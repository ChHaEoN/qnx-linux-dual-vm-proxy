"""kind4-spec 16.1 C7-C23, C30 and C31: kind 4 in the vss monitor (sdv Phase 2, WP2+3; C21's console, WP4).

Under MONITOR_EXT_KINDS & 0x10, monitor.c gains kind 4 (the kind 4 wire specification, sections 2 to 8):
its payload offsets and flags; reasons 8, 9, 10 and 21-27 and their names in reason_name(); the decoders
(get_u16_le, f32_at by memcpy, any_nonzero, absent_slot_nonzero, present_nonfinite, dabs; no <math.h>);
the compiled profile table and its one lookup; vss_tan() and the rule-26 kinematics; check_vss() in the
order 10, 8, 21, 9, 22, 23, 24, 25, 26, 27; and `case KIND_VSS:` in check_claim(). sdv/frame/rules.py is
the oracle. Every frame of C9-C18 is judged three ways, which must agree: the oracle, the monitor's own
check_claim() through tests/vss_driver.c, and the native vss monitor over UDP, whose whole reply must be
rules.reply()'s. Each edge's expected (verdict, reason) is also written out here from the specification,
so an oracle that moved with the C would still fail.

- C7: the default build answers a kind 4 frame (1, 5) with `monitor: REJECT seq=N kind=4
  reason=claim-kind-unknown`. C8: the vss build answers kinds 2, 7 and 255 (1, 5) with the default
  build's line, byte for byte, once per frame: never limited, so three identical frames give three lines.
- C9-C17: each rule at its edges, under every compiled profile and with both signs. C17: an empty frame
  (no flags, age 0) is ACCEPTED (owner's decision, 2026-10-01).
- C11's a_y edges: a second vss build against a temporary vss_profiles.h that adds a fresh id with
  ay26_max 2.0, bound in Python through Tables.from_contract(profiles=...). Since Phase 7 WP2 the generated
  table compiles a bounded profile too (3, the CARLA ego's): under it the corner of the reachable envelope is
  skipped, and each profile-derived tol and turn point is moved inside the bound (_inside_ay), where the rule judges.
- C18: every adjacent pair of the order gives the earlier reason; everything at once gives 10.
- C19: vss_tan within 1e-9 of math.tan on [0, 1], and psi_dot_kin within 1e-5 deg/s of math's (with L_m
  formed as l_mm * VSS_M_PER_MM, as the C does). Beyond the specification (informative there, asserted
  here): the C equals rules.vss_tan and rules.kinematics bit for bit on tests/test_sdv_frame.py's grids,
  and its coefficients are rules.py's, which -ffp-contract=off makes hold on the PC; a driver built to
  contract (-ffp-contract=fast -mfma) differs, so the comparison can see contraction.
- C20: the conversion constants bit for bit. C30: the digest as monitor.c sees it. C31: the compiled
  struct table and its lookup against the Python table and specification 5.4.
- C21: 10 000 seeded frames, honest and corrupted, an empty frame among them, through the native vss
  monitor over UDP against rules.judge_frame, with the console read while it runs (monitor_corpus._Proc),
  so no run of printed rejects can fill an unread pipe and park the monitor in fflush. Its console is held
  to the limiter's clock-free parts: every kind 4 line is a reject's, in order, differing in reason from
  the frame before it (rule 1), and lines + suppressed = rejected, reason by reason.
- C22, C23: the same frame gets the same verdict on UDP, TCP, svc, stamp and shm, after a 21 and after a
  MISS; a reply differs from its request in p[6] and p[7] only, and in stamp mode also in p[8..23], which
  carry t_in <= t_out.

A kind 4 reject prints its own line, `monitor: REJECT seq=N kind=vss profile=P reason=NAME`, through the
limiter WP4 added; the console (C3, C4, C24-C27), the startup self-check, C29's C half and the profile-id
guard are tests/test_monitor_kind4_console.py's. The generator halves of C30 and C31 (the forbidden
digests, a malformed constUID, a .fidl input, v_max 0.1, two live defaults) are in tests/test_sdv_vss.py.

EQUIVALENT MUTANTS (WP2+3's mutation run and its correctness review, 2026-10-01), recorded so a later run
does not chase them. None of these changes a verdict on any frame, so no test here can or needs to kill
them:
- x01, rule 26's `ay <= ay26_max` made `<`: a_y_kin is a computed double, and no f32 frame lands exactly
  on the bound (spec 5.4; an exhaustive f32 scan at the crossing found none), so the two comparisons
  never disagree.
- The six presence gates that reason 10 and the profile invariants make redundant: F_SPEED in rule 23,
  F_ACCEL in rule 24, F_STEER in rule 25, F_SPEED in rule 26's mask, and F_SPEED or F_GEAR in rule 27's
  mask. Reason 10, judged first, makes an absent slot all zero bytes, so an absent v, a_x or delta reads
  0.0 and an absent gear 0; and every profile has v_max, a_max and delta_max > 0, v26_lo > 0 and v_tol > 0
  (spec 5.4). So 0.0 never exceeds a limit, never lies in rule 26's window, never passes -v_tol or v_tol,
  and gear 0 is never checked. F_STEER and F_YAW in rule 26's mask are NOT redundant (an absent delta or
  psi_dot reads 0 and would reject): C11's "no steering" and "no yaw" cases kill those.

What this does NOT show: anything about the guest build (qcc output cannot run here, and 4.6(c) forbids
taking it apart), so the guest's bits rest on the same source and the pinned flag; any timing.

Needs gcc on Linux (WSL Ubuntu-24.04 or CI's tooling job) and the generated contract in sdv-out/gen
(sdv/vss/generate.py); the shm legs need x86-64, as tests/monitor_corpus.py says.
"""
import collections
import math
import os
import platform
import random
import re
import shutil
import socket
import struct
import subprocess

import pytest

import monitor_corpus as mc
import test_monitor_vss as tmv
import test_sdv_frame as tsf

rules = tsf.rules
vf = tsf.vf
C = tsf.C
H = vf.FRAME_HEADER_BYTES

pytestmark = [tsf.NEEDS_CONTRACT, tmv.NEEDS_GEN]

ACCEPT = (rules.V_ACCEPT, rules.RSN_OK)
COMPILED = tuple(C.COMPILED_PROFILE_IDS) if C is not None else ()

# The specification's names (section 6), written out here, not read from rules.py, plus 0.
SPEC_NAMES = dict(tsf.SPEC_NAMES)
SPEC_NAMES[0] = "ok"
# reason_name()'s names for 0-7, unchanged from main (spec 12: byte-identical).
DEFAULT_NAMES = {0: "ok", 1: "class-out-of-range", 2: "confidence-not-a-percentage", 3: "confidence-below-threshold",
                 4: "inference-time-implausible", 5: "claim-kind-unknown", 6: "vlm-model-unbounded",
                 7: "vlm-time-inconsistent"}
UNKNOWN_KINDS = (2, 7, 255)          # the vss build's unknown-kind parameter (spec 10; owner, 2026-10-01)


def reject(reason):
    return (rules.V_REJECT, reason)


# The kind 4 console lines (spec 12), parsed here and in tests/test_monitor_kind4_console.py.
KIND4_REJECT_RE = re.compile(r"monitor: REJECT seq=(\d+) kind=vss profile=(\d+) reason=([a-z-]+)\n\Z")
SUMMARY_RE = re.compile(r"monitor: vss summary: seen=(\d+) rejected=(\d+) suppressed=(\d+) by reason:((?: \d+=\d+)*)\n\Z")


def parse_summary(line):
    """(seen, rejected, suppressed, {reason: count}) of a `monitor: vss summary:` line, held to what every summary
    is: a bucket with a suppressed line, `by reason:` ascending and non-zero, summing to its suppressed lines, and
    at most the cap's 11 lines beside them (rejected - suppressed are the lines its bucket printed)."""
    m = SUMMARY_RE.match(line)
    assert m, line
    seen, rejected, suppressed = (int(m.group(i)) for i in (1, 2, 3))
    by = [tuple(int(x) for x in kv.split("=")) for kv in m.group(4).split()]
    assert [r for r, _ in by] == sorted({r for r, _ in by}) and all(n > 0 for _, n in by), line
    assert sum(n for _, n in by) == suppressed >= 1 and seen >= rejected >= suppressed, line
    assert rejected - suppressed <= 11, line
    return seen, rejected, suppressed, dict(by)


def kind4_console(lines):
    """The kind 4 lines of a console (str lines): [(seq, profile, reason name)] of its REJECT lines, and the
    suppressed lines its summaries count, by reason. Every `kind=vss` line must parse, and no kind 4 frame may
    print the generic `kind=4` line."""
    printed, suppressed = [], collections.Counter()
    for ln in lines:
        if ln.startswith("monitor: REJECT ") and " kind=vss " in ln:
            m = KIND4_REJECT_RE.match(ln)
            assert m, ln
            printed.append((int(m.group(1)), int(m.group(2)), m.group(3)))
        elif ln.startswith("monitor: vss summary:"):
            suppressed.update(parse_summary(ln)[3])
        assert " kind=4 " not in ln, "a kind 4 reject printed the generic line in the vss build: " + ln
    return printed, suppressed


def with_seq(fr, seq):
    return struct.pack("<Q", seq) + bytes(fr[8:])


def setp(fr, off, value_bytes):
    return tsf.setp(fr, off, value_bytes)


def f32b(x):
    return struct.pack("<f", x)


# ============================================================ builds

def _build(gcc, gen, out_dir, flags=tmv.VSS_FLAGS, names=("monitor", "driver")):
    """The vss build of monitor.c and of the driver, against the contract in `gen`, under -Werror."""
    srcs = {"monitor": tmv.MONITOR_C, "driver": tmv.DRIVER_C}
    out = {}
    for name in names:
        cmd = [gcc, *flags, "-I", str(tmv.COMMON), "-I", str(gen), "-o", str(out_dir / name), str(srcs[name]),
               str(tmv.SHM_MAP_POSIX_C), str(tmv.IVSHM_CLIENT_C)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, "the vss build of %s must compile clean under %s:\n%s" % (name, " ".join(flags), r.stderr)
        out[name] = str(out_dir / name)
    return out


@pytest.fixture(scope="module")
def vss(tmp_path_factory):
    return _build(tmv._gcc(), tmv.GEN, tmp_path_factory.mktemp("kind4"))


@pytest.fixture(scope="module")
def default_monitor(tmp_path_factory):
    """The default build, with tests/test_measure_lib.py's native_servers line (the golden's, C1)."""
    out = tmp_path_factory.mktemp("default") / "monitor"
    r = subprocess.run(mc.gcc_command(tmv._gcc(), str(tmv.REPO), str(out)), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


class Udp:
    """A monitor serving UDP on a free port, its console read as it comes (monitor_corpus._Proc), one
    connected socket to it; frames go one at a time, each waiting for its reply."""

    def __init__(self, binary):
        self.proc, self.port = mc._start_on_port(binary, ["udp"], socket.SOCK_DGRAM, mc.BANNER["udp"])
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.connect(("127.0.0.1", self.port))
        self.sock.settimeout(mc.REPLY_TIMEOUT)

    def exchange(self, frames):
        out = []
        for f in frames:
            self.sock.send(f)
            out.append(self.sock.recv(4096))
        return out

    def rejects(self):
        return [ln for ln in list(self.proc.out) if ln.startswith(b"monitor: REJECT ")]

    def close(self):
        """Stop the monitor; its exit code (0 for a clean SIGTERM)."""
        self.sock.close()
        try:
            return self.proc.stop()
        except BaseException:
            self.proc.kill()
            raise


@pytest.fixture(scope="module")
def vss_udp(vss):
    u = Udp(vss["monitor"])
    yield u
    rc = u.close()
    assert rc == 0 and not u.proc.err, (rc, b"".join(u.proc.err))
    assert u.proc.count(b"monitor: udp done: ") == 1


def driver_lines(driver, mode, lines=None):
    r = subprocess.run([driver] + ([mode] if mode else []), input="".join(x + "\n" for x in lines or ()),
                       capture_output=True, text=True)
    assert r.returncode == 0 and not r.stderr, (mode, r.returncode, r.stderr)
    return r.stdout.splitlines()


def driver_judge(driver, frames):
    """(verdict, reason, name) of each frame from the monitor's check_claim(), through the driver."""
    out = []
    for ln in driver_lines(driver, "judge", [f.hex() for f in frames]):
        v, r, name = ln.split()
        out.append((int(v), int(r), name))
    assert len(out) == len(frames)
    return out


def three_way(bins, udp, cases, t=None):
    """cases: (label, frame, want). The oracle, the monitor's check_claim() (driver) and the native vss
    monitor over UDP each give `want` for every frame; the UDP reply is rules.reply()'s, byte for byte; the
    driver's reason name is the specification's."""
    t = t or tsf.tables()
    frames = [f for _, f, _ in cases]
    bad = []
    for label, f, want in cases:
        got = rules.judge_frame(f, t)
        if got != want:
            bad.append("oracle: %s: %r, want %r" % (label, got, want))
    for (label, _f, want), (v, r, name) in zip(cases, driver_judge(bins["driver"], frames)):
        if (v, r) != want or name != SPEC_NAMES[r]:
            bad.append("check_claim: %s: (%d, %d, %s), want %r" % (label, v, r, name, want))
    for (label, f, _want), rep in zip(cases, udp.exchange(frames)):
        if rep != rules.reply(f, t):
            bad.append("udp: %s: reply %s, want %s" % (label, rep.hex(), rules.reply(f, t).hex()))
    assert not bad, "\n".join(bad[:40]) + ("\n... %d in all" % len(bad) if len(bad) > 40 else "")


def honest(pid, **kw):
    return tsf.honest(profile=pid, **kw)


def frame(pid, **kw):
    return tsf.frame(profile=pid, **kw)


# ============================================================ C7, C8: kind 4 in the default build; unknown kinds

def test_c7_the_default_build_answers_kind_4_as_an_unknown_kind(default_monitor):
    frames = [with_seq(tsf.honest(), 41), with_seq(tsf.honest(psi_dot=100.0), 42), with_seq(tsf.frame(), 43),
              with_seq(setp(tsf.honest(), 0, b"\xff"), 44)]
    u = Udp(default_monitor)
    try:
        replies = u.exchange(frames)
        u.proc.wait_for(b"monitor: REJECT seq=44 ")
    finally:
        rc = u.close()
    assert rc == 0 and not u.proc.err
    for f, rep in zip(frames, replies):
        want = bytearray(f)
        want[H + vf.P_VERDICT], want[H + vf.P_REASON] = 1, 5
        assert rep == bytes(want)
    assert u.rejects() == [b"monitor: REJECT seq=%d kind=4 reason=claim-kind-unknown\n" % s for s in (41, 42, 43, 44)]


def test_c8_the_vss_build_answers_kinds_2_7_255_as_the_default_build_does(vss, default_monitor):
    frames = []
    for kind in UNKNOWN_KINDS:
        f = with_seq(setp(tsf.honest(), vf.P_KIND, bytes([kind])), 100 + kind)
        frames += [f, f, f]                       # identical frames: one line each, never limited
    lines, replies = {}, {}
    for name, binary in (("default", default_monitor), ("vss", vss["monitor"])):
        u = Udp(binary)
        try:
            replies[name] = u.exchange(frames)
            u.proc.wait_for(b"monitor: REJECT ", n=len(frames))
        finally:
            rc = u.close()
        assert rc == 0 and not u.proc.err
        lines[name] = u.rejects()
    want_lines = [b"monitor: REJECT seq=%d kind=%d reason=claim-kind-unknown\n" % (100 + k, k) for k in UNKNOWN_KINDS for _ in "abc"]
    assert lines["vss"] == lines["default"] == want_lines
    for f, rep in zip(frames, replies["vss"]):
        want = bytearray(f)
        want[H + vf.P_VERDICT], want[H + vf.P_REASON] = 1, 5
        assert rep == bytes(want)
    assert replies["vss"] == replies["default"]


def test_the_vss_build_stays_pure_posix_with_no_libm(vss):
    """Spec 3 and 7.2: no <math.h> in monitor.c, and the vss monitor links no libm (tan, |x| and the finiteness
    test are its own)."""
    text = tmv.MONITOR_C.read_text(encoding="ascii")
    assert not [ln for ln in text.splitlines() if ln.lstrip().startswith("#") and "include" in ln and "math.h" in ln]
    readelf = shutil.which("readelf")
    if readelf is None:
        pytest.skip("needs readelf (binutils)")
    dyn = subprocess.run([readelf, "-d", vss["monitor"]], check=True, capture_output=True, text=True).stdout
    needed = [ln for ln in dyn.splitlines() if "(NEEDED)" in ln]
    assert needed and not any("libm." in ln for ln in needed), needed


def test_reason_names_are_the_specs_and_0_to_7_are_unchanged(vss):
    names = dict(ln.split(" ", 2)[1:] for ln in driver_lines(vss["driver"], "reasons"))
    for r in range(256):
        want = DEFAULT_NAMES.get(r) or SPEC_NAMES.get(r) or "unknown"
        assert names[str(r)] == want, r
    for r in tsf.SPEC_ORDER:
        assert rules.REASON_NAMES[r] == SPEC_NAMES[r]


# ============================================================ C9-C17: each rule at its edges

@pytest.mark.parametrize("pid", COMPILED)
@pytest.mark.parametrize("sign", [1.0, -1.0], ids=["pos", "neg"])
def test_c9_speed_accel_steer_at_their_limits(vss, vss_udp, pid, sign):
    p = tsf.tables().profiles[pid]
    cases = []
    for field, lim, reason in (("v", p.v_max, 23), ("a_x", p.a_max, 24), ("delta", p.delta_max, 25)):
        assert vf.f32(lim) == lim, "spec 5.4: every limit compared with a field is a binary32"
        over = vf.f32_next_up(lim)
        cases += [("%s = %r" % (field, sign * lim), frame(pid, **{field: sign * lim}), ACCEPT),
                  ("%s = %r" % (field, sign * over), frame(pid, **{field: sign * over}), reject(reason)),
                  ("%s = %r, f32 below" % (field, sign * lim), frame(pid, **{field: sign * vf.f32_next_down(lim)}), ACCEPT)]
    gear = 1 if sign > 0 else -1
    cases += [("v at v_max, with the gear", frame(pid, v=sign * p.v_max, gear=gear), ACCEPT),
              ("v over v_max, with the gear", frame(pid, v=sign * vf.f32_next_up(p.v_max), gear=gear), reject(23))]
    three_way(vss, vss_udp, cases)


@pytest.mark.parametrize("pid", COMPILED)
def test_c10_age_at_age_max(vss, vss_udp, pid):
    m = C.AGE_MAX_MS
    cases = [("age AGE_MAX", honest(pid, age=m), ACCEPT), ("age AGE_MAX + 1", honest(pid, age=m + 1), reject(22)),
             ("age 0xFFFF", honest(pid, age=0xFFFF), reject(22)), ("age 0", honest(pid, age=0), ACCEPT),
             ("gear alone, age AGE_MAX", frame(pid, gear=1, age=m), ACCEPT),
             ("gear alone, age AGE_MAX + 1", frame(pid, gear=1, age=m + 1), reject(22))]
    three_way(vss, vss_udp, cases)


def _window_cases(pid, p):
    wild = 100.0
    lo, hi = p.v26_lo, p.v26_hi
    assert lo <= p.v_max, "premise: the window's lower edge is reachable under v_max"
    hi_want = reject(26) if hi <= p.v_max else reject(23)              # rule 23 precedes 26 (spec 5.4)
    up_hi = vf.f32_next_up(hi)
    up_hi_want = reject(23) if up_hi > p.v_max else ACCEPT
    cases = []
    for s, gear in ((1.0, 1), (-1.0, -1)):                            # reverse speed: magnitudes
        for y in (wild, -wild):                                       # yaw sign flipped: magnitudes
            cases += [("v %r, y %r" % (s * lo, y), honest(pid, v=s * lo, psi_dot=y, gear=gear), reject(26)),
                      ("v %r, y %r" % (s * hi, y), honest(pid, v=s * hi, psi_dot=y, gear=gear), hi_want),
                      ("v just under lo %r, y %r" % (s * lo, y),
                       honest(pid, v=s * vf.f32_next_down(lo), psi_dot=y, gear=gear), ACCEPT),
                      ("v just over hi %r, y %r" % (s * hi, y), honest(pid, v=s * up_hi, psi_dot=y, gear=gear), up_hi_want)]
    return cases


def _inside_ay(p, t, v, d):
    """d, or for a profile with an a_y bound whose a_y_kin at (|v|, |d|) is past it, the widest binary32 angle of d's sign
    still inside it: rule 26 skips a frame past the bound (spec 6), so an edge of its tol or a turn there is no case of
    the rule. Since Phase 7 WP2 compiled profile 3 (the CARLA ego's, with a bound), the profile-derived points below
    are moved inside it this way; profiles without a bound keep every point."""
    if p.ay26_max == 0.0 or rules.kinematics(abs(v), abs(d), p.l_mm, t)[1] <= p.ay26_max:
        return d
    judged, _skipped = tsf._f32_side(lambda x: rules.kinematics(abs(v), x, p.l_mm, t)[1] > p.ay26_max, 0.0, abs(d))
    return math.copysign(judged, d)


def _f32_at_or_under(x):
    """The largest binary32 value at or under x: x itself when x is a binary32 value."""
    f = vf.f32(x)
    return f if f <= x else vf.f32_next_down(f)


def _tol_cases(pid, p, t):
    tol = p.tol26
    # tol26 is compared in double (spec 5.4 asks binary32 of the limits compared with an f32 field only). Profiles 1-3's
    # tols are binary32 values (3.0, 8.0), so 'exactly at tol' is a frame; profile 4's (Phase 8 WP3b: 9.9, the smallest
    # one-decimal value that keeps its envelope's margin) is not, so at kin 0 its edge is the largest binary32 at or under
    # tol (ACCEPT) and the next one up (REJECT): the same edge at the frame's own resolution.
    at = _f32_at_or_under(tol)
    assert at == tol or (vf.f32(tol) != tol and at < tol < vf.f32_next_up(at)), "premise: at is tol, or the binary32 just under it"
    top = min(p.v26_hi, p.v_max)
    span = top - p.v26_lo
    mid = vf.f32(p.v26_lo + span / 2)
    cases = [("kin 0, y = tol (or the binary32 just under it)", honest(pid, v=mid, delta=0.0, psi_dot=at), ACCEPT),
             ("kin 0, y = -tol (or the binary32 just over it)", honest(pid, v=mid, delta=0.0, psi_dot=-at), ACCEPT),
             ("kin 0, y just over tol", honest(pid, v=mid, delta=0.0, psi_dot=vf.f32_next_up(at)), reject(26)),
             ("kin 0, y just under -tol", honest(pid, v=mid, delta=0.0, psi_dot=-vf.f32_next_up(at)), reject(26))]
    points = ((p.v26_lo + span * 0.25, p.delta_max * 0.5), (p.v26_lo, p.delta_max),
              (p.v26_lo + span * 0.9, p.delta_max / 16), (-(p.v26_lo + span * 0.4), -p.delta_max * 0.3))
    under = 0
    for v, d in points:
        v, d = vf.f32(v), vf.f32(d)
        d = _inside_ay(p, t, v, d)
        kin, ay = rules.kinematics(abs(v), abs(d), p.l_mm, t)
        assert p.ay26_max == 0.0 or ay <= p.ay26_max, "premise: rule 26 judges the point"
        gear = 1 if v > 0 else -1
        below_y, above_y = tsf._f32_side(lambda y, k=kin: abs(abs(y) - k) > tol and abs(y) > k, kin, kin + 2 * tol)
        cases += [("(%r, %r) y over kin, inside tol" % (v, d), honest(pid, v=v, delta=d, psi_dot=below_y, gear=gear), ACCEPT),
                  ("(%r, %r) y over kin, past tol" % (v, d), honest(pid, v=v, delta=d, psi_dot=above_y, gear=gear), reject(26)),
                  ("(%r, %r) -y, past tol" % (v, d), honest(pid, v=v, delta=d, psi_dot=-above_y, gear=gear), reject(26)),
                  ("(%r, %r) -y, inside tol" % (v, d), honest(pid, v=v, delta=d, psi_dot=-below_y, gear=gear), ACCEPT)]
        if kin > tol:
            under += 1
            in_y, out_y = tsf._f32_side(lambda y, k=kin: not (k - y > tol), 0.0, kin)
            cases += [("(%r, %r) y under kin, inside tol" % (v, d), honest(pid, v=v, delta=d, psi_dot=out_y, gear=gear), ACCEPT),
                      ("(%r, %r) y under kin, past tol" % (v, d), honest(pid, v=v, delta=d, psi_dot=in_y, gear=gear), reject(26)),
                      ("(%r, %r) -y under kin, past tol" % (v, d), honest(pid, v=v, delta=d, psi_dot=-in_y, gear=gear), reject(26))]
    assert under >= 2, "premise: two of the points have psi_dot_kin above tol, so the lower edge is tried"
    return cases


@pytest.mark.parametrize("pid", COMPILED)
def test_c11_rule_26_window_edges(vss, vss_udp, pid):
    three_way(vss, vss_udp, _window_cases(pid, tsf.tables().profiles[pid]))


@pytest.mark.parametrize("pid", COMPILED)
def test_c11_rule_26_tol_edges(vss, vss_udp, pid):
    t = tsf.tables()
    three_way(vss, vss_udp, _tol_cases(pid, t.profiles[pid], t), t)


@pytest.mark.parametrize("pid", COMPILED)
def test_c11_rule_26_turns_reverse_yaw_sign_and_the_three_flags(vss, vss_udp, pid):
    t = tsf.tables()
    p = t.profiles[pid]
    v, d = 5.0, _inside_ay(p, t, 5.0, 20.0)
    assert v <= min(p.v26_hi, p.v_max) and d <= p.delta_max
    kin, ay = rules.kinematics(v, d, p.l_mm, t)
    assert kin > p.tol26 + 5.0 and (p.ay26_max == 0.0 or ay <= p.ay26_max)
    over = max(5.0, p.tol26 + 2.0)                            # a yaw past tol above kin: 5 for tol 3, more for profile 3's tol 8
    cases = [("yaw zeroed while turning", honest(pid, v=v, delta=d, psi_dot=0.0), reject(26)),
             ("yaw kinematic", honest(pid, v=v, delta=d, psi_dot=kin), ACCEPT),
             ("yaw sign flipped", honest(pid, v=v, delta=d, psi_dot=-kin), ACCEPT),
             ("reverse", honest(pid, v=-v, delta=d, psi_dot=kin, gear=-1), ACCEPT),
             ("reverse, yaw zeroed", honest(pid, v=-v, delta=d, psi_dot=0.0, gear=-1), reject(26)),
             ("steering the other way", honest(pid, v=v, delta=-d, psi_dot=kin), ACCEPT),
             ("yaw %g over, past tol" % over, honest(pid, v=v, delta=d, psi_dot=kin + over), reject(26)),
             ("no yaw", frame(pid, v=v, delta=d, gear=1), ACCEPT),
             ("no steering", frame(pid, v=v, psi_dot=100.0), ACCEPT),
             ("no speed", frame(pid, delta=d, psi_dot=100.0), ACCEPT)]
    vc, dc = min(p.v26_hi, p.v_max), p.delta_max
    if p.ay26_max == 0.0:                                     # a profile with no a_y bound never skips on a_y
        cases.append(("no a_y bound: the corner (%r, %r) is judged" % (vc, dc), honest(pid, v=vc, delta=dc, psi_dot=0.0), reject(26)))
    else:                                                     # one with a bound skips the corner, the generated table's own
        assert rules.kinematics(vc, dc, p.l_mm, t)[1] > p.ay26_max, "premise: the corner is past the bound"
        cases.append(("a_y bound: the corner (%r, %r) is skipped" % (vc, dc), honest(pid, v=vc, delta=dc, psi_dot=0.0), ACCEPT))
    three_way(vss, vss_udp, cases, t)


@pytest.mark.parametrize("pid", COMPILED)
def test_c12_rule_27(vss, vss_udp, pid):
    p = tsf.tables().profiles[pid]
    vt = p.v_tol
    wrong = vf.f32(2 * vt)
    assert vt < wrong <= p.v_max
    cases = [("v -v_tol, gear 1", frame(pid, v=-vt, gear=1), ACCEPT),
             ("v under -v_tol, gear 1", frame(pid, v=vf.f32_next_down(-vt), gear=1), reject(27)),
             ("v v_tol, gear -1", frame(pid, v=vt, gear=-1), ACCEPT),
             ("v over v_tol, gear -1", frame(pid, v=vf.f32_next_up(vt), gear=-1), reject(27)),
             ("gear 127 backwards", frame(pid, v=-wrong, gear=127), reject(27)),
             ("gear -128 forwards", frame(pid, v=wrong, gear=-128), reject(27)),
             ("gear 5 backwards", frame(pid, v=-wrong, gear=5), reject(27)),
             ("gear 127 forwards", frame(pid, v=wrong, gear=127), ACCEPT),
             ("gear -128 backwards", frame(pid, v=-wrong, gear=-128), ACCEPT),
             ("no speed", frame(pid, gear=1, a_x=1.0), ACCEPT),
             ("no gear", frame(pid, v=-wrong), ACCEPT)]
    for v in (-p.v_max, -wrong, wrong, p.v_max):
        cases.append(("gear 0 at %r" % v, frame(pid, v=v, gear=0), ACCEPT))
    three_way(vss, vss_udp, cases)


def test_c13_profile_ids(vss, vss_udp):
    """Reason 8 for 0, the reserved ids, the first id no row defines (5 until Phase 8's WP3b gave it to profile 5), 255,
    and every generated but uncompiled row (profile 5 until WP3c's freeze); every compiled profile accepted."""
    bound = set(COMPILED)
    absent = min(i for i in range(1, 256) if i not in {int(r["id"]) for r in C.PROFILES} | set(C.RESERVED_PROFILE_IDS))
    assert not {0, absent, 255} & bound
    uncompiled = {int(r["id"]) for r in C.PROFILES if not r["compiled"]}
    assert 5 in uncompiled, "premise (Phase 8 WP3b): profile 5 is generated but not compiled"
    unbound = sorted({0, absent, 255} | set(C.RESERVED_PROFILE_IDS) | uncompiled)
    cases = [("id %d" % i, honest(i), reject(8)) for i in unbound]
    cases += [("id %d, an empty frame" % i, frame(i), reject(8)) for i in unbound]
    cases += [("id %d" % i, honest(i), ACCEPT) for i in COMPILED]
    three_way(vss, vss_udp, cases)


def test_c14_the_catalogue_digest(vss, vss_udp):
    d = C.CATALOG_DIGEST
    swapped = struct.unpack("<I", struct.pack(">I", d))[0]
    assert swapped != d
    cases = [("bit %d" % b, tsf.honest(digest=d ^ (1 << b)), reject(21)) for b in range(32)]
    cases += [("0", tsf.honest(digest=0), reject(21)), ("all ones", tsf.honest(digest=0xFFFFFFFF), reject(21)),
              ("byte-swapped", tsf.honest(digest=swapped), reject(21)), ("the catalogue's", tsf.honest(digest=d), ACCEPT),
              ("empty frame, bit 0", tsf.frame(digest=d ^ 1), reject(21))]
    three_way(vss, vss_udp, cases)


def test_c15_non_finite_values(vss, vss_udp):
    patterns = {"+Inf": 0x7F800000, "-Inf": 0xFF800000, "quiet NaN": 0x7FC00000, "signalling NaN": 0x7F800001,
                "NaN with payload": 0x7FA5A5A5, "negative NaN, all ones": 0xFFFFFFFF}
    base = [vf.f32_bits(x) for x in (5.0, 0.0, 0.0, 0.0)]
    cases = []
    for slot in range(4):
        for name, bits in patterns.items():
            b = list(base)
            b[slot] = bits
            cases.append(("slot %d %s" % (slot, name), vf.pack_bits(1, 0, COMPILED[0], C.CATALOG_DIGEST, b, 1, 0), reject(9)))
        for name, bits in (("subnormal", 0x00000001), ("negative subnormal", 0x807FFFFF), ("-0.0", 0x80000000)):
            b = list(base)
            b[slot] = bits                                    # finite: no 9 (and below every limit and tol, so ACCEPT)
            cases.append(("slot %d %s present" % (slot, name), vf.pack_bits(1, 0, COMPILED[0], C.CATALOG_DIGEST, b, 1, 0), ACCEPT))
    for bits in (0x7F7FFFFF, 0xFF7FFFFF, 0x7F000000, 0xFF000000):              # the largest finite exponent, psi_dot alone
        cases.append(("psi_dot %08X alone" % bits, vf.pack_bits(1, 0, COMPILED[0], C.CATALOG_DIGEST, (None, None, None, bits), None, 0), ACCEPT))
    flt_max = list(base)
    flt_max[1] = 0x7F7FFFFF
    cases.append(("a_x FLT_MAX: finite, so 24", vf.pack_bits(1, 0, COMPILED[0], C.CATALOG_DIGEST, flt_max, 1, 0), reject(24)))
    absent_nan = vf.pack_bits(1, 0, COMPILED[0], C.CATALOG_DIGEST, (vf.f32_bits(5.0), None, None, None), 1, 0)
    cases.append(("a NaN in an absent slot is 10, not 9", setp(absent_nan, vf.P_AX, struct.pack("<I", 0x7FC00000)), reject(10)))
    three_way(vss, vss_udp, cases)


def test_c16_the_layout(vss, vss_udp):
    g = tsf.honest()
    cases = [("flag bit 0x%02X" % bit, setp(g, 0, bytes([g[H] | bit])), reject(10)) for bit in (0x20, 0x40, 0x80)]
    cases += [("p[%d]" % off, setp(g, off, b"\x01"), reject(10)) for off in range(8, 24)]
    cases += [("p[%d]" % off, setp(g, off, b"\x80"), reject(10)) for off in range(44, 48)]
    only_v, only_ax = tsf.frame(v=5.0), tsf.frame(a_x=1.0)
    absent = [(off, only_ax if lo == vf.P_V else only_v) for lo, hi in vf.SLOT_SPANS for off in range(lo, hi)]
    assert [off for off, _ in absent] == list(range(25, 41)) + [43]           # each byte of each slot, slot 0 included
    cases += [("absent slot byte p[%d]" % off, setp(host, off, b"\x01"), reject(10)) for off, host in absent]
    cases += [("-0.0 in absent slot at p[%d]" % off, setp(only_v, off, f32b(-0.0)), reject(10)) for off in (29, 33, 37)]
    cases.append(("-0.0 as v with b0 clear", setp(only_ax, vf.P_V, f32b(-0.0)), reject(10)))
    empty = tsf.frame()
    cases += [("age p[41] with no flags", setp(empty, 41, b"\x01"), reject(10)),
              ("age p[42] with no flags", setp(empty, 42, b"\x01"), reject(10)),
              ("age 0xFFFF with no flags", setp(empty, 41, b"\xff\xff"), reject(10)),
              ("gear with b4 clear", setp(tsf.frame(v=1.0), 43, b"\x01"), reject(10)),
              ("gear -1 with b4 clear", setp(tsf.frame(v=1.0), 43, b"\xff"), reject(10))]
    for kw in (dict(v=1.0), dict(a_x=1.0), dict(delta=1.0), dict(psi_dot=1.0), dict(gear=1)):   # each of b0..b4 carries an age
        cases.append(("age 5 with %s alone" % kw, tsf.frame(age=5, **kw), ACCEPT))
    cases.append(("p[6], p[7] in a request are not judged", setp(g, 6, b"\xee\xee"), ACCEPT))
    three_way(vss, vss_udp, cases)


def test_c17_an_empty_frame_is_accepted(vss, vss_udp):
    """No flags, age 0, everything else valid: ACCEPT (the owner's decision of 2026-10-01; spec 3)."""
    cases = [("empty, profile %d" % pid, with_seq(frame(pid), 7 + pid), ACCEPT) for pid in COMPILED]
    cases.append(("empty, stamp byte", setp(tsf.frame(), 8, b"\x01"), reject(10)))
    three_way(vss, vss_udp, cases)


# ============================================================ C18: the order

@pytest.mark.parametrize("pair", list(zip(tsf.SPEC_ORDER, tsf.SPEC_ORDER[1:])), ids=lambda p: "%d-before-%d" % p)
def test_c18_adjacent_pairs_report_the_earlier(vss, vss_udp, pair):
    first, second = pair
    muts = tsf._mutations()
    base = tsf.honest()
    both = muts[second](muts[first](base))
    assert both == muts[first](muts[second](base)), "the two mutations touch disjoint bytes"
    three_way(vss, vss_udp, [("%d alone" % first, muts[first](base), reject(first)),
                             ("%d alone" % second, muts[second](base), reject(second)),
                             ("%d and %d" % pair, both, reject(first))])


def test_c18_everything_at_once_is_10(vss, vss_udp):
    muts = tsf._mutations()
    fr = tsf.honest()
    for reason in (27, 24, 25, 22, 9, 21, 8, 10, 23):            # 26 shares 9's slot; 23 overwrites 27's v
        fr = muts[reason](fr)
    fr2 = muts[8](muts[21](muts[9](muts[22](muts[23](muts[24](muts[25](tsf.honest())))))))
    three_way(vss, vss_udp, [("all", fr, reject(10)), ("all but 10", fr2, reject(8))])


# ============================================================ C11: the a_y bound, from a second build

def _render_profiles_h(rows):
    """A vss_profiles.h in the generator's form, from rules.Profile rows."""
    xs = ["    X(%du, %du, %s)" % (p.id, p.l_mm, ", ".join(repr(float(getattr(p, n))) for n in
                                                       ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "ay26_max", "tol26", "v_tol")))
          for p in rows]
    return ("/* vss_profiles.h -- a TEST table written by tests/test_monitor_kind4.py; never the generated one. */\n"
            "#ifndef VSS_PROFILES_H\n#define VSS_PROFILES_H\n\n#define VSS_PROFILE_TABLE(X) \\\n" + " \\\n".join(xs) + "\n\n"
            "#define VSS_PROFILE_COUNT %du\n#define VSS_PROFILE_IDS \"%s\"\n\n#endif\n" % (len(rows), " ".join(str(p.id) for p in rows)))


@pytest.fixture(scope="module")
def ay(tmp_path_factory):
    """A second vss build whose table adds a test-only profile with the rule-26 a_y bound 2.0 under a fresh id,
    bound in Python under the same id (Tables.from_contract(profiles=...))."""
    d = tmp_path_factory.mktemp("ay")
    gen = d / "gen"
    gen.mkdir()
    shutil.copy2(tmv.GEN / "vss_contract.h", gen / "vss_contract.h")
    row = next(r for r in C.PROFILES if int(r["id"]) == tsf.ay_bounded())
    used = {int(r["id"]) for r in C.PROFILES} | set(C.RESERVED_PROFILE_IDS)
    fresh = min(set(range(1, 256)) - used)
    test_p = rules.Profile(id=fresh, l_mm=row["l_mm"], v_max=row["v_max"], a_max=row["a_max"], delta_max=row["delta_max"],
                           v26_lo=row["v26_lo"], v26_hi=row["v26_hi"], ay26_max=2.0, tol26=row["tol26"], v_tol=row["v_tol"])
    t = rules.Tables.from_contract(C, profiles=[test_p])
    rows = [t.profiles[i] for i in COMPILED] + [test_p]
    (gen / "vss_profiles.h").write_text(_render_profiles_h(rows), encoding="ascii")
    bins = _build(tmv._gcc(), gen, d)
    u = Udp(bins["monitor"])
    yield {"bins": bins, "t": t, "p": test_p, "udp": u}
    rc = u.close()
    assert rc == 0 and not u.proc.err


def test_c11_the_second_build_compiled_the_test_profile(ay):
    p = ay["p"]
    rows = [ln.split()[1:] for ln in driver_lines(ay["bins"]["driver"], "table") if ln.startswith("row ")]
    assert [int(r[0]) for r in rows] == list(COMPILED) + [p.id]
    assert int(rows[-1][1]) == p.l_mm and float.fromhex(rows[-1][7]) == p.ay26_max == 2.0
    assert p.id not in COMPILED and ay["t"].profiles[p.id] == p


def test_c11_rule_26_a_y_bound_edges(ay):
    """a_y_kin just below the bound judged, just above skipped (ACCEPT with a wild yaw), placed by bisecting the
    f32 delta at fixed f32 speeds with rules.kinematics; reverse and the yaw's sign change nothing; a wild yaw
    never moves a frame out of the rule; a profile with no bound in the same build never skips on a_y."""
    t, p = ay["t"], ay["p"]
    pid = p.id
    wild = 250.0
    cases = []
    for v in (vf.f32(8.0), vf.f32(3.0), vf.f32(p.v26_hi)):
        judged, skipped = tsf._f32_side(lambda d, u=v: rules.kinematics(u, d, p.l_mm, t)[1] > p.ay26_max, 0.0, p.delta_max)
        assert rules.kinematics(v, judged, p.l_mm, t)[1] <= p.ay26_max < rules.kinematics(v, skipped, p.l_mm, t)[1]
        kin = rules.kinematics(v, judged, p.l_mm, t)[0]
        for s, gear in ((1.0, 1), (-1.0, -1)):
            cases += [("v %r: a_y just inside, wild yaw" % (s * v), honest(pid, v=s * v, delta=judged, psi_dot=wild, gear=gear), reject(26)),
                      ("v %r: a_y just inside, -wild yaw" % (s * v), honest(pid, v=s * v, delta=-judged, psi_dot=-wild, gear=gear), reject(26)),
                      ("v %r: a_y just outside, wild yaw" % (s * v), honest(pid, v=s * v, delta=skipped, psi_dot=wild, gear=gear), ACCEPT),
                      ("v %r: a_y just outside, -wild yaw" % (s * v), honest(pid, v=s * v, delta=-skipped, psi_dot=-wild, gear=gear), ACCEPT),
                      ("v %r: a_y just inside, yaw kinematic" % (s * v), honest(pid, v=s * v, delta=judged, psi_dot=kin, gear=gear), ACCEPT)]
    nominal = tsf.nominal()
    pn = t.profiles[nominal]
    assert pn.ay26_max == 0.0
    vc, dc = min(pn.v26_hi, pn.v_max), pn.delta_max
    assert rules.kinematics(vc, dc, pn.l_mm, t)[1] > p.ay26_max, "premise: past the test profile's bound"
    cases += [("no a_y bound: the corner is judged", honest(nominal, v=vc, delta=dc, psi_dot=0.0), reject(26)),
              ("the compiled profiles still judge", honest(nominal), ACCEPT)]
    three_way(ay["bins"], ay["udp"], cases, t)


# ============================================================ C19, C20: rule 26's arithmetic

def _bits(x):
    return struct.pack("<d", x)


def driver_tan(driver, xs):
    return [float.fromhex(ln) for ln in driver_lines(driver, "tan", [x.hex() for x in xs])]


def driver_kin(driver, triples):
    out = driver_lines(driver, "kin", ["%s %s %d" % (v.hex(), d.hex(), l) for v, d, l in triples])
    return [tuple(float.fromhex(x) for x in ln.split()) for ln in out]


def test_c19_vss_tan_within_1e_9_of_math_tan(vss):
    xs = [i / 200000 for i in range(200001)]
    assert xs[0] == 0.0 and xs[-1] == 1.0
    got = driver_tan(vss["driver"], xs)
    worst = max(abs(c - math.tan(x)) for c, x in zip(got, xs))
    assert worst <= 1e-9, worst                         # the design bound (spec 7.2)


def test_c19_kinematics_within_1e_5_deg_per_s_of_math(vss):
    t = tsf.tables()
    triples = [(i * 0.5, float(j), l_mm) for l_mm in (rules.L_MM_MIN, t.profiles[tsf.nominal()].l_mm, rules.L_MM_MAX)
               for i in range(41) for j in range(58)]
    worst = 0.0
    for (v, d, l_mm), (kin, ay) in zip(triples, driver_kin(vss["driver"], triples)):
        ref = C.DEG_PER_RAD * v * math.tan(d * C.RAD_PER_DEG) / (l_mm * C.M_PER_MM)     # L_m as the C forms it (7.1)
        ay_ref = v * ref * C.RAD_PER_DEG
        worst = max(worst, abs(kin - ref))
        assert abs(ay - ay_ref) <= 1e-9 * max(1.0, ay_ref), (v, d, l_mm)          # tests/test_sdv_frame.py's a_y bound
    assert worst <= rules.PSI_DOT_KIN_ERROR_BOUND == 1e-5, worst                    # the design bound (spec 7.3)


def test_c19_vss_tan_equals_the_reference_bit_for_bit(vss):
    """Informative in the specification (C19; rules.py's note), asserted here: with -ffp-contract=off the PC
    build is the reference's arithmetic, on tests/test_sdv_frame.py's grid and at its golden points."""
    xs = tsf.tan_grid() + list(tsf.GOLDEN_TAN)
    got = driver_tan(vss["driver"], xs)
    bad = [x for x, c in zip(xs, got) if _bits(c) != _bits(rules.vss_tan(x))]
    assert not bad, bad[:10]
    for x, want in tsf.GOLDEN_TAN.items():
        assert _bits(got[xs.index(x)]).hex() == want, x


def test_c19_kinematics_equal_the_reference_bit_for_bit(vss):
    """The same, for psi_dot_kin and a_y_kin on tests/test_sdv_frame.py's grid, whose L values separate
    L * M_PER_MM from L / 1000."""
    t = tsf.tables()
    ls, vs, ds = tsf.kinematics_grid()
    triples = [(v, d, l_mm) for l_mm in ls for v in vs for d in ds]
    got = driver_kin(vss["driver"], triples)
    bad = [(v, d, l_mm) for (v, d, l_mm), (kin, ay) in zip(triples, got)
           if (_bits(kin), _bits(ay)) != tuple(_bits(x) for x in rules.kinematics(v, d, l_mm, t))]
    assert not bad, bad[:10]


def test_c19_the_tan_coefficients_are_rules_py_s(vss):
    lines = dict(ln.split(" ", 1) for ln in driver_lines(vss["driver"], "coeffs"))
    assert tuple(float.fromhex(x) for x in lines["sin"].split()) == rules.TAN_SIN_COEFFS
    assert tuple(float.fromhex(x) for x in lines["cos"].split()) == rules.TAN_COS_COEFFS
    assert len(rules.TAN_SIN_COEFFS) + len(rules.TAN_COS_COEFFS) == 15


def _has_fma():
    if platform.machine() not in ("x86_64", "AMD64"):
        return False
    try:
        with open("/proc/cpuinfo", encoding="ascii", errors="replace") as fh:
            return any(ln.startswith("flags") and " fma" in ln for ln in fh)
    except OSError:
        return False


def test_c19_a_contracting_build_differs_so_the_bit_comparison_can_see_it(tmp_path):
    """The driver built with -ffp-contract=fast -mfma fuses the Horner steps: it must differ from the reference
    somewhere on the grids (so the bit-for-bit tests above can see contraction), and must still meet 1e-9."""
    if not _has_fma():
        pytest.skip("needs x86-64 with fma in /proc/cpuinfo")
    flags = tuple(f for f in tmv.VSS_FLAGS if f != "-ffp-contract=off") + ("-ffp-contract=fast", "-mfma")
    drv = _build(tmv._gcc(), tmv.GEN, tmp_path, flags=flags, names=("driver",))["driver"]
    xs = tsf.tan_grid()
    got = driver_tan(drv, xs)
    assert sum(_bits(c) != _bits(rules.vss_tan(x)) for x, c in zip(xs, got)) > 0
    assert max(abs(c - math.tan(x)) for x, c in zip(xs, got)) <= 1e-9


def test_c20_the_conversion_constants_bit_for_bit(vss):
    lines = dict(ln.split(" ", 1) for ln in driver_lines(vss["driver"], None) if not ln.startswith("profile "))
    got = [float.fromhex(x) for x in lines["consts"].split()]
    want = [180 / math.pi, math.pi / 180, 1 / 1000]
    assert [_bits(x) for x in got] == [_bits(x) for x in want]
    assert got == [C.DEG_PER_RAD, C.RAD_PER_DEG, C.M_PER_MM]


# ============================================================ C30, C31: the contract as monitor.c compiles it

def test_c30_the_digest_monitor_c_compiles_is_the_python_one_and_recomputes(vss, vss_udp):
    lines = dict(ln.split(" ", 1) for ln in driver_lines(vss["driver"], None) if not ln.startswith("profile "))
    uids = tuple(int(x, 16) for x in lines["uids"].split())
    c_digest = int(lines["digest"], 16)
    assert uids == tuple(C.SLOT_UIDS)
    assert c_digest == C.CATALOG_DIGEST == vf.digest_of(uids) == vf.fnv1_32(b"".join(struct.pack("<I", u) for u in uids))
    assert c_digest not in (0x00000000, 0xFFFFFFFF)
    three_way(vss, vss_udp, [("the recomputed digest", tsf.honest(digest=vf.digest_of(uids)), ACCEPT)])


def test_c31_the_compiled_table_is_the_python_one_and_keeps_spec_5_4(vss):
    t = tsf.tables()
    out = driver_lines(vss["driver"], "table")
    rows = [ln.split()[1:] for ln in out if ln.startswith("row ")]
    finds = {int(a): int(b) for a, b in (ln.split()[1:] for ln in out if ln.startswith("find "))}
    names = ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "ay26_max", "tol26", "v_tol")
    compiled = []
    for r in rows:
        vals = dict(zip(names, (float.fromhex(x) for x in r[2:])))
        p = rules.Profile(id=int(r[0]), l_mm=int(r[1]), **vals)        # refuses whatever spec 5.4 forbids
        assert 1 <= p.id <= 255 and p.id not in C.RESERVED_PROFILE_IDS
        assert p == t.profiles[p.id], "the C and Python tables agree in every column both carry"
        assert p.ay26_max == 0.0 or p.ay26_max > 0
        compiled.append(p.id)
    assert compiled == list(COMPILED) and len(set(compiled)) == len(compiled)
    assert sorted(finds) == list(range(256))
    for i in range(256):
        assert finds[i] == (compiled.index(i) if i in compiled else -1), i
    x_rows = [ln.split()[1:] for ln in driver_lines(vss["driver"], None) if ln.startswith("profile ")]
    assert x_rows == rows, "the struct table is the X-macro table, row for row"
    run_types = [rt for r in C.PROFILES for rt in r["live_default_for"]]
    assert len(run_types) == len(set(run_types)), "at most one live-default profile per run type"


# ============================================================ C21: the differential corpus

AGE_MAX = C.AGE_MAX_MS if C is not None else 0


def _honest_random(rng, p, t, seq):
    present = [rng.random() < 0.85 for _ in range(5)]
    v = vf.f32(rng.uniform(-min(2.0, p.v_max), min(25.0, p.v_max)))
    gear = rng.randint(1, 6) if v > p.v_tol else (-1 if v < -p.v_tol else rng.choice((-1, 0, 1)))
    d = vf.f32(rng.choice((0.0, rng.uniform(-0.9, 0.9) * p.delta_max)))
    kin = rules.kinematics(abs(v), abs(d), p.l_mm, t)[0]
    y = math.copysign(kin, (v * d) or 1.0) + rng.uniform(-0.4, 0.4) * p.tol26
    claim = vf.Claim(seq=seq, tstamp_ns=rng.getrandbits(63), profile=p.id,
                     v=v if present[0] else None, a_x=rng.uniform(-6.0, 3.0) if present[1] else None,
                     delta=d if present[2] else None, psi_dot=y if present[3] else None,
                     gear=gear if present[4] else None, age_ms=rng.randint(0, AGE_MAX) if any(present) else 0)
    return bytearray(vf.encode(claim, C))


def _corruptions(t):
    """Byte patches on a packed frame (payload offsets + H), one per kind of fault. Each changes a field the
    rules read; which reason, if any, a frame then gets is the oracle's to say, not the patch's."""
    d0 = C.CATALOG_DIGEST
    nan_inf = (0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001, 0x7FA5A5A5, 0xFFFFFFFF)

    def prof(b):
        return t.profiles.get(b[H + vf.P_PROFILE]) or t.profiles[COMPILED[0]]

    def put_f32(rng, b, slot, x, p_flag=1.0):
        struct.pack_into("<f", b, H + vf.F32_SLOT_OFFSETS[slot], x)
        if rng.random() < p_flag:
            b[H] |= 1 << slot

    def signed(rng, x):
        return rng.choice((1.0, -1.0)) * x

    def near(rng, lim):
        return signed(rng, rng.choice((lim, vf.f32_next_up(lim), vf.f32_next_down(lim), lim * rng.uniform(1.0, 2.0),
                                       lim * rng.uniform(0.0, 1.0))))

    def reserved_flag(rng, b):
        b[H] |= rng.choice((0x20, 0x40, 0x80))

    def stamp_byte(rng, b):
        b[H + rng.randrange(8, 24)] = rng.randrange(1, 256)

    def reserved_byte(rng, b):
        b[H + rng.randrange(44, 48)] = rng.randrange(1, 256)

    def flag_cleared(rng, b):                                 # its bytes stay
        b[H] &= ~(1 << rng.randrange(5)) & 0xFF

    def negative_zero(rng, b):                                # its flag as it was
        struct.pack_into("<I", b, H + vf.F32_SLOT_OFFSETS[rng.randrange(4)], 0x80000000)

    def nothing_present(rng, b):                              # an empty frame, or an age of nothing
        b[H] = 0
        b[H + 25:H + 41] = bytes(16)
        b[H + vf.P_GEAR] = 0
        struct.pack_into("<H", b, H + vf.P_AGE, rng.choice((0, 0, 1, rng.randrange(0x10000))))

    def profile(rng, b):
        b[H + vf.P_PROFILE] = rng.choice((0, 3, 4, 5, 255, rng.randrange(256)))

    def digest(rng, b):
        swapped = struct.unpack("<I", struct.pack(">I", d0))[0]
        struct.pack_into("<I", b, H + vf.P_DIGEST, rng.choice((d0 ^ (1 << rng.randrange(32)), 0, 0xFFFFFFFF, swapped, rng.getrandbits(32))))

    def non_finite(rng, b):
        bits = rng.choice(nan_inf + (0x7F800000 | rng.randrange(1, 1 << 23),))
        struct.pack_into("<I", b, H + vf.F32_SLOT_OFFSETS[rng.randrange(4)], bits)
        if rng.random() < 0.8:
            b[H] |= 0x0F

    def age(rng, b):
        struct.pack_into("<H", b, H + vf.P_AGE, rng.choice((AGE_MAX, AGE_MAX + 1, AGE_MAX - 1, 0xFFFF, rng.randrange(0x10000))))

    def speed(rng, b):
        put_f32(rng, b, 0, near(rng, prof(b).v_max))

    def accel(rng, b):
        put_f32(rng, b, 1, near(rng, prof(b).a_max))

    def steer(rng, b):
        put_f32(rng, b, 2, near(rng, prof(b).delta_max))

    def window(rng, b):
        p = prof(b)
        put_f32(rng, b, 0, signed(rng, rng.choice((p.v26_lo, p.v26_hi, vf.f32_next_down(p.v26_lo), vf.f32_next_up(p.v26_hi)))))

    def yaw(rng, b):
        tol = _f32_at_or_under(prof(b).tol26)                 # tol itself for a binary32 tol (_tol_cases says why)
        put_f32(rng, b, 3, rng.choice((rng.uniform(-300.0, 300.0), 0.0, tol, -tol, vf.f32_next_up(tol))), p_flag=0.9)

    def direction(rng, b):
        vt = prof(b).v_tol
        put_f32(rng, b, 0, signed(rng, rng.choice((vt, vf.f32_next_up(vt), 2 * vt))))

    def gear(rng, b):
        b[H + vf.P_GEAR] = rng.choice((-128, 127, -1, 1, 0, rng.randint(-128, 127))) & 0xFF
        if rng.random() < 0.9:
            b[H] |= vf.F_GEAR

    def raw_bits(rng, b):                                     # any pattern, subnormals and FLT_MAX among them
        bits = rng.choice((rng.getrandbits(32), 0x00000001, 0x807FFFFF, 0x80000000, 0x7F7FFFFF))
        struct.pack_into("<I", b, H + vf.F32_SLOT_OFFSETS[rng.randrange(4)], bits)
        b[H] |= rng.choice((0x01, 0x02, 0x04, 0x08))

    def any_byte(rng, b):                                     # p[6..7] too: a request's are never judged
        b[H + rng.choice([o for o in range(vf.FRAME_PAYLOAD_BYTES) if o != vf.P_KIND])] = rng.randrange(256)

    return (reserved_flag, stamp_byte, reserved_byte, flag_cleared, negative_zero, nothing_present, profile, digest,
            non_finite, age, speed, accel, steer, window, yaw, direction, gear, raw_bits, any_byte)


def c21_corpus(n=10000, seed=2121):
    """n seeded kind 4 frames: honest ones (each slot present or not, every compiled profile) with none, one or
    several fields corrupted; the empty frame first. Seq is the frame's 1-based index."""
    rng = random.Random(seed)
    t = tsf.tables()
    corrupt = _corruptions(t)
    frames = [with_seq(tsf.frame(), 1)]
    while len(frames) < n:
        seq = len(frames) + 1
        b = _honest_random(rng, t.profiles[rng.choice(COMPILED)], t, seq)
        for _ in range(rng.choices((0, 1, 2, 3), weights=(30, 40, 20, 10))[0]):
            rng.choice(corrupt)(rng, b)
        b[0:8] = struct.pack("<Q", seq)
        frames.append(bytes(b))
    return frames


def test_c21_ten_thousand_seeded_frames_against_the_reference(vss):
    t = tsf.tables()
    frames = c21_corpus()
    assert len(frames) == 10000 and frames[0][H:] == tsf.frame()[H:] and frames[0][H] == 0, "the empty frame is in it"
    want = [rules.judge_frame(f, t) for f in frames]
    counts = {}
    for _v, r in want:
        counts[r] = counts.get(r, 0) + 1
    assert set(counts) == {0, 8, 9, 10, 21, 22, 23, 24, 25, 26, 27}, counts
    assert min(counts.values()) >= 100, "every reason and ACCEPT is well represented: %r" % counts
    assert want[0] == ACCEPT

    got_c = driver_judge(vss["driver"], frames)
    bad = [(i + 1, w, g[:2]) for i, (w, g) in enumerate(zip(want, got_c)) if w != g[:2]]
    assert not bad, "check_claim against rules.judge_frame (seq, want, got): %r" % bad[:20]

    u = Udp(vss["monitor"])
    try:
        replies = u.exchange(frames)
    finally:
        rc = u.close()          # the stop flushes the last summary before `udp done:`
    assert rc == 0 and not u.proc.err
    bad = [i + 1 for i, (f, rep) in enumerate(zip(frames, replies)) if rep != rules.reply(f, t)]
    assert not bad, "replies that are not rules.reply's, by seq: %r" % bad[:20]
    n_rej = sum(1 for v, _ in want if v)
    assert u.proc.count(b"monitor: udp done: seen=10000 accepted=%d rejected=%d dropped=0\n" % (counts[0], n_rej)) == 1

    # The console under WP4's limiter (spec 12). Which rejects print depends on the monitor's clock through the
    # cap of 11 per bucket, so end to end this holds the clock-free parts (the limiter itself is driven with a
    # scripted clock in tests/test_monitor_kind4_console.py): each line is a reject's, in order, with its frame's
    # id and reason, and differs in reason from the frame before it (rule 1; an ACCEPT is 0); and every reject is
    # a line or counted in a summary, reason by reason (lines + suppressed = rejected).
    printed, suppressed = kind4_console([ln.decode("ascii") for ln in u.proc.out])
    reasons = [r for _v, r in want]
    before = [0] + reasons[:-1]
    seqs = [s for s, _, _ in printed]
    assert seqs == sorted(set(seqs)) and seqs, "lines in order, one per frame at most"
    for s, pid, name in printed:
        r = reasons[s - 1]
        assert r != 0 and r != before[s - 1] and name == SPEC_NAMES[r] and pid == frames[s - 1][H + vf.P_PROFILE], (s, pid, name)
    lines_by_reason = collections.Counter(reasons[s - 1] for s in seqs)
    assert lines_by_reason + suppressed == collections.Counter(r for r in reasons if r), "lines + suppressed = rejected"
    assert sum(suppressed.values()) > 0, "premise: the corpus makes the limiter suppress"


# ============================================================ C22, C23: every transport

TRANSPORTS = ("udp", "tcp", "stamp", "svc", "shm")


def _session(binary, transport, frames, workdir):
    """One session of `frames` on one transport: the replies as bytes and the console."""
    items = [("f%d" % i, f, None) for i, f in enumerate(frames)]
    path = None
    if transport == "udp":
        proc, port = mc._start_on_port(binary, ["udp"], socket.SOCK_DGRAM, mc.BANNER["udp"])
    elif transport in ("tcp", "stamp", "svc"):
        words = {"tcp": [], "stamp": ["stamp"], "svc": ["svc", str(mc.SVC_DEADLINE_MS)]}[transport]
        proc, port = mc._start_on_port(binary, words, socket.SOCK_STREAM, mc.BANNER[transport])
    else:
        if not mc.shm_client_ok():
            pytest.skip("the shm client needs x86-64 (tests/monitor_corpus.py)")
        path = os.path.join(str(workdir), "slot")
        with open(path, "wb") as fh:
            fh.write(b"\0" * mc.SHM_FILE_BYTES)
        proc = mc._Proc([binary, "shm", path])
        port = None
    try:
        if transport == "shm":
            proc.wait_for(mc.BANNER["shm"])
            replies = mc._drive_shm(path, proc, items)
        elif transport == "udp":
            replies = mc._drive_udp(port, items)
        else:
            replies = mc._drive_stream(port, items)
            proc.wait_for(b"monitor: client done:")
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err, (rc, b"".join(proc.err))
    assert all(r[1] is not None for r in replies), replies
    return [bytes.fromhex(r[1]) for r in replies], proc


def _c22_frames():
    """An honest frame and one frame per reason, each with its own seq, and a frame that gets 21."""
    muts = tsf._mutations()
    xs = [with_seq(tsf.honest(), 1)] + [with_seq(muts[r](tsf.honest()), 10 + r) for r in tsf.SPEC_ORDER]
    xs.append(with_seq(tsf.frame(), 2))                                                  # the empty frame
    d21 = with_seq(muts[21](tsf.honest(psi_dot=100.0)), 99)
    return xs, d21


def _unstamped(rep):
    b = bytearray(rep)
    b[H + 8:H + 24] = bytes(16)
    return bytes(b)


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_c22_the_same_frame_gets_the_same_verdict_on_every_transport_and_after_a_21(vss, transport, tmp_path):
    t = tsf.tables()
    xs, d21 = _c22_frames()
    seq = list(xs)
    for x in xs:
        seq += [d21, x]                                       # each frame again, right after a 21
    replies, _proc = _session(vss["monitor"], transport, seq, tmp_path)
    if transport == "stamp":
        replies = [_unstamped(r) for r in replies]
    want = [rules.reply(f, t) for f in seq]
    assert replies == want
    first = dict(zip(xs, replies[:len(xs)]))
    for f, rep in zip(seq[len(xs):], replies[len(xs):]):
        if f != d21:
            assert rep == first[f]
    assert {rules.judge_frame(x, t)[1] for x in xs} == set(tsf.SPEC_ORDER) | {0}, "premise: every reason and an accept"


def test_c22_after_a_miss_the_same_frames_get_the_same_verdicts(vss):
    """svc with the :7160 deadline (500 ms, spec 13): the frames on one connection, held open in silence until the
    monitor reports the MISS and closes it; then the same frames on a new connection, whose first claim is RESTORED."""
    t = tsf.tables()
    xs, _d21 = _c22_frames()
    proc, port = mc._start_on_port(vss["monitor"], ["svc", "500"], socket.SOCK_STREAM, mc.BANNER["svc"])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            first = []
            for f in xs:
                s.sendall(f)
                first.append(mc._recv_exact(s, vf.FRAME_TOTAL_BYTES))
            proc.wait_for(b"monitor: LIVENESS MISS: ")
            proc.wait_for(b"monitor: client closed: no complete frame for 500 ms")
            s.settimeout(mc.REPLY_TIMEOUT)
            assert s.recv(64) == b"", "the monitor closed the silent connection"
        with socket.create_connection(("127.0.0.1", port), timeout=mc.REPLY_TIMEOUT) as s:
            second = []
            for f in xs:
                s.sendall(f)
                second.append(mc._recv_exact(s, vf.FRAME_TOTAL_BYTES))
        proc.wait_for(b"monitor: LIVENESS RESTORED: seq=1 ")
        proc.wait_for(b"monitor: client done:", n=2)
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err
    assert first == second == [rules.reply(f, t) for f in xs]


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_c23_a_reply_changes_only_the_verdict_and_reason_and_in_stamp_mode_the_stamps(vss, transport, tmp_path):
    t = tsf.tables()
    xs, d21 = _c22_frames()
    poisoned = [setp(f, vf.P_VERDICT, b"\xee\xee") for f in xs + [d21]]   # the request's p[6..7] are overwritten, never judged
    replies, _proc = _session(vss["monitor"], transport, poisoned, tmp_path)
    for f, rep in zip(poisoned, replies):
        diff = {i for i in range(vf.FRAME_TOTAL_BYTES) if f[i] != rep[i]}
        allowed = {H + vf.P_VERDICT, H + vf.P_REASON}
        if transport == "stamp":
            allowed |= set(range(H + 8, H + 24))
            t_in, t_out = struct.unpack_from("<QQ", rep, H + vf.P_T_IN)
            assert 0 < t_in <= t_out, (t_in, t_out)
            assert _unstamped(rep) == rules.reply(f, t)
        else:
            assert rep == rules.reply(f, t)
        assert diff <= allowed and {H + vf.P_VERDICT, H + vf.P_REASON} <= diff, sorted(diff)
