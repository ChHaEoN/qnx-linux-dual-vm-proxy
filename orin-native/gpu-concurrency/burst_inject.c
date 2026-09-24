/*
 * burst_inject.c -- run-bursts.sh's injector (Phase 3b / A6, 2026-09-24). Run as root,
 * pinned to the aux core, while a probe round runs. At seeded, jittered times it does one
 * of six things, each marked in the ftrace marker just before ("tjinj KIND I"):
 *
 *   U  three "change" writes to the thermal zone's uevent file (the uevents; control)
 *   N  nothing (the null control)
 *   C  compute for BURST_MS: a register-only xorshift loop, no memory traffic
 *   M  memory for BURST_MS: 1 MB memcpy's cycling through a 64 MB buffer touched at start
 *   T  TLB maintenance for BURST_MS: mmap 64 KB anonymous, touch one page, munmap, again
 *      (each munmap flushes the range, which arm64 broadcasts to every core)
 *   S  syscalls for BURST_MS: getppid() in a loop, no memory-map change
 *
 * Nothing is allocated, forked or mapped between the start and the end of the run except
 * by T itself. One JSON line per injection goes to the log: its index, kind, CLOCK_MONOTONIC
 * ns at the marker, the uevent seqnum before and after, the action's duration (us) and its
 * iteration count. Build: gcc -O2 -o burst_inject burst_inject.c
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define MAXK 32
#define BUF (64u << 20)
#define CHUNK (1u << 20)

static uint64_t rng_state;

static uint64_t rng(void)
{
	rng_state ^= rng_state << 13;
	rng_state ^= rng_state >> 7;
	rng_state ^= rng_state << 17;
	return rng_state;
}

static double urand(void) { return (double)(rng() >> 11) / (double)(1ull << 53); }

static int64_t now_ns(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return (int64_t)t.tv_sec * 1000000000ll + t.tv_nsec;
}

static long read_seq(const char *p)
{
	char b[64];
	long v = -1;
	int fd = open(p, O_RDONLY);
	if (fd >= 0) {
		ssize_t n = read(fd, b, sizeof b - 1);
		if (n > 0) {
			b[n] = 0;
			v = strtol(b, NULL, 10);
		}
		close(fd);
	}
	return v;
}

static volatile uint64_t sink;

static long act(char k, const char *uevent, int64_t burst_ns, unsigned char *buf)
{
	long it = 0;
	int64_t end = now_ns() + burst_ns;
	if (k == 'U') {
		for (int i = 0; i < 3; i++) {
			int fd = open(uevent, O_WRONLY);
			if (fd < 0 || write(fd, "change", 6) != 6)
				return -1;
			close(fd);
			it++;
		}
	} else if (k == 'C') {
		uint64_t x = 88172645463325252ull;
		do {
			for (int i = 0; i < 4096; i++) {
				x ^= x << 13;
				x ^= x >> 7;
				x ^= x << 17;
			}
			it += 4096;
		} while (now_ns() < end);
		sink = x;
	} else if (k == 'M') {
		size_t off = 0, half = BUF / 2;
		do {
			memcpy(buf + half + off, buf + off, CHUNK);
			off = (off + CHUNK) % half;
			it++;
		} while (now_ns() < end);
	} else if (k == 'T') {
		do {
			for (int i = 0; i < 16; i++) {
				volatile char *p = mmap(NULL, 65536, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
				if (p == MAP_FAILED)
					return -1;
				p[0] = 1;
				munmap((void *)p, 65536);
			}
			it += 16;
		} while (now_ns() < end);
	} else if (k == 'S') {
		do {
			for (int i = 0; i < 256; i++)
				sink += (uint64_t)syscall(SYS_getppid);
			it += 256;
		} while (now_ns() < end);
	}
	return it;
}

int main(int argc, char **argv)
{
	const char *zone = NULL, *marker = NULL, *logp = NULL, *seqp = "/sys/kernel/uevent_seqnum";
	char kinds[MAXK] = "UNCMTS";
	double start = 0.75, step = 0.3, jitter = 0.1, burst_ms = 3.0;
	long seed = 1;
	for (int i = 1; i + 1 < argc; i += 2) {
		if (!strcmp(argv[i], "--zone")) zone = argv[i + 1];
		else if (!strcmp(argv[i], "--marker")) marker = argv[i + 1];
		else if (!strcmp(argv[i], "--log")) logp = argv[i + 1];
		else if (!strcmp(argv[i], "--seqnum")) seqp = argv[i + 1];
		else if (!strcmp(argv[i], "--seed")) seed = atol(argv[i + 1]);
		else if (!strcmp(argv[i], "--start")) start = atof(argv[i + 1]);
		else if (!strcmp(argv[i], "--step")) step = atof(argv[i + 1]);
		else if (!strcmp(argv[i], "--jitter")) jitter = atof(argv[i + 1]);
		else if (!strcmp(argv[i], "--burst-ms")) burst_ms = atof(argv[i + 1]);
		else if (!strcmp(argv[i], "--kinds")) {
			size_t j = 0;
			for (const char *c = argv[i + 1]; *c && j < MAXK - 1; c++)
				if (*c != ',')
					kinds[j++] = *c;
			kinds[j] = 0;
		} else {
			fprintf(stderr, "burst_inject: unknown option %s\n", argv[i]);
			return 2;
		}
	}
	if (!zone || !marker || !logp) {
		fprintf(stderr, "usage: burst_inject --zone DIR --marker FILE --log FILE --seed N [--kinds UNCMTS] "
				"[--start S] [--step S] [--jitter S] [--burst-ms MS] [--seqnum FILE]\n");
		return 2;
	}
	size_t nk = strlen(kinds);
	for (size_t i = 0; i < nk; i++)
		if (!strchr("UNCMTS", kinds[i])) {
			fprintf(stderr, "burst_inject: unknown kind %c\n", kinds[i]);
			return 2;
		}
	rng_state = 0x9E3779B97F4A7C15ull ^ (uint64_t)seed;
	for (int i = 0; i < 8; i++)
		rng();
	for (size_t i = nk - 1; i > 0; i--) {             /* Fisher-Yates */
		size_t j = (size_t)(rng() % (i + 1));
		char t = kinds[i];
		kinds[i] = kinds[j];
		kinds[j] = t;
	}
	int64_t offs[MAXK];
	for (size_t i = 0; i < nk; i++)
		offs[i] = (int64_t)((start + step * (double)i + jitter * urand()) * 1e9);
	unsigned char *buf = malloc(BUF);
	if (!buf) {
		fprintf(stderr, "burst_inject: no memory\n");
		return 1;
	}
	memset(buf, 1, BUF);                               /* touched now, not during a burst */
	char uevent[512];
	snprintf(uevent, sizeof uevent, "%s/uevent", zone);
	int mfd = open(marker, O_WRONLY | O_APPEND);
	FILE *log = fopen(logp, "w");
	if (mfd < 0 || !log) {
		fprintf(stderr, "burst_inject: cannot open the marker or the log\n");
		return 1;
	}
	int64_t t0 = now_ns();
	for (size_t i = 0; i < nk; i++) {
		struct timespec ts;
		int64_t at = t0 + offs[i];
		ts.tv_sec = at / 1000000000ll;
		ts.tv_nsec = at % 1000000000ll;
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
		long s0 = read_seq(seqp);
		char m[64];
		int ml = snprintf(m, sizeof m, "tjinj %c %zu\n", kinds[i], i);
		if (write(mfd, m, (size_t)ml) != ml) {
			fprintf(stderr, "burst_inject: marker write failed\n");
			return 1;
		}
		int64_t t = now_ns();
		long it = act(kinds[i], uevent, (int64_t)(burst_ms * 1e6), buf);
		double dur = (double)(now_ns() - t) / 1000.0;
		long s1 = read_seq(seqp);
		if (it < 0) {
			fprintf(stderr, "burst_inject: action %c failed\n", kinds[i]);
			return 1;
		}
		fprintf(log, "{\"i\": %zu, \"kind\": \"%c\", \"t_ns\": %lld, \"seq_before\": %ld, \"seq_after\": %ld, "
			     "\"dur_us\": %.1f, \"iters\": %ld}\n", i, kinds[i], (long long)t, s0, s1, dur, it);
		fflush(log);
	}
	fclose(log);
	close(mfd);
	return 0;
}
