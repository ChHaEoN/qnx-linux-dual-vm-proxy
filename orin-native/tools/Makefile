# Phase 3b user-space tools. Compile-only from a Windows or Linux SDP host.
#
#   source ~/qnx800/qnxsdp-env.sh   (or run qnxsdp-env.bat first on Windows)
#   make
#
# The binaries go into the M1/M2/M1b/M3 images as /proc/boot entries; none is
# committed. bwait is M3's bounded-wait helper (m3-design.md §3.8.2).

CC      := qcc -Vgcc_ntoaarch64le
CFLAGS  := -Wall -Wextra -Werror -O2
TOOLS   := tcu-cat stamp smpcheck bwait

all: $(TOOLS)

%: %.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TOOLS)

.PHONY: all clean
