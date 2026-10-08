"""scripts/orin/gate2-smoke.sh, run against stubs only (Phase 3b / A6, 2026-10-05).

The runner takes one functional smoke per harness family through the board after its upgrade
(Gate 2): for each step G0 to G21 it runs one fixed command, applies one fixed pass rule, and
appends one line to ~/gate2/gate2.log. Nothing here needs a board. The harnesses, the launcher,
the two DDS peers, fma and llama-cli are stub scripts in a made-up deploy under a temporary
HOME; journalctl, systemctl, udevadm, lsblk, findmnt, ps, id, sudo, sync, sleep, date,
tegrastats, python3 and qemu-system-aarch64 are stubs on PATH; /sys, /proc, /run, /dev/shm and
/tmp are made-up trees. A guest is a small process the stub launcher starts, so that the
runner's Stop has something to signal and to wait for. The real commands left are bash's own,
env, timeout, sha256sum, mkdir, mv, rm, tr and grep.

Every value below is made up: the latencies, counts, percentages and verdict words the stub
harnesses print, the console lines' numbers, the image contents, the login. The layouts are the
real ones (the reports' check lines, the guest's console lines, lsblk -P, findmnt -r,
journalctl's cursor line, systemctl show's blocks, tegrastats' GR3D field, the two DDS peers'
lines).

What these tests do NOT show: that any step passes on the board, or that a real harness prints
what its stub prints here (the pass rules are held to the report sources' wording by reading
them, not by running them). The stub sudo runs what it is given; the real one is not
exercised. llama.cpp's own wording for an offloaded model and for an NvMap failure is taken
from its upstream form and from the vendor's forum note, and is unverified at the pinned commit.
"""
import hashlib
import os
import re
import shutil
import subprocess
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ORIN = os.path.join(REPO, "scripts", "orin")
SCRIPT = os.path.join(ORIN, "gate2-smoke.sh")
LIB = os.path.join(ORIN, "lib-stick.sh")
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not available")

MARKER = "marker-zq7-not-a-real-host"
LOGIN = "tester"
STEPS = ["G%d" % i for i in range(22)]
GPU_STEPS = ("G18", "G19", "G20", "G21")
GPU_OWNER = {"GATE2_GPU_OWNER_PRESENT": "1"}
NO_VM_STEPS = ("G18", "G19")                   # every other step creates a KVM VM
LINE = re.compile(r"^G(?:[0-9]|1[0-9]|2[01]) (?:PASS|FAIL [a-z]+(?:-[a-z]+)*)$")
VERDICT_WORDS = ("HELD", "PARTIAL", "REFUTED", "VOID", "UNSCORED", "ACCEPT", "REJECT")
DDS_PIN = "ab12cd34" * 5                       # a made-up commit, in the shape of the pinned one
IMAGES = ("ifs-its.bin", "ifs-kick.bin", "ifs-bell.bin", "ifs-paths.bin", "ifs-stamp.bin", "ifs-someip.bin",
          "ifs-live.bin", "ifs-unmask-a.bin", "ifs-unmask-b.bin", "ifs-robust.bin", "ifs-trace.bin", "ifs-dds.bin",
          "ifs-svc.bin", "disk-qemu")
STICK = 'NAME="sda" RM="1" TRAN="usb" TYPE="disk"\n'
LSBLK = 'NAME="nvme0n1" RM="0" TRAN="nvme" TYPE="disk"\nNAME="zram0" RM="0" TRAN="" TYPE="disk"\n'
MOUNTS = "/ /dev/nvme0n1p1 rw,relatime\n/run tmpfs rw,nosuid,nodev,noexec,relatime\n"
VENDOR_MOUNT = "/media/%s/L4T-README /dev/loop0 ro,nosuid,nodev,relatime,uid=1000\n" % LOGIN


# ------------------------------------------------------------------ what the stubs print

# What each harness prints when its smoke is functionally clean. The numbers and the verdict
# words are made up; they are here so that a test can show that none of them leaves the attempt's
# own directory.
def _complete(arms, k):
    return ("[01:02:09] complete: %d arm(s) x %d round(s), each round a clean result or a recorded stall, "
            "every file this run's\n" % (arms, k))


PASS_OUT = {
    "run-ladder.sh": (
        '[01:02:03] doorbell proof: "run": 1, "want": 10000, "got": 10000, "d_mmio_exit_kernel": 11111, '
        '"d_mmio_exit_user": 7, "d_exits": 22222, "ok": true\n' + _complete(12, 4)
        + "  A-loopback    4   0.7770 [0.7700, 0.7780]\n  D-guest       4   0.8880 [0.8800, 0.8890]\n"),
    "run-bell.sh": (
        _complete(2, 2) + "  rounds 2\n"
        "  M1 every arm 2 rounds of n samples, none rejected or bad, its own transport, the probe on core 4 -> ok\n"
        "  M2 one doorbell per exchange, none early, no stray byte -> ok\n"
        "  M3 every boot: msixcfg done, the console and the msix monitors serving -> ok\n"
        "  M4 KVM's counters around every arm -> ok\n"
        "    K  shmdb       777.70    788.80    799.90    811.10\n"
        "  P1  median DIFF(p50) -66.60 us, interval upper -55.50 (HELD at <= -40) -> HELD\n"
        "  P2  median DIFF(p99) -77.70 us, interval upper -11.10 -> PARTIAL\n"
        "  P3  mmio_exit_user -9.99 (want <= -1.5), mmio_exit_kernel +9.99 (want >= +0.5) per exchange -> REFUTED\n"),
    "run-paths.sh": (
        _complete(6, 6) + "  rounds 6 (stamp k=6, smp=2)\n"
        "  M1 every arm a round for each of 1..k of n samples after the warm-up, none rejected or bad, "
        "its own transport, the probe on core 4 -> ok\n"
        "  M2 K and B: one doorbell per exchange, one wake-up each, none early, no stray byte, no EAGAIN -> ok\n"
        "  M3 every boot: msixcfg done, the console and msix monitors serving -> ok\n"
        "  M4 KVM's counters and all 2 vCPU threads' run times around every arm -> ok\n"
        "  P1  B - T -555.50 (<= -100), B - U -444.40 (<= -100) -> UNSCORED (k=6, smoke; the rule is fixed at k = 18)\n"
        "  P2  P - B -33.30 (<= -20) -> UNSCORED (k=6, smoke; the rule is fixed at k = 18)\n"
        "  P3  S - T +0.11 [-0.22, +0.33] (inside +-3) -> UNSCORED (k=6, smoke; the rule is fixed at k = 18)\n"
        "  P4  B - K -66.60 (<= -40) -> UNSCORED (k=6, smoke; the rule is fixed at k = 18)\n"),
    "run-mmio.sh": (
        _complete(2, 6) + "  rounds 6, 1200 exchanges per arm\n"
        "  M1 every arm 6 rounds, the probe's counts clean -> ok\n"
        "  M2 every traced address falls in a named region -> ok\n"
        "  M3 the reply doorbell, BAR0 + 0xc, 0.90-1.10 writes per exchange, all in the kernel; BAR0/BAR1 read "
        "from every boot -> ok\n"
        "  M4 traced accesses match KVM's MMIO exit counters (all, and userspace) -> ok\n"
        "  P1  GICD K 7.777 (>= 2.5), B 0.111 (<= 0.5); GITS B 8.888 (>= 3.5), K 0.222 (<= 0.5) -> HELD\n"
        "  P2  console userspace +0x60 7.777, +0x64 8.888 (each >= 0.9), share 0.999 (>= 0.90) -> HELD\n"),
    "run-stamp.sh": (
        "[01:02:03] window sampler verified: 3 clock and 2 tegrastats sample(s) in 1.6 s\n" + _complete(4, 4)
        + "  D-stamp       4   0.9990 [0.9900, 0.9995]\n"),
    "run-metal.sh": (
        "[01:02:03] the units are back on 0-5, drop-ins removed\n" + _complete(1, 4)
        + "  host: HZ 250 (tick period 4000 us), all cores 0-5, confined to 3,5, QEMU on 0-2\n"
        "  rounds 4, aligned 4, arms {'open': 2, 'confined': 2}\n"
        "  M1 aligned rounds 4/4 (want >= 90%) -> ok\n"
        "  M2 rounds whose udevd and PID 1 fit their arm, before and after: 4/4 (want all) -> ok\n"
        "  M3 rounds whose QEMU threads stayed on their cores: 4/4 (want all) -> ok\n"
        "  M4 SSH logins accepted during the rounds: 0 (want 0) -> ok\n"
        "  M5 tick handler (tick_nohz_highres_handler) expiries within [0, 100) us of the grid: 3900/4000 (want >= 90%) -> ok\n"
        "  M6 tick-bin tail exchanges 3 (want >= 30) -> FAILED\n"
        "  P1  the tick bin is over-represented in the tail: RATIO 7.77 -> not scored (k=4; the prediction is for k=40)\n"
        "  P2  tick-bin exchanges are slower: SLOWDOWN +7.7 us -> not scored (k=4; the prediction is for k=40)\n"
        "  P3  confinement changes the tail little: p99 confined 777.7, open 888.8 us -> not scored (k=4; the prediction is for k=40)\n"
        "  P4  the typical exchange does not change: p50 confined 555.5, open 666.6 us -> not scored (k=4; the prediction is for k=40)\n"),
    "run-tick.sh": (
        "[01:02:03] the units are back on 0-5, drop-ins removed\n" + _complete(1, 4)
        + "  rounds 4, aligned 4, kinds {'light': 2, 'heavy': 2}, traced cores [0, 1, 2, 4]\n"
        "  M1 aligned rounds 4/4 (want >= 90%) -> ok\n"
        "  M2 rounds confined (udevd, PID 1, gnome-shell on 3,5) 4/4, QEMU's threads on 0-2 4/4 (want all) -> ok\n"
        "  M3 SSH logins accepted during the rounds: 0 (want 0) -> ok\n"
        "  M4 tick handler (tick_nohz_highres_handler) expiries within [0, 100) us of the 4000 us grid: 1900/2000 (want >= 90%) -> ok\n"
        "  M5 tick-bin tail in light rounds 2 (want >= 30) -> FAILED; heavy tick-bin tail 1, non-tail 9 (want >= 20, >= 100)\n"
        "  M6 p50 heavy 555.5, light 556.6 us (want within 10) -> ok\n"
        "  P1  the tick bin is over-represented in the tail: RATIO 8.88 -> not scored (k=4; the prediction is for k=40)\n"),
    "run-someip0.sh": (
        _complete(6, 6) + "  M1 every arm 6 rounds of n samples, none rejected or bad, its own transport, the client on core 4 -> ok\n"
        "  P1  the retention is the ~5 ms: VT - VT0 +5555.00, VU - VU0 +4444.00 us (want both in [4800, 5200]) -> HELD\n"),
    "liveness-demo.sh": "[01:02:03] liveness demo -> out\n[01:02:40] done -> out\n",
    "run-unmask.sh": (
        _complete(2, 4) + "  rounds 4, 1200 exchanges per arm\n"
        "  P1  D - U at p50 -7.777 (<= -2.0, interval upper -0.111 < 0) -> HELD\n"),
    "run-bellrobust.sh": (
        "[01:02:03] the doorbell's robustness, by the rule above\n  repeats 1, one boot per scenario and repeat\n"
        + "".join("    S%d r1 pass\n" % i for i in range(1, 9))
        + "  console lines naming an error, any boot (unscored): 0\n"
        + "".join("  P%d  S%d passes in every repeat -> HELD (1 of 3 repeats ran)\n" % (i, i) for i in range(1, 9))),
    "run-trace.sh": (
        _complete(1, 6) + "  pairs 6\n"
        "  M1 every window's trace is whole, one CPU, >= 100 reads of its kind, <= 2% not cut -> ok\n"
        "  M2 the whole read is >= 3 us longer for the network read under tracing: 6/6 -> ok\n"
        "  M3 every N probe clean, every L benchmark ran its spaced sock op -> ok\n"
        "  P1  io-sock's work B + Cw is >= 3 us longer for the network read: +7.77 us -> HELD\n"),
    "run-queue.sh": (
        "[01:02:50] udevd's queue released and settled\n" + _complete(1, 4)
        + "  rounds 4, aligned 4, arms {'run': 2, 'hold': 2}\n"
        "  M1 aligned rounds 4/4 (want >= 90%) -> ok\n"
        "  M2 U raised the seqnum by >= 3: 4/4 (want >= 90%) -> ok\n"
        "  M3 rounds whose queue at the end fits the arm (held: events waiting; run: empty): 4/4 (want all) -> ok\n"
        "  M4 exchanges U [10, 12], tj [11, 9] (want >= 400 and >= 400 per arm) -> FAILED\n"
        "  P1  held, the injected uevents make no window: U +0.11 us (quiet below +3) -> not scored (k=4; the prediction is for k=24)\n"),
    "vlm-demo.sh": (
        "honest-digit-0     seq=1001 answer=0 conf=77.7%  client=ACCEPT/ok  console=accept (seen=1 acc=1 rej=0)  ok\n"
        "corrupt-class      seq=1011 answer=3 conf=66.6%  client=REJECT/class-out-of-range  console=REJECT class-out-of-range  ok\n"
        "18 of 18 claims: client verdict as expected AND corroborated by the guest console\n[01:03:00] done -> out\n"),
    "run-llm-interference.sh": (
        "[01:02:03] window sampler verified: 3 clock and 2 tegrastats sample(s) in 1.6 s\n" + _complete(4, 2)
        + "  llm           2   0.9990 [0.9900, 0.9995]\n"),
}
GC_HARNESSES = ("run-ladder.sh", "run-bell.sh", "run-paths.sh", "run-mmio.sh", "run-stamp.sh", "run-metal.sh", "run-tick.sh",
                "run-someip0.sh", "run-unmask.sh", "run-bellrobust.sh", "run-trace.sh", "run-queue.sh")
EL_HARNESSES = ("liveness-demo.sh", "vlm-demo.sh", "run-llm-interference.sh")

# What a guest's console holds once the image's last start-up line is out. A NUL and CRs are in
# it because a real console log has both.
_MON = "monitor: safety monitor listening on :7100 (frame=64 bytes, conf_min=60%)\r\n"
CONSOLES = {
    "ifs-its.bin": (
        "cpu0: MPIDR=80000000\r\ncpu1: MPIDR=80000001\r\n\0" + _MON
        + "monitor: shm configured: ivshmem BAR2 at a made-up address\r\n"
        "its: selftest: DeviceID 0x8 EventID 0 -> LPI 8200 (ITT 0x40000000)\r\n"
        "its: selftest: 20 INT commands, 20 LPIs delivered, 0 timeouts (1 s each), slowest 777 us\r\n"
        "its: msixcfg: ivshmem 00:01.0 BAR1 0x10040000 (4096 B), MSI-X entry 0 -> 0x8090040 data 0\r\n"
        "monitor: safety monitor serving shm on ivshmem (frame=64 bytes, conf_min=60%)\r\n"
        "monitor: safety monitor serving shm-kick on ivshmem@4096 (frame=64 bytes, conf_min=60%)\r\n"
        "its: msixwait: attached LPI 8193; ringing back the peer id at BAR2+60\r\n"),
    "ifs-kick.bin": (
        _MON + "monitor: shm configured: ivshmem BAR2 at a made-up address\r\n"
        "monitor: safety monitor serving shm on ivshmem (frame=64 bytes, conf_min=60%)\r\n"
        "monitor: safety monitor serving shm-kick on ivshmem@4096 (frame=64 bytes, conf_min=60%)\r\n"),
    "ifs-stamp.bin": _MON + "monitor: stamping replies on :7103: t_in payload[8..15], t_out payload[16..23], CLOCK_MONOTONIC ns\r\n",
    "ifs-live.bin": _MON + "monitor: service monitor listening on :7102 (frame=64 bytes, conf_min=60%), liveness deadline 2000 ms\r\n",
    "ifs-svc.bin": (_MON + "monitor: claim kinds: 0 mnist (us <= 100000), 1 vlm model 7 (us <= 1000000), conf_min=60%\r\n"
                    "monitor: safety monitor listening on :7102 (frame=64 bytes, conf_min=60%)\r\n"),
    "ifs-dds.bin": (
        _MON + "qnx-dds-monitor: waiting for claims\r\n"
        "claim seq=11 cls=9 conf=8 us=7 -> REJECT (reason=1)\r\n"
        "claim seq=12 cls=1 conf=2 us=7 -> REJECT (reason=3)\r\n"
        "claim seq=13 cls=1 conf=9 us=7 -> REJECT (reason=2)\r\n"
        "claim seq=14 cls=1 conf=8 us=6 -> REJECT (reason=4)\r\n"
        "claim seq=15 cls=1 conf=8 us=7 -> ACCEPT (reason=0)\r\n"),
}
# The two peers' lines, in their layout. The claims are made up: their numbers, and the names
# the four bad ones go by.
PUBBAD_OUT = ("matched=1 after 333 ms\nsend seq=11 bad-one rc=0\nsend seq=12 bad-two rc=0\n"
              "send seq=13 bad-three rc=0\nsend seq=14 bad-four rc=0\nsend seq=15 good rc=0\n")
SUBV_OUT = ("VERDICT seq=11 accepted=0 reason=1\nVERDICT seq=12 accepted=0 reason=3\nVERDICT seq=13 accepted=0 reason=2\n"
            "VERDICT seq=14 accepted=0 reason=4\nVERDICT seq=15 accepted=1 reason=0\ntotal verdicts=5\n")
RING_OUT = ("ring: joined as peer 2; ringing peer 1 vector 0, 100 times, 2.0 ms apart, waiting for each echo\n"
            "ring: window 1111 2222 (time_ns of the first and last ring)\n"
            "ring: 100 rung, 100 echoed, 0 timed out (1000 ms)\nring: echo round trip us: p50 777.7  p90 888.8  max 999.9\n")
FMA_OUT = ("device=Orin cc=8.7 sms=8 tag=gate2\nround=1 gflops=7.7 elapsed=1.1\nround=2 gflops=8.8 elapsed=2.2\n"
           "SUMMARY tag=gate2 rounds=2 mean_gflops=8.2 best=8.8 worst=7.7 seconds=5.5\n")
TEGRA_IDLE = "10-05-2026 01:02:03 RAM 1111/9999MB (lfb 1x1MB) CPU [1%@1111,2%@1111] GR3D_FREQ 0% cpu@11.1C/22.2C VDD_IN 1111mW/2222mW/3333mW\n"
TEGRA_BUSY = TEGRA_IDLE.replace("GR3D_FREQ 0%", "GR3D_FREQ 77%")
LLAMA_ERR = ("ggml_cuda_init: found 1 CUDA devices:\n  Device 0: Orin, compute capability 8.7, VMM: no\n"
             "load_tensors: offloading 8 repeating layers to GPU\nload_tensors: offloaded 9/9 layers to GPU\n"
             "llama_perf_context_print:        eval time =     777.70 ms /    15 runs   (   55.55 ms per token)\n")
LLAMA_OUT = "Hello! How can I help you today?\n"
NVMAP = "NvMapMemAllocInternalTagged: 1111111111 error 12\nNvMapMemHandleAlloc: error 0\nNvMapMemAllocInternalTagged failed: error 12\n"
STAMP_JSON = """{
  "utc": "2026-10-05T01:02:03Z",
  "kernel": "6.8.0-made-up",
  "system": {
    "l4t_release": "# R39 (release), REVISION: 9.9, GCID: 12345678, BOARD: generic, EABI: aarch64, DATE: made up",
    "os_release": "Ubuntu 24.04.9 LTS (made up)",
    "config_hz": 250,
    "config_hz_source": "/proc/config.gz",
    "python3_version": "3.12.9",
    "nvpmodel": "NV Power Mode: EXAMPLE 1"
  },
  "n": 1000, "k": 4, "warmup": 200, "interval_ms": 2
}
"""
SERVER_LOG = LLAMA_ERR + "main: server is listening on http://127.0.0.1:8089\n"

# ------------------------------------------------------------------ the stubs

HEAD = r'''#!/bin/bash
S='@S@'
show() { local l; [ -e "$S/$1" ] || return 0; while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$l"; done < "$S/$1"; }
code() { local c=0; if [ -e "$S/$1" ]; then read -r c < "$S/$1"; fi; exit "$c"; }
stdin_is() { readlink "/proc/$$/fd/0" > "$S/stdin-$1" 2>/dev/null || echo unreadable > "$S/stdin-$1"; }
'''
LOGGED = 'echo "@NAME@ $*" >> "$S/calls.log"\n'

PATH_STUBS = {
    "sudo": LOGGED + r'''
if [ -e "$S/sudo_denied" ]; then echo "sudo: a password is required" >&2; exit 1; fi
if [ "${1:-}" != -n ]; then echo "stub sudo: called without -n" >&2; exit 64; fi
shift
exec "$@"
''',
    "ps": LOGGED + r'''
if [ "$*" != "-e -o pid= -o args=" ]; then echo "stub ps: unexpected arguments: $*" >&2; exit 64; fi
if [ -e "$S/ps_rc" ]; then code ps_rc; fi
echo "      1 /sbin/init"
show procs_static
if [ -e "$S/procs" ]; then
	while read -r pid rest; do
		if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then echo "   $pid $rest"; fi
	done < "$S/procs"
fi
exit 0
''',
    "id": LOGGED + r'''
case "$*" in
	-u) show uid ;;
	-nG) show my_groups ;;
	*) echo "stub id: unexpected arguments: $*" >&2; exit 64 ;;
esac
''',
    "lsblk": LOGGED + r'''
if [ "$*" != "-d -n -P -o NAME,RM,TRAN,TYPE" ]; then echo "stub lsblk: unexpected arguments: $*" >&2; exit 64; fi
show lsblk; code lsblk_rc
''',
    "findmnt": LOGGED + r'''
if [ "$*" != "-r -n -o TARGET,SOURCE,OPTIONS" ]; then echo "stub findmnt: unexpected arguments: $*" >&2; exit 64; fi
show findmnt; code findmnt_rc
''',
    # journalctl: the kernel's lines since a cursor, a fresh cursor, or the ssh units' lines. Any
    # other form would print the host's name with every line, and prints the marker here. The
    # kernel's journal is the file kjournal, one line a line, and a cursor "cur-N" stands after
    # its Nth line; a line that begins <3> is one at err level.
    "journalctl": LOGGED + r'''
a=" $* "
case "$a" in
	*" -u ssh -u sshd "*)
		if [[ "$a" != *" -o cat "* ]] || [[ "$a" != *" --since @"* ]] || [[ "$a" != *" --until @"* ]]; then echo "@MARKER@"; exit 0; fi
		show ssh_log; exit 0 ;;
	*" -k "*) ;;
	*) echo "@MARKER@"; exit 0 ;;
esac
if [ -e "$S/journal_rc" ]; then code journal_rc; fi
lines=()
if [ -e "$S/kjournal" ]; then while IFS= read -r l || [ -n "$l" ]; do lines+=("$l"); done < "$S/kjournal"; fi
total="${#lines[@]}"
if [[ "$a" == *" -n 0 "* ]]; then
	if [[ "$a" != *" --show-cursor "* ]]; then echo "@MARKER@"; exit 0; fi
	echo "-- cursor: cur-$total"; exit 0
fi
if [[ "$a" != *" -o cat "* ]] || [[ "$a" != *" --after-cursor "* ]]; then echo "@MARKER@"; exit 0; fi
from=""; prev=""
for w in "$@"; do if [ "$prev" = --after-cursor ]; then from="$w"; fi; prev="$w"; done
echo "$from" >> "$S/cursors_asked"
case "$from" in cur-[0-9]*) from="${from#cur-}" ;; *) echo "Failed to seek to cursor: Invalid argument" >&2; exit 1 ;; esac
i="$from"
while [ "$i" -lt "$total" ]; do
	l="${lines[$i]}"; i=$((i + 1))
	if [[ "$a" == *" -p err "* ]]; then
		case "$l" in "<3>"*) printf '%s\n' "${l#<3>}" ;; esac
	else
		printf '%s\n' "${l#<3>}"
	fi
done
if [[ "$a" == *" --show-cursor "* ]]; then echo "-- cursor: cur-$total"; fi
exit 0
''',
    "systemctl": LOGGED + r'''
case "${1:-}" in
	list-units)
		if [ "$*" != "list-units --no-legend --plain user@*.service session-*.scope" ]; then echo "stub systemctl: unexpected: $*" >&2; exit 64; fi
		show units; exit 0 ;;
	show)
		if [ "${2:-} ${3:-}" != "-p AllowedCPUs" ] || [ "$#" -lt 4 ]; then echo "stub systemctl: unexpected: $*" >&2; exit 64; fi
		shift 3
		first=1
		for u in "$@"; do
			if [ "$first" = 0 ]; then echo; fi
			first=0; v=""
			if [ -e "$S/allowed-$u" ]; then read -r v < "$S/allowed-$u"; fi
			echo "AllowedCPUs=$v"
		done
		exit 0 ;;
esac
echo "$*" >> "$S/systemctl-changed"
echo "@MARKER@"
exit 0
''',
    "udevadm": LOGGED + r'''
case "$*" in
	"settle --timeout=30")
		if [ -e "$S/on_settle" ]; then . "$S/on_settle"; fi
		code settle_rc ;;
	"control --start-exec-queue")
		if [ -e "$S/udev_release_works" ]; then rm -f '@RUN@/udev/queue'; fi
		exit 0 ;;
esac
echo "stub udevadm: unexpected arguments: $*" >&2; exit 64
''',
    "sync": 'echo "sync" >> "$S/calls.log"\n',
    # sleep: a twentieth of a second whatever was asked, so that a bounded wait is short here.
    # While the made-up guest's second vCPU runs, its run time grows with every sleep.
    "sleep": LOGGED + r'''
'@SLEEP@' 0.05
if [ -e "$S/cpu1_schedstat" ] && [ ! -e "$S/cpu1_idle" ]; then
	read -r f < "$S/cpu1_schedstat"
	if [ -e "$f" ]; then read -r a b c < "$f"; echo "$((a + 1000)) $b $c" > "$f"; fi
fi
if [ -e "$S/on_sleep" ]; then . "$S/on_sleep"; fi
exit 0
''',
    # date: the stamp an attempt's directory is named by moves on a second with every call, so
    # that two calls of a test never fall into one second; a test can hold it still instead.
    "date": r'''
if [ "$*" = "-u +%Y%m%dT%H%M%SZ" ]; then
	if [ -e "$S/date_utc" ]; then show date_utc; exit 0; fi
	n=0; if [ -e "$S/date_n" ]; then read -r n < "$S/date_n"; fi
	n=$((n + 1)); echo "$n" > "$S/date_n"
	printf '20261005T%02d%02d%02dZ\n' $((n / 3600)) $((n / 60 % 60)) $((n % 60))
	exit 0
fi
exec '@DATE@' "$@"
''',
    "tegrastats": LOGGED + r'''
show tegrastats
''',
    "python3": LOGGED + r'''
stdin_is "python3-${1##*/}"
case "${1##*/}" in
	check_virt_dtb.py) if [ ! -s "${2:-}" ]; then echo "no device tree at ${2:-}" >&2; exit 2; fi; show dtbcheck_out; code dtbcheck_rc ;;
	ivshmem_ring.py) show ring_out; code ring_rc ;;
esac
echo "stub python3: unexpected: $*" >&2; exit 97
''',
    "qemu-system-aarch64": LOGGED + r'''
stdin_is qemu
for a in "$@"; do printf '%s\n' "$a"; done > "$S/qemu.argv"
env > "$S/qemu.env"
for a in "$@"; do
	case "$a" in
		*dumpdtb=*) if [ ! -e "$S/qemu_no_dtb" ]; then printf 'made-up device tree\n' > "${a##*dumpdtb=}"; fi ;;
	esac
done
code qemu_rc
''',
}
# Each of these would print something that names the machine. None may ever run.
for _n in ("hostname", "uname", "ip", "nmcli", "hostnamectl", "loginctl", "dmesg"):
    PATH_STUBS[_n] = LOGGED + 'echo "@MARKER@"\n'

# A made-up long-running process: a guest's QEMU, or the ivshmem server that exits with it. It
# says when it is told to end, and ends by itself after a while whatever happens to the test.
# The QEMU waits on one long sleep: a wait ends at once when a signal with a handler arrives, so
# it answers TERM without waking up many times a second (every wake-up would be a process).
FAKEPROC = r'''
kind="$1"; peer="${2:-}"
if [ "$kind" = qemu ]; then
	sp=""
	if [ -e "$S/qemu_ignores_term" ]; then trap 'echo "qemu-term-ignored" >> "$S/calls.log"' TERM
	else trap 'echo "qemu-term" >> "$S/calls.log"; if [ -n "$sp" ]; then kill "$sp" 2>/dev/null; fi; exit 0' TERM; fi
	'@SLEEP@' 150 > /dev/null 2>&1 < /dev/null &
	sp=$!
	echo "$sp" >> "$S/helper_pids"
	: > "$S/qemu-ready-$$"
	while kill -0 "$sp" 2>/dev/null; do wait "$sp"; done
	exit 0
fi
# the server: gone a little after its peer, unless the test keeps it
trap 'exit 0' TERM
tail --pid="$peer" -s 0.1 -f /dev/null 2>/dev/null
i=0; while kill -0 "$peer" 2>/dev/null && [ "$i" -lt 1500 ]; do '@SLEEP@' 0.1; i=$((i + 1)); done
i=0; while [ -e "$S/server_stays" ] && [ "$i" -lt 1500 ]; do '@SLEEP@' 0.1; i=$((i + 1)); done
n=0; if [ -e "$S/server_lingers" ]; then read -r n < "$S/server_lingers"; fi
i=0; while [ "$i" -lt "$n" ]; do '@SLEEP@' 0.1; i=$((i + 1)); done
if [ -e '@TMP@/a6-ivshmem.sock' ]; then echo "server-exit sockets-present" >> "$S/calls.log"
else echo "server-exit sockets-gone" >> "$S/calls.log"; fi
exit 0
'''

LAUNCHER = r'''
stdin_is launcher
n=0; while [ -e "$S/launch-$n.env" ]; do n=$((n + 1)); done
env > "$S/launch-$n.env"
for a in "$@"; do printf '%s\n' "$a"; done > "$S/launch-$n.argv"
img="${IFS_BIN##*/}"
echo "launcher $img" >> "$S/calls.log"
if [ -e "$S/hook-launcher" ]; then . "$S/hook-launcher"; fi
if [ -e "$S/launch_refuses" ]; then echo "ERROR: a qemu-system-aarch64 is already running." >&2; exit 1; fi
# As the real launcher: it does not start over a socket it finds.
if [ -n "${KICK_SOCK:-}" ] && [ -e "$KICK_SOCK" ]; then echo "ERROR: $KICK_SOCK exists -- remove the leftover first" >&2; exit 1; fi
if [ -n "${IVSHMEM_SERVER:-}" ] && [ -e "$IVSHMEM_SERVER" ]; then echo "ERROR: $IVSHMEM_SERVER exists -- a live server, or a leftover" >&2; exit 1; fi
if [ -e "$S/console-$img" ]; then
	while IFS= read -r l || [ -n "$l" ]; do printf '%s\n' "$l"; done < "$S/console-$img" > "$LOG"
else : > "$LOG"; fi
bash "$S/fakeproc.sh" qemu > /dev/null 2>&1 < /dev/null &
q=$!
echo "$q" >> "$S/pids"
# Not before the made-up QEMU is ready to be told to end: a TERM that came sooner would not be logged.
i=0; while [ ! -e "$S/qemu-ready-$q" ] && [ "$i" -lt 500 ]; do '@SLEEP@' 0.01; i=$((i + 1)); done
echo "$q qemu-system-aarch64 -machine virt,gic-version=3 -kernel $IFS_BIN -nographic" >> "$S/procs"
mkdir -p '@PROC@'/"$q"/task/11 '@PROC@'/"$q"/task/12
echo "CPU 0/KVM" > '@PROC@'/"$q"/task/11/comm; echo "5000 10 3" > '@PROC@'/"$q"/task/11/schedstat
if [ -e "$S/no_cpu1_thread" ]; then echo "worker" > '@PROC@'/"$q"/task/12/comm
else echo "CPU 1/KVM" > '@PROC@'/"$q"/task/12/comm; fi
echo "7000 20 4" > '@PROC@'/"$q"/task/12/schedstat
echo '@PROC@'/"$q"/task/12/schedstat > "$S/cpu1_schedstat"
if [ -n "${IVSHMEM_SERVER:-}" ]; then
	: > "$IVSHMEM"; : > "$IVSHMEM_SERVER"; : > "$KICK_SOCK"
	bash "$S/fakeproc.sh" server "$q" > /dev/null 2>&1 < /dev/null &
	echo "$!" > "$IVSHMEM_SERVER.ready"
	echo "$!" >> "$S/pids"
	echo "$! python3 /made-up/gpu-concurrency/ivshmem_server.py --socket $IVSHMEM_SERVER --shm $IVSHMEM" >> "$S/procs"
fi
if [ ! -e "$S/launch_names_no_pid" ]; then echo "qemu pid: $q"; fi
echo "waiting for the guest to answer on 192.168.100.10 ..."
if [ -e "$S/launch_times_out" ] || [ -e "$S/launch_times_out_once" ]; then
	rm -f "$S/launch_times_out_once"
	echo "ERROR: guest did not answer on :7100 within 60s. Console tail:" >&2; exit 1
fi
if [ -e "$S/launch_never_says_up" ]; then exit 0; fi
echo "guest up after 1s (monitor answering on :7100)"
exit 0
'''

# A harness: it says what it was given, does what the test's hook says, prints what the test
# says, and returns what the test says. A hook runs before the output directory is made.
HARNESS = r'''
name="${0##*/}"
stdin_is "$name"
env > "$S/harness-$name.env"
for a in "$@"; do printf '%s\n' "$a"; done > "$S/harness-$name.argv"
echo "harness $name $*" >> "$S/calls.log"
if [ -e "$S/hook-$name" ]; then . "$S/hook-$name"; fi
if [ -n "${OUT:-}" ]; then mkdir -p "$OUT"; fi
if [ -e "$S/post-$name" ]; then . "$S/post-$name"; fi
show "out-$name"
if [ -e "$S/err-$name" ]; then show "err-$name" >&2; fi
code "rc-$name"
'''
# What a harness of lib-measure.sh does with its OUT: one that holds an earlier run is refused.
HOOK_FRESH_OUT = r'''
if compgen -G "$OUT/lat-*.json" > /dev/null; then echo "FATAL: $OUT already holds lat-*.json from an earlier run" >&2; exit 1; fi
'''
POST_LAT = 'echo made-up > "$OUT/lat-x_r1.json"\n'
# liveness-demo.sh refuses an OUT that exists at all.
HOOK_NO_OUT = 'if [ -e "$OUT" ]; then echo "FATAL: $OUT already exists" >&2; exit 1; fi\n'
# run-ladder.sh reads the native monitor at a fixed path, and has nothing to run without it.
HOOK_NEEDS_MONITOR = ('if [ ! -e "$HOME/ladder/monitor-native" ]; then echo "FATAL: no monitor-native under ~/ladder: build it first" >&2; '
                      'exit 1; fi\n')

PEER = r'''
name="${0##*/}"
stdin_is "$name"
echo "$name $*" >> "$S/calls.log"
env > "$S/$name.env"
if [ -e "$S/hook-$name" ]; then . "$S/hook-$name"; fi
show "${name}_out"; code "${name}_rc"
'''
FMA = r'''
stdin_is fma
echo "fma $*" >> "$S/calls.log"
env > "$S/fma.env"
show fma_out; code fma_rc
'''
LLAMA = r'''
v=""; if [ -n "${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-}" ]; then v=".retry"; fi
stdin_is "llama-cli$v"
echo "llama-cli$v $*" >> "$S/calls.log"
env > "$S/llama$v.env"
for a in "$@"; do printf '%s\n' "$a"; done > "$S/llama$v.argv"
if [ -e "$S/llama_hook$v" ]; then . "$S/llama_hook$v"; fi
if [ -e "$S/llama_stdout$v" ]; then show "llama_stdout$v"; else show llama_stdout; fi
if [ -e "$S/llama_stderr$v" ]; then show "llama_stderr$v" >&2; else show llama_stderr >&2; fi
if [ -e "$S/llama_rc$v" ]; then code "llama_rc$v"; fi
code llama_rc
'''
PROVISION_STUB = r'''
stdin_is provision
echo "provision $*" >> "$S/calls.log"
echo "check: 13 ok, 0 missing, 0 differs -- nothing for apply to do"
code provision_rc
'''


# ------------------------------------------------------------------ a made-up board

def _fwd(p):
    return str(p).replace("\\", "/")


def _put(path, text, mode=None):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as f:
        f.write(text.encode())
    if mode:
        os.chmod(str(path), mode)


def _sha(path):
    with open(str(path), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _bash_out(script):
    return subprocess.run([BASH, "-c", script], capture_output=True, text=True, timeout=60).stdout


@pytest.fixture(scope="session")
def tools(tmp_path_factory):
    """Where this bash finds the real sleep and date, which variables a bash started with an
    empty environment has by itself (its own, and on Windows the platform's), and how this bash
    writes the directory every made-up board is under when it is given as HOME."""
    out = _bash_out("type -P sleep; type -P date; env -i HOME=/nowhere PATH=\"$PATH\" bash -c 'env | cut -d= -f1'").split("\n")
    base = _fwd(tmp_path_factory.getbasetemp())
    its = subprocess.run([BASH, "-c", 'printf %s "$HOME"'], capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, HOME=base)).stdout
    return {"sleep": out[0].strip(), "date": out[1].strip(), "base": (base, its),
            "auto": set(x.strip() for x in out[2:] if x.strip()) - {"HOME", "PATH"}}


class Board:
    """A made-up board under one directory: a home with the deployed repo, the images, their
    manifests and what the builds left; fake /sys, /proc, /run, /dev/shm and /tmp; the stubs
    and their state. The defaults are a board on which every smoke passes."""

    def __init__(self, root, tools):
        self.root, self.tools = root, tools
        self.runner = SCRIPT                         # the copy of the runner a call starts
        self.stdin = subprocess.DEVNULL              # and what that call has as its standard input
        self.home, self.sys, self.proc, self.run_root = root / "home", root / "sys", root / "proc", root / "run"
        self.shm, self.tmp, self.state, self.bin = root / "shm", root / "tmp", root / "state", root / "bin"
        for d in (self.home, self.run_root, self.shm, self.tmp, self.state, self.bin):
            d.mkdir(parents=True)
        self.H, self.SHM, self.TMP = _fwd(self.home), _fwd(self.shm), _fwd(self.tmp)
        self.G = self.H + "/gate2"
        self.REPO = self.G + "/repo"
        self.R = self.REPO + "/orin-native/gpu-concurrency"
        self.E = self.REPO + "/orin-native/edge-llm"
        self.IMG = self.H + "/output"
        self.DDS = self.H + "/cyclonedds/" + DDS_PIN[:12]
        self.shmvars = {"IVSHMEM": self.SHM + "/a6-ivshmem", "IVSHMEM_SERVER": self.TMP + "/a6-ivshmem.sock",
                        "KICK_SOCK": self.TMP + "/a6-kick.sock"}
        # /sys
        net = self.sys / "class" / "net"
        (net / "br0" / "brif" / "tap-qnx").mkdir(parents=True)
        (net / "tap-qnx").mkdir()
        cpu = self.sys / "devices" / "system" / "cpu"
        _put(cpu / "online", "0-5\n")
        for c in ("cpu0", "cpu1"):
            for st in ("state0", "state1"):
                _put(cpu / c / "cpuidle" / st / "disable", "0\n")
        for pol in ("policy0", "policy4"):
            _put(cpu / "cpufreq" / pol / "scaling_governor", "schedutil\n")
        (self.sys / "kernel" / "tracing" / "instances").mkdir(parents=True)
        _put(self.sys / "kernel" / "tracing" / "set_event", "")
        (self.sys / "fs" / "pstore").mkdir(parents=True)
        # /proc
        _put(self.proc / "sys" / "kernel" / "random" / "boot_id", "0a0a0a0a-1111-2222-3333-444444444444\n")
        _put(self.proc / "stat", "cpu  1 2 3 4\nbtime 1700000000\nprocesses 99\n")
        _put(self.proc / "sys" / "vm" / "drop_caches", "0\n")
        # the home: the deployed repo, the images, what the builds left
        for n in GC_HARNESSES:
            self.script(self.R + "/" + n, HARNESS)
            self.set("out-" + n, PASS_OUT[n])
            self.set("hook-" + n, HOOK_FRESH_OUT)
            self.set("post-" + n, POST_LAT)
        for n in EL_HARNESSES:
            self.script(self.E + "/" + n, HARNESS)
            self.set("out-" + n, PASS_OUT[n])
        self.set("hook-liveness-demo.sh", HOOK_NO_OUT)
        self.set("hook-run-ladder.sh", HOOK_FRESH_OUT + HOOK_NEEDS_MONITOR)
        self.set("hook-run-llm-interference.sh", HOOK_FRESH_OUT)
        self.set("post-run-llm-interference.sh", POST_LAT)
        self.set("post-run-stamp.sh", POST_LAT + "cat > \"$OUT/stamp.json\" <<'EOF'\n" + STAMP_JSON + "EOF\n")
        self.set("post-run-tick.sh", POST_LAT + 'echo "made-up reduced trace" > "$OUT/tk-t2ms_r2.log"\n')
        self.set("post-vlm-demo.sh", "cat > \"$OUT/server.log\" <<'EOF'\n" + SERVER_LOG + "EOF\n")
        self.script(self.R + "/launch-qnx-kvm-bridged.sh", LAUNCHER)
        _put(self.R + "/ivshmem_ring.py", "# made up\n")
        _put(self.REPO + "/orin-native/tools/check_virt_dtb.py", "# made up\n")
        _put(self.REPO + "/ipc-test/qnx-dds-monitor/cyclonedds-l4t.xml", "<CycloneDDS/>\n")
        _put(self.REPO + "/ipc-test/qnx-dds-monitor/build-cyclonedds-qnx.sh",
             '#!/usr/bin/env bash\nset -euo pipefail\n\nCDDS_COMMIT="${CDDS_COMMIT:-%s}"   # made up\n' % DDS_PIN)
        _put(self.E + "/vlm-demo.sh.note", "made up\n")
        for n in IMAGES:
            _put(self.IMG + "/" + n, "made-up image %s\n" % n)
        self.write_manifests()
        _put(self.H + "/ladder/monitor-native", "made-up native monitor\n", 0o755)
        _put(self.H + "/ladder/monitor-native.source-sha256", "made-up source hash line\n")
        self.script(self.H + "/gpuload/fma", FMA)
        self.script(self.H + "/llama.cpp/build/bin/llama-cli", LLAMA)
        _put(self.H + "/models/SmolVLM-500M-Instruct-Q8_0.gguf", "made-up model\n")
        (self.home / "mnist").mkdir()
        for n in ("subv", "pubbad"):
            self.script(self.DDS + "/bin/" + n, PEER)
        # the stubs on PATH, and their state
        for n, body in PATH_STUBS.items():
            self.script(self.bin / n, body, name=n)
        self.script(self.state / "fakeproc.sh", FAKEPROC)
        self.script(self.state / "provision.sh", PROVISION_STUB)
        for img, text in CONSOLES.items():
            self.set("console-" + img, text)
        self.set("uid", "1000\n")
        self.set("my_groups", "%s adm sudo kvm\n" % LOGIN)
        self.set("lsblk", LSBLK)
        self.set("findmnt", MOUNTS)
        self.set("units", "user@1000.service loaded active running User Manager for UID 1000\n"
                          "session-3.scope loaded active running Session 3 of User %s\n" % LOGIN)
        self.set("ssh_log", "Server listening on :: port 22.\n"
                            "Accepted publickey for %s from 192.0.2.7 port 50000 ssh2: ED25519 SHA256:made-up\n" % LOGIN)
        self.set("tegrastats", TEGRA_IDLE)
        self.set("ring_out", RING_OUT)
        self.set("subv_out", SUBV_OUT)
        self.set("pubbad_out", PUBBAD_OUT)
        self.set("fma_out", FMA_OUT)
        self.set("llama_stdout", LLAMA_OUT)
        self.set("llama_stderr", LLAMA_ERR)

    def script(self, path, body, name=None):
        text = (HEAD + body).replace("@S@", _fwd(self.state)).replace("@NAME@", name or "").replace("@MARKER@", MARKER)
        text = text.replace("@SLEEP@", self.tools["sleep"]).replace("@DATE@", self.tools["date"])
        text = text.replace("@PROC@", _fwd(self.proc)).replace("@RUN@", _fwd(self.run_root)).replace("@TMP@", self.TMP)
        _put(path, text, 0o755)

    def write_manifests(self):
        """The two manifests the runner reads by path: the images', as lines of the backup's own
        list (a hash and a path, the image named by its last component), and the deploy's."""
        _put(self.G + "/images.sha256", "".join("%s  ./output/%s\n" % (_sha(self.IMG + "/" + n), n) for n in IMAGES))
        lines = []
        for d, _dirs, names in os.walk(self.REPO):
            for n in sorted(names):
                p = os.path.join(d, n)
                lines.append("%s  %s\n" % (_sha(p), os.path.relpath(p, self.REPO).replace(os.sep, "/")))
        _put(self.G + "/deploy.sha256", "".join(sorted(lines)))

    def drop_from_deploy_list(self, *paths):
        """The deploy's manifest without the lines of the paths given: files that are deployed, and
        that nothing holds to the deployed commit."""
        man = self.home / "gate2" / "deploy.sha256"
        lines = man.read_bytes().decode().splitlines(True)
        kept = [l for l in lines if l.split(None, 1)[1].strip() not in paths]
        assert len(kept) == len(lines) - len(paths), "the made-up deploy lists each of %s once" % (paths,)
        man.write_bytes("".join(kept).encode())

    def norm(self, text):
        """What a stub recorded, with the home written as these tests write it. A bash on Windows
        rewrites HOME into its own form (a drive path, or a path under its /tmp), and hands that
        form on in everything it derives from HOME."""
        ours, its = self.tools["base"]
        return text.replace(its, ours) if its and its != ours else text

    def set(self, name, text):
        _put(self.state / name, text)

    def unset(self, name):
        p = self.state / name
        if p.exists():
            p.unlink()

    def get(self, name):
        p = self.state / name
        return p.read_bytes().decode() if p.exists() else None

    def env(self, **env):
        e = dict(os.environ, HOME=self.H, PATH=_fwd(self.bin) + os.pathsep + os.environ.get("PATH", ""),
                 SYS_ROOT=_fwd(self.sys), PROC_ROOT=_fwd(self.proc), RUN_ROOT=_fwd(self.run_root),
                 SHM_ROOT=self.SHM, TMP_ROOT=self.TMP, GATE2_PROVISION=_fwd(self.state / "provision.sh"),
                 USER=LOGIN, LOGNAME=LOGIN, LANG="C.UTF-8")
        for k in ("GATE2_GPU_OWNER_PRESENT", "PROVISION_ALLOW_REMOVABLE", "GATE2_NEW_BOOT", "GATE2_FRESH_CURSOR",
                  "GATE2_MANIFEST", "GATE2_DEPLOY_MANIFEST", "LC_ALL", "LD_LIBRARY_PATH", "GGML_CUDA_ENABLE_UNIFIED_MEMORY"):
            e.pop(k, None)
        e.update(env)
        return e

    def run(self, *steps, **env):
        calls = self.state / "calls.log"
        if calls.exists():
            calls.unlink()
        for p in list(self.state.glob("launch-*.env")) + list(self.state.glob("launch-*.argv")):
            p.unlink()
        r = subprocess.run([BASH, self.runner, *steps], capture_output=True, text=True, timeout=300, env=self.env(**env),
                           stdin=self.stdin)
        r.calls = calls.read_bytes().decode().splitlines() if calls.exists() else []
        r.out = r.stdout.replace("\r\n", "\n")
        r.err = r.stderr.replace("\r\n", "\n")
        r.log = self.log()
        for line in r.log:
            assert LINE.match(line), "gate2.log holds only '<step> PASS' and '<step> FAIL <check>': %r" % line
        return r

    def log(self):
        p = self.home / "gate2" / "gate2.log"
        return p.read_bytes().decode().splitlines() if p.is_file() else []

    def attempts(self, step):
        """The attempt directories of a step, oldest first."""
        d = self.home / "gate2" / "out" / step
        return sorted(p for p in d.iterdir()) if d.exists() else []

    def attempt(self, step):
        dirs = self.attempts(step)
        assert len(dirs) == 1, "%s: %d attempt directories" % (step, len(dirs))
        return dirs[0]

    def dump(self, name):
        """A stub's record of the environment it was given, without what a bash has by itself."""
        text = self.get(name)
        assert text is not None, "%s was never written: the stub did not run" % name
        d = {}
        for line in text.replace("\r\n", "\n").split("\n"):
            k, eq, v = line.partition("=")
            if eq and k not in self.tools["auto"] and k not in ("PWD", "SHLVL", "_", "OLDPWD"):
                d[k] = self.norm(v)
        return d

    def argv(self, name):
        text = self.get(name)
        assert text is not None, "%s was never written: the stub did not run" % name
        return [self.norm(a) for a in text.replace("\r\n", "\n").split("\n")[:-1]]

    def passthrough(self):
        """What reaches every command of a row besides the row's own variables: the session's
        HOME, PATH, login and locale, and nothing else of the runner's environment."""
        return {"HOME": self.H, "USER": LOGIN, "LOGNAME": LOGIN, "LANG": "C.UTF-8"}

    def kill_all(self):
        pids = (self.get("pids") or "").split() + (self.get("helper_pids") or "").split()
        if pids:
            subprocess.run([BASH, "-c", "kill -KILL %s 2>/dev/null; exit 0" % " ".join(pids)], timeout=60)

    def alive(self):
        """The made-up guests and servers that are still running."""
        pids = (self.get("pids") or "").split()
        if not pids:
            return []
        out = _bash_out("for p in %s; do if kill -0 $p 2>/dev/null; then echo $p; fi; done" % " ".join(pids))
        return out.split()

    def tree(self, top):
        out = {}
        for d, _dirs, names in os.walk(str(top)):
            for n in names:
                p = os.path.join(d, n)
                out[os.path.relpath(p, str(top)).replace(os.sep, "/")] = _sha(p)
        return out


@pytest.fixture
def board(tmp_path, tools):
    b = Board(tmp_path / "b", tools)
    yield b
    b.kill_all()


def row_env(b, dump):
    """The variables a row's command was given, beyond what every command of a row gets."""
    d = b.dump(dump)
    base = b.passthrough()
    assert "PATH" in d, "the command keeps the session's PATH"
    for k, v in base.items():
        assert d.get(k) == v, "%s reaches the command as the session has it" % k
    return {k: v for k, v in d.items() if k not in base and k != "PATH"}


def harness_calls(r):
    return [c for c in r.calls if c.startswith(("harness ", "launcher ", "fma ", "llama-cli", "subv", "pubbad", "qemu-system-aarch64 "))]


def refused(r, step, why):
    """The step was refused: its line says so, and nothing of it ran."""
    assert "%s FAIL refused-%s" % (step, why) in r.log, (r.log, r.out[-1500:])
    assert r.returncode == 2, (r.returncode, r.out[-800:])


GPU = GPU_OWNER


# ------------------------------------------------------------------ the script's text

def _text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def _code(text):
    """The script without its comments: full-line comments and a trailing ` # ...` are dropped."""
    lines = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s#\s.*$", "", line))
    return "\n".join(lines)


def _cmds(code):
    """The code with every quoted string emptied, so that what a message says is not taken for a
    command."""
    return re.sub(r"'[^'\n]*'", "''", re.sub(r'"[^"\n]*"', '""', code))


def test_the_runner_is_there_with_its_header_and_one_function_per_step():
    text = _text(SCRIPT)
    assert text.startswith("#!/usr/bin/env bash\n") and "\r" not in text
    assert re.search(r"^# Phase \d", text, re.M), "the header carries its Phase tag"
    code = _code(text)
    assert re.findall(r"(?m)^step_(G\d+)\(\) \{", code) == STEPS, "one function per step, G0 to G21, in order"
    for must in ("WHAT A PASS DOES NOT SHOW", "not a QNX-supported configuration", "GATE2_GPU_OWNER_PRESENT=1",
                 "PROVISION_ALLOW_REMOVABLE=1"):
        assert must in text, must


def test_the_script_text_holds_no_sha256_of_an_image():
    """The image hashes are in a local file on the board, read by path: hashes of QNX-derived
    images do not go into a public script. Nor into the library, nor into this file."""
    for path in (SCRIPT, LIB, os.path.abspath(__file__)):
        assert not re.search(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])", _text(path)), path
    code = _code(_text(SCRIPT))
    assert 'MANIFEST="${GATE2_MANIFEST:-$G/images.sha256}"' in code
    assert 'DEPLOY_MANIFEST="${GATE2_DEPLOY_MANIFEST:-$G/deploy.sha256}"' in code


def test_the_stick_rule_is_sourced_and_the_runner_holds_no_copy_of_it():
    code = _code(_text(SCRIPT))
    assert re.findall(r"(?m)^\s*(?:\.|source)\s+(\S+)", code) == ['"$here/lib-stick.sh"'], "one file is sourced: the shared rule"
    for word in ("lsblk", "findmnt", "backing_file", "/media", "first_line()"):
        assert word not in code, "%r is the library's" % word
    # The override is the one the provisioning script has, read by the library and by nothing here.
    assert "PROVISION_ALLOW_REMOVABLE" not in code and "GATE2_ALLOW_REMOVABLE" not in _text(SCRIPT)
    asked = re.findall(r"(?m)^\s*stick_rule\b.*$", code)
    assert len(asked) == 1 and asked[0].strip() == 'stick_rule "every step that creates a KVM VM"', "the rule is asked in one place: %s" % asked
    # A file of that name that is not the rule ends the call before anything: the source's own
    # status, and both functions by name.
    assert '\n. "$here/lib-stick.sh" || {' in code and "\ndeclare -F stick_rule first_line > /dev/null || {" in code


def test_every_reason_is_a_checks_name_and_never_a_number_or_a_verdict_word():
    """What can follow FAIL in the log is fixed in the text: lowercase words joined by hyphens."""
    code = _code(_text(SCRIPT))
    cmds = _cmds(code)
    # Every place a name is given: a failed check, an item left wrong, a refusal.
    given = re.findall(r"(?<![\w-])(?:fail|wrong) +([^\s;]+)", cmds) + re.findall(r"\bturn_away \S+ ([^\s;]+)", cmds)
    given += re.findall(r"\b(?:REFUSAL|WHY_NOT|why)=([^\s;]+)", cmds)
    names = set(n for n in given if n not in ('""', "$1", "{"))
    assert len(names) > 60, sorted(names)
    for n in sorted(names):
        assert re.match(r"^[a-z]+(-[a-z]+)*$", n), "%r is not a check's name" % n
        assert n.upper() not in VERDICT_WORDS and n not in ("pass", "fail", "ok"), n
    # A name is never made up at run time, but for a refusal: "refused-" and a name from above.
    assert re.findall(r"\bturn_away \S+ (\S+)", cmds).count('""') == 1 and 'turn_away "$step" "$why"' in code
    assert 'record "$1" "refused-$2"' in code and code.count("refused-") == 1
    # And the one place that writes the log holds anything else out, whatever a caller hands it.
    body = re.search(r"\nrecord\(\) \{.*?\n(.*?)\n\}\n", code, re.S).group(1)
    assert '[[ "$why" =~ ^[a-z]+(-[a-z]+)*$ ]] || why=malformed-reason' in body
    assert code.count('>> "$GLOG"') == 1 and '>> "$GLOG"' in body, "one writer of gate2.log"
    assert "> \"$GLOG\"" not in code.replace('>> "$GLOG"', ""), "appended to, never rewritten"


def test_the_runner_reads_no_predictions_verdict():
    """It applies the checks and completeness. The words a report scores a prediction with are in
    no pattern it matches."""
    code = _code(_text(SCRIPT))
    for word in ("HELD", "PARTIAL", "REFUTED", "VOID"):
        assert word not in code, "%s is a verdict word, and the runner reads none" % word
    # What it does read of a prediction's line is only that the report left it unscored.
    assert sorted(set(re.findall(r'predictions_say "\$A/run\.log" "([^"]+)"', code))) == ["-> UNSCORED (", "-> not scored ("]


def test_the_runner_asks_nothing_that_names_the_machine_and_changes_little():
    code = _code(_text(SCRIPT))
    cmds = _cmds(code)
    for word in ("hostname", "uname", "nmcli", "ifconfig", "machine-id", "loginctl", "dmesg", "hostnamectl", "ssid", "SSID"):
        assert word not in cmds, word
    assert not re.search(r"(^|[\s;(|&])ip\s", cmds, re.M), "ip is never called"
    # journalctl: the kernel's lines and the ssh units', always as bare messages.
    j = re.findall(r"journalctl ([^|)\n]*)", cmds)
    assert len(j) == 5, j
    for site in j:
        assert " -o cat " in site + " " or " -n 0 " in site, "journalctl without -o cat prints the host's name: %s" % site
        assert "-k " in site or "-u ssh -u sshd " in site, site
    # systemd is asked two things and told nothing.
    assert re.findall(r"\bsystemctl +(\S+)", cmds) == ["list-units", "show"]
    for word in ("set-property", "daemon-reload", "isolate", "restart", "reboot", "shutdown", "poweroff", "kexec", "modprobe",
                 "apt-get", "apt ", "nvpmodel", "scaling_governor\" >", "tee ", "sed -i", "eval ", "docker", "usermod"):
        assert word not in cmds, "%r has a code path" % word
    # Everything it runs through sudo, by name; and sudo is never asked for a password.
    assert "sudo" not in re.sub(r"\bsudo -n |\bsudo_lists_nothing\b", "", cmds), "every sudo is sudo -n"
    assert sorted(set(re.findall(r"\bsudo -n (\S+)", cmds))) == ['""', "journalctl", "sh", "udevadm"]
    assert 'out=$(sudo -n "$@" 2>/dev/null < /dev/null) || return 1' in code, "the one sudo that takes its command from its caller"
    assert re.findall(r"\bsudo_lists_nothing (\w+ [^\s;]+)", cmds) == ["ls -A", "ls -A", "cat \"\""], "and its callers only list and read"
    assert re.findall(r"sudo -n sh -c '([^']*)'", code) == ['echo 3 > "$1"'], "the one thing written as root: the page cache drop"
    assert re.findall(r"sudo -n udevadm (\w+ \S+)", cmds) == ["control --start-exec-queue"], "the queue is released, and udevd is never restarted"
    assert re.findall(r"\budevadm (\w+)", cmds) == ["settle", "control"]
    # What it removes and moves: the last guest's four leftovers, its own cursor file when a fresh
    # one is asked for, and the ladder's native monitor.
    assert re.findall(r"(?m)^\s*rm (.*)$", code) == ['-f "$IVSHMEM_SERVER" "$IVSHMEM_SERVER.ready" "$KICK_SOCK" "$IVSHMEM"',
                                                     '-f "$STATE/cursor"', '-f "$STATE/cursor"']
    assert re.findall(r"\bmv (.*?)(?: \|\||;|$)", code, re.M) == ['"$mon" "$mon.source-sha256" "$dest/"', '"$mon" "$dest/"']
    assert "rm -r" not in code and "rmdir" not in code, "no attempt directory is ever deleted"
    # Every output redirection goes into the attempt's or the call's own directory, to its two
    # state files, to the log, or nowhere.
    targets = set(t.rstrip(");'") for t in re.findall(r"(?<![<&\d-])\d?>>?\s*(\S+)", code))
    allowed = {'"$GLOG"', "/dev/null", "&2", "&1", '"$STATE/cursor"', '"$STATE/boot-id"', '"$STATE/nvmap-workaround"', '"$1"',
               '"$pre.stdout"', '"$pre.stderr"', '"$dir/kernel-new.log"', '"$dir/kernel-err.log"', '"$SESSION/deploy-check.log"',
               '"$SESSION/provision-check.log"'}
    stray = sorted(t for t in targets if t not in allowed and not re.match(r'^"\$A/[\w.-]+"$', t))
    assert stray == [], stray
    # "$1" is the page cache's file under the /proc root, and the file kernel_peek is given, in the attempt.
    assert code.count('> "$1"') == 2 and "kernel_peek \"$A/kernel-during.log\"" in code


def test_the_default_roots_and_the_rows_fixed_names():
    code = _code(_text(SCRIPT))
    for line in ('SYSR="${SYS_ROOT:-/sys}"', 'PROC="${PROC_ROOT:-/proc}"', 'RUNR="${RUN_ROOT:-/run}"', 'SHMR="${SHM_ROOT:-/dev/shm}"',
                 'TMPR="${TMP_ROOT:-/tmp}"', 'G="$HOME/gate2"', 'REPO="$G/repo"', 'R="$REPO/orin-native/gpu-concurrency"',
                 'E="$REPO/orin-native/edge-llm"', 'O="$G/out"', 'IMG="$HOME/output"', 'GLOG="$G/gate2.log"',
                 'IVSHMEM="$SHMR/a6-ivshmem"', 'IVSHMEM_SERVER="$TMPR/a6-ivshmem.sock"', 'KICK_SOCK="$TMPR/a6-kick.sock"',
                 'PROVISION="${GATE2_PROVISION:-$here/provision-orin-r39.sh}"'):
        assert "\n" + line + "\n" in code, line
    # A command of a row gets an emptied environment, the session's few, and the row's own.
    assert "ROW=(env -i " in code and code.count("env -i") == 1
    assert '\nPASS_NAMES="HOME PATH LD_LIBRARY_PATH USER LOGNAME LANG LC_ALL"\n' in code
    # The bounds the rows give, and the two of the runner's own (the dump, one tegrastats line).
    assert re.findall(r"\btimeout (\d+) (\S+)", code) == [
        ("20", "qemu-system-aarch64"), ("30", '"$DDS/bin/subv"'), ("40", '"$DDS/bin/pubbad"'), ("3", "tegrastats"),
        ("180", '"$HOME/llama.cpp/build/bin/llama-cli"')]
    # The stop pattern, as the plan has it: a plain "oops" would match the ramoops lines.
    assert "\nSTOP_PATTERN='Internal error|Unable to handle|BUG:|WARNING:|Call trace|Oops:'\n" in code


# ------------------------------------------------------------------ usage

@needs_bash
@pytest.mark.parametrize("args", [(), ("G22",), ("G5", "g6"), ("G5", "--force"), ("all",)],
                         ids=["none", "no-such-step", "lower-case", "an-option", "all"])
def test_a_call_that_names_no_step_or_an_unknown_one_is_a_usage_error_before_anything_runs(board, args):
    r = board.run(*args)
    assert r.returncode == 64, (r.returncode, r.out, r.err)
    assert "usage: bash gate2-smoke.sh STEP..." in r.err
    assert r.calls == [] and r.log == [] and not (board.home / "gate2" / "out").exists()


@needs_bash
@pytest.mark.parametrize("args", [("G5 G6",), ("G1 G2 G3",), ("G18 G19",), ("G0", "G5 G6"), ("G5 ",), (" G5",), ("G5", ""), ("G05",),
                                  ("G5,G6",), ("G",)],
                         ids=["two-in-one", "three-in-one", "two-gpu-steps-in-one", "one-then-two-in-one", "a-space-after", "a-space-before",
                              "an-empty-one", "a-leading-zero", "a-comma", "no-number"])
@pytest.mark.parametrize("env", [{}, GPU_OWNER], ids=["", "owner-present"])
def test_an_argument_is_exactly_one_step_or_the_call_is_a_usage_error(board, args, env):
    """Several steps in one quoted argument (a caller's "$STEPS") are not a step. Nothing is run,
    no directory is made, and above all no line is written: a line that begins with two steps'
    ids and ends in PASS would be read as the second one's."""
    r = board.run(*args, **env)
    assert r.returncode == 64, (r.returncode, r.out, r.err)
    assert "not a step" in r.err and "usage: bash gate2-smoke.sh STEP..." in r.err
    assert r.calls == [] and r.log == [], (r.calls, r.log)
    assert not (board.home / "gate2" / "out").exists() and not (board.home / "gate2" / "gate2.log").exists()


@needs_bash
@pytest.mark.parametrize("args", [("-h",), ("G5", "--help")])
def test_help_prints_the_usage_and_runs_nothing(board, args):
    r = board.run(*args)
    assert r.returncode == 0 and "usage: bash gate2-smoke.sh STEP..." in r.out and r.calls == [] and r.log == []


@needs_bash
def test_the_runner_refuses_to_run_as_root(board):
    board.set("uid", "0\n")
    r = board.run("G5")
    assert r.returncode == 2 and "never as root" in r.err
    assert r.calls == ["id -u"] and r.log == []


# ------------------------------------------------------------------ every step runs its row's command

def _launch_env(b, n, image, extras):
    got = row_env(b, "launch-%d.env" % n)
    want = dict(extras, IFS_BIN=b.IMG + "/" + image, DISK=b.IMG + "/disk-qemu")
    log = got.pop("LOG")
    assert got == want, (got, want)
    assert b.argv("launch-%d.argv" % n) == [], "the launcher takes no argument"
    return log


def _harness(b, name, **want):
    got = row_env(b, "harness-%s.env" % name)
    assert got == want, (name, got, want)
    assert b.argv("harness-%s.argv" % name) == [], "the harness takes no argument: its settings are its environment"


# Noise in the runner's own environment: none of it may reach a row's command.
NOISE = dict(N="7", K="99", WARMUP="1", CSTATE="", SMOKE="0", R="9", IMG_B="/nowhere/x.bin", IFS_BIN="/nowhere/y.bin",
             DISK="/nowhere/disk", LOG="/nowhere/log", OUT="/nowhere/out", CONSOLE="/nowhere/console", LOCK="/nowhere/lock",
             IVSHMEM="/nowhere/shm", IVSHMEM_SERVER="/nowhere/sock", KICK_SOCK="/nowhere/kick", THREAD_NAMES="0",
             VECTORS="2", TEGRA="0", QEMU="/nowhere/qemu", MON="/nowhere/mon", PROBE="/nowhere/probe", IMAGES="/nowhere/img",
             CYCLONEDDS_URI="file:///nowhere", GGML_CUDA_ENABLE_UNIFIED_MEMORY="1", STUB_STRAY="1")


@needs_bash
def test_g0_dumps_the_device_tree_with_the_launchers_options_and_checks_it(board):
    r = board.run("G0", **NOISE)
    assert r.log == ["G0 PASS"] and r.returncode == 0, (r.log, r.out)
    a = _fwd(board.attempt("G0"))
    assert board.argv("qemu.argv") == [
        "-machine", "virt,gic-version=3,dumpdtb=%s/virt.dtb" % a, "-cpu", "host", "-enable-kvm", "-smp", "2", "-m", "1G",
        "-display", "none",
        "-drive", "file=null-co://,if=none,id=drv0,format=raw", "-device", "virtio-blk-device,drive=drv0",
        "-netdev", "user,id=n0", "-device", "virtio-net-device,netdev=n0,mac=52:54:00:11:11:11",
        "-object", "rng-random,filename=/dev/urandom,id=rng0", "-device", "virtio-rng-device,rng=rng0"]
    assert row_env(board, "qemu.env") == {}
    assert "python3 %s/orin-native/tools/check_virt_dtb.py %s/virt.dtb" % (board.REPO, a) in [board.norm(c) for c in r.calls]
    assert not [c for c in r.calls if c.startswith("launcher")], "no guest is launched: QEMU only writes its tree"


@needs_bash
def test_g1_to_g3_share_one_boot_of_the_its_image_and_ring_its_doorbell(board):
    r = board.run("G1", "G2", "G3", **NOISE)
    assert r.log == ["G1 PASS", "G2 PASS", "G3 PASS"] and r.returncode == 0, (r.log, r.out[-2000:])
    assert [c for c in r.calls if c.startswith("launcher")] == ["launcher ifs-its.bin"], "one boot for the three"
    log = _launch_env(board, 0, "ifs-its.bin", dict(board.shmvars, THREAD_NAMES="1"))
    assert log == _fwd(board.attempt("G1")) + "/guest-console.log", "the console is in the attempt's own directory"
    assert ("python3 %s/ivshmem_ring.py --socket %s --count 100 --gap-ms 2 --echo" % (board.R, board.shmvars["IVSHMEM_SERVER"])
            in [board.norm(c) for c in r.calls])
    assert "--json" not in " ".join(r.calls), "the ring's round trips are not kept"
    # Stop, after the last of the three and not before.
    assert r.calls.count("qemu-term") == 1 and r.calls.index("qemu-term") > max(i for i, c in enumerate(r.calls) if c.startswith("python3"))
    assert board.alive() == []
    for step in ("G1", "G2", "G3"):
        assert len(board.attempts(step)) == 1


@needs_bash
@pytest.mark.parametrize("step", ["G2", "G3"])
def test_a_step_of_a_shared_boot_run_by_itself_launches_the_image_itself(board, step):
    r = board.run(step)
    assert r.log == [step + " PASS"], (r.log, r.out[-1500:])
    assert _launch_env(board, 0, "ifs-its.bin", dict(board.shmvars, THREAD_NAMES="1")) == _fwd(board.attempt(step)) + "/guest-console.log"
    assert r.calls.count("qemu-term") == 1 and board.alive() == []


@needs_bash
def test_g4_runs_the_ladder_on_the_kick_image_and_moves_the_native_monitor_away(board):
    r = board.run("G4", **NOISE)
    assert r.log == ["G4 PASS"] and r.returncode == 0, (r.log, r.out[-2000:])
    a = _fwd(board.attempt("G4"))
    assert _launch_env(board, 0, "ifs-kick.bin", board.shmvars) == a + "/guest-console.log"
    _harness(board, "run-ladder.sh", SHM="1", KICK="1", DB="1", UDP_IN_TCP="1", KVM_STATS="1", ARM_C_PORT="7000",
             CSTATE="shallow", K="4", OUT=a + "/raw")
    assert r.calls.index("launcher ifs-kick.bin") < r.calls.index("harness run-ladder.sh ") < r.calls.index("qemu-term")
    # gap 4i: no later ladder finds a binary it did not choose.
    assert not (board.home / "ladder" / "monitor-native").exists() and not (board.home / "ladder" / "monitor-native.source-sha256").exists()
    moved = list((board.home / "gate2" / "bin").glob("*/monitor-native"))
    assert len(moved) == 1 and moved[0].read_bytes() == b"made-up native monitor\n"
    assert (moved[0].parent / "monitor-native.source-sha256").read_bytes() == b"made-up source hash line\n"
    assert moved[0].parent.name == board.attempt("G4").name, "under the attempt's own stamp, so nothing is ever overwritten"


SELF_BOOTING = {
    "G5": ("run-bell.sh", dict(K="2")),
    "G6": ("run-paths.sh", dict(SMOKE="1", K="6")),
    "G7": ("run-mmio.sh", dict(K="6")),
    "G11": ("run-someip0.sh", dict(K="6")),
    "G13": ("run-unmask.sh", dict(K="4")),
    "G14": ("run-bellrobust.sh", dict(R="1")),
    "G15": ("run-trace.sh", dict(K="6")),
}


@needs_bash
@pytest.mark.parametrize("step", [s for s in STEPS if s in SELF_BOOTING])
def test_a_harness_that_boots_its_own_guests_is_given_its_row_and_nothing_else(board, step):
    name, row = SELF_BOOTING[step]
    r = board.run(step, **NOISE)
    assert r.log == [step + " PASS"] and r.returncode == 0, (r.log, r.out[-2000:])
    _harness(board, name, OUT=_fwd(board.attempt(step)) + "/raw", **row)
    assert harness_calls(r) == ["harness %s " % name], "the harness, and no launch of the runner's own"
    assert "sudo -n sh -c echo 3 > \"$1\" _ %s/sys/vm/drop_caches" % _fwd(board.proc) not in r.calls, "no page cache drop outside the GPU tier"


@needs_bash
def test_a_rows_command_gets_the_sessions_few_variables_where_the_session_has_them(board):
    """HOME, PATH, the library path, the login and the locale reach a row's command as the session
    has them, and which of them the session has is said by name. Nothing else does."""
    r = board.run("G5", **NOISE)
    assert r.log == ["G5 PASS"]
    line = [l for l in r.out.split("\n") if l.startswith("a row's command gets, of this session's environment:")]
    assert len(line) == 1 and line[0].split(":")[1].split(" --")[0].split() == ["HOME", "PATH", "USER", "LOGNAME", "LANG"], line
    got = board.dump("harness-run-bell.sh.env")
    assert sorted(got) == ["HOME", "K", "LANG", "LOGNAME", "OUT", "PATH", "USER"], sorted(got)
    r = board.run("G5", LD_LIBRARY_PATH="/made-up/lib", LC_ALL="C", **NOISE)
    got = board.dump("harness-run-bell.sh.env")
    assert got["LD_LIBRARY_PATH"] == "/made-up/lib" and got["LC_ALL"] == "C"
    assert sorted(got) == ["HOME", "K", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "LOGNAME", "OUT", "PATH", "USER"], sorted(got)
    assert "/made-up/lib" not in r.out, "named, and its value not said"


@needs_bash
def test_every_command_of_a_row_has_nothing_on_its_standard_input_whatever_the_runner_has(board):
    """G19's row ends in `< /dev/null` (this build's llama-cli once spun on end-of-input), and the
    same holds for every command the runner starts: a caller that leaves a pipe as the runner's
    input does not hand it on to a harness, a launcher, a peer or a load."""
    board.stdin = subprocess.PIPE                   # a pipe, where the runbook's call has /dev/null
    board.set("tegrastats", TEGRA_BUSY)
    steps = ("G0", "G3", "G5", "G12", "G16", "G18", "G19")
    r = board.run(*steps, **GPU)
    assert r.log == [s + " PASS" for s in steps], (r.log, r.out[-2000:])
    for stub in ("provision", "qemu", "python3-check_virt_dtb.py", "python3-ivshmem_ring.py", "launcher", "run-bell.sh", "liveness-demo.sh",
                 "subv", "pubbad", "fma", "llama-cli"):
        assert board.get("stdin-" + stub) == "/dev/null\n", "%s was given %r" % (stub, board.get("stdin-" + stub))
    # In the text as well: every run of a row's command names its input, the three in the
    # background too (fma, llama-cli, subv). A bash without job control is documented to give a
    # background command /dev/null by itself; it stops doing so once it has run a loop with
    # redirected input, as the runner has long before its first load.
    runs = re.findall(r'(?m)^.*"\$\{ROW\[@\]\}".*$', _code(_text(SCRIPT)))
    assert len(runs) >= 22 and [line for line in runs if "< /dev/null" not in line] == [], runs


@needs_bash
def test_g8_to_g10_share_one_boot_of_the_stamp_image_in_one_session(board):
    r = board.run("G8", "G9", "G10", **NOISE)
    assert r.log == ["G8 PASS", "G9 PASS", "G10 PASS"] and r.returncode == 0, (r.log, r.out[-2500:])
    assert [c for c in r.calls if c.startswith("launcher")] == ["launcher ifs-stamp.bin"]
    console = _launch_env(board, 0, "ifs-stamp.bin", {})
    assert console == _fwd(board.attempt("G8")) + "/guest-console.log"
    for step, name in (("G8", "run-stamp.sh"), ("G9", "run-metal.sh"), ("G10", "run-tick.sh")):
        _harness(board, name, CONSOLE=console, K="4", OUT=_fwd(board.attempt(step)) + "/raw")
    order = [c for c in r.calls if c.startswith(("harness", "launcher", "qemu-term"))]
    assert order == ["launcher ifs-stamp.bin", "harness run-stamp.sh ", "harness run-metal.sh ", "harness run-tick.sh ", "qemu-term"]
    # G9's positive control: the harness's own journal query, over a window that began at boot.
    q = [c for c in r.calls if c.startswith("journalctl -u ssh")]
    assert len(q) == 1 and re.match(r"^journalctl -u ssh -u sshd --since @1700000000 --until @\d+ -o cat$", q[0]), q
    assert "sudo -n " + q[0] in r.calls


@needs_bash
@pytest.mark.parametrize("step, name", [("G9", "run-metal.sh"), ("G10", "run-tick.sh")])
def test_g9_or_g10_by_itself_boots_the_stamp_image_and_stops_it(board, step, name):
    r = board.run(step)
    assert r.log == [step + " PASS"], (r.log, r.out[-1500:])
    console = _launch_env(board, 0, "ifs-stamp.bin", {})
    _harness(board, name, CONSOLE=console, K="4", OUT=_fwd(board.attempt(step)) + "/raw")
    assert console == _fwd(board.attempt(step)) + "/guest-console.log" and r.calls.count("qemu-term") == 1


@needs_bash
def test_g12_runs_the_liveness_demo_on_a_fresh_boot_into_a_directory_that_does_not_exist_yet(board):
    r = board.run("G12", **NOISE)
    assert r.log == ["G12 PASS"], (r.log, r.out[-1500:])
    a = _fwd(board.attempt("G12"))
    assert _launch_env(board, 0, "ifs-live.bin", {}) == a + "/guest-console.log"
    # The demo refuses an OUT that exists, and the attempt's directory exists (the console is in
    # it): OUT is a directory of the demo's own under it.
    _harness(board, "liveness-demo.sh", CONSOLE=a + "/guest-console.log", OUT=a + "/demo")
    assert r.calls.index("harness liveness-demo.sh ") < r.calls.index("qemu-term")


@needs_bash
def test_g16_runs_the_two_dds_peers_against_the_dds_image_under_their_timeouts(board):
    r = board.run("G16", **NOISE)
    assert r.log == ["G16 PASS"], (r.log, r.out[-1500:])
    _launch_env(board, 0, "ifs-dds.bin", {})
    uri = "file://%s/ipc-test/qnx-dds-monitor/cyclonedds-l4t.xml" % board.REPO
    assert row_env(board, "subv.env") == {"CYCLONEDDS_URI": uri} and row_env(board, "pubbad.env") == {"CYCLONEDDS_URI": uri}
    code = _code(_text(SCRIPT))
    assert '-- timeout 30 "$DDS/bin/subv"' in code and '-- timeout 40 "$DDS/bin/pubbad"' in code
    assert "subv " in r.calls and "pubbad " in r.calls, "neither peer takes an argument"
    order = [c.split()[0] for c in r.calls if c.split()[0] in ("launcher", "subv", "pubbad", "qemu-term")]
    assert order[0] == "launcher" and order[-1] == "qemu-term" and sorted(order[1:3]) == ["pubbad", "subv"]


@needs_bash
def test_g17_runs_the_queue_harness_on_a_boot_of_the_stamp_image(board):
    r = board.run("G17", **NOISE)
    assert r.log == ["G17 PASS"], (r.log, r.out[-1500:])
    a = _fwd(board.attempt("G17"))
    assert _launch_env(board, 0, "ifs-stamp.bin", {}) == a + "/guest-console.log"
    _harness(board, "run-queue.sh", CONSOLE=a + "/guest-console.log", K="4", OUT=a + "/raw")
    assert "sudo -n udevadm control --start-exec-queue" not in r.calls, "nothing to release: the harness left the queue running"


@needs_bash
def test_g17_boots_the_stamp_image_afresh_and_does_not_share_g10s_boot(board):
    """G8 to G10 share a boot and end in a Stop; G17's row launches the same image again."""
    r = board.run("G10", "G17")
    assert r.log == ["G10 PASS", "G17 PASS"], (r.log, r.out[-1500:])
    order = [c.strip() for c in r.calls if c.startswith(("harness", "launcher", "qemu-term"))]
    assert order == ["launcher ifs-stamp.bin", "harness run-tick.sh", "qemu-term", "launcher ifs-stamp.bin", "harness run-queue.sh", "qemu-term"]
    a = _fwd(board.attempt("G17"))
    assert _launch_env(board, 1, "ifs-stamp.bin", {}) == a + "/guest-console.log", "its console is its own attempt's, not G10's"
    _harness(board, "run-queue.sh", CONSOLE=a + "/guest-console.log", K="4", OUT=a + "/raw")


@needs_bash
def test_the_gpu_tier_runs_its_four_rows_with_the_owner_present(board):
    board.set("tegrastats", TEGRA_BUSY)
    r = board.run("G18", "G19", "G20", "G21", **dict(NOISE, **GPU))
    assert r.log == ["G18 PASS", "G19 PASS", "G20 PASS", "G21 PASS"] and r.returncode == 0, (r.log, r.out[-3000:])
    # G18: the page cache dropped first, and written down; then fma for five seconds, by name.
    assert [c for c in r.calls if c.startswith("fma")] == ["fma 5 gate2"]
    assert row_env(board, "fma.env") == {}
    drop = "sudo -n sh -c echo 3 > \"$1\" _ %s/sys/vm/drop_caches" % _fwd(board.proc)
    calls = [board.norm(c) for c in r.calls]
    assert calls.index("sync") < calls.index(drop) < calls.index("fma 5 gate2")
    assert (board.proc / "sys" / "vm" / "drop_caches").read_bytes().strip() == b"3"
    assert (board.attempt("G18") / "page-cache-dropped.txt").exists() and (board.attempt("G19") / "page-cache-dropped.txt").exists()
    # G19: the row's command, bounded, with nothing on its standard input.
    assert board.argv("llama.argv") == ["-m", board.H + "/models/SmolVLM-500M-Instruct-Q8_0.gguf", "-ngl", "99", "-n", "16", "-st", "-p", "hello"]
    assert row_env(board, "llama.env") == {}, "the workaround is not set by default (gap 4o)"
    assert 'timeout 180 "$HOME/llama.cpp/build/bin/llama-cli"' in _code(_text(SCRIPT))
    assert calls.count(drop) == 2, "before fma and before llama-cli; the demos drop it themselves"
    # G20 and G21: a guest each, and the row's harness.
    a20, a21 = _fwd(board.attempt("G20")), _fwd(board.attempt("G21"))
    assert _launch_env(board, 0, "ifs-svc.bin", {}) == a20 + "/guest-console.log"
    _harness(board, "vlm-demo.sh", CONSOLE=a20 + "/guest-console.log", OUT=a20, IMAGES=board.H + "/mnist")
    assert _launch_env(board, 1, "ifs-kick.bin", {}) == a21 + "/guest-console.log"
    _harness(board, "run-llm-interference.sh", K="2", OUT=a21 + "/raw")
    assert r.calls.count("qemu-term") == 2 and board.alive() == []


@needs_bash
def test_every_step_in_one_call_passes_on_a_board_where_every_smoke_is_clean(board):
    """All twenty-two in the list's order, and no command that names the machine among what was
    called. (The stub tegrastats says the GPU is busy throughout: the runner reads it only beside
    the two loads of G18 and G19; the harnesses' own idle checks are the harnesses'.)"""
    board.set("tegrastats", TEGRA_BUSY)
    r = board.run(*STEPS, **GPU)
    assert r.log == [s + " PASS" for s in STEPS] and r.returncode == 0, (r.log, r.out[-3000:])
    assert [c for c in r.calls if c.startswith("launcher")] == ["launcher " + i for i in (
        "ifs-its.bin", "ifs-kick.bin", "ifs-stamp.bin", "ifs-live.bin", "ifs-dds.bin", "ifs-stamp.bin", "ifs-svc.bin", "ifs-kick.bin")]
    assert board.alive() == [] and r.calls.count("qemu-term") == 8
    for marker_stub in ("hostname", "uname", "ip", "nmcli", "hostnamectl", "loginctl", "dmesg"):
        assert not [c for c in r.calls if c.split()[0] == marker_stub], "%s names the machine and is never called" % marker_stub
    assert MARKER not in r.out + r.err and not (board.state / "systemctl-changed").exists()
    for p in (board.home / "gate2").rglob("*"):
        if p.is_file():
            assert MARKER.encode() not in p.read_bytes(), "%s holds what a host-naming form of a command prints" % p
    # Every journalctl call asked for bare messages, or for a cursor and no entry at all.
    for c in r.calls:
        if c.startswith("journalctl"):
            assert " -o cat" in c or " -n 0 " in c, c


# ------------------------------------------------------------------ PASS and FAIL

HARNESS_STEPS = {
    "G4": "run-ladder.sh", "G5": "run-bell.sh", "G6": "run-paths.sh", "G7": "run-mmio.sh", "G8": "run-stamp.sh", "G9": "run-metal.sh",
    "G10": "run-tick.sh", "G11": "run-someip0.sh", "G13": "run-unmask.sh", "G14": "run-bellrobust.sh", "G15": "run-trace.sh",
    "G17": "run-queue.sh", "G21": "run-llm-interference.sh",
}


@needs_bash
@pytest.mark.parametrize("step", [s for s in STEPS if s in HARNESS_STEPS])
def test_a_harness_that_exits_non_zero_gives_fail_whatever_it_printed(board, step):
    """The stub prints every line of a clean run and returns 1: the step is FAIL harness-exit."""
    board.set("rc-" + HARNESS_STEPS[step], "1\n")
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\nG20 PASS\n")     # the GPU tier's order, for G21
    r = board.run(step, **GPU)
    assert r.log[-1] == step + " FAIL harness-exit" and r.returncode == 1, (r.log, r.out[-1500:])
    assert board.alive() == [], "a failed step still stops its guest"


@needs_bash
@pytest.mark.parametrize("step, name", [("G12", "liveness-demo.sh"), ("G20", "vlm-demo.sh")])
def test_a_demo_that_exits_non_zero_gives_fail(board, step, name):
    board.set("rc-" + name, "1\n")
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\n")
    r = board.run(step, **GPU)
    assert r.log[-1] == step + " FAIL demo-exit" and r.returncode == 1, (r.log, r.out[-1500:])


def _drop(text, needle):
    """The text without its lines that hold the needle."""
    kept = [l for l in text.split("\n") if needle not in l]
    assert len(kept) < len(text.split("\n")), "nothing held %r" % needle
    return "\n".join(kept)


def _swap(text, old, new):
    assert old in text, old
    return text.replace(old, new, 1)


# One row per line of a pass rule: the step, the stub output with that line gone or wrong, and
# the name of the check that then fails.
MISSING = [
    ("G4", "run-ladder.sh", lambda t: _drop(t, "doorbell proof"), "doorbell-proof"),
    ("G4", "run-ladder.sh", lambda t: _swap(t, '"ok": true', '"ok": false'), "doorbell-proof"),
    ("G4", "run-ladder.sh", lambda t: _drop(t, "complete:"), "complete"),
    ("G4", "run-ladder.sh", lambda t: _swap(t, "x 4 round(s)", "x 2 round(s)"), "complete"),
    ("G5", "run-bell.sh", lambda t: _drop(t, "complete:"), "complete"),
    ("G5", "run-bell.sh", lambda t: _drop(t, "  M3 "), "banner-and-msixcfg"),
    ("G5", "run-bell.sh", lambda t: _swap(t, "monitors serving -> ok", "monitors serving -> FAILED"), "banner-and-msixcfg"),
    ("G6", "run-paths.sh", lambda t: _drop(t, "complete:"), "complete"),
    ("G6", "run-paths.sh", lambda t: _swap(t, "(<= -20) -> UNSCORED (k=6, smoke; the rule is fixed at k = 18)", "(<= -20) -> HELD"),
     "predictions-unscored"),
    ("G6", "run-paths.sh", lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("  P")), "predictions-unscored"),
    ("G7", "run-mmio.sh", lambda t: _drop(t, "  M2 "), "m-checks"),
    ("G7", "run-mmio.sh", lambda t: _swap(t, "(all, and userspace) -> ok", "(all, and userspace) -> FAILED"), "m-checks"),
    ("G8", "run-stamp.sh", lambda t: _drop(t, "window sampler verified"), "sampler-verified"),
    ("G8", "run-stamp.sh", lambda t: _drop(t, "complete:"), "complete"),
    ("G9", "run-metal.sh", lambda t: _drop(t, "  M5 "), "m-checks"),
    ("G9", "run-metal.sh", lambda t: _swap(t, "(want 0) -> ok", "(want 0) -> FAILED"), "m-checks"),
    ("G9", "run-metal.sh", lambda t: _swap(t, "RATIO 7.77 -> not scored (k=4; the prediction is for k=40)", "RATIO 7.77 -> HELD"),
     "predictions-not-scored"),
    ("G10", "run-tick.sh", lambda t: _drop(t, "  M4 "), "m-checks"),
    ("G10", "run-tick.sh", lambda t: _swap(t, "(want all) -> ok", "(want all) -> FAILED"), "m-checks"),
    ("G11", "run-someip0.sh", lambda t: _drop(t, "complete:"), "complete"),
    ("G13", "run-unmask.sh", lambda t: _drop(t, "complete:"), "complete"),
    ("G14", "run-bellrobust.sh",
     lambda t: _swap(t, "    S4 r1 pass", "    S4 r1 VOID (M6 (msixcfg or the MSI-X monitor was never seen during the rings))"), "scenario-checks"),
    ("G14", "run-bellrobust.sh", lambda t: _swap(t, "    S2 r1 pass", "    S2 r1 FAIL (the doubled exchanges)"), "scenario-checks"),
    ("G15", "run-trace.sh", lambda t: _drop(t, "complete:"), "complete"),
    ("G15", "run-trace.sh", lambda t: _swap(t, "<= 2% not cut -> ok", "<= 2% not cut -> FAILED"), "trace-reduces"),
    ("G17", "run-queue.sh", lambda t: _drop(t, "  M3 "), "m-checks"),
    ("G17", "run-queue.sh", lambda t: _swap(t, ">= 3: 4/4 (want >= 90%) -> ok", ">= 3: 0/4 (want >= 90%) -> FAILED"), "m-checks"),
    ("G21", "run-llm-interference.sh", lambda t: _drop(t, "window sampler verified"), "sampler-verified"),
    ("G21", "run-llm-interference.sh", lambda t: _drop(t, "complete:"), "complete"),
]


def _without_scenario(i):
    return lambda t: _drop(t, "    S%d r1" % i)


# G14: each of the eight scenarios' lines, gone in turn.
MISSING += [("G14", "run-bellrobust.sh", _without_scenario(i), "scenario-checks") for i in range(1, 9)]
# A check's line ends in its outcome: "-> ok" with more after it is not the report's ok.
MISSING += [
    ("G5", "run-bell.sh", lambda t: _swap(t, "monitors serving -> ok", "monitors serving -> ok, but for one boot -> FAILED"),
     "banner-and-msixcfg"),
    ("G7", "run-mmio.sh", lambda t: _swap(t, "(all, and userspace) -> ok", "(all, and userspace) -> ok?"), "m-checks"),
]


@needs_bash
@pytest.mark.parametrize("step, name, change, why", MISSING, ids=["%s-%s-%d" % (m[0], m[3], i) for i, m in enumerate(MISSING)])
def test_a_harness_whose_output_lacks_a_line_of_the_pass_rule_gives_fail_though_it_exits_zero(board, step, name, change, why):
    board.set("out-" + name, change(PASS_OUT[name]))
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\nG20 PASS\n")
    r = board.run(step, **GPU)
    assert r.log[-1] == "%s FAIL %s" % (step, why) and r.returncode == 1, (r.log, r.out[-1500:])


@needs_bash
def test_a_check_line_that_is_not_one_of_the_rows_does_not_fail_the_step(board):
    """G9 asks for M1 to M5 and G10 for M1 to M4: a later check that a short run cannot meet
    prints FAILED in the clean output above, and both steps pass."""
    assert "M6 tick-bin tail exchanges 3 (want >= 30) -> FAILED" in PASS_OUT["run-metal.sh"]
    assert "-> FAILED; heavy tick-bin tail" in PASS_OUT["run-tick.sh"]
    r = board.run("G9", "G10")
    assert r.log == ["G9 PASS", "G10 PASS"], (r.log, r.out[-1500:])


@needs_bash
def test_the_log_holds_only_pass_and_fail_lines_and_no_number_or_verdict_word_leaves_the_attempt(board):
    """The stubs print latencies, counts and every verdict word. None of it is in gate2.log, and
    none of it is in what the runner itself prints: it says a check's name and a path."""
    board.set("tegrastats", TEGRA_BUSY)
    board.set("out-run-bell.sh", _swap(PASS_OUT["run-bell.sh"], "monitors serving -> ok", "monitors serving -> FAILED"))
    board.set("rc-run-mmio.sh", "3\n")
    r = board.run(*STEPS, **GPU)
    text = (board.home / "gate2" / "gate2.log").read_bytes().decode()
    assert text.endswith("\n") and len(r.log) == 22 and "G5 FAIL banner-and-msixcfg" in r.log and "G7 FAIL harness-exit" in r.log
    body = re.sub(r"(?m)^G\d+ ", "", text)
    assert not re.search(r"\d", body), "no number after the step's own id: %r" % body
    for word in VERDICT_WORDS + ("not scored", "ok\n"):
        assert word not in text, word
    said = r.out + r.err
    for figure in ("66.60", "77.70", "777.70", "555.5", "0.7770", "777.7", "8.88", "11111", "22222", "55.55", "7.777",
                   "77.7", "+5555.00", "77%", "1111mW", "9/9"):
        assert figure not in said, "%s is a figure of a stub's, and the runner prints none" % figure
    for word in ("HELD", "PARTIAL", "REFUTED", "UNSCORED", "not scored", "ACCEPT", "REJECT"):
        assert word not in said, "%s is a verdict word of a stub's" % word
    # They are where the harness put them: in the attempt's own directory, and only there.
    assert "-66.60 us" in (board.attempt("G5") / "run.log").read_bytes().decode()


@needs_bash
def test_a_reason_that_is_not_a_checks_name_cannot_reach_the_log(board):
    """Driven through the script's own writer: whatever it is handed, the log gets a name."""
    out = _bash_out("set -u; GLOG='%s'; say() { :; }; %s; record G5 'p50 777.7 us HELD'; record G6 ''; record G7 complete; cat \"$GLOG\""
                    % (_fwd(board.root / "x.log"), re.search(r"\nrecord\(\) \{.*?\n\}\n", _text(SCRIPT), re.S).group(0).strip()))
    assert out.split("\n")[:3] == ["G5 FAIL malformed-reason", "G6 PASS", "G7 FAIL complete"], out


@needs_bash
def test_what_begins_a_line_of_the_log_is_one_steps_id_or_no_line_is_written(board):
    """The writer again, driven directly: a line begins with one step's id, G0 to G21, and for
    anything else it writes none, whatever follows would have been."""
    writer = re.search(r"\nrecord\(\) \{.*?\n\}\n", _text(SCRIPT), re.S).group(0).strip()
    out = _bash_out("set -u; GLOG='%s'; say() { :; }; %s; record 'G5 G6' ''; record G22 ''; record G05 complete; record '' ''; "
                    "record 'G5 PASS\nG6' ''; record 'p50 777.7' ''; record G21 ''; record G0 launch; cat \"$GLOG\""
                    % (_fwd(board.root / "y.log"), writer))
    assert out == "G21 PASS\nG0 FAIL launch\n", out


# ------------------------------------------------------------------ the console rules of G1 to G3, and the launch

def _con(image, change):
    return change(CONSOLES[image])


CONSOLE_RULES = [
    ("G1", lambda t: _drop(t, "cpu1: MPIDR="), "cpu-lines"),
    ("G1", lambda t: _drop(t, "cpu0: MPIDR="), "cpu-lines"),
    ("G1", lambda t: _drop(t, "its: msixwait: attached"), "terminal-marker"),
    ("G2", lambda t: _drop(t, "shm configured:"), "shm-configured"),
    ("G2", lambda t: t + "shm: BARs/command did not take (BAR2=0x0000000000000000 BAR0=0x00000000 cmd=0x0000)\r\n", "shmcfg-error"),
    ("G2", lambda t: _drop(t, "its: msixwait: attached"), "terminal-marker"),
    ("G3", lambda t: _drop(t, "LPIs delivered"), "selftest"),
    ("G3", lambda t: _swap(t, "20 LPIs delivered, 0 timeouts", "19 LPIs delivered, 1 timeouts"), "selftest"),
    ("G3", lambda t: _swap(t, "20 LPIs delivered, 0 timeouts", "19 LPIs delivered, 0 timeouts"), "selftest"),
    ("G3", lambda t: _swap(t, "slowest 777 us", "slowest 777 us, with errors"), "selftest"),
    ("G3", lambda t: _drop(t, "its: msixcfg:"), "msixcfg"),
]


@needs_bash
@pytest.mark.parametrize("step, change, why", CONSOLE_RULES, ids=["%s-%s-%d" % (c[0], c[2], i) for i, c in enumerate(CONSOLE_RULES)])
def test_a_console_without_a_line_of_the_rule_gives_fail(board, step, change, why):
    board.set("console-ifs-its.bin", _con("ifs-its.bin", change))
    r = board.run(step)
    assert r.log == ["%s FAIL %s" % (step, why)] and r.returncode == 1, (r.log, r.out[-1500:])
    assert board.alive() == [] and r.calls.count("qemu-term") == 1


@needs_bash
def test_the_steps_that_share_a_boot_each_fail_on_a_terminal_marker_that_never_came(board):
    """G2 and G3 read their rules off the boot G1 launched. Without the image's terminal marker
    on that console neither rule is read: each fails by the marker's name, and no doorbell is rung."""
    board.set("console-ifs-its.bin", _drop(CONSOLES["ifs-its.bin"], "its: msixwait: attached"))
    r = board.run("G1", "G2", "G3")
    assert r.log == ["G1 FAIL terminal-marker", "G2 FAIL terminal-marker", "G3 FAIL terminal-marker"], (r.log, r.out[-1500:])
    assert [c for c in r.calls if c.startswith("launcher")] == ["launcher ifs-its.bin"], "the one boot, kept while its steps follow"
    assert not [c for c in r.calls if c.startswith("python3")] and r.calls.count("qemu-term") == 1 and board.alive() == []


@needs_bash
def test_g1_wants_the_second_vcpu_to_run_and_not_only_a_thread_of_its_name(board):
    """QEMU names both vCPU threads whether or not the guest starts CPU 1: the thread's run time
    has to grow over the second the runner waits."""
    board.set("cpu1_idle", "1\n")
    r = board.run("G1")
    assert r.log == ["G1 FAIL cpu-one-runs"], (r.log, r.out[-1200:])
    assert "7000" not in r.out + r.err, "no value of the run time is said"
    board.unset("cpu1_idle")
    board.set("no_cpu1_thread", "1\n")
    assert board.run("G1").log[-1] == "G1 FAIL cpu-one-runs", "no thread of that name at all"
    board.unset("no_cpu1_thread")
    r = board.run("G1")
    assert r.log[-1] == "G1 PASS" and "sleep 1" in r.calls, "one second between the two reads"


@needs_bash
@pytest.mark.parametrize("ring, rc, why", [
    (RING_OUT.replace("100 echoed, 0 timed out", "97 echoed, 3 timed out"), "1", "ring-echo"),
    (RING_OUT.replace("100 echoed, 0 timed out", "97 echoed, 0 timed out"), "0", "ring-echo"),
    (RING_OUT, "1", "ring-echo"),
    ("ring: joined as peer 2\n", "0", "ring-echo"),
], ids=["timeouts", "fewer-echoes", "non-zero-exit", "no-count-line"])
def test_g3_wants_every_ring_echoed(board, ring, rc, why):
    board.set("ring_out", ring)
    board.set("ring_rc", rc + "\n")
    assert board.run("G3").log == ["G3 FAIL " + why]


@needs_bash
def test_g0_fails_by_name_when_qemu_or_the_tool_does(board):
    board.set("qemu_rc", "1\n")
    assert board.run("G0").log == ["G0 FAIL qemu-dumpdtb"]
    board.unset("qemu_rc")
    board.set("qemu_no_dtb", "1\n")
    assert board.run("G0").log[-1] == "G0 FAIL dtb-written"
    board.unset("qemu_no_dtb")
    board.set("dtbcheck_rc", "1\n")
    board.set("dtbcheck_out", "MISMATCH: ECAM base 0x4010000000 against 0x3f000000\n")
    r = board.run("G0")
    assert r.log[-1] == "G0 FAIL dtb-check" and "0x3f000000" not in r.out, (r.log, r.out)


@needs_bash
def test_a_terminal_marker_that_comes_late_is_waited_for_and_one_that_never_comes_is_given_up_on(board):
    """The launcher returns when :7100 answers, before the image's later start-up lines: the
    rules are read only once the image's terminal marker is on the console, within a bound."""
    full = CONSOLES["ifs-its.bin"]
    marker = [l for l in full.split("\n") if "its: msixwait: attached" in l][0] + "\n"
    board.set("console-ifs-its.bin", full.replace(marker, ""))
    # The marker reaches the console after a few of the runner's sleeps.
    board.set("late", marker)
    board.set("on_sleep", 'n=0; [ -e "$S/slept" ] && read -r n < "$S/slept"; n=$((n + 1)); echo "$n" > "$S/slept"\n'
                          'if [ "$n" = 5 ]; then for f in \'%s\'/gate2/out/G*/*/guest-console.log; do cat "$S/late" >> "$f"; done; fi\n' % board.H)
    r = board.run("G1")
    assert r.log == ["G1 PASS"], (r.log, r.out[-1200:])
    board.unset("on_sleep")
    r = board.run("G1")
    assert r.log[-1] == "G1 FAIL terminal-marker", r.log
    waits = [c for c in r.calls if c == "sleep 1"]
    assert 55 <= len(waits) <= 70, "a bounded wait of about a minute, in steps of a second: %d" % len(waits)


MARKS = [
    ("G4", "ifs-kick.bin", "serving shm on ivshmem"), ("G4", "ifs-kick.bin", "serving shm-kick"),
    ("G8", "ifs-stamp.bin", "stamping replies on :7103"), ("G12", "ifs-live.bin", "liveness deadline"),
    ("G16", "ifs-dds.bin", "waiting for claims"), ("G17", "ifs-stamp.bin", "stamping replies on :7103"),
    ("G20", "ifs-svc.bin", "listening on :7102"), ("G21", "ifs-kick.bin", "listening on :7100"),
]


@needs_bash
@pytest.mark.parametrize("step, image, line", MARKS, ids=["%s-%d" % (m[0], i) for i, m in enumerate(MARKS)])
def test_every_image_the_runner_launches_is_waited_for_until_its_last_start_up_line(board, step, image, line):
    """The line the step's harness looks for on the console, or the service it is about to
    use, is not there when :7100 first answers. Without it within the wait, nothing is run
    against the guest."""
    board.set("console-" + image, _drop(CONSOLES[image], line))
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\nG20 PASS\n")
    r = board.run(step, **GPU)
    assert r.log[-1] == step + " FAIL terminal-marker" and r.returncode == 1, (r.log, r.out[-1200:])
    assert not [c for c in r.calls if c.startswith(("harness", "subv", "pubbad"))], "nothing was run against a guest that is not ready"
    assert r.calls.count("qemu-term") == 1 and board.alive() == []


@needs_bash
@pytest.mark.parametrize("flag", ["launch_times_out", "launch_refuses", "launch_names_no_pid", "launch_never_says_up"])
def test_a_launch_that_fails_gives_fail_and_a_qemu_it_left_behind_is_stopped(board, flag):
    """The launcher that gives up waiting for the guest leaves its QEMU running: the runner stops
    the QEMU the launcher named, with a sync first, and the step fails by name. A launcher that
    returns 0 and names its QEMU without its "guest up" line has not said that :7100 answered."""
    board.set(flag, "1\n")
    r = board.run("G12")
    assert r.log == ["G12 FAIL launch"], (r.log, r.out[-1200:])
    assert not [c for c in r.calls if c.startswith("harness")], "nothing is run against a guest that did not come up"
    if flag in ("launch_times_out", "launch_never_says_up"):
        assert r.calls.count("qemu-term") == 1 and r.calls.index("sync") < r.calls.index("qemu-term")
        assert board.alive() == []
    if flag == "launch_names_no_pid":
        # A QEMU nobody named is not signalled; the check after the step finds it, and says so:
        # in the call's output and by its exit status, the step being the call's last.
        assert "qemu-term" not in r.calls and board.alive() != []
        assert "REFUSED from here on: leftover-process." in r.out and r.returncode == 2, (r.returncode, r.out[-600:])
    else:
        assert r.returncode == 1, (r.returncode, r.out[-600:])


# ------------------------------------------------------------------ Stop

@needs_bash
def test_sync_is_called_before_the_guest_is_stopped_and_again_after(board):
    r = board.run("G12")
    assert r.log == ["G12 PASS"]
    i = r.calls.index("qemu-term")
    before, after = r.calls[:i], r.calls[i + 1:]
    assert "sync" in before and before.index("sync") > before.index("harness liveness-demo.sh "), "a sync between the smoke and the TERM"
    assert "sync" in after, "and one when the guest has gone"
    # The step's line is in the log, and so flushed, before the guest is stopped.
    assert "G12 PASS" in r.out and r.out.index("G12 PASS") < r.out.index("stopping the guest")


@needs_bash
def test_stop_waits_for_the_ivshmem_server_and_then_removes_the_leftover_sockets(board):
    board.set("server_lingers", "4\n")              # the server outlives its QEMU by a few of its own sleeps
    r = board.run("G4")
    assert r.log == ["G4 PASS"], (r.log, r.out[-1500:])
    assert "server-exit sockets-present" in r.calls, "the sockets were still there when the server went: it was waited for"
    for p in (board.tmp / "a6-ivshmem.sock", board.tmp / "a6-ivshmem.sock.ready", board.tmp / "a6-kick.sock", board.shm / "a6-ivshmem"):
        assert not p.exists(), "%s is a leftover the launcher would refuse to start over" % p.name
    assert board.alive() == []


@needs_bash
def test_a_server_that_does_not_exit_is_left_with_its_sockets_and_the_next_step_is_refused(board):
    board.set("server_stays", "1\n")
    r = board.run("G4", "G5")
    assert r.log == ["G4 PASS", "G5 FAIL refused-leftover-process"] and r.returncode == 2, (r.log, r.out[-1500:])
    assert (board.tmp / "a6-ivshmem.sock").exists(), "nothing is removed under a server that is still there"
    assert "ivshmem_server.py" in r.out and not [c for c in r.calls if c.startswith("harness run-bell.sh")]
    waits = [c for c in r.calls if c == "sleep 0.5"]
    assert len(waits) >= 20, "the server was waited for"


@needs_bash
def test_the_last_guests_server_of_a_harness_that_boots_its_own_is_waited_for_before_the_check(board):
    """run-bell.sh stops its last guest itself and returns, and that guest's ivshmem server is
    still on its way out. It is waited for as Stop waits, its sockets go after it, and the next
    step is not refused over a server that was about to leave."""
    board.set("server_lingers", "4\n")
    board.set("post-run-bell.sh", POST_LAT + (
        ": > '%(tmp)s/a6-ivshmem.sock'; : > '%(tmp)s/a6-kick.sock'; : > '%(shm)s/a6-ivshmem'\n"
        'bash "$S/fakeproc.sh" server $$ > /dev/null 2>&1 < /dev/null &\n'
        "echo \"$!\" > '%(tmp)s/a6-ivshmem.sock.ready'; echo \"$!\" >> \"$S/pids\"\n"
        'echo "$! python3 /made-up/gpu-concurrency/ivshmem_server.py --socket /made-up/a6-ivshmem.sock" >> "$S/procs"\n'
        % {"tmp": board.TMP, "shm": board.SHM}))
    r = board.run("G5", "G6")
    assert r.log == ["G5 PASS", "G6 PASS"], (r.log, r.out[-1500:])
    assert "server-exit sockets-present" in r.calls, "nothing was removed under the server"
    for p in (board.tmp / "a6-ivshmem.sock", board.tmp / "a6-ivshmem.sock.ready", board.tmp / "a6-kick.sock", board.shm / "a6-ivshmem"):
        assert not p.exists(), "%s is a leftover the launcher would refuse to start over" % p.name
    assert board.alive() == []


@needs_bash
def test_a_qemu_that_ignores_term_is_killed(board):
    board.set("qemu_ignores_term", "1\n")
    r = board.run("G12", "G5")
    assert r.log == ["G12 PASS", "G5 PASS"], (r.log, r.out[-1500:])
    assert "qemu-term-ignored" in r.calls and board.alive() == []


@needs_bash
def test_the_runner_survives_the_loss_of_whoever_reads_its_output(board):
    """Started as the runbook says, its output is a file. If it is a pipe and the reader goes
    away, the runner still stops its guest and still writes its line."""
    p = subprocess.Popen([BASH, SCRIPT, "G12"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         env=board.env())
    p.stdout.readline()
    p.stdout.close()                                # the reader is gone after the first line
    assert p.wait(timeout=300) in (0, 1, 2)
    assert board.log() == ["G12 PASS"], board.log()
    deadline = time.time() + 20
    while board.alive() and time.time() < deadline:
        time.sleep(0.2)
    assert board.alive() == []
    calls = (board.state / "calls.log").read_bytes().decode().splitlines()
    assert calls.index("sync") < calls.index("qemu-term")


# ------------------------------------------------------------------ one directory per attempt

@needs_bash
def test_a_second_attempt_writes_to_a_new_directory_and_leaves_the_first_untouched(board):
    board.set("date_utc", "20261005T010203Z\n")
    board.set("rc-run-bell.sh", "1\n")
    r = board.run("G5")
    first = board.attempt("G5")
    assert first.name == "20261005T010203Z" and r.log == ["G5 FAIL harness-exit"]
    before = board.tree(first)
    assert "raw/lat-x_r1.json" in before and "run.log" in before
    board.set("date_utc", "20261005T010309Z\n")
    board.unset("rc-run-bell.sh")
    r = board.run("G5")
    assert r.log == ["G5 FAIL harness-exit", "G5 PASS"], (r.log, r.out[-1200:])
    dirs = board.attempts("G5")
    assert [d.name for d in dirs] == ["20261005T010203Z", "20261005T010309Z"]
    assert board.tree(first) == before, "the failed attempt's files are the evidence, and stay as they were"
    assert row_env(board, "harness-run-bell.sh.env")["OUT"] == _fwd(dirs[1]) + "/raw"


@needs_bash
def test_an_attempt_directory_is_never_reused_even_when_the_clock_names_the_same_one(board):
    board.set("date_utc", "20261005T010203Z\n")
    assert board.run("G5").log == ["G5 PASS"]
    first = board.attempt("G5")
    before = board.tree(first)
    r = board.run("G5")                             # the stub clock still says the same second
    assert r.log == ["G5 PASS", "G5 FAIL refused-attempt-directory"] and r.returncode == 2, (r.log, r.out[-800:])
    assert board.tree(first) == before and len(board.attempts("G5")) == 1
    assert [c for c in r.calls if c.startswith("harness")] == []


# ------------------------------------------------------------------ the GPU tier's own rules

@needs_bash
@pytest.mark.parametrize("steps", [("G18",), ("G19",), ("G20",), ("G21",), ("G18", "G19", "G20", "G21")],
                         ids=["G18", "G19", "G20", "G21", "the-tier"])
@pytest.mark.parametrize("env", [{}, {"GATE2_GPU_OWNER_PRESENT": "yes"}, {"GATE2_GPU_OWNER_PRESENT": "0"},
                                 {"GATE2_GPU_OWNER_PRESENT": ""}], ids=["unset", "yes", "zero", "empty"])
def test_a_gpu_step_without_the_owners_variable_is_refused_and_no_stub_is_called(board, steps, env):
    r = board.run(*steps, **env)
    assert r.log == ["%s FAIL refused-gpu-owner-absent" % s for s in steps] and r.returncode == 2, (r.log, r.out)
    assert r.calls == [], "not one command was run: %s" % r.calls
    assert "GATE2_GPU_OWNER_PRESENT=1" in r.out and not (board.home / "gate2" / "out").exists()


@needs_bash
def test_a_gpu_step_among_others_is_refused_alone_and_the_others_run(board):
    r = board.run("G17", "G18", "G0")
    assert r.log == ["G17 PASS", "G18 FAIL refused-gpu-owner-absent", "G0 PASS"] and r.returncode == 2, (r.log, r.out[-800:])
    assert not [c for c in r.calls if c.startswith(("fma", "tegrastats"))]
    assert not [c for c in r.calls if "drop_caches" in c]


@needs_bash
def test_the_gpu_tier_goes_in_its_order_and_a_step_whose_predecessor_did_not_pass_is_refused(board):
    """CUDA alone, then llama.cpp alone, then the guest: the first GPU load on a new release is
    not taken beside a guest before it has been taken alone."""
    assert board.run("G19", **GPU).log == ["G19 FAIL refused-gpu-order"]
    # The step before has to have passed last: a PASS that a later FAIL followed does not count.
    _put(board.G + "/gate2.log", "G18 PASS\nG18 FAIL fma-exit\n")
    assert board.run("G19", **GPU).log[-1] == "G19 FAIL refused-gpu-order"
    os.unlink(board.G + "/gate2.log")
    assert board.run("G19", **GPU).log == ["G19 FAIL refused-gpu-order"]
    board.set("fma_rc", "1\n")
    r = board.run("G18", "G19", "G20", "G21", **GPU)
    assert r.log[1:] == ["G18 FAIL fma-exit", "G19 FAIL refused-gpu-order", "G20 FAIL refused-gpu-order", "G21 FAIL refused-gpu-order"], r.log
    assert not [c for c in r.calls if c.startswith(("llama-cli", "launcher", "harness"))]
    board.unset("fma_rc")
    board.set("tegrastats", TEGRA_BUSY)
    r = board.run("G18", "G19", **GPU)
    assert r.log[-2:] == ["G18 PASS", "G19 PASS"], (r.log, r.out[-1500:])


@needs_bash
@pytest.mark.parametrize("change, why", [
    (dict(fma_out=FMA_OUT, tegrastats=TEGRA_IDLE), "gpu-busy"),
    (dict(fma_out="device=Orin cc=8.7 sms=8 tag=gate2\n", tegrastats=TEGRA_BUSY), "fma-rounds"),
    (dict(fma_out="FATAL cudaMalloc failed\n", fma_rc="1\n", tegrastats=TEGRA_BUSY), "fma-exit"),
    (dict(tegrastats=TEGRA_BUSY), "page-cache"),
], ids=["gpu-idle", "no-rounds", "fma-fails", "cache-not-dropped"])
def test_g18_wants_fma_to_print_its_rounds_with_the_gpu_busy_after_the_cache_was_dropped(board, change, why):
    for k, v in change.items():
        board.set(k, v)
    if why == "page-cache":
        # A sudo that is denied would refuse the opening check as well, so the write itself is
        # made to fail: where the made-up /proc has a directory, nothing can be written.
        (board.proc / "sys" / "vm" / "drop_caches").unlink()
        (board.proc / "sys" / "vm" / "drop_caches").mkdir()
    r = board.run("G18", **GPU)
    assert r.log == ["G18 FAIL " + why], (r.log, r.out[-1200:])
    if why == "page-cache":
        assert not [c for c in r.calls if c.startswith("fma")], "no GPU load on a warm cache"


OFFLOAD = [
    (LLAMA_ERR, TEGRA_IDLE, None),
    (LLAMA_ERR.replace("offloaded 9/9 layers", "offloaded 0/9 layers"), TEGRA_IDLE, "gpu-evidence"),
    (LLAMA_ERR.replace("ggml_cuda_init: found 1 CUDA devices:\n", ""), TEGRA_IDLE, "gpu-evidence"),
    ("load_tensors: layers on the CPU\n", TEGRA_IDLE, "gpu-evidence"),
    ("load_tensors: layers on the CPU\n", TEGRA_BUSY, None),
]


@needs_bash
@pytest.mark.parametrize("err, tegra, why", OFFLOAD, ids=["offloaded", "no-layer", "no-cuda-line", "cpu-only", "cpu-wording-gpu-busy"])
def test_g19_wants_positive_evidence_of_the_gpu_as_a_yes_or_a_no(board, err, tegra, why):
    """A CUDA that fails to initialise leaves llama.cpp on the CPU, still printing tokens. The
    step passes on layers offloaded, more than none, with a CUDA device named, or on the GPU seen
    busy during the run."""
    _put(board.G + "/gate2.log", "G18 PASS\n")
    board.set("llama_stderr", err)
    board.set("tegrastats", tegra)
    r = board.run("G19", **GPU)
    assert r.log[-1] == ("G19 PASS" if why is None else "G19 FAIL " + why), (r.log, r.out[-1200:])
    ev = (board.attempt("G19") / "evidence.txt").read_bytes().decode()
    assert re.search(r"(?m)^layers offloaded to the GPU, with a CUDA device named: (yes|no)$", ev)
    assert re.search(r"(?m)^the GPU seen busy during the run: (yes|no)$", ev)
    assert not re.search(r"\d", ev), "a yes or a no, and no value: %r" % ev
    assert "9/9" not in r.out and "77%" not in r.out


@needs_bash
@pytest.mark.parametrize("change, why", [
    (dict(llama_rc="124\n"), "llama-exit"),
    (dict(llama_stdout="\n  \n"), "tokens"),
    (dict(llama_stdout=""), "tokens"),
], ids=["timed-out", "blank-output", "no-output"])
def test_g19_wants_the_model_to_load_and_print_tokens(board, change, why):
    _put(board.G + "/gate2.log", "G18 PASS\n")
    for k, v in change.items():
        board.set(k, v)
    r = board.run("G19", **GPU)
    assert r.log[-1] == "G19 FAIL " + why, (r.log, r.out[-1200:])
    assert len([c for c in r.calls if c.startswith("llama-cli")]) == 1, "no second load: the failure was not NvMap's"


@needs_bash
@pytest.mark.parametrize("where", ["output", "kernel"])
def test_gap_4o_one_retry_with_the_workaround_when_the_load_fails_with_the_nvmap_error(board, where):
    """As the R36 scripts would run it first. With the NvMap error in the load's own output, or
    in the kernel's lines of that load (the load itself may then still print tokens), it is run
    once more with the variable set, and with it only then."""
    _put(board.G + "/gate2.log", "G18 PASS\n")
    if where == "output":
        board.set("llama_stderr", LLAMA_ERR + NVMAP)
        board.set("llama_rc", "1\n")
        board.set("llama_stdout", "")
    else:
        board.set("llama_hook", 'echo "nvgpu: made-up line" >> "$S/kjournal"\n'
                                'echo "<3>NvMap: made-up handle: allocation failed, error 12" >> "$S/kjournal"\n')
    board.set("llama_stderr.retry", LLAMA_ERR)
    board.set("llama_stdout.retry", LLAMA_OUT)
    board.set("llama_rc.retry", "0\n")
    r = board.run("G19", **GPU)
    assert r.log == ["G18 PASS", "G19 FAIL nvmap", "G19 PASS"] and r.returncode == 1, (r.log, r.out[-1500:])
    loads = [c.split()[0] for c in r.calls if c.startswith("llama-cli")]
    assert loads == ["llama-cli", "llama-cli.retry"], "once as the R36 scripts would, once more with the workaround, and never a third"
    assert row_env(board, "llama.env") == {} and row_env(board, "llama.retry.env") == {"GGML_CUDA_ENABLE_UNIFIED_MEMORY": "1"}
    assert board.argv("llama.retry.argv") == board.argv("llama.argv"), "the same command"
    dirs = board.attempts("G19")
    assert len(dirs) == 2 and (dirs[0] / "llama.stderr").exists() and (dirs[1] / "llama.stderr").exists(), "each load in a directory of its own"
    if where == "output":
        assert "NvMapMemAllocInternalTagged" in (dirs[0] / "llama.stderr").read_bytes().decode()
    else:
        assert "allocation failed" in (dirs[0] / "kernel-during.log").read_bytes().decode()
        assert "allocation failed" not in r.out, "a kernel line is kept in a file and never printed"
    assert (board.home / "gate2" / "state" / "nvmap-workaround").exists()
    ev = [(d / "evidence.txt").read_bytes().decode() for d in dirs]
    assert "the unified-memory workaround: not set\n" in ev[0] and "the unified-memory workaround: set\n" in ev[1]


@needs_bash
def test_gap_4o_a_second_nvmap_failure_stops_the_gpu_tier(board):
    _put(board.G + "/gate2.log", "G18 PASS\n")
    board.set("llama_stderr", LLAMA_ERR + NVMAP)
    board.set("llama_rc", "1\n")
    r = board.run("G19", "G20", "G21", **GPU)
    assert r.log == ["G18 PASS", "G19 FAIL nvmap", "G19 FAIL nvmap", "G20 FAIL refused-gpu-order", "G21 FAIL refused-gpu-order"], \
        (r.log, r.out[-1500:])
    assert len([c for c in r.calls if c.startswith("llama-cli")]) == 2 and not [c for c in r.calls if c.startswith(("launcher", "harness"))]
    assert not (board.home / "gate2" / "state" / "nvmap-workaround").exists(), "the workaround did not help: nothing to carry on with"


@needs_bash
def test_gap_4o_after_the_workaround_g21_is_left_out_and_g20_waits_for_the_scripts_to_carry_it(board):
    _put(board.G + "/gate2.log", "G18 PASS\n")
    board.set("llama_stderr", LLAMA_ERR + NVMAP)
    board.set("llama_rc", "1\n")
    board.set("llama_stderr.retry", LLAMA_ERR)
    board.set("llama_rc.retry", "0\n")
    r = board.run("G19", "G20", "G21", **GPU)
    assert r.log == ["G18 PASS", "G19 FAIL nvmap", "G19 PASS", "G20 FAIL refused-nvmap-workaround", "G21 FAIL refused-nvmap-workaround"], \
        (r.log, r.out[-1500:])
    assert not [c for c in r.calls if c.startswith(("launcher", "harness"))]
    # Once the deployed demo names the variable (a code change, with tests, before G20), G20 runs.
    # G21 stays left out.
    with open(board.E + "/vlm-demo.sh", "ab") as f:
        f.write(b"\n# GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 is set and stamped (made up)\n")
    board.write_manifests()
    r = board.run("G20", "G21", **GPU)
    assert r.log[-2:] == ["G20 PASS", "G21 FAIL refused-nvmap-workaround"], (r.log, r.out[-1500:])
    assert "GGML_CUDA_ENABLE_UNIFIED_MEMORY" not in row_env(board, "harness-vlm-demo.sh.env"), \
        "the runner does not set it for the demo: the scripts do"


@needs_bash
@pytest.mark.parametrize("log, why", [
    (SERVER_LOG.replace("offloaded 9/9 layers", "offloaded 0/9 layers"), "gpu-evidence"),
    ("main: server is listening on http://127.0.0.1:8089\n", "gpu-evidence"),
    (SERVER_LOG + NVMAP, "nvmap"),
], ids=["no-layer", "no-load-lines", "nvmap"])
def test_g20_wants_the_same_offload_evidence_in_the_servers_log(board, log, why):
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\n")
    board.set("tegrastats", TEGRA_BUSY)             # the GPU busy is no evidence here: the rule reads server.log
    board.set("post-vlm-demo.sh", "cat > \"$OUT/server.log\" <<'EOF'\n" + log + "EOF\n")
    r = board.run("G20", "G21", **GPU)
    assert r.log[2] == "G20 FAIL " + why, (r.log, r.out[-1500:])
    if why == "nvmap":
        assert r.log[3] == "G21 FAIL refused-nvmap-workaround" and (board.home / "gate2" / "state" / "nvmap-workaround").exists()
        assert len([c for c in r.calls if c.startswith("harness vlm-demo.sh")]) == 1, "the retry is G19's; the demo is not run twice"


@needs_bash
def test_g20_reads_the_kernels_lines_of_the_demo_for_the_nvmap_failure_as_well(board):
    """The failure may be in the kernel's lines only, with the server's own log clean."""
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\n")
    board.set("hook-vlm-demo.sh", 'echo "<3>NvMap: made-up handle: allocation failed, error 12" >> "$S/kjournal"\n')
    r = board.run("G20", "G21", **GPU)
    assert r.log[2:] == ["G20 FAIL nvmap", "G21 FAIL refused-nvmap-workaround"], (r.log, r.out[-1500:])
    assert "allocation failed" in (board.attempt("G20") / "kernel-during.log").read_bytes().decode()
    assert "allocation failed" not in r.out, "a kernel line is kept in a file and never printed"


@needs_bash
@pytest.mark.parametrize("step, hook", [("G19", "llama_hook"), ("G20", "hook-vlm-demo.sh")])
def test_a_gpu_step_whose_kernel_lines_cannot_be_read_fails_by_that_name(board, step, hook):
    """"No NvMap error in the kernel log" is part of both rows' rule. Lines that cannot be read
    show nothing of the kind: the step fails, and what follows is refused on the same reading."""
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\n")
    board.set("tegrastats", TEGRA_BUSY)
    board.set(hook, 'echo 1 > "$S/journal_rc"\n')
    r = board.run(step, "G5", **GPU)
    assert r.log[2:] == [step + " FAIL kernel-lines-read", "G5 FAIL refused-kernel-lines"], (r.log, r.out[-1500:])
    assert board.alive() == []


@needs_bash
def test_a_refusal_keeps_the_calls_exit_status_whatever_fails_after_it(board):
    """2 says that something asked for was not run. A step that failed after it does not turn
    that into the 1 of a call whose every step ran."""
    board.set("rc-run-bell.sh", "1\n")
    r = board.run("G18", "G5")
    assert r.log == ["G18 FAIL refused-gpu-owner-absent", "G5 FAIL harness-exit"] and r.returncode == 2, (r.log, r.returncode)
    r = board.run("G5")
    assert r.log[-1] == "G5 FAIL harness-exit" and r.returncode == 1
    # Nor does the first line of gap 4o's retry, which is a failed step's.
    b = Board(board.root.parent / "retry-after-a-refusal", board.tools)
    _put(b.G + "/gate2.log", "G18 PASS\n")
    for k, v in (("llama_stderr", LLAMA_ERR + NVMAP), ("llama_rc", "1\n"), ("llama_stderr.retry", LLAMA_ERR), ("llama_rc.retry", "0\n"),
                 ("lsblk", LSBLK + STICK)):
        b.set(k, v)
    r = b.run("G0", "G19", **GPU)
    b.kill_all()
    assert r.log == ["G18 PASS", "G0 FAIL refused-stick", "G19 FAIL nvmap", "G19 PASS"] and r.returncode == 2, (r.log, r.returncode)


# ------------------------------------------------------------------ G9, G16, G17: the rules of their own

@needs_bash
@pytest.mark.parametrize("ssh_log, why", [
    ("Server listening on :: port 22.\n", "login-control"),
    ("", "login-control"),
    ("Failed password for invalid user made-up from 192.0.2.9 port 40000 ssh2\n  Accepted nothing\n", "login-control"),
], ids=["no-login-line", "empty", "no-accepted-line"])
def test_g9s_positive_control_wants_the_login_counter_to_count_this_sessions_own_login(board, ssh_log, why):
    """M4 wants no login during the rounds, which a counter that cannot count also gives."""
    board.set("ssh_log", ssh_log)
    r = board.run("G9")
    assert r.log == ["G9 FAIL " + why], (r.log, r.out[-1200:])


@needs_bash
def test_g9_wants_the_units_back_on_all_cores(board):
    board.set("post-run-metal.sh", POST_LAT + 'echo "3,5" > "$S/allowed-system.slice"\n')
    r = board.run("G9", "G10")
    assert r.log == ["G9 FAIL confinement", "G10 FAIL refused-confinement"], (r.log, r.out[-1200:])
    assert "system.slice" in r.out


@needs_bash
def test_units_set_back_to_all_cores_are_not_confined(board):
    """AllowedCPUs is empty or all cores. A harness that undoes its confinement writes the full
    set back, and the unit then reads as the cores that are online, not as nothing."""
    units = ("system.slice", "init.scope", "user@1000.service", "session-3.scope")
    for unit in units:
        board.set("allowed-" + unit, "0-5\n")
    r = board.run("G9", "G10")
    assert r.log == ["G9 PASS", "G10 PASS"] and r.returncode == 0, (r.log, r.out[-1500:])
    # One core fewer than are online is a confinement, on any of them.
    for unit in units:
        board.set("allowed-" + unit, "0-4\n")
        refused(board.run("G5"), "G5", "confinement")
        board.set("allowed-" + unit, "0-5\n")


@needs_bash
def test_g10_wants_a_reduced_heavy_trace(board):
    board.set("post-run-tick.sh", POST_LAT)
    assert board.run("G10").log == ["G10 FAIL heavy-trace"]
    board.set("post-run-tick.sh", POST_LAT + ': > "$OUT/tk-t2ms_r2.log"\n')
    assert board.run("G10").log[-1] == "G10 FAIL heavy-trace", "an empty file is not a reduced trace"


@needs_bash
def test_g8_wants_the_stamp_to_hold_the_new_releases_values(board):
    for change, ok in ((lambda t: t, True),
                       (lambda t: t.replace("# R39 (release)", "# R36 (release)"), False),
                       (lambda t: t.replace("Ubuntu 24.04.9", "Ubuntu 22.04.5"), False),
                       (lambda t: t.replace('"config_hz": 250', '"config_hz": null'), False),
                       (lambda t: t.replace('"l4t_release"', '"l4t"'), False)):
        b = Board(board.root.parent / ("s%d" % len(list(board.root.parent.iterdir()))), board.tools)
        b.set("post-run-stamp.sh", POST_LAT + "cat > \"$OUT/stamp.json\" <<'EOF'\n" + change(STAMP_JSON) + "EOF\n")
        r = b.run("G8")
        b.kill_all()
        assert r.log == (["G8 PASS"] if ok else ["G8 FAIL stamp-system"]), (r.log, r.out[-800:])
    b = Board(board.root.parent / "nostamp", board.tools)
    b.set("post-run-stamp.sh", POST_LAT)
    assert b.run("G8").log == ["G8 FAIL stamp-system"]
    b.kill_all()


DDS_CASES = [
    (dict(), None),
    (dict(subv_rc="1\n"), None),
    (dict(subv_rc="124\n"), None),
    (dict(subv_out="VERDICT seq=15 accepted=1 reason=0\ntotal verdicts=1\n"), "five-verdicts"),
    (dict(subv_out=SUBV_OUT.replace("VERDICT seq=13 accepted=0 reason=2\n", "")), "five-verdicts"),
    (dict(subv_out=SUBV_OUT.replace("VERDICT seq=13 accepted=0 reason=2\n", "VERDICT seq=12 accepted=0 reason=3\n")), "five-verdicts"),
    (dict(subv_out=SUBV_OUT + "VERDICT seq=15 accepted=1 reason=0\n"), "five-verdicts"),
    (dict(subv_out=SUBV_OUT.replace("seq=12 accepted=0 reason=3", "seq=12 accepted=1 reason=0")), "bad-rejected"),
    (dict(subv_out=SUBV_OUT.replace("seq=13 accepted=0 reason=2", "seq=13 accepted=0 reason=3")), "own-reasons"),
    (dict(subv_out=SUBV_OUT.replace("seq=15 accepted=1 reason=0", "seq=15 accepted=0 reason=4")), "good-accepted"),
    (dict(pubbad_out=PUBBAD_OUT.replace("send seq=14 bad-four rc=0\n", "")), "claims-sent"),
    (dict(pubbad_out=PUBBAD_OUT.replace("send seq=15 good rc=0", "send seq=15 good rc=-1")), "claims-sent"),
    (dict(pubbad_out="matched=0 after 9999 ms\n"), "claims-sent"),
    (dict(console=CONSOLES["ifs-dds.bin"].replace("claim seq=14 cls=1 conf=8 us=6 -> REJECT (reason=4)\r\n", "")), "console-agrees"),
    (dict(console=CONSOLES["ifs-dds.bin"].replace("-> REJECT (reason=3)", "-> REJECT (reason=2)")), "console-agrees"),
    (dict(console=CONSOLES["ifs-dds.bin"].replace("-> ACCEPT (reason=0)", "-> REJECT (reason=4)")), "console-agrees"),
]


@needs_bash
@pytest.mark.parametrize("change, why", DDS_CASES, ids=[
    "clean", "subv-exit-one", "subv-timed-out", "one-verdict-exit-zero", "four-verdicts", "a-seq-twice", "six-lines", "a-bad-one-accepted",
    "two-share-a-reason", "the-good-one-rejected", "four-sent", "a-send-failed", "nothing-sent", "console-lacks-one", "console-other-reason",
    "console-other-verdict"])
def test_g16_is_judged_by_subvs_five_verdict_lines_and_not_by_an_exit_status(board, change, why):
    """subv exits 0 on a single verdict. The rule: one verdict per claim pubbad sent, the four
    bad ones rejected, each with its own reason, the good one accepted, and the guest's console
    saying the same of each."""
    for k, v in change.items():
        board.set("console-ifs-dds.bin" if k == "console" else k, v)
    r = board.run("G16")
    assert r.log == (["G16 PASS"] if why is None else ["G16 FAIL " + why]), (r.log, r.out[-1200:])
    assert board.alive() == []


@needs_bash
def test_g16_waits_for_subv_and_reads_the_console_again_after_the_peers_ran(board):
    """subv prints its verdicts when it has heard them, after pubbad has gone; and the guest's
    claim lines reach its console while the peers run, long after the launch read it."""
    full = CONSOLES["ifs-dds.bin"]
    claims = "".join(l + "\n" for l in full.split("\n") if l.startswith("claim seq="))
    assert claims.count("claim seq=") == 5 and full.endswith(claims)
    board.set("console-ifs-dds.bin", full[:-len(claims)])
    board.set("late", claims)
    board.set("hook-pubbad", 'for f in \'%s\'/gate2/out/G16/*/guest-console.log; do cat "$S/late" >> "$f"; done\n' % board.H)
    board.set("hook-subv", "'%s' 0.8\n" % board.tools["sleep"])
    r = board.run("G16")
    assert r.log == ["G16 PASS"], (r.log, r.out[-1500:])
    assert board.alive() == []


@needs_bash
def test_g16_wants_the_two_peers_built_at_the_pinned_commit_and_nowhere_else(board):
    other = board.home / "cyclonedds" / "ffffffffffff"
    (board.home / "cyclonedds" / DDS_PIN[:12]).rename(other)
    r = board.run("G16")
    assert r.log == ["G16 FAIL dds-peers"] and not [c for c in r.calls if c.startswith(("launcher", "subv", "pubbad"))], (r.log, r.out)
    assert DDS_PIN not in _text(SCRIPT), "the pin is read from the deployed build script, not written here"


@needs_bash
def test_g17_fails_on_the_harnesss_warning_and_releases_a_queue_that_stayed_held(board):
    board.set("err-run-queue.sh", "WARNING: udevd's queue may still be held -- release it by hand: sudo udevadm control --start-exec-queue\n")
    r = board.run("G17")
    assert r.log == ["G17 FAIL queue-warning"], (r.log, r.out[-1200:])
    board.unset("err-run-queue.sh")
    # The queue file is still there after the harness: the step fails, the row's recovery is
    # tried once (release, then settle), and udevd is never restarted.
    board.set("post-run-queue.sh", POST_LAT + "mkdir -p '%s/udev'; : > '%s/udev/queue'\n" % (_fwd(board.run_root), _fwd(board.run_root)))
    board.set("udev_release_works", "1\n")
    r = board.run("G17", "G5")
    assert r.log[-2:] == ["G17 FAIL queue-released", "G5 PASS"], (r.log, r.out[-1500:])
    assert "sudo -n udevadm control --start-exec-queue" in r.calls and not (board.run_root / "udev" / "queue").exists()
    assert not (board.state / "systemctl-changed").exists()
    # A queue that stays held after the recovery refuses what follows.
    board.unset("udev_release_works")
    r = board.run("G17", "G5")
    assert r.log[-2:] == ["G17 FAIL queue-released", "G5 FAIL refused-udev"], (r.log, r.out[-1500:])


@needs_bash
def test_g17_fails_when_udev_does_not_settle(board):
    board.set("post-run-queue.sh", POST_LAT + 'echo 1 > "$S/settle_rc"\n')
    r = board.run("G17")
    assert r.log == ["G17 FAIL queue-released"], (r.log, r.out[-1200:])


# ------------------------------------------------------------------ before any step: the refusals

@needs_bash
def test_a_running_qemu_refuses_every_step_before_anything_starts(board):
    board.set("procs_static", "   4242 /usr/bin/qemu-system-aarch64 -machine virt,gic-version=3 -kernel /made-up/ifs.bin\n")
    r = board.run("G0", "G5", "G12")
    for step in ("G0", "G5", "G12"):
        refused(r, step, "leftover-process")
    assert harness_calls(r) == [], "nothing was started beside a guest somebody else left: %s" % harness_calls(r)
    assert "qemu-system-aarch64" in r.out


@needs_bash
@pytest.mark.parametrize("line", [
    "   4243 /made-up/ladder/monitor-native 7100\n", "   4244 /made-up/gpuload/fma 30 x\n", "   4245 /made-up/bin/llama-server -m x\n",
    "   4246 llama-cli -m x\n", "   4247 python3 /made-up/gpu-concurrency/ivshmem_server.py --socket /tmp/x\n",
    "   4248 /made-up/cpuload 4 30\n"], ids=["monitor-native", "fma", "llama-server", "llama-cli", "ivshmem-server", "cpuload"])
def test_a_load_or_a_leftover_process_refuses_every_step(board, line):
    board.set("procs_static", line)
    r = board.run("G5")
    refused(r, "G5", "leftover-process")
    assert harness_calls(r) == []


@needs_bash
def test_a_process_that_only_names_one_of_them_in_its_arguments_is_not_taken_for_it(board):
    board.set("procs_static", "   4249 bash /made-up/gate2-smoke.sh G5\n   4250 grep qemu-system-aarch64\n   4251 tail -f /made-up/fma.log\n"
                              "   4252 vim ivshmem_server.py\n   4253 /usr/bin/python3 /made-up/latency_probe.py --ivshm /tmp/a6-ivshmem.sock\n")
    assert board.run("G5").log == ["G5 PASS"]


@needs_bash
def test_a_process_list_that_cannot_be_read_refuses(board):
    board.set("ps_rc", "1\n")
    refused(board.run("G5"), "G5", "leftover-process")


@needs_bash
@pytest.mark.parametrize("gone", ["class/net/tap-qnx", "class/net/br0", "class/net/br0/brif/tap-qnx"],
                         ids=["no-tap", "no-bridge", "tap-not-on-the-bridge"])
def test_a_missing_bridge_refuses_before_anything_starts(board, gone):
    shutil.rmtree(str(board.sys / gone))
    r = board.run("G5", "G12")
    refused(r, "G5", "bridge")
    refused(r, "G12", "bridge")
    assert harness_calls(r) == [] and "setup-bridge-orin.sh" in r.out


@needs_bash
@pytest.mark.parametrize("how", ["image-changed", "disk-changed", "no-line", "two-hashes", "two-hashes-the-right-one-last", "only-elsewhere",
                                 "no-manifest", "image-missing", "not-a-hash"])
def test_an_image_that_is_not_the_manifests_refuses_the_step_before_anything_starts(board, how):
    man = board.home / "gate2" / "images.sha256"
    other = hashlib.sha256(b"another file altogether").hexdigest()
    without = b"".join(l for l in man.read_bytes().splitlines(True) if b"ifs-bell.bin" not in l)
    if how == "image-changed":
        _put(board.IMG + "/ifs-bell.bin", "another image\n")
    elif how == "disk-changed":
        _put(board.IMG + "/disk-qemu", "another disk\n")
    elif how == "no-line":
        man.write_bytes(without)
    elif how == "two-hashes":
        man.write_bytes(man.read_bytes() + ("%s  ifs-bell.bin\n" % other).encode())
    elif how == "two-hashes-the-right-one-last":
        man.write_bytes(("%s  ifs-bell.bin\n" % other).encode() + man.read_bytes())
    elif how == "only-elsewhere":
        man.write_bytes(without + ("%s  ./qhv-output/ifs-bell.bin\n" % _sha(board.IMG + "/ifs-bell.bin")).encode())
    elif how == "no-manifest":
        man.unlink()
    elif how == "not-a-hash":
        man.write_bytes(without + b"unreadable  ./output/ifs-bell.bin\n")
    else:
        os.unlink(board.IMG + "/ifs-bell.bin")
    r = board.run("G5", "G12")
    refused(r, "G5", "image-hash")
    assert not [c for c in r.calls if c.startswith("harness run-bell.sh")]
    if how in ("disk-changed", "no-manifest"):
        refused(r, "G12", "image-hash")
    else:
        assert r.log[-1] == "G12 PASS", "a step that boots another image is not held up by this one: %s" % r.log


@needs_bash
def test_the_manifest_may_be_the_backups_whole_list_and_a_line_for_another_directory_is_not_read(board):
    """The list made on the board when it was backed up has every file of the home, the images
    under ./output/ among them. A file of an image's name in another directory is another file."""
    man = board.home / "gate2" / "images.sha256"
    other = hashlib.sha256(b"another file altogether").hexdigest()
    man.write_bytes(("%s  ./qhv-output/ifs-bell.bin\n%s  ./qlv/disk-qemu\n%s  ./notes.txt\n" % (other, other, other)).encode()
                    + man.read_bytes() + ("%s *ifs-live.bin\n" % _sha(board.IMG + "/ifs-live.bin")).encode())
    assert board.run("G5", "G12").log == ["G5 PASS", "G12 PASS"]


@needs_bash
def test_the_manifest_is_read_from_the_path_it_is_given(board):
    elsewhere = board.root / "elsewhere.sha256"
    shutil.move(str(board.home / "gate2" / "images.sha256"), str(elsewhere))
    assert board.run("G5", GATE2_MANIFEST=_fwd(elsewhere)).log == ["G5 PASS"]


# The images each step boots, itself or through its harness: section 3's rows.
STEP_IMAGES = {
    "G1": ("ifs-its.bin",), "G2": ("ifs-its.bin",), "G3": ("ifs-its.bin",), "G4": ("ifs-kick.bin",), "G5": ("ifs-bell.bin",),
    "G6": ("ifs-paths.bin",), "G7": ("ifs-bell.bin",), "G8": ("ifs-stamp.bin",), "G9": ("ifs-stamp.bin",), "G10": ("ifs-stamp.bin",),
    "G11": ("ifs-someip.bin",), "G12": ("ifs-live.bin",), "G13": ("ifs-unmask-a.bin", "ifs-unmask-b.bin"),
    "G14": ("ifs-bell.bin", "ifs-robust.bin", "ifs-unmask-a.bin"), "G15": ("ifs-trace.bin",), "G16": ("ifs-dds.bin",),
    "G17": ("ifs-stamp.bin",), "G20": ("ifs-svc.bin",), "G21": ("ifs-kick.bin",),
}
STEP_IMAGE_PAIRS = [(s, i) for s in STEPS for i in STEP_IMAGES.get(s, ())]


@needs_bash
@pytest.mark.parametrize("step, image", STEP_IMAGE_PAIRS, ids=["%s-%s" % p for p in STEP_IMAGE_PAIRS])
def test_every_image_a_step_boots_is_held_to_the_manifest_before_anything_starts(board, step, image):
    """Each image of each step's row, changed in turn: the step is refused, and neither the
    launcher nor the harness that would have booted the image is called."""
    _put(board.IMG + "/" + image, "another image\n")
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\nG20 PASS\n")     # the GPU tier's order, for G20 and G21
    r = board.run(step, **GPU)
    assert r.log[-1] == "%s FAIL refused-image-hash" % step and r.returncode == 2, (r.log, r.out[-1200:])
    assert harness_calls(r) == [], "nothing was started over an image that is not the manifest's: %s" % harness_calls(r)
    assert "/%s is not the file" % image in r.out


@needs_bash
def test_a_step_that_boots_no_image_is_not_held_up_by_one(board):
    assert sorted(STEP_IMAGES) == sorted(s for s in STEPS if s not in ("G0", "G18", "G19"))
    for n in IMAGES:
        _put(board.IMG + "/" + n, "another file\n")
    board.set("tegrastats", TEGRA_BUSY)
    assert board.run("G0", "G18", "G19", **GPU).log == ["G0 PASS", "G18 PASS", "G19 PASS"]


def test_the_images_held_for_a_harness_that_boots_its_own_guests_are_that_harnesss_own_defaults():
    """The runner cannot see which image a harness boots; it holds the ones the harness's own
    default lines name. Read here from the harnesses as they are in the repo."""
    for step, (name, _row) in SELF_BOOTING.items():
        code = _code(_text(os.path.join(REPO, "orin-native", "gpu-concurrency", name)))
        named = re.findall(r'(?m)^IMG_\w+="\$\{IMG_\w+:-(?:\$\{IFS_BIN:-)?\$HOME/output/(ifs-[\w-]+\.bin)\}+"', code)
        assert sorted(named) == sorted(STEP_IMAGES[step]), (step, name, named)
    assert set(i for v in STEP_IMAGES.values() for i in v) | {"disk-qemu"} == set(IMAGES), "and every image of the list is some step's"


@needs_bash
@pytest.mark.parametrize("which", ["images", "deploy", "both"])
def test_a_manifest_with_crlf_line_ends_is_read_as_the_same_list(board, which):
    """Both lists are made on another machine. A carriage return at the end of a line is not part
    of the file's name."""
    for name in {"images": ("images.sha256",), "deploy": ("deploy.sha256",), "both": ("images.sha256", "deploy.sha256")}[which]:
        man = board.home / "gate2" / name
        man.write_bytes(man.read_bytes().replace(b"\n", b"\r\n"))
        assert b"\r\n" in man.read_bytes()
    assert board.run("G5", "G12").log == ["G5 PASS", "G12 PASS"]


@needs_bash
@pytest.mark.parametrize("how", ["file-changed", "no-manifest", "file-missing", "a-line-that-is-no-checksum-line"])
def test_a_deploy_that_is_not_its_manifests_refuses_every_step(board, how):
    if how == "file-changed":
        with open(board.R + "/run-bell.sh", "ab") as f:
            f.write(b"\n# edited on the board\n")
    elif how == "no-manifest":
        (board.home / "gate2" / "deploy.sha256").unlink()
    elif how == "a-line-that-is-no-checksum-line":
        # Every file it does list matches. A list with a line nobody can read is not one to go by.
        with open(board.G + "/deploy.sha256", "ab") as f:
            f.write(b"what follows was cut off\n")
    else:
        os.unlink(board.R + "/ivshmem_ring.py")
    # Every step of the call, G18 too, which runs no deployed file: the deploy as a whole is
    # not what was reviewed.
    r = board.run("G12", "G5", "G18", **GPU)
    for step in ("G12", "G5", "G18"):
        refused(r, step, "deploy-hash")
    assert harness_calls(r) == []


# The deployed files the runner itself starts or reads for each step, by their paths below the
# repo root: the launcher where the runner launches, the row's harness or tool, and for G16 the
# peers' configuration and the build script the pin is read from.
_GC, _EL, _DDS = "orin-native/gpu-concurrency/", "orin-native/edge-llm/", "ipc-test/qnx-dds-monitor/"
_LAUNCHER = _GC + "launch-qnx-kvm-bridged.sh"
STEP_FILES = {
    "G0": ("orin-native/tools/check_virt_dtb.py",), "G1": (_LAUNCHER,), "G2": (_LAUNCHER,), "G3": (_LAUNCHER, _GC + "ivshmem_ring.py"),
    "G4": (_LAUNCHER, _GC + "run-ladder.sh"), "G5": (_GC + "run-bell.sh",), "G6": (_GC + "run-paths.sh",), "G7": (_GC + "run-mmio.sh",),
    "G8": (_LAUNCHER, _GC + "run-stamp.sh"), "G9": (_LAUNCHER, _GC + "run-metal.sh"), "G10": (_LAUNCHER, _GC + "run-tick.sh"),
    "G11": (_GC + "run-someip0.sh",), "G12": (_LAUNCHER, _EL + "liveness-demo.sh"), "G13": (_GC + "run-unmask.sh",),
    "G14": (_GC + "run-bellrobust.sh",), "G15": (_GC + "run-trace.sh",),
    "G16": (_LAUNCHER, _DDS + "cyclonedds-l4t.xml", _DDS + "build-cyclonedds-qnx.sh"), "G17": (_LAUNCHER, _GC + "run-queue.sh"),
    "G20": (_LAUNCHER, _EL + "vlm-demo.sh"), "G21": (_LAUNCHER, _EL + "run-llm-interference.sh"),
}
STEP_FILE_PAIRS = [(s, f) for s in STEPS for f in STEP_FILES.get(s, ())]


@needs_bash
@pytest.mark.parametrize("step, path", STEP_FILE_PAIRS, ids=["%s-%s" % (s, f.rsplit("/", 1)[1]) for s, f in STEP_FILE_PAIRS])
def test_a_deployed_file_a_step_runs_that_the_deploys_manifest_does_not_list_refuses_the_step(board, step, path):
    """Every file the manifest lists matches, and it does not list this one: nothing held the file
    to the deployed commit, so the step that would run it is refused, and that step only."""
    board.drop_from_deploy_list(path)
    _put(board.G + "/gate2.log", "G18 PASS\nG19 PASS\nG20 PASS\n")
    other = "G5" if _GC + "run-bell.sh" not in STEP_FILES[step] else "G6"
    r = board.run(step, other, **GPU)
    assert r.log[-2:] == ["%s FAIL refused-deploy-hash" % step, other + " PASS"] and r.returncode == 2, (r.log, r.out[-1200:])
    assert [c.split()[1] for c in harness_calls(r)] == [SELF_BOOTING[other][0]], "only the other step ran: %s" % harness_calls(r)
    assert "%s has no line in " % path in board.norm(r.out)


@needs_bash
def test_a_deploy_list_cut_short_refuses_though_every_file_it_lists_matches(board):
    """One line, and it is right. The harness beside it was edited on the board, and nothing says so."""
    man = board.home / "gate2" / "deploy.sha256"
    man.write_bytes(b"".join(l for l in man.read_bytes().splitlines(True) if l.endswith(b"/ivshmem_ring.py\n")))
    assert len(man.read_bytes().splitlines()) == 1
    with open(board.R + "/run-bell.sh", "ab") as f:
        f.write(b"\n# edited on the board\n")
    r = board.run("G5", "G12", "G0")
    for step in ("G5", "G12", "G0"):
        refused(r, step, "deploy-hash")
    assert harness_calls(r) == []


def test_every_deployed_file_the_runner_names_is_in_some_steps_list():
    """A step that starts or reads a deployed file names it in files_of, so that the file is held
    to the manifest: no path under the deploy is in the code and in no step's list."""
    code = _code(_text(SCRIPT))
    named = set(_GC + n for n in re.findall(r"\$R/([\w.-]+)", code)) | set(_EL + n for n in re.findall(r"\$E/([\w.-]+)", code))
    named |= set(p for p in re.findall(r"\$REPO/((?:orin-native|ipc-test|scripts)/[\w./-]+\.\w+)", code))
    listed = set(f for v in STEP_FILES.values() for f in v)
    assert named == listed, (sorted(named - listed), sorted(listed - named))
    body = re.search(r"\nfiles_of\(\) \{\n(.*?)\n\}\n", code, re.S).group(1)
    for step, files in STEP_FILES.items():
        line = [l for l in body.split("\n") if re.match(r"\t\t(?:G\d+\|)*%s(?:\|G\d+)*\) " % step, l)]
        assert len(line) == 1, (step, line)
        got = line[0].split('FILES="')[1].split('"')[0]
        for short, full in (("$launcher", _LAUNCHER), ("$gc/", _GC), ("$el/", _EL), ("$dds/", _DDS)):
            got = got.replace(short, full)
        assert tuple(got.split()) == files, (step, got)


@needs_bash
def test_the_deployed_copy_of_the_runner_wants_its_own_three_files_in_the_deploys_manifest(board):
    """Run as the runbook says, from the deploy: the runner, the stick rule it sources and the
    provisioning script it calls are files of that deploy, and the manifest has to list them. A
    copy run from anywhere else is not held by the manifest, and says so."""
    r = board.run("G5")
    assert r.log == ["G5 PASS"] and re.search(r"(?m)^WARNING: this gate2-smoke\.sh is not the copy under .*/gate2/repo/scripts/orin, "
                                                r"so the deploy's manifest does not hold it -- test use only$", r.out), r.out[:1500]
    orin = board.REPO + "/scripts/orin"
    os.makedirs(orin)
    for src in (SCRIPT, LIB, os.path.join(ORIN, "provision-orin-r39.sh")):
        shutil.copy(src, orin + "/" + os.path.basename(src))
    board.runner = orin + "/gate2-smoke.sh"
    r = board.run("G5")
    refused(r, "G5", "deploy-hash")                 # the three are deployed, and the list is the one from before them
    assert "has no line in " in r.out and harness_calls(r) == []
    board.write_manifests()
    r = board.run("G5")
    assert r.log[-1] == "G5 PASS" and "is not the copy under" not in r.out, (r.log, r.out[-1500:])
    for name in ("gate2-smoke.sh", "lib-stick.sh", "provision-orin-r39.sh"):
        board.write_manifests()
        board.drop_from_deploy_list("scripts/orin/" + name)
        r = board.run("G5", "G0")
        refused(r, "G5", "deploy-hash")
        refused(r, "G0", "deploy-hash")
        assert "scripts/orin/%s has no line in " % name in r.out and harness_calls(r) == []


@needs_bash
@pytest.mark.parametrize("change, why", [
    (dict(provision_rc="1\n"), "provision-check"), (dict(provision_rc="2\n"), "provision-check"),
    (dict(my_groups="%s adm sudo\n" % LOGIN), "kvm-group"), (dict(my_groups="%s adm sudo kvmx\n" % LOGIN), "kvm-group"),
    (dict(sudo_denied="1\n"), "kernel-cursor"),
], ids=["apply-has-something-to-do", "something-differs", "not-in-kvm", "a-group-named-alike", "no-sudo"])
def test_a_board_that_is_not_provisioned_refuses_every_step(board, change, why):
    for k, v in change.items():
        board.set(k, v)
    r = board.run("G0", "G5")
    refused(r, "G0", why)
    refused(r, "G5", why)
    assert harness_calls(r) == []
    if why == "provision-check":
        assert "provision check" in r.calls and "provision-orin-r39.sh check did not exit 0" in r.out
        session = [p for p in (board.home / "gate2" / "out" / "session").iterdir()]
        assert len(session) == 1 and b"nothing for apply to do" in (session[0] / "provision-check.log").read_bytes(), "its lines are kept"


# ------------------------------------------------------------------ the installer stick

VM_STEPS_TRIED = ("G0", "G1", "G5", "G12", "G16")


@needs_bash
@pytest.mark.parametrize("lsblk, findmnt, says", [
    (LSBLK + STICK, MOUNTS, "removable block device: sda"),
    (LSBLK + 'NAME="sdb" RM="0" TRAN="usb" TYPE="disk"\n', MOUNTS, "removable block device: sdb"),
    (LSBLK, MOUNTS + "/media/%s/writable /dev/sda1 rw,nosuid,nodev,relatime\n" % LOGIN, "1 mount under /media"),
    (LSBLK + STICK, MOUNTS + VENDOR_MOUNT, "removable block device: sda; not counted: the vendor's read-only image (L4T-README"),
    ("", MOUNTS, "cannot tell whether a stick is in"),
], ids=["removable", "usb-not-flagged-removable", "mounted", "beside-the-vendors-image", "device-list-unreadable"])
def test_a_stick_refuses_every_step_that_creates_a_kvm_vm_and_g0_is_one(board, lsblk, findmnt, says):
    board.set("lsblk", lsblk)
    board.set("findmnt", findmnt)
    _put(board.sys / "block" / "loop0" / "loop" / "backing_file", "/opt/nvidia/l4t-usb-device-mode/filesystem.img\n")
    r = board.run(*VM_STEPS_TRIED)
    for step in VM_STEPS_TRIED:
        refused(r, step, "stick")
    assert harness_calls(r) == [], "no VM was created with the stick in: %s" % harness_calls(r)
    # R1's rule and R1's words, with the runner as the one that refuses.
    line = [l for l in r.out.split("\n") if "refuses while it is there" in l][0]
    assert says in line and LOGIN not in line
    assert ("every step that creates a KVM VM refuses while it is there: a reset would walk the boot order with an unattended "
            "installer attached. The owner removes it; PROVISION_ALLOW_REMOVABLE=1 is the owner's override") in line


@needs_bash
def test_every_step_but_the_two_without_a_guest_is_held_to_the_stick_rule(board):
    board.set("lsblk", LSBLK + STICK)
    board.set("tegrastats", TEGRA_BUSY)
    r = board.run(*STEPS, **GPU)
    assert r.log == [("%s PASS" % s) if s in NO_VM_STEPS else ("%s FAIL refused-stick" % s) for s in STEPS[:20]] + [
        "G20 FAIL refused-stick", "G21 FAIL refused-stick"], r.log
    assert [c.split()[0] for c in harness_calls(r)] == ["fma", "llama-cli"]


@needs_bash
def test_the_vendors_read_only_image_under_media_is_not_a_stick_to_the_runner_either(board):
    board.set("lsblk", LSBLK + 'NAME="loop0" RM="0" TRAN="" TYPE="loop"\n')
    board.set("findmnt", MOUNTS + VENDOR_MOUNT)
    _put(board.sys / "block" / "loop0" / "loop" / "backing_file", "/opt/nvidia/l4t-usb-device-mode/filesystem.img\n")
    r = board.run("G0", "G5")
    assert r.log == ["G0 PASS", "G5 PASS"], (r.log, r.out[-1200:])
    # The same mount, read-write, counts: the rule is the library's, with every condition of it.
    board.set("findmnt", MOUNTS + VENDOR_MOUNT.replace(" ro,", " rw,"))
    refused(board.run("G0"), "G0", "stick")


@needs_bash
def test_the_owners_override_is_the_provisioning_scripts_and_lets_a_vm_step_proceed(board):
    board.set("lsblk", LSBLK + STICK)
    r = board.run("G0", "G5", PROVISION_ALLOW_REMOVABLE="1")
    assert r.log == ["G0 PASS", "G5 PASS"], (r.log, r.out[-1200:])
    assert "removable block device: sda -- allowed by PROVISION_ALLOW_REMOVABLE=1, the owner's override" in r.out
    for other in ({"PROVISION_ALLOW_REMOVABLE": "yes"}, {"GATE2_ALLOW_REMOVABLE": "1"}):
        refused(board.run("G0", **other), "G0", "stick")


# ------------------------------------------------------------------ after every step: a refusal for the next

def _mk(path, text=""):
    return "mkdir -p '%s'; printf '%%s' '%s' > '%s'\n" % (_fwd(os.path.dirname(str(path))), text, _fwd(path))


def _left_wrong(b):
    """For each item of the check after a step: a harness hook that leaves it wrong, the item's
    name, and what the runner then says."""
    s, run, cpu = b.sys, b.run_root, b.sys / "devices" / "system" / "cpu"
    return {
        "kernel-lines": ('echo "Unable to handle kernel paging request at virtual address made-up" >> "$S/kjournal"\n', "kernel-new.log"),
        "boot-changed": ("echo 9b9b9b9b-1111-2222-3333-444444444444 > '%s'\n" % _fwd(b.proc / "sys" / "kernel" / "random" / "boot_id"), "boot"),
        "boot-unreadable": ("rm -f '%s'\n" % _fwd(b.proc / "sys" / "kernel" / "random" / "boot_id"), "boot"),
        "pstore": (_mk(s / "fs" / "pstore" / "dmesg-ramoops-0", "made up"), "pstore"),
        "confinement": ('echo "3,5" > "$S/allowed-user@1000.service"\n', "user@1000.service"),
        "confinement-session": ('echo "3,5" > "$S/allowed-session-3.scope"\n', "session-3.scope"),
        "confinement-init": ('echo "3,5" > "$S/allowed-init.scope"\n', "init.scope"),
        "confinement-drop-in": (_mk(run / "systemd" / "system.control" / "system.slice.d" / "50-AllowedCPUs.conf", "[Slice]"), "50-AllowedCPUs.conf"),
        "tracing-instance": ("mkdir -p '%s'\n" % _fwd(s / "kernel" / "tracing" / "instances" / "metaltick"), "instance"),
        "tracing-event": ("echo timer:hrtimer_expire_entry > '%s'\n" % _fwd(s / "kernel" / "tracing" / "set_event"), "event"),
        "idle-states": ("echo 1 > '%s'\n" % _fwd(cpu / "cpu1" / "cpuidle" / "state1" / "disable"), "cpuidle"),
        "governor": ("echo performance > '%s'\n" % _fwd(cpu / "cpufreq" / "policy4" / "scaling_governor"), "schedutil"),
        "udev-queue": (_mk(run / "udev" / "queue"), "udev"),
        "udev-settle": ('echo 1 > "$S/settle_rc"\n', "udev"),
        "leftover-netns": (_mk(run / "netns" / "ladder"), "ladder"),
        "leftover-veth": ("mkdir -p '%s'\n" % _fwd(s / "class" / "net" / "veth-l"), "veth-l"),
        "leftover-process": ('echo "   4301 /made-up/ladder/monitor-native 7100" >> "$S/procs_static"\n', "monitor-native"),
        "leftover-socket": (_mk(b.tmp / "a6-kick-host.sock"), "a6-kick-host.sock"),
        "leftover-shm": (_mk(b.shm / "a6-shm-host"), "a6-shm-host"),
    }


ITEMS = ["kernel-lines", "boot-changed", "boot-unreadable", "pstore", "confinement", "confinement-session", "confinement-init",
         "confinement-drop-in", "tracing-instance", "tracing-event", "idle-states",
         "governor", "udev-queue", "udev-settle", "leftover-netns", "leftover-veth", "leftover-process", "leftover-socket", "leftover-shm"]
ITEM_NAME = {"confinement-drop-in": "confinement", "tracing-instance": "tracing", "tracing-event": "tracing", "udev-queue": "udev",
             "udev-settle": "udev", "leftover-veth": "leftover-netns", "leftover-socket": "leftover-files", "leftover-shm": "leftover-files",
             "boot-unreadable": "boot-changed", "confinement-session": "confinement", "confinement-init": "confinement"}


@needs_bash
@pytest.mark.parametrize("item", ITEMS)
def test_each_item_a_step_leaves_wrong_refuses_the_next_step_and_is_named(board, item):
    hook, says = _left_wrong(board)[item]
    board.set("post-run-bell.sh", POST_LAT + hook)
    r = board.run("G5", "G6", "G0")
    name = ITEM_NAME.get(item, item)
    assert r.log == ["G5 PASS", "G6 FAIL refused-" + name, "G0 FAIL refused-" + name] and r.returncode == 2, (r.log, r.out[-1500:])
    assert [c for c in r.calls if c.startswith("harness")] == ["harness run-bell.sh "], "the step's own smoke ran, and nothing after it"
    assert not [c for c in r.calls if c.startswith("qemu-system-aarch64")]
    assert says in r.out and name in r.out, r.out[-800:]
    # It is still wrong in the next call, which refuses before its first step.
    if item not in ("leftover-process", "kernel-lines", "boot-changed"):
        board.set("post-run-bell.sh", POST_LAT)
        r = board.run("G5")
        assert r.log[-1] == "G5 FAIL refused-" + name and not [c for c in r.calls if c.startswith("harness")], (r.log, r.out[-800:])


@needs_bash
def test_udev_is_looked_at_twice_a_second_apart_before_it_is_called_busy(board):
    """An event of the board's own that arrives between the settle and the look leaves a queue
    file for a moment. A queue that is still there at the second look is the item's refusal."""
    board.set("post-run-bell.sh", POST_LAT + _mk(board.run_root / "udev" / "queue"))
    board.set("on_sleep", "rm -f '%s'\n" % _fwd(board.run_root / "udev" / "queue"))
    r = board.run("G5", "G6")
    assert r.log == ["G5 PASS", "G6 PASS"], (r.log, r.out[-1500:])
    assert "sleep 1" in r.calls, "the second look came a second after the first"


@needs_bash
def test_a_state_that_cannot_be_read_counts_as_wrong(board):
    """Nothing there to read is not "nothing wrong": no cpuidle state at all, no cpufreq policy at
    all, or one of them without its file, refuses as a disabled state or another governor does."""
    cpu = board.sys / "devices" / "system" / "cpu"
    cases = (([board.sys / "kernel" / "tracing" / "instances"], "tracing"), ([board.sys / "fs" / "pstore"], "pstore"),
             ([cpu / "cpufreq"], "governor"), ([cpu / "cpufreq" / "policy0", cpu / "cpufreq" / "policy4"], "governor"),
             ([cpu / "cpufreq" / "policy4" / "scaling_governor"], "governor"),
             ([cpu / "cpu0" / "cpuidle", cpu / "cpu1" / "cpuidle"], "idle-states"),
             ([cpu / "cpu1" / "cpuidle" / "state1" / "disable"], "idle-states"), ([cpu / "online"], "confinement"))
    for i, (gone, name) in enumerate(cases):
        b = Board(board.root.parent / ("unread-%d" % i), board.tools)
        for path in gone:
            target = b.root / os.path.relpath(str(path), str(board.root))
            if target.is_dir():
                shutil.rmtree(str(target))
            else:
                target.unlink()
        r = b.run("G5")
        assert r.log == ["G5 FAIL refused-" + name], (name, [str(g) for g in gone], r.log, r.out[-600:])


@needs_bash
def test_kernel_lines_since_the_cursor_only_the_stop_pattern_stops_and_err_lines_are_listed(board):
    """A plain grep for oops would match the ramoops lines the board prints at rest, and other
    lines at err level are for a human to read: neither is a stop."""
    board.set("post-run-bell.sh", POST_LAT + "cat >> \"$S/kjournal\" <<'EOF'\nramoops: using 0x200000@0x made-up\nnvme nvme0: made-up notice\n"
              "<3>tegra-xusb made-up: firmware request failed\nEOF\n")
    r = board.run("G5", "G6")
    assert r.log == ["G5 PASS", "G6 PASS"], (r.log, r.out[-1200:])
    a = board.attempt("G5")
    assert (a / "kernel-err.log").read_bytes().decode() == "tegra-xusb made-up: firmware request failed\n"
    assert "kernel-err.log" in r.out and "firmware request failed" not in r.out, "listed in a file, for a human; not printed"
    assert (a / "kernel-new.log").read_bytes().decode().split("\n")[:2] == ["ramoops: using 0x200000@0x made-up", "nvme nvme0: made-up notice"]
    assert not (board.attempt("G6") / "kernel-new.log").exists(), "read once: the cursor moved past them"


@needs_bash
@pytest.mark.parametrize("line", ["Internal error: Oops: 0000000096000004 [#1] PREEMPT SMP", "Unable to handle kernel NULL pointer dereference",
                                  "BUG: Bad page state in process qemu-system-aar", "WARNING: CPU: 2 PID: 4242 at made-up.c:1",
                                  "Call trace:", "Oops: made up"])
def test_each_form_of_the_stop_pattern_refuses_the_next_step(board, line):
    board.set("post-run-bell.sh", POST_LAT + "cat >> \"$S/kjournal\" <<'EOF'\nnvme nvme0: made-up notice\n" + line + "\nEOF\n")
    r = board.run("G5", "G6")
    assert r.log == ["G5 PASS", "G6 FAIL refused-kernel-lines"], (r.log, r.out[-800:])
    assert "4242" not in r.out and "0000000096000004" not in r.out, "the lines are in a file, and are not printed"
    assert line in (board.attempt("G5") / "kernel-new.log").read_bytes().decode()


@needs_bash
def test_the_cursor_moves_on_with_what_was_read_and_a_stop_is_refused_again_until_a_fresh_cursor_is_asked_for(board):
    r = board.run("G5")
    assert r.log == ["G5 PASS"]
    state = board.home / "gate2" / "state"
    assert (state / "cursor").read_bytes().strip() == b"cur-0", "the cursor taken before the first step"
    board.set("post-run-bell.sh", POST_LAT + 'echo "nvme nvme0: made-up notice" >> "$S/kjournal"\n')
    r = board.run("G5")
    assert r.log[-1] == "G5 PASS" and (state / "cursor").read_bytes().strip() == b"cur-1", "moved past the line that was read"
    # A stop: the cursor stays where it was, so the next call reads the same lines and refuses.
    board.set("post-run-bell.sh", POST_LAT + 'echo "Oops: made up" >> "$S/kjournal"\n')
    r = board.run("G5", "G6")
    assert r.log[-2:] == ["G5 PASS", "G6 FAIL refused-kernel-lines"]
    assert (state / "cursor").read_bytes().strip() == b"cur-1"
    board.set("post-run-bell.sh", POST_LAT)
    r = board.run("G6")
    assert r.log[-1] == "G6 FAIL refused-kernel-lines" and harness_calls(r) == [], "still refused: nobody has said the lines were read"
    assert board.get("cursors_asked").split()[-1] == "cur-1"
    # The orchestrator's word, once stop condition 1 has been dealt with: a fresh cursor.
    r = board.run("G6", GATE2_FRESH_CURSOR="1")
    assert r.log[-1] == "G6 PASS" and "GATE2_FRESH_CURSOR=1" in r.out, (r.log, r.out[-800:])
    assert (state / "cursor").read_bytes().strip() == b"cur-2"
    assert board.run("G6").log[-1] == "G6 PASS", "and the calls after it go on from there"


@needs_bash
def test_a_kernel_journal_that_cannot_be_read_counts_as_a_stop(board):
    """Nothing can be said of the kernel's lines, so nothing more is run."""
    board.set("post-run-bell.sh", POST_LAT + 'echo 1 > "$S/journal_rc"\n')
    r = board.run("G5", "G6")
    assert r.log == ["G5 PASS", "G6 FAIL refused-kernel-lines"], (r.log, r.out[-800:])
    board.unset("journal_rc")
    board.set("post-run-bell.sh", POST_LAT)
    # A cursor the journal no longer knows (rotated away): refused, until a fresh one is asked for.
    _put(board.G + "/state/cursor", "a-cursor-the-journal-does-not-know\n")
    r = board.run("G6")
    assert r.log[-1] == "G6 FAIL refused-kernel-lines" and "GATE2_FRESH_CURSOR=1" in r.out, (r.log, r.out[-800:])
    assert board.run("G6", GATE2_FRESH_CURSOR="1").log[-1] == "G6 PASS"


@needs_bash
def test_a_boot_that_changed_between_calls_refuses_until_it_is_said_to_be_a_new_one(board):
    assert board.run("G5").log == ["G5 PASS"]
    _put(board.proc / "sys" / "kernel" / "random" / "boot_id", "7c7c7c7c-1111-2222-3333-444444444444\n")
    r = board.run("G5", "G0")
    refused(r, "G5", "boot-changed")
    refused(r, "G0", "boot-changed")
    assert harness_calls(r) == [] and "reset_reason" in r.out and "7c7c7c7c" not in r.out
    r = board.run("G5", GATE2_NEW_BOOT="1")
    assert r.log[-1] == "G5 PASS" and "GATE2_NEW_BOOT=1" in r.out
    assert board.run("G5").log[-1] == "G5 PASS", "the new boot is now the one on record"
    os.unlink(str(board.proc / "sys" / "kernel" / "random" / "boot_id"))
    refused(board.run("G5"), "G5", "boot-changed")


@needs_bash
def test_a_guest_kept_for_the_next_step_of_its_boot_is_not_a_leftover_but_another_one_is(board):
    """Between G8 and G9 the guest is up on purpose. Anything else that is up is not."""
    board.set("post-run-stamp.sh", board.get("post-run-stamp.sh")
              + 'echo "   4401 /usr/bin/qemu-system-aarch64 -kernel /made-up/other.bin" >> "$S/procs_static"\n')
    r = board.run("G8", "G9", "G10")
    assert r.log == ["G8 PASS", "G9 FAIL refused-leftover-process", "G10 FAIL refused-leftover-process"], (r.log, r.out[-1200:])
    assert r.calls.count("qemu-term") == 1 and board.alive() == [], "its own guest is stopped when the steps that share it will not run"


@needs_bash
def test_a_step_refused_in_the_middle_of_a_shared_boot_stops_the_guest(board):
    board.set("post-run-stamp.sh", board.get("post-run-stamp.sh") + "printf 'another disk\\n' > '%s/disk-qemu'\n" % board.IMG)
    r = board.run("G8", "G9")
    assert r.log == ["G8 PASS", "G9 FAIL refused-image-hash"], (r.log, r.out[-1200:])
    assert r.calls.count("qemu-term") == 1 and board.alive() == []


# ------------------------------------------------------------------ gap 4i

@needs_bash
def test_the_native_monitor_is_moved_after_g4_ran_whatever_it_returned_and_not_when_g4_was_refused(board):
    board.set("rc-run-ladder.sh", "1\n")
    r = board.run("G4")
    assert r.log == ["G4 FAIL harness-exit"]
    assert not (board.home / "ladder" / "monitor-native").exists() and len(list((board.home / "gate2" / "bin").glob("*/monitor-native"))) == 1
    b = Board(board.root.parent / "refused", board.tools)
    b.set("lsblk", LSBLK + STICK)
    refused(b.run("G4"), "G4", "stick")
    assert (b.home / "ladder" / "monitor-native").exists() and not (b.home / "gate2" / "bin").exists()
    # A ladder that was built without its source hash beside it: the binary is still moved.
    b = Board(board.root.parent / "nohash", board.tools)
    os.unlink(b.H + "/ladder/monitor-native.source-sha256")
    r = b.run("G4")
    b.kill_all()
    assert r.log == ["G4 PASS"] and not (b.home / "ladder" / "monitor-native").exists()


@needs_bash
def test_test_overrides_are_announced(board):
    r = board.run("G0")
    for name in ("SYS_ROOT", "PROC_ROOT", "RUN_ROOT", "SHM_ROOT", "TMP_ROOT", "GATE2_PROVISION"):
        assert re.search(r"(?m)^WARNING: %s overridden to .* -- test use only$" % name, r.out), name


# ------------------------------------------------------------------ what a session is read from

# How the header says a call is started and read: detached, waited for in the same session, then
# its exit status and its lines of the log.
SESSION_FORM = ("setsid --wait nohup bash gate2-smoke.sh G5 > ~/gate2/run-<utc>.log 2>&1 < /dev/null &",
                'tail --pid=$! -f /dev/null; wait $!; echo "exit $?"; tail -n 1 ~/gate2/gate2.log')


def _header(text):
    """The script's header: its comment lines up to the first line of code."""
    return text[:text.index("\nset -u\n")]


def _said(text):
    """The header as running text, whatever its line breaks."""
    return " ".join(l.lstrip("#").strip() for l in _header(text).split("\n"))


def test_the_header_says_how_a_call_is_started_and_what_is_read_of_it():
    head = _header(_text(SCRIPT))
    for line in SESSION_FORM:
        assert "\n#     " + line + "\n" in head, line
    said = _said(_text(SCRIPT))
    # The exit status is one of the two things read, and what the check after the call's last
    # step finds is in it.
    assert "also after the call's last step" in said and "whatever else failed" in said
    assert "a line could not be written to the log" in said
    assert "--wait is for a shell with job control" in said, "and why setsid is told to wait"


@needs_bash
@pytest.mark.parametrize("item", ITEMS)
def test_an_item_left_wrong_by_the_only_step_of_a_call_is_the_calls_exit_status_and_the_next_calls_refusal(board, item):
    """Most sessions of the runbook are one step, and a session is read from two things: the
    call's exit status and the last lines of gate2.log. What the check after the call's last step
    finds has no later step to refuse. The step's own line stands; the call says the item in its
    output and by its exit status; and the next call refuses by the item's name."""
    hook, _says = _left_wrong(board)[item]
    name = ITEM_NAME.get(item, item)
    board.set("post-run-bell.sh", POST_LAT + hook)
    r = board.run("G5")
    assert r.log == ["G5 PASS"], (r.log, r.out[-1500:])
    assert r.returncode == 2, "exit %d after a check that found %s wrong: %s" % (r.returncode, name, r.out[-600:])
    assert "REFUSED from here on: %s." % name in r.out, r.out[-800:]
    board.set("post-run-bell.sh", POST_LAT)
    r = board.run("G6")
    assert r.log == ["G5 PASS", "G6 FAIL refused-" + name] and r.returncode == 2, (r.log, r.out[-800:])
    assert harness_calls(r) == []


@needs_bash
def test_a_step_that_failed_and_left_an_item_wrong_ends_the_call_with_the_refusals_exit_status(board):
    """2 wins over 1: the step's own FAIL line stands, and the call's status says that the board
    is not as a step must leave it."""
    cpu = board.sys / "devices" / "system" / "cpu"
    board.set("rc-run-bell.sh", "1\n")
    board.set("post-run-bell.sh", POST_LAT + "echo performance > '%s'\n" % _fwd(cpu / "cpufreq" / "policy4" / "scaling_governor"))
    r = board.run("G5")
    assert r.log == ["G5 FAIL harness-exit"] and r.returncode == 2, (r.log, r.returncode, r.out[-600:])
    assert "REFUSED from here on: governor." in r.out


@needs_bash
def test_gap_4o_an_item_found_wrong_before_the_retry_is_said_and_is_the_calls_exit_status(board):
    """The first load failed with the NvMap error and left the governor changed. No second load is
    started on a board that is not at rest; and as after any step, the call says the item as its
    refusal, in its output and by its exit status."""
    cpu = board.sys / "devices" / "system" / "cpu"
    _put(board.G + "/gate2.log", "G18 PASS\n")
    board.set("llama_stderr", LLAMA_ERR + NVMAP)
    board.set("llama_rc", "1\n")
    board.set("llama_stdout", "")
    board.set("llama_hook", "echo performance > '%s'\n" % _fwd(cpu / "cpufreq" / "policy4" / "scaling_governor"))
    r = board.run("G19", **GPU)
    assert r.log == ["G18 PASS", "G19 FAIL nvmap"], (r.log, r.out[-1500:])
    assert [c.split()[0] for c in r.calls if c.startswith("llama-cli")] == ["llama-cli"], "no second load on a board that is not at rest"
    assert len(board.attempts("G19")) == 1
    assert "REFUSED from here on: governor." in r.out and r.returncode == 2, (r.returncode, r.out[-800:])
    assert r.out.count("REFUSED from here on") == 1 and r.out.count("not as a step must leave it") == 1, "said once: the board is not looked at again"
    r = board.run("G20", **GPU)
    assert r.log[-1] == "G20 FAIL refused-governor" and r.returncode == 2 and harness_calls(r) == [], (r.log, r.out[-800:])


@needs_bash
@pytest.mark.skipif(os.name == "nt" or shutil.which("setsid") is None, reason="the board's own form: setsid, nohup and tail --pid")
@pytest.mark.parametrize("item", [None, "governor", "kernel-lines", "pstore", "leftover-socket"])
@pytest.mark.parametrize("shell", ["", "set -m\n"], ids=["no-job-control", "job-control"])
def test_started_and_read_as_the_header_says_a_session_shows_what_the_check_after_its_only_step_found(board, item, shell):
    """The two lines of the header, run as they stand (the script by its path, the run log under
    one name): the status that is echoed and the log's last line are all a session reads. In a
    shell without job control, as `ssh host '...'` gives, and in one with it, where setsid forks
    and the status is the runner's only because setsid waits for it."""
    if item:
        board.set("post-run-bell.sh", POST_LAT + _left_wrong(board)[item][0])
    start, read = SESSION_FORM
    start = start.replace("gate2-smoke.sh", "'%s'" % SCRIPT).replace("<utc>", "made-up")
    r = subprocess.run([BASH, "-c", shell + start + "\n" + read + "\n"], capture_output=True, text=True, timeout=300, env=board.env(),
                       stdin=subprocess.DEVNULL)
    assert r.stdout.split("\n")[:2] == ["exit %d" % (2 if item else 0), "G5 PASS"], (r.stdout, r.stderr)
    said = (board.home / "gate2" / "run-made-up.log").read_bytes().decode()
    last = [l for l in said.split("\n") if l.strip()][-1]
    if item:
        assert last.startswith("REFUSED from here on: %s." % ITEM_NAME.get(item, item)), last
    else:
        assert "REFUSED" not in said, said[-600:]


def _refused_an_append(path):
    """Whether this bash, as this user, is refused an append to the file (a root is not)."""
    return subprocess.run([BASH, "-c", ': 2> /dev/null >> "$1"', "_", _fwd(path)], capture_output=True, timeout=60).returncode != 0


@needs_bash
@pytest.mark.parametrize("how", ["read-only", "a-directory"])
def test_a_line_that_cannot_be_written_to_the_log_is_said_so_and_ends_the_call(board, how):
    """The log is the one file a result is read from. A line that could not be appended to it is
    not said as if it were there: the call says that it was not written, runs nothing more, and
    exits 2, so that an earlier line of the same step is not read as this attempt's."""
    glog = board.home / "gate2" / "gate2.log"
    if how == "read-only":
        assert board.run("G5").log == ["G5 PASS"]
        os.chmod(str(glog), 0o444)
        if not _refused_an_append(glog):
            os.chmod(str(glog), 0o644)
            pytest.skip("this user can append to a read-only file")
    else:
        glog.mkdir()
    board.set("rc-run-bell.sh", "1\n")
    try:
        r = board.run("G5", "G6")
        # A call of one step, and the step passes: its PASS is not in the log either, and the
        # call's exit status is not the 0 of a pass.
        one = board.run("G6")
    finally:
        if how == "read-only":
            os.chmod(str(glog), 0o644)
    assert r.returncode == 2, (r.returncode, r.out[-800:])
    assert r.log == (["G5 PASS"] if how == "read-only" else []), "nothing could be added: %s" % r.log
    lines = r.out.split("\n")
    assert "G5 FAIL harness-exit" not in lines, "the line is not said as if it had been written"
    assert [l for l in lines if l.startswith("NOT WRITTEN") and "G5 FAIL harness-exit" in l], r.out[-800:]
    assert [c for c in r.calls if c.startswith("harness")] == ["harness run-bell.sh "], "and no further step is run without a log to write to"
    assert [l for l in lines if l.startswith("NOT WRITTEN") and "G6 FAIL " in l], "the step that was not run has its line said the same way"
    assert one.returncode == 2 and one.log == r.log, (one.returncode, one.log, one.out[-800:])
    said = one.out.split("\n")
    assert "G6 PASS" not in said and [l for l in said if l.startswith("NOT WRITTEN") and '"G6 PASS"' in l], one.out[-800:]


@needs_bash
@pytest.mark.parametrize("what, why, says", [("boot-id", "boot-changed", "the boot on record cannot be written"),
                                             ("cursor", "kernel-cursor", "the kernel journal cursor cannot be written")])
def test_a_state_file_that_cannot_be_written_refuses_the_call(board, what, why, says):
    """The boot on record and the cursor are what a refusal between two calls rests on. A call
    that cannot write one of them would leave the next call nothing to tell a reset by, or a
    kernel line: it is refused, by the item the file stands for."""
    (board.home / "gate2" / "state" / what).mkdir(parents=True)     # where the file should be, nothing can be written
    r = board.run("G5", "G0")
    refused(r, "G5", why)
    refused(r, "G0", why)
    assert harness_calls(r) == [] and says in r.out, r.out[-800:]


@needs_bash
def test_a_state_directory_that_cannot_be_written_to_refuses_before_a_reset_could_go_unseen(board):
    """With ~/gate2/state unwritable the boot on record was never written, and a boot id that
    changed between two calls refused nothing. The first call is refused already."""
    state = board.home / "gate2" / "state"
    state.mkdir()
    os.chmod(str(state), 0o555)
    try:
        if not _refused_an_append(state / "probe"):
            pytest.skip("this user can write into a read-only directory")
        r = board.run("G5")
        refused(r, "G5", "boot-changed")
        assert harness_calls(r) == []
        _put(board.proc / "sys" / "kernel" / "random" / "boot_id", "7c7c7c7c-1111-2222-3333-444444444444\n")
        refused(board.run("G5"), "G5", "boot-changed")
    finally:
        os.chmod(str(state), 0o755)


@needs_bash
def test_a_cursor_that_cannot_be_moved_on_after_a_step_counts_as_kernel_lines(board):
    """The kernel's new lines were read and were no stop, and the cursor could not be written past
    them: the next call would read them again from a cursor nobody can vouch for."""
    cursor = _fwd(board.home / "gate2" / "state" / "cursor")
    board.set("post-run-bell.sh", POST_LAT + 'echo "nvme nvme0: made-up notice" >> "$S/kjournal"\n'
              + "rm -f '%s'; mkdir '%s'\n" % (cursor, cursor))
    r = board.run("G5", "G6")
    assert r.log == ["G5 PASS", "G6 FAIL refused-kernel-lines"] and r.returncode == 2, (r.log, r.out[-800:])
    assert "the kernel journal cursor cannot be written" in r.out


# ------------------------------------------------------------------ the shared rule's file, and the order of the refusals

LIB_NOT_THE_RULE = {
    "empty": lambda t: "",
    "comments-only": lambda t: "".join(l + "\n" for l in t.split("\n") if l.startswith("#")),
    "cut-before-first-line": lambda t: t[:t.index("\nfirst_line() {")] + "\n",
    "cut-before-stick-rule": lambda t: t[:t.index("\n# Looks, and says what it found")] + "\n",
    "cut-inside-stick-rule": lambda t: t[:t.index("\tout=$(findmnt")],
    "a-syntax-error-inside-stick-rule": lambda t: _swap(t, '\tif [ -n "$found" ]; then what=', '\tif [ -n "$found" ]; then then what='),
    "stick-rule-renamed": lambda t: _swap(t, "\nstick_rule() {", "\nstick_rule_as_it_was() {"),
    "first-line-renamed": lambda t: _swap(t, "\nfirst_line() {", "\nfirst_line_as_it_was() {"),
    # Both functions are defined, and the file does not read to its end.
    "a-syntax-error-after-the-rule": lambda t: t + "\nif then\n",
}


@needs_bash
@pytest.mark.parametrize("how", sorted(LIB_NOT_THE_RULE))
@pytest.mark.parametrize("steps", [("G5", "G0"), ("G18", "G19")], ids=["vm-steps", "gpu-loads"])
def test_a_library_that_is_not_the_stick_rule_ends_the_call_before_anything(board, how, steps):
    """A lib-stick.sh that is there and readable and is not the rule (cut short, broken, a
    function renamed): the call ends before it has made, started or written anything. A VM step
    is not refused under a wording that is empty, and the two GPU loads, which the stick rule
    does not hold, are not run from a copy whose library is not the reviewed one."""
    copy = board.root / "copy"
    copy.mkdir()
    for src in (SCRIPT, os.path.join(ORIN, "provision-orin-r39.sh")):
        shutil.copy(src, str(copy / os.path.basename(src)))
    _put(copy / "lib-stick.sh", LIB_NOT_THE_RULE[how](_text(LIB)))
    board.runner = _fwd(copy / "gate2-smoke.sh")
    board.set("tegrastats", TEGRA_BUSY)
    _put(board.G + "/gate2.log", "G18 PASS\n")
    before = board.tree(board.home / "gate2")
    r = board.run(*steps, **GPU)
    assert r.returncode == 1 and "FATAL: lib-stick.sh" in r.err, (r.returncode, r.err[-600:], r.out[-600:])
    assert r.calls == [], "nothing was started: %s" % r.calls
    assert r.log == ["G18 PASS"] and board.tree(board.home / "gate2") == before, "no line, and nothing made under ~/gate2"
    assert not (board.home / "gate2" / "state").exists() and not (board.home / "gate2" / "out").exists()


@needs_bash
@pytest.mark.parametrize("why", ["deploy-hash", "governor"])
def test_a_refused_calls_lines_name_the_calls_refusal_and_the_stick_only_where_a_step_could_otherwise_run(board, why):
    """The call's own refusal is asked before the stick rule: with both, every step's line names
    what refused the call, a VM step's like the others'."""
    cpu = board.sys / "devices" / "system" / "cpu"
    board.set("lsblk", LSBLK + STICK)
    if why == "deploy-hash":
        with open(board.R + "/run-bell.sh", "ab") as f:
            f.write(b"\n# edited on the board\n")
    else:
        _put(cpu / "cpufreq" / "policy4" / "scaling_governor", "performance\n")
    r = board.run("G0", "G5", "G18", **GPU)
    for step in ("G0", "G5", "G18"):
        refused(r, step, why)
    assert harness_calls(r) == [] and "installer stick:" not in r.out, r.out[-800:]
    assert "lsblk -d -n -P -o NAME,RM,TRAN,TYPE" not in r.calls, "the rule is not asked for a step that is not run anyway"


# ------------------------------------------------------------------ G19's tokens, the stop pattern's edge, a failed launch

@needs_bash
@pytest.mark.parametrize("out, why", [
    ("hello\n", "tokens"), ("hello", "tokens"), ("  hello \nhello\n\n", "tokens"),
    ("hello\n\nHello! How can I help you today?\n", None), ("hello there\n", None),
], ids=["the-prompt-alone", "the-prompt-without-a-newline", "the-prompt-twice", "the-prompt-then-a-reply", "a-word-beyond-the-prompt"])
def test_g19s_tokens_are_something_printed_besides_the_prompts_own_word(board, out, why):
    """llama-cli echoes the prompt. A standard output that holds the prompt's word and nothing
    else shows no token: the row's "prints tokens" wants something besides it."""
    _put(board.G + "/gate2.log", "G18 PASS\n")
    board.set("tegrastats", TEGRA_BUSY)
    board.set("llama_stdout", out)
    r = board.run("G19", **GPU)
    assert r.log[-1] == ("G19 PASS" if why is None else "G19 FAIL " + why), (r.log, r.out[-1200:])
    assert board.argv("llama.argv")[-2:] == ["-p", "hello"], "the prompt is the row's"
    said = _said(_text(SCRIPT))
    assert "besides the prompt's own word" in said and "cannot be told from" in said, "and the header says how little that is"


@needs_bash
def test_a_kernel_line_that_only_holds_a_word_of_the_stop_pattern_is_a_stop_and_the_header_says_so(board):
    """The plan's pattern is taken as it stands, unanchored: DEBUG: holds BUG:. Such a line stops
    the gate until it has been read (the safe direction), and the header names the edge."""
    board.set("post-run-bell.sh", POST_LAT + 'echo "nvgpu: DEBUG: made-up driver chatter at rest" >> "$S/kjournal"\n')
    r = board.run("G5", "G6")
    assert r.log == ["G5 PASS", "G6 FAIL refused-kernel-lines"], (r.log, r.out[-800:])
    said = _said(_text(SCRIPT))
    assert "DEBUG: holds BUG:" in said and "unanchored" in said


@needs_bash
def test_a_guest_whose_launch_failed_is_not_kept_for_the_steps_that_share_its_boot(board):
    """The launcher gave up waiting for the guest and left its QEMU running. That QEMU is stopped
    with the step that failed. The next step of the group launches the image itself; it does not
    read its rule off a guest the launcher never said was up."""
    board.set("launch_times_out_once", "1\n")
    r = board.run("G1", "G2", "G3")
    assert r.log == ["G1 FAIL launch", "G2 PASS", "G3 PASS"] and r.returncode == 1, (r.log, r.out[-2000:])
    order = [c for c in r.calls if c.startswith("launcher") or c == "qemu-term"]
    assert order == ["launcher ifs-its.bin", "qemu-term", "launcher ifs-its.bin", "qemu-term"], order
    assert "the guest is kept for G2" not in r.out and "the guest is kept for G3" in r.out
    assert _launch_env(board, 1, "ifs-its.bin", dict(board.shmvars, THREAD_NAMES="1")) == _fwd(board.attempt("G2")) + "/guest-console.log"
    assert board.alive() == []
    # A launcher that gives up every time: each step of the group fails by its own launch.
    b = Board(board.root.parent / "never-up", board.tools)
    b.set("launch_times_out", "1\n")
    r = b.run("G1", "G2", "G3")
    left = b.alive()
    b.kill_all()
    assert r.log == ["G1 FAIL launch", "G2 FAIL launch", "G3 FAIL launch"], (r.log, r.out[-1500:])
    assert [c for c in r.calls if c.startswith("launcher") or c == "qemu-term"] == ["launcher ifs-its.bin", "qemu-term"] * 3 and left == []


@needs_bash
@pytest.mark.parametrize("err, tegra, told", [("load_tensors: layers on the CPU\n", TEGRA_BUSY, True), (LLAMA_ERR, TEGRA_BUSY, False),
                                              (LLAMA_ERR, TEGRA_IDLE, False), ("load_tensors: layers on the CPU\n", TEGRA_IDLE, None)],
                         ids=["busy-and-no-wording", "busy-and-the-wording", "the-wording-alone", "neither-and-so-a-fail"])
def test_g19_says_when_it_passed_without_the_offload_wording_that_g20_reads_alone(board, err, tegra, told):
    """G20's rule reads the offload wording alone, in the server's log, and that wording is
    unverified at the pin. A G19 that passed on the GPU seen busy, without the wording, says so
    and names the file to read before G20 is run. A G19 that failed says nothing of G20."""
    _put(board.G + "/gate2.log", "G18 PASS\n")
    board.set("llama_stderr", err)
    board.set("tegrastats", tegra)
    r = board.run("G19", **GPU)
    assert r.log[-1] == ("G19 FAIL gpu-evidence" if told is None else "G19 PASS"), (r.log, r.out[-1200:])
    line = [l for l in r.out.split("\n") if "before G20" in l]
    assert (len(line) == 1) == bool(told), r.out[-1200:]
    if told:
        assert board.norm(line[0]).rstrip().endswith("read %s/llama.stderr and settle the wording before G20" % _fwd(board.attempt("G19")))


# ------------------------------------------------------------------ edges no test held

@needs_bash
@pytest.mark.parametrize("value", ["yes", "0", "true", "11"])
def test_only_the_value_one_takes_a_fresh_cursor_or_a_new_boot(board, value):
    """Each of the two is somebody's word that something was read. Any other value is not it."""
    board.set("post-run-bell.sh", POST_LAT + 'echo "Oops: made up" >> "$S/kjournal"\n')
    assert board.run("G5", "G6").log == ["G5 PASS", "G6 FAIL refused-kernel-lines"]
    board.set("post-run-bell.sh", POST_LAT)
    r = board.run("G6", GATE2_FRESH_CURSOR=value)
    assert r.log[-1] == "G6 FAIL refused-kernel-lines" and "a fresh kernel journal cursor is taken" not in r.out, (r.log, r.out[-600:])
    assert board.run("G6", GATE2_FRESH_CURSOR="1").log[-1] == "G6 PASS"
    _put(board.proc / "sys" / "kernel" / "random" / "boot_id", "7c7c7c7c-1111-2222-3333-444444444444\n")
    r = board.run("G6", GATE2_NEW_BOOT=value)
    assert r.log[-1] == "G6 FAIL refused-boot-changed" and "is taken as the one on record" not in r.out, (r.log, r.out[-600:])
    assert board.run("G6", GATE2_NEW_BOOT="1").log[-1] == "G6 PASS"


@needs_bash
def test_a_harness_is_started_with_sigpipe_at_its_default(board):
    """The runner handles SIGPIPE and does not ignore it: an ignored signal is inherited by
    everything it starts, and the harnesses' `tegrastats | head -1` reads rely on the signal
    ending the writer. Here a writer into a pipe whose reader has gone ends by it (128 + 13)."""
    board.set("hook-run-bell.sh", '( yes 2> /dev/null; echo "$?" > "$S/pipe-writer" ) | head -n 1 > /dev/null\n')
    r = board.run("G5")
    assert r.log == ["G5 PASS"], (r.log, r.out[-800:])
    assert (board.get("pipe-writer") or "").strip() == "141", board.get("pipe-writer")


@needs_bash
def test_a_runner_that_is_ended_in_the_middle_of_a_step_still_stops_its_guest(board):
    """TERM to the runner while a step's harness runs against its guest: no line is written for a
    step that did not end, the next step does not start, and the guest is stopped on the way out,
    with a sync before the TERM it is sent."""
    board.set("hook-liveness-demo.sh", 'kill -TERM "$PPID"\n')
    r = board.run("G12", "G5")
    assert r.log == [] and r.returncode != 0, (r.log, r.returncode, r.out[-800:])
    assert not [c for c in r.calls if c.startswith("harness run-bell.sh")], "the next step did not start"
    deadline = time.time() + 20
    while board.alive() and time.time() < deadline:
        time.sleep(0.2)
    calls = (board.state / "calls.log").read_bytes().decode().splitlines()
    assert "qemu-term" in calls and "sync" in calls[:calls.index("qemu-term")], calls[-8:]
    assert board.alive() == []


@needs_bash
def test_a_guest_kept_for_a_step_that_is_then_refused_is_stopped_before_the_next_step_runs(board):
    """G8's guest is kept for G9, and G9 is refused by a rule of its own. The guest goes at the
    refusal: the step after it does not run beside a guest nobody is using."""
    board.drop_from_deploy_list(_GC + "run-metal.sh")
    r = board.run("G8", "G9", "G5")
    assert r.log == ["G8 PASS", "G9 FAIL refused-deploy-hash", "G5 PASS"] and r.returncode == 2, (r.log, r.out[-1500:])
    order = [c.strip() for c in r.calls if c.startswith(("harness", "launcher")) or c == "qemu-term"]
    assert order == ["launcher ifs-stamp.bin", "harness run-stamp.sh", "qemu-term", "harness run-bell.sh"], order


@needs_bash
def test_a_kept_guest_that_died_between_two_steps_is_cleared_away_before_the_image_is_launched_again(board):
    """G1's guest is kept for G2 and dies before G2 begins. What it left (its sockets, its shared
    file) is removed first: the launcher refuses to start over a socket it finds."""
    board.set("on_settle", 'if [ -s "$S/pids" ] && [ ! -e "$S/guest-killed" ]; then\n'
                           '\t: > "$S/guest-killed"; read -r q < "$S/pids"; kill -KILL "$q" 2>/dev/null\nfi\n')
    r = board.run("G1", "G2")
    assert r.log == ["G1 PASS", "G2 PASS"], (r.log, r.out[-2000:])
    assert board.get("guest-killed") is not None and "the guest is kept for G2" in r.out
    assert [c for c in r.calls if c.startswith("launcher")] == ["launcher ifs-its.bin"] * 2, "the image is launched again for G2"
    assert _launch_env(board, 1, "ifs-its.bin", dict(board.shmvars, THREAD_NAMES="1")) == _fwd(board.attempt("G2")) + "/guest-console.log"
    assert board.alive() == []


@needs_bash
def test_what_the_stop_of_a_refused_steps_guest_leaves_behind_refuses_the_steps_after_it(board):
    """G2's guest is kept for G3, and G3 is refused by a rule of its own. The guest is stopped at
    the refusal, and its ivshmem server stays: the board is looked at then, and the step after
    is not run beside a server nobody owns."""
    board.set("server_stays", "1\n")
    board.drop_from_deploy_list(_GC + "ivshmem_ring.py")
    r = board.run("G2", "G3", "G5")
    assert r.log == ["G2 PASS", "G3 FAIL refused-deploy-hash", "G5 FAIL refused-leftover-process"] and r.returncode == 2, (r.log, r.out[-1500:])
    assert not [c for c in r.calls if c.startswith("harness")] and "REFUSED from here on: leftover-process." in r.out


@needs_bash
def test_another_ivshmem_server_beside_a_kept_guest_is_a_leftover(board):
    """While a guest is kept for the next step, its own server is the one its ready file names.
    Any other ivshmem server is somebody else's."""
    board.set("hook-launcher", 'echo "   4402 python3 /made-up/ivshmem_server.py --socket /made-up/other.sock" >> "$S/procs_static"\n')
    r = board.run("G1", "G2")
    assert r.log == ["G1 PASS", "G2 FAIL refused-leftover-process"] and r.returncode == 2, (r.log, r.out[-1500:])
    assert "ivshmem_server.py" in r.out and [c for c in r.calls if c.startswith("launcher")] == ["launcher ifs-its.bin"]
    assert r.calls.count("qemu-term") == 1 and board.alive() == []


@needs_bash
@pytest.mark.parametrize("form", ["%s  %s\n", "%s *%s\n", "%s  ./%s\n", "%s *./%s\n"],
                         ids=["text", "binary-marker", "dot-slash", "binary-marker-and-dot-slash"])
@pytest.mark.parametrize("which", ["images", "deploy"])
def test_either_manifest_is_read_in_every_form_sha256sum_writes_a_line_in(board, which, form):
    """A line's path may carry sha256sum's binary marker, a leading ./, or both: the file is the
    same one, for the image list and for the files a step is held to in the deploy's."""
    man = board.home / "gate2" / (which + ".sha256")
    lines = [l.split(None, 1) for l in man.read_bytes().decode().splitlines()]
    man.write_bytes("".join(form % (h, p.strip()[2:] if p.startswith("./") else p.strip()) for h, p in lines).encode())
    first = man.read_bytes().decode().splitlines()[0]
    assert len(lines) > 10 and first == (form % (lines[0][0], lines[0][1].strip().replace("./", "", 1))).rstrip(), first
    assert board.run("G5", "G12").log == ["G5 PASS", "G12 PASS"]
