/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * tcu-cat — put bytes on the Tegra Combined UART from QNX user space.
 *
 * Phase 3b, docs/orin-native-port-plan.md §4.2. The board has no console a
 * normal program can write to: the only wire out is the TCU, and the TCU is a
 * mailbox in the AON HSP block rather than a UART with a driver. This maps that
 * one register and writes to it. No resource manager, no driver, nothing on the
 * critical path of a milestone that has to work before anything else does.
 *
 *   pidin | tcu-cat
 *   traceprinter -f /dev/shmem/t.kev | grep QVM | tcu-cat
 *   tcu-cat -m "M1: user space up"
 *
 * The mailbox word, established from two BSD-licensed references that agree
 * (edk2-nvidia's TegraCombinedSerialPortLib and TF-A's Tegra shared console):
 *
 *   bits 23:0   up to three data bytes, byte i in bits 8i..8i+7
 *   bits 25:24  how many of them are valid, 1 to 3
 *   bit 26      Flush
 *   bit 27      HwFlush
 *   bit 31      FULL — the writer sets it, the SPE clears it when it consumes
 *
 * So the protocol is: wait for FULL to clear, then write. The wait is bounded.
 * If the SPE has stopped servicing the mailbox this program must degrade to
 * dropping bytes, never to hanging — the same rule the M0 shim follows, for the
 * same reason: nobody is standing next to the board.
 */

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

#define TCU_TX_PADDR    0x0C168000u     /* AON HSP shared mailbox 1 */

#define MB_FULL         (1u << 31)
#define MB_HWFLUSH      (1u << 27)
#define MB_FLUSH        (1u << 26)
#define MB_COUNT_SHIFT  24

#define POLL_MS         20              /* how long to wait on a busy mailbox */

static volatile uint32_t *tx;
static uint64_t           cps;          /* ClockCycles() per second */
static unsigned long      drops;

/* Wait for the SPE to take the previous word. Returns 0 on timeout. */
static int
mailbox_ready(void)
{
	uint64_t deadline = ClockCycles() + (cps / (1000 / POLL_MS));

	while ((*tx & MB_FULL) != 0) {
		if (ClockCycles() > deadline) {
			return 0;
		}
	}
	return 1;
}

static void
put_bytes(const unsigned char *b, unsigned n)
{
	uint32_t w;

	if (n == 0 || n > 3) {
		return;
	}
	if (!mailbox_ready()) {
		drops += n;
		return;
	}

	w = MB_FULL | MB_FLUSH | ((uint32_t)n << MB_COUNT_SHIFT);
	for (unsigned i = 0; i < n; i++) {
		w |= (uint32_t)b[i] << (8 * i);
	}
	*tx = w;
}

static void
put_buf(const unsigned char *b, size_t len)
{
	while (len >= 3) {
		put_bytes(b, 3);
		b += 3;
		len -= 3;
	}
	if (len > 0) {
		put_bytes(b, (unsigned)len);
	}
}

int
main(int argc, char **argv)
{
	const char *msg = NULL;
	int         opt;

	while ((opt = getopt(argc, argv, "m:")) != -1) {
		switch (opt) {
		case 'm':
			msg = optarg;
			break;
		default:
			fprintf(stderr, "usage: %s [-m message]   (otherwise copies stdin)\n", argv[0]);
			return 2;
		}
	}

	cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
	if (cps == 0) {
		fprintf(stderr, "tcu-cat: qtime reports no cycles_per_sec\n");
		return 1;
	}

	tx = mmap_device_memory(NULL, sizeof(uint32_t),
	                        PROT_READ | PROT_WRITE | PROT_NOCACHE, 0,
	                        TCU_TX_PADDR);
	if (tx == MAP_FAILED) {
		fprintf(stderr, "tcu-cat: cannot map the TCU mailbox at 0x%08x: %s\n",
		        TCU_TX_PADDR, strerror(errno));
		return 1;
	}

	if (msg != NULL) {
		put_buf((const unsigned char *)msg, strlen(msg));
		put_bytes((const unsigned char *)"\n", 1);
	} else {
		unsigned char buf[512];
		ssize_t       n;

		while ((n = read(STDIN_FILENO, buf, sizeof(buf))) > 0) {
			put_buf(buf, (size_t)n);
		}
		if (n < 0) {
			fprintf(stderr, "tcu-cat: read: %s\n", strerror(errno));
			return 1;
		}
	}

	if (drops != 0) {
		/* Not to the TCU — if it swallowed bytes it will swallow this too. */
		fprintf(stderr, "tcu-cat: %lu bytes dropped, the mailbox stayed full\n", drops);
		return 1;
	}
	return 0;
}
