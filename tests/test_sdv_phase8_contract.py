"""The Phase 8 contract test (the Phase 8 specification, section 8): WP1a, WP2 and WP3a held to each other on p8-early.

WP1a's kind 2 judge in monitor.c, WP2's claim side (sdv/ctl) and WP3a's ROS->VSS feeder (sdv/rosvss) were written apart,
each against section 2's interfaces and a fixture of its own. This file holds them to each other. What is tested, and
how:

- The two fixture contracts define the same values: tests/fixtures/ctl-c/vss_ctl.h (WP1a's) and
  tests/fixtures/ctl-py/vss_ctl.py (WP2's), every name of 2.4, the header read from its text and as monitor.c compiles it
  (tests/ctl_driver.c's constants and table), the module as ctlframe.load_contract loads it; the two bad-digest twins
  are each their fixture with the digest alone changed, both to one value.
- The two judges agree: over a seeded corpus of kind 2 frames (honest ones, each limit and threshold at its edge and one
  binary32 step beyond, each fault of rules 10, 8 and 9, and random mixtures of all three), ctl_driver's judge (the
  monitor's check_claim()) and ctlrules.judge give the same verdict and reason, frame by frame, and the corpus reaches
  every reason 0 and 8-19. Once on the fixtures, and once on a variant written here in both languages from one table:
  the fixtures give TOL17 and ROLLBACK_V one value, their limits are binary32 values and their ids are 1 and 2, so a
  judge that swapped those two constants, held a limit in binary32 or found a profile by its position would agree with
  the other on them; the variant's four constants are pairwise distinct, its limits off the binary32 grid (one steer_max
  is 2.3's largest, 1.0 rad) and its ids 3, 77 and 254 with an uncompiled 9.
- Every frame WP2 packs is a layout the monitor takes: ctlframe.encode's and pack_bits' frames and the core's
  (ctlclient, with Controls of every shape, non-finite and out-of-binary32 values and stale or absent odometry
  included) never get reason 10; and each injection check_config accepts gets its designed reason from the monitor,
  under profile 1, inside profile 2's window and under the variant's profile 3, where check_config refuses rolling-back
  (only undef and reserved give 10; kind9 gives 5).
- ctlclient's four connection cases against the native ctl build (WP1a's monitor.c with WP1a's fixture header) in
  `PORT svc 300`, the client's clock moved by hand and the monitor's real: the late connect (no connection before the
  first Control, and a first Control offered before the monitor listens), the intake pause (whose closed connection
  only the peer check before the send can see), the reconnect after the monitor closes an idle connection, and a frame
  in flight when the monitor goes away (stopped, then killed). In each, controls = packed = replied + drop +
  lost_on_reconnect, lost_on_reconnect is 0 but for the frame in flight, and the monitor's own counts and lines agree
  with the client's.
- Every message ctlclient.verdict_message builds (each outcome, a connection change, each injection, a non-finite
  value, the largest seq, and every message the four cases above published) is an update WP3a's update.py takes and
  mapping.py maps into the eleven CtlClaim and ten ControlCommand leaves of 2.8, with the frame's values and the
  counters, and within both run types' write sets. That holds while every counter is at most 2**32 - 1, the uint32 of
  CtlClaim's counter leaves: verdict_message passes the counters as they are, and update.py refuses a message with one
  past it (a run reaches that only after 2**32 packed frames).

Nothing here is a result: every value is a fixture's, the variant's (written here) or the specification's.

What this does NOT show: that the guest build judges kind 2 (qcc output cannot run here: WP5, WP7); anything about the
generated kind 2 contract (WP1b); that the monitor is in any control loop, or that it would catch Autoware's own faults
(the claim node packs the gate's output, after the gate has clamped it); anything about ROS, rclpy, kuksa-client or a
databroker (the feeder's mapping is driven with the update record alone); any timing (a wait below only bounds when an
event may come on a loaded host).

Needs gcc on Linux and the generated kind 4 contract in sdv-out/gen (sdv/vss/generate.py); without them a test skips,
and under SDV_REQUIRE_GEN=1 it fails instead (tests/twin_gate.py). The two tests of the fixtures' text, the test of item
5's bound and the one of the layout test's docstring need neither.
"""
import importlib
import json
import os
import random
import re
import runpy
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import twin_gate

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CTL_DIR = REPO / "sdv" / "ctl"
ROSVSS_DIR = REPO / "sdv" / "rosvss"
MONITOR_C = REPO / "ipc-test" / "qnx-safety-monitor" / "monitor.c"
COMMON = REPO / "ipc-test" / "common"
CTL_DRIVER_C = HERE / "ctl_driver.c"
GEN_FILES = ("vss_contract.h", "vss_profiles.h", "vss_contract.py")
C_FIXTURE = HERE / "fixtures" / "ctl-c" / "vss_ctl.h"
C_TWIN = HERE / "fixtures" / "ctl-c" / "bad-digest" / "vss_ctl.h"
PY_FIXTURE = HERE / "fixtures" / "ctl-py" / "vss_ctl.py"
PY_TWIN = HERE / "fixtures" / "ctl-py" / "vss_ctl_bad_digest.py"

# tests/test_monitor_vss.py's DEFAULT_FLAGS and the ctl build's additions, as tests/test_monitor_ctl.py writes them out.
DEFAULT_FLAGS = ("-O2", "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Wundef", "-Werror")
CTL_FLAGS = DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x14")

SVC_MS = 300                    # section 8: the four connection cases run against `PORT svc 300`
SLACK_S = 10.0                  # how long a wait may run on a loaded host before the test gives up
MS = 1_000_000
T0 = 10 ** 12

# 2.4's names, written out here.
C_NAMES = (("VSS_CTL_H", "VSS_CTL_FORMAT") + tuple("VSS_CTL_UID_SLOT%d" % i for i in range(7))
           + ("VSS_CTL_DIGEST", "VSS_CTL_DT_MAX_MS", "VSS_CTL_TOL17", "VSS_CTL_OVERSPEED_FACTOR", "VSS_CTL_OVERSPEED_MARGIN",
              "VSS_CTL_ROLLBACK_V", "VSS_CTL_PROFILE_TABLE", "VSS_CTL_PROFILE_COUNT", "VSS_CTL_PROFILE_IDS"))
PY_NAMES = ("FORMAT", "SLOT_PATHS", "SLOT_UIDS", "DIGEST", "DT_MAX_MS", "TOL17", "OVERSPEED_FACTOR", "OVERSPEED_MARGIN",
            "ROLLBACK_V", "PROFILES", "COMPILED_PROFILE_IDS")
CONSTANTS = ("TOL17", "OVERSPEED_FACTOR", "OVERSPEED_MARGIN", "ROLLBACK_V")
ROW_KEYS = ("l_mm", "v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max", "lat_acc_max")
SLOT_PATHS = ("Vehicle.DualVm.ControlCommand.Velocity", "Vehicle.DualVm.ControlCommand.Acceleration",
              "Vehicle.DualVm.ControlCommand.Jerk", "Vehicle.DualVm.ControlCommand.SteeringTireAngle",
              "Vehicle.DualVm.ControlCommand.SteeringTireRotationRate", "Vehicle.DualVm.Motion.LongitudinalVelocity",
              "Vehicle.DualVm.ControlCommand.StampInterval")

# 2.3's reasons and their names (the monitor's and ctlframe's), and 2.8's leaves, written out here.
REASONS = (0, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)
NAMES = {0: "ok", 5: "claim-kind-unknown", 8: "profile-unbound", 9: "field-not-finite", 10: "flags-invalid",
         11: "ctl-interval", 12: "ctl-speed", 13: "ctl-accel", 14: "ctl-jerk", 15: "ctl-steer", 16: "ctl-steer-rate",
         17: "ctl-lat-accel", 18: "ctl-overspeed", 19: "ctl-rolling-back"}
CC_ = "Vehicle.DualVm.ControlCommand."
CTL_ = "Vehicle.DualVm.Monitor.CtlClaim."
CONTROL_COMMAND = tuple(CC_ + x for x in ("Velocity", "Acceleration", "IsAccelerationDefined", "Jerk", "IsJerkDefined",
                                          "SteeringTireAngle", "SteeringTireRotationRate", "IsSteeringTireRotationRateDefined",
                                          "ProfileId", "StampInterval"))
CTL_CLAIM = tuple(CTL_ + x for x in ("Verdict", "Reason", "LastSeq", "Packed", "Replied", "Accepted", "Rejected", "Dropped",
                                     "LostOnReconnect", "Reconnects", "IsConnected"))
CHANGE_LEAVES = {CTL_ + x for x in ("IsConnected", "Reconnects", "Packed", "Replied", "Accepted", "Rejected", "Dropped",
                                    "LostOnReconnect")}
REPLY_LEAVES = {CTL_ + "Verdict", CTL_ + "Reason", CTL_ + "LastSeq"}
COUNTER_LEAVES = {"Packed": "packed", "Replied": "replied", "Accepted": "accepted", "Rejected": "rejected",
                  "Dropped": "dropped", "LostOnReconnect": "lost_on_reconnect", "Reconnects": "reconnects"}
U32_MAX = 2 ** 32 - 1           # CtlClaim's seven counter leaves are uint32 (sdv/vss/overlay.vspec): item 5's bound


# ============================================================ loading the packages

def _import(directory, name):
    """A module of sdv/ctl or sdv/rosvss, imported as its siblings import it (its directory on sys.path), no bytecode
    written, and checked to be that directory's (`update` and `mapping` are common names)."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        mod = importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved
    assert Path(mod.__file__).resolve().parent == directory, (name, mod.__file__)
    return mod


cf = _import(CTL_DIR, "ctlframe")
cc = _import(CTL_DIR, "ctlclient")
cr = _import(CTL_DIR, "ctlrules")
upd = _import(ROSVSS_DIR, "update")
mp = _import(ROSVSS_DIR, "mapping")


@pytest.fixture(scope="module")
def K():
    """WP2's fixture contract, through WP2's loader (2.4's rules hold)."""
    return cf.load_contract(PY_FIXTURE)


# ============================================================ the two contracts as values

def c_contract(path):
    """2.4's names of one vss_ctl.h, read from its text: {name: (parameters, value text)}, and the slot paths its
    comments give, in slot order."""
    text = path.read_text(encoding="ascii")
    joined = text.replace("\\\n", " ")
    defs = {}
    for m in re.finditer(r"^#define (\w+)(\(X\))?(?: +(.*?))?[ \t]*$", joined, re.M):
        assert m.group(1) not in defs, "%s: %s is defined twice" % (path, m.group(1))
        defs[m.group(1)] = (m.group(2), m.group(3) or "")
    slots = re.findall(r"^/\* slot (\d): (\S+)", text, re.M)
    assert [int(i) for i, _p in slots] == list(range(len(slots))), slots
    return defs, tuple(p for _i, p in slots)


def _c_uint(text, hexa=False):
    assert re.fullmatch(r"0x[0-9A-F]{8}u" if hexa else r"[0-9]+u", text), text
    return int(text[:-1], 16 if hexa else 10)


def _c_double(text):
    assert re.fullmatch(r"-?[0-9]+\.[0-9]+(?:e[-+]?[0-9]+)?", text), "%r is not a double literal" % text
    return float(text)


def c_values(path):
    """The header's values under the Python module's names (py_values' shape): ints for the u literals, floats for
    the doubles, the table's rows in table order as (id, l_mm, six doubles)."""
    defs, slots = c_contract(path)
    assert set(defs) == set(C_NAMES), sorted(set(defs) ^ set(C_NAMES))
    assert defs["VSS_CTL_H"] == (None, "")
    assert all(defs[n][0] is None for n in C_NAMES if n != "VSS_CTL_PROFILE_TABLE")
    params, table = defs["VSS_CTL_PROFILE_TABLE"]
    assert params == "(X)", params
    rows = []
    for body in re.findall(r"X\(([^)]*)\)", table):
        f = body.split(", ")
        assert len(f) == 8, body
        rows.append((_c_uint(f[0]), _c_uint(f[1])) + tuple(_c_double(x) for x in f[2:]))
    ids = re.fullmatch(r'"([0-9 ]*)"', defs["VSS_CTL_PROFILE_IDS"][1])
    assert ids is not None, defs["VSS_CTL_PROFILE_IDS"]
    out = {"FORMAT": _c_uint(defs["VSS_CTL_FORMAT"][1]), "SLOT_PATHS": slots,
           "SLOT_UIDS": tuple(_c_uint(defs["VSS_CTL_UID_SLOT%d" % i][1], hexa=True) for i in range(7)),
           "DIGEST": _c_uint(defs["VSS_CTL_DIGEST"][1], hexa=True), "DT_MAX_MS": _c_uint(defs["VSS_CTL_DT_MAX_MS"][1]),
           "ROWS": tuple(rows), "PROFILE_COUNT": _c_uint(defs["VSS_CTL_PROFILE_COUNT"][1]), "PROFILE_IDS": ids.group(1)}
    out.update({n: _c_double(defs["VSS_CTL_" + n][1]) for n in CONSTANTS})
    return out


def py_namespace(path):
    """A contract module's globals, executed by path as it stands (the bad-digest twin included, which the loader
    refuses), no bytecode written."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return runpy.run_path(str(path))
    finally:
        sys.dont_write_bytecode = saved


def py_values(ns):
    """A contract module's values under its own names; the compiled rows, in COMPILED_PROFILE_IDS order, are the
    header's table (the header lists compiled profiles only), their count and ids its count and ids."""
    public = {k for k in ns if not k.startswith("_")}
    assert public == set(PY_NAMES), sorted(public ^ set(PY_NAMES))
    ids = tuple(ns["COMPILED_PROFILE_IDS"])
    out = {"FORMAT": ns["FORMAT"], "SLOT_PATHS": tuple(ns["SLOT_PATHS"]), "SLOT_UIDS": tuple(ns["SLOT_UIDS"]),
           "DIGEST": ns["DIGEST"], "DT_MAX_MS": ns["DT_MAX_MS"],
           "ROWS": tuple((i,) + tuple(ns["PROFILES"][i][k] for k in ROW_KEYS) for i in ids),
           "PROFILE_COUNT": len(ids), "PROFILE_IDS": " ".join(str(i) for i in ids)}
    out.update({n: ns[n] for n in CONSTANTS})
    return out


def typed(x):
    """A value with the type of every number in it: 200 and 200.0 differ here, as 200u and 200.0 do in C."""
    if isinstance(x, tuple):
        return tuple(typed(v) for v in x)
    return (type(x).__name__, x)


def differences(a, b):
    return {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if typed(a.get(k)) != typed(b.get(k))}


# ============================================================ 1. the two fixtures define the same values

def test_the_two_fixture_contracts_define_the_same_value_for_every_name_of_2_4(K):
    c, p = c_values(C_FIXTURE), py_values(py_namespace(PY_FIXTURE))
    assert differences(c, p) == {}
    assert c["SLOT_PATHS"] == SLOT_PATHS and c["FORMAT"] == 1
    assert c["DIGEST"] == cf.digest_of(c["SLOT_UIDS"]), "the digest is the FNV-1 32 of the seven UIDs"
    assert tuple(r[0] for r in c["ROWS"]) == tuple(K.COMPILED_PROFILE_IDS), "the header lists the compiled profiles only"


def test_the_bad_digest_twins_are_their_fixtures_with_one_digest_and_the_same_one():
    c, ct = c_values(C_FIXTURE), c_values(C_TWIN)
    p, pt = py_values(py_namespace(PY_FIXTURE)), py_values(py_namespace(PY_TWIN))
    assert differences(c, ct) == {"DIGEST": (c["DIGEST"], ct["DIGEST"])}
    assert differences(p, pt) == {"DIGEST": (p["DIGEST"], pt["DIGEST"])}
    assert ct["DIGEST"] == pt["DIGEST"] != cf.digest_of(ct["SLOT_UIDS"])
    with pytest.raises(cf.ContractError, match="DIGEST"):
        cf.load_contract(PY_TWIN)


# ============================================================ the native builds

def _gcc():
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        twin_gate.missing("needs gcc on Linux: runs in WSL and in CI's tooling job")
    return gcc


def _gen():
    gen = twin_gate.gen_dir()
    absent = [n for n in GEN_FILES if not (gen / n).is_file()]
    if absent:
        twin_gate.missing("needs the generated kind 4 contract in %s (sdv/vss/generate.py): no %s" % (gen, ", ".join(absent)))
    return gen


def _build(out_dir, ctl_dir, names=("monitor", "driver")):
    """monitor.c (the ctl build) and tests/ctl_driver.c, against the vss_ctl.h in ctl_dir: the include order of
    tests/test_monitor_ctl.py, the fixture's directory before sdv-out/gen."""
    gcc, gen = _gcc(), _gen()
    out = {}
    for name, src in (("monitor", MONITOR_C), ("driver", CTL_DRIVER_C)):
        if name not in names:
            continue
        cmd = [gcc, *CTL_FLAGS, "-I", str(COMMON), "-I", str(ctl_dir), "-I", str(gen), "-o", str(out_dir / name), str(src),
               str(COMMON / "shm_map_posix.c"), str(COMMON / "ivshm_client.c")]
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, "%s must compile clean:\n%s" % (src.name, r.stderr)
        out[name] = str(out_dir / name)
    return out


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    """The native ctl build and its driver against WP1a's fixture header, in a scratch directory."""
    return _build(tmp_path_factory.mktemp("ctl"), C_FIXTURE.parent)


def _run(binary, mode, lines=()):
    r = subprocess.run([binary, mode], input="".join(x + "\n" for x in lines), capture_output=True, text=True, timeout=600)
    assert r.returncode == 0 and not r.stderr, (r.returncode, r.stderr[:2000])
    return r.stdout.splitlines()


def judge_c(builds, frames):
    """(verdict, reason, name) of each frame from the monitor's check_claim(), through ctl_driver judge."""
    out = _run(builds["driver"], "judge", [bytes(f).hex() for f in frames])
    assert len(out) == len(frames), (len(out), len(frames))
    res = []
    for ln in out:
        v, r, name = ln.split(" ", 2)
        res.append((int(v), int(r), name))
    return res


def compiled_view(builds):
    """What monitor.c compiles of a vss_ctl.h (ctl_driver constants and table), under py_values' names."""
    out = _run(builds["driver"], "constants")
    lines = dict(ln.split(" ", 1) for ln in out if not ln.startswith("profile "))
    table = _run(builds["driver"], "table")
    rows = [ln.split()[1:] for ln in table if ln.startswith("row ")]
    finds = {int(a): int(b) for _f, a, b in (ln.split() for ln in table if ln.startswith("find "))}
    ids, _count, count = lines["ids"].rpartition(" count ")
    v = {"FORMAT": int(lines["format"]), "SLOT_UIDS": tuple(int(x, 16) for x in lines["uids"].split()),
         "DIGEST": int(lines["digest"], 16), "DT_MAX_MS": int(lines["dt_max_ms"]),
         "ROWS": tuple((int(r[0]), int(r[1])) + tuple(float.fromhex(x) for x in r[2:]) for r in rows),
         "PROFILE_COUNT": int(count), "PROFILE_IDS": ids}
    v.update(zip(CONSTANTS, (float.fromhex(x) for x in lines["consts"].split())))
    return v, float.fromhex(lines["m_per_mm"]), finds


def test_the_fixture_header_as_monitor_c_compiles_it_is_the_python_modules_contract(native, K):
    v, m, finds = compiled_view(native)
    p = py_values(py_namespace(PY_FIXTURE))
    p.pop("SLOT_PATHS")
    assert differences(v, p) == {}
    assert m == cr.default_m_per_mm(), "the C build and ctlrules read one generation's M_PER_MM"
    ids = list(K.COMPILED_PROFILE_IDS)
    assert finds == {i: (ids.index(i) if i in ids else -1) for i in range(256)}
    sc = _run(native["driver"], "selfcheck")
    assert sc == ["computed %08X header %08X consistent 1" % (K.DIGEST, K.DIGEST)]


# ============================================================ frames

class Raw(int):
    """A slot's binary32 bits as they are: a NaN's payload, an infinity, -0.0."""


OPTIONAL = (("accel", cf.F_ACCEL, cf.P_ACCEL), ("jerk", cf.F_JERK, cf.P_JERK), ("rate", cf.F_RATE, cf.P_RATE),
            ("v_meas", cf.F_ODOM, cf.P_V_MEAS))
SLOT_OFF = {"v_cmd": cf.P_V_CMD, "accel": cf.P_ACCEL, "jerk": cf.P_JERK, "delta": cf.P_DELTA, "rate": cf.P_RATE,
            "v_meas": cf.P_V_MEAS}
LIMIT_OF = (("v_cmd", "v_max"), ("accel", "a_max"), ("jerk", "jerk_max"), ("delta", "steer_max"), ("rate", "steer_rate_max"))
NONFINITE = (0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001, 0xFFFFFFFF, 0xFFC00001)
NEG_ZERO = Raw(0x80000000)
F32_MAX = cf.bits_f32(0x7F7FFFFF)
H = cf.FRAME_HEADER_BYTES


def _bits(x):
    if isinstance(x, Raw):
        return int(x)
    b = cf.f32_bits(x)
    assert cf.bits_f32(b) == x, "%r is not a binary32 value: give one, or Raw bits" % (x,)
    return b


def frame(seq=1, profile=1, v_cmd=0.0, delta=0.0, accel=None, jerk=None, rate=None, v_meas=None, interval=0):
    """A kind 2 request packed by ctlframe.pack_bits: each optional value given sets its slot's flag."""
    kw = {"accel": accel, "jerk": jerk, "rate": rate, "v_meas": v_meas}
    flags = 0
    bits = {}
    for name, flag, _off in OPTIONAL:
        if kw[name] is not None:
            flags |= flag
            bits[name] = _bits(kw[name])
    return cf.pack_bits(seq=seq, tstamp_ns=0, flags=flags, profile=profile, v_cmd=_bits(v_cmd), delta=_bits(delta),
                        interval_ms=interval, **bits)


def patch(fr, off, data):
    """The frame with payload bytes from payload offset `off` overwritten."""
    b = bytearray(fr)
    b[H + off:H + off + len(data)] = data
    return bytes(b)


def fields(fr):
    """2.2's fields of a frame as packed, read here (not through ctlframe): seq, profile, interval, and each slot's
    binary32 bits, None when its flag is clear (v_cmd and delta are always there)."""
    f = fr[H + cf.P_FLAGS]
    out = {"seq": struct.unpack_from("<Q", fr, 0)[0], "profile": fr[H + 1], "interval_ms": struct.unpack_from("<H", fr, H + 45)[0]}
    for name, off, flag in (("v_cmd", 2, 0), ("accel", 25, 0x01), ("jerk", 29, 0x02), ("delta", 33, 0), ("rate", 37, 0x04),
                            ("v_meas", 41, 0x08)):
        out[name] = struct.unpack_from("<I", fr, H + off)[0] if flag == 0 or f & flag else None
    return out


def finite_bits(b):
    return b is not None and (b >> 23) & 0xFF != 0xFF


def f32_floor(x):
    """The largest binary32 at or below the double x >= 0 (x itself when x is a binary32 value)."""
    f = cf.f32(x)
    return cf.f32_next_down(f) if f > x else f


def up(x):
    return cf.f32_next_up(x)


def last_f32(holds):
    """The largest non-negative binary32 x with holds(x), holds being true at 0.0 and monotone."""
    assert holds(0.0)
    lo, hi = 0, 0x7F7FFFFF
    if holds(cf.bits_f32(hi)):
        return cf.bits_f32(hi)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if holds(cf.bits_f32(mid)):
            lo = mid
        else:
            hi = mid - 1
    return cf.bits_f32(lo)


def r17_edge(K, pr, ad, m):
    """The last binary32 v_meas at which rule 17 holds back for the angle ad under the row pr (ctlrules' arithmetic)."""
    return last_f32(lambda v: not cr.lat_accel(v, ad, pr["l_mm"], m) > pr["lat_acc_max"] + K.TOL17)


def edge_frames(K, m):
    """Each limit at its last binary32 and one step above in both signs, rule 17 at its edge for three angles in every
    sign, rules 18 and 19 at their thresholds, and the interval at 0, DT_MAX_MS, one above and 0xFFFF; every compiled
    profile."""
    out = []
    for pid in K.COMPILED_PROFILE_IDS:
        pr = K.PROFILES[pid]
        for slot, key in LIMIT_OF:
            e = f32_floor(pr[key])
            for s in (1.0, -1.0):
                out += [frame(profile=pid, **{slot: s * e}), frame(profile=pid, **{slot: s * up(e)})]
        for frac in (1.0, 0.5, 0.125):
            ad = f32_floor(pr["steer_max"] * frac)
            v = r17_edge(K, pr, ad, m)
            for ds, ms in ((1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0)):
                vc = ms * min(v, f32_floor(pr["v_max"]))
                out += [frame(profile=pid, v_cmd=vc, delta=ds * ad, v_meas=ms * v),
                        frame(profile=pid, v_cmd=vc, delta=ds * ad, v_meas=ms * up(v))]
        for vc in (0.0, 1.0, f32_floor(pr["v_max"])):
            e = f32_floor(K.OVERSPEED_FACTOR * vc + K.OVERSPEED_MARGIN)
            for cs, ms in ((1.0, 1.0), (-1.0, -1.0), (-1.0, 1.0), (1.0, -1.0)):
                out += [frame(profile=pid, v_cmd=cs * vc, v_meas=ms * e), frame(profile=pid, v_cmd=cs * vc, v_meas=ms * up(e))]
        e = f32_floor(K.ROLLBACK_V)
        for vc in (0.0, -0.0, 1.0, -1.0):
            out += [frame(profile=pid, v_cmd=vc, v_meas=-e), frame(profile=pid, v_cmd=vc, v_meas=-up(e))]
        for iv in (0, 1, 256, K.DT_MAX_MS, K.DT_MAX_MS + 1, 0xFFFF):
            out.append(frame(profile=pid, interval=iv))
    return out


def fault_frames(K):
    """Rule 10's faults (each reserved flag bit, each reserved byte, each undefined slot with bytes in it: a non-finite
    pattern, -0.0, one low bit), rule 9's (each non-finite pattern in each defined slot) and rule 8's (every id 0..255
    on an honest frame)."""
    out = []
    for b in range(4, 8):
        out += [patch(frame(), cf.P_FLAGS, bytes((1 << b,))),
                patch(frame(v_cmd=1.0, accel=0.5, jerk=0.5, rate=0.125, v_meas=1.0), cf.P_FLAGS, bytes((0x0F | 1 << b,)))]
    for i in list(range(8, 24)) + [cf.P_RESERVED]:
        out += [patch(frame(), i, b"\x01"), patch(frame(), i, b"\x80")]
    for _name, _flag, off in OPTIONAL:
        for pattern in NONFINITE + (0x80000000, 0x00000001, 0x3F800000):
            out.append(patch(frame(), off, struct.pack("<I", pattern)))
    for name in SLOT_OFF:
        for pattern in NONFINITE:
            out.append(frame(**{name: Raw(pattern)}))
    out += [frame(profile=i, v_cmd=1.0) for i in range(256)]
    return out


def random_frames(K, m, rng, n):
    """n frames drawn around the contract's edges and faults, several at once: a value at a limit or one binary32 above,
    at rule 17's, 18's or 19's edge, a non-finite pattern, -0.0, a random value; undefined slots, some with bytes in
    them; reserved bits and bytes; unbound and uncompiled profiles; intervals at DT_MAX_MS."""
    ids = list(K.COMPILED_PROFILE_IDS)
    others = [i for i in range(256) if i not in ids]
    out = []
    for _ in range(n):
        pid = rng.choice(ids * 3 + [0, rng.choice(others)])
        pr = K.PROFILES[pid] if pid in K.PROFILES else K.PROFILES[ids[0]]
        lim = {slot: pr[key] for slot, key in LIMIT_OF}
        kw = {}
        for slot in ("v_cmd", "accel", "jerk", "delta", "rate"):
            if slot not in ("v_cmd", "delta") and rng.random() < 0.35:
                continue
            r = rng.random()
            if r < 0.04:
                kw[slot] = Raw(rng.choice(NONFINITE))
            elif r < 0.07:
                kw[slot] = NEG_ZERO
            elif r < 0.4:
                e = f32_floor(lim[slot])
                kw[slot] = rng.choice((e, up(e))) * rng.choice((1.0, -1.0))
            else:
                kw[slot] = cf.f32(rng.uniform(-1.3 * lim[slot], 1.3 * lim[slot]))
        r = rng.random()
        vc = kw["v_cmd"] if not isinstance(kw["v_cmd"], Raw) else 1.0
        if r < 0.15:                                       # rule 17's edge for an angle of this row
            ad = f32_floor(pr["steer_max"] * rng.choice((1.0, 0.75, 0.5, 0.25)))
            kw["delta"] = ad * rng.choice((1.0, -1.0))
            e = r17_edge(K, pr, ad, m)
            kw["v_meas"] = rng.choice((e, up(e))) * rng.choice((1.0, -1.0))
        elif r < 0.3:                                      # rule 18's threshold for this v_cmd
            e = f32_floor(K.OVERSPEED_FACTOR * abs(vc) + K.OVERSPEED_MARGIN)
            kw["v_meas"] = rng.choice((e, up(e))) * rng.choice((1.0, -1.0))
        elif r < 0.45:                                     # rule 19's threshold
            e = f32_floor(K.ROLLBACK_V)
            kw["v_meas"] = -rng.choice((e, up(e)))
        elif r < 0.5:
            kw["v_meas"] = Raw(rng.choice(NONFINITE + (0x80000000,)))
        elif r < 0.8:
            kw["v_meas"] = cf.f32(rng.uniform(-30.0, 30.0))
        interval = rng.choice((0, 30, K.DT_MAX_MS, K.DT_MAX_MS + 1, 0xFFFF, rng.randrange(0x10000)))
        fr = frame(seq=len(out) + 1, profile=pid, interval=interval, **kw)
        r = rng.random()
        if r < 0.04:
            fr = patch(fr, cf.P_FLAGS, bytes((fr[H + cf.P_FLAGS] | 1 << rng.randrange(4, 8),)))
        elif r < 0.08:
            fr = patch(fr, rng.choice(list(range(8, 24)) + [cf.P_RESERVED]), bytes((rng.randrange(1, 256),)))
        elif r < 0.12:
            _name, flag, off = rng.choice(OPTIONAL)
            if not fr[H + cf.P_FLAGS] & flag:
                fr = patch(fr, off, struct.pack("<I", rng.choice(NONFINITE + (0x80000000, 1, 0x3F800000))))
        out.append(fr)
    return out


def honest_frames(K, rng, n):
    """n requests ctlframe.encode packs from finite values inside a compiled profile's limits: an odometry near the
    command, a stamp interval of about a control period, any of the optional flags."""
    ids = list(K.COMPILED_PROFILE_IDS)
    out = []
    for i in range(n):
        pid = rng.choice(ids)
        pr = K.PROFILES[pid]
        flags = rng.randrange(16)
        v = cf.f32(rng.uniform(-0.9, 0.9) * pr["v_max"])
        vals = {"accel": cf.f32(rng.uniform(-0.9, 0.9) * pr["a_max"]), "jerk": cf.f32(rng.uniform(-0.9, 0.9) * pr["jerk_max"]),
                "rate": cf.f32(rng.uniform(-0.9, 0.9) * pr["steer_rate_max"]), "v_meas": cf.f32(v * rng.uniform(0.9, 1.1))}
        out.append(cf.encode(seq=i + 1, tstamp_ns=0, flags=flags, profile=pid, v_cmd=v,
                             delta=cf.f32(rng.uniform(-0.2, 0.2) * pr["steer_max"]), interval_ms=rng.choice((0, 29, 30, 33)),
                             **{name: (vals[name] if flags & flag else None) for name, flag, _off in OPTIONAL}))
    return out


def corpus(K, m, seed, n=6000):
    rng = random.Random(seed)
    return {"honest": honest_frames(K, rng, 1000), "edge": edge_frames(K, m), "fault": fault_frames(K),
            "random": random_frames(K, m, rng, n)}


def compare_judges(builds, K, m, frames):
    """Every frame's verdict and reason from the monitor and from ctlrules; the reasons the monitor gave."""
    got = judge_c(builds, frames)
    bad = []
    for fr, (v, r, name) in zip(frames, got):
        ref = cr.judge(fr, K, m)
        if (v, r) != ref or name != NAMES[r] or name != cf.REASON_NAMES[r]:
            bad.append("%s: monitor %s, ctlrules %s" % (bytes(fr).hex(), (v, r, name), ref))
    assert not bad, "%d of %d frames judged otherwise:\n%s" % (len(bad), len(frames), "\n".join(bad[:8]))
    return [r for _v, r, _n in got]


# ============================================================ 2. the two judges agree

def test_the_monitor_and_ctlrules_judge_the_fixture_corpus_alike_reason_for_reason(native, K):
    m = cr.default_m_per_mm()
    parts = corpus(K, m, 20261018)
    seen = {}
    for name, frames in parts.items():
        seen[name] = set(compare_judges(native, K, m, frames))
    assert 0 in seen["honest"] and seen["fault"] >= {8, 9, 10} and seen["edge"] >= {0, 11, 12, 13, 14, 15, 16, 17, 18, 19}
    assert set().union(*seen.values()) == set(REASONS) and seen["random"] == set(REASONS), seen


# The variant: one table, written here as a header and as a module. Its four constants are pairwise distinct, its limits
# off the binary32 grid but one steer_max of exactly 1.0 rad, its ids neither contiguous nor from 1, profile 9 not
# compiled. Synthetic values, made up for this test.
VARIANT = {
    "FORMAT": 1,
    "SLOT_UIDS": (0x5EED2001, 0x5EED2002, 0x5EED2003, 0x5EED2004, 0x5EED2005, 0x5EED2006, 0x5EED2007),
    "DT_MAX_MS": 150,
    "TOL17": 0.35, "OVERSPEED_FACTOR": 1.15, "OVERSPEED_MARGIN": 0.85, "ROLLBACK_V": 0.55,
    "PROFILES": {
        3: {"l_mm": 2611, "v_max": 13.9, "a_max": 3.3, "jerk_max": 7.7, "steer_max": 0.61, "steer_rate_max": 0.33,
            "lat_acc_max": 1.7, "run_window_max_ms": None, "compiled": True},
        9: {"l_mm": 2611, "v_max": 13.9, "a_max": 3.3, "jerk_max": 7.7, "steer_max": 0.61, "steer_rate_max": 0.33,
            "lat_acc_max": 1.7, "run_window_max_ms": None, "compiled": False},
        77: {"l_mm": 3911, "v_max": 2.9, "a_max": 1.3, "jerk_max": 9.1, "steer_max": 0.47, "steer_rate_max": 0.21,
             "lat_acc_max": 1.1, "run_window_max_ms": 30000, "compiled": True},
        254: {"l_mm": 1503, "v_max": 40.1, "a_max": 9.7, "jerk_max": 55.3, "steer_max": 1.0, "steer_rate_max": 0.95,
              "lat_acc_max": 6.3, "run_window_max_ms": None, "compiled": True},
    },
}


def render_c(t):
    """A vss_ctl.h of the table t in 2.4's names."""
    ids = sorted(i for i, r in t["PROFILES"].items() if r["compiled"])
    lines = ["/* vss_ctl.h -- the Phase 8 contract test's variant, written at its run (synthetic values). */",
             "#ifndef VSS_CTL_H", "#define VSS_CTL_H", "", "#define VSS_CTL_FORMAT %du" % t["FORMAT"], ""]
    for i, (path, uid) in enumerate(zip(SLOT_PATHS, t["SLOT_UIDS"])):
        lines += ["/* slot %d: %s */" % (i, path), "#define VSS_CTL_UID_SLOT%d 0x%08Xu" % (i, uid)]
    lines += ["", "#define VSS_CTL_DIGEST 0x%08Xu" % cf.digest_of(t["SLOT_UIDS"]), "#define VSS_CTL_DT_MAX_MS %du" % t["DT_MAX_MS"]]
    lines += ["#define VSS_CTL_%s %r" % (n, float(t[n])) for n in CONSTANTS]
    rows = ["    X(%du, %du, %s)" % (i, t["PROFILES"][i]["l_mm"], ", ".join(repr(float(t["PROFILES"][i][k])) for k in ROW_KEYS[1:]))
            for i in ids]
    lines += ["", "#define VSS_CTL_PROFILE_TABLE(X) \\", " \\\n".join(rows), "",
              "#define VSS_CTL_PROFILE_COUNT %du" % len(ids), '#define VSS_CTL_PROFILE_IDS "%s"' % " ".join(map(str, ids)), "",
              "#endif /* VSS_CTL_H */", ""]
    return "\n".join(lines)


def render_py(t):
    """A vss_ctl.py of the table t in 2.4's names."""
    ids = tuple(sorted(i for i, r in t["PROFILES"].items() if r["compiled"]))
    return "".join(['"""vss_ctl.py -- the Phase 8 contract test\'s variant, written at its run (synthetic values)."""\n',
                    "FORMAT = %d\n" % t["FORMAT"], "SLOT_PATHS = %r\n" % (SLOT_PATHS,),
                    "SLOT_UIDS = (%s)\n" % ", ".join("0x%08X" % u for u in t["SLOT_UIDS"]),
                    "DIGEST = 0x%08X\n" % cf.digest_of(t["SLOT_UIDS"]), "DT_MAX_MS = %d\n" % t["DT_MAX_MS"]]
                   + ["%s = %r\n" % (n, float(t[n])) for n in CONSTANTS]
                   + ["PROFILES = %r\n" % (t["PROFILES"],), "COMPILED_PROFILE_IDS = %r\n" % (ids,)])


@pytest.fixture(scope="module")
def variant(tmp_path_factory):
    """The variant as a header (built into a driver) and as a module (through WP2's loader)."""
    d = tmp_path_factory.mktemp("variant")
    (d / "c").mkdir()
    (d / "c" / "vss_ctl.h").write_text(render_c(VARIANT), encoding="ascii")
    (d / "vss_ctl.py").write_text(render_py(VARIANT), encoding="ascii")
    return _build(d, d / "c", names=("driver",)), cf.load_contract(d / "vss_ctl.py"), d


def test_the_variant_is_one_contract_in_both_languages_and_tells_apart_what_the_fixtures_cannot(variant):
    builds, k, d = variant
    c, p = c_values(d / "c" / "vss_ctl.h"), py_values(py_namespace(d / "vss_ctl.py"))
    assert differences(c, p) == {}
    v, _m, finds = compiled_view(builds)
    p.pop("SLOT_PATHS")
    assert differences(v, p) == {}
    assert finds == {i: {3: 0, 77: 1, 254: 2}.get(i, -1) for i in range(256)}
    consts = [VARIANT[n] for n in CONSTANTS]
    assert len(set(consts)) == len(consts) and all(cf.f32(x) != x for x in consts)
    limits = [r[k] for r in VARIANT["PROFILES"].values() for k in ROW_KEYS[1:] if r["compiled"]]
    assert sum(cf.f32(x) == x for x in limits) == 1, "every limit off the binary32 grid but one steer_max of 1.0"
    assert {cf.f32(x) > x for x in limits if cf.f32(x) != x} == {True, False}, "limits that round up and limits that round down"


def test_the_monitor_and_ctlrules_judge_the_variant_corpus_alike_reason_for_reason(variant):
    builds, k, _d = variant
    m = cr.default_m_per_mm()
    parts = corpus(k, m, 20261019)
    seen = set()
    for frames in parts.values():
        seen |= set(compare_judges(builds, k, m, frames))
    assert seen == set(REASONS), seen


# ============================================================ 3. every frame WP2 packs is a layout the monitor takes

def _finite_value(rng):
    """A finite binary32 value: an ordinary one, a signed zero, a subnormal or the largest."""
    return rng.choice((cf.f32(rng.uniform(-60.0, 60.0)), cf.f32(rng.uniform(-60.0, 60.0)), 0.0, -0.0,
                       cf.bits_f32(1) * rng.choice((1, -1)), F32_MAX * rng.choice((1, -1))))


def _any_bits(rng):
    """Any binary32 bit pattern: a random one, a non-finite one, or a small finite value's."""
    r = rng.random()
    if r < 0.5:
        return rng.randrange(1 << 32)
    if r < 0.75:
        return rng.choice(NONFINITE + (0x80000000,))
    return cf.f32_bits(rng.uniform(-1.0, 1.0))


def test_every_frame_encode_and_pack_bits_make_is_a_layout_the_monitor_takes(native, K):
    rng = random.Random(7150)
    ids = list(K.COMPILED_PROFILE_IDS)
    frames = []
    for i in range(3000):
        flags = rng.randrange(16)
        vals = {name: (_finite_value(rng) if flags & flag else None) for name, flag, _off in OPTIONAL}
        frames.append(cf.encode(seq=i + 1, tstamp_ns=rng.randrange(1 << 64), flags=flags,
                                profile=rng.choice(ids + [rng.randrange(1, 256)]), v_cmd=_finite_value(rng),
                                delta=_finite_value(rng), interval_ms=rng.choice((0, 30, rng.randrange(0x10000))), **vals))
    for _i in range(3000):
        flags = rng.randrange(16)
        bits = {name: (_any_bits(rng) if flags & flag else None) for name, flag, _off in OPTIONAL}
        frames.append(cf.pack_bits(seq=rng.randrange(1, (1 << 64) - 1), tstamp_ns=rng.randrange(1 << 64), flags=flags,
                                   profile=rng.choice(ids + [rng.randrange(256)]), v_cmd=_any_bits(rng), delta=_any_bits(rng),
                                   interval_ms=rng.choice((0, 30, rng.randrange(0x10000))), **bits))
    got = judge_c(native, frames)
    assert [r for _v, r, _n in got].count(10) == 0, [f.hex() for f, g in zip(frames, got) if g[1] == 10][:5]
    assert all(cf.layout_errors(f) == [] for f in frames)
    assert {r for _v, r, _n in got[:3000]} >= {0, 8, 11, 12, 15} and {r for _v, r, _n in got[3000:]} >= {0, 8, 9}


class Clock:
    """The client's clock, moved by hand, in ns."""

    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, ms):
        self.t += int(ms * MS)


def control(t, v=2.0, d=0.1, a=None, j=None, r=None, odom=True, odom_age_ms=0, v_meas=None):
    """A Control stamped and received at t (a field None leaves its is_defined flag clear), and its odometry."""
    c = cc.Control(stamp_ns=t, recv_ns=t, velocity=v, acceleration=0.0 if a is None else a, is_defined_acceleration=a is not None,
                   jerk=0.0 if j is None else j, is_defined_jerk=j is not None, steering_tire_angle=d,
                   steering_tire_rotation_rate=0.0 if r is None else r, is_defined_steering_tire_rotation_rate=r is not None)
    o = cc.Odometry(v=v if v_meas is None else v_meas, recv_ns=t - odom_age_ms * MS) if odom else None
    return c, o


def packed_frames(cfg, K, controls):
    """The frames the core packs for these Controls (no socket: each offer queues its frame, replacing the last), and
    the messages its sink got."""
    clk, msgs = Clock(), []
    c = cc.CtlClient(cfg, K, clock=clk, sink=msgs.append)
    frames = []
    for ctl, odom in controls:
        clk.advance(30)
        if c.offer(ctl, odom) is not None:
            frames.append(c.queued.frame)
    s = c.stop(drain=False)
    assert s["identity"]["holds"] and s["counters"]["drop"] == len(frames), s
    return frames, msgs


ODD_VALUES = (2.0, -3.5, 0.0, -0.0, 1e39, -1e39, float("nan"), float("inf"), float("-inf"), 1e-50, 7.25)


def _odd_controls(rng, n, t0=T0):
    out = []
    for i in range(n):
        t = t0 + i * 30 * MS
        pick = [rng.choice(ODD_VALUES) for _ in range(6)]
        out.append(control(t, v=pick[0], d=pick[1], a=pick[2] if rng.random() < 0.5 else None,
                           j=pick[3] if rng.random() < 0.5 else None, r=pick[4] if rng.random() < 0.5 else None,
                           odom=rng.random() < 0.8, odom_age_ms=rng.choice((0, 50, 100, 101, 400, -5)), v_meas=pick[5]))
    return out


def test_every_frame_the_core_packs_is_a_layout_the_monitor_takes_and_only_injected_ones_get_10(native, K):
    """No injection here: that only undef and reserved get 10 is held by
    test_each_injection_check_config_accepts_gets_its_designed_reason_from_the_monitor."""
    rng = random.Random(7151)
    frames, _msgs = packed_frames(cc.Config(host="127.0.0.1", port=1), K, _odd_controls(rng, 2000))
    got = judge_c(native, frames)
    assert [r for _v, r, _n in got].count(10) == 0
    assert all(cf.layout_errors(f) == [] for f in frames)
    for fr, (_v, r, _n) in zip(frames, got):
        nonfinite = any(b is not None and not finite_bits(b) for name, b in fields(fr).items() if name in SLOT_OFF)
        assert (r == 9) == nonfinite, (fr.hex(), r)


def test_the_layout_tests_docstring_names_the_test_that_holds_the_second_clause_of_its_name():
    """The test above configures no injection, so its name's "only injected ones get 10" rests on the test its
    docstring names: that name must stay the one of a test of this file."""
    doc =test_every_frame_the_core_packs_is_a_layout_the_monitor_takes_and_only_injected_ones_get_10.__doc__ or ""
    named = re.findall(r"\btest_\w+", doc)
    assert named == ["test_each_injection_check_config_accepts_gets_its_designed_reason_from_the_monitor"], doc
    assert callable(globals().get(named[0]))


@pytest.mark.parametrize("demo", [False, True], ids=["profile 1", "profile 2 in its window"])
def test_each_injection_check_config_accepts_gets_its_designed_reason_from_the_monitor(native, K, demo):
    injections = tuple((i + 1, mode) for i, mode in enumerate(cc.INJECTIONS))
    cfg = cc.Config(host="127.0.0.1", port=1, injections=injections, demo=(0, 30000) if demo else None)
    assert cc.check_config(cfg, K) == []
    controls = [control(T0 + i * 30 * MS, v=2.0, d=0.1, a=0.5 if i % 2 else None, r=0.1 if i % 3 else None)
                for i in range(len(injections) + 2)]
    frames, _msgs = packed_frames(cfg, K, controls)
    got = judge_c(native, frames)
    want = [cc.INJECTION_REASONS[mode] for _s, mode in injections] + [0, 0]
    assert [r for _v, r, _n in got] == want, list(zip([m for _s, m in injections] + ["honest", "honest"], got))
    profile = 2 if demo else 1
    assert [fr[H + cf.P_PROFILE] for fr in frames] == [0 if mode == "profile0" else profile for _s, mode in injections] + [profile] * 2
    assert {mode for (_s, mode), (_v, r, _n) in zip(injections, got) if r == 10} == {"undef", "reserved"}


def test_each_injection_the_variant_leaves_a_frame_for_gets_its_designed_reason_from_the_monitor(variant):
    """Under the variant (profile 3: limits off the binary32 grid, an inexact L, distinct constants) every injection but
    rolling-back gets its reason from the variant's build; rolling-back packs |v_meas| ROLLBACK_V + 1 m/s, above its
    OVERSPEED_MARGIN, so for a small v_cmd rule 18 would come first and check_config refuses it."""
    builds, k, _d = variant
    modes = [mode for mode in cc.INJECTIONS if mode != "rolling-back"]
    refused = cc.check_config(cc.Config(host="127.0.0.1", port=1, profile=3, injections=((1, "rolling-back"),)), k)
    assert len(refused) == 1 and "OVERSPEED_MARGIN" in refused[0], refused
    injections = tuple((i + 1, mode) for i, mode in enumerate(modes))
    cfg = cc.Config(host="127.0.0.1", port=1, profile=3, injections=injections)
    assert cc.check_config(cfg, k) == []
    controls = [control(T0 + i * 30 * MS, v=2.0, d=0.1, a=0.5 if i % 2 else None, r=0.1 if i % 3 else None)
                for i in range(len(injections) + 2)]
    frames, _msgs = packed_frames(cfg, k, controls)
    got = judge_c(builds, frames)
    assert [r for _v, r, _n in got] == [cc.INJECTION_REASONS[m] for m in modes] + [0, 0], list(zip(modes + ["honest"] * 2, got))


# ============================================================ 5. every verdict message is an update the feeder maps

SPEC_LEAVES = set(CONTROL_COMMAND) | set(CTL_CLAIM)


def feed(text):
    """One verdict message through WP3a: parsed and checked as 2.6 (update.py), its update checked, mapped
    (mapping.py). Returns the 2.6 object and {path: value}."""
    obj = upd.parse_verdict(text)
    u = upd.check({"topic": upd.VERDICT, "recv_ns": 0, "stamp_ns": None, "fields": obj})
    items = mp.map_update(u)
    paths = [p for p, _v in items]
    assert len(paths) == len(set(paths)), paths
    assert set(paths) <= SPEC_LEAVES, sorted(set(paths) - SPEC_LEAVES)
    assert set(paths) <= mp.write_set("planning-sim") and set(paths) <= mp.write_set("carla-autoware")
    return obj, dict(items)


def check_message(text, frame=None, verdict=None, counters=None, connected=None):
    """feed() and what the leaves must carry: a connection change only IsConnected, Reconnects and the counters; a
    frame's message its command leaves as packed (a null never written, its Is...Defined false), and Verdict, Reason
    and LastSeq only when it was replied (2.8, the overlay's last reply received)."""
    obj, w = feed(text)
    assert all(w[CTL_ + leaf] == obj[key] for leaf, key in COUNTER_LEAVES.items())
    assert w[CTL_ + "IsConnected"] is obj["connected"]
    if counters is not None:
        assert [obj[k] for k in ("packed", "replied", "accepted", "rejected", "dropped", "lost_on_reconnect", "reconnects")] == [
            counters[k] for k in ("packed", "replied", "accepted", "rejected", "drop", "lost_on_reconnect", "reconnects")]
    if connected is not None:
        assert obj["connected"] is connected
    if obj["seq"] == 0:
        assert set(w) == CHANGE_LEAVES, sorted(w)
        return w
    if obj["verdict"] is None:
        assert not set(w) & REPLY_LEAVES
    else:
        assert (w[CTL_ + "Verdict"], w[CTL_ + "Reason"], w[CTL_ + "LastSeq"]) == (obj["verdict"], obj["reason"], obj["seq"])
    if frame is not None:
        f = fields(frame)
        assert obj["seq"] == f["seq"] and w[CC_ + "ProfileId"] == f["profile"] and w[CC_ + "StampInterval"] == f["interval_ms"]
        for leaf, defined, name in (("Velocity", None, "v_cmd"), ("Acceleration", "IsAccelerationDefined", "accel"),
                                    ("Jerk", "IsJerkDefined", "jerk"), ("SteeringTireAngle", None, "delta"),
                                    ("SteeringTireRotationRate", "IsSteeringTireRotationRateDefined", "rate")):
            b = f[name]
            finite = finite_bits(b)
            assert (CC_ + leaf in w) is finite, (leaf, b)
            if finite:
                assert w[CC_ + leaf] == struct.unpack("<f", struct.pack("<I", b))[0]
            if defined is not None:
                assert w[CC_ + defined] is finite
        if verdict is not None:
            assert (obj["verdict"], obj["reason"]) == verdict
    return w


def test_every_message_verdict_message_builds_is_an_update_the_feeder_takes_mapped_to_the_21_leaves(native, K):
    counters = {"packed": 9, "replied": 6, "accepted": 4, "rejected": 2, "drop": 2, "lost_on_reconnect": 1, "reconnects": 3}
    full = dict.fromkeys(counters, U32_MAX)
    injections = tuple((i + 1, mode) for i, mode in enumerate(cc.INJECTIONS))
    cfg = cc.Config(host="127.0.0.1", port=1, injections=injections)
    controls = [control(T0 + i * 30 * MS, v=2.0, d=0.1, a=0.5, j=1.0, r=0.1) for i in range(len(injections))]
    frames, sink_msgs = packed_frames(cfg, K, controls + _odd_controls(random.Random(9), 40, T0 + 10 ** 9))
    frames.append(frame(seq=(1 << 64) - 2, v_cmd=3.0, delta=-0.25, accel=-1.5, v_meas=3.0, interval=0xFFFF))
    frames.append(frame(seq=5, v_cmd=up(25.0), accel=up(5.0), jerk=80.0, rate=-1.0, v_meas=1.0, interval=33))
    got = judge_c(native, frames)
    union = set()
    for fr, (v, r, _n) in zip(frames, got):
        seq = struct.unpack_from("<Q", fr, 0)[0]
        for verdict, n in (((v, r), counters), (None, counters), (None, full)):
            for conn in (True, False):
                text = cc.verdict_message(seq=seq, frame=fr, verdict=None if verdict is None else verdict[0],
                                          reason=None if verdict is None else verdict[1], counters=n, connected=conn)
                union |= set(check_message(text, fr, verdict, n, conn))
    for conn in (True, False):
        for n in (counters, full, dict.fromkeys(counters, 0)):
            w = check_message(cc.verdict_message(seq=0, frame=None, verdict=None, reason=None, counters=n, connected=conn),
                              counters=n, connected=conn)
            union |= set(w)
    for text in sink_msgs:
        union |= set(check_message(text))
    assert union == SPEC_LEAVES, sorted(SPEC_LEAVES - union)
    assert set(mp.CTL_CLAIM) == set(CTL_CLAIM) and set(mp.CONTROL_COMMAND) == set(CONTROL_COMMAND)
    assert len(CTL_CLAIM) == 11 and len(CONTROL_COMMAND) == 10


def test_item_5_holds_while_every_counter_fits_ctlclaims_uint32_and_update_py_refuses_one_past_it():
    """Item 5 holds under a bound: CtlClaim's seven counter leaves are uint32 (the overlay), update.py refuses a counter
    above 2**32 - 1, and verdict_message passes the core's cumulative counters as they are. So a message is an update
    the feeder takes while every counter is at most U32_MAX, and one counter past it makes a message the feeder refuses
    (verdict-value: counted, never written). A run reaches the bound only after 2**32 packed frames."""
    vspec = (REPO / "sdv" / "vss" / "overlay.vspec").read_text(encoding="utf-8")
    datatypes = dict(re.findall(r"^%s(\w+):\n  type: sensor\n  datatype: (\w+)$" % re.escape(CTL_), vspec, re.M))
    assert {leaf: datatypes.get(leaf) for leaf in COUNTER_LEAVES} == dict.fromkeys(COUNTER_LEAVES, "uint32")
    assert upd.U32_MAX == U32_MAX
    fr = frame(seq=7, v_cmd=3.0, delta=-0.25, accel=-1.5, v_meas=3.0, interval=33)
    small = {"packed": 9, "replied": 6, "accepted": 4, "rejected": 2, "drop": 2, "lost_on_reconnect": 1, "reconnects": 3}
    for key in small:
        for value, taken in ((U32_MAX, True), (U32_MAX + 1, False)):
            n = dict(small, **{key: value})
            for seq, f, verdict in ((7, fr, (0, 0)), (7, fr, None), (0, None, None)):
                text = cc.verdict_message(seq=seq, frame=f, verdict=None if verdict is None else verdict[0],
                                          reason=None if verdict is None else verdict[1], counters=n, connected=True)
                if taken:
                    check_message(text, f, verdict, n, True)
                    continue
                name = "dropped" if key == "drop" else key
                with pytest.raises(upd.Refused, match=r"^verdict-value: %s is not an int in \[0, %d\]$" % (name, U32_MAX)):
                    upd.parse_verdict(text)


# ============================================================ 4. ctlclient against the native ctl build in svc 300

class Monitor:
    """The native ctl build in `PORT svc SVC_MS`, its stdout and stderr collected line by line."""

    def __init__(self, binary, port):
        self.port = port
        self.lines = []
        self.err = []
        self._cv = threading.Condition()
        self.proc = subprocess.Popen([binary, str(port), "svc", str(SVC_MS)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self._readers = [threading.Thread(target=self._read, args=(s, sink), daemon=True)
                         for s, sink in ((self.proc.stdout, self.lines), (self.proc.stderr, self.err))]
        for t in self._readers:
            t.start()
        self.up = self.wait_for("monitor: service monitor listening on :%d " % port)
        if not self.up:
            self.kill()

    def _read(self, stream, sink):
        for raw in iter(stream.readline, b""):
            with self._cv:
                sink.append(raw.decode("ascii", "replace").rstrip("\n"))
                self._cv.notify_all()

    def _count(self, prefix):
        return sum(1 for ln in self.lines if ln.startswith(prefix))

    def count(self, prefix):
        with self._cv:
            return self._count(prefix)

    def snapshot(self):
        with self._cv:
            return list(self.lines)

    def wait_for(self, prefix, n=1, timeout=SLACK_S):
        end = time.monotonic() + timeout
        with self._cv:
            while self._count(prefix) < n:
                left = end - time.monotonic()
                if left <= 0 or (self.proc.poll() is not None and not any(t.is_alive() for t in self._readers)):
                    return self._count(prefix) >= n
                self._cv.wait(min(left, 0.1))
            return True

    def signal(self, sig):
        os.kill(self.proc.pid, sig)

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=SLACK_S)
        for t in self._readers:
            t.join(SLACK_S)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def monitors(native, K):
    """start(port=None) starts the native ctl build in svc 300 (on a free port unless one is given) and checks its
    opening lines carry the fixture contract; every monitor still running at the end is killed."""
    started = []

    def start(port=None):
        for _attempt in range(3):
            mon = Monitor(native["monitor"], port or free_port())
            started.append(mon)
            if mon.up:
                break
            if port is not None:
                break
        assert mon.up, (mon.lines, mon.err)
        rules_line = [ln for ln in mon.snapshot() if ln.startswith("monitor: ctl rules: ")]
        assert len(rules_line) == 1 and rules_line[0].startswith(
            "monitor: ctl rules: kind 2, catalog 0x%08X (vss " % K.DIGEST), rules_line
        assert ", dt_max %d ms, " % K.DT_MAX_MS in rules_line[0]
        return mon

    yield start
    for mon in started:
        mon.kill()


def settle(c, cond, timeout=SLACK_S):
    """Let the client handle its socket (wait() pumps too) until cond() holds or the time runs out."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        c.wait(0.02)
    return cond()


def client(port, K, clk, msgs, tmp_path, **kw):
    return cc.CtlClient(cc.Config(host="127.0.0.1", port=port, **kw), K, clock=clk, sink=msgs.append,
                        reply_log=tmp_path / "replies.jsonl")


def offer(c, clk, step_ms=30, **kw):
    clk.advance(step_ms)
    return c.offer(*control(clk.t, **kw))


def offer_replied(c, clk, **kw):
    seq = offer(c, clk, **kw)
    assert seq is not None
    assert settle(c, lambda: c.n["replied"] + c.n["drop"] + c.n["lost_on_reconnect"] >= seq), c.n
    return seq


def closed_out(c):
    """Stop the client and hold the run to the identity: every counted Control packed one frame, and every packed
    frame is replied, dropped or lost, nothing left in flight."""
    s = c.stop(drain=True)
    n = c.n
    assert n["controls"] == n["packed"] == n["replied"] + n["drop"] + n["lost_on_reconnect"], n
    assert s["identity"]["holds"] and c.queued is None and c.outstanding is None and not c.connected
    return n


def reply_log(tmp_path):
    lines = [json.loads(x) for x in (tmp_path / "replies.jsonl").read_text(encoding="utf-8").splitlines()]
    assert set(lines[0]) == {"header"} and set(lines[-1]) == {"summary"}
    return {r["seq"]: (r["outcome"], r["verdict"], r["reason"]) for r in lines[1:-1]}


def monitor_seen(mon):
    """The claims the monitor counted over its finished sessions (its `client done:` lines)."""
    seen = [re.match(r"monitor: client done: seen=(\d+) accepted=(\d+) rejected=(\d+)$", ln) for ln in mon.snapshot()
            if ln.startswith("monitor: client done:")]
    assert all(seen), mon.snapshot()
    return [tuple(int(x) for x in m.groups()) for m in seen if m]


def test_late_connect_no_connection_before_the_first_control_then_it_is_replied(monitors, K, tmp_path):
    mon = monitors()
    clk, msgs = Clock(), []
    c = client(mon.port, K, clk, msgs, tmp_path)
    end = time.monotonic() + 1.5 * SVC_MS / 1000.0
    while time.monotonic() < end:
        c.wait(0.02)
    # A connection would have been closed at the monitor's 300 ms deadline, with its `client done:` line.
    assert c.n["connects"] == c.n["connect_failures"] == 0 and not c.connected
    assert not [ln for ln in mon.snapshot() if ln.startswith(("monitor: client", "monitor: LIVENESS"))], mon.snapshot()
    for _ in range(3):
        offer_replied(c, clk)
    n = closed_out(c)
    assert (n["controls"], n["replied"], n["accepted"], n["lost_on_reconnect"], n["drop"], n["connects"]) == (3, 3, 3, 0, 0, 1)
    assert mon.wait_for("monitor: client done:")
    assert monitor_seen(mon) == [(3, 3, 0)]
    assert reply_log(tmp_path) == {1: ("replied", 0, 0), 2: ("replied", 0, 0), 3: ("replied", 0, 0)}
    for text in msgs:
        check_message(text)
    assert [json.loads(t)["connected"] for t in msgs if json.loads(t)["seq"] == 0] == [True, False]


def test_late_connect_a_first_control_offered_before_the_monitor_listens_backs_off_then_is_replied(monitors, K, tmp_path):
    port = free_port()
    clk, msgs = Clock(), []
    c = client(port, K, clk, msgs, tmp_path)
    assert offer(c, clk) == 1
    c.pump()
    assert settle(c, lambda: c.n["connect_failures"] == 1), c.n
    assert c.next_connect_ns == clk.t + 100 * MS and c.queued is not None and c.queued.seq == 1
    mon = monitors(port)
    end = time.monotonic() + 0.3
    while time.monotonic() < end:                       # the monitor listens now, but the backoff runs on the client's clock
        c.wait(0.02)
    assert c.n["connect_failures"] == 1 and c.n["connects"] == 0
    clk.advance(100)
    assert settle(c, lambda: c.n["replied"] == 1), c.n
    n = closed_out(c)
    assert (n["controls"], n["replied"], n["lost_on_reconnect"], n["drop"], n["connects"]) == (1, 1, 0, 0, 1)
    assert mon.wait_for("monitor: client done:") and monitor_seen(mon) == [(1, 1, 0)]
    assert reply_log(tmp_path) == {1: ("replied", 0, 0)}
    for text in msgs:
        check_message(text)


def test_the_intake_pause_the_closed_connection_seen_by_the_peer_check_and_reason_11_after_it(monitors, K, tmp_path):
    mon = monitors()
    clk, msgs = Clock(), []
    c = client(mon.port, K, clk, msgs, tmp_path, pause=(3, 1000))
    for _ in range(3):
        offer_replied(c, clk)
    t3 = clk.t
    paused = [offer(c, clk) for _ in range(5)]
    assert paused == [None] * 5 and c.n["controls_paused"] == 5 and c.n["controls"] == 3
    # The client is not pumped during the pause: the monitor's close reaches it only through the peer check before the
    # next send (without that check the frame would go into the closed connection and be lost).
    assert mon.wait_for("monitor: client done: seen=3 accepted=3 rejected=0")
    assert mon.count("monitor: client closed: no complete frame for %d ms" % SVC_MS) == 1
    assert mon.wait_for("monitor: LIVENESS MISS:")
    time.sleep(0.2)
    assert c.connected and c.n["connects"] == 1
    clk.t = t3 + 1030 * MS                             # the first Control after the pause: its interval is over DT_MAX_MS
    checks, changes = c.n["peer_checks"], len(msgs)
    assert offer(c, clk, step_ms=0) == 4
    c.pump()                                            # pump() reads no socket but through the peer check
    assert c.n["peer_checks"] > checks and c.n["lost_on_reconnect"] == 0
    assert [json.loads(t)["connected"] for t in msgs[changes:] if json.loads(t)["seq"] == 0][:1] == [False]
    assert settle(c, lambda: c.n["replied"] == 4), c.n
    assert c.last_reply == (1, 11, 4) and c.n["reconnects"] == 1
    for _ in range(2):
        offer_replied(c, clk)
    n = closed_out(c)
    assert (n["controls"], n["replied"], n["rejected"], n["lost_on_reconnect"], n["drop"], n["controls_paused"]) == (6, 6, 1, 0, 0, 5)
    assert mon.wait_for("monitor: client done:", n=2) and mon.wait_for("monitor: LIVENESS RESTORED: seq=4 ")
    assert monitor_seen(mon) == [(3, 3, 0), (3, 2, 1)]
    assert "monitor: REJECT seq=4 kind=ctl profile=1 reason=ctl-interval" in mon.snapshot()
    log = reply_log(tmp_path)
    assert log[4] == ("replied", 1, 11) and [log[s][0] for s in sorted(log)] == ["replied"] * 6
    for text in msgs:
        check_message(text)


def test_the_reconnect_after_the_monitor_closes_an_idle_connection_is_lazy(monitors, K, tmp_path):
    mon = monitors()
    clk, msgs = Clock(), []
    c = client(mon.port, K, clk, msgs, tmp_path)
    for _ in range(3):
        offer_replied(c, clk)
    # The gate is silent: the client keeps handling its socket, sees the monitor close the idle connection, and makes no
    # new connection until the next Control (an eager one would have been closed at the deadline in its turn).
    end = time.monotonic() + SLACK_S
    while time.monotonic() < end and mon.count("monitor: client done:") < 1:
        c.wait(0.02)
    end = time.monotonic() + 1.5 * SVC_MS / 1000.0
    while time.monotonic() < end:
        c.wait(0.02)
    assert not c.connected and c.n["connects"] == 1 and c.n["connect_failures"] == 0
    assert mon.count("monitor: client closed: no complete frame for %d ms" % SVC_MS) == 1 and mon.count("monitor: client done:") == 1
    clk.advance(1500)
    assert offer_replied(c, clk) == 4
    assert c.last_reply == (1, 11, 4) and c.n["reconnects"] == 1
    for _ in range(2):
        offer_replied(c, clk)
    n = closed_out(c)
    assert (n["controls"], n["replied"], n["rejected"], n["lost_on_reconnect"], n["drop"], n["connects"]) == (6, 6, 1, 0, 0, 2)
    assert mon.wait_for("monitor: client done:", n=2) and monitor_seen(mon) == [(3, 3, 0), (3, 2, 1)]
    assert mon.count("monitor: LIVENESS MISS:") >= 1 and mon.count("monitor: LIVENESS RESTORED: seq=4 ") == 1
    for text in msgs:
        check_message(text)
    changes = [json.loads(t)["connected"] for t in msgs if json.loads(t)["seq"] == 0]
    assert changes == [True, False, True, False]


def test_a_frame_in_flight_when_the_monitor_goes_away_is_the_one_lost_on_reconnect(monitors, K, tmp_path):
    mon = monitors()
    clk, msgs = Clock(), []
    c = client(mon.port, K, clk, msgs, tmp_path)
    offer_replied(c, clk)
    mon.signal(signal.SIGSTOP)                          # the frame below reaches the socket and is never answered
    assert offer(c, clk) == 2
    c.pump()
    assert c.outstanding is not None and c.outstanding.seq == 2 and c.n["sends"] == 2
    time.sleep(0.1)
    assert c.n["replied"] == 1 and c.outstanding is not None
    mon.kill()                                          # the stopped monitor is killed: its connection closes
    assert settle(c, lambda: c.n["lost_on_reconnect"] == 1), c.n
    assert not c.connected and c.outstanding is None
    mon2 = monitors(mon.port)
    offer_replied(c, clk)
    n = closed_out(c)
    assert (n["controls"], n["replied"], n["drop"], n["lost_on_reconnect"], n["reconnects"]) == (3, 2, 0, 1, 1)
    assert mon2.wait_for("monitor: client done:") and monitor_seen(mon2) == [(1, 1, 0)]
    assert reply_log(tmp_path) == {1: ("replied", 0, 0), 2: ("lost", None, None), 3: ("replied", 0, 0)}
    lost = [json.loads(t) for t in msgs if json.loads(t)["seq"] == 2]
    assert len(lost) == 1 and lost[0]["verdict"] is None and lost[0]["lost_on_reconnect"] == 1 and lost[0]["connected"] is False
    for text in msgs:
        check_message(text)
