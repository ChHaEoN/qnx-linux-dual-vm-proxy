/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * startup-t234-orin-nano — QNX startup for the Jetson Orin Nano Developer Kit.
 *
 * Entered from the M0 shim (orin-native/shim/), which kexec has placed at
 * 0x80080000 and which has already put the machine into the state the library
 * expects: EL2, MMU and caches off, x0 the device tree. Everything the shim
 * does beyond that is reporting; the real normalisation is the library's own
 * at_el2, which runs on this CPU and on every secondary.
 *
 * Nothing here has run. This file compiles; it has never executed on the board.
 *
 * The call order below is not stylistic. hypervisor_init(0) must precede
 * init_smp, init_mmu and init_qtime, and the library enforces two of those with
 * a crash rather than a comment: secondaries compare their hypervisor flags
 * against ones CPU 0 records in that call, and enabling VHE redirects most EL1
 * register accesses to their EL2 counterparts, so EL1 state configured earlier
 * is simply not carried across. Source-verified, see
 * results/orin-native-port/20260909T1100Z/board-dir-source-reads.md.
 */

#include "t234_startup.h"

#include <stddef.h>
#include <aarch64/psci.h>

extern struct callout_rtn   reboot_psci_smc;
extern void                 init_pl011(unsigned, const char *, const char *);
extern void                 put_pl011(int);
extern void                 init_8250(unsigned, const char *, const char *);
extern void                 put_8250(int);
extern struct callout_rtn   display_char_pl011, poll_key_pl011, break_detect_pl011;
extern struct callout_rtn   display_char_tegra, poll_key_tegra, break_detect_tegra;

/*
 * Debug devices, in the order -D selects them and in the order they are tried.
 *
 * The TCU is first because it is the only port that needs no clock, no reset,
 * no pinmux and no BPMP transaction — it is a mailbox, and the SPE owns the
 * wire. Whether the SPE keeps servicing it once Linux is gone is the open
 * question M0 exists to answer, which is exactly why the two 16550-class ports
 * are here as well: if the mailbox turns out to be dead, -Dtegra8250 moves the
 * console to the port Linux had already clocked and left configured, with no
 * rebuild of anything but the buildfile line.
 *
 * The device strings follow the library's "base^shift.reserved.clk.baud" form.
 * init_tcu ignores its string entirely: the mailbox addresses are board
 * constants, not something a command line should be able to move.
 */
static const struct debug_device debug_devices[] = {
	{
		"tcu",
		{ "0x0C168000^0.0.0.0", "" },
		init_tcu, put_tcu,
		{ &display_char_tcu, &poll_key_tcu, &break_detect_tcu },
	},
	{
		"tegra8250",
		{ "0x03100000^2.0.0.115200", "" },
		init_8250, put_8250,
		{ &display_char_tegra, &poll_key_tegra, &break_detect_tegra },
	},
	{
		"pl011",
		{ "0x031D0000^2.0.0.115200", "" },
		init_pl011, put_pl011,
		{ &display_char_pl011, &poll_key_pl011, &break_detect_pl011 },
	},
};

/*
 * Size with an optional K, M or G suffix. Anything unrecognised after the
 * digits is rejected loudly rather than ignored: a typo in a memory size is
 * not something to guess at.
 */
static _Uint64t
t234_parse_size(const char *arg)
{
	char     *end = NULL;
	_Uint64t  v   = strtoull(arg, &end, 0);

	if (end == NULL || *end == '\0') {
		return v;
	}
	switch (*end) {
	case 'k': case 'K': v *= 1024ull; end++; break;
	case 'm': case 'M': v *= 1024ull * 1024ull; end++; break;
	case 'g': case 'G': v *= 1024ull * 1024ull * 1024ull; end++; break;
	default: break;
	}
	if (*end != '\0') {
		crash("t234: -m%s is not a size\n", arg);
	}
	return v;
}

const struct callout_slot callouts_reboot[] = {
	{ offsetof(struct callout_entry, reboot), &reboot_psci_smc },
};

int
main(int argc, char **argv, char **envv)
{
	const char *wdt_policy = "keep";
	int         probe_hv   = 0;
	int         opt;

	add_callout_array(callouts_reboot, sizeof(callouts_reboot));

	/*
	 * The device tree kexec hands over is used for the CPU list and as
	 * something to register for user space. It is deliberately not used for
	 * RAM (there is no /memory node) or for the GIC bases (hard-coded and
	 * cross-checked), and never for the console.
	 */
	if (boot_regs[0] != 0) {
		fdt_init((paddr_t)boot_regs[0]);
	}

	/*
	 * PSCI conduit, set unconditionally rather than probed. fdt_psci_configure
	 * matches the literal compatible string "arm,psci"; this board's node says
	 * "arm,psci-1.0", so the probe would find nothing and leave the conduit
	 * unset. Linux logs PSCIv1.1 over SMC on this firmware.
	 */
	psci_call = psci_smc;
	in_hvc    = 0;

	while ((opt = getopt(argc, argv, COMMON_OPTIONS_STRING "m:W:t")) != -1) {
		switch (opt) {
		case 'm':
			/*
			 * Override the RAM size, for bisecting a memory-map problem.
			 * Takes a K/M/G suffix, because -m992M is what anyone will
			 * actually type and silently reading it as 992 bytes would be a
			 * memorable afternoon.
			 */
			t234_ram_size_override = t234_parse_size(optarg);
			break;
		case 'W':
			/* keep | disable — see wdt.c. Default keep: the watchdog is the
			 * only thing that returns the board unattended. */
			wdt_policy = optarg;
			break;
		case 't':
			probe_hv = 1;
			break;
		default:
			handle_common_option(opt);
			break;
		}
	}

	select_debug(debug_devices, sizeof(debug_devices));

	/*
	 * Install our own EL1 vectors before hypervisor_init can drop us there.
	 *
	 * The library's vbar_default is a branch-to-self in every slot — right for
	 * a board with a debugger attached, and the worst possible ending here.
	 * Under -Q disable the drop happens inside hypervisor_init below, so from
	 * that point until procnto takes over, every fault in the least-tested code
	 * in this port would otherwise be silent and unrecoverable: no output, no
	 * reset, and a power cycle that wipes the log. See aarch64/vectors_el1.S.
	 *
	 * After select_debug, so a fault that happens between here and the drop can
	 * already say so.
	 */
	t234_install_el1_vectors();

	/*
	 * Report both watchdogs before anything else can hang. WDT0 is armed at
	 * two minutes when Linux hands over, so these two words decide whether a
	 * milestone that outlasts that needs -Wdisable or a kicker.
	 */
	t234_wdt_report();
	t234_wdt_apply(wdt_policy);

	t234_init_raminfo();

	/*
	 * Keep the shim's page. Its EL2 vectors stay installed — the library writes
	 * vbar_el2 only under -Q enable,el1-host — but they only *apply* while the
	 * CPU is still at EL2, which under -Q disable is a short window ending
	 * inside hypervisor_init. EL1 faults after that are ours to catch, which is
	 * what t234_install_el1_vectors is for. An earlier version of this comment
	 * claimed the shim covered all of startup; it does not, and the pre-flight
	 * review caught it before the image ran.
	 */
	avoid_ram(T234_SHIM_BASE, T234_SHIM_SIZE);
	if (fdt_size != 0) {
		avoid_ram((paddr_t)boot_regs[0], fdt_size);
		fdt_asinfo();          /* register the tree for qvm */
	}
	alloc_ram(shdr->ram_paddr, shdr->ram_size, 1);

	hypervisor_init(0);        /* must precede init_smp/init_mmu/init_qtime */
	init_smp();

	if (shdr->flags1 & STARTUP_HDR_FLAGS1_VIRTUAL) {
		init_mmu();
	}

	init_intrinfo();
	init_qtime();              /* no timer_freq override: CNTFRQ_EL0 is right */

	if (probe_hv) {
		t234_probe_hv_timer();
	}

	init_cacheattr();
	init_cpuinfo();
	init_hwinfo();

	add_typed_string(_CS_MACHINE, "NVIDIA Jetson Orin Nano Developer Kit (Tegra234)");

	init_system_private();

	/*
	 * Swap the library's unbounded AP release loop for the bounded one in
	 * board_smp.c. This line has exactly one correct place.
	 *
	 * smp_hook_rtn is called twice. The first call is inside
	 * init_system_private (lib/init_system_private.c:305), where it is still
	 * start_aps: that issues every CPU_ON and, on its way out, sets the hook to
	 * the library's transfer_aps (lib/init_smp.c:83). The second call is from
	 * _main after this function returns (lib/_main.c:156), and releases the
	 * parked cores. The override has to sit between the two. Installed any
	 * earlier — just after init_smp, say — the first call would run the
	 * release loop instead of start_aps and no core would ever be started;
	 * t234_transfer_aps checks for that and names it.
	 *
	 * At -P1 num_cpu is 1, the hook stays hook_dummy (lib/_main.c:165), and
	 * this is M1's path unchanged.
	 */
	if (lsp.syspage.p->num_cpu > 1) {
		smp_hook_rtn = t234_transfer_aps;
	}

	print_syspage();

	return 0;
}
