/* A6, OD12 (2026-09-22) -- a peer of an ivshmem server. See ivshm_client.h. */
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>

#include "ivshm_client.h"

/* One message: 8 little-endian bytes, maybe one fd. Returns 1 with *val (and
 * *fd, -1 if none), 0 if nothing is waiting and !block, -1 on EOF or error.
 * A stream may split the 8 bytes; the fd rides on the first of them. */
static int recv_msg(int sock, int block, int64_t *val, int *fd)
{
	unsigned char buf[8];
	size_t got = 0;

	*fd = -1;
	while (got < sizeof(buf)) {
		char cbuf[CMSG_SPACE(sizeof(int))];
		struct iovec iov = { buf + got, sizeof(buf) - got };
		struct msghdr mh;
		struct cmsghdr *cm;
		ssize_t n;

		memset(&mh, 0, sizeof(mh));
		mh.msg_iov = &iov;
		mh.msg_iovlen = 1;
		mh.msg_control = cbuf;
		mh.msg_controllen = sizeof(cbuf);
		n = recvmsg(sock, &mh, (block || got) ? 0 : MSG_DONTWAIT);
		if (n < 0) {
			if (errno == EINTR) {
				continue;
			}
			if (!block && got == 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
				return 0;
			}
			return -1;
		}
		if (n == 0) {
			return -1;
		}
		for (cm = CMSG_FIRSTHDR(&mh); cm != NULL; cm = CMSG_NXTHDR(&mh, cm)) {
			if (cm->cmsg_level == SOL_SOCKET && cm->cmsg_type == SCM_RIGHTS) {
				int f;
				memcpy(&f, CMSG_DATA(cm), sizeof(int));
				if (*fd >= 0) {
					close(f);          /* one fd per message; never leak a second */
				} else {
					*fd = f;
				}
			}
		}
		got += (size_t)n;
	}
	*val = 0;
	for (int i = 7; i >= 0; i--) {
		*val = (int64_t)(((uint64_t)*val << 8) | buf[i]);
	}
	return 1;
}

static int peer_index(const struct ivshm_client *c, int64_t id)
{
	for (int i = 0; i < c->npeers; i++) {
		if (c->peers[i].id == id) {
			return i;
		}
	}
	return -1;
}

/* A message after setup: (own id, fd) = own vector; (other id, fd) = that peer's
 * vector; (other id, no fd) = that peer left. */
static int handle(struct ivshm_client *c, int64_t val, int fd)
{
	int i;

	if (val == c->my_id) {
		if (fd < 0 || c->my_efd >= 0) {
			if (fd >= 0) {
				close(fd);
			}
			return -1;             /* one vector only; a second is a protocol error here */
		}
		c->my_efd = fd;
		return 0;
	}
	i = peer_index(c, val);
	if (fd < 0) {                  /* disconnect */
		if (i >= 0) {
			close(c->peers[i].efd);
			c->peers[i] = c->peers[--c->npeers];
		}
		return 0;
	}
	if (i >= 0) {                  /* a second vector for a known peer: keep the first */
		close(fd);
		return 0;
	}
	if (c->npeers >= IVSHM_PEERS_MAX) {
		close(fd);
		return -1;
	}
	c->peers[c->npeers].id = val;
	c->peers[c->npeers].efd = fd;
	c->npeers++;
	return 0;
}

int ivshm_client_connect(struct ivshm_client *c, const char *path, int timeout_ms, char *err, size_t errlen)
{
	struct sockaddr_un sa;
	int64_t val;
	int fd;

	memset(c, 0, sizeof(*c));
	c->sock = c->shm_fd = c->my_efd = -1;
	c->my_id = -1;
	if (strlen(path) >= sizeof(sa.sun_path)) {
		snprintf(err, errlen, "socket path too long: %s", path);
		return -1;
	}
	c->sock = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	if (c->sock < 0) {
		snprintf(err, errlen, "socket: %s", strerror(errno));
		return -1;
	}
	memset(&sa, 0, sizeof(sa));
	sa.sun_family = AF_UNIX;
	memcpy(sa.sun_path, path, strlen(path) + 1);
	if (connect(c->sock, (struct sockaddr *)&sa, sizeof(sa)) != 0) {
		snprintf(err, errlen, "connect(%s): %s", path, strerror(errno));
		ivshm_client_close(c);
		return -1;
	}
	if (recv_msg(c->sock, 1, &val, &fd) != 1 || fd >= 0 || val != 0) {
		snprintf(err, errlen, "server did not send protocol version 0");
		if (fd >= 0) {
			close(fd);
		}
		ivshm_client_close(c);
		return -1;
	}
	if (recv_msg(c->sock, 1, &val, &fd) != 1 || fd >= 0 || val < 0 || val > 65535) {
		snprintf(err, errlen, "server sent no valid peer id");
		if (fd >= 0) {
			close(fd);
		}
		ivshm_client_close(c);
		return -1;
	}
	c->my_id = val;
	if (recv_msg(c->sock, 1, &val, &fd) != 1 || val != -1 || fd < 0) {
		snprintf(err, errlen, "server sent no shared memory fd");
		if (fd >= 0) {
			close(fd);
		}
		ivshm_client_close(c);
		return -1;
	}
	c->shm_fd = fd;
	while (c->my_efd < 0) {
		struct pollfd p = { c->sock, POLLIN, 0 };
		int r = poll(&p, 1, timeout_ms);
		if (r <= 0) {
			snprintf(err, errlen, "no own eventfd within %d ms", timeout_ms);
			ivshm_client_close(c);
			return -1;
		}
		if (recv_msg(c->sock, 1, &val, &fd) != 1 || handle(c, val, fd) != 0) {
			snprintf(err, errlen, "protocol error during setup");
			ivshm_client_close(c);
			return -1;
		}
	}
	return 0;
}

int ivshm_client_poll(struct ivshm_client *c)
{
	for (;;) {
		int64_t val;
		int fd;
		int r = recv_msg(c->sock, 0, &val, &fd);
		if (r == 0) {
			return 0;
		}
		if (r < 0 || handle(c, val, fd) != 0) {
			return -1;
		}
	}
}

int ivshm_client_lookup(const struct ivshm_client *c, int64_t id)
{
	int i = peer_index(c, id);

	return i < 0 ? -1 : c->peers[i].efd;
}

int ivshm_client_wait_peer(struct ivshm_client *c, int64_t id, int timeout_ms)
{
	struct pollfd p = { c->sock, POLLIN, 0 };
	int efd;

	for (;;) {
		if (ivshm_client_poll(c) != 0) {
			return -1;
		}
		efd = ivshm_client_lookup(c, id);
		if (efd >= 0) {
			return efd;
		}
		if (poll(&p, 1, timeout_ms) <= 0) {
			return -1;
		}
	}
}

int ivshm_client_signal(int efd)
{
	uint64_t one = 1;

	return write(efd, &one, sizeof(one)) == (ssize_t)sizeof(one) ? 0 : -1;
}

void ivshm_client_close(struct ivshm_client *c)
{
	for (int i = 0; i < c->npeers; i++) {
		close(c->peers[i].efd);
	}
	c->npeers = 0;
	if (c->my_efd >= 0) {
		close(c->my_efd);
	}
	if (c->shm_fd >= 0) {
		close(c->shm_fd);
	}
	if (c->sock >= 0) {
		close(c->sock);
	}
	c->sock = c->shm_fd = c->my_efd = -1;
}
