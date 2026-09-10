/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * bwait — bounded waits for a script that nobody can rescue.
 *
 * Phase 3b, the M3 design's §3.8.2 (results/orin-native-port/20260909T1100Z/
 * m3-design.md, revision 2). The M3 host script runs from an IFS on a board
 * whose watchdog does not fire after the kexec hand-over: a wait that never
 * returns costs a power cycle and the black box with it. Every wait in that
 * script is one of these.
 *
 *   bwait -p PATH [-p PATH]... -t SECS
 *       Poll stat() on each PATH every 50 ms; the first that exists wins.
 *       One line at the end: "BWAIT path hit=<path> ms=<n>" (exit 0) or
 *       "BWAIT path timeout secs=<S> ms=<n> first=<first path>" (exit 1).
 *
 *   bwait -k SECS [-r FILE] [-o OUT] [-e ERR] -- PROG [ARG...]
 *       posix_spawn PROG (a path, no PATH search) with stdin /dev/null and
 *       stdout/stderr to OUT/ERR (truncated; /dev/null by default). Poll
 *       waitpid every 50 ms; at SECS send SIGKILL and poll up to 5 s more.
 *       One line, to stdout and appended to FILE:
 *       "BWAIT run prog=<basename> rc=<status|-1> sig=<n|0> killed=<0|1> ms=<n>".
 *       Exit: the child's status if it exited, 124 if killed, 128+sig if it
 *       died of a signal on its own, 125 if it could not be spawned
 *       ("BWAIT run prog=<basename> spawn-failed errno=<n>") or supervised.
 *
 *   bwait -s SECS -c PATH
 *       Silent. Sleep SECS, then create PATH. Exit 0, or 1 if PATH could not
 *       be created.
 *
 *   bwait -g SECS
 *       The guard. Raise itself to SCHED_RR priority 50, print
 *       "BWAIT guard armed secs=<S> prio=<50|err<n>>", sleep SECS, print
 *       "BWAIT guard deadline=<S> expired: sysmgr_reboot" and call
 *       sysmgr_reboot(). If that returns: "BWAIT guard sysmgr_reboot returned
 *       errno=<n>", posix_spawn /proc/boot/shutdown -S reboot, and after 30 s
 *       "BWAIT guard still alive", exit 1.
 *
 * Every deadline is ClockCycles() against the system page's cycles_per_sec.
 * Sleeps are nanosleep, at most 50 ms (-p, -k) or 1 s (-s, -g) at a time,
 * re-checked against the counter after each, so a sleep that runs slow against
 * the counter cannot stretch a bound by more than one nap. The census that runs
 * before this program proves cpu 0's tick in the same boot.
 *
 * Exit 2 on a malformed command line.
 */

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <spawn.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/stat.h>
#include <sys/syspage.h>
#include <sys/sysmgr.h>
#include <sys/types.h>
#include <sys/wait.h>

extern char **environ;

#define POLL_MS         50u
#define NAP_MS          1000u
#define KILL_GRACE_S    5u
#define GUARD_PRIO      50
#define GUARD_TAIL_S    30u
#define MAX_SECS        86400u
#define MAX_PATHS       8
#define LINE_BUF        1024

static uint64_t cps;

static void say(const char *fmt, ...) __attribute__((__format__(__printf__, 1, 2)));

/* One complete line, one write, to stdout: the console is the record. */
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

static uint64_t
cycles_to_ms(uint64_t const d)
{
	return d / cps * 1000u + (d % cps) * 1000u / cps;
}

static uint64_t
ms_since(uint64_t const t0)
{
	return cycles_to_ms(ClockCycles() - t0);
}

/* Sleep toward the deadline, at most max_ms; the caller re-checks the counter. */
static void
nap_toward(uint64_t const deadline, unsigned const max_ms)
{
	uint64_t const now = ClockCycles();
	uint64_t       ms;
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

static const char *
base_name(const char *const p)
{
	const char *const s = strrchr(p, '/');

	return (s != NULL && s[1] != '\0') ? s + 1 : p;
}

static int
usage(void)
{
	fprintf(stderr,
	        "usage: bwait -p PATH [-p PATH]... -t SECS\n"
	        "       bwait -k SECS [-r FILE] [-o OUT] [-e ERR] -- PROG [ARG...]\n"
	        "       bwait -s SECS -c PATH\n"
	        "       bwait -g SECS\n"
	        "  SECS is 0-86400 for -p and -s, 1-86400 for -k and -g; PROG is a path\n"
	        "  exit: -p 0 hit, 1 timeout; -k child status, 124 killed, 125 spawn failure;\n"
	        "        2 usage\n");
	return 2;
}

static int
parse_secs(const char *const s, unsigned const lo, unsigned *const v)
{
	char         *end = NULL;
	unsigned long x;

	if (s[0] < '0' || s[0] > '9') {
		return 0;
	}
	errno = 0;
	x = strtoul(s, &end, 10);
	if (errno != 0 || *end != '\0' || x < lo || x > MAX_SECS) {
		return 0;
	}
	*v = (unsigned)x;
	return 1;
}

static int
wait_paths(const char *const *const paths, int const npaths, unsigned const secs)
{
	uint64_t const t0       = ClockCycles();
	uint64_t const deadline = t0 + (uint64_t)secs * cps;
	struct stat    sb;

	for (;;) {
		for (int i = 0; i < npaths; i++) {
			if (stat(paths[i], &sb) == 0) {
				say("BWAIT path hit=%s ms=%llu\n", paths[i], (unsigned long long)ms_since(t0));
				return 0;
			}
		}
		if (ClockCycles() >= deadline) {
			say("BWAIT path timeout secs=%u ms=%llu first=%s\n", secs,
			    (unsigned long long)ms_since(t0), paths[0]);
			return 1;
		}
		nap_toward(deadline, POLL_MS);
	}
}

static void
report_run(const char *const rec, const char *const line)
{
	say("%s", line);
	if (rec != NULL) {
		int const fd = open(rec, O_WRONLY | O_CREAT | O_APPEND, 0644);

		if (fd >= 0) {
			ssize_t w;

			do {
				w = write(fd, line, strlen(line));
			} while (w < 0 && errno == EINTR);
			(void)close(fd);
		}
	}
}

static int
run_bounded(unsigned const secs, const char *const rec, const char *const out, const char *const err,
            char **const pargv)
{
	char const                *prog = base_name(pargv[0]);
	char                       line[LINE_BUF];
	posix_spawn_file_actions_t fa;
	pid_t                      pid;
	int                        fds[3];
	int                        rc;
	int                        st       = 0;
	int                        reaped   = 0;
	int                        killed   = 0;
	int                        wait_err = 0;
	uint64_t                   t0;
	uint64_t                   deadline;

	/* An inherited SIG_IGN would have the child reaped behind waitpid's back. */
	(void)signal(SIGCHLD, SIG_DFL);

	fds[0] = open("/dev/null", O_RDONLY);
	fds[1] = (fds[0] < 0) ? -1 : open((out != NULL) ? out : "/dev/null", O_WRONLY | O_CREAT | O_TRUNC, 0644);
	fds[2] = (fds[1] < 0) ? -1 : open((err != NULL) ? err : "/dev/null", O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (fds[2] < 0) {
		(void)snprintf(line, sizeof(line), "BWAIT run prog=%s spawn-failed errno=%d\n", prog, errno);
		report_run(rec, line);
		return 125;
	}

	rc = posix_spawn_file_actions_init(&fa);
	for (int i = 0; rc == 0 && i < 3; i++) {
		rc = posix_spawn_file_actions_adddup2(&fa, fds[i], i);
	}
	for (int i = 0; rc == 0 && i < 3; i++) {
		int dup = 0;

		for (int j = 0; j < i; j++) {
			dup |= (fds[j] == fds[i]);
		}
		if (fds[i] > 2 && !dup) {
			rc = posix_spawn_file_actions_addclose(&fa, fds[i]);
		}
	}
	t0 = ClockCycles();
	if (rc == 0) {
		rc = posix_spawn(&pid, pargv[0], &fa, NULL, pargv, environ);
	}
	(void)posix_spawn_file_actions_destroy(&fa);
	for (int i = 0; i < 3; i++) {
		(void)close(fds[i]);
	}
	if (rc != 0) {
		(void)snprintf(line, sizeof(line), "BWAIT run prog=%s spawn-failed errno=%d\n", prog, rc);
		report_run(rec, line);
		return 125;
	}

	deadline = t0 + (uint64_t)secs * cps;
	for (;;) {
		pid_t const w = waitpid(pid, &st, WNOHANG);

		if (w == pid) {
			reaped = 1;
			break;
		}
		if (w < 0) {
			if (errno == EINTR) {
				continue;
			}
			wait_err = errno;
			break;
		}
		if (ClockCycles() >= deadline) {
			if (killed) {
				break;      /* SIGKILL sent 5 s ago and still not reaped */
			}
			(void)kill(pid, SIGKILL);
			killed   = 1;
			deadline = ClockCycles() + (uint64_t)KILL_GRACE_S * cps;
			continue;
		}
		nap_toward(deadline, POLL_MS);
	}

	int const exited = reaped && WIFEXITED(st);
	int const sig    = (reaped && WIFSIGNALED(st)) ? WTERMSIG(st) : 0;
	int const status = exited ? WEXITSTATUS(st) : -1;
	char      extra[64];

	extra[0] = '\0';
	if (wait_err != 0) {
		(void)snprintf(extra, sizeof(extra), " waitpid-errno=%d", wait_err);
	} else if (!reaped) {
		(void)snprintf(extra, sizeof(extra), " reaped=0");
	}
	(void)snprintf(line, sizeof(line), "BWAIT run prog=%s rc=%d sig=%d killed=%d ms=%llu%s\n",
	               prog, status, sig, killed, (unsigned long long)ms_since(t0), extra);
	report_run(rec, line);

	if (killed) {
		return 124;
	}
	if (wait_err != 0 || !reaped) {
		return 125;
	}
	return exited ? status : 128 + sig;
}

static int
sleep_create(unsigned const secs, const char *const path)
{
	uint64_t const deadline = ClockCycles() + (uint64_t)secs * cps;
	int            fd;

	while (ClockCycles() < deadline) {
		nap_toward(deadline, NAP_MS);
	}
	fd = open(path, O_WRONLY | O_CREAT, 0644);
	if (fd < 0) {
		return 1;
	}
	(void)close(fd);
	return 0;
}

static int
guard(unsigned const secs)
{
	struct sched_param sp;
	uint64_t           deadline;
	char               prio[16];
	int                err;
	pid_t              pid;

	memset(&sp, 0, sizeof(sp));
	sp.sched_priority = GUARD_PRIO;
	err = pthread_setschedparam(pthread_self(), SCHED_RR, &sp);
	if (err == 0) {
		(void)snprintf(prio, sizeof(prio), "%d", GUARD_PRIO);
	} else {
		(void)snprintf(prio, sizeof(prio), "err%d", err);
	}
	deadline = ClockCycles() + (uint64_t)secs * cps;
	say("BWAIT guard armed secs=%u prio=%s\n", secs, prio);

	while (ClockCycles() < deadline) {
		nap_toward(deadline, NAP_MS);
	}

	say("BWAIT guard deadline=%u expired: sysmgr_reboot\n", secs);
	(void)sysmgr_reboot();
	say("BWAIT guard sysmgr_reboot returned errno=%d\n", errno);

	{
		static char a0[] = "shutdown";
		static char a1[] = "-S";
		static char a2[] = "reboot";
		char       *sargv[] = { a0, a1, a2, NULL };

		err = posix_spawn(&pid, "/proc/boot/shutdown", NULL, NULL, sargv, environ);
		if (err != 0) {
			say("BWAIT guard shutdown spawn-failed errno=%d\n", err);
		}
	}

	deadline = ClockCycles() + (uint64_t)GUARD_TAIL_S * cps;
	while (ClockCycles() < deadline) {
		nap_toward(deadline, NAP_MS);
	}
	say("BWAIT guard still alive\n");
	return 1;
}

int
main(int argc, char **argv)
{
	const char *paths[MAX_PATHS];
	int         npaths = 0;
	const char *rec    = NULL;
	const char *out    = NULL;
	const char *err    = NULL;
	const char *create = NULL;
	char      **pargv  = NULL;
	unsigned    t = 0, k = 0, s = 0, g = 0;
	int         have_t = 0, have_k = 0, have_s = 0, have_g = 0;

	for (int i = 1; i < argc; i++) {
		const char *const a   = argv[i];
		int const         val = (i + 1 < argc);

		if (strcmp(a, "--") == 0) {
			if (i + 1 >= argc) {
				return usage();
			}
			pargv = &argv[i + 1];
			break;
		} else if (val && strcmp(a, "-p") == 0) {
			if (npaths == MAX_PATHS) {
				return usage();
			}
			paths[npaths++] = argv[++i];
		} else if (val && strcmp(a, "-t") == 0 && !have_t) {
			if (!parse_secs(argv[++i], 0u, &t)) {
				return usage();
			}
			have_t = 1;
		} else if (val && strcmp(a, "-k") == 0 && !have_k) {
			if (!parse_secs(argv[++i], 1u, &k)) {
				return usage();
			}
			have_k = 1;
		} else if (val && strcmp(a, "-s") == 0 && !have_s) {
			if (!parse_secs(argv[++i], 0u, &s)) {
				return usage();
			}
			have_s = 1;
		} else if (val && strcmp(a, "-g") == 0 && !have_g) {
			if (!parse_secs(argv[++i], 1u, &g)) {
				return usage();
			}
			have_g = 1;
		} else if (val && strcmp(a, "-r") == 0 && rec == NULL) {
			rec = argv[++i];
		} else if (val && strcmp(a, "-o") == 0 && out == NULL) {
			out = argv[++i];
		} else if (val && strcmp(a, "-e") == 0 && err == NULL) {
			err = argv[++i];
		} else if (val && strcmp(a, "-c") == 0 && create == NULL) {
			create = argv[++i];
		} else {
			return usage();
		}
	}

	int const modes = (npaths > 0) + have_k + have_s + have_g;

	if (modes != 1) {
		return usage();
	}
	if (npaths > 0 && (!have_t || rec || out || err || create || pargv)) {
		return usage();
	}
	if (have_k && (pargv == NULL || have_t || create)) {
		return usage();
	}
	if (have_s && (create == NULL || have_t || rec || out || err || pargv)) {
		return usage();
	}
	if (have_g && (have_t || rec || out || err || create || pargv)) {
		return usage();
	}

	cps = SYSPAGE_ENTRY(qtime)->cycles_per_sec;
	if (cps == 0) {
		say("BWAIT clock-error cps=0\n");
		return have_k ? 125 : 1;
	}

	if (npaths > 0) {
		return wait_paths(paths, npaths, t);
	}
	if (have_k) {
		return run_bounded(k, rec, out, err, pargv);
	}
	if (have_s) {
		return sleep_create(s, create);
	}
	return guard(g);
}
