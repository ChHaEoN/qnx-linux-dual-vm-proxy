/* cpuload.c v2 — the CPU-side control for the interference experiment.
 *
 * v1 was wrong and would have produced a misleading arm: `y = y*x + c` with
 * x > 1 overflows to +inf within a few thousand iterations, and once y is inf
 * every later multiply is a trivial special case the FPU disposes of without
 * the pipeline pressure a real FP workload creates. The arm exists to be a
 * faithful CPU twin of fma.cu's driver thread, so it must stay in normal range.
 *
 * This keeps the value bounded by construction: an FMA chain that decays back
 * toward a fixed point instead of growing. Verified by printing the sink, which
 * must be finite.
 */
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
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

int main(int argc, char **argv)
{
	int secs = (argc > 1) ? atoi(argv[1]) : 30;
	int nthr = (argc > 2) ? atoi(argv[2]) : 1;
	if (nthr < 1) nthr = 1;
	pthread_t *t = calloc((size_t)nthr, sizeof(*t));
	if (!t) return 1;
	printf("cpuload: %d thread(s) for %d s (no GPU, no memory streaming)\n", nthr, secs);
	fflush(stdout);
	for (int i = 0; i < nthr; i++) pthread_create(&t[i], NULL, burn, NULL);
	struct timespec ts = { .tv_sec = secs, .tv_nsec = 0 };
	nanosleep(&ts, NULL);
	g_stop = 1;
	for (int i = 0; i < nthr; i++) pthread_join(t[i], NULL);
	free(t);
	printf("cpuload: done (sink=%g, finite=%d)\n", g_sink, isfinite(g_sink));
	return 0;
}
