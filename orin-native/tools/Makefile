# Phase 3b user-space tools. Compile-only from a Windows or Linux SDP host.
#
#   source ~/qnx800/qnxsdp-env.sh   (or run qnxsdp-env.bat first on Windows)
#   make
#
# The binaries go into the M1/M2/M1b/M3 images as /proc/boot entries; none is
# committed. bwait is M3's bounded-wait helper (m3-design.md §3.8.2).
# clkcmp and trcctl are the checklist 7b dry run's tools (m4-dryrun-design.md
# §5.1-5.2); orin-native/m4dry/build-m4dry-image.ps1 builds them with bwait.
# m4count is M4's on-target counter (m4-design.md §4.5); tcu-cat gained -f, -a,
# -T and -s for M4 (§5.1) and keeps its old behaviour without them.

CC      := qcc -Vgcc_ntoaarch64le
CFLAGS  := -Wall -Wextra -Werror -O2
TOOLS   := tcu-cat stamp smpcheck bwait clkcmp trcctl m4count

all: $(TOOLS)

%: %.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TOOLS)

.PHONY: all clean
