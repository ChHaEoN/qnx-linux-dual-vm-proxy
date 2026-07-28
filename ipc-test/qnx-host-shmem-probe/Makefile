# Phase 2.5 (cloud, RQ-2 host<->guest shmem-viability spike).
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2
LDFLAGS := -lhyp

BIN := hyp-shm-probe

.PHONY: all clean
all: $(BIN)

$(BIN): probe.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ probe.c $(LDFLAGS)

clean:
	rm -f $(BIN)
