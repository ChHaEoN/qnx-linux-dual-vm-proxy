/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * stamp — take a host-clock reading when a marker goes past.
 *
 * Phase 3b, docs/orin-native-port-plan.md §7 M3. The first hardware-timed
 * number this port owes is the interval from launching the hypervisor to the
 * guest announcing itself. Both ends of that interval have to be read on the
 * same clock, on the machine under test, without a filesystem or a network to
 * carry a log off the board.
 *
 *   stamp -n                                   print a reading and exit
 *   stamp -s 'QNX qnx-guest' < /dev/ttyp0      print one when that text passes
 *
 * In -s mode the input is forwarded to stdout unchanged, so it can sit in a
 * pipe that is doing something else with the same stream:
 *
 *   stamp -s 'Startup complete' < /dev/ttyp0 | tcu-cat &
 *
 * The reading is ClockCycles(), the free-running counter, together with the
 * cycles-per-second the system page reports, so the consumer converts rather
 * than trusting a number this program computed. On this board that counter is
 * the ARM generic timer at 31.25 MHz, i.e. 32 ns per tick — stated rather than
 * assumed, because the conversion is the part that quietly goes wrong.
 *
 * What it deliberately does not do: it does not measure anything itself, it
 * does not average, and it does not decide what an interval means. It prints
 * one line per event and leaves the arithmetic to whoever reads them.
 */

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

static void
emit(const char *label, uint64_t cycles, uint64_t cps)
{
	printf("STAMP %s cycles=%llu cps=%llu\n",
	       label, (unsigned long long)cycles, (unsigned long long)cps);
	fflush(stdout);
}

int
main(int argc, char **argv)
{
	const char *needle = NULL;
	const char *label  = "mark";
	int         now    = 0;
	int         opt;
	uint64_t    cps;

	while ((opt = getopt(argc, argv, "ns:l:")) != -1) {
		switch (opt) {
		case 'n':
			now = 1;
			break;
		case 's':
			needle = optarg;
			break;
		case 'l':
			label = optarg;
			break;
		default:
			fprintf(stderr,
			        "usage: %s -n | -s <substring> [-l label]\n"
			        "  -n            print one reading now and exit\n"
			        "  -s <text>     copy stdin to stdout, print a reading the first\n"
			        "                time <text> appears\n"
			        "  -l <label>    name the reading (default \"mark\")\n", argv[0]);
			return 2;
		}
	}

	cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
	if (cps == 0) {
		fprintf(stderr, "stamp: qtime reports no cycles_per_sec\n");
		return 1;
	}

	if (now) {
		emit(label, ClockCycles(), cps);
		return 0;
	}
	if (needle == NULL) {
		fprintf(stderr, "stamp: one of -n or -s is required\n");
		return 2;
	}

	/*
	 * Match across read boundaries: keep the tail of what has been seen, so a
	 * marker split over two reads is still found. The window is the needle
	 * length minus one, which is all that can matter.
	 */
	size_t nlen = strlen(needle);
	if (nlen == 0 || nlen > 256) {
		fprintf(stderr, "stamp: -s needs 1 to 256 characters\n");
		return 2;
	}

	char    keep[256];
	size_t  keptlen = 0;
	char    buf[1024];
	ssize_t n;
	int     fired = 0;

	while ((n = read(STDIN_FILENO, buf, sizeof(buf))) > 0) {
		/* Forward first: never delay the stream for our own bookkeeping. */
		if (write(STDOUT_FILENO, buf, (size_t)n) != n) {
			fprintf(stderr, "stamp: write: %s\n", strerror(errno));
			return 1;
		}

		if (!fired) {
			char   window[sizeof(keep) + sizeof(buf)];
			size_t wlen = 0;

			memcpy(window, keep, keptlen);
			wlen = keptlen;
			memcpy(window + wlen, buf, (size_t)n);
			wlen += (size_t)n;

			if (memmem(window, wlen, needle, nlen) != NULL) {
				emit(label, ClockCycles(), cps);
				fired = 1;
			} else {
				size_t tail = nlen - 1;
				if (tail > wlen) {
					tail = wlen;
				}
				memcpy(keep, window + wlen - tail, tail);
				keptlen = tail;
			}
		}
	}
	if (n < 0) {
		fprintf(stderr, "stamp: read: %s\n", strerror(errno));
		return 1;
	}
	return fired ? 0 : 1;      /* never saw it: say so in the exit status */
}
