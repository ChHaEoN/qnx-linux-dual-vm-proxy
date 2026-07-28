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
#include <termios.h>
#include <sys/select.h>
#include <sys/time.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>

#include "frame.h"

/* Both console endpoints here (the host pty slave /dev/ttyp0 and the guest
 * devc-virtio node /dev/vcon2) default to line-buffered "cooked"/edited tty
 * mode: input is held until a newline byte appears. The wire frame is raw
 * binary (arbitrary byte values, no guaranteed '\n'), so without this a
 * frame can sit in the line-discipline buffer forever -- a real deadlock
 * observed empirically on the qvm/TCG spike, not a hypothetical. Put the fd
 * into raw mode (no canon/echo/signals) right after open(). ENOTTY (fd is a
 * plain file, e.g. in a future non-tty test harness) is not an error here. */
static inline int cio_set_raw(int fd)
{
    struct termios t;
    if (tcgetattr(fd, &t) < 0) {
        return (errno == ENOTTY) ? 0 : -1;
    }
    cfmakeraw(&t);
    /* VMIN=1/VTIME=0 (cfmakeraw's own default): block until at least one
     * byte arrives. Correct for the SERVER, which must wait indefinitely
     * for the next request; a bounded read timeout, where wanted, is a
     * caller-local policy layered on top (see qnx-host-client/client.c),
     * not a shared default -- an idle server timing out and treating that
     * as EOF was a real regression caught empirically on this spike. */
    if (tcsetattr(fd, TCSANOW, &t) < 0) {
        return -1;
    }
    /* Discard stale bytes queued before this end started reading (observed
     * empirically: qvm writes a short preamble to its hostdev pty master the
     * moment it arms the vdev, long before either endpoint's protocol loop
     * starts -- those bytes sit in the queue and corrupt the very first
     * frame's alignment otherwise). ENOTTY here is likewise not an error. */
    if (tcflush(fd, TCIOFLUSH) < 0 && errno != ENOTTY) {
        return -1;
    }
    return 0;
}

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

/* Defensive resync: discard any bytes already sitting in the read queue,
 * with NO blocking wait -- call right before a write when the protocol
 * expects the link to be idle (a correctly-synced request/response
 * exchange should never have anything pending here). Returns the number of
 * stray bytes discarded (0 in the nominal case), or -1 on a real error. */
static inline int cio_drain_stray(int fd)
{
    int total = 0;
    for (;;) {
        fd_set rfds;
        struct timeval tv;
        FD_ZERO(&rfds);
        FD_SET(fd, &rfds);
        tv.tv_sec = 0;
        tv.tv_usec = 0;
        int sr = select(fd + 1, &rfds, NULL, NULL, &tv);
        if (sr < 0) {
            return (errno == EINTR) ? total : -1;
        }
        if (sr == 0 || !FD_ISSET(fd, &rfds)) {
            return total;
        }
        uint8_t junk[256];
        ssize_t n = read(fd, junk, sizeof junk);
        if (n <= 0) {
            return total;
        }
        total += (int)n;
    }
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
