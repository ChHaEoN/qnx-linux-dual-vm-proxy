# `orin-native/uefi/` — the M5 loader and its PC rehearsal

**Phase 3b, M5-F.** These files boot the pinned QNX image from the firmware's
own UEFI Shell instead of from Linux's `kexec`. Everything here runs on the PC
until the board session; nothing in this directory contacts the board.

Design: [`m5-design.md`](../../results/orin-native-port/20260909T1100Z/m5-design.md),
§3.3 (the loader), §3.4 (the PE layout and the gate), §6.1 (T0) and §13 (the
implementation decisions these files follow).

## What is here

| File | Role |
|---|---|
| `m5load-head.S` | the hand-written DOS and PE headers, the entry, the post-exit console writers, the EL2 exception table, and the trampoline that takes the CPU and branches |
| `m5load.c` | steps 1-10: arguments, the device tree, the CRCs, the allocation and copy, the map rules, `check`, `go`, `ExitBootServices` |
| `efi-min.h` | only the UEFI types and table offsets the loader uses, written from the specification |
| `m5load.lds` | one section, blob last, link base as an argument |
| `blob-consts.py` | derives the payload's length, CRC32 and `image_size` from the payload itself |
| `build-m5-loader.sh` | builds, links twice, flattens, and runs the gate |
| `m5-gate.py` | the ten checks of §3.4; any miss fails the build |
| `t0/contract-probe.S`, `t0/contract-probe.lds` | the T0 payload, which stands in for the kimg so no QNX byte runs under QEMU |
| `t0/run-t0.ps1` | the five QEMU cases |
| `com3-term.ps1` | the board session's terminal: receives byte-exact, sends only when armed |

## The terminal, at the board

`com3-term.ps1` is the only thing in this project that can put a byte on the
board's UART, so it is built to fail toward silence:

- **Forwarding starts disarmed.** F12 arms and disarms it; F12 itself is never
  sent. The state is in the window title and printed on every change.
- **It disarms itself** after the Enter that ends a `go` line — and also after
  the Enter that ends any line it could not follow. An arrow key or Escape marks
  the line unreliable, because the firmware's own line editor moves the cursor
  and this script cannot track that. A line recalled from history therefore
  costs one extra F12, which is the right price: the first version tracked
  arrows as text and would have stayed **armed** through `go`, the reset and the
  firmware's autoboot countdown.
- **Only ESC, the four arrows, Enter, Backspace and printable ASCII** can ever
  be sent. Every other key is ignored, so no control character reaches the board.
- **Ctrl+] or F10 exits**, and the exit test is layout-independent: on layouts
  where `]` is AltGr+digit, AltGr is Ctrl+Alt, and that keypress must not both
  exit and send.
- **Records are never overwritten.** Both logs are created, not truncated, so a
  retry cannot destroy the previous attempt's record.
- `-SelfTest` checks the encoder, the tracker and the exit keys with no port, no
  board and no console input.

`out/` holds build products and is git-ignored: on the board build it carries
QNX bytes, which are evaluation material under NC QDL v7 4.6(i) and are never
committed.

## Building

```sh
KIMG=orin-native/shim/out/m1b/m1b-p1.kimg \
KIMG_SHA256=cf0715ef7f0e447228d336557772a53b0f822709428a2f03610cfbaec9bd2f8e \
./orin-native/uefi/build-m5-loader.sh
```

`T0=1` builds the rehearsal image with the contract probe embedded instead. The
gate compares the two builds and requires that they differ only in the blob and
its three constants.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0.ps1
```

## What the loader prints

Before `ExitBootServices`, on ConOut, one token per line:

| Token | Meaning |
|---|---|
| `M5L start mode=… el=… ctr=… self=…` | which mode, what exception level, the cache line sizes, and where the firmware put the loader |
| `M5L fdt addr=… size=…` | the device tree it found |
| `M5L con kind=tcu\|pl011\|none base=…` | the console chosen for the post-exit tokens (§13 decision C) |
| `M5L crc src=ok`, `M5L crc dst=ok` | the payload is the built one, and the copy matches |
| `M5L map type=… start=… pages=… attr=…` | every descriptor overlapping the window, the zone or the tree |
| `M5L CHECK PASS` | every rule passed; nothing was changed |
| `M5L GO` | the last line before the exit |
| `M5L REFUSE <rule>` | the first rule that failed: `fdt`, `crc src`, `crc dst`, `kimg`, `alloc status=…`, `window reason=gap\|type at=…`, `zone type=…`, `el=1` |

After the exit, on the TCU mailbox or the PL011: `M5L-EBS ok`, `M5L-JUMP`, and
on failure `M5L-EBS FAIL` or `M5L-EXC ESR=… ELR=…`.

The T0 payload prints `PROBE EL=… X0=… X1=… X2=… X3=… MAGIC=… SCTLR_EL2=… DAIF=… PC=…`.

## J7a: the UEFI-entry arm (`M5L_J7A`)

Design: [`s1-design.md`](../../results/orin-native-port/20260909T1100Z/s1-design.md)
§15.13.3 (UM1-UM10) and §15.13.4 (the image, the loader, T0). Everything J7a
adds to `m5load.c` sits behind the compile-time switch `M5L_J7A`; with it off,
the object is M5's byte for byte (UM8, checked by D0b). `m5load-head.S` is not
touched.

| File | Role |
|---|---|
| `m5load-rules.h` | the pure J7a rules, included only under `M5L_J7A`: the window-2 sweep, the canary rule, the tree-overlap rule and the reserved-memory walk; no static data, no stored pointer, no allocation |
| `t0/pad-like.py` | `T0_PAD_LIKE`: pads the probe to a kimg's length and copies its `image_size`, reading only the header our shim wrote |
| `t0/t0u-rules.c`, `t0/run-t0u.ps1` | T0u: the rules compiled for the host (MSVC) and run on synthetic maps and trees |

Build in a git worktree, never in the main checkout, whose `out/` holds M5's
gated loader:

```sh
M5L_J7A=1 T0=1 T0_PAD_LIKE=<kimg> ./orin-native/uefi/build-m5-loader.sh
M5L_J7A=1 KIMG=<kimg> KIMG_SHA256=<J6c's registered kimg_sha256> ./orin-native/uefi/build-m5-loader.sh
M5L_J7A=1 T0=1 T0_PAD_LIKE=<kimg> T0_FORCE=um6-first OUT_DIR=<scratch> ./orin-native/uefi/build-m5-loader.sh
```

The gate adds item 11 (the window-2 and canary constants equal
`t234_startup.h`'s) and item 12 (no `T0_FORCE` build as a board build; a J7a
board build must match a J7a T0 build outside the blob and constants), and
item 8 compares builds of the same variant only.

J7a adds these lines before `ExitBootServices`:

| Token | Meaning |
|---|---|
| `M5L variant=j7a` | directly after the start line, whose grammar is unchanged |
| `M5L self w2=yes\|no canary=none\|c1\|c2\|c3` | the loader's own pages against window 2 and the canaries |
| `M5L fdt addr=… size=… crc32=…` | the tree stamp; `M5L REFUSE fdt reason=w2\|canary` when the tree lies in window 2 or over c1 |
| `M5L resmem name=… status=… map=… prop=… over=… base=…`, `… form=unparsed`, `M5L resmem done` | class-only report of `/reserved-memory` children over window 2 or a canary; never a refusal |
| `M5L canary cN preclaim=ok` | UM4's claim of each canary; on failure `M5L canary cN preclaim=fail status=…`, the descriptors over it, `M5L REFUSE canary cN status=…` |
| `M5L map …` over window 2 | UM5's descriptors, in the existing form |
| `M5L REFUSE w2 reason=gap\|type\|rt at=…`, `M5L REFUSE canary cN reason=type at=…` | UM5's sweep and canary rule |
| `M5L W2 PASS` | before `M5L CHECK PASS`, so `check` and `go` print the same prelude |
| `M5L REFUSE w2-final` | UM6 failed on the first try; everything released, back to the Shell. A later-try failure takes the existing `M5L-EBS FAIL` and reset |

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0.ps1 -Variant j7a `
  -LoaderDir <worktree>\orin-native\uefi\out\t0 -SwitchOffDir <switch-off T0 build> `
  -ForceFirstDir <um6-first build> -ForceLaterDir <um6-later build>
powershell -NoProfile -ExecutionPolicy Bypass -File orin-native\uefi\t0\run-t0u.ps1
```

## Never (m5-design §7.4, binding on this code and on the session)

- Never write a UEFI variable, `Boot####` or `BootOrder`; never run `bcfg`,
  `setvar`, `efibootmgr -c/-n/-o/-B`, or a `mm` write.
- Never enrol or delete a Secure Boot key, and never set a menu password.
- Never place a capsule under `EFI/UpdateCapsule`, and never run a fuse or
  flashing tool.
- Never create `BOOTAA64.EFI`, and never use the firmware's "Boot From File".
- Never put a `startup.nsh` on any filesystem the board can map. T0's
  `startup.nsh` exists on the QEMU FAT drive only.
- Never widen a tolerance at the board: a refusal is recorded, the loader is
  revised on the PC, and T0 runs again first.
- The gate never disassembles the embedded payload — only our own trampoline,
  bounded by its symbols (NC QDL v7 4.6(c)).

## What a T0 pass does not show

T0 says nothing about cache coherency after the copy: QEMU's TCG invalidates
its translated code when the guest writes the page, so a loader missing the
instruction-cache step would still pass there. That is why the gate reads the
sequence statically, and why the board run is the only real test (§3.2 item 4,
§6.1, risk R33).
