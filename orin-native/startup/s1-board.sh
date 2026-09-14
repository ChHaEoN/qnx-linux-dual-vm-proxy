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
#                                      capture. BOARDLOG is the run, p1, reboot, jrun
#                                      or j3 record: its NO RETURN line shows the bound
#                                      has passed, and a run's gives the kexec
#                                      offset. Without one, no cut is advised. A log
#                                      with wq_armed (jrun control|remove, j3): NO CUT
#                                      in every class until the fallback deadline +
#                                      1,200 s, then F25b, F25a/F25b, or F25w (§15.7.3)
#   s1-board.sh extract FILE           the record lines of a black box or COM3 copy
#   s1-board.sh consistency BB COM3    the black box's records as a subsequence of COM3's
#   s1-board.sh b1-compare BB REF      B1: a black box against M1b R2's, addresses masked
#   s1-board.sh redact-selftest        the redaction, against synthetic values
#   s1-board.sh harness-selftest       advice, consistency, extract, B1 tokens: synthetic
#   s1-board.sh j1                     J1 (§15.4.2): census and the private J-set.conf, the
#                                      s1wq: marker and transient-timer probe (D20), the
#                                      trace (D21) and a reboot; no quiesce, no kexec.
#                                      Needs <rec>/J-decisions.conf, S1_COM3_LOG and
#                                      S1_REDACT_SSID
#   s1-board.sh j3                     J3 (§15.4.5): the detached removal rehearsed on L4T with J4's
#                                      set and no kexec; ends through the fallback timer. Only
#                                      after J2's F32. Needs D20, D22, D25
#   s1-board.sh jrun IMG control|remove|b2repeat
#                                      J2, J4, J2b (§15.4.4, §15.4.6) with IMG s1-h1; J6c, J6r
#                                      (§15.4.8) with IMG s1-j1, control|remove only. control and
#                                      remove run the detached sequence (§15.4.3: J-set.conf's set,
#                                      empty in control), b2repeat is run's B2 flow as J2b. Parser
#                                      run --diag j2|j4|j2b|j1; J6 adds canwatch.txt. Exit 5: the
#                                      sequence aborted or its fallback fired, no kexec. J6 needs
#                                      D27=yes in <rec>/J-waivers.conf (and D34_J6=yes when J2's
#                                      row is F39) and T-J1 met with the image's memcanary-w; J6c
#                                      follows J4's F36, J2's F32a|F32b or J2b's F46 (else
#                                      D27_J6C=yes), J6r J4's F35 (else D27_J6R=yes); its first
#                                      attempt per arm appends the J6 stage to J-prereg.log after
#                                      gate A (S1_J6_FILL_FACTOR; S1_J6_AMEND_BY for an amendment)
#   s1-board.sh wq-status BOARDLOG     §15.4.6's state (ARMED, PROGRESS, ISSUED, JUMPED, ABORTED,
#                                      STALLED) of a j3 or jrun board log, from S1_COM3_LOG
#   s1-board.sh kpf-decode HEADER [HEADER] | --selftest
#                                      orin-native/s1/kpf-decode.py on b_kpf_snap headers
#
# IMAGES (the step each one is, §6.12)
#   s1-m1b-p6 B1 (no S1 host script; no parser)   s1-h1 B2 (host)
#   s1-n1 B3 (boot)   s1-n2 B4 (hold)   s1-q2 B5 (q2)   s1-d1 d1 (boot; a diagnostic)
#   s1-j1 J6 (host; the watcher, §15.4.8: stage and p0 as any image, then jrun only, never run)
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
#                          required); its header must carry epoch= and seconds=.
#                          J rungs (and advice on their logs) accept E:\... paths
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
#   S1_REDACT_SSID         the wireless network name to redact (never written to
#                          a record; read through awk ENVIRON, refused under 3
#                          bytes). Mandatory for the J diagnostic rungs (§15.5 A4)
#   S1_J_RULE_FILE         J rungs: a file holding §15.6's pre-registered rule
#                          text; its sha256 goes into J-prereg.log (§15.4.1)
#   S1_J6_FILL_FACTOR      jrun s1-j1: the fill-rate factor of §15.4.8's row (a decimal >= 1),
#                          read only when the first J6 attempt appends the J6 stage to
#                          J-prereg.log; afterwards it must be unset or equal the registered one
#   S1_J6_AMEND_BY         jrun s1-j1: owner-<decision>, naming the owner's decision when J6's
#                          stage is an amendment (the harness differs from J2's registration, or
#                          the stage supersedes one that no longer matches, only before the arm's
#                          first run); written into the amendment line, read nowhere else
#   S1_J6_WQ_CHANGED       jrun s1-j1: yes only when the owner accepts that WQ_FUNCS differs from
#                          the registered commit's, so J6 would not repeat J2's detached sequence
#   S1_J_L4T_CONSOLE       yes: after an exit-5 (no kexec) return of jrun or j3, copy the
#                          previous console as -l4t-console-ramoops.log (scanned, never a
#                          black box, never parsed); unset: not copied
#   S1_WQ_*                REFUSED: the detached-sequence constants are fixed by
#                          the design (§15.4.3); unset any S1_WQ_ variable
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
# first reading (F30): stop all board work; 5 (J rungs) the detached sequence
# aborted or its fallback fired, no kexec happened, a harness-reason retry
# (§15.5 A1). A J rung's 3 also covers F37 (an immediate stop) and a return with
# no jump, abort or fallback marker and no shim line; neither is a retry.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROG="$(basename "$0")"
S1DIR="$HERE/../s1"
PARSER="$S1DIR/parse-s1.py"

usage() { sed -n '3,/^set -uo/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//' >&2; exit 2; }
ON_DIE=""
die()   { echo "$PROG: FAIL: $*" >&2; [ -n "${REC:-}" ] && printf '%s\n' "FAIL: $*" | redact >> "$REC"; [ -n "$ON_DIE" ] && "$ON_DIE"; exit 1; }
# J6c (2026-09-14): a set -u stop (status 127) skipped ON_DIE and left a crashed attempt's records
# in place. No path exits 127 on purpose, so only that status runs the handler here.
trap '__rc=$?; if [ "$__rc" = 127 ] && [ -n "${ON_DIE:-}" ]; then __f="$ON_DIE"; ON_DIE=""; "$__f"; fi' EXIT
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

# §15.5 A1: the J diagnostic rungs' abort/fallback return, no kexec (a harness-reason retry).
EXIT_SEQ_REBOOT=5

# §15.4.3: the detached-sequence timing constants are fixed by the design and refused
# if set in the environment (the S1_WQ_ forms and the bare names alike); they are
# printed in every J board log (wq_constants). WQ_SLOTS is fixed by the slot list the
# generator derives from J1's set file (part 2), so it is not a script constant here;
# WQ_FALLBACK_S is a function of the slot count (wq_fallback_s).
for v in WQ_START_DELAY_S WQ_SLOT_S WQ_STEP_TIMEOUT_S WQ_FINAL_READS_S WQ_ISSUE_WAIT_S WQ_SLOTS WQ_FALLBACK_S; do
	if [ -n "${!v+x}" ]; then
		echo "$PROG: FAIL: $v is set: the detached-sequence constants are fixed by s1-design.md (§15.4.3); unset it" >&2
		exit 1
	fi
done
for v in "${!S1_WQ_@}"; do
	echo "$PROG: FAIL: $v is set: no S1_WQ_ variable configures the detached sequence; its timing is fixed by the design (§15.4.3); unset it" >&2
	exit 1
done
WQ_START_DELAY_S=15
WQ_SLOT_S=30
WQ_STEP_TIMEOUT_S=25
WQ_FINAL_READS_S=60
WQ_ISSUE_WAIT_S=180

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
# Colon and hyphen forms (a vendor wireless/Ethernet driver may print either), and
# systemd's MAC-based interface name enx<12 hex digits>, which carries the MAC unseparated.
IDENT_MAC='([0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}|[0-9A-Fa-f]{2}(-[0-9A-Fa-f]{2}){5}|enx[0-9A-Fa-f]{12})'
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

# §15.5 A4: the SSID (S1_REDACT_SSID) is passed through awk ENVIRON, never -v: awk
# -v processes backslash escapes in the value, and an SSID may hold a backslash. It
# is used only when it is at least 3 bytes long (a 1-2 byte name would over-redact;
# a J subcommand refuses a shorter one up front, ssid_len_ok).
redact() {
	awk -v BINMODE=3 -v u="$R_USER" -v h="$R_HOST" -v k="$R_KEY" -v kb="$R_KEYBASE" -v pu="$R_PCUSER" -v hn="$R_HOSTNAME" '
	BEGIN { sd = ENVIRON["S1_REDACT_SSID"] }
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
		if (length(sd) >= 3) line = lit(line, sd, "<ssid>")
		line = lit(line, k, "<orin-key>")
		line = lit(line, kb, "<orin-key>")
		if (hn != "") line = lit(line, hn, "<orin-host>")
		if (u != "") { line = lit(line, u "@", "<user>@"); line = lit(line, "/home/" u, "/home/<user>") }
		if (u != "") line = lit(line, u, "<user>")
		if (pu != "") { line = lit(line, "Users/" pu, "Users/<user>"); line = lit(line, "Users\\" pu, "Users\\<user>"); line = lit(line, "/home/" pu, "/home/<user>") }
		line = lit(line, h, "<orin-ip>")
		line = mask_ips(line)
		gsub(/[0-9A-Fa-f][0-9A-Fa-f](:[0-9A-Fa-f][0-9A-Fa-f]){5}/, "<mac>", line)
		gsub(/[0-9A-Fa-f][0-9A-Fa-f](-[0-9A-Fa-f][0-9A-Fa-f]){5}/, "<mac>", line)
		gsub(/enx[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]/, "enx<mac>", line)
		print line
	}'
}

# Counts per class. Prints: total addr=N mac=N name=N ssid=N
# The ssid class (§15.5 A4) is counted whenever S1_REDACT_SSID is set and at least 3
# bytes, so a copy whose only identifier is the SSID is never kept raw by privacy_scan.
ident_hits() {
	local f="$1" pats=() addr mac name ssid sv total
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
	ssid=0
	sv="${S1_REDACT_SSID:-}"
	[ "${#sv}" -ge 3 ] && ssid="$(grep -acF -- "$sv" "$f" 2>/dev/null)"
	addr="${addr:-0}" mac="${mac:-0}" name="${name:-0}" ssid="${ssid:-0}"
	total=$(( addr + mac + name + ssid ))
	echo "$total addr=$addr mac=$mac name=$name ssid=$ssid"
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

# ---- J diagnostic reads (§15.5 A1), Phase A over ssh. b_pci_state and b_trace_on are
# also meant for WQ_FUNCS, so they use printf, not echo. None of these names a driver, an
# address or a network: a device is found by its PCI class code, its sysfs driver link or
# the USB host it carries. None reads an address or serial file, or runs ip addr, nmcli,
# iw, rfkill, lsusb or hciconfig (§15.1's Never items). S1_SYSROOT (a prefix for the /sys
# and /proc reads) and S1_SHM (the tmpfs root) exist for the self-tests' fixture tree only;
# neither is set on the board, so the board reads /sys, /proc and /dev/shm.

# A link fully resolved (readlink -e); empty when it or any component is missing.
s1_rl() { readlink -e -- "$1" 2>/dev/null; }

# §15.5 A1: raw /proc/kpageflags and /proc/kpagecount slices of c1's and window 2's page
# frames (§3.3's design constants), zoneinfo and buddyinfo, and the version-1 text header
# orin-native/s1/kpf-decode.py documents, all in a fresh mktemp -d tmpfs directory: no tar,
# nothing on the rootfs. Prints 'kpf tag= dir=', one 'kpf file= bytes= sha256=' line per
# file and 'kpf tag= result='. The PC fetches, verifies and removes (j_kpf_fetch). $1 the
# tag (prequiesce|postquiesce); KPF_NAME, set on a command line before it, the file prefix.
b_kpf_snap() {
	local tag="$1" R="${S1_SYSROOT:-}" shm="${S1_SHM:-/dev/shm}" dir n fl ct hd zi bi r name start count src soff=0 rc=0
	local ranges="" bid up f
	case "$tag" in prequiesce|postquiesce) ;; *) echo "kpf tag=$tag result=refused reason=tag"; return 0 ;; esac
	case "${KPF_NAME:-}" in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9._-]*) echo "kpf tag=$tag result=refused reason=name"; return 0 ;; esac
	dir="$(mktemp -d "$shm/s1kpf.XXXXXX" 2>/dev/null)" || dir=""
	[ -n "$dir" ] || { echo "kpf tag=$tag result=failed reason=mktemp"; return 0; }
	echo "kpf tag=$tag dir=$dir"
	bid="$(cat "$R/proc/sys/kernel/random/boot_id" 2>/dev/null)"
	up="$(cut -d' ' -f1 "$R/proc/uptime" 2>/dev/null)"
	n="$KPF_NAME-kpf-$tag"
	fl="$n.flags.bin"; ct="$n.count.bin"; hd="$n-header.txt"; zi="$n-zoneinfo.txt"; bi="$n-buddyinfo.txt"
	: > "$dir/$fl"; : > "$dir/$ct"
	# name:first page frame:page frames. The slices are the ranges concatenated in this order.
	for r in c1:0xbd000:4096 w2:0x100000:565248; do
		name="${r%%:*}"; start="${r#*:}"; count="${start#*:}"; start="${start%%:*}"
		src=$(( start * 8 ))
		sudo -n dd if="$R/proc/kpageflags" iflag=skip_bytes,count_bytes,fullblock bs=65536 skip="$src" count=$(( count * 8 )) status=none >> "$dir/$fl" || rc=1
		sudo -n dd if="$R/proc/kpagecount" iflag=skip_bytes,count_bytes,fullblock bs=65536 skip="$src" count=$(( count * 8 )) status=none >> "$dir/$ct" || rc=1
		ranges="${ranges}range=$name pfn_start=$start pfn_count=$count src_offset=$(printf '0x%x' "$src") slice_offset=$soff"$'\n'
		soff=$(( soff + count * 8 ))
	done
	[ "$(stat -c %s "$dir/$fl")" = "$soff" ] && [ "$(stat -c %s "$dir/$ct")" = "$soff" ] || rc=1
	cat "$R/proc/zoneinfo" > "$dir/$zi" 2>/dev/null || rc=1
	cat "$R/proc/buddyinfo" > "$dir/$bi" 2>/dev/null || rc=1
	{
		echo "kpf_header=1"
		echo "tag=$tag"
		echo "boot_id=$bid"
		echo "uptime_s=$up"
		echo "page_size=$(getconf PAGESIZE 2>/dev/null)"
		echo "flags_file=$fl"
		echo "flags_sha256=$(sha256sum "$dir/$fl" | cut -d' ' -f1)"
		echo "count_file=$ct"
		echo "count_sha256=$(sha256sum "$dir/$ct" | cut -d' ' -f1)"
		case "${UTC:-}" in [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) echo "utc=$UTC" ;; esac
		echo "zoneinfo_file=$zi"
		echo "zoneinfo_sha256=$(sha256sum "$dir/$zi" | cut -d' ' -f1)"
		echo "buddyinfo_file=$bi"
		echo "buddyinfo_sha256=$(sha256sum "$dir/$bi" | cut -d' ' -f1)"
		printf '%s' "$ranges"
	} > "$dir/$hd"
	for f in "$hd" "$fl" "$ct" "$zi" "$bi"; do
		echo "kpf file=$f bytes=$(stat -c %s "$dir/$f") sha256=$(sha256sum "$dir/$f" | cut -d' ' -f1)"
	done
	echo "kpf tag=$tag result=$([ "$rc" = 0 ] && echo ok || echo failed) entries=$(( soff / 8 ))"
}

# Removes one b_kpf_snap (or J1 probe) directory and nothing else: the path must be the
# mktemp pattern directly under the tmpfs root.
b_kpf_rm() {
	local dir="$1" shm="${S1_SHM:-/dev/shm}"
	case "$dir" in "$shm"/s1kpf.??????) ;; *) echo "kpf rm refused"; return 0 ;; esac
	case "${dir##*/}" in *[!A-Za-z0-9.]*) echo "kpf rm refused"; return 0 ;; esac
	rm -rf -- "$dir"
	echo "kpf rm dir=$dir rc=$? left=$([ -e "$dir" ] && echo yes || echo no)"
}

# §15.5 A1: one line per PCI function (driver, parent port, power_state, enable, the
# Command register from config offset 4 and its Bus Master bit), each USB host's binding
# (and XHCI_PATH's, when set: a /sys/devices path from J-set.conf, since the root hubs go
# with an unbind), rfkill soft and hard from sysfs, each netdev's operstate, and whether
# NetworkManager and wpa_supplicant are active. A Command register that reads all ones
# (0xffff: the function is gone, in D3cold or behind a link that is down) is bme=unread.
# PCI_CONFIG_READ=no (J1 without D22) reads no configuration space: cmd=not-read. A
# MAC-based interface name (enx + 12 hex digits) is printed as enx<mac>. $1 the tag.
b_pci_state() {
	local tag="${1:-}" R="${S1_SYSROOT:-}" l dev drv par cls ps en b cmdh bme z ctl sub t nm n=0
	local -a cb
	for l in "$R"/sys/bus/pci/devices/*; do
		dev="$(s1_rl "$l")"
		[ -n "$dev" ] || continue
		drv="$(s1_rl "$dev/driver")"; drv="${drv##*/}"
		par="${dev%/*}"; par="${par##*/}"
		case "$par" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f].[0-7]) ;; *) par=none ;; esac
		cls="$(cat "$dev/class" 2>/dev/null)"
		ps="$(cat "$dev/power_state" 2>/dev/null)"
		en="$(cat "$dev/enable" 2>/dev/null)"
		b=""
		[ "${PCI_CONFIG_READ:-yes}" = yes ] && b="$(timeout 10 od -An -tu1 -j4 -N2 "$dev/config" 2>/dev/null)"
		cb=($b)
		if [ "${PCI_CONFIG_READ:-yes}" != yes ]; then
			cmdh=not-read; bme=not-read
		elif [ "${#cb[@]}" = 2 ] && [ "${cb[0]}" = 255 ] && [ "${cb[1]}" = 255 ]; then
			cmdh=0xffff; bme=unread
		elif [ "${#cb[@]}" = 2 ]; then
			printf -v cmdh '0x%04x' $(( cb[0] + 256 * cb[1] ))
			bme=$(( (cb[0] >> 2) & 1 ))
		else
			cmdh=unread; bme=unread
		fi
		printf '%s\n' "pci $tag dev=${dev##*/} class=${cls:-unread} driver=${drv:-none} parent=$par power_state=${ps:-unread} enable=${en:-unread} cmd=$cmdh bme=$bme"
	done
	for l in "$R"/sys/bus/usb/devices/usb*; do
		z="$(s1_rl "$l")"
		[ -n "$z" ] || continue
		n=$(( n + 1 ))
		ctl="${z%/*}"
		sub="$(s1_rl "$ctl/subsystem")"; t="$(s1_rl "$ctl/driver")"
		printf '%s\n' "usbhost $tag bus=${z##*/} controller=${ctl##*/} subsystem=${sub##*/} driver=${t##*/}"
	done
	[ "$n" = 0 ] && printf '%s\n' "usbhost $tag none"
	case "${XHCI_PATH:-}" in
	'') ;;
	/sys/devices/*[!A-Za-z0-9@:._/-]*) printf '%s\n' "xhci $tag path refused" ;;
	/sys/devices/*)
		t="$(s1_rl "$R$XHCI_PATH/driver")"
		printf '%s\n' "xhci $tag present=$([ -d "$R$XHCI_PATH" ] && printf yes || printf no) driver=${t##*/}" ;;
	*) printf '%s\n' "xhci $tag path refused" ;;
	esac
	for z in "$R"/sys/class/rfkill/rfkill*; do
		[ -d "$z" ] || continue
		printf '%s\n' "rfkill $tag name=${z##*/} type=$(cat "$z/type" 2>/dev/null) soft=$(cat "$z/soft" 2>/dev/null) hard=$(cat "$z/hard" 2>/dev/null)"
	done
	for z in "$R"/sys/class/net/*; do
		[ -d "$z" ] || continue
		t="$(s1_rl "$z/device")"; t="${t##*/}"
		nm="${z##*/}"
		case "$nm" in enx[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) nm="enx<mac>" ;; esac
		printf '%s\n' "netdev $tag if=$nm operstate=$(cat "$z/operstate" 2>/dev/null) dev=${t:-none}"
	done
	printf '%s\n' "svc $tag NetworkManager=$(timeout 10 systemctl is-active NetworkManager.service </dev/null 2>/dev/null) wpa_supplicant=$(timeout 10 systemctl is-active wpa_supplicant.service </dev/null 2>/dev/null)"
}

# §15.4.2 item 4: one 'cen blkchain' line per sysfs device behind a mount, a swap area,
# the root, $HOME, KD or /dev/shm (and each device-mapper slave, four levels deep).
# path= is the sysfs path, 'network' for a network filesystem, 'none' for a RAM
# filesystem, and 'unresolved' when a non-mount use cannot be traced (the set rules treat
# that fail-safe). A mount that is neither a /dev device nor network is not listed.
# $1 use (mount|swap|root|home|kd|shm), $2 source, $3 fstype.
b_census_chain() {
	local use="$1" src="${2%%[[]*}" fs="${3:-unknown}" R="${S1_SYSROOT:-}" d real
	case "$fs" in
	nfs|nfs4|cifs|smb3|fuse.sshfs|9p) echo "cen blkchain use=$use fstype=$fs path=network"; return 0 ;;
	tmpfs|ramfs|devtmpfs) [ "$use" = mount ] || echo "cen blkchain use=$use fstype=$fs path=none"; return 0 ;;
	esac
	case "$src" in
	/dev/*) ;;
	*) [ "$use" = mount ] || echo "cen blkchain use=$use fstype=$fs path=unresolved"; return 0 ;;
	esac
	d="$(s1_rl "$src")"
	[ -n "$d" ] || d="$src"
	real="$(s1_rl "$R/sys/class/block/${d##*/}")"
	if [ -z "$real" ]; then
		echo "cen blkchain use=$use fstype=$fs path=unresolved"
		return 0
	fi
	echo "cen blkchain use=$use fstype=$fs path=${real#"$R"}"
	b_census_slaves "$use" "$fs" "$real" 1
}

b_census_slaves() {
	local use="$1" fs="$2" real="$3" depth="$4" s r
	[ "$depth" -le 4 ] || return 0
	for s in "$real"/slaves/*; do
		r="$(s1_rl "$s")"
		[ -n "$r" ] || continue
		echo "cen blkchain use=$use fstype=$fs path=${r#"${S1_SYSROOT:-}"}"
		b_census_slaves "$use" "$fs" "$r" $(( depth + 1 ))
	done
}

# $1 use, $2 a path: the filesystem that holds it, traced by b_census_chain.
b_census_path() {
	local src="" fs=""
	read -r src fs < <(findmnt -rn -T "$2" -o SOURCE,FSTYPE </dev/null 2>/dev/null)
	b_census_chain "$1" "$src" "$fs"
}

# §15.4.2 reads 1-5 and 7 (J1's census; read 6, the marker and timer probe, is the PC's).
# Every line starts 'cen ' (b_pci_state's census lines and the probe's 'kpf ' lines
# aside); j_set_rules reads the 'cen ' lines on the PC. KPF_NAME, J_D22 and J_D23 are set on
# command lines before it. Without D22 (the snapshots and the PCI configuration reads,
# §15.6), the kpageflags probe is not taken and no configuration space is read.
b_census() {
	local R="${S1_SYSROOT:-}" shm="${S1_SHM:-/dev/shm}" t p l dev drv mod par nd z n ctl sub k=no dir f rc mnts src fs tgt rest cls PCI_CONFIG_READ=yes
	# read 1: tools, and the snapshot primitive (R60): 64 kpageflags entries at c1's frame
	for t in systemd-run setpci dd sha256sum modprobe findmnt; do
		p="$(command -v "$t" 2>/dev/null)"
		echo "cen tool name=$t path=${p:-absent}"
	done
	echo "cen systemd-run-version $(systemd-run --version </dev/null 2>/dev/null | head -n 1)"
	f="${KPF_NAME:-j1}-kpf-probe.bin"
	case "$f" in [!A-Za-z0-9]*|*[!A-Za-z0-9._-]*) f="j1-kpf-probe.bin" ;; esac
	dir=""
	if [ "${J_D22:-no}" != yes ]; then
		PCI_CONFIG_READ=no
		echo "kpf tag=probe result=not-read reason=D22-not-yes"
		echo "cen pciconfig not read: D22 is not yes"
	else
		dir="$(mktemp -d "$shm/s1kpf.XXXXXX" 2>/dev/null)" || dir=""
		[ -n "$dir" ] || echo "kpf tag=probe result=failed reason=mktemp"
	fi
	if [ -n "$dir" ]; then
		echo "kpf tag=probe dir=$dir"
		sudo -n dd if="$R/proc/kpageflags" iflag=skip_bytes,count_bytes,fullblock bs=512 skip=$(( 0xbd000 * 8 )) count=512 status=none > "$dir/$f"
		rc=$?
		echo "kpf file=$f bytes=$(stat -c %s "$dir/$f") sha256=$(sha256sum "$dir/$f" | cut -d' ' -f1)"
		echo "kpf tag=probe result=$([ "$rc" = 0 ] && echo ok || echo failed) dd_rc=$rc entries_wanted=64"
	fi
	# read 2: kernel configuration and printk
	if [ -r "$R/proc/config.gz" ]; then
		zcat "$R/proc/config.gz" | grep -E '^(# )?CONFIG_(DMA_API_DEBUG|PAGE_OWNER|IOMMU_DEBUGFS|KEXEC_FILE|PCI_IOV)[= ]' | sed 's/^/cen kconfig /'
	else
		echo "cen kconfig none: /proc/config.gz is not readable"
	fi
	for t in printk printk_devkmsg panic panic_on_oops; do
		echo "cen sysctl $t=$(tr -s ' \t' ',,' < "$R/proc/sys/kernel/$t" 2>/dev/null)"
	done
	# read 3: PCI topology (the parent port's child count is j_set_rules'), identity groups
	b_pci_state census
	for l in "$R"/sys/bus/pci/devices/*; do
		dev="$(s1_rl "$l")"
		[ -n "$dev" ] || continue
		drv="$(s1_rl "$dev/driver")"
		mod=""
		[ -n "$drv" ] && mod="$(s1_rl "$drv/module")"
		par="${dev%/*}"; par="${par##*/}"
		case "$par" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f].[0-7]) ;; *) par=none ;; esac
		nd=""
		for z in "$dev"/net/*; do
			[ -e "$z" ] || continue
			t="${z##*/}"
			case "$t" in enx[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]) t="enx<mac>" ;; esac
			nd="${nd:+$nd,}$t"
		done
		cls="$(cat "$dev/class" 2>/dev/null)"
		drv="${drv##*/}"; mod="${mod##*/}"
		echo "cen pcidev bdf=${dev##*/} class=${cls:-unread} driver=${drv:-none} module=${mod:-none} parent=$par netdev=${nd:-none} path=${dev#"$R"}"
	done
	n=0
	for z in "$R"/sys/kernel/iommu_groups/*; do
		[ -f "$z/type" ] || continue
		n=$(( n + 1 ))
		t="$(cat "$z/type" 2>/dev/null)"
		case "$t" in DMA|DMA-FQ) ;; *) echo "cen iommu_group group=${z##*/} type=${t:-unread}" ;; esac
	done
	echo "cen iommu_groups_read=$n"
	# read 4: mounts, swap, and the storage chain of /, $HOME, /dev/shm and KD
	mnts="$(findmnt -rn -o TARGET,SOURCE,FSTYPE </dev/null 2>/dev/null)"
	printf '%s\n' "$mnts" | sed 's/^/cen mount /'
	sed 's/^/cen swaps /' "$R/proc/swaps" 2>/dev/null
	while read -r tgt src fs; do
		[ -n "$src" ] && b_census_chain mount "$src" "$fs"
	done < <(printf '%s\n' "$mnts")
	while read -r src rest; do
		case "$src" in
		/dev/*) b_census_chain swap "$src" swap ;;
		?*)     b_census_path swap "$src" ;;
		esac
	done < <(awk 'NR > 1 { print $1 }' "$R/proc/swaps" 2>/dev/null)
	b_census_path root /
	b_census_path home "$HOME"
	b_census_path kd "${KD:-$HOME}"
	b_census_path shm /dev/shm
	# read 5: USB: driver links, ids and interface classes only (no serial, no address)
	for l in "$R"/sys/bus/usb/devices/*; do
		z="$(s1_rl "$l")"
		[ -n "$z" ] || continue
		n="${z##*/}"
		drv="$(s1_rl "$z/driver")"; drv="${drv##*/}"
		case "$n" in
		*:*)
			t="$(cat "$z/bInterfaceClass" 2>/dev/null)"
			[ "$t" = 03 ] && [ "$(cat "$z/bInterfaceProtocol" 2>/dev/null)" = 01 ] && k=yes
			echo "cen usbif name=$n driver=${drv:-none} bInterfaceClass=${t:-unread}"
			;;
		*)
			echo "cen usbdev name=$n driver=${drv:-none} idVendor=$(cat "$z/idVendor" 2>/dev/null) idProduct=$(cat "$z/idProduct" 2>/dev/null)"
			case "$n" in
			usb[0-9]*)
				ctl="${z%/*}"
				sub="$(s1_rl "$ctl/subsystem")"; t="$(s1_rl "$ctl/driver")"
				mod=""
				[ -n "$t" ] && mod="$(s1_rl "$t/module")"
				t="${t##*/}"; mod="${mod##*/}"
				echo "cen usbhost bus=$n controller=${ctl##*/} subsystem=${sub##*/} driver=${t:-none} module=${mod:-none} path=${ctl#"$R"}"
				;;
			esac
			;;
		esac
	done
	echo "cen hid_keyboard=$k"
	# read 7, only under D23: record only, never a gate, never GPU MMIO (paths HYPOTHESIS, Q18)
	if [ "${J_D23:-no}" = yes ]; then
		sudo -n cat "$R/sys/kernel/debug/pm_genpd/pm_genpd_summary" 2>/dev/null | grep -i gpu | head -n 4 | sed 's/^/cen debugfs genpd /'
		for p in /sys/kernel/debug/bpmp/debug/clk/emc/rate /sys/kernel/debug/clk/emc/clk_rate; do
			echo "cen debugfs emc_rate path=$p value=$(sudo -n cat "$R$p" 2>/dev/null | head -n 1)"
		done
	else
		echo "cen debugfs not read: D23 is not yes"
	fi
}

# D21 (§15.4.2 item 8; §15.4.3 Phase B step 9): the runtime-only trace settings, and the
# only writes of J1. Runs as root: in a unit, or over ssh as sudo -n bash -c with this
# function's declare -f. One redirect and one dmesg -n; nothing persists across a boot.
b_trace_on() {
	printf '1\n' > /sys/module/kernel/parameters/initcall_debug
	printf '%s\n' "trace initcall_debug_rc=$? initcall_debug=$(cat /sys/module/kernel/parameters/initcall_debug 2>/dev/null)"
	dmesg -n 7
	printf '%s\n' "trace console_level_7_rc=$?"
}

# §15.4.2 item 6 (D20): the marker probe and the transient timer. Neither the unit's
# description nor any status line carries the marker text; the command holds no % and
# no $, so systemd expands nothing in it.
b_j1_probe() {
	echo '<3>s1wq: j1 probe result=0' | sudo -n tee /dev/kmsg >/dev/null
	echo "j1_probe_write_rc=$?"
}
b_j1_timer() {
	sudo -n systemd-run --unit="s1wqj1-$UTC" --description=s1-j1-timer-probe --on-active=30s --collect \
		/bin/sh -c 'echo "<3>s1wq: j1 timer result=0" > /dev/kmsg' </dev/null
	echo "j1_timer_arm_rc=$?"
}

# ---- the detached sequence's own functions (§15.4.3 Phase B; §15.5 A1 and A5). Only these
# (WQ_FUNCS) are emitted by declare -f into <name>-wq.sh and <name>-wqfb.sh, whose header
# (b_wq_gen, printf %q only) sets every WQ_ variable they read; they run as root in a
# transient unit, so they call no sudo (b_freq's own 'sudo -n cat' aside). None quiesces,
# pins, writes dynamic_debug or names a device: each set member comes from J-set.conf's
# driver link and path, re-resolved here (b_wq_resolve). Every command and redirect in
# them is on §15.5 A5's allow-list (wq_gate); markers go to /dev/kmsg at level 3 and to
# stdout (the unit's wq.log), with the prefix 's1wq:' and 'result=', never 'rc='. WQ_ROOT
# is '' on the board; the self-tests' dry run points it at a fixture tree. No $'..' quote
# and no [[ are used: declare -f prints the first across lines, and the gate refuses both.

# A marker, to the console and to wq.log.
b_wq_mark() {
	printf '<3>s1wq: %s\n' "$1" > "$WQ_KMSG"
	printf 's1wq: %s\n' "$1"
}

# §15.4.3 Phase B steps 2 and 4. $1 home: refuse when $HOME's or KD's storage (resolved
# by Phase A into WQ_HOME_DEV and WQ_KD_DEV) lies under a set member (return 2). $1
# members: each set member's driver link, bus function name, network interface and
# single-child parent port must still be what J-set.conf recorded (return 1 on a mismatch).
b_wq_resolve() {
	local L v path bdf drv d rp
	for L in W X E N; do
		v="WQ_${L}_IN"
		[ "${!v}" = yes ] || continue
		v="WQ_${L}_PATH"
		path="${!v}"
		if [ "$1" = home ]; then
			case "$WQ_HOME_DEV/" in "$path"/*) printf '%s\n' "resolve member=$L home_under=yes"; return 2 ;; esac
			case "$WQ_KD_DEV/" in "$path"/*) printf '%s\n' "resolve member=$L kd_under=yes"; return 2 ;; esac
			continue
		fi
		v="WQ_${L}_DRV"
		drv="${!v}"
		v="WQ_${L}_BDF"
		bdf="${!v}"
		d="$(readlink -e -- "$WQ_ROOT$path/driver" 2> /dev/null)"
		if [ -z "$d" ] || [ "${d##*/}" != "$drv" ]; then
			printf '%s\n' "resolve member=$L driver=${d##*/} result=mismatch"
			return 1
		fi
		if [ "$L" != X ] && [ "${path##*/}" != "$bdf" ]; then
			printf '%s\n' "resolve member=$L function=${path##*/} result=mismatch"
			return 1
		fi
		if [ "$L" = W ] && [ ! -e "$WQ_ROOT$path/net/$WQ_W_NETDEV" ]; then
			printf '%s\n' "resolve member=$L netdev=absent result=mismatch"
			return 1
		fi
		# slot 3 removes WQ_W_MOD: it must still be the bound driver's own module (none: built in)
		if [ "$L" = W ]; then
			rp="$(readlink -e -- "$d/module" 2> /dev/null)"
			rp="${rp##*/}"
			if [ "${rp:-none}" != "$WQ_W_MOD" ]; then
				printf '%s\n' "resolve member=$L module=${rp:-none} result=mismatch"
				return 1
			fi
		fi
		v="WQ_${L}_RPCLEAR"
		if [ "${!v}" = yes ]; then
			v="WQ_${L}_RP"
			rp="${path%/*}"
			if [ "${rp##*/}" != "${!v}" ]; then
				printf '%s\n' "resolve member=$L port=${rp##*/} result=mismatch"
				return 1
			fi
		fi
		printf '%s\n' "resolve member=$L result=ok"
	done
	return 0
}

# §15.4.3's Bus Master read, clear and read-back, the only configuration write. $1 member
# letter (W, E, N), $2 read (J2, or a member not in the set), clear (a set member's slot)
# or check (step 7). The endpoint, then its parent port when J-set.conf marked it a
# single-child port (rp_clear=yes). The clear is only 'setpci -s <BDF> COMMAND=0000:0004',
# with setpci's own read before and after; no dd fallback: without setpci (WQ_SETPCI=no) a
# set bit stays set. A Command register that reads 0xffff (gone, D3cold, link down) is
# unread: no setpci is sent to it. $3, when set, is the slot's deadline in epoch seconds:
# every read and write gets at most 10 s and never runs past it (§15.4.3: the action stays
# inside WQ_STEP_TIMEOUT_S); a read or write the deadline leaves no time for is not made
# (budget=exhausted, unread). Returns 0 every required bit reads 0 (read: every read
# succeeded), 1 a required bit is still set, 2 a read failed.
b_wq_bme() {
	local L="$1" mode="$2" dl="${3:-0}" v path dev b cmdh bit after sb sa rc=0 role t now
	local -a c
	v="WQ_${L}_PATH"
	path="${!v}"
	v="WQ_${L}_RPCLEAR"
	for dev in "$path" "${path%/*}"; do
		role=endpoint
		if [ "$dev" != "$path" ]; then
			[ "${!v}" = yes ] || continue
			role=port
		fi
		t=10
		if [ "$dl" -gt 0 ]; then now="$(date +%s)"; t=$(( dl - now )); [ "$t" -gt 10 ] && t=10; fi
		b=""
		[ "$t" -ge 1 ] && b="$(timeout "$t" od -An -tu1 -j4 -N2 "$WQ_ROOT$dev/config" 2> /dev/null)"
		c=($b)
		if [ "${#c[@]}" != 2 ] || [ "${c[0]}${c[1]}" = 255255 ]; then
			cmdh=unread
			[ "${#c[@]}" = 2 ] && cmdh=0xffff
			[ "$t" -ge 1 ] || cmdh="unread budget=exhausted"
			printf '%s\n' "bme member=$L role=$role mode=$mode dev=${dev##*/} cmd=$cmdh"
			rc=2
			continue
		fi
		printf -v cmdh '0x%04x' $(( c[0] + 256 * c[1] ))
		bit=$(( (c[0] >> 2) & 1 ))
		after="$bit"
		sb=none
		sa=none
		if [ "$mode" = clear ] && [ "$bit" = 1 ] && [ "$WQ_SETPCI" = yes ]; then
			after="unread budget=exhausted"
			if [ "$dl" -gt 0 ]; then now="$(date +%s)"; t=$(( dl - now )); [ "$t" -gt 10 ] && t=10; fi
			[ "$t" -ge 1 ] && sb="$(timeout "$t" setpci -s "${dev##*/}" COMMAND 2> /dev/null)"
			if [ "$dl" -gt 0 ]; then now="$(date +%s)"; t=$(( dl - now )); [ "$t" -gt 10 ] && t=10; fi
			[ "$t" -ge 1 ] && timeout "$t" setpci -s "${dev##*/}" COMMAND=0000:0004 2> /dev/null
			if [ "$dl" -gt 0 ]; then now="$(date +%s)"; t=$(( dl - now )); [ "$t" -gt 10 ] && t=10; fi
			[ "$t" -ge 1 ] && sa="$(timeout "$t" setpci -s "${dev##*/}" COMMAND 2> /dev/null)"
			if [ "$dl" -gt 0 ]; then now="$(date +%s)"; t=$(( dl - now )); [ "$t" -gt 10 ] && t=10; fi
			if [ "$t" -ge 1 ]; then
				b="$(timeout "$t" od -An -tu1 -j4 -N2 "$WQ_ROOT$dev/config" 2> /dev/null)"
				c=($b)
				after=unread
				[ "${#c[@]}" = 2 ] && [ "${c[0]}${c[1]}" != 255255 ] && after=$(( (c[0] >> 2) & 1 ))
			fi
		fi
		printf '%s\n' "bme member=$L role=$role mode=$mode dev=${dev##*/} cmd=$cmdh bme_before=$bit setpci_before=${sb:-empty} setpci_after=${sa:-empty} bme_after=$after"
		[ "$role" = endpoint ] && [ "$mode" = clear ] && printf '%s\n' "bme_after_unbind member=$L value=$bit"
		case "$mode:$after" in
		read:*) ;;
		*:0) ;;
		*:1) rc=1 ;;
		*) [ "$rc" = 1 ] || rc=2 ;;
		esac
	done
	return "$rc"
}

# After each slot and before the issue (§15.4.3 step 5): Oops lines in dmesg since the
# sequence began (b_quiesce's pattern), counted after this sequence's own 'begin' marker, so
# a ring buffer that wraps cannot hide a new line behind an old one; when the marker is no
# longer in the buffer, every matching line counts (fail-safe). WQ_OOPS0, the whole-buffer
# count at the start, is only recorded. Also no task of this unit in D-state or still running
# beside its shell (the slot's process is gone). $1 the check.
b_wq_oops() {
	local n seen r d=0 x=0 p s cg="" l procs=""
	r="$(dmesg 2> /dev/null | {
		n=0
		seen=no
		while IFS= read -r l; do
			case "$l" in
			*"s1wq: begin arm="*) seen=yes; n=0 ;;
			*Oops*|*BUG:*|*"Kernel panic"*|*"Unable to handle kernel"*|*"Internal error"*) n=$(( n + 1 )) ;;
			esac
		done
		printf '%s %s\n' "$n" "$seen"
	})"
	n="${r% *}"
	seen="${r#* }"
	case "$n" in ''|*[!0-9]*) n=unread ;; esac
	while IFS= read -r l; do
		case "$l" in 0::*) cg="${l#0::}" ;; esac
	done < "$WQ_ROOT/proc/self/cgroup"
	[ -n "$cg" ] && procs="$(cat "$WQ_ROOT/sys/fs/cgroup$cg/cgroup.procs" 2> /dev/null)"
	for p in $procs; do
		[ "$p" = "$$" ] && continue
		s="$(ps -o stat= -p "$p" 2> /dev/null)"
		case "$s" in
		*D*) d=$(( d + 1 )) ;;
		?*) x=$(( x + 1 )) ;;
		esac
	done
	printf '%s\n' "oops check=$1 matches_since_begin=$n begin_marker_in_buffer=$seen buffer_base=$WQ_OOPS0 dstate=$d other_tasks=$x cgroup=${cg:-unread}"
	[ "$n" = 0 ] && [ "$d" = 0 ] && [ "$x" = 0 ]
}

# One fixed slot (§15.4.3's table): $1 number, $2 step, $3 member letter. A set member's
# action runs (external commands under timeout WQ_STEP_TIMEOUT_S, the Bus Master reads and
# writes inside one WQ_STEP_TIMEOUT_S deadline; an unbind is a shell write, which no timeout
# can bound, so a hung remove is the fallback's); otherwise result=skip, or a read-only Bus
# Master read under the same deadline. Then the marker, the Oops and D-state check (abort
# reason=oops) and the padding to WQ_SLOT_S, so every arm dwells alike. A slot whose action
# overran WQ_SLOT_S says so on the console too ('overrun slot= s='), in every arm, so a
# dwell mismatch between the arms is visible in the records.
b_wq_slot() {
	local n="$1" step="$2" L="$3" t0 now rem rc v path drv
	t0="$(date +%s)"
	v="WQ_${L}_IN"
	if [ "$step" != "${step%-bme}" ]; then
		v="WQ_${L}_BDF"
		if [ "${!v}" = none ]; then
			rc=skip
		else
			v="WQ_${L}_IN"
			if [ "${!v}" = yes ]; then b_wq_bme "$L" clear "$(( t0 + WQ_STEP_TIMEOUT_S ))"; else b_wq_bme "$L" read "$(( t0 + WQ_STEP_TIMEOUT_S ))"; fi
			rc=$?
		fi
	elif [ "${!v}" != yes ]; then
		rc=skip
	else
		v="WQ_${L}_PATH"
		path="${!v}"
		v="WQ_${L}_DRV"
		drv="${!v}"
		case "$step" in
		wireless-down)
			timeout -k 3 "$WQ_STEP_TIMEOUT_S" ip link set dev "$WQ_W_NETDEV" down
			rc=$?
			;;
		wireless-module)
			if [ "$WQ_W_MOD" = none ]; then
				rc=skip
			else
				timeout -k 3 "$WQ_STEP_TIMEOUT_S" modprobe -r "$WQ_W_MOD"
				rc=$?
			fi
			;;
		xhci-unbind)
			printf '%s\n' "${path##*/}" > "$WQ_ROOT/sys/bus/platform/drivers/$drv/unbind"
			rc=$?
			;;
		*-unbind)
			printf '%s\n' "${path##*/}" > "$WQ_ROOT/sys/bus/pci/drivers/$drv/unbind"
			rc=$?
			;;
		*)
			rc=99
			;;
		esac
		if [ "$rc" = 0 ] && [ "$step" != "${step%-unbind}" ] && [ -n "$(readlink -e -- "$WQ_ROOT$path/driver" 2> /dev/null)" ]; then
			rc=98
		fi
	fi
	b_wq_mark "slot$n $step result=$rc"
	b_wq_oops "slot$n" || b_wq_abort oops
	now="$(date +%s)"
	rem=$(( t0 + WQ_SLOT_S - now ))
	if [ "$rem" -gt 0 ]; then
		sleep "$rem"
	elif [ "$rem" -lt 0 ]; then
		b_wq_mark "overrun slot=$n s=$(( 0 - rem ))"
	fi
}

# §15.4.3 step 11: the issue-time uptime guard. The limit is fixed here, never read from
# the environment; 7,200 s is refused without exception, and so is anything at 1,800 s.
b_wq_uptime() {
	local up rest
	read -r up rest < "$WQ_ROOT/proc/uptime"
	up="${up%%.*}"
	printf '%s\n' "uptime_at_issue_s=${up:-unread} limit_s=1800"
	case "$up" in ''|*[!0-9]*) return 1 ;; esac
	[ "$up" -lt 7200 ] && [ "$up" -lt 1800 ]
}

# §15.4.3 step 11: both cpufreq policies must still read performance.
b_wq_governor_read() {
	local p g rc=0
	for p in policy0 policy4; do
		g="$(cat "$WQ_ROOT/sys/devices/system/cpu/cpufreq/$p/scaling_governor" 2> /dev/null)"
		printf '%s\n' "governor_at_issue_$p=${g:-unread}"
		[ "$g" = performance ] || rc=1
	done
	return "$rc"
}

# §15.4.3 steps 11-12: mark, issue, and only a non-zero rc is 'rejected'. After rc 0 the
# sequence waits WQ_ISSUE_WAIT_S; a system that reads 'stopping' is left to its shutdown
# (R72), anything else is 'kexec did not happen': unload and reboot, exit 5.
b_wq_issue() {
	local rc st
	b_wq_mark "kexec issuing"
	systemctl kexec
	rc=$?
	printf '%s\n' "systemctl_kexec_rc=$rc"
	[ "$rc" = 0 ] || b_wq_abort kexec-rejected
	sleep "$WQ_ISSUE_WAIT_S"
	st="$(systemctl is-system-running 2> /dev/null)"
	printf '%s\n' "after_issue_wait state=${st:-unread}"
	if [ "$st" = stopping ]; then
		b_wq_mark "shutdown in progress"
		exit 0
	fi
	b_wq_mark "kexec did not happen"
	kexec -u
	printf '%s\n' "kexec_unload_rc=$?"
	sync
	systemctl reboot
	printf '%s\n' "reboot_rc=$?"
	exit 5
}

# §15.4.3's abort path: unload, sync, reboot; exit 5. $1 the reason.
b_wq_abort() {
	b_wq_mark "abort reason=$1"
	kexec -u
	printf '%s\n' "kexec_unload_rc=$?"
	sync
	systemctl reboot
	printf '%s\n' "reboot_rc=$?"
	exit 5
}

# §15.4.3's fallback script: idle when the system is already stopping; otherwise fire
# (a bounded dmesg tail into wq.log, unload, sync, reboot), and after 120 s, still not
# stopping, exactly one forced reboot.
b_wq_fallback() {
	local st out
	st="$(systemctl is-system-running 2> /dev/null)"
	printf '%s\n' "fallback state=${st:-unread}"
	if [ "$st" = stopping ]; then
		b_wq_mark "fallback idle shutdown in progress"
		return 0
	fi
	b_wq_mark "fallback firing"
	out="$(dmesg 2> /dev/null)"
	# ${out: -8000} is empty for a shorter buffer, so it is cut only when longer
	[ "${#out}" -gt 8000 ] && out="${out: -8000}"
	printf '%s\n' "fallback dmesg tail begins" "$out" "fallback dmesg tail ends"
	kexec -u
	printf '%s\n' "kexec_unload_rc=$?"
	sync
	systemctl reboot
	printf '%s\n' "reboot_rc=$?"
	sleep 120
	st="$(systemctl is-system-running 2> /dev/null)"
	if [ "$st" != stopping ]; then
		b_wq_mark "fallback forcing"
		systemctl reboot --force
	fi
	return 0
}

# §15.4.3 Phase B, steps 1-12, in order. The slot list is fixed here and is the same in
# every arm (WQ_SLOT_LIST on the PC must equal it: a self-test compares them).
b_wq_main() {
	local s n rc L v t0 now
	sleep "$WQ_START_DELAY_S"
	WQ_OOPS0="$(dmesg 2> /dev/null | grep -cE 'Oops|BUG:|Kernel panic|Unable to handle kernel|Internal error')"
	b_wq_mark "begin arm=$WQ_ARM final=$WQ_FINAL result=0"
	if [ "$WQ_FINAL" = kexec ] && [ "$(cat "$WQ_ROOT/sys/kernel/kexec_loaded" 2> /dev/null)" != 1 ]; then
		b_wq_abort kexec-not-loaded
	fi
	b_wq_resolve home || b_wq_abort home-under-member
	b_pci_state pre
	b_wq_resolve members || b_wq_abort resolve
	for s in 1:wireless-down:W 2:wireless-unbind:W 3:wireless-module:W 4:wireless-bme:W 5:xhci-unbind:X 6:ethernet-unbind:E 7:ethernet-bme:E 8:nvme-unbind:N 9:nvme-bme:N; do
		n="${s%%:*}"
		s="${s#*:}"
		b_wq_slot "$n" "${s%%:*}" "${s#*:}"
	done
	t0="$(date +%s)"
	b_pci_state final
	now="$(date +%s)"
	printf '%s\n' "final_reads_s=$(( now - t0 )) bound_s=$WQ_FINAL_READS_S"
	if [ "$WQ_ARM" != control ]; then
		rc=0
		for L in W E N; do
			v="WQ_${L}_IN"
			[ "${!v}" = yes ] || continue
			b_wq_bme "$L" check || rc=1
		done
		[ "$rc" = 0 ] || b_wq_abort bme-not-cleared
	fi
	b_wq_oops final || b_wq_abort oops
	[ "$WQ_TRACE" = yes ] && b_trace_on
	if [ "$WQ_FINAL" = none ]; then
		b_wq_mark "no final action result=0"
		return 0
	fi
	b_wq_uptime || b_wq_abort uptime
	b_wq_governor_read || b_wq_abort governor
	b_freq final
	b_wq_issue
}

WQ_FUNCS="s1_rl b_freq b_pci_state b_trace_on b_wq_mark b_wq_resolve b_wq_bme b_wq_oops b_wq_slot b_wq_uptime b_wq_governor_read b_wq_issue b_wq_abort b_wq_fallback b_wq_main"
WQ_SLOT_LIST="1:wireless-down:W 2:wireless-unbind:W 3:wireless-module:W 4:wireless-bme:W 5:xhci-unbind:X 6:ethernet-unbind:E 7:ethernet-bme:E 8:nvme-unbind:N 9:nvme-bme:N"
WQ_SLOT_COUNT=9

# ---- Phase A's board reads for the detached sequence (over ssh, not in WQ_FUNCS).

# §15.4.3 step 3: kexec -s -l (J3 too), kexec_loaded, the governor pin and its read-back,
# and the storage chain of $HOME and KD read now (the sequence refuses a member above them).
b_wq_load() {
	local p
	sudo -n kexec -s -l "$K"
	echo "kexec_load_rc=$?"
	echo "kexec_loaded=$(cat /sys/kernel/kexec_loaded)"
	b_governor
	for p in policy0 policy4; do
		echo "governor_final_$p=$(cat /sys/devices/system/cpu/cpufreq/$p/scaling_governor)"
	done
	echo "home=$HOME"
	b_census_path home "$HOME"
	b_census_path kd "$KD"
}

# §15.4.3's rule-5 exception: the sequence's three files in the home directory, and the
# s1wq units systemd still lists (J3's return gate wants none).
b_wq_files() {
	local f
	for f in "$HOME"/*-wq.sh "$HOME"/*-wqfb.sh "$HOME"/*-wq.log; do
		[ -f "$f" ] || continue
		echo "wqfile name=${f##*/} bytes=$(stat -c %s "$f") sha256=$(sha256sum "$f" | cut -d' ' -f1)"
	done
	echo "wqfiles listed"
	systemctl list-units --all --no-legend --plain 's1wq*' </dev/null 2>/dev/null | sed 's/^/wqunit /'
}

# §15.5 A1: the previous boot's console, for an exit-5, F43, F47, F48 or F25w return, named
# -l4t-console-ramoops.log and never a black box. JNAME, set before it, is the file prefix.
b_l4t_console() {
	local f
	case "${JNAME:-}" in ''|[!A-Za-z0-9]*|*[!A-Za-z0-9._-]*) echo "l4tcon refused"; return 0 ;; esac
	f="$HOME/$JNAME-l4t-console-ramoops.log"
	sudo -n cat /sys/fs/pstore/console-ramoops-0 > "$f"
	echo "l4tcon read_rc=$? bytes=$(stat -c %s "$f") sha256=$(sha256sum "$f" | cut -d' ' -f1)"
}

BOARD_FUNCS="b_sha b_identity b_df b_pstore b_freq b_session b_governor b_iomem b_iomem_hi b_dmesg_mark b_dmesg_since b_quiesce b_accept b_dyndbg b_placement b_tree b_slots b_preflight b_kexec_go b_unload b_after b_ramoops_fetch b_rmfiles b_reboot"
BOARD_FUNCS="$BOARD_FUNCS s1_rl b_kpf_snap b_kpf_rm b_pci_state b_census_chain b_census_slaves b_census_path b_census b_trace_on b_j1_probe b_j1_timer"
BOARD_FUNCS="$BOARD_FUNCS b_wq_load b_wq_files b_l4t_console"

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
	s1-j1)     STEP=J6; MODE=host ;;    # jrun sets J6c|J6r after resolve_kimg; run refuses it
	*) die "image '$1' is not an S1 board image (s1-m1b-p6, s1-h1, s1-n1, s1-n2, s1-q2, s1-d1, s1-j1)" ;;
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

# ---------------------------------------------------------------- J diagnostic plumbing (§15.5 A)
#
# Foundations shared by the J diagnostic rungs (j1, j3, jrun control|remove|b2repeat,
# §15.4). The rung command bodies, the detached-sequence generation and the board-side
# wq_* functions are added by later parts; this block gives them the pieces those need:
# the timing constants (above), the decisions-file reader, the pre-registration and
# stamp writers, the dirty-tree and start-margin gates, the used-captures ledger, the
# J capture gate and the J record-directory helper. No function here names a driver,
# address or network: J1 resolves devices at run time from PCI class codes, sysfs
# driver links and the private <rec>/J-set.conf it writes (§15.4.2, §15.5 A1).
#
# SEAMS for parts 2 and 3:
#   - j_step_dir sets JSD (the rung record dir); set SD=$JSD and ON_DIE=run_refused_move
#     to reuse the existing refused-attempt move (<STEP>-refused-<utc>).
#   - the generator passes its slot count to wq_fallback_s / wq_worst_case /
#     wq_constants_line / j_capture_gate, and its slot list and fill-rate factor to
#     j_prereg_write (both default to 'pending' until then).
#   - a rung body calls, in order: need_record_dir; j_read_decisions; j_require the
#     decisions it needs; j_require_clean_tree; j_capture_gate; then per rung the
#     start-margin, fresh-boot and (for jrun) j_prereg_check gates.

j_sha256() { local h; h="$(sha256sum "$1" 2>/dev/null | cut -d' ' -f1)"; echo "${h:--}"; }

# The detached sequence's fallback deadline: start delay + slots + final reads +
# issue wait + a 120 s tail (§15.4.3). $1 the slot count.
wq_fallback_s() { echo $(( WQ_START_DELAY_S + $1 * WQ_SLOT_S + WQ_FINAL_READS_S + WQ_ISSUE_WAIT_S + 120 )); }

# Phase B, from the start delay to systemctl kexec, worst case (§15.4.3): the same
# terms without the 120 s tail. A rung adds its own Phase A bounds for the start margin.
wq_worst_case() { echo $(( WQ_START_DELAY_S + $1 * WQ_SLOT_S + WQ_FINAL_READS_S + WQ_ISSUE_WAIT_S )); }

# The fixed constants, for a J board log (§15.4.3: printed, refused if set in the
# environment). $1 the generator's slot count, or empty before it is known.
wq_constants_line() {
	local slots="${1:-}" fb=pending wc=pending
	if [[ "$slots" =~ ^[0-9]+$ ]]; then fb="$(wq_fallback_s "$slots")"; wc="$(wq_worst_case "$slots")"; fi
	echo "wq_constants start_delay_s=$WQ_START_DELAY_S slot_s=$WQ_SLOT_S step_timeout_s=$WQ_STEP_TIMEOUT_S final_reads_s=$WQ_FINAL_READS_S issue_wait_s=$WQ_ISSUE_WAIT_S slots=${slots:-pending} worst_case_s=$wc fallback_s=$fb"
}

# ---- decisions (§15.6, CONTEXT): <rec>/J-decisions.conf, one KEY=value per line.
# D20-D25 and D25_F25W_CUT are yes|no; D24_SET is max|wireless. A J rung refuses to
# start when the file is missing or a decision it needs is not yes (j_require). The
# file's sha256 goes into J-prereg.log and every J board log's stamps.
declare -A J_DEC=()
J_DEC_LOADED=0

j_decisions_path() { echo "$RECDIR/J-decisions.conf"; }

j_read_decisions() {
	local f line k v
	f="$(j_decisions_path)"
	[ -f "$f" ] || die "no $(basename "$f") in the record directory: the J rungs need the owner's decisions; write one KEY=yes|no per line (D20-D25, D25_F25W_CUT; D24_SET=max|wireless) first (§15.6)"
	J_DEC=()
	while IFS= read -r line || [ -n "$line" ]; do
		line="${line%$'\r'}"
		case "$line" in ''|'#'*) continue ;; esac
		[[ "$line" =~ ^[A-Z0-9_]+=[a-z]+$ ]] || die "$(basename "$f"): line '$line' is not KEY=value (a lowercase value); fix it"
		k="${line%%=*}"; v="${line#*=}"
		case "$k" in
		D20|D21|D22|D23|D24|D25|D25_F25W_CUT)
			case "$v" in yes|no) ;; *) die "$(basename "$f"): $k must be yes or no, not '$v'" ;; esac ;;
		D24_SET)
			case "$v" in max|wireless) ;; *) die "$(basename "$f"): D24_SET must be max or wireless, not '$v'" ;; esac ;;
		*) die "$(basename "$f"): unknown decision key '$k' (allowed: D20-D25, D25_F25W_CUT, D24_SET)" ;;
		esac
		J_DEC["$k"]="$v"
	done < "$f"
	J_DEC_LOADED=1
}

# The value of one decision, or empty. $1 the key.
j_decision() { printf '%s\n' "${J_DEC[$1]:-}"; }

# Dies unless the named yes|no decision is present and yes. $1 the key, $2 what it gates.
j_require() {
	[ "$J_DEC_LOADED" = 1 ] || j_read_decisions
	[ "${J_DEC[$1]:-}" = yes ] || die "decision $1 is '${J_DEC[$1]:-unset}', not yes: $2 needs it (set $1=yes in $(basename "$(j_decisions_path)") only when the owner has taken it, §15.6)"
}

# The removal set the owner chose (D24_SET): max or wireless. Dies if unset.
j_decision_set() {
	[ "$J_DEC_LOADED" = 1 ] || j_read_decisions
	case "${J_DEC[D24_SET]:-}" in
	max|wireless) printf '%s\n' "${J_DEC[D24_SET]}" ;;
	*) die "D24_SET is '${J_DEC[D24_SET]:-unset}', not max or wireless: J4's removal set needs it (§15.6 D24)" ;;
	esac
}

# ---- clean-tree, stamps and pre-registration (§15.4.1, §15.5 A1)

# 0 if git in GITDIR reports every given path clean (no modification, staging or
# untracked state); 1 otherwise. A path that does not exist is skipped (kpf-decode.py
# is added by a later part). GITDIR outside a work tree is treated as clean (no gate).
git_paths_clean() {
	local gitdir="$1" f rc=0
	shift
	git -C "$gitdir" rev-parse --show-toplevel >/dev/null 2>&1 || return 0
	for f in "$@"; do
		[ -e "$f" ] || continue
		[ -n "$(git -C "$gitdir" status --porcelain -- "$f" 2>/dev/null)" ] && rc=1
	done
	return "$rc"
}

# The tracked files whose clean state and sha256 the J stamps record (§15.4.1).
j_tree_clean() { git_paths_clean "$HERE" "$HERE/$PROG" "$S1DIR/kpf-decode.py" "$PARSER"; }

# Dies if any tracked file is uncommitted (§15.5 A1: a J rung runs committed code so the
# J-prereg.log stamps mean something). $1 what.
j_require_clean_tree() {
	j_tree_clean || die "the working tree is dirty for s1-board.sh, kpf-decode.py or parse-s1.py: ${1:-a J rung} must run committed code (§15.5 A1). Commit or stash first"
}

# The stamp lines for a J board log (§15.5 A1 'Stamps'). $1 the generator's slot count
# (empty before it is known). Records HEAD, the tracked files' sha256, the clean-tree
# result, the decisions- and prereg-file sha256, and the fixed timing constants.
j_stamps() {
	local slots="${1:-}" head
	head="$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"
	echo "stamp head=$head"
	echo "stamp s1-board.sh sha256=$(j_sha256 "$HERE/$PROG")"
	echo "stamp kpf-decode.py sha256=$(j_sha256 "$S1DIR/kpf-decode.py")"
	echo "stamp parse-s1.py sha256=$(j_sha256 "$PARSER")"
	echo "stamp tree=$(j_tree_clean && echo clean || echo DIRTY)"
	echo "stamp decisions_sha256=$(j_sha256 "$(j_decisions_path)")"
	echo "stamp prereg_sha256=$(j_sha256 "$RECDIR/J-prereg.log")"
	wq_constants_line "$slots"
}

# §15.4.1: the pre-registration written before J2, cited by every J run note. It holds
# only file basenames, hashes and decision letters (no identifier), so it is written
# without redaction to keep its integrity hashes byte-exact. The slot list defaults to
# §15.4.3's fixed WQ_SLOT_LIST; the fill-rate factor is J6's (§15.5 B) and stays 'pending'.
# The member lines' own hash (set_members) is what jrun and j3 compare later: j3 appends its
# wireless-only fallback line to J-set.conf, which is pre-registered and changes no member.
j_prereg_write() {
	local slot_list="${1:-${WQ_SLOT_LIST// /,}}" factor="${2:-pending}" stage="${3:-j1}" trace="${4:-pending}" f rule k
	f="$RECDIR/J-prereg.log"
	rule="${S1_J_RULE_FILE:-}"
	if [ "$stage" = j2 ] && { [ -z "$rule" ] || [ ! -f "$rule" ]; }; then
		die "S1_J_RULE_FILE must name a copy of §15.6's rule text: its sha256 is part of the J2 pre-registration (§15.4.1, C18)"
	fi
	{
		echo "# J-prereg.log: pre-registration for the J diagnostic rungs (§15.4.1)"
		echo "# written by orin-native/startup/$PROG at $(iso_now); evaluation output, NC QDL v7 4.6(i), unpublished"
		echo "prereg stage=$stage"
		echo "prereg trace=$trace"
		echo "prereg head=$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"
		echo "prereg tree=$(j_tree_clean && echo clean || echo DIRTY)"
		echo "prereg s1-board.sh sha256=$(j_sha256 "$HERE/$PROG")"
		echo "prereg kpf-decode.py sha256=$(j_sha256 "$S1DIR/kpf-decode.py")"
		echo "prereg parse-s1.py sha256=$(j_sha256 "$PARSER")"
		if [ -n "$rule" ] && [ -f "$rule" ]; then
			echo "prereg rule_text=$(basename "$rule") sha256=$(j_sha256 "$rule")"
		else
			echo "prereg rule_text=unset (set S1_J_RULE_FILE to a copy of §15.6's rule text)"
		fi
		echo "prereg set_file sha256=$(j_sha256 "$RECDIR/J-set.conf")"
		echo "prereg set_members sha256=$(j_set_members_sha)"
		echo "prereg removal_set=$(j_decision D24_SET) members_in_set=$(j_set_in_members) fallback=wireless (§15.4.3, pre-registered)"
		echo "prereg decisions sha256=$(j_sha256 "$(j_decisions_path)")"
		echo "prereg slot_list=$slot_list"
		echo "prereg fill_rate_factor=$factor"
		for k in D20 D21 D22 D23 D24 D24_SET D25 D25_F25W_CUT; do
			echo "prereg $k=$(j_decision "$k")"
		done
	} > "$f"
	check_private "$f"
}

# The stage J-prereg.log was last appended at: j1 (J1's draft), j2 (the pre-registration), j6
# (J6's stage, appended after it by j6_prereg_append), or empty.
j_prereg_stage() { sed -n 's/^prereg stage=//p' "$RECDIR/J-prereg.log" 2>/dev/null | tail -n 1; }

# 0 when J-prereg.log holds a 'prereg stage=$1' line. The J2 pre-registration is recognised by its
# line, not by being the last stage, so J6's appended stage never makes it look unwritten.
j_prereg_has_stage() { grep -qx "prereg stage=$1" "$RECDIR/J-prereg.log" 2>/dev/null; }

# Verifies J-prereg.log is the J2 pre-registration and still describes the current harness
# (§15.4.1): the stage, s1-board.sh, the set's member lines, D24_SET, the rule text (set, and
# S1_J_RULE_FILE's hash equal to it), kpf-decode.py, parse-s1.py and the decisions file; dies
# otherwise. Every jrun and j3 cites it. For $1 s1-j1 and $2 the arm it reads s1-board.sh,
# kpf-decode.py and parse-s1.py from that arm's J6 stage instead of J2's lines, and checks the
# stage against the harness and the image (j6_prereg_verify). Echoes the prereg's own sha256.
j_prereg_check() {
	local f pre cur img="${1:-}" arm="${2:-}" j6=""
	f="$RECDIR/J-prereg.log"
	[ -f "$f" ] || die "no J-prereg.log in the record directory: run the pre-registration before the first J kexec run (§15.4.1)"
	j_prereg_has_stage j2 \
		|| die "J-prereg.log is J1's draft, not the J2 pre-registration: jrun control (or, after J1's F42 row, jrun b2repeat) writes it first (§15.4.1)"
	# a later stage (J6's) is appended after J2's, never before it
	awk '$0 == "prereg stage=j2" && !j2 { j2 = NR } /^prereg stage=j6$/ && !j6 { j6 = NR } END { exit !(j6 == 0 || (j2 > 0 && j6 > j2)) }' "$f" \
		|| die "J-prereg.log holds a J6 stage before the J2 pre-registration: the file was not appended in order (§15.4.1)"
	# an s1-j1 run reads its harness hashes from its own J6 stage (j6_prereg_verify): J2's lines keep
	# describing the harness the s1-h1 arms ran and are never re-anchored by J6
	if [ "$img" != s1-j1 ]; then
		pre="$(sed -n 's/^prereg s1-board.sh sha256=//p' "$f" | tail -n 1)"
		cur="$(j_sha256 "$HERE/$PROG")"
		[ "$pre" = "$cur" ] || die "J-prereg.log recorded s1-board.sh sha256=$pre, but it is now $cur: re-register, or restore the pre-registered harness (§15.4.1)"
	fi
	pre="$(sed -n 's/^prereg set_members sha256=//p' "$f" | tail -n 1)"
	cur="$(j_set_members_sha)"
	[ "$pre" = "$cur" ] || die "J-prereg.log recorded J-set.conf's member lines as sha256=${pre:-none}, but they are now $cur: the removal set changed after the pre-registration (§15.4.1)"
	pre="$(sed -n 's/^prereg D24_SET=//p' "$f" | tail -n 1)"
	[ "$pre" = "$(j_decision D24_SET)" ] || die "J-prereg.log recorded D24_SET=${pre:-unset}, but J-decisions.conf now says $(j_decision D24_SET): the removal set is pre-registered (§15.4.1)"
	pre="$(sed -n 's/^prereg rule_text=[^ ]* sha256=//p' "$f" | tail -n 1)"
	[[ "$pre" =~ ^[0-9a-f]{64}$ ]] || die "J-prereg.log holds no rule text hash: §15.6's rule must be registered before J2 (§15.4.1, C18)"
	[ -n "${S1_J_RULE_FILE:-}" ] && [ -f "$S1_J_RULE_FILE" ] \
		|| die "S1_J_RULE_FILE must name the copy of §15.6's rule text registered in J-prereg.log (§15.4.1)"
	cur="$(j_sha256 "$S1_J_RULE_FILE")"
	[ "$pre" = "$cur" ] || die "J-prereg.log registered the rule text as sha256=$pre, but S1_J_RULE_FILE is now $cur: the rule is fixed before any result (§15.4.1, C18)"
	for cur in kpf-decode.py:"$S1DIR/kpf-decode.py" parse-s1.py:"$PARSER" decisions:"$(j_decisions_path)"; do
		[ "$img" = s1-j1 ] && [ "${cur%%:*}" != decisions ] && continue
		pre="$(sed -n "s/^prereg ${cur%%:*} sha256=//p" "$f" | tail -n 1)"
		[ "$pre" = "$(j_sha256 "${cur#*:}")" ] \
			|| die "J-prereg.log recorded ${cur%%:*} as sha256=${pre:-none}, but it is now $(j_sha256 "${cur#*:}"): re-register, or restore the pre-registered file (§15.4.1)"
	done
	if [ "$img" = s1-j1 ]; then
		j6="$(j6_prereg_verify "$arm")" || exit 1
	fi
	j_require_clean_tree "a J run"
	echo "prereg ok sha256=$(j_sha256 "$f")${j6:+ $j6}"
}

# ---- J6's pre-registration stage (§15.4.1, §15.4.8, §15.5 B)
#
# Appended to J-prereg.log by the first jrun s1-j1 attempt of each arm, after gate A and before
# anything is read from the board, and never rewritten: its own 'prereg j6' hashes of the three
# tracked files and of WQ_FUNCS, the parse-s1.py hash (the J6 rows are its code), the memcanary-w
# pin, the hold size and its margin, the fill-rate factor, the arm, and the image's params and
# kimg hashes. It never re-emits J2's 'prereg <file> sha256=' lines, so the s1-h1 checks above keep
# reading J2's registration and its dated amendments. When the harness differs from that
# registration the stage opens with an amendment line that the owner names (S1_J6_AMEND_BY), and an
# s1-j1 run is checked against its own arm's stage only (j6_prereg_block). The rule text, the set,
# the decisions and the trace are not re-emitted and stay J2's.

# make-s1-images.sh, whose PIN_MEMCANARY_W, J1_HOLD_MIB and J1_HOLD_MARGIN_MIB the stage records.
# Not read from the environment; only the self-tests point it at a synthetic copy, in-process.
J6_GENERATOR="$HERE/make-s1-images.sh"

# One NAME=value constant line of the generator. $1 the name.
j6_gen_const() { sed -n "s/^$1=\\([0-9A-Za-z_-]*\\)\$/\\1/p" "$J6_GENERATOR" 2>/dev/null | tr -d '\r' | head -n 1; }

# parse-s1.py's J1_HOLD_MIB (its own constant, which the generator's constant check compares).
j6_parser_hold() { sed -n 's/^J1_HOLD_MIB = \([0-9][0-9]*\)\([^0-9].*\)\{0,1\}$/\1/p' "$PARSER" 2>/dev/null | tr -d '\r' | head -n 1; }

# 0 when $1 is a fill-rate factor parse-s1.py accepts: a plain decimal, 1 or above.
j6_factor_ok() {
	[[ "$1" =~ ^[0-9]+(\.[0-9]+)?$ ]] || return 1
	awk -v f="$1" 'BEGIN { exit !(f + 0 >= 1) }'
}

# One key's value from an s1-j1 params file. $1 the file, $2 the key.
j6_pkey() { awk -F= -v k="$2" '$1 == k { print substr($0, length(k) + 2); exit }' "$1" 2>/dev/null | tr -d '\r'; }

# The values J6's stage and its check compare, from the s1-j1 params file $1: dies unless the file
# is s1-j1's (rung, host mode, diag j1), the pin is a real sha256 equal to the generator's, the
# hold size equals the generator's and parse-s1.py's, and the guard and return bound are the
# generator's shape (the guard at most 3,600 s, the return bound at least the guard + 300 s).
# Sets J6_PIN, J6_HOLD, J6_MARGIN, J6_HOLD_T, J6_GUARD.
j6_params_values() {
	local p="$1" v
	[ -f "$p" ] || die "no s1-j1.params under S1_KIMG_DIR: build s1-j1 with make-s1-images.sh (§15.5 B9)"
	[ "$(j6_pkey "$p" rung)" = s1-j1 ] && [ "$(j6_pkey "$p" mode)" = host ] && [ "$(j6_pkey "$p" diag)" = j1 ] \
		|| die "s1-j1.params is not the watcher's (rung=$(j6_pkey "$p" rung) mode=$(j6_pkey "$p" mode) diag=$(j6_pkey "$p" diag); want s1-j1, host, j1)"
	J6_PIN="$(j6_pkey "$p" memcanary_w_sha256)"
	[[ "$J6_PIN" =~ ^[0-9a-f]{64}$ ]] || die "s1-j1.params' memcanary_w_sha256 is '${J6_PIN:-missing}', not a sha256 (§15.5 B9)"
	v="$(j6_gen_const PIN_MEMCANARY_W)"
	[ "$v" = "$J6_PIN" ] || die "make-s1-images.sh's PIN_MEMCANARY_W is '${v:-missing}', not s1-j1.params' $J6_PIN: rebuild s1-j1 from the committed pin (§15.5 B9)"
	J6_HOLD="$(j6_pkey "$p" j1_hold_mib)"
	[[ "$J6_HOLD" =~ ^[1-9][0-9]*$ ]] || die "s1-j1.params' j1_hold_mib is '${J6_HOLD:-missing}', not a whole number of MiB"
	v="$(j6_gen_const J1_HOLD_MIB)"
	[ "$v" = "$J6_HOLD" ] || die "make-s1-images.sh's J1_HOLD_MIB is '${v:-missing}', not s1-j1.params' $J6_HOLD (§15.4.8)"
	v="$(j6_parser_hold)"
	[ "$v" = "$J6_HOLD" ] || die "parse-s1.py's J1_HOLD_MIB is '${v:-missing}', not s1-j1.params' $J6_HOLD: the parser would judge another hold (§15.5 B7)"
	J6_MARGIN="$(j6_gen_const J1_HOLD_MARGIN_MIB)"
	[[ "$J6_MARGIN" =~ ^[0-9]+$ ]] || die "make-s1-images.sh has no whole-number J1_HOLD_MARGIN_MIB (D27: the hold margin is recorded before J6)"
	J6_HOLD_T="$(j6_pkey "$p" j1_hold_t)"
	[[ "$J6_HOLD_T" =~ ^[0-9]+$ ]] || die "s1-j1.params has no whole-number j1_hold_t"
	J6_GUARD="$(j6_pkey "$p" guard_s)"
	v="$(j6_pkey "$p" return_bound_s)"
	[[ "$J6_GUARD" =~ ^[0-9]+$ ]] && [[ "$v" =~ ^[0-9]+$ ]] && (( J6_GUARD <= 3600 && v >= J6_GUARD + 300 )) \
		|| die "s1-j1.params' guard_s=${J6_GUARD:-missing} and return_bound_s=${v:-missing} are not the generator's shape (guard <= 3600 s, return bound >= guard + 300 s)"
	return 0
}

# The registered fill-rate factor (J6's stages hold one for the revision), or empty.
j6_prereg_factor() { sed -n 's/^prereg j6 fill_rate_factor=//p' "$RECDIR/J-prereg.log" 2>/dev/null | tail -n 1; }

# 0 when a complete J6 stage for arm $1 is in J-prereg.log (its last line, 'prereg j6 arm=', written).
j6_prereg_has_arm() { grep -qx "prereg j6 arm=$1" "$RECDIR/J-prereg.log" 2>/dev/null; }

# The newest complete J6 stage for arm $1: its lines from 'prereg stage=j6' to 'prereg j6 arm=$1'.
# A stage that ends in the other arm's line is not this arm's, whatever follows it.
j6_prereg_block() {
	awk -v want="prereg j6 arm=$1" '
		{ sub(/\r$/, "") }
		$0 == "prereg stage=j6" { buf = ""; open = 1 }
		open { buf = buf $0 "\n" }
		open && $0 == want { last = buf; open = 0 }
		open && /^prereg j6 arm=/ { open = 0 }
		END { printf "%s", last }' "$RECDIR/J-prereg.log" 2>/dev/null
}

# One value of arm $1's J6 stage: the rest of its newest line that starts with $2.
j6_block_value() { j6_prereg_block "$1" | sed -n "s/^$2//p" | tail -n 1; }

# WQ_FUNCS' definitions in file $1 ('-' for stdin), in WQ_FUNCS order: each from its 'name() {'
# line to the first line that is '}', or that one line when it ends in '; }'. The detached
# sequence of J2 and J4 was generated from these (declare -f, §15.5 A5).
j6_wq_text() {
	awk -v names="$WQ_FUNCS" '
		BEGIN { n = split(names, a, " "); for (i = 1; i <= n; i++) want[a[i]] = 1 }
		{ sub(/\r$/, "") }
		cur != "" { txt[cur] = txt[cur] "\n" $0; if ($0 == "}") cur = ""; next }
		match($0, /^[A-Za-z0-9_]+\(\) \{/) {
			nm = substr($0, 1, index($0, "(") - 1)
			if ((nm in want) && !(nm in txt)) { txt[nm] = $0; if ($0 !~ /; \}$/) cur = nm }
		}
		END { for (i = 1; i <= n; i++) print txt[a[i]] }' "${1:--}"
}

# sha256 of WQ_FUNCS' text in this s1-board.sh.
j6_wq_sha() { j6_wq_text "$HERE/$PROG" | sha256sum | cut -d' ' -f1; }

# sha256 of WQ_FUNCS' text in s1-board.sh as committed at $1, or '-' when git cannot show it.
j6_wq_sha_at() {
	local t h
	[ -n "$1" ] || { echo -; return 0; }
	t="$(git -C "$HERE" show "$1:orin-native/startup/$PROG" 2>/dev/null)" && [ -n "$t" ] || { echo -; return 0; }
	h="$(printf '%s\n' "$t" | j6_wq_text - | sha256sum | cut -d' ' -f1)"
	echo "${h:--}"
}

# The newest commit J-prereg.log registers: J2's 'prereg head=', or a later amendment's 'commit='.
j6_registered_commit() {
	awk '{ sub(/\r$/, "") }
		/^prereg head=/ { c = substr($0, 13) }
		/^prereg amendment / && match($0, / commit=[0-9a-f]+/) { c = substr($0, RSTART + 8, RLENGTH - 8) }
		END { print c }' "$RECDIR/J-prereg.log" 2>/dev/null
}

# 0 when arm $1's J6 stage still describes this harness and image: the three tracked files and
# WQ_FUNCS, the memcanary-w pin, the hold size, and the params and kimg hashes. j6_params_values has
# set J6_PIN and J6_HOLD. $2 the s1-j1 directory.
j6_stage_matches() {
	local arm="$1" dir="$2" k
	for k in s1-board.sh:"$HERE/$PROG" kpf-decode.py:"$S1DIR/kpf-decode.py" parse-s1.py:"$PARSER"; do
		[ "$(j6_block_value "$arm" "prereg j6 ${k%%:*} sha256=")" = "$(j_sha256 "${k#*:}")" ] || return 1
	done
	[ "$(j6_block_value "$arm" 'prereg j6 wq_funcs sha256=')" = "$(j6_wq_sha)" ] || return 1
	[ "$(j6_block_value "$arm" 'prereg j6 pin_memcanary_w=')" = "$J6_PIN" ] || return 1
	[ "$(j6_block_value "$arm" 'prereg j6 hold_mib=' | cut -d' ' -f1)" = "$J6_HOLD" ] || return 1
	[ "$(j6_block_value "$arm" 'prereg j6 params sha256=')" = "$(j_sha256 "$dir/s1-j1.params") kimg_sha256=$(j_sha256 "$dir/s1-j1.kimg")" ]
}

# 0 when a board log of J step $1 exists other than this attempt's own ($REC, opened before gate A):
# an earlier attempt of the arm got past its refusals, so its stage may no longer be superseded.
# A refused attempt's records were moved to <step>-refused-<utc> and are not counted.
j6_arm_has_run() {
	local f
	for f in "$RECDIR/$1"/*-board.log "$RECDIR/$1"-a[0-9]*/*-board.log; do
		[ -f "$f" ] && [ "$f" != "${REC:-}" ] && return 0
	done
	return 1
}

# Appends J6's stage for arm $1 (control|remove); an attempt of an arm whose stage still matches
# (j6_stage_matches) appends nothing. Needs the J2 pre-registration, a clean tree (the caller's
# gate), the s1-j1 params and kimg, and the factor: S1_J6_FILL_FACTOR on the first stage; for any
# later stage it must be unset or equal the one already registered (one factor for the revision).
# J2's 'prereg <file> sha256=' lines are never re-emitted, so every s1-h1 check keeps reading J2's
# registration and its dated amendments. The stage is an amendment when a tracked file differs from
# that registration, when WQ_FUNCS differs from the registered commit's, or when it supersedes an
# earlier stage of the arm that no longer matches (allowed only while the arm has no board log).
# Then S1_J6_AMEND_BY=owner-<decision> must name the owner's decision, a WQ_FUNCS change also needs
# S1_J6_WQ_CHANGED=yes, and the stage opens with an amendment line in the D34 and J3 form (by=,
# commit=, reason=, old -> new per changed file).
j6_prereg_append() {
	local arm="$1" f="$RECDIR/J-prereg.log" dir="${S1_KIMG_DIR:-$HERE/../shim/out/s1}" factor old step k pre cur
	local amend="" supersede="" commit wq_old wq_cur wq_note by="${S1_J6_AMEND_BY:-}"
	case "$arm" in control) step=J6c ;; remove) step=J6r ;; *) die "j6_prereg_append: no J6 arm '$arm'" ;; esac
	j_prereg_has_stage j2 || die "J-prereg.log holds no J2 pre-registration: J6's stage is appended after it (§15.4.1)"
	j6_params_values "$dir/s1-j1.params"
	[ -f "$dir/s1-j1.kimg" ] || die "no s1-j1.kimg under S1_KIMG_DIR"
	if j6_prereg_has_arm "$arm"; then
		j6_stage_matches "$arm" "$dir" && return 0
		! j6_arm_has_run "$step" \
			|| die "J6's $arm stage no longer matches the harness or the image, and a $step board log exists: a stage is superseded only before its arm's first run (§15.4.1); the owner decides"
		supersede="$(j6_block_value "$arm" 'prereg j6 utc=' | cut -d' ' -f1)"
	fi
	old="$(j6_prereg_factor)"
	factor="${S1_J6_FILL_FACTOR:-$old}"
	[ -n "$factor" ] || die "S1_J6_FILL_FACTOR is unset: the fill-rate factor of §15.4.8's row is pre-registered by the first J6 attempt (§15.4.1)"
	j6_factor_ok "$factor" || die "S1_J6_FILL_FACTOR='$factor' is not a decimal of 1 or above (parse-s1.py --fill-factor)"
	[ -z "$old" ] || [ "$old" = "$factor" ] \
		|| die "S1_J6_FILL_FACTOR=$factor differs from the fill-rate factor $old already registered for J6: one factor holds for the revision (§15.4.1)"
	for k in s1-board.sh:"$HERE/$PROG" kpf-decode.py:"$S1DIR/kpf-decode.py" parse-s1.py:"$PARSER"; do
		pre="$(sed -n "s/^prereg ${k%%:*} sha256=//p" "$f" | tail -n 1)"
		cur="$(j_sha256 "${k#*:}")"
		[ "$pre" = "$cur" ] || amend="$amend; ${k%%:*} sha256 ${pre:-none} -> $cur"
	done
	commit="$(j6_registered_commit)"
	wq_old="$(j6_wq_sha_at "$commit")"
	wq_cur="$(j6_wq_sha)"
	wq_note="wq_funcs unchanged since ${commit:-unknown}"
	if [ "$wq_old" != "$wq_cur" ]; then
		[ "${S1_J6_WQ_CHANGED:-}" = yes ] \
			|| die "WQ_FUNCS, the detached sequence J2 and J4 ran, differs from the registered commit ${commit:-unknown} (or git cannot show it): J6 would not repeat J2's sequence (§15.4.3). Only the owner names that change, with S1_J6_WQ_CHANGED=yes and S1_J6_AMEND_BY"
		wq_note="wq_funcs changed, named by the owner"
		amend="$amend; wq_funcs sha256 $wq_old -> $wq_cur"
	fi
	if [ -n "$amend$supersede" ]; then
		[[ "$by" =~ ^owner-[A-Za-z0-9._-]{1,40}$ ]] \
			|| die "J6's $arm stage is an amendment (${amend#; }${supersede:+${amend:+; }it supersedes the stage of $supersede}): name the owner's decision with S1_J6_AMEND_BY=owner-<decision>, as the D34 and J3 amendments were (§15.4.1)"
	fi
	{
		echo "prereg stage=j6"
		[ -z "$amend$supersede" ] \
			|| echo "prereg amendment utc=$(utc_now) by=$by commit=$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown) reason=J6's stage for the $arm arm${supersede:+, superseding the stage of $supersede}; J2's harness lines are not re-emitted, so the s1-h1 checks are unchanged; rule text, set, decisions and trace unchanged; $wq_note$amend"
		echo "prereg j6 utc=$(utc_now) step=$step image=s1-j1 by=${by:-first-attempt} reason=J6's pre-registration before its first run"
		echo "prereg j6 head=$(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"
		echo "prereg j6 tree=$(j_tree_clean && echo clean || echo DIRTY)"
		echo "prereg j6 s1-board.sh sha256=$(j_sha256 "$HERE/$PROG")"
		echo "prereg j6 kpf-decode.py sha256=$(j_sha256 "$S1DIR/kpf-decode.py")"
		echo "prereg j6 parse-s1.py sha256=$(j_sha256 "$PARSER")"
		echo "prereg j6 wq_funcs sha256=$wq_cur"
		echo "prereg j6 pin_memcanary_w=$J6_PIN"
		echo "prereg j6 hold_mib=$J6_HOLD hold_margin_mib=$J6_MARGIN hold_t_s=$J6_HOLD_T guard_s=$J6_GUARD"
		echo "prereg j6 fill_rate_factor=$factor"
		echo "prereg j6 params sha256=$(j_sha256 "$dir/s1-j1.params") kimg_sha256=$(j_sha256 "$dir/s1-j1.kimg")"
		echo "prereg j6 waivers sha256=$(j_sha256 "$RECDIR/J-waivers.conf")"
		echo "prereg j6 arm=$arm"
	} >> "$f"
	check_private "$f"
	note "J-prereg.log: J6's stage for the $arm arm appended (fill_rate_factor=$factor$([ -n "$amend$supersede" ] && echo ", an amendment by $by")); it is never rewritten by the harness (§15.4.1)"
}

# Checks arm $1's J6 stage (the newest that ends in its arm line, j6_prereg_block) against the
# harness and image about to run (§15.4.1): parse-s1.py (J6's rows are its code), s1-board.sh,
# kpf-decode.py, WQ_FUNCS, the memcanary-w pin, the hold size, the params and the kimg, and the
# factor. It never reads another arm's stage. Dies otherwise; prints one 'j6' summary.
j6_prereg_verify() {
	local arm="$1" dir="${S1_KIMG_DIR:-$HERE/../shim/out/s1}" pre factor k
	case "$arm" in control|remove) ;; *) die "J6 runs in the control or remove arm, not '${arm:-none}'" ;; esac
	j_prereg_has_stage j6 && j6_prereg_has_arm "$arm" \
		|| die "J-prereg.log holds no J6 stage for the $arm arm: jrun s1-j1 $arm appends it before its first run (§15.4.1)"
	pre="$(j6_block_value "$arm" 'prereg j6 parse-s1.py sha256=')"
	[ "$pre" = "$(j_sha256 "$PARSER")" ] \
		|| die "J6's $arm stage registered parse-s1.py as sha256=${pre:-none}, but it is now $(j_sha256 "$PARSER"): J6's rows are that code, fixed before any result (§15.4.1)"
	for k in s1-board.sh:"$HERE/$PROG" kpf-decode.py:"$S1DIR/kpf-decode.py"; do
		pre="$(j6_block_value "$arm" "prereg j6 ${k%%:*} sha256=")"
		[ "$pre" = "$(j_sha256 "${k#*:}")" ] \
			|| die "J6's $arm stage registered ${k%%:*} as sha256=${pre:-none}, but it is now $(j_sha256 "${k#*:}"): restore the registered file, or supersede the stage under S1_J6_AMEND_BY before the arm's first run (§15.4.1)"
	done
	pre="$(j6_block_value "$arm" 'prereg j6 wq_funcs sha256=')"
	[ "$pre" = "$(j6_wq_sha)" ] \
		|| die "J6's $arm stage registered WQ_FUNCS as sha256=${pre:-none}, but this harness's is $(j6_wq_sha): the detached sequence changed after the pre-registration (§15.4.1, §15.4.3)"
	j6_params_values "$dir/s1-j1.params"
	pre="$(j6_block_value "$arm" 'prereg j6 pin_memcanary_w=')"
	[ "$pre" = "$J6_PIN" ] || die "J6's $arm stage registered PIN_MEMCANARY_W=${pre:-none}, but s1-j1.params now carries $J6_PIN (§15.4.1)"
	pre="$(j6_block_value "$arm" 'prereg j6 hold_mib=' | cut -d' ' -f1)"
	[ "$pre" = "$J6_HOLD" ] || die "J6's $arm stage registered hold_mib=${pre:-none}, but s1-j1.params now says $J6_HOLD (§15.4.1)"
	pre="$(j6_block_value "$arm" 'prereg j6 params sha256=')"
	[ "$pre" = "$(j_sha256 "$dir/s1-j1.params") kimg_sha256=$(j_sha256 "$dir/s1-j1.kimg")" ] \
		|| die "J6's $arm stage registered other s1-j1.params and s1-j1.kimg hashes than the ones under S1_KIMG_DIR: the image changed after its pre-registration (§15.4.1)"
	factor="$(j6_block_value "$arm" 'prereg j6 fill_rate_factor=')"
	j6_factor_ok "$factor" || die "J6's $arm stage holds no usable fill-rate factor ('${factor:-none}')"
	[ "$factor" = "$(j6_prereg_factor)" ] \
		|| die "J6's $arm stage registered fill-rate factor $factor, but a later stage holds $(j6_prereg_factor): one factor holds for the revision (§15.4.1)"
	[ -z "${S1_J6_FILL_FACTOR:-}" ] || [ "$S1_J6_FILL_FACTOR" = "$factor" ] \
		|| die "S1_J6_FILL_FACTOR=$S1_J6_FILL_FACTOR differs from the registered fill-rate factor $factor: unset it (§15.4.1)"
	echo "j6_arm=$arm fill_rate_factor=$factor hold_mib=$J6_HOLD pin_memcanary_w=registered"
}

# §15.5 A4 for the J records: rec() redacts every board-log line, and J-set.conf is redacted in
# place, so an SSID that is part of a line the harness reads back from its own records would be
# rewritten to <ssid> there (a cut hold, an offset, a ladder row, a member value). These are
# those lines' fixed words; a record's numbers are guarded by refusing an SSID of digits and
# separators only. Prints the refusal, or nothing when the SSID is usable. $1 the SSID.
J_READBACK_TEXT="run com3_log= com3_bytes_before_kexec= j3 com3_log= com3_bytes_before_arm= wq_armed armed_epoch= wq_fallback_s= jrun j1 p1 reboot NO RETURN within next=J2b trace=go trace=no-go trace=off RESULT MET wireless-only NOT MET S1PC j_row= set in_this_arm= trace=yes wq.sh wqfb.sh sha256= fallback=wireless set_version= set_rule=max member=wireless member=xhci member=ethernet member=nvme candidates= subsystem=pci subsystem=platform bdf= path=/sys/devices/ driver= module= netdev= root_port= root_port_children= rp_clear=yes mounted_descendant= home_or_kd_under= in_set=yes in_set=no reason=ok note=no-j3-j4 tools systemd_run= setpci=yes none"
ssid_refusal() {
	local s="$1"
	if [ "${#s}" -lt 3 ]; then echo "S1_REDACT_SSID is unset or under 3 bytes (mandatory for J rungs, §15.5 A4)"; return 0; fi
	case "$s" in
	*[!0-9.:,_-]*) ;;
	*) echo "S1_REDACT_SSID holds only digits and separators: its redaction would rewrite numbers the harness reads back from its own records (§15.5 A4); the owner decides"; return 0 ;;
	esac
	case "$J_READBACK_TEXT" in
	*"$s"*) echo "S1_REDACT_SSID is part of a fixed word of a line the harness reads back from its own J records: its redaction would rewrite that line (§15.5 A4); the owner decides" ;;
	esac
	return 0
}

# ---- used-captures ledger (§15.5 A1): each COM3 capture is used once.
capture_used() {
	[ -n "$RECDIR" ] && [ -f "$RECDIR/used-captures.log" ] || return 1
	grep -qxF "$(basename "$1")" "$RECDIR/used-captures.log"
}
mark_capture() {
	[ -n "$RECDIR" ] || return 0
	printf '%s\n' "$(basename "$1")" >> "$RECDIR/used-captures.log"
	check_private "$RECDIR/used-captures.log"
}

# 0 when the capture holds an s1wq: marker or any earlier rung's record output. The
# existing com3_has_records misses the L4T-only J rungs, whose only board lines are
# s1wq: markers (§15.5 A1). $1 the capture file.
j_capture_has_prior() {
	com3_has_records "$1" && return 0
	tr -d '\r' < "$1" | grep -aq 's1wq:'
}

# S1_COM3_LOG as typed for PowerShell (E:\...\x.log): Git Bash's dirname and basename need
# forward slashes, so a J rung, and advice on a detached-sequence log, use them.
j_norm_capture() {
	[ -n "${S1_COM3_LOG:-}" ] && S1_COM3_LOG="${S1_COM3_LOG//\\//}"
	return 0
}

# 0 when FILE resolves inside RECDIR (§15.5 A1: the raw capture must live in the
# git-ignored record directory; need_record_dir guarantees RECDIR itself is ignored).
capture_inside_recdir() {
	local f="$1" fp rp
	[ -n "$RECDIR" ] || return 1
	# pwd -W (Git Bash) names both in one form, whether the path was typed E:/... or /e/...
	fp="$(cd "$(dirname "$f")" 2>/dev/null && { pwd -W 2>/dev/null || pwd; })" || return 1
	rp="$(cd "$RECDIR" 2>/dev/null && { pwd -W 2>/dev/null || pwd; })" || return 1
	case "$fp/" in "$rp"/*) return 0 ;; *) return 1 ;; esac
}

# §15.5 A1 gate A: the capture life a J rung needs. j1 is L4T only (1800 s); b2repeat is
# as B2 (return bound + 2180); j3 and jrun control|remove add the fallback deadline.
# $1 kind, $2 return bound (default RETURN_BOUND), $3 slot count (default 9).
j_capture_life_min() {
	local kind="$1" rb="${2:-$RETURN_BOUND}" slots="${3:-9}"
	case "$kind" in
	j1)                echo 1800 ;;
	b2repeat)          echo $(( rb + 2180 )) ;;
	j3|control|remove) echo $(( rb + 2180 + $(wq_fallback_s "$slots") )) ;;
	*)                 echo $(( rb + 2180 )) ;;
	esac
}

# §15.5 A1 gate A for j1, j3 and jrun. Prints one 'jgate' line and returns 0 when the
# capture is usable, non-zero (with the reason) otherwise; the command body turns a
# non-zero into a refusal. Uses S1_COM3_LOG, RETURN_BOUND and S1_REDACT_SSID. $1 kind,
# $2 slot count (default 9).
j_capture_gate() {
	local kind="$1" slots="${2:-9}" f="${S1_COM3_LOG:-}" sv left min cs
	sv="$(ssid_refusal "${S1_REDACT_SSID:-}")"
	if [ -n "$sv" ]; then echo "jgate $kind FAIL: $sv"; return 1; fi
	if [ -z "$f" ] || [ ! -f "$f" ]; then echo "jgate $kind FAIL: S1_COM3_LOG must name the running capture-com3-raw.ps1 file"; return 1; fi
	if ! capture_inside_recdir "$f"; then echo "jgate $kind FAIL: S1_COM3_LOG is not inside the git-ignored record directory (§15.5 A1)"; return 1; fi
	if capture_used "$f"; then echo "jgate $kind FAIL: $(basename "$f") is already in used-captures.log: start a fresh capture, each is used once (§15.5 A1)"; return 1; fi
	if j_capture_has_prior "$f"; then echo "jgate $kind FAIL: the capture already holds s1wq: markers or an earlier rung's records: start a fresh capture (§15.5 A1)"; return 1; fi
	cs="$(capture_state "$f")"
	if [ "$cs" != running ]; then echo "jgate $kind FAIL: the capture is $cs, not running: start a fresh one from PowerShell"; return 1; fi
	left="$(capture_left_s)"
	min="$(j_capture_life_min "$kind" "$RETURN_BOUND" "$slots")"
	if ! [[ "$left" =~ ^-?[0-9]+$ ]]; then echo "jgate $kind FAIL: the capture header has no epoch=/seconds= ($left)"; return 1; fi
	if (( left < min )); then echo "jgate $kind FAIL: the capture has $left s left, under $min s for $kind (§15.5 A1)"; return 1; fi
	echo "jgate $kind ok: capture_left_s=$left min_s=$min inside_record_dir=yes unused=yes running=yes ssid=set"
	return 0
}

# ---- start margin (§15.4.3): start uptime + the rung's worst case must be under the
# quiesce limit. $1 uptime (decimal seconds), $2 worst-case seconds. 0 if there is margin.
start_margin_ok() {
	awk -v u="$1" -v w="$2" -v m="$QUIESCE_MAX_UPTIME_S" 'BEGIN { exit !((u + 0) + (w + 0) < (m + 0)) }'
}

# Records the margin and dies if it is exceeded (the detached sequence's issue-time
# uptime check stays the hard guard). $1 uptime, $2 worst case, $3 what.
start_margin_gate() {
	local u="$1" w="$2" what="$3"
	if start_margin_ok "$u" "$w"; then
		rec "$what start margin: uptime ${u%.*} s + worst case $w s < $QUIESCE_MAX_UPTIME_S s: ok (the start uptime ceiling is $(( QUIESCE_MAX_UPTIME_S - w )) s)"
		return 0
	fi
	die "$what start margin: uptime ${u%.*} s + worst case $w s is at or above $QUIESCE_MAX_UPTIME_S s (the start uptime ceiling is $(( QUIESCE_MAX_UPTIME_S - w )) s): run '$PROG reboot' first, then start this command at once (§15.4.3)"
}

# ---- J record directory (§15.5 A1): <rec>/<STEP> (a second attempt is <STEP>-a2, and
# so on; a refused attempt is moved to <STEP>-refused-<utc> by run_refused_move). STEP
# is always a J name (J2|J2b|J4|J6r|J6c) because jrun sets STEP after resolve_kimg, so
# image_step's B2 mapping for s1-h1 never reaches here. The J* guard makes a B* step a
# hard error rather than a created directory. Sets JSD.
j_step_dir() {
	local step="$1" n=1 d
	case "$step" in
	J*) ;;
	*) die "j_step_dir: '$step' is not a J step: a J rung must never create or write a B* directory (§15.5 A1)" ;;
	esac
	d="$RECDIR/$step"
	while [ -d "$d" ] && [ -n "$(ls -A "$d" 2>/dev/null)" ]; do n=$(( n + 1 )); d="$RECDIR/$step-a$n"; done
	JSD="$d"
	mkdir -p "$JSD" || die "cannot create $(basename "$JSD")"
}

# ---------------------------------------------------------------- J reads on the PC, and J1 (§15.4.2)
#
# SEAMS for part 3:
#   - j_kpf_snap TAG NAME DIR takes, fetches, verifies and removes one page-frame snapshot
#     (b_kpf_snap, j_kpf_fetch); it records a failure and returns non-zero, never dies.
#     kpf_decode_record HEADER... OUT writes a -decode.txt.
#   - b_pci_state TAG over ssh: board 120 "b_pci_state postquiesce"; in the unit, with
#     XHCI_PATH set from J-set.conf's xhci member so its binding stays visible after an
#     unbind. It uses od for the Command register and systemctl is-active: the allow-list
#     gate (§15.5 A5) has to admit those two read forms, or part 3 swaps them.
#   - J-set.conf (j_set_rules): member=wireless|xhci|ethernet|nvme lines in slot order, with
#     path, bdf, driver, module, netdev, root_port, root_port_children, rp_clear and in_set;
#     'tools setpci=' says whether the Bus Master clear can run. D24_SET is applied by the
#     generator, not here.
#   - com3_marker_seen / com3_wait_marker are the strict s1wq: line matchers for wait_wq.

# One token's value from a space-separated key=value line. $1 the line, $2 the key.
tok() { printf '%s\n' "$1" | awk -v k="$2" '{ for (i = 1; i <= NF; i++) if (index($i, k "=") == 1) { print substr($i, length(k) + 2); exit } }'; }

J1_POLL_S=5
J1_PROBE_WAIT_S=30
J1_TIMER_WAIT_S=120

# §15.5 A1: fetch the files one b_kpf_snap (or J1's probe) listed, check each copy's
# sha256 against the board's, run privacy_scan on the text files (the header, zoneinfo,
# buddyinfo), then remove the tmpfs directory on the board. Records every step; a failure
# returns non-zero and never stops the rung. $1 the board output, $2 the PC directory.
# Sets KPF_FILES to the copies that verified. $3, when set (Phase A), bounds the whole fetch
# in seconds, the tmpfs removal's 30 s included; J1 leaves it unset (120 s per file, 60 s rm).
j_kpf_fetch() {
	local out="$1" dest="$2" total="${3:-0}" dir line name want got f ok=0 bad=0 t0 per
	KPF_FILES=()
	t0=$(date +%s)
	dir="$(printf '%s\n' "$out" | sed -n 's/^kpf tag=[a-z]* dir=\(.*\)$/\1/p' | tail -n 1)"
	if ! [[ "$dir" =~ ^/[A-Za-z0-9._/-]*/s1kpf\.[A-Za-z0-9]{6}$ ]]; then
		rec "kpf no usable tmpfs directory in the board's output: nothing fetched (recorded; the rung goes on)"
		return 1
	fi
	while IFS= read -r line; do
		name="$(tok "$line" file)"
		want="$(tok "$line" sha256)"
		if ! [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
			rec "kpf a listed file name was refused"
			bad=$(( bad + 1 ))
			continue
		fi
		f="$dest/$name"
		per=120
		if [ "$total" -gt 0 ]; then
			per=$(( total - 30 - ($(date +%s) - t0) ))
			if [ "$per" -le 0 ]; then
				rec "kpf copy $name NOT tried: the fetch bound of $total s has passed"
				bad=$(( bad + 1 ))
				continue
			fi
			[ "$per" -gt 120 ] && per=120
		fi
		if timeout "$per" scp "${ssh_work[@]}" "$ORIN_HOST:$dir/$name" "$f" </dev/null >/dev/null 2>&1; then
			got="$(sha256sum "$f" | cut -d' ' -f1)"
			if [ "$got" = "$want" ]; then
				rec "kpf copied $name bytes=$(stat -c %s "$f") sha256=$got, equal to the board's"
				KPF_FILES+=("$f")
				ok=$(( ok + 1 ))
				check_private "$f"
				case "$name" in *.txt) privacy_scan "$f" ;; esac
			else
				rec "kpf copy $name sha256 $got DIFFERS from the board's ${want:-unread}"
				bad=$(( bad + 1 ))
			fi
		else
			rec "kpf copy $name FAILED"
			bad=$(( bad + 1 ))
		fi
	done < <(printf '%s\n' "$out" | grep '^kpf file=')
	board "$([ "$total" -gt 0 ] && echo 30 || echo 60)" "b_kpf_rm $dir" | rec_pipe
	[ "$bad" = 0 ] && [ "$ok" -gt 0 ]
}

# Phase A's snapshot (§15.4.3 step 2): $1 tag (prequiesce|postquiesce), $2 the file prefix
# (<img>-<utc>), $3 the PC record directory, $4 the board session's bound (default 300),
# $5 the fetch bound (default: j_kpf_fetch's per-file bounds). Records the lines and the fetch.
j_kpf_snap() {
	local tag="$1" name="$2" dest="$3" out
	[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { rec "kpf $tag refused: the prefix is not [A-Za-z0-9._-]+"; return 1; }
	out="$(board "${4:-300}" "KPF_NAME=$name" "b_kpf_snap $tag")" || rec "kpf $tag board session rc=$? (recorded; the rung goes on)"
	printf '%s\n' "$out" | grep '^kpf ' | rec_pipe
	j_kpf_fetch "$out" "$dest" "${5:-0}"
}

# kpf-decode.py on one or two fetched headers, into OUT (the last argument). Records rc.
kpf_decode_record() {
	local out="${*: -1}" rc
	find_python || { rec "kpf decode NOT run: no working python 3.8+"; return 1; }
	"$PY_BIN" "$S1DIR/kpf-decode.py" "${@:1:$#-1}" > "$out" 2>&1
	rc=$?
	check_private "$out"
	rec "kpf decode rc=$rc $(grep -a '^decode result=' "$out" | tail -n 1) record=$(basename "$out")"
	return "$rc"
}

# §15.4.2's set file from J1's census lines on stdin: J4's "max" set in slot order
# (§15.4.3: wireless, xHCI, Ethernet, NVMe). Class codes, not names: wireless 0x0280,
# Ethernet 0x0200, NVMe 0x0108; the xHCI is the one USB host whose controller sits on the
# platform bus. A member stays in the set (in_set=yes reason=ok) only when:
#   - exactly one candidate exists (absent, ambiguous);
#   - a driver is bound (no-driver);
#   - its parent port has no other child (shared-root-port; J1's table: it leaves the set);
#   - no mount, swap area or the root lies under its sysfs path (mounted-descendant);
#   - neither $HOME nor KD lies under it (home-or-kd-under; for the wireless function
#     that is note=no-j3-j4);
#   - wireless and Ethernet: no network filesystem is mounted (network-mount);
#   - NVMe and xHCI: every root, home, KD and swap chain resolved (unresolved-storage).
# The last two are fail-safe additions: an unknown backing is treated as a descendant.
j_set_rules() {
	awk '
	function tv(line, k,    n, i, a) {
		n = split(line, a, " ")
		for (i = 1; i <= n; i++) if (index(a[i], k "=") == 1) return substr(a[i], length(k) + 2)
		return ""
	}
	function under(c, p) { return (p != "" && c != "" && index(c, p "/") == 1) }
	function nz(v) { return (v == "" ? "none" : v) }
	function member(m, cand, sb, bdf, path, drv, mod, nd, par,    r, i, md, hk, kn, rpc) {
		r = ""; md = "no"; hk = "no"; kn = 0
		if (cand == 0) r = ",absent"
		else if (cand > 1) r = ",ambiguous"
		else {
			if (drv == "" || drv == "none") r = r ",no-driver"
			if (sb == "pci" && par != "none" && par != "") kn = kids[par] + 0
			if (kn > 1) r = r ",shared-root-port"
			for (i = 1; i <= nb; i++) {
				if (Bu[i] ~ /^(mount|swap|root)$/ && under(Bp[i], path)) md = "yes"
				if (Bu[i] ~ /^(home|kd)$/ && under(Bp[i], path)) hk = "yes"
			}
			if (md == "yes") r = r ",mounted-descendant"
			if (hk == "yes") r = r ",home-or-kd-under"
			if (net && (m == "wireless" || m == "ethernet")) r = r ",network-mount"
			if (unres && (m == "nvme" || m == "xhci")) r = r ",unresolved-storage"
		}
		rpc = (cand == 1 && kn == 1) ? "yes" : "no"
		printf "member=%s candidates=%d subsystem=%s bdf=%s path=%s driver=%s module=%s netdev=%s root_port=%s root_port_children=%d rp_clear=%s mounted_descendant=%s home_or_kd_under=%s in_set=%s reason=%s\n", \
			m, cand, nz(sb), nz(bdf), nz(path), nz(drv), nz(mod), nz(nd), nz(par), kn, rpc, md, hk, (r == "" ? "yes" : "no"), (r == "" ? "ok" : substr(r, 2))
		if (m == "wireless" && hk == "yes") hkw = 1
	}
	function pcimember(m, cls,    i, c, k) {
		c = 0
		for (i = 1; i <= np; i++) if (substr(Pc[i], 1, 6) == cls) { c++; k = i }
		if (c == 1) member(m, 1, "pci", Pb[k], Pa[k], Pd[k], Pm[k], Pn[k], Pp[k])
		else member(m, c, "", "", "", "", "", "", "")
	}
	function xhcimember(    i, c, k) {
		c = 0
		for (i = 1; i <= nh; i++) if (Hs[i] == "platform") { c++; k = i }
		if (c == 1) member("xhci", 1, "platform", "", Hp[k], Hd[k], Hm[k], "", "")
		else member("xhci", c, "", "", "", "", "", "", "")
	}
	$1 != "cen" { next }
	$2 == "pcidev" {
		np++
		Pb[np] = tv($0, "bdf"); Pc[np] = tolower(tv($0, "class")); Pd[np] = tv($0, "driver"); Pm[np] = tv($0, "module")
		Pp[np] = tv($0, "parent"); Pn[np] = tv($0, "netdev"); Pa[np] = tv($0, "path")
		if (Pp[np] != "" && Pp[np] != "none") kids[Pp[np]]++
		next
	}
	$2 == "usbhost" {
		p = tv($0, "path")
		if (p != "" && !(p in hseen)) { hseen[p] = 1; nh++; Hp[nh] = p; Hs[nh] = tv($0, "subsystem"); Hd[nh] = tv($0, "driver"); Hm[nh] = tv($0, "module") }
		next
	}
	$2 == "blkchain" {
		nb++; Bu[nb] = tv($0, "use"); Bp[nb] = tv($0, "path")
		if (Bp[nb] == "network") net = 1
		if (Bp[nb] == "unresolved") unres = 1
		next
	}
	$2 == "iommu_group" { ng++; next }
	$2 == "tool" { tools[tv($0, "name")] = (tv($0, "path") == "absent" ? "no" : "yes"); next }
	$2 ~ /^hid_keyboard=/ { kbd = substr($2, 14); next }
	END {
		print "set_version=1"
		print "set_rule=max slots=wireless,xhci,ethernet,nvme"
		printf "tools systemd_run=%s setpci=%s modprobe=%s\n", nz(tools["systemd-run"]), nz(tools["setpci"]), nz(tools["modprobe"])
		pcimember("wireless", "0x0280")
		xhcimember()
		pcimember("ethernet", "0x0200")
		pcimember("nvme", "0x0108")
		for (i = 1; i <= np; i++) if ((Pb[i] in kids) && !(Pb[i] in pdone)) { pdone[Pb[i]] = 1; printf "port=%s children=%d\n", Pb[i], kids[Pb[i]] }
		if (hkw) print "note=no-j3-j4 reason=home-or-kd-under-wireless"
		if (ng) printf "note=untranslated-groups count=%d\n", ng
		if (net) print "note=network-mount"
		if (unres) print "note=unresolved-storage"
		printf "recovery hid_keyboard=%s\n", nz(kbd)
	}'
}

# J1's set rows for the board log, from J-set.conf: no path, driver or address. $1 the file.
j1_set_rows() {
	local line
	while IFS= read -r line; do
		case "$line" in
		member=*)
			printf 'j1 row set %s\n' "$(printf '%s\n' "$line" | awk '{ s = ""; for (i = 1; i <= NF; i++) if ($i ~ /^(member|candidates|subsystem|root_port_children|rp_clear|mounted_descendant|home_or_kd_under|in_set|reason)=/) s = s (s == "" ? "" : " ") $i; print s }')"
			;;
		note=no-j3-j4*)
			echo "j1 row set STOP: \$HOME or the kimg directory resolves under the wireless function, so it leaves the set: no J3 or J4 (memo, §15.4.2)" ;;
		note=untranslated-groups*)
			echo "j1 row iommu: a group whose type is not DMA or DMA-FQ exists ($(tok "$line" count)): a new untranslated master; memo line; H4 widens; the ladder is unchanged" ;;
		note=network-mount)
			echo "j1 row set: a network filesystem is mounted: the wireless and Ethernet functions leave the set (fail-safe)" ;;
		note=unresolved-storage)
			echo "j1 row set: a root, home, kimg-directory or swap chain did not resolve: the NVMe and xHCI members leave the set (fail-safe)" ;;
		tools*|recovery*)
			echo "j1 row $line" ;;
		esac
	done < "$1"
}

# 0 when the capture, after byte $2, holds $3 as a whole console line: CR removed, blanks
# trimmed, an optional printk time (and caller id) in front and nothing after. A systemd
# status line quoting a command that holds the text, or another result=, does not count.
# Reads the whole stream (no early exit: pipefail would turn a SIGPIPE into a miss).
com3_marker_seen() {
	tail -c +"$(( ${2:-0} + 1 ))" "$1" 2>/dev/null | tr -d '\r' | LC_ALL=C awk -v m="$3" '
	{
		s = $0
		# J2: a marker can share its line with stray non-ASCII bytes left by earlier output
		sub(/^[ \t]+/, "", s); sub(/^[^ -~]+[ \t]*/, "", s); sub(/[ \t]+$/, "", s)
		sub(/^\[ *[0-9]+\.[0-9]+\] */, "", s)
		sub(/^\[ *[CT][0-9]+\] */, "", s)
		if (s == m) found = 1
	}
	END { exit !found }'
}

# Polls the capture every J1_POLL_S s for com3_marker_seen. $1 file, $2 offset, $3 text,
# $4 bound in seconds. 0 seen, 1 not within the bound.
com3_wait_marker() {
	local t0
	t0=$(date +%s)
	while :; do
		com3_marker_seen "$1" "$2" "$3" && return 0
		(( $(date +%s) - t0 >= $4 )) && return 1
		sleep "$J1_POLL_S"
	done
}

# Polls the capture for an ERE after byte $2; prints the epoch it was first seen, or
# nothing when the bound $4 passed. $1 file, $3 the ERE.
com3_wait_re() {
	local t0 n
	t0=$(date +%s)
	while :; do
		n="$(tail -c +"$(( $2 + 1 ))" "$1" 2>/dev/null | tr -d '\r' | grep -acE -- "$3")"
		if [ "${n:-0}" -gt 0 ]; then date +%s; return 0; fi
		(( $(date +%s) - t0 >= $4 )) && return 1
		sleep "$J1_POLL_S"
	done
}

# §15.4.2 item 8: the per-device shutdown trace (device_shutdown()'s initcall_debug lines,
# 'shutdown' or 'shutdown_pre' after a device name) between byte $2 and the kernel's
# restart line. Prints trace_lines=N trace_pci_lines=N restart_seen=yes|no.
com3_trace_counts() {
	tail -c +"$(( ${2:-0} + 1 ))" "$1" 2>/dev/null | tr -d '\r' | awk '
	{
		s = $0
		sub(/[ \t]+$/, "", s)
		if (s ~ /Restarting system/) rs = 1
		if (!rs && s ~ /: shutdown(_pre)?$/) {
			t++
			if (s ~ /[0-9a-f][0-9a-f][0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f][.][0-7]: shutdown(_pre)?$/) p++
		}
	}
	END { printf "trace_lines=%d trace_pci_lines=%d restart_seen=%s\n", t, p, (rs ? "yes" : "no") }'
}

# §15.4.2's go/no-go table as a rule. key=value arguments: systemd_run=yes|no
# probe_entries=N probe_marker=yes|no timer_marker=yes|no d21=yes|no trace_lines=N
# shutdown_s=N|unknown stuck_s=N watchdog=yes|no. Prints 'j1 row' lines and one
# 'j1 next=J2|J2b trace=go|no-go|off' line.
j1_rows() {
	local a sr=no pe=0 pm=no tm=no d21=no tl=0 ss=unknown st=600 wd=no next trace
	for a in "$@"; do
		case "$a" in
		systemd_run=*)   sr="${a#*=}" ;;
		probe_entries=*) pe="${a#*=}" ;;
		probe_marker=*)  pm="${a#*=}" ;;
		timer_marker=*)  tm="${a#*=}" ;;
		d21=*)           d21="${a#*=}" ;;
		trace_lines=*)   tl="${a#*=}" ;;
		shutdown_s=*)    ss="${a#*=}" ;;
		stuck_s=*)       st="${a#*=}" ;;
		watchdog=*)      wd="${a#*=}" ;;
		esac
	done
	[[ "$tl" =~ ^[0-9]+$ ]] || tl=0
	[[ "$st" =~ ^[0-9]+$ ]] || st=0
	if [ "$sr" = yes ] && [ "$pm" = yes ] && [ "$tm" = yes ]; then
		next=J2
		echo "j1 row detached MET: systemd-run present and both s1wq: j1 markers on COM3: the detached sequence and the markers can run as designed"
	else
		next=J2b
		echo "j1 row detached F42: systemd_run=$sr probe_marker=$pm timer_marker=$tm: no detached sequence can be proven; J2b runs in J2's place (a pure B2 repeat); J3 and J4 wait (revision 4, or D25's Ethernet variant)"
	fi
	if [ "$pe" = 64 ]; then
		echo "j1 row snapshot MET: the dd probe returned 64 entries (R60)"
	else
		echo "j1 row snapshot UNPROVEN: the dd probe returned ${pe} entries, not 64 (R60): a snapshot failure is recorded and never stops a rung"
	fi
	if [ "$d21" != yes ]; then
		trace=off
		echo "j1 row trace NOT RUN: D21 is not yes: J2 and J4 run without the trace"
	elif (( tl > 0 )) && [[ "$ss" =~ ^[0-9]+$ ]] && (( ss * 2 < st )); then
		trace=go
		echo "j1 row trace GO: trace_lines=$tl, and the shutdown section took $ss s, under half of S1_STUCK_S=$st: J2 and J4 both carry it (matched)"
	else
		trace=no-go
		echo "j1 row trace NO-GO (F38): trace_lines=$tl shutdown_s=$ss against half of S1_STUCK_S=$st: J2 and J4 both run without the trace; no rerun for the trace alone"
	fi
	[ "$wd" = yes ] && echo "j1 row reboot F27: a new dmesg-ramoops record after the reboot (the known long-uptime pattern): J2 on the fresh boot"
	echo "j1 next=$next trace=$trace"
}

cmd_j1() {
	local out old gate rc stuck d21 d22 d23 base census setf pe=0 sr=no pm=no tm=no off_probe off_timer off_reboot
	local t0 ts shutdown_s=unknown wrc com3 tc tl=0 rs=no pstore_before pstore_after newrec wd=no f bound SD
	need_host
	need_record_dir
	IMG=""
	UTC="$(utc_now)"
	stuck="${S1_STUCK_S:-600}"
	[[ "$stuck" =~ ^[0-9]+$ ]] || die "S1_STUCK_S must be a whole number of seconds"
	j_read_decisions
	j_require D20 "j1's marker and transient-timer probe (§15.4.2 item 6)"
	d21="$(j_decision D21)"
	d22="$(j_decision D22)"
	d23="$(j_decision D23)"
	for f in "$RECDIR"/J[234]*; do
		[ -d "$f" ] && die "$(basename "$f") exists: J4's set has been used by a later rung, and j1 would replace J-set.conf. Start a new record directory for a new census (§15.4.1)"
	done
	j_require_clean_tree "j1"
	j_norm_capture
	[ -n "${S1_COM3_LOG:-}" ] || die "S1_COM3_LOG must name the running capture-com3-raw.ps1 file, inside the record directory (§15.4.2)"

	j_step_dir J1
	SD="$JSD"
	base="$SD/j1-$UTC"
	rec_open "$base-board.log"
	ON_DIE=run_refused_move
	rec "j1 utc=$UTC: census, marker and transient-timer path, trace rehearsal; no quiesce, no kexec; ends in a reboot (§15.4.2)"
	rec "j1 record_dir=$(basename "$RECDIR")/$(basename "$SD")"
	j_stamps | rec_pipe
	rec "j1 decisions D20=$(j_decision D20) D21=${d21:-unset} (the trace) D22=${d22:-unset} (the kpageflags probe and the PCI configuration reads; not yes: neither is taken, the snapshot row stays UNPROVEN) D23=${d23:-unset} (the debugfs reads)"
	gate="$(j_capture_gate j1)" || die "gate A: ${gate#*FAIL: }"
	rec "$gate"

	out="$(board 60 b_identity b_pstore)" || die "board unreachable (rc=$?); nothing was changed on the board"
	printf '%s\n' "$out" | rec_pipe
	old="$(kv boot_id "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	pstore_before="$(printf '%s\n' "$out" | grep '^pstore ')"
	mark_boot "$old" j1
	mark_capture "$S1_COM3_LOG"
	ON_DIE=""
	rec "j1 com3_log=$(basename "$S1_COM3_LOG") return_bound_s=$RETURN_BOUND stuck_s=$stuck: this boot is now used (by=j1) and never serves a quiesce"

	# reads 1-5 and 7
	rec "j1 reads 1-5 and 7 (bound 300 s): tools and the kpageflags probe, kernel configuration, PCI topology, storage chain, USB$([ "$d23" = yes ] && echo ', debugfs (D23)')"
	out="$(board 300 "KPF_NAME=j1-$UTC" "J_D22=${d22:-no}" "J_D23=${d23:-no}" b_census)"
	rc=$?
	census="$base-census.log"
	{ printf '# %s: evaluation output, NC QDL v7 4.6(i), unpublished\n' "$(basename "$census")"; printf '%s\n' "$out"; } > "$census"
	check_private "$census"
	rec "j1 census session rc=$rc cen_lines=$(printf '%s\n' "$out" | grep -c '^cen ') record=$(basename "$census")"
	case "$(printf '%s\n' "$out" | sed -n 's/^cen tool name=systemd-run path=//p' | head -n 1)" in ''|absent) sr=no ;; *) sr=yes ;; esac
	rec "j1 tools: systemd-run=$sr setpci=$(printf '%s\n' "$out" | sed -n 's/^cen tool name=setpci path=//p' | head -n 1 | sed 's/^\/.*/present/')"
	if j_kpf_fetch "$out" "$SD" && [ -f "$base-kpf-probe.bin" ]; then
		pe=$(( $(stat -c %s "$base-kpf-probe.bin") / 8 ))
	fi
	rec "j1 kpf probe entries=$pe (64 wanted, R60)"

	# the set file (§15.4.2), its rows and the pre-registration update (§15.4.1)
	setf="$base-set.conf"
	{
		printf '# J-set.conf from j1 %s: J4'"'"'s "max" set by the rules of s1-design §15.4.2-§15.4.3; private, unpublished (D29)\n' "$UTC"
		printf '%s\n' "$out" | j_set_rules
	} > "$setf"
	# the SSID inside a device path, driver or interface name: the privacy scan would rewrite
	# the set file's member values, so no J2-J4 could use it (§15.5 A4)
	if grep -aqF -- "$S1_REDACT_SSID" "$setf"; then
		redact_file "$setf"
		die "the set file holds the S1_REDACT_SSID text inside a device path, driver or interface name: its redaction would rewrite the member values J2-J4 act on, so J-set.conf is not written (the owner decides; the redacted copy is $(basename "$setf"))"
	fi
	cp "$setf" "$RECDIR/J-set.conf" || die "cannot write J-set.conf"
	check_private "$setf" "$RECDIR/J-set.conf"
	privacy_scan "$census"
	privacy_scan "$setf"
	privacy_scan "$RECDIR/J-set.conf"
	rec "j1 set file J-set.conf sha256=$(j_sha256 "$RECDIR/J-set.conf") (copy $(basename "$setf"))"
	j1_set_rows "$RECDIR/J-set.conf" | rec_pipe
	j_prereg_write
	rec "j1 J-prereg.log updated sha256=$(j_sha256 "$RECDIR/J-prereg.log"): the set file hash; the slot list and fill-rate factor stay pending until the generator derives them"

	# read 6 (D20): the marker, then one transient timer
	off_probe=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)
	rec "j1 com3_bytes_before_probe=$off_probe"
	board 60 b_j1_probe | rec_pipe
	if com3_wait_marker "$S1_COM3_LOG" "$off_probe" 's1wq: j1 probe result=0' "$J1_PROBE_WAIT_S"; then pm=yes; fi
	rec "j1 marker probe on COM3: $pm (within $J1_PROBE_WAIT_S s, R57)"
	off_timer=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)
	if [ "$sr" = yes ]; then
		out="$(board 60 b_j1_timer)"
		printf '%s\n' "$out" | rec_pipe
		if [ "$(kv j1_timer_arm_rc "$out")" = 0 ] \
			&& com3_wait_marker "$S1_COM3_LOG" "$off_timer" 's1wq: j1 timer result=0' "$J1_TIMER_WAIT_S"; then
			tm=yes
		fi
		rec "j1 timer marker on COM3: $tm (armed for 30 s, bound $J1_TIMER_WAIT_S s, R59)"
	else
		rec "j1 timer NOT armed: systemd-run is absent"
	fi

	# item 8 (D21), then the harness's reboot path
	off_reboot=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)
	rec "j1 com3_bytes_before_reboot=$off_reboot"
	if [ "$d21" = yes ]; then
		board 60 'sudo -n bash -c "$(declare -f b_trace_on); b_trace_on"' | rec_pipe
	else
		rec "j1 trace not set: D21 is not yes"
	fi
	rec "j1: sudo -n reboot, then wait for a new boot_id"
	t0=$(date +%s)
	board 30 b_reboot | rec_pipe
	bound="$RETURN_BOUND"
	(( stuck > 0 && stuck < bound )) && bound="$stuck"
	ts="$(com3_wait_re "$S1_COM3_LOG" "$off_reboot" "Restarting system|$(printf '%s|' "${FW_BANNER[@]}" | sed 's/|$//')" "$bound")"
	wait_new_boot_id "$old" "$t0" 0 0
	wrc=$?
	if [ "$wrc" != 0 ]; then
		rec "reboot NO RETURN within $RETURN_BOUND s (j1's reboot). Read COM3 and run, from the repository root with S1_COM3_LOG set, '$(repo_rel "$HERE/$PROG") advice $(repo_rel "$REC")': power is cut by the class of the last COM3 line, never by the clock alone (§2 rule 6a)"
		check_private "$REC" "$census" "$setf"
		exit 2
	fi
	rec "j1 back new_boot_id=$NEW_BOOT_ID after $BACK_S s"

	# COM3: the copy, the markers again over the whole stream, the trace (raw, before redaction)
	com3="$base-com3.log"
	if cp "$S1_COM3_LOG" "$com3" 2>/dev/null; then
		rec "j1 COM3 copied: $(basename "$com3") bytes=$(stat -c %s "$com3") raw_sha256=$(sha256sum "$com3" | cut -d' ' -f1); L4T is back: stop the capture after this command returns"
		com3_marker_seen "$com3" "$off_probe" 's1wq: j1 probe result=0' && pm=yes
		[ "$sr" = yes ] && com3_marker_seen "$com3" "$off_timer" 's1wq: j1 timer result=0' && tm=yes
		tc="$(com3_trace_counts "$com3" "$off_reboot")"
		rec "j1 trace $tc"
		tl="$(tok "$tc" trace_lines)"
		rs="$(tok "$tc" restart_seen)"
	else
		rec "j1 COM3 copy FAILED (the capture may hold the file): the markers and the trace are judged on the polls only"
		com3=""
	fi
	if [ -n "$ts" ] && [ "$rs" = yes ]; then
		shutdown_s=$(( ts - t0 ))
		rec "j1 shutdown section: the restart line was on COM3 within $shutdown_s s of the reboot (${J1_POLL_S} s polls)"
	else
		rec "j1 shutdown section: no restart line seen by the polls (shutdown_s=unknown)"
	fi

	# after the return: identity, pstore, nvbootctrl (F27, F30)
	out="$(board 60 b_identity b_pstore b_slots)"
	printf '%s\n' "$out" | grep -v '^slots ' | rec_pipe
	pstore_after="$(printf '%s\n' "$out" | grep '^pstore ')"
	newrec="$(comm -13 <(printf '%s\n' "$pstore_before" | sort) <(printf '%s\n' "$pstore_after" | sort) | grep '^pstore dmesg-ramoops' || true)"
	if [ -n "$newrec" ]; then
		wd=yes
		rec "j1 NEW dmesg-ramoops records (F27):"
		printf '%s\n' "$newrec" | rec_pipe
	fi
	slots_check "$out" "$base-nvbootctrl-post.log"
	slots_report j1 "$base-nvbootctrl-post.log"

	j1_rows systemd_run="$sr" probe_entries="$pe" probe_marker="$pm" timer_marker="$tm" d21="${d21:-no}" \
		trace_lines="$tl" shutdown_s="$shutdown_s" stuck_s="$stuck" watchdog="$wd" | rec_pipe
	[ -n "$com3" ] && privacy_scan "$com3"
	rec "j1 done. Record: $(basename "$SD")/$(basename "$REC"); set file J-set.conf; pre-registration J-prereg.log"
	check_private "$REC" "$census" "$setf" "$com3" "$base-kpf-probe.bin" "$base-nvbootctrl-post.log"
	if [ "$SLOTS_STATE" = differ ]; then
		rec "j1 F30: STOP ALL BOARD WORK (exit 4)"
		exit 4
	fi
	return 0
}

# §15.5 A2: orin-native/s1/kpf-decode.py on one or two b_kpf_snap headers, or --selftest.
cmd_kpf_decode() {
	local f
	[ -f "$S1DIR/kpf-decode.py" ] || die "no orin-native/s1/kpf-decode.py"
	find_python || die "no working python 3.8+ for kpf-decode.py"
	if [ "$1" != --selftest ]; then
		for f in "$@"; do [ -f "$f" ] || die "no header file $(basename "$f")"; done
	fi
	"$PY_BIN" "$S1DIR/kpf-decode.py" "$@"
}

# ---------------------------------------------------------------- the detached sequence on the PC (§15.4.3, §15.5 A5)

# §15.4.3 step 4: one generated script on stdout, with printf %q and declare -f only (never a
# heredoc: heredocs eat backslashes). $1 main (-wq.sh) or fallback (-wqfb.sh). Every value
# comes from a WQG_ variable (j_wq_prepare): WQG_ARM control|j3|remove, WQG_FINAL kexec|none,
# WQG_UTC, WQG_LOG, WQG_TRACE, WQG_SETPCI, WQG_HOME_DEV, WQG_KD_DEV, WQG_XHCI_PATH, and
# WQG_<L>_<KEY> for the members W (wireless), X (xHCI), E (Ethernet), N (NVMe). WQG_KMSG and
# WQG_ROOT exist for the self-tests' dry run only; the gate refuses anything but /dev/kmsg
# and ''. The header comment is ASCII, as the gate requires.
b_wq_gen() {
	local kind="$1" L k v
	printf '%s\n' '#!/bin/bash'
	printf '# %s: generated by orin-native/startup/%s (s1-design.md 15.4.3); evaluation output, NC QDL v7 4.6(i), unpublished\n' "$kind" "$PROG"
	printf 'WQ_KIND=%q\nWQ_ARM=%q\nWQ_FINAL=%q\nWQ_UTC=%q\n' "$kind" "$WQG_ARM" "$WQG_FINAL" "$WQG_UTC"
	printf 'WQ_LOG=%q\nWQ_KMSG=%q\nWQ_ROOT=%q\n' "$WQG_LOG" "${WQG_KMSG:-/dev/kmsg}" "${WQG_ROOT:-}"
	printf 'WQ_START_DELAY_S=%q\nWQ_SLOT_S=%q\nWQ_STEP_TIMEOUT_S=%q\nWQ_FINAL_READS_S=%q\nWQ_ISSUE_WAIT_S=%q\n' \
		"$WQ_START_DELAY_S" "$WQ_SLOT_S" "$WQ_STEP_TIMEOUT_S" "$WQ_FINAL_READS_S" "$WQ_ISSUE_WAIT_S"
	printf 'WQ_TRACE=%q\nWQ_SETPCI=%q\nWQ_HOME_DEV=%q\nWQ_KD_DEV=%q\nWQ_OOPS0=0\nXHCI_PATH=%q\n' \
		"$WQG_TRACE" "$WQG_SETPCI" "$WQG_HOME_DEV" "$WQG_KD_DEV" "${WQG_XHCI_PATH:-}"
	for L in W X E N; do
		for k in IN PATH BDF DRV MOD NETDEV RP RPCLEAR; do
			v="WQG_${L}_$k"
			printf 'WQ_%s_%s=%q\n' "$L" "$k" "${!v:-none}"
		done
	done
	# shellcheck disable=SC2086  # a list of function names
	declare -f $WQ_FUNCS
	case "$kind" in
	main)     printf '%s\n' 'b_wq_main >> "$WQ_LOG" 2>&1' ;;
	fallback) printf '%s\n' 'b_wq_fallback >> "$WQ_LOG" 2>&1' ;;
	esac
}

# §15.5 A5: the allow-list gate on one generated script, on the PC before scp. It lexes the
# script as bash would (quotes, $( ), ${ }, $(( )), array literals, case patterns, the
# redirections declare -f prints) and checks:
#   - line 1 is #!/bin/bash; the header holds only comments and WQ_ assignments whose values
#     are plain printf %q tokens; WQ_KIND is $2, WQ_KMSG /dev/kmsg, WQ_ROOT '', WQ_LOG the
#     fixed <home>/<name>-<utc>-wq.log, the timing constants the harness's own, and WQ_ARM
#     and WQ_FINAL a pair the design allows (control|remove with kexec, j3 with none);
#   - the member values (WQ_<L>_PATH a /sys/devices path or none, BDF and RP a function name or
#     none, DRV, MOD and NETDEV plain names, IN and RPCLEAR yes|no), WQ_HOME_DEV and WQ_KD_DEV,
#     XHCI_PATH, WQ_UTC and WQ_OOPS0=0;
#   - the functions are exactly WQ_FUNCS, and the last line is the one call for $2, the only
#     command outside the functions;
#   - every simple command is on the exact list (§15.5 A5), in the exact form the functions
#     use: cat of a literal sysfs or /proc path (or $WQ_ROOT's) or of one of the few variable
#     read paths, each only in its own function; ip link set dev "$WQ_W_NETDEV" down and
#     modprobe -r "$WQ_W_MOD" (b_wq_slot); setpci -s "${dev##*/}" COMMAND and
#     COMMAND=0000:0004 (b_wq_bme); kexec -u; systemctl kexec (exactly once, b_wq_issue),
#     reboot, is-system-running and exactly one reboot --force (b_wq_fallback); sync; sleep;
#     timeout; dmesg (-n 7 only in b_trace_on); sha256sum and readlink -e of read paths;
#     date; printf; grep reading stdin; ps -o <fmt>= -p "$var"; the shell's own words; and
#     two reads b_pci_state needs (od -An -tu1 -j4 -N2 of a config file, systemctl is-active
#     <unit>.service) plus the 'sudo -n' b_freq carries, which A5's list does not name;
#   - every redirect: >> $WQ_LOG; > $WQ_KMSG; > $WQ_ROOT/sys/bus/{pci,platform}/drivers/$drv/unbind;
#     > /sys/module/kernel/parameters/initcall_debug (b_trace_on); /dev/null; descriptor dups;
#     input from /dev/null or a read path;
#   - explicit refusals, on every line of the text and again on every lexed word and redirect
#     target (so a quote split cannot hide one): rfkill, nmcli, iw, ip addr, systemctl
#     enable|disable|mask|stop|isolate, /etc, /boot, /var/lib, apt, dpkg, extlinux,
#     --force --force, -ff, /dev/mem, devmem, /dev/tcp, /dev/udp, dd, of=, tar, remove,
#     rescan, reset, driver_override, new_id, power/control, address, serial, lsusb,
#     hciconfig; also [[, backticks, heredocs, here-strings, process substitution, eval-like
#     builtins and &.
# Prints 'wqgate <name> refused: <reason>' per finding and one 'wqgate <name> ok|FAIL' line.
# $1 the script, $2 main|fallback.
wq_gate() {
	awk -v name="$(basename "$1")" -v kind="$2" -v funcs="$WQ_FUNCS" \
		-v consts="WQ_START_DELAY_S=$WQ_START_DELAY_S WQ_SLOT_S=$WQ_SLOT_S WQ_STEP_TIMEOUT_S=$WQ_STEP_TIMEOUT_S WQ_FINAL_READS_S=$WQ_FINAL_READS_S WQ_ISSUE_WAIT_S=$WQ_ISSUE_WAIT_S" '
	function bad(m) { nbad++; print "wqgate " name " refused: " m }
	function push(t) { SC[depth] = cur; SQ[depth] = dq; SI[depth] = inw; depth++; TY[depth] = t; NW[depth] = 0; NR2[depth] = 0; CL[depth] = 0; cur = ""; dq = 0; inw = 0 }
	function pop(   t) { t = TY[depth]; depth--; cur = SC[depth]; dq = SQ[depth]; inw = SI[depth]; return t }
	# the explicit refusals, on one lexed word (quotes and escapes removed, so a quote split
	# such as addr""ess or /e""tc is the word bash would pass) or one redirect target
	function wordcheck(w) {
		if (w ~ /\/(etc|boot)(\/|[^A-Za-z0-9_.-]|$)/) bad("the word \047" w "\047: a path under /etc or /boot")
		if (w ~ /\/var\/lib/) bad("the word \047" w "\047: a path under /var/lib")
		if (w ~ /\/dev\/mem|devmem/) bad("the word \047" w "\047: /dev/mem or devmem")
		if (w ~ /\/dev\/(tcp|udp)/) bad("the word \047" w "\047: a /dev/tcp or /dev/udp socket path")
		if (w ~ /of=/) bad("the word \047" w "\047: of=")
		if (w ~ /\/(remove|rescan|reset)([^A-Za-z0-9_]|$)|driver_override|new_id|power\/control/) bad("the word \047" w "\047: a write path remove, rescan, reset, driver_override, new_id or power/control")
		if (w ~ /address|serial|lsusb|hciconfig|nmcli|extlinux|dpkg/) bad("the word \047" w "\047: address, serial, lsusb, hciconfig, nmcli, extlinux or dpkg")
	}
	function endword(   k) {
		if (inw) {
			wordcheck(cur)
			NW[depth]++
			W[depth, NW[depth]] = cur
			k = 1
			while (k <= NW[depth] && W[depth, k] ~ /^(if|then|else|elif|do|while|until|!|\{|\})$/) k++
			if (W[depth, k] == "case" && NW[depth] == k + 2 && W[depth, NW[depth]] == "in") {
				NW[depth] = 0; NR2[depth] = 0; CL[depth]++; CS[depth, CL[depth]] = "pat"
			}
		}
		cur = ""; inw = 0
	}
	function endcmd() { endword(); if (NW[depth] > 0 || NR2[depth] > 0) checkcmd(depth); NW[depth] = 0; NR2[depth] = 0 }
	# a read path: a literal /sys or /proc path (or one under $WQ_ROOT) with no variable in it,
	# or one of the exact variable forms the functions use, each only inside its own function
	function readpath(t) {
		if (t ~ /\/\.\.(\/|$)|\/dev\/(tcp|udp)/) return 0
		if (t ~ /^(\$WQ_ROOT)?\/(sys|proc)\/[A-Za-z0-9_.@:,+\/-]*$/) return 1
		if (FN == "b_freq") return (t == "$d/$f" || t == "$d/cpuinfo_cur_freq")
		if (FN == "b_pci_state") return (t ~ /^\$dev\/(class|enable|power_state|config)$/ || t ~ /^\$z\/(hard|soft|type|operstate)$/)
		if (FN == "b_wq_bme") return (t == "$WQ_ROOT$dev/config")
		if (FN == "b_wq_resolve") return (t == "$WQ_ROOT$path/driver" || t == "$d/module")
		if (FN == "b_wq_slot") return (t == "$WQ_ROOT$path/driver")
		if (FN == "b_wq_governor_read") return (t == "$WQ_ROOT/sys/devices/system/cpu/cpufreq/$p/scaling_governor")
		if (FN == "b_wq_oops") return (t == "$WQ_ROOT/sys/fs/cgroup$cg/cgroup.procs")
		if (FN == "s1_rl") return (t == "$1")
		return 0
	}
	function isnum(s) { return s ~ /^[0-9]+$/ }
	function isvar(s) { return s ~ /^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$/ }
	function plain(s) { return s != "" && s !~ /^-/ }
	function A(dp, k, j) { return W[dp, k + j] }
	function dollar(k,   nx, j, p, ch, s) {
		nx = substr(T, k + 1, 1)
		if (nx == "(") {
			if (substr(T, k + 2, 1) == "(") { j = skiparith(k + 3, 2); cur = cur "$((..))"; return j }
			push("subst")
			return k + 2
		}
		if (nx == "{") {
			p = 0
			for (j = k + 1; j <= n; j++) {
				ch = substr(T, j, 1)
				if (ch == "{") p++
				else if (ch == "}") { p--; if (p == 0) break }
				else if (ch == "\n") break
			}
			s = substr(T, k, j - k + 1)
			if (ch != "}") bad("an unterminated ${")
			if (s ~ /\$\(|`/) bad("a command substitution inside ${ }")
			cur = cur s
			return j + 1
		}
		if (nx == "\047") { bad("an ANSI-C $\047...\047 quote"); return k + 2 }
		cur = cur "$"
		return k + 1
	}
	function skiparith(k, p,   ch) {
		for (; k <= n; k++) {
			ch = substr(T, k, 1)
			if (ch == "$" && substr(T, k + 1, 1) == "(" && substr(T, k + 2, 1) != "(") bad("a command substitution inside $(( ))")
			if (ch == "`") bad("a backtick")
			if (ch == "(") p++
			else if (ch == ")") { p--; if (p == 0) return k + 1 }
		}
		bad("an unterminated (( ))")
		return n + 1
	}
	function skiparray(k,   ch, p) {
		p = 0
		for (; k <= n; k++) {
			ch = substr(T, k, 1)
			if (ch == "(") p++
			else if (ch == ")") { p--; if (p == 0) { cur = cur "(..)"; return k + 1 } }
			else if (ch == "`" || (ch == "$" && substr(T, k + 1, 1) == "(")) bad("a substitution inside an array literal")
			else if (ch == "\n") break
		}
		bad("an unterminated array literal")
		return k
	}
	function skippat(k,   ch, j) {
		for (; k <= n; k++) {
			ch = substr(T, k, 1)
			if (ch == "\047") { j = index(substr(T, k + 1), "\047"); k += j; continue }
			if (ch == "\"") { for (k++; k <= n && substr(T, k, 1) != "\""; k++) if (substr(T, k, 1) == "\\") k++; continue }
			if (ch == "\\") { k++; continue }
			if (ch == "$" && substr(T, k + 1, 1) == "(") bad("a command substitution in a case pattern")
			if (ch == "`") bad("a backtick")
			if (ch == ")") return k + 1
			if (ch == "\n") { bad("a case pattern without )"); return k + 1 }
		}
		return k
	}
	function redir(k,   op, ch, t, j) {
		while (substr(T, k, 1) ~ /[0-9]/) k++
		op = substr(T, k, 1); k++
		ch = substr(T, k, 1)
		if ((op == ">" && (ch == ">" || ch == "&" || ch == "|" || ch == "(")) || (op == "<" && (ch == "<" || ch == "&" || ch == ">" || ch == "("))) { op = op ch; k++ }
		while (substr(T, k, 1) == " " || substr(T, k, 1) == "\t") k++
		t = ""
		while (k <= n) {
			ch = substr(T, k, 1)
			if (ch ~ /[ \t\n;|&()<>]/) break
			if (ch == "\047") { j = index(substr(T, k + 1), "\047"); t = t substr(T, k + 1, j - 1); k += j + 1; continue }
			if (ch == "\"") {
				k++
				while (k <= n && substr(T, k, 1) != "\"") {
					if (substr(T, k, 1) == "\\") k++
					else if (substr(T, k, 2) == "$(" || substr(T, k, 1) == "`") bad("a substitution in a redirect target")
					t = t substr(T, k, 1); k++
				}
				k++
				continue
			}
			if (ch == "$" && substr(T, k + 1, 1) == "(") { bad("a substitution in a redirect target"); k += 2; continue }
			t = t ch; k++
		}
		NR2[depth]++; ROP[depth, NR2[depth]] = op; RTG[depth, NR2[depth]] = t
		return k
	}
	function checkredir(op, t) {
		wordcheck(t)
		if (op == ">&" || op == "<&") { if (t !~ /^([0-9]|-)$/) bad("a descriptor redirect to " t); return }
		if (op == "<") { if (t != "/dev/null" && !readpath(t)) bad("an input redirect from " t); return }
		if (op == ">" || op == ">>") {
			if (t == "/dev/null") return
			if (t == "$WQ_LOG" && op == ">>") return
			if (t == "$WQ_KMSG" && op == ">") return
			if (op == ">" && t ~ /^\$WQ_ROOT\/sys\/bus\/(pci|platform)\/drivers\/\$drv\/unbind$/) return
			if (op == ">" && t == "/sys/module/kernel/parameters/initcall_debug" && FN == "b_trace_on") return
			bad("a redirect to " t)
			return
		}
		bad("the redirect operator " op)
	}
	function checkcmd(dp,   k, r) {
		k = 1
		while (k <= NW[dp] && W[dp, k] ~ /^(if|then|else|elif|do|while|until|!|\{|\}|fi|done|esac)$/) {
			if (W[dp, k] == "{") brace++
			if (W[dp, k] == "}") { brace--; if (brace == 0) FN = "" }
			k++
		}
		for (r = 1; r <= NR2[dp]; r++) checkredir(ROP[dp, r], RTG[dp, r])
		if (k > NW[dp] || W[dp, k] == "for") return
		while (k <= NW[dp] && W[dp, k] ~ /^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=/) k++
		if (k > NW[dp]) return
		ncmd++
		# outside the functions only the one last call runs (the header is assignments only)
		if (FN == "") { ntop++; if (!(W[dp, k] in DEFS)) { bad("the command " W[dp, k] " outside the functions"); return } }
		checkform(dp, k)
	}
	function checkform(dp, k,   c, na, j, ok, line) {
		c = W[dp, k]; na = NW[dp] - k
		if (c in DEFS) return
		if (c ~ /^(local|echo|printf|read|return|exit|shift|break|continue|true|false|:|\[|test)$/) return
		# the command words §15.5 A5 refuses by name, and the builtins that could run or hide one
		if (c ~ /^(rfkill|nmcli|iw|dd|tar|apt|apt-get|dpkg|extlinux|devmem|lsusb|hciconfig)$/) { bad("the command " c " is refused explicitly"); return }
		if (c ~ /^(eval|exec|source|\.|trap|alias|builtin|command|enable|set|unset|export|declare|typeset|let|coproc|mapfile|readarray|kill|function|select|time)$/) { bad("the builtin " c " is not on the allow-list"); return }
		if (c == "timeout") {
			j = k + 1
			if (W[dp, j] == "-k") { if (!isnum(W[dp, j + 1])) { bad("timeout -k needs a number"); return } j += 2 }
			if (!(isnum(W[dp, j]) || isvar(W[dp, j]))) { bad("timeout needs a duration"); return }
			if (j + 1 > NW[dp]) { bad("timeout without a command"); return }
			checkform(dp, j + 1)
			return
		}
		if (c == "sudo") {
			if (W[dp, k + 1] != "-n" || k + 2 > NW[dp] || FN != "b_freq") { bad("sudo other than the sudo -n of b_freq, with an allowed command"); return }
			checkform(dp, k + 2)
			return
		}
		ok = 0
		# each form exactly as the functions use it, and the acting ones only in their own function
		if (c == "cat") { ok = (na >= 1); for (j = 1; j <= na; j++) if (!readpath(A(dp, k, j))) ok = 0 }
		else if (c == "od") ok = (na == 5 && A(dp, k, 1) == "-An" && A(dp, k, 2) == "-tu1" && A(dp, k, 3) == "-j4" && A(dp, k, 4) == "-N2" && readpath(A(dp, k, 5)) && A(dp, k, 5) ~ /\/config$/)
		else if (c == "ip") ok = (FN == "b_wq_slot" && na == 5 && A(dp, k, 1) == "link" && A(dp, k, 2) == "set" && A(dp, k, 3) == "dev" && A(dp, k, 4) == "$WQ_W_NETDEV" && A(dp, k, 5) == "down")
		else if (c == "modprobe") ok = (FN == "b_wq_slot" && na == 2 && A(dp, k, 1) == "-r" && A(dp, k, 2) == "$WQ_W_MOD")
		else if (c == "setpci") ok = (FN == "b_wq_bme" && na == 3 && A(dp, k, 1) == "-s" && A(dp, k, 2) == "${dev##*/}" && (A(dp, k, 3) == "COMMAND" || A(dp, k, 3) == "COMMAND=0000:0004"))
		else if (c == "kexec") ok = (na == 1 && A(dp, k, 1) == "-u" && FN ~ /^b_wq_(abort|issue|fallback)$/)
		else if (c == "systemctl") {
			if (na == 1 && A(dp, k, 1) == "kexec") { nkexec++; ok = (FN == "b_wq_issue") }
			else if (na == 1 && A(dp, k, 1) == "reboot") ok = (FN ~ /^b_wq_(abort|issue|fallback)$/)
			else if (na == 1 && A(dp, k, 1) == "is-system-running") ok = (FN ~ /^b_wq_(issue|fallback)$/)
			else if (na == 2 && A(dp, k, 1) == "reboot" && A(dp, k, 2) == "--force") ok = (FN == "b_wq_fallback")
			else if (na == 2 && A(dp, k, 1) == "is-active" && A(dp, k, 2) ~ /^[A-Za-z0-9_.@-]+\.service$/) ok = (FN == "b_pci_state")
		}
		else if (c == "sync") ok = (na == 0)
		else if (c == "sleep") ok = (na == 1 && (isnum(A(dp, k, 1)) || isvar(A(dp, k, 1))))
		else if (c == "dmesg") ok = ((na == 0 && FN ~ /^b_wq_(main|oops|fallback)$/) || (na == 2 && A(dp, k, 1) == "-n" && A(dp, k, 2) == "7" && FN == "b_trace_on"))
		else if (c == "sha256sum") { ok = (na >= 1); for (j = 1; j <= na; j++) if (!readpath(A(dp, k, j))) ok = 0 }
		else if (c == "date") { ok = 1; for (j = 1; j <= na; j++) if (A(dp, k, j) !~ /^(\+[%A-Za-z:T-]+|-u)$/) ok = 0 }
		else if (c == "readlink") ok = ((na == 3 && A(dp, k, 1) == "-e" && A(dp, k, 2) == "--" && readpath(A(dp, k, 3))) || (na == 2 && A(dp, k, 1) == "-e" && readpath(A(dp, k, 2))))
		# grep reads stdin only: options, then one pattern, no file
		else if (c == "grep") { ok = (na >= 1 && na <= 3 && plain(A(dp, k, na))); for (j = 1; j < na; j++) if (A(dp, k, j) !~ /^-[cEFqivx]+$/) ok = 0 }
		else if (c == "ps") ok = (na == 4 && A(dp, k, 1) == "-o" && A(dp, k, 2) ~ /^[a-z,]+=$/ && A(dp, k, 3) == "-p" && isvar(A(dp, k, 4)))
		else { bad("the command " c " is not on the allow-list"); return }
		if (!ok) { line = c; for (j = 1; j <= na; j++) line = line " " A(dp, k, j); bad("the form \047" line "\047 is not on the allow-list") }
	}
	{ L[NR] = $0; T = T $0 "\n" }
	END {
		nl = NR
		# lines: shebang, header, functions, the last call
		if (L[1] != "#!/bin/bash") bad("line 1 is not #!/bin/bash")
		split(funcs, FA, " ")
		for (i in FA) WANT[FA[i]] = 1
		hdr = 1
		for (i = 2; i <= nl; i++) {
			s = L[i]
			if (s ~ /^[A-Za-z_][A-Za-z0-9_]* \(\) *$/) {
				f = s; sub(/ .*/, "", f)
				if (f in DEFS) bad("function " f " defined twice")
				DEFS[f] = 1; hdr = 0
				continue
			}
			if (!hdr) continue
			if (s == "" || s ~ /^# [ -~]*$/) continue
			if (match(s, /^(WQ_[A-Z0-9_]+|XHCI_PATH)=/)) {
				k = substr(s, 1, RLENGTH - 1); v = substr(s, RLENGTH + 1)
				if (v != "\047\047" && v !~ /^([A-Za-z0-9_.\/:@,+=%-]|\\.)+$/) bad("the header value of " k " is not a plain printf %q token")
				if (k in HV) bad("the header sets " k " twice")
				HV[k] = v
				continue
			}
			bad("header line " i " is neither a comment nor a WQ_ assignment")
		}
		for (f in WANT) if (!(f in DEFS)) bad("function " f " of WQ_FUNCS is missing")
		for (f in DEFS) if (!(f in WANT)) bad("function " f " is not in WQ_FUNCS")
		last = nl
		while (last > 1 && L[last] == "") last--
		want = (kind == "main") ? "b_wq_main >> \"$WQ_LOG\" 2>&1" : "b_wq_fallback >> \"$WQ_LOG\" 2>&1"
		if (kind != "main" && kind != "fallback") bad("unknown script kind " kind)
		if (L[last] != want) bad("the last line is not the one call for " kind)
		if (HV["WQ_KIND"] != kind) bad("WQ_KIND is not " kind)
		if (HV["WQ_KMSG"] != "/dev/kmsg") bad("WQ_KMSG is not /dev/kmsg")
		if (HV["WQ_ROOT"] != "\047\047") bad("WQ_ROOT is not empty")
		if (HV["WQ_LOG"] !~ /^\/[A-Za-z0-9._\/-]+\/[A-Za-z0-9][A-Za-z0-9._-]*-[0-9]{8}T[0-9]{6}Z-wq\.log$/) bad("WQ_LOG is not <home>/<name>-<utc>-wq.log")
		if (!((HV["WQ_ARM"] ~ /^(control|remove)$/ && HV["WQ_FINAL"] == "kexec") || (HV["WQ_ARM"] == "j3" && HV["WQ_FINAL"] == "none"))) bad("WQ_ARM and WQ_FINAL are not a pair the design allows")
		split(consts, CA, " ")
		for (i in CA) { split(CA[i], kvp, "="); if (HV[kvp[1]] != kvp[2]) bad(kvp[1] " is not the design constant " kvp[2]) }
		# the member values the functions act on: sysfs device paths, bus function names and
		# plain driver, module and interface names only
		for (i = 1; i <= 4; i++) {
			m = "WQ_" substr("WXEN", i, 1) "_"
			if (HV[m "IN"] !~ /^(yes|no)$/ || HV[m "RPCLEAR"] !~ /^(yes|no)$/) bad(m "IN or " m "RPCLEAR is not yes or no")
			v = HV[m "PATH"]
			if (v != "none" && (v !~ /^\/sys\/devices\/[A-Za-z0-9@:._\/+-]+$/ || v ~ /\/\.\.(\/|$)/)) bad(m "PATH is not none or a /sys/devices path")
			if (HV[m "BDF"] != "none" && HV[m "BDF"] !~ /^[0-9a-f][0-9a-f][0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f][.][0-7]$/) bad(m "BDF is not none or a PCI function name")
			if (HV[m "RP"] != "none" && HV[m "RP"] !~ /^[0-9a-f][0-9a-f][0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f][.][0-7]$/) bad(m "RP is not none or a PCI function name")
			if (HV[m "DRV"] !~ /^[A-Za-z0-9_.-]+$/ || HV[m "MOD"] !~ /^[A-Za-z0-9_.-]+$/ || HV[m "NETDEV"] !~ /^[A-Za-z0-9_.-]+$/) bad(m "DRV, MOD or NETDEV is not a plain name")
		}
		if (HV["WQ_TRACE"] !~ /^(yes|no)$/ || HV["WQ_SETPCI"] !~ /^(yes|no)$/) bad("WQ_TRACE or WQ_SETPCI is not yes or no")
		for (i = 1; i <= 2; i++) {
			v = HV[i == 1 ? "WQ_HOME_DEV" : "WQ_KD_DEV"]
			if (v !~ /^(\/sys\/[A-Za-z0-9@:._\/+-]+|unresolved|none|network)$/ || v ~ /\/\.\.(\/|$)/) bad("WQ_HOME_DEV or WQ_KD_DEV is not a /sys path, unresolved, none or network")
		}
		if (HV["XHCI_PATH"] != "\047\047" && (HV["XHCI_PATH"] !~ /^\/sys\/devices\/[A-Za-z0-9@:._\/+-]+$/ || HV["XHCI_PATH"] ~ /\/\.\.(\/|$)/)) bad("XHCI_PATH is not empty or a /sys/devices path")
		if (HV["WQ_UTC"] !~ /^[0-9]{8}T[0-9]{6}Z$/) bad("WQ_UTC is not a utc stamp")
		if (HV["WQ_OOPS0"] != "0") bad("WQ_OOPS0 is not 0")
		# explicit refusals, anywhere in the text (§15.5 A5)
		for (i = 1; i <= nl; i++) {
			s = L[i]
			if (s ~ /\/(etc|boot)(\/|[^A-Za-z0-9_.-]|$)/) bad("line " i ": a path under /etc or /boot")
			if (s ~ /\/var\/lib/) bad("line " i ": a path under /var/lib")
			if (s ~ /\/dev\/mem|devmem/) bad("line " i ": /dev/mem or devmem")
			if (s ~ /\/dev\/(tcp|udp)/) bad("line " i ": a /dev/tcp or /dev/udp socket path")
			if (s ~ /of=/) bad("line " i ": of=")
			if (s ~ /--force[ \t]+--force/) bad("line " i ": --force --force")
			if (s ~ /(^|[ \t])-ff([ \t;]|$)/) bad("line " i ": -ff")
			if (s ~ /\/(remove|rescan|reset)([^A-Za-z0-9_]|$)|driver_override|new_id|power\/control/) bad("line " i ": a write path remove, rescan, reset, driver_override, new_id or power/control")
			if (s ~ /address|serial|lsusb|hciconfig|nmcli|extlinux|dpkg/) bad("line " i ": address, serial, lsusb, hciconfig, nmcli, extlinux or dpkg")
			if (s ~ /(^|[^A-Za-z0-9_.-])ip[ \t]+a(d|dd|ddr|ddre|ddres|ddress)?([ \t;]|$)/) bad("line " i ": ip addr")
			if (s ~ /systemctl[ \t]+(enable|disable|mask|stop|isolate)/) bad("line " i ": systemctl enable, disable, mask, stop or isolate")
			if (s ~ /<<|<\(|>\(|`/) bad("line " i ": a heredoc, here-string, process substitution or backtick")
			if (s ~ /\[\[/) bad("line " i ": [[")
			if (s ~ /systemctl[ \t]+reboot[ \t]+--force/) nforce++
		}
		if (nforce != 1) bad("systemctl reboot --force appears " (nforce + 0) " times, not exactly once")
		# the lexer: every simple command and redirect
		n = length(T); depth = 0; NW[0] = 0; NR2[0] = 0; CL[0] = 0; cur = ""; dq = 0; inw = 0; FN = ""; brace = 0
		i = 1
		while (i <= n) {
			c = substr(T, i, 1)
			if (!dq && !inw && CL[depth] > 0 && CS[depth, CL[depth]] == "pat") {
				if (c == " " || c == "\t" || c == "\n" || c == ";") { i++; continue }
				if (substr(T, i, 4) == "esac" && (i + 4 > n || substr(T, i + 4, 1) ~ /[ \t\n;)]/)) { CL[depth]--; i += 4; continue }
				i = skippat(i)
				CS[depth, CL[depth]] = "body"
				continue
			}
			if (dq) {
				if (c == "\\") { cur = cur substr(T, i + 1, 1); i += 2; continue }
				if (c == "\"") { dq = 0; i++; continue }
				if (c == "`") { bad("a backtick"); i++; continue }
				if (c == "$") { i = dollar(i); continue }
				cur = cur c; i++
				continue
			}
			if (!inw && NW[depth] == 0 && NR2[depth] == 0 && match(substr(T, i, 80), /^[A-Za-z_][A-Za-z0-9_]* \(\) *\n/)) {
				FN = substr(T, i, RLENGTH); sub(/ .*/, "", FN)
				i += RLENGTH
				continue
			}
			if (c == " " || c == "\t") { endword(); i++; continue }
			if (c == "\n") { endcmd(); i++; continue }
			if (c == ";") {
				if (substr(T, i + 1, 1) == ";") {
					endcmd()
					if (CL[depth] > 0 && CS[depth, CL[depth]] == "body") CS[depth, CL[depth]] = "pat"
					else bad("a ;; outside a case item")
					i += 2
					continue
				}
				endcmd(); i++
				continue
			}
			if (c == "#" && !inw) { while (i <= n && substr(T, i, 1) != "\n") i++; continue }
			if (c == "\047") {
				j = index(substr(T, i + 1), "\047")
				if (!j) { bad("an unterminated single quote"); break }
				cur = cur substr(T, i + 1, j - 1); inw = 1; i += j + 1
				continue
			}
			if (c == "\"") { dq = 1; inw = 1; i++; continue }
			if (c == "\\") { cur = cur substr(T, i + 1, 1); inw = 1; i += 2; continue }
			if (c == "`") { bad("a backtick"); i++; continue }
			if (c == "$") { inw = 1; i = dollar(i); continue }
			if (c == "&") {
				if (substr(T, i + 1, 1) == "&") { endcmd(); i += 2; continue }
				bad("a background & or an &> redirection"); endcmd(); i++
				continue
			}
			if (c == "|") { endcmd(); i += (substr(T, i + 1, 1) == "|") ? 2 : 1; continue }
			if (!inw && substr(T, i, 4) ~ /^[0-9]*[<>]/) { i = redir(i); continue }
			if (c == "<" || c == ">") { endword(); i = redir(i); continue }
			if (c == "(") {
				if (!inw && substr(T, i + 1, 1) == "(") { i = skiparith(i + 2, 2); continue }
				if (inw && cur ~ /^[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=$/) { i = skiparray(i); continue }
				endcmd(); push("sub"); i++
				continue
			}
			if (c == ")") {
				endcmd()
				if (depth == 0) { bad("an unbalanced )"); i++; continue }
				if (pop() == "subst") { cur = cur "$(..)"; inw = 1 }
				i++
				continue
			}
			cur = cur c; inw = 1; i++
		}
		endcmd()
		if (nkexec != 1) bad("systemctl kexec appears " (nkexec + 0) " times, not exactly once")
		if (ntop != 1) bad((ntop + 0) " commands run outside the functions, not only the one last call")
		if (depth != 0 || dq) bad("an unterminated quote or command substitution")
		if (ncmd < 50) bad("only " (ncmd + 0) " commands were read: the lexer did not see the script")
		if (nbad) { print "wqgate " name " FAIL refused=" nbad " commands=" (ncmd + 0); exit 1 }
		print "wqgate " name " ok commands=" ncmd " functions=" length(DEFS)
	}' "$1"
}

# §15.5 A5: a systemd-run command line, exactly as it will be sent over ssh (the board's
# shell expands $HOME). $1 main|fallback, $2 the line, $3 the utc, $4 the script's file
# name, $5 WQ_FALLBACK_S. Anything but the exact form is refused.
wq_gate_runline() {
	local want
	[[ "$3" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] && [[ "$4" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*-wq(fb)?\.sh$ ]] && [[ "$5" =~ ^[0-9]+$ ]] \
		|| { echo "wqgate runline $1 refused: the utc, script name or fallback seconds are malformed"; return 1; }
	case "$1" in
	fallback) want="sudo -n systemd-run --unit=s1wqfb-$3 --on-active=${5}s --timer-property=AccuracySec=1s --collect /bin/bash \"\$HOME/$4\"" ;;
	main)     want="sudo -n systemd-run --unit=s1wq-$3 --collect --no-block -p TimeoutStopSec=30 /bin/bash \"\$HOME/$4\"" ;;
	*)        echo "wqgate runline refused: unknown kind $1"; return 1 ;;
	esac
	if [ "$2" = "$want" ]; then
		echo "wqgate runline $1 ok"
		return 0
	fi
	echo "wqgate runline $1 refused: not the exact allowed systemd-run form (§15.5 A5)"
	return 1
}

# Both scripts and both lines: bash -n, wq_gate, wq_gate_runline. $1 wq.sh, $2 wqfb.sh,
# $3 the main line, $4 the fallback line, $5 utc, $6 WQ_FALLBACK_S. Prints the gate lines.
wq_gate_all() {
	local rc=0 o
	for o in "$1:main" "$2:fallback"; do
		if bash -n "${o%:*}" 2>/dev/null; then echo "wqgate $(basename "${o%:*}") bash-n ok"; else echo "wqgate $(basename "${o%:*}") bash-n FAIL"; rc=1; fi
		wq_gate "${o%:*}" "${o##*:}" || rc=1
	done
	wq_gate_runline main "$3" "$5" "$(basename "$1")" "$6" || rc=1
	wq_gate_runline fallback "$4" "$5" "$(basename "$2")" "$6" || rc=1
	return "$rc"
}

# ---------------------------------------------------------------- J2, J2b, J3 and J4 on the PC (§15.4.3-§15.4.6)

# Phase A's session bounds for the detached arms (§15.4.3: every ssh session carries its own
# bound as its timeout). With the fixed quiesce bound and Phase B's own worst case they give
# the start margin (j_worst_case); a snapshot or its fetch that runs out is recorded, never a stop.
JA_GOV_S=60
JA_KPF_S=60
JA_KPF_FETCH_S=120
JA_QUIESCE_S=500
JA_PCI_S=30
JA_LOAD_S=60
JA_SEND_S=60
# The arming and starting sessions stay well under WQ_START_DELAY_S (15 s): a start session that
# runs out after systemd-run did start the unit still leaves time to stop it before slot 1.
JA_ARM_S=10
# PC-side work between the uptime read and the issue that no ssh bound covers (the generation,
# bash -n, the allow-list gate and the privacy scans): an allowance, not a timeout.
JA_PC_S=30

# jrun b2repeat goes through cmd_run with these set; empty for every B rung.
JRUN=""
JDIAG=""
J_Q17_LINE=""
# jrun s1-j1 (J6): the parser's extra arguments, and the factor and kpf headers canwatch reads.
J6_PARGS=()
J6_FACTOR=""
J6_KPF=()
JPREREG=""
JGATE=""
J_RETURN_HOOK=""
J_UNITS_UTC=""

j_scp() { timeout "$1" scp "${ssh_work[@]}" "$2" "$3" </dev/null >/dev/null 2>&1; }

# The sha256 of J-set.conf's member lines (the removal set as pre-registered), or '-'.
j_set_members_sha() {
	[ -f "$RECDIR/J-set.conf" ] || { echo -; return; }
	grep '^member=' "$RECDIR/J-set.conf" | sha256sum | cut -d' ' -f1
}

# The members J-set.conf's rules keep in the set, comma-separated, or none.
j_set_in_members() {
	[ -f "$RECDIR/J-set.conf" ] || { echo none; return; }
	awk '/^member=/ && index($0, " in_set=yes ") { split($1, a, "="); s = s (s == "" ? "" : ",") a[2] } END { print (s == "" ? "none" : s) }' "$RECDIR/J-set.conf"
}

# §15.5 A1: jrun accepts s1-h1 with control, remove or b2repeat, and s1-j1 (J6, §15.4.8) with
# control or remove only (J6 is J2's or J4's harness arm; no J2b of the watcher); anything else
# is refused.
jrun_args() {
	case "$1" in
	s1-h1) ;;
	s1-j1)
		case "$2" in
		control|remove) ;;
		b2repeat) die "jrun s1-j1 runs the control or remove arm only (§15.4.8): b2repeat is J2b's, with s1-h1" ;;
		esac ;;
	*)     die "jrun accepts s1-h1 and s1-j1 only (§15.5 A1); '$1' is refused" ;;
	esac
	case "$2" in
	control|remove|b2repeat) ;;
	*) die "jrun's arm is control, remove or b2repeat; '$2' is refused" ;;
	esac
}

# §15.5 A1: STEP and MODE for a J arm, set after resolve_kimg so image_step's B2 for s1-h1 (and
# J6 for s1-j1) never reaches a record path. $1 control|remove|b2repeat|j3, $2 the image (s1-j1
# gives J6c or J6r; anything else, or none, the s1-h1 steps).
jrun_step() {
	case "${2:-}:$1" in
	s1-j1:control) STEP=J6c ;;
	s1-j1:remove)  STEP=J6r ;;
	s1-j1:*)       die "no J6 step for '$1'" ;;
	*:control)     STEP=J2 ;;
	*:remove)      STEP=J4 ;;
	*:b2repeat)    STEP=J2b ;;
	*:j3)          STEP=J3 ;;
	*) die "no J step for '$1'" ;;
	esac
	MODE=host
}

# Q17 (§15.4.1): IMG.params' kimg_sha256 must be a real hash, not '-' (a regeneration with
# the default output root writes that, §15.7.4), and equal the PC's kimg's sha256; the
# board's staged copy is compared in Phase A. Dies otherwise; prints one line.
j_q17_check() {
	local img="$1" dir="${S1_KIMG_DIR:-$HERE/../shim/out/s1}" want have
	[ -f "$dir/$img.params" ] && [ -f "$dir/$img.kimg" ] || die "Q17: no $img.kimg and $img.params under S1_KIMG_DIR"
	want="$(awk -F= '$1 == "kimg_sha256" { print substr($0, 13); exit }' "$dir/$img.params" | tr -d '\r')"
	[[ "$want" =~ ^[0-9a-f]{64}$ ]] \
		|| die "Q17: $img.params' kimg_sha256 is '${want:-missing}', not a real hash: a generator run with the default output root overwrote it (§15.7.4). Restore the staged build's params"
	have="$(sha256sum "$dir/$img.kimg" | cut -d' ' -f1)"
	[ "$want" = "$have" ] || die "Q17: $img.params' kimg_sha256 $want is not $img.kimg's sha256 $have"
	echo "q17 $img.params kimg_sha256 is a real hash equal to $img.kimg's; the staged copy is compared on the board"
}

# The newest board log of a J step among <rec>/<STEP> and <rec>/<STEP>-aN (by the utc in its
# name; refused attempts are not counted). $1 STEP. Prints the path, or nothing.
j_newest_board() {
	local f u best="" bu=""
	for f in "$RECDIR/$1"/*-board.log "$RECDIR/$1"-a[0-9]*/*-board.log; do
		[ -f "$f" ] || continue
		u="$(basename "$f" | sed -n 's/.*-\([0-9]\{8\}T[0-9]\{6\}Z\)-board\.log$/\1/p')"
		if [ -n "$u" ] && [[ "$u" > "$bu" ]]; then bu="$u"; best="$f"; fi
	done
	[ -n "$best" ] && printf '%s\n' "$best"
	return 0
}

# D34 (§15.6.1, owner, 2026-09-14): F39's immediate stop waived for J3 and J4 only. 0 when
# <rec>/J-waivers.conf holds 'D34_F39=yes' and J2's parse shows c2 bad at both checks with c1
# ok at both, so the waiver never covers a control whose window-1 canary failed. $1 J2's parse.
j_waiver_f39() {
	local w="$RECDIR/J-waivers.conf" p="$1"
	grep -qx 'D34_F39=yes' "$w" 2>/dev/null || return 1
	grep -qx 'S1PC c2_start=bad' "$p" 2>/dev/null && grep -qx 'S1PC c2_end=bad' "$p" 2>/dev/null \
		&& grep -qx 'S1PC c1_start=ok' "$p" 2>/dev/null && grep -qx 'S1PC c1_end=ok' "$p" 2>/dev/null
}

# 0 when <rec>/J-waivers.conf holds the owner's '$1=yes' line (D34_F39, D27, D27_J6C, D27_J6R).
j_waiver() { grep -qx "$1=yes" "$RECDIR/J-waivers.conf" 2>/dev/null; }

# The newest parse row of a J step (parse-s1.txt beside its newest board log), or empty. J2, J2b
# and J4 print one token; J6's is a comma list of every §15.4.8 row that holds. $1 STEP.
j_step_row() {
	local b
	b="$(j_newest_board "$1")"
	[ -n "$b" ] && sed -n 's/^S1PC j_row=//p' "$(dirname "$b")/parse-s1.txt" 2>/dev/null | tail -n 1
	return 0
}

# 0 when the row list $1 holds the code $2 (membership in a comma list, J6's form; a single
# token, J2's and J4's form, is a list of one).
j_row_has() { case ",$1," in *",$2,"*) return 0 ;; *) return 1 ;; esac; }

# The TCG records launch-s1tcg.ps1 writes (qhv/s1tcg/attempt<N>/parse-s1.txt, §14.4 V), where T-J1's
# verdict is. Not read from the environment; only the self-tests point it at a synthetic copy.
J6_TCG_RECORDS="$HERE/../../qhv/s1tcg"

# Prints 't_j1 met <attempt>' when a TCG attempt's parse-s1.txt shows T-J1 with verdict diagnostic
# complete and the memcanary-w pin that s1-j1.params carries, so the watcher J6 would run is the one
# whose self-test passed (§15.4.8 preconditions); returns 1, printing nothing, otherwise.
j6_tj1_met() {
	local pin f a=""
	pin="$(j6_pkey "${S1_KIMG_DIR:-$HERE/../shim/out/s1}/s1-j1.params" memcanary_w_sha256)"
	[[ "$pin" =~ ^[0-9a-f]{64}$ ]] || return 1
	for f in "$J6_TCG_RECORDS"/attempt*/parse-s1.txt; do
		[ -f "$f" ] || continue
		tr -d '\r' < "$f" | grep -qx 'S1PC step=T-J1' || continue
		tr -d '\r' < "$f" | grep -qx 'S1PC verdict=diagnostic complete' || continue
		tr -d '\r' < "$f" | grep -qx "S1PC memcanary_w_sha256=$pin" || continue
		a="$(basename "$(dirname "$f")")"
	done
	[ -n "$a" ] || return 1
	echo "t_j1 met $a"
}

# How many J board logs recorded a kexec about to be issued ('run com3_bytes_before_kexec='): the
# revision's kexec diagnostic runs so far, harness-reason retries included. §15.6's budget of four
# does not count those retries, so this is printed for the owner, never a refusal.
j_kexec_runs() {
	local s f n=0
	for s in J2 J2b J4 J5 J6c J6r; do
		for f in "$RECDIR/$s"/*-board.log "$RECDIR/$s"-a[0-9]*/*-board.log; do
			[ -f "$f" ] && grep -aq '^run com3_bytes_before_kexec=' "$f" && n=$(( n + 1 ))
		done
	done
	echo "$n"
}

# §15.4.8 'Run' and §15.6: J6's arm, as refusals. Both need D27 (the owner's, after J4's memo) in
# J-waivers.conf, no J6 row so far with F39 or F49 (§15.6's immediate stops), and T-J1 met with the
# image's memcanary-w pin (j6_tj1_met). J2's own F39 was waived by D34 for J3 and J4 only (§15.6.1),
# so when J2's row holds F39 a J6 run also needs the owner's 'D34_J6=yes'. j6control (J6c)
# follows J4's F36, J2's F32a or F32b, or J2b's F46; j6remove (J6r) follows J4's F35. Otherwise the
# arm runs only by the owner's D27 for it: D27_J6C=yes or D27_J6R=yes. Prints the reason and the
# kexec runs so far (j_kexec_runs). $1 the arm.
j6_precondition() {
	local r2 r2b r4 s why="" d34="" tj1
	j_waiver D27 || die "J6 needs D27 (build s1-j1 and run J6, §15.6): the owner's 'D27=yes' is not in J-waivers.conf (§15.4.8 preconditions)"
	for s in J6c J6r; do
		r2="$(j_step_row "$s")"
		if j_row_has "$r2" F39 || j_row_has "$r2" F49; then
			die "the newest $s parse row '$r2' holds F39 or F49, an immediate stop (§15.6): no further J6 run; the owner decides"
		fi
	done
	r2="$(j_step_row J2)"; r2b="$(j_step_row J2b)"; r4="$(j_step_row J4)"
	if j_row_has "$r2" F39; then
		j_waiver D34_J6 || die "J2's row is F39, an immediate stop that D34 waived for J3 and J4 only (§15.6.1): a J6 run after it needs the owner's 'D34_J6=yes' in J-waivers.conf"
		d34="; J2's F39 is under D34, extended to J6 by the owner's D34_J6"
	fi
	tj1="$(j6_tj1_met)" || die "T-J1 has not met with this memcanary-w: no qhv/s1tcg attempt's parse-s1.txt shows step T-J1, verdict diagnostic complete and s1-j1.params' memcanary_w_sha256 (§15.4.8 preconditions, §15.5 B8.5)"
	case "$1" in
	j6control)
		if [ "$r4" = F36 ]; then why="J4's row is F36"
		elif [ "$r2" = F32a ] || [ "$r2" = F32b ]; then why="J2's row is $r2"
		elif [ "$r2b" = F46 ]; then why="J2b's row is F46"
		elif j_waiver D27_J6C; then why="the owner's D27_J6C (the other arm, §15.4.8)"
		else die "J6c runs after J4's F36, J2's F32a or F32b, or J2b's F46, or by the owner's D27_J6C=yes in J-waivers.conf (§15.4.8); the rows are J2=${r2:-none} J2b=${r2b:-none} J4=${r4:-none}"
		fi ;;
	j6remove)
		if [ "$r4" = F35 ]; then why="J4's row is F35"
		elif j_waiver D27_J6R; then why="the owner's D27_J6R (the other arm, §15.4.8)"
		else die "J6r runs after J4's F35, or by the owner's D27_J6R=yes in J-waivers.conf (§15.4.8); J4's row is ${r4:-none}"
		fi ;;
	*) die "no J6 arm '$1'" ;;
	esac
	echo "j6 precondition: $why$d34; $tj1; kexec_runs_before=$(j_kexec_runs) (§15.6's budget is four kexec diagnostic runs, harness-reason retries not counted); D27 in J-waivers.conf sha256=$(j_sha256 "$RECDIR/J-waivers.conf")"
}

# §15.4's ladder, as refusals: control after J1 met; b2repeat after J2's F33 or J1's F42 row;
# j3 after J2's F32 (or its F39 under D34); remove after J3 met; j6control and j6remove as
# j6_precondition. $1 the arm.
j_precondition() {
	local b1 b2 b3 row=""
	case "$1" in j6control|j6remove) j6_precondition "$1"; return 0 ;; esac
	b1="$(j_newest_board J1)"
	b2="$(j_newest_board J2)"
	b3="$(j_newest_board J3)"
	[ -n "$b2" ] && row="$(sed -n 's/^S1PC j_row=//p' "$(dirname "$b2")/parse-s1.txt" 2>/dev/null | tail -n 1)"
	case "$1" in
	control)
		{ [ -n "$b1" ] && grep -aq '^j1 next=J2 ' "$b1"; } \
			|| die "J2 needs J1 met: the newest J1 board log does not end in 'j1 next=J2' (§15.4.4; after J1's F42 row, J2b runs instead)" ;;
	b2repeat)
		{ [ "$row" = F33 ] || { [ -n "$b1" ] && grep -aq '^j1 next=J2b ' "$b1"; }; } \
			|| die "J2b runs only after J2's F33 or J1's F42 row (§15.4.4); the newest J2 row is ${row:-none}" ;;
	j3)
		if [ "$row" = F32 ]; then
			:
		elif [ "$row" = F39 ] && j_waiver_f39 "$(dirname "$b2")/parse-s1.txt"; then
			echo "j3 precondition: J2's row is F39, accepted under D34 (the owner's waiver for J3 and J4 only, §15.6.1; J-waivers.conf sha256=$(j_sha256 "$RECDIR/J-waivers.conf"))"
		else
			die "J3 runs only after J2's F32, or after its F39 under D34's waiver with c2 bad at both checks and c1 ok (§15.4.5, §15.6.1); the newest J2 parse row is ${row:-none}"
		fi ;;
	remove)
		{ [ -n "$b3" ] && grep -aq '^j3 RESULT MET' "$b3"; } \
			|| die "J4 needs J3 met: the newest J3 board log has no 'j3 RESULT MET' (§15.4.6)" ;;
	esac
}

# §15.4.3: the removal set for an arm, from J-set.conf and D24_SET. control: every member read
# only (IN=no). j3 and remove: the members J1's rules kept, all of them under D24_SET=max or
# the wireless function alone under D24_SET=wireless; remove falls back to wireless only when
# J3's last line in J-set.conf says so (pre-registered). Sets WQG_<L>_<KEY>, WQG_SETPCI,
# WQG_XHCI_PATH, J_SETDESC, J_SET_FB and J_REQ (the functions whose Bus Master must read 0).
j_set_select() {
	local arm="$1" f="$RECDIR/J-set.conf" line m L k set in
	[ -f "$f" ] || die "no J-set.conf in the record directory: run j1 first (§15.4.2)"
	set="$(j_decision_set)"
	J_SET_FB=no
	if [ "$arm" = remove ] && [ "$(grep '^j3 fallback=' "$f" | tail -n 1 | sed 's/^j3 fallback=\([a-z]*\).*/\1/')" = wireless ]; then
		J_SET_FB=yes
		set=wireless
	fi
	for L in W X E N; do
		for k in IN PATH BDF DRV MOD NETDEV RP RPCLEAR; do printf -v "WQG_${L}_$k" '%s' none; done
		printf -v "WQG_${L}_IN" '%s' no
	done
	J_SETDESC=""
	J_REQ=""
	while IFS= read -r line; do
		case "$line" in member=*) ;; *) continue ;; esac
		m="$(tok "$line" member)"
		case "$m" in wireless) L=W ;; xhci) L=X ;; ethernet) L=E ;; nvme) L=N ;; *) continue ;; esac
		printf -v "WQG_${L}_PATH" '%s' "$(tok "$line" path)"
		printf -v "WQG_${L}_BDF" '%s' "$(tok "$line" bdf)"
		printf -v "WQG_${L}_DRV" '%s' "$(tok "$line" driver)"
		printf -v "WQG_${L}_MOD" '%s' "$(tok "$line" module)"
		printf -v "WQG_${L}_NETDEV" '%s' "$(tok "$line" netdev)"
		printf -v "WQG_${L}_RP" '%s' "$(tok "$line" root_port)"
		printf -v "WQG_${L}_RPCLEAR" '%s' "$(tok "$line" rp_clear)"
		in=no
		if [ "$arm" != control ] && [ "$(tok "$line" in_set)" = yes ] && { [ "$set" = max ] || [ "$L" = W ]; }; then in=yes; fi
		printf -v "WQG_${L}_IN" '%s' "$in"
		if [ "$in" = yes ]; then
			J_SETDESC="${J_SETDESC:+$J_SETDESC,}$m"
			if [ "$L" != X ]; then
				J_REQ="$J_REQ $(tok "$line" bdf)"
				[ "$(tok "$line" rp_clear)" = yes ] && J_REQ="$J_REQ $(tok "$line" root_port)"
			fi
		fi
	done < "$f"
	if [ "$arm" != control ]; then
		grep -q '^note=no-j3-j4' "$f" && die "J-set.conf says no J3 or J4: \$HOME or KD resolves under the wireless function (§15.4.2)"
		[ "$WQG_W_IN" = yes ] || die "the wireless function is not in the set by J-set.conf's rules: no J3 or J4 (memo, §15.4.2)"
		[ "$WQG_W_NETDEV" != none ] || die "J-set.conf gives the wireless function no network interface: its slot 1 cannot be resolved"
	fi
	WQG_SETPCI="$(sed -n 's/^tools .*setpci=\([a-z]*\).*/\1/p' "$f" | tail -n 1)"
	[ "$WQG_SETPCI" = yes ] || WQG_SETPCI=no
	WQG_XHCI_PATH="$WQG_X_PATH"
	[ "$WQG_XHCI_PATH" = none ] && WQG_XHCI_PATH=""
	J_SETDESC="${J_SETDESC:-empty}"
	return 0
}

# §15.4.3's start margin: Phase A's bounds after the uptime read (governor, snapshots, the
# fixed quiesce bound, PCI read, load, send, arm and start, and the PC-side allowance), then
# Phase B up to the issue, or to the fallback's firing for J3 (no prequiesce snapshot there).
# The uptime is the last read of its session, and the page-flag decode runs only after the
# return, so neither falls outside these bounds. $1 the arm.
j_worst_case() {
	local w=$(( JA_GOV_S + JA_QUIESCE_S + JA_KPF_S + JA_KPF_FETCH_S + JA_PCI_S + JA_LOAD_S + JA_SEND_S + 2 * JA_ARM_S + JA_PC_S ))
	case "$1" in
	control|remove) echo $(( w + JA_KPF_S + JA_KPF_FETCH_S + $(wq_worst_case "$WQ_SLOT_COUNT") )) ;;
	j3)             echo $(( w + $(wq_fallback_s "$WQ_SLOT_COUNT") )) ;;
	*)              echo 999999 ;;
	esac
}

# §15.5 A1 gate B, just before the load (or, for b2repeat, the kexec session): the capture is
# still the rung's own (inside the record directory, in used-captures.log exactly once, the
# entry this rung wrote), holds no s1wq: marker or record line yet, is running, and has life
# for what is left: return bound + 1200 (b2repeat), + WQ_FALLBACK_S (control, remove), or
# WQ_FALLBACK_S + 1200 (j3). Prints one 'jgateB' line; non-zero on a refusal. $1 kind.
j_gate_b() {
	local kind="$1" f="${S1_COM3_LOG:-}" sv n left min cs
	sv="$(ssid_refusal "${S1_REDACT_SSID:-}")"
	if [ -n "$sv" ]; then echo "jgateB $kind FAIL: $sv"; return 1; fi
	if [ -z "$f" ] || [ ! -f "$f" ]; then echo "jgateB $kind FAIL: S1_COM3_LOG names no capture file"; return 1; fi
	if ! capture_inside_recdir "$f"; then echo "jgateB $kind FAIL: S1_COM3_LOG is not inside the git-ignored record directory (§15.5 A1)"; return 1; fi
	n="$(grep -cxF "$(basename "$f")" "$RECDIR/used-captures.log" 2>/dev/null)"
	if [ "${n:-0}" != 1 ]; then echo "jgateB $kind FAIL: $(basename "$f") is in used-captures.log ${n:-0} times, not once (this rung's own entry)"; return 1; fi
	if j_capture_has_prior "$f"; then echo "jgateB $kind FAIL: the capture holds s1wq: markers or record lines before this rung issued anything"; return 1; fi
	cs="$(capture_state "$f")"
	if [ "$cs" != running ]; then echo "jgateB $kind FAIL: the capture is $cs, not running"; return 1; fi
	left="$(capture_left_s)"
	if ! [[ "$left" =~ ^-?[0-9]+$ ]]; then echo "jgateB $kind FAIL: the capture header has no epoch=/seconds= ($left)"; return 1; fi
	case "$kind" in
	b2repeat) min=$(( RETURN_BOUND + 1200 )) ;;
	j3)       min=$(( $(wq_fallback_s "$WQ_SLOT_COUNT") + 1200 )) ;;
	*)        min=$(( RETURN_BOUND + 1200 + $(wq_fallback_s "$WQ_SLOT_COUNT") )) ;;
	esac
	if (( left < min )); then echo "jgateB $kind FAIL: the capture has $left s left, under $min s"; return 1; fi
	echo "jgateB $kind ok: capture_left_s=$left min_s=$min used_once=yes earlier_records=none running=yes"
	return 0
}

# §15.4.3's rule-5 exception on the PC: the sequence's files in the board's home directory are
# fetched (wq.log, sha256-verified, into the J directory whose board log has the same
# <name>-<utc>, else $1) or compared with the PC's as-sent copy (the scripts), then removed
# with b_rmfiles; every removal, and anything left behind, is recorded. $2 yes runs
# privacy_scan on a fetched wq.log at once (a leftover); no leaves it to the caller. Sets
# WQ_UNITS to the s1wq units systemd still lists (empty when none).
j_wq_collect() {
	local dest="$1" scan="${2:-yes}" out line name want d f pre rmf="" left=""
	WQ_UNITS=unread
	WQ_LEFT="unread"
	if ! out="$(board 60 b_wq_files)"; then
		rec "wq files: the board session failed: nothing fetched or removed"
		return 1
	fi
	WQ_UNITS="$(printf '%s\n' "$out" | sed -n 's/^wqunit //p')"
	while IFS= read -r line; do
		name="$(tok "$line" name)"
		want="$(tok "$line" sha256)"
		if ! [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*-[0-9]{8}T[0-9]{6}Z-(wq\.sh|wqfb\.sh|wq\.log)$ ]]; then
			rec "wq files: a listed name is not a sequence file name: left on the board"
			left="$left (unnamed)"
			continue
		fi
		pre="${name%-wq.sh}"; pre="${pre%-wqfb.sh}"; pre="${pre%-wq.log}"
		d="$dest"
		for f in "$RECDIR"/J*/"$pre"-board.log; do [ -f "$f" ] && d="$(dirname "$f")"; done
		if [ -f "$d/$name" ] && [ "$(j_sha256 "$d/$name")" = "$want" ]; then
			rec "wq files: $name equals the copy in $(basename "$d")"
			rmf="$rmf $name"
		elif [ "$name" != "${name%.sh}" ] && [[ "$want" =~ ^[0-9a-f]{64}$ ]] && grep -aqF "${name##*-} sha256=$want" "$d"/*-board.log 2>/dev/null; then
			rec "wq files: $name equals the as-sent sha256 recorded in $(basename "$d")'s board log (the local copy is redacted)"
			rmf="$rmf $name"
		elif [ -f "$d/$name" ] && [ "$name" != "${name%.sh}" ]; then
			rec "wq files: $name on the board DIFFERS from the as-sent copy in $(basename "$d"): left on the board"
			left="$left $name"
		elif j_scp 120 "$ORIN_HOST:$name" "$d/$name" && [ "$(j_sha256 "$d/$name")" = "$want" ]; then
			rec "wq files: $name copied to $(basename "$d") bytes=$(stat -c %s "$d/$name") sha256=$want, equal to the board's"
			check_private "$d/$name"
			[ "$scan" = yes ] && privacy_scan "$d/$name"
			rmf="$rmf $name"
		else
			rec "wq files: $name copy FAILED or differs from the board's: left on the board"
			left="$left $name"
		fi
	done < <(printf '%s\n' "$out" | grep '^wqfile ')
	[ -n "$rmf" ] && RMFILES="$rmf" board 60 b_rmfiles | rec_pipe
	WQ_LEFT="${left# }"
	if [ -n "$left" ]; then rec "wq files LEFT on the board:$left"; else rec "wq files: no sequence file left on the board"; fi
	[ -n "$WQ_UNITS" ] && rec "wq units still listed: $(printf '%s\n' "$WQ_UNITS" | awk '{ print $1 }' | tr '\n' ' ')"
	return 0
}

# Stops both units of one sequence (the ARMED stop, §15.4.6, and Phase A's failure path).
j_stop_units() {
	[[ "$1" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || return 1
	board 60 "sudo -n systemctl stop s1wq-$1.service s1wqfb-$1.timer s1wqfb-$1.service </dev/null" 'echo "wq_units_stop_rc=$?"' | rec_pipe
}

# The s1wq: marker lines of stdin (CR removed): a printk time or caller id stripped, J1's
# probe lines left out.
j_wq_lines() {
	LC_ALL=C awk '{ s = $0; sub(/^[ \t]+/, "", s); sub(/^[^ -~]+[ \t]*/, "", s); sub(/[ \t]+$/, "", s); sub(/^\[ *[0-9]+\.[0-9]+\] */, "", s); sub(/^\[ *[CT][0-9]+\] */, "", s); if (s ~ /^s1wq: / && s !~ /^s1wq: j1 /) print s }'
}

# §15.4.6's state from COM3 after the offset, a pure function of the capture and the clock:
#   JUMPED   'kexec_core: Starting new kernel', 'T234-SHIM', or a record line of the image (S1, STAMP, BWAIT, T234, t234:)
#   ABORTED  'abort reason=', 'kexec did not happen' or 'fallback firing'
#   ISSUED   'kexec issuing'
#   STALLED  no new marker by the fixed schedule's bound (begin by the start delay + 60 s; slot
#            n by the start delay + n x WQ_SLOT_S + 60 s; the final marker after the final
#            reads + 60 s; after 'no final action', the fallback deadline + 60 s)
#   ARMED    no marker yet;  PROGRESS  markers, none of the above
# $1 the capture, $2 the offset, $3 armed_epoch, $4 now. Prints 'wq state=... ' and 'wq last_marker='.
wq_state() {
	tail -c +"$(( $2 + 1 ))" "$1" 2>/dev/null | tr -d '\r' | LC_ALL=C awk -v armed="$3" -v now="$4" -v sd="$WQ_START_DELAY_S" -v ss="$WQ_SLOT_S" \
		-v fr="$WQ_FINAL_READS_S" -v fb="$(wq_fallback_s "$WQ_SLOT_COUNT")" -v nslots="$WQ_SLOT_COUNT" '
	{
		s = $0
		sub(/^[ \t]+/, "", s); sub(/^[^ -~]+[ \t]*/, "", s); sub(/[ \t]+$/, "", s)
		# record lines of the image prove the jump too, when COM3 lost both texts (as com3_wq_class)
		if (s ~ /kexec_core: Starting new kernel/ || s ~ /T234-SHIM/ || s ~ /^(S1 |STAMP |BWAIT |T234 |t234: )/) jump = 1
		m = s
		sub(/^\[ *[0-9]+\.[0-9]+\] */, "", m); sub(/^\[ *[CT][0-9]+\] */, "", m)
		if (m !~ /^s1wq: / || m ~ /^s1wq: j1 /) next
		nm++; last = m
		if (m ~ /^s1wq: slot[0-9]+ [a-z-]+ result=/) { k = m; sub(/^s1wq: slot/, "", k); sub(/ .*/, "", k); if (k + 0 > maxslot) maxslot = k + 0 }
		if (m ~ /^s1wq: begin /) begun = 1
		if (m == "s1wq: kexec issuing") issuing = 1
		if (m ~ /^s1wq: no final action/) fnone = 1
		if (m ~ /^s1wq: (abort reason=|kexec did not happen|fallback firing)/) abort = 1
		if (m ~ /^s1wq: fallback firing/) fired = 1
	}
	END {
		fbd = armed + fb
		if (!begun && maxslot == 0) nd = armed + sd + 60
		else if (fnone) nd = fbd + 60
		else if (maxslot < nslots) nd = armed + sd + (maxslot + 1) * ss + 60
		else nd = armed + sd + nslots * ss + fr + 60
		if (jump) st = "JUMPED"
		else if (abort) st = "ABORTED"
		else if (issuing) st = "ISSUED"
		else if (now + 0 > nd) st = "STALLED"
		else if (nm == 0) st = "ARMED"
		else st = "PROGRESS"
		printf "wq state=%s markers=%d slots=%d issuing=%s final_none=%s abort=%s fallback_fired=%s jump=%s next_deadline=%d fallback_deadline=%d\n", \
			st, nm, maxslot, (issuing ? "yes" : "no"), (fnone ? "yes" : "no"), (abort ? "yes" : "no"), (fired ? "yes" : "no"), (jump ? "yes" : "no"), nd, fbd
		printf "wq last_marker=%s\n", last
	}'
}

# §15.4.6's PC progress: COM3 every S1_POLL_S (10) s after the offset. ssh, once a minute, only
# while COM3 shows no marker of the sequence (the ARMED stop) and again after the fallback
# deadline (a new boot_id with no jump text on COM3): once markers arrive, the PC reads COM3
# only, in every arm, so the arms differ in nothing but the removal set (§15.4.3 Phase B
# step 1). $1 the old boot_id, $2 the offset, $3 armed_epoch. Sets WQ_END: JUMPED or ABORTED
# (COM3), BACK (a new boot_id first; NEW_BOOT_ID set), STOPPED (ARMED past its bound while the
# old boot answers), or GIVEUP (none of those by the fallback deadline + 600 s; extended once
# by 600 s while an issued shutdown's COM3 still grows: a slow shutdown is not a hang).
wait_wq() {
	local old="$1" off="$2" armed="$3" now line st prev="" bid lastssh=0 deadline ext=0 sz lastsz=-1 grow fbd
	grow=$(date +%s)
	fbd=$(( armed + $(wq_fallback_s "$WQ_SLOT_COUNT") ))
	deadline=$(( fbd + 600 ))
	# s1-j1's host run outlasts that bound: a lost jump text must not give up while QNX still watches
	[ "${IMG:-}" = s1-j1 ] && (( fbd + RETURN_BOUND > deadline )) && deadline=$(( fbd + RETURN_BOUND ))
	WQ_END=""
	while :; do
		now=$(date +%s)
		line="$(wq_state "$S1_COM3_LOG" "$off" "$armed" "$now" | head -n 1)"
		st="$(tok "$line" state)"
		if [ "$st" != "$prev" ]; then
			rec "wait_wq +$(( now - armed )) s: ${line#wq }"
			prev="$st"
		fi
		sz=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)
		if [ "$sz" != "$lastsz" ]; then lastsz="$sz"; grow="$now"; fi
		case "$st" in JUMPED|ABORTED) WQ_END="$st"; return 0 ;; esac
		if (( now - lastssh >= 60 )) && { [ "$(tok "$line" markers)" = 0 ] || (( now >= fbd )); }; then
			lastssh="$now"
			bid="$(read_boot_id)"
			if [[ "$bid" =~ ^[0-9a-f-]{36}$ ]]; then
				if [ "$bid" != "$old" ]; then NEW_BOOT_ID="$bid"; WQ_END=BACK; return 0; fi
				if [ "$st" = STALLED ] && [ "$(tok "$line" markers)" = 0 ]; then WQ_END=STOPPED; return 0; fi
			fi
		fi
		if (( now >= deadline )); then
			if [ "$st" = ISSUED ] && [ "$ext" = 0 ] && (( now - grow < 60 )); then
				deadline=$(( deadline + 600 ))
				ext=1
				rec "wait_wq: the fallback deadline + 600 s passed after the issue while COM3 still grows: extended once by 600 s (a slow shutdown is not a hang)"
			else
				WQ_END=GIVEUP
				return 0
			fi
		fi
		sleep "${S1_POLL_S:-10}"
	done
}

# §15.4.4-§15.4.6 records from the raw capture after the offset (never the redacted copy, whose
# bytes before the offset may differ): -wq-com3-markers.txt; the check that wq.log's s1wq: lines
# are a subsequence of COM3's; -pci-pre.log and -pci-final.log split out of wq.log; then the
# privacy scan of each (wq.log's dmesg tail included). $1 wq.log, $2 raw capture, $3 offset, $4 base.
j_wq_after() {
	local wql="$1" raw="$2" off="$3" b="$4" mk t
	mk="$b-wq-com3-markers.txt"
	{
		printf '# %s: evaluation output, NC QDL v7 4.6(i), unpublished\n' "$(basename "$mk")"
		tail -c +"$(( off + 1 ))" "$raw" 2>/dev/null | tr -d '\r' | j_wq_lines
	} > "$mk"
	check_private "$mk"
	rec "wq com3 markers=$(grep -c '^s1wq: ' "$mk") slot_overruns=$(grep -c '^s1wq: overrun ' "$mk") record=$(basename "$mk")"
	if [ -f "$wql" ]; then
		awk 'FILENAME != cur { cur = FILENAME; fi++ }
		fi == 1 && /^s1wq: / { w[++nw] = $0; next }
		fi == 2 && /^s1wq: / { if (k < nw && $0 == w[k + 1]) k++ }
		END { printf "wq subsequence wq_log_markers=%d in_order_on_com3=%d %s\n", nw, k, (k == nw ? "consistent" : "DIFFER first_missing=" w[k + 1]) }' \
			<(tr -d '\r' < "$wql") "$mk" | rec_pipe
		for t in pre final; do
			{
				printf '# %s: evaluation output, NC QDL v7 4.6(i), unpublished\n' "$(basename "$b-pci-$t.log")"
				grep -aE "^(pci|usbhost|xhci|rfkill|netdev|svc) $t " "$wql"
			} > "$b-pci-$t.log"
			check_private "$b-pci-$t.log"
			privacy_scan "$b-pci-$t.log"
		done
		privacy_scan "$wql"
	else
		rec "wq no wq.log was fetched: no subsequence check, no -pci-pre and -pci-final records"
	fi
	privacy_scan "$mk"
}

# §15.4.4: -trace.txt, the per-device shutdown lines on COM3 after the offset, up to the jump or
# restart line, redacted. $1 raw capture, $2 offset, $3 the file.
j_trace_file() {
	{
		printf '# %s: evaluation output, NC QDL v7 4.6(i), unpublished\n' "$(basename "$3")"
		tail -c +"$(( $2 + 1 ))" "$1" 2>/dev/null | tr -d '\r' \
			| awk '{ s = $0; sub(/[ \t]+$/, "", s); if (s ~ /kexec_core: Starting new kernel|Restarting system/) done = 1; if (!done && s ~ /: shutdown(_pre)?$/) print s }'
	} > "$3"
	check_private "$3"
	rec "wq trace $(com3_trace_counts "$1" "$2") lines_kept=$(grep -vc '^#' "$3") record=$(basename "$3")"
	privacy_scan "$3"
}

# §15.4.3 Phase A failures after the load: stop any armed unit, read kexec_loaded, unload,
# collect and remove the sequence's files, exit 3. The stop and the unload are claimed only
# when a read after them confirms it (kexec_loaded=0, and no unit of this sequence listed);
# otherwise the units may still run (a start session that ran out after systemd-run started
# the unit, and a board whose network the sequence already took down), so the log gets a
# wq_armed line if it has none, and the owner is sent to COM3 and advice, whose hold applies.
# Reads j_detached's locals (kw, SD, base).
j_phase_a_fail() {
	local out loaded units=yes
	ON_DIE=j_phase_a_last
	rec "$kw PHASE A FAILED after the load: $1"
	[ -n "$J_UNITS_UTC" ] && j_stop_units "$J_UNITS_UTC"
	out="$(board 60 'echo "kexec_loaded_before_unload=$(cat /sys/kernel/kexec_loaded)"' b_unload)"
	printf '%s\n' "$out" | rec_pipe
	loaded="$(kv kexec_loaded "$out")"
	j_wq_collect "$SD" yes
	if [ -n "$J_UNITS_UTC" ]; then
		case "$WQ_UNITS" in unread|*"$J_UNITS_UTC"*) units=no ;; esac
	fi
	j_kpf_decode_after
	if [ "$loaded" = 0 ] && [ "$units" = yes ]; then
		rec "$kw no kexec: confirmed by a read after the stop and the unload (kexec_loaded=0, no unit of this sequence listed). L4T is still running and quiesced: '$PROG reboot' before another attempt (exit 3, §15.4.3)"
	else
		j_phase_a_unconfirmed "kexec_loaded=${loaded:-unread} units_gone=$units"
	fi
	check_private "$REC"
	exit 3
}

# The unconfirmed end of a Phase A failure (also after a die inside it). $1 what was read.
j_phase_a_unconfirmed() {
	if [ -n "$J_UNITS_UTC" ] && ! grep -aq '^wq_armed ' "$REC" 2>/dev/null; then
		rec "wq_armed armed_epoch=$(date +%s) wq_fallback_s=$(wq_fallback_s "$WQ_SLOT_COUNT")"
	fi
	rec "$kw NOT CONFIRMED ($1): the stop and the unload could not be shown, so the detached sequence or its fallback may still run and reboot L4T$([ "$kw" = jrun ] && echo ' or issue the kexec'). Keep the capture running, read COM3 with '$(repo_rel "$HERE/$PROG") wq-status $(repo_rel "$REC")', and run '$(repo_rel "$HERE/$PROG") advice $(repo_rel "$REC")' before power is touched: its hold applies (exit 3, §15.4.3, §15.7.3)"
}

# ON_DIE after a die inside j_phase_a_fail: nothing more is tried.
j_phase_a_last() {
	ON_DIE=""
	j_phase_a_unconfirmed "a harness step died inside the failure path"
	check_private "$REC"
	exit 3
}

# ON_DIE from the load until the sequence runs: a die (a redaction failure, say) is a Phase A
# failure after the load, never exit 1.
j_phase_a_die() { j_phase_a_fail "a harness step died (the FAIL line above)"; }

# ON_DIE from the boot's marking until the load: the board is pinned and perhaps quiesced, with
# nothing loaded and no unit armed.
j_quiesced_die() {
	ON_DIE=""
	rec "$kw a harness step died (the FAIL line above) after this boot was used: nothing loaded and no unit armed, but the governor is pinned and the board may be quiesced. '$PROG reboot' before another attempt (exit 3)"
	check_private "$REC"
	exit 3
}

# ON_DIE after the sequence ran and L4T came back: the records may be incomplete.
j_return_die() {
	ON_DIE=""
	rec "$kw a harness step died (the FAIL line above) while the return's records were written: they may be incomplete; L4T is back (exit 3)"
	check_private "$REC"
	exit 3
}

# The page-flag decode, record only, run after the rung's timed part (§15.4.3's start margin
# does not cover it). Reads base and kw.
j_kpf_decode_after() {
	local f
	local -a hd=()
	for f in "$base-kpf-prequiesce-header.txt" "$base-kpf-postquiesce-header.txt"; do [ -f "$f" ] && hd+=("$f"); done
	if [ "${#hd[@]}" -gt 0 ]; then kpf_decode_record "${hd[@]}" "$base-decode.txt"; else rec "$kw kpf decode not run: no header was fetched"; fi
}

# §15.4.4's last row: J2's Bus Master state at the issue, from wq.log's 'pci final' lines, for
# every PCI member J-set.conf names (its endpoint, and its single-child port). A named input to
# F35's Q-p / Q-x split (§15.4.6); it shows only the state before the shutdown, not whether
# the shutdown cleared it. Uses WQG_*. $1 wq.log.
j_bme_at_issue() {
	local wql="$1" L v bdf dev role line val
	for L in W E N; do
		v="WQG_${L}_BDF"; bdf="${!v}"
		[ "$bdf" != none ] || continue
		for role in endpoint port; do
			dev="$bdf"
			if [ "$role" = port ]; then
				v="WQG_${L}_RPCLEAR"; [ "${!v}" = yes ] || continue
				v="WQG_${L}_RP"; dev="${!v}"
			fi
			line="$(tr -d '\r' < "$wql" 2>/dev/null | grep -F "pci final dev=$dev " | tail -n 1)"
			val="$(tok "$line" bme)"
			case "$val" in 0|1) ;; *) val=unread ;; esac
			echo "bme_at_issue_control member=$L role=$role value=$val"
		done
	done
}

# J_RETURN_HOOK for a JUMPED jrun: the sequence's files, the markers, the subsequence check, the
# PCI records and the trace, before run_return_records' closing line. Reads j_detached's locals.
j_kexec_extras() {
	j_wq_collect "$SD" no
	if [ "$arm" = control ]; then
		if [ -f "$base-wq.log" ]; then j_bme_at_issue "$base-wq.log" | rec_pipe; else rec "bme_at_issue_control unread: no wq.log was fetched"; fi
	fi
	j_wq_after "$base-wq.log" "$S1_COM3_LOG" "$com3_off" "$base"
	j_kpf_decode_after
	if [ "$WQG_TRACE" = yes ]; then
		j_trace_file "$S1_COM3_LOG" "$com3_off" "$base-trace.txt"
	else
		rec "wq trace not carried (D21 or J1's go not met): no -trace.txt"
	fi
	check_private "$base-wq.sh" "$base-wqfb.sh" "$base-wq.log"
}

# J6 (§15.4.8, §15.5 B7) before run_return_records: the parser's J6 arguments. The factor is the
# registered one (J-prereg.log), the hold size s1-j1.params' j1_hold_mib, and the kpf headers the
# rung's own b_kpf_snap headers that were fetched (prequiesce first; none is a cpu-side-lean row,
# never a refusal). Sets J6_PARGS, J6_FACTOR and J6_KPF. $1 the arm, $2 the record base.
j6_parse_setup() {
	local arm="$1" b="$2" f
	J6_FACTOR="$(j6_prereg_factor)"
	J6_KPF=()
	for f in "$b-kpf-prequiesce-header.txt" "$b-kpf-postquiesce-header.txt"; do [ -f "$f" ] && J6_KPF+=("$f"); done
	J6_PARGS=(--arm "$arm" --fill-factor "$J6_FACTOR" --hold-mib "$(param j1_hold_mib)")
	for f in "${J6_KPF[@]}"; do J6_PARGS+=(--kpf "$f"); done
	rec "jrun j6 parse: --arm $arm --fill-factor $J6_FACTOR --hold-mib $(param j1_hold_mib) kpf_headers=${#J6_KPF[@]} (the registered factor; the rung's own snapshots)"
}

# J6 after the parser, still on the raw COM3 copy (before any privacy scan): the four exports
# the parser wrote (s1-j1a..d.bin, decoded from COM3's S1 BEGIN/S1 END frames by run's export
# path), 'parse-s1.py canwatch' into canwatch.txt (counts, classes and page bitmaps only, §15.1),
# and J6's stop rows. j_row is a comma list (§15.4.8's rows are not exclusive), so F39 and F49 are
# found by membership (j_row_has), never by equality. Reads SD, PY_BIN and the J6_* settings. $1
# the COM3 copy.
j6_after_parse() {
	local log="$1" out rc row l cw="$SD/canwatch.txt" res
	local -a cargs=(canwatch "$log" --fill-factor "$J6_FACTOR" --bin-dir "$SD" --out-dir "$SD")
	for l in a b c d; do
		if [ -f "$SD/s1-j1$l.bin" ]; then
			rec "run j6 export s1-j1$l.bin bytes=$(stat -c %s "$SD/s1-j1$l.bin") sha256=$(j_sha256 "$SD/s1-j1$l.bin")"
			check_private "$SD/s1-j1$l.bin"
		else
			rec "run j6 export s1-j1$l.bin NOT written by the parser (canwatch records it as absent)"
		fi
	done
	for l in "${J6_KPF[@]}"; do cargs+=(--kpf "$l"); done
	out="$(timeout 900 "$PY_BIN" "$PARSER" "${cargs[@]}" 2>&1)"
	rc=$?
	printf '%s\n' "$out" | grep -E '^parse-s1: ' | rec_pipe
	res="$(grep -a '^S1CW result=' "$cw" 2>/dev/null | tail -n 1)"
	rec "run canwatch rc=$rc ${res:-S1CW result=unwritten} (0 printed, 1 an input error, 2 a usage error or a refused output path; its record: $(basename "$SD")/canwatch.txt)"
	if [ -f "$cw" ]; then
		check_private "$cw"
		privacy_scan "$cw"
	fi
	row="$(sed -n 's/^S1PC j_row=//p' "$SD/parse-s1.txt" 2>/dev/null | tail -n 1)"
	rec "run j6 j_row=${row:-none}"
	if j_row_has "$row" F39 || j_row_has "$row" F49; then
		rec "run j6 IMMEDIATE STOP: j_row holds $(j_row_has "$row" F39 && echo F39)$(j_row_has "$row" F39 && j_row_has "$row" F49 && echo ' and ')$(j_row_has "$row" F49 && echo F49) (§15.6): stop; the owner decides; the exposure item is raised; no further J6 run (§15.4.8)"
	fi
}

# §15.5 A1's exit-5 return (F43, F47, F48, a fallback reboot: an abort, 'kexec did not happen'
# or fallback marker on COM3 after the offset): no black box and no parser. $1 the state.
j_return_aborted() { j_return_noparse aborted "$1"; }

# The returns with no QNX run to parse. Identity, pstore and nvbootctrl; for aborted, the abort
# marker's class; the previous console (-l4t-console-ramoops.log, never --blackbox: optional
# for aborted, always for f37 and unclassified, where it is the evidence); the sequence's files
# and markers; the COM3 copy; the decode. $1 aborted (exit 5, a harness-reason retry), f37
# (ISSUED, then a new boot with no shim line in the black box: an immediate stop, exit 3) or
# unclassified (no jump, abort or fallback marker and no shim line: exit 3, the owner reads
# the records); 4 on F30. $2 the state at the return.
j_return_noparse() {
	local mode="$1" st="$2" out newrec abort cls
	case "$mode" in
	aborted)
		rec "$kw ABORTED at the return ($st): no kexec happened. The black box is NOT copied and the parser NOT run (§15.5 A1)" ;;
	f37)
		rec "$kw F37 at the return: COM3 ends in L4T text after 'kexec issuing', with no jump on COM3 and no shim line in the black box: Linux hung in the detached shutdown and came back without a kexec (§15.4.6). IMMEDIATE STOP: the diagnosis ends for the day (§15.6); not a harness-reason retry. The black box is L4T's console, copied only as -l4t-console-ramoops.log; the parser is NOT run" ;;
	*)
		rec "$kw UNCLASSIFIED return ($st): no jump, abort, fallback or 'kexec did not happen' marker on COM3 after the offset, and no shim line in the black box. Not a harness-reason retry: the owner reads the records. The black box is copied only as -l4t-console-ramoops.log; the parser is NOT run" ;;
	esac
	out="$(board 120 b_identity b_pstore b_slots)" || rec "$kw warning: the return read ended with rc=$?"
	printf '%s\n' "$out" | grep -v '^slots ' | rec_pipe
	newrec="$(comm -13 <(printf '%s\n' "$pstore_before" | sort) <(printf '%s\n' "$out" | grep '^pstore ' | sort) | grep '^pstore dmesg-ramoops' || true)"
	if [ -n "$newrec" ]; then rec "$kw NEW dmesg-ramoops records (F27):"; printf '%s\n' "$newrec" | rec_pipe; fi
	slots_check "$out" "$base-nvbootctrl-post.log"
	slots_report "$kw" "$base-nvbootctrl-post.log"
	if [ "$mode" = aborted ]; then
		abort="$(tail -c +"$(( com3_off + 1 ))" "$S1_COM3_LOG" 2>/dev/null | tr -d '\r' | j_wq_lines | grep -E '^s1wq: (abort reason=|kexec did not happen|fallback firing|fallback forcing)' | head -n 1)"
		case "$abort" in
		*reason=oops*)                    cls=F47 ;;
		*reason=uptime*|*reason=governor*) cls=F48 ;;
		*reason=bme-not-cleared*)         cls=F44 ;;
		*reason=*|*"kexec did not happen"*) cls=F43 ;;
		*fallback*)                       cls="fallback (the sequence did not finish, §15.7.3 item 4)" ;;
		*)                                cls="no marker (a reboot with no abort marker on COM3)" ;;
		esac
		rec "$kw abort class=$cls marker='${abort:-none}': one harness-reason retry on a fresh boot; a second stops the day (§15.6)"
	fi
	if [ "$mode" != aborted ] || [ "${S1_J_L4T_CONSOLE:-}" = yes ]; then
		j_l4t_console
	else
		rec "$kw previous console not copied (S1_J_L4T_CONSOLE is not yes); it is never a black box"
	fi
	j_wq_collect "$SD" no
	j_wq_after "$base-wq.log" "$S1_COM3_LOG" "$com3_off" "$base"
	j_kpf_decode_after
	if cp "$S1_COM3_LOG" "$base-com3.log" 2>/dev/null; then
		rec "$kw COM3 copied: $(basename "$base-com3.log") bytes=$(stat -c %s "$base-com3.log") raw_sha256=$(j_sha256 "$base-com3.log"); L4T is back: stop the capture after this command returns"
		privacy_scan "$base-com3.log"
	else
		rec "$kw COM3 copy FAILED (the capture may hold the file)"
	fi
	check_private "$REC" "$base-com3.log" "$base-nvbootctrl-post.log"
	if [ "$SLOTS_STATE" = differ ]; then rec "$kw F30: STOP ALL BOARD WORK (exit 4)"; exit 4; fi
	case "$mode" in
	aborted) exit "$EXIT_SEQ_REBOOT" ;;
	f37)     rec "$kw F37: STOP. No further J rung today (§15.6 immediate stops; §15.7.3) (exit 3)"; exit 3 ;;
	*)       rec "$kw unclassified return: no retry is advised by the harness; the owner decides (exit 3)"; exit 3 ;;
	esac
}

# The previous boot's console as -l4t-console-ramoops.log: sha256-verified, scanned (the SSID
# class included), removed from the board; never passed as --blackbox. Reads name, base.
j_l4t_console() {
	local out want f="$base-l4t-console-ramoops.log"
	out="$(board 60 "JNAME=$name" b_l4t_console)"
	printf '%s\n' "$out" | rec_pipe
	want="$(tok "$(printf '%s\n' "$out" | grep '^l4tcon ')" sha256)"
	if [ -n "$want" ] && j_scp 120 "$ORIN_HOST:$name-l4t-console-ramoops.log" "$f" && [ "$(j_sha256 "$f")" = "$want" ]; then
		rec "$kw previous console copied: $(basename "$f") sha256=$want, equal to the board's (not a black box)"
		check_private "$f"
		privacy_scan "$f"
		RMFILES="$name-l4t-console-ramoops.log" board 60 b_rmfiles | rec_pipe
	else
		rec "$kw previous console copy FAILED: $name-l4t-console-ramoops.log may stay on the board"
	fi
}

# §15.4.5's J3 gates as rows, from the fetched wq.log ($1), the raw capture ($2) after the offset
# ($3), the return's PCI state file ($4), the units systemd still lists ($5) and the sequence
# files j_wq_collect left on the board ($6: empty when none). After the return every member
# J-set.conf names with a driver must be bound again, in the set or not. Uses WQG_* and J_REQ.
# Prints 'j3 row' lines and one last 'j3 RESULT MET|MET wireless-only|NOT MET <reasons>'.
j3_rows() {
	local wql="$1" raw="$2" off="$3" pr="$4" units="$5" left="${6:-}" com3m s r m n L v dev line fails="" nonw=""
	com3m="$(tail -c +"$(( off + 1 ))" "$raw" 2>/dev/null | tr -d '\r' | j_wq_lines)"
	s="$(printf '%s\n' "$com3m" | sed -n 's/^s1wq: slot\([0-9]*\) .*/\1/p' | tr '\n' ',')"
	if [ "$s" = "1,2,3,4,5,6,7,8,9," ]; then
		echo "j3 row markers MET: every slot marker on COM3, in order (R57)"
	else
		echo "j3 row markers NOT MET (F42): the slot markers on COM3 were '${s:-none}'"
		fails="$fails,markers"
	fi
	if [ ! -f "$wql" ]; then
		echo "j3 row wq.log NOT fetched: its steps cannot be read"
		fails="$fails,wq-log"
	fi
	r="$( { printf '%s\n' "$com3m"; tr -d '\r' < "$wql" 2>/dev/null; } | grep -o 'abort reason=[a-z-]*' | head -n 1)"
	if [ -n "$r" ]; then
		case "$r" in
		*oops) echo "j3 row $r (F47): an unbind or removal oopsed or hung" ;;
		*bme-not-cleared) echo "j3 row $r (F44): a required Bus Master bit stayed set" ;;
		*) echo "j3 row $r: the sequence refused before its steps" ;;
		esac
		fails="$fails,abort"
	fi
	for m in 1:W 2:W 3:W 4:W 5:X 6:E 7:E 8:N 9:N; do
		n="${m%%:*}"
		L="${m#*:}"
		v="WQG_${L}_IN"
		[ "${!v}" = yes ] || continue
		r="$(tr -d '\r' < "$wql" 2>/dev/null | sed -n "s/^s1wq: slot$n [a-z-]* result=\([^ ]*\)\$/\1/p" | tail -n 1)"
		if [ "$r" = 0 ] || { [ "$n" = 3 ] && [ "$r" = skip ] && [ "$WQG_W_MOD" = none ]; }; then continue; fi
		echo "j3 row slot$n result=${r:-absent}: not 0"
		if [ "$L" = W ]; then fails="$fails,wireless-slot$n"; else nonw="$nonw,slot$n"; fi
	done
	tr -d '\r' < "$wql" 2>/dev/null | grep '^bme_after_unbind ' | sed 's/^/j3 row /'
	for dev in $J_REQ; do
		line="$(tr -d '\r' < "$wql" 2>/dev/null | grep -F "pci final dev=$dev " | tail -n 1)"
		case "$line" in
		*" bme=0") ;;
		*) echo "j3 row Bus Master at the final read is ${line##* } on a required function, not 0"; fails="$fails,bme" ;;
		esac
	done
	if printf '%s\n' "$com3m" | grep -q '^s1wq: fallback firing$'; then
		echo "j3 row fallback firing on COM3, then a new boot_id (R59)"
	else
		echo "j3 row fallback firing NOT on COM3 (F42)"
		fails="$fails,fallback"
	fi
	if [ -z "$units" ]; then echo "j3 row units: no s1wq unit listed after the return"; else echo "j3 row units STILL LISTED after the return"; fails="$fails,units"; fi
	# after the return (R58): drivers bound, the interface up, rfkill 0, the network services active
	grep -F "pci return dev=$WQG_W_BDF " "$pr" 2>/dev/null | grep -qF " driver=$WQG_W_DRV " \
		|| { echo "j3 row F41: the wireless driver is not bound after the return"; fails="$fails,F41-wireless"; }
	grep -qF "netdev return if=$WQG_W_NETDEV operstate=up " "$pr" 2>/dev/null \
		|| { echo "j3 row F41: the wireless interface is not up after the return"; fails="$fails,F41-interface"; }
	if grep '^rfkill return ' "$pr" 2>/dev/null | grep -qv ' soft=0 hard=0$'; then echo "j3 row F41: an rfkill soft or hard state is not 0"; fails="$fails,F41-rfkill"; fi
	grep -q '^svc return NetworkManager=active wpa_supplicant=active$' "$pr" 2>/dev/null \
		|| { echo "j3 row F41: NetworkManager or wpa_supplicant is not active"; fails="$fails,F41-services"; }
	if [ "$WQG_X_DRV" != none ] && [ "$WQG_X_PATH" != none ]; then
		grep -qxF "xhci return present=yes driver=$WQG_X_DRV" "$pr" 2>/dev/null \
			|| { echo "j3 row F41: the xHCI driver is not bound after the return"; fails="$fails,F41-xhci"; }
	fi
	for L in E N; do
		v="WQG_${L}_BDF"; dev="${!v}"
		v="WQG_${L}_DRV"
		{ [ "$dev" != none ] && [ "${!v}" != none ]; } || continue
		grep -F "pci return dev=$dev " "$pr" 2>/dev/null | grep -qF " driver=${!v} " \
			|| { echo "j3 row F41: member $L's driver is not bound after the return"; fails="$fails,F41-$L"; }
	done
	if [ -n "$left" ]; then
		echo "j3 row sequence files NOT removed from the board after the return ($left)"
		fails="$fails,files-left"
	else
		echo "j3 row sequence files: removed from the board, and the removal recorded"
	fi
	if [ -z "$fails" ] && [ -z "$nonw" ]; then
		echo "j3 RESULT MET: detached removal and fallback recovery work on this L4T (§15.4.5)"
	elif [ -z "$fails" ]; then
		echo "j3 RESULT MET wireless-only: a non-wireless step failed (${nonw#,}) and the wireless steps passed: J4 uses the pre-registered wireless-only set"
	else
		echo "j3 RESULT NOT MET ${fails#,}${nonw:+ (also ${nonw#,})}: no J4 today (§15.4.5)"
	fi
}

# §15.4.5's return: the gates, the fallback line in J-set.conf, the records. No black box, no
# parser. Exit 0 (MET or NOT MET), 5 when the sequence aborted, 4 on F30. Reads j_detached's locals.
j3_return() {
	local out pr rows res newrec
	# J3 (2026-09-14): without XHCI_PATH the read printed no 'xhci return' line, and the xHCI
	# rebind gate failed on a board whose xHCI was bound again
	out="$(board 120 b_identity b_pstore b_slots "XHCI_PATH=$(printf '%q' "$WQG_XHCI_PATH") b_pci_state return")" || rec "j3 warning: the return read ended with rc=$?"
	printf '%s\n' "$out" | grep -E '^(boot_id|uptime_s)=|^pstore ' | rec_pipe
	pr="$base-pci-return.log"
	{
		printf '# %s: evaluation output, NC QDL v7 4.6(i), unpublished\n' "$(basename "$pr")"
		printf '%s\n' "$out" | grep -E '^(pci|usbhost|xhci|rfkill|netdev|svc) return '
	} > "$pr"
	check_private "$pr"
	newrec="$(comm -13 <(printf '%s\n' "$pstore_before" | sort) <(printf '%s\n' "$out" | grep '^pstore ' | sort) | grep '^pstore dmesg-ramoops' || true)"
	if [ -n "$newrec" ]; then rec "j3 NEW dmesg-ramoops records (F27, recorded):"; printf '%s\n' "$newrec" | rec_pipe; fi
	slots_check "$out" "$base-nvbootctrl-post.log"
	slots_report j3 "$base-nvbootctrl-post.log"
	rec "j3 black box NOT copied and parser NOT run: J3 has no QNX run (§15.4.5)"
	j_wq_collect "$SD" no
	rows="$(j3_rows "$base-wq.log" "$S1_COM3_LOG" "$com3_off" "$pr" "$WQ_UNITS" "$WQ_LEFT")"
	printf '%s\n' "$rows" | rec_pipe
	res="$(printf '%s\n' "$rows" | tail -n 1)"
	[ "$SLOTS_STATE" = same ] || rec "j3 nvbootctrl is $SLOTS_STATE, not equal to the first reading"
	case "$res" in
	"j3 RESULT MET wireless-only"*) printf 'j3 fallback=wireless utc=%s reason=a-non-wireless-step-failed\n' "$UTC" >> "$RECDIR/J-set.conf" ;;
	"j3 RESULT MET"*)               printf 'j3 fallback=none utc=%s\n' "$UTC" >> "$RECDIR/J-set.conf" ;;
	esac
	[ "${S1_J_L4T_CONSOLE:-}" = yes ] && j_l4t_console
	j_wq_after "$base-wq.log" "$S1_COM3_LOG" "$com3_off" "$base"
	privacy_scan "$pr"
	if cp "$S1_COM3_LOG" "$base-com3.log" 2>/dev/null; then
		rec "j3 COM3 copied: $(basename "$base-com3.log") bytes=$(stat -c %s "$base-com3.log") raw_sha256=$(j_sha256 "$base-com3.log"); stop the capture after this command returns"
		privacy_scan "$base-com3.log"
	else
		rec "j3 COM3 copy FAILED (the capture may hold the file)"
	fi
	rec "j3 done. Record: $(basename "$SD")/$(basename "$REC")"
	check_private "$REC" "$base-com3.log" "$base-nvbootctrl-post.log"
	if [ "$SLOTS_STATE" = differ ]; then rec "j3 F30: STOP ALL BOARD WORK (exit 4)"; exit 4; fi
	printf '%s\n' "$rows" | grep -q '^j3 row abort reason=' && exit "$EXIT_SEQ_REBOOT"
	return 0
}

# §15.4.3-§15.4.6: J2 (control), J4 (remove) and J3 (j3). Phase A over ssh, the detached
# sequence, COM3 progress, and the return paths. $1 the arm, $2 the image (s1-h1).
j_detached() {
	# J6c (2026-09-14): an s1-j1 run defers pre_ok to after gate A, and 'set -u' stopped it at
	# the first read; every local starts empty
	local arm="$1" img="$2" kw=jrun out="" old="" up="" rc="" wrc="" left="" gate="" worst="" name="" base="" q17="" pre_ok="" home="" homedev="" kddev="" trace=no j1b="" st="" jpre="" cmin=""
	local wq wqfb line_main line_fb fb_s armed com3_off gok gov0 gov4 rcs oops L v p SD pstore_before
	local conf="$S1DIR/s1-linux.conf" tree="" pc_conf_sha="" pc_image_sha="" pc_l4t_initrd_sha="" pc_initrd_sha="" conf_gate
	local pc_image="$S1DIR/out/l4t/Image" pc_l4t_initrd="$S1DIR/out/l4t/initrd" pc_initrd="$S1DIR/out/initrd.cpio.gz"
	local newrec shim reason lsha bb names n f want got rmfiles com3 pargs verdict slots_state_post j2b
	need_host
	need_record_dir
	j_norm_capture
	[ -n "${S1_COM3_LOG:-}" ] || die "S1_COM3_LOG must name the running capture-com3-raw.ps1 file, inside the record directory (§15.5 A1)"
	[ "$arm" = j3 ] && kw=j3
	if [ "$arm" != j3 ]; then q17="$(j_q17_check "$img")" || exit 1; fi
	IMG="$img"
	resolve_kimg "$IMG"
	jrun_step "$arm" "$img"
	[ "$arm" = j3 ] && RETURN_BOUND=1200
	KEXEC_MODE=s
	UTC="$(utc_now)"
	j_read_decisions
	j_require D20 "the J ledger (§15.6 D20)"
	j_require D22 "the snapshots, the PCI reads and the Bus Master clear (§15.6 D22)"
	j_require D25 "the detached sequence, exit 5 and the rule-5 exception (§15.6 D25)"
	[ "$arm" = remove ] && j_require D24 "J4 today (§15.6 D24)"
	j_decision_set >/dev/null
	j_require_clean_tree "$STEP"
	if [ "$img" = s1-j1 ]; then
		jpre="$(j_precondition "j6$arm")" || exit 1
	else
		j_precondition "$arm"
	fi
	[ "$arm" = j3 ] || run_pc_inputs
	j_set_select "$arm"
	j1b="$(j_newest_board J1)"
	if [ "$arm" != j3 ] && [ "$(j_decision D21)" = yes ] && [ -n "$j1b" ] && grep -aq '^j1 next=J2 trace=go$' "$j1b"; then trace=yes; fi
	# the J2 pre-registration is written once, by J2's first attempt over J1's draft, and never
	# rewritten by the harness afterwards: every later attempt and rung is checked against it.
	# It is found by its stage line, so J6's later stage never makes it look unwritten.
	if [ "$arm" = control ] && [ "$img" = s1-h1 ] && ! j_prereg_has_stage j2; then
		j_prereg_write "" "" j2 "$trace"
		note "J-prereg.log written as the J2 pre-registration, with the decisions taken now (§15.4.1); it is never rewritten by the harness"
	fi
	# an s1-j1 run's check needs J6's stage, which is appended after gate A below
	if [ "$img" != s1-j1 ]; then pre_ok="$(j_prereg_check "$img" "$arm")" || exit 1; fi
	# the trace is carried by J2 and J4 together or by neither (§15.4.6)
	if [ "$arm" != j3 ]; then
		[ "$(sed -n 's/^prereg trace=//p' "$RECDIR/J-prereg.log" | tail -n 1)" = "$trace" ] \
			|| die "J-prereg.log registered trace=$(sed -n 's/^prereg trace=//p' "$RECDIR/J-prereg.log" | tail -n 1), but this arm would run with trace=$trace: J2 and J4 carry the trace together or not at all (§15.4.6)"
		j2b="$(j_newest_board J2)"
		if [ "$arm" = remove ] && [ -n "$j2b" ]; then
			[ "$(sed -n 's/^jrun set in_this_arm=.* trace=\([a-z]*\) .*/\1/p' "$j2b" | tail -n 1)" = "$trace" ] \
				|| die "the newest J2 board log ran with trace=$(sed -n 's/^jrun set in_this_arm=.* trace=\([a-z]*\) .*/\1/p' "$j2b" | tail -n 1), but J4 would run with trace=$trace: the arms are matched (§15.4.6)"
		fi
	fi

	j_step_dir "$STEP"
	SD="$JSD"
	if [ "$arm" = j3 ]; then name="j3-$UTC"; else name="$IMG-$UTC"; fi
	base="$SD/$name"
	rec_open "$base-board.log"
	ON_DIE=run_refused_move
	rec "$kw arm=$arm step=$STEP image=$IMG utc=$UTC: the detached sequence (§15.4.3), FINAL=$([ "$arm" = j3 ] && echo none || echo kexec)"
	rec "$kw record_dir=$(basename "$RECDIR")/$(basename "$SD")"
	j_stamps "$WQ_SLOT_COUNT" | rec_pipe
	[ -n "$pre_ok" ] && rec "$kw $pre_ok"
	[ -n "$jpre" ] && rec "$kw $jpre"
	[ -n "$q17" ] && rec "$kw $q17"
	rec "$kw decisions D20=$(j_decision D20) D21=$(j_decision D21) D22=$(j_decision D22) D24=$(j_decision D24) D24_SET=$(j_decision D24_SET) D25=$(j_decision D25) D25_F25W_CUT=$(j_decision D25_F25W_CUT)"
	rec "$kw set in_this_arm=$([ "$arm" = control ] && echo empty || echo "$J_SETDESC") wireless_only_fallback=$J_SET_FB setpci=$WQG_SETPCI trace=$trace slots=$WQ_SLOT_COUNT"
	[ "$arm" != control ] && [ "$WQG_W_MOD" != none ] \
		&& rec "$kw note: slot 3's modprobe -r also unloads the dependencies of the wireless function's module that become unused (modprobe(8)); runtime-only, like the unbinds"
	if [ "$img" = s1-j1 ]; then
		# J6's host run (four watches, the hold, four exports) lies after the jump, in QNX: it adds
		# nothing to the start margin, which bounds L4T's uptime up to the issue (j_worst_case, the
		# same Phase A and Phase B as J2 and J4). It lengthens the return bound, and through it the
		# capture life of gates A and B, both taken from s1-j1.params (guard + 300 s, C14)
		cmin="$(j_capture_life_min "$arm" "$RETURN_BOUND" "$WQ_SLOT_COUNT")"
		rec "$kw j6 bounds from s1-j1.params: guard_s=$(param guard_s) return_bound_s=$RETURN_BOUND capture_s=$CAPTURE_S; capture life needed at gate A $cmin s (return bound + 2180 + fallback); start the capture with -Seconds $(( CAPTURE_S > cmin + 600 ? CAPTURE_S : cmin + 600 )) or more. The host run follows the jump, so the start margin is J2's and J4's"
	fi
	gate="$(j_capture_gate "$arm" "$WQ_SLOT_COUNT")" || die "gate A: ${gate#*FAIL: }"
	rec "$gate"
	if [ "$img" = s1-j1 ]; then
		# J6's stage (§15.4.1): appended by the arm's first attempt once gate A has passed and before
		# anything reads the board, so a refused capture registers nothing; then the full check
		j6_prereg_append "$arm"
		# ON_DIE is cleared in the check's subshell, so only this shell moves a refused attempt's records
		pre_ok="$(ON_DIE=""; j_prereg_check "$img" "$arm")" || die "J6's pre-registration check refused (above)"
		rec "$kw $pre_ok"
	fi
	left="$(capture_left_s)"
	if [ "$arm" != j3 ]; then
		cp "$PARAMS" "$base-params.log" || die "cannot copy $PARAMS into the record directory"
		check_private "$base-params.log"
		rec "run kimg=$IMG.kimg pc_sha256=$KIMG_SHA params_copy=$(basename "$base-params.log")"
		rec "run kexec_tree_sha256=$tree (p0's reading, for the parser)"
		rec "run pc_inputs conf_sha256=$pc_conf_sha conf_gate=pass (§8 PC item 2)"
	fi

	# the next command after a failed or cut path removes the sequence's leftovers first (§15.4.3)
	j_wq_collect "$SD" yes

	# step 1: the kimg, identity, the uptime, fresh-boot and start-margin gates, pstore, nvbootctrl;
	# the uptime is the session's last read, so nothing of the session runs after it
	out="$(board 300 b_sha b_pstore b_slots b_tree b_identity)" || die "board unreachable (rc=$?); nothing was changed on the board"
	printf '%s\n' "$out" | rec_pipe
	[ "$(kv board_sha256 "$out")" = "$KIMG_SHA" ] || die "Q17: the board's staged $IMG.kimg is not the PC's $KIMG_SHA: run stage"
	old="$(kv boot_id "$out")"
	up="$(kv uptime_s "$out")"
	[[ "$old" =~ ^[0-9a-f-]{36}$ ]] || die "no boot_id read"
	uptime_gate "$up" "$STEP"
	fresh_boot_gate "$old" "$STEP"
	worst="$(j_worst_case "$arm")"
	start_margin_gate "$up" "$worst" "$kw $STEP"
	pstore_before="$(printf '%s\n' "$out" | grep '^pstore ')"
	slots_check "$out" "$base-nvbootctrl-pre.log"
	slots_report "$kw" "$base-nvbootctrl-pre.log"
	case "$SLOTS_STATE" in
	differ) rec "$kw no quiesce and no sequence: L4T is still running"; check_private "$REC"; run_refused_move; exit 4 ;;
	unread) die "nvbootctrl could not be read before the rung (§8 item 13)" ;;
	esac
	mark_boot "$old" "$(printf '%s' "$STEP" | tr 'A-Z' 'a-z')"
	mark_capture "$S1_COM3_LOG"
	ON_DIE=j_quiesced_die

	# step 1: the governor pin and its read-back (always)
	out="$(board "$JA_GOV_S" b_governor 'b_freq pre')"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	gok="$(printf '%s\n' "$out" | grep -cE '^governor policy[04] performance rc=0$')"
	gov0="$(kv 'freq pre policy0 scaling_governor' "$out")"
	gov4="$(kv 'freq pre policy4 scaling_governor' "$out")"
	if [ "$rc" != 0 ] || [ "$gok" != 2 ] || [ "$gov0" != performance ] || [ "$gov4" != performance ]; then
		rec "$kw GOVERNOR PIN FAILED (session rc=$rc, governor_ok=$gok/2, policy0=$gov0 policy4=$gov4): no quiesce, nothing loaded. L4T is still running; reboot it before another attempt"
		check_private "$REC"
		exit 3
	fi

	# step 2 (J2, J4): the prequiesce snapshot
	if [ "$arm" != j3 ]; then
		j_kpf_snap prequiesce "$name" "$SD" "$JA_KPF_S" "$JA_KPF_FETCH_S" || rec "$kw prequiesce snapshot incomplete (recorded; the rung goes on)"
	fi

	# step 1: the quiesce (bound 500 s, as run's)
	out="$(board "$JA_QUIESCE_S" b_quiesce 'b_iomem run')"
	printf '%s\n' "$out" | grep -v '^iomemline ' | rec_pipe
	printf '%s\n' "$out" | sed -n 's/^iomemline run //p' | redact > "$base-iomem-postrmmod.log"
	rcs="$(printf '%s\n' "$out" | grep -c '^rmmod [a-z_]* rc=0$')"
	oops="$(kv quiesce_oops_lines "$out")"
	if [ "$rcs" != 4 ] || [ "${oops:-x}" != 0 ]; then
		rec "$kw QUIESCE FAILED (rmmod_ok=$rcs/4 oops_lines=${oops:-?}): nothing loaded, no unit armed. The board is part-quiesced: '$PROG reboot' before another attempt"
		check_private "$REC" "$base-iomem-postrmmod.log"
		exit 3
	fi

	# step 2: the postquiesce snapshot and PCI state, and the decode
	j_kpf_snap postquiesce "$name" "$SD" "$JA_KPF_S" "$JA_KPF_FETCH_S" || rec "$kw postquiesce snapshot incomplete (recorded; the rung goes on)"
	out="$(board "$JA_PCI_S" 'b_pci_state postquiesce')" || rec "$kw postquiesce PCI read ended with rc=$?"
	{
		printf '# %s: evaluation output, NC QDL v7 4.6(i), unpublished\n' "$(basename "$base-pci-postquiesce.log")"
		printf '%s\n' "$out"
	} > "$base-pci-postquiesce.log"
	check_private "$base-pci-postquiesce.log"
	privacy_scan "$base-pci-postquiesce.log"
	rec "$kw pci postquiesce functions=$(printf '%s\n' "$out" | grep -c '^pci ') record=$(basename "$base-pci-postquiesce.log")"
	rec "$kw kpf decode deferred to the return (record only; it would otherwise run inside the start margin)"

	# gate B: the capture, re-checked before anything is loaded or armed
	if ! gate="$(j_gate_b "$arm")"; then
		rec "$kw GATE B: ${gate#*FAIL: }: nothing loaded, no unit armed. The board is quiesced: '$PROG reboot', start a fresh capture, then run again"
		check_private "$REC"
		exit 3
	fi
	rec "$gate"

	# step 3: kexec -s -l (J3 too), kexec_loaded, the governor, the storage chain of $HOME and KD;
	# from here a die is a Phase A failure after the load (unload, stop, collect, exit 3)
	ON_DIE=j_phase_a_die
	out="$(board "$JA_LOAD_S" b_wq_load)"
	rc=$?
	printf '%s\n' "$out" | grep -v '^home=' | rec_pipe
	if [ "$rc" != 0 ] || [ "$(kv kexec_load_rc "$out")" != 0 ] || [ "$(kv kexec_loaded "$out")" != 1 ] \
		|| [ "$(kv governor_final_policy0 "$out")" != performance ] || [ "$(kv governor_final_policy4 "$out")" != performance ]; then
		j_phase_a_fail "the load, kexec_loaded or the governor read-back failed (session rc=$rc)"
	fi
	home="$(kv home "$out")"
	[[ "$home" =~ ^/[A-Za-z0-9._/-]+$ ]] || j_phase_a_fail "the board's home directory is not a plain path"
	homedev="$(printf '%s\n' "$out" | sed -n 's/^cen blkchain use=home fstype=[^ ]* path=//p' | head -n 1)"
	kddev="$(printf '%s\n' "$out" | sed -n 's/^cen blkchain use=kd fstype=[^ ]* path=//p' | head -n 1)"
	homedev="${homedev:-unresolved}"
	kddev="${kddev:-unresolved}"
	for L in W X E N; do
		v="WQG_${L}_IN"
		[ "${!v}" = yes ] || continue
		v="WQG_${L}_PATH"
		p="${!v}"
		case "$homedev/" in "$p"/*) j_phase_a_fail "\$HOME's storage lies under a set member (§15.4.3 step 2)" ;; esac
		case "$kddev/" in "$p"/*) j_phase_a_fail "KD's storage lies under a set member (§15.4.3 step 2)" ;; esac
		if [ "$L" = X ] || [ "$L" = N ]; then
			case "$homedev $kddev" in *unresolved*) j_phase_a_fail "\$HOME's or KD's storage did not resolve and the set holds the xHCI or NVMe (fail-safe)" ;; esac
		fi
	done

	# step 4: generate, gate (bash -n, allow-list, both systemd-run lines), send, compare
	WQG_ARM="$arm"
	WQG_FINAL=kexec
	[ "$arm" = j3 ] && WQG_FINAL=none
	WQG_UTC="$UTC"
	WQG_LOG="$home/$name-wq.log"
	WQG_TRACE="$trace"
	WQG_HOME_DEV="$homedev"
	WQG_KD_DEV="$kddev"
	WQG_KMSG=/dev/kmsg
	WQG_ROOT=""
	wq="$base-wq.sh"
	wqfb="$base-wqfb.sh"
	b_wq_gen main > "$wq"
	b_wq_gen fallback > "$wqfb"
	check_private "$wq" "$wqfb"
	fb_s="$(wq_fallback_s "$WQ_SLOT_COUNT")"
	line_main="sudo -n systemd-run --unit=s1wq-$UTC --collect --no-block -p TimeoutStopSec=30 /bin/bash \"\$HOME/$name-wq.sh\""
	line_fb="sudo -n systemd-run --unit=s1wqfb-$UTC --on-active=${fb_s}s --timer-property=AccuracySec=1s --collect /bin/bash \"\$HOME/$name-wqfb.sh\""
	out="$(wq_gate_all "$wq" "$wqfb" "$line_main" "$line_fb" "$UTC" "$fb_s")"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	[ "$rc" = 0 ] || j_phase_a_fail "the allow-list gate refused the generated sequence (§15.5 A5)"
	rec "$kw sequence wq.sh sha256=$(j_sha256 "$wq") wqfb.sh sha256=$(j_sha256 "$wqfb") fallback_s=$fb_s"
	if ! j_scp 25 "$wq" "$ORIN_HOST:$name-wq.sh" || ! j_scp 25 "$wqfb" "$ORIN_HOST:$name-wqfb.sh"; then
		J_UNITS_UTC=""
		j_phase_a_fail "scp of the sequence failed"
	fi
	out="$(board 10 "sha256sum \"\$HOME/$name-wq.sh\" \"\$HOME/$name-wqfb.sh\" | cut -d' ' -f1")"
	[ "$(printf '%s\n' "$out" | tr '\n' ' ' | sed 's/ *$//')" = "$(j_sha256 "$wq") $(j_sha256 "$wqfb")" ] \
		|| j_phase_a_fail "the board's copies of the sequence differ from the PC's"
	rec "$kw sequence on the board: both sha256 equal the PC's"
	# the as-sent copies hold the board's home path; their sha256 above is what a later
	# collection compares with, so the local copies may now be redacted
	privacy_scan "$wq"
	privacy_scan "$wqfb"

	# steps 5-7: the offset, then the fallback first, then the sequence
	com3_off=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)
	if [ "$arm" = j3 ]; then
		rec "j3 com3_log=$(basename "$S1_COM3_LOG") capture_left_s=$left reboot_bound_s=$RETURN_BOUND"
		rec "j3 com3_bytes_before_arm=$com3_off"
	else
		rec "run com3_log=$(basename "$S1_COM3_LOG") capture_left_s=$left return_bound_s=$RETURN_BOUND quiesce=1 governor_pin=1 detached=1"
		rec "run com3_bytes_before_kexec=$com3_off"
	fi
	J_UNITS_UTC="$UTC"
	out="$(board "$JA_ARM_S" "$line_fb" 'echo "wq_arm_rc=$?"')"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	{ [ "$rc" = 0 ] && [ "$(kv wq_arm_rc "$out")" = 0 ]; } || j_phase_a_fail "arming the fallback timer failed (session rc=$rc)"
	armed=$(date +%s)
	rec "wq_armed armed_epoch=$armed wq_fallback_s=$fb_s"
	out="$(board "$JA_ARM_S" "$line_main" 'echo "wq_start_rc=$?"')"
	rc=$?
	printf '%s\n' "$out" | rec_pipe
	{ [ "$rc" = 0 ] && [ "$(kv wq_start_rc "$out")" = 0 ]; } || j_phase_a_fail "starting the sequence failed (session rc=$rc)"
	rec "$kw sequence started as s1wq-$UTC; the fallback fires at armed_epoch + $fb_s s. From here the PC reads COM3 ('$(repo_rel "$HERE/$PROG") wq-status $(repo_rel "$REC")')"

	# Phase B: COM3 progress
	wait_wq "$old" "$com3_off" "$armed"
	rec "$kw wq_end=$WQ_END com3_bytes=$(stat -c %s "$S1_COM3_LOG" 2>/dev/null || echo 0)"
	case "$WQ_END" in
	STOPPED)
		ON_DIE=j_phase_a_last
		j_stop_units "$UTC"
		board 60 'echo "kexec_loaded_before_unload=$(cat /sys/kernel/kexec_loaded)"' b_unload | rec_pipe
		j_wq_collect "$SD" yes
		j_kpf_decode_after
		rec "$kw F42: no s1wq: begin marker on COM3 by its bound while L4T still answered ssh: both units stopped and the image unloaded, no kexec (exit 3). Reboot; no J4 today (§15.4.5, §15.4.6)"
		check_private "$REC"
		exit 3
		;;
	GIVEUP)
		ON_DIE=""
		j_kpf_decode_after
		rec "$kw NO RETURN within $(( $(date +%s) - armed )) s of the arming (the fallback deadline + 600 s). Power-cut advice by the COM3 class (§2 rule 6a, §15.7.3), never by the clock alone:"
		ADVICE_F25W_CUT="$(j_decision D25_F25W_CUT)" com3_advice "$S1_COM3_LOG" "$com3_off" 0 passed "$armed" "$fb_s" | rec_pipe
		rec "$kw: from the repository root, with S1_COM3_LOG and ORIN_HOST set, re-run '$(repo_rel "$HERE/$PROG") advice $(repo_rel "$REC")' until it allows a cut, or L4T answers; the next harness command removes the sequence's files first"
		check_private "$REC"
		exit 2
		;;
	BACK) ;;
	*)
		wait_new_boot_id "$old" "$(date +%s)" 0 1
		wrc=$?
		if [ "$wrc" != 0 ]; then
			ON_DIE=""
			j_kpf_decode_after
			rec "$kw NO RETURN within $RETURN_BOUND s after $WQ_END (extended=$EXTENDED). Power-cut advice by the COM3 class (§2 rule 6a, §15.7.3), never by the clock alone:"
			ADVICE_F25W_CUT="$(j_decision D25_F25W_CUT)" com3_advice "$S1_COM3_LOG" "$com3_off" 0 passed "$armed" "$fb_s" | rec_pipe
			rec "$kw: from the repository root, with S1_COM3_LOG and ORIN_HOST set, re-run '$(repo_rel "$HERE/$PROG") advice $(repo_rel "$REC")' until it allows a cut, or L4T answers"
			check_private "$REC"
			exit 2
		fi
		;;
	esac
	ON_DIE=j_return_die
	rec "$kw back new_boot_id=$NEW_BOOT_ID after $WQ_END"
	st="$(tok "$(wq_state "$S1_COM3_LOG" "$com3_off" "$armed" "$(date +%s)" | head -n 1)" state)"
	rec "$kw state at the return: $st"
	[ "$arm" = j3 ] && { j3_return; return $?; }
	case "$st" in
	JUMPED) ;;
	ABORTED) j_return_aborted "$st" ;;
	*)
		# no jump and no abort, fallback or 'kexec did not happen' marker after the offset: the
		# black box's shim line decides whether the kexec happened (COM3 may have lost the text)
		out="$(board 60 'echo "blackbox_shim_lines=$(sudo -n cat /sys/fs/pstore/console-ramoops-0 2>/dev/null | grep -ac T234-SHIM)"')"
		shim="$(kv blackbox_shim_lines "$out")"
		rec "$kw the black box read at the return: blackbox_shim_lines=${shim:-unread}"
		if [[ "${shim:-0}" =~ ^[1-9][0-9]*$ ]]; then
			rec "$kw the black box holds the shim: the kexec happened and COM3 lost the jump text; the return records run as after a jump"
		elif [ "$st" = ISSUED ]; then
			j_return_noparse f37 "$st"
		else
			j_return_noparse unclassified "$st"
		fi
		;;
	esac
	if [ "$img" = s1-j1 ]; then
		JDIAG=j1
		j6_parse_setup "$arm" "$base"
	else
		JDIAG="$([ "$arm" = remove ] && echo j4 || echo j2)"
	fi
	J_RETURN_HOOK=j_kexec_extras
	run_return_records
}

# §15.5 A1: jrun IMG control|remove|b2repeat.
cmd_jrun() {
	jrun_args "$1" "$2"
	if [ "$2" = b2repeat ]; then
		J_Q17_LINE="$(j_q17_check "$1")" || exit 1
		JRUN=b2repeat
		JDIAG=j2b
		cmd_run "$1"
		return $?
	fi
	j_detached "$2" "$1"
}

# §15.4.5: J3 loads s1-h1 as J4 would, so its memory state matches, and never issues it.
cmd_j3() { j_detached j3 s1-h1; }

# §15.4.6's state of a j3 or jrun control|remove board log, from S1_COM3_LOG after its offset.
cmd_wq_status() {
	local bl="$1" off name wq armed fbs
	j_norm_capture
	[ -n "${S1_COM3_LOG:-}" ] || die "S1_COM3_LOG must name the capture the rung ran with"
	off="$(sed -n 's/^run com3_bytes_before_kexec=\([0-9][0-9]*\)$/\1/p; s/^j3 com3_bytes_before_arm=\([0-9][0-9]*\)$/\1/p' "$bl" | tail -n 1)"
	name="$(sed -n 's/^run com3_log=\([^ ]*\) .*/\1/p; s/^j3 com3_log=\([^ ]*\) .*/\1/p' "$bl" | tail -n 1)"
	wq="$(sed -n 's/^wq_armed armed_epoch=\([0-9][0-9]*\) wq_fallback_s=\([0-9][0-9]*\)$/\1 \2/p' "$bl" | tail -n 1)"
	[ -n "$off" ] && [ -n "$wq" ] || die "$(basename "$bl") has no wq_armed line and offset: not a j3 or jrun control|remove board log"
	[ "$name" = "$(basename "$S1_COM3_LOG")" ] || die "the board log names another capture than S1_COM3_LOG"
	armed="${wq% *}"
	fbs="${wq#* }"
	wq_state "$S1_COM3_LOG" "$off" "$armed" "$(date +%s)" | redact
	echo "wq fallback_s=$fbs advice_hold_until=$(( armed + fbs + 1200 )) now=$(date +%s)"
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

# §8 PC item 2 and §5.2 items 2 and 5: the kexec tree sha256 and the PC's inputs, before any
# board round (cmd_run's, moved here unchanged so jrun uses the same checks). Sets tree and the
# pc_*_sha variables in the caller's scope (bash's dynamic scoping: cmd_run declares them local).
run_pc_inputs() {
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
}

# §6.11 steps 7-8b after a return: black box, pstore, nvbootctrl, raw copies, the parser, the
# privacy scan, extract and consistency (cmd_run's, moved here unchanged; it reads and sets
# cmd_run's locals through bash's dynamic scoping). JDIAG adds --diag for jrun, and
# J_RETURN_HOOK runs jrun's own records before the closing line; both are empty for B rungs.
run_return_records() {
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
		[ -n "${JDIAG:-}" ] && pargs+=(--diag "$JDIAG")    # jrun (§15.5 A3); empty for every B rung
		[ "${JDIAG:-}" = j1 ] && pargs+=("${J6_PARGS[@]}")   # J6: arm, factor, hold, kpf headers (§15.5 B7)
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
		[ "${JDIAG:-}" = j1 ] && j6_after_parse "$com3"    # J6: the exports, canwatch.txt, the stop rows
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
	[ -n "${J_RETURN_HOOK:-}" ] && "$J_RETURN_HOOK"    # jrun control|remove: the sequence files and markers (§15.4.6)
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

cmd_run() {
	local out old up rc wrc pstore_before pstore_after newrec shim reason lsha rcs oops gok gov0 gov4 stuck left
	local bb com3 SD base tree tree_now attempt com3_off names n f want got rmfiles verdict slots_state_post
	local conf="$S1DIR/s1-linux.conf" pargs conf_gate cstate
	local pc_image="$S1DIR/out/l4t/Image" pc_l4t_initrd="$S1DIR/out/l4t/initrd" pc_initrd="$S1DIR/out/initrd.cpio.gz"
	local pc_conf_sha="" pc_image_sha="" pc_l4t_initrd_sha="" pc_initrd_sha=""
	# §15.4.8: s1-j1 is J6's watcher, never a pass run; only jrun s1-j1 control|remove runs it
	[ "$1" = s1-j1 ] && die "run refuses s1-j1: J6's watcher image runs only as 'jrun s1-j1 control|remove' (§15.4.8)"
	need_host
	need_record_dir
	IMG="$1"
	resolve_kimg "$IMG"
	# jrun s1-h1 b2repeat (J2b, §15.4.4): STEP is set after resolve_kimg, so image_step's B2
	# never reaches the record path; the J gates only add refusals. JRUN is empty for B rungs.
	if [ -n "$JRUN" ]; then
		j_norm_capture
		jrun_step "$JRUN"
		j_read_decisions
		j_require D20 "J2b (§15.6 D20)"
		j_require_clean_tree "J2b"
		j_precondition b2repeat
		# after J1's F42 row J2b runs in J2's place, so it writes the J2 pre-registration (J2b
		# carries no trace); found by its stage line, never rewritten over a later stage
		if ! j_prereg_has_stage j2; then
			j_prereg_write "" "" j2 no
			note "J-prereg.log written as the J2 pre-registration by J2b's first attempt (§15.4.1)"
		fi
		JPREREG="$(j_prereg_check)" || exit 1
		JGATE="$(j_capture_gate b2repeat)" || die "gate A: ${JGATE#*FAIL: }"
	fi
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
	run_pc_inputs

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
	if [ -n "$JRUN" ]; then
		rec "run jrun=$JRUN step=$STEP: run's B2 flow with no additions (no snapshot, no trace, no detached sequence); parser run --diag $JDIAG (§15.4.4)"
		j_stamps | rec_pipe
		rec "run $J_Q17_LINE"
		rec "run $JPREREG"
		rec "$JGATE"
		j_wq_collect "$SD" yes
	fi
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
	if [ -n "$JRUN" ]; then
		mark_boot "$old" j2b
		mark_capture "$S1_COM3_LOG"
	else
		mark_boot "$old" run
	fi
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
	if [ -n "$JRUN" ]; then
		if ! JGATE="$(j_gate_b b2repeat)"; then
			rec "run GATE B: ${JGATE#*FAIL: }: no kexec. The board is quiesced: '$PROG reboot', start a fresh capture, then run again"
			check_private "$REC" "$base-iomem-postrmmod.log"
			exit 3
		fi
		rec "$JGATE"
	fi
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

	run_return_records
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

# §15.5 A1 and §15.7.3 for a detached-sequence board log (wq_armed): after the offset, a reset
# marker (fallback firing or forcing, abort reason=, kexec did not happen, Restarting system,
# reboot:, and, fail-safe, the image's reset line, the guard's deadline or a firmware banner)
# prints 'reset'; a jump (Starting new kernel, a shim line or a record line) prints 'jump';
# anything else (s1wq: markers, L4T text, nothing) prints 'markers'. $1 file, $2 offset.
com3_wq_class() {
	tail -c +"$(( $2 + 1 ))" "$1" 2>/dev/null | tr -d '\r' | LC_ALL=C awk -v banners="$(printf '%s\n' "${FW_BANNER[@]}")" '
	BEGIN { nb = split(banners, B, "\n") }
	{
		s = $0
		sub(/^[ \t]+/, "", s); sub(/^[^ -~]+[ \t]*/, "", s); sub(/[ \t]+$/, "", s)
		m = s
		sub(/^\[ *[0-9]+\.[0-9]+\] */, "", m); sub(/^\[ *[CT][0-9]+\] */, "", m)
		if (s ~ /kexec_core: Starting new kernel|T234-SHIM/ || s ~ /^(S1 |STAMP |BWAIT |T234 |t234: |tcu-cat:)/) jump = 1
		if (m ~ /^s1wq: (fallback firing|fallback forcing|abort reason=|kexec did not happen)/ || s ~ /Restarting system|reboot: /) reset = 1
		if (s ~ /resetting so the log can be recovered|BWAIT guard deadline/) reset = 1
		for (i = 1; i <= nb; i++) if (B[i] != "" && index(s, B[i])) reset = 1
	}
	END { print (jump ? "jump" : (reset ? "reset" : "markers")) }'
}

# $1 file, $2 offset (-1 unknown), $3 last growth epoch (0 none), $4 the return bound:
# passed (a NO RETURN line), not_reached or unknown (the default). ADVICE_SSH may be
# preset to answered, silent or unchecked; otherwise the board is asked once.
# $5 armed_epoch and $6 WQ_FALLBACK_S, from a detached-sequence board log's wq_armed line
# (empty for every other log, whose advice is unchanged): NO CUT in every class until
# armed_epoch + WQ_FALLBACK_S + 1200 s; after that com3_wq_class decides F25b, today's
# F25a/F25b logic after a jump, or F25w, whose one cut needs ADVICE_F25W_CUT=yes
# (J-decisions.conf's D25_F25W_CUT, set by cmd_advice).
com3_advice() {
	local f="$1" off="${2:--1}" grow="${3:-0}" bound="${4:-unknown}" now s0 s1 out head1 class idle menu last ssh="${ADVICE_SSH:-}" bid
	local cstate reset banner kind armed="${5:-}" fbs="${6:-}" hold jcls f25w_cut=no
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
	if [ -n "$armed" ]; then
		hold=$(( armed + fbs + 1200 ))
		echo "advice wq_armed armed_epoch=$armed wq_fallback_s=$fbs hold_until=$hold"
		if (( now < hold )); then
			echo "advice NO CUT (detached sequence): a board log with wq_armed holds every class (F25a, F25b, F25w) until armed_epoch + WQ_FALLBACK_S + 1200 s, $(( hold - now )) s from now: the sequence's abort or its fallback may still reboot L4T (§15.5 A1, §15.7.3)"
			return 0
		fi
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
	# a detached-sequence log whose capture offset is unknown (another capture, or none named):
	# F25w and F25b cannot be told apart, and F25w's cut needs the offset, so never a cut
	if [ -n "$armed" ] && [ "$class" != nocapture ] && ! [ "$off" -ge 0 ] 2>/dev/null; then
		echo "advice NO CUT (detached sequence, kexec offset unknown): S1_COM3_LOG is not the capture this board log names, so whether a reset marker followed the arming (F25b) or only s1wq: markers (F25w) cannot be shown, and neither class's cut is advised: the owner decides (§15.7.3 items 6 and 7)"
		echo "advice F25w recovery without a cut (§15.7.3 item 6): wait for the fallback; if J4's set left the Ethernet driver bound (the wireless-only set), fit an Ethernet cable, find the new address by scanning the /24, and run 'sudo systemctl reboot'; if J1 found a USB keyboard and the xHCI was not unbound, log in locally and reboot"
		return 0
	fi
	if [ -n "$armed" ] && [ "$class" != nocapture ]; then
		jcls="$(com3_wq_class "$f" "$off")"
		echo "advice wq_class=$jcls"
		case "$jcls" in
		reset)
			class=F25b
			echo "advice F25b because: a reset marker (fallback firing or forcing, abort reason=, kexec did not happen, Restarting system, reboot:, the image's reset line or a firmware banner) follows the offset, so a firmware boot may have started (§15.7.3 item 7)"
			;;
		markers)
			# F25w only when today's class is F25a, or the unrecognised last line is itself an
			# s1wq: marker: other unrecognised text after the markers may be firmware, so F25b stays
			if [ "$class" = F25a ] || printf '%s\n' "$last" | grep -aqE '^[[:space:]]*(\[ *[0-9]+\.[0-9]+\] *)?(\[ *[CT][0-9]+\] *)?s1wq: '; then
				class=F25w
			else
				echo "advice F25b kept: after the offset the markers are followed by text that is not a marker, Linux's text or a record line, which may be firmware output (§15.7.3 item 7)"
			fi
			;;
		esac
	fi
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
			[ -n "$armed" ] && echo "advice note (detached sequence): for a board log with wq_armed, a capture the log does not name gives NO CUT, since F25w and F25b cannot be told apart without the offset: the owner decides"
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
	F25w)
		echo "advice F25w: after the offset only s1wq: markers or L4T text, and no reset marker, jump, shim or record line: L4T is alive with no network, and its fallback did not act (§15.7.2)"
		if [ "$menu" = yes ]; then
			echo "advice NO CUT (F25w): the last output looks like a menu or a prompt: the owner decides"
		elif [ "$ssh" != silent ]; then
			echo "advice NO CUT YET (F25w): ssh was not checked; F25w needs no ssh answer in that time. Set ORIN_HOST and run advice again"
		elif (( idle < 600 )); then
			echo "advice NO CUT YET (F25w): COM3 last grew $idle s ago; F25w needs 600 s with no new byte"
		elif [ "${ADVICE_F25W_CUT:-}" != yes ]; then
			echo "advice NO CUT (F25w): D25_F25W_CUT is not yes in J-decisions.conf, so no cut is advised for F25w"
		else
			f25w_cut=yes
			echo "advice ONE CUT ALLOWED (F25w, under D25): COM3 has shown no new byte for 10 minutes, the last output is not a menu or a prompt, L4T has not answered ssh, and no reset marker followed the offset, so the running L4T is the boot validated at the rung's start (F25a's reasoning). Record the last line, cut power once and press nothing, then let L4T boot. Never a second cut"
		fi
		[ "$f25w_cut" = yes ] || echo "advice F25w recovery without a cut (§15.7.3 item 6): wait for the fallback; if J4's set left the Ethernet driver bound (the wireless-only set), fit an Ethernet cable, find the new address by scanning the /24, and run 'sudo systemctl reboot'; if J1 found a USB keyboard and the xHCI was not unbound, log in locally and reboot"
		;;
	esac
	[ -n "$last" ] || echo "advice note: COM3 shows no output after the kexec"
	return 0
}

cmd_advice() {
	local off=-1 bl="${1:-}" name bound=unknown wq="" armed="" fbs="" cut=""
	[ -n "${S1_COM3_LOG:-}" ] || die "S1_COM3_LOG must name the COM3 capture to classify"
	if [ -n "$bl" ]; then
		if grep -aqE '^(run|p1|reboot|jrun|j3) NO RETURN within' "$bl"; then bound=passed; else bound=not_reached; fi
		off="$(sed -n 's/^run com3_bytes_before_kexec=\([0-9][0-9]*\)$/\1/p; s/^j3 com3_bytes_before_arm=\([0-9][0-9]*\)$/\1/p' "$bl" | tail -n 1)"
		name="$(sed -n 's/^run com3_log=\([^ ]*\) .*/\1/p; s/^j3 com3_log=\([^ ]*\) .*/\1/p' "$bl" | tail -n 1)"
		# §15.5 A1: a detached-sequence log's arming, and the owner's D25_F25W_CUT beside it
		wq="$(sed -n 's/^wq_armed armed_epoch=\([0-9][0-9]*\) wq_fallback_s=\([0-9][0-9]*\)$/\1 \2/p' "$bl" | tail -n 1)"
		if [ -n "$wq" ]; then
			j_norm_capture
			armed="${wq% *}"
			fbs="${wq#* }"
			cut="$(sed -n 's/^D25_F25W_CUT=//p' "${S1_RECORD_DIR:-$(dirname "$(dirname "$bl")")}/J-decisions.conf" 2>/dev/null | tr -d '\r' | tail -n 1)"
		fi
		if [ -z "$off" ] || [ "$name" != "$(basename "$S1_COM3_LOG")" ]; then
			note "the board log names no kexec offset for $(basename "$S1_COM3_LOG"): the offset is unknown, so F25a cannot be shown"
			off=-1
		fi
	else
		note "no board log: the return bound cannot be shown to have passed, so no cut is advised (and the kexec offset is unknown)"
	fi
	ADVICE_F25W_CUT="$cut" com3_advice "$S1_COM3_LOG" "$off" 0 "$bound" "$armed" "$fbs" | redact
}

# ---------------------------------------------------------------- self-tests
#
# The redaction decides whether a private record can ever be shown to anyone;
# the advice decides whether power is cut. Both run here against synthetic
# values only - never the board's - and need no board, no ORIN_HOST, no network.

cmd_redact_selftest() {
	local d out fail=0 ran=0
	d="$(mktemp -d)" || die "cannot make a temp directory"
	unset S1_REDACT_SSID   # the SSID class is off unless a case sets it (§15.5 A4)

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
	check "ident_hits clean" "$(ident_hits "$d/clean" 2>&1)" "0 addr=0 mac=0 name=0 ssid=0"

	# §15.5 A4: the SSID redaction class. S1_REDACT_SSID is read through awk ENVIRON, so a
	# backslash in it is literal; it is used only at 3 bytes or more; and it is counted in
	# ident_hits so an SSID-only file is never kept raw. Set per case in a subshell
	# (command substitution) so it does not leak between checks.
	printf '%s\n' 'wifi joined CoffeeShop-WiFi ok' > "$d/ssidonly"
	out="$(export S1_REDACT_SSID='CoffeeShop-WiFi'; redact < "$d/ssidonly")"
	check "SSID redacted to a placeholder" "$(printf '%s\n' "$out" | grep -c '<ssid>')" 1
	check "SSID not left raw" "$(printf '%s\n' "$out" | grep -c 'CoffeeShop-WiFi')" 0
	out="$(export S1_REDACT_SSID='CoffeeShop-WiFi'; ident_hits "$d/ssidonly")"
	check "an SSID-only file counts as identifying (never kept raw)" "$(printf '%s\n' "$out" | grep -cE '^[1-9][0-9]* addr=0 mac=0 name=0 ssid=[1-9]')" 1

	out="$(export S1_REDACT_SSID='ab'; redact < "$d/ssidonly")"
	check "a 1-2 byte SSID is not applied (refused)" "$(printf '%s\n' "$out" | grep -c 'CoffeeShop-WiFi')" 1
	out="$(export S1_REDACT_SSID='ab'; ident_hits "$d/ssidonly")"
	check "a short SSID is not counted" "$(printf '%s\n' "$out" | grep -c ' ssid=0$')" 1

	printf '%s\n' 'connected to net\wifi now' > "$d/ssidbs"
	out="$(export S1_REDACT_SSID='net\wifi'; redact < "$d/ssidbs")"
	check "an SSID with a backslash is redacted" "$(printf '%s\n' "$out" | grep -c '<ssid>')" 1
	check "the backslash SSID is not left raw" "$(printf '%s\n' "$out" | grep -cF 'net\wifi')" 0

	printf '%s\n' 's1wq: slot1 deauth from 00:00:5e:00:53:01 result=0' > "$d/wq"
	out="$(redact < "$d/wq")"
	check "a colon MAC in a wq.log line is masked" "$(printf '%s\n' "$out" | grep -c '00:00:5e')" 0
	check "the wq.log line keeps its marker" "$(printf '%s\n' "$out" | grep -c 's1wq: slot1')" 1

	printf '%s\n' 'link 00-00-5e-00-53-01 up' > "$d/hymac"
	out="$(redact < "$d/hymac")"
	check "a hyphen-form MAC is masked" "$(printf '%s\n' "$out" | grep -c '00-00-5e')" 0
	check "a hyphen-form MAC becomes <mac>" "$(printf '%s\n' "$out" | grep -c '<mac>')" 1
	check "ident_hits counts a hyphen-form MAC" "$(ident_hits "$d/hymac" | grep -cE ' mac=1 ')" 1

	printf 'primary 203.0.113.7 and fallback 198.51.100.23 both up\n' > "$d/two"
	out="$(redact < "$d/two")"
	check "a second host address is masked too" "$(printf '%s\n' "$out" | grep -cE '203[.]0[.]113[.]7|198[.]51[.]100[.]23')" 0

	printf '%s\n' 'netdev return if=enx00005e005301 operstate=up dev=none' > "$d/enx"
	out="$(redact < "$d/enx")"
	check "a MAC-based interface name (enx + 12 hex) is masked" "$(printf '%s\n' "$out" | grep -c 'enx00005e')/$(printf '%s\n' "$out" | grep -c 'if=enx<mac> ')" "0/1"
	check "ident_hits counts a MAC-based interface name" "$(ident_hits "$d/enx" | grep -cE ' mac=1 ')" 1

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

	# §15.4.3: the detached-sequence timing is fixed; the constants and the S1_WQ_ forms
	# are refused if set in the environment.
	S1_WQ_FOO=1 bash "$0" redact-selftest >/dev/null 2>&1
	check "an S1_WQ_ variable is refused" "$?" 1
	WQ_SLOT_S=99 bash "$0" redact-selftest >/dev/null 2>&1
	check "a WQ_ constant override is refused" "$?" 1
	check "exit-5 constant" "$EXIT_SEQ_REBOOT" 5
	check "wq constants (§15.4.3)" "$WQ_START_DELAY_S/$WQ_SLOT_S/$WQ_STEP_TIMEOUT_S/$WQ_FINAL_READS_S/$WQ_ISSUE_WAIT_S" "15/30/25/60/180"
	check "wq_worst_case for 9 slots" "$(wq_worst_case 9)" "$(( 15 + 9 * 30 + 60 + 180 ))"
	check "wq_fallback_s for 9 slots" "$(wq_fallback_s 9)" "$(( 15 + 9 * 30 + 60 + 180 + 120 ))"
	check "wq_constants_line names the slots and both totals" "$(has "$(wq_constants_line 9)" 'slots=9 worst_case_s=525 fallback_s=645')" yes
	check "wq_constants_line before the slots are known" "$(has "$(wq_constants_line)" 'slots=pending worst_case_s=pending fallback_s=pending')" yes

	# ---- J diagnostic plumbing (§15.5 A), all synthetic; RECDIR is a temp directory.
	local jrec cap gr bid JSD
	jrec="$d/jrec"; mkdir -p "$jrec"
	RECDIR="$jrec"; RECDIR="$(cd "$jrec" && pwd)"

	# decisions: a missing file is refused
	( J_DEC_LOADED=0; j_read_decisions ) >/dev/null 2>&1
	check "decisions: a missing J-decisions.conf is refused" "$?" 1
	{ printf 'D20=yes\n'; printf 'D21=yes\n'; printf 'D22=yes\n'; printf 'D23=no\n'
	  printf 'D24=yes\n'; printf 'D24_SET=max\n'; printf 'D25=yes\n'
	  printf 'D25_F25W_CUT=no\n'; printf '# owner ruling\n'; } > "$jrec/J-decisions.conf"
	J_DEC_LOADED=0; j_read_decisions
	check "decisions: a yes decision reads back" "$(j_decision D20)" yes
	check "decisions: a no decision reads back" "$(j_decision D23)" no
	check "decisions: D24_SET reads back" "$(j_decision_set)" max
	( j_require D20 "a test" ) >/dev/null 2>&1
	check "j_require passes a yes decision" "$?" 0
	( j_require D23 "a test" ) >/dev/null 2>&1
	check "j_require refuses a no decision" "$?" 1
	( j_require D24_SET "a test" ) >/dev/null 2>&1
	check "j_require refuses a non-yes value (max)" "$?" 1
	check "decisions: the file hashes to 64 hex" "$(j_sha256 "$(j_decisions_path)" | grep -cE '^[0-9a-f]{64}$')" 1

	# clean-tree, on a synthetic repo (the real tree is dirty while this file is edited)
	gr="$d/gr"; mkdir -p "$gr"
	( cd "$gr" && git init -q && git config user.email t@example.invalid && git config user.name t \
		&& printf 'x\n' > f.txt && git add f.txt && git commit -qm init ) >/dev/null 2>&1
	check "git_paths_clean: a committed file is clean" "$(git_paths_clean "$gr" "$gr/f.txt"; echo $?)" 0
	printf 'y\n' >> "$gr/f.txt"
	check "git_paths_clean: a modified file is dirty" "$(git_paths_clean "$gr" "$gr/f.txt"; echo $?)" 1
	printf 'z\n' > "$gr/untracked.py"
	check "git_paths_clean: an untracked file is dirty" "$(git_paths_clean "$gr" "$gr/untracked.py"; echo $?)" 1
	check "git_paths_clean: a missing file is skipped (clean)" "$(git_paths_clean "$gr" "$gr/nope.py"; echo $?)" 0

	# stamps
	out="$(j_stamps 9)"
	check "stamps: a HEAD line" "$(has "$out" 'stamp head=')" yes
	check "stamps: s1-board.sh sha256" "$(printf '%s\n' "$out" | grep -cE '^stamp s1-board.sh sha256=[0-9a-f]{64}$')" 1
	check "stamps: a tree line" "$(has "$out" 'stamp tree=')" yes
	check "stamps: the decisions sha256" "$(has "$out" 'stamp decisions_sha256=')" yes
	check "stamps: the fixed wq constants" "$(has "$out" 'wq_constants start_delay_s=15')" yes

	# pre-registration
	S1_J_RULE_FILE="$d/rule.txt"; printf 'pre-registered rule text (§15.6)\n' > "$S1_J_RULE_FILE"
	j_prereg_write "slot1,slot4,slot7" "1.5"
	check "prereg: the file is written" "$([ -f "$jrec/J-prereg.log" ] && echo yes || echo no)" yes
	check "prereg: the slot list" "$(has "$(cat "$jrec/J-prereg.log")" 'prereg slot_list=slot1,slot4,slot7')" yes
	check "prereg: the fill-rate factor" "$(has "$(cat "$jrec/J-prereg.log")" 'prereg fill_rate_factor=1.5')" yes
	check "prereg: the rule text hash" "$(grep -cE '^prereg rule_text=rule.txt sha256=[0-9a-f]{64}$' "$jrec/J-prereg.log")" 1
	check "prereg: the decisions are recorded" "$(has "$(cat "$jrec/J-prereg.log")" 'prereg D24_SET=max')" yes
	check "prereg: the recorded harness sha equals the current" \
		"$(sed -n 's/^prereg s1-board.sh sha256=//p' "$jrec/J-prereg.log" | tail -n 1)" "$(j_sha256 "$HERE/$PROG")"
	# prereg_check refusals (deterministic regardless of the working tree's state)
	sed 's/^prereg s1-board.sh sha256=.*/prereg s1-board.sh sha256=deadbeef/' "$jrec/J-prereg.log" > "$jrec/J-prereg.bad"
	mv "$jrec/J-prereg.bad" "$jrec/J-prereg.log"
	( j_prereg_check ) >/dev/null 2>&1
	check "prereg_check refuses a harness sha mismatch" "$?" 1
	rm -f "$jrec/J-prereg.log"
	( j_prereg_check ) >/dev/null 2>&1
	check "prereg_check refuses a missing prereg" "$?" 1

	# used-captures ledger
	check "capture_used: an unknown name is free" "$(capture_used "$d/cap-a.log"; echo $?)" 1
	mark_capture "$d/cap-a.log"
	check "capture_used: a marked name is used" "$(capture_used "$d/cap-a.log"; echo $?)" 0
	check "capture_used: another name is still free" "$(capture_used "$d/cap-b.log"; echo $?)" 1

	# J capture gate (§15.5 A1 gate A)
	export ADVICE_CAPTURE_HELD=yes
	export S1_REDACT_SSID='CoffeeShop-WiFi'
	RETURN_BOUND=1200
	cap="$jrec/j-cap.log"
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=99999 ---\n' "$now" > "$cap"
	printf 'MB1 version synthetic\r\n' >> "$cap"
	check "j_capture_gate: a good capture passes (control)" "$(has "$(S1_COM3_LOG="$cap" j_capture_gate control 9)" 'jgate control ok')" yes
	cp "$cap" "$jrec/j-cap-reuse.log"; mark_capture "$jrec/j-cap-reuse.log"
	check "j_capture_gate: a reused capture is refused" "$(has "$(S1_COM3_LOG="$jrec/j-cap-reuse.log" j_capture_gate control 9)" 'already in used-captures.log')" yes
	cp "$cap" "$jrec/j-cap-wq.log"; printf 's1wq: slot1 result=0\r\n' >> "$jrec/j-cap-wq.log"
	check "j_capture_gate: an s1wq: marker is refused" "$(has "$(S1_COM3_LOG="$jrec/j-cap-wq.log" j_capture_gate control 9)" 's1wq: markers or an earlier')" yes
	cp "$cap" "$jrec/j-cap-rec.log"; printf 'S1 STATE launch\r\n' >> "$jrec/j-cap-rec.log"
	check "j_capture_gate: an earlier rung's records are refused" "$(has "$(S1_COM3_LOG="$jrec/j-cap-rec.log" j_capture_gate control 9)" 's1wq: markers or an earlier')" yes
	cp "$cap" "$d/j-cap-out.log"
	check "j_capture_gate: a capture outside the record dir is refused" "$(has "$(S1_COM3_LOG="$d/j-cap-out.log" j_capture_gate control 9)" 'not inside the git-ignored record directory')" yes
	check "j_capture_gate: a missing SSID is refused" "$(has "$(S1_COM3_LOG="$cap" S1_REDACT_SSID='' j_capture_gate control 9)" 'S1_REDACT_SSID is unset')" yes
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=100 ---\n' "$now" > "$jrec/j-cap-short.log"
	printf 'MB1 version synthetic\r\n' >> "$jrec/j-cap-short.log"
	check "j_capture_gate: too-short life is refused" "$(has "$(S1_COM3_LOG="$jrec/j-cap-short.log" j_capture_gate control 9)" 'under')" yes
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=1900 ---\n' "$now" > "$jrec/j-cap-1900.log"
	printf 'MB1 version synthetic\r\n' >> "$jrec/j-cap-1900.log"
	check "j_capture_gate j1: 1900 s passes the 1800 s floor" "$(has "$(S1_COM3_LOG="$jrec/j-cap-1900.log" j_capture_gate j1)" 'jgate j1 ok')" yes
	check "j_capture_gate control: 1900 s misses the fallback floor" "$(has "$(S1_COM3_LOG="$jrec/j-cap-1900.log" j_capture_gate control 9)" FAIL)" yes
	check "j_capture_life_min: j1 is 1800" "$(j_capture_life_min j1 1200 9)" 1800
	check "j_capture_life_min: b2repeat is bound+2180" "$(j_capture_life_min b2repeat 1200 9)" "$(( 1200 + 2180 ))"
	check "j_capture_life_min: control adds the fallback" "$(j_capture_life_min control 1200 9)" "$(( 1200 + 2180 + $(wq_fallback_s 9) ))"

	# start margin (§15.4.3)
	check "start_margin_ok: room under 1800" "$(start_margin_ok 100 500; echo $?)" 0
	check "start_margin_ok: over 1800 refused" "$(start_margin_ok 1500 500; echo $?)" 1
	check "start_margin_ok: a decimal uptime" "$(start_margin_ok 100.7 500; echo $?)" 0
	( start_margin_gate 1500 500 "a test" ) >/dev/null 2>&1
	check "start_margin_gate refuses over the limit" "$?" 1
	( start_margin_gate 100 500 "a test" ) >/dev/null 2>&1
	check "start_margin_gate allows room" "$?" 0

	# used-boot-ids marks by=jN
	bid=00000000-0000-4000-8000-000000000002
	mark_boot "$bid" j2
	check "mark_boot records by=j2" "$(grep -c "boot_id=$bid by=j2 " "$jrec/used-boot-ids.log")" 1
	check "boot_used finds the j2 boot" "$(boot_used "$bid"; echo $?)" 0
	mark_boot "11111111-1111-4111-8111-111111111111" j4
	check "mark_boot records by=j4" "$(grep -c ' by=j4 ' "$jrec/used-boot-ids.log")" 1

	# J record directory, and the no-B*-directory proof (§15.5 A1)
	j_step_dir J2
	check "j_step_dir J2 -> J2" "$(basename "$JSD")" J2
	check "j_step_dir made the J2 directory" "$([ -d "$jrec/J2" ] && echo yes || echo no)" yes
	printf 'x\n' > "$jrec/J2/f"
	j_step_dir J2
	check "j_step_dir a second attempt -> J2-a2" "$(basename "$JSD")" J2-a2
	j_step_dir J4
	check "j_step_dir J4 -> J4" "$(basename "$JSD")" J4
	( j_step_dir B2 ) >/dev/null 2>&1
	check "j_step_dir refuses a B* step" "$?" 1
	check "j_step_dir did not create a B2 directory" "$([ -d "$jrec/B2" ] && echo yes || echo no)" no
	check "no J path created a B* directory" "$(ls -1 "$jrec" | grep -c '^B')" 0

	# decisions: malformed lines are refused (subshells; the parent's load is untouched)
	printf 'D20=YES\n' > "$jrec/J-decisions.conf"
	( J_DEC_LOADED=0; j_read_decisions ) >/dev/null 2>&1
	check "decisions: an uppercase value is refused" "$?" 1
	printf 'D99=yes\n' > "$jrec/J-decisions.conf"
	( J_DEC_LOADED=0; j_read_decisions ) >/dev/null 2>&1
	check "decisions: an unknown key is refused" "$?" 1
	printf 'D24_SET=off\n' > "$jrec/J-decisions.conf"
	( J_DEC_LOADED=0; j_read_decisions ) >/dev/null 2>&1
	check "decisions: a bad D24_SET value is refused" "$?" 1

	# ---- J1 (§15.4.2), all synthetic. The census runs on a sysfs-like fixture tree of fake
	# names. Git Bash makes no real symlinks here, so a link is a '<name>.lnk' file holding
	# its target; s1_rl, sudo, findmnt, systemctl and getconf are redefined only inside the
	# fxrun subshell that runs the board functions.
	local fx cen cen2 setl nvp sdp usbp wlp cw hdr kdir
	fx="$d/fx"
	fxput() { mkdir -p "$(dirname "$fx/$1")"; printf '%s\n' "$2" > "$fx/$1"; }
	fxlnk() { mkdir -p "$(dirname "$fx/$1")"; printf '%s\n' "$fx/$2" > "$fx/$1.lnk"; }
	# $1 the function's directory under sys/devices, $2 class, $3 driver ('' for none),
	# $4 the Command register's low byte in hex (the high byte is 04)
	fxpci() {
		local p="sys/devices/$1"
		fxput "$p/class" "$2"; fxput "$p/enable" 1; fxput "$p/power_state" D0
		printf "\\x00\\x00\\x00\\x00\\x$4\\x04" > "$fx/$p/config"
		fxlnk "sys/bus/pci/devices/${1##*/}" "$p"
		if [ -n "$3" ]; then fxlnk "$p/driver" "sys/bus/pci/drivers/$3"; fxlnk "sys/bus/pci/drivers/$3/module" "sys/module/${3}_mod"; fi
	}
	fxrun() {
		(
			S1_SYSROOT="$fx"; S1_SHM="$d/shm"; HOME="$fx/home"; KD="$fx/kimgs"; UTC=20260914T000000Z; KPF_NAME=j1-20260914T000000Z; J_D22="${FX_D22:-yes}"
			mkdir -p "$S1_SHM" "$HOME" "$KD"
			s1_rl() { if [ -f "$1.lnk" ]; then cat "$1.lnk"; elif [ "${1%.lnk}" != "$1" ] && [ -f "$1" ]; then cat "$1"; elif [ -d "$1" ]; then printf '%s\n' "$1"; fi; }
			sudo() { [ "${1:-}" = -n ] && shift; "$@"; }
			timeout() { [ "$1" = -k ] && shift 2; shift; "$@"; }
			systemctl() { echo active; }
			getconf() { echo 4096; }
			findmnt() {
				if [ "${2:-}" = -T ]; then
					case "$3" in
					"$HOME") printf '%s\n' "${FX_HOME_SRC:-/dev/mmcblk0p1 ext4}" ;;
					"$KD")   printf '%s\n' "${FX_KD_SRC:-/dev/mmcblk0p1 ext4}" ;;
					/dev/shm) printf 'tmpfs tmpfs\n' ;;
					*) printf '/dev/mmcblk0p1 ext4\n' ;;
					esac
				else
					cat "$fx/mounts"
				fi
			}
			"$@"
		)
	}
	wlp="platform/fakebus/1000.fakepcie/pci00f1:00/00f1:00:00.0/00f1:01:00.0"
	fxpci platform/fakebus/1000.fakepcie/pci00f1:00/00f1:00:00.0 0x060400 fakeport 07
	fxpci "$wlp" 0x028000 fakewlan 06
	mkdir -p "$fx/sys/devices/$wlp/net/fakewlan0"
	fxpci platform/fakebus/2000.fakepcie/pci00f2:00/00f2:00:00.0 0x060400 fakeport 07
	fxpci platform/fakebus/2000.fakepcie/pci00f2:00/00f2:00:00.0/00f2:01:00.0 0x020000 fakeeth 02
	fxpci platform/fakebus/3000.fakepcie/pci00f3:00/00f3:00:00.0 0x060400 fakeport 07
	fxpci platform/fakebus/3000.fakepcie/pci00f3:00/00f3:00:00.0/00f3:01:00.0 0x010802 fakenvme 06
	nvp="sys/devices/platform/fakebus/3000.fakepcie/pci00f3:00/00f3:00:00.0/00f3:01:00.0/nvme/nvme0/nvme0n1/nvme0n1p1"
	mkdir -p "$fx/$nvp"; fxlnk sys/class/block/nvme0n1p1 "$nvp"
	sdp="sys/devices/platform/fakebus/5000.fakesd/mmc_host/mmc0/mmc0:0001/block/mmcblk0/mmcblk0p1"
	mkdir -p "$fx/$sdp"; fxlnk sys/class/block/mmcblk0p1 "$sdp"
	usbp="sys/devices/platform/fakebus/4000.fakeusb"
	fxlnk "$usbp/driver" sys/bus/platform/drivers/fakexhci
	fxlnk sys/bus/platform/drivers/fakexhci/module sys/module/fakexhci_mod
	fxlnk "$usbp/subsystem" sys/bus/platform
	mkdir -p "$fx/$usbp/usb1/1-1/1-1:1.0" "$fx/$usbp/usb2"
	fxlnk "$usbp/usb1/driver" sys/bus/usb/drivers/fakehub
	fxput "$usbp/usb1/1-1/idVendor" ffff; fxput "$usbp/usb1/1-1/idProduct" 0001
	fxput "$usbp/usb1/1-1/1-1:1.0/bInterfaceClass" 03; fxput "$usbp/usb1/1-1/1-1:1.0/bInterfaceProtocol" 01
	fxlnk sys/bus/usb/devices/usb1 "$usbp/usb1"; fxlnk sys/bus/usb/devices/usb2 "$usbp/usb2"
	fxlnk sys/bus/usb/devices/1-1 "$usbp/usb1/1-1"; fxlnk "sys/bus/usb/devices/1-1:1.0" "$usbp/usb1/1-1/1-1:1.0"
	fxput sys/kernel/iommu_groups/fakegrpa/type DMA; fxput sys/kernel/iommu_groups/fakegrpb/type identity
	fxput sys/class/rfkill/rfkill0/type wlan; fxput sys/class/rfkill/rfkill0/soft 0; fxput sys/class/rfkill/rfkill0/hard 0
	fxput sys/class/net/fakewlan0/operstate up; fxlnk sys/class/net/fakewlan0/device "sys/devices/$wlp"
	fxput proc/swaps 'Filename Type Size Used Priority'
	fxput proc/uptime '123.45 456.78'
	fxput proc/sys/kernel/random/boot_id 00000000-1111-4222-8333-444444444444
	fxput proc/zoneinfo 'Node 0, zone Normal'; fxput proc/buddyinfo 'Node 0, zone Normal 1 2 3'
	truncate -s 13M "$fx/proc/kpageflags" "$fx/proc/kpagecount"
	printf '/ /dev/mmcblk0p1 ext4\n/proc proc proc\n/dev/shm tmpfs tmpfs\n' > "$fx/mounts"

	cen="$(fxrun b_census 2>/dev/null)"
	check "census: the wireless-class function, driver, module, port, netdev" "$(has "$cen" "cen pcidev bdf=00f1:01:00.0 class=0x028000 driver=fakewlan module=fakewlan_mod parent=00f1:00:00.0 netdev=fakewlan0 path=/sys/devices/$wlp")" yes
	check "census: a root port's parent is none" "$(has "$cen" 'cen pcidev bdf=00f1:00:00.0 class=0x060400 driver=fakeport module=fakeport_mod parent=none')" yes
	check "census: the USB host's platform controller" "$(has "$cen" "cen usbhost bus=usb1 controller=4000.fakeusb subsystem=platform driver=fakexhci module=fakexhci_mod path=/$usbp")" yes
	check "census: the root's storage chain" "$(has "$cen" "cen blkchain use=root fstype=ext4 path=/$sdp")" yes
	check "census: /dev/shm is RAM" "$(has "$cen" 'cen blkchain use=shm fstype=tmpfs path=none')" yes
	check "census: an identity group is listed" "$(has "$cen" 'cen iommu_group group=fakegrpb type=identity')" yes
	check "census: a HID keyboard interface" "$(has "$cen" 'cen hid_keyboard=yes')" yes
	check "census: the kpageflags probe is 64 entries" "$(has "$cen" 'kpf file=j1-20260914T000000Z-kpf-probe.bin bytes=512 ')" yes
	check "census: D23 not yes reads no debugfs" "$(has "$cen" 'cen debugfs not read')" yes
	check "pci state: the Command register and a set Bus Master bit" "$(has "$cen" 'pci census dev=00f1:01:00.0 class=0x028000 driver=fakewlan parent=00f1:00:00.0 power_state=D0 enable=1 cmd=0x0406 bme=1')" yes
	check "pci state: a clear Bus Master bit" "$(has "$cen" 'pci census dev=00f2:01:00.0 class=0x020000 driver=fakeeth parent=00f2:00:00.0 power_state=D0 enable=1 cmd=0x0402 bme=0')" yes
	check "pci state: rfkill soft and hard from sysfs" "$(has "$cen" 'rfkill census name=rfkill0 type=wlan soft=0 hard=0')" yes
	check "pci state: a netdev's operstate and function" "$(has "$cen" 'netdev census if=fakewlan0 operstate=up dev=00f1:01:00.0')" yes
	check "pci state: the network services" "$(has "$cen" 'svc census NetworkManager=active wpa_supplicant=active')" yes
	check "pci state: the USB host binding" "$(has "$cen" 'usbhost census bus=usb1 controller=4000.fakeusb subsystem=platform driver=fakexhci')" yes
	rm -rf "$d/shm"/s1kpf.*

	# the set-file rules on the fixture's census
	setl="$(printf '%s\n' "$cen" | j_set_rules)"
	check "set: wireless in, single-child port, rp_clear" "$(printf '%s\n' "$setl" | grep -c '^member=wireless candidates=1 subsystem=pci bdf=00f1:01:00.0 .*driver=fakewlan module=fakewlan_mod netdev=fakewlan0 root_port=00f1:00:00.0 root_port_children=1 rp_clear=yes .*in_set=yes reason=ok$')" 1
	check "set: the xHCI is the one platform USB host (two root hubs)" "$(printf '%s\n' "$setl" | grep -c '^member=xhci candidates=1 subsystem=platform .*driver=fakexhci .*in_set=yes reason=ok$')" 1
	check "set: Ethernet in" "$(printf '%s\n' "$setl" | grep -c '^member=ethernet candidates=1 .*driver=fakeeth .*in_set=yes reason=ok$')" 1
	check "set: NVMe in (nothing mounted under it)" "$(printf '%s\n' "$setl" | grep -c '^member=nvme candidates=1 .*driver=fakenvme .*in_set=yes reason=ok$')" 1
	check "set: the slot order" "$(printf '%s\n' "$setl" | sed -n 's/^member=\([a-z]*\) .*/\1/p' | tr '\n' ,)" "wireless,xhci,ethernet,nvme,"
	check "set: an identity group is a note" "$(has "$setl" 'note=untranslated-groups count=1')" yes
	check "set: the keyboard for recovery" "$(has "$setl" 'recovery hid_keyboard=yes')" yes
	check "set rows: no path or driver in the board log" "$(printf '%s\n' "$setl" > "$d/set.conf"; j1_set_rows "$d/set.conf" | grep -cE 'fake|/sys/')" 0

	# one more census (each is slow to fork on Windows): a mounted NVMe partition, KD on
	# the NVMe, and a second child on the wireless function's port, all at once
	printf '/ /dev/mmcblk0p1 ext4\n/mnt/data /dev/nvme0n1p1 ext4\n' > "$fx/mounts"
	fxpci platform/fakebus/1000.fakepcie/pci00f1:00/00f1:00:00.0/00f1:01:00.1 0x0d1100 fakeother 06
	cen2="$(FX_D22=no FX_KD_SRC='/dev/nvme0n1p1 ext4' fxrun b_census 2>/dev/null)"
	setl="$(printf '%s\n' "$cen2" | j_set_rules)"
	check "census without D22: no kpageflags probe and no configuration space read" \
		"$(has "$cen2" 'kpf tag=probe result=not-read reason=D22-not-yes')/$(printf '%s\n' "$cen2" | grep -c '^pci census .* cmd=not-read bme=not-read$' | sed 's/^[1-9][0-9]*$/some/')/$(printf '%s\n' "$cen2" | grep -c ' cmd=0x')" "yes/some/0"
	check "set: a mounted NVMe partition and KD under the NVMe take it out" "$(printf '%s\n' "$setl" | grep -c '^member=nvme .*mounted_descendant=yes home_or_kd_under=yes in_set=no reason=mounted-descendant,home-or-kd-under$')" 1
	check "set: a second child on the wireless port takes it out, no port clear" "$(printf '%s\n' "$setl" | grep -c '^member=wireless .*root_port_children=2 rp_clear=no .*in_set=no reason=shared-root-port$')" 1
	check "set: the Ethernet function is untouched by the other members' rules" "$(printf '%s\n' "$setl" | grep -c '^member=ethernet .*in_set=yes reason=ok$')" 1
	rm -f "$fx/sys/bus/pci/devices/00f1:01:00.1.lnk"
	printf '/ /dev/mmcblk0p1 ext4\n' > "$fx/mounts"
	rm -rf "$d/shm"/s1kpf.*

	# the set-file rules on synthetic census lines
	cw="cen pcidev bdf=00f1:01:00.0 class=0x028000 driver=fakewlan module=none parent=00f1:00:00.0 netdev=fakewlan0 path=/sys/devices/p/pci00f1:00/00f1:00:00.0/00f1:01:00.0"
	setl="$(printf '%s\n%s\n' "$cw" "${cw//00f1:01:00.0/00f1:02:00.0}" | j_set_rules)"
	check "set rules: two wireless-class functions are ambiguous" "$(printf '%s\n' "$setl" | grep -c '^member=wireless candidates=2 .*in_set=no reason=ambiguous$')" 1
	setl="$(printf '%s\n' "${cw/driver=fakewlan/driver=none}" | j_set_rules)"
	check "set rules: an unbound function is out" "$(printf '%s\n' "$setl" | grep -c '^member=wireless .*in_set=no reason=no-driver$')" 1
	check "set rules: an absent class is out" "$(printf '%s\n' "$setl" | grep -c '^member=ethernet candidates=0 .*in_set=no reason=absent$')" 1
	setl="$(printf '%s\ncen blkchain use=mount fstype=nfs4 path=network\n' "$cw" | j_set_rules)"
	check "set rules: a network mount takes the wireless function out" "$(printf '%s\n' "$setl" | grep -c '^member=wireless .*in_set=no reason=network-mount$')" 1
	setl="$(printf '%s\ncen blkchain use=home fstype=ext4 path=/sys/devices/p/pci00f1:00/00f1:00:00.0/00f1:01:00.0/fakeblk/blk0\n' "$cw" | j_set_rules)"
	check "set rules: \$HOME under the wireless function" "$(printf '%s\n' "$setl" | grep -c '^member=wireless .*in_set=no reason=home-or-kd-under$')" 1
	check "set rules: ... is note=no-j3-j4" "$(has "$setl" 'note=no-j3-j4')" yes
	setl="$(printf '%s\ncen blkchain use=home fstype=ext4 path=/sys/devices/p/pci00f1:00/00f1:00:00.0/00f1:01:00.0x/blk0\n' "$cw" | j_set_rules)"
	check "set rules: a sibling path sharing a prefix is not under it" "$(printf '%s\n' "$setl" | grep -c '^member=wireless .*in_set=yes reason=ok$')" 1
	setl="$(printf '%s\ncen blkchain use=root fstype=ext4 path=unresolved\n' "${cw/class=0x028000/class=0x010802}" | j_set_rules)"
	check "set rules: an unresolved root takes the NVMe out (fail-safe)" "$(printf '%s\n' "$setl" | grep -c '^member=nvme .*in_set=no reason=unresolved-storage$')" 1

	# marker detection on a synthetic COM3 (§15.4.2 item 6)
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=6000 ---\n' "$now" > "$d/j1c.log"
	printf 'Ubuntu synthetic login:\r\n[  100.000001] s1wq: j1 probe result=0\r\n' >> "$d/j1c.log"
	off=$(stat -c %s "$d/j1c.log")
	printf 'systemd[1]: Started /bin/sh -c echo "<3>s1wq: j1 timer result=0" > /dev/kmsg.\r\n[  130.123456] s1wq: j1 timer result=1\r\n' >> "$d/j1c.log"
	check "marker: a probe line before the offset is not seen" "$(com3_marker_seen "$d/j1c.log" "$off" 's1wq: j1 probe result=0' && echo yes || echo no)" no
	check "marker: the probe line from the start is seen" "$(com3_marker_seen "$d/j1c.log" 0 's1wq: j1 probe result=0' && echo yes || echo no)" yes
	check "marker: a status line quoting the command, and result=1, are not the timer marker" "$(com3_marker_seen "$d/j1c.log" "$off" 's1wq: j1 timer result=0' && echo yes || echo no)" no
	printf '[  131.000000] s1wq: j1 timer result=0 \r\n' >> "$d/j1c.log"
	check "marker: the timer line with a printk time and CRLF is seen" "$(com3_marker_seen "$d/j1c.log" "$off" 's1wq: j1 timer result=0' && echo yes || echo no)" yes
	check "marker wait: seen at once" "$(com3_wait_marker "$d/j1c.log" "$off" 's1wq: j1 timer result=0' 0; echo $?)" 0
	check "marker wait: a bound of 0 gives up" "$(com3_wait_marker "$d/j1c.log" "$off" 's1wq: j1 other result=0' 0; echo $?)" 1

	# the trace and the restart line (§15.4.2 item 8)
	cp "$d/j1c.log" "$d/j1t.log"
	off=$(stat -c %s "$d/j1t.log")
	printf '[  200.000000] fakeeth 00f2:01:00.0: shutdown\r\n[  200.100000] fakebus 4000.fakeusb: shutdown_pre\r\n[  200.200000] fakebus 4000.fakeusb: shutdown\r\n[  201.000000] reboot: Restarting system\r\n[    1.000000] fakeeth 00f2:01:00.0: shutdown\r\n' >> "$d/j1t.log"
	check "trace: device lines before the restart line only" "$(com3_trace_counts "$d/j1t.log" "$off")" "trace_lines=3 trace_pci_lines=1 restart_seen=yes"
	check "trace: nothing before the offset" "$(com3_trace_counts "$d/j1c.log" 0)" "trace_lines=0 trace_pci_lines=0 restart_seen=no"
	check "restart wait: seen at once" "$(com3_wait_re "$d/j1t.log" "$off" 'Restarting system' 0 | grep -cE '^[0-9]+$')" 1
	check "restart wait: a bound of 0 gives up" "$(com3_wait_re "$d/j1c.log" 0 'Restarting system' 0; echo "rc=$?")" "rc=1"

	# §15.4.2's go/no-go table
	local j1ok="systemd_run=yes probe_entries=64 probe_marker=yes timer_marker=yes d21=yes trace_lines=5 shutdown_s=100 stuck_s=600"
	# shellcheck disable=SC2086  # deliberate word-splitting of the key=value list
	out="$(j1_rows $j1ok)"
	check "go/no-go: all met, the trace cheap: J2 with the trace" "$(printf '%s\n' "$out" | tail -n 1)" "j1 next=J2 trace=go"
	check "go/no-go: the detached row is met" "$(has "$out" 'j1 row detached MET')" yes
	check "go/no-go: no systemd-run: F42, J2b" "$(j1_rows ${j1ok/systemd_run=yes/systemd_run=no} | tail -n 1)" "j1 next=J2b trace=go"
	check "go/no-go: no timer marker: F42" "$(has "$(j1_rows ${j1ok/timer_marker=yes/timer_marker=no})" 'detached F42')" yes
	check "go/no-go: no probe marker: J2b" "$(j1_rows ${j1ok/probe_marker=yes/probe_marker=no} | tail -n 1)" "j1 next=J2b trace=go"
	check "go/no-go: no trace lines: F38, no trace" "$(j1_rows ${j1ok/trace_lines=5/trace_lines=0} | tail -n 1)" "j1 next=J2 trace=no-go"
	check "go/no-go: the shutdown at half of S1_STUCK_S is no-go" "$(j1_rows ${j1ok/shutdown_s=100/shutdown_s=300} | tail -n 1)" "j1 next=J2 trace=no-go"
	check "go/no-go: just under half is go" "$(j1_rows ${j1ok/shutdown_s=100/shutdown_s=299} | tail -n 1)" "j1 next=J2 trace=go"
	check "go/no-go: an unknown shutdown time is no-go" "$(j1_rows ${j1ok/shutdown_s=100/shutdown_s=unknown} | tail -n 1)" "j1 next=J2 trace=no-go"
	check "go/no-go: D21 not yes: no trace" "$(j1_rows ${j1ok/d21=yes/d21=no} | tail -n 1)" "j1 next=J2 trace=off"
	check "go/no-go: a short dd probe is recorded, not a stop" "$(has "$(j1_rows ${j1ok/probe_entries=64/probe_entries=8})" 'snapshot UNPROVEN')" yes
	check "go/no-go: a watchdog return is F27" "$(has "$(j1_rows $j1ok watchdog=yes)" 'reboot F27')" yes

	# b_kpf_snap on the fixture, its header against kpf-decode.py, and b_kpf_rm
	out="$(fxrun b_kpf_snap prequiesce 2>/dev/null)"
	check "kpf snap: the design's entry count" "$(has "$out" 'kpf tag=prequiesce result=ok entries=569344')" yes
	kdir="$(printf '%s\n' "$out" | sed -n 's/^kpf tag=prequiesce dir=//p')"
	hdr="$kdir/j1-20260914T000000Z-kpf-prequiesce-header.txt"
	check "kpf snap: the header's first line" "$(head -n 1 "$hdr" 2>/dev/null)" "kpf_header=1"
	check "kpf snap: the w2 range line" "$(grep -c '^range=w2 pfn_start=0x100000 pfn_count=565248 src_offset=0x800000 slice_offset=32768$' "$hdr" 2>/dev/null)" 1
	if [ -f "$S1DIR/kpf-decode.py" ] && find_python; then
		out="$(bash "$0" kpf-decode "$hdr" 2>&1)"
		check "kpf-decode subcommand: the header decodes" "$(has "$out" 'decode result=ok snapshots=1')" yes
	else
		echo "  skip  kpf-decode subcommand: no kpf-decode.py or python here"
	fi
	check "kpf snap: an unknown tag is refused" "$(has "$(fxrun b_kpf_snap other)" 'result=refused reason=tag')" yes
	check "kpf rm: a path outside the pattern is refused" "$(has "$(fxrun b_kpf_rm "$d")" 'kpf rm refused')" yes
	check "kpf rm: the snapshot directory is removed" "$(has "$(fxrun b_kpf_rm "$kdir")" 'left=no')" yes
	bash "$0" kpf-decode >/dev/null 2>&1
	check "kpf-decode without a header is a usage error" "$?" 2

	# the J board functions: defined, parseable, and within §15.1's Never items
	check "BOARD_FUNCS are all defined" "$(declare -f $BOARD_FUNCS >/dev/null 2>&1; echo $?)" 0
	check "the board functions parse" "$(declare -f $BOARD_FUNCS | bash -n 2>&1; echo "rc=$?")" "rc=0"
	out="$(declare -f s1_rl b_kpf_snap b_kpf_rm b_pci_state b_census_chain b_census_slaves b_census_path b_census b_trace_on b_j1_probe b_j1_timer)"
	check "J board functions read no address or serial file and run no network or radio tool" \
		"$(printf '%s\n' "$out" | grep -cE '/address|/serial|nmcli|ip addr|(^|[^A-Za-z_])iw |lsusb|hciconfig|rfkill (block|unblock|list)|of=/sys|driver_override|/remove|/rescan|/reset')" 0

	# ---- the detached sequence (§15.4.3-§15.4.6, §15.5 A5 and A6), all synthetic: fake names,
	# a fixture root, stubs for every external command the sequence would run on the board.
	local wg wr wb arm g line rcx sq a cw bl jd cap4 off4 jr2 jr2a kd2 cb res
	wg="$d/wg"; wr="$d/wr"; wb="$d/wbin"
	mkdir -p "$wg" "$wb"
	wqfake() {
		local W=/sys/devices/platform/fakebus/1000.fakepcie/pci00f1:00/00f1:00:00.0/00f1:01:00.0
		local E=/sys/devices/platform/fakebus/2000.fakepcie/pci00f2:00/00f2:00:00.0/00f2:01:00.0
		local N=/sys/devices/platform/fakebus/3000.fakepcie/pci00f3:00/00f3:00:00.0/00f3:01:00.0
		WQG_W_PATH=$W; WQG_W_BDF=00f1:01:00.0; WQG_W_DRV=fakewlan; WQG_W_MOD=fakewlan_mod; WQG_W_NETDEV=fakewlan0; WQG_W_RP=00f1:00:00.0; WQG_W_RPCLEAR=yes
		WQG_X_PATH=/sys/devices/platform/fakebus/4000.fakeusb; WQG_X_BDF=none; WQG_X_DRV=fakexhci; WQG_X_MOD=fakexhci_mod; WQG_X_NETDEV=none; WQG_X_RP=none; WQG_X_RPCLEAR=no
		WQG_E_PATH=$E; WQG_E_BDF=00f2:01:00.0; WQG_E_DRV=fakeeth; WQG_E_MOD=fakeeth_mod; WQG_E_NETDEV=none; WQG_E_RP=00f2:00:00.0; WQG_E_RPCLEAR=yes
		WQG_N_PATH=$N; WQG_N_BDF=00f3:01:00.0; WQG_N_DRV=fakenvme; WQG_N_MOD=fakenvme_mod; WQG_N_NETDEV=none; WQG_N_RP=00f3:00:00.0; WQG_N_RPCLEAR=yes
		WQG_XHCI_PATH=$WQG_X_PATH; WQG_SETPCI=yes; WQG_TRACE=no; WQG_UTC=20260914T000000Z
		WQG_HOME_DEV=/sys/devices/platform/fakebus/5000.fakesd/mmc_host/mmc0/mmc0:0001/block/mmcblk0/mmcblk0p1; WQG_KD_DEV=$WQG_HOME_DEV
	}
	wqarm() {
		local L
		WQG_ARM="$1"; WQG_FINAL=kexec
		[ "$1" = j3 ] && WQG_FINAL=none
		for L in W X E N; do printf -v "WQG_${L}_IN" '%s' "$([ "$1" = control ] && echo no || echo yes)"; done
	}

	# generation: the three arms as the board would get them, through bash -n, the allow-list
	# gate and both systemd-run lines; the same fixed slot list in each; a %q round trip
	wqfake
	WQG_ROOT=""; WQG_KMSG=/dev/kmsg; WQG_LOG=/home/fakeuser/s1-h1-20260914T000000Z-wq.log
	sq=""
	for arm in control j3 remove; do
		wqarm "$arm"
		b_wq_gen main > "$wg/$arm-wq.sh"
		b_wq_gen fallback > "$wg/$arm-wqfb.sh"
		out="$(wq_gate_all "$wg/$arm-wq.sh" "$wg/$arm-wqfb.sh" \
			"sudo -n systemd-run --unit=s1wq-20260914T000000Z --collect --no-block -p TimeoutStopSec=30 /bin/bash \"\$HOME/$arm-wq.sh\"" \
			"sudo -n systemd-run --unit=s1wqfb-20260914T000000Z --on-active=645s --timer-property=AccuracySec=1s --collect /bin/bash \"\$HOME/$arm-wqfb.sh\"" \
			20260914T000000Z 645)"
		rcx=$?
		check "generation $arm: bash -n, the allow-list gate and both systemd-run lines pass" "$rcx/$(printf '%s\n' "$out" | grep -c ' ok')" "0/6"
		sq="$sq$(sed -n 's/^ *for s in \(.*\);$/\1/p' "$wg/$arm-wq.sh")|"
	done
	check "generation: one fixed slot list, equal in the three arms and to WQ_SLOT_LIST" "$sq" "$WQ_SLOT_LIST|$WQ_SLOT_LIST|$WQ_SLOT_LIST|"
	check "generation: WQ_SLOT_COUNT is the list's length" "$(printf '%s\n' $WQ_SLOT_LIST | wc -l)" "$WQ_SLOT_COUNT"
	g='a b\c$d'"'"'e;f`g'
	check "generation: a printf %q value round-trips" "$(bash -c "$(printf 'X=%q' "$g"); printf '%s' \"\$X\"")" "$g"
	check "generation: the header's member path round-trips" "$(bash -c "$(grep '^WQ_W_PATH=' "$wg/remove-wq.sh"); printf '%s' \"\$WQ_W_PATH\"")" "$WQG_W_PATH"
	check "generation: no heredoc in any generated script" "$(cat "$wg"/*.sh | grep -c '<<')" 0

	# the gate: one injection per refused form (§15.5 A5), each into the real control script,
	# inside b_wq_main's body (so the function-scoped forms are tested, not only the rule that
	# refuses a command outside the functions)
	wqinj() {
		awk -v l="$1" '{ print } $0 == "    local s n rc L v t0 now;" { print l }' "$wg/control-wq.sh" > "$wg/inj-wq.sh"
		wq_gate "$wg/inj-wq.sh" main 2>&1
	}
	check "gate: an allowed read injected into b_wq_main passes (the injection lands inside a function)" "$(has "$(wqinj 'cat /sys/kernel/kexec_loaded')" 'wqgate inj-wq.sh ok')" yes
	awk '$0 == "b_wq_main >> \"$WQ_LOG\" 2>&1" { print "cat /sys/kernel/kexec_loaded" } { print }' "$wg/control-wq.sh" > "$wg/inj-wq.sh"
	check "gate refuses a command outside the functions" "$(has "$(wq_gate "$wg/inj-wq.sh" main)" 'outside the functions')" yes
	sed 's|^WQ_W_PATH=.*|WQ_W_PATH=/home/fakeuser|' "$wg/control-wq.sh" > "$wg/inj-wq.sh"
	check "gate refuses a member path that is not a /sys/devices path" "$(has "$(wq_gate "$wg/inj-wq.sh" main)" 'WQ_W_PATH is not none or a /sys/devices path')" yes
	while IFS= read -r line; do
		out="$(wqinj "${line#*@@}")"
		check "gate refuses ${line%%@@*}" "$(has "$out" ' FAIL refused=')" yes
	done < <(printf '%s\n' 'a quote-split address read@@cat "/sys/class/net/fake0/addr"ess' 'a quote-split /etc path@@cat $WQ_ROOT/e""tc/fakefile' \
		'grep with a file argument@@grep "" /proc/uptime' 'sha256sum of a home file@@sha256sum /home/fakeuser/.ssh/fakekey' \
		'a /dev/tcp input redirect@@read -r x < "$WQ_ROOT/dev/tcp/192.0.2.1/80"' 'cat of $HOME@@cat "$HOME/.ssh/fakekey"' \
		'a variable read path outside its function@@cat "$dev/class"' 'modprobe -r of a literal module@@modprobe -r fakemod' \
		'ip link down of a literal interface@@ip link set dev fakeeth0 down' 'setpci of a literal function@@setpci -s 00ff:00:00.0 COMMAND=0000:0004' \
		'a second systemctl kexec@@systemctl kexec' 'kexec -u outside its functions@@kexec -u' 'dmesg -C@@dmesg -C')
	while IFS= read -r line; do
		out="$(wqinj "${line#*@@}")"
		check "gate refuses ${line%%@@*}" "$(has "$out" ' FAIL refused=')" yes
	done < <(printf '%s\n' 'rfkill@@rfkill block all' 'nmcli@@nmcli radio wifi off' 'iw@@iw dev' 'ip addr@@ip addr show' \
		'systemctl enable@@systemctl enable fake.service' 'systemctl disable@@systemctl disable fake.service' \
		'systemctl mask@@systemctl mask fake.service' 'systemctl stop@@systemctl stop fake.service' \
		'systemctl isolate@@systemctl isolate rescue.target' '/etc@@cat /etc/hostname' '/boot@@cat /boot/Image' \
		'/var/lib@@cat /var/lib/fake/state' 'apt@@apt install fake' 'dpkg@@dpkg -l' 'extlinux@@extlinux --install x' \
		'--force --force@@systemctl reboot --force --force' '-ff@@reboot -ff' '/dev/mem@@cat /dev/mem' 'devmem@@devmem 0x0' \
		'dd@@dd if=/dev/zero bs=1 count=1' 'of= on /sys@@printf x | dd of=/sys/bus/pci/devices/00ff:00:00.0/config' \
		'tar@@tar cf x.tar y' 'a remove write@@printf 1 > /sys/bus/pci/devices/00ff:00:00.0/remove' \
		'a rescan write@@printf 1 > /sys/bus/pci/rescan' 'a reset write@@printf 1 > /sys/bus/pci/devices/00ff:00:00.0/reset' \
		'a driver_override write@@printf x > /sys/bus/pci/devices/00ff:00:00.0/driver_override' \
		'a new_id write@@printf x > /sys/bus/pci/drivers/fake/new_id' \
		'a power/control write@@printf on > /sys/bus/pci/devices/00ff:00:00.0/power/control' \
		'an address read@@cat /sys/class/net/fake0/address' 'a serial read@@cat /sys/bus/usb/devices/1-1/serial' \
		'lsusb@@lsusb -v' 'hciconfig@@hciconfig -a' 'a backtick@@x=`date`' 'a heredoc@@cat <<EOF' 'a background &@@sleep 1 &' \
		'eval@@eval x' 'a redirect to an unlisted path@@printf x > /tmp/fake' 'sudo without -n@@sudo cat /proc/uptime' \
		'dmesg -n outside b_trace_on@@dmesg -n 1' 'a function not in WQ_FUNCS@@b_extra () ')
	check "gate: a second systemctl reboot --force is refused" "$(has "$(wqinj 'systemctl reboot --force')" 'not exactly once')" yes
	check "runline: an extra property is refused" "$(wq_gate_runline main "sudo -n systemd-run --unit=s1wq-20260914T000000Z --collect --no-block -p TimeoutStopSec=30 -p ExecStartPre=/bin/true /bin/bash \"\$HOME/control-wq.sh\"" 20260914T000000Z control-wq.sh 645 >/dev/null; echo $?)" 1
	check "runline: another unit name is refused" "$(wq_gate_runline main "sudo -n systemd-run --unit=s1wq-other --collect --no-block -p TimeoutStopSec=30 /bin/bash \"\$HOME/control-wq.sh\"" 20260914T000000Z control-wq.sh 645 >/dev/null; echo $?)" 1
	check "runline: a fallback with another delay is refused" "$(wq_gate_runline fallback "sudo -n systemd-run --unit=s1wqfb-20260914T000000Z --on-active=10s --timer-property=AccuracySec=1s --collect /bin/bash \"\$HOME/control-wqfb.sh\"" 20260914T000000Z control-wqfb.sh 645 >/dev/null; echo $?)" 1

	# a dry run of the generated scripts on the PC: WQ_ROOT is a fixture tree, WQ_KMSG a file,
	# and ip, modprobe, setpci, kexec, systemctl, dmesg, sleep, sync, ps, readlink and sudo are
	# stubs on PATH (a driver link is a <link>.lnk file; an unbind file naming the function
	# unbinds it; setpci clears bit 2 of the fixture's Command register unless FX_NOCLEAR)
	wqstub() { local n="$1"; shift; printf '%s\n' '#!/bin/bash' "$@" > "$wb/$n"; chmod +x "$wb/$n"; }
	wqstub sleep 'exit 0'
	wqstub sync 'exit 0'
	wqstub ps 'exit 1'
	wqstub kexec 'printf "kexec %s\n" "$*" >> "$FX_CALLS"'
	wqstub ip 'printf "ip %s\n" "$*" >> "$FX_CALLS"'
	wqstub modprobe 'printf "modprobe %s\n" "$*" >> "$FX_CALLS"'
	wqstub sudo '[ "$1" = -n ] && shift' 'exec "$@"'
	wqstub systemctl 'printf "systemctl %s\n" "$*" >> "$FX_CALLS"' 'case "$1" in' 'is-system-running) cat "$FX_STATE" ;;' \
		'is-active) echo active ;;' 'kexec) exit "${FX_KEXEC_RC:-0}" ;;' 'esac' 'exit 0'
	wqstub dmesg 'n=$(cat "$FX_DMESG_N" 2>/dev/null || echo 0); n=$(( n + 1 )); echo "$n" > "$FX_DMESG_N"' \
		'[ -n "${FX_OLD_OOPS:-}" ] && printf "%s\n" "[    5.000000] Internal error: synthetic earlier line" "[   90.000000] s1wq: begin arm=control final=kexec result=0"' \
		'[ "$n" -ge "${FX_OOPS_AT:-9999}" ] && echo "Unable to handle kernel paging request (synthetic)"' 'exit 0'
	wqstub readlink 'p="${@: -1}"' \
		'if [ -f "$p.lnk" ]; then t="$(cat "$p.lnk")"; d="${p%/driver}"; if [ "$d" != "$p" ] && grep -qx "${d##*/}" "$t/unbind" 2>/dev/null; then exit 1; fi; printf "%s\n" "$t"; exit 0; fi' \
		'[ -e "$p" ] && { printf "%s\n" "$p"; exit 0; }' 'exit 1'
	wqstub setpci 'bdf="$2"; op="$3"; f="$(awk -v b="$bdf" "\$1 == b { print \$2 }" "$FX_MAP")/config"' \
		'set -- $(od -An -tu1 -j4 -N2 "$f")' \
		'if [ "$op" = COMMAND=0000:0004 ]; then printf "setpci %s clear\n" "$bdf" >> "$FX_CALLS"; [ -n "${FX_NOCLEAR:-}" ] && exit 0; printf "\\x00\\x00\\x00\\x00\\x$(printf %02x $(( $1 & 251 )))\\x$(printf %02x "$2")" > "$f"; exit 0; fi' \
		'printf "%02x%02x\n" "$2" "$1"'
	printf 'stopping\n' > "$d/wstop"
	printf 'running\n' > "$d/wrun"
	# a fresh fixture: FXU the uptime, FXG the governor; Command registers: endpoints 0x0406
	# (Bus Master set), NVMe's 0x0402 (clear), every parent port 0x0407
	wqfx() {
		local L v p
		rm -rf "$wr"
		mkdir -p "$wr/home" "$wr/proc/self" "$wr/sys/kernel" "$wr/sys/fs/cgroup/fake.service"
		printf '0::/fake.service\n' > "$wr/proc/self/cgroup"
		: > "$wr/sys/fs/cgroup/fake.service/cgroup.procs"
		printf '%s 456.78\n' "${FXU:-123.45}" > "$wr/proc/uptime"
		printf '1\n' > "$wr/sys/kernel/kexec_loaded"
		for p in policy0 policy4; do
			mkdir -p "$wr/sys/devices/system/cpu/cpufreq/$p"
			printf '%s\n' "${FXG:-performance}" > "$wr/sys/devices/system/cpu/cpufreq/$p/scaling_governor"
		done
		: > "$d/wmap"
		for L in W E N; do
			v="WQG_${L}_PATH"; p="${!v}"
			mkdir -p "$wr$p"
			if [ "$L" = N ]; then printf '\x00\x00\x00\x00\x02\x04' > "$wr$p/config"; else printf '\x00\x00\x00\x00\x06\x04' > "$wr$p/config"; fi
			printf '\x00\x00\x00\x00\x07\x04' > "$wr${p%/*}/config"
			v="WQG_${L}_DRV"
			mkdir -p "$wr/sys/bus/pci/drivers/${!v}"
			if [ "$L" = W ]; then mkdir -p "$wr/sys/module/$WQG_W_MOD"; printf '%s\n' "$wr/sys/module/$WQG_W_MOD" > "$wr/sys/bus/pci/drivers/${!v}/module.lnk"; fi
			printf '%s\n' "$wr/sys/bus/pci/drivers/${!v}" > "$wr$p/driver.lnk"
			printf '%s %s\n%s %s\n' "${p##*/}" "$wr$p" "$(basename "${p%/*}")" "$wr${p%/*}" >> "$d/wmap"
		done
		mkdir -p "$wr$WQG_W_PATH/net/fakewlan0" "$wr$WQG_X_PATH" "$wr/sys/bus/platform/drivers/fakexhci"
		printf '%s\n' "$wr/sys/bus/platform/drivers/fakexhci" > "$wr$WQG_X_PATH/driver.lnk"
	}
	# $1 arm, $2 main|fallback, then VAR=value for the stubs. Prints the script's exit code.
	wqrun() {
		local ar="$1" k="$2"
		shift 2
		wqarm "$ar"
		WQG_ROOT="$wr"; WQG_KMSG="$wr/kmsg"
		b_wq_gen "$k" > "$wg/run.sh"
		: > "$wr/kmsg"; : > "$WQG_LOG"; : > "$d/wcalls"; rm -f "$d/wdn"
		env PATH="$wb:$PATH" FX_CALLS="$d/wcalls" FX_STATE="$d/wstop" FX_DMESG_N="$d/wdn" FX_MAP="$d/wmap" "$@" bash "$wg/run.sh" </dev/null >/dev/null 2>&1
		echo "$?"
	}
	# wqrun runs in a command substitution, so the log's path is set here. The fixture's WQ_KMSG
	# is a plain file that each '>' marker write replaces (on the board every write to /dev/kmsg
	# is one record): the markers are read, in order, from wq.log, and WQ_KMSG holds the last.
	WQG_LOG="$wr/home/s1-h1-20260914T000000Z-wq.log"
	kl() { tr -d '\r' < "$WQG_LOG" | sed -n 's/^s1wq: /<3>s1wq: /p'; }
	wqfx
	rcx="$(wqrun control main)"
	check "dry run control: exit 0 after 'shutdown in progress'" "$rcx/$(kl | tail -n 1)" "0/<3>s1wq: shutdown in progress"
	check "dry run control: the console marker is written to WQ_KMSG at level 3" "$(tr -d '\r' < "$wr/kmsg")" "<3>s1wq: shutdown in progress"
	check "dry run control: nine slot markers, in order" "$(kl | sed -n 's/^<3>s1wq: slot\([0-9]\) .*/\1/p' | tr -d '\n')" 123456789
	check "dry run control: actions skip, Bus Master read only" "$(kl | grep -c ' result=skip$')/$(kl | grep -cE 'slot[479] [a-z]+-bme result=0$')" "6/3"
	check "dry run control: begin, kexec issuing, shutdown in progress" "$(kl | grep -cE '^<3>s1wq: (begin arm=control final=kexec result=0|kexec issuing|shutdown in progress)$')" 3
	check "dry run control: no configuration write, unbind, removal or unload; one kexec" "$(grep -cE 'clear$|^ip |^modprobe |^kexec ' "$d/wcalls")/$(grep -c '^systemctl kexec$' "$d/wcalls")" "0/1"
	check "dry run control: the markers are in wq.log too" "$(grep -c '^s1wq: slot' "$WQG_LOG")" 9
	wqfx
	rcx="$(wqrun j3 main)"
	check "dry run j3: exit 0 after 'no final action', no kexec" "$rcx/$(kl | tail -n 1)/$(grep -c '^systemctl kexec$' "$d/wcalls")" "0/<3>s1wq: no final action result=0/0"
	check "dry run j3: every slot of the set result=0" "$(kl | grep -cE 'slot[1-9] [a-z-]+ result=0$')" 9
	check "dry run j3: interface down, module removal, the wireless unbind" "$(grep -c '^ip link set dev fakewlan0 down$' "$d/wcalls")/$(grep -c '^modprobe -r fakewlan_mod$' "$d/wcalls")/$(cat "$wr/sys/bus/pci/drivers/fakewlan/unbind")" "1/1/00f1:01:00.0"
	check "dry run j3: only set Bus Master bits are cleared (endpoints and single-child ports)" "$(grep -c 'clear$' "$d/wcalls")" 5
	check "dry run j3: bme_after_unbind is recorded before the clear" "$(grep -c '^bme_after_unbind member=W value=1$' "$WQG_LOG")" 1
	wqfx
	rcx="$(wqrun remove main FX_NOCLEAR=1)"
	check "dry run remove: a bit that stays set aborts bme-not-cleared (exit 5)" "$rcx/$(kl | tail -n 1)" "5/<3>s1wq: abort reason=bme-not-cleared"
	check "dry run remove: the abort unloads and reboots, no kexec" "$(grep -cE '^kexec -u$|^systemctl reboot$' "$d/wcalls")/$(grep -c '^systemctl kexec$' "$d/wcalls")" "2/0"
	FXU=1800.20 wqfx
	check "dry run: uptime 1,800 s at the issue aborts (F48)" "$(wqrun control main)/$(kl | tail -n 1)" "5/<3>s1wq: abort reason=uptime"
	FXG=powersave wqfx
	check "dry run: a governor that is not performance aborts (F48)" "$(wqrun control main)/$(kl | tail -n 1)" "5/<3>s1wq: abort reason=governor"
	wqfx
	check "dry run: systemctl kexec rc 1 is kexec-rejected" "$(wqrun control main FX_KEXEC_RC=1)/$(kl | tail -n 1)" "5/<3>s1wq: abort reason=kexec-rejected"
	check "dry run: rc 0 and not stopping after the wait: kexec did not happen" "$(wqrun control main FX_STATE="$d/wrun")/$(kl | tail -n 1)/$(grep -c '^kexec -u$' "$d/wcalls")" "5/<3>s1wq: kexec did not happen/1"
	check "dry run: a new Oops after slot 3 aborts oops (F47)" "$(wqrun control main FX_OOPS_AT=4)/$(kl | sed -n 's/^<3>s1wq: slot\([0-9]\) .*/\1/p' | tr -d '\n')/$(kl | tail -n 1)" "5/123/<3>s1wq: abort reason=oops"
	printf '%s\n' "$wr/sys/bus/pci/drivers/fakeother" > "$wr$WQG_E_PATH/driver.lnk"
	check "dry run remove: a driver link that is not J-set.conf's aborts resolve, before any slot" "$(wqrun remove main)/$(kl | grep -c 'slot')/$(kl | tail -n 1)" "5/0/<3>s1wq: abort reason=resolve"
	wqfx
	g="$WQG_HOME_DEV"; WQG_HOME_DEV="$WQG_N_PATH/nvme/nvme0/nvme0n1"
	check "dry run remove: \$HOME under a set member aborts" "$(wqrun remove main)/$(kl | tail -n 1)" "5/<3>s1wq: abort reason=home-under-member"
	WQG_HOME_DEV="$g"
	check "dry run fallback, not stopping: fire, then exactly one forced reboot" "$(wqrun control fallback FX_STATE="$d/wrun")/$(kl | tr '\n' '|')/$(grep -c '^systemctl reboot$' "$d/wcalls")/$(grep -c '^systemctl reboot --force$' "$d/wcalls")" "0/<3>s1wq: fallback firing|<3>s1wq: fallback forcing|/1/1"
	check "dry run fallback, stopping: idle, no reboot" "$(wqrun control fallback)/$(kl)/$(grep -c 'reboot' "$d/wcalls")" "0/<3>s1wq: fallback idle shutdown in progress/0"
	check "dry run fallback: a short dmesg is kept whole in the tail (not emptied)" "$(wqrun control fallback FX_STATE="$d/wrun" FX_OLD_OOPS=1 >/dev/null; grep -c '^\[ *5.000000\] Internal error: synthetic earlier line$' "$WQG_LOG")" 1
	wqfx
	check "dry run control: an Oops line older than the begin marker does not abort" "$(wqrun control main FX_OLD_OOPS=1)/$(kl | tail -n 1)" "0/<3>s1wq: shutdown in progress"
	wqfx
	printf '%s\n' "$wr/sys/module/otherfake_mod" > "$wr/sys/bus/pci/drivers/fakewlan/module.lnk"
	check "dry run remove: a wireless module that is not J-set.conf's aborts resolve, before any slot" "$(wqrun remove main)/$(kl | grep -c 'slot')/$(kl | tail -n 1)" "5/0/<3>s1wq: abort reason=resolve"
	wqfx
	printf '\xff\xff\xff\xff\xff\xff' > "$wr$WQG_N_PATH/config"
	out="$(
		export PATH="$wb:$PATH" FX_CALLS="$d/wcalls" FX_MAP="$d/wmap"
		: > "$d/wcalls"
		WQ_ROOT="$wr"; WQ_SETPCI=yes; WQ_N_PATH="$WQG_N_PATH"; WQ_N_RPCLEAR=no; WQ_E_PATH="$WQG_E_PATH"; WQ_E_RPCLEAR=no
		b_wq_bme N clear 0; echo "rc=$?"
		b_wq_bme E clear 1; echo "rc=$?"
		echo "clears=$(grep -c 'clear$' "$d/wcalls")"
	)"
	check "bme: a Command register reading 0xffff is unread and gets no setpci (rc 2)" "$(has "$out" 'bme member=N role=endpoint mode=clear dev=00f3:01:00.0 cmd=0xffff')/$(printf '%s\n' "$out" | sed -n 2p)" "yes/rc=2"
	check "bme: a deadline already passed reads and writes nothing (budget, rc 2)" "$(has "$out" 'cmd=unread budget=exhausted')/$(printf '%s\n' "$out" | sed -n 4p)/$(printf '%s\n' "$out" | tail -n 1)" "yes/rc=2/clears=0"

	# §15.4.6's states from a synthetic COM3 (a marker before the offset never counts)
	cw="$d/wqs.log"
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=99999 ---\n' "$now" > "$cw"
	printf 'Ubuntu synthetic login:\r\n[   90.000000] s1wq: begin arm=control final=kexec result=0\r\n' >> "$cw"
	off=$(stat -c %s "$cw")
	a=1000000
	wqs() { wq_state "$1" "$off" "$a" "$2" | head -n 1 | sed 's/^wq state=\([A-Z]*\) .*/\1/'; }
	check "wq_state ARMED: no marker after the offset yet" "$(wqs "$cw" $(( a + 10 )))" ARMED
	check "wq_state STALLED: no begin by its bound" "$(wqs "$cw" $(( a + 15 + 61 )))" STALLED
	printf '[  100.000001] s1wq: j1 probe result=0\r\n' >> "$cw"
	check "wq_state: a J1 probe line is not a sequence marker" "$(wqs "$cw" $(( a + 10 )))" ARMED
	printf '[  100.000001] s1wq: begin arm=remove final=kexec result=0\r\n[  130.000001] s1wq: slot1 wireless-down result=0\r\ns1wq: slot2 wireless-unbind result=0\r\n' >> "$cw"
	check "wq_state PROGRESS: slot markers inside the schedule" "$(wqs "$cw" $(( a + 15 + 2 * 30 )))" PROGRESS
	check "wq_state STALLED: no slot3 marker by its bound" "$(wqs "$cw" $(( a + 15 + 3 * 30 + 61 )))" STALLED
	cp "$cw" "$d/wqi.log"; printf '[  400.000000] s1wq: kexec issuing\r\n' >> "$d/wqi.log"
	check "wq_state ISSUED" "$(wqs "$d/wqi.log" $(( a + 5000 )))" ISSUED
	cp "$d/wqi.log" "$d/wqj.log"; printf '[  460.000000] kexec_core: Starting new kernel\r\n' >> "$d/wqj.log"
	check "wq_state JUMPED: Starting new kernel" "$(wqs "$d/wqj.log" $(( a + 5000 )))" JUMPED
	cp "$d/wqi.log" "$d/wqj.log"; printf 'T234-SHIM EL=2 PC=0000000080080000\r\n' >> "$d/wqj.log"
	check "wq_state JUMPED: a shim line" "$(wqs "$d/wqj.log" $(( a + 5000 )))" JUMPED
	cp "$d/wqi.log" "$d/wqj.log"; printf 't234: WDT0 CR=00710010 SR=00000010\r\nS1 STATE config\r\n' >> "$d/wqj.log"
	check "wq_state JUMPED: the image's record lines when COM3 lost both jump texts (J6c review)" "$(wqs "$d/wqj.log" $(( a + 5000 )))" JUMPED
	for line in 'abort reason=oops' 'kexec did not happen' 'fallback firing'; do
		cp "$cw" "$d/wqa.log"; printf '[  400.000000] s1wq: %s\r\n' "$line" >> "$d/wqa.log"
		check "wq_state ABORTED: $line" "$(wqs "$d/wqa.log" $(( a + 100 )))" ABORTED
	done

	# advice on detached-sequence board logs (§15.5 A1, §15.7.3), through cmd_advice
	jd="$d/advrec"; mkdir -p "$jd/J4"
	printf 'D25_F25W_CUT=no\n' > "$jd/J-decisions.conf"
	cap4="$d/adv-base.log"
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=99999 ---\n' "$now" > "$cap4"
	printf 'Ubuntu synthetic login:\r\n' >> "$cap4"
	off4=$(stat -c %s "$cap4")
	printf '[  900.000001] s1wq: begin arm=remove final=kexec result=0\r\n[  930.000001] s1wq: slot1 wireless-down result=0\r\n' >> "$cap4"
	# $1 the capture, $2 armed_epoch, $3 yes for a NO RETURN line, $4 silence in seconds. Prints the
	# advice. It runs in command substitutions, so the board log's path is set out here.
	bl="$jd/J4/s1-h1-20260914T000000Z-board.log"
	wqadv() {
		{
			printf 'run com3_log=%s capture_left_s=1 return_bound_s=1200\n' "${5:-$(basename "$1")}"
			printf 'run com3_bytes_before_kexec=%s\n' "$off4"
			printf 'wq_armed armed_epoch=%s wq_fallback_s=645\n' "$2"
			[ "$3" = yes ] && printf 'jrun NO RETURN within 1845 s of the arming\n'
		} > "$bl"
		touch -d "@$(( now - $4 ))" "$1"
		S1_COM3_LOG="$1" S1_RECORD_DIR="" ADVICE_SSH=silent cmd_advice "$bl" 2>/dev/null
	}
	out="$(wqadv "$cap4" $(( now - 400 )) yes 400)"
	check "advice J4: markers and 400 s of silence, no jump: NO CUT (the hold)" "$(has "$out" 'NO CUT (detached sequence)')/$(has "$out" 'CUT ALLOWED')" "yes/no"
	cp "$cap4" "$d/adv-lx.log"; printf '[ 1000.123456] systemd-shutdown[1]: Syncing filesystems and block devices.\r\n' >> "$d/adv-lx.log"
	out="$(wqadv "$d/adv-lx.log" $(( now - 400 )) yes 400)"
	check "advice J4: F25a-looking shutdown text before the fallback deadline: NO CUT" "$(has "$out" 'NO CUT (detached sequence)')/$(has "$out" 'CUT ALLOWED')" "yes/no"
	cp "$cap4" "$d/adv-rs.log"; printf '[ 1200.000001] s1wq: fallback firing\r\n' >> "$d/adv-rs.log"
	out="$(wqadv "$d/adv-rs.log" $(( now - 645 - 1300 )) yes 700)"
	check "advice J4 after the deadline: a reset marker classes F25b, M5's exception" "$(has "$out" 'wq_class=reset')/$(has "$out" 'ONE CUT ALLOWED under M5')" "yes/yes"
	out="$(wqadv "$cap4" $(( now - 645 - 1300 )) yes 700)"
	check "advice J4 after the deadline: markers alone class F25w; D25_F25W_CUT=no: NO CUT, recovery paths" "$(has "$out" 'NO CUT (F25w): D25_F25W_CUT is not yes')/$(has "$out" 'F25w recovery without a cut')/$(has "$out" 'CUT ALLOWED')" "yes/yes/no"
	printf 'D25_F25W_CUT=yes\n' > "$jd/J-decisions.conf"
	out="$(wqadv "$cap4" $(( now - 645 - 1300 )) yes 700)"
	check "advice J4 F25w with D25_F25W_CUT=yes and 700 s: one cut" "$(has "$out" 'ONE CUT ALLOWED (F25w, under D25)')" yes
	out="$(wqadv "$cap4" $(( now - 645 - 1300 )) yes 400)"
	check "advice J4 F25w at 400 s: not yet" "$(has "$out" 'NO CUT YET (F25w)')/$(has "$out" 'CUT ALLOWED')" "yes/no"
	cp "$cap4" "$d/adv-j.log"
	printf '[ 1100.000000] s1wq: kexec issuing\r\n[ 1160.000000] kexec_core: Starting new kernel\r\nT234-SHIM EL=2 PC=0000000080080000\r\nT234 S1 s1-h1 -P4: procnto up\r\nS1 STATE launch\r\n' >> "$d/adv-j.log"
	out="$(wqadv "$d/adv-j.log" $(( now - 645 - 1300 )) yes 400)"
	check "advice J4 after a jump: today's F25a, unchanged" "$(has "$out" 'wq_class=jump')/$(has "$out" 'CUT ALLOWED (F25a)')" "yes/yes"
	printf 'T234 S1 s1-h1 -P4: resetting so the log can be recovered\r\nMB1 version synthetic\r\n' >> "$d/adv-j.log"
	out="$(wqadv "$d/adv-j.log" $(( now - 645 - 1300 )) yes 700)"
	check "advice J4 after a jump and the image's reset: today's F25b, unchanged" "$(has "$out" 'class=F25b')/$(has "$out" 'ONE CUT ALLOWED under M5')" "yes/yes"
	sed -i '/^wq_armed /d' "$bl"
	sed -i 's/^jrun NO RETURN/run NO RETURN/' "$bl"
	out="$(S1_COM3_LOG="$d/adv-j.log" S1_RECORD_DIR="" ADVICE_SSH=silent cmd_advice "$bl" 2>/dev/null)"
	check "advice on a log without wq_armed: no hold and no wq class (non-J logs unchanged)" "$(has "$out" 'wq_armed')/$(has "$out" 'wq_class')/$(has "$out" 'ONE CUT ALLOWED under M5')" "no/no/yes"
	printf 'D25_F25W_CUT=no\n' > "$jd/J-decisions.conf"
	out="$(wqadv "$cap4" $(( now - 645 - 1300 )) yes 700 other-capture.log)"
	check "advice J4 after the deadline, a capture the log does not name (offset unknown), markers only: NO CUT" "$(has "$out" 'NO CUT (detached sequence, kexec offset unknown)')/$(has "$out" 'CUT ALLOWED')" "yes/no"
	printf 'D25_F25W_CUT=yes\n' > "$jd/J-decisions.conf"
	cp "$cap4" "$d/adv-ub.log"; printf 'Jetson UEFI firmware synthetic\r\nsome unknown boot text\r\n' >> "$d/adv-ub.log"
	out="$(wqadv "$d/adv-ub.log" $(( now - 645 - 1300 )) yes 700)"
	check "advice J4 after the deadline: markers then unrecognised text stay F25b, never F25w's cut" "$(has "$out" 'F25b kept')/$(has "$out" 'F25w, under D25')/$(has "$out" 'ONE CUT ALLOWED under M5')" "yes/no/yes"
	printf 'D25_F25W_CUT=no\n' > "$jd/J-decisions.conf"
	cp "$cap4" "$d/adv-um.log"; printf 's1wq: slot2 wireless-unbind result=0\r\n' >> "$d/adv-um.log"
	out="$(wqadv "$d/adv-um.log" $(( now - 645 - 1300 )) yes 700)"
	check "advice J4 after the deadline: a marker with no printk time as the last line is F25w (D25_F25W_CUT=no: no cut)" "$(has "$out" 'NO CUT (F25w): D25_F25W_CUT is not yes')/$(has "$out" 'CUT ALLOWED')" "yes/no"

	# wait_wq: ssh only while COM3 shows no marker of the sequence (and after the fallback deadline)
	for g in markers none; do
		out="$(
			REC=""; S1_POLL_S=0; S1_COM3_LOG="$d/ww-$g.log"; rm -f "$d/ww-ssh"
			if [ "$g" = markers ]; then cp "$cap4" "$S1_COM3_LOG"; else head -c "$off4" "$cap4" > "$S1_COM3_LOG"; fi
			read_boot_id() { echo x >> "$d/ww-ssh"; echo 00000000-0000-4000-8000-000000000001; }
			sleep() { printf '[ 1300.000000] kexec_core: Starting new kernel\r\n' >> "$S1_COM3_LOG"; }
			rec() { :; }
			wait_wq 00000000-0000-4000-8000-000000000001 "$off4" "$(( $(date +%s) - 10 ))"
			echo "end=$WQ_END ssh=$(cat "$d/ww-ssh" 2>/dev/null | wc -l)"
		)"
		case "$g" in
		markers) check "wait_wq: markers on COM3 before the fallback deadline: no ssh poll (every arm)" "$out" "end=JUMPED ssh=0" ;;
		none)    check "wait_wq: no marker yet: ssh polls for the ARMED stop" "$out" "end=JUMPED ssh=1" ;;
		esac
	done
	wqadv "$cap4" $(( now - 400 )) no 400 >/dev/null
	out="$(S1_COM3_LOG="$cap4" cmd_wq_status "$bl" 2>&1)"
	check "wq-status prints the state and the advice hold" "$(has "$out" 'wq state=')/$(has "$out" 'advice_hold_until=')" "yes/yes"

	# gate A with J1 text, and gate B (§15.5 A1): the capture must still be this rung's alone
	RETURN_BOUND=1200
	cb="$jrec/jb-cap.log"
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=99999 ---\n' "$now" > "$cb"
	printf 'MB1 version synthetic\r\n' >> "$cb"
	cp "$cb" "$jrec/jb-j1.log"; printf '[   10.000000] s1wq: j1 timer result=0\r\n' >> "$jrec/jb-j1.log"
	check "gate A: a capture holding J1 text is refused" "$(has "$(S1_COM3_LOG="$jrec/jb-j1.log" j_capture_gate control 9)" 's1wq: markers or an earlier')" yes
	mark_capture "$cb"
	check "gate B: a capture this rung marked once passes" "$(has "$(S1_COM3_LOG="$cb" j_gate_b control)" 'jgateB control ok')" yes
	mark_capture "$cb"
	check "gate B: a capture name used twice is refused" "$(has "$(S1_COM3_LOG="$cb" j_gate_b control)" 'times, not once')" yes
	mark_capture "$jrec/jb-j1.log"
	check "gate B: a capture holding s1wq: markers is refused" "$(has "$(S1_COM3_LOG="$jrec/jb-j1.log" j_gate_b j3)" 'holds s1wq: markers')" yes
	cp "$cb" "$d/jb-out.log"
	check "gate B: a capture outside the record directory is refused" "$(has "$(S1_COM3_LOG="$d/jb-out.log" j_gate_b control)" 'not inside')" yes
	check "gate B: a missing SSID is refused" "$(has "$(S1_COM3_LOG="$cb" S1_REDACT_SSID='' j_gate_b control)" 'S1_REDACT_SSID')" yes

	# jrun refusals, Q17, the J step after resolve_kimg (no B* directory) and the start margin
	out="$(bash "$0" jrun s1-n1 control 2>&1)"; rcx=$?
	check "jrun refuses another image" "$rcx/$(has "$out" 'accepts s1-h1 and s1-j1 only')" "1/yes"
	# ORIN_HOST is emptied, so an accepted jrun s1-j1 stops at need_host before any board session
	out="$(ORIN_HOST= bash "$0" jrun s1-j1 b2repeat 2>&1)"; rcx=$?
	check "jrun s1-j1 refuses b2repeat (J6 is control or remove, §15.4.8)" "$rcx/$(has "$out" 'control or remove arm only')" "1/yes"
	for arm in control remove; do
		out="$(ORIN_HOST= bash "$0" jrun s1-j1 "$arm" 2>&1)"; rcx=$?
		check "jrun s1-j1 $arm passes the argument check (stops at ORIN_HOST here)" \
			"$rcx/$(has "$out" 'ORIN_HOST is not set')/$(has "$out" 'accepts s1-h1')/$(has "$out" 'waits for the watcher image')" "1/yes/no/no"
	done
	out="$(ORIN_HOST= bash "$0" run s1-j1 2>&1)"; rcx=$?
	check "run refuses s1-j1: the watcher runs only through jrun (§15.4.8)" "$rcx/$(has "$out" 'run refuses s1-j1')" "1/yes"
	check "image table: s1-j1 is J6 host (jrun sets J6c|J6r after it)" "$(image_step s1-j1; echo "$STEP $MODE")" "J6 host"
	out="$(bash "$0" jrun s1-h1 bogus 2>&1)"; rcx=$?
	check "jrun refuses another arm" "$rcx/$(has "$out" "arm is control, remove or b2repeat")" "1/yes"
	bash "$0" jrun s1-h1 >/dev/null 2>&1
	check "jrun without an arm is a usage error" "$?" 2
	kd2="$d/kimg"; mkdir -p "$kd2"
	printf 'synthetic kimg\n' > "$kd2/s1-h1.kimg"
	printf 'kimg_sha256=-\nreturn_bound_s=1200\ncapture_s=4000\nmode=host\nrung=s1-h1\n' > "$kd2/s1-h1.params"
	( S1_KIMG_DIR="$kd2"; j_q17_check s1-h1 ) >/dev/null 2>&1
	check "Q17: kimg_sha256=- is refused" "$?" 1
	sed -i "s/^kimg_sha256=.*/kimg_sha256=$(printf '%064d' 0)/" "$kd2/s1-h1.params"
	( S1_KIMG_DIR="$kd2"; j_q17_check s1-h1 ) >/dev/null 2>&1
	check "Q17: a hash that is not the kimg's is refused" "$?" 1
	sed -i "s/^kimg_sha256=.*/kimg_sha256=$(sha256sum "$kd2/s1-h1.kimg" | cut -d' ' -f1)/" "$kd2/s1-h1.params"
	( S1_KIMG_DIR="$kd2"; j_q17_check s1-h1 ) >/dev/null 2>&1
	check "Q17: the kimg's own hash passes" "$?" 0
	jr2="$d/jrec2"; mkdir -p "$jr2"; jr2a="$(cd "$jr2" && pwd)"
	out="$(
		RECDIR="$jr2a"; S1_KIMG_DIR="$kd2"
		for arm in control remove b2repeat; do
			resolve_kimg s1-h1
			printf '%s>' "$STEP"
			jrun_step "$arm"
			j_step_dir "$STEP"
			printf '%s/%s ' "$STEP" "$(basename "$JSD")"
		done
	)"
	check "jrun: resolve_kimg gives B2, the J step is set after it: J2, J4, J2b" "$out" "B2>J2/J2 B2>J4/J4 B2>J2b/J2b "
	check "jrun: no B* directory was created" "$(ls -1 "$jr2" | grep -c '^B')" 0
	check "start margin: the worst cases of control, remove and j3" "$(j_worst_case control)/$(j_worst_case remove)/$(j_worst_case j3)" "1645/1645/1585"
	( start_margin_gate 200 "$(j_worst_case control)" "jrun J2" ) >/dev/null 2>&1
	check "start margin: 200 s of uptime + J2's worst case is refused" "$?" 1
	( start_margin_gate 100 "$(j_worst_case control)" "jrun J2" ) >/dev/null 2>&1
	check "start margin: 100 s of uptime + J2's worst case starts" "$?" 0

	# the ladder's preconditions, the set per arm, the pre-registration's set check
	wqpre() { ( RECDIR="$jr2a"; j_precondition "$1" ) >/dev/null 2>&1; echo $?; }
	check "precondition: J2 without J1 met is refused" "$(wqpre control)" 1
	mkdir -p "$jr2/J1"; printf 'j1 next=J2 trace=go\n' > "$jr2/J1/j1-20260914T000000Z-board.log"
	check "precondition: J2 after J1 met" "$(wqpre control)" 0
	check "precondition: J3 without J2's F32 is refused" "$(wqpre j3)" 1
	printf 'run image=s1-h1\n' > "$jr2/J2/s1-h1-20260914T010000Z-board.log"; printf 'S1PC j_row=F32\n' > "$jr2/J2/parse-s1.txt"
	check "precondition: J3 after J2's F32" "$(wqpre j3)" 0
	printf 'S1PC j_row=F39\nS1PC c1_start=ok\nS1PC c1_end=ok\nS1PC c2_start=bad\nS1PC c2_end=bad\n' > "$jr2/J2/parse-s1.txt"
	check "precondition: J3 after J2's F39 without D34's waiver is refused" "$(wqpre j3)" 1
	printf 'D34_F39=yes\n' > "$jr2/J-waivers.conf"
	check "precondition: J3 after J2's F39 under D34, c2 bad twice and c1 ok" "$(wqpre j3)" 0
	printf 'S1PC j_row=F39\nS1PC c1_start=bad\nS1PC c1_end=ok\nS1PC c2_start=bad\nS1PC c2_end=bad\n' > "$jr2/J2/parse-s1.txt"
	check "precondition: D34 does not cover an F39 whose c1 was bad" "$(wqpre j3)" 1
	rm -f "$jr2/J-waivers.conf"
	printf 'S1PC j_row=F32\n' > "$jr2/J2/parse-s1.txt"
	sb="$(printf '\357\277\275\357\277\275[   89.230298] s1wq: begin arm=control final=kexec result=0')"
	check "j_wq_lines: a marker after stray bytes on its line is kept" "$(printf '%s\n' "$sb" | j_wq_lines)" "s1wq: begin arm=control final=kexec result=0"
	printf '%s\n' "$sb" > "$jr2/stray-marker.log"
	com3_marker_seen "$jr2/stray-marker.log" 0 "s1wq: begin arm=control final=kexec result=0"
	check "com3_marker_seen: a marker after stray bytes is seen" "$?" 0
	check "j_wq_lines: a marker quoted mid-line is still not a marker" "$(printf 'systemd[1]: echo s1wq: begin arm=x\n' | j_wq_lines | wc -l)" 0
	check "jrun's locals start empty, so an s1-j1 run survives set -u before its deferred prereg (J6c)" "$(grep -c '^[[:space:]]*local arm="\$1" img="\$2" kw=jrun .* pre_ok="" ' "$HERE/$PROG")" 1
	check "j3's return read passes XHCI_PATH to b_pci_state (the F41-xhci gate defect)" "$(grep -c '^[[:space:]]*out="$(board 120 b_identity b_pstore b_slots "XHCI_PATH=' "$HERE/$PROG")" 1
	check "precondition: J2b after F32 is refused" "$(wqpre b2repeat)" 1
	check "precondition: J4 without J3 met is refused" "$(wqpre remove)" 1
	mkdir -p "$jr2/J3"; printf 'j3 RESULT MET wireless-only: synthetic\n' > "$jr2/J3/j3-20260914T020000Z-board.log"
	check "precondition: J4 after J3 met" "$(wqpre remove)" 0
	printf 'S1PC j_row=F33\n' > "$jr2/J2/parse-s1.txt"
	check "precondition: J2b after J2's F33" "$(wqpre b2repeat)" 0
	printf '%s\n' "$cen" | j_set_rules > "$jr2/J-set.conf"
	printf 'D20=yes\nD21=no\nD22=yes\nD23=no\nD24=yes\nD24_SET=max\nD25=yes\nD25_F25W_CUT=no\n' > "$jr2/J-decisions.conf"
	wqsel() { ( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_set_select "$1"; local -a q=($J_REQ); printf '%s %s%s%s%s req=%s' "$J_SETDESC" "$WQG_W_IN" "$WQG_X_IN" "$WQG_E_IN" "$WQG_N_IN" "${#q[@]}" ) 2>&1; }
	check "set control: empty, every member read only" "$(wqsel control)" "empty nononono req=0"
	check "set remove, D24_SET=max: all four, endpoints and single-child ports required" "$(wqsel remove)" "wireless,xhci,ethernet,nvme yesyesyesyes req=6"
	sed -i 's/^D24_SET=max$/D24_SET=wireless/' "$jr2/J-decisions.conf"
	check "set remove, D24_SET=wireless" "$(wqsel remove)" "wireless yesnonono req=2"
	sed -i 's/^D24_SET=wireless$/D24_SET=max/' "$jr2/J-decisions.conf"
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; S1_J_RULE_FILE=""; j_prereg_write "" "" j2 no 2>&1 )"
	check "prereg write: the J2 pre-registration without a rule file is refused" "$(has "$out" 'S1_J_RULE_FILE must name a copy')" yes
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_prereg_write "" "" j2 no; cat "$jr2a/J-prereg.log" )"
	check "prereg: the J2 stage and the trace are registered" "$(has "$out" 'prereg stage=j2')/$(has "$out" 'prereg trace=no')" "yes/yes"
	check "prereg: the fixed slot list by default, and the removal set" "$(has "$out" "prereg slot_list=${WQ_SLOT_LIST// /,}")/$(has "$out" 'prereg removal_set=max members_in_set=wireless,xhci,ethernet,nvme')" "yes/yes"
	printf 'j3 fallback=wireless utc=20260914T020000Z reason=synthetic\n' >> "$jr2/J-set.conf"
	check "set remove after J3's wireless-only line" "$(wqsel remove)" "wireless yesnonono req=2"
	check "set j3 keeps the max set" "$(wqsel j3)" "wireless,xhci,ethernet,nvme yesyesyesyes req=6"
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_prereg_check 2>&1 )"
	check "prereg check: J3's fallback line changes no member (no set refusal)" "$(has "$out" 'removal set changed')" no
	sed -i 's/driver=fakeeth /driver=fakeother /' "$jr2/J-set.conf"
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_prereg_check 2>&1 )"
	check "prereg check: a changed member line is refused" "$(has "$out" 'the removal set changed')" yes
	sed -i 's/driver=fakeother /driver=fakeeth /' "$jr2/J-set.conf"
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; S1_J_RULE_FILE=""; j_prereg_check 2>&1 )"
	check "prereg check: no rule file at a later rung is refused" "$(has "$out" 'S1_J_RULE_FILE must name the copy')" yes
	printf 'changed rule text\n' > "$d/rule2.txt"
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; S1_J_RULE_FILE="$d/rule2.txt"; j_prereg_check 2>&1 )"
	check "prereg check: a changed rule text is refused" "$(has "$out" 'the rule is fixed before any result')" yes
	cp "$jr2/J-decisions.conf" "$d/dec.bak"; printf 'D23=yes\n' >> "$jr2/J-decisions.conf"
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_prereg_check 2>&1 )"
	check "prereg check: a changed decisions file is refused" "$(has "$out" 'recorded decisions as sha256=')" yes
	cp "$d/dec.bak" "$jr2/J-decisions.conf"
	sed -i 's/^prereg stage=j2$/prereg stage=j1/' "$jr2/J-prereg.log"
	out="$( RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_prereg_check 2>&1 )"
	check "prereg check: J1's draft is not the J2 pre-registration" "$(has "$out" 'is J1')" yes
	sed -i 's/^prereg stage=j1$/prereg stage=j2/' "$jr2/J-prereg.log"

	# ---- J6 (§15.4.8, §15.5 A1's jrun s1-j1): its own record directory, a copy of the J2
	# pre-registration above, a synthetic s1-j1 kimg and params, and a synthetic generator whose
	# three constant lines stand for make-s1-images.sh's. The tree is stubbed clean in each case.
	local jr6 jr6a kd6 gen6 h6 pin6 k6 cap6
	jr6="$d/jrec6"; mkdir -p "$jr6"; jr6a="$(cd "$jr6" && pwd)"
	cp "$jr2/J-prereg.log" "$jr2/J-set.conf" "$jr2/J-decisions.conf" "$jr6/"
	kd6="$d/kimg6"; mkdir -p "$kd6"
	h6="$(j6_parser_hold)"
	check "j6: parse-s1.py's J1_HOLD_MIB reads as a whole number" "$(printf '%s\n' "$h6" | grep -cE '^[1-9][0-9]*$')" 1
	pin6="$(printf 'synthetic memcanary-w' | sha256sum | cut -d' ' -f1)"
	gen6="$d/gen6.sh"
	printf 'PIN_MEMCANARY_W=%s\nJ1_HOLD_MIB=%s\nJ1_HOLD_MARGIN_MIB=256\n' "$pin6" "$h6" > "$gen6"
	printf 'synthetic s1-j1 kimg\n' > "$kd6/s1-j1.kimg"
	k6="$(sha256sum "$kd6/s1-j1.kimg" | cut -d' ' -f1)"
	printf 'image=s1-j1\nrung=s1-j1\nmode=host\ndiag=j1\nguard_s=1800\nreturn_bound_s=2100\ncapture_s=5100\nkimg_sha256=%s\nmemcanary_w_sha256=%s\nj1_hold_mib=%s\nj1_hold_t=600\nbb_worst_b=1\n' \
		"$k6" "$pin6" "$h6" > "$kd6/s1-j1.params"
	# WQ_FUNCS at the registered commit is stubbed to this harness's, so the checks do not depend on git
	j6s() { ( RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"; J6_GENERATOR="$gen6"; j_tree_clean() { return 0; }; j6_wq_sha_at() { j6_wq_sha; }; J_DEC_LOADED=0; j_read_decisions; "$@" ) 2>&1; }

	# the step table and the record directory: J6c and J6r, never a B* directory
	out="$(
		RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"
		for arm in control remove; do
			resolve_kimg s1-j1
			printf '%s>' "$STEP"
			jrun_step "$arm" s1-j1
			j_step_dir "$STEP"
			printf '%s/%s/%s ' "$STEP" "$MODE" "$(basename "$JSD")"
		done
	)"
	check "jrun s1-j1: resolve_kimg gives J6, the J step is set after it: J6c, J6r" "$out" "J6>J6c/host/J6c J6>J6r/host/J6r "
	check "jrun s1-j1: no B* directory was created" "$(ls -1 "$jr6" | grep -c '^B')" 0
	rmdir "$jr6/J6c" "$jr6/J6r"
	( jrun_step b2repeat s1-j1 ) >/dev/null 2>&1
	check "jrun_step: no J6 step for b2repeat" "$?" 1

	# J6's arm (§15.4.8 'Run'), and the membership test on J6's comma-list rows
	check "j_row_has: a member of a comma list" "$(j_row_has 'F49,writer-static' F49 && echo yes || echo no)" yes
	check "j_row_has: a single token is a list of one" "$(j_row_has F36 F36 && echo yes || echo no)" yes
	check "j_row_has: F490 is not F49, F4 is not F49" "$(j_row_has 'F490,writer-none' F49 && echo yes || echo no)/$(j_row_has 'F4' F49 && echo yes || echo no)" "no/no"
	# T-J1's record (§15.4.8 preconditions): a synthetic TCG attempt with the synthetic pin, CRLF as on the PC
	mkdir -p "$d/tcg6/attempt1"
	printf 'S1PC memcanary_w_sha256=%s\r\nS1PC step=T-J1\r\nS1PC verdict=diagnostic complete\r\n' "$pin6" > "$d/tcg6/attempt1/parse-s1.txt"
	j6pre() { ( RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"; J6_TCG_RECORDS="$d/tcg6"; j_precondition "$1" ) >/dev/null 2>&1; echo $?; }
	j6pre_out() { ( RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"; J6_TCG_RECORDS="$d/tcg6"; j_precondition "$1" ) 2>&1; }
	mkdir -p "$jr6/J4"; printf 'run image=s1-h1\n' > "$jr6/J4/s1-h1-20260914T010000Z-board.log"; printf 'S1PC j_row=F36\n' > "$jr6/J4/parse-s1.txt"
	check "j6 precondition: J6c after J4's F36 without D27 is refused" "$(j6pre j6control)" 1
	check "j6 precondition: the refusal names D27" "$(has "$(j6pre_out j6control)" "'D27=yes'")" yes
	printf 'D34_F39=yes\nD27=yes\n' > "$jr6/J-waivers.conf"
	check "j6 precondition: J6c after J4's F36 under D27" "$(j6pre j6control)" 0
	out="$(j6pre_out j6control)"
	check "j6 precondition: the reason, T-J1's attempt and the kexec runs so far are printed" \
		"$(has "$out" "j6 precondition: J4's row is F36")/$(has "$out" 't_j1 met attempt1')/$(has "$out" 'kexec_runs_before=0 ')" "yes/yes/yes"
	mv "$d/tcg6/attempt1/parse-s1.txt" "$d/tcg6/attempt1/parse-s1.bak"
	check "j6 precondition: no T-J1 record is refused" "$(has "$(j6pre_out j6control)" 'T-J1 has not met')" yes
	sed "s/^S1PC memcanary_w_sha256=.*/S1PC memcanary_w_sha256=$(printf '%064d' 7)\r/" "$d/tcg6/attempt1/parse-s1.bak" > "$d/tcg6/attempt1/parse-s1.txt"
	check "j6 precondition: a T-J1 record of another memcanary-w is refused" "$(j6pre j6control)" 1
	sed 's/^S1PC verdict=.*/S1PC verdict=diagnostic incomplete failed=cw_selftest\r/' "$d/tcg6/attempt1/parse-s1.bak" > "$d/tcg6/attempt1/parse-s1.txt"
	check "j6 precondition: an incomplete T-J1 is refused" "$(j6pre j6control)" 1
	mv "$d/tcg6/attempt1/parse-s1.bak" "$d/tcg6/attempt1/parse-s1.txt"
	mkdir -p "$jr6/J2"; printf 'run image=s1-h1\n' > "$jr6/J2/s1-h1-20260914T000000Z-board.log"; printf 'S1PC j_row=F39\n' > "$jr6/J2/parse-s1.txt"
	check "j6 precondition: after J2's F39, D34_F39 alone does not cover J6 (D34 is J3 and J4 only)" "$(has "$(j6pre_out j6control)" "'D34_J6=yes'")" yes
	printf 'D34_F39=yes\nD27=yes\nD34_J6=yes\n' > "$jr6/J-waivers.conf"
	check "j6 precondition: after J2's F39 under the owner's D34_J6, named in the reason" \
		"$(has "$(j6pre_out j6control)" "extended to J6 by the owner's D34_J6")" yes
	printf 'run com3_bytes_before_kexec=100\n' >> "$jr6/J2/s1-h1-20260914T000000Z-board.log"
	check "j6 precondition: the kexec runs so far count J2's issued kexec" "$(has "$(j6pre_out j6control)" 'kexec_runs_before=1 ')" yes
	rm -rf "$jr6/J2"
	printf 'D34_F39=yes\nD27=yes\n' > "$jr6/J-waivers.conf"
	check "j6 precondition: J6r after J4's F36 is refused" "$(j6pre j6remove)" 1
	printf 'S1PC j_row=F35\n' > "$jr6/J4/parse-s1.txt"
	check "j6 precondition: J6r after J4's F35" "$(j6pre j6remove)" 0
	check "j6 precondition: J6c after J4's F35 alone is refused" "$(j6pre j6control)" 1
	mkdir -p "$jr6/J2"; printf 'run image=s1-h1\n' > "$jr6/J2/s1-h1-20260914T000000Z-board.log"; printf 'S1PC j_row=F32b\n' > "$jr6/J2/parse-s1.txt"
	check "j6 precondition: J6c after J2's F32b" "$(j6pre j6control)" 0
	printf 'S1PC j_row=F33\n' > "$jr6/J2/parse-s1.txt"
	mkdir -p "$jr6/J2b"; printf 'run image=s1-h1\n' > "$jr6/J2b/s1-h1-20260914T005000Z-board.log"; printf 'S1PC j_row=F46\n' > "$jr6/J2b/parse-s1.txt"
	check "j6 precondition: J6c after J2b's F46" "$(j6pre j6control)" 0
	rm -rf "$jr6/J2" "$jr6/J2b"
	printf 'S1PC j_row=F36\n' > "$jr6/J4/parse-s1.txt"
	printf 'D27=yes\nD27_J6R=yes\n' > "$jr6/J-waivers.conf"
	check "j6 precondition: J6r after F36 by the owner's D27_J6R (the other arm)" "$(j6pre j6remove)" 0
	mkdir -p "$jr6/J6c"; printf 'run image=s1-j1\n' > "$jr6/J6c/s1-j1-20260914T060000Z-board.log"; printf 'S1PC j_row=F49,writer-static\n' > "$jr6/J6c/parse-s1.txt"
	check "j6 precondition: a J6c row holding F49 stops every J6 run" "$(j6pre j6remove)/$(j6pre j6control)" "1/1"
	printf 'S1PC j_row=F40,writer-none\n' > "$jr6/J6c/parse-s1.txt"
	check "j6 precondition: a J6c row without F39 or F49 does not stop J6" "$(j6pre j6remove)" 0
	rm -rf "$jr6/J6c"
	printf 'D27=yes\n' > "$jr6/J-waivers.conf"

	# J6's pre-registration stage (§15.4.1): appended once per arm, checked against the image
	out="$(j6s j6_prereg_append control)"
	check "j6 prereg: no S1_J6_FILL_FACTOR is refused" "$(has "$out" 'S1_J6_FILL_FACTOR is unset')" yes
	for g in 0.5 2x; do
		out="$(S1_J6_FILL_FACTOR="$g" j6s j6_prereg_append control)"
		check "j6 prereg: factor '$g' is refused" "$(has "$out" 'not a decimal of 1 or above')" yes
	done
	printf 'PIN_MEMCANARY_W=UNSET-integrate-sets-the-memcanary-w-sha256\nJ1_HOLD_MIB=%s\nJ1_HOLD_MARGIN_MIB=256\n' "$h6" > "$d/gen6-unset.sh"
	out="$(S1_J6_FILL_FACTOR=2 J6_GENERATOR="$d/gen6-unset.sh" j6s eval 'J6_GENERATOR="$d/gen6-unset.sh"; j6_prereg_append control')"
	check "j6 prereg: an unset PIN_MEMCANARY_W in the generator is refused" "$(has "$out" "make-s1-images.sh's PIN_MEMCANARY_W is 'UNSET")" yes
	check "j6 prereg: nothing was appended by a refusal" "$(grep -c '^prereg stage=j6$' "$jr6/J-prereg.log")" 0
	n=$(wc -l < "$jr6/J-prereg.log")
	out="$(S1_J6_FILL_FACTOR=2 j6s j6_prereg_append control)"
	k="$(cat "$jr6/J-prereg.log")"
	check "j6 prereg: the stage is appended after J2's (J2's lines kept, stage j6 last)" \
		"$(head -n "$n" "$jr6/J-prereg.log" | cmp -s - "$jr2/J-prereg.log" && echo kept)/$(RECDIR="$jr6a" j_prereg_stage)/$(RECDIR="$jr6a"; j_prereg_has_stage j2 && echo j2)" "kept/j6/j2"
	check "j6 prereg: the arm, the factor, the pin, the hold and its margin" \
		"$(has "$k" 'prereg j6 arm=control')/$(has "$k" 'prereg j6 fill_rate_factor=2')/$(has "$k" "prereg j6 pin_memcanary_w=$pin6")/$(has "$k" "prereg j6 hold_mib=$h6 hold_margin_mib=256 hold_t_s=600 guard_s=1800")" "yes/yes/yes/yes"
	check "j6 prereg: parse-s1.py's hash, and the params and kimg hashes" \
		"$(has "$k" "prereg j6 parse-s1.py sha256=$(j_sha256 "$PARSER")")/$(has "$k" "kimg_sha256=$k6")" "yes/yes"
	check "j6 prereg: the complete-stage line is the last" "$(tail -n 1 "$jr6/J-prereg.log")" "prereg j6 arm=control"
	n=$(wc -l < "$jr6/J-prereg.log")
	S1_J6_FILL_FACTOR=9 j6s j6_prereg_append control >/dev/null
	check "j6 prereg: a second attempt of the arm appends nothing (never rewritten)" "$(wc -l < "$jr6/J-prereg.log")" "$n"
	out="$(j6s j_prereg_check s1-j1 control)"
	check "j6 prereg check: s1-j1 control passes with its stage" "$(has "$out" 'prereg ok sha256=')/$(has "$out" 'j6_arm=control fill_rate_factor=2')" "yes/yes"
	out="$(j6s j_prereg_check)"
	check "j6 prereg check: the s1-h1 checks still pass after J6's stage" "$(has "$out" 'prereg ok sha256=')/$(has "$out" 'j6_arm=')" "yes/no"
	out="$(j6s j_prereg_check s1-j1 remove)"
	check "j6 prereg check: the remove arm without its stage is refused" "$(has "$out" 'no J6 stage for the remove arm')" yes
	out="$(S1_J6_FILL_FACTOR=3 j6s j6_prereg_append remove)"
	check "j6 prereg: the other arm with another factor is refused" "$(has "$out" 'differs from the fill-rate factor 2')" yes
	out="$(S1_J6_FILL_FACTOR=5 j6s j_prereg_check s1-j1 control)"
	check "j6 prereg check: S1_J6_FILL_FACTOR other than the registered one is refused" "$(has "$out" 'differs from the registered fill-rate factor 2')" yes
	j6s j6_prereg_append remove >/dev/null
	out="$(j6s j_prereg_check s1-j1 remove)"
	check "j6 prereg: the other arm's stage takes the registered factor" "$(has "$out" 'j6_arm=remove fill_rate_factor=2')" yes
	cp "$jr6/J-prereg.log" "$d/prereg6.bak"
	sed -i "s/^prereg j6 parse-s1.py sha256=.*/prereg j6 parse-s1.py sha256=$(printf '%064d' 0)/" "$jr6/J-prereg.log"
	check "j6 prereg check: another parse-s1.py than the registered one is refused" "$(has "$(j6s j_prereg_check s1-j1 control)" "J6's rows are that code")" yes
	cp "$d/prereg6.bak" "$jr6/J-prereg.log"
	printf 'rebuilt\n' >> "$kd6/s1-j1.kimg"
	check "j6 prereg check: a kimg changed after the stage is refused" "$(has "$(j6s j_prereg_check s1-j1 control)" 'the image changed after its pre-registration')" yes
	printf 'synthetic s1-j1 kimg\n' > "$kd6/s1-j1.kimg"
	sed -i "s/^memcanary_w_sha256=.*/memcanary_w_sha256=$(printf '%064d' 1)/" "$kd6/s1-j1.params"
	check "j6 prereg check: a params pin other than the generator's is refused" "$(has "$(j6s j_prereg_check s1-j1 control)" "not s1-j1.params'")" yes
	sed -i "s/^memcanary_w_sha256=.*/memcanary_w_sha256=$pin6/" "$kd6/s1-j1.params"
	sed -i "s/^j1_hold_mib=.*/j1_hold_mib=$(( h6 - 1 ))/" "$kd6/s1-j1.params"
	check "j6 params: a hold size other than the generator's is refused" "$(has "$(j6s j_prereg_check s1-j1 control)" "J1_HOLD_MIB is '$h6', not s1-j1.params'")" yes
	sed -i "s/^j1_hold_mib=.*/j1_hold_mib=$h6/" "$kd6/s1-j1.params"
	sed -i 's/^guard_s=.*/guard_s=3900/' "$kd6/s1-j1.params"
	check "j6 params: a guard over 3,600 s is refused" "$(has "$(j6s j_prereg_check s1-j1 control)" "not the generator's shape")" yes
	sed -i 's/^guard_s=.*/guard_s=1900/' "$kd6/s1-j1.params"
	check "j6 params: a return bound under the guard + 300 s is refused" "$(has "$(j6s j_prereg_check s1-j1 control)" "not the generator's shape")" yes
	sed -i 's/^guard_s=.*/guard_s=1800/; s/^diag=.*/diag=-/' "$kd6/s1-j1.params"
	check "j6 params: another image's params (diag) are refused" "$(has "$(j6s j_prereg_check s1-j1 control)" "not the watcher's")" yes
	sed -i 's/^diag=.*/diag=j1/' "$kd6/s1-j1.params"
	check "j6 prereg check: the restored image passes again" "$(has "$(j6s j_prereg_check s1-j1 control)" 'prereg ok sha256=')" yes
	{ printf 'prereg stage=j6\nprereg j6 arm=control\n'; cat "$d/prereg6.bak"; } > "$jr6/J-prereg.log"
	check "j6 prereg check: a J6 stage before J2's is refused" "$(has "$(j6s j_prereg_check s1-j1 control)" 'before the J2 pre-registration')" yes
	cp "$d/prereg6.bak" "$jr6/J-prereg.log"
	check "no J2 pre-registration is written over a later stage (the stage-line test, not the last stage)" \
		"$(grep -cE '^[[:space:]]*if .*j_prereg_stage\)" != j2' "$HERE/$PROG")" 0

	# J6's stages never re-anchor J2's harness lines; an amendment is the owner's; each arm reads its own stage
	check "j6 prereg: J2's harness lines are not re-emitted by J6's stages" \
		"$(grep -c '^prereg s1-board.sh sha256=' "$jr6/J-prereg.log")/$(grep -c '^prereg parse-s1.py sha256=' "$jr6/J-prereg.log")" \
		"$(grep -c '^prereg s1-board.sh sha256=' "$jr2/J-prereg.log")/$(grep -c '^prereg parse-s1.py sha256=' "$jr2/J-prereg.log")"
	awk -v z="$(printf '%064d' 0)" '/^prereg j6 pin_memcanary_w=/ && ++n == 2 { $0 = "prereg j6 pin_memcanary_w=" z } { print }' \
		"$d/prereg6.bak" > "$jr6/J-prereg.log"
	check "j6 prereg check: the control arm reads its own stage, not the remove stage after it" \
		"$(has "$(j6s j_prereg_check s1-j1 control)" 'prereg ok sha256=')/$(has "$(j6s j_prereg_check s1-j1 remove)" "registered PIN_MEMCANARY_W=$(printf '%064d' 0)")" "yes/yes"
	cp "$jr2/J-prereg.log" "$jr6/J-prereg.log"
	sed -i "s/^prereg parse-s1.py sha256=.*/prereg parse-s1.py sha256=$(printf '%064d' 0)/" "$jr6/J-prereg.log"
	n=$(wc -l < "$jr6/J-prereg.log")
	out="$(S1_J6_FILL_FACTOR=2 j6s j6_prereg_append control)"
	check "j6 prereg: a harness that differs from J2's registration needs the owner's S1_J6_AMEND_BY" \
		"$(has "$out" 'is an amendment')/$(wc -l < "$jr6/J-prereg.log")" "yes/$n"
	check "j6 prereg: S1_J6_AMEND_BY must name an owner decision" \
		"$(has "$(S1_J6_FILL_FACTOR=2 S1_J6_AMEND_BY=me j6s j6_prereg_append control)" 'S1_J6_AMEND_BY=owner-')" yes
	S1_J6_FILL_FACTOR=2 S1_J6_AMEND_BY=owner-D27 j6s j6_prereg_append control >/dev/null
	k="$(cat "$jr6/J-prereg.log")"
	check "j6 prereg: the amendment line names the owner, the commit, parse-s1.py's old and new hashes, and WQ_FUNCS" \
		"$(has "$k" 'prereg amendment utc=')/$(has "$k" 'by=owner-D27 commit=')/$(has "$k" "parse-s1.py sha256 $(printf '%064d' 0) -> $(j_sha256 "$PARSER")")/$(has "$k" 'wq_funcs unchanged since')" \
		"yes/yes/yes/yes"
	check "j6 prereg check: the s1-j1 arm passes on its own stage while J2's parse-s1.py line differs" \
		"$(has "$(j6s j_prereg_check s1-j1 control)" 'prereg ok sha256=')" yes
	check "j6 prereg check: the s1-h1 checks still read J2's line, and refuse" \
		"$(has "$(j6s j_prereg_check)" 'J-prereg.log recorded parse-s1.py')" yes
	printf 'rebuilt\n' >> "$kd6/s1-j1.kimg"
	n=$(wc -l < "$jr6/J-prereg.log")
	out="$(j6s j6_prereg_append control)"
	check "j6 prereg: a stage that no longer matches the image is superseded only by the owner" \
		"$(has "$out" 'it supersedes the stage of')/$(wc -l < "$jr6/J-prereg.log")" "yes/$n"
	S1_J6_AMEND_BY=owner-D27 j6s j6_prereg_append control >/dev/null
	check "j6 prereg: the superseding stage is the one the arm is checked against" \
		"$(has "$(j6s j_prereg_check s1-j1 control)" 'prereg ok sha256=')/$(grep -c '^prereg j6 arm=control$' "$jr6/J-prereg.log")" "yes/2"
	mkdir -p "$jr6/J6c"; printf 'run image=s1-j1\n' > "$jr6/J6c/s1-j1-20260914T070000Z-board.log"
	printf 'rebuilt again\n' >> "$kd6/s1-j1.kimg"
	check "j6 prereg: no stage is superseded once the arm has a board log" \
		"$(has "$(S1_J6_AMEND_BY=owner-D27 j6s j6_prereg_append control)" 'board log exists')" yes
	check "j6 prereg: this attempt's own board log (REC, opened before gate A) does not block the supersede" \
		"$(REC="$jr6a/J6c/s1-j1-20260914T070000Z-board.log" S1_J6_AMEND_BY=owner-D27 j6s j6_prereg_append control >/dev/null; grep -c '^prereg j6 arm=control$' "$jr6/J-prereg.log")" 3
	rm -rf "$jr6/J6c"
	printf 'synthetic s1-j1 kimg\n' > "$kd6/s1-j1.kimg"
	out="$(S1_J6_AMEND_BY=owner-D27 j6s eval 'j6_wq_sha_at() { echo 00; }; j6_prereg_append remove')"
	check "j6 prereg: WQ_FUNCS other than the registered commit's is refused without S1_J6_WQ_CHANGED" \
		"$(has "$out" 'WQ_FUNCS, the detached sequence J2 and J4 ran, differs')" yes
	S1_J6_WQ_CHANGED=yes S1_J6_AMEND_BY=owner-D27 j6s eval 'j6_wq_sha_at() { echo 00; }; j6_prereg_append remove' >/dev/null
	check "j6 prereg: a WQ_FUNCS change the owner names is in the amendment line" \
		"$(grep -c 'wq_funcs changed, named by the owner; .*wq_funcs sha256 00 -> ' "$jr6/J-prereg.log")" 1
	check "j6 wq: the WQ_FUNCS text holds every function's definition once" \
		"$(j6_wq_text "$HERE/$PROG" | grep -cE '^[A-Za-z0-9_]+\(\) \{')" "$(set -- $WQ_FUNCS; echo $#)"
	check "j6 wq: WQ_FUNCS at a commit is a sha256, or '-' when git cannot show it" \
		"$(j6_wq_sha_at HEAD | grep -cE '^([0-9a-f]{64}|-)$')/$(j6_wq_sha_at '')" "1/-"
	check "jrun: J6's stage is appended after gate A and before the board is first read" \
		"$(awk '/gate="\$\(j_capture_gate "\$arm"/ && !g { g = NR } /^\t\tj6_prereg_append "\$arm"$/ && !a { a = NR } a && !b && /out="\$\(board 300 b_sha b_pstore/ { b = NR } END { print (g && a > g && b > a) ? "ordered" : "not" }' "$HERE/$PROG")" ordered
	cp "$d/prereg6.bak" "$jr6/J-prereg.log"

	# capture life and the start margin for J6's longer host run: s1-j1.params' return bound
	# lengthens gates A and B; the start margin (L4T up to the issue) is J2's and J4's
	out="$(
		RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"; resolve_kimg s1-j1; jrun_step control s1-j1
		printf '%s/%s/%s' "$RETURN_BOUND" "$(j_capture_life_min control "$RETURN_BOUND" 9)" "$(j_worst_case control)"
	)"
	check "j6 bounds: return bound from s1-j1.params, gate A life = return bound + 2180 + fallback, start margin J2's" \
		"$out" "2100/$(( 2100 + 2180 + $(wq_fallback_s 9) ))/$(j_worst_case control)"
	# the captures' deadlines are taken from the clock now, not from the self-test's start. Its own
	# name (cap6): the gate-A checks further down still read J1-J4's $cap in $jrec
	cap6="$jr6/j6-cap.log"
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=4600 ---\n' "$(date +%s)" > "$cap6"
	printf 'MB1 version synthetic\r\n' >> "$cap6"
	out="$( RECDIR="$jr6a"; RETURN_BOUND=1200; S1_COM3_LOG="$cap6" j_capture_gate control 9 )"
	check "j6 bounds: a 4,600 s capture passes gate A at s1-h1's return bound (1,200 s)" "$(has "$out" 'jgate control ok')" yes
	out="$( RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"; resolve_kimg s1-j1; S1_COM3_LOG="$cap6" j_capture_gate control 9 )"
	check "j6 bounds: the same capture is refused at s1-j1's longer return bound" "$(has "$out" "under $(( 2100 + 2180 + $(wq_fallback_s 9) )) s for control")" yes
	printf -- '--- raw capture started on COMX at 115200, 2026-09-14T00:00:00Z epoch=%s seconds=3500 ---\n' "$(date +%s)" > "$jr6/j6-capb.log"
	printf 'MB1 version synthetic\r\n' >> "$jr6/j6-capb.log"
	out="$( RECDIR="$jr6a"; mark_capture "$jr6/j6-capb.log"; RETURN_BOUND=1200; S1_COM3_LOG="$jr6/j6-capb.log" j_gate_b remove )"
	check "j6 bounds: a 3,500 s capture passes gate B at s1-h1's return bound" "$(has "$out" 'jgateB remove ok')" yes
	out="$( RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"; resolve_kimg s1-j1; S1_COM3_LOG="$jr6/j6-capb.log" j_gate_b remove )"
	check "j6 bounds: gate B's life uses s1-j1's return bound too" "$(has "$out" "under $(( 2100 + 1200 + $(wq_fallback_s 9) )) s")" yes

	# J6's export frames on COM3 (§15.5 B8.4): its S1 BEGIN/S1 END bodies keep the record classes
	out="$(printf '%s\n' 'S1 CANARY c2 watch=verdict label=d writer=static heal=no reads=stable content=unclassified' \
		'  S1 BEGIN name=j1a bytes=1632 md5=00000000000000000000000000000000 enc=base64' 'UzFKMVBCTVABAAAAYzIAAGEAAAAAAAAAAAAAAA==' | com3_last_kind)"
	check "com3_last_kind: an open J6 export's body is export-body" "$out" export-body
	out="$(printf '%s\n' 'S1 BEGIN name=j1d bytes=1632 md5=00000000000000000000000000000000 enc=base64' 'UzFKMVBCTVAB' \
		'S1 END name=j1d' 'S1 EXPORT name=j1d bytes=1632 md5=00000000000000000000000000000000 enc=base64 rc=0' | com3_last_kind)"
	check "com3_last_kind: J6's closed frame and its S1 EXPORT record are record" "$out" record
	cp "$d/c.log" "$d/j6e.log"
	printf 'S1 CANARY c1 watch=time label=d snaps=60 changed_snaps=0 changed_words=0 healed=0 osc=0 prog=0 stable=0 stop=count\r\nS1 BEGIN name=j1c bytes=1632 md5=00000000000000000000000000000000 enc=base64\r\nUzFKMVBCTVAB\r\n' >> "$d/j6e.log"
	touch -d "@$(( now - 400 ))" "$d/j6e.log"
	check "advice: a J6 export body as the last line after the jump is F25a" "$(has "$(ADVICE_SSH=silent com3_advice "$d/j6e.log" "$off" 0 passed)" 'class=F25a')" yes

	# J6's parse arguments, canwatch.txt and the stop rows (parser and python are stubs)
	printf '%s\n' '#!/bin/bash' 'printf "%s\n" "$@" > "$FAKEPY_ARGS"' 'prev=""' 'for a in "$@"; do' \
		'	if [ "$prev" = --out-dir ]; then printf "S1CW result=complete\n" > "$a/canwatch.txt"; fi' '	prev="$a"' 'done' 'exit 0' > "$d/fakepy.sh"
	chmod +x "$d/fakepy.sh"
	for g in F49,writer-static writer-none; do
		out="$(
			RECDIR="$jr6a"; S1_KIMG_DIR="$kd6"; ORIN_HOST=""; R_HOSTNAME=synthetic-board
			resolve_kimg s1-j1 >/dev/null; jrun_step control s1-j1
			SD="$jr6a/J6c-t$([ "$g" = writer-none ] && echo 2 || echo 1)"; mkdir -p "$SD"; UTC=20260914T070000Z; base="$SD/s1-j1-$UTC"
			rec_open "$base-board.log" >/dev/null
			printf 'kpf_header=1\n' > "$base-kpf-prequiesce-header.txt"
			export FAKEPY_ARGS="$d/fakepy-$g.args"
			PY_BIN="$d/fakepy.sh"
			j6_parse_setup control "$base" >/dev/null
			printf '%s|' "${J6_PARGS[@]}"
			for l in a b c; do printf 'S1J1PBMP' > "$SD/s1-j1$l.bin"; done
			printf 'S1PC step=J6c\nS1PC j_row=%s\n' "$g" > "$SD/parse-s1.txt"
			printf 'synthetic\n' > "$base-com3.log"
			j6_after_parse "$base-com3.log" >/dev/null 2>&1
			echo
			cat "$base-board.log"
		)"
		k="$(cat "$d/fakepy-$g.args" 2>/dev/null | tr '\n' '|')"
		case "$g" in
		F49,writer-static)
			check "j6 parse args: arm, the registered factor, the params' hold and the one fetched kpf header" "$(printf '%s\n' "$out" | head -n 1)" \
				"--arm|control|--fill-factor|2|--hold-mib|$h6|--kpf|$jr6a/J6c-t1/s1-j1-20260914T070000Z-kpf-prequiesce-header.txt|"
			check "j6 canwatch: run on the COM3 copy with the factor, the rung's directory and the kpf header" \
				"$(has "$k" "canwatch|$jr6a/J6c-t1/s1-j1-20260914T070000Z-com3.log|--fill-factor|2|--bin-dir|$jr6a/J6c-t1|--out-dir|$jr6a/J6c-t1|--kpf|")" yes
			check "j6 canwatch: its rc and result line are recorded, and canwatch.txt exists" \
				"$(has "$out" 'run canwatch rc=0 S1CW result=complete')/$([ -f "$jr6a/J6c-t1/canwatch.txt" ] && echo written)" "yes/written"
			check "j6 exports: three written are recorded, the missing fourth is said" \
				"$(printf '%s\n' "$out" | grep -c '^run j6 export s1-j1[abc].bin bytes=8 ')/$(has "$out" 'run j6 export s1-j1d.bin NOT written')" "3/yes"
			check "j6 stop: a j_row holding F49 is an IMMEDIATE STOP in the board log" "$(has "$out" 'run j6 IMMEDIATE STOP: j_row holds F49 (')" yes
			;;
		writer-none)
			check "j6 stop: a j_row without F39 or F49 is no stop" "$(has "$out" 'run j6 j_row=writer-none')/$(has "$out" 'IMMEDIATE STOP')" "yes/no"
			;;
		esac
	done
	check "run_return_records passes J6's arguments to the parser only for --diag j1" \
		"$(grep -cE '^[[:space:]]*\[ "\$\{JDIAG:-\}" = j1 \] && pargs\+=\("\$\{J6_PARGS\[@\]\}"\)' "$HERE/$PROG")/$(grep -cE '^[[:space:]]*\[ "\$\{JDIAG:-\}" = j1 \] && j6_after_parse "\$com3"' "$HERE/$PROG")" "1/1"

	# J3's gates as rows (§15.4.5), on synthetic records
	res="$(
		RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_set_select j3
		{ for line in 1:wireless-down 2:wireless-unbind 3:wireless-module 4:wireless-bme 5:xhci-unbind 6:ethernet-unbind 7:ethernet-bme 8:nvme-unbind 9:nvme-bme; do
			printf 's1wq: slot%s %s result=0\n' "${line%%:*}" "${line#*:}"; done
		  for g in 00f1:01:00.0 00f1:00:00.0 00f2:01:00.0 00f2:00:00.0 00f3:01:00.0 00f3:00:00.0; do printf 'pci final dev=%s class=x driver=none parent=none power_state=D0 enable=1 cmd=0x0402 bme=0\n' "$g"; done
		  printf 'bme_after_unbind member=W value=1\n'; } > "$d/j3wq.log"
		{ printf -- '--- raw capture started ---\n'; sed 's/^/[  1.000000] /' "$d/j3wq.log" | grep 's1wq:'; printf '[  9.000000] s1wq: fallback firing\n'; } > "$d/j3c.log"
		printf '%s\n' 'pci return dev=00f1:01:00.0 class=0x028000 driver=fakewlan parent=00f1:00:00.0 power_state=D0 enable=1 cmd=0x0406 bme=1' \
			'pci return dev=00f2:01:00.0 class=0x020000 driver=fakeeth parent=00f2:00:00.0 power_state=D0 enable=1 cmd=0x0406 bme=1' \
			'pci return dev=00f3:01:00.0 class=0x010802 driver=fakenvme parent=00f3:00:00.0 power_state=D0 enable=1 cmd=0x0406 bme=1' \
			'xhci return present=yes driver=fakexhci' 'rfkill return name=rfkill0 type=wlan soft=0 hard=0' \
			'netdev return if=fakewlan0 operstate=up dev=00f1:01:00.0' 'svc return NetworkManager=active wpa_supplicant=active' > "$d/j3pr.log"
		j3_rows "$d/j3wq.log" "$d/j3c.log" 0 "$d/j3pr.log" "" | tail -n 1
		sed -i 's/^s1wq: slot6 ethernet-unbind result=0$/s1wq: slot6 ethernet-unbind result=1/' "$d/j3wq.log"
		j3_rows "$d/j3wq.log" "$d/j3c.log" 0 "$d/j3pr.log" "" | tail -n 1
		sed -i '/^svc return/d' "$d/j3pr.log"
		j3_rows "$d/j3wq.log" "$d/j3c.log" 0 "$d/j3pr.log" "" | tail -n 1
		printf '[  8.000000] s1wq: abort reason=oops\n' >> "$d/j3c.log"
		j3_rows "$d/j3wq.log" "$d/j3c.log" 0 "$d/j3pr.log" "fake.service loaded" | tail -n 1
		j3_rows "$d/j3wq.log" "$d/j3c.log" 0 "$d/j3pr.log" "" "fake-20260914T000000Z-wq.log" | tail -n 1
		WQG_E_IN=no
		sed -i '/^pci return dev=00f2:01:00.0 /d' "$d/j3pr.log"
		j3_rows "$d/j3wq.log" "$d/j3c.log" 0 "$d/j3pr.log" "" | tail -n 1
	)"
	check "j3 rows: sequence files left on the board are NOT MET" "$(printf '%s\n' "$res" | sed -n 5p | grep -c 'files-left')" 1
	check "j3 rows: a member outside the set whose driver is not bound after the return is F41" "$(printf '%s\n' "$res" | sed -n 6p | grep -c 'F41-E')" 1
	check "j3 rows: every gate met" "$(printf '%s\n' "$res" | sed -n 1p | cut -d: -f1)" "j3 RESULT MET"
	check "j3 rows: a non-wireless step failed: wireless-only" "$(printf '%s\n' "$res" | sed -n 2p | cut -d: -f1)" "j3 RESULT MET wireless-only"
	check "j3 rows: a network service not active after the return is F41" "$(printf '%s\n' "$res" | sed -n 3p | grep -c '^j3 RESULT NOT MET F41-services')" 1
	check "j3 rows: an Oops abort and a listed unit are NOT MET" "$(printf '%s\n' "$res" | sed -n 4p | grep -c '^j3 RESULT NOT MET abort,units')" 1

	# the exit-5 branch: identity, pstore, nvbootctrl, the abort class and the sequence's files,
	# but no black box and no parser (board, scp, python and the return records are stubs)
	cp "$cap4" "$d/x5.log"; printf '[ 1000.000000] s1wq: abort reason=oops\r\n' >> "$d/x5.log"
	out="$(
		RECDIR="$jr2a"; SD="$jr2a/J4"; UTC=20260914T030000Z; name="s1-h1-$UTC"; base="$SD/$name"; kw=jrun
		S1_COM3_LOG="$d/x5.log"; com3_off="$off4"; pstore_before=""
		rec_open "$base-board.log" >/dev/null
		board() { case "$*" in *b_identity*) printf 'boot_id=00000000-0000-4000-8000-000000000009\nuptime_s=50\nslots_rc=0\nslots synthetic\n' ;; *b_wq_files*) printf 'wqfiles listed\n' ;; esac; }
		j_scp() { return 1; }
		find_python() { echo parser >> "$d/x5-called"; return 1; }
		run_return_records() { echo blackbox >> "$d/x5-called"; }
		( j_return_aborted ABORTED ) >/dev/null 2>&1
		echo "rc=$?"
	)"
	check "exit-5 branch: exit 5" "$out" "rc=5"
	check "exit-5 branch: the black box and the parser are skipped, and it says so" "$([ -f "$d/x5-called" ] && echo called || echo skipped)/$(grep -c 'black box is NOT copied and the parser NOT run' "$jr2/J4/s1-h1-20260914T030000Z-board.log")" "skipped/1"
	check "exit-5 branch: an Oops abort is F47; no black box or parse-s1.txt file" "$(grep -c 'abort class=F47' "$jr2/J4/s1-h1-20260914T030000Z-board.log")/$(ls "$jr2/J4" | grep -cE 'blackbox|parse-s1')" "1/0"

	# F37 (ISSUED, a new boot, no shim line): an immediate stop, exit 3, never exit 5's retry
	cp "$cap4" "$d/x37.log"; printf '[ 1100.000000] s1wq: kexec issuing\r\n' >> "$d/x37.log"
	out="$(
		RECDIR="$jr2a"; SD="$jr2a/J4-a2"; mkdir -p "$SD"; UTC=20260914T040000Z; name="s1-h1-$UTC"; base="$SD/$name"; kw=jrun
		S1_COM3_LOG="$d/x37.log"; com3_off="$off4"; pstore_before=""
		rec_open "$base-board.log" >/dev/null
		board() { case "$*" in *b_identity*) printf 'boot_id=00000000-0000-4000-8000-000000000009\nuptime_s=50\nslots_rc=0\nslots synthetic\n' ;; *b_wq_files*) printf 'wqfiles listed\n' ;; esac; }
		j_scp() { return 1; }
		run_return_records() { echo blackbox >> "$d/x37-called"; }
		( j_return_noparse f37 ISSUED ) >/dev/null 2>&1
		echo "rc=$?"
	)"
	bl="$jr2/J4-a2/s1-h1-20260914T040000Z-board.log"
	check "F37 return: exit 3, an immediate stop, no retry advised, no black box or parser" \
		"$out/$(grep -c 'IMMEDIATE STOP' "$bl")/$(grep -c 'retry on a fresh boot' "$bl")/$([ -f "$d/x37-called" ] && echo called || echo skipped)/$(grep -c 'previous console copy FAILED' "$bl")" "rc=3/1/0/skipped/1"

	# J2's Bus Master state at the issue (§15.4.4's last row)
	out="$(
		RECDIR="$jr2a"; J_DEC_LOADED=0; j_read_decisions; j_set_select control
		printf '%s\n' 'pci final dev=00f1:01:00.0 class=x driver=fakewlan parent=00f1:00:00.0 power_state=D0 enable=1 cmd=0x0406 bme=1' \
			'pci final dev=00f1:00:00.0 class=x driver=fakeport parent=none power_state=D0 enable=1 cmd=0x0403 bme=0' \
			'pci final dev=00f2:01:00.0 class=x driver=fakeeth parent=00f2:00:00.0 power_state=D0 enable=1 cmd=0xffff bme=unread' > "$d/bai.log"
		j_bme_at_issue "$d/bai.log" | tr '\n' '|'
	)"
	check "bme_at_issue_control: the endpoint's and the port's values, unread when absent or unreadable" "$out" \
		"bme_at_issue_control member=W role=endpoint value=1|bme_at_issue_control member=W role=port value=0|bme_at_issue_control member=E role=endpoint value=unread|bme_at_issue_control member=E role=port value=unread|bme_at_issue_control member=N role=endpoint value=unread|bme_at_issue_control member=N role=port value=unread|"

	# Phase A's failure path: the stop and the unload are claimed only when a read confirms them
	for g in confirmed unconfirmed; do
		out="$(
			RECDIR="$jr2a"; SD="$jr2a/J2-a3"; mkdir -p "$SD"; UTC="20260914T05000$([ "$g" = confirmed ] && echo 1 || echo 2)Z"; base="$SD/s1-h1-$UTC"; kw=jrun; J_UNITS_UTC="$UTC"
			rec_open "$base-board.log" >/dev/null
			if [ "$g" = confirmed ]; then
				board() { case "$*" in *b_unload*) printf 'kexec_loaded_before_unload=1\nkexec_unload_rc=0\nkexec_loaded=0\n' ;; *b_wq_files*) printf 'wqfiles listed\n' ;; esac; }
			else
				board() { return 124; }
			fi
			( j_phase_a_fail "a synthetic failure" ) >/dev/null 2>&1
			echo "rc=$? armed=$(grep -c '^wq_armed armed_epoch=[0-9]* wq_fallback_s=645$' "$base-board.log") confirmed=$(grep -c 'confirmed by a read' "$base-board.log") unconfirmed=$(grep -c 'NOT CONFIRMED' "$base-board.log")"
		)"
		case "$g" in
		confirmed)   check "Phase A failure: a confirmed stop and unload say so (exit 3)" "$out" "rc=3 armed=0 confirmed=1 unconfirmed=0" ;;
		unconfirmed) check "Phase A failure: an unreachable board is NOT CONFIRMED, and a wq_armed line holds advice (exit 3)" "$out" "rc=3 armed=1 confirmed=0 unconfirmed=1" ;;
		esac
	done

	# the SSID against the lines the harness reads back, and a PowerShell-typed capture path
	check "ssid: a usable name is not refused" "$(ssid_refusal 'CoffeeShop-WiFi')" ""
	check "ssid: part of a fixed word the harness reads back (run) is refused" "$(has "$(ssid_refusal run)" 'fixed word')" yes
	check "ssid: digits and separators only are refused" "$(has "$(ssid_refusal 12-345)" 'digits and separators')" yes
	check "gate A: an SSID that is a control word (MET) is refused" "$(has "$(S1_COM3_LOG="$cap" S1_REDACT_SSID='MET' j_capture_gate control 9)" 'fixed word')" yes
	g="$(cygpath -w "$cap" 2>/dev/null)"
	[ -n "$g" ] || g="${cap//\//\\}"
	check "a backslash capture path is normalised and still resolves inside the record directory" \
		"$( S1_COM3_LOG="$g"; j_norm_capture; capture_inside_recdir "$S1_COM3_LOG" && basename "$S1_COM3_LOG" )" "j-cap.log"

	if [ -f "$S1DIR/kpf-decode.py" ] && find_python; then
		bash "$0" kpf-decode --selftest >/dev/null 2>&1
		check "kpf-decode --selftest" "$?" 0
	else
		echo "  skip  kpf-decode --selftest: no kpf-decode.py or python here"
	fi
	unset S1_REDACT_SSID S1_COM3_LOG S1_J_RULE_FILE

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
j1)          [ $# -eq 1 ] || usage; cmd_j1 ;;
j3)          [ $# -eq 1 ] || usage; cmd_j3 ;;
jrun)        [ $# -eq 3 ] || usage; cmd_jrun "$2" "$3" ;;
wq-status)   { [ $# -eq 2 ] && [ -f "$2" ]; } || usage; cmd_wq_status "$2" ;;
kpf-decode)  { [ $# -eq 2 ] || [ $# -eq 3 ]; } || usage; cmd_kpf_decode "${@:2}" ;;
redact-selftest)  [ $# -eq 1 ] || usage; cmd_redact_selftest ;;
harness-selftest) [ $# -eq 1 ] || usage; cmd_harness_selftest ;;
*)           usage ;;
esac
