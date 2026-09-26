# Phase 3b / A6 (2026-09-26): the guest-side clock-period control (clockctl.c).
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make
# The binary is QNX-derived and is never committed (.gitignore); ifs-clock.build stages it.

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2
LDFLAGS := -lsocket

BIN := qnx-clockctl

.PHONY: all clean
all: $(BIN)

$(BIN): clockctl.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ clockctl.c $(LDFLAGS)

clean:
	rm -f $(BIN)
