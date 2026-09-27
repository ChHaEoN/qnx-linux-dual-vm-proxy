# qnx-guest-shmem-probe — Phase 2.5 (cloud, ADR-002 RQ-2 guest-side shmem spike)

The **guest**-side counterpart to
[../qnx-host-shmem-probe/](../qnx-host-shmem-probe/), which covers RQ-2's
host-only half (see `../../docs/phase2-topology-decision.md` RQ-2). This program runs inside
`qnx-guest` — a `qvm` guest, **not** the `qnx-qhv` host — and attaches to the
SAME named region (`phase2-rq2-probe`) via a completely different API
family: `qvm/guest_shm.h`'s raw-MMIO factory-page protocol (no library, no
`ChannelCreate`/pulses — just `mmap_device_memory()` onto the physical
address a `vdev shmem` line's `loc`/`intr` declares, plus direct register
reads/writes).

## What it does

1. **Host -> guest**: the `qnx-qhv` host (`../qnx-host-shmem-probe/roundtrip.c`,
   run *before* `qvm` launches the guest) creates `phase2-rq2-probe` via
   `hyp_shm_attach_ext()` and writes `"hyp-shm-host-ok"` at offset 0. The
   **guest** (this program) maps the `vdev shmem` factory page at the
   `loc` its `g2.conf` line declares, checks the factory signature, calls
   `guest_shm_create()` for the same name and one 4 KB page, and reads 16
   bytes at offset 0, comparing them with the host's pattern.
2. **Guest -> host**: this program writes `"hyp-shm-guest-ok"` at offset 64
   and exits. The host's `roundtrip.c` stays attached and polls for it.

Both ends ask for the **same name and the same size** (4096 bytes: the host
requests it in bytes via `hyp_shm_attach_ext`, the guest in 4 KB pages via
`guest_shm_factory.size` — `1` page == `4096` bytes).

It was run on 2026-07-28. The outcome, including what the first attempt did
and the fix it needed, and the curated logs
(`qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log`,
`qhv-tcg-rq2-shmem-roundtrip-success.log`) are held locally under NC QDL v7
4.6(i).

## Why the factory page is written byte by byte

The program writes the region name into `factory->name`, and reads and
writes the shared data area, **byte by byte** in explicit loops of
single-byte volatile accesses, never with a block `memcpy()`. The factory
page is an MMIO-trapped virtual-register file (per the vdev shmem docs, "the
client in a guest ... can use the shmem vdev register set" — these are
registers, not RAM), and an aarch64 `memcpy()` of 32 bytes routinely uses
paired 8- or 16-byte load/store-pair instructions, which an MMIO trap
emulator need not decode. See `probe.c`'s inline comments for the exact
code.

## What this does NOT demonstrate

- **No interrupt/notify-driven round trip.** `factory->vector` (the
  hypervisor-assigned interrupt number; `g2.conf` declares `intr gic:43`) is
  read and logged, but this program deliberately does **not** call
  `InterruptAttach()` or write `guest_shm_control.notify`. The vdev's
  interrupt line's edge-vs-level and masking semantics were not confirmed in
  the time available, and guessing wrong risks an interrupt storm that hangs
  the guest under TCG with no fast iteration loop available to debug it
  live. This is the concrete next step if the notify path is picked up again
  (see "Status" below). The exchange is **pure MMIO polling** on both ends
  by design (the host's `roundtrip.c` polls with `sleep()`; the guest never
  blocks waiting for a notification at all — it writes once and exits).
- **No latency/throughput measurement.** Same as the host-only probe: this
  is an existence + byte-exactness check, not a benchmark.
- **Not wired into the committed pipeline.** Like the host-only probe, this
  was staged directly into the gitignored `qhv/host/local/snippets/` and
  `qhv/guest/local/snippets/` build trees (a manual `vdev shmem` line added
  to the `g2.conf` `printf` in a **staged copy** of `post_start.custom`, and
  a manual invocation added to a staged copy of `guest-post_start.custom`),
  built via `mkqnximage --build` directly, then **reverted** by re-running
  `scripts/build-qhv.bat` (which regenerates both build trees from the
  clean committed `scripts/qhv/*.custom` sources) — same convention as
  `../qnx-host-shmem-probe/README.md`'s precedent. `scripts/qhv/post_start.custom`
  and `scripts/qhv/guest-post_start.custom` are unchanged by this session.

## g2.conf used for this spike (not committed to scripts/qhv/post_start.custom)

Appended to the existing guest `g2.conf` (pl011/virtio-console/virtio-blk,
unchanged):

```
vdev shmem
 loc 0x1c0f0000
 intr gic:43
 allow phase2-rq2-probe
```

`0x1c0f0000` sits just past the existing `virtio-blk` factory-ish MMIO
region (`0x1c0d0000`) and `gic:43` is the next unused interrupt after the
existing `gic:37`/`gic:41`/`gic:42` assignments (verified against
`scripts/qhv/post_start.custom` before reuse). `allow phase2-rq2-probe`
restricts the guest to exactly the one named region this spike needs — the
least-privilege posture the vdev's own `allow`/`deny` restrictions list is
designed for; see `../../scripts/qhv/g2.conf.allow`'s new `allow` keyword
and `vdev:shmem` type entries (added this session, with the same
least-directive reasoning inline there).

## Build

```
qnxsdp-env.bat            # Windows
make                      # -> gshm-probe (aarch64le ELF, no extra libs -- guest_shm.h is header-only)
```

Build evidence (2026-07-28): `qcc -Vgcc_ntoaarch64le -std=gnu99 -Wall
-Wextra -Wformat=2` (zero warnings).

## Run

Staged the same way as `../qnx-host-shmem-probe/README.md` describes for
its own diagnostic run: append a `[perms=555] gshm-probe=<path>` line to
`qhv/guest/local/snippets/ifs_files.custom`, append an invocation block to
`qhv/guest/local/snippets/post_start.custom`, add the `vdev shmem` line
above to the `g2.conf` `printf` in `qhv/host/local/snippets/post_start.custom`
and a `hyp-shm-roundtrip` invocation (see `../qnx-host-shmem-probe/roundtrip.c`)
near the top of the same file (before `qvm` launches), then rebuild guest
then host directly with `mkqnximage --build` (not `build-qhv.bat`, which
would overwrite the manual edits with the committed sources).

## Status

Both halves of the RQ-2 spike — the host-only probe and this two-way
exchange — were run on 2026-07-28; their outcomes are held locally under NC
QDL v7 4.6(i). Open, explicitly not attempted: the interrupt/notify-driven
path (`InterruptAttach()` + `guest_shm_control.notify`) — both programs
poll. Whether this transport is worth building a full replacement IPC layer
on top of (vs. the sentinel-recovery virtio-console approach already
carrying the committed Phase-2 benchmark) is a call for a future
session/Architect decision, not made here.
