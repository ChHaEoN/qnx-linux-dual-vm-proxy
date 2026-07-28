# qnx-host-shmem-probe — Phase 2.5 (cloud, ADR-002 RQ-2 host<->guest shmem spike)

A minimal, **host-only** smoke test for the crux question raised in the
2026-07-28 shmem-viability spike (see `../../docs/findings.md` and
`../../docs/phase2-topology-decision.md` RQ-2): can an ordinary QNX
**host** userspace process on `qnx-qhv` (NOT itself a `qvm` guest) create
or attach to a named shared-memory region via the QNX Hypervisor
Virtualization API (`hyp_shm.h` / `libhyp.a`), the way QNX's own vendor
docs say a host "may"?

## Result — RESOLVED YES, empirically, on the live host (2026-07-28)

`hyp_shm_attach_ext()` succeeded on the first live boot tried, with
**no** `vdev shmem` line anywhere in any `g2.conf` and **no** guest
involvement at all:

```
=== RQ-2 SPIKE: running hyp-shm-probe (host-only, no qvm/guest involved) ===
probe: hyp_shm_attach_ext rc=0 errno=2 (n/a)
probe: attached 'phase2-rq2-probe' idx=0 size=4096 data=4c194fb000
probe: wrote test pattern to shared region
probe: hyp_shm_poke rc=0 errno=2
probe: detached cleanly
=== hyp-shm-probe exit=0 ===
```

(curated log:
[../../logs/sample-boot/qhv-tcg-rq2-hyp-shm-host-probe.log](../../logs/sample-boot/qhv-tcg-rq2-hyp-shm-host-probe.log))

`errno=2` (ENOENT) alongside `rc=0` is expected noise, not a failure —
`hyp_shm_attach_ext`/`hyp_shm_poke` do not clear `errno` on success and
this program does not otherwise touch a file; `rc` is the authoritative
result.

This confirms the shared-memory-region registry the shmem vdev uses is a
**host-OS/kernel-level facility**, not something scoped to a specific
`qvm` VM instance — the host attached to (and, being first, created) a
named region entirely on its own. This is the load-bearing half of RQ-2's
"is shmem usable from `qnx-qhv`'s own process space, or is it guest<->guest
only by construction" question, and it resolves **usable**, not
guest-only.

## What this does NOT demonstrate

- **The guest-side half is untested.** No `vdev shmem` line was added to
  the guest's `g2.conf`, and no guest-side program using
  `qvm/guest_shm.h`'s raw-MMIO factory-page protocol was written or run.
  Whether a `qnx-guest` process can attach to the *same* named region
  (`phase2-rq2-probe`) the host created, and see the host's
  `"hyp-shm-host-ok"` test pattern, is the concrete next step — not
  attempted in this session (see `docs/findings.md`, 2026-07-28, for the
  honest time-box accounting).
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
make                      # -> hyp-shm-probe (aarch64le ELF, links -lhyp)
```

Build evidence (2026-07-28): `qcc -Vgcc_ntoaarch64le -std=gnu99 -Wall
-Wextra -Wformat=2` (zero warnings).

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

Host-side RQ-2: **RESOLVED, proven live.** Guest-side RQ-2 (the true
host<->guest round trip): **open, not attempted, not ruled out** — the
concrete next step if this stretch transport is picked back up.
