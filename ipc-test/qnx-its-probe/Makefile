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
# `make twovec` (2026-09-29): the build with msixcfg NVEC, under its own name, so
# the binary ifs-its/bell/paths.bin embed is not rebuilt; ifs-unmask-a.build and
# ifs-unmask-b.build both stage it (one binary for the pair, by design).
TWOVEC := qnx-its-probe-2v

.PHONY: all twovec clean
all: $(BIN)
twovec: $(TWOVEC)

$(BIN): its_probe.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ its_probe.c

$(TWOVEC): its_probe.c
	$(CC) $(TARGET) $(CFLAGS) -o $@ its_probe.c

clean:
	rm -f $(BIN) $(TWOVEC)
