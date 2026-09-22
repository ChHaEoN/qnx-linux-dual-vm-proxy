/* A6, OD12 (2026-09-22) -- the QNX guest's side of the shm transports: QEMU's
 * ivshmem device, configured through ECAM, and a virtio console as a kick
 * channel. See shm_map.h for the interface.
 *
 * SPEC must be "ivshmem": the QEMU ivshmem PCI function (vendor 0x1af4, device
 * 0x1110 -- the same for ivshmem-plain and ivshmem-doorbell) on bus 0 of QEMU's
 * virt machine. BAR2 is the shared memory; BAR0 holds the device's registers
 * (IntrMask, IntrStatus, IVPosition at 8, Doorbell at 12); on ivshmem-doorbell
 * BAR1 is the MSI-X table, which this program never uses.
 *
 * WHY NOT THE PCI SERVER. SDP 8.0's pci-server with pci_hw-fdt.so refused QEMU
 * virt's generic ECAM host bridge on 2026-09-22: by its own log it took the ECAM
 * window's size as zero, found no memory window and returned EINVAL, and an
 * [ecam] override in PCI_HW_CONFIG_FILE changed nothing. So this file does what
 * is needed for this one function itself, through ECAM. The same fact means no
 * MSI-X, so QEMU 6.2's ivshmem-doorbell -- which notifies a guest only by MSI-X
 * and otherwise drops the notification -- can never interrupt this guest. The
 * guest can still RING a peer (a Doorbell write is caught by a KVM ioeventfd),
 * and it is interrupted instead through the virtio console, whose driver,
 * devc-virtio, takes an ordinary SPI.
 *
 * CONFIGURE ONCE (FOUND BY DESIGN REVIEW, 2026-09-22). Sizing a BAR means
 * switching memory decoding off and writing all-ones to it, which unmaps the
 * BAR under anyone already using it. So shm_configure() runs once, first, and
 * synchronously ("qnx-safety-monitor shmcfg ivshmem" in the image), and writes
 * the addresses to a marker, /dev/shmem/ivshmem-config. shm_map() and
 * shm_kick_open() only read the marker and map. Without a marker, shm_map()
 * configures itself, as the first version of this file always did.
 *
 *   1. map bus 0's configuration space (1 MiB of ECAM), uncached;
 *   2. find 1af4:1110 at function 0 of exactly one device;
 *   3. with decoding off, size BAR2 (64-bit) and BAR0 (32-bit) by the PCI rule
 *      -- all ones, read the mask back -- and restore them;
 *   4. place BAR2 at the base of the 32-bit window and BAR0 right after it
 *      (BAR2's own size decides where), unless they already hold addresses in
 *      the window that do not overlap; refuse anything else;
 *   5. enable decoding, verify it stuck, unmap the ECAM, write the marker.
 *
 * THE ADDRESSES are QEMU virt's (6.2, highmem on), read from its own generated
 * device tree on the Orin (qemu -machine virt,dumpdtb=...): ECAM reg
 * <0x40 0x10000000 0x0 0x10000000>, and a 32-bit memory window mapping PCI
 * 0x10000000 to CPU 0x10000000 (size 0x2eff0000). The IDs read in step 2 are the
 * check that the ECAM address is right.
 *
 * MMIO ACCESSES ARE SINGLE-REGISTER, WITHOUT WRITEBACK, BY INLINE ASM, and the
 * Doorbell store is 32 bits. KVM on this board emulates a trapped access only
 * when its syndrome is valid (ISV=1); a post-increment or a load/store pair
 * reports ISV=0 -- the defect this project root-caused in the shipped
 * startup-qemu-virt. And QEMU registers the doorbell's ioeventfd for 4-byte
 * writes only: a wider store would miss it and go to QEMU's userspace instead.
 *
 * BAR2 IS MAPPED CACHEABLE, ON PURPOSE. The host maps the same pages cacheable,
 * and on a CPU without FEAT_S2FWB (the A78AE has none) an uncached guest view
 * would give the two views mismatched attributes, for which Arm does not
 * promise coherence. BAR0 is registers, mapped uncached.
 *
 * Runs as root (physical mappings). Not portable beyond QEMU virt.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#include <sys/mman.h>

#include "shm_chan.h"
#include "shm_map.h"

#define ECAM_BASE       0x4010000000ull   /* QEMU virt, highmem: ECAM for buses 0..255 */
#define ECAM_BUS0_BYTES 0x100000u         /* 32 devices x 8 functions x 4 KiB */
#define MMIO32_BASE     0x10000000ull     /* PCI == CPU address in this window */
#define MMIO32_SIZE     0x2eff0000ull
#define MARKER          "/ivshmem-config" /* shm_open name: /dev/shmem/ivshmem-config */

#define IVSHMEM_ID      0x11101af4u       /* device << 16 | vendor */
#define CFG_ID          0x00u
#define CFG_CMD         0x04u
#define CFG_BAR0        0x10u
#define CFG_BAR2        0x18u
#define CFG_BAR3        0x1cu
#define CMD_MEM         0x0002u
#define REG_IVPOSITION  0x08u
#define REG_DOORBELL    0x0cu

static inline uint32_t rd32(volatile uint8_t *p)
{
	uint32_t v;
	__asm__ __volatile__("ldr %w0, [%1]" : "=r"(v) : "r"(p) : "memory");
	return v;
}

static inline void wr32(volatile uint8_t *p, uint32_t v)
{
	__asm__ __volatile__("str %w0, [%1]" : : "r"(v), "r"(p) : "memory");
}

static inline uint16_t rd16(volatile uint8_t *p)
{
	uint16_t v;
	__asm__ __volatile__("ldrh %w0, [%1]" : "=r"(v) : "r"(p) : "memory");
	return v;
}

static inline void wr16(volatile uint8_t *p, uint16_t v)
{
	__asm__ __volatile__("strh %w0, [%1]" : : "r"(v), "r"(p) : "memory");
}

struct ivcfg {
	uint64_t bar2, bar2_size, bar0, bar0_size;
	unsigned dev;
};

static int read_marker(struct ivcfg *c)
{
	char buf[256];
	ssize_t n;
	int fd = shm_open(MARKER, O_RDONLY, 0);

	if (fd < 0) {
		return -1;
	}
	n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	if (n <= 0) {
		return -1;
	}
	buf[n] = '\0';
	if (sscanf(buf, "bar2=%llx bar2_size=%llx bar0=%llx bar0_size=%llx dev=%u",
	           (unsigned long long *)&c->bar2, (unsigned long long *)&c->bar2_size,
	           (unsigned long long *)&c->bar0, (unsigned long long *)&c->bar0_size, &c->dev) != 5) {
		fprintf(stderr, "shm: marker /dev/shmem%s is malformed: %s\n", MARKER, buf);
		return -1;
	}
	return 0;
}

static int write_marker(const struct ivcfg *c)
{
	char buf[256];
	int len = snprintf(buf, sizeof(buf), "bar2=%llx bar2_size=%llx bar0=%llx bar0_size=%llx dev=%u\n",
	                   (unsigned long long)c->bar2, (unsigned long long)c->bar2_size,
	                   (unsigned long long)c->bar0, (unsigned long long)c->bar0_size, c->dev);
	int fd = shm_open(MARKER, O_RDWR | O_CREAT | O_TRUNC, 0444);

	if (fd < 0) {
		fprintf(stderr, "shm: cannot write the marker: %s\n", strerror(errno));
		return -1;
	}
	if (ftruncate(fd, len) != 0 || write(fd, buf, (size_t)len) != len) {
		fprintf(stderr, "shm: writing the marker: %s\n", strerror(errno));
		close(fd);
		return -1;
	}
	close(fd);
	return 0;
}

/* Size one BAR (decoding must be off): all ones, read back, restore. Returns
 * the mask with the low flag bits cleared, 64-bit when hi is non-NULL. */
static uint64_t size_mask(volatile uint8_t *lo, volatile uint8_t *hi)
{
	uint32_t const olo = rd32(lo);
	uint32_t const ohi = hi ? rd32(hi) : 0u;
	uint32_t mlo, mhi = 0xffffffffu;

	wr32(lo, 0xffffffffu);
	if (hi) {
		wr32(hi, 0xffffffffu);
	}
	mlo = rd32(lo);
	if (hi) {
		mhi = rd32(hi);
	}
	wr32(lo, olo);
	if (hi) {
		wr32(hi, ohi);
	}
	return ((uint64_t)mhi << 32) | (uint64_t)(mlo & ~0xfu);
}

static int configure(struct ivcfg *out, char *what, size_t what_len)
{
	volatile uint8_t *ecam, *cfg = NULL;
	uint32_t lo2, hi2, lo0;
	uint64_t a2, a0, m2, m0, s2, s0;
	uint16_t cmd;
	unsigned dev, found = 0;
	int kept;

	ecam = mmap_device_memory(NULL, ECAM_BUS0_BYTES, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, ECAM_BASE);
	if (ecam == MAP_FAILED) {
		fprintf(stderr, "shm: mmap_device_memory(ECAM 0x%llx): %s\n",
		        (unsigned long long)ECAM_BASE, strerror(errno));
		return -1;
	}
	for (dev = 0; dev < 32u; dev++) {
		volatile uint8_t *c = ecam + ((size_t)dev << 15);
		if (rd32(c + CFG_ID) == IVSHMEM_ID) {
			if (found++ == 0u) {
				cfg = c;
			}
		}
	}
	if (cfg == NULL || found != 1u) {
		fprintf(stderr, "shm: %u ivshmem functions (1af4:1110) on bus 0 at ECAM 0x%llx; this program "
		        "expects exactly one -- was QEMU given -device ivshmem-plain or ivshmem-doorbell?\n",
		        found, (unsigned long long)ECAM_BASE);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return -1;
	}
	dev = (unsigned)((cfg - ecam) >> 15);
	lo2 = rd32(cfg + CFG_BAR2);
	hi2 = rd32(cfg + CFG_BAR3);
	lo0 = rd32(cfg + CFG_BAR0);
	if ((lo2 & 0x1u) != 0u || ((lo2 >> 1) & 0x3u) != 0x2u || (lo0 & 0x7u) != 0u) {
		fprintf(stderr, "shm: BAR2 is not a 64-bit memory BAR (0x%08x) or BAR0 not a 32-bit one (0x%08x)\n",
		        lo2, lo0);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return -1;
	}
	cmd = rd16(cfg + CFG_CMD);
	wr16(cfg + CFG_CMD, (uint16_t)(cmd & (uint16_t)~CMD_MEM));
	m2 = size_mask(cfg + CFG_BAR2, cfg + CFG_BAR3);
	m0 = size_mask(cfg + CFG_BAR0, NULL) | 0xffffffff00000000ull;
	s2 = ~m2 + 1u;
	s0 = ~m0 + 1u;
	if (m2 == 0u || (s2 & (s2 - 1u)) != 0u || s2 < SHM_CHAN_MIN_BYTES || s2 > MMIO32_SIZE / 2u
	    || m0 == 0xffffffff00000000ull || (s0 & (s0 - 1u)) != 0u || s0 > 0x1000u) {
		fprintf(stderr, "shm: BAR2 sizes to 0x%llx and BAR0 to 0x%llx; this program will not map them\n",
		        (unsigned long long)s2, (unsigned long long)s0);
		wr16(cfg + CFG_CMD, cmd);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return -1;
	}
	a2 = ((uint64_t)hi2 << 32) | (uint64_t)(lo2 & ~0xfu);
	a0 = (uint64_t)(lo0 & ~0xfu);
	kept = a2 != 0u && a0 != 0u;
	if (!kept) {
		a2 = MMIO32_BASE;          /* aligned to far more than any size allowed above */
		a0 = a2 + s2;              /* BAR0 right after BAR2, aligned by BAR2's size */
	}
	if (a2 < MMIO32_BASE || a2 + s2 > MMIO32_BASE + MMIO32_SIZE || (a2 & (s2 - 1u)) != 0u
	    || a0 < MMIO32_BASE || a0 + s0 > MMIO32_BASE + MMIO32_SIZE || (a0 & (s0 - 1u)) != 0u
	    || (a0 < a2 + s2 && a2 < a0 + s0)) {
		fprintf(stderr, "shm: BAR2 0x%llx+0x%llx / BAR0 0x%llx+0x%llx are outside the window, "
		        "misaligned or overlapping\n", (unsigned long long)a2, (unsigned long long)s2,
		        (unsigned long long)a0, (unsigned long long)s0);
		wr16(cfg + CFG_CMD, cmd);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return -1;
	}
	if (!kept) {
		wr32(cfg + CFG_BAR2, (uint32_t)(a2 & 0xffffffffu) | (lo2 & 0xfu));
		wr32(cfg + CFG_BAR3, (uint32_t)(a2 >> 32));
		wr32(cfg + CFG_BAR0, (uint32_t)a0 | (lo0 & 0xfu));
	}
	wr16(cfg + CFG_CMD, (uint16_t)(cmd | CMD_MEM));
	lo2 = rd32(cfg + CFG_BAR2);
	hi2 = rd32(cfg + CFG_BAR3);
	lo0 = rd32(cfg + CFG_BAR0);
	cmd = rd16(cfg + CFG_CMD);
	munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
	if ((((uint64_t)hi2 << 32) | (uint64_t)(lo2 & ~0xfu)) != a2 || (uint64_t)(lo0 & ~0xfu) != a0
	    || (cmd & CMD_MEM) == 0u) {
		fprintf(stderr, "shm: BARs/command did not take (BAR2=0x%08x%08x BAR0=0x%08x cmd=0x%04x)\n",
		        hi2, lo2, lo0, cmd);
		return -1;
	}
	out->bar2 = a2;
	out->bar2_size = s2;
	out->bar0 = a0;
	out->bar0_size = s0;
	out->dev = dev;
	if (write_marker(out) != 0) {
		return -1;
	}
	snprintf(what, what_len, "ivshmem 00:%02x.0 BAR2 0x%llx (%llu bytes%s) BAR0 0x%llx (%llu bytes), %s, cmd=0x%04x",
	         dev, (unsigned long long)a2, (unsigned long long)s2, (lo2 & 0x8u) ? ", prefetchable" : "",
	         (unsigned long long)a0, (unsigned long long)s0,
	         kept ? "addresses kept as found" : "addresses assigned here", (unsigned)cmd);
	return 0;
}

int shm_configure(const char *spec, char *what, size_t what_len)
{
	struct ivcfg c;

	if (strcmp(spec, "ivshmem") != 0) {
		fprintf(stderr, "shm: in the guest the only region is 'ivshmem', not '%s'\n", spec);
		return -1;
	}
	if (read_marker(&c) == 0) {
		snprintf(what, what_len, "already configured: BAR2 0x%llx BAR0 0x%llx (marker)",
		         (unsigned long long)c.bar2, (unsigned long long)c.bar0);
		return 0;
	}
	return configure(&c, what, what_len);
}

static int get_config(const char *spec, struct ivcfg *c, char *what, size_t what_len)
{
	if (strcmp(spec, "ivshmem") != 0) {
		fprintf(stderr, "shm: in the guest the only region is 'ivshmem', not '%s'\n", spec);
		return -1;
	}
	if (read_marker(c) == 0) {
		snprintf(what, what_len, "ivshmem 00:%02x.0 BAR2 0x%llx, %llu bytes, BAR0 0x%llx, from the marker, cacheable",
		         c->dev, (unsigned long long)c->bar2, (unsigned long long)c->bar2_size,
		         (unsigned long long)c->bar0);
		return 0;
	}
	return configure(c, what, what_len);   /* no marker: configure, as the first version did */
}

void *shm_map(const char *spec, size_t *len, char *what, size_t what_len)
{
	struct ivcfg c;
	void *base;

	if (get_config(spec, &c, what, what_len) != 0) {
		return NULL;
	}
	base = mmap_device_memory(NULL, (size_t)c.bar2_size, PROT_READ | PROT_WRITE, 0, c.bar2);
	if (base == MAP_FAILED) {
		fprintf(stderr, "shm: mmap_device_memory(BAR2 0x%llx): %s\n",
		        (unsigned long long)c.bar2, strerror(errno));
		return NULL;
	}
	*len = (size_t)c.bar2_size;
	return base;
}

struct shm_kick {
	volatile uint8_t *regs;        /* BAR0 */
	int tty;
	uint32_t my_id;
	struct shm_kick_stats st;
};

struct shm_kick *shm_kick_open(const char *spec, size_t offset, const char *kick,
                               void **slot, char *what, size_t what_len)
{
	struct ivcfg c;
	struct termios t;
	char cfgwhat[256];
	uint8_t *base;
	struct shm_kick *k;

	if (get_config(spec, &c, cfgwhat, sizeof(cfgwhat)) != 0) {
		return NULL;
	}
	if (offset % SHM_CHAN_LINE != 0 || offset > c.bar2_size || c.bar2_size - offset < SHM_CHAN_MIN_BYTES) {
		fprintf(stderr, "shm-kick: slot offset %zu does not fit BAR2's %llu bytes\n",
		        offset, (unsigned long long)c.bar2_size);
		return NULL;
	}
	k = calloc(1, sizeof(*k));
	if (k == NULL) {
		return NULL;
	}
	base = mmap_device_memory(NULL, (size_t)c.bar2_size, PROT_READ | PROT_WRITE, 0, c.bar2);
	k->regs = mmap_device_memory(NULL, 0x1000u, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, c.bar0);
	if (base == MAP_FAILED || k->regs == MAP_FAILED) {
		fprintf(stderr, "shm-kick: mapping BAR2/BAR0: %s\n", strerror(errno));
		free(k);
		return NULL;
	}
	/* The server numbers peers from 1, so a 0 here means BAR0 is not the
	 * register file it should be (or the device is ivshmem-plain, which has
	 * no peers and cannot ring anyone). */
	k->my_id = rd32(k->regs + REG_IVPOSITION);
	if (k->my_id == 0u || k->my_id > 65535u) {
		fprintf(stderr, "shm-kick: IVPosition reads %u -- not an ivshmem-doorbell with a server "
		        "that numbers peers from 1\n", k->my_id);
		free(k);
		return NULL;
	}
	k->tty = open(kick, O_RDWR | O_NOCTTY);
	if (k->tty < 0) {
		fprintf(stderr, "shm-kick: open(%s): %s\n", kick, strerror(errno));
		free(k);
		return NULL;
	}
	/* Raw, and nothing the line discipline could eat or act on: a kick byte
	 * must arrive as itself, and none may stop output or raise a signal. */
	if (tcgetattr(k->tty, &t) != 0) {
		fprintf(stderr, "shm-kick: tcgetattr(%s): %s\n", kick, strerror(errno));
		close(k->tty);
		free(k);
		return NULL;
	}
	cfmakeraw(&t);
	t.c_iflag &= ~(tcflag_t)(IXON | IXOFF | ICRNL | ISTRIP);
	t.c_oflag &= ~(tcflag_t)OPOST;
	t.c_lflag &= ~(tcflag_t)(ECHO | ICANON | ISIG | IEXTEN);
	t.c_cflag &= ~(tcflag_t)(IHFLOW | OHFLOW);
	t.c_cflag |= (tcflag_t)(CLOCAL | CREAD);
	t.c_cc[VMIN] = 1;
	t.c_cc[VTIME] = 0;
	if (tcsetattr(k->tty, TCSANOW, &t) != 0) {
		fprintf(stderr, "shm-kick: tcsetattr(%s): %s\n", kick, strerror(errno));
		close(k->tty);
		free(k);
		return NULL;
	}
	tcflush(k->tty, TCIOFLUSH);
	*slot = base + offset;
	snprintf(what, what_len, "%s; slot @%zu; peer %u; kick %s (raw)", cfgwhat, offset, k->my_id, kick);
	return k;
}

int shm_kick_wait(struct shm_kick *k)
{
	unsigned char buf[64];
	int kicked = 0;
	ssize_t n = read(k->tty, buf, sizeof(buf));

	if (n < 0) {
		return errno == EINTR ? 0 : -1;
	}
	for (ssize_t i = 0; i < n; i++) {
		if (buf[i] == SHM_KICK_BYTE) {
			k->st.kick_bytes++;
			kicked = 1;
		} else if (buf[i] == SHM_ECHO_BYTE) {
			unsigned char e = SHM_ECHO_BYTE;
			k->st.echoes++;
			if (write(k->tty, &e, 1) != 1) {
				k->st.notify_fail++;
			}
		} else {
			k->st.stray_bytes++;
		}
	}
	return kicked;
}

int shm_kick_notify(struct shm_kick *k, unsigned via, unsigned peer, unsigned count)
{
	unsigned char b = SHM_KICK_BYTE;

	switch (via) {
	case SHM_VIA_KICK:
		if (write(k->tty, &b, 1) != 1) {
			k->st.notify_fail++;
			return -1;
		}
		k->st.notify_kicks++;
		return 0;
	case SHM_VIA_DOORBELL:
		count = 1;
		/* fall through */
	case SHM_VIA_BURST:
		if (count == 0u || count > SHM_BURST_MAX || peer == 0u || peer > 65535u) {
			k->st.notify_fail++;
			return -1;
		}
		/* The reply was published with a store-release to normal memory; the
		 * doorbell is a store to device memory, and release does not order a
		 * LATER device store. The barrier makes the reply visible before the
		 * doorbell can be. */
		__asm__ __volatile__("dsb st" ::: "memory");
		for (unsigned i = 0; i < count; i++) {
			wr32(k->regs + REG_DOORBELL, (uint32_t)peer << 16);
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
