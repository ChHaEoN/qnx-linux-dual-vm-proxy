# Phase 3b (Orin, QNX guest under KVM): Safety-side cross-partition monitor.
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common
LDFLAGS := -lsocket

BIN := qnx-safety-monitor

.PHONY: all clean
all: $(BIN)

$(BIN): monitor.c ../common/frame.h ../common/frame_io.h
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c $(LDFLAGS)

clean:
	rm -f $(BIN)
