/* Phase 3b (Orin, QNX guest under KVM): the Safety end of a cross-partition
 * service.
 *
 * WHAT THIS IS
 *
 * L4T owns the GPU and runs the perception work (TensorRT); this program runs
 * in the QNX guest and plays the role a Safety partition plays in a DRIVE OS
 * style split: it does not perceive anything itself, it *checks* what the
 * Compute side claims, and answers with a verdict.
 *
 * It is a deliberate step up from ipc-test/qnx-server-net/server.c, which
 * echoes frames verbatim. This one interprets the payload, applies plausibility
 * rules, and writes its own verdict into the reply -- so the reply says
 * something the Compute side did not already know.
 *
 * WIRE FORMAT (reuses ipc-test/common/frame.h, 64 bytes fixed)
 *
 *   offset 0  : uint64 seq             (initiator's, echoed back unchanged)
 *   offset 8  : uint64 tstamp_cycles   (initiator's, echoed back unchanged)
 *   payload[0]     : uint8  class id     (0..9 for the mnist demo)
 *   payload[1]     : uint8  confidence   (0..100, percent)
 *   payload[2..5]  : uint32 inference_us (Compute side's own GPU time)
 *   payload[6]     : uint8  verdict      <- WRITTEN BY THIS PROGRAM
 *   payload[7]     : uint8  reason       <- WRITTEN BY THIS PROGRAM
 *   payload[8..47] : reserved, echoed unchanged
 *
 * The initiator's seq and timestamp are never touched, exactly as in
 * qnx-server-net: only the initiator interprets a clock, so there is no
 * cross-OS clock to reconcile.
 *
 * WHAT THIS IS NOT
 *
 * Not a safety mechanism in any ISO 26262 sense, and no ASIL claim attaches to
 * it. The rules below are plausibility checks chosen to be legible, not a
 * validated diagnostic. It shows the *shape* of a safety partition checking a
 * compute partition across a real VM boundary; it does not show freedom from
 * interference, and the boundary here is KVM (Linux owns this guest's memory),
 * not a certified Type-1 partition.
 *
 * TWO TRANSPORTS, ONE JUDGEMENT (owner decision OD12, 2026-09-21)
 *
 *   monitor [PORT]        TCP, one client at a time (the original)
 *   monitor PORT udp      UDP, one 64-byte frame per datagram
 *
 * Both paths call judge_frame(), so a claim gets the same verdict whichever
 * transport carried it -- the point of a UDP arm is to vary the transport and
 * nothing else. A datagram that is not exactly one frame is dropped without a
 * reply and counted: on UDP there is no stream to resynchronise, and replying
 * to a fragment would hand the initiator bytes it did not send. The UDP socket
 * does NOT set SO_REUSEADDR, so a second UDP monitor on the same port fails to
 * bind -- the ladder relies on that to refuse a leftover server.
 *
 * A THIRD TRANSPORT: SHARED MEMORY (OD12, 2026-09-22)
 *
 *   monitor shm SPEC      one request/reply slot in shared memory (shm_chan.h)
 *
 * SPEC is resolved by whichever shm_map_*.c was linked in: on the host a file
 * path under /dev/shm, in the guest "ivshmem" (QEMU's ivshmem PCI device). This
 * file has no #ifdef for it -- the guest and the host still build one source.
 * The same judge_frame() again. There is no interrupt: the loop polls. It spins
 * while requests are arriving and, 50 ms after the last one, falls back to
 * looking every 10 ms, so a monitor left running between arms costs a wake-up
 * every 10 ms rather than a whole core. The first frames after a quiet spell
 * wait for that 10 ms look -- the probe's warm-up frames absorb it.
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
#include <time.h>

#include "frame.h"
#include "frame_io.h"
#include "shm_chan.h"
#include "shm_map.h"

#define DEFAULT_PORT 7100

/* payload offsets */
#define P_CLASS      0u
#define P_CONF       1u
#define P_INFER_US   2u
#define P_VERDICT    6u
#define P_REASON     7u

/* verdicts */
#define V_ACCEPT     0u
#define V_REJECT     1u

/* Reasons (why a frame was rejected; 0 when accepted).
 *
 * Prefixed RSN_ rather than R_: <unistd.h> already defines R_OK as the
 * test-for-read-permission bit for access(2), and shadowing it here compiled
 * but warned. A reason code in a monitor that silently aliases a libc access
 * mode is the kind of ambiguity this program is supposed to not have. */
#define RSN_OK             0u
#define RSN_CLASS_RANGE    1u   /* class id outside the model's label set    */
#define RSN_CONF_RANGE     2u   /* confidence not a percentage               */
#define RSN_CONF_LOW       3u   /* below the acceptance threshold            */
#define RSN_INFER_IMPLAUS  4u   /* inference time implausible for this model */

/* Acceptance threshold, percent. Chosen for the demo, not derived from any
 * hazard analysis -- see "WHAT THIS IS NOT" above. */
#define CONF_MIN     60u

/* An mnist engine on this GPU runs ~0.07 ms; anything over 100 ms did not come
 * from that engine on that device, so the claim is not plausible. Generous on
 * purpose: this rejects nonsense, it does not police performance. */
#define INFER_US_MAX 100000u

static volatile sig_atomic_t g_stop = 0;

static void on_signal(int sig)
{
	(void)sig;
	g_stop = 1;
}

static uint32_t get_u32_le(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
	       ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* Returns the verdict, and sets *reason. */
static uint8_t check_claim(const uint8_t *payload, uint8_t *reason)
{
	uint8_t const cls  = payload[P_CLASS];
	uint8_t const conf = payload[P_CONF];
	uint32_t const us  = get_u32_le(&payload[P_INFER_US]);

	if (cls > 9u) {
		*reason = RSN_CLASS_RANGE;
		return V_REJECT;
	}
	if (conf > 100u) {
		*reason = RSN_CONF_RANGE;
		return V_REJECT;
	}
	if (us > INFER_US_MAX) {
		*reason = RSN_INFER_IMPLAUS;
		return V_REJECT;
	}
	if (conf < CONF_MIN) {
		*reason = RSN_CONF_LOW;
		return V_REJECT;
	}

	*reason = RSN_OK;
	return V_ACCEPT;
}

static const char *reason_name(uint8_t r)
{
	switch (r) {
	case RSN_OK:            return "ok";
	case RSN_CLASS_RANGE:   return "class-out-of-range";
	case RSN_CONF_RANGE:    return "confidence-not-a-percentage";
	case RSN_CONF_LOW:      return "confidence-below-threshold";
	case RSN_INFER_IMPLAUS: return "inference-time-implausible";
	default:              return "unknown";
	}
}

/* Judge one non-sentinel frame in place: write verdict and reason into the
 * payload, log a reject. Shared by every transport. Returns the verdict. */
static uint8_t judge_frame(uint8_t *buf)
{
	uint8_t reason = RSN_OK;
	uint8_t const verdict = check_claim(&buf[FRAME_HEADER_BYTES], &reason);

	buf[FRAME_HEADER_BYTES + P_VERDICT] = verdict;
	buf[FRAME_HEADER_BYTES + P_REASON]  = reason;

	if (verdict != V_ACCEPT) {
		/* Log only rejects: an accepted frame is the common case and
		 * flooding the console would itself be a hazard on a
		 * serial-consoled guest. */
		printf("monitor: REJECT seq=%llu class=%u conf=%u us=%u reason=%s\n",
		       (unsigned long long)frame_get_u64(&buf[0]),
		       buf[FRAME_HEADER_BYTES + P_CLASS],
		       buf[FRAME_HEADER_BYTES + P_CONF],
		       get_u32_le(&buf[FRAME_HEADER_BYTES + P_INFER_US]),
		       reason_name(reason));
		fflush(stdout);
	}
	return verdict;
}

static int serve_one_client(int cfd)
{
	uint8_t buf[FRAME_TOTAL_BYTES];
	unsigned long long seen = 0, accepted = 0, rejected = 0;

	for (;;) {
		if (g_stop) {
			break;
		}
		int const rc = frameio_read_frame(cfd, buf);
		if (rc > 0) {
			break;      /* clean EOF: the client finished and hung up */
		}
		if (rc < 0) {
			/* Short read mid-frame or a socket error. Distinguished
			 * from EOF on purpose: a truncated frame is a protocol
			 * fault, and silently treating it as a polite disconnect
			 * would hide exactly the kind of fault this program
			 * exists to notice. */
			fprintf(stderr, "monitor: frame read failed: %s\n",
			        strerror(errno));
			break;
		}

		/* A sentinel is a keepalive carrying no claim. Echo it untouched
		 * and never count it -- treating it as a claim would invent a
		 * verdict about data that was never sent. */
		if (frame_get_u64(&buf[0]) == FRAME_SENTINEL_SEQ) {
			if (frameio_write_frame(cfd, buf) != 0) {
				break;
			}
			continue;
		}

		seen++;
		if (judge_frame(buf) == V_ACCEPT) {
			accepted++;
		} else {
			rejected++;
		}

		if (frameio_write_frame(cfd, buf) != 0) {
			break;
		}
	}

	printf("monitor: client done: seen=%llu accepted=%llu rejected=%llu\n",
	       seen, accepted, rejected);
	fflush(stdout);
	return 0;
}

/* UDP: one frame per datagram, the reply to the sender's address. The receive
 * buffer is larger than a frame on purpose -- an oversize datagram must be SEEN
 * as oversize and dropped, not silently truncated to 64 bytes and answered. */
static int serve_udp(int port)
{
	struct sockaddr_in addr;
	uint8_t buf[2048];
	unsigned long long seen = 0, accepted = 0, rejected = 0, dropped = 0;
	int fd = socket(AF_INET, SOCK_DGRAM, 0);

	if (fd < 0) {
		fprintf(stderr, "monitor: socket(udp): %s\n", strerror(errno));
		return 1;
	}
	memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_addr.s_addr = htonl(INADDR_ANY);
	addr.sin_port = htons((uint16_t)port);
	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
		fprintf(stderr, "monitor: bind(%d/udp): %s\n", port, strerror(errno));
		close(fd);
		return 1;
	}

	printf("monitor: safety monitor listening on :%d/udp (frame=%u bytes, conf_min=%u%%)\n",
	       port, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN);
	fflush(stdout);

	while (!g_stop) {
		struct sockaddr_in peer;
		socklen_t plen = sizeof(peer);
		ssize_t const n = recvfrom(fd, buf, sizeof(buf), 0,
		                           (struct sockaddr *)&peer, &plen);
		if (n < 0) {
			if (errno == EINTR) {
				continue;
			}
			fprintf(stderr, "monitor: recvfrom: %s\n", strerror(errno));
			break;
		}
		if (n != (ssize_t)FRAME_TOTAL_BYTES) {
			dropped++;
			continue;
		}
		if (frame_get_u64(&buf[0]) != FRAME_SENTINEL_SEQ) {
			seen++;
			if (judge_frame(buf) == V_ACCEPT) {
				accepted++;
			} else {
				rejected++;
			}
		}
		if (sendto(fd, buf, FRAME_TOTAL_BYTES, 0, (struct sockaddr *)&peer, plen)
		    != (ssize_t)FRAME_TOTAL_BYTES) {
			fprintf(stderr, "monitor: sendto: %s\n", strerror(errno));
		}
	}

	printf("monitor: udp done: seen=%llu accepted=%llu rejected=%llu dropped=%llu\n",
	       seen, accepted, rejected, dropped);
	fflush(stdout);
	close(fd);
	return 0;
}

#define SHM_SPIN_NS  50000000ull   /* keep spinning this long after a request */
#define SHM_IDLE_NS  10000000L     /* then look this often */
#define SHM_SPIN_CHECK 4096u       /* spins between clock reads */

static uint64_t now_ns(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

/* Shared memory: one request outstanding, answered in place (shm_chan.h). */
static int serve_shm(const char *spec)
{
	uint8_t buf[FRAME_TOTAL_BYTES];
	unsigned long long seen = 0, accepted = 0, rejected = 0, jumps = 0;
	unsigned long long seen_at_quiet = 0;
	char what[192];
	size_t len = 0;
	uint64_t last, active;
	unsigned spins = 0;
	int quiet = 1;
	void *base = shm_map(spec, &len, what, sizeof(what));

	if (base == NULL) {
		return 1;
	}

	/* Take the slot over. Not serving (magic 0) while it is set up; a
	 * request left in it from before this server started is NOT answered --
	 * its client is gone, and answering would hand a later client a reply to
	 * a frame it never sent. */
	__atomic_store_n(shm_chan_u32(base, SHM_CHAN_OFF_MAGIC), 0u, __ATOMIC_RELEASE);
	last = shm_chan_load(base, SHM_CHAN_OFF_REQ_SEQ);
	shm_chan_store(base, SHM_CHAN_OFF_RSP_SEQ, last);
	*shm_chan_u32(base, SHM_CHAN_OFF_VERSION) = SHM_CHAN_VERSION;
	__atomic_store_n(shm_chan_u32(base, SHM_CHAN_OFF_MAGIC), SHM_CHAN_MAGIC, __ATOMIC_RELEASE);

	printf("monitor: safety monitor serving shm on %s (frame=%u bytes, conf_min=%u%%)\n",
	       what, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN);
	fflush(stdout);

	active = now_ns();
	while (!g_stop) {
		uint64_t const cur = shm_chan_load(base, SHM_CHAN_OFF_REQ_SEQ);

		if (cur == last) {
			shm_chan_relax();
			if (++spins < SHM_SPIN_CHECK) {
				continue;
			}
			spins = 0;
			if (now_ns() - active > SHM_SPIN_NS) {
				struct timespec const idle = { 0, SHM_IDLE_NS };
				if (!quiet) {
					/* One line per burst of traffic, so a console
					 * shows sessions the way the TCP path's
					 * "client done" lines do. */
					printf("monitor: shm quiet: seen=%llu accepted=%llu rejected=%llu (%llu this burst)\n",
					       seen, accepted, rejected, seen - seen_at_quiet);
					fflush(stdout);
					seen_at_quiet = seen;
					quiet = 1;
				}
				nanosleep(&idle, NULL);
			}
			continue;
		}
		/* A client publishes previous + 1. Anything else means a second
		 * client, or a client that lost count: still answered (the
		 * client waits for exactly this value), but counted. */
		if (cur != last + 1u) {
			jumps++;
		}
		shm_chan_get_frame(base, SHM_CHAN_OFF_REQ, buf);
		if (frame_get_u64(&buf[0]) != FRAME_SENTINEL_SEQ) {
			seen++;
			if (judge_frame(buf) == V_ACCEPT) {
				accepted++;
			} else {
				rejected++;
			}
		}
		shm_chan_put_frame(base, SHM_CHAN_OFF_RSP, buf);
		shm_chan_store(base, SHM_CHAN_OFF_RSP_SEQ, cur);
		last = cur;
		active = now_ns();
		quiet = 0;
	}

	__atomic_store_n(shm_chan_u32(base, SHM_CHAN_OFF_MAGIC), 0u, __ATOMIC_RELEASE);
	printf("monitor: shm done: seen=%llu accepted=%llu rejected=%llu jumps=%llu\n",
	       seen, accepted, rejected, jumps);
	fflush(stdout);
	return 0;
}

int main(int argc, char **argv)
{
	int const port = (argc > 1) ? atoi(argv[1]) : DEFAULT_PORT;
	struct sigaction sa;
	struct sockaddr_in addr;
	int lfd, opt = 1;

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_signal;
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGTERM, &sa, NULL);
	signal(SIGPIPE, SIG_IGN);

	if (argc > 1 && strcmp(argv[1], "shm") == 0) {
		if (argc != 3) {
			fprintf(stderr, "monitor: usage: monitor shm SPEC (a /dev/shm file on a host, 'ivshmem' in the guest)\n");
			return 2;
		}
		return serve_shm(argv[2]);
	}
	if (argc > 2) {
		if (strcmp(argv[2], "udp") == 0) {
			return serve_udp(port);
		}
		/* Refuse an unknown transport word rather than guess. (Only the
		 * word is checked: the port is still atoi(argv[1]), as before.) */
		fprintf(stderr, "monitor: unknown transport '%s' (only 'udp', or none for tcp; shm is 'monitor shm SPEC')\n",
		        argv[2]);
		return 2;
	}

	lfd = socket(AF_INET, SOCK_STREAM, 0);
	if (lfd < 0) {
		fprintf(stderr, "monitor: socket: %s\n", strerror(errno));
		return 1;
	}
	setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

	memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_addr.s_addr = htonl(INADDR_ANY);
	addr.sin_port = htons((uint16_t)port);

	if (bind(lfd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
		fprintf(stderr, "monitor: bind(%d): %s\n", port, strerror(errno));
		close(lfd);
		return 1;
	}
	if (listen(lfd, 4) != 0) {
		fprintf(stderr, "monitor: listen: %s\n", strerror(errno));
		close(lfd);
		return 1;
	}

	printf("monitor: safety monitor listening on :%d (frame=%u bytes, conf_min=%u%%)\n",
	       port, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN);
	fflush(stdout);

	while (!g_stop) {
		int cfd = accept(lfd, NULL, NULL);
		if (cfd < 0) {
			if (errno == EINTR) {
				continue;
			}
			fprintf(stderr, "monitor: accept: %s\n", strerror(errno));
			break;
		}
		setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));
		serve_one_client(cfd);
		close(cfd);
	}

	close(lfd);
	printf("monitor: stopped\n");
	return 0;
}
