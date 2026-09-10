/* SPDX-License-Identifier: MIT
 *
 * t234-shim.S — Phase 3b, milestone M0: the first thing that runs natively on
 * the Jetson Orin Nano after kexec hands control away from Linux.
 *
 * Project: qnx-linux-dual-vm-proxy.  Plan: docs/orin-native-port-plan.md §3.3.
 * This file is our own code.  It contains nothing from QNX, NVIDIA or Linux.
 *
 * WHAT IT IS
 *   An 8 KiB page prefixed to a QNX IFS.  Byte 0 carries the 64-byte arm64
 *   Image header that both kexec syscalls insist on (they check the magic and
 *   nothing else on this board), so the pair loads as one "kernel".  The shim
 *   then reports the machine state Linux left behind, normalises the few EL2
 *   bits the QNX startup library does not touch, and either resets, hangs or
 *   jumps into the IFS.
 *
 * WHY A SHIM AT ALL
 *   A QNX raw IFS starts with its own preboot stub, so the Image header cannot
 *   be overlaid on it — bytes 0x00-0x0B are already the stub's instructions.
 *   Prefixing a page is the only way to satisfy kexec without touching a
 *   shipped byte.
 *
 * WHAT IT PROVES ON ITS FIRST RUN (all of M0's open questions at once)
 *   - the exception level kexec actually enters at   (plan unknown #1)
 *   - whether the SPE still drains the TCU mailbox once Linux is gone  (#2)
 *   - whether a non-Linux payload can write the ramoops console zone and have
 *     pstore surface it after the reset                                (#7)
 *   - what Linux left armed: HCR/SCTLR/timers, and both watchdogs      (K9)
 *   - where kexec actually placed us                                   (#6)
 *
 * OUTPUT — two channels, both written for every byte:
 *   1. Tegra Combined UART, one byte per HSP mailbox word.  The poll is bounded
 *      by a system-counter deadline, so a dead SPE degrades to silence instead
 *      of a hang, and the bytes it swallowed are counted and reported.
 *   2. The ramoops console zone at 0x2_72770000.  We keep the DBGC signature
 *      word and maintain start/size as we go, so whatever was printed before a
 *      fault still surfaces as /sys/fs/pstore/console-ramoops-0 after the
 *      board comes back.  Addresses and format verified 2026-09-09, see
 *      results/orin-native-port/20260909T1100Z/blackbox-verified.md.
 *
 * CONSTRAINTS THIS CODE HONOURS
 *   MMU and caches are off at entry, so every access is Device-nGnRnE and no
 *   cache maintenance is needed for our own stores; there is no stack, so
 *   helpers return through dedicated registers rather than a frame; the code
 *   is position-independent up to the landing check, which is the point.
 *
 * REGISTER CONVENTION (no stack — do not reuse these)
 *   x19 run address of _start          x20 DTB physical address (entry x0)
 *   x21 TCU TX mailbox                 x22 black-box write cursor
 *   x23 black-box zone base            x24 CurrentEL, already shifted
 *   x25 TCU mailbox word sampled before our first write / exception index
 *   x26 puthex64 nibble counter        x27 puthex64 return
 *   x28 puts return                    x16 TCU bytes dropped
 *   x9-x14 clobbered by putc
 *
 * BUILD    see build-shim.sh; assemble with ntoaarch64-gcc -c (it runs cpp).
 */

#ifndef SHIM_MODE
#define SHIM_MODE 'p'                   /* p=probe (print+reset), h=hang, j=jump */
#endif
#ifndef IMAGE_SIZE
#define IMAGE_SIZE 0x200000             /* patched by build-shim.sh for shim+IFS */
#endif
#ifndef LINK_ADDR
#define LINK_ADDR 0x80080000            /* where kexec is expected to land us */
#endif
#ifndef PAYLOAD_OFF
#define PAYLOAD_OFF 0x2000              /* IFS sits right after this 8 KiB page */
#endif
#ifndef SHIM_WDT_START
#define SHIM_WDT_START 0                /* 1 = restart WDT0's counter before handing over */
#endif

#define PSCI_SYSTEM_RESET  0x84000009
#define WDT0_BASE          0x02190000   /* TKE WDT0: WDTCR at +0, WDTSR at +4 */
#define WDT1_BASE          0x021A0000

	.arch	armv8-a
	.section .text.head, "ax"
	.globl	_start

/* ------------------------------------------------------------------ *
 * 0x00: the arm64 Image header.  Reserved fields stay zero: kexec only
 * checks the magic, but a header that lies about itself is a bad habit
 * and future kernels do validate more.
 * ------------------------------------------------------------------ */
_start:
	b	shim_body			/* code0: entry                */
	.long	0				/* code1                       */
	.quad	0x80000				/* text_offset                 */
	.quad	IMAGE_SIZE			/* image_size                  */
	.quad	0				/* flags: LE, 4K, anywhere     */
	.quad	0				/* res2                        */
	.quad	0				/* res3                        */
	.quad	0				/* res4                        */
	.ascii	"ARM\x64"			/* magic, offset 0x38          */
	.long	0				/* res5                        */

/* ------------------------------------------------------------------ */
shim_body:
	mov	x20, x0				/* DTB physical address        */
	adr	x19, _start			/* where we really landed      */
	mov	x16, xzr			/* TCU bytes dropped so far    */

	/* TCU TX mailbox = AON HSP shared mailbox 1 = 0x0C168000 */
	movz	x21, #0x8000
	movk	x21, #0x0C16, lsl #16

	/* ramoops console zone = 0x2_72770000 (carveout + 0x180000) */
	movz	x23, #0x0000
	movk	x23, #0x7277, lsl #16
	movk	x23, #0x0002, lsl #32

	/* Sample the mailbox before we ever write it: a non-zero word here
	 * means the SPE has not drained what Linux left, which is the first
	 * thing worth knowing if the console turns out to be silent. */
	ldr	w25, [x21]

	/* Clean+invalidate the first 4 KiB of the console zone.  Our stores
	 * are Device (MMU off) and never allocate, but a stale dirty line
	 * left by Linux could be evicted on top of them later. */
	mov	x9, x23
	add	x10, x23, #0x1000
1:	dc	civac, x9
	add	x9, x9, #64
	cmp	x9, x10
	b.lo	1b
	dsb	sy
	isb

	/* Black-box header: keep DBGC, restart the log at the data offset. */
	movz	w9, #0x4244
	movk	w9, #0x4347, lsl #16		/* 0x43474244 = 'D','B','G','C' */
	str	w9, [x23]
	str	wzr, [x23, #4]			/* start */
	str	wzr, [x23, #8]			/* size  */
	add	x22, x23, #12			/* write cursor */

	/* CurrentEL first: reading or writing any EL2 register from EL1
	 * traps, so nothing EL2-flavoured may happen before this test. */
	mrs	x2, CurrentEL
	lsr	x2, x2, #2
	and	x24, x2, #3

	cmp	x24, #2
	b.ne	no_vectors
	adr	x9, vectors			/* our vectors: every fault now  */
	msr	vbar_el2, x9			/* prints and resets, not silence */
	isb
no_vectors:

	adr	x1, s_banner
	bl	puts
	add	w0, w24, #'0'
	bl	putc

	cmp	x24, #2
	b.eq	bank_el2

	/* Kill criterion (a): never jump into QNX from the wrong level. */
	adr	x1, s_el_bad
	bl	puts
	b	reset

/* ---- the state Linux left, printed as one line ------------------- */
bank_el2:
	adr	x1, s_hcr
	bl	puts
	mrs	x2, hcr_el2
	bl	puthex64

	adr	x1, s_sctlr2
	bl	puts
	mrs	x2, sctlr_el2
	bl	puthex64

	adr	x1, s_mmfr1
	bl	puts
	mrs	x2, id_aa64mmfr1_el1		/* VH field: EL2-host viability */
	bl	puthex64

	adr	x1, s_mpidr
	bl	puts
	mrs	x2, mpidr_el1
	bl	puthex64

	adr	x1, s_cntfrq
	bl	puts
	mrs	x2, cntfrq_el0
	bl	puthex64

	adr	x1, s_cnthctl
	bl	puts
	mrs	x2, cnthctl_el2
	bl	puthex64

	adr	x1, s_cnthpctl
	bl	puts
	mrs	x2, cnthp_ctl_el2
	bl	puthex64

	adr	x1, s_mdcr
	bl	puts
	mrs	x2, mdcr_el2
	bl	puthex64

	/* Both watchdogs, control and status.  K9: WDT0 is armed by systemd
	 * at 2 minutes, so these two words decide whether M3/M4 need
	 * -Wdisable or a kicker, and whether an un-petted hang recovers. */
	adr	x1, s_wdt0
	bl	puts
	movz	x9, #0x0000
	movk	x9, #0x0219, lsl #16		/* WDT0_BASE */
	ldr	w2, [x9]
	bl	puthex64
	mov	w0, #'/'
	bl	putc
	movz	x9, #0x0000
	movk	x9, #0x0219, lsl #16
	ldr	w2, [x9, #4]
	bl	puthex64

	adr	x1, s_wdt1
	bl	puts
	movz	x9, #0x0000
	movk	x9, #0x021A, lsl #16		/* WDT1_BASE */
	ldr	w2, [x9]
	bl	puthex64
	mov	w0, #'/'
	bl	putc
	movz	x9, #0x0000
	movk	x9, #0x021A, lsl #16
	ldr	w2, [x9, #4]
	bl	puthex64

	adr	x1, s_txmb
	bl	puts
	mov	x2, x25				/* sampled before our first write */
	bl	puthex64

	adr	x1, s_pc
	bl	puts
	mov	x2, x19
	bl	puthex64

	adr	x1, s_x0
	bl	puts
	mov	x2, x20
	bl	puthex64

	/* If x0 is not a DTB this load faults, and the vectors say so —
	 * which is itself the answer.  d00dfeed stored big-endian reads
	 * back as 0xedfe0dd0 here. */
	adr	x1, s_dtbmagic
	bl	puts
	ldr	w2, [x20]
	bl	puthex64

	mov	w0, #'\n'
	bl	putc

/* ---- did kexec put us where the arithmetic said? ------------------ */
	movz	x9, #(LINK_ADDR & 0xffff)
	movk	x9, #(LINK_ADDR >> 16), lsl #16
	cmp	x19, x9
	b.eq	landing_ok

	adr	x1, s_badland
	bl	puts
	mov	x2, x19
	bl	puthex64
	adr	x1, s_expect
	bl	puts
	movz	x2, #(LINK_ADDR & 0xffff)
	movk	x2, #(LINK_ADDR >> 16), lsl #16
	bl	puthex64
	mov	w0, #'\n'
	bl	putc
	b	reset				/* never jump blind */
landing_ok:

/* ---- normalise only what the QNX library does not ----------------- *
 * at_el2 (lib/aarch64/_start_el1.S) already handles SCTLR_EL2 M/C/I,
 * HCR_EL2 wholesale, CPTR_EL2, CNTHCTL_EL2, VMPIDR/VPIDR, CNTVOFF,
 * VTTBR and ICC_SRE_EL2, on the boot CPU and on every secondary.  What
 * it does not do is disarm the timer Linux left running or clear the
 * debug/trap registers, so that is all we touch.  Clearing E2H here is
 * for the hand-off only; hyp_enable_el2_host re-asserts it later.
 * ------------------------------------------------------------------ */
	msr	cntp_ctl_el0, xzr		/* aliases CNTHP_CTL while E2H=1 */
	msr	cntv_ctl_el0, xzr		/* aliases CNTHV_CTL while E2H=1 */
	isb
	movz	x9, #0x0000
	movk	x9, #0x8000, lsl #16		/* HCR_EL2 = RW only            */
	msr	hcr_el2, x9
	isb
	msr	cnthp_ctl_el2, xzr		/* now the real EL2 views       */
	msr	cntp_ctl_el0, xzr
	msr	cntv_ctl_el0, xzr
	msr	mdcr_el2, xzr
	msr	hstr_el2, xzr
	msr	ich_hcr_el2, xzr
	isb

	adr	x1, s_norm
	bl	puts

#if SHIM_WDT_START
/* ---- restart the watchdog counter ------------------------------------ *
 * The board arrives with WDT0 configured — systemd set it to two minutes —
 * but the hang test proved it does not actually fire after this hand-over,
 * so systemd almost certainly hands it back on its shutdown path. The
 * configuration is still in the register though, so this tries the cheapest
 * possible thing: unlock and issue the start command, reusing whatever
 * period Linux left rather than programming a timer source blind.
 *
 * If it takes, every hang from here on becomes an automatic warm reset,
 * which is the one kind of reset the black box survives. If it does not,
 * the status word printed afterwards says so and nothing is worse than
 * before.
 * --------------------------------------------------------------------- */
	movz	x9, #0x0000
	movk	x9, #0x0219, lsl #16		/* WDT0 */
	movz	w10, #0xc45a			/* unlock pattern */
	str	w10, [x9, #0x0c]
	mov	w10, #1				/* start the counter */
	str	w10, [x9, #0x08]
	dsb	sy

	adr	x1, s_wdtstart
	bl	puts
	movz	x9, #0x0000
	movk	x9, #0x0219, lsl #16
	ldr	w2, [x9]			/* CR after the write */
	bl	puthex64
	mov	w0, #'/'
	bl	putc
	movz	x9, #0x0000
	movk	x9, #0x0219, lsl #16
	ldr	w2, [x9, #4]		/* SR after the write */
	bl	puthex64
	mov	w0, #'\n'
	bl	putc
#endif

	/* How many bytes the TCU swallowed.  Zero means the SPE is alive; a
	 * count equal to everything printed means the console is dead and only
	 * the black box carries this run — which is a result, not a failure. */
	adr	x1, s_drops
	bl	puts
	mov	x2, x16
	bl	puthex64
	mov	w0, #'\n'
	bl	putc

/* ---- what to do next --------------------------------------------- */
#if SHIM_MODE == 'j'
	adr	x1, s_jump
	bl	puts
	mov	x0, x20				/* QNX startup wants the DTB    */
	mov	x1, xzr
	mov	x2, xzr
	mov	x3, xzr
	add	x9, x19, #PAYLOAD_OFF
	br	x9
#elif SHIM_MODE == 'h'
	adr	x1, s_hang
	bl	puts
	/* Deliberate: nothing pets WDT0 from here.  If systemd left it armed
	 * the board resets on its own in ~2 minutes and unattended recovery
	 * is proven; if it does not, this needs a power cycle and we know
	 * that too. */
2:	wfi
	b	2b
#else
	adr	x1, s_probe
	bl	puts
	b	reset
#endif

/* ------------------------------------------------------------------ *
 * reset — PSCI SYSTEM_RESET.  Works from EL1 and EL2 alike.
 * ------------------------------------------------------------------ */
reset:
	dsb	sy
	isb
	movz	w0, #(PSCI_SYSTEM_RESET & 0xffff)
	movk	w0, #(PSCI_SYSTEM_RESET >> 16), lsl #16
	smc	#0
3:	wfi
	b	3b

/* ------------------------------------------------------------------ *
 * putc — w0 = byte.  Writes the black box first (it cannot fail) and
 * the TCU second (it can).  Clobbers x9-x12; advances x22.
 * ------------------------------------------------------------------ */
putc:
	/* Black box first — it cannot fail — but never past the zone's data
	 * capacity (console-size 0x80000 less the 12-byte header).  Nothing
	 * this shim prints comes close, but the same routine is meant to stay
	 * live through QNX startup, and running off the end would write into
	 * memory outside the reserved carveout. */
	sub	x9, x22, x23
	movz	x10, #0xfff0
	movk	x10, #0x0007, lsl #16		/* 0x0007fff0                   */
	cmp	x9, x10
	b.hs	13f				/* zone full: stop mirroring    */
	strb	w0, [x22], #1
	sub	x9, x22, x23
	sub	w9, w9, #12			/* bytes of payload so far      */
	str	w9, [x23, #4]			/* start */
	str	w9, [x23, #8]			/* size  */
	dsb	sy

	/* TCU second — it can fail.  The bound is a real deadline read off the
	 * system counter, not an instruction count: if the SPE has stopped
	 * draining the mailbox, an uncalibrated spin per byte could eat a
	 * meaningful slice of WDT0's two minutes over a whole bank line. */
13:	mrs	x13, cntfrq_el0
	lsr	x13, x13, #6			/* ~15.6 ms at 31.25 MHz        */
	mrs	x14, cntpct_el0
	add	x13, x13, x14			/* deadline                     */
11:	ldr	w11, [x21]
	tbz	w11, #31, 12f
	mrs	x14, cntpct_el0
	cmp	x14, x13
	b.lo	11b
	add	x16, x16, #1			/* the SPE is not draining:     */
	ret					/* counted, not silently lost   */
12:	and	w11, w0, #0xff
	movz	w12, #0x8500, lsl #16		/* FULL | Flush | count=1       */
	orr	w11, w11, w12
	str	w11, [x21]
	ret

/* puts — x1 = NUL-terminated string.  Returns through x28. */
puts:
	mov	x28, x30
6:	ldrb	w0, [x1], #1
	cbz	w0, 7f
	bl	putc
	b	6b
7:	ret	x28

/* puthex64 — x2 = value, printed as 16 nibbles.  Returns through x27. */
puthex64:
	mov	x27, x30
	mov	x26, #60
8:	lsr	x0, x2, x26
	and	x0, x0, #0xf
	cmp	w0, #9
	b.hi	9f
	add	w0, w0, #'0'
	b	10f
9:	add	w0, w0, #('a' - 10)
10:	bl	putc
	subs	x26, x26, #4
	b.ge	8b
	ret	x27

/* ------------------------------------------------------------------ */
s_banner:	.asciz	"\nT234-SHIM EL="
s_el_bad:	.asciz	" EL!=2 abort\n"
s_hcr:		.asciz	" HCR="
s_sctlr2:	.asciz	" SCTLR2="
s_mmfr1:	.asciz	" MMFR1="
s_mpidr:	.asciz	" MPIDR="
s_cntfrq:	.asciz	" CNTFRQ="
s_cnthctl:	.asciz	" CNTHCTL="
s_cnthpctl:	.asciz	" CNTHPCTL="
s_mdcr:		.asciz	" MDCR="
s_wdt0:		.asciz	" WDT0="
s_wdt1:		.asciz	" WDT1="
s_txmb:		.asciz	" TXMB="
s_pc:		.asciz	" PC="
s_x0:		.asciz	" X0="
s_dtbmagic:	.asciz	" DTBMAGIC="
s_badland:	.asciz	"BAD-LANDING pc="
s_expect:	.asciz	" expect="
s_norm:		.asciz	"NORMALISED"
s_wdtstart:	.asciz	" WDT0-RESTARTED CR/SR="
s_drops:	.asciz	" TCUDROPS="
s_probe:	.asciz	"PROBE-RESET\n"
s_hang:		.asciz	"HANG (waiting on WDT0)\n"
s_jump:		.asciz	"JUMP\n"
s_exc:		.asciz	"\nEXC "
s_esr:		.asciz	" ESR="
s_elr:		.asciz	" ELR="
s_far:		.asciz	" FAR="

/* ------------------------------------------------------------------ *
 * Vector table.  VBAR_EL2 needs 2 KiB alignment and the table is 2 KiB;
 * each of the 16 entries has 128 bytes, so each one only records which
 * it was and jumps to the common handler.
 *
 * These stay installed all the way through QNX startup: the library
 * writes vbar_el1 (cstart.S, smp_start.S) and touches vbar_el2 only
 * under -Q enable,el1-host.  So an early fault inside startup still
 * prints here instead of vanishing.
 * ------------------------------------------------------------------ */
	.macro	VEC n
	.balign	0x80
	mov	w25, #\n
	b	exc_common
	.endm

	.balign	0x800
vectors:
	VEC 0			/* Current EL, SP0:   sync, irq, fiq, serror */
	VEC 1
	VEC 2
	VEC 3
	VEC 4			/* Current EL, SPx:   the realistic ones     */
	VEC 5
	VEC 6
	VEC 7
	VEC 8			/* Lower EL, aarch64                        */
	VEC 9
	VEC 10
	VEC 11
	VEC 12			/* Lower EL, aarch32                        */
	VEC 13
	VEC 14
	VEC 15

	.balign	0x80				/* clear of every vector slot */
exc_common:
	adr	x1, s_exc
	bl	puts
	mov	x2, x25
	bl	puthex64
	adr	x1, s_esr
	bl	puts
	mrs	x2, esr_el2
	bl	puthex64
	adr	x1, s_elr
	bl	puts
	mrs	x2, elr_el2
	bl	puthex64
	adr	x1, s_far
	bl	puts
	mrs	x2, far_el2
	bl	puthex64
	mov	w0, #'\n'
	bl	putc
	b	reset

	.balign	0x2000				/* the page is exactly 8 KiB */
_shim_end:
