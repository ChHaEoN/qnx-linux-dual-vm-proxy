# Phase 1 — Cloud Twin TARA (starting-point)

> **Study-level only; not 21434 evidence. TARA here is illustrative,
> not the work-product a real programme would audit.**

Owner: Cyber-Analysis Agent. Scope: Phase 1 cloud-twin bring-up
(QNX SDP 8.0 aarch64 IFS + Ubuntu 22.04 cloudimg under QEMU/KVM
on AWS Graviton, with virtio-net IPC over `br0` + `tap-qnx` +
`tap-linux`, and the x86_64 build host that produces the IFS).
Hardware twin (Orin) is **not** in scope yet — that is Phase 3.

This document follows the ISO/SAE 21434 §15 TARA structure:
**Item Definition → Asset list → Cybersec Properties (CIA + AAA)
→ Threat Scenarios → Damage Scenarios → Attack Path Analysis +
Feasibility (5-factor) → Risk per threat → Open questions for
Cyber-Design.** Mitigations are **deliberately not proposed here**
— that is Cyber-Design's deliverable.

---

## 1. Item Definition

### 1.1 Item under analysis

The Phase 1 *Item* is the **cloud-twin dual-VM bring-up
configuration**: the minimum integrated set of components needed
to demonstrate that a QNX guest and a Linux guest can co-exist
on a single Graviton runtime host and reach each other over a
host bridge. No application-level IPC traffic exists yet
(Phase 2). Phase 1's Item is therefore mostly a *posture* item:
the TCB and attack surfaces that the Phase 2 IPC workload will
inherit.

### 1.2 Boundary

**In scope:**

- QNX guest aarch64 IFS (boot image produced by `mkqnximage --type=qemu --arch=aarch64le`)
- Linux guest (Ubuntu 22.04 cloudimg, aarch64) — kernel + cloud-init + sshd
- Host runtime: Ubuntu 22.04 on c7g.large, Linux bridge `br0`,
  `tap-qnx`, `tap-linux`, `qemu-system-aarch64` processes
- virtio-net guest/host data path (and virtio-blk for cloudimg
  rootfs, but not for QNX which boots IFS-resident)
- IFS build pipeline on the cloud-twin x86_64 build host
  (t3.medium): SDP 8.0 install tree, `mkqnximage` invocation,
  output staging, `scp` transport to runtime host, NCEULA
  hygiene (no binaries committed)
- SSH key handling between dev workstation → build host →
  runtime host

**Trusted base (excluded as attack surface, included as TCB):**

- KVM-on-Graviton host kernel
- AWS Graviton hardware itself (no fuse/RoT analysis)

**Out of scope (per security-model.md §1):**

- AWS account-level controls (IAM, VPC ACLs)
- Physical security
- DRIVE OS production posture
- Any CAN / ethernet / wireless surface (none in design)
- Hardware twin (Orin Nano) — Phase 3

### 1.3 Trust boundaries (Phase 1 cloud twin)

```
                                  AWS account/IAM (out of scope)
                                          │
   Dev workstation (Macbook)──ssh────►Build host (t3.medium x86_64)
       │                                  │
       │                                  │ mkqnximage → output/ifs.bin
       │                                  │
       │                                  ▼
       └────────────────ssh──────────►Runtime host (c7g.large arm64, KVM)
                                          │
                                  ┌───────┴───────┐
                                  │  Host kernel  │ ◄── TCB
                                  │  + bridge br0 │
                                  └───┬───────┬───┘
                                  tap-qnx tap-linux
                                      │       │
                              ┌───────▼─┐  ┌──▼──────────┐
                              │ QNX VM  │  │ Linux VM    │
                              │ (IFS)   │  │ (cloudimg)  │
                              └─────────┘  └─────────────┘
                                  ▲             ▲
                                  └─trust bdry──┘  (peer guests; NOT mutually trusted)
```

Trust boundaries crossed in Phase 1:
1. Dev workstation → build host (SSH)
2. Build host → runtime host (SCP of IFS)
3. Runtime host kernel ↔ each guest (KVM/virtio)
4. Guest ↔ Guest (`br0`)
5. Each guest ↔ host bridge (tap interface)

---

## 2. Asset list (with cybersec properties)

ISO/SAE 21434 cybersec properties: **C** Confidentiality, **I** Integrity,
**A** Availability, **Au** Authenticity, **Az** Authorisation,
**NR** Non-repudiation. "—" means the property is not load-bearing
for this asset in Phase 1.

| ID | Asset | Owner / Location | C | I | A | Au | Az | NR |
|----|-------|------------------|---|---|---|----|----|----|
| A1 | QNX IFS binary `output/ifs.bin` | Build host filesystem; transits SCP; runtime host filesystem | M (NCEULA — not a secret but redistribution-controlled) | **H** (boot integrity = Safety guest integrity) | M | **H** | M | L |
| A2 | Ubuntu cloudimg (qcow2) on runtime host | Runtime host filesystem | L | **H** | M | **H** | M | L |
| A3 | QNX guest runtime memory + CPU state | KVM-managed; per-guest | M | **H** | **H** | M | M | L |
| A4 | Linux guest runtime memory + CPU state | KVM-managed; per-guest | M | **H** | M | M | M | L |
| A5 | virtio-net frames in flight on `br0` (Phase 1: ARP, DHCP, sshd noise; Phase 2: IPC payload) | Host kernel net stack | L (Phase 1) → M (Phase 2) | **H** | M | **H** | M | L |
| A6 | Host bridge `br0` configuration (MAC fwding, fdb, port list) | Host kernel | L | **H** | **H** | — | M | L |
| A7 | SSH keys — dev workstation private + build/runtime authorized_keys | Dev workstation; runtime+build hosts | **H** | **H** | M | **H** | **H** | M |
| A8 | QNX SDP 8.0 install tree on build host (`qnx800/`) | Build host filesystem | M (NCEULA — restricted distribution) | **H** | M | **H** | M | L |
| A9 | Build scripts + repo source (`scripts/`, `configs/`) | Git, all hosts | L | **H** | M | M | M | M |
| A10 | KVM/QEMU process boundary on runtime host | Host kernel | M | **H** | **H** | — | **H** | L |

Notes:
- A1's "M" confidentiality reflects the NCEULA: the IFS is not a
  business secret but its redistribution is contractually limited.
  Treating it as M raises the bar for `scp` over untrusted paths.
- A3/A4 have higher availability rating for QNX than Linux because
  the QNX guest is the *Safety proxy* in the framing, even though
  no real safety claim exists. Loss of QNX availability is a
  cyber-FuSa interaction candidate.

---

## 3. Threat Scenarios

Numbered T-IDs are reused in §4 (damage), §5 (attack paths), and
§6 (risk). STRIDE category in brackets. **[CFI]** flag = candidate
for cyber-FuSa interaction analysis (i.e., realisation could
plausibly cause a hazard the FuSa-Analysis pair-review would
recognise).

### QNX Safety guest (A1, A3)

- **T1 [S][CFI]** Attacker on `br0` spoofs `linux-client` peer
  identity and sends crafted frames to `qnx-server`'s expected
  socket (Phase 1: TCP sshd / cloud-init noise; Phase 2:
  application IPC).
- **T2 [T][CFI]** Replay of previously-observed frames from the
  bridge (latent in Phase 1; live once Phase 2 IPC is up).
- **T3 [I]** Eavesdrop on QNX guest's network traffic via
  promiscuous capture on `br0`.
- **T4 [D][CFI]** Co-resident Linux guest (or local host
  process) saturates `tap-qnx` with frames, starving QNX's
  virtio-net ring and stalling boot or Phase 2 listener.
- **T5 [E][CFI]** Guest→host escape via virtio-net (or QEMU
  device-model) vulnerability, giving attacker host-kernel
  privilege from within the QNX guest.

### Linux Compute guest (A2, A4)

- **T6 [S][CFI]** Rogue local process on the Linux guest binds
  to the port `linux-client` expects to talk to, returning
  forged responses (relevant once Phase 2 client/server exists).
- **T7 [T]** Tampered or substituted Ubuntu cloudimg
  (supply-chain at fetch time) provisions a backdoored guest
  kernel.
- **T8 [I]** Cleartext IPC payload disclosed via host
  `tcpdump br0`.
- **T9 [D]** Bridge-side flood degrades Linux guest
  responsiveness to dev-driver SSH, blocking observability.
- **T10 [E][CFI]** Linux guest kernel CVE → KVM escape →
  runtime-host compromise.

### Host bridge `br0` (A5, A6)

- **T11 [S][CFI]** A guest spoofs the *peer* guest's MAC
  address on the bridge, intercepting frames intended for the
  other VM.
- **T12 [T][CFI]** Attacker with `CAP_NET_ADMIN` on the
  runtime host silently reconfigures the bridge (adds a
  mirror port, changes forwarding rules).
- **T13 [I]** Promiscuous capture by anyone with root on the
  runtime host (tcpdump/tshark/`bpftrace`).
- **T14 [D][CFI]** Broadcast / ARP storm across `br0`
  degrades both guests simultaneously (common-cause loss of
  inter-VM IPC = pattern recognised in DFA / FuSa).
- **T15 [E][CFI]** Linux bridge / netfilter vulnerability
  allows pivot from bridge L2 path into host kernel.

### IFS build pipeline (A1, A7, A8, A9)

- **T16 [S]** Stolen SSH private key from dev workstation
  authenticates as the developer to the build host.
- **T17 [T][CFI]** Tampered build inputs (`mkqnximage` config,
  startup script, kernel args in repo) produce a malicious-by-design
  IFS that the runtime host boots trustingly.
- **T18 [R]** Accidental commit of QNX SDK fragments / IFS
  binary into git (NCEULA breach; legal/operational impact).
- **T19 [I]** `scp` of IFS leaks the binary to an
  unintended recipient (NCEULA-restricted distribution).
- **T20 [D]** Build host CPU starvation by runaway process
  blocks IFS production (delivery delay only).
- **T21 [E][CFI]** Build host fully compromised → all future
  IFS images are silently backdoored → both twins boot
  attacker-controlled QNX.

---

## 4. Damage Scenarios

Per ISO/SAE 21434 the impact dimensions are **Safety (S),
Financial (F), Operational (O), Privacy (P).** This is a
study/portfolio project so most ratings are low; what matters
is the *shape* of the analysis.

| Threat | S (Safety) | F (Financial) | O (Operational) | P (Privacy) | Notes |
|--------|------------|----------------|------------------|-------------|-------|
| T1 | M (CFI; in DRIVE OS analogue, mis-routed Safety command = hazard) | L | M (Phase 2 IPC corruption) | L | |
| T2 | M (CFI: re-armed action) | L | M | L | |
| T3 | L | L | L | M (if dev SSH or NCEULA blob traverses bridge) | |
| T4 | M (CFI: loss of Safety guest availability) | L | H (Phase 1 boot blocked; Phase 2 listener stalls) | L | |
| T5 | H (CFI: host pwn = both VMs) | M (re-provision cost) | H | M | Most-severe outcome in scope. |
| T6 | M (CFI in Phase 2) | L | M | L | |
| T7 | H (CFI: backdoored guest kernel) | M | H | M | |
| T8 | L | L | L | M | |
| T9 | L | L | M (loss of observability) | L | |
| T10 | H (CFI: host pwn) | M | H | M | |
| T11 | M (CFI) | L | M | L | |
| T12 | M (CFI) | L | M | L | |
| T13 | L | L | L | M | |
| T14 | M (CFI: common-cause IPC loss) | L | M (both guests degrade) | L | |
| T15 | H (CFI) | M | H | M | |
| T16 | M | M (account compromise) | M | M | Pivot to T17/T21. |
| T17 | H (CFI: corrupted Safety guest) | M | H | L | |
| T18 | L | M (legal: NCEULA breach) | M (repo policy violation) | L | Reputational, not safety. |
| T19 | L | M (NCEULA) | L | L | |
| T20 | L | L | M (delivery delay only) | L | |
| T21 | H (CFI: every downstream IFS backdoored) | H | H | M | Worst F/O in scope. |

---

## 5. Attack Path Analysis + Attack Feasibility

ISO/SAE 21434 attack-feasibility uses the 5-factor scheme.
Each factor is rated **L (low effort/easy for attacker),
M (moderate), H (high effort)**. Lower scores ⇒ higher
feasibility. Aggregate **Feasibility = High / Medium / Low**
follows the 21434 convention (predominantly L → High
feasibility; predominantly H → Low feasibility).

Scope assumption for "attacker": a co-resident process on the
runtime host with shell access (the realistic Phase 1 lab
threat model), unless the threat is specifically about an
external attacker (T16, T18, T19) or supply chain (T7, T17).

| Threat | Attack Path | ET (Elapsed Time) | SE (Specialist Expertise) | KoT (Knowledge of Target) | WoO (Window of Opportunity) | Eq (Equipment) | Feasibility |
|--------|-------------|-------------------|----------------------------|----------------------------|------------------------------|----------------|-------------|
| T1 | Local proc on host or guest → craft frame to QNX MAC/IP → inject via raw socket on `br0` | L | L | L | L (continuous) | L | **High** |
| T2 | tcpdump `br0` to capture → `tcpreplay` back | L | L | L | L | L | **High** |
| T3 | `tcpdump -i br0` | L | L | L | L | L | **High** |
| T4 | Local proc on Linux guest spams traffic to QNX MAC | L | L | L | L | L | **High** |
| T5 | Acquire / weaponise virtio-net or QEMU CVE → exploit from QNX guest | H | H | M | M | M | **Low** |
| T6 | Local proc binds expected port before `linux-client` starts | L | L | M (need port#) | M | L | **High** |
| T7 | MITM cloudimg fetch or compromise mirror | M | M | M | L (boot time) | M | **Medium** |
| T8 | `tcpdump br0` | L | L | L | L | L | **High** |
| T9 | Bridge flood from local proc | L | L | L | L | L | **High** |
| T10 | Acquire/weaponise Linux/KVM CVE chain | H | H | M | M | M | **Low** |
| T11 | `ip link set address` inside guest, then send | L | L | M | L | L | **High** |
| T12 | `ip link`/`bridge` commands as host root | L | L | L | L | L | **High** (assumes host root already) |
| T13 | `tcpdump -i br0` as host root | L | L | L | L | L | **High** |
| T14 | Userspace ARP flood from a guest | L | L | L | L | L | **High** |
| T15 | Acquire/weaponise Linux bridging CVE | H | H | H | M | M | **Low** |
| T16 | Steal SSH key from dev workstation (phishing, malware, lost laptop) | M | M | M | M | L | **Medium** |
| T17 | Push tampered config to repo or insert via PR | M | M | M | M | L | **Medium** |
| T18 | Developer mistypes `git add`; `.gitignore` miss | L | L | L | L | L | **High** (single-developer self-review = weak control) |
| T19 | Wrong scp destination, accidental S3 upload | L | L | L | L | L | **High** |
| T20 | Runaway build process | L | L | L | L | L | **High** |
| T21 | Persistent backdoor on build host (e.g., compromised package) | H | H | M | M | M | **Low** |

### Aggregate impact rating per threat (max across S/F/O/P)

| Threat | Max impact | Notes |
|--------|------------|-------|
| T1 | **M** | CFI |
| T2 | **M** | CFI |
| T3 | **L** | |
| T4 | **H** (operational) | CFI |
| T5 | **H** | CFI |
| T6 | **M** | CFI |
| T7 | **H** | CFI |
| T8 | **L** | |
| T9 | **M** | |
| T10 | **H** | CFI |
| T11 | **M** | CFI |
| T12 | **M** | CFI |
| T13 | **L** | |
| T14 | **M** | CFI |
| T15 | **H** | CFI |
| T16 | **M** | |
| T17 | **H** | CFI |
| T18 | **M** | NCEULA |
| T19 | **M** | NCEULA |
| T20 | **L** | |
| T21 | **H** | CFI |

---

## 6. Risk Determination

Risk = function of **Impact × Feasibility**. Using a coarse
21434-style 1–5 mapping (5 = highest risk):

| Impact \ Feasibility | High | Medium | Low |
|----------------------|------|--------|-----|
| **High**             | 5    | 4      | 3   |
| **Medium**           | 4    | 3      | 2   |
| **Low**              | 2    | 2      | 1   |

| Threat | Impact | Feasibility | **Risk** | Cyber-FuSa flag |
|--------|--------|-------------|----------|-----------------|
| T4  Linux→QNX flood, loss of Safety availability | H | High   | **5** | YES |
| T17 Tampered build inputs → malicious IFS         | H | Medium | **4** | YES |
| T7  Tampered Ubuntu cloudimg                      | H | Medium | **4** | YES |
| T11 Peer-MAC spoof on bridge                      | M | High   | **4** | YES |
| T1  Spoofed `linux-client` peer                   | M | High   | **4** | YES |
| T2  Frame replay (Phase 2-live)                   | M | High   | **4** | YES |
| T6  Rogue Linux-side peer binding                 | M | High   | **4** | YES |
| T9  Bridge flood degrades observability           | M | High   | **4** | NO  |
| T12 Bridge config tampered (host root)            | M | High   | **4** | YES |
| T14 Broadcast storm common-cause                  | M | High   | **4** | YES |
| T18 NCEULA accidental binary commit               | M | High   | **4** | NO (compliance) |
| T19 NCEULA leaky scp                              | M | High   | **4** | NO (compliance) |
| T16 Stolen SSH key                                | M | Medium | **3** | NO (pivot) |
| T5  virtio-net guest→host escape                  | H | Low    | **3** | YES |
| T10 Linux guest→KVM escape                        | H | Low    | **3** | YES |
| T15 Bridge L2 stack escape                        | H | Low    | **3** | YES |
| T21 Build host fully compromised                  | H | Low    | **3** | YES |
| T3  Eavesdrop QNX traffic                         | L | High   | **2** | NO  |
| T8  Eavesdrop IPC payload                         | L | High   | **2** | NO  |
| T13 Bridge promiscuous capture                    | L | High   | **2** | NO  |
| T20 Build host runaway                            | L | High   | **2** | NO  |

### 6.1 Top-3 highest-risk threats (Phase 1 cloud twin)

1. **T4** — Linux-side flood of `tap-qnx` starves the QNX guest's
   virtio-net ring (Risk 5; cyber-FuSa interaction candidate —
   loss of Safety guest availability is a hazard pattern).
2. **T17** — Tampered `mkqnximage` inputs in the build pipeline
   produce a malicious IFS booted by both twins (Risk 4; CFI —
   the highest-leverage supply-chain threat in scope).
3. **T7** — Tampered Ubuntu cloudimg subverts the Compute guest
   kernel before it ever reaches the bridge (Risk 4; CFI —
   parallels T17 on the Linux side).

(Multiple Risk-4 threats tie for #3; T7 is selected as the
representative because it complements T17's narrative.)

### 6.2 Cyber-FuSa interaction candidates (full set)

The threats below are flagged for joint review with the
parallel **FuSa-Analysis** Phase 1 run, because their
realisation would also plausibly induce a hazard the FuSa
analyst would recognise (loss of Safety guest, corrupted
command path, common-cause IPC loss, host pwn collapsing
both guests):

T1, T2, T4, T5, T6, T7, T10, T11, T12, T14, T15, T17, T21.

---

## 7. Open questions handed to Cyber-Design

Cyber-Design owns the response to each. Cyber-Analysis
deliberately does **not** prescribe the mechanism.

- OQ-1: What authentication scheme bounds T1/T6/T11
  (peer/identity spoofing) for Phase 2 IPC? (Static IP
  allow-list vs mTLS vs both — Cyber-Design call.)
- OQ-2: What Phase 2 anti-replay primitive bounds T2 without
  blowing the latency budget being measured?
- OQ-3: What rate-limiting / queue-bounding mechanism on
  `tap-qnx` reduces T4 below current Risk 5? Where does it
  live — host bridge, QNX guest stack, or both?
- OQ-4: Which build-pipeline integrity controls (signed
  commits, reproducible builds, ephemeral build host,
  release attestation) are proportionate to T17 / T21 in a
  *study-level* programme — and which are explicitly out of
  scope as overkill for a portfolio project?
- OQ-5: Do we accept residual T5 / T10 / T15 (KVM escape) as
  trusted-base risk per §1.2, or does Cyber-Design propose a
  stricter posture (e.g., minimal QEMU command line, seccomp
  profile, AppArmor)?
- OQ-6: Is `br0` MAC filtering / ebtables in scope for Phase 5,
  or treated as host-config best practice outside the
  study artefact?

---

## 8. Honest framing & limitations

- **No CVE intake.** T5/T10/T15/T21 cite "acquire/weaponise a
  CVE" as the attack path; in a real programme, Cyber-Verification
  would maintain a vulnerability-management process. This project
  does not.
- **Single-developer review.** T17/T18 ratings reflect that
  PR self-review is the only control; "High" feasibility is
  honest, not hand-waved.
- **No quantitative likelihood data.** L/M/H ratings are
  expert-judgement, not measured base rates. A real TARA would
  use historical CVE rates, threat intelligence feeds, and
  SoC-vendor advisories. None are available at this scale.
- **Trusted base assumption.** The KVM-on-Graviton host kernel
  is a **massive** TCB to assume away; doing so is consistent
  with the project's "no Type-1 hypervisor" framing. A real
  DRIVE OS analysis would not get to make that assumption.
- **Phase 1 is pre-IPC.** Several threats (T1, T2, T6) become
  *live* only when Phase 2 lands. They are entered now so the
  Cyber-Design baseline is in place before Phase 2 starts; they
  will be re-rated once Phase 2 measurements exist.
- **Not 21434 evidence.** Per the honest-framing rule at the top
  of this document.

---

## 9. Pair-review note for FuSa-Analysis

The CFI-flagged threats in §6.2 are the candidate set for the
**joint cyber-FuSa interaction analysis** at the Phase 1 gate.
Cyber-Analysis does not block on FuSa-Analysis output (per the
hard rules); each side runs its analysis in parallel and the
CFI list is the join key for the gate review.
