#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# m4-board.sh — the M4 board procedure, driven from the PC in Git Bash.
#
# Phase 3b. Encodes results/orin-native-port/20260909T1100Z/m4-design.md,
# revision 2, §7: M3's harness (m3-board.sh, not edited) with the changes of
# §7.2 and the implementation notes of that file's §14. The Linux-side procedure
# is M3's for every rung and every run. It decides nothing the design leaves to
# the owner: O4 (quiesce) and O5 (governor pin) must be stated on every run.
# The verdict is the parser's (orin-native/m4/parse-m4.py run, step 8b).
#
# RUNS ON the PC. It reaches the board over ssh and scp only. It never opens
# COM3: a capture started from Git Bash receives nothing (m2-runs.md:135-137),
# so orin-native/m4/capture-com3-raw.ps1 is started from PowerShell before
# `run` and named here.
#
# Every M4 board run needs the owner at the plug (§10): a native image that
# hangs after kexec does not recover by itself.
#
# USAGE
#   m4-board.sh stage IMG              copy IMG.kimg, resumable, sha256-gated
#   m4-board.sh p0 IMG                 pre-flight reads, kexec -s -l / -u acceptance
#   m4-board.sh p1                     quiesce rehearsal (O4), then reboot L4T
#   m4-board.sh reboot                 reboot L4T, wait for a new boot_id
#   m4-board.sh run IMG                one kexec round, records fetched, parser run
#   m4-board.sh extract FILE           the record fields from a black box, offline
#   m4-board.sh consistency BB COM3    record lines of both records, compared
#   m4-board.sh size-r1 R0LOG          parse-m4.py size-r1 --r0-parse R0LOG
#   m4-board.sh size-r2 R1LOG R0LOG    parse-m4.py size-r2 --r1-parse R1LOG --r0-parse R0LOG
#   m4-board.sh series L1 L2 L3 L4 L5  parse-m4.py series over five T-run parse logs
#
# ENVIRONMENT (no host, user, key or path is written into this file)
#   ORIN_HOST                board commands: user@address of the board (required)
#   ORIN_KEY                 ssh private key file, passed as -i (optional)
#   SSH_OPTS                 extra ssh and scp flags, word-split (optional)
#   M4_KIMG_DIR              where IMG.kimg and IMG.params are on the PC
#                            (default ../shim/out/m4 from this script)
#   M4_KIMG_SHA256           the generator's sha256 for IMG; checked when set
#   M4_REMOTE_DIR            kimg directory on the board, relative to its home
#                            unless absolute (default: the home directory)
#   M4_RECORD_DIR            p0, p1, run, size-*, series:
#                            results/orin-native-port/<utc>/m4 (required)
#   M4_COM3_LOG              run: the running raw capture's file (required); its
#                            header must carry epoch= and seconds=
#   M4_RUN_ID                run: r0, r1, q, t1, t2, t3, t4 or t5 (required)
#   M4_QUIESCE               run: 1 = O4 adopted, 0 = not (required, no default)
#   M4_GOVERNOR_PIN          run: 1 = O5 adopted, 0 = not (required, no default)
#   M4_KEXEC                 s = kexec_file_load (default); c = K1, kexec -c -l IMG -i
#   M4_MAX_UPTIME_S          run refuses at or above this L4T uptime (default 7200)
#   M4_QUIESCE_MAX_UPTIME_S  with M4_QUIESCE=1, run refuses at or above this
#                            uptime (default 1800; §7.2 item 4)
#   M4_RETURN_BOUND_S        give-up bound after kexec; default and minimum are
#                            IMG.params' return_bound_s (§7.2 item 2)
#   M4_STUCK_S               run: stop with exit 3 once the old boot_id has
#                            answered every poll this long (default 600, 0 = off)
#   M4_POLL_S                seconds between boot_id polls (default 10)
#
# RECORDS. Every file written ends in .log, or lies under $M4_RECORD_DIR/out/
# (both git-ignored), and is re-checked with git check-ignore: evaluation output
# under NC QDL v7 4.6(i), private and unpublished. The parser reads the raw
# copies first; only then does the redaction filter run over them (§7.2 item 6).
#
# EXIT: 0 done; 1 refused or failed before anything changed on the board;
# 2 the board did not come back within the bound; 3 stopped with L4T running
# (a gate, quiesce failed, kexec not issued, or Linux never went down), or a
# sizing rule that goes to the owner.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROG="$(basename "$0")"
PARSER="$HERE/../m4/parse-m4.py"

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
ssh_poll=("${ssh_base[@]}" -o ServerAliveInterval=3 -o ServerAliveCountMax=2)

need_host() { [ -n "${ORIN_HOST:-}" ] || die "ORIN_HOST is not set (user@address of the board)"; }

RDIR="${M4_REMOTE_DIR:-}"
[[ -z "$RDIR" || "$RDIR" =~ ^[A-Za-z0-9._/-]+$ ]] || die "M4_REMOTE_DIR has characters outside [A-Za-z0-9._/-]"

# ---------------------------------------------------------------- redaction

R_USER=""; R_HOST=""; R_KEYBASE=""
case "${ORIN_HOST:-}" in
*@*) R_USER="${ORIN_HOST%%@*}"; R_HOST="${ORIN_HOST#*@}" ;;
*)   R_HOST="${ORIN_HOST:-}" ;;
esac
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
	local d="${M4_RECORD_DIR:-}"
	[ -n "$d" ] || die "M4_RECORD_DIR is not set (results/orin-native-port/<utc>/m4, private)"
	case "$d" in
	*results/cloud*|*results/hw*) die "M4_RECORD_DIR must not be under results/cloud or results/hw (m4-design.md §6.4, §7.2 item 1)" ;;
	esac
	mkdir -p "$d" "$d/out" || die "cannot create M4_RECORD_DIR"
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

kv() { printf '%s\n' "$2" | awk -v k="$1" 'index($0, k "=") == 1 { print substr($0, length(k) + 2); exit }'; }

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

find_python() {
	local t
	PY_BIN=""
	for t in python3 python py; do
		if command -v "$t" >/dev/null 2>&1 && "$t" -c pass >/dev/null 2>&1; then
			PY_BIN="$t"
			return 0
		fi
	done
	return 1
}

# ---------------------------------------------------------------- board side (m3-board.sh:200-389, unchanged)

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

b_pstore() {
	sudo -n ls -l --time-style=+%s /sys/fs/pstore 2>&1 | awk 'NR > 1 && NF >= 7 { print "pstore " $7 " " $5 " " $6 }'
}

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

b_governor() {
	local p
	for p in policy0 policy4; do
		echo performance | sudo -n tee /sys/devices/system/cpu/cpufreq/$p/scaling_governor >/dev/null
		echo "governor $p performance rc=$?"
	done
	sleep 2
}

b_iomem() {
	local f="$HOME/iomem-$1-$UTC.txt"
	sudo -n cat /proc/iomem > "$f"
	echo "iomem_$1_rc=$?"
	grep -E '^[[:space:]]*[89a-f][0-9a-f]{7}-[0-9a-f]{8} :' "$f" | sed "s/^/iomemline $1 /"
}

b_dmesg_mark() {
	sudo -n dmesg | tail -n 1 | sed -n 's/^\[ *\([0-9]*\.[0-9]*\)\].*/\1/p'
}
b_dmesg_since() {
	sudo -n dmesg | awk -v t0="${1:-0}" 'match($0, /^\[ *[0-9]+\.[0-9]+\]/) { t = substr($0, RSTART + 1, RLENGTH - 2) + 0; if (t > t0 + 0) print }'
}

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

board() {
	local secs="$1"
	shift
	{
		printf 'IMG=%q\nRDIR=%q\nUTC=%q\nKEXEC_MODE=%q\nGOV_PIN=%q\n' "${IMG:-}" "$RDIR" "${UTC:-}" "${KEXEC_MODE:-s}" "${M4_GOVERNOR_PIN:-0}"
		printf '%s\n' 'case "$RDIR" in "") KD="$HOME" ;; /*) KD="$RDIR" ;; *) KD="$HOME/$RDIR" ;; esac' 'K="$KD/$IMG.kimg"'
		# shellcheck disable=SC2086  # a list of function names
		declare -f $BOARD_FUNCS
		printf '%s\n' "$@"
	} | timeout "$secs" ssh "${ssh_work[@]}" "$ORIN_HOST" 'bash -s' | tr -d '\r'
}

read_boot_id() {
	timeout 25 ssh "${ssh_poll[@]}" "$ORIN_HOST" 'cat /proc/sys/kernel/random/boot_id' </dev/null 2>/dev/null | tr -dc '0-9a-f-'
}

RETURN_BOUND=1200
EXTENDED=0

# 0 when the COM3 file grew during the last 60 s of the samples taken (§7.2 item 5).
com3_grew_60() {
	local now="$1" i n=${#COM3_T[@]} base_s="" cur
	[ "$n" -gt 0 ] || return 1
	cur="${COM3_S[$((n - 1))]}"
	for (( i = n - 1; i >= 0; i-- )); do
		if (( COM3_T[i] <= now - 60 )); then base_s="${COM3_S[$i]}"; break; fi
	done
	[ -n "$base_s" ] || base_s="${COM3_S[0]}"
	(( cur > base_s ))
}

# $1 old boot_id, $2 start in epoch seconds, $3 stuck bound in seconds (0 off),
# $4 1 to allow the one COM3-growth extension. Sets NEW_BOOT_ID, BACK_S, WAITED_S
# and EXTENDED. Returns 0 back; 3 Linux never went down; 1 the bound passed.
wait_new_boot_id() {
	local old="$1" t0="$2" stuck="${3:-0}" extend="${4:-0}" bound="$RETURN_BOUND" poll="${M4_POLL_S:-10}"
	local now bid last=0 down=0 sz
	NEW_BOOT_ID=""
	BACK_S=""
	WAITED_S=0
	EXTENDED=0
	COM3_T=()
	COM3_S=()
	while :; do
		now=$(date +%s)
		WAITED_S=$(( now - t0 ))
		if [ "$extend" = 1 ] && [ -n "${M4_COM3_LOG:-}" ]; then
			sz=$(stat -c %s "$M4_COM3_LOG" 2>/dev/null || echo 0)
			COM3_T+=("$now")
			COM3_S+=("$sz")
		fi
		if (( now - t0 >= bound )); then
			if [ "$extend" = 1 ] && [ "$EXTENDED" = 0 ] && com3_grew_60 "$now" \
				&& ! grep -aq -e '--- raw capture ended' "$M4_COM3_LOG" 2>/dev/null; then
				bound=$(( bound + 600 ))
				EXTENDED=1
				rec "run return bound reached while COM3 is still growing and the capture has not ended: extended once by 600 s to $bound s (§7.2 item 5; a slow transfer is not a hang)"
				continue
			fi
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

# Sets KIMG, KIMG_SHA, PARAMS and RETURN_BOUND (§7.2 item 2).
resolve_kimg() {
	local want rb
	[[ "${1:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "image name '${1:-}' is not [A-Za-z0-9._-]+"
	case "$1" in *.kimg) die "give the image name without .kimg" ;; esac
	KIMG="${M4_KIMG_DIR:-$HERE/../shim/out/m4}/$1.kimg"
	PARAMS="${M4_KIMG_DIR:-$HERE/../shim/out/m4}/$1.params"
	[ -f "$KIMG" ] || die "no $1.kimg under M4_KIMG_DIR"
	[ -f "$PARAMS" ] || die "no $1.params beside $1.kimg: build the image with make-m4-images.sh"
	KIMG_SHA="$(sha256sum "$KIMG" | cut -d' ' -f1)"
	if [ -n "${M4_KIMG_SHA256:-}" ] && [ "$KIMG_SHA" != "$M4_KIMG_SHA256" ]; then
		die "$1.kimg sha256 $KIMG_SHA is not M4_KIMG_SHA256"
	fi
	want="$(awk -F= '$1 == "kimg_sha256" { print $2; exit }' "$PARAMS" | tr -d '\r')"
	[ "$want" = "$KIMG_SHA" ] || die "$1.params says kimg_sha256=$want, but $1.kimg is $KIMG_SHA: rebuild, or the params belong to another build"
	rb="$(awk -F= '$1 == "return_bound_s" { print $2; exit }' "$PARAMS" | tr -d '\r')"
	[[ "$rb" =~ ^[0-9]+$ ]] || die "$1.params has no whole-number return_bound_s"
	CAPTURE_S="$(awk -F= '$1 == "capture_s" { print $2; exit }' "$PARAMS" | tr -d '\r')"
	RETURN_BOUND="$rb"
	if [ -n "${M4_RETURN_BOUND_S:-}" ]; then
		[[ "$M4_RETURN_BOUND_S" =~ ^[0-9]+$ ]] || die "M4_RETURN_BOUND_S must be a whole number of seconds"
		(( M4_RETURN_BOUND_S >= rb )) || die "M4_RETURN_BOUND_S=$M4_RETURN_BOUND_S is lower than $1.params' return_bound_s=$rb (§7.2 item 2)"
		RETURN_BOUND="$M4_RETURN_BOUND_S"
	fi
}

# §7.2 item 3: the capture's remaining life from its header and the PC's clock.
capture_left_s() {
	local head epoch secs
	head="$(head -n 1 "$M4_COM3_LOG" 2>/dev/null | tr -d '\r')"
	case "$head" in "--- raw capture started"*) ;; *) echo "noheader"; return ;; esac
	epoch="$(printf '%s\n' "$head" | sed -n 's/.* epoch=\([0-9][0-9]*\) .*/\1/p')"
	secs="$(printf '%s\n' "$head" | sed -n 's/.* seconds=\([0-9][0-9]*\) .*/\1/p')"
	if [ -z "$epoch" ] || [ -z "$secs" ]; then echo "noepoch"; return; fi
	echo $(( epoch + secs - $(date +%s) ))
}

# ---------------------------------------------------------------- stage

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
	if [ -n "${M4_RECORD_DIR:-}" ]; then
		need_record_dir
		rec_open "$RECDIR/stage-$IMG-$UTC.log"
	fi
	rec "stage image=$IMG kimg_bytes=$(stat -c %s "$KIMG") pc_sha256=$KIMG_SHA"
	out="$(board 300 'mkdir -p "$KD"' b_df b_sha)" || die "board unreachable or its read failed (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	have="$(kv board_sha256 "$out")"
	if [ "$have" != "$KIMG_SHA" ]; then
		avail="$(kv df_avail_kb "$out")"
		[ "${avail:-0}" -ge 614400 ] 2>/dev/null || die "the board has ${avail:-?} KB free, under 600 MB"
		t0=$(date +%s)
		copy_kimg || die "transfer failed after 3 attempts; re-running stage resumes a partial copy"
		t1=$(date +%s)
		rec "stage transfer secs=$(( t1 - t0 )) bytes_sent=$SENT"
		have="$(kv board_sha256 "$(board 300 b_sha)")"
	else
		rec "stage already on the board with the PC's sha256; nothing sent"
	fi
	rec "stage board_sha256=$have"
	[ "$have" = "$KIMG_SHA" ] || die "the board's copy differs from the PC's kimg; re-run stage"
	rec "stage PASS: the board's $IMG.kimg equals the PC's"
	[ -n "$REC" ] && check_private "$REC"
	return 0
}

# ---------------------------------------------------------------- P0

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
	rec "p0 steps 3-4: dynamic debug; kexec -s -l, kexec_loaded, kexec -u, kexec_loaded"
	out="$(board 300 b_dyndbg b_accept)"
	printf '%s\n' "$out" | rec_pipe
	if [ "$(kv accept_load_rc "$out")" = 0 ] && [ "$(kv accept_kexec_loaded "$out")" = 1 ] \
		&& [ "$(kv accept_kexec_loaded_after "$out")" = 0 ]; then
		rec "p0 GATE step 4 PASS: rc=0, then 1, then 0"
	else
		rec "p0 GATE step 4 FAIL: rc=$(kv accept_load_rc "$out") loaded=$(kv accept_kexec_loaded "$out") after=$(kv accept_kexec_loaded_after "$out")"
	fi
	dy="$(kv dyndbg "$out")"
	if [ "$dy" = yes ]; then
		rec "p0 step 5: placement through dynamic debug"
		out="$(board 300 b_placement)"
		printf '%s\n' "$out" | rec_pipe
		line="$(printf '%s\n' "$out" | grep '^placement_line ' | tail -n 1)"
		if [ -z "$line" ]; then
			rec "p0 placement: no 'Loaded kernel at' line appeared: UNKNOWN"
		elif [[ "$line" =~ $re ]]; then
			rec "p0 placement: 0x80080000, as expected"
		else
			rec "p0 placement: NOT 0x80080000, which predicts BAD-LANDING: take K1 first"
		fi
	else
		rec "p0 step 5 skipped: dyndbg=${dy:-unknown}"
	fi
	board 60 'echo "kexec_loaded_at_end=$(cat /sys/kernel/kexec_loaded)"' | rec_pipe
	check_private "$REC" "$RECDIR/p0-iomem-$UTC.log"
}

# ---------------------------------------------------------------- P1

cmd_p1() {
	local out old t0 rcs oops smmu rc
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
	out="$(board 500 b_quiesce 'b_iomem postrmmod')"
	printf '%s\n' "$out" | grep -v '^iomemline ' | rec_pipe
	rcs="$(printf '%s\n' "$out" | grep -c '^rmmod [a-z_]* rc=0$')"
	oops="$(kv quiesce_oops_lines "$out")"
	smmu="$(kv quiesce_smmu_emem_lines "$out")"
	if [ "$rcs" = 4 ] && [ "$oops" = 0 ] && [ "$smmu" = 0 ]; then
		rec "p1 GATE: rmmod_ok=4/4 oops_lines=0 smmu_emem_lines=0"
	else
		rec "p1 GATE NOT MET: rmmod_ok=$rcs/4 oops_lines=${oops:-?} smmu_emem_lines=${smmu:-?}"
	fi
	rec "p1 step 5: sudo -n reboot, then wait for a new boot_id"
	t0=$(date +%s)
	board 30 b_reboot | rec_pipe
	wait_new_boot_id "$old" "$t0" 0 0
	rc=$?
	if [ "$rc" != 0 ]; then
		rec "p1 NO RETURN within $RETURN_BOUND s: read COM3, then power-cycle"
		check_private "$REC"
		exit 2
	fi
	rec "p1 back_after_s=$BACK_S new_boot_id=$NEW_BOOT_ID"
	board 60 b_identity b_pstore | rec_pipe
	check_private "$REC"
}

# ---------------------------------------------------------------- reboot

cmd_reboot() {
	local out old t0 rc
	need_host
	IMG=""
	UTC="$(utc_now)"
	if [ -n "${M4_RECORD_DIR:-}" ]; then
		need_record_dir
		rec_open "$RECDIR/reboot-$UTC-board.log"
	fi
	out="$(board 60 b_identity)" || die "board unreachable (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	old="$(kv boot_id "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	t0=$(date +%s)
	board 30 b_reboot | rec_pipe
	wait_new_boot_id "$old" "$t0" 0 0
	rc=$?
	if [ "$rc" != 0 ]; then
		rec "reboot NO RETURN within $RETURN_BOUND s: read COM3, then power-cycle"
		exit 2
	fi
	rec "reboot back_after_s=$BACK_S new_boot_id=$NEW_BOOT_ID"
	board 60 b_identity b_pstore | rec_pipe
	[ -n "$REC" ] && check_private "$REC"
	return 0
}

# ---------------------------------------------------------------- run (§7)

cmd_run() {
	local base out old up rc wrc pstore_before pstore_after newrec shim reason lsha rcs oops gok gov0 gov4 stuck left
	local bb com3 run_id verdict
	need_host
	need_record_dir
	IMG="$1"
	resolve_kimg "$IMG"
	case "${M4_RUN_ID:-}" in r0|r1|q|t1|t2|t3|t4|t5) ;; *) die "M4_RUN_ID must be r0, r1, q, t1, t2, t3, t4 or t5 (§7.2 item 7)" ;; esac
	case "${M4_QUIESCE:-}" in 0|1) ;; *) die "M4_QUIESCE must be 1 (O4 adopted) or 0 (not adopted), stated on every run" ;; esac
	case "${M4_GOVERNOR_PIN:-}" in 0|1) ;; *) die "M4_GOVERNOR_PIN must be 1 (O5 adopted) or 0 (not adopted), stated on every run" ;; esac
	stuck="${M4_STUCK_S:-600}"
	[[ "$stuck" =~ ^[0-9]+$ ]] || die "M4_STUCK_S must be a whole number of seconds (0 turns the early stop off)"
	KEXEC_MODE="${M4_KEXEC:-s}"
	case "$KEXEC_MODE" in s|c) ;; *) die "M4_KEXEC must be s, or c for contingency K1" ;; esac
	if [ -z "${M4_COM3_LOG:-}" ] || [ ! -f "$M4_COM3_LOG" ]; then
		die "M4_COM3_LOG must name the running capture-com3-raw.ps1 file: COM3 is a mandatory co-record (§8.3)"
	fi
	find_python || die "no working python for the parser (step 8b)"

	# Gate A (§7.2 item 3): before any board session.
	left="$(capture_left_s)"
	case "$left" in
	noheader) die "M4_COM3_LOG does not begin with '--- raw capture started': start capture-com3-raw.ps1 (-Seconds ${CAPTURE_S:-?})" ;;
	noepoch)  die "M4_COM3_LOG's header has no epoch= and seconds=: start capture-com3-raw.ps1 (-Seconds ${CAPTURE_S:-?})" ;;
	esac
	(( left >= RETURN_BOUND + 2180 )) \
		|| die "gate A: the COM3 capture has $left s left, under return_bound_s + 2180 = $(( RETURN_BOUND + 2180 )) s: start a fresh capture with -Seconds ${CAPTURE_S:-?}"

	UTC="$(utc_now)"
	run_id="$IMG-$M4_RUN_ID"
	base="$RECDIR/$IMG-$M4_RUN_ID-$UTC"
	rec_open "$base-board.log"
	if [ "$KEXEC_MODE" = s ]; then
		rec "run image=$IMG run_id=$M4_RUN_ID utc=$UTC kexec_syscall=kexec_file_load (-s)"
	else
		rec "run image=$IMG run_id=$M4_RUN_ID utc=$UTC kexec_syscall=kexec_load (-c -l ... -i, contingency K1)"
	fi
	rec "run kimg=$IMG.kimg bytes=$(stat -c %s "$KIMG") pc_sha256=$KIMG_SHA params=$(basename "$PARAMS") params_sha256=$(sha256sum "$PARAMS" | cut -d' ' -f1)"
	# I25 (m4-design.md 14.6): keep the params this run used beside its records, so a later
	# make-m4-images.sh run cannot overwrite the only copy.
	cp "$PARAMS" "$base-params.log" || die "cannot copy $PARAMS into the record directory"
	check_private "$base-params.log"
	rec "run params_copy=$(basename "$base-params.log")"
	rec "run com3_log=$(basename "$M4_COM3_LOG") capture_left_s=$left return_bound_s=$RETURN_BOUND quiesce_O4=$M4_QUIESCE governor_pin_O5=$M4_GOVERNOR_PIN"

	# step 2: the kimg, identity, the uptime rules, pstore before
	out="$(board 300 b_sha b_identity b_pstore)" || die "board unreachable (rc=$?); nothing was changed on the board"
	printf '%s\n' "$out" | rec_pipe
	[ "$(kv board_sha256 "$out")" = "$KIMG_SHA" ] || die "the board's $IMG.kimg differs from the PC's: run stage"
	old="$(kv boot_id "$out")"
	up="$(kv uptime_s "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	pstore_before="$(printf '%s\n' "$out" | grep '^pstore ')"
	if awk -v u="$up" -v m="${M4_MAX_UPTIME_S:-7200}" 'BEGIN { exit !(u + 0 >= m + 0) }'; then
		die "L4T has been up ${up%.*} s, at or above ${M4_MAX_UPTIME_S:-7200} s: reboot it first ($PROG reboot)"
	fi
	# §7.2 item 4: a quiesce only on a freshly booted L4T.
	if [ "$M4_QUIESCE" = 1 ] && awk -v u="$up" -v m="${M4_QUIESCE_MAX_UPTIME_S:-1800}" 'BEGIN { exit !(u + 0 >= m + 0) }'; then
		die "L4T has been up ${up%.*} s, at or above M4_QUIESCE_MAX_UPTIME_S=${M4_QUIESCE_MAX_UPTIME_S:-1800} s with M4_QUIESCE=1: run '$PROG reboot' first (§7.2 item 4)"
	fi

	# step 3 (O5)
	if [ "$M4_GOVERNOR_PIN" = 1 ]; then
		out="$(board 60 b_governor)"
		rc=$?
		printf '%s\n' "$out" | rec_pipe
		gok="$(printf '%s\n' "$out" | grep -cE '^governor policy[04] performance rc=0$')"
		if [ "$rc" != 0 ] || [ "$gok" != 2 ]; then
			rec "run GOVERNOR PIN FAILED (session rc=$rc, governor_ok=$gok/2): no quiesce and no kexec. L4T is still running"
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
		rec "run FREQUENCY READ FAILED (session rc=$rc): no quiesce and no kexec. L4T is still running"
		check_private "$REC"
		exit 3
	fi
	if [ "$M4_GOVERNOR_PIN" = 1 ] && { [ "$gov0" != performance ] || [ "$gov4" != performance ]; }; then
		rec "run GOVERNOR NOT PINNED (policy0=$gov0 policy4=$gov4 after the pin): no quiesce and no kexec. L4T is still running"
		check_private "$REC"
		exit 3
	fi
	rec "run step 3 governor read back: policy0=$gov0 policy4=$gov4 (O5=$M4_GOVERNOR_PIN)"

	# step 4 (O4)
	if [ "$M4_QUIESCE" = 1 ]; then
		out="$(board 500 b_quiesce 'b_iomem run')"
		printf '%s\n' "$out" | grep -v '^iomemline ' | rec_pipe
		printf '%s\n' "$out" | sed -n 's/^iomemline run //p' | redact > "$base-iomem-postrmmod.log"
		rcs="$(printf '%s\n' "$out" | grep -c '^rmmod [a-z_]* rc=0$')"
		oops="$(kv quiesce_oops_lines "$out")"
		if [ "$rcs" != 4 ] || [ "${oops:-x}" != 0 ]; then
			rec "run QUIESCE FAILED (rmmod_ok=$rcs/4 oops_lines=${oops:-?}): no kexec. The board is part-quiesced: reboot L4T before another attempt"
			check_private "$REC" "$base-iomem-postrmmod.log"
			exit 3
		fi
	fi

	# Gate B (§7.2 item 3): just before the kexec session.
	left="$(capture_left_s)"
	if ! [[ "$left" =~ ^-?[0-9]+$ ]] || (( left < RETURN_BOUND + 1200 )); then
		rec "run GATE B: the COM3 capture has $left s left, under return_bound_s + 1200 = $(( RETURN_BOUND + 1200 )) s: no kexec. The board may be quiesced: reboot L4T, start a fresh capture (-Seconds ${CAPTURE_S:-?}), then run again"
		check_private "$REC"
		exit 3
	fi
	rec "run gate B: capture_left_s=$left: ok"
	rec "run com3_bytes_before_kexec=$(stat -c %s "$M4_COM3_LOG" 2>/dev/null || echo 0)"

	# step 5
	rec "run step 5: kexec load, kexec_loaded, last frequency read, systemctl kexec"
	out="$(board 300 b_kexec_go)"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	if [ -n "$(kv governor_final_fail "$out")" ]; then
		rec "run GOVERNOR REVERTED before kexec: the image was unloaded, no kexec. L4T is still running"
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

	# step 6: the return bound from IMG.params, with the one COM3-growth extension
	wait_new_boot_id "$old" "$(date +%s)" "$stuck" 1
	wrc=$?
	rec "run com3_bytes_at_return=$(stat -c %s "$M4_COM3_LOG" 2>/dev/null || echo 0) extended=$EXTENDED"
	case "$wrc" in
	0)
		rec "run back_after_s=$BACK_S (counted from the end of the kexec session) new_boot_id=$NEW_BOOT_ID"
		;;
	3)
		rec "run the old boot_id answered every poll for $WAITED_S s after the kexec session (M4_STUCK_S=$stuck): Linux never went down. Keep the capture running and check /sys/kernel/kexec_loaded by hand"
		check_private "$REC"
		exit 3
		;;
	*)
		rec "run NO RETURN within $RETURN_BOUND s (extended=$EXTENDED): read COM3 first, then power-cycle, and record that the black box was lost (§9)"
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
			rec "run VALIDITY: no T234-SHIM and a new dmesg-ramoops record: Linux died before the jump. Retry from a fresh L4T; do not judge the image"
		else
			rec "run VALIDITY: no T234-SHIM in the black box: this run never reached the shim"
		fi
	fi

	# step 8: raw copies first (§7.2 item 6)
	bb="$base-blackbox.log"
	com3="$base-com3.log"
	if timeout 300 scp "${ssh_work[@]}" "$ORIN_HOST:$IMG-$UTC-blackbox.log" "$bb" </dev/null; then
		lsha="$(sha256sum "$bb" | cut -d' ' -f1)"
		if [ "$lsha" = "$(kv blackbox_sha256 "$out")" ]; then
			rec "run black box copied: $(basename "$bb") bytes=$(stat -c %s "$bb") sha256=$lsha, equal to the board's"
		else
			rec "run black box copy sha256 $lsha DIFFERS from the board's"
		fi
	else
		rec "run black box copy FAILED: it stays on the board as $IMG-$UTC-blackbox.log"
		bb=""
	fi
	if cp "$M4_COM3_LOG" "$com3" 2>/dev/null; then
		rec "run COM3 copied: $(basename "$com3") bytes=$(stat -c %s "$com3") raw_sha256=$(sha256sum "$com3" | cut -d' ' -f1). L4T is back: stop the capture after this command returns"
	else
		rec "run COM3 copy FAILED (the capture may hold the file): stop the capture, then copy it as $(basename "$com3")"
		com3=""
	fi

	# step 8b: the parser on the raw copies (§7.2 item 7)
	if [ -n "$com3" ]; then
		verdict="$(timeout 900 "$PY_BIN" "$PARSER" run --params "$PARAMS" --blackbox "${bb:-none}" --com3 "$com3" \
			--run-id "$run_id" --out-dir "$RECDIR/out" --reset-reason "$reason" 2>&1)"
		rc=$?
		printf '%s\n' "$verdict" | grep -E '^(M4PC |parse-m4: )' | rec_pipe
		rec "run parser rc=$rc (parse log: out/$run_id-parse.log)"
	else
		rec "run parser NOT run: no COM3 copy"
	fi

	# only then the privacy scan, whose redaction could change a body's bytes
	[ -n "$bb" ] && privacy_scan "$bb"
	[ -n "$com3" ] && privacy_scan "$com3"
	if [ -n "$bb" ]; then
		extract_file "$bb" | rec_pipe
		[ -n "$com3" ] && consistency_files "$bb" "$com3" | rec_pipe
	fi
	rec "run done. Record: $(basename "$REC"). The verdict is the parser's M4PC run_verdict line above"
	check_private "$REC" "$bb" "$com3" "$base-iomem-postrmmod.log" "$RECDIR/out/$run_id-parse.log"
	return 0
}

# ---------------------------------------------------------------- extraction (§7.2 items 8-10)

NEG_TOKENS=(
	't234: EL1' 't234: EL2' 'hvtimer STOP' 'el2-host requested but' 'continuing despite' 'probe off'
	'ASSERT' 'start failure' 'start timeout' 'released but' 'entered at EL1' 'wake timeout' 'not awake'
	'transfer hook ran' 'PE is not awake' 'does not match cpu 0' 'tick=dead' 'tick=bad' 'CENSUS FAIL' 'RESULT FAIL'
	'BWAIT guard deadline' 'STAMP exec-failed' 'STAMP read-error' 'Unable to start' '[g2.conf:' 'Could not load library'
	'unrecoverable stall' 'sentinel-recovery exhausted' 'echo seq mismatch' 'killed=1'
	'No system file system' 'Unable to access /dev/hd0' 'BAD-LANDING' 'Shutdown['
	'by=early' 'by=sigint' 'by=kill' 'by=none' 'path=none' 'aborted=1' 'deadline=1'
	'state=wrapped' 'state=unknown' 'mem_trace' 'mem_format'
)
NEG_PATTERNS=(
	'M4 FAIL([^_]|$)' '^TRCCTL .*rc=-1' 'mismatches=[1-9]' 'order_violated=[1-9]' 'drops=[1-9]'
	'marker_collision=[1-9]' 'M4C END w=[A-Za-z0-9_.-]+ rc=[13]'
)

extract_file() {
	local f="$1" t tok n bytes pat
	t="$(mktemp)"
	tr -d '\r' < "$f" > "$t"
	bytes=$(stat -c %s "$f")
	echo "extract file=$(basename "$f") bytes=$bytes sha256=$(sha256sum "$f" | cut -d' ' -f1)"
	if [ "$bytes" -ge 65500 ]; then
		echo "extract size: the 65,520 B cap was hit, head only; the tail is on COM3 (§8.3)"
	elif [ "$bytes" -ge 60000 ]; then
		echo "extract size: at or above 60,000 B, gate G1-M4 (§8.3): contingency C4 for later images"
	else
		echo "extract size: under 60,000 B (§8.3 G1-M4)"
	fi
	echo "extract lines:"
	grep -aE '^(T234-SHIM|T234 M4 |Enabling EL2 host|t234: (all [0-9]+ cpus parked|cpu [0-9]+ el2-host|hvtimer cpu)|SMPCHECK (census|CENSUS|done)|BWAIT (guard|run |path hit=/dev/qvmdisk0)|M4 (CONFIG|CHECK|FAIL|MEM|QVM|STATE (end|diag)|TRACE|STOP|KEVFILE|TEXT|FLT)|M4C (QVM|TIME64|RING|VCPU|OFFSET|TRIPLES|PAIRS|STAT|WARN|FLT|END) |TRCCTL |tcu-cat:|rc=|samples=|P50=|sentinel_|QNX qnx-guest)' "$t" | sed 's/^/  /'
	echo "extract guest_banner_lines=$(grep -acE 'QNX qnx-guest 8[.]0[.]0 .*ARMv8_Foundation_Model aarch64le' "$t")"
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
		for (i = 1; i <= n; i++) print "  " line[order[i]]
		if (!("qvm_launch" in cyc)) { print "extract headline: no qvm_launch stamp"; exit }
		c = ("qvm_launch" in cps) ? cps["qvm_launch"] + 0 : 31250000
		if (c <= 0) c = 31250000
		if ("banner" in cyc) printf "extract headline banner-qvm_launch ms=%.3f\n", ms(cyc["banner"] - cyc["qvm_launch"])
		if (("ipc_start" in cyc) && ("ipc_end" in cyc)) printf "extract segment ipc_end-ipc_start ms=%.3f\n", ms(cyc["ipc_end"] - cyc["ipc_start"])
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
		if (!s && !b) { print "extract ipc: no client output (trace mode, or the IPC never ran)"; exit }
		printf "extract ipc samples=%s sentinel_recoveries=%s sum=%s bwait_rc=%s killed=%s ms=%s\n", (s ? ns : "?"), (r ? nr : "?"), ((s && r) ? ns + nr : "?"), (b ? brc : "?"), (b ? bk : "?"), (b ? bms : "?")
	}' "$t"
	awk '/^M4 MEM / { v = $4; sub(/MB.*/, "", v); printf "extract mem %s free_mb=%s\n", $3, v }' "$t"
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
	# The counter's fixture records carry wrapped rings and order violations on purpose (§4.5.9; §14).
	grep -avE '^M4C [A-Z0-9]+ w=fix( |$)' "$t" > "$t.neg" || true
	echo "extract negative tokens (m4-design.md §7.2 item 9; fixture records excluded):"
	for pat in "${NEG_PATTERNS[@]}"; do
		n=$(grep -acE -- "$pat" "$t.neg")
		[ "$n" = 0 ] || echo "  '$pat' x$n"
	done
	for tok in "${NEG_TOKENS[@]}"; do
		n=$(grep -acF -- "$tok" "$t.neg")
		[ "$n" = 0 ] || echo "  '$tok' x$n"
	done
	echo "extract negative tokens end"
	rm -f "$t" "$t.neg"
}

consistency_files() {
	local re='(STAMP |samples=|P50=|sentinel_recoveries=|BWAIT run prog=qnx-host-client |M4C |M4 (TRACE|STOP|KEVFILE|TEXT|FLT) |TRCCTL |tcu-cat: ).*' a b na
	a="$(mktemp)"
	b="$(mktemp)"
	tr -d '\r' < "$1" | grep -aoE "$re" > "$a"
	tr -d '\r' < "$2" | grep -aoE "$re" > "$b"
	na=$(wc -l < "$a")
	echo "consistency blackbox_lines=$na com3_lines=$(wc -l < "$b") (record lines, CR-stripped, in order)"
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

# ---------------------------------------------------------------- sizing and series wrappers (§7.2 item 11)

cmd_size() {
	local which="$1"
	shift
	need_record_dir
	find_python || die "no working python"
	if [ "$which" = r1 ]; then
		timeout 120 "$PY_BIN" "$PARSER" size-r1 --r0-parse "$1"
	else
		timeout 120 "$PY_BIN" "$PARSER" size-r2 --r1-parse "$1" --r0-parse "$2"
	fi
}

cmd_series() {
	need_record_dir
	find_python || die "no working python"
	timeout 300 "$PY_BIN" "$PARSER" series --parse-logs "$@" \
		--csv "$RECDIR/out/orin-native-qvm-trace-latest.csv" \
		--cloud-csv "$HERE/../../results/cloud/cloud-ipc-latest.csv" --out-dir "$RECDIR/out"
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
size-r1)     { [ $# -eq 2 ] && [ -f "$2" ]; } || usage; cmd_size r1 "$2" ;;
size-r2)     { [ $# -eq 3 ] && [ -f "$2" ] && [ -f "$3" ]; } || usage; cmd_size r2 "$2" "$3" ;;
series)      [ $# -eq 6 ] || usage; shift; cmd_series "$@" ;;
*)           usage ;;
esac
