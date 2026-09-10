/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * What an EL1 exception during startup should do: say what happened, then reset.
 *
 * Reached from the vector table in aarch64/vectors_el1.S. It reports through
 * crash(), which means the message goes out by the same kprintf path as every
 * other startup message — so it lands in the black box as well as the mailbox —
 * and then ends in crash_done(), which this board overrides to issue a PSCI
 * reset rather than parking in wfi.
 *
 * The result is that a fault in the untested parts of this bring-up costs one
 * warm reset and leaves a readable explanation in pstore, instead of costing a
 * trip to the board and leaving nothing at all.
 *
 * The decode is deliberately minimal — the exception class and the three
 * registers. Anything more would be guessing at what the failure will be, and
 * the raw values are enough to look up afterwards on a machine with room to
 * think.
 */

#include "t234_startup.h"

void t234_el1_fault(unsigned long idx, unsigned long esr,
                    unsigned long elr, unsigned long far);

void
t234_el1_fault(unsigned long idx, unsigned long esr,
               unsigned long elr, unsigned long far)
{
	unsigned ec = (unsigned)((esr >> 26) & 0x3fu);

	/*
	 * Naming the three classes worth recognising on sight saves a lookup at
	 * the moment someone is staring at a recovered log and wondering whether
	 * the port is broken or the memory map is.
	 */
	const char *what = "exception";

	switch (ec) {
	case 0x21: what = "instruction abort"; break;
	case 0x25: what = "data abort"; break;
	case 0x26: what = "SP alignment fault"; break;
	case 0x22: what = "PC alignment fault"; break;
	case 0x00: what = "unknown/undefined"; break;
	default: break;
	}

	crash("t234: EL1 %s, vector %d, EC=%x ESR=%x ELR=%x FAR=%x\n",
	      what, (int)idx, ec, (unsigned)esr, (unsigned)elr, (unsigned)far);
	/* crash() does not return; crash_done() resets this board. */
}
