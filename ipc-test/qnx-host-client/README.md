# qnx-host-client — Phase 2 (cloud, QNX-host -> QNX-guest over qvm virtio-console)

The `qnx-qhv` HOST end of the host<->guest console IPC channel (ADR-002,
[../../docs/phase2-topology-decision.md](../../docs/phase2-topology-decision.md)).
It runs the framed echo initiator + RTT/percentile benchmark across the
`qvm` `virtio-console` vdev that crosses the EL2 host <-> EL1 guest
partition boundary. It does NOT route through host `io-sock` (not available
on this leg).

Honest framing: this is a study-level **mechanism-alive** proxy across a
**TCG-emulated** `qvm` boundary, not a transport benchmark. The reported
RTT is dominated by TCG emulation overhead, not a meaningful transport cost
— read P50/P99 as a mechanism-alive sanity number, nothing more.

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

## Host<->guest wiring (settled 2026-07-28)

`qvm`'s `virtio-console` vdev needs a **host-side endpoint**. The live
`g2.conf` (built by `../../scripts/qhv/post_start.custom`) declares:

```
vdev virtio-console
 loc 0x20000000
 intr gic:42
 hostdev /dev/ptyp0
```

- **`/dev/ptyp0`/`/dev/ttyp0` is a `devc-pty` master/slave pair**
  (`devc-pty` starts as part of the standard mkqnximage startup sequence; no
  extra package needed).
- `qvm` itself opens the **master**, `/dev/ptyp0` (that is what the
  `hostdev` directive names). The **host-side initiator
  (`qnx-host-client`) opens the paired SLAVE, `/dev/ttyp0`** — that is
  `DEFAULT_DEV` in `client.c`.
- The virtio-console vdev needs a `hostdev` backing it; the earlier
  `hostdev`-less config is superseded by the one above. What the bring-up
  printed with and without it is held locally (NC QDL v7 4.6(i)).
- `/dev/qhv/con1` (the earlier placeholder guess in `g2.conf.proposed`) is
  not used.

Both the `hostdev` keyword and `vdev:virtio-console` type were already on
the Phase-1 allow-list (`../../scripts/qhv/g2.conf.allow`); no gate change
was needed.

## Guest-side device node (settled 2026-07-28)

Generic board bring-up auto-attaches a console driver only to the *first*
console vdev (`pl011` -> `/dev/vcon1`); for the second one the guest starts
the `devc-virtio` driver itself. Per the `devc-virtio` usage doc (extracted
from the shipped SDP 8.0 help), the `location,irq` argument must match the
vdev's `loc`/`intr` from `g2.conf` exactly:

```
devc-virtio -E 0x20000000,42 &
```

and the guest end uses **`/dev/vcon2`**. `-E` selects raw mode —
`devc-virtio` defaults to *edited* ("cooked", line-buffered) mode, which is
wrong for a binary framed protocol (see next section). This is baked into
`../../scripts/qhv/guest-post_start.custom`, which starts `devc-virtio`
then `qnx-echo-server /dev/vcon2` automatically at guest boot. `DEFAULT_DEV`
in `server.c` is `/dev/vcon2` accordingly.

## Console contention with the boot banner (no change needed)

By inspection of the config: `pl011`'s `hostdev >-` is **unidirectional**
(the leading `>`), guest console *output* only — the host's keystrokes are
never forwarded to the guest over that path. The virtio-console vdev is a
second, independent port on its own MMIO location/IRQ.

## What the code does about the link, and why

All of this lives in `../common/console_io.h` and `client.c`:

1. **Raw mode on both ends.** Both `/dev/ttyp0` (a pty) and `/dev/vcon2`
   (an io-char `devc-virtio` device) default to line-buffered "cooked"
   mode, in which input is held until a newline byte appears. The wire frame
   is raw binary with no guaranteed `\n`, so both ends call `cio_set_raw()`
   (termios `cfmakeraw` + `tcsetattr`) right after `open()`, plus `-E` on the
   guest's `devc-virtio` invocation.
2. **Priming and draining.** `qnx-host-client` sends one throwaway "priming"
   frame and drains the fd until it goes quiet before starting the real
   warm-up/timed loop (`cio_drain_stray()` + the priming block in
   `client.c`). The client also does a defensive drain before every write
   and applies a bounded read timeout (`CLIENT_READ_TIMEOUT_DS`) so a
   stalled link is a diagnosable error, not a silent hang.
3. **Pacing.** A `usleep(20000)` gap between iterations is measured
   **outside** the RTT sample window.
4. **Sentinel-kick recovery.** A reserved-value kick-safe sentinel frame
   (`FRAME_SENTINEL_SEQ = UINT64_MAX` in `../common/frame.h`). On a read
   timeout, `sentinel_recover()` in `client.c` writes a **sentinel** frame
   rather than resending the real in-flight frame, so it carries no request
   semantics either end needs to track. `qnx-server` needs **zero** changes:
   it already echoes any frame verbatim regardless of `seq`, so a sentinel
   bounces back for free. The initiator then reads until it sees the real
   echo (`seq` match — recovered, alignment intact, but this iteration's
   timing is discarded as contaminated) or the sentinel's own bounce
   (discarded, keep waiting), bounded by `SENTINEL_MAX_ROUNDS` /
   `SENTINEL_READS_PER_ROUND` so an unrecoverable link still fails loudly
   instead of hanging forever. A leftover sentinel echo is swept up by the
   `cio_drain_stray()` call at the top of the next iteration. Recovered
   iterations are excluded from the timing statistics, so `samples` can be
   smaller than the requested count.

Why each of these exists — the link behaviour that motivated them, the
investigation, a resend-on-timeout mitigation that was tried and reverted,
and the evidence for the sentinel design — is held locally under NC QDL v7
4.6(i), with the curated logs `qhv-tcg-sentinel-recovery-*.log`. None of it
is a claim that the underlying `qvm`/TCG link behaviour was fixed; the
committed benchmark config (5 warm-up + 15 timed) is unchanged.

## Getting results off the image

`qnx-host-client` runs **inside the QNX host image's own filesystem** (a
raw disk under QEMU-TCG) — there is no shared filesystem back to this
Windows checkout on this leg (no virtiofs/9p, no network). Its own
`fopen("../../results/cloud/cloud-ipc-latest.csv", ...)` therefore resolves
to a nonsensical path inside the QNX image and fails harmlessly (handled
already — see `client.c`: it prints a note and the STDOUT summary still
stands). The STDOUT summary line **is** captured, verbatim, in the serial
log by `../../scripts/launch-qhv-tcg.ps1`. `../../scripts/qhv/extract-ipc-result.sh
<captured-log>` transcribes that already-printed summary into
`../../results/cloud/cloud-ipc-latest.csv` (schema: `header.csv`) —
it never invents a number. That CSV is held locally, not committed
(NC QDL v7 4.6(i); see `../../results/cloud/README.md`).

## Status

1. **Host-side `hostdev` pathname:** **`/dev/ptyp0`** (qvm's master); the
   client opens the slave, **`/dev/ttyp0`**.
2. **Guest-side device node:** **`/dev/vcon2`**, from explicitly starting
   `devc-virtio -E 0x20000000,42` at guest boot.
3. **Console contention with the boot banner:** none by design — `pl011`'s
   `hostdev >-` is output-only.
4. **Link behaviour under load and the sentinel recovery:** implemented as
   above; the investigation and its evidence are held locally. Bumping the
   committed benchmark config is left to a future session/Architect
   decision.
