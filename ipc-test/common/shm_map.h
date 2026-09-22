/* A6, OD12 (2026-09-22) -- map the shared region a shm channel lives in.
 *
 * One declaration, two implementations, chosen by which file is linked -- never
 * by #ifdef in monitor.c, which stays one source for the guest and the host:
 *
 *   shm_map_posix.c  SPEC is a file path (the host: /dev/shm/...), mmap'd
 *                    MAP_SHARED. The file must already exist and be at least
 *                    SHM_CHAN_MIN_BYTES; it is never created or resized here.
 *   shm_map_qnx.c    SPEC is "ivshmem" (the guest): the first QEMU ivshmem PCI
 *                    function (1af4:1110), its BAR2, mapped CACHEABLE.
 *
 * Returns the base address and sets *len, or returns NULL after printing why.
 * `what` receives a one-line description of what was mapped, for the log.
 */
#ifndef IPC_TEST_SHM_MAP_H
#define IPC_TEST_SHM_MAP_H

#include <stddef.h>

void *shm_map(const char *spec, size_t *len, char *what, size_t what_len);

#endif /* IPC_TEST_SHM_MAP_H */
