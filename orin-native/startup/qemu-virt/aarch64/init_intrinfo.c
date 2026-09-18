/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * GICv3 setup for the QEMU virt machine.
 *
 * This is the function the whole board exists to reach. The KVM boot of the
 * QNX-shipped startup-qemu-virt dies inside gic_v3_initialize(), and the trace
 * captured on 2026-09-18 names the instruction:
 *
 *   kvm_guest_fault: ipa 0x8000000 hsr 0x92000045 hxfar 0x8000420 pc 0x40085978
 *   kvm_userspace_exit: reason KVM_EXIT_ARM_NISV (28)
 *
 * hsr 0x92000045 has ISV=0 — the hardware gave KVM no instruction syndrome, so
 * KVM cannot emulate the access and bails out to userspace, which cannot either.
 * The faulting store is a writeback form (`str w3,[x0],#4`) into GICD+0x420,
 * IPRIORITYR. The neighbouring accesses at the same IPA carry ISV=1 and are
 * handled normally, which is why the guest gets as far as printing its banner
 * before stopping here.
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
	 * at 0x08080000 and the shipped startup evidently finds it (`FOUND GICv3
	 * ITS` is the last line before the hang). LPI support needs ITS tables in
	 * guest memory and adds failure surface this board has no use for yet,
	 * and the fault under investigation is in distributor priority setup,
	 * which runs either way. If an LPI-using device is ever wanted here, this
	 * is the line that changes.
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
