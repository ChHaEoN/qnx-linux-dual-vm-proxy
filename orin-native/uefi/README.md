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
