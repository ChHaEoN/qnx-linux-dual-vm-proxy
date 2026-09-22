/* A6, OD12 (2026-09-22) -- map the shared region a shm channel lives in.
 *
 * One declaration, two implementations, chosen by which file is linked -- never
 * by #ifdef in monitor.c, which stays one source for the guest and the host:
 *
 *   shm_map_posix.c  SPEC is a file path (the host: /dev/shm/...), mmap'd
 *                    MAP_SHARED. The file must already exist and be at least
 *                    SHM_CHAN_MIN_BYTES; it is never created or resized here.
 *   shm_map_qnx.c    SPEC is "ivshmem" (the guest): the QEMU ivshmem PCI
 *                    function (1af4:1110), its BAR2, mapped CACHEABLE.
 *
 * Returns the base address and sets *len, or returns NULL after printing why.
 * `what` receives a one-line description of what was mapped, for the log.
 */
#ifndef IPC_TEST_SHM_MAP_H
#define IPC_TEST_SHM_MAP_H

#include <stddef.h>

void *shm_map(const char *spec, size_t *len, char *what, size_t what_len);

/* Guest only: configure the ivshmem function once -- place BAR2 and BAR0,
 * enable decoding -- and write the marker every later mapping reads, so no two
 * processes ever program the function's configuration space at once. Run it
 * synchronously before any monitor starts. A host has nothing to configure and
 * returns 0. 0 on success, -1 after printing why. */
int shm_configure(const char *spec, char *what, size_t what_len);

/* THE NOTIFIED VARIANT (OD12, 2026-09-22; see shm_chan.h). A slot plus a kick
 * channel, and a way to tell the client its reply is ready.
 *
 *   host  (shm_map_posix.c): SPEC is an ivshmem server's socket -- the monitor
 *         joins as a peer, maps the memory the server hands it, and keeps a
 *         table of the other peers' eventfds; KICK is a UNIX socket path it
 *         listens on, one client at a time.
 *   guest (shm_map_qnx.c): SPEC is "ivshmem" -- BAR2 for the slot, BAR0 for the
 *         Doorbell register, both from the shm_configure() marker; KICK is the
 *         virtio console's tty, put in raw mode.
 * OFFSET places the slot in the region (a multiple of SHM_CHAN_LINE). */
struct shm_kick;

struct shm_kick_stats {
	unsigned long long kick_bytes;    /* SHM_KICK_BYTE received */
	unsigned long long echoes;        /* SHM_ECHO_BYTE received and answered */
	unsigned long long stray_bytes;   /* anything else received */
	unsigned long long notify_kicks;  /* SHM_KICK_BYTE sent back */
	unsigned long long rings;         /* doorbells rung */
	unsigned long long ring_misses;   /* host: a peer not yet in the table when ringing */
	unsigned long long notify_fail;   /* a notification that could not be sent */
	unsigned long long clients;       /* host: kick connections accepted */
};

struct shm_kick *shm_kick_open(const char *spec, size_t offset, const char *kick,
                               void **slot, char *what, size_t what_len);

/* Block until the kick channel delivers. Echo bytes are answered inside and
 * never returned. 1: at least one SHM_KICK_BYTE arrived; 0: nothing to do (a
 * client left, only stray or echo bytes, an interrupted wait); -1: an error
 * the server cannot continue from. */
int shm_kick_wait(struct shm_kick *k);

/* Tell the client its reply is in the slot: via SHM_VIA_KICK, SHM_VIA_DOORBELL
 * (to `peer`), or SHM_VIA_BURST (`count` doorbells to `peer`, a test). 0 or -1. */
int shm_kick_notify(struct shm_kick *k, unsigned via, unsigned peer, unsigned count);

void shm_kick_get_stats(const struct shm_kick *k, struct shm_kick_stats *st);

#endif /* IPC_TEST_SHM_MAP_H */
