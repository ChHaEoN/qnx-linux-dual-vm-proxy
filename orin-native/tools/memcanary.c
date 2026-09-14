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
 *
 * memcanary-w is J6's watcher (s1-design.md §15.4.8, §15.5 B1-B2), built from
 * this file with -DMEMCANARY_WATCH. Every addition sits under that macro, so the
 * plain build stays byte-identical to its pin (§15.5 B8.1). It adds one mode:
 *
 *   memcanary-w watch -n c1|c2|c3 -l LABEL -i MS -c COUNT -T SECS -d /dev/shmem/j1LABEL.bin
 *
 * LABEL is [a-z0-9]{1,8}; MS 0-60000 is the sleep before each snapshot; COUNT is
 * 1-100000 snapshots; SECS 1-3600 is the deadline, counted from the end of BASE;
 * the file is /dev/shmem/j1 with this watch's own LABEL and .bin, exactly, so a
 * watch never writes the hold's files or another label's. A hex or any other
 * address is refused like any unknown name. watch keeps verify's refusals and
 * its PROT_READ mapping; its only writes are two heap copies of the range (BASE
 * and the last read) and one small file. It reads every word once (BASE), then
 * takes snapshots until COUNT or the deadline, then reads every word once more
 * (FINL). A word read that differs from what it is compared with (the pattern at
 * BASE, its last read after) is read twice more at once, B and C. When B and C
 * agree on the last read (at BASE: on any value other than the first read), the
 * first read did not hold: it is counted revert, and revert_flip2 when it
 * differed in 1-2 bits, and nothing else. Otherwise a snapshot counts the change
 * as osc (A-B-A), stable (A-A-A) or prog (anything else: A-B-B, A-B-C, A-A-C),
 * healed when C is the pattern, and whole_heal once for each page whose words
 * all healed in that snapshot; C becomes the last read. Nothing is printed inside
 * the loop (§2 rule 7). FINL gives the bad set, which is classified by word class
 * (first match wins), by in-page offset modulo 64, and by byte signatures scanned
 * at every offset of each bad extent; signatures are positive-only. Then one file
 * write, and eight lines, each under 255 bytes at maximum field widths:
 *
 *   S1 CANARY <n> watch=base label=<l> bad=<n> pages=<n> first_off=0x<hex> last_off=0x<hex>
 *   S1 CANARY <n> watch=time label=<l> snaps=<n> changed_snaps=<n> changed_words=<n> healed=<n> osc=<n> prog=<n> stable=<n> stop=count|deadline
 *   S1 CANARY <n> watch=reread label=<l> revert=<n> revert_flip2=<n> whole_heal=<n>
 *   S1 CANARY <n> watch=words label=<l> bad=<n> zero=<n> ones=<n> flip2_same=<n> flip2_var=<n> flip8=<n> pat_same=<n> pat_other=<n>
 *   S1 CANARY <n> watch=words2 label=<l> hi_pat=<n> lo_pat=<n> pte=<n> kva=<n> ptr_self=<n> ptr_ram=<n> u32page=<n> small32=<n> other=<n>
 *   S1 CANARY <n> watch=stride label=<l> b0=<n> ... b7=<n>
 *   S1 CANARY <n> watch=bytes label=<l> ascii_runs=<n> ascii_bytes=<n> ipv4=<n> beacon=<n> trb_evt=<n>
 *   S1 CANARY <n> watch=verdict label=<l> writer=none|static|stopped|ongoing heal=no|yes reads=stable|revert|osc|prog content=<list>|unclassified|none
 *   S1 CANARY <n> watch=fail label=<l> reason=nomem|dump-open|dump-write errno=<n>
 *
 * The file holds offsets and counts only, never a word value or a byte: a 64 B
 * header (magic S1J1PBMP), three page bitmaps (bad_final, changed_ever,
 * healed_ever) and a 32 B tail of counts; cw_export below gives the layout. No
 * value of the range leaves this program (D28 is not taken). Under the macro,
 * --selftest also runs the watch checks and prints first
 *
 *   MEMCANARY-W SELFTEST PASS <n> checks  |  MEMCANARY-W SELFTEST FAIL <f> of <n> checks
 *
 * watch exits 0 when complete, whatever the words hold; 1 on a refusal, a map
 * failure, no memory or a file failure; 2 on a malformed command line or an
 * unknown name.
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

#ifdef MEMCANARY_WATCH
/* ---------------------------------------------------------------- watch */

/* DRAM's end, T234_RAM_BASE + 8 GiB; make-s1-images.sh's constant check reads this line
 * (s1-design.md §15.5 B5). DRAM starts at S1_W1_BASE. */
#define S1_DRAM_END         0x280000000ull

#define CW_PAGE             0x1000ull
#define CW_WORDS_PER_PAGE   (CW_PAGE / 8u)
#define CW_PAGES            4096u               /* S1_CANARY_SIZE / CW_PAGE */
#define CW_BMAP             ((CW_PAGES + 7u) / 8u)
#define CW_MS_MAX           60000u
#define CW_COUNT_MAX        100000u
#define CW_SECS_MAX         3600u
#define CW_LABEL_MAX        8u
#define CW_DUMP_PREFIX      "/dev/shmem/j1"
#define CW_DUMP_SUFFIX      ".bin"
#define CW_FILE_VERSION     1u
#define CW_FILE_HEAD        64u
#define CW_FILE_TAIL        32u
#define CW_FILE_MAX         (CW_FILE_HEAD + 3u * CW_BMAP + CW_FILE_TAIL)
#define CW_ASCII_MIN        16u
#define CW_LIST_BUF         128
#define CW_U(x)             ((unsigned long long)(x))

/* Word classes in precedence order: the first rule that matches wins, so they sum to bad. */
enum cw_class {
	K_ZERO, K_ONES, K_FLIP2_SAME, K_FLIP2_VAR, K_FLIP8, K_PAT_SAME, K_PAT_OTHER, K_HI_PAT, K_LO_PAT,
	K_PTE, K_KVA, K_PTR_SELF, K_PTR_RAM, K_U32PAGE, K_SMALL32, K_OTHER, K_NCLASS
};

static const char *const cw_class_name[K_NCLASS] = {
	"zero", "ones", "flip2_same", "flip2_var", "flip8", "pat_same", "pat_other", "hi_pat", "lo_pat",
	"pte", "kva", "ptr_self", "ptr_ram", "u32page", "small32", "other"
};

/* The inverse of an odd a modulo 2^64: each Newton step doubles the correct low bits, 3 to 96. */
static uint64_t
inv64(uint64_t const a)
{
	uint64_t x = a;

	for (int k = 0; k < 5; k++) {
		x *= 2u - a * x;
	}
	return x;
}

/* The inverse of y = z ^ (z >> s), 0 < s < 64: each step fixes s more high bits. */
static uint64_t
unshift(uint64_t const y, unsigned const s)
{
	uint64_t z = y;

	for (unsigned k = s; k < 64u; k += s) {
		z = y ^ (z >> s);
	}
	return z;
}

/* splitmix64's input from its output: unmix64(splitmix64(x)) == x. */
static uint64_t
unmix64(uint64_t const v)
{
	uint64_t z = unshift(v, 31u);

	z = unshift(z * inv64(0x94D049BB133111EBull), 27u);
	z = unshift(z * inv64(0xBF58476D1CE4E5B9ull), 30u);
	return z - 0x9E3779B97F4A7C15ull;
}

/* The class of one bad word v at byte offset off of the canary at cbase, whose BASE read was b
 * (§15.4.8). Each rule is our reading of a public specification, from memory: HYPOTHESIS, and
 * cw_selftest encodes that reading.
 *   flip2 and flip8: 1-2 and 3-8 bits differ from the pattern; flip2_same when they are the bits
 *     BASE's read differed in;
 *   pat_same and pat_other: splitmix64's inverse lands on another 8-byte-aligned offset of this
 *     canary, or of another table canary;
 *   hi_pat and lo_pat: only the low, or only the high, 32 bits differ;
 *   pte: an ARMv8-A VMSA descriptor with bits[1:0] = 0b11 (a table descriptor at levels 0-2, a page
 *     descriptor at level 3), bits[51:48] clear (RES0 for a 48-bit output address with a 4 KiB
 *     granule), and an output address bits[47:12] in DRAM;
 *   kva: the top 16 bits all ones; ptr_self: inside this canary; ptr_ram: inside DRAM;
 *   u32page: below 4 GiB and page-aligned; small32: below 4 GiB otherwise (ring indices, counters
 *     and queue headers; HYPOTHESIS on such layouts). The 32-bit all-ones value, a common invalid
 *     index, is small32 ahead of pte and the pointer rules, which would otherwise read it as a
 *     descriptor into DRAM (a reading added before J6's pre-registration; HYPOTHESIS). */
static enum cw_class
cw_classify(uint64_t const v, uint64_t const off, uint64_t const b, uint64_t const cbase)
{
	uint64_t const p     = splitmix64(cbase + off);
	uint64_t const d     = v ^ p;
	int const      flips = __builtin_popcountll(d);
	uint64_t const oa    = v & 0x0000FFFFFFFFF000ull;
	uint64_t const x     = unmix64(v);

	if (v == 0) {
		return K_ZERO;
	}
	if (v == ~0ull) {
		return K_ONES;
	}
	if (flips <= 2) {
		return (d == (b ^ p)) ? K_FLIP2_SAME : K_FLIP2_VAR;
	}
	if (flips <= 8) {
		return K_FLIP8;
	}
	if (x - cbase < S1_CANARY_SIZE && (x - cbase) % 8u == 0) {
		return K_PAT_SAME;
	}
	for (size_t k = 0; k < NCANARY; k++) {
		if (table[k].base != cbase && x - table[k].base < S1_CANARY_SIZE && (x - table[k].base) % 8u == 0) {
			return K_PAT_OTHER;
		}
	}
	if ((v >> 32) == (p >> 32)) {
		return K_HI_PAT;
	}
	if ((uint32_t)v == (uint32_t)p) {
		return K_LO_PAT;
	}
	if (v == 0xFFFFFFFFull) {
		return K_SMALL32;
	}
	if ((v & 3u) == 3u && (v & 0x000F000000000000ull) == 0 && oa >= S1_W1_BASE && oa < S1_DRAM_END) {
		return K_PTE;
	}
	if ((v >> 48) == 0xFFFFu) {
		return K_KVA;
	}
	if (v - cbase < S1_CANARY_SIZE) {
		return K_PTR_SELF;
	}
	if (v >= S1_W1_BASE && v < S1_DRAM_END) {
		return K_PTR_RAM;
	}
	if (v < 0x100000000ull) {
		return ((v & (CW_PAGE - 1u)) == 0) ? K_U32PAGE : K_SMALL32;
	}
	return K_OTHER;
}

/* watch's arguments. The name is only a string here; lookup() refuses anything but c1-c3. */
struct cw_args {
	const char *name;
	const char *label;
	const char *dump;
	unsigned    ms;
	unsigned    count;
	unsigned    secs;
};

static int cw_parse(int argc, char **argv, struct cw_args *a);

/* [a-z0-9]{1,8} */
static int
cw_label_ok(const char *const s)
{
	size_t const n = strlen(s);

	if (n < 1u || n > CW_LABEL_MAX) {
		return 0;
	}
	for (size_t i = 0; i < n; i++) {
		if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= '0' && s[i] <= '9'))) {
			return 0;
		}
	}
	return 1;
}

/* Exactly /dev/shmem/j1LABEL.bin for this watch's own label, already checked by cw_label_ok: never the
 * hold's trigger or output files, which share the /dev/shmem/j1 prefix, and never another label's file. */
static int
cw_dump_ok(const char *const s, const char *const label)
{
	char      want[sizeof(CW_DUMP_PREFIX) + CW_LABEL_MAX + sizeof(CW_DUMP_SUFFIX)];
	int const n = snprintf(want, sizeof(want), "%s%s%s", CW_DUMP_PREFIX, label, CW_DUMP_SUFFIX);

	return n > 0 && (size_t)n < sizeof(want) && strcmp(s, want) == 0;
}

/* One word source: the device mapping, or a self-test's scripted buffer. */
struct cw_src {
	uint64_t (*read)(void *ctx, uint64_t i);
	void     *ctx;
};

/* The mapping is read through volatile, so the compiler can never merge a word's three reads. */
static uint64_t
cw_read_dev(void *const ctx, uint64_t const i)
{
	const volatile uint64_t *const w = ctx;

	return w[i];
}

enum cw_stop { STOP_NONE, STOP_COUNT, STOP_DEADLINE };

struct cw_state {
	uint64_t     cbase;
	uint64_t     nwords;             /* a whole number of pages, at most S1_CANARY_SIZE / 8 */
	uint64_t    *base;               /* BASE's read */
	uint64_t    *prev;               /* each word's last read; FINL's after cw_final */
	uint64_t     base_bad;
	uint64_t     base_pages;
	uint64_t     first_off;
	uint64_t     last_off;
	uint64_t     snaps;
	uint64_t     changed_snaps;
	uint64_t     changed_words;
	uint64_t     healed;
	uint64_t     osc;
	uint64_t     prog;
	uint64_t     stable;
	uint64_t     revert;             /* re-reads that did not hold their first read: BASE, snapshots and FINL */
	uint64_t     revert_flip2;       /* reverts whose first read differed in 1-2 bits from the re-reads */
	uint64_t     whole_heal;         /* (snapshot, page) pairs in which every word of the page healed */
	uint64_t     last_change;        /* the last snapshot with a change, from 1; 0 for none */
	enum cw_stop stop;
	uint64_t     final_diff;         /* words whose FINL read differs from their last read */
	uint64_t     final_bad;
	uint64_t     cls[K_NCLASS];
	uint64_t     stride[8];
	uint64_t     ascii_runs;
	uint64_t     ascii_bytes;
	uint64_t     ipv4;
	uint64_t     beacon;
	uint64_t     trb_evt;
	uint8_t      bad_final[CW_BMAP];
	uint8_t      changed_ever[CW_BMAP];
	uint8_t      healed_ever[CW_BMAP];
};

static void
bit_set(uint8_t *const map, uint64_t const page)
{
	map[page / 8u] |= (uint8_t)(1u << (page % 8u));
}

/* A revert: a first read a that the two re-reads, both c, did not repeat. */
static void
cw_revert(struct cw_state *const st, uint64_t const a, uint64_t const c)
{
	st->revert++;
	if (__builtin_popcountll(a ^ c) <= 2) {
		st->revert_flip2++;
	}
}

/* BASE: one read of every word, kept as base and prev, and its bad words against the pattern. A read
 * that differs from the pattern is read twice more at once; when those two agree on another value,
 * the first read is a revert, and the last read is the one kept. */
static void
cw_base(struct cw_state *const st, const struct cw_src *const src)
{
	uint64_t last_page = UINT64_MAX;

	for (uint64_t i = 0; i < st->nwords; i++) {
		uint64_t const p = splitmix64(st->cbase + i * 8u);
		uint64_t       a = src->read(src->ctx, i);

		if (a != p) {
			uint64_t const b = src->read(src->ctx, i);
			uint64_t const c = src->read(src->ctx, i);

			if (b == c && c != a) {
				cw_revert(st, a, c);
			}
			a = c;
		}
		st->base[i] = a;
		st->prev[i] = a;
		if (a != p) {
			if (st->base_bad == 0) {
				st->first_off = i * 8u;
			}
			st->last_off = i * 8u;
			st->base_bad++;
			if (i / CW_WORDS_PER_PAGE != last_page) {
				last_page = i / CW_WORDS_PER_PAGE;
				st->base_pages++;
			}
		}
	}
}

/* One snapshot. A word whose read A differs from its last read is read twice more at once, B and C.
 * B and C both the last read: A did not hold, a revert, and nothing else is counted or marked.
 * Otherwise a change: stable A-A-A, osc A-B-A (a marginal read), prog otherwise (A-B-B, A-B-C,
 * A-A-C: a writer in progress); healed when C is the pattern, and whole_heal when every word of
 * the page healed in this snapshot. C becomes the last read. */
static void
cw_snap(struct cw_state *const st, const struct cw_src *const src)
{
	uint64_t changed    = 0;
	uint64_t page_heals = 0;

	st->snaps++;
	for (uint64_t i = 0; i < st->nwords; i++) {
		uint64_t const a = src->read(src->ctx, i);

		if (a != st->prev[i]) {
			uint64_t const b = src->read(src->ctx, i);
			uint64_t const c = src->read(src->ctx, i);

			if (b == c && c == st->prev[i]) {
				cw_revert(st, a, c);
			} else {
				if (a == b && b == c) {
					st->stable++;
				} else if (b != a && c == a) {
					st->osc++;
				} else {
					st->prog++;
				}
				bit_set(st->changed_ever, i / CW_WORDS_PER_PAGE);
				if (c == splitmix64(st->cbase + i * 8u)) {
					st->healed++;
					page_heals++;
					bit_set(st->healed_ever, i / CW_WORDS_PER_PAGE);
				}
				st->prev[i] = c;
				changed++;
			}
		}
		if (i % CW_WORDS_PER_PAGE == CW_WORDS_PER_PAGE - 1u) {
			if (page_heals == CW_WORDS_PER_PAGE) {
				st->whole_heal++;
			}
			page_heals = 0;
		}
	}
	if (changed != 0) {
		st->changed_snaps++;
		st->changed_words += changed;
		st->last_change = st->snaps;
	}
}

/* FINL: one more read of every word into prev. A read that differs from the last one is read twice
 * more at once: both the last read, a revert; otherwise final_diff, and the last re-read is kept. */
static void
cw_final(struct cw_state *const st, const struct cw_src *const src)
{
	for (uint64_t i = 0; i < st->nwords; i++) {
		uint64_t const v = src->read(src->ctx, i);

		if (v != st->prev[i]) {
			uint64_t const b = src->read(src->ctx, i);
			uint64_t const c = src->read(src->ctx, i);

			if (b == c && c == st->prev[i]) {
				cw_revert(st, v, c);
			} else {
				st->final_diff++;
				st->prev[i] = c;
			}
		}
	}
}

static uint32_t
le32(const uint8_t *const b)
{
	return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

static uint64_t
le64(const uint8_t *const b)
{
	return (uint64_t)le32(b) | ((uint64_t)le32(b + 4) << 32);
}

/* An IPv4 header at b: version 4, IHL 5-15 inside len, a total length of at least the header, the
 * reserved flag clear, TTL non-zero, protocol ICMP, IGMP, TCP or UDP, and a one's-complement sum
 * of 0xffff over the header (RFC 791, RFC 1071; our reading, HYPOTHESIS). */
static int
cw_is_ipv4(const uint8_t *const b, uint64_t const len)
{
	unsigned const ihl = (unsigned)(b[0] & 0x0Fu) * 4u;
	uint32_t       sum = 0;

	if (len < 20u || (b[0] >> 4) != 4u || ihl < 20u || ihl > len) {
		return 0;
	}
	if ((((unsigned)b[2] << 8) | b[3]) < ihl || (b[6] & 0x80u) != 0 || b[8] == 0) {
		return 0;
	}
	if (b[9] != 1u && b[9] != 2u && b[9] != 6u && b[9] != 17u) {
		return 0;
	}
	for (unsigned k = 0; k < ihl; k += 2u) {
		sum += ((uint32_t)b[k] << 8) | b[k + 1u];
	}
	while ((sum >> 16) != 0) {
		sum = (sum & 0xFFFFu) + (sum >> 16);
	}
	return sum == 0xFFFFu;
}

/* An 802.11 beacon's MAC header at b: frame control 0x80 0x00, the broadcast receiver address after
 * the 2-byte duration, and a transmitter address that is unicast, not zero, and equal to the BSSID
 * (IEEE 802.11 management frame layout; our reading, HYPOTHESIS). No address leaves this function. */
static int
cw_is_beacon(const uint8_t *const b, uint64_t const len)
{
	static const uint8_t bc[6]   = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };
	static const uint8_t zero[6] = { 0 };

	if (len < 24u || b[0] != 0x80u || b[1] != 0x00u) {
		return 0;
	}
	return memcmp(b + 4, bc, 6u) == 0 && (b[10] & 1u) == 0 && memcmp(b + 10, zero, 6u) != 0
	       && memcmp(b + 10, b + 16, 6u) == 0;
}

/* An xHCI event TRB at b, 16 bytes little-endian (parameter, status, control): completion code 1-36,
 * control bits 9:3 clear, and TRB type 32 (transfer: bits 1 and 23:21 clear, endpoint and slot
 * non-zero), 33 (command completion: bits 9:1 clear, a non-zero command TRB pointer with its low
 * 4 bits clear) or 34 (port status change: only the port id set in the parameter, status bits 23:0
 * and control bits 31:16 and 9:1 clear) (xHCI 1.2 §6.4.2; our reading, HYPOTHESIS). */
static int
cw_is_trb_evt(const uint8_t *const b, uint64_t const len)
{
	uint64_t param;
	uint32_t status;
	uint32_t ctl;
	unsigned cc;

	if (len < 16u) {
		return 0;
	}
	param  = le64(b);
	status = le32(b + 8);
	ctl    = le32(b + 12);
	cc     = status >> 24;
	if (cc < 1u || cc > 36u || (ctl & 0x3F8u) != 0) {
		return 0;
	}
	switch ((ctl >> 10) & 0x3Fu) {
	case 32u:
		return (ctl & 0x00E00002u) == 0 && ((ctl >> 16) & 0x1Fu) != 0 && (ctl >> 24) != 0;
	case 33u:
		return (ctl & 0x3FEu) == 0 && param != 0 && (param & 0xFu) == 0;
	case 34u:
		return (param & 0xFFFFFFFF00FFFFFFull) == 0 && (param >> 24) != 0 && (status & 0x00FFFFFFu) == 0
		       && (ctl & 0xFFFF03FEu) == 0;
	default:
		return 0;
	}
}

static void
cw_ascii_end(struct cw_state *const st, uint64_t const run)
{
	if (run >= CW_ASCII_MIN) {
		st->ascii_runs++;
		st->ascii_bytes += run;
	}
}

/* The byte signatures of one bad extent, at every byte offset; each stays inside the extent. */
static void
cw_scan_extent(struct cw_state *const st, const uint8_t *const b, uint64_t const len)
{
	uint64_t run = 0;

	for (uint64_t j = 0; j < len; j++) {
		if (b[j] >= 0x20u && b[j] <= 0x7Eu) {
			run++;
		} else {
			cw_ascii_end(st, run);
			run = 0;
		}
		st->ipv4    += (uint64_t)cw_is_ipv4(b + j, len - j);
		st->beacon  += (uint64_t)cw_is_beacon(b + j, len - j);
		st->trb_evt += (uint64_t)cw_is_trb_evt(b + j, len - j);
	}
	cw_ascii_end(st, run);
}

/* FINL's bad set: the page bitmap, the classes, the stride and the signatures. It needs no mapping.
 * The stride bin is the in-page offset modulo 64 over 8; a page is 4096 bytes, so that is i mod 8. */
static void
cw_summarise(struct cw_state *const st)
{
	uint64_t run = 0;

	for (uint64_t i = 0; i <= st->nwords; i++) {
		if (i < st->nwords && st->prev[i] != splitmix64(st->cbase + i * 8u)) {
			st->final_bad++;
			bit_set(st->bad_final, i / CW_WORDS_PER_PAGE);
			st->cls[cw_classify(st->prev[i], i * 8u, st->base[i], st->cbase)]++;
			st->stride[i % 8u]++;
			run++;
		} else if (run != 0) {
			cw_scan_extent(st, (const uint8_t *)st->prev + (i - run) * 8u, run * 8u);
			run = 0;
		}
	}
}

/* The verdict line's writer field. none: no bad word at BASE and no change at all; static: bad at
 * BASE and no change; ongoing: FINL differed from the last snapshot, or the last change fell in
 * the last quarter of the snapshots; stopped: changes, but none there. */
static const char *
cw_writer(const struct cw_state *const st)
{
	if (st->changed_words == 0 && st->final_diff == 0) {
		return (st->base_bad == 0) ? "none" : "static";
	}
	if (st->final_diff != 0 || st->last_change * 4u > st->snaps * 3u) {
		return "ongoing";
	}
	return "stopped";
}

static const char *
cw_reads(const struct cw_state *const st)
{
	return (st->prog != 0) ? "prog" : (st->osc != 0) ? "osc" : (st->revert != 0) ? "revert" : "stable";
}

/* The content field: every class but other that holds at least a quarter of FINL's bad words, most
 * first, ties in class order; "unclassified" when none does, "none" when there is no bad word. */
static void
cw_content(const struct cw_state *const st, char *const list, size_t const cap)
{
	int    used[K_NCLASS] = { 0 };
	size_t off            = 0;

	if (st->final_bad == 0) {
		(void)snprintf(list, cap, "none");
		return;
	}
	list[0] = '\0';
	for (;;) {
		int best = -1;
		int n;

		for (int k = 0; k < K_OTHER; k++) {
			if (!used[k] && st->cls[k] != 0 && st->cls[k] * 4u >= st->final_bad
			    && (best < 0 || st->cls[k] > st->cls[best])) {
				best = k;
			}
		}
		if (best < 0) {
			break;
		}
		used[best] = 1;
		n = snprintf(list + off, cap - off, "%s%s", (off != 0) ? "," : "", cw_class_name[best]);
		if (n < 0 || (size_t)n >= cap - off) {
			break;
		}
		off += (size_t)n;
	}
	if (off == 0) {
		(void)snprintf(list, cap, "unclassified");
	}
}

enum cw_line { W_BASE, W_TIME, W_REREAD, W_WORDS, W_WORDS2, W_STRIDE, W_BYTES, W_VERDICT, W_NLINE };

static int
cw_format(char *const line, size_t const cap, enum cw_line const which, const char *const name,
          const char *const label, const struct cw_state *const st)
{
	char list[CW_LIST_BUF];
	int  n = -1;

	switch (which) {
	case W_BASE:
		n = snprintf(line, cap, "S1 CANARY %s watch=base label=%s bad=%llu pages=%llu first_off=0x%llx last_off=0x%llx",
		             name, label, CW_U(st->base_bad), CW_U(st->base_pages), CW_U(st->first_off), CW_U(st->last_off));
		break;
	case W_TIME:
		n = snprintf(line, cap, "S1 CANARY %s watch=time label=%s snaps=%llu changed_snaps=%llu changed_words=%llu"
		             " healed=%llu osc=%llu prog=%llu stable=%llu stop=%s", name, label, CW_U(st->snaps),
		             CW_U(st->changed_snaps), CW_U(st->changed_words), CW_U(st->healed), CW_U(st->osc),
		             CW_U(st->prog), CW_U(st->stable), (st->stop == STOP_COUNT) ? "count" : "deadline");
		break;
	case W_REREAD:
		n = snprintf(line, cap, "S1 CANARY %s watch=reread label=%s revert=%llu revert_flip2=%llu whole_heal=%llu",
		             name, label, CW_U(st->revert), CW_U(st->revert_flip2), CW_U(st->whole_heal));
		break;
	case W_WORDS:
		n = snprintf(line, cap, "S1 CANARY %s watch=words label=%s bad=%llu zero=%llu ones=%llu flip2_same=%llu"
		             " flip2_var=%llu flip8=%llu pat_same=%llu pat_other=%llu", name, label, CW_U(st->final_bad),
		             CW_U(st->cls[K_ZERO]), CW_U(st->cls[K_ONES]), CW_U(st->cls[K_FLIP2_SAME]),
		             CW_U(st->cls[K_FLIP2_VAR]), CW_U(st->cls[K_FLIP8]), CW_U(st->cls[K_PAT_SAME]),
		             CW_U(st->cls[K_PAT_OTHER]));
		break;
	case W_WORDS2:
		n = snprintf(line, cap, "S1 CANARY %s watch=words2 label=%s hi_pat=%llu lo_pat=%llu pte=%llu kva=%llu"
		             " ptr_self=%llu ptr_ram=%llu u32page=%llu small32=%llu other=%llu", name, label,
		             CW_U(st->cls[K_HI_PAT]), CW_U(st->cls[K_LO_PAT]), CW_U(st->cls[K_PTE]), CW_U(st->cls[K_KVA]),
		             CW_U(st->cls[K_PTR_SELF]), CW_U(st->cls[K_PTR_RAM]), CW_U(st->cls[K_U32PAGE]),
		             CW_U(st->cls[K_SMALL32]), CW_U(st->cls[K_OTHER]));
		break;
	case W_STRIDE:
		n = snprintf(line, cap, "S1 CANARY %s watch=stride label=%s b0=%llu b1=%llu b2=%llu b3=%llu b4=%llu b5=%llu"
		             " b6=%llu b7=%llu", name, label, CW_U(st->stride[0]), CW_U(st->stride[1]), CW_U(st->stride[2]),
		             CW_U(st->stride[3]), CW_U(st->stride[4]), CW_U(st->stride[5]), CW_U(st->stride[6]),
		             CW_U(st->stride[7]));
		break;
	case W_BYTES:
		n = snprintf(line, cap, "S1 CANARY %s watch=bytes label=%s ascii_runs=%llu ascii_bytes=%llu ipv4=%llu"
		             " beacon=%llu trb_evt=%llu", name, label, CW_U(st->ascii_runs), CW_U(st->ascii_bytes),
		             CW_U(st->ipv4), CW_U(st->beacon), CW_U(st->trb_evt));
		break;
	case W_VERDICT:
		cw_content(st, list, sizeof(list));
		n = snprintf(line, cap, "S1 CANARY %s watch=verdict label=%s writer=%s heal=%s reads=%s content=%s", name,
		             label, cw_writer(st), (st->healed != 0) ? "yes" : "no", cw_reads(st), list);
		break;
	default:
		break;
	}
	return n > 0 && (size_t)n < cap;
}

static int
cw_format_fail(char *const line, size_t const cap, const char *const name, const char *const label,
               const char *const reason, int const err)
{
	int const n = snprintf(line, cap, "S1 CANARY %s watch=fail label=%s reason=%s errno=%d", name, label, reason, err);

	return n > 0 && (size_t)n < cap;
}

static void
put_le(uint8_t *const p, uint64_t v, unsigned const n)
{
	for (unsigned k = 0; k < n; k++) {
		p[k] = (uint8_t)(v & 0xFFu);
		v >>= 8;
	}
}

/* The export file, content-free and little-endian (§15.4.8); its length, or 0 if it does not fit:
 *    0  8  magic "S1J1PBMP"               36  4  interval in ms (-i)
 *    8  4  version, 1                     40  4  snapshots taken
 *   12  4  name, NUL-padded               44  4  snapshots asked (-c)
 *   16  8  label, NUL-padded              48  4  deadline in s (-T)
 *   24  8  the canary's base (§3.3)       52  4  stop: 1 count, 2 deadline
 *   32  4  pages P                        56  8  zero
 * then three bitmaps of ceil(P/8) bytes each, page p in bit (p % 8) of byte p / 8: bad_final,
 * changed_ever, healed_ever; then a 32 B tail of u64 counts: bad at BASE, bad at FINL,
 * changed_words, healed. A 16 MiB canary has P = 4096, so the file is 1,632 B. */
static size_t
cw_export(const struct cw_state *const st, const char *const name, const char *const label, unsigned const ms,
          unsigned const count, unsigned const secs, uint8_t *const out, size_t const cap)
{
	uint64_t const pages = st->nwords / CW_WORDS_PER_PAGE;
	size_t const   bm    = (size_t)((pages + 7u) / 8u);
	size_t const   len   = CW_FILE_HEAD + 3u * bm + CW_FILE_TAIL;
	uint8_t       *p;

	if (pages > CW_PAGES || len > cap || strlen(name) > 4u || strlen(label) > CW_LABEL_MAX) {
		return 0;
	}
	memset(out, 0, len);
	memcpy(out, "S1J1PBMP", 8u);
	put_le(out + 8, CW_FILE_VERSION, 4u);
	memcpy(out + 12, name, strlen(name));
	memcpy(out + 16, label, strlen(label));
	put_le(out + 24, st->cbase, 8u);
	put_le(out + 32, pages, 4u);
	put_le(out + 36, ms, 4u);
	put_le(out + 40, st->snaps, 4u);
	put_le(out + 44, count, 4u);
	put_le(out + 48, secs, 4u);
	put_le(out + 52, (uint64_t)st->stop, 4u);
	p = out + CW_FILE_HEAD;
	memcpy(p, st->bad_final, bm);
	memcpy(p + bm, st->changed_ever, bm);
	memcpy(p + 2u * bm, st->healed_ever, bm);
	p += 3u * bm;
	put_le(p, st->base_bad, 8u);
	put_le(p + 8, st->final_bad, 8u);
	put_le(p + 16, st->changed_words, 8u);
	put_le(p + 24, st->healed, 8u);
	return len;
}

/* One write of the file: 0, or 1 when it cannot be opened, 2 when the write or close fails. */
static int
cw_dump(const char *const path, const uint8_t *const buf, size_t const len, int *const err)
{
	int const fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	ssize_t   w;

	if (fd < 0) {
		*err = errno;
		return 1;
	}
	do {
		w = write(fd, buf, len);
	} while (w < 0 && errno == EINTR);
	if (w != (ssize_t)len) {
		*err = (w < 0) ? errno : EIO;
		(void)close(fd);
		return 2;
	}
	if (close(fd) != 0) {
		*err = errno;
		return 2;
	}
	return 0;
}

static int
cmd_watch(const struct cw_args *const a)
{
	static struct as_view      v[AS_MAX];
	static struct cw_state     st;
	static uint8_t             file[CW_FILE_MAX];
	const struct canary *const c = lookup(a->name);
	struct cw_src              src;
	char                       line[LINE_BUF];
	uint64_t                   deadline;
	size_t                     len;
	enum refusal               k;
	int                        n;
	int                        err = 0;
	int                        dumped;
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
	cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
	if (cps == 0) {
		fprintf(stderr, "memcanary-w: qtime reports no cycles_per_sec\n");
		return 1;
	}

	memset(&st, 0, sizeof(st));
	st.cbase  = c->base;
	st.nwords = S1_CANARY_SIZE / 8u;
	st.base   = malloc((size_t)S1_CANARY_SIZE);
	st.prev   = malloc((size_t)S1_CANARY_SIZE);
	if (st.base == NULL || st.prev == NULL) {
		err = errno;
		free(st.base);
		free(st.prev);
		(void)cw_format_fail(line, sizeof(line), c->name, a->label, "nomem", err);
		say("%s\n", line);
		return 1;
	}
	p = mmap_device_memory(NULL, (size_t)S1_CANARY_SIZE, PROT_READ, 0, c->base);
	if (p == MAP_FAILED) {
		err = errno;
		free(st.base);
		free(st.prev);
		(void)format_canary(line, sizeof(line), c->name, V_MAPFAIL, 0, 0, err);
		say("%s\n", line);
		return 1;
	}

	/* Nothing is printed from here to the lines below (§2 rule 7). */
	src.read = cw_read_dev;
	src.ctx  = p;
	cw_base(&st, &src);
	deadline = ClockCycles() + (uint64_t)a->secs * cps;
	for (;;) {
		if (st.snaps >= a->count) {
			st.stop = STOP_COUNT;
			break;
		}
		if (a->ms != 0) {
			nap_toward(deadline, a->ms);
		}
		if (ClockCycles() >= deadline) {
			st.stop = STOP_DEADLINE;
			break;
		}
		cw_snap(&st, &src);
	}
	cw_final(&st, &src);
	(void)munmap_device_memory(p, (size_t)S1_CANARY_SIZE);
	cw_summarise(&st);
	len    = cw_export(&st, c->name, a->label, a->ms, a->count, a->secs, file, sizeof(file));
	dumped = (len == 0) ? 2 : cw_dump(a->dump, file, len, &err);
	free(st.base);
	free(st.prev);

	for (int w = W_BASE; w < W_NLINE; w++) {
		(void)cw_format(line, sizeof(line), (enum cw_line)w, c->name, a->label, &st);
		say("%s\n", line);
	}
	if (dumped != 0) {
		(void)cw_format_fail(line, sizeof(line), c->name, a->label, (dumped == 1) ? "dump-open" : "dump-write", err);
		say("%s\n", line);
		return 1;
	}
	return 0;
}

#endif /* MEMCANARY_WATCH: watch engine */

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

#ifdef MEMCANARY_WATCH
/* ---------------------------------------------------------------- watch self-test */

#define CW_ST_WORDS         (2u * CW_WORDS_PER_PAGE)
#define CW_ST_OVR           8u

/* A scripted source: the buffer, except that a read of an armed word returns its three values first. */
struct cw_script {
	uint64_t *w;
	unsigned  nov;
	struct {
		uint64_t idx;
		uint64_t seq[3];
		unsigned pos;
	} ovr[CW_ST_OVR];
};

static uint64_t
cw_read_script(void *const ctx, uint64_t const i)
{
	struct cw_script *const s = ctx;

	for (unsigned k = 0; k < s->nov; k++) {
		if (s->ovr[k].idx == i && s->ovr[k].pos < 3u) {
			return s->ovr[k].seq[s->ovr[k].pos++];
		}
	}
	return s->w[i];
}

static void
cw_arm(struct cw_script *const s, uint64_t const idx, uint64_t const a, uint64_t const b, uint64_t const c)
{
	if (s->nov < CW_ST_OVR) {
		s->ovr[s->nov].idx    = idx;
		s->ovr[s->nov].seq[0] = a;
		s->ovr[s->nov].seq[1] = b;
		s->ovr[s->nov].seq[2] = c;
		s->ovr[s->nov].pos    = 0;
		s->nov++;
	}
}

static void
cw_trb(uint8_t *const t, uint64_t const param, uint32_t const status, uint32_t const ctl)
{
	put_le(t, param, 8u);
	put_le(t + 8, status, 4u);
	put_le(t + 12, ctl, 4u);
}

/* cw_parse on a good command line, with flag's value replaced (or the pair dropped when value is
 * NULL), and x1 and x2 appended when given. */
static int
cw_try(const char *const flag, const char *const value, const char *const x1, const char *const x2,
       struct cw_args *const a)
{
	char *argv[16] = { "memcanary-w", "watch", "-n", "c2", "-l", "b", "-i", "1000", "-c", "180", "-T", "190",
	                   "-d", "/dev/shmem/j1b.bin" };
	int   argc     = 14;

	for (int i = 2; i < argc; i += 2) {
		if (flag != NULL && strcmp(argv[i], flag) == 0) {
			if (value == NULL) {
				argv[i]     = argv[argc - 2];
				argv[i + 1] = argv[argc - 1];
				argc -= 2;
			} else {
				argv[i + 1] = (char *)value;
			}
			break;
		}
	}
	if (x1 != NULL) {
		argv[argc++] = (char *)x1;
	}
	if (x2 != NULL) {
		argv[argc++] = (char *)x2;
	}
	return cw_parse(argc, argv, a);
}

/* §15.5 B8.5: the inverse, one crafted value per class with precedence, the signatures at byte
 * offsets that are not word-aligned (documentation addresses only: RFC 5737 IPv4, RFC 7042 MAC),
 * the engine's changes, heals, osc, prog and stable on a scripted buffer, the stride histogram,
 * the export round trip, every line's text and its length at maximum field widths, and the
 * refusals. It maps no physical memory and reads no system page. */
static void
cw_selftest(void)
{
	static uint64_t             w[CW_ST_WORDS];
	static uint64_t             b[CW_ST_WORDS];
	static uint64_t             q[CW_ST_WORDS];
	static struct cw_state      st;
	static struct cw_state      mx;
	static struct cw_script     sc;
	static uint8_t              file[CW_FILE_MAX];
	static const unsigned       shifts[] = { 1u, 27u, 30u, 31u, 32u, 63u };
	static const uint8_t        ipv4[20] = { 0x45, 0x00, 0x00, 0x54, 0x00, 0x00, 0x40, 0x00, 0x40, 0x01, 0x4E, 0x72,
	                                         0xC0, 0x00, 0x02, 0x01, 0xC6, 0x33, 0x64, 0x02 };
	static const uint8_t        beacon[24] = { 0x80, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
	                                           0x00, 0x00, 0x5E, 0x00, 0x53, 0x01, 0x00, 0x00, 0x5E, 0x00, 0x53, 0x01,
	                                           0x10, 0x00 };
	static const char           ascii20[] = "S1-J1-SELFTEST-ASCII";
	static const char           ascii15[] = "SHORT-RUN-15-CH";
	static const char *const    want[W_NLINE] = {
		"S1 CANARY c2 watch=base label=t1 bad=2 pages=2 first_off=0x18 last_off=0x12c0",
		"S1 CANARY c2 watch=time label=t1 snaps=4 changed_snaps=2 changed_words=7 healed=2 osc=1 prog=3 stable=3 stop=count",
		"S1 CANARY c2 watch=reread label=t1 revert=4 revert_flip2=2 whole_heal=0",
		"S1 CANARY c2 watch=words label=t1 bad=5 zero=1 ones=1 flip2_same=1 flip2_var=1 flip8=0 pat_same=0 pat_other=0",
		"S1 CANARY c2 watch=words2 label=t1 hi_pat=0 lo_pat=0 pte=0 kva=0 ptr_self=0 ptr_ram=0 u32page=0 small32=1 other=0",
		"S1 CANARY c2 watch=stride label=t1 b0=2 b1=0 b2=2 b3=0 b4=0 b5=0 b6=1 b7=0",
		"S1 CANARY c2 watch=bytes label=t1 ascii_runs=0 ascii_bytes=0 ipv4=0 beacon=0 trb_evt=0",
		"S1 CANARY c2 watch=verdict label=t1 writer=stopped heal=yes reads=prog content=unclassified",
	};
	static const char *const    bad_args[][2] = {
		{ "-i", "60001" }, { "-i", "-1" }, { "-i", "0x10" }, { "-i", "1e3" }, { "-i", "" }, { "-i", " 1" },
		{ "-c", "0" }, { "-c", "100001" }, { "-T", "0" }, { "-T", "3601" }, { "-T", "0xe10" },
		{ "-l", "" }, { "-l", "abcdefghi" }, { "-l", "B" }, { "-l", "a-b" }, { "-l", "a b" }, { "-l", ".." },
		{ "-d", "/dev/shmem/j2b.bin" }, { "-d", "/tmp/j1b.bin" }, { "-d", "/dev/shmem/j1" },
		{ "-d", "/dev/shmem/j1../x" }, { "-d", "/dev/shmem/j1a/b" }, { "-d", "/dev/shmem/j1a..b" },
		{ "-d", "/dev/shmem/J1b.bin" }, { "-d", "/dev/shmem/j1abcdefghijklmnopqrstuvwxyz0123456" },
		{ "-d", "/dev/shmem/j1hold.go" }, { "-d", "/dev/shmem/j1hold.out" }, { "-d", "/dev/shmem/j1hold.out.fill" },
		{ "-d", "/dev/shmem/j1c.bin" }, { "-d", "/dev/shmem/j1b.bin.x" }, { "-d", "/dev/shmem/j1b.go" },
		{ "-d", "/dev/shmem/j1b" }, { "-d", "/dev/shmem/j1.bin" }, { "-d", "/dev/shmem/j1b.bin/" },
		{ "-n", NULL }, { "-l", NULL }, { "-i", NULL }, { "-c", NULL }, { "-T", NULL }, { "-d", NULL },
	};
	static const char *const    addresses[] = { "0x100000000", "0x272770000", "272770000", "4294967296", "0xbd000000" };
	unsigned const              ran0  = st_ran;
	unsigned const              fail0 = st_fail;
	uint64_t const              p     = splitmix64(S1_CANARY_C2_BASE + 0x40u);
	struct cw_vec {
		uint64_t      v;
		uint64_t      b;
		enum cw_class want;
	} const                     vec[] = {
		{ 0, p, K_ZERO }, { ~0ull, p, K_ONES }, { p ^ 5u, p ^ 5u, K_FLIP2_SAME }, { p ^ 1u, p ^ 1u, K_FLIP2_SAME },
		{ p ^ 5u, p, K_FLIP2_VAR }, { p ^ 4u, p ^ 1u, K_FLIP2_VAR }, { p ^ 7u, p, K_FLIP8 }, { p ^ 0xFFu, p, K_FLIP8 },
		{ p ^ 0x1FFu, p, K_HI_PAT }, { p ^ (0x1FFull << 40), p, K_LO_PAT },
		{ splitmix64(S1_CANARY_C2_BASE + 0x48u), p, K_PAT_SAME }, { splitmix64(S1_CANARY_C2_BASE), p, K_PAT_SAME },
		{ splitmix64(S1_CANARY_C3_BASE + 0x10u), p, K_PAT_OTHER },
		{ splitmix64(S1_CANARY_C1_BASE + S1_CANARY_SIZE - 8u), p, K_PAT_OTHER },
		{ splitmix64(S1_CANARY_C2_BASE + 0x44u), p, K_OTHER }, { splitmix64(S1_CANARY_C2_BASE + S1_CANARY_SIZE), p, K_OTHER },
		{ 0x100001003ull, p, K_PTE }, { 0x80000003ull, p, K_PTE }, { 0xFFFFFFFFull, p, K_SMALL32 },
		{ 0xBFFFFFFFull, p, K_PTE },
		{ 0x300001003ull, p, K_OTHER }, { 0x0001000100001003ull, p, K_OTHER }, { 0x100001001ull, p, K_PTR_SELF },
		{ 0xFFFF800012345678ull, p, K_KVA }, { 0xFFFF000000000003ull, p, K_KVA },
		{ S1_CANARY_C2_BASE + 0x1234u, p, K_PTR_SELF }, { 0x200000010ull, p, K_PTR_RAM }, { 0x80000000ull, p, K_PTR_RAM },
		{ 0x27FFFFFF8ull, p, K_PTR_RAM }, { 0xFFFFFFFEull, p, K_PTR_RAM }, { 0x280000000ull, p, K_OTHER },
		{ 0x40000000ull, p, K_U32PAGE }, { 0x1000u, p, K_U32PAGE }, { 0x1234u, p, K_SMALL32 },
		{ 0x7FFFFFFFull, p, K_SMALL32 }, { 0x123456789ABCDEF0ull, p, K_OTHER },
	};
	struct cw_src               src;
	struct cw_args              a;
	uint8_t                     t[24];
	uint8_t                    *e;
	char                        line[LINE_BUF];
	char                        list[CW_LIST_BUF];
	char                        what[80];
	size_t                      len;
	int                         ok;

	/* The inverse. */
	check(inv64(0x94D049BB133111EBull) * 0x94D049BB133111EBull == 1u
	      && inv64(0xBF58476D1CE4E5B9ull) * 0xBF58476D1CE4E5B9ull == 1u && inv64(3u) * 3u == 1u
	      && inv64(~0ull) * ~0ull == 1u, "watch: inv64 of the two multipliers, 3 and -1");
	ok = 1;
	for (size_t i = 0; i < sizeof(shifts) / sizeof(shifts[0]); i++) {
		uint64_t const z = 0x0123456789ABCDEFull;

		ok &= (unshift(z ^ (z >> shifts[i]), shifts[i]) == z);
	}
	check(ok, "watch: unshift undoes z ^ (z >> s)");
	ok  = (unmix64(splitmix64(0)) == 0) && (unmix64(splitmix64(S1_CANARY_C1_BASE)) == S1_CANARY_C1_BASE);
	ok &= (unmix64(splitmix64(S1_CANARY_C2_BASE + 8u)) == S1_CANARY_C2_BASE + 8u);
	ok &= (unmix64(splitmix64(S1_CANARY_C3_BASE + S1_CANARY_SIZE - 8u)) == S1_CANARY_C3_BASE + S1_CANARY_SIZE - 8u);
	ok &= (unmix64(splitmix64(~0ull)) == ~0ull) && (splitmix64(unmix64(0x0123456789ABCDEFull)) == 0x0123456789ABCDEFull);
	check(ok, "watch: unmix64 and splitmix64 round trips");

	/* One crafted value per class, at c2 + 0x40, with the precedence cases. */
	for (size_t i = 0; i < sizeof(vec) / sizeof(vec[0]); i++) {
		(void)snprintf(what, sizeof(what), "watch: class vector %u is %s", (unsigned)i, cw_class_name[vec[i].want]);
		check(cw_classify(vec[i].v, 0x40u, vec[i].b, S1_CANARY_C2_BASE) == vec[i].want, what);
	}
	check(cw_classify(0xBD000010ull, 0x40u, splitmix64(S1_CANARY_C1_BASE + 0x40u), S1_CANARY_C1_BASE) == K_PTR_SELF,
	      "watch: ptr_self in c1 comes before ptr_ram");

	/* The signatures, positive and negative. */
	check(cw_is_ipv4(ipv4, 20u) == 1 && cw_is_ipv4(ipv4, 19u) == 0, "watch: an ipv4 header, and not past len");
	memcpy(t, ipv4, 20u);
	t[15] ^= 1u;
	check(cw_is_ipv4(t, 20u) == 0, "watch: an ipv4 header with a bad checksum is not one");
	memcpy(t, ipv4, 20u);
	t[0] = 0x65u;
	check(cw_is_ipv4(t, 20u) == 0, "watch: version 6 is not ipv4");
	check(cw_is_beacon(beacon, 24u) == 1 && cw_is_beacon(beacon, 23u) == 0, "watch: a beacon, and not past len");
	memcpy(t, beacon, 24u);
	t[21] = 0x02u;
	check(cw_is_beacon(t, 24u) == 0, "watch: a transmitter other than the BSSID is not a beacon");
	memcpy(t, beacon, 24u);
	t[0] = 0x40u;
	check(cw_is_beacon(t, 24u) == 0, "watch: a probe request is not a beacon");
	memcpy(t, beacon, 24u);
	t[10] = 0x01u;
	t[16] = 0x01u;
	check(cw_is_beacon(t, 24u) == 0, "watch: a group transmitter address is not a beacon");
	cw_trb(t, 0x03000000u, 0x01000000u, 0x00008801u);
	check(cw_is_trb_evt(t, 16u) == 1 && cw_is_trb_evt(t, 15u) == 0, "watch: a port status change TRB, and not past len");
	cw_trb(t, 0x12345670u, 0x01000400u, 0x01028001u);
	check(cw_is_trb_evt(t, 16u) == 1, "watch: a transfer event TRB");
	cw_trb(t, 0x12345670u, 0x01000000u, 0x00008401u);
	check(cw_is_trb_evt(t, 16u) == 1, "watch: a command completion event TRB");
	cw_trb(t, 0x03000000u, 0x00000000u, 0x00008801u);
	check(cw_is_trb_evt(t, 16u) == 0, "watch: completion code 0 is not an event TRB");
	cw_trb(t, 0x03000000u, 0x01000000u, 0x00008C01u);
	check(cw_is_trb_evt(t, 16u) == 0, "watch: TRB type 35 is not counted");
	cw_trb(t, 0x03000001u, 0x01000000u, 0x00008801u);
	check(cw_is_trb_evt(t, 16u) == 0, "watch: a port status change with a reserved bit is not one");

	/* The engine on a scripted two-page buffer: BASE, four snapshots, FINL. */
	memset(&st, 0, sizeof(st));
	memset(&sc, 0, sizeof(sc));
	st.cbase  = S1_CANARY_C2_BASE;
	st.nwords = CW_ST_WORDS;
	st.base   = b;
	st.prev   = q;
	for (uint64_t i = 0; i < CW_ST_WORDS; i++) {
		w[i] = splitmix64(S1_CANARY_C2_BASE + i * 8u);
	}
	w[3] ^= 0xF0F0u;
	w[600] ^= 5u;
	sc.w     = w;
	src.read = cw_read_script;
	src.ctx  = &sc;
	/* word 5's first BASE read does not hold: its re-reads agree on the pattern, 2 bits away */
	cw_arm(&sc, 5u, splitmix64(S1_CANARY_C2_BASE + 40u) ^ 3u, splitmix64(S1_CANARY_C2_BASE + 40u),
	       splitmix64(S1_CANARY_C2_BASE + 40u));
	cw_base(&st, &src);
	check(st.base_bad == 2u && st.base_pages == 2u && st.first_off == 0x18u && st.last_off == 0x12C0u,
	      "watch: BASE counts two bad words on two pages");
	check(st.revert == 1u && st.revert_flip2 == 1u && st.base[5] == splitmix64(S1_CANARY_C2_BASE + 40u),
	      "watch: a BASE read that its re-reads do not repeat is a revert, not a bad word");
	cw_snap(&st, &src);
	check(st.snaps == 1u && st.changed_words == 0 && st.changed_snaps == 0 && st.last_change == 0 && st.revert == 1u,
	      "watch: an unchanged snapshot counts nothing");
	w[10] = 0;
	cw_arm(&sc, 20u, 0x1234u, splitmix64(S1_CANARY_C2_BASE + 160u), 0x1234u);
	cw_arm(&sc, 30u, 0x55u, ~0ull, ~0ull);
	w[30] = ~0ull;
	cw_arm(&sc, 40u, 0x66u, 0x77u, splitmix64(S1_CANARY_C2_BASE + 320u) ^ 3u);
	w[40] = splitmix64(S1_CANARY_C2_BASE + 320u) ^ 3u;
	cw_arm(&sc, 50u, 0x88u, 0x88u, 0x1234u);
	w[50] = 0x1234u;
	/* two misreads of good words, on page 0 and on page 1: reverts, never changes */
	cw_arm(&sc, 60u, splitmix64(S1_CANARY_C2_BASE + 480u) ^ 1u, splitmix64(S1_CANARY_C2_BASE + 480u),
	       splitmix64(S1_CANARY_C2_BASE + 480u));
	cw_arm(&sc, 700u, splitmix64(S1_CANARY_C2_BASE + 5600u) ^ 0xFF00u, splitmix64(S1_CANARY_C2_BASE + 5600u),
	       splitmix64(S1_CANARY_C2_BASE + 5600u));
	cw_snap(&st, &src);
	check(st.changed_words == 5u && st.stable == 1u && st.osc == 1u && st.prog == 3u && st.healed == 0
	      && st.last_change == 2u, "watch: stable A-A-A, osc A-B-A, and prog A-B-B, A-B-C and A-A-C");
	check(st.revert == 3u && st.revert_flip2 == 2u && st.changed_ever[0] == 0x01u && st.healed == 0,
	      "watch: a read whose re-reads return to the last read is a revert: no change, heal or page bit");
	w[3] = splitmix64(S1_CANARY_C2_BASE + 24u);
	cw_snap(&st, &src);
	check(st.changed_words == 7u && st.stable == 3u && st.healed == 2u && st.changed_snaps == 2u && st.last_change == 3u,
	      "watch: a bad word and an oscillating word heal");
	cw_snap(&st, &src);
	/* word 90's FINL read does not hold either: a revert, not a final difference */
	cw_arm(&sc, 90u, ~splitmix64(S1_CANARY_C2_BASE + 720u), splitmix64(S1_CANARY_C2_BASE + 720u),
	       splitmix64(S1_CANARY_C2_BASE + 720u));
	cw_final(&st, &src);
	st.stop = STOP_COUNT;
	check(st.snaps == 4u && st.final_diff == 0 && st.revert == 4u && st.revert_flip2 == 2u,
	      "watch: FINL equals the last snapshot, its one misread a revert");
	cw_summarise(&st);
	check(st.final_bad == 5u && st.cls[K_ZERO] == 1u && st.cls[K_ONES] == 1u && st.cls[K_FLIP2_VAR] == 1u
	      && st.cls[K_SMALL32] == 1u && st.cls[K_FLIP2_SAME] == 1u, "watch: FINL's five bad words by class");
	check(st.stride[0] == 2u && st.stride[2] == 2u && st.stride[6] == 1u
	      && st.stride[1] + st.stride[3] + st.stride[4] + st.stride[5] + st.stride[7] == 0,
	      "watch: the stride histogram by in-page offset modulo 64");
	check(st.bad_final[0] == 0x03u && st.changed_ever[0] == 0x01u && st.healed_ever[0] == 0x01u, "watch: the page bitmaps");
	check(st.ascii_runs + st.ascii_bytes + st.ipv4 + st.beacon + st.trb_evt == 0, "watch: no signature in single words");
	for (int k = W_BASE; k < W_NLINE; k++) {
		(void)snprintf(what, sizeof(what), "watch: line %d text", k);
		check(line_is(line, cw_format(line, sizeof(line), (enum cw_line)k, "c2", "t1", &st), want[k]), what);
	}
	check(line_is(line, cw_format_fail(line, sizeof(line), "c2", "t1", "dump-open", 2),
	              "S1 CANARY c2 watch=fail label=t1 reason=dump-open errno=2"), "watch: line fail text");

	/* The export round trip. */
	len = cw_export(&st, "c2", "t1", 1000u, 180u, 190u, file, sizeof(file));
	check(len == 99u && memcmp(file, "S1J1PBMP", 8u) == 0 && le32(file + 8) == 1u && memcmp(file + 12, "c2\0\0", 4u) == 0
	      && memcmp(file + 16, "t1\0\0\0\0\0\0", 8u) == 0 && le64(file + 24) == S1_CANARY_C2_BASE && le32(file + 32) == 2u
	      && le32(file + 36) == 1000u && le32(file + 40) == 4u && le32(file + 44) == 180u && le32(file + 48) == 190u
	      && le32(file + 52) == 1u && le64(file + 56) == 0, "watch: export header round trip");
	check(file[64] == 0x03u && file[65] == 0x01u && file[66] == 0x01u && le64(file + 67) == 2u && le64(file + 75) == 5u
	      && le64(file + 83) == 7u && le64(file + 91) == 2u, "watch: export bitmaps and tail round trip");
	memset(&mx, 0, sizeof(mx));
	mx.cbase  = S1_CANARY_C3_BASE;
	mx.nwords = S1_CANARY_SIZE / 8u;
	mx.stop   = STOP_DEADLINE;
	bit_set(mx.bad_final, CW_PAGES - 1u);
	bit_set(mx.healed_ever, 9u);
	len = cw_export(&mx, "c3", "abcdefgh", 0u, 100000u, 3600u, file, sizeof(file));
	check(len == 1632u && len == CW_FILE_MAX && le32(file + 32) == 4096u && le32(file + 52) == 2u && file[64 + 511] == 0x80u
	      && file[576] == 0 && file[1088 + 1] == 0x02u && memcmp(file + 16, "abcdefgh", 8u) == 0,
	      "watch: a 16 MiB canary's export is 1,632 B with each bit in place");
	check(cw_export(&mx, "c3", "abcdefgh", 0u, 1u, 1u, file, 1631u) == 0, "watch: an export that does not fit is refused");

	/* The byte signatures inside one 16-word bad extent, at byte offsets 3, 29, 57 and 77. */
	memset(&st, 0, sizeof(st));
	memset(&sc, 0, sizeof(sc));
	st.cbase  = S1_CANARY_C2_BASE;
	st.nwords = CW_ST_WORDS;
	st.base   = b;
	st.prev   = q;
	sc.w      = w;
	for (uint64_t i = 0; i < CW_ST_WORDS; i++) {
		w[i] = splitmix64(S1_CANARY_C2_BASE + i * 8u);
	}
	e = (uint8_t *)w + 100u * 8u;
	memset(e, 0, 128u);
	memcpy(e + 3, ipv4, 20u);
	memcpy(e + 29, beacon, 24u);
	cw_trb(e + 57, 0x03000000u, 0x01000000u, 0x00008801u);
	memcpy(e + 77, ascii20, 20u);
	memcpy(e + 99, ascii15, 15u);
	cw_base(&st, &src);
	cw_final(&st, &src);
	cw_summarise(&st);
	check(st.base_bad == 16u && st.base_pages == 1u && st.first_off == 0x320u && st.last_off == 0x398u && st.final_bad == 16u,
	      "watch: a 16-word bad extent");
	check(st.ascii_runs == 1u && st.ascii_bytes == 20u && st.ipv4 == 1u && st.beacon == 1u && st.trb_evt == 1u,
	      "watch: signatures at non-aligned byte offsets; a 15-byte printable run is not counted");
	ok = 1;
	for (size_t k = 0; k < 8u; k++) {
		ok &= (st.stride[k] == 2u);
	}
	check(ok, "watch: 16 consecutive bad words put two in each stride bin");

	/* whole_heal: page 1 zero at BASE, healed in halves over two snapshots (no whole heal), zeroed
	 * again, then healed in one snapshot (one whole heal). */
	memset(&st, 0, sizeof(st));
	memset(&sc, 0, sizeof(sc));
	st.cbase  = S1_CANARY_C2_BASE;
	st.nwords = CW_ST_WORDS;
	st.base   = b;
	st.prev   = q;
	sc.w      = w;
	for (uint64_t i = 0; i < CW_ST_WORDS; i++) {
		w[i] = (i < CW_WORDS_PER_PAGE) ? splitmix64(S1_CANARY_C2_BASE + i * 8u) : 0;
	}
	cw_base(&st, &src);
	for (uint64_t i = CW_WORDS_PER_PAGE; i < CW_WORDS_PER_PAGE + CW_WORDS_PER_PAGE / 2u; i++) {
		w[i] = splitmix64(S1_CANARY_C2_BASE + i * 8u);
	}
	cw_snap(&st, &src);
	for (uint64_t i = CW_WORDS_PER_PAGE + CW_WORDS_PER_PAGE / 2u; i < CW_ST_WORDS; i++) {
		w[i] = splitmix64(S1_CANARY_C2_BASE + i * 8u);
	}
	cw_snap(&st, &src);
	check(st.base_bad == CW_WORDS_PER_PAGE && st.healed == CW_WORDS_PER_PAGE && st.whole_heal == 0,
	      "watch: a page healed over two snapshots is not a whole heal");
	memset(w + CW_WORDS_PER_PAGE, 0, CW_WORDS_PER_PAGE * sizeof(w[0]));
	cw_snap(&st, &src);
	for (uint64_t i = CW_WORDS_PER_PAGE; i < CW_ST_WORDS; i++) {
		w[i] = splitmix64(S1_CANARY_C2_BASE + i * 8u);
	}
	cw_snap(&st, &src);
	check(st.healed == 2u * CW_WORDS_PER_PAGE && st.whole_heal == 1u && st.revert == 0 && st.changed_snaps == 4u,
	      "watch: a page whose every word healed in one snapshot is one whole heal");

	/* The verdict fields. */
	memset(&mx, 0, sizeof(mx));
	ok = (strcmp(cw_writer(&mx), "none") == 0);
	mx.base_bad = 3u;
	ok &= (strcmp(cw_writer(&mx), "static") == 0);
	mx.changed_words = 1u;
	mx.snaps         = 4u;
	mx.last_change   = 3u;
	ok &= (strcmp(cw_writer(&mx), "stopped") == 0);
	mx.last_change = 4u;
	ok &= (strcmp(cw_writer(&mx), "ongoing") == 0);
	mx.snaps       = 100u;
	mx.last_change = 75u;
	ok &= (strcmp(cw_writer(&mx), "stopped") == 0);
	mx.last_change = 76u;
	ok &= (strcmp(cw_writer(&mx), "ongoing") == 0);
	mx.changed_words = 0;
	mx.base_bad      = 0;
	mx.final_diff    = 1u;
	ok &= (strcmp(cw_writer(&mx), "ongoing") == 0);
	check(ok, "watch: writer none, static, stopped and ongoing, at the last-quarter boundary and after FINL");
	memset(&mx, 0, sizeof(mx));
	ok = (strcmp(cw_reads(&mx), "stable") == 0);
	mx.revert = 1u;
	ok &= (strcmp(cw_reads(&mx), "revert") == 0);
	mx.osc = 1u;
	ok &= (strcmp(cw_reads(&mx), "osc") == 0);
	mx.prog = 1u;
	ok &= (strcmp(cw_reads(&mx), "prog") == 0);
	check(ok, "watch: reads stable, revert, osc over revert, and prog over osc");
	memset(&mx, 0, sizeof(mx));
	cw_content(&mx, list, sizeof(list));
	ok = (strcmp(list, "none") == 0);
	mx.final_bad          = 12u;
	mx.cls[K_SMALL32]     = 6u;
	mx.cls[K_HI_PAT]      = 3u;
	mx.cls[K_OTHER]       = 3u;
	cw_content(&mx, list, sizeof(list));
	ok &= (strcmp(list, "small32,hi_pat") == 0);
	mx.cls[K_SMALL32] = 3u;
	mx.cls[K_OTHER]   = 6u;
	cw_content(&mx, list, sizeof(list));
	ok &= (strcmp(list, "hi_pat,small32") == 0);
	memset(mx.cls, 0, sizeof(mx.cls));
	mx.cls[K_OTHER] = 12u;
	cw_content(&mx, list, sizeof(list));
	ok &= (strcmp(list, "unclassified") == 0);
	memset(mx.cls, 0, sizeof(mx.cls));
	mx.final_bad         = 10u;
	mx.cls[K_FLIP2_SAME] = 2u;
	mx.cls[K_FLIP2_VAR]  = 2u;
	mx.cls[K_PTE]        = 2u;
	mx.cls[K_KVA]        = 2u;
	mx.cls[K_OTHER]      = 2u;
	cw_content(&mx, list, sizeof(list));
	ok &= (strcmp(list, "unclassified") == 0);
	check(ok, "watch: content none, a quarter or more most first, ties in class order, and unclassified");

	/* Every line at maximum field widths: all words bad, every snapshot changing every word. */
	memset(&mx, 0, sizeof(mx));
	mx.base_bad      = S1_CANARY_SIZE / 8u;
	mx.final_bad     = S1_CANARY_SIZE / 8u;
	mx.base_pages    = CW_PAGES;
	mx.first_off     = S1_CANARY_SIZE - 8u;
	mx.last_off      = S1_CANARY_SIZE - 8u;
	mx.snaps         = CW_COUNT_MAX;
	mx.changed_snaps = CW_COUNT_MAX;
	mx.last_change   = CW_COUNT_MAX;
	mx.changed_words = (uint64_t)CW_COUNT_MAX * (S1_CANARY_SIZE / 8u);
	mx.healed        = mx.changed_words;
	mx.osc           = mx.changed_words;
	mx.prog          = mx.changed_words;
	mx.stable        = mx.changed_words;
	mx.revert        = mx.changed_words + 2u * (S1_CANARY_SIZE / 8u);
	mx.revert_flip2  = mx.revert;
	mx.whole_heal    = (uint64_t)CW_COUNT_MAX * CW_PAGES;
	mx.stop          = STOP_DEADLINE;
	for (size_t k = 0; k < K_NCLASS; k++) {
		mx.cls[k] = S1_CANARY_SIZE / 8u;
	}
	for (size_t k = 0; k < 8u; k++) {
		mx.stride[k] = S1_CANARY_SIZE / 8u;
	}
	mx.ascii_runs  = S1_CANARY_SIZE;
	mx.ascii_bytes = S1_CANARY_SIZE;
	mx.ipv4        = S1_CANARY_SIZE;
	mx.beacon      = S1_CANARY_SIZE;
	mx.trb_evt     = S1_CANARY_SIZE;
	ok = 1;
	for (int k = W_BASE; k < W_NLINE; k++) {
		if (k == W_VERDICT) {
			mx.osc  = 0;         /* reads=stable is the longest form */
			mx.prog = 0;
		}
		ok &= cw_format(line, sizeof(line), (enum cw_line)k, "c1", "abcdefgh", &mx) && strlen(line) + 1u <= 255u;
	}
	ok &= cw_format_fail(line, sizeof(line), "c1", "abcdefgh", "dump-write", -2147483647 - 1) && strlen(line) + 1u <= 255u;
	check(ok, "watch: every line with its newline within 255 bytes at maximum field widths");

	/* The refusals: ranges, labels, file names, missing and repeated flags, and addresses as names. */
	ok = (cw_try(NULL, NULL, NULL, NULL, &a) == 0) && strcmp(a.name, "c2") == 0 && strcmp(a.label, "b") == 0
	     && a.ms == 1000u && a.count == 180u && a.secs == 190u && strcmp(a.dump, "/dev/shmem/j1b.bin") == 0;
	ok &= (cw_try("-i", "0", NULL, NULL, &a) == 0) && (cw_try("-i", "60000", NULL, NULL, &a) == 0);
	ok &= (cw_try("-c", "100000", NULL, NULL, &a) == 0) && (cw_try("-T", "3600", NULL, NULL, &a) == 0);
	{
		char *argv[] = { "memcanary-w", "watch", "-n", "c2", "-l", "abcdefgh", "-i", "1000", "-c", "180", "-T", "190",
		                 "-d", "/dev/shmem/j1abcdefgh.bin" };

		ok &= (cw_parse(14, argv, &a) == 0) && strcmp(a.dump, "/dev/shmem/j1abcdefgh.bin") == 0;
	}
	check(ok, "watch: good command lines and their boundaries parse, each file named by its own label");
	ok = 1;
	for (size_t i = 0; i < sizeof(bad_args) / sizeof(bad_args[0]); i++) {
		ok &= (cw_try(bad_args[i][0], bad_args[i][1], NULL, NULL, &a) == 2);
	}
	ok &= (cw_try("-l", "abcdefgh", NULL, NULL, &a) == 2);   /* a good label with label b's file */
	ok &= (cw_try(NULL, NULL, "-l", "c", &a) == 2) && (cw_try(NULL, NULL, "-s", "16", &a) == 2);
	ok &= (cw_try(NULL, NULL, "-o", "/dev/shmem/j1x", &a) == 2) && (cw_try(NULL, NULL, "extra", NULL, &a) == 2);
	check(ok, "watch: out-of-range, malformed, missing, repeated and unknown arguments refused");
	ok = 1;
	for (size_t i = 0; i < sizeof(addresses) / sizeof(addresses[0]); i++) {
		ok &= (cw_try("-n", addresses[i], NULL, NULL, &a) == 0) && lookup(a.name) == NULL;
	}
	check(ok, "watch: an address as a name, the black box's among them, is refused by lookup");
	check(sim_refusal(SIM_TCG, S1_CANARY_C2_BASE, C_NO_ENTRY) && sim_refusal(SIM_GOOD, S1_CANARY_C2_BASE, C_OK),
	      "watch: the canary check it shares with verify");

	if (st_fail == fail0) {
		say("MEMCANARY-W SELFTEST PASS %u checks\n", st_ran - ran0);
	} else {
		say("MEMCANARY-W SELFTEST FAIL %u of %u checks\n", st_fail - fail0, st_ran - ran0);
	}
}
#endif

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

#ifdef MEMCANARY_WATCH
	cw_selftest();
#endif
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
#ifdef MEMCANARY_WATCH
	fprintf(stderr, "       memcanary-w watch -n c1|c2|c3 -l LABEL -i MS -c COUNT -T SECS -d /dev/shmem/j1LABEL.bin\n"
	                "  LABEL is [a-z0-9]{1,8}, MS 0-60000, COUNT 1-100000, SECS 1-3600; -d names this LABEL's file\n");
#endif
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

#ifdef MEMCANARY_WATCH
/* watch's command line after the mode: 0 when every flag is present once and in range, else 2.
 * The numbers are decimal only, so a hex address is refused here, and a name by lookup() later. */
static int
cw_parse(int const argc, char **const argv, struct cw_args *const a)
{
	int have_i = 0;
	int have_c = 0;
	int have_t = 0;

	memset(a, 0, sizeof(*a));
	for (int i = 2; i < argc; i++) {
		const char *const f   = argv[i];
		int const         val = (i + 1 < argc);

		if (val && strcmp(f, "-n") == 0 && a->name == NULL) {
			a->name = argv[++i];
		} else if (val && strcmp(f, "-l") == 0 && a->label == NULL) {
			a->label = argv[++i];
		} else if (val && strcmp(f, "-i") == 0 && !have_i) {
			if (!parse_uint(argv[++i], 0u, CW_MS_MAX, &a->ms)) {
				return 2;
			}
			have_i = 1;
		} else if (val && strcmp(f, "-c") == 0 && !have_c) {
			if (!parse_uint(argv[++i], 1u, CW_COUNT_MAX, &a->count)) {
				return 2;
			}
			have_c = 1;
		} else if (val && strcmp(f, "-T") == 0 && !have_t) {
			if (!parse_uint(argv[++i], 1u, CW_SECS_MAX, &a->secs)) {
				return 2;
			}
			have_t = 1;
		} else if (val && strcmp(f, "-d") == 0 && a->dump == NULL) {
			a->dump = argv[++i];
		} else {
			return 2;
		}
	}
	if (a->name == NULL || a->label == NULL || a->dump == NULL || !have_i || !have_c || !have_t
	    || !cw_label_ok(a->label) || !cw_dump_ok(a->dump, a->label)) {
		return 2;
	}
	return 0;
}
#endif

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
#ifdef MEMCANARY_WATCH
	if (strcmp(mode, "watch") == 0) {
		struct cw_args a;

		return (cw_parse(argc, argv, &a) != 0) ? usage() : cmd_watch(&a);
	}
#endif

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
