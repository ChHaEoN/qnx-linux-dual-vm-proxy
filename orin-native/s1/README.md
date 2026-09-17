# `orin-native/s1/` — the S1-F Linux guest and its PC tooling

**Phase 3b, S1-F.** S1-F runs a Linux guest, with no GPU, under native qvm on the
Jetson Orin Nano. The guest is the board's stock L4T `Image`, a small busybox
initrd and one pinned configuration. It is rehearsed first under the TCG QHV host
on the PC, then run natively. Nothing in this directory contacts the board; only
`orin-native/startup/s1-board.sh` does, and only with the owner at the plug.

**2026-09-14:** T0 was built and gated on the PC. Nothing has run under QEMU or
on the board.

Design: [`s1-design.md`](../../results/orin-native-port/20260909T1100Z/s1-design.md)
(revision 2; the owner took D1-D19 as recommended). The sections these files
follow:
- §3.5, the initrd
- §3.7, the configuration
- §4.2, the files
- §6, the procedure
- §7.3, the Never list
- §14, the implementation decisions, deviations and T0 gate verdicts

## What is here

| File | Role |
|---|---|
| `s1-linux.conf` | The guest configuration (§3.7). It carries no comments: its bytes are staged unchanged on every leg |
| `s1-conf.allow` | The configuration's allow-list: keywords, vdev types, forbidden words, and at most one approved non-GPU overlay (D13, D19) |
| `init.sh` | The guest's `/init`: mounts, `S1-INIT start`, `S1-INIT ready`, a heartbeat, then a shell on the console |
| `initrd.manifest` | Every initrd member: the source archive, path, mode and sha256, the links, `dev/console`, and the output pins |
| `mkcpio.py` | A newc cpio reader and writer (standard library only) that builds the initrd from the manifest |
| `parse-s1.py` | The configuration gate, the FDT checklist, the run parser and `kshcheck`: **the token contract** for every S1 line |
| `build-s1tcg-image.ps1` | Builds one TCG rehearsal host image under `qhv/s1tcg/` |
| `launch-s1tcg.ps1` | Boots it under QEMU-TCG, watches the serial file, then runs the parser |
| `post_start-s1tcg.custom` | The rehearsal host's post-start lines: `ksh /system/bin/s1-host.ksh`, then a reboot that ends QEMU |
| `out/` | Git-ignored. `out/l4t/` holds D3's copies of the board's `Image` and `initrd`; `out/initrd.cpio.gz` is the built initrd; `out/startup/` is the S1 startup |

Elsewhere:

| File | Role |
|---|---|
| `../startup/make-s1-images.sh` | Generates, checks, builds and wraps the board images; `--tcg` renders the TCG profile of the host script |
| `../startup/s1.build.in`, `../startup/s1-host.ksh.in` | The buildfile and host-script templates |
| `../startup/s1-board.sh` | The board procedure, driven from the PC: `stage`, `p0`, `p1`, `reboot`, `run`, `advice` and the record tools |
| `../startup/t234-orin-nano/` | The startup's `-b w2` and `-b w2,canary` options: window 2, and the three canaries startup fills |
| `../tools/s1con.c` | `stamp`'s stream mode on the guest console, plus bounded probe writes |
| `../tools/memcanary.c` | Read-only canary checks by name, an anonymous allocation, a held allocation, and a self-test |

## Before anything: Python and the inputs

- Run Python as **`python`** (3.12), never `python3`, which is a Microsoft Store
  alias on this PC.
- `out/l4t/Image` and `out/l4t/initrd` are an owner-run copy of the board's
  `/boot/Image` and `/boot/initrd` (D3). Their sha256s are pinned in
  `initrd.manifest`, `make-s1-images.sh`, `build-s1tcg-image.ps1` and
  `s1-board.sh`. Every step refuses a mismatch.
- The S1 startup is kept at `out/startup/startup-t234-orin-nano`, pinned as
  `PIN_STARTUP_S1`. The shared BSP output path must keep the M1b-M4 startup,
  because the M1b-M4 generators read it. Never leave an S1 build there. After a
  rebuild, copy the result to `out/startup/`, restore the shared path, and
  verify both hashes.

## Building the initrd

```sh
python orin-native/s1/mkcpio.py --selftest
python orin-native/s1/mkcpio.py build orin-native/s1/initrd.manifest
python orin-native/s1/mkcpio.py list orin-native/s1/out/initrd.cpio.gz
```

- `build` writes `out/initrd.cpio.gz`, and only when every pin holds. Paths in
  the manifest are relative to the manifest's own directory.
- **Two output pins:** the gzip file, and the cpio stream inside it. The cpio
  bytes depend only on the inputs. The gzip bytes also depend on the zlib build,
  so a mismatch in the gzip pin alone is reported as exactly that.
- `init.sh` is pinned in the manifest. An edit to `/init` needs a new pin there,
  a new initrd pin, and new pins in every generator.
- The manifest's `busybox` line checks the applets the guest uses, and `+math`
  checks that ash has `$(( ))` (R10). The link lines are checked against the
  source archive (R11).

## The gate and the parser

```sh
python orin-native/s1/parse-s1.py --selftest
python orin-native/s1/parse-s1.py conf orin-native/s1/s1-linux.conf
python orin-native/s1/parse-s1.py fdt qhv/s1tcg/attempt<N>/s1-fdt.dtb --conf orin-native/s1/s1-linux.conf
python orin-native/s1/parse-s1.py run qhv/s1tcg/attempt<N>/serial-raw.log --profile tcg --mode dryrun \
    --conf orin-native/s1/s1-linux.conf --image orin-native/s1/out/l4t/Image \
    --initrd orin-native/s1/out/initrd.cpio.gz
python orin-native/s1/parse-s1.py kshcheck FILE
```

`parse-s1.py` is the contract. Its module docstring and its `--selftest`
synthetic logs define every line the host script prints:
- `S1 CONFIG` with the item-5 fields;
- `S1 STATE`, `S1 HB k=N qvm=alive rc=absent` and `S1 FAIL_STATE`;
- `S1 DRYRUN rc=0 saved=yes … logger_errors=0`, with a `qvmlog` export that
  holds no line beginning with qvm's `[file:line] ` diagnostic form. Since T1
  attempt 1 a dryrun with any other exit code, or with such a line, fails L2
  (design C3 and §14.9);
- the export framing `S1 BEGIN name=<n> bytes=<n> md5=<hex> enc=base64` …
  `S1 END name=<n>`.

A change to any record's text is made in the parser and the template together.
Where the parser and the design disagree, the parser wins unless it is clearly a
bug.

- **`run`'s other options:**
  - `--profile tcg|board` and `--mode dryrun|boot|hold|host|q2`;
  - on the board, `--blackbox`, `--kexec-tree-sha256` and `--reset-reason`;
  - for the board's boot, hold and q2 steps, `--ref-conf-sha256` (T2's `conf_sha256`);
  - `--out-dir DIR|none`.
- **Output:** `run` writes `parse-s1.txt` and the decoded exports only into a
  git-ignored directory. `--out-dir none` writes nothing.
- **Exit codes:** 0 a verdict was given, pass or fail; 3 refused, because item-5
  stamps are missing; 1 an input error; 2 a refused output path or a usage error.
- **No figures:** the parser prints no FreeMem value and no duration.

## Generating and building the host images

```sh
# Generate and check only, into a scratch root (no SDP needed):
./orin-native/startup/make-s1-images.sh --generate-only --out orin-native/shim/out/s1-test

# The full board build of s1-m1b-p6, s1-h1, s1-n1, s1-n2 and s1-d1:
BSP=<extracted BSP tree> QNX_BASE=<SDP 8.0 install> ./orin-native/startup/make-s1-images.sh

# The TCG profile of the host script, for the builder below (no SDP needed):
./orin-native/startup/make-s1-images.sh --tcg
```

- **Output root:** `--out DIR`, else `$S1_OUT`, else `orin-native/shim/out/s1`,
  which is also where `s1-board.sh` looks by default. A build into another root
  needs `S1_KIMG_DIR` set to it on the board side.
- **The root must** lie inside the repository, be git-ignored, and lie outside
  the earlier milestones' `shim/out/m1b` to `shim/out/m4`, `orin-native/s1/out`
  and `qhv`, so a test run cannot overwrite a real output.
- **What a build writes:** each image gets `<img>.build`, `.ksh`, `.params`,
  `.ifs` and `.kimg`, plus its check texts. `<img>.params` carries the pins, the
  guard, `return_bound_s` and `capture_s` that `s1-board.sh` reads.
- **`s1-q2`** is refused without `--q2-limit`. D14's limit was never derived, and **B5 does not run**: OD1 (2026-09-16) settled the guest set as Linux only, so pass item 3 is not applicable. The image was never built; the `q2` mode is kept implemented as the design record (s1-design §6.10).

## The TCG rehearsal (T1-T3)

From PowerShell, one QEMU at a time:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\s1\build-s1tcg-image.ps1 -Variant lin -Mode dryrun -Tag t1a
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\s1\launch-s1tcg.ps1 -Attempt 1 -Variant lin -Mode dryrun -Tag t1a -QemuPath <QEMU 11.1.0>\qemu-system-aarch64.exe
```

| Step | Build | Launch `-Mode` |
|---|---|---|
| T1 | `-Variant lin -Mode dryrun` | `dryrun` |
| T2 | `-Variant lin -Mode boot` | `boot` |
| T3 | `-Variant hold` | `hold` |
| diagnostics | `-Variant d1 -Mode dryrun\|boot`, `-Variant d2` | as built; never a pass run |

- **The build needs:** run `make-s1-images.sh --tcg` first, because the builder
  takes the generator's rendering of the host script and cross-checks its params.
- **Mode and tag:** the mode is inside the image, so `lin` and `d1` refuse a
  build without `-Mode`. `-Tag` must be new.
- **Checks first:** `-CheckOnly` on either script runs the checks and writes no
  image and starts no QEMU.
- **Records:** `qhv/s1tcg/attempt<N>/`: `serial-raw.log`, `launch.log`,
  `parse-s1.txt`, `s1-fdt.dtb`. `LAUNCH_VERDICT` is the parser's verdict. Every
  TCG result is emulated and never a board result.

## The board session (B0-B5)

Owner at the plug from B0 to the last return (§2 rule 6, D15). Start each COM3
capture from PowerShell, into a new file for every run. A capture started from
Git Bash receives nothing, and `run` refuses a file that already holds an earlier
run's lines.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\m4\capture-com3-raw.ps1 -Seconds <capture_s from the image's params> -Out <new file under the record directory>
```

```sh
export ORIN_HOST=<user>@<address>   # from the environment only; never written into a file
export ORIN_KEY=<key file>          # optional
export S1_RECORD_DIR=results/orin-native-port/<utc>/s1

./orin-native/startup/s1-board.sh stage s1-n1
./orin-native/startup/s1-board.sh p0 s1-n1
./orin-native/startup/s1-board.sh reboot    # a fresh L4T boot before any quiesce
S1_COM3_LOG=<the running capture file> S1_REF_CONF_SHA256=<T2's conf_sha256> \
    ./orin-native/startup/s1-board.sh run s1-n1
# Only if the run prints NO RETURN:
./orin-native/startup/s1-board.sh advice results/orin-native-port/<utc>/s1/<step>/<img>-<utc>-board.log
```

- **Images and steps:** `s1-m1b-p6` is B1, `s1-h1` B2, `s1-n1` B3, `s1-n2` B4,
  `s1-q2` B5 (does not run: OD1 settled Linux only), and `s1-d1` a diagnostic.
- **Exit codes:**
  - 0 done;
  - 1 refused before the board changed;
  - 2 no return within the bound: read `advice`, never the clock alone;
  - 3 stopped with L4T running;
  - 4 `nvbootctrl` changed (F30): stop all board work.
- **Fixed limits:** the uptime limits (7,200 s, and 1,800 s with the quiesce),
  the quiesce and the governor pin cannot be overridden.
- **Self-tests:** `redact-selftest` and `harness-selftest` run on synthetic
  inputs, with no board.

## Privacy and records

- **Private until cleared.** Every serial log, COM3 capture, black box, dumped
  FDT and parser output from S1 is evaluation output under NC QDL v7 4.6(i). It
  stays private until the supervising professor has been consulted. The
  repository is public, so a push is a publication.
- **Where records go:**
  - TCG records under `qhv/s1tcg/attempt<N>/`;
  - board records under `results/orin-native-port/<utc>/s1/`;
  - never under `logs/sample-boot/`.

  The first two are git-ignored; the scripts check it. The run note
  `s1-runs.md` lives only on the local branch `m3-results-unpublished`.
- **Records, not measurements.** No duration, rate, FreeMem value or stream size
  is reported (§2 rule 8). `extract` masks every figure.
- **No identifiers in a committed file.** That covers user names, the board
  hostname, addresses, MAC addresses, key names and real Windows user paths. The
  scripts take hosts, keys and paths from the environment or discover them. Board
  records are redacted after the parser has read the raw copies.

## Licence

- **Our files.** `mkcpio.py`, `parse-s1.py`, `init.sh`, `initrd.manifest` and
  `s1-conf.allow` are MIT, per their SPDX lines. `s1-linux.conf` has no header on
  purpose, and the PowerShell scripts and the `.custom` snippet follow their M4
  precedents with none; files without an SPDX line fall under the repository's
  MIT licence. `make-s1-images.sh`, `s1-board.sh`, the startup's board directory
  and the two tools are Apache-2.0, matching the BSP templates the board
  directory is modelled on.
- **Linux bytes.** The Linux `Image` (GPLv2), busybox (GPLv2) and glibc
  (LGPL-2.1) are private copies of the board's own files. They live only under
  `out/`, inside host images under `/qhv/`, or in `*.kimg`, and are never
  committed; a push would be distribution. `mkcpio.py` reads strings of busybox,
  a GPL binary, and is never pointed at a QNX file.
- **QNX bytes (NC QDL v7 4.6(c)).** No QNX-shipped binary is read, disassembled
  or string-searched. SDP files are opaque: mkifs and mkqnximage take them, and
  hashes identify them. `dumpifs` runs only on our own IFS, to extract our own
  payload, as the M3 and M4 generators do. Host IFSs, kimgs, `.sym` files and the
  built `s1con` and `memcanary` binaries are never committed.
- **The dumped FDT** is our private evaluation output, decoded with our own
  reader (D12, R27).

## Never (s1-design §7.3, binding on this code and on every session)

- Load a `pass` line, a `smmu` vdev or any GPU node in an S1 configuration; or an
  `fdt` overlay, except a non-GPU overlay D19 has approved by hash.
- Add a range to `add_ram` other than windows 1 and 2; widen window 2 into the
  GPU range, CMA or above; or resize it without rerunning B1 and B2.
- Add a physical write mode or an address argument to `memcanary`, or call
  `memcanary asinfo` or `verify` in a TCG script.
- Cut power between the image's reset and a validated L4T boot, except under
  M5's exception (§2 rule 6a); cut power a second time under that exception.
- Override `s1-board.sh`'s uptime limits (7,200 s; 1,800 s with the quiesce), or
  run a quiesce on an L4T that was not freshly booted.
- Run a board S1 rung without the owner at the plug, or while the owner is away.
- Read GPU MMIO from the host in any S1 image (§3.8).
- Install a package on the board, or download a kernel source tree, as a step of
  S1 (D16).
- Commit `Image`, the initrd, a host IFS, a kimg, a `.sym` or a dumped FDT.

## What a T0 or TCG pass does not show

- **T0 is a build and a set of gates.** Nothing in it booted.
- **A TCG pass does not predict a native one.** TCG does not exercise the
  A78AE, the board's PSCI, window 2 or physical pinning.
- **No pass is a measurement or an isolation claim.** It gives no timing and no
  isolation or memory-integrity claim beyond the canaries watched in the runs
  made.
- **Nothing here is publishable** before the 4.6(i) consultation. §10 lists the
  rest.
