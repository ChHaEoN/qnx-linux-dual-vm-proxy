#!/usr/bin/env python3
"""live.py -- the live CARLA feeder in WSL: WP1's take against the Windows server, each step sent onto vcan0 as it becomes current (sdv/feeder).

SDV plan Phase 7 WP3c (spec-2 2.4 and section 6). Runs in WSL Ubuntu-24.04 with the
feeder's venv ~/sdv-carla-venv (requirements-live.lock: the carla 0.9.16 cp312 manylinux wheel, and cantools and python-can
at the sim lock's versions with their resolution), from the repo root, while `stack.py live` runs the stack:

    ~/sdv-carla-venv/bin/python sdv/feeder/live.py run --name N --seed S --host GATEWAY --out DIR [--freeze-at-s T]

REFUSED BEFORE CONNECTING (exit 2; nothing written, nothing sent): a name that is not <yyyymmdd>-carla-<S>[suffix]
(carla_capture.name_problem), a negative seed, a DIR whose last component is not the name (a take's directory is named by
it), a DIR that exists or lies inside a git work tree, a --freeze-at-s that is not a finite number above 0; no generated
contract, or one that does not compile the carla run type's live-default profile (the bridge and the guest would refuse
every frame); fwcheck --for wsl not passing (fwcheck_wsl: the firewall cmdlets run on the Windows side through WSL's
interop, fwcheck.command() unchanged, and fwcheck's own pure predicate judges their output here, P4 included, its
interpreters read through WSL's automount; the result line is the take's fwcheck_line, as on Windows); a --host that is not
the gateway of the default route (read from /proc/net/route at run time; neither address is written to any file or printed);
no vcan0, or a vcan0 that is not a CAN interface or not up (/sys/class/net); slice.dbc that cantools cannot load against the
contract (encode.load_dbc); a SocketCAN bus that does not open; no carla client to import.

THE TAKE: exactly WP1's (carla_capture.take with drive.py's DRIVE and ROUTE, frames off, no Traffic Manager), against the
server at the gateway's port 2000, written to DIR (steps.jsonl, script.jsonl, capture.json, take.sha256: spec 2.2), with the
take's per-step hook (on_current) set to this module's Hook. Then live.json, beside them. Nothing here opens a listener.

THE SENDER (Sender, SenderThread; slice.dbc DESIGN VALUES (2): the frames sendpolicy.schedule gives a recording): the
dynamics message at every instant k x its period and the gear message at every instant k x its own, from the moment step 0
became current, each from the step current at its instant (the latest step that became current at or before it,
schedule's rule) while that step has been current for no longer than the repeat cap there (FEEDER_REPEAT_CAP_MS, counted
from its becoming current), otherwise no frame (counted as capped). The take announces a step through its hook only after the
step became current and its row was written, so at an instant one pacing interval or more after the latest step announced a
newer step may already be current (no step becomes current sooner: sendpolicy.became_current); there the sender waits for
the hook, up to LATE_HOOK_GUARD_MS after the instant, and sends the step current at the instant as far as announced by then.
A frame therefore goes out at its instant, or up to the guard after it. A step announced later than that, current at an
instant already served, is counted (stale, per message; the first STALE_KEPT in stale_sends): that instant went out from
the step before it, or as none. A sender that wakes late sends each message's latest due instant only and counts the
instants it passed (missed): never a catch-up. The frames go out through python-can's SocketCAN on vcan0, encoded as
encode.py encodes a recording's (Codec: carla_iso.convert, the range check, cantools with the database strict). A step with a
value outside slice.dbc's range, or one carla_iso refuses, sends no frame of either message and is logged (refused_steps),
never clamped. A send that fails is logged (send_errors), the sender goes on, and the run exits 1. The pacing is the take's
(sendpolicy.became_current): this module only sends.

THE HOST: the server's address is checked against the default route and never written: the take's writer is wrapped so that
every string capture.json holds has it masked (HOST_MASK; LibCarla's errors name the endpoint the client was connected to,
and the take records an error's text), and live.json is masked the same way. LibCarla's own C++ messages on stderr are not
this module's: do not keep the feeder's stderr in a file unredacted.

THE FREEZE (--freeze-at-s T): at the first step whose simulated time since the take's step 0 passes T (the server's
elapsed_seconds counts from the world's load, not from the take), the hook holds the take's loop, and so the ticking, for
FREEZE_S of wall time, then ends the take there (completed, as a true return of the hook ends it). Meanwhile the sender
repeats the frozen step until the repeat cap and then sends nothing: the bridge's held values age, and the guest answers 22
(K4 16.4's F2, which f2check.py judges). A T the take never passes freezes nothing, and stderr says so.

LIVE.JSON (written last, also after a failure; compact, sorted keys): the policy; every send as [message (0 the dynamics, 1
the gear), instant, step, t_ns, t_real_ns], t_ns on the take's clock from step 0's becoming current and t_real_ns on
CLOCK_REALTIME, the clock the bridge ages on (origin_real_ns: that clock at step 0's becoming current, from the two clocks'
offset at that moment); counts, capped and missed per message; refused_steps; send_errors; the guard (late_hook_guard_ms),
stale per message and stale_sends; gaps (the steps that became current more than the repeat cap after the previous one or
after a skipped frame: sendpolicy.gaps over the steps the sender was given; the take's capture.json holds the RTF); the
freeze (its point, FREEZE_S, the frozen step, its start and end on both clocks, the last frame sent); the sha256 of
slice.dbc, of the generated contract and of this file; fwcheck's line; the take's exit code. No address of any host.

DOES NOT DEMONSTRATE: CAN timing (vcan has no arbitration, error frames or bus timing); any timing (the sender keeps a
wall-clock schedule on a general-purpose kernel at no real-time priority, and F2 is functional: one 22 within a bound, no
MISS); vehicle dynamics (CARLA's physics and the scripted drive are not a vehicle); anything off the PC.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib
import importlib.util
import ipaddress
import json
import math
import sys
import threading
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CARLA_DIR = REPO / "sdv" / "carla"
for _d in (str(CARLA_DIR), str(REPO / "sdv" / "sim"), str(REPO / "sdv" / "frame")):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import carla_iso  # noqa: E402
import drive  # noqa: E402
import frameset  # noqa: E402
import fwcheck  # noqa: E402
import sendpolicy  # noqa: E402
import vssframe  # noqa: E402


def _load(name: str, path: Path) -> Any:
    """A command-line module of sdv/carla by path, under a name of its own (its generic name may be another tree's module)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                    # dataclasses with postponed annotations look their module up there
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        del sys.modules[name]
        raise
    return mod


capture = _load("sdv_feeder_carla_capture", CARLA_DIR / "carla_capture.py")
encode = _load("sdv_feeder_carla_encode", CARLA_DIR / "encode.py")

CHANNEL = "vcan0"
LIVE_JSON = "live.json"
FORMAT = 1
ROUTE_FILE = Path("/proc/net/route")
SYS_NET = Path("/sys/class/net")
MOUNT_ROOT = "/mnt"                  # WSL's default automount root: drive E: is /mnt/e
ARPHRD_CAN = 280                     # linux/if_arp.h: a CAN interface's type
IFF_UP = 0x1                         # linux/if.h
RTF_UP, RTF_GATEWAY = 0x1, 0x2       # linux/route.h: a route's flags as /proc/net/route prints them
SEND_KEYS = ("message", "instant", "step", "t_ns", "t_real_ns")
# Design values, each with its reason.
TICK_MS = 100        # one tick of the claim bridge (sdv/bridge/vss_claim_bridge.py, TICK_HZ 10; K4 14.1): F2's bound is AGE_MAX
                     # plus one tick (K4 16.4), and f2check.py takes it from here
FREEZE_S = 2.0       # the freeze's wall time: at least AGE_MAX + one tick + the repeat cap + LATE_HOOK_GUARD_MS (the last frame's
                     # latest transmission), so the first 22 falls inside it whatever the tick's phase (a test holds that against the
                     # generated contract), and four of the native monitor's 500 ms deadlines, so a bridge that stopped sending during
                     # it would show a MISS
IDLE_POLL_S = 0.005  # the sender's thread, before step 0 is current: how often it looks for it (an announced step wakes it at once)
JOIN_S = 5.0         # at the end, how long to wait for the sender's thread
LATE_HOOK_GUARD_MS = 5   # at an instant a newer step may hold, how long the sender waits for the take's hook: the hook follows the
                         # step's becoming current by the pacing sleep's overshoot, the steps.jsonl write and the two frames'
                         # encoding. This design allowance is a quarter of the shortest period (20 ms)
                         # to leave scheduling room, so a frame that waited is never near the same message's
                         # next instant (Sender refuses a guard not above 0 and below the shortest period)
HISTORY = 64         # the steps, and the instants served, the sender keeps: 3.2 s at the pacing interval, far more than a
                     # sender keeping up ever looks back
STALE_KEPT = 20      # live.json's stale_sends: the first this many, the counts hold them all
HOST_MASK = "<gateway>"   # what every file written here says in place of the server's host address (spec-2 2.4: never written)

Frames = Dict[str, Tuple[int, bytes]]


class LiveRefused(RuntimeError):
    """A live run that cannot start (the module docstring, REFUSED BEFORE CONNECTING)."""


# --- the checks before connecting ----------------------------------------------------------------------------------

def wsl_path(win_path: str, mount: Optional[str] = None) -> str:
    """A Windows drive path (X:\\a\\b) as WSL's automount shows it (<mount>/x/a/b)."""
    p = PureWindowsPath(win_path)
    if len(p.drive) != 2 or p.drive[1] != ":" or not p.root:
        raise ValueError("%r is not a Windows drive path" % win_path)
    root = MOUNT_ROOT if mount is None else mount
    return "/".join([root.rstrip("/"), p.drive[0].lower()] + list(p.parts[1:]))


def wsl_interpreters() -> Tuple[str, ...]:
    """fwcheck's P4 operands read from WSL: the Windows client venv's pyvenv.cfg through the automount (the rules name the
    interpreters by their Windows paths, which fwcheck.interpreters_of gives)."""
    with open(wsl_path(str(PureWindowsPath(fwcheck.VENV) / "pyvenv.cfg")), encoding="utf-8") as f:
        return fwcheck.interpreters_of(f.read())


def fwcheck_wsl() -> Tuple[int, List[str]]:
    """fwcheck --for wsl, whole (P1-P4): PowerShell's read on the Windows side through WSL's interop, the predicate here."""
    return fwcheck.run("wsl", interpreters=wsl_interpreters)


def default_gateway(route_text: str) -> Optional[str]:
    """The gateway of the default route in /proc/net/route's text: of the default routes that are up and go through a
    gateway, the one of the lowest metric, as a dotted IPv4 address; None when there is none."""
    best: Optional[Tuple[int, str]] = None
    for line in route_text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8:
            continue
        try:
            dest, gw, flags, metric, mask = int(f[1], 16), int(f[2], 16), int(f[3], 16), int(f[6]), int(f[7], 16)
        except ValueError:
            continue
        if dest != 0 or mask != 0 or flags & (RTF_UP | RTF_GATEWAY) != (RTF_UP | RTF_GATEWAY):
            continue
        addr = str(ipaddress.IPv4Address(gw.to_bytes(4, sys.byteorder)))      # the kernel prints the address in host order
        if best is None or metric < best[0]:
            best = (metric, addr)
    return best[1] if best is not None else None


def gateway_problem(host: str, route_text: str) -> Optional[str]:
    """Why --host is not the default route's gateway, or None. No address is printed: none is written anywhere."""
    gw = default_gateway(route_text)
    if gw is None:
        return "no default route through a gateway in %s: the server's host cannot be checked" % ROUTE_FILE
    try:
        given = ipaddress.ip_address(host)
    except ValueError:
        return "--host is not an IP address: it is the Windows host as WSL's NAT shows it, the default route's gateway"
    if given != ipaddress.ip_address(gw):
        return "--host is not the default route's gateway, the Windows host as WSL's NAT shows it (neither address is printed)"
    return None


def vcan_problem(sys_net: Path = SYS_NET, channel: str = CHANNEL) -> Optional[str]:
    """Why vcan0 cannot carry the frames (missing, not a CAN interface, down), or None."""
    d = sys_net / channel
    try:
        kind = int((d / "type").read_text(encoding="ascii").strip())
        flags = int((d / "flags").read_text(encoding="ascii").strip(), 16)
    except (OSError, ValueError):
        return "no %s: start `stack.py live` first (its vcan feed makes %s)" % (channel, channel)
    if kind != ARPHRD_CAN:
        return "%s is not a CAN interface (type %d, not %d)" % (channel, kind, ARPHRD_CAN)
    if not flags & IFF_UP:
        return "%s is down" % channel
    return None


def preflight(name: str, seed: int, out: Path, freeze_at_s: Optional[float], host: str, *, contract: Any,
              fwcheck_run: Optional[Callable[[], Tuple[int, List[str]]]], route_text: Optional[str],
              sys_net: Optional[Path]) -> Tuple[Any, str]:
    """Every refusal before connecting (the module docstring); returns the contract and fwcheck's line."""
    if seed < 0:
        raise LiveRefused("--seed must be a non-negative integer")
    problem = capture.name_problem(name, seed)
    if problem:
        raise LiveRefused(problem)
    if out.name != name:
        raise LiveRefused("--out's last component %r is not the take's name %r (a take's directory is named by it)" % (out.name, name))
    if freeze_at_s is not None and not (math.isfinite(freeze_at_s) and freeze_at_s > 0):
        raise LiveRefused("--freeze-at-s %r is not a number of simulated seconds above 0" % (freeze_at_s,))
    if out.exists() or out.is_symlink():
        raise LiveRefused("--out %s exists: a take is never rewritten" % out)
    if frameset.inside_work_tree(out):
        raise LiveRefused("--out %s lies inside a git work tree" % out)
    if contract is None:
        try:
            contract = vssframe.load_contract()
        except vssframe.ContractError as e:
            raise LiveRefused(str(e)) from e
    try:
        encode.profile_of(contract)
    except encode.EncodeError as e:
        raise LiveRefused(str(e)) from e
    rc, lines = (fwcheck_run or fwcheck_wsl)()
    if rc != 0:
        raise LiveRefused("fwcheck --for wsl does not pass: %s" % "; ".join(lines))
    if route_text is None:
        try:
            route_text = ROUTE_FILE.read_text(encoding="ascii")
        except OSError as e:
            raise LiveRefused("the routes cannot be read (%s): the server's host cannot be checked" % e) from e
    problem = gateway_problem(host, route_text)
    if problem:
        raise LiveRefused(problem)
    problem = vcan_problem(SYS_NET if sys_net is None else sys_net)
    if problem:
        raise LiveRefused(problem)
    return contract, lines[0]


# --- the frames, the sender, the hook ------------------------------------------------------------------------------

class Codec:
    """A step's two frames, as encode.py encodes a recording's: carla_iso.convert (spec 2.7), slice.dbc's ranges
    (encode.range_problems: refused, never clamped), cantools' encode of each message."""

    def __init__(self, db: Any, contract: Any, pol: Any) -> None:
        self.pol = pol
        self.signals = tuple(contract.SLOT_DBC_SIGNALS)
        self.ranges = encode.dbc_ranges(db, contract)
        self.messages = {m: db.get_message_by_name(m) for m in (pol.dyn_msg, pol.gear_msg)}

    def frames(self, row: Dict[str, Any], front_max_steer_deg: Sequence[float]) -> Tuple[Optional[Frames], List[str]]:
        """(the step's frames by message, []), or (None, why) for a step that sends no frame."""
        i = int(row["i"])
        try:
            vals = carla_iso.convert(row, front_max_steer_deg)
        except (carla_iso.ConversionError, ValueError) as e:
            return None, ["step %d: %s" % (i, e)]
        problems = encode.range_problems([(i, dict(zip(self.signals, vals)))], self.ranges)
        if problems:
            return None, problems
        dyn, gear = self.messages[self.pol.dyn_msg], self.messages[self.pol.gear_msg]
        try:
            return {self.pol.dyn_msg: (int(dyn.frame_id), bytes(dyn.encode(dict(zip(self.signals[:4], vals[:4]))))),
                    self.pol.gear_msg: (int(gear.frame_id), bytes(gear.encode({self.signals[4]: vals[4]})))}, []
        except Exception as e:  # noqa: BLE001 - cantools refused the step: logged, no frame (encode.py would refuse the take)
            return None, ["step %d: cantools: %s: %s" % (i, type(e).__name__, e)]


class Sender:
    """The frames of the send policy, sent as the clock reaches their instants (the module docstring, THE SENDER). The take's
    thread calls current() through the hook and the sender's thread pump(); a lock keeps the two apart, and `changed` wakes
    the sender's thread at each step announced."""

    def __init__(self, pol: Any, send: Callable[[int, bytes], None], clock_ns: Callable[[], int],
                 realtime_ns: Callable[[], int]) -> None:
        self.pol = pol
        self.send = send
        self.clock_ns, self.realtime_ns = clock_ns, realtime_ns
        self.msgs = (pol.dyn_msg, pol.gear_msg)
        self.periods_ns = (pol.dyn_period_ms * sendpolicy.NS_PER_MS, pol.gear_period_ms * sendpolicy.NS_PER_MS)
        self.guard_ns = int(LATE_HOOK_GUARD_MS * sendpolicy.NS_PER_MS)
        if not 0 < self.guard_ns < min(self.periods_ns):
            raise ValueError("LATE_HOOK_GUARD_MS %r is not above 0 and below the shortest period" % (LATE_HOOK_GUARD_MS,))
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.origin: Optional[int] = None             # the clock at which step 0 became current
        self.steps: Deque[Tuple[int, int, Optional[Frames]]] = collections.deque(maxlen=HISTORY)   # (i, t_cur, frames), announced
        self.served: Deque[List[Any]] = collections.deque(maxlen=HISTORY)   # [message, instant, its time, step used, found stale]
        self.next_k = [0, 0]                          # per message, the next instant not yet dealt with
        self.sends: List[List[int]] = []              # SEND_KEYS, t_ns from origin
        self.capped = [0, 0]
        self.missed = [0, 0]
        self.stale = [0, 0]
        self.stale_sends: List[Dict[str, Any]] = []
        self.refused: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []

    def current(self, i: int, t_cur: int, frames: Optional[Frames], problems: Sequence[str]) -> None:
        """Step i became current at t_cur (the take's clock); frames None: it sends none (problems say why). An instant already
        served at or after t_cur from an older step is counted stale: its hook came later than the guard."""
        with self.lock:
            if self.origin is None:
                self.origin = t_cur
            for s in self.served:
                if s[2] >= t_cur and s[3] < i and not s[4]:
                    s[4] = True
                    self.stale[s[0]] += 1
                    if len(self.stale_sends) < STALE_KEPT:
                        self.stale_sends.append({"message": self.msgs[s[0]], "instant": s[1], "sent_step": s[3], "current_step": i})
            self.steps.append((i, t_cur, frames))
            if frames is None:
                self.refused.append({"i": i, "problems": list(problems)})
        self.changed.set()

    def _unsure(self, inst: int) -> bool:
        """A step newer than the latest announced may be current at inst: inst lies one pacing interval or more after it (no
        step becomes current sooner, sendpolicy.became_current), and the take announces a step only after it became current."""
        return inst >= self.steps[-1][1] + self.pol.interval_ns

    def _step_at(self, inst: int) -> Optional[Tuple[int, int, Optional[Frames]]]:
        """The step current at inst as far as announced: the latest that became current at or before it."""
        for st in reversed(self.steps):
            if st[1] <= inst:
                return st
        return None

    def _due(self) -> int:
        assert self.origin is not None
        out = []
        for k, p in zip(self.next_k, self.periods_ns):
            inst = self.origin + k * p
            out.append(inst + self.guard_ns if self._unsure(inst) else inst)
        return min(out)

    def next_due(self) -> Optional[int]:
        """When pump has something to do next: a message's next instant, or its end of the guard (None before step 0)."""
        with self.lock:
            return None if self.origin is None else self._due()

    def pump(self, now: int) -> Optional[int]:
        """Send what is due at `now`: per message its latest instant at or before now not yet dealt with, the earlier ones
        counted as missed and never sent late; at an instant a newer step may hold (_unsure), not before the hook announced
        one or the guard after the instant ran out; the frame of the step current at the instant, while that step is no
        older than the repeat cap at it. Returns when pump has something to do next (None before step 0)."""
        with self.lock:
            if self.origin is None or not self.steps:
                return None
            todo: List[Tuple[int, int, int]] = []
            for m in (0, 1):
                k = (now - self.origin) // self.periods_ns[m]
                if k < self.next_k[m]:
                    continue
                self.missed[m] += k - self.next_k[m]
                self.next_k[m] = k
                inst = self.origin + k * self.periods_ns[m]
                if self._unsure(inst) and now < inst + self.guard_ns:
                    continue                          # the hook may yet announce the step current at inst
                self.next_k[m] = k + 1
                todo.append((inst, m, k))
            for inst, m, k in sorted(todo):           # in schedule's order: by instant, the dynamics first at an equal one
                step = self._step_at(inst)
                if step is None:                      # older than every step kept: a sender that far behind sends nothing
                    self.missed[m] += 1
                    continue
                i, t_cur, frames = step
                self.served.append([m, k, inst, i, False])
                if inst - t_cur > self.pol.cap_ns:
                    self.capped[m] += 1
                    continue
                if frames is None:
                    continue
                can_id, data = frames[self.msgs[m]]
                try:
                    self.send(can_id, data)
                except Exception as e:  # noqa: BLE001 - a frame the bus refused: logged, the sender goes on
                    self.errors.append({"message": self.msgs[m], "instant": k, "step": i, "error": "%s: %s" % (type(e).__name__, e)})
                    continue
                self.sends.append([m, k, i, now - self.origin, self.realtime_ns()])
            return self._due()

    def record(self) -> Dict[str, Any]:
        with self.lock:
            return {"sends": [list(x) for x in self.sends],
                    "counts": {self.msgs[m]: sum(1 for x in self.sends if x[0] == m) for m in (0, 1)},
                    "capped": {self.msgs[m]: self.capped[m] for m in (0, 1)},
                    "missed": {self.msgs[m]: self.missed[m] for m in (0, 1)},
                    "stale": {self.msgs[m]: self.stale[m] for m in (0, 1)}, "stale_sends": [dict(s) for s in self.stale_sends],
                    "refused_steps": [dict(r) for r in self.refused], "send_errors": [dict(e) for e in self.errors]}


class SenderThread:
    """The sender's own thread: pump whenever the sender has something to do on the clock (the take's, time.perf_counter_ns),
    or a step was announced, until stopped."""

    def __init__(self, sender: Sender, clock_ns: Callable[[], int]) -> None:
        self.sender, self.clock_ns = sender, clock_ns
        self.stopping = threading.Event()
        self.error: Optional[str] = None
        self.thread = threading.Thread(target=self._run, name="live-sender", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        try:
            while not self.stopping.is_set():
                self.sender.changed.clear()               # before the pump: a step announced after it wakes the wait below
                due = self.sender.pump(self.clock_ns())
                if due is None:
                    self.sender.changed.wait(IDLE_POLL_S)
                    continue
                wait_ns = due - self.clock_ns()
                if wait_ns > 0:
                    self.sender.changed.wait(wait_ns / 1e9)
        except BaseException as e:  # noqa: BLE001 - the run's record says so and the run exits 1
            self.error = "%s: %s" % (type(e).__name__, e)

    def stop(self) -> None:
        self.stopping.set()
        self.sender.changed.set()
        self.thread.join(JOIN_S)


class Hook:
    """carla_capture.take's on_current: each step to the sender, and the freeze (the module docstring, THE FREEZE)."""

    def __init__(self, sender: Sender, codec: Codec, clock_ns: Callable[[], int], realtime_ns: Callable[[], int],
                 sleep: Callable[[float], None], freeze_at_s: Optional[float]) -> None:
        self.sender, self.codec = sender, codec
        self.clock_ns, self.realtime_ns, self.sleep = clock_ns, realtime_ns, sleep
        self.freeze_at_s = freeze_at_s
        self.first_elapsed: Optional[float] = None
        self.origin_real_ns: Optional[int] = None
        self.frames_seen: List[int] = []
        self.t_cur_seen: List[int] = []
        self.freeze: Optional[Dict[str, Any]] = None

    def __call__(self, row: Dict[str, Any], t_cur: int, ego: Dict[str, Any]) -> Optional[bool]:
        frames, problems = self.codec.frames(row, ego["front_max_steer_deg"])
        self.sender.current(int(row["i"]), t_cur, frames, problems)
        self.frames_seen.append(int(row["frame"]))
        self.t_cur_seen.append(t_cur)
        if self.first_elapsed is None:
            self.first_elapsed = float(row["elapsed_s"])
            self.origin_real_ns = self.realtime_ns() - (self.clock_ns() - t_cur)
        if self.freeze_at_s is None or self.freeze is not None:
            return None
        sim = float(row["elapsed_s"]) - self.first_elapsed
        if not sim > self.freeze_at_s:
            return None
        origin = self.t_cur_seen[0]
        start, start_real = self.clock_ns(), self.realtime_ns()
        self.sleep(FREEZE_S)
        end, end_real = self.clock_ns(), self.realtime_ns()
        self.freeze = {"at_s": self.freeze_at_s, "freeze_s": FREEZE_S, "step": int(row["i"]), "frame": int(row["frame"]), "sim_s": sim,
                       "start_ns": start - origin, "start_real_ns": start_real, "end_ns": end - origin, "end_real_ns": end_real}
        return True


# --- the run ---------------------------------------------------------------------------------------------------------

def host_texts(host: str) -> Tuple[str, ...]:
    """The spellings of the server's host a text may carry: as given, and as the address prints (the longer first)."""
    out = {host}
    try:
        out.add(str(ipaddress.ip_address(host)))
    except ValueError:
        pass
    return tuple(sorted((h for h in out if h), key=len, reverse=True))


def mask_host(doc: Any, hosts: Sequence[str]) -> Any:
    """doc with every occurrence of the host's spellings in every string (keys too) replaced by HOST_MASK. LibCarla's errors
    name the endpoint the client was connected to (its TimeoutException: '... connected to <host>:<port>'), and the take
    records each error's text, so a server that is not up or stalls would put the gateway into the take's files."""
    if isinstance(doc, str):
        for h in hosts:
            doc = doc.replace(h, HOST_MASK)
        return doc
    if isinstance(doc, dict):
        return {mask_host(k, hosts): mask_host(v, hosts) for k, v in doc.items()}
    if isinstance(doc, (list, tuple)):
        return [mask_host(x, hosts) for x in doc]
    return doc


def _sha256_file(path: Optional[Any]) -> Optional[str]:
    try:
        return hashlib.sha256(Path(str(path)).read_bytes()).hexdigest() if path else None
    except OSError:
        return None


def live_doc(name: str, seed: int, pol: Any, rec: Dict[str, Any], hook: Hook, contract: Any, fwcheck_line: str, rc: int,
             clock_ns: Callable[[], int], realtime_ns: Callable[[], int]) -> Dict[str, Any]:
    """live.json (the module docstring, LIVE.JSON)."""
    fz = dict(hook.freeze) if hook.freeze is not None else None
    if fz is not None:
        last = rec["sends"][-1] if rec["sends"] else None
        fz["last_frame"] = None if last is None else {"message": [pol.dyn_msg, pol.gear_msg][last[0]], "instant": last[1], "step": last[2],
                                                      "t_ns": last[3], "t_real_ns": last[4]}
    origin = hook.t_cur_seen[0] if hook.t_cur_seen else 0
    return {
        "format": FORMAT, "name": name, "seed": seed, "channel": CHANNEL,
        "policy": {"step_ms": pol.step_ms, "interval_ms": pol.interval_ms, "cap_ms": pol.cap_ms, "messages": [pol.dyn_msg, pol.gear_msg],
                   "periods_ms": [pol.dyn_period_ms, pol.gear_period_ms]},
        "dbc_sha256": _sha256_file(encode.DBC_PATH), "contract_sha256": _sha256_file(getattr(contract, "__file__", None)),
        "live_sha256": _sha256_file(Path(__file__)), "fwcheck": fwcheck_line,
        "clock": {"monotonic": "time.perf_counter_ns" if clock_ns is time.perf_counter_ns else "a stand-in for time.perf_counter_ns",
                  "realtime": "time.time_ns (CLOCK_REALTIME, the clock the bridge ages on)" if realtime_ns is time.time_ns
                  else "a stand-in for time.time_ns"},
        "origin_real_ns": hook.origin_real_ns, "send_keys": list(SEND_KEYS), "sends": rec["sends"], "counts": rec["counts"],
        "capped": rec["capped"], "missed": rec["missed"], "refused_steps": rec["refused_steps"], "send_errors": rec["send_errors"],
        "late_hook_guard_ms": LATE_HOOK_GUARD_MS, "stale": rec["stale"], "stale_sends": rec["stale_sends"],
        "gaps": sendpolicy.gaps(hook.frames_seen, [t - origin for t in hook.t_cur_seen], pol.cap_ns),
        "steps_seen": len(hook.frames_seen), "freeze": fz, "take_rc": rc,
    }


def run_live(name: str, seed: int, out: Path, freeze_at_s: Optional[float], *, carla: Any, host: str, contract: Any, db: Any,
             send: Callable[[int, bytes], None], clock_ns: Callable[[], int], realtime_ns: Callable[[], int],
             sleep: Callable[[float], None], fwcheck_line: str, drv: Any, rv: Any,
             attach_sender: Optional[Callable[[Sender], Any]] = None) -> int:
    """The take with the sender on its hook, then live.json. attach_sender (the tests' clock): drives the sender instead of
    its own thread. The take's JSON writer (carla_capture._write_json, of this module's own copy of carla_capture) is wrapped
    for the take's length so that capture.json holds the host masked, and live.json is masked too (mask_host). Returns the
    take's exit code, or 1 when a send failed or the sender's thread stopped on an error."""
    pol = sendpolicy.Policy.from_contract(contract)
    sender = Sender(pol, send, clock_ns, realtime_ns)
    hook = Hook(sender, Codec(db, contract, pol), clock_ns, realtime_ns, sleep, freeze_at_s)
    hosts = host_texts(host)
    write_json = capture._write_json

    def masked_write_json(path: Path, doc: Dict[str, Any]) -> None:
        write_json(path, mask_host(doc, hosts))
    thread: Optional[SenderThread] = None
    if attach_sender is not None:
        attach_sender(sender)
    else:
        thread = SenderThread(sender, clock_ns)
        thread.start()
    capture._write_json = masked_write_json
    rc = 1
    try:
        rc = capture.take(name, seed, False, carla=carla, rts=capture.Roots(takes=out.parent, frames=out.parent), host=host,
                          contract=contract, clock_ns=clock_ns, sleep=sleep, fwcheck_line=fwcheck_line, drv=drv, rv=rv,
                          on_current=hook)
    finally:
        capture._write_json = write_json
        if thread is not None:
            thread.stop()
        rec = sender.record()
        if thread is not None and thread.error:
            rec["send_errors"].append({"message": None, "instant": None, "step": None, "error": "the sender's thread: " + thread.error})
        if out.is_dir():
            doc = mask_host(live_doc(name, seed, pol, rec, hook, contract, fwcheck_line, rc, clock_ns, realtime_ns), hosts)
            (out / LIVE_JSON).write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    if freeze_at_s is not None and hook.freeze is None:
        print("live.py: no freeze: the take never passed --freeze-at-s %r of simulated time" % freeze_at_s, file=sys.stderr)
    return 1 if rc == 0 and rec["send_errors"] else rc


def open_bus(channel: str = CHANNEL) -> Tuple[Any, Callable[[int, bytes], None]]:
    """python-can's SocketCAN bus on vcan0 and its send of one standard data frame (the feeder's venv)."""
    import can  # type: ignore[import-not-found]
    bus = can.Bus(interface="socketcan", channel=channel)

    def send(can_id: int, data: bytes) -> None:
        bus.send(can.Message(arbitration_id=can_id, data=data, is_extended_id=False))
    return bus, send


def main(argv: Optional[Sequence[str]] = None, *, carla: Any = None, send: Optional[Callable[[int, bytes], None]] = None, db: Any = None,
         contract: Any = None, fwcheck_run: Optional[Callable[[], Tuple[int, List[str]]]] = None, route_text: Optional[str] = None,
         sys_net: Optional[Path] = None, clock_ns: Optional[Callable[[], int]] = None, realtime_ns: Optional[Callable[[], int]] = None,
         sleep: Optional[Callable[[float], None]] = None, drive_values: Any = None, route_values: Any = None,
         attach_sender: Optional[Callable[[Sender], Any]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="drive WP1's take against the Windows server and send its steps onto vcan0")
    r.add_argument("--name", required=True)
    r.add_argument("--seed", type=int, required=True)
    r.add_argument("--host", required=True, help="the Windows host as WSL's NAT shows it: the default route's gateway (checked, never written)")
    r.add_argument("--out", type=Path, required=True, help="the take's directory, named by the take (made here; never an existing one)")
    r.add_argument("--freeze-at-s", type=float, default=None, help="freeze for FREEZE_S once the take's simulated time passes this, then end")
    a = ap.parse_args(argv)
    out = a.out.expanduser().absolute()
    bus = None
    try:
        con, line = preflight(a.name, a.seed, out, a.freeze_at_s, a.host, contract=contract, fwcheck_run=fwcheck_run,
                              route_text=route_text, sys_net=sys_net)
        if db is None:
            try:
                db = encode.load_dbc(con)
            except (ImportError, OSError, ValueError) as e:
                raise LiveRefused("slice.dbc cannot be loaded with cantools against the contract: %s" % e) from e
        if carla is None:
            try:
                carla = importlib.import_module("carla")
            except ImportError as e:
                raise LiveRefused("the carla 0.9.16 client is not importable here (%s): build ~/sdv-carla-venv" % e) from e
        if send is None:
            try:
                bus, send = open_bus()
            except Exception as e:  # noqa: BLE001 - python-can's errors are its own classes
                raise LiveRefused("the SocketCAN bus on %s does not open: %s: %s" % (CHANNEL, type(e).__name__, e)) from e
    except LiveRefused as e:
        print("live.py: refused: %s" % e, file=sys.stderr)
        return 2
    try:
        return run_live(a.name, a.seed, out, a.freeze_at_s, carla=carla, host=a.host, contract=con, db=db, send=send,
                        clock_ns=clock_ns or time.perf_counter_ns, realtime_ns=realtime_ns or time.time_ns, sleep=sleep or time.sleep,
                        fwcheck_line=line, drv=drive_values if drive_values is not None else drive.DRIVE,
                        rv=route_values if route_values is not None else drive.ROUTE, attach_sender=attach_sender)
    finally:
        if bus is not None:
            bus.shutdown()


if __name__ == "__main__":
    sys.exit(main())
