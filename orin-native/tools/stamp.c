/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * stamp — take a host-clock reading when a marker goes past.
 *
 * Phase 3b, docs/orin-native-port-plan.md M3; revised to the M3 design's
 * §3.8.1 (results/orin-native-port/20260909T1100Z/m3-design.md, revision 2).
 * The first hardware-timed number this port owes is the interval from launching
 * the hypervisor to the guest announcing itself. Both ends of that interval have
 * to be read on the same clock, on the machine under test, without a filesystem
 * or a network to carry a log off the board.
 *
 *   stamp -n [-q] [-l LABEL] [-r FILE] [-x PROG [ARG...]]
 *   stamp [-i INPUT] [-o FILE] [-m BYTES] [-r FILE] [-h DIR]
 *         -s TEXT [-l LABEL] [-s TEXT -l LABEL]...
 *
 * -n takes one reading now. With -x it then execv()s PROG in the same pid, so
 * the reading is the last thing before PROG's image starts:
 *
 *   stamp -n -q -l qvm_launch -r /dev/shmem/m3.stamps -x /proc/boot/qvm @/proc/boot/g2.conf
 *
 * Stream mode reads INPUT (stdin by default), forwards it to FILE (stdout by
 * default) and takes a reading the first time each TEXT passes. The guest
 * banner travels on the guest's pl011, which the qvm configuration binds to
 * qvm's stdout, so the M3 host puts qvm's stdio on the slave of pty pair 1 and
 * reads the master:
 *
 *   stamp -i /dev/ptyp1 -o /dev/shmem/m3.guest -r /dev/shmem/m3.stamps \
 *         -h /dev/shmem -s 'Startup complete' -l g_startup_complete \
 *         -s 'QNX qnx-guest' -l banner &
 *
 * The banner is never on /dev/ttyp0: that pair is the IPC channel (design C5).
 *
 * One line per event:
 *
 *   STAMP <label> cycles=<u64> cps=<u64> cpu=<n> mono_ns=<u64> bytes=<u64>
 *
 * cycles is ClockCycles(), taken first; cps is the system page's
 * cycles_per_sec, so the consumer converts rather than trusting a number this
 * program computed (31,250,000 on the board, 32 ns per tick); mono_ns is
 * CLOCK_MONOTONIC, taken next, as a cross-check; cpu is SchedGetCpuNum(); bytes
 * is the stream offset at the end of the chunk that fired, and 0 for -n. The
 * fields after cps= are appended, so a parser of the old two fields still works.
 *
 * In stream mode a reading is taken as soon as read() returns, before any
 * other work. Every needle first found in one chunk carries that chunk's
 * reading. With -h, DIR/open.hit is created once the input is open, DIR/<label>.hit
 * after that label's line has been written, and DIR/eof.hit when the input ends
 * or fails. Nothing is written to the console while the stream runs unless no
 * -o was given; stamp never writes to the input, never changes its termios and
 * never closes it before end of input or an error.
 *
 * What it deliberately does not do: it does not measure anything itself, it
 * does not average, and it does not decide what an interval means.
 *
 * Exit: 0 when every needle fired before end of input (or -n succeeded), 1
 * otherwise, 2 on a malformed command line, 127 when -x could not exec.
 */

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>
#include <sys/types.h>

#define MAX_NEEDLES     12
#define NEEDLE_MAX      256
#define LABEL_MAX       64
#define CHUNK           4096
#define DEFAULT_CAP     65536ull        /* bytes kept with -o unless -m says otherwise */
#define LINE_BUF        512
#define PATH_BUF        512

struct reading {
	uint64_t cycles;
	uint64_t mono_ns;
	unsigned cpu;
};

static uint64_t cps;

static void
take(struct reading *const r)
{
	struct timespec ts;

	r->cycles = ClockCycles();
	if (clock_gettime(CLOCK_MONOTONIC, &ts) == 0) {
		r->mono_ns = (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
	} else {
		r->mono_ns = 0;
	}
	r->cpu = SchedGetCpuNum();
}

/* The standard fields; returns the length written into line, or 0 if it did not fit. */
static size_t
format_line(char *const line, size_t const cap, const char *const head,
            const struct reading *const r, uint64_t const bytes, const char *const tail)
{
	int n = snprintf(line, cap, "STAMP %s cycles=%llu cps=%llu cpu=%u mono_ns=%llu bytes=%llu%s\n",
	                 head, (unsigned long long)r->cycles, (unsigned long long)cps, r->cpu,
	                 (unsigned long long)r->mono_ns, (unsigned long long)bytes, tail);

	return (n > 0 && (size_t)n < cap) ? (size_t)n : 0;
}

static int
write_all(int const fd, const char *p, size_t len)
{
	while (len > 0) {
		ssize_t const w = write(fd, p, len);

		if (w < 0) {
			if (errno == EINTR) {
				continue;
			}
			return -1;
		}
		p   += w;
		len -= (size_t)w;
	}
	return 0;
}

/* One write(2) per record line, so appends from several stamps do not interleave. */
static int
record_line(int const fd, const char *const line, size_t const len)
{
	ssize_t w;

	do {
		w = write(fd, line, len);
	} while (w < 0 && errno == EINTR);
	return (w == (ssize_t)len) ? 0 : -1;
}

static int
touch_hit(const char *const dir, const char *const name)
{
	char path[PATH_BUF];
	int  fd;
	int  n = snprintf(path, sizeof(path), "%s/%s.hit", dir, name);

	if (n <= 0 || (size_t)n >= sizeof(path)) {
		return -1;
	}
	fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0) {
		return -1;
	}
	(void)close(fd);
	return 0;
}

static int
usage(void)
{
	fprintf(stderr,
	        "usage: stamp -n [-q] [-l LABEL] [-r FILE] [-x PROG [ARG...]]\n"
	        "       stamp [-i INPUT] [-o FILE] [-m BYTES] [-r FILE] [-h DIR]\n"
	        "             -s TEXT [-l LABEL] [-s TEXT -l LABEL]...\n"
	        "  -n         take one reading now; -q: do not print it to stdout\n"
	        "  -x PROG    then execv PROG with the remaining arguments (last option)\n"
	        "  -r FILE    append each STAMP line to FILE with one write\n"
	        "  -i INPUT   read INPUT (opened O_RDWR, e.g. a pty master) instead of stdin\n"
	        "  -o FILE    forward the stream to FILE instead of stdout (needs -r)\n"
	        "  -m BYTES   store at most BYTES of the stream (default 65536 with -o)\n"
	        "  -h DIR     create DIR/open.hit, DIR/<label>.hit and DIR/eof.hit\n"
	        "  -s TEXT    1-256 bytes; up to 12, each paired with the -l after it\n"
	        "  -l LABEL   name the reading (default \"mark\" for a single -s or -n)\n");
	return 2;
}

static int
label_ok(const char *const s)
{
	size_t const n = strlen(s);

	if (n == 0 || n > LABEL_MAX) {
		return 0;
	}
	for (size_t i = 0; i < n; i++) {
		char const c = s[i];

		if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')
		      || c == '_' || c == '-' || c == '.')) {
			return 0;
		}
	}
	/* Names this program uses for its own lines and hit files. */
	return strcmp(s, "eof") != 0 && strcmp(s, "open") != 0
	       && strcmp(s, "read-error") != 0 && strcmp(s, "exec-failed") != 0;
}

static int
parse_u64(const char *const s, uint64_t *const v)
{
	char *end = NULL;

	if (s[0] < '0' || s[0] > '9') {
		return 0;
	}
	errno = 0;
	*v = strtoull(s, &end, 10);
	return errno == 0 && end != s && *end == '\0';
}

static int
run_now(const char *const label, const char *const rec, int const quiet, char **const xargv)
{
	struct reading r;
	char           line[LINE_BUF];
	size_t         len;
	int            fd = -1;

	/* Opened before the reading, so nothing but the write sits between it and the exec. */
	if (rec != NULL) {
		fd = open(rec, O_WRONLY | O_CREAT | O_APPEND, 0644);
		if (fd < 0) {
			fprintf(stderr, "stamp: open %s: %s\n", rec, strerror(errno));
		}
	}
	take(&r);
	len = format_line(line, sizeof(line), label, &r, 0, "");
	if (fd >= 0) {
		if (len == 0 || record_line(fd, line, len) != 0) {
			fprintf(stderr, "stamp: write %s failed\n", rec);
		}
		(void)close(fd);
	}
	if (!quiet && len > 0) {
		(void)write_all(STDOUT_FILENO, line, len);
	}
	if (xargv == NULL) {
		return (len > 0) ? 0 : 1;
	}

	(void)execv(xargv[0], xargv);

	int const e = errno;
	int       n = snprintf(line, sizeof(line), "STAMP exec-failed errno=%d prog=%s\n", e, xargv[0]);

	if (n <= 0 || (size_t)n >= sizeof(line)) {
		n = snprintf(line, sizeof(line), "STAMP exec-failed errno=%d prog=(too long)\n", e);
	}
	if (rec != NULL) {
		fd = open(rec, O_WRONLY | O_CREAT | O_APPEND, 0644);
		if (fd >= 0) {
			(void)record_line(fd, line, (size_t)n);
			(void)close(fd);
		}
	}
	(void)write_all(STDERR_FILENO, line, (size_t)n);
	return 127;
}

struct stream {
	const char *needle[MAX_NEEDLES];
	const char *label[MAX_NEEDLES];
	size_t      nlen[MAX_NEEDLES];
	int         fired[MAX_NEEDLES];
	unsigned    count;
	const char *hit_dir;
	int         rec_fd;             /* -1 without -r */
	int         to_stdout;          /* STAMP lines also to stdout: no -o */
	unsigned    rec_errors;
	unsigned    hit_errors;
};

static void
emit(struct stream *const st, const char *const head, const struct reading *const r,
     uint64_t const bytes, const char *const tail)
{
	char         line[LINE_BUF];
	size_t const len = format_line(line, sizeof(line), head, r, bytes, tail);

	if (len == 0) {
		st->rec_errors++;
		return;
	}
	if (st->rec_fd >= 0 && record_line(st->rec_fd, line, len) != 0) {
		st->rec_errors++;
	}
	if (st->to_stdout) {
		(void)write_all(STDOUT_FILENO, line, len);
	}
}

static int
run_stream(struct stream *const st, const char *const in_path, const char *const out_path,
           const char *const rec, uint64_t const cap, int const have_cap)
{
	static char    buf[CHUNK];
	static char    window[NEEDLE_MAX + CHUNK];
	char           keep[NEEDLE_MAX];
	size_t         keptlen  = 0;
	size_t         longest  = 0;
	uint64_t       total    = 0;
	uint64_t       stored   = 0;
	unsigned       nfired   = 0;
	unsigned       fwd_errs = 0;
	int            in_fd    = STDIN_FILENO;
	int            out_fd   = STDOUT_FILENO;
	struct reading r;
	char           tail[160];

	/* A reader of a closed pipe should count the failure, not die of it. */
	(void)signal(SIGPIPE, SIG_IGN);

	for (unsigned k = 0; k < st->count; k++) {
		if (st->nlen[k] > longest) {
			longest = st->nlen[k];
		}
	}
	if (rec != NULL) {
		st->rec_fd = open(rec, O_WRONLY | O_CREAT | O_APPEND, 0644);
		if (st->rec_fd < 0) {
			fprintf(stderr, "stamp: open %s: %s\n", rec, strerror(errno));
			return 1;
		}
	}
	if (out_path != NULL) {
		out_fd = open(out_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
		if (out_fd < 0) {
			fprintf(stderr, "stamp: open %s: %s\n", out_path, strerror(errno));
			return 1;
		}
	}
	if (in_path != NULL) {
		in_fd = open(in_path, O_RDWR | O_NOCTTY);
		if (in_fd < 0) {
			fprintf(stderr, "stamp: open %s: %s\n", in_path, strerror(errno));
			return 1;
		}
	}
	if (st->hit_dir != NULL && touch_hit(st->hit_dir, "open") != 0) {
		st->hit_errors++;
	}

	for (;;) {
		ssize_t const n = read(in_fd, buf, sizeof(buf));

		if (n > 0) {
			size_t fw = (size_t)n;

			take(&r);           /* before any other work */
			total += (uint64_t)n;

			if (have_cap) {
				uint64_t const room = (cap > stored) ? cap - stored : 0;

				if ((uint64_t)fw > room) {
					fw = (size_t)room;
				}
			}
			if (fw > 0) {
				if (write_all(out_fd, buf, fw) != 0) {
					fwd_errs++;
				} else {
					stored += (uint64_t)fw;
				}
			}

			if (nfired < st->count) {
				size_t wlen;
				size_t keepn;

				memcpy(window, keep, keptlen);
				memcpy(window + keptlen, buf, (size_t)n);
				wlen = keptlen + (size_t)n;

				for (unsigned k = 0; k < st->count; k++) {
					if (st->fired[k]
					    || memmem(window, wlen, st->needle[k], st->nlen[k]) == NULL) {
						continue;
					}
					emit(st, st->label[k], &r, total, "");
					if (st->hit_dir != NULL && touch_hit(st->hit_dir, st->label[k]) != 0) {
						st->hit_errors++;
					}
					st->fired[k] = 1;
					nfired++;
				}

				keepn = longest - 1;
				if (keepn > wlen) {
					keepn = wlen;
				}
				memcpy(keep, window + wlen - keepn, keepn);
				keptlen = keepn;
			}
			continue;
		}

		if (n < 0 && errno == EINTR) {
			continue;
		}

		int const e = (n < 0) ? errno : 0;

		take(&r);
		(void)snprintf(tail, sizeof(tail), " stored=%llu fired=%u/%u fwd_errors=%u rec_errors=%u hit_errors=%u",
		               (unsigned long long)stored, nfired, st->count, fwd_errs, st->rec_errors,
		               st->hit_errors);
		if (n == 0) {
			emit(st, "eof", &r, total, tail);
		} else {
			char head[32];

			(void)snprintf(head, sizeof(head), "read-error errno=%d", e);
			emit(st, head, &r, total, tail);
		}
		if (st->hit_dir != NULL) {
			(void)touch_hit(st->hit_dir, "eof");
		}
		return (n == 0 && nfired == st->count) ? 0 : 1;
	}
}

int
main(int argc, char **argv)
{
	struct stream st;
	int           now      = 0;
	int           quiet    = 0;
	const char   *rec      = NULL;
	const char   *in_path  = NULL;
	const char   *out_path = NULL;
	const char   *pending  = NULL;      /* a -l given before any -s */
	const char   *label_n  = NULL;      /* the -l of -n mode */
	char        **xargv    = NULL;
	uint64_t      cap      = 0;
	int           have_cap = 0;
	unsigned      nlabels  = 0;

	memset(&st, 0, sizeof(st));
	st.rec_fd = -1;

	for (int i = 1; i < argc; i++) {
		const char *const a = argv[i];

		if (strcmp(a, "-n") == 0) {
			now = 1;
		} else if (strcmp(a, "-q") == 0) {
			quiet = 1;
		} else if (strcmp(a, "-x") == 0) {
			if (i + 1 >= argc) {
				return usage();
			}
			xargv = &argv[i + 1];
			break;          /* option parsing stops at -x */
		} else if (i + 1 < argc && strcmp(a, "-s") == 0) {
			const char *const v = argv[++i];
			size_t const      l = strlen(v);

			if (st.count == MAX_NEEDLES || l == 0 || l > NEEDLE_MAX) {
				return usage();
			}
			st.needle[st.count] = v;
			st.nlen[st.count]   = l;
			st.count++;
		} else if (i + 1 < argc && strcmp(a, "-l") == 0) {
			const char *const v = argv[++i];

			if (!label_ok(v)) {
				return usage();
			}
			nlabels++;
			if (st.count == 0) {
				if (pending != NULL) {
					return usage();
				}
				pending = v;
			} else if (st.label[st.count - 1] == NULL) {
				st.label[st.count - 1] = v;
			} else {
				return usage();     /* a second -l after one -s */
			}
		} else if (i + 1 < argc && strcmp(a, "-r") == 0 && rec == NULL) {
			rec = argv[++i];
		} else if (i + 1 < argc && strcmp(a, "-i") == 0 && in_path == NULL) {
			in_path = argv[++i];
		} else if (i + 1 < argc && strcmp(a, "-o") == 0 && out_path == NULL) {
			out_path = argv[++i];
		} else if (i + 1 < argc && strcmp(a, "-m") == 0 && !have_cap) {
			if (!parse_u64(argv[++i], &cap)) {
				return usage();
			}
			have_cap = 1;
		} else if (i + 1 < argc && strcmp(a, "-h") == 0 && st.hit_dir == NULL) {
			st.hit_dir = argv[++i];
		} else {
			return usage();
		}
	}

	if (now) {
		if (st.count != 0 || in_path != NULL || out_path != NULL || have_cap
		    || st.hit_dir != NULL || nlabels > 1) {
			return usage();
		}
		label_n = (pending != NULL) ? pending : "mark";
	} else {
		if (quiet || xargv != NULL || st.count == 0 || (out_path != NULL && rec == NULL)) {
			return usage();
		}
		if (pending != NULL) {
			if (st.count != 1 || st.label[0] != NULL) {
				return usage();
			}
			st.label[0] = pending;
		}
		if (st.count == 1 && st.label[0] == NULL) {
			st.label[0] = "mark";
		}
		for (unsigned k = 0; k < st.count; k++) {
			if (st.label[k] == NULL) {
				return usage();     /* two or more -s without their -l */
			}
			for (unsigned j = 0; j < k; j++) {
				if (strcmp(st.label[j], st.label[k]) == 0) {
					return usage();
				}
			}
		}
		if (out_path != NULL && !have_cap) {
			cap      = DEFAULT_CAP;
			have_cap = 1;
		}
		st.to_stdout = (out_path == NULL);
	}

	cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
	if (cps == 0) {
		fprintf(stderr, "stamp: qtime reports no cycles_per_sec\n");
		return 1;
	}

	if (now) {
		return run_now(label_n, rec, quiet, xargv);
	}
	return run_stream(&st, in_path, out_path, rec, cap, have_cap);
}
