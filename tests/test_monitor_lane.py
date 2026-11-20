"""C2b S3: kind 6 (`lane`) in the monitor. The rules come from the project's local design notes, not in this tree.

Under MONITOR_EXT_KINDS & 0x40, built only with 0x10 (the lane builds 0x50, vss and lane, and 0x54, ctl and lane),
monitor.c judges kind 6: a lane found by a camera model (offset, heading, curvature, width, confidence) with the
vehicle's speed and yaw rate at the frame carried in the same 29 bytes, judged against the one profile table under the
kind 6 guard. Every kind 6 line of monitor.c stands in a block opened by the exact line
`#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x40)`. What is tested, and how:

- The switch (2.1): 0x50 and 0x54 compile clean under -Wformat=2 -Wundef -Werror with -ffp-contract=off, and under the
  -Wpedantic syntax check; 0x1C still stops as not implemented; every other value (0x40 and 0x5C among them) stops with
  the one #error line that names all five accepted values; only 0x54 depends on vss_ctl.h; no <math.h> and no libm.
- The rules (2.3), through tests/lane_driver.c's `judge` mode, which runs the monitor's own check_claim(), in both lane
  builds: each limit at and one binary32 step past it, in both signs (rule 29's curvature limit is no binary32, so its
  last binary32 below); rule 30 at its edge in several widths; rule 31 at its edge (found here by search over the speed's
  binary32 values) in several geometries and both signs, away from the line, on the centre, at V_MIN; each non-finite
  slot, each reserved bit and byte, each absent byte, -0.0 in an absent slot; every profile id; the order between
  adjacent rules and from every rule on; a seeded random corpus. Every expected verdict is also ref_judge()'s, a
  reference written here from 2.3, and sdv/lane/lanerules.py's (the Python judge the C judge is held to). The table's
  values off and on the binary32 grid: 2.4's curvature limit and VEH_HALF_W are no binary32 values, so the strictness
  of rules 29 (curvature), 30 and 31 and the lookup by id are judged on a variant table (two rows, ids 7 and 255, with
  limits that make exact ties), compiled from a copy of monitor.c with the table's row replaced, and judged by
  lanerules with the same table. The sin polynomial, through the driver's `sin` mode, bit for bit against lanerules';
  rule 31's predicate alone (`imminent`), with VEH clear.
- The table and the self-check (2.4, 2.5): the compiled table is laneframe's, row by row, and found by id; a copy of
  monitor.c whose row breaks an invariant refuses to serve (exit 2, `monitor: lane table inconsistent`, nothing on
  stdout) in every serving mode, after the vss self-check and the ctl one; a row id outside 1..255 does not compile.
- Kind 6 among the kinds: reason 5 in the default, vss and ctl builds; kinds 0, 1, 2, 4 and the unknown kinds get the
  vss build's verdicts in 0x50 and the ctl build's in 0x54, and their console lines over UDP.
- The console (2.5): the opening lines in every serving mode (the vss build's or the ctl build's, then the one `lane
  rules:` line, free of every harness word); the limiter's four rules at its cap, in `log` mode with a scripted clock,
  against limiter_model(); the kind 6 REJECT line, which the harnesses' regex reads, and a pending summary right before
  `udp done:` and `client done:`, end to end; a new bucket after a silence (the limiter has the monitor's clock); each
  lane flush hook right before the ctl hook of each of the seven session ends.
- The native build (2.7): build-monitor-native.sh builds 0x50 with kind 4's two headers hashed and 0x54 with vss_ctl.h
  too, names each build on its switch line, and refuses every other value.

Nothing here is a result: every number is 2.4's, the variant's or the specification's.

What this does NOT show: anything about the guest build (qcc output cannot run here, and 4.6(c) forbids taking the guest
binary apart); the guest's make target, image or ports (C2b LB: tests/test_make_ctl.py and tests/test_ifs_lane.py);
anything about a lane model, a camera or the claim's client; that rule 31's time-to-line is a good warning (its limits
are design values, not fitted); any timing.

Needs gcc on Linux (WSL Ubuntu-24.04 or CI's tooling job), readelf, and the generated kind 4 contract and vss_ctl.h in
sdv-out/gen (sdv/vss/generate.py). Without them a test skips, and under SDV_REQUIRE_GEN=1 it fails instead. The text
tests need none of them.
"""
import collections
import hashlib
import math
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

import monitor_corpus as mc
import test_monitor_vss as tmv

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MONITOR_C = REPO / "ipc-test" / "qnx-safety-monitor" / "monitor.c"
COMMON = REPO / "ipc-test" / "common"
SHM_MAP_POSIX_C = COMMON / "shm_map_posix.c"
IVSHM_CLIENT_C = COMMON / "ivshm_client.c"
LANE_DRIVER_C = HERE / "lane_driver.c"
CTL_DRIVER_C = HERE / "ctl_driver.c"
VSS_DRIVER_C = HERE / "vss_driver.c"
GEN = REPO / "sdv-out" / "gen"
GEN_HEADERS = ("vss_contract.h", "vss_profiles.h")
CTL_HEADER = "vss_ctl.h"
LANE_DIR = REPO / "sdv" / "lane"
NATIVE = REPO / "orin-native" / "gpu-concurrency" / "build-monitor-native.sh"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(LANE_DIR) not in sys.path:
    sys.path.insert(0, str(LANE_DIR))
import laneframe as lf  # noqa: E402
import lanerules as lr  # noqa: E402

sys.dont_write_bytecode = _saved

DEFAULT_FLAGS = ("-O2", "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Wundef", "-Werror")


def flags(value):
    return DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=" + value)


PEDANTIC_FLAGS = ("-fsyntax-only", "-std=gnu11", "-Wpedantic", "-Werror")
PLAIN_FLAGS = ("-O2", "-std=gnu99", "-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x50")
REQUIRE_ENV = "SDV_REQUIRE_GEN"

LANE_GUARD = "#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x40)"
CTL_GUARD = "#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)"
VSS_GUARD = "#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)"
# 2.1: the one #error line, its wording this package's.
SWITCH_ERROR = "MONITOR_EXT_KINDS must be 0x10 (vss), 0x14 (ctl), 0x1C (gap), 0x50 (vss and lane) or 0x54 (ctl and lane)"
GAP_ERROR = "MONITOR_EXT_KINDS 0x1C (gap): not implemented"
# 2.4's table, as monitor.c writes its one row: id, conf_min, width_min, width_max, k_max, h_max, veh_half_w, v_min,
# tlc_min.
TABLE_ROW = "X(1u, 50u, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, 1.0)"
P1 = (1, 50, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, 1.0)
Prof = collections.namedtuple("Prof", "id conf_min width_min width_max k_max h_max half v_min tlc")
TABLE = {1: Prof(*P1)}

# 2.5's lines, written out here, never read from monitor.c.
CLAIM_KINDS = "monitor: claim kinds: 0 mnist (us <= 100000), 1 vlm model 1 (us <= 1000000), conf_min=60%\n"
LANE_LINE = ("monitor: lane rules: profiles %s, kind 6%s\n")
LANE_PROFILE_PART = "; profile %u: conf_min %u, width %g..%g m, k_max %g 1/m, h_max %g rad, veh_half_w %g m, v_min %g m/s, tlc_min %g s"
REJECT_LINE = "monitor: REJECT seq=%d kind=lane profile=%d reason=%s"
SUMMARY_LINE = "monitor: lane summary: seen=%d rejected=%d suppressed=%d by reason:%s"
INCONSISTENT = b"monitor: lane table inconsistent\n"
VSS_INCONSISTENT = b"monitor: vss contract inconsistent\n"
CTL_INCONSISTENT = b"monitor: ctl contract inconsistent\n"
HARNESS_REGEX = re.compile(r"REJECT seq=(\d+) .*?reason=([a-z-]+)")
# tests/test_monitor_kind4_console.py's HARNESS_WORDS, written out here (spec 12: no announcement line may carry one).
HARNESS_WORDS = ("claim kinds:", "listening on", "serving shm", "stamping replies", "REJECT", "client done", "client closed",
                 "udp done", "shm quiet", "shm done", "shm-kick", "LIVENESS", "stopped")

CAP = 31                        # kind 6 REJECT lines per bucket (DESIGN: a 30 Hz camera's frames plus one)
S = 1_000_000_000
MS = 1_000_000
END = "E"

H = 16
NAMES = {0: "ok", 5: "claim-kind-unknown", 8: "profile-unbound", 9: "field-not-finite", 10: "flags-invalid",
         28: "lane-conf-low", 29: "lane-implausible", 30: "lane-departure", 31: "lane-departure-imminent"}
LANE_REASONS = {r: NAMES[r] for r in (28, 29, 30, 31)}
ORDER = (10, 9, 8, 28, 29, 30, 31)
QNAN = 0x7FC00000
NONFINITE = {"+inf": 0x7F800000, "-inf": 0xFF800000, "quiet NaN": QNAN, "signalling NaN": 0x7F800001,
             "negative NaN": 0xFFFFFFFF}
SLOTS = {"offset": (2, 0x01), "heading": (25, 0x01), "curvature": (29, 0x01), "width": (33, 0x01), "speed": (37, 0x02),
         "yaw": (41, 0x02)}


# --- skips, builds and drivers ----------------------------------------------------------------------------------------

def _missing(what):
    """An input is not there: skip, or fail under SDV_REQUIRE_GEN=1 (read strictly: 1, or off)."""
    value = os.environ.get(REQUIRE_ENV)
    if value == "1":
        pytest.fail("%s=1 and an input of the lane tests is missing: %s" % (REQUIRE_ENV, what), pytrace=False)
    if value not in (None, "", "0"):
        pytest.fail("%s is %r: it is 1, or unset (a mistyped switch must not read as off)" % (REQUIRE_ENV, value),
                    pytrace=False)
    pytest.skip(what)


def _gcc():
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        _missing("needs gcc on Linux: runs in WSL and in CI's tooling job")
    return gcc


def _need_gen(ctl=False):
    names = GEN_HEADERS + ((CTL_HEADER,) if ctl else ())
    if not all((GEN / h).is_file() for h in names):
        _missing("needs the generated contract in sdv-out/gen (sdv/vss/generate.py): %s" % ", ".join(names))


def _compile(gcc, flag_list, out, src, gen=GEN, link=True):
    cmd = [gcc, *flag_list, "-I", str(COMMON), "-I", str(gen)]
    if link:
        cmd += ["-o", str(out), str(src), str(SHM_MAP_POSIX_C), str(IVSHM_CLIENT_C)]
    else:
        cmd += ["-c", "-o", str(out), str(src)]
    return subprocess.run(cmd, capture_output=True, text=True)


def _build(out_dir, value, driver=LANE_DRIVER_C, monitor=MONITOR_C, gen=GEN, names=("monitor", "driver")):
    """monitor.c and a driver built with the flags of switch value `value`, against the headers in gen."""
    gcc = _gcc()
    _need_gen(ctl=value in ("0x14", "0x54"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, src in (("monitor", monitor), ("driver", driver)):
        if name not in names:
            continue
        r = _compile(gcc, flags(value), out_dir / name, src, gen=gen)
        assert r.returncode == 0, "%s must compile clean under %s:\n%s" % (src.name, " ".join(flags(value)), r.stderr)
        out[name] = str(out_dir / name)
    return out


@pytest.fixture(scope="module")
def lane50(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("lane50"), "0x50")


@pytest.fixture(scope="module")
def lane54(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("lane54"), "0x54")


@pytest.fixture(scope="module", params=["0x50", "0x54"])
def lane(request):
    """Each lane build in turn."""
    return request.getfixturevalue("lane50" if request.param == "0x50" else "lane54")


@pytest.fixture(scope="module")
def vss10(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("vss10"), "0x10", driver=VSS_DRIVER_C)


@pytest.fixture(scope="module")
def ctl14(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("ctl14"), "0x14", driver=CTL_DRIVER_C)


@pytest.fixture(scope="module")
def default_monitor(tmp_path_factory):
    out = tmp_path_factory.mktemp("default") / "monitor"
    r = subprocess.run(mc.gcc_command(_gcc(), str(REPO), str(out)), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


def _run(binary, mode, lines=()):
    r = subprocess.run([binary, mode], input="".join(x + "\n" for x in lines), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and not r.stderr, (r.returncode, r.stderr)
    return r.stdout.splitlines()


def judge(builds, frames):
    out = _run(builds["driver"], "judge", [bytes(f).hex() for f in frames])
    assert len(out) == len(frames), out
    res = []
    for ln in out:
        v, r, name = ln.split(" ", 2)
        res.append((int(v), int(r), name))
    return res


# --- a variant of monitor.c with another table ---------------------------------------------------------------------------

def table_text(rows):
    """The X-macro's rows as monitor.c writes them, for a copy of monitor.c."""
    def num(x):
        return repr(float(x))
    return " \\\n\t".join("X(%du, %du, %s)" % (r[0], r[1], ", ".join(num(x) for x in r[2:])) for r in rows)


def variant_tree(d, rows=None, row_text=None):
    """d/ipc-test/qnx-safety-monitor/monitor.c, monitor.c with the table's one row replaced, and d/tests/lane_driver.c,
    which includes it by its relative path."""
    text = MONITOR_C.read_text(encoding="ascii")
    assert text.count(TABLE_ROW) == 1, "the table's row is written once in monitor.c"
    new = row_text if row_text is not None else table_text(rows)
    mon = d / "ipc-test" / "qnx-safety-monitor" / "monitor.c"
    mon.parent.mkdir(parents=True)
    mon.write_text(text.replace(TABLE_ROW, new), encoding="ascii")
    drv = d / "tests" / "lane_driver.c"
    drv.parent.mkdir(parents=True)
    shutil.copy2(str(LANE_DRIVER_C), str(drv))
    return mon, drv


def build_variant(d, rows=None, value="0x50", row_text=None, gen=GEN, names=("monitor", "driver")):
    mon, drv = variant_tree(d / "src", rows, row_text)
    return _build(d / "bin", value, driver=drv, monitor=mon, gen=gen, names=names)


def py_table(rows):
    return {r[0]: lf.LaneProfile(*r) for r in rows}


def ref_table(rows):
    return {r[0]: Prof(*r) for r in rows}


# --- frames -----------------------------------------------------------------------------------------------------------

class Raw(int):
    """A slot's binary32 bits as they are: a NaN's payload, an infinity, -0.0."""


def F(x):
    """x rounded to binary32: a slot's value."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


def bits(x):
    if isinstance(x, Raw):
        return int(x)
    b = struct.unpack("<I", struct.pack("<f", x))[0]
    assert F(x) == x or math.isnan(x), "%r is not a binary32 value: give one (F), or Raw bits" % (x,)
    return b


def up(x):
    return lf.f32_next_up(x)


def down(x):
    return lf.f32_next_down(x)


def k6(seq=1, profile=1, lane=True, conf=90, offset=0.0, heading=0.0, curvature=0.0, width=3.5, speed=None, yaw=None,
       age=0, flags=None, kind=6, tstamp=0):
    """A kind 6 request laid out as 2.2, written here: LANE set with its five values when lane is true; VEH set when
    speed or yaw is given (the other 0.0); flags= overrides the byte."""
    p = bytearray(48)
    f = 0
    if lane:
        f |= 0x01
        p[1] = conf
        for off, v in ((2, offset), (25, heading), (29, curvature), (33, width)):
            p[off:off + 4] = struct.pack("<I", bits(v))
    if speed is not None or yaw is not None:
        f |= 0x02
        p[37:41] = struct.pack("<I", bits(0.0 if speed is None else speed))
        p[41:45] = struct.pack("<I", bits(0.0 if yaw is None else yaw))
    p[0] = f if flags is None else flags
    p[24] = kind
    p[45:47] = struct.pack("<H", age)
    p[47] = profile
    return struct.pack("<QQ", seq, tstamp) + bytes(p)


def setp(frame, off, data):
    b = bytearray(frame)
    b[H + off:H + off + len(data)] = data
    return bytes(b)


def poisoned(frame):
    return setp(frame, 6, b"\xee\xee")


def replied(frame, verdict, reason):
    return setp(frame, 6, bytes((verdict, reason)))


def ref_sin(x):
    """2.3's sin, written here: the odd Taylor polynomial to x^9 by Horner in x^2, highest power innermost."""
    c = [(-1) ** k / math.factorial(2 * k + 1) for k in range(5)]
    x2 = x * x
    s = c[4]
    for k in (3, 2, 1, 0):
        s = c[k] + x2 * s
    return x * s


def ref_room(w, pr):
    return w / 2 - pr.half


def ref_imminent(pr, f, off, h, room, sp):
    if not f & 0x02 or not sp > pr.v_min:
        return False
    vl = sp * ref_sin(h)
    toward = (off > 0 and vl > 0) or (off < 0 and vl < 0) or (off == 0 and vl != 0)
    return toward and room - abs(off) < pr.tlc * abs(vl)


def ref_judge(frame, table=None):
    """2.3, written here from the specification: (verdict, reason) of one kind 6 request. The order 10, 9, 8, the no-lane
    accept, 28, 29, 30, 31; every comparison strict; f32 widened to double."""
    t = TABLE if table is None else table
    p = bytes(frame[H:])
    assert len(p) == 48 and p[24] == 6
    f = p[0]

    def u32(off):
        return struct.unpack_from("<I", p, off)[0]

    def val(off):
        return struct.unpack_from("<f", p, off)[0]

    if f & 0xFC or any(p[8:24]) or (not f & 1 and (any(p[1:6]) or any(p[25:37]))) or (not f & 2 and any(p[37:45])):
        return 1, 10
    present = ([2, 25, 29, 33] if f & 1 else []) + ([37, 41] if f & 2 else [])
    if any((u32(o) >> 23) & 0xFF == 0xFF for o in present):
        return 1, 9
    pr = t.get(p[47])
    if pr is None:
        return 1, 8
    if not f & 1:
        return 0, 0
    if p[1] < pr.conf_min or p[1] > 100:
        return 1, 28
    off, h, k, w = val(2), val(25), val(29), val(33)
    if w < pr.width_min or w > pr.width_max or abs(k) > pr.k_max or abs(h) > pr.h_max:
        return 1, 29
    room = ref_room(w, pr)
    if abs(off) > room:
        return 1, 30
    if ref_imminent(pr, f, off, h, room, val(37)):
        return 1, 31
    return 0, 0


def expect(builds_list, cases, table=None, py_profiles=None):
    """cases: [(label, frame, reason)]. Each build's verdict, reason and name, ref_judge() and lanerules.judge must all be
    the case's."""
    frames = [x[1] for x in cases]
    bad = []
    for builds in builds_list:
        got = judge(builds, frames)
        for (label, fr, want), res in zip(cases, got):
            w = (0 if want == 0 else 1, want, NAMES[want])
            ref = ref_judge(fr, table)
            py = lr.judge(fr, py_profiles) if py_profiles is not None else lr.judge(fr)
            if res != w or ref != w[:2] or tuple(py) != w[:2]:
                bad.append("%s: build %s, ref_judge %s, lanerules %s, want %s" % (label, res, ref, py, w))
    assert not bad, "\n".join(bad[:20])


def r31_edge(pr, w, off, h):
    """The first binary32 speed above V_MIN at which rule 31 fires (ref's computation), and the one below it; the edge
    must lie above V_MIN, so the margin decides it there."""
    room = ref_room(w, pr)

    def fires(sp):
        return ref_imminent(pr, 0x03, off, h, room, sp)
    lo, hi = bits(up(F(pr.v_min))), 0x7F7FFFFF
    assert fires(struct.unpack("<f", struct.pack("<I", hi))[0])
    while lo < hi:
        mid = (lo + hi) // 2
        if fires(struct.unpack("<f", struct.pack("<I", mid))[0]):
            hi = mid
        else:
            lo = mid + 1
    edge = struct.unpack("<f", struct.pack("<I", lo))[0]
    assert down(edge) > pr.v_min and not fires(down(edge)) and fires(edge)
    return down(edge), edge


# ============================================================ the switch and the builds

def test_both_lane_builds_and_their_driver_compile_clean_under_the_tests_flags(lane50, lane54):
    for b in (lane50, lane54):
        assert os.path.isfile(b["monitor"]) and os.path.isfile(b["driver"])


@pytest.mark.parametrize("value", ["0x50", "0x54"])
def test_the_lane_units_hold_no_stray_semicolon(value):
    gcc = _gcc()
    _need_gen(ctl=value == "0x54")
    r = subprocess.run([gcc, *PEDANTIC_FLAGS, "-ffp-contract=off", "-DMONITOR_EXT_KINDS=" + value, "-I", str(COMMON),
                        "-I", str(GEN), str(MONITOR_C)], capture_output=True, text=True)
    assert r.returncode == 0, "the %s unit must be clean under -Wpedantic:\n%s" % (value, r.stderr)


@pytest.mark.parametrize("value", ["0x40", "0x44", "0x48", "0x4C", "0x58", "0x5C", "0x60", "0x70", "0xD0", "0x51",
                                   "0x150", None])
def test_every_value_but_the_five_stops_with_the_one_switch_error(value, tmp_path):
    # None is a bare -DMONITOR_EXT_KINDS, which gcc defines as 1. 0x40 alone would compile kind 6 without kind 4's
    # helpers; 0x5C would be gap and lane.
    define = "-DMONITOR_EXT_KINDS" if value is None else "-DMONITOR_EXT_KINDS=" + value
    r = _compile(_gcc(), DEFAULT_FLAGS + ("-ffp-contract=off", define), tmp_path / "unit.o", MONITOR_C, link=False)
    assert r.returncode != 0 and SWITCH_ERROR in r.stderr, r.stderr


def test_the_switch_error_is_one_line_naming_the_five_values():
    lines = MONITOR_C.read_text(encoding="ascii").replace("\\\n", " ").splitlines()   # logical lines
    errs = [ln for ln in lines if re.match(r"#\s*error", ln) and "must be" in ln]
    assert errs == ['#    error "%s"' % SWITCH_ERROR], errs
    checks = [ln for ln in lines if re.match(r"#\s*if", ln) and "MONITOR_EXT_KINDS !=" in ln]
    assert len(checks) == 1, checks
    assert re.findall(r"MONITOR_EXT_KINDS != (0x[0-9A-F]+)", checks[0]) == ["0x10", "0x14", "0x1C", "0x50", "0x54"], checks


def test_0x50_and_0x54_compile_and_0x1C_still_stops_as_not_implemented(tmp_path):
    gcc = _gcc()
    _need_gen(ctl=True)
    for value in ("0x50", "0x54"):
        r = _compile(gcc, flags(value), tmp_path / ("%s.o" % value), MONITOR_C, link=False)
        assert r.returncode == 0 and not r.stderr, (value, r.stderr)
    r = _compile(gcc, flags("0x1C"), tmp_path / "gap.o", MONITOR_C, link=False)
    assert r.returncode != 0 and GAP_ERROR in r.stderr and "must be 0x10" not in r.stderr, r.stderr


def test_only_the_0x54_lane_build_depends_on_vss_ctl_h():
    gcc = _gcc()
    _need_gen(ctl=True)
    for value, ctl_header in (("0x50", False), ("0x54", True)):
        cmd = [gcc, "-std=gnu99", "-DMONITOR_EXT_KINDS=" + value, "-I", str(COMMON), "-I", str(GEN), "-MM", str(MONITOR_C)]
        deps = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
        assert (CTL_HEADER in deps) is ctl_header, (value, deps)
        assert all(h in deps for h in GEN_HEADERS), (value, deps)


def test_no_math_h_and_no_libm_in_the_lane_builds(lane50, lane54):
    assert not re.search(r"#\s*include\s*<\s*math\.h\s*>", MONITOR_C.read_text(encoding="ascii"))
    readelf = shutil.which("readelf")
    if readelf is None:
        _missing("needs readelf (binutils)")
    for b in (lane50, lane54):
        dyn = subprocess.run([readelf, "-d", b["monitor"]], check=True, capture_output=True, text=True).stdout
        needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", dyn)
        assert needed and not [n for n in needed if n.startswith("libm.") or n.startswith("libm-")], needed
        syms = subprocess.run([readelf, "--dyn-syms", "-W", b["monitor"]], check=True, capture_output=True, text=True).stdout
        undefined = {ln.split()[-1].split("@")[0] for ln in syms.splitlines() if " UND " in ln and len(ln.split()) >= 8}
        assert not undefined & {"sin", "sinf", "cos", "tan", "fabs", "sqrt"}, sorted(undefined)


def _blocks(lines, guard):
    """[(first, last)] line indexes of each block opened by `guard` through its matching #endif."""
    out = []
    i = 0
    while i < len(lines):
        if lines[i] == guard:
            depth = 0
            for j in range(i, len(lines)):
                d = re.match(r"\s*#\s*([a-z]+)", lines[j])
                d = d.group(1) if d else None
                if d in ("if", "ifdef", "ifndef"):
                    depth += 1
                elif d == "endif":
                    depth -= 1
                    if depth == 0:
                        break
                elif d in ("else", "elif") and depth == 1:
                    raise AssertionError("line %d: an #%s at a kind 6 block's own level" % (j + 1, d))
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def test_every_kind_6_line_stands_in_a_block_opened_by_the_0x40_guard_alone():
    lines = MONITOR_C.read_text(encoding="ascii").split("\n")
    spelt = [i + 1 for i, ln in enumerate(lines) if "& 0x40" in ln and ln != LANE_GUARD]
    assert not spelt, "a 0x40 guard not spelt exactly as 2.1's line, at line(s) %s" % spelt
    assert not [ln for ln in lines if re.search(r"MONITOR_EXT_KINDS\s*&\s*0x(?!40\b|04\b|10\b)[0-9A-Fa-f]+", ln)], \
        "a guard combining bits"
    blocks = _blocks(lines, LANE_GUARD)
    assert len(blocks) >= 10, blocks
    inside = set()
    for a, b in blocks:
        inside |= set(range(a, b + 1))
    ident = re.compile(r"\b(lane_[a-z_]+|g_lane_log|LANE_[A-Z_]+|KIND_LANE|RSN_LANE_[A-Z_]+|P_LANE_[A-Z_]+|LF_[A-Z]+)\b")
    code = [(i, ln) for i, ln in enumerate(lines) if not ln.lstrip().startswith(("*", "/*", "//"))]
    stray = [(i + 1, ln) for i, ln in code if ident.search(ln.split("/*")[0]) and i not in inside]
    assert not stray, stray


# ============================================================ the table and the self-check (2.4, 2.5)

def _rows(builds):
    out = _run(builds["driver"], "table")
    rows = [ln.split()[1:] for ln in out if ln.startswith("row ")]
    rows = [(int(r[0]), int(r[1])) + tuple(float.fromhex(x) for x in r[2:]) for r in rows]
    finds = {int(a): int(b) for _, a, b in (ln.split() for ln in out if ln.startswith("find "))}
    return rows, finds


def test_the_compiled_table_is_2_4s_and_laneframes_and_found_by_id(lane):
    rows, finds = _rows(lane)
    assert rows == [P1]
    assert rows == [tuple(getattr(p, k) for k in lf.PROFILE_FIELDS) for p in lf.PROFILES.values()]
    assert finds == {i: (0 if i == 1 else -1) for i in range(256)}
    assert MONITOR_C.read_text(encoding="ascii").count(TABLE_ROW) == 1


def test_the_driver_constants(lane50, lane54):
    # sin_c is monitor.c's lane_sin_c itself, held to lanerules' SIN_COEFFS (which test_sdv_lane.py holds to the doubles
    # nearest (-1)^k / (2k+1)!): on |x| <= 0.5 a coefficient one ulp off moves lane_sin() far less than one ulp of its
    # result, so the sin test's outputs alone need not see it.
    for b, value in ((lane50, "0x50"), (lane54, "0x54")):
        lines = dict(ln.split(" ", 1) for ln in _run(b["driver"], "constants"))
        assert sorted(lines) == ["ext_kinds", "log_cap", "rows", "sin_c", "sin_domain"], lines
        assert (lines["ext_kinds"], lines["log_cap"], lines["rows"]) == (value, str(CAP), "1")
        assert float.fromhex(lines["sin_domain"]) == 0.5
        assert [float.fromhex(c) for c in lines["sin_c"].split()] == list(lr.SIN_COEFFS), lines["sin_c"]
    assert lf.SIN_DOMAIN == 0.5


def test_the_self_check_passes_on_the_compiled_table(lane):
    assert _run(lane["driver"], "selfcheck") == ["consistent 1"]


BAD_ROWS = {
    "conf_min 101": [(1, 101, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, 1.0)],
    "width_min at width_max": [(1, 50, 4.5, 4.5, 0.1, 0.5, 0.95, 1.0, 1.0)],
    "width_min 0": [(1, 50, 0.0, 4.5, 0.1, 0.5, 0.0, 1.0, 1.0)],
    "veh_half_w at width_min / 2": [(1, 50, 2.5, 4.5, 0.1, 0.5, 1.25, 1.0, 1.0)],
    "veh_half_w below 0": [(1, 50, 2.5, 4.5, 0.1, 0.5, -0.5, 1.0, 1.0)],
    "k_max 0": [(1, 50, 2.5, 4.5, 0.0, 0.5, 0.95, 1.0, 1.0)],
    "h_max over the sin domain": [(1, 50, 2.5, 4.5, 0.1, 0.5000000000000001, 0.95, 1.0, 1.0)],
    "h_max 0": [(1, 50, 2.5, 4.5, 0.1, 0.0, 0.95, 1.0, 1.0)],
    "v_min below 0": [(1, 50, 2.5, 4.5, 0.1, 0.5, 0.95, -1.0, 1.0)],
    "tlc_min 0": [(1, 50, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, 0.0)],
    "two rows with id 1": [P1, P1],
    "the second row bad": [P1, (2, 50, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, -1.0)],
}


@pytest.mark.parametrize("label", list(BAD_ROWS))
def test_a_table_breaking_an_invariant_refuses_to_serve(label, tmp_path):
    rows = BAD_ROWS[label]
    if label != "two rows with id 1":       # a dict cannot hold two rows with one id: lanerules' table never has them
        assert lf.table_errors(py_table(rows)), "the Python twin of the self-check refuses it too"
    b = build_variant(tmp_path, rows)
    assert _run(b["driver"], "selfcheck") == ["consistent 0"]
    assert _refusal(b["monitor"], ["<port>", "udp"], tmp_path) == (2, b"", INCONSISTENT)


# rows with a limit that is infinite or NaN: table_text's repr(float) cannot spell them, so they go in as row_text
NONFINITE_ROWS = {
    "width_max inf": "X(1u, 50u, 2.5, __builtin_inf(), 0.1, 0.5, 0.95, 1.0, 1.0)",
    "k_max inf": "X(1u, 50u, 2.5, 4.5, __builtin_inf(), 0.5, 0.95, 1.0, 1.0)",
    "v_min inf": "X(1u, 50u, 2.5, 4.5, 0.1, 0.5, 0.95, __builtin_inf(), 1.0)",
    "tlc_min inf": "X(1u, 50u, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, __builtin_inf())",
    "v_min NaN": "X(1u, 50u, 2.5, 4.5, 0.1, 0.5, 0.95, __builtin_nan(\"\"), 1.0)",
}


@pytest.mark.parametrize("label", list(NONFINITE_ROWS))
def test_a_table_with_an_infinite_or_nan_limit_refuses_to_serve(label, tmp_path):
    b = build_variant(tmp_path, row_text=NONFINITE_ROWS[label])
    assert _run(b["driver"], "selfcheck") == ["consistent 0"]
    assert _refusal(b["monitor"], ["<port>", "udp"], tmp_path) == (2, b"", INCONSISTENT)


def test_a_good_variant_passes_the_self_check_in_both_languages(tmp_path):
    rows = [(1, 50, 2.5, 4.5, 0.1, 0.5, 1.2499999999999998, 0.0, 1.0), (2, 100, 0.5, 1e3, 1e3, 0.5, 0.0, 1e3, 1e3)]
    assert lf.table_errors(py_table(rows)) == []
    b = build_variant(tmp_path, rows)
    assert _run(b["driver"], "selfcheck") == ["consistent 1"]


def _refusal(binary, words, tmp_path):
    argv = [binary]
    for w in words:
        if w == "<port>":
            argv.append(str(mc._free_port(socket.SOCK_STREAM)))
        elif w == "<slot>":
            (tmp_path / "slot").write_bytes(b"\0" * mc.SHM_FILE_BYTES)
            argv.append(str(tmp_path / "slot"))
        else:
            argv.append(w)
    r = subprocess.run(argv, capture_output=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


SERVING = [["<port>", "udp"], ["<port>"], ["<port>", "stamp"], ["<port>", "svc", "500"], ["shm", "<slot>"],
           ["shmkick", "<slot>@0", "/nonexistent-kick"]]


@pytest.fixture(scope="module")
def bad_table(tmp_path_factory):
    return build_variant(tmp_path_factory.mktemp("badtable"), BAD_ROWS["tlc_min 0"], names=("monitor",))["monitor"]


@pytest.mark.parametrize("words", SERVING, ids=["udp", "tcp", "stamp", "svc", "shm", "shmkick"])
def test_a_bad_table_refuses_to_serve_before_any_serving_line_in_every_mode(bad_table, words, tmp_path):
    words = [w.replace("<slot>@0", str(tmp_path / "slot") + "@0") for w in words]
    if any("@0" in w for w in words):
        (tmp_path / "slot").write_bytes(b"\0" * mc.SHM_FILE_BYTES)
    assert _refusal(bad_table, words, tmp_path) == (2, b"", INCONSISTENT)


def test_shmcfg_is_not_self_checked(bad_table, tmp_path):
    # As kind 4's and kind 2's: shmcfg serves nothing and exits before the claim kinds line.
    rc, out, err = _refusal(bad_table, ["shmcfg", str(tmp_path / "nonexistent")], tmp_path)
    assert INCONSISTENT not in err


def _gen_copy(tmp_path, ctl=False, flip_vss=False, flip_ctl=False):
    gen = tmp_path / "gen"
    gen.mkdir(parents=True)
    for h in GEN_HEADERS + ((CTL_HEADER,) if ctl else ()):
        shutil.copy2(str(GEN / h), str(gen / h))
    for flip, h, name in ((flip_vss, "vss_contract.h", "VSS_CATALOG_DIGEST"), (flip_ctl, CTL_HEADER, "VSS_CTL_DIGEST")):
        if flip:
            text = (gen / h).read_text(encoding="ascii")
            m = re.search(r"^#define %s 0x([0-9A-F]{8})u$" % name, text, re.M)
            assert m is not None, (h, name)
            (gen / h).write_text(text.replace(m.group(0), "#define %s 0x%08Xu" % (name, int(m.group(1), 16) ^ 1)),
                                 encoding="ascii")
    return gen


def test_the_lane_self_check_comes_after_the_vss_one_and_the_ctl_one(tmp_path):
    _need_gen(ctl=True)
    bad = BAD_ROWS["tlc_min 0"]
    g1 = _gen_copy(tmp_path / "a", flip_vss=True)
    m1 = build_variant(tmp_path / "a", bad, gen=g1, names=("monitor",))["monitor"]
    assert _refusal(m1, ["<port>", "udp"], tmp_path) == (2, b"", VSS_INCONSISTENT)
    g2 = _gen_copy(tmp_path / "b", ctl=True, flip_ctl=True)
    m2 = build_variant(tmp_path / "b", bad, value="0x54", gen=g2, names=("monitor",))["monitor"]
    assert _refusal(m2, ["<port>", "udp"], tmp_path) == (2, b"", CTL_INCONSISTENT)
    g3 = _gen_copy(tmp_path / "c", ctl=True)
    m3 = build_variant(tmp_path / "c", bad, value="0x54", gen=g3, names=("monitor",))["monitor"]
    assert _refusal(m3, ["<port>", "udp"], tmp_path) == (2, b"", INCONSISTENT)


@pytest.mark.parametrize("row", ["X(0u, 50u, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, 1.0)", "X(256u, 50u, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, 1.0)"])
def test_a_row_id_outside_1_to_255_does_not_compile_with_or_without_werror(row, tmp_path):
    _need_gen()
    mon, _ = variant_tree(tmp_path / "src", row_text=row)
    for fl in (flags("0x50"), PLAIN_FLAGS):
        r = _compile(_gcc(), fl, tmp_path / "unit.o", mon, link=False)
        assert r.returncode != 0 and "a lane profile id is 1..255" in r.stderr, r.stderr


# ============================================================ the reasons

def test_the_lane_builds_reason_names(lane50, lane54, vss10, ctl14):
    for lane_b, base_b in ((lane50, vss10), (lane54, ctl14)):
        got = {int(r): n for r, n in (ln.split(" ", 2)[1:] for ln in _run(lane_b["driver"], "reasons"))}
        base = {int(r): n for r, n in (ln.split(" ", 2)[1:] for ln in _run(base_b["driver"], "reasons"))}
        assert got == {r: LANE_REASONS.get(r, base[r]) for r in range(256)}
        assert all(base[r] == "unknown" for r in LANE_REASONS), "no other build names a kind 6 reason"
        assert all(re.fullmatch(r"[a-z-]+", n) for n in LANE_REASONS.values())


# ============================================================ the rules (2.3)

def test_honest_frames_are_accepted(lane50, lane54):
    cases = [("a lane, no vehicle values", k6(), 0),
             ("a lane and vehicle values", k6(offset=F(0.2), heading=F(-0.01), curvature=F(0.004), speed=F(13.9), yaw=F(0.1)), 0),
             ("no lane", k6(lane=False), 0),
             ("no lane, vehicle values", k6(lane=False, speed=F(30.0), yaw=F(-1.0)), 0),
             ("no lane, any age", k6(lane=False, age=0xFFFF), 0),
             ("a lane at every limit", k6(conf=100, width=4.5, curvature=F(-0.09), heading=-0.5), 0),
             ("verdict and reason preset", poisoned(k6()), 0)]
    expect([lane50, lane54], cases)


def test_rule_28_confidence_at_its_bounds(lane50, lane54):
    cases = [("conf %d" % c, k6(conf=c), 0 if 50 <= c <= 100 else 28) for c in (0, 1, 49, 50, 51, 99, 100, 101, 200, 255)]
    expect([lane50, lane54], cases)


def test_rule_29_each_limit_at_and_one_binary32_step_past(lane50, lane54):
    k = F(0.1)
    assert k > 0.1
    cases = [("width 2.5", k6(width=2.5), 0), ("width one below 2.5", k6(width=down(2.5)), 29),
             ("width 4.5", k6(width=4.5), 0), ("width one above 4.5", k6(width=up(4.5)), 29)]
    for s in (1.0, -1.0):
        cases += [("curvature %r" % (s * down(k)), k6(curvature=s * down(k)), 0),
                  ("curvature %r" % (s * k), k6(curvature=s * k), 29),
                  ("heading %r" % (s * 0.5), k6(heading=s * 0.5), 0),
                  ("heading %r" % (s * up(0.5)), k6(heading=s * up(0.5)), 29)]
    cases += [("width 0", k6(width=0.0), 29), ("width -3.5", k6(width=-3.5), 29), ("width huge", k6(width=F(1e30)), 29)]
    expect([lane50, lane54], cases)


@pytest.mark.parametrize("w", [2.5, 3.0, 3.5, F(3.7), 4.5])
def test_rule_30_at_its_edge_in_both_signs(lane50, lane54, w):
    room = ref_room(w, TABLE[1])
    edge = F(room)
    edge = edge if edge <= room else down(edge)
    assert edge != room, "2.4's VEH_HALF_W is no binary32 value: the edge is never a tie"
    cases = []
    for s in (1.0, -1.0):
        cases += [("width %r offset %r" % (w, s * edge), k6(width=w, offset=s * edge), 0),
                  ("width %r offset %r" % (w, s * up(edge)), k6(width=w, offset=s * up(edge)), 30)]
    expect([lane50, lane54], cases)


# (width, |offset|, |heading|): each edge speed lies above V_MIN, so the margin decides it there
R31 = [(3.5, F(0.3), 0.25), (3.5, 0.75, F(0.01)), (4.5, 0.25, 0.5), (4.5, 1.0, F(0.05)), (3.0, F(0.1), F(0.3)),
       (F(3.7), F(0.2), F(0.49)), (3.5, 0.0, 0.5), (3.5, 0.5, 2.0 ** -20), (2.5, 0.0625, F(0.02)),
       (2.625, 0.125, F(0.07)), (2.75, 0.0, F(0.001)), (3.25, 0.25, F(0.15)), (3.75, 0.5, F(0.2)), (4.0, 0.25, F(0.35)),
       (4.25, 0.5, F(0.45)), (4.375, 0.5, 0.5), (3.125, 0.0625, F(0.05)), (3.875, 0.5, F(0.12)), (F(4.4), 0.5, F(0.3))]


@pytest.mark.parametrize("w,off,h", R31, ids=["w%g-off%g-h%g" % x for x in R31])
def test_rule_31_at_its_edge_toward_the_nearer_line_in_both_signs(lane50, lane54, w, off, h):
    pr = TABLE[1]
    cases = []
    for s in (1.0, -1.0):
        lo, hi = r31_edge(pr, w, s * off if off else off, s * h)
        o = s * off if off else (0.0 if s > 0 else -0.0)
        cases += [("speed %r" % lo, k6(width=w, offset=o, heading=s * h, speed=lo), 0),
                  ("speed %r" % hi, k6(width=w, offset=o, heading=s * h, speed=hi, yaw=F(-0.3)), 31)]
        if off:
            cases += [("away at the same speed", k6(width=w, offset=o, heading=-s * h, speed=hi), 0),
                      ("away much faster", k6(width=w, offset=o, heading=-s * h, speed=F(1e6)), 0)]
    expect([lane50, lane54], cases)


def test_rule_31_s_speed_bound_and_the_centre(lane50, lane54):
    cases = [("V_MIN exactly", k6(offset=0.75, heading=0.5, speed=1.0), 0),
             ("one step over V_MIN", k6(offset=0.75, heading=0.5, speed=up(1.0)), 31),
             ("reversing fast", k6(offset=0.75, heading=0.5, speed=-30.0), 0),
             ("standing", k6(offset=0.75, heading=0.5, speed=0.0), 0),
             ("-0.0 speed", k6(offset=0.75, heading=0.5, speed=-0.0), 0),
             ("on the centre, no heading", k6(offset=0.0, heading=0.0, speed=50.0), 0),
             ("on the centre, -0.0 heading", k6(offset=0.0, heading=-0.0, speed=50.0), 0),
             ("-0.0 offset, a heading", k6(offset=-0.0, heading=F(-0.3), speed=50.0), 31),
             ("no vehicle values", k6(offset=0.75, heading=0.5), 0)]
    expect([lane50, lane54], cases)


def test_the_sin_polynomial_bit_for_bit_against_lanerules_and_the_reference(lane50, lane54):
    rng = random.Random(6)
    xs = [i / 512.0 for i in range(-256, 257)] + [F(rng.uniform(-0.5, 0.5)) for _ in range(500)]
    xs += [0.5, -0.5, 2.0 ** -30, -0.0, 5e-324, 0.4999999999999999]
    for b in (lane50, lane54):
        got = [float.fromhex(x) for x in _run(b["driver"], "sin", [float.hex(x) for x in xs])]
        assert got == [lr.lane_sin(x) for x in xs] == [ref_sin(x) for x in xs]
    assert ref_sin(0.5) != 0.5 and abs(ref_sin(0.5) - math.sin(0.5)) < 2e-11


def test_rule_31_s_predicate_alone_with_veh_clear(lane50, lane54):
    room = ref_room(3.5, TABLE[1])
    lines, want = [], []
    for f in (0x00, 0x01, 0x02, 0x03):
        for off, h, sp in ((0.75, 0.1, 10.0), (-0.75, -0.1, 10.0), (0.75, -0.1, 10.0), (0.0, 0.3, 50.0), (0.75, 0.1, 1.0)):
            lines.append("1 %d %s %s %s %s" % (f, float.hex(off), float.hex(h), float.hex(room), float.hex(sp)))
            want.append(int(ref_imminent(TABLE[1], f, off, h, room, sp)))
            assert lr.imminent(lf.PROFILES[1], f, off, h, room, sp) is bool(want[-1])
    assert set(want[:10]) == {0} and 1 in want[15:], "VEH clear never fires; VEH set does"
    for b in (lane50, lane54):
        assert [int(x) for x in _run(b["driver"], "imminent", lines)] == want


@pytest.mark.parametrize("slot", list(SLOTS))
def test_an_infinity_or_a_nan_in_each_slot(lane50, lane54, slot):
    off, bit = SLOTS[slot]
    cases = []
    for name, v in NONFINITE.items():
        present = setp(k6(speed=1.0), off, struct.pack("<I", v))
        cases.append(("%s %s present" % (slot, name), present, 9))
        absent = setp(k6(lane=bit != 0x01, speed=1.0 if bit != 0x02 else None), off, struct.pack("<I", v))
        cases.append(("%s %s absent" % (slot, name), absent, 10))
    expect([lane50, lane54], cases)


def test_the_largest_finite_value_in_each_slot_is_judged_by_its_value_never_9(lane50, lane54):
    # Rule 9's boundary in C: exponent 0xFE is finite
    # (+-FLT_MAX, 2^127), so each slot carrying one is judged by the later rules; 0xFF is the infinities' and NaNs'.
    cases = []
    for slot, (off, _bit) in SLOTS.items():
        for v in (0x7F7FFFFF, 0xFF7FFFFF, 0x7F000000):
            fr = setp(k6(speed=2.0), off, struct.pack("<I", v))
            want = ref_judge(fr)[1]
            assert want != 9, (slot, v)
            cases.append(("%s %08X" % (slot, v), fr, want))
    expect([lane50, lane54], cases)


def test_a_kind_6_reject_line_reaches_stdout_while_its_client_is_still_connected(lane50):
    # stdout is a pipe here, so fully buffered: the line must be flushed when it is printed, as kind 2's is, and not
    # only by the session's done line.
    proc, port = mc._start_on_port(lane50["monitor"], [], socket.SOCK_STREAM, mc.BANNER["tcp"])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            s.sendall(k6(seq=5, conf=10))
            mc._recv_exact(s, 64)
            proc.wait_for(b"monitor: REJECT seq=5 kind=lane profile=1 reason=lane-conf-low")
        proc.wait_for(b"monitor: client done:")
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))


def test_each_reserved_bit_each_stamp_byte_and_each_absent_byte_is_reason_10(lane50, lane54):
    full = k6(speed=F(5.0), yaw=F(0.1), age=3)
    none = k6(lane=False)
    cases = [("flag b%d" % b, setp(full, 0, bytes([full[H] | (1 << b)])), 10) for b in range(2, 8)]
    cases += [("p[%d]" % i, setp(full, i, b"\x01"), 10) for i in range(8, 24)]
    cases += [("absent lane byte p[%d]" % i, setp(none, i, b"\x80"), 10) for i in list(range(1, 6)) + list(range(25, 37))]
    cases += [("absent vehicle byte p[%d]" % i, setp(k6(), i, b"\x01"), 10) for i in range(37, 45)]
    cases += [("-0.0 in the absent %s" % n, setp(k6(lane=n not in ("offset", "heading", "curvature", "width"),
                                                     speed=None if n in ("speed", "yaw") else 1.0), o, b"\x00\x00\x00\x80"), 10)
              for n, (o, _b) in SLOTS.items()]
    cases += [("the age, any value", setp(full, 45, b"\xff\xff"), 0),
              ("no lane, flags only VEH, age", setp(k6(lane=False, speed=2.0), 45, b"\x01\x00"), 0)]
    expect([lane50, lane54], cases)


def test_profile_0_and_every_id_but_1_are_reason_8(lane50, lane54):
    cases = [("profile %d" % i, k6(profile=i), 0 if i == 1 else 8) for i in range(256)]
    cases += [("profile %d, no lane" % i, k6(profile=i, lane=False), 0 if i == 1 else 8) for i in (0, 2, 255)]
    expect([lane50, lane54], cases)


def _failing_from(k):
    """A frame failing every rule from ORDER[k] on (each fault of its own), and its expected reason ORDER[k]."""
    fr = k6(conf=10, width=9.0, offset=F(5.0), heading=0.5, speed=50.0, profile=1)
    faults = {
        31: lambda f: f,
        30: lambda f: f,
        29: lambda f: f,
        28: lambda f: f,
        8: lambda f: setp(f, 47, b"\x00"),
        9: lambda f: setp(f, 33, struct.pack("<I", QNAN)),
        10: lambda f: setp(f, 0, bytes([f[H] | 0x40])),
    }
    out = fr
    for r in ORDER[k:]:
        out = faults[r](out)
    return out


def test_every_rule_from_k_on_failing_gives_k(lane50, lane54):
    cases = [("from %d on" % ORDER[k], _failing_from(k), ORDER[k]) for k in range(3)]
    cases += [("28 over 29-31", k6(conf=10, width=9.0, offset=F(5.0), heading=0.5, speed=50.0), 28),
              ("29 over 30-31", k6(width=9.0, offset=F(5.0), heading=0.5, speed=50.0), 29),
              ("29 by curvature over 30-31", k6(curvature=0.25, offset=F(5.0), heading=0.5, speed=50.0), 29),
              ("30 over 31", k6(offset=F(0.81), heading=0.5, speed=50.0), 30),
              ("9 on yaw over 8", setp(k6(profile=0, speed=1.0), 41, struct.pack("<I", QNAN)), 9),
              ("8 over the no-lane accept", k6(lane=False, profile=0), 8),
              ("9 over the no-lane accept", setp(k6(lane=False, speed=1.0), 37, struct.pack("<I", QNAN)), 9),
              ("10 over 9 over 8", setp(setp(k6(profile=0), 2, struct.pack("<I", QNAN)), 0, b"\x81"), 10)]
    expect([lane50, lane54], cases)


def _random_k6(rng, n):
    out = []
    while len(out) < n:
        lane_on = rng.random() < 0.8
        veh = rng.random() < 0.7
        kw = dict(seq=len(out) + 1, lane=lane_on, profile=rng.choice((1, 1, 1, 1, 0, 2, 255)),
                  conf=rng.choice((rng.randrange(256), rng.randrange(50, 101), rng.randrange(50, 101))),
                  offset=F(rng.uniform(-1.6, 1.6)), heading=F(rng.uniform(-0.6, 0.6)), curvature=F(rng.uniform(-0.12, 0.12)),
                  width=F(rng.uniform(2.3, 4.7)), age=rng.randrange(0x10000))
        if veh:
            kw.update(speed=F(rng.uniform(-3.0, 40.0)), yaw=F(rng.uniform(-1.0, 1.0)))
        fr = k6(**kw)
        r = rng.random()
        if r < 0.04:
            fr = setp(fr, rng.choice((2, 25, 29, 33, 37, 41)), struct.pack("<I", rng.choice(list(NONFINITE.values()))))
        elif r < 0.08:
            fr = setp(fr, rng.choice((0, 1, 5, 8, 15, 23, 25, 30, 36, 37, 44)), bytes([rng.randrange(1, 256)]))
        elif r < 0.10:
            fr = setp(fr, rng.choice((2, 25, 37)), b"\x00\x00\x00\x80")
        out.append(fr)
    return out


def test_seeded_random_frames_match_the_reference_and_lanerules(lane50, lane54):
    frames = _random_k6(random.Random(6061), 5000)
    want = [ref_judge(f) for f in frames]
    assert [tuple(lr.judge(f)) for f in frames] == want
    for b in (lane50, lane54):
        got = [(v, r) for v, r, _n in judge(b, frames)]
        bad = [(i, g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w]
        assert not bad, bad[:5]
    seen = collections.Counter(r for _v, r in want)
    assert set(seen) == {0} | set(ORDER), "the corpus reaches every reason: %s" % sorted(seen.items())


# ============================================================ a table that makes ties (the strictness and the lookup)

TIE_ROWS = [(7, 40, 2.5, 4.5, 0.125, 0.5, 0.75, 1.0, 1.0), (255, 60, 2.0, 5.0, 0.0625, 0.25, 0.5, 2.0, 0.5)]


@pytest.fixture(scope="module")
def ties(tmp_path_factory):
    d = tmp_path_factory.mktemp("ties")
    return [build_variant(d / "50", TIE_ROWS, value="0x50"), build_variant(d / "54", TIE_ROWS, value="0x54")]


def test_the_tie_table_is_compiled_found_by_id_and_judged_alike(ties):
    for b in ties:
        rows, finds = _rows(b)
        assert rows == [tuple(r) for r in TIE_ROWS]
        assert finds == {i: {7: 0, 255: 1}.get(i, -1) for i in range(256)}
        assert _run(b["driver"], "selfcheck") == ["consistent 1"]
    t, py = ref_table(TIE_ROWS), py_table(TIE_ROWS)
    cases = [("profile 1 is not an id of the table", k6(profile=1), 8), ("profile 7", k6(profile=7), 0),
             ("profile 255", k6(profile=255, width=3.0), 0),
             ("profile 7's conf_min", k6(profile=7, conf=40), 0), ("profile 255's conf_min", k6(profile=255, conf=40), 28),
             ("profile 255's width_max", k6(profile=255, width=5.0), 0), ("profile 7's width_max", k6(profile=7, width=5.0), 29)]
    expect(ties, cases, t, py)


def test_ties_at_each_limit_are_accepted_and_one_step_past_rejected(ties):
    t, py = ref_table(TIE_ROWS), py_table(TIE_ROWS)
    cases = []
    for s in (1.0, -1.0):
        cases += [("curvature at k_max", k6(profile=7, curvature=s * 0.125), 0),
                  ("curvature past k_max", k6(profile=7, curvature=s * up(0.125)), 29),
                  ("heading at h_max (255)", k6(profile=255, width=3.0, heading=s * 0.25), 0),
                  ("heading past h_max (255)", k6(profile=255, width=3.0, heading=s * up(0.25)), 29),
                  # width 3.5 and VEH_HALF_W 0.75: room 1.0 exactly
                  ("offset at the room", k6(profile=7, offset=s * 1.0), 0),
                  ("offset past the room", k6(profile=7, offset=s * up(1.0)), 30)]
    # Rule 31 at an exact tie: sin(2^-30) is 2^-30 in double, so at 2^20 m/s |vl| is 2^-10 m/s, and with the offset
    # 1 - 2^-10 the margin is 2^-10 m: TLC_MIN (1.0) times |vl| exactly.
    h, sp, off = 2.0 ** -30, 2.0 ** 20, 1.0 - 2.0 ** -10
    assert ref_sin(h) == h and F(off) == off
    for s in (1.0, -1.0):
        cases += [("rule 31 at a tie", k6(profile=7, offset=s * off, heading=s * h, speed=sp), 0),
                  ("rule 31 one offset step past the tie", k6(profile=7, offset=s * up(off), heading=s * h, speed=sp), 31),
                  ("rule 31 one speed step past the tie", k6(profile=7, offset=s * off, heading=s * h, speed=up(sp)), 31)]
    # profile 255: TLC_MIN 0.5, width 3.0, VEH_HALF_W 0.5: room 1.0; |vl| 2^-10 makes 0.5 * 2^-10 = 2^-11 the margin
    off2 = 1.0 - 2.0 ** -11
    cases += [("rule 31 at TLC_MIN 0.5's tie", k6(profile=255, width=3.0, offset=off2, heading=h, speed=sp), 0),
              ("rule 31 past TLC_MIN 0.5's tie", k6(profile=255, width=3.0, offset=up(off2), heading=h, speed=sp), 31),
              ("V_MIN 2.0 exactly", k6(profile=255, width=3.0, offset=0.875, heading=0.25, speed=2.0), 0),
              ("one step over V_MIN 2.0", k6(profile=255, width=3.0, offset=0.875, heading=0.25, speed=up(2.0)), 31)]
    expect(ties, cases, t, py)


# ============================================================ kind 6 among the kinds

def test_kind_6_is_an_unknown_kind_in_the_vss_and_ctl_builds(vss10, ctl14):
    frames = [k6(), k6(lane=False), k6(conf=10), k6(profile=0), setp(k6(), 0, b"\xff")]
    for b in (vss10, ctl14):
        assert judge(b, frames) == [(1, 5, "claim-kind-unknown")] * len(frames)


def test_kind_6_is_an_unknown_kind_in_the_default_build_with_the_generic_line(default_monitor):
    replies, out = _udp_session(default_monitor, [k6(seq=61), k6(seq=62, conf=10)])
    assert [bytes.fromhex(r)[H + 6:H + 8] for r in replies] == [b"\x01\x05"] * 2
    assert "monitor: REJECT seq=61 kind=6 reason=claim-kind-unknown\n" in out
    assert "monitor: REJECT seq=62 kind=6 reason=claim-kind-unknown\n" in out


def _other_kinds(rng, n):
    """Frames of every other kind, structured enough to reach their rules: a zero p[6..23] and binary32 values."""
    out = []
    while len(out) < n:
        p = bytearray(48)
        kind = rng.choice((0, 1, 2, 2, 4, 4, 3, 5, 7, 9, 255))
        p[0] = rng.choice((0, 1, 3, 7, 15, 31, rng.randrange(256)))
        p[1] = rng.choice((0, 1, 2, 3, 60, 95, rng.randrange(256)))
        for off in (2, 25, 29, 33, 37, 41):
            p[off:off + 4] = struct.pack("<f", F(rng.choice((0.0, rng.uniform(-5, 5), rng.uniform(-60, 60)))))
        p[45:47] = struct.pack("<H", rng.choice((0, 10, 33, 600, 0xFFFF)))
        p[47] = rng.choice((0, 0, 1))
        p[24] = kind
        if rng.random() < 0.1:
            p[rng.randrange(8, 24)] = 1
        out.append(struct.pack("<QQ", len(out) + 1, 0) + bytes(p))
    out += [f for _l, f, _w in mc.corpus()]
    return out


def test_kinds_0_1_2_4_and_unknown_get_the_vss_and_ctl_builds_verdicts_in_the_lane_builds(lane50, lane54, vss10, ctl14):
    frames = _other_kinds(random.Random(4602), 3000)
    a, b = judge(lane50, frames), judge(vss10, frames)
    assert a == b
    c, d = judge(lane54, frames), judge(ctl14, frames)
    assert c == d
    reasons = {r for _v, r, _n in d}
    assert len(reasons) >= 12, sorted(reasons)


def _udp_session(binary, frames, pause=None):
    proc, port = mc._start_on_port(binary, ["udp"], socket.SOCK_DGRAM, mc.BANNER["udp"])
    try:
        items = [("frame %d" % i, f, None) for i, f in enumerate(frames)]
        if pause is None:
            replies = mc._drive_udp(port, items)
        else:
            replies = mc._drive_udp(port, items[:pause[0]])
            time.sleep(pause[1])
            replies += mc._drive_udp(port, items[pause[0]:])
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    return [r[1] for r in replies], mc._normalise_stdout(b"".join(proc.out), port=port)


def _from_banner(lines):
    starts = [i for i, ln in enumerate(lines) if ln.startswith(mc.BANNER["udp"].decode("ascii"))]
    assert len(starts) == 1, lines
    return lines[starts[0]:]


def test_kinds_0_and_1_and_the_unknown_kinds_reply_and_print_in_0x50_as_in_the_vss_build(lane50, vss10):
    frames = [f for _l, f, _w in mc.corpus()] + [mc.vlm(600 + k, kind=k) for k in (2, 3, 7, 255)]
    a_rep, a_out = _udp_session(lane50["monitor"], frames)
    b_rep, b_out = _udp_session(vss10["monitor"], frames)
    assert a_rep == b_rep and None not in a_rep
    assert _from_banner(a_out) == _from_banner(b_out)


# ============================================================ the console: the opening lines

def lane_announcement(rows=None):
    rows = [P1] if rows is None else rows
    parts = "".join(LANE_PROFILE_PART % tuple(r) for r in rows)
    return [LANE_LINE % (" ".join(str(r[0]) for r in rows), parts)]


def _opening(binary, mode, workdir):
    workdir.mkdir(parents=True, exist_ok=True)
    port, path = None, None
    if mode == "shm":
        path = str(workdir / "slot")
        with open(path, "wb") as fh:
            fh.write(b"\0" * mc.SHM_FILE_BYTES)
        proc = mc._Proc([binary, "shm", path])
        try:
            proc.wait_for(mc.BANNER["shm"])
        except BaseException:
            proc.kill()
            raise
    else:
        words = {"udp": ["udp"], "tcp": [], "stamp": ["stamp"], "svc": ["svc", "500"]}[mode]
        kind = socket.SOCK_DGRAM if mode == "udp" else socket.SOCK_STREAM
        proc, port = mc._start_on_port(binary, words, kind, mc.BANNER[mode])
    rc = proc.stop()
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    lines = mc._normalise_stdout(b"".join(proc.out), port=port, shm_path=path)
    ends = [i for i, ln in enumerate(lines) if ln.startswith(mc.BANNER[mode].decode("ascii"))]
    assert ends, lines
    return lines[:ends[0] + 1]


@pytest.mark.parametrize("mode", ["udp", "tcp", "stamp", "svc", "shm"])
def test_the_opening_lines_in_every_serving_mode(lane50, lane54, vss10, ctl14, mode, tmp_path):
    for lane_b, base_b, last in ((lane50, vss10, "monitor: vss profile "), (lane54, ctl14, "monitor: ctl profile ")):
        base = _opening(base_b["monitor"], mode, tmp_path / "base")
        got = _opening(lane_b["monitor"], mode, tmp_path / "lane")
        assert base[0] == CLAIM_KINDS
        k = max(i for i, ln in enumerate(base) if ln.startswith(last)) + 1
        assert got == base[:k] + lane_announcement() + base[k:]
        assert [ln for ln in got if "claim kinds:" in ln] == [CLAIM_KINDS]


def test_the_lane_announcement_holds_no_harness_word_and_no_banner_prefix():
    for ln in lane_announcement() + lane_announcement(TIE_ROWS):
        assert ln.startswith("monitor: lane rules: profiles ")
        assert not [w for w in HARNESS_WORDS if w in ln], ln
        assert not ln.startswith(tuple(b.decode() for b in mc.BANNER.values()))
        assert "vss rules:" not in ln and "ctl rules:" not in ln
    assert lane_announcement()[0].startswith("monitor: lane rules: profiles 1, kind 6")


def test_the_tie_tables_announcement_lists_its_rows(ties, tmp_path):
    got = _opening(ties[0]["monitor"], "udp", tmp_path)
    assert [ln for ln in got if ln.startswith("monitor: lane rules:")] == lane_announcement(TIE_ROWS)


# ============================================================ the limiter (2.5)

def ev(now, seq, reason, profile=1):
    return "F %d %d %d %d" % (now, seq, profile, reason)


def limiter_model(events, cap=CAP):
    """2.5's limiter, kind 2's four rules with kind 6's own state and cap, written from the specification and not from
    monitor.c."""
    out = []
    st = {}

    def fresh_bucket():
        st.update(lines=0, seen=0, rejected=0, suppressed=0, by=collections.Counter())

    def summary():
        if st["suppressed"]:
            by = "".join(" %d=%d" % (r, st["by"][r]) for r in sorted(st["by"]))
            out.append(SUMMARY_LINE % (st["seen"], st["rejected"], st["suppressed"], by))

    fresh_bucket()
    st.update(open=False, bucket=0, prev=0)
    for e in events:
        if e == END:
            summary()
            fresh_bucket()
            st.update(open=False, bucket=0, prev=0)
            continue
        now, seq, profile, reason = (int(x) for x in e.split()[1:])
        if not st["open"] or now // S != st["bucket"]:
            summary()
            fresh_bucket()
            st.update(open=True, bucket=now // S)
        st["seen"] += 1
        if reason:
            st["rejected"] += 1
            if reason != st["prev"] and st["lines"] < cap:
                st["lines"] += 1
                out.append(REJECT_LINE % (seq, profile, NAMES[reason]))
            else:
                st["suppressed"] += 1
                st["by"][reason] += 1
        st["prev"] = reason
    return out


def check_log(builds, events, want):
    assert limiter_model(events) == want, "the model and the specification's lines disagree"
    assert _run(builds["driver"], "log", events) == want


def test_one_reason_persisting_prints_one_line_and_its_buckets_summary(lane):
    events = [ev(i * 10 * MS, i + 1, 30) for i in range(100)] + [END]
    check_log(lane, events, [REJECT_LINE % (1, 1, "lane-departure"), SUMMARY_LINE % (100, 100, 99, " 30=99")])


def test_cap_alternating_rejects_in_a_bucket_all_print_and_one_more_goes_into_the_summary(lane):
    alt = [28 if i % 2 == 0 else 29 for i in range(CAP + 1)]
    lines = [REJECT_LINE % (i + 1, 1, NAMES[alt[i]]) for i in range(CAP)]
    check_log(lane, [ev(i * 30 * MS, i + 1, alt[i]) for i in range(CAP)] + [END], lines)
    check_log(lane, [ev(i * 30 * MS, i + 1, alt[i]) for i in range(CAP + 1)] + [END],
              lines + [SUMMARY_LINE % (CAP + 1, CAP + 1, 1, " %d=1" % alt[CAP])])


def test_rule_1_compares_with_the_previous_frame_and_an_accept_is_reason_0(lane):
    check_log(lane, [ev(0, 1, 31), ev(MS, 2, 0), ev(2 * MS, 3, 31), ev(3 * MS, 4, 31), END],
              [REJECT_LINE % (1, 1, "lane-departure-imminent"), REJECT_LINE % (3, 1, "lane-departure-imminent"),
               SUMMARY_LINE % (4, 3, 1, " 31=1")])


def test_the_limiter_at_its_cap_across_a_bucket_edge_compares_with_the_previous_frame(lane):
    alt = [28 if i % 2 == 0 else 29 for i in range(CAP + 1)]
    # The frame past the cap (index CAP, odd) is a 29; the next bucket's first 29 is then a repeat of the previous FRAME,
    # although the last line printed was a 28.
    events = ([ev(i * 30 * MS, i + 1, alt[i]) for i in range(CAP + 1)] + [ev(S + 10 * MS, CAP + 2, 29), ev(S + 20 * MS, CAP + 3, 28), END])
    want = ([REJECT_LINE % (i + 1, 1, NAMES[alt[i]]) for i in range(CAP)] + [SUMMARY_LINE % (CAP + 1, CAP + 1, 1, " 29=1")]
            + [REJECT_LINE % (CAP + 3, 1, "lane-conf-low"), SUMMARY_LINE % (2, 2, 1, " 29=1")])
    check_log(lane, events, want)


def test_the_session_end_flush_resets_rule_1_and_the_line_count(lane):
    alt = [28 if i % 2 == 0 else 29 for i in range(CAP)]
    events = [ev(i * 30 * MS, i + 1, alt[i]) for i in range(CAP)] + [END] + [ev(990 * MS, 40, alt[-1]), ev(991 * MS, 41, 8), END]
    want = [REJECT_LINE % (i + 1, 1, NAMES[alt[i]]) for i in range(CAP)] + [REJECT_LINE % (40, 1, NAMES[alt[-1]]),
                                                                           REJECT_LINE % (41, 1, "profile-unbound")]
    check_log(lane, events, want)
    check_log(lane, [END, END], [])


def test_a_summary_pending_at_a_bucket_edge_is_printed_once(lane):
    events = [ev(900 * MS, 1, 9), ev(950 * MS, 2, 9), ev(1100 * MS, 3, 9), ev(1150 * MS, 4, 9), END]
    check_log(lane, events, [REJECT_LINE % (1, 1, "field-not-finite"), SUMMARY_LINE % (2, 2, 1, " 9=1"),
                             SUMMARY_LINE % (2, 2, 2, " 9=2")])


def test_the_limiter_matches_the_model_on_seeded_streams(lane):
    rng = random.Random(6402)
    for _ in range(15):
        events, t, seq = [], rng.randrange(3 * S), 1
        for _ in range(rng.randrange(50, 600)):
            if rng.random() < 0.02:
                events.append(END)
                continue
            t += rng.choice((0, 1 * MS, 10 * MS, 30 * MS, 33 * MS, rng.randrange(1500 * MS)))
            events.append(ev(t, seq, rng.choice((0, 0, 8, 9, 10, 28, 28, 29, 30, 31)), rng.choice((1, 0, 7))))
            seq += 1
        events.append(END)
        got = _run(lane["driver"], "log", events)
        assert got == limiter_model(events)


# ============================================================ the text of monitor.c: the hooks

LANE_HOOK = [LANE_GUARD, "lane_log_end(&g_lane_log);", "#endif"]
CTL_HOOK = [CTL_GUARD, "ctl_log_end(&g_ctl_log);", "#endif"]
VSS_HOOK = [VSS_GUARD, "vss_log_end(&g_vss_log);", "#endif"]
SESSION_END_PRINTS = ('printf("monitor: client done:', 'printf("monitor: udp done:', 'printf("monitor: shm quiet:',
                      'printf("monitor: shm done:', 'printf("monitor: shm-kick burst:', 'printf("monitor: shm-kick done:')


def test_each_lane_flush_hook_stands_right_before_the_ctl_hook_of_each_session_end():
    src = [ln.strip() for ln in MONITOR_C.read_text(encoding="ascii").splitlines()]
    ends = [i for i, ln in enumerate(src) if ln.startswith(SESSION_END_PRINTS)]
    assert len(ends) == 7, ends
    for i in ends:
        assert src[i - 9:i] == LANE_HOOK + CTL_HOOK + VSS_HOOK, src[i - 10:i + 1]
    assert [i for i, ln in enumerate(src) if "lane_log_end(&g_lane_log)" in ln] == [i - 8 for i in ends]


# ============================================================ end to end

def test_kind_6_rejects_over_udp_print_the_lane_line_and_a_pending_summary_right_before_udp_done(lane50):
    frames = [k6(seq=1), k6(seq=2, conf=10), k6(seq=3, conf=10), k6(seq=4, width=9.0), k6(seq=5),
              k6(seq=6, width=9.0), k6(seq=7, width=9.0)]
    replies, out = _udp_session(lane50["monitor"], frames)
    assert [bytes.fromhex(r)[H + 7] for r in replies] == [0, 28, 28, 29, 0, 29, 29]
    assert [bytes.fromhex(r) for r in replies] == [replied(f, *ref_judge(f)) for f in frames]
    body = _from_banner(out)
    rejects = [ln for ln in body if ln.startswith("monitor: REJECT")]
    assert rejects == [REJECT_LINE % (2, 1, "lane-conf-low") + "\n", REJECT_LINE % (4, 1, "lane-implausible") + "\n",
                       REJECT_LINE % (6, 1, "lane-implausible") + "\n"]
    assert [HARNESS_REGEX.search(ln).groups() for ln in rejects] == [("2", "lane-conf-low"), ("4", "lane-implausible"),
                                                                     ("6", "lane-implausible")]
    by = collections.Counter()
    for ln in (x for x in body if x.startswith("monitor: lane summary:")):
        m = re.match(r"monitor: lane summary: seen=\d+ rejected=\d+ suppressed=(\d+) by reason:((?: \d+=\d+)+)\n$", ln)
        assert m is not None, ln
        for r, n in re.findall(r" (\d+)=(\d+)", m.group(2)):
            by[int(r)] += int(n)
    assert by == {28: 1, 29: 1}
    assert body[-2].startswith("monitor: lane summary:")
    assert body[-1] == "monitor: udp done: seen=7 accepted=2 rejected=5 dropped=0\n"


def test_the_lane_limiter_is_given_the_clock_and_a_new_bucket_prints_again_over_udp(lane50):
    frames = [k6(seq=s, conf=10) if s % 2 else k6(seq=s, width=9.0) for s in range(1, 43)]
    replies, out = _udp_session(lane50["monitor"], frames, pause=(40, 1.3))
    assert [bytes.fromhex(r)[H + 7] for r in replies] == [28 if s % 2 else 29 for s in range(1, 43)]
    printed = [int(m.group(1)) for m in (re.match(r"monitor: REJECT seq=(\d+) kind=lane ", ln) for ln in out) if m]
    assert 41 in printed and 42 in printed, printed


@pytest.mark.parametrize("mode", ["tcp", "stamp", "svc"])
def test_kind_6_rejects_over_a_stream_print_a_pending_summary_right_before_client_done_in_0x54(lane54, mode):
    words = {"tcp": [], "stamp": ["stamp"], "svc": ["svc", "60000"]}[mode]
    frames = [k6(seq=1), k6(seq=2, offset=F(0.9)), k6(seq=3, offset=F(0.9)), k6(seq=4, offset=0.75, heading=0.5, speed=20.0),
              k6(seq=5), k6(seq=6, offset=0.75, heading=0.5, speed=20.0), k6(seq=7, offset=0.75, heading=0.5, speed=20.0)]
    proc, port = mc._start_on_port(lane54["monitor"], words, socket.SOCK_STREAM, mc.BANNER[mode])
    try:
        replies = mc._drive_stream(port, [("frame %d" % i, f, None) for i, f in enumerate(frames)])
        proc.wait_for(b"monitor: client done:")
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    assert [bytes.fromhex(r[1])[H + 7] for r in replies] == [0, 30, 30, 31, 0, 31, 31]
    out = mc._normalise_stdout(b"".join(proc.out), port=port)
    assert [ln for ln in out if ln.startswith("monitor: REJECT")] == [
        REJECT_LINE % (2, 1, "lane-departure") + "\n", REJECT_LINE % (4, 1, "lane-departure-imminent") + "\n",
        REJECT_LINE % (6, 1, "lane-departure-imminent") + "\n"]
    i = out.index("monitor: client done: seen=7 accepted=2 rejected=5\n")
    assert out[i - 1].startswith("monitor: lane summary:")
    assert not [ln for ln in out if " kind=6 " in ln]


# ============================================================ the native build (2.7)

@pytest.fixture
def native(tmp_path):
    return tmv._Native(tmp_path)


def _gen_dir(tmp_path, ctl):
    _need_gen(ctl=ctl)
    gen = tmp_path / "gen"
    gen.mkdir()
    for h in GEN_HEADERS + ((CTL_HEADER,) if ctl else ()):
        shutil.copy2(str(GEN / h), str(gen / h))
    return gen


# C2b LB: 0x54's guest build is `make lane`.
@pytest.mark.parametrize("value,ctl,name", [("0x50", False, "the vss build with kind 6, lane; no guest build of it yet"),
                                            ("0x54", True, "the guest's build: make lane")])
def test_the_native_script_builds_each_lane_monitor_to_its_own_out(native, tmp_path, value, ctl, name):
    gen = _gen_dir(tmp_path, ctl)
    out = tmp_path / "out" / ("monitor-lane-" + value)
    r = native.run(OUT=out, MONITOR_EXT_KINDS=value, MONITOR_VSS_GEN=gen)
    assert r.returncode == 0, r.stderr
    assert native.argv() == tmv._default_argv(out) + ["-DMONITOR_EXT_KINDS=" + value, "-I", str(gen), "-ffp-contract=off"]
    headers = GEN_HEADERS + ((CTL_HEADER,) if ctl else ())
    base = [p.read_bytes() for p in tmv.DEFAULT_SOURCES]
    want = tmv._sha256(*base, *((gen / h).read_bytes() for h in headers),
                       ("MONITOR_EXT_KINDS=%s -ffp-contract=off\n" % value).encode())
    assert Path(str(out) + ".source-sha256").read_text(encoding="ascii") == want + "\n"
    switch = [ln for ln in r.stdout.splitlines() if ln.startswith("switch:")]
    assert switch == ["switch: MONITOR_EXT_KINDS=%s -ffp-contract=off  (%s)" % (value, name)], switch
    assert ("source: %s  vss_ctl.h" % hashlib.sha256((GEN / CTL_HEADER).read_bytes()).hexdigest() in r.stdout) is ctl
    assert not (native.home / "ladder").exists()
    got = _opening(str(out), "udp", tmp_path / "run")
    assert lane_announcement()[0] in got


def test_the_native_script_names_the_vss_and_ctl_builds_as_before(native, tmp_path):
    gen = _gen_dir(tmp_path, True)
    for value, make in (("0x10", "make vss"), ("0x14", "make ctl")):
        r = native.run(OUT=tmp_path / "out" / value, MONITOR_EXT_KINDS=value, MONITOR_VSS_GEN=gen)
        assert r.returncode == 0, r.stderr
        switch = [ln for ln in r.stdout.splitlines() if ln.startswith("switch:")]
        assert switch == ["switch: MONITOR_EXT_KINDS=%s -ffp-contract=off  (the guest's build: %s)" % (value, make)], switch


@pytest.mark.parametrize("value", ["0x40", "0x5C", "0x44", "0x58", "0X50", "0x050", "80", "0x55"])
def test_the_native_script_refuses_every_other_value(native, tmp_path, value):
    r = native.run(OUT=tmp_path / "out" / "monitor-x", MONITOR_EXT_KINDS=value)
    assert r.returncode != 0 and "spelt so" in r.stderr and "0x50" in r.stderr and "0x54" in r.stderr, r.stderr
    assert native.argv() is None


@pytest.mark.parametrize("value", ["0x50", "0x54"])
def test_the_native_script_refuses_the_default_out_for_a_lane_build(native, value):
    r = native.run(MONITOR_EXT_KINDS=value)
    assert r.returncode != 0 and "default OUT" in r.stderr, r.stderr
    assert native.argv() is None


def test_the_native_script_keeps_its_two_gcc_lines():
    sh = [ln.strip() for ln in NATIVE.read_text(encoding="ascii").splitlines() if ln.strip().startswith('"${CC}"')]
    assert len(sh) == 2 and sh[0] == tmv.DEFAULT_GCC_LINE, sh
