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

.PHONY: all clean
all: $(BIN)

$(BIN): monitor.c ../common/shm_map_qnx.c ../common/frame.h ../common/frame_io.h ../common/shm_chan.h ../common/shm_map.h
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

clean:
	rm -f $(BIN)
