# Phase 3b (Orin, QNX guest under KVM): Safety-side cross-partition monitor.
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make
#
# OD12 (2026-09-22): the shm transport maps QEMU's ivshmem device, so the guest
# build links shm_map_qnx.c (which configures that one PCI function itself,
# through ECAM -- see its header for why not pci-server). monitor.c stays the
# one source the host also builds (build-monitor-native.sh links
# shm_map_posix.c instead).

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common
LDFLAGS := -lsocket

BIN := qnx-safety-monitor
SRCS := monitor.c ../common/shm_map_qnx.c ../common/frame.h ../common/frame_io.h ../common/shm_chan.h ../common/shm_map.h

# `make svc` builds the VLM service arm's monitor (OD13, 2026-09-23) under its
# OWN name. Use it, not plain `make`: every ifs-*.build stages $(BIN) by this
# exact path, so rebuilding $(BIN) from today's source would change what a
# later rebuild of ifs-udp, ifs-shm or ifs-kick embeds. ifs-svc.build stages
# qnx-safety-monitor-svc and names it qnx-safety-monitor inside the image.
SVC := qnx-safety-monitor-svc

# `make live` builds the liveness deadline's monitor (OD14, 2026-09-23) under
# its own name, for the same reason; ifs-live.build stages it. From OD14 on
# monitor.c has the deadline mode, so `make svc` no longer rebuilds the binary
# ifs-svc.bin embeds -- that image is pinned by its sha256, not by this target.
LIVE := qnx-safety-monitor-live

.PHONY: all svc live clean
all: $(BIN)
svc: $(SVC)
live: $(LIVE)

$(BIN): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(SVC): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(LIVE): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

clean:
	rm -f $(BIN) $(SVC) $(LIVE)
