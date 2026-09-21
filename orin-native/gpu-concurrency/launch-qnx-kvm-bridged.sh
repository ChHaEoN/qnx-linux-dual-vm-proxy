#!/usr/bin/env bash
# launch-qnx-kvm-bridged.sh -- boot the QNX guest under KVM onto br0/tap-qnx.
#
# WHY THIS EXISTS. run-ladder.sh launches nothing: it pgreps for a running
# qemu-system-aarch64 and exits if there is none. On the Orin the guest was
# started by a script that lives only on that board, so a second host had
# nothing to start it with. This is that script, written to be host-agnostic.
#
# NOT SLIRP. The 2026-09-20 two-host boot comparison used "-netdev user" on
# both hosts, deliberately, so the device set would not depend on a local
# bridge. The ladder cannot do that: arm B enslaves a veth to br0 and arm D
# must reach the guest through tap-qnx on that same bridge. SLIRP has no bridge
# and no tap, so a ladder run over SLIRP would be measuring a different path
# from the one the published Orin figure measured.
#
# DEVICE ORDER IS LOAD-BEARING: blk, then net, then rng. QEMU assigns
# virtio-mmio slots in command-line order and the image's startup.sh binds
# absolute addresses to them. Reordering these does not fail loudly -- it
# produces a guest that boots and then cannot see its disk or its network.
#
# WHICH IMAGE. It must be one whose startup-qemu-virt is the rebuild
# (-fno-auto-inc-dec); the startup QNX ships stops after 17 bytes of serial
# under KVM. It must also actually START the server the ladder probes: several
# images in this tree stage a binary without running it, and their startup
# script is visibly shorter. Pass IFS= explicitly; there is no safe default.
set -euo pipefail

IFS_BIN="${IFS_BIN:?set IFS_BIN to the QNX image (it must start the server the ladder probes)}"
DISK="${DISK:?set DISK to the guest disk image}"
TAP="${TAP:-tap-qnx}"
SMP="${SMP:-2}"
MEM="${MEM:-1G}"
MAC="${MAC:-52:54:00:11:11:11}"
QEMU="${QEMU:-qemu-system-aarch64}"
LOG="${LOG:-${HOME}/ladder/guest-console.log}"

for f in "${IFS_BIN}" "${DISK}"; do
	[ -r "$f" ] || { echo "ERROR: unreadable: $f" >&2; exit 1; }
done
[ -r /dev/kvm ] || { echo "ERROR: /dev/kvm absent or unreadable -- this host cannot run the guest under KVM" >&2; exit 1; }
ip link show "${TAP}" >/dev/null 2>&1 || {
	echo "ERROR: ${TAP} does not exist. Run scripts/orin/setup-bridge-orin.sh first." >&2; exit 1; }
if ! ip link show "${TAP}" | grep -q 'master br0'; then
	echo "ERROR: ${TAP} is not enslaved to br0; arm D would not reach the guest." >&2; exit 1
fi
if pgrep -f "[q]emu-system-aarch64" >/dev/null 2>&1; then
	echo "ERROR: a qemu-system-aarch64 is already running. run-ladder.sh picks the" >&2
	echo "       guest by pgrep and cannot tell two apart. Stop it first." >&2
	exit 1
fi

mkdir -p "$(dirname "${LOG}")"
echo "ifs    : ${IFS_BIN}  sha256 $(sha256sum "${IFS_BIN}" | cut -c1-16)..."
echo "disk   : ${DISK}  sha256 $(sha256sum "${DISK}" | cut -c1-16)...  (-snapshot: not written)"
echo "qemu   : $(${QEMU} --version | head -1)"
echo "console: ${LOG}"

# -snapshot ALWAYS: the guest disk is an input to a measurement, and a run that
# mutates it makes the next run a different experiment.
nohup "${QEMU}" \
	-machine virt,gic-version=3 -cpu host -enable-kvm \
	-smp "${SMP}" -m "${MEM}" \
	-drive file="${DISK}",if=none,id=drv0,format=raw \
	-device virtio-blk-device,drive=drv0 \
	-snapshot \
	-netdev tap,id=n0,ifname="${TAP}",script=no,downscript=no \
	-device virtio-net-device,netdev=n0,mac="${MAC}" \
	-object rng-random,filename=/dev/urandom,id=rng0 \
	-device virtio-rng-device,rng=rng0 \
	-kernel "${IFS_BIN}" \
	-nographic > "${LOG}" 2>&1 &

qpid=$!
echo "qemu pid: ${qpid}"
echo "waiting for the guest to answer on 192.168.100.10 ..."
for i in $(seq 1 60); do
	if timeout 1 bash -c 'echo > /dev/tcp/192.168.100.10/7100' 2>/dev/null; then
		echo "guest up after ${i}s (monitor answering on :7100)"; exit 0
	fi
	kill -0 "${qpid}" 2>/dev/null || { echo "ERROR: qemu exited; see ${LOG}" >&2; tail -20 "${LOG}" >&2; exit 1; }
	sleep 1
done
echo "ERROR: guest did not answer on :7100 within 60s. Console tail:" >&2
tail -30 "${LOG}" >&2
exit 1
