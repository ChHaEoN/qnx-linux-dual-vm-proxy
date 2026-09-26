# Phase 3b / A6 (2026-09-26): qnx-ipcbench -- one guest call of each kind, timed
# (run-ipcbench.sh). qcc cross-build for aarch64le (SDP 8.0); source the SDP env first.
# The native control is built by run-ipcbench.sh with gcc (no QNX calls: msg/msgx drop out).

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2
LDFLAGS := -lsocket

BIN := qnx-ipcbench

.PHONY: all clean
all: $(BIN)

$(BIN): ipcbench.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ ipcbench.c $(LDFLAGS)

clean:
	rm -f $(BIN)
