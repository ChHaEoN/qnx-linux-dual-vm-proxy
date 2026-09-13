/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * s1con — stamp's stream mode on the S1 guest console, plus a few bounded writes.
 *
 * Phase 3b, the S1-F design's §3.4 and §4.2 (results/orin-native-port/
 * 20260909T1100Z/s1-design.md, revision 2). The Linux guest's shell is on hvc0,
 * a virtio-console whose host end is the slave of pty pair 3. COM3 is
 * receive-only, so the only way to show that the shell reads a line is for the
 * host to type one and look for an answer the typed text cannot contain. stamp
 * never writes to its input and is not edited, so its instrument hash holds;
 * this program is stamp's stream mode with the writes added.
 *
 *   s1con [-i DEV [-O] [-R]] [-o FILE] [-m BYTES] [-r FILE] [-h DIR] [-d SECS]
 *         -s TEXT [-l LABEL] [-s TEXT -l LABEL]...
 *         [-w LABEL=TEXT]... [-t FILE=TEXT]...
 *
 * -i, -o, -m, -r, -h, -s and -l are stamp's, with stamp's bounds (12 needles of
 * 1-256 bytes, 64-byte labels, 4 KiB reads, 65536 bytes stored with -o unless -m
 * says otherwise), stamp's STAMP line and stamp's hit files. stamp's -n, -q and
 * -x are not carried: stamp takes those readings.
 *
 * The hit names are stamp's too: DIR/open.hit and DIR/eof.hit. S1 runs stamp on
 * /dev/ptyp2 while s1con runs on /dev/ptyp3 (design §6.3, §6.8, §6.9), so the two
 * need different -h DIRs, or one tool's open.hit or eof.hit satisfies a wait
 * meant for the other. Give them different -r files as well: a shared record
 * gets two STAMP eof lines that cannot be told apart. s1con does not create DIR.
 * If DIR is missing, the open and needle hits count as hit_errors, and the
 * host's wait on DIR/open.hit fails.
 *
 * -O opens DEV read-write (O_RDWR | O_NOCTTY). Without it DEV is opened
 *    read-only, unlike stamp, so a console that is only watched cannot be typed
 *    into. -w and -t need -O.
 * -R sets DEV raw with cfmakeraw() once it is open: design C11's fallback, where
 *    DEV is the slave /dev/ttyp3 and qvm holds the master. Without -R the
 *    termios is never touched.
 * -w LABEL=TEXT writes TEXT and a newline once, after LABEL's STAMP line and
 *    hit file. LABEL is an -l given with -s. At most 4.
 * -t FILE=TEXT writes TEXT and a newline once, when stat(FILE) first succeeds.
 *    FILE is polled every 100 ms. At most 4.
 * -d SECS (0-3600, default 0) is the settle delay from the needle's reading, or
 *    from the poll that found FILE, to each write.
 * TEXT is 1-256 bytes with no CR or LF.
 *
 * S1's probe 1 (design §3.4):
 *
 *   s1con -i /dev/ptyp3 -O -o /dev/shmem/s1.hvc -r /dev/shmem/s1con.stamps \
 *         -h /dev/shmem/con -d 2 -s 'S1-INIT ready' -l i_ready \
 *         -s 'S1-SHELL-42-OK' -l shell_ok \
 *         -w 'i_ready=echo S1-SHELL-$((40+2))-OK' &
 *
 * The echoed command cannot contain S1-SHELL-42-OK; only the shell's arithmetic
 * produces it. /dev/shmem/con stands for a directory that the host script
 * creates, and stamp's -h does not use it. Whether /dev/shmem accepts a
 * subdirectory is not verified here. The host's wait on
 * /dev/shmem/con/open.hit tests that, and at teardown the host waits on
 * /dev/shmem/con/eof.hit, not on stamp's eof.hit.
 *
 * Each write adds one line to the record, in stamp's format, once the write
 * has returned:
 *
 *   STAMP write w=<label>|t=<n> rc=<0|errno> cycles=<u64> cps=<u64> cpu=<n> mono_ns=<u64> bytes=<u64>
 *
 * <n> is the -t's position among the -t options, from 1; bytes is the stream
 * offset at that moment. A write is non-blocking and bounded to 2 s in total;
 * one that cannot finish is rc=EAGAIN, and a partial line may then have
 * reached the guest. "write" is therefore not a valid label. The eof and
 * read-error lines gain " writes=<made>/<given> write_errors=<n>" after
 * stamp's fields.
 *
 * With no -w or -t the loop is stamp's: one blocking read after another. With
 * them, poll() waits for input with a timeout set by the next due write or the
 * next -t poll, at most 1 s at a time, re-checked against the counter. Every
 * reading is still taken as soon as read() returns. If poll() fails, the stream
 * ends as on a read error, with "poll-error errno=<n>" as the head.
 *
 * What it deliberately does not do: it does not decide what the guest's answer
 * means, it does not retry a write, and it writes nothing except the given
 * TEXTs.
 *
 * Exit: 0 when every needle fired and every write was made before end of
 * input, 1 otherwise, 2 on a malformed command line.
 */

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/stat.h>
#include <sys/syspage.h>
#include <sys/types.h>

#define MAX_NEEDLES     12
#define NEEDLE_MAX      256
#define LABEL_MAX       64
#define CHUNK           4096
#define DEFAULT_CAP     65536ull        /* bytes kept with -o unless -m says otherwise */
#define LINE_BUF        512
#define PATH_BUF        512
#define MAX_W           4               /* -w options */
#define MAX_T           4               /* -t options */
#define TEXT_MAX        256             /* bytes of one write, before its newline */
#define SETTLE_MAX_S    3600u
#define TRIGGER_POLL_MS 100u
#define WRITE_BOUND_MS  2000u
#define WRITE_NAP_MS    50
#define WAIT_MAX_MS     1000u           /* longest poll() before the counter is re-read */

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

static uint64_t
cycles_to_ms(uint64_t const d)
{
	return d / cps * 1000u + (d % cps) * 1000u / cps;
}

static uint64_t
ms_to_cycles(uint64_t const ms)
{
	return ms / 1000u * cps + (ms % 1000u) * cps / 1000u;
}

static int
usage(void)
{
	fprintf(stderr,
	        "usage: s1con [-i DEV [-O] [-R]] [-o FILE] [-m BYTES] [-r FILE] [-h DIR] [-d SECS]\n"
	        "             -s TEXT [-l LABEL] [-s TEXT -l LABEL]...\n"
	        "             [-w LABEL=TEXT]... [-t FILE=TEXT]...\n"
	        "  -i DEV     read DEV instead of stdin (read-only unless -O)\n"
	        "  -O         open DEV read-write; needed by -w and -t\n"
	        "  -R         set DEV raw (cfmakeraw) once it is open\n"
	        "  -o FILE    forward the stream to FILE instead of stdout (needs -r)\n"
	        "  -m BYTES   store at most BYTES of the stream (default 65536 with -o)\n"
	        "  -r FILE    append each STAMP line to FILE with one write\n"
	        "  -h DIR     create DIR/open.hit, DIR/<label>.hit and DIR/eof.hit\n"
	        "  -s TEXT    1-256 bytes; up to 12, each paired with the -l after it\n"
	        "  -l LABEL   name the reading (default \"mark\" for a single -s)\n"
	        "  -w L=TEXT  write TEXT and a newline once after label L fires; up to 4\n"
	        "  -t F=TEXT  write TEXT and a newline once file F exists (100 ms polls); up to 4\n"
	        "  -d SECS    settle 0-3600 s before each write (default 0)\n"
	        "  TEXT for -w and -t is 1-256 bytes with no CR or LF\n");
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
	       && strcmp(s, "read-error") != 0 && strcmp(s, "poll-error") != 0
	       && strcmp(s, "write") != 0;
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
parse_secs(const char *const s, unsigned *const v)
{
	uint64_t x;

	if (!parse_u64(s, &x) || x > SETTLE_MAX_S) {
		return 0;
	}
	*v = (unsigned)x;
	return 1;
}

enum { A_WAIT, A_DUE, A_DONE };

struct action {
	char        name[PATH_BUF];     /* -w: the label; -t: the trigger file */
	const char *text;
	size_t      tlen;
	int         is_w;
	unsigned    needle;             /* -w: index of the needle with that label */
	unsigned    ord;                /* -t: position among the -t options, from 1 */
	int         state;
	uint64_t    due;                /* cycles, once A_DUE */
};

/* NAME=TEXT: NAME is copied, TEXT points into argv, which is left as it was. */
static int
parse_action(const char *const arg, struct action *const a, int const is_w)
{
	const char *const eq = strchr(arg, '=');
	size_t            nlen;

	if (eq == NULL) {
		return 0;
	}
	nlen    = (size_t)(eq - arg);
	a->text = eq + 1;
	a->tlen = strlen(a->text);
	if (nlen == 0 || nlen >= sizeof(a->name) || a->tlen == 0 || a->tlen > TEXT_MAX
	    || strpbrk(a->text, "\r\n") != NULL) {
		return 0;
	}
	memcpy(a->name, arg, nlen);
	a->name[nlen] = '\0';
	a->is_w       = is_w;
	a->state      = A_WAIT;
	return !is_w || label_ok(a->name);
}

struct stream {
	const char   *needle[MAX_NEEDLES];
	const char   *label[MAX_NEEDLES];
	size_t        nlen[MAX_NEEDLES];
	int           fired[MAX_NEEDLES];
	unsigned      count;
	const char   *hit_dir;
	int           rec_fd;           /* -1 without -r */
	int           to_stdout;        /* STAMP lines also to stdout: no -o */
	unsigned      rec_errors;
	unsigned      hit_errors;
	struct action act[MAX_W + MAX_T];
	unsigned      nact;
	uint64_t      settle;           /* -d, in cycles */
	uint64_t      total;            /* stream offset */
	unsigned      made;
	unsigned      write_errors;
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

/* TEXT and a newline, non-blocking, bounded; 0 or the errno that stopped it. */
static int
write_bounded(int const fd, const char *const text, size_t const tlen)
{
	char           buf[TEXT_MAX + 1];
	size_t const   len      = tlen + 1;
	size_t         off      = 0;
	int            err      = 0;
	int const      fl       = fcntl(fd, F_GETFL);
	uint64_t const deadline = ClockCycles() + ms_to_cycles(WRITE_BOUND_MS);

	if (fl < 0) {
		return (errno != 0) ? errno : EIO;
	}
	memcpy(buf, text, tlen);
	buf[tlen] = '\n';
	if ((fl & O_NONBLOCK) == 0 && fcntl(fd, F_SETFL, fl | O_NONBLOCK) < 0) {
		return (errno != 0) ? errno : EIO;
	}
	while (off < len) {
		ssize_t const w = write(fd, buf + off, len - off);

		if (w > 0) {
			off += (size_t)w;
			continue;
		}
		if (w < 0 && errno == EINTR) {
			continue;
		}
		if (w < 0 && errno != EAGAIN) {
			err = errno;
			break;
		}
		if (ClockCycles() >= deadline) {
			err = EAGAIN;
			break;
		}

		struct pollfd p;

		p.fd      = fd;
		p.events  = POLLOUT;
		p.revents = 0;
		(void)poll(&p, 1, WRITE_NAP_MS);
	}
	if ((fl & O_NONBLOCK) == 0) {
		(void)fcntl(fd, F_SETFL, fl);
	}
	return err;
}

static void
do_write(struct stream *const st, struct action *const a, int const fd)
{
	struct reading r;
	char           head[LABEL_MAX + 48];
	int const      err = write_bounded(fd, a->text, a->tlen);

	take(&r);
	a->state = A_DONE;
	if (err == 0) {
		st->made++;
	} else {
		st->write_errors++;
	}
	if (a->is_w) {
		(void)snprintf(head, sizeof(head), "write w=%s rc=%d", a->name, err);
	} else {
		(void)snprintf(head, sizeof(head), "write t=%u rc=%d", a->ord, err);
	}
	emit(st, head, &r, st->total, "");
}

/* -t files that have appeared, then every write that is due. */
static void
run_actions(struct stream *const st, int const fd, uint64_t *const next_poll)
{
	uint64_t const now = ClockCycles();
	struct stat    sb;

	if (now >= *next_poll) {
		for (unsigned k = 0; k < st->nact; k++) {
			struct action *const a = &st->act[k];

			if (!a->is_w && a->state == A_WAIT && stat(a->name, &sb) == 0) {
				a->state = A_DUE;
				a->due   = now + st->settle;
			}
		}
		*next_poll = now + ms_to_cycles(TRIGGER_POLL_MS);
	}
	for (unsigned k = 0; k < st->nact; k++) {
		struct action *const a = &st->act[k];

		if (a->state == A_DUE && ClockCycles() >= a->due) {
			do_write(st, a, fd);
		}
	}
}

/* poll()'s timeout: the next due write or -t poll, at most 1 s; -1 when nothing is timed. */
static int
next_timeout(const struct stream *const st, uint64_t const next_poll)
{
	uint64_t const now  = ClockCycles();
	uint64_t       wait = UINT64_MAX;

	for (unsigned k = 0; k < st->nact; k++) {
		const struct action *const a = &st->act[k];
		uint64_t                   at;

		if (a->state == A_DUE) {
			at = a->due;
		} else if (!a->is_w && a->state == A_WAIT) {
			at = next_poll;
		} else {
			continue;
		}
		at = (at > now) ? at - now : 0;
		if (at < wait) {
			wait = at;
		}
	}
	if (wait == UINT64_MAX) {
		return -1;
	}
	if (wait == 0) {
		return 0;
	}

	uint64_t const ms = cycles_to_ms(wait) + 1u;

	return (int)((ms > WAIT_MAX_MS) ? WAIT_MAX_MS : ms);
}

/* stamp's end-of-stream line, with the writes appended. */
static int
finish(struct stream *const st, const char *const head, uint64_t const stored,
       unsigned const nfired, unsigned const fwd_errs, int const clean)
{
	struct reading r;
	char           tail[224];

	take(&r);
	(void)snprintf(tail, sizeof(tail), " stored=%llu fired=%u/%u fwd_errors=%u rec_errors=%u hit_errors=%u"
	               " writes=%u/%u write_errors=%u",
	               (unsigned long long)stored, nfired, st->count, fwd_errs, st->rec_errors,
	               st->hit_errors, st->made, st->nact, st->write_errors);
	emit(st, head, &r, st->total, tail);
	if (st->hit_dir != NULL) {
		(void)touch_hit(st->hit_dir, "eof");
	}
	return (clean && nfired == st->count && st->made == st->nact) ? 0 : 1;
}

static int
run_stream(struct stream *const st, const char *const in_path, const char *const out_path,
           const char *const rec, uint64_t const cap, int const have_cap, int const rdwr, int const raw)
{
	static char    buf[CHUNK];
	static char    window[NEEDLE_MAX + CHUNK];
	char           keep[NEEDLE_MAX];
	size_t         keptlen   = 0;
	size_t         longest   = 0;
	uint64_t       stored    = 0;
	uint64_t       next_poll = 0;   /* poll the -t files at once */
	unsigned       nfired    = 0;
	unsigned       fwd_errs  = 0;
	int            in_fd     = STDIN_FILENO;
	int            out_fd    = STDOUT_FILENO;
	int const      acting    = (st->nact > 0);
	struct reading r;
	char           head[32];

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
			fprintf(stderr, "s1con: open %s: %s\n", rec, strerror(errno));
			return 1;
		}
	}
	if (out_path != NULL) {
		out_fd = open(out_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
		if (out_fd < 0) {
			fprintf(stderr, "s1con: open %s: %s\n", out_path, strerror(errno));
			return 1;
		}
	}
	if (in_path != NULL) {
		in_fd = open(in_path, (rdwr ? O_RDWR : O_RDONLY) | O_NOCTTY);
		if (in_fd < 0) {
			fprintf(stderr, "s1con: open %s: %s\n", in_path, strerror(errno));
			return 1;
		}
	}
	if (raw) {
		struct termios t;

		if (tcgetattr(in_fd, &t) != 0 || cfmakeraw(&t) != 0 || tcsetattr(in_fd, TCSANOW, &t) != 0) {
			fprintf(stderr, "s1con: raw %s: %s\n", in_path, strerror(errno));
			return 1;
		}
	}
	if (st->hit_dir != NULL && touch_hit(st->hit_dir, "open") != 0) {
		st->hit_errors++;
	}

	for (;;) {
		if (acting) {
			struct pollfd p;
			int           pr;

			run_actions(st, in_fd, &next_poll);
			p.fd      = in_fd;
			p.events  = POLLIN;
			p.revents = 0;
			pr = poll(&p, 1, next_timeout(st, next_poll));
			if (pr == 0) {
				continue;
			}
			if (pr < 0) {
				int const e = errno;

				if (e == EINTR) {
					continue;
				}
				(void)snprintf(head, sizeof(head), "poll-error errno=%d", e);
				return finish(st, head, stored, nfired, fwd_errs, 0);
			}
		}

		ssize_t const n = read(in_fd, buf, sizeof(buf));

		if (n > 0) {
			size_t fw = (size_t)n;

			take(&r);           /* before any other work */
			st->total += (uint64_t)n;

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
					emit(st, st->label[k], &r, st->total, "");
					if (st->hit_dir != NULL && touch_hit(st->hit_dir, st->label[k]) != 0) {
						st->hit_errors++;
					}
					st->fired[k] = 1;
					nfired++;
					for (unsigned j = 0; j < st->nact; j++) {
						struct action *const a = &st->act[j];

						if (a->is_w && a->needle == k && a->state == A_WAIT) {
							a->state = A_DUE;
							a->due   = r.cycles + st->settle;
						}
					}
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
		if (n == 0) {
			return finish(st, "eof", stored, nfired, fwd_errs, 1);
		}
		(void)snprintf(head, sizeof(head), "read-error errno=%d", errno);
		return finish(st, head, stored, nfired, fwd_errs, 0);
	}
}

int
main(int argc, char **argv)
{
	struct stream st;
	const char   *rec      = NULL;
	const char   *in_path  = NULL;
	const char   *out_path = NULL;
	const char   *pending  = NULL;      /* a -l given before any -s */
	uint64_t      cap      = 0;
	int           have_cap = 0;
	int           rdwr     = 0;
	int           raw      = 0;
	int           have_d   = 0;
	unsigned      settle_s = 0;
	unsigned      nw       = 0;
	unsigned      nt       = 0;

	memset(&st, 0, sizeof(st));
	st.rec_fd = -1;

	for (int i = 1; i < argc; i++) {
		const char *const a = argv[i];

		if (strcmp(a, "-O") == 0) {
			rdwr = 1;
		} else if (strcmp(a, "-R") == 0) {
			raw = 1;
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
		} else if (i + 1 < argc && strcmp(a, "-w") == 0) {
			if (nw == MAX_W || !parse_action(argv[++i], &st.act[st.nact], 1)) {
				return usage();
			}
			nw++;
			st.nact++;
		} else if (i + 1 < argc && strcmp(a, "-t") == 0) {
			if (nt == MAX_T || !parse_action(argv[++i], &st.act[st.nact], 0)) {
				return usage();
			}
			st.act[st.nact].ord = ++nt;
			st.nact++;
		} else if (i + 1 < argc && strcmp(a, "-d") == 0 && !have_d) {
			if (!parse_secs(argv[++i], &settle_s)) {
				return usage();
			}
			have_d = 1;
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

	if (st.count == 0 || (out_path != NULL && rec == NULL)) {
		return usage();
	}
	if ((rdwr || raw || st.nact > 0) && in_path == NULL) {
		return usage();
	}
	if ((st.nact > 0 && !rdwr) || (have_d && st.nact == 0)) {
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
	/* Each -w names a needle, and no needle more than once. */
	for (unsigned j = 0; j < st.nact; j++) {
		struct action *const a     = &st.act[j];
		int                  found = 0;

		if (!a->is_w) {
			continue;
		}
		for (unsigned k = 0; k < st.count; k++) {
			if (strcmp(st.label[k], a->name) == 0) {
				a->needle = k;
				found     = 1;
			}
		}
		for (unsigned i = 0; i < j; i++) {
			if (st.act[i].is_w && strcmp(st.act[i].name, a->name) == 0) {
				found = 0;
			}
		}
		if (!found) {
			return usage();
		}
	}
	if (out_path != NULL && !have_cap) {
		cap      = DEFAULT_CAP;
		have_cap = 1;
	}
	st.to_stdout = (out_path == NULL);

	cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
	if (cps == 0) {
		fprintf(stderr, "s1con: qtime reports no cycles_per_sec\n");
		return 1;
	}
	st.settle = (uint64_t)settle_s * cps;

	return run_stream(&st, in_path, out_path, rec, cap, have_cap, rdwr, raw);
}
