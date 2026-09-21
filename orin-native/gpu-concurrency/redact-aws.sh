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
set -euo pipefail

filter() {
	awk -v pcuser="${USER:-}" -v awsuser="${AWS_SSH_USER:-ubuntu}" '
	function isword(c) { return (c ~ /[0-9A-Za-z_-]/) }
	# Replace every occurrence of `re` that stands alone, with `rep`.
	function mask(s, re, rep,    out, rest, tok, before, after, pos) {
		out = ""; rest = s
		while (match(rest, re)) {
			pos = RSTART
			tok = substr(rest, pos, RLENGTH)
			before = (pos > 1) ? substr(rest, pos - 1, 1) : ""
			after  = substr(rest, pos + RLENGTH, 1)
			out = out substr(rest, 1, pos - 1)
			if ((before == "" || !isword(before)) && (after == "" || !isword(after)))
				out = out rep
			else
				out = out tok
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
		while (match(rest, /[0-9a-fA-F][0-9a-fA-F](:[0-9a-fA-F][0-9a-fA-F]){5}/)) {
			tok = substr(rest, RSTART, RLENGTH)
			out = out substr(rest, 1, RSTART - 1)
			out = out ((tolower(tok) == "52:54:00:11:11:11") ? tok : "<mac>")
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
		line = mask(line, "[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]", "<account>")
		line = mask_ips(line)
		line = mask_macs(line)
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
	echo "masked direction:"
	check "instance id"   "launched i-0123456789abcdef0 ok"    "i-0123456789abcdef0" 0
	check "volume id"     "vol-0abcdef1234567890 attached"     "vol-0abcdef1234567890" 0
	check "sg id"         "using sg-0123456789abcdef0 now"     "sg-0123456789abcdef0" 0
	check "subnet id"     "in subnet-0aaaaaaaaaaaaaaa1 ok"     "subnet-0aaaaaaaaaaaaaaa1" 0
	check "account id"    "iam user 123456789012 here"         "123456789012" 0
	check "arn"           "arn:aws:iam::111122223333:user/Bob" "arn:aws" 0
	check "public ip"     "ssh to 203.0.113.7 now"             "203.0.113.7" 0
	check "private ip"    "addr 172.31.20.5/20 brd"            "172.31.20.5" 0
	check "ec2 hostname"  "root@ip-172-31-20-5 ~"              "ip-172-31-20-5" 0
	check "public dns"    "ec2-203-0-113-7.eu-central-1.compute.amazonaws.com" "203-0-113-7" 0
	check "foreign mac"   "link/ether 0a:1b:2c:3d:4e:5f brd"   "0a:1b:2c:3d:4e:5f" 0

	echo "preserved direction:"
	check "br0 addr"      "br0 192.168.100.1/24 up"            "192.168.100.1" 1
	check "guest addr"    "probe 192.168.100.10:7100"          "192.168.100.10" 1
	check "netns addr"    "netns at 192.168.100.20"            "192.168.100.20" 1
	check "loopback"      "arm A 127.0.0.1:7100"               "127.0.0.1" 1
	check "guest mac"     "mac=52:54:00:11:11:11 set"          "52:54:00:11:11:11" 1
	check "ami id"        "booted ami-0abcdef1234567890"       "ami-0abcdef1234567890" 1
	check "the figures"   "p50 181.8 us crossing 126.0 us"     "181.8" 1
	check "kernel ver"    "kernel 6.8.0-1063-aws"              "6.8.0-1063-aws" 1
	check "sha256"        "sha256 26170cd7dc74c216181db71c5"   "26170cd7dc74c216181db71c5" 1

	[ "$fail" -eq 0 ] && echo "PASS -- both directions" || { echo "SELFTEST FAILED"; exit 1; }
	exit 0
fi

filter
