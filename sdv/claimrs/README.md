# sdv/claimrs: the kind 4 claim codec and svc probe in Rust

A std-only Rust crate on the L4T side, the untrusted Compute partition, where every claim starts. It ports
the kind 4 claim codec of [vssframe.py](../frame/vssframe.py) and adds a blocking svc client that sends kind
4 claims to a monitor's service port and checks each reply byte for byte. It has no dependencies of any
kind, and `unsafe` is forbidden in it. It replaces nothing: the bridge, the Python codec, the reference
judge, `monitor.c` and `frame.h` are unchanged, and the crate judges no claim.

| file | what it is |
|---|---|
| `src/frame.rs` | The 64-byte frame's constants ([frame.h](../../ipc-test/common/frame.h)) and the kind 4 payload offsets and flags (`vssframe.py`'s `P_*` and `F_*`). |
| `src/kind4.rs` | `fnv1_32`, `digest_of`, `pack_bits`, `encode`, `layout_errors`, `decode` and `age_field`, with `vssframe.py`'s refusals in its order. A refusal has a stable code (`overflow`, `seq-zero`, `absent-slot-4`, ...); its text is never compared. The crate reads no generated contract: the digest comes in as a value. |
| `src/link.rs` | The svc client: one connection with TCP_NODELAY, one request outstanding at a time. `roundtrip` reads exactly 64 bytes within a reply deadline (3000 ms by default, as `kind4_client._roundtrip`); `end_session` shuts the write side and takes any byte in the next 200 ms as an error. |
| `src/bin/vssclaim.rs` | The command line, below. |
| `vectors.py` | The test-time vector writer. It writes what `vssframe.py` and [rules.py](../frame/rules.py) say about a set of inputs; its docstring holds the file format and the `rt` rule. |

## Build and run

In WSL Ubuntu-24.04 only, with the toolchain [rust-toolchain.toml](rust-toolchain.toml) pins (1.100.0,
minimal, with clippy and rustfmt) installed in `~/.rustup` and `~/.cargo`. Every cargo call runs with
`--locked --offline` and with `RUSTUP_AUTO_INSTALL=0` and `RUSTUP_TOOLCHAIN=1.100.0`, so neither a crate nor a
toolchain can be fetched, and with `CARGO_TARGET_DIR` outside the tree:

    cd sdv/claimrs
    RUSTUP_AUTO_INSTALL=0 RUSTUP_TOOLCHAIN=1.100.0 CARGO_TARGET_DIR=~/.cache/claimrs/target \
        ~/.cargo/bin/cargo --locked --offline build --release

- `vssclaim consts` prints the frame constants under frame.h's names, one `NAME VALUE` line each.
- `vssclaim vectors FILE` checks the codec against a vector file: `ok NAME` or `diff NAME ...` per record,
  then `vectors done: total=N matched=M`.
- `vssclaim probe --host H --port P --vectors FILE [--reply-timeout-ms MS]` encodes every `rt` record's
  base with this crate's encoder and holds it to the record's request, all before it connects. Then it sends
  each record's frame (the request with its patch) on one connection and compares the whole reply with the
  record's, ends the session and prints `probe done: sent=N matched=M`. It prints no time and has no stamp
  mode.
- Exit codes: 0 when everything matched and the session ended clean; 1 for a mismatch or a link error; 2 for
  a usage error or a vector file it refuses, always before any connect. A file whose `rt` patch touches a
  byte the `rt` rule does not let it is refused.

A vector file comes from `vectors.py` at run time and is never committed, so it cannot go stale after the
contract is regenerated: `python3 sdv/claimrs/vectors.py OUT` writes the codec vectors from the generated
contract in `sdv-out/gen`.

## Tests

[tests/test_sdv_claimrs.py](../../tests/test_sdv_claimrs.py) holds the crate three ways, which must agree:
`cargo test` (written from the layout and the published FNV-1 values only), `vssclaim vectors` against the
Python codec and judge, and `vssclaim probe` end to end on loopback against the vss monitor built natively
from `monitor.c` with gcc, on C21's 10,000 seeded frames and the eleven `build_cases` frames. It also holds
the writer itself, the probe's failure paths against a fake peer, `cargo fmt --check` and clippy with
`-D warnings`. The module runs on Linux when rustup lists `1.100.0-x86_64-unknown-linux-gnu` and the
generated contract is in `sdv-out/gen`, and skips otherwise; with `CLAIMRS_REQUIRED=1` every skip in it is a
failure.

## What this does not demonstrate

- **No timing.** The probe records no time, and nothing here compares Rust with Python or C for speed.
- **No aarch64, no Orin and no guest.** The crate runs on the PC only. The monitor its tests use is the gcc
  build on x86-64, not the guest's qcc binary.
- **The bridge stays Python, and so does every source adapter.** Agreement on the tests' inputs is not
  agreement on every input.
- **The memory safety is this crate's own.** `unsafe` is forbidden in this crate only; std and the kernel
  are trusted. The L4T side stays untrusted, and the judgement that matters is still `monitor.c`'s, which is
  unchanged.
- **No qualified compiler and no ISO 26262 or other certification claim.** Rust 1.100.0 is an upstream
  compiler.
