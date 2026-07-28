/* Phase 2 (cloud, QNX-host -> QNX-guest over qvm virtio-console).
 *
 * The qnx-qhv HOST end of the host<->guest console IPC channel (ADR-002 /
 * docs/phase2-topology-decision.md). Opens the host end of the qvm
 * virtio-console channel, runs a warm-up burst (discarded) then a timed run:
 * each iteration stamps ClockCycles() into the frame, sends it, awaits the
 * echo, and records the RTT in cycles. After the run it converts samples to ns
 * via cycles_per_sec and reports P50 / P99 / Max.
 *
 * Single-OS time-base: both ends are QNX, so RTT is measured purely with
 * ClockCycles() on the host (no cross-clock skew on this leg; that re-enters at
 * Phase 3 / Orin with the Linux end).
 *
 * Honest framing: study-level mechanism-alive proxy across a TCG-emulated qvm
 * boundary. The RTT is dominated by TCG emulation overhead, NOT a meaningful
 * transport cost — read P50/P99 as proof the IPC path is wired and stable, not
 * as a transport benchmark.
 *
 * RUNTIME-SPIKE (resolved 2026-07-28): g2.conf binds the virtio-console vdev
 * to `hostdev /dev/ptyp0` (a QNX devc-pty master); qvm itself opens that
 * master end, so the host-side initiator opens the paired pty SLAVE,
 * /dev/ttyp0, to reach the same channel. See ../qnx-host-client/README.md.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <sys/select.h>
#include <sys/time.h>

#include "frame.h"
#include "console_io.h"

#define DEFAULT_ITERS    100000u
#define DEFAULT_WARMUP   1000u
#define DEFAULT_DEV      "/dev/ttyp0"
#define RESULTS_REL      "../../results/cloud"

/* Client-local read timeout (termios VTIME, deciseconds): unlike the server
 * (which must block indefinitely for the next request), the initiator
 * should never hang forever on a stalled link -- a timeout turns a silent
 * hang into a diagnosable error. Layered on top of cio_set_raw() locally
 * (NOT in the shared header: applying this to the server caused it to treat
 * ordinary idle time waiting for the client as EOF, a real regression
 * caught empirically on this spike). */
#define CLIENT_READ_TIMEOUT_DS 100

static int client_set_read_timeout(int fd)
{
    struct termios t;
    if (tcgetattr(fd, &t) < 0) {
        return (errno == ENOTTY) ? 0 : -1;
    }
    t.c_cc[VMIN] = 0;
    t.c_cc[VTIME] = CLIENT_READ_TIMEOUT_DS;
    return tcsetattr(fd, TCSANOW, &t);
}

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

static void usage(const char *argv0)
{
    fprintf(stderr,
        "usage: %s [iters] [device] [warmup]\n"
        "  iters   timed iterations (default %u)\n"
        "  device  host end of the qvm virtio-console (default %s)\n"
        "  warmup  discarded warm-up iterations (default %u)\n",
        argv0, DEFAULT_ITERS, DEFAULT_DEV, DEFAULT_WARMUP);
}

int main(int argc, char **argv)
{
    unsigned long iters = DEFAULT_ITERS;
    unsigned long warmup = DEFAULT_WARMUP;
    const char *dev = DEFAULT_DEV;

    if (argc > 1) {
        if (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0) {
            usage(argv[0]);
            return 0;
        }
        iters = strtoul(argv[1], NULL, 10);
    }
    if (argc > 2) {
        dev = argv[2];
    }
    if (argc > 3) {
        warmup = strtoul(argv[3], NULL, 10);
    }
    if (iters == 0) {
        fprintf(stderr, "client: iters must be > 0\n");
        return 2;
    }

    uint64_t cps = cio_cycles_per_sec();
    if (cps == 0) {
        fprintf(stderr, "client: cycles_per_sec is 0; cannot convert to ns\n");
        return 1;
    }

    int fd = open(dev, O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "client: open(%s): %s\n", dev, strerror(errno));
        return 1;
    }
    if (cio_set_raw(fd) < 0) {
        fprintf(stderr, "client: cio_set_raw(%s): %s\n", dev, strerror(errno));
        close(fd);
        return 1;
    }
    if (client_set_read_timeout(fd) < 0) {
        fprintf(stderr, "client: client_set_read_timeout(%s): %s\n", dev, strerror(errno));
        close(fd);
        return 1;
    }

    /* Prime the link before starting the protocol: on the FIRST write-
     * triggered exchange, qvm's hostdev pty delivers a short one-time
     * artifact (a handful of extra bytes, empirically observed and
     * reproducible across boots) ahead of the real echo -- almost certainly
     * first-kick vring/queue-negotiation overhead in qvm's virtio-console
     * bridging, not anything either endpoint's protocol emits. Send one
     * throwaway frame and drain the fd until it goes quiet, discarding
     * everything (including the throwaway frame's own echo), so the real
     * warm-up + timed loop below starts from a clean frame boundary. This
     * does NOT assume a fixed junk-byte count.
     */
    {
        uint8_t junk[FRAME_TOTAL_BYTES];
        memset(junk, 0xAA, sizeof junk);
        if (cio_write_frame(fd, junk) < 0) {
            fprintf(stderr, "client: priming write: %s\n", strerror(errno));
            close(fd);
            return 1;
        }
        for (;;) {
            fd_set rfds;
            struct timeval tv;
            FD_ZERO(&rfds);
            FD_SET(fd, &rfds);
            tv.tv_sec = 1;
            tv.tv_usec = 0;
            int sr = select(fd + 1, &rfds, NULL, NULL, &tv);
            if (sr <= 0) {
                break;
            }
            uint8_t drain[256];
            ssize_t n = read(fd, drain, sizeof drain);
            if (n <= 0) {
                break;
            }
        }
    }

    fprintf(stderr, "client: link up on %s; cps=%llu, frame=%u bytes\n",
            dev, (unsigned long long)cps, (unsigned)FRAME_TOTAL_BYTES);

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

        int stray = cio_drain_stray(fd);
        if (stray < 0) {
            fprintf(stderr, "client: cio_drain_stray at iter %lu: %s\n", i, strerror(errno));
            free(samples);
            close(fd);
            return 1;
        }
        if (stray > 0) {
            fprintf(stderr, "client: WARNING discarded %d stray byte(s) before iter %lu\n", stray, i);
        }

        /* RUNTIME-SPIKE finding (2026-07-28, UNRESOLVED): back-to-back
         * exchanges with no gap stall within single-digit iterations (a
         * real hang under the CLIENT_READ_TIMEOUT_DS bound above, not a
         * framing bug -- every frame up to the stall point was byte-exact).
         * This pacing gap raised the iteration count reached in SOME runs
         * but did NOT reliably prevent the stall (a larger gap and a much
         * larger read timeout both still stalled, at *earlier* iterations
         * in some runs) -- non-deterministic across boots, most likely
         * qvm/TCG virtio-queue kick/notify timing, not something fixed
         * from this side. Left in as an occasionally-helpful mitigation,
         * NOT a proven fix -- see ipc-test/qnx-host-client/README.md and
         * docs/findings.md (2026-07-28) for the honest account. Measured
         * OUTSIDE the RTT sample window below either way. */
        usleep(20000);

        f.seq = (uint64_t)i;
        f.tstamp_cycles = cio_now_cycles();
        frame_pack(&f, wire);

        if (cio_write_frame(fd, wire) < 0) {
            fprintf(stderr, "client: write at iter %lu: %s\n", i, strerror(errno));
            free(samples);
            close(fd);
            return 1;
        }

        int r = cio_read_frame(fd, wire);
        if (r != 0) {
            fprintf(stderr, "client: %s at iter %lu\n",
                    (r == 1) ? "unexpected EOF" : strerror(errno), i);
            free(samples);
            close(fd);
            return 1;
        }
        uint64_t end = cio_now_cycles();

        ipc_frame_t echo;
        frame_unpack(wire, &echo);
        if (echo.seq != f.seq) {
            fprintf(stderr, "client: echo seq mismatch at iter %lu (got %llu)\n",
                    i, (unsigned long long)echo.seq);
            fprintf(stderr, "client: sent :");
            for (size_t k = 0; k < FRAME_TOTAL_BYTES; ++k) {
                uint8_t sb[FRAME_TOTAL_BYTES];
                frame_pack(&f, sb);
                fprintf(stderr, " %02x", sb[k]);
            }
            fprintf(stderr, "\nclient: got  :");
            for (size_t k = 0; k < FRAME_TOTAL_BYTES; ++k) {
                fprintf(stderr, " %02x", wire[k]);
            }
            fprintf(stderr, "\n");
            free(samples);
            close(fd);
            return 1;
        }

        if (i >= warmup) {
            samples[kept++] = end - echo.tstamp_cycles;
        }
    }

    qsort(samples, kept, sizeof *samples, cmp_u64);
    uint64_t p50_c = percentile(samples, kept, 50.0);
    uint64_t p99_c = percentile(samples, kept, 99.0);
    uint64_t max_c = (kept > 0) ? samples[kept - 1] : 0;

    uint64_t p50_ns = cio_cycles_to_ns(p50_c, cps);
    uint64_t p99_ns = cio_cycles_to_ns(p99_c, cps);
    uint64_t max_ns = cio_cycles_to_ns(max_c, cps);

    printf("samples=%zu payload=%u cps=%llu\n",
           kept, (unsigned)FRAME_PAYLOAD_BYTES, (unsigned long long)cps);
    printf("P50=%llu ns  P99=%llu ns  Max=%llu ns\n",
           (unsigned long long)p50_ns,
           (unsigned long long)p99_ns,
           (unsigned long long)max_ns);
    printf("(P50 sanity: link alive if non-zero and stable)\n");

    /* Append one CSV row in the results/cloud schema (see header.csv). The path
     * is best-effort; a failure here must not lose the stdout summary above. */
    char csvpath[512];
    snprintf(csvpath, sizeof csvpath, "%s/cloud-ipc-latest.csv", RESULTS_REL);
    FILE *csv = fopen(csvpath, "a");
    if (csv != NULL) {
        time_t now = time(NULL);
        fprintf(csv, "%ld,%zu,%u,%llu,%llu,%llu,%llu,%s\n",
                (long)now, kept, (unsigned)FRAME_PAYLOAD_BYTES,
                (unsigned long long)p50_ns,
                (unsigned long long)p99_ns,
                (unsigned long long)max_ns,
                (unsigned long long)cps,
                "tcg-qvm-virtio-console");
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
