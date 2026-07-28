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
 *
 * SENTINEL-KICK RECOVERY (2026-07-28, docs/findings.md): a read timeout is
 * recovered by writing a FRAME_SENTINEL_SEQ frame (never a resend of the
 * real in-flight frame -- an earlier resend experiment reliably corrupted
 * the next iteration's alignment, see README) and reading until the real
 * echo (seq match) surfaces or the sentinel's own harmless bounce is seen
 * and discarded. See sentinel_recover() below.
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

/* Sentinel-kick recovery bounds: a "round" is one sentinel write followed by
 * up to SENTINEL_READS_PER_ROUND frame reads (each bound by the same
 * CLIENT_READ_TIMEOUT_DS as normal traffic); SENTINEL_MAX_ROUNDS bounds how
 * many times we re-kick before giving up. This keeps recovery a diagnosable,
 * bounded retry rather than an unbounded wait. */
#define SENTINEL_MAX_ROUNDS        5
#define SENTINEL_READS_PER_ROUND   3

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

/* Recover from a read timeout (cio_read_frame() returned 1: zero bytes
 * arrived before CLIENT_READ_TIMEOUT_DS elapsed) WITHOUT resending the real,
 * still-in-flight frame -- see the file header and README for why a resend
 * corrupts the next iteration's alignment while a sentinel does not: the
 * guest's echo loop is a dumb byte-stream echo, so a resent REAL frame is
 * indistinguishable from a new request and gets a real, orphaning duplicate
 * reply; a sentinel carries no request semantics either side needs to care
 * about, so any number of stray sentinel bounces are safe to discard.
 *
 * Returns 0 if the real echo (seq == expected_seq) was recovered (the caller
 * should discard timing for this iteration -- the RTT is contaminated by
 * however long recovery took) or -1 if recovery was exhausted/unrecoverable
 * (caller should treat this the same as any other fatal link error). */
static int sentinel_recover(int fd, uint64_t expected_seq, unsigned long iter,
                             unsigned long *sentinel_recoveries,
                             unsigned long *sentinel_bounces)
{
    for (int round = 0; round < SENTINEL_MAX_ROUNDS; ++round) {
        ipc_frame_t sf;
        uint8_t swire[FRAME_TOTAL_BYTES];
        sf.seq = FRAME_SENTINEL_SEQ;
        sf.tstamp_cycles = cio_now_cycles();
        memset(sf.payload, 0, sizeof sf.payload);
        frame_pack(&sf, swire);

        fprintf(stderr,
                "client: iter %lu: read timeout; sentinel-kick round %d/%d\n",
                iter, round + 1, SENTINEL_MAX_ROUNDS);
        if (cio_write_frame(fd, swire) < 0) {
            fprintf(stderr, "client: sentinel write failed at iter %lu: %s\n",
                    iter, strerror(errno));
            return -1;
        }

        for (int attempt = 0; attempt < SENTINEL_READS_PER_ROUND; ++attempt) {
            uint8_t rbuf[FRAME_TOTAL_BYTES];
            int r = cio_read_frame(fd, rbuf);
            if (r == 1) {
                /* Timed out waiting even for the sentinel's own bounce;
                 * try another kick round rather than looping here forever. */
                break;
            }
            if (r < 0) {
                fprintf(stderr,
                        "client: sentinel-recovery read error at iter %lu: %s\n",
                        iter, strerror(errno));
                return -1;
            }
            ipc_frame_t got;
            frame_unpack(rbuf, &got);
            if (got.seq == expected_seq) {
                fprintf(stderr,
                        "client: iter %lu: recovered real echo via sentinel kick "
                        "(sample discarded, timing contaminated)\n", iter);
                (*sentinel_recoveries)++;
                return 0;
            }
            if (frame_is_sentinel(&got)) {
                fprintf(stderr,
                        "client: iter %lu: discarded a stale sentinel bounce\n", iter);
                (*sentinel_bounces)++;
                continue;
            }
            fprintf(stderr,
                    "client: iter %lu: unexpected seq %llu during sentinel "
                    "recovery (wanted %llu or the sentinel value)\n",
                    iter, (unsigned long long)got.seq,
                    (unsigned long long)expected_seq);
            return -1;
        }
    }
    fprintf(stderr,
            "client: iter %lu: sentinel-recovery exhausted after %d round(s)\n",
            iter, SENTINEL_MAX_ROUNDS);
    return -1;
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
    unsigned long sentinel_recoveries = 0;
    unsigned long sentinel_bounces = 0;
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
        if (r == 1) {
            /* Zero bytes arrived before CLIENT_READ_TIMEOUT_DS elapsed --
             * the missed-notification stall (docs/findings.md, 2026-07-28).
             * Recover with a sentinel kick instead of aborting or resending
             * the real frame; see sentinel_recover()'s header comment. */
            if (sentinel_recover(fd, f.seq, i, &sentinel_recoveries, &sentinel_bounces) != 0) {
                fprintf(stderr, "client: unrecoverable stall at iter %lu\n", i);
                free(samples);
                close(fd);
                return 1;
            }
            /* Real echo recovered and seq alignment restored; this
             * iteration's timing is contaminated by recovery time, so it
             * contributes no RTT sample -- move on to the next iteration. */
            continue;
        }
        if (r < 0) {
            fprintf(stderr, "client: %s at iter %lu\n", strerror(errno), i);
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
    printf("sentinel_recoveries=%lu sentinel_bounces=%lu"
           " (see ipc-test/qnx-host-client/README.md; 0/0 means no stall hit this run)\n",
           sentinel_recoveries, sentinel_bounces);

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
