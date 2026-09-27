# qnx-host-shmem-probe — Phase 2.5 (cloud, ADR-002 RQ-2 host<->guest shmem spike)

A minimal, **host-only** smoke test for the crux question raised in the
2026-07-28 shmem-viability spike (see `../../docs/findings.md` and
`../../docs/phase2-topology-decision.md` RQ-2): can an ordinary QNX
**host** userspace process on `qnx-qhv` (NOT itself a `qvm` guest) create
or attach to a named shared-memory region via the QNX Hypervisor
Virtualization API (`hyp_shm.h` / `libhyp.a`), the way QNX's own vendor
docs say a host "may"?

## What it does

`probe.c` calls `hyp_shm_attach_ext()` to create or attach the named region
`phase2-rq2-probe` (4096 bytes), writes the `"hyp-shm-host-ok"` test pattern,
calls `hyp_shm_poke()`, and detaches — with **no** `vdev shmem` line in any
`g2.conf` and **no** guest involvement. It prints each call's `rc` and
`errno`; `rc` is the authoritative result, since the library does not clear
`errno` on success.

It was run on 2026-07-28 on the QHV host image; the outcome and its curated
log (`qhv-tcg-rq2-hyp-shm-host-probe.log`) are held locally under NC QDL v7
4.6(i).

## What this does NOT demonstrate

- **The guest-side half is not in this program.** `probe.c` adds no
  `vdev shmem` line to the guest's `g2.conf` and runs no guest-side code.
  The guest-side half is a separate program,
  [../qnx-guest-shmem-probe/](../qnx-guest-shmem-probe/), paired with this
  directory's `roundtrip.c`.
- No latency/throughput measurement of any kind — this is a pure
  create/attach/poke/detach existence check.
- No IPC protocol — a real transport would still need an application-level
  framing/notification scheme built on top of `guest_shm_control`'s
  `notify` bitset (which only tells you "something changed", not how much
  or what), analogous to what `../common/console_io.h` does for the
  virtio-console byte stream.

## Build

```
qnxsdp-env.bat            # Windows
make                      # -> hyp-shm-probe + hyp-shm-roundtrip (aarch64le ELF, both link -lhyp)
```

`hyp-shm-roundtrip` (`roundtrip.c`, added 2026-07-28) is the host-side half
of the guest-side spike documented in
[../qnx-guest-shmem-probe/README.md](../qnx-guest-shmem-probe/README.md) —
same create/attach/write as `probe.c`, but polls for a guest write-back
instead of detaching immediately.

Build evidence (2026-07-28): `qcc -Vgcc_ntoaarch64le -std=gnu99 -Wall
-Wextra -Wformat=2` (zero warnings), both binaries.

## Run

Staged and run the same way `qnx-host-client` is (see
`../qnx-host-client/README.md` and `../../scripts/qhv/post_start.custom`
for the pattern) — **but this program was never wired into the committed
`post_start.custom`.** It was staged as a one-off diagnostic (matching the
project's established "diagnostic variant, never committed, reverted
after use" convention — see `docs/findings.md`'s 2026-07-28 root-cause
entry for the precedent) directly into the gitignored
`qhv/host/local/snippets/` build directory, tested, then the build
directory was regenerated from the clean committed sources via
`scripts/build-qhv.bat` to leave no trace in the repo-tracked
configuration. To repeat the spike: build this program, append a
`[perms=555] hypervisor/hyp-shm-probe=<path>` line to
`qhv/host/local/snippets/data_files.custom` and an invocation block to
`qhv/host/local/snippets/post_start.custom` (do **not** edit
`scripts/qhv/post_start.custom` for this — that file is the committed
Phase-2 pipeline), then re-run the host build step of
`scripts/build-qhv.bat` (mkqnximage's `--type=qemu ... --build` line)
directly so it picks up the manual edits.

## Status

Both halves of the RQ-2 spike were run on 2026-07-28 — this host-only
probe, then the two-way exchange of
[../qnx-guest-shmem-probe/README.md](../qnx-guest-shmem-probe/README.md)
with this directory's `roundtrip.c` as its host side (this original
`probe.c` is left unchanged). Their outcomes are held locally under NC QDL
v7 4.6(i).
