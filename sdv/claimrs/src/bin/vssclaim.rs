//! vssclaim: the claimrs command line.
//!
//! - `vssclaim consts` prints the frame constants, one `NAME VALUE` line each (frame.h's names).
//! - `vssclaim vectors FILE` checks the codec against a vector file (`sdv/claimrs/vectors.py` writes
//!   them): `ok NAME` or `diff NAME ...` for each record, then `vectors done: total=N matched=M`.
//! - `vssclaim probe --host H --port P --vectors FILE [--reply-timeout-ms MS]` encodes each `rt`
//!   record's base with this crate's encoder (`encode`, or `pack_bits` for a raw-bits base) and holds it
//!   to the record's request, all before connecting; then, on one connection, applies each record's
//!   patch, sends the frame and compares the whole reply with the record's. After the last record it
//!   ends the session and prints `probe done: sent=N matched=M`. It prints no time and has no stamp mode.
//!
//! Exit codes: 0 when everything matched (and, for the probe, the session ended clean); 1 for a mismatch
//! or a link error; 2 for a usage error or a vector file it refuses, always before any connect. A file is
//! refused, among other things, when an `rt` record's patch touches a byte the rt rule does not let it.

use std::fmt::{self, Write as _};
use std::fs;
use std::io::{self, Write};
use std::process::ExitCode;
use std::time::Duration;

use claimrs::frame::{
    F_RESERVED, F_SLOTS, FRAME_HEADER_BYTES, FRAME_PAYLOAD_BYTES, FRAME_TOTAL_BYTES, Frame, P_AGE,
    P_FLAGS, P_VERDICT, RESERVED_SPAN, SENTINEL_SEQ, SLOT_SPANS, STAMP_SPAN, slot_flag,
};
use claimrs::kind4::{self, Claim, Decoded, EncodeError, Mode};
use claimrs::link::{DEFAULT_REPLY_TIMEOUT_MS, Link};

const EXIT_OK: u8 = 0;
const EXIT_MISMATCH: u8 = 1;
const EXIT_REFUSED: u8 = 2;

const USAGE: &str = "usage: vssclaim consts\n       vssclaim vectors FILE\n       \
                     vssclaim probe --host H --port P --vectors FILE [--reply-timeout-ms MS]";

/// The vector file's first line: the format and its version.
const FORMAT: &str = "claimrs-vectors\t1";
const HEADER_KEYS: [&str; 8] = [
    "contract_sha256",
    "catalog_digest",
    "slot_uids",
    "seed",
    "records",
    "rt_records",
    "rt_encode_bases",
    "rt_patched",
];
const ENCODE_CODES: [&str; 5] = [
    "overflow",
    "not-finite",
    "seq-zero",
    "seq-sentinel",
    "age-without-value",
];
const LAYOUT_CODES: [&str; 16] = [
    "length",
    "seq-sentinel",
    "seq-zero",
    "kind",
    "flags-reserved",
    "request-verdict",
    "reply-verdict",
    "reply-reason",
    "stamp-span",
    "reserved-span",
    "absent-slot-0",
    "absent-slot-1",
    "absent-slot-2",
    "absent-slot-3",
    "absent-slot-4",
    "age-without-value",
];

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    ExitCode::from(run(&args))
}

/// Standard output, line by line; a failed write makes a clean exit 1.
struct Out {
    w: io::StdoutLock<'static>,
    failed: bool,
}

impl Out {
    fn line(&mut self, args: fmt::Arguments<'_>) {
        if !self.failed && writeln!(self.w, "{args}").is_err() {
            self.failed = true;
        }
    }

    fn finish(mut self, code: u8) -> u8 {
        if self.w.flush().is_err() {
            self.failed = true;
        }
        if self.failed && code == EXIT_OK {
            EXIT_MISMATCH
        } else {
            code
        }
    }
}

macro_rules! say {
    ($out:expr, $($t:tt)*) => {
        $out.line(format_args!($($t)*))
    };
}

fn run(args: &[String]) -> u8 {
    let mut out = Out {
        w: io::stdout().lock(),
        failed: false,
    };
    let code = match args.first().map(String::as_str) {
        Some("consts") if args.len() == 1 => consts(&mut out),
        Some("vectors") if args.len() == 2 => vectors(&args[1], &mut out),
        Some("probe") => probe(&args[1..], &mut out),
        _ => usage("a command and its arguments, as below"),
    };
    out.finish(code)
}

fn usage(why: &str) -> u8 {
    let _ = writeln!(io::stderr(), "vssclaim: {why}\n{USAGE}");
    EXIT_REFUSED
}

fn refuse(why: &str) -> u8 {
    let _ = writeln!(io::stderr(), "vssclaim: refused: {why}");
    EXIT_REFUSED
}

fn consts(out: &mut Out) -> u8 {
    say!(out, "FRAME_HEADER_BYTES {FRAME_HEADER_BYTES}");
    say!(out, "FRAME_PAYLOAD_BYTES {FRAME_PAYLOAD_BYTES}");
    say!(out, "FRAME_TOTAL_BYTES {FRAME_TOTAL_BYTES}");
    say!(out, "FRAME_SENTINEL_SEQ {SENTINEL_SEQ}");
    EXIT_OK
}

// ============================================================ the vector file

struct PackArgs {
    seq: u64,
    tstamp_ns: u64,
    profile: u8,
    digest: u32,
    slot_bits: [Option<u32>; 4],
    gear: Option<i8>,
    age_ms: u16,
}

impl PackArgs {
    fn pack(&self) -> Result<Frame, EncodeError> {
        kind4::pack_bits(
            self.seq,
            self.tstamp_ns,
            self.profile,
            self.digest,
            self.slot_bits,
            self.gear,
            self.age_ms,
        )
    }
}

enum Want {
    Frame(Frame),
    Error(&'static str),
}

enum Base {
    Enc(Claim),
    Pack(PackArgs),
}

struct Rt {
    base: Base,
    request: Frame,
    patch: Vec<(usize, u8)>,
    reply: Frame,
}

enum Body {
    Enc(Claim, Want),
    Pack(PackArgs, Want),
    Dec(Mode, Vec<u8>, Result<Decoded, Vec<&'static str>>),
    Age(u64, Vec<u64>, (u16, bool)),
    Rt(Rt),
}

struct Record {
    name: String,
    body: Body,
}

fn is_decimal(s: &str) -> bool {
    !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()) && (s == "0" || !s.starts_with('0'))
}

fn dec_u64(s: &str, what: &str) -> Result<u64, String> {
    if !is_decimal(s) {
        return Err(format!("{what}: {s:?} is not a decimal integer"));
    }
    s.parse::<u64>()
        .map_err(|_| format!("{what}: {s} does not fit a u64"))
}

fn dec_as<T: TryFrom<u64>>(s: &str, what: &str) -> Result<T, String> {
    T::try_from(dec_u64(s, what)?).map_err(|_| format!("{what}: {s} is out of range"))
}

fn dec_i8(s: &str, what: &str) -> Result<i8, String> {
    let (neg, digits) = match s.strip_prefix('-') {
        Some(d) => (true, d),
        None => (false, s),
    };
    if !is_decimal(digits) || (neg && digits == "0") {
        return Err(format!("{what}: {s:?} is not a decimal integer"));
    }
    let v = i64::try_from(dec_u64(digits, what)?)
        .map_err(|_| format!("{what}: {s} is out of range"))?;
    i8::try_from(if neg { -v } else { v }).map_err(|_| format!("{what}: {s} is not an i8"))
}

/// Lowercase hex, two digits a byte; anything else is refused.
fn hex(s: &str, what: &str) -> Result<Vec<u8>, String> {
    let ok = s.len().is_multiple_of(2) && s.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
    if !ok {
        return Err(format!("{what}: {s:?} is not lowercase hex"));
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| format!("{what}: {e}")))
        .collect()
}

fn hex_n(s: &str, digits: usize, what: &str) -> Result<u64, String> {
    if s.len() != digits {
        return Err(format!("{what}: {s:?} is not {digits} hex digits"));
    }
    Ok(hex(s, what)?
        .iter()
        .fold(0u64, |acc, &b| (acc << 8) | u64::from(b)))
}

fn hex_u32(s: &str, what: &str) -> Result<u32, String> {
    u32::try_from(hex_n(s, 8, what)?).map_err(|_| format!("{what}: out of range"))
}

fn hex_u8(s: &str, what: &str) -> Result<u8, String> {
    u8::try_from(hex_n(s, 2, what)?).map_err(|_| format!("{what}: out of range"))
}

fn hex_frame(s: &str, what: &str) -> Result<Frame, String> {
    let b = hex(s, what)?;
    Frame::try_from(b.as_slice())
        .map_err(|_| format!("{what}: {} bytes, not {FRAME_TOTAL_BYTES}", b.len()))
}

fn opt<T>(s: &str, f: impl Fn(&str) -> Result<T, String>) -> Result<Option<T>, String> {
    if s == "-" { Ok(None) } else { f(s).map(Some) }
}

fn opt_f64(s: &str, what: &str) -> Result<Option<f64>, String> {
    opt(s, |x| Ok(f64::from_bits(hex_n(x, 16, what)?)))
}

fn code_in(s: &str, codes: &[&'static str], what: &str) -> Result<&'static str, String> {
    codes
        .iter()
        .copied()
        .find(|c| *c == s)
        .ok_or_else(|| format!("{what}: {s:?} is not a code this reader knows"))
}

fn mode(s: &str) -> Result<Mode, String> {
    match s {
        "request" => Ok(Mode::Request),
        "reply" => Ok(Mode::Reply),
        "stamp" => Ok(Mode::Stamp),
        _ => Err(format!("mode {s:?} is not request, reply or stamp")),
    }
}

fn want(outcome: &str, value: &str) -> Result<Want, String> {
    match outcome {
        "frame" => Ok(Want::Frame(hex_frame(value, "the expected frame")?)),
        "error" => Ok(Want::Error(code_in(
            value,
            &ENCODE_CODES,
            "the expected refusal",
        )?)),
        _ => Err(format!("outcome {outcome:?} is not frame or error")),
    }
}

/// SEQ TSTAMP PROFILE DIGEST: the four fields every claim starts with.
fn head(f: &[&str]) -> Result<(u64, u64, u8, u32), String> {
    Ok((
        dec_u64(f[0], "seq")?,
        dec_u64(f[1], "tstamp")?,
        dec_as(f[2], "profile")?,
        hex_u32(f[3], "digest")?,
    ))
}

/// The ten fields of an encode claim: SEQ TSTAMP PROFILE DIGEST V A_X DELTA PSI_DOT GEAR AGE.
fn claim(f: &[&str]) -> Result<Claim, String> {
    let (seq, tstamp_ns, profile, digest) = head(f)?;
    Ok(Claim {
        v: opt_f64(f[4], "v")?,
        a_x: opt_f64(f[5], "a_x")?,
        delta: opt_f64(f[6], "delta")?,
        psi_dot: opt_f64(f[7], "psi_dot")?,
        gear: opt(f[8], |x| dec_i8(x, "gear"))?,
        age_ms: dec_as(f[9], "age")?,
        ..Claim::new(seq, tstamp_ns, profile, digest)
    })
}

/// The ten fields of a pack_bits call: SEQ TSTAMP PROFILE DIGEST B0 B1 B2 B3 GEAR AGE.
fn pack_args(f: &[&str]) -> Result<PackArgs, String> {
    let (seq, tstamp_ns, profile, digest) = head(f)?;
    let mut slot_bits = [None; 4];
    for (i, b) in slot_bits.iter_mut().enumerate() {
        *b = opt(f[4 + i], |x| hex_u32(x, "slot bits"))?;
    }
    Ok(PackArgs {
        seq,
        tstamp_ns,
        profile,
        digest,
        slot_bits,
        gear: opt(f[8], |x| dec_i8(x, "gear"))?,
        age_ms: dec_as(f[9], "age")?,
    })
}

fn decoded(f: &[&str]) -> Result<Decoded, String> {
    let mut slot_bits = [None; 4];
    for (i, b) in slot_bits.iter_mut().enumerate() {
        *b = opt(f[5 + i], |x| hex_u32(x, "slot bits"))?;
    }
    Ok(Decoded {
        seq: dec_u64(f[0], "seq")?,
        tstamp_ns: dec_u64(f[1], "tstamp")?,
        flags: hex_u8(f[2], "flags")?,
        profile: dec_as(f[3], "profile")?,
        digest: hex_u32(f[4], "digest")?,
        slot_bits,
        gear: opt(f[9], |x| dec_i8(x, "gear"))?,
        age_ms: dec_as(f[10], "age")?,
        verdict: dec_as(f[11], "verdict")?,
        reason: dec_as(f[12], "reason")?,
        t_in_ns: opt(f[13], |x| dec_u64(x, "t_in"))?,
        t_out_ns: opt(f[14], |x| dec_u64(x, "t_out"))?,
    })
}

fn patch(s: &str) -> Result<Vec<(usize, u8)>, String> {
    if s == "-" {
        return Ok(Vec::new());
    }
    let mut out: Vec<(usize, u8)> = Vec::new();
    for item in s.split(',') {
        let (off, val) = item
            .split_once('=')
            .ok_or_else(|| format!("patch item {item:?} is not OFF=VV"))?;
        let off: usize = dec_as(off, "patch offset")?;
        if off >= FRAME_TOTAL_BYTES || out.last().is_some_and(|&(prev, _)| off <= prev) {
            return Err(format!(
                "patch offset {off} is outside the frame or not ascending"
            ));
        }
        out.push((off, hex_u8(val, "patch byte")?));
    }
    Ok(out)
}

/// May an rt patch change payload byte `p` by the bits `diff` in a request with these flags? The rt rule
/// (vectors.py's `_patchable`): only the flags byte's reserved bits, p[6..23], the bytes of a slot the
/// request leaves absent (gear's included), the age when the request holds no value, and p[44..47].
fn patchable(p: usize, flags: u8, diff: u8) -> bool {
    if p == P_FLAGS {
        return (diff & !F_RESERVED) == 0;
    }
    if (P_VERDICT..STAMP_SPAN.1).contains(&p) || (RESERVED_SPAN.0..RESERVED_SPAN.1).contains(&p) {
        return true;
    }
    if p == P_AGE || p == P_AGE + 1 {
        return (flags & F_SLOTS) == 0;
    }
    SLOT_SPANS
        .iter()
        .position(|&(lo, hi)| (lo..hi).contains(&p))
        .is_some_and(|slot| (flags & slot_flag(slot)) == 0)
}

/// Refuse a patch that breaks the rt rule, judged from the record's own request, so a vector file the
/// writer did not write cannot make the probe send what the request check did not hold.
fn patch_in_rule(request: &Frame, patch: &[(usize, u8)]) -> Result<(), String> {
    let flags = request[FRAME_HEADER_BYTES + P_FLAGS];
    for &(off, v) in patch {
        let ok = off
            .checked_sub(FRAME_HEADER_BYTES)
            .is_some_and(|p| patchable(p, flags, v ^ request[off]));
        if !ok {
            return Err(format!(
                "the patch sets frame byte {off}, which the rt rule does not let a patch change"
            ));
        }
    }
    Ok(())
}

fn fields_n<'a>(f: &'a [&'a str], n: usize) -> Result<&'a [&'a str], String> {
    if f.len() == n {
        Ok(f)
    } else {
        Err(format!("a {} record has {n} fields, not {}", f[0], f.len()))
    }
}

fn record(line: &str) -> Result<Record, String> {
    let f: Vec<&str> = line.split('\t').collect();
    let name = f.get(1).copied().unwrap_or("");
    if name.is_empty() || !name.bytes().all(|b| b.is_ascii_graphic()) {
        return Err(format!(
            "the record name {name:?} is empty or not printable without spaces"
        ));
    }
    let body = match f[0] {
        "enc" => {
            let f = fields_n(&f, 14)?;
            Body::Enc(claim(&f[2..12])?, want(f[12], f[13])?)
        }
        "pack" => {
            let f = fields_n(&f, 14)?;
            Body::Pack(pack_args(&f[2..12])?, want(f[12], f[13])?)
        }
        "dec" => {
            let m = mode(f.get(2).copied().unwrap_or(""))?;
            let frame = hex(f.get(3).copied().unwrap_or("-"), "the frame")?;
            let expect = match f.get(4).copied() {
                Some("error") => {
                    let f = fields_n(&f, 6)?;
                    let mut codes = Vec::new();
                    for c in f[5].split(',') {
                        let c = code_in(c, &LAYOUT_CODES, "a refusal")?;
                        if codes.contains(&c) {
                            return Err(format!("the refusal {c} twice"));
                        }
                        codes.push(c);
                    }
                    Err(codes)
                }
                Some("decoded") => Ok(decoded(&fields_n(&f, 20)?[5..])?),
                _ => return Err("a dec record's outcome is error or decoded".to_string()),
            };
            Body::Dec(m, frame, expect)
        }
        "age" => {
            let f = fields_n(&f, 6)?;
            let samples = if f[3] == "-" {
                Vec::new()
            } else {
                f[3].split(',')
                    .map(|s| dec_u64(s, "sample"))
                    .collect::<Result<_, _>>()?
            };
            let neg = match f[5] {
                "0" => false,
                "1" => true,
                x => return Err(format!("negative {x:?} is not 0 or 1")),
            };
            Body::Age(dec_u64(f[2], "now")?, samples, (dec_as(f[4], "age")?, neg))
        }
        "rt" => {
            let f = fields_n(&f, 16)?;
            let base = match f[2] {
                "enc" => Base::Enc(claim(&f[3..13])?),
                "pack" => Base::Pack(pack_args(&f[3..13])?),
                x => return Err(format!("an rt base is enc or pack, not {x:?}")),
            };
            let request = hex_frame(f[13], "the request")?;
            let patch = patch(f[14])?;
            patch_in_rule(&request, &patch)?;
            Body::Rt(Rt {
                base,
                request,
                patch,
                reply: hex_frame(f[15], "the reply")?,
            })
        }
        x => return Err(format!("no record type {x:?}")),
    };
    Ok(Record {
        name: name.to_string(),
        body,
    })
}

/// Read and check a whole vector file; any refusal names its line.
fn load(path: &str) -> Result<Vec<Record>, String> {
    let bytes = fs::read(path).map_err(|e| format!("{path}: {e}"))?;
    if !bytes.is_ascii() {
        return Err(format!("{path}: not ASCII"));
    }
    let text = String::from_utf8(bytes).map_err(|_| format!("{path}: not ASCII"))?;
    let body = text
        .strip_suffix('\n')
        .ok_or_else(|| format!("{path}: does not end with a newline"))?;
    let lines: Vec<&str> = body.split('\n').collect();
    if lines[0] != FORMAT {
        return Err(format!(
            "line 1: {:?} is not {FORMAT:?} (a format or version this reader does not take)",
            lines[0]
        ));
    }
    let mut header = Vec::new();
    for (i, key) in HEADER_KEYS.iter().enumerate() {
        let line = lines.get(i + 1).copied().unwrap_or("");
        match line.split_once('\t') {
            Some((k, v)) if k == *key && !v.contains('\t') => header.push(v),
            _ => return Err(format!("line {}: not the header line {key}", i + 2)),
        }
    }
    hex(header[0], "contract_sha256").and_then(|b| {
        if b.len() == 32 {
            Ok(())
        } else {
            Err("contract_sha256: not 32 bytes".into())
        }
    })?;
    let digest = hex_u32(header[1], "catalog_digest")?;
    let uids: Vec<u32> = header[2]
        .split(',')
        .map(|u| hex_u32(u, "slot_uids"))
        .collect::<Result<_, _>>()?;
    if uids.len() != 5 {
        return Err(format!("slot_uids: {} UIDs, not 5", uids.len()));
    }
    let computed = kind4::digest_of(&uids);
    if computed != digest {
        return Err(format!(
            "catalog_digest {digest:08x} is not digest_of(slot_uids) {computed:08x}"
        ));
    }
    dec_u64(header[3], "seed")?;
    let counts: Vec<usize> = header[4..]
        .iter()
        .map(|v| dec_as(v, "a count"))
        .collect::<Result<_, _>>()?;
    let first = 1 + HEADER_KEYS.len();
    let records = lines[first.min(lines.len())..]
        .iter()
        .enumerate()
        .map(|(i, ln)| record(ln).map_err(|e| format!("line {}: {e}", first + i + 1)))
        .collect::<Result<Vec<_>, _>>()?;
    let rts: Vec<&Rt> = records
        .iter()
        .filter_map(|r| match &r.body {
            Body::Rt(rt) => Some(rt),
            _ => None,
        })
        .collect();
    let have = [
        records.len(),
        rts.len(),
        rts.iter()
            .filter(|rt| matches!(rt.base, Base::Enc(_)))
            .count(),
        rts.iter().filter(|rt| !rt.patch.is_empty()).count(),
    ];
    if have.as_slice() != counts.as_slice() {
        return Err(format!(
            "the header counts records, rt_records, rt_encode_bases, rt_patched as {counts:?}, the file holds {have:?}"
        ));
    }
    Ok(records)
}

// ============================================================ checks

fn hexs(b: &[u8]) -> String {
    let mut s = String::with_capacity(2 * b.len());
    for x in b {
        let _ = write!(s, "{x:02x}");
    }
    s
}

fn shown(r: &Result<Frame, EncodeError>) -> String {
    match r {
        Ok(f) => hexs(f),
        Err(e) => format!("error:{}", e.code()),
    }
}

fn check_want(got: Result<Frame, EncodeError>, want: &Want) -> Result<(), String> {
    match (&got, want) {
        (Ok(f), Want::Frame(w)) if f == w => Ok(()),
        (Err(e), Want::Error(c)) if e.code() == *c => Ok(()),
        (_, Want::Frame(w)) => Err(format!("want={} got={}", hexs(w), shown(&got))),
        (_, Want::Error(c)) => Err(format!("want=error:{c} got={}", shown(&got))),
    }
}

/// An rt record's frame to send: the base encoded here, held to the record's request, then patched.
fn rt_frame(rt: &Rt) -> Result<Frame, String> {
    let got = match &rt.base {
        Base::Enc(c) => kind4::encode(c),
        Base::Pack(a) => a.pack(),
    }
    .map_err(|e| format!("want={} got=error:{}", hexs(&rt.request), e.code()))?;
    if got != rt.request {
        return Err(format!("want={} got={}", hexs(&rt.request), hexs(&got)));
    }
    let mut sent = got;
    for &(off, v) in &rt.patch {
        sent[off] = v;
    }
    Ok(sent)
}

fn check(body: &Body) -> Result<(), String> {
    match body {
        Body::Enc(c, w) => check_want(kind4::encode(c), w),
        Body::Pack(a, w) => check_want(a.pack(), w),
        Body::Dec(m, frame, w) => {
            let got = kind4::decode(frame, *m).map_err(|e| {
                let mut c: Vec<&str> = e.iter().map(|x| x.code()).collect();
                c.sort_unstable();
                c
            });
            let w = w.as_ref().map_err(|c| {
                let mut c = c.clone();
                c.sort_unstable();
                c
            });
            match (&got, &w) {
                (Ok(g), Ok(w)) if g == *w => Ok(()),
                (Err(g), Err(w)) if g == w => Ok(()),
                _ => Err(format!("want={w:?} got={got:?}")),
            }
        }
        Body::Age(now, samples, w) => {
            let got = kind4::age_field(*now, samples);
            if got == *w {
                Ok(())
            } else {
                Err(format!("want={w:?} got={got:?}"))
            }
        }
        Body::Rt(rt) => rt_frame(rt).map(|_| ()).map_err(|d| format!("request {d}")),
    }
}

fn vectors(path: &str, out: &mut Out) -> u8 {
    let records = match load(path) {
        Ok(r) => r,
        Err(e) => return refuse(&e),
    };
    let mut matched = 0;
    for r in &records {
        match check(&r.body) {
            Ok(()) => {
                matched += 1;
                say!(out, "ok {}", r.name);
            }
            Err(d) => say!(out, "diff {} {d}", r.name),
        }
    }
    say!(
        out,
        "vectors done: total={} matched={matched}",
        records.len()
    );
    if matched == records.len() {
        EXIT_OK
    } else {
        EXIT_MISMATCH
    }
}

// ============================================================ the probe

struct ProbeArgs {
    host: String,
    port: u16,
    vectors: String,
    reply_timeout_ms: u64,
}

fn probe_args(args: &[String]) -> Result<ProbeArgs, String> {
    let (mut host, mut port, mut vectors, mut timeout) = (None, None, None, None);
    let mut it = args.iter();
    while let Some(opt) = it.next() {
        let v = it
            .next()
            .ok_or_else(|| format!("{opt} needs a value"))?
            .as_str();
        let slot_taken = match opt.as_str() {
            "--host" => host.replace(v.to_string()).is_some(),
            "--port" => port.replace(v).is_some(),
            "--vectors" => vectors.replace(v.to_string()).is_some(),
            "--reply-timeout-ms" => timeout.replace(v).is_some(),
            _ => return Err(format!("no option {opt}")),
        };
        if slot_taken {
            return Err(format!("{opt} given twice"));
        }
    }
    let port: u16 = dec_as(port.ok_or("--port is required")?, "--port")?;
    let reply_timeout_ms = match timeout {
        Some(t) => dec_u64(t, "--reply-timeout-ms")?,
        None => DEFAULT_REPLY_TIMEOUT_MS,
    };
    if port == 0 || reply_timeout_ms == 0 {
        return Err("--port and --reply-timeout-ms must be above 0".to_string());
    }
    let host = host.ok_or("--host is required")?;
    if host.is_empty() {
        return Err("--host is empty".to_string());
    }
    Ok(ProbeArgs {
        host,
        port,
        vectors: vectors.ok_or("--vectors is required")?,
        reply_timeout_ms,
    })
}

fn probe(args: &[String], out: &mut Out) -> u8 {
    let a = match probe_args(args) {
        Ok(a) => a,
        Err(e) => return usage(&e),
    };
    let records = match load(&a.vectors) {
        Ok(r) => r,
        Err(e) => return refuse(&e),
    };
    let rts: Vec<(&str, &Rt)> = records
        .iter()
        .filter_map(|r| match &r.body {
            Body::Rt(rt) => Some((r.name.as_str(), rt)),
            _ => None,
        })
        .collect();
    if rts.is_empty() {
        return refuse("the vector file has no rt record");
    }
    // This crate's encoder against Python's packing, for every record, before any connect.
    let mut frames = Vec::with_capacity(rts.len());
    for (name, rt) in &rts {
        match rt_frame(rt) {
            Ok(f) => frames.push(f),
            Err(d) => say!(out, "diff {name} request {d}"),
        }
    }
    if frames.len() != rts.len() {
        say!(out, "probe done: sent=0 matched=0");
        return EXIT_MISMATCH;
    }
    let timeout = Duration::from_millis(a.reply_timeout_ms);
    let mut link = match Link::connect(&a.host, a.port, timeout) {
        Ok(l) => l,
        Err(e) => {
            say!(out, "error connect: {e}");
            say!(out, "probe done: sent=0 matched=0");
            return EXIT_MISMATCH;
        }
    };
    let (mut sent, mut matched) = (0usize, 0usize);
    for ((name, rt), frame) in rts.iter().zip(&frames) {
        sent += 1;
        match link.roundtrip(frame) {
            Ok(reply) if reply == rt.reply => {
                matched += 1;
                say!(out, "ok {name}");
            }
            Ok(reply) => say!(
                out,
                "diff {name} reply want={} got={}",
                hexs(&rt.reply),
                hexs(&reply)
            ),
            Err(e) => {
                say!(out, "error {name}: {e}");
                say!(out, "probe done: sent={sent} matched={matched}");
                return EXIT_MISMATCH;
            }
        }
    }
    let ended = link.end_session();
    if let Err(e) = &ended {
        say!(out, "error end of session: {e}");
    }
    say!(out, "probe done: sent={sent} matched={matched}");
    if ended.is_ok() && matched == rts.len() {
        EXIT_OK
    } else {
        EXIT_MISMATCH
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn numbers_are_strict() {
        assert_eq!(dec_u64("0", "x"), Ok(0));
        assert_eq!(dec_u64("18446744073709551615", "x"), Ok(u64::MAX));
        for bad in ["", "01", "+1", "-1", "1 ", "18446744073709551616", "0x10"] {
            assert!(dec_u64(bad, "x").is_err(), "{bad:?}");
        }
        assert_eq!(dec_i8("-128", "g"), Ok(-128));
        assert_eq!(dec_i8("127", "g"), Ok(127));
        for bad in ["128", "-129", "-0", "--1", "-"] {
            assert!(dec_i8(bad, "g").is_err(), "{bad:?}");
        }
        assert_eq!(hex("00ff7a", "h"), Ok(vec![0, 255, 0x7a]));
        for bad in ["0", "FF", "0g", " 0"] {
            assert!(hex(bad, "h").is_err(), "{bad:?}");
        }
        assert_eq!(hex_u32("deadbeef", "d"), Ok(0xDEAD_BEEF));
        assert!(hex_u32("deadbee", "d").is_err());
        assert!(hex_frame(&"00".repeat(63), "f").is_err());
    }

    #[test]
    fn a_patch_is_ascending_inside_the_frame() {
        assert_eq!(patch("-"), Ok(vec![]));
        assert_eq!(patch("16=20,60=01"), Ok(vec![(16, 0x20), (60, 0x01)]));
        for bad in ["", "64=00", "17=00,16=00", "16=00,16=01", "16:00", "16=0"] {
            assert!(patch(bad).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn a_patch_keeps_to_the_rt_rule() {
        let h = FRAME_HEADER_BYTES;
        // v and gear present (flags 0x11), a_x, delta and psi_dot absent, an age with a value present.
        let mut c = Claim::new(5, 9, 1, 0xDEAD_BEEF);
        c.v = Some(5.0);
        c.gear = Some(1);
        c.age_ms = 7;
        let req = kind4::encode(&c).unwrap();
        assert_eq!(req[h], 0x11);
        let ok = |items: &[(usize, u8)]| patch_in_rule(&req, items).is_ok();
        assert!(ok(&[]));
        assert!(ok(&[(h, 0x11 | 0xE0)]), "the flags byte's reserved bits");
        for p in [6, 7, 8, 23, 29, 32, 33, 36, 37, 40, 44, 47] {
            assert!(ok(&[(h + p, 0xA5)]), "p[{p}]");
        }
        for off in [0, 7, 8, 15] {
            assert!(!ok(&[(off, req[off] ^ 1)]), "header byte {off}");
        }
        for flags in [0x10, 0x13, 0x90] {
            assert!(!ok(&[(h, flags)]), "a slot bit changed: flags {flags:#04x}");
        }
        for p in [1, 2, 5, 24, 25, 28, 41, 42, 43] {
            assert!(!ok(&[(h + p, req[h + p] ^ 1)]), "p[{p}]");
        }
        // A byte the rule forbids is refused even when the patch leaves it as it was, and one bad item
        // among good ones is refused.
        assert!(!ok(&[(h + 24, req[h + 24])]));
        assert!(!ok(&[(h + 6, 1), (h + 24, 5)]));
        // No value present: the age is patchable, and so is every slot's bytes, gear's included.
        let empty = kind4::encode(&Claim::new(5, 9, 1, 0xDEAD_BEEF)).unwrap();
        for p in [25, 28, 37, 40, 41, 42, 43] {
            assert!(patch_in_rule(&empty, &[(h + p, 1)]).is_ok(), "p[{p}]");
        }
        assert!(patch_in_rule(&empty, &[(h + 24, 5)]).is_err());
    }
}
