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

# `make stamp` builds guest-side timestamps' monitor (OD15, 2026-09-23) under its
# own name, for the same reason; ifs-stamp.build stages it.
STAMP := qnx-safety-monitor-stamp

# `make bell` builds the monitor for the doorbell into the guest (2026-09-29)
# under its own name, for the same reason; ifs-bell.build stages it. It is the
# first build with shm_map_qnx.c's "msix" kick channel.
BELL := qnx-safety-monitor-bell

# `make unmask` builds the monitor for where the doorbell's LPI is unmasked
# (2026-09-29) under its own name, for the same reason; ifs-unmask-a.build and
# ifs-unmask-b.build both stage it, by design: the two images must differ only in
# startup-script, so rebuild and accept them together. It is the first build with
# the "msix1" and ":defer" kicks.
UNMASK := qnx-safety-monitor-unmask

.PHONY: all svc live stamp bell unmask clean
all: $(BIN)
svc: $(SVC)
live: $(LIVE)
stamp: $(STAMP)
bell: $(BELL)
unmask: $(UNMASK)

$(BIN): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(SVC): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(LIVE): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(STAMP): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(BELL): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(UNMASK): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

clean:
	rm -f $(BIN) $(SVC) $(LIVE) $(STAMP) $(BELL) $(UNMASK)
