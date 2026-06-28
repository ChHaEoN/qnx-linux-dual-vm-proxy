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
 * RUNTIME-SPIKE UNKNOWN: the exact guest-side device node the qvm
 * virtio-console vdev presents to the guest is not settled from docs alone
 * (see qnx-host-client/README). DEFAULT_DEV below is the conventional guess;
 * pass the real node as argv[1] once the qvm/TCG console-wiring spike resolves
 * it.
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

#define DEFAULT_DEV "/dev/con1"

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
