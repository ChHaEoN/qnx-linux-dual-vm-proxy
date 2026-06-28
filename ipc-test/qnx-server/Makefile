# Phase 2 (cloud, QNX-guest virtio-console echo endpoint).
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common
LDFLAGS :=

BIN := qnx-echo-server

.PHONY: all clean
all: $(BIN)

$(BIN): server.c ../common/frame.h ../common/console_io.h
	$(CC) $(TARGET) $(CFLAGS) -o $@ server.c $(LDFLAGS)

clean:
	rm -f $(BIN)
