/* A6, OD12 (2026-09-22) -- shm_map() for a host: SPEC is a file path.
 * See shm_map.h. Used by the native monitor on the host side of the ladder,
 * where the "shared memory" is a file in /dev/shm that two host processes map.
 *
 * The notified variant's host side is here too (shm_kick_*): the monitor joins
 * an ivshmem server as a peer (ivshm_client.c), maps the memory the server hands
 * it, and listens for one kick client at a time on a UNIX socket.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>

#include "shm_chan.h"
#include "shm_map.h"
#include "ivshm_client.h"

void *shm_map(const char *spec, size_t *len, char *what, size_t what_len)
{
	struct stat st;
	void *base;
	int fd = open(spec, O_RDWR);

	if (fd < 0) {
		fprintf(stderr, "shm: open(%s): %s\n", spec, strerror(errno));
		return NULL;
	}
	if (fstat(fd, &st) != 0) {
		fprintf(stderr, "shm: fstat(%s): %s\n", spec, strerror(errno));
		close(fd);
		return NULL;
	}
	/* Never resized here: the file is shared with another process (or with
	 * QEMU), and growing or truncating it under them is not this program's
	 * call. Too small is refused. */
	if (st.st_size < (off_t)SHM_CHAN_MIN_BYTES) {
		fprintf(stderr, "shm: %s is %lld bytes, needs at least %u\n",
		        spec, (long long)st.st_size, (unsigned)SHM_CHAN_MIN_BYTES);
		close(fd);
		return NULL;
	}
	base = mmap(NULL, (size_t)st.st_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	close(fd);
	if (base == MAP_FAILED) {
		fprintf(stderr, "shm: mmap(%s): %s\n", spec, strerror(errno));
		return NULL;
	}
	*len = (size_t)st.st_size;
	snprintf(what, what_len, "file %s, %zu bytes", spec, *len);
	return base;
}

int shm_configure(const char *spec, char *what, size_t what_len)
{
	snprintf(what, what_len, "nothing to configure on a host (%s)", spec);
	return 0;
}

struct shm_kick {
	struct ivshm_client ivc;
	void *region;
	size_t len;
	int lsock;
	int conn;
	char kick_path[108];
	struct shm_kick_stats st;
};

struct shm_kick *shm_kick_open(const char *spec, size_t offset, const char *kick,
                               void **slot, char *what, size_t what_len)
{
	struct sockaddr_un sa;
	struct stat st;
	char err[160];
	struct shm_kick *k = calloc(1, sizeof(*k));

	if (k == NULL) {
		return NULL;
	}
	k->lsock = k->conn = -1;
	if (ivshm_client_connect(&k->ivc, spec, 5000, err, sizeof(err)) != 0) {
		fprintf(stderr, "shm-kick: ivshmem server %s: %s\n", spec, err);
		free(k);
		return NULL;
	}
	if (fstat(k->ivc.shm_fd, &st) != 0 || st.st_size < (off_t)SHM_CHAN_MIN_BYTES) {
		fprintf(stderr, "shm-kick: the server's memory is unusable\n");
		goto fail;
	}
	k->len = (size_t)st.st_size;
	if (offset % SHM_CHAN_LINE != 0 || offset > k->len || k->len - offset < SHM_CHAN_MIN_BYTES) {
		fprintf(stderr, "shm-kick: slot offset %zu does not fit %zu bytes\n", offset, k->len);
		goto fail;
	}
	k->region = mmap(NULL, k->len, PROT_READ | PROT_WRITE, MAP_SHARED, k->ivc.shm_fd, 0);
	if (k->region == MAP_FAILED) {
		fprintf(stderr, "shm-kick: mmap: %s\n", strerror(errno));
		k->region = NULL;
		goto fail;
	}
	/* The kick socket: never take over a path that exists -- it may be a live
	 * server's -- and never listen for more than one client. */
	if (strlen(kick) >= sizeof(sa.sun_path) || access(kick, F_OK) == 0) {
		fprintf(stderr, "shm-kick: kick socket %s is too long or already exists\n", kick);
		goto fail;
	}
	k->lsock = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	memset(&sa, 0, sizeof(sa));
	sa.sun_family = AF_UNIX;
	memcpy(sa.sun_path, kick, strlen(kick) + 1);
	if (k->lsock < 0 || bind(k->lsock, (struct sockaddr *)&sa, sizeof(sa)) != 0
	    || listen(k->lsock, 1) != 0) {
		fprintf(stderr, "shm-kick: listen on %s: %s\n", kick, strerror(errno));
		goto fail;
	}
	memcpy(k->kick_path, kick, strlen(kick) + 1);
	*slot = (uint8_t *)k->region + offset;
	snprintf(what, what_len, "ivshmem server %s as peer %lld, %zu bytes @%zu, kick %s",
	         spec, (long long)k->ivc.my_id, k->len, offset, kick);
	return k;
fail:
	if (k->lsock >= 0) {
		close(k->lsock);
	}
	if (k->region != NULL) {
		munmap(k->region, k->len);
	}
	ivshm_client_close(&k->ivc);
	free(k);
	return NULL;
}

int shm_kick_wait(struct shm_kick *k)
{
	unsigned char buf[64];
	struct pollfd p;
	int kicked = 0;
	ssize_t n;

	if (k->conn < 0) {
		k->conn = accept(k->lsock, NULL, NULL);
		if (k->conn < 0) {
			return errno == EINTR ? 0 : -1;
		}
		k->st.clients++;
		/* Off the timed path: the server tells existing peers about a newcomer
		 * before the newcomer has its own eventfd, and a probe joins the server
		 * before it connects here, so its connect notice is already waiting. */
		if (ivshm_client_poll(&k->ivc) != 0) {
			return -1;
		}
	}
	p.fd = k->conn;
	p.events = POLLIN;
	p.revents = 0;
	if (poll(&p, 1, -1) < 0) {
		return errno == EINTR ? 0 : -1;
	}
	n = recv(k->conn, buf, sizeof(buf), MSG_DONTWAIT);
	if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
		return 0;
	}
	if (n <= 0) {                        /* the client left: the next wait accepts */
		close(k->conn);
		k->conn = -1;
		return 0;
	}
	for (ssize_t i = 0; i < n; i++) {
		if (buf[i] == SHM_KICK_BYTE) {
			k->st.kick_bytes++;
			kicked = 1;
		} else if (buf[i] == SHM_ECHO_BYTE) {
			unsigned char e = SHM_ECHO_BYTE;
			k->st.echoes++;
			if (send(k->conn, &e, 1, MSG_NOSIGNAL) != 1) {
				k->st.notify_fail++;
			}
		} else {
			k->st.stray_bytes++;
		}
	}
	return kicked;
}

static int ring(struct shm_kick *k, unsigned peer)
{
	int efd = ivshm_client_lookup(&k->ivc, (int64_t)peer);

	if (efd < 0) {
		/* Not in the table: read the server's messages, bounded. Counted,
		 * because it puts system calls on this one reply's path. */
		k->st.ring_misses++;
		efd = ivshm_client_wait_peer(&k->ivc, (int64_t)peer, 100);
		if (efd < 0) {
			return -1;
		}
	}
	return ivshm_client_signal(efd);
}

int shm_kick_notify(struct shm_kick *k, unsigned via, unsigned peer, unsigned count)
{
	unsigned char b = SHM_KICK_BYTE;

	switch (via) {
	case SHM_VIA_KICK:
		if (k->conn < 0 || send(k->conn, &b, 1, MSG_NOSIGNAL) != 1) {
			k->st.notify_fail++;
			return -1;
		}
		k->st.notify_kicks++;
		return 0;
	case SHM_VIA_DOORBELL:
		count = 1;
		/* fall through */
	case SHM_VIA_BURST:
		if (count == 0 || count > SHM_BURST_MAX) {
			k->st.notify_fail++;
			return -1;
		}
		for (unsigned i = 0; i < count; i++) {
			if (ring(k, peer) != 0) {
				k->st.notify_fail++;
				return -1;
			}
			k->st.rings++;
		}
		return 0;
	default:
		k->st.notify_fail++;
		return -1;
	}
}

void shm_kick_get_stats(const struct shm_kick *k, struct shm_kick_stats *st)
{
	*st = k->st;
}
