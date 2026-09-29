/* A6, OD12 (2026-09-22) -- a peer of an ivshmem server, on a Linux host.
 *
 * The server (orin-native/gpu-concurrency/ivshmem_server.py, or QEMU's own)
 * hands every peer the shared memory's fd, the peer's own id, and one eventfd
 * per vector for itself and for every other peer; see that file's header for
 * the protocol. QEMU's ivshmem-doorbell device is one peer; a process using
 * this is another. Signalling a peer is a write of 1 to that peer's eventfd;
 * being signalled is a read of one's own.
 *
 * Up to IVSHM_VECTORS_MAX vectors per peer (2026-09-29: two, so one guest can
 * serve two MSI-X ways in at once); this peer waits on its own vector 0 only and
 * closes any other own vector. Linux only (eventfd, SCM_RIGHTS); used by the host-side monitor and by the
 * probe's libshmchan.so, never by the guest.
 */
#ifndef IPC_TEST_IVSHM_CLIENT_H
#define IPC_TEST_IVSHM_CLIENT_H

#include <stdint.h>
#include <stddef.h>

#define IVSHM_PEERS_MAX 256
#define IVSHM_VECTORS_MAX 4

struct ivshm_client {
	int sock;                     /* the connection to the server; closing it leaves */
	int64_t my_id;
	int shm_fd;
	int my_efd;                   /* read this to be signalled; -1 until the server sends it */
	int my_nvec;                  /* own vectors the server sent (vector 0 kept, the rest closed) */
	int npeers;
	struct { int64_t id; int nvec; int efd[IVSHM_VECTORS_MAX]; } peers[IVSHM_PEERS_MAX];
};

/* Connect and complete the setup: version, own id, shm fd, then messages until
 * the own eventfd has arrived (bounded by timeout_ms). 0, or -1 with err set. */
int ivshm_client_connect(struct ivshm_client *c, const char *path, int timeout_ms, char *err, size_t errlen);

/* Process every message already waiting (peers arriving or leaving); never
 * blocks. 0, or -1 if the server went away or broke the protocol. */
int ivshm_client_poll(struct ivshm_client *c);

/* That peer's eventfd from the table as it stands -- no system call; -1 if
 * unknown. The host monitor uses this on its reply path, so the notification
 * costs the same one write whether or not the server has said anything. */
int ivshm_client_lookup(const struct ivshm_client *c, int64_t id);

/* The same for that peer's vector vec; -1 if the peer or that vector is unknown. */
int ivshm_client_lookup_vec(const struct ivshm_client *c, int64_t id, int vec);

/* That peer's eventfd, reading server messages for up to timeout_ms until it
 * appears; -1 if it does not. Off the hot path: for a table miss only. */
int ivshm_client_wait_peer(struct ivshm_client *c, int64_t id, int timeout_ms);

/* The same for that peer's vector vec. */
int ivshm_client_wait_peer_vec(struct ivshm_client *c, int64_t id, int vec, int timeout_ms);

/* Signal a known eventfd once. 0, or -1 if the write failed. */
int ivshm_client_signal(int efd);

void ivshm_client_close(struct ivshm_client *c);

#endif /* IPC_TEST_IVSHM_CLIENT_H */
