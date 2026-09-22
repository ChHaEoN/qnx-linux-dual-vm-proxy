/* shmchan.c -- the probe's side of the shared-memory transport (A6, OD12).
 *
 * Built by the run into libshmchan.so, together with
 * ipc-test/common/shm_map_posix.c, and called from latency_probe.py through
 * ctypes:
 *
 *   gcc -O2 -Wall -Wextra -Werror -shared -fPIC -I ipc-test/common \
 *       -o libshmchan.so shmchan.c ipc-test/common/shm_map_posix.c
 *
 * WHY C AND NOT PYTHON. The channel's correctness rests on ordering: the frame
 * must be visible before the doorbell that announces it (shm_chan.h). Python
 * has no store-release or load-acquire, and Armv8 is weakly ordered, so a
 * probe that wrote the slot from Python could publish a doorbell ahead of its
 * frame. The TIMING stays in Python, around this call, exactly where it is for
 * TCP and UDP -- so the instrument's own cost is the same interpreter loop on
 * every transport, and only what happens inside the call differs.
 *
 * The wait is a spin, like the server's: there is no interrupt on this path.
 */
#include <stdint.h>
#include <time.h>

#include "shm_chan.h"
#include "shm_map.h"

#define SHMCHAN_OK       0
#define SHMCHAN_TIMEOUT  1
#define SHMCHAN_NOTREADY 2
#define SPIN_CHECK       1024u

static uint64_t now_ns(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

/* 1 when a server has published the magic and version, else 0. */
int shmchan_ready(void *base)
{
	return shm_chan_ready(base);
}

/* One round trip: publish `req`, wait for the reply to THIS doorbell, copy it
 * into `rsp`. Returns SHMCHAN_OK, SHMCHAN_TIMEOUT (no reply within timeout_ns;
 * the reply may still arrive later, and the caller must not reuse the slot --
 * the probe aborts the arm, as on TCP), or SHMCHAN_NOTREADY (no server). */
int shmchan_roundtrip(void *base, const uint8_t *req, uint8_t *rsp, uint64_t timeout_ns)
{
	uint64_t const n = __atomic_load_n(shm_chan_u64(base, SHM_CHAN_OFF_REQ_SEQ), __ATOMIC_RELAXED) + 1u;
	uint64_t deadline;
	unsigned spins = 0;

	if (!shm_chan_ready(base)) {
		return SHMCHAN_NOTREADY;
	}
	shm_chan_put_frame(base, SHM_CHAN_OFF_REQ, req);
	shm_chan_store(base, SHM_CHAN_OFF_REQ_SEQ, n);
	deadline = now_ns() + timeout_ns;
	while (shm_chan_load(base, SHM_CHAN_OFF_RSP_SEQ) != n) {
		shm_chan_relax();
		if (++spins >= SPIN_CHECK) {
			spins = 0;
			if (now_ns() > deadline) {
				return SHMCHAN_TIMEOUT;
			}
		}
	}
	shm_chan_get_frame(base, SHM_CHAN_OFF_RSP, rsp);
	return SHMCHAN_OK;
}
