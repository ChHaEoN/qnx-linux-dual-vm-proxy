"""ctlsynth.py, the kind 2 synthetic client (SDV plan Phase 8, WP5; the Phase 8 specification
spec-2.md, section 8.1; the project's local design notes, not in this tree).

sdv/ctl/ctlsynth.py drives ctlclient.py's core (the claim node's core, imported) with synthetic Controls at a fixed
rate against a monitor at --host and --port, writes ctlclient's reply log with its header, and checks each reply
against the frame's designed reason; with --console it also reads the monitor's console. What is held here:

- Pure (no gcc; WP2's fixture contract tests/fixtures/ctl-py/vss_ctl.py): the five plans as built (the reasons plan
  one injection per reason 8-19 at its fixed even seq with honest frames between, the silence's pause, the late wait,
  the flood's window, the stamp target); the honest Control and every injected frame under the reference judge
  (ctlrules, which ctlsynth itself never imports); every refusal before anything is sent (exit 2, no connection
  reaches a listening port, nothing written); the reply checks and the console checks on crafted runs, each fault
  failing the one check it belongs to, and a silence plan's window opened by an earlier session's RESTORED for seq 1;
  the console preflight judging whole ctl lines and naming a split one; the imports (the standard library, ctlclient
  and ctlframe only) and no address in the file.
- Against a Python peer on loopback that answers as a stamp port, slower than a control period: a claim plan offers no
  second Control before its first frame's outcome, so the peer gets one honest frame.
- With gcc and the generation (sdv-out/gen; WSL, CI's tooling job): each plan against the native ctl build of monitor.c
  on loopback, the claim port in `PORT svc 300` and the stamp port in `PORT stamp`, the monitor's stdout its console:
  exit 0, every reply its designed reason, the reply log's header, the console's lines. And the plan fails, naming
  the frame, against a monitor that answers another reason than the designed one (compiled from the generated
  vss_ctl.h with another DT_MAX_MS), and the stamp plan against a monitor that writes no stamps; with that monitor's
  console the run is refused before anything is sent. Several plans on one monitor and one console, as the board
  session runs them: the silence plan after the reasons plan and a pause above the deadline, the late plan twice at
  once; a claim plan at a stamp monitor stops at its first reply; a ctl rules line split by another line refuses
  nothing.

Nothing here is a result: every value is a design value of ctlsynth, the fixture's or the generation's.

What this does NOT show: that the guest (the qcc build in ifs-ctl.bin) judges kind 2 or prints these lines (8.3
builds it, 8.4 boots it with the owner at the plug); any timing (a wait below only bounds when an event may come on a
loaded host; the plans' spacing is the control rate as closely as the host's scheduler allows).
"""
import ast
import dataclasses
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import twin_gate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CTL_DIR = REPO / "sdv" / "ctl"
SYNTH = CTL_DIR / "ctlsynth.py"
MONITOR_C = REPO / "ipc-test" / "qnx-safety-monitor" / "monitor.c"
COMMON = REPO / "ipc-test" / "common"
PY_FIXTURE = HERE / "fixtures" / "ctl-py" / "vss_ctl.py"
GEN_FILES = ("vss_contract.h", "vss_profiles.h", "vss_contract.py", "vss_ctl.h", "vss_ctl.py")

# tests/test_monitor_vss.py's DEFAULT_FLAGS and the ctl build's two additions, written out here.
DEFAULT_FLAGS = ("-O2", "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Wundef", "-Werror")
CTL_FLAGS = DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x14")

SVC_MS = 300                    # spec-2 8.1: the tests run the native ctl build in `PORT svc 300`
SLACK_S = 10.0                  # how long a wait may run on a loaded host before the test gives up
MS = 1_000_000
T0 = 10 ** 12
VARIANT_DT_MAX_MS = 5000        # above the interval injection's DT_MAX_MS + 1, so the variant accepts that frame

# The plans' shapes as spec-2 8.1 and ctlsynth's design values give them, written out here.
DESIGNED = ((8, "profile0"), (9, "nan"), (10, "undef"), (11, "interval"), (12, "speed"), (13, "accel"), (14, "jerk"),
            (15, "steer"), (16, "steer-rate"), (17, "lat-accel"), (18, "overspeed"), (19, "rolling-back"))
REASON_SEQ = {r: 2 * (r - 7) for r, _m in DESIGNED}        # the even seqs 2..24; honest frames at the odd seqs 1..25
REASONS_FRAMES = 25
LEAD, TAIL, LATE_FRAMES, STAMP_FRAMES = 3, 3, 5, 5
# The monitor's reason names (monitor.c's reason_name(), 2.3), written out here.
NAMES = {8: "profile-unbound", 9: "field-not-finite", 10: "flags-invalid", 11: "ctl-interval", 12: "ctl-speed",
         13: "ctl-accel", 14: "ctl-jerk", 15: "ctl-steer", 16: "ctl-steer-rate", 17: "ctl-lat-accel", 18: "ctl-overspeed",
         19: "ctl-rolling-back"}


# ============================================================ loading the package

def _import(name):
    """A module of sdv/ctl, imported as its siblings import it (its directory on sys.path), no bytecode written."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(CTL_DIR) not in sys.path:
            sys.path.insert(0, str(CTL_DIR))
        mod = importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved
    assert Path(mod.__file__).resolve().parent == CTL_DIR, (name, mod.__file__)
    return mod


cf = _import("ctlframe")
cc = _import("ctlclient")
cr = _import("ctlrules")


@pytest.fixture(scope="module")
def cs():
    return _import("ctlsynth")


@pytest.fixture(scope="module")
def K():
    """WP2's fixture contract, through WP2's loader: the pure tests' contract."""
    return cf.load_contract(PY_FIXTURE)


def _gen():
    gen = twin_gate.gen_dir()
    absent = [n for n in GEN_FILES if not (gen / n).is_file()]
    if absent:
        twin_gate.missing("needs the generated contract in %s (sdv/vss/generate.py): no %s" % (gen, ", ".join(absent)))
    return gen


@pytest.fixture(scope="module")
def G():
    """The generation's kind 2 contract (WP1b), the native builds' contract."""
    return cf.load_contract(_gen() / "vss_ctl.py")


# ============================================================ the plans as built

def test_the_reasons_plan_is_one_injection_per_reason_8_to_19_at_its_even_seq_with_honest_frames_between(cs, K):
    plan = cs.build_plan("reasons", K, "127.0.0.1")
    assert plan.name == "reasons" and plan.frames == REASONS_FRAMES
    assert plan.config.injections == tuple((REASON_SEQ[r], m) for r, m in DESIGNED)
    assert plan.config.port == cc.CLAIM_PORT and not plan.config.is_stamp()
    assert plan.config.pause is None and plan.config.demo is None and plan.config.profile == 1
    assert [cc.INJECTION_REASONS[m] for _s, m in plan.config.injections] == list(range(8, 20))
    assert plan.designed == {REASON_SEQ[r]: r for r, _m in DESIGNED}
    assert sorted(plan.designed) == list(range(2, REASONS_FRAMES, 2)), "honest frames at every odd seq, first and last"


def test_the_other_plans_their_pause_wait_window_and_stamp_target(cs, K):
    silence = cs.build_plan("silence", K, "127.0.0.1")
    assert silence.config.pause == (LEAD, 2 * cs.DEADLINE_MS) and silence.frames == LEAD + TAIL
    assert silence.designed == {LEAD + 1: 11} and silence.wait_ms == 0
    late = cs.build_plan("late", K, "127.0.0.1", deadline_ms=SVC_MS)
    assert late.wait_ms == 2 * SVC_MS and late.frames == LATE_FRAMES and late.designed == {}
    assert late.config.injections == () and late.config.pause is None and late.config.demo is None
    flood = cs.build_plan("flood", K, "127.0.0.1", flood_ms=300)
    assert flood.config.demo == (LEAD * 30 - 15, 300) and flood.frames is None and flood.designed == {}
    stamp = cs.build_plan("stamp", K, "127.0.0.1")
    assert stamp.config.port == cc.STAMP_PORT and stamp.config.stamp is True and stamp.frames == STAMP_FRAMES
    assert stamp.config.injections == () and stamp.config.pause is None and stamp.config.demo is None
    other = cs.build_plan("stamp", K, "127.0.0.1", port=40999)
    assert other.config.port == 40999 and other.config.is_stamp(), "the stamp plan marks any port it is given a stamp target"
    for name in ("reasons", "silence", "late", "flood"):
        assert cs.build_plan(name, K, "127.0.0.1").config.port == cc.CLAIM_PORT
    assert cs.CONTROL_PERIOD_MS == 30 and cs.DEADLINE_MS == 500


def _packed(cs, plan, K, n):
    """The frames ctlclient's core packs for n of the plan's honest Controls at the control rate, on a clock moved by
    hand (no connection: the core is never pumped)."""
    clk = [T0]
    c = cc.CtlClient(plan.config, K, clock=lambda: clk[0])
    frames = []
    try:
        for k in range(n):
            clk[0] = T0 + k * plan.period_ms * MS
            ctl, odom = cs.honest(stamp_ns=clk[0], recv_ns=clk[0])
            assert c.offer(ctl, odom) is not None
            frames.append(c.queued.frame)
    finally:
        c.stop(drain=False)
    return frames


def test_the_honest_control_is_accepted_under_profile_1_and_rejected_12_under_profile_2_by_the_reference_judge(cs, K):
    ctl, odom = cs.honest(stamp_ns=T0, recv_ns=T0)
    assert not (ctl.is_defined_acceleration or ctl.is_defined_jerk or ctl.is_defined_steering_tire_rotation_rate)
    assert odom is not None and odom.recv_ns == ctl.recv_ns and ctl.velocity == cs.HONEST_V_MPS
    late = _packed(cs, cs.build_plan("late", K, "127.0.0.1"), K, 3)
    assert [cr.judge(f, K, 0.001) for f in late] == [(0, 0)] * 3
    assert all(f[cf.FRAME_HEADER_BYTES] & cf.F_ODOM for f in late), "the odometry is fresh: rules 17-19 judge every frame"
    flood = _packed(cs, cs.build_plan("flood", K, "127.0.0.1", flood_ms=300), K, 20)
    profiles = [f[cf.FRAME_HEADER_BYTES + cf.P_PROFILE] for f in flood]
    assert profiles == [1] * LEAD + [2] * 10 + [1] * 7
    assert [cr.judge(f, K, 0.001) for f in flood] == [(0, 0)] * LEAD + [(1, 12)] * 10 + [(0, 0)] * 7


def test_every_frame_of_the_reasons_plan_gets_its_designed_reason_from_the_reference_judge(cs, K):
    plan = cs.build_plan("reasons", K, "127.0.0.1")
    frames = _packed(cs, plan, K, REASONS_FRAMES)
    got = {i + 1: cr.judge(f, K, 0.001) for i, f in enumerate(frames)}
    want = {s: (0, 0) for s in range(1, REASONS_FRAMES + 1)}
    want.update({REASON_SEQ[r]: (1, r) for r, _m in DESIGNED})
    assert got == want


# ============================================================ refusals before anything is sent

@pytest.fixture
def listener():
    """A loopback port that listens and never accepts: a connection to it would be waiting in its backlog."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(4)
    s.setblocking(False)
    yield s
    s.close()


def _nothing_connected(s):
    with pytest.raises(BlockingIOError):
        s.accept()[0].close()


REFUSALS = {
    # name: (plan, extra argv, the reason's words on stderr)
    "--check without --console": ("reasons", ["--check"], "--check needs --console"),
    "the late plan on the stamp port": ("late", ["--port", "<stamp>"], "the stamp plan's"),
    "the reasons plan on the stamp port": ("reasons", ["--port", "<stamp>"], "injections are refused on a stamp target"),
    "a control period the deadline does not hold": ("late", ["--period-ms", "300", "--deadline-ms", "300"],
                                                    "inside the deadline"),
    "a deadline of 0": ("late", ["--deadline-ms", "0"], "deadline"),
    "a flood beyond profile 2's window": ("flood", ["--flood-ms", "30001"], "run_window_max_ms"),
    "a flood shorter than two control periods": ("flood", ["--flood-ms", "59"], "two control periods"),
    "a silence the contract's DT_MAX_MS holds": ("silence", ["--deadline-ms", "50"], "DT_MAX_MS"),
    "the demo profile as the base profile": ("late", ["--profile", "2"], "demo profile"),
    "a profile the contract does not have": ("late", ["--profile", "9"], "not in the contract"),
    "a contract that does not load": ("late", ["--contract", "<tmp>/absent/vss_ctl.py"], "no kind 2 contract"),
    "a console that is not there": ("late", ["--console", "<tmp>/absent-console.txt"], "console"),
    "a console without the contract's ctl rules line": ("late", ["--console", "<tmp>/console.txt"], "ctl rules"),
    "a run directory that is not empty": ("late", ["--out", "<tmp>/full"], "not an empty directory"),
    "a run directory inside the work tree": ("late", ["--out", str(REPO / "tests" / "no-such-ctlsynth-run")], "work tree"),
    "a control period of 0": ("late", ["--period-ms", "0"], "control period"),
    "a control period above the contract's DT_MAX_MS": ("late", ["--period-ms", "201"], "above the contract's DT_MAX_MS"),
    # A period at DT_MAX_MS itself passes the DT_MAX_MS check, so the deadline check alone refuses it: this case tells the
    # deadline check's >= from > (the case above, 300 against 300, is past DT_MAX_MS too).
    "a control period equal to the deadline, at the contract's DT_MAX_MS": (
        "late", ["--period-ms", "200", "--deadline-ms", "200"], "inside the deadline"),
    "the demo profile as the stamp plan's base": ("stamp", ["--profile", "2"], "demo profile"),
    "the flood plan on the stamp port": ("flood", ["--port", "<stamp>"], "the stamp plan's"),
    "the silence plan on the stamp port": ("silence", ["--port", "<stamp>"], "the stamp plan's"),
}


@pytest.mark.parametrize("name", sorted(REFUSALS))
def test_each_refusal_comes_before_anything_is_sent_or_written(cs, K, tmp_path, listener, capsys, monkeypatch, name):
    plan, extra, words = REFUSALS[name]
    port = listener.getsockname()[1]
    if "<stamp>" in extra:
        # The listener is the stamp port the refusal is about: ctlclient's STAMP_PORT moved onto it, so a connection made
        # before the refusal would wait in its backlog and be seen (nothing listens on :7151 itself: one would not be).
        monkeypatch.setattr(cc, "STAMP_PORT", port)
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "kept.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "console.txt").write_text(
        "monitor: ctl rules: kind 2, catalog 0x%08X (vss v6.0), dt_max %d ms, overspeed 1.2 x v_cmd + 2 m/s, rollback 0.5 m/s, "
        "tol17 0.5 m/s^2, profiles 1 2\n" % (K.DIGEST ^ 1, K.DT_MAX_MS), encoding="utf-8")
    extra = [x.replace("<tmp>", str(tmp_path)).replace("<stamp>", str(port)) for x in extra]
    argv = ["--plan", plan, "--host", "127.0.0.1", "--port", str(port), "--contract", str(PY_FIXTURE),
            "--out", str(tmp_path / "run")] + extra
    rc = cs.main(argv)
    err = capsys.readouterr().err
    assert rc == 2, (rc, err)
    assert "ctlsynth: refused: " in err and words in err, err
    if cc.STAMP_PORT == port:
        assert ":%d" % port in err, "the refusal names the listener as the stamp port"
    _nothing_connected(listener)
    assert not (tmp_path / "run").exists(), "nothing is made before every refusal has been checked"
    assert sorted(p.name for p in (tmp_path / "full").iterdir()) == ["kept.txt"]
    assert not (REPO / "tests" / "no-such-ctlsynth-run").exists()


def test_a_control_period_of_exactly_the_contracts_dt_max_ms_is_not_refused(cs, K):
    """Rule 11 rejects an interval over DT_MAX_MS: a period equal to it is the largest one whose honest frames pass it."""
    plan = cs.build_plan("late", K, "127.0.0.1", period_ms=K.DT_MAX_MS)
    assert plan.period_ms == K.DT_MAX_MS
    with pytest.raises(cs.SynthError, match="above the contract's DT_MAX_MS"):
        cs.build_plan("late", K, "127.0.0.1", period_ms=K.DT_MAX_MS + 1)


def _contract_with(K, pid=None, row=None, **names):
    """K as a stand-in module: every public name K's, one profile row changed and any top-level name given."""
    k = types.SimpleNamespace(**{n: getattr(K, n) for n in dir(K) if not n.startswith("__")})
    k.PROFILES = {p: dict(r, **(row if p == pid else {})) for p, r in K.PROFILES.items()}
    for n, v in names.items():
        setattr(k, n, v)
    return k


@pytest.mark.parametrize("plan, pid, row, names, words", [
    ("late", 1, {"v_max": 3.5}, {}, "honest velocity"),
    ("late", 1, {"steer_max": 0.04}, {}, "honest steering"),
    ("late", 1, {"lat_acc_max": 0.1}, {"TOL17": 0.0}, "lateral acceleration"),
    ("flood", 2, {"v_max": 4.0}, {}, "not below the honest velocity"),
], ids=["profile 1 v_max under the honest speed", "profile 1 steer_max under the honest angle",
        "the honest lateral acceleration above lat_acc_max + TOL17", "profile 2 v_max not below the honest speed"])
def test_a_contract_the_honest_control_does_not_suit_is_refused(cs, K, plan, pid, row, names, words):
    with pytest.raises(cs.SynthError, match=words):
        cs.build_plan(plan, _contract_with(K, pid, row, **names), "127.0.0.1")


def test_the_contracts_own_honest_control_is_not_refused_under_every_plan(cs, K):
    """The control for the four refusals above: the same stand-in with nothing changed builds every plan."""
    for plan in cs.PLANS:
        assert cs.build_plan(plan, _contract_with(K), "127.0.0.1").name == plan


def test_host_and_out_and_plan_are_required_and_no_address_stands_in_the_file(cs):
    for missing in ("--host", "--out", "--plan"):
        argv = {"--host": "127.0.0.1", "--out": "/nonexistent-ctlsynth", "--plan": "late"}
        argv.pop(missing)
        with pytest.raises(SystemExit) as e:
            cs.main([x for kv in argv.items() for x in kv])
        assert e.value.code == 2, missing
    text = SYNTH.read_text(encoding="utf-8")
    assert re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text) is None, "no address in the tree (spec-2 8.1)"
    assert cs.PLANS == ("reasons", "silence", "late", "flood", "stamp")


@pytest.mark.parametrize("passed, checked, closing", [
    (True, False, "passed, console NOT CHECKED"), (True, True, "passed"), (False, False, "FAILED"), (False, True, "FAILED")],
    ids=["passed without the console read", "passed with it read", "failed without it", "failed with it"])
def test_the_closing_line_says_when_the_console_was_not_read_and_the_exit_code_stays_the_cores(cs, tmp_path, capsys, monkeypatch,
                                                                                            passed, checked, closing):
    """Without --console the plans' console checks are NOT CHECKED: the closing line must not read as a full verdict."""
    result = {"passed": passed, "console_checked": checked, "checks": [{"name": "a check", "status": "PASS", "detail": ""}]}
    monkeypatch.setattr(cs, "prepare", lambda args: (types.SimpleNamespace(name="silence"), None, None, tmp_path))
    monkeypatch.setattr(cs, "run", lambda plan, contract, run_dir, console: result)
    rc = cs.main(["--plan", "silence", "--host", "127.0.0.1", "--out", str(tmp_path / "run")])
    captured = capsys.readouterr()
    assert captured.err.splitlines()[-1] == "ctlsynth: plan silence %s" % closing, captured.err
    assert "CHECK a check PASS" in captured.out
    assert rc == (0 if passed else 1)


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module)
        elif isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("import_module", "__import__"):
            names.add("<dynamic import>")
    return names


def test_ctlsynth_imports_the_standard_library_ctlclient_and_ctlframe_only(cs):
    names = {m.split(".")[0] for m in _imports(SYNTH)}
    assert {"ctlclient", "ctlframe"} <= names
    assert not [m for m in names - {"ctlclient", "ctlframe"} if m not in sys.stdlib_module_names], names
    assert not names & {"ctlrules", "rules", "vssframe", "kind4_client", "<dynamic import>"}
    assert b"\r" not in SYNTH.read_bytes() and b"\r" not in Path(__file__).read_bytes()


# ============================================================ the checks on crafted runs

def _frame(seq, profile):
    return cf.pack_bits(seq=seq, tstamp_ns=T0, flags=0, profile=profile, v_cmd=cf.f32_bits(4.0), delta=cf.f32_bits(0.05))


def _rec(seq, profile, reason, **extra):
    r = {"seq": seq, "frame": _frame(seq, profile).hex(), "outcome": "replied", "verdict": int(reason != 0), "reason": reason,
         "mono_ns": T0 + seq * 30 * MS}
    r.update(extra)
    return r


def _summary(records, connects, **counters):
    n = dict.fromkeys(cc.COUNTERS, 0)
    n.update(controls=len(records), packed=len(records), replied=len(records), connects=connects, reconnects=connects - 1,
             accepted=sum(1 for r in records if r["verdict"] == 0), rejected=sum(1 for r in records if r["verdict"] == 1))
    n.update(counters)
    return {"counters": n, "identity": cc.identity(n), "demo": None, "last_reply": None, "fatal": None}


def _done(records):
    a = sum(1 for r in records if r["verdict"] == 0)
    return "monitor: client done: seen=%d accepted=%d rejected=%d" % (len(records), a, len(records) - a)


def _crafted(cs, K, name):
    """(plan, records, summary, facts, console lines) of a run that passes every check: the records and counters as
    ctlclient writes them and the lines the native monitor prints for them, written here."""
    plan = cs.build_plan(name, K, "127.0.0.1", deadline_ms=SVC_MS, port=None if name != "stamp" else 40999,
                         flood_ms=180 if name == "flood" else cs.FLOOD_MS)
    facts = {"connections_during_wait": 0}
    if name == "reasons":
        recs = [_rec(s, 0 if s == REASON_SEQ[8] else 1, plan.designed.get(s, 0)) for s in range(1, REASONS_FRAMES + 1)]
        lines = ["monitor: REJECT seq=%d kind=ctl profile=%d reason=%s" % (s, 0 if r == 8 else 1, NAMES[r])
                 for s, r in sorted(plan.designed.items())] + [_done(recs)]
        return plan, recs, _summary(recs, 1), facts, lines
    if name == "silence":
        recs = [_rec(s, 1, 11 if s == LEAD + 1 else 0) for s in range(1, LEAD + TAIL + 1)]
        lines = ["monitor: client closed: no complete frame for %d ms" % SVC_MS, _done(recs[:LEAD]),
                 "monitor: LIVENESS MISS: no claim for %d ms since seq=%d (deadline %d ms, miss 1)" % (SVC_MS, LEAD, SVC_MS),
                 "monitor: REJECT seq=%d kind=ctl profile=1 reason=ctl-interval" % (LEAD + 1),
                 "monitor: LIVENESS RESTORED: seq=%d after 640 ms without a claim" % (LEAD + 1), _done(recs[LEAD:])]
        return plan, recs, _summary(recs, 2, controls_paused=20), facts, lines
    if name == "late":
        recs = [_rec(s, 1, 0) for s in range(1, LATE_FRAMES + 1)]
        return plan, recs, _summary(recs, 1), facts, [_done(recs)]
    if name == "flood":
        profiles = [1] * LEAD + [2] * 6 + [1] * TAIL
        recs = [_rec(i + 1, p, 12 if p == 2 else 0) for i, p in enumerate(profiles)]
        lines = ["monitor: REJECT seq=%d kind=ctl profile=2 reason=ctl-speed" % (LEAD + 1),
                 "monitor: ctl summary: seen=7 rejected=4 suppressed=3 by reason: 12=3",
                 "monitor: ctl summary: seen=5 rejected=2 suppressed=2 by reason: 12=2", _done(recs)]
        s = _summary(recs, 1, demo_frames=6)
        s["demo"] = {"profile": 2, "first_seq": LEAD + 1, "last_seq": LEAD + 6, "frames": 6}
        return plan, recs, s, facts, lines
    recs = [_rec(s, 1, 0, t_in_ns=T0 + s * 7, t_out_ns=T0 + s * 7 + 3) for s in range(1, STAMP_FRAMES + 1)]
    return plan, recs, _summary(recs, 1), facts, [_done(recs)]


def _statuses(checks):
    return {c.name: c.status for c in checks}


@pytest.mark.parametrize("name", ["reasons", "silence", "late", "flood", "stamp"])
def test_a_crafted_run_passes_every_check_of_its_plan_crlf_and_nul_in_the_console_included(cs, K, name):
    plan, recs, summary, facts, lines = _crafted(cs, K, name)
    replies = cs.reply_checks(plan, K, recs, summary, facts)
    console = cs.console_checks(plan, recs, summary, "\r\n".join("\0" + ln for ln in lines) + "\r\n")
    assert replies and all(c.status == "PASS" for c in replies), replies
    assert console and all(c.status == "PASS" for c in console), console
    assert cs.CON_TOTALS in _statuses(console)


def _drop(lines, prefix):
    hit = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
    assert len(hit) == 1, (prefix, lines)
    return lines[:hit[0]] + lines[hit[0] + 1:]


def _sub(lines, old, new):
    hit = [i for i, ln in enumerate(lines) if old in ln]
    assert len(hit) == 1, (old, lines)
    return [ln.replace(old, new) if i == hit[0] else ln for i, ln in enumerate(lines)]


def _swap(lines, a, b):
    i = [k for k, ln in enumerate(lines) if ln.startswith(a)]
    j = [k for k, ln in enumerate(lines) if ln.startswith(b)]
    assert len(i) == len(j) == 1
    out = list(lines)
    out[i[0]], out[j[0]] = out[j[0]], out[i[0]]
    return out


def _insert_after(lines, prefix, new):
    hit = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
    assert len(hit) == 1, (prefix, lines)
    return lines[:hit[0] + 1] + [new] + lines[hit[0] + 1:]


MISS, RESTORED = "monitor: LIVENESS MISS:", "monitor: LIVENESS RESTORED:"
RESTORED_1 = "monitor: LIVENESS RESTORED: seq=1 after 640 ms without a claim"
CONSOLE_FAULTS = {
    # name: (plan, edit of the crafted lines, the console check that must fail)
    "reasons: a reject line with another reason": ("reasons", lambda ls: _sub(ls, "seq=4 kind=ctl profile=1 reason=field-not-finite",
                                                                               "seq=4 kind=ctl profile=1 reason=flags-invalid"), "CON_REJECTS"),
    "reasons: a reject line with another profile": ("reasons", lambda ls: _sub(ls, "seq=6 kind=ctl profile=1", "seq=6 kind=ctl profile=2"),
                                                    "CON_REJECTS"),
    "reasons: a reject line missing": ("reasons", lambda ls: _drop(ls, "monitor: REJECT seq=24 "), "CON_REJECTS"),
    "reasons: a reject line for an honest frame": ("reasons", lambda ls: ["monitor: REJECT seq=3 kind=ctl profile=1 reason=ctl-speed"] + ls,
                                                   "CON_REJECTS"),
    "reasons: a reject line twice": ("reasons", lambda ls: [ls[0]] + ls, "CON_REJECTS"),
    "reasons: a session total off by one": ("reasons", lambda ls: _sub(ls, "seen=25 accepted=13", "seen=24 accepted=12"), "CON_TOTALS"),
    "reasons: a reject line of another kind for an injected frame": (
        "reasons", lambda ls: _sub(ls, "seq=2 kind=ctl", "seq=2 kind=vss"), "CON_REJECTS"),
    "reasons: a malformed done line": ("reasons", lambda ls: ls + ["monitor: client done: seen=x"], "CON_TOTALS"),
    "silence: no MISS": ("silence", lambda ls: _drop(ls, MISS), "CON_SILENCE"),
    "silence: RESTORED before MISS": ("silence", lambda ls: _swap(ls, MISS, RESTORED), "CON_SILENCE"),
    "silence: the MISS of another seq": ("silence", lambda ls: _sub(ls, "since seq=3 ", "since seq=2 "), "CON_SILENCE"),
    "silence: the MISS of another deadline": ("silence", lambda ls: _sub(ls, "(deadline 300 ms", "(deadline 500 ms"), "CON_SILENCE"),
    "silence: no close at the deadline": ("silence", lambda ls: _drop(ls, "monitor: client closed:"), "CON_SILENCE"),
    "silence: a close at another deadline": ("silence", lambda ls: _sub(ls, "no complete frame for 300 ms", "no complete frame for 500 ms"),
                                             "CON_SILENCE"),
    "silence: the RESTORED of another seq": ("silence", lambda ls: _sub(ls, "RESTORED: seq=4 ", "RESTORED: seq=5 "), "CON_SILENCE"),
    "silence: the 11 line missing": ("silence", lambda ls: _drop(ls, "monitor: REJECT seq=4 "), "CON_REJECTS"),
    "silence: one session's done line missing": ("silence", lambda ls: _drop(ls, "monitor: client done: seen=3 accepted=3"), "CON_TOTALS"),
    "silence: a second RESTORED": ("silence", lambda ls: ls + ["monitor: LIVENESS RESTORED: seq=6 after 640 ms without a claim"],
                                   "CON_SILENCE"),
    "silence: a second close": ("silence", lambda ls: ls + ["monitor: client closed: no complete frame for 300 ms"], "CON_SILENCE"),
    # A RESTORED for seq 1 is the end of an earlier session's silence only where it opens the session's lines.
    "silence: a RESTORED for seq 1 after the session's MISS": ("silence", lambda ls: _insert_after(ls, MISS, RESTORED_1), "CON_SILENCE"),
    "silence: the RESTORED for seq 1 twice": ("silence", lambda ls: [RESTORED_1, RESTORED_1] + ls, "CON_SILENCE"),
    "silence: the session's RESTORED for seq 1, not its first after the pause": (
        "silence", lambda ls: _sub(ls, "RESTORED: seq=4 ", "RESTORED: seq=1 "), "CON_SILENCE"),
    "late: a close during the session": ("late", lambda ls: ["monitor: client closed: no complete frame for 300 ms"] + ls, "CON_LATE"),
    "late: a MISS for a frame of the session before its end": (
        "late", lambda ls: ["monitor: LIVENESS MISS: no claim for 300 ms since seq=2 (deadline 300 ms, miss 1)"] + ls, "CON_LATE"),
    "late: a session total off": ("late", lambda ls: _sub(ls, "seen=5 accepted=5", "seen=5 accepted=4"), "CON_TOTALS"),
    "flood: a second line in the window": ("flood", lambda ls: [ls[0].replace("seq=4 ", "seq=5 ")] + ls, "CON_FLOOD"),
    "flood: the line of another window frame": ("flood", lambda ls: _sub(ls, "REJECT seq=4 ", "REJECT seq=5 "), "CON_FLOOD"),
    "flood: the line with profile 1": ("flood", lambda ls: _sub(ls, "seq=4 kind=ctl profile=2", "seq=4 kind=ctl profile=1"), "CON_FLOOD"),
    "flood: the summaries one short": ("flood", lambda ls: _sub(ls, "suppressed=2 by reason: 12=2", "suppressed=1 by reason: 12=1"),
                                       "CON_FLOOD"),
    "flood: a summary with another reason": ("flood", lambda ls: _sub(ls, "suppressed=2 by reason: 12=2", "suppressed=2 by reason: 12=1 13=1"),
                                             "CON_FLOOD"),
    "flood: a reject line for an honest frame after the window": (
        "flood", lambda ls: ["monitor: REJECT seq=11 kind=ctl profile=1 reason=ctl-speed"] + ls, "CON_FLOOD"),
    "flood: a summary whose count is not its suppressed count": (
        "flood", lambda ls: _sub(ls, "suppressed=3 by reason: 12=3", "suppressed=3 by reason: 12=2"), "CON_FLOOD"),
    "stamp: the session total off": ("stamp", lambda ls: _sub(ls, "seen=5 accepted=5", "seen=6 accepted=6"), "CON_TOTALS"),
    "stamp: the done line missing": ("stamp", lambda ls: _drop(ls, "monitor: client done:"), "CON_TOTALS"),
}


@pytest.mark.parametrize("name", sorted(CONSOLE_FAULTS))
def test_each_console_fault_fails_exactly_the_check_it_belongs_to(cs, K, name):
    plan_name, edit, check = CONSOLE_FAULTS[name]
    plan, recs, summary, _facts, lines = _crafted(cs, K, plan_name)
    got = _statuses(cs.console_checks(plan, recs, summary, "\n".join(edit(lines)) + "\n"))
    want = dict.fromkeys(got, "PASS")
    want[getattr(cs, check)] = "FAIL"
    assert got == want


# What an earlier session on the same port leaves at the head of a silence plan's console window when the port's
# liveness has missed since it (monitor.c's svc mode: liveness is the process's, not the connection's): this plan's
# first frame restores it, and when that frame comes within a scheduler tick of the earlier deadline, the earlier MISS
# is printed with it, just before its RESTORED.
EARLIER_SESSION = {
    "its MISS before the plan started": [RESTORED_1],
    "its MISS printed with the plan's first frame, the reasons plan's last seq": [
        "monitor: LIVENESS MISS: no claim for 300 ms since seq=25 (deadline 300 ms, miss 1)", RESTORED_1],
    "its MISS printed with the plan's first frame, a session cut at the silence plan's seq 3": [
        "monitor: LIVENESS MISS: no claim for 300 ms since seq=3 (deadline 300 ms, miss 1)", RESTORED_1],
}


@pytest.mark.parametrize("name", sorted(EARLIER_SESSION))
def test_a_silence_plan_after_an_earlier_session_on_its_port_passes_and_names_the_restored_of_its_first_frame(cs, K, name):
    plan, recs, summary, _facts, lines = _crafted(cs, K, "silence")
    checks = cs.console_checks(plan, recs, summary, "\n".join(EARLIER_SESSION[name] + lines) + "\n")
    assert all(c.status == "PASS" for c in checks), checks
    silence = [c for c in checks if c.name == cs.CON_SILENCE]
    assert len(silence) == 1 and RESTORED_1 in silence[0].detail, silence


def _with(recs, seq, **changes):
    return [dict(r, **changes) if r["seq"] == seq else r for r in recs]


REPLY_FAULTS = {
    # name: (plan, edit of (records, summary, facts), the reply check that must fail)
    "a frame lost": ("late", lambda rs, s, f: (_with(rs, 3, outcome="lost", verdict=None, reason=None),
                                               _summary(rs, 1, replied=4, lost_on_reconnect=1, accepted=4), f), "CHK_REPLIED"),
    "a frame fewer than the plan's": ("reasons", lambda rs, s, f: (rs[:-1], _summary(rs[:-1], 1), f), "CHK_REPLIED"),
    "another reason than the designed one": ("reasons", lambda rs, s, f: (_with(rs, 8, verdict=0, reason=0), s, f), "CHK_DESIGNED"),
    "an injection answered with another reject reason": ("reasons", lambda rs, s, f: (_with(rs, 8, verdict=1, reason=12), s, f),
                                                         "CHK_DESIGNED"),
    "an honest frame rejected": ("reasons", lambda rs, s, f: (_with(rs, 9, verdict=1, reason=12), s, f), "CHK_DESIGNED"),
    "the silence without a reconnect": ("silence", lambda rs, s, f: (rs, _summary(rs, 1, controls_paused=20), f), "CHK_SILENCE"),
    "the silence with nothing paused": ("silence", lambda rs, s, f: (rs, _summary(rs, 2), f), "CHK_SILENCE"),
    "a connection during the late wait": ("late", lambda rs, s, f: (rs, s, {"connections_during_wait": 1}), "CHK_LATE"),
    "a second late connection": ("late", lambda rs, s, f: (rs, _summary(rs, 2), f), "CHK_LATE"),
    "profile 2 again after the window": ("flood", lambda rs, s, f: (_with(rs, 11, frame=_frame(11, 2).hex(), verdict=1, reason=12), s, f),
                                         "CHK_FLOOD"),
    # Honest frames before the window and TAIL after it, so only the window's being one run of frames is broken.
    "profile 2 on a frame before the window": ("flood", lambda rs, s, f: (_with(rs, 2, frame=_frame(2, 2).hex(), verdict=1, reason=12),
                                                                          s, f), "CHK_FLOOD"),
    "a window of one frame": ("flood", lambda rs, s, f: ([dict(r, frame=_frame(r["seq"], 1).hex(), verdict=0, reason=0)
                                                          if LEAD + 2 <= r["seq"] <= LEAD + 6 else r for r in rs], s, f), "CHK_FLOOD"),
    "no honest frame after the window": ("flood", lambda rs, s, f: (rs[:LEAD + 6], _summary(rs[:LEAD + 6], 1), f), "CHK_FLOOD"),
    "a reply without its stamps": ("stamp", lambda rs, s, f: (_with(rs, 2, t_in_ns=0, t_out_ns=0), s, f), "CHK_STAMPS"),
    "stamps out of order": ("stamp", lambda rs, s, f: (_with(rs, 4, t_in_ns=T0 + 9, t_out_ns=T0 + 8), s, f), "CHK_STAMPS"),
}


@pytest.mark.parametrize("name", sorted(REPLY_FAULTS))
def test_each_reply_fault_fails_exactly_the_check_it_belongs_to(cs, K, name):
    plan_name, edit, check = REPLY_FAULTS[name]
    plan, recs, summary, facts, _lines = _crafted(cs, K, plan_name)
    recs, summary, facts = edit(recs, summary, facts)
    got = _statuses(cs.reply_checks(plan, K, recs, summary, facts))
    want = dict.fromkeys(got, "PASS")
    want[getattr(cs, check)] = "FAIL"
    assert got == want


def test_the_stamp_check_fails_for_a_plan_whose_target_ctlclient_would_not_refuse_injections_on(cs, K):
    plan, recs, summary, facts, _lines = _crafted(cs, K, "stamp")
    plain = dataclasses.replace(plan, config=dataclasses.replace(plan.config, stamp=False))
    assert not plain.config.is_stamp()
    got = _statuses(cs.reply_checks(plain, K, recs, summary, facts))
    assert got[cs.CHK_STAMP_REFUSED] == "FAIL"


def _rules_lines(K, **changes):
    v = {"digest": K.DIGEST, "dt": K.DT_MAX_MS, "of": K.OVERSPEED_FACTOR, "om": K.OVERSPEED_MARGIN, "rb": K.ROLLBACK_V,
         "tol": K.TOL17, "ids": " ".join(str(i) for i in K.COMPILED_PROFILE_IDS), "v_max1": K.PROFILES[1]["v_max"]}
    v.update(changes)
    out = ["monitor: claim kinds: 0 mnist (us <= 1000000), 1 vlm model 1 (us <= 1000000), conf_min=60%",
           "monitor: ctl rules: kind 2, catalog 0x%08X (vss v6.0), dt_max %u ms, overspeed %g x v_cmd + %g m/s, rollback %g m/s, "
           "tol17 %g m/s^2, profiles %s" % (v["digest"], v["dt"], v["of"], v["om"], v["rb"], v["tol"], v["ids"])]
    for pid in K.COMPILED_PROFILE_IDS:
        p = dict(K.PROFILES[pid])
        if pid == 1:
            p["v_max"] = v["v_max1"]
        out.append("monitor: ctl profile %u: L %u mm, v_max %g m/s, a_max %g m/s^2, jerk_max %g m/s^3, steer_max %g rad, "
                   "steer_rate_max %g rad/s, lat_acc_max %g m/s^2" % (pid, p["l_mm"], p["v_max"], p["a_max"], p["jerk_max"],
                                                                     p["steer_max"], p["steer_rate_max"], p["lat_acc_max"]))
    return out


@pytest.mark.parametrize("change", [{}, {"digest": 0x0BADF00D}, {"dt": 101}, {"of": 1.25}, {"om": 2.5}, {"rb": 0.25},
                                    {"tol": 0.75}, {"ids": "1"}, {"ids": "1 2 3"}, {"v_max1": 24.5}],
                         ids=["the contract's", "another digest", "another dt_max", "another overspeed factor",
                              "another overspeed margin", "another rollback", "another tol17", "another profile list",
                              "a longer profile list", "another profile row"])
def test_the_console_preflight_takes_the_contracts_ctl_lines_only(cs, K, change):
    text = "\r\n".join(_rules_lines(K, **change) * 2) + "\r\n"
    problems = cs.console_rules_problems(K, text)
    assert (problems == []) == (change == {}), problems


def test_the_console_preflight_refuses_a_console_with_no_ctl_lines_or_one_wrong_among_right_ones(cs, K):
    assert cs.console_rules_problems(K, "monitor: claim kinds: 0 mnist\n") != []
    right, wrong = _rules_lines(K), _rules_lines(K, dt=K.DT_MAX_MS + 1)
    assert cs.console_rules_problems(K, "\n".join(right + wrong[1:2]) + "\n") != []
    assert cs.console_rules_problems(K, "\n".join(right[:2]) + "\n") != [], "a compiled profile's line is missing"
    extra = wrong[2].replace("ctl profile 1:", "ctl profile 3:")
    assert cs.console_rules_problems(K, "\n".join(right + [extra]) + "\n") != [], "a profile line beside the compiled rows"


def _split_by_another_line(line, at):
    """A console line with another process's line written into it, as on the guest's shared serial console."""
    return [line[:at], "monitor: vss profile 1: another process's line", line[at:]]


def test_the_console_preflight_judges_whole_ctl_lines_and_names_a_line_split_by_other_output_without_refusing(cs, K):
    right = _rules_lines(K)                        # claim kinds, the rules line, one line per compiled profile
    rules, prof = right[1], right[2]
    split = _split_by_another_line(rules, 40) + _split_by_another_line(prof, 30)
    # Seven monitor processes print their lines at boot: whole ones carry the contract, a split one is judged no further.
    text = "\r\n".join(right + split + right[1:]) + "\r\n"
    assert cs.console_rules_problems(K, text) == []
    assert cs.console_rules_fragments(text) == [rules[:40], prof[:30]]
    assert cs.console_rules_fragments("\n".join(right) + "\n") == []
    # A whole line with other values is still refused beside whole right ones and a fragment.
    wrong = _rules_lines(K, digest=K.DIGEST ^ 1)[1]
    assert [p for p in cs.console_rules_problems(K, text + wrong + "\n") if "not the contract's" in p], "another build's whole line"
    # Fragments only: no whole rules line carries the contract.
    only = "\n".join([right[0]] + split) + "\n"
    assert [p for p in cs.console_rules_problems(K, only) if "no whole `ctl rules:` line" in p], cs.console_rules_problems(K, only)


# ============================================================ a target that answers as no claim port does (a Python peer)

class StampingPeer:
    """A loopback peer that answers every frame as a stamp port does (the stamp span written: here every byte of it
    flipped, so the reply differs from the request there) after DELAY_S, longer than a control period, and keeps every
    frame it receives. A client that offered its second Control before its first frame's outcome would have that one
    queued, and sent on the reconnect, by the time the first reply is seen to be invalid."""

    DELAY_S = 0.1

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.srv.settimeout(0.05)
        self.port = self.srv.getsockname()[1]
        self.frames = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        h = cf.FRAME_HEADER_BYTES
        while not self._stop.is_set():
            try:
                conn, _addr = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(0.05)
                buf = b""
                while not self._stop.is_set():
                    try:
                        data = conn.recv(cf.FRAME_TOTAL_BYTES - len(buf))
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not data:
                        break
                    buf += data
                    if len(buf) < cf.FRAME_TOTAL_BYTES:
                        continue
                    frame, buf = buf, b""
                    self.frames.append(frame)
                    time.sleep(self.DELAY_S)
                    reply = bytearray(frame)
                    for i in range(h + cf.STAMP_SPAN[0], h + cf.STAMP_SPAN[1]):
                        reply[i] ^= 0xFF
                    try:
                        conn.sendall(bytes(reply))
                    except OSError:
                        break

    def close(self):
        self._stop.set()
        self._thread.join(SLACK_S)
        self.srv.close()


def test_a_claim_plan_offers_no_control_before_its_first_frames_outcome_so_a_slow_stamping_peer_gets_one_honest_frame(cs, tmp_path):
    peer = StampingPeer()
    out = tmp_path / "run"
    try:
        rc = cs.main(["--plan", "reasons", "--host", "127.0.0.1", "--port", str(peer.port), "--contract", str(PY_FIXTURE),
                      "--out", str(out)])
        time.sleep(2 * StampingPeer.DELAY_S)       # a frame sent on a reconnect after the run's last offer would be in by now
    finally:
        peer.close()
    _header, recs, summary, result = outputs(out)
    assert rc == 1 and not result["passed"], result
    assert [(r["seq"], r["outcome"]) for r in recs] == [(1, "lost")], recs
    assert [f.hex() for f in peer.frames] == [recs[0]["frame"]], "the peer got seq 1 alone, an honest frame"
    n = summary["counters"]
    assert (n["packed"], n["reply_invalid"], n["injected"]) == (1, 1, 0), n
    assert "invalid" in result["facts"]["stopped"], result["facts"]


# ============================================================ against the native ctl build on loopback

def _gcc():
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        twin_gate.missing("needs gcc on Linux: runs in WSL and in CI's tooling job")
    return gcc


def _compile(out, include_dirs):
    cmd = [_gcc(), *CTL_FLAGS, "-I", str(COMMON)]
    for d in include_dirs:
        cmd += ["-I", str(d)]
    cmd += ["-o", str(out), str(MONITOR_C), str(COMMON / "shm_map_posix.c"), str(COMMON / "ivshm_client.c")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, "monitor.c must compile clean:\n%s" % r.stderr
    return str(out)


@pytest.fixture(scope="module")
def native(tmp_path_factory, G):
    """monitor.c's ctl build against the generation's vss_ctl.h, in a scratch directory."""
    return _compile(tmp_path_factory.mktemp("ctl-native") / "monitor", [_gen()])


def _row1(G, steer_max):
    p = G.PROFILES[1]
    return "X(1u, %du, %r, %r, %r, %r, %r, %r)" % (p["l_mm"], p["v_max"], p["a_max"], p["jerk_max"], steer_max,
                                                  p["steer_rate_max"], p["lat_acc_max"])


@pytest.fixture(scope="module")
def variants(tmp_path_factory, G):
    """The ctl build against the generation's vss_ctl.h with one value changed (the digest is the UIDs': it serves).
    "dt_max": DT_MAX_MS above the interval injection's frame, which it then accepts; "steer_max": profile 1's steer_max
    one step under the lat-accel injection's delta (the largest binary32 not above 1.0 rad), which then gets 15, not 17,
    while the honest frames' delta stays far inside it."""
    made = {}

    def build(which):
        if which not in made:
            d = tmp_path_factory.mktemp("ctl-variant-" + which)
            text = (_gen() / "vss_ctl.h").read_text(encoding="ascii")
            if which == "dt_max":
                old, new = "#define VSS_CTL_DT_MAX_MS %du\n" % G.DT_MAX_MS, "#define VSS_CTL_DT_MAX_MS %du\n" % VARIANT_DT_MAX_MS
            else:
                assert G.PROFILES[1]["steer_max"] == 1.0
                old, new = _row1(G, 1.0), _row1(G, 0.99)
            assert text.count(old) == 1, old
            (d / "vss_ctl.h").write_text(text.replace(old, new), encoding="ascii")
            made[which] = _compile(d / "monitor", [d, _gen()])
        return made[which]

    return build


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Monitor:
    """One native monitor process serving one port in one mode, its stdout the console file ctlsynth reads. The console
    is opened for appending, so a test may write another process's line into it while the monitor runs, as the guest's
    other processes do on its serial console."""

    def __init__(self, binary, words, tmp):
        banner = "monitor: stamping replies on :%d:" if words == ["stamp"] else "monitor: service monitor listening on :%d "
        for attempt in range(5):
            self.port = _free_port()
            self.console = tmp / ("console-%d.txt" % attempt)
            self.err = tmp / ("stderr-%d.txt" % attempt)
            with open(self.console, "ab") as out, open(self.err, "wb") as err:
                self.proc = subprocess.Popen([binary, str(self.port)] + list(words), stdout=out, stderr=err)
            end = time.monotonic() + SLACK_S
            while time.monotonic() < end and self.proc.poll() is None and (banner % self.port) not in self.text():
                time.sleep(0.02)
            if (banner % self.port) in self.text():
                return
            self.stop()
            if b"bind(" not in self.err.read_bytes():
                raise AssertionError((self.text(), self.err.read_bytes()))
        raise AssertionError("no free port in five tries")

    def text(self):
        return self.console.read_bytes().decode("ascii", "replace")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=SLACK_S)


@pytest.fixture
def monitors(tmp_path):
    started = []

    def start(binary, words):
        d = tmp_path / ("mon-%d" % len(started))
        d.mkdir()
        mon = Monitor(binary, words, d)
        started.append(mon)
        return mon

    yield start
    for mon in started:
        mon.stop()


def synth(cs, plan, port, out, *extra, console=None):
    argv = ["--plan", plan, "--host", "127.0.0.1", "--port", str(port), "--contract", str(_gen() / "vss_ctl.py"),
            "--deadline-ms", str(SVC_MS), "--out", str(out)] + list(extra)
    if console is not None:
        argv += ["--console", str(console), "--check"]
    return cs.main(argv)


def outputs(out):
    lines = [json.loads(x) for x in (out / "replies.jsonl").read_text(encoding="utf-8").splitlines()]
    assert set(lines[0]) == {"header"} and set(lines[-1]) == {"summary"}
    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    return lines[0]["header"], lines[1:-1], lines[-1]["summary"], result


def by_seq(recs):
    return {r["seq"]: (r["outcome"], r["verdict"], r["reason"]) for r in recs}


OK = ("replied", 0, 0)


def _header_common(header, plan, G):
    assert header["format"] == 1 and header["kind"] == 2 and header["mode"] == "synth"
    assert header["digest"] == G.DIGEST and header["synth"]["plan"] == plan
    assert header["synth"]["period_ms"] == 30 and header["synth"]["deadline_ms"] == SVC_MS


def test_the_reasons_plan_gets_each_designed_reason_from_the_native_ctl_build_with_its_console_line(cs, G, native, monitors, tmp_path):
    mon = monitors(native, ["svc", str(SVC_MS)])
    out = tmp_path / "run"
    rc = synth(cs, "reasons", mon.port, out, console=mon.console)
    header, recs, summary, result = outputs(out)
    assert rc == 0 and result["passed"] and result["console_checked"], result
    _header_common(header, "reasons", G)
    assert header["injections"] == [{"seq": REASON_SEQ[r], "mode": m} for r, m in DESIGNED]
    want = {s: OK for s in range(1, REASONS_FRAMES + 1)}
    want.update({REASON_SEQ[r]: ("replied", 1, r) for r, _m in DESIGNED})
    assert by_seq(recs) == want
    assert summary["identity"]["holds"] and summary["counters"]["connects"] == 1
    lines = mon.text().splitlines()
    for r, m in DESIGNED:
        line = "monitor: REJECT seq=%d kind=ctl profile=%d reason=%s" % (REASON_SEQ[r], 0 if m == "profile0" else 1, NAMES[r])
        assert lines.count(line) == 1, line
    assert len([ln for ln in lines if ln.startswith("monitor: REJECT ")]) == len(DESIGNED)
    assert "monitor: client done: seen=25 accepted=13 rejected=12" in lines
    assert all(c["status"] == "PASS" for c in result["checks"]), result["checks"]


def test_the_silence_plan_gets_11_after_the_pause_and_the_console_shows_miss_then_restored(cs, G, native, monitors, tmp_path):
    mon = monitors(native, ["svc", str(SVC_MS)])
    out = tmp_path / "run"
    rc = synth(cs, "silence", mon.port, out, console=mon.console)
    header, recs, summary, result = outputs(out)
    assert rc == 0 and result["passed"], result
    _header_common(header, "silence", G)
    assert header["pause"] == {"after_seq": LEAD, "duration_ms": 2 * SVC_MS} and header["injections"] == []
    want = {s: OK for s in range(1, LEAD + TAIL + 1)}
    want[LEAD + 1] = ("replied", 1, 11)
    assert by_seq(recs) == want
    n = summary["counters"]
    assert (n["reconnects"], n["lost_on_reconnect"], n["drop"]) == (1, 0, 0) and n["controls_paused"] > 0
    lines = mon.text().splitlines()
    assert lines.count("monitor: client closed: no complete frame for %d ms" % SVC_MS) == 1
    miss = [i for i, ln in enumerate(lines) if ln.startswith("monitor: LIVENESS MISS: ") and " since seq=%d " % LEAD in ln]
    restored = [i for i, ln in enumerate(lines) if ln.startswith("monitor: LIVENESS RESTORED: seq=%d " % (LEAD + 1))]
    assert len(miss) == 1 and len(restored) == 1 and miss[0] < restored[0], lines
    assert "monitor: REJECT seq=%d kind=ctl profile=1 reason=ctl-interval" % (LEAD + 1) in lines


def test_the_late_plan_connects_after_its_wait_and_every_frame_is_accepted(cs, G, native, monitors, tmp_path):
    mon = monitors(native, ["svc", str(SVC_MS)])
    out = tmp_path / "run"
    rc = synth(cs, "late", mon.port, out, console=mon.console)
    header, recs, summary, result = outputs(out)
    assert rc == 0 and result["passed"], result
    _header_common(header, "late", G)
    assert header["synth"]["wait_ms"] == 2 * SVC_MS
    assert by_seq(recs) == {s: OK for s in range(1, LATE_FRAMES + 1)}
    assert recs[0]["mono_ns"] - header["synth"]["t0_ns"] >= 2 * SVC_MS * MS, "the first reply comes after the wait"
    n = summary["counters"]
    assert (n["connects"], n["connect_failures"], n["reconnects"]) == (1, 0, 0)
    lines = mon.text().splitlines()
    end = lines.index("monitor: client done: seen=5 accepted=5 rejected=0")
    # A fresh monitor: nothing before the session's end (the MISS after the run's last frame may follow it).
    assert not [ln for ln in lines[:end] if ln.startswith(("monitor: client closed:", "monitor: LIVENESS"))], lines


def test_the_flood_plan_gets_12_for_every_frame_of_profile_2s_window_and_one_console_line_with_summaries(cs, G, native, monitors,
                                                                                                          tmp_path):
    mon = monitors(native, ["svc", str(SVC_MS)])
    out = tmp_path / "run"
    rc = synth(cs, "flood", mon.port, out, "--flood-ms", "300", console=mon.console)
    header, recs, summary, result = outputs(out)
    assert rc == 0 and result["passed"], result
    _header_common(header, "flood", G)
    assert header["demo"] == {"profile": 2, "start_ms": LEAD * 30 - 15, "duration_ms": 300}
    profiles = [bytes.fromhex(r["frame"])[cf.FRAME_HEADER_BYTES + cf.P_PROFILE] for r in recs]
    window = [r["seq"] for r, p in zip(recs, profiles) if p == 2]
    assert len(window) >= 2 and window == list(range(window[0], window[-1] + 1)) and window[0] > 1
    assert len(recs) - window[-1] >= TAIL and set(profiles) == {1, 2}
    assert by_seq(recs) == {r["seq"]: ("replied", 1, 12) if p == 2 else OK for r, p in zip(recs, profiles)}
    lines = mon.text().splitlines()
    rejects = [ln for ln in lines if ln.startswith("monitor: REJECT ")]
    assert rejects == ["monitor: REJECT seq=%d kind=ctl profile=2 reason=ctl-speed" % window[0]]
    sums = [re.fullmatch(r"monitor: ctl summary: seen=\d+ rejected=\d+ suppressed=(\d+) by reason: 12=(\d+)", ln)
            for ln in lines if ln.startswith("monitor: ctl summary:")]
    assert sums and all(sums) and sum(int(m.group(2)) for m in sums if m) == len(window) - 1


def test_the_stamp_plan_sends_honest_frames_only_and_every_reply_carries_t_in_and_t_out(cs, G, native, monitors, tmp_path):
    mon = monitors(native, ["stamp"])
    out = tmp_path / "run"
    rc = synth(cs, "stamp", mon.port, out, console=mon.console)
    header, recs, summary, result = outputs(out)
    assert rc == 0 and result["passed"], result
    _header_common(header, "stamp", G)
    assert header["stamp"] is True and header["injections"] == [] and header["pause"] is None and header["demo"] is None
    assert by_seq(recs) == {s: OK for s in range(1, STAMP_FRAMES + 1)}
    assert all(0 < r["t_in_ns"] <= r["t_out_ns"] for r in recs), recs
    assert "monitor: client done: seen=5 accepted=5 rejected=0" in mon.text().splitlines()
    assert {c["name"]: c["status"] for c in result["checks"]}[cs.CHK_STAMP_REFUSED] == "PASS"


@pytest.mark.parametrize("which,reason,answered", [("dt_max", 11, (0, 0)), ("steer_max", 17, (1, 15))],
                         ids=["an accepted frame designed to get 11", "a frame designed to get 17 rejected with 15"])
def test_a_frame_answered_with_another_reason_than_its_designed_one_fails_the_plan_and_names_the_frame(cs, G, variants, monitors,
                                                                                                         tmp_path, which, reason,
                                                                                                         answered):
    mon = monitors(variants(which), ["svc", str(SVC_MS)])
    out = tmp_path / "run"
    rc = synth(cs, "reasons", mon.port, out)
    header, recs, summary, result = outputs(out)
    assert rc == 1 and not result["passed"] and not result["console_checked"]
    want = {s: OK for s in range(1, REASONS_FRAMES + 1)}
    want.update({REASON_SEQ[r]: ("replied", 1, r) for r, _m in DESIGNED})
    want[REASON_SEQ[reason]] = ("replied",) + answered
    assert by_seq(recs) == want, "the variant answers that one frame otherwise, every other as designed"
    failed = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert [c["name"] for c in failed] == [cs.CHK_DESIGNED]
    assert failed[0]["detail"] == "seq %d: designed reason %d, answered verdict %d reason %d" % ((REASON_SEQ[reason], reason) + answered)
    assert [c["status"] for c in result["checks"] if c["name"].startswith("console:")] == ["NOT CHECKED"] * 3


def test_the_variants_console_is_refused_before_anything_is_sent(cs, G, variants, monitors, tmp_path, capsys):
    mon = monitors(variants("dt_max"), ["svc", str(SVC_MS)])
    out = tmp_path / "run"
    rc = synth(cs, "reasons", mon.port, out, console=mon.console)
    assert rc == 2 and "dt_max" in capsys.readouterr().err and not out.exists()
    assert not [ln for ln in mon.text().splitlines() if ln.startswith("monitor: client")]


def test_the_stamp_plan_against_a_monitor_that_writes_no_stamps_fails(cs, G, native, monitors, tmp_path):
    mon = monitors(native, ["svc", str(SVC_MS)])
    out = tmp_path / "run"
    rc = synth(cs, "stamp", mon.port, out, console=mon.console)
    header, recs, summary, result = outputs(out)
    assert rc == 1 and by_seq(recs) == {s: OK for s in range(1, STAMP_FRAMES + 1)}
    assert [c["name"] for c in result["checks"] if c["status"] == "FAIL"] == [cs.CHK_STAMPS]


# ============================================================ several plans on one monitor and one console (spec-2 8.4's case)

LIVE_RE = re.compile(r"monitor: LIVENESS (MISS|RESTORED): .*?seq=(\d+)")


def _liveness(lines):
    return [(m.group(1), int(m.group(2))) for m in map(LIVE_RE.match, lines) if m]


def test_the_silence_plan_passes_on_a_port_that_served_the_reasons_plan_and_missed_its_deadline_since(cs, G, native, monitors,
                                                                                                       tmp_path):
    """8.4's order on the guest's one :7150 and one console: the reasons plan, a pause longer than the deadline, then the
    silence plan. The port's liveness is the process's, so its MISS for the reasons plan's last frame comes first and
    the silence plan's first frame restores it; the plan's own MISS and RESTORED follow."""
    mon = monitors(native, ["svc", str(SVC_MS)])
    assert synth(cs, "reasons", mon.port, tmp_path / "reasons", console=mon.console) == 0
    time.sleep(2 * SVC_MS / 1000)
    rc = synth(cs, "silence", mon.port, tmp_path / "silence", console=mon.console)
    _header, recs, _summary, result = outputs(tmp_path / "silence")
    assert rc == 0 and result["passed"], result
    lines = mon.text().splitlines()
    first_done = lines.index("monitor: client done: seen=25 accepted=13 rejected=12")
    assert _liveness(lines[first_done:])[:4] == [("MISS", REASONS_FRAMES), ("RESTORED", 1), ("MISS", LEAD), ("RESTORED", LEAD + 1)], lines
    silence = {c["name"]: c for c in result["checks"]}[cs.CON_SILENCE]
    assert silence["status"] == "PASS" and "monitor: LIVENESS RESTORED: seq=1 " in silence["detail"], silence


def test_the_late_plan_run_twice_at_once_on_one_monitor_passes_both_times(cs, G, native, monitors, tmp_path):
    """The first late session's MISS names its last seq, 5, one of the second session's own seqs, and falls due inside the
    second plan's wait: the second plan judges the console from the end of its wait, where its session begins."""
    mon = monitors(native, ["svc", str(SVC_MS)])
    assert synth(cs, "late", mon.port, tmp_path / "late-1", console=mon.console) == 0
    rc = synth(cs, "late", mon.port, tmp_path / "late-2", console=mon.console)
    _header, _recs, _summary, result = outputs(tmp_path / "late-2")
    assert rc == 0 and result["passed"], result
    lines = mon.text().splitlines()
    dones = [i for i, ln in enumerate(lines) if ln == "monitor: client done: seen=5 accepted=5 rejected=0"]
    assert len(dones) == 2, lines
    assert ("MISS", LATE_FRAMES) in _liveness(lines[dones[0]:dones[1]]), "the first session's MISS comes before the second's end"


def test_a_claim_plan_at_a_stamp_monitor_on_another_port_stops_at_the_first_reply_and_no_injection_reaches_it(cs, G, native, monitors,
                                                                                                                 tmp_path):
    """The image's :7161 is a stamp port ctlclient does not know (it knows :7151): the stamped reply is invalid to a plan
    that did not mark its target, and the plan stops there, so the stamp monitor judges one honest frame."""
    mon = monitors(native, ["stamp"])
    out = tmp_path / "run"
    rc = synth(cs, "reasons", mon.port, out)
    header, recs, summary, result = outputs(out)
    assert rc == 1 and not result["passed"] and header["stamp"] is False
    assert [(r["seq"], r["outcome"]) for r in recs] == [(1, "lost")], recs
    n = summary["counters"]
    assert (n["packed"], n["reply_invalid"], n["injected"], n["connects"]) == (1, 1, 0, 1), n
    end = time.monotonic() + SLACK_S
    while time.monotonic() < end and "monitor: client done:" not in mon.text():
        time.sleep(0.02)
    lines = mon.text().splitlines()
    assert "monitor: client done: seen=1 accepted=1 rejected=0" in lines and not [ln for ln in lines if " REJECT " in ln], lines
    replied = {c["name"]: c for c in result["checks"]}[cs.CHK_REPLIED]
    assert replied["status"] == "FAIL" and "invalid" in replied["detail"], replied


def test_a_ctl_rules_line_split_by_another_process_is_named_in_the_result_and_refuses_nothing(cs, G, native, monitors, tmp_path):
    mon = monitors(native, ["svc", str(SVC_MS)])
    rules = [ln for ln in mon.text().splitlines() if ln.startswith("monitor: ctl rules:")]
    assert len(rules) == 1, rules
    with open(mon.console, "ab") as f:
        f.write(("\n".join(_split_by_another_line(rules[0], 40)) + "\n").encode("ascii"))
    out = tmp_path / "run"
    rc = synth(cs, "late", mon.port, out, console=mon.console)
    _header, _recs, _summary, result = outputs(out)
    assert rc == 0 and result["passed"], result
    con_rules = {c["name"]: c for c in result["checks"]}[cs.CON_RULES]
    assert con_rules["status"] == "PASS" and rules[0][:40] in con_rules["detail"], con_rules
