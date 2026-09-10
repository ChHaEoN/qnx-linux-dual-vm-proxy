/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * crash_done — reset instead of parking forever.
 *
 * Every ASSERT and every crash() in the startup library ends here, and the
 * library's own AArch64 version is `while (1) wfi`. On a board with a debugger
 * attached that is exactly right: the machine stops with its registers intact
 * for someone to look at. On this one it is the worst possible ending.
 *
 * The reason is measured rather than assumed. This board's watchdog does not
 * fire after the kexec hand-over — tested, see
 * results/orin-native-port/20260909T1100Z/m0-hang-watchdog.md — so a parked CPU
 * needs a human to pull the power, and a cold power cycle wipes the DRAM region
 * the crash message was just written into. So the library's ending turns a
 * loud, diagnosed failure into a silent one: the message is composed, printed
 * into a buffer that is about to be erased, and then the machine sits there
 * until someone erases it.
 *
 * Resetting instead keeps everything. The message has already gone out through
 * kprintf by the time this is called, and a PSCI reset is warm, so the black box
 * survives and the whole crash text is waiting in pstore on the next boot.
 *
 * This overrides the library's version by ordinary archive resolution: the
 * board object is linked before libstartup.a is scanned, so this definition
 * satisfies the reference and the library's member is never pulled. The build
 * script counts the definitions to make sure that is still true.
 */

#include "t234_startup.h"
#include <aarch64/psci.h>

void
crash_done(void)
{
	/*
	 * Give the console a moment to drain. put_tcu polls the mailbox before
	 * each character, so by the time control reaches here the bytes are in
	 * the SPE's hands, but the black-box writes are ordinary stores and a
	 * barrier costs nothing next to a reset.
	 */
	__asm__ __volatile__("dsb sy" ::: "memory");

	if (psci_call != 0) {
		(void)psci_call(PSCI_SYSTEM_RESET, 0, 0, 0);
	}

	/*
	 * PSCI did not reset us, which should not happen on this firmware. There
	 * is nothing left to try, so do what the library would have done and stop
	 * — but the message and the reason are already in the black box, which is
	 * the whole point of getting this far.
	 */
	while (1) {
		__asm__ __volatile__("wfi");
	}
}
