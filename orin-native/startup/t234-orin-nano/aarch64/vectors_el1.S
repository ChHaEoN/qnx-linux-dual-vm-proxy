/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * EL1 exception vectors for startup, because the library's are a silent trap.
 *
 * The startup library installs `vbar_default` into VBAR_EL1, and every one of
 * its sixteen slots is a branch to itself. That is deliberate and reasonable:
 * it stops the machine with ELR_EL1 and ESR_EL1 intact for a JTAG debugger to
 * read. There is no debugger on this board and there is not going to be one.
 *
 * It also covers far more ground than it looks. Under `-Q disable` the library
 * drops to EL1 inside hypervisor_init, which main() calls before init_smp,
 * init_mmu, init_intrinfo and init_qtime — so the entire first-ever bring-up of
 * this port's interrupt controller, MMU and timer runs at EL1 with those
 * vectors installed. The shim's own EL2 vectors, which do print and reset, stop
 * applying the moment the CPU drops: EL1 exceptions are not routed to EL2
 * unless HCR_EL2 says so, and under `-Q disable` nothing sets those bits.
 *
 * So without this file, any fault in the least-tested code in the project ends
 * as a branch-to-self: no output, no reset, and — because this board's watchdog
 * does not fire after the kexec hand-over — a power cycle, which wipes the DRAM
 * region holding everything printed up to that point. A diagnosed failure
 * becomes an undiagnosable one.
 *
 * With it, the same fault prints its cause and resets warm, which is the one
 * kind of reset the black box survives.
 *
 * The table is installed from main() before hypervisor_init runs, so there is
 * no window where the library's version is the live one after the drop. A
 * secondary core gets the same table from board_smp_adjust_num, which the
 * library calls after writing vbar_default (lib/aarch64/smp_start.S:44-45,
 * :66) and before that core's own hypervisor_init drops it (:73).
 *
 * Two guards sit in front of the C handler, because a handler that faults
 * while reporting a fault would otherwise loop without a word:
 *
 *   - MMU on. Once vstart has enabled translation, TTBR0 maps only the startup
 *     image (lib/aarch64/aarch64_map.c:111-118, lib/aarch64/vstart.S:68-74), so
 *     the mailbox and the black box are probably unmapped and printing would
 *     fault again. With the MMU on, the handler resets without printing.
 *   - Nesting. A second entry, from any CPU, resets without printing. The
 *     flag is one word shared by all CPUs rather than one per CPU, which keeps
 *     the guard free of indexing: a second CPU faulting after a first loses
 *     its own text, and the first CPU's text is already in the black box.
 *
 * Both reset paths use constants and one SMC, no memory. The SMC reaches EL3
 * from EL1 because at_el2 leaves HCR_EL2.TSC clear
 * (lib/aarch64/_start_el1.S:148-156), and from EL2 unconditionally.
 *
 * The EL2 table below is installed only by secondary cores, from
 * t234_ap_entry, before they run any other EL2 code. CPU0 keeps the shim's EL2
 * vectors: their common path needs registers the shim's own body sets up
 * (orin-native/shim/t234-shim.S:102-138), so they cannot be shared.
 *
 * Nothing in this file has run on a secondary core.
 */

#include <aarch64/callout.ah>

	.text
	.align 2

/*
 * void t234_install_el1_vectors(void)
 *
 * Called from C at EL2, before the library drops. Writing VBAR_EL1 from EL2 is
 * allowed and is the only chance to get ahead of the drop.
 */
	.globl	t234_install_el1_vectors
t234_install_el1_vectors:
	adr	x0, t234_el1_vectors
	msr	vbar_el1, x0
	isb
	ret

/*
 * Each slot records which vector it was and branches to the common handler.
 * There is a stack here — cstart established one before any of this is
 * reachable, and smp_start does the same for a secondary before
 * board_smp_adjust_num installs the table — so the handler can call C, which is
 * what makes the message go through the same kprintf path as everything else
 * and therefore into both the mailbox and the black box.
 */
	.macro	VEC1 idx
	.balign	0x80
	mov	x0, #\idx
	b	t234_el1_common
	.endm

	.balign	0x800
t234_el1_vectors:
	VEC1 0				/* Current EL, SP0 */
	VEC1 1
	VEC1 2
	VEC1 3
	VEC1 4				/* Current EL, SPx — where startup's own faults land */
	VEC1 5
	VEC1 6
	VEC1 7
	VEC1 8				/* Lower EL, aarch64 */
	VEC1 9
	VEC1 10
	VEC1 11
	VEC1 12				/* Lower EL, aarch32 */
	VEC1 13
	VEC1 14
	VEC1 15

	.balign	0x80
t234_el1_common:
	mrs	x9, sctlr_el1
	tbnz	x9, #0, t234_fault_reset	/* MMU on: printing would fault again */
	adr	x9, t234_fault_nest
	ldr	w10, [x9]
	cbnz	w10, t234_fault_reset		/* already reporting a fault */
	mov	w10, #1
	str	w10, [x9]
	mrs	x1, esr_el1
	mrs	x2, elr_el1
	mrs	x3, far_el1
	b	t234_el1_fault		/* noreturn: prints, then resets */

/*
 * EL2 vectors for secondary cores. Same shape as the EL1 table; the handler
 * also receives SPSR_EL2, which says where the exception came from.
 *
 * The stack a handler here uses is the board's small one from ap_entry.S until
 * smp_start installs the library's; after the drop to EL1, SP_EL2 keeps the
 * library stack value it had.
 */
	.macro	VEC2 idx
	.balign	0x80
	mov	x0, #\idx
	b	t234_el2_common
	.endm

	.globl	t234_el2_vectors
	.balign	0x800
t234_el2_vectors:
	VEC2 0				/* Current EL, SP0 */
	VEC2 1
	VEC2 2
	VEC2 3
	VEC2 4				/* Current EL, SPx — the trampoline and at_el2 */
	VEC2 5
	VEC2 6
	VEC2 7
	VEC2 8				/* Lower EL, aarch64 */
	VEC2 9
	VEC2 10
	VEC2 11
	VEC2 12				/* Lower EL, aarch32 */
	VEC2 13
	VEC2 14
	VEC2 15

	.balign	0x80
t234_el2_common:
	mrs	x9, sctlr_el2
	tbnz	x9, #0, t234_fault_reset	/* EL2 MMU on: not this startup's state */
	adr	x9, t234_fault_nest
	ldr	w10, [x9]
	cbnz	w10, t234_fault_reset
	mov	w10, #1
	str	w10, [x9]
	mrs	x1, esr_el2
	mrs	x2, elr_el2
	mrs	x3, far_el2
	mrs	x4, spsr_el2
	b	t234_el2_fault		/* noreturn: prints, then resets */

/*
 * PSCI SYSTEM_RESET (0x84000009, lib/public/aarch64/psci.h:49) with no memory
 * access at all, for the cases where touching memory is the problem.
 */
	.globl	t234_fault_reset
t234_fault_reset:
	movz	w0, #0x0009
	movk	w0, #0x8400, lsl #16
	mov	x1, #0
	mov	x2, #0
	mov	x3, #0
	smc	#0
	b	.

	.data
	.balign	4
t234_fault_nest:
	.word	0
