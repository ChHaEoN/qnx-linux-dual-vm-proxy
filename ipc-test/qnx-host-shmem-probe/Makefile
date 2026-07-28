# Phase 2.5 (cloud, RQ-2 host<->guest shmem-viability spike).
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2
LDFLAGS := -lhyp

BINS := hyp-shm-probe hyp-shm-roundtrip

.PHONY: all clean
all: $(BINS)

hyp-shm-probe: probe.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ probe.c $(LDFLAGS)

# hyp-shm-roundtrip continues the guest-side spike (2026-07-28 follow-up):
# same create/attach/write as probe.c, but polls for a guest write-back
# instead of detaching immediately. See roundtrip.c and
# ../qnx-guest-shmem-probe/README.md.
hyp-shm-roundtrip: roundtrip.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ roundtrip.c $(LDFLAGS)

clean:
	rm -f $(BINS)
