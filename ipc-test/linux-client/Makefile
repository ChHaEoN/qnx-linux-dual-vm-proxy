# Phase 3 (Orin, native-Linux TCP client). Builds natively on L4T with the
# system gcc -- no cross-compile, no QNX SDP env needed. Run directly:
#   make && ./linux-client [iters] [host] [warmup]

CC      := gcc
CFLAGS  := -std=gnu99 -Wall -Wextra -O2 -I../common
LDFLAGS :=

BIN := linux-client

.PHONY: all clean
all: $(BIN)

$(BIN): client.c ../common/frame.h ../common/frame_io.h
	$(CC) $(CFLAGS) -o $@ client.c $(LDFLAGS)

clean:
	rm -f $(BIN)
