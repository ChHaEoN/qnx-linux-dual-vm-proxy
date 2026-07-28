# Phase 2 (cloud) — builds both QNX sides of the host<->guest virtio-console
# IPC pair (ADR-002). Phase 3 (Orin) adds qnx-server-net, the QNX-guest TCP
# echo endpoint for the br0/tap/virtio-net heterogeneous IPC leg. All three
# are qcc cross-builds for aarch64le; source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make
#
# linux-client/ is Phase 3 (Orin, gcc-built natively on L4T) and is
# intentionally NOT built here.

SIDES := qnx-server qnx-host-client qnx-server-net

.PHONY: all clean $(SIDES)
all: $(SIDES)

$(SIDES):
	$(MAKE) -C $@

clean:
	for d in $(SIDES); do $(MAKE) -C $$d clean; done
