# Future scope — Multi-SoC domain-controller extension (Phase 7)

> **Status:** design exploration. Frozen here so Phase 7 has a starting
> point when Phase 1–6 land. Not on the active roadmap; do not work on
> this until at least Phase 4 (twin diff) is delivered.

---

## Why this exists

Real Software Defined Vehicle (SDV) platforms are not single-SoC. A
typical modern E/E architecture pairs a **cockpit SoC** (Qualcomm
Snapdragon Cockpit family — SA8155P / SA8295P / SA8775P) for IVI,
cluster, and head-up display, with an **autonomous-driving SoC**
(NVIDIA DRIVE Orin / Thor) for ADAS, perception, and planning. The
two SoCs talk over automotive Ethernet (often TSN) or, on newer
platforms, PCIe.

A QNX/Linux dual-VM project that stays on a single SoC misses half
of the customer-facing surface area an AVOS / DRIVE OS SE actually
encounters. Phase 7 layers a **second SoC proxy** onto the existing
cloud twin so the project can exercise inter-SoC IPC, AUTOSAR
Adaptive / SOME/IP-SD framing, and the integration shape that real
OEM programmes have.

---

## Reference architecture (real hardware)

```
┌─────────────────────────┐     Ethernet TSN /     ┌──────────────────────────┐
│ Cockpit SoC: Snapdragon │ ◀── PCIe / SerDes ──▶  │ ADAS SoC: NVIDIA Orin    │
│   Cockpit (8295/8775)   │                        │   (DRIVE Thor next gen)  │
│ ─────────────────────── │                        │ ──────────────────────── │
│ • QNX Hypervisor (cmrcl)│                        │ • NVIDIA Hypervisor (T1) │
│ • Android Automotive OS │                        │ • QNX Safety partition   │
│ • QNX Cockpit Safety VM │                        │ • Linux Compute partition│
│ • Hexagon DSP (audio)   │                        │ • NVDLA / PVA / Ampere   │
└─────────────────────────┘                        └──────────────────────────┘
```

This is structurally what programmes like VW CARIAD E³ 2.0,
Stellantis STLA Brain, and Hyundai Pleos / ccOS look like.

---

## Phase 7 cloud-twin layout (proposed)

The existing cloud twin grows from a single host running two VMs to
a **single host running two VM clusters** representing two SoCs:

```
┌──────────────────────────────────────────────────────────────────────┐
│ AWS c7g.xlarge or c7g.2xlarge (more cores + RAM than Phase 1–6)      │
│                                                                      │
│  ┌────────────────────────┐      ┌──────────────────────────────┐    │
│  │ "Cockpit SoC" proxy    │      │ "ADAS SoC" proxy              │    │
│  │  (QC family, simulated)│      │  (NVIDIA family, Phase 1-6)   │    │
│  │ ┌────────────────────┐ │      │ ┌──────────────────────────┐ │    │
│  │ │ Android Automotive │ │      │ │ QNX Safety VM            │ │    │
│  │ │  OS VM (heavy)     │ │      │ │  (Phase 1-6 same IFS)    │ │    │
│  │ │   OR Linux IVI VM  │ │      │ └──────────────────────────┘ │    │
│  │ │  (lightweight)     │ │      │ ┌──────────────────────────┐ │    │
│  │ └────────────────────┘ │      │ │ Linux Compute VM         │ │    │
│  │ ┌────────────────────┐ │      │ │  (Phase 1-6 same image)  │ │    │
│  │ │ QNX Cockpit Safety │ │      │ └──────────────────────────┘ │    │
│  │ │ VM                 │ │      │                              │    │
│  │ └────────────────────┘ │      │                              │    │
│  └────────────┬───────────┘      └──────────┬───────────────────┘    │
│               │ tap-cockpit                  │ tap-adas              │
│               │                              │                       │
│               └────── br-intersoc ───────────┘                       │
│                  (virtio-net = Ethernet inter-SoC link proxy)         │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

The Phase 1–6 NVIDIA proxy stays unchanged on the right; the new
left cluster is the cockpit SoC proxy. The **`br-intersoc`** bridge
is the Phase 7 deliverable's load-bearing piece.

---

## QNX Hypervisor (QHV) availability — important correction

QHV 2.x is **bundled with QNX SDP 8.0** and the QNX Everywhere
non-commercial licence covers personal use of QHV (same NCEULA as the
rest of SDP). What is *not* available under Everywhere is the
proprietary Snapdragon BSP for QHV (that lives behind Qualcomm-QNX
commercial agreements).

**Implication for Phase 7's cockpit-proxy:** the QC cockpit side can
legitimately use QHV running on QEMU's `virt` aarch64 machine, hosting
an Android Automotive guest + a QNX Cockpit Safety guest underneath.
This is structurally closer to a real Snapdragon Cockpit software
stack than running both guests directly under KVM. It also gives the
project a much stronger BSP-engineering story (porting / configuring
QHV virt BSP, hypercall surface, guest isolation).

The trade-off is **nested virtualisation**: AWS Graviton hosts QEMU,
QEMU hosts QHV, QHV hosts the inner guests. KVM-on-arm64 nesting is
considered experimental on some kernels — Phase 7 needs to validate
the nesting path before committing to QHV-as-cockpit-HV. If nesting
turns out unstable, the fallback is KVM-on-host directly (simpler,
honest framing notes the QHV gap).

Phase 7 research items (added):

- [ ] Does QHV 2.x ship a `--type=qemu --arch=aarch64le` BSP comparable to `mkqnximage`'s? If not, what is the porting effort?
- [ ] Does KVM-on-Graviton support nested virt well enough to host QHV? (Single-host nested-KVM benchmark is the gate.)
- [ ] If nested QHV works: what is the inter-guest IPC latency *inside* QHV vs the inter-SoC virtio-net latency? (Useful comparison point — gives Phase 7 a "stacked latency budget" picture.)

---

## What the simulation can validate

| Concept | Validates? |
|---|---|
| Two co-resident VM clusters representing two SoCs | ✅ structurally correct |
| Virtio-net inter-SoC link as Ethernet proxy | ✅ shape; not RT/TSN guarantees |
| SOME/IP-SD service discovery between SoCs | ✅ runs end-to-end on Linux + QNX |
| AUTOSAR Adaptive (ara::com) frames | ✅ if you build a small adapter |
| DDS pub/sub (RTI / Eclipse Cyclone) | ✅ both sides can run a DDS stack |
| Boot-order dependency (cockpit waits for ADAS heartbeat) | ✅ orchestrate via launch scripts |
| Workload separation (IVI on cockpit, perception proxy on ADAS) | ✅ shape only |

## What the simulation cannot

| Concept | Why not |
|---|---|
| QNX Hypervisor on a real Snapdragon SoC | Qualcomm-QNX cockpit reference uses QHV, but the Snapdragon BSP for QHV is proprietary (commercial Qualcomm-QNX agreement); not obtainable via QNX Everywhere |
| Hexagon DSP | No QEMU model |
| NVDLA / PVA / Tensor / Ampere CUDA | No QEMU model |
| Real TSN (802.1AS / Qbv) | Linux has TSN scheduling but jitter ≠ real PHY |
| PCIe Gen5 inter-SoC link (DRIVE Thor) | No QEMU model with required latency profile |
| Hardware secure-boot chain across SoCs | No HW root of trust to chain |
| Real inter-SoC latency | Virtio-net inside one host = µs; real Ethernet = tens of µs to ms |

---

## New skills folders Phase 7 will add

- `skills/multi-soc-arch/` — domain controller / zonal architecture; E/E topology evolution from distributed ECUs → domain → zonal → centralised
- `skills/automotive-ethernet/` — TSN (802.1AS, Qbv, Qci), SOME/IP-SD, AUTOSAR Adaptive (ara::com), DDS
- `skills/qualcomm-cockpit/` — Snapdragon Cockpit family (8155/8295/8775); Android Automotive stack; Hexagon DSP — honest gap doc; **no Snapdragon-specific code shipped** (all simulation is generic ARMv8 in QEMU)

---

## AWS sizing

Phase 1–6 uses `c7g.large` (2 vCPU, 4 GB) which is enough for two VMs
with ~1 GB each. Phase 7 needs to run 4–5 VMs simultaneously
(cockpit-side IVI + cockpit-safety + ADAS-safety + ADAS-compute +
host overhead), so the runtime instance must grow:

| Instance | vCPU | RAM | $/hr (us-east-1, May 2026) | Verdict |
|---|---|---|---|---|
| `c7g.large` | 2 | 4 GB | $0.07 | Phase 1–6 only; insufficient for Phase 7 |
| `c7g.xlarge` | 4 | 8 GB | $0.15 | Workable for Phase 7 if Android replaced by lightweight Linux IVI |
| `c7g.2xlarge` | 8 | 16 GB | $0.29 | Comfortable Phase 7; required if running Android Automotive |

Phase 7 is a stretch goal precisely because the AWS bill goes up
~3–4× (still cheap in absolute terms — $30–60 for full Phase 7 run).

---

## Open empirical questions (to revisit when Phase 7 starts)

- [ ] Does Android Automotive OS aarch64 boot under QEMU/KVM on Graviton with virtio devices? (Cuttlefish targets x86_64; aarch64 path is less smooth.)
- [ ] Can SOME/IP-SD (vsomeip / CommonAPI) run on QNX SDP 8.0 without porting effort?
- [ ] What is `br-intersoc` realistic latency vs the existing intra-SoC `br0`? (The two should differ; Phase 7 wants to see that delta.)
- [ ] Is there a public open-source DRIVE OS-style "service discovery" stub usable as scaffolding, or do we write our own minimal SOME/IP server?

---

## Why Phase 7 and not Phase 0

Putting this in core scope from day one would triple the bring-up
surface area for Phase 1 (4 VMs to debug instead of 2, two virtio-net
bridges instead of one, two OS distributions instead of one). The
risk of getting stuck in bring-up before any IPC measurement
happens is high.

The Phase 1–6 narrative — single-SoC NVIDIA twin done well, with
honest framing — is already enough for the AVOS / DRIVE OS JD
target. Phase 7 is the upgrade path: when the user has time and
budget, it converts the project from "single-SoC twin" to
"E/E architecture twin," which is meaningfully more ambitious and a
cleaner story for a senior platform-integration role.
