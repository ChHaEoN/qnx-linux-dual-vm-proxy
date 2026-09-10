/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * t234_ap_entry — where PSCI CPU_ON starts a secondary core.
 *
 * The library would start secondaries at its own smp_start, which goes
 * straight into at_el2. That routine is sound for what it touches, but it was
 * not written for a core firmware has just warm-booted after Linux used it:
 *
 *   - it writes HCR_EL2 with no ISB after it (lib/aarch64/_start_el1.S:156),
 *     so a firmware-set E2H would be flipped without the synchronisation the
 *     change needs;
 *   - it never touches MDCR_EL2, HSTR_EL2, ICH_HCR_EL2 or the three timer
 *     controls (:125-197), and never sets VBAR_EL2, so a trap or fault in it
 *     goes wherever firmware left the EL2 vector base — silently.
 *
 * CPU0 does not have that problem because the shim runs first: its
 * normalisation (orin-native/shim/t234-shim.S:291-304), then at_el2. This file
 * gives every secondary the same order, with the shim's writes copied verbatim
 * rather than re-derived. What firmware actually leaves in those registers
 * after a CPU_OFF/CPU_ON cycle has never been measured, so the raw values are
 * recorded into t234_ap_diag[] before anything is written; board_smp_adjust_num
 * prints them once the library has given this core a stack.
 *
 * Environment: MMU and caches off, at whatever EL firmware chose, no stack, and
 * one secondary at a time — CPU0 starts the next core only after this one has
 * cleared cpu_starting (lib/init_smp.c:69-77). Every address is PC-relative,
 * as smp_start forms its own (lib/aarch64/smp_start.S:57, :63).
 *
 * Ran on every secondary in M2 (CPU_ON issued from EL1, -Q disable); not yet
 * with CPU_ON issued from EL2.
 */

#include "t234_startup.h"

	.text
	.align	2

	.globl	t234_ap_entry
t234_ap_entry:
	/*
	 * Exceptions off, then SP_ELx. The stack set below must land in the banked
	 * SP that _start_el2_or_el1 selects unconditionally
	 * (lib/aarch64/_start_el1.S:61). Upstream TF-A already enters with SP_ELx;
	 * T234's fork has not been read, and the write costs nothing.
	 */
	msr	daifset, #0xf
	msr	spsel, #1

	/*
	 * Board EL2 vectors before any other EL2 code runs, so a trap in the
	 * reads and writes below prints and resets instead of vanishing into
	 * whatever firmware left in VBAR_EL2. x11 keeps the entry EL.
	 */
	mrs	x11, CurrentEL
	lsr	x11, x11, #2
	cmp	x11, #2
	b.ne	1f
	adr	x9, t234_el2_vectors
	msr	vbar_el2, x9
	isb
1:
	/*
	 * A small stack of our own, used only if the EL2 fault handler has to run
	 * before smp_start replaces SP with the library's (smp_start.S:57-58).
	 * Shared by all secondaries, which is safe for the same reason the
	 * library's single AP stack is: they start one at a time.
	 */
	adr	x9, t234_ap_stack_top
	mov	sp, x9

	/*
	 * This core's index, from the same variable smp_start reads
	 * (smp_start.S:63-65). start_aps sets it to index+1 just before CPU_ON
	 * (lib/init_smp.c:70), so anything outside 1..5 means this entry was
	 * reached without a CPU_ON from start_aps: no record can be trusted and
	 * nothing sensible can continue. Reset with constants only.
	 */
	adr	x10, cpu_starting
	ldr	w10, [x10]
	sub	w10, w10, #1
	cmp	w10, #1
	b.lo	t234_fault_reset
	cmp	w10, #(T234_NUM_CPU - 1)
	b.hi	t234_fault_reset

	/* x12 = &t234_ap_diag[index]; w10 was zero-extended into x10 above. */
	adr	x12, t234_ap_diag
	mov	x13, #T234_DIAG_SIZE
	mul	x13, x10, x13
	add	x12, x12, x13

	mov	w13, #T234_STAGE_TRAMP_IN
	str	w13, [x12, #T234_DIAG_STAGE]
	str	w11, [x12, #T234_DIAG_ENTRY_EL]
	mrs	x13, mpidr_el1
	str	x13, [x12, #T234_DIAG_MPIDR]

	/*
	 * Entered at EL1: the EL2 registers can be neither read nor normalised
	 * from here, so the record keeps zeros for them and says EL1.
	 * board_smp_adjust_num stops the run by name on that — it does not
	 * continue on state nobody can see.
	 */
	cmp	x11, #2
	b.ne	2f

	/*
	 * Firmware's values, raw, before anything is written. With HCR_EL2.E2H
	 * set, the CNTP/CNTV reads alias the EL2 timers; HCR_EL2 is recorded
	 * first so the printed line can be read in the right view.
	 */
	mrs	x13, hcr_el2
	str	x13, [x12, #T234_DIAG_HCR_EL2]
	mrs	x13, sctlr_el2
	str	x13, [x12, #T234_DIAG_SCTLR_EL2]
	mrs	x13, mdcr_el2
	str	x13, [x12, #T234_DIAG_MDCR_EL2]
	mrs	x13, hstr_el2
	str	x13, [x12, #T234_DIAG_HSTR_EL2]
	mrs	x13, ich_hcr_el2
	str	x13, [x12, #T234_DIAG_ICH_HCR_EL2]
	mrs	x13, cnthp_ctl_el2
	str	x13, [x12, #T234_DIAG_CNTHP_CTL]
	mrs	x13, cntp_ctl_el0
	str	x13, [x12, #T234_DIAG_CNTP_CTL]
	mrs	x13, cntv_ctl_el0
	str	x13, [x12, #T234_DIAG_CNTV_CTL]
	mrs	x13, cntfrq_el0
	str	x13, [x12, #T234_DIAG_CNTFRQ]

	/*
	 * The shim's normalisation, instruction for instruction
	 * (t234-shim.S:291-304). The order is the point: timers disarmed in
	 * whatever view E2H currently gives, E2H cleared with an ISB, then the
	 * real EL2 timer and trap registers. That sequence is what CPU0 ran from
	 * a Linux-dirty kexec state; whether it is equally safe from an AP's
	 * warm-boot state is exactly what the first run of this code measures.
	 */
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

	mov	w13, #T234_STAGE_TRAMP_NORM
	str	w13, [x12, #T234_DIAG_STAGE]
2:
	/*
	 * Into the library's path, unchanged: _start_el2_or_el1 / at_el2,
	 * vbar_default, cache flush, the library stack, board_smp_adjust_num.
	 * A branch, not a call: smp_start never returns.
	 */
	b	smp_start

	.data
	.balign	16
	.space	4096
t234_ap_stack_top:
