# Phase 3 (Orin, QNX-guest TCP echo endpoint over br0/virtio-net).
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common
LDFLAGS := -lsocket

BIN := qnx-echo-server-net
# `make sweep` builds the frame-size sweep's endpoint (2026-09-26, run-sweep.sh)
# from its own source under its own name: server.c and the binary every
# published image stages are not touched.
SWEEP := qnx-echo-server-sweep

.PHONY: all sweep clean
all: $(BIN)
sweep: $(SWEEP)

$(BIN): server.c ../common/frame.h ../common/frame_io.h
	$(CC) $(TARGET) $(CFLAGS) -o $@ server.c $(LDFLAGS)

$(SWEEP): sweep.c ../common/frame.h
	$(CC) $(TARGET) $(CFLAGS) -o $@ sweep.c $(LDFLAGS)

clean:
	rm -f $(BIN) $(SWEEP)
