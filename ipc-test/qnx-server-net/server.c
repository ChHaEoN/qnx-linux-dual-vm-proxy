/* Phase 3 (Orin, QNX-guest TCP echo endpoint over br0/virtio-net).
 *
 * The QNX-guest END of the heterogeneous QNX-safety <-> Linux-compute IPC
 * channel (docs/orin-port.md). Unlike ipc-test/qnx-server/server.c (Phase 2,
 * cloud leg, virtio-console) this listens on a TCP socket reached over the
 * host br0 bridge + tap-qnx + virtio-net -- a different I/O model, hence a
 * separate program rather than a modification of the Phase-2 file. Accepts
 * one client at a time, reads a full fixed-width frame, echoes the payload
 * back unmodified, and loops; a dropped client is not fatal -- the server
 * goes back to accept() for the next connection.
 *
 * The server never reads or writes its own clock into the frame: only the
 * initiator (linux-client) needs a timestamp to compute RTT, and it uses its
 * own clock on both send and receipt, so there is no cross-OS clock to
 * reconcile on this transport (see ipc-test/linux-client/client.c).
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
#include "frame_io.h"

#define DEFAULT_PORT 7000

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int sig)
{
    (void)sig;
    g_stop = 1;
}

static int serve_one_client(int cfd)
{
    uint8_t buf[FRAME_TOTAL_BYTES];
    unsigned long long echoed = 0;

    while (!g_stop) {
        int r = frameio_read_frame(cfd, buf);
        if (r == 1) {
            fprintf(stderr, "server: client EOF after %llu frames\n", echoed);
            return 0;
        }
        if (r < 0) {
            if (errno == EINTR && g_stop) {
                return 0;
            }
            fprintf(stderr, "server: read: %s\n", strerror(errno));
            return -1;
        }
        if (frameio_write_frame(cfd, buf) < 0) {
            fprintf(stderr, "server: write: %s\n", strerror(errno));
            return -1;
        }
        echoed++;
    }
    fprintf(stderr, "server: signalled stop after %llu frames\n", echoed);
    return 0;
}

int main(int argc, char **argv)
{
    unsigned short port = (argc > 1) ? (unsigned short)strtoul(argv[1], NULL, 10) : DEFAULT_PORT;

    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_signal;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);

    int lfd = socket(AF_INET, SOCK_STREAM, 0);
    if (lfd < 0) {
        fprintf(stderr, "server: socket: %s\n", strerror(errno));
        return 1;
    }

    int one = 1;
    if (setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one) < 0) {
        fprintf(stderr, "server: setsockopt(SO_REUSEADDR): %s\n", strerror(errno));
        close(lfd);
        return 1;
    }
    /* TCP_NODELAY on the accepted fd (not this listening fd) matters for
     * RTT: Nagle's algorithm would coalesce the small echo with a delayed
     * ACK and add tens of ms of jitter to every sample. Set per-connection
     * below, after accept(). */

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof addr);
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);

    if (bind(lfd, (struct sockaddr *)&addr, sizeof addr) < 0) {
        fprintf(stderr, "server: bind(:%u): %s\n", port, strerror(errno));
        close(lfd);
        return 1;
    }
    if (listen(lfd, 1) < 0) {
        fprintf(stderr, "server: listen: %s\n", strerror(errno));
        close(lfd);
        return 1;
    }

    fprintf(stderr, "server: echo endpoint listening on 0.0.0.0:%u (frame=%u bytes)\n",
            port, (unsigned)FRAME_TOTAL_BYTES);

    while (!g_stop) {
        struct sockaddr_in peer;
        socklen_t peerlen = sizeof peer;
        int cfd = accept(lfd, (struct sockaddr *)&peer, &peerlen);
        if (cfd < 0) {
            if (errno == EINTR) {
                continue;
            }
            fprintf(stderr, "server: accept: %s\n", strerror(errno));
            break;
        }
        if (setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one) < 0) {
            fprintf(stderr, "server: setsockopt(TCP_NODELAY): %s\n", strerror(errno));
        }
        fprintf(stderr, "server: client connected from %s:%u\n",
                inet_ntoa(peer.sin_addr), (unsigned)ntohs(peer.sin_port));

        int rc = serve_one_client(cfd);
        close(cfd);
        if (rc < 0) {
            fprintf(stderr, "server: client session ended with an error; awaiting next client\n");
        }
    }

    close(lfd);
    fprintf(stderr, "server: clean shutdown\n");
    return 0;
}
