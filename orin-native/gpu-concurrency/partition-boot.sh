#!/usr/bin/env bash
# partition-boot.sh -- add, select and remove a second L4T boot entry that partitions the
# kernel: the host's housekeeping on cores 0 and 5, QEMU's cores and the probe's isolated.
# Phase 3b / A6, 2026-09-25; for run-partition.sh. The owner asked for this (2026-09-25).
#
#   partition-boot.sh status             DEFAULT, whether the entry exists, the running cmdline
#   partition-boot.sh install            save extlinux.conf, append LABEL partition
#   partition-boot.sh default LABEL      DEFAULT primary or DEFAULT partition (next boot)
#   partition-boot.sh remove             restore the saved extlinux.conf, byte for byte
#
# The entry is a copy of LABEL primary (comment lines left out) whose APPEND line gains
# PARAMS (default "isolcpus=managed_irq,domain,1-4 irqaffinity=0,5"; core 0, the boot CPU,
# cannot be isolated on this kernel). This kernel has
# CPU_ISOLATION but not NO_HZ_FULL or RCU_NOCB_CPU, so the tick itself stays: isolcpus=domain
# takes the cores out of the scheduler's load balancing and gives unbound work queues and
# init (so all of userspace) the housekeeping cores; managed_irq and irqaffinity keep device
# interrupts off the isolated ones. Nothing is changed but /boot/extlinux/extlinux.conf; the original is
# kept beside it as extlinux.conf.pre-partition with its sha256, and every write is synced
# and read back. A boot that fails needs the owner at the board: the L4T menu on the serial
# console (TIMEOUT 3 s) still offers LABEL primary.
set -u
CONF="${CONF:-/boot/extlinux/extlinux.conf}"
SAVE="$CONF.pre-partition"
PARAMS="${PARAMS:-isolcpus=managed_irq,domain,1-4 irqaffinity=0,5}"
LABEL=partition
tmp=""

die() { echo "partition-boot: $*" >&2; exit 1; }
labels() { awk '$1 == "LABEL" {print $2}' "$1"; }
default_of() { awk '$1 == "DEFAULT" {print $2}' "$1"; }
CUR="$(mktemp)"
trap 'rm -f "$CUR" "$tmp"' EXIT
sudo -n cat "$CONF" > "$CUR" || die "cannot read $CONF"

check() {   # $1 a candidate extlinux.conf: one DEFAULT naming an existing label, labels unique
	[ "$(grep -c '^DEFAULT ' "$1")" = 1 ] || return 1
	labels "$1" | grep -qx "$(default_of "$1")" || return 1
	[ "$(labels "$1" | sort | uniq -d | wc -l)" = 0 ]
}

write() {   # $1 the new content's file: install it over CONF, synced and read back
	check "$1" || die "the new extlinux.conf does not check -- nothing written"
	sudo -n cp "$1" "$CONF.new" && sudo -n sync && sudo -n mv "$CONF.new" "$CONF" && sudo -n sync \
		|| die "could not write $CONF"
	sudo -n cat "$CONF" | cmp -s "$1" - || die "$CONF does not read back as written"
}

case "${1:-}" in
status)
	echo "default: $(default_of "$CUR")"
	echo "labels: $(labels "$CUR" | tr '\n' ' ')"
	echo "saved: $([ -e "$SAVE" ] && echo yes || echo no)"
	echo "running: $(tr ' ' '\n' < /proc/cmdline | grep -E '^(isolcpus|irqaffinity)=' | tr '\n' ' ')"
	;;
install)
	check "$CUR" || die "$CONF does not check as it is -- not touching it"
	labels "$CUR" | grep -qx "$LABEL" && die "$CONF already has LABEL $LABEL"
	[ -e "$SAVE" ] && die "$SAVE exists: an earlier install was not removed"
	[ "$(default_of "$CUR")" = primary ] || die "DEFAULT is not primary"
	blk="$(awk '$1 == "LABEL" {inb = ($2 == "primary")} inb && NF && $1 !~ /^#/' "$CUR")"
	[ -n "$blk" ] || die "no LABEL primary block"
	[ "$(echo "$blk" | grep -cE '^[[:space:]]*APPEND ')" = 1 ] || die "LABEL primary has not exactly one APPEND line"
	sudo -n cp "$CONF" "$SAVE" && sudo -n sh -c "sha256sum '$CONF' | cut -d' ' -f1 > '$SAVE.sha256'" && sudo -n sync \
		|| die "could not save $CONF"
	tmp="$(mktemp)"
	{
		cat "$CUR"
		echo
		echo "$blk" | sed -e "s/^LABEL primary\$/LABEL $LABEL/" \
			-e "s/^\([[:space:]]*\)MENU LABEL .*/\1MENU LABEL partition: $PARAMS/" \
			-e "s/^\([[:space:]]*APPEND .*\)\$/\1 $PARAMS/"
	} > "$tmp"
	[ "$(labels "$tmp" | tr '\n' ' ')" = "$(labels "$CUR" | tr '\n' ' ')$LABEL " ] \
		|| die "the new file's labels are not the old ones plus $LABEL"
	[ "$(grep -c -- "$PARAMS" "$tmp")" = 2 ] || die "the new entry does not carry the parameters on MENU LABEL and APPEND"
	write "$tmp"
	echo "installed LABEL $LABEL; DEFAULT unchanged"
	;;
default)
	want="${2:-}"
	case "$want" in primary|"$LABEL") ;; *) die "default takes primary or $LABEL" ;; esac
	labels "$CUR" | grep -qx "$want" || die "$CONF has no LABEL $want"
	tmp="$(mktemp)"
	sed "s/^DEFAULT .*/DEFAULT $want/" "$CUR" > "$tmp"
	[ "$(diff "$CUR" "$tmp" | grep -c '^[<>]')" -le 2 ] || die "changing DEFAULT would change more than one line"
	write "$tmp"
	echo "DEFAULT $want (from the next boot)"
	;;
remove)
	[ -e "$SAVE" ] || die "no $SAVE to restore"
	want="$(sudo -n cat "$SAVE.sha256")" || die "no $SAVE.sha256"
	[ "$(sudo -n sha256sum "$SAVE" | cut -d' ' -f1)" = "$want" ] || die "$SAVE does not match its saved sha256"
	tmp="$(mktemp)"
	sudo -n cat "$SAVE" > "$tmp" || die "cannot read $SAVE"
	write "$tmp"
	[ "$(sudo -n sha256sum "$CONF" | cut -d' ' -f1)" = "$want" ] || die "$CONF is not the saved original after restoring"
	sudo -n rm -f "$SAVE" "$SAVE.sha256" && sudo -n sync
	echo "restored the original $CONF"
	;;
*)
	echo "usage: partition-boot.sh status | install | default primary|$LABEL | remove" >&2
	exit 2
	;;
esac
