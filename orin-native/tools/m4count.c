/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * m4count — hypervisor exit/entry pairs, their classes and dwell statistics,
 * counted on the target from a traceprinter -n listing, with no pipe and no awk.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/m4-design.md §4.5
 * (revision 2), with the implementation notes of that file's §14. The board
 * image has neither gawk nor pipes, so the counter is C, and it is its own tool
 * so smpcheck keeps its pin. orin-native/m4/parse-m4.py implements the same
 * rules independently in Python; the two must agree (§2.2 item 5). It reads
 * text only and calls no trace library, QNX kernel or Tegra interface, so the
 * same file builds on a PC for testing.
 *
 *   m4count -i LISTING -w NAME -s START -e END [-q] [-v VFILE -V VCAP]
 *           [-c CFILE -C CCAP] [-P MAXTRIPLES] [-T MAXTHREAD] [-E status0|none]
 *
 *   -i  a traceprinter -n listing in the default format
 *   -w  the label every record carries (w=), 1-32 of [A-Za-z0-9_.-]
 *   -s  the start marker text, matched against STR:"<text>" exactly
 *   -e  the end marker text
 *   -q  quiet: IN, TIME64, BUF, RING, VCPU, TRIPLES, PAIRS, the clean STAT, END
 *   -v  write the verbatim window selection to VFILE, at most VCAP bytes
 *   -c  write the compact pair list to CFILE, at most CCAP bytes
 *   -P  triple table cap (broken fragments share it), default 1,000,000
 *   -T  THREAD and INTERRUPT table caps, default 2,000,000 each
 *   -E  eligibility E3: status0, the design's rule (default), or none (§14)
 *
 * Passes over the one file:
 *   1  64-bit host time per CPU, BUFFER sequences, markers, histogram, QVM
 *      counts, THRUNNING attribution, triple assembly per (CPU, thread)
 *   2  the THRUNNING events of every thread and every THREAD event of the vCPU
 *      threads, the INTERRUPT events, the per-CPU rates, the start anchors
 *   3  only with -v or -c: the verbatim selection and the compact pair list
 * Records IN to WARN print as soon as pass 2 has ended, before pass 3 writes a
 * byte, and every record is flushed as it is printed: a counter killed by
 * bwait -k loses at most the line being written (§4.5.8, review V3).
 *
 * Rules, in brief (the design sections are authoritative):
 *   time (§4.5.3)  a CONTROL TIME event sets msb[cpu]; a t: of more than 8 hex
 *                  digits is the full count (mismatch when its high word is
 *                  neither msb nor msb+1); otherwise t = msb<<32 | low, a low
 *                  word dropping by more than 2^31 adds one to msb (not on a
 *                  TIME event), a smaller drop is a backstep; no msb, no time
 *   buffers (§4.5.4, §14)  gaps count sequence numbers that are not the
 *                  previous plus one; a sequence of 1 after the first kept
 *                  buffer is the STOP-time trailing buffer and counts as a
 *                  restart, not a gap. held needs both markers, start before
 *                  end, every CPU covered, no gap, and every restart after the
 *                  end marker
 *   triples (§4.5.5)  ENTER, CYCLES, EXIT consecutively per (CPU, thread),
 *                  attributed to the latest THRUNNING on that CPU; every
 *                  sequence that does not complete is one broken fragment; the
 *                  order ENTER, EXIT, CYCLES is alt_order; both kinds keep their
 *                  first time and block a pair across them
 *   pairs          consecutive triples of one thread sorted by t_enter;
 *                  dwell = at_entry(n+1) - at_exit(n); I = [at_exit(n) - off(n),
 *                  at_entry(n+1) - off(n+1)]; class mig, blk, pre, clean, or
 *                  unk when an untimed or capped table prevents a decision;
 *                  eligibility E1-E8 in order, the first failure named
 *   statistics     nearest rank over eligible pairs of each class and nonblk;
 *                  ns = ticks * 10^9 / cps in 128-bit arithmetic
 *
 * Exit: 0 parsed; 1 input error (unreadable, no event line), an output file
 * that could not be written, or no memory; 2 usage; 3 a table cap was hit
 * (every record is still printed).
 */

#if defined(_MSC_VER)
#define _CRT_SECURE_NO_WARNINGS 1
#endif

#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(_MSC_VER)
#include <fcntl.h>
#include <intrin.h>
#include <io.h>
#define M4_FMT(a, b)
#else
#define M4_FMT(a, b) __attribute__((__format__(__printf__, a, b)))
#endif

#define LINE_BUF        1024u
#define MAX_CPUS        8u
#define DEF_TRIPLES     1000000ul
#define DEF_THREAD      2000000ul
#define MIN_TABLE       1000ul
#define MAX_TABLE       50000000ul
#define MAX_CAP_BYTES   (1ul << 30)
#define GROW_BYTES      (64u * 1024u)
#define MAX_THREADS     (1ul << 22)
#define HIST_SLOTS      16384u
#define HIST_PRINT      48u
#define QOTHER_KEEP     64u
#define QOTHER_PRINT    8u
#define SAMPLE_MAX      12u
#define SAMPLE_CHARS    160u
#define OFFSETS_KEEP    64u
#define SEQ_KEEP        4096u
#define ANCHOR_MAX      100000ul
#define QUOTABLE_N      10000u
#define CLS_LEN         32u
#define SUB_LEN         48u
#define LABEL_MAX       32u
#define FLT_MARK        "=M4FLT="
#define NS_PER_S        1000000000u
#define DEFAULT_CPS     31250000u

enum { SEQ_NONE = 0, SEQ_E, SEQ_EC, SEQ_EX };
enum { K_RUNNING = 0, K_READY, K_OTHER };
enum { PC_CLEAN = 0, PC_PRE, PC_BLK, PC_MIG, PC_UNK_UNTIMED, PC_UNK_CAPPED, PC_NONE = 255 };
enum { R_ELIG = 0, R_BROKEN, R_ORDER, R_STATUS, R_NEG, R_WINDOW, R_NOTHELD, R_UNTIMED, R_CAPPED };
enum { RING_UNKNOWN = 0, RING_HELD, RING_WRAPPED };

#define F_E_TIMED       0x01u
#define F_X_TIMED       0x02u
#define F_AE            0x04u
#define F_AX            0x08u
#define F_OFF           0x10u
#define F_STATUS        0x20u
#define F_HW            0x40u
#define F_ORDER_OK      0x80u

#define PF_DWELL        0x01u
#define PF_A            0x02u
#define PF_LIST         0x04u

static const char *const CLASS_NAME[] = { "clean", "pre", "blk", "mig", "unk", "unk" };

/* ------------------------------------------------------------------------ */
/* Tables                                                                    */
/* ------------------------------------------------------------------------ */

struct vec {
	void  *p;
	size_t n;
	size_t cap;
	size_t max;
	size_t esz;
};

struct ev {
	uint64_t    tval;
	unsigned    tdigits;
	unsigned    cpu;
	char        cls[CLS_LEN];
	char        sub[SUB_LEN];
	const char *args;
};

struct cpu_time {
	uint64_t msb;
	uint64_t last;
	uint32_t prev_low;
	uint8_t  msb_known;
	uint8_t  low_known;
	uint8_t  last_known;
};

struct tstate {
	struct cpu_time c[MAX_CPUS];
	uint64_t        time_events;
	uint64_t        mismatches;
	uint64_t        wraps;
	uint64_t        backsteps;
	uint64_t        backsteps64;
	uint64_t        unknown;
	uint64_t        n_t64;
	uint64_t        n_rebuilt;
};

struct cpurec {
	uint64_t events;
	uint64_t first_seq;
	uint64_t last_seq;
	uint64_t prev_seq;
	uint64_t kept;
	uint64_t gaps;
	uint64_t restarts;
	uint64_t max_events;
	uint64_t first_t;
	uint64_t last_t;
	uint64_t restart_t;
	uint64_t untimed_class;
	uint64_t bufs_in_window;
	uint64_t events_in_window;
	uint64_t anchor_t;
	uint32_t anchor_line;
	uint8_t  first_known;
	uint8_t  restart_seen;
	uint8_t  restart_timed;
	uint8_t  anchor_known;
	uint8_t  wrapped;
};

struct thread {
	uint32_t pid;
	uint32_t tid;
	uint64_t cycles;
};

struct seq {
	uint64_t t_enter;
	uint64_t f_t;
	uint64_t ae;
	uint64_t ax;
	uint32_t thread;
	uint32_t line_enter;
	uint32_t line_cycles;
	uint8_t  cpu;
	uint8_t  st;
	uint8_t  e_timed;
	uint8_t  f_timed;
	uint8_t  have_ae;
	uint8_t  have_ax;
};

struct triple {
	uint64_t t_enter;
	uint64_t t_exit;
	uint64_t ae;
	uint64_t ax;
	uint64_t off;
	uint64_t hw;
	int64_t  dwell;
	uint32_t line_enter;
	uint32_t line_cycles;
	uint32_t line_exit;
	uint32_t thread;
	uint32_t status;
	uint32_t intr;
	uint8_t  cpu_enter;
	uint8_t  cpu_exit;
	uint8_t  flags;
	uint8_t  pclass;
	uint8_t  preason;
	uint8_t  pflags;
};

struct frag {
	uint64_t t;
	uint32_t thread;
	uint32_t pad;
};

struct tev {
	uint64_t t;
	uint32_t thread;
	uint8_t  cpu;
	uint8_t  kind;
	uint8_t  pad[2];
};

struct iev {
	uint64_t t;
	uint32_t cpu;
	uint32_t pad;
};

struct mark {
	uint64_t t;
	uint32_t line;
	unsigned cpu;
	int      found;
	int      timed;
};

struct hkey {
	uint64_t n;
	char     cls[CLS_LEN];
	char     sub[SUB_LEN];
};

struct qother {
	uint64_t n;
	char     sub[SUB_LEN];
};

struct sample {
	char sub[SUB_LEN];
	char line[SAMPLE_CHARS + 1u];
};

/* ------------------------------------------------------------------------ */
/* State                                                                     */
/* ------------------------------------------------------------------------ */

static const char   *opt_in;
static const char   *opt_label;
static const char   *opt_start;
static const char   *opt_end;
static const char   *opt_vfile;
static const char   *opt_cfile;
static unsigned long opt_vcap;
static unsigned long opt_ccap;
static unsigned long opt_max_triples = DEF_TRIPLES;
static unsigned long opt_max_thread  = DEF_THREAD;
static int           opt_quiet;
static int           opt_e3_status0 = 1;

static int      nomem;
static int      cap_triples;
static int      cap_thread;
static int      cap_intr;
static uint64_t cap_thread_at;
static uint64_t cap_intr_at;

static uint64_t g_lines;
static uint64_t g_bytes;
static uint64_t g_events;
static uint64_t g_unformatted;
static uint64_t g_long;
static uint64_t g_oor;
static uint64_t g_cps = DEFAULT_CPS;
static int      g_cps_header;

static struct tstate  ts1;
static struct cpurec  cpus[MAX_CPUS];
static struct mark    mk_start;
static struct mark    mk_end;
static uint64_t       mk_dup;
static int            window_known;
static uint64_t       start_t;
static uint64_t       end_t;
static int            ring_state;

static struct vec     threads;
static uint32_t      *thash;
static size_t         thash_n;
static long           running[MAX_CPUS];

static struct seq     seqs[SEQ_KEEP];
static size_t         nseqs;

static struct vec     triples;
static struct vec     frags;
static struct vec     tevs;
static struct vec     ievs;
static struct vec     anchors;

static struct hkey   *hist;
static size_t         nhist;
static uint32_t      *hist_hash;
static uint64_t       hist_overflow;

static uint64_t       q_enter;
static uint64_t       q_exit;
static uint64_t       q_cycles;
static uint64_t       q_create;
static uint64_t       q_raise;
static uint64_t       q_lower;
static uint64_t       q_timer;
static uint64_t       q_other;
static uint64_t       q_status_nonzero;
static uint64_t       q_unattributed;
static struct qother  qothers[QOTHER_KEEP];
static size_t         nqothers;

static struct sample  samples[SAMPLE_MAX];
static size_t         nsamples;
static int            sampled_running;
static int            sampled_intr;

static uint64_t       offsets[OFFSETS_KEEP];
static size_t         noffsets;
static int            offsets_overflow;

static uint64_t       tr_complete;
static uint64_t       tr_broken;
static uint64_t       tr_alt;
static uint64_t       tr_ok;
static uint64_t       tr_violated;
static uint64_t       tr_in_window;

static uint64_t       p_total;
static uint64_t       p_reason[R_CAPPED + 1];
static uint64_t       p_class[PC_MIG + 1];
static uint64_t       p_intr[PC_MIG + 1];
static uint64_t       p_unk;
static uint64_t       p_list;

static char           quantum[24];

/* ------------------------------------------------------------------------ */
/* Helpers                                                                   */
/* ------------------------------------------------------------------------ */

static void rec(const char *fmt, ...) M4_FMT(1, 2);

/* One record, one line, flushed: the console is the record (§4.5.8). */
static void
rec(const char *const fmt, ...)
{
	va_list ap;

	va_start(ap, fmt);
	(void)vprintf(fmt, ap);
	va_end(ap);
	(void)fflush(stdout);
}

static uint64_t
mono_ms(void)
{
	struct timespec ts;

#if defined(_MSC_VER)
	if (timespec_get(&ts, TIME_UTC) == 0) {
		return 0;
	}
#else
	if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
		return 0;
	}
#endif
	return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}

static uint64_t
ticks_to_ns(uint64_t const t, uint64_t const c)
{
#if defined(__SIZEOF_INT128__)
	unsigned __int128 const v = (unsigned __int128)t * NS_PER_S / c;

	return (v > (unsigned __int128)UINT64_MAX) ? UINT64_MAX : (uint64_t)v;
#elif defined(_MSC_VER) && defined(_M_X64)
	uint64_t const q = t / c;
	uint64_t       hi;
	uint64_t       rem;
	uint64_t const lo = _umul128(t % c, NS_PER_S, &hi);

	return q * NS_PER_S + _udiv128(hi, lo, c, &rem);
#else
	return t / c * NS_PER_S + (t % c) * NS_PER_S / c;
#endif
}

static void
vec_init(struct vec *const v, size_t const esz, size_t const max)
{
	v->p   = NULL;
	v->n   = 0;
	v->cap = 0;
	v->max = max;
	v->esz = esz;
}

static void *
vec_at(struct vec const *const v, size_t const i)
{
	return (char *)v->p + i * v->esz;
}

/* 1 stored, 0 at the cap, -1 no memory. Doubles from 64 KiB, never past max. */
static int
vec_push(struct vec *const v, const void *const e)
{
	if (v->n == v->cap) {
		size_t nc;
		void  *np;

		if (v->cap >= v->max) {
			return 0;
		}
		nc = (v->cap == 0u) ? (GROW_BYTES / v->esz) : v->cap * 2u;
		if (nc < 1u) {
			nc = 1u;
		}
		if (nc > v->max) {
			nc = v->max;
		}
		np = realloc(v->p, nc * v->esz);
		if (np == NULL) {
			nomem = 1;
			return -1;
		}
		v->p   = np;
		v->cap = nc;
	}
	memcpy(vec_at(v, v->n), e, v->esz);
	v->n++;
	return 1;
}

static int
hexval(char const c)
{
	if (c >= '0' && c <= '9') {
		return c - '0';
	}
	if (c >= 'a' && c <= 'f') {
		return c - 'a' + 10;
	}
	if (c >= 'A' && c <= 'F') {
		return c - 'A' + 10;
	}
	return -1;
}

static int
is_blank(char const c)
{
	return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

static void
copy_field(char *const dst, size_t const size, const char *const src, size_t n)
{
	if (n >= size) {
		n = size - 1u;
	}
	memcpy(dst, src, n);
	dst[n] = '\0';
}

/*
 * One line into buf, the newline kept. 0 at end of file, 1 a line, 2 a line
 * longer than the buffer, drained to its newline (§4.5.2). *nbytes counts every
 * byte consumed, the drained ones included.
 */
static int
read_line(FILE *const f, char *const buf, size_t const size, uint64_t *const nbytes)
{
	size_t len;
	int    ch;

	if (fgets(buf, (int)size, f) == NULL) {
		return 0;
	}
	len     = strlen(buf);
	*nbytes = len;
	if (len > 0u && buf[len - 1u] == '\n') {
		return 1;
	}
	if (feof(f)) {
		return 1;
	}
	while ((ch = getc(f)) != EOF) {
		(*nbytes)++;
		if (ch == '\n') {
			break;
		}
	}
	return 2;
}

/*
 * t:0x<1-16 hex> <blanks> CPU:<spaces?><1-3 digits> <blank> <CLASS>:<SUBTYPE>
 * <arguments> (§4.5.2). The class is the trimmed text up to the first colon;
 * the subtype runs to the next blank. Returns 1 for an event line.
 */
static int
parse_event(const char *const line, struct ev *const e)
{
	const char   *p  = line;
	uint64_t      v  = 0;
	unsigned      nd = 0;
	unsigned long cpu = 0;
	unsigned      cd = 0;
	const char   *colon;
	const char   *cs;
	const char   *ce;
	const char   *se;

	if (strncmp(p, "t:0x", 4) != 0) {
		return 0;
	}
	p += 4;
	for (int h; (h = hexval(*p)) >= 0; p++) {
		if (nd == 16u) {
			return 0;
		}
		v = (v << 4) | (uint64_t)h;
		nd++;
	}
	if (nd == 0u || (*p != ' ' && *p != '\t')) {
		return 0;
	}
	while (*p == ' ' || *p == '\t') {
		p++;
	}
	if (strncmp(p, "CPU:", 4) != 0) {
		return 0;
	}
	p += 4;
	while (*p == ' ') {
		p++;
	}
	if (*p < '0' || *p > '9') {
		return 0;
	}
	while (*p >= '0' && *p <= '9') {
		if (++cd > 3u) {
			return 0;
		}
		cpu = cpu * 10u + (unsigned long)(*p - '0');
		p++;
	}
	if (*p != ' ' && *p != '\t') {
		return 0;
	}
	colon = strchr(p, ':');
	if (colon == NULL) {
		return 0;
	}
	cs = p;
	while (cs < colon && (*cs == ' ' || *cs == '\t')) {
		cs++;
	}
	ce = colon;
	while (ce > cs && (ce[-1] == ' ' || ce[-1] == '\t')) {
		ce--;
	}
	if (ce == cs) {
		return 0;
	}
	copy_field(e->cls, sizeof(e->cls), cs, (size_t)(ce - cs));
	se = colon + 1;
	while (*se != '\0' && !is_blank(*se)) {
		se++;
	}
	copy_field(e->sub, sizeof(e->sub), colon + 1, (size_t)(se - (colon + 1)));
	e->args    = se;
	e->tval    = v;
	e->tdigits = nd;
	e->cpu     = (unsigned)cpu;
	return 1;
}

/* name:0x<hex> or name:<decimal>, the name preceded by a blank. */
static int
arg_u64(const char *const args, const char *const name, uint64_t *const out)
{
	size_t const nl = strlen(name);

	for (const char *p = strstr(args, name); p != NULL; p = strstr(p + 1, name)) {
		const char *q;
		uint64_t    v  = 0;
		unsigned    nd = 0;

		if (p == args || (p[-1] != ' ' && p[-1] != '\t') || p[nl] != ':') {
			continue;
		}
		q = p + nl + 1;
		if (q[0] == '0' && (q[1] == 'x' || q[1] == 'X')) {
			q += 2;
			while (nd < 16u) {
				int const h = hexval(*q);

				if (h < 0) {
					break;
				}
				v = (v << 4) | (uint64_t)h;
				nd++;
				q++;
			}
		} else {
			for (; nd < 20u && *q >= '0' && *q <= '9'; q++) {
				v = v * 10u + (uint64_t)(*q - '0');
				nd++;
			}
		}
		if (nd == 0u) {
			continue;
		}
		*out = v;
		return 1;
	}
	return 0;
}

/* The first STR:"<text>". */
static int
arg_str(const char *const args, const char **const s, size_t *const n)
{
	const char *p = strstr(args, "STR:\"");
	const char *q;

	if (p == NULL) {
		return 0;
	}
	p += 5;
	q = strchr(p, '"');
	if (q == NULL) {
		return 0;
	}
	*s = p;
	*n = (size_t)(q - p);
	return 1;
}

static int
decimal_after(const char *const args, const char *const key, uint64_t *const out)
{
	const char *p = strstr(args, key);
	uint64_t    v = 0;
	unsigned    nd = 0;

	if (p == NULL) {
		return 0;
	}
	for (p += strlen(key); nd < 20u && *p >= '0' && *p <= '9'; p++) {
		v = v * 10u + (uint64_t)(*p - '0');
		nd++;
	}
	if (nd == 0u) {
		return 0;
	}
	*out = v;
	return 1;
}

/* The last run of decimal digits in a line (the TRACE_CYCLES_PER_SEC header). */
static int
last_decimal(const char *const line, uint64_t *const out)
{
	int      found = 0;
	uint64_t v     = 0;

	for (const char *p = line; *p != '\0';) {
		if (*p >= '0' && *p <= '9') {
			uint64_t x  = 0;
			unsigned nd = 0;

			while (*p >= '0' && *p <= '9') {
				if (nd < 20u) {
					x = x * 10u + (uint64_t)(*p - '0');
				}
				nd++;
				p++;
			}
			v     = x;
			found = 1;
		} else {
			p++;
		}
	}
	if (found) {
		*out = v;
	}
	return found;
}

/*
 * §4.5.3. Returns 1 with *t when the event has a 64-bit host time. The TIME
 * event sets msb before its own time is taken, and is never itself a wrap.
 */
static int
time64(struct tstate *const s, const struct ev *const e, int const is_time, int const have_msb,
       uint64_t const msb, uint64_t *const t)
{
	struct cpu_time *const c = &s->c[e->cpu];
	uint64_t const         v = e->tval;

	if (is_time && have_msb) {
		c->msb       = msb;
		c->msb_known = 1;
		s->time_events++;
	}
	if (e->tdigits > 8u) {
		if (c->msb_known) {
			uint64_t const hi = v >> 32;

			if (hi != c->msb && hi != c->msb + 1u) {
				s->mismatches++;
			}
		}
		c->prev_low  = (uint32_t)(v & 0xffffffffu);
		c->low_known = 1;
		*t           = v;
		s->n_t64++;
	} else {
		uint32_t const low = (uint32_t)(v & 0xffffffffu);

		if (!is_time && c->low_known && low < c->prev_low) {
			if ((uint32_t)(c->prev_low - low) > 0x80000000u) {
				if (c->msb_known) {
					c->msb++;
					s->wraps++;
				}
			} else {
				s->backsteps++;
			}
		}
		c->prev_low  = low;
		c->low_known = 1;
		if (!c->msb_known) {
			s->unknown++;
			return 0;
		}
		*t = (c->msb << 32) | low;
		s->n_rebuilt++;
	}
	if (c->last_known && *t < c->last) {
		s->backsteps64++;
	}
	c->last       = *t;
	c->last_known = 1;
	return 1;
}

static int
event_time(struct tstate *const s, const struct ev *const e, uint64_t *const t)
{
	int const is_time = strcmp(e->cls, "CONTROL") == 0 && strcmp(e->sub, "TIME") == 0;
	uint64_t  msb     = 0;
	int const have    = is_time ? arg_u64(e->args, "msb", &msb) : 0;

	return time64(s, e, is_time, have, msb, t);
}

static void
hex_or_dash(char *const buf, size_t const size, int const known, uint64_t const v)
{
	if (known) {
		(void)snprintf(buf, size, "0x%" PRIx64, v);
	} else {
		(void)snprintf(buf, size, "-");
	}
}

/* ------------------------------------------------------------------------ */
/* Threads, histogram, samples                                               */
/* ------------------------------------------------------------------------ */

static size_t
hash_slot(uint64_t const key, size_t const n)
{
	return (size_t)((key * 0x9E3779B97F4A7C15ull) >> 32) & (n - 1u);
}

static struct thread *
thread_at(size_t const i)
{
	return (struct thread *)vec_at(&threads, i);
}

/* Index of (pid, tid), inserted when insert is set; -1 absent, capped or no memory. */
static long
thread_index(uint32_t const pid, uint32_t const tid, int const insert)
{
	uint64_t const key = ((uint64_t)pid << 32) | tid;
	size_t         s;

	if (thash_n == 0u) {
		if (!insert) {
			return -1;
		}
		thash = calloc(1024u, sizeof(*thash));
		if (thash == NULL) {
			nomem = 1;
			return -1;
		}
		thash_n = 1024u;
	}
	for (s = hash_slot(key, thash_n); thash[s] != 0u; s = (s + 1u) & (thash_n - 1u)) {
		struct thread const *const t = thread_at(thash[s] - 1u);

		if (t->pid == pid && t->tid == tid) {
			return (long)(thash[s] - 1u);
		}
	}
	if (!insert) {
		return -1;
	}
	if ((threads.n + 1u) * 2u > thash_n) {
		size_t const    nn = thash_n * 2u;
		uint32_t *const nh = calloc(nn, sizeof(*nh));

		if (nh == NULL) {
			nomem = 1;
			return -1;
		}
		for (size_t i = 0; i < thash_n; i++) {
			if (thash[i] != 0u) {
				struct thread const *const t = thread_at(thash[i] - 1u);
				size_t                     j = hash_slot(((uint64_t)t->pid << 32) | t->tid, nn);

				while (nh[j] != 0u) {
					j = (j + 1u) & (nn - 1u);
				}
				nh[j] = thash[i];
			}
		}
		free(thash);
		thash   = nh;
		thash_n = nn;
		for (s = hash_slot(key, thash_n); thash[s] != 0u; s = (s + 1u) & (thash_n - 1u)) {
		}
	}
	{
		struct thread t;

		memset(&t, 0, sizeof(t));
		t.pid = pid;
		t.tid = tid;
		if (vec_push(&threads, &t) != 1) {
			return -1;
		}
	}
	thash[s] = (uint32_t)threads.n;
	return (long)(threads.n - 1u);
}

static uint64_t
fnv(const char *const a, const char *const b)
{
	uint64_t h = 1469598103934665603ull;

	for (const char *p = a; *p != '\0'; p++) {
		h = (h ^ (unsigned char)*p) * 1099511628211ull;
	}
	h = (h ^ (unsigned char)'|') * 1099511628211ull;
	for (const char *p = b; *p != '\0'; p++) {
		h = (h ^ (unsigned char)*p) * 1099511628211ull;
	}
	return h;
}

static void
hist_add(const char *const cls, const char *const sub)
{
	size_t const n = (size_t)HIST_SLOTS * 2u;
	size_t       s = hash_slot(fnv(cls, sub), n);

	for (; hist_hash[s] != 0u; s = (s + 1u) & (n - 1u)) {
		struct hkey *const k = &hist[hist_hash[s] - 1u];

		if (strcmp(k->cls, cls) == 0 && strcmp(k->sub, sub) == 0) {
			k->n++;
			return;
		}
	}
	if (nhist == HIST_SLOTS) {
		hist_overflow++;
		return;
	}
	memset(&hist[nhist], 0, sizeof(hist[nhist]));
	copy_field(hist[nhist].cls, sizeof(hist[nhist].cls), cls, strlen(cls));
	copy_field(hist[nhist].sub, sizeof(hist[nhist].sub), sub, strlen(sub));
	hist[nhist].n = 1;
	nhist++;
	hist_hash[s] = (uint32_t)nhist;
}

static void
sample_add(const char *const sub, const char *const line)
{
	struct sample *sm;
	size_t         j = 0;

	for (size_t i = 0; i < nsamples; i++) {
		if (strcmp(samples[i].sub, sub) == 0) {
			return;
		}
	}
	if (nsamples == SAMPLE_MAX) {
		return;
	}
	sm = &samples[nsamples++];
	copy_field(sm->sub, sizeof(sm->sub), sub, strlen(sub));
	for (const char *p = line; *p != '\0' && *p != '\n' && *p != '\r' && j < SAMPLE_CHARS; p++) {
		sm->line[j++] = (*p == '"') ? '\'' : *p;
	}
	sm->line[j] = '\0';
}

static void
qother_add(const char *const sub)
{
	for (size_t i = 0; i < nqothers; i++) {
		if (strcmp(qothers[i].sub, sub) == 0) {
			qothers[i].n++;
			return;
		}
	}
	if (nqothers < QOTHER_KEEP) {
		copy_field(qothers[nqothers].sub, sizeof(qothers[nqothers].sub), sub, strlen(sub));
		qothers[nqothers].n = 1;
		nqothers++;
	}
}

static void
offset_add(uint64_t const off)
{
	for (size_t i = 0; i < noffsets; i++) {
		if (offsets[i] == off) {
			return;
		}
	}
	if (noffsets < OFFSETS_KEEP) {
		offsets[noffsets++] = off;
	} else {
		offsets_overflow = 1;
	}
}

/* ------------------------------------------------------------------------ */
/* Triple assembly (§4.5.5)                                                  */
/* ------------------------------------------------------------------------ */

static void
fragment(uint32_t const thread, int const timed, uint64_t const t)
{
	struct frag f;
	int         r;

	memset(&f, 0, sizeof(f));
	f.t      = timed ? t : 0u;
	f.thread = thread;
	r        = vec_push(&frags, &f);
	if (r == 0) {
		cap_triples = 1;
	}
}

static struct seq *
seq_get(uint32_t const thread, unsigned const cpu)
{
	for (size_t i = 0; i < nseqs; i++) {
		if (seqs[i].thread == thread && seqs[i].cpu == cpu) {
			return &seqs[i];
		}
	}
	if (nseqs == SEQ_KEEP) {
		return NULL;
	}
	memset(&seqs[nseqs], 0, sizeof(seqs[nseqs]));
	seqs[nseqs].thread = thread;
	seqs[nseqs].cpu    = (uint8_t)cpu;
	return &seqs[nseqs++];
}

/* The partial sequence, if any, is one broken fragment. */
static void
seq_break(struct seq *const s)
{
	if (s->st != SEQ_NONE) {
		tr_broken++;
		fragment(s->thread, s->f_timed, s->f_t);
		s->st = SEQ_NONE;
	}
}

static void
on_enter(struct seq *const s, int const timed, uint64_t const t, uint32_t const line)
{
	seq_break(s);
	s->st         = SEQ_E;
	s->e_timed    = (uint8_t)timed;
	s->f_timed    = (uint8_t)timed;
	s->t_enter    = t;
	s->f_t        = t;
	s->line_enter = line;
	s->have_ae    = 0;
	s->have_ax    = 0;
}

static void
on_cycles(struct seq *const s, int const timed, uint64_t const t, uint32_t const line, const char *const args)
{
	if (s->st == SEQ_E) {
		s->have_ae     = (uint8_t)arg_u64(args, "at_entry", &s->ae);
		s->have_ax     = (uint8_t)arg_u64(args, "at_exit", &s->ax);
		s->line_cycles = line;
		s->st          = SEQ_EC;
		return;
	}
	if (s->st == SEQ_EX) {
		tr_alt++;
		fragment(s->thread, s->f_timed, s->f_t);
		s->st = SEQ_NONE;
		return;
	}
	seq_break(s);
	tr_broken++;
	fragment(s->thread, timed, t);
}

static void
on_exit_event(struct seq *const s, int const timed, uint64_t const t, uint32_t const line, const char *const args)
{
	struct triple tr;
	uint64_t      status = 0;
	int           r;

	if (s->st == SEQ_E) {
		s->st = SEQ_EX;
		return;
	}
	if (s->st != SEQ_EC) {
		seq_break(s);
		tr_broken++;
		fragment(s->thread, timed, t);
		return;
	}
	memset(&tr, 0, sizeof(tr));
	tr.t_enter     = s->t_enter;
	tr.t_exit      = t;
	tr.ae          = s->ae;
	tr.ax          = s->ax;
	tr.line_enter  = s->line_enter;
	tr.line_cycles = s->line_cycles;
	tr.line_exit   = line;
	tr.thread      = s->thread;
	tr.cpu_enter   = s->cpu;
	tr.cpu_exit    = s->cpu;
	tr.pclass      = PC_NONE;
	tr.flags       = (uint8_t)((s->e_timed ? F_E_TIMED : 0u) | (timed ? F_X_TIMED : 0u) |
	                           (s->have_ae ? F_AE : 0u) | (s->have_ax ? F_AX : 0u));
	if (arg_u64(args, "clockcycles_offset", &tr.off)) {
		tr.flags |= F_OFF;
	}
	if (arg_u64(args, "status", &status)) {
		tr.status = (uint32_t)status;
		tr.flags |= F_STATUS;
	}
	if (arg_u64(args, "hw_reason", &tr.hw)) {
		tr.flags |= F_HW;
	}
	s->st = SEQ_NONE;
	tr_complete++;
	r = vec_push(&triples, &tr);
	if (r == 0) {
		cap_triples = 1;
	}
}

/* ------------------------------------------------------------------------ */
/* Pass 1                                                                    */
/* ------------------------------------------------------------------------ */

static void
marker(struct mark *const m, const struct ev *const e, int const timed, uint64_t const t, uint32_t const line)
{
	if (m->found) {
		mk_dup++;
		return;
	}
	m->found = 1;
	m->timed = timed;
	m->t     = t;
	m->cpu   = e->cpu;
	m->line  = line;
}

static void
pass1_event(const struct ev *const e, const char *const line_text, uint32_t const line)
{
	struct cpurec *const c = &cpus[e->cpu];
	uint64_t             t = 0;
	int const            timed = event_time(&ts1, e, &t);

	hist_add(e->cls, e->sub);
	c->events++;
	if (timed) {
		if (!c->first_known) {
			c->first_t     = t;
			c->first_known = 1;
		}
		c->last_t = t;
	}

	if (strcmp(e->cls, "CONTROL") == 0) {
		uint64_t seq = 0;
		uint64_t nev = 0;

		if (strcmp(e->sub, "BUFFER") == 0 && decimal_after(e->args, "sequence = ", &seq)) {
			(void)decimal_after(e->args, "num_events = ", &nev);
			if (c->kept == 0u) {
				c->first_seq = seq;
				c->last_seq  = seq;
			} else if (seq == 1u) {
				c->restarts++;
				if (!c->restart_seen) {
					c->restart_seen  = 1;
					c->restart_timed = (uint8_t)timed;
					c->restart_t     = t;
				}
			} else if (seq != c->prev_seq + 1u) {
				c->gaps++;
			}
			if (c->kept != 0u && !c->restart_seen) {
				c->last_seq = seq;
			}
			c->prev_seq = seq;
			c->kept++;
			if (nev > c->max_events) {
				c->max_events = nev;
			}
		}
		return;
	}

	if (strcmp(e->cls, "USREVENT") == 0) {
		const char *s = NULL;
		size_t      n = 0;

		if (arg_str(e->args, &s, &n)) {
			if (n == strlen(opt_start) && memcmp(s, opt_start, n) == 0) {
				marker(&mk_start, e, timed, t, line);
			} else if (n == strlen(opt_end) && memcmp(s, opt_end, n) == 0) {
				marker(&mk_end, e, timed, t, line);
			}
		}
		return;
	}

	if (strcmp(e->cls, "THREAD") == 0 && strncmp(e->sub, "TH", 2) == 0) {
		uint64_t pid = 0;
		uint64_t tid = 0;
		long     th  = -1;

		if (arg_u64(e->args, "pid", &pid) && arg_u64(e->args, "tid", &tid)) {
			th = thread_index((uint32_t)pid, (uint32_t)tid, 1);
		}
		if (strcmp(e->sub, "THRUNNING") == 0) {
			running[e->cpu] = th;
			if (!sampled_running) {
				sampled_running = 1;
				sample_add("THRUNNING", line_text);
			}
		}
		return;
	}

	if (strcmp(e->cls, "INTERRUPT") == 0) {
		if (!sampled_intr && strcmp(e->sub, "INT_DELIVER") == 0) {
			sampled_intr = 1;
			sample_add("INT_DELIVER", line_text);
		}
		return;
	}

	if (strcmp(e->cls, "QVM") == 0) {
		int kind = -1;

		sample_add(e->sub, line_text);
		if (strcmp(e->sub, "GUEST_ENTER") == 0) {
			q_enter++;
			kind = 0;
		} else if (strcmp(e->sub, "GUEST_EXIT") == 0) {
			uint64_t v = 0;

			q_exit++;
			if (arg_u64(e->args, "status", &v) && v != 0u) {
				q_status_nonzero++;
			}
			if (arg_u64(e->args, "clockcycles_offset", &v)) {
				offset_add(v);
			}
			kind = 1;
		} else if (strcmp(e->sub, "CYCLES") == 0) {
			q_cycles++;
			kind = 7;
		} else if (strcmp(e->sub, "CREATE_VCPU_THREAD") == 0) {
			q_create++;
		} else if (strcmp(e->sub, "INTR_RAISE") == 0 || strcmp(e->sub, "RAISE_INTR") == 0) {
			q_raise++;
		} else if (strcmp(e->sub, "INTR_LOWER") == 0 || strcmp(e->sub, "LOWER_INTR") == 0) {
			q_lower++;
		} else if (strcmp(e->sub, "TIMER_CREATE") == 0 || strcmp(e->sub, "CREATE_TIMER") == 0 ||
		           strcmp(e->sub, "TIMER_FIRE") == 0 || strcmp(e->sub, "FIRE_TIMER") == 0) {
			q_timer++;
		} else {
			q_other++;
			qother_add(e->sub);
		}
		if (kind >= 0) {
			struct seq *s;

			if (running[e->cpu] < 0) {
				q_unattributed++;
				return;
			}
			s = seq_get((uint32_t)running[e->cpu], e->cpu);
			if (s == NULL) {
				tr_broken++;
				return;
			}
			if (kind == 0) {
				on_enter(s, timed, t, line);
			} else if (kind == 7) {
				thread_at((size_t)running[e->cpu])->cycles++;
				on_cycles(s, timed, t, line, e->args);
			} else {
				on_exit_event(s, timed, t, line, e->args);
			}
		}
	}
}

static void
pass1(FILE *const f)
{
	char buf[LINE_BUF];
	int  seen_event = 0;

	for (;;) {
		uint64_t  nb = 0;
		int const r  = read_line(f, buf, sizeof(buf), &nb);
		struct ev e;

		if (r == 0) {
			break;
		}
		g_lines++;
		g_bytes += nb;
		if (r == 2) {
			g_long++;
			continue;
		}
		if (!parse_event(buf, &e)) {
			g_unformatted++;
			if (!seen_event && strstr(buf, "TRACE_CYCLES_PER_SEC") != NULL) {
				uint64_t cps = 0;

				if (last_decimal(buf, &cps) && cps > 0u) {
					g_cps        = cps;
					g_cps_header = 1;
				}
			}
			continue;
		}
		if (e.cpu >= MAX_CPUS) {
			g_oor++;
			continue;
		}
		seen_event = 1;
		g_events++;
		pass1_event(&e, buf, (uint32_t)g_lines);
	}
	for (size_t i = 0; i < nseqs; i++) {
		seq_break(&seqs[i]);
	}
}

/* ------------------------------------------------------------------------ */
/* Between passes                                                            */
/* ------------------------------------------------------------------------ */

static int
cmp_triple(const void *const a, const void *const b)
{
	struct triple const *const x  = a;
	struct triple const *const y  = b;
	uint64_t const             kx = (x->flags & F_E_TIMED) ? x->t_enter : 0u;
	uint64_t const             ky = (y->flags & F_E_TIMED) ? y->t_enter : 0u;

	if (x->thread != y->thread) {
		return (x->thread < y->thread) ? -1 : 1;
	}
	if (kx != ky) {
		return (kx < ky) ? -1 : 1;
	}
	if (x->line_enter != y->line_enter) {
		return (x->line_enter < y->line_enter) ? -1 : 1;
	}
	return 0;
}

static int
cmp_frag(const void *const a, const void *const b)
{
	struct frag const *const x = a;
	struct frag const *const y = b;

	if (x->thread != y->thread) {
		return (x->thread < y->thread) ? -1 : 1;
	}
	if (x->t != y->t) {
		return (x->t < y->t) ? -1 : 1;
	}
	return 0;
}

static int
cmp_tev(const void *const a, const void *const b)
{
	struct tev const *const x = a;
	struct tev const *const y = b;

	if (x->t != y->t) {
		return (x->t < y->t) ? -1 : 1;
	}
	return (x->cpu < y->cpu) ? -1 : ((x->cpu > y->cpu) ? 1 : 0);
}

static int
cmp_iev(const void *const a, const void *const b)
{
	struct iev const *const x = a;
	struct iev const *const y = b;

	if (x->t != y->t) {
		return (x->t < y->t) ? -1 : 1;
	}
	return (x->cpu < y->cpu) ? -1 : ((x->cpu > y->cpu) ? 1 : 0);
}

static int
cmp_u32(const void *const a, const void *const b)
{
	uint32_t const x = *(const uint32_t *)a;
	uint32_t const y = *(const uint32_t *)b;

	return (x < y) ? -1 : ((x > y) ? 1 : 0);
}

static int
cmp_i64(const void *const a, const void *const b)
{
	int64_t const x = *(const int64_t *)a;
	int64_t const y = *(const int64_t *)b;

	return (x < y) ? -1 : ((x > y) ? 1 : 0);
}

static void
anchor_add(uint32_t const line)
{
	if (vec_push(&anchors, &line) < 0) {
		nomem = 1;
	}
}

static void
between_passes(void)
{
	struct triple *const T = triples.p;
	size_t const         n = triples.n;

	window_known = mk_start.found && mk_end.found && mk_start.timed && mk_end.timed;
	if (window_known) {
		start_t = mk_start.t;
		end_t   = mk_end.t;
	}

	for (size_t i = 0; i < n; i++) {
		struct triple *const x   = &T[i];
		unsigned const       all = F_E_TIMED | F_X_TIMED | F_AE | F_AX | F_OFF;

		if ((x->flags & all) == all) {
			uint64_t const he = x->ae - x->off;
			uint64_t const hx = x->ax - x->off;

			if (x->t_enter <= he && he <= hx && hx <= x->t_exit) {
				x->flags |= F_ORDER_OK;
			}
		}
		if (x->flags & F_ORDER_OK) {
			tr_ok++;
		} else {
			tr_violated++;
		}
		if (window_known && (x->flags & F_E_TIMED) && x->t_enter >= start_t && x->t_enter <= end_t) {
			tr_in_window++;
		}
	}
	if (n > 1u) {
		qsort(T, n, sizeof(*T), cmp_triple);
	}
	if (frags.n > 1u) {
		qsort(frags.p, frags.n, sizeof(struct frag), cmp_frag);
	}

	/* The ring (§4.5.4, with the restart rule of §14). */
	ring_state = RING_UNKNOWN;
	if (window_known) {
		int any_wrapped = 0;
		int clean       = 1;

		for (unsigned c = 0; c < MAX_CPUS; c++) {
			struct cpurec *const r = &cpus[c];

			if (r->events == 0u) {
				continue;
			}
			if (!r->first_known || r->first_t > start_t) {
				r->wrapped  = 1;
				any_wrapped = 1;
			}
			if (r->gaps != 0u) {
				clean = 0;
			}
			if (r->restart_seen && (!r->restart_timed || r->restart_t <= end_t)) {
				clean = 0;
			}
		}
		if (any_wrapped) {
			ring_state = RING_WRAPPED;
		} else if (start_t < end_t && clean) {
			ring_state = RING_HELD;
		}
	} else if (mk_end.found && !mk_start.found) {
		/* I22 (m4-design.md 14.5): the start marker was overwritten. A CPU whose first kept
		 * BUFFER sequence is above 1 lost its earlier buffers, so the ring wrapped past the
		 * start; say wrapped, so an undersized ring is not reported as a missing marker. */
		int any_wrapped = 0;

		for (unsigned c = 0; c < MAX_CPUS; c++) {
			struct cpurec *const r = &cpus[c];

			if (r->events != 0u && r->kept != 0u && r->first_seq > 1u) {
				r->wrapped  = 1;
				any_wrapped = 1;
			}
		}
		if (any_wrapped) {
			ring_state = RING_WRAPPED;
		}
	}

	/* Triple anchors of the verbatim selection (§4.5.8 rule 4). */
	if (window_known) {
		for (size_t i = 0; i < n; i++) {
			struct triple const *const x = &T[i];

			if (!(x->flags & F_E_TIMED) || !(x->flags & F_X_TIMED)) {
				continue;
			}
			if ((x->t_enter < start_t && start_t <= x->t_exit) || (x->t_enter <= end_t && end_t < x->t_exit)) {
				anchor_add(x->line_enter);
				anchor_add(x->line_cycles);
				anchor_add(x->line_exit);
			}
		}
		for (size_t i = 0; i < n;) {
			size_t j = i;

			while (j < n && T[j].thread == T[i].thread) {
				j++;
			}
			for (size_t k = i; k < j; k++) {
				if ((T[k].flags & F_E_TIMED) && T[k].t_enter > end_t) {
					anchor_add(T[k].line_enter);
					anchor_add(T[k].line_cycles);
					anchor_add(T[k].line_exit);
					break;
				}
			}
			i = j;
		}
	}
}

/* ------------------------------------------------------------------------ */
/* Pass 2                                                                    */
/* ------------------------------------------------------------------------ */

static void
pass2(FILE *const f)
{
	char          buf[LINE_BUF];
	struct tstate s;
	uint32_t      line = 0;

	memset(&s, 0, sizeof(s));
	rewind(f);
	for (;;) {
		uint64_t  nb = 0;
		int const r  = read_line(f, buf, sizeof(buf), &nb);
		struct ev e;
		uint64_t  t = 0;
		int       timed;

		if (r == 0) {
			break;
		}
		line++;
		if (r == 2 || !parse_event(buf, &e) || e.cpu >= MAX_CPUS) {
			continue;
		}
		timed = event_time(&s, &e, &t);
		if (timed && window_known && t >= start_t && t <= end_t) {
			cpus[e.cpu].events_in_window++;
			if (strcmp(e.cls, "CONTROL") == 0 && strcmp(e.sub, "BUFFER") == 0) {
				cpus[e.cpu].bufs_in_window++;
			}
		}

		if (strcmp(e.cls, "THREAD") == 0 && strncmp(e.sub, "TH", 2) == 0) {
			uint64_t pid = 0;
			uint64_t tid = 0;
			long     th;
			int      kind;

			if (!arg_u64(e.args, "pid", &pid) || !arg_u64(e.args, "tid", &tid)) {
				continue;
			}
			th = thread_index((uint32_t)pid, (uint32_t)tid, 0);
			if (th < 0) {
				continue;
			}
			kind = (strcmp(e.sub, "THRUNNING") == 0) ? K_RUNNING
			     : (strcmp(e.sub, "THREADY") == 0)   ? K_READY
			                                         : K_OTHER;
			if (kind == K_RUNNING && timed && window_known && t < start_t) {
				struct cpurec *const c = &cpus[e.cpu];

				if (!c->anchor_known || t >= c->anchor_t) {
					c->anchor_known = 1;
					c->anchor_t     = t;
					c->anchor_line  = line;
				}
			}
			if (kind == K_RUNNING || thread_at((size_t)th)->cycles > 0u) {
				if (!timed) {
					cpus[e.cpu].untimed_class++;
				} else if (!cap_thread) {
					struct tev v;
					int        pr;

					memset(&v, 0, sizeof(v));
					v.t      = t;
					v.thread = (uint32_t)th;
					v.cpu    = (uint8_t)e.cpu;
					v.kind   = (uint8_t)kind;
					pr       = vec_push(&tevs, &v);
					if (pr != 1) {
						cap_thread    = 1;
						cap_thread_at = (tevs.n > 0u) ? ((struct tev *)vec_at(&tevs, tevs.n - 1u))->t : 0u;
					}
				}
			}
			continue;
		}

		if (strcmp(e.cls, "INTERRUPT") == 0) {
			if (!timed) {
				cpus[e.cpu].untimed_class++;
			} else if (!cap_intr) {
				struct iev v;
				int        pr;

				memset(&v, 0, sizeof(v));
				v.t   = t;
				v.cpu = e.cpu;
				pr    = vec_push(&ievs, &v);
				if (pr != 1) {
					cap_intr    = 1;
					cap_intr_at = (ievs.n > 0u) ? ((struct iev *)vec_at(&ievs, ievs.n - 1u))->t : 0u;
				}
			}
		}
	}
	for (unsigned c = 0; c < MAX_CPUS; c++) {
		if (cpus[c].anchor_known) {
			anchor_add(cpus[c].anchor_line);
		}
	}
}

/* ------------------------------------------------------------------------ */
/* Pairs, classes, eligibility                                               */
/* ------------------------------------------------------------------------ */

static size_t
lower_tev(uint64_t const t)
{
	struct tev const *const v  = tevs.p;
	size_t                  lo = 0;
	size_t                  hi = tevs.n;

	while (lo < hi) {
		size_t const mid = lo + (hi - lo) / 2u;

		if (v[mid].t < t) {
			lo = mid + 1u;
		} else {
			hi = mid;
		}
	}
	return lo;
}

static size_t
lower_iev(uint64_t const t)
{
	struct iev const *const v  = ievs.p;
	size_t                  lo = 0;
	size_t                  hi = ievs.n;

	while (lo < hi) {
		size_t const mid = lo + (hi - lo) / 2u;

		if (v[mid].t < t) {
			lo = mid + 1u;
		} else {
			hi = mid;
		}
	}
	return lo;
}

static int
sorted_tev(void)
{
	struct tev const *const v = tevs.p;

	for (size_t i = 1; i < tevs.n; i++) {
		if (v[i].t < v[i - 1u].t) {
			return 0;
		}
	}
	return 1;
}

static int
sorted_iev(void)
{
	struct iev const *const v = ievs.p;

	for (size_t i = 1; i < ievs.n; i++) {
		if (v[i].t < v[i - 1u].t) {
			return 0;
		}
	}
	return 1;
}

/* A broken fragment of the thread with a first time in [lo, hi]. */
static int
frag_between(uint32_t const thread, uint64_t const lo, uint64_t const hi)
{
	struct frag const *const f  = frags.p;
	size_t                   a  = 0;
	size_t                   b  = frags.n;

	if (hi < lo) {
		return 0;
	}
	while (a < b) {
		size_t const mid = a + (b - a) / 2u;

		if (f[mid].thread < thread || (f[mid].thread == thread && f[mid].t < lo)) {
			a = mid + 1u;
		} else {
			b = mid;
		}
	}
	return a < frags.n && f[a].thread == thread && f[a].t <= hi;
}

static uint8_t
classify(struct triple const *const A, struct triple const *const B, uint64_t const lo, uint64_t const hi,
         uint32_t *const intr)
{
	unsigned const cx  = A->cpu_exit;
	int            mig = B->cpu_enter != A->cpu_exit;
	int            blk = 0;
	int            pre = 0;
	uint32_t       ni  = 0;

	*intr = 0;
	for (unsigned c = 0; c < MAX_CPUS; c++) {
		if (cpus[c].untimed_class != 0u && (!cpus[c].first_known || lo < cpus[c].first_t)) {
			return PC_UNK_UNTIMED;
		}
	}
	if ((cap_thread && hi >= cap_thread_at) || (cap_intr && hi >= cap_intr_at)) {
		return PC_UNK_CAPPED;
	}
	for (size_t i = lower_tev(lo); i < tevs.n; i++) {
		struct tev const *const e = vec_at(&tevs, i);

		if (e->t > hi) {
			break;
		}
		if (e->thread == A->thread) {
			if (e->kind == K_RUNNING) {
				if ((unsigned)e->cpu != cx) {
					mig = 1;
				}
			} else if (e->kind == K_READY) {
				pre = 1;
			} else {
				blk = 1;
			}
		} else if (e->kind == K_RUNNING && (unsigned)e->cpu == cx) {
			pre = 1;
		}
	}
	for (size_t i = lower_iev(lo); i < ievs.n; i++) {
		struct iev const *const e = vec_at(&ievs, i);

		if (e->t > hi) {
			break;
		}
		if (e->cpu == cx) {
			ni++;
		}
	}
	*intr = ni;
	return mig ? PC_MIG : (blk ? PC_BLK : (pre ? PC_PRE : PC_CLEAN));
}

static void
pairs(void)
{
	struct triple *const T = triples.p;

	if (tevs.n > 1u && !sorted_tev()) {
		qsort(tevs.p, tevs.n, sizeof(struct tev), cmp_tev);
	}
	if (ievs.n > 1u && !sorted_iev()) {
		qsort(ievs.p, ievs.n, sizeof(struct iev), cmp_iev);
	}
	for (size_t i = 0; i + 1u < triples.n; i++) {
		struct triple *const       A = &T[i];
		struct triple const *const B = &T[i + 1u];
		uint64_t                   a = 0;
		uint64_t                   b = 0;
		int const                  have_a = (A->flags & F_AX) && (A->flags & F_OFF);
		int const                  have_b = (B->flags & F_AE) && (B->flags & F_OFF);
		uint8_t                    reason;

		if (A->thread != B->thread) {
			continue;
		}
		p_total++;
		A->pflags = 0;
		A->intr   = 0;
		if ((A->flags & F_AX) && (B->flags & F_AE)) {
			A->dwell = (int64_t)(B->ae - A->ax);
			A->pflags |= PF_DWELL;
		}
		if (have_a) {
			a = A->ax - A->off;
			A->pflags |= PF_A;
		}
		if (have_b) {
			b = B->ae - B->off;
		}
		if (have_a && have_b) {
			uint64_t const lo = (a < b) ? a : b;
			uint64_t const hi = (a < b) ? b : a;

			A->pclass = classify(A, B, lo, hi, &A->intr);
		} else {
			A->pclass = PC_UNK_UNTIMED;
		}
		if (A->pclass == PC_UNK_UNTIMED || A->pclass == PC_UNK_CAPPED) {
			p_unk++;
		}

		{
			uint64_t const lo1 = (A->flags & F_X_TIMED) ? A->t_exit : 0u;
			uint64_t const hi1 = (B->flags & F_E_TIMED) ? B->t_enter : 0u;

			if (frag_between(A->thread, lo1, hi1)) {
				reason = R_BROKEN;
			} else if (!(A->flags & F_ORDER_OK) || !(B->flags & F_ORDER_OK)) {
				reason = R_ORDER;
			} else if (opt_e3_status0 && (!(A->flags & F_STATUS) || A->status != 0u ||
			                              !(B->flags & F_STATUS) || B->status != 0u)) {
				reason = R_STATUS;
			} else if (A->dwell < 0) {
				reason = R_NEG;
			} else if (window_known && (a < start_t || b > end_t)) {
				reason = R_WINDOW;
			} else if (ring_state != RING_HELD) {
				reason = R_NOTHELD;
			} else if (A->pclass == PC_UNK_UNTIMED) {
				reason = R_UNTIMED;
			} else if (A->pclass == PC_UNK_CAPPED) {
				reason = R_CAPPED;
			} else {
				reason = R_ELIG;
			}
		}
		A->preason = reason;
		p_reason[reason]++;
		if (reason == R_ELIG) {
			p_class[A->pclass]++;
			p_intr[A->pclass] += A->intr;
		}
		if (have_a && window_known && a >= start_t && a <= end_t) {
			A->pflags |= PF_LIST;
			p_list++;
		}
	}
}

/* ------------------------------------------------------------------------ */
/* Records                                                                   */
/* ------------------------------------------------------------------------ */

static size_t
rank(unsigned const p, size_t const n)
{
	size_t k = ((size_t)p * n + 99u) / 100u;

	if (k < 1u) {
		k = 1u;
	}
	if (k > n) {
		k = n;
	}
	return k;
}

static void
stat_line(const char *const name, int64_t *const v, size_t const n)
{
	int64_t p50;
	int64_t p99;
	int64_t mx;

	if (n == 0u) {
		rec("M4C STAT w=%s class=%s n=0 p50_ticks=- p99_ticks=- max_ticks=- p50_ns=- p99_ns=- max_ns=-"
		    " quantum_ns=%s p99_quotable=no\n", opt_label, name, quantum);
		return;
	}
	qsort(v, n, sizeof(*v), cmp_i64);
	p50 = v[rank(50u, n) - 1u];
	p99 = v[rank(99u, n) - 1u];
	mx  = v[n - 1u];
	rec("M4C STAT w=%s class=%s n=%zu p50_ticks=%" PRId64 " p99_ticks=%" PRId64 " max_ticks=%" PRId64
	    " p50_ns=%" PRIu64 " p99_ns=%" PRIu64 " max_ns=%" PRIu64 " quantum_ns=%s p99_quotable=%s\n",
	    opt_label, name, n, p50, p99, mx,
	    ticks_to_ns((uint64_t)p50, g_cps), ticks_to_ns((uint64_t)p99, g_cps), ticks_to_ns((uint64_t)mx, g_cps),
	    quantum, (n >= QUOTABLE_N) ? "yes" : "no");
}

static void
stats(void)
{
	static const struct {
		const char *name;
		unsigned    mask;
	} which[] = {
		{ "clean", 1u << PC_CLEAN },
		{ "pre", 1u << PC_PRE },
		{ "blk", 1u << PC_BLK },
		{ "mig", 1u << PC_MIG },
		{ "nonblk", (1u << PC_CLEAN) | (1u << PC_PRE) | (1u << PC_MIG) },
	};
	struct triple const *const T    = triples.p;
	size_t const               elig = (size_t)p_reason[R_ELIG];
	int64_t                   *v    = NULL;

	if (elig > 0u) {
		v = malloc(elig * sizeof(*v));
		if (v == NULL) {
			nomem = 1;
		}
	}
	for (size_t w = 0; w < sizeof(which) / sizeof(which[0]); w++) {
		size_t n = 0;

		if (opt_quiet && w != 0u) {
			continue;
		}
		if (v != NULL) {
			for (size_t i = 0; i + 1u < triples.n; i++) {
				if (T[i].pclass != PC_NONE && T[i].preason == R_ELIG && T[i].pclass <= PC_MIG &&
				    ((1u << T[i].pclass) & which[w].mask) != 0u) {
					v[n++] = T[i].dwell;
				}
			}
		}
		stat_line(which[w].name, v, n);
	}
	free(v);
}

static void
cpu_list(char *const buf, size_t const size, int const which)
{
	size_t used = 0;

	buf[0] = '\0';
	for (unsigned c = 0; c < MAX_CPUS; c++) {
		int const hit = (which == 0) ? (cpus[c].events != 0u && cpus[c].wrapped)
		                             : (cpus[c].kept != 0u && cpus[c].first_seq == 1u);

		if (hit) {
			int const k = snprintf(buf + used, size - used, "%s%u", (used != 0u) ? "," : "", c);

			if (k > 0 && (size_t)k < size - used) {
				used += (size_t)k;
			}
		}
	}
	if (used == 0u) {
		(void)snprintf(buf, size, "none");
	}
}

static void
records(void)
{
	char a[24];
	char b[24];
	char list[64];

	rec("M4C IN w=%s path=%s lines=%" PRIu64 " bytes=%" PRIu64 " events=%" PRIu64 " unformatted=%" PRIu64
	    " long_lines=%" PRIu64 " cpu_out_of_range=%" PRIu64 " cps=%" PRIu64 " cps_source=%s\n",
	    opt_label, opt_in, g_lines, g_bytes, g_events, g_unformatted, g_long, g_oor, g_cps,
	    g_cps_header ? "header" : "default");

	if (!opt_quiet) {
		size_t const printed = (nhist < HIST_PRINT) ? nhist : HIST_PRINT;

		for (size_t i = 0; i < printed; i++) {
			rec("M4C HIST w=%s class=%s sub=%s n=%" PRIu64 "\n", opt_label, hist[i].cls, hist[i].sub, hist[i].n);
		}
		if (hist_overflow != 0u) {
			rec("M4C HISTSUM w=%s keys=%zu printed=%zu overflow=%" PRIu64 "\n", opt_label, nhist, printed, hist_overflow);
		} else {
			rec("M4C HISTSUM w=%s keys=%zu printed=%zu\n", opt_label, nhist, printed);
		}
		rec("M4C QVM w=%s enter=%" PRIu64 " exit=%" PRIu64 " cycles=%" PRIu64 " create_vcpu=%" PRIu64
		    " intr_raise=%" PRIu64 " intr_lower=%" PRIu64 " timer=%" PRIu64 " other=%" PRIu64
		    " status_nonzero=%" PRIu64 "\n",
		    opt_label, q_enter, q_exit, q_cycles, q_create, q_raise, q_lower, q_timer, q_other, q_status_nonzero);
		for (size_t i = 0; i < nqothers && i < QOTHER_PRINT; i++) {
			rec("M4C QVMOTHER w=%s sub=%s n=%" PRIu64 "\n", opt_label, qothers[i].sub, qothers[i].n);
		}
		for (size_t i = 0; i < nsamples; i++) {
			rec("M4C SAMPLE w=%s sub=%s line=\"%s\"\n", opt_label, samples[i].sub, samples[i].line);
		}
	}

	rec("M4C TIME64 w=%s mode=%s time_events=%" PRIu64 " mismatches=%" PRIu64 " wraps=%" PRIu64
	    " backsteps=%" PRIu64 " backsteps64=%" PRIu64 " unknown=%" PRIu64 "\n",
	    opt_label,
	    (ts1.n_t64 + ts1.n_rebuilt == 0u) ? "none"
	    : (ts1.n_rebuilt == 0u)           ? "t64"
	    : (ts1.n_t64 == 0u)               ? "rebuilt"
	                                      : "mixed",
	    ts1.time_events, ts1.mismatches, ts1.wraps, ts1.backsteps, ts1.backsteps64, ts1.unknown);

	for (unsigned c = 0; c < MAX_CPUS; c++) {
		if (cpus[c].events == 0u) {
			continue;
		}
		hex_or_dash(a, sizeof(a), cpus[c].first_known, cpus[c].first_t);
		hex_or_dash(b, sizeof(b), cpus[c].first_known, cpus[c].last_t);
		rec("M4C BUF w=%s cpu=%u first_seq=%" PRIu64 " last_seq=%" PRIu64 " kept=%" PRIu64 " gaps=%" PRIu64
		    " restarts=%" PRIu64 " max_events=%" PRIu64 " first_t=%s last_t=%s\n",
		    opt_label, c, cpus[c].first_seq, cpus[c].last_seq, cpus[c].kept, cpus[c].gaps,
		    cpus[c].restarts, cpus[c].max_events, a, b);
	}

	if (!opt_quiet) {
		char sc[8];
		char ec[8];

		hex_or_dash(a, sizeof(a), mk_start.found && mk_start.timed, mk_start.t);
		hex_or_dash(b, sizeof(b), mk_end.found && mk_end.timed, mk_end.t);
		if (mk_start.found) {
			(void)snprintf(sc, sizeof(sc), "%u", mk_start.cpu);
		} else {
			(void)snprintf(sc, sizeof(sc), "-");
		}
		if (mk_end.found) {
			(void)snprintf(ec, sizeof(ec), "%u", mk_end.cpu);
		} else {
			(void)snprintf(ec, sizeof(ec), "-");
		}
		rec("M4C MARK w=%s start=%s start_t=%s start_cpu=%s end=%s end_t=%s end_cpu=%s dup=%" PRIu64 "\n",
		    opt_label, mk_start.found ? "found" : "absent", a, sc, mk_end.found ? "found" : "absent", b, ec, mk_dup);
	}

	{
		char wl[64];

		cpu_list(wl, sizeof(wl), 0);
		cpu_list(list, sizeof(list), 1);
		rec("M4C RING w=%s state=%s wrapped_cpus=%s seq1_cpus=%s\n", opt_label,
		    (ring_state == RING_HELD) ? "held" : ((ring_state == RING_WRAPPED) ? "wrapped" : "unknown"), wl, list);
	}

	if (!opt_quiet) {
		for (unsigned c = 0; c < MAX_CPUS; c++) {
			if (cpus[c].events == 0u) {
				continue;
			}
			if (window_known) {
				rec("M4C RATE w=%s cpu=%u bufs_in_window=%" PRIu64 " events_in_window=%" PRIu64 " span_ticks=%" PRIu64 "\n",
				    opt_label, c, cpus[c].bufs_in_window, cpus[c].events_in_window, end_t - start_t);
			} else {
				rec("M4C RATE w=%s cpu=%u bufs_in_window=0 events_in_window=0 span_ticks=-\n", opt_label, c);
			}
		}
	}

	{
		size_t      nv    = 0;
		long        first = -1;
		char        pid[16];
		char        tid[16];
		uint64_t    cyc   = 0;

		for (size_t i = 0; i < threads.n; i++) {
			if (thread_at(i)->cycles > 0u) {
				if (first < 0) {
					first = (long)i;
				}
				nv++;
			}
		}
		if (first >= 0) {
			struct thread const *const t = thread_at((size_t)first);

			(void)snprintf(pid, sizeof(pid), "%" PRIu32, t->pid);
			(void)snprintf(tid, sizeof(tid), "%" PRIu32, t->tid);
			cyc = t->cycles;
		} else {
			(void)snprintf(pid, sizeof(pid), "-");
			(void)snprintf(tid, sizeof(tid), "-");
		}
		rec("M4C VCPU w=%s threads=%zu pid=%s tid=%s cycles_events=%" PRIu64 " unattributed_qvm=%" PRIu64 "\n",
		    opt_label, nv, pid, tid, cyc, q_unattributed);
	}

	if (!opt_quiet) {
		hex_or_dash(a, sizeof(a), noffsets > 0u, (noffsets > 0u) ? offsets[0] : 0u);
		if (offsets_overflow) {
			rec("M4C OFFSET w=%s distinct=%zu value=%s overflow=1\n", opt_label, noffsets, a);
		} else {
			rec("M4C OFFSET w=%s distinct=%zu value=%s\n", opt_label, noffsets, a);
		}
	}

	rec("M4C TRIPLES w=%s complete=%" PRIu64 " broken=%" PRIu64 " alt_order=%" PRIu64 " order_ok=%" PRIu64
	    " order_violated=%" PRIu64 " in_window=%" PRIu64 "\n",
	    opt_label, tr_complete, tr_broken, tr_alt, tr_ok, tr_violated, tr_in_window);

	rec("M4C PAIRS w=%s total=%" PRIu64 " eligible=%" PRIu64 " clean=%" PRIu64 " pre=%" PRIu64 " blk=%" PRIu64
	    " mig=%" PRIu64 " unk=%" PRIu64 " broken_between=%" PRIu64 " order_violated=%" PRIu64
	    " status_nonzero=%" PRIu64 " negative=%" PRIu64 " out_of_window=%" PRIu64 " not_held=%" PRIu64
	    " untimed=%" PRIu64 " capped=%" PRIu64 " intr_clean=%" PRIu64 " intr_pre=%" PRIu64 " intr_blk=%" PRIu64
	    " intr_mig=%" PRIu64 " e3=%s\n",
	    opt_label, p_total, p_reason[R_ELIG], p_class[PC_CLEAN], p_class[PC_PRE], p_class[PC_BLK],
	    p_class[PC_MIG], p_unk, p_reason[R_BROKEN], p_reason[R_ORDER], p_reason[R_STATUS], p_reason[R_NEG],
	    p_reason[R_WINDOW], p_reason[R_NOTHELD], p_reason[R_UNTIMED], p_reason[R_CAPPED],
	    p_intr[PC_CLEAN], p_intr[PC_PRE], p_intr[PC_BLK], p_intr[PC_MIG], opt_e3_status0 ? "status0" : "none");

	stats();

	if (!opt_quiet) {
		uint64_t const pm     = p_class[PC_PRE] + p_class[PC_MIG];
		uint64_t const nonblk = p_class[PC_CLEAN] + pm;

		if (nonblk > 0u && pm * 100u >= nonblk) {
			rec("M4C WARN w=%s clean_tail_bias pre_mig=%" PRIu64 " nonblk=%" PRIu64 " permille=%" PRIu64 "\n",
			    opt_label, pm, nonblk, pm * 1000u / nonblk);
		}
	}
}

/* ------------------------------------------------------------------------ */
/* Pass 3: the verbatim selection and the compact list (§4.5.8)              */
/* ------------------------------------------------------------------------ */

static int      v_err;
static int      v_errno;
static int      v_capped;
static uint64_t v_lines;
static uint64_t v_bytes;
static uint64_t v_sel_lines;
static uint64_t v_sel_bytes;
static uint64_t v_collision;
static uint64_t v_cr;
static uint64_t v_last_t;
static int      v_last_known;

static int      c_err;
static int      c_errno;
static int      c_capped;
static uint64_t c_lines;
static uint64_t c_bytes;
static uint64_t c_written;

static void
pass3_verbatim(FILE *const f)
{
	char                  buf[LINE_BUF + 1u];
	struct tstate         s;
	uint32_t              line       = 0;
	int                   seen_event = 0;
	size_t                ai         = 0;
	uint32_t const *const A          = anchors.p;
	FILE *const           out        = fopen(opt_vfile, "wb");

	if (out == NULL) {
		v_err   = 1;
		v_errno = errno;
		return;
	}
	memset(&s, 0, sizeof(s));
	rewind(f);
	for (;;) {
		uint64_t  nb = 0;
		int const r  = read_line(f, buf, LINE_BUF, &nb);
		struct ev e;
		int       sel   = 0;
		int       timed = 0;
		uint64_t  t     = 0;
		size_t    len;

		if (r == 0) {
			break;
		}
		line++;
		if (r == 2) {
			continue;
		}
		if (!parse_event(buf, &e)) {
			sel = !seen_event;
		} else if (e.cpu < MAX_CPUS) {
			seen_event = 1;
			timed      = event_time(&s, &e, &t);
			if (strcmp(e.cls, "CONTROL") == 0) {
				sel = 1;
			} else if (timed && window_known && t >= start_t && t <= end_t) {
				sel = 1;
			}
			while (ai < anchors.n && A[ai] < line) {
				ai++;
			}
			if (ai < anchors.n && A[ai] == line) {
				sel = 1;
			}
			/* I23 (m4-design.md 14.5): the marker events themselves, always. Without the end
			 * marker the PC cannot tell a ring that wrapped past the start (I22) from one whose
			 * markers are missing, and its reading of v would disagree with RING. */
			if ((mk_start.found && mk_start.line == line) || (mk_end.found && mk_end.line == line)) {
				sel = 1;
			}
		}
		if (!sel) {
			continue;
		}
		len = strlen(buf);
		if (len == 0u || buf[len - 1u] != '\n') {
			buf[len++] = '\n';
			buf[len]   = '\0';
		}
		if (strstr(buf, FLT_MARK) != NULL) {
			v_collision++;
			continue;
		}
		v_sel_lines++;
		v_sel_bytes += len;
		if (v_capped || v_err) {
			continue;
		}
		if (v_bytes + len > opt_vcap) {
			v_capped = 1;
			continue;
		}
		if (fwrite(buf, 1u, len, out) != len) {
			v_err   = 1;
			v_errno = errno;
			continue;
		}
		v_lines++;
		v_bytes += len;
		for (size_t i = 0; i < len; i++) {
			if (buf[i] == '\r') {
				v_cr++;
			}
		}
		if (timed) {
			v_last_t     = t;
			v_last_known = 1;
		}
	}
	if (fclose(out) != 0 && !v_err) {
		v_err   = 1;
		v_errno = errno;
	}
}

struct listed {
	uint64_t a;
	uint32_t idx;
	uint32_t thread;
};

static int
cmp_listed(const void *const x, const void *const y)
{
	struct listed const *const p = x;
	struct listed const *const q = y;

	if (p->a != q->a) {
		return (p->a < q->a) ? -1 : 1;
	}
	if (p->thread != q->thread) {
		return (p->thread < q->thread) ? -1 : 1;
	}
	return (p->idx < q->idx) ? -1 : ((p->idx > q->idx) ? 1 : 0);
}

static void
pass3_compact(void)
{
	struct triple const *const T   = triples.p;
	struct listed             *L   = NULL;
	size_t                     n   = 0;
	FILE *const                out = fopen(opt_cfile, "wb");
	char                       line[256];
	char                       st[24];
	int                        k;

	if (out == NULL) {
		c_err   = 1;
		c_errno = errno;
		return;
	}
	if (window_known) {
		(void)snprintf(st, sizeof(st), "0x%" PRIx64, start_t);
	} else {
		(void)snprintf(st, sizeof(st), "-");
	}
	k = snprintf(line, sizeof(line),
	             "# m4count compact w=%s start_t=%s cps=%" PRIu64
	             " fields=k,class,elig,dwell_ticks,cpu_exit,cpu_entry,hw_reason,dt_start_ticks\n",
	             opt_label, st, g_cps);
	if (k > 0 && (size_t)k < sizeof(line) && (uint64_t)k <= opt_ccap) {
		if (fwrite(line, 1u, (size_t)k, out) == (size_t)k) {
			c_lines++;
			c_bytes += (uint64_t)k;
		} else {
			c_err   = 1;
			c_errno = errno;
		}
	} else {
		c_capped = 1;
	}
	if (p_list > 0u) {
		L = malloc((size_t)p_list * sizeof(*L));
		if (L == NULL) {
			nomem = 1;
		}
	}
	if (L != NULL) {
		for (size_t i = 0; i + 1u < triples.n; i++) {
			if (T[i].pclass != PC_NONE && (T[i].pflags & PF_LIST) != 0u && n < p_list) {
				L[n].a      = T[i].ax - T[i].off;
				L[n].idx    = (uint32_t)i;
				L[n].thread = T[i].thread;
				n++;
			}
		}
		qsort(L, n, sizeof(*L), cmp_listed);
	}
	for (size_t j = 0; j < n && !c_capped && !c_err; j++) {
		struct triple const *const A = &T[L[j].idx];
		struct triple const *const B = &T[L[j].idx + 1u];
		char                       dw[24];
		char                       hw[24];

		if (A->pflags & PF_DWELL) {
			(void)snprintf(dw, sizeof(dw), "%" PRId64, A->dwell);
		} else {
			(void)snprintf(dw, sizeof(dw), "-");
		}
		if (A->flags & F_HW) {
			(void)snprintf(hw, sizeof(hw), "%" PRIx64, A->hw);
		} else {
			(void)snprintf(hw, sizeof(hw), "-");
		}
		k = snprintf(line, sizeof(line), "c %zu %s %d %s %u %u %s %" PRId64 "\n", j + 1u, CLASS_NAME[A->pclass],
		             (A->preason == R_ELIG) ? 1 : 0, dw, (unsigned)A->cpu_exit, (unsigned)B->cpu_enter, hw,
		             (int64_t)(L[j].a - start_t));
		if (k <= 0 || (size_t)k >= sizeof(line)) {
			continue;
		}
		if (c_bytes + (uint64_t)k > opt_ccap) {
			c_capped = 1;
			break;
		}
		if (fwrite(line, 1u, (size_t)k, out) != (size_t)k) {
			c_err   = 1;
			c_errno = errno;
			break;
		}
		c_lines++;
		c_bytes += (uint64_t)k;
		c_written++;
	}
	free(L);
	if (fclose(out) != 0 && !c_err) {
		c_err   = 1;
		c_errno = errno;
	}
}

/* ------------------------------------------------------------------------ */
/* Command line                                                              */
/* ------------------------------------------------------------------------ */

static int
usage(void)
{
	fprintf(stderr,
	        "usage: m4count -i LISTING -w NAME -s START -e END [-q] [-v VFILE -V VCAP]\n"
	        "               [-c CFILE -C CCAP] [-P MAXTRIPLES] [-T MAXTHREAD] [-E status0|none]\n"
	        "  VCAP, CCAP 1-%lu bytes; MAXTRIPLES, MAXTHREAD %lu-%lu\n"
	        "  exit: 0 parsed, 1 input, output or memory error, 2 usage, 3 a table cap was hit\n",
	        MAX_CAP_BYTES, MIN_TABLE, MAX_TABLE);
	return 2;
}

static int
parse_ul(const char *const s, unsigned long const lo, unsigned long const hi, unsigned long *const v)
{
	char         *end = NULL;
	unsigned long x;

	if (s[0] < '0' || s[0] > '9') {
		return 0;
	}
	errno = 0;
	x     = strtoul(s, &end, 10);
	if (errno != 0 || *end != '\0' || x < lo || x > hi) {
		return 0;
	}
	*v = x;
	return 1;
}

static int
valid_label(const char *const s)
{
	size_t const n = strlen(s);

	if (n == 0u || n > LABEL_MAX) {
		return 0;
	}
	for (size_t i = 0; i < n; i++) {
		char const c = s[i];

		if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' ||
		      c == '.' || c == '-')) {
			return 0;
		}
	}
	return 1;
}

static int
options(int const argc, char **const argv)
{
	for (int i = 1; i < argc; i++) {
		const char *const a   = argv[i];
		int const         val = (i + 1 < argc);

		if (strcmp(a, "-q") == 0) {
			opt_quiet = 1;
		} else if (!val) {
			return 0;
		} else if (strcmp(a, "-i") == 0 && opt_in == NULL) {
			opt_in = argv[++i];
		} else if (strcmp(a, "-w") == 0 && opt_label == NULL) {
			opt_label = argv[++i];
		} else if (strcmp(a, "-s") == 0 && opt_start == NULL) {
			opt_start = argv[++i];
		} else if (strcmp(a, "-e") == 0 && opt_end == NULL) {
			opt_end = argv[++i];
		} else if (strcmp(a, "-v") == 0 && opt_vfile == NULL) {
			opt_vfile = argv[++i];
		} else if (strcmp(a, "-c") == 0 && opt_cfile == NULL) {
			opt_cfile = argv[++i];
		} else if (strcmp(a, "-V") == 0 && opt_vcap == 0u) {
			if (!parse_ul(argv[++i], 1ul, MAX_CAP_BYTES, &opt_vcap)) {
				return 0;
			}
		} else if (strcmp(a, "-C") == 0 && opt_ccap == 0u) {
			if (!parse_ul(argv[++i], 1ul, MAX_CAP_BYTES, &opt_ccap)) {
				return 0;
			}
		} else if (strcmp(a, "-P") == 0) {
			if (!parse_ul(argv[++i], MIN_TABLE, MAX_TABLE, &opt_max_triples)) {
				return 0;
			}
		} else if (strcmp(a, "-T") == 0) {
			if (!parse_ul(argv[++i], MIN_TABLE, MAX_TABLE, &opt_max_thread)) {
				return 0;
			}
		} else if (strcmp(a, "-E") == 0) {
			const char *const m = argv[++i];

			if (strcmp(m, "status0") == 0) {
				opt_e3_status0 = 1;
			} else if (strcmp(m, "none") == 0) {
				opt_e3_status0 = 0;
			} else {
				return 0;
			}
		} else {
			return 0;
		}
	}
	if (opt_in == NULL || opt_label == NULL || opt_start == NULL || opt_end == NULL) {
		return 0;
	}
	if (!valid_label(opt_label) || opt_start[0] == '\0' || opt_end[0] == '\0' ||
	    strchr(opt_start, '"') != NULL || strchr(opt_end, '"') != NULL || strcmp(opt_start, opt_end) == 0) {
		return 0;
	}
	if ((opt_vfile == NULL) != (opt_vcap == 0u) || (opt_cfile == NULL) != (opt_ccap == 0u)) {
		return 0;
	}
	return 1;
}

/* ------------------------------------------------------------------------ */
/* main                                                                      */
/* ------------------------------------------------------------------------ */

static void
end_record(int *const rc)
{
	const char *reason;

	if (nomem) {
		*rc    = 1;
		reason = "nomem";
	} else if (g_events == 0u) {
		*rc    = 1;
		reason = "input";
	} else if (v_err || c_err) {
		*rc    = 1;
		reason = "output";
	} else if (cap_triples) {
		*rc    = 3;
		reason = "cap-triples";
	} else if (cap_thread) {
		*rc    = 3;
		reason = "cap-thread";
	} else if (cap_intr) {
		*rc    = 3;
		reason = "cap-intr";
	} else {
		*rc    = 0;
		reason = "ok";
	}
	rec("M4C END w=%s rc=%d reason=%s\n", opt_label, *rc, reason);
}

int
main(int argc, char **argv)
{
	FILE    *f;
	uint64_t t0;
	int      rc = 0;

#if defined(_MSC_VER)
	(void)_setmode(_fileno(stdout), _O_BINARY);
#endif
	if (!options(argc, argv)) {
		return usage();
	}
	vec_init(&threads, sizeof(struct thread), MAX_THREADS);
	vec_init(&triples, sizeof(struct triple), opt_max_triples);
	vec_init(&frags, sizeof(struct frag), opt_max_triples);
	vec_init(&tevs, sizeof(struct tev), opt_max_thread);
	vec_init(&ievs, sizeof(struct iev), opt_max_thread);
	vec_init(&anchors, sizeof(uint32_t), ANCHOR_MAX);
	for (unsigned c = 0; c < MAX_CPUS; c++) {
		running[c] = -1;
	}
	hist      = calloc(HIST_SLOTS, sizeof(*hist));
	hist_hash = calloc((size_t)HIST_SLOTS * 2u, sizeof(*hist_hash));
	if (hist == NULL || hist_hash == NULL) {
		nomem = 1;
		rec("M4C END w=%s rc=1 reason=nomem\n", opt_label);
		return 1;
	}

	f = fopen(opt_in, "rb");
	if (f == NULL) {
		int const e = errno;

		rec("M4C IN w=%s path=%s error=open errno=%d\n", opt_label, opt_in, e);
		rec("M4C END w=%s rc=1 reason=input\n", opt_label);
		return 1;
	}

	t0 = mono_ms();
	pass1(f);
	if (!opt_quiet) {
		rec("M4C PASS w=%s pass=1 lines=%" PRIu64 " ms=%" PRIu64 "\n", opt_label, g_lines, mono_ms() - t0);
	}
	between_passes();

	t0 = mono_ms();
	pass2(f);
	if (!opt_quiet) {
		rec("M4C PASS w=%s pass=2 lines=%" PRIu64 " ms=%" PRIu64 "\n", opt_label, g_lines, mono_ms() - t0);
	}
	if (anchors.n > 1u) {
		size_t          w = 1;
		uint32_t *const A = anchors.p;

		qsort(A, anchors.n, sizeof(*A), cmp_u32);
		for (size_t i = 1; i < anchors.n; i++) {
			if (A[i] != A[w - 1u]) {
				A[w++] = A[i];
			}
		}
		anchors.n = w;
	}
	pairs();

	if (NS_PER_S % g_cps == 0u) {
		(void)snprintf(quantum, sizeof(quantum), "%" PRIu64, (uint64_t)NS_PER_S / g_cps);
	} else {
		(void)snprintf(quantum, sizeof(quantum), "inexact");
	}
	records();

	if (opt_vfile != NULL || opt_cfile != NULL) {
		t0 = mono_ms();
		if (opt_vfile != NULL) {
			pass3_verbatim(f);
		}
		if (opt_cfile != NULL) {
			pass3_compact();
		}
		if (!opt_quiet) {
			rec("M4C PASS w=%s pass=3 lines=%" PRIu64 " ms=%" PRIu64 "\n", opt_label, g_lines, mono_ms() - t0);
		}
		if (opt_vfile != NULL) {
			char lt[24];

			if (v_err) {
				rec("M4C FLT w=%s form=v file=%s error=write errno=%d\n", opt_label, opt_vfile, v_errno);
			} else {
				hex_or_dash(lt, sizeof(lt), v_last_known, v_last_t);
				rec("M4C FLT w=%s form=v file=%s lines=%" PRIu64 " bytes=%" PRIu64 " capped=%d sel_lines=%" PRIu64
				    " sel_bytes=%" PRIu64 " last_t=%s marker_collision=%" PRIu64 " cr_bytes=%" PRIu64 "\n",
				    opt_label, opt_vfile, v_lines, v_bytes, v_capped, v_sel_lines, v_sel_bytes, lt, v_collision,
				    v_cr);
			}
		}
		if (opt_cfile != NULL) {
			if (c_err) {
				rec("M4C FLT w=%s form=c file=%s error=write errno=%d\n", opt_label, opt_cfile, c_errno);
			} else {
				rec("M4C FLT w=%s form=c file=%s lines=%" PRIu64 " bytes=%" PRIu64 " capped=%d pairs_written=%" PRIu64
				    " pairs_total=%" PRIu64 "\n",
				    opt_label, opt_cfile, c_lines, c_bytes, c_capped, c_written, p_list);
			}
		}
	}
	(void)fclose(f);
	end_record(&rc);
	return rc;
}
