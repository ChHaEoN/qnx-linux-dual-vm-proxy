/* Phase 3 (Orin, QNX-guest TCP server <-> native-Linux TCP client over
 * br0/virtio-net) — shared TCP byte-stream framing IO.
 *
 * A TCP socket fd is a byte stream exactly like the Phase-2 virtio-console
 * fd, so the same partial-read/partial-write loop applies verbatim. Unlike
 * ../console_io.h this header stays QNX/Linux-portable on purpose (no
 * <sys/neutrino.h>, no termios): the Linux client and the QNX guest server
 * both include it, and neither needs raw-tty handling or ClockCycles() —
 * a TCP socket has no line discipline to fight, and each side times with
 * its own OS's native clock (the QNX side never reads a clock for this
 * transport at all; see qnx-server-net/server.c).
 */
#ifndef IPC_TEST_FRAME_IO_H
#define IPC_TEST_FRAME_IO_H

#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <unistd.h>

#include "frame.h"

/* Read exactly FRAME_TOTAL_BYTES into buf, looping over partial reads.
 * Returns 0 on success, -1 on error (errno set), 1 on clean EOF. */
static inline int frameio_read_frame(int fd, uint8_t *buf)
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
static inline int frameio_write_frame(int fd, const uint8_t *buf)
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

#endif /* IPC_TEST_FRAME_IO_H */
