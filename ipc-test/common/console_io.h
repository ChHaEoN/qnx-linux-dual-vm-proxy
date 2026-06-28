/* Phase 2 (cloud, QNX<->QNX over qvm virtio-console) — shared byte-stream IO
 * and single-OS timing helpers.
 *
 * virtio-console fds are BYTE STREAMS, not message-framed: a single read() or
 * write() may transfer fewer than FRAME_TOTAL_BYTES. Both ends must loop until
 * a whole frame is in/out, which is why this lives in one shared header — the
 * QNX-host initiator and the QNX-guest endpoint use identical framing IO so the
 * two cannot disagree on partial-transfer handling.
 *
 * Timing is QNX ClockCycles() (single-OS leg). cycles_per_sec is read from
 * SYSPAGE_ENTRY(qtime)->cycles_per_sec to convert cycle deltas to ns.
 */
#ifndef IPC_TEST_CONSOLE_IO_H
#define IPC_TEST_CONSOLE_IO_H

#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

#include "frame.h"

/* Cycles-per-second for the ClockCycles() time-base on this core. */
static inline uint64_t cio_cycles_per_sec(void)
{
    return (uint64_t)SYSPAGE_ENTRY(qtime)->cycles_per_sec;
}

static inline uint64_t cio_now_cycles(void)
{
    return (uint64_t)ClockCycles();
}

static inline uint64_t cio_cycles_to_ns(uint64_t cycles, uint64_t cps)
{
    if (cps == 0u) {
        return 0u;
    }
    /* 64-bit overflow guard: cycles * 1e9 overflows above ~18 s at 1 GHz, so
     * split the conversion to keep the per-sample RTT range safe. */
    uint64_t whole = cycles / cps;
    uint64_t frac = cycles % cps;
    return whole * 1000000000ull + (frac * 1000000000ull) / cps;
}

/* Read exactly FRAME_TOTAL_BYTES into buf, looping over partial reads.
 * Returns 0 on success, -1 on error (errno set), 1 on clean EOF. */
static inline int cio_read_frame(int fd, uint8_t *buf)
{
    size_t got = 0;
    while (got < FRAME_TOTAL_BYTES) {
        ssize_t n = read(fd, buf + got, FRAME_TOTAL_BYTES - got);
        if (n > 0) {
            got += (size_t)n;
        } else if (n == 0) {
            return (got == 0) ? 1 : -1;  /* EOF mid-frame is a protocol error */
        } else if (errno == EINTR) {
            continue;
        } else {
            return -1;
        }
    }
    return 0;
}

/* Write exactly FRAME_TOTAL_BYTES from buf, looping over partial writes.
 * Returns 0 on success, -1 on error (errno set). */
static inline int cio_write_frame(int fd, const uint8_t *buf)
{
    size_t put = 0;
    while (put < FRAME_TOTAL_BYTES) {
        ssize_t n = write(fd, buf + put, FRAME_TOTAL_BYTES - put);
        if (n > 0) {
            put += (size_t)n;
        } else if (n < 0 && errno == EINTR) {
            continue;
        } else {
            return -1;
        }
    }
    return 0;
}

#endif /* IPC_TEST_CONSOLE_IO_H */
