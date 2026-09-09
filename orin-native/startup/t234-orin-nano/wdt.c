/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * The watchdogs, which on this board are load-bearing in both directions.
 *
 * The plan originally recorded that nothing was counting at hand-off, because
 * the device tree's watchdog node is disabled. That was the wrong node: the
 * driver binds through the timer block, systemd arms it at two minutes, and a
 * register read on the running board shows WDT0 counting. So:
 *
 *   - a milestone that hangs gets the board back on its own, with nobody
 *     standing next to it. That is worth more than it sounds when the only
 *     alternative is a manual power cycle.
 *   - a milestone that legitimately takes longer than two minutes — M3's guest
 *     boot plus M4's trace capture over an 11 KB/s console — will be killed
 *     mid-measurement unless the watchdog is disabled or someone kicks it.
 *
 * Hence -W, defaulting to keep. Reporting is unconditional: the two register
 * values go out before anything else can go wrong, so even a run that dies
 * immediately afterwards says what it inherited.
 *
 * What is not implemented here, deliberately: arming. The board comes up with
 * it armed already, and a startup that arms a watchdog it did not verify it can
 * feed is a way to lose a board rather than recover one.
 */

#include "t234_startup.h"

static _Uint32t
wdt_rd(_Uint64t base, unsigned off)
{
	return in32(startup_io_map(0x10u, base) + off);
}

void
t234_wdt_report(void)
{
	_Uint32t cr0 = wdt_rd(T234_WDT0_BASE, T234_WDT_CR);
	_Uint32t sr0 = wdt_rd(T234_WDT0_BASE, T234_WDT_SR);
	_Uint32t cr1 = wdt_rd(T234_WDT1_BASE, T234_WDT_CR);
	_Uint32t sr1 = wdt_rd(T234_WDT1_BASE, T234_WDT_SR);

	kprintf("t234: WDT0 CR=%x SR=%x  WDT1 CR=%x SR=%x\n", cr0, sr0, cr1, sr1);

	if (cr0 != 0) {
		kprintf("t234: WDT0 is armed — this run has about two minutes unless -Wdisable\n");
	}
}

void
t234_wdt_apply(const char *policy)
{
	if (policy == NULL || strcmp(policy, "keep") == 0) {
		/* Leave it exactly as inherited. The default, because an armed
		 * watchdog is the only unattended way back from a hang. */
		return;
	}

	if (strcmp(policy, "disable") == 0) {
		uintptr_t base = startup_io_map(0x10u, T234_WDT0_BASE);

		/* Unlock, then command a disable. The unlock value is the one the
		 * upstream Linux driver uses for this block; whether NS-EL2 is
		 * permitted to write it at all is untested — if the register is
		 * locked this write is silently ignored and the report below will
		 * still show it counting, which is the signal that a kicker is
		 * needed instead. */
		out32(base + T234_WDT_UR, T234_WDT_UNLOCK);
		out32(base + T234_WDT_CMDR, T234_WDT_CMD_DISABLE);

		kprintf("t234: WDT0 disable requested, CR now %x\n",
		        wdt_rd(T234_WDT0_BASE, T234_WDT_CR));
		return;
	}

	kprintf("t234: -W%s not understood, leaving the watchdog as inherited\n", policy);
}

/*
 * The EL2 virtual timer probe, behind -t.
 *
 * In el2-host mode the library sets the system timer's interrupt to INTID 28,
 * the non-secure EL2 virtual timer PPI, unconditionally — it does not check
 * that anything wired it. Tegra234's device tree lists only PPIs 13, 14, 11 and
 * 10, and Linux never uses 28, so whether the GIC sees it on this silicon is
 * genuinely unknown and is the single fact that decides whether M3 produces a
 * VHE number or an EL1-host one wearing a different label.
 *
 * The probe: arm CNTHV to fire almost immediately, then look at the boot CPU's
 * redistributor pending register for bit 28. It reports and clears; it never
 * takes the interrupt.
 */
void
t234_probe_hv_timer(void)
{
	/*
	 * Not implemented yet — and saying so is better than a probe that reports
	 * "absent" because it was written wrong. Writing it needs the SGI frame
	 * address for the boot CPU's redistributor, which is the frame the library
	 * has already located during gic_v3_initialize but does not expose; the
	 * honest way in is a small accessor rather than recomputing the walk here
	 * and getting a different answer than the library did.
	 *
	 * Until then M1 runs -Q disable and M1b runs -Q enable,el2-host, and if the
	 * hypervisor comes up and its timeouts work, INTID 28 is wired — which is
	 * the same answer by a slower route.
	 */
	kprintf("t234: -t requested, but the EL2 virtual-timer probe is not implemented\n");
}
