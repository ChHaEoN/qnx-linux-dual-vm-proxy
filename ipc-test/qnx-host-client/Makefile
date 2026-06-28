# Phase 2 (cloud, QNX-host -> QNX-guest over qvm virtio-console).
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common
LDFLAGS :=

BIN := qnx-host-client

.PHONY: all clean
all: $(BIN)

$(BIN): client.c ../common/frame.h ../common/console_io.h
	$(CC) $(TARGET) $(CFLAGS) -o $@ client.c $(LDFLAGS)

clean:
	rm -f $(BIN)
