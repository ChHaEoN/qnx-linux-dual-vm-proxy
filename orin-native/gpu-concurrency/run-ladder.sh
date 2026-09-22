#!/usr/bin/env bash
# run-ladder.sh -- the attribution ladder of docs/measurement-design.md §3.2.
#
# WHY A LADDER. The published figure is one blended number: it covers the Linux
# stack, virtio-net, the bridge, the tap, the guest's io-sock, the guest
# scheduler and the monitor's own work, with no way to attribute any of it. The
# reference papers decompose with QNX kernel tracing; this does it with arms of
# the SAME client against the SAME server program, changing only the path.
#
#   A  loopback   client -> 127.0.0.1               the instrument's own floor
#   B  bridge     client -> br0 -> veth/netns       bridge datapath cost
#   C  null       client -> guest, echo server      guest path, no judging
#   D  guest      client -> guest, safety monitor   the published path
#
# ARM C IS OPT-IN (ARM_C_PORT=7000). Without it, D-B is reported as "the
# crossing" when it is really the crossing PLUS the monitor's own read, verdict
# and write inside the guest. On a1.metal on 2026-09-21, C and D landed 0.04 us
# apart: the monitor's own work is not measurable against the transport.
#
# B USES A NETWORK NAMESPACE ON PURPOSE. Sending to br0's own address
# (192.168.100.1) does NOT cross the bridge: Linux routes a local address via
# loopback and short-circuits the datapath, so that arm would have measured the
# same thing as A while looking like it measured the bridge. A veth peer inside
# a namespace is on the far side of br0, so the traffic is really bridged.
#
# WHY k, NOT n (OD11). Within one run of 3000 samples the median is pinned to
# +/-0.2%, but between two runs of the same arm it moves 13.3%. So n is 1000 and
# the budget goes to k interleaved rounds. These arms carry no load, so unlike
# run-interference.sh and run-saturation.sh they need no counterbalancing.
#
# A LEFTOVER SERVER IS REFUSED. Arm A reaches 127.0.0.1:7100 by address, so an
# old monitor-native still running from an earlier session would answer it --
# the new one would fail to bind, and the reachability check would pass against
# the wrong process. Found by review, pre-existing; now checked before start.
#
# UDP ARMS (owner decision OD12, 2026-09-21), opt-in with UDP=1. The same four
# rungs over UDP, beside the TCP rungs in the SAME run: A-udp and B-udp against
# the native monitor in UDP mode (port PORT_UDP, default 7101) on the host and
# in the namespace, D-udp against the guest's monitor in UDP mode, and C-udp
# against the guest's echo server in UDP mode (ARM_C_UDP_PORT, default unset).
# Distinct ports on purpose: a TCP/UDP mix-up must fail, not answer with the
# other transport's figure. The guest must run an image that starts both UDP
# servers; the run refuses if a UDP rung does not answer. Which transport goes
# first alternates by round, so position in the round is not folded into
# UDP - TCP. The summary pairs each UDP rung with its TCP rung.
#
# A UDP stall stops the ladder like a TCP one (STALL_POLICY=refuse, set below),
# and on UDP a lost datagram cannot be told from a stalled guest: the first run
# keeps the TCP rule (an implementation choice of 2026-09-22, recorded under
# OD12). If it bites, the evidence is probe.log's "FATAL desync" line for that
# -udp tag.
#
# SHM ARMS (OD12, 2026-09-22), opt-in with SHM=1: the frame through shared
# memory instead of a network stack (ipc-test/common/shm_chan.h). Two rungs:
#   A-shm  probe -> native monitor on the host, through a file in /dev/shm
#          (SHM_HOST_FILE): the same slot with no partition in the way
#   D-shm  probe -> the guest's monitor, through QEMU's ivshmem device, whose
#          memory is the host file IVSHMEM
# There is no B or C rung: no bridge is involved, and the guest image runs no
# shm echo server. BOTH ENDS POLL -- there is no interrupt on this path -- so
# during an shm arm the probe holds its core and the monitor holds one core
# (host) or one vCPU (guest); that cost belongs to the figure. The running QEMU
# must have been launched with IVSHMEM behind -device ivshmem-plain (checked
# from its own command line), and the probe's end is libshmchan.so, built here
# from shmchan.c.
#
# NOTIFIED SHM ARMS (OD12, 2026-09-22), opt-in with KICK=1 and DB=1: the same
# slot (at SLOT_OFF, clear of the polled one), and nobody spins (shm_chan.h).
#   A-kick  probe <-> host monitor, a kick byte each way over a UNIX socket
#   C-kick  probe <-> the guest's shmkick monitor over the virtio console, one
#           byte echoed, no slot: the bare notification round trip
#   D-kick  probe <-> the guest's shmkick monitor: kick over the virtio console,
#           the reply kicked back over it
#   A-db    as A-kick, but the host monitor answers by writing the probe's
#           eventfd, learned as a peer of a host-side ivshmem server
#   D-db    as D-kick, but the guest answers by writing the ivshmem Doorbell
#           register, which KVM turns into a write to the probe's eventfd
# QEMU 6.2's ivshmem-doorbell interrupts a guest only by MSI-X, which this guest
# cannot have, so host->guest is the virtio console in every guest arm and only
# guest->host varies between D-kick and D-db. The running QEMU must present
# ivshmem-doorbell on IVSHMEM_SERVER and a virtconsole on KICK_SOCK (checked from
# its command line), with the server alive on CORE_AUX. With DB=1 the run first
# PROVES the doorbell path: one exchange answered by DB_BURST doorbells must
# deliver all of them and raise the VM's mmio_exit_kernel by at least that many
# while mmio_exit_user stays at background -- otherwise the doorbells are taking
# QEMU's userspace path and D-db would not measure what it is called; the run
# refuses. KVM_STATS=1 snapshots the VM's KVM counters and QEMU's per-thread
# schedstat around every arm (lib-measure.sh m_kvm_snap). UDP_IN_TCP=1 puts D-udp
# in the tcp group, a datagram comparator without a fifth group.
#
# TRANSPORT ORDER. With more than one transport, the order of the transport
# groups in each round follows a Williams design over the groups (as the loaded
# arms elsewhere do), so K must be a multiple of its period: 2 for two
# transports (TCP first in odd rounds, as before), 6 for three. A K that breaks
# the balance is refused rather than recorded as balanced.
#
# The shared controls live in lib-measure.sh, one copy for all three scripts.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -r "$here/lib-measure.sh" ] || { echo "FATAL: lib-measure.sh not found beside $0" >&2; exit 1; }
. "$here/lib-measure.sh"
[ "${MEASURE_LIB_LOADED:-}" = 1 ] || { echo "FATAL: lib-measure.sh did not load" >&2; exit 1; }
[ $# -eq 0 ] || die "positional arguments are not read (set N=, K= in the environment); got: $*"

N="${N:-1000}"
K="${K:-12}"
WARMUP="${WARMUP:-200}"
INTERVAL_MS="${INTERVAL_MS:-2}"
PORT="${PORT:-7100}"
ARM_C_PORT="${ARM_C_PORT:-}"
UDP="${UDP:-0}"
PORT_UDP="${PORT_UDP:-7101}"
ARM_C_UDP_PORT="${ARM_C_UDP_PORT:-}"
SHM="${SHM:-0}"
SHM_HOST_FILE="${SHM_HOST_FILE:-/dev/shm/a6-shm-host}"
IVSHMEM="${IVSHMEM:-/dev/shm/a6-ivshmem}"
KICK="${KICK:-0}"
DB="${DB:-0}"
UDP_IN_TCP="${UDP_IN_TCP:-0}"
KVM_STATS="${KVM_STATS:-0}"
DB_BURST="${DB_BURST:-10000}"
SLOT_OFF="${SLOT_OFF:-4096}"
KICK_SOCK="${KICK_SOCK:-/tmp/a6-kick.sock}"
IVSHMEM_SERVER="${IVSHMEM_SERVER:-/tmp/a6-ivshmem.sock}"
HOST_IVSHM_SOCK="${HOST_IVSHM_SOCK:-/tmp/a6-ivshmem-host.sock}"
HOST_KICK_SOCK="${HOST_KICK_SOCK:-/tmp/a6-kick-host.sock}"
CORE_AUX="${CORE_AUX:-5}"        # the ivshmem servers and the KVM counter reader
STALL_POLICY=refuse              # the ladder's figures are headlines: any stall stops it
case "$UDP" in 0|1) ;; *) die "UDP='$UDP' must be 0 or 1" ;; esac
case "$SHM" in 0|1) ;; *) die "SHM='$SHM' must be 0 or 1" ;; esac
for v in KICK DB UDP_IN_TCP KVM_STATS; do
	case "${!v}" in 0|1) ;; *) die "$v='${!v}' must be 0 or 1" ;; esac
done
case "$DB_BURST" in ''|*[!0-9]*) die "DB_BURST='$DB_BURST' is not a count" ;; esac
# At least 1000, so the ordinary console-RX user exits during the burst cannot
# fail the proof's "under a tenth" bound; at most the monitor's SHM_BURST_MAX.
[ "$DB_BURST" -ge 1000 ] && [ "$DB_BURST" -le 100000 ] || die "DB_BURST=$DB_BURST must be 1000..100000"
[ "$UDP$UDP_IN_TCP" = 11 ] && die "UDP_IN_TCP=1 needs UDP=0: with UDP=1, D-udp is already in the udp group"
case "$SLOT_OFF" in ''|*[!0-9]*) die "SLOT_OFF='$SLOT_OFF' is not a byte offset" ;; esac
[ $((SLOT_OFF % 4096)) -eq 0 ] && [ "$SLOT_OFF" -gt 0 ] || die "SLOT_OFF=$SLOT_OFF must be a non-zero multiple of 4096 (the polled slot is at 0)"
case "$PORT_UDP" in ''|*[!0-9]*) die "PORT_UDP='$PORT_UDP' is not a port number" ;; esac
case "$ARM_C_UDP_PORT" in *[!0-9]*) die "ARM_C_UDP_PORT='$ARM_C_UDP_PORT' is not a port number" ;; esac
case "$K" in ''|*[!0-9]*) die "K='$K' is not a round count" ;; esac
TGROUPS=(tcp)
[ "$UDP" = 1 ] && TGROUPS+=(udp)
[ "$SHM" = 1 ] && TGROUPS+=(shm)
[ "$KICK" = 1 ] && TGROUPS+=(kick)
[ "$DB" = 1 ] && TGROUPS+=(db)
if [ "${#TGROUPS[@]}" -gt 1 ]; then
	TPERIOD="$(m_williams_period "${#TGROUPS[@]}")"
	[ $((K % TPERIOD)) -eq 0 ] \
		|| die "${#TGROUPS[@]} transports (${TGROUPS[*]}) need K to be a multiple of $TPERIOD so their order is balanced; K=$K"
fi
GUEST="${GUEST:-192.168.100.10}"
NS="ladder"
NS_IP="192.168.100.20"
PROBE="$HOME/interference/latency_probe.py"
MON="$HOME/ladder/monitor-native"
SHM_COMMON="${SHM_COMMON:-$here/../../ipc-test/common}"

CORE_MON="${CORE_MON:-3}"        # native monitor, host side and namespace side
CORE_PROBE="${CORE_PROBE:-4}"    # the instrument, off the measured cores
FIFO_ARMS=""                     # every arm runs the probe at SCHED_OTHER; the gate checks it
SAMPLE_WINDOW=0                  # no window sampler: these are the headline numbers, and a
                                 # sampler running beside them would be a new perturbation
QEMU_CORES="${QEMU_CORES:-0-2}"  # guest vCPUs + QEMU I/O thread

cleanup() {
	say "cleanup"
	# By argv[0], never by pattern: see m_pids_of in lib-measure.sh.
	for p in $(m_pids_of monitor-native); do kill "$p" 2>/dev/null; sudo kill "$p" 2>/dev/null; done
	sudo ip netns pids "$NS" 2>/dev/null | while read -r p; do sudo kill "$p" 2>/dev/null; done
	sudo ip netns del "$NS" 2>/dev/null
	sudo ip link del veth-l 2>/dev/null
	[ -n "${HOST_SRV_PID:-}" ] && kill "$HOST_SRV_PID" 2>/dev/null
	[ "$KICK$DB" != 00 ] && rm -f "$HOST_KICK_SOCK" "$HOST_IVSHM_SOCK" "$HOST_IVSHM_SOCK.ready"
	[ "$SHM$KICK$DB" != 000 ] && rm -f "$SHM_HOST_FILE"
	m_cstate_restore
	m_governor_restore
}

# ---------------------------------------------------------------- preflight
# Checked BEFORE the trap is set, so a refusal here cannot kill a server this
# run did not start.
[ -n "$(m_pids_of monitor-native)" ] \
	&& die "a monitor-native is already running; it would answer arm A in place of this run's. Stop it first."
[ -x "$MON" ] || die "$MON missing -- run build-monitor-native.sh on this host"
[ -r "$PROBE" ] || die "missing: $PROBE"
if [ "$SHM$KICK$DB" != 000 ]; then
	[ -r "$here/shmchan.c" ] || die "missing: $here/shmchan.c"
	[ -r "$SHM_COMMON/shm_chan.h" ] || die "missing: $SHM_COMMON/shm_chan.h (set SHM_COMMON to ipc-test/common)"
	[ -e "$SHM_HOST_FILE" ] && die "$SHM_HOST_FILE exists -- a leftover from another run; remove it first"
	# The guest's end must be THIS file: read from the running QEMU itself.
	qp="$(m_pids_of qemu-system-aarch64)"
	[ -n "$qp" ] || die "no qemu-system-aarch64 is running"
	[ "$(printf '%s\n' "$qp" | grep -c .)" = 1 ] || die "more than one qemu-system-aarch64 is running"
	qcmd="$(tr '\0' ' ' < "/proc/$qp/cmdline")"
	case "$qcmd" in
		*ivshmem-doorbell*)
			# The doorbell device's memory comes from the server: QEMU must hold
			# an fd to $IVSHMEM, and its chardev must be that server's socket.
			case "$qcmd" in *"path=$IVSHMEM_SERVER "*|*"path=$IVSHMEM_SERVER,"*) ;;
				*) die "the running QEMU's ivshmem-doorbell does not use the server $IVSHMEM_SERVER" ;; esac
			case "$qcmd" in *ioeventfd=off*) die "the running QEMU has ivshmem ioeventfd=off" ;; esac
			ls -l "/proc/$qp/fd/" 2>/dev/null | grep -q -- "-> $IVSHMEM\$" \
				|| die "the running QEMU holds no fd to $IVSHMEM -- is the server serving another file?"
			;;
		*"mem-path=$IVSHMEM,"*|*"mem-path=$IVSHMEM "*)
			case "$qcmd" in *ivshmem-plain*) ;; *) die "the running QEMU has no ivshmem device on $IVSHMEM" ;; esac
			[ "$KICK$DB" = 00 ] || die "KICK/DB need ivshmem-doorbell; the running QEMU has ivshmem-plain"
			;;
		*) die "the running QEMU does not back an ivshmem device with $IVSHMEM -- relaunch with IVSHMEM=$IVSHMEM" ;;
	esac
	if [ "$KICK$DB" != 00 ]; then
		case "$qcmd" in *"path=$KICK_SOCK,"*virtconsole*|*virtconsole*"path=$KICK_SOCK,"*) ;;
			*) die "the running QEMU has no virtconsole on $KICK_SOCK -- relaunch with KICK_SOCK=$KICK_SOCK" ;; esac
		[ -S "$KICK_SOCK" ] || die "$KICK_SOCK is not a socket"
		[ -r "$SHM_COMMON/ivshm_client.c" ] || die "missing: $SHM_COMMON/ivshm_client.c"
		[ -r "$here/ivshmem_server.py" ] || die "missing: $here/ivshmem_server.py"
		GUEST_SRV_PID="$(cat "$IVSHMEM_SERVER.ready" 2>/dev/null)"
		[ -n "$GUEST_SRV_PID" ] && kill -0 "$GUEST_SRV_PID" 2>/dev/null \
			|| die "the guest's ivshmem server (pid file $IVSHMEM_SERVER.ready) is not running"
		GUEST_SRV_AFF="$(taskset -pc "$GUEST_SRV_PID" 2>/dev/null | sed 's/.*: //')"
		[ "$GUEST_SRV_AFF" = "$CORE_AUX" ] || die "the guest's ivshmem server runs on '$GUEST_SRV_AFF', not CORE_AUX=$CORE_AUX"
		# The server must serve THIS file on THIS socket, by its own arguments.
		GUEST_SRV_ARGS="$(tr '\0' '\n' < "/proc/$GUEST_SRV_PID/cmdline")"
		GUEST_SRV_SCRIPT="$(printf '%s\n' "$GUEST_SRV_ARGS" | grep -m1 'ivshmem_server.py$')"
		printf '%s\n' "$GUEST_SRV_ARGS" | grep -A1 -x -- --shm | tail -1 | grep -qx -- "$IVSHMEM" \
			|| die "the guest's ivshmem server does not serve $IVSHMEM"
		printf '%s\n' "$GUEST_SRV_ARGS" | grep -A1 -x -- --socket | tail -1 | grep -qx -- "$IVSHMEM_SERVER" \
			|| die "the guest's ivshmem server is not listening on $IVSHMEM_SERVER"
	fi
	[ -e "$HOST_KICK_SOCK" ] || [ -e "$HOST_IVSHM_SOCK" ] \
		&& [ "$KICK$DB" != 00 ] && die "$HOST_KICK_SOCK or $HOST_IVSHM_SOCK exists -- a leftover; remove it first"
fi
trap cleanup EXIT

m_prepare_out "${OUT:-}" "$HOME/ladder-out"
m_check_cores "$QEMU_CORES" "$CORE_MON" "$CORE_PROBE" "$CORE_AUX"
m_require_disjoint "qemu=$QEMU_CORES" "monitor=$CORE_MON" "probe=$CORE_PROBE" "aux=$CORE_AUX"
say "cores: $NCPU total; qemu=$QEMU_CORES monitor=$CORE_MON probe=$CORE_PROBE"
m_governor_pin
m_cstate_apply
m_pin_qemu "$QEMU_CORES"

# ---------------------------------------------------------------- arm B setup
sudo ip netns del "$NS" 2>/dev/null
sudo ip link del veth-l 2>/dev/null
sudo ip netns add "$NS" || die "ip netns add failed"
sudo ip link add veth-l type veth peer name veth-ns || die "veth create failed"
sudo ip link set veth-l master br0 up || die "could not enslave veth-l to br0 -- does br0 exist?"
sudo ip link set veth-ns netns "$NS"
sudo ip netns exec "$NS" ip addr add "$NS_IP/24" dev veth-ns
sudo ip netns exec "$NS" ip link set veth-ns up
sudo ip netns exec "$NS" ip link set lo up
say "netns $NS up at $NS_IP behind br0"

# one native monitor on the host (arm A, INADDR_ANY), one in the namespace
# (arm B). Same source as the guest's -- one source, two targets, no #ifdef.
taskset -c "$CORE_MON" "$MON" "$PORT" > "$OUT/monitor-host.log" 2>&1 &
MON_HOST=$!
sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$MON" "$PORT" \
	> "$OUT/monitor-ns.log" 2>&1 &
if [ "$SHM$KICK$DB" != 000 ]; then
	m_build_shmchan "$here/shmchan.c" "$SHM_COMMON" "$OUT/libshmchan.so"
	# A fresh, zeroed page set for the host rungs: no magic, no counters.
	dd if=/dev/zero of="$SHM_HOST_FILE" bs=4096 count=256 status=none || die "could not create $SHM_HOST_FILE"
fi
if [ "$SHM" = 1 ]; then
	taskset -c "$CORE_MON" "$MON" shm "$SHM_HOST_FILE" > "$OUT/monitor-host-shm.log" 2>&1 &
	MON_HOST_SHM=$!
fi
if [ "$KICK$DB" != 00 ]; then
	# The host rungs' own ivshmem server, on the same file, and the host's
	# notified monitor as its first peer.
	taskset -c "$CORE_AUX" python3 "$here/ivshmem_server.py" --socket "$HOST_IVSHM_SOCK" --shm "$SHM_HOST_FILE" \
		--ready "$HOST_IVSHM_SOCK.ready" > "$OUT/ivshmem-server-host.log" 2>&1 &
	HOST_SRV_PID=$!
	for i in $(seq 1 50); do [ -s "$HOST_IVSHM_SOCK.ready" ] && break; sleep 0.1; done
	[ -s "$HOST_IVSHM_SOCK.ready" ] || die "the host ivshmem server did not come up -- see $OUT/ivshmem-server-host.log"
	taskset -c "$CORE_MON" "$MON" shmkick "$HOST_IVSHM_SOCK@$SLOT_OFF" "$HOST_KICK_SOCK" > "$OUT/monitor-host-kick.log" 2>&1 &
	MON_HOST_KICK=$!
fi
if [ "$UDP" = 1 ]; then
	taskset -c "$CORE_MON" "$MON" "$PORT_UDP" udp > "$OUT/monitor-host-udp.log" 2>&1 &
	MON_HOST_UDP=$!
	sudo ip netns exec "$NS" taskset -c "$CORE_MON" "$MON" "$PORT_UDP" udp \
		> "$OUT/monitor-ns-udp.log" 2>&1 &
fi
sleep 2
kill -0 "$MON_HOST" 2>/dev/null || die "host monitor-native exited -- see $OUT/monitor-host.log (port in use?)"
if [ "$UDP" = 1 ]; then
	kill -0 "$MON_HOST_UDP" 2>/dev/null \
		|| die "host monitor-native (udp) exited -- see $OUT/monitor-host-udp.log (port in use?)"
	# Positive check, not only liveness: a monitor-native built before OD12
	# ignores "udp", listens on TCP, and stays alive.
	for l in "$OUT/monitor-host-udp.log" "$OUT/monitor-ns-udp.log"; do
		grep -q ":$PORT_UDP/udp" "$l" \
			|| die "$(basename "$l" .log) did not start in UDP mode -- rebuild $MON with build-monitor-native.sh (a pre-OD12 binary ignores 'udp' and serves TCP)"
	done
fi
if [ "$SHM" = 1 ]; then
	kill -0 "$MON_HOST_SHM" 2>/dev/null \
		|| die "host monitor-native (shm) exited -- see $OUT/monitor-host-shm.log (built before the shm transport?)"
	grep -q "serving shm on file $SHM_HOST_FILE," "$OUT/monitor-host-shm.log" \
		|| die "monitor-host-shm did not start in shm mode on $SHM_HOST_FILE -- see $OUT/monitor-host-shm.log"
fi
if [ "$KICK$DB" != 00 ]; then
	kill -0 "$MON_HOST_KICK" 2>/dev/null \
		|| die "host monitor-native (shmkick) exited -- see $OUT/monitor-host-kick.log (built before the notified variant?)"
	grep -q "serving shm-kick on ivshmem server $HOST_IVSHM_SOCK as peer " "$OUT/monitor-host-kick.log" \
		|| die "monitor-host-kick did not start in shmkick mode -- see $OUT/monitor-host-kick.log"
fi

# ---------------------------------------------------------------- arm set
ARMS=("A-loopback 127.0.0.1 $PORT tcp" "B-bridge $NS_IP $PORT tcp")
[ -n "$ARM_C_PORT" ] && ARMS+=("C-null $GUEST $ARM_C_PORT tcp")
ARMS+=("D-guest $GUEST $PORT tcp")
[ "$UDP_IN_TCP" = 1 ] && ARMS+=("D-udp $GUEST $PORT_UDP udp")
UARMS=()
UDP_ARMS=""
if [ "$UDP" = 1 ]; then
	UARMS=("A-udp 127.0.0.1 $PORT_UDP udp" "B-udp $NS_IP $PORT_UDP udp")
	[ -n "$ARM_C_UDP_PORT" ] && UARMS+=("C-udp $GUEST $ARM_C_UDP_PORT udp")
	UARMS+=("D-udp $GUEST $PORT_UDP udp")
fi
SARMS=()
SHM_ARMS=""
[ "$SHM" = 1 ] && SARMS=("A-shm $SHM_HOST_FILE - shm" "D-shm $IVSHMEM - shm")
KARMS=(); DBARMS=(); KICK_ARMS=""; DB_ARMS=""; ECHO_ARMS=""
[ "$KICK" = 1 ] && KARMS=("A-kick $SHM_HOST_FILE@$SLOT_OFF $HOST_KICK_SOCK shmkick"
                          "C-kick - $KICK_SOCK kickecho"
                          "D-kick $IVSHMEM@$SLOT_OFF $KICK_SOCK shmkick")
[ "$DB" = 1 ] && DBARMS=("A-db $SHM_HOST_FILE@$SLOT_OFF $HOST_KICK_SOCK shmdb $HOST_IVSHM_SOCK"
                         "D-db $IVSHMEM@$SLOT_OFF $KICK_SOCK shmdb $IVSHMEM_SERVER")
TAGS=(); ARMJSON=""; sep=""
for a in "${ARMS[@]}" "${UARMS[@]}" "${SARMS[@]}" "${KARMS[@]}" "${DBARMS[@]}"; do
	set -- $a
	if [ "$4" = udp ]; then
		m_reachable_udp "$2" "$3" "$1"
		UDP_ARMS="$UDP_ARMS $1"
	elif [ "$4" = shm ]; then
		m_reachable_shm "$2" "$1"
		SHM_ARMS="$SHM_ARMS $1"
	elif [ "$4" = shmkick ] || [ "$4" = shmdb ] || [ "$4" = kickecho ]; then
		m_reachable_notified "$1" "$4" "$2" "$3" "${5:-}"
		case "$4" in
			shmkick) KICK_ARMS="$KICK_ARMS $1" ;;
			shmdb) DB_ARMS="$DB_ARMS $1" ;;
			kickecho) ECHO_ARMS="$ECHO_ARMS $1" ;;
		esac
	else
		m_reachable "$2" "$3" "$1"
	fi
	TAGS+=("$1"); ARMJSON="$ARMJSON$sep\"$1\""; sep=", "
done
UDP_ARMS="${UDP_ARMS# }"
SHM_ARMS="${SHM_ARMS# }"
KICK_ARMS="${KICK_ARMS# }"; DB_ARMS="${DB_ARMS# }"; ECHO_ARMS="${ECHO_ARMS# }"

# ---------------------------------------------------------------- doorbell proof
# Before any D-db sample: one exchange answered by DB_BURST doorbells. All must
# arrive, the VM's mmio_exit_kernel must rise by at least that many (KVM's
# ioeventfd caught them in the kernel), and mmio_exit_user must stay far below
# (they did not take QEMU's userspace path). Anything else, and D-db would not
# measure what it is called: refuse.
BURSTJSON='"run": 0'
if [ "$DB" = 1 ]; then
	m_kvm_snap "$OUT/db-burst-kvm.json" before
	taskset -c "$CORE_PROBE" python3 "$PROBE" --proto shmdb --shm "$IVSHMEM@$SLOT_OFF" --kick "$KICK_SOCK" \
		--ivshm "$IVSHMEM_SERVER" --shm-lib "$SHMCHAN_LIB" --db-burst "$DB_BURST" --tag db-burst \
		--out "$OUT/db-burst.json" >> "$OUT/probe.log" 2>&1 \
		|| die "the doorbell burst did not deliver $DB_BURST doorbells -- see $OUT/probe.log"
	m_kvm_snap "$OUT/db-burst-kvm.json" after
	BURSTJSON="$(m_db_proof "$OUT" "$DB_BURST")" || die "the doorbell path is not KVM's in-kernel one: $BURSTJSON"
	say "doorbell proof: $BURSTJSON"
fi
NOTIFJSON='"kick": 0, "db": 0'
if [ "$KICK$DB" != 00 ]; then
	NOTIFJSON="\"kick\": $KICK, \"db\": $DB, \"slot_offset\": $SLOT_OFF, \"kick_sock\": \"$KICK_SOCK\", \"ivshmem_server\": \"$IVSHMEM_SERVER\", \"host_ivshmem_server\": \"$HOST_IVSHM_SOCK\", \"host_kick_sock\": \"$HOST_KICK_SOCK\", \"core_aux\": $CORE_AUX, \"guest_server_pid\": $GUEST_SRV_PID, \"guest_server_affinity\": \"$GUEST_SRV_AFF\", \"guest_server_script_sha256\": \"$(_sha "$GUEST_SRV_SCRIPT")\", \"ivshmem_server_py_sha256\": \"$(_sha "$here/ivshmem_server.py")\", \"ivshm_client_c_sha256\": \"$(_sha "$SHM_COMMON/ivshm_client.c")\", \"db_burst\": {$BURSTJSON}"
fi
HALTJSON=""; hsep=""
for hp in halt_poll_ns halt_poll_ns_grow halt_poll_ns_grow_start halt_poll_ns_shrink; do
	HALTJSON="$HALTJSON$hsep\"$hp\": \"$(cat /sys/module/kvm/parameters/$hp 2>/dev/null || echo NA)\""; hsep=", "
done
SHMJSON='"enabled": 0'
# The instrument's library and the slot files are recorded whenever ANY shm-family
# arm ran -- a notified-only run used them too (FOUND BY CODE REVIEW).
if [ "$SHM$KICK$DB" != 000 ]; then
	SHMJSON="\"enabled\": $SHM, \"host_file\": \"$SHM_HOST_FILE\", \"ivshmem_file\": \"$IVSHMEM\", \"libshmchan_sha256\": \"$(_sha "$OUT/libshmchan.so")\", \"shmchan_c_sha256\": \"$(_sha "$here/shmchan.c")\", \"shm_chan_h_sha256\": \"$(_sha "$SHM_COMMON/shm_chan.h")\", \"shm_map_posix_c_sha256\": \"$(_sha "$SHM_COMMON/shm_map_posix.c")\""
fi

m_write_stamp "$OUT/stamp.json" \
	'"experiment": "ladder"' \
	"\"pin\": {\"qemu\": \"$QEMU_CORES\", \"monitor\": $CORE_MON, \"probe\": $CORE_PROBE}" \
	"\"monitor_native_sha256\": \"$(_sha "$MON")\"" \
	"\"udp\": {\"enabled\": $UDP, \"port\": $PORT_UDP, \"arm_c_port\": \"$ARM_C_UDP_PORT\"}" \
	"\"shm\": {$SHMJSON}" \
	"\"notified\": {$NOTIFJSON}" \
	"\"kvm_stats\": $KVM_STATS" \
	"\"kvm_halt_poll\": {$HALTJSON}" \
	"\"udp_in_tcp\": $UDP_IN_TCP" \
	"\"transports\": \"${TGROUPS[*]}\"" \
	'"order": "within each transport its rungs in fixed order A, B, C, D (those it has); the transport groups in a Williams order by round, as run in order.log (two transports: tcp first in odd rounds)"' \
	"\"arms\": [$ARMJSON]"

# ---------------------------------------------------------------- the run
say "k=$K rounds, n=$N, warmup=$WARMUP, interval=${INTERVAL_MS}ms, ${#TAGS[@]} arms, interleaved -> $OUT"
for r in $(seq 1 "$K"); do
	ROUND=()
	for gi in $(m_williams_row "$r" "${#TGROUPS[@]}"); do
		case "${TGROUPS[gi]}" in
			tcp) ROUND+=("${ARMS[@]}") ;;
			udp) ROUND+=("${UARMS[@]}") ;;
			shm) ROUND+=("${SARMS[@]}") ;;
			kick) ROUND+=("${KARMS[@]}") ;;
			db) ROUND+=("${DBARMS[@]}") ;;
		esac
	done
	order=""
	for a in "${ROUND[@]}"; do
		set -- $a
		m_probe "$OUT" "$1_r$r" "$2" "$3" "" "$4" "${5:-}"
		order="$order $1"
	done
	echo "round $r order:$order" >> "$OUT/order.log"
	say "round $r/$K done"
done

m_governor_recheck
m_stamp_after "$OUT/stamp.json"
m_require_complete "$OUT" "${TAGS[@]}"
m_summary "$OUT" "${TAGS[0]}" "${TAGS[@]}"
if [ "$UDP" = 1 ]; then
	say "UDP rungs paired with their TCP rungs, and each transport's crossing"
	PAIRS=("A-udp:A-loopback" "B-udp:B-bridge")
	[ -n "$ARM_C_UDP_PORT" ] && [ -n "$ARM_C_PORT" ] && PAIRS+=("C-udp:C-null")
	PAIRS+=("D-udp:D-guest" "D-guest:B-bridge" "D-udp:B-udp")
	m_pairs "$OUT" "${PAIRS[@]}"
fi
if [ "$SHM" = 1 ]; then
	# No bridge on the shm path, so its crossing is D - A; the TCP line beside
	# it is D - A too, for like against like.
	say "shm rungs paired with their TCP rungs, and each transport's D - A"
	m_pairs "$OUT" "A-shm:A-loopback" "D-shm:D-guest" "D-shm:A-shm" "D-guest:A-loopback"
fi
if [ "$KICK$DB" != 00 ]; then
	say "notified rungs: against spinning, against each other, and against TCP"
	PAIRS=()
	[ "$KICK" = 1 ] && PAIRS+=("D-kick:C-kick" "D-kick:A-kick" "D-kick:D-guest")
	[ "$KICK" = 1 ] && [ "$SHM" = 1 ] && PAIRS+=("A-kick:A-shm" "D-kick:D-shm")
	[ "$DB" = 1 ] && PAIRS+=("D-db:A-db" "D-db:D-guest")
	[ "$DB" = 1 ] && [ "$KICK" = 1 ] && PAIRS+=("A-db:A-kick" "D-db:D-kick")
	[ "$DB" = 1 ] && [ "$SHM" = 1 ] && PAIRS+=("D-db:D-shm")
	[ "$UDP_IN_TCP" = 1 ] && [ "$KICK" = 1 ] && PAIRS+=("D-kick:D-udp")
	m_pairs "$OUT" "${PAIRS[@]}"
fi
