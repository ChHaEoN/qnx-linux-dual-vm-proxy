/* Phase 3b / A6 (2026-09-26): qnx-ipcbench -- what one guest call costs, by kind of call
 * (orin-native/gpu-concurrency/run-ipcbench.sh).
 *
 * WHY. What a guest socket read() that finds its 32 bytes already there costs, against the
 * native one, is in record `20260926T-a6-orin-readtime` (held locally). A QNX read() is a
 * message to the server behind the fd, so its cost could be the message pass itself, the
 * kernel entry, or io-sock's own socket code. This program times one call of each kind,
 * in the guest and natively, so they can be told apart.
 *
 * THE OPS. Each is timed the way the endpoint's second read happens: one call first (the
 * "prime", untimed), then the timed call, on CLOCK_MONOTONIC.
 *   clock  clock_gettime() itself (the instrument's own cost)
 *   kcall  one trivial kernel call: SchedGet() on QNX, syscall(SYS_getppid) on Linux
 *   zero   read() of 32 bytes from /dev/zero (QNX: a message to procnto)
 *   msg    QNX only: MsgSend() of 32 bytes to a server process on the same CPU, and its reply
 *   msgx   QNX only: the same to a server process on the other CPU
 *   sock   a TCP loopback pair: the prime writes 64 bytes and reads 32 (waiting for them),
 *          the timed call reads the other 32, already there (QNX: io-sock)
 * Two regimes: "tight" (the pairs back to back) and "spaced" (a sleep of GAP_US before each
 * pair, as the A6 exchange's 2 ms). The calling thread runs on CPU 0 (QNX: ThreadCtl runmask;
 * natively, taskset from outside); the msg servers are pinned to CPU 0 and CPU 1.
 *
 * USAGE.
 *   qnx-ipcbench PORT        a TCP service: one command per connection, results back on it
 *   qnx-ipcbench local CMD   run one command, results on stdout (the native control)
 * Commands: "run N GAP_US ROT" -- every op in both regimes, N timed calls each, the ops
 * rotated by ROT; "check" -- every op three times per regime, "ok"/"fail" only, no timings.
 * Result lines, which run-ipcbench.sh parses:
 *   op NAME regime tight|spaced n N p10_ns X p50_ns X p90_ns X mean_ns X
 * then "done". An op that cannot run says "fail NAME REGIME errno N".
 *
 * Not the monitor: this program uses QNX's own calls, and nothing in the A6 path runs it.
 */
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#ifdef __QNX__
#include <sched.h>
#include <sys/neutrino.h>
#else
#include <sys/syscall.h>
#endif

#define N_MAX 4096
#define NOPS 6

static long long samp[N_MAX];
static int zfd = -1, sa = -1, sb = -1;
#ifdef __QNX__
static int coid[2] = { -1, -1 };
static pid_t srv[2] = { -1, -1 };
#endif

static long long now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void gap(long us)
{
    struct timespec ts = { us / 1000000, (us % 1000000) * 1000 };
    while (nanosleep(&ts, &ts) < 0 && errno == EINTR) {
    }
}

/* ---------------------------------------------------------------- the calls */
static int c_clock(void)
{
    struct timespec ts;
    return clock_gettime(CLOCK_MONOTONIC, &ts);
}

static int c_kcall(void)
{
#ifdef __QNX__
    struct sched_param p;
    return SchedGet(0, 0, &p) < 0 ? -1 : 0;
#else
    return syscall(SYS_getppid) < 0 ? -1 : 0;
#endif
}

static int c_zero(void)
{
    char b[32];
    return read(zfd, b, sizeof b) == (ssize_t)sizeof b ? 0 : -1;
}

#ifdef __QNX__
static int c_msg_on(int i)
{
    char s[32] = { 0 }, r[32];
    return MsgSend(coid[i], s, sizeof s, r, sizeof r) < 0 ? -1 : 0;
}
static int c_msg(void) { return c_msg_on(0); }
static int c_msgx(void) { return c_msg_on(1); }
#endif

static int read_all(int fd, char *b, size_t n)
{
    size_t got = 0;
    while (got < n) {
        ssize_t k = read(fd, b + got, n - got);
        if (k <= 0) {
            if (k < 0 && errno == EINTR) {
                continue;
            }
            return -1;
        }
        got += (size_t)k;
    }
    return 0;
}

static int p_sock(void)   /* 64 bytes in, the first 32 read (waiting for them) */
{
    char b[64] = { 0 };
    if (write(sa, b, sizeof b) != (ssize_t)sizeof b) {
        return -1;
    }
    return read_all(sb, b, 32);
}

static int c_sock(void)   /* the other 32, already there */
{
    char b[32];
    return read(sb, b, sizeof b) == (ssize_t)sizeof b ? 0 : -1;
}

/* ---------------------------------------------------------------- setup */
static int sock_open(void)
{
    struct sockaddr_in a;
    socklen_t al = sizeof a;
    int one = 1, l = socket(AF_INET, SOCK_STREAM, 0);
    if (l < 0) {
        return -1;
    }
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(l, (struct sockaddr *)&a, sizeof a) < 0 || listen(l, 1) < 0
        || getsockname(l, (struct sockaddr *)&a, &al) < 0) {
        close(l);
        return -1;
    }
    sa = socket(AF_INET, SOCK_STREAM, 0);
    if (sa < 0 || connect(sa, (struct sockaddr *)&a, sizeof a) < 0) {
        close(l);
        return -1;
    }
    sb = accept(l, NULL, NULL);
    close(l);
    if (sb < 0) {
        return -1;
    }
    setsockopt(sa, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    setsockopt(sb, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    return 0;
}

static void sock_close(void)
{
    if (sa >= 0) close(sa);
    if (sb >= 0) close(sb);
    sa = sb = -1;
}

#ifdef __QNX__
/* A server process pinned to one CPU: receive 32 bytes, reply 32. Its channel id is passed
 * back through a file in /dev/shmem (procnto's, always there). */
static int server_start(int cpu)
{
    char path[64];
    snprintf(path, sizeof path, "/dev/shmem/ipcbench.chid%d", cpu);
    unlink(path);
    pid_t pid = fork();
    if (pid < 0) {
        return -1;
    }
    if (pid == 0) {
        char buf[64];
        ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)(1u << cpu));
        int chid = ChannelCreate(0);
        FILE *f = fopen(path, "w");
        if (chid < 0 || f == NULL) {
            _exit(1);
        }
        fprintf(f, "%d\n", chid);
        fclose(f);
        for (;;) {
            rcvid_t id = MsgReceive(chid, buf, sizeof buf, NULL);
            if (id == 0) {
                continue;                     /* a pulse */
            }
            if (id < 0) {
                if (errno == EINTR) {
                    continue;
                }
                _exit(1);
            }
            MsgReply(id, 0, buf, 32);
        }
    }
    int chid = -1;
    for (int i = 0; i < 200 && chid < 0; i++) {
        FILE *f = fopen(path, "r");
        if (f != NULL) {
            if (fscanf(f, "%d", &chid) != 1) {
                chid = -1;
            }
            fclose(f);
        }
        if (chid < 0) {
            gap(10000);
        }
    }
    if (chid < 0) {
        return -1;
    }
    srv[cpu] = pid;
    coid[cpu] = ConnectAttach(0, pid, chid, _NTO_SIDE_CHANNEL, 0);
    return coid[cpu] < 0 ? -1 : 0;
}

static void servers_stop(void)
{
    for (int i = 0; i < 2; i++) {
        if (srv[i] > 0) {
            kill(srv[i], SIGTERM);
        }
    }
}
#endif

/* ---------------------------------------------------------------- the runner */
struct op {
    const char *name;
    int (*prime)(void);
    int (*call)(void);
    int available;
};

static struct op ops[NOPS];
static int nops;

static void ops_init(void)
{
    nops = 0;
    ops[nops++] = (struct op){ "clock", c_clock, c_clock, 1 };
    ops[nops++] = (struct op){ "kcall", c_kcall, c_kcall, 1 };
    ops[nops++] = (struct op){ "zero", c_zero, c_zero, zfd >= 0 };
#ifdef __QNX__
    ops[nops++] = (struct op){ "msg", c_msg, c_msg, coid[0] >= 0 };
    ops[nops++] = (struct op){ "msgx", c_msgx, c_msgx, coid[1] >= 0 };
#endif
    ops[nops++] = (struct op){ "sock", p_sock, c_sock, 1 };
}

static int cmp_ll(const void *a, const void *b)
{
    long long x = *(const long long *)a, y = *(const long long *)b;
    return (x > y) - (x < y);
}

static void run_one(FILE *o, const struct op *op, const char *regime, int n, long gap_us, int check)
{
    int is_sock = strcmp(op->name, "sock") == 0;
    if (!op->available || (is_sock && sock_open() < 0)) {
        fprintf(o, "fail %s %s errno %d\n", op->name, regime, errno);
        return;
    }
    for (int i = 0; i < n; i++) {
        if (gap_us > 0) {
            gap(gap_us);
        }
        if (op->prime() < 0) {
            fprintf(o, "fail %s %s errno %d\n", op->name, regime, errno);
            if (is_sock) sock_close();
            return;
        }
        long long t0 = now_ns();
        int rc = op->call();
        long long t1 = now_ns();
        if (rc < 0) {
            fprintf(o, "fail %s %s errno %d\n", op->name, regime, errno);
            if (is_sock) sock_close();
            return;
        }
        samp[i] = t1 - t0;
    }
    if (is_sock) {
        sock_close();
    }
    if (check) {
        fprintf(o, "ok %s %s\n", op->name, regime);
        return;
    }
    long long sum = 0;
    for (int i = 0; i < n; i++) {
        sum += samp[i];
    }
    qsort(samp, (size_t)n, sizeof samp[0], cmp_ll);
    fprintf(o, "op %s regime %s n %d p10_ns %lld p50_ns %lld p90_ns %lld mean_ns %lld\n",
            op->name, regime, n, samp[n / 10], samp[n / 2], samp[(n * 9) / 10], sum / n);
}

static void command(FILE *o, const char *line)
{
    int n = 3, rot = 0, check = 0;
    long gap_us = 2000;
    if (strncmp(line, "check", 5) == 0) {
        check = 1;
    } else if (sscanf(line, "run %d %ld %d", &n, &gap_us, &rot) != 3 || n < 1 || n > N_MAX || gap_us < 0) {
        fprintf(o, "error usage: run N GAP_US ROT | check\n");
        return;
    }
#ifdef __QNX__
    ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)1u);
#endif
    for (int k = 0; k < nops; k++) {
        const struct op *op = &ops[(k + rot) % nops];
        run_one(o, op, "tight", n, 0, check);
        run_one(o, op, "spaced", n, check ? 0 : gap_us, check);
    }
    fprintf(o, "done\n");
    fflush(o);
}

int main(int argc, char **argv)
{
    signal(SIGPIPE, SIG_IGN);
    zfd = open("/dev/zero", O_RDONLY);
#ifdef __QNX__
    server_start(0);
    server_start(1);
    atexit(servers_stop);
#endif
    ops_init();
    if (argc > 2 && strcmp(argv[1], "local") == 0) {
        char line[128] = { 0 };
        for (int i = 2; i < argc; i++) {
            strncat(line, argv[i], sizeof line - strlen(line) - 2);
            strcat(line, " ");
        }
        command(stdout, line);
        return 0;
    }
    if (argc != 2) {
        fprintf(stderr, "ipcbench: usage: %s PORT | local run N GAP_US ROT | local check\n", argv[0]);
        return 2;
    }
    int one = 1, l = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a;
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    a.sin_port = htons((unsigned short)strtoul(argv[1], NULL, 10));
    setsockopt(l, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    if (l < 0 || bind(l, (struct sockaddr *)&a, sizeof a) < 0 || listen(l, 1) < 0) {
        fprintf(stderr, "ipcbench: cannot listen on :%s: %s\n", argv[1], strerror(errno));
        return 1;
    }
    fprintf(stderr, "ipcbench: listening on :%s\n", argv[1]);
    for (;;) {
        int c = accept(l, NULL, NULL);
        if (c < 0) {
            if (errno == EINTR) {
                continue;
            }
            return 1;
        }
        /* The command line by read(), the results by a write-only stream: one stdio stream
         * cannot switch from reading to writing on a socket (no fseek). */
        char line[128];
        size_t got = 0;
        while (got < sizeof line - 1) {
            ssize_t k = read(c, line + got, 1);
            if (k <= 0 || line[got] == '\n') {
                break;
            }
            got++;
        }
        line[got] = '\0';
        FILE *o = fdopen(c, "w");
        if (o == NULL) {
            close(c);
            continue;
        }
        command(o, line);
        fclose(o);
    }
}
