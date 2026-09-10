/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * What an exception during startup should do: say what happened, then reset.
 *
 * Reached from the vector tables in aarch64/vectors_el1.S. It reports through
 * crash(), which means the message goes out by the same kprintf path as every
 * other startup message — so it lands in the black box as well as the mailbox —
 * and then ends in crash_done(), which this board overrides to issue a PSCI
 * reset rather than parking in wfi.
 *
 * The result is that a fault in the untested parts of this bring-up costs one
 * warm reset and leaves a readable explanation in pstore, instead of costing a
 * trip to the board and leaving nothing at all.
 *
 * The decode is deliberately minimal — the exception class and the raw
 * registers. Anything more would be guessing at what the failure will be, and
 * the raw values are enough to look up afterwards on a machine with room to
 * think.
 *
 * Two things changed for SMP. Every register prints as 64 bits: this library's
 * %x takes an unsigned and prints 32 (lib/kprintf.c, case 'x'), so a black-box
 * FAR such as 0x2_72770000, or any virtual ELR, used to print wrong. And the
 * faulting core names itself: MPIDR is read here, in C, on the CPU that took
 * the exception, which keeps the assembly-to-C call at four arguments.
 *
 * M1b adds the core's stage to both lines, and HCR_EL2 to the EL2 line: under
 * -Q enable,el2-host the EL2 handler is the only one any core has from its
 * first board code until procnto, and E2H in that value says whether the fault
 * came before or after the core's own hypervisor_init.
 */

#include "t234_startup.h"

void t234_el1_fault(unsigned long idx, unsigned long esr,
                    unsigned long elr, unsigned long far);

/*
 * Naming the classes worth recognising on sight saves a lookup at the moment
 * someone is staring at a recovered log and wondering whether the port is
 * broken or the memory map is.
 */
static const char *
t234_ec_name(unsigned const ec)
{
	switch (ec) {
	case 0x21: return "instruction abort";
	case 0x25: return "data abort";
	case 0x26: return "SP alignment fault";
	case 0x22: return "PC alignment fault";
	case 0x00: return "unknown/undefined";
	/*
	 * The one trap CPTR_EL2 can produce at EL2 once E2H is set: at_el2 wrote
	 * CPTR_EL2 = 0 (lib/aarch64/_start_el1.S:161) and init_one_cpuinfo writes
	 * cpacr_el1 = 0 (lib/aarch64/init_cpuinfo.c:320), and with E2H=1 that
	 * layout means FPEN = 00, which traps FP/SIMD (VENDOR_CLAIM, Arm ARM).
	 */
	case 0x07: return "FP/SIMD access trap";
	case 0x18: return "system register trap";
	case 0x3c: return "BRK";
	default: break;
	}
	return "exception";
}

/*
 * The stage from the faulting core's diagnostic record. The record is found by
 * affinity, with the same mask the GIC wrapper uses: MPIDR bits 31 and 24
 * (RES1 and MT) are not part of the table. On CPU0 the stage is a boot stage
 * below 0x10, or a wrapper stage 0x40-0x45 during init_cpuinfo; 0 means the
 * affinity is not in the table.
 */
static unsigned
t234_stage_of(_Uint64t const mpidr)
{
	unsigned i;

	for (i = 0; i < T234_NUM_CPU; ++i) {
		if ((mpidr & 0xff00ffffffull) == t234_cpu_mpidr[i]) {
			return t234_ap_diag[i].stage;
		}
	}
	return 0;
}

void
t234_el1_fault(unsigned long idx, unsigned long esr,
               unsigned long elr, unsigned long far)
{
	_Uint64t const mpidr = aa64_sr_rd64(mpidr_el1);
	unsigned const ec    = (unsigned)((esr >> 26) & 0x3fu);

	crash("t234: EL1 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L stage=%x\n",
	      t234_ec_name(ec), mpidr, (int)idx, ec,
	      (_Uint64t)esr, (_Uint64t)elr, (_Uint64t)far, t234_stage_of(mpidr));
	/* crash() does not return; crash_done() resets this board. */
}

/*
 * The EL2 counterpart. Reached on a secondary from t234_ap_entry onward, and on
 * CPU0 from board_init onward, in every -Q mode. Under el2-host it is the only
 * fault handler any core has until procnto. The stage says how far that core's
 * bring-up had got, which is what separates a trap in the trampoline's
 * normalisation from one in at_el2 or later. HCR_EL2 is read directly: this
 * handler only ever runs at EL2. With E2H (bit 34) clear the fault came before
 * that core's hypervisor_init; with E2H and TGE set it came in the VHE host.
 */
void
t234_el2_fault(unsigned long idx, unsigned long esr, unsigned long elr,
               unsigned long far, unsigned long spsr)
{
	_Uint64t const mpidr = aa64_sr_rd64(mpidr_el1);
	_Uint64t const hcr   = aa64_sr_rd64(hcr_el2);
	unsigned const ec    = (unsigned)((esr >> 26) & 0x3fu);

	crash("t234: EL2 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L SPSR=%L HCR_EL2=%L stage=%x\n",
	      t234_ec_name(ec), mpidr, (int)idx, ec,
	      (_Uint64t)esr, (_Uint64t)elr, (_Uint64t)far, (_Uint64t)spsr, hcr,
	      t234_stage_of(mpidr));
	/* crash() does not return; crash_done() resets this board. */
}
