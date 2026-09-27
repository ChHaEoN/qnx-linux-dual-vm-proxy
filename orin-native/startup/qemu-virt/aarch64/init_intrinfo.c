/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * GICv3 setup for the QEMU virt machine.
 *
 * This is the function the whole board exists to reach. Compiled with the
 * BSP's default flags, the library's gic_v3.c sets distributor priorities
 * with a writeback-form store into GICD+0x420, IPRIORITYR:
 *
 *   str  w3, [x0], #4
 *
 * A trapped writeback access reports no instruction syndrome (ISV=0;
 * VENDOR_CLAIM, Arm ARM, the data-abort ISS), so KVM cannot emulate it and
 * exits to userspace with KVM_EXIT_ARM_NISV, which QEMU cannot handle either.
 * Plain offset-form accesses carry ISV=1 and are emulated normally. What the
 * SDP's shipped startup-qemu-virt does under KVM on this board is a board
 * result, held locally (NC QDL v7 4.6(i)); nothing here depends on it being
 * stated.
 *
 * The fix is not in this file: it is the -fno-auto-inc-dec flag applied to the
 * library's own gic_v3.c (patches/gic-no-auto-inc-dec.patch), which turns the
 * writeback store into `stur w3,[x0,#-4]` — same address, same value, same
 * iteration count, but a plain offset form that reports a valid syndrome.
 * This file's job is only to give that code the right addresses.
 */

#include "qemu_virt_startup.h"
#include <aarch64/gic_v3.h>

void
init_intrinfo(void)
{
	/*
	 * gic_v3_set_paddr_range rather than gic_v3_set_paddr: the range form
	 * takes the redistributor region size explicitly, and the virt machine's
	 * region is far larger than the frames this guest uses (0xf60000, room
	 * for 123 cores). The library walks it by TYPER affinity, so handing it
	 * the real region size is what lets it find CPU 1's frame at all.
	 *
	 * The ITS is deliberately NOT passed, although the virt machine has one
	 * at 0x08080000 in the device tree QEMU generates. LPI support needs ITS
	 * tables in guest memory and adds failure surface this board has no use
	 * for yet, and the distributor priority setup this board exists for runs
	 * either way. If an LPI-using device is ever wanted here, this is the
	 * line that changes: the last argument below becomes the ITS base in
	 * place of NULL_PADDR.
	 */
	gic_v3_set_paddr_range(QV_GICD_BASE, QV_GICR_BASE, QV_GICR_SIZE,
	                       NULL_PADDR);

	/*
	 * System-register access to the CPU interface (ICC_*), not MMIO. Passing
	 * NULL_PADDR with use=0 is what t234-orin-nano does and what a GICv3 on
	 * ARMv8.0 and later expects; the MMIO path exists for GICv2-style access
	 * and would need a GICC address the virt machine does not publish.
	 */
	gic_v3_use_mm_reg_callouts(NULL_PADDR, 0);

	gic_v3_initialize();

	/*
	 * The correct IPI routine is only known once the GIC version is settled,
	 * so the library's board_smp_init could not have set it. Both the
	 * Foundation Model board and t234 do exactly this, for the same reason.
	 */
	{
		struct smp_entry *const smp = lsp.smp.p;

		if (smp != NULL) {
			smp->send_ipi = (void *)gic_sendipi;
		}
	}
}
