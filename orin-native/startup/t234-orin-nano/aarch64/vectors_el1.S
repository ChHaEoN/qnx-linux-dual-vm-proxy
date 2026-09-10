/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * EL1 and EL2 exception vectors for startup, because the library's are a
 * silent trap and the shim's cannot be relied on.
 *
 * The startup library installs `vbar_default` into VBAR_EL1, and every one of
 * its sixteen slots is a branch to itself. That is deliberate and reasonable:
 * it stops the machine with ELR_EL1 and ESR_EL1 intact for a JTAG debugger to
 * read. There is no debugger on this board and there is not going to be one.
 *
 * Which table a startup fault lands in depends on the -Q mode:
 *
 *   - -Q disable, and -Q enable,el1-host: CPU0 and each secondary drop to EL1
 *     inside their own hypervisor_init, which main() calls before init_smp,
 *     init_mmu, init_intrinfo and init_qtime — so the bring-up of this port's
 *     interrupt controller, MMU and timer runs at EL1, and its faults land in
 *     t234_el1_vectors. EL1 exceptions are not routed to EL2 unless HCR_EL2
 *     says so, and under -Q disable nothing sets those bits.
 *   - -Q enable,el2-host: no core ever runs at EL1. hyp_enable_el2_host sets
 *     E2H and TGE (lib/aarch64/hypervisor_enable.S:24-34), every startup fault
 *     on every core lands in t234_el2_vectors, and VBAR_EL1 is written but
 *     never used.
 *
 * So without this file, any fault in the least-tested code in the project ends
 * as a branch-to-self or a re-fault loop: no output, no reset, and — because
 * this board's watchdog does not fire after the kexec hand-over — a power
 * cycle, which wipes the DRAM region holding everything printed up to that
 * point. A diagnosed failure becomes an undiagnosable one.
 *
 * With it, the same fault prints its cause and resets warm, which is the one
 * kind of reset the black box survives.
 *
 * The EL1 table is installed from main() before hypervisor_init runs, so there
 * is no window where the library's version is the live one after the drop. A
 * secondary core gets the same table from board_smp_adjust_num, which the
 * library calls after writing vbar_default (lib/aarch64/smp_start.S:44-45,
 * :66) and before that core's own hypervisor_init (:73). Both calls precede
 * hypervisor_init by construction, so they reach the real VBAR_EL1 in every
 * mode, never VBAR_EL2 through the E2H alias.
 *
 * Two guards sit in front of each C handler, because a handler that faults
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
 * The EL2 table is installed on every secondary by t234_ap_entry, and on CPU0
 * by board_init (main.c) in every -Q mode. CPU0 does not keep the shim's EL2
 * vectors: their printer depends on x21-x23 (orin-native/shim/t234-shim.S:
 * 404-435), which _main's own code has already reused by the time it calls
 * board_init, and their page lies outside the only low mapping once vstart
 * turns the MMU on (lib/aarch64/init_mmu.c:159-161).
 *
 * What has run on the board: M1 and M2 installed the EL1 table on every core
 * they used and the EL2 table on the five secondaries, all under -Q disable.
 * No fault reached either handler in any of those runs, so the handlers
 * themselves have not run. t234_install_el2_vectors is new for M1b and has not
 * run.
 */

#include <aarch64/callout.ah>

	.text
	.align 2

/*
 * void t234_install_el1_vectors(void)
 *
 * Called from C at EL2, before the library drops: from main() on CPU0 and from
 * board_smp_adjust_num on a secondary. Writing VBAR_EL1 from EL2 is allowed and
 * is the only chance to get ahead of the drop. Both callers run before
 * hypervisor_init, while E2H is clear, so this is the real VBAR_EL1; under
 * el2-host the table is then never used.
 */
	.globl	t234_install_el1_vectors
t234_install_el1_vectors:
	adr	x0, t234_el1_vectors
	msr	vbar_el1, x0
	isb
	ret

/*
 * void t234_install_el2_vectors(void)
 *
 * Called from board_init on CPU0, first thing in _main (lib/_main.c:126),
 * with cstart's stack in place (lib/aarch64/cstart.S:88-90). Replaces the
 * shim's EL2 vectors. Their printer depends on x21-x23
 * (orin-native/shim/t234-shim.S:404-435), and _main's own code has already
 * reused x21 and x22 by the time it calls board_init. Their page also leaves
 * the only low mapping once vstart turns the MMU on
 * (lib/aarch64/init_mmu.c:159-161).
 * At EL1 (never on this board: kexec enters at EL2) it does nothing.
 */
	.globl	t234_install_el2_vectors
t234_install_el2_vectors:
	mrs	x9, CurrentEL
	cmp	x9, #(2 << 2)
	b.ne	1f
	adr	x9, t234_el2_vectors
	msr	vbar_el2, x9
	isb
1:	ret

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
 * EL2 vectors for every core: each secondary from t234_ap_entry, CPU0 from
 * board_init. Same shape as the EL1 table; the handler also receives SPSR_EL2,
 * which says where the exception came from.
 *
 * The stack a handler here uses: on CPU0, cstart's
 * (lib/aarch64/cstart.S:88-90); on a secondary, the board's small one from
 * ap_entry.S until smp_start installs the library AP stack. Under -Q disable
 * the core then drops to EL1 and SP_EL2 keeps the value it had; under el2-host
 * it stays the live stack until procnto.
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
	VEC2 4				/* Current EL, SPx — trampoline, at_el2, el2-host startup */
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
	/*
	 * SCTLR_EL2.M set: under el2-host vstart's sctlr_el1 write lands here
	 * through E2H (lib/aarch64/vstart.S:86-90). TTBR0 then maps only the
	 * startup image (lib/aarch64/init_mmu.c:159-161), so MMIO is unmapped:
	 * reset without printing.
	 */
	mrs	x9, sctlr_el2
	tbnz	x9, #0, t234_fault_reset
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
