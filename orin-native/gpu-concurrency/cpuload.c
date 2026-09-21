/* cpuload.c v2 — the CPU-side control for the interference experiment.
 *
 * v1 was wrong and would have produced a misleading arm: `y = y*x + c` with
 * x > 1 overflows to +inf within a few thousand iterations, and once y is inf
 * every later multiply is a trivial special case the FPU disposes of without
 * the pipeline pressure a real FP workload creates. The arm was designed as a
 * faithful CPU twin of fma.cu's driver thread, so it must stay in normal range.
 *
 * THAT DESIGN PREMISE IS FALSE (measured 2026-09-21). fma.cu's host thread does
 * not keep a core busy: it blocks in cudaDeviceSynchronize, and during all 12
 * interference gpu arms no core exceeded 1% CPU while the GPU sat at 99%. So
 * this program is not a twin of anything in the gpu arm -- it is "one busy core",
 * a legitimate arm in its own right but not a control that separates "GPU busy"
 * from "system busy". The burn loop below is unchanged from v2 and still correct
 * for what it does; the argument handling and the pinning around it were added
 * on 2026-09-21 (next paragraph).
 *
 * This keeps the value bounded by construction: an FMA chain that decays back
 * toward a fixed point instead of growing. Verified by printing the sink, which
 * must be finite.
 *
 * usage: cpuload SECS NTHREADS [CORES]
 *
 * CORES (added 2026-09-21) pins thread i to the i-th core of a comma-separated
 * list, e.g. "0,1". An independent analysis of the first Orin campaign found
 * that WHERE the scheduler put unpinned threads decided the result more than how
 * many there were: one thread cost ~0 on core 3 and up to ~+50 us on core 2, and
 * four threads with two of them on QEMU's cores cost more than six on all six in
 * most such rounds (12 of 17, across both idle-state runs). Placement was read
 * from one sample before each probe, so that is a correlation. An arm named by
 * thread count alone was a placement lottery. With CORES, placement is the
 * variable, fixed and stated.
 *
 * The affinity is set at CREATION (pthread_attr_setaffinity_np), so a thread
 * never runs anywhere else even for its first instructions, and then READ BACK
 * per thread. If any thread did not land exactly where asked, the program exits
 * non-zero within milliseconds -- the threads already created spin until then,
 * but the harness's liveness check comes 3 s later and sees the process gone.
 * A "pinned" arm that silently was not is
 * the failure shape this whole toolchain exists to refuse. The list must name
 * exactly NTHREADS cores: no cycling, no guessing what was meant.
 */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <math.h>
#include <time.h>

static volatile double g_sink;
static volatile int g_stop;

static void *burn(void *arg)
{
	(void)arg;
	double y = 0.5;
	while (!g_stop) {
		for (int i = 0; i < 100000; i++) {
			y = y * 0.9999999 + 0.0000001;   /* contracts; stays near 1e-3..1 */
		}
		if (!isfinite(y) || y < 1e-9) y = 0.5; /* never degenerate to 0 or inf */
		g_sink = y;
	}
	return NULL;
}

/* Parse "0,1,5" into cores[]; returns the count, or -1 on any malformed entry.
 * Written by hand, not with strtok: strtok collapses empty fields, so "0,,1"
 * and "0,1," would have been read as "0,1" -- a typo quietly becoming a
 * placement. Every entry must start with a digit and end at a comma or the end. */
static int parse_cores(const char *s, int *cores, int max, long ncpu)
{
	int n = 0;
	const char *p = s;
	for (;;) {
		char *end;
		long c;
		if (*p < '0' || *p > '9') return -1;   /* empty entry, sign, space or junk */
		c = strtol(p, &end, 10);
		if (c >= ncpu || n >= max) return -1;
		cores[n++] = (int)c;
		if (*end == '\0') return n;
		if (*end != ',') return -1;
		p = end + 1;
	}
}

int main(int argc, char **argv)
{
	int secs = (argc > 1) ? atoi(argv[1]) : 30;
	int nthr = (argc > 2) ? atoi(argv[2]) : 1;
	if (nthr < 1) nthr = 1;
	pthread_t *t = calloc((size_t)nthr, sizeof(*t));
	int *cores = calloc((size_t)nthr, sizeof(*cores));
	if (!t || !cores) return 1;
	int pinned = (argc > 3);
	long ncpu = sysconf(_SC_NPROCESSORS_CONF);

	if (pinned) {
		int got = parse_cores(argv[3], cores, nthr, ncpu);
		if (got != nthr) {
			fprintf(stderr, "cpuload: FATAL CORES '%s' must name exactly %d valid core(s) of %ld\n",
				argv[3], nthr, ncpu);
			return 2;
		}
	}
	printf("cpuload: %d thread(s) for %d s (no GPU, no memory streaming), %s\n",
	       nthr, secs, pinned ? "PINNED" : "unpinned");
	fflush(stdout);

	for (int i = 0; i < nthr; i++) {
		pthread_attr_t attr;
		pthread_attr_init(&attr);
		if (pinned) {
			cpu_set_t set;
			CPU_ZERO(&set);
			CPU_SET(cores[i], &set);
			if (pthread_attr_setaffinity_np(&attr, sizeof(set), &set) != 0) {
				fprintf(stderr, "cpuload: FATAL could not set affinity for thread %d -> core %d\n", i, cores[i]);
				g_stop = 1;
				return 2;
			}
		}
		if (pthread_create(&t[i], &attr, burn, NULL) != 0) {
			fprintf(stderr, "cpuload: FATAL pthread_create failed for thread %d\n", i);
			g_stop = 1;
			return 2;
		}
		pthread_attr_destroy(&attr);
	}

	/* Read back every thread's affinity. "Asked for" is not "got". */
	if (pinned) {
		for (int i = 0; i < nthr; i++) {
			cpu_set_t got;
			CPU_ZERO(&got);
			if (pthread_getaffinity_np(t[i], sizeof(got), &got) != 0
			    || CPU_COUNT(&got) != 1 || !CPU_ISSET(cores[i], &got)) {
				fprintf(stderr, "cpuload: FATAL thread %d affinity did not read back as core %d only\n",
					i, cores[i]);
				g_stop = 1;
				for (int j = 0; j < nthr; j++) pthread_join(t[j], NULL);
				return 2;
			}
			printf("cpuload: thread %d pinned to core %d (verified)\n", i, cores[i]);
		}
		fflush(stdout);
	}
	struct timespec ts = { .tv_sec = secs, .tv_nsec = 0 };
	nanosleep(&ts, NULL);
	g_stop = 1;
	for (int i = 0; i < nthr; i++) pthread_join(t[i], NULL);
	free(t);
	free(cores);
	printf("cpuload: done (sink=%g, finite=%d)\n", g_sink, isfinite(g_sink));
	return 0;
}
