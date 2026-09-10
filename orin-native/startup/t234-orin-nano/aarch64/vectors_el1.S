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
 * no window where the library's version is the live one after the drop.
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
 * reachable — so the handler can call C, which is what makes the message go
 * through the same kprintf path as everything else and therefore into both the
 * mailbox and the black box.
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
	mrs	x1, esr_el1
	mrs	x2, elr_el1
	mrs	x3, far_el1
	b	t234_el1_fault		/* noreturn: prints, then resets */
