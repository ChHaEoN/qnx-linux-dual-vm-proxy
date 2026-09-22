/* A6, OD12 (2026-09-22) -- shm_map() for a host: SPEC is a file path.
 * See shm_map.h. Used by the native monitor on the host side of the ladder,
 * where the "shared memory" is a file in /dev/shm that two host processes map.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>

#include "shm_chan.h"
#include "shm_map.h"

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
