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
 *   tcu-cat [-m MESSAGE] [-a N] [-T SECS] [-s]
 *   tcu-cat [-f FILE] [-a N] [-T SECS] [-s]
 *
 *   pidin | tcu-cat                          (stdin, as M1-M3 images use it)
 *   tcu-cat -m "M1: user space up"
 *   tcu-cat -a 50 -T 220 -s -f /dev/shmem/flt.v   (the M4 host script: no pipe)
 *
 * Revised for M4 (results/orin-native-port/20260909T1100Z/m4-design.md §5.1),
 * backward-compatible: without -f, -a, -T and -s it behaves exactly as before.
 *
 *   -m MESSAGE  MESSAGE plus a newline (unchanged)
 *   -f FILE     read FILE instead of stdin; -f with -m is a usage error. Under
 *               bwait -k stdin is /dev/null, so the M4 script needs this.
 *   -a N        abort after N consecutive words whose mailbox stayed full
 *               (N 1-100000); default: never abort
 *   -T SECS     stop reading at SECS seconds after start by ClockCycles()
 *               (1-86400); default: no deadline
 *   -s          one summary line to stderr at the end:
 *               tcu-cat: bytes_in=<n> bytes_sent=<n> drops=<n> timeouts=<n>
 *                        max_consecutive=<n> aborted=<0|1> deadline=<0|1> ms=<n> rc=<n>
 *               (one line; bytes_sent counts bytes in words the mailbox accepted)
 *
 * -a and -T are checked after every word; on abort or deadline the rest of the
 * input is not sent. A dead SPE otherwise costs one 20 ms poll per 1-3 bytes,
 * and a bwait kill would lose the drop count.
 *
 * Exit: 0 every byte accepted; 1 drops, or a map, open or read error (as
 * before); 2 usage; 3 aborted by -a; 4 stopped by -T.
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
#include <fcntl.h>
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

#define ABORT_MAX       100000ul
#define DEADLINE_MAX_S  86400ul

static volatile uint32_t *tx;
static uint64_t           cps;          /* ClockCycles() per second */
static unsigned long      drops;
static unsigned long      bytes_sent;
static unsigned long      timeouts;     /* words whose mailbox stayed full */
static unsigned long      consecutive;
static unsigned long      max_consecutive;
static unsigned long      abort_after;  /* 0: never */
static uint64_t           deadline;     /* 0: none */
static int                aborted;
static int                deadline_hit;

/* Wait for the SPE to take the previous word. Returns 0 on timeout. */
static int
mailbox_ready(void)
{
	uint64_t deadline_poll = ClockCycles() + (cps / (1000 / POLL_MS));

	while ((*tx & MB_FULL) != 0) {
		if (ClockCycles() > deadline_poll) {
			return 0;
		}
	}
	return 1;
}

/* One word of 1-3 bytes. Returns 1 when the mailbox took it, 0 when dropped. */
static int
put_bytes(const unsigned char *b, unsigned n)
{
	uint32_t w;

	if (n == 0 || n > 3) {
		return 1;
	}
	if (!mailbox_ready()) {
		drops += n;
		timeouts++;
		consecutive++;
		if (consecutive > max_consecutive) {
			max_consecutive = consecutive;
		}
		if (abort_after != 0 && consecutive >= abort_after) {
			aborted = 1;
		}
		return 0;
	}

	consecutive = 0;
	w = MB_FULL | MB_FLUSH | ((uint32_t)n << MB_COUNT_SHIFT);
	for (unsigned i = 0; i < n; i++) {
		w |= (uint32_t)b[i] << (8 * i);
	}
	*tx = w;
	bytes_sent += n;
	return 1;
}

/* After every word: 1 when -a or -T says stop. Without either, never. */
static int
stop_now(void)
{
	if (aborted) {
		return 1;
	}
	if (deadline != 0 && ClockCycles() >= deadline) {
		deadline_hit = 1;
		return 1;
	}
	return 0;
}

/* Returns 1 when -a or -T stopped the copy part-way. */
static int
put_buf(const unsigned char *b, size_t len)
{
	while (len > 0) {
		unsigned const n = (len >= 3) ? 3u : (unsigned)len;

		(void)put_bytes(b, n);
		b += n;
		len -= n;
		if (stop_now()) {
			return 1;
		}
	}
	return 0;
}

static int
usage(const char *const prog)
{
	fprintf(stderr,
	        "usage: %s [-m message] [-a N] [-T secs] [-s]   (otherwise copies stdin)\n"
	        "       %s [-f file] [-a N] [-T secs] [-s]\n"
	        "  -a N abort after N consecutive full-mailbox words (1-%lu)\n"
	        "  -T SECS stop at SECS seconds (1-%lu); -s summary line to stderr\n"
	        "  exit: 0 all sent, 1 drops or error, 2 usage, 3 aborted, 4 deadline\n",
	        prog, prog, ABORT_MAX, DEADLINE_MAX_S);
	return 2;
}

static int
parse_range(const char *const s, unsigned long const lo, unsigned long const hi, unsigned long *const v)
{
	char         *end = NULL;
	unsigned long x;

	if (s[0] < '0' || s[0] > '9') {
		return 0;
	}
	errno = 0;
	x = strtoul(s, &end, 10);
	if (errno != 0 || *end != '\0' || x < lo || x > hi) {
		return 0;
	}
	*v = x;
	return 1;
}

static unsigned long long
cycles_to_ms(uint64_t const d)
{
	return (unsigned long long)(d / cps * 1000u + (d % cps) * 1000u / cps);
}

int
main(int argc, char **argv)
{
	const char   *msg     = NULL;
	const char   *file    = NULL;
	int           summary = 0;
	int           io_err  = 0;
	int           opt;
	int           rc;
	int           fd      = STDIN_FILENO;
	unsigned long secs    = 0;
	unsigned long bytes_in = 0;
	uint64_t      t0;

	while ((opt = getopt(argc, argv, "m:f:a:T:s")) != -1) {
		switch (opt) {
		case 'm':
			msg = optarg;
			break;
		case 'f':
			file = optarg;
			break;
		case 'a':
			if (!parse_range(optarg, 1ul, ABORT_MAX, &abort_after)) {
				return usage(argv[0]);
			}
			break;
		case 'T':
			if (!parse_range(optarg, 1ul, DEADLINE_MAX_S, &secs)) {
				return usage(argv[0]);
			}
			break;
		case 's':
			summary = 1;
			break;
		default:
			return usage(argv[0]);
		}
	}
	if (msg != NULL && file != NULL) {
		return usage(argv[0]);
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

	t0 = ClockCycles();
	if (secs != 0) {
		deadline = t0 + (uint64_t)secs * cps;
	}

	if (msg != NULL) {
		size_t const len = strlen(msg);

		bytes_in = (unsigned long)len + 1u;
		if (!put_buf((const unsigned char *)msg, len)) {
			(void)put_buf((const unsigned char *)"\n", 1);
		}
	} else {
		unsigned char buf[512];
		ssize_t       n = 0;

		if (file != NULL) {
			fd = open(file, O_RDONLY);
			if (fd < 0) {
				fprintf(stderr, "tcu-cat: open %s: %s\n", file, strerror(errno));
				io_err = 1;
			}
		}
		while (!io_err && (n = read(fd, buf, sizeof(buf))) > 0) {
			bytes_in += (unsigned long)n;
			if (put_buf(buf, (size_t)n)) {
				break;
			}
		}
		if (!io_err && n < 0) {
			fprintf(stderr, "tcu-cat: read: %s\n", strerror(errno));
			io_err = 1;
		}
		if (file != NULL && fd >= 0) {
			(void)close(fd);
		}
	}

	if (io_err) {
		rc = 1;
	} else if (aborted) {
		rc = 3;
	} else if (deadline_hit) {
		rc = 4;
	} else if (drops != 0) {
		rc = 1;
	} else {
		rc = 0;
	}

	if (summary) {
		fprintf(stderr,
		        "tcu-cat: bytes_in=%lu bytes_sent=%lu drops=%lu timeouts=%lu max_consecutive=%lu"
		        " aborted=%d deadline=%d ms=%llu rc=%d\n",
		        bytes_in, bytes_sent, drops, timeouts, max_consecutive,
		        aborted, deadline_hit, cycles_to_ms(ClockCycles() - t0), rc);
	} else if (!io_err && drops != 0) {
		/* Not to the TCU — if it swallowed bytes it will swallow this too. */
		fprintf(stderr, "tcu-cat: %lu bytes dropped, the mailbox stayed full\n", drops);
	}
	return rc;
}
