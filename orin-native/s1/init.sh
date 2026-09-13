#!/bin/sh
# SPDX-License-Identifier: MIT
#
# init.sh - /init of the S1-F Linux guest's initrd.
#
# Phase 3b, results/orin-native-port/20260909T1100Z/s1-design.md section 3.5
# (option I-a). mkcpio.py packs this file as /init, mode 0755, beside the
# board initrd's own busybox, ld-linux-aarch64.so.1, libc.so.6 and
# libresolv.so.2. Its sha256 is pinned in initrd.manifest, so an edit here
# needs a new pin there, and a new initrd pin in every generator.
#
# The lines below are the host's needles on hvc0 (section 3.4):
#   S1-INIT start   after the mounts                              i_start
#   S1-INIT ready   the last line before the shell                i_ready
#   S1-HB           background heartbeat, every 60 s, 12 at most  hb
# The probe answers S1-SHELL-42-OK and S1-END-43-OK come only from the shell
# the host drives afterwards, never from this script.
#
# POSIX sh as busybox ash runs it, using only the applets the manifest links:
# sh, mount, echo, cat, uname, sleep. On purpose there is no $(( )) and no
# [ ]: shell arithmetic is what probe 1 tests, so /init must not depend on it.
# A redirection that could fail runs only in a forked child, because a failed
# redirection ends a non-interactive shell, and init ending panics the kernel.
# None names /dev/null: the archive's dev/ holds only dev/console, so
# /dev/null exists only once devtmpfs is mounted. It never reboots, halts or
# exits.

PATH=/usr/bin:/bin
export PATH

# devtmpfs is not mounted automatically on an initramfs root: DEVTMPFS_MOUNT
# acts only when the kernel mounts a real root (drivers/base/Kconfig). A
# failed mount is reported, not fatal; the archive's own dev/console node
# (c 5 1) keeps the console usable without it.
mount -t devtmpfs devtmpfs /dev
rc_dev=$?
mount -t proc proc /proc
rc_proc=$?
mount -t sysfs sysfs /sys
rc_sys=$?

echo "S1-INIT start"
echo "S1-INIT mount dev=$rc_dev proc=$rc_proc sys=$rc_sys"
echo "S1-INIT uname_r=$(uname -r)"
echo "S1-INIT cmdline=$(cat /proc/cmdline)"
echo "S1-INIT cpus_online=$(cat /sys/devices/system/cpu/online)"
cat /proc/meminfo | while IFS= read -r line; do
	case $line in
	MemTotal:*) echo "S1-INIT $line" ;;
	esac
done

# Twelve words rather than a counter, so the heartbeat needs no arithmetic.
# The twelve minutes run from here, not from the hold's start, so S1-HB is
# liveness evidence only; the hold's ten heartbeats are the host's own
# S1 HB k= lines (section 5.1 L6). ash, like dash, gives a background job
# /dev/null as stdin itself, so without devtmpfs this loop may still not
# start; the dev= line above says why.
(
	for k in 1 2 3 4 5 6 7 8 9 10 11 12; do
		sleep 60
		echo "S1-HB"
	done
) &

echo "S1-INIT ready"

# The kernel opened /dev/console as fds 0-2 before running /init. Reopen it
# explicitly for the shell, but test the open in a subshell first: a failed
# redirection on exec would end this shell and panic the kernel. The test
# opens the console for writing (2>) and then for reading (<), as exec does.
if (: </dev/console) 2>/dev/console; then
	exec sh </dev/console >/dev/console 2>&1
fi
echo "S1-INIT console_reopen=fail"
exec sh
