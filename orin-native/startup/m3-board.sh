#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# m3-board.sh — the M3 board procedure, driven from the PC in Git Bash.
#
# Phase 3b. Encodes results/orin-native-port/20260909T1100Z/m3-design.md,
# revision 2: §6.2 staging, §6.3 P0, §6.4 P1 and §6.5 each run, so that the
# Linux-side procedure is the same for every rung and every run (§2 rule 2).
# It decides nothing the design leaves to the owner: O4 (quiesce) and O5
# (governor pin) must be stated on every run, and it prints no verdict against
# §8, only the fields the run note needs (§4.6).
#
# RUNS ON the PC. It reaches the board over ssh and scp only. It never opens
# COM3: a capture started from Git Bash receives nothing (m2-runs.md:135-137),
# so the capture is started from PowerShell before `run` and named here.
#
# USAGE
#   m3-board.sh stage IMG            §6.2  copy IMG.kimg, resumable, sha256-gated
#   m3-board.sh p0 IMG               §6.3  pre-flight reads, kexec -s -l / -u acceptance
#   m3-board.sh p1                   §6.4  quiesce rehearsal (O4), then reboot L4T
#   m3-board.sh reboot               reboot L4T, wait for a new boot_id (§6.5 step 2)
#   m3-board.sh run IMG              §6.5  steps 2-9: one kexec round, records fetched
#   m3-board.sh extract FILE         the §4.6 fields from a black box, offline
#   m3-board.sh consistency BB COM3  STAMP and IPC lines of both records, compared
#
# ENVIRONMENT (no host, user, key or path is written into this file)
#   ORIN_HOST          board commands: user@address of the board (required)
#   ORIN_KEY           ssh private key file, passed as -i (optional)
#   SSH_OPTS           extra ssh and scp flags, word-split (optional)
#   M3_KIMG_DIR        where IMG.kimg is on the PC (default ../shim/out/m3 from
#                      this script; the C1 image m1b-p4 is in ../shim/out/m1b)
#   M3_KIMG_SHA256     the generator's sha256 for IMG; checked when set
#   M3_REMOTE_DIR      kimg directory on the board, relative to its home unless
#                      absolute (default: the home directory itself)
#   M3_RECORD_DIR      p0, p1, run: results/orin-native-port/<utc>/m3 (required)
#   M3_COM3_LOG        run: the running PowerShell capture's file (required)
#   M3_QUIESCE         run: 1 = O4 adopted, 0 = not (required, no default)
#   M3_GOVERNOR_PIN    run: 1 = O5 adopted, 0 = not (required, no default)
#   M3_KEXEC           s = kexec_file_load (default); c = K1, kexec -c -l IMG -i
#   M3_MAX_UPTIME_S    run refuses at or above this L4T uptime (default 7200)
#   M3_RETURN_BOUND_S  give-up bound after kexec or reboot (default 1200)
#   M3_STUCK_S         run: stop with exit 3 once the old boot_id has answered
#                      every poll for this long after systemctl kexec, i.e.
#                      Linux never went down (default 600, 0 = off). Not in the
#                      design. Relocation runs after user space is gone, so a
#                      slow relocation cannot keep the old boot_id answering;
#                      only a stalled systemd shutdown with sshd still up can
#   M3_POLL_S          seconds between boot_id polls (default 10)
#
# RECORDS. Every file written ends in .log, which .gitignore ignores, and is
# re-checked with git check-ignore when it lies inside a work tree: these are
# evaluation output under NC QDL v7 4.6(i), private and unpublished. Records
# keep only basenames of PC paths and pass a redaction filter first (IPv4, MAC,
# user@, home directories, the key), as the plan's results hygiene asks (§12).
# A raw black box or COM3 copy is redacted only if it holds such a string, and
# its raw sha256 is recorded before that.
#
# EXIT: 0 done; 1 refused or failed before anything changed on the board;
# 2 the board did not come back within the bound; 3 stopped with L4T running
# (quiesce failed, kexec not issued, or Linux never went down).

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROG="$(basename "$0")"

usage() { sed -n '3,/^set -uo/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//' >&2; exit 2; }
die()   { echo "$PROG: FAIL: $*" >&2; [ -n "${REC:-}" ] && printf '%s\n' "FAIL: $*" | redact >> "$REC"; exit 1; }
note()  { echo "$PROG: $*" >&2; }
utc_now() { date -u +%Y%m%dT%H%M%SZ; }
iso_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ---------------------------------------------------------------- ssh

ssh_base=(-o BatchMode=yes -o ConnectTimeout=10)
[ -n "${ORIN_KEY:-}" ] && ssh_base+=(-i "$ORIN_KEY")
# shellcheck disable=SC2206  # deliberate word-splitting, as scripts/twin/sync-qhv.sh
ssh_base+=(${SSH_OPTS:-})
ssh_work=("${ssh_base[@]}" -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
# The poll options of §6.5 step 6: a connect timeout does not bound an
# established session, and a poll that connects while Linux shuts down would
# otherwise hang (m2-runs.md, "An SSH poll hung during R2").
ssh_poll=("${ssh_base[@]}" -o ServerAliveInterval=3 -o ServerAliveCountMax=2)

need_host() { [ -n "${ORIN_HOST:-}" ] || die "ORIN_HOST is not set (user@address of the board)"; }

RDIR="${M3_REMOTE_DIR:-}"
[[ -z "$RDIR" || "$RDIR" =~ ^[A-Za-z0-9._/-]+$ ]] || die "M3_REMOTE_DIR has characters outside [A-Za-z0-9._/-]"

# ---------------------------------------------------------------- redaction

R_USER=""; R_HOST=""; R_KEYBASE=""
case "${ORIN_HOST:-}" in
*@*) R_USER="${ORIN_HOST%%@*}"; R_HOST="${ORIN_HOST#*@}" ;;
*)   R_HOST="${ORIN_HOST:-}" ;;
esac
# A bare short host name is not replaced as a literal: it could be a common
# word in board output. Addresses and dotted names are.
case "$R_HOST" in *.*|*:*) ;; *) R_HOST="" ;; esac
R_KEY="${ORIN_KEY:-}"
[ -n "$R_KEY" ] && R_KEYBASE="$(basename "$R_KEY")"
[ "${#R_KEYBASE}" -ge 6 ] || R_KEYBASE=""
R_PCUSER="${USERNAME:-${USER:-}}"
IDENT_RE='([0-9]{1,3}[.]){3}[0-9]{1,3}|[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}'

redact() {
	awk -v u="$R_USER" -v h="$R_HOST" -v k="$R_KEY" -v kb="$R_KEYBASE" -v pu="$R_PCUSER" '
	function lit(s, a, r,    i, out) {
		if (a == "") return s
		out = ""
		while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)) }
		return out s
	}
	{
		line = $0
		line = lit(line, k, "<orin-key>")
		line = lit(line, kb, "<orin-key>")
		if (u != "") { line = lit(line, u "@", "<user>@"); line = lit(line, "/home/" u, "/home/<user>") }
		if (pu != "") { line = lit(line, "Users/" pu, "Users/<user>"); line = lit(line, "Users\\" pu, "Users\\<user>"); line = lit(line, "/home/" pu, "/home/<user>") }
		line = lit(line, h, "<orin-ip>")
		gsub(/[0-9][0-9]?[0-9]?[.][0-9][0-9]?[0-9]?[.][0-9][0-9]?[0-9]?[.][0-9][0-9]?[0-9]?/, "<ip>", line)
		gsub(/[0-9A-Fa-f][0-9A-Fa-f](:[0-9A-Fa-f][0-9A-Fa-f]){5}/, "<mac>", line)
		print line
	}'
}

# Lines in FILE that the redaction filter would change.
ident_hits() {
	local f="$1" pats=()
	[ -n "$R_USER" ] && pats+=(-e "$R_USER@" -e "/home/$R_USER")
	[ -n "$R_PCUSER" ] && pats+=(-e "Users/$R_PCUSER" -e "Users\\$R_PCUSER" -e "/home/$R_PCUSER")
	[ -n "$R_HOST" ] && pats+=(-e "$R_HOST")
	[ -n "$R_KEY" ] && pats+=(-e "$R_KEY")
	[ -n "$R_KEYBASE" ] && pats+=(-e "$R_KEYBASE")
	{
		grep -aE "$IDENT_RE" "$f"
		[ "${#pats[@]}" -gt 0 ] && grep -aF "${pats[@]}" "$f"
	} | wc -l
}

# ---------------------------------------------------------------- records

REC=""
RECDIR=""

need_record_dir() {
	local d="${M3_RECORD_DIR:-}"
	[ -n "$d" ] || die "M3_RECORD_DIR is not set (results/orin-native-port/<utc>/m3, private)"
	case "$d" in
	*results/cloud*|*results/hw*) die "M3_RECORD_DIR must not be under results/cloud or results/hw (m3-design.md §4.4)" ;;
	esac
	mkdir -p "$d" || die "cannot create M3_RECORD_DIR"
	RECDIR="$(cd "$d" && pwd)"
}

rec_open() {
	REC="$1"
	: > "$REC" || { REC=""; die "cannot write $(basename "$1")"; }
	rec "# $(basename "$REC"): evaluation output, NC QDL v7 4.6(i), unpublished"
	rec "# written by orin-native/startup/$PROG at $(iso_now)"
}

rec_pipe() { if [ -n "$REC" ]; then redact | tee -a "$REC"; else redact; fi; }
rec()      { printf '%s\n' "$*" | rec_pipe; }

# key=value from a block of board output
kv() { printf '%s\n' "$2" | awk -v k="$1" 'index($0, k "=") == 1 { print substr($0, length(k) + 2); exit }'; }

# Warn about any written file inside a work tree that git would not ignore.
check_private() {
	local f d
	for f in "$@"; do
		[ -e "$f" ] || continue
		d="$(dirname "$f")"
		git -C "$d" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
		if ! git -C "$d" check-ignore -q "$(basename "$f")"; then
			note "WARNING: $(basename "$f") is NOT git-ignored: private evaluation output, keep it out of any commit"
		fi
	done
}

# Redact a raw PC copy in place only if it holds an identifying string.
privacy_scan() {
	local f="$1" n
	n="$(ident_hits "$f")"
	if [ "${n:-0}" -gt 0 ]; then
		redact < "$f" > "$f.redact" && mv "$f.redact" "$f"
		rec "privacy $(basename "$f"): $n identifying line(s) redacted in the PC copy (raw sha256 recorded above)"
	else
		rec "privacy $(basename "$f"): nothing identifying found, copy kept raw"
	fi
}

# ---------------------------------------------------------------- board side
#
# The b_* functions run on the board. They are shipped verbatim with declare -f
# and read by the board's bash from stdin; the only values passed in are the
# preamble's printf %q assignments. Output is key=value or prefixed lines.

b_sha() {
	echo "board_sha256=$(sha256sum "$K" 2>/dev/null | cut -d' ' -f1)"
	echo "board_bytes=$(stat -c %s "$K" 2>/dev/null || echo 0)"
}

b_identity() {
	echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
	echo "uptime_s=$(cut -d' ' -f1 /proc/uptime)"
}

b_df() {
	echo "df_avail_kb=$(df -Pk "$KD" | awk 'NR == 2 { print $4 }')"
}

# name, size and mtime of every pstore record, so new dmesg-ramoops ones show
b_pstore() {
	sudo -n ls -l --time-style=+%s /sys/fs/pstore 2>&1 | awk 'NR > 1 && NF >= 7 { print "pstore " $7 " " $5 " " $6 }'
}

# §4.3 step 2 for each policy; $1 labels the reading
b_freq() {
	local p d f
	for p in policy0 policy4; do
		d=/sys/devices/system/cpu/cpufreq/$p
		for f in affected_cpus scaling_governor scaling_cur_freq scaling_min_freq scaling_max_freq; do
			echo "freq $1 $p $f=$(cat "$d/$f" 2>&1)"
		done
		echo "freq $1 $p cpuinfo_cur_freq=$(sudo -n cat "$d/cpuinfo_cur_freq" 2>&1)"
	done
}

# §4.3 step 3 and §6.3 step 1, read-only
b_session() {
	local p z o
	for p in policy0 policy4; do
		echo "freq session $p scaling_available_frequencies=$(cat /sys/devices/system/cpu/cpufreq/$p/scaling_available_frequencies 2>&1)"
	done
	for z in /sys/class/thermal/thermal_zone*; do
		echo "thermal ${z##*/} $(cat "$z/type" 2>&1) $(cat "$z/temp" 2>&1)"
	done
	o="$(nvpmodel -q 2>&1)" || o="$(sudo -n nvpmodel -q 2>&1)"
	printf '%s\n' "$o" | sed 's/^/nvpmodel /'
}

# §6.5 step 3.1 (O5), the design's command
b_governor() {
	local p
	for p in policy0 policy4; do
		echo performance | sudo -n tee /sys/devices/system/cpu/cpufreq/$p/scaling_governor >/dev/null
		echo "governor $p performance rc=$?"
	done
	sleep 2
}

# All of /proc/iomem saved on the board, its 80000000-ffffffff lines printed
# (§6.3 step 2, §6.4 step 4). $1 labels the read.
b_iomem() {
	local f="$HOME/iomem-$1-$UTC.txt"
	sudo -n cat /proc/iomem > "$f"
	echo "iomem_$1_rc=$?"
	grep -E '^[[:space:]]*[89a-f][0-9a-f]{7}-[0-9a-f]{8} :' "$f" | sed "s/^/iomemline $1 /"
}

# The timestamp of dmesg's last line, and the lines after a timestamp. Line
# counts are not used: a full ring buffer keeps its count while it scrolls.
b_dmesg_mark() {
	sudo -n dmesg | tail -n 1 | sed -n 's/^\[ *\([0-9]*\.[0-9]*\)\].*/\1/p'
}
b_dmesg_since() {
	sudo -n dmesg | awk -v t0="${1:-0}" 'match($0, /^\[ *[0-9]+\.[0-9]+\]/) { t = substr($0, RSTART + 1, RLENGTH - 2) + 0; if (t > t0 + 0) print }'
}

# §6.4 steps 1-3: P1, and every run under O4. The design's own dmesg grep is
# recorded as dmesg-tail100; the counts use only lines newer than the start.
b_quiesce() {
	local t0 m new
	echo "quiesce_get_default=$(systemctl get-default 2>&1)"
	t0=$(b_dmesg_mark)
	sudo -n systemctl isolate multi-user.target
	echo "quiesce_isolate_rc=$?"
	for m in nvidia_drm nvidia_modeset nvidia nvgpu; do
		sudo -n timeout 30 rmmod $m
		echo "rmmod $m rc=$?"
	done
	lsmod | grep -E '^(nvidia_drm|nvidia_modeset|nvidia|nvgpu) ' | sed 's/^/still-loaded /'
	sudo -n dmesg | tail -n 100 | grep -iE 'smmu|tegra-mc|emem|nvgpu|nvidia|oops|bug' | sed 's/^/dmesg-tail100 /'
	new=$(mktemp)
	b_dmesg_since "$t0" > "$new"
	echo "quiesce_dmesg_new_lines=$(wc -l < "$new")"
	echo "quiesce_oops_lines=$(grep -cE 'Oops|BUG:|Kernel panic|Unable to handle kernel|Internal error' "$new")"
	echo "quiesce_smmu_emem_lines=$(grep -ciE 'smmu|tegra-mc|emem' "$new")"
	grep -E 'Oops|BUG:|[Pp]anic|[Ss][Mm][Mm][Uu]|tegra-mc|[Ee][Mm][Ee][Mm]|nvgpu|nvidia' "$new" | head -n 60 | sed 's/^/dmesg-new /'
	rm -f "$new"
}

# §6.3 step 4, the design's sequence; the pass is 0, then 1, then 0
b_accept() {
	sudo -n kexec -s -l "$K"
	echo "accept_load_rc=$?"
	echo "accept_kexec_loaded=$(cat /sys/kernel/kexec_loaded)"
	sudo -n kexec -u
	echo "accept_unload_rc=$?"
	echo "accept_kexec_loaded_after=$(cat /sys/kernel/kexec_loaded)"
}

b_dyndbg() {
	if sudo -n test -e /sys/kernel/debug/dynamic_debug/control; then echo "dyndbg=yes"; else echo "dyndbg=no"; fi
}

# §6.3 step 5, only when dyndbg=yes
b_placement() {
	local t0
	t0=$(b_dmesg_mark)
	echo 'file kexec_image.c +p' | sudo -n tee /sys/kernel/debug/dynamic_debug/control >/dev/null
	echo "placement_dyndbg_on_rc=$?"
	b_accept | sed 's/^accept_/placement_accept_/'
	b_dmesg_since "$t0" | grep 'Loaded kernel at' | sed 's/^/placement_line /'
	echo 'file kexec_image.c -p' | sudo -n tee /sys/kernel/debug/dynamic_debug/control >/dev/null
	echo "placement_dyndbg_off_rc=$?"
}

# §6.5 step 5. Stops before systemctl kexec unless the load succeeded and
# kexec_loaded reads 1. The last frequency read is taken just before (§4.3).
b_kexec_go() {
	local rc kl
	if [ "$KEXEC_MODE" = c ]; then
		sudo -n kexec -c -l "$K" -i; rc=$?
	else
		sudo -n kexec -s -l "$K"; rc=$?
	fi
	echo "kexec_load_rc=$rc"
	[ "$rc" = 0 ] || exit 10
	kl=$(cat /sys/kernel/kexec_loaded)
	echo "kexec_loaded=$kl"
	if [ "$kl" != 1 ]; then
		sudo -n kexec -u
		echo "kexec_unload_rc=$?"
		exit 11
	fi
	# R0 (2026-09-10T21:11Z): the quiesce step's isolate put both policies back
	# to schedutil after the step-3 pin. Pin again here, after quiesce, and do
	# not kexec unless both read 'performance'.
	if [ "${GOV_PIN:-0}" = 1 ]; then
		b_governor
		local p g
		for p in policy0 policy4; do
			g=$(cat /sys/devices/system/cpu/cpufreq/$p/scaling_governor)
			echo "governor_final_$p=$g"
			if [ "$g" != performance ]; then
				sudo -n kexec -u
				echo "kexec_unload_rc=$?"
				echo "governor_final_fail=$p"
				exit 12
			fi
		done
	fi
	b_freq final
	echo "uptime_at_kexec_s=$(cut -d' ' -f1 /proc/uptime)"
	echo "kexec_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo "systemctl_kexec=issuing"
	sudo -n systemctl kexec
	echo "systemctl_kexec_rc=$?"
}

b_unload() {
	sudo -n kexec -u
	echo "kexec_unload_rc=$?"
	echo "kexec_loaded=$(cat /sys/kernel/kexec_loaded)"
}

# §6.5 step 7
b_after() {
	local bb="$HOME/$IMG-$UTC-blackbox.log"
	b_identity
	sudo -n cat /sys/fs/pstore/console-ramoops-0 > "$bb"
	echo "blackbox_read_rc=$?"
	echo "blackbox_bytes=$(stat -c %s "$bb")"
	echo "blackbox_sha256=$(sha256sum "$bb" | cut -d' ' -f1)"
	echo "blackbox_shim_lines=$(grep -ac 'T234-SHIM' "$bb")"
	echo "reset_reason=$(cat /sys/devices/platform/bus@0/c360000.pmc/reset_reason 2>&1 | tr '\n' ' ' | sed 's/ *$//')"
	b_pstore
}

b_reboot() {
	echo "reboot=issuing"
	sudo -n reboot
	echo "reboot_rc=$?"
}

BOARD_FUNCS="b_sha b_identity b_df b_pstore b_freq b_session b_governor b_iomem b_dmesg_mark b_dmesg_since b_quiesce b_accept b_dyndbg b_placement b_kexec_go b_unload b_after b_reboot"

# Run board functions: $1 = timeout in seconds, then the lines to run.
board() {
	local secs="$1"
	shift
	{
		printf 'IMG=%q\nRDIR=%q\nUTC=%q\nKEXEC_MODE=%q\nGOV_PIN=%q\n' "${IMG:-}" "$RDIR" "${UTC:-}" "${KEXEC_MODE:-s}" "${M3_GOVERNOR_PIN:-0}"
		printf '%s\n' 'case "$RDIR" in "") KD="$HOME" ;; /*) KD="$RDIR" ;; *) KD="$HOME/$RDIR" ;; esac' 'K="$KD/$IMG.kimg"'
		# shellcheck disable=SC2086  # a list of function names
		declare -f $BOARD_FUNCS
		printf '%s\n' "$@"
	} | timeout "$secs" ssh "${ssh_work[@]}" "$ORIN_HOST" 'bash -s' | tr -d '\r'
}

read_boot_id() {
	timeout 25 ssh "${ssh_poll[@]}" "$ORIN_HOST" 'cat /proc/sys/kernel/random/boot_id' </dev/null 2>/dev/null | tr -dc '0-9a-f-'
}

# $1 old boot_id, $2 start in epoch seconds, $3 stuck bound in seconds (0 off).
# Sets NEW_BOOT_ID, BACK_S and WAITED_S. Returns 0 when back; 3 when the stuck
# bound is on and the old boot_id answered every poll, either for the stuck
# bound or up to the give-up bound; 1 when the give-up bound passed after the
# board went quiet at least once.
wait_new_boot_id() {
	local old="$1" t0="$2" stuck="${3:-0}" bound="${M3_RETURN_BOUND_S:-1200}" poll="${M3_POLL_S:-10}"
	local now bid last=0 down=0
	NEW_BOOT_ID=""
	BACK_S=""
	WAITED_S=0
	while :; do
		now=$(date +%s)
		WAITED_S=$(( now - t0 ))
		if (( now - t0 >= bound )); then
			# A board that answered with the old boot_id throughout is still up:
			# telling the operator to power-cycle it would be wrong.
			if (( stuck > 0 && down == 0 )); then return 3; fi
			return 1
		fi
		bid="$(read_boot_id)"
		if [[ "$bid" =~ ^[0-9a-f-]{36}$ ]]; then
			if [ "$bid" != "$old" ]; then
				NEW_BOOT_ID="$bid"
				BACK_S=$(( $(date +%s) - t0 ))
				return 0
			fi
		else
			down=1
		fi
		if (( stuck > 0 && down == 0 && now - t0 >= stuck )); then return 3; fi
		if (( now - last >= 60 )); then
			note "waiting for a new boot_id: $(( now - t0 )) s of $bound s"
			last=$now
		fi
		sleep "$poll"
	done
}

resolve_kimg() {
	[[ "${1:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "image name '${1:-}' is not [A-Za-z0-9._-]+"
	case "$1" in *.kimg) die "give the image name without .kimg" ;; esac
	KIMG="${M3_KIMG_DIR:-$HERE/../shim/out/m3}/$1.kimg"
	[ -f "$KIMG" ] || die "no $1.kimg under M3_KIMG_DIR"
	KIMG_SHA="$(sha256sum "$KIMG" | cut -d' ' -f1)"
	if [ -n "${M3_KIMG_SHA256:-}" ] && [ "$KIMG_SHA" != "$M3_KIMG_SHA256" ]; then
		die "$1.kimg sha256 $KIMG_SHA is not M3_KIMG_SHA256"
	fi
}

# ---------------------------------------------------------------- stage (§6.2)

# The copy_one pattern of scripts/twin/sync-qhv.sh:108-175: remote size, then
# the prefix sha256, then append or resend, over scp -C. Sets SENT.
copy_kimg() {
	local dest local_size remote_size prefix_sha remote_sha attempt
	dest="${RDIR:+$RDIR/}$IMG.kimg"
	local_size=$(stat -c %s "$KIMG")
	SENT=0
	for attempt in 1 2 3; do
		remote_size="$(timeout 60 ssh "${ssh_work[@]}" "$ORIN_HOST" "stat -c %s $dest 2>/dev/null || echo 0" </dev/null 2>/dev/null | tr -dc '0-9')"
		: "${remote_size:=0}"
		if (( remote_size > 0 && remote_size < local_size )); then
			prefix_sha="$(head -c "$remote_size" "$KIMG" | sha256sum | cut -d' ' -f1)"
			remote_sha="$(timeout 300 ssh "${ssh_work[@]}" "$ORIN_HOST" "sha256sum $dest | cut -d' ' -f1" </dev/null 2>/dev/null | tr -dc '0-9a-f')"
			if [ "$prefix_sha" = "$remote_sha" ]; then
				rec "stage attempt=$attempt resuming at byte $remote_size of $local_size"
				if dd if="$KIMG" bs=1M iflag=skip_bytes skip="$remote_size" status=none \
					| timeout 3600 ssh "${ssh_work[@]}" -o Compression=yes "$ORIN_HOST" "cat >> $dest"; then
					SENT=$(( SENT + local_size - remote_size ))
					return 0
				fi
				rec "stage attempt=$attempt resume failed; waiting 20 s"
				sleep 20
				continue
			fi
			rec "stage the partial copy is not a prefix of the kimg; resending in full"
		fi
		rec "stage attempt=$attempt sending $local_size bytes"
		if timeout 3600 scp "${ssh_work[@]}" -C "$KIMG" "$ORIN_HOST:$dest" </dev/null; then
			SENT=$(( SENT + local_size ))
			return 0
		fi
		rec "stage attempt=$attempt failed; waiting 20 s"
		sleep 20
	done
	return 1
}

cmd_stage() {
	local out avail have t0 t1
	need_host
	IMG="$1"
	resolve_kimg "$IMG"
	UTC="$(utc_now)"
	if [ -n "${M3_RECORD_DIR:-}" ]; then
		need_record_dir
		rec_open "$RECDIR/stage-$IMG-$UTC.log"
	fi
	rec "stage image=$IMG kimg_bytes=$(stat -c %s "$KIMG") pc_sha256=$KIMG_SHA"
	out="$(board 300 'mkdir -p "$KD"' b_df b_sha)" || die "board unreachable or its read failed (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	have="$(kv board_sha256 "$out")"
	if [ "$have" != "$KIMG_SHA" ]; then
		avail="$(kv df_avail_kb "$out")"
		[ "${avail:-0}" -ge 614400 ] 2>/dev/null || die "the board has ${avail:-?} KB free, under the 600 MB of §6.2 step 1"
		t0=$(date +%s)
		copy_kimg || die "transfer failed after 3 attempts; re-running stage resumes a partial copy"
		t1=$(date +%s)
		rec "stage transfer secs=$(( t1 - t0 )) bytes_sent=$SENT mb_per_s=$(awk -v b="$SENT" -v s="$(( t1 - t0 ))" 'BEGIN { if (s < 1) s = 1; printf "%.2f", b / 1e6 / s }')"
		have="$(kv board_sha256 "$(board 300 b_sha)")"
	else
		rec "stage already on the board with the PC's sha256; nothing sent"
	fi
	rec "stage board_sha256=$have"
	[ "$have" = "$KIMG_SHA" ] || die "the board's copy differs from the PC's kimg; re-run stage"
	rec "stage PASS: the board's $IMG.kimg equals the PC's (§6.2 step 3)"
	[ -n "$REC" ] && check_private "$REC"
	return 0
}

# ---------------------------------------------------------------- P0 (§6.3)

cmd_p0() {
	local out have dy line re='Loaded kernel at 0x0*80080000([^0-9a-fA-F]|$)'
	need_host
	need_record_dir
	IMG="$1"
	resolve_kimg "$IMG"
	UTC="$(utc_now)"
	rec_open "$RECDIR/p0-$IMG-$UTC-board.log"
	rec "p0 utc=$(iso_now) image=$IMG pc_sha256=$KIMG_SHA (no reboot, nothing persistent)"
	out="$(board 300 b_sha b_identity)" || die "board unreachable (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	have="$(kv board_sha256 "$out")"
	[ "$have" = "$KIMG_SHA" ] || die "the board has no $IMG.kimg with the PC's sha256; run stage first"

	rec "p0 step 1: frequency grid, nvpmodel, thermal zones"
	board 120 'b_freq p0' b_session | rec_pipe
	rec "p0 step 2: lsmod, and the 80000000-ffffffff lines of /proc/iomem"
	out="$(board 120 'lsmod | sed "s/^/lsmod /"' 'b_iomem p0')"
	printf '%s\n' "$out" | rec_pipe
	printf '%s\n' "$out" | sed -n 's/^iomemline p0 //p' | redact > "$RECDIR/p0-iomem-$UTC.log"
	rec "p0 iomem lines saved as p0-iomem-$UTC.log (compare with raw/orin-iomem.txt:180-186)"

	rec "p0 steps 3-4: dynamic debug; kexec -s -l, kexec_loaded, kexec -u, kexec_loaded"
	out="$(board 300 b_dyndbg b_accept)"
	printf '%s\n' "$out" | rec_pipe
	if [ "$(kv accept_load_rc "$out")" = 0 ] && [ "$(kv accept_kexec_loaded "$out")" = 1 ] \
		&& [ "$(kv accept_kexec_loaded_after "$out")" = 0 ]; then
		rec "p0 GATE step 4 PASS: rc=0, then 1, then 0"
	else
		rec "p0 GATE step 4 FAIL: rc=$(kv accept_load_rc "$out") loaded=$(kv accept_kexec_loaded "$out") after=$(kv accept_kexec_loaded_after "$out"): §7 kexec rows, K1"
	fi
	dy="$(kv dyndbg "$out")"
	if [ "$dy" = yes ]; then
		rec "p0 step 5: placement through dynamic debug"
		out="$(board 300 b_placement)"
		printf '%s\n' "$out" | rec_pipe
		line="$(printf '%s\n' "$out" | grep '^placement_line ' | tail -n 1)"
		if [ -z "$line" ]; then
			rec "p0 placement: no 'Loaded kernel at' line appeared (NVIDIA's fork is unread): UNKNOWN, R0 answers it"
		elif [[ "$line" =~ $re ]]; then
			rec "p0 placement: 0x80080000, as expected"
		else
			rec "p0 placement: NOT 0x80080000, which predicts BAD-LANDING: take K1 before R0 (§6.3 step 5)"
		fi
	else
		rec "p0 step 5 skipped: dyndbg=${dy:-unknown}"
	fi
	board 60 'echo "kexec_loaded_at_end=$(cat /sys/kernel/kexec_loaded)"' | rec_pipe
	check_private "$REC" "$RECDIR/p0-iomem-$UTC.log"
}

# ---------------------------------------------------------------- P1 (§6.4)

cmd_p1() {
	local out old t0 p0f rcs oops smmu rc
	need_host
	need_record_dir
	IMG=""
	UTC="$(utc_now)"
	rec_open "$RECDIR/p1-$UTC-board.log"
	rec "p1 utc=$(iso_now): quiesce rehearsal, no kexec"
	out="$(board 60 b_identity)" || die "board unreachable (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	old="$(kv boot_id "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"

	rec "p1 steps 1-3: get-default, isolate multi-user.target, rmmod of four modules (timeout 30 each), dmesg"
	rec "p1 step 4: /proc/iomem after rmmod, and the swiotlb and cma lines of dmesg"
	out="$(board 500 b_quiesce 'b_iomem postrmmod' 'sudo -n dmesg | grep -iE "software IO TLB|swiotlb|cma" | sed "s/^/dmesg-dma /"')"
	printf '%s\n' "$out" | grep -v '^iomemline ' | rec_pipe
	printf '%s\n' "$out" | sed -n 's/^iomemline postrmmod //p' | redact > "$RECDIR/p1-iomem-postrmmod-$UTC.log"
	p0f="$(ls -1t "$RECDIR"/p0-iomem-*.log 2>/dev/null | head -n 1)"
	if [ -n "$p0f" ]; then
		if diff "$p0f" "$RECDIR/p1-iomem-postrmmod-$UTC.log" > "$RECDIR/p1-iomem-diff-$UTC.log"; then
			rec "p1 iomem 80000000-ffffffff lines identical to $(basename "$p0f") (checklist 11c)"
		else
			rec "p1 iomem 80000000-ffffffff lines differ from $(basename "$p0f") (checklist 11c):"
			rec_pipe < "$RECDIR/p1-iomem-diff-$UTC.log"
		fi
	else
		rec "p1 no p0-iomem-*.log in M3_RECORD_DIR: the post-rmmod read is saved, not diffed"
	fi
	rcs="$(printf '%s\n' "$out" | grep -c '^rmmod [a-z_]* rc=0$')"
	oops="$(kv quiesce_oops_lines "$out")"
	smmu="$(kv quiesce_smmu_emem_lines "$out")"
	if [ "$rcs" = 4 ] && [ "$oops" = 0 ] && [ "$smmu" = 0 ]; then
		rec "p1 GATE: rmmod_ok=4/4 oops_lines=0 smmu_emem_lines=0: the quiesce steps can join every run"
	else
		rec "p1 GATE NOT MET: rmmod_ok=$rcs/4 oops_lines=${oops:-?} smmu_emem_lines=${smmu:-?}: record it; O4 falls back or the owner decides"
	fi

	rec "p1 step 5: sudo -n reboot, then wait for a new boot_id"
	t0=$(date +%s)
	board 30 b_reboot | rec_pipe
	wait_new_boot_id "$old" "$t0" 0
	rc=$?
	if [ "$rc" != 0 ]; then
		rec "p1 NO RETURN within ${M3_RETURN_BOUND_S:-1200} s: a Linux shutdown Oops ends in a watchdog reset after about 3 min (m1b-runs.md:54-58); read COM3, then power-cycle"
		check_private "$REC" "$RECDIR"/p1-*-"$UTC".log
		exit 2
	fi
	rec "p1 back_after_s=$BACK_S new_boot_id=$NEW_BOOT_ID"
	board 60 b_identity b_pstore | rec_pipe
	check_private "$REC" "$RECDIR"/p1-*-"$UTC".log
}

# ---------------------------------------------------------------- reboot

cmd_reboot() {
	local out old t0 rc
	need_host
	IMG=""
	UTC="$(utc_now)"
	if [ -n "${M3_RECORD_DIR:-}" ]; then
		need_record_dir
		rec_open "$RECDIR/reboot-$UTC-board.log"
	fi
	out="$(board 60 b_identity)" || die "board unreachable (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	old="$(kv boot_id "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	t0=$(date +%s)
	board 30 b_reboot | rec_pipe
	wait_new_boot_id "$old" "$t0" 0
	rc=$?
	if [ "$rc" != 0 ]; then
		rec "reboot NO RETURN within ${M3_RETURN_BOUND_S:-1200} s: read COM3, then power-cycle"
		exit 2
	fi
	rec "reboot back_after_s=$BACK_S new_boot_id=$NEW_BOOT_ID"
	board 60 b_identity b_pstore | rec_pipe
	[ -n "$REC" ] && check_private "$REC"
	return 0
}

# ---------------------------------------------------------------- run (§6.5)

cmd_run() {
	local base out old up rc wrc pstore_before pstore_after newrec shim reason lsha rcs oops gok gov0 gov4 stuck
	need_host
	need_record_dir
	IMG="$1"
	resolve_kimg "$IMG"
	case "${M3_QUIESCE:-}" in 0|1) ;; *) die "M3_QUIESCE must be 1 (O4 adopted) or 0 (not adopted), stated on every run" ;; esac
	case "${M3_GOVERNOR_PIN:-}" in 0|1) ;; *) die "M3_GOVERNOR_PIN must be 1 (O5 adopted) or 0 (not adopted), stated on every run" ;; esac
	stuck="${M3_STUCK_S:-600}"
	[[ "$stuck" =~ ^[0-9]+$ ]] || die "M3_STUCK_S must be a whole number of seconds (0 turns the early stop off)"
	KEXEC_MODE="${M3_KEXEC:-s}"
	case "$KEXEC_MODE" in s|c) ;; *) die "M3_KEXEC must be s, or c for contingency K1" ;; esac
	if [ -z "${M3_COM3_LOG:-}" ] || [ ! -f "$M3_COM3_LOG" ]; then
		die "M3_COM3_LOG must name the running PowerShell COM3 capture's file: COM3 is a mandatory co-record (§4.5, §6.5 step 1)"
	fi
	UTC="$(utc_now)"
	base="$RECDIR/$IMG-$UTC"
	rec_open "$base-board.log"
	if [ "$KEXEC_MODE" = s ]; then
		rec "run image=$IMG utc=$UTC kexec_syscall=kexec_file_load (-s)"
	else
		rec "run image=$IMG utc=$UTC kexec_syscall=kexec_load (-c -l ... -i, contingency K1: purgatory checks skipped)"
	fi
	rec "run kimg=$IMG.kimg bytes=$(stat -c %s "$KIMG") pc_sha256=$KIMG_SHA"
	rec "run com3_log=$(basename "$M3_COM3_LOG") quiesce_O4=$M3_QUIESCE governor_pin_O5=$M3_GOVERNOR_PIN"

	# step 2: the kimg, identity, the uptime rule, pstore before
	out="$(board 300 b_sha b_identity b_pstore)" || die "board unreachable (rc=$?); nothing was changed on the board"
	printf '%s\n' "$out" | rec_pipe
	[ "$(kv board_sha256 "$out")" = "$KIMG_SHA" ] || die "the board's $IMG.kimg differs from the PC's: run stage"
	old="$(kv boot_id "$out")"
	up="$(kv uptime_s "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	pstore_before="$(printf '%s\n' "$out" | grep '^pstore ')"
	if awk -v u="$up" -v m="${M3_MAX_UPTIME_S:-7200}" 'BEGIN { exit !(u + 0 >= m + 0) }'; then
		die "L4T has been up ${up%.*} s, at or above ${M3_MAX_UPTIME_S:-7200} s: reboot it first ($PROG reboot), §6.5 step 2"
	fi

	# step 3 (O5), gated like steps 4 and 5. A pin that did not reach both
	# policies, or a §4.3 read that did not reach the record, stops the run
	# before quiesce and kexec: every run keeps the same Linux-side procedure
	# (§2 rule 2), and the header's governor_pin_O5 states the request only.
	if [ "$M3_GOVERNOR_PIN" = 1 ]; then
		out="$(board 60 b_governor)"
		rc=$?
		printf '%s\n' "$out" | rec_pipe
		gok="$(printf '%s\n' "$out" | grep -cE '^governor policy[04] performance rc=0$')"
		if [ "$rc" != 0 ] || [ "$gok" != 2 ]; then
			rec "run GOVERNOR PIN FAILED (session rc=$rc, governor_ok=$gok/2): no quiesce and no kexec, so the runs stay identical (§2 rule 2). L4T is still running; a policy may be left at performance, so reboot L4T before a run with M3_GOVERNOR_PIN=0"
			check_private "$REC"
			exit 3
		fi
	fi
	out="$(board 120 'b_freq pre' b_session)"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	gov0="$(kv 'freq pre policy0 scaling_governor' "$out")"
	gov4="$(kv 'freq pre policy4 scaling_governor' "$out")"
	if [ "$rc" != 0 ] || ! [[ "$gov0" =~ ^[a-z_]+$ && "$gov4" =~ ^[a-z_]+$ ]]; then
		rec "run FREQUENCY READ FAILED (session rc=$rc, policy0 scaling_governor='$gov0', policy4 scaling_governor='$gov4'): the §4.3 fields of step 3 are not in the record; no quiesce and no kexec (§2 rule 2). L4T is still running"
		check_private "$REC"
		exit 3
	fi
	if [ "$M3_GOVERNOR_PIN" = 1 ] && { [ "$gov0" != performance ] || [ "$gov4" != performance ]; }; then
		rec "run GOVERNOR NOT PINNED (policy0=$gov0 policy4=$gov4 after the pin): no quiesce and no kexec (§2 rule 2). L4T is still running"
		check_private "$REC"
		exit 3
	fi
	rec "run step 3 governor read back: policy0=$gov0 policy4=$gov4 (O5=$M3_GOVERNOR_PIN)"

	# step 4 (O4)
	if [ "$M3_QUIESCE" = 1 ]; then
		out="$(board 500 b_quiesce 'b_iomem run')"
		printf '%s\n' "$out" | grep -v '^iomemline ' | rec_pipe
		printf '%s\n' "$out" | sed -n 's/^iomemline run //p' | redact > "$base-iomem-postrmmod.log"
		rcs="$(printf '%s\n' "$out" | grep -c '^rmmod [a-z_]* rc=0$')"
		oops="$(kv quiesce_oops_lines "$out")"
		if [ "$rcs" != 4 ] || [ "${oops:-x}" != 0 ]; then
			rec "run QUIESCE FAILED (rmmod_ok=$rcs/4 oops_lines=${oops:-?}): no kexec, so the runs stay identical (§7 quiesce row). The board is part-quiesced: reboot L4T before another attempt"
			check_private "$REC" "$base-iomem-postrmmod.log"
			exit 3
		fi
	fi

	# step 5
	rec "run step 5: kexec load, kexec_loaded, last frequency read, systemctl kexec"
	out="$(board 300 b_kexec_go)"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	if [ -n "$(kv governor_final_fail "$out")" ]; then
		rec "run GOVERNOR REVERTED before kexec ($(kv governor_final_fail "$out") not performance after the re-pin): the image was unloaded, no kexec. L4T is still running"
		check_private "$REC"
		exit 3
	fi
	if [ "$(kv kexec_loaded "$out")" != 1 ]; then
		rec "run kexec NOT issued (rc=$rc): L4T is still running"
		check_private "$REC"
		exit 3
	fi
	if [ -n "$(kv systemctl_kexec_rc "$out")" ] && [ "$(kv systemctl_kexec_rc "$out")" != 0 ]; then
		board 60 b_unload | rec_pipe
		rec "run systemctl kexec FAILED: the image was unloaded and L4T is still running"
		check_private "$REC"
		exit 3
	fi
	rec "run kexec issued; the session ended with rc=$rc (255 is expected when Linux drops it)"

	# step 6
	wait_new_boot_id "$old" "$(date +%s)" "$stuck"
	wrc=$?
	case "$wrc" in
	0)
		rec "run back_after_s=$BACK_S (counted from the end of the kexec session) new_boot_id=$NEW_BOOT_ID"
		;;
	3)
		rec "run the old boot_id answered every poll for $WAITED_S s after the kexec session (M3_STUCK_S=$stuck): Linux never went down. The image may still be loaded: keep the COM3 capture running, and check /sys/kernel/kexec_loaded by hand (sudo -n kexec -u unloads it)"
		check_private "$REC"
		exit 3
		;;
	*)
		rec "run NO RETURN within ${M3_RETURN_BOUND_S:-1200} s (§6.5 step 9): read COM3 first (with nothing resetting, the TCU drains fully), then power-cycle, and record that the black box was lost"
		check_private "$REC"
		exit 2
		;;
	esac

	# step 7
	out="$(board 120 b_after)" || rec "run warning: the return read ended with rc=$?"
	printf '%s\n' "$out" | rec_pipe
	pstore_after="$(printf '%s\n' "$out" | grep '^pstore ')"
	newrec="$(comm -13 <(printf '%s\n' "$pstore_before" | sort) <(printf '%s\n' "$pstore_after" | sort) | grep '^pstore dmesg-ramoops' || true)"
	if [ -n "$newrec" ]; then
		rec "run NEW dmesg-ramoops records:"
		printf '%s\n' "$newrec" | rec_pipe
	else
		rec "run new_dmesg_ramoops=none"
	fi
	shim="$(kv blackbox_shim_lines "$out")"
	reason="$(kv reset_reason "$out")"
	rec "run reset_reason=$reason (MAINSWRST: the image's own reset; BCCPLEXWDT: the watchdog)"
	if [ "${shim:-0}" = 0 ]; then
		if [ -n "$newrec" ]; then
			rec "run VALIDITY: no T234-SHIM and a new dmesg-ramoops record: Linux died before the jump. Retry from a fresh L4T; do not judge the image (§6.5 validity rule)"
		else
			rec "run VALIDITY: no T234-SHIM in the black box: this run never reached the shim (§6.5 validity rule)"
		fi
	fi

	# step 8: records to the PC
	if timeout 300 scp "${ssh_work[@]}" "$ORIN_HOST:$IMG-$UTC-blackbox.log" "$base-blackbox.log" </dev/null; then
		lsha="$(sha256sum "$base-blackbox.log" | cut -d' ' -f1)"
		if [ "$lsha" = "$(kv blackbox_sha256 "$out")" ]; then
			rec "run black box copied: $(basename "$base")-blackbox.log bytes=$(stat -c %s "$base-blackbox.log") sha256=$lsha, equal to the board's"
		else
			rec "run black box copy sha256 $lsha DIFFERS from the board's"
		fi
		privacy_scan "$base-blackbox.log"
	else
		rec "run black box copy FAILED: it stays on the board as $IMG-$UTC-blackbox.log"
	fi
	if cp "$M3_COM3_LOG" "$base-com3.log" 2>/dev/null; then
		rec "run COM3 copied: $(basename "$base")-com3.log bytes=$(stat -c %s "$base-com3.log") raw_sha256=$(sha256sum "$base-com3.log" | cut -d' ' -f1). L4T is back: stop the capture now"
		privacy_scan "$base-com3.log"
	else
		rec "run COM3 copy FAILED (the capture may hold the file): stop the capture, then copy it as $(basename "$base")-com3.log"
	fi
	if [ -f "$base-blackbox.log" ]; then
		extract_file "$base-blackbox.log" | rec_pipe
		if [ -f "$base-com3.log" ]; then
			consistency_files "$base-blackbox.log" "$base-com3.log" | rec_pipe
		fi
	fi
	rec "run done. Record: $(basename "$REC"). The verdict against §8 belongs to the run note (§6.5 step 10)"
	check_private "$REC" "$base-blackbox.log" "$base-com3.log" "$base-iomem-postrmmod.log"
	return 0
}

# ---------------------------------------------------------------- extraction

# The tokens of m3-design.md §8 item 12 and m1b-design.md §8 item 10, as fixed
# strings. "M3 FAIL" is matched on its own below, so that the required line
# "M3 FAIL_STATE none" (§8 item 11) does not count as a hit.
NEG_TOKENS=(
	't234: EL1' 't234: EL2' 'hvtimer STOP' 'el2-host requested but' 'continuing despite' 'probe off'
	'ASSERT' 'start failure' 'start timeout' 'released but' 'entered at EL1' 'wake timeout' 'not awake'
	'transfer hook ran' 'PE is not awake' 'does not match cpu 0' 'tick=dead' 'tick=bad' 'CENSUS FAIL' 'RESULT FAIL'
	'BWAIT guard deadline' 'STAMP exec-failed' 'STAMP read-error' 'Unable to start' '[g2.conf:' 'Could not load library'
	'unrecoverable stall' 'sentinel-recovery exhausted' 'echo seq mismatch' 'killed=1'
	'No system file system' 'Unable to access /dev/hd0' 'BAD-LANDING' 'Shutdown['
)

# The §4.6 fields of one black box, mechanically, with no verdict.
extract_file() {
	local f="$1" t tok n bytes
	t="$(mktemp)"
	tr -d '\r' < "$f" > "$t"
	bytes=$(stat -c %s "$f")
	echo "extract file=$(basename "$f") bytes=$bytes sha256=$(sha256sum "$f" | cut -d' ' -f1)"
	if [ "$bytes" -ge 65500 ]; then
		echo "extract size: the 65,520 B cap was hit, head only; the tail is on COM3 (§7)"
	elif [ "$bytes" -ge 60000 ]; then
		echo "extract size: at or above 60,000 B, the G1/G2 threshold (§4.5)"
	else
		echo "extract size: under 60,000 B (§4.5 G1/G2)"
	fi
	echo "extract lines:"
	grep -aE '^(T234-SHIM|T234 M3 |Enabling EL2 host|t234: (all [0-9]+ cpus parked|cpu [0-9]+ el2-host|hvtimer cpu)|SMPCHECK (census|CENSUS|done)|BWAIT (guard|run |path hit=/dev/qvmdisk0)|M3 (CONFIG|CHECK|FAIL|MEM|QVM|STATE (end|diag))|rc=|samples=|P50=|sentinel_|QNX qnx-guest)' "$t" | sed 's/^/  /'
	echo "extract guest_banner_lines=$(grep -acE 'QNX qnx-guest 8[.]0[.]0 .*ARMv8_Foundation_Model aarch64le' "$t") (the §8 item 5 pattern)"

	awk '
	$1 == "STAMP" && !($2 in seen) {
		seen[$2] = 1; order[++n] = $2; line[$2] = $0
		for (i = 3; i <= NF; i++) {
			eq = index($i, "=")
			if (eq == 0) continue
			key = substr($i, 1, eq - 1); val = substr($i, eq + 1)
			if (key == "cycles") cyc[$2] = val
			else if (key == "cps") cps[$2] = val
		}
	}
	function ms(d) { return d * 1000 / c }
	END {
		print "extract stamps (the first line of each label):"
		bad = 0
		for (i = 1; i <= n; i++) { l = order[i]; print "  " line[l]; if ((l in cps) && cps[l] != "31250000") bad++ }
		print "extract stamps_with_cps_other_than_31250000=" bad
		if (!("qvm_launch" in cyc)) { print "extract headline: no qvm_launch stamp"; exit }
		c = ("qvm_launch" in cps) ? cps["qvm_launch"] + 0 : 31250000
		if (c <= 0) c = 31250000
		a = cyc["qvm_launch"]
		if ("banner" in cyc) printf "extract headline banner-qvm_launch cycles=%.0f ms=%.3f\n", cyc["banner"] - a, ms(cyc["banner"] - a)
		else print "extract headline: no banner stamp"
		for (i = 1; i <= n; i++) { l = order[i]; if (l in cyc) printf "extract offset %s-qvm_launch ms=%.3f\n", l, ms(cyc[l] - a) }
		k = split("qvm_launch g_first g_devb g_net g_ifup g_sshd g_misc g_startup_complete banner", ch, " ")
		prev = ""; mono = "yes"
		for (i = 1; i <= k; i++) {
			l = ch[i]
			if (!(l in cyc)) { print "extract chain " l " absent"; continue }
			if (prev != "") {
				d = cyc[l] - cyc[prev]
				printf "extract segment %s-%s cycles=%.0f ms=%.3f\n", l, prev, d, ms(d)
				if (d < 0) mono = "no"
			}
			prev = l
		}
		print "extract chain_non_decreasing=" mono " (over the labels present; §8 item 6)"
		if (("ipc_start" in cyc) && ("ipc_end" in cyc)) printf "extract segment ipc_end-ipc_start ms=%.3f\n", ms(cyc["ipc_end"] - cyc["ipc_start"])
		if ("g_srv" in cyc) {
			if ("g_misc" in cyc) printf "extract offset-signed g_srv-g_misc ms=%.3f\n", ms(cyc["g_srv"] - cyc["g_misc"])
			if ("g_startup_complete" in cyc) printf "extract offset-signed g_srv-g_startup_complete ms=%.3f\n", ms(cyc["g_srv"] - cyc["g_startup_complete"])
			if ("ipc_start" in cyc) printf "extract offset-signed ipc_start-g_srv ms=%.3f\n", ms(cyc["ipc_start"] - cyc["g_srv"])
		} else print "extract g_srv absent"
	}' "$t"

	awk '
	function val(key,    i, eq) {
		for (i = 1; i <= NF; i++) { eq = index($i, "="); if (eq && substr($i, 1, eq - 1) == key) return substr($i, eq + 1) }
		return ""
	}
	/^samples=/ && !s { s = 1; ns = val("samples") }
	/^sentinel_recoveries=/ && !r { r = 1; nr = val("sentinel_recoveries") }
	/^BWAIT run prog=qnx-host-client / && !b { b = 1; brc = val("rc"); bk = val("killed"); bms = val("ms") }
	END {
		if (!s && !b) { print "extract ipc: no client output (boot mode, or the IPC never ran)"; exit }
		printf "extract ipc samples=%s sentinel_recoveries=%s sum=%s bwait_rc=%s killed=%s ms=%s (completion: rc=0, killed=0, sum=15; §4.4)\n", (s ? ns : "?"), (r ? nr : "?"), ((s && r) ? ns + nr : "?"), (b ? brc : "?"), (b ? bk : "?"), (b ? bms : "?")
	}' "$t"

	awk '
	/^M3 MEM / {
		v = $4; sub(/MB.*/, "", v)
		printf "extract mem %s free_mb=%s", $3, v
		if ($3 == "disk") printf " G-MEM=%s", (v + 0 >= 600 ? "proceed" : (v + 0 >= 560 ? "proceed-with-note" : "O7-before-R1"))
		printf "\n"
	}' "$t"

	awk '
	/^SMPCHECK done cpu=/ {
		c = ""; r = ""
		for (i = 1; i <= NF; i++) {
			eq = index($i, "=")
			if (!eq) continue
			k = substr($i, 1, eq - 1)
			if (k == "cpu") c = substr($i, eq + 1); else if (k == "rate") r = substr($i, eq + 1)
		}
		if (c != "" && r != "") { m = ++cnt[c]; rate[c, m] = r }
	}
	END {
		for (c in cnt) {
			if (cnt[c] < 2) { printf "extract rate cpu=%s single=%s\n", c, rate[c, 1]; continue }
			p = rate[c, 1]; q = rate[c, cnt[c]]
			d = (p > 0) ? (q - p) * 100 / p : 0
			printf "extract rate cpu=%s pre=%s post=%s drift_pct=%.2f%s\n", c, p, q, d, ((d > 2 || d < -2) ? " FLAG-over-2pct" : "")
		}
	}' "$t" | sort

	echo "extract negative tokens (m3-design.md §8 item 12 and m1b-design.md §8 item 10; R0 expects its client to fail):"
	n=$(grep -acE 'M3 FAIL([^_]|$)' "$t")
	[ "$n" = 0 ] || echo "  'M3 FAIL' x$n"
	for tok in "${NEG_TOKENS[@]}"; do
		n=$(grep -acF -- "$tok" "$t")
		[ "$n" = 0 ] || echo "  '$tok' x$n"
	done
	echo "extract negative tokens end"
	rm -f "$t"
}

# STAMP and IPC lines of the black box and COM3, CR-stripped, in order (§4.5,
# §8 item 11). The black box keeps only its head, so a COM3 record that holds
# more after an identical prefix is reported as such, not as a difference.
consistency_files() {
	local re='(STAMP |samples=|P50=|sentinel_recoveries=|BWAIT run prog=qnx-host-client ).*' a b na
	a="$(mktemp)"
	b="$(mktemp)"
	tr -d '\r' < "$1" | grep -aoE "$re" > "$a"
	tr -d '\r' < "$2" | grep -aoE "$re" > "$b"
	na=$(wc -l < "$a")
	echo "consistency blackbox_lines=$na com3_lines=$(wc -l < "$b") (STAMP and IPC lines, CR-stripped, in order)"
	if cmp -s "$a" "$b"; then
		echo "consistency identical"
	elif head -n "$na" "$b" | cmp -s "$a" -; then
		echo "consistency identical over the black box's lines; COM3 holds more (a capped black box?)"
	else
		echo "consistency DIFFER (first 40 diff lines):"
		diff "$a" "$b" | head -n 40 | sed 's/^/  /'
	fi
	rm -f "$a" "$b"
}

# ---------------------------------------------------------------- main

case "${1:-}" in
stage)       [ $# -eq 2 ] || usage; cmd_stage "$2" ;;
p0)          [ $# -eq 2 ] || usage; cmd_p0 "$2" ;;
p1)          [ $# -eq 1 ] || usage; cmd_p1 ;;
reboot)      [ $# -eq 1 ] || usage; cmd_reboot ;;
run)         [ $# -eq 2 ] || usage; cmd_run "$2" ;;
extract)     { [ $# -eq 2 ] && [ -f "$2" ]; } || usage; extract_file "$2" ;;
consistency) { [ $# -eq 3 ] && [ -f "$2" ] && [ -f "$3" ]; } || usage; consistency_files "$2" "$3" ;;
*)           usage ;;
esac
