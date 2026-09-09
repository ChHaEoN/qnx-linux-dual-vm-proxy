/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Board override: linear CPU index to the MPIDR affinity PSCI expects.
 *
 * The library's own version returns the index unchanged, which is correct on a
 * machine whose cores are numbered 0..n-1 in affinity space and wrong here.
 * This SKU is floor-swept: cluster 0 holds four cores at affinities 0x0, 0x100,
 * 0x200 and 0x300, and cluster 1 holds two at 0x10200 and 0x10300. Asking
 * firmware to start "CPU 4" would ask it to start affinity 0x4, which does not
 * exist; CPU_ON returns an error and the core never appears.
 *
 * This file exists rather than a patch to the library because the board object
 * is linked before libstartup.a is scanned, so this definition satisfies the
 * reference and the library's member is never pulled in. That is ordinary
 * archive behaviour, but it is also the thing to check first if a symbol
 * collision ever appears: nm the linked startup and confirm there is exactly
 * one psci_cpu_id.
 */

#include "t234_startup.h"
#include <aarch64/psci.h>

_Uint64t
psci_cpu_id(unsigned const cpu)
{
	if (cpu >= T234_NUM_CPU) {
		/*
		 * Out of range. Returning the index would ask firmware to start a
		 * core that does not exist; returning the boot core's affinity would
		 * be worse. Hand back an affinity no core has, so CPU_ON fails
		 * cleanly and the library's start_aps counter reports it.
		 */
		return ~0ull;
	}
	return t234_cpu_mpidr[cpu];
}
