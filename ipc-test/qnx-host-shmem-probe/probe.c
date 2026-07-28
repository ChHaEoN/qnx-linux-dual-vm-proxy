/* Phase 2.5 (cloud, ADR-002 RQ-2 host<->guest shmem-viability spike, 2026-07-28).
 *
 * Host-ONLY smoke test. Does NOT touch qvm/g2.conf or the qnx-guest image --
 * this checks a narrower, prerequisite question first: can an ordinary QNX
 * HOST userspace process (qnx-qhv running this as a plain program, not
 * itself a qvm guest) call the libhyp.a Virtualization API (hyp_shm.h) to
 * create/attach a named shared-memory region and get a mapped pointer at
 * all? See docs/findings.md (2026-07-28) and
 * docs/phase2-topology-decision.md (RQ-2) for what this result resolves.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <hyp_shm.h>

#define REGION_NAME "phase2-rq2-probe"
#define REGION_SIZE 4096u

int main(void)
{
    int chid = ChannelCreate(0);
    if (chid < 0) {
        fprintf(stderr, "probe: ChannelCreate: %s\n", strerror(errno));
        return 1;
    }

    struct hyp_shm *h = hyp_shm_create(0);
    if (h == NULL) {
        fprintf(stderr, "probe: hyp_shm_create: %s\n", strerror(errno));
        return 1;
    }

    errno = 0;
    int rc = hyp_shm_attach_ext(h, REGION_NAME, REGION_SIZE, chid, 10, 100,
                                 NULL, 0666, (gid_t)-1);
    fprintf(stderr, "probe: hyp_shm_attach_ext rc=%d errno=%d (%s)\n",
            rc, errno, (rc != 0) ? strerror(errno) : "n/a");
    if (rc != 0) {
        return 1;
    }

    void *data = hyp_shm_data(h);
    unsigned size = hyp_shm_size(h);
    unsigned idx = hyp_shm_idx(h);
    fprintf(stderr, "probe: attached '%s' idx=%u size=%u data=%p\n",
            hyp_shm_name(h), idx, size, data);

    if (data != NULL && size >= 16) {
        memcpy(data, "hyp-shm-host-ok", 16);
        fprintf(stderr, "probe: wrote test pattern to shared region\n");
    }

    int poke_rc = hyp_shm_poke(h, HYP_SHM_POKE_ALL);
    fprintf(stderr, "probe: hyp_shm_poke rc=%d errno=%d\n", poke_rc, errno);

    hyp_shm_detach(h);
    fprintf(stderr, "probe: detached cleanly\n");
    return 0;
}
