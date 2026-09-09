/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * The Tegra Combined UART as a startup debug device.
 *
 * This is what carries startup's own output — the banner, -vvv, the syspage
 * dump — before procnto exists and before any driver does. It is deliberately
 * the simplest thing that can work: map one register, poll one bit, write one
 * word per character.
 *
 * The port is not a UART. It is a shared mailbox in the AON HSP block that the
 * SPE drains and demultiplexes onto the physical debug wire. That is why there
 * is no clock to enable, no reset to deassert, no pinmux and no BPMP
 * transaction here: the CCPLEX's only job is to put a word in a register, and
 * everything else belongs to a processor we do not control and cannot see.
 *
 * The consequence, and the reason for the bounded poll: if the SPE stops
 * draining the mailbox, an unbounded wait would hang startup with no console
 * to say so, on a board nobody is standing next to. Bounded, it degrades to
 * dropped characters, which is recoverable and legible. The bound is an
 * iteration count rather than a real deadline because this runs before
 * init_qtime and there is no calibrated clock to spend yet — the userland
 * tcu-cat, which runs later, uses a proper one.
 */

#include "t234_startup.h"

#define TX_POLL_LIMIT   0x100000u   /* generous; only reached if the SPE is gone */

static uintptr_t tcu_tx;
static unsigned  tcu_drops;

void
init_tcu(unsigned channel, const char *init, const char *defaults)
{
	(void)channel;
	(void)init;
	(void)defaults;

	/*
	 * The device string is ignored on purpose. Both mailbox addresses are
	 * board constants that a command line has no business moving, and taking
	 * them from -D would make a typo look like dead hardware.
	 */
	tcu_tx = startup_io_map(sizeof(_Uint32t), T234_TCU_TX);

	/*
	 * A newline with both flush bits, which is what NVIDIA's own firmware
	 * sends to open the channel. It also makes the first real line start
	 * cleanly rather than appended to whatever Linux left mid-line.
	 */
	put_tcu('\n');
}

void
put_tcu(int c)
{
	unsigned limit = TX_POLL_LIMIT;
	_Uint32t w;

	if (tcu_tx == 0) {
		return;
	}

	while ((in32(tcu_tx) & TCU_FULL) != 0) {
		if (--limit == 0) {
			tcu_drops++;
			return;
		}
	}

	w = TCU_FULL | TCU_FLUSH | (1u << TCU_COUNT_SHIFT) | ((_Uint32t)c & 0xffu);
	out32(tcu_tx, w);
}

/*
 * How many characters the mailbox swallowed. Nothing calls this yet; it exists
 * so that a later milestone can print the count over whichever console did
 * survive, which is the difference between "the console is dead" and "startup
 * hung" — two failure modes that look identical from the far end of a wire.
 */
unsigned
tcu_drop_count(void)
{
	return tcu_drops;
}
