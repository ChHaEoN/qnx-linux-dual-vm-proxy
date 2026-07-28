# qnx-guest-shmem-probe — Phase 2.5 (cloud, ADR-002 RQ-2 guest-side shmem spike)

The **guest**-side counterpart to
[../qnx-host-shmem-probe/](../qnx-host-shmem-probe/), which resolved RQ-2's
host-only half on 2026-07-28 (see `../../docs/findings.md` and
`../../docs/phase2-topology-decision.md` RQ-2). This program runs inside
`qnx-guest` — a `qvm` guest, **not** the `qnx-qhv` host — and attaches to the
SAME named region (`phase2-rq2-probe`) via a completely different API
family: `qvm/guest_shm.h`'s raw-MMIO factory-page protocol (no library, no
`ChannelCreate`/pulses — just `mmap_device_memory()` onto the physical
address a `vdev shmem` line's `loc`/`intr` declares, plus direct register
reads/writes).

## Result — RESOLVED YES, empirically, on a live boot (2026-07-28, second attempt)

A real host<->guest shared-memory round trip, captured on a live boot:

```
gprobe: factory mapped @paddr=0x1c0f0000, signature=0x4d534732474d5651 (expect 0x4d534732474d5651)
gprobe: guest_shm_create name='phase2-rq2-probe' pages=1 -> status=GSS_OK (0)
gprobe: region ready -- control-page GPA=0x1000 hypervisor-assigned-vector=43
gprobe: control page status=0x00030000 idx=1
gprobe: read 16 bytes at data+0: "hyp-shm-host-ok"
gprobe: MATCH -- host pattern read back byte-exact
gprobe: wrote guest pattern "hyp-shm-guest-ok" at data+64 for the host to poll
gprobe: NOT using InterruptAttach()/control->notify this session (see header comment + README Status) -- pure-polling MMIO round trip only.
gprobe: done, exit=0
...
roundtrip: SAW GUEST WRITE-BACK after 24s: "hyp-shm-guest-ok"
roundtrip: detached, exit=0
```

(curated log:
[../../logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-success.log](../../logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-success.log))

This is a genuine two-way exchange across the real `qvm` EL2 host <-> EL1
guest partition boundary:

1. **Host -> guest**: the `qnx-qhv` host (`../qnx-host-shmem-probe/roundtrip.c`,
   run *before* `qvm` even launches the guest) creates `phase2-rq2-probe`
   via `hyp_shm_attach_ext()` and writes `"hyp-shm-host-ok"` at offset 0.
   The **guest** (this program) later attaches to the same name via
   `guest_shm_create()`, gets `GSS_OK`, and reads that exact string back
   byte-for-byte.
2. **Guest -> host**: this program writes `"hyp-shm-guest-ok"` at offset 64.
   The host's `roundtrip.c`, still alive and polling (it never detached),
   sees it 24 seconds later and prints it before detaching.

Because both ends attached with the **same name and the same size** (4096
bytes: the host requests it in bytes via `hyp_shm_attach_ext`, the guest in
4 KB pages via `guest_shm_factory.size` — `1` page == `4096` bytes), and the
guest's `status` came back `GSS_OK` (create-or-attach succeeded) rather than
`GSS_NOMEM`/`GSS_ILLEGAL_NAME`/etc., this also answers the crux question the
2026-07-28 host-only session left open: **the host's `hyp_shm`-created
region and the guest's `vdev shmem`-attached region are the same underlying
host-OS/kernel-level object**, not two independent registries that happen to
share a name. A `qnx-qhv` host process (via `libhyp.a`) and a `qnx-guest`
process (via the raw-MMIO `vdev shmem` protocol) can genuinely rendezvous on
one named shared-memory region.

## What this took two attempts to get right (real, not hypothetical)

The **first** boot ([../../logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log](../../logs/sample-boot/qhv-tcg-rq2-shmem-roundtrip-attempt1-bus-error.log))
crashed:

```
gprobe: factory mapped @paddr=0x1c0f0000, signature=0x4d534732474d5651 (expect 0x4d534732474d5651)
Bus error (core dumped)
=== gshm-probe exit=138 ===
```

The signature read (a single 8-byte scalar load through the `volatile
struct guest_shm_factory *` pointer) worked — proving the `vdev shmem
loc/intr` MMIO wiring itself is real and live. The crash happened
immediately after, in the very next statement: a block `memcpy()` of the
32-byte region name into `factory->name`. **Diagnosis:** the factory page is
an MMIO-trapped virtual-register file (per the vdev shmem docs, "the client
in a guest ... can use the shmem vdev register set" — these are registers,
not RAM), and `qvm`'s MMIO trap decoder evidently does not accept whatever
wide/vector store instruction the target's `memcpy()` chose for a 32-byte
copy (aarch64 `memcpy` routinely uses paired 8- or 16-byte NEON
load/store-pair instructions for a copy this size). This is the same *class*
of problem as the unrelated Orin GICv3 `KVM_EXIT_ARM_NISV` finding elsewhere
in this project (`docs/orin-port.md`'s risk register) — an MMIO trap
emulator that only decodes a subset of the instruction encodings a compiler
might actually generate. **Fix:** write the name (and, defensively, the
shared data-area read/write too, since only one more boot cycle was
budgeted) byte-by-byte in an explicit loop, forcing single-byte volatile
stores instead of a block copy. The second attempt, with that fix, is the
clean run quoted above. See `probe.c`'s inline comments for the exact
before/after.

## What this does NOT demonstrate

- **No interrupt/notify-driven round trip.** `factory->vector` (the real
  hypervisor-assigned interrupt number, `43`, matching the `intr gic:43`
  declared in `g2.conf`) is read and logged, but this program deliberately
  does **not** call `InterruptAttach()` or write
  `guest_shm_control.notify`. The vdev's interrupt line's edge-vs-level and
  masking semantics were not confirmed in the time available, and guessing
  wrong risks an interrupt storm that hangs the guest under TCG with no fast
  iteration loop available to debug it live — a real, cited risk, not
  hypothetical caution. This is the concrete next step if the notify path is
  picked up again (see "Status" below). The round trip proven here is
  **pure MMIO polling** on both ends (the host's `roundtrip.c` polls with
  `sleep()`; the guest never blocks waiting for a notification at all — it
  writes once and exits).
- **No latency/throughput measurement.** Same as the host-only probe: this
  is an existence + byte-exactness check, not a benchmark. (The existing
  virtio-console IPC benchmark, `../qnx-host-client/`, still ran cleanly
  immediately afterward in the same boot — one sentinel-kick recovery, the
  same known, already-documented non-deterministic `qvm`/TCG stall, nothing
  new — confirming the new `vdev shmem` wiring did not regress the
  committed Phase-2 pipeline.)
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

Guest-side RQ-2: **RESOLVED, proven live, two-way.** The host-only half
(2026-07-28, earlier session) and this guest-side half (2026-07-28,
continuation session) together prove a real host<->guest shared-memory
exchange across the `qvm` partition boundary using the two different,
vendor-documented API families on each side. Open, explicitly not
attempted: the interrupt/notify-driven path (`InterruptAttach()` +
`guest_shm_control.notify`) — everything proven here is polling-based.
Whether this transport is worth building a full replacement IPC layer on
top of (vs. the sentinel-recovery-patched virtio-console approach already
carrying the committed Phase-2 benchmark) is a call for a future
session/Architect decision, not made here.
