/* Phase 3 (Orin, native-Linux TCP client -> QNX-guest TCP echo endpoint).
 *
 * The Linux Compute END of the heterogeneous QNX-safety <-> Linux-compute
 * IPC channel (docs/orin-port.md). Runs a warm-up burst (discarded) then a
 * timed run: each iteration stamps clock_gettime(CLOCK_MONOTONIC) into the
 * frame, sends it over br0/virtio-net to the QNX guest's
 * ipc-test/qnx-server-net/server.c, awaits the echo, and records the RTT.
 * Reports P50 / P99 / Max, mirroring ipc-test/qnx-host-client/client.c's
 * style and CLI convention -- but this is a plain TCP socket, not a QNX
 * console fd, so it builds with plain gcc (no qcc, no QNX headers) and
 * needs none of console_io.h's termios/raw-mode handling.
 *
 * Clock-skew note: the QNX server never reads or writes a clock of its own
 * into the frame -- it echoes the payload (including this client's
 * tstamp_ns field) byte-for-byte. This client is therefore the only party
 * that ever interprets a timestamp, and it always diffs against its own
 * clock on receipt, so there is no cross-OS clock reconciliation needed for
 * this specific RTT measurement.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>

#include "frame.h"
#include "frame_io.h"

#define DEFAULT_ITERS    100000ul
#define DEFAULT_WARMUP   1000ul
#define DEFAULT_HOST     "192.168.100.10"
#define DEFAULT_PORT     7000
#define RESULTS_REL      "../../results/hw"

static int cmp_u64(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a;
    uint64_t y = *(const uint64_t *)b;
    return (x < y) ? -1 : (x > y) ? 1 : 0;
}

/* Nearest-rank percentile over a sorted array (n > 0). */
static uint64_t percentile(const uint64_t *sorted, size_t n, double pct)
{
    if (n == 0) {
        return 0;
    }
    size_t rank = (size_t)(pct / 100.0 * (double)n);
    if (rank >= n) {
        rank = n - 1;
    }
    return sorted[rank];
}

static uint64_t now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static void usage(const char *argv0)
{
    fprintf(stderr,
        "usage: %s [iters] [host] [warmup]\n"
        "  iters   timed iterations (default %lu)\n"
        "  host    QNX guest IP (default %s), port fixed at %d\n"
        "  warmup  discarded warm-up iterations (default %lu)\n",
        argv0, DEFAULT_ITERS, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_WARMUP);
}

int main(int argc, char **argv)
{
    unsigned long iters = DEFAULT_ITERS;
    unsigned long warmup = DEFAULT_WARMUP;
    const char *host = DEFAULT_HOST;

    if (argc > 1) {
        if (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0) {
            usage(argv[0]);
            return 0;
        }
        iters = strtoul(argv[1], NULL, 10);
    }
    if (argc > 2) {
        host = argv[2];
    }
    if (argc > 3) {
        warmup = strtoul(argv[3], NULL, 10);
    }
    if (iters == 0) {
        fprintf(stderr, "client: iters must be > 0\n");
        return 2;
    }

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        fprintf(stderr, "client: socket: %s\n", strerror(errno));
        return 1;
    }

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_port = htons(DEFAULT_PORT);
    if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) {
        fprintf(stderr, "client: inet_pton(%s): invalid address\n", host);
        close(fd);
        return 1;
    }

    if (connect(fd, (struct sockaddr *)&addr, sizeof addr) < 0) {
        fprintf(stderr, "client: connect(%s:%d): %s\n", host, DEFAULT_PORT, strerror(errno));
        close(fd);
        return 1;
    }

    int one = 1;
    if (setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one) < 0) {
        fprintf(stderr, "client: setsockopt(TCP_NODELAY): %s\n", strerror(errno));
    }

    fprintf(stderr, "client: connected to %s:%d; frame=%u bytes\n",
            host, DEFAULT_PORT, (unsigned)FRAME_TOTAL_BYTES);

    uint64_t *samples = malloc((size_t)iters * sizeof *samples);
    if (samples == NULL) {
        fprintf(stderr, "client: malloc(%lu samples): %s\n", iters, strerror(errno));
        close(fd);
        return 1;
    }

    ipc_frame_t f;
    uint8_t wire[FRAME_TOTAL_BYTES];
    for (size_t i = 0; i < FRAME_PAYLOAD_BYTES; ++i) {
        f.payload[i] = (uint8_t)(0x41u + (i & 0x0fu));
    }

    unsigned long total = warmup + iters;
    size_t kept = 0;
    for (unsigned long i = 0; i < total; ++i) {
        if (i == 0 || (i % 1000ul) == 0) {
            fprintf(stderr, "client: progress %lu/%lu\n", i, total);
        }

        f.seq = (uint64_t)i;
        f.tstamp_cycles = now_ns();
        frame_pack(&f, wire);

        if (frameio_write_frame(fd, wire) < 0) {
            fprintf(stderr, "client: write at iter %lu: %s\n", i, strerror(errno));
            free(samples);
            close(fd);
            return 1;
        }

        int r = frameio_read_frame(fd, wire);
        uint64_t end = now_ns();
        if (r != 0) {
            fprintf(stderr, "client: %s at iter %lu\n",
                    (r == 1) ? "unexpected EOF" : strerror(errno), i);
            free(samples);
            close(fd);
            return 1;
        }

        ipc_frame_t echo;
        frame_unpack(wire, &echo);
        if (echo.seq != f.seq) {
            fprintf(stderr, "client: echo seq mismatch at iter %lu (got %llu)\n",
                    i, (unsigned long long)echo.seq);
            free(samples);
            close(fd);
            return 1;
        }

        if (i >= warmup) {
            samples[kept++] = end - echo.tstamp_cycles;
        }
    }

    qsort(samples, kept, sizeof *samples, cmp_u64);
    uint64_t p50_ns = percentile(samples, kept, 50.0);
    uint64_t p99_ns = percentile(samples, kept, 99.0);
    uint64_t max_ns = (kept > 0) ? samples[kept - 1] : 0;

    printf("samples=%zu payload=%u\n", kept, (unsigned)FRAME_PAYLOAD_BYTES);
    printf("P50=%llu ns  P99=%llu ns  Max=%llu ns\n",
           (unsigned long long)p50_ns,
           (unsigned long long)p99_ns,
           (unsigned long long)max_ns);
    printf("(P50 sanity: link alive if non-zero and stable)\n");

    /* Append one CSV row in the results/hw schema (see header.csv). Unlike
     * the QNX host-client (which runs inside a self-contained disk image
     * with no path back to the repo checkout), this client runs natively on
     * L4T with a real filesystem, so the relative path resolves as long as
     * the caller lays out ../../results/hw next to this binary's cwd (see
     * docs/orin-port.md run instructions). cycles_per_sec has no hardware
     * meaning on this leg (clock_gettime is already ns); 1000000000 is
     * recorded so the column stays populated and self-consistent with the
     * already-ns p50/p99/max fields, not a real cycle rate -- called out in
     * notes so it is never mistaken for one. */
    char csvpath[512];
    snprintf(csvpath, sizeof csvpath, "%s/orin-ipc-latest.csv", RESULTS_REL);
    FILE *csv = fopen(csvpath, "a");
    if (csv != NULL) {
        time_t now = time(NULL);
        fprintf(csv, "%ld,%zu,%u,%llu,%llu,%llu,%llu,%s\n",
                (long)now, kept, (unsigned)FRAME_PAYLOAD_BYTES,
                (unsigned long long)p50_ns,
                (unsigned long long)p99_ns,
                (unsigned long long)max_ns,
                1000000000ull,
                "orin-tcg-br0-tap-virtio-net;clock_gettime-ns-not-cycles");
        fclose(csv);
        fprintf(stderr, "client: appended summary to %s\n", csvpath);
    } else {
        fprintf(stderr, "client: note: could not open %s (%s); stdout summary stands\n",
                csvpath, strerror(errno));
    }

    free(samples);
    close(fd);
    return 0;
}
