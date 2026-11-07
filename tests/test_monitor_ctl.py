"""Phase 8 WP1a: kind 2 (`ctl`) in the monitor, judged against a fixture contract (the Phase 8 specification, sections
2.1-2.5 and 3).

Under MONITOR_EXT_KINDS & 0x04 (the ctl build, 0x14), monitor.c judges kind 2: one Control command of the planning
stack's command gate, packed by the claim node (sdv/ctl, WP2) into the 64-byte frame of ipc-test/common/frame.h and
judged with the constants of vss_ctl.h. Every kind 2 line of monitor.c stands in a block opened by the exact line
`#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)`, and the Phase 2 deviation now stops 0x1C alone. What
is tested, and how:

- The rules (2.3), through tests/ctl_driver.c's `judge` mode, which runs the monitor's own check_claim(): each limit
  at, and one binary32 step above, in both signs and under both fixture profiles; the interval at 0, DT_MAX_MS, one
  above and 0xFFFF, read little-endian; an infinity or a NaN in each slot (9 when the slot is defined, 10 when its
  flag is clear); -0.0 in each undefined slot; each reserved bit and byte; profile 0 and every uncompiled id; rule
  17 at its edge against sdv/frame/rules.py's vss_tan in double, in every sign of the angle and of v_meas; rules 18
  and 19 at their thresholds in every sign; the order between every adjacent pair of rules, and from every rule on;
  and a seeded random corpus. The fixture's limits and constants are binary32 values, so a variant whose limits and
  constants are not is judged too: each limit accepted at its last binary32 and rejected one step above, rules 17-19
  at their bounds in double, its table and announcement as written; and rule 17's operation order at ties, on a
  variant whose rows are found by search. The fixture gives TOL17 and ROLLBACK_V one value and its profile ids are 1
  and 2, so two more variants tell what it cannot: ROLLBACK_V 0.25 against TOL17 0.5 (rules 17 and 19 and the rules
  line), and the ids 7 and 255 (the table and the lookup by id). Every expected verdict is also ref_judge()'s, a
  reference written here from 2.3 (WP2's sdv/ctl/ctlrules.py is the other one, held to this build by the Phase 8
  contract test).
- Kind 2 among the kinds: the unknown kinds [3, 7, 255] get reason 5 and the generic line; kind 4 frames (a corpus
  encoded with sdv/frame/vssframe.py) get the vss build's verdicts and console lines; kinds 0 and 1 and the unknown
  kinds reply and print as in the default build; kind 2 stays unknown in the vss build.
- The console (2.5): the opening lines in every serving mode (the vss build's, then the `ctl rules:` and `ctl
  profile` lines, none of them containing "claim kinds:"); the self-check's exit 2 on the bad-digest fixture before
  any serving line, after the vss one; the limiter's four rules at its cap of 34, in `log` mode with a scripted clock,
  against scenarios written out from the specification and against limiter_model(); end to end over UDP, the ctl
  REJECT line and a pending summary flushed right before `udp done:`, and a new bucket after a silence of 1.3 s
  (the limiter is given the monitor's clock).
- The text: each ctl flush hook stands as three lines right before the vss hook, seven of them and none elsewhere;
  outside the 0x04 blocks and the deviation, monitor.c is the reference blob's text with only comments changed (section
  3 item 3: the base value below is that text's sha256), and the deviation is its seven lines word for word; no
  <math.h> anywhere, no libm in the ctl build (readelf); the ctl unit clean under -Wpedantic.
- One exchange end to end on loopback with the ctl build in `PORT svc 500`: a kind 2 reply, a LIVENESS MISS after a
  silence, RESTORED on the next frame.
- The build: 0x1C still stops as not implemented and 0x14 does not; a vss_ctl.h of another format stops the ctl build;
  only the ctl build depends on vss_ctl.h; a vss_ctl.h in the gen directory never stands in for the fixtures (their
  directory comes first on the include path); a digest wrong in its high bit refuses as the twin's wrong low bit does.
  WP1a's own additions, each with its test: the self-check also refuses a
  compiled steer_max outside (0, 1.0] rad (2.3's invariant, which the Python loader of 2.4 holds too), an l_mm of 0
  (rule 17 divides by L_m) and an id two rows share; a row id outside 1..255, a VSS_CTL_PROFILE_COUNT that is not the
  row count, or a VSS_CTL_DT_MAX_MS of 0xFFFF or more (rule 11 could never reject the saturated interval) does not
  compile, with or without -Werror; rule 17's strictness at an exact tie, on a fixture variant whose lat_acc_max is
  computed here to make one.

The contract is tests/fixtures/ctl-c/vss_ctl.h, written by hand with synthetic values (its bad-digest twin beside it).
The generated one is WP1b's; the kind 4 headers are the generated ones in sdv-out/gen. Nothing here is a result: every
number is the fixture's or the specification's.

What this does NOT show: anything about the guest build (qcc output cannot run here, and 4.6(c) forbids taking the
guest binary apart); anything about the real kind 2 contract or the limits a real profile will carry (WP1b, WP4a);
that rules 17-19 are skipped when b3 is clear (a clear b3 means p[41..44] is zero, and with v_meas zero none of the
three can fire, so the skip cannot be seen in a verdict); the limiter under someip.c's two threads, which never define
the switch; any timing (the bucket edges end to end lie wherever the PC's clock puts them).

Needs gcc on Linux (WSL Ubuntu-24.04 or CI's tooling job), readelf, and the generated kind 4 contract in sdv-out/gen
(sdv/vss/generate.py). Without them a test skips, and under SDV_REQUIRE_GEN=1 it fails instead. The text tests need
none of them.
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

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MONITOR_C = REPO / "ipc-test" / "qnx-safety-monitor" / "monitor.c"
COMMON = REPO / "ipc-test" / "common"
SHM_MAP_POSIX_C = COMMON / "shm_map_posix.c"
IVSHM_CLIENT_C = COMMON / "ivshm_client.c"
CTL_DRIVER_C = HERE / "ctl_driver.c"
VSS_DRIVER_C = HERE / "vss_driver.c"
GEN = REPO / "sdv-out" / "gen"
GEN_HEADERS = ("vss_contract.h", "vss_profiles.h")
FIXTURE = HERE / "fixtures" / "ctl-c"
BAD_DIGEST = FIXTURE / "bad-digest"
FRAME_DIR = REPO / "sdv" / "frame"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(FRAME_DIR) not in sys.path:
    sys.path.insert(0, str(FRAME_DIR))
import rules  # noqa: E402
import vssframe as vf  # noqa: E402

sys.dont_write_bytecode = _saved

# tests/test_monitor_vss.py's DEFAULT_FLAGS, written out here (that file is Phase 7's and its helpers may move). The
# ctl build adds what the vss build adds, with the ctl value of the switch (2.1; WP1b's `make ctl` passes the same).
DEFAULT_FLAGS = ("-O2", "-std=gnu99", "-Wall", "-Wextra", "-Wformat=2", "-Wundef", "-Werror")
CTL_FLAGS = DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x14")
VSS_FLAGS = DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x10")
# The syntax-only gate for a stray file-scope ';' (only -Wpedantic reports an empty declaration). gnu11, not gnu99:
# shm_chan.h's _Static_assert is C11, as tests/test_monitor_vss.py found.
PEDANTIC_FLAGS = ("-fsyntax-only", "-std=gnu11", "-Wpedantic", "-Werror")
# The ctl build with no warning flag and no -Werror (the Makefile's builds warn and go on: it has no -Werror).
PLAIN_CTL_FLAGS = ("-O2", "-std=gnu99", "-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x14")
UNDEF_DIAG = "[-Werror=undef]"
GAP_ERROR = "MONITOR_EXT_KINDS 0x1C (gap): not implemented"
FORMAT_ERROR = "vss_ctl.h is not ctl contract format 1"
DT_MAX_ERROR = "VSS_CTL_DT_MAX_MS is below 0xFFFF: a saturated interval (0xFFFF) fails rule 11"

GUARD = "#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)"
DEVIATION_FIRST = "/* A deviation from section 11 (Phase 2 design decision d)"
# Section 3 item 3's base value: strip_kind2() applied to ipc-test/qnx-safety-monitor/monitor.c at the reference commit
# BASE_COMMIT (its blob exported with git cat-file on the Windows side, before any edit of the file, by the same function
# copied into a script outside the tree), then moved for the later comment-only edits (the KVM caveat, the threshold
# comments, the accepted socket's flag and the vlm bound's wording); the C tokens are unchanged.
BASE_COMMIT = "9d83ab91"
BASE_STRIPPED_SHA256 = "6dbadc1d76afd7d412f292b5e79959d570f7c05ec4fa312a96ca579f152cbd2b"
# Section 3 item 2's lines, the one stretch outside the 0x04 blocks that is not the reference blob's text. strip_kind2() removes
# it from its first line through the #endif of the not-implemented #error, so its own text is pinned here word for word.
DEVIATION = ("/* A deviation from section 11 (Phase 2 design decision d), narrowed in Phase 8",
             " * (WP1a) when kind 2 landed: kind 3 does not exist yet, so a gap build would",
             " * answer it with claim-kind-unknown while its name says it knows it. This",
             " * #error goes when kind 3 lands. */",
             "#  if MONITOR_EXT_KINDS == 0x1C",
             '#    error "MONITOR_EXT_KINDS 0x1C (gap): not implemented"',
             "#  endif")

REQUIRE_ENV = "SDV_REQUIRE_GEN"

# --- the payload (2.2) ----------------------------------------------------------------------------------------------

H = 16
P_FLAGS, P_PROFILE, P_V_CMD, P_VERDICT, P_REASON, P_KIND = 0, 1, 2, 6, 7, 24
P_ACC, P_JERK, P_DELTA, P_RATE, P_V_MEAS, P_INTERVAL, P_RESERVED = 25, 29, 33, 37, 41, 45, 47
B_ACC, B_JERK, B_RATE, B_ODOM = 0x01, 0x02, 0x04, 0x08
SLOT = {"v_cmd": (P_V_CMD, 0), "acc": (P_ACC, B_ACC), "jerk": (P_JERK, B_JERK), "delta": (P_DELTA, 0),
        "rate": (P_RATE, B_RATE), "v_meas": (P_V_MEAS, B_ODOM)}
OPTIONAL = ("acc", "jerk", "rate", "v_meas")
QNAN = 0x7FC00000
NONFINITE = {"+inf": 0x7F800000, "-inf": 0xFF800000, "quiet NaN": QNAN, "signalling NaN": 0x7F800001,
             "negative NaN": 0xFFFFFFFF}
ORDER = (10, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19)

NAMES = {0: "ok", 5: "claim-kind-unknown", 8: "profile-unbound", 9: "field-not-finite", 10: "flags-invalid",
         11: "ctl-interval", 12: "ctl-speed", 13: "ctl-accel", 14: "ctl-jerk", 15: "ctl-steer", 16: "ctl-steer-rate",
         17: "ctl-lat-accel", 18: "ctl-overspeed", 19: "ctl-rolling-back"}
CTL_REASONS = {r: NAMES[r] for r in range(11, 20)}

# 2.5's formats and the claim kinds line, written out here, never read from monitor.c.
CLAIM_KINDS = "monitor: claim kinds: 0 mnist (us <= 100000), 1 vlm model 1 (us <= 1000000), conf_min=60%\n"
CTL_RULES_LINE = ("monitor: ctl rules: kind 2, catalog 0x%08X (vss %s), dt_max %u ms, overspeed %g x v_cmd + %g m/s, "
                  "rollback %g m/s, tol17 %g m/s^2, profiles %s\n")
CTL_PROFILE_LINE = ("monitor: ctl profile %u: L %u mm, v_max %g m/s, a_max %g m/s^2, jerk_max %g m/s^3, steer_max %g rad, "
                    "steer_rate_max %g rad/s, lat_acc_max %g m/s^2\n")
REJECT_LINE = "monitor: REJECT seq=%d kind=ctl profile=%d reason=%s"
SUMMARY_LINE = "monitor: ctl summary: seen=%d rejected=%d suppressed=%d by reason:%s"
INCONSISTENT = b"monitor: ctl contract inconsistent\n"
VSS_INCONSISTENT = b"monitor: vss contract inconsistent\n"

CAP = 34                        # kind 2 REJECT lines per bucket (2.1: the control rate plus one; D6)
S = 1_000_000_000               # one bucket, ns
MS = 1_000_000
END = "E"

Prof = collections.namedtuple("Prof", "id l_mm v_max a_max jerk_max steer_max steer_rate_max lat_acc_max")


class Ctl:
    """The kind 2 contract of one vss_ctl.h, read from its text by 2.4's names."""

    def __init__(self, path):
        text = path.read_text(encoding="ascii")
        d = dict(m.groups() for m in re.finditer(r"^#define (VSS_CTL_[A-Z0-9_]+) (\S+)$", text, re.M))
        num = r"([-+0-9.eE]+)"
        rows = re.findall(r"^\s*X\((\d+)u, (\d+)u, %s\)" % ", ".join([num] * 6), text, re.M)
        self.format = int(d["VSS_CTL_FORMAT"].rstrip("u"))
        self.uids = tuple(int(d["VSS_CTL_UID_SLOT%d" % i].rstrip("u"), 16) for i in range(7))
        self.digest = int(d["VSS_CTL_DIGEST"].rstrip("u"), 16)
        self.dt_max_ms = int(d["VSS_CTL_DT_MAX_MS"].rstrip("u"))
        self.tol17 = float(d["VSS_CTL_TOL17"])
        self.overspeed_factor = float(d["VSS_CTL_OVERSPEED_FACTOR"])
        self.overspeed_margin = float(d["VSS_CTL_OVERSPEED_MARGIN"])
        self.rollback_v = float(d["VSS_CTL_ROLLBACK_V"])
        self.count = int(d["VSS_CTL_PROFILE_COUNT"].rstrip("u"))
        self.ids_text = re.search(r'^#define VSS_CTL_PROFILE_IDS "([^"]*)"$', text, re.M).group(1)
        self.profiles = collections.OrderedDict(
            (int(r[0]), Prof(int(r[0]), int(r[1]), *(float(x) for x in r[2:]))) for r in rows)


CTL = Ctl(FIXTURE / "vss_ctl.h")
P1 = CTL.profiles[1]


# --- skips, builds and drivers ----------------------------------------------------------------------------------------

def _missing(what):
    """An input is not there: skip, or fail under SDV_REQUIRE_GEN=1 (read strictly: 1, or off)."""
    value = os.environ.get(REQUIRE_ENV)
    if value == "1":
        pytest.fail("%s=1 and an input of the ctl tests is missing: %s" % (REQUIRE_ENV, what), pytrace=False)
    if value not in (None, "", "0"):
        pytest.fail("%s is %r: it is 1, or unset (a mistyped switch must not read as off)" % (REQUIRE_ENV, value),
                    pytrace=False)
    pytest.skip(what)


def _gcc():
    gcc = shutil.which("gcc")
    if gcc is None or not hasattr(os, "sched_getaffinity"):
        _missing("needs gcc on Linux: runs in WSL and in CI's tooling job")
    return gcc


def _need_gen():
    if not all((GEN / h).is_file() for h in GEN_HEADERS + ("vss_contract.py",)):
        _missing("needs the generated kind 4 contract in sdv-out/gen (sdv/vss/generate.py)")


def c4():
    """The generated kind 4 contract (vss_contract.py), loaded by path by sdv/frame/vssframe.py."""
    _need_gen()
    return vf.load_contract()


def _compile(gcc, flags, out, src, ctl_dir=FIXTURE, gen=GEN, link=True):
    # ctl_dir before gen: WP1b writes a vss_ctl.h into sdv-out/gen beside the kind 4 headers, and a build of this file
    # compiles the one it names (the fixture, a variant, the bad-digest twin), never the generated one.
    cmd = [gcc, *flags, "-I", str(COMMON), "-I", str(ctl_dir), "-I", str(gen)]
    if link:
        cmd += ["-o", str(out), str(src), str(SHM_MAP_POSIX_C), str(IVSHM_CLIENT_C)]
    else:
        cmd += ["-c", "-o", str(out), str(src)]
    return subprocess.run(cmd, capture_output=True, text=True)


def _build(out_dir, flags, ctl_dir=FIXTURE, gen=GEN, names=("monitor", "driver"), driver=CTL_DRIVER_C):
    """monitor.c and a driver built with `flags`, against the vss_ctl.h in ctl_dir and the kind 4 headers in gen."""
    gcc = _gcc()
    _need_gen()
    srcs = {"monitor": MONITOR_C, "driver": driver}
    out = {}
    for name in names:
        r = _compile(gcc, flags, out_dir / name, srcs[name], ctl_dir=ctl_dir, gen=gen)
        assert r.returncode == 0, "%s must compile clean under %s:\n%s" % (srcs[name].name, " ".join(flags), r.stderr)
        out[name] = str(out_dir / name)
    return out


@pytest.fixture(scope="module")
def ctl(tmp_path_factory):
    """The ctl build and tests/ctl_driver.c against the consistent fixture."""
    return _build(tmp_path_factory.mktemp("ctl"), CTL_FLAGS)


@pytest.fixture(scope="module")
def vss(tmp_path_factory):
    """The vss build and tests/vss_driver.c, with the fixture on the include path (which the vss build never reads)."""
    return _build(tmp_path_factory.mktemp("vss"), VSS_FLAGS, driver=VSS_DRIVER_C)


@pytest.fixture(scope="module")
def bad_digest(tmp_path_factory):
    return _build(tmp_path_factory.mktemp("bad"), CTL_FLAGS, ctl_dir=BAD_DIGEST, names=("monitor",))["monitor"]


@pytest.fixture(scope="module")
def default_monitor(tmp_path_factory):
    """The default build, with the golden's gcc line (tests/monitor_corpus.py)."""
    out = tmp_path_factory.mktemp("default") / "monitor"
    r = subprocess.run(mc.gcc_command(_gcc(), str(REPO), str(out)), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


def _run(binary, mode, lines=()):
    r = subprocess.run([binary, mode], input="".join(x + "\n" for x in lines), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and not r.stderr, (r.returncode, r.stderr)
    return r.stdout.splitlines()


def judge(builds, frames):
    """(verdict, reason, name) of each frame from the build's check_claim()."""
    out = _run(builds["driver"], "judge", [bytes(f).hex() for f in frames])
    assert len(out) == len(frames), out
    res = []
    for ln in out:
        v, r, name = ln.split(" ", 2)
        res.append((int(v), int(r), name))
    return res


# --- frames -----------------------------------------------------------------------------------------------------------

class Raw(int):
    """A slot's binary32 bits as they are: a NaN's payload, an infinity, -0.0."""


def bits(x):
    if isinstance(x, Raw):
        return int(x)
    b = vf.f32_bits(x)
    assert vf.bits_f32(b) == x, "%r is not a binary32 value: give one, or Raw bits" % (x,)
    return b


def up(x):
    """The next binary32 above the binary32 x."""
    return vf.f32_next_up(x)


def k2(seq=1, profile=1, v_cmd=0.0, acc=None, jerk=None, delta=0.0, rate=None, v_meas=None, interval=0, flags=None,
       kind=2, tstamp=0):
    """A kind 2 request laid out as 2.2: each optional slot given has its flag set (flags= overrides the byte)."""
    p = bytearray(48)
    f = 0
    for name, value in (("v_cmd", v_cmd), ("acc", acc), ("jerk", jerk), ("delta", delta), ("rate", rate),
                        ("v_meas", v_meas)):
        if value is None:
            continue
        off, bit = SLOT[name]
        f |= bit
        p[off:off + 4] = struct.pack("<I", bits(value))
    p[P_FLAGS] = f if flags is None else flags
    p[P_PROFILE] = profile
    p[P_KIND] = kind
    p[P_INTERVAL:P_INTERVAL + 2] = struct.pack("<H", interval)
    return struct.pack("<QQ", seq, tstamp) + bytes(p)


def setp(frame, off, data):
    """The frame with payload bytes at payload offset `off` overwritten."""
    b = bytearray(frame)
    b[H + off:H + off + len(data)] = data
    return bytes(b)


def poisoned(frame):
    """The verdict and reason bytes preset to 0xEE, as tests/monitor_corpus.py does: a reply's are the monitor's."""
    return setp(frame, P_VERDICT, b"\xee\xee")


def replied(frame, verdict, reason):
    return setp(frame, P_VERDICT, bytes((verdict, reason)))


def ref_judge(frame, c=None):
    """2.3, written here from the specification: (verdict, reason) of one kind 2 request. The order 10, 8, 9, 11-19,
    the first failure winning; every comparison strict; f32 widened to double; rule 17 in double in its operation
    order with rules.vss_tan and L in m (l_mm x M_PER_MM)."""
    c = CTL if c is None else c
    p = bytes(frame[H:])
    assert len(p) == 48 and p[P_KIND] == 2
    f = p[P_FLAGS]
    opt = [SLOT[n] for n in OPTIONAL]

    def u32(off):
        return struct.unpack_from("<I", p, off)[0]

    def val(off):
        return struct.unpack_from("<f", p, off)[0]

    if (f & 0xF0 or any(p[8:24]) or p[P_RESERVED]
            or any(not f & bit and any(p[off:off + 4]) for off, bit in opt)):
        return 1, 10
    pr = c.profiles.get(p[P_PROFILE])
    if pr is None:
        return 1, 8
    defined = [P_V_CMD, P_DELTA] + [off for off, bit in opt if f & bit]
    if any((u32(off) >> 23) & 0xFF == 0xFF for off in defined):
        return 1, 9
    if struct.unpack_from("<H", p, P_INTERVAL)[0] > c.dt_max_ms:
        return 1, 11
    v_cmd, a, j, d, rate, v_meas = (val(SLOT[n][0]) for n in ("v_cmd", "acc", "jerk", "delta", "rate", "v_meas"))
    ad = rules.dabs(d)
    if rules.dabs(v_cmd) > pr.v_max:
        return 1, 12
    if f & B_ACC and rules.dabs(a) > pr.a_max:
        return 1, 13
    if f & B_JERK and rules.dabs(j) > pr.jerk_max:
        return 1, 14
    if ad > pr.steer_max:
        return 1, 15
    if f & B_RATE and rules.dabs(rate) > pr.steer_rate_max:
        return 1, 16
    if f & B_ODOM and v_meas * v_meas * rules.vss_tan(ad) / (pr.l_mm * c4().M_PER_MM) > pr.lat_acc_max + c.tol17:
        return 1, 17
    if f & B_ODOM and rules.dabs(v_meas) > c.overspeed_factor * rules.dabs(v_cmd) + c.overspeed_margin:
        return 1, 18
    if f & B_ODOM and v_meas < -c.rollback_v and v_cmd >= 0.0:
        return 1, 19
    return 0, 0


def expect(builds, cases, c=None):
    """cases: [(label, frame, reason)]. Each frame's verdict, reason and name from the build must be the case's, and
    ref_judge() under the build's contract c (the fixture's when None) must say the same."""
    got = judge(builds, [x[1] for x in cases])
    bad = []
    for (label, fr, want), res in zip(cases, got):
        w = (0 if want == 0 else 1, want, NAMES[want])
        ref = ref_judge(fr, c)
        if res != w or ref != w[:2]:
            bad.append("%s: build %s, ref_judge %s, want %s" % (label, res, ref, w))
    assert not bad, "\n".join(bad)


def last_f32(holds):
    """The largest non-negative binary32 x for which holds(x) is true, holds being true at 0.0 and monotone: a binary
    search over the bit patterns, whose order is the values' order for non-negative floats."""
    assert holds(0.0)
    lo, hi = 0, 0x7F7FFFFF
    if holds(vf.bits_f32(hi)):
        return vf.bits_f32(hi)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if holds(vf.bits_f32(mid)):
            lo = mid
        else:
            hi = mid - 1
    return vf.bits_f32(lo)


def f32_floor(x):
    """The largest binary32 at or below the double x >= 0, x itself when x is a binary32 value: a limit's last accepted
    value, whether or not the limit is on the binary32 grid (the fixture's limits are, the variant's below are not)."""
    assert x >= 0.0
    f = vf.f32(x)
    return vf.f32_next_down(f) if f > x else f


def _d_step(x, n):
    """The double n steps from the positive double x (bit patterns of positive doubles are ordered as their values)."""
    assert x > 0.0
    return struct.unpack("<d", struct.pack("<q", struct.unpack("<q", struct.pack("<d", x))[0] + n))[0]


# ============================================================ the builds

def test_the_ctl_build_and_its_driver_compile_clean_under_the_tests_flags(ctl):
    assert os.path.isfile(ctl["monitor"]) and os.path.isfile(ctl["driver"])


def test_the_ctl_unit_holds_no_stray_semicolon():
    gcc = _gcc()
    _need_gen()
    r = subprocess.run([gcc, *PEDANTIC_FLAGS, "-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x14", "-I", str(COMMON),
                        "-I", str(FIXTURE), "-I", str(GEN), str(MONITOR_C)], capture_output=True, text=True)
    assert r.returncode == 0, "the ctl unit must be clean under -Wpedantic:\n" + r.stderr


def test_0x1C_alone_still_stops_as_not_implemented(tmp_path):
    # Section 3 item 2: kind 3 does not exist yet, so a gap build would answer it with claim-kind-unknown.
    gcc = _gcc()
    _need_gen()
    r = _compile(gcc, DEFAULT_FLAGS + ("-ffp-contract=off", "-DMONITOR_EXT_KINDS=0x1C"), tmp_path / "gap.o", MONITOR_C,
                 link=False)
    assert r.returncode != 0 and GAP_ERROR in r.stderr, r.stderr
    assert "0x14" not in r.stderr and "must be 0x10" not in r.stderr, r.stderr
    r = _compile(gcc, CTL_FLAGS, tmp_path / "ctl.o", MONITOR_C, link=False)
    assert r.returncode == 0 and "not implemented" not in r.stderr, r.stderr


@pytest.mark.parametrize("edit", ["format 2", "format 0", "no format"])
def test_a_ctl_contract_of_another_format_stops_the_ctl_build(edit, tmp_path):
    gcc = _gcc()
    _need_gen()
    text = (FIXTURE / "vss_ctl.h").read_text(encoding="ascii")
    line = "#define VSS_CTL_FORMAT 1u\n"
    assert text.count(line) == 1
    d = tmp_path / "ctl"
    d.mkdir()
    new = {"format 2": "#define VSS_CTL_FORMAT 2u\n", "format 0": "#define VSS_CTL_FORMAT 0u\n", "no format": ""}[edit]
    (d / "vss_ctl.h").write_text(text.replace(line, new), encoding="ascii")
    r = _compile(gcc, CTL_FLAGS, tmp_path / "unit.o", MONITOR_C, ctl_dir=d, link=False)
    assert r.returncode != 0 and FORMAT_ERROR in r.stderr, r.stderr
    assert UNDEF_DIAG not in r.stderr, "the guard tests definedness before it reads the macro:\n" + r.stderr


def test_only_the_ctl_build_depends_on_vss_ctl_h():
    gcc = _gcc()
    _need_gen()
    for define, ctl_header in ((None, False), ("0x10", False), ("0x14", True)):
        cmd = [gcc, "-std=gnu99"] + (["-DMONITOR_EXT_KINDS=" + define] if define else [])
        cmd += ["-I", str(COMMON), "-I", str(FIXTURE), "-I", str(GEN), "-MM", str(MONITOR_C)]
        deps = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
        assert ("vss_ctl.h" in deps) is ctl_header, (define, deps)
        assert all(h in deps for h in GEN_HEADERS) is (define is not None), (define, deps)


def test_no_math_h_anywhere_and_no_libm_in_the_ctl_build(ctl):
    text = MONITOR_C.read_text(encoding="ascii")
    assert not re.search(r"#\s*include\s*<\s*math\.h\s*>", text)
    deps = subprocess.run([_gcc(), "-std=gnu99", "-DMONITOR_EXT_KINDS=0x14", "-I", str(COMMON), "-I", str(FIXTURE),
                           "-I", str(GEN), "-M", str(MONITOR_C)], check=True, capture_output=True, text=True).stdout
    assert "/math.h" not in deps, deps
    readelf = shutil.which("readelf")
    if readelf is None:
        _missing("needs readelf (binutils)")
    dyn = subprocess.run([readelf, "-d", ctl["monitor"]], check=True, capture_output=True, text=True).stdout
    needed = re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", dyn)
    assert needed and not [n for n in needed if n.startswith("libm.") or n.startswith("libm-")], needed
    syms = subprocess.run([readelf, "--dyn-syms", "-W", ctl["monitor"]], check=True, capture_output=True, text=True).stdout
    undefined = {ln.split()[-1].split("@")[0] for ln in syms.splitlines() if " UND " in ln and len(ln.split()) >= 8}
    assert not undefined & {"tan", "tanf", "sin", "sinf", "cos", "cosf", "atan", "sqrt", "fabs"}, sorted(undefined)


# ============================================================ the contract as monitor.c sees it

def test_the_driver_sees_the_fixture_contract_through_monitor_c(ctl):
    out = _run(ctl["driver"], "constants")
    lines = dict(ln.split(" ", 1) for ln in out if not ln.startswith("profile "))
    assert lines["ext_kinds"] == "0x14"
    assert int(lines["format"]) == CTL.format == 1
    assert tuple(int(x, 16) for x in lines["uids"].split()) == CTL.uids
    assert int(lines["digest"], 16) == CTL.digest == vf.digest_of(CTL.uids), "the fixture is consistent"
    assert int(lines["dt_max_ms"]) == CTL.dt_max_ms
    assert [float.fromhex(x) for x in lines["consts"].split()] == [CTL.tol17, CTL.overspeed_factor, CTL.overspeed_margin,
                                                                   CTL.rollback_v]
    assert float.fromhex(lines["m_per_mm"]) == c4().M_PER_MM
    rows = [ln.split()[1:] for ln in out if ln.startswith("profile ")]
    assert [Prof(int(r[0]), int(r[1]), *(float.fromhex(x) for x in r[2:])) for r in rows] == list(CTL.profiles.values())
    ids = " ".join(str(i) for i in CTL.profiles)
    assert lines["ids"] == "%s count %d" % (ids, len(CTL.profiles)) and CTL.ids_text == ids and CTL.count == len(rows)
    assert int(lines["log_cap"]) == CAP
    # 2.3: every compiled profile has 0 < steer_max <= 1.0 rad, so rule 17 only ever takes tan inside [0, 1].
    assert all(0.0 < p.steer_max <= 1.0 for p in CTL.profiles.values())


def test_the_compiled_table_and_ctl_profile_find_for_every_id(ctl):
    out = _run(ctl["driver"], "table")
    rows = [ln.split()[1:] for ln in out if ln.startswith("row ")]
    assert [Prof(int(r[0]), int(r[1]), *(float.fromhex(x) for x in r[2:])) for r in rows] == list(CTL.profiles.values())
    finds = {int(a): int(b) for _, a, b in (ln.split() for ln in out if ln.startswith("find "))}
    ids = list(CTL.profiles)
    assert finds == {i: (ids.index(i) if i in ids else -1) for i in range(256)}
    assert finds[0] == -1, "profile 0 is never bound"


def test_profiles_are_found_by_their_ids_whatever_the_ids_are(tmp_path):
    """The fixture's ids are 1 and 2, contiguous from 1, so a lookup by position (the row id - 1) finds both. In this
    variant the rows keep their limits and take the ids 7 and 255: the table carries them, ctl_profile_find() finds
    exactly them, and the judge binds them to their own rows and no other id (not 1 and 2)."""
    rows = [(i,) + tuple(p)[1:] for i, p in zip((7, 255), CTL.profiles.values())]
    d = _contract_variant(tmp_path / "contract", rows=rows)
    c = Ctl(d / "vss_ctl.h")
    assert list(c.profiles) == [7, 255] and c.ids_text == "7 255" and c.count == 2
    builds = _build(tmp_path, CTL_FLAGS, ctl_dir=d)
    out = _run(builds["driver"], "table")
    got = [Prof(int(r[0]), int(r[1]), *(float.fromhex(x) for x in r[2:])) for r in
           (ln.split()[1:] for ln in out if ln.startswith("row "))]
    assert [p.id for p in got] == [7, 255] and got == list(c.profiles.values())
    finds = {int(a): int(b) for _, a, b in (ln.split() for ln in out if ln.startswith("find "))}
    assert finds == {i: {7: 0, 255: 1}.get(i, -1) for i in range(256)}
    expect(builds, [("profile 7", k2(profile=7), 0), ("profile 255", k2(profile=255), 0),
                    ("profile 1, not an id of the variant", k2(profile=1), 8),
                    ("profile 2, not an id of the variant", k2(profile=2), 8),
                    ("profile 7 binds profile 1's limits", k2(profile=7, v_cmd=20.0), 0),
                    ("profile 255 binds profile 2's limits", k2(profile=255, v_cmd=20.0), 12)], c)


def test_the_ctl_builds_reason_names(ctl, vss):
    got = dict(ln.split(" ", 2)[1:] for ln in _run(ctl["driver"], "reasons"))
    vss_names = dict(ln.split(" ", 2)[1:] for ln in _run(vss["driver"], "reasons"))
    assert {int(r): n for r, n in got.items()} == {r: CTL_REASONS.get(r, vss_names[str(r)]) for r in range(256)}
    assert all(vss_names[str(r)] == "unknown" for r in CTL_REASONS), "the vss build names no kind 2 reason"
    assert [vss_names[str(r)] for r in (8, 9, 10)] == ["profile-unbound", "field-not-finite", "flags-invalid"]


# ============================================================ the rules (2.3)

def test_an_honest_frame_is_accepted_under_each_profile(ctl):
    cases = []
    for pid in CTL.profiles:
        cases.append(("profile %d, the always-present fields only" % pid, k2(profile=pid), 0))
        cases.append(("profile %d, every slot defined" % pid,
                      k2(profile=pid, v_cmd=2.0, acc=0.5, jerk=1.0, delta=0.125, rate=0.125, v_meas=2.0, interval=33), 0))
        cases.append(("profile %d, verdict and reason bytes preset" % pid, poisoned(k2(profile=pid, v_cmd=1.0)), 0))
    expect(ctl, cases)


LIMITS = [(12, "v_cmd", "v_max"), (13, "acc", "a_max"), (14, "jerk", "jerk_max"), (15, "delta", "steer_max"),
          (16, "rate", "steer_rate_max")]


@pytest.mark.parametrize("pid", sorted(CTL.profiles))
@pytest.mark.parametrize("rule,slot,field", LIMITS, ids=[str(x[0]) for x in LIMITS])
def test_each_limit_is_accepted_at_and_rejected_one_binary32_step_above(ctl, rule, slot, field, pid):
    lim = getattr(CTL.profiles[pid], field)
    cases = []
    for sign in (1.0, -1.0):
        cases.append(("%s = %r" % (slot, sign * lim), k2(profile=pid, **{slot: sign * lim}), 0))
        cases.append(("%s = %r" % (slot, sign * up(lim)), k2(profile=pid, **{slot: sign * up(lim)}), rule))
    expect(ctl, cases)


def test_the_interval_at_its_edges_read_little_endian(ctl):
    d = CTL.dt_max_ms
    assert d < 256, "the cases below read 1 and 256 against a DT_MAX_MS under 256"
    expect(ctl, [
        ("0, the first Control", k2(interval=0), 0),
        ("DT_MAX_MS", k2(interval=d), 0),
        ("DT_MAX_MS + 1", k2(interval=d + 1), 11),
        ("0xFFFF, saturated", k2(interval=0xFFFF), 11),
        ("1, which is 256 read big-endian", k2(interval=1), 0),
        ("256, which is 1 read big-endian", k2(interval=256), 11),
    ])


@pytest.mark.parametrize("slot", list(SLOT))
def test_an_infinity_or_a_nan_in_each_slot(ctl, slot):
    cases = []
    for what, b in NONFINITE.items():
        cases.append(("%s %s, defined" % (slot, what), k2(**{slot: Raw(b)}), 9))
        if slot in OPTIONAL:
            # flags-invalid before field-not-finite: an undefined slot's bytes are judged as bytes
            cases.append(("%s %s, its flag clear" % (slot, what), setp(k2(), SLOT[slot][0], struct.pack("<I", b)), 10))
    expect(ctl, cases)


def test_finite_extremes_are_judged_by_their_value(ctl):
    biggest, tiny, neg_zero = Raw(0x7F7FFFFF), Raw(0x00000001), Raw(0x80000000)
    cases = [("v_cmd the largest finite", k2(v_cmd=biggest), 12), ("acc the largest finite", k2(acc=biggest), 13),
             ("jerk the largest finite", k2(jerk=biggest), 14), ("delta the largest finite", k2(delta=biggest), 15),
             ("rate the largest finite", k2(rate=biggest), 16), ("v_meas the largest finite", k2(v_meas=biggest), 18)]
    cases += [("%s the smallest subnormal" % s, k2(**{s: tiny}), 0) for s in SLOT]
    cases += [("%s -0.0, defined" % s, k2(**{s: neg_zero}), 0) for s in SLOT]
    expect(ctl, cases)


@pytest.mark.parametrize("slot", OPTIONAL)
def test_minus_zero_in_an_undefined_slot_is_reason_10(ctl, slot):
    off = SLOT[slot][0]
    expect(ctl, [("%s -0.0, its flag clear" % slot, setp(k2(), off, struct.pack("<I", 0x80000000)), 10),
                 ("%s +0.0, its flag clear" % slot, setp(k2(), off, b"\0\0\0\0"), 0),
                 ("%s one low byte, its flag clear" % slot, setp(k2(), off, b"\x01\0\0\0"), 10)])


def test_each_reserved_bit_and_byte_is_reason_10(ctl):
    cases = [("flag b%d" % b, k2(flags=1 << b), 10) for b in range(4, 8)]
    cases += [("flag b%d with every slot defined" % b,
               k2(v_cmd=1.0, acc=0.5, jerk=0.5, rate=0.125, v_meas=1.0, flags=0x0F | (1 << b)), 10) for b in range(4, 8)]
    for i in range(8, 24):
        cases += [("p[%d] = 0x%02X" % (i, v), setp(k2(), i, bytes((v,))), 10) for v in (0x01, 0x80)]
    cases += [("p[47] = 0x%02X" % v, setp(k2(), P_RESERVED, bytes((v,))), 10) for v in (0x01, 0x80)]
    expect(ctl, cases)


def test_profile_0_and_every_uncompiled_id_are_reason_8(ctl):
    expect(ctl, [("profile %d" % i, k2(profile=i), 0 if i in CTL.profiles else 8) for i in range(256)])


RULE17 = [(1, 1.0), (1, 0.5), (1, 0.125), (2, 1.0)]       # (profile, the fraction of its steer_max): binary32 angles


def _rule_17_edge_cases(c, pid, frac):
    """Rule 17 at its edge, under profile pid of the contract c and the angle frac x steer_max: the cases (label, frame,
    reason) with v_meas the last binary32 at which v_meas^2 tan|delta| / L_m is not over lat_acc_max + TOL17 (accepted,
    in each sign of the angle and of v_meas) and the next one up (17)."""
    pr = c.profiles[pid]
    ad = pr.steer_max * frac
    l_m = pr.l_mm * c4().M_PER_MM
    bound = pr.lat_acc_max + c.tol17

    def within(v):
        return not v * v * rules.vss_tan(ad) / l_m > bound

    v = last_f32(within)
    assert within(v) and not within(up(v))
    cases = []
    for d_sign in (1.0, -1.0):
        for m_sign in (1.0, -1.0):
            # v_cmd of v_meas's sign and no smaller than needed: rules 18 and 19 cannot fire at the edge
            v_cmd = m_sign * min(v, pr.v_max)
            label = "delta %r v_cmd %r v_meas %r" % (d_sign * ad, v_cmd, m_sign * v)
            cases.append((label, k2(profile=pid, v_cmd=v_cmd, delta=d_sign * ad, v_meas=m_sign * v), 0))
            cases.append((label + " + one step", k2(profile=pid, v_cmd=v_cmd, delta=d_sign * ad, v_meas=m_sign * up(v)), 17))
    return cases


@pytest.mark.parametrize("pid,frac", RULE17, ids=["p%d-%g" % x for x in RULE17])
def test_rule_17_at_its_edge_against_rules_vss_tan_in_double(ctl, pid, frac):
    expect(ctl, _rule_17_edge_cases(CTL, pid, frac))


def test_rule_17_is_strict_at_an_exact_tie(tmp_path):
    """A v_meas whose v_meas^2 tan|delta| / L is exactly lat_acc_max + TOL17 is accepted. No fixture profile has such a
    tie, so a variant of the fixture header gives profile 2 a lat_acc_max that makes one (a second build, as
    tests/test_monitor_kind4_console.py builds one with test profiles); its value is computed here, never a result."""
    pr = CTL.profiles[2]
    v0, ad0 = 4.0, 0.5
    assert ad0 <= pr.steer_max
    target = v0 * v0 * rules.vss_tan(ad0) / (pr.l_mm * c4().M_PER_MM)
    lat = target - CTL.tol17
    assert lat > 0.0 and lat + CTL.tol17 == target and float(repr(lat)) == lat
    row = "X(2u, 2790u, 3.0, 5.0, 80.0, 1.0, 1.0, 5.0)"
    d = _fixture_variant(tmp_path, row, row.replace(", 5.0)", ", %r)" % lat))
    variant = Ctl(d / "vss_ctl.h")
    assert variant.profiles[2].lat_acc_max == lat
    builds = _build(tmp_path, CTL_FLAGS, ctl_dir=d)
    frames = [k2(profile=2, v_cmd=3.0, delta=ad0, v_meas=v0), k2(profile=2, v_cmd=3.0, delta=ad0, v_meas=up(v0)),
              k2(profile=2, v_cmd=-3.0, delta=-ad0, v_meas=-v0), k2(profile=2, v_cmd=-3.0, delta=-ad0, v_meas=-up(v0))]
    want = [(0, 0, "ok"), (1, 17, "ctl-lat-accel")] * 2
    assert judge(builds, frames) == want
    assert [ref_judge(f, variant) for f in frames] == [w[:2] for w in want]


def _r17_orders(v, t, l_mm, lat, tol, m):
    """Whether rule 17 fires at v_meas v and tan|delta| t: 2.3's operation order (v * v, times tan, divided by L_m =
    l_mm * M_PER_MM, M_PER_MM being m, against lat_acc_max + TOL17, in double), and four other orders a port could slip
    into, each of which rounds otherwise at some points."""
    l_m = l_mm * m
    return v * v * t / l_m > lat + tol, {
        "L_m as l_mm / 1000": v * v * t / (l_mm / 1000.0) > lat + tol,
        "v * (v * tan) / L_m": v * (v * t) / l_m > lat + tol,
        "v * v / L_m * tan": v * v / l_m * t > lat + tol,
        "the tolerance moved to the left": v * v * t / l_m - tol > lat,
    }


def _near_the_r17_bound(t, tol, m):
    """(l_mm, v0, lat_acc_max) in a fixed order: v0 the binary32 at or below k/10 m/s, never a power of two, and
    lat_acc_max within two doubles of v0^2 t / L_m - tol, so that v0 is at or next to rule 17's bound."""
    for l_mm in range(2501, 2701):
        for k in range(31, 120):
            v0 = f32_floor(k / 10.0)
            if v0 == 2.0 ** round(math.log2(v0)):
                continue
            x = v0 * v0 * t / (l_mm * m)
            for step in (0, -1, 1, -2, 2):
                yield l_mm, v0, _d_step(x - tol, step)


def test_rule_17_keeps_its_operation_order_at_ties(tmp_path):
    """2.3 computes rule 17 in double "in that operation order". At a tie, or a double or two from one, another order
    can round to the other side of lat_acc_max + TOL17, which an exactly representable v_meas^2 (the tie test above
    has v0 = 4.0) and an exact L_m cannot show. The rows of this variant are found here by search: a v0 that is no power
    of two and an l_mm (some of them with an inexact L_m), with lat_acc_max within two doubles of v0^2 tan|delta0| / L_m
    - TOL17, at which 2.3's order and one other order judge otherwise; one row for each other order at least. Every
    value is computed here, never a result."""
    tol, ad0, m = 0.5, f32_floor(0.37), c4().M_PER_MM
    t = rules.vss_tan(ad0)

    def otherwise(point, name):
        spec, alt = _r17_orders(point[1], t, point[0], point[2], tol, m)
        return alt[name] != spec

    rows, covered = [], {}
    names = sorted(_r17_orders(1.0, t, 2700, 1.0, tol, m)[1])
    for name in names:
        hit = next((p for p in _near_the_r17_bound(t, tol, m) if otherwise(p, name)), None)
        assert hit is not None, "no point found at which %r rounds otherwise" % name
        if hit not in rows:
            rows.append(hit)
        covered[name] = rows.index(hit) + 1
    assert any(l_mm * m != l_mm / 1000.0 for l_mm, _, _ in rows), "an inexact L_m among the rows"
    assert all(v0 != 2.0 ** round(math.log2(v0)) for _, v0, _ in rows), "no v0 a power of two"
    d = _contract_variant(tmp_path / "contract", (("VSS_CTL_TOL17", repr(tol)),),
                          [(i + 1, l_mm, 25.0, 5.0, 80.0, 1.0, 1.0, lat) for i, (l_mm, _, lat) in enumerate(rows)])
    variant = Ctl(d / "vss_ctl.h")
    assert variant.tol17 == tol and [(p.l_mm, p.lat_acc_max) for p in variant.profiles.values()] == [
        (r[0], r[2]) for r in rows]
    frames, want = [], []
    for i, (l_mm, v0, lat) in enumerate(rows):
        spec = _r17_orders(v0, t, l_mm, lat, tol, m)[0]
        assert all(otherwise(rows[i], n) for n in names if covered[n] == i + 1)
        for sign in (1.0, -1.0):
            frames.append(k2(profile=i + 1, v_cmd=sign * v0, delta=sign * ad0, v_meas=sign * v0))
            want.append(17 if spec else 0)
            frames.append(k2(profile=i + 1, v_cmd=sign * v0, delta=sign * ad0, v_meas=sign * up(v0)))
            want.append(17)
    builds = _build(tmp_path, CTL_FLAGS, ctl_dir=d)
    want = [(0 if r == 0 else 1, r, NAMES[r]) for r in want]
    assert judge(builds, frames) == want
    assert [ref_judge(f, variant) for f in frames] == [w[:2] for w in want]


@pytest.mark.parametrize("v_cmd", [5.0, 3.0, 0.0])
def test_rule_18_at_its_threshold_in_every_sign(ctl, v_cmd):
    threshold = CTL.overspeed_factor * v_cmd + CTL.overspeed_margin
    v = last_f32(lambda x: x <= threshold)
    cases = []
    for c_sign, m_sign in ((1.0, 1.0), (-1.0, -1.0), (-1.0, 1.0), (1.0, -1.0)):
        c = c_sign * v_cmd
        # at the edge rule 18 holds back; a negative v_meas under a v_cmd >= 0 (-0.0 included) is then rule 19's
        at = 19 if (m_sign < 0 and c >= 0.0) else 0
        cases.append(("v_cmd %r v_meas %r" % (c, m_sign * v), k2(v_cmd=c, v_meas=m_sign * v), at))
        cases.append(("v_cmd %r v_meas %r" % (c, m_sign * up(v)), k2(v_cmd=c, v_meas=m_sign * up(v)), 18))
    expect(ctl, cases)


@pytest.mark.parametrize("v_cmd", [0.0, -0.0, 1.0, -1.0])
def test_rule_19_at_its_threshold(ctl, v_cmd):
    edge = last_f32(lambda x: x <= CTL.rollback_v)
    back = 19 if v_cmd >= 0.0 else 0
    expect(ctl, [("v_cmd %r v_meas %r" % (v_cmd, -edge), k2(v_cmd=v_cmd, v_meas=-edge), 0),
                 ("v_cmd %r v_meas %r" % (v_cmd, -up(edge)), k2(v_cmd=v_cmd, v_meas=-up(edge)), back),
                 ("v_cmd %r v_meas -2.0" % v_cmd, k2(v_cmd=v_cmd, v_meas=-2.0), back),
                 ("v_cmd %r v_meas +2.0" % v_cmd, k2(v_cmd=v_cmd, v_meas=2.0), 0)])


def test_rule_17s_tolerance_and_rule_19s_threshold_are_two_constants(tmp_path):
    """The fixture gives TOL17 and ROLLBACK_V the one value, 0.5, so a rule 17 that took ROLLBACK_V for its tolerance, a
    rule 19 that took TOL17 for its threshold, or a rules line that printed the two the other way round would judge and
    print the fixture as 2.3 and 2.5 do. In this variant ROLLBACK_V is 0.25 and TOL17 stays 0.5: the rules line carries
    each at its own place, rule 19 turns at 0.25, and rule 17's edge lies against lat_acc_max + 0.5."""
    d = _fixture_variant(tmp_path, "#define VSS_CTL_ROLLBACK_V 0.5\n", "#define VSS_CTL_ROLLBACK_V 0.25\n")
    c = Ctl(d / "vss_ctl.h")
    assert (c.tol17, c.rollback_v) == (0.5, 0.25)
    builds = _build(tmp_path, CTL_FLAGS, ctl_dir=d)
    line = [ln for ln in _opening(builds["monitor"], "udp", tmp_path / "udp") if ln.startswith("monitor: ctl rules:")]
    assert line == [ctl_announcement(c)[0]] and "rollback 0.25 m/s, tol17 0.5 m/s^2, " in line[0], line
    edge = last_f32(lambda x: x <= c.rollback_v)
    assert edge == 0.25
    expect(builds, [("v_meas = -0.25", k2(v_cmd=0.0, v_meas=-edge), 0),
                    ("v_meas = -0.25 less one step", k2(v_cmd=0.0, v_meas=-up(edge)), 19),
                    ("v_meas = -0.375, between the two constants", k2(v_cmd=0.0, v_meas=-0.375), 19)], c)
    expect(builds, _rule_17_edge_cases(c, 1, 1.0), c)


def test_rules_17_to_19_with_b3_clear(ctl):
    # With b3 clear p[41..44] is zero (10 otherwise), so none of the three could fire: these only show acceptance.
    expect(ctl, [("b3 clear, the largest angle and speed", k2(v_cmd=P1.v_max, delta=P1.steer_max), 0),
                 ("b3 clear, v_cmd 0", k2(v_cmd=0.0, delta=-P1.steer_max), 0),
                 ("b3 clear, v_cmd negative", k2(v_cmd=-P1.v_max), 0)])


def _pairs():
    """(the two rules, a frame failing both, the frame failing the second alone), profile 1."""
    d, nan = CTL.dt_max_ms, Raw(QNAN)
    p = P1
    return [
        ((10, 8), setp(k2(profile=0), P_RESERVED, b"\x01"), k2(profile=0)),
        ((8, 9), k2(profile=0, v_cmd=nan), k2(v_cmd=nan)),
        ((9, 11), k2(v_cmd=nan, interval=d + 1), k2(interval=d + 1)),
        ((11, 12), k2(v_cmd=up(p.v_max), interval=d + 1), k2(v_cmd=up(p.v_max))),
        ((12, 13), k2(v_cmd=up(p.v_max), acc=up(p.a_max)), k2(acc=up(p.a_max))),
        ((13, 14), k2(acc=up(p.a_max), jerk=up(p.jerk_max)), k2(jerk=up(p.jerk_max))),
        ((14, 15), k2(jerk=up(p.jerk_max), delta=up(p.steer_max)), k2(delta=up(p.steer_max))),
        ((15, 16), k2(delta=up(p.steer_max), rate=up(p.steer_rate_max)), k2(rate=up(p.steer_rate_max))),
        ((16, 17), k2(rate=up(p.steer_rate_max), delta=p.steer_max, v_cmd=10.0, v_meas=10.0),
         k2(delta=p.steer_max, v_cmd=10.0, v_meas=10.0)),
        ((17, 18), k2(delta=p.steer_max, v_cmd=1.0, v_meas=10.0), k2(v_cmd=1.0, v_meas=10.0)),
        ((18, 19), k2(v_cmd=0.0, v_meas=-10.0), k2(v_cmd=0.0, v_meas=-2.0)),
    ]


def test_the_order_between_every_adjacent_pair_of_rules(ctl):
    pairs = _pairs()
    assert [x[0] for x in pairs] == list(zip(ORDER, ORDER[1:]))
    cases = []
    for (first, second), both, alone in pairs:
        cases.append(("%d before %d" % (first, second), both, first))
        cases.append(("%d alone" % second, alone, second))
    expect(ctl, cases)


def _failing_from(k):
    """A frame that fails every rule from k on (in ORDER), as far as one frame can: 9 is a NaN in the jerk slot, so a
    frame failing 9 cannot also fail 14; 15 takes an angle over steer_max, so such a frame cannot also fail 17."""
    fail = set(ORDER[ORDER.index(k):])
    p = P1
    kw = dict(profile=0 if 8 in fail else 1, v_cmd=up(p.v_max) if 12 in fail else 1.0,
              interval=CTL.dt_max_ms + 1 if 11 in fail else 0)
    if 9 in fail:
        kw["jerk"] = Raw(QNAN)
    elif 14 in fail:
        kw["jerk"] = up(p.jerk_max)
    if 13 in fail:
        kw["acc"] = up(p.a_max)
    kw["delta"] = up(p.steer_max) if 15 in fail else (p.steer_max if 17 in fail else 0.0)
    if 16 in fail:
        kw["rate"] = up(p.steer_rate_max)
    if 18 in fail:
        kw["v_meas"] = -40.0
    elif 19 in fail:
        kw["v_meas"] = -2.0
    elif 17 in fail:
        kw["v_meas"] = 10.0
    fr = k2(**kw)
    return setp(fr, P_RESERVED, b"\x01") if 10 in fail else fr


def test_every_rule_from_k_on_failing_gives_k(ctl):
    expect(ctl, [("every rule from %d on" % k, _failing_from(k), k) for k in ORDER])


def _random_k2(rng, seq):
    """A kind 2 frame drawn around the fixture's edges: limits and their next binary32, non-finite patterns, -0.0,
    undefined slots with bytes in them, reserved bits and bytes, unbound profiles, intervals at DT_MAX_MS."""
    pid = rng.choice([1, 1, 2, 2, 0, 3, 255])
    pr = CTL.profiles.get(pid, P1)
    lim = {"v_cmd": pr.v_max, "acc": pr.a_max, "jerk": pr.jerk_max, "delta": pr.steer_max, "rate": pr.steer_rate_max,
           "v_meas": 12.0}
    kw = {}
    for name in SLOT:
        if name in OPTIONAL and rng.random() < 0.3:
            continue
        r = rng.random()
        if r < 0.04:
            kw[name] = Raw(rng.choice(list(NONFINITE.values())))
        elif r < 0.08:
            kw[name] = Raw(0x80000000)
        elif r < 0.4:
            x = rng.choice([lim[name], up(lim[name])])
            kw[name] = x if rng.random() < 0.5 else -x
        else:
            kw[name] = vf.f32(rng.uniform(-1.3 * lim[name], 1.3 * lim[name]))
    interval = rng.choice([0, 33, CTL.dt_max_ms, CTL.dt_max_ms + 1, 0xFFFF, rng.randrange(0x10000)])
    fr = k2(seq=seq, profile=pid, interval=interval, **kw)
    r = rng.random()
    if r < 0.03:
        fr = setp(fr, P_FLAGS, bytes((fr[H + P_FLAGS] | (1 << rng.randrange(4, 8)),)))
    elif r < 0.06:
        fr = setp(fr, rng.choice(list(range(8, 24)) + [P_RESERVED]), bytes((rng.randrange(1, 256),)))
    elif r < 0.09:
        name = rng.choice(OPTIONAL)
        if name not in kw:
            fr = setp(fr, SLOT[name][0], struct.pack("<I", rng.choice([0x80000000, QNAN, 1, bits(1.0)])))
    return fr


def test_seeded_random_frames_match_the_reference(ctl):
    rng = random.Random(20261018)
    frames = [_random_k2(rng, i + 1) for i in range(4000)]
    got = judge(ctl, frames)
    bad = [(f.hex(), g, ref_judge(f)) for f, g in zip(frames, got) if (g[0], g[1]) != ref_judge(f) or g[2] != NAMES[g[1]]]
    assert not bad, bad[:5]
    seen = collections.Counter(g[1] for g in got)
    assert set(seen) == {0} | set(ORDER), "the corpus reaches every reason: %s" % sorted(seen.items())


@pytest.mark.parametrize("kind", [3, 7, 255])
def test_an_unknown_kind_of_the_ctl_build_is_reason_5(ctl, kind):
    # kind 3 is not built, so it stays unknown in the ctl build: the ctl build's unknown-kind parameter is [3, 7, 255]
    frames = [k2(kind=kind), k2(kind=kind, v_cmd=Raw(QNAN), profile=0), mc.vlm(1, kind=kind)]
    assert judge(ctl, frames) == [(1, 5, "claim-kind-unknown")] * len(frames)


# ============================================================ kind 2 among the kinds

def _kind4_frames():
    """Kind 4 frames encoded with sdv/frame/vssframe.py: an honest one, then one per kind 4 reason (each checked with
    rules.judge_frame), under the first compiled profile."""
    c = c4()
    t = rules.Tables.from_contract(c)
    pid = c.COMPILED_PROFILE_IDS[0]
    pr = t.profiles[pid]

    def enc(seq, **kw):
        base = dict(v=5.0, a_x=0.0, delta=0.0, psi_dot=0.0, gear=1)
        base.update(kw)
        profile = base.pop("profile", pid)
        return vf.encode(vf.Claim(seq=seq, tstamp_ns=0, profile=profile, **base), c)

    def honest(seq):
        return enc(seq)

    rejects = {
        8: lambda s: enc(s, profile=0),
        9: lambda s: vf.pack_bits(s, 0, pid, c.CATALOG_DIGEST, [QNAN, 0, 0, 0], 1, 0),
        10: lambda s: setp(enc(s), 0, b"\x3f"),
        21: lambda s: enc(s, digest=c.CATALOG_DIGEST ^ 1),
        22: lambda s: enc(s, age_ms=c.AGE_MAX_MS + 1),
        23: lambda s: enc(s, v=up(pr.v_max)),
        24: lambda s: enc(s, a_x=up(pr.a_max)),
        25: lambda s: enc(s, delta=up(pr.delta_max)),
        26: lambda s: enc(s, psi_dot=pr.tol26 * 10.0),
        27: lambda s: enc(s, gear=-1),
    }
    for reason, make in rejects.items():
        assert rules.judge_frame(make(1), t)[1] == reason, reason
    assert rules.judge_frame(honest(1), t) == (0, 0)
    return honest, rejects, t


def _random_k4(rng, n):
    c = c4()
    pid = c.COMPILED_PROFILE_IDS[0]
    out = []
    while len(out) < n:
        slots = []
        for _ in range(4):
            r = rng.random()
            if r < 0.2:
                slots.append(None)
            elif r < 0.25:
                slots.append(rng.choice(list(NONFINITE.values())))
            elif r < 0.3:
                slots.append(0x80000000)
            else:
                slots.append(vf.f32_bits(rng.uniform(-60.0, 60.0)))
        gear = None if rng.random() < 0.2 else rng.randrange(-2, 3)
        present = gear is not None or any(s is not None for s in slots)
        age = rng.choice([0, 10, c.AGE_MAX_MS, c.AGE_MAX_MS + 1, 0xFFFF]) if present else 0
        profile = rng.choice([pid, pid, pid, 0, 2, 3, 255])
        digest = c.CATALOG_DIGEST if rng.random() < 0.9 else rng.randrange(1 << 32)
        fr = vf.pack_bits(len(out) + 1, 0, profile, digest, slots, gear, age)
        if rng.random() < 0.05:
            fr = setp(fr, rng.choice([8, 20, 44, 47]), b"\x01")
        out.append(fr)
    return out


def test_kind_4_frames_get_the_vss_builds_verdicts_in_the_ctl_build(ctl, vss):
    honest, rejects, t = _kind4_frames()
    frames = [honest(1)] + [make(i + 2) for i, make in enumerate(rejects.values())] + _random_k4(random.Random(2410), 600)
    a, b = judge(ctl, frames), judge(vss, frames)
    assert a == b
    assert [(v, r) for v, r, _ in a] == [rules.judge_frame(f, t) for f in frames]
    assert {r for _, r, _ in a} >= {0, 8, 9, 10, 21, 22, 23, 24, 25, 26, 27}


def test_kind_2_stays_unknown_in_the_vss_build(vss):
    frames = [k2(), k2(v_cmd=up(P1.v_max)), k2(profile=0), setp(k2(), P_RESERVED, b"\x01")]
    assert judge(vss, frames) == [(1, 5, "claim-kind-unknown")] * len(frames)


def _udp_session(binary, frames, pause=None):
    """One UDP session: the replies (hex), and stdout normalised, after a SIGTERM that the monitor honours. pause:
    (n, seconds), that long a silence before frame n."""
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


def test_kind_4_frames_reply_and_print_in_the_ctl_build_as_in_the_vss_build(ctl, vss):
    # Every reject follows an ACCEPT, so rule 1 prints each, and ten rejects stay under kind 4's cap of 11: no line
    # depends on where the PC's clock puts a bucket edge.
    honest, rejects, _ = _kind4_frames()
    frames, seq = [], 1
    for make in rejects.values():
        frames += [honest(seq), make(seq + 1)]
        seq += 2
    a_rep, a_out = _udp_session(ctl["monitor"], frames)
    b_rep, b_out = _udp_session(vss["monitor"], frames)
    assert a_rep == b_rep and None not in a_rep
    assert _from_banner(a_out) == _from_banner(b_out)
    assert sum(1 for ln in a_out if ln.startswith("monitor: REJECT seq=") and " kind=vss " in ln) == len(rejects)


def test_kinds_0_and_1_and_the_unknown_kinds_reply_and_print_as_in_the_default_build(ctl, default_monitor):
    frames = [f for _, f, _ in mc.corpus() if f[H + P_KIND] != 2] + [mc.vlm(600 + k, kind=k) for k in (3, 7, 255)]
    a_rep, a_out = _udp_session(ctl["monitor"], frames)
    b_rep, b_out = _udp_session(default_monitor, frames)
    assert a_rep == b_rep and None not in a_rep
    assert _from_banner(a_out) == _from_banner(b_out)
    for k in (3, 7, 255):
        assert "monitor: REJECT seq=%d kind=%d reason=claim-kind-unknown\n" % (600 + k, k) in a_out


# ============================================================ the console: opening lines and the self-check

def ctl_announcement(c=None):
    """2.5's two formats for the contract c (the fixture's when None): the ctl rules line, then one ctl profile line
    per compiled id."""
    c = CTL if c is None else c
    out = [CTL_RULES_LINE % (c.digest, c4().VSS_VERSION, c.dt_max_ms, c.overspeed_factor, c.overspeed_margin,
                             c.rollback_v, c.tol17, " ".join(str(i) for i in c.profiles))]
    out += [CTL_PROFILE_LINE % tuple(p) for p in c.profiles.values()]
    return out


def _opening(binary, mode, workdir):
    """A monitor's stdout from its start through its banner, in one serving mode, the port and slot normalised."""
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
def test_the_opening_lines_in_every_serving_mode(ctl, vss, mode, tmp_path):
    base = _opening(vss["monitor"], mode, tmp_path / "vss")
    got = _opening(ctl["monitor"], mode, tmp_path / "ctl")
    assert base[0] == CLAIM_KINDS and base[1].startswith("monitor: vss rules: kind 4, "), base
    k = max(i for i, ln in enumerate(base) if ln.startswith("monitor: vss profile ")) + 1
    assert got == base[:k] + ctl_announcement() + base[k:]
    assert [ln for ln in got if "claim kinds:" in ln] == [CLAIM_KINDS]


def _refusal(binary, words, tmp_path):
    """A monitor's exit code, stdout and stderr in one serving mode (<port> a free port, <slot> a fresh slot file). A
    monitor that serves instead of refusing runs into the timeout, and is killed."""
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


SERVING = [["<port>", "udp"], ["<port>"], ["<port>", "stamp"], ["<port>", "svc", "500"], ["shm", "<slot>"]]


@pytest.mark.parametrize("words", SERVING, ids=["udp", "tcp", "stamp", "svc", "shm"])
def test_a_bad_digest_refuses_to_serve_before_any_serving_line(bad_digest, words, tmp_path):
    assert _refusal(bad_digest, words, tmp_path) == (2, b"", INCONSISTENT)


def test_a_digest_that_differs_in_its_high_bit_only_refuses_to_serve(tmp_path):
    # The bad-digest twin differs from the fixture in bit 0, so a self-check that compared only the low 16 bits of the
    # digest would still refuse it; this one differs in bit 31.
    d = _fixture_variant(tmp_path, "#define VSS_CTL_DIGEST 0x%08Xu" % CTL.digest,
                         "#define VSS_CTL_DIGEST 0x%08Xu" % (CTL.digest ^ 0x80000000))
    mon = _build(tmp_path, CTL_FLAGS, ctl_dir=d, names=("monitor",))["monitor"]
    assert _refusal(mon, ["<port>", "udp"], tmp_path) == (2, b"", INCONSISTENT)


def test_the_self_check_hashes_the_seven_uids_by_shifts_with_fnv1(ctl):
    rng = random.Random(7)
    vectors = [CTL.uids, (0,) * 7, (0xFFFFFFFF,) * 7,
               (0x01020304, 0x0A1B2C3D, 0xDEADBEEF, 0x12345678, 0x9ABCDEF0, 0x00000001, 0x80000000)]
    vectors += [tuple(rng.randrange(1 << 32) for _ in range(7)) for _ in range(30)]
    out = _run(ctl["driver"], "uids", [" ".join("%08X" % u for u in v) for v in vectors])
    assert [int(x, 16) for x in out] == [vf.digest_of(v) for v in vectors]
    # the order of the bytes matters: a serialisation by copying a u32 would follow the host's byte order
    swapped = vf.fnv1_32(b"".join(struct.pack(">I", u) for u in vectors[3]))
    assert swapped != int(out[3], 16)
    assert _run(ctl["driver"], "selfcheck") == ["computed %08X header %08X consistent 1" % (CTL.digest, CTL.digest)]


def _fixture_variant(tmp_path, old, new):
    text = (FIXTURE / "vss_ctl.h").read_text(encoding="ascii")
    assert text.count(old) == 1, old
    d = tmp_path / "ctl"
    d.mkdir()
    (d / "vss_ctl.h").write_text(text.replace(old, new), encoding="ascii")
    return d


def _contract_variant(d, consts=(), rows=None):
    """The fixture header written into the new directory d with some of 2.4's #defines given other values (consts:
    (name, literal) pairs) and, when rows is given, the profile table, VSS_CTL_PROFILE_COUNT and VSS_CTL_PROFILE_IDS
    made of those rows ((id, l_mm, the six doubles) each; a double written with repr, which reads back exactly). The
    UIDs and the digest stay the fixture's. Returns d."""
    text = (FIXTURE / "vss_ctl.h").read_text(encoding="ascii")
    if rows is not None:
        table = "#define VSS_CTL_PROFILE_TABLE(X)" + "".join(
            " \\\n    X(%du, %du, %s)" % (r[0], r[1], ", ".join(repr(float(x)) for x in r[2:])) for r in rows)
        text, n = re.subn(r"^#define VSS_CTL_PROFILE_TABLE\(X\)(?: \\\n    X\([^\n]*\))+$", lambda m: table, text,
                          flags=re.M)
        assert n == 1
        text, n = re.subn(r'^#define VSS_CTL_PROFILE_IDS "[^"]*"$',
                          lambda m: '#define VSS_CTL_PROFILE_IDS "%s"' % " ".join(str(r[0]) for r in rows), text, flags=re.M)
        assert n == 1
        consts = tuple(consts) + (("VSS_CTL_PROFILE_COUNT", "%du" % len(rows)),)
    for name, value in consts:
        line = "#define %s %s" % (name, value)
        text, n = re.subn(r"^#define %s \S+$" % name, lambda m, line=line: line, text, flags=re.M)
        assert n == 1, name
    d.mkdir()
    (d / "vss_ctl.h").write_text(text, encoding="ascii")
    return d


@pytest.mark.parametrize("row", [1, 2])
@pytest.mark.parametrize("steer", ["1.5", "1.0000000000000002", "0.0", "-0.5"])
def test_a_compiled_profile_with_steer_max_outside_0_to_1_rad_refuses_to_serve(steer, row, tmp_path):
    # WP1a's decision: the C self-check holds 2.3's invariant (0 < steer_max <= 1.0 rad, so vss_tan stays in its
    # domain) as the Python loader of 2.4 does; a hand-edited header cannot serve with it broken, in either row (a
    # check that started its loop at the second row would pass the first).
    rows = [tuple(p) for p in CTL.profiles.values()]
    rows[row - 1] = rows[row - 1][:5] + (float(steer),) + rows[row - 1][6:]
    d = _contract_variant(tmp_path / "contract", rows=rows)
    mon = _build(tmp_path, CTL_FLAGS, ctl_dir=d, names=("monitor",))["monitor"]
    assert _refusal(mon, ["<port>", "udp"], tmp_path) == (2, b"", INCONSISTENT)


@pytest.mark.parametrize("edit", ["row 1 l_mm 0", "row 2 l_mm 0", "row 2 with row 1's id"])
def test_a_compiled_profile_with_l_mm_0_or_an_id_twice_refuses_to_serve(edit, tmp_path):
    # WP1a's decision, as for steer_max: the self-check holds what the judge needs to be defined. Rule 17 divides by
    # L_m, so an l_mm of 0 would judge a NaN (accepted) or an infinity; ctl_profile_find() would only ever find the
    # first of two rows that share an id. A contract WP1b generates is to have neither.
    rows = [tuple(p) for p in CTL.profiles.values()]
    if edit == "row 1 l_mm 0":
        rows[0] = rows[0][:1] + (0,) + rows[0][2:]
    elif edit == "row 2 l_mm 0":
        rows[1] = rows[1][:1] + (0,) + rows[1][2:]
    else:
        rows[1] = rows[0][:1] + rows[1][1:]
    d = _contract_variant(tmp_path / "contract", rows=rows)
    builds = _build(tmp_path, CTL_FLAGS, ctl_dir=d)
    assert _run(builds["driver"], "selfcheck") == ["computed %08X header %08X consistent 0" % (CTL.digest, CTL.digest)]
    assert _refusal(builds["monitor"], ["<port>", "udp"], tmp_path) == (2, b"", INCONSISTENT)


@pytest.mark.parametrize("edit", ["count", "id 0", "id 256"])
def test_a_table_whose_count_or_an_id_is_wrong_does_not_compile(edit, tmp_path):
    # WP1a's decision: as kind 4's table, every id 1..255 at compile time; and VSS_CTL_PROFILE_COUNT the row count.
    # Id 256 is built without -Werror, as the Makefile builds: there -Woverflow does not stop it, the id check must.
    gcc = _gcc()
    _need_gen()
    if edit == "count":
        d = _fixture_variant(tmp_path, "#define VSS_CTL_PROFILE_COUNT 2u\n", "#define VSS_CTL_PROFILE_COUNT 3u\n")
        want = "VSS_CTL_PROFILE_COUNT is the number of rows of VSS_CTL_PROFILE_TABLE"
    else:
        d = _fixture_variant(tmp_path, "X(2u, 2790u,", "X(%su, 2790u," % edit[3:])
        want = "a ctl profile id is 1..255: id 0 is never bound"
    r = _compile(gcc, PLAIN_CTL_FLAGS if edit == "id 256" else CTL_FLAGS, tmp_path / "unit.o", MONITOR_C, ctl_dir=d,
                 link=False)
    assert r.returncode != 0 and want in r.stderr, r.stderr


@pytest.mark.parametrize("dt_max", ["65535u", "70000u"])
def test_a_dt_max_ms_that_the_saturated_interval_cannot_exceed_does_not_compile(dt_max, tmp_path):
    # WP1a's decision: the interval saturates at 0xFFFF (2.2), the first Control after a silence carries it, and rule 11
    # must reject it, so VSS_CTL_DT_MAX_MS is below 0xFFFF. At 0xFFFF or above rule 11 could never fire; gcc says so
    # only in a -Wextra warning (-Wtype-limits), and the Makefile builds without -Werror, so that image would serve.
    # monitor.c makes it a compile error, whatever the warning flags (none here).
    gcc = _gcc()
    _need_gen()
    d = _contract_variant(tmp_path / "contract", (("VSS_CTL_DT_MAX_MS", dt_max),))
    r = _compile(gcc, PLAIN_CTL_FLAGS, tmp_path / "unit.o", MONITOR_C, ctl_dir=d, link=False)
    assert r.returncode != 0 and DT_MAX_ERROR in r.stderr, r.stderr


def test_a_dt_max_ms_of_0xFFFE_compiles_and_still_rejects_the_saturated_interval(tmp_path):
    d = _contract_variant(tmp_path / "contract", (("VSS_CTL_DT_MAX_MS", "65534u"),))
    builds = _build(tmp_path, CTL_FLAGS, ctl_dir=d)
    assert judge(builds, [k2(interval=0xFFFE), k2(interval=0xFFFF)]) == [(0, 0, "ok"), (1, 11, "ctl-interval")]


def test_the_vss_self_check_comes_before_the_ctl_one(tmp_path):
    _need_gen()
    gen = tmp_path / "gen"
    gen.mkdir()
    for h in GEN_HEADERS:
        shutil.copy2(str(GEN / h), str(gen / h))
    text = (gen / "vss_contract.h").read_text(encoding="ascii")
    m = re.search(r"^#define VSS_CATALOG_DIGEST 0x([0-9A-F]{8})u$", text, re.M)
    assert m is not None
    (gen / "vss_contract.h").write_text(text.replace(m.group(0), "#define VSS_CATALOG_DIGEST 0x%08Xu"
                                                     % (int(m.group(1), 16) ^ 1)), encoding="ascii")
    mon = _build(tmp_path, CTL_FLAGS, ctl_dir=BAD_DIGEST, gen=gen, names=("monitor",))["monitor"]
    assert _refusal(mon, ["<port>", "udp"], tmp_path) == (2, b"", VSS_INCONSISTENT)


def test_a_vss_ctl_h_in_the_gen_directory_does_not_stand_in_for_the_fixtures(tmp_path):
    """WP1b generates a vss_ctl.h into sdv-out/gen beside the kind 4 headers. A copy of gen with a vss_ctl.h of another
    DT_MAX_MS (and a consistent digest) stands for it: the builds of this file still compile the header they name, the
    fixture or the bad-digest twin, because their directory comes before gen on the include path."""
    _need_gen()
    gen = tmp_path / "gen"
    gen.mkdir()
    for h in GEN_HEADERS:
        shutil.copy2(str(GEN / h), str(gen / h))
    old = "#define VSS_CTL_DT_MAX_MS %du\n" % CTL.dt_max_ms
    text = (FIXTURE / "vss_ctl.h").read_text(encoding="ascii")
    assert text.count(old) == 1
    (gen / "vss_ctl.h").write_text(text.replace(old, "#define VSS_CTL_DT_MAX_MS %du\n" % (CTL.dt_max_ms + 100)),
                                   encoding="ascii")
    (tmp_path / "fixture").mkdir()
    (tmp_path / "bad").mkdir()
    builds = _build(tmp_path / "fixture", CTL_FLAGS, gen=gen)
    lines = dict(ln.split(" ", 1) for ln in _run(builds["driver"], "constants") if not ln.startswith("profile "))
    assert int(lines["dt_max_ms"]) == CTL.dt_max_ms
    bad = _build(tmp_path / "bad", CTL_FLAGS, ctl_dir=BAD_DIGEST, gen=gen, names=("monitor",))["monitor"]
    assert _refusal(bad, ["<port>", "udp"], tmp_path) == (2, b"", INCONSISTENT)


# ============================================================ a contract off the binary32 grid

# Every limit and the four constants of the fixture are binary32 values, so a limit held in binary32 instead of double,
# a bound rounded to binary32, or a limit printed with too few digits would judge and print the fixture exactly as 2.3
# and 2.5 do. In this variant none of them is a binary32 value (and the four constants are pairwise distinct); some
# round up to binary32 and some down. Synthetic values, as the fixture's.
ODD_CONSTS = (("VSS_CTL_TOL17", "0.35"), ("VSS_CTL_OVERSPEED_FACTOR", "1.15"), ("VSS_CTL_OVERSPEED_MARGIN", "0.85"),
              ("VSS_CTL_ROLLBACK_V", "0.55"))
ODD_ROWS = ((1, 2789, 13.9, 3.3, 0.7, 0.61, 0.33, 1.7), (2, 3911, 2.9, 1.3, 9.1, 0.47, 0.21, 1.1))


@pytest.fixture(scope="module")
def odd(tmp_path_factory):
    """The ctl build and its driver against the variant off the binary32 grid, and that contract as Ctl reads it."""
    d = _contract_variant(tmp_path_factory.mktemp("odd") / "contract", ODD_CONSTS, ODD_ROWS)
    return _build(d.parent, CTL_FLAGS, ctl_dir=d), Ctl(d / "vss_ctl.h")


def test_the_variant_off_the_binary32_grid_is_compiled_and_announced_as_written(odd, vss, tmp_path):
    builds, c = odd
    limits = [x for p in c.profiles.values() for x in p[2:]]
    consts = [c.tol17, c.overspeed_factor, c.overspeed_margin, c.rollback_v]
    assert [tuple(p) for p in c.profiles.values()] == [tuple(r) for r in ODD_ROWS]
    assert all(vf.f32(x) != x for x in limits + consts) and len(set(consts)) == 4
    assert {vf.f32(x) > x for x in limits} == {True, False}, "limits that round up to binary32 and limits that round down"
    out = _run(builds["driver"], "constants")
    lines = dict(ln.split(" ", 1) for ln in out if not ln.startswith("profile "))
    assert [float.fromhex(x) for x in lines["consts"].split()] == consts
    rows = [ln.split()[1:] for ln in _run(builds["driver"], "table") if ln.startswith("row ")]
    assert [Prof(int(r[0]), int(r[1]), *(float.fromhex(x) for x in r[2:])) for r in rows] == list(c.profiles.values())
    base = _opening(vss["monitor"], "udp", tmp_path / "vss")
    got = _opening(builds["monitor"], "udp", tmp_path / "odd")
    k = max(i for i, ln in enumerate(base) if ln.startswith("monitor: vss profile ")) + 1
    assert got == base[:k] + ctl_announcement(c) + base[k:]


@pytest.mark.parametrize("pid", [r[0] for r in ODD_ROWS])
def test_each_limit_off_the_binary32_grid_is_accepted_at_its_last_binary32_and_rejected_one_step_above(odd, pid):
    builds, c = odd
    pr = c.profiles[pid]
    cases = []
    for rule, slot, field in LIMITS:
        lim = getattr(pr, field)
        edge = f32_floor(lim)
        assert edge < lim < up(edge)
        for sign in (1.0, -1.0):
            cases.append(("%s = %r (limit %r)" % (slot, sign * edge, lim), k2(profile=pid, **{slot: sign * edge}), 0))
            cases.append(("%s = %r (limit %r)" % (slot, sign * up(edge), lim), k2(profile=pid, **{slot: sign * up(edge)}),
                          rule))
    expect(builds, cases, c)


@pytest.mark.parametrize("pid", [r[0] for r in ODD_ROWS])
def test_rule_17_off_the_binary32_grid_at_its_edge_against_the_bound_in_double(odd, pid):
    """At steer_max's last binary32, and at the first angle down from it (in steps of a 64th of steer_max) at which a
    bound rounded to binary32 would judge one of the two edge frames otherwise: found here by search."""
    builds, c = odd
    pr = c.profiles[pid]
    l_m = pr.l_mm * c4().M_PER_MM
    bound = pr.lat_acc_max + c.tol17
    assert vf.f32(bound) != bound

    def edge(ad):
        t = rules.vss_tan(ad)

        def x(v):
            return v * v * t / l_m
        v = last_f32(lambda q: not x(q) > bound)
        assert not x(v) > bound and x(up(v)) > bound
        return v, x

    def quiet_18(v):
        return not v > c.overspeed_factor * min(v, f32_floor(pr.v_max)) + c.overspeed_margin

    angles = [f32_floor(pr.steer_max)]
    for i in range(64, 0, -1):
        ad = f32_floor(pr.steer_max * i / 64)
        v, x = edge(ad)
        if quiet_18(v) and (x(v) > vf.f32(bound), x(up(v)) > vf.f32(bound)) != (False, True):
            angles.append(ad)
            break
    assert len(angles) == 2, "no angle found at which a bound in binary32 would judge the edge otherwise"
    cases = []
    for ad in angles:
        v, _ = edge(ad)
        assert quiet_18(v), "rule 18 must not fire at the edge"
        for d_sign in (1.0, -1.0):
            for m_sign in (1.0, -1.0):
                v_cmd = m_sign * min(v, f32_floor(pr.v_max))
                label = "delta %r v_cmd %r v_meas %r" % (d_sign * ad, v_cmd, m_sign * v)
                cases.append((label, k2(profile=pid, v_cmd=v_cmd, delta=d_sign * ad, v_meas=m_sign * v), 0))
                cases.append((label + " + one step", k2(profile=pid, v_cmd=v_cmd, delta=d_sign * ad,
                                                        v_meas=m_sign * up(v)), 17))
    expect(builds, cases, c)


def test_rules_18_and_19_off_the_binary32_grid_at_their_thresholds(odd):
    builds, c = odd
    v_cmds = [0.0, 2.5, f32_floor(2.9), 5.0, f32_floor(13.9)]          # binary32 commands within profile 1's v_max
    bounds = [c.overspeed_factor * v + c.overspeed_margin for v in v_cmds]
    assert all(vf.f32(b) != b for b in bounds)
    assert {vf.f32(b) > b for b in bounds} == {True, False}, "bounds that round up to binary32 and bounds that round down"
    cases = []
    for v_cmd, bound in zip(v_cmds, bounds):
        v = f32_floor(bound)
        for c_sign, m_sign in ((1.0, 1.0), (-1.0, -1.0), (-1.0, 1.0), (1.0, -1.0)):
            cmd = c_sign * v_cmd
            at = 19 if (m_sign < 0 and cmd >= 0.0) else 0
            cases.append(("v_cmd %r v_meas %r" % (cmd, m_sign * v), k2(v_cmd=cmd, v_meas=m_sign * v), at))
            cases.append(("v_cmd %r v_meas %r" % (cmd, m_sign * up(v)), k2(v_cmd=cmd, v_meas=m_sign * up(v)), 18))
    edge = f32_floor(c.rollback_v)
    assert vf.f32(c.rollback_v) > c.rollback_v, "a ROLLBACK_V that rounds up, so that one held in binary32 is seen"
    for v_cmd in (0.0, -0.0, 1.0, -1.0):
        back = 19 if v_cmd >= 0.0 else 0
        cases.append(("v_cmd %r v_meas %r" % (v_cmd, -edge), k2(v_cmd=v_cmd, v_meas=-edge), 0))
        cases.append(("v_cmd %r v_meas %r" % (v_cmd, -up(edge)), k2(v_cmd=v_cmd, v_meas=-up(edge)), back))
    expect(builds, cases, c)


# ============================================================ the limiter (2.5)

def ev(now, seq, reason, profile=1):
    return "F %d %d %d %d" % (now, seq, profile, reason)


def limiter_model(events, cap=CAP):
    """2.5's limiter, kind 4's four rules with kind 2's own state and cap, written from the specification and not from
    monitor.c: a REJECT line only when the reason differs from the previous frame's (an ACCEPT is 0); buckets of one
    second; at most `cap` lines a bucket, the rest counted; one summary for a bucket with a suppressed line, at the
    next bucket's first frame or at the session end, its counters the bucket's own; the session end resets all."""
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


def test_one_reason_persisting_prints_one_line_and_its_buckets_summary(ctl):
    events = [ev(i * 10 * MS, i + 1, 12) for i in range(100)] + [END]
    check_log(ctl, events, [REJECT_LINE % (1, 1, "ctl-speed"), SUMMARY_LINE % (100, 100, 99, " 12=99")])


def test_34_alternating_rejects_in_a_bucket_all_print_and_a_35th_goes_into_the_summary(ctl):
    alt = [12 if i % 2 == 0 else 13 for i in range(35)]
    lines34 = [REJECT_LINE % (i + 1, 1, NAMES[alt[i]]) for i in range(34)]
    check_log(ctl, [ev(i * 29 * MS, i + 1, alt[i]) for i in range(34)] + [END], lines34)
    check_log(ctl, [ev(i * 28 * MS, i + 1, alt[i]) for i in range(35)] + [END], lines34 + [SUMMARY_LINE % (35, 35, 1, " 12=1")])


def test_rule_1_compares_with_the_previous_frame_and_an_accept_is_reason_0(ctl):
    check_log(ctl, [ev(0, 1, 12), ev(MS, 2, 0), ev(2 * MS, 3, 12), ev(3 * MS, 4, 12), END],
              [REJECT_LINE % (1, 1, "ctl-speed"), REJECT_LINE % (3, 1, "ctl-speed"), SUMMARY_LINE % (4, 3, 1, " 12=1")])
    # At the cap the 35th frame (12) is suppressed; the next bucket's first 12 is then a repeat of the previous FRAME,
    # although the last line printed was a 13.
    alt = [12 if i % 2 == 0 else 13 for i in range(35)]
    events = [ev(i * 28 * MS, i + 1, alt[i]) for i in range(35)] + [ev(S + 10 * MS, 36, 12), ev(S + 20 * MS, 37, 13), END]
    want = ([REJECT_LINE % (i + 1, 1, NAMES[alt[i]]) for i in range(34)] + [SUMMARY_LINE % (35, 35, 1, " 12=1")]
            + [REJECT_LINE % (37, 1, "ctl-accel"), SUMMARY_LINE % (2, 2, 1, " 12=1")])
    check_log(ctl, events, want)


def test_the_session_end_flush_resets_rule_1_and_the_line_count(ctl):
    alt = [12 if i % 2 == 0 else 13 for i in range(34)]                  # ends on 13, the cap reached
    events = [ev(i * 28 * MS, i + 1, alt[i]) for i in range(34)] + [END] + [ev(990 * MS, 35, 13), ev(991 * MS, 36, 12), END]
    want = [REJECT_LINE % (i + 1, 1, NAMES[alt[i]]) for i in range(34)] + [REJECT_LINE % (35, 1, "ctl-accel"),
                                                                          REJECT_LINE % (36, 1, "ctl-speed")]
    check_log(ctl, events, want)
    check_log(ctl, [END, END], [])                                     # nothing pending: nothing printed


def test_a_summary_pending_at_a_bucket_edge_is_printed_once(ctl):
    events = [ev(900 * MS, 1, 16), ev(950 * MS, 2, 16), ev(1100 * MS, 3, 16), ev(1150 * MS, 4, 16), END]
    check_log(ctl, events, [REJECT_LINE % (1, 1, "ctl-steer-rate"), SUMMARY_LINE % (2, 2, 1, " 16=1"),
                            SUMMARY_LINE % (2, 2, 2, " 16=2")])
    events = [ev(10 * MS, 1, 17, 2), ev(20 * MS, 2, 17, 2), ev(5 * S, 3, 0, 2), END]
    check_log(ctl, events, [REJECT_LINE % (1, 2, "ctl-lat-accel"), SUMMARY_LINE % (2, 2, 1, " 17=1")])


def test_the_summary_counts_the_buckets_frames_and_lists_its_suppressed_reasons_in_order(ctl):
    reasons = [13, 13, 12, 12, 19, 19, 0]
    events = [ev(i * MS, i + 1, r) for i, r in enumerate(reasons)] + [END]
    want = [REJECT_LINE % (1, 1, "ctl-accel"), REJECT_LINE % (3, 1, "ctl-speed"), REJECT_LINE % (5, 1, "ctl-rolling-back"),
            SUMMARY_LINE % (7, 6, 3, " 12=1 13=1 19=1")]
    check_log(ctl, events, want)


def test_the_limiter_matches_the_model_on_seeded_streams(ctl):
    rng = random.Random(3402)
    for _ in range(20):
        events, t, seq = [], rng.randrange(3 * S), 1
        for _ in range(rng.randrange(50, 600)):
            if rng.random() < 0.02:
                events.append(END)
                continue
            t += rng.choice((0, 1 * MS, 1 * MS, 10 * MS, 30 * MS, rng.randrange(1500 * MS)))
            events.append(ev(t, seq, rng.choice((0, 0, 8, 9, 10, 11, 12, 12, 13, 14, 15, 16, 17, 18, 19)), rng.choice((1, 2, 0))))
            seq += 1
        events.append(END)
        got = _run(ctl["driver"], "log", events)
        assert got == limiter_model(events)
        rejects = sum(1 for e in events if e != END and not e.endswith(" 0"))
        supp = sum(int(re.search(r"suppressed=(\d+)", ln).group(1)) for ln in got if ln.startswith("monitor: ctl summary:"))
        assert sum(1 for ln in got if ln.startswith("monitor: REJECT")) + supp == rejects


# ============================================================ the text of monitor.c

CTL_HOOK = [GUARD, "ctl_log_end(&g_ctl_log);", "#endif"]
VSS_HOOK = ["#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)", "vss_log_end(&g_vss_log);", "#endif"]
SESSION_END_PRINTS = ('printf("monitor: client done:', 'printf("monitor: udp done:', 'printf("monitor: shm quiet:',
                      'printf("monitor: shm done:', 'printf("monitor: shm-kick burst:', 'printf("monitor: shm-kick done:')


def test_each_ctl_flush_hook_stands_right_before_the_vss_hook_of_each_session_end():
    """2.5: seven session-end prints (two client done:, one each of the rest), each preceded by the ctl hook's three
    lines and then the vss hook's three, so tests/test_monitor_kind4_console.py still finds the vss hook right before
    each print; and no ctl flush anywhere else."""
    src = [ln.strip() for ln in MONITOR_C.read_text(encoding="ascii").splitlines()]
    ends = [i for i, ln in enumerate(src) if ln.startswith(SESSION_END_PRINTS)]
    assert len(ends) == 7, ends
    for i in ends:
        assert src[i - 6:i] == CTL_HOOK + VSS_HOOK, src[i - 7:i + 1]
    assert [i for i, ln in enumerate(src) if "ctl_log_end(&g_ctl_log)" in ln] == [i - 5 for i in ends]


_DIRECTIVE = re.compile(r"\s*#\s*([a-z]+)")


def _directive(line):
    m = _DIRECTIVE.match(line)
    return m.group(1) if m else None


def _closing_endif(lines, start, depth):
    """The index of the #endif that brings the nesting from `depth` (counted before lines[start]) to 0."""
    for i in range(start, len(lines)):
        d = _directive(lines[i])
        if d in ("if", "ifdef", "ifndef"):
            depth += 1
        elif d in ("else", "elif") and depth == 1:
            raise AssertionError("line %d: an #%s at a stripped block's own level" % (i + 1, d))
        elif d == "endif":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError("no #endif closes the block before line %d" % (start + 1))


def strip_kind2(text):
    """monitor.c without the deviation (its comment's first line through the #endif that closes the not-implemented
    #error) and without every block opened by GUARD through its matching #endif: section 3 item 3's removal.
    Returns the rest and the removed ranges (1-based, inclusive)."""
    lines = text.split("\n")
    spelt = [i + 1 for i, ln in enumerate(lines) if "MONITOR_EXT_KINDS & 0x04" in ln and ln != GUARD]
    assert not spelt, "a 0x04 guard not spelt exactly as section 2.1's line, at line(s) %s" % spelt
    first = [i for i, ln in enumerate(lines) if ln.startswith(DEVIATION_FIRST)]
    err = [i for i, ln in enumerate(lines) if _directive(ln) == "error" and "not implemented" in ln]
    assert len(first) == 1 and len(err) == 1 and first[0] < err[0], (first, err)
    end = _closing_endif(lines, err[0] + 1, 1)
    removed = [(first[0] + 1, end + 1)]
    out = []
    i = 0
    while i < len(lines):
        if first[0] <= i <= end:
            i += 1
            continue
        if lines[i] == GUARD:
            j = _closing_endif(lines, i, 0)
            removed.append((i + 1, j + 1))
            i = j + 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), removed


def _item3_problems(text):
    """Section 3 item 3 on one text of monitor.c: what is wrong with it ([] when nothing is). Outside the 0x04 blocks
    and the deviation it is the comment-updated reference byte for byte, and the deviation is DEVIATION's seven lines, no more."""
    stripped, removed = strip_kind2(text)
    problems = []
    if hashlib.sha256(stripped.encode("ascii")).hexdigest() != BASE_STRIPPED_SHA256:
        problems.append("changed outside the 0x04 blocks and the deviation (against %s); removed %s" % (BASE_COMMIT, removed))
    first, last = removed[0]
    deviation = tuple(text.split("\n")[first - 1:last])
    if deviation != DEVIATION:
        problems.append("the deviation (lines %d-%d) is not section 3 item 2's seven lines: %r" % (first, last, deviation))
    return problems


def test_outside_the_0x04_blocks_and_the_deviation_monitor_c_matches_the_comment_updated_reference():
    text = MONITOR_C.read_bytes().decode("ascii")
    assert _item3_problems(text) == []
    stripped, removed = strip_kind2(text)
    assert len(removed) > 1, "kind 2's blocks are there to strip"
    errors = [ln.strip() for ln in text.splitlines() if _directive(ln) == "error" and "not implemented" in ln]
    assert errors == ['#    error "%s"' % GAP_ERROR], errors


def test_a_line_put_into_the_deviation_or_its_wording_changed_is_caught():
    """The strip removes the deviation from its comment's first line through its #endif, so the hash alone would pass a
    line put between the two, or the comment reworded; DEVIATION, pinned word for word, catches both. A line just
    outside the deviation is the hash's to catch."""
    lines = MONITOR_C.read_bytes().decode("ascii").split("\n")
    i = lines.index(DEVIATION[0])
    assert tuple(lines[i:i + len(DEVIATION)]) == DEVIATION
    smuggled = "#define CTL_SMUGGLED 1"
    variants = {
        "a line between the comment and its #if": lines[:i + 4] + [smuggled] + lines[i + 4:],
        "a line after the comment's first line": lines[:i + 1] + [smuggled] + lines[i + 1:],
        "a line between the #error and its #endif": lines[:i + 6] + [smuggled] + lines[i + 6:],
        "the comment's last line reworded": lines[:i + 3] + [" * #error goes when kind 3 is done. */"] + lines[i + 4:],
        "a line just above the deviation": lines[:i] + [smuggled] + lines[i:],
    }
    caught = {name: bool(_item3_problems("\n".join(v))) for name, v in variants.items()}
    assert caught == dict.fromkeys(variants, True), caught


def test_the_strip_counts_nested_conditionals_and_refuses_what_it_cannot_strip():
    base = ["a", DEVIATION_FIRST + " */", "#  if X", '#    error "not implemented"', "#  endif", "b"]
    assert strip_kind2("\n".join(base)) == ("a\nb", [(2, 5)])
    nested = base[:1] + [GUARD, "#  if Y", "c", "#  endif", "#endif"] + base[1:]
    assert strip_kind2("\n".join(nested)) == ("a\nb", [(7, 10), (2, 6)])
    with pytest.raises(AssertionError):
        strip_kind2("\n".join(base[:1] + [GUARD, "c", "#else", "d", "#endif"] + base[1:]))
    with pytest.raises(AssertionError):
        strip_kind2("\n".join(base[:1] + ["#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04) ", "c", "#endif"]
                              + base[1:]))


# ============================================================ end to end

def test_svc_500_end_to_end_a_kind_2_reply_a_miss_after_silence_and_restored_on_the_next_frame(ctl):
    f1 = poisoned(k2(seq=1, v_cmd=5.0, acc=0.5, jerk=1.0, delta=0.125, rate=0.25, v_meas=5.0, interval=33))
    f2 = poisoned(k2(seq=2, v_cmd=up(P1.v_max), interval=33))
    f3 = poisoned(k2(seq=3, interval=0xFFFF))       # the first Control after a silence: reason 11, by design
    proc, port = mc._start_on_port(ctl["monitor"], ["svc", "500"], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.sendall(f1)
            r1 = mc._recv_exact(s, 64)
            s.sendall(f2)
            r2 = mc._recv_exact(s, 64)
            proc.wait_for(b"monitor: LIVENESS MISS:")
            proc.wait_for(b"monitor: client closed: no complete frame for 500 ms")
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            s.sendall(f3)
            r3 = mc._recv_exact(s, 64)
        proc.wait_for(b"monitor: LIVENESS RESTORED:")
        proc.wait_for(b"monitor: client done:", n=2)
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    assert (r1, r2, r3) == (replied(f1, 0, 0), replied(f2, 1, 12), replied(f3, 1, 11))
    out = [ln.decode("ascii") for ln in proc.out]
    misses = [ln for ln in out if ln.startswith("monitor: LIVENESS MISS:")]
    restored = [ln for ln in out if ln.startswith("monitor: LIVENESS RESTORED:")]
    assert len(misses) == 1 and re.match(r"monitor: LIVENESS MISS: no claim for \d+ ms since seq=2 \(deadline 500 ms, miss 1\)\n$",
                                         misses[0]), misses
    assert len(restored) == 1 and re.match(r"monitor: LIVENESS RESTORED: seq=3 after \d+ ms without a claim\n$", restored[0])
    assert out.index(misses[0]) < out.index(restored[0])
    rejects = [ln for ln in out if ln.startswith("monitor: REJECT")]
    assert rejects == [REJECT_LINE % (2, 1, "ctl-speed") + "\n", REJECT_LINE % (3, 1, "ctl-interval") + "\n"], rejects


def test_kind_2_rejects_over_udp_print_the_ctl_line_and_a_pending_summary_right_before_udp_done(ctl):
    p = P1
    frames = [k2(seq=1), k2(seq=2, v_cmd=up(p.v_max)), k2(seq=3, v_cmd=up(p.v_max)), k2(seq=4, acc=up(p.a_max)),
              k2(seq=5), k2(seq=6, acc=up(p.a_max)), k2(seq=7, acc=up(p.a_max))]
    replies, out = _udp_session(ctl["monitor"], frames)
    assert [bytes.fromhex(r)[H + P_REASON] for r in replies] == [0, 12, 12, 13, 0, 13, 13]
    body = _from_banner(out)
    assert [ln for ln in body if ln.startswith("monitor: REJECT")] == [
        REJECT_LINE % (2, 1, "ctl-speed") + "\n", REJECT_LINE % (4, 1, "ctl-accel") + "\n", REJECT_LINE % (6, 1, "ctl-accel") + "\n"]
    summaries = [ln for ln in body if ln.startswith("monitor: ctl summary:")]
    by = collections.Counter()
    for ln in summaries:
        m = re.match(r"monitor: ctl summary: seen=\d+ rejected=\d+ suppressed=(\d+) by reason:((?: \d+=\d+)+)\n$", ln)
        assert m is not None, ln
        for r, n in re.findall(r" (\d+)=(\d+)", m.group(2)):
            by[int(r)] += int(n)
    assert by == {12: 1, 13: 1}
    # The last frame repeats the reason before it, so the last bucket always holds a suppressed line: the flush hook
    # prints its summary as the line right before `udp done:`, wherever the bucket edges fell.
    assert body[-2].startswith("monitor: ctl summary:") and body[-1] == "monitor: udp done: seen=7 accepted=2 rejected=5 dropped=0\n"


def test_the_ctl_limiter_is_given_the_clock_and_a_new_bucket_prints_again_over_udp(ctl):
    """judge_frame() hands the limiter the monitor's clock: 40 alternating rejects (reason 12, then 13, ...), a silence
    of 1.3 s, and two more. Each of the two stands in a bucket after the first 40's, whatever second edge the 40
    straddled, so both print (a limiter given a frozen clock would hold all 42 in one bucket, and print 34 lines)."""
    p = P1
    frames = [k2(seq=s, v_cmd=up(p.v_max)) if s % 2 else k2(seq=s, acc=up(p.a_max)) for s in range(1, 43)]
    replies, out = _udp_session(ctl["monitor"], frames, pause=(40, 1.3))
    assert [bytes.fromhex(r)[H + P_REASON] for r in replies] == [12 if s % 2 else 13 for s in range(1, 43)]
    printed = [int(m.group(1)) for m in (re.match(r"monitor: REJECT seq=(\d+) kind=ctl ", ln) for ln in out) if m]
    assert 41 in printed and 42 in printed, printed


@pytest.mark.parametrize("mode", ["tcp", "stamp", "svc"])
def test_kind_2_rejects_over_a_stream_print_the_ctl_line_and_a_pending_summary_right_before_client_done(ctl, mode):
    p = P1
    words = {"tcp": [], "stamp": ["stamp"], "svc": ["svc", "60000"]}[mode]
    frames = [k2(seq=1), k2(seq=2, v_cmd=up(p.v_max)), k2(seq=3, v_cmd=up(p.v_max)), k2(seq=4, acc=up(p.a_max)),
              k2(seq=5), k2(seq=6, acc=up(p.a_max)), k2(seq=7, acc=up(p.a_max))]
    proc, port = mc._start_on_port(ctl["monitor"], words, socket.SOCK_STREAM, mc.BANNER[mode])
    try:
        replies = mc._drive_stream(port, [("frame %d" % i, f, None) for i, f in enumerate(frames)])
        proc.wait_for(b"monitor: client done:")
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    assert [bytes.fromhex(r[1])[H + P_REASON] for r in replies] == [0, 12, 12, 13, 0, 13, 13]
    out = mc._normalise_stdout(b"".join(proc.out), port=port)
    assert [ln for ln in out if ln.startswith("monitor: REJECT")] == [
        REJECT_LINE % (2, 1, "ctl-speed") + "\n", REJECT_LINE % (4, 1, "ctl-accel") + "\n", REJECT_LINE % (6, 1, "ctl-accel") + "\n"]
    by = collections.Counter()
    for ln in (x for x in out if x.startswith("monitor: ctl summary:")):
        m = re.match(r"monitor: ctl summary: seen=\d+ rejected=\d+ suppressed=(\d+) by reason:((?: \d+=\d+)+)\n$", ln)
        assert m is not None, ln
        for r, n in re.findall(r" (\d+)=(\d+)", m.group(2)):
            by[int(r)] += int(n)
    assert by == {12: 1, 13: 1}
    # As over UDP: the last frame repeats the reason before it, so the last bucket always holds a suppressed line, and the
    # flush hook prints its summary as the line right before `client done:`, wherever the bucket edges fell.
    i = out.index("monitor: client done: seen=7 accepted=2 rejected=5\n")
    assert out[i - 1].startswith("monitor: ctl summary:")
    assert not [ln for ln in out if " kind=2 " in ln]
