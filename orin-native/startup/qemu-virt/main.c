/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * startup-qemu-virt — QNX startup for the QEMU `virt` aarch64 machine, built
 * to run as a KVM guest on the Jetson Orin Nano.
 *
 * WHY THIS EXISTS
 *
 * The SDP ships a startup-qemu-virt binary but not its board source, so the
 * shipped one cannot be relinked. It dies under KVM inside gic_v3_initialize()
 * on a writeback MMIO store that reports no instruction syndrome (ISV=0), which
 * KVM cannot emulate; the guest stops with KVM_EXIT_ARM_NISV. Rebuilding the
 * library with -fno-auto-inc-dec removes that instruction form, and rebuilding
 * needs a board to link against — this one. See aarch64/init_intrinfo.c for the
 * captured fault and patches/gic-no-auto-inc-dec.patch for the fix itself.
 *
 * WHAT IT HAS DONE, AND WHAT IT HAS NOT
 *
 * 2026-09-18: it boots. Under KVM on a Jetson Orin Nano, an IFS carrying this
 * startup reached procnto and printed the banner below, on QEMU 6.2.0 and
 * 11.1.0 alike (byte-identical serial output, so the QEMU version is not a
 * factor). The control -- the SDP's own startup-qemu-virt, same launch line,
 * same host, same hour -- still dies after "FOUND GICv3 ITS" with 17 bytes of
 * output. So the chain "remove the writeback store -> no NISV exit -> the guest
 * boots" now has its last link measured, not argued.
 *
 * What that does not establish: nothing about timing, latency or throughput;
 * nothing about running two guests; nothing about the GPU. And the fix lives in
 * a startup WE rebuilt -- QNX ships no such binary, so this is evidence for a
 * defect report, not a supported configuration.
 *
 * WHY IT IS NOT A COPY OF t234-orin-nano
 *
 * Three of that board's decisions are wrong here, and each was checked against
 * the device tree QEMU actually generates rather than assumed:
 *
 *   - PSCI conduit. t234 sets psci_call = psci_smc by hand, because Tegra's
 *     node says "arm,psci-1.0" and the library's probe matches only the literal
 *     "arm,psci". The virt machine's node is "arm,psci-0.2\0arm,psci", which
 *     does contain that string, and carries method = "hvc". So the probe works
 *     here and forcing SMC would be exactly wrong.
 *   - psci_cpu_id. t234 overrides it because Tegra's MPIDR affinities are
 *     0x00000, 0x00100, ... The virt machine's are flat (cpu@0 reg=<0>,
 *     cpu@1 reg=<1>), which is what the library's identity version already
 *     returns, so overriding it would introduce a bug rather than fix one.
 *   - RAM. t234 hard-codes it because Tegra publishes no /memory node. The
 *     virt machine publishes memory@40000000, so init_raminfo_fdt() does the
 *     whole job and this board needs no RAM code at all.
 */

#include "qemu_virt_startup.h"

#include <stddef.h>
#include <aarch64/psci.h>
#include <arm/armboth_startup.h>

extern struct callout_rtn   reboot_psci_hvc;
extern void                 init_pl011(unsigned, const char *, const char *);
extern void                 put_pl011(int);
extern struct callout_rtn   display_char_pl011, poll_key_pl011, break_detect_pl011;

/*
 * The console. Started for real from the IFS script (devc-serpl011 -e -F
 * 0x9000000,33); this entry is what startup itself prints through before
 * procnto exists. The device string is the library's
 * "base^shift.reserved.clk.baud" form; the virt machine's PL011 is a plain
 * 32-bit-spaced register block, so shift 2.
 */
static const struct debug_device debug_devices[] = {
	{
		"pl011",
		{ "0x09000000^2.0.0.115200", "" },
		init_pl011, put_pl011,
		{ &display_char_pl011, &poll_key_pl011, &break_detect_pl011 },
	},
};

/*
 * Reboot through PSCI on the HVC conduit, matching what the device tree says.
 * t234 uses the SMC form; using it here would trap to a secure monitor the
 * guest does not have.
 */
const struct callout_slot callouts_reboot[] = {
	{ offsetof(struct callout_entry, reboot), &reboot_psci_hvc },
};

int
main(int argc, char **argv, char **envv)
{
	int opt;

	add_callout_array(callouts_reboot, sizeof(callouts_reboot));

	/*
	 * QEMU places the device tree and passes it in x0, which the library has
	 * already saved into boot_regs. Everything this board learns about the
	 * machine beyond the constants in its header comes from here: the CPU
	 * list, the memory nodes and the PSCI conduit.
	 */
	if (boot_regs[0] != 0) {
		fdt_init((paddr_t)boot_regs[0]);
	}

	while ((opt = getopt(argc, argv, COMMON_OPTIONS_STRING)) != -1) {
		handle_common_option(opt);
	}

	select_debug(debug_devices, sizeof(debug_devices));

	/*
	 * PSCI, from the device tree. Nothing in the library calls this, so the
	 * board must, and the return value matters: psci_call is a function
	 * pointer with no default, so a silent failure here becomes a call
	 * through NULL at the first CPU_ON, with no output to say why. Fail
	 * loudly instead — select_debug has already run, so this can print.
	 */
	if (fdt_psci_configure() == 0) {
		crash("qemu-virt: no usable PSCI node in the device tree: "
		      "expected compatible \"arm,psci\" with cpu_on and method\n");
	}

	/*
	 * RAM, entirely from the device tree: every node with
	 * device_type = "memory" is added, and the FDT reserved-memory entries
	 * are put on the avoid list first. No board constant is involved.
	 */
	if (init_raminfo_fdt() == 0) {
		crash("qemu-virt: no memory node in the device tree\n");
	}

	/*
	 * Keep the tree itself out of allocatable RAM and register it for user
	 * space, as t234 does.
	 */
	if (fdt_size != 0) {
		avoid_ram((paddr_t)boot_regs[0], fdt_size);
		fdt_asinfo();
	}
	alloc_ram(shdr->ram_paddr, shdr->ram_size, 1);

	hypervisor_init(0);        /* must precede init_smp/init_mmu/init_qtime */

	init_smp();

	if (shdr->flags1 & STARTUP_HDR_FLAGS1_VIRTUAL) {
		init_mmu();
	}

	init_intrinfo();
	init_qtime();              /* CNTFRQ_EL0 is set by the host; no override */

	init_cacheattr();
	init_cpuinfo();
	init_hwinfo();

	add_typed_string(_CS_MACHINE, "QEMU virt (aarch64), KVM guest");

	init_system_private();
	print_syspage();

	return 0;
}
