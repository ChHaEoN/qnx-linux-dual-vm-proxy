/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * The watchdogs.
 *
 * The plan originally recorded that nothing was counting at hand-off, because
 * the device tree's watchdog node is disabled. That was the wrong node: the
 * driver binds through the timer block, systemd configures WDT0 at two minutes,
 * and a register read at hand-over shows it still configured.
 *
 * The M0 hang test then showed that it does not fire after `systemctl kexec`:
 * the shim, parked in wfi with nothing feeding the watchdog, stayed unreachable
 * well past two minutes and had to be power-cycled by hand
 * (results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md). Most likely
 * systemd hands the device back on its way out (HYPOTHESIS, from that note).
 * So a hang costs a power cycle, which also empties the black box, and there is
 * no two-minute ceiling on a run either.
 *
 * -W is kept, defaulting to keep: as insurance against the opposite finding on
 * another hand-over path, and for parity with the runs so far. Reporting is
 * unconditional: the two register values go out before anything else can go
 * wrong, so even a run that dies immediately afterwards says what it inherited.
 *
 * What is not implemented here, deliberately: arming. The board comes up with
 * it configured already, and a startup that arms a watchdog it did not verify it
 * can feed is a way to lose a board rather than recover one.
 *
 * The EL2 virtual-timer probe that used to end this file as a stub is now the
 * automatic el2-host probe in aarch64/hvtimer.c.
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
		kprintf("t234: WDT0 is configured, but it did not fire after the kexec hand-over (M0 hang test): a hang from here needs a power cycle\n");
	}
}

void
t234_wdt_apply(const char *policy)
{
	if (policy == NULL || strcmp(policy, "keep") == 0) {
		/* Leave it exactly as inherited. The default, for parity; the
		 * header says why it is not a way back from a hang. */
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
