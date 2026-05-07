> **Study-level only; not certification evidence.**
>
> This worksheet is a Phase 1 study artefact for the qnx-linux-dual-vm-proxy
> Digital Twin project. It is modelled on ISO 26262 Part 3 (Concept Phase —
> Item Definition, HARA, ASIL determination, Safety Goals) and Part 9
> (FMEA / DFA practice). It produces no safety case, no FSC, no TSC, and
> makes **no ASIL claim** about the deployed system. The S × E × C scoring
> below is illustrative — applied to a software-only proxy that has no
> nominal vehicle item, no nominal driver, and no road exposure — and is
> kept only because doing the exercise on a non-vehicle item is the
> learning point.

---

# Phase 1 — Cloud-Twin Bring-Up: HARA + Design FMEA

- **Phase under analysis:** Phase 1 — Cloud twin bring-up (QNX SDP 8.0 + Linux aarch64 on AWS Graviton QEMU/KVM)
- **Type:** ISO 26262 Part 3 HARA + Part 9 D-FMEA, study-level
- **Date:** 2026-05-07
- **Reviewer(s):** self-review (FuSa-Analysis Agent; pair-review with Cyber-Analysis at Phase-1 gate)
- **Reference docs:** [`docs/architecture.md`](../../../docs/architecture.md), [`docs/bsp-selection.md`](../../../docs/bsp-selection.md), [`docs/orin-port.md`](../../../docs/orin-port.md)
- **Out of scope:** Hardware twin (Phase 3); IPC application logic and benchmarks (Phase 2); Orin / DRIVE-class SoC failures.

---

## 1. Item Definition

### 1.1 Item

The **Phase 1 Cloud-Twin Bring-Up Item** is the running pair of QEMU
guests on a single AWS Graviton (c7g.large) host, brought up to the
point where each guest has booted to a usable shell and reached its
peer over the host bridge. The item is the **bring-up**, not steady-state
operation — IPC application latency is Phase 2's HARA item.

### 1.2 Boundary

**Inside the item (Phase 1 cloud twin Elements):**

| Element | Layer | Role |
|---|---|---|
| QNX guest | Guest OS (Safety proxy stand-in) | aarch64 IFS produced by `mkqnximage --type=qemu --arch=aarch64le` |
| Linux guest | Guest OS (Compute proxy stand-in) | Ubuntu 22.04 cloudimg, aarch64, cloud-init seed |
| QEMU process — QNX | Host userspace | `qemu-system-aarch64 -M virt,gic-version=3 -cpu host -enable-kvm` for VM0 |
| QEMU process — Linux | Host userspace | Same QEMU shape for VM1 |
| Host bridge `br0` | Host kernel networking | Linux bridge, 192.168.100.1/24 |
| `tap-qnx`, `tap-linux` | Host kernel networking | tap devices owned by QEMU processes, attached to `br0` |
| virtio-net front/back | Guest driver + host vhost/QEMU backend | Network IPC transport (path under test) |
| virtio-blk front/back | Guest driver + QEMU backend | Boot disk for Linux (`disk-qemu.vmdk`-class for QNX) |
| `setup-bridge.sh` | Host orchestration | Creates `br0`, `tap-qnx`, `tap-linux`; assigns host IP |
| `launch-qnx-vm.sh`, `launch-linux-vm.sh` | Host orchestration | Spawns QEMU with deterministic args |

**Trusted base (outside the item, assumed correct):**

- AWS Nitro / Graviton3 hardware
- Ubuntu 22.04 host kernel and KVM-on-arm64 module set
- AWS networking up to the EC2 instance ENI
- Linux host cgroups, scheduler (CFS), filesystem

**External interfaces:**

| Interface | Direction | Purpose |
|---|---|---|
| SSH (host ↔ operator) | bidirectional | Shell, log capture, script invocation |
| AWS ENI ↔ EC2 host | bidirectional | apt updates, IFS scp from build host |
| Build host (t3.medium) → Runtime host | one-way | scp `output/ifs.bin`, `disk-qemu.vmdk` |
| QEMU monitor / serial console | host → guest | Debug, log capture |

### 1.3 Modes of operation (Phase 1 only)

| Mode | Trigger | Successful exit |
|---|---|---|
| M0 — Cold host | EC2 instance fresh, no bridge | Bridge + taps provisioned |
| M1 — Bridge-up, no guests | `setup-bridge.sh` returns 0 | `ip a` shows `br0` UP, taps DOWN (no QEMU yet) |
| M2 — QNX boot | `launch-qnx-vm.sh` started | QNX prompt; `pidin sysinfo` runs |
| M3 — Linux boot | `launch-linux-vm.sh` started | Linux login prompt; cloud-init OK |
| M4 — Both up, peers reachable | Both guests booted | Each guest pings the other across `br0` |
| M5 — Teardown | `scripts/ec2/teardown.sh` | QEMU processes gone; taps removed; bridge removed; instance stopped |

### 1.4 Operational design domain (proxy)

This is a **bench / portfolio / development** workload running on a
non-vehicle host. No real-world vehicle, road, or driver. The HARA
below scores hazards as if a notional integrator had taken this
configuration and embedded it in a vehicle path — a fiction that lets
us practise S/E/C scoring against a recognisable Item rather than
pretending the cloud twin is itself in a vehicle.

---

## 2. HARA — Hazardous Events Table

**Scoring keys (ISO 26262-3 reference, study-level):**

- **S** — Severity: S0 = no injuries; S1 = light/moderate; S2 = severe survivable; S3 = life-threatening / fatal.
- **E** — Exposure: E0 = incredible; E1 = very low (<1 % operating time); E2 = low; E3 = medium; E4 = high (>10 %).
- **C** — Controllability: C0 = controllable in general; C1 = simply controllable (>99 % of drivers); C2 = normally controllable; C3 = difficult / uncontrollable.
- **ASIL** = Part 3 Table 4 lookup of (S, E, C); blanks below are QM.

**Notional integration assumption used for scoring:** the cloud twin's
behaviour is mapped onto a hypothetical vehicle integration where the
QNX guest carries Safety-relevant signals and the Linux guest carries
Compute-derived signals (perception, planning hints). This is a study
device only — see the honest-framing note above.

| ID | Operational Situation | Hazardous Event (Item-level) | S | E | C | ASIL | Notes |
|---|---|---|---|---|---|---|---|
| HE-01 | Vehicle start-up; mode M2 (QNX boot) | QNX guest fails to reach prompt within FTTI; Safety partition unavailable at start of drive | S2 | E4 | C2 | **B** | Boot-time observability is the only Phase-1 detection surface |
| HE-02 | Steady-state driving; M4 active | Loss of IPC liveness (peer unreachable) silently; Safety partition cannot publish/consume cross-VM signals | S3 | E3 | C3 | **D** | Cross-VM bridge is single point of failure for *all* IPC; loss is hazardous and hard to detect from inside QNX guest alone |
| HE-03 | Steady-state; M4 | IPC delivers messages with latency > FTTI but does not signal staleness (silent timing fault) | S3 | E3 | C3 | **D** | "On-time wrong" — older payload accepted as fresh; arguably worse than loss |
| HE-04 | Steady-state; M4 | virtio-net delivers a corrupted frame that passes IP/UDP checksum (fault below the checksum) | S2 | E2 | C3 | **C** | Single-bit flip + checksum-collision class; very low E but high C |
| HE-05 | Steady-state; M4 | Linux guest panic / kernel crash; Compute partition unavailable mid-drive | S2 | E3 | C2 | **B** | Loss-of-Compute hazard, but Safety partition may still assert safe state |
| HE-06 | Steady-state; M4 | QNX guest panic / kernel crash; Safety partition unavailable mid-drive | S3 | E3 | C3 | **D** | Loss-of-Safety; FTTI exceeded immediately |
| HE-07 | Steady-state; M4 | Host kernel CFS starves QEMU(QNX) thread, missing real-time deadlines (priority inversion) | S2 | E4 | C2 | **C** | Inherent to KVM-on-CFS; explicitly out-of-scope to fix in Phase 1 |
| HE-08 | Steady-state; M4 | Bridge `br0` saturated by Linux-guest workload; QNX traffic dropped (no QoS) | S2 | E2 | C2 | **A** | Noisy-neighbour on the IPC path |
| HE-09 | Steady-state; M4 | virtio-blk on Linux reports write errors silently; cloud-init / log writes lost | S1 | E2 | C2 | **A** | Loss of forensic / detection signal rather than direct hazard |
| HE-10 | Bring-up M0→M2 | Wrong IFS loaded (build/runtime SHA mismatch); QNX boots a stale or unrelated image | S3 | E1 | C3 | **B** | Configuration-mgmt hazard; very low E because of explicit checksum step but C3 if it slips through |
| HE-11 | Steady-state; M4 | MAC address collision between guests after script change; one guest silently shadows the other on `br0` | S2 | E1 | C3 | **A** | Determinism hazard from script regression |
| HE-12 | M5 teardown | Teardown leaks QEMU process; next launch sees stale taps, lock files, listening sockets | S0 | E4 | C0 | **QM** | Operational nuisance only; included for completeness |
| HE-13 | Steady-state; M4 | KVM trap-and-emulate slow path (e.g., GICv3 vIRQ inject) introduces unbounded latency on Safety guest | S3 | E2 | C3 | **C** | Hypervisor freedom-from-interference question; surfaced honestly because Phase 1 baseline exposes it |
| HE-14 | M3 → M4 | Linux guest cloud-init fetches network metadata that overwrites static `192.168.100.0/24` plan; bridge addressing diverges | S1 | E3 | C2 | **A** | Configuration drift hazard from cloud-init defaults |
| HE-15 | Steady-state; M4 | virtio-net front-end driver in QNX crashes / hangs; QNX kernel survives but Safety partition is islanded | S3 | E2 | C3 | **C** | Sub-element failure that does not crash the guest but does sever the IPC channel |

---

## 3. Safety Goals (one per ASIL ≥ A hazard)

> SG-x are **what** must hold; the **how** belongs to FuSa-Design (TSC,
> safety mechanisms). Safety Goals here are deliberately implementation-free.

| Safety Goal | Source HE | ASIL | Statement |
|---|---|---|---|
| **SG-01** | HE-01 | B | The QNX (Safety) partition shall reach an operational state within a defined boot-FTTI from system start, or the integrator shall be informed that Safety services are unavailable. |
| **SG-02** | HE-02, HE-15 | D | Loss of cross-VM IPC liveness shall be detected within the IPC-FTTI and announced to both partitions. |
| **SG-03** | HE-03 | D | Cross-VM IPC payloads shall not be consumed as fresh after their freshness window has expired. |
| **SG-04** | HE-04 | C | Cross-VM IPC payloads shall be protected against undetected single-bit corruption end-to-end (i.e., above the virtio-net layer). |
| **SG-05** | HE-05 | B | Loss of the Compute partition shall not cause the Safety partition to lose its operational state or its detection capability. |
| **SG-06** | HE-06 | D | Loss of the Safety partition shall be detectable within FTTI by an external supervisor (Compute partition or higher integrator). |
| **SG-07** | HE-07, HE-13 | C | Cross-VM IPC scheduling latency on the Safety partition shall be bounded, or the partition shall detect a missed deadline within FTTI. |
| **SG-08** | HE-08 | A | Cross-VM IPC bandwidth available to the Safety partition shall not be reducible below a defined floor by Compute-partition traffic alone. |
| **SG-09** | HE-09 | A | Loss of the Linux storage path shall not silently disable detection or logging of any other Safety Goal violation. |
| **SG-10** | HE-10 | B | The IFS executed at runtime shall be cryptographically bound to the IFS produced and approved on the build host. |
| **SG-11** | HE-11 | A | Each guest's L2 identity on the bridge shall be unique and stable across re-launches. |
| **SG-14** | HE-14 | A | The Phase-1 IPC subnet plan shall not be silently overridden by guest auto-configuration. |

(HE-12 is QM and produces no Safety Goal.)

---

## 4. Failure Mode Catalogue (Design FMEA)

D-FMEA scoring uses the local 1–5 scale from `skills/fmea/template.md`
(S = Severity at the integrator level; O = likelihood of the cause
manifesting in Phase-1 day-to-day use on AWS; D = how likely the
existing Phase-1 instrumentation catches it pre-release). RPN = S×O×D;
flag any row with **S ≥ 4 OR RPN ≥ 40** for FuSa-Design attention.

### 4.1 QNX guest

| # | Function | Failure Mode | Effect | Cause | S | O | D | RPN | Linked HE / SG |
|---|---|---|---|---|---|---|---|---|---|
| Q1 | Boot to prompt | Hang in IPL / kernel init | M2 never reached | aarch64 IFS feature mismatch with KVM-on-Neoverse-V1; missing virtio-mmio vs virtio-pci default (F5 open) | 5 | 3 | 2 | 30 | HE-01 / SG-01 |
| Q2 | Boot to prompt | Boots but `pidin sysinfo` reports wrong cycles_per_sec | Time-base wrong; any later FTTI scoring invalid | KVM CNTFRQ pass-through mismatch | 4 | 2 | 3 | 24 | HE-03 / SG-03 |
| Q3 | virtio-net frontend | Driver attaches but link stays DOWN | QNX islanded from `br0` | Wrong virtio transport (mmio vs pci); MAC mis-config | 5 | 3 | 2 | 30 | HE-02, HE-15 / SG-02 |
| Q4 | virtio-net frontend | Driver crashes after N frames | Channel severed mid-run | Frontend defect or guest-side resource exhaustion | 5 | 2 | 3 | 30 | HE-15 / SG-02 |
| Q5 | Kernel | Panic / fatal trap | M2 → no QNX | Unhandled instruction class on Neoverse-V1; KVM emulation gap | 5 | 1 | 2 | 10 | HE-06 / SG-06 |
| Q6 | Real-time scheduler | Thread misses deadline due to KVM trap | "On-time wrong" payload published | Hypervisor trap path not bounded | 5 | 4 | 5 | **100** | HE-07, HE-13 / SG-07 |
| Q7 | virtio-blk frontend (if used) | Read returns stale page | Wrong code/data executed | Cache coherency assumption between QEMU page cache and guest | 5 | 1 | 4 | 20 | HE-10 / SG-10 |

### 4.2 Linux guest

| # | Function | Failure Mode | Effect | Cause | S | O | D | RPN |
|---|---|---|---|---|---|---|---|---|
| L1 | Boot via cloud-init | cloud-init networking overwrites planned static IP | Bridge addressing diverges; Phase-1 plan invalid | Cloudimg default DHCP fallback | 3 | 4 | 2 | 24 |
| L2 | Boot via cloud-init | First-boot user-data not delivered (NoCloud seed mis-built) | No login, no automation | seed.iso build script defect | 3 | 3 | 1 | 9 |
| L3 | Linux kernel | OOM-kills the IPC client | Compute side stops talking; HE-05 | Insufficient guest RAM allocation | 4 | 2 | 2 | 16 |
| L4 | Linux kernel | Soft-lockup on virtio-net IRQ | Bridge stays up but Linux peer silent | virtio-net backend bug; queue stall | 4 | 2 | 3 | 24 |
| L5 | virtio-blk | Write errors not surfaced to userspace | Logs and benchmark CSVs lost; HE-09 | QEMU `-drive` cache mode mis-set; backing-file ENOSPC | 3 | 3 | 4 | 36 |

### 4.3 Host bridge `br0` + tap devices

| # | Function | Failure Mode | Effect | Cause | S | O | D | RPN |
|---|---|---|---|---|---|---|---|---|
| B1 | Provide L2 broadcast domain to both VMs | `br0` not created on cold host | M1 unreachable; both VMs islanded | `setup-bridge.sh` race with `systemd-networkd` | 5 | 3 | 1 | 15 |
| B2 | Hold tap-qnx UP while QEMU(QNX) runs | tap-qnx flaps when QEMU restarts under same name | Brief but undetected loss of liveness | tap left dangling from previous launch | 5 | 4 | 4 | **80** |
| B3 | Forward L2 between taps | Bridge STP timer puts new tap into LISTENING for 30 s | Cross-VM ping fails for 30 s after launch | STP enabled by default | 4 | 3 | 2 | 24 |
| B4 | Frame integrity | Bridge corrupts frames on overload | HE-04 corruption | Host kernel skb bug under packet flood | 5 | 1 | 5 | 25 |
| B5 | Isolation | Bridge promiscuously shares broadcast traffic across guests | Cyber-FuSa interaction hazard (info leak between partitions) | Bridge is single L2 domain by design | 4 | 5 | 4 | **80** |
| B6 | MAC stability | Both guests come up with same MAC after script regression | HE-11 collision | Static MACs not pinned in launch scripts | 4 | 2 | 3 | 24 |

### 4.4 virtio-net path (front-end + backend together)

| # | Function | Failure Mode | Effect | Cause | S | O | D | RPN |
|---|---|---|---|---|---|---|---|---|
| N1 | Reliable frame delivery | Silent frame drop under load | HE-02 / HE-03 mix | Backend ring full; no flow control | 5 | 3 | 4 | **60** |
| N2 | Throughput | Throughput collapse with vhost-net disabled | HE-08 floor breached | Host kernel built without vhost-net | 4 | 2 | 2 | 16 |
| N3 | Latency bound | Tail latency spikes from KVM IRQ injection | HE-07 / HE-13 | GICv3 vIRQ trap path | 4 | 4 | 4 | **64** |
| N4 | Payload integrity | Single-bit corruption survives TCP/UDP checksum | HE-04 | Hardware bit flip + checksum collision | 5 | 1 | 5 | 25 |

### 4.5 virtio-blk path

| # | Function | Failure Mode | Effect | Cause | S | O | D | RPN |
|---|---|---|---|---|---|---|---|---|
| K1 | Boot media integrity | Disk image corruption between build and runtime | HE-10 | scp interrupted; no checksum verification | 5 | 2 | 1 | 10 |
| K2 | Boot media identity | Wrong IFS loaded (cached old blob) | HE-10 | Operator forgets to re-scp after rebuild | 5 | 4 | 3 | **60** |
| K3 | Disk write durability | Writes acknowledged but not persisted on host crash | HE-09 | QEMU `cache=writeback` default | 3 | 2 | 4 | 24 |

### 4.6 KVM-on-Graviton host kernel (trusted base — failure-mode catalogue, not designed-against)

These are listed because honesty requires it; they are explicitly
**not in scope** for Phase-1 mitigation work — the host kernel is part
of the trusted base. They are the right candidates for **Dependent
Failure Analysis** at the Phase 1 → Phase 2 boundary.

| # | Function | Failure Mode | Effect | Cause | S | O | D | RPN |
|---|---|---|---|---|---|---|---|---|
| H1 | KVM trap emulation | Unbounded trap latency on GICv3 vIRQ injection | HE-13 — Safety guest deadline miss | Host CFS scheduling QEMU vCPU thread alongside other host workload | 5 | 5 | 5 | **125** |
| H2 | KVM CPU model pass-through | `-cpu host` exposes Neoverse-V1 erratum that QNX kernel does not mask | Q5 panic class | CPU erratum + missing kernel workaround | 5 | 2 | 4 | 40 |
| H3 | Host networking stack | Bridge / tap kernel-side bug under packet storm | B4 | skb path defect | 5 | 1 | 5 | 25 |
| H4 | Common host | Single host kernel hosts both guests — cascading failure | Loss of *both* partitions simultaneously | Host kernel oops, OOM, security update reboot | 5 | 2 | 4 | 40 |

H4 is the single most important DFA item for the cloud twin: there
is **no freedom-from-interference argument** between the two partitions
because they share a host kernel. The DRIVE OS comparison doc must
say so; no Phase-1 mitigation is possible by definition.

### 4.7 Top-priority rows (S ≥ 4 OR RPN ≥ 40), sorted by RPN

| Rank | ID | Description | RPN |
|---|---|---|---|
| 1 | H1 | KVM trap unbounded latency to Safety guest | 125 |
| 2 | Q6 | Real-time deadline miss from KVM trap | 100 |
| 3 | B2 | Stale tap from previous launch flaps undetected | 80 |
| 4 | B5 | Bridge promiscuous L2 shares broadcast across partitions (cyber-FuSa) | 80 |
| 5 | N3 | Tail-latency spikes from KVM IRQ injection | 64 |
| 6 | N1 | Silent virtio-net frame drop under load | 60 |
| 7 | K2 | Wrong/cached IFS loaded after rebuild | 60 |
| 8 | H2 | Neoverse-V1 erratum surfaces as QNX panic | 40 |
| 9 | H4 | Shared-host common-cause failure of both VMs | 40 |
| 10 | L5 | virtio-blk write errors not surfaced | 36 |
| 11 | Q1 | QNX hang in IPL / kernel init | 30 (S=5) |
| 12 | Q3 | virtio-net link DOWN after attach | 30 (S=5) |
| 13 | Q4 | virtio-net frontend crashes after N frames | 30 (S=5) |
| 14 | B4 | Bridge corrupts frames on overload | 25 (S=5) |
| 15 | N4 | Single-bit corruption survives checksum | 25 (S=5) |
| 16 | Q2 | Wrong cycles_per_sec invalidates time base | 24 (S=4) |
| 17 | B3 | STP 30 s LISTENING window blocks ping | 24 (S=4) |
| 18 | B6 | MAC collision after script regression | 24 (S=4) |
| 19 | L4 | virtio-net soft-lockup in Linux | 24 (S=4) |
| 20 | K3 | Writeback cache loses writes on host crash | 24 |

---

## 5. Open questions handed to FuSa-Design

These are explicit asks for the FuSa-Design Agent (Safety Concept,
TSC, safety mechanism selection). Each names the SG and FMEA rows it
must address. **Do not treat the questions as answers — they are
decisions FuSa-Design owns.**

1. **OQ-1 (SG-01, Q1, Q3):** What is the boot-FTTI for the QNX partition in Phase 1? Without an FTTI number, "fails to reach prompt within FTTI" is unmeasurable. Phase 1 has a **measured boot time** as Phase-1 deliverable — once that exists, FuSa-Design fixes the FTTI threshold.
2. **OQ-2 (SG-02, SG-03, N1, B2):** What is the cross-VM IPC liveness FTTI, and what mechanism announces loss to both partitions? Phase 1 has no heartbeat — adding it is Phase 2 implementation work; the **requirement** for it is Phase 1 FuSa-Design output.
3. **OQ-3 (SG-04, N4, B4):** virtio-net + IP/UDP checksums are **not end-to-end integrity** at the IPC payload level. What payload integrity layer (CRC, CMAC, signed counter) does the Safety Concept require above virtio-net?
4. **OQ-4 (SG-06, H4, Q5):** With a shared host kernel, no freedom-from-interference between the two guests is achievable on the cloud twin. FuSa-Design must explicitly write the residual-risk argument: either accept it (cloud twin is dev only) or define an external supervisor outside the host.
5. **OQ-5 (SG-07, Q6, H1, N3):** Hard-real-time bounds are not provided by KVM-on-CFS. Does the Phase-1 Safety Concept (a) require a deadline-miss detector inside the QNX guest, (b) drop the FTTI claim entirely on the cloud twin, or (c) constrain the cloud twin to non-real-time work?
6. **OQ-6 (SG-08, B5, N2):** Bridge `br0` provides no QoS between guests and no L2 partitioning. Is a Safety Concept that depends on bandwidth floors achievable on the cloud twin without changing transport?
7. **OQ-7 (SG-10, K1, K2):** What is the integrity binding from build-host IFS to runtime-host IFS? `sha256sum` already exists for the Orin transfer — is the same step **required** on the cloud twin transfer?
8. **OQ-8 (SG-11, B6):** MAC pinning is currently script convention. Is a config-time check (refuse to launch on collision) a TSR?
9. **OQ-9 (SG-14, L1):** Should cloudimg cloud-init networking be disabled outright, or should the seed.iso enforce the static plan?
10. **OQ-10 (HE-13, H1):** Hypervisor freedom-from-interference is a cross-cutting question. Is it deferred to the Phase-4 DRIVE OS comparison doc, or does it need a TSC entry now to make later comparisons traceable?

### Hand-off to Cyber-Analysis (interaction analysis candidates)

These failure modes are **also** plausible threats; FuSa-Analysis flags
them so Cyber-Analysis (TARA) and Cyber-Design can decide whether the
threat path warrants a security control whose **side effect** would
also satisfy a Safety Goal:

- **B5 — bridge promiscuous L2:** an attacker on either guest sees the other's traffic. STRIDE: Information Disclosure; safety side: integrity of cross-partition signalling.
- **K2 / SG-10 — wrong IFS at runtime:** STRIDE: Tampering; safety side: SG-10 integrity goal.
- **H4 — shared host kernel:** any host-kernel CVE compromises both partitions; STRIDE: Elevation of Privilege; safety side: SG-06 loss-of-Safety detectability.
- **B6 / SG-11 — MAC collision:** STRIDE: Spoofing; safety side: identity/determinism of the IPC channel.
- **L1 / SG-14 — cloud-init network override:** STRIDE: Tampering at config time; safety side: deterministic addressing.

These five are the recommended agenda for the Phase 1 cyber-FuSa
pair-review at the gate.

---

## 6. Items deliberately not analysed in this worksheet

- **Phase 2 IPC application logic** — message framing, ordering, application-level retries, etc. These get their own HARA at the Phase 2 boundary.
- **Hardware twin (Orin Nano)** — same Items will need re-scoring under L4T-as-host and a real Tegra-class CPU; that is the Phase 3 FuSa-Analysis task.
- **DRIVE OS comparison** — Phase 4 work; not a HARA but a gap analysis.
- **Build-host (t3.medium) supply chain** — partially overlaps with Cyber-Analysis (SBOM, NCEULA, signed artefacts); FuSa-Analysis touches it only via SG-10.
