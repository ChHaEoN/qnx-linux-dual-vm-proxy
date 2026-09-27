/*
 * tracectl.c -- Phase 3b / A6 (2026-09-27): a guest-side control for the QNX kernel event
 * trace, for run-trace.sh.
 *
 * WHY. How a guest read() of a network-connected socket compares with a read of a loopback
 * socket is in record `20260927T-a6-orin-free` (held locally). The host cannot see guest
 * threads, so the split between the kernel's message pass and io-sock's own work has to be
 * traced from inside: the image already runs procnto-smp-instr, and this
 * program runs the SDP's tracelogger on request and hands its output back over TCP.
 *
 * It is NOT the monitor: monitor.c stays pure POSIX. This program only spawns QNX's own
 * utilities; it never sees a claim frame.
 *
 * Protocol: TCP on PORT (argv[1]), one connection at a time, one line per connection:
 *   "ping\n"        -> "tracectl ok\n"
 *   "trace SECS\n"  -> SECS in 1..10. Spawns
 *                        tracelogger -n 0 -s SECS -f /dev/shmem/tracectl.kev
 *                      (fast events, every class), waits SETTLE_MS for it to start, and writes
 *                      "started pid P\n" -- the caller starts its load then. When tracelogger
 *                      exits it writes "logged rc R bytes B\n", then three sections, each
 *                      opened by "=== NAME\n" and closed by "=== NAME rc R\n":
 *                        tracelogger  its own stdout/stderr
 *                        traceprinter the trace as text (traceprinter -f the .kev)
 *                        pidin        every thread's name and state, taken after the trace
 *                      and last "end\n". The .kev and the log are then removed.
 *   anything else   -> "error ...\n"
 * The guest's console gets one line per trace.
 */
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define KEV "/dev/shmem/tracectl.kev"
#define LOG "/dev/shmem/tracectl.log"
#define TRACELOGGER "/proc/boot/tracelogger"
#define TRACEPRINTER "/proc/boot/traceprinter"
#define PIDIN "/proc/boot/pidin"
#define SETTLE_MS 500

extern char **environ;

static void say(int c, const char *s)
{
	(void)write(c, s, strlen(s));
}

/* "WHAT V\n": a literal word and a number. */
static void sayn(int c, const char *what, long v)
{
	char out[128];

	snprintf(out, sizeof out, "%s %ld\n", what, v);
	say(c, out);
}

/* Spawn argv with stdout and stderr on fd; the child's pid, or -1. */
static pid_t spawn_to(char *const argv[], int fd)
{
	posix_spawn_file_actions_t fa;
	pid_t pid;
	int rc;

	if (posix_spawn_file_actions_init(&fa) != 0)
		return -1;
	posix_spawn_file_actions_adddup2(&fa, fd, 1);
	posix_spawn_file_actions_adddup2(&fa, fd, 2);
	rc = posix_spawn(&pid, argv[0], &fa, NULL, argv, environ);
	posix_spawn_file_actions_destroy(&fa);
	if (rc != 0) {
		errno = rc;
		return -1;
	}
	return pid;
}

static int wait_rc(pid_t pid)
{
	int st;

	while (waitpid(pid, &st, 0) == -1) {
		if (errno != EINTR)
			return -1;
	}
	return WIFEXITED(st) ? WEXITSTATUS(st) : 128 + WTERMSIG(st);
}

/* One section: "=== NAME", argv's output on c, "=== NAME rc R". */
static void section(int c, const char *name, char *const argv[])
{
	char head[64];
	pid_t pid;
	int rc;

	snprintf(head, sizeof head, "=== %s\n", name);
	say(c, head);
	pid = spawn_to(argv, c);
	rc = pid == -1 ? -errno : wait_rc(pid);
	snprintf(head, sizeof head, "=== %s rc %d\n", name, rc);
	say(c, head);
}

static void copy_file(int c, const char *path)
{
	char buf[4096];
	ssize_t k;
	int fd = open(path, O_RDONLY);

	if (fd == -1)
		return;
	while ((k = read(fd, buf, sizeof buf)) > 0)
		(void)write(c, buf, (size_t)k);
	close(fd);
}

static void trace(int c, long secs)
{
	char s_arg[16], msg[96];
	char *tl[] = { TRACELOGGER, "-n", "0", "-s", s_arg, "-f", KEV, NULL };
	char *tp[] = { TRACEPRINTER, "-f", KEV, NULL };
	char *pi[] = { PIDIN, NULL };
	struct timespec settle = { SETTLE_MS / 1000, (SETTLE_MS % 1000) * 1000000L };
	struct stat sb;
	pid_t pid;
	int logfd, rc, st;

	unlink(KEV);
	logfd = open(LOG, O_WRONLY | O_CREAT | O_TRUNC, 0644);
	if (logfd == -1) {
		sayn(c, "error log", errno);
		return;
	}
	snprintf(s_arg, sizeof s_arg, "%ld", secs);
	pid = spawn_to(tl, logfd);
	close(logfd);
	if (pid == -1) {
		sayn(c, "error spawn", errno);
		return;
	}
	nanosleep(&settle, NULL);
	if (waitpid(pid, &st, WNOHANG) == pid) {
		sayn(c, "error tracelogger exited early status", st);
		copy_file(c, LOG);
		return;
	}
	sayn(c, "started pid", (long)pid);
	rc = wait_rc(pid);
	snprintf(msg, sizeof msg, "logged rc %d bytes %ld\n", rc, stat(KEV, &sb) == 0 ? (long)sb.st_size : -1L);
	say(c, msg);
	say(c, "=== tracelogger\n");
	copy_file(c, LOG);
	say(c, "=== tracelogger rc 0\n");
	section(c, "traceprinter", tp);
	section(c, "pidin", pi);
	say(c, "end\n");
	printf("tracectl: traced %ld s, tracelogger rc %d\n", secs, rc);
	fflush(stdout);
	unlink(KEV);
	unlink(LOG);
}

int main(int argc, char **argv)
{
	struct sockaddr_in a;
	struct timeval tv = { 2, 0 };
	int ls, one = 1;

	if (argc != 2) {
		fprintf(stderr, "usage: qnx-tracectl PORT\n");
		return 2;
	}
	signal(SIGPIPE, SIG_IGN);
	ls = socket(AF_INET, SOCK_STREAM, 0);
	if (ls == -1) {
		perror("tracectl: socket");
		return 1;
	}
	setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET;
	a.sin_addr.s_addr = htonl(INADDR_ANY);
	a.sin_port = htons((unsigned short)atoi(argv[1]));
	if (bind(ls, (struct sockaddr *)&a, sizeof a) == -1 || listen(ls, 1) == -1) {
		perror("tracectl: bind/listen");
		return 1;
	}
	printf("tracectl: listening on :%s\n", argv[1]);
	fflush(stdout);
	for (;;) {
		char line[64], *end;
		size_t n = 0;
		ssize_t got;
		long secs;
		int c = accept(ls, NULL, NULL);

		if (c == -1) {
			if (errno == EINTR)
				continue;
			perror("tracectl: accept");
			return 1;
		}
		setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
		while (n < sizeof line - 1) {
			got = read(c, line + n, 1);
			if (got <= 0 || line[n] == '\n')
				break;
			n++;
		}
		line[n] = '\0';
		if (n > 0 && line[n - 1] == '\r')
			line[n - 1] = '\0';
		if (strcmp(line, "ping") == 0) {
			say(c, "tracectl ok\n");
		} else if (strncmp(line, "trace ", 6) == 0) {
			errno = 0;
			secs = strtol(line + 6, &end, 10);
			if (errno != 0 || end == line + 6 || *end != '\0' || secs < 1 || secs > 10)
				say(c, "error usage: trace SECS (1..10)\n");
			else
				trace(c, secs);
		} else {
			say(c, "error unknown\n");
		}
		close(c);
	}
}
