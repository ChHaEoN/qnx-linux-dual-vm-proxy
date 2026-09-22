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
#
# SHARED MEMORY (OD12, 2026-09-22), opt-in with IVSHMEM=/dev/shm/<name>: adds
# QEMU's ivshmem-plain PCI device, its BAR2 backed by that host file (1 MiB,
# created fresh and zeroed here, so no magic or counter survives from an earlier
# guest). It is PCI, not virtio-mmio, so the blk/net/rng slot order above is
# untouched. The guest needs an image whose monitor runs in shm mode
# (ifs-shm.bin); ifs-demo2.bin and ifs-udp.bin never look at the device.
#
# THE NOTIFIED VARIANT (OD12, 2026-09-22), opt-in with IVSHMEM_SERVER=<socket>
# (with IVSHMEM as well): ivshmem-doorbell instead of ivshmem-plain. Its memory
# and every peer's eventfds come from this project's ivshmem_server.py, which is
# started FIRST -- pinned to CORE_AUX, detached, and waited for until it has
# written its ready file, because QEMU's client-mode chardev connects at once
# and fails on a socket that is not there -- and which exits when QEMU (its peer
# 1) goes away. KICK_SOCK=<socket> adds a virtio console on that UNIX socket,
# the guest's interrupt-driven kick channel (devc-virtio in the image). Both
# devices come AFTER virtio-rng, so blk/net/rng keep their virtio-mmio slots and
# the console takes the next one (0xa003800, SPI 44). The guest needs ifs-kick.bin.
set -euo pipefail

IFS_BIN="${IFS_BIN:?set IFS_BIN to the QNX image (it must start the server the ladder probes)}"
DISK="${DISK:?set DISK to the guest disk image}"
TAP="${TAP:-tap-qnx}"
SMP="${SMP:-2}"
MEM="${MEM:-1G}"
MAC="${MAC:-52:54:00:11:11:11}"
QEMU="${QEMU:-qemu-system-aarch64}"
LOG="${LOG:-${HOME}/ladder/guest-console.log}"
IVSHMEM="${IVSHMEM:-}"
IVSHMEM_SERVER="${IVSHMEM_SERVER:-}"
KICK_SOCK="${KICK_SOCK:-}"
CORE_AUX="${CORE_AUX:-5}"

for f in "${IFS_BIN}" "${DISK}"; do
	[ -r "$f" ] || { echo "ERROR: unreadable: $f" >&2; exit 1; }
done
[ -r /dev/kvm ] || { echo "ERROR: /dev/kvm absent or unreadable -- this host cannot run the guest under KVM" >&2; exit 1; }
ip link show "${TAP}" >/dev/null 2>&1 || {
	echo "ERROR: ${TAP} does not exist. Run scripts/orin/setup-bridge-orin.sh first." >&2; exit 1; }
if ! ip link show "${TAP}" | grep -q 'master br0'; then
	echo "ERROR: ${TAP} is not enslaved to br0; arm D would not reach the guest." >&2; exit 1
fi
# By argv[0], never by a pgrep -f pattern, which can match the invoking shell's
# own command line. See m_pids_of in lib-measure.sh.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -r "$here/lib-measure.sh" ] || { echo "ERROR: lib-measure.sh not found beside $0" >&2; exit 1; }
. "$here/lib-measure.sh"
if [ -n "$(m_pids_of qemu-system-aarch64)" ]; then
	echo "ERROR: a qemu-system-aarch64 is already running. The measurement scripts" >&2
	echo "       pick the guest by process and cannot tell two apart. Stop it first." >&2
	exit 1
fi

# Everything that can refuse is checked BEFORE the ivshmem server starts, and the
# log directory exists before anything writes to it (FOUND BY CODE REVIEW: a
# refusal after the server started orphaned it, pinned and holding IVSHMEM).
mkdir -p "$(dirname "${LOG}")"
KICK_ARGS=()
if [ -n "${KICK_SOCK}" ]; then
	case "${KICK_SOCK}" in *,*) echo "ERROR: KICK_SOCK may not contain a comma" >&2; exit 1 ;; esac
	[ -e "${KICK_SOCK}" ] && { echo "ERROR: ${KICK_SOCK} exists -- remove the leftover first" >&2; exit 1; }
	KICK_ARGS=(-device virtio-serial-device
	           -chardev "socket,id=kick0,path=${KICK_SOCK},server=on,wait=off"
	           -device "virtconsole,chardev=kick0")
fi
SHM_ARGS=()
SRV_PID=""
if [ -n "${IVSHMEM}" ]; then
	case "${IVSHMEM}" in
		/dev/shm/*[!/]) ;;
		*) echo "ERROR: IVSHMEM='${IVSHMEM}' must be a file under /dev/shm" >&2; exit 1 ;;
	esac
	case "${IVSHMEM}" in *,*) echo "ERROR: IVSHMEM may not contain a comma (QEMU option syntax)" >&2; exit 1 ;; esac
	dd if=/dev/zero of="${IVSHMEM}" bs=1M count=1 status=none
	if [ -z "${IVSHMEM_SERVER}" ]; then
		SHM_ARGS=(-object "memory-backend-file,id=ivshm0,share=on,mem-path=${IVSHMEM},size=1M"
		          -device "ivshmem-plain,memdev=ivshm0")
	fi
fi
if [ -n "${IVSHMEM_SERVER}" ]; then
	[ -n "${IVSHMEM}" ] || { echo "ERROR: IVSHMEM_SERVER needs IVSHMEM, the file it serves" >&2; exit 1; }
	case "${IVSHMEM_SERVER}" in *,*) echo "ERROR: IVSHMEM_SERVER may not contain a comma" >&2; exit 1 ;; esac
	[ -e "${IVSHMEM_SERVER}" ] && { echo "ERROR: ${IVSHMEM_SERVER} exists -- a live server, or a leftover" >&2; exit 1; }
	rm -f "${IVSHMEM_SERVER}.ready"
	setsid nohup taskset -c "${CORE_AUX}" python3 "$here/ivshmem_server.py" --socket "${IVSHMEM_SERVER}" \
		--shm "${IVSHMEM}" --ready "${IVSHMEM_SERVER}.ready" --exit-with-peer 1 \
		> "$(dirname "${LOG}")/ivshmem-server.log" 2>&1 < /dev/null &
	for i in $(seq 1 50); do [ -s "${IVSHMEM_SERVER}.ready" ] && break; sleep 0.1; done
	[ -s "${IVSHMEM_SERVER}.ready" ] || { echo "ERROR: the ivshmem server did not come up; see $(dirname "${LOG}")/ivshmem-server.log" >&2; exit 1; }
	SRV_PID="$(cat "${IVSHMEM_SERVER}.ready")"
	# Until the guest answers, a failure must not leave the server behind.
	trap '[ -n "$SRV_PID" ] && kill "$SRV_PID" 2>/dev/null' EXIT
	SHM_ARGS=(-chardev "socket,id=ivsh0,path=${IVSHMEM_SERVER}"
	          -device "ivshmem-doorbell,chardev=ivsh0,vectors=1")
fi

echo "ifs    : ${IFS_BIN}  sha256 $(sha256sum "${IFS_BIN}" | cut -c1-16)..."
echo "disk   : ${DISK}  sha256 $(sha256sum "${DISK}" | cut -c1-16)...  (-snapshot: not written)"
echo "qemu   : $(${QEMU} --version | head -1)"
echo "console: ${LOG}"
if [ -n "${IVSHMEM_SERVER}" ]; then
	echo "ivshmem: ${IVSHMEM} (1 MiB, zeroed) via server ${IVSHMEM_SERVER} (pid $(cat "${IVSHMEM_SERVER}.ready"), core ${CORE_AUX}), -device ivshmem-doorbell"
elif [ -n "${IVSHMEM}" ]; then
	echo "ivshmem: ${IVSHMEM} (1 MiB, zeroed, -device ivshmem-plain)"
fi
[ -n "${KICK_SOCK}" ] && echo "kick   : virtio console on ${KICK_SOCK}"
# KVM halt polling decides whether a "sleeping" vCPU really sleeps; the VM takes
# its maximum when it is created, so the values in force are the ones now.
for p in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
	printf 'kvm    : %s=%s\n' "$p" "$(cat /sys/module/kvm/parameters/$p 2>/dev/null || echo NA)"
done

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
	${KICK_ARGS[@]+"${KICK_ARGS[@]}"} \
	${SHM_ARGS[@]+"${SHM_ARGS[@]}"} \
	-kernel "${IFS_BIN}" \
	-nographic > "${LOG}" 2>&1 &

qpid=$!
echo "qemu pid: ${qpid}"
echo "waiting for the guest to answer on 192.168.100.10 ..."
for i in $(seq 1 60); do
	if timeout 1 bash -c 'echo > /dev/tcp/192.168.100.10/7100' 2>/dev/null; then
		echo "guest up after ${i}s (monitor answering on :7100)"; trap - EXIT; exit 0
	fi
	kill -0 "${qpid}" 2>/dev/null || { echo "ERROR: qemu exited; see ${LOG}" >&2; tail -20 "${LOG}" >&2; exit 1; }
	sleep 1
done
echo "ERROR: guest did not answer on :7100 within 60s. Console tail:" >&2
tail -30 "${LOG}" >&2
exit 1
