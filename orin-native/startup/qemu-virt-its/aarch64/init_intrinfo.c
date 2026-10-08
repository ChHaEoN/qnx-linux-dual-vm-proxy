/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * GICv3 setup for the QEMU virt machine, WITH the ITS and LPIs.
 *
 * This is the only file of the qemu-virt-its variant. build-qemu-virt.sh
 * (VARIANT=its) stages ../qemu-virt as boards/qemu-virt-its and puts this file
 * over its aarch64/init_intrinfo.c, so the variant builds as
 * startup-qemu-virt-its and the default startup-qemu-virt is built from sources
 * this variant never touches. Everything that file says about the NISV fix
 * holds here unchanged: the library is the same one, built with the same flag.
 *
 * WHAT IT ADDS, AND WHY (the ivshmem doorbell into the guest, parked on
 * 2026-09-22 and taken up again on 2026-09-29). QEMU 6.2's ivshmem-doorbell
 * interrupts a guest by MSI-X only. On this machine an MSI is a write to the
 * GIC ITS's GITS_TRANSLATER, which turns (DeviceID, EventID) into an LPI. So
 * the guest needs the ITS set up and LPIs routed to it:
 *
 *   - the ITS base (QV_GITS_BASE, the virt machine's 0x08080000) goes to the
 *     library in place of NULL_PADDR;
 *   - one LPI block, INTIDs 8192.. (QV_LPI_COUNT of them), becomes interrupt
 *     vectors 8192.. -- vector number equals INTID. The library installs the
 *     ITS mask/unmask callouts for it, and gic_v3_initialize() allocates the
 *     LPI configuration and pending tables and the ITS device table,
 *     collection table and command queue, and maps ICID n to CPU n (MAPC).
 * (R39 note, 2026-10-05, on "QEMU 6.2's ivshmem-doorbell": end of this file.)
 * The library does NOT map any device to an LPI (MAPD/MAPTI): that is the job
 * of whatever owns the device's MSI-X, normally the PCI server's hardware
 * module. This guest runs no PCI server, so ipc-test/qnx-its-probe does it,
 * the way shm_map_qnx.c places the BARs. The library publishes what that
 * needs in the syspage: a hwinfo device "GIC_ITS" with two locations, the ITS
 * registers and the command-queue lock the callouts take.
 *
 * EVERY ITS AND LPI TABLE IS CACHEABLE (inner shareable, write-back). The
 * library's defaults are non-shareable, non-cacheable, and its callouts map
 * the command queue and the LPI configuration table uncached. Under KVM the
 * GIC is emulated in the host kernel, which reads these tables through its own
 * cacheable mapping of guest memory. This CPU has no FEAT_S2FWB, so an uncached
 * guest view and a cacheable host view of the same page have mismatched
 * attributes, for which Arm does not promise coherence -- the host could read a
 * stale command, or a stale enable bit after an unmask. shm_map_qnx.c maps
 * BAR2 cacheable for the same reason. `qnx-its-probe info` prints the
 * attributes the emulated GIC reports back in GITS_CBASER and GITS_BASERn.
 *
 * WHAT THIS DOES NOT ESTABLISH. Nothing about whether an LPI reaches a QNX
 * thread, how fast, or whether it is lost: that is what the probe is for, and
 * its results are held locally (NC QDL v7 4.6(i)). And like the default
 * variant, this is a startup WE rebuilt: not a QNX-supported configuration.
 */

#include "qemu_virt_startup.h"
#include <aarch64/gic_v3.h>
#include <aarch64/gic.h>

/*
 * 8192 is the library's minimum (gic_v3_initialize asserts num_lpis >= 8192).
 * If the GIC reports fewer, gic_v3_lpi_add_entry() refuses and startup stops
 * below. Vector base = 8192 keeps vector number == INTID, which is what the
 * probe and anyone reading its output will assume.
 */
#define QV_LPI_BASE    8192u
#define QV_LPI_COUNT   8192u

static struct startup_intrinfo qv_lpi = {
	.vector_base = QV_LPI_BASE,
	.num_vectors = QV_LPI_COUNT,
	.flags = 0,
};

void
init_intrinfo(void)
{
	/* Inner shareable, write-back read/write-allocate, inner and outer. */
	static const gic_tbl_params_t cacheable = {
		.shareability = arm_gic_tbl_shareability_INNER,
		.cacheability.inner = arm_gic_tbl_cacheability_RDWR_ALLOC_WB,
		.cacheability.outer = arm_gic_tbl_cacheability_RDWR_ALLOC_WB,
	};

	gic_v3_set_paddr_range(QV_GICD_BASE, QV_GICR_BASE, QV_GICR_SIZE,
	                       QV_GITS_BASE);

	gic_v3_use_mm_reg_callouts(NULL_PADDR, 0);

	/*
	 * Before gic_v3_initialize(), which allocates and programs the tables
	 * with whatever parameters are set by then. mmap flags without
	 * PROT_NOCACHE make the callouts' views cacheable too.
	 */
	gic_v3_set_lpi_cfgtbl_params(&cacheable, PROT_READ | PROT_WRITE);
	gic_v3_set_lpi_pendtbl_params(&cacheable);
	gic_v3_its_set_dt_params(0, &cacheable);
	gic_v3_its_set_ct_params(0, &cacheable);
	gic_v3_its_set_cmd_q_params(0, &cacheable, PROT_READ | PROT_WRITE);

	/*
	 * 64 KiB table pages. The library defaults to 4 KiB and asserts that
	 * GITS_BASERn's Page_Size reads back as written, while KVM's emulated
	 * ITS supports one page size, 64 KiB, and forces the field to it
	 * (Linux, arch/arm64/kvm/vgic/vgic-its.c, vgic_sanitise_its_baser). The
	 * library then sizes the device and collection tables in 64 KiB pages.
	 */
	gic_v3_its_set_dt_page_size(0, 65536u);
	gic_v3_its_set_ct_page_size(0, 65536u);

	/*
	 * gic_v3_lpi_add_entry() reads GICD_TYPER, so it must come after the
	 * addresses are set; it returns -1 when the GIC has no LPIs or too few.
	 * A startup that carried on would give procnto no LPI vectors and the
	 * probe nothing to attach to, silently, so stop here instead.
	 */
	if (gic_v3_lpi_add_entry(&qv_lpi) != 0) {
		crash("qemu-virt-its: no room for LPIs %u..%u (GIC reports %u LPIs); "
		      "was QEMU started without its ITS?\n",
		      QV_LPI_BASE, QV_LPI_BASE + QV_LPI_COUNT - 1u, gic_v3_num_lpis());
	}

	gic_v3_initialize();

	{
		struct smp_entry *const smp = lsp.smp.p;

		if (smp != NULL) {
			smp->send_ipi = (void *)gic_sendipi;
		}
	}
}

/*
 * R39 NOTE (2026-10-05), on "QEMU 6.2's ivshmem-doorbell interrupts a guest
 * by MSI-X only" in the header of this file.
 *
 * "6.2" names the QEMU the board ran when that was written. The sentence is
 * about the device and holds for the QEMU 8.2.2 the board runs since its
 * upgrade to L4T R39 on 2026-10-04. Whether the ITS and the LPIs this file
 * sets up behave the same under that QEMU and its host kernel is not for a
 * comment to say: a run shows it, and what a run shows is held locally (NC
 * QDL v7 4.6(i)).
 *
 * The note stands below the last line of code so that no line above moves
 * (the reason is at the end of ../../qemu-virt/qemu_virt_startup.h). No line
 * above this comment moved. One changed: a comment line of the header that
 * was empty and now points down here.
 */
