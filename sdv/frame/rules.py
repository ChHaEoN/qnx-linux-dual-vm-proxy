"""rules.py -- the Python reference judge of kind 4 (sdv/frame): reasons 8, 9, 10 and 21-27.

The kind 4 wire specification (the project's local design notes,
sections 3, 6, 7 and 8; not in this tree) defines the rules; this module is the oracle the C monitor
(`check_vss()` under MONITOR_EXT_KINDS) will be tested against in Phase 2, frame by frame. So it is written
the way the C sketch is: it reads the payload bytes itself (never through the codec's decode, which
refuses what reason 10 must judge), evaluates in the specification's order and returns the first
failure, and computes rule 26 with the same expression, operation order, polynomial tan and generated
constants.

    order: 10, 8, 21, 9, 22, 23, 24, 25, 26, 27; the first failure wins; comparisons strict (a value
    exactly at a limit is accepted); window bounds inclusive.

    rule 26, units in the formula (specification 7.1):
      L_m [m]             = L [mm] * M_PER_MM
      psi_dot_kin [deg/s] = DEG_PER_RAD * |v| [m/s] * tan(|delta| [deg] * RAD_PER_DEG) / L_m [m]
      a_y_kin [m/s^2]     = |v| [m/s] * psi_dot_kin [deg/s] * RAD_PER_DEG
      reject iff b0, b2, b3; v26_lo <= |v| <= v26_hi; (no a_y bound, or a_y_kin <= the bound);
                 and | |psi_dot| - psi_dot_kin | > tol

Stateless: the verdict is a function of the 48 payload bytes and the compiled tables only. The
tables come from the generated contract; by default only the profiles the specification has the guest
compile (COMPILED_PROFILE_IDS) are bound, so an uncompiled profile gets 8 here, as the Phase 2 guest
will give it. A test may bind another profile of the Python table explicitly
(`Tables.from_contract(extra_ids=...)`), which is how the specification's a_y-bound tests use profile 3
before it is compiled, or a profile of its own (`profiles=`, under an id no bound profile has).

The a_y bound is None in the Python profile table and 0.0 in the C table; both mean "no bound" here.
"""
from __future__ import annotations

import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import vssframe as vf  # noqa: E402

V_ACCEPT = 0
V_REJECT = 1

RSN_OK = 0
RSN_KIND_UNKNOWN = 5
RSN_PROFILE_UNBOUND = 8
RSN_NOT_FINITE = 9
RSN_FLAGS_INVALID = 10
RSN_VSS_CATALOG = 21
RSN_VSS_STALE = 22
RSN_VSS_SPEED = 23
RSN_VSS_ACCEL = 24
RSN_VSS_STEER = 25
RSN_VSS_YAW = 26
RSN_VSS_GEAR = 27

REASON_NAMES = {
    RSN_OK: "ok",
    RSN_PROFILE_UNBOUND: "profile-unbound",
    RSN_NOT_FINITE: "field-not-finite",
    RSN_FLAGS_INVALID: "flags-invalid",
    RSN_VSS_CATALOG: "vss-catalog-mismatch",
    RSN_VSS_STALE: "vss-stale",
    RSN_VSS_SPEED: "vss-speed",
    RSN_VSS_ACCEL: "vss-accel",
    RSN_VSS_STEER: "vss-steer",
    RSN_VSS_YAW: "vss-yaw-inconsistent",
    RSN_VSS_GEAR: "vss-gear-direction",
}

ORDER = (RSN_FLAGS_INVALID, RSN_PROFILE_UNBOUND, RSN_VSS_CATALOG, RSN_NOT_FINITE, RSN_VSS_STALE,
         RSN_VSS_SPEED, RSN_VSS_ACCEL, RSN_VSS_STEER, RSN_VSS_YAW, RSN_VSS_GEAR)

# --- tan without libm (specification 7.2) -------------------------------------------------------
# s(x) is the Taylor polynomial of sin through x^13, c(x) that of cos through x^14, both by Horner in
# x^2, in double. The specification fixes the degrees, Horner and the error bound (1e-9 on [0, 1]);
# it does not fix the coefficient literals or the Horner arrangement. These are: each coefficient
# the double nearest (-1)^k / n!, from Python's correctly rounded int division, innermost term the
# highest power. The C monitor should use these exact doubles in this arrangement (printed with
# %.17g) to agree bit for bit where the compiler does not contract; otherwise it relies on the 1e-9
# margin, as the specification allows.
TAN_SIN_COEFFS = tuple((-1.0 if k % 2 else 1.0) / math.factorial(2 * k + 1) for k in range(7))   # x^1 .. x^13
TAN_COS_COEFFS = tuple((-1.0 if k % 2 else 1.0) / math.factorial(2 * k) for k in range(8))       # x^0 .. x^14
TAN_DOMAIN_MAX = 1.0      # rad; rule 25 and the profile invariant delta_max <= 57 deg (enforced by Profile) keep |delta| inside


def vss_tan(x: float) -> float:
    """tan(x) = s(x) / c(x) for 0 <= x <= 1.0 rad, no libm."""
    if not (x >= 0.0 and x <= TAN_DOMAIN_MAX):
        raise ValueError("vss_tan: %r outside [0, %r] rad (a profile invariant is broken)" % (x, TAN_DOMAIN_MAX))
    x2 = x * x
    s = TAN_SIN_COEFFS[6]
    for c in TAN_SIN_COEFFS[5::-1]:
        s = c + x2 * s
    s = x * s
    co = TAN_COS_COEFFS[7]
    for c in TAN_COS_COEFFS[6::-1]:
        co = c + x2 * co
    return s / co


def dabs(x: float) -> float:
    """The C sketch's `x < 0.0 ? -x : x` (keeps -0.0 as -0.0, unlike abs())."""
    return -x if x < 0.0 else x


# --- the compiled tables -------------------------------------------------------------------------

# The bounds specification 5.4 puts on a profile row, the ones sdv/vss/generate.py checks on profiles.toml
# (its L_MM_MIN, L_MM_MAX, DELTA_MAX_LIMIT_DEG, PSI_DOT_KIN_ERROR_BOUND, TOL_OVER_ERROR_MIN and F32_LIMITS).
# They are not exported into the generated contract, so they are written here too, and
# tests/test_sdv_frame.py compares the two copies. `Profile` makes every numeric row check the generator
# makes, so a profile built by hand never has a number the generator would have refused (delta_max above
# 57 degrees would leave vss_tan's domain mid-judgement, where the C monitor's s/c would just return a
# verdict; a limit that is not a binary32 has no "next f32 above" to test its edge with). What only the
# generator checks is the row's place in the table: its id, its envelope and wheelbase, its compiled flag.
L_MM_MIN = 1000
L_MM_MAX = 6000
DELTA_MAX_LIMIT_DEG = 57.0
PSI_DOT_KIN_ERROR_BOUND = 1.0e-5      # spec 7.3: the design bound of psi_dot_kin against Python's math, deg/s
TOL_OVER_ERROR_MIN = 1.0e5            # spec 5.4: tol26 must exceed that bound by at least this factor
TOL26_MIN = PSI_DOT_KIN_ERROR_BOUND * TOL_OVER_ERROR_MIN          # the product, as the generator writes it
F32_LIMITS = ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "v_tol")     # limits a frame field is compared with
_NUMERIC_FIELDS = ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "ay26_max", "tol26", "v_tol")
assert math.radians(DELTA_MAX_LIMIT_DEG) <= TAN_DOMAIN_MAX


def _f32_exact(x: Any) -> bool:
    """float32(x) == x, which is how the generator asks whether a limit is a binary32 (an overflow is not one)."""
    try:
        return bool(vf.f32(x) == x)
    except (vf.FrameError, OverflowError):
        return False


@dataclass(frozen=True)
class Profile:
    id: int
    l_mm: int
    v_max: float
    a_max: float
    delta_max: float
    v26_lo: float
    v26_hi: float
    ay26_max: float        # 0.0 = no a_y bound
    tol26: float
    v_tol: float

    def __post_init__(self) -> None:
        """Refuse a row that breaks the numeric bounds of specification 5.4, each one as the generator does:
        l_mm an integer in range, every number a number (a bool is not one), the four positive limits, the
        delta_max and v26 windows, tol26 at least TOL26_MIN, every F32_LIMITS entry a binary32, ay26_max
        0.0 or positive, and the id an int (not a bool). Id 0's reservation is Tables' to refuse; the id
        range, envelope and compiled flag are the generator's. Nothing here converts: `from_row` hands a
        contract row's values over as they are, so these checks judge the row itself."""
        bad = []
        if isinstance(self.id, bool) or not isinstance(self.id, int):
            bad.append("id %r not an int" % (self.id,))
        if isinstance(self.l_mm, bool) or not isinstance(self.l_mm, int) or not L_MM_MIN <= self.l_mm <= L_MM_MAX:
            bad.append("l_mm %r not an integer in %d..%d" % (self.l_mm, L_MM_MIN, L_MM_MAX))
        nonnum = [n for n in _NUMERIC_FIELDS
                  if isinstance(getattr(self, n), bool) or not isinstance(getattr(self, n), (int, float))]
        if nonnum:                                               # the checks below compare numbers
            bad.append("%s must be numbers (not bool)" % ", ".join(nonnum))
            raise ValueError("profile %r: %s" % (self.id, "; ".join(bad)))
        for name in ("v_max", "a_max", "tol26", "v_tol"):
            if not getattr(self, name) > 0:                      # a NaN fails too
                bad.append("%s %r not > 0" % (name, getattr(self, name)))
        if not 0 < self.delta_max <= DELTA_MAX_LIMIT_DEG:
            bad.append("delta_max %r not in (0, %r] (the tan domain)" % (self.delta_max, DELTA_MAX_LIMIT_DEG))
        if not 0 < self.v26_lo < self.v26_hi:
            bad.append("need 0 < v26_lo < v26_hi, got %r, %r" % (self.v26_lo, self.v26_hi))
        if self.tol26 < TOL26_MIN:
            bad.append("tol26 %r below %r (the rule-26 error bound %r x %r)"
                       % (self.tol26, TOL26_MIN, PSI_DOT_KIN_ERROR_BOUND, TOL_OVER_ERROR_MIN))
        for name in F32_LIMITS:
            if not _f32_exact(getattr(self, name)):
                bad.append("%s %r is not exactly representable in binary32" % (name, getattr(self, name)))
        if not (self.ay26_max == 0.0 or self.ay26_max > 0):
            bad.append("ay26_max %r not 0.0 (no bound) or > 0" % (self.ay26_max,))
        if bad:
            raise ValueError("profile %r: %s" % (self.id, "; ".join(bad)))

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Profile":
        """A row of the generated contract's PROFILES. Only ay26_max is mapped (None, "no bound", is 0.0 in the
        compiled table); every value else goes to `__post_init__` as it is, so a float l_mm, a string or a
        bool in a hand-edited row is refused there instead of being converted into something valid."""
        ay = row["ay26_max"]
        return cls(id=row["id"], l_mm=row["l_mm"], v_max=row["v_max"], a_max=row["a_max"],
                   delta_max=row["delta_max"], v26_lo=row["v26_lo"], v26_hi=row["v26_hi"],
                   ay26_max=0.0 if ay is None else ay, tol26=row["tol26"], v_tol=row["v_tol"])


@dataclass(frozen=True)
class Tables:
    """What the specification has the guest compile in: the profiles, the digest, AGE_MAX and the
    conversion constants."""
    profiles: Mapping[int, Profile]
    digest: int
    age_max_ms: int
    deg_per_rad: float
    rad_per_deg: float
    m_per_mm: float

    @classmethod
    def from_contract(cls, contract: Any = None, extra_ids: Iterable[int] = (),
                      profiles: Optional[Iterable[Profile]] = None) -> "Tables":
        """The compiled profiles of the contract, plus the contract's rows named in extra_ids, plus the
        hand-built `profiles`. A hand-built profile never replaces one: an id that is already bound (a
        compiled one, one of extra_ids, or an earlier hand-built profile) is a ValueError, and so is id 0."""
        c = contract if contract is not None else vf.load_contract()
        rows = {int(r["id"]): r for r in c.PROFILES}
        bound: Dict[int, Profile] = {}
        for pid in tuple(c.COMPILED_PROFILE_IDS) + tuple(extra_ids):
            if pid not in rows:
                raise KeyError("profile %d is not in the generated table" % pid)
            bound[pid] = Profile.from_row(rows[pid])
        for p in profiles or ():
            if p.id in bound:
                raise ValueError("profile %d is already bound (a compiled profile, one of extra_ids or an earlier hand-built "
                                 "profile): a hand-built profile needs a new id" % p.id)
            bound[p.id] = p
        if 0 in bound:
            raise ValueError("profile id 0 is reserved and never bound")
        return cls(profiles=bound, digest=int(c.CATALOG_DIGEST), age_max_ms=int(c.AGE_MAX_MS),
                   deg_per_rad=float(c.DEG_PER_RAD), rad_per_deg=float(c.RAD_PER_DEG), m_per_mm=float(c.M_PER_MM))


# --- rule 26's computation ---------------------------------------------------------------------

def kinematics(av: float, ad: float, l_mm: int, t: Tables) -> Tuple[float, float]:
    """(psi_dot_kin [deg/s], a_y_kin [m/s^2]) from |v| [m/s], |delta| [deg] and L [mm], evaluated
    exactly as the C sketch: left to right, L multiplied by M_PER_MM, never divided by 1000."""
    l_m = float(l_mm) * t.m_per_mm
    kin = t.deg_per_rad * av * vss_tan(ad * t.rad_per_deg) / l_m
    ay = av * kin * t.rad_per_deg
    return kin, ay


# --- the judge -----------------------------------------------------------------------------------

def _u16(p: bytes, off: int) -> int:
    return p[off] | (p[off + 1] << 8)


def _u32(p: bytes, off: int) -> int:
    return p[off] | (p[off + 1] << 8) | (p[off + 2] << 16) | (p[off + 3] << 24)


def _f32(p: bytes, off: int) -> float:
    return struct.unpack("<f", struct.pack("<I", _u32(p, off)))[0]


def _absent_slot_nonzero(p: bytes, f: int) -> bool:
    for slot, (lo, hi) in enumerate(vf.SLOT_SPANS):
        if not f & (1 << slot) and any(p[lo:hi]):
            return True
    return False


def _present_nonfinite(p: bytes, f: int) -> bool:
    for slot, off in enumerate(vf.F32_SLOT_OFFSETS):
        if f & (1 << slot) and ((_u32(p, off) >> 23) & 0xFF) == 0xFF:
            return True
    return False


def check_vss(payload: bytes, t: Tables) -> Tuple[int, int]:
    """(verdict, reason) of one kind 4 payload (48 bytes), in the specification's order."""
    p = bytes(payload)
    if len(p) != vf.FRAME_PAYLOAD_BYTES:
        raise ValueError("payload of %d bytes, not %d" % (len(p), vf.FRAME_PAYLOAD_BYTES))
    f = p[vf.P_FLAGS]
    # 10
    if ((f & vf.F_RESERVED) or any(p[8:24]) or any(p[44:48]) or _absent_slot_nonzero(p, f)
            or ((f & vf.F_SLOTS) == 0 and (p[vf.P_AGE] | p[vf.P_AGE + 1]))):
        return V_REJECT, RSN_FLAGS_INVALID
    # 8
    pr = t.profiles.get(p[vf.P_PROFILE])
    if pr is None:
        return V_REJECT, RSN_PROFILE_UNBOUND
    # 21
    if _u32(p, vf.P_DIGEST) != t.digest:
        return V_REJECT, RSN_VSS_CATALOG
    # 9
    if _present_nonfinite(p, f):
        return V_REJECT, RSN_NOT_FINITE
    # 22
    if _u16(p, vf.P_AGE) > t.age_max_ms:
        return V_REJECT, RSN_VSS_STALE
    v, ax, d, y = _f32(p, vf.P_V), _f32(p, vf.P_AX), _f32(p, vf.P_DELTA), _f32(p, vf.P_PSI_DOT)
    g = p[vf.P_GEAR] - 256 if p[vf.P_GEAR] > 127 else p[vf.P_GEAR]
    av, ad = dabs(v), dabs(d)
    # 23, 24, 25
    if (f & vf.F_SPEED) and av > pr.v_max:
        return V_REJECT, RSN_VSS_SPEED
    if (f & vf.F_ACCEL) and dabs(ax) > pr.a_max:
        return V_REJECT, RSN_VSS_ACCEL
    if (f & vf.F_STEER) and ad > pr.delta_max:
        return V_REJECT, RSN_VSS_STEER
    # 26
    need = vf.F_SPEED | vf.F_STEER | vf.F_YAW
    if (f & need) == need and pr.v26_lo <= av <= pr.v26_hi:
        kin, ay = kinematics(av, ad, pr.l_mm, t)
        if (pr.ay26_max == 0.0 or ay <= pr.ay26_max) and dabs(dabs(y) - kin) > pr.tol26:
            return V_REJECT, RSN_VSS_YAW
    # 27
    need = vf.F_SPEED | vf.F_GEAR
    if (f & need) == need and ((g > 0 and v < -pr.v_tol) or (g < 0 and v > pr.v_tol)):
        return V_REJECT, RSN_VSS_GEAR
    return V_ACCEPT, RSN_OK


def judge_frame(frame: bytes, t: Tables) -> Optional[Tuple[int, int]]:
    """(verdict, reason) of a 64-byte kind 4 request; None for a sentinel (echoed, never judged).

    Only kind 4 is this oracle's: any other kind byte is refused (the monitor's own kinds 0 and 1 and
    its unknown-kind reason 5 are outside it)."""
    frame = bytes(frame)
    if len(frame) != vf.FRAME_TOTAL_BYTES:
        raise ValueError("frame of %d bytes, not %d" % (len(frame), vf.FRAME_TOTAL_BYTES))
    if struct.unpack_from("<Q", frame, 0)[0] == vf.SENTINEL_SEQ:
        return None
    payload = frame[vf.FRAME_HEADER_BYTES:]
    if payload[vf.P_KIND] != vf.KIND_VSS:
        raise ValueError("kind %d is not kind 4" % payload[vf.P_KIND])
    return check_vss(payload, t)


def reply(frame: bytes, t: Tables) -> bytes:
    """The monitor's (non-stamp) reply: the request with only p[6] and p[7] written."""
    res = judge_frame(frame, t)
    if res is None:
        return bytes(frame)
    out = bytearray(frame)
    out[vf.FRAME_HEADER_BYTES + vf.P_VERDICT], out[vf.FRAME_HEADER_BYTES + vf.P_REASON] = res
    return bytes(out)
