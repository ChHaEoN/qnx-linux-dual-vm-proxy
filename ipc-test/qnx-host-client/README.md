# qnx-host-client — Phase 2 (cloud, QNX-host -> QNX-guest over qvm virtio-console)

The `qnx-qhv` HOST end of the host<->guest console IPC channel (ADR-002,
[../../docs/phase2-topology-decision.md](../../docs/phase2-topology-decision.md)).
It runs the framed echo initiator + RTT/percentile benchmark across the
`qvm` `virtio-console` vdev that crosses the EL2 host <-> EL1 guest
partition boundary. It does NOT route through host `io-sock` (down on this
leg).

Honest framing: this is a study-level **mechanism-alive** proxy across a
**TCG-emulated** `qvm` boundary, not a transport benchmark. The reported
RTT is dominated by TCG emulation overhead, not a meaningful transport cost
— read P50/P99 as proof the IPC path is wired and stable, nothing more.

## Build

```
# source the SDP 8.0 env first
qnxsdp-env.bat            # Windows
. qnxsdp-env.sh           # Linux/macOS
make                      # -> qnx-host-client (aarch64le ELF)
```

Build evidence (2026-07-28): both this client and `../qnx-server/server.c`
cross-compile clean with `qcc -Vgcc_ntoaarch64le -std=gnu99 -Wall -Wextra
-Wformat=2` (zero warnings) to `ELF 64-bit LSB ARM aarch64` with the QNX
interpreter `/usr/lib/ldqnx-64.so.2`.

## Run

```
qnx-host-client [iters] [device] [warmup]
# defaults: iters=100000  device=/dev/ttyp0  warmup=1000
```

It writes a one-row CSV summary to `../../results/cloud/cloud-ipc-latest.csv`
(schema in `../../results/cloud/header.csv`) **only if that relative path
happens to resolve** — see "Getting results off the image" below; the
STDOUT summary line is the reliable output.

## Host<->guest wiring — RESOLVED (2026-07-28 runtime spike)

`qvm`'s `virtio-console` vdev needs a **host-side endpoint**. The live
`g2.conf` (built by `../../scripts/qhv/post_start.custom`) declares:

```
vdev virtio-console
 loc 0x20000000
 intr gic:42
 hostdev /dev/ptyp0
```

Confirmed empirically, live, on the QHV host image:

- **`/dev/ptyp0`/`/dev/ttyp0` is a real, already-running `devc-pty` master/
  slave pair** on this image (`devc-pty` starts as part of the standard
  mkqnximage startup sequence; no extra package needed).
- `qvm` itself opens the **master**, `/dev/ptyp0` (that is what the
  `hostdev` directive names). The **host-side initiator
  (`qnx-host-client`) opens the paired SLAVE, `/dev/ttyp0`** — that is
  `DEFAULT_DEV` in `client.c` now.
- Adding the `hostdev` line makes the previously-observed
  `[g2.conf:9] Failed to arm a resource manager: Function not implemented`
  (present even in the *original*, `hostdev`-less config —
  `scripts/qhv/verify-bringup.sh`'s TSR-CFG-001 would BLOCK on it) go away
  entirely. The virtio-console vdev cannot arm without a hostdev backing it.
- `/dev/qhv/con1` (the earlier placeholder guess in `g2.conf.proposed`) does
  **not** exist on this image — confirmed via a live host shell
  (`ls: /dev/qhv: No such file or directory`).

Both the `hostdev` keyword and `vdev:virtio-console` type were already on
the Phase-1 allow-list (`../../scripts/qhv/g2.conf.allow`); no gate change
was needed.

## Guest-side device node — RESOLVED (2026-07-28 runtime spike)

The guest sees **no device node at all** for the virtio-console vdev until
it explicitly starts the `devc-virtio` driver itself — generic board
bring-up only auto-attaches a console driver to the *first* console vdev
(`pl011` -> `/dev/vcon1`); a second/extra console vdev is not auto-detected.

Per the `devc-virtio` usage doc (extracted from the shipped SDP 8.0 help),
the `location,irq` argument must match the vdev's `loc`/`intr` from
`g2.conf` exactly:

```
devc-virtio -E 0x20000000,42 &
```

which creates **`/dev/vcon2`** (confirmed via a diagnostic guest boot that
dumped `ls -la /dev` before/after). `-E` selects raw mode — `devc-virtio`
defaults to *edited* ("cooked", line-buffered) mode, which is wrong for a
binary framed protocol (see next section). This is baked into
`../../scripts/qhv/guest-post_start.custom`, which starts `devc-virtio`
then `qnx-echo-server /dev/vcon2` automatically at guest boot. `DEFAULT_DEV`
in `server.c` is `/dev/vcon2` accordingly.

## Console contention with the boot banner — RESOLVED (no change needed)

Confirmed by inspection, no runtime surprise: `pl011`'s `hostdev >-` is
**unidirectional** (the leading `>`), guest console *output* only — the
host's keystrokes are never forwarded to the guest over that path. The
virtio-console vdev is a second, independent port on its own MMIO
location/IRQ. There is no collision with the boot banner.

## Two more things the runtime spike found (not anticipated, but real)

Getting a byte-exact round trip required two more fixes beyond the wiring,
both now in `../common/console_io.h`:

1. **tty canonical-mode deadlock.** Both `/dev/ttyp0` (a pty) and
   `/dev/vcon2` (an io-char `devc-virtio` device) default to line-buffered
   "cooked" mode: input is held until a newline byte appears. The wire
   frame is raw binary with no guaranteed `\n`, so a frame can sit in the
   line discipline forever — this **hung** on the first spike attempt.
   Fix: `cio_set_raw()` (termios `cfmakeraw` + `tcsetattr`) on both ends
   right after `open()`, plus `-E` on the guest's `devc-virtio` invocation.
2. **A short one-time byte-injection artifact.** Even after fixing (1),
   the very first echoed frame arrived with a handful of extra bytes
   prepended (reproducible byte-for-byte across separate boots) that did
   **not** come from the server (whose received frame was byte-exact) —
   almost certainly `qvm` virtio-queue/kick negotiation overhead on the
   first exchange. Fix: `qnx-host-client` sends one throwaway "priming"
   frame and drains the fd until it goes quiet before starting the real
   warm-up/timed loop (`cio_drain_stray()` + the priming block in
   `client.c`). The client also does a defensive drain before every write
   and applies a bounded read timeout (`CLIENT_READ_TIMEOUT_DS`) so a
   stalled link is a diagnosable error, not a silent hang.
3. **A non-deterministic stall, UNRESOLVED but more precisely characterised
   (2026-07-28 follow-up root-cause session — see `docs/findings.md`).**
   Back-to-back exchanges with no gap between them hang within a few to a
   few hundred iterations (a real hang under `CLIENT_READ_TIMEOUT_DS`, not
   a framing bug — every frame up to the stall point was byte-exact). A
   `usleep(20000)` pacing gap between iterations (measured **outside** the
   RTT sample window) does **not** reliably prevent it: 24 diagnostic
   attempts with the *same* 20 ms gap stalled anywhere from iteration 6 to
   iteration 180, plus one full clean 200-sample run — a much wider and
   later range than earlier believed ("single-digit to several-dozen" was
   an artefact of a small early sample, not a real ceiling). Live `pidin`
   probing during multiple stalls shows `qvm`'s own threads never
   deadlocked (they keep cycling RECEIVE/RUNNING/REPLY normally), `qvm`'s
   documented `logger debug`/`verbose` facility (`use qvm`) produces zero
   extra output around a stall, and `use qvm`'s full option list has no
   vdev-level queue-depth/ring-size tunable — so process deadlock, missing
   debug visibility, and a config-level fix are all ruled out. A resend-
   on-timeout retry mitigation was implemented and tested, then **fully
   reverted** after failing identically in 8/8 attempts: the resend's write
   always unstuck a reply (never permanently lost, but a 25 s passive wait
   alone, tried separately below, does not recover it either), but that
   reply was always the *stale*, one-iteration-behind echo, leaving an
   orphaned duplicate that corrupts frame alignment one iteration later.
   That failure is itself the most informative result: it points to a
   missed host-side read-ready notification on data the guest already
   produced, recoverable only by new write/kick activity — not a permanent
   loss, not a slow guest, not a `qvm` deadlock, and not fixable by
   resending without a protocol-level, both-ends change (an explicit
   kick-safe sentinel frame, not attempted). This is most consistent with
   `qvm`/TCG virtio-queue kick/notify timing sensitivity (probabilistic per
   boot, roughly a constant ~1–2% per-iteration hazard), not something
   fixable from the client/server application side as it stands today. The
   pacing gap is left in as an occasionally-helpful mitigation, not a
   proven cure — see the honest account in `docs/findings.md` (both
   2026-07-28 entries).

## Getting results off the image

`qnx-host-client` runs **inside the QNX host image's own filesystem** (a
raw disk under QEMU-TCG) — there is no shared filesystem back to this
Windows checkout on this leg (no virtiofs/9p, no network). Its own
`fopen("../../results/cloud/cloud-ipc-latest.csv", ...)` therefore resolves
to a nonsensical path inside the QNX image and fails harmlessly (handled
already — see `client.c`: it prints a note and the STDOUT summary still
stands). The STDOUT summary line **is** captured, verbatim, in the serial
log by `../../scripts/launch-qhv-tcg.ps1`. `../../scripts/qhv/extract-ipc-result.sh
<captured-log>` transcribes that real, already-printed summary into
`../../results/cloud/cloud-ipc-latest.csv` (schema: `header.csv`) —
it never invents a number.

## Status

The three original RUNTIME-SPIKE unknowns are **resolved** by the live
experiments above; a fourth, unanticipated one (the non-deterministic
stall) was found and is **not** resolved, and was root-caused further
(still not fixed) in a 2026-07-28 follow-up session. See
`../../docs/findings.md` (both 2026-07-28 entries) for the measured
baseline and the full honest account, including a resend-retry mitigation
that was tried and rejected (reverted in full, never shipped) because it
failed instructively rather than helped.

1. ~~Host-side `hostdev` pathname.~~ **RESOLVED**: **`/dev/ptyp0`** (qvm's
   master); the client opens the slave, **`/dev/ttyp0`**.
2. ~~Guest-side device node.~~ **RESOLVED**: **`/dev/vcon2`**, created by
   explicitly starting `devc-virtio -E 0x20000000,42` at guest boot.
3. ~~Console contention with the boot banner.~~ **RESOLVED (non-issue)**:
   `pl011`'s `hostdev >-` is output-only.
4. **Non-deterministic per-boot stall — NOT RESOLVED, more precisely
   root-caused.** A real, reproducible hang after a boot-dependent number
   of back-to-back iterations (see "Two more things the runtime spike
   found" above), now known from 24 diagnostic attempts to range from
   iteration 6 to iteration 180 (not just "single-digit to dozens") with
   one clean 200-sample run also observed — consistent with a small,
   roughly constant ~1–2% per-iteration hazard rather than a fixed
   threshold. Live `pidin` probing rules out a `qvm` process deadlock;
   `qvm`'s own debug/verbose logging (`use qvm`) produces no extra
   visibility; `use qvm`'s option list has no relevant config knob; and a
   resend-on-timeout mitigation reliably (8/8) produces a *stale* echo
   plus a corrupting orphaned duplicate, which is itself strong evidence
   for a missed host-side read-ready notification on data the guest
   already produced (not permanent loss, not a `qvm` hang) — recoverable
   only by new write activity, not by waiting, and not safely exploitable
   without a protocol-level change to both ends (not attempted). 5
   warm-up + 15 timed (20 round trips total, 15 measured samples) remains
   the largest configuration that has reproducibly completed cleanly
   across repeated attempts; larger counts are a real risk of an
   incomplete run, not a guaranteed-longer measurement.
