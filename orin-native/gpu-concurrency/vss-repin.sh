#!/usr/bin/env bash
# vss-repin.sh TAG -- every thread of the one running QEMU pinned to QEMU's cores and read back, in one line.
# Plan Phase 5 WP2, 2026-10-17. The one re-pin of the Orin
# mode: run-vss-setup.sh and run-vss-suite.sh run it as `vss-repin.sh boot` after each boot (VSS_REPIN), and the stack
# runs it after every container it starts, with the container's name as TAG (SDV_AFTER_START, which the suite sets to
# VSS_REPIN). It may run beside a running guest at any time; it never starts or stops anything.
#
# WHAT IT DOES, in this order:
#   1 finds the one running qemu-system-aarch64 by its process name, `pgrep -x qemu-system-aar` (the kernel keeps 15
#     characters of a name; -x matches that name only, never a command line, so neither pgrep's own nor this script's,
#     whose TAG may be anything, can match as -f would). None, or more than one: exit 3, saying which.
#   2 reads every thread's affinity BEFORE, from /proc/<pid>/task/<tid>/status (Cpus_allowed_list): how many were not on
#     QEMU's cores is what a record reads to say whether a container's start moved the pin.
#     Two lists name the same cores when they hold the same CPUs (0-2 and 0,1,2 do).
#   3 pins every thread to QEMU's cores with `sudo -n taskset -pc <cores> <tid>`, its output discarded. A thread whose
#     pin fails and whose task directory has gone ended meanwhile ("gone"); any other failed pin counts as failed.
#   4 reads every thread back, listing the task directory again, so a thread born during step 3 is read too.
#
# THE LINE, the only output (stdout), whatever happens:
#   repin tag=TAG cores=0-2 qemu=PID threads=N off_before=M pin_failed=F gone=G threads_after=A off_after=K on_cores=yes|no
#     N and M are step 2's (the threads read, those not on QEMU's cores), F and G step 3's, A and K step 4's
#   repin tag=TAG cores=0-2 qemu=none error=no-qemu            no QEMU runs
#   repin tag=TAG cores=0-2 qemu=PID,PID,... error=not-one-qemu  more than one runs: which one is the guest's is unknown
#   repin error=usage: ...                                     not one TAG of letters, digits, '.', '_' or '-'
#
# EXIT: 0 only when no pin failed, every thread read back in step 4 is on QEMU's cores, and at least one was read
# back (on_cores=yes); 1 otherwise (on_cores=no); 2 for a wrong call; 3 when not exactly one QEMU runs.
#
# DESIGN VALUE (not measured): QEMU's cores, 0-2, held in QEMU_CORES below and nowhere else; the
# containers' cores and the probe's core 4 are SDV_CONTAINER_CPUSET's rule, not this script's.
#
# It writes no file, needs no network, sources nothing, and changes nothing but the affinity of QEMU's threads, through
# sudo -n alone.
#
# WHAT IT DOES NOT SHOW: that the threads stay on QEMU's cores after it returns; that a container's start moved them
# (only whether they were on those cores when step 2 looked, which a start moments before may or may not explain); any
# timing; any isolation or guarantee: the pin is placement only.
set -euo pipefail

QEMU_CORES=0-2                  # the design value: QEMU's cores on the Orin
QEMU_COMM=qemu-system-aar       # qemu-system-aarch64's process name, as the kernel keeps it (15 characters)
PROC=/proc

TAG="${1:-}"
if [ "$#" != 1 ] || ! [[ "$TAG" =~ ^[A-Za-z0-9._-]+$ ]] || [ "${TAG:0:1}" = - ]; then
	echo "repin error=usage: vss-repin.sh TAG, one TAG of letters, digits, '.', '_' or '-' that does not begin with '-'"
	exit 2
fi

cpus_of() {   # LIST: its CPUs, ascending and comma-joined ("2,0-1" gives 0,1,2); fails for what is not a CPU list
	local IFS=, part a b c
	local -a seen=()
	[ -n "$1" ] || return 1
	for part in $1; do
		case "$part" in
			*-*) a="${part%%-*}"; b="${part#*-}" ;;
			*) a="$part"; b="$part" ;;
		esac
		[[ "$a" =~ ^[0-9]{1,4}$ && "$b" =~ ^[0-9]{1,4}$ ]] || return 1
		[ "$((10#$a))" -le "$((10#$b))" ] || return 1
		for ((c = 10#$a; c <= 10#$b; c++)); do seen[c]=1; done
	done
	echo "${!seen[*]}"
}
WANT="$(cpus_of "$QEMU_CORES")"

on_cores() {   # LIST: whether that affinity list names exactly QEMU's cores
	local got
	got="$(cpus_of "$1")" || return 1
	[ "$got" = "$WANT" ]
}

pids="$(pgrep -x "$QEMU_COMM" || true)"
# shellcheck disable=SC2086  # pgrep's pids, one per line, as the words of one line
read -r -a found <<< "$(echo $pids)"
if [ "${#found[@]}" = 0 ]; then
	echo "repin tag=$TAG cores=$QEMU_CORES qemu=none error=no-qemu"
	exit 3
fi
if [ "${#found[@]}" != 1 ]; then
	echo "repin tag=$TAG cores=$QEMU_CORES qemu=$(IFS=,; echo "${found[*]}") error=not-one-qemu"
	exit 3
fi
PID="${found[0]}"

tids() {   # the thread ids of QEMU now, from its task directory (none once QEMU has gone)
	local d
	for d in "$PROC/$PID/task"/[0-9]*; do
		if [ -d "$d" ]; then echo "${d##*/}"; fi
	done
}
affinity() {   # TID: that thread's Cpus_allowed_list; fails when its status cannot be read (the thread has ended)
	local out
	out="$(sed -n 's/^Cpus_allowed_list:[[:space:]]*//p' "$PROC/$PID/task/$1/status" 2>/dev/null)" || return 1
	echo "$out"
}

# 2: before
threads=0; off_before=0; listed=()
for tid in $(tids); do
	aff="$(affinity "$tid")" || continue
	threads=$((threads + 1)); listed+=("$tid")
	on_cores "$aff" || off_before=$((off_before + 1))
done

# 3: the pins
failed=0; gone=0
for tid in ${listed[@]+"${listed[@]}"}; do
	if sudo -n taskset -pc "$QEMU_CORES" "$tid" >/dev/null 2>&1; then continue; fi
	if [ -d "$PROC/$PID/task/$tid" ]; then failed=$((failed + 1)); else gone=$((gone + 1)); fi
done

# 4: the read-back, over the threads there now
after=0; off_after=0
for tid in $(tids); do
	aff="$(affinity "$tid")" || continue
	after=$((after + 1))
	on_cores "$aff" || off_after=$((off_after + 1))
done

ok=no
if [ "$failed" = 0 ] && [ "$off_after" = 0 ] && [ "$after" -gt 0 ]; then ok=yes; fi
echo "repin tag=$TAG cores=$QEMU_CORES qemu=$PID threads=$threads off_before=$off_before pin_failed=$failed gone=$gone" \
	"threads_after=$after off_after=$off_after on_cores=$ok"
if [ "$ok" = yes ]; then exit 0; fi
exit 1
