# Phase 3b user-space tools. Compile-only from a Windows or Linux SDP host.
#
#   source ~/qnx800/qnxsdp-env.sh   (or run qnxsdp-env.bat first on Windows)
#   make
#
# Both binaries go into the M1 image as /proc/boot entries; neither is committed.

CC      := qcc -Vgcc_ntoaarch64le
CFLAGS  := -Wall -Wextra -Werror -O2
TOOLS   := tcu-cat stamp

all: $(TOOLS)

%: %.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TOOLS)

.PHONY: all clean
