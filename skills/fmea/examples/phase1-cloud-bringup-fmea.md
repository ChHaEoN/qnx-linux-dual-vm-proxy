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

---

# Phase-1 Gate Addendum (2026-06-11) — reconciliation with the as-built QHV/TCG boundary

> **Study-level only; not certification evidence.**
>
> This addendum does **not** rewrite §§1–6 above. The body of this worksheet
> remains the HARA/FMEA for the *originally-assumed* cloud item (QNX + Linux as
> two co-equal guests under QEMU/**KVM** on a Graviton c7g.large, talking
> virtio-net over `br0` + `tap-qnx`/`tap-linux`). That item has been
> **partially falsified** by what Phase 1 actually built. This section records
> the Item delta, marks which existing rows are now moot or deferred, and adds
> the NEW failure modes the as-built QHV/`qvm`-under-TCG boundary introduces.
> The S × E × C and S×O×D scores remain **illustrative** — a software-only,
> non-vehicle item with no nominal driver, no road exposure, and (now) no
> hardware acceleration at all. No ASIL claim is made.
>
> - **Date:** 2026-06-11
> - **Reviewer(s):** self-review (FuSa-Analysis Agent; pair-review with Cyber-Analysis at the Phase-1 gate)
> - **Evidence:** [`logs/sample-boot/qhv-tcg-host-and-guest-boot.log`](../../../logs/sample-boot/qhv-tcg-host-and-guest-boot.log); [`docs/findings.md`](../../../docs/findings.md) entries 2026-06-11 (QHV pull-forward) and 2026-06-10 (IFS build).

## A.1 Item re-definition delta (as-built vs. assumed)

| Dimension | Body of worksheet assumed | As-built (Phase-1 evidence) |
|---|---|---|
| Host platform | AWS Graviton c7g.large, Ubuntu host kernel | **Local Windows build host**, no AWS in this leg |
| Acceleration | QEMU/**KVM** on arm64 (`-enable-kvm`, `-cpu host`) | QEMU/**TCG** pure emulation (`-accel tcg`, `-cpu max`); non-metal Graviton exposes **no `/dev/kvm`** (EL2 not passed through by Nitro) — falsified |
| Partition mechanism | Host Linux kernel + KVM hosting two independent guests | **QHV `qvm` (Type-1 hypervisor)** on a QNX host (`qnx-qhv`, machine `QEMU_virt`) hosting **one** QNX guest (`qnx-guest`, synthetic machine `ARMv8_Foundation_Model`). The synthetic platform IS the partition boundary |
| Number/kind of guests | QNX guest **and** Linux guest, co-equal | **One QNX guest only.** No Linux/Compute guest booted in this leg |
| IPC / network data path | virtio-net front/back over `br0` + tap devices | **Inert.** Host io-sock stack failed (`network stack down: Bad file descriptor`, `Address family not supported`); `qvm` run **no-network**; guest `if_up: tries exhausted`, `no valid interfaces found` |
| Cross-VM transport SPOF | Linux bridge `br0` | Not instantiated this leg; the only realised boundary is the `qvm`/synthetic-platform one |

**Net effect on scope:** the cloud leg is no longer a *dual-VM cross-partition IPC* item; it is a **single-host-hypervisor-hosts-single-guest** item with no live data path. KVM, `br0`/tap, the Linux guest, and the entire virtio-net data path move out of the cloud-leg item. In exchange, the project gains its **first concrete partition-isolation boundary** (the `qvm` synthetic platform), which the original KVM framing never claimed.

## A.2 Existing FMEA / HE rows now moot or deferred for the cloud leg

"Moot (cloud leg)" = the cause cannot manifest in the as-built TCG/QHV config. "Deferred → Phase 3 / Phase 2" = the row is still valid but migrates to where its substrate actually exists. None are *deleted* — KVM rows are live again on Orin (Phase 3, real `/dev/kvm`); data-path rows are live again when IPC is implemented (Phase 2).

| Existing row | Disposition for cloud leg | Migrates to |
|---|---|---|
| **H1** KVM trap unbounded latency | Moot — no KVM | **Phase 3 (Orin)** — real KVM/EL2 |
| **H2** `-cpu host` Neoverse-V1 erratum | Moot — `-cpu max` TCG, no silicon erratum | **Phase 3 (Orin)** — A78AE silicon |
| **H3** host bridge/tap kernel bug | Moot — no `br0`/tap up | Phase 3 (Orin host net) / Phase 2 |
| **H4** shared **Linux** host kernel common-cause | Re-cast, not moot — see A.3 (DFA): the shared base is now the **`qnx-qhv` host**, not a Linux kernel | Recharacterised in A.3 / **Phase 3** |
| **Q2** wrong `cycles_per_sec` from KVM CNTFRQ | Moot as a *KVM* cause; **but** TCG time-base fidelity is a NEW concern (see NF-7) | Superseded by **NF-7**; Phase 3 for KVM form |
| **Q6** RT deadline miss from KVM trap | Moot — no KVM trap path | Superseded by **NF-7** (TCG masks timing); KVM form → **Phase 3** |
| **Q3 / Q4** virtio-net frontend (link DOWN / crash) | Deferred — net path inert this leg | **Phase 2** (IPC bring-up) / Phase 3 |
| **B1–B6** all `br0`/tap rows | Moot — bridge/taps not instantiated | **Phase 3** (Orin host net) / Phase 2 |
| **N1–N4** virtio-net data path | Deferred — no frames flow | **Phase 2** (IPC) / Phase 3 |
| **L1–L5** Linux guest rows | Moot — no Linux guest in this leg | **Phase 3** (L4T-as-host carries Linux) / whenever a Linux guest is added |
| **K1–K3** virtio-blk | Partially live — guest **does** boot from a raw virtio-blk disk (`disk-qemu`), and the 2026-06-10 split-VMDK finding is a real config-integrity hazard. K2 (wrong/cached IFS) and K1 (image corruption in transfer) **remain live** | Stay live; see also NF-8 build-config angle |
| **HE-02/03/04/15** cross-VM IPC liveness/staleness/integrity | Moot **this leg** (no IPC), but they are the reason Phase 2 exists | **Phase 2** IPC HARA |
| **HE-05** Linux guest panic | Moot — no Linux guest | Phase 3 |
| **HE-07/13** KVM scheduling / trap FFI | Moot — no KVM | **Phase 3**; FFI question re-opened against `qvm` in A.3 |
| **HE-08/11/14** `br0` QoS / MAC / cloud-init | Moot — no bridge, no Linux cloud-init | Phase 3 / Phase 2 |
| **HE-01 / Q1 / SG-01** boot-to-prompt FTTI | **Still live** — both host and guest must reach `Startup complete`; the log shows they do, but also shows degraded init (A.3, NF-5/NF-6) | Stays live (cloud leg) |
| **HE-10 / K2 / SG-10** wrong IFS at runtime | **Still live** — IFS identity matters regardless of host | Stays live |

**Count:** of the existing catalogue, **~20 rows are moot or deferred for the cloud leg** (all H1–H3, B1–B6, N1–N4, L1–L5, Q3/Q4); ~5 stay live (Q1, K1, K2, plus HE-01/HE-10 and SG-01/SG-10). Nothing is discarded — the moot rows are correct again on their proper substrate.

## A.3 NEW failure modes introduced by the QHV / `qvm` / TCG boundary

New scope, new Elements: **`qvm` (the Type-1 hypervisor process)**, its **config (`g2.conf`)**, its **vdev model**, the **synthetic `ARMv8_Foundation_Model` platform** it presents to the guest, the **`qnx-qhv` host's own resource managers**, and the **TCG execution substrate** itself. Same illustrative S×O×D 1–5 scale and flag rule (S ≥ 4 **OR** RPN ≥ 40) as §4. A notional-integration severity is assigned exactly as the body does — explicitly a study device for a non-vehicle item.

### A.3.1 QHV host + `qvm` hypervisor (new Element group)

| # | Function | Failure Mode | Effect | Cause (evidence) | S | O | D | RPN | Linked |
|---|---|---|---|---|---|---|---|---|---|
| **NF-1** | Parse `g2.conf` and build the guest | `qvm` config parse / validation fails or partially applies | Guest does not start, **or** starts with a silently different resource set than intended | Malformed/edited `g2.conf`; option not supported on this build. Evidenced indirectly: `[g2.conf:9] Failed to arm a resource manager: Function not implemented` — a config directive that did **not** take effect, yet boot proceeded | 4 | 3 | 2 | **24** | new SG-A1; HE-01 analogue |
| **NF-2** | Instantiate vdevs for the guest | vdev instantiation failure (a virtual device the guest expects is absent/half-built) | Guest boots into a degraded platform; missing device surfaces only when guest uses it. Evidenced: guest `vtnet0` never exists (`ifconfig: interface vtnet0 does not exist`) — the net vdev was intentionally dropped, but the *same failure surface* applies to any vdev | 4 | 3 | 3 | **36** | new SG-A2 |
| **NF-3** | Maintain guest within the synthetic-platform partition boundary | **Guest escapes / influences the host or another partition** (freedom-from-interference breach) | Loss of the project's only partition-isolation claim; a fault in `qnx-guest` reaches `qnx-qhv` or its siblings | `qvm`/`libhyp` defect; shared EL2 host (VHE `el2-host`); shared physical CPU under TCG. **Cannot be exercised on one host under TCG** — see A.4 | **5** | 1 | **5** | **25** | new SG-A3; DFA (A.4) |
| **NF-4** | `qnx-qhv` host resource managers arm and serve | Host resource manager fails to arm but host continues | Host advertises a service it cannot back; guest or host components silently lose a capability | **Direct evidence:** `Failed to arm a resource manager: Function not implemented`; also host `setfacl ... /dev/bpf: No such file`, `socketpair: Address family not supported`. The host came up **partly degraded** and proceeded | **4** | **4** | 3 | **48** | new SG-A4 |
| **NF-9** | Host io-sock / networking stack init | Host network stack does not initialise; any QHV feature depending on it is silently unavailable | No host-mediated guest networking; any future health/heartbeat/telemetry channel that assumes host net is dead on arrival | **Direct evidence:** host `if_up: network stack down: Bad file descriptor`, repeated `Address family not supported by protocol family`. Worked around by running `qvm` no-network — i.e. the failure was *avoided*, not *fixed* | 4 | 4 | 2 | **32** | new SG-A2 |

### A.3.2 Platform / integrity / determinism (new)

| # | Function | Failure Mode | Effect | Cause (evidence) | S | O | D | RPN | Linked |
|---|---|---|---|---|---|---|---|---|---|
| **NF-5** | Provide cryptographic-quality entropy to host **and** guest | **PRNG never seeded** on both host and guest | Any current/future integrity or freshness mechanism that relies on randomness (nonces, session keys, anti-replay counters, signed-counter freshness for SG-03/SG-04) is **born weak or deterministic** | **Direct evidence, BOTH instances:** host `random: Could not initialize entropy`, `Unable to access /dev/random`, `PRNG is not seeded`; guest inherits the same synthetic platform with no entropy source. Cross-cutting FuSa↔Cyber: this undermines integrity mechanisms FuSa-Design may later mandate (SG-04) | **5** | **5** | 4 | **100** | new SG-A5; SG-04 dependency; cyber-FuSa |
| **NF-6** | Bring all configured PEs (cores) online | **SMP processing elements not awake** — degraded core availability | Guest/host run on fewer cores than provisioned (`-smp 2`); any deadline budget or load assumption made against N cores is invalid; silent capacity loss | **Direct evidence:** `** CPU 0 PE is not awake`, `** CPU 1 PE is not awake` at host boot. Whether `qvm` then presents working vCPUs to the guest is **unverified** | **4** | **4** | 3 | **48** | new SG-A6; SG-07 dependency |
| **NF-7** | Execution substrate represents target timing faithfully enough to *find* timing faults | **TCG-only execution masks a whole class of timing / scheduling / acceleration failure modes** that real silicon (KVM on Orin, or metal) would expose | Boot "passing" under TCG gives **false confidence**: instruction timing, cache effects, vIRQ injection latency, real EL2 trap costs, scheduler jitter under load are all unrepresented. The original Q6/H1/N3 timing hazards are not *gone* — they are **invisible** here | TCG is a functional emulator, not a cycle/timing model; no `/dev/kvm` on this host forced TCG. **By construction**, a timing fault present on metal would not appear in this leg | **5** | **5** | **5** | **125** | new SG-A7; supersedes-visibility-of Q6/H1/N3 |
| **NF-8** | Boot the *intended* image with a complete package set | Host/guest built from an **incomplete or split artefact** boots wrong or not at all | Wrong-image / missing-startup hazard at build→runtime boundary, distinct from K2's "stale blob" | **Evidence (2026-06-10):** build failed for missing `target.qemuvirt` (`startup-qemu-virt` absent); and the **split VMDK** (169-byte descriptor vs. 150 MB extent) would have shipped a non-bootable disk. Config-management hazard on the new `qvm` packaging path | **5** | 3 | 2 | **30** | extends K2 / SG-10 |

### A.3.3 New illustrative Safety Goals raised by the addendum (statements only — `how` is FuSa-Design's)

| Safety Goal | Source NF | Statement (implementation-free) |
|---|---|---|
| **SG-A1** | NF-1 | A `qvm` configuration that fails validation shall not result in a guest that boots with a silently divergent resource set. |
| **SG-A2** | NF-2, NF-9 | Absence of a vdev or host service the guest depends on shall be detectable, not silently degraded. |
| **SG-A3** | NF-3 | A fault within the guest partition shall not propagate to the `qnx-qhv` host or to any sibling partition (freedom from interference). |
| **SG-A4** | NF-4 | A host resource manager that fails to arm shall not leave the host advertising a capability it cannot provide. |
| **SG-A5** | NF-5 | Any integrity/freshness mechanism shall not depend on entropy that the platform has not actually seeded. |
| **SG-A6** | NF-6 | Core/PE availability assumed by any timing or capacity argument shall be verified online, not assumed from configuration. |
| **SG-A7** | NF-7 | No timing, scheduling, or real-partition-isolation claim shall be asserted on the basis of TCG-only execution. |

### A.3.4 Addendum top-priority rows (S ≥ 4 OR RPN ≥ 40)

| Rank | ID | Description | RPN |
|---|---|---|---|
| 1 | NF-7 | TCG-only execution masks timing/scheduling/acceleration failure class | 125 |
| 2 | NF-5 | PRNG never seeded (host + guest) — integrity mechanisms born weak | 100 |
| 3 | NF-4 | Host resource manager fails to arm yet host proceeds | 48 |
| 4 | NF-6 | SMP PEs not awake — silent degraded core availability | 48 |
| 5 | NF-2 | vdev instantiation failure — guest degraded silently | 36 |
| 6 | NF-9 | Host net stack down — host-mediated channels dead on arrival | 32 |
| 7 | NF-8 | Incomplete / split build artefact boots wrong image | 30 |
| 8 | NF-3 | Guest escapes synthetic-platform partition (FFI) | 25 (S=5) |
| 9 | NF-1 | `qvm` config parse/validation failure | 24 |

## A.4 DFA angle — the `qvm` boundary as the project's only FFI claim

With KVM and the shared Linux host kernel out of the cloud leg, the `qvm`
synthetic-platform boundary becomes the project's **first and only concrete
claim to freedom from interference / partition isolation**. A Dependent
Failure Analysis at this boundary would have to examine the **shared
resources** the partition boundary sits on top of:

- **Shared EL2 host (VHE / `el2-host`):** host and guest share the same
  hypervisor-privilege context. A defect in `qvm`/`libhyp` is a **common-cause**
  that defeats the boundary for all partitions at once. (Recharacterises old H4:
  the shared base is no longer a Linux kernel — it is `qnx-qhv` + `qvm`.)
- **Shared physical CPU under TCG:** every partition's vCPU is multiplexed onto
  the same emulated PEs by one host scheduler — a cascading-failure and
  resource-exhaustion channel (and note NF-6: some PEs were not even awake).
- **Shared `qnx-qhv` resource managers:** NF-4 shows a host resource manager can
  fail to arm while the host proceeds; a guest depending on a host-served
  resource has a **dependent-failure** path through the host, not an isolated one.
- **Shared (absent) entropy source:** NF-5 — both instances share the same
  non-seeded PRNG; a single common-cause weakens integrity mechanisms on **both**
  sides simultaneously.

**What TCG-on-one-host CANNOT demonstrate about FFI (honest framing):**

- It cannot show **temporal** freedom from interference: TCG does not model the
  timing/contention by which one partition starves another (NF-7). A passing
  no-load boot says nothing about behaviour under load.
- It cannot show **spatial** isolation holds on real hardware: a TCG run does not
  exercise real MMU/SMMU stage-2 translation, real cache partitioning, or real
  EL2 trap costs. The synthetic `ARMv8_Foundation_Model` proves the *software*
  partition model exists, not that silicon enforces it.
- It cannot demonstrate **NF-3 (guest escape)** in either direction: a single
  guest under emulation with no adversarial load is not an isolation *test*, only
  an isolation *architecture demo*.

A real DFA for this boundary therefore **cannot be closed on the cloud leg** and
must be re-opened on Phase 3 (Orin, real EL2/KVM and, if QHV is built there, real
hardware-enforced stage-2 isolation). This is exactly the class of mitigation
that is **outside the project's current reach**: demonstrating hardware-enforced
partition isolation requires real silicon with EL2 / SMMU, which TCG-on-Windows
structurally cannot provide.

## A.5 Honest framing (per CLAUDE.md — every claim paired with what it does NOT show)

- The as-built leg **proves the QHV software architecture**: `qvm` parses a
  config, synthesises a virtual platform, and boots a *distinct* QNX guest
  (different machine banner) to `Startup complete`. It does **NOT** prove
  hardware timing, acceleration, or real partition isolation under load.
- Two distinct machine banners (`QEMU_virt` host vs. `ARMv8_Foundation_Model`
  guest) are **load-bearing evidence of a real partition boundary in software**.
  They are **NOT** evidence that a fault in one partition is contained from the
  other (NF-3 untested).
- The guest reaching `Startup complete` is a **functional** bring-up result. It
  is **NOT** a timing, FTTI, or availability result — both instances booted
  **degraded** (no entropy NF-5, PEs not awake NF-6, host net down NF-9, a
  resource manager unarmed NF-4), and TCG hides whatever timing faults exist
  (NF-7).
- KVM-specific and bridge/data-path failure modes being "moot" here means **only
  that this leg cannot exercise them** — they are not retired; they are live
  again on Phase 3 (KVM/Orin) and Phase 2 (IPC data path).

## A.6 Hand-off to FuSa-Design (open items raised by this addendum)

FuSa-Analysis finds; FuSa-Design decides the `how`. These are **decisions
FuSa-Design owns**, not proposed mitigations:

1. **OQ-A1 (SG-A4, NF-4 / NF-9):** A host resource manager / network stack came
   up unarmed yet boot proceeded. Does the Safety Concept require boot to **fail
   loud** on a missing host service, or is silent degradation acceptable for a
   dev twin? Define the policy and the FTTI for detecting it.
2. **OQ-A2 (SG-A5, NF-5):** PRNG is unseeded on host **and** guest. This directly
   undermines any integrity/freshness mechanism FuSa-Design may mandate for SG-03
   / SG-04. What is the entropy-source requirement, and is it a TSR that no
   integrity mechanism may be claimed until a seeded PRNG is demonstrated?
   (Cross-cutting with Cyber-Design.)
3. **OQ-A3 (SG-A7, NF-7):** TCG cannot expose timing/scheduling faults. Does the
   Safety Concept **forbid** any timing/FTTI/FFI claim on the cloud (TCG) leg and
   route all such claims to Phase 3 (Orin/KVM)? This supersedes OQ-5's cloud-leg
   half.
4. **OQ-A4 (SG-A3, NF-3 / DFA A.4):** The `qvm` synthetic boundary is now the only
   FFI claim. FuSa-Design must write the residual-risk argument for FFI **and**
   state explicitly that hardware-enforced isolation is **out of reach on the
   cloud leg** and deferred to Phase 3. (Replaces the cloud-leg portion of OQ-4 /
   H4; H4's shared-host common-cause is recharacterised onto `qnx-qhv`/`qvm`.)
5. **OQ-A5 (SG-A6, NF-6):** Cores reported "not awake". Does any Safety Concept
   capacity/deadline argument require an online PE-count check before the claim is
   asserted?
6. **OQ-A6 (SG-A1 / SG-A2, NF-1 / NF-2):** What is the required `qvm` config and
   vdev validation gate — i.e. must a config that fails validation (`Function not
   implemented`) **block** guest start rather than proceed with a divergent
   resource set?
7. **OQ-A7 (SG-10, NF-8 / K2):** Extends OQ-7. The build path now produces a
   **split VMDK** and depends on package completeness (`target.qemuvirt`). Is a
   build→runtime integrity + completeness check (checksum of *every* extent, plus
   a startup-binary-present check) a TSR on the `qvm` packaging path?

### Re-scoping note for FuSa-Verification

FuSa-Verification should treat **NF-3, NF-7, and the A.4 DFA** as items it
**cannot close on the cloud/TCG leg** and must carry forward to a Phase-3
(Orin, real EL2/KVM) fault-injection / FMEDA plan. Closing FFI or any timing
claim against TCG evidence would be invalid.
