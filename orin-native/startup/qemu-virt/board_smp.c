/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * SMP for the QEMU virt machine, as a KVM guest.
 *
 * Deliberately thin. t234-orin-nano's equivalent issues its own CPU_ON, parks
 * the secondaries by hand and carries a per-core diagnostic record, because on
 * that board the cores enter at EL2 with firmware state that has to be read and
 * normalised before anything else is safe, and a core that fails to start has
 * no other way to say so. None of that applies to a guest whose vCPUs the host
 * creates in a known state, so this board uses the library's PSCI path and adds
 * nothing to it.
 *
 * The conduit is not chosen here. main() calls fdt_psci_configure(), which reads
 * method = "hvc" from the device tree and sets psci_call accordingly, and fails
 * loudly if it cannot — so by the time board_smp_start runs, psci_call is set
 * and is the right one. psci_cpu_id is the library's identity mapping, which is
 * correct because the virt machine's MPIDRs are flat (cpu@0 reg=<0>, cpu@1
 * reg=<1>), unlike Tegra's.
 */

#include "qemu_virt_startup.h"
#include <aarch64/psci.h>
#include <arm/armboth_startup.h>

unsigned
board_smp_num_cpu(void)
{
	unsigned const num = fdt_num_cpu();

	/*
	 * The device tree lists exactly the vCPUs the launch line asked for, so
	 * it is the authority. Fall back to one core rather than guessing if the
	 * tree is missing: booting single-core is recoverable and says so in the
	 * syspage, whereas claiming cores that do not exist is not.
	 */
	return (num == 0) ? 1u : num;
}

void
board_smp_init(struct smp_entry *smp, unsigned num_cpus)
{
	(void)smp;
	(void)num_cpus;

	/*
	 * send_ipi is deliberately not set here. The correct routine depends on
	 * the GIC version, which is not settled until gic_v3_initialize() runs,
	 * so init_intrinfo() installs gic_sendipi once it is. Setting a GICv2
	 * routine here the way the Foundation Model board does would be dead
	 * anyway, but it would also be wrong if it ever survived.
	 */
}

int
board_smp_start(unsigned cpu, void (*start)(void))
{
	return psci_smp_start(cpu, start);
}

unsigned
board_smp_adjust_num(unsigned cpu)
{
	return cpu;
}
