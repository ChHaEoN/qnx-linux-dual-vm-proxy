//! The 64-byte frame (`ipc-test/common/frame.h`) and the kind 4 payload layout (`vssframe.py`'s `P_*`).
//!
//! A 16-byte header of seq and tstamp, u64 little-endian, then a 48-byte payload. Offsets below are
//! into the payload. Every multi-byte field is little-endian.

/// The header: seq (u64 LE) and tstamp (u64 LE).
pub const FRAME_HEADER_BYTES: usize = 16;
/// The payload after the header.
pub const FRAME_PAYLOAD_BYTES: usize = 48;
/// The whole frame.
pub const FRAME_TOTAL_BYTES: usize = FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES;
/// `FRAME_SENTINEL_SEQ`: a keepalive, echoed untouched, never judged and never a claim.
pub const SENTINEL_SEQ: u64 = u64::MAX;

/// One frame on the wire.
pub type Frame = [u8; FRAME_TOTAL_BYTES];

/// The payload's kind byte for a kind 4 (`vss`) claim.
pub const KIND_VSS: u8 = 4;

pub const P_FLAGS: usize = 0;
pub const P_PROFILE: usize = 1;
pub const P_DIGEST: usize = 2;
pub const P_VERDICT: usize = 6;
pub const P_REASON: usize = 7;
pub const P_T_IN: usize = 8;
pub const P_T_OUT: usize = 16;
pub const P_KIND: usize = 24;
pub const P_V: usize = 25;
pub const P_AX: usize = 29;
pub const P_DELTA: usize = 33;
pub const P_PSI_DOT: usize = 37;
pub const P_AGE: usize = 41;
pub const P_GEAR: usize = 43;
pub const P_RESERVED: usize = 44;
/// p[8..23]: zero in a request, t_in and t_out in a stamp reply.
pub const STAMP_SPAN: (usize, usize) = (8, 24);
/// p[44..47]: reserved, zero.
pub const RESERVED_SPAN: (usize, usize) = (44, 48);

/// Slots 0..3 are f32 (v, a_x, delta, psi_dot); slot 4 is the i8 gear.
pub const N_SLOTS: usize = 5;
pub const F32_SLOT_OFFSETS: [usize; 4] = [P_V, P_AX, P_DELTA, P_PSI_DOT];
pub const SLOT_SPANS: [(usize, usize); N_SLOTS] = [
    (P_V, P_V + 4),
    (P_AX, P_AX + 4),
    (P_DELTA, P_DELTA + 4),
    (P_PSI_DOT, P_PSI_DOT + 4),
    (P_GEAR, P_GEAR + 1),
];

pub const F_SPEED: u8 = 0x01;
pub const F_ACCEL: u8 = 0x02;
pub const F_STEER: u8 = 0x04;
pub const F_YAW: u8 = 0x08;
pub const F_GEAR: u8 = 0x10;
pub const F_SLOTS: u8 = 0x1F;
pub const F_RESERVED: u8 = 0xE0;

/// The age field saturates here.
pub const AGE_SATURATED: u16 = 0xFFFF;

/// The flag bit that says slot `slot` holds a value (slot 4 is gear's, `F_GEAR`).
pub const fn slot_flag(slot: usize) -> u8 {
    1 << slot
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sizes_offsets_and_flags() {
        assert_eq!(
            (FRAME_HEADER_BYTES, FRAME_PAYLOAD_BYTES, FRAME_TOTAL_BYTES),
            (16, 48, 64)
        );
        assert_eq!(SENTINEL_SEQ, 0xFFFF_FFFF_FFFF_FFFF);
        // The layout table: p[24] kind, four f32 from p[25], the u16 age at p[41], the i8 gear at p[43],
        // p[44..47] reserved, the payload ending at 48.
        assert_eq!(
            [P_KIND, P_V, P_AX, P_DELTA, P_PSI_DOT, P_AGE, P_GEAR],
            [24, 25, 29, 33, 37, 41, 43]
        );
        assert_eq!(RESERVED_SPAN.1, FRAME_PAYLOAD_BYTES);
        let flags: Vec<u8> = (0..N_SLOTS).map(slot_flag).collect();
        assert_eq!(flags, [F_SPEED, F_ACCEL, F_STEER, F_YAW, F_GEAR]);
        assert_eq!(flags, [0x01, 0x02, 0x04, 0x08, 0x10]);
        assert_eq!(F_SLOTS | F_RESERVED, 0xFF);
        assert_eq!(F_SLOTS & F_RESERVED, 0);
    }
}
