/* Phase 2 (cloud, QNX-guest virtio-console echo endpoint).
 *
 * The qnx-guest END of the host<->guest console IPC channel (ADR-002 /
 * docs/phase2-topology-decision.md). Opens the guest-side virtio-console
 * device, reads a full fixed-width frame, echoes the payload back unmodified,
 * and loops. The transport is the qvm virtio-console vdev that mediates the
 * EL2 host <-> EL1 guest partition boundary; it does NOT route through host
 * io-sock (down on this leg).
 *
 * Honest framing: study-level mechanism-alive proxy across a TCG-emulated qvm
 * boundary, not a transport benchmark.
 *
 * RUNTIME-SPIKE (resolved 2026-07-28): the guest sees no device node for the
 * virtio-console vdev until it starts the devc-virtio driver itself, matching
 * the vdev's loc/intr from g2.conf: `devc-virtio 0x20000000,42 &`. That
 * creates /dev/vcon2 (vcon1 is already taken by the guest's pl011 console).
 * See ../qnx-host-client/README.md and ../../scripts/qhv/guest-post_start.custom
 * (which starts devc-virtio before this server).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>

#include "frame.h"
#include "console_io.h"

#define DEFAULT_DEV "/dev/vcon2"

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int sig)
{
    (void)sig;
    g_stop = 1;
}

int main(int argc, char **argv)
{
    const char *dev = (argc > 1) ? argv[1] : DEFAULT_DEV;

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    int fd = open(dev, O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "server: open(%s): %s\n", dev, strerror(errno));
        return 1;
    }
    if (cio_set_raw(fd) < 0) {
        fprintf(stderr, "server: cio_set_raw(%s): %s\n", dev, strerror(errno));
        close(fd);
        return 1;
    }
    fprintf(stderr, "server: echo endpoint up on %s (frame=%u bytes)\n",
            dev, (unsigned)FRAME_TOTAL_BYTES);

    uint8_t buf[FRAME_TOTAL_BYTES];
    unsigned long long echoed = 0;

    while (!g_stop) {
        int r = cio_read_frame(fd, buf);
        if (r == 1) {
            fprintf(stderr, "server: EOF after %llu frames; exiting\n", echoed);
            break;
        }
        if (r < 0) {
            if (errno == EINTR && g_stop) {
                break;
            }
            fprintf(stderr, "server: read: %s\n", strerror(errno));
            close(fd);
            return 1;
        }

        /* Echo the frame back verbatim: seq + tstamp + payload unchanged, so
         * the initiator can match the reply and measure full RTT. */
        if (cio_write_frame(fd, buf) < 0) {
            fprintf(stderr, "server: write: %s\n", strerror(errno));
            close(fd);
            return 1;
        }
        echoed++;
    }

    close(fd);
    fprintf(stderr, "server: clean shutdown after %llu frames\n", echoed);
    return 0;
}
