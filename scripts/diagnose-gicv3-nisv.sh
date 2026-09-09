#!/usr/bin/env bash
#
# Phase 3 / Phase 4 diagnostic
# diagnose-gicv3-nisv.sh — read-only evidence collector, decoder and report
#                          generator for the qnx-safety-vm KVM boot hang
#                          (GICv3 distributor bring-up -> KVM_EXIT_ARM_NISV,
#                          docs/orin-port.md risk register, docs/findings.md
#                          2026-07-28/29 and 2026-09-08 entries).
#
# NOT the QHV/TCG QEMU-6.2 virtual-timer hang (docs/orin-port.md 2026-09-08/09
# rows, every logs/sample-boot/*qhv* file). Those logs are listed as excluded.
#
# What it does
#   - collects host / repo / log evidence that is readable without privilege
#   - decodes an ESR_EL2 value (--esr), composes an IPA (--hpfar/--far/--ipa),
#     classifies a faulting opcode from a disassembly window (--elf/--guest-pc)
#   - compares a candidate IPA with GIC MMIO ranges (DTB / monitor / reference)
#   - writes results/gicv3-nisv-debug/<UTC>/summary.md + raw/*.txt, redacted
#
# What it never does
#   - boot a guest, ssh anywhere, install anything, or run a privileged command
#     (those are PRINTED under "Exact next commands")
#   - copy a QNX binary, ELF, IFS or DTB into results/ (only short excerpts,
#     hashes and decoded fields)
#   - overwrite a previous results directory
#
# Runs on Linux (L4T, Ubuntu) and Git Bash on Windows. Tools that are missing
# degrade the corresponding matrix row to BLOCKED / NOT RUN; nothing aborts.
#
# Usage: bash scripts/diagnose-gicv3-nisv.sh [options]      (all optional)
#   --log-dir DIR          directory of serial boot logs to classify
#                          (default: logs/sample-boot)
#   --boot-log FILE        one more boot log to classify (repeatable)
#   --dtb FILE             flattened device tree to analyse (dumpdtb= output)
#   --elf FILE             startup ELF (or raw binary with --elf-base) to
#                          disassemble around --guest-pc
#   --elf-base HEX         load address of --elf's .text (converts a guest VA
#                          into a file offset; required for raw binaries)
#   --guest-pc HEX         faulting PC (guest VA, e.g. from kvm_guest_fault pc=)
#   --esr HEX              ESR_EL2 / kvm_guest_fault hsr= value to decode
#   --far HEX              FAR_EL2 / HXFAR (guest VA of the access)
#   --hpfar HEX            HPFAR_EL2 (FIPA field, see formula in summary)
#   --ipa HEX              fault IPA as printed by the kvm_guest_fault trace
#   --granule 4K|16K|64K   stage-1 (guest) translation granule you assert; used
#                          ONLY as a FAR-vs-HPFAR consistency check (default
#                          4K). It never enters the IPA: the 12-bit page
#                          offset is fixed by the architecture
#   --qemu-pid PID         inspect /proc/PID of a running QEMU (Linux)
#   --qmp-socket PATH      QMP unix socket of a running QEMU (read-only cmds)
#   --monitor-socket PATH  HMP unix socket of a running QEMU (read-only cmds)
#   --out-root DIR         results root (default: results/gicv3-nisv-debug)
#   --window N             instructions each side of the PC (default 4, max
#                          64 — keeps NCEULA disassembly excerpts short)
#   --redact TOKEN         extra literal to redact from everything written
#                          (repeatable; DIAGNOSE_REDACT=a,b,c also works)
#   --help

set -euo pipefail

script_path="${BASH_SOURCE[0]}"
script_dir="$(cd "$(dirname "${script_path}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

log_dir="${repo_root}/logs/sample-boot"
boot_logs=()
dtb_file=""
elf_file=""
elf_base=""
guest_pc=""
esr_value=""
far_value=""
hpfar_value=""
ipa_value=""
granule="4K"
qemu_pid=""
qmp_socket=""
monitor_socket=""
out_root="${repo_root}/results/gicv3-nisv-debug"
disasm_window=4
redact_tokens=()
cmd_timeout=25

usage() {
  sed -n '/^# Usage:/,/^# *--help/p' "${script_path}" | sed 's/^# \{0,1\}//'
}

argv_record="$*"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --log-dir|--boot-log|--dtb|--elf|--elf-base|--guest-pc|--esr|--far|--hpfar|--ipa|--granule|--qemu-pid|--qmp-socket|--monitor-socket|--out-root|--window|--redact)
      [[ $# -ge 2 ]] || { echo "ERROR: $1 needs a value (see --help)" >&2; exit 2; };;
  esac
  case "$1" in
    --log-dir)        log_dir="$2"; shift 2;;
    --boot-log)       boot_logs+=("$2"); shift 2;;
    --dtb)            dtb_file="$2"; shift 2;;
    --elf)            elf_file="$2"; shift 2;;
    --elf-base)       elf_base="$2"; shift 2;;
    --guest-pc)       guest_pc="$2"; shift 2;;
    --esr)            esr_value="$2"; shift 2;;
    --far)            far_value="$2"; shift 2;;
    --hpfar)          hpfar_value="$2"; shift 2;;
    --ipa)            ipa_value="$2"; shift 2;;
    --granule)        granule="$2"; shift 2;;
    --qemu-pid)       qemu_pid="$2"; shift 2;;
    --qmp-socket)     qmp_socket="$2"; shift 2;;
    --monitor-socket) monitor_socket="$2"; shift 2;;
    --out-root)       out_root="$2"; shift 2;;
    --window)         disasm_window="$2"; shift 2;;
    --redact)         redact_tokens+=("$2"); shift 2;;
    -h|--help)        usage; exit 0;;
    *) echo "ERROR: unknown option '$1' (see --help)" >&2; exit 2;;
  esac
done

is_hex() { [[ "$1" =~ ^(0[xX])?[0-9a-fA-F]{1,16}$ ]]; }
to_dec() { printf '%d' "$(( 0x${1#0[xX]} ))"; }
hex() { printf '0x%x' "$1"; }

for pair in "esr:${esr_value}" "far:${far_value}" "hpfar:${hpfar_value}" "ipa:${ipa_value}" "guest-pc:${guest_pc}" "elf-base:${elf_base}"; do
  v="${pair#*:}"
  if [[ -n "${v}" ]] && ! is_hex "${v}"; then
    echo "ERROR: --${pair%%:*} '${v}' is not a hex value (up to 16 hex digits, optional 0x)" >&2
    exit 2
  fi
done
case "${granule}" in
  4K|4k)   granule="4K";  granule_bytes=4096;;
  16K|16k) granule="16K"; granule_bytes=16384;;
  64K|64k) granule="64K"; granule_bytes=65536;;
  *) echo "ERROR: --granule must be 4K, 16K or 64K" >&2; exit 2;;
esac
[[ "${disasm_window}" =~ ^[0-9]+$ ]] && (( disasm_window <= 64 )) || { echo "ERROR: --window must be an integer 0..64" >&2; exit 2; }
[[ -z "${qemu_pid}" || "${qemu_pid}" =~ ^[0-9]+$ ]] || { echo "ERROR: --qemu-pid must be numeric" >&2; exit 2; }

# ---------------------------------------------------------------- platform
uname_s="$(uname -s 2>/dev/null || echo unknown)"
case "${uname_s}" in
  MINGW*|MSYS*|CYGWIN*) platform="windows-gitbash";;
  Linux)                platform="linux";;
  Darwin)               platform="macos";;
  *)                    platform="other";;
esac

have() { command -v "$1" >/dev/null 2>&1; }

qnx_host_dirs=()
[[ -n "${QNX_HOST:-}" ]] && qnx_host_dirs+=("${QNX_HOST}/usr/bin")
for d in "${HOME:-/nonexistent}/qnx800/host/win64/x86_64/usr/bin" "${HOME:-/nonexistent}/qnx800/host/linux/x86_64/usr/bin" \
         "/opt/qnx800/host/linux/x86_64/usr/bin" "${USERPROFILE:-/nonexistent}/qnx800/host/win64/x86_64/usr/bin"; do
  [[ -d "${d}" ]] && qnx_host_dirs+=("${d}")
done

find_tool() {
  local n p d c
  for n in "$@"; do
    if p="$(command -v "${n}" 2>/dev/null)"; then printf '%s' "${p}"; return 0; fi
    for d in ${qnx_host_dirs[@]+"${qnx_host_dirs[@]}"}; do
      for c in "${d}/${n}" "${d}/${n}.exe"; do
        if [[ -x "${c}" ]]; then printf '%s' "${c}"; return 0; fi
      done
    done
  done
  return 1
}

run_with_timeout() {
  if have timeout; then timeout "${cmd_timeout}" "$@"; else "$@"; fi
}

python_bin=""
for cand in python3 python; do
  if have "${cand}" && run_with_timeout "${cand}" -c 'import sys, struct' >/dev/null 2>&1; then
    python_bin="${cand}"; break
  fi
done

# ---------------------------------------------------------------- redaction
# Everything written under results/ passes through redact(). Documented
# project constants (br0 subnet, SLIRP lease, synthetic MACs) are preserved.
# Built and self-tested BEFORE the results dir exists so a bad token cannot
# leave a half-written directory behind.
sed_args=()
build_redaction() {
  local toks=() t esc seen=" "
  for t in "${USER:-}" "${USERNAME:-}" "${LOGNAME:-}" "$(id -un 2>/dev/null || true)" \
           "$(basename "${HOME:-/}")" "$(basename "${USERPROFILE:-/}")" "$(hostname 2>/dev/null || true)" \
           ${redact_tokens[@]+"${redact_tokens[@]}"}; do
    toks+=("${t}")
  done
  if [[ -n "${DIAGNOSE_REDACT:-}" ]]; then
    IFS=',' read -r -a env_toks <<< "${DIAGNOSE_REDACT}"
    toks+=("${env_toks[@]}")
  fi
  sed_args+=(-e 's/\b192\.168\.100\.([0-9]{1,3})\b/__KEEP_BR_\1__/g'
             -e 's/\b10\.0\.2\.15\b/__KEEP_SLIRP__/g'
             -e 's/\b52:54:00:11:11:11\b/__KEEP_MAC1__/g'
             -e 's/\b52:54:00:22:22:22\b/__KEEP_MAC2__/g'
             -e 's/\b10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b/<LAN-IP>/g'
             -e 's/\b172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}\b/<LAN-IP>/g'
             -e 's/\b192\.168\.[0-9]{1,3}\.[0-9]{1,3}\b/<LAN-IP>/g'
             -e 's/\bi-[0-9a-f]{8,17}\b/<aws-instance-id>/g'
             -e 's/\b(ami|vol|sg|subnet|vpc|eni|snap|rtb|igw)-[0-9a-f]{8,17}\b/<aws-id>/g'
             -e 's/\b[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}\b/<mac>/g'
             -e 's#\.ssh/[A-Za-z0-9_.-]+#.ssh/<key>#g'
             -e 's/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/<email>/g'
             # environment-independent: other hosts' logins in tracked logs and AWS hostnames
             -e 's#/home/[^/[:space:]]+#/home/<user>#g'
             -e 's#/Users/[^/[:space:]]+#/Users/<user>#g'
             -e 's#([A-Za-z]:\\Users\\)[^\\[:space:]]+#\1<user>#g'
             -e 's/\bec2-[0-9-]+\.[a-z0-9.-]*amazonaws\.com\b/<aws-host>/g'
             -e 's/\bip-[0-9]{1,3}(-[0-9]{1,3}){3}\b/<aws-host>/g')
  for t in ${toks[@]+"${toks[@]}"}; do
    [[ -n "${t}" ]] || continue
    case "${t}" in root|ubuntu|nvidia|user|admin|/|.) continue;; esac
    if [[ ${#t} -lt 3 ]]; then echo "WARNING: redaction token '${t}' dropped (shorter than 3 characters)" >&2; continue; fi
    [[ "${seen}" == *" ${t} "* ]] && continue
    seen="${seen}${t} "
    esc="$(printf '%s' "${t}" | sed -e 's/[][\/.*^$+?(){}|\\]/\\&/g')"
    # \b only matches next to a word character, so anchor only on such sides
    lb=""; rb=""
    [[ "${t:0:1}" =~ [A-Za-z0-9_] ]] && lb='\b'
    [[ "${t: -1}" =~ [A-Za-z0-9_] ]] && rb='\b'
    sed_args+=(-e "s/${lb}${esc}${rb}/<user>/Ig")
  done
  sed_args+=(-e 's/__KEEP_BR_([0-9]{1,3})__/192.168.100.\1/g'
             -e 's/__KEEP_SLIRP__/10.0.2.15/g'
             -e 's/__KEEP_MAC1__/52:54:00:11:11:11/g'
             -e 's/__KEEP_MAC2__/52:54:00:22:22:22/g')
}
build_redaction
redact() { sed -E "${sed_args[@]}"; }
if ! probe="$(printf 'redaction-probe 192.168.1.2 i-0123456789abcdef0 /home/probelogin7/x C:\\Users\\probelogin7\\y\n' | redact 2>/dev/null)" \
   || [[ "${probe}" != 'redaction-probe <LAN-IP> <aws-instance-id> /home/<user>/x C:\Users\<user>\y' ]]; then
  echo "ERROR: redaction filter failed its self-test (bad --redact/DIAGNOSE_REDACT token?): '${probe:-}'" >&2
  exit 2
fi

# ---------------------------------------------------------------- output dir
work="$(mktemp -d "${TMPDIR:-/tmp}/gicv3-nisv.XXXXXX")"
out_dir=""
finish() {
  local rc=$?
  rm -rf "${work}"
  if [[ ${rc} -ne 0 && -n "${out_dir}" && -d "${out_dir}" && ! -f "${out_dir}/summary.md" ]]; then
    printf 'INCOMPLETE: exited with status %d before summary.md was written; raw/ may be partial\n' "${rc}" > "${out_dir}/INCOMPLETE"
    echo "NOTE: partial results left in ${out_dir} (INCOMPLETE marker written, nothing deleted)" >&2
  fi
}
trap finish EXIT
ts="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${out_root}"
# plain mkdir is the atomic claim: two runs in the same second get distinct
# dirs; out_dir stays empty until the claim succeeds so the EXIT trap can
# never stamp INCOMPLETE into another run's directory
claim="${out_root}/${ts}"; n=1
until mkdir "${claim}" 2>/dev/null; do
  n=$((n + 1)); claim="${out_root}/${ts}-${n}"
  if (( n > 999 )); then echo "ERROR: cannot create a results dir under ${out_root} (permissions?)" >&2; exit 2; fi
done
out_dir="${claim}"
mkdir "${out_dir}/raw"
out_dir_rel="${out_dir#"${repo_root}"/}"

# ---------------------------------------------------------------- capture helpers
raw_index=()
run_to_raw() {
  local name="$1"; shift
  local rc=0
  run_with_timeout "$@" >"${work}/cap" 2>&1 || rc=$?
  redact <"${work}/cap" >"${out_dir}/raw/${name}.txt"
  raw_index+=("raw/${name}.txt")
  return "${rc}"
}
sh_to_raw() { local name="$1" cmd="$2"; shift 2; run_to_raw "${name}" bash -c "${cmd}" _ "$@"; }
raw_lines() { wc -l <"${out_dir}/raw/$1.txt" | tr -d ' '; }
raw_denied() { grep -qiE 'permission denied|operation not permitted|are you root|not seeing messages|no journal files' "${out_dir}/raw/$1.txt"; }
write_raw() {  # name <- stdin
  redact >"${out_dir}/raw/$1.txt"
  raw_index+=("raw/$1.txt")
}

# Rows are joined with a unit separator so detail text may contain '|';
# cell() escapes '|' for the markdown renderers.
sep=$'\x1f'
cell() { printf '%s' "${1//|/\\|}"; }
matrix=()
record() {
  case "$2" in PASS|FAIL|BLOCKED|"NOT APPLICABLE"|"NOT RUN") ;;
    *) echo "BUG: bad status '$2' for '$1'" >&2; exit 3;; esac
  matrix+=("$1${sep}$2${sep}$3")
}

section() { echo "==> $*"; }

# ================================================================ 1. environment
section "Environment"
env_lines=()
env_lines+=("platform: ${platform} (uname -s: ${uname_s}, uname -m: $(uname -m 2>/dev/null || echo '?'))")
env_lines+=("bash: ${BASH_VERSION}")
env_lines+=("generated (UTC): ${ts}")
run_to_raw host-uname uname -a || true

if [[ -r /etc/os-release ]]; then
  run_to_raw host-os-release cat /etc/os-release || true
  env_lines+=("os-release: $({ grep -E '^PRETTY_NAME=' /etc/os-release || true; } | cut -d= -f2- | tr -d '"')")
else
  env_lines+=("os-release: not present (non-Linux host)")
fi

if have lscpu; then
  run_to_raw host-lscpu lscpu || true
  record "Host CPU inventory (lscpu)" "PASS" "raw/host-lscpu.txt"
else
  record "Host CPU inventory (lscpu)" "NOT RUN" "lscpu not on PATH ($platform)"
fi
if [[ -r /proc/cpuinfo ]]; then
  sh_to_raw host-cpuinfo "grep -E 'CPU (implementer|architecture|variant|part|revision)|model name|Features|Hardware' /proc/cpuinfo | sort | uniq -c" || true
  cpu_parts="$(awk '/CPU part/{print $4}' /proc/cpuinfo | sort -u | tr '\n' ' ')"
  [[ -n "${cpu_parts}" ]] && env_lines+=("cpu part(s): ${cpu_parts}(MIDR part numbers, not mapped to names here)")
fi

qemu_found=()
qemu_kvm_capable="no"
qemu_cands=()
[[ -n "${QEMU_BIN:-}" ]] && qemu_cands+=("${QEMU_BIN}")
if p="$(command -v qemu-system-aarch64 2>/dev/null)"; then qemu_cands+=("${p}"); fi
for p in "${HOME:-/nonexistent}"/qemu-v*/bin/qemu-system-aarch64 "/c/Program Files/qemu/qemu-system-aarch64.exe" "/opt/qemu"*/bin/qemu-system-aarch64; do
  [[ -x "${p}" ]] && qemu_cands+=("${p}")
done
qi=0
for q in ${qemu_cands[@]+"${qemu_cands[@]}"}; do
  [[ -x "${q}" ]] || continue
  qi=$((qi + 1))
  ver="$(run_with_timeout "${q}" --version 2>/dev/null || true)"; ver="${ver%%$'\n'*}"; ver="${ver%$'\r'}"
  [[ -n "${ver}" ]] || ver='(version query failed)'
  accels="$(run_with_timeout "${q}" -accel help 2>/dev/null || true)"
  accels="$(grep -vi 'accelerators supported' <<<"${accels}" | tr -s '\r\n' ' ' || true)"
  [[ -n "${accels// /}" ]] || accels='?'
  qemu_found+=("${q} :: ${ver} :: accel: ${accels}")
  printf '%s\n%s\naccel: %s\n' "${q}" "${ver}" "${accels}" | write_raw "qemu-${qi}-version"
  [[ " ${accels} " == *" kvm "* ]] && qemu_kvm_capable="yes"
done
if [[ ${#qemu_found[@]} -eq 0 ]]; then
  record "qemu-system-aarch64 located" "NOT RUN" "no qemu-system-aarch64 on PATH, \$QEMU_BIN, ~/qemu-v*/bin or the Windows default install dir"
  record "KVM accelerator compiled into a local QEMU" "NOT RUN" "no QEMU binary found"
else
  record "qemu-system-aarch64 located" "PASS" "${#qemu_found[@]} binary/binaries, see raw/qemu-*-version.txt"
  if [[ "${qemu_kvm_capable}" == "yes" ]]; then
    record "KVM accelerator compiled into a local QEMU" "PASS" "'-accel help' lists kvm on at least one binary"
  elif [[ "${platform}" == "linux" ]]; then
    record "KVM accelerator compiled into a local QEMU" "FAIL" "'-accel help' never lists kvm (rebuild with --enable-kvm, cf. scripts/orin/build-qemu-on-orin.sh)"
  else
    record "KVM accelerator compiled into a local QEMU" "NOT APPLICABLE" "${platform}: local QEMU builds are TCG-only; KVM needs a Linux arm64 host"
  fi
fi

kvm_state=""
if [[ "${platform}" == "linux" ]]; then
  if [[ -e /dev/kvm ]]; then
    perms="$(stat -c '%A %U:%G' /dev/kvm 2>/dev/null || echo '?')"
    if [[ -r /dev/kvm && -w /dev/kvm ]]; then
      kvm_state="present, rw (${perms})"
      record "/dev/kvm present and accessible" "PASS" "${kvm_state}"
    else
      kvm_state="present, NOT rw for this user (${perms})"
      record "/dev/kvm present and accessible" "BLOCKED" "${kvm_state}; needs kvm group or sudo (bootstrap-orin-l4t.sh)"
    fi
  else
    kvm_state="absent"
    record "/dev/kvm present and accessible" "FAIL" "no /dev/kvm (cf. non-metal Graviton, ADR-002)"
  fi
  sh_to_raw host-kvm-modules "ls -d /sys/module/kvm* 2>/dev/null; lsmod 2>/dev/null | grep -iE 'kvm|vgic' || echo '(no kvm/vgic loadable modules; arm64 KVM is usually built-in — see /sys/module/kvm above)'" || true
  sh_to_raw host-dmesg-kvm-gic "dmesg 2>&1 | grep -iE 'kvm|vgic|gic|its|nisv|hyp mode|vhe|ipa size'" || true
  if raw_denied host-dmesg-kvm-gic; then
    record "Host dmesg KVM/GIC excerpt" "BLOCKED" "dmesg permission denied (kernel.dmesg_restrict) — run 'sudo dmesg' and grep -iE 'kvm|vgic|gic'"
  elif [[ "$(raw_lines host-dmesg-kvm-gic)" -gt 0 ]]; then
    record "Host dmesg KVM/GIC excerpt" "PASS" "$(raw_lines host-dmesg-kvm-gic) line(s) in raw/host-dmesg-kvm-gic.txt"
  else
    record "Host dmesg KVM/GIC excerpt" "NOT RUN" "dmesg readable but no matching lines (ring buffer rotated?) — try journalctl -k"
  fi
  if have journalctl; then
    # the unprivileged 'Hint: ... not seeing messages' notice is kept so raw_denied can see it
    sh_to_raw host-journalctl-kvm-gic "journalctl -k --no-pager 2>&1 | grep -iE 'kvm|vgic|gic|nisv|hyp mode|vhe|ipa size|not seeing messages|permission denied|no journal files'" || true
    if raw_denied host-journalctl-kvm-gic; then
      record "Host journalctl -k KVM/GIC excerpt" "BLOCKED" "journal not readable unprivileged (adm/systemd-journal group or sudo) — run 'sudo journalctl -k' and grep -iE 'kvm|vgic|gic'"
    elif [[ "$(raw_lines host-journalctl-kvm-gic)" -gt 0 ]]; then
      record "Host journalctl -k KVM/GIC excerpt" "PASS" "$(raw_lines host-journalctl-kvm-gic) line(s) in raw/host-journalctl-kvm-gic.txt"
    else
      record "Host journalctl -k KVM/GIC excerpt" "NOT RUN" "journal readable but no matching kernel lines (journal rotated or kernel messages not persisted)"
    fi
  else
    record "Host journalctl -k KVM/GIC excerpt" "NOT RUN" "journalctl not on PATH"
  fi
else
  kvm_state="not applicable on ${platform}"
  record "/dev/kvm present and accessible" "NOT APPLICABLE" "${platform} has no /dev/kvm; KVM reproduction needs the Orin or an arm64 metal instance"
  record "Host dmesg KVM/GIC excerpt" "NOT APPLICABLE" "no Linux kernel log on ${platform}"
  record "Host journalctl -k KVM/GIC excerpt" "NOT APPLICABLE" "no journald on ${platform}"
fi

# running QEMU processes; placeholders are '#' comment lines so they never count
if [[ "${platform}" == "linux" ]] && have ps; then
  sh_to_raw qemu-processes "ps -eo pid,etimes,args 2>/dev/null | grep -i '[q]emu-system' || echo '# none: no qemu-system process running'" || true
elif have tasklist; then
  sh_to_raw qemu-processes "tasklist 2>/dev/null | grep -i qemu || echo '# none: no qemu process running'" || true
else
  printf '# none: no process listing tool on this host\n' | write_raw qemu-processes
fi
qemu_running="$(grep -cE '^[^#[:space:]]' "${out_dir}/raw/qemu-processes.txt" || true)"

if [[ -n "${qemu_pid}" ]]; then
  if [[ "${platform}" == "linux" && -d "/proc/${qemu_pid}" ]]; then
    sh_to_raw "qemu-pid-${qemu_pid}" "echo '--- cmdline'; tr '\\0' ' ' </proc/${qemu_pid}/cmdline; echo; echo '--- exe'; readlink /proc/${qemu_pid}/exe; echo '--- status'; grep -E '^(Name|State|Threads|VmRSS|VmSize)' /proc/${qemu_pid}/status; echo '--- fds to /dev/kvm'; ls -l /proc/${qemu_pid}/fd 2>&1 | grep -c '/dev/kvm'; echo '--- maps (count)'; wc -l < /proc/${qemu_pid}/maps" || true
    if raw_denied "qemu-pid-${qemu_pid}"; then
      record "Running QEMU /proc inspection (--qemu-pid)" "BLOCKED" "permission denied on /proc/${qemu_pid}; re-run with sudo or as the QEMU owner"
    else
      record "Running QEMU /proc inspection (--qemu-pid)" "PASS" "raw/qemu-pid-${qemu_pid}.txt"
    fi
  else
    record "Running QEMU /proc inspection (--qemu-pid)" "BLOCKED" "/proc/${qemu_pid} not available on ${platform}"
  fi
else
  record "Running QEMU /proc inspection (--qemu-pid)" "NOT RUN" "--qemu-pid not given; ${qemu_running} qemu process line(s) listed in raw/qemu-processes.txt"
fi

# toolchain detection (used later; reported in Environment)
objdump_bin="$(find_tool ntoaarch64-objdump aarch64-unknown-nto-qnx8.0.0-objdump aarch64-linux-gnu-objdump aarch64-none-elf-objdump aarch64-elf-objdump || true)"
if [[ -z "${objdump_bin}" ]] && have objdump && objdump -i 2>/dev/null | grep -q aarch64; then objdump_bin="$(command -v objdump)"; fi
if [[ -z "${objdump_bin}" ]] && have llvm-objdump; then objdump_bin="$(command -v llvm-objdump)"; fi
nm_bin="$(find_tool ntoaarch64-nm aarch64-unknown-nto-qnx8.0.0-nm aarch64-linux-gnu-nm aarch64-none-elf-nm || true)"
addr2line_bin="$(find_tool ntoaarch64-addr2line aarch64-unknown-nto-qnx8.0.0-addr2line aarch64-linux-gnu-addr2line aarch64-none-elf-addr2line || true)"
readelf_bin="$(find_tool ntoaarch64-readelf aarch64-unknown-nto-qnx8.0.0-readelf aarch64-linux-gnu-readelf readelf || true)"
dumpifs_bin="$(find_tool dumpifs || true)"
dtc_bin="$(command -v dtc 2>/dev/null || true)"
fdtdump_bin="$(command -v fdtdump 2>/dev/null || true)"
fdtget_bin="$(command -v fdtget 2>/dev/null || true)"
socat_bin="$(command -v socat 2>/dev/null || true)"

tool_row() { printf '| %s | %s |\n' "$1" "${2:-not found}"; }
{
  echo "| tool | path |"; echo "|---|---|"
  tool_row "aarch64 objdump" "${objdump_bin}"
  tool_row "aarch64 nm" "${nm_bin}"
  tool_row "aarch64 addr2line" "${addr2line_bin}"
  tool_row "aarch64 readelf" "${readelf_bin}"
  tool_row "dumpifs" "${dumpifs_bin}"
  tool_row "dtc" "${dtc_bin}"
  tool_row "fdtdump" "${fdtdump_bin}"
  tool_row "fdtget" "${fdtget_bin}"
  tool_row "python" "${python_bin:+$(command -v "${python_bin}")}"
  tool_row "socat" "${socat_bin}"
  tool_row "git" "$(command -v git 2>/dev/null || true)"
  tool_row "sha256sum" "$(command -v sha256sum 2>/dev/null || true)"
  tool_row "timeout" "$(command -v timeout 2>/dev/null || true)"
} > "${work}/tools.md"

# ================================================================ 2. repository
section "Repository revision"
git_head="(git unavailable)"; git_desc=""; git_branch=""
if have git && git -C "${repo_root}" rev-parse HEAD >/dev/null 2>&1; then
  git_head="$(git -C "${repo_root}" rev-parse HEAD)"
  git_desc="$(git -C "${repo_root}" describe --always --dirty --tags 2>/dev/null || true)"
  git_branch="$(git -C "${repo_root}" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  sh_to_raw git-state "cd '${repo_root}' && echo 'HEAD: '\$(git rev-parse HEAD) && echo 'branch: '\$(git rev-parse --abbrev-ref HEAD) && echo 'describe: '\$(git describe --always --dirty --tags) && echo '--- status --short' && git status --short && echo '--- last 8 commits (no author fields on purpose)' && git log -8 --date=short --format='%h %ad %s'" || true
  record "Git repository state captured" "PASS" "HEAD ${git_head:0:12}${git_desc:+ (${git_desc})}"
else
  record "Git repository state captured" "NOT RUN" "git not available or not a repository"
fi

recorded_ifs_sha=""
a1_log="${log_dir}/aws-a1-metal-kvm-nisv-repro.log"
[[ -f "${a1_log}" ]] && recorded_ifs_sha="$(grep -oE 'ifs\.bin=[0-9a-f]{64}' "${a1_log}" | head -1 | cut -d= -f2 || true)"
local_ifs="${repo_root}/qnx-safety-vm/output/ifs.bin"
local_ifs_sha=""
if [[ -f "${local_ifs}" ]] && have sha256sum; then
  local_ifs_sha="$(sha256sum "${local_ifs}" | cut -d' ' -f1)"
  {
    echo "local ifs.bin (gitignored, NOT copied): size $(stat -c %s "${local_ifs}" 2>/dev/null || wc -c <"${local_ifs}") bytes"
    echo "sha256 local:    ${local_ifs_sha}"
    echo "sha256 recorded: ${recorded_ifs_sha:-(none found in a1.metal log header)}"
    [[ -f "${repo_root}/qnx-safety-vm/output/SHA256SUMS" ]] && { echo "--- output/SHA256SUMS (hashes only)"; cat "${repo_root}/qnx-safety-vm/output/SHA256SUMS"; }
    echo "note: disk-qemu is a mutable raw disk and drifts on every non--snapshot boot; only ifs.bin is expected to stay byte-identical"
  } | write_raw image-hashes
  if [[ -n "${recorded_ifs_sha}" && "${recorded_ifs_sha}" == "${local_ifs_sha}" ]]; then
    record "Local ifs.bin sha256 == hash recorded for the hung KVM boots" "PASS" "${local_ifs_sha:0:16}... matches the a1.metal log header (same image that hung on Orin and a1.metal)"
  elif [[ -n "${recorded_ifs_sha}" ]]; then
    record "Local ifs.bin sha256 == hash recorded for the hung KVM boots" "FAIL" "local ${local_ifs_sha:0:16}... != recorded ${recorded_ifs_sha:0:16}... (local image rebuilt since; any new KVM run must re-record its hash)"
  else
    record "Local ifs.bin sha256 == hash recorded for the hung KVM boots" "NOT RUN" "no recorded hash found (a1.metal log missing from ${log_dir})"
  fi
else
  record "Local ifs.bin sha256 == hash recorded for the hung KVM boots" "NOT RUN" "no local qnx-safety-vm/output/ifs.bin (or no sha256sum) on this host"
fi

# ================================================================ 3. evidence
section "Evidence found"
grep_terms=("KVM_EXIT_ARM_NISV" "kvm_guest_fault" "0x92000045" "ISV=0" "VBAR_EL1" "str w3" "IPRIORITY" "0x420" "b8004403" "fno-auto-inc-dec" "gic_v3.c" "FOUND GICv3 ITS" "a1.metal" "PE is not awake")
grep_counts=()
: > "${work}/grep-all"
if have git && git -C "${repo_root}" rev-parse HEAD >/dev/null 2>&1; then
  for t in "${grep_terms[@]}"; do
    c="$({ git -C "${repo_root}" grep -n -I -F -e "${t}" -- docs scripts logs README.md CLAUDE.md AGENTS.md ipc-test skills 2>/dev/null || true; } | tee -a "${work}/grep-all" | wc -l | tr -d ' ')"
    grep_counts+=("${t}|${c}")
  done
  sort -u "${work}/grep-all" | write_raw repo-evidence-grep
  hits="$(wc -l <"${out_dir}/raw/repo-evidence-grep.txt" | tr -d ' ')"
  if [[ "${hits}" -gt 0 ]]; then
    record "Repo evidence grep (key terms present)" "PASS" "${hits} matching line(s) across ${#grep_terms[@]} terms, raw/repo-evidence-grep.txt"
  else
    record "Repo evidence grep (key terms present)" "FAIL" "none of the key terms found — wrong checkout?"
  fi
else
  record "Repo evidence grep (key terms present)" "NOT RUN" "git grep unavailable"
fi

# boot-log classification
log_rows=()
a1_class=""; tcg_boot_ok=0; tcg_hang=0; kvm_hang=0
classify_log() {
  local f="$1" base mode its awake complete nisv exitc class topic
  base="$(basename "${f}")"
  case "${base}" in *qhv*) topic="EXCLUDED (QHV/TCG leg, different defect)";; *) topic="in-topic";; esac
  its="$(grep -c 'FOUND GICv3 ITS' "${f}" 2>/dev/null || true)"
  awake="$(grep -c 'PE is not awake' "${f}" 2>/dev/null || true)"
  complete="$(grep -c 'Startup complete' "${f}" 2>/dev/null || true)"
  # '#' header/comment lines are prose: a comment that names NISV is not fault data
  nisv="$({ grep -vE '^[[:space:]]*#' "${f}" 2>/dev/null || true; } | grep -cE 'kvm_guest_fault|hsr=0x[0-9a-fA-F]+|esr=0x[0-9a-fA-F]+|KVM_EXIT_ARM_NISV|ISV=0|Data abort exception with no valid ISS' || true)"
  exitc="$(grep -oE 'QEMU_EXIT=[0-9]+' "${f}" 2>/dev/null | head -1 || true)"
  # prefer tokens on command-looking lines (the header's qemu invocation or its
  # continuation lines) over prose mentions of the other accelerator
  # '[^-]-enable-kvm' rejects the configure flag '--enable-kvm' seen in prose
  local accel_re='(-accel tcg|[^-]-enable-kvm|accel=kvm|-accel kvm)'
  mode="$(grep -E 'qemu-system-aarch64|-machine |^#[[:space:]]+-' "${f}" 2>/dev/null | grep -m1 -oE "${accel_re}" | head -1 || true)"
  [[ -z "${mode}" ]] && mode="$(grep -m1 -oE "${accel_re}" "${f}" 2>/dev/null | head -1 || true)"
  case "${mode}" in
    *"-accel tcg"*) mode="tcg";;
    "") case "${base}" in *tcg*) mode="tcg (from filename)";; *kvm*) mode="kvm (from filename)";; *) mode="?";; esac;;
    *) mode="kvm";;
  esac
  if [[ "${complete}" -gt 0 ]]; then class="boots (Startup complete)"
  elif [[ "${its}" -gt 0 && "${awake}" -eq 0 ]]; then class="HANG-AFTER-ITS-DISCOVERY signature (no 'PE is not awake', no 'Startup complete')"
  elif [[ "${its}" -gt 0 ]]; then class="partial (past ITS discovery and PE wake; no 'Startup complete' in capture)"
  else class="no startup markers"; fi
  log_rows+=("${base}${sep}${topic}${sep}${mode}${sep}${class}${sep}$([[ "${nisv}" -gt 0 ]] && echo "yes (${nisv} line(s))" || echo "no — symptom-only")${sep}${exitc:-—}")
  if [[ "${topic}" == "in-topic" ]]; then
    if [[ "${base}" == "aws-a1-metal-kvm-nisv-repro.log" ]]; then a1_class="${class}"; fi
    if [[ "${mode}" == tcg* && "${complete}" -gt 0 ]]; then tcg_boot_ok=$((tcg_boot_ok + 1)); fi
    if [[ "${mode}" == tcg* && "${class}" == HANG* ]]; then tcg_hang=$((tcg_hang + 1)); fi
    if [[ "${mode}" == kvm* && "${class}" == HANG* ]]; then kvm_hang=$((kvm_hang + 1)); fi
  fi
}
if [[ -d "${log_dir}" ]]; then
  for f in "${log_dir}"/*.log; do [[ -f "${f}" ]] && classify_log "${f}"; done
fi
for f in ${boot_logs[@]+"${boot_logs[@]}"}; do
  if [[ -f "${f}" ]]; then classify_log "${f}"; else log_rows+=("$(basename "${f}")${sep}—${sep}—${sep}FILE NOT FOUND${sep}—${sep}—"); fi
done
{
  echo "file|topic|accel|classification|ESR/exit-reason tokens (non-comment lines)|QEMU_EXIT"
  for r in ${log_rows[@]+"${log_rows[@]}"}; do echo "${r//${sep}/|}"; done
} | write_raw boot-log-classification

if [[ -z "${a1_class}" ]]; then
  record "a1.metal KVM serial log shows the hang signature" "NOT RUN" "aws-a1-metal-kvm-nisv-repro.log not found in ${log_dir}"
elif [[ "${a1_class}" == HANG* ]]; then
  record "a1.metal KVM serial log shows the hang signature" "PASS" "boot FAIL with 'FOUND GICv3 ITS' then silence, QEMU_EXIT=124 (timeout); NO ISV/exit-reason data in that log — NISV there is inferred"
else
  record "a1.metal KVM serial log shows the hang signature" "FAIL" "classified as: ${a1_class}"
fi
if [[ "${tcg_hang}" -gt 0 ]]; then
  record "TCG control logs (in-topic) reach 'Startup complete'" "FAIL" "${tcg_hang} TCG log(s) carry the hang signature — TCG is no longer a clean control"
elif [[ "${tcg_boot_ok}" -gt 0 ]]; then
  record "TCG control logs (in-topic) reach 'Startup complete'" "PASS" "${tcg_boot_ok} TCG log(s) boot the same IFS; isolates the hang to KVM acceleration"
else
  record "TCG control logs (in-topic) reach 'Startup complete'" "NOT RUN" "no in-topic TCG boot log with 'Startup complete' found"
fi

# ================================================================ 4. registers
section "Registers"
esr_name_of_ec() {
  case "$1" in
    0x0) echo "Unknown reason";; 0x1) echo "WFI/WFE trapped";; 0x3) echo "MCR/MRC (cp15) trapped";;
    0x4) echo "MCRR/MRRC (cp15) trapped";; 0x5) echo "MCR/MRC (cp14) trapped";; 0x6) echo "LDC/STC trapped";;
    0x7) echo "SVE/SIMD/FP access trapped";; 0xc) echo "MRRC (cp14) trapped";; 0xe) echo "Illegal Execution state";;
    0x11) echo "SVC (AArch32)";; 0x12) echo "HVC (AArch32)";; 0x13) echo "SMC (AArch32)";;
    0x15) echo "SVC (AArch64)";; 0x16) echo "HVC (AArch64)";; 0x17) echo "SMC (AArch64)";;
    0x18) echo "MSR/MRS/System instruction trapped";; 0x19) echo "SVE access trapped";;
    0x20) echo "Instruction Abort from a lower EL";; 0x21) echo "Instruction Abort, same EL";;
    0x22) echo "PC alignment fault";; 0x24) echo "Data Abort from a lower EL";; 0x25) echo "Data Abort, same EL";;
    0x26) echo "SP alignment fault";; 0x28) echo "FP exception (AArch32)";; 0x2c) echo "FP exception (AArch64)";;
    0x2f) echo "SError";; 0x30) echo "Breakpoint, lower EL";; 0x31) echo "Breakpoint, same EL";;
    0x32) echo "Software step, lower EL";; 0x33) echo "Software step, same EL";; 0x34) echo "Watchpoint, lower EL";;
    0x35) echo "Watchpoint, same EL";; 0x38) echo "BKPT (AArch32)";; 0x3c) echo "BRK (AArch64)";;
    *) echo "(EC not in this table)";;
  esac
}
dfsc_name() {
  local v="$1" lvl=$(( v & 3 ))
  case $(( v >> 2 )) in
    0) echo "Address size fault, level ${lvl}";;
    1) echo "Translation fault, level ${lvl}";;
    2) echo "Access flag fault, level ${lvl}";;
    3) echo "Permission fault, level ${lvl}";;
    *) case "$(printf '0x%02x' "${v}")" in
         0x10) echo "Synchronous External abort, not on translation table walk";;
         0x11) echo "Synchronous Tag Check Fault";;
         0x14|0x15|0x16|0x17) echo "Synchronous External abort on translation table walk, level ${lvl}";;
         0x18) echo "Synchronous parity/ECC error, not on table walk";;
         0x1c|0x1d|0x1e|0x1f) echo "Synchronous parity/ECC error on table walk, level ${lvl}";;
         0x21) echo "Alignment fault";;
         0x30) echo "TLB conflict abort";;
         0x31) echo "Unsupported atomic hardware update fault";;
         0x34) echo "IMPLEMENTATION DEFINED (Lockdown)";;
         0x35) echo "IMPLEMENTATION DEFINED (Unsupported Exclusive or Atomic access)";;
         *) echo "(DFSC not in this table)";;
       esac;;
  esac
}
# decode_esr HEX -> markdown on stdout; exports esr_ec esr_il esr_isv esr_wnr esr_dfsc
decode_esr() {
  local v; v="$(to_dec "$1")"
  esr_ec=$(( (v >> 26) & 0x3F )); esr_il=$(( (v >> 25) & 1 )); local iss=$(( v & 0x1FFFFFF ))
  esr_isv=-1; esr_wnr=-1; esr_dfsc=-1; esr_s1ptw=-1; esr_fnv=-1
  echo "- value: $(hex "${v}")"
  echo "- EC [31:26] = $(printf '0x%02x' "${esr_ec}") — $(esr_name_of_ec "$(printf '0x%x' "${esr_ec}")")"
  echo "- IL [25] = ${esr_il} ($([[ ${esr_il} -eq 1 ]] && echo '32-bit instruction' || echo '16-bit instruction / not applicable'))"
  echo "- ISS [24:0] = $(printf '0x%07x' "${iss}")"
  if [[ ${esr_ec} -eq 0x24 || ${esr_ec} -eq 0x25 ]]; then
    esr_isv=$(( (iss >> 24) & 1 )); esr_wnr=$(( (iss >> 6) & 1 )); esr_dfsc=$(( iss & 0x3F ))
    local set=$(( (iss >> 11) & 3 )) ea=$(( (iss >> 9) & 1 )) cm=$(( (iss >> 8) & 1 )) vncr=$(( (iss >> 13) & 1 ))
    esr_fnv=$(( (iss >> 10) & 1 )); esr_s1ptw=$(( (iss >> 7) & 1 ))
    echo "- Data Abort ISS:"
    echo "  - ISV [24] = ${esr_isv} — $([[ ${esr_isv} -eq 1 ]] && echo 'instruction syndrome VALID (SAS/SSE/SRT/SF/AR below are meaningful)' || echo 'instruction syndrome NOT VALID: SAS/SSE/SRT/SF/AR are RES0 and are NOT decoded here')"
    if [[ ${esr_isv} -eq 1 ]]; then
      local sas=$(( (iss >> 22) & 3 )) sse=$(( (iss >> 21) & 1 )) srt=$(( (iss >> 16) & 0x1F )) sf=$(( (iss >> 15) & 1 )) ar=$(( (iss >> 14) & 1 ))
      local sas_name; case ${sas} in 0) sas_name=byte;; 1) sas_name=halfword;; 2) sas_name=word;; 3) sas_name=doubleword;; esac
      echo "  - SAS [23:22] = ${sas} (${sas_name}), SSE [21] = ${sse} ($([[ ${sse} -eq 1 ]] && echo 'sign-extended load' || echo 'no sign extension')), SRT [20:16] = ${srt} (register), SF [15] = ${sf} ($([[ ${sf} -eq 1 ]] && echo '64-bit Xt' || echo '32-bit Wt')), AR [14] = ${ar} ($([[ ${ar} -eq 1 ]] && echo 'acquire/release semantics' || echo 'plain access'))"
    fi
    local set_txt
    case "$(printf '0x%02x' "${esr_dfsc}")" in
      # SET is defined for the synchronous External abort / parity-ECC DFSC
      # group (0b01xxxx except the Tag Check Fault 0x11), FEAT_RAS
      0x10|0x14|0x15|0x16|0x17|0x18|0x1c|0x1d|0x1e|0x1f)
        local set_name; case ${set} in 0) set_name='recoverable (UER)';; 2) set_name='uncontainable (UC)';; 3) set_name='restartable (UEO)';; *) set_name='reserved';; esac
        set_txt="SET [12:11] = ${set} (${set_name}; FEAT_RAS)";;
      0x35) set_txt="LST [12:11] = ${set} (load/store type of the unsupported exclusive/atomic access; FEAT_LS64)";;
      *)    set_txt="bits [12:11] = ${set} (RES0 for this DFSC)";;
    esac
    echo "  - VNCR [13] = ${vncr}, ${set_txt}, FnV [10] = ${esr_fnv} ($([[ ${esr_fnv} -eq 1 ]] && echo 'FAR NOT valid' || echo 'FAR valid')), EA [9] = ${ea}, CM [8] = ${cm}, S1PTW [7] = ${esr_s1ptw}"
    echo "  - WnR [6] = ${esr_wnr} ($([[ ${esr_wnr} -eq 1 ]] && echo 'write' || echo 'read'))"
    echo "  - DFSC [5:0] = $(printf '0x%02x' "${esr_dfsc}") — $(dfsc_name "${esr_dfsc}")"
    if [[ ${esr_isv} -eq 0 ]]; then
      echo "  - reading: ISV=0 means the hardware did not describe the access (this is what the KVM API calls a 'NISV' Data Abort). ISV=0 by itself does NOT prove the IPA is GIC MMIO — that needs HPFAR/IPA (see Candidate IPA) or the disassembled instruction."
    fi
  else
    echo "- not a Data Abort: no DFSC/WnR/ISV decode applies"
  fi
}

# decode_esr must run in this shell (not $(...)) so the esr_* globals survive
decode_esr 0x92000045 > "${work}/esr-selftest.md"
esr_selftest_md="$(cat "${work}/esr-selftest.md")"
if [[ ${esr_ec} -eq 0x24 && ${esr_il} -eq 1 && ${esr_isv} -eq 0 && ${esr_wnr} -eq 1 && ${esr_dfsc} -eq 0x05 ]]; then
  record "ESR decoder self-test (0x92000045 -> EC=0x24, IL=1, ISV=0, WnR=1, DFSC=0x05)" "PASS" "decoder reproduces the expected fields from the repo's documented hsr value"
else
  record "ESR decoder self-test (0x92000045 -> EC=0x24, IL=1, ISV=0, WnR=1, DFSC=0x05)" "FAIL" "got EC=$(hex ${esr_ec}) IL=${esr_il} ISV=${esr_isv} WnR=${esr_wnr} DFSC=$(hex ${esr_dfsc})"
fi
selftest_ec=${esr_ec}; selftest_isv=${esr_isv}

user_esr_md=""; user_esr_isv=-1; user_esr_ec=-1; user_esr_dfsc=-1; user_esr_s1ptw=-1; user_esr_fnv=-1
if [[ -n "${esr_value}" ]]; then
  decode_esr "${esr_value}" > "${work}/esr-user.md"
  user_esr_md="$(cat "${work}/esr-user.md")"
  user_esr_isv=${esr_isv}; user_esr_ec=${esr_ec}; user_esr_dfsc=${esr_dfsc}; user_esr_s1ptw=${esr_s1ptw}; user_esr_fnv=${esr_fnv}
  note=""
  [[ "$(to_dec "${esr_value}")" -eq "$(to_dec 0x92000045)" ]] && note="; value is identical to the one documented in docs/orin-port.md — unless you captured it yourself this is a re-decode of prose, not a new observation"
  record "Supplied --esr decoded" "PASS" "EC=$(hex ${esr_ec}) ISV=${esr_isv} WnR=${esr_wnr} DFSC=$(hex ${esr_dfsc})${note}"
else
  record "Supplied --esr decoded" "NOT RUN" "--esr not given (pass the kvm_guest_fault hsr= value from a fresh trace)"
fi
printf '%s\n\n%s\n' "--- self-test 0x92000045" "${esr_selftest_md}" | write_raw esr-decode
[[ -n "${user_esr_md}" ]] && printf '\n--- supplied --esr %s\n%s\n' "${esr_value}" "${user_esr_md}" | redact >> "${out_dir}/raw/esr-decode.txt"

# ================================================================ 5. candidate IPA
section "Candidate IPA"
observed_ipa=""; ipa_md=()
if [[ -n "${ipa_value}" ]]; then
  observed_ipa="$(to_dec "${ipa_value}")"
  ipa_md+=("- --ipa supplied directly: $(hex "${observed_ipa}") (as printed by the kvm_guest_fault tracepoint's ipa= field; treated as observed)")
fi
if [[ -n "${hpfar_value}" ]]; then
  hp="$(to_dec "${hpfar_value}")"
  # HPFAR_EL2.FIPA is bits [43:4] = IPA[51:12], in 4 KiB units regardless of
  # translation granule; [63] is NS, [62:44] RES0. The page offset is always
  # the low 12 bits of FAR (Linux KVM: fault_ipa | hxfar & 0xFFF).
  hp_hi=$(( (hp >> 44) & 0xFFFFF ))
  fipa=$(( (hp & 0x00000FFFFFFFFFF0) << 8 ))
  far_dec=""
  if [[ -n "${far_value}" ]]; then far_dec="$(to_dec "${far_value}")"; off=$(( far_dec & 0xFFF )); else off=0; fi
  composed=$(( fipa | off ))
  ipa_md+=("- inputs: HPFAR_EL2 = $(hex "${hp}")${far_value:+, FAR_EL2/HXFAR = $(hex "${far_dec}")}")
  if [[ ${hp_hi} -ne 0 ]]; then
    ipa_md+=("- NOTE: HPFAR_EL2[63:44] is non-zero ($(hex "${hp_hi}") in those bits): NS (bit 63) / RES0 bits are ignored by the composition — check the source of this value")
  fi
  ipa_md+=("- formula: FIPA = HPFAR_EL2[43:4] = IPA[51:12]; IPA = (FIPA << 12) | (FAR_EL2 & 0xFFF), equivalently ((HPFAR & 0xFFFFFFFFFF0) << 8) | (FAR & 0xFFF). The 12-bit page offset is fixed by the architecture (HPFAR is defined in 4 KiB units) whatever the translation granule; Linux KVM composes the same way (kvm_vcpu_get_fault_ipa | hxfar & 0xFFF)")
  ipa_md+=("- FIPA<<12 = $(hex "${fipa}"), page offset (FAR & 0xFFF) = $(hex "${off}")$([[ -n "${far_value}" ]] || echo ' (no --far: offset assumed 0, IPA is page-granular only)')")
  ipa_md+=("- composed IPA = $(hex "${composed}")")
  ipa_md+=("- --granule ${granule}: used only as a FAR-vs-HPFAR consistency check (matrix row below); it does not enter the IPA")
  if [[ -n "${observed_ipa}" && "${observed_ipa}" -ne "${composed}" ]]; then
    ipa_md+=("- WARNING: --ipa ($(hex "${observed_ipa}")) and the composed value differ; --ipa is used for the range comparison")
  fi
  [[ -z "${observed_ipa}" ]] && observed_ipa="${composed}"
  # HPFAR_EL2 holds a defined IPA only for stage-2 translation / access-flag /
  # permission faults or a stage-1 walk fault (S1PTW); FnV=1 invalidates FAR
  hpfar_valid="unchecked (no --esr: pass the hsr from the same fault to validate)"
  if [[ ${user_esr_ec} -eq 0x24 || ${user_esr_ec} -eq 0x25 ]]; then
    dfsc_txt="$(printf '0x%02x' "${user_esr_dfsc}")"
    if [[ ${user_esr_fnv} -eq 1 ]]; then
      hpfar_valid="NO — FnV=1: FAR_EL2 is not valid, so the page offset above is untrustworthy"
    elif (( user_esr_dfsc >= 0x04 && user_esr_dfsc <= 0x0f )) || [[ ${user_esr_s1ptw} -eq 1 ]]; then
      s1ptw_txt=""; [[ ${user_esr_s1ptw} -eq 1 ]] && s1ptw_txt=" (S1PTW=1: on a stage-1 table walk)"
      hpfar_valid="yes — DFSC ${dfsc_txt} is a stage-2 translation/access-flag/permission fault${s1ptw_txt}"
    else
      hpfar_valid="NO — DFSC ${dfsc_txt} with S1PTW=0 is not a stage-2 translation/access-flag/permission fault; HPFAR_EL2 is UNKNOWN for this abort class"
    fi
  elif [[ ${user_esr_ec} -ge 0 ]]; then
    hpfar_valid="NO — --esr EC=$(hex "${user_esr_ec}") is not a Data Abort, HPFAR_EL2 is not defined for it"
  fi
  ipa_md+=("- HPFAR_EL2 architecturally valid for the supplied --esr: ${hpfar_valid}")
  if [[ "${hpfar_valid}" == NO* ]]; then
    ipa_md+=("- NOTE: the composed value is NOT trustworthy for this --esr; it is still shown and range-compared below, but treat any match as unproven")
    record "Candidate IPA composed from --hpfar/--far" "FAIL" "composed $(hex "${composed}") but HPFAR not architecturally valid for this DFSC/FnV — composed value is not trustworthy"
  else
    record "Candidate IPA composed from --hpfar/--far" "PASS" "IPA $(hex "${composed}") = (HPFAR[43:4] << 12) | (FAR & 0xFFF); HPFAR validity vs --esr: ${hpfar_valid%% —*}"
  fi
  # with a 16K/64K stage-1 granule VA[top:12] lies inside the page offset and
  # must equal the HPFAR-derived IPA bits if both values come from one fault
  case "${granule}" in 16K) top_bit=13;; 64K) top_bit=15;; *) top_bit=11;; esac
  gran_row="FAR[${top_bit}:12] agrees with HPFAR-derived IPA bits (--granule ${granule})"
  if [[ ${granule_bytes} -eq 4096 ]]; then
    record "FAR-vs-HPFAR consistency check (--granule 4K)" "NOT APPLICABLE" "4 KiB granule: FAR and HPFAR share no bits above the 12-bit page offset"
  elif [[ -z "${far_value}" ]]; then
    record "${gran_row}" "NOT RUN" "--far not given"
  else
    far_bits=$(( (far_dec & (granule_bytes - 1)) >> 12 )); fipa_bits=$(( (fipa >> 12) & ((granule_bytes >> 12) - 1) ))
    if [[ ${far_bits} -eq ${fipa_bits} ]]; then
      record "${gran_row}" "PASS" "both $(hex "${far_bits}"); consistent with one fault under a ${granule} stage-1 granule"
    else
      record "${gran_row}" "FAIL" "FAR bits $(hex "${far_bits}") != HPFAR-derived $(hex "${fipa_bits}") — inputs are not from the same fault, or the stage-1 granule is not ${granule}; the IPA above still uses only FAR[11:0]"
    fi
  fi
elif [[ -n "${far_value}" ]]; then
  ipa_md+=("- only --far given: FAR_EL2/HXFAR holds the guest VIRTUAL address ($(hex "$(to_dec "${far_value}")")), not an IPA; without HPFAR_EL2 (or --ipa) no IPA can be composed")
  record "Candidate IPA composed from --hpfar/--far" "NOT RUN" "--far without --hpfar: FAR is a VA, not an IPA"
elif [[ -n "${observed_ipa}" ]]; then
  record "Candidate IPA composed from --hpfar/--far" "NOT RUN" "--ipa supplied directly instead"
else
  ipa_md+=("- no --hpfar/--far/--ipa supplied: no observed IPA. The repo never recorded one either (docs/orin-port.md quotes hsr and the exit reason only).")
  record "Candidate IPA composed from --hpfar/--far" "NOT RUN" "no --hpfar/--far/--ipa given; the repo holds no recorded HPFAR/IPA to fall back on"
fi

# ================================================================ 6. DTB + MMIO ranges
section "DTB analysis / MMIO range comparison"
range_labels=(); range_bases=(); range_sizes=(); range_srcs=()
add_range() { range_labels+=("$1"); range_bases+=("$2"); range_sizes+=("$3"); range_srcs+=("$4"); }

dtb_status=""; dtb_detail=""
if [[ -n "${dtb_file}" ]]; then
  if [[ ! -f "${dtb_file}" ]]; then
    dtb_status="BLOCKED"; dtb_detail="--dtb file not found: ${dtb_file}"
  else
    dtb_sha="$(sha256sum "${dtb_file}" 2>/dev/null | cut -d' ' -f1 || echo '?')"
    magic="$(od -An -tx1 -N4 "${dtb_file}" 2>/dev/null | tr -d ' \n')"
    if [[ "${magic}" != "d00dfeed" ]]; then
      dtb_status="FAIL"; dtb_detail="not an FDT (magic ${magic:-?} != d00dfeed)"
    else
      any=0
      # full decompilations stay in $work; only grepped excerpts reach results/
      dts_grep='interrupt-controller|redistributor|its@|gic|timer|psci|cpus|cpu@|compatible|\breg\b|method|enable-method|interrupts'
      if [[ -n "${dtc_bin}" ]]; then
        if run_with_timeout "${dtc_bin}" -I dtb -O dts -q "${dtb_file}" >"${work}/dtb.dts" 2>&1; then
          any=1
          sh_to_raw dtb-dts-grep "grep -nE '${dts_grep}' '${work}/dtb.dts'" || true
        else
          write_raw dtb-dts-grep <"${work}/dtb.dts"
        fi
      fi
      if [[ -n "${fdtdump_bin}" ]]; then
        if run_with_timeout "${fdtdump_bin}" "${dtb_file}" >"${work}/dtb.fdtdump" 2>&1; then
          any=1
          sh_to_raw dtb-fdtdump-grep "grep -nE '${dts_grep}' '${work}/dtb.fdtdump'" || true
        else
          write_raw dtb-fdtdump-grep <"${work}/dtb.fdtdump"
        fi
      fi
      if [[ -n "${fdtget_bin}" ]]; then
        # paths travel as positional parameters, never interpolated into the
        # command string; counts as parsed only if the root node is readable
        # (individual nodes may legitimately be absent, e.g. its=off)
        if sh_to_raw dtb-fdtget '"$1" -l "$2" / >/dev/null 2>&1 || exit 1; for n in / /intc@8000000 /intc@8000000/its@8080000 /timer /psci /cpus; do echo "--- $n"; "$1" -l "$2" "$n" 2>&1; "$1" -p "$2" "$n" 2>&1; done; exit 0' "${fdtget_bin}" "${dtb_file}"; then any=1; fi
      fi
      if [[ -n "${python_bin}" ]]; then
        # Minimal FDT walker: prints interrupt/GIC/timer/PSCI/cpu nodes and
        # machine-readable RANGE lines. No ranges-translation beyond identity.
        cat > "${work}/fdt.py" <<'PY'
import struct, sys, re
data = open(sys.argv[1], 'rb').read()
if len(data) < 40 or struct.unpack('>I', data[:4])[0] != 0xd00dfeed:
    print('NOT-FDT'); sys.exit(2)
(_, totalsize, off_struct, off_strings, _, version, _, _, _, _) = struct.unpack('>10I', data[:40])
u32 = lambda p: struct.unpack('>I', data[p:p+4])[0]
def cstr(o):
    return data[o:data.index(b'\0', o)].decode('ascii', 'replace')
pos = off_struct; stack = []; nodes = []
while True:
    tok = u32(pos); pos += 4
    if tok == 1:
        end = data.index(b'\0', pos); name = data[pos:end].decode('ascii', 'replace'); pos = (end + 1 + 3) & ~3
        parent = stack[-1] if stack else None
        node = {'name': name, 'props': {}, 'parent': parent,
                'path': ('/' if parent is None else (parent['path'].rstrip('/') + '/' + name))}
        stack.append(node); nodes.append(node)
    elif tok == 2: stack.pop()
    elif tok == 3:
        ln, noff = u32(pos), u32(pos + 4); pos += 8
        stack[-1]['props'][cstr(off_strings + noff)] = data[pos:pos+ln]; pos = (pos + ln + 3) & ~3
    elif tok == 4: pass
    elif tok == 9: break
    else: print('NOT-FDT: bad token', tok); sys.exit(2)
def cells(n, key, default):
    while n is not None:
        if key in n['props']: return struct.unpack('>I', n['props'][key])[0]
        n = n['parent']
    return default
def strs(v): return [s for s in v.decode('ascii', 'replace').split('\0') if s]
def words(v): return list(struct.unpack('>%dI' % (len(v) // 4), v[:len(v) // 4 * 4]))
def reg_pairs(n):
    v = n['props'].get('reg')
    if v is None: return []
    p = n['parent']; ac = cells(p, '#address-cells', 2) if p else 2; sc = cells(p, '#size-cells', 1) if p else 1
    w = words(v); out = []; step = ac + sc
    for i in range(0, len(w) - step + 1, step):
        base = 0
        for c in w[i:i+ac]: base = (base << 32) | c
        size = 0
        for c in w[i+ac:i+step]: size = (size << 32) | c
        out.append((base, size))
    return out
print('FDT version %d, totalsize %d, %d nodes' % (version, totalsize, len(nodes)))
pat = re.compile(r'^(intc|interrupt-controller|gic|its|redistributor|timer|psci|cpus|cpu@|memory|pl011|uart|virtio_mmio|apb-pclk|pmu)', re.I)
for n in nodes:
    p = n['props']
    comp = strs(p['compatible']) if 'compatible' in p else []
    interesting = pat.match(n['name']) or 'interrupt-controller' in p or any('gic' in c for c in comp)
    if not interesting: continue
    print('NODE', n['path'])
    if comp: print('  compatible =', ', '.join(comp))
    if 'interrupt-controller' in p: print('  interrupt-controller (present); #interrupt-cells =', words(p['#interrupt-cells'])[0] if '#interrupt-cells' in p else '?')
    if 'ranges' in p and len(p['ranges']) > 0: print('  ranges = (non-empty: reg below is bus-relative, translation NOT applied)')
    for (b, s) in reg_pairs(n): print('  reg = base 0x%x size 0x%x' % (b, s))
    for k in ('#redistributor-regions', 'redistributor-stride', 'method', 'enable-method', 'msi-controller', 'always-on', 'device_type'):
        if k in p:
            v = p[k]; print('  %s =' % k, (words(v) if len(v) % 4 == 0 and k not in ('method', 'enable-method', 'device_type') else strs(v)))
    if 'interrupts' in p: print('  interrupts =', ' '.join('0x%x' % w for w in words(p['interrupts'])))
    pairs = reg_pairs(n)
    if any(c == 'arm,gic-v3' for c in comp) and pairs:
        print('RANGE GICD 0x%x 0x%x %s' % (pairs[0][0], pairs[0][1], n['path']))
        for i, (b, s) in enumerate(pairs[1:]): print('RANGE GICR%d 0x%x 0x%x %s' % (i, b, s, n['path']))
    elif any('gic-v3-its' in c for c in comp) and pairs:
        print('RANGE ITS 0x%x 0x%x %s' % (pairs[0][0], pairs[0][1], n['path']))
    elif any(c in ('arm,cortex-a15-gic', 'arm,gic-400', 'arm,cortex-a9-gic') for c in comp) and pairs:
        print('RANGE GICv2D 0x%x 0x%x %s' % (pairs[0][0], pairs[0][1], n['path']))
        if len(pairs) > 1: print('RANGE GICv2C 0x%x 0x%x %s' % (pairs[1][0], pairs[1][1], n['path']))
PY
        run_to_raw dtb-nodes "${python_bin}" "${work}/fdt.py" "${dtb_file}" && any=1
        while read -r _ label base size path; do
          add_range "${label}" "$(to_dec "${base}")" "$(to_dec "${size}")" "dtb:${path}"
        done < <(grep '^RANGE ' "${out_dir}/raw/dtb-nodes.txt" || true)
      fi
      if [[ "${any}" -eq 1 && ${#range_labels[@]} -gt 0 ]]; then
        dtb_status="PASS"; dtb_detail="${#range_labels[@]} GIC range(s) parsed from $(basename "${dtb_file}") (sha256 ${dtb_sha:0:16}...); neither the DTB nor its full decompilation is copied into results/ (grepped excerpts + RANGE lines only)"
      elif [[ "${any}" -eq 1 ]]; then
        dtb_status="FAIL"; dtb_detail="tree parsed but no arm,gic-v3 / gic-v3-its node with reg found"
      else
        dtb_status="BLOCKED"; dtb_detail="no dtc/fdtdump/fdtget and no working python — cannot read the FDT"
      fi
    fi
  fi
else
  dtb_status="NOT RUN"; dtb_detail="--dtb not given (produce one with: qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=virt.dtb -cpu host -enable-kvm -smp 2 -m 1G -display none)"
fi
record "DTB analysis (GIC/ITS/timer/PSCI/cpus nodes located)" "${dtb_status}" "${dtb_detail}"

# QEMU monitor / QMP (read-only info commands only)
hmp_cmds=("info registers -a" "info mtree" "info qtree" "info cpus" "info irq" "info status")
if [[ -n "${python_bin}" ]]; then
  cat > "${work}/mon.py" <<'PY'
import socket, sys, json, time
kind, path = sys.argv[1], sys.argv[2]; cmds = sys.argv[3:]
def connect(p):
    if ':' in p and not p.startswith('/'):
        h, port = p.rsplit(':', 1); s = socket.create_connection((h, int(port)), timeout=5)
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(5); s.connect(p)
    return s
def drain(s, quiet=0.8):
    buf = b''; s.settimeout(quiet)
    while True:
        try:
            chunk = s.recv(65536)
            if not chunk: break
            buf += chunk
        except socket.timeout: break
    return buf.decode('utf-8', 'replace')
s = connect(path)
if kind == 'qmp':
    drain(s); s.sendall(b'{"execute":"qmp_capabilities"}\n'); drain(s)
    for c in cmds:
        s.sendall((json.dumps({"execute": "human-monitor-command", "arguments": {"command-line": c}}) + '\n').encode())
        print('=== %s\n%s' % (c, drain(s)))
else:
    drain(s)
    for c in cmds:
        s.sendall((c + '\n').encode()); print('=== %s\n%s' % (c, drain(s)))
PY
fi
mon_status="NOT RUN"; mon_detail="no --monitor-socket/--qmp-socket given; the exact read-only commands are printed under 'Exact next commands'"
if [[ -n "${monitor_socket}" || -n "${qmp_socket}" ]]; then
  if [[ -z "${python_bin}" && -z "${socat_bin}" ]]; then
    mon_status="BLOCKED"; mon_detail="socket given but neither python nor socat is available to talk to it"
  else
    ok=0
    if [[ -n "${qmp_socket}" ]]; then
      if [[ -n "${python_bin}" ]]; then run_to_raw qemu-qmp "${python_bin}" "${work}/mon.py" qmp "${qmp_socket}" "${hmp_cmds[@]}" && ok=1
      else mon_detail="QMP needs python (socat cannot do the capabilities handshake non-interactively here)"; fi
    fi
    if [[ -n "${monitor_socket}" ]]; then
      if [[ -n "${python_bin}" ]]; then run_to_raw qemu-monitor "${python_bin}" "${work}/mon.py" hmp "${monitor_socket}" "${hmp_cmds[@]}" && ok=1
      elif [[ -n "${socat_bin}" ]]; then
        printf '%s\n' "${hmp_cmds[@]}" > "${work}/hmp-cmds"
        sh_to_raw qemu-monitor "'${socat_bin}' -T5 - UNIX-CONNECT:'${monitor_socket}' < '${work}/hmp-cmds'" && ok=1
      fi
    fi
    if [[ "${ok}" -eq 1 ]]; then
      mon_status="PASS"; mon_detail="raw/qemu-monitor.txt / raw/qemu-qmp.txt (read-only info commands)"
      for f in qemu-monitor qemu-qmp; do
        [[ -f "${out_dir}/raw/${f}.txt" ]] || continue
        while read -r a b rest; do
          lo="${a%-*}"; hi="${a#*-}"
          add_range "monitor:${rest##*: }" "$(to_dec "0x${lo}")" "$(( $(to_dec "0x${hi}") - $(to_dec "0x${lo}") + 1 ))" "${f}"
        done < <(grep -E '^[[:space:]]*[0-9a-f]{16}-[0-9a-f]{16} \(prio [0-9]+, i/o\): (gicv3|gic|its|arm_gicv3|gicv3_dist|gicv3_redist)[a-z_0-9]*' "${out_dir}/raw/${f}.txt" | sed -E 's/^[[:space:]]+//' || true)
      done
    else
      mon_status="BLOCKED"; mon_detail="${mon_detail}; connect failed or timed out (is the socket path right and QEMU alive?)"
    fi
  fi
fi
record "QEMU monitor/QMP info capture (registers, mtree, qtree, cpus, irq)" "${mon_status}" "${mon_detail}"

# reference ranges (board constants, NOT observed). Kept last so DTB/monitor win.
ref_note="QEMU 'virt' board memmap constants (hw/arm/virt.c) — assumed for -machine virt; verify against a dumpdtb from the SAME QEMU/KVM invocation before trusting"
add_range "GICD" "$(to_dec 0x08000000)" "$(to_dec 0x10000)" "reference"
add_range "ITS" "$(to_dec 0x08080000)" "$(to_dec 0x20000)" "reference"
add_range "GICR0" "$(to_dec 0x080A0000)" "$(to_dec 0xF60000)" "reference"

gicd_base_dtb=""
for i in "${!range_labels[@]}"; do
  if [[ "${range_labels[$i]}" == "GICD" && "${range_srcs[$i]}" == dtb:* ]]; then gicd_base_dtb="${range_bases[$i]}"; break; fi
done
derived_ipa=""
derived_src=""
if [[ -n "${gicd_base_dtb}" ]]; then derived_ipa=$(( gicd_base_dtb + 0x420 )); derived_src="DTB GICD base"; else derived_ipa=$(( 0x08000000 + 0x420 )); derived_src="reference GICD base (unverified)"; fi

mmio_md=()
mmio_md+=("| label | base | end (incl.) | size | source |"); mmio_md+=("|---|---|---|---|---|")
for i in "${!range_labels[@]}"; do
  b="${range_bases[$i]}"; s="${range_sizes[$i]}"
  mmio_md+=("| ${range_labels[$i]} | $(hex "${b}") | $(hex $(( b + s - 1 ))) | $(hex "${s}") | ${range_srcs[$i]} |")
done
if [[ -n "${observed_ipa}" ]]; then
  inside=""
  for i in "${!range_labels[@]}"; do
    b="${range_bases[$i]}"; s="${range_sizes[$i]}"
    if (( observed_ipa >= b && observed_ipa < b + s )); then inside="${inside}${range_labels[$i]}[${range_srcs[$i]}] +$(hex $(( observed_ipa - b ))); "; fi
  done
  if [[ -n "${inside}" ]]; then
    record "Observed IPA lies inside a GIC MMIO range" "PASS" "$(hex "${observed_ipa}") in ${inside}"
    mmio_md+=(""); mmio_md+=("Observed IPA $(hex "${observed_ipa}") falls in: ${inside}")
    [[ "${inside}" == *reference* && "${inside}" != *dtb* && "${inside}" != *monitor* ]] && mmio_md+=("(matched only the reference constants — confirm with a DTB or 'info mtree' from the failing invocation)")
  else
    record "Observed IPA lies inside a GIC MMIO range" "FAIL" "$(hex "${observed_ipa}") is outside every known GIC range — the fault is not a GIC access, or the ranges are wrong"
    mmio_md+=(""); mmio_md+=("Observed IPA $(hex "${observed_ipa}") is OUTSIDE every range above.")
  fi
else
  record "Observed IPA lies inside a GIC MMIO range" "NOT RUN" "no observed IPA (no --hpfar/--far/--ipa); only the derived expectation $(hex "${derived_ipa}") is shown, which is circular and proves nothing"
  mmio_md+=(""); mmio_md+=("No observed IPA. Derived expectation (hypothesis, from static disassembly: GICD + 0x420 with ${derived_src}): $(hex "${derived_ipa}") — by construction inside GICD, so this comparison is not evidence.")
fi

# ================================================================ 7. faulting instruction
section "Faulting instruction"
# classify_opcode HEX -> "class|writeback|expected_isv|detail"
classify_opcode() {
  local insn; insn="$(to_dec "$1")"
  local b28_25=$(( (insn >> 25) & 0xF ))
  if (( (b28_25 & 0x5) != 0x4 )); then
    local bits="" i
    for i in 3 2 1 0; do bits="${bits}$(( (b28_25 >> i) & 1 ))"; done
    printf 'not a load/store (top-level op0 bits[28:25]=%s is not x1x0)|n/a|n/a|could be a system instruction (e.g. DC ZVA -> ISV=0) or a non-memory instruction' "${bits}"
    return
  fi
  local op0=$(( (insn >> 28) & 3 )) V=$(( (insn >> 26) & 1 )) op2=$(( (insn >> 23) & 3 )) op3=$(( (insn >> 16) & 0x3F )) op4=$(( (insn >> 10) & 3 ))
  local size=$(( (insn >> 30) & 3 )) opc=$(( (insn >> 22) & 3 )) rt=$(( insn & 0x1F )) rn=$(( (insn >> 5) & 0x1F ))
  local sz; case ${size} in 0) sz="byte";; 1) sz="halfword";; 2) sz="word (w-reg)";; 3) sz="doubleword (x-reg)";; esac
  local dir; case ${opc} in 0) dir="store";; 1) dir="load";; 2) dir="load (sign-ext to 64) / PRFM when size=3";; 3) dir="load (sign-ext to 32)";; esac
  local common="size=${sz}, opc=${opc} (${dir}), Rt=${rt}, Rn=${rn}"
  local L=$(( (insn >> 22) & 1 )) ldst; ldst="$([[ ${L} -eq 1 ]] && echo load || echo store)"
  if (( V == 1 )); then
    # bit 22 is L in every SIMD&FP / AdvSIMD-structure class; opc[1] (bit 23)
    # is a width bit for single-register forms, not a writeback flag
    local vcls vwb vcommon="L=${L} (${ldst}), size=${size}, opc=${opc} (width from size:opc), Rt=${rt} (V-reg), Rn=${rn}"
    case ${op0} in
      0) if (( (insn >> 31) & 1 )); then vcls="unallocated (V=1, op0=1x00)"; vwb="n/a"
         else vcls="AdvSIMD load/store structure (LD1-LD4/ST1-ST4, $( (( op2 & 2 )) && echo single || echo multiple))"; vwb="$( (( op2 & 1 )) && echo yes || echo no )"; fi;;
      1) if (( op2 & 2 )); then vcls="unallocated (V=1, op0=xx01, op2=1x)"; vwb="n/a"
         else printf 'load register (literal, PC-relative), SIMD&FP|no|n/a (PC-relative; never an MMIO target)|opc=%d, Rt=%d (V-reg)' "${opc}" "${rt}"; return; fi;;
      2) case ${op2} in 0) vcls="SIMD&FP pair, no-allocate (STNP/LDNP)"; vwb=no;; 1) vcls="SIMD&FP pair, post-indexed"; vwb=yes;; 2) vcls="SIMD&FP pair, signed offset"; vwb=no;; 3) vcls="SIMD&FP pair, pre-indexed"; vwb=yes;; esac;;
      3) if (( op2 & 2 )); then vcls="SIMD&FP single register, unsigned immediate offset"; vwb=no
         elif (( (op3 >> 5) == 0 )); then
           case ${op4} in 0) vcls="SIMD&FP single register, unscaled immediate (LDUR/STUR)"; vwb=no;; 1) vcls="SIMD&FP single register, POST-INDEXED"; vwb=yes;; 2) vcls="unallocated (V=1, op3=0xxxxx, op4=2)"; vwb="n/a";; 3) vcls="SIMD&FP single register, PRE-INDEXED"; vwb=yes;; esac
         else
           case ${op4} in 2) vcls="SIMD&FP single register, register offset"; vwb=no;; *) vcls="unallocated (V=1, op3=1xxxxx, op4=${op4})"; vwb="n/a";; esac
         fi;;
    esac
    printf 'SIMD/FP or vector load/store: %s|%s|0|V=1: not a single general-purpose-register access -> ISV=0; %s' "${vcls}" "${vwb}" "${vcommon}"; return
  fi
  # PRFM/PRFUM (size=3, opc=2, V=0 in the unsigned-imm / unscaled / register-offset classes) is a hint and never faults
  local prefetch=0; (( size == 3 && opc == 2 )) && prefetch=1
  case ${op0} in
    0) # exclusive / ordered / CAS share one layout: o2=bit23, L=bit22, o1=bit21, Rs=[20:16], o0=bit15, Rt2=[14:10] (no opc field)
       local o2=$(( (insn >> 23) & 1 )) o1=$(( (insn >> 21) & 1 )) rs=$(( (insn >> 16) & 0x1F )) o0=$(( (insn >> 15) & 1 )) rt2=$(( (insn >> 10) & 0x1F ))
       local xfields="size=${sz}, L=${L} (${ldst}), o2=${o2}, o1=${o1}, o0=${o0} ($([[ ${o0} -eq 1 ]] && echo 'acquire/release' || echo 'plain')), Rs=${rs} (status/compare reg), Rt2=${rt2}, Rt=${rt}, Rn=${rn}"
       if (( op2 == 0 )); then
         if (( op3 >> 5 )); then
           # o1=1: exclusive pair when bit 31 is set (op0=1x00), compare-and-swap pair when clear (op0=0x00)
           if (( (insn >> 31) & 1 )); then printf 'load/store exclusive pair|no|0|LDXP/STXP/LDAXP/STLXP (op0=1x00, o1=1); %s' "${xfields}"
           else printf 'compare-and-swap pair (CASP, FEAT_LSE)|no|0|op0=0x00, op2=00, o1=1: read-modify-write -> ISV=0; %s' "${xfields}"; fi
         else printf 'load/store exclusive register|no|0|LDXR/STXR/LDAXR/STLXR family (o1=0); %s' "${xfields}"; fi
       elif (( op2 == 1 )); then
         if (( (op3 >> 5) == 0 )); then printf 'load-acquire/store-release (ordered)|no|1|LDAR/STLR (o0=1) or LDLAR/STLLR (o0=0): single register, no writeback -> ISS valid with AR=1; %s' "${xfields}"
         else printf 'compare-and-swap (CAS, FEAT_LSE)|no|0|read-modify-write -> ISV=0; %s' "${xfields}"; fi
       else printf 'unknown load/store encoding (op0=xx00, op2=1x)|n/a|n/a|%s' "${xfields}"; fi;;
    1) if (( op2 & 2 )); then
         local imm9u=$(( (insn >> 12) & 0x1FF )); (( imm9u & 0x100 )) && imm9u=$(( imm9u - 0x200 ))
         if (( (op3 >> 5) == 0 )); then
           case ${op4} in
             0) printf 'load-acquire/store-release, unscaled immediate (LDAPUR/STLUR, FEAT_LRCPC2)|no|1|single register, no writeback -> ISS valid with AR=1; imm9=%d; %s' "${imm9u}" "${common}";;
             1) printf 'memory copy/set (CPYx/SETx, FEAT_MOPS)|n/a|0|multi-register bulk operation, not a single-register access; %s' "${common}";;
             *) printf 'unallocated (op0=xx01, op2=1x, op3=0xxxxx, op4=%d)|n/a|n/a|%s' "${op4}" "${common}";;
           esac
         elif (( size == 3 )); then
           # bits[31:30]=11 here is the FEAT_MTE 'load/store memory tags' class
           local mte_wb mte_mode
           case ${op4} in 0) mte_wb=no;  mte_mode="LDG / no writeback";; 1) mte_wb=yes; mte_mode="post-indexed";; 2) mte_wb=no; mte_mode="signed offset";; 3) mte_wb=yes; mte_mode="pre-indexed";; esac
           printf 'memory tag store/load (STG/STZG/ST2G/STZ2G/LDG, FEAT_MTE)|%s|0|tag-granule access, not a general-purpose data access -> ISV=0; opc=%d, op2[11:10]=%d (%s), imm9=%d, Rt=%d, Rn=%d' "${mte_wb}" "${opc}" "${op4}" "${mte_mode}" "${imm9u}" "${rt}" "${rn}"
         else printf 'unallocated (op0=xx01, op2=1x, op3=1xxxxx, size!=3)|n/a|n/a|%s' "${common}"; fi
       else
         local lopc=$(( (insn >> 30) & 3 )) imm19=$(( (insn >> 5) & 0x7FFFF )); (( imm19 & 0x40000 )) && imm19=$(( imm19 - 0x80000 ))
         local lname; case ${lopc} in 0) lname="LDR (literal) 32-bit";; 1) lname="LDR (literal) 64-bit";; 2) lname="LDRSW (literal)";; 3) lname="PRFM (literal)";; esac
         printf 'load register (literal, PC-relative)|no|n/a (PC-relative; never an MMIO target)|%s, Rt=%d, imm19=%d (x4 = PC-relative byte offset)' "${lname}" "${rt}" "${imm19}"
       fi;;
    2) local mode; case ${op2} in 0) mode="no-allocate pair (STNP/LDNP)|no";; 1) mode="pair, post-indexed|yes";; 2) mode="pair, signed offset|no";; 3) mode="pair, pre-indexed|yes";; esac
       local popc=$(( (insn >> 30) & 3 )) L=$(( (insn >> 22) & 1 )) rt2=$(( (insn >> 10) & 0x1F )) imm7=$(( (insn >> 15) & 0x7F ))
       (( imm7 & 0x40 )) && imm7=$(( imm7 - 0x80 ))
       local pw; case ${popc} in 0) pw="32-bit (w-regs)";; 1) pw="LDPSW / STGP";; 2) pw="64-bit (x-regs)";; 3) pw="unallocated";; esac
       printf 'load/store pair (%s)|%s|0|two registers -> never ISV; opc=%d (%s), L=%d (%s), Rt=%d, Rt2=%d, Rn=%d, imm7=%d (scaled by the register size)' \
         "${mode%%|*}" "${mode##*|}" "${popc}" "${pw}" "${L}" "$([[ ${L} -eq 1 ]] && echo load || echo store)" "${rt}" "${rt2}" "${rn}" "${imm7}";;
    3) local pf_form=""
       if (( prefetch )); then
         if (( op2 & 2 )); then pf_form="unsigned immediate"
         elif (( (op3 >> 5) == 0 && op4 == 0 )); then pf_form="unscaled immediate, PRFUM"
         elif (( (op3 >> 5) == 1 && op4 == 2 )); then pf_form="register offset"; fi
       fi
       if [[ -n "${pf_form}" ]]; then
         printf 'prefetch hint (PRFM/PRFUM, %s) — never faults, cannot be the faulting PC|no|n/a|size=3, opc=2, V=0: prfop=%d, Rn=%d' "${pf_form}" "${rt}" "${rn}"
       elif (( op2 & 2 )); then printf 'ordinary load/store, unsigned immediate offset|no|1|single register, no writeback; imm12=%s; %s' "$(hex $(( (insn >> 10) & 0xFFF )))" "${common}"
       else
         local imm9=$(( (insn >> 12) & 0x1FF )); (( imm9 & 0x100 )) && imm9=$(( imm9 - 0x200 ))
         if (( (op3 >> 5) == 0 )); then
           case ${op4} in
             0) printf 'ordinary load/store, unscaled immediate (LDUR/STUR)|no|1|single register, no writeback; imm9=%d; %s' "${imm9}" "${common}";;
             1) printf 'ordinary load/store, immediate POST-INDEXED (writeback)|yes|0|base register updated after the access; imm9=%d; ARM ARM excludes writeback forms from ISV=1; %s' "${imm9}" "${common}";;
             2) printf 'ordinary load/store, unprivileged (LDTR/STTR)|no|1|imm9=%d; %s' "${imm9}" "${common}";;
             3) printf 'ordinary load/store, immediate PRE-INDEXED (writeback)|yes|0|base register updated before the access; imm9=%d; ARM ARM excludes writeback forms from ISV=1; %s' "${imm9}" "${common}";;
           esac
         else
           case ${op4} in
             0) printf 'atomic memory operation (LDADD/LDCLR/LDSET/SWP..., FEAT_LSE)|no|0|read-modify-write -> ISV=0; %s' "${common}";;
             2) printf 'ordinary load/store, register offset|no|1|single register, no writeback; Rm=%d; %s' "$(( op3 & 0x1F ))" "${common}";;
             *) printf 'PAC-authenticated load (LDRAA/LDRAB)|%s|0|%s' "$( (( op4 == 3 )) && echo yes || echo no )" "${common}";;
           esac
         fi
       fi;;
  esac
}

st1="$(classify_opcode 0xb8004403)"; st2="$(classify_opcode 0xb81fc003)"
if [[ "${st1}" == *POST-INDEXED* && "$(cut -d'|' -f2 <<<"${st1}")" == "yes" && "$(cut -d'|' -f3 <<<"${st1}")" == "0" && "${st1}" == *"Rt=3, Rn=0"* \
   && "${st2}" == *unscaled* && "$(cut -d'|' -f2 <<<"${st2}")" == "no" && "$(cut -d'|' -f3 <<<"${st2}")" == "1" && "${st2}" == *"imm9=-4"* ]]; then
  record "Opcode classifier self-test (b8004403 post-indexed store / b81fc003 unscaled store)" "PASS" "both encodings quoted in docs/findings.md classify as documented (writeback+ISV=0 vs no-writeback+ISV=1)"
else
  record "Opcode classifier self-test (b8004403 post-indexed store / b81fc003 unscaled store)" "FAIL" "got: ${st1} // ${st2}"
fi

fi_md=(); fi_status=""; fi_detail=""
if [[ -n "${elf_file}" && -n "${guest_pc}" ]]; then
  pc_dec="$(to_dec "${guest_pc}")"
  if [[ ! -f "${elf_file}" ]]; then
    fi_status="BLOCKED"; fi_detail="--elf not found: ${elf_file}"
  elif [[ -z "${objdump_bin}" ]]; then
    fi_status="BLOCKED"; fi_detail="no aarch64-capable objdump found (ntoaarch64-objdump / aarch64-*-objdump / llvm-objdump); set QNX_HOST or PATH"
  else
    elf_sha="$(sha256sum "${elf_file}" 2>/dev/null | cut -d' ' -f1 || echo '?')"
    magic="$(od -An -tx1 -N4 "${elf_file}" 2>/dev/null | tr -d ' \n')"
    is_elf=0; e_type=0
    if [[ "${magic}" == "7f454c46" ]]; then is_elf=1; e_type="$(od -An -tu2 -j16 -N2 "${elf_file}" | tr -d ' ')"; fi
    case "${e_type}" in 1) e_type_name="REL (relocatable)";; 2) e_type_name="EXEC";; 3) e_type_name="DYN";; *) e_type_name="not ELF (raw binary)";; esac
    if [[ -n "${elf_base}" ]]; then addr=$(( pc_dec - $(to_dec "${elf_base}") )); else addr="${pc_dec}"; fi
    fi_md+=("- file: $(basename "${elf_file}") (${e_type_name}, sha256 ${elf_sha:0:16}...; the file itself is NOT copied into results/)")
    fi_md+=("- guest PC $(hex "${pc_dec}")${elf_base:+ - base $(hex "$(to_dec "${elf_base}")")} -> file address $(hex "${addr}")")
    [[ "${e_type}" == "1" && -z "${elf_base}" ]] && fi_md+=("- NOTE: REL object without --elf-base: the PC is interpreted as a .text offset, not a guest VA. mkifs links startup at the IFS image address; pass --elf-base <.text load address> to convert a traced PC.")
    lo=$(( addr - 4 * disasm_window )); (( lo < 0 )) && lo=0
    hi=$(( addr + 4 * (disasm_window + 1) ))
    if [[ "${is_elf}" -eq 1 ]]; then
      run_to_raw faulting-instruction-window "${objdump_bin}" -d --start-address="${lo}" --stop-address="${hi}" "${elf_file}" || true
    elif [[ -n "${elf_base}" ]]; then
      base_dec="$(to_dec "${elf_base}")"
      lo_raw=$(( pc_dec - 4 * disasm_window )); (( lo_raw < base_dec )) && lo_raw=${base_dec}
      run_to_raw faulting-instruction-window "${objdump_bin}" -D -b binary -m aarch64 --adjust-vma="${base_dec}" --start-address="${lo_raw}" --stop-address="$(( pc_dec + 4 * (disasm_window + 1) ))" "${elf_file}" || true
      # for raw binaries objdump addresses are already guest VAs
      addr="${pc_dec}"
    else
      fi_status="BLOCKED"; fi_detail="raw (non-ELF) file needs --elf-base to place it"
    fi
    if [[ -z "${fi_status}" ]]; then
      pc_line="$(grep -E "^[[:space:]]*$(printf '%x' "${addr}"):" "${out_dir}/raw/faulting-instruction-window.txt" | head -1 | sed 's/\t/ /g' || true)"
      if [[ -z "${pc_line}" ]]; then
        fi_status="FAIL"; fi_detail="objdump produced no line at $(hex "${addr}") (outside .text? wrong --elf-base?) — see raw/faulting-instruction-window.txt"
      else
        opcode="$(awk '{print $2}' <<<"${pc_line}")"
        mnem="$(sed -E 's/^[[:space:]]*[0-9a-f]+:[[:space:]]+[0-9a-f]{8}[[:space:]]+//' <<<"${pc_line}")"
        if [[ "${opcode}" =~ ^[0-9a-f]{8}$ ]]; then
          cls="$(classify_opcode "0x${opcode}")"
          fi_md+=("- instruction at $(hex "${addr}"): opcode 0x${opcode}  \`${mnem}\`")
          fi_md+=("- class (from the opcode, not the function name): $(cut -d'|' -f1 <<<"${cls}"); writeback: $(cut -d'|' -f2 <<<"${cls}"); expected ISV per ARM ARM: $(cut -d'|' -f3 <<<"${cls}")")
          fi_md+=("- fields: $(cut -d'|' -f4 <<<"${cls}")")
          if [[ -n "${nm_bin}" && "${is_elf}" -eq 1 ]]; then
            sym=""
            while read -r saddr stype sname; do
              [[ "${stype}" =~ ^[TtW]$ && "${saddr}" =~ ^[0-9a-f]+$ ]] || continue
              sv=$(( 0x${saddr} ))
              (( sv <= addr )) && sym="${sname}+$(hex $(( addr - sv )))"
            done < <(run_with_timeout "${nm_bin}" -n --defined-only "${elf_file}" 2>/dev/null || true)
            [[ -n "${sym}" ]] && fi_md+=("- symbol (nm, nearest preceding text symbol): ${sym}")
          fi
          if [[ -n "${addr2line_bin}" && "${is_elf}" -eq 1 ]]; then
            a2l="$(run_with_timeout "${addr2line_bin}" -f -e "${elf_file}" "$(hex "${addr}")" 2>/dev/null | tr '\n' ' ' || true)"
            [[ -n "${a2l}" ]] && fi_md+=("- addr2line: ${a2l}")
          fi
          fi_md+=("- window (up to +/- ${disasm_window} instructions, clamped at the file start): raw/faulting-instruction-window.txt")
          fi_status="PASS"; fi_detail="0x${opcode} -> $(cut -d'|' -f1 <<<"${cls}") (writeback $(cut -d'|' -f2 <<<"${cls}"), expected ISV $(cut -d'|' -f3 <<<"${cls}"))"
        else
          fi_status="FAIL"; fi_detail="could not parse an opcode from: ${pc_line}"
        fi
      fi
    fi
  fi
else
  fi_status="BLOCKED"; fi_detail="--elf and/or --guest-pc not given — the repo records no numeric faulting PC, and the shipped startup is NCEULA (not committed)"
  fi_md+=("- BLOCKED: no --elf/--guest-pc. Documented (prose, docs/orin-port.md + docs/findings.md 2026-09-08): \`str w3,[x0],#4\` at GICD+0x420 in gic_v3_initialize, opcode 0xb8004403 in the BSP-rebuilt gic_v3.o.")
  fi_md+=("- classifier on the documented opcode 0xb8004403: $(cut -d'|' -f1 <<<"${st1}"); writeback $(cut -d'|' -f2 <<<"${st1}"); expected ISV $(cut -d'|' -f3 <<<"${st1}"); $(cut -d'|' -f4 <<<"${st1}")")
  fi_md+=("- classifier on the -fno-auto-inc-dec replacement 0xb81fc003: $(cut -d'|' -f1 <<<"${st2}"); writeback $(cut -d'|' -f2 <<<"${st2}"); expected ISV $(cut -d'|' -f3 <<<"${st2}"); $(cut -d'|' -f4 <<<"${st2}")")
fi
record "Faulting-instruction disassembly + opcode classification (--elf/--guest-pc)" "${fi_status}" "${fi_detail}"

# ================================================================ hardware-only rows
if [[ "${platform}" == "linux" && "${kvm_state}" == present* ]]; then
  record "KVM boot reproduction of the IFS on this host" "NOT RUN" "this script never boots a guest; exact command printed below"
  record "ftrace capture of kvm_guest_fault / kvm_userspace_exit during a KVM boot" "NOT RUN" "needs root + a KVM boot; commands printed below"
else
  record "KVM boot reproduction of the IFS on this host" "NOT APPLICABLE" "no usable KVM on this host (${kvm_state})"
  record "ftrace capture of kvm_guest_fault / kvm_userspace_exit during a KVM boot" "BLOCKED" "needs a Linux/KVM host (Orin or arm64 metal) — not this one"
fi
record "TCG control boot of the same IFS on this host" "NOT RUN" "not executed by this script; existing TCG controls are classified above"
record "KVM re-check with from-source QEMU 11.1.0 (--enable-kvm) on the Orin" "NOT RUN" "never performed; every NISV data point is QEMU 6.2.0 (scripts/orin/build-qemu-on-orin.sh built the binary)"
record "KVM variants -smp 1 / gic-version=host / its=off logged with n>=1 each" "NOT RUN" "asserted in docs/orin-port.md without logs or counts; commands printed below"
record "a1.metal (or c7g.metal) re-run with ftrace to classify that hang as NISV by data" "NOT RUN" "a1.metal log is symptom-only; c7g.metal blocked by the 32-vCPU quota"
record "Boot of a startup rebuilt with -fno-auto-inc-dec under KVM" "BLOCKED" "startup-qemu-virt cannot be relinked (BSP ships boards/armv8_fm, not boards/qemu-virt)"

# ================================================================ render summary
section "Writing summary"
S="${work}/summary.md"
emit() { printf '%s\n' "$@" >> "${S}"; }
: > "${S}"

emit "# GICv3 / KVM_EXIT_ARM_NISV diagnostic — ${ts}" ""
emit "Read-only collection by \`scripts/diagnose-gicv3-nisv.sh\` (nothing booted, nothing privileged executed)." \
     "Scope: the qnx-safety-vm IFS hanging under \`-enable-kvm\` after \`FOUND GICv3 ITS\`. **Not** the QHV/TCG QEMU-6.2 virtual-timer hang — those logs are listed as excluded." \
     "Results dir: \`${out_dir_rel}\`. Arguments: \`${argv_record:-(none)}\`." ""

emit "## Environment" ""
for l in "${env_lines[@]}"; do emit "- ${l}"; done
emit "- /dev/kvm: ${kvm_state}"
emit "- running qemu process lines: ${qemu_running} (raw/qemu-processes.txt)"
if [[ ${#qemu_found[@]} -gt 0 ]]; then emit "- QEMU binaries:"; for q in "${qemu_found[@]}"; do emit "  - ${q}"; done; else emit "- QEMU binaries: none found"; fi
emit "" "Tools detected:" ""
cat "${work}/tools.md" >> "${S}"
emit ""

emit "## Repository revision" ""
emit "- HEAD: ${git_head}${git_branch:+ (branch ${git_branch})}${git_desc:+, describe ${git_desc}}"
emit "- working tree and last commits: raw/git-state.txt"
emit "- local ifs.bin sha256: ${local_ifs_sha:-(no local image)}"
emit "- hash recorded for the hung KVM boots (a1.metal log header): ${recorded_ifs_sha:-(not found)}"
emit ""

emit "## Evidence found" ""
emit "Key-term hits in docs/, scripts/, logs/, README/CLAUDE/AGENTS (raw/repo-evidence-grep.txt):" ""
emit "| term | matching lines |" "|---|---|"
for c in ${grep_counts[@]+"${grep_counts[@]}"}; do emit "| \`${c%%|*}\` | ${c##*|} |"; done
emit "" "Boot-log classification (${log_dir#"${repo_root}"/}${boot_logs[0]:+ + --boot-log}); hang signature = 'FOUND GICv3 ITS' with no later '** CPU n PE is not awake':" ""
emit "| file | topic | accel | classification | ESR/exit-reason tokens (non-comment lines) | QEMU_EXIT |" "|---|---|---|---|---|---|"
for r in ${log_rows[@]+"${log_rows[@]}"}; do
  IFS="${sep}" read -r c1 c2 c3 c4 c5 c6 <<<"${r}"
  emit "| $(cell "${c1}") | $(cell "${c2}") | $(cell "${c3}") | $(cell "${c4}") | $(cell "${c5}") | $(cell "${c6}") |"
done
emit "" "Documented facts carried by the repo (prose unless a log is cited):" ""
emit "- observed on Orin Nano (ftrace, transcribed, no raw file): \`kvm_guest_fault hsr=0x92000045\`, \`kvm_userspace_exit reason KVM_EXIT_ARM_NISV (28)\` — docs/orin-port.md risk register"
emit "- observed on Orin Nano (QEMU monitor, transcribed): \`VBAR_EL1=0x4008d800\`; vector slot +0x200 disassembles to \`b .\` — same row"
emit "- observed in a committed log: a1.metal KVM boot prints only \`FOUND GICv3 ITS\` for 60 s, QEMU_EXIT=124 — logs/sample-boot/aws-a1-metal-kvm-nisv-repro.log (n=1, no ESR/exit data)"
emit "- observed in committed logs: the same ifs.bin boots to 'Startup complete' under TCG on the Orin and on Windows"
emit "- observed at compile level (2026-09-08): BSP gic_v3.c builds to \`str w3,[x0],#4\` at GICD+0x420 (opcode b8004403); \`-fno-auto-inc-dec\` removes all 4 writeback MMIO stores in that object — docs/findings.md"
emit "- derived, not recorded anywhere before this script: ESR field decode (below) and the expected IPA GICD+0x420"
emit ""

emit "## Registers" ""
emit "ESR decoder self-test on the repo's documented value (this is a decode of prose, not a fresh capture):" ""
emit "${esr_selftest_md}"
if [[ -n "${user_esr_md}" ]]; then emit "" "Supplied --esr ${esr_value}:" "" "${user_esr_md}"; else emit "" "- --esr not supplied."; fi
emit ""
emit "- guest PC: ${guest_pc:-not supplied (the repo never recorded the numeric PC)}"
emit "- FAR_EL2/HXFAR: ${far_value:-not supplied}; HPFAR_EL2: ${hpfar_value:-not supplied}; IPA: ${ipa_value:-not supplied}"
emit "- VBAR_EL1 = 0x4008d800 — documented (docs/orin-port.md), read live on 2026-07-28, no dump file; the post-hang PC was never read, so 'parked at VBAR+0x200' is an inference"
emit ""

emit "## Candidate IPA" ""
for l in ${ipa_md[@]+"${ipa_md[@]}"}; do emit "${l}"; done
emit "- derived expectation (hypothesis): GICD base + 0x420 = $(hex "${derived_ipa}") using ${derived_src}; the +0x420 comes from the documented disassembly (GICD_IPRIORITYRn, first loop iteration)"
emit ""

emit "## MMIO range comparison" ""
emit "- ${ref_note}"
emit "- DTB-derived ranges describe the DTB you passed; only a dumpdtb from the failing KVM invocation itself (same QEMU binary, -cpu host, -enable-kvm) describes the hung guest's view"
emit "- DTB: ${dtb_status} — ${dtb_detail}"
emit "- monitor/QMP: ${mon_status} — ${mon_detail}" ""
for l in "${mmio_md[@]}"; do emit "${l}"; done
emit ""

emit "## Faulting instruction" ""
emit "- status: ${fi_status} — ${fi_detail}"
for l in ${fi_md[@]+"${fi_md[@]}"}; do emit "${l}"; done
emit "- classification is by opcode encoding class only (ARM ARM 'Loads and stores' decode); 'expected ISV' restates the architectural rule — ISV=1 only for a single general-purpose-register load/store with no writeback that is not exclusive; pair, exclusive, atomic, SIMD&FP, memory-tag and writeback forms report ISV=0 — as an expectation, not an observation. PC-relative literal loads are not excluded by the rule but cannot target MMIO, and prefetch hints (PRFM/PRFUM) never fault, so both are marked n/a"
emit ""

emit "## Test status matrix" ""
emit "| test | status | detail |" "|---|---|---|"
for r in "${matrix[@]}"; do IFS="${sep}" read -r t st d <<<"${r}"; emit "| $(cell "${t}") | **${st}** | $(cell "${d}") |"; done
emit ""

emit "## Current diagnosis" ""
emit "**Facts (observed, with where):**" ""
emit "1. Under \`-machine virt,gic-version=3 -cpu host -enable-kvm\` the IFS prints \`FOUND GICv3 ITS\` and nothing else; the QEMU process stays alive. Orin Nano (prose, 2026-07-28) and a1.metal (committed log, 2026-07-29, n=1)."
emit "2. On the Orin the host ftrace showed \`kvm_guest_fault hsr=0x92000045\` and a \`KVM_EXIT_ARM_NISV (28)\` userspace exit (prose transcription). Decoded here: EC=0x24 Data Abort from a lower EL, ISV=0, WnR=1 (write), DFSC=0x05 stage-2 translation fault level 1 — i.e. a write to an IPA with no stage-2 mapping (what emulated MMIO looks like) whose syndrome the CPU did not describe."
emit "3. The same ifs.bin (sha256 ${recorded_ifs_sha:0:16}...) boots under TCG on the same Orin and on Windows (committed logs)."
emit "4. VBAR_EL1=0x4008d800 was read live; the +0x200 slot is \`b .\` (prose)."
emit "5. QNX's own BSP source compiles to \`str w3,[x0],#4\` (0xb8004403) at GICD+0x420, and \`-fno-auto-inc-dec\` removes that encoding class from the object (compile-level, docs/findings.md 2026-09-08)."
emit "6. vGIC creation succeeds on both hosts (bare \`-kernel /dev/null\` smoke tests clean, prose)."
emit "" "**Hypotheses (not yet shown by data):**" ""
emit "- that the faulting IPA is 0x08000420 (GICD_IPRIORITYR<8>) — no HPFAR/IPA was ever captured; the address is derived from static disassembly plus the virt board map"
emit "- that QEMU actually injected an external Data Abort and the guest is parked at VBAR_EL1+0x200 — inferred from strings in the QEMU binary and the vector slot content; no post-hang PC read"
emit "- that the a1.metal hang is the same NISV mechanism — same symptom, no ESR/exit-reason data there"
emit "- that removing the writeback store makes the guest boot under KVM — nothing rebuilt has been booted; startup-qemu-virt cannot be relinked"
emit "- that the '-smp 1 / gic-version=host / its=off' variants hang identically — asserted, no logs or counts"
emit "" "**What this run added:** decoder + classifier self-tests, log classification, image-hash check, tool inventory. It did not add hardware evidence (see matrix)."
emit ""

emit "## Ranked hypotheses" ""
emit "Eight candidate explanations, ranked against the evidence above. The two the repo already established are marked CONFIRMED; a CONFIRMED status here means 'observed on Orin + reproduced at compile level', not 'closed'. This enumeration is the script's; the original author's wording was not available to it." ""
emit "| # | hypothesis | status | evidence for / against |" "|---|---|---|---|"
emit "| 1 | The GICD write is a writeback-form (post-indexed) store, so the CPU reports ESR.ISV=0 and KVM cannot decode it -> KVM_EXIT_ARM_NISV | **CONFIRMED (Orin)** | hsr=0x92000045 decodes to ISV=0/WnR=1; \`str w3,[x0],#4\` found by static disassembly and reproduced from BSP source; the KVM API documents this exact exit for non-ISV MMIO |"
emit "| 2 | The target is GIC distributor MMIO (GICD_IPRIORITYRn, GICD+0x420) emulated in-kernel by vgic-v3, so there is no decoder fallback | **CONFIRMED at instruction level; IPA unobserved** | offset 0x420 from disassembly + gic_v3.h (IPRIORITYn=0x400); no HPFAR/IPA capture exists — see 'Candidate IPA' |"
emit "| 3 | QEMU 6.2's kvm_arm_handle_dabt_nisv() injects a synthetic external Data Abort; QNX startup's EL1 vector at VBAR_EL1+0x200 is \`b .\` -> silent park | **SUPPORTED, partly inferred** | VBAR_EL1 read live and slot disassembled; injection inferred from binary strings; post-hang PC never read |"
emit "| 4 | Guest memory map / DTB mismatch (GICD base wrong, unmapped IPA) rather than an MMIO decode problem | **WEAKENED** | DFSC=0x05 is consistent with either; but the same IFS + same board map boots under TCG, and vGIC/ITS discovery succeeds first. A captured IPA would settle it |"
emit "| 5 | ITS involvement (its=on default, GITS programming) is the trigger | **WEAKENED (unlogged)** | faulting register is GICD not GITS; docs assert its=off hangs identically but no log/count exists |"
emit "| 6 | vGIC device-creation failure (AGX Orin VmCreateGIC Error(19) family) | **REFUTED on both hosts** | bare vGIC smoke tests clean; guest runs far enough to print ITS discovery |"
emit "| 7 | Tegra234 / Cortex-A78AE / VHE-specific silicon quirk | **WEAKENED (n=1)** | identical symptom on a1.metal (Annapurna A72, non-VHE host); single run, symptom-only |"
emit "| 8 | QEMU-version-specific bug (6.2.0) fixed by a newer QEMU on KVM | **UNTESTED, assessed unlikely** | upstream KVM backend injects by design (no decode fallback for KVM); the from-source 11.1.0 --enable-kvm re-check was never run; a1.metal QEMU version unrecorded |"
emit ""

emit "## Missing evidence" ""
emit "- raw ftrace output (trace_pipe) from the Orin: numeric PC, IPA/HPFAR, HXFAR, vCPU id, exit count — only hsr and the exit reason were transcribed"
emit "- any serial log of an Orin KVM attempt (only the TCG control was committed)"
emit "- QEMU monitor dump file (VBAR_EL1 is a transcribed value); post-hang PC/ELR_EL1/ESR_EL1 read to confirm the park at VBAR+0x200"
emit "- command lines, logs and counts for the -smp 1 / gic-version=host / its=off variants"
emit "- DTB (dumpdtb) and 'info mtree' from the failing KVM invocation; whether QNX startup reads the FDT at all"
emit "- an ESR/exit-reason capture on a1.metal (or any second host) — currently symptom-only; QEMU version there"
emit "- KVM re-check with the from-source QEMU 11.1.0 on the Orin; c7g.metal run (quota-blocked)"
emit "- a bootable startup rebuilt with -fno-auto-inc-dec (needs the qemu-virt board source from QNX); an audit of libstartup.a beyond gic_v3.c"
emit "- guest-side data value at the fault (w3=0xA0A0A0A0 known only from the rebuilt object)"
[[ -z "${esr_value}" ]]   && emit "- this run: no --esr supplied"
[[ -z "${hpfar_value}${ipa_value}" ]] && emit "- this run: no --hpfar/--ipa supplied (no IPA comparison possible)"
[[ -z "${elf_file}${guest_pc}" ]] && emit "- this run: no --elf/--guest-pc supplied (no live disassembly)"
[[ -z "${dtb_file}" ]]     && emit "- this run: no --dtb supplied (reference board constants used, unverified)"
emit ""

emit "## Exact next commands" ""
emit "Printed, not executed. Anything with sudo is privileged. The Orin is in use by another experiment at the time of writing — do not run the Orin block until it is free. Replace <...> placeholders." ""
next_cmds="$(cat <<'CMDS'
### A. Orin Nano (L4T), fresh KVM capture with raw evidence — privileged, PRINT ONLY
# 0. environment stamp
uname -a; grep -m1 'CPU part' /proc/cpuinfo; qemu-system-aarch64 --version | head -1; dpkg -s qemu-system-arm 2>/dev/null | grep '^Version'
sudo dmesg | grep -iE 'kvm|vgic|gic|vhe|hyp mode|ipa size' > __OUT__/raw/orin-dmesg-kvm.txt
ls -l /dev/kvm; id
# 1. DTB + memory tree of the exact failing invocation (KVM shape, -cpu host)
sudo qemu-system-aarch64 -machine virt,gic-version=3,dumpdtb=virt-kvm-gicv3.dtb -cpu host -enable-kvm -smp 2 -m 1G -display none
dtc -I dtb -O dts virt-kvm-gicv3.dtb > __OUT__/raw/orin-virt-kvm-gicv3.dts     # or pass --dtb virt-kvm-gicv3.dtb to this script
# 2. ftrace on the KVM events (root), then boot with monitor + QMP sockets and a QEMU log
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true
T=/sys/kernel/debug/tracing
echo 0 | sudo tee $T/tracing_on; sudo sh -c "echo > $T/trace"
for e in kvm_guest_fault kvm_userspace_exit kvm_exit kvm_mmio kvm_irq_line; do echo 1 | sudo tee $T/events/kvm/$e/enable; done
echo 1 | sudo tee $T/tracing_on
sudo sh -c "cat $T/trace_pipe > __OUT__/raw/orin-kvm-trace_pipe.txt" &
cd ~/output && sha256sum -c SHA256SUMS
sudo timeout 60 qemu-system-aarch64 -machine virt,gic-version=3 -cpu host -enable-kvm -smp 2 -m 1G -snapshot \
  -drive file=disk-qemu,if=none,id=drv0,format=raw -device virtio-blk-device,drive=drv0 \
  -kernel ifs.bin -nographic -serial file:boot-kvm.log -display none -no-reboot \
  -monitor unix:/tmp/qemu-mon.sock,server,nowait -qmp unix:/tmp/qemu-qmp.sock,server,nowait \
  -D qemu-kvm-debug.log -d guest_errors,unimp ; echo QEMU_EXIT=$?
# 3. while it is hung (before the timeout fires), read state without changing it
for c in 'info registers -a' 'info mtree' 'info qtree' 'info cpus' 'info irq' 'info status'; do echo "$c" | sudo socat - UNIX-CONNECT:/tmp/qemu-mon.sock; done > __OUT__/raw/orin-monitor.txt
#    (or: bash scripts/diagnose-gicv3-nisv.sh --monitor-socket /tmp/qemu-mon.sock --qmp-socket /tmp/qemu-qmp.sock --qemu-pid $(pgrep -f 'qemu-system-aarch64.*ifs.bin'))
echo 0 | sudo tee $T/tracing_on
# 4. variants, one log each (n>=1 recorded per variant, which the repo currently lacks)
#    -smp 1        : replace '-smp 2' with '-smp 1'
#    its=off       : '-machine virt,gic-version=3,its=off'
#    gic host      : '-machine virt,gic-version=host'
#    QEMU 11.1.0   : QEMU_BIN=$HOME/qemu-v11.1.0/bin/qemu-system-aarch64 (built --enable-kvm by scripts/orin/build-qemu-on-orin.sh; check '$QEMU_BIN -accel help' lists kvm)
# 5. feed the capture back:
bash scripts/diagnose-gicv3-nisv.sh --esr <hsr from trace> --far <hxfar> --hpfar <hpfar or --ipa ipa> --guest-pc <pc> \
  --dtb virt-kvm-gicv3.dtb --boot-log boot-kvm.log --monitor-socket /tmp/qemu-mon.sock

### B. Second host (a1.metal / c7g.metal) — same as A; adds ESR/exit data the a1.metal log lacks
#    c7g.metal needs a 64-vCPU quota (currently 32). Record 'qemu-system-aarch64 --version' this time.

### C. Local Windows / Linux build host — static, unprivileged (proprietary outputs stay out of results/)
# extract the linked startup from the IFS into a scratch dir (NCEULA: never into the repo)
dumpifs -x -d <scratch> qnx-safety-vm/output/ifs.bin
# SDP relocatable startup: locate the store and disassemble around it
ntoaarch64-objdump -d --start-address=0x4168 --stop-address=0x4188 <sdp>/target/qnx/aarch64le/boot/sys/startup-qemu-virt
bash scripts/diagnose-gicv3-nisv.sh --elf <sdp>/target/qnx/aarch64le/boot/sys/startup-qemu-virt --guest-pc 0x4178 --out-root <scratch>/results
# linked blob at the IFS load address (0x400810a0 per dumpifs) once a traced PC exists:
bash scripts/diagnose-gicv3-nisv.sh --elf <scratch>/startup.* --elf-base 0x400810a0 --guest-pc <pc from trace>
# whole-library sweep for writeback MMIO stores (extends the gic_v3.c-only audit)
ntoaarch64-objdump -d <sdp>/target/qnx/aarch64le/usr/lib/libstartup.a | grep -E '(str|ldr)[a-z]* +[wx][0-9]+, \[x[0-9]+\], #' | wc -l

### D. QNX / BlackBerry filing — what to attach (no binaries)
#  hsr=0x92000045 decode, KVM_EXIT_ARM_NISV, gic_v3.c disassembly excerpt + -fno-auto-inc-dec diff (docs/findings.md 2026-09-08),
#  a1.metal cross-vendor log, request for boards/qemu-virt source or an SDP dot-release with the flag applied.
CMDS
)"
emit '```'
emit "${next_cmds//__OUT__/${out_dir_rel}}"
emit '```'
emit ""
emit "Raw files written (all redacted): $(cd "${out_dir}" && ls raw/*.txt 2>/dev/null | tr '\n' ' ')"

redact <"${S}" >"${out_dir}/summary.md"
# final pass: every text file under the results dir, in case a helper wrote directly
for f in "${out_dir}"/summary.md "${out_dir}"/raw/*.txt; do
  [[ -f "${f}" ]] || continue
  redact <"${f}" >"${work}/final" && cat "${work}/final" >"${f}"
done

echo
echo "Results: ${out_dir}"
echo
printf '| %s | %s | %s |\n' "test" "status" "detail"
echo "|---|---|---|"
for r in "${matrix[@]}"; do IFS="${sep}" read -r t st d <<<"${r}"; printf '| %s | %s | %s |\n' "$(cell "${t}")" "${st}" "$(cell "${d}")"; done | redact
