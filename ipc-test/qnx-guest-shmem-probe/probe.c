/* Phase 2.5 (cloud, ADR-002 RQ-2 guest-side shmem-viability spike, 2026-07-28
 * continuation session). GUEST-side counterpart to
 * ../qnx-host-shmem-probe/probe.c. Runs inside qnx-guest (a qvm guest, NOT
 * the qnx-qhv host) and attaches to the SAME named region
 * ("phase2-rq2-probe") via the raw-MMIO qvm/guest_shm.h factory-page
 * protocol -- a different API family from the host's libhyp.a (hyp_shm.h):
 * no library, no ChannelCreate/pulses, just mmap_device_memory() onto the
 * physical addresses the shmem vdev's `loc` directive declares, plus direct
 * register reads/writes per docs/findings.md (2026-07-28) and
 * docs/phase2-topology-decision.md RQ-2.
 *
 * Deliberately does NOT call InterruptAttach() or write
 * guest_shm_control.notify: the vdev's intr line's edge-vs-level and
 * masking semantics were not confirmed in the time available, and a wrong
 * guess risks an interrupt storm that hangs the guest under TCG with no
 * fast iteration loop to debug it against. factory->vector (the real
 * interrupt number the hypervisor assigned) is still read and logged so a
 * future session has the number it would need. See README.md "Status".
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
#include <sys/mman.h>
#include <qvm/guest_shm.h>

#define FACTORY_PADDR   0x1c0f0000ULL
#define FACTORY_LEN     4096u
#define REGION_NAME     "phase2-rq2-probe"
#define REGION_PAGES    1u   /* 1 * 4KB = 4096 bytes -- matches the host probe's REGION_SIZE */
#define HOST_PATTERN    "hyp-shm-host-ok"
#define GUEST_PATTERN   "hyp-shm-guest-ok"
#define GUEST_OFFSET    64u  /* byte offset into the data area for the write-back */

static const char *status_name(uint32_t s)
{
    switch (s) {
    case GSS_OK:              return "GSS_OK";
    case GSS_UNKNOWN_FAILURE: return "GSS_UNKNOWN_FAILURE";
    case GSS_NOMEM:           return "GSS_NOMEM";
    case GSS_CLIENT_MAX:      return "GSS_CLIENT_MAX";
    case GSS_ILLEGAL_NAME:    return "GSS_ILLEGAL_NAME";
    case GSS_NO_PERMISSION:   return "GSS_NO_PERMISSION";
    case GSS_DOES_NOT_EXIST:  return "GSS_DOES_NOT_EXIST";
    default:                  return "?";
    }
}

int main(void)
{
    volatile struct guest_shm_factory *factory =
        (volatile struct guest_shm_factory *)mmap_device_memory(
            NULL, FACTORY_LEN, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, FACTORY_PADDR);
    if (factory == MAP_FAILED) {
        fprintf(stderr, "gprobe: mmap_device_memory(factory@0x%llx): %s\n",
                (unsigned long long)FACTORY_PADDR, strerror(errno));
        return 1;
    }

    fprintf(stderr, "gprobe: factory mapped @paddr=0x%llx, signature=0x%llx (expect 0x%llx)\n",
            (unsigned long long)FACTORY_PADDR, (unsigned long long)factory->signature,
            (unsigned long long)GUEST_SHM_SIGNATURE);
    if (factory->signature != GUEST_SHM_SIGNATURE) {
        fprintf(stderr, "gprobe: FAIL -- signature mismatch; is 'vdev shmem loc/intr' really at this address?\n");
        return 1;
    }

    /* RUNTIME-SPIKE finding (2026-07-28, this session): a block memcpy()
     * into factory->name took a Bus error. The factory page is an
     * MMIO-trapped virtual-register file (unlike the shared DATA region,
     * which is ordinary guest-physical RAM and memcpy-safe below) -- qvm's
     * MMIO trap decoder evidently does not accept whatever wide/vector
     * store instruction the libc memcpy() picked for a 32-byte copy. Write
     * the name byte-by-byte instead, forcing single-byte volatile stores. */
    char namebuf[GUEST_SHM_MAX_NAME];
    memset(namebuf, 0, sizeof namebuf);
    strncpy(namebuf, REGION_NAME, sizeof namebuf - 1);
    for (unsigned i = 0; i < GUEST_SHM_MAX_NAME; i++) {
        factory->name[i] = namebuf[i];
    }
    factory->flags = GUEST_SHM_USR_RD | GUEST_SHM_USR_WR | GUEST_SHM_GRP_RD |
                      GUEST_SHM_GRP_WR | GUEST_SHM_OTH_RD | GUEST_SHM_OTH_WR;
    guest_shm_create(factory, REGION_PAGES);

    fprintf(stderr, "gprobe: guest_shm_create name='%s' pages=%u -> status=%s (%u)\n",
            REGION_NAME, REGION_PAGES, status_name(factory->status), factory->status);
    if (factory->status != GSS_OK) {
        fprintf(stderr, "gprobe: FAIL -- guest_shm_create did not return GSS_OK\n");
        return 1;
    }

    uint64_t ctrl_gpa = factory->shmem;
    uint32_t vector   = factory->vector;
    fprintf(stderr, "gprobe: region ready -- control-page GPA=0x%llx hypervisor-assigned-vector=%u\n",
            (unsigned long long)ctrl_gpa, vector);

    size_t span = (size_t)FACTORY_LEN + (size_t)REGION_PAGES * FACTORY_LEN; /* control page + data page(s) */
    volatile unsigned char *region =
        (volatile unsigned char *)mmap_device_memory(
            NULL, span, PROT_READ | PROT_WRITE | PROT_NOCACHE, 0, ctrl_gpa);
    if (region == MAP_FAILED) {
        fprintf(stderr, "gprobe: mmap_device_memory(control@0x%llx): %s\n",
                (unsigned long long)ctrl_gpa, strerror(errno));
        return 1;
    }

    volatile struct guest_shm_control *ctrl = (volatile struct guest_shm_control *)region;
    volatile unsigned char *data = region + FACTORY_LEN;
    fprintf(stderr, "gprobe: control page status=0x%08x idx=%u\n", ctrl->status, ctrl->idx);

    /* Byte-wise, not memcpy(), for the same reason as the factory->name
     * write above -- even though the docs describe the data area as
     * ordinary shared guest-physical RAM (unlike the factory page's
     * virtual registers), this session has exactly one real boot-cycle
     * budget left after the factory-page Bus error, so the data area gets
     * the same defensive treatment rather than re-risking a second crash
     * on an untested code path. */
    char host_seen[sizeof HOST_PATTERN];
    for (unsigned i = 0; i < sizeof host_seen; i++) {
        host_seen[i] = (char)data[i];
    }
    fprintf(stderr, "gprobe: read %u bytes at data+0: \"%s\"\n",
            (unsigned)sizeof host_seen, host_seen);
    if (memcmp(host_seen, HOST_PATTERN, sizeof host_seen) == 0) {
        fprintf(stderr, "gprobe: MATCH -- host pattern read back byte-exact\n");
    } else {
        fprintf(stderr, "gprobe: NO MATCH -- expected \"%s\"\n", HOST_PATTERN);
    }

    for (unsigned i = 0; i < sizeof GUEST_PATTERN; i++) {
        data[GUEST_OFFSET + i] = GUEST_PATTERN[i];
    }
    fprintf(stderr, "gprobe: wrote guest pattern \"%s\" at data+%u for the host to poll\n",
            GUEST_PATTERN, GUEST_OFFSET);

    fprintf(stderr, "gprobe: NOT using InterruptAttach()/control->notify this session (see "
            "header comment + README Status) -- pure-polling MMIO round trip only.\n");
    fprintf(stderr, "gprobe: done, exit=0\n");
    return 0;
}
