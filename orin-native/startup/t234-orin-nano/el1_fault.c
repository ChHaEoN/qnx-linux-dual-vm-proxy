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
	default: break;
	}
	return "exception";
}

void
t234_el1_fault(unsigned long idx, unsigned long esr,
               unsigned long elr, unsigned long far)
{
	_Uint64t const mpidr = aa64_sr_rd64(mpidr_el1);
	unsigned const ec    = (unsigned)((esr >> 26) & 0x3fu);

	crash("t234: EL1 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L\n",
	      t234_ec_name(ec), mpidr, (int)idx, ec,
	      (_Uint64t)esr, (_Uint64t)elr, (_Uint64t)far);
	/* crash() does not return; crash_done() resets this board. */
}

/*
 * The EL2 counterpart, reached only on a secondary core (CPU0 keeps the shim's
 * EL2 vectors). The stage from that core's diagnostic record says how far its
 * bring-up had got, which is what separates a trap in the trampoline's
 * normalisation from one in at_el2 or later. The record is found by affinity,
 * with the same mask the GIC wrapper uses: MPIDR bits 31 and 24 (RES1 and MT)
 * are not part of the table.
 */
void
t234_el2_fault(unsigned long idx, unsigned long esr, unsigned long elr,
               unsigned long far, unsigned long spsr)
{
	_Uint64t const mpidr = aa64_sr_rd64(mpidr_el1);
	unsigned const ec    = (unsigned)((esr >> 26) & 0x3fu);
	unsigned       stage = 0;
	unsigned       i;

	for (i = 0; i < T234_NUM_CPU; ++i) {
		if ((mpidr & 0xff00ffffffull) == t234_cpu_mpidr[i]) {
			stage = t234_ap_diag[i].stage;
			break;
		}
	}

	crash("t234: EL2 %s on MPIDR=%L vector %d EC=%x ESR=%L ELR=%L FAR=%L SPSR=%L stage=%x\n",
	      t234_ec_name(ec), mpidr, (int)idx, ec,
	      (_Uint64t)esr, (_Uint64t)elr, (_Uint64t)far, (_Uint64t)spsr, stage);
	/* crash() does not return; crash_done() resets this board. */
}
