/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * clkcmp — ClockCycles() against CLOCK_MONOTONIC, bracketed, pinned, repeated.
 *
 * Phase 3b, checklist 7b (docs/orin-native-port-plan.md:550): the M4 dry run's
 * clock comparison, specified in results/orin-native-port/20260909T1100Z/
 * m4-dryrun-design.md §1.4 and §5.1 (revision 2). The plan asks for
 * ClockCycles() against clock_gettime() over one second. A single pair of reads
 * cannot tell a clock disagreement from a preemption between the two calls, so
 * every counter read here sits between two monotonic reads, and the width of
 * that bracket bounds how far apart the two clocks' readings can be.
 *
 *   clkcmp [-n REPS] [-i MS] [-w NS]
 *   clkcmp -e SECS
 *
 * One sample:
 *
 *   bracket A on cpuA:  m0 = CLOCK_MONOTONIC, c0 = ClockCycles(), m1 = CLOCK_MONOTONIC
 *   clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME) to m1 + MS
 *   bracket B on cpuB:  m2, c1, m3 the same way
 *
 * With cps the system page's cycles_per_sec, in unsigned 64-bit arithmetic:
 *
 *   cc_ns     = (c1 - c0) * 10^9 / cps            the product in 128 bits
 *   mono_ns   = mid(m2, m3) - mid(m0, m1)         mid(a, b) = a/2 + b/2 + (a%2 + b%2)/2
 *   err_ns    = cc_ns - mono_ns                   signed
 *   wA = m1 - m0, wB = m3 - m2, q = ceil(10^9 / cps)
 *   tol_ns    = mid(wA, wB) + 4q                  strict when |err_ns| <= tol_ns
 *   tolres_ns = tol_ns + 2 * clock_getres(CLOCK_MONOTONIC)
 *                                                 res when |err_ns| <= tolres_ns
 *
 * The counter read lies inside its bracket, so each mid-point estimate is off
 * by at most half its bracket, plus a quantum or so of reading resolution.
 *
 * A sample is usable when both brackets ran wholly on their intended CPU
 * (SchedGetCpuNum() just before and just after each bracket, why=migrated
 * otherwise) and wA and wB are each at most NS (why=wide). The thread is pinned
 * with _NTO_TCTL_RUNMASK before each bracket. Bracket B's pin is set before the
 * sleep, so the thread wakes on cpuB; a pin that has not moved the thread yet
 * gets one 1 ms nap before the bracket, never a busy-wait.
 *
 * Modes, REPS samples each: same0 (both brackets on cpu 0), same1 (both on
 * cpu 1) and cross (A on cpu 0, B on cpu 1). cross tests the claim that the
 * counter is synchronised across processors ([clockcycles]), which matters
 * because a vCPU's at_entry and at_exit may be read on different CPUs. With one
 * CPU, same1 and cross are skipped with a CLK SKIP line. Defaults: REPS 5,
 * MS 1000, NS 1000000.
 *
 * Per mode, the first rule that matches (m4-dryrun-design.md §1.4):
 *
 *   disagree                 a usable sample is outside its resolution bound
 *   unusable                 fewer than 3 usable samples
 *   agree                    every usable sample is strict
 *   agree-within-resolution  otherwise
 *
 * Output, one line per sample and one per mode (CLK S is one line):
 *
 *   CLK HDR cps=<u64> ncpu=<n> reps=<r> interval_ms=<i> wide_ns=<w> res_ns=<u64>
 *   CLK S mode=<m> rep=<k> cpuA=<a> cpuB=<b> c0= c1= m0= m1= m2= m3= cc_ns= mono_ns=
 *         err_ns= wA= wB= tol_ns= tolres_ns= usable=<0|1> strict=<0|1> res=<0|1>
 *         why=<ok|wide|migrated>
 *   CLK VERDICT mode=<m> usable=<n> strict=<n> res=<n> result=<verdict>
 *
 * strict= and res= on the VERDICT line count usable samples only.
 *
 * -e SECS is the coarse external reference. Pinned to cpu 0 it prints
 *
 *   CLK EXT start c=<u64> mono_ns=<u64> cps=<u64>
 *
 * sleeps to SECS monotonic seconds after that reading and prints
 *
 *   CLK EXT end c=<u64> mono_ns=<u64> dcc=<u64> dmono_ns=<u64>
 *
 * flushing each line, so the launcher on the PC can timestamp both as they
 * appear in the serial file.
 *
 * What it deliberately does not do: no busy-wait, no averaging, and no judgement
 * about real time. QNX derives system time from this counter at this
 * cycles_per_sec, so agreement is a self-consistency check, not a calibration.
 * There is no Tegra-specific code: the board M4 image can carry it unchanged.
 *
 * Exit: 0 when every mode that ran agrees (strictly or within resolution), 1
 * when any mode disagrees, 3 when any mode is unusable and none disagrees, 2 on
 * a malformed command line. -e exits 0. A zero cycles_per_sec prints
 * "CLK ERROR cps=0" and exits 1, as does a failing clock call.
 */

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

#define NS_PER_S        1000000000u
#define MIN_USABLE      3u
#define MAX_REPS        100ul
#define MAX_INTERVAL_MS 60000ul
#define MAX_WIDE_NS     1000000000ul
#define MAX_EXT_SECS    3600ul
#define SETTLE_NS       1000000L        /* the one nap a pin that has not moved us gets */

struct bracket {
	uint64_t lo;            /* CLOCK_MONOTONIC just before the counter read, ns */
	uint64_t c;             /* ClockCycles() */
	uint64_t hi;            /* CLOCK_MONOTONIC just after it, ns */
	int      on_cpu;        /* the whole bracket ran on the intended CPU */
};

struct mode {
	const char *name;
	unsigned    cpu_a;
	unsigned    cpu_b;
};

struct tally {
	unsigned usable;
	unsigned strict;        /* usable and strict */
	unsigned res;           /* usable and within resolution */
	unsigned outside;       /* usable and outside the resolution bound */
};

static const struct mode modes[] = {
	{ "same0", 0u, 0u },
	{ "same1", 1u, 1u },
	{ "cross", 0u, 1u },
};

static uint64_t cps;

static void
die(const char *const what, int const err)
{
	printf("CLK ERROR %s errno=%d\n", what, err);
	fflush(stdout);
	exit(1);
}

static uint64_t
mono_now(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts) == -1) {
		die("clock_gettime", errno);
	}
	return (uint64_t)ts.tv_sec * NS_PER_S + (uint64_t)ts.tv_nsec;
}

/* floor((a + b) / 2) without overflow */
static uint64_t
mid(uint64_t const a, uint64_t const b)
{
	return a / 2u + b / 2u + (a % 2u + b % 2u) / 2u;
}

static void
sleep_until(uint64_t const t)
{
	struct timespec const ts = {
		.tv_sec  = (time_t)(t / NS_PER_S),
		.tv_nsec = (long)(t % NS_PER_S),
	};
	int rc;

	do {
		rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
		if (rc == -1) {
			rc = errno;
		}
	} while (rc == EINTR);
	if (rc != 0) {
		die("clock_nanosleep", rc);
	}
}

/*
 * Pin the calling thread. _NTO_TCTL_RUNMASK takes the mask itself as the data
 * argument (sys/neutrino.h:432). A failed pin is only noted: the CPU checks
 * around each bracket decide whether the sample is usable.
 */
static void
pin(unsigned const cpu)
{
	if (ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)(1u << cpu)) == -1) {
		printf("CLK NOTE pin cpu=%u errno=%d\n", cpu, errno);
		fflush(stdout);
		return;
	}
	if (SchedGetCpuNum() != cpu) {
		struct timespec const ts = { .tv_sec = 0, .tv_nsec = SETTLE_NS };

		(void)nanosleep(&ts, NULL);
	}
}

static void
take(struct bracket *const b, unsigned const cpu)
{
	unsigned const before = SchedGetCpuNum();

	b->lo     = mono_now();
	b->c      = ClockCycles();
	b->hi     = mono_now();
	b->on_cpu = (before == cpu) && (SchedGetCpuNum() == cpu);
}

static void
sample(const struct mode *const md, unsigned long const rep, uint64_t const interval_ns,
       uint64_t const wide_ns, uint64_t const res_ns, struct tally *const t)
{
	struct bracket a;
	struct bracket b;

	pin(md->cpu_a);
	take(&a, md->cpu_a);
	pin(md->cpu_b);
	sleep_until(a.hi + interval_ns);
	take(&b, md->cpu_b);

	uint64_t const cc_ns   = (uint64_t)((unsigned __int128)(b.c - a.c) * NS_PER_S / cps);
	uint64_t const mono_ns = mid(b.lo, b.hi) - mid(a.lo, a.hi);
	__int128 const diff    = (__int128)cc_ns - (__int128)mono_ns;
	int64_t const  err_ns  = (diff > INT64_MAX) ? INT64_MAX : (diff < INT64_MIN) ? INT64_MIN : (int64_t)diff;
	uint64_t const abs_err = (diff < 0) ? (uint64_t)(-diff) : (uint64_t)diff;
	uint64_t const wa      = a.hi - a.lo;
	uint64_t const wb      = b.hi - b.lo;
	uint64_t const q       = (NS_PER_S + cps - 1u) / cps;
	uint64_t const tol     = mid(wa, wb) + 4u * q;
	uint64_t const tolres  = tol + 2u * res_ns;
	int const      on_cpu  = a.on_cpu && b.on_cpu;
	int const      usable  = on_cpu && wa <= wide_ns && wb <= wide_ns;
	int const      strict  = abs_err <= tol;
	int const      res     = abs_err <= tolres;
	const char    *why     = "ok";

	if (!on_cpu) {
		why = "migrated";
	} else if (!usable) {
		why = "wide";
	}

	printf("CLK S mode=%s rep=%lu cpuA=%u cpuB=%u c0=%" PRIu64 " c1=%" PRIu64
	       " m0=%" PRIu64 " m1=%" PRIu64 " m2=%" PRIu64 " m3=%" PRIu64
	       " cc_ns=%" PRIu64 " mono_ns=%" PRIu64 " err_ns=%" PRId64
	       " wA=%" PRIu64 " wB=%" PRIu64 " tol_ns=%" PRIu64 " tolres_ns=%" PRIu64
	       " usable=%d strict=%d res=%d why=%s\n",
	       md->name, rep, md->cpu_a, md->cpu_b, a.c, b.c, a.lo, a.hi, b.lo, b.hi,
	       cc_ns, mono_ns, err_ns, wa, wb, tol, tolres, usable, strict, res, why);
	fflush(stdout);

	if (usable) {
		t->usable++;
		t->strict += (unsigned)strict;
		t->res += (unsigned)res;
		t->outside += (unsigned)!res;
	}
}

static int
compare(unsigned long const reps, unsigned long const interval_ms, unsigned long const wide_ns)
{
	unsigned const  ncpu = _syspage_ptr->num_cpu;
	struct timespec rs;
	uint64_t        res_ns;
	int             any_disagree = 0;
	int             any_unusable = 0;

	if (clock_getres(CLOCK_MONOTONIC, &rs) == -1) {
		die("clock_getres", errno);
	}
	res_ns = (uint64_t)rs.tv_sec * NS_PER_S + (uint64_t)rs.tv_nsec;
	printf("CLK HDR cps=%" PRIu64 " ncpu=%u reps=%lu interval_ms=%lu wide_ns=%lu res_ns=%" PRIu64 "\n",
	       cps, ncpu, reps, interval_ms, wide_ns, res_ns);
	fflush(stdout);

	for (size_t m = 0; m < sizeof(modes) / sizeof(modes[0]); m++) {
		const struct mode *const md = &modes[m];
		struct tally             t;
		const char              *result;

		if (md->cpu_a >= ncpu || md->cpu_b >= ncpu) {
			printf("CLK SKIP mode=%s ncpu=%u\n", md->name, ncpu);
			fflush(stdout);
			continue;
		}
		memset(&t, 0, sizeof(t));
		for (unsigned long r = 1ul; r <= reps; r++) {
			sample(md, r, (uint64_t)interval_ms * 1000000u, (uint64_t)wide_ns, res_ns, &t);
		}
		if (t.outside > 0u) {
			result       = "disagree";
			any_disagree = 1;
		} else if (t.usable < MIN_USABLE) {
			result       = "unusable";
			any_unusable = 1;
		} else if (t.strict == t.usable) {
			result = "agree";
		} else {
			result = "agree-within-resolution";
		}
		printf("CLK VERDICT mode=%s usable=%u strict=%u res=%u result=%s\n",
		       md->name, t.usable, t.strict, t.res, result);
		fflush(stdout);
	}
	return any_disagree ? 1 : (any_unusable ? 3 : 0);
}

static int
external(uint64_t const secs)
{
	uint64_t c0;
	uint64_t m0;
	uint64_t c1;
	uint64_t m1;

	pin(0u);
	c0 = ClockCycles();
	m0 = mono_now();
	printf("CLK EXT start c=%" PRIu64 " mono_ns=%" PRIu64 " cps=%" PRIu64 "\n", c0, m0, cps);
	fflush(stdout);
	sleep_until(m0 + secs * NS_PER_S);
	c1 = ClockCycles();
	m1 = mono_now();
	printf("CLK EXT end c=%" PRIu64 " mono_ns=%" PRIu64 " dcc=%" PRIu64 " dmono_ns=%" PRIu64 "\n",
	       c1, m1, c1 - c0, m1 - m0);
	fflush(stdout);
	return 0;
}

static int
usage(void)
{
	fprintf(stderr,
	        "usage: clkcmp [-n REPS] [-i MS] [-w NS]\n"
	        "       clkcmp -e SECS\n"
	        "  REPS 1-%lu (5), MS 1-%lu (1000), NS 1-%lu (1000000), SECS 1-%lu\n"
	        "  exit: 0 agree, 1 disagree, 3 unusable, 2 usage\n",
	        MAX_REPS, MAX_INTERVAL_MS, MAX_WIDE_NS, MAX_EXT_SECS);
	return 2;
}

static int
parse_ul(const char *const s, unsigned long const hi, unsigned long *const v)
{
	char         *end = NULL;
	unsigned long x;

	if (s[0] < '0' || s[0] > '9') {
		return 0;
	}
	errno = 0;
	x = strtoul(s, &end, 10);
	if (errno != 0 || *end != '\0' || x < 1ul || x > hi) {
		return 0;
	}
	*v = x;
	return 1;
}

int
main(int argc, char **argv)
{
	unsigned long reps        = 5ul;
	unsigned long interval_ms = 1000ul;
	unsigned long wide_ns     = 1000000ul;
	unsigned long ext_secs    = 0ul;
	int           have_n = 0, have_i = 0, have_w = 0, have_e = 0;

	for (int i = 1; i < argc; i++) {
		const char *const a   = argv[i];
		int const         val = (i + 1 < argc);

		if (val && strcmp(a, "-n") == 0 && !have_n) {
			if (!parse_ul(argv[++i], MAX_REPS, &reps)) {
				return usage();
			}
			have_n = 1;
		} else if (val && strcmp(a, "-i") == 0 && !have_i) {
			if (!parse_ul(argv[++i], MAX_INTERVAL_MS, &interval_ms)) {
				return usage();
			}
			have_i = 1;
		} else if (val && strcmp(a, "-w") == 0 && !have_w) {
			if (!parse_ul(argv[++i], MAX_WIDE_NS, &wide_ns)) {
				return usage();
			}
			have_w = 1;
		} else if (val && strcmp(a, "-e") == 0 && !have_e) {
			if (!parse_ul(argv[++i], MAX_EXT_SECS, &ext_secs)) {
				return usage();
			}
			have_e = 1;
		} else {
			return usage();
		}
	}
	if (have_e && (have_n || have_i || have_w)) {
		return usage();
	}

	cps = (uint64_t)SYSPAGE_ENTRY(qtime)->cycles_per_sec;
	if (cps == 0u) {
		printf("CLK ERROR cps=0\n");
		fflush(stdout);
		return 1;
	}
	if (have_e) {
		return external((uint64_t)ext_secs);
	}
	return compare(reps, interval_ms, wide_ns);
}
