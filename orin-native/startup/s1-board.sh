#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# s1-board.sh — the S1-F board procedure, driven from the PC in Git Bash.
#
# Phase 3b. Encodes results/orin-native-port/20260909T1100Z/s1-design.md,
# revision 2 (the owner took D1-D19 as recommended): the s1-board.sh row of
# §4.2, B0's staging and p0 (§6.5), the return and records of §6.11, the uptime
# limits of §6.12, §2 rule 6a's power-cut rule and §8's board reads. It is
# m4-board.sh (not edited) with S1's differences only. The verdict is the
# parser's (orin-native/s1/parse-s1.py run), written to <rec>/<step>/parse-s1.txt.
#
# RUNS ON the PC. It reaches the board over ssh and scp only. It never opens
# COM3: a capture started from Git Bash receives nothing (m2-runs.md:135-137),
# so orin-native/m4/capture-com3-raw.ps1 is started from PowerShell before
# `run` and named here.
#
# Every S1 board rung needs the owner at the plug (§2 rule 6): a native image
# that hangs after kexec does not recover by itself. Power is cut by the class
# of the last COM3 output, never by the clock alone (§2 rule 6a): `advice`
# reads that class.
#
# Fixed by the design, not by the operator: every rung runs M3's quiesce (four
# modules) and the governor pin (D6, §6.6); a run refuses at or above 7,200 s of
# L4T uptime, and at or above 1,800 s because it quiesces. Neither limit can be
# overridden (§7.3), and a quiesce never runs on a boot that staging, p0, p1 or
# an earlier run already used (§6.5 step 4): run `reboot` first.
#
# USAGE
#   s1-board.sh stage IMG              copy IMG.kimg, resumable, sha256-gated
#   s1-board.sh p0 IMG                 §8 board reads, nvbootctrl, kexec tree sha256,
#                                      kexec -s -l / -u, the landing line (§6.5)
#   s1-board.sh p1                     quiesce rehearsal, then reboot L4T
#   s1-board.sh reboot                 reboot L4T, wait for a new boot_id
#   s1-board.sh run IMG                one kexec round, records fetched, parser run
#   s1-board.sh advice BOARDLOG        §2 rule 6a: the power-cut class of the COM3
#                                      capture. BOARDLOG is the run, p1 or reboot
#                                      record: its NO RETURN line shows the bound
#                                      has passed, and a run's gives the kexec
#                                      offset. Without one, no cut is advised
#   s1-board.sh extract FILE           the record lines of a black box or COM3 copy
#   s1-board.sh consistency BB COM3    the black box's records as a subsequence of COM3's
#   s1-board.sh b1-compare BB REF      B1: a black box against M1b R2's, addresses masked
#   s1-board.sh redact-selftest        the redaction, against synthetic values
#   s1-board.sh harness-selftest       advice, consistency, extract, B1 tokens: synthetic
#
# IMAGES (the step each one is, §6.12)
#   s1-m1b-p6 B1 (no S1 host script; no parser)   s1-h1 B2 (host)
#   s1-n1 B3 (boot)   s1-n2 B4 (hold)   s1-q2 B5 (q2)   s1-d1 d1 (boot; a diagnostic)
#
# ENVIRONMENT (no host, user, key or path is written into this file)
#   ORIN_HOST              board commands: user@address of the board (required)
#   ORIN_KEY               ssh private key file, passed as -i (optional)
#   SSH_OPTS               extra ssh and scp flags, word-split (optional)
#   S1_BOARD_HOSTNAME      the board's hostname for the redaction (optional;
#                          otherwise asked of the board)
#   S1_KIMG_DIR            where IMG.kimg and IMG.params are on the PC
#                          (default ../shim/out/s1 from this script)
#   S1_KIMG_SHA256         the generator's sha256 for IMG; checked when set
#   S1_REMOTE_DIR          kimg directory on the board, relative to its home
#                          unless absolute (default: the home directory)
#   S1_RECORD_DIR          stage, p0, p1, run: results/orin-native-port/<utc>/s1
#                          (required; must be git-ignored)
#   S1_COM3_LOG            run, advice: the running raw capture's file (run:
#                          required); its header must carry epoch= and seconds=
#   S1_REF_CONF_SHA256     run of s1-n1, s1-n2, s1-q2, s1-d1: T2's conf_sha256
#                          (required there; parse-s1.py --ref-conf-sha256)
#   S1_KEXEC_TREE_SHA256   run: p0's kexec tree sha256 (default: the newest p0
#                          record of IMG in S1_RECORD_DIR)
#   S1_KEXEC               s = kexec_file_load (default); c = K1, kexec -c -l IMG -i
#   S1_RETURN_BOUND_S      give-up bound after kexec; default and minimum are
#                          IMG.params' return_bound_s
#   S1_STUCK_S             run: stop with exit 3 once the old boot_id has
#                          answered every poll this long (default 600, 0 = off)
#   S1_POLL_S              seconds between boot_id polls (default 10)
#
# PARAMS (IMG.params, written by make-s1-images.sh; key=value lines)
#   kimg_sha256, return_bound_s, capture_s (all required); mode and rung (when
#   present, they must equal the image table above: mode b1|host|boot|hold|q2).
#
# RECORDS. A run writes under $S1_RECORD_DIR/<step>/ (a second attempt of a
# step goes to <step>-a2, and so on: a record is never replaced, §5.3). Every
# file there, and every record the other commands write, lies in a git-ignored
# directory and is re-checked with git check-ignore: evaluation output under NC
# QDL v7 4.6(i), private and unpublished. The parser reads the raw copies first;
# only then does the redaction filter run over them. No duration and no FreeMem
# value is extracted (§2 rule 8).
#
# EXIT: 0 done; 1 refused or failed before anything changed on the board (p0:
# a gate not met); 2 the board did not come back within the bound; 3 stopped
# with L4T running (a gate, quiesce failed, kexec not issued, or Linux never
# went down); 4 records complete, but nvbootctrl differs from the session's
# first reading (F30): stop all board work.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROG="$(basename "$0")"
S1DIR="$HERE/../s1"
PARSER="$S1DIR/parse-s1.py"

usage() { sed -n '3,/^set -uo/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//' >&2; exit 2; }
ON_DIE=""
die()   { echo "$PROG: FAIL: $*" >&2; [ -n "${REC:-}" ] && printf '%s\n' "FAIL: $*" | redact >> "$REC"; [ -n "$ON_DIE" ] && "$ON_DIE"; exit 1; }
note()  { echo "$PROG: $*" >&2; }
utc_now() { date -u +%Y%m%dT%H%M%SZ; }
iso_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# §6.12 and §7.3: fixed, with no override.
MAX_UPTIME_S=7200
QUIESCE_MAX_UPTIME_S=1800
for v in S1_MAX_UPTIME_S S1_QUIESCE_MAX_UPTIME_S S1_QUIESCE S1_GOVERNOR_PIN; do
	if [ -n "${!v+x}" ]; then
		echo "$PROG: FAIL: $v is set: the uptime limits, the quiesce and the governor pin are fixed by s1-design.md (§6.6, §6.12, §7.3); unset it" >&2
		exit 1
	fi
done

# §8 item 5 and D3: the board's /boot files, as copied to the PC.
PIN_BOOT_IMAGE=b844b7cfaafd071a25f1dc91d2ad1d7369008c28ce84b25625efc425825a2120
PIN_BOOT_INITRD=f0cdcc61064ff6e9ac99b1c4ff02468dbe9cf0c0e9404cf429524d741f6883f8
# §8 PC item 2 and §5.2 items 2 and 5: the PC's inputs, checked before a board round.
# The Image and the L4T initrd are D3's copies (the pins above); the payload initrd is
# orin-native/s1/initrd.manifest's output pin; the configuration is T2's.
PIN_PC_INITRD_CPIO=44e81ea65903e25a66cafe6b35f28776bba1f6ae8082251cc8a988a689495ab6
PIN_CONF=85d51359229ea4fa9860de76519a523250e71c5c77666821a07e7f4561196e31
# §8 item 7: ramoops_carveout's reg, two address and two size cells.
RAMOOPS_REG_HEX=00000002725f00000000000000200000

# The firmware banner after the image's reset: parse-s1.py's FW_BANNER, word for word.
FW_BANNER=('ESC to enter Setup' 'F11 to enter Boot Manager Menu' 'L4TLauncher:' 'MB1')

# ---------------------------------------------------------------- ssh

ssh_base=(-o BatchMode=yes -o ConnectTimeout=10)
[ -n "${ORIN_KEY:-}" ] && ssh_base+=(-i "$ORIN_KEY")
# shellcheck disable=SC2206  # deliberate word-splitting, as scripts/twin/sync-qhv.sh
ssh_base+=(${SSH_OPTS:-})
ssh_work=("${ssh_base[@]}" -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
ssh_poll=("${ssh_base[@]}" -o ServerAliveInterval=3 -o ServerAliveCountMax=2)

need_host() { [ -n "${ORIN_HOST:-}" ] || die "ORIN_HOST is not set (user@address of the board)"; }

RDIR="${S1_REMOTE_DIR:-}"
[[ -z "$RDIR" || "$RDIR" =~ ^[A-Za-z0-9._/-]+$ ]] || die "S1_REMOTE_DIR has characters outside [A-Za-z0-9._/-]"

# ---------------------------------------------------------------- redaction (m4-board.sh's)

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

# The board's own hostname: not derivable from ORIN_HOST, and printed by the
# serial console in systemd's banner, getty's banner and the login prompt.
# learn_hostname() asks the board once per command that talks to it.
R_HOSTNAME="${S1_BOARD_HOSTNAME:-}"

# An address, but not a version string: octets only, 0-255, no leading zero,
# with a non-token character or an end on each side (m4-board.sh's reasons).
IDENT_OCTET='(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])'
IDENT_IP="(^|[^-._0-9A-Za-z])$IDENT_OCTET([.]$IDENT_OCTET){3}($|[^-._0-9A-Za-z])"
IDENT_MAC='[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}'
IDENT_RE="$IDENT_IP|$IDENT_MAC"

learn_hostname() {
	[ -n "$R_HOSTNAME" ] && return 0
	[ -n "${ORIN_HOST:-}" ] || return 0
	R_HOSTNAME="$(timeout 20 ssh "${ssh_poll[@]}" "$ORIN_HOST" hostname </dev/null 2>/dev/null | tr -d "\r\n")"
	case "$R_HOSTNAME" in
	*[!A-Za-z0-9._-]*) R_HOSTNAME="" ;;
	esac
	[ "${#R_HOSTNAME}" -ge 3 ] || R_HOSTNAME=""
	return 0
}

redact() {
	awk -v BINMODE=3 -v u="$R_USER" -v h="$R_HOST" -v k="$R_KEY" -v kb="$R_KEYBASE" -v pu="$R_PCUSER" -v hn="$R_HOSTNAME" '
	function lit(s, a, r,    i, out) {
		if (a == "") return s
		out = ""
		while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)) }
		return out s
	}
	function octet_ok(o,    n) {
		if (o !~ /^[0-9]+$/) return 0
		if (length(o) > 1 && substr(o, 1, 1) == "0") return 0
		n = o + 0
		return (n <= 255)
	}
	function mask_ips(s,    out, rest, tok, parts, i, ok) {
		out = ""
		rest = s
		while (match(rest, /[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+/)) {
			tok = substr(rest, RSTART, RLENGTH)
			split(tok, parts, ".")
			ok = 1
			for (i = 1; i <= 4; i++) if (!octet_ok(parts[i])) ok = 0
			out = out substr(rest, 1, RSTART - 1)
			if (ok) out = out "<ip>"
			else out = out tok
			rest = substr(rest, RSTART + RLENGTH)
		}
		return out rest
	}
	{
		line = $0
		line = lit(line, k, "<orin-key>")
		line = lit(line, kb, "<orin-key>")
		if (hn != "") line = lit(line, hn, "<orin-host>")
		if (u != "") { line = lit(line, u "@", "<user>@"); line = lit(line, "/home/" u, "/home/<user>") }
		if (u != "") line = lit(line, u, "<user>")
		if (pu != "") { line = lit(line, "Users/" pu, "Users/<user>"); line = lit(line, "Users\\" pu, "Users\\<user>"); line = lit(line, "/home/" pu, "/home/<user>") }
		line = lit(line, h, "<orin-ip>")
		line = mask_ips(line)
		gsub(/[0-9A-Fa-f][0-9A-Fa-f](:[0-9A-Fa-f][0-9A-Fa-f]){5}/, "<mac>", line)
		print line
	}'
}

# Counts per class. Prints: total addr=N mac=N name=N
ident_hits() {
	local f="$1" pats=() addr mac name total
	[ -n "$R_USER" ] && pats+=(-e "$R_USER@" -e "/home/$R_USER")
	[ -n "$R_PCUSER" ] && pats+=(-e "Users/$R_PCUSER" -e "Users\\$R_PCUSER" -e "/home/$R_PCUSER")
	[ -n "$R_HOST" ] && pats+=(-e "$R_HOST")
	[ -n "$R_KEY" ] && pats+=(-e "$R_KEY")
	[ -n "$R_KEYBASE" ] && pats+=(-e "$R_KEYBASE")
	[ -n "$R_HOSTNAME" ] && pats+=(-e "$R_HOSTNAME")
	# grep -c prints 0 and exits 1 when nothing matches: '|| echo 0' made that
	# "0<newline>0", the sum failed, and a file with hits in another class was kept raw.
	addr="$(grep -acE "$IDENT_IP" "$f" 2>/dev/null)"
	mac="$(grep -acE "$IDENT_MAC" "$f" 2>/dev/null)"
	name=0
	[ "${#pats[@]}" -gt 0 ] && name="$(grep -acF "${pats[@]}" "$f" 2>/dev/null)"
	addr="${addr:-0}" mac="${mac:-0}" name="${name:-0}"
	total=$(( addr + mac + name ))
	echo "$total addr=$addr mac=$mac name=$name"
}

# ---------------------------------------------------------------- records

REC=""
RECDIR=""

# §2 rule 10 and §8 item 12: the record directory is inside this repository and
# git-ignored for any file name, because parse-s1.py writes parse-s1.txt and
# s1-fdt.dtb beside the .log records and refuses a path that is not ignored.
need_record_dir() {
	local d="${S1_RECORD_DIR:-}" top_rec top_here
	[ -n "$d" ] || die "S1_RECORD_DIR is not set (results/orin-native-port/<utc>/s1, private)"
	case "$d" in
	*results/cloud*|*results/hw*) die "S1_RECORD_DIR must not be under results/cloud or results/hw (s1-design.md §2 rule 10)" ;;
	esac
	mkdir -p "$d" || die "cannot create S1_RECORD_DIR"
	RECDIR="$(cd "$d" && pwd)"
	top_here="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null)"
	top_rec="$(git -C "$RECDIR" rev-parse --show-toplevel 2>/dev/null)"
	[ -n "$top_here" ] && [ "$top_rec" = "$top_here" ] \
		|| die "S1_RECORD_DIR is not inside this repository's work tree: the parser refuses outputs it cannot check with git check-ignore"
	git -C "$RECDIR" check-ignore -q "s1-ignore-probe.txt" \
		|| die "S1_RECORD_DIR is not git-ignored (a test name in it is not ignored): use results/orin-native-port/<utc>/s1 (§8 item 12)"
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
		[ -n "$f" ] && [ -e "$f" ] || continue
		d="$(dirname "$f")"
		git -C "$d" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue
		if ! git -C "$d" check-ignore -q "$(basename "$f")"; then
			note "WARNING: $(basename "$f") is NOT git-ignored: private evaluation output, keep it out of any commit"
		fi
	done
}

# Redact a file in place, byte for byte apart from the redactions themselves
# (m4-board.sh's: the one byte gawk adds to an unterminated last line is taken back).
redact_file() {
	local f="$1"
	redact < "$f" > "$f.redact" || return 1
	if [ -s "$f" ] && [ "$(tail -c 1 "$f" | od -An -tu1 | tr -d " ")" != "10" ] &&
		[ "$(tail -c 1 "$f.redact" | od -An -tu1 | tr -d " ")" = "10" ]; then
		head -c -1 "$f.redact" > "$f.redact2" && mv "$f.redact2" "$f.redact"
	fi
	mv "$f.redact" "$f"
}

privacy_scan() {
	local f="$1" hits n classes before after
	learn_hostname
	hits="$(ident_hits "$f")"
	n="${hits%% *}"
	classes="${hits#* }"
	if [ "${n:-0}" -gt 0 ]; then
		before="$(stat -c %s "$f" 2>/dev/null || echo 0)"
		redact_file "$f" || die "redaction failed on $(basename "$f")"
		after="$(stat -c %s "$f" 2>/dev/null || echo 0)"
		rec "privacy $(basename "$f"): $n identifying line(s) redacted ($classes), bytes $before -> $after, copy sha256=$(sha256sum "$f" | cut -d" " -f1)"
	else
		rec "privacy $(basename "$f"): nothing identifying found ($classes), copy kept raw"
	fi
}

find_python() {
	local t
	PY_BIN=""
	for t in python python3 py; do
		if command -v "$t" >/dev/null 2>&1 && "$t" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
			PY_BIN="$t"
			return 0
		fi
	done
	return 1
}

# §6.5 step 4: a quiesce runs only on a boot that no staging, p0, p1 or earlier
# run used. Each of those appends the boot_id it saw; run and p1 refuse a listed one.
BOOT_MARKS=""
mark_boot() {
	[ -n "$RECDIR" ] && [[ "$1" =~ ^[0-9a-f-]{36}$ ]] || return 0
	BOOT_MARKS="$RECDIR/used-boot-ids.log"
	printf 'boot_id=%s by=%s utc=%s\n' "$1" "$2" "$(utc_now)" >> "$BOOT_MARKS"
	check_private "$BOOT_MARKS"
}
boot_used() {
	[ -n "$RECDIR" ] && [ -f "$RECDIR/used-boot-ids.log" ] || return 1
	grep -q "^boot_id=$1 " "$RECDIR/used-boot-ids.log"
}

# ---------------------------------------------------------------- board side (m4-board.sh's, plus S1's reads)

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

# The 80000000-ffffffff lines; the full listing is not kept on the board (§2 rule 5).
b_iomem() {
	local f
	f=$(mktemp)
	sudo -n cat /proc/iomem > "$f"
	echo "iomem_$1_rc=$?"
	grep -E '^[[:space:]]*[89a-f][0-9a-f]{7}-[0-9a-f]{8} :' "$f" | sed "s/^/iomemline $1 /"
	rm -f "$f"
}

# §8 item 6: the lines above 4 GiB, indentation kept.
b_iomem_hi() {
	sudo -n cat /proc/iomem 2>/dev/null | grep -E '^[[:space:]]*[0-9a-f]{9}-[0-9a-f]{9} :' | sed 's/^/iomemhi /'
}

b_dmesg_mark() {
	sudo -n dmesg | tail -n 1 | sed -n 's/^\[ *\([0-9]*\.[0-9]*\)\].*/\1/p'
}
b_dmesg_since() {
	sudo -n dmesg | awk -v t0="${1:-0}" 'match($0, /^\[ *[0-9]+\.[0-9]+\]/) { t = substr($0, RSTART + 1, RLENGTH - 2) + 0; if (t > t0 + 0) print }'
}

# M3's quiesce (m3-board.sh b_quiesce), four modules (s1-design.md C13).
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

# §6.5 step 3 and C16: the tree kexec_file_load starts from. It edits /chosen
# (bootargs, initrd, seeds) in its own copy at every load, so that copy's hash is
# not readable from user space; the source blob's is (research-kexec-tcu.md:479-480).
b_tree() {
	echo "kexec_tree_source=/sys/firmware/fdt"
	echo "kexec_tree_sha256=$(sudo -n sha256sum /sys/firmware/fdt 2>/dev/null | cut -d' ' -f1)"
	echo "kexec_tree_bytes=$(sudo -n cat /sys/firmware/fdt 2>/dev/null | wc -c)"
}

# §8 item 13, §6.11 and F30: the bootloader slots, read-only.
b_slots() {
	local o rc
	o="$(sudo -n nvbootctrl dump-slots-info 2>&1)"
	rc=$?
	echo "slots_rc=$rc"
	printf '%s\n' "$o" | sed 's/[[:space:]]*$//' | sed 's/^/slots /'
}

# §8 items 5, 7, 8 and 9, read-only.
b_preflight() {
	local s
	echo "release=$(head -n 1 /etc/nv_tegra_release 2>&1)"
	s=$(sudo -n sha256sum /boot/Image 2>/dev/null | cut -d' ' -f1)
	echo "boot_image_sha256=${s:-none}"
	s=$(sudo -n sha256sum /boot/initrd 2>/dev/null | cut -d' ' -f1)
	echo "boot_initrd_sha256=${s:-none}"
	echo "load_kexec=$(grep -E '^[[:space:]]*LOAD_KEXEC=' /etc/default/kexec 2>/dev/null | tail -n 1 | tr -d ' "' | sed 's/^LOAD_KEXEC=//')"
	echo "ramoops_reg=$(od -An -tx1 /proc/device-tree/reserved-memory/ramoops_carveout/reg 2>/dev/null | tr -d ' \n')"
	if [ -r /proc/config.gz ]; then
		zcat /proc/config.gz | grep -E '^(# )?CONFIG_(CMA|CMA_SIZE_MBYTES|ACPI|PANIC_TIMEOUT|INITRAMFS_SOURCE)[= ]' | sed 's/^/kconfig /'
	else
		echo "kconfig none: /proc/config.gz is not readable"
	fi
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

# §6.11: the new dmesg-ramoops records, copied to the home directory for scp.
b_ramoops_fetch() {
	local n f
	for n in $RAMOOPS; do
		case "$n" in dmesg-ramoops-[0-9]*) ;; *) echo "ramoops $n refused"; continue ;; esac
		f="$HOME/$IMG-$UTC-$n.log"
		sudo -n cat "/sys/fs/pstore/$n" > "$f"
		echo "ramoops $n rc=$? bytes=$(stat -c %s "$f") sha256=$(sha256sum "$f" | cut -d' ' -f1)"
	done
}

# §2 rule 5: nothing but staged kimgs stays in the home directory.
b_rmfiles() {
	local f
	for f in $RMFILES; do
		case "$f" in
		*[!A-Za-z0-9._-]*|*.kimg) echo "rm $f refused" ;;
		*) rm -f "$HOME/$f"; echo "rm $f rc=$?" ;;
		esac
	done
}

b_reboot() {
	echo "reboot=issuing"
	sudo -n reboot
	echo "reboot_rc=$?"
}

BOARD_FUNCS="b_sha b_identity b_df b_pstore b_freq b_session b_governor b_iomem b_iomem_hi b_dmesg_mark b_dmesg_since b_quiesce b_accept b_dyndbg b_placement b_tree b_slots b_preflight b_kexec_go b_unload b_after b_ramoops_fetch b_rmfiles b_reboot"

board() {
	local secs="$1"
	shift
	{
		printf 'IMG=%q\nRDIR=%q\nUTC=%q\nKEXEC_MODE=%q\nGOV_PIN=%q\nRAMOOPS=%q\nRMFILES=%q\n' \
			"${IMG:-}" "$RDIR" "${UTC:-}" "${KEXEC_MODE:-s}" 1 "${RAMOOPS:-}" "${RMFILES:-}"
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

# 0 when the COM3 file grew during the last 60 s of the samples taken.
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

# m4-board.sh's: $1 old boot_id, $2 start in epoch seconds, $3 stuck bound (0 off),
# $4 1 to allow the one COM3-growth extension. Sets NEW_BOOT_ID, BACK_S, WAITED_S
# and EXTENDED. Returns 0 back; 3 Linux never went down; 1 the bound passed.
wait_new_boot_id() {
	local old="$1" t0="$2" stuck="${3:-0}" extend="${4:-0}" bound="$RETURN_BOUND" poll="${S1_POLL_S:-10}"
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
		if [ "$extend" = 1 ] && [ -n "${S1_COM3_LOG:-}" ]; then
			sz=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)
			COM3_T+=("$now")
			COM3_S+=("$sz")
		fi
		if (( now - t0 >= bound )); then
			if [ "$extend" = 1 ] && [ "$EXTENDED" = 0 ] && com3_grew_60 "$now" \
				&& [ "$(capture_state "$S1_COM3_LOG")" = running ]; then
				bound=$(( bound + 600 ))
				EXTENDED=1
				rec "run return bound reached while COM3 is still growing and the capture has not ended: extended once by 600 s to $bound s (a slow transfer is not a hang)"
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

# §6.12: the step and host-script mode of each image.
image_step() {
	case "$1" in
	s1-m1b-p6) STEP=B1; MODE=b1 ;;
	s1-h1)     STEP=B2; MODE=host ;;
	s1-n1)     STEP=B3; MODE=boot ;;
	s1-n2)     STEP=B4; MODE=hold ;;
	s1-q2)     STEP=B5; MODE=q2 ;;
	s1-d1)     STEP=d1; MODE=boot ;;
	*) die "image '$1' is not an S1 board image (s1-m1b-p6, s1-h1, s1-n1, s1-n2, s1-q2, s1-d1)" ;;
	esac
}

param() { awk -F= -v k="$1" '$1 == k { print substr($0, length(k) + 2); exit }' "$PARAMS" | tr -d '\r'; }

# Sets KIMG, KIMG_SHA, PARAMS, CAPTURE_S, STEP, MODE and RETURN_BOUND.
resolve_kimg() {
	local want rb pm pr
	[[ "${1:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "image name '${1:-}' is not [A-Za-z0-9._-]+"
	case "$1" in *.kimg) die "give the image name without .kimg" ;; esac
	image_step "$1"
	KIMG="${S1_KIMG_DIR:-$HERE/../shim/out/s1}/$1.kimg"
	PARAMS="${S1_KIMG_DIR:-$HERE/../shim/out/s1}/$1.params"
	[ -f "$KIMG" ] || die "no $1.kimg under S1_KIMG_DIR"
	[ -f "$PARAMS" ] || die "no $1.params beside $1.kimg: build the image with make-s1-images.sh"
	KIMG_SHA="$(sha256sum "$KIMG" | cut -d' ' -f1)"
	if [ -n "${S1_KIMG_SHA256:-}" ] && [ "$KIMG_SHA" != "$S1_KIMG_SHA256" ]; then
		die "$1.kimg sha256 $KIMG_SHA is not S1_KIMG_SHA256"
	fi
	want="$(param kimg_sha256)"
	[ "$want" = "$KIMG_SHA" ] || die "$1.params says kimg_sha256=$want, but $1.kimg is $KIMG_SHA: rebuild, or the params belong to another build"
	pm="$(param mode)"
	[ -z "$pm" ] || [ "$pm" = "$MODE" ] || die "$1.params says mode=$pm, but $1 is step $STEP in mode $MODE"
	pr="$(param rung)"
	[ -z "$pr" ] || [ "$pr" = "$1" ] || die "$1.params says rung=$pr: the params belong to another image"
	rb="$(param return_bound_s)"
	[[ "$rb" =~ ^[0-9]+$ ]] || die "$1.params has no whole-number return_bound_s"
	CAPTURE_S="$(param capture_s)"
	[[ "$CAPTURE_S" =~ ^[0-9]+$ ]] || die "$1.params has no whole-number capture_s"
	RETURN_BOUND="$rb"
	if [ -n "${S1_RETURN_BOUND_S:-}" ]; then
		[[ "$S1_RETURN_BOUND_S" =~ ^[0-9]+$ ]] || die "S1_RETURN_BOUND_S must be a whole number of seconds"
		(( S1_RETURN_BOUND_S >= rb )) || die "S1_RETURN_BOUND_S=$S1_RETURN_BOUND_S is lower than $1.params' return_bound_s=$rb"
		RETURN_BOUND="$S1_RETURN_BOUND_S"
	fi
}

# The capture's remaining life from its header and the PC's clock (m4-design.md §7.2 item 3).
capture_left_s() {
	local head epoch secs
	head="$(head -n 1 "$S1_COM3_LOG" 2>/dev/null | tr -d '\r')"
	case "$head" in "--- raw capture started"*) ;; *) echo "noheader"; return ;; esac
	epoch="$(printf '%s\n' "$head" | sed -n 's/.* epoch=\([0-9][0-9]*\) .*/\1/p')"
	secs="$(printf '%s\n' "$head" | sed -n 's/.* seconds=\([0-9][0-9]*\) .*/\1/p')"
	if [ -z "$epoch" ] || [ -z "$secs" ]; then echo "noepoch"; return; fi
	echo $(( epoch + secs - $(date +%s) ))
}

# Whether the capture in $1 is still running (§2 rule 6a and F25b: a capture that
# is not running is F25b's). capture-com3-raw.ps1 writes its start header, then
# '--- raw capture ended ...' at its deadline or '--- raw capture read error: ...'
# when a read fails; a forced stop writes no footer. It holds the file with
# FileShare.Read, so a write open from here fails while it runs: VERIFIED on this
# PC against a PowerShell FileStream opened the same way (2026-09-14); the open
# writes nothing and leaves size and mtime unchanged. ADVICE_CAPTURE_HELD=yes|no
# replaces that open test (the self-tests' synthetic files are held by nobody).
# Prints one word: running, missing, noheader, ended, expired (the header's
# deadline has passed with no footer) or released (no process holds the file).
capture_state() {
	local f="$1" head epoch secs
	[ -f "$f" ] || { echo missing; return; }
	head="$(head -n 1 "$f" 2>/dev/null | tr -d '\r')"
	case "$head" in "--- raw capture started"*) ;; *) echo noheader; return ;; esac
	if tail -n +2 "$f" | tr -d '\r' | grep -aq -e '^--- raw capture '; then echo ended; return; fi
	epoch="$(printf '%s\n' "$head" | sed -n 's/.* epoch=\([0-9][0-9]*\) .*/\1/p')"
	secs="$(printf '%s\n' "$head" | sed -n 's/.* seconds=\([0-9][0-9]*\) .*/\1/p')"
	if [ -n "$epoch" ] && [ -n "$secs" ] && (( epoch + secs <= $(date +%s) )); then echo expired; return; fi
	case "${ADVICE_CAPTURE_HELD:-}" in
	yes) ;;
	no)  echo released; return ;;
	*)   if ( exec 3>>"$f" ) 2>/dev/null; then echo released; return; fi ;;
	esac
	echo running
}

# 0 when the capture in $1 already holds a record line (parse-s1.py's BB_PREFIXES).
# parse-s1.py reads one run per log with first-match rules, so a capture that
# spans an earlier run would lend that run's L0, L1 and S1 CONFIG lines to this one.
com3_has_records() {
	tr -d '\r' < "$1" | grep -aqE '^[[:space:]]*(S1 |STAMP |BWAIT |T234 |T234-SHIM|t234: )'
}

# A path inside this repository, relative to its top (no user or host name in it),
# for the commands the operator is told to run from the repository root.
repo_rel() {
	local top
	top="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null)" && top="$(cd "$top" 2>/dev/null && pwd)" \
		|| { basename "$1"; return; }
	case "$1" in
	"$top"/*) printf '%s\n' "${1#"$top"/}" ;;
	*)        basename "$1" ;;
	esac
}

# ---------------------------------------------------------------- shared gates

# §6.12: 7,200 s for any kexec run, 1,800 s because every S1 rung quiesces.
# $1 uptime in seconds (decimal), $2 what is refused. Dies at or above either limit.
uptime_gate() {
	if awk -v u="$1" -v m="$MAX_UPTIME_S" 'BEGIN { exit !(u + 0 >= m + 0) }'; then
		die "L4T has been up ${1%.*} s, at or above $MAX_UPTIME_S s: no $2. Run '$PROG reboot' first (§6.12; the limit cannot be overridden, §7.3)"
	fi
	if awk -v u="$1" -v m="$QUIESCE_MAX_UPTIME_S" 'BEGIN { exit !(u + 0 >= m + 0) }'; then
		die "L4T has been up ${1%.*} s, at or above $QUIESCE_MAX_UPTIME_S s, and the $2 quiesces: run '$PROG reboot' first (§6.12; the limit cannot be overridden, §7.3)"
	fi
}

# §6.5 step 4. $1 boot_id, $2 what is refused.
fresh_boot_gate() {
	if boot_used "$1"; then
		die "this L4T boot already served $(grep "^boot_id=$1 " "$RECDIR/used-boot-ids.log" | sed -n 's/.* by=\([a-z0-9]*\) .*/\1/p' | sort -u | tr '\n' ' ')in this record directory: the $2 quiesces only on a freshly booted L4T. Run '$PROG reboot' first (§6.5 step 4)"
	fi
}

# §8 item 13, §6.11, F30. $1 a board output carrying slots_rc= and 'slots ' lines,
# $2 the file for this reading. Sets SLOTS_STATE: first, same, differ or unread.
slots_check() {
	local out="$1" dest="$2" rc body first
	SLOTS_STATE=unread
	rc="$(kv slots_rc "$out")"
	body="$(printf '%s\n' "$out" | sed -n 's/^slots //p')"
	[ "$rc" = 0 ] && [ -n "$body" ] || return 0
	printf '%s\n' "$body" | redact > "$dest"
	check_private "$dest"
	first="$RECDIR/nvbootctrl-first.log"
	if [ ! -f "$first" ]; then
		cp "$dest" "$first"
		check_private "$first"
		SLOTS_STATE=first
	elif cmp -s "$dest" "$first"; then
		SLOTS_STATE=same
	else
		SLOTS_STATE=differ
	fi
}

# Records the reading and its comparison; $1 the command word, $2 the reading file.
slots_report() {
	case "$SLOTS_STATE" in
	first)  rec "$1 nvbootctrl: the session's first reading, kept as nvbootctrl-first.log (§8 item 13)" ;;
	same)   rec "$1 nvbootctrl: equal to the session's first reading" ;;
	differ) rec "$1 F30: nvbootctrl DIFFERS from the session's first reading. STOP ALL BOARD WORK. Follow NVIDIA's A/B documentation; reflash only as the last resort (s1-design.md F30)"
	        diff "$RECDIR/nvbootctrl-first.log" "$2" | head -n 20 | sed 's/^/  /' | rec_pipe ;;
	*)      rec "$1 nvbootctrl: NOT READ (sudo -n nvbootctrl dump-slots-info failed or printed nothing): read it by hand before any rung" ;;
	esac
}

# §8 item 6, from 'iomemhi ' lines on stdin: the window's System RAM line, and every
# entry that starts inside 0x100000000-0x249ffffff other than that line.
#
# The running Linux kernel's own image is not a reservation of that range: KASLR
# places it anywhere in System RAM on each boot, and it is gone once kexec hands
# over (plan checklist 11c: on one of the three boots compared it sat inside the
# candidate). B0 on 2026-09-14 met exactly that: 'Kernel code', a 'reserved' child
# and 'Kernel data' inside the range. Only that shape is excluded: exactly one
# 'Kernel code' and one 'Kernel data' line, both indented alike (children of the
# System RAM line), exactly one entry between them, named 'reserved', at the same
# indent, and the three contiguous (code end + 1 = reserved start, reserved end
# + 1 = data start). Those three lines are reported as iomem_kernel_image and not
# counted; any other entry that starts inside the range, including a looser
# shape, still fails the gate. A no-map firmware carve-out splits the System RAM
# line itself, so it fails the exact top-level match anyway (review, 2026-09-14).
iomem_gate() {
	awk '
	function h(x,   i, v) { v = 0; for (i = 1; i <= length(x); i++) v = v * 16 + index("0123456789abcdef", substr(x, i, 1)) - 1; return v }
	{
		sub(/^iomemhi /, "")
		l = $0
		s = l
		sub(/^[ \t]+/, "", s)
		start = substr(s, 1, 9)
		if (s == "100000000-25e20dfff : System RAM" && l !~ /^[ \t]/) { sys = 1; next }
		if (start >= "100000000" && start <= "249ffffff") {
			m++
			line[m] = s
			ind[m] = length(l) - length(s)
			st[m] = start
			en[m] = substr(s, 11, 9)
			name[m] = s
			sub(/^[^:]*: /, "", name[m])
			if (name[m] == "Kernel code") { kc = m; nkc++ }
			if (name[m] == "Kernel data") { kd = m; nkd++ }
		}
		if (start == "24a000000") print "iomem_at_cma " s
	}
	END {
		kr = 0; nr = 0; img = 0
		if (nkc == 1 && nkd == 1 && st[kc] < st[kd] && ind[kc] > 0 && ind[kc] == ind[kd]) {
			for (i = 1; i <= m; i++)
				if (st[i] > st[kc] && st[i] < st[kd]) { kr = i; nr++ }
			img = (nr == 1 && name[kr] == "reserved" && ind[kr] == ind[kc] \
				&& h(en[kc]) + 1 == h(st[kr]) && h(en[kr]) + 1 == h(st[kd]))
		}
		for (i = 1; i <= m; i++) {
			if (img && (i == kc || i == kr || i == kd)) print "iomem_kernel_image " line[i]
			else { n++; print "iomem_in_range " line[i] }
		}
		printf "iomem_sysram_line=%s iomem_entries_in_range=%d\n", (sys ? "yes" : "no"), n + 0
	}'
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
	local out avail have
	need_host
	need_record_dir
	IMG="$1"
	resolve_kimg "$IMG"
	UTC="$(utc_now)"
	rec_open "$RECDIR/stage-$IMG-$UTC.log"
	rec "stage image=$IMG step=$STEP kimg_bytes=$(stat -c %s "$KIMG") pc_sha256=$KIMG_SHA"
	out="$(board 300 'mkdir -p "$KD"' b_identity b_df b_sha)" || die "board unreachable or its read failed (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	mark_boot "$(kv boot_id "$out")" stage
	have="$(kv board_sha256 "$out")"
	if [ "$have" != "$KIMG_SHA" ]; then
		avail="$(kv df_avail_kb "$out")"
		[ "${avail:-0}" -ge 614400 ] 2>/dev/null || die "the board has ${avail:-?} KB free, under 600 MB"
		copy_kimg || die "transfer failed after 3 attempts; re-running stage resumes a partial copy"
		rec "stage bytes_sent=$SENT"
		have="$(kv board_sha256 "$(board 300 b_sha)")"
	else
		rec "stage already on the board with the PC's sha256; nothing sent"
	fi
	rec "stage board_sha256=$have"
	[ "$have" = "$KIMG_SHA" ] || die "the board's copy differs from the PC's kimg; re-run stage"
	rec "stage PASS: the board's $IMG.kimg equals the PC's. This boot is now used: '$PROG reboot' before any quiesce (§6.5 step 4)"
	check_private "$REC"
	return 0
}

# ---------------------------------------------------------------- P0 (§6.5 steps 2-3, §8)

P0_FAILS=()
p0_gate() {
	local n="$1" r="$2"
	shift 2
	rec "p0 GATE $n $r${*:+: $*}"
	[ "$r" = PASS ] || P0_FAILS+=("$n")
}

cmd_p0() {
	local out have dy line re='Loaded kernel at 0x0*80080000([^0-9a-fA-F]|$)' v g tree slots_file iomem_file
	need_host
	need_record_dir
	IMG="$1"
	resolve_kimg "$IMG"
	UTC="$(utc_now)"
	rec_open "$RECDIR/p0-$IMG-$UTC-board.log"
	rec "p0 utc=$(iso_now) image=$IMG step=$STEP pc_sha256=$KIMG_SHA (no reboot; changes nothing persistent)"
	out="$(board 300 b_sha b_identity)" || die "board unreachable (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	have="$(kv board_sha256 "$out")"
	[ "$have" = "$KIMG_SHA" ] || die "the board has no $IMG.kimg with the PC's sha256; run stage first"
	mark_boot "$(kv boot_id "$out")" p0

	rec "p0 step 1: frequency grid, nvpmodel, thermal zones"
	board 120 'b_freq p0' b_session | rec_pipe

	rec "p0 step 2: s1-design.md §8 items 5, 7, 8 and 9 (read-only)"
	out="$(board 120 b_preflight)"
	printf '%s\n' "$out" | rec_pipe
	v="$(kv release "$out")"
	if printf '%s\n' "$v" | grep -qE 'R36([^0-9]|$).*REVISION: 4[.]7([^0-9]|$)'; then p0_gate item5_release PASS; else p0_gate item5_release FAIL "not R36 REVISION 4.7"; fi
	[ "$(kv boot_image_sha256 "$out")" = "$PIN_BOOT_IMAGE" ] && p0_gate item5_boot_image PASS || p0_gate item5_boot_image FAIL "/boot/Image is not D3's copy"
	[ "$(kv boot_initrd_sha256 "$out")" = "$PIN_BOOT_INITRD" ] && p0_gate item5_boot_initrd PASS || p0_gate item5_boot_initrd FAIL "/boot/initrd is not D3's copy"
	[ "$(kv ramoops_reg "$out")" = "$RAMOOPS_REG_HEX" ] && p0_gate item7_ramoops PASS || p0_gate item7_ramoops FAIL "ramoops_carveout reg is not 0x2_725F_0000, 0x200000"
	[ "$(kv load_kexec "$out")" = false ] && p0_gate item8_load_kexec PASS || p0_gate item8_load_kexec FAIL "/etc/default/kexec is not LOAD_KEXEC=false"

	rec "p0 step 3: §8 item 6, the /proc/iomem lines above 4 GiB"
	out="$(board 120 b_iomem_hi)"
	iomem_file="$RECDIR/p0-iomemhi-$IMG-$UTC.log"
	printf '%s\n' "$out" | sed -n 's/^iomemhi //p' | redact > "$iomem_file"
	g="$(printf '%s\n' "$out" | grep '^iomemhi ' | iomem_gate)"
	printf '%s\n' "$g" | rec_pipe
	if [ "$(kv iomem_sysram_line "$(printf '%s\n' "$g" | tail -n 1 | tr ' ' '\n')")" = yes ] \
		&& [ "$(kv iomem_entries_in_range "$(printf '%s\n' "$g" | tail -n 1 | tr ' ' '\n')")" = 0 ]; then
		p0_gate item6_iomem PASS
	else
		p0_gate item6_iomem FAIL "the window's System RAM line is missing, or an entry starts inside 0x100000000-0x249ffffff: stop"
	fi

	rec "p0 step 4: §8 item 13, sudo -n nvbootctrl dump-slots-info"
	out="$(board 60 b_slots)"
	printf '%s\n' "$out" | rec_pipe
	slots_file="$RECDIR/p0-nvbootctrl-$IMG-$UTC.log"
	slots_check "$out" "$slots_file"
	slots_report p0 "$slots_file"
	case "$SLOTS_STATE" in first|same) p0_gate item13_nvbootctrl PASS ;; *) p0_gate item13_nvbootctrl FAIL "$SLOTS_STATE" ;; esac

	rec "p0 step 5: the kexec tree's sha256 (C16; the input to psci-supported auto)"
	out="$(board 60 b_tree)"
	printf '%s\n' "$out" | rec_pipe
	tree="$(kv kexec_tree_sha256 "$out")"
	if [[ "$tree" =~ ^[0-9a-f]{64}$ ]]; then
		rec "p0 kexec_tree_sha256=$tree"
		p0_gate kexec_tree PASS
	else
		p0_gate kexec_tree FAIL "no sha256 of /sys/firmware/fdt"
	fi

	rec "p0 step 6: lsmod, and the 80000000-ffffffff lines of /proc/iomem"
	out="$(board 120 'lsmod | sed "s/^/lsmod /"' 'b_iomem p0')"
	printf '%s\n' "$out" | grep -v '^iomemline ' | rec_pipe
	printf '%s\n' "$out" | sed -n 's/^iomemline p0 //p' | redact > "$RECDIR/p0-iomem-$IMG-$UTC.log"

	rec "p0 step 7: dynamic debug; kexec -s -l, kexec_loaded, kexec -u, kexec_loaded"
	out="$(board 300 b_dyndbg b_accept)"
	printf '%s\n' "$out" | rec_pipe
	if [ "$(kv accept_load_rc "$out")" = 0 ] && [ "$(kv accept_kexec_loaded "$out")" = 1 ] \
		&& [ "$(kv accept_kexec_loaded_after "$out")" = 0 ]; then
		p0_gate accept PASS "rc=0, then 1, then 0"
	else
		p0_gate accept FAIL "rc=$(kv accept_load_rc "$out") loaded=$(kv accept_kexec_loaded "$out") after=$(kv accept_kexec_loaded_after "$out")"
	fi
	dy="$(kv dyndbg "$out")"
	rec "p0 step 8: the landing line through dynamic debug (§6.5 step 3)"
	if [ "$dy" = yes ]; then
		out="$(board 300 b_placement)"
		printf '%s\n' "$out" | rec_pipe
		line="$(printf '%s\n' "$out" | grep '^placement_line ' | tail -n 1)"
		if [ -z "$line" ]; then
			p0_gate landing FAIL "no 'Loaded kernel at' line appeared: UNKNOWN"
		elif [[ "$line" =~ $re ]]; then
			p0_gate landing PASS "0x80080000"
		else
			p0_gate landing FAIL "NOT 0x80080000, which predicts BAD-LANDING: take K1 (S1_KEXEC=c) first"
		fi
	elif [ "$dy" = no ]; then
		# M3's rule (m3-design §6.3 step 5): the placement read runs only if dynamic
		# debug exists. Without it the landing is checked at run time instead: the
		# shim's line must carry PC=0000000080080000 and BAD-LANDING must not appear
		# (§5.1 L0, §6.6's B1 tokens). B0 on 2026-09-14 found dyndbg=no on this L4T.
		rec "p0 GATE landing SKIPPED: dyndbg=no, so the landing line cannot be read here. Guard: the shim compares its run address with 0x80080000 and on a mismatch prints BAD-LANDING and PSCI-resets before any QNX code (t234-shim.S landing check). B1's tokens and parse-s1.py L0 (B2, B3) also require PC=0000000080080000 and no BAD-LANDING; B4 and B5 report tier_L0 but their verdicts do not gate on it"
	else
		p0_gate landing FAIL "dyndbg=${dy:-unknown}: the dynamic-debug check did not answer"
	fi
	out="$(board 60 'echo "kexec_loaded_at_end=$(cat /sys/kernel/kexec_loaded)"')"
	printf '%s\n' "$out" | rec_pipe
	[ "$(kv kexec_loaded_at_end "$out")" = 0 ] && p0_gate unloaded_at_end PASS || p0_gate unloaded_at_end FAIL "a kexec image is still loaded: run 'sudo -n kexec -u' on the board"

	check_private "$REC" "$RECDIR/p0-iomem-$IMG-$UTC.log" "$iomem_file"
	if [ "${#P0_FAILS[@]}" -eq 0 ]; then
		rec "p0 RESULT PASS for $IMG. Next: '$PROG reboot' before any quiesce (§6.5 step 4)"
		return 0
	fi
	rec "p0 RESULT NOT MET for $IMG: ${P0_FAILS[*]}. Stop (§6.12 B0)"
	[ "$SLOTS_STATE" = differ ] && exit 4
	exit 1
}

# ---------------------------------------------------------------- P1

cmd_p1() {
	local out old rcs oops smmu rc
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
	uptime_gate "$(kv uptime_s "$out")" "quiesce rehearsal"
	fresh_boot_gate "$old" "quiesce rehearsal"
	mark_boot "$old" p1
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
	rec "p1: sudo -n reboot, then wait for a new boot_id"
	board 30 b_reboot | rec_pipe
	wait_new_boot_id "$old" "$(date +%s)" 0 0
	rc=$?
	if [ "$rc" != 0 ]; then
		rec "p1 NO RETURN within $RETURN_BOUND s. Read COM3 and run, from the repository root with S1_COM3_LOG set, '$(repo_rel "$HERE/$PROG") advice $(repo_rel "$REC")': power is cut by the class of the last COM3 line, never by the clock alone (§2 rule 6a)"
		check_private "$REC"
		exit 2
	fi
	rec "p1 back new_boot_id=$NEW_BOOT_ID"
	after_reboot_reads p1
}

# After a reboot's return: identity, pstore and the F30 comparison.
after_reboot_reads() {
	local out f
	out="$(board 60 b_identity b_pstore b_slots)"
	printf '%s\n' "$out" | grep -v '^slots ' | rec_pipe
	f="$RECDIR/$1-nvbootctrl-$UTC.log"
	slots_check "$out" "$f"
	slots_report "$1" "$f"
	check_private "$REC"
	[ "$SLOTS_STATE" = differ ] && exit 4
	return 0
}

# ---------------------------------------------------------------- reboot

cmd_reboot() {
	local out old rc
	need_host
	need_record_dir
	IMG=""
	UTC="$(utc_now)"
	rec_open "$RECDIR/reboot-$UTC-board.log"
	out="$(board 60 b_identity)" || die "board unreachable (rc=$?)"
	printf '%s\n' "$out" | rec_pipe
	old="$(kv boot_id "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	board 30 b_reboot | rec_pipe
	wait_new_boot_id "$old" "$(date +%s)" 0 0
	rc=$?
	if [ "$rc" != 0 ]; then
		rec "reboot NO RETURN within $RETURN_BOUND s. Read COM3 and run, from the repository root with S1_COM3_LOG set, '$(repo_rel "$HERE/$PROG") advice $(repo_rel "$REC")': power is cut by the class of the last COM3 line, never by the clock alone (§2 rule 6a)"
		check_private "$REC"
		exit 2
	fi
	rec "reboot back new_boot_id=$NEW_BOOT_ID: a fresh L4T for the next quiesce"
	after_reboot_reads reboot
}

# ---------------------------------------------------------------- run (§6.6-§6.11)

# §2 rule 10 and §5.3: an attempt refused before the board changed (die, or F30 before
# the quiesce) gives its step's name back, so the design's <rec>/<step>/ holds the
# first real run. Its records move to <step>-refused-<utc>; none is removed.
run_refused_move() {
	local to
	ON_DIE=""
	[ -n "${SD:-}" ] && [ -d "$SD" ] || return 0
	to="$RECDIR/$(basename "$SD")-refused-$UTC"
	if mv "$SD" "$to" 2>/dev/null; then
		REC="$to/$(basename "$REC")"
		note "nothing was changed on the board: this attempt's records moved to $(basename "$to"), and $(basename "$SD") stays free for the real run"
	else
		note "WARNING: could not move $(basename "$SD") to $(basename "$to"); the next run of the step would take $(basename "$SD")-a2"
	fi
}

cmd_run() {
	local out old up rc wrc pstore_before pstore_after newrec shim reason lsha rcs oops gok gov0 gov4 stuck left
	local bb com3 SD base tree tree_now attempt com3_off names n f want got rmfiles verdict slots_state_post
	local conf="$S1DIR/s1-linux.conf" pargs conf_gate cstate
	local pc_image="$S1DIR/out/l4t/Image" pc_l4t_initrd="$S1DIR/out/l4t/initrd" pc_initrd="$S1DIR/out/initrd.cpio.gz"
	local pc_conf_sha="" pc_image_sha="" pc_l4t_initrd_sha="" pc_initrd_sha=""
	need_host
	need_record_dir
	IMG="$1"
	resolve_kimg "$IMG"
	stuck="${S1_STUCK_S:-600}"
	[[ "$stuck" =~ ^[0-9]+$ ]] || die "S1_STUCK_S must be a whole number of seconds (0 turns the early stop off)"
	KEXEC_MODE="${S1_KEXEC:-s}"
	case "$KEXEC_MODE" in s|c) ;; *) die "S1_KEXEC must be s, or c for contingency K1" ;; esac
	if [ -z "${S1_COM3_LOG:-}" ] || [ ! -f "$S1_COM3_LOG" ]; then
		die "S1_COM3_LOG must name the running capture-com3-raw.ps1 file: COM3 is a mandatory co-record (§6.11)"
	fi
	case "$MODE" in
	boot|hold|q2)
		[[ "${S1_REF_CONF_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] \
			|| die "S1_REF_CONF_SHA256 must be T2's conf_sha256 (64 lowercase hex): $STEP needs --ref-conf-sha256 (§5.2 item 2)" ;;
	esac
	tree=""
	if [ "$MODE" != b1 ]; then
		if [ -n "${S1_KEXEC_TREE_SHA256:-}" ]; then
			tree="$S1_KEXEC_TREE_SHA256"
		else
			for f in "$RECDIR"/p0-"$IMG"-*-board.log; do
				[ -f "$f" ] || continue
				got="$(sed -n 's/^p0 kexec_tree_sha256=\([0-9a-f]\{64\}\)$/\1/p' "$f" | tail -n 1)"
				[ -n "$got" ] && tree="$got"    # the glob sorts by UTC: the newest p0 wins
			done
		fi
		[[ "$tree" =~ ^[0-9a-f]{64}$ ]] \
			|| die "no kexec tree sha256: run '$PROG p0 $IMG' in this record directory, or set S1_KEXEC_TREE_SHA256 to p0's reading (§6.5 step 3, §5.2 item 5)"
		find_python || die "no working python 3.8+ for the parser (§6.11)"
		[ -f "$conf" ] || die "no orin-native/s1/s1-linux.conf for the parser"
		# §8 PC item 2, §5.2 items 2 and 5: the PC's inputs, before any board round, so a
		# configuration or payload mismatch is found here and not after the kexec.
		pc_conf_sha="$(sha256sum "$conf" | cut -d' ' -f1)"
		[ "$pc_conf_sha" = "$PIN_CONF" ] \
			|| die "orin-native/s1/s1-linux.conf sha256 $pc_conf_sha is not T2's $PIN_CONF (§8 PC item 2)"
		conf_gate="$(timeout 120 "$PY_BIN" "$PARSER" conf "$conf" 2>&1)" \
			|| die "'parse-s1.py conf' refuses orin-native/s1/s1-linux.conf (§8 PC item 2): $(printf '%s\n' "$conf_gate" | grep -a '^S1CONF gate=' | head -n 1)"
		case "$MODE" in
		boot|hold|q2)
			[ "$S1_REF_CONF_SHA256" = "$pc_conf_sha" ] \
				|| die "S1_REF_CONF_SHA256 is not s1-linux.conf's sha256 $pc_conf_sha: the run must carry T2's configuration (§8 PC item 2)"
			[ -f "$pc_image" ] || die "no orin-native/s1/out/l4t/Image: the parser's board-versus-PC comparison needs it (§5.2 item 2)"
			[ -f "$pc_l4t_initrd" ] || die "no orin-native/s1/out/l4t/initrd, D3's copy (§8 PC item 2)"
			[ -f "$pc_initrd" ] || die "no orin-native/s1/out/initrd.cpio.gz: the parser's board-versus-PC comparison needs it (§5.2 item 2)"
			pc_image_sha="$(sha256sum "$pc_image" | cut -d' ' -f1)"
			pc_l4t_initrd_sha="$(sha256sum "$pc_l4t_initrd" | cut -d' ' -f1)"
			pc_initrd_sha="$(sha256sum "$pc_initrd" | cut -d' ' -f1)"
			[ "$pc_image_sha" = "$PIN_BOOT_IMAGE" ] || die "orin-native/s1/out/l4t/Image sha256 $pc_image_sha is not D3's $PIN_BOOT_IMAGE (§8 PC item 2)"
			[ "$pc_l4t_initrd_sha" = "$PIN_BOOT_INITRD" ] || die "orin-native/s1/out/l4t/initrd sha256 $pc_l4t_initrd_sha is not D3's $PIN_BOOT_INITRD (§8 PC item 2)"
			[ "$pc_initrd_sha" = "$PIN_PC_INITRD_CPIO" ] \
				|| die "orin-native/s1/out/initrd.cpio.gz sha256 $pc_initrd_sha is not initrd.manifest's $PIN_PC_INITRD_CPIO: rebuild it with mkcpio.py"
			;;
		esac
	fi

	# Gate A (m4-design.md §7.2 item 3): before any board session.
	left="$(capture_left_s)"
	case "$left" in
	noheader) die "S1_COM3_LOG does not begin with '--- raw capture started': start capture-com3-raw.ps1 from PowerShell (-Seconds $CAPTURE_S)" ;;
	noepoch)  die "S1_COM3_LOG's header has no epoch= and seconds=: start capture-com3-raw.ps1 from PowerShell (-Seconds $CAPTURE_S)" ;;
	esac
	(( left >= RETURN_BOUND + 2180 )) \
		|| die "gate A: the COM3 capture has $left s left, under return_bound_s + 2180 = $(( RETURN_BOUND + 2180 )) s: start a fresh capture with -Seconds $CAPTURE_S"
	cstate="$(capture_state "$S1_COM3_LOG")"
	[ "$cstate" = running ] \
		|| die "gate A: the COM3 capture is $cstate, not running: start a fresh capture from PowerShell (-Seconds $CAPTURE_S)"
	if com3_has_records "$S1_COM3_LOG"; then
		die "gate A: S1_COM3_LOG already holds record lines from an earlier run, and parse-s1.py reads one run per log: start a fresh capture for each run (-Seconds $CAPTURE_S, a new -Out file)"
	fi

	# §2 rule 10: <rec>/<step>/, and a later attempt of the step never replaces it (§5.3).
	SD="$RECDIR/$STEP"
	attempt=1
	while [ -d "$SD" ] && [ -n "$(ls -A "$SD" 2>/dev/null)" ]; do
		attempt=$(( attempt + 1 ))
		SD="$RECDIR/$STEP-a$attempt"
	done
	mkdir -p "$SD" || die "cannot create $(basename "$SD")"
	UTC="$(utc_now)"
	base="$SD/$IMG-$UTC"
	rec_open "$base-board.log"
	ON_DIE=run_refused_move
	if [ "$KEXEC_MODE" = s ]; then
		rec "run image=$IMG step=$STEP mode=$MODE attempt=$attempt utc=$UTC kexec_syscall=kexec_file_load (-s)"
	else
		rec "run image=$IMG step=$STEP mode=$MODE attempt=$attempt utc=$UTC kexec_syscall=kexec_load (-c -l ... -i, contingency K1)"
	fi
	rec "run record_dir=$(basename "$RECDIR")/$(basename "$SD")"
	rec "run kimg=$IMG.kimg bytes=$(stat -c %s "$KIMG") pc_sha256=$KIMG_SHA params=$(basename "$PARAMS") params_sha256=$(sha256sum "$PARAMS" | cut -d' ' -f1)"
	cp "$PARAMS" "$base-params.log" || die "cannot copy $PARAMS into the record directory"
	check_private "$base-params.log"
	rec "run params_copy=$(basename "$base-params.log")"
	rec "run com3_log=$(basename "$S1_COM3_LOG") capture_left_s=$left return_bound_s=$RETURN_BOUND quiesce=1 governor_pin=1 (fixed: D6, §6.6)"
	[ "$MODE" != b1 ] && rec "run kexec_tree_sha256=$tree (p0's reading, for the parser)"
	[ "$MODE" != b1 ] && rec "run pc_inputs conf_sha256=$pc_conf_sha conf_gate=pass${pc_image_sha:+ image_sha256=$pc_image_sha l4t_initrd_sha256=$pc_l4t_initrd_sha initrd_cpio_sha256=$pc_initrd_sha ref_conf_sha256=equal} (§8 PC item 2, §5.2 item 5)"

	# step 2: the kimg, identity, the uptime and fresh-boot rules, pstore, slots, tree
	out="$(board 300 b_sha b_identity b_pstore b_slots b_tree)" || die "board unreachable (rc=$?); nothing was changed on the board"
	printf '%s\n' "$out" | rec_pipe
	[ "$(kv board_sha256 "$out")" = "$KIMG_SHA" ] || die "the board's $IMG.kimg differs from the PC's: run stage"
	old="$(kv boot_id "$out")"
	up="$(kv uptime_s "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	uptime_gate "$up" "kexec run"
	fresh_boot_gate "$old" "run"
	pstore_before="$(printf '%s\n' "$out" | grep '^pstore ')"
	slots_check "$out" "$base-nvbootctrl-pre.log"
	slots_report run "$base-nvbootctrl-pre.log"
	case "$SLOTS_STATE" in
	differ) rec "run no quiesce and no kexec: L4T is still running"; check_private "$REC"; run_refused_move; exit 4 ;;
	unread) die "nvbootctrl could not be read before the rung: it is read before every rung and after every return (§8 item 13)" ;;
	esac
	tree_now="$(kv kexec_tree_sha256 "$out")"
	if [ "$MODE" != b1 ]; then
		if [ "$tree_now" = "$tree" ]; then
			rec "run kexec tree now equals p0's reading"
		else
			rec "run kexec tree now ${tree_now:-unread} DIFFERS from p0's reading: recorded; the parser gets p0's (parse-s1.py's contract)"
		fi
	fi

	# From here the board changes: this boot is used (§6.5 step 4).
	mark_boot "$old" run
	ON_DIE=""

	# step 3: the governor pin (always)
	out="$(board 60 b_governor)"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	gok="$(printf '%s\n' "$out" | grep -cE '^governor policy[04] performance rc=0$')"
	if [ "$rc" != 0 ] || [ "$gok" != 2 ]; then
		rec "run GOVERNOR PIN FAILED (session rc=$rc, governor_ok=$gok/2): no quiesce and no kexec. L4T is still running; reboot it before another attempt"
		check_private "$REC"
		exit 3
	fi
	out="$(board 120 'b_freq pre' b_session)"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	gov0="$(kv 'freq pre policy0 scaling_governor' "$out")"
	gov4="$(kv 'freq pre policy4 scaling_governor' "$out")"
	if [ "$rc" != 0 ] || [ "$gov0" != performance ] || [ "$gov4" != performance ]; then
		rec "run GOVERNOR NOT PINNED or frequency read failed (session rc=$rc policy0=$gov0 policy4=$gov4): no quiesce and no kexec. L4T is still running; reboot it before another attempt"
		check_private "$REC"
		exit 3
	fi
	rec "run step 3 governor read back: policy0=$gov0 policy4=$gov4"

	# step 4: the quiesce (always; four modules)
	out="$(board 500 b_quiesce 'b_iomem run')"
	printf '%s\n' "$out" | grep -v '^iomemline ' | rec_pipe
	printf '%s\n' "$out" | sed -n 's/^iomemline run //p' | redact > "$base-iomem-postrmmod.log"
	rcs="$(printf '%s\n' "$out" | grep -c '^rmmod [a-z_]* rc=0$')"
	oops="$(kv quiesce_oops_lines "$out")"
	if [ "$rcs" != 4 ] || [ "${oops:-x}" != 0 ]; then
		rec "run QUIESCE FAILED (rmmod_ok=$rcs/4 oops_lines=${oops:-?}): no kexec. The board is part-quiesced: '$PROG reboot' before another attempt"
		check_private "$REC" "$base-iomem-postrmmod.log"
		exit 3
	fi

	# Gate B: just before the kexec session.
	left="$(capture_left_s)"
	if ! [[ "$left" =~ ^-?[0-9]+$ ]] || (( left < RETURN_BOUND + 1200 )); then
		rec "run GATE B: the COM3 capture has $left s left, under return_bound_s + 1200 = $(( RETURN_BOUND + 1200 )) s: no kexec. The board is quiesced: '$PROG reboot', start a fresh capture (-Seconds $CAPTURE_S), then run again"
		check_private "$REC" "$base-iomem-postrmmod.log"
		exit 3
	fi
	cstate="$(capture_state "$S1_COM3_LOG")"
	if [ "$cstate" != running ] || com3_has_records "$S1_COM3_LOG"; then
		rec "run GATE B: the COM3 capture is $cstate$(com3_has_records "$S1_COM3_LOG" && printf ' and holds record lines of an earlier run'): no kexec. The board is quiesced: '$PROG reboot', start a fresh capture (-Seconds $CAPTURE_S, a new -Out file), then run again"
		check_private "$REC" "$base-iomem-postrmmod.log"
		exit 3
	fi
	rec "run gate B: capture_left_s=$left capture=running earlier_records=none: ok"
	com3_off=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)
	rec "run com3_bytes_before_kexec=$com3_off"

	# step 5
	rec "run step 5: kexec load, kexec_loaded, the last governor check and frequency read, systemctl kexec"
	out="$(board 300 b_kexec_go)"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	if [ -n "$(kv governor_final_fail "$out")" ]; then
		rec "run GOVERNOR REVERTED before kexec: the image was unloaded, no kexec. L4T is still running; reboot it before another attempt"
		check_private "$REC"
		exit 3
	fi
	if [ "$(kv kexec_loaded "$out")" != 1 ]; then
		rec "run kexec NOT issued (rc=$rc): L4T is still running; reboot it before another attempt"
		check_private "$REC"
		exit 3
	fi
	if [ -n "$(kv systemctl_kexec_rc "$out")" ] && [ "$(kv systemctl_kexec_rc "$out")" != 0 ]; then
		board 60 b_unload | rec_pipe
		rec "run systemctl kexec FAILED: the image was unloaded and L4T is still running; reboot it before another attempt"
		check_private "$REC"
		exit 3
	fi
	rec "run kexec issued; the session ended with rc=$rc (255 is expected when Linux drops it)"

	# step 6: the return bound from IMG.params, with the one COM3-growth extension
	wait_new_boot_id "$old" "$(date +%s)" "$stuck" 1
	wrc=$?
	rec "run com3_bytes_at_return=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0) extended=$EXTENDED"
	case "$wrc" in
	0)
		rec "run back new_boot_id=$NEW_BOOT_ID"
		;;
	3)
		rec "run the old boot_id answered every poll for $WAITED_S s after the kexec session (S1_STUCK_S=$stuck): Linux never went down. Keep the capture running and check /sys/kernel/kexec_loaded by hand"
		check_private "$REC"
		exit 3
		;;
	*)
		rec "run NO RETURN within $RETURN_BOUND s (extended=$EXTENDED). The black box of this run is lost if power is cut. Power-cut advice by the COM3 class (§2 rule 6a), never by the clock alone:"
		com3_advice "$S1_COM3_LOG" "$com3_off" 0 passed | rec_pipe
		rec "run: from the repository root, with S1_COM3_LOG set, re-run '$(repo_rel "$HERE/$PROG") advice $(repo_rel "$REC")' until the advice says a cut is allowed, or L4T answers"
		check_private "$REC"
		exit 2
		;;
	esac

	# step 7 (§6.11): black box, reset_reason, pstore, nvbootctrl
	out="$(board 120 b_after b_slots)" || rec "run warning: the return read ended with rc=$?"
	printf '%s\n' "$out" | rec_pipe
	pstore_after="$(printf '%s\n' "$out" | grep '^pstore ')"
	newrec="$(comm -13 <(printf '%s\n' "$pstore_before" | sort) <(printf '%s\n' "$pstore_after" | sort) | grep '^pstore dmesg-ramoops' || true)"
	if [ -n "$newrec" ]; then
		rec "run NEW dmesg-ramoops records (F27):"
		printf '%s\n' "$newrec" | rec_pipe
	else
		rec "run new_dmesg_ramoops=none"
	fi
	shim="$(kv blackbox_shim_lines "$out")"
	reason="$(kv reset_reason "$out")"
	rec "run reset_reason=$reason (MAINSWRST: the image's own reset; BCCPLEXWDT: the watchdog)"
	if [ "${shim:-0}" = 0 ]; then
		if [ -n "$newrec" ]; then
			rec "run VALIDITY: no T234-SHIM and a new dmesg-ramoops record: Linux died before the jump. Retry from a fresh L4T on the same image (§5.3 Retries); do not judge the image"
		else
			rec "run VALIDITY: no T234-SHIM in the black box: this run never reached the shim"
		fi
	fi
	slots_check "$out" "$base-nvbootctrl-post.log"
	slots_report run "$base-nvbootctrl-post.log"
	slots_state_post="$SLOTS_STATE"

	# step 8: raw copies first; the board's copies are then removed (§2 rule 5)
	rmfiles=""
	bb="$base-blackbox.log"
	if timeout 300 scp "${ssh_work[@]}" "$ORIN_HOST:$IMG-$UTC-blackbox.log" "$bb" </dev/null; then
		lsha="$(sha256sum "$bb" | cut -d' ' -f1)"
		if [ "$lsha" = "$(kv blackbox_sha256 "$out")" ]; then
			rec "run black box copied: $(basename "$bb") bytes=$(stat -c %s "$bb") sha256=$lsha, equal to the board's"
			rmfiles="$IMG-$UTC-blackbox.log"
		else
			rec "run black box copy sha256 $lsha DIFFERS from the board's: the board keeps $IMG-$UTC-blackbox.log"
		fi
	else
		rec "run black box copy FAILED: it stays on the board as $IMG-$UTC-blackbox.log"
		bb=""
	fi
	names="$(printf '%s\n' "$newrec" | awk 'NF >= 2 { print $2 }' | grep -E '^dmesg-ramoops-[0-9]+$' | tr '\n' ' ')"
	RAMOOPS_FILES=()
	if [ -n "$names" ]; then
		out="$(RAMOOPS="$names" board 60 b_ramoops_fetch)"
		printf '%s\n' "$out" | rec_pipe
		for n in $names; do
			f="$base-$n.log"
			want="$(printf '%s\n' "$out" | awk -v n="$n" '$1 == "ramoops" && $2 == n { for (i = 3; i <= NF; i++) if ($i ~ /^sha256=/) print substr($i, 8) }')"
			if timeout 120 scp "${ssh_work[@]}" "$ORIN_HOST:$IMG-$UTC-$n.log" "$f" </dev/null; then
				got="$(sha256sum "$f" | cut -d' ' -f1)"
				if [ -n "$want" ] && [ "$got" = "$want" ]; then
					rec "run $n copied: $(basename "$f") sha256=$got, equal to the board's"
					rmfiles="$rmfiles $IMG-$UTC-$n.log"
				else
					rec "run $n copy sha256 $got differs from the board's (${want:-unread}): the board keeps it"
				fi
				RAMOOPS_FILES+=("$f")
			else
				rec "run $n copy FAILED: it stays on the board as $IMG-$UTC-$n.log"
			fi
		done
	fi
	if [ -n "$rmfiles" ]; then
		RMFILES="$rmfiles" board 60 b_rmfiles | rec_pipe
	fi
	com3="$base-com3.log"
	if cp "$S1_COM3_LOG" "$com3" 2>/dev/null; then
		rec "run COM3 copied: $(basename "$com3") bytes=$(stat -c %s "$com3") raw_sha256=$(sha256sum "$com3" | cut -d' ' -f1); L4T is back: stop the capture after this command returns"
	else
		rec "run COM3 copy FAILED (the capture may hold the file): stop the capture, then copy it as $(basename "$com3")"
		com3=""
	fi

	# step 8b: the verdict. parse-s1.py has no B1 step: B1 has its own tokens (§6.6).
	if [ "$MODE" = b1 ]; then
		rec "run parser not applicable: B1 runs no S1 host script (§6.6). B1's tokens:"
		if [ -n "$com3" ]; then
			b1_tokens "$com3" "${bb:-}" "$reason" "$slots_state_post" | rec_pipe
		else
			rec "run B1 tokens NOT read: no COM3 copy"
		fi
		rec "run B1: the normalised black box against M1b R2's is '$PROG b1-compare $(basename "${bb:-<bb>}") <M1b R2 black box>' (§6.6)"
	elif [ -n "$com3" ]; then
		pargs=(run "$com3" --profile board --mode "$MODE" --out-dir "$SD" --conf "$conf" --kexec-tree-sha256 "$tree")
		[ -n "$bb" ] && pargs+=(--blackbox "$bb")
		[ -n "$reason" ] && pargs+=(--reset-reason "$reason")
		case "$MODE" in
		boot|hold|q2)
			pargs+=(--ref-conf-sha256 "$S1_REF_CONF_SHA256")
			pargs+=(--image "$pc_image" --initrd "$pc_initrd")    # both checked against their pins before the round
			;;
		esac
		verdict="$(timeout 900 "$PY_BIN" "$PARSER" "${pargs[@]}" 2>&1)"
		rc=$?
		printf '%s\n' "$verdict" | grep -E '^(S1PC |parse-s1: )' | rec_pipe
		rec "run parser rc=$rc (0 a verdict, 3 refused for missing item-5 stamps; its record: $(basename "$SD")/parse-s1.txt)"
	else
		rec "run parser NOT run: no COM3 copy"
	fi

	# only then the privacy scan, whose redaction could change a body's bytes
	[ -n "$bb" ] && privacy_scan "$bb"
	[ -n "$com3" ] && privacy_scan "$com3"
	for f in "${RAMOOPS_FILES[@]}"; do privacy_scan "$f"; done
	if [ -n "$bb" ]; then
		extract_file "$bb" | rec_pipe
		[ -n "$com3" ] && consistency_files "$bb" "$com3" | rec_pipe
	fi
	rec "run done. Record: $(basename "$SD")/$(basename "$REC"). The verdict is the parser's S1PC verdict line above (B1: the tokens and b1-compare)"
	check_private "$REC" "$bb" "$com3" "$base-iomem-postrmmod.log" "$base-nvbootctrl-pre.log" "$base-nvbootctrl-post.log" \
		"$SD/parse-s1.txt" "$SD/s1-fdt.dtb" "${RAMOOPS_FILES[@]}"
	if [ "$slots_state_post" = differ ]; then
		rec "run F30: STOP ALL BOARD WORK (exit 4)"
		exit 4
	fi
	[ "$slots_state_post" = unread ] && rec "run nvbootctrl was not read after the return: read it by hand before any next rung"
	return 0
}

# ---------------------------------------------------------------- extraction (no duration, no FreeMem: §2 rule 8)

NEG_TOKENS=(
	'BAD-LANDING' 'EXC ' 'EL!=2' 'overlaps' 't234: -b' 'BWAIT guard deadline' 'STAMP exec-failed' 'STAMP read-error'
	'STAMP l_panic' 'STAMP l_rbfail' 'Kernel panic' 'Reboot failed' 'verify=bad' 'verify=timeout' 'refuse=' 'map=fail'
	'reflected=no' 'sysram_w1=no' 'sysram_w2=no' 'canary_in_sysram=yes' 'gpu_in_sysram=yes' 'saved=no'
	'Unable to start' 'Could not load library' 'killed=1' 'Shutdown[' 't234: EL1' 't234: EL2' 'entered at EL1'
	'ASSERT' 'start failure' 'start timeout' 'wake timeout' 'not awake' 'hvtimer STOP' 'CENSUS FAIL' 'RESULT FAIL'
)
NEG_PATTERNS=(
	'S1 FAIL([^_]|$)' 'S1 FAIL_STATE [^n]' 'logger_errors=[1-9]' 'S1 HB k=[0-9]+ qvm=[^a]' 'S1 HB k=[0-9]+ .*rc=[^a]'
	'S1 HOLD end qvm=[^a]' 'S1 DRYRUN rc=[^0]' '^[[:space:]]*\[[^]]+:[0-9]+] '
)

# Durations, clock counts and FreeMem values are masked in everything extracted.
mask_figures() {
	sed -E 's/(^| )(ms|cycles|cps|mono_ns|samples)=[0-9]+/\1\2=<masked>/g; s/^(S1 MEM [^ ]+) [^ ]+/\1 <masked>/'
}

extract_file() {
	local f="$1" t tok n bytes pat
	t="$(mktemp)"
	tr -d '\r' < "$f" > "$t"
	bytes=$(stat -c %s "$f")
	echo "extract file=$(basename "$f") bytes=$bytes sha256=$(sha256sum "$f" | cut -d' ' -f1)"
	if [ "$bytes" -ge 65500 ]; then
		echo "extract size: the 65,520 B cap was hit, head only; the full streams are on COM3 (§3.4)"
	elif [ "$bytes" -ge 60000 ]; then
		echo "extract size: at or above 60,000 B, M3's rebuild-at--vv rule (§3.4, R22)"
	else
		echo "extract size: under 60,000 B (§3.4, R22)"
	fi
	echo "extract lines:"
	grep -aE '^[[:space:]]*(T234-SHIM|T234 (S1|m1b)|Enabling EL2 host|t234: (WDT0|ram w2|gpu range|canary|-b|all [0-9]+ cpus parked|cpu [0-9]+ el2-host|hvtimer cpu)|BWAIT (guard|run |path hit=)|S1 (CONFIG|MEM|GATE|W2|ASINFO|CANARY|CHECK|STATE|DRYRUN|HOLD|ALLOC|HB|GUESTRAM|BOTH|FAIL_STATE|FAIL|QVM|BEGIN|END)|tcu-cat:|rc=|samples=)' "$t" \
		| sed 's/^[[:space:]]*//' | mask_figures | sed 's/^/  /'
	echo "extract stamps (the first line of each label):"
	awk '$1 == "STAMP" && !($2 in seen) { seen[$2] = 1; print }' "$t" | mask_figures | sed 's/^/  /'
	echo "extract negative tokens:"
	for pat in "${NEG_PATTERNS[@]}"; do
		n=$(grep -acE -- "$pat" "$t")
		[ "$n" = 0 ] || echo "  '$pat' x$n"
	done
	for tok in "${NEG_TOKENS[@]}"; do
		n=$(grep -acF -- "$tok" "$t")
		[ "$n" = 0 ] || echo "  '$tok' x$n"
	done
	echo "extract negative tokens end"
	rm -f "$t"
}

# parse-s1.py's rule (BB_PREFIXES, is_subsequence): the black box's record lines,
# CR removed and blanks trimmed, appear in COM3's in order. COM3 holds more: the
# full streams tcu-cat sends and the export bodies never enter the black box.
consistency_files() {
	awk -v P='^(S1 |STAMP |BWAIT |T234 |T234-SHIM|t234: )' '
	FILENAME != cur { cur = FILENAME; fi++ }
	{
		gsub(/\r/, "")
		sub(/[ \t]+$/, "")
		s = $0
		sub(/^[ \t]+/, "", s)
		if (s !~ P) next
	}
	fi == 1 { bb[++nb] = s; next }
	fi == 2 { nc++; if (k < nb && s == bb[k + 1]) k++ }
	END {
		printf "consistency blackbox_records=%d com3_records=%d (record lines, CR-stripped, in order)\n", nb, nc
		if (nb == 0) print "consistency NO RECORDS in the black box"
		else if (k == nb) print "consistency the black box is a subsequence of COM3: consistent"
		else printf "consistency DIFFER first_missing_record=%d: %s\n", k + 1, bb[k + 1]
	}' "$1" "$2" | mask_figures
}

# §6.6: B1's tokens. $1 COM3 copy, $2 black box copy (or empty), $3 reset_reason, $4 SLOTS_STATE.
b1_tokens() {
	local c="$1" b="$2" reason="$3" slots="$4" t tb fails=0 tok ri banner=no x
	t="$(mktemp)"
	tr -d '\r' < "$c" > "$t"
	for tok in 'T234-SHIM EL=2' 'PC=0000000080080000' 't234: WDT0 CR=' 'T234 M1b -P6: procnto up' \
		'T234 M1b -P6: resetting so the log can be recovered'; do
		if grep -aqF -- "$tok" "$t"; then echo "B1 com3 present '$tok': ok"; else echo "B1 com3 present '$tok': MISSING"; fails=$(( fails + 1 )); fi
	done
	for tok in 't234: ram w2' 't234: gpu range' 't234: canary' 'BAD-LANDING' 'EXC ' 'EL!=2'; do
		if grep -aqF -- "$tok" "$t"; then echo "B1 com3 absent '$tok': PRESENT"; fails=$(( fails + 1 )); else echo "B1 com3 absent '$tok': ok"; fi
	done
	ri="$(grep -anF 'T234 M1b -P6: resetting so the log can be recovered' "$t" | head -n 1 | cut -d: -f1)"
	if [ -n "$ri" ]; then
		for x in "${FW_BANNER[@]}"; do tail -n +"$(( ri + 1 ))" "$t" | grep -aqF -- "$x" && banner=yes; done
	fi
	if [ "$banner" = yes ]; then echo "B1 firmware banner after the reset: ok"; else echo "B1 firmware banner after the reset: MISSING"; fails=$(( fails + 1 )); fi
	if [ -n "$b" ] && [ -f "$b" ]; then
		tb="$(mktemp)"
		tr -d '\r' < "$b" > "$tb"
		for tok in 'T234-SHIM EL=2' 'T234 M1b -P6: procnto up'; do
			if grep -aqF -- "$tok" "$tb"; then echo "B1 blackbox present '$tok': ok"; else echo "B1 blackbox present '$tok': MISSING"; fails=$(( fails + 1 )); fi
		done
		for tok in 't234: ram w2' 't234: gpu range' 't234: canary' 'BAD-LANDING' 'EXC ' 'EL!=2'; do
			if grep -aqF -- "$tok" "$tb"; then echo "B1 blackbox absent '$tok': PRESENT"; fails=$(( fails + 1 )); fi
		done
		rm -f "$tb"
	else
		echo "B1 black box: NOT GIVEN"
		fails=$(( fails + 1 ))
	fi
	case "$reason" in *MAINSWRST*) echo "B1 reset_reason MAINSWRST: ok" ;; *) echo "B1 reset_reason '$reason': NOT MAINSWRST"; fails=$(( fails + 1 )) ;; esac
	case "$slots" in same|first) echo "B1 bootloader slot unchanged: ok" ;; *) echo "B1 bootloader slot: $slots"; fails=$(( fails + 1 )) ;; esac
	rm -f "$t"
	if [ "$fails" = 0 ]; then echo "B1 RESULT tokens met (§6.6); the black-box comparison is b1-compare's"; else echo "B1 RESULT tokens NOT MET ($fails): stop, revise the startup change (§5.3)"; fi
}

# §6.6: B1's black box against M1b R2's, with addresses and hex words masked.
# The pass judgement ("apart from startup-size-dependent addresses") is the run note's.
# Trailing blanks and blank lines go too: B1's only R2 reference is a curated
# COM3 capture, which carries both where a black box has neither.
b1_normalise() {
	tr -d '\r' < "$1" | sed -E 's/[[:space:]]+$//; /^$/d' | mask_figures \
		| sed -E 's/0x[0-9a-fA-F]+/0x<n>/g; s/(^|[^0-9A-Za-z_])[0-9a-fA-F]{8,}([^0-9A-Za-z_]|$)/\1<hex>\2/g'
}

cmd_b1_compare() {
	local a b
	a="$(mktemp)"
	b="$(mktemp)"
	b1_normalise "$1" > "$a"
	b1_normalise "$2" > "$b"
	echo "b1-compare run=$(basename "$1") sha256=$(sha256sum "$1" | cut -d' ' -f1) reference=$(basename "$2") sha256=$(sha256sum "$2" | cut -d' ' -f1)"
	if cmp -s "$a" "$b"; then
		echo "b1-compare identical after masking 0x values and hex words of 8 or more digits"
	else
		echo "b1-compare DIFFER after masking (first 60 diff lines; the run note judges whether only startup-size-dependent addresses differ):"
		diff "$b" "$a" | head -n 60 | sed 's/^/  /'
	fi
	rm -f "$a" "$b"
}

# ---------------------------------------------------------------- power-cut advice (§2 rule 6a)
#
# Never a cut on the clock alone, and never before the return bound has passed
# (F25a and F25b both begin 'not back by the return bound'): the class comes from
# what COM3 shows after the kexec, and the wait from COM3's own silence.
#   F25a  the capture is running; after the kexec there is no image reset line,
#         no guard deadline and no firmware banner; and the last line is image
#         output this harness recognises (below). L4T's boot option had started
#         before kexec; a cut is allowed once COM3 has not grown for 5 minutes.
#   F25b  anything else with a running capture: M5's exception only (m5-design.md
#         §2 rule 5): 10 minutes with no new COM3 byte, the last output not a menu
#         or prompt, no ssh answer; one cut, never a second.
#   nocapture  the capture is missing, has ended, failed, passed its deadline or is
#         held by no process: no cut from this file (F25b's rule, on a fresh capture).
# The firmware banner texts are parse-s1.py's FW_BANNER, which it calls HYPOTHESIS,
# so they are never the only evidence for F25a: the image's own reset line
# ('resetting so the log can be recovered', B1's included) and 'BWAIT guard
# deadline' mean a firmware boot has started, and an unrecognised last line may be
# firmware text under another name. Both give F25b (fail-safe).
# Recognised image output on COM3 (the guest's pl011 goes to /dev/ttyp2, and hvc0 to
# s1con's file, so neither reaches COM3): a record line (parse-s1.py's BB_PREFIXES,
# and tcu-cat:); a body line inside an open S1 BEGIN export; and, before the first
# record line only, Linux's own shutdown text (a printk time with six decimals, or a
# systemd status bracket), which is F10's hang before the shim. No output at all after
# the kexec is F10's too. Unprefixed QNX or qvm text as the last line is F25b: the cost
# of fail-safe is the longer wait and the one-cut limit.
# COM3's silence is the later of the file's modification time and a size sample
# taken here (the capture flushes after every read; that the NTFS time follows
# each write while the file is open is a HYPOTHESIS, so a 10 s sample backs it).

# stdin: the capture after the kexec, CR removed. Prints the last non-blank line's
# kind: none, record, export-body, linux-shutdown or unrecognised.
com3_last_kind() {
	awk '
	BEGIN { kind = "none"; seen = 0; open = 0 }
	{
		s = $0
		sub(/^[ \t]+/, "", s)
		sub(/[ \t]+$/, "", s)
		if (s == "" || s ~ /^--- raw capture /) next
		if (s ~ /^S1 BEGIN name=/) { open = 1; seen = 1; kind = "record"; next }
		if (s ~ /^S1 END name=/)   { open = 0; seen = 1; kind = "record"; next }
		if (s ~ /^(S1 |STAMP |BWAIT |T234 |T234-SHIM|t234: |tcu-cat:)/) { seen = 1; kind = "record"; next }
		if (open && s ~ /^[A-Za-z0-9+\/]+=*$/) { kind = "export-body"; next }
		if (!seen && (s ~ /^\[ *[0-9]+\.[0-9][0-9][0-9][0-9][0-9][0-9]\]/ || s ~ /^\[ *(OK|FAILED|DEPEND|TIME) *\]/)) { kind = "linux-shutdown"; next }
		kind = "unrecognised"
	}
	END { print kind }'
}

# $1 file, $2 offset of the kexec in bytes (-1 unknown), $3 now, $4 last growth
# epoch seen by the caller (0 none). Prints key=value lines.
com3_class() {
	local f="$1" off="${2:--1}" now="$3" grow="${4:-0}" t mt idle last banner=no reset=no menu=no cstate kind class x
	cstate="$(capture_state "$f")"
	if [ "$cstate" = missing ]; then
		echo "class=nocapture capture=missing"
		return
	fi
	t="$(mktemp)"
	if [ "$off" -ge 0 ] 2>/dev/null; then
		tail -c +"$(( off + 1 ))" "$f" | tr -d '\r' > "$t"
	else
		tr -d '\r' < "$f" > "$t"
	fi
	for x in "${FW_BANNER[@]}"; do grep -aqF -- "$x" "$t" && banner=yes; done
	grep -aqE 'resetting so the log can be recovered|BWAIT guard deadline' "$t" && reset=yes
	kind="$(com3_last_kind < "$t")"
	last="$(grep -av '^[[:space:]]*$' "$t" | grep -av '^--- raw capture' | tail -n 1)"
	if printf '%s\n' "$last" | grep -aqE 'Shell>|:\\>|login:|[Pp]assword:|Boot Manager|Setup|Select|Press|Continue|[$#>][[:space:]]*$'; then
		menu=yes
	fi
	mt=$(stat -c %Y "$f" 2>/dev/null || echo 0)
	(( grow > mt )) && mt=$grow
	idle=$(( now - mt ))
	if [ "$cstate" != running ]; then
		class=nocapture
	elif [ "$reset" = yes ] || [ "$banner" = yes ] || [ "$kind" = unrecognised ] || ! [ "$off" -ge 0 ] 2>/dev/null; then
		class=F25b
	else
		class=F25a
	fi
	echo "class=$class com3_silent_s=$idle capture=$cstate reset_after_kexec=$reset banner_after_kexec=$banner last_kind=$kind kexec_offset=$off last_is_menu_or_prompt=$menu"
	echo "last_line=$last"
	rm -f "$t"
}

# $1 file, $2 offset (-1 unknown), $3 last growth epoch (0 none), $4 the return bound:
# passed (a NO RETURN line), not_reached or unknown (the default). ADVICE_SSH may be
# preset to answered, silent or unchecked; otherwise the board is asked once.
com3_advice() {
	local f="$1" off="${2:--1}" grow="${3:-0}" bound="${4:-unknown}" now s0 s1 out head1 class idle menu last ssh="${ADVICE_SSH:-}" bid
	local cstate reset banner kind
	if [ -f "$f" ] && [ -z "${ADVICE_NO_SAMPLE:-}" ]; then
		s0=$(stat -c %s "$f")
		sleep 10
		s1=$(stat -c %s "$f")
		(( s1 > s0 )) && grow=$(date +%s)
	fi
	now=$(date +%s)
	out="$(com3_class "$f" "$off" "$now" "$grow")"
	head1="$(printf '%s\n' "$out" | head -n 1 | tr ' ' '\n')"
	class="$(kv class "$head1")"
	idle="$(kv com3_silent_s "$head1")"
	menu="$(kv last_is_menu_or_prompt "$head1")"
	cstate="$(kv capture "$head1")"
	reset="$(kv reset_after_kexec "$head1")"
	banner="$(kv banner_after_kexec "$head1")"
	kind="$(kv last_kind "$head1")"
	last="$(kv last_line "$out")"
	printf '%s\n' "$out" | mask_figures | sed 's/^/advice /'
	if [ -z "$ssh" ]; then
		if [ -n "${ORIN_HOST:-}" ]; then
			bid="$(read_boot_id)"
			if [[ "$bid" =~ ^[0-9a-f-]{36}$ ]]; then ssh=answered; else ssh=silent; fi
		else
			ssh=unchecked
		fi
	fi
	echo "advice ssh=$ssh"
	if [ "$ssh" = answered ]; then
		echo "advice NO CUT: L4T answers ssh. Compare its boot_id with the run's old one before anything else"
		return 0
	fi
	echo "advice return_bound=$bound"
	case "$bound" in
	passed) ;;
	not_reached)
		echo "advice NO CUT: the board log has no NO RETURN line, so the return bound has not passed (F25a and F25b both need 'not back by the return bound'). A healthy run can leave COM3 silent for minutes between its lines: wait until $PROG reports NO RETURN, then run advice again"
		return 0
		;;
	*)
		echo "advice NO CUT: no board log was given, so the return bound cannot be shown to have passed. Run advice with the run's, p1's or reboot's board log, whose NO RETURN line shows it"
		return 0
		;;
	esac
	if [ "$class" = F25b ]; then
		[ "$reset" = yes ] && echo "advice F25b because: the image's reset line or the guard's deadline follows the kexec, so a firmware boot has started"
		[ "$banner" = yes ] && echo "advice F25b because: a firmware banner text (parse-s1.py's FW_BANNER) follows the kexec"
		[ "$kind" = unrecognised ] && echo "advice F25b because: the last line is not a record line, an export body or Linux's shutdown text; it may be firmware output (the banner texts are a HYPOTHESIS)"
		[ "$off" -ge 0 ] 2>/dev/null || echo "advice F25b because: the kexec offset is unknown"
	fi
	case "$class" in
	F25a)
		if [ "$menu" = yes ]; then
			echo "advice NO CUT: the last COM3 line looks like a menu or prompt, which is not image text: the owner decides"
		elif (( idle >= 300 )); then
			echo "advice CUT ALLOWED (F25a): the last output is the image's own text and no firmware banner followed the kexec, so L4T's boot option had already started. Record the last line, pull power, let L4T boot, and reboot once more before any next run"
		else
			echo "advice NO CUT YET (F25a): COM3 last grew $idle s ago; F25a needs 300 s with no new byte. Keep the capture running and run advice again"
		fi
		;;
	F25b|nocapture)
		if [ "$class" = nocapture ]; then
			echo "advice NO CUT: no capture is running (capture=${cstate:-unknown}), so the class cannot be read and M5's exception applies, which needs COM3 evidence. Stop the old capture if its window is still open, start a fresh capture from PowerShell (a new -Out file), watch it for 10 minutes, then run advice on it with the same board log (its offset names the old file, so the class stays F25b)"
		elif [ "$menu" = yes ]; then
			echo "advice NO CUT (F25b): the last output is a menu, a prompt or the countdown, which M5's exception excludes: the owner decides"
		elif [ "$ssh" != silent ]; then
			echo "advice NO CUT YET (F25b): ssh was not checked; M5's exception needs no ssh answer in that time. Set ORIN_HOST and run advice again"
		elif (( idle >= 600 )); then
			echo "advice ONE CUT ALLOWED under M5's exception (F25b): COM3 has shown no new byte for 10 minutes, the last output is not a menu or a prompt, and L4T has not answered ssh. Record the last line, cut power once and press nothing, then let L4T boot to a validated state before any other step. If that boot also stops, board work stops and the owner decides. Never a second cut"
		else
			echo "advice NO CUT YET (F25b): COM3 last grew $idle s ago; M5's exception needs 600 s with no new byte. A firmware boot after the image is unvalidated until L4T answers: press nothing, and run advice again"
		fi
		;;
	esac
	[ -n "$last" ] || echo "advice note: COM3 shows no output after the kexec"
	return 0
}

cmd_advice() {
	local off=-1 bl="${1:-}" name bound=unknown
	[ -n "${S1_COM3_LOG:-}" ] || die "S1_COM3_LOG must name the COM3 capture to classify"
	if [ -n "$bl" ]; then
		if grep -aqE '^(run|p1|reboot) NO RETURN within' "$bl"; then bound=passed; else bound=not_reached; fi
		off="$(sed -n 's/^run com3_bytes_before_kexec=\([0-9][0-9]*\)$/\1/p' "$bl" | tail -n 1)"
		name="$(sed -n 's/^run com3_log=\([^ ]*\) .*/\1/p' "$bl" | tail -n 1)"
		if [ -z "$off" ] || [ "$name" != "$(basename "$S1_COM3_LOG")" ]; then
			note "the board log names no kexec offset for $(basename "$S1_COM3_LOG"): the offset is unknown, so F25a cannot be shown"
			off=-1
		fi
	else
		note "no board log: the return bound cannot be shown to have passed, so no cut is advised (and the kexec offset is unknown)"
	fi
	com3_advice "$S1_COM3_LOG" "$off" 0 "$bound" | redact
}

# ---------------------------------------------------------------- self-tests
#
# The redaction decides whether a private record can ever be shown to anyone;
# the advice decides whether power is cut. Both run here against synthetic
# values only - never the board's - and need no board, no ORIN_HOST, no network.

cmd_redact_selftest() {
	local d out fail=0 ran=0
	d="$(mktemp -d)" || die "cannot make a temp directory"

	R_USER=fakeuser
	R_HOST=203.0.113.7
	R_KEY=/c/Users/fakepc/.ssh/fakekeyname
	R_KEYBASE=fakekeyname
	R_PCUSER=fakepc
	R_HOSTNAME=fakehost-desktop

	printf 'MB1 version 01.02.03.04 loaded\r\n' > "$d/in"
	printf 'megasas driver 07.714.04.00-rc1\r\n' >> "$d/in"
	printf 'qemu 11.1.0 build\r\n' >> "$d/in"
	printf 'server at 203.0.113.7 replied\r\n' >> "$d/in"
	printf 'gateway 10.0.2.2 seen\r\n' >> "$d/in"
	printf 'mac 00:1b:44:11:3a:b7 seen\r\n' >> "$d/in"
	printf 'fakehost-desktop login:\r\n' >> "$d/in"
	printf 'systemd[1]: Started on fakehost-desktop\r\n' >> "$d/in"
	printf 'fakeuser@fakehost-desktop:~$ id\r\n' >> "$d/in"
	printf '/home/fakeuser/x\r\n' >> "$d/in"
	printf 'no trailing newline here' >> "$d/in"

	cp "$d/in" "$d/copy"
	redact_file "$d/copy" || die "redact_file failed in the self-test"
	redact < "$d/in" > "$d/out"

	check() {
		ran=$(( ran + 1 ))
		if [ "$2" = "$3" ]; then
			echo "  ok    $1"
		else
			echo "  FAIL  $1: got [$2] want [$3]"
			fail=$(( fail + 1 ))
		fi
	}

	check "version 01.02.03.04 kept" "$(grep -c '01[.]02[.]03[.]04' "$d/out")" 1
	check "version 07.714.04.00 kept" "$(grep -c '07[.]714[.]04[.]00' "$d/out")" 1
	check "version 11.1.0 kept" "$(grep -c 'qemu 11[.]1[.]0 build' "$d/out")" 1
	check "address masked" "$(grep -c '203[.]0[.]113[.]7' "$d/out")" 0
	check "slirp address masked" "$(grep -c '10[.]0[.]2[.]2' "$d/out")" 0
	check "mac masked" "$(grep -c '00:1b:44' "$d/out")" 0
	check "hostname masked" "$(grep -c 'fakehost-desktop' "$d/out")" 0
	check "login name masked" "$(grep -c 'fakeuser' "$d/out")" 0
	check "orin-host placeholder" "$(grep -c '<orin-host>' "$d/out")" 3
	check "CRs preserved" "$(tr -cd '\r' < "$d/out" | wc -c)" "$(tr -cd '\r' < "$d/in" | wc -c)"
	check "copy adds no newline" "$(tail -c 1 "$d/copy" | od -An -tu1 | tr -d ' ')" "$(tail -c 1 "$d/in" | od -An -tu1 | tr -d ' ')"
	check "copy keeps CRs" "$(tr -cd '\r' < "$d/copy" | wc -c)" "$(tr -cd '\r' < "$d/in" | wc -c)"

	out="$(ident_hits "$d/in")"
	check "ident_hits classes" "$(echo "$out" | grep -c 'addr=2 mac=1 name=')" 1
	printf 'login fakeuser@fakehost-desktop only\n' > "$d/nameonly"
	out="$(ident_hits "$d/nameonly" 2>&1)"
	check "ident_hits zero classes sum" "$(echo "$out" | grep -cE '^[1-9][0-9]* addr=0 mac=0 name=[1-9]')" 1
	check "ident_hits one line" "$(echo "$out" | wc -l)" 1
	printf 'nothing to see\n' > "$d/clean"
	check "ident_hits clean" "$(ident_hits "$d/clean" 2>&1)" "0 addr=0 mac=0 name=0"

	rm -rf "$d"
	echo
	if [ "$fail" -eq 0 ]; then
		echo "REDACT SELFTEST PASS $ran checks"
		return 0
	fi
	echo "REDACT SELFTEST FAIL $fail of $ran checks"
	return 1
}

cmd_harness_selftest() {
	local d fail=0 ran=0 now off out
	d="$(mktemp -d)" || die "cannot make a temp directory"
	R_USER=""; R_HOST=""; R_KEY=""; R_KEYBASE=""; R_PCUSER=""; R_HOSTNAME=""
	export ADVICE_NO_SAMPLE=1

	check() {
		ran=$(( ran + 1 ))
		if [ "$2" = "$3" ]; then
			echo "  ok    $1"
		else
			echo "  FAIL  $1: got [$2] want [$3]"
			fail=$(( fail + 1 ))
		fi
	}
	has() { printf '%s\n' "$1" | grep -qF -- "$2" && echo yes || echo no; }

	# SYNTHETIC captures. Before the kexec: an earlier firmware boot's banner. The
	# header's deadline is taken from now, so the capture is not expired on a later day;
	# nobody holds these files open, so ADVICE_CAPTURE_HELD stands in for the capture.
	now=$(date +%s)
	export ADVICE_CAPTURE_HELD=yes
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=6000 ---\n' "$now" > "$d/c.log"
	printf 'MB1 version synthetic\r\nESC to enter Setup.\r\nUbuntu synthetic login:\r\n' >> "$d/c.log"
	off=$(stat -c %s "$d/c.log")
	cp "$d/c.log" "$d/k.log"
	printf '[ 1234.567890] kexec_core: Starting new kernel\r\n' >> "$d/c.log"
	cp "$d/c.log" "$d/k.log"
	printf 'T234-SHIM EL=2 PC=0000000080080000\r\nt234: WDT0 CR=0x0\r\nT234 S1 s1-n1 -P4: procnto up\r\nS1 STATE launch\r\n' >> "$d/c.log"

	touch -d "@$(( now - 400 ))" "$d/c.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/c.log" "$off" 0 passed)"
	check "F25a: image text, no banner after the kexec" "$(has "$out" 'class=F25a')" yes
	check "F25a: 400 s silent allows a cut" "$(has "$out" 'CUT ALLOWED (F25a)')" yes
	touch -d "@$(( now - 100 ))" "$d/c.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/c.log" "$off" 0 passed)"
	check "F25a: 100 s silent is not yet" "$(has "$out" 'NO CUT YET (F25a)')" yes
	touch -d "@$(( now - 400 ))" "$d/c.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/c.log" "$off" "$(( now - 50 ))" passed)"
	check "F25a: a growth seen 50 s ago overrides the file time" "$(has "$out" 'NO CUT YET (F25a)')" yes
	out="$(ADVICE_SSH=silent com3_advice "$d/c.log" 0 0 passed)"
	check "offset 0 sees the earlier banner: F25b" "$(has "$out" 'class=F25b')" yes
	out="$(ADVICE_SSH=silent com3_advice "$d/c.log" -1 0 passed)"
	check "unknown offset: F25b, 400 s is not yet" "$(has "$out" 'NO CUT YET (F25b)')" yes
	out="$(ADVICE_SSH=answered com3_advice "$d/c.log" "$off" 0 passed)"
	check "ssh answers: no cut" "$(has "$out" 'NO CUT: L4T answers ssh')" yes

	# The return bound (F25a and F25b: 'not back by the return bound').
	out="$(ADVICE_SSH=silent com3_advice "$d/c.log" "$off" 0 not_reached)"
	check "bound not reached: no cut on 400 s of silence" "$(has "$out" 'NO CUT: the board log has no NO RETURN line')" yes
	check "bound not reached: no CUT ALLOWED said" "$(has "$out" 'CUT ALLOWED')" no
	out="$(ADVICE_SSH=silent com3_advice "$d/c.log" "$off" 0)"
	check "no board log: no cut" "$(has "$out" 'NO CUT: no board log was given')" yes

	# The image's own reset, or the guard's deadline, with an unknown firmware banner text.
	cp "$d/c.log" "$d/r.log"
	printf 'T234 S1 s1-n1 -P4: resetting so the log can be recovered\r\nJetson System firmware version synthetic date synthetic\r\n' >> "$d/r.log"
	touch -d "@$(( now - 400 ))" "$d/r.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/r.log" "$off" 0 passed)"
	check "reset line and an unknown banner: F25b" "$(has "$out" 'class=F25b')" yes
	check "reset line and an unknown banner: no F25a cut at 400 s" "$(has "$out" 'CUT ALLOWED (F25a)')" no
	check "reset line: the reason is said" "$(has "$out" "the image's reset line or the guard's deadline")" yes
	touch -d "@$(( now - 700 ))" "$d/r.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/r.log" "$off" 0 passed)"
	check "reset line and an unknown banner: one cut at 700 s" "$(has "$out" 'ONE CUT ALLOWED')" yes
	cp "$d/c.log" "$d/m.log"
	printf 'T234 M1b -P6: resetting so the log can be recovered\r\n' >> "$d/m.log"
	touch -d "@$(( now - 400 ))" "$d/m.log"
	check "B1's reset line alone: F25b" "$(has "$(ADVICE_SSH=silent com3_advice "$d/m.log" "$off" 0 passed)" 'class=F25b')" yes
	cp "$d/c.log" "$d/g.log"
	printf 'BWAIT guard deadline secs=900\r\n' >> "$d/g.log"
	touch -d "@$(( now - 400 ))" "$d/g.log"
	check "the guard's deadline: F25b" "$(has "$(ADVICE_SSH=silent com3_advice "$d/g.log" "$off" 0 passed)" 'class=F25b')" yes
	cp "$d/c.log" "$d/u.log"
	printf 'Jetson System firmware version synthetic\r\n' >> "$d/u.log"
	touch -d "@$(( now - 400 ))" "$d/u.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/u.log" "$off" 0 passed)"
	check "an unrecognised last line without a reset line: F25b" "$(has "$out" 'class=F25b')" yes
	check "an unrecognised last line: kind said" "$(has "$out" 'last_kind=unrecognised')" yes
	cp "$d/c.log" "$d/p.log"
	printf '[    0.000000] Booting Linux synthetic\r\n' >> "$d/p.log"
	touch -d "@$(( now - 400 ))" "$d/p.log"
	check "printk after a record line (a new L4T boot): F25b" "$(has "$(ADVICE_SSH=silent com3_advice "$d/p.log" "$off" 0 passed)" 'class=F25b')" yes
	cp "$d/c.log" "$d/e.log"
	printf 'S1 BEGIN name=fdt bytes=3 md5=0 enc=base64\r\nAAAA\r\n' >> "$d/e.log"
	touch -d "@$(( now - 400 ))" "$d/e.log"
	check "an open export's body as the last line: F25a" "$(has "$(ADVICE_SSH=silent com3_advice "$d/e.log" "$off" 0 passed)" 'class=F25a')" yes
	touch -d "@$(( now - 400 ))" "$d/k.log"
	check "only Linux's shutdown text after the kexec (F10): F25a" "$(has "$(ADVICE_SSH=silent com3_advice "$d/k.log" "$off" 0 passed)" 'class=F25a')" yes
	printf '[0000.063] I> synthetic firmware line\r\n' >> "$d/k.log"
	touch -d "@$(( now - 400 ))" "$d/k.log"
	check "a three-decimal bracket after Linux's text: F25b" "$(has "$(ADVICE_SSH=silent com3_advice "$d/k.log" "$off" 0 passed)" 'class=F25b')" yes

	cp "$d/c.log" "$d/b.log"
	printf 'T234 S1 s1-n1 -P4: resetting so the log can be recovered\r\nMB1 version synthetic\r\nL4TLauncher: synthetic stop\r\n' >> "$d/b.log"
	touch -d "@$(( now - 700 ))" "$d/b.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/b.log" "$off" 0 passed)"
	check "F25b: a banner after the image's reset" "$(has "$out" 'class=F25b')" yes
	check "F25b: 700 s silent, not a menu, no ssh: one cut" "$(has "$out" 'ONE CUT ALLOWED')" yes
	check "F25b: never a second cut is said" "$(has "$out" 'Never a second cut')" yes
	out="$(ADVICE_SSH=unchecked com3_advice "$d/b.log" "$off" 0 passed)"
	check "F25b: ssh unchecked is not a cut" "$(has "$out" 'NO CUT YET (F25b): ssh was not checked')" yes
	touch -d "@$(( now - 500 ))" "$d/b.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/b.log" "$off" 0 passed)"
	check "F25b: 500 s silent is not yet" "$(has "$out" 'NO CUT YET (F25b)')" yes
	printf 'Shell> \r\n' >> "$d/b.log"
	touch -d "@$(( now - 700 ))" "$d/b.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/b.log" "$off" 0 passed)"
	check "F25b: a prompt as the last line is no cut" "$(has "$out" 'NO CUT (F25b): the last output is a menu')" yes

	# A capture that is not running (F25b's third case): no cut from its file.
	cp "$d/c.log" "$d/x.log"
	printf -- '\n--- raw capture read error: The port is closed. bytes=99 ---\n' >> "$d/x.log"
	touch -d "@$(( now - 400 ))" "$d/x.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/x.log" "$off" 0 passed)"
	check "a read-error footer: nocapture" "$(has "$out" 'class=nocapture')" yes
	check "a read-error footer: no F25a cut" "$(has "$out" 'CUT ALLOWED')" no
	{ printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=6000 ---\n' "$(( now - 7000 ))"; tail -n +2 "$d/c.log"; } > "$d/t.log"
	touch -d "@$(( now - 400 ))" "$d/t.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/t.log" "$off" 0 passed)"
	check "the header's deadline passed with no footer: nocapture" "$(has "$out" 'capture=expired')" yes
	touch -d "@$(( now - 400 ))" "$d/c.log"
	out="$(ADVICE_CAPTURE_HELD=no ADVICE_SSH=silent com3_advice "$d/c.log" "$off" 0 passed)"
	check "a file no process holds (a forced stop): nocapture" "$(has "$out" 'capture=released')" yes
	check "capture_state: the open test finds an unheld file released" "$(ADVICE_CAPTURE_HELD='' capture_state "$d/c.log")" released
	tail -n +2 "$d/c.log" > "$d/n.log"
	check "capture_state: no header" "$(capture_state "$d/n.log")" noheader
	cp "$d/c.log" "$d/z.log"
	printf -- '\n--- raw capture ended 2026-09-14T01:00:00Z bytes=1 ---\n' >> "$d/z.log"
	touch -d "@$(( now - 900 ))" "$d/z.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/z.log" "$off" 0 passed)"
	check "an ended capture: no cut" "$(has "$out" 'NO CUT: no capture is running')" yes
	out="$(ADVICE_SSH=silent com3_advice "$d/missing.log" "$off" 0 passed)"
	check "a missing capture: no cut" "$(has "$out" 'class=nocapture')" yes
	sed -n '1,4p' "$d/c.log" > "$d/w.log"
	touch -d "@$(( now - 400 ))" "$d/w.log"
	out="$(ADVICE_SSH=silent com3_advice "$d/w.log" "$(stat -c %s "$d/w.log")" 0 passed)"
	check "no output after the kexec with a running capture (F10): F25a" "$(has "$out" 'class=F25a')" yes

	# Gate A: a capture that already holds an earlier run's records is refused.
	check "gate A: L4T text only has no records" "$(com3_has_records "$d/w.log" && echo yes || echo no)" no
	check "gate A: an earlier run's records are found" "$(com3_has_records "$d/c.log" && echo yes || echo no)" yes

	# A refused attempt gives its step's name back (§5.3).
	out="$(
		RECDIR="$d/rec"; SD="$RECDIR/B3"; UTC=20260914T000000Z; REC="$SD/s1-n1-$UTC-board.log"
		mkdir -p "$SD" && : > "$REC"
		run_refused_move 2>/dev/null
		[ ! -e "$SD" ] && [ -f "$RECDIR/B3-refused-$UTC/s1-n1-$UTC-board.log" ] && [ "$REC" = "$RECDIR/B3-refused-$UTC/s1-n1-$UTC-board.log" ] && echo moved
	)"
	check "a refused attempt moves to <step>-refused-<utc>" "$out" moved

	# The advice command the operator is told to run names a usable path.
	check "repo_rel: a path from the repository root" "$(repo_rel "$HERE/$PROG")" "orin-native/startup/$PROG"

	# consistency, extract
	printf 'T234-SHIM EL=2\nS1 STATE launch\nSTAMP i_ready cycles=5 cps=31250000 mono_ns=9\nS1 FAIL_STATE none\n' > "$d/bb.log"
	printf 'noise\r\nT234-SHIM EL=2\r\n  S1 STATE launch\r\nkernel text\r\nSTAMP i_ready cycles=5 cps=31250000 mono_ns=9\r\nS1 BEGIN name=fdt bytes=1 md5=0 enc=base64\r\nAA==\r\nS1 END name=fdt\r\nS1 FAIL_STATE none\r\n' > "$d/cc.log"
	check "consistency: subsequence" "$(has "$(consistency_files "$d/bb.log" "$d/cc.log")" 'consistent')" yes
	printf 'S1 STATE bogus\n' >> "$d/bb.log"
	check "consistency: a missing record differs" "$(has "$(consistency_files "$d/bb.log" "$d/cc.log")" 'DIFFER first_missing_record=5')" yes
	printf 'S1 MEM boot 900MB/992MB\nBWAIT run prog=qvm rc=0 sig=0 killed=0 ms=4000\nS1 CANARY c2 verify=bad first_off=0x10 words=1\n' >> "$d/bb.log"
	out="$(extract_file "$d/bb.log")"
	check "extract: FreeMem masked" "$(has "$out" '900MB')" no
	check "extract: ms masked" "$(has "$out" 'ms=4000')" no
	check "extract: stamp counts masked" "$(has "$out" 'cycles=5')" no
	check "extract: verify=bad flagged" "$(has "$out" "'verify=bad' x1")" yes

	# B1 tokens
	printf 'T234-SHIM EL=2 PC=0000000080080000\nt234: WDT0 CR=0x0\nT234 M1b -P6: procnto up\nT234 M1b -P6: resetting so the log can be recovered\nESC to enter Setup.\n' > "$d/b1c.log"
	printf 'T234-SHIM EL=2 PC=0000000080080000\nT234 M1b -P6: procnto up\n' > "$d/b1b.log"
	check "B1 tokens met" "$(has "$(b1_tokens "$d/b1c.log" "$d/b1b.log" MAINSWRST same)" 'B1 RESULT tokens met')" yes
	printf 't234: ram w2 base=0x100000000 size=0x8a000000\n' >> "$d/b1b.log"
	check "B1: a window-2 line fails" "$(has "$(b1_tokens "$d/b1c.log" "$d/b1b.log" MAINSWRST same)" 'NOT MET')" yes
	check "B1: another reset reason fails" "$(has "$(b1_tokens "$d/b1c.log" "" BCCPLEXWDT same)" 'NOT MET')" yes

	# b1-compare masks addresses
	printf 'startup at 0x80082000 size 00a1b2c3d4\nprocnto up\n' > "$d/r1.log"
	printf 'startup at 0x80083000 size 00a1b2c3ff\nprocnto up\n' > "$d/r2.log"
	check "b1-compare: addresses masked" "$(has "$(cmd_b1_compare "$d/r1.log" "$d/r2.log")" 'identical after masking')" yes

	# §8 item 6
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   24a000000-24dffffff : reserved\n' | iomem_gate)"
	check "iomem: the window line, nothing in range" "$(has "$out" 'iomem_sysram_line=yes iomem_entries_in_range=0')" yes
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   180000000-180ffffff : reserved\n' | iomem_gate)"
	check "iomem: a reservation in range is counted" "$(has "$out" 'iomem_entries_in_range=1')" yes
	# B0, 2026-09-14: the running kernel's KASLR image inside the range is not a reservation
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   221da0000-223b2ffff : Kernel code\niomemhi   223b30000-2242affff : reserved\niomemhi   2242b0000-22473ffff : Kernel data\niomemhi   24a000000-259ffffff : reserved\n' | iomem_gate)"
	check "iomem: the kernel image (code, reserved between, data) is not counted" "$(has "$out" 'iomem_sysram_line=yes iomem_entries_in_range=0')" yes
	check "iomem: the kernel image lines are reported" "$(printf '%s\n' "$out" | grep -c '^iomem_kernel_image ')" 3
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   180000000-180ffffff : reserved\niomemhi   221da0000-223b2ffff : Kernel code\niomemhi   223b30000-2242affff : reserved\niomemhi   2242b0000-22473ffff : Kernel data\n' | iomem_gate)"
	check "iomem: a reservation outside the kernel image still counts" "$(has "$out" 'iomem_entries_in_range=1')" yes
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   221da0000-223b2ffff : Kernel code\niomemhi   230000000-230ffffff : reserved\niomemhi   2242b0000-22473ffff : Kernel data\n' | iomem_gate)"
	check "iomem: a reserved line past the kernel data's end breaks the shape, all three count" "$(has "$out" 'iomem_entries_in_range=3')" yes
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   221da0000-223b2ffff : Kernel code\niomemhi   223b30000-223cfffff : reserved\niomemhi   223d00000-2242affff : reserved\niomemhi   2242b0000-22473ffff : Kernel data\n' | iomem_gate)"
	check "iomem: two reserved lines in the gap all count" "$(has "$out" 'iomem_entries_in_range=4')" yes
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   221da0000-223b2ffff : Kernel code\niomemhi   223c00000-2241fffff : reserved\niomemhi   2242b0000-22473ffff : Kernel data\n' | iomem_gate)"
	check "iomem: a gap line that is not contiguous counts" "$(has "$out" 'iomem_entries_in_range=3')" yes
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   221da0000-223b2ffff : Kernel code\niomemhi     223b30000-2242affff : reserved\niomemhi   2242b0000-22473ffff : Kernel data\n' | iomem_gate)"
	check "iomem: a gap line at another indent counts" "$(has "$out" 'iomem_entries_in_range=3')" yes
	out="$(printf 'iomemhi 100000000-25e20dfff : System RAM\niomemhi   223b30000-2242affff : reserved\niomemhi   2242b0000-22473ffff : Kernel data\n' | iomem_gate)"
	check "iomem: without Kernel code, the reserved and data lines both count" "$(has "$out" 'iomem_entries_in_range=2')" yes

	# §6.12, §7.3: the limits are constants and cannot be overridden
	check "uptime limit 7200" "$MAX_UPTIME_S" 7200
	check "quiesce uptime limit 1800" "$QUIESCE_MAX_UPTIME_S" 1800
	S1_QUIESCE_MAX_UPTIME_S=99999 bash "$0" redact-selftest >/dev/null 2>&1
	check "an uptime override is refused" "$?" 1
	check "image table: s1-n2 is B4 hold" "$(image_step s1-n2; echo "$STEP $MODE")" "B4 hold"

	rm -rf "$d"
	echo
	if [ "$fail" -eq 0 ]; then
		echo "HARNESS SELFTEST PASS $ran checks"
		return 0
	fi
	echo "HARNESS SELFTEST FAIL $fail of $ran checks"
	return 1
}

# ---------------------------------------------------------------- main

case "${1:-}" in
stage)       [ $# -eq 2 ] || usage; cmd_stage "$2" ;;
p0)          [ $# -eq 2 ] || usage; cmd_p0 "$2" ;;
p1)          [ $# -eq 1 ] || usage; cmd_p1 ;;
reboot)      [ $# -eq 1 ] || usage; cmd_reboot ;;
run)         [ $# -eq 2 ] || usage; cmd_run "$2" ;;
advice)      { [ $# -eq 1 ] || { [ $# -eq 2 ] && [ -f "$2" ]; }; } || usage; cmd_advice "${2:-}" ;;
extract)     { [ $# -eq 2 ] && [ -f "$2" ]; } || usage; extract_file "$2" ;;
consistency) { [ $# -eq 3 ] && [ -f "$2" ] && [ -f "$3" ]; } || usage; consistency_files "$2" "$3" ;;
b1-compare)  { [ $# -eq 3 ] && [ -f "$2" ] && [ -f "$3" ]; } || usage; cmd_b1_compare "$2" "$3" ;;
redact-selftest)  [ $# -eq 1 ] || usage; cmd_redact_selftest ;;
harness-selftest) [ $# -eq 1 ] || usage; cmd_harness_selftest ;;
*)           usage ;;
esac
