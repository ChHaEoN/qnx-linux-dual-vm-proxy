/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Interrupt controller: GIC-600, a plain GICv3.
 *
 * This file is short because the library does the work. gic_v3_initialize()
 * registers the PPI entry itself and synthesises a default SPI entry when the
 * board has not added one, so there are no startup_intrinfo structures to
 * build here — which is the opposite of what the plan assumed, and worth
 * knowing before someone writes two hundred lines that are already written.
 *
 * What the board must get right is the geometry, and there is exactly one trap
 * in it. The redistributor frames are 0x20000 apart in a 2 MiB region, so
 * sixteen fit, but this SKU populates only six and not contiguously: CPUs 0-3
 * in frames 0-3, the two cluster-1 cores in frames 6 and 7. The library derives
 * its frame limit from the region size when one is given, and from the CPU
 * count when it is not. Six is not enough to reach frame 7. So the size is
 * passed explicitly, and the wrapper that omits it — gic_v3_set_paddr — must
 * not be used here, however much simpler it looks.
 *
 * The failure mode of getting that wrong is at least loud: the affinity walk
 * asserts and crashes with a named file and line, rather than hanging. On a
 * board with no console that distinction is most of the debugging budget.
 */

#include "t234_startup.h"

void
init_intrinfo(void)
{
	/*
	 * Bases and the full region size. No ITS on this part: the device tree
	 * has no ITS child and Linux logs no LPI support, so NULL_PADDR rather
	 * than an address — and NULL_PADDR is all-ones, not zero. A literal 0
	 * would be taken for a real physical address and mapped.
	 */
	gic_v3_set_paddr_range(T234_GICD_BASE, T234_GICR_BASE, T234_GICR_SIZE,
	                       NULL_PADDR);

	/*
	 * System-register callouts, which are already the default. This call is a
	 * no-op as written — the library guards its body on a non-null GICC and
	 * ignores a zero second argument — and it is here for what it documents
	 * rather than what it does: this part has no GICC MMIO aperture, and if
	 * the CPU ever reported no system-register GIC interface the library would
	 * force memory-mapped callouts and then assert, because no aperture was
	 * ever supplied. On A78AE that field is non-zero; Linux logs the
	 * system-register interface at boot.
	 */
	gic_v3_use_mm_reg_callouts(NULL_PADDR, 0);

	gic_v3_initialize();

	/*
	 * The IPI routine could not be chosen before the GIC version was known.
	 * board_smp_init set it too, so this is belt and braces rather than the
	 * only assignment — cheap insurance against an ordering change leaving the
	 * field null, which would be a silent SMP failure rather than a loud one.
	 */
	{
		struct smp_entry *const smp = lsp.smp.p;

		if (smp != NULL) {
			smp->send_ipi = (void *)gic_sendipi;
		}
	}
}
