/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Kernel debug callouts for the Tegra Combined UART.
 *
 * These are what procnto uses once startup has handed over: kprintf, the crash
 * dump, and the kernel debugger all reach the wire through here. They run with
 * the MMU on and interrupts off, patched at startup time with the virtual
 * address of the mailbox, which is why each begins with the four-instruction
 * movz/movk sequence the patcher rewrites.
 *
 * Transmit and receive are separate mailboxes in different HSP blocks, so each
 * callout carries its own patcher rather than sharing one — that avoids having
 * to know the runtime layout of the library's debug-device structure, which is
 * the sort of thing that changes between releases.
 *
 * The receive side deserves a word, because copying NVIDIA's own reference
 * implementation without understanding it produces something that never
 * releases the mailbox. That code consumes one byte per call and, when bytes
 * remain, writes the word back with the FULL bit still set — using the hardware
 * register as its own scratch buffer between calls. Only the call that takes the
 * last byte writes a literal zero, and that zero is the release. The same trick
 * is used here, deliberately: it means no read-write storage has to be
 * allocated for the callout, and the three-byte case costs nothing.
 */

#include <aarch64/callout.ah>
#include "t234_startup.h"

	.text
	.align 2

/*
 * Patchers. Each maps its own mailbox page and patches the caller's address
 * sequence with the virtual address it gets back.
 *
 * Called with:
 *   x0 - syspage paddr        x1 - vaddr of callout
 *   x2 - offset from syspage to the callout routine
 *   x3 - offset from syspage to rw storage (unused, rw_size is 0)
 *   x4 - patch data           x5 - callout_rtn
 */
patch_tcu_tx:
	sub		sp, sp, #16
	stp		x19, x30, [sp]
	add		x19, x0, x2			// address of the callout routine

	mov		x0, #0x1000
	movz	x1, #(T234_TCU_TX & 0xffff)
	movk	x1, #(T234_TCU_TX >> 16), lsl #16
	bl		callout_io_map

	CALLOUT_PATCH	x19, w6, w7		// x19 advances past the 4 patched words

	/*
	 * The same callout carries a second address: the black box. Without it,
	 * every byte procnto prints exists only on a wire nobody is reading, and
	 * a kernel that comes up perfectly is indistinguishable from one that
	 * never started. CALLOUT_PATCH left x19 pointing at the next sequence.
	 */
	mov		x0, #T234_BB_MAP
	movz	x1, #(T234_BB_BASE & 0xffff)
	movk	x1, #((T234_BB_BASE >> 16) & 0xffff), lsl #16
	movk	x1, #((T234_BB_BASE >> 32) & 0xffff), lsl #32
	bl		callout_io_map

	CALLOUT_PATCH	x19, w6, w7

	ldp		x19, x30, [sp]
	add		sp, sp, #16
	ret

patch_tcu_rx:
	sub		sp, sp, #16
	stp		x19, x30, [sp]
	add		x19, x0, x2

	mov		x0, #0x1000
	movz	x1, #(T234_TCU_RX & 0xffff)
	movk	x1, #(T234_TCU_RX >> 16), lsl #16
	bl		callout_io_map

	CALLOUT_PATCH	x19, w6, w7
	ldp		x19, x30, [sp]
	add		sp, sp, #16
	ret

/*
 * void display_char_tcu(struct syspage_entry *, char)
 *   x0 - syspage   w1 - character
 *
 * Wait for the SPE to take the previous word, then write this one. The wait is
 * bounded: a dead SPE must cost a dropped character, never a hung kernel.
 */
CALLOUT_START(display_char_tcu, 0, patch_tcu_tx)
	mov		x7, #0xabcd			// TX mailbox vaddr (patched)
	movk	x7, #0xabcd, lsl #16
	movk	x7, #0xabcd, lsl #32
	movk	x7, #0xabcd, lsl #48

	mov		x6, #0xabcd			// black box vaddr (patched)
	movk	x6, #0xabcd, lsl #16
	movk	x6, #0xabcd, lsl #32
	movk	x6, #0xabcd, lsl #48

	/*
	 * Mirror first, because the mailbox is the half that can fail. The zone's
	 * own length word is the cursor — the same trick the region's format
	 * already uses — so this needs no read-write storage of its own and
	 * appends to whatever the shim and startup wrote before it.
	 */
	ldr		w2, [x6]
	movz	w3, #0x4244
	movk	w3, #0x4347, lsl #16		// 'D','B','G','C'
	cmp		w2, w3
	b.ne	2f					// not our zone: leave it alone
	ldr		w2, [x6, #8]			// bytes already there
	movz	w3, #0xfff0			// what is mapped, less a margin
	cmp		w2, w3
	b.hs	2f					// full: stop rather than run off the map
	add		x4, x6, x2
	strb	w1, [x4, #12]
	add		w2, w2, #1
	str		w2, [x6, #4]
	str		w2, [x6, #8]
2:
	mov		x2, #0x100000		// bounded poll
0:	ldr		w3, [x7]
	tbz		w3, #31, 1f			// FULL clear: the mailbox is ours
	subs	x2, x2, #1
	b.ne	0b
	ret							// gave up; drop the character

1:	and		w3, w1, #0xff
	movz	w4, #0x8500, lsl #16	// FULL | Flush | count = 1
	orr		w3, w3, w4
	str		w3, [x7]
	ret
CALLOUT_END(display_char_tcu)

/*
 * int poll_key_tcu(struct syspage_entry *)
 *   returns the next character, or -1 when nothing is waiting.
 *
 * Non-blocking by construction: test FULL first and return immediately if it
 * is clear. Never call anything shaped like the reference Read(), which spins
 * until it has the bytes it wants.
 */
CALLOUT_START(poll_key_tcu, 0, patch_tcu_rx)
	mov		x7, #0xabcd			// RX mailbox vaddr (patched)
	movk	x7, #0xabcd, lsl #16
	movk	x7, #0xabcd, lsl #32
	movk	x7, #0xabcd, lsl #48

	ldr		w2, [x7]
	tbz		w2, #31, 3f			// FULL clear: nothing to read

	ubfx	w3, w2, #24, #2		// byte count, 1..3
	cbz		w3, 2f				// FULL set with no bytes: stale, release it

	ubfx	w0, w2, #0, #8		// the byte we return
	subs	w3, w3, #1
	b.eq	2f					// that was the last one: release

	/*
	 * Bytes remain. Shift them down and write the word back with FULL still
	 * set, preserving the flush bits, so the next call finds them without the
	 * SPE having to do anything.
	 */
	lsr		w4, w2, #8
	and		w4, w4, #0xffff		// bytes 1 and 2 become 0 and 1
	bic		w5, w2, #0xffffff	// keep FULL, flush bits and reserved
	bic		w5, w5, #0x3000000	// clear the old count
	orr		w5, w5, w4
	orr		w5, w5, w3, lsl #24	// new count
	str		w5, [x7]
	ret

2:	str		wzr, [x7]			// literal zero is the release
	ret

3:	mov		x0, #-1
	ret
CALLOUT_END(poll_key_tcu)

/*
 * int break_detect_tcu(struct syspage_entry *)
 *
 * A mailbox has no line state, so there is no break condition to detect and
 * nothing this could usefully return but zero. Present because the debug-device
 * table wants three callouts.
 *
 * No patcher, deliberately. This routine used to name patch_tcu_tx, which
 * rewrites two four-instruction address sequences starting wherever it is
 * pointed: eight instructions, into a routine of two. That turned the return
 * value into part of the mailbox address, turned the ret into some other
 * instruction, and wrote six more words past the end of the routine. M1 got away
 * with it only because this is the last callout the library copies, so the
 * overrun fell past the callout area rather than onto another callout, and
 * nothing visibly called it. The library's own dummy debug device declares its
 * break_detect the same way as here, with a null patcher, which the copy loop
 * skips.
 */
CALLOUT_START(break_detect_tcu, 0, 0)
	mov		x0, #0
	ret
CALLOUT_END(break_detect_tcu)
