/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * memcanary — read-only checks of S1's memory canaries, and one host allocation.
 *
 * Phase 3b, the S1-F design's §3.8 (results/orin-native-port/20260909T1100Z/
 * s1-design.md, revision 2). Pass item 4 asks for host memory canaries intact
 * at the end of a ten-minute run. With -b w2,canary the board startup takes
 * three fixed 16 MiB ranges out of the RAM allocator with alloc_ram, registers
 * each as an asinfo entry named "s1canary", and writes every 8-byte word as
 * splitmix64(base + offset) before procnto starts (§3.3). This program never
 * writes physical memory. It has no write mode and no address argument; it
 * reads only the three ranges compiled into the table below, and each only
 * after the system page shows it registered and outside "sysram".
 *
 *   memcanary asinfo
 *   memcanary verify -n c1|c2|c3
 *   memcanary alloc -s MIB
 *   memcanary hold -s MIB -f TRIGGER -T SECS -o FILE
 *   memcanary --selftest
 *
 * asinfo walks the system page's asinfo section and prints one line:
 *
 *   S1 ASINFO sysram_w1=yes|no sysram_w2=yes|no s1canary=<n> canary_in_sysram=no|yes gpu_in_sysram=no|yes
 *
 * sysram_wN is yes when a "sysram" entry overlaps window N; s1canary counts the
 * entries of that name; canary_in_sysram and gpu_in_sysram are yes when a
 * "sysram" entry overlaps any table canary, or the GPU range. A section that
 * does not decode prints "S1 ASINFO error=undecodable".
 *
 * verify refuses unless an "s1canary" entry has exactly the named range and no
 * "sysram" entry overlaps it; otherwise it maps the range PROT_READ with
 * mmap_device_memory and compares every word with the pattern:
 *
 *   S1 CANARY c1 refuse=no-entry        (" asinfo=undecodable" appended if so)
 *   S1 CANARY c1 refuse=in-sysram
 *   S1 CANARY c1 map=fail errno=<n>
 *   S1 CANARY c1 verify=ok
 *   S1 CANARY c1 verify=bad first_off=0x<hex> words=<n>
 *
 * A name outside the table prints "S1 CANARY refuse=unknown-name", without
 * echoing it, and exits 2.
 *
 * alloc maps MIB (1-3072) MiB of private anonymous memory, writes every word as
 * splitmix64(seed + offset), where offset is the byte offset in the mapping and
 * seed is ClockCycles() at the start, compares, and unmaps, in one call:
 *
 *   S1 ALLOC mib=<MIB> fill=ok verify=ok
 *   S1 ALLOC mib=<MIB> fill=ok verify=bad first_off=0x<hex> words=<n>
 *   S1 ALLOC mib=<MIB> map=fail errno=<n>
 *
 * hold does the same, but keeps the filled mapping until TRIGGER exists: one
 * stat() a second, for at most SECS (1-86400). It prints nothing, because the
 * host script starts it in the background and a console write there busy-polls
 * the TCU callout (design §2 rule 7). It truncates FILE, removes FILE.fill and
 * FILE.done, and writes its lines to FILE, one write each; a marker is created
 * only after its line is complete, so a bwait -p on the marker never races the
 * line:
 *
 *   S1 ALLOC hold mib=<MIB> fill=ok                                    then FILE.fill
 *   S1 ALLOC hold mib=<MIB> verify=ok                                  then FILE.done
 *   S1 ALLOC hold mib=<MIB> verify=bad first_off=0x<hex> words=<n>     then FILE.done
 *   S1 ALLOC hold mib=<MIB> verify=timeout data=ok                     then FILE.done
 *   S1 ALLOC hold mib=<MIB> verify=timeout data=bad first_off=0x<hex> words=<n>
 *   S1 ALLOC hold mib=<MIB> map=fail errno=<n>                         then FILE.fill and FILE.done
 *
 * --selftest checks the pattern against fixed vectors, the table's geometry,
 * the name lookup (an unknown name, and the black box at 0x272770000, which has
 * no entry by construction), the asinfo decoding, the summary and the refusals
 * against simulated system pages, every output line's text, and the fill and
 * compare on a heap buffer. It reads no system page and maps no physical
 * memory, so it runs on any QNX aarch64 target:
 *
 *   MEMCANARY SELFTEST PASS <n> checks  |  MEMCANARY SELFTEST FAIL <f> of <n> checks
 *
 * Exit: 0 ok; 1 a refusal, a mismatch, a map failure, a timeout, an
 * undecodable section or a failed self-test; 2 on a malformed command line or
 * an unknown name.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/neutrino.h>
#include <sys/stat.h>
#include <sys/syspage.h>
#include <sys/types.h>

/* The design constants (§3.3, D18). make-s1-images.sh checks them against
 * board/t234_startup.h, so each stays on its own line in this form. */
#define S1_W1_BASE          0x80000000ull
#define S1_W1_SIZE          0x3E000000ull       /* 992 MiB, -m992M */
#define S1_W2_BASE          0x100000000ull
#define S1_W2_SIZE          0x8A000000ull       /* 2,208 MiB */
#define S1_GPU_BASE         0x18A000000ull
#define S1_GPU_SIZE         0xC0000000ull       /* 3,072 MiB, never added */
#define S1_CANARY_SIZE      0x1000000ull        /* 16 MiB */
#define S1_CANARY_C1_BASE   0xBD000000ull
#define S1_CANARY_C2_BASE   0x100000000ull
#define S1_CANARY_C3_BASE   0x189000000ull

/* Self-test only: what no canary may touch (board/t234_startup.h; plan:864). */
#define S1_CMA_BASE         0x24A000000ull
#define S1_BB_BASE          0x272770000ull
#define S1_BB_SIZE          0x10000ull

#define MIB                 0x100000ull
#define MIB_MAX             3072u
#define SECS_MAX            86400u
#define NAP_MS              1000u
#define AS_MAX              256
#define LINE_BUF            256
#define PATH_BUF            512

struct canary {
	const char *name;
	uint64_t    base;
};

static const struct canary table[] = {
	{ "c1", S1_CANARY_C1_BASE },
	{ "c2", S1_CANARY_C2_BASE },
	{ "c3", S1_CANARY_C3_BASE },
};

#define NCANARY (sizeof(table) / sizeof(table[0]))

static uint64_t cps;

static void say(const char *fmt, ...) __attribute__((__format__(__printf__, 1, 2)));

/* One complete line, one write, to stdout. */
static void
say(const char *const fmt, ...)
{
	char    line[LINE_BUF];
	va_list ap;
	int     n;

	va_start(ap, fmt);
	n = vsnprintf(line, sizeof(line), fmt, ap);
	va_end(ap);
	if (n <= 0) {
		return;
	}
	if ((size_t)n >= sizeof(line)) {
		n = (int)sizeof(line) - 1;
		line[n - 1] = '\n';
	}
	for (size_t off = 0; off < (size_t)n;) {
		ssize_t const w = write(STDOUT_FILENO, line + off, (size_t)n - off);

		if (w < 0) {
			if (errno == EINTR) {
				continue;
			}
			return;
		}
		off += (size_t)w;
	}
}

/* The fill pattern; startup computes the same function of the same input. */
static uint64_t
splitmix64(uint64_t const x)
{
	uint64_t z = x + 0x9E3779B97F4A7C15ull;

	z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
	z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
	return z ^ (z >> 31);
}

static void
fill_words(uint64_t *const w, uint64_t const nwords, uint64_t const base)
{
	for (uint64_t i = 0; i < nwords; i++) {
		w[i] = splitmix64(base + i * 8u);
	}
}

/* Mismatching words, and the byte offset of the first one. */
static uint64_t
check_words(const uint64_t *const w, uint64_t const nwords, uint64_t const base, uint64_t *const first_off)
{
	uint64_t bad = 0;

	*first_off = 0;
	for (uint64_t i = 0; i < nwords; i++) {
		if (w[i] != splitmix64(base + i * 8u)) {
			if (bad == 0) {
				*first_off = i * 8u;
			}
			bad++;
		}
	}
	return bad;
}

static const struct canary *
lookup(const char *const name)
{
	for (size_t k = 0; k < NCANARY; k++) {
		if (strcmp(table[k].name, name) == 0) {
			return &table[k];
		}
	}
	return NULL;
}

/* ---------------------------------------------------------------- asinfo */

struct as_view {
	uint64_t    start;
	uint64_t    end;                /* inclusive, as the syspage keeps it */
	const char *name;
};

/* An asinfo array and its strings section, decoded into views. Pure, so the
 * self-test can hand it a synthetic section. The count, or -1. */
static int
view_decode(const void *const arr, unsigned const nbytes, unsigned const esz, const char *const strs,
            unsigned const slen, struct as_view *const v, unsigned const cap)
{
	unsigned n;

	if (esz < sizeof(struct asinfo_entry) || nbytes % esz != 0 || nbytes / esz > cap) {
		return -1;
	}
	n = nbytes / esz;
	for (unsigned i = 0; i < n; i++) {
		struct asinfo_entry e;

		memcpy(&e, (const char *)arr + (size_t)i * esz, sizeof(e));
		v[i].start = e.start;
		v[i].end   = e.end;
		v[i].name  = "?";
		for (unsigned j = e.name; j < slen; j++) {
			if (strs[j] == '\0') {
				v[i].name = strs + e.name;
				break;
			}
		}
	}
	return (int)n;
}

static int
view_load(struct as_view *const v, unsigned const cap)
{
	unsigned const esz = SYSPAGE_ELEMENT_SIZE(asinfo);

	return view_decode(SYSPAGE_ENTRY(asinfo), SYSPAGE_ENTRY_SIZE(asinfo),
	                   (esz != 0) ? esz : (unsigned)sizeof(struct asinfo_entry),
	                   (const char *)(void *)SYSPAGE_ENTRY(strings), SYSPAGE_ENTRY_SIZE(strings), v, cap);
}

static int
overlaps(const struct as_view *const e, uint64_t const base, uint64_t const size)
{
	return e->start <= base + size - 1u && base <= e->end;
}

struct as_summary {
	int      sysram_w1;
	int      sysram_w2;
	unsigned s1canary;
	int      canary_in_sysram;
	int      gpu_in_sysram;
};

static void
summarise(const struct as_view *const v, unsigned const n, struct as_summary *const s)
{
	memset(s, 0, sizeof(*s));
	for (unsigned i = 0; i < n; i++) {
		if (strcmp(v[i].name, "s1canary") == 0) {
			s->s1canary++;
		}
		if (strcmp(v[i].name, "sysram") != 0) {
			continue;
		}
		s->sysram_w1     |= overlaps(&v[i], S1_W1_BASE, S1_W1_SIZE);
		s->sysram_w2     |= overlaps(&v[i], S1_W2_BASE, S1_W2_SIZE);
		s->gpu_in_sysram |= overlaps(&v[i], S1_GPU_BASE, S1_GPU_SIZE);
		for (size_t k = 0; k < NCANARY; k++) {
			s->canary_in_sysram |= overlaps(&v[i], table[k].base, S1_CANARY_SIZE);
		}
	}
}

static int
format_asinfo(char *const line, size_t const cap, const struct as_summary *const s)
{
	int const n = snprintf(line, cap, "S1 ASINFO sysram_w1=%s sysram_w2=%s s1canary=%u canary_in_sysram=%s gpu_in_sysram=%s",
	                       s->sysram_w1 ? "yes" : "no", s->sysram_w2 ? "yes" : "no", s->s1canary,
	                       s->canary_in_sysram ? "yes" : "no", s->gpu_in_sysram ? "yes" : "no");

	return n > 0 && (size_t)n < cap;
}

enum refusal { C_OK, C_NO_ENTRY, C_IN_SYSRAM };

static enum refusal
canary_check(const struct as_view *const v, unsigned const n, uint64_t const base)
{
	int found = 0;

	for (unsigned i = 0; i < n; i++) {
		if (strcmp(v[i].name, "s1canary") == 0 && v[i].start == base
		    && v[i].end == base + S1_CANARY_SIZE - 1u) {
			found = 1;
		}
	}
	if (!found) {
		return C_NO_ENTRY;
	}
	for (unsigned i = 0; i < n; i++) {
		if (strcmp(v[i].name, "sysram") == 0 && overlaps(&v[i], base, S1_CANARY_SIZE)) {
			return C_IN_SYSRAM;
		}
	}
	return C_OK;
}

/* ---------------------------------------------------------------- lines */

enum verdict { V_OK, V_BAD, V_MAPFAIL, V_NOENTRY, V_INSYSRAM, V_FILLED, V_TIMEOUT_OK, V_TIMEOUT_BAD };

static int
format_canary(char *const line, size_t const cap, const char *const name, enum verdict const vd,
              uint64_t const first_off, uint64_t const words, int const err)
{
	int n = -1;

	switch (vd) {
	case V_OK:
		n = snprintf(line, cap, "S1 CANARY %s verify=ok", name);
		break;
	case V_BAD:
		n = snprintf(line, cap, "S1 CANARY %s verify=bad first_off=0x%llx words=%llu", name,
		             (unsigned long long)first_off, (unsigned long long)words);
		break;
	case V_MAPFAIL:
		n = snprintf(line, cap, "S1 CANARY %s map=fail errno=%d", name, err);
		break;
	case V_NOENTRY:
		n = snprintf(line, cap, "S1 CANARY %s refuse=no-entry", name);
		break;
	case V_INSYSRAM:
		n = snprintf(line, cap, "S1 CANARY %s refuse=in-sysram", name);
		break;
	default:
		break;
	}
	return n > 0 && (size_t)n < cap;
}

static int
format_alloc(char *const line, size_t const cap, int const hold, unsigned const mib, enum verdict const vd,
             uint64_t const first_off, uint64_t const words, int const err)
{
	const char *const head = hold ? "S1 ALLOC hold" : "S1 ALLOC";
	char              bad[80];
	int               n = -1;

	(void)snprintf(bad, sizeof(bad), "first_off=0x%llx words=%llu",
	               (unsigned long long)first_off, (unsigned long long)words);
	switch (vd) {
	case V_OK:
		n = snprintf(line, cap, hold ? "%s mib=%u verify=ok" : "%s mib=%u fill=ok verify=ok", head, mib);
		break;
	case V_BAD:
		n = snprintf(line, cap, hold ? "%s mib=%u verify=bad %s" : "%s mib=%u fill=ok verify=bad %s",
		             head, mib, bad);
		break;
	case V_MAPFAIL:
		n = snprintf(line, cap, "%s mib=%u map=fail errno=%d", head, mib, err);
		break;
	case V_FILLED:
		n = hold ? snprintf(line, cap, "%s mib=%u fill=ok", head, mib) : -1;
		break;
	case V_TIMEOUT_OK:
		n = hold ? snprintf(line, cap, "%s mib=%u verify=timeout data=ok", head, mib) : -1;
		break;
	case V_TIMEOUT_BAD:
		n = hold ? snprintf(line, cap, "%s mib=%u verify=timeout data=bad %s", head, mib, bad) : -1;
		break;
	default:
		break;
	}
	return n > 0 && (size_t)n < cap;
}

/* ---------------------------------------------------------------- modes */

static int
cmd_asinfo(void)
{
	static struct as_view v[AS_MAX];
	struct as_summary     s;
	char                  line[LINE_BUF];
	int const             n = view_load(v, AS_MAX);

	if (n < 0) {
		say("S1 ASINFO error=undecodable\n");
		return 1;
	}
	summarise(v, (unsigned)n, &s);
	if (!format_asinfo(line, sizeof(line), &s)) {
		say("S1 ASINFO error=format\n");
		return 1;
	}
	say("%s\n", line);
	return 0;
}

static int
cmd_verify(const char *const name)
{
	static struct as_view      v[AS_MAX];
	const struct canary *const c = lookup(name);
	char                       line[LINE_BUF];
	uint64_t                   first = 0;
	uint64_t                   bad;
	enum refusal               k;
	int                        n;
	void                      *p;

	if (c == NULL) {
		say("S1 CANARY refuse=unknown-name\n");
		return 2;
	}
	n = view_load(v, AS_MAX);
	k = (n < 0) ? C_NO_ENTRY : canary_check(v, (unsigned)n, c->base);
	if (k != C_OK) {
		(void)format_canary(line, sizeof(line), c->name, (k == C_NO_ENTRY) ? V_NOENTRY : V_INSYSRAM, 0, 0, 0);
		say("%s%s\n", line, (n < 0) ? " asinfo=undecodable" : "");
		return 1;
	}

	p = mmap_device_memory(NULL, (size_t)S1_CANARY_SIZE, PROT_READ, 0, c->base);
	if (p == MAP_FAILED) {
		(void)format_canary(line, sizeof(line), c->name, V_MAPFAIL, 0, 0, errno);
		say("%s\n", line);
		return 1;
	}
	bad = check_words((const uint64_t *)p, S1_CANARY_SIZE / 8u, c->base, &first);
	(void)munmap_device_memory(p, (size_t)S1_CANARY_SIZE);
	(void)format_canary(line, sizeof(line), c->name, (bad == 0) ? V_OK : V_BAD, first, bad, 0);
	say("%s\n", line);
	return (bad == 0) ? 0 : 1;
}

static void *
map_anon(unsigned const mib)
{
	return mmap(NULL, (size_t)mib * MIB, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, NOFD, 0);
}

static int
cmd_alloc(unsigned const mib)
{
	size_t const   len   = (size_t)mib * MIB;
	uint64_t const seed  = ClockCycles();
	void *const    p     = map_anon(mib);
	uint64_t       first = 0;
	uint64_t       bad;
	char           line[LINE_BUF];

	if (p == MAP_FAILED) {
		(void)format_alloc(line, sizeof(line), 0, mib, V_MAPFAIL, 0, 0, errno);
		say("%s\n", line);
		return 1;
	}
	fill_words((uint64_t *)p, len / 8u, seed);
	bad = check_words((const uint64_t *)p, len / 8u, seed, &first);
	(void)munmap(p, len);
	(void)format_alloc(line, sizeof(line), 0, mib, (bad == 0) ? V_OK : V_BAD, first, bad, 0);
	say("%s\n", line);
	return (bad == 0) ? 0 : 1;
}

static uint64_t
cycles_to_ms(uint64_t const d)
{
	return d / cps * 1000u + (d % cps) * 1000u / cps;
}

/* Sleep toward the deadline, at most max_ms; the caller re-checks the counter. */
static void
nap_toward(uint64_t const deadline, unsigned const max_ms)
{
	uint64_t const  now = ClockCycles();
	uint64_t        ms;
	struct timespec ts;

	if (now >= deadline) {
		return;
	}
	ms = cycles_to_ms(deadline - now) + 1u;
	if (ms > max_ms) {
		ms = max_ms;
	}
	ts.tv_sec  = (time_t)(ms / 1000u);
	ts.tv_nsec = (long)((ms % 1000u) * 1000000u);
	(void)nanosleep(&ts, NULL);
}

/* One line, one write; 0 or -1. */
static int
put_line(int const fd, const char *const line)
{
	char         buf[LINE_BUF + 1];
	int const    n = snprintf(buf, sizeof(buf), "%s\n", line);
	ssize_t      w;

	if (n <= 0 || (size_t)n >= sizeof(buf)) {
		return -1;
	}
	do {
		w = write(fd, buf, (size_t)n);
	} while (w < 0 && errno == EINTR);
	return (w == (ssize_t)n) ? 0 : -1;
}

static void
touch(const char *const path)
{
	int const fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);

	if (fd >= 0) {
		(void)close(fd);
	}
}

static int
cmd_hold(unsigned const mib, const char *const trigger, unsigned const secs, const char *const file,
         const char *const fill_path, const char *const done_path)
{
	size_t const len   = (size_t)mib * MIB;
	uint64_t     first = 0;
	uint64_t     bad;
	uint64_t     seed;
	uint64_t     deadline;
	int          hit = 0;
	int          ok  = 1;
	int          fd;
	void        *p;
	struct stat  sb;
	char         line[LINE_BUF];

	(void)unlink(fill_path);
	(void)unlink(done_path);
	fd = open(file, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fd < 0) {
		fprintf(stderr, "memcanary: open %s: %s\n", file, strerror(errno));
		return 1;
	}

	seed = ClockCycles();
	p    = map_anon(mib);
	if (p == MAP_FAILED) {
		(void)format_alloc(line, sizeof(line), 1, mib, V_MAPFAIL, 0, 0, errno);
		(void)put_line(fd, line);
		(void)close(fd);
		touch(fill_path);
		touch(done_path);
		return 1;
	}
	fill_words((uint64_t *)p, len / 8u, seed);
	(void)format_alloc(line, sizeof(line), 1, mib, V_FILLED, 0, 0, 0);
	ok &= (put_line(fd, line) == 0);
	touch(fill_path);

	deadline = ClockCycles() + (uint64_t)secs * cps;
	for (;;) {
		if (stat(trigger, &sb) == 0) {
			hit = 1;
			break;
		}
		if (ClockCycles() >= deadline) {
			break;
		}
		nap_toward(deadline, NAP_MS);
	}

	bad = check_words((const uint64_t *)p, len / 8u, seed, &first);
	(void)munmap(p, len);
	(void)format_alloc(line, sizeof(line), 1, mib,
	                   hit ? ((bad == 0) ? V_OK : V_BAD) : ((bad == 0) ? V_TIMEOUT_OK : V_TIMEOUT_BAD),
	                   first, bad, 0);
	ok &= (put_line(fd, line) == 0);
	(void)close(fd);
	touch(done_path);
	if (!ok) {
		fprintf(stderr, "memcanary: write %s failed\n", file);
	}
	return (ok && hit && bad == 0) ? 0 : 1;
}

/* ---------------------------------------------------------------- self-test */

static unsigned st_ran;
static unsigned st_fail;

static void
check(int const ok, const char *const what)
{
	st_ran++;
	if (!ok) {
		st_fail++;
		say("MEMCANARY SELFTEST fail %s\n", what);
	}
}

static const char sim_strs[] = "memory\0ram\0sysram\0s1canary\0startup";

#define SIM_MAX 16

struct sim {
	struct asinfo_entry raw[SIM_MAX];
	unsigned            n;
	int                 overflow;
};

static uint16_t
sim_off(const char *const name)
{
	for (size_t i = 0; i < sizeof(sim_strs); i += strlen(sim_strs + i) + 1u) {
		if (strcmp(sim_strs + i, name) == 0) {
			return (uint16_t)i;
		}
	}
	return AS_NULL_OFF;
}

static void
sim_add(struct sim *const s, uint64_t const start, uint64_t const end, const char *const name)
{
	struct asinfo_entry *e;

	if (s->n == SIM_MAX) {
		s->overflow = 1;
		return;
	}
	e = &s->raw[s->n++];
	memset(e, 0, sizeof(*e));
	e->start    = start;
	e->end      = end;
	e->owner    = AS_NULL_OFF;
	e->name     = sim_off(name);
	e->priority = AS_PRIORITY_DEFAULT;
}

/* What -b w2,canary is designed to leave (§3.3), with each variant's one change. */
enum sim_kind { SIM_GOOD, SIM_OPTION_OFF, SIM_CANARY_IN_SYSRAM, SIM_ENTRY_MOVED, SIM_GPU_IN_SYSRAM, SIM_TCG };

static int
sim_build(enum sim_kind const kind, struct as_view *const v)
{
	struct sim s;

	memset(&s, 0, sizeof(s));
	sim_add(&s, 0, 0xFFFFFFFFFFull, "memory");
	if (kind == SIM_TCG) {
		sim_add(&s, 0x40000000ull, 0xBFFFFFFFull, "ram");
		sim_add(&s, 0x40000000ull, 0xBFFFFFFFull, "sysram");
	} else {
		sim_add(&s, S1_W1_BASE, S1_W1_BASE + S1_W1_SIZE - 1u, "ram");
		sim_add(&s, 0x80080000ull, 0x835FFFFFull, "startup");
		sim_add(&s, S1_W1_BASE, 0x8007FFFFull, "sysram");
		if (kind == SIM_OPTION_OFF) {
			sim_add(&s, 0x83600000ull, S1_W1_BASE + S1_W1_SIZE - 1u, "sysram");
		} else {
			uint64_t const w2_top = (kind == SIM_GPU_IN_SYSRAM) ? S1_GPU_BASE + S1_GPU_SIZE - 1u
			                        : (kind == SIM_CANARY_IN_SYSRAM) ? S1_W2_BASE + S1_W2_SIZE - 1u
			                        : S1_CANARY_C3_BASE - 1u;

			sim_add(&s, 0x83600000ull, S1_CANARY_C1_BASE - 1u, "sysram");
			sim_add(&s, S1_W2_BASE, S1_W2_BASE + S1_W2_SIZE - 1u, "ram");
			sim_add(&s, S1_CANARY_C2_BASE + S1_CANARY_SIZE, w2_top, "sysram");
			if (kind == SIM_ENTRY_MOVED) {
				sim_add(&s, S1_CANARY_C1_BASE, S1_CANARY_C1_BASE + S1_CANARY_SIZE - 2u, "s1canary");
				sim_add(&s, S1_CANARY_C2_BASE + 0x1000u, S1_CANARY_C2_BASE + S1_CANARY_SIZE + 0xFFFu, "s1canary");
			} else {
				sim_add(&s, S1_CANARY_C1_BASE, S1_CANARY_C1_BASE + S1_CANARY_SIZE - 1u, "s1canary");
				sim_add(&s, S1_CANARY_C2_BASE, S1_CANARY_C2_BASE + S1_CANARY_SIZE - 1u, "s1canary");
			}
			sim_add(&s, S1_CANARY_C3_BASE, S1_CANARY_C3_BASE + S1_CANARY_SIZE - 1u, "s1canary");
		}
	}
	if (s.overflow) {
		return -1;
	}
	return view_decode(s.raw, s.n * (unsigned)sizeof(struct asinfo_entry), (unsigned)sizeof(struct asinfo_entry),
	                   sim_strs, (unsigned)sizeof(sim_strs), v, AS_MAX);
}

static int
line_is(const char *const got, int const fitted, const char *const want)
{
	return fitted && strcmp(got, want) == 0;
}

static int
sim_line(enum sim_kind const kind, const char *const want)
{
	static struct as_view v[AS_MAX];
	struct as_summary     s;
	char                  line[LINE_BUF];
	int const             n = sim_build(kind, v);

	if (n < 0) {
		return 0;
	}
	summarise(v, (unsigned)n, &s);
	return line_is(line, format_asinfo(line, sizeof(line), &s), want);
}

static int
sim_refusal(enum sim_kind const kind, uint64_t const base, enum refusal const want)
{
	static struct as_view v[AS_MAX];
	int const             n = sim_build(kind, v);

	return n >= 0 && canary_check(v, (unsigned)n, base) == want;
}

static int
inside(uint64_t const base, uint64_t const size, uint64_t const wbase, uint64_t const wsize)
{
	return base >= wbase && base + size <= wbase + wsize;
}

static int
disjoint(uint64_t const a, uint64_t const asize, uint64_t const b, uint64_t const bsize)
{
	return a + asize <= b || b + bsize <= a;
}

static int
selftest(void)
{
	static struct as_view v[AS_MAX];
	static const char    *refused[] = { "", "c0", "c4", "C1", "c1 ", " c1", "c", "c10", "s1canary",
	                                    "0x272770000", "272770000", "bb", "gpu", "w2" };
	uint64_t              w[64];
	uint8_t               wide[4 * (sizeof(struct asinfo_entry) + 8u)];
	struct sim            s;
	char                  line[LINE_BUF];
	uint64_t              first = 0;
	int                   n;
	int                   ok;

	/* The pattern: splitmix64's first two outputs from state 0, and canary words
	 * at fixed places, so a startup fill can be checked against the same numbers. */
	check(splitmix64(0) == 0xE220A8397B1DCDAFull, "splitmix64(0)");
	check(splitmix64(0x9E3779B97F4A7C15ull) == 0x6E789E6AA1B965F4ull, "splitmix64(0x9e3779b97f4a7c15)");
	check(splitmix64(S1_CANARY_C1_BASE) == 0x67A21DEE21C7807Eull, "pattern c1+0x0");
	check(splitmix64(S1_CANARY_C1_BASE + 8u) == 0xB78E336F73A3571Aull, "pattern c1+0x8");
	check(splitmix64(S1_CANARY_C2_BASE) == 0xC42C5A1AA3820138ull, "pattern c2+0x0");
	check(splitmix64(S1_CANARY_C3_BASE + S1_CANARY_SIZE - 8u) == 0x41F6AB1BCDFCCB0Dull, "pattern c3+0xfffff8");

	/* Fill and compare, on a heap buffer only. */
	fill_words(w, 64u, S1_CANARY_C1_BASE);
	check(w[0] == 0x67A21DEE21C7807Eull && w[1] == 0xB78E336F73A3571Aull, "fill writes the canary pattern");
	check(check_words(w, 64u, S1_CANARY_C1_BASE, &first) == 0 && first == 0, "compare: clean buffer");
	w[5] ^= 1u;
	w[9] ^= 0x8000000000000000ull;
	check(check_words(w, 64u, S1_CANARY_C1_BASE, &first) == 2 && first == 0x28u, "compare: two words, first at 0x28");
	check(check_words(w, 64u, S1_CANARY_C2_BASE, &first) == 64 && first == 0, "compare: wrong base");

	/* The table: three names, sizes and places; nothing else answers. */
	check(NCANARY == 3 && lookup("c1") == &table[0] && lookup("c2") == &table[1] && lookup("c3") == &table[2],
	      "table names c1-c3");
	check(table[0].base == 0xBD000000ull && table[1].base == 0x100000000ull && table[2].base == 0x189000000ull
	      && S1_CANARY_SIZE == 0x1000000ull, "table bases and size");
	ok = 1;
	for (size_t i = 0; i < sizeof(refused) / sizeof(refused[0]); i++) {
		ok &= (lookup(refused[i]) == NULL);
	}
	check(ok, "unknown names refused, the black box's address among them");
	ok = 1;
	for (size_t k = 0; k < NCANARY; k++) {
		ok &= !(S1_BB_BASE >= table[k].base && S1_BB_BASE < table[k].base + S1_CANARY_SIZE);
	}
	check(ok, "no table range holds the black box");
	ok = 1;
	for (size_t k = 0; k < NCANARY; k++) {
		uint64_t const b = table[k].base;
		uint64_t const e = b + S1_CANARY_SIZE;

		ok &= inside(b, S1_CANARY_SIZE, S1_W1_BASE, S1_W1_SIZE) || inside(b, S1_CANARY_SIZE, S1_W2_BASE, S1_W2_SIZE);
		ok &= disjoint(b, S1_CANARY_SIZE, S1_GPU_BASE, S1_GPU_SIZE);
		ok &= disjoint(b, S1_CANARY_SIZE, S1_BB_BASE, S1_BB_SIZE);
		ok &= (b % 0x1000u) == 0;
		ok &= e != S1_W2_BASE;
		for (size_t j = 0; j < NCANARY; j++) {
			if (j != k) {
				ok &= disjoint(b, S1_CANARY_SIZE, table[j].base, S1_CANARY_SIZE) && e != table[j].base;
			}
		}
	}
	check(ok, "canaries inside a window, apart, clear of the GPU range and the black box");
	check(S1_W1_BASE + S1_W1_SIZE <= S1_W2_BASE && S1_W2_BASE + S1_W2_SIZE == S1_GPU_BASE
	      && S1_GPU_BASE + S1_GPU_SIZE == S1_CMA_BASE && S1_CMA_BASE < S1_BB_BASE,
	      "window 2 ends at the GPU range, which ends at CMA");

	/* Decoding a section. */
	memset(&s, 0, sizeof(s));
	sim_add(&s, 0x1000u, 0x1FFFu, "sysram");
	sim_add(&s, 0x2000u, 0x2FFFu, "s1canary");
	sim_add(&s, 0x3000u, 0x3FFFu, "startup");
	n = view_decode(s.raw, 3u * (unsigned)sizeof(struct asinfo_entry), (unsigned)sizeof(struct asinfo_entry),
	                sim_strs, (unsigned)sizeof(sim_strs), v, AS_MAX);
	check(n == 3 && v[0].start == 0x1000u && v[0].end == 0x1FFFu && strcmp(v[0].name, "sysram") == 0
	      && strcmp(v[1].name, "s1canary") == 0 && strcmp(v[2].name, "startup") == 0, "decode names and ranges");
	n = view_decode(s.raw, 3u * (unsigned)sizeof(struct asinfo_entry), (unsigned)sizeof(struct asinfo_entry),
	                sim_strs, (unsigned)sizeof(sim_strs) - 1u, v, AS_MAX);
	check(n == 3 && strcmp(v[2].name, "?") == 0 && strcmp(v[0].name, "sysram") == 0,
	      "decode: a name with no NUL inside the section is \"?\"");
	s.raw[1].name = 0xFFF0u;
	n = view_decode(s.raw, 3u * (unsigned)sizeof(struct asinfo_entry), (unsigned)sizeof(struct asinfo_entry),
	                sim_strs, (unsigned)sizeof(sim_strs), v, AS_MAX);
	check(n == 3 && strcmp(v[1].name, "?") == 0, "decode: a name offset past the section is \"?\"");
	check(view_decode(s.raw, 3u * (unsigned)sizeof(struct asinfo_entry), (unsigned)sizeof(struct asinfo_entry) - 1u,
	                  sim_strs, (unsigned)sizeof(sim_strs), v, AS_MAX) == -1, "decode: element too small refused");
	check(view_decode(s.raw, 3u * (unsigned)sizeof(struct asinfo_entry) - 1u, (unsigned)sizeof(struct asinfo_entry),
	                  sim_strs, (unsigned)sizeof(sim_strs), v, AS_MAX) == -1, "decode: ragged section refused");
	check(view_decode(s.raw, 3u * (unsigned)sizeof(struct asinfo_entry), (unsigned)sizeof(struct asinfo_entry),
	                  sim_strs, (unsigned)sizeof(sim_strs), v, 2u) == -1, "decode: more entries than room refused");
	memset(wide, 0xA5, sizeof(wide));
	s.raw[1].name = sim_off("s1canary");
	for (unsigned i = 0; i < 3u; i++) {
		memcpy(wide + i * (sizeof(struct asinfo_entry) + 8u), &s.raw[i], sizeof(struct asinfo_entry));
	}
	n = view_decode(wide, 3u * ((unsigned)sizeof(struct asinfo_entry) + 8u), (unsigned)sizeof(struct asinfo_entry) + 8u,
	                sim_strs, (unsigned)sizeof(sim_strs), v, AS_MAX);
	check(n == 3 && v[2].start == 0x3000u && strcmp(v[1].name, "s1canary") == 0,
	      "decode: a larger element size is stepped over");

	/* The summary and the refusals, on simulated system pages. */
	check(sim_line(SIM_GOOD, "S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=no gpu_in_sysram=no"),
	      "asinfo: as designed");
	check(sim_refusal(SIM_GOOD, S1_CANARY_C1_BASE, C_OK) && sim_refusal(SIM_GOOD, S1_CANARY_C2_BASE, C_OK)
	      && sim_refusal(SIM_GOOD, S1_CANARY_C3_BASE, C_OK), "verify: c1-c3 accepted as designed");
	check(sim_line(SIM_OPTION_OFF, "S1 ASINFO sysram_w1=yes sysram_w2=no s1canary=0 canary_in_sysram=yes gpu_in_sysram=no"),
	      "asinfo: option off");
	check(sim_refusal(SIM_OPTION_OFF, S1_CANARY_C1_BASE, C_NO_ENTRY)
	      && sim_refusal(SIM_OPTION_OFF, S1_CANARY_C2_BASE, C_NO_ENTRY), "verify: no entry refused");
	check(sim_line(SIM_CANARY_IN_SYSRAM,
	               "S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=yes gpu_in_sysram=no"),
	      "asinfo: a canary left in sysram");
	check(sim_refusal(SIM_CANARY_IN_SYSRAM, S1_CANARY_C3_BASE, C_IN_SYSRAM)
	      && sim_refusal(SIM_CANARY_IN_SYSRAM, S1_CANARY_C1_BASE, C_OK), "verify: a sysram overlap refused");
	check(sim_refusal(SIM_ENTRY_MOVED, S1_CANARY_C1_BASE, C_NO_ENTRY)
	      && sim_refusal(SIM_ENTRY_MOVED, S1_CANARY_C2_BASE, C_NO_ENTRY)
	      && sim_refusal(SIM_ENTRY_MOVED, S1_CANARY_C3_BASE, C_OK), "verify: an entry one byte short or moved refused");
	check(sim_line(SIM_GPU_IN_SYSRAM,
	               "S1 ASINFO sysram_w1=yes sysram_w2=yes s1canary=3 canary_in_sysram=yes gpu_in_sysram=yes"),
	      "asinfo: the GPU range in sysram");
	check(sim_refusal(SIM_TCG, S1_CANARY_C1_BASE, C_NO_ENTRY) && sim_refusal(SIM_TCG, S1_CANARY_C2_BASE, C_NO_ENTRY)
	      && sim_refusal(SIM_TCG, S1_CANARY_C3_BASE, C_NO_ENTRY), "verify: a TCG host has no entry");

	/* Every output line's text. */
	check(line_is(line, format_canary(line, sizeof(line), "c1", V_OK, 0, 0, 0), "S1 CANARY c1 verify=ok"),
	      "line canary ok");
	check(line_is(line, format_canary(line, sizeof(line), "c1", V_BAD, 0x28u, 2u, 0),
	              "S1 CANARY c1 verify=bad first_off=0x28 words=2"), "line canary bad");
	check(line_is(line, format_canary(line, sizeof(line), "c2", V_NOENTRY, 0, 0, 0), "S1 CANARY c2 refuse=no-entry"),
	      "line canary no-entry");
	check(line_is(line, format_canary(line, sizeof(line), "c3", V_INSYSRAM, 0, 0, 0), "S1 CANARY c3 refuse=in-sysram"),
	      "line canary in-sysram");
	check(line_is(line, format_canary(line, sizeof(line), "c1", V_MAPFAIL, 0, 0, 12), "S1 CANARY c1 map=fail errno=12"),
	      "line canary map");
	check(line_is(line, format_alloc(line, sizeof(line), 0, 1536u, V_OK, 0, 0, 0), "S1 ALLOC mib=1536 fill=ok verify=ok"),
	      "line alloc ok");
	check(line_is(line, format_alloc(line, sizeof(line), 0, 1536u, V_BAD, 0x28u, 2u, 0),
	              "S1 ALLOC mib=1536 fill=ok verify=bad first_off=0x28 words=2"), "line alloc bad");
	check(line_is(line, format_alloc(line, sizeof(line), 0, 1536u, V_MAPFAIL, 0, 0, 12),
	              "S1 ALLOC mib=1536 map=fail errno=12"), "line alloc map");
	check(line_is(line, format_alloc(line, sizeof(line), 1, 256u, V_FILLED, 0, 0, 0), "S1 ALLOC hold mib=256 fill=ok"),
	      "line hold fill");
	check(line_is(line, format_alloc(line, sizeof(line), 1, 256u, V_OK, 0, 0, 0), "S1 ALLOC hold mib=256 verify=ok"),
	      "line hold ok");
	check(line_is(line, format_alloc(line, sizeof(line), 1, 256u, V_BAD, 0x28u, 2u, 0),
	              "S1 ALLOC hold mib=256 verify=bad first_off=0x28 words=2"), "line hold bad");
	check(line_is(line, format_alloc(line, sizeof(line), 1, 64u, V_TIMEOUT_OK, 0, 0, 0),
	              "S1 ALLOC hold mib=64 verify=timeout data=ok"), "line hold timeout");
	check(line_is(line, format_alloc(line, sizeof(line), 1, 64u, V_TIMEOUT_BAD, 0x28u, 2u, 0),
	              "S1 ALLOC hold mib=64 verify=timeout data=bad first_off=0x28 words=2"), "line hold timeout bad");
	check(line_is(line, format_alloc(line, sizeof(line), 1, 64u, V_MAPFAIL, 0, 0, 12),
	              "S1 ALLOC hold mib=64 map=fail errno=12"), "line hold map");
	check(!format_alloc(line, sizeof(line), 0, 64u, V_FILLED, 0, 0, 0), "line: alloc has no separate fill line");

	if (st_fail == 0) {
		say("MEMCANARY SELFTEST PASS %u checks\n", st_ran);
		return 0;
	}
	say("MEMCANARY SELFTEST FAIL %u of %u checks\n", st_fail, st_ran);
	return 1;
}

/* ---------------------------------------------------------------- main */

static int
usage(void)
{
	fprintf(stderr,
	        "usage: memcanary asinfo\n"
	        "       memcanary verify -n c1|c2|c3\n"
	        "       memcanary alloc -s MIB\n"
	        "       memcanary hold -s MIB -f TRIGGER -T SECS -o FILE\n"
	        "       memcanary --selftest\n"
	        "  MIB is 1-3072 and SECS 1-86400; hold writes FILE, then FILE.fill and FILE.done\n"
	        "  no mode writes physical memory, and none takes an address\n");
	return 2;
}

static int
parse_uint(const char *const s, unsigned const lo, unsigned const hi, unsigned *const v)
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
	*v = (unsigned)x;
	return 1;
}

int
main(int argc, char **argv)
{
	const char *mode;
	const char *name    = NULL;
	const char *trigger = NULL;
	const char *file    = NULL;
	unsigned    mib     = 0;
	unsigned    secs    = 0;
	int         have_s  = 0;
	int         have_t  = 0;

	if (argc < 2) {
		return usage();
	}
	mode = argv[1];
	if (strcmp(mode, "--selftest") == 0 || strcmp(mode, "asinfo") == 0) {
		if (argc != 2) {
			return usage();
		}
		return (mode[0] == '-') ? selftest() : cmd_asinfo();
	}

	for (int i = 2; i < argc; i++) {
		const char *const a   = argv[i];
		int const         val = (i + 1 < argc);

		if (val && strcmp(a, "-n") == 0 && name == NULL) {
			name = argv[++i];
		} else if (val && strcmp(a, "-s") == 0 && !have_s) {
			if (!parse_uint(argv[++i], 1u, MIB_MAX, &mib)) {
				return usage();
			}
			have_s = 1;
		} else if (val && strcmp(a, "-f") == 0 && trigger == NULL) {
			trigger = argv[++i];
		} else if (val && strcmp(a, "-T") == 0 && !have_t) {
			if (!parse_uint(argv[++i], 1u, SECS_MAX, &secs)) {
				return usage();
			}
			have_t = 1;
		} else if (val && strcmp(a, "-o") == 0 && file == NULL) {
			file = argv[++i];
		} else {
			return usage();
		}
	}

	if (strcmp(mode, "verify") == 0) {
		if (name == NULL || have_s || trigger != NULL || have_t || file != NULL) {
			return usage();
		}
		return cmd_verify(name);
	}
	if (strcmp(mode, "alloc") == 0) {
		if (!have_s || name != NULL || trigger != NULL || have_t || file != NULL) {
			return usage();
		}
		return cmd_alloc(mib);
	}
	if (strcmp(mode, "hold") == 0) {
		char fill_path[PATH_BUF];
		char done_path[PATH_BUF];
		int  nf;
		int  nd;

		if (!have_s || trigger == NULL || !have_t || file == NULL || name != NULL) {
			return usage();
		}
		nf = snprintf(fill_path, sizeof(fill_path), "%s.fill", file);
		nd = snprintf(done_path, sizeof(done_path), "%s.done", file);
		if (nf <= 0 || (size_t)nf >= sizeof(fill_path) || nd <= 0 || (size_t)nd >= sizeof(done_path)) {
			return usage();
		}
		cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
		if (cps == 0) {
			fprintf(stderr, "memcanary: qtime reports no cycles_per_sec\n");
			return 1;
		}
		return cmd_hold(mib, trigger, secs, file, fill_path, done_path);
	}
	return usage();
}
