/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * smpcheck — the M2 payload: a census, a pinned load per core, a verdict.
 *
 * Phase 3b, M2 (docs/orin-native-port-plan.md; the M2 design's §5 is the
 * specification this implements). Startup prints what it did to each core. This
 * reads back what the kernel was actually handed, then puts one pinned, timed
 * load on every core, so a pass is a statement about the running system rather
 * than about startup's intentions. M1b (the M1b design's §3.10) adds two things
 * to the census: the hypervisor fields of the system page, and a bounded check
 * that cpu 0's kernel clock ticks at all.
 *
 *   smpcheck -i -n 6                          census of the kernel's system page
 *   smpcheck -b 60 -C 3 -o /dev/shmem/m2c3 &  silent busy worker pinned to cpu 3
 *   smpcheck -R 6 -p /dev/shmem/m2c -T 15     print the workers' ready lines
 *   smpcheck -c 6 -p /dev/shmem/m2c -T 90     print their results and the verdict
 *   smpcheck -k /dev/shmem/m2.txt -n 6        count traceprinter lines per cpu
 *   smpcheck -z 3                             sleep so the TCU can drain
 *
 * Two rules shape everything below.
 *
 * One printer at a time. The kernel-time console callout, display_char_tcu
 * (startup/t234-orin-nano/aarch64/callout_debug_tcu.S:99-143), takes no lock,
 * and whether procnto serialises debug output across cores is unknown. So a
 * busy worker never prints: it writes one line to a file, and the collector,
 * one foreground process, prints those lines one after another.
 *
 * No mode may block forever. Nobody is standing next to the board, and a hang
 * costs a power cycle, which wipes the black box. Every wait has a deadline in
 * ClockCycles(). A waiter that has to sleep pins itself to cpu 0 first: cpu 0's
 * clock is the one qtime names; the census proves it ticks before any waiter
 * relies on it (-i). A timer that never fires on an application processor is
 * exactly one of the failures this tool is here to catch, so it must not also
 * be able to stop the tool. The one sleep that has
 * to happen on the core under test, a worker's timer check, is watched from
 * cpu 0 by a second thread that writes the hang into the record and ends the
 * process.
 *
 * Exit status: 0 PASS, 1 FAIL, 2 usage, 3 PASS-DEGRADED (fewer than six cpus
 * expected). The script ignores it; the printed lines are the record.
 */

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>
#include <sys/sysmgr.h>

/*
 * ---- Expectations: a DUPLICATE of the board's tables ----------------------
 *
 * The source of truth is orin-native/startup/t234-orin-nano/board_smp.c, which
 * holds t234_cpu_mpidr[], t234_cpu_gicr_idx[] and t234_cpu_sgi1r[], together
 * with psci_cpu_id.c, which hands those affinities to PSCI CPU_ON. Startup
 * checks each core against those tables as it brings the core up; this checks
 * the kernel's copy of the system page against the same values afterwards. If
 * the board's tables change, change them there first and then here.
 *
 *   affinity   MPIDR & 0xff00ffffff, from the device tree's cpu@ reg cells
 *   gicr idx   redistributor frame: 0-3 for cluster 0, 6-7 for cluster 1;
 *              frames 4 and 5 are empty on this floor-swept SKU
 *   gicr base  the asinfo "gicr" start plus idx << 17, the 0x20000 frame
 *              stride (startup library aarch64/gic_v3.c:324; the asinfo entry
 *              is added at :334)
 *   SGI1R      the IPI value the library stores in gic_map: 1 << Aff0 |
 *              Aff1 << 16 | Aff2 << 32 (aarch64/gic_v3.c:1528-1542)
 */
#define EXPECT_CPUS     6

static const uint64_t expect_aff[EXPECT_CPUS] = {
	0x00000ull, 0x00100ull, 0x00200ull, 0x00300ull, 0x10200ull, 0x10300ull,
};
static const unsigned expect_gicr_idx[EXPECT_CPUS] = {
	0, 1, 2, 3, 6, 7,
};
static const uint64_t expect_gicr[EXPECT_CPUS] = {
	0x0F440000ull, 0x0F460000ull, 0x0F480000ull,
	0x0F4A0000ull, 0x0F500000ull, 0x0F520000ull,
};
static const uint64_t expect_sgi1r[EXPECT_CPUS] = {
	0x1ull, 0x10001ull, 0x20001ull, 0x30001ull, 0x100020001ull, 0x100030001ull,
};
/* ---- end of the duplicated tables ---------------------------------------- */

#define AFF_MASK        0xff00ffffffull /* Aff3 and Aff2..Aff0; drops bits 31, 30, 24 */
#define GICR_SHIFT      17
#define GICR_IDX_MASK   0xffffu         /* top half names a region (aarch64/syspage.h:95-97) */

#define WORKER_PRIO     9               /* below the script and the collector */
#define WATCH_PRIO      10              /* level with them */

#define TIMER_SLEEP_MS  100
#define TIMER_MIN_MS    90
#define TIMER_MAX_MS    2000
#define SAMPLE_EVERY    0x10000u        /* busy iterations per sample: 65,536 */

#define POLL_MS         200             /* collector: how often it looks for files */
#define WD_POLL_MS      250             /* watchdog: how often it looks at the worker */
#define WD_GRACE_S      3               /* per-stage budget on top of its nominal length */

#define MAX_N           32              /* one runmask word */
#define MAX_SECS        3600
#define PREFIX_MAX      200
#define PATH_BUF        256
#define TEXT_BUF        512
#define SAMPLE_CHARS    80

/* ------------------------------------------------------------------------ */
/* Small helpers                                                             */
/* ------------------------------------------------------------------------ */

static void out(const char *fmt, ...) __attribute__((__format__(__printf__, 1, 2)));

/* One call, one complete line, flushed: the console is the record. */
static void
out(const char *const fmt, ...)
{
	va_list ap;

	va_start(ap, fmt);
	(void)vprintf(fmt, ap);
	va_end(ap);
	(void)fflush(stdout);
}

static int
pass_code(unsigned const n)
{
	return (n < EXPECT_CPUS) ? 3 : 0;
}

/* Replace anything that is not printable ASCII, so a stray byte cannot reach the console. */
static void
sanitize(char *s)
{
	for (; *s != '\0'; s++) {
		if ((unsigned char)*s < 0x20 || (unsigned char)*s > 0x7e) {
			*s = '.';
		}
	}
}

/* Copy up to the first newline, cut to size - 1 characters. */
static void
copy_cut(char *const dst, size_t const size, const char *const src)
{
	size_t len = strcspn(src, "\n");

	if (len > size - 1) {
		len = size - 1;
	}
	memcpy(dst, src, len);
	dst[len] = '\0';
	sanitize(dst);
}

/*
 * The qtime section's cycles_per_sec, or 0 when the section is too short to
 * hold it. On this board the counter is CNTVCT_EL0 (aarch64/neutrino.h:70).
 */
static uint64_t
syspage_cps(void)
{
	if ((size_t)SYSPAGE_ENTRY_SIZE(qtime)
	    < offsetof(struct qtime_entry, cycles_per_sec) + sizeof(uint64_t)) {
		return 0;
	}
	return SYSPAGE_ENTRY(qtime)->cycles_per_sec;
}

static uint64_t
cycles_to_ms(uint64_t const cycles, uint64_t const cps)
{
	return (cycles / cps) * 1000u + ((cycles % cps) * 1000u) / cps;
}

/* Returns 0 or an error number. POSIX has clock_nanosleep return the number; -1 plus errno is accepted too. */
static int
sleep_ms(unsigned const ms)
{
	struct timespec const ts = {
		.tv_sec  = (time_t)(ms / 1000u),
		.tv_nsec = (long)(ms % 1000u) * 1000000L,
	};
	int const rc = clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, NULL);

	return (rc == -1) ? errno : rc;
}

/*
 * Pin the calling thread. _NTO_TCTL_RUNMASK takes the mask itself as the data
 * argument (sys/neutrino.h:432); it changes this thread only.
 */
static int
pin_self(unsigned const cpu)
{
	if (ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)(1u << cpu)) == -1) {
		return errno;
	}
	return 0;
}

/* Every mode that sleeps while waiting does it on cpu 0 (see the header). */
static void
pin_waiter(void)
{
	int const err = pin_self(0);

	if (err != 0) {
		out("SMPCHECK note: cannot pin this waiter to cpu 0 (%s); waiting unpinned\n",
		    strerror(err));
	}
}

static int
make_path(char *const buf, size_t const size, const char *const prefix,
          int const idx, const char *const suffix)
{
	int const n = (idx < 0) ? snprintf(buf, size, "%s%s", prefix, suffix)
	                        : snprintf(buf, size, "%s%d%s", prefix, idx, suffix);

	return n > 0 && (size_t)n < size;
}

/*
 * Write a whole line in a single write(). A reader that opens the file between
 * the truncate and the write sees no newline and simply looks again, so no
 * rename is needed, and /dev/shmem's support for one never has to be relied on.
 */
static int
write_line_file(const char *const path, const char *const line)
{
	int const    fd  = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	size_t const len = strlen(line);
	ssize_t      n;
	int          err;

	if (fd == -1) {
		return errno;
	}
	n   = write(fd, line, len);
	err = (n == (ssize_t)len) ? 0 : ((n == -1) ? errno : EIO);
	if (close(fd) == -1 && err == 0) {
		err = errno;
	}
	return err;
}

/*
 * 1 when the file holds a complete, newline-terminated line, which is returned
 * without its newline. O_NONBLOCK makes a FIFO or device at that path return
 * at once instead of waiting for a writer.
 */
static int
read_line_file(const char *const path, char *const buf, size_t const size)
{
	int const fd = open(path, O_RDONLY | O_NONBLOCK);
	ssize_t   n;
	char     *nl;

	buf[0] = '\0';
	if (fd == -1) {
		return 0;
	}
	n = read(fd, buf, size - 1);
	(void)close(fd);
	if (n <= 0) {
		buf[0] = '\0';
		return 0;
	}
	buf[n] = '\0';
	nl = memchr(buf, '\n', (size_t)n);
	if (nl == NULL) {
		buf[0] = '\0';
		return 0;
	}
	*nl = '\0';
	sanitize(buf);
	return 1;
}

/* The value after " key=" (or "key=" at the start of the line), else NULL. */
static const char *
kv_find(const char *const line, const char *const key)
{
	size_t const klen = strlen(key);

	for (const char *p = strstr(line, key); p != NULL; p = strstr(p + 1, key)) {
		if ((p == line || p[-1] == ' ') && p[klen] == '=') {
			return p + klen + 1;
		}
	}
	return NULL;
}

static int
kv_u64(const char *const line, const char *const key, unsigned long long *const v)
{
	const char *const s = kv_find(line, key);
	char             *end;

	if (s == NULL || *s < '0' || *s > '9') {
		return 0;
	}
	errno = 0;
	*v = strtoull(s, &end, 10);
	return errno == 0 && (*end == ' ' || *end == '\0' || *end == '\n');
}

static int
kv_is(const char *const line, const char *const key, const char *const want)
{
	const char *const s = kv_find(line, key);
	size_t const      n = strlen(want);

	return s != NULL && strncmp(s, want, n) == 0
	       && (s[n] == ' ' || s[n] == '\0' || s[n] == '\n');
}

static int
parse_uint(const char *const s, unsigned const lo, unsigned const hi, unsigned *const v)
{
	char         *end;
	unsigned long x;

	if (s == NULL || *s < '0' || *s > '9') {
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

/* ------------------------------------------------------------------------ */
/* -i: census                                                                */
/* ------------------------------------------------------------------------ */

/* A NUL-terminated string at offset off in the strings section, or NULL if it runs off the end. */
static const char *
syspage_string(unsigned const off)
{
	size_t const      size = SYSPAGE_ENTRY_SIZE(strings);
	const char *const base = (const char *)SYSPAGE_ENTRY(strings)
	                         + offsetof(struct strings_entry, data);

	if (off >= size || memchr(base + off, '\0', size - off) == NULL) {
		return NULL;
	}
	return base + off;
}

/* The start of the asinfo entry with this name (gic_v3.c:334 adds "gicr"). */
static int
find_asinfo(const char *const want, uint64_t *const start)
{
	size_t const el = SYSPAGE_ELEMENT_SIZE(asinfo);
	size_t       count;

	if (el < sizeof(struct asinfo_entry)) {
		return 0;
	}
	count = SYSPAGE_ENTRY_SIZE(asinfo) / el;
	for (size_t i = 0; i < count; i++) {
		const struct asinfo_entry *const as   = SYSPAGE_ARRAY_IDX(asinfo, i);
		const char *const                name = syspage_string(as->name);

		if (name != NULL && strcmp(name, want) == 0) {
			*start = as->start;
			return 1;
		}
	}
	return 0;
}

/*
 * The kernel's view of the hypervisor mode, printed and never judged. qtime's
 * intr is the clock interrupt startup named: the virtual timer's PPI, or under
 * el2-host the EL2 virtual timer's (startup library
 * aarch64/init_qtime_v8gt.c:56-60). hypinfo's flags say only whether a
 * hypervisor mode was enabled (hypervisor_setup.c:86-90), not which one.
 * Neither is a PASS/FAIL input, so the census verdict reads the same in every
 * -Q mode. A section too short for its field prints "-".
 */
static void
census_hyp(void)
{
	char intr[16]  = "-";
	char flags[24] = "-";

	if ((size_t)SYSPAGE_ENTRY_SIZE(qtime)
	    >= offsetof(struct qtime_entry, intr) + sizeof(SYSPAGE_ENTRY(qtime)->intr)) {
		snprintf(intr, sizeof intr, "%u", (unsigned)SYSPAGE_ENTRY(qtime)->intr);
	}
	if ((size_t)SYSPAGE_ENTRY_SIZE(hypinfo) >= sizeof(struct hypinfo_entry)) {
		snprintf(flags, sizeof flags, "0x%llx",
		         (unsigned long long)SYSPAGE_ENTRY(hypinfo)->flags);
	}
	out("SMPCHECK census hyp qtime_intr=%s hypinfo_flags=%s\n", intr, flags);
}

/*
 * Census tick check: does the kernel clock on cpu 0 fire at all?
 *
 * Every later wait in the image sleeps — the collectors' polls, the workers'
 * timer checks and their watchdogs, the script's own sleeps — so a clock
 * interrupt that never arrives stalls the run with nothing left to end it but a
 * power cycle, which wipes the black box. Under -Q enable,el2-host that clock is
 * INTID 28, which procnto has not been seen to use on this board. So it is
 * proved here, before any worker starts, with a bound that needs no tick: one
 * thread sleeps 100 ms on cpu 0 while this thread, pinned there at the same
 * priority, polls ClockCycles() for at most TIMER_MAX_MS and yields between
 * polls, which lets the woken sleeper run. The thread that judges never sleeps.
 *
 * A dead clock ends in sysmgr_reboot(), so the run resets and the black box can
 * be read. Whether that reboot completes without a working tick is unknown.
 */
static struct {
	volatile int      done;
	volatile int      rc;
	volatile int      pin_err;      /* -1 not yet run, 0, or an error number */
	volatile uint64_t t0;
	volatile uint64_t t1;
} Tk;

static void *
tick_sleeper(void *const arg)
{
	(void)arg;
	Tk.pin_err = pin_self(0);
	Tk.t0      = ClockCycles();
	Tk.rc      = sleep_ms(TIMER_SLEEP_MS);
	Tk.t1      = ClockCycles();
	Tk.done    = 1;
	return NULL;
}

/* 0 when the tick was shown, 1 when the census must fail. Does not return on a dead tick. */
static int
tick_check(uint64_t const cps)
{
	pthread_t tid;
	uint64_t  bound;
	int       err;

	if (cps == 0) {
		out("SMPCHECK census tick=unknown (no cycles_per_sec)\n");
		return 1;       /* the census has already failed on cps */
	}
	pin_waiter();

	Tk.done    = 0;
	Tk.rc      = 0;
	Tk.pin_err = -1;
	err = pthread_create(&tid, NULL, tick_sleeper, NULL);
	if (err != 0) {
		out("SMPCHECK census tick=error errno=%d\n", err);
		return 1;
	}

	bound = ClockCycles() + (uint64_t)TIMER_MAX_MS * cps / 1000u;
	while (!Tk.done && ClockCycles() < bound) {
		(void)sched_yield();
	}

	if (!Tk.done) {
		int rc;
		int e;

		out("SMPCHECK census tick=dead ms>%u: the kernel clock on cpu 0 did not fire\n",
		    (unsigned)TIMER_MAX_MS);
		out("SMPCHECK CENSUS FAIL\n");
		out("SMPCHECK tick dead: calling sysmgr_reboot so the log can be recovered\n");
		rc = sysmgr_reboot();
		e  = errno;
		out("SMPCHECK sysmgr_reboot returned %d errno=%d\n", rc, e);
		exit(1);
	}
	(void)pthread_join(tid, NULL);

	if (Tk.pin_err > 0) {
		out("SMPCHECK note: the tick thread cannot pin to cpu 0 (%s); its sleep was not pinned\n",
		    strerror(Tk.pin_err));
	}
	if (Tk.t1 < Tk.t0) {
		out("SMPCHECK census tick=bad ms=backwards rc=%d\n", Tk.rc);
		return 1;
	}
	{
		unsigned long long const ms = cycles_to_ms(Tk.t1 - Tk.t0, cps);

		/* rc != 0 fails as it does in a worker's timer check (fmt_timer, judge_done). */
		if (Tk.rc == 0 && ms >= TIMER_MIN_MS && ms <= TIMER_MAX_MS) {
			out("SMPCHECK census tick=ok ms=%llu rc=%d\n", ms, Tk.rc);
			return 0;
		}
		out("SMPCHECK census tick=bad ms=%llu rc=%d\n", ms, Tk.rc);
	}
	return 1;
}

/*
 * Re-prove, from the kernel's copy of the system page, what startup printed.
 * Every section is bounds-checked against its recorded size before it is
 * indexed; a section too short for a cpu shows as "-" and fails that row.
 *
 *   hwid   cpuinfo[i].smp_hwcoreid: MPIDR_EL1 read on cpu i itself
 *          (startup library aarch64/init_cpuinfo.c:182-183)
 *   gic    gic_map[i], sized for PROCESSORS_MAX (aarch64/cpu_syspage_memory.c:35)
 *   idx    gicr_map[i], sized num_cpu * 4 (aarch64/gic_v3.c:1105, set at :1356)
 */
static int
census(unsigned const n)
{
	unsigned const        num_cpu = _syspage_ptr->num_cpu;
	uint64_t const        cps     = syspage_cps();
	size_t const          ci_el   = SYSPAGE_ELEMENT_SIZE(cpuinfo);
	size_t const          ci_cnt  = (ci_el >= sizeof(struct cpuinfo_entry))
	                                ? SYSPAGE_ENTRY_SIZE(cpuinfo) / ci_el : 0;
	size_t const          gic_sz  = SYSPAGE_CPU_ENTRY_SIZE(aarch64, gic_map);
	size_t const          gicr_sz = SYSPAGE_CPU_ENTRY_SIZE(aarch64, gicr_map);
	const uint64_t *const gic     = (const uint64_t *)(void *)
	        ((const char *)SYSPAGE_CPU_ENTRY(aarch64, gic_map)
	         + offsetof(struct aarch64_gic_map_entry, gic_cpu));
	const uint32_t *const gicr    = (const uint32_t *)(void *)
	        ((const char *)SYSPAGE_CPU_ENTRY(aarch64, gicr_map)
	         + offsetof(struct aarch64_gicr_map_entry, gicr_idx));
	uint64_t              gicr_start = 0;
	int const             have_gicr  = find_asinfo("gicr", &gicr_start);
	int                   fail       = 0;

	out("SMPCHECK census cps=%llu num_cpu=%u expect=%u smp_size=%u online=%ld\n",
	    (unsigned long long)cps, num_cpu, n, (unsigned)SYSPAGE_ENTRY_SIZE(smp),
	    sysconf(_SC_NPROCESSORS_ONLN));
	if (cps == 0) {
		out("SMPCHECK census MISMATCH qtime cycles_per_sec is 0\n");
		fail = 1;
	}
	if (num_cpu != n) {
		out("SMPCHECK census MISMATCH num_cpu=%u, expected %u\n", num_cpu, n);
		fail = 1;
	}
	if (!have_gicr) {
		out("SMPCHECK census MISMATCH no asinfo entry named gicr\n");
		fail = 1;
	}

	for (unsigned i = 0; i < num_cpu; i++) {
		char hwid[24] = "-", aff[24] = "-", gicv[24] = "-";
		char idx[16]  = "-", base[24] = "-", name[33] = "-";
		int  ok       = (i < EXPECT_CPUS);   /* no expectation, no pass */

		if (i < ci_cnt) {
			const struct cpuinfo_entry *const ci = SYSPAGE_ARRAY_IDX(cpuinfo, i);
			uint64_t const                    a  = ci->smp_hwcoreid & AFF_MASK;
			const char *const                 s  = syspage_string(ci->name);

			snprintf(hwid, sizeof hwid, "0x%llx", (unsigned long long)ci->smp_hwcoreid);
			snprintf(aff, sizeof aff, "0x%llx", (unsigned long long)a);
			if (s != NULL) {
				copy_cut(name, sizeof name, s);
			}
			ok = ok && a == expect_aff[i];
		} else {
			ok = 0;
		}

		if ((i + 1u) * sizeof(uint64_t) <= gic_sz) {
			snprintf(gicv, sizeof gicv, "0x%llx", (unsigned long long)gic[i]);
			ok = ok && gic[i] == expect_sgi1r[i];
		} else {
			ok = 0;
		}

		if ((i + 1u) * sizeof(uint32_t) <= gicr_sz) {
			unsigned const x = gicr[i] & GICR_IDX_MASK;

			snprintf(idx, sizeof idx, "%u", x);
			ok = ok && x == expect_gicr_idx[i];
			if (have_gicr) {
				uint64_t const b = gicr_start + ((uint64_t)x << GICR_SHIFT);

				snprintf(base, sizeof base, "0x%08llx", (unsigned long long)b);
				ok = ok && b == expect_gicr[i];
			} else {
				ok = 0;
			}
		} else {
			ok = 0;
		}

		out("SMPCHECK cpu %u hwid=%s aff=%s gic=%s gicr_idx=%s gicr=%s name=%s %s\n",
		    i, hwid, aff, gicv, idx, base, name, ok ? "ok" : "MISMATCH");
		if (!ok) {
			fail = 1;
		}
	}

	/* M1b: informational hypervisor fields, then the cpu 0 tick (no return if dead). */
	census_hyp();
	if (tick_check(cps) != 0) {
		fail = 1;
	}

	out("SMPCHECK CENSUS %s\n", fail ? "FAIL" : "PASS");
	return fail ? 1 : pass_code(n);
}

/* ------------------------------------------------------------------------ */
/* Pass rule for one done line, shared by -b (its own record) and -c         */
/* ------------------------------------------------------------------------ */

static void
add_reason(char *const reasons, size_t const size, unsigned const cpu, const char *const why)
{
	size_t len;

	if (reasons == NULL) {
		return;
	}
	len = strlen(reasons);
	if (len + 1 < size) {
		(void)snprintf(reasons + len, size - len, "%scpu%u:%s", (len != 0) ? "," : "", cpu, why);
	}
}

/*
 * PASS for cpu i needs: the file is cpu i's, the worker ran to its end, the pin
 * held, both timer checks returned within [90 ms, 2 s] on cpu i, samples > 0,
 * misplaced == 0, backwards == 0, and the load lasted the seconds asked for.
 * Iteration rates are informational only: DVFS is not controlled.
 */
static int
judge_done(unsigned const i, const char *const line, char *const reasons, size_t const size)
{
	static const char *const ms_key[2]  = { "timer0_ms", "timer1_ms" };
	static const char *const cpu_key[2] = { "timer0_cpu", "timer1_cpu" };
	static const char *const tag[2]     = { "timer0", "timer1" };
	unsigned long long       v, w;
	int                      ok = 1;

	if (!kv_u64(line, "cpu", &v) || v != i) {
		ok = 0;
		add_reason(reasons, size, i, "file");
	}
	if (!kv_is(line, "end", "ok")) {
		ok = 0;
		add_reason(reasons, size, i, "hung");
	}
	if (!kv_is(line, "pin", "ok")) {
		ok = 0;
		add_reason(reasons, size, i, "pin");
	}
	for (int k = 0; k < 2; k++) {
		if (!kv_u64(line, ms_key[k], &v) || v < TIMER_MIN_MS || v > TIMER_MAX_MS
		    || !kv_u64(line, cpu_key[k], &w) || w != i) {
			ok = 0;
			add_reason(reasons, size, i, tag[k]);
		}
	}
	if (!kv_u64(line, "samples", &v) || v == 0) {
		ok = 0;
		add_reason(reasons, size, i, "samples");
	}
	if (!kv_u64(line, "misplaced", &v) || v != 0) {
		ok = 0;
		add_reason(reasons, size, i, "misplaced");
	}
	if (!kv_u64(line, "backwards", &v) || v != 0) {
		ok = 0;
		add_reason(reasons, size, i, "backwards");
	}
	if (!kv_u64(line, "secs", &v) || !kv_u64(line, "elapsed_ms", &w) || w < v * 1000u) {
		ok = 0;
		add_reason(reasons, size, i, "short");
	}
	return ok;
}

/* ------------------------------------------------------------------------ */
/* -b: silent busy worker                                                    */
/* ------------------------------------------------------------------------ */

/* ST_NOWD is never a stage; it marks a record written because no watchdog started. */
enum { ST_PIN, ST_TIMER0, ST_BUSY, ST_TIMER1, ST_FINISH, ST_NOWD };
enum { WD_NONE, WD_STARTED, WD_PINNED, WD_UNPINNED };

#define NO_HANG         (-1)
#define NOT_RUN         (-1)
#define MS_BACKWARDS    (-2)

/*
 * Shared between the worker and its watchdog. The watchdog only reads, apart
 * from wd; a file is written only with lock held, and ready_written and
 * done_written make each file a write-once record whichever thread gets there.
 */
static struct {
	unsigned          cpu;
	unsigned          secs;
	uint64_t          cps;
	char              ready[PATH_BUF];
	char              done[PATH_BUF];
	pthread_mutex_t   lock;
	int               ready_written;
	int               done_written;
	volatile int      stage;
	volatile int      wd;
	volatile int      prio_err;     /* NOT_RUN, 0, or an error number */
	volatile int      pin_err;
	volatile int      get_err;
	volatile unsigned mask;         /* runmask as read back */
	volatile int      t_rc[2];
	volatile int      t_cpu[2];
	volatile int64_t  t_ms[2];      /* NOT_RUN, MS_BACKWARDS, or milliseconds */
	volatile uint64_t samples;
	volatile uint64_t misplaced;
	volatile uint64_t backwards;
	volatile uint64_t iters;
	volatile uint64_t busy_ms;
	volatile uint64_t spin;         /* keeps the busy work observable to the compiler */
} W;

static const char *
pin_word(int const hung)
{
	if (hung == ST_PIN) {
		return "hung";
	}
	if (W.pin_err == NOT_RUN) {
		return "-";     /* not attempted: only a no-watchdog record gets here */
	}
	return (W.pin_err == 0 && W.get_err == 0 && W.mask == (1u << W.cpu)) ? "ok" : "err";
}

static const char *
end_word(int const hung)
{
	switch (hung) {
	case NO_HANG:   return "ok";
	case ST_PIN:    return "hung-pin";
	case ST_TIMER0: return "hung-timer0";
	case ST_BUSY:   return "hung-busy";
	case ST_TIMER1: return "hung-timer1";
	case ST_NOWD:   return "nowatchdog";
	default:        return "hung-finish";
	}
}

static const char *
wd_word(void)
{
	switch (W.wd) {
	case WD_PINNED:   return "ok";
	case WD_UNPINNED: return "unpinned";
	case WD_STARTED:  return "starting";
	default:          return "none";
	}
}

static void
fmt_timer(char *const ms, char *const cpu, size_t const size, int const k, int const hung)
{
	if (hung == ((k == 0) ? ST_TIMER0 : ST_TIMER1)) {
		snprintf(ms, size, "hung");
		snprintf(cpu, size, "-");
	} else if (W.t_ms[k] == NOT_RUN) {
		snprintf(ms, size, "-");
		snprintf(cpu, size, "-");
	} else {
		if (W.t_rc[k] != 0) {
			snprintf(ms, size, "err%d", W.t_rc[k]);
		} else if (W.t_ms[k] == MS_BACKWARDS) {
			snprintf(ms, size, "backwards");
		} else {
			snprintf(ms, size, "%lld", (long long)W.t_ms[k]);
		}
		snprintf(cpu, size, "%d", W.t_cpu[k]);
	}
}

static void
fmt_ready(char *const buf, size_t const size, int const hung)
{
	char prio[16] = "-", mask[16] = "-", ms[24], cpu[24];
	int  err = 0;

	if (W.prio_err == 0) {
		snprintf(prio, sizeof prio, "ok");
	} else if (W.prio_err != NOT_RUN) {
		snprintf(prio, sizeof prio, "err%d", W.prio_err);
	}
	if (W.get_err == 0) {
		snprintf(mask, sizeof mask, "0x%x", W.mask);
	}
	if (W.pin_err > 0) {
		err = W.pin_err;
	} else if (W.get_err > 0) {
		err = W.get_err;
	}
	fmt_timer(ms, cpu, sizeof ms, 0, hung);
	snprintf(buf, size,
	         "SMPCHECK ready cpu=%u prio=%s pin=%s mask=%s errno=%d timer0_ms=%s timer0_cpu=%s wd=%s\n",
	         W.cpu, prio, pin_word(hung), mask, err, ms, cpu, wd_word());
}

/*
 * The design's record plus three fields its pass rule needs: elapsed_ms (the
 * -c line's -T is the wait bound, not the load length, so the length has to
 * travel in the file), timerK_cpu (the "on cpu c afterwards" half of the timer
 * check), and end (ok, or which stage the watchdog found stuck).
 */
static void
fmt_done(char *const buf, size_t const size, int const hung)
{
	char           ms0[24], cpu0[24], ms1[24], cpu1[24];
	uint64_t const iters   = W.iters;
	uint64_t const busy_ms = W.busy_ms;

	fmt_timer(ms0, cpu0, sizeof ms0, 0, hung);
	fmt_timer(ms1, cpu1, sizeof ms1, 1, hung);
	snprintf(buf, size,
	         "SMPCHECK done cpu=%u secs=%u elapsed_ms=%llu samples=%llu misplaced=%llu "
	         "backwards=%llu iters=%llu rate=%llu timer0_ms=%s timer0_cpu=%s "
	         "timer1_ms=%s timer1_cpu=%s pin=%s end=%s\n",
	         W.cpu, W.secs, (unsigned long long)busy_ms,
	         (unsigned long long)W.samples, (unsigned long long)W.misplaced,
	         (unsigned long long)W.backwards, (unsigned long long)iters,
	         (unsigned long long)((busy_ms != 0) ? iters * 1000u / busy_ms : 0),
	         ms0, cpu0, ms1, cpu1, pin_word(hung), end_word(hung));
}

/* Both are called with W.lock held. */
static void
emit_ready(int const hung)
{
	char line[TEXT_BUF];

	if (!W.ready_written) {
		fmt_ready(line, sizeof line, hung);
		(void)write_line_file(W.ready, line);
		W.ready_written = 1;
	}
}

static void
emit_done(int const hung, char *const line, size_t const size)
{
	if (!W.done_written) {
		fmt_done(line, size, hung);
		(void)write_line_file(W.done, line);
		W.done_written = 1;
	}
}

/*
 * The timer check (design §5 steps 4 and 7). QNX 8.0 documents that a software
 * timer fires on the core that armed it — a vendor claim, not something read
 * here — so a 100 ms sleep that returns in time, still on this core, is taken
 * as evidence that this core's timer interrupt is being delivered. Plausible,
 * not proof. Both readings come from this core's own counter.
 */
static void
timer_check(int const k)
{
	uint64_t const t0 = ClockCycles();
	int const      rc = sleep_ms(TIMER_SLEEP_MS);
	uint64_t const t1 = ClockCycles();

	W.t_cpu[k] = (int)SchedGetCpuNum();
	W.t_rc[k]  = rc;
	W.t_ms[k]  = (t1 >= t0) ? (int64_t)cycles_to_ms(t1 - t0, W.cps) : MS_BACKWARDS;
}

/* Design §5 step 6: load this core for secs seconds of its own ClockCycles(). */
static void
busy(void)
{
	uint64_t const cps       = W.cps;
	uint64_t const start     = ClockCycles();
	uint64_t const end       = start + (uint64_t)W.secs * cps;
	uint64_t       prev      = start;
	uint64_t       now       = start;
	uint64_t       samples   = 0;
	uint64_t       misplaced = 0;
	uint64_t       backwards = 0;
	uint64_t       x         = start | 1u;

	do {
		/*
		 * A multiply-add recurrence rather than an empty count: an empty
		 * loop is a simple induction variable the compiler can fold into
		 * one addition, and then the core would not really be busy.
		 */
		for (unsigned i = 0; i < SAMPLE_EVERY; i++) {
			x = x * 6364136223846793005ull + 1442695040888963407ull;
		}
		W.spin = x;

		samples++;
		if (SchedGetCpuNum() != W.cpu) {
			misplaced++;
		}
		now = ClockCycles();
		if (now < prev) {
			backwards++;
		}
		prev = now;

		/* Published every sample so the watchdog can record progress. */
		W.samples   = samples;
		W.misplaced = misplaced;
		W.backwards = backwards;
		W.iters     = samples * SAMPLE_EVERY;
		W.busy_ms   = (now >= start) ? cycles_to_ms(now - start, cps) : 0;
	} while (now < end);
}

/*
 * The worker's bound. It lives on cpu 0 and gives each stage WD_GRACE_S beyond
 * its nominal length (the load stage gets secs more). Stage lengths are timed on
 * the watchdog's own counter, from when it first saw the stage, so nothing here
 * assumes ClockCycles() agrees across cores — which has not been measured. If a
 * stage overruns, the watchdog writes whichever files are still missing, marked
 * with the stuck stage, and ends the process: a dead timer on the core under
 * test, a core that stops scheduling the worker, or a clock that runs backwards
 * all end in a record instead of a process that never exits.
 */
static void *
watchdog(void *const arg)
{
	uint64_t const cps       = W.cps;
	int            seen      = -1;
	uint64_t       since     = 0;
	unsigned       waited_ms = 0;
	char           line[TEXT_BUF];

	(void)arg;
	W.wd = (pin_self(0) == 0) ? WD_PINNED : WD_UNPINNED;

	for (;;) {
		uint64_t now;
		uint64_t budget;
		int      st;

		(void)sleep_ms(WD_POLL_MS);
		now = ClockCycles();
		st  = W.stage;
		if (st != seen || now < since) {
			seen  = st;
			since = now;
			continue;
		}
		budget = ((st == ST_BUSY) ? (uint64_t)W.secs + WD_GRACE_S : (uint64_t)WD_GRACE_S) * cps;
		if (now - since <= budget) {
			continue;
		}

		if (pthread_mutex_trylock(&W.lock) == 0) {
			if (W.done_written) {
				/* The worker finished as the budget ran out; it is exiting. */
				(void)pthread_mutex_unlock(&W.lock);
				continue;
			}
			/*
			 * If the stuck stage ends between the check above and here, the
			 * record still says hung. That needs a stage WD_GRACE_S late,
			 * which fails the check anyway.
			 */
			emit_ready(st);
			emit_done(st, line, sizeof line);
			_exit(1);
		}
		/* The worker holds the lock, so it is writing a file. Allow it one more grace period. */
		waited_ms += WD_POLL_MS;
		if (waited_ms >= WD_GRACE_S * 1000u) {
			_exit(1);
		}
	}
	return NULL;
}

/*
 * Design §5, -b. Silent: nothing goes to the console from here, not even on
 * failure. A worker that cannot write its files is reported by the collector
 * as MISSING.
 */
static int
busy_worker(unsigned const cpu, unsigned const secs, const char *const prefix)
{
	unsigned const     num_cpu = _syspage_ptr->num_cpu;
	pthread_attr_t     attr;
	pthread_t          tid;
	struct sched_param sp;
	char               line[TEXT_BUF] = "";    /* judged below; empty fails */

	W.cpu      = cpu;
	W.secs     = secs;
	W.cps      = syspage_cps();
	W.stage    = ST_PIN;
	W.wd       = WD_NONE;
	W.prio_err = NOT_RUN;
	W.pin_err  = NOT_RUN;
	W.get_err  = NOT_RUN;
	W.t_ms[0]  = NOT_RUN;
	W.t_ms[1]  = NOT_RUN;
	W.t_cpu[0] = -1;
	W.t_cpu[1] = -1;

	if (!make_path(W.ready, sizeof W.ready, prefix, -1, ".ready")
	    || !make_path(W.done, sizeof W.done, prefix, -1, ".done")) {
		return 2;
	}
	if (W.cps == 0 || pthread_mutex_init(&W.lock, NULL) != 0) {
		return 1;       /* nothing to bound a wait with, or no lock: stay silent */
	}

	/* A record left by an earlier run in this boot must not pass for this one. */
	(void)unlink(W.ready);
	(void)unlink(W.done);

	/*
	 * 0. The watchdog first, so every step after this one is covered: explicit
	 * SCHED_RR priority WATCH_PRIO if that works, otherwise inherited attributes
	 * (the priority this process started at, before step 1 lowers it).
	 */
	W.wd = WD_STARTED;
	{
		int created = 0;

		if (pthread_attr_init(&attr) == 0) {
			memset(&sp, 0, sizeof sp);
			sp.sched_priority = WATCH_PRIO;
			if (pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED) == 0
			    && pthread_attr_setschedpolicy(&attr, SCHED_RR) == 0
			    && pthread_attr_setschedparam(&attr, &sp) == 0
			    && pthread_create(&tid, &attr, watchdog, NULL) == 0) {
				created = 1;
			}
			(void)pthread_attr_destroy(&attr);
		}
		if (!created && pthread_create(&tid, NULL, watchdog, NULL) == 0) {
			created = 1;
		}
		if (!created) {
			/*
			 * Nothing would bound the timer check's sleep on the core under
			 * test (timer_check() has no deadline of its own), so do not start
			 * it. Both records say why, and judge_done() fails them on end=.
			 */
			W.wd = WD_NONE;
			(void)pthread_mutex_lock(&W.lock);
			emit_ready(ST_NOWD);
			emit_done(ST_NOWD, line, sizeof line);
			(void)pthread_mutex_unlock(&W.lock);
			return 1;
		}
	}

	/* 1. Priority 9, round robin: below the script and the collector at 10. */
	memset(&sp, 0, sizeof sp);
	sp.sched_priority = WORKER_PRIO;
	W.prio_err = pthread_setschedparam(pthread_self(), SCHED_RR, &sp);

	/* 2. Pin to cpu c. */
	W.pin_err = pin_self(cpu);

	/*
	 * 3. Read the runmask back. _NTO_TCTL_RUNMASK_GET_AND_SET_INHERIT takes a
	 * struct _thread_runmask whose size must be exactly RMSK_SIZE(num_cpu),
	 * followed by that many runmask words and then as many inherit-mask words
	 * (sys/neutrino.h:478-489; the fortify check in sys/neutrino_chk.h:397-410
	 * sizes the buffer the same way). Both masks are passed as zero: QNX's
	 * ThreadCtl() documentation says a zero mask is left unchanged and the
	 * current value is returned in its place. That page is not in the SDP tree,
	 * so this rests on a vendor claim; a zero mask applied instead of read
	 * would show up as an error, a mask other than bit c, or a worker that
	 * stops being scheduled — the last of which the watchdog records.
	 */
	if (num_cpu == 0 || num_cpu > MAX_N) {
		W.get_err = E2BIG;      /* this reads one mask word: at most 32 cpus */
	} else {
		struct {
			struct _thread_runmask hdr;
			unsigned               bits[2];     /* runmask[1], then inherit_mask[1] */
		} rm;

		memset(&rm, 0, sizeof rm);
		rm.hdr.size = RMSK_SIZE(num_cpu);
		if (ThreadCtl(_NTO_TCTL_RUNMASK_GET_AND_SET_INHERIT, &rm) == -1) {
			W.get_err = errno;
		} else {
			W.mask    = rm.bits[0];
			W.get_err = 0;
		}
	}

	/* 4. Timer check on this core. */
	W.stage = ST_TIMER0;
	timer_check(0);

	/* 5. Ready. */
	(void)pthread_mutex_lock(&W.lock);
	emit_ready(NO_HANG);
	(void)pthread_mutex_unlock(&W.lock);

	/* 6. Load. */
	W.stage = ST_BUSY;
	busy();

	/* 7. Timer check again, after the load. */
	W.stage = ST_TIMER1;
	timer_check(1);

	/* 8. Done. */
	W.stage = ST_FINISH;
	(void)pthread_mutex_lock(&W.lock);
	emit_done(NO_HANG, line, sizeof line);
	(void)pthread_mutex_unlock(&W.lock);

	return judge_done(cpu, line, NULL, 0) ? 0 : 1;
}

/* ------------------------------------------------------------------------ */
/* -R and -c: bounded collectors                                             */
/* ------------------------------------------------------------------------ */

/*
 * Look for PREFIX<i><suffix>, i < n, until every one is a complete line or
 * secs have passed on cpu 0's counter. Returns how many were found.
 */
static unsigned
wait_files(unsigned const n, const char *const prefix, const char *const suffix,
           unsigned const secs, char lines[][TEXT_BUF], unsigned char have[])
{
	uint64_t const cps   = syspage_cps();
	unsigned       found = 0;
	uint64_t       dl;

	pin_waiter();
	if (cps == 0) {
		out("SMPCHECK note: qtime reports no cycles_per_sec; looking once instead of waiting\n");
	}
	dl = ClockCycles() + (uint64_t)secs * cps;
	memset(have, 0, n);

	for (;;) {
		for (unsigned i = 0; i < n; i++) {
			char path[PATH_BUF];

			if (!have[i] && make_path(path, sizeof path, prefix, (int)i, suffix)
			    && read_line_file(path, lines[i], TEXT_BUF)) {
				have[i] = 1;
				found++;
			}
		}
		if (found == n || cps == 0 || ClockCycles() >= dl) {
			return found;
		}
		(void)sleep_ms(POLL_MS);
	}
}

static int
collect_ready(unsigned const n, const char *const prefix, unsigned const secs)
{
	static char    lines[MAX_N][TEXT_BUF];
	unsigned char  have[MAX_N];
	unsigned const found = wait_files(n, prefix, ".ready", secs, lines, have);

	for (unsigned i = 0; i < n; i++) {
		if (have[i]) {
			out("%s\n", lines[i]);
		} else {
			out("SMPCHECK ready cpu=%u MISSING\n", i);
		}
	}
	return (found == n) ? pass_code(n) : 1;
}

static int
collect_done(unsigned const n, const char *const prefix, unsigned const secs)
{
	static char        lines[MAX_N][TEXT_BUF];
	unsigned char      have[MAX_N];
	char               reasons[TEXT_BUF] = "";
	unsigned           passed   = 0;
	unsigned long long min_secs = 0;
	int                any_secs = 0;
	const char        *verdict;

	(void)wait_files(n, prefix, ".done", secs, lines, have);

	for (unsigned i = 0; i < n; i++) {
		unsigned long long s;

		if (!have[i]) {
			out("SMPCHECK done cpu=%u MISSING\n", i);
			add_reason(reasons, sizeof reasons, i, "missing");
			continue;
		}
		out("%s\n", lines[i]);
		if (kv_u64(lines[i], "secs", &s) && (!any_secs || s < min_secs)) {
			min_secs = s;
			any_secs = 1;
		}
		if (judge_done(i, lines[i], reasons, sizeof reasons)) {
			passed++;
		}
	}

	if (passed != n) {
		verdict = "FAIL";
	} else {
		verdict = (n < EXPECT_CPUS) ? "PASS-DEGRADED" : "PASS";
	}
	out("SMPCHECK RESULT %s cpus=%u/%u secs=%llu reasons=%s\n",
	    verdict, passed, EXPECT_CPUS, min_secs, (reasons[0] != '\0') ? reasons : "none");
	return (passed != n) ? 1 : pass_code(n);
}

/* ------------------------------------------------------------------------ */
/* -k: traceprinter lines per cpu                                            */
/* ------------------------------------------------------------------------ */

/*
 * The cpu of a traceprinter line, or -1. traceprinter's default format, per its
 * own usage text, is "t:0x%08c CPU:%02C %-16Z:%-18z". Only the "CPU:" field is
 * relied on, spaces after the colon are allowed, and a "CPU:" not followed by a
 * digit is skipped, so a changed layout degrades to a high nomatch count rather
 * than wrong per-cpu numbers.
 */
static int
trace_cpu(const char *const line)
{
	for (const char *p = strstr(line, "CPU:"); p != NULL; p = strstr(p + 4, "CPU:")) {
		const char *q = p + 4;

		while (*q == ' ') {
			q++;
		}
		if (*q >= '0' && *q <= '9') {
			int v = 0;

			for (int d = 0; d < 3 && *q >= '0' && *q <= '9'; d++, q++) {
				v = v * 10 + (*q - '0');
			}
			return v;
		}
	}
	return -1;
}

static int
trace_count(const char *const path, unsigned const n)
{
	static char        samples[MAX_N][SAMPLE_CHARS + 1];
	unsigned long long counts[MAX_N] = { 0 };
	unsigned long long lines = 0, matched = 0, nomatch = 0, beyond = 0;
	unsigned           with  = 0;
	char               buf[1024];
	int const          fd    = open(path, O_RDONLY | O_NONBLOCK);
	FILE              *f     = NULL;

	if (fd != -1) {
		f = fdopen(fd, "r");
	}
	if (f == NULL) {
		int const err = errno;

		if (fd != -1) {
			(void)close(fd);
		}
		out("SMPCHECK trace cannot read %s: %s\n", path, strerror(err));
		out("SMPCHECK TRACE FAIL cpus=0/%u\n", n);
		return 1;
	}

	while (fgets(buf, sizeof buf, f) != NULL) {
		size_t const len = strlen(buf);
		int          cpu;

		if (len > 0 && buf[len - 1] != '\n') {
			int c;

			/* Longer than the buffer: drain the rest so it counts as one line. */
			while ((c = getc(f)) != EOF && c != '\n') {
			}
		}
		lines++;
		cpu = trace_cpu(buf);
		if (cpu < 0) {
			nomatch++;
			continue;
		}
		matched++;
		if ((unsigned)cpu >= n) {
			beyond++;
			continue;
		}
		if (counts[cpu]++ == 0) {
			copy_cut(samples[cpu], sizeof samples[cpu], buf);
		}
	}
	if (ferror(f)) {
		out("SMPCHECK note: read error on %s after %llu lines: %s\n", path, lines, strerror(errno));
	}
	(void)fclose(f);

	out("SMPCHECK trace lines=%llu matched=%llu nomatch=%llu beyond_n=%llu\n",
	    lines, matched, nomatch, beyond);
	for (unsigned i = 0; i < n; i++) {
		if (counts[i] != 0) {
			with++;
		}
		out("SMPCHECK trace cpu=%u events=%llu sample=\"%s\"\n", i, counts[i], samples[i]);
	}
	out("SMPCHECK TRACE %s cpus=%u/%u\n", (with == n) ? "PASS" : "FAIL", with, n);
	return (with == n) ? pass_code(n) : 1;
}

/* ------------------------------------------------------------------------ */
/* -z: let the TCU drain                                                     */
/* ------------------------------------------------------------------------ */

static int
drain_sleep(unsigned const secs)
{
	uint64_t const cps = syspage_cps();
	uint64_t       dl;

	pin_waiter();
	if (cps == 0) {
		(void)sleep_ms(secs * 1000u);
		return 0;
	}
	dl = ClockCycles() + (uint64_t)secs * cps;
	for (uint64_t now = ClockCycles(); now < dl; now = ClockCycles()) {
		uint64_t const left = cycles_to_ms(dl - now, cps);

		(void)sleep_ms((left >= 1000u) ? 1000u : (unsigned)left + 1u);
	}
	return 0;
}

/* ------------------------------------------------------------------------ */

static int
usage(const char *const argv0)
{
	out("usage: %s <mode>\n", argv0);
	out("  -i -n N                census: kernel system page against the board tables,\n");
	out("                         the hypervisor fields, and a bounded cpu 0 tick check\n");
	out("  -b S -C c -o PREFIX    silent worker: pin to cpu c, load it S s,\n");
	out("                         write PREFIX.ready and PREFIX.done\n");
	out("  -R N -p PREFIX -T S    wait up to S s for PREFIX0..N-1.ready, print them\n");
	out("  -c N -p PREFIX -T S    wait up to S s for PREFIX0..N-1.done, print them\n");
	out("                         and the verdict\n");
	out("  -k FILE -n N           count traceprinter lines per CPU:NN in FILE\n");
	out("  -z S                   sleep S s so the TCU can drain before a reset\n");
	out("  exit: 0 PASS, 1 FAIL, 2 usage, 3 PASS-DEGRADED (N < 6)\n");
	return 2;
}

int
main(int argc, char **argv)
{
	int         mode   = 0;
	int         modes  = 0;
	int         have_n = 0;
	int         have_c = 0;
	int         have_t = 0;
	unsigned    n      = 0;
	unsigned    secs   = 0;
	unsigned    cpu    = 0;
	unsigned    tmo    = 0;
	const char *outp   = NULL;
	const char *prefix = NULL;
	const char *file   = NULL;
	int         opt;

	while ((opt = getopt(argc, argv, "in:b:C:o:R:c:p:T:k:z:")) != -1) {
		switch (opt) {
		case 'i':
			mode = opt;
			modes++;
			break;
		case 'b':
		case 'z':
			mode = opt;
			modes++;
			if (!parse_uint(optarg, (opt == 'b') ? 1u : 0u, MAX_SECS, &secs)) {
				return usage(argv[0]);
			}
			break;
		case 'R':
		case 'c':
			mode = opt;
			modes++;
			if (!parse_uint(optarg, 1u, MAX_N, &n)) {
				return usage(argv[0]);
			}
			have_n = 1;
			break;
		case 'k':
			mode = opt;
			modes++;
			file = optarg;
			break;
		case 'n':
			if (!parse_uint(optarg, 1u, MAX_N, &n)) {
				return usage(argv[0]);
			}
			have_n = 1;
			break;
		case 'C':
			if (!parse_uint(optarg, 0u, MAX_N - 1u, &cpu)) {
				return usage(argv[0]);
			}
			have_c = 1;
			break;
		case 'o':
			outp = optarg;
			break;
		case 'p':
			prefix = optarg;
			break;
		case 'T':
			if (!parse_uint(optarg, 1u, MAX_SECS, &tmo)) {
				return usage(argv[0]);
			}
			have_t = 1;
			break;
		default:
			return usage(argv[0]);
		}
	}
	if (modes != 1 || optind != argc
	    || (outp != NULL && strlen(outp) > PREFIX_MAX)
	    || (prefix != NULL && strlen(prefix) > PREFIX_MAX)) {
		return usage(argv[0]);
	}

	switch (mode) {
	case 'i':
		return have_n ? census(n) : usage(argv[0]);
	case 'b':
		return (have_c && outp != NULL) ? busy_worker(cpu, secs, outp) : usage(argv[0]);
	case 'R':
		return (have_t && prefix != NULL) ? collect_ready(n, prefix, tmo) : usage(argv[0]);
	case 'c':
		return (have_t && prefix != NULL) ? collect_done(n, prefix, tmo) : usage(argv[0]);
	case 'k':
		return have_n ? trace_count(file, n) : usage(argv[0]);
	case 'z':
		return drain_sleep(secs);
	default:
		return usage(argv[0]);
	}
}
