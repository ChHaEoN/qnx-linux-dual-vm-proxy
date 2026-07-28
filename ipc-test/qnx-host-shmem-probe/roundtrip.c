/* Phase 2.5 (cloud, ADR-002 RQ-2 host<->guest shmem round trip, 2026-07-28
 * continuation session). HOST-side half of the full round trip: attaches
 * (or, since it runs first, creates) "phase2-rq2-probe" exactly as probe.c
 * already proved works, writes the same host test pattern, then POLLS (see
 * ../qnx-guest-shmem-probe/README.md for why this is polling, not
 * interrupt/pulse-driven) for the guest's write-back at a fixed offset
 * before detaching. Pair this with ../qnx-guest-shmem-probe/probe.c running
 * in qnx-guest during the SAME boot -- run this one FIRST (before `qvm` is
 * launched) so the host pattern is already in place by the time the guest
 * attaches.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/neutrino.h>
#include <hyp_shm.h>

#define REGION_NAME       "phase2-rq2-probe"
#define REGION_SIZE       4096u
#define HOST_PATTERN      "hyp-shm-host-ok"
#define GUEST_OFFSET      64u
#define GUEST_PATTERN     "hyp-shm-guest-ok"
#define POLL_INTERVAL_SEC 2
#define POLL_TIMEOUT_SEC  180

int main(void)
{
    int chid = ChannelCreate(0);
    if (chid < 0) {
        fprintf(stderr, "roundtrip: ChannelCreate: %s\n", strerror(errno));
        return 1;
    }

    struct hyp_shm *h = hyp_shm_create(0);
    if (h == NULL) {
        fprintf(stderr, "roundtrip: hyp_shm_create: %s\n", strerror(errno));
        return 1;
    }

    errno = 0;
    int rc = hyp_shm_attach_ext(h, REGION_NAME, REGION_SIZE, chid, 10, 100,
                                 NULL, 0666, (gid_t)-1);
    fprintf(stderr, "roundtrip: hyp_shm_attach_ext rc=%d errno=%d\n", rc, errno);
    if (rc != 0) {
        return 1;
    }

    void *data = hyp_shm_data(h);
    unsigned size = hyp_shm_size(h);
    fprintf(stderr, "roundtrip: attached '%s' size=%u data=%p\n",
            hyp_shm_name(h), size, data);

    if (data == NULL || size < GUEST_OFFSET + sizeof(GUEST_PATTERN)) {
        fprintf(stderr, "roundtrip: region too small for the host+guest pattern layout\n");
        hyp_shm_detach(h);
        return 1;
    }

    memcpy(data, HOST_PATTERN, sizeof HOST_PATTERN);
    fprintf(stderr, "roundtrip: wrote host pattern \"%s\" at offset 0\n", HOST_PATTERN);
    hyp_shm_poke(h, HYP_SHM_POKE_ALL);

    fprintf(stderr, "roundtrip: polling offset %u for the guest's write-back, up to %ds ...\n",
            GUEST_OFFSET, POLL_TIMEOUT_SEC);

    char seen[sizeof GUEST_PATTERN];
    int elapsed = 0;
    int matched = 0;
    while (elapsed < POLL_TIMEOUT_SEC) {
        sleep(POLL_INTERVAL_SEC);
        elapsed += POLL_INTERVAL_SEC;
        memcpy(seen, (const char *)data + GUEST_OFFSET, sizeof seen);
        if (memcmp(seen, GUEST_PATTERN, sizeof seen) == 0) {
            matched = 1;
            break;
        }
    }

    if (matched) {
        fprintf(stderr, "roundtrip: SAW GUEST WRITE-BACK after %ds: \"%s\"\n", elapsed, seen);
    } else {
        seen[sizeof seen - 1] = '\0';
        fprintf(stderr, "roundtrip: TIMEOUT after %ds -- offset %u holds \"%s\" (not the expected guest pattern)\n",
                elapsed, GUEST_OFFSET, seen);
    }

    hyp_shm_detach(h);
    fprintf(stderr, "roundtrip: detached, exit=%d\n", matched ? 0 : 2);
    return matched ? 0 : 2;
}
