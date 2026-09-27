/* Phase 3b / A6 (2026-09-26): the frame-size sweep's echo endpoint
 * (docs/measurement-design.md section 3.4; orin-native/gpu-concurrency/run-sweep.sh).
 *
 * WHY A SEPARATE PROGRAM. The sweep needs frames of 64..2048 bytes, and every
 * existing endpoint is fixed at FRAME_TOTAL_BYTES = 64, which must stay 64: the
 * shared-memory slot copies that many bytes with no bound check (shm_chan.h).
 * So the monitor is not touched, server.c (qnx-echo-server-net, staged in every
 * earlier image) is not touched, and this is its own binary,
 * qnx-echo-server-sweep, built from its own source for the guest (qcc, `make
 * sweep`) and for the host (gcc, by run-sweep.sh). It is pure POSIX, so the two
 * are the same program.
 *
 * THE WIRE. A frame's first 64 bytes are an ordinary frame (frame.h). Its total
 * length S is a little-endian uint16 in the last two of those bytes, payload[46..47]
 * -- the only payload bytes no claim kind uses -- and 0 there means 64, so an
 * ordinary frame is echoed as it is. The endpoint reads the 64 bytes, then S - 64
 * more, and writes all S back unmodified. A length outside 64..SWEEP_MAX_BYTES
 * ends the connection: echoing a guess would hand the initiator bytes it did not
 * send.
 *
 * READ MODES (2026-09-26, run-reads.sh). The default mode above makes one read() at
 * 64 B and two above it, so in the sweep (record `20260926T-a6-orin-sweep`, held
 * locally) the read count moves with the frame size. Two opt-in modes separate the
 * read count from the frame size:
 *   greedy  read as much as is there (up to two frames' room), then only what is
 *           missing: one read() per frame whenever the frame arrived whole;
 *   split   read the first 64 bytes as 32 + 32, then S - 64 as the default does:
 *           two read()s at 64 B, three above.
 * The default mode's socket calls are unchanged. Every mode counts its read() calls
 * that returned data, and prints them with the frames in one more line at the end of
 * each connection -- the check that the mode did what it says.
 *
 * WAIT MODE (2026-09-27, run-spin.sh). "splitw SPIN_US" is split with a busy wait of SPIN_US
 * microseconds between the frame's first 32 bytes and its second read. The wait spins on
 * CLOCK_MONOTONIC so the thread stays runnable; a sleep would round up to QNX's 1 ms tick. A
 * SWEEP_TIMING build also prints the waits' median, the check that the wait was what was asked.
 *
 * TCP only, one client at a time, TCP_NODELAY per connection, as server.c.
 * Usage: qnx-echo-server-sweep PORT [greedy|split|splitw SPIN_US]
 * (built as qnx-echo-server-reads by `make reads` for ifs-reads.build, and with
 * -DSWEEP_TIMING as qnx-echo-server-timed by `make timed` for ifs-timed.build and as
 * qnx-echo-server-spin by `make spin` for ifs-spin.build: see TIMING)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>

#include "frame.h"

#define DEFAULT_PORT     7120
#define SWEEP_LEN_OFF    (FRAME_TOTAL_BYTES - 2u)   /* payload[46..47] */
#define SWEEP_MAX_BYTES  4096u

enum mode { MODE_DEFAULT, MODE_GREEDY, MODE_SPLIT, MODE_SPLITW };

static volatile sig_atomic_t g_stop = 0;
static unsigned long long g_reads = 0;   /* read() calls that returned data, this connection */
static long g_spin_us = 0;               /* splitw: the wait between the two halves' reads */

static void on_signal(int sig)
{
    (void)sig;
    g_stop = 1;
}

#ifdef SWEEP_TIMING
/* TIMING (2026-09-26, run-readtime.sh), only in a build with -DSWEEP_TIMING
 * (qnx-echo-server-timed): each frame's second read() that returned data, its write(s),
 * and its service time (from the return of its first read to the return of its write) are
 * timed on this OS's CLOCK_MONOTONIC and kept per connection; their medians are printed with
 * the read count. The first read of a frame is not timed as a cost: it waits for the frame.
 * A default build compiles none of this. */
#define TIMED_MAX 8192u
static long long t_r2[TIMED_MAX], t_w[TIMED_MAX], t_svc[TIMED_MAX], t_spin[TIMED_MAX];
static unsigned long long n_r2, n_w, n_svc, n_spin;
static unsigned g_read_idx;      /* read() calls that returned data, this frame */
static long long g_first_ret;    /* when this frame's first such read returned */

static long long now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void keep(long long *a, unsigned long long *n, long long v)
{
    if (*n < TIMED_MAX) {
        a[*n] = v;
    }
    (*n)++;
}

static int cmp_ll(const void *a, const void *b)
{
    long long x = *(const long long *)a, y = *(const long long *)b;
    return (x > y) - (x < y);
}

static long long median(long long *a, unsigned long long n)
{
    size_t m = n < TIMED_MAX ? (size_t)n : TIMED_MAX;
    if (m == 0) {
        return -1;
    }
    qsort(a, m, sizeof a[0], cmp_ll);
    return a[m / 2];
}

#define FRAME_BEGIN() (g_read_idx = 0, g_first_ret = now_ns())
#else
#define FRAME_BEGIN() ((void)0)
#endif

/* splitw's wait: spin on the monotonic clock until SPIN_US have passed. */
static void spin_wait(long us)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    long long t0 = (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec, t = t0, end = t0 + (long long)us * 1000LL;
    while (t < end) {
        clock_gettime(CLOCK_MONOTONIC, &ts);
        t = (long long)ts.tv_sec * 1000000000LL + ts.tv_nsec;
    }
#ifdef SWEEP_TIMING
    keep(t_spin, &n_spin, t - t0);
#endif
}

/* One read(), counted when it returns data. */
static ssize_t counted_read(int fd, uint8_t *buf, size_t len)
{
#ifdef SWEEP_TIMING
    long long t0 = now_ns();
#endif
    ssize_t n = read(fd, buf, len);
    if (n > 0) {
        g_reads++;
#ifdef SWEEP_TIMING
        long long t1 = now_ns();
        if (++g_read_idx == 1) {
            g_first_ret = t1;
        } else if (g_read_idx == 2) {
            keep(t_r2, &n_r2, t1 - t0);
        }
#endif
    }
    return n;
}

/* 0 on success, 1 on EOF before the first byte, -1 on error or EOF mid-frame. */
static int read_full(int fd, uint8_t *buf, size_t len)
{
    size_t got = 0;
    while (got < len) {
        ssize_t n = counted_read(fd, buf + got, len - got);
        if (n == 0) {
            return got == 0 ? 1 : -1;
        }
        if (n < 0) {
            if (errno == EINTR && !g_stop) {
                continue;
            }
            return -1;
        }
        got += (size_t)n;
    }
    return 0;
}

static int write_full(int fd, const uint8_t *buf, size_t len)
{
    size_t put = 0;
    while (put < len) {
        ssize_t n = write(fd, buf + put, len - put);
        if (n < 0) {
            if (errno == EINTR && !g_stop) {
                continue;
            }
            return -1;
        }
        put += (size_t)n;
    }
    return 0;
}

/* A frame's reply: write_full, timed in a SWEEP_TIMING build. */
static int write_frame(int fd, const uint8_t *buf, size_t len)
{
#ifdef SWEEP_TIMING
    long long t0 = now_ns();
    int rc = write_full(fd, buf, len);
    long long t1 = now_ns();
    keep(t_w, &n_w, t1 - t0);
    keep(t_svc, &n_svc, t1 - g_first_ret);
    return rc;
#else
    return write_full(fd, buf, len);
#endif
}

/* The frame's length from its first 64 bytes, or 0 if it is out of range. */
static size_t frame_len(const uint8_t *buf)
{
    size_t len = (size_t)buf[SWEEP_LEN_OFF] | ((size_t)buf[SWEEP_LEN_OFF + 1] << 8);
    if (len == 0) {
        len = FRAME_TOTAL_BYTES;
    }
    if (len < FRAME_TOTAL_BYTES || len > SWEEP_MAX_BYTES) {
        fprintf(stderr, "sweep: frame length %zu outside %u..%u -- closing\n",
                len, (unsigned)FRAME_TOTAL_BYTES, (unsigned)SWEEP_MAX_BYTES);
        return 0;
    }
    return len;
}

/* The default and split modes: the first 64 bytes (whole, or as 32 + 32), then the rest. */
static int serve_stepwise(int cfd, int split, unsigned long long *echoed)
{
    static uint8_t buf[SWEEP_MAX_BYTES];

    while (!g_stop) {
        FRAME_BEGIN();
        int r = split ? read_full(cfd, buf, FRAME_TOTAL_BYTES / 2u) : read_full(cfd, buf, FRAME_TOTAL_BYTES);
        if (r == 0 && split) {
            if (g_spin_us > 0) {
                spin_wait(g_spin_us);
            }
            if (read_full(cfd, buf + FRAME_TOTAL_BYTES / 2u, FRAME_TOTAL_BYTES / 2u) != 0) {
                r = -1;
            }
        }
        if (r == 1) {
            fprintf(stderr, "sweep: client EOF after %llu frames\n", *echoed);
            return 0;
        }
        if (r < 0) {
            fprintf(stderr, "sweep: read: %s\n", errno ? strerror(errno) : "EOF mid-frame");
            return -1;
        }
        size_t len = frame_len(buf);
        if (len == 0) {
            return -1;
        }
        if (len > FRAME_TOTAL_BYTES && read_full(cfd, buf + FRAME_TOTAL_BYTES, len - FRAME_TOTAL_BYTES) != 0) {
            fprintf(stderr, "sweep: read: %s\n", errno ? strerror(errno) : "EOF mid-frame");
            return -1;
        }
        if (write_frame(cfd, buf, len) < 0) {
            fprintf(stderr, "sweep: write: %s\n", strerror(errno));
            return -1;
        }
        (*echoed)++;
    }
    fprintf(stderr, "sweep: signalled stop after %llu frames\n", *echoed);
    return 0;
}

/* The greedy mode: take what is there, then only what is missing; bytes past one frame are
 * kept for the next (the probe never sends them, but a stream may). */
static int serve_greedy(int cfd, unsigned long long *echoed)
{
    static uint8_t buf[2u * SWEEP_MAX_BYTES];
    size_t have = 0;

    while (!g_stop) {
        size_t len = 0;
        FRAME_BEGIN();
        for (;;) {
            if (have >= FRAME_TOTAL_BYTES) {
                if (len == 0 && (len = frame_len(buf)) == 0) {
                    return -1;
                }
                if (have >= len) {
                    break;
                }
            }
            ssize_t n = counted_read(cfd, buf + have, sizeof buf - have);
            if (n == 0) {
                if (have == 0) {
                    fprintf(stderr, "sweep: client EOF after %llu frames\n", *echoed);
                    return 0;
                }
                fprintf(stderr, "sweep: read: EOF mid-frame\n");
                return -1;
            }
            if (n < 0) {
                if (errno == EINTR && !g_stop) {
                    continue;
                }
                if (errno == EINTR) {
                    fprintf(stderr, "sweep: signalled stop after %llu frames\n", *echoed);
                    return 0;
                }
                fprintf(stderr, "sweep: read: %s\n", strerror(errno));
                return -1;
            }
            have += (size_t)n;
        }
        if (write_frame(cfd, buf, len) < 0) {
            fprintf(stderr, "sweep: write: %s\n", strerror(errno));
            return -1;
        }
        (*echoed)++;
        memmove(buf, buf + len, have - len);
        have -= len;
    }
    fprintf(stderr, "sweep: signalled stop after %llu frames\n", *echoed);
    return 0;
}

int main(int argc, char **argv)
{
    static const char *const names[] = { "default", "greedy", "split", "splitw" };
    unsigned short port = (argc > 1) ? (unsigned short)strtoul(argv[1], NULL, 10) : DEFAULT_PORT;
    enum mode mode = MODE_DEFAULT;
    if (argc > 2 && strcmp(argv[2], "greedy") == 0) {
        mode = MODE_GREEDY;
    } else if (argc > 2 && strcmp(argv[2], "split") == 0) {
        mode = MODE_SPLIT;
    } else if (argc > 3 && strcmp(argv[2], "splitw") == 0) {
        mode = MODE_SPLITW;
        g_spin_us = strtol(argv[3], NULL, 10);
    }
    if (argc > (mode == MODE_SPLITW ? 4 : 3) || (argc > 2 && mode == MODE_DEFAULT)
        || (mode == MODE_SPLITW && (g_spin_us < 0 || g_spin_us > 100000))) {
        fprintf(stderr, "sweep: usage: %s [PORT [greedy|split|splitw SPIN_US]]\n", argv[0]);
        return 2;
    }

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    int lfd = socket(AF_INET, SOCK_STREAM, 0);
    if (lfd < 0) {
        fprintf(stderr, "sweep: socket: %s\n", strerror(errno));
        return 1;
    }
    int one = 1;
    if (setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one) < 0) {
        fprintf(stderr, "sweep: setsockopt(SO_REUSEADDR): %s\n", strerror(errno));
        close(lfd);
        return 1;
    }
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);
    if (bind(lfd, (struct sockaddr *)&addr, sizeof addr) < 0) {
        fprintf(stderr, "sweep: bind(:%u): %s\n", port, strerror(errno));
        close(lfd);
        return 1;
    }
    if (listen(lfd, 1) < 0) {
        fprintf(stderr, "sweep: listen: %s\n", strerror(errno));
        close(lfd);
        return 1;
    }
    /* The harness greps this line: keep it byte-identical. */
    fprintf(stderr, "sweep: echo endpoint listening on 0.0.0.0:%u (frames %u..%u bytes, length at [%u..%u])\n",
            port, (unsigned)FRAME_TOTAL_BYTES, (unsigned)SWEEP_MAX_BYTES,
            (unsigned)SWEEP_LEN_OFF, (unsigned)SWEEP_LEN_OFF + 1u);
    if (mode != MODE_DEFAULT) {
        fprintf(stderr, "sweep: :%u read mode %s\n", port, names[mode]);
        if (mode == MODE_SPLITW) {
            fprintf(stderr, "sweep: :%u spin %ld us\n", port, g_spin_us);
        }
    }

    while (!g_stop) {
        struct sockaddr_in peer;
        socklen_t peerlen = sizeof peer;
        int cfd = accept(lfd, (struct sockaddr *)&peer, &peerlen);
        if (cfd < 0) {
            if (errno == EINTR) {
                continue;
            }
            fprintf(stderr, "sweep: accept: %s\n", strerror(errno));
            break;
        }
        if (setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one) < 0) {
            fprintf(stderr, "sweep: setsockopt(TCP_NODELAY): %s\n", strerror(errno));
        }
        fprintf(stderr, "sweep: client connected from %s:%u\n",
                inet_ntoa(peer.sin_addr), (unsigned)ntohs(peer.sin_port));
        unsigned long long echoed = 0;
        g_reads = 0;
#ifdef SWEEP_TIMING
        n_r2 = n_w = n_svc = n_spin = 0;
#endif
        int rc = (mode == MODE_GREEDY) ? serve_greedy(cfd, &echoed)
                                       : serve_stepwise(cfd, mode == MODE_SPLIT || mode == MODE_SPLITW, &echoed);
        /* run-reads.sh parses this line: keep its form. */
        fprintf(stderr, "sweep: reads :%u %s frames=%llu reads=%llu\n", port, names[mode], echoed, g_reads);
#ifdef SWEEP_TIMING
        /* run-readtime.sh parses this line: keep its form. */
        fprintf(stderr, "sweep: timing :%u %s frames=%llu r2_n=%llu r2_p50_ns=%lld w_p50_ns=%lld svc_p50_ns=%lld\n",
                port, names[mode], echoed, n_r2, median(t_r2, n_r2), median(t_w, n_w), median(t_svc, n_svc));
        if (mode == MODE_SPLITW) {
            /* run-spin.sh parses this line: keep its form. */
            fprintf(stderr, "sweep: spin :%u frames=%llu spin_us=%ld spin_p50_ns=%lld\n",
                    port, echoed, g_spin_us, median(t_spin, n_spin));
        }
#endif
        if (rc < 0) {
            fprintf(stderr, "sweep: client session ended with an error; awaiting next client\n");
        }
        close(cfd);
    }
    close(lfd);
    fprintf(stderr, "sweep: clean shutdown\n");
    return 0;
}
