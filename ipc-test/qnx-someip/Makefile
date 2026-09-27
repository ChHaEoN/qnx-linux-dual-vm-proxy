# Phase 3b / A6 (2026-09-27, OD12): the monitor's judgement as a SOME/IP method (someip.c).
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make
# someip.c #includes ../qnx-safety-monitor/monitor.c, so the guest build links the same
# shm_map_qnx.c the monitor links; a native build links ../common/shm_map_posix.c instead.
# The binary is QNX-derived and is never committed (.gitignore); ifs-someip.build stages it.

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common
LDFLAGS := -lsocket

BIN := qnx-someip-monitor
SRCS := someip.c ../qnx-safety-monitor/monitor.c ../common/shm_map_qnx.c ../common/frame.h ../common/frame_io.h \
	../common/shm_chan.h ../common/shm_map.h

.PHONY: all clean
all: $(BIN)

$(BIN): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ someip.c ../common/shm_map_qnx.c $(LDFLAGS)

clean:
	rm -f $(BIN)
