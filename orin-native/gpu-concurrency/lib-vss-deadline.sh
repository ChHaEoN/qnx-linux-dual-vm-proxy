# lib-vss-deadline.sh -- the deadline contract of the vss harnesses (run-vss-setup.sh, run-vss-suite.sh) on a
# bare-metal AWS session, and of remote-ladder.sh's wait-run. Sourced, never run. plan Phase 3
# (WP3g), 2026-10-03. Bash, safe to source under set -euo pipefail.
# vss_deadline_load, vss_past_stop, vss_capped and vss_cap_fired return non-zero by design, so a harness under
# set -e calls each in a condition (vss_capped's call form is under THE FUNCTIONS).
#
# THE DEADLINE. userdata.sh arms two nets, a monotonic timer and the wall-clock poweroff, and writes the absolute
# time of the wall-clock one, in epoch seconds, to /var/lib/qnx-metal-deadline (both re-armed from that file on
# every boot). This contract reads that file alone. The wall-clock poweroff is scheduled never later than the
# timer, so at the schedule the file names the earlier end; a wall clock stepped BACKWARD after it leaves the
# timer the earlier one, and stop_at, the caps and the give-up point are then late by the size of the step.
# QNX_METAL_DEADLINE_FILE names another file, for the tests and for a rehearsal off the instance.
#
# THE CONTRACT (design values, not measured ones):
#   stop_at   = deadline - 25 minutes (the margin): no unit starts at or after it.
#   check point: a harness checks before each unit (setup: before each of its steps; suite: before each run and
#             each compare) and stops when now >= stop_at: it stops cleanly (sync, QEMU stopped if it runs),
#             writes `status=TIMEOUT at=<unit> reason=deadline`, lists the units not run, and exits 0.
#   cap       = stop_at + 10 minutes - now, the unit run under `timeout --kill-after=30s <cap>`. A check between
#             units does not bound a unit (one `docker pull` may take long): the cap does. Every cap therefore
#             ends at one moment, stop_at + 10 minutes (the cap's end). When it fires the harness stops as at
#             a check point, with reason=step-timeout. timeout sends TERM to the unit's process group. Its KILL,
#             30 seconds later, goes out only while the unit's direct child still lives, and then to the whole group
#             (timeout itself included, hence 137). Once that child has died of the TERM, timeout returns 124 at
#             once, and whatever in the group ignored the TERM (the docker CLI of a container whose PID 1 ignores
#             it) outlives the cap. The harness's clean stop is what removes those (containers by docker rm -f);
#             it also stops a QEMU still shutting down (pkill, then KILL). So a unit's direct child ends at the
#             latest 10 minutes and 30 seconds after stop_at, leaving at least 14 minutes for the clean stop,
#             wait-run's return, and capture, fetch and terminate.
#   give-up   = stop_at + 12 minutes (the deadline - 13 minutes): wait-run stops waiting there (exit 2), after
#             the latest a cap can end plus time for the clean stop and sync, and the operator goes straight to
#             capture.
#
# SIGNALS (remote-ladder.sh, SIGNALS). A harness that sources this runs
# under remote-ladder.sh's detached runner with SIGPIPE, SIGHUP, SIGINT and SIGQUIT ignored: the runner's trap and
# nohup ignore PIPE and HUP, and bash ignores INT and QUIT for the runner, a command started in the background with
# no job control. Whatever the harness runs directly inherits all four, so a Python started there installs no
# KeyboardInterrupt (it sets one only when SIGINT is at its default as it starts), and a trap the harness sets on
# any of the four is void. A unit under vss_capped is a child of GNU timeout, which catches HUP, INT, QUIT and TERM
# before it forks; an exec resets a caught signal to its default, so the unit starts with only SIGPIPE ignored, and
# a Python unit (step3.py) has its KeyboardInterrupt. The cap signals with TERM and KILL, which are not ignored by
# anything the runner passes down: a unit that ignores the TERM does so itself.
#
# THE FUNCTIONS
#   vss_deadline_file   the deadline file's path
#   vss_deadline_load   sets VSS_DEADLINE and VSS_STOP_AT; returns 1, with the reason on stderr, when the file
#                       is unreadable or does not hold one epoch second (digits, no leading zero)
#   vss_now             epoch seconds (a test redefines it)
#   vss_past_stop       true at a check point that must stop: now >= stop_at
#   vss_cap_s           stop_at + 10 minutes - now, in seconds
#   vss_capped CMD...   CMD under its cap; CMD's status, or timeout's 124 (TERM) or 137 (the KILL after the
#                       kill-after, to the whole group, while the direct child still lived) when the cap fired.
#                       A cap of 0 or less runs nothing and returns 124. Under set -e call it as
#                           rc=0; vss_capped CMD... || rc=$?
#                       then test vss_cap_fired "$rc": called bare, a fired cap ends the harness at once, with
#                       no status line and no clean stop, and the detached runner records it as FAILED.
#   vss_cap_fired RC    true for 124 or 137 once now has reached the cap's end (stop_at + 10 minutes), the
#                       earliest any cap can fire. Before it a 124 or 137 is the command's own (an OOM kill's
#                       137, a container's status passed on), which the harness records as that unit's status,
#                       not as a cap. It reads the clock: call it as soon as the unit has returned.
#   vss_giveup_at       stop_at + 12 minutes, in epoch seconds
#   vss_status WORD...  appends one line `status=WORD ...` to $STATUS (the harness's status file, which the
#                       detached runner and wait-run read) and prints it (to the harness's run.log). Newlines
#                       and carriage returns in the words become spaces: a status line is one line.
#
# WHAT IT DOES NOT DO. It keeps no clock of its own and measures nothing: every value here is a design value. It
# cannot bound a unit that `timeout` cannot kill (a process in uninterruptible sleep), nor anything after the
# deadline itself, which belongs to the instance's own poweroff.

VSS_DEADLINE_FILE_DEFAULT=/var/lib/qnx-metal-deadline
VSS_MARGIN_S=1500              # stop_at = deadline - 25 minutes
VSS_OVERRUN_S=600              # a unit's cap ends at most 10 minutes after stop_at
VSS_KILL_AFTER_S=30            # timeout --kill-after
VSS_GIVEUP_AFTER_STOP_S=720    # wait-run gives up 12 minutes after stop_at (the deadline - 13 minutes)

vss_deadline_file() { printf '%s\n' "${QNX_METAL_DEADLINE_FILE:-$VSS_DEADLINE_FILE_DEFAULT}"; }

vss_deadline_load() {
	local f d
	f="$(vss_deadline_file)"
	if [ ! -r "$f" ]; then
		echo "lib-vss-deadline: no readable deadline file $f" >&2
		return 1
	fi
	d="$(head -c 64 "$f" | tr -d '\r\n')"
	case "$d" in
		''|*[!0-9]*|0*) echo "lib-vss-deadline: the deadline file $f does not hold one epoch second" >&2; return 1 ;;
	esac
	VSS_DEADLINE="$d"
	VSS_STOP_AT=$((d - VSS_MARGIN_S))
}

vss_now() { date +%s; }

vss_past_stop() { [ "$(vss_now)" -ge "$VSS_STOP_AT" ]; }

vss_cap_s() { echo $((VSS_STOP_AT + VSS_OVERRUN_S - $(vss_now))); }

vss_capped() {
	local cap
	cap="$(vss_cap_s)"
	[ "$cap" -gt 0 ] || return 124
	timeout --kill-after="${VSS_KILL_AFTER_S}s" "$cap" "$@"
}

vss_cap_fired() {   # RC: the cap's own status (124, 137) at or after the cap's end; before it, the command's own
	{ [ "$1" = 124 ] || [ "$1" = 137 ]; } && [ "$(vss_now)" -ge $((VSS_STOP_AT + VSS_OVERRUN_S)) ]
}

vss_giveup_at() { echo $((VSS_STOP_AT + VSS_GIVEUP_AFTER_STOP_S)); }

vss_status() {
	local IFS=' ' line
	line="status=$*"
	line="${line//$'\r'/ }"
	line="${line//$'\n'/ }"
	printf '%s\n' "$line" >> "${STATUS:?vss_status: STATUS is not set}"
	printf '%s\n' "$line"
}
