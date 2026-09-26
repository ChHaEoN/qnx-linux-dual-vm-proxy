/*
 * clockctl.c -- Phase 3b / A6 (2026-09-26): a guest-side reader (and, where the OS allows,
 * setter) of the QNX clock period, for run-clock.sh.
 *
 * QNX OS 8.0 DOES NOT ALLOW SETTING IT AT RUN TIME: ClockPeriod() with a new value fails with
 * ENOTSUP (errno 48; found on this guest 2026-09-26, and so documented for 8.0). The tick is
 * fixed at boot by procnto -C, so the intervention is two images (ifs-clock.build at 1 kHz,
 * ifs-clock100.build at 100 Hz), and run-clock.sh uses only `get`, to prove in every guest
 * boot which tick it runs. `set` is kept for an OS that allows it; here it answers
 * "error set 48".
 *
 * It is NOT the monitor: monitor.c stays pure POSIX, and this program calls ClockPeriod(),
 * which is QNX's own (sys/neutrino.h). It never sees a claim frame.
 *
 * Protocol: TCP on PORT (argv[1]), one connection at a time, one line per connection:
 *   "get\n"          -> "period NS\n"             the current period, read back
 *   "set NS\n"       -> "period OLD NEW\n"        ClockPeriod() set to NS, NEW read back
 *   anything else    -> "error ...\n"
 * NS must lie in [100000, 100000000] (0.1 to 100 ms); anything outside is refused, so a
 * typo cannot give the guest a pathological tick. Every change is logged to stdout, which
 * the image's startup script leaves on the guest console.
 */
#include <errno.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/neutrino.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define NS_MIN 100000UL
#define NS_MAX 100000000UL

static int period_get(unsigned long *ns)
{
	struct _clockperiod cur;

	if (ClockPeriod(CLOCK_REALTIME, NULL, &cur, 0) == -1)
		return -1;
	*ns = cur.nsec;
	return 0;
}

static int period_set(unsigned long ns)
{
	struct _clockperiod nw;

	nw.nsec = (_Uint32t)ns;
	nw.fract = 0;
	return ClockPeriod(CLOCK_REALTIME, &nw, NULL, 0);
}

/* One request: read a line (up to 63 bytes), answer it into out. */
static void handle(const char *line, char *out, size_t outsz)
{
	unsigned long old, now, want;
	char *end;

	if (strcmp(line, "get") == 0) {
		if (period_get(&now) == -1)
			snprintf(out, outsz, "error get %d\n", errno);
		else
			snprintf(out, outsz, "period %lu\n", now);
		return;
	}
	if (strncmp(line, "set ", 4) == 0) {
		errno = 0;
		want = strtoul(line + 4, &end, 10);
		if (errno != 0 || end == line + 4 || *end != '\0') {
			snprintf(out, outsz, "error parse\n");
			return;
		}
		if (want < NS_MIN || want > NS_MAX) {
			snprintf(out, outsz, "error range %lu..%lu\n", NS_MIN, NS_MAX);
			return;
		}
		if (period_get(&old) == -1) {
			snprintf(out, outsz, "error get %d\n", errno);
			return;
		}
		if (period_set(want) == -1) {
			snprintf(out, outsz, "error set %d\n", errno);
			return;
		}
		if (period_get(&now) == -1) {
			snprintf(out, outsz, "error get %d\n", errno);
			return;
		}
		printf("clockctl: period %lu -> %lu ns (asked %lu)\n", old, now, want);
		fflush(stdout);
		snprintf(out, outsz, "period %lu %lu\n", old, now);
		return;
	}
	snprintf(out, outsz, "error unknown\n");
}

int main(int argc, char **argv)
{
	struct sockaddr_in a;
	struct timeval tv = { 2, 0 };
	unsigned long ns = 0;
	int ls, one = 1;

	if (argc != 2) {
		fprintf(stderr, "usage: qnx-clockctl PORT\n");
		return 2;
	}
	ls = socket(AF_INET, SOCK_STREAM, 0);
	if (ls == -1) {
		perror("clockctl: socket");
		return 1;
	}
	setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET;
	a.sin_addr.s_addr = htonl(INADDR_ANY);
	a.sin_port = htons((unsigned short)atoi(argv[1]));
	if (bind(ls, (struct sockaddr *)&a, sizeof a) == -1 || listen(ls, 1) == -1) {
		perror("clockctl: bind/listen");
		return 1;
	}
	period_get(&ns);
	printf("clockctl: listening on :%s, clock period %lu ns\n", argv[1], ns);
	fflush(stdout);
	for (;;) {
		char line[64], out[96];
		size_t n = 0;
		ssize_t got;
		int c = accept(ls, NULL, NULL);

		if (c == -1) {
			if (errno == EINTR)
				continue;
			perror("clockctl: accept");
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
		handle(line, out, sizeof out);
		(void)write(c, out, strlen(out));
		close(c);
	}
}
