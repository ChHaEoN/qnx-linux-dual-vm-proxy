/* A6, OD12 (2026-09-22) -- shm_map() for the QNX guest: QEMU's ivshmem.
 *
 * SPEC must be "ivshmem": the QEMU ivshmem PCI function (vendor 0x1af4, device
 * 0x1110) on bus 0 of QEMU's virt machine. Its BAR2 is the shared memory -- a
 * file in the host's /dev/shm that QEMU backs the BAR with (-object
 * memory-backend-file,share=on ... -device ivshmem-plain). BAR0 holds the
 * device's registers, which the plain device does not use.
 *
 * WHY NOT THE PCI SERVER. The plan was pci-server with the SDP's
 * pci_hw-fdt.so. On 2026-09-22 that module refused QEMU virt's generic ECAM
 * host bridge: by its own log it took the ECAM window's size as zero and found
 * no memory window, returned EINVAL, and enumeration aborted -- and its HW
 * config file can filter address windows but not add them. So this file does
 * the one thing needed itself, for this one function, through ECAM:
 *
 *   1. map bus 0's configuration space (1 MiB of ECAM), uncached;
 *   2. find 1af4:1110 at function 0 of some device;
 *   3. with memory decoding off, size BAR2 (64-bit) by the PCI rule -- write
 *      all ones, read the mask back -- and restore it;
 *   4. if BAR2 is unassigned, place it at the base of the 32-bit memory window,
 *      which no other device on this machine uses; if something already
 *      assigned it, keep that address and say so;
 *   5. enable memory decoding, verify it stuck, unmap the ECAM;
 *   6. map BAR2 CACHEABLE (below).
 * BAR0 is left unassigned: nothing here reads the device's registers.
 *
 * THE ADDRESSES are QEMU virt's (6.2, highmem on), read from its own generated
 * device tree on the Orin (qemu -machine virt,dumpdtb=...): ECAM reg
 * <0x40 0x10000000 0x0 0x10000000>, and a 32-bit memory window mapping PCI
 * 0x10000000 to CPU 0x10000000 (size 0x2eff0000). The IDs read at step 2 are
 * the check that the ECAM address is right: a wrong one finds nothing and
 * refuses.
 *
 * MMIO ACCESSES ARE SINGLE-REGISTER, WITHOUT WRITEBACK, BY INLINE ASM. Config
 * space accesses trap to QEMU, and KVM on this board can only emulate a trapped
 * access whose syndrome is valid (ISV=1). A compiler is free to use a
 * post-increment or a load/store pair for volatile accesses in a loop, and
 * those report ISV=0 -- the exact defect this project root-caused in the
 * shipped startup-qemu-virt. The accessors below pin the instruction.
 *
 * MAPPED CACHEABLE, ON PURPOSE: no PROT_NOCACHE on BAR2. The host maps the same
 * pages cacheable, and on a CPU without FEAT_S2FWB (the A78AE has none) a guest
 * uncached mapping would give the two views mismatched memory attributes, for
 * which Arm does not promise coherence. BAR2 is RAM in QEMU (a KVM memslot), so
 * ordinary loads and stores reach it without trapping.
 *
 * Runs as root (mmap of physical memory). Not portable beyond QEMU virt.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <sys/mman.h>

#include "shm_chan.h"
#include "shm_map.h"

#define ECAM_BASE       0x4010000000ull   /* QEMU virt, highmem: ECAM for buses 0..255 */
#define ECAM_BUS0_BYTES 0x100000u         /* 32 devices x 8 functions x 4 KiB */
#define MMIO32_BASE     0x10000000ull     /* PCI == CPU address in this window */
#define MMIO32_SIZE     0x2eff0000ull

#define IVSHMEM_ID      0x11101af4u       /* device << 16 | vendor */
#define CFG_ID          0x00u
#define CFG_CMD         0x04u
#define CFG_BAR2        0x18u
#define CFG_BAR3        0x1cu
#define CMD_MEM         0x0002u

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

void *shm_map(const char *spec, size_t *len, char *what, size_t what_len)
{
	volatile uint8_t *ecam, *cfg = NULL;
	uint32_t lo, hi, lo_mask, hi_mask;
	uint64_t addr, mask, size;
	uint16_t cmd;
	unsigned dev, found = 0;
	int kept;
	void *base;

	if (strcmp(spec, "ivshmem") != 0) {
		fprintf(stderr, "shm: in the guest the only region is 'ivshmem', not '%s'\n", spec);
		return NULL;
	}
	ecam = mmap_device_memory(NULL, ECAM_BUS0_BYTES, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, ECAM_BASE);
	if (ecam == MAP_FAILED) {
		fprintf(stderr, "shm: mmap_device_memory(ECAM 0x%llx): %s\n",
		        (unsigned long long)ECAM_BASE, strerror(errno));
		return NULL;
	}
	for (dev = 0; dev < 32u; dev++) {
		volatile uint8_t *c = ecam + ((size_t)dev << 15);
		if (rd32(c + CFG_ID) == IVSHMEM_ID) {
			if (found++ == 0u) {
				cfg = c;
			}
		}
	}
	if (cfg == NULL) {
		fprintf(stderr, "shm: no ivshmem function (1af4:1110) on bus 0 at ECAM 0x%llx -- "
		        "was QEMU given -device ivshmem-plain?\n", (unsigned long long)ECAM_BASE);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return NULL;
	}
	if (found > 1u) {
		fprintf(stderr, "shm: %u ivshmem functions on bus 0; this program expects exactly one\n", found);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return NULL;
	}
	dev = (unsigned)((cfg - ecam) >> 15);

	lo = rd32(cfg + CFG_BAR2);
	hi = rd32(cfg + CFG_BAR3);
	if ((lo & 0x1u) != 0u || ((lo >> 1) & 0x3u) != 0x2u) {
		fprintf(stderr, "shm: BAR2 is not a 64-bit memory BAR (0x%08x)\n", lo);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return NULL;
	}

	/* Size it with decoding off, then restore. */
	cmd = rd16(cfg + CFG_CMD);
	wr16(cfg + CFG_CMD, (uint16_t)(cmd & (uint16_t)~CMD_MEM));
	wr32(cfg + CFG_BAR2, 0xffffffffu);
	wr32(cfg + CFG_BAR3, 0xffffffffu);
	lo_mask = rd32(cfg + CFG_BAR2);
	hi_mask = rd32(cfg + CFG_BAR3);
	wr32(cfg + CFG_BAR2, lo);
	wr32(cfg + CFG_BAR3, hi);
	mask = ((uint64_t)hi_mask << 32) | (uint64_t)(lo_mask & ~0xfu);
	size = ~mask + 1u;
	if (mask == 0u || (size & (size - 1u)) != 0u || size < SHM_CHAN_MIN_BYTES || size > MMIO32_SIZE) {
		fprintf(stderr, "shm: BAR2 sizes to 0x%llx, which this program will not map\n",
		        (unsigned long long)size);
		wr16(cfg + CFG_CMD, cmd);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return NULL;
	}

	addr = ((uint64_t)hi << 32) | (uint64_t)(lo & ~0xfu);
	kept = addr != 0u;
	if (!kept) {
		addr = MMIO32_BASE;      /* aligned to far more than any size allowed above */
		wr32(cfg + CFG_BAR2, (uint32_t)(addr & 0xffffffffu) | (lo & 0xfu));
		wr32(cfg + CFG_BAR3, (uint32_t)(addr >> 32));
	} else if (addr < MMIO32_BASE || addr + size > MMIO32_BASE + MMIO32_SIZE || (addr & (size - 1u)) != 0u) {
		fprintf(stderr, "shm: BAR2 already at 0x%llx, outside the 32-bit window or misaligned\n",
		        (unsigned long long)addr);
		wr16(cfg + CFG_CMD, cmd);
		munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
		return NULL;
	}
	wr16(cfg + CFG_CMD, (uint16_t)(cmd | CMD_MEM));
	lo = rd32(cfg + CFG_BAR2);
	hi = rd32(cfg + CFG_BAR3);
	cmd = rd16(cfg + CFG_CMD);
	munmap_device_memory((void *)ecam, ECAM_BUS0_BYTES);
	if ((((uint64_t)hi << 32) | (uint64_t)(lo & ~0xfu)) != addr || (cmd & CMD_MEM) == 0u) {
		fprintf(stderr, "shm: BAR2/command did not take (BAR2=0x%08x%08x cmd=0x%04x)\n", hi, lo, cmd);
		return NULL;
	}

	base = mmap_device_memory(NULL, (size_t)size, PROT_READ | PROT_WRITE, 0, addr);
	if (base == MAP_FAILED) {
		fprintf(stderr, "shm: mmap_device_memory(BAR2 0x%llx): %s\n",
		        (unsigned long long)addr, strerror(errno));
		return NULL;
	}
	*len = (size_t)size;
	snprintf(what, what_len,
	         "ivshmem 00:%02x.0 BAR2 0x%llx, %zu bytes%s, %s, cmd=0x%04x, cacheable",
	         dev, (unsigned long long)addr, *len, (lo & 0x8u) ? " prefetchable" : "",
	         kept ? "address kept as found" : "address assigned here", (unsigned)cmd);
	return base;
}
