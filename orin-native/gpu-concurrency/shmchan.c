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
 *
 * THE NOTIFIED VARIANT (OD12, 2026-09-22) is here too, and built the same way
 * with ipc-test/common/ivshm_client.c added. shmchan_kick_roundtrip() never
 * spins: it sends one kick byte and blocks in poll() on its wait fd -- the kick
 * socket itself, or its own ivshmem eventfd -- then drains that fd once and
 * checks the slot. It counts what woke it, so a run can show exactly one
 * notification per exchange, and it tells a LOST notification (the reply is in
 * the slot, nothing said so) from a reply that never came.
 */
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/socket.h>

#include "shm_chan.h"
#include "shm_map.h"
#include "ivshm_client.h"

#define SHMCHAN_OK       0
#define SHMCHAN_TIMEOUT  1
#define SHMCHAN_NOTREADY 2
#define SHMCHAN_BROKEN   3   /* the kick stream closed or failed */
#define SHMCHAN_LOST     4   /* the reply is in the slot but no notification came */
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

/* ---------------------------------------------------------------- notified */

/* What the waits saw, cumulatively, for the probe to report and a gate to
 * check: one notification and one wake-up per exchange, nothing else. */
struct shmchan_counts {
	uint64_t exchanges;       /* round trips attempted */
	uint64_t wakeups;         /* poll() returns with data */
	uint64_t early_wakeups;   /* woken, but the reply was not in the slot yet */
	uint64_t notifications;   /* kick bytes of the expected value, or eventfd counts */
	uint64_t stray;           /* bytes of any other value on the kick stream */
	uint64_t eagain;          /* a drain that found nothing after poll said readable */
};

static struct shmchan_counts g_counts;

void shmchan_counts(uint64_t out[6])
{
	out[0] = g_counts.exchanges;
	out[1] = g_counts.wakeups;
	out[2] = g_counts.early_wakeups;
	out[3] = g_counts.notifications;
	out[4] = g_counts.stray;
	out[5] = g_counts.eagain;
}

int shmchan_kick_ready(void *slot)
{
	return shm_chan_ready_as(slot, SHM_CHAN_MAGIC_KICK);
}

/* Drain the wait fd ONCE after poll() said it is readable: one read for an
 * eventfd (it returns and clears its whole counter), one recv for a stream,
 * counting bytes of `expect` as notifications. -1 when the stream has closed.
 *
 * FOUND BY CODE REVIEW, 2026-09-22: the stream branch first looped until
 * EAGAIN, so every kick exchange paid a second, failing recv inside the timed
 * window that no doorbell exchange paid, and the kick-versus-doorbell pairs
 * carried it as if it were the transport's. A byte that arrives later raises
 * POLLIN again and is read on the next wake-up; the loop reads again only when
 * a recv filled the whole buffer. */
static int drain(int fd, int is_eventfd, unsigned char expect)
{
	if (is_eventfd) {
		uint64_t v = 0;
		ssize_t const n = read(fd, &v, sizeof(v));
		if (n == (ssize_t)sizeof(v)) {
			g_counts.notifications += v;
		} else if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
			g_counts.eagain++;
		} else {
			return -1;
		}
		return 0;
	}
	for (;;) {
		unsigned char buf[64];
		ssize_t const n = recv(fd, buf, sizeof(buf), MSG_DONTWAIT);
		if (n == 0) {
			return -1;
		}
		if (n < 0) {
			if (errno == EINTR) {
				continue;
			}
			if (errno == EAGAIN || errno == EWOULDBLOCK) {
				g_counts.eagain++;
				return 0;
			}
			return -1;
		}
		for (ssize_t i = 0; i < n; i++) {
			if (buf[i] == expect) {
				g_counts.notifications++;
			} else {
				g_counts.stray++;
			}
		}
		if ((size_t)n < sizeof(buf)) {
			return 0;
		}
	}
}

/* Read what is waiting and throw it away, uncounted: after an untimed
 * handshake, so a late notification from it can never be charged to the first
 * timed exchange. */
void shmchan_drain_quiet(int fd, int is_eventfd)
{
	unsigned char buf[64];

	if (is_eventfd) {
		uint64_t v;
		(void)!read(fd, &v, sizeof(v));
		return;
	}
	while (recv(fd, buf, sizeof(buf), MSG_DONTWAIT) > 0) {
	}
}

/* 1 when the slot's reply matches its request (nothing outstanding), else 0. */
int shmchan_slot_answered(void *slot)
{
	return shm_chan_load(slot, SHM_CHAN_OFF_RSP_SEQ)
	    == __atomic_load_n(shm_chan_u64(slot, SHM_CHAN_OFF_REQ_SEQ), __ATOMIC_RELAXED);
}

/* Block until THIS exchange's notification has been consumed and, with a slot,
 * the reply is in it; or the deadline. SHMCHAN_OK, SHMCHAN_TIMEOUT or
 * SHMCHAN_BROKEN.
 *
 * FOUND IN REVIEW OF A FIRST DRAFT: returning as soon as the reply is in the
 * slot, before reading the notification, leaves that notification pending, and
 * the NEXT exchange then pays a stale wake-up inside its own timed window. The
 * notification is what ends the wait; the slot is checked after it. */
static int wait_notified(int wait_fd, int is_eventfd, unsigned char expect, void *slot, uint64_t n,
                         uint64_t deadline, int kick_fd)
{
	uint64_t const before = g_counts.notifications;

	for (;;) {
		/* A doorbell wait watches the kick stream as well, in the same poll:
		 * the far end closing it is a broken channel, never a stall
		 * (FOUND BY CODE REVIEW). Nothing else is ever sent on it. */
		struct pollfd p[2] = { { wait_fd, POLLIN, 0 }, { kick_fd, POLLIN, 0 } };
		nfds_t const nfds = (kick_fd >= 0 && kick_fd != wait_fd) ? 2u : 1u;
		uint64_t const t = now_ns();
		int ms, r;

		if (g_counts.notifications > before
		    && (slot == NULL || shm_chan_load(slot, SHM_CHAN_OFF_RSP_SEQ) == n)) {
			return SHMCHAN_OK;
		}
		if (t >= deadline) {
			return SHMCHAN_TIMEOUT;
		}
		ms = (int)((deadline - t + 999999u) / 1000000u);
		r = poll(p, nfds, ms);
		if (r < 0) {
			if (errno == EINTR) {
				continue;
			}
			return SHMCHAN_BROKEN;
		}
		if (r == 0) {
			/* The deadline passed with nothing more. A reply that sits in
			 * the slot without its own notification (say, after an early
			 * one) is then LOST, decided by the caller -- never an OK sample
			 * as long as the timeout (FOUND BY CODE REVIEW). */
			return SHMCHAN_TIMEOUT;
		}
		if (nfds == 2u && p[1].revents != 0) {
			if (drain(kick_fd, 0, 0) != 0) {
				return SHMCHAN_BROKEN;
			}
			if (p[0].revents == 0) {
				continue;
			}
		}
		g_counts.wakeups++;
		if (drain(wait_fd, is_eventfd, expect) != 0) {
			return SHMCHAN_BROKEN;
		}
		if (slot != NULL && g_counts.notifications > before
		    && shm_chan_load(slot, SHM_CHAN_OFF_RSP_SEQ) != n) {
			g_counts.early_wakeups++;    /* told before the reply was visible */
		}
	}
}

/* One notified round trip. `via` SHM_VIA_KICK waits on the kick socket itself;
 * SHM_VIA_DOORBELL (and SHM_VIA_BURST, with `count`) waits on `wait_fd`, the
 * probe's own ivshmem eventfd, and tells the server `peer`, the probe's peer id.
 * SHMCHAN_LOST: at the deadline the reply WAS in the slot -- the server answered
 * and the notification never arrived, which is a protocol fault, not a stall. */
int shmchan_kick_roundtrip(void *slot, const uint8_t *req, uint8_t *rsp, uint64_t timeout_ns,
                           int kick_fd, int wait_fd, uint32_t via, uint32_t peer, uint32_t count)
{
	uint64_t const n = __atomic_load_n(shm_chan_u64(slot, SHM_CHAN_OFF_REQ_SEQ), __ATOMIC_RELAXED) + 1u;
	unsigned char const k = SHM_KICK_BYTE;
	int const is_eventfd = via != SHM_VIA_KICK;
	int r;

	if (!shm_chan_ready_as(slot, SHM_CHAN_MAGIC_KICK)) {
		return SHMCHAN_NOTREADY;
	}
	g_counts.exchanges++;
	shm_chan_put_frame(slot, SHM_CHAN_OFF_REQ, req);
	shm_chan_store32(slot, SHM_CHAN_OFF_REPLY_VIA, via);
	shm_chan_store32(slot, SHM_CHAN_OFF_CLIENT_PEER, peer);
	shm_chan_store32(slot, SHM_CHAN_OFF_RING_COUNT, count);
	shm_chan_store(slot, SHM_CHAN_OFF_REQ_SEQ, n);
	if (send(kick_fd, &k, 1, MSG_NOSIGNAL) != 1) {
		return SHMCHAN_BROKEN;
	}
	r = wait_notified(is_eventfd ? wait_fd : kick_fd, is_eventfd, SHM_KICK_BYTE, slot, n,
	                  now_ns() + timeout_ns, is_eventfd ? kick_fd : -1);
	if (r == SHMCHAN_TIMEOUT && shm_chan_load(slot, SHM_CHAN_OFF_RSP_SEQ) == n) {
		return SHMCHAN_LOST;
	}
	if (r != SHMCHAN_OK) {
		return r;
	}
	shm_chan_get_frame(slot, SHM_CHAN_OFF_RSP, rsp);
	return SHMCHAN_OK;
}

/* The bare notification round trip: one SHM_ECHO_BYTE out, the same byte back,
 * no slot. */
int shmchan_echo_roundtrip(int kick_fd, uint64_t timeout_ns)
{
	unsigned char const e = SHM_ECHO_BYTE;

	g_counts.exchanges++;
	if (send(kick_fd, &e, 1, MSG_NOSIGNAL) != 1) {
		return SHMCHAN_BROKEN;
	}
	return wait_notified(kick_fd, 0, SHM_ECHO_BYTE, NULL, 0, now_ns() + timeout_ns, -1);
}

/* After a SHM_VIA_BURST exchange: wait until `want` doorbells in all have been
 * counted on the eventfd, or the deadline. Returns the total counted. */
uint64_t shmchan_burst_total(int wait_fd, uint64_t want, uint64_t timeout_ns)
{
	uint64_t const deadline = now_ns() + timeout_ns;
	uint64_t const base = g_counts.notifications;

	while (g_counts.notifications - base < want && now_ns() < deadline) {
		struct pollfd p = { wait_fd, POLLIN, 0 };
		if (poll(&p, 1, 10) > 0 && drain(wait_fd, 1, 0) != 0) {
			break;
		}
	}
	return g_counts.notifications - base;
}

/* The flags of a descriptor, for the record: whether the wait fd was
 * non-blocking at the start and at the end of an arm (QEMU changes it). */
int shmchan_fd_flags(int fd)
{
	return fcntl(fd, F_GETFL);
}

/* The probe's ivshmem peer: joins the server, keeps the connection -- leaving
 * would make the server tell QEMU, and QEMU would drop this peer's eventfd --
 * and hands back its id and its own eventfd. */
void *shmchan_ivshm_connect(const char *path)
{
	char err[160];
	struct ivshm_client *c = calloc(1, sizeof(*c));

	if (c == NULL) {
		return NULL;
	}
	if (ivshm_client_connect(c, path, 5000, err, sizeof(err)) != 0) {
		fprintf(stderr, "shmchan: ivshmem server %s: %s\n", path, err);
		free(c);
		return NULL;
	}
	return c;
}

long long shmchan_ivshm_id(void *h)
{
	return (long long)((struct ivshm_client *)h)->my_id;
}

int shmchan_ivshm_efd(void *h)
{
	return ((struct ivshm_client *)h)->my_efd;
}

/* Leave the server: it tells every other peer (QEMU, a monitor) this id is gone. */
void shmchan_ivshm_close(void *h)
{
	if (h != NULL) {
		ivshm_client_close((struct ivshm_client *)h);
		free(h);
	}
}
