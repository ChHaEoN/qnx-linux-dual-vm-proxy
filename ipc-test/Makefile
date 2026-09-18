# Phase 2 (cloud) — builds both QNX sides of the host<->guest virtio-console
# IPC pair (ADR-002). Phase 3 (Orin) adds qnx-server-net, the QNX-guest TCP
# echo endpoint for the br0/tap/virtio-net heterogeneous IPC leg. All three
# are qcc cross-builds for aarch64le; source the SDP env first:
#   Windows: qnxsdp-env.bat   |   Linux/macOS: . qnxsdp-env.sh
# then: make
#
# Phase 3b (Orin, QNX guest under KVM) adds qnx-safety-monitor, the Safety end
# of the cross-partition service: it interprets a claim from the Compute side
# and answers with a verdict, rather than echoing. It is additive -- the echo
# endpoint stays, because the KVM-concurrency liveness probe talks to it.
#
# linux-client/ is Phase 3 (Orin, gcc-built natively on L4T) and is
# intentionally NOT built here. The Phase-3b Compute side
# (orin-native/gpu-concurrency/ and the TensorRT client) is likewise built on
# the board, not here: it needs CUDA and TensorRT headers that exist only there.

SIDES := qnx-server qnx-host-client qnx-server-net qnx-safety-monitor

.PHONY: all clean $(SIDES)
all: $(SIDES)

$(SIDES):
	$(MAKE) -C $@

clean:
	for d in $(SIDES); do $(MAKE) -C $$d clean; done
