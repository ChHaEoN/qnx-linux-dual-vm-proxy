/*
 * someip.c -- Phase 3b / A6 (2026-09-27, OD12's SOME/IP arm): the safety monitor's judgement,
 * served as a SOME/IP method.
 *
 * WHAT THIS IS
 *
 * A minimal SOME/IP server for the QNX guest, written for this project. It answers one method,
 * judge (service 0x5AFE, instance 0x0001, method 0x0001, interface version 1), whose request
 * payload is the monitor's 64-byte claim frame and whose response payload is that frame judged:
 * payload[6] verdict and [7] reason, exactly as the TCP monitor writes them. The judgement is
 * monitor.c's own: this file #includes monitor.c (its main() renamed), so the rules cannot
 * drift from the monitor's -- unlike qnx-dds-monitor's copy -- and monitor.c is not changed.
 *
 * On the Linux side the peer is either a raw SOME/IP client (latency_probe.py --proto someip or
 * someipu) or a vsomeip application (orin-native/someip/someip_probe.cpp). vsomeip finds this
 * service by static configuration: service discovery is disabled, and its "services" entry
 * names this guest's unicast address and port.
 *
 * WHAT THIS IS NOT
 *
 * Not vsomeip, and not a SOME/IP stack: no service discovery (SOME/IP-SD), no events or
 * eventgroups, no TP segmentation, no magic cookies, no E2E protection, no serialisation beyond
 * raw bytes. It is enough of the wire protocol for a request and its response, checked
 * field by field, and nothing else.
 *
 * WIRE FORMAT (SOME/IP, big-endian header of 16 bytes, then the payload)
 *   [0..1] service id   [2..3] method id   [4..7] length (bytes after this field)
 *   [8..9] client id    [10..11] session id
 *   [12] protocol version (1)  [13] interface version  [14] message type  [15] return code
 * A request is answered with the same message id, request id and interface version, message
 * type RESPONSE (0x80) and return code E_OK, or with ERROR (0x81), no payload, and one of
 * E_UNKNOWN_SERVICE, E_UNKNOWN_METHOD, E_WRONG_PROTOCOL_VERSION, E_WRONG_INTERFACE_VERSION or
 * E_MALFORMED_MESSAGE (a payload that is not exactly 64 bytes). A REQUEST_NO_RETURN, or any
 * message that is not a request, gets no answer. A frame whose seq is the sentinel is echoed
 * unjudged, as the TCP monitor does.
 *
 * TRANSPORTS. TCP and UDP on the same port (default 30509), each served the way monitor.c
 * serves it, because inside this guest every socket call is a message to io-sock that costs
 * ~7-13 us (20260927T-a6-orin-free), so the server's own call pattern would otherwise be
 * measured as SOME/IP's cost:
 *   TCP  one connection at a time (the main thread), blocking; each read() takes whatever has
 *        arrived into a buffer, so a whole 80-byte message is one read, as the monitor's
 *        64-byte frame is; messages are framed by their length field, and a header announcing
 *        a length outside [8, MAX_MSG - 8] closes the connection: the framing is lost
 *   UDP  a second thread, one blocking recvfrom() per datagram; a datagram may carry several
 *        messages, and their answers go back in one datagram
 * No poll(), no select(): each would be one more io-sock message per request.
 *
 * Pure POSIX, like monitor.c.
 */
#define main monitor_main
#include "../qnx-safety-monitor/monitor.c"
#undef main

#include <pthread.h>

#define SIP_PORT         30509
#define SIP_SERVICE      0x5AFEu
#define SIP_METHOD_JUDGE 0x0001u
#define SIP_IFACE        1u
#define SIP_PROTO        1u
#define SIP_HDR          16u
#define MAX_MSG          1400u

#define MT_REQUEST           0x00u
#define MT_REQUEST_NO_RETURN 0x01u
#define MT_RESPONSE          0x80u
#define MT_ERROR             0x81u

#define E_OK                      0x00u
#define E_UNKNOWN_SERVICE         0x02u
#define E_UNKNOWN_METHOD          0x03u
#define E_WRONG_PROTOCOL_VERSION  0x07u
#define E_WRONG_INTERFACE_VERSION 0x08u
#define E_MALFORMED_MESSAGE       0x09u

struct sip_stats {
	unsigned long long seen, accepted, rejected, errors, dropped;
};

static uint16_t be16(const uint8_t *p)
{
	return (uint16_t)((p[0] << 8) | p[1]);
}

static uint32_t be32(const uint8_t *p)
{
	return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static void put_be32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)(v >> 24);
	p[1] = (uint8_t)(v >> 16);
	p[2] = (uint8_t)(v >> 8);
	p[3] = (uint8_t)v;
}

/* The answer's header: the request's ids, our type and code, a payload of plen bytes. */
static void answer_header(const uint8_t *req, uint8_t *out, uint8_t type, uint8_t code, uint32_t plen)
{
	memcpy(out, req, 4);                 /* service and method */
	put_be32(out + 4, 8u + plen);
	memcpy(out + 8, req + 8, 4);         /* client and session */
	out[12] = SIP_PROTO;
	out[13] = req[13];
	out[14] = type;
	out[15] = code;
}

/* One whole message msg[0..len) (len >= SIP_HDR, and its length field says len - 8). Writes the
 * answer to out and returns its length, or 0 for no answer. */
static size_t sip_answer(const uint8_t *msg, size_t len, uint8_t *out, struct sip_stats *st)
{
	uint8_t const type = msg[14];
	uint8_t code = E_OK;
	size_t const plen = len - SIP_HDR;

	if (type != MT_REQUEST) {
		st->dropped++;
		return 0;          /* REQUEST_NO_RETURN, a response, a notification: no answer */
	}
	if (be16(msg) != SIP_SERVICE)
		code = E_UNKNOWN_SERVICE;
	else if (msg[12] != SIP_PROTO)
		code = E_WRONG_PROTOCOL_VERSION;
	else if (be16(msg + 2) != SIP_METHOD_JUDGE)
		code = E_UNKNOWN_METHOD;
	else if (msg[13] != SIP_IFACE)
		code = E_WRONG_INTERFACE_VERSION;
	else if (plen != FRAME_TOTAL_BYTES)
		code = E_MALFORMED_MESSAGE;
	if (code != E_OK) {
		st->errors++;
		answer_header(msg, out, MT_ERROR, code, 0);
		return SIP_HDR;
	}
	memcpy(out + SIP_HDR, msg + SIP_HDR, FRAME_TOTAL_BYTES);
	if (frame_get_u64(out + SIP_HDR) != FRAME_SENTINEL_SEQ) {
		st->seen++;
		if (judge_frame(out + SIP_HDR) == V_ACCEPT)
			st->accepted++;
		else
			st->rejected++;
	}
	answer_header(msg, out, MT_RESPONSE, E_OK, FRAME_TOTAL_BYTES);
	return SIP_HDR + FRAME_TOTAL_BYTES;
}

static int write_all(int fd, const uint8_t *p, size_t n)
{
	while (n > 0) {
		ssize_t k = write(fd, p, n);
		if (k < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		p += k;
		n -= (size_t)k;
	}
	return 0;
}

struct sip_conn {
	int fd;
	size_t have;
	uint8_t buf[2 * MAX_MSG];
	struct sip_stats st;
};

static void conn_done(struct sip_conn *c, const char *why)
{
	printf("someip: tcp client done (%s): seen=%llu accepted=%llu rejected=%llu errors=%llu dropped=%llu\n",
	       why, c->st.seen, c->st.accepted, c->st.rejected, c->st.errors, c->st.dropped);
	fflush(stdout);
	close(c->fd);
	c->fd = -1;
}

/* Read what the connection has, answer every whole message in it. -1: close it. */
static int conn_serve(struct sip_conn *c, const char **why)
{
	uint8_t out[SIP_HDR + FRAME_TOTAL_BYTES];
	ssize_t k;
	size_t off = 0;

	if (c->have >= sizeof c->buf) {
		*why = "buffer full";      /* cannot happen: a message is at most MAX_MSG bytes */
		return -1;
	}
	k = read(c->fd, c->buf + c->have, sizeof c->buf - c->have);
	if (k == 0) {
		*why = c->have ? "eof mid-message" : "eof";
		return -1;
	}
	if (k < 0) {
		if (errno == EINTR)
			return 0;
		*why = "read error";
		return -1;
	}
	c->have += (size_t)k;
	while (c->have - off >= 8) {
		uint32_t const l = be32(c->buf + off + 4);
		size_t n;

		if (l < 8 || l > MAX_MSG - 8) {
			*why = "bad length";
			return -1;
		}
		if (c->have - off < 8u + l)
			break;
		n = sip_answer(c->buf + off, 8u + l, out, &c->st);
		if (n && write_all(c->fd, out, n) != 0) {
			*why = "write error";
			return -1;
		}
		off += 8u + l;
	}
	memmove(c->buf, c->buf + off, c->have - off);
	c->have -= off;
	return 0;
}

/* One datagram: every whole message in it, answered in one datagram. */
static void udp_serve(int ufd, struct sip_stats *st)
{
	uint8_t in[2048], out[2048];
	struct sockaddr_in from;
	socklen_t fl = sizeof from;
	ssize_t k = recvfrom(ufd, in, sizeof in, 0, (struct sockaddr *)&from, &fl);
	size_t off = 0, o = 0;

	if (k <= 0)
		return;
	while ((size_t)k - off >= SIP_HDR) {
		uint32_t const l = be32(in + off + 4);

		if (l < 8 || (size_t)k - off < 8u + l || o + SIP_HDR + FRAME_TOTAL_BYTES > sizeof out)
			break;
		o += sip_answer(in + off, 8u + l, out + o, st);
		off += 8u + l;
	}
	if (off != (size_t)k)
		st->dropped++;     /* a truncated or oversize tail: not answered */
	if (o)
		(void)sendto(ufd, out, o, 0, (struct sockaddr *)&from, fl);
}

static int listen_on(int type, int port)
{
	struct sockaddr_in a;
	int opt = 1, fd = socket(AF_INET, type, 0);

	if (fd < 0)
		return -1;
	setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof opt);
	memset(&a, 0, sizeof a);
	a.sin_family = AF_INET;
	a.sin_addr.s_addr = htonl(INADDR_ANY);
	a.sin_port = htons((uint16_t)port);
	if (bind(fd, (struct sockaddr *)&a, sizeof a) != 0 || (type == SOCK_STREAM && listen(fd, 4) != 0)) {
		close(fd);
		return -1;
	}
	return fd;
}

/* UDP, in its own thread: one blocking recvfrom per datagram, as monitor.c's UDP path. */
static void *udp_loop(void *arg)
{
	int const ufd = *(int *)arg;
	struct sip_stats st;

	memset(&st, 0, sizeof st);
	while (!g_stop)
		udp_serve(ufd, &st);
	printf("someip: udp: seen=%llu accepted=%llu rejected=%llu errors=%llu dropped=%llu\n",
	       st.seen, st.accepted, st.rejected, st.errors, st.dropped);
	fflush(stdout);
	return NULL;
}

int main(int argc, char **argv)
{
	static struct sip_conn conn;
	struct sigaction sa;
	pthread_t ut;
	int const port = argc > 1 ? atoi(argv[1]) : SIP_PORT;
	int tfd, ufd, opt = 1;

	memset(&sa, 0, sizeof sa);
	sa.sa_handler = on_signal;
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGTERM, &sa, NULL);
	signal(SIGPIPE, SIG_IGN);
	tfd = listen_on(SOCK_STREAM, port);
	ufd = listen_on(SOCK_DGRAM, port);
	if (tfd < 0 || ufd < 0) {
		fprintf(stderr, "someip: bind(%d): %s\n", port, strerror(errno));
		return 1;
	}
	printf("someip: claim kinds: 0 mnist (us <= %u), 1 vlm model %u (us <= %u), conf_min=%u%%\n",
	       INFER_US_MAX, VLM_MODEL_SMOLVLM_500M, VLM_INFER_US_MAX, CONF_MIN);
	printf("someip: judge service 0x%04x method 0x%04x interface %u on :%d tcp+udp (payload %u bytes)\n",
	       SIP_SERVICE, SIP_METHOD_JUDGE, SIP_IFACE, port, (unsigned)FRAME_TOTAL_BYTES);
	fflush(stdout);
	if (pthread_create(&ut, NULL, udp_loop, &ufd) != 0) {
		fprintf(stderr, "someip: pthread_create failed\n");
		return 1;
	}
	while (!g_stop) {
		const char *why = NULL;
		int cfd = accept(tfd, NULL, NULL);

		if (cfd < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "someip: accept: %s\n", strerror(errno));
			break;
		}
		setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof opt);
		memset(&conn, 0, sizeof conn);
		conn.fd = cfd;
		while (!g_stop && conn_serve(&conn, &why) == 0)
			;
		conn_done(&conn, why ? why : "stopped");
	}
	printf("someip: stopped\n");
	return 0;
}
