#!/usr/bin/env python3
"""ctlsynth.py -- the kind 2 synthetic client for the guest-only boot of ifs-ctl.bin (sdv/ctl).

The Phase 8 specification's later packages (spec-2.md section 8.1; the project's local
design notes, not in this tree) define it: sdv/frame/kind4_client.py's pattern for kind 2 (the pattern only: nothing of
it is imported). It drives ctlclient.py's core -- the claim node's core, with its connection rules, its reply log and
its header -- with synthetic Controls at a fixed rate against the monitor at --host and --port (no address in this
tree), and checks each reply against the frame's designed reason. With --console (the guest console's capture, or a
native monitor's stdout) it also reads the monitor's own lines.

    ctlsynth.py --plan {reasons,silence,late,flood,stamp} --host ADDR [--port PORT] [--profile 1]
        [--contract vss_ctl.py] [--deadline-ms 500] [--period-ms 30] [--flood-ms 2000] [--console FILE] [--check]
        --out DIR

PLANS (one per run; each starts its own connection and writes its own run directory)
  reasons  one frame per reason 8-19 at a fixed seq, honest frames between: seq 2k is ctlclient's injection for reason
           k + 7 (REASON_INJECTIONS: profile0 8, nan 9, undef 10, interval 11, speed 12, accel 13, jerk 14, steer 15,
           steer-rate 16, lat-accel 17, overspeed 18, rolling-back 19), every odd seq 1..25 honest.
  silence  LEAD_FRAMES honest frames, then ctlclient's intake pause for WAIT_FACTOR x the deadline (the monitor closes
           the idle connection and reports a MISS), then TAIL_FRAMES: the first of them gets 11 (its interval spans the
           silence) and gives RESTORED; the client sees the close by its peer check and reconnects once.
  late     no Control for WAIT_FACTOR x the deadline (so no connection: ctlclient connects at the first Control), then
           LATE_FRAMES honest frames on one connection, all accepted: the monitor's deadline runs from the accept.
  flood    profile 2's window (ctlclient's demo window, --flood-ms long, from half a control period before the
           (LEAD_FRAMES + 1)th frame): every honest frame inside it gets 12 at the control rate, the frames before and
           the TAIL_FRAMES after it are accepted under the base profile.
  stamp    STAMP_FRAMES honest frames to a stamp target (:7151 by default; any port given is marked a stamp target):
           every reply carries t_in and t_out; every injection, the pause and the demo window are refused there by
           ctlclient's own rule (check_config), which this plan asks of it before it sends.
  Only the stamp plan goes to a stamp target: any other plan on :7151 is refused. ctlclient knows :7151 alone as a stamp
  port (and a target marked stamp, as the stamp plan marks its port); a claim plan pointed at another stamp port (the
  image's :7161 is kind 4's) gets a stamped reply, which ctlclient takes as invalid. So every plan offers no Control
  before its first frame's outcome and none after an invalid reply: such a target gets one honest frame.

THE HONEST CONTROL: velocity HONEST_V_MPS and steering tire angle HONEST_DELTA_RAD, with acceleration, jerk and
steering rate carried but undefined (their is_defined flags clear, so rules 13, 14 and 16 skip every honest frame), the
odometry at the commanded speed received with the Control (b3 set: rules 17-19 judge every honest frame), stamped at
the control rate, one CONTROL_PERIOD_MS apart (so its interval is one period; a paused Control keeps the schedule).

CHECKS (result.json, one line each; exit 1 if any fails)
  every frame replied           every packed frame replied (no drop, no lost), the plan's count, the identity whole
  each reply its designed reason  (verdict, reason) of each replied frame equal to its design: the plan's seq table, 11
                                 after the silence, 12 for a frame packed with profile 2, else ACCEPT
  and the plan's own: one reconnect after the silence with Controls paused; no connection during the late wait and one
  after it; the flood's window contiguous, at least two frames, honest frames before and TAIL_FRAMES after; t_in and
  t_out on every stamp reply, 0 < t_in <= t_out; the stamp target refusing every injection, the pause and the window.
  With --console, from the console's end when the plan's first Control is due (after the late plan's wait, which is
  twice the deadline: by then an earlier session's MISS on the port has been printed): the `client done:` totals equal
  the replies; one `REJECT ... kind=ctl` line per designed reject with its profile and reason name, none for an honest
  frame (reasons, silence); the deadline's `client closed:`, the MISS of the last frame before the silence, then the
  RESTORED of the first after it (silence; the monitor's liveness is the process's, so on a port that served an
  earlier session and has missed its deadline since, this plan's first frame prints a RESTORED for seq 1, with that
  session's MISS just before it when the two come together: the session's lines start at that RESTORED, which the check
  names); no close and no MISS of the session's frames before its end (late); one REJECT line for the window's first
  frame and `ctl summary` lines of reason 12 alone counting the rest (flood: the REJECT-line limiter prints a reason
  only when it differs from the previous frame's). Before anything is sent, every whole `ctl rules:` and `ctl profile`
  line of the whole console must be the contract's (digest, constants, profiles), and one rules line at least must
  stand whole; a line that begins as one and has not its whole shape (another process's output split it) is named in
  the result and judged no further. Without --console those checks are NOT CHECKED; --check refuses to start without it.

ON THE GUEST'S CONSOLE (the board session, spec-2 8.4): one capture holds every monitor process's lines, none naming its
port. Run kind4_client.py's campaign before any plan here: its check refuses a console that already holds a LIVENESS
line, and every plan on :7150 leaves some. Run one plan at a time, each with --console (a plan returns once its
session's lines are on the console), and let nothing else claim on a port in svc mode meanwhile: another port's lines
would be read as this one's.

OUTPUTS (in --out, never inside a work tree, empty or absent): replies.jsonl, ctlclient's reply log (mode "synth"; its
header gains "synth": the plan, the spacing, the deadline, the wait, the flood, t0_ns and this file's sha256), and
result.json. Exit 0 every check that ran passed, 1 a check failed, 2 a refusal before anything was sent.

DOES NOT DEMONSTRATE: any timing (the plans' spacing is the control rate only as closely as this host's scheduler
allows; nothing here is a measurement); that the monitor judges Autoware's traffic (every frame is synthetic: WP4b's
runs); anything about the guest beyond its replies and its console lines.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import ctlclient as cc  # noqa: E402
import ctlframe as cf  # noqa: E402

MS = 1_000_000

# --- design values: each in this one place, with its reason ----------------------------------------------------------
# The control rate: the controller's ctrl_period, 0.03 s (READ in WP4a's facts, P6), which the gate passes on.
CONTROL_PERIOD_MS = 30
# The claim port's deadline: the :7150 start line's `svc 500` (ifs-ctl.build).
DEADLINE_MS = 500
# The silence and the late wait: twice the deadline, so the monitor's deadline passes with a margin on a loaded host.
WAIT_FACTOR = 2
# The honest command: under the planner's max_vel of 4.17 m/s (READ, WP4a P8), so an honest cruise command under
# profile 1; above profile 2's v_max, so the flood's frames get 12. A gentle left curve, far inside every steer_max.
HONEST_V_MPS = 4.0
HONEST_DELTA_RAD = 0.05
# Carried in the Control and never packed (their is_defined flags are clear).
HONEST_UNDEFINED = {"acceleration": -0.5, "jerk": 0.1, "steering_tire_rotation_rate": 0.01}
# Profile 2's window: two of the REJECT-line limiter's one-second buckets at the control rate.
FLOOD_MS = 2000
LEAD_FRAMES = 3                        # honest frames before the silence and before the window
TAIL_FRAMES = 3                        # honest frames after them
LATE_FRAMES = 5
STAMP_FRAMES = 5
CONSOLE_WAIT_S = 5.0                   # how long the console may take to show a session's last lines
POLL_S = 0.05                          # the longest wait between two looks at the clock or the console
OFFER_MARGIN = 200                     # Controls a plan may offer beyond its schedule before it gives up

PLANS = ("reasons", "silence", "late", "flood", "stamp")
REASON_INJECTIONS = ((8, "profile0"), (9, "nan"), (10, "undef"), (11, "interval"), (12, "speed"), (13, "accel"),
                     (14, "jerk"), (15, "steer"), (16, "steer-rate"), (17, "lat-accel"), (18, "overspeed"),
                     (19, "rolling-back"))
MODE = "synth"
RESULT = "result.json"
RESULT_FORMAT = 1

# The checks, by name.
CHK_REPLIED = "every frame replied"
CHK_DESIGNED = "each reply its designed reason"
CHK_SILENCE = "silence: one reconnect after Controls paused"
CHK_LATE = "late: no connection during the wait, one after it"
CHK_FLOOD = "flood: profile 2 frames in one window between honest frames"
CHK_STAMPS = "stamp: t_in and t_out on every reply"
CHK_STAMP_REFUSED = "stamp: every injection, the pause and the demo window refused on the stamp target"
CON_RULES = "console: the ctl rules and ctl profile lines are the contract's"
CON_TOTALS = "console: the session totals equal the replies"
CON_REJECTS = "console: one REJECT line per designed reject"
CON_SILENCE = "console: the deadline's close and MISS, then RESTORED"
CON_LATE = "console: no close and no MISS during the late session"
CON_FLOOD = "console: the window's one REJECT line and its summaries"
PASS, FAIL, NOT_CHECKED = "PASS", "FAIL", "NOT CHECKED"

ANY_REJECT_RE = re.compile(r"monitor: REJECT seq=(\d+) ")
DONE_RE = re.compile(r"monitor: client done: seen=(\d+) accepted=(\d+) rejected=(\d+)")
CLOSED_RE = re.compile(r"monitor: client closed: no complete frame for (\d+) ms")
MISS_RE = re.compile(r"monitor: LIVENESS MISS: no claim for \d+ ms since seq=(\d+) \(deadline (\d+) ms, miss \d+\)")
RESTORED_RE = re.compile(r"monitor: LIVENESS RESTORED: seq=(\d+) after \d+ ms without a claim")
SUMMARY_RE = re.compile(r"monitor: ctl summary: seen=(\d+) rejected=(\d+) suppressed=(\d+) by reason:((?: \d+=\d+)*)")
# The whole shape of monitor.c's two announcement lines, whatever their values: a line that begins as one of them and
# has not its shape is a fragment (another process's output split it on a shared console), judged no further.
CTL_LINE_PREFIXES = ("monitor: ctl rules:", "monitor: ctl profile ")
RULES_LINE_RE = re.compile(r"monitor: ctl rules: kind \d+, catalog 0x[0-9A-F]{8} \(vss [^()]*\), dt_max \d+ ms, overspeed \S+ x v_cmd "
                           r"\+ \S+ m/s, rollback \S+ m/s, tol17 \S+ m/s\^2, profiles \d+(?: \d+)*")
PROFILE_LINE_RE = re.compile(r"monitor: ctl profile \d+: L \d+ mm, v_max \S+ m/s, a_max \S+ m/s\^2, jerk_max \S+ m/s\^3, "
                             r"steer_max \S+ rad, steer_rate_max \S+ rad/s, lat_acc_max \S+ m/s\^2")


class SynthError(RuntimeError):
    """A refusal before anything is sent."""


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class Plan:
    """One plan as built: ctlclient's config, the counted frames it packs (None: the flood's, until its tail), the wait
    before the first Control, and its designed reasons by seq (the flood's come from each frame's profile)."""
    name: str
    config: cc.Config
    frames: Optional[int]
    wait_ms: int
    period_ms: int
    deadline_ms: int
    flood_ms: Optional[int]
    designed: Dict[int, int] = field(default_factory=dict)


def reason_seq(reason: int) -> int:
    """The reasons plan's fixed seq for a reason 8..19: the even seqs 2..24."""
    return 2 * (reason - 7)


def honest(stamp_ns: int, recv_ns: int) -> Tuple[cc.Control, cc.Odometry]:
    """The honest Control, stamped stamp_ns and received at recv_ns, and its odometry received with it."""
    ctl = cc.Control(stamp_ns=stamp_ns, recv_ns=recv_ns, velocity=HONEST_V_MPS, acceleration=HONEST_UNDEFINED["acceleration"],
                     is_defined_acceleration=False, jerk=HONEST_UNDEFINED["jerk"], is_defined_jerk=False,
                     steering_tire_angle=HONEST_DELTA_RAD,
                     steering_tire_rotation_rate=HONEST_UNDEFINED["steering_tire_rotation_rate"],
                     is_defined_steering_tire_rotation_rate=False)
    return ctl, cc.Odometry(v=HONEST_V_MPS, recv_ns=recv_ns)


def honest_problems(contract: Any, profile: int) -> List[str]:
    """Why the honest Control would not be accepted under this compiled profile (rules 12, 15 and 17; 18 and 19 cannot
    fire with the odometry at the commanded speed), or an empty list. math.tan suffices this far inside the edge."""
    pr = contract.PROFILES[profile]
    v, d = cf.f32(HONEST_V_MPS), cf.f32(HONEST_DELTA_RAD)
    out = []
    if not v <= pr["v_max"]:
        out.append("the honest velocity %r m/s is above profile %d's v_max %r" % (v, profile, pr["v_max"]))
    if not d <= pr["steer_max"]:
        out.append("the honest steering %r rad is above profile %d's steer_max %r" % (d, profile, pr["steer_max"]))
    elif not v * v * math.tan(d) / (pr["l_mm"] / 1000.0) <= pr["lat_acc_max"] + contract.TOL17:
        out.append("the honest Control's lateral acceleration is above profile %d's lat_acc_max + TOL17" % profile)
    return out


def build_plan(name: str, contract: Any, host: str, port: Optional[int] = None, profile: int = 1,
               deadline_ms: int = DEADLINE_MS, period_ms: int = CONTROL_PERIOD_MS, flood_ms: int = FLOOD_MS) -> Plan:
    """The plan, or SynthError with every reason it is refused (ctlclient's own check_config included)."""
    problems: List[str] = []
    if name not in PLANS:
        raise SynthError("plan %r is not one of %s" % (name, ", ".join(PLANS)))
    if port is None:
        port = cc.STAMP_PORT if name == "stamp" else cc.CLAIM_PORT
    for what, x in (("deadline", deadline_ms), ("control period", period_ms)):
        if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
            problems.append("the %s %r ms is not a positive int" % (what, x))
    if not problems and period_ms >= deadline_ms:
        problems.append("the control period %d ms is not inside the deadline %d ms: the monitor would close the connection "
                        "between two honest frames" % (period_ms, deadline_ms))
    if not problems and period_ms > contract.DT_MAX_MS:
        problems.append("the control period %d ms is above the contract's DT_MAX_MS %r: every honest frame after the first "
                        "would get 11" % (period_ms, contract.DT_MAX_MS))
    wait = WAIT_FACTOR * deadline_ms if not problems else 0
    designed: Dict[int, int] = {}
    frames: Optional[int] = None
    kw: Dict[str, Any] = {}
    if name == "reasons":
        kw["injections"] = tuple((reason_seq(r), m) for r, m in REASON_INJECTIONS)
        designed = {reason_seq(r): r for r, _m in REASON_INJECTIONS}
        frames = reason_seq(REASON_INJECTIONS[-1][0]) + 1
        bad = [(r, m) for r, m in REASON_INJECTIONS if cc.INJECTION_REASONS.get(m) != r]
        if bad:
            problems.append("ctlclient's injections give other reasons than the plan's table: %r" % (bad,))
    elif name == "silence":
        kw["pause"] = (LEAD_FRAMES, wait)
        designed = {LEAD_FRAMES + 1: cf.RSN_CTL_INTERVAL}
        frames = LEAD_FRAMES + TAIL_FRAMES
        if not problems and not wait > contract.DT_MAX_MS:
            problems.append("the silence of %d ms is not above the contract's DT_MAX_MS %r: its first frame would not get 11"
                            % (wait, contract.DT_MAX_MS))
    elif name == "late":
        frames = LATE_FRAMES
    elif name == "flood":
        if not problems and flood_ms < 2 * period_ms:
            problems.append("--flood-ms %r is shorter than two control periods (%d ms)" % (flood_ms, 2 * period_ms))
        kw["demo"] = (LEAD_FRAMES * period_ms - period_ms // 2, flood_ms)
        demo = contract.PROFILES.get(cc.DEMO_PROFILE)
        if demo is not None and not demo["v_max"] < cf.f32(HONEST_V_MPS):
            problems.append("profile %d's v_max %r is not below the honest velocity %r m/s: the window's frames would not get 12"
                            % (cc.DEMO_PROFILE, demo["v_max"], cf.f32(HONEST_V_MPS)))
    else:
        kw["stamp"] = True
        frames = STAMP_FRAMES
    cfg = cc.Config(host=host, port=port, profile=profile, **kw)
    if name != "stamp" and cfg.is_stamp():
        problems.append("the %s plan is for the claim port: :%d is the stamp plan's" % (name, cc.STAMP_PORT))
    problems.extend(cc.check_config(cfg, contract))
    if isinstance(profile, int) and profile in tuple(contract.COMPILED_PROFILE_IDS) and profile != cc.DEMO_PROFILE:
        problems.extend(honest_problems(contract, profile))
    if problems:
        raise SynthError("; ".join(problems))
    return Plan(name=name, config=cfg, frames=frames, wait_ms=wait if name == "late" else 0, period_ms=period_ms,
                deadline_ms=deadline_ms, flood_ms=flood_ms if name == "flood" else None, designed=designed)


# --- the checks ----------------------------------------------------------------------------------------------------------

def _profile_of(rec: Mapping[str, Any]) -> int:
    return bytes.fromhex(rec["frame"])[cf.FRAME_HEADER_BYTES + cf.P_PROFILE]


def designed_reason(plan: Plan, rec: Mapping[str, Any]) -> int:
    """The reason a frame of this plan is designed to get (0: ACCEPT)."""
    if plan.config.demo is not None:
        return cf.RSN_CTL_SPEED if _profile_of(rec) == cc.DEMO_PROFILE else cf.RSN_OK
    return plan.designed.get(rec["seq"], cf.RSN_OK)


def _check(name: str, problems: Sequence[str], note: str = "") -> Check:
    return Check(name, FAIL, "; ".join(problems[:6]) + ("; ..." if len(problems) > 6 else "")) if problems else Check(name, PASS, note)


def reply_checks(plan: Plan, contract: Any, records: Sequence[Mapping[str, Any]], summary: Mapping[str, Any],
                 facts: Mapping[str, Any]) -> List[Check]:
    """The checks on the replies (the reply log's records and the core's summary) and on the run's own facts."""
    n = summary["counters"]
    out = []
    p = []
    unreplied = [r["seq"] for r in records if r["outcome"] != "replied"]
    if unreplied:
        p.append("seqs %s not replied" % unreplied[:8])
    if len(records) != n["packed"] or (plan.frames is not None and len(records) != plan.frames):
        p.append("%d records for %d packed frames (the plan's: %s)" % (len(records), n["packed"], plan.frames))
    if not summary["identity"]["holds"] or summary.get("fatal") is not None:
        p.append("the identity %r, fatal %r" % (summary["identity"], summary.get("fatal")))
    if facts.get("stopped"):
        p.append("the plan stopped: %s" % facts["stopped"])
    out.append(_check(CHK_REPLIED, p))
    p = []
    for r in records:
        if r["outcome"] != "replied":
            continue
        want = designed_reason(plan, r)
        if (r["verdict"], r["reason"]) != (int(want != cf.RSN_OK), want):
            p.append("seq %d: designed reason %d, answered verdict %s reason %s" % (r["seq"], want, r["verdict"], r["reason"]))
    out.append(_check(CHK_DESIGNED, p))
    if plan.name == "silence":
        p = []
        if n["reconnects"] != 1 or n["connects"] != 2:
            p.append("connects %d, reconnects %d (one reconnect after the silence)" % (n["connects"], n["reconnects"]))
        if n["controls_paused"] < 1:
            p.append("no Control was paused")
        out.append(_check(CHK_SILENCE, p))
    elif plan.name == "late":
        p = []
        if facts.get("connections_during_wait") != 0:
            p.append("%r connection attempts during the wait" % (facts.get("connections_during_wait"),))
        if n["connects"] != 1 or n["connect_failures"] != 0:
            p.append("connects %d, connect failures %d after the wait (one connection)" % (n["connects"], n["connect_failures"]))
        out.append(_check(CHK_LATE, p))
    elif plan.name == "flood":
        prof = [_profile_of(r) for r in records]
        window = [i for i, x in enumerate(prof) if x == cc.DEMO_PROFILE]
        p = []
        if len(window) < 2:
            p.append("%d frames in the window (at least two)" % len(window))
        elif window != list(range(window[0], window[-1] + 1)):
            p.append("the profile 2 frames %s are not one window" % [records[i]["seq"] for i in window][:8])
        else:
            if window[0] < 1:
                p.append("no honest frame before the window")
            if len(prof) - 1 - window[-1] < TAIL_FRAMES:
                p.append("%d honest frames after the window (%d)" % (len(prof) - 1 - window[-1], TAIL_FRAMES))
        other = sorted(set(prof) - {plan.config.profile, cc.DEMO_PROFILE})
        if other:
            p.append("frames of profile %s" % other)
        out.append(_check(CHK_FLOOD, p))
    elif plan.name == "stamp":
        p = []
        for r in records:
            if r["outcome"] == "replied":
                t_in, t_out = r.get("t_in_ns"), r.get("t_out_ns")
                if not (isinstance(t_in, int) and isinstance(t_out, int) and 0 < t_in <= t_out):
                    p.append("seq %d: t_in %r, t_out %r" % (r["seq"], t_in, t_out))
        out.append(_check(CHK_STAMPS, p))
        p = []
        trials = [("injection " + m, dataclasses.replace(plan.config, injections=((1, m),))) for m in cc.INJECTIONS]
        trials += [("the pause", dataclasses.replace(plan.config, pause=(1, 100))),
                   ("the demo window", dataclasses.replace(plan.config, demo=(0, 100)))]
        for what, cfg in trials:
            if not any("refused on a stamp target" in x for x in cc.check_config(cfg, contract)):
                p.append("%s is not refused on this target" % what)
        out.append(_check(CHK_STAMP_REFUSED, p))
    return out


def console_lines(text: str) -> List[str]:
    """A console's lines with the guest console's CR and NUL bytes taken out."""
    return [ln.replace("\0", "").replace("\r", "") for ln in text.splitlines()]


def _g(x: float) -> str:
    return "%g" % x                    # C's %g, as the monitor prints a double (Python's %g is C's)


def console_rules_problems(contract: Any, text: str) -> List[str]:
    """Why the console's ctl lines are not this contract's (an empty list: they are): every whole `ctl rules:` line
    names its digest, DT_MAX_MS, the four constants and the compiled ids, and every whole `ctl profile` line is a
    compiled row's, each row present; at least one whole rules line. A fragment (console_rules_fragments) is judged no
    further: on the guest's serial console every monitor process prints these lines at boot, and another's output may
    split one, while the whole ones carry the contract."""
    k = contract
    ids = " ".join(str(i) for i in k.COMPILED_PROFILE_IDS)
    rules = re.compile(re.escape("monitor: ctl rules: kind 2, catalog 0x%08X (vss " % k.DIGEST) + r"[^()]*"
                       + re.escape("), dt_max %d ms, overspeed %s x v_cmd + %s m/s, rollback %s m/s, tol17 %s m/s^2, profiles %s"
                                   % (k.DT_MAX_MS, _g(k.OVERSPEED_FACTOR), _g(k.OVERSPEED_MARGIN), _g(k.ROLLBACK_V),
                                      _g(k.TOL17), ids)))
    rows = set()
    for pid in k.COMPILED_PROFILE_IDS:
        pr = k.PROFILES[pid]
        rows.add("monitor: ctl profile %d: L %d mm, v_max %s m/s, a_max %s m/s^2, jerk_max %s m/s^3, steer_max %s rad, "
                 "steer_rate_max %s rad/s, lat_acc_max %s m/s^2" % (pid, pr["l_mm"], _g(pr["v_max"]), _g(pr["a_max"]),
                                                                   _g(pr["jerk_max"]), _g(pr["steer_max"]),
                                                                   _g(pr["steer_rate_max"]), _g(pr["lat_acc_max"])))
    lines = console_lines(text)
    out = []
    rl = [ln for ln in lines if RULES_LINE_RE.fullmatch(ln)]
    if not rl:
        out.append("the console holds no whole `ctl rules:` line (is it the ctl build's console?)")
    out.extend("a ctl rules line is not the contract's (catalog 0x%08X, dt_max %d ms, profiles %s): %s"
               % (k.DIGEST, k.DT_MAX_MS, ids, ln) for ln in rl if not rules.fullmatch(ln))
    pl = [ln for ln in lines if PROFILE_LINE_RE.fullmatch(ln)]
    out.extend("a ctl profile line is not a compiled row of the contract: %s" % ln for ln in pl if ln not in rows)
    if rl:
        out.extend("no console line for the contract's row: %s" % row for row in sorted(rows - set(pl)))
    return out


def console_rules_fragments(text: str) -> List[str]:
    """The console's lines that begin as a `ctl rules:` or `ctl profile` line and have not its whole shape: lines
    another process's output split on a shared console. The preflight judges none of them; the result names them."""
    return [ln for ln in console_lines(text) if ln.startswith(CTL_LINE_PREFIXES)
            and not (RULES_LINE_RE.fullmatch(ln) or PROFILE_LINE_RE.fullmatch(ln))]


def console_checks(plan: Plan, records: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], text: str) -> List[Check]:
    """The checks on the console's text since the plan's first Control was due (CR and NUL bytes taken out)."""
    n = summary["counters"]
    lines = console_lines(text)
    seqs = {r["seq"] for r in records}
    designed = {r["seq"]: designed_reason(plan, r) for r in records if r["outcome"] == "replied"}
    profile = {r["seq"]: _profile_of(r) for r in records}
    rejects = [(i, int(m.group(1)), ln) for i, ln in enumerate(lines) for m in [ANY_REJECT_RE.match(ln)] if m]
    out = []
    p = []
    dones = [DONE_RE.fullmatch(ln) for ln in lines if ln.startswith("monitor: client done:")]
    totals = [tuple(int(x) for x in m.groups()) for m in dones if m]
    if len(totals) != len(dones) or len(totals) != n["connects"]:
        p.append("%d `client done:` lines for %d connections" % (len(dones), n["connects"]))
    elif tuple(map(sum, zip(*totals))) != (n["replied"], n["accepted"], n["rejected"]):
        p.append("the sessions' totals %s are not the replies' (%d, %d, %d)" % (totals, n["replied"], n["accepted"], n["rejected"]))
    out.append(_check(CON_TOTALS, p))
    if plan.name in ("reasons", "silence"):
        p = []
        for s in sorted(seqs):
            got = [ln for _i, q, ln in rejects if q == s]
            want = designed.get(s, cf.RSN_OK)
            if want == cf.RSN_OK:
                if got:
                    p.append("seq %d is honest but has %d REJECT line(s)" % (s, len(got)))
                continue
            line = "monitor: REJECT seq=%d kind=ctl profile=%d reason=%s" % (s, profile[s], cf.REASON_NAMES[want])
            if got != [line]:
                p.append("seq %d: %r, not [%r]" % (s, got, line))
        out.append(_check(CON_REJECTS, p))
    if plan.name == "silence":
        p = []
        last, first = LEAD_FRAMES, LEAD_FRAMES + 1
        closed = [m for ln in lines for m in [CLOSED_RE.fullmatch(ln)] if m]
        if [int(m.group(1)) for m in closed] != [plan.deadline_ms]:
            p.append("the `client closed: no complete frame` lines %s, not one of %d ms" % ([m.group(0) for m in closed], plan.deadline_ms))
        miss = [(i, m) for i, ln in enumerate(lines) for m in [MISS_RE.fullmatch(ln)] if m]
        restored = [(i, m) for i, ln in enumerate(lines) for m in [RESTORED_RE.fullmatch(ln)] if m]
        start, note = -1, ""
        if restored and int(restored[0][1].group(1)) == 1:
            # The port served an earlier session and has missed its deadline since (the liveness is the process's):
            # this plan's first frame ends that silence, with the earlier MISS just before it when the two come
            # together. The session's own lines start there.
            start, note = restored[0][0], "this plan's first frame ended an earlier silence on the port: %s" % restored[0][1].group(0)
            restored = restored[1:]
        mine = [(i, m) for i, m in miss if i > start and int(m.group(1)) == last]
        if len(mine) != 1 or int(mine[0][1].group(2)) != plan.deadline_ms:
            p.append("not one MISS since seq=%d with deadline %d ms: %s" % (last, plan.deadline_ms, [m.group(0) for _i, m in miss]))
        if [int(m.group(1)) for _i, m in restored] != [first]:
            p.append("the RESTORED lines %s, not one for seq=%d" % ([m.group(0) for _i, m in restored], first))
        elif len(mine) == 1 and not mine[0][0] < restored[0][0]:
            p.append("the RESTORED comes before the MISS")
        out.append(_check(CON_SILENCE, p, note))
    elif plan.name == "late":
        ends = [i for i, ln in enumerate(lines) if ln.startswith("monitor: client done:")]
        p = []
        for ln in lines[:ends[-1]] if ends else lines:
            m = MISS_RE.fullmatch(ln)
            if ln.startswith("monitor: client closed:") or (m is not None and int(m.group(1)) in seqs):
                p.append("%r before the session's end" % ln)
        out.append(_check(CON_LATE, p))
    elif plan.name == "flood":
        p = []
        window = sorted(s for s in seqs if profile[s] == cc.DEMO_PROFILE)
        seen = [ln for _i, q, ln in rejects if q in seqs]
        expected = ["monitor: REJECT seq=%d kind=ctl profile=%d reason=%s" % (window[0], cc.DEMO_PROFILE,
                                                                              cf.REASON_NAMES[cf.RSN_CTL_SPEED])] if window else []
        if seen != expected:
            p.append("the REJECT lines %s, not %s" % (seen[:4], expected))
        suppressed = 0
        for ln in lines:
            if ln.startswith("monitor: ctl summary:"):
                m = SUMMARY_RE.fullmatch(ln)
                pairs = re.findall(r" (\d+)=(\d+)", m.group(4)) if m else []
                if not m or [r for r, _x in pairs] != [str(cf.RSN_CTL_SPEED)] or int(pairs[0][1]) != int(m.group(3)):
                    p.append("a summary of another form or reason: %r" % ln)
                    continue
                suppressed += int(m.group(3))
        if window and suppressed != len(window) - 1:
            p.append("the summaries suppress %d lines, the window's frames after its first are %d" % (suppressed, len(window) - 1))
        out.append(_check(CON_FLOOD, p))
    return out


# --- the run ---------------------------------------------------------------------------------------------------------------

def _read_log(path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return lines[0]["header"], lines[1:-1], lines[-1]["summary"]


def _console_text(console: Optional[Path], offset: int) -> str:
    if console is None:
        return ""
    data = console.read_bytes()
    if len(data) < offset:
        raise SynthError("the console %s shrank during the run" % console)
    return data[offset:].decode("utf-8", "replace")


def _wait_until(c: Any, clock: Callable[[], int], due: int) -> None:
    while True:
        now = clock()
        if now >= due:
            return
        c.wait(min((due - now) / 1e9, POLL_S))


def _done(plan: Plan, c: Any) -> bool:
    if plan.frames is not None:
        return bool(c.n["packed"] >= plan.frames)
    demo = c.summary()["demo"]
    return bool(demo is not None and demo["last_seq"] is not None and c.n["packed"] - demo["last_seq"] >= TAIL_FRAMES)


def _max_offers(plan: Plan) -> int:
    span = (plan.config.pause[1] if plan.config.pause else 0) + (sum(plan.config.demo) if plan.config.demo else 0)
    return (plan.frames or 0) + span // plan.period_ms + LEAD_FRAMES + TAIL_FRAMES + OFFER_MARGIN


def _await_first_outcome(c: Any) -> None:
    """Until the first frame has its outcome -- a reply, valid or not, or none, which ctlclient's reply timeout settles
    as lost -- no second Control is offered (for at most twice that timeout, should a connect never complete)."""
    end = time.monotonic() + 2 * cc.REPLY_TIMEOUT_NS / 1e9
    while c.n["replied"] + c.n["lost_on_reconnect"] + c.n["drop"] < 1 and time.monotonic() < end:
        c.wait(POLL_S)


def run(plan: Plan, contract: Any, run_dir: Path, console: Optional[Path] = None,
        clock: Callable[[], int] = time.monotonic_ns) -> Dict[str, Any]:
    """The plan against its target, inline (no client thread): the wait, the Controls at the control rate, the stop
    (ctlclient's drain), then the checks; result.json written and returned."""
    head = console.read_bytes() if console is not None else b""
    fragments = console_rules_fragments(head.decode("utf-8", "replace"))
    offset = len(head)
    t0 = clock()
    header = {"plan": plan.name, "period_ms": plan.period_ms, "deadline_ms": plan.deadline_ms, "wait_ms": plan.wait_ms,
              "flood_ms": plan.flood_ms, "frames": plan.frames, "t0_ns": t0, "console": console is not None,
              "ctlsynth_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    c = cc.CtlClient(plan.config, contract, clock=clock, reply_log=run_dir / cc.REPLY_LOG, mode=MODE,
                     header_extra={"synth": header})
    facts: Dict[str, Any] = {}
    try:
        _wait_until(c, clock, t0 + plan.wait_ms * MS)
        facts["connections_during_wait"] = c.n["connects"] + c.n["connect_failures"]
        if console is not None:
            # The session begins at its first Control: its console is read from here. After the late plan's wait (twice
            # the deadline) an earlier session's MISS on the port has been printed, so it is never read as this one's.
            offset = console.stat().st_size
        start = clock()
        k = 0
        while not _done(plan, c) and k < _max_offers(plan):
            due = start + k * plan.period_ms * MS
            _wait_until(c, clock, due)
            if k == 1:
                _await_first_outcome(c)
            if c.n["reply_invalid"]:
                facts["stopped"] = ("a reply ctlclient found invalid, %d frame(s) packed (a stamp port this plan did not mark, "
                                    "or a peer that is no monitor): no Control offered after it" % c.n["packed"])
                break
            ctl, odom = honest(stamp_ns=due, recv_ns=clock())
            c.offer(ctl, odom)
            c.pump()
            k += 1
        facts["offered"] = k
    finally:
        summary = c.stop(drain=True)
    _header, records, summary = _read_log(run_dir / cc.REPLY_LOG)
    checks = reply_checks(plan, contract, records, summary, facts)
    names = [CON_RULES] + [x.name for x in console_checks(plan, records, summary, "")]
    if console is None:
        checks += [Check(x, NOT_CHECKED, "no --console") for x in names]
    else:
        end = time.monotonic() + CONSOLE_WAIT_S
        while True:
            con = console_checks(plan, records, summary, _console_text(console, offset))
            if all(x.status == PASS for x in con) or time.monotonic() >= end:
                break
            time.sleep(POLL_S)
        rules_note = "checked before the first frame"
        if fragments:
            rules_note += "; %d line(s) split by other output, judged no further: %s" % (len(fragments), "; ".join(map(repr, fragments[:4])))
        checks += [Check(CON_RULES, PASS, rules_note)] + con
    result = {"format": RESULT_FORMAT, "plan": plan.name, "passed": all(x.status != FAIL for x in checks),
              "console_checked": console is not None, "facts": facts, "checks": [dataclasses.asdict(x) for x in checks]}
    (run_dir / RESULT).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


# --- the command line --------------------------------------------------------------------------------------------------------

def argument_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ctlsynth.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True, choices=PLANS)
    ap.add_argument("--host", required=True, help="the monitor's address (the guest's, on the bridge)")
    ap.add_argument("--port", type=int, help="the monitor's port (default :%d; :%d for the stamp plan)" % (cc.CLAIM_PORT, cc.STAMP_PORT))
    ap.add_argument("--profile", type=int, default=1, help="the base kind 2 profile (default %(default)s)")
    ap.add_argument("--contract", default=str(cc.DEFAULT_CONTRACT), help="the kind 2 contract vss_ctl.py (default %(default)s)")
    ap.add_argument("--deadline-ms", type=int, default=DEADLINE_MS, help="the claim port's svc deadline (default %(default)s)")
    ap.add_argument("--period-ms", type=int, default=CONTROL_PERIOD_MS, help="the control rate's period (default %(default)s)")
    ap.add_argument("--flood-ms", type=int, default=FLOOD_MS, help="profile 2's window in the flood plan (default %(default)s)")
    ap.add_argument("--console", help="the monitor's console capture, read from its end when the plan starts")
    ap.add_argument("--check", action="store_true", help="a judged run: refuse to start without --console")
    ap.add_argument("--out", required=True, help="the run directory for %s and %s (never inside a work tree)" % (cc.REPLY_LOG, RESULT))
    return ap


def prepare(args: argparse.Namespace) -> Tuple[Plan, Any, Optional[Path], Path]:
    """The plan, the contract, the console and the run directory; every refusal a SynthError before anything is sent or
    made (the run directory last)."""
    problems: List[str] = []
    if args.check and not args.console:
        problems.append("--check needs --console: a judged run reads the monitor's console")
    try:
        contract = cf.load_contract(args.contract)
    except cf.ContractError as err:
        raise SynthError("; ".join(problems + [str(err)])) from err
    try:
        plan: Optional[Plan] = build_plan(args.plan, contract, args.host, port=args.port, profile=args.profile,
                                          deadline_ms=args.deadline_ms, period_ms=args.period_ms, flood_ms=args.flood_ms)
    except SynthError as err:
        plan = None
        problems.append(str(err))
    console = None
    if args.console:
        console = Path(args.console)
        if not console.is_file():
            problems.append("the console %s is not a file" % console)
        else:
            problems.extend(console_rules_problems(contract, console.read_bytes().decode("utf-8", "replace")))
    if problems or plan is None:
        raise SynthError("; ".join(problems))
    try:
        run_dir = cc.open_run_dir(args.out)
    except cc.ClientError as err:
        raise SynthError(str(err).replace("refused: ", "", 1)) from err
    return plan, contract, console, run_dir


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = argument_parser().parse_args(argv)
    try:
        plan, contract, console, run_dir = prepare(args)
    except (SynthError, OSError) as err:
        print("ctlsynth: refused: %s" % err, file=sys.stderr, flush=True)
        return 2
    try:
        result = run(plan, contract, run_dir, console)
    except KeyboardInterrupt:
        print("ctlsynth: interrupted", file=sys.stderr, flush=True)
        return 1
    except (SynthError, OSError, ValueError, cc.ClientError) as err:
        print("ctlsynth: the run failed after it started: %s: %s" % (type(err).__name__, err), file=sys.stderr, flush=True)
        return 1
    for x in result["checks"]:
        print("CHECK %s %s%s" % (x["name"], x["status"], (": " + x["detail"]) if x["detail"] else ""), flush=True)
    print("ctlsynth: plan %s %s" % (plan.name, ("passed" if result["console_checked"] else "passed, console NOT CHECKED")
                                   if result["passed"] else "FAILED"), file=sys.stderr, flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
