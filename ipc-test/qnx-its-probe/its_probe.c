/* qnx-its-probe -- A6, the ivshmem doorbell INTO the guest (2026-09-29).
 *
 *   qnx-its-probe info              what the syspage and the ITS registers say
 *   qnx-its-probe selftest [N]      N LPIs raised by the ITS's own INT command
 *   qnx-its-probe msixcfg [NVEC]    ivshmem's MSI-X vectors 0..NVEC-1 -> LPIs (once, early)
 *   qnx-its-probe msixwait [SECS]   wait on that LPI; ring the host back each time
 *
 * WHY. QEMU 6.2's ivshmem-doorbell interrupts a guest by MSI-X only, and this
 * guest has no PCI server to set MSI-X up, so until now the host could reach it
 * only through a virtio console (shm_map_qnx.c). On QEMU's virt machine an MSI
 * is a write to the GIC ITS's GITS_TRANSLATER that the ITS turns, by its own
 * tables, from (DeviceID, EventID) into an LPI. startup-qemu-virt-its sets the
 * ITS up and gives procnto an LPI block (vectors 8192.., vector == INTID); what
 * it leaves to the owner of a device is the device's mapping, MAPD and MAPTI.
 * With no PCI server that owner is this program, as shm_map_qnx.c is for BARs.
 *
 * THE ITS IS SHARED WITH THE KERNEL. procnto's LPI mask and unmask callouts
 * write INVALL/SYNC into the same command queue, under a lock the startup puts
 * one page past the queue and publishes as the second location of the syspage
 * hwinfo device "GIC_ITS" (the first is the ITS registers). This program takes
 * that lock the way the callouts do -- a counter, taken when an atomic add finds
 * it 0, else given back and retried -- and holds it only while it copies
 * commands in and moves GITS_CWRITER. It runs on CPU 1: every LPI here is routed
 * to CPU 0 (collection 0), so a callout spinning for the lock never waits on a
 * thread its own CPU has preempted.
 *
 * MEMORY ATTRIBUTES. The command queue and the lock are mapped cacheable when
 * GITS_CBASER says the queue is write-back, which startup-qemu-virt-its asks for
 * (see its header: KVM reads guest tables through a cacheable host mapping, and
 * this CPU has no FEAT_S2FWB). The ITS registers, ECAM and BAR0/BAR1 are
 * device memory, accessed one register at a time by inline asm with no
 * writeback: KVM emulates a trapped access only when its syndrome is valid
 * (ISV=1), which a post-increment or a load/store pair does not give.
 *
 * MSIXCFG MUST RUN BEFORE ANY SHM MONITOR, right after "qnx-safety-monitor
 * shmcfg": sizing BAR1 turns the function's memory decoding off, which unmaps
 * BAR0 and BAR2 under anyone already using them (the same rule shmcfg follows).
 * It places BAR1 after BAR0, points MSI-X table entry 0 at GITS_TRANSLATER with
 * EventID 0, maps (DeviceID = the function's requester ID, EventID 0) to LPI
 * MSIX_LPI through collection 0, enables MSI-X and bus mastering (an MSI is a
 * bus-master write; QEMU drops it otherwise), unmasks the entry, and writes
 * /dev/shmem/its-msix for msixwait.
 *
 * NVEC = 2 (2026-09-29; QEMU started with vectors=2) does the same for entry 1:
 * EventID 1 -> LPI MSIX_LPI + 1, and adds "lpi1=" to the marker. The default, 1,
 * is what every earlier image ran, command for command.
 *
 * MSIXWAIT counts the LPI and, when the host has put its ivshmem peer id at
 * ECHO_OFF in BAR2 (ivshmem_ring.py does), rings that peer back through the
 * Doorbell register -- one host-to-guest interrupt and one guest-to-host
 * ioeventfd per exchange, with no console on the path.
 *
 * WHAT THIS DOES NOT ESTABLISH. It is a functional probe, not a latency harness:
 * whatever it prints is a local record (NC QDL v7 4.6(i)). It proves nothing
 * about a real ITS (KVM keeps its translations in kernel structures and never
 * reads the ITT), nothing about QNX's supported MSI path (the PCI server, which
 * this guest does not run), and nothing about more than two vectors or one
 * device. And it runs on a startup WE rebuilt: not a QNX-supported
 * configuration.
 *
 * Runs as root (physical mappings, interrupt events). Not portable beyond
 * QEMU's virt machine under KVM.
 */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/neutrino.h>
#include <sys/syspage.h>
#include <hw/sysinfo.h>

#define LPI_BASE        8192u        /* startup-qemu-virt-its: vector == INTID */
#define SELFTEST_LPI    (LPI_BASE + 100u)
#define SELFTEST_DEVID  0xff00u      /* bus 0xff: no function on bus 0 can have it */
#define MSIX_LPI        (LPI_BASE + 1u)
#define MSIX_VECTORS_MAX 2u          /* msixcfg NVEC: vector v -> EventID v -> LPI MSIX_LPI + v */
#define ICID            0u           /* collection 0 = CPU 0 (the startup's MAPC) */

#define GITS_CTLR       0x000u
#define GITS_IIDR       0x004u
#define GITS_TYPER      0x008u
#define GITS_CBASER     0x080u
#define GITS_CWRITER    0x088u
#define GITS_CREADR     0x090u
#define GITS_BASER(n)   (0x100u + 8u * (n))
#define GITS_TRANSLATER 0x10040u     /* in the ITS's second 64 KiB frame */

#define CMD_INT         0x03u
#define CMD_SYNC        0x05u
#define CMD_MAPD        0x08u
#define CMD_MAPTI       0x0au
#define CMD_DISCARD     0x0fu

#define ECAM_BASE       0x4010000000ull   /* as shm_map_qnx.c: QEMU virt, highmem */
#define ECAM_BUS0_BYTES 0x100000u
#define MMIO32_BASE     0x10000000ull
#define MMIO32_SIZE     0x2eff0000ull
#define IVSHMEM_ID      0x11101af4u
#define CFG_CMD         0x04u
#define CFG_STATUS      0x06u
#define CFG_BAR1        0x14u
#define CFG_CAP_PTR     0x34u
#define CMD_MEM         0x0002u
#define CMD_MASTER      0x0004u
#define CAP_MSIX        0x11u
#define MSIX_ENABLE     0x8000u
#define MSIX_FMASK      0x4000u
#define REG_DOORBELL    0x0cu
#define ECHO_OFF        65536u       /* host peer id, uint32, in BAR2; far past every monitor slot */

#define SHM_MARKER      "/ivshmem-config"
#define MSIX_MARKER     "/its-msix"

/* ------------------------------------------------------------ device access */

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

static inline uint64_t rd64(volatile uint8_t *p)
{
	uint64_t v;
	__asm__ __volatile__("ldr %0, [%1]" : "=r"(v) : "r"(p) : "memory");
	return v;
}

static inline void wr64(volatile uint8_t *p, uint64_t v)
{
	__asm__ __volatile__("str %0, [%1]" : : "r"(v), "r"(p) : "memory");
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

static inline uint8_t rd8(volatile uint8_t *p)
{
	uint8_t v;
	__asm__ __volatile__("ldrb %w0, [%1]" : "=r"(v) : "r"(p) : "memory");
	return v;
}

static uint64_t now_ns(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

/* ---------------------------------------------------------------- the ITS */

struct its {
	uint64_t pa, lock_pa, q_pa, typer, cbaser;
	volatile uint8_t *regs;          /* frame 0, device memory */
	volatile uint8_t *q;             /* command queue */
	volatile uint32_t *lock;
	size_t q_bytes;
	int q_cached;
	unsigned devbits, idbits, itt_entry;
};

static int its_open(struct its *t)
{
	unsigned item, t1, t2;
	hwi_tag *a, *b;
	void *lockpage;

	memset(t, 0, sizeof(*t));
	item = hwi_find_item(HWI_NULL_OFF, "GIC_ITS", NULL);
	if (item == HWI_NULL_OFF) {
		fprintf(stderr, "its: no GIC_ITS device in the syspage hwinfo -- this image's startup is "
		        "not startup-qemu-virt-its, or QEMU presented no ITS\n");
		return -1;
	}
	t1 = hwi_find_tag(item, 1, HWI_TAG_NAME_location);
	t2 = t1 == HWI_NULL_OFF ? HWI_NULL_OFF : hwi_find_tag(t1, 1, HWI_TAG_NAME_location);
	if (t1 == HWI_NULL_OFF || t2 == HWI_NULL_OFF) {
		fprintf(stderr, "its: GIC_ITS lacks its two locations (registers, command-queue lock)\n");
		return -1;
	}
	a = hwi_off2tag(t1);
	b = hwi_off2tag(t2);
	t->pa = a->location.base;
	t->lock_pa = b->location.base;

	t->regs = mmap_device_memory(NULL, 0x10000u, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, t->pa);
	if (t->regs == MAP_FAILED) {
		fprintf(stderr, "its: mmap_device_memory(GITS 0x%" PRIx64 "): %s\n", t->pa, strerror(errno));
		return -1;
	}
	t->typer = rd64(t->regs + GITS_TYPER);
	t->cbaser = rd64(t->regs + GITS_CBASER);
	t->devbits = (unsigned)((t->typer >> 13) & 0x1fu) + 1u;
	t->idbits = (unsigned)((t->typer >> 8) & 0x1fu) + 1u;
	t->itt_entry = (unsigned)((t->typer >> 4) & 0xfu) + 1u;
	if ((t->cbaser >> 63) == 0u) {
		fprintf(stderr, "its: GITS_CBASER 0x%016" PRIx64 " is not valid: the startup set up no queue\n", t->cbaser);
		return -1;
	}
	if ((rd32(t->regs + GITS_CTLR) & 1u) == 0u) {
		fprintf(stderr, "its: the ITS is not enabled (GITS_CTLR bit 0): the startup's MAPC never ran\n");
		return -1;
	}
	t->q_pa = t->cbaser & 0x000ffffffffff000ull;
	t->q_bytes = ((size_t)(t->cbaser & 0xffu) + 1u) * 4096u;
	{
		/* InnerCache 3, 5 and 7 are the write-back encodings. */
		unsigned const ic = (unsigned)((t->cbaser >> 59) & 7u);
		t->q_cached = ic == 3u || ic == 5u || ic == 7u;
	}
	t->q = mmap_device_memory(NULL, t->q_bytes, PROT_READ | PROT_WRITE | (t->q_cached ? 0 : PROT_NOCACHE),
	                          0, t->q_pa);
	lockpage = mmap_device_memory(NULL, 4096u, PROT_READ | PROT_WRITE, 0, t->lock_pa & ~(uint64_t)0xfffu);
	if (t->q == MAP_FAILED || lockpage == MAP_FAILED) {
		fprintf(stderr, "its: mapping the command queue / lock: %s\n", strerror(errno));
		return -1;
	}
	t->lock = (volatile uint32_t *)((volatile uint8_t *)lockpage + (t->lock_pa & 0xfffu));
	return 0;
}

static void its_lock(struct its *t)
{
	for (;;) {
		if (__atomic_fetch_add(t->lock, 1u, __ATOMIC_ACQUIRE) == 0u) {
			return;
		}
		__atomic_fetch_sub(t->lock, 1u, __ATOMIC_RELAXED);
	}
}

static void its_unlock(struct its *t)
{
	__atomic_fetch_sub(t->lock, 1u, __ATOMIC_RELEASE);
}

/* Copy n commands into the queue after GITS_CWRITER, move CWRITER, and wait
 * until the ITS has read up to it. Returns -1 on a stall or a timeout. */
static int its_submit(struct its *t, const uint64_t (*cmd)[4], unsigned n)
{
	uint64_t cw, cr, target;
	uint64_t const t0 = now_ns();

	its_lock(t);
	cw = rd64(t->regs + GITS_CWRITER) & 0xfffe0u;
	cr = rd64(t->regs + GITS_CREADR) & 0xfffe0u;
	if (((cr + t->q_bytes - cw - 32u) % t->q_bytes) < (uint64_t)n * 32u) {
		its_unlock(t);
		fprintf(stderr, "its: command queue full (CWRITER 0x%" PRIx64 ", CREADR 0x%" PRIx64 ")\n", cw, cr);
		return -1;
	}
	for (unsigned i = 0; i < n; i++) {
		volatile uint64_t *slot = (volatile uint64_t *)(t->q + cw);
		slot[0] = cmd[i][0];
		slot[1] = cmd[i][1];
		slot[2] = cmd[i][2];
		slot[3] = cmd[i][3];
		cw = (cw + 32u) % t->q_bytes;
	}
	/* The commands must be visible before the ITS is told to read them. */
	__asm__ __volatile__("dsb sy" ::: "memory");
	wr64(t->regs + GITS_CWRITER, cw);
	its_unlock(t);

	/* The callouts may queue more behind ours; ours are done once CREADR
	 * has moved past them, which is the same as reaching `target` or any
	 * point after it -- so wait for CREADR == CWRITER at the time of reading,
	 * or for it to have passed target. */
	target = cw;
	for (;;) {
		cr = rd64(t->regs + GITS_CREADR);
		if ((cr & 1u) != 0u) {
			fprintf(stderr, "its: the ITS stalled on a command (GITS_CREADR 0x%" PRIx64 ")\n", cr);
			return -1;
		}
		if ((cr & 0xfffe0u) == target || (cr & 0xfffe0u) == (rd64(t->regs + GITS_CWRITER) & 0xfffe0u)) {
			return 0;
		}
		if (now_ns() - t0 > 1000000000ull) {
			fprintf(stderr, "its: the ITS did not consume the commands within 1 s (CREADR 0x%" PRIx64
			        ", waiting for 0x%" PRIx64 ")\n", cr, target);
			return -1;
		}
	}
}

static void cmd_mapd(uint64_t c[4], uint32_t dev, unsigned evbits, uint64_t itt_pa, int valid)
{
	c[0] = CMD_MAPD | ((uint64_t)dev << 32);
	c[1] = (uint64_t)(evbits - 1u) & 0x1fu;
	c[2] = (valid ? (1ull << 63) : 0u) | (itt_pa & 0x000fffffffffff00ull);
	c[3] = 0;
}

static void cmd_mapti(uint64_t c[4], uint32_t dev, uint32_t ev, uint32_t lpi)
{
	c[0] = CMD_MAPTI | ((uint64_t)dev << 32);
	c[1] = (uint64_t)ev | ((uint64_t)lpi << 32);
	c[2] = ICID;
	c[3] = 0;
}

static void cmd_devev(uint64_t c[4], unsigned op, uint32_t dev, uint32_t ev)
{
	c[0] = op | ((uint64_t)dev << 32);
	c[1] = ev;
	c[2] = 0;
	c[3] = 0;
}

/* SYNC to redistributor 0. With GITS_TYPER.PTA = 0 RDbase is a processor
 * number, in bits [51:16]; with PTA = 1 it would be an address, which this
 * machine's ITS does not use (checked in info). */
static void cmd_sync(uint64_t c[4])
{
	c[0] = CMD_SYNC;
	c[1] = 0;
	c[2] = 0;
	c[3] = 0;
}

/* An ITT: physically contiguous, 256-byte aligned (a page is), for 2 EventIDs.
 * KVM never reads it, but a real ITS would, so it is real memory. With a name
 * it is a shared memory object that outlives this process, as the mapping it
 * backs does (msixcfg exits and the device stays mapped); without one it is
 * this process's own, for a mapping this process also removes (selftest). */
static void *itt_alloc(const char *name, uint64_t *pa)
{
	off64_t off;
	size_t contig;
	void *p;

	if (name == NULL) {
		p = mmap(NULL, 4096u, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON | MAP_PHYS, NOFD, 0);
	} else {
		int fd;
		shm_unlink(name);
		fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0400);
		if (fd < 0 || shm_ctl(fd, SHMCTL_ANON | SHMCTL_PHYS, 0, 4096u) != 0) {
			fprintf(stderr, "its: creating /dev/shmem%s for the ITT: %s\n", name, strerror(errno));
			return NULL;
		}
		p = mmap(NULL, 4096u, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
		close(fd);
	}
	if (p == MAP_FAILED) {
		fprintf(stderr, "its: allocating an ITT: %s\n", strerror(errno));
		return NULL;
	}
	memset(p, 0, 4096u);
	if (mem_offset64(p, NOFD, 4096u, &off, &contig) != 0 || contig < 4096u) {
		fprintf(stderr, "its: the ITT's physical address: %s\n", strerror(errno));
		return NULL;
	}
	*pa = (uint64_t)off;
	return p;
}

static void on_cpu1(void)
{
	if (_syspage_ptr->num_cpu > 1u) {
		if (ThreadCtl(_NTO_TCTL_RUNMASK, (void *)(uintptr_t)0x2u) == -1) {
			fprintf(stderr, "its: runmask to CPU 1: %s (continuing)\n", strerror(errno));
		}
	}
}

/* ------------------------------------------------------------------- info */

static int do_info(void)
{
	struct its t;

	if (its_open(&t) != 0) {
		return 1;
	}
	printf("its: GITS 0x%" PRIx64 ", lock 0x%" PRIx64 "\n", t.pa, t.lock_pa);
	printf("its: CTLR 0x%08x IIDR 0x%08x TYPER 0x%016" PRIx64 " (Devbits %u, IDbits %u, ITT entry %u B, PTA %u)\n",
	       rd32(t.regs + GITS_CTLR), rd32(t.regs + GITS_IIDR), t.typer, t.devbits, t.idbits, t.itt_entry,
	       (unsigned)((t.typer >> 19) & 1u));
	printf("its: CBASER 0x%016" PRIx64 " -> queue 0x%" PRIx64 ", %zu B, InnerCache %u, Shareability %u, mapped %s\n",
	       t.cbaser, t.q_pa, t.q_bytes, (unsigned)((t.cbaser >> 59) & 7u), (unsigned)((t.cbaser >> 10) & 3u),
	       t.q_cached ? "cacheable" : "uncached");
	for (unsigned i = 0; i < 8u; i++) {
		uint64_t const b = rd64(t.regs + GITS_BASER(i));
		if (((b >> 56) & 7u) != 0u) {
			printf("its: BASER%u 0x%016" PRIx64 " (type %u, valid %u, InnerCache %u, Shareability %u)\n", i, b,
			       (unsigned)((b >> 56) & 7u), (unsigned)(b >> 63), (unsigned)((b >> 59) & 7u),
			       (unsigned)((b >> 10) & 3u));
		}
	}
	printf("its: CWRITER 0x%" PRIx64 " CREADR 0x%" PRIx64 ", lock word %u\n",
	       rd64(t.regs + GITS_CWRITER), rd64(t.regs + GITS_CREADR), *t.lock);
	return 0;
}

/* --------------------------------------------------------------- selftest */

static int do_selftest(unsigned n)
{
	struct its t;
	uint64_t itt_pa, c[3][4];
	struct sigevent ev;
	unsigned got = 0, timeouts = 0;
	uint64_t worst = 0;
	void *itt;
	int id, rc = 0;

	on_cpu1();
	if (its_open(&t) != 0 || (itt = itt_alloc(NULL, &itt_pa)) == NULL) {
		return 1;
	}
	if (SELFTEST_DEVID >= (1u << t.devbits) || SELFTEST_LPI >= (1u << t.idbits)) {
		fprintf(stderr, "its: DeviceID 0x%x or LPI %u out of the ITS's range\n", SELFTEST_DEVID, SELFTEST_LPI);
		return 1;
	}
	cmd_mapd(c[0], SELFTEST_DEVID, 1u, itt_pa, 1);
	cmd_mapti(c[1], SELFTEST_DEVID, 0u, SELFTEST_LPI);
	cmd_sync(c[2]);
	if (its_submit(&t, (const uint64_t (*)[4])c, 3u) != 0) {
		return 1;
	}
	printf("its: selftest: DeviceID 0x%x EventID 0 -> LPI %u (ITT 0x%" PRIx64 ")\n",
	       SELFTEST_DEVID, SELFTEST_LPI, itt_pa);

	SIGEV_INTR_INIT(&ev);
	id = InterruptAttachEvent((int)SELFTEST_LPI, &ev, _NTO_INTR_FLAGS_TRK_MSK);
	if (id == -1) {
		fprintf(stderr, "its: InterruptAttachEvent(%u): %s\n", SELFTEST_LPI, strerror(errno));
		return 1;
	}
	for (unsigned i = 0; i < n; i++) {
		uint64_t const timeout = 1000000000ull;
		uint64_t t0, dt;

		cmd_devev(c[0], CMD_INT, SELFTEST_DEVID, 0u);
		t0 = now_ns();
		if (its_submit(&t, (const uint64_t (*)[4])c, 1u) != 0) {
			rc = 1;
			break;
		}
		TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_INTR, NULL, &timeout, NULL);
		if (InterruptWait(0, NULL) == -1) {
			if (errno == ETIMEDOUT) {
				timeouts++;
				continue;
			}
			fprintf(stderr, "its: InterruptWait: %s\n", strerror(errno));
			rc = 1;
			break;
		}
		dt = now_ns() - t0;
		worst = dt > worst ? dt : worst;
		got++;
		InterruptUnmask((int)SELFTEST_LPI, id);
	}
	InterruptDetach(id);
	cmd_devev(c[0], CMD_DISCARD, SELFTEST_DEVID, 0u);
	cmd_mapd(c[1], SELFTEST_DEVID, 1u, 0u, 0);
	cmd_sync(c[2]);
	if (its_submit(&t, (const uint64_t (*)[4])c, 3u) != 0) {
		rc = 1;
	}
	munmap(itt, 4096u);
	printf("its: selftest: %u INT commands, %u LPIs delivered, %u timeouts (1 s each), slowest %" PRIu64 " us%s\n",
	       n, got, timeouts, worst / 1000u, rc ? ", with errors" : "");
	return rc || got != n;
}

/* ---------------------------------------------------------------- msixcfg */

struct shmcfg {
	uint64_t bar2, bar2_size, bar0, bar0_size;
	unsigned dev;
};

static int read_shm_marker(struct shmcfg *c)
{
	char buf[256];
	ssize_t n;
	int fd = shm_open(SHM_MARKER, O_RDONLY, 0);

	if (fd < 0) {
		fprintf(stderr, "its: no /dev/shmem%s: run \"qnx-safety-monitor shmcfg ivshmem\" first\n", SHM_MARKER);
		return -1;
	}
	n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	if (n <= 0) {
		return -1;
	}
	buf[n] = '\0';
	if (sscanf(buf, "bar2=%" SCNx64 " bar2_size=%" SCNx64 " bar0=%" SCNx64 " bar0_size=%" SCNx64 " dev=%u",
	           &c->bar2, &c->bar2_size, &c->bar0, &c->bar0_size, &c->dev) != 5) {
		fprintf(stderr, "its: /dev/shmem%s is malformed: %s\n", SHM_MARKER, buf);
		return -1;
	}
	return 0;
}

static int do_msixcfg(unsigned nvec)
{
	struct its t;
	struct shmcfg s;
	volatile uint8_t *ecam, *cfg, *tbl;
	uint64_t itt_pa, c[2 + MSIX_VECTORS_MAX][4], a1, s1, tr;
	uint32_t lo1, tblreg;
	uint16_t cmd, mc;
	unsigned cap = 0, bir, guard = 0, devid;
	char buf[160];
	int fd, len;

	on_cpu1();
	if (nvec < 1u || nvec > MSIX_VECTORS_MAX) {
		fprintf(stderr, "its: msixcfg maps 1..%u vectors, not %u\n", MSIX_VECTORS_MAX, nvec);
		return 1;
	}
	if (read_shm_marker(&s) != 0 || its_open(&t) != 0) {
		return 1;
	}
	ecam = mmap_device_memory(NULL, ECAM_BUS0_BYTES, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, ECAM_BASE);
	if (ecam == MAP_FAILED) {
		fprintf(stderr, "its: mmap_device_memory(ECAM): %s\n", strerror(errno));
		return 1;
	}
	cfg = ecam + ((size_t)s.dev << 15);
	if (rd32(cfg) != IVSHMEM_ID) {
		fprintf(stderr, "its: 00:%02x.0 is not the ivshmem function the marker names\n", s.dev);
		return 1;
	}
	/* The MSI-X capability. */
	if ((rd16(cfg + CFG_STATUS) & 0x10u) != 0u) {
		unsigned p = rd8(cfg + CFG_CAP_PTR) & 0xfcu;
		while (p != 0u && guard++ < 48u) {
			if (rd8(cfg + p) == CAP_MSIX) {
				cap = p;
				break;
			}
			p = rd8(cfg + p + 1u) & 0xfcu;
		}
	}
	if (cap == 0u) {
		fprintf(stderr, "its: 00:%02x.0 has no MSI-X capability: ivshmem-plain, or vectors=0?\n", s.dev);
		return 1;
	}
	mc = rd16(cfg + cap + 2u);
	tblreg = rd32(cfg + cap + 4u);
	bir = tblreg & 7u;
	if ((unsigned)(mc & 0x7ffu) + 1u < nvec) {
		fprintf(stderr, "its: the MSI-X table has %u entries, not %u: start QEMU with vectors=%u\n",
		        (unsigned)(mc & 0x7ffu) + 1u, nvec, nvec);
		return 1;
	}
	if (bir != 1u) {
		fprintf(stderr, "its: the MSI-X table is in BAR%u, not BAR1 as ivshmem puts it\n", bir);
		return 1;
	}

	/* BAR1: size it with decoding off (this is why msixcfg runs before any
	 * monitor), place it after BAR0, turn decoding back on. */
	cmd = rd16(cfg + CFG_CMD);
	wr16(cfg + CFG_CMD, (uint16_t)(cmd & (uint16_t)~(CMD_MEM | CMD_MASTER)));
	lo1 = rd32(cfg + CFG_BAR1);
	wr32(cfg + CFG_BAR1, 0xffffffffu);
	s1 = ~((uint64_t)(rd32(cfg + CFG_BAR1) & ~0xfu) | 0xffffffff00000000ull) + 1u;
	wr32(cfg + CFG_BAR1, lo1);
	if ((lo1 & 0x7u) != 0u || s1 == 0u || (s1 & (s1 - 1u)) != 0u || s1 > 0x10000u) {
		fprintf(stderr, "its: BAR1 (0x%08x) is not a 32-bit memory BAR of a sane size (0x%" PRIx64 ")\n", lo1, s1);
		wr16(cfg + CFG_CMD, cmd);
		return 1;
	}
	a1 = (s.bar0 + s.bar0_size + s1 - 1u) & ~(s1 - 1u);
	if (a1 + s1 > MMIO32_BASE + MMIO32_SIZE || (a1 < s.bar2 + s.bar2_size && s.bar2 < a1 + s1)) {
		fprintf(stderr, "its: no room for BAR1 (0x%" PRIx64 "+0x%" PRIx64 ")\n", a1, s1);
		wr16(cfg + CFG_CMD, cmd);
		return 1;
	}
	wr32(cfg + CFG_BAR1, (uint32_t)a1 | (lo1 & 0xfu));
	wr16(cfg + CFG_CMD, (uint16_t)(cmd | CMD_MEM));
	if ((uint64_t)(rd32(cfg + CFG_BAR1) & ~0xfu) != a1 || (rd16(cfg + CFG_CMD) & CMD_MEM) == 0u) {
		fprintf(stderr, "its: BAR1 did not take (0x%08x)\n", rd32(cfg + CFG_BAR1));
		return 1;
	}

	/* Table entry i -> GITS_TRANSLATER, EventID i, masked for now. */
	tbl = mmap_device_memory(NULL, (size_t)s1, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, a1);
	if (tbl == MAP_FAILED) {
		fprintf(stderr, "its: mmap_device_memory(BAR1): %s\n", strerror(errno));
		return 1;
	}
	tbl += tblreg & ~7u;
	tr = t.pa + GITS_TRANSLATER;
	for (unsigned v = 0; v < nvec; v++) {
		volatile uint8_t *e = tbl + 16u * v;
		wr32(e + 12u, 1u);
		wr32(e + 0u, (uint32_t)tr);
		wr32(e + 4u, (uint32_t)(tr >> 32));
		wr32(e + 8u, v);
	}

	/* The ITS side: the function's requester ID is its DeviceID. */
	devid = s.dev << 3;
	if (devid >= (1u << t.devbits) || MSIX_LPI + nvec - 1u >= (1u << t.idbits)) {
		fprintf(stderr, "its: DeviceID 0x%x or LPI %u out of the ITS's range\n", devid, MSIX_LPI + nvec - 1u);
		return 1;
	}
	if (itt_alloc("/its-msix-itt", &itt_pa) == NULL) {
		return 1;
	}
	cmd_mapd(c[0], devid, 1u, itt_pa, 1);               /* 1 bit of EventID: 0 and 1 */
	for (unsigned v = 0; v < nvec; v++) {
		cmd_mapti(c[1 + v], devid, v, MSIX_LPI + v);
	}
	cmd_sync(c[1 + nvec]);
	if (its_submit(&t, (const uint64_t (*)[4])c, 2u + nvec) != 0) {
		return 1;
	}

	/* MSI-X on, function unmasked, bus mastering on, then the entry. */
	wr16(cfg + cap + 2u, (uint16_t)((mc | MSIX_ENABLE) & (uint16_t)~MSIX_FMASK));
	wr16(cfg + CFG_CMD, (uint16_t)(rd16(cfg + CFG_CMD) | CMD_MEM | CMD_MASTER));
	for (unsigned v = 0; v < nvec; v++) {
		wr32(tbl + 16u * v + 12u, 0u);
	}
	mc = rd16(cfg + cap + 2u);
	cmd = rd16(cfg + CFG_CMD);
	if ((mc & MSIX_ENABLE) == 0u || (mc & MSIX_FMASK) != 0u || (cmd & CMD_MASTER) == 0u) {
		fprintf(stderr, "its: MSI-X enable / bus mastering did not take (MC 0x%04x, cmd 0x%04x)\n", mc, cmd);
		return 1;
	}

	/* One vector: the marker every earlier image wrote. Two: " lpi1=" added, which
	 * an older reader's four-field sscanf ignores. */
	if (nvec == 1u) {
		len = snprintf(buf, sizeof(buf), "dev=%u devid=%u bar1=%" PRIx64 " lpi=%u\n", s.dev, devid, a1, MSIX_LPI);
	} else {
		len = snprintf(buf, sizeof(buf), "dev=%u devid=%u bar1=%" PRIx64 " lpi=%u lpi1=%u\n",
		               s.dev, devid, a1, MSIX_LPI, MSIX_LPI + 1u);
	}
	fd = shm_open(MSIX_MARKER, O_RDWR | O_CREAT | O_TRUNC, 0444);
	if (fd < 0 || ftruncate(fd, len) != 0 || write(fd, buf, (size_t)len) != len) {
		fprintf(stderr, "its: writing /dev/shmem%s: %s\n", MSIX_MARKER, strerror(errno));
		return 1;
	}
	close(fd);
	printf("its: msixcfg: ivshmem 00:%02x.0 BAR1 0x%" PRIx64 " (%" PRIu64 " B), MSI-X entry 0 -> 0x%" PRIx64
	       " data 0, DeviceID 0x%x EventID 0 -> LPI %u (ITT 0x%" PRIx64 "), MC 0x%04x cmd 0x%04x\n",
	       s.dev, a1, s1, tr, devid, MSIX_LPI, itt_pa, mc, cmd);
	for (unsigned v = 1; v < nvec; v++) {
		printf("its: msixcfg: MSI-X entry %u -> 0x%" PRIx64 " data %u, DeviceID 0x%x EventID %u -> LPI %u\n",
		       v, tr, v, devid, v, MSIX_LPI + v);
	}
	return 0;
}

/* --------------------------------------------------------------- msixwait */

static int do_msixwait(unsigned secs)
{
	struct shmcfg s;
	struct sigevent ev;
	volatile uint8_t *bar0, *bar2;
	uint64_t const start = now_ns();
	uint64_t last_print = start;
	unsigned got = 0, echoes = 0, printed = 0;
	int id;

	if (read_shm_marker(&s) != 0) {
		return 1;
	}
	{
		int fd = shm_open(MSIX_MARKER, O_RDONLY, 0);
		if (fd < 0) {
			fprintf(stderr, "its: no /dev/shmem%s: run \"qnx-its-probe msixcfg\" first\n", MSIX_MARKER);
			return 1;
		}
		close(fd);
	}
	bar0 = mmap_device_memory(NULL, 0x1000u, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, s.bar0);
	bar2 = mmap_device_memory(NULL, (size_t)s.bar2_size, PROT_READ | PROT_WRITE, 0, s.bar2);
	if (bar0 == MAP_FAILED || bar2 == MAP_FAILED || s.bar2_size < ECHO_OFF + 4u) {
		fprintf(stderr, "its: mapping BAR0/BAR2: %s\n", strerror(errno));
		return 1;
	}
	SIGEV_INTR_INIT(&ev);
	id = InterruptAttachEvent((int)MSIX_LPI, &ev, _NTO_INTR_FLAGS_TRK_MSK);
	if (id == -1) {
		fprintf(stderr, "its: InterruptAttachEvent(%u): %s\n", MSIX_LPI, strerror(errno));
		return 1;
	}
	printf("its: msixwait: attached LPI %u; ringing back the peer id at BAR2+%u%s\n",
	       MSIX_LPI, ECHO_OFF, secs ? "" : "; no time limit");
	fflush(stdout);
	for (;;) {
		uint64_t const timeout = 1000000000ull;
		uint64_t now;

		TimerTimeout(CLOCK_MONOTONIC, _NTO_TIMEOUT_INTR, NULL, &timeout, NULL);
		if (InterruptWait(0, NULL) == 0) {
			uint32_t const peer = __atomic_load_n((volatile uint32_t *)(bar2 + ECHO_OFF), __ATOMIC_ACQUIRE);
			got++;
			if (peer != 0u && peer <= 65535u) {
				__asm__ __volatile__("dsb st" ::: "memory");
				wr32(bar0 + REG_DOORBELL, peer << 16);
				echoes++;
			}
			InterruptUnmask((int)MSIX_LPI, id);
		} else if (errno != ETIMEDOUT) {
			fprintf(stderr, "its: InterruptWait: %s\n", strerror(errno));
			break;
		}
		now = now_ns();
		if ((got != printed && (printed < 3u || now - last_print >= 1000000000ull))) {
			printf("its: msixwait: %u LPIs, %u echoes\n", got, echoes);
			fflush(stdout);
			printed = got;
			last_print = now;
		}
		if (secs != 0u && now - start >= (uint64_t)secs * 1000000000ull) {
			break;
		}
	}
	InterruptDetach(id);
	printf("its: msixwait: done, %u LPIs, %u echoes\n", got, echoes);
	return 0;
}

int main(int argc, char **argv)
{
	if (argc >= 2 && strcmp(argv[1], "info") == 0) {
		return do_info();
	}
	if (argc >= 2 && strcmp(argv[1], "selftest") == 0) {
		return do_selftest(argc >= 3 ? (unsigned)strtoul(argv[2], NULL, 0) : 10u);
	}
	if (argc >= 2 && strcmp(argv[1], "msixcfg") == 0) {
		return do_msixcfg(argc >= 3 ? (unsigned)strtoul(argv[2], NULL, 0) : 1u);
	}
	if (argc >= 2 && strcmp(argv[1], "msixwait") == 0) {
		return do_msixwait(argc >= 3 ? (unsigned)strtoul(argv[2], NULL, 0) : 0u);
	}
	fprintf(stderr, "usage: qnx-its-probe info | selftest [N] | msixcfg [NVEC] | msixwait [SECS]\n");
	return 2;
}
