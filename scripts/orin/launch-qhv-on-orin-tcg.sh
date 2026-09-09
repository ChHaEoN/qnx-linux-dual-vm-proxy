#!/usr/bin/env bash
#
# Phase 4
# launch-qhv-on-orin-tcg.sh — boot the QHV host (and its auto-started QNX
#                             guest) under QEMU-TCG on Orin Nano L4T, and
#                             time launch -> guest banner.
#
# WHY THIS EXISTS
# ---------------
# The QHV leg is the only part of this project with a real EL2/EL1 partition
# boundary -- the thing the DRIVE OS proxy is actually about -- and until now
# it had only ever run on the local Windows build host. Its QEMU invocation
# turns out to have no host-specific content at all: the pty pair, the vdevs
# and the guest all live *inside* the emulated QNX world, and the only host
# inputs are two image files. Moving it here therefore costs a file copy and
# this script, and buys the twin diff its first clean host-only comparison on
# the *hypervisor* topology instead of on plain boot time alone --
#
#   same ifs.bin, same disk-qemu, same qvm config, same guest, same
#   transport, same accelerator; only the host CPU differs.
#
# Per docs/digital-twin-design.md §1 the twin's invariant set had collapsed
# to {wire protocol, harness/CSV shape, QEMU machine shape}; this restores
# the images and the topology to it.
#
# WHY TCG, AND WHY THAT IS *NOT* THE USUAL REASON
# -----------------------------------------------
# QHV needs EL2 for its guest, i.e. nested virtualisation, which ARM KVM does
# not provide on A78AE -- so TCG here is a hard architectural requirement, not
# a workaround. That matters for how the resulting number is read: the Windows
# side is TCG for the same reason, so for once TCG-on-both is *genuine
# symmetry* rather than the incidental blockage the plain qnx-safety-vm leg
# suffers from (docs/orin-port.md's GICv3/KVM_EXIT_ARM_NISV risk-register row).
# Do not describe this leg as "TCG because KVM is broken" -- it is not.
#
# No sudo, no br0, no tap-qnx: this leg does no host networking whatsoever.
# That is a real difference from launch-qnx-on-orin-tcg.sh, which needs all
# three.
#
# RUN ON: Orin Nano L4T, from a directory containing
#   ifs.bin      <- qhv/host/output/ifs.bin    from the Windows build host
#   disk-qemu    <- qhv/host/output/disk-qemu  from the Windows build host
#   SHA256SUMS   <- twin-sync invariant; verify before running, do NOT skip
#
# USAGE
#   ./launch-qhv-on-orin-tcg.sh [runs] [capture_seconds] [log_prefix]
#     runs             how many boots to time (default 1; use 5 to match the
#                      n=5 methodology in docs/digital-twin-design.md §5)
#     capture_seconds  per-run ceiling before giving up (default 240)
#     log_prefix       serial logs go to <prefix>N.log (default qhv-orin-boot)
#
# The Windows counterpart is scripts/launch-qhv-tcg.ps1 -StopOnGuestBanner.
# The QEMU argument list below is duplicated there ON PURPOSE (two host OSes,
# no shared config format) -- if you change one, change the other, or the twin
# diff silently stops comparing like with like.

set -euo pipefail

runs="${1:-1}"
capture="${2:-240}"
prefix="${3:-qhv-orin-boot}"

# WITH_RNG=1 presents the virtio-net + virtio-rng devices in the virtio-mmio
# slot order mkqnximage's own runimage assembles (disk, net, ..., rng — see
# $QNX_HOST/common/mkqnximage/qemu/runimage line 55) and the host image's
# startup.sh binds ("random ... devr-virtio.so:mem=0xa003a00" is slot 3).
# The net device is a slot filler; user-mode slirp, no host bridge.
#
# This is not cosmetic. On 2026-09-09 presenting the rng device moved the
# Windows launch->guest-banner time from ~49.2 s to 29.7 s — the 19 s the
# entropy-less boot spends timing out is 40% of the measurement. A run
# without it and a run with it are NOT comparable, which is why the device
# set is stamped into the times file below alongside the QEMU version.
# rng-builtin, not rng-random, so the identical line works on Windows.
with_rng="${WITH_RNG:-0}"
rng_args=()
if [[ "${with_rng}" == "1" ]]; then
  rng_args=(-netdev user,id=n0 -device virtio-net-device,netdev=n0
            -object rng-builtin,id=rng0 -device virtio-rng-device,rng=rng0)
fi

ifs="ifs.bin"
disk="disk-qemu"

# Progress markers on the shared serial line, in the order they must appear.
#
# NOTE, because the obvious guess is wrong: the QHV *host* prints no banner of
# its own here. logs/sample-boot/qhv-tcg-host-and-guest-boot.log's curation
# header claims to look for a host banner "QNX qnx-qhv ... QEMU_virt", and the
# original launch-qhv-tcg.ps1 said the same -- but no such line exists in that
# log's body, or in any run reproduced since. Only the guest ever prints a
# banner. Checking for the host one therefore always failed and made healthy
# runs look broken. These three markers are all genuinely emitted:
#
#   1. host reached post_start   -> "=== AUTO-START QNX GUEST UNDER QVM"
#   2. hypervisor was invoked    -> "=== launching qvm @g2.conf"
#   3. guest crossed EL2/EL1     -> "QNX qnx-guest ... ARMv8_Foundation_Model"
#
# The guest identifies as ARMv8_Foundation_Model -- the virtual platform QHV
# synthesises for it, which is also why its startup is startup-armv8_fm.
marker_host="=== AUTO-START QNX GUEST UNDER QVM"
marker_qvm="=== launching qvm @g2.conf"
marker_guest="QNX qnx-guest"

for f in "${ifs}" "${disk}"; do
  if [[ ! -f "${f}" ]]; then
    echo "ERROR: ${f} not found in $(pwd)." >&2
    echo "       scp it from the Windows build host's qhv/host/output/." >&2
    exit 1
  fi
done

if [[ ! -f "SHA256SUMS" ]]; then
  echo "WARNING: SHA256SUMS not found — twin-sync invariant unverified." >&2
  echo "         The whole point of this leg is that both hosts boot the SAME" >&2
  echo "         images; an unverified copy makes the diff meaningless." >&2
fi

# WHICH QEMU. The 2026-09-08 confound came from this script silently picking
# up /usr/bin's distro 6.2.0 while the Windows side ran 11.x -- and 6.2's virt
# board does not wire the EL2 virtual-timer IRQ at all (added in QEMU 9.0,
# commit 1ec896fe7c), so a VHE hypervisor host hangs at its first timeout.
# Selection is therefore explicit and stamped: QEMU_BIN wins; otherwise the
# from-source build produced by build-qemu-on-orin.sh if present; otherwise
# PATH, loudly.
qemu_bin="${QEMU_BIN:-}"
if [[ -z "${qemu_bin}" ]]; then
  if [[ -x "${HOME}/qemu-v11.1.0/bin/qemu-system-aarch64" ]]; then
    qemu_bin="${HOME}/qemu-v11.1.0/bin/qemu-system-aarch64"
  else
    qemu_bin="$(command -v qemu-system-aarch64 || true)"
    echo "WARNING: no from-source QEMU under ~/qemu-v11.1.0; using PATH's ${qemu_bin:-(none)}." >&2
    echo "         If that is the distro 6.2.0 the QHV host will hang -- see build-qemu-on-orin.sh." >&2
  fi
fi
if [[ -z "${qemu_bin}" || ! -x "${qemu_bin}" ]]; then
  echo "ERROR: no usable qemu-system-aarch64 (QEMU_BIN='${QEMU_BIN:-}')." >&2
  exit 1
fi

echo "Host kernel: $(uname -r)  /  CPU part: $(awk '/CPU part/{print $4; exit}' /proc/cpuinfo)"
echo "QEMU: ${qemu_bin} -> $("${qemu_bin}" --version | head -1)"
echo

summary="${prefix}-times.txt"
# Stamp provenance into the data itself. On 2026-09-08 this leg was run with
# QEMU 11.0.50 on Windows against 6.2.0 here -- five major releases apart, on
# the EL2-emulation path QHV depends on -- and the argument lists being
# identical hid it. Whoever compares two of these files must be able to see
# that at a glance without re-deriving it.
{
  echo "# host: $(uname -srm) / $(awk -F: '/model name/{print $2; exit}' /proc/cpuinfo 2>/dev/null | sed 's/^ *//')"
  echo "# qemu: $("${qemu_bin}" --version | head -1)  [${qemu_bin}]"
  echo "# disk: -snapshot (guest writes discarded; every run boots the copy-time bytes, so SHA256SUMS keeps holding)"
  echo "# devices: virtio-blk$([[ "${with_rng}" == "1" ]] && echo " + virtio-net(slirp) + virtio-rng(builtin)" || echo " only (NO rng: entropy init fails and times out, ~+19 s)")"
  echo "# marker: launch -> guest banner (QNX qnx-guest ... ARMv8_Foundation_Model)"
  echo "# NOTE: only comparable against a run whose 'qemu:' AND 'devices:' lines both match."
} > "${summary}"
failures=0

for ((run = 1; run <= runs; run++)); do
  log="${prefix}${run}.log"
  rm -f "${log}"

  start_ns=$(date +%s%N)
  "${qemu_bin}" \
    -machine virt,virtualization=on,gic-version=3 \
    -cpu max \
    -accel tcg \
    -smp 2 \
    -m 2G \
    -snapshot \
    -drive file="${disk}",if=none,id=drv0,format=raw \
    -device virtio-blk-device,drive=drv0 \
    "${rng_args[@]}" \
    -kernel "${ifs}" \
    -serial "file:${log}" \
    -display none \
    -no-reboot &
  qpid=$!

  elapsed_ms=""; t_host=""; t_qvm=""; t_sc=""
  deadline=$(( $(date +%s) + capture ))
  while [[ $(date +%s) -lt ${deadline} ]]; do
    # Per-marker wall times. The headline number contains fixed waits that are
    # identical on both hosts (the guest's if_up retries with no net vdev, the
    # host's waitfor /dev/random without rng), which dilute the host ratio; the
    # segments let a reader separate compute-bound time from timeouts.
    now_ms=$(( ( $(date +%s%N) - start_ns ) / 1000000 ))
    [[ -z "${t_host}" ]] && grep -qF "${marker_host}" "${log}" 2>/dev/null && t_host=${now_ms}
    [[ -z "${t_qvm}"  ]] && grep -qF "${marker_qvm}"  "${log}" 2>/dev/null && t_qvm=${now_ms}
    [[ -z "${t_sc}"   ]] && grep -qF "Startup complete" "${log}" 2>/dev/null && t_sc=${now_ms}
    if grep -qF "${marker_guest}" "${log}" 2>/dev/null; then
      elapsed_ms=${now_ms}
      break
    fi
    # QEMU died early — stop waiting on a log that will never grow.
    kill -0 "${qpid}" 2>/dev/null || break
    sleep 0.1
  done

  kill "${qpid}" 2>/dev/null || true
  wait "${qpid}" 2>/dev/null || true

  host_seen="no"; qvm_seen="no"; guest_seen="no"
  grep -qF "${marker_host}"  "${log}" 2>/dev/null && host_seen="yes"
  grep -qF "${marker_qvm}"   "${log}" 2>/dev/null && qvm_seen="yes"
  grep -qF "${marker_guest}" "${log}" 2>/dev/null && guest_seen="yes"

  if [[ -n "${elapsed_ms}" ]]; then
    echo "run ${run}: ${elapsed_ms} ms" | tee -a "${summary}"
    ifup=$(grep -c "if_up: tries exhausted" "${log}" 2>/dev/null || true)
    echo "#   segments run ${run}: host_post_start=${t_host:-?} qvm_launched=${t_qvm:-?} guest_startup_complete=${t_sc:-?} guest_banner=${elapsed_ms} (ms from launch); if_up_exhausted=${ifup}" \
      | tee -a "${summary}"
  else
    failures=$((failures + 1))
    echo "run ${run}: TIMEOUT after ${capture}s (host=${host_seen} qvm=${qvm_seen} guest=${guest_seen})" \
      | tee -a "${summary}"
  fi
  echo "         host=${host_seen}  qvm=${qvm_seen}  guest=${guest_seen}  log=${log}"
done

echo
echo "========== SUMMARY =========="
cat "${summary}"
echo
echo "All three markers must read yes for a run to count, and they fail"
echo "differently: host=no means QHV never reached post_start; qvm=no means the"
echo "hypervisor was never invoked; guest=no with the other two yes means qvm ran"
echo "but nothing came up across the EL2/EL1 boundary. Only the last of those is"
echo "the interesting failure, and none of them is the same as a timeout."
echo
echo "To compare against the Windows leg, run there:"
echo "    scripts\\launch-qhv-tcg.ps1 -Runs ${runs} -StopOnGuestBanner"
echo "and diff the two '<prefix>-times.txt' files. Same images, same QEMU args,"
echo "same accelerator, same marker — only the host differs."

if (( failures > 0 )); then
  echo
  echo "WARNING: ${failures}/${runs} run(s) did not reach the guest banner." >&2
  exit 1
fi
