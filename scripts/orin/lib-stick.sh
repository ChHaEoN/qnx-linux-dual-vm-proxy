# Phase 3b (A6; the board after its upgrade to L4T R39, 2026-10-04)
# lib-stick.sh -- the installer-stick rule, one copy for every script that must refuse while the
# installer stick is in the board.
#
#   Sourced, not executed:   . "$here/lib-stick.sh"
#   Callers: provision-orin-r39.sh (apply) and gate2-smoke.sh (every step that creates a KVM VM).
#
# WHY ONE FILE. The installer's boot entry installs unattended, and a reset nobody chose would
# walk the boot order with the stick attached. Two scripts refuse on that, and a rule kept in
# two places is two rules by the second edit. The rule, its wording and its one override are
# here, and each caller says only who it is.
#
# THE RULE. A stick counts as in while a removable or USB block device is present, or anything
# is mounted under /media. A device list or a mount list that cannot be read counts as a stick.
# One kind of mount under /media does not count: the vendor's own image, which the desktop
# session mounts by itself with no stick in. A mount is taken for it only when all three hold:
# its source is a loop device, the file behind that device (the first line of
# /sys/block/<loopN>/loop/backing_file) is under /opt/nvidia/, and it is mounted read-only. With
# any one of them wrong, or the backing file not readable, the mount counts as any other. The
# text then names the image, and a removable or USB device beside it counts as before. The only
# override is PROVISION_ALLOW_REMOVABLE=1, under whichever caller, and it is the owner's to give.
#
# WHAT IT RUNS: lsblk and findmnt, once each, and one read under /sys. Nothing else, and nothing
# that changes a mount. Mount points are counted, not said; of the vendor's image the last
# component of its mount point is said, and nothing of one that sits directly under /media, where
# the desktop keeps a directory per login. The backing file's path is never said.
#
# THE CALLER sets SYSR (the /sys root; SYS_ROOT redirects it for tests, and the caller announces
# that) before it calls stick_rule. first_line is here because the rule reads sysfs with it; the
# callers use it for their own reads as well.
#
# WHAT A PASS DOES NOT SHOW: that a read-only loop mount on a file under /opt/nvidia/ is the
# vendor's image and nothing else (the file's path is all that is read of it; who may write under
# /opt/nvidia/ is not looked at); a card in the module's own slot that lsblk flags neither
# removable nor USB and that is not mounted under /media.

FL=""
STICK_WORD=""
STICK_TEXT=""

first_line() {  # FL = the first line of a file, or nothing; never an error
	FL=""
	if [ -r "$1" ]; then IFS= read -r FL < "$1" 2>/dev/null; fi
	return 0
}

# Looks, and says what it found in the two variables a caller reads:
#   STICK_WORD  ok       no stick
#               note     a stick, allowed by the owner's override
#               differs  a stick: the caller refuses
#   STICK_TEXT  the item's text, the same words whoever asks
#   usage: stick_rule <who refuses, as the subject of "refuses">
stick_rule() {
	local who="$1"
	local out rc line name removable tran found="" mounts=0 unknown="" what=""
	local target src opts label vendor=""
	local re_name='NAME="([^"]*)"' re_rm='RM="([^"]*)"' re_tran='TRAN="([^"]*)"' re_loop='^/dev/(loop[0-9]+)$'
	STICK_WORD=""; STICK_TEXT=""
	out=$(lsblk -d -n -P -o NAME,RM,TRAN,TYPE 2>/dev/null); rc=$?
	if [ "$rc" != 0 ] || [ -z "$out" ]; then
		unknown="lsblk listed no block device (exit $rc)"
	else
		while IFS= read -r line; do
			name=""; removable=""; tran=""
			if [[ "$line" =~ $re_name ]]; then name="${BASH_REMATCH[1]}"; fi
			if [[ "$line" =~ $re_rm ]]; then removable="${BASH_REMATCH[1]}"; fi
			if [[ "$line" =~ $re_tran ]]; then tran="${BASH_REMATCH[1]}"; fi
			if [ "$removable" = 1 ] || [ "$tran" = usb ]; then found="$found $name"; fi
		done <<< "$out"
	fi
	out=$(findmnt -r -n -o TARGET,SOURCE,OPTIONS 2>/dev/null); rc=$?
	if [ "$rc" != 0 ] || [ -z "$out" ]; then
		unknown="${unknown:+$unknown; }findmnt listed no mount (exit $rc)"
	else
		while read -r target src opts; do
			case "$target" in /media|/media/*) ;; *) continue ;; esac
			# One kind of mount under /media is not a stick: the vendor's own image, which the
			# desktop session mounts by itself. A mount is taken for it only when all three hold:
			# its source is a loop device, the file behind that device is under /opt/nvidia/, and
			# it is mounted read-only. A backing file that cannot be read is under nothing.
			FL=""
			if [[ "$src" =~ $re_loop ]]; then first_line "$SYSR/block/${BASH_REMATCH[1]}/loop/backing_file"; fi
			if [[ "$FL" == /opt/nvidia/* ]] && [[ ",$opts," == *,ro,* ]]; then
				# Named by the last component of its mount point. One level under /media is where
				# the desktop keeps a directory per login, so a name at that level is not said.
				label="[not shown]"
				case "$target" in /media/*/*) label="${target##*/}" ;; esac
				vendor="${vendor:+$vendor, }$label"
			else
				mounts=$((mounts + 1))
			fi
		done <<< "$out"
	fi
	if [ -n "$found" ]; then what="removable block device:$found"; fi
	if [ "$mounts" = 1 ]; then what="${what:+$what; }1 mount under /media"; fi
	if [ "$mounts" -gt 1 ]; then what="${what:+$what; }$mounts mounts under /media"; fi
	if [ -n "$unknown" ]; then what="${what:+$what; }cannot tell whether a stick is in: $unknown"; fi
	if [ -n "$vendor" ]; then
		vendor="the vendor's read-only image ($vendor: a loop device on a file under /opt/nvidia/)"
		if [ -n "$what" ]; then what="$what; not counted: $vendor"; fi
	fi
	if [ -z "$what" ] && [ -n "$vendor" ]; then
		STICK_WORD=ok
		STICK_TEXT="no removable or USB block device; under /media only $vendor, which is not a stick"
	elif [ -z "$what" ]; then
		STICK_WORD=ok
		STICK_TEXT="no removable or USB block device, nothing mounted under /media"
	elif [ "${PROVISION_ALLOW_REMOVABLE:-}" = 1 ]; then
		STICK_WORD=note
		STICK_TEXT="$what -- allowed by PROVISION_ALLOW_REMOVABLE=1, the owner's override"
	else
		STICK_WORD=differs
		STICK_TEXT="$what -- $who refuses while it is there: a reset would walk the boot order with an unattended installer attached. The owner removes it; PROVISION_ALLOW_REMOVABLE=1 is the owner's override"
	fi
}
