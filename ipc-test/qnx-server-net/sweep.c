/* Phase 3b / A6 (2026-09-26): the frame-size sweep's echo endpoint
 * (docs/measurement-design.md section 3.4; orin-native/gpu-concurrency/run-sweep.sh).
 *
 * WHY A SEPARATE PROGRAM. The sweep needs frames of 64..2048 bytes, and every
 * existing endpoint is fixed at FRAME_TOTAL_BYTES = 64, which must stay 64: the
 * shared-memory slot copies that many bytes with no bound check (shm_chan.h).
 * So the monitor is not touched, server.c (qnx-echo-server-net, staged in every
 * published image) is not touched, and this is its own binary,
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
 * TCP only, one client at a time, TCP_NODELAY per connection, as server.c.
 * Usage: qnx-echo-server-sweep PORT
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int sig)
{
    (void)sig;
    g_stop = 1;
}

/* 0 on success, 1 on EOF before the first byte, -1 on error or EOF mid-frame. */
static int read_full(int fd, uint8_t *buf, size_t len)
{
    size_t got = 0;
    while (got < len) {
        ssize_t n = read(fd, buf + got, len - got);
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

static int serve_one_client(int cfd)
{
    static uint8_t buf[SWEEP_MAX_BYTES];
    unsigned long long echoed = 0;

    while (!g_stop) {
        int r = read_full(cfd, buf, FRAME_TOTAL_BYTES);
        if (r == 1) {
            fprintf(stderr, "sweep: client EOF after %llu frames\n", echoed);
            return 0;
        }
        if (r < 0) {
            fprintf(stderr, "sweep: read: %s\n", errno ? strerror(errno) : "EOF mid-frame");
            return -1;
        }
        size_t len = (size_t)buf[SWEEP_LEN_OFF] | ((size_t)buf[SWEEP_LEN_OFF + 1] << 8);
        if (len == 0) {
            len = FRAME_TOTAL_BYTES;
        }
        if (len < FRAME_TOTAL_BYTES || len > SWEEP_MAX_BYTES) {
            fprintf(stderr, "sweep: frame length %zu outside %u..%u -- closing\n",
                    len, (unsigned)FRAME_TOTAL_BYTES, (unsigned)SWEEP_MAX_BYTES);
            return -1;
        }
        if (len > FRAME_TOTAL_BYTES && read_full(cfd, buf + FRAME_TOTAL_BYTES, len - FRAME_TOTAL_BYTES) != 0) {
            fprintf(stderr, "sweep: read: %s\n", errno ? strerror(errno) : "EOF mid-frame");
            return -1;
        }
        if (write_full(cfd, buf, len) < 0) {
            fprintf(stderr, "sweep: write: %s\n", strerror(errno));
            return -1;
        }
        echoed++;
    }
    fprintf(stderr, "sweep: signalled stop after %llu frames\n", echoed);
    return 0;
}

int main(int argc, char **argv)
{
    unsigned short port = (argc > 1) ? (unsigned short)strtoul(argv[1], NULL, 10) : DEFAULT_PORT;
    if (argc > 2) {
        fprintf(stderr, "sweep: usage: %s [PORT]\n", argv[0]);
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
        if (serve_one_client(cfd) < 0) {
            fprintf(stderr, "sweep: client session ended with an error; awaiting next client\n");
        }
        close(cfd);
    }
    close(lfd);
    fprintf(stderr, "sweep: clean shutdown\n");
    return 0;
}
