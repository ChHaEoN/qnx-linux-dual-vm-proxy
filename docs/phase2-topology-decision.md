# ADR-002 — Phase-2 cloud-leg IPC topology

> **Status:** **Accepted** — Architect verdict (Option D) ratified by the
> project owner 2026-06-11. Downstream doc/stub changes in §4 are now in force.
> **Date:** 2026-06-11
> **Supersedes:** the implicit topology assumed in `ipc-test/README.md`,
> `docs/architecture.md` §"IPC path detail", and `docs/digital-twin-design.md`
> §2 — all of which still describe the falsified QNX↔Linux-over-`br0`/KVM design.
> **Decision owner:** Architect. **Inputs:** Phase-1 gate cycle, QHV pull-forward,
> and IFS-build findings (top three entries in `docs/findings.md`, 2026-06-10/11).

---

## 1. Context — what the QHV pivot changed

The original Phase-2 plan (still encoded in the stubs and several diagrams)
assumed the cloud leg was **two co-equal QEMU/KVM guests** — a QNX Safety VM and
a Linux Compute VM — on a Graviton host, doing IPC over a Linux bridge `br0` +
`tap-qnx`/`tap-linux` + virtio-net. Phase 1 falsified that on two independent
counts:

1. **No KVM on cloud.** AWS non-metal Graviton exposes no `/dev/kvm` (EL2 is not
   passed through by Nitro; proven on a t4g.small probe). Any
   hardware-accelerated partitioner — KVM *or* QHV — needs `*.metal` or real
   silicon. KVM-on-cloud is dead; KVM acceleration moves to Phase 3 (Orin).

2. **The as-built cloud leg is a QNX Type-1 hypervisor, not a Linux host.**
   The QHV pull-forward demonstrated `qvm` (the SDP 8.0 QHV host) booting a
   **single QNX guest** under `qemu-system-aarch64 ... -accel tcg`. There is no
   Linux guest. The host boots as `qnx-qhv` (machine `QEMU_virt`); the guest
   reaches `Startup complete` as `qnx-guest` on the synthetic
   `ARMv8_Foundation_Model` platform QHV fabricates. That synthetic platform
   boundary *is* the real partition boundary — this is the strongest hypervisor
   artefact the project has.

3. **The host network stack did not initialise.** The stock `start_guest` wires
   a virtio-net peer that depends on the host `io-sock` stack, which fails on
   this qemu-virt build (`network stack down` / `Address family not supported`).
   The demonstrated guest therefore ran **no-network**, driven by a hand-rolled
   `g2.conf` (`post_start.custom`) declaring only `pl011`, `virtio-console`, and
   `virtio-blk` vdevs. Any Phase-2 transport that depends on host `io-sock`
   (i.e. anything routed through `br0`/tap/host TCP) is presumed broken on this
   leg until proven otherwise.

**Net effect on Phase 2:** the entire `ipc-test/` premise (QNX TCP server +
Linux TCP client over `br0`) describes infrastructure that does not exist on the
cloud leg and partly cannot exist there without first fixing host `io-sock`.
This ADR decides what the cloud-leg IPC study actually *is*.

### As-built constraint summary (the decision must respect these)

| Constraint | Source | Consequence for Phase 2 |
|---|---|---|
| No `/dev/kvm` on cloud | findings 2026-06-11 | TCG only; no two-guest KVM topology on cloud |
| QHV host is QNX; one QNX guest built | findings 2026-06-11 | Linux-guest path is unproven, not built |
| Host `io-sock` down | `post_start.custom`, qhv/README | Host-routed TCP/bridge transports presumed dead |
| Guest vdevs today: pl011 / virtio-console / virtio-blk | `g2.conf` in `post_start.custom`; `vdev.manifest` | A host↔guest channel already exists via virtio-console |
| TCG is slow (minutes to boot, char-drop on console) | findings, qhv/README | Two guests under TCG is a real performance risk; interactive console control is unreliable |

---

## 2. Options

Each option is paired with an explicit **"does NOT demonstrate"** line, per the
honest-framing rule. This is a study-level digital twin, not a real hypervisor.

### Option A — QNX-host ↔ QNX-guest IPC across the qvm vdev boundary

One line: keep exactly what is built — `qvm` host + one QNX guest — and run the
IPC client/server across the **host↔guest partition boundary** using a vdev
channel (virtio-console today; a virtio-vsock or shared-memory vdev as a
stretch).

- **Cost:** low. The host and guest are both already QNX and already booting; a
  `virtio-console` vdev is already in the live `g2.conf`. Implementation is a
  console-framed echo on each side plus the existing build pipeline. No new
  guest OS, no `io-sock` fix required.
- **Buys:** exercises the **real hypervisor partition boundary** (`qvm` vdev
  mediation between EL2 host and EL1 guest) — the closest thing in the project
  to DRIVE OS's hypervisor-mediated inter-VM channel. It is also the only option
  that is *certain* to run on the as-built cloud leg.
- **Risk / fallback:** virtio-console is byte-stream, not message-framed and not
  latency-optimised; the latency number will be dominated by TCG emulation, not
  a meaningful transport cost. Fallback if a richer channel is wanted: add a
  `virtio-vsock` or shared-memory vdev (research spike RQ-2) — but virtio-console
  is the guaranteed floor.
- **Does NOT demonstrate:** the QNX-safety ↔ **Linux**-compute heterogeneity
  that is the load-bearing mirror of DRIVE OS's dual-OS partitioning. Both ends
  are QNX. It also does not demonstrate hardware-timed IPC (TCG only).

### Option B — QHV hosts BOTH a QNX safety guest AND a Linux compute guest

One line: build a second guest (aarch64 Linux) under the same `qvm` host and run
IPC **between the two guests** across an inter-VM channel — the most faithful
analogue to DRIVE OS's dual-VM Type-1 partition design.

- **Cost:** high and **unbounded until a research spike lands**. Three open
  unknowns, each a potential blocker: (1) can `mkqnximage`/`qvm` boot an aarch64
  **Linux** guest at all, and how is the guest image built outside the
  QNX-native `--type=qvm` flow? (2) what **inter-guest** channel exists when host
  `io-sock` is down — a shared-memory vdev, a virtio-vsock-style channel, or a
  back-to-back virtio-net between guests that does *not* route through the host
  stack? (3) TCG performance of **two** guests booting concurrently (Phase-1
  already saw minutes-to-boot for one).
- **Buys:** if it works, this is the single most credible DRIVE OS analogue the
  project can produce on the cloud leg — heterogeneous OS partitions on a real
  Type-1 hypervisor, exactly the cockpit/compute split. Highest narrative payoff.
- **Risk / fallback:** highest risk of the three; any of the three unknowns
  could be a hard wall (QHV may simply not ship/support a Linux guest config in
  SDP 8.0; the inter-guest channel may itself depend on `io-sock`). Fallback if
  blocked: drop to Option A for the cloud leg and carry the heterogeneity to
  Phase 3 (Option C's posture).
- **Does NOT demonstrate:** even if it boots, it does not demonstrate certified
  Type-1 isolation, ASIL-D, or hardware-timed IPC — it is TCG-emulated EL2. The
  isolation is *architecturally* real (qvm partitions) but its timing/coverage
  is not.

### Option C — Split the heterogeneity across the twins

One line: cloud leg does **QNX↔QNX over qvm** (Option A) as the *IPC-mechanism*
study; the QNX-safety ↔ Linux-compute **heterogeneous** IPC moves to **Phase 3
(Orin)**, where KVM actually works and L4T natively *is* the Linux compute side.

- **Cost:** low on the cloud leg (= Option A). Phase 3 already plans a QNX guest
  under KVM-on-L4T with L4T as the Compute host, so the heterogeneous client is
  "free" there — no second guest to build, L4T provides it natively.
- **Buys:** honesty. Each host demonstrates what it *can*: the cloud leg shows
  the hypervisor partition boundary and the IPC mechanism; Orin shows the
  heterogeneous QNX↔Linux path on real silicon with working KVM. It also sharpens
  the **twin diff**: the cloud and Orin legs are no longer running the identical
  IPC topology, so the diff becomes "mechanism vs. heterogeneity" rather than a
  pure host-only delta.
- **Risk / fallback:** the cloud leg no longer tells the dual-OS story on its
  own; the narrative leans on Phase 3 to complete it. If Phase 3 Orin slips, the
  heterogeneous claim is unproven anywhere. Fallback: pursue Option B as a Phase
  2.5 stretch once RQ-1/RQ-2 are answered.
- **Does NOT demonstrate (cloud leg):** the dual-OS partition story. It is a
  deliberate split, recorded as such — not a gap papered over.

### Option D (hybrid, recommended) — A now, B as a research-gated stretch

One line: **ship Option A as the committed Phase-2 cloud deliverable now**, and
hold Option B as an explicitly research-gated stretch (Phase 2.5) that only opens
if RQ-1 (QHV hosts a Linux guest) and RQ-3 (an inter-guest channel survives
`io-sock` being down) both come back affirmative — while Phase 3/Orin remains the
*committed* home of heterogeneous QNX↔Linux IPC (Option C's posture).

- **Cost:** low committed cost (= A); the B work is conditional and time-boxed
  behind a spike, so it cannot blow up the Phase-2 schedule.
- **Buys:** a guaranteed, runnable cloud deliverable (A) *plus* a credible upside
  path to the strongest analogue (B) *plus* an honest heterogeneity home (C/Orin)
  — without betting Phase 2 on any unproven QHV-hosts-Linux assumption.
- **Risk / fallback:** if the B spike is negative, nothing is lost — A already
  shipped and C/Orin already owns heterogeneity. The only cost is the spike
  itself.
- **Does NOT demonstrate:** until the B spike resolves positively, the cloud leg
  does not show heterogeneous OS partitions; that claim lives on Orin.

---

## 3. Decision

**Adopt Option D: Option A is the committed Phase-2 cloud-leg deliverable;
Option C's posture is adopted (heterogeneous QNX↔Linux IPC is committed to Phase
3/Orin); Option B is a research-gated Phase-2.5 stretch only.**

### 3.1 Recommended IPC transport for the committed (A) deliverable

**Primary transport: a host↔guest channel over the `qvm` `virtio-console` vdev
that is already in the live `g2.conf`** — i.e. the QNX *host* (`qnx-qhv`) runs
one end and the QNX *guest* (`qnx-guest`) runs the other, exchanging the
fixed-width framed echo over the console device that `qvm` mediates across the
EL2/EL1 partition boundary.

Why this transport, against the known constraints:

- **It survives host `io-sock` being down.** virtio-console is a `qvm` vdev
  mediated by the hypervisor; it does **not** route through the host TCP/IP
  stack, the bridge, or tap devices. Every transport that died in Phase 1
  (br0/tap/host TCP) depends on `io-sock`; this one does not. It is the one
  channel already *proven live* on this leg (the guest banner prints over it).
- **It is the partition boundary, not a network.** This is strictly closer to
  the DRIVE OS reference (hypervisor-mediated shared memory + mailbox) than the
  old `br0` virtio-net path was — the old path crossed a host Linux bridge; this
  one crosses the actual `qvm` vdev boundary.
- **It is already declared and allow-listed.** `vdev:virtio-console` is in
  `scripts/qhv/g2.conf.allow` and `scripts/qhv/vdev.manifest`; no config-surface
  change or new gate review is needed to use it.

**Stretch transport (within A, if the byte-stream framing proves too coarse): a
shared-memory vdev or a `virtio-vsock` channel between host and guest.** This is
gated behind RQ-2 and is *not* required for the committed deliverable —
virtio-console is the guaranteed floor.

**Explicitly rejected for the cloud leg:** any `br0`/tap/host-TCP transport
(depends on dead `io-sock`); any KVM-dependent topology (no `/dev/kvm` on cloud).

### 3.2 Why this verdict (rationale, not restatement)

The decision optimises for **a deliverable that is certain to run on the
as-built leg** while refusing to either (a) fake a Linux guest the project has
not built, or (b) bet Phase 2 on the unproven assumption that QHV hosts Linux.
Option A is the only option guaranteed to execute today; making it the committed
deliverable de-risks Phase 2 entirely. Heterogeneity is the project's
load-bearing DRIVE OS mirror, so it is not abandoned — it is *relocated* to the
one host where it is cheap and proven (Orin: KVM works, L4T *is* Linux). Option B
is genuinely the strongest analogue, so it is preserved as upside — but behind a
spike, so its unbounded risk cannot contaminate the committed schedule. This is
the honest-framing rule applied to scope: demonstrate what each host can
actually do, and say plainly where the dual-OS story does and does not live.

---

## 4. Consequences (downstream changes this decision forces)

> These are **proposed follow-ups for human ratification.** Per the Architect
> hard-rules, this ADR does not rewrite `CLAUDE.md` or the other docs — it lists
> the edits the decision forces so the human can ratify the decision first.

### 4.1 `ipc-test/` stub changes

- **`ipc-test/qnx-server/`** — repurpose from "QNX TCP listen on
  `192.168.100.10:5555`" to a **virtio-console endpoint on the QNX guest**
  (read/write the guest-side console device the `qvm` vdev exposes). The
  fixed-width frame format (8-byte seq + 8-byte timestamp + N-byte payload) and
  the echo semantics survive unchanged; only the transport (console fd, not a TCP
  socket) changes.
- **`ipc-test/linux-client/`** — on the **cloud leg this stub is removed/parked**:
  there is no Linux guest on the cloud leg. Two sub-options for the human to pick:
  (i) rename the cloud-side initiator to `qnx-host-client/` (the `qnx-qhv` host
  end of the console channel), keeping `linux-client/` reserved for Phase 3/Orin
  where it runs natively on L4T; or (ii) keep `linux-client/` as a Phase-3-tagged
  stub and add a new `qnx-host-client/` for the cloud leg. **Architect
  recommendation: (i)** — the cloud initiator is a QNX-host program, and
  `linux-client/` should be re-tagged `Phase 3` so its name stays truthful.
- **A new pair tag:** mark the cloud-leg pair `Phase 2 (cloud, QNX↔QNX over
  virtio-console)` and the Linux client `Phase 3 (Orin, QNX↔Linux over
  KVM/virtio-net)` so the two topologies are not conflated in the tree.

### 4.2 Doc updates required (architecture.md + digital-twin-design.md together,
so they do not drift)

- **`docs/architecture.md`** —
  - §"Cloud twin — hybrid build/runtime": the runtime-host diagram shows
    `qemu-system-aarch64 (KVM)`, `Bridge br0 + tap-qnx,tap-linux`, and two
    co-equal guests. Replace with the as-built QHV/TCG picture: `qvm` host +
    single QNX guest, console/blk vdevs, **no** br0/tap, **no** KVM (TCG), and a
    note that the Linux guest moved to Phase 3.
  - §"IPC path detail": the entire `br0 (192.168.100.1/24)` + tap diagram and the
    "six context boundaries plus two virtio rings" summary describe the dead
    topology. Replace with the host↔guest virtio-console-over-`qvm` path.
  - §"What this is NOT" table, "Inter-VM IPC" row for the cloud twin: change
    "virtio-net through host bridge" to "host↔guest over `qvm` virtio-console
    vdev (TCG-emulated EL2 partition boundary; not hardware-timed)".
  - DRIVE OS reference block can stay (it describes the real thing being proxied).

- **`docs/digital-twin-design.md`** —
  - §1 table: the `ipc-test/linux-client` row ("on the Linux guest in cloud
    twin") is now false for the cloud leg — mark it Phase-3/Orin only. The "QEMU
    command line" row's `-enable-kvm` invariant is false on cloud (TCG) — move it
    from the invariant set to the delta set, or annotate the cloud value as TCG.
  - §2 "What is deliberately not twinned": the claim "Cloud twin runs Linux
    Compute as a *second QEMU VM*" is falsified — rewrite to "cloud leg runs a
    single QNX guest under QHV; the Linux Compute side is twinned on Orin (L4T)
    only". This is the biggest prose change and is **load-bearing** for the twin
    diff framing.
  - §4 twin-diff methodology (deferred): note that the cloud and Orin legs no
    longer share an identical IPC topology, so the diff design must account for
    transport difference (console-over-qvm vs. virtio-net-over-KVM), not just
    host difference.

- **`ipc-test/README.md`** — rewrite "Topology" and "Layout": cloud leg is
  QNX-host ↔ QNX-guest over virtio-console; the vsock/ivshmem line moves from a
  "Phase 2.5 follow-up if curiosity warrants" to the **named RQ-2 stretch**; the
  Linux client is relocated to Phase 3.

- **`CLAUDE.md`** — the "Common across both twins" bullet ("IPC: virtio-net via
  host bridge `br0` + tap devices") and the Phase-1/Phase-2 sequence steps that
  reference `setup-bridge.sh` / `launch-linux-vm.sh` on the cloud runtime are now
  cloud-false. Phase plan needs: Phase 2 = QNX↔QNX-over-qvm-virtio-console (cloud);
  Phase 3 = adds heterogeneous QNX↔Linux on Orin. **Listed only — not edited here.**

### 4.3 Latency-benchmark implications

- The `ipc-test/README.md` benchmark table ("virtio-net via host bridge ~hundreds
  of µs to low ms") no longer describes the cloud transport. The cloud number is
  now **virtio-console over a TCG-emulated qvm boundary** — expect it to be
  dominated by **TCG emulation overhead**, not by a meaningful transport cost, so
  the cloud P50/P99 is a *mechanism-alive* sanity number, not a transport
  benchmark. State this explicitly (honest framing: the cloud latency number does
  NOT measure hypervisor IPC cost — it measures TCG emulation cost).
- The **real** transport-vs-transport and hardware-timed numbers come from Phase
  3 (Orin, KVM). The twin diff (Phase 4) must therefore compare *non-identical*
  IPC paths and say so, rather than presenting the delta as host-only.
- Time-base normalisation (`ClockCycles()` on QNX, `clock_gettime` on Linux) in
  `ipc-test/README.md` is now **single-OS on the cloud leg** (both ends QNX →
  both use `ClockCycles()`); the cross-clock-skew handling only re-enters at
  Phase 3 when the Linux end appears.

---

## 5. Open research questions (hand to the Research agent)

These gate the **Option B stretch** and resolve the **A stretch transport**.
Implementation can start the committed Option-A/virtio-console deliverable
**without** waiting on any of these.

- **RQ-1 (gates B):** Does SDP 8.0 `mkqnximage`/`qvm` support hosting an
  **aarch64 Linux** guest at all? If so, how is the Linux guest image produced
  (there is no `--type=qvm` for Linux), and what `g2.conf` shape does a Linux
  guest need (kernel `load`, dtb, virtio-blk rootfs)? *If negative, Option B is
  closed and heterogeneity stays on Orin permanently.*
- **RQ-2 (resolves A stretch transport):** What richer host↔guest channels does
  `qvm` expose besides virtio-console — a **shared-memory vdev**, a
  **virtio-vsock**-style vdev? Which are available in SDP 8.0 and declarable in
  `g2.conf` without depending on host `io-sock`? This decides whether the A
  deliverable can upgrade past byte-stream console framing.
- **RQ-3 (gates B):** When two guests run under one `qvm` host, what
  **inter-guest** channel exists with host `io-sock` **down** — a shared-memory
  vdev between guests, an inter-VM virtio-vsock, or a back-to-back virtio-net
  that `qvm` bridges in EL2 without touching the host stack? *If every inter-guest
  channel depends on `io-sock`, Option B is blocked even if RQ-1 is positive.*
- **RQ-4 (de-risks everything):** Can the host `io-sock` / network-stack
  init failure on this qemu-virt build be fixed (missing driver/package, wrong
  `io-sock` invocation, missing entropy precondition — cf. NF-5/T31)? A fix would
  *not* change this decision (the qvm vdev path is preferred regardless) but
  would re-open the host-routed transports as a comparison point and is needed
  anyway for any future Linux-guest networking.
- **RQ-5 (Phase-3 readiness):** Confirm KVM-on-L4T + QEMU(QNX) + native-L4T-client
  is buildable on Orin Nano (this is the committed home of heterogeneous IPC, so
  its feasibility should be confirmed before Phase 2 closes, not discovered in
  Phase 3).

---

## 6. Honest-framing ledger (per the project rule)

| This decision demonstrates | It does NOT demonstrate |
|---|---|
| IPC across a **real `qvm` Type-1 partition boundary** (EL2 host ↔ EL1 guest) | Certified Type-1 isolation, ASIL-D, or quantified freedom-from-interference |
| A transport that **survives the host `io-sock` failure** (qvm vdev, not host TCP) | A working host network stack — `io-sock` is still down (RQ-4) |
| A **runnable, de-risked** Phase-2 cloud deliverable | The QNX-safety ↔ **Linux**-compute heterogeneity on the cloud leg (relocated to Orin) |
| A latency number proving the IPC path is **wired and stable** | A meaningful transport-cost benchmark — the cloud number is TCG-emulation-bound, not hardware-timed |
| An honest scope split (mechanism on cloud, heterogeneity on Orin) | A single host that tells the whole DRIVE OS dual-VM story by itself |
