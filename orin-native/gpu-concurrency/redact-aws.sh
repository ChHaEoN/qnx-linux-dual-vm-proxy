#!/usr/bin/env bash
# redact-aws.sh -- stdin to stdout, masking what must never reach a public repo.
#
#   usage:  <command> | redact-aws.sh > capture.log
#           redact-aws.sh selftest
#
# AT CAPTURE TIME, NOT AFTERWARDS. The project rule exists because a committed
# instance id once needed a history rewrite to remove. A filter applied while
# the bytes are being written cannot be forgotten later; a cleanup pass can.
#
# THE SUBTLETY THAT MAKES THIS NOT A ONE-LINER: some addresses in this record
# are the PROJECT'S OWN and must survive. 192.168.100.0/24 is the synthetic
# bridge subnet -- .1 is br0, .10 the QNX guest, .20 the ladder namespace -- and
# those numbers are documented in README, the plan and every ladder record.
# Masking them would protect nothing and make the capture unreadable. Same for
# the fixed guest MAC, a constant in the launch line, and for the AMI id, which
# is the opposite of a secret: it is what makes the host image reproducible. So
# this is an allowlist inside a denylist, and the selftest pins BOTH directions.
#
# NO \b, NO \y. gawk reads \b as backspace and spells word-boundary \y; mawk,
# which is what Ubuntu gives you on the instance, has neither. The first draft
# used \b and the selftest caught it leaking every id it was meant to mask --
# which is the entire reason the selftest asserts the masked direction rather
# than only checking that the allowlist survives. mask() therefore does its own
# boundary check against the surrounding characters.
#
# NO {n} INTERVALS EITHER. mawk 1.3.4-20200120, the default awk of Ubuntu 22.04, the
# release of the Orin and of a stock a1.metal at the time, does not support them:
# /x{5}/ never matches, so the MAC pattern written with {5} let every foreign MAC
# through. Found 2026-09-22 when this selftest failed in a rehearsal on the Orin.
# Patterns are spelled out instead, whatever a later mawk supports, and AWK= picks
# the implementation so the tests can run the selftest under every awk they find.
set -euo pipefail
AWK="${AWK:-awk}"

filter() {
	"$AWK" -v pcuser="${USER:-}" -v awsuser="${AWS_SSH_USER:-ubuntu}" '
	function isword(c) { return (c ~ /[0-9A-Za-z_-]/) }
	# Replace every occurrence of `re` that stands alone, with `rep`.
	#
	# `num` (optional): the token is a NUMBER, and a digit run is not a
	# standalone number if it is part of a decimal. FOUND 2026-09-21 by
	# corrupting real data: the account mask took the 12 fraction digits of a
	# latency sample, "0.100123456789," -- "." before, "," after, neither a
	# word character -- and wrote "0.<account>,", which is no longer JSON.
	#
	# The rule is deliberately NOT "a dot on either side blocks". That first
	# attempt would have let "account 123456789012." through -- a real id at
	# the end of a sentence -- which trades corrupted data for a leak. So:
	#   a "." BEFORE the run      -> it is a fraction            -> keep it
	#   a "." AFTER, then a digit -> the integer part of a decimal -> keep it
	#   a "." AFTER, then not     -> sentence punctuation        -> mask it
	# Every other mask keeps the ordinary boundary, because an AWS id beside a
	# "." still has to go.
	#
	# `prev` is the character of the INPUT just before what is left to scan:
	# "" only at the start of the line. FOUND 2026-10-04 in a capture rehearsal
	# (a made-up record): the character before a match was read from what was left,
	# so a match at its head always looked as if it began the line. After a
	# kept 12-digit match the next 12 digits of the same run were then masked
	# whenever the run ended there: a run 24, 36, ... digits long lost its last
	# 12, and a guest reply frame, zero-padded hex, lost its trailing zeros to
	# "<account>" in every file of the capture that held one. (No apostrophe in any
	# comment here: this program is a single-quoted shell word.)
	function mask(s, re, rep, num,    out, rest, tok, before, after, after2, pos, bb, ba, prev) {
		out = ""; rest = s; prev = ""
		while (match(rest, re)) {
			pos = RSTART
			tok = substr(rest, pos, RLENGTH)
			before = (pos > 1) ? substr(rest, pos - 1, 1) : prev
			after  = substr(rest, pos + RLENGTH, 1)
			after2 = substr(rest, pos + RLENGTH + 1, 1)
			out = out substr(rest, 1, pos - 1)
			bb = isword(before) || (num && before == ".")
			ba = isword(after)  || (num && after == "." && after2 ~ /[0-9]/)
			if ((before == "" || !bb) && (after == "" || !ba))
				out = out rep
			else
				out = out tok
			prev = substr(tok, length(tok), 1)
			rest = substr(rest, pos + RLENGTH)
		}
		return out rest
	}
	function mask_ips(s,   out, rest, tok) {
		out = ""; rest = s
		while (match(rest, /[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+/)) {
			tok = substr(rest, RSTART, RLENGTH)
			out = out substr(rest, 1, RSTART - 1)
			if (tok ~ /^192[.]168[.]100[.]/ || tok == "127.0.0.1" \
			    || tok == "0.0.0.0" || tok == "255.255.255.255")
				out = out tok
			else
				out = out "<ip>"
			rest = substr(rest, RSTART + RLENGTH)
		}
		return out rest
	}
	function mask_macs(s,   out, rest, tok) {
		out = ""; rest = s
		while (match(rest, /[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]:[0-9a-fA-F][0-9a-fA-F]/)) {
			tok = substr(rest, RSTART, RLENGTH)
			out = out substr(rest, 1, RSTART - 1)
			out = out ((tolower(tok) == "52:54:00:11:11:11") ? tok : "<mac>")
			rest = substr(rest, RSTART + RLENGTH)
		}
		return out rest
	}
	# IPv6 (2026-10-08). Until then only IPv4 was masked: an IPv6 address of the
	# instance in a text file of the record went into pub.tgz, and the scan after
	# the fetch refused the whole capture. THE RULE IS THE ONE OF THAT SCAN
	# (leakscan.py), so what it would refuse as an IPv6 address is masked here
	# first, and what it lets through is left as it is. A candidate is a whole run
	# of hex digits and colons with two colons or more in it. It is masked when
	#   - the character before it is not a letter, a digit or "_": a C++ scope
	#     ("impl::send") and a trace header ("TRACE_DATE::") are glued to a word,
	#     and an address is not;
	#   - it has at most seven colons, and at most four hex digits in each group;
	#   - it holds "::" or at least five colons, which a clock time ("13:20:34")
	#     and the epoch of a package version ("1:9.8") do not;
	#   - it is not six pairs, a MAC: mask_macs has been over the line, and the
	#     one it kept is the guest;
	#   - it is not the link-local address of the guest, which follows from that
	#     fixed MAC.
	# The match is the leftmost run with two colons, taken whole: the pattern ends
	# in a class that takes every hex digit and colon, so what follows a match is
	# neither. AFTER mask_ips: in an IPv4-mapped address the run ends at the first
	# ".", and masked first it would leave the last three numbers of the IPv4
	# part in the line. No {n}, as everywhere here, and no apostrophe (see mask).
	function mask_ipv6(s,   out, rest, tok, before, prev, n, i, g, ok, pairs) {
		if (index(s, ":") == 0) return s
		out = ""; rest = s; prev = ""
		while (match(rest, /[0-9a-fA-F]*:[0-9a-fA-F]*:[0-9a-fA-F:]*/)) {
			tok = substr(rest, RSTART, RLENGTH)
			before = (RSTART > 1) ? substr(rest, RSTART - 1, 1) : prev
			n = split(tok, g, ":")
			ok = (before !~ /[0-9A-Za-z_:]/) && n <= 8 && (index(tok, "::") > 0 || n >= 6)
			pairs = (n == 6)
			for (i = 1; i <= n; i++) {
				if (length(g[i]) > 4) ok = 0
				if (length(g[i]) != 2) pairs = 0
			}
			if (pairs || tolower(tok) == "fe80::5054:ff:fe11:1111") ok = 0
			out = out substr(rest, 1, RSTART - 1) (ok ? "<ipv6>" : tok)
			prev = substr(tok, length(tok), 1)
			rest = substr(rest, RSTART + RLENGTH)
		}
		return out rest
	}
	{
		line = $0
		# THE PATTERNS ARE STRINGS, NOT /regex/ CONSTANTS. A regex constant
		# passed as a function argument is evaluated as a boolean against $0,
		# so mask() received 1 or 0, matched the literal "1", and every id
		# sailed through while the allowlist got shredded. The selftest caught
		# it -- which is exactly why it asserts the masked direction and not
		# just that the kept tokens survive.
		H = "[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]+"
		# EC2-assigned hostnames first: they embed the private address, so
		# masking the address first would leave "ip-<ip>" behind.
		line = mask(line, "ip-[0-9]+-[0-9]+-[0-9]+-[0-9]+([.][a-z0-9.-]+)?", "<host>")
		line = mask(line, "ec2-[0-9]+-[0-9]+-[0-9]+-[0-9]+[.][a-z0-9.-]+",   "<host>")
		# AWS resource ids. ami- is deliberately absent: it is provenance.
		line = mask(line, "i-" H,      "<instance-id>")
		line = mask(line, "vol-" H,    "<volume-id>")
		line = mask(line, "sg-" H,     "<sg-id>")
		line = mask(line, "subnet-" H, "<subnet-id>")
		line = mask(line, "vpc-" H,    "<vpc-id>")
		line = mask(line, "eni-" H,    "<eni-id>")
		line = mask(line, "snap-" H,   "<snapshot-id>")
		gsub(/arn:aws[a-z-]*:[^ ]+/, "<arn>", line)
		line = mask(line, "[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]", "<account>", 1)
		line = mask_ips(line)
		line = mask_macs(line)
		line = mask_ipv6(line)
		if (pcuser  != "") gsub(pcuser, "<user>", line)
		if (awsuser != "") line = mask(line, "@" awsuser "$", "@<user>")
		print line
	}'
}

if [ "${1:-}" = "selftest" ]; then
	fail=0
	check() { # label | input | token | 1=must-keep 0=must-be-gone
		got="$(printf '%s\n' "$2" | filter)"
		if [ "$4" = "1" ]; then
			case "$got" in *"$3"*) ;; *) echo "  FAIL [$1] dropped '$3' -> $got"; fail=1;; esac
		else
			case "$got" in *"$3"*) echo "  FAIL [$1] LEAKED '$3' -> $got"; fail=1;; *) ;; esac
		fi
	}
	# Fixtures are documentation values only (AWS's example account ids, RFC 5737
	# addresses, synthetic resource ids). Until 2026-09-22 they were real values
	# from this account, which is exactly what this filter exists to keep out.
	echo "masked direction:"
	check "instance id"   "launched i-0123456789abcdef0 ok"    "i-0123456789abcdef0" 0
	check "volume id"     "vol-0abcdef1234567890 attached"     "vol-0abcdef1234567890" 0
	check "sg id"         "using sg-0123456789abcdef0 now"     "sg-0123456789abcdef0" 0
	check "subnet id"     "in subnet-0aaaaaaaaaaaaaaa1 ok"     "subnet-0aaaaaaaaaaaaaaa1" 0
	check "account id"    "iam user 123456789012 here"         "123456789012" 0
	check "arn"           "arn:aws:iam::111122223333:user/Bob" "arn:aws" 0
	check "public ip"     "ssh to 203.0.113.7 now"             "203.0.113.7" 0
	check "private ip"    "addr 10.0.0.5/20 brd"            "10.0.0.5" 0
	check "ec2 hostname"  "root@ip-10-0-0-5 ~"              "ip-10-0-0-5" 0
	check "public dns"    "ec2-203-0-113-7.eu-central-1.compute.amazonaws.com" "203-0-113-7" 0
	check "foreign mac"   "link/ether 0a:1b:2c:3d:4e:5f brd"   "0a:1b:2c:3d:4e:5f" 0
	# 2026-10-08: IPv6, by the rule of the scan after the fetch (mask_ipv6). RFC 3849's
	# documentation prefix and link-local values; none is a host's. "mapped v6, v4" pins the
	# order: masked before the IPv4 pass, the address would leave ".0.113.7" behind.
	check "link-local v6" "inet6 fe80::1%ens5 scope link"      "fe80::1" 0
	check "bracketed v6"  "ssh to [2001:db8::1]:22 now"        "2001:db8::1" 0
	check "mapped v6"     "peer ::ffff:203.0.113.7 said"       "ffff" 0
	check "mapped v6, v4" "peer ::ffff:203.0.113.7 said"       "113" 0
	check "full v6"       "route 2001:db8:0:0:0:0:0:1 dev"     "2001:db8" 0
	check "upper-case v6" "ADDR FE80::ABCD:1 UP"               "FE80" 0
	check "another guest" "fe80::5054:ff:fe11:1112 is not it"  "fe80::" 0

	echo "preserved direction:"
	check "br0 addr"      "br0 192.168.100.1/24 up"            "192.168.100.1" 1
	check "guest addr"    "probe 192.168.100.10:7100"          "192.168.100.10" 1
	check "netns addr"    "netns at 192.168.100.20"            "192.168.100.20" 1
	check "loopback"      "arm A 127.0.0.1:7100"               "127.0.0.1" 1
	check "guest mac"     "mac=52:54:00:11:11:11 set"          "52:54:00:11:11:11" 1
	check "ami id"        "booted ami-0abcdef1234567890"       "ami-0abcdef1234567890" 1
	check "the figures"   "p50 111.1 us crossing 22.2 us"       "111.1" 1
	check "kernel ver"    "kernel 6.8.0-1063-aws"              "6.8.0-1063-aws" 1
	check "sha256"        "sha256 26170cd7dc74c216181db71c5"   "26170cd7dc74c216181db71c5" 1
	# 2026-10-08: what only looks like an IPv6 address. The guest link-local address follows
	# from its fixed MAC; the rest is data. (No kept line here may hold the login of the host
	# the capture runs on, which the filter masks: the package version below is made up.)
	check "guest link-local" "link fe80::5054:ff:fe11:1111/64 scope" "fe80::5054:ff:fe11:1111/64" 1
	check "clock time"    "at 13:20:34 on 2026-10-08T13:20:34Z" "at 13:20:34 on 2026-10-08T13:20:34Z" 1
	check "package epoch" "qemu 1:9.8.7+ds-0example1.23 here"  "1:9.8.7+ds-0example1.23" 1
	check "c++ scope"     "in client_endpoint_impl::send, x_::1" "client_endpoint_impl::send, x_::1" 1
	check "trace header"  "TRACE_DATE:: Sun 08:20:16 SEC:: 3125" "TRACE_DATE:: Sun 08:20:16 SEC:: 3125" 1
	check "five hex, nine groups" "sum 12345:6:7:8:9:a of 1:2:3:4:5:6:7:8:9" "12345:6:7:8:9:a of 1:2:3:4:5:6:7:8:9" 1
	# 2026-09-21: the account mask corrupted a real latency sample. Both
	# directions pinned -- the data must survive AND a real id must not.
	check "12-digit fraction" "0.0012345678, 0.100123456789, 0.5000" "0.100123456789" 1
	check "decimal integer"   "value 123456789012.75 ms"            "123456789012.75" 1
	check "fraction, EOL"     "p50 0.100123456789"                  "0.100123456789" 1

	echo "masked direction, numeric edge cases:"
	check "id then period"    "the account is 111122223333."        "111122223333" 0
	check "id in parens"      "owner (444455556666) set"            "444455556666" 0
	check "id then comma"     "123456789012, then"                  "123456789012" 0

	# 2026-10-04: mask() read the character before a match as "" whenever the match began at the
	# head of what was left, so after a kept 12-digit match the last 12 digits of a run 24, 36, ... long were
	# masked. A guest's reply frame (128 hex characters, zero-padded) lost its trailing zeros that way in every
	# file of a rehearsal capture that held one. Both directions pinned; the frame is synthetic.
	frame="07000000000000004a1b2c3daf0000001f0168ea684d$(printf '%036d' 0)04$(printf '%046d' 0)"
	echo "preserved direction, a digit run a multiple of 12 long:"
	check "24 digits"         "x000000000000000000000000"           "x000000000000000000000000" 1
	check "24 digits, comma"  "n 123456789012123456789012,"         "n 123456789012123456789012," 1
	check "36 digits, EOL"    "n 123456789012123456789012123456789012" "n 123456789012123456789012123456789012" 1
	check "reply frame"       "\"frame\":\"$frame\",\"reason\":0"    "\"$frame\"" 1
	echo "masked direction, after a kept run:"
	check "run, then an id"   "x000000000000000000000000 then 111122223333" "111122223333" 0
	check "two ids"           "123456789012 444455556666"           "444455556666" 0

	[ "$fail" -eq 0 ] && echo "PASS -- both directions" || { echo "SELFTEST FAILED"; exit 1; }
	exit 0
fi

filter
