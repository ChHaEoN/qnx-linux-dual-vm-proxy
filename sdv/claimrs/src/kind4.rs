//! The kind 4 codec: `vssframe.py`'s `fnv1_32`, `digest_of`, `pack_bits`, `encode`, `layout_errors`,
//! `decode` and `age_field`, with the same refusals in the same order.
//!
//! A refusal has a stable code ([`LayoutError::code`], [`EncodeError::code`]); its text is for people
//! and is never compared. The types take over most of `pack_bits`' range checks (profile `u8`, digest
//! `u32`, age `u16`, gear `i8`, seq and tstamp `u64`); what is left is the seq (not 0, not the sentinel),
//! a present value that is not a finite binary32, and an age with no value present.

use std::fmt;

use crate::frame::{
    AGE_SATURATED, F_GEAR, F_RESERVED, F_SLOTS, F32_SLOT_OFFSETS, FRAME_HEADER_BYTES,
    FRAME_TOTAL_BYTES, Frame, KIND_VSS, P_AGE, P_DIGEST, P_FLAGS, P_GEAR, P_KIND, P_PROFILE,
    P_REASON, P_T_IN, P_T_OUT, P_VERDICT, RESERVED_SPAN, SENTINEL_SEQ, SLOT_SPANS, STAMP_SPAN,
    slot_flag,
};

/// FNV-1 32's offset basis and prime.
pub const FNV1_OFFSET: u32 = 0x811C_9DC5;
pub const FNV1_PRIME: u32 = 0x0100_0193;

/// FNV-1 32 (multiply, then xor; not FNV-1a): the hash vss-tools uses for staticUIDs.
pub fn fnv1_32(data: &[u8]) -> u32 {
    let mut h = FNV1_OFFSET;
    for &b in data {
        h = h.wrapping_mul(FNV1_PRIME);
        h ^= u32::from(b);
    }
    h
}

/// The catalogue digest: FNV-1 32 over the slot UIDs as u32 little-endian, in slot order.
pub fn digest_of(uids: &[u32]) -> u32 {
    let bytes: Vec<u8> = uids.iter().flat_map(|u| u.to_le_bytes()).collect();
    fnv1_32(&bytes)
}

/// Why `encode` or `pack_bits` refused (codes `overflow`, `not-finite`, `seq-zero`, `seq-sentinel`,
/// `age-without-value`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EncodeError {
    /// A finite value whose binary32 rounding is infinite.
    Overflow {
        slot: usize,
    },
    /// An infinity or a NaN given as a value.
    NotFinite {
        slot: usize,
    },
    SeqZero,
    SeqSentinel,
    AgeWithoutValue {
        age_ms: u16,
    },
}

impl EncodeError {
    pub fn code(&self) -> &'static str {
        match self {
            EncodeError::Overflow { .. } => "overflow",
            EncodeError::NotFinite { .. } => "not-finite",
            EncodeError::SeqZero => "seq-zero",
            EncodeError::SeqSentinel => "seq-sentinel",
            EncodeError::AgeWithoutValue { .. } => "age-without-value",
        }
    }
}

impl fmt::Display for EncodeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            EncodeError::Overflow { slot } => write!(f, "slot {slot}: does not fit a binary32"),
            EncodeError::NotFinite { slot } => write!(f, "slot {slot}: not finite"),
            EncodeError::SeqZero => write!(f, "seq 0 (the bridge counts from 1)"),
            EncodeError::SeqSentinel => write!(f, "seq is the sentinel (a keepalive, not a claim)"),
            EncodeError::AgeWithoutValue { age_ms } => {
                write!(f, "age {age_ms} ms with no value present")
            }
        }
    }
}

impl std::error::Error for EncodeError {}

/// One kind 4 claim as the bridge packs it. `None` is an absent slot (its flag clear).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Claim {
    pub seq: u64,
    pub tstamp_ns: u64,
    pub profile: u8,
    pub digest: u32,
    /// m/s
    pub v: Option<f64>,
    /// m/s^2
    pub a_x: Option<f64>,
    /// degrees
    pub delta: Option<f64>,
    /// degrees/s
    pub psi_dot: Option<f64>,
    pub gear: Option<i8>,
    pub age_ms: u16,
}

impl Claim {
    /// A claim with every slot absent and age 0.
    pub fn new(seq: u64, tstamp_ns: u64, profile: u8, digest: u32) -> Claim {
        Claim {
            seq,
            tstamp_ns,
            profile,
            digest,
            v: None,
            a_x: None,
            delta: None,
            psi_dot: None,
            gear: None,
            age_ms: 0,
        }
    }

    /// The four f32 slots in slot order.
    pub fn floats(&self) -> [Option<f64>; 4] {
        [self.v, self.a_x, self.delta, self.psi_dot]
    }
}

fn check_seq(seq: u64) -> Result<(), EncodeError> {
    if seq == 0 {
        return Err(EncodeError::SeqZero);
    }
    if seq == SENTINEL_SEQ {
        return Err(EncodeError::SeqSentinel);
    }
    Ok(())
}

/// The binary32 bits of a slot's value: rounded to nearest, ties to even. A finite value whose rounding
/// is infinite is `Overflow`; an infinity or a NaN given is `NotFinite`.
pub fn slot_bits(slot: usize, x: f64) -> Result<u32, EncodeError> {
    let y = x as f32;
    if y.is_infinite() && x.is_finite() {
        return Err(EncodeError::Overflow { slot });
    }
    if !y.is_finite() {
        return Err(EncodeError::NotFinite { slot });
    }
    Ok(y.to_bits())
}

fn presence_flags(slot_bits: &[Option<u32>; 4], gear: Option<i8>) -> u8 {
    let mut flags = 0;
    for (slot, b) in slot_bits.iter().enumerate() {
        if b.is_some() {
            flags |= slot_flag(slot);
        }
    }
    if gear.is_some() {
        flags |= F_GEAR;
    }
    flags
}

/// Pack a request from raw parts: `slot_bits` are the four f32 slots' binary32 bits, any pattern.
/// Refuses, in this order, a zero or sentinel seq and an age with no value present.
pub fn pack_bits(
    seq: u64,
    tstamp_ns: u64,
    profile: u8,
    digest: u32,
    slot_bits: [Option<u32>; 4],
    gear: Option<i8>,
    age_ms: u16,
) -> Result<Frame, EncodeError> {
    check_seq(seq)?;
    let flags = presence_flags(&slot_bits, gear);
    if flags == 0 && age_ms != 0 {
        return Err(EncodeError::AgeWithoutValue { age_ms });
    }
    let mut f = [0u8; FRAME_TOTAL_BYTES];
    f[0..8].copy_from_slice(&seq.to_le_bytes());
    f[8..16].copy_from_slice(&tstamp_ns.to_le_bytes());
    let p = &mut f[FRAME_HEADER_BYTES..];
    p[P_FLAGS] = flags;
    p[P_PROFILE] = profile;
    p[P_DIGEST..P_DIGEST + 4].copy_from_slice(&digest.to_le_bytes());
    p[P_KIND] = KIND_VSS;
    for (off, b) in F32_SLOT_OFFSETS.iter().zip(slot_bits) {
        if let Some(bits) = b {
            p[*off..*off + 4].copy_from_slice(&bits.to_le_bytes());
        }
    }
    p[P_AGE..P_AGE + 2].copy_from_slice(&age_ms.to_le_bytes());
    if let Some(g) = gear {
        p[P_GEAR] = g.to_le_bytes()[0];
    }
    Ok(f)
}

/// Pack an honest claim: every present value finite and inside binary32. Checks the slots in order
/// (the first bad one is reported), then what `pack_bits` checks.
pub fn encode(claim: &Claim) -> Result<Frame, EncodeError> {
    let mut bits = [None; 4];
    for (slot, x) in claim.floats().into_iter().enumerate() {
        if let Some(x) = x {
            bits[slot] = Some(slot_bits(slot, x)?);
        }
    }
    pack_bits(
        claim.seq,
        claim.tstamp_ns,
        claim.profile,
        claim.digest,
        bits,
        claim.gear,
        claim.age_ms,
    )
}

/// What a frame is read as: a request (verdict and reason zero), the monitor's reply, or a stamp reply,
/// which is a reply that also carries t_in and t_out at p[8..23].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Request,
    Reply,
    Stamp,
}

impl Mode {
    /// A stamp reply is a reply.
    pub fn is_reply(self) -> bool {
        !matches!(self, Mode::Request)
    }
}

/// One refusal of `layout_errors`, one variant per branch (the slot branch one code per slot).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LayoutError {
    Length { len: usize },
    SeqSentinel,
    SeqZero,
    Kind { kind: u8 },
    FlagsReserved { bits: u8 },
    RequestVerdict,
    ReplyVerdict { verdict: u8 },
    ReplyReason { verdict: u8, reason: u8 },
    StampSpan,
    ReservedSpan,
    AbsentSlot { slot: usize },
    AgeWithoutValue,
}

const ABSENT_SLOT_CODES: [&str; 5] = [
    "absent-slot-0",
    "absent-slot-1",
    "absent-slot-2",
    "absent-slot-3",
    "absent-slot-4",
];

impl LayoutError {
    pub fn code(&self) -> &'static str {
        match self {
            LayoutError::Length { .. } => "length",
            LayoutError::SeqSentinel => "seq-sentinel",
            LayoutError::SeqZero => "seq-zero",
            LayoutError::Kind { .. } => "kind",
            LayoutError::FlagsReserved { .. } => "flags-reserved",
            LayoutError::RequestVerdict => "request-verdict",
            LayoutError::ReplyVerdict { .. } => "reply-verdict",
            LayoutError::ReplyReason { .. } => "reply-reason",
            LayoutError::StampSpan => "stamp-span",
            LayoutError::ReservedSpan => "reserved-span",
            LayoutError::AbsentSlot { slot } => ABSENT_SLOT_CODES[*slot],
            LayoutError::AgeWithoutValue => "age-without-value",
        }
    }
}

impl fmt::Display for LayoutError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            LayoutError::Length { len } => write!(f, "length {len}, not {FRAME_TOTAL_BYTES}"),
            LayoutError::SeqSentinel => write!(f, "seq is the sentinel (a keepalive, not a claim)"),
            LayoutError::SeqZero => write!(f, "seq 0 (the bridge counts from 1)"),
            LayoutError::Kind { kind } => write!(f, "kind {kind}, not {KIND_VSS}"),
            LayoutError::FlagsReserved { bits } => write!(f, "reserved flag bits 0x{bits:02X}"),
            LayoutError::RequestVerdict => write!(f, "verdict/reason bytes non-zero in a request"),
            LayoutError::ReplyVerdict { verdict } => write!(f, "verdict {verdict}"),
            LayoutError::ReplyReason { verdict, reason } => {
                write!(f, "verdict {verdict} with reason {reason}")
            }
            LayoutError::StampSpan => write!(f, "p[8..23] non-zero"),
            LayoutError::ReservedSpan => write!(f, "reserved p[44..47] non-zero"),
            LayoutError::AbsentSlot { slot } => {
                write!(f, "slot {slot} absent but its bytes are non-zero")
            }
            LayoutError::AgeWithoutValue => write!(f, "age non-zero with no value present"),
        }
    }
}

impl std::error::Error for LayoutError {}

fn any_nonzero(bytes: &[u8]) -> bool {
    bytes.iter().any(|&b| b != 0)
}

fn u16_at(p: &[u8], off: usize) -> u16 {
    u16::from_le_bytes([p[off], p[off + 1]])
}

fn u32_at(p: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([p[off], p[off + 1], p[off + 2], p[off + 3]])
}

fn u64_at(p: &[u8], off: usize) -> u64 {
    let mut b = [0u8; 8];
    b.copy_from_slice(&p[off..off + 8]);
    u64::from_le_bytes(b)
}

/// Everything that makes these bytes not a well-formed kind 4 frame in this mode (empty: well formed).
/// A wrong length is reported alone, as `vssframe.layout_errors` does.
pub fn layout_errors(frame: &[u8], mode: Mode) -> Vec<LayoutError> {
    if frame.len() != FRAME_TOTAL_BYTES {
        return vec![LayoutError::Length { len: frame.len() }];
    }
    let mut errs = Vec::new();
    let seq = u64_at(frame, 0);
    if seq == SENTINEL_SEQ {
        errs.push(LayoutError::SeqSentinel);
    } else if seq == 0 {
        errs.push(LayoutError::SeqZero);
    }
    let p = &frame[FRAME_HEADER_BYTES..];
    if p[P_KIND] != KIND_VSS {
        errs.push(LayoutError::Kind { kind: p[P_KIND] });
    }
    let f = p[P_FLAGS];
    if f & F_RESERVED != 0 {
        errs.push(LayoutError::FlagsReserved {
            bits: f & F_RESERVED,
        });
    }
    let (verdict, reason) = (p[P_VERDICT], p[P_REASON]);
    if !mode.is_reply() {
        if verdict != 0 || reason != 0 {
            errs.push(LayoutError::RequestVerdict);
        }
    } else if verdict > 1 {
        errs.push(LayoutError::ReplyVerdict { verdict });
    } else if (verdict == 0) != (reason == 0) {
        errs.push(LayoutError::ReplyReason { verdict, reason });
    }
    if mode != Mode::Stamp && any_nonzero(&p[STAMP_SPAN.0..STAMP_SPAN.1]) {
        errs.push(LayoutError::StampSpan);
    }
    if any_nonzero(&p[RESERVED_SPAN.0..RESERVED_SPAN.1]) {
        errs.push(LayoutError::ReservedSpan);
    }
    for (slot, &(lo, hi)) in SLOT_SPANS.iter().enumerate() {
        if f & slot_flag(slot) == 0 && any_nonzero(&p[lo..hi]) {
            errs.push(LayoutError::AbsentSlot { slot });
        }
    }
    if f & F_SLOTS == 0 && u16_at(p, P_AGE) != 0 {
        errs.push(LayoutError::AgeWithoutValue);
    }
    errs
}

/// A well-formed kind 4 frame's fields.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Decoded {
    pub seq: u64,
    pub tstamp_ns: u64,
    pub flags: u8,
    pub profile: u8,
    pub digest: u32,
    pub slot_bits: [Option<u32>; 4],
    pub gear: Option<i8>,
    pub age_ms: u16,
    pub verdict: u8,
    pub reason: u8,
    /// Stamp mode only.
    pub t_in_ns: Option<u64>,
    pub t_out_ns: Option<u64>,
}

impl Decoded {
    /// Slot `slot`'s value widened to a double (a signalling NaN may come back quieted: keep the bits).
    pub fn value(&self, slot: usize) -> Option<f64> {
        self.slot_bits[slot].map(|b| f64::from(f32::from_bits(b)))
    }
}

/// Unpack a kind 4 frame in this mode, or every refusal `layout_errors` finds.
pub fn decode(frame: &[u8], mode: Mode) -> Result<Decoded, Vec<LayoutError>> {
    let errs = layout_errors(frame, mode);
    if !errs.is_empty() {
        return Err(errs);
    }
    let p = &frame[FRAME_HEADER_BYTES..];
    let flags = p[P_FLAGS];
    let mut slot_bits = [None; 4];
    for (slot, &off) in F32_SLOT_OFFSETS.iter().enumerate() {
        if flags & slot_flag(slot) != 0 {
            slot_bits[slot] = Some(u32_at(p, off));
        }
    }
    let gear = if flags & F_GEAR != 0 {
        Some(i8::from_le_bytes([p[P_GEAR]]))
    } else {
        None
    };
    let stamp = mode == Mode::Stamp;
    Ok(Decoded {
        seq: u64_at(frame, 0),
        tstamp_ns: u64_at(frame, 8),
        flags,
        profile: p[P_PROFILE],
        digest: u32_at(p, P_DIGEST),
        slot_bits,
        gear,
        age_ms: u16_at(p, P_AGE),
        verdict: p[P_VERDICT],
        reason: p[P_REASON],
        t_in_ns: stamp.then(|| u64_at(p, P_T_IN)),
        t_out_ns: stamp.then(|| u64_at(p, P_T_OUT)),
    })
}

/// The age of the oldest used value at packing: (now - oldest) truncated to ms, saturated at 0xFFFF;
/// a negative difference is sent as 0 and reported (`true`). No value used gives `(0, false)`.
pub fn age_field(now_ns: u64, samples: &[u64]) -> (u16, bool) {
    let Some(&oldest) = samples.iter().min() else {
        return (0, false);
    };
    let Some(diff) = now_ns.checked_sub(oldest) else {
        return (0, true);
    };
    let ms = (diff / 1_000_000).min(u64::from(AGE_SATURATED));
    (u16::try_from(ms).unwrap_or(AGE_SATURATED), false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::frame::{F_SPEED, P_DELTA, P_PSI_DOT, P_RESERVED, P_V};

    const D: u32 = 0x1234_5678;

    /// A frame written from the layout table, byte by byte: seq, tstamp, then payload bytes.
    fn hand(seq: u64, tstamp: u64, payload: &[(usize, &[u8])]) -> Frame {
        let mut f = [0u8; FRAME_TOTAL_BYTES];
        f[..8].copy_from_slice(&seq.to_le_bytes());
        f[8..16].copy_from_slice(&tstamp.to_le_bytes());
        for (off, bytes) in payload {
            f[16 + off..16 + off + bytes.len()].copy_from_slice(bytes);
        }
        f
    }

    fn codes(errs: &[LayoutError]) -> Vec<&'static str> {
        errs.iter().map(LayoutError::code).collect()
    }

    #[test]
    fn fnv1_32_published_values() {
        assert_eq!(fnv1_32(b""), 0x811C_9DC5);
        assert_eq!(fnv1_32(b"a"), 0x050C_5D7E);
        assert_eq!(fnv1_32(b"foobar"), 0x31F0_B262);
    }

    #[test]
    fn digest_of_hashes_the_uids_little_endian() {
        let uids = [0x0A1B_2C3D, 0x0102_0304];
        let le = [0x3D, 0x2C, 0x1B, 0x0A, 0x04, 0x03, 0x02, 0x01];
        assert_eq!(digest_of(&uids), fnv1_32(&le));
        assert_ne!(
            digest_of(&uids),
            fnv1_32(&[0x0A, 0x1B, 0x2C, 0x3D, 1, 2, 3, 4])
        );
        assert_eq!(digest_of(&[]), FNV1_OFFSET);
    }

    #[test]
    fn hand_written_v_5_0() {
        // v = 5.0 is 0x40A00000 at payload offset 25 with flags 0x01; profile 1; the digest LE at p[2..5];
        // kind 4 at p[24]; everything else zero.
        let want = hand(
            1,
            2,
            &[
                (0, &[0x01]),
                (1, &[0x01]),
                (2, &[0x78, 0x56, 0x34, 0x12]),
                (24, &[0x04]),
                (25, &[0x00, 0x00, 0xA0, 0x40]),
            ],
        );
        let mut c = Claim::new(1, 2, 1, D);
        c.v = Some(5.0);
        assert_eq!(encode(&c), Ok(want));
        assert_eq!(
            pack_bits(1, 2, 1, D, [Some(0x40A0_0000), None, None, None], None, 0),
            Ok(want)
        );
        let d = decode(&want, Mode::Request).unwrap();
        assert_eq!(
            (d.flags, d.slot_bits, d.gear, d.digest),
            (F_SPEED, [Some(0x40A0_0000), None, None, None], None, D)
        );
        assert_eq!(d.value(0), Some(5.0));
    }

    #[test]
    fn hand_written_every_field() {
        let want = hand(
            0x0102_0304_0506_0708,
            0x1112_1314_1516_1718,
            &[
                (0, &[0x1F]),
                (1, &[0x03]),
                (2, &[0xEF, 0xBE, 0xAD, 0xDE]),
                (24, &[0x04]),
                (25, &[0x00, 0x00, 0xA0, 0x40]),
                (29, &[0x00, 0x00, 0x40, 0xBF]),
                (33, &[0x00, 0x00, 0x48, 0x41]),
                (37, &[0x00, 0x00, 0xE8, 0xC0]),
                (41, &[0x21, 0x00]),
                (43, &[0xFF]),
            ],
        );
        let c = Claim {
            v: Some(5.0),
            a_x: Some(-0.75),
            delta: Some(12.5),
            psi_dot: Some(-7.25),
            gear: Some(-1),
            age_ms: 33,
            ..Claim::new(0x0102_0304_0506_0708, 0x1112_1314_1516_1718, 3, 0xDEAD_BEEF)
        };
        assert_eq!(encode(&c), Ok(want));
        let d = decode(&want, Mode::Request).unwrap();
        assert_eq!(d.seq, 0x0102_0304_0506_0708);
        assert_eq!(d.tstamp_ns, 0x1112_1314_1516_1718);
        assert_eq!((d.flags, d.profile, d.digest), (0x1F, 3, 0xDEAD_BEEF));
        assert_eq!(
            d.slot_bits,
            [
                Some(0x40A0_0000),
                Some(0xBF40_0000),
                Some(0x4148_0000),
                Some(0xC0E8_0000)
            ]
        );
        assert_eq!(
            (d.gear, d.age_ms, d.verdict, d.reason),
            (Some(-1), 33, 0, 0)
        );
        assert_eq!((d.t_in_ns, d.t_out_ns), (None, None));
        let g = hand(9, 0, &[(0, &[0x10]), (24, &[0x04]), (43, &[0x80])]);
        assert_eq!(decode(&g, Mode::Request).unwrap().gear, Some(-128));
        let mut s = want;
        s[16 + 6] = 1;
        s[16 + 7] = 23;
        s[16 + P_T_IN..16 + P_T_IN + 8].copy_from_slice(&7u64.to_le_bytes());
        s[16 + P_T_OUT..16 + P_T_OUT + 8].copy_from_slice(&9u64.to_le_bytes());
        let d = decode(&s, Mode::Stamp).unwrap();
        assert_eq!(
            (d.verdict, d.reason, d.t_in_ns, d.t_out_ns),
            (1, 23, Some(7), Some(9))
        );
    }

    #[test]
    fn rounding_to_binary32() {
        let p = |x: f64| slot_bits(0, x);
        assert_eq!(p(0.0), Ok(0x0000_0000));
        assert_eq!(p(-0.0), Ok(0x8000_0000));
        assert_eq!(p(2f64.powi(-149)), Ok(0x0000_0001));
        assert_eq!(p(2f64.powi(-150)), Ok(0x0000_0000)); // a tie: 0 is even
        assert_eq!(p(-(2f64.powi(-150))), Ok(0x8000_0000));
        assert_eq!(p(3.0 * 2f64.powi(-150)), Ok(0x0000_0002)); // a tie: 2 is even
        assert_eq!(p(1.0 + 2f64.powi(-24)), Ok(0x3F80_0000)); // a tie, down to even
        assert_eq!(p(1.0 + 3.0 * 2f64.powi(-24)), Ok(0x3F80_0002)); // a tie, up to even
        let flt_max = f64::from(f32::MAX);
        let midpoint = 2f64.powi(128) - 2f64.powi(103);
        assert_eq!(p(flt_max), Ok(0x7F7F_FFFF));
        assert_eq!(p(f64::from_bits(midpoint.to_bits() - 1)), Ok(0x7F7F_FFFF));
        assert_eq!(p(midpoint), Err(EncodeError::Overflow { slot: 0 }));
        assert_eq!(p(-midpoint), Err(EncodeError::Overflow { slot: 0 }));
        assert_eq!(p(1e39), Err(EncodeError::Overflow { slot: 0 }));
        assert_eq!(p(f64::INFINITY), Err(EncodeError::NotFinite { slot: 0 }));
        assert_eq!(
            p(f64::NEG_INFINITY),
            Err(EncodeError::NotFinite { slot: 0 })
        );
        assert_eq!(p(f64::NAN), Err(EncodeError::NotFinite { slot: 0 }));
    }

    #[test]
    fn one_frame_per_refusal_class() {
        let ok = {
            let mut c = Claim::new(5, 0, 1, D);
            c.v = Some(5.0);
            c.a_x = Some(1.0);
            c.delta = Some(2.0);
            c.psi_dot = Some(3.0);
            c.gear = Some(1);
            c.age_ms = 7;
            encode(&c).unwrap()
        };
        let set = |off: usize, v: u8| {
            let mut f = ok;
            f[16 + off] = v;
            f
        };
        let reply = |v: u8, r: u8| {
            let mut f = set(P_VERDICT, v);
            f[16 + P_REASON] = r;
            f
        };
        let mut seq_max = ok;
        seq_max[..8].copy_from_slice(&u64::MAX.to_le_bytes());
        let mut seq_0 = ok;
        seq_0[..8].copy_from_slice(&[0; 8]);
        let clear = |slot: usize| set(P_FLAGS, ok[16] & !slot_flag(slot));
        let mut empty_aged = encode(&Claim::new(5, 0, 1, D)).unwrap();
        empty_aged[16 + P_AGE] = 9;
        let cases: Vec<(&str, Vec<u8>, Mode)> = vec![
            ("length", ok[..63].to_vec(), Mode::Request),
            ("seq-sentinel", seq_max.to_vec(), Mode::Request),
            ("seq-zero", seq_0.to_vec(), Mode::Request),
            ("kind", set(P_KIND, 5).to_vec(), Mode::Request),
            (
                "flags-reserved",
                set(P_FLAGS, ok[16] | 0x80).to_vec(),
                Mode::Request,
            ),
            ("request-verdict", set(P_REASON, 3).to_vec(), Mode::Request),
            ("reply-verdict", reply(2, 0).to_vec(), Mode::Reply),
            ("reply-reason", reply(1, 0).to_vec(), Mode::Reply),
            ("stamp-span", set(23, 1).to_vec(), Mode::Reply),
            (
                "reserved-span",
                set(P_RESERVED + 3, 1).to_vec(),
                Mode::Stamp,
            ),
            ("absent-slot-0", clear(0).to_vec(), Mode::Request),
            ("absent-slot-1", clear(1).to_vec(), Mode::Request),
            ("absent-slot-2", clear(2).to_vec(), Mode::Request),
            ("absent-slot-3", clear(3).to_vec(), Mode::Request),
            ("absent-slot-4", clear(4).to_vec(), Mode::Request),
            ("age-without-value", empty_aged.to_vec(), Mode::Request),
        ];
        for (code, frame, mode) in &cases {
            assert_eq!(codes(&layout_errors(frame, *mode)), [*code], "{code}");
            assert_eq!(
                decode(frame, *mode).map_err(|e| codes(&e)),
                Err(vec![*code])
            );
        }
        // Each mode takes what the others refuse: a reply's verdict, a stamp's t_in and t_out.
        assert!(layout_errors(&reply(1, 23), Mode::Reply).is_empty());
        assert!(layout_errors(&reply(0, 0), Mode::Stamp).is_empty());
        let mut stamped = reply(1, 23);
        stamped[16 + P_T_IN] = 1;
        assert!(layout_errors(&stamped, Mode::Stamp).is_empty());
        assert_eq!(codes(&layout_errors(&stamped, Mode::Reply)), ["stamp-span"]);
        assert_eq!(
            codes(&layout_errors(&reply(0, 4), Mode::Stamp)),
            ["reply-reason"]
        );
        // encode's own refusals, one each.
        let with = |f: &dyn Fn(&mut Claim)| {
            let mut c = Claim::new(5, 0, 1, D);
            c.v = Some(1.0);
            f(&mut c);
            encode(&c).map_err(|e| e.code())
        };
        assert_eq!(with(&|c| c.delta = Some(1e39)), Err("overflow"));
        assert_eq!(with(&|c| c.psi_dot = Some(f64::NAN)), Err("not-finite"));
        assert_eq!(with(&|c| c.seq = 0), Err("seq-zero"));
        assert_eq!(with(&|c| c.seq = u64::MAX), Err("seq-sentinel"));
        assert_eq!(
            with(&|c| {
                c.v = None;
                c.age_ms = 1
            }),
            Err("age-without-value")
        );
        assert!(with(&|c| c.age_ms = 1).is_ok());
    }

    #[test]
    fn encode_refusals_in_python_order() {
        let mut c = Claim::new(5, 0, 1, D);
        c.v = Some(1e39);
        c.psi_dot = Some(f64::INFINITY);
        assert_eq!(encode(&c), Err(EncodeError::Overflow { slot: 0 }));
        c.v = Some(f64::NAN);
        c.psi_dot = Some(1e39);
        assert_eq!(encode(&c), Err(EncodeError::NotFinite { slot: 0 }));
        c.v = Some(1.0);
        assert_eq!(encode(&c), Err(EncodeError::Overflow { slot: 3 }));
        let mut c = Claim::new(0, 0, 1, D);
        c.delta = Some(1e39);
        assert_eq!(encode(&c), Err(EncodeError::Overflow { slot: 2 }));
        let mut c = Claim::new(0, 0, 1, D);
        c.age_ms = 5;
        assert_eq!(encode(&c), Err(EncodeError::SeqZero));
        c.seq = u64::MAX;
        assert_eq!(encode(&c), Err(EncodeError::SeqSentinel));
        assert_eq!(
            pack_bits(0, 0, 1, D, [None; 4], None, 5),
            Err(EncodeError::SeqZero)
        );
        assert_eq!(
            pack_bits(1, 0, 1, D, [None; 4], None, 5),
            Err(EncodeError::AgeWithoutValue { age_ms: 5 })
        );
        // pack_bits takes any bit pattern; encode refuses a non-finite value.
        let f = pack_bits(1, 0, 1, D, [Some(0x7F80_0001), None, None, None], None, 0).unwrap();
        assert_eq!(f[16 + P_V..16 + P_V + 4], [0x01, 0x00, 0x80, 0x7F]);
        let f = pack_bits(1, 0, 1, D, [None, None, Some(0xFFFF_FFFF), None], None, 0).unwrap();
        assert_eq!(f[16 + P_DELTA..16 + P_DELTA + 4], [0xFF; 4]);
        assert_eq!(f[16 + P_PSI_DOT..16 + P_PSI_DOT + 4], [0; 4]);
    }

    #[test]
    fn age_field_cases() {
        let t = 5_000_000_000u64;
        assert_eq!(age_field(t, &[]), (0, false));
        assert_eq!(age_field(t, &[t]), (0, false));
        assert_eq!(age_field(t, &[t - 999_999]), (0, false));
        assert_eq!(age_field(t, &[t - 1_000_000]), (1, false));
        assert_eq!(age_field(t, &[t - 1_999_999]), (1, false));
        assert_eq!(age_field(t, &[t + 1]), (0, true));
        assert_eq!(age_field(t, &[t + 1, t - 3_000_000]), (3, false));
        let sat = 65_535 * 1_000_000u64;
        assert_eq!(age_field(sat, &[1]), (0xFFFE, false));
        assert_eq!(age_field(sat, &[0]), (0xFFFF, false));
        assert_eq!(age_field(sat + 999_999, &[0]), (0xFFFF, false));
        assert_eq!(age_field(sat + 1_000_000, &[0]), (0xFFFF, false));
        assert_eq!(age_field(u64::MAX, &[0]), (0xFFFF, false));
        assert_eq!(age_field(0, &[u64::MAX]), (0, true));
    }
}
