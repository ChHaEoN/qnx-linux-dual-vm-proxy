#!/bin/bash
# hostcheck.sh -- the host check around every run that starts a container from the Autoware image or built on it
# (sdv/aw; Phase 8 WP4b 7.1; the Phase 8 specification's 2.12, layer 3).
#
# The four host settings the image's own entrypoint would change (W4 S4): the loopback interface's flags and three
# kernel network settings. A run reads them before its first container starts and after its last is removed, into its
# directory (host-before.txt, host-after.txt), and compares the two; any difference fails the run with the setting
# named, and nothing here reverts it.
#
#   hostcheck.sh
#       prints the four, one per line after a format line, in this fixed form, and exits 0:
#           format=1
#           lo.flags=<the flags `ip -br link show lo` prints between < and >, e.g. LOOPBACK,UP,LOWER_UP>
#           net.core.rmem_max=<its value>
#           net.ipv4.ipfrag_time=<its value>
#           net.ipv4.ipfrag_high_thresh=<its value>
#       prints nothing on stdout and exits 2 when any of the four cannot be read (the reason on stderr).
#   hostcheck.sh --compare BEFORE AFTER
#       exits 0 when the two files hold the same four settings; exits 1 when one or more differ, printing one line
#       per setting that differs, in the order above, as `changed <setting> before=<value> after=<value>`; exits 2
#       when either file cannot be read or is not in the fixed form (a line missing, repeated, unknown or malformed).
#
# It reads and never sets: `ip -br link show lo` and `sysctl -n <name>`, nothing else, and it writes no file. Any other
# command line exits 2.
set -u
FORMAT=1
SYSCTLS="net.core.rmem_max net.ipv4.ipfrag_time net.ipv4.ipfrag_high_thresh"
KEYS="lo.flags $SYSCTLS"

die() {
	echo "hostcheck.sh: $*" >&2
	exit 2
}

valid() { # valid KEY VALUE: the value in the form its key takes
	case "$1" in
	format) [ "$2" = "$FORMAT" ] ;;
	lo.flags) [[ $2 =~ ^[A-Z0-9_,-]+$ ]] ;;
	*) [[ $2 =~ ^[0-9]+$ ]] ;;
	esac
}

read_host() {
	local out flags name value report in_brackets='<([^>]*)>'
	out=$(ip -br link show lo) || die "cannot read: ip -br link show lo failed"
	[[ $out =~ $in_brackets ]] || die "cannot read: no flags in lo's line: $out"
	flags=${BASH_REMATCH[1]}
	valid lo.flags "$flags" || die "cannot read: lo's flags '$flags'"
	report="format=$FORMAT"$'\n'"lo.flags=$flags"$'\n'
	for name in $SYSCTLS; do
		value=$(sysctl -n "$name") || die "cannot read: sysctl -n $name failed"
		valid "$name" "$value" || die "cannot read: $name is '$value'"
		report+="$name=$value"$'\n'
	done
	printf '%s' "$report"
}

parse() { # parse FILE ARRAY: the file's settings into the associative array named ARRAY, or exit 2
	local file=$1 line key value
	local -n into=$2
	[ -f "$file" ] && [ -r "$file" ] || die "cannot read $file"
	while IFS= read -r line || [ -n "$line" ]; do
		[[ $line == *=* ]] || die "$file: not in the fixed form: '$line'"
		key=${line%%=*}
		value=${line#*=}
		case " format $KEYS " in
		*" $key "*) ;;
		*) die "$file: unknown setting '$key'" ;;
		esac
		[ -z "${into[$key]+set}" ] || die "$file: $key twice"
		valid "$key" "$value" || die "$file: $key is '$value'"
		into[$key]=$value
	done <"$file"
	for key in format $KEYS; do
		[ -n "${into[$key]+set}" ] || die "$file: $key missing"
	done
}

compare() {
	local -A before=() after=()
	local key changed=0
	parse "$1" before
	parse "$2" after
	for key in $KEYS; do
		if [ "${before[$key]}" != "${after[$key]}" ]; then
			echo "changed $key before=${before[$key]} after=${after[$key]}"
			changed=1
		fi
	done
	return "$changed"
}

if [ "$#" -eq 0 ]; then
	read_host
elif [ "$1" = "--compare" ] && [ "$#" -eq 3 ]; then
	compare "$2" "$3"
else
	die "usage: hostcheck.sh [--compare BEFORE AFTER]"
fi
