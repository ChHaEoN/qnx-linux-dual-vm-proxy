//! claimrs: the kind 4 `vss` claim codec and a blocking svc client, in Rust with std only.
//!
//! A port of `sdv/frame/vssframe.py` for the L4T side, where every claim starts: [`frame`] holds the
//! 64-byte frame's constants, [`kind4`] the codec (encode, pack, decode, the layout refusals, the age
//! field, FNV-1 and the catalogue digest), and [`link`] the svc client that sends one frame and reads one
//! reply at a time. The crate reads no generated contract: the digest comes in as a value. The judgement
//! stays the guest monitor's (`monitor.c`); nothing here judges a claim.

#![forbid(unsafe_code)]

pub mod frame;
pub mod kind4;
pub mod link;
