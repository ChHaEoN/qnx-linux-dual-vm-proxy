# A6 (2026-09-29): the ivshmem doorbell into the guest -- the guest-side ITS and
# MSI-X probe (its_probe.c). qcc cross-build for aarch64le (SDP 8.0). Source the
# SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make
# The binary is QNX-derived and is never committed (.gitignore); ifs-its.build stages it.

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2

BIN := qnx-its-probe

.PHONY: all clean
all: $(BIN)

$(BIN): its_probe.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ its_probe.c

clean:
	rm -f $(BIN)
