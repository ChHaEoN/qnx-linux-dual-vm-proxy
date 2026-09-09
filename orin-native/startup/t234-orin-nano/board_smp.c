/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Secondary-CPU bring-up: PSCI CPU_ON over SMC, six cores, two clusters.
 *
 * There is no spin table here and no firmware handshake to discover. TF-A
 * started all six cores for Linux at EL2 and will return them the same way, so
 * the whole of this file is telling the library how many cores there are and
 * letting its PSCI path do the work. The part that is not boilerplate is
 * psci_cpu_id.c next door: the affinities are not the linear indices.
 */

#include "t234_startup.h"

/*
 * MPIDR affinities from the live device tree's cpu@ reg cells. Cluster 0 holds
 * four cores at 0x0, 0x100, 0x200, 0x300; cluster 1 holds two at 0x10200 and
 * 0x10300. The gap is real — this SKU is floor-swept, and the missing cores'
 * redistributor frames (4 and 5) sit unoccupied in the middle of the region.
 */
const _Uint64t t234_cpu_mpidr[T234_NUM_CPU] = {
	0x00000ull, 0x00100ull, 0x00200ull, 0x00300ull, 0x10200ull, 0x10300ull,
};

unsigned
board_smp_num_cpu(void)
{
	unsigned num = fdt_num_cpu();

	if (num == 0 || num > T234_NUM_CPU) {
		/*
		 * No device tree, or one describing a machine this file was not
		 * written for. Six is what this SKU has; -P caps it below that and
		 * the library applies that cap itself.
		 */
		num = T234_NUM_CPU;
	}
	return num;
}

void
board_smp_init(struct smp_entry *smp, unsigned num_cpus)
{
	(void)num_cpus;

	/*
	 * The IPI routine is set again in init_intrinfo once the GIC is up, which
	 * is where the correct one is finally known. Setting it here as well keeps
	 * the field from being left null if the order ever changes.
	 */
	smp->send_ipi = (void *)gic_sendipi;
}

int
board_smp_start(unsigned cpu, void (*start)(void))
{
	/*
	 * Always PSCI. The library's other option is a spin table, which this
	 * firmware does not provide: TF-A owns the cores and hands them back
	 * through CPU_ON. psci_call was pointed at the SMC conduit in main().
	 */
	return psci_smp_start(cpu, start);
}

unsigned
board_smp_adjust_num(unsigned cpu)
{
	return cpu;
}
