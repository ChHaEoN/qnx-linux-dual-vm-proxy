"""C2b S3: the kind 6 `lane` claim's Python twin alone (sdv/lane/laneframe.py and lanerules.py). The rules come from the
project's local design notes, not in this tree.

What is tested, and how:

- The layout (2.2): the offsets, the flags and the 29 bytes kind 6 owns (p[0..5] and p[25..47]); the reasons 28-31, their
  names (`[a-z-]+`) and the order 10, 9, 8, 28, 29, 30, 31 (2.3); profile 1's eight design values (2.4) and the table's
  invariants (table_errors, the twin of the monitor's startup self-check), each broken one refused.
- The codec: encode packs an honest claim (a lane with its four values and confidence, a "no lane" claim, vehicle values
  or none) that decodes to the binary32 of what was given, and refuses what an honest claim cannot carry; pack_bits takes
  each slot's exact bits and refuses what the layout forbids; layout_errors names each layout fault (a reserved flag bit,
  a byte of p[8..23], each absent lane or vehicle byte, -0.0 in an absent slot, the kind, the seq, the verdict and reason
  of a request or a reply), and decode_request and decode_reply refuse each.
- The judge (2.3), by hand cases written here from the specification: each rule's limit at and one binary32 step past
  it, rule 31's direction in every sign of offset and heading, its speed bound and its margin; the order between adjacent
  rules; the rule 31 predicate alone (imminent), with the vehicle flag clear; the sin polynomial (its coefficients the
  doubles nearest (-1)^k / (2k+1)!, odd, within 2e-11 of math.sin on the domain |x| <= 0.5); the judge reads bytes, so a
  frame decode refuses still gets its reason.
- The package's own rule (2.6): nothing in sdv/lane imports another sdv package or anything outside the standard library;
  it holds no __init__.py and imports nothing relatively, so CI's mypy keeps sdv/ off its path, and its module names are
  its own among the paths that mypy command checks beside it.

The C monitor's judge is held to this one by tests/test_monitor_lane.py and tests/test_sdv_lane_contract.py. Nothing here
is a result: every value is 2.4's or a hand case's.

What this does NOT show: that the C monitor judges as lanerules does (the two files above); anything about a lane model,
a camera, CARLA or the claim's client (S0-S2, S4); any timing.

Needs only Python's standard library: runs on Windows and in WSL alike.
"""
import ast
import math
import random
import re
import struct
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LANE_DIR = REPO / "sdv" / "lane"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
if str(LANE_DIR) not in sys.path:
    sys.path.insert(0, str(LANE_DIR))
import laneframe as lf  # noqa: E402
import lanerules as lr  # noqa: E402

sys.dont_write_bytecode = _saved

H = 16
P1 = (1, 50, 2.5, 4.5, 0.1, 0.5, 0.95, 1.0, 1.0)     # 2.4, written out here: id, conf_min, width_min, width_max, k_max,
#                                                     h_max, veh_half_w, v_min, tlc_min
NAMES = {0: "ok", 5: "claim-kind-unknown", 8: "profile-unbound", 9: "field-not-finite", 10: "flags-invalid",
         28: "lane-conf-low", 29: "lane-implausible", 30: "lane-departure", 31: "lane-departure-imminent"}
QNAN = 0x7FC00000
NONFINITE = (0x7F800000, 0xFF800000, QNAN, 0x7F800001, 0xFFFFFFFF)
LANE_FIELDS = ("offset", "heading", "curvature", "width")
VEH_FIELDS = ("speed", "yaw_rate")


def up(x):
    return lf.f32_next_up(x)


def down(x):
    return lf.f32_next_down(x)


def lane(seq=1, conf=90, offset=0.0, heading=0.0, curvature=0.0, width=3.5, speed=None, yaw_rate=None, profile=1, **kw):
    """An honest claim with a lane (and vehicle values when speed is given)."""
    if speed is not None and yaw_rate is None:
        yaw_rate = 0.0
    return lf.encode(seq=seq, profile=profile, conf=conf, offset=offset, heading=heading, curvature=curvature, width=width,
                     speed=speed, yaw_rate=yaw_rate, **kw)


def setp(frame, off, data):
    b = bytearray(frame)
    b[H + off:H + off + len(data)] = data
    return bytes(b)


def verdict(frame):
    return lr.judge(frame)


# ============================================================ the layout, the reasons and the table

def test_the_offsets_and_flags_are_2_2s_and_kind_6_owns_its_29_bytes():
    assert (lf.KIND_LANE, lf.P_KIND, lf.P_VERDICT, lf.P_REASON) == (6, 24, 6, 7)
    assert (lf.P_FLAGS, lf.P_CONF, lf.P_OFFSET) == (0, 1, 2)
    assert (lf.P_HEADING, lf.P_CURVATURE, lf.P_WIDTH, lf.P_SPEED, lf.P_YAW_RATE, lf.P_AGE, lf.P_PROFILE) == (
        25, 29, 33, 37, 41, 45, 47)
    assert (lf.F_LANE, lf.F_VEH, lf.F_RESERVED) == (0x01, 0x02, 0xFC)
    assert lf.FRAME_TOTAL_BYTES == 64 and lf.FRAME_HEADER_BYTES == 16 and lf.FRAME_PAYLOAD_BYTES == 48
    owned = {lf.P_FLAGS, lf.P_CONF} | set(range(lf.P_OFFSET, lf.P_OFFSET + 4)) | {lf.P_PROFILE}
    for off in (lf.P_HEADING, lf.P_CURVATURE, lf.P_WIDTH, lf.P_SPEED, lf.P_YAW_RATE):
        owned |= set(range(off, off + 4))
    owned |= {lf.P_AGE, lf.P_AGE + 1}
    assert owned == set(range(0, 6)) | set(range(25, 48)) and len(owned) == 29


def test_the_reasons_their_names_and_their_order():
    assert {r: lf.REASON_NAMES[r] for r in NAMES if r != 5} == {r: n for r, n in NAMES.items() if r != 5}
    assert all(re.fullmatch(r"[a-z-]+", n) for n in lf.REASON_NAMES.values())
    assert lf.ORDER == (10, 9, 8, 28, 29, 30, 31)
    assert (lf.RSN_LANE_CONF_LOW, lf.RSN_LANE_IMPLAUSIBLE, lf.RSN_LANE_DEPARTURE, lf.RSN_LANE_DEPARTURE_IMMINENT) == (
        28, 29, 30, 31)
    assert max(lf.ORDER) < 32, "the limiter's by_reason[32] covers every kind 6 reason"


def test_profile_1_is_2_4s_design_values_and_the_only_one():
    assert list(lf.PROFILES) == [1]
    assert tuple(getattr(lf.PROFILES[1], k) for k in lf.PROFILE_FIELDS) == P1
    assert lf.PROFILE_FIELDS == ("id", "conf_min", "width_min", "width_max", "k_max", "h_max", "veh_half_w", "v_min",
                                 "tlc_min")
    assert lf.table_errors(lf.PROFILES) == []
    assert lf.SIN_DOMAIN == 0.5


def _row(**kw):
    vals = dict(zip(lf.PROFILE_FIELDS, P1))
    vals.update(kw)
    return lf.LaneProfile(**vals)


@pytest.mark.parametrize("edit", [
    dict(conf_min=101), dict(width_min=0.0), dict(width_min=-1.0), dict(width_max=2.5), dict(width_max=2.0),
    dict(width_max=math.inf), dict(width_min=math.nan), dict(veh_half_w=-0.1), dict(veh_half_w=1.25),
    dict(veh_half_w=1.3), dict(k_max=0.0), dict(k_max=math.inf), dict(h_max=0.0), dict(h_max=0.5000000000000001),
    dict(h_max=1.0), dict(v_min=-0.5), dict(v_min=math.inf), dict(tlc_min=0.0), dict(tlc_min=math.nan), dict(id=0),
    dict(id=256)], ids=lambda d: "%s=%r" % next(iter(d.items())))
def test_table_errors_refuses_each_broken_invariant(edit):
    assert lf.table_errors({1: _row()}) == []
    row = _row(**edit)
    assert lf.table_errors({row.id: row}), edit


def test_table_errors_refuses_two_rows_with_one_id_and_a_key_that_is_not_its_rows_id():
    assert lf.table_errors({1: _row(), 2: _row(id=2)}) == []
    assert lf.table_errors({1: _row(), 2: _row(id=1)})
    assert lf.table_errors({}) , "an empty table binds nothing: refused"


def test_the_table_accepts_its_bounds_exactly():
    # conf_min 100, veh_half_w just under width_min / 2, h_max at the sin domain: the self-check's limits are its own
    assert lf.table_errors({1: _row(conf_min=100, veh_half_w=1.2499999999999998, h_max=0.5, v_min=0.0)}) == []


# ============================================================ the codec

def test_encode_an_honest_lane_claim_round_trips_as_binary32():
    fr = lf.encode(seq=7, tstamp_ns=123456789, profile=1, conf=88, offset=-0.3, heading=0.02, curvature=-0.004, width=3.6,
                   speed=13.9, yaw_rate=-0.05, age_ms=42)
    assert len(fr) == 64 and lf.layout_errors(fr) == []
    d = lf.decode_request(fr)
    assert (d.seq, d.tstamp_ns, d.flags, d.conf, d.profile, d.age_ms, d.verdict, d.reason) == (
        7, 123456789, 0x03, 88, 1, 42, 0, 0)
    assert d.lane and d.veh
    for name, x in (("offset", -0.3), ("heading", 0.02), ("curvature", -0.004), ("width", 3.6), ("speed", 13.9),
                    ("yaw_rate", -0.05)):
        assert d.value(name) == lf.f32(x), name
    p = fr[H:]
    assert p[lf.P_KIND] == 6 and p[6] == p[7] == 0 and not any(p[8:24])
    assert struct.unpack_from("<f", p, lf.P_OFFSET)[0] == lf.f32(-0.3)
    assert struct.unpack_from("<H", p, lf.P_AGE)[0] == 42 and p[lf.P_PROFILE] == 1


def test_a_no_lane_claim_carries_zero_bytes_where_2_2_says():
    fr = lf.encode(seq=1)
    p = fr[H:]
    assert p[0] == 0 and not any(p[1:6]) and not any(p[25:45]) and p[47] == 1 and lf.layout_errors(fr) == []
    d = lf.decode_request(fr)
    assert not d.lane and not d.veh and all(d.bits[n] is None for n in LANE_FIELDS + VEH_FIELDS)
    fr = lf.encode(seq=2, speed=5.0, yaw_rate=0.1, age_ms=7)
    p = fr[H:]
    assert p[0] == lf.F_VEH and not any(p[1:6]) and not any(p[25:37]) and any(p[37:45]) and lf.layout_errors(fr) == []
    assert lf.decode_request(fr).value("speed") == 5.0


def test_encode_keeps_minus_zero_in_a_present_slot():
    fr = lane(offset=-0.0, heading=-0.0)
    assert fr[H + lf.P_OFFSET:H + lf.P_OFFSET + 4] == b"\x00\x00\x00\x80"
    assert lf.layout_errors(fr) == []


@pytest.mark.parametrize("kw,why", [
    (dict(offset=0.0), "a lane's values come together"),
    (dict(conf=90, offset=0.0, heading=0.0, curvature=0.0), "a lane's values come together"),
    (dict(conf=90), "a lane's values come together"),
    (dict(offset=0.0, heading=0.0, curvature=0.0, width=3.5), "a lane's values come together"),
    (dict(speed=1.0), "speed and yaw rate come together"),
    (dict(yaw_rate=1.0), "speed and yaw rate come together"),
    (dict(conf=101, offset=0.0, heading=0.0, curvature=0.0, width=3.5), "conf"),
    (dict(conf=-1, offset=0.0, heading=0.0, curvature=0.0, width=3.5), "conf"),
    (dict(conf=True, offset=0.0, heading=0.0, curvature=0.0, width=3.5), "conf"),
    (dict(conf=90, offset=math.nan, heading=0.0, curvature=0.0, width=3.5), "not finite"),
    (dict(conf=90, offset=0.0, heading=math.inf, curvature=0.0, width=3.5), "not finite"),
    (dict(speed=1e39, yaw_rate=0.0), "binary32"),
    (dict(speed=1.0, yaw_rate=True), "not a number"),
    (dict(speed="1", yaw_rate=0.0), "not a number"),
    (dict(profile=0), "profile"),
    (dict(profile=256), "profile"),
    (dict(seq=0), "seq"),
    (dict(seq=(1 << 64) - 1), "seq"),
    (dict(age_ms=-1), "age_ms"),
    (dict(age_ms=0x10000), "age_ms"),
    (dict(tstamp_ns=-1), "tstamp_ns"),
    (dict(tstamp_ns=1 << 64), "tstamp_ns"),
    (dict(tstamp_ns=True), "tstamp_ns"),
])
def test_encode_refuses_what_an_honest_claim_cannot_carry(kw, why):
    args = dict(seq=1)
    args.update(kw)
    with pytest.raises(lf.FrameError, match=re.escape(why)):
        lf.encode(**args)


def test_pack_bits_takes_exact_bits_for_injection():
    fr = lf.pack_bits(seq=3, flags=0x03, profile=0, conf=255, offset=QNAN, heading=0x7F800000, curvature=0xFFFFFFFF,
                      width=0x80000000, speed=0x7F800001, yaw_rate=0)
    p = fr[H:]
    assert p[0] == 3 and p[1] == 255 and p[47] == 0 and p[24] == 6
    assert struct.unpack_from("<IIII", p, 25) == (0x7F800000, 0xFFFFFFFF, 0x80000000, 0x7F800001)
    assert struct.unpack_from("<I", p, 2)[0] == QNAN and lf.layout_errors(fr) == []


@pytest.mark.parametrize("kw,why", [
    (dict(flags=0x04), "reserved flag bits"),
    (dict(flags=0x80), "reserved flag bits"),
    (dict(flags=0x01), "its flag is set but no value is given"),
    (dict(flags=0x00, offset=0), "a value is given but its flag is clear"),
    (dict(flags=0x00, speed=0), "a value is given but its flag is clear"),
    (dict(flags=0x02, speed=0), "its flag is set but no value is given"),
    (dict(flags=0x00, conf=1), "confidence"),
    (dict(flags=0x00, profile=256), "profile"),
    (dict(flags=0x00, offset=None, age_ms=0x10000), "age_ms"),
])
def test_pack_bits_refuses_what_the_layout_forbids(kw, why):
    args = dict(seq=1, flags=0, profile=1)
    args.update(kw)
    with pytest.raises(lf.FrameError, match=re.escape(why)):
        lf.pack_bits(**args)


def _faults():
    """(label, frame) of every layout fault, each a byte patch on an honest frame."""
    full = lane(speed=5.0, yaw_rate=0.1, age_ms=3)
    none = lf.encode(seq=1)
    out = [("flag b%d" % b, setp(full, 0, bytes([full[H] | (1 << b)]))) for b in range(2, 8)]
    out += [("p[%d]" % i, setp(full, i, b"\x01")) for i in range(8, 24)]
    out += [("absent lane byte p[%d]" % i, setp(none, i, b"\x01")) for i in list(range(1, 6)) + list(range(25, 37))]
    out += [("absent vehicle byte p[%d]" % i, setp(none, i, b"\x01")) for i in range(37, 45)]
    out += [("-0.0 in the absent %s" % n, setp(none, off, b"\x00\x00\x00\x80"))
            for n, off in (("offset", 2), ("heading", 25), ("curvature", 29), ("width", 33), ("speed", 37), ("yaw", 41))]
    veh_only = lf.encode(seq=1, speed=5.0, yaw_rate=0.1)
    out += [("a lane byte with only VEH set p[%d]" % i, setp(veh_only, i, b"\x20")) for i in (1, 5, 25, 36)]
    lane_only = lane()
    out += [("a vehicle byte with only LANE set p[%d]" % i, setp(lane_only, i, b"\x20")) for i in (37, 44)]
    return out


@pytest.mark.parametrize("label,frame", _faults(), ids=[x[0] for x in _faults()])
def test_each_layout_fault_is_named_refused_by_decode_and_judged_10(label, frame):
    assert lf.layout_errors(frame), label
    with pytest.raises(lf.FrameError):
        lf.decode_request(frame)
    assert verdict(frame) == (1, 10), label


def test_layout_errors_of_the_frame_around_the_payload():
    good = lane()
    assert lf.layout_errors(good[:63]) == ["length 63, not 64"]
    assert lf.layout_errors(struct.pack("<Q", 0) + good[8:])
    assert lf.layout_errors(struct.pack("<Q", (1 << 64) - 1) + good[8:])
    assert lf.layout_errors(setp(good, 24, b"\x02")), "another kind"
    assert lf.layout_errors(setp(good, 6, b"\x01")), "a verdict in a request"
    assert lf.layout_errors(setp(good, 7, b"\x1c")), "a reason in a request"


def test_decode_reply_takes_the_monitors_verdict_and_reason_and_the_stamps():
    good = lane()
    assert lf.decode_reply(setp(good, 6, b"\x01\x1e")).reason == 30
    assert lf.decode_reply(good).verdict == 0
    for bad in (b"\x01\x00", b"\x00\x1e", b"\x02\x1e"):
        with pytest.raises(lf.FrameError):
            lf.decode_reply(setp(good, 6, bad))
    stamped = setp(setp(good, 6, b"\x00\x00"), 8, struct.pack("<QQ", 5, 9))
    with pytest.raises(lf.FrameError):
        lf.decode_reply(stamped)
    d = lf.decode_reply(stamped, stamp=True)
    assert (d.t_in_ns, d.t_out_ns) == (5, 9)
    assert lf.layout_errors(stamped, stamp=True) == []


# ============================================================ the sin polynomial

def test_the_sin_coefficients_are_the_doubles_nearest_1_over_odd_factorials():
    assert len(lr.SIN_COEFFS) == 5
    assert list(lr.SIN_COEFFS) == [(-1) ** k / math.factorial(2 * k + 1) for k in range(5)]


def test_lane_sin_is_odd_and_within_2e_11_of_math_sin_on_its_domain():
    xs = [i / 4096.0 * 0.5 for i in range(-4096, 4097)] + [0.5, -0.5, lf.f32(0.3), 1e-300, 5e-324]
    assert all(lr.lane_sin(-x) == -lr.lane_sin(x) for x in xs)
    assert max(abs(lr.lane_sin(x) - math.sin(x)) for x in xs) <= 2e-11
    assert lr.lane_sin(0.0) == 0.0 and lr.lane_sin(2.0 ** -30) == 2.0 ** -30


def test_lane_sin_is_horner_in_x_squared_highest_power_innermost():
    x = 0.4375
    x2 = x * x
    s = lr.SIN_COEFFS[4]
    for k in (3, 2, 1, 0):
        s = lr.SIN_COEFFS[k] + x2 * s
    assert lr.lane_sin(x) == x * s


# ============================================================ the judge, by hand

def test_honest_claims_are_accepted():
    for fr in (lane(), lane(speed=10.0, yaw_rate=0.1, offset=0.2, heading=-0.01), lf.encode(seq=1),
               lf.encode(seq=1, speed=30.0, yaw_rate=1.0), lane(conf=100, width=4.5, curvature=-0.09, heading=-0.5)):
        assert verdict(fr) == (0, 0)


def test_a_no_lane_claim_is_accepted_whatever_its_vehicle_values():
    for speed in (0.0, 1.0, 50.0, -3.0, 1e30):
        assert verdict(lf.encode(seq=1, speed=speed, yaw_rate=-2.0)) == (0, 0)


def test_rule_28_confidence():
    assert [verdict(lane(conf=c))[1] for c in (49, 50, 100)] == [28, 0, 0]
    assert verdict(lf.pack_bits(seq=1, flags=1, profile=1, conf=101, offset=0, heading=0, curvature=0,
                                width=lf.f32_bits(3.5))) == (1, 28)
    assert verdict(lane(conf=0)) == (1, 28)


def test_rule_29_each_limit_at_and_one_step_past():
    assert verdict(lane(width=2.5)) == (0, 0) and verdict(lane(width=down(2.5))) == (1, 29)
    assert verdict(lane(width=4.5)) == (0, 0) and verdict(lane(width=up(4.5))) == (1, 29)
    k = lf.f32(0.1)
    assert k > 0.1, "0.1 is not a binary32: its nearest lies above"
    for s in (1.0, -1.0):
        assert verdict(lane(curvature=s * down(k))) == (0, 0) and verdict(lane(curvature=s * k)) == (1, 29)
        assert verdict(lane(heading=s * 0.5)) == (0, 0) and verdict(lane(heading=s * up(0.5))) == (1, 29)


def test_rule_30_the_offset_against_half_the_width_less_half_the_vehicle():
    room = 3.5 / 2 - 0.95
    edge = lf.f32(room)
    edge = edge if edge <= room else down(edge)
    for s in (1.0, -1.0):
        assert verdict(lane(width=3.5, offset=s * edge)) == (0, 0)
        assert verdict(lane(width=3.5, offset=s * up(edge))) == (1, 30)


def _r31(off, h, sp, width=3.5, conf=90):
    return verdict(lane(width=width, offset=off, heading=h, speed=sp, yaw_rate=0.0, conf=conf))


def test_rule_31_needs_the_vehicle_moving_toward_the_nearer_line():
    # margin 0.8 - 0.75 = 0.05 m; at 10 m/s and 0.1 rad the lateral speed is about 1 m/s: under a second to the line
    assert _r31(0.75, 0.1, 10.0) == (1, 31)
    assert _r31(-0.75, -0.1, 10.0) == (1, 31)
    assert _r31(0.75, -0.1, 10.0) == (0, 0), "moving away from the left line"
    assert _r31(-0.75, 0.1, 10.0) == (0, 0), "moving away from the right line"
    assert _r31(0.0, 0.05, 10.0) == (0, 0), "a margin of 0.8 m at 0.5 m/s is not under a second"
    assert _r31(0.0, 0.1, 10.0) == (1, 31), "a margin of 0.8 m at 1 m/s is"
    assert _r31(0.0, 0.5, 10.0) == (1, 31), "on the centre any lateral speed is toward a line"
    assert _r31(0.0, -0.5, 10.0) == (1, 31)
    assert _r31(-0.0, -0.5, 10.0) == (1, 31), "-0.0 is the centre too"
    assert _r31(0.0, 0.0, 10.0) == (0, 0), "no lateral speed"
    assert _r31(0.75, 0.1, -10.0) == (0, 0), "reversing: not over V_MIN"
    assert _r31(0.75, 0.1, 1.0) == (0, 0), "at V_MIN exactly"
    assert _r31(0.75, 0.1, up(1.0)) == (1, 31)
    assert verdict(lane(width=3.5, offset=0.75, heading=0.1)) == (0, 0), "no vehicle values: rule 31 is not judged"


def test_rule_31_s_threshold_is_tlc_min_times_the_lateral_speed():
    # about 0.5 m of margin; |vl| = speed * sin(0.25): the edge speed is near 0.5 / sin(0.25), about 2.02 m/s, and the
    # judge's order of operations is (width / 2 - VEH_HALF_W) - |offset| against TLC_MIN * |speed * sin(heading)|
    h, off = 0.25, lf.f32(0.3)
    margin = (3.5 / 2 - 0.95) - off
    s = lr.lane_sin(h)
    sp = lf.f32(margin / s)
    while margin < 1.0 * (sp * s):
        sp = down(sp)
    while not margin < 1.0 * (sp * s):
        sp = up(sp)
    assert down(sp) > 1.0
    assert _r31(off, h, down(sp)) == (0, 0) and _r31(off, h, sp) == (1, 31)
    assert _r31(-off, -h, down(sp)) == (0, 0) and _r31(-off, -h, sp) == (1, 31)


def test_the_rule_31_predicate_alone_needs_veh():
    pr = lf.PROFILES[1]
    room = 3.5 / 2 - 0.95
    assert lr.imminent(pr, lf.F_LANE | lf.F_VEH, 0.75, 0.1, room, 10.0) is True
    assert lr.imminent(pr, lf.F_LANE, 0.75, 0.1, room, 10.0) is False, "VEH clear: never imminent, whatever the speed"
    assert lr.imminent(pr, lf.F_LANE | lf.F_VEH, 0.75, 0.1, room, 1.0) is False


ORDER_PAIRS = [
    ("10 before 9", lambda: setp(lf.pack_bits(seq=1, flags=1, profile=1, conf=90, offset=QNAN, heading=0, curvature=0,
                                              width=lf.f32_bits(3.5)), 0, b"\x05"), 10),
    ("9 before 8", lambda: lf.pack_bits(seq=1, flags=1, profile=0, conf=90, offset=QNAN, heading=0, curvature=0,
                                        width=lf.f32_bits(3.5)), 9),
    ("8 before 28", lambda: lf.pack_bits(seq=1, flags=1, profile=2, conf=10, offset=0, heading=0, curvature=0,
                                         width=lf.f32_bits(3.5)), 8),
    ("8 before the no-lane accept", lambda: lf.pack_bits(seq=1, flags=0, profile=0), 8),
    ("9 before the no-lane accept", lambda: lf.pack_bits(seq=1, flags=2, profile=1, speed=QNAN, yaw_rate=0), 9),
    ("9 on the yaw rate", lambda: lf.pack_bits(seq=1, flags=3, profile=1, conf=90, offset=0, heading=0, curvature=0,
                                               width=lf.f32_bits(3.5), speed=0, yaw_rate=0x7F800000), 9),
    ("28 before 29", lambda: lane(conf=10, width=9.0), 28),
    ("29 before 30", lambda: lane(width=9.0, offset=5.0), 29),
    ("30 before 31", lambda: lane(offset=0.9, heading=0.4, speed=30.0), 30),
]


@pytest.mark.parametrize("label,make,want", ORDER_PAIRS, ids=[x[0] for x in ORDER_PAIRS])
def test_the_order_between_adjacent_rules(label, make, want):
    assert verdict(make()) == (1, want), label


@pytest.mark.parametrize("bits", NONFINITE, ids=["%08X" % b for b in NONFINITE])
@pytest.mark.parametrize("slot", LANE_FIELDS + VEH_FIELDS)
def test_a_non_finite_present_value_is_9_in_each_slot(slot, bits):
    vals = dict(offset=0, heading=0, curvature=0, width=lf.f32_bits(3.5), speed=0, yaw_rate=0)
    vals[slot] = bits
    assert verdict(lf.pack_bits(seq=1, flags=3, profile=1, conf=90, **vals)) == (1, 9)


def test_finite_extremes_and_subnormals_are_judged_by_their_value():
    tiny = lf.bits_f32(1)
    assert verdict(lane(heading=tiny, curvature=-tiny, offset=tiny, speed=lf.bits_f32(0x7F7FFFFF), yaw_rate=-tiny)) == (0, 0)


def test_profile_0_and_every_id_but_1_are_8():
    for pid in (0, 2, 7, 255):
        assert verdict(lf.pack_bits(seq=1, flags=0, profile=pid)) == (1, 8)


def test_the_judge_reads_the_payload_bytes_and_ignores_the_request_s_verdict_and_reason():
    assert verdict(setp(lane(), 6, b"\xee\xee")) == (0, 0)


def test_the_judge_refuses_another_kind_a_sentinel_and_a_wrong_length():
    with pytest.raises(ValueError):
        lr.judge(setp(lane(), 24, b"\x02"))
    with pytest.raises(ValueError):
        lr.judge(struct.pack("<Q", (1 << 64) - 1) + lane()[8:])
    with pytest.raises(ValueError):
        lr.judge(lane()[:63])


def test_judge_takes_another_table():
    t = {7: _row(id=7, veh_half_w=0.75)}
    assert lr.judge(lane(profile=7, width=3.5, offset=1.0), t) == (0, 0)
    assert lr.judge(lane(profile=7, width=3.5, offset=up(1.0)), t) == (1, 30)
    assert lr.judge(lane(profile=1), t) == (1, 8)


def test_seeded_random_frames_reach_every_reason_and_never_raise():
    rng = random.Random(606)
    seen = set()
    for i in range(3000):
        flags = rng.choice((0, 1, 2, 3, 3, 3))
        vals = {}
        if flags & 1:
            vals.update(offset=lf.f32_bits(rng.uniform(-1.5, 1.5)), heading=lf.f32_bits(rng.uniform(-0.7, 0.7)),
                        curvature=lf.f32_bits(rng.uniform(-0.15, 0.15)), width=lf.f32_bits(rng.uniform(2, 5)))
        if flags & 2:
            vals.update(speed=lf.f32_bits(rng.uniform(-5, 40)), yaw_rate=lf.f32_bits(rng.uniform(-1, 1)))
        if vals and rng.random() < 0.05:
            vals[rng.choice(list(vals))] = rng.choice(NONFINITE)
        conf = rng.choice((rng.randrange(256), rng.randrange(50, 101), rng.randrange(50, 101))) if flags & 1 else 0
        fr = lf.pack_bits(seq=i + 1, flags=flags, profile=rng.choice((1, 1, 1, 0, 2)), conf=conf, **vals)
        if rng.random() < 0.05:
            fr = setp(fr, rng.choice((0, 8, 20, 30, 40)), bytes([rng.randrange(4, 256)]))
        seen.add(lr.judge(fr)[1])
    assert seen == {0, 8, 9, 10, 28, 29, 30, 31}, sorted(seen)


# ============================================================ the package's own rule (2.6)

def test_nothing_in_sdv_lane_imports_another_sdv_package_or_a_non_stdlib_module():
    files = sorted(LANE_DIR.glob("*.py"))
    assert {f.name for f in files} == {"laneframe.py", "lanerules.py", "laneclient.py"}, "no __init__.py (the next test says why)"
    own = {"laneframe", "lanerules"}
    stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert not node.level, (f.name, "a relative import, though sdv/lane is no package", node.module)
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for n in names:
                assert n != "sdv" and n not in ("rules", "vssframe", "ctlframe", "ctlrules"), (f.name, n)
                assert n in own or n == "__future__" or (stdlib is None or n in stdlib), (f.name, n)


def ci_mypy_paths():
    """The paths tooling.yml's one mypy command checks (the command and its continued lines), in its order."""
    lines = (REPO / ".github" / "workflows" / "tooling.yml").read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("mypy --no-incremental"))
    words = []
    for ln in lines[start:]:
        words += ln.strip().rstrip("\\").split()
        if not ln.rstrip().endswith("\\"):
            break
    return [w for w in words if w == "tests" or w.startswith(("scripts/", "sdv/"))]


def test_sdv_lane_is_no_package_so_ci_s_mypy_keeps_sdv_off_its_path():
    """CI's one mypy command (tooling.yml) checks sdv/lane together with tests and the other sdv directories. An
    __init__.py here would make mypy take sdv/ as this package's base and put it on its path, so `import stack` and
    `import inject` in the tests would resolve to the directories sdv/stack and sdv/inject as empty namespace packages
    (tests/test_sdv_carla.py holds the same for sdv/carla). So there is none, lanerules imports laneframe by name (the
    test above), and each module's name is its own among the paths that command checks beside it (mypy stops on two
    top-level modules of one name)."""
    assert not (LANE_DIR / "__init__.py").exists()
    paths = ci_mypy_paths()
    assert "sdv/lane" in paths and "tests" in paths and "sdv/ctl" in paths, paths
    mine = {p.stem for p in LANE_DIR.glob("*.py")}
    others = set()
    for rel in paths:
        if rel != "sdv/lane":
            p = REPO / rel
            others |= {p.stem} if p.suffix == ".py" else {q.stem for q in p.rglob("*.py")}
    assert mine == {"laneframe", "lanerules", "laneclient"} and not (mine & others), mine & others


def test_layout_errors_with_stamp_takes_a_stamped_reply_without_reply_true():
    # "stamp implies reply" (layout_errors' docstring): a stamped REJECT needs no reply=True beside stamp=True.
    stamped = setp(setp(lane(), 6, b"\x01\x1c"), 8, struct.pack("<QQ", 5, 9))
    assert lf.layout_errors(stamped, stamp=True) == []
    assert lf.layout_errors(stamped, reply=True) == ["p[8..23] non-zero"]
