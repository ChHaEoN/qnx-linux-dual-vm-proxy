# Phase 3b (Orin, QNX guest under KVM): Safety-side cross-partition monitor.
# KVM here boots our startup-qemu-virt; this is not a QNX-supported
# configuration, and no timing claim attaches to the boot.
# qcc cross-build for aarch64le (SDP 8.0). Source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make
#
# OD12 (2026-09-22): the shm transport maps QEMU's ivshmem device, so the guest
# build links shm_map_qnx.c (which configures that one PCI function itself,
# through ECAM -- see its header for why not pci-server). monitor.c stays the
# one source the host also builds (build-monitor-native.sh links
# shm_map_posix.c instead).

CC      := qcc
TARGET  := -Vgcc_ntoaarch64le
CFLAGS  := -std=gnu99 -Wall -Wextra -Wformat=2 -O2 -I../common
LDFLAGS := -lsocket

BIN := qnx-safety-monitor
SRCS := monitor.c ../common/shm_map_qnx.c ../common/frame.h ../common/frame_io.h ../common/shm_chan.h ../common/shm_map.h

# `make svc` builds the VLM service arm's monitor (OD13, 2026-09-23) under its
# OWN name. Use it, not plain `make`: every ifs-*.build stages $(BIN) by this
# exact path, so rebuilding $(BIN) from today's source would change what a
# later rebuild of ifs-udp, ifs-shm or ifs-kick embeds. ifs-svc.build stages
# qnx-safety-monitor-svc and names it qnx-safety-monitor inside the image.
SVC := qnx-safety-monitor-svc

# `make live` builds the liveness deadline's monitor (OD14, 2026-09-23) under
# its own name, for the same reason; ifs-live.build stages it. From OD14 on
# monitor.c has the deadline mode, so `make svc` no longer rebuilds the binary
# ifs-svc.bin embeds -- that image is pinned by its sha256, not by this target.
LIVE := qnx-safety-monitor-live

# `make stamp` builds guest-side timestamps' monitor (OD15, 2026-09-23) under its
# own name, for the same reason; ifs-stamp.build stages it.
STAMP := qnx-safety-monitor-stamp

# `make bell` builds the monitor for the doorbell into the guest (2026-09-29)
# under its own name, for the same reason; ifs-bell.build stages it. It is the
# first build with shm_map_qnx.c's "msix" kick channel.
BELL := qnx-safety-monitor-bell

# `make unmask` builds the monitor for where the doorbell's LPI is unmasked
# (2026-09-29) under its own name, for the same reason; ifs-unmask-a.build and
# ifs-unmask-b.build both stage it, by design: the two images must differ only in
# startup-script, so rebuild and accept them together. It is the first build with
# the "msix1" and ":defer" kicks.
UNMASK := qnx-safety-monitor-unmask

# `make vss` builds the kind 4 (vss) monitor (sdv Phase 2; the kind 4 wire
# specification, section 11) under its own name, for the same reason as above.
# It is the one build with MONITOR_EXT_KINDS defined, and that -D lives in its
# recipe alone: never put it in CFLAGS, or every target above would build with
# the switch. It includes the generated contract (vss_contract.h,
# vss_profiles.h) from VSS_GEN, by default the in-tree output root that
# sdv/vss/generate.py writes; both headers are prerequisites, so a new contract
# or profile table rebuilds the binary. -ffp-contract=off (Phase 2 design
# decision e): gcc ignores #pragma STDC FP_CONTRACT and in GNU mode fuses
# multiply-adds where the target has them, so without it the guest's rule-26
# arithmetic could round differently from the native build the tests compare
# with the Python reference. It goes in this recipe only, never in CFLAGS.
VSS := qnx-safety-monitor-vss
VSS_GEN ?= ../../sdv-out/gen

# `make vss-carla` builds the kind 4 monitor of a generation that compiles
# profile 3, the CARLA ego (sdv Phase 7, WP4a), under its own name, for the same
# reason as above; ifs-vss-carla.build stages it. Its recipe is the vss recipe
# with the flags exactly as they are there, the contract from VSS_CARLA_GEN. The
# name is not qnx-safety-monitor-vss-carla: tests/test_ifs_vss.py refuses
# "qnx-safety-monitor-vss" in every build file but ifs-vss.build, and that name
# holds it. Before any compiler runs, the recipe's first line stops the build
# when vss_profiles.h has no X() row for profile 3: a guest built without it
# answers every profile-3 claim with reason 8. It reads the X-macro's rows (a
# word "X(3u," as sdv/vss/generate.py writes them), not VSS_PROFILE_IDS, by
# make's own $(file) (GNU make 4.2 or later), so no shell tool is involved.
# The second line stops it when monitor.c's directory or ../common holds a
# vss_contract.h or vss_profiles.h that is not VSS_CARLA_GEN's own: monitor.c
# includes the contract with quotes, so the compiler looks there before
# -I$(VSS_CARLA_GEN) and would compile that copy, not the table the first line
# read (`make vss` has the same include order, kept as it was). `make clean`
# does not remove the binary: the Phase 7 spec (7.1) keeps every other recipe,
# clean's included, as it was.
VSS_CARLA := qnx-safety-monitor-carla
VSS_CARLA_GEN ?= ../../sdv-out/gen
VSS_CARLA_ROW3 := X(3u,
VSS_CARLA_NO_ROW3 = $(VSS_CARLA_GEN)/vss_profiles.h holds no profile 3: generate a \
	contract that compiles it with sdv/vss/generate.py (sdv/vss/README.md), or point VSS_CARLA_GEN at one
VSS_CARLA_MISSING = is missing: generate the kind 4 contract with sdv/vss/generate.py \
	(sdv/vss/README.md), or point VSS_CARLA_GEN at its output
VSS_CARLA_STRAY = $(filter-out $(realpath $(VSS_CARLA_GEN)/vss_contract.h $(VSS_CARLA_GEN)/vss_profiles.h), \
	$(realpath vss_contract.h vss_profiles.h ../common/vss_contract.h ../common/vss_profiles.h))
VSS_CARLA_SHADOW = $(VSS_CARLA_STRAY) would be compiled instead of the contract in $(VSS_CARLA_GEN) \
	(a quoted include looks in monitor.c's directory and ../common first): remove it

# `make ctl` builds the kind 2 (ctl) monitor (sdv Phase 8, WP1b; the Phase 8
# specification, 2.1 and section 3 item 4) under its own name,
# qnx-safety-monitor-ctl, for the same reason as above; ifs-ctl.build (WP5)
# stages it. Its recipe is the vss recipe with MONITOR_EXT_KINDS=0x14 (kinds 2
# and 4) and the contract from CTL_GEN: vss_contract.h and vss_profiles.h
# (kind 4) and vss_ctl.h (kind 2), all three written by sdv/vss/generate.py.
# The image it is for judges kinds 2 and 4 with kind 4's profile 4 (the
# planning-sim vehicle), so before any compiler runs the recipe stops when
# vss_profiles.h holds no X() row for profile 4 or vss_ctl.h none for kind 2's
# profile 1 (the words "X(4u," and "X(1u," as the generator writes its tables,
# read by $(file)), and when a copy of any of the three beside monitor.c or in
# ../common would be compiled instead of CTL_GEN's (vss-carla's guard). A
# missing header stops it as the makefile is read, naming CTL_GEN, whenever the
# command line names ctl or its binary; no header rule is defined for CTL_GEN,
# so none can override vss's or vss-carla's. `make clean` does not remove the
# binary: the Phase 8 specification keeps every other recipe, clean's included,
# as it was.
CTL := qnx-safety-monitor-ctl
CTL_GEN ?= ../../sdv-out/gen
CTL_HEADERS := vss_contract.h vss_profiles.h vss_ctl.h
CTL_ROW4 := X(4u,
CTL_ROW1 := X(1u,
CTL_NO_ROW4 = $(CTL_GEN)/vss_profiles.h holds no kind 4 profile 4: generate a \
	contract that compiles it with sdv/vss/generate.py (sdv/vss/README.md), or point CTL_GEN at one
CTL_NO_ROW1 = $(CTL_GEN)/vss_ctl.h holds no kind 2 profile 1: generate a \
	contract that compiles it with sdv/vss/generate.py (sdv/vss/README.md), or point CTL_GEN at one
CTL_MISSING = is missing: generate the kind 2 and kind 4 contract with sdv/vss/generate.py \
	(sdv/vss/README.md), or point CTL_GEN at its output
CTL_STRAY = $(filter-out $(realpath $(addprefix $(CTL_GEN)/,$(CTL_HEADERS))), \
	$(realpath $(CTL_HEADERS) $(addprefix ../common/,$(CTL_HEADERS))))
CTL_SHADOW = $(CTL_STRAY) would be compiled instead of the contract in $(CTL_GEN) \
	(a quoted include looks in monitor.c's directory and ../common first): remove it

.PHONY: all svc live stamp bell unmask vss vss-carla ctl clean
all: $(BIN)
svc: $(SVC)
live: $(LIVE)
stamp: $(STAMP)
bell: $(BELL)
unmask: $(UNMASK)
vss: $(VSS)
vss-carla: $(VSS_CARLA)
ctl: $(CTL)

$(BIN): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(SVC): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(LIVE): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(STAMP): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(BELL): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(UNMASK): $(SRCS)
	$(CC) $(TARGET) $(CFLAGS) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

$(VSS): $(SRCS) $(VSS_GEN)/vss_contract.h $(VSS_GEN)/vss_profiles.h
	$(CC) $(TARGET) $(CFLAGS) -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I$(VSS_GEN) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

# The generated contract is not built here: a missing header stops the build
# and names its generator, instead of a compiler error about an include. The
# recipe looks for the file itself, so `make -B vss`, which remakes every
# target, passes over headers that exist and plans only the vss line.
$(VSS_GEN)/vss_contract.h $(VSS_GEN)/vss_profiles.h:
	$(if $(wildcard $@),,$(error $@ is missing: generate the kind 4 contract with sdv/vss/generate.py (sdv/vss/README.md), or point VSS_GEN at its output))

$(VSS_CARLA): $(SRCS) $(VSS_CARLA_GEN)/vss_contract.h $(VSS_CARLA_GEN)/vss_profiles.h
	$(if $(filter $(VSS_CARLA_ROW3),$(file <$(VSS_CARLA_GEN)/vss_profiles.h)),,$(error $(VSS_CARLA_NO_ROW3)))
	$(if $(VSS_CARLA_STRAY),$(error $(VSS_CARLA_SHADOW)))
	$(CC) $(TARGET) $(CFLAGS) -ffp-contract=off -DMONITOR_EXT_KINDS=0x10 -I$(VSS_CARLA_GEN) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

# The headers' rule above serves vss-carla too while VSS_CARLA_GEN is VSS_GEN
# (both default to the in-tree output root); a second rule for the same files
# would override it. Pointed elsewhere, vss-carla's headers get their own. In
# the default case, when the command line names vss-carla or its binary, the
# headers are checked as the makefile is read, so a missing one names
# VSS_CARLA_GEN, the knob vss-carla reads; vss's message, naming VSS_GEN, stays.
ifneq ($(VSS_CARLA_GEN),$(VSS_GEN))
$(VSS_CARLA_GEN)/vss_contract.h $(VSS_CARLA_GEN)/vss_profiles.h:
	$(if $(wildcard $@),,$(error $@ $(VSS_CARLA_MISSING)))
else ifneq ($(filter vss-carla $(VSS_CARLA),$(MAKECMDGOALS)),)
$(foreach h,vss_contract.h vss_profiles.h,$(if $(wildcard $(VSS_CARLA_GEN)/$(h)),,$(error $(VSS_CARLA_GEN)/$(h) $(VSS_CARLA_MISSING))))
endif

$(CTL): $(SRCS) $(CTL_GEN)/vss_contract.h $(CTL_GEN)/vss_profiles.h $(CTL_GEN)/vss_ctl.h
	$(if $(filter $(CTL_ROW4),$(file <$(CTL_GEN)/vss_profiles.h)),,$(error $(CTL_NO_ROW4)))
	$(if $(filter $(CTL_ROW1),$(file <$(CTL_GEN)/vss_ctl.h)),,$(error $(CTL_NO_ROW1)))
	$(if $(CTL_STRAY),$(error $(CTL_SHADOW)))
	$(CC) $(TARGET) $(CFLAGS) -ffp-contract=off -DMONITOR_EXT_KINDS=0x14 -I$(CTL_GEN) -o $@ monitor.c ../common/shm_map_qnx.c $(LDFLAGS)

# ctl's three headers are checked as the makefile is read whenever the command
# line names ctl or its binary, so a missing one names CTL_GEN wherever it
# points; vss_ctl.h has no rule, and vss's or vss-carla's rule for the other
# two is never redefined here.
ifneq ($(filter ctl $(CTL),$(MAKECMDGOALS)),)
$(foreach h,$(CTL_HEADERS),$(if $(wildcard $(CTL_GEN)/$(h)),,$(error $(CTL_GEN)/$(h) $(CTL_MISSING))))
endif

clean:
	rm -f $(BIN) $(SVC) $(LIVE) $(STAMP) $(BELL) $(UNMASK) $(VSS)
