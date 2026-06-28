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

Build evidence (2026-06): both this client and `../qnx-server/server.c`
cross-compile clean with `qcc -Vgcc_ntoaarch64le -std=gnu99 -Wall -Wextra
-Wformat=2` (zero warnings) to `ELF 64-bit LSB ARM aarch64` with the QNX
interpreter `/usr/lib/ldqnx-64.so.2`.

## Run

```
qnx-host-client [iters] [device] [warmup]
# defaults: iters=100000  device=/dev/qhv/con1  warmup=1000
```

It writes a one-row CSV summary to `../../results/cloud/cloud-ipc-latest.csv`
(schema described in `../../results/cloud/header.csv`).

## Host<->guest wiring proposal (the load-bearing open item)

For the two ends to connect, the `qvm` `virtio-console` vdev needs a
**host-side endpoint**. The live `g2.conf` (in
`../../scripts/qhv/post_start.custom`) declares the guest-facing console
(`vdev virtio-console / loc 0x20000000 / intr gic:42`) but **no `hostdev`
mapping**, so the host has nothing to open.

The SDP 8.0 `vdev-virtio-console.so` usage confirms the missing directive
(extracted from the shipped `.so`):

```
hostdev [<|>]<pathname>
    Host device to use for input/output.
delayed <num>|forever
    Delay opening host device until first guest reference. ...
```

**Proposed minimal change** — add one `hostdev` line to the existing
virtio-console vdev (full proposed config in `g2.conf.proposed`):

```
vdev virtio-console
 loc 0x20000000
 intr gic:42
 hostdev /dev/qhv/con1      <-- ADDED: bind the host end
```

This is the **only** g2.conf change required. Both the `hostdev` keyword
and the `vdev:virtio-console` type are already on the Phase-1 allow-list
(`../../scripts/qhv/g2.conf.allow`), so no allow-list/gate change is needed.

**Gate evidence:** `g2.conf.proposed` PASSES the Phase-1 config gate:

```
$ sh scripts/qhv/validate-g2conf.sh ipc-test/qnx-host-client/g2.conf.proposed scripts/qhv/g2.conf.allow
CFG-GATE: PASS — all directives within locked-down allow-list (scripts/qhv/g2.conf.allow).
VALIDATOR_EXIT=0
```

## RUNTIME-SPIKE unknowns (deferred, not guessed)

The C99 source compiles against real QNX headers, but the following cannot
be settled from docs alone and are the **qvm/TCG console-wiring spike**:

1. **Host-side `hostdev` pathname.** `/dev/qhv/con1` above is a
   placeholder. The exact host path the vdev should bind — a real char
   device, a created node, or a pty pair — must be confirmed at runtime
   against what the `qvm` host actually exposes when the `hostdev`
   directive is present. Whatever it resolves to is what the client opens
   (pass it as `argv[2]`).

2. **Guest-side device node.** The guest endpoint (`../qnx-server`) opens
   `/dev/con1` by default; the actual node the guest sees for this
   virtio-console port must likewise be confirmed at runtime (pass as
   `argv[1]`).

3. **Console contention with the boot banner.** This same virtio-console
   port currently carries the guest boot banner. The spike must confirm
   whether a dedicated second console port is needed (a second
   `vdev virtio-console` with its own `hostdev`) so framed traffic does
   not collide with console text.

Until this spike runs under qvm/TCG, **no benchmark numbers exist** —
`../../results/cloud/` holds only the schema header, never fabricated
samples.
