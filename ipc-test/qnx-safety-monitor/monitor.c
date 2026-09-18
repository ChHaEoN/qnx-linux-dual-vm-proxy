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

		uint8_t reason = RSN_OK;
		uint8_t const verdict = check_claim(&buf[FRAME_HEADER_BYTES], &reason);

		buf[FRAME_HEADER_BYTES + P_VERDICT] = verdict;
		buf[FRAME_HEADER_BYTES + P_REASON]  = reason;

		seen++;
		if (verdict == V_ACCEPT) {
			accepted++;
		} else {
			rejected++;
			/* Log only rejects: an accepted frame is the common case
			 * and flooding the console would itself be a hazard on a
			 * serial-consoled guest. */
			printf("monitor: REJECT seq=%llu class=%u conf=%u us=%u reason=%s\n",
			       (unsigned long long)frame_get_u64(&buf[0]),
			       buf[FRAME_HEADER_BYTES + P_CLASS],
			       buf[FRAME_HEADER_BYTES + P_CONF],
			       get_u32_le(&buf[FRAME_HEADER_BYTES + P_INFER_US]),
			       reason_name(reason));
			fflush(stdout);
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
