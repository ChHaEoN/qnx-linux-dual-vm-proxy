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

---

## 2026-05-07 amendment — build-host pivot

> **Study-level only; not 21434 evidence. TARA here is illustrative,
> not the work-product a real programme would audit.**

This amendment refreshes the Phase 1 TARA after the 2026-05-07
build-host pivot recorded in [findings.md](../findings.md) (the
"Phase 0 amendment: build host pivots to local Windows" entry).
The pivot collapses two previously-distinct hosts — the dev
workstation (Macbook macOS) and the build host (AWS t3.medium
x86_64 Ubuntu) — onto a **single local Windows PC** that now plays
both roles. The runtime host (c7g.large Graviton arm64) is
unchanged. The EC2 x86_64 build host is retained as a documented
*fallback* path (i.e., still in scope for users who follow the
fallback) but the *primary* path is Windows-native.

The Phase 0 record (sections 1–9 above, threat IDs T1..T21) is
preserved verbatim. This amendment only describes the *delta*: which
existing threats need to be re-rated, and which entirely new threats
arise from the new attack surfaces. New threat IDs continue at T22
and onward in the same rating style.

### A. Revised trust-boundary diagram (collapsed topology)

```
                        AWS account/IAM (out of scope)
                                    │
   ┌────────────────────────────────────────────────┐
   │           Local Windows PC (x86_64)            │
   │   ── plays BOTH roles: dev driver + build ──   │
   │                                                │
   │   git / IDE / OpenSSH client (Win32-OpenSSH)   │
   │   QNX Software Center (Windows-native GUI)     │
   │   SDP 8.0 install tree   C:\qnx800\            │
   │   mkqnximage --arch=aarch64le → output\ifs.bin │
   │   %USERPROFILE%\.ssh\id_*  (NTFS ACLs)         │
   │   Windows Defender + cloud-protection          │
   │   Optional: OneDrive / Dropbox / iCloud sync   │
   └────────────────────────────────────────────────┘
                              │
                              │ scp (Win32-OpenSSH client)
                              │ over public Internet → AWS VPC
                              ▼
                Runtime host (c7g.large arm64, KVM)
                              │
                      ┌───────┴───────┐
                      │  Host kernel  │ ◄── TCB (unchanged)
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

Trust boundaries crossed in the new topology:
1. ~~Dev workstation → build host (SSH)~~ — **REMOVED** (single machine).
2. Local Windows PC (build host) → Runtime host (SCP of IFS) — **unchanged in shape, changed in client implementation**: now Windows-native OpenSSH client (`%SYSTEMROOT%\System32\OpenSSH\ssh.exe`) instead of Linux/macOS `ssh`. Default key store is `%USERPROFILE%\.ssh\` on NTFS, not `~/.ssh` on POSIX.
3. Runtime host kernel ↔ each guest (KVM/virtio) — unchanged.
4. Guest ↔ Guest (`br0`) — unchanged.
5. Each guest ↔ host bridge (tap interface) — unchanged.

New trust boundary added by the pivot:
6. **Windows user account ↔ Windows admin (UAC)** — formerly handled implicitly across two POSIX hosts via `sudo` + per-host accounts; now a *within-machine* boundary on the build host.
7. **Local filesystem ↔ cloud-sync agent (OneDrive / Dropbox / iCloud-on-Windows)** — new exfiltration channel that did not exist when the build host was an EC2 instance with no consumer cloud-sync clients installed.

### B. Asset list delta

The Phase 0 asset rows A1..A10 are retained. Two are repointed and one is added:

- **A7 (SSH keys)** — `Owner / Location` reads "Dev workstation; runtime+build hosts" in the Phase 0 table. Under the new topology this collapses to a **single location**: `%USERPROFILE%\.ssh\` on the local Windows PC, plus `authorized_keys` on the runtime host. The C/I/Au/Az ratings are unchanged but the blast radius of A7 compromise is materially larger (see T16 revised, below).
- **A8 (QNX SDP 8.0 install tree)** — `Owner / Location` repoints from `qnx800/` on EC2 build host to `C:\qnx800\` (or installer-default per QNX SW Center) on the local Windows PC. Cybersec property ratings unchanged.
- **A11 (NEW)** — **Windows user-profile directory** (`%USERPROFILE%`, including `\.ssh`, `\Documents`, optionally synced subtrees). Owner / Location: local Windows PC NTFS. C: **H** (contains A7 plus potentially scp-staged copies of A1). I: **H**. A: M. Au: M. Az: **H** (a non-admin local process reading another user's profile is the relevant authorisation question on Windows, distinct from the POSIX `chmod 600` model). NR: L. A11 did not exist as a distinct asset in the Phase 0 model because the dev workstation was out of scope as a "Macbook IDE only".

### C. Revised feasibility ratings for existing threats (Phase 0 rows kept; revisions listed here only)

For each revised threat the original Phase 0 rating is preserved in §5/§6 above; the revised rating below is what the Cyber-Design hand-off should now act on. Rationale is one line per threat. Method: same 5-factor (ET / SE / KoT / WoO / Eq) aggregate as §5.

- **T7 revised**: Tampered Ubuntu cloudimg — feasibility unchanged at **Medium**, impact unchanged at **H**. Risk **4**. The cloudimg fetch is a runtime-host concern; the build-host pivot does not touch it.
- **T16 revised**: Stolen SSH key — *feasibility raised* from Medium to **High**. Aggregate Risk **4** (was 3). Rationale: the Phase 0 model spread the SSH key footprint across two machines (dev workstation private + build-host authorized_keys) and treated dev-workstation theft as the dominant path. Under the new topology the *same* private key now grants direct access to the runtime host from the same machine that produces the IFS — phishing-grade malware that lands on the Windows PC obtains source tree, build environment, IFS production, and an interactive scp session in one step. Windows-default `%USERPROFILE%\.ssh\` ACLs also do not enforce 0600-equivalent restrictions out of the box (other local users / services with read access are a known footgun); this raises ET and KoT into the L range.
- **T17 revised**: Tampered build inputs (`mkqnximage` config, kernel args) — feasibility unchanged at **Medium**, impact unchanged at **H**. Risk **4**. The supply chain into the repo is git, not the host OS, so the pivot does not change this rating directly. (But see T22 below for the *installer*-side supply-chain delta.)
- **T18 revised**: Accidental commit of QNX SDK / IFS binary into git — feasibility unchanged at **High**, impact unchanged at **M**. Risk **4**. The QNX install tree now lives on the same machine that holds the working tree (`C:\qnx800\` next to `E:\Project\qnx-linux-dual-vm-proxy\`); on Linux EC2 the SDP tree was outside the repo path by convention, so accidental staging of NCEULA-restricted files was bounded by directory layout. On Windows the user is more likely to drag-and-drop or VS Code's "Open Folder" across both trees. The aggregate stays High because §5 already rated it High; this note sharpens the rationale.
- **T19 revised**: `scp` of IFS to wrong destination — feasibility unchanged at **High**, impact unchanged at **M**. Risk **4**. The transport itself is unchanged (still SSH/SCP), but path-completion semantics differ on Windows (drive letters, `\` vs `/`, OpenSSH on Windows behaves like Unix here but PowerShell tab-completion does not always match), which is a minor offsetting friction; net rating unchanged.
- **T20 revised**: ~~Build host CPU starvation by runaway process~~ — *threat reframed.* Feasibility unchanged at **High**, impact unchanged at **L**. Risk **2**. Rationale: the original wording assumed a single-tenant t3.medium. On a developer's own Windows PC the host is multi-tenant by definition (browser, IDE, video calls, OS background tasks). Resource contention is therefore *more likely* but the **operational impact** is not safety- or integrity-relevant, only delivery-time, so the aggregate Risk does not move. Logged here for transparency.
- **T21 revised**: Build host fully compromised → all future IFS images silently backdoored — *feasibility raised* from Low to **Medium**. Aggregate Risk **4** (was 3). Rationale: the Phase 0 rating treated the build host as "single-tenant t3.medium ... hardened Ubuntu" with no consumer-grade attack surface. A general-purpose Windows PC has materially broader exposure (web browsing, email attachments, Office macros, USB devices, third-party software updates, gaming/streaming software). ET drops from H to M and KoT drops from M to L (the attacker no longer needs to know "this is a build host"; any compromise of the Windows machine reaches the build pipeline by virtue of the role collapse). SE remains M (still need to identify and tamper with the SDP install tree once on the box).

### D. New threats introduced by the pivot (T22 onward)

Same 5-factor feasibility scheme as §5. Same impact dimensions (S/F/O/P) as §4. CFI flag where realisation could plausibly induce a hazard for joint cyber-FuSa review.

#### Build-host (Windows) attack surface

- **T22 [T][CFI]** — *Windows-native QNX Software Center installer compromised at distribution.* The Windows installer is a new GUI executable signed by QNX/BlackBerry that did not exist in the Phase 0 model (the Linux flow was an extracted tarball / shell installer). A supply-chain compromise of the signed installer or its update channel results in a malicious-by-design SDP install tree that subsequently produces a backdoored IFS.
  - Path: attacker controls the QNX SW Center distribution endpoint or signing chain → developer installs SDP 8.0 → all IFS builds inherit backdoor.
  - ET: H, SE: H, KoT: M, WoO: H (one shot per release), Eq: M → **Feasibility: Low**.
  - Impact: S **H** (CFI: corrupted Safety guest), F M, O H, P L → Max **H**.
  - Risk **3**. CFI: yes (parallels T17/T21 but at vendor-installer layer).

- **T23 [T][CFI]** — *Windows Defender (or third-party AV) quarantines an in-progress `mkqnximage` artefact, producing a silently-truncated or missing IFS.* On-access scanning of large generated binaries during build is a known integrity failure mode (AV products have heuristically quarantined cross-compilation outputs in the past). The resulting IFS may boot partway and exhibit hard-to-diagnose runtime failure.
  - Path: AV on-access scanner triggers on a `mkqnximage` intermediate or final blob → file is quarantined or zeroed → downstream `scp` ships a truncated artefact → runtime host boots a corrupted IFS.
  - ET: L, SE: L (no attacker required; this is a misconfiguration / FP threat), KoT: L, WoO: L, Eq: L → **Feasibility: High**.
  - Impact: S M (CFI: a truncated Safety-guest IFS that boots into a degraded state is a hazard pattern; usually it just fails to boot, but a partial boot is the worse case), F L, O **H** (build pipeline broken with confusing failure mode), P L → Max **H**.
  - Risk **5**. CFI: yes. *This is a new top-of-stack risk introduced by the pivot.* The threat actor here is unintentional (defender is a defensive product) — but ISO/SAE 21434 vocabulary still treats a tampering event as tampering regardless of intent; the integrity property of A1 is what matters.

- **T24 [I][CFI]** — *OneDrive / Dropbox / iCloud-for-Windows silently syncs the SDP install tree, the working repo, or `output\ifs.bin` into a personal cloud account.* Default Windows installs increasingly redirect `Documents`, `Desktop`, `Pictures` to OneDrive without prominent UI indication; if the user clones the project under their `Documents` folder, or if SDP is installed under a synced location, the QNX IFS, SDP install tree, and SSH private key directory may end up replicated to a consumer cloud bucket.
  - Path: synced folder root contains repo or `C:\qnx800\` or `%USERPROFILE%\.ssh\` → cloud client uploads on file change → blob ends up in a personal cloud account whose credentials are out of scope.
  - ET: L (continuous, automatic), SE: L, KoT: L, WoO: L (every file write), Eq: L → **Feasibility: High**.
  - Impact: S L, F **M** (NCEULA breach: SDP redistribution to a non-licensed cloud account; A8 confidentiality compromise), O M (loss of NCEULA-compliance posture documented in security-model.md §4), P **M** (developer's identity bound to the synced account) → Max **M**.
  - Risk **4**. CFI: no (compliance/IP, not safety) but coupled with T16: **if `%USERPROFILE%\.ssh\` syncs, the private key replicates to a consumer cloud and T16 feasibility rises further.** Note this dependency for Cyber-Design.

- **T25 [E]** — *Windows local-privilege-escalation pivot from a non-admin user context into the build pipeline.* On a developer's general-purpose Windows PC, low-quality third-party software (gaming launchers, OEM utilities) commonly runs as a service with broad privileges; standard UAC-bypass techniques may allow lateral movement from a phishing-delivered initial foothold up to the build pipeline. Not a 0-day class threat — a known LPE attack surface that the EC2 single-purpose Ubuntu host did not present.
  - Path: phishing payload runs as user → LPE via third-party service or known UAC-bypass → write access to `C:\qnx800\` or `%USERPROFILE%\.ssh\` → pivots to T16 / T21.
  - ET: M, SE: M, KoT: M, WoO: M, Eq: L → **Feasibility: Medium**.
  - Impact: S **H** (chains into T21), F M, O H, P M → Max **H**.
  - Risk **4**. CFI: yes (chains).

- **T26 [S]** — *NTFS ACL / OpenSSH-on-Windows key-permission mismatch exposes `%USERPROFILE%\.ssh\id_*` to other local accounts or services.* On Linux/macOS, OpenSSH refuses to use a private key with permissions wider than 0600. On Windows the equivalent enforcement uses NTFS ACLs and the Win32-OpenSSH project has had a bumpy history of correctly applying / inheriting them; the developer must explicitly run `icacls` or PowerShell ACL fix-ups for the key to be considered "secure" by ssh, and many tutorials skip this step.
  - Path: developer creates / imports keys without ACL hardening → background service or another local user reads the private key → attacker authenticates to runtime host as the developer.
  - ET: L, SE: L, KoT: M, WoO: M, Eq: L → **Feasibility: High**.
  - Impact: S M (chains into T16 / T21 once on runtime host), F M, O M, P M → Max **M**.
  - Risk **4**. CFI: indirectly (chains).

- **T27 [I]** — *Windows SmartScreen / cloud-protection telemetry submits fragments of `output\ifs.bin` or `mkqnximage` outputs to Microsoft for reputation scoring.* Windows submits unfamiliar binaries to Defender cloud-protection by default ("Send sample files automatically" is on for many users). NCEULA-restricted artefacts may be uploaded to a Microsoft-controlled endpoint as a side effect of running the build.
  - Path: build produces unfamiliar PE-like artefacts (or AV heuristic flags an `output\` blob) → cloud-protection submits sample → blob copy lands on Microsoft infrastructure outside the developer's NCEULA-licensed possession.
  - ET: L (automatic), SE: L, KoT: L, WoO: L, Eq: L → **Feasibility: High**.
  - Impact: S L, F **M** (NCEULA: same compliance shape as T19), O M, P L → Max **M**.
  - Risk **4**. CFI: no (compliance).

#### Topology-collapse blast-radius threats

- **T28 [E][CFI]** — *Single-machine compromise yields source tree + build environment + IFS production + interactive scp session in one step.* This is the structural delta from the pivot, separated from the per-vector threats above so it can be argued about on its own merits. Under Phase 0, an attacker who landed on the dev workstation (Macbook) still had to pivot via SSH to the build host to produce a malicious IFS, and pivot again to scp it; under the new topology, all three capabilities are present on the same Windows host the moment a single foothold lands.
  - Path: any of T16 / T22 / T25 / T26 → attacker has source, SDP, build, and scp credentials in one place → produces and ships a backdoored IFS without any further pivot.
  - ET: L (post-foothold; pre-foothold is rated by the upstream T-IDs), SE: L, KoT: L, WoO: L, Eq: L → **Feasibility: High** (post-foothold; the upstream foothold is its own gating rate).
  - Impact: S **H** (CFI: corrupted Safety guest), F M, O H, P M → Max **H**.
  - Risk **5** (post-foothold). CFI: yes.
  - **Note:** the Risk-5 rating is conditional on a foothold existing. Cyber-Design should treat T28 as a *blast-radius amplifier* rather than a stand-alone threat, and decide whether to count it once or count it as a multiplier on T16 / T22 / T25 / T26. Cyber-Analysis flags this as an open-question modelling choice (see OQ-7 below).

#### Removed-attack-surface bookkeeping (no T-IDs assigned)

For audit traceability, the following Phase 0 attack surfaces are *no longer present* in the primary path (still present in the documented EC2 fallback path; out of scope of this amendment unless the user takes the fallback):

- SSH boundary between dev workstation and build host — collapsed; no separate hop.
- AWS EC2 build-host instance metadata service (IMDSv1/v2) — not reachable on the new primary path.
- IAM-role escalation from the build-host EC2 — not reachable on the new primary path.
- EC2 keypair handling specific to the build host — not reachable on the new primary path.
- t3.medium snapshot exfiltration via AWS API — not reachable on the new primary path.

These are surface *reductions*, but Cyber-Analysis does not net them against the additions above as a single "verdict number" — see honest-framing paragraph at the end of this amendment.

### E. Updated risk-table delta

Threats whose risk rating changes from §6 (Phase 0) under this amendment:

| Threat | Phase 0 Risk | Revised Risk | Change driver |
|--------|--------------|--------------|---------------|
| T16 Stolen SSH key | 3 | **4** | Single-machine collapse + Windows ACL footgun |
| T21 Build host fully compromised | 3 | **4** | Consumer-grade attack surface vs. single-purpose EC2 |
| T22 (NEW) QNX SW Center installer supply chain | — | **3** | New surface |
| T23 (NEW) AV quarantines IFS mid-build | — | **5** | New surface; integrity-impacting top risk |
| T24 (NEW) Cloud-sync exfiltration of SDP / IFS / keys | — | **4** | New surface; NCEULA + chains into T16 |
| T25 (NEW) Windows LPE pivot into build pipeline | — | **4** | New surface |
| T26 (NEW) NTFS / Win32-OpenSSH ACL mismatch on private key | — | **4** | New surface |
| T27 (NEW) SmartScreen / cloud-protection submission of build artefacts | — | **4** | New surface; NCEULA |
| T28 (NEW) Single-machine compromise = source + build + scp in one | — | **5** (post-foothold) | Topology collapse blast radius |

Top-of-stack risks under the revised model:
1. **T23** AV quarantines IFS mid-build (Risk 5; CFI). Replaces T4 as the highest-rated threat in the Phase 1 cloud-twin TARA when measured by aggregate Risk score.
2. **T28** Single-machine blast radius (Risk 5; CFI; post-foothold conditional).
3. **T4** Linux→QNX flood (Risk 5; CFI). Unchanged from Phase 0.

### F. Open questions handed to Cyber-Design (additions to §7)

- **OQ-7**: Should T28 (single-machine blast-radius amplifier) be counted as a stand-alone threat or as a multiplier on the upstream foothold threats (T16 / T22 / T25 / T26)? The choice affects how the Cybersecurity Concept should describe the build-host TCB.
- **OQ-8**: How should the project document the *existence* of the EC2 fallback path without rating its threats twice? (The fallback retains T20-original / T21-original feasibility ratings; the primary path uses the revised ratings. Cyber-Design will need to choose a documentation convention.)
- **OQ-9**: Is the AV-quarantine integrity threat (T23) a security threat, a build-system reliability issue, or both? In ISO/SAE 21434 vocabulary it is a tampering event against A1's integrity property (regardless of attacker intent), so Cyber-Analysis lists it here. Cyber-Design may wish to coordinate with FuSa-Design because a corrupted-but-bootable IFS is also a FuSa concern.
- **OQ-10**: Cloud-sync exfiltration (T24) and SmartScreen/cloud-protection submission (T27) both turn the Windows build host into an outbound NCEULA-leak channel. Are these in-scope for Cyber-Design's Cybersecurity Concept, or do they belong in the NCEULA compliance-audit table in security-model.md §4 (a separate work product)? Cyber-Analysis flags both — Cyber-Design picks the home.

### G. Pair-review note for FuSa-Analysis (amendment)

New CFI-flagged threats added to the cyber-FuSa interaction candidate set: **T22, T23, T25, T28**. The full revised CFI list is now:

T1, T2, T4, T5, T6, T7, T10, T11, T12, T14, T15, T17, T21, T22, T23, T25, T28.

T23 (AV quarantines IFS mid-build) is the most novel addition — it is a *non-malicious-actor* tampering event that nonetheless breaches A1 integrity. FuSa-Analysis should be aware that "the build pipeline can produce a corrupted Safety-guest image without anyone noticing" is now a Phase 1 cloud-twin top-of-stack concern, not an edge case.

### H. What this amendment does NOT demonstrate

- This remains a **study-level TARA**. It is not 21434 audit evidence, it is not signed off by an independent assessor, and the threat ratings are expert-judgement L/M/H, not measured base rates from CVE feeds or vendor advisories.
- The new Windows-native attack surfaces (OneDrive sync behaviour, Defender quarantine likelihood, SmartScreen submission rate, NTFS ACL drift on `%USERPROFILE%\.ssh\`) have been **enumerated, not measured**. None of T22..T28 has been verified under real Windows-build conditions in this repo. Phase 1 implementation/test work could measure (for example) whether `mkqnximage` outputs actually trigger Defender quarantine on a default-configured Windows 11 host — but until that data exists, the feasibility ratings here are illustrative.
- The **net security delta vs. the old EC2 topology has NOT been quantified.** This amendment lists removed surfaces (the EC2 IMDS / IAM-role / keypair / snapshot exfiltration) and added surfaces (T22..T28) but it deliberately does not collapse them into a single "the pivot is/is not a security improvement" verdict. That comparison requires a probability-weighted apples-to-apples model the project does not have. The honest framing is: the pivot is a **cost/friction optimisation whose net security effect is non-obvious**, and the asymmetric blast-radius concern in T28 is the single biggest reason a real programme might push back on the pivot regardless of the cost win.
- The fallback EC2 path has **not** been re-analysed in this amendment. Its Phase 0 ratings (T1..T21) still apply when the user takes the fallback. There is no "merged" rating that combines both paths — the choice of build host changes which threat list is in force.

---

## Phase-1 Gate Addendum (2026-06-11) — TARA reconciliation with the as-built QHV/TCG boundary

> **Study-level only; not 21434 evidence. TARA here is illustrative,
> not the work-product a real programme would audit.**

This addendum reconciles the Phase-1 TARA with what was **actually
built** at the Phase-1 gate, recorded in the 2026-06-11 findings entry
(*"QNX Hypervisor (QHV) boots a QNX guest under QEMU-TCG"*) and
evidenced in
[../../logs/sample-boot/qhv-tcg-host-and-guest-boot.log](../../logs/sample-boot/qhv-tcg-host-and-guest-boot.log).
The TARA body (§1–§9) and the 2026-05-07 amendment (§A–§H) analysed an
architecture that the as-built leg has **partially falsified**. Per the
honest-framing and hard rules: this is a Cyber-Analysis (TARA)
deliverable — it **FINDS threats and rates feasibility**; it does
**not** propose mitigations (that is Cyber-Design's deliverable).

The prior sections are **preserved verbatim** for audit traceability.
This addendum describes only the *delta*: which boundary/assets/threats
the as-built config changes, the **new threat scenarios** it
introduces, and the new risk rows. New threat IDs continue at **T29**
in the same rating style. New asset IDs continue at **A12**.

### AA. Item / boundary delta (as-built vs. TARA-body assumption)

The TARA body and §A–§H assumed a **KVM-accelerated dual-VM** item on
an AWS Graviton runtime host: a QNX guest **and** a Linux guest as two
co-equal VMs under QEMU/KVM, virtio-net IPC over a Linux bridge `br0` +
`tap-qnx`/`tap-linux`, with an x86_64 (then Windows) build host
producing the IFS. The as-built Phase-1 cloud leg is materially
different:

| Dimension | TARA-body / §A–§H assumption | As-built (2026-06-11) | Consequence for the model |
|---|---|---|---|
| Acceleration | QEMU/**KVM** on Graviton (EL2 passthrough) | QEMU-**TCG** pure emulation of an EL2-capable `-cpu max` | The host-kernel-KVM TCB assumption (§1.2) is **not exercised**; the new TCB root is the `qvm` hypervisor process itself. KVM acceleration deferred to Phase 3 (Orin). |
| Hypervisor model | None ("no Type-1 hypervisor", per CLAUDE.md) — KVM host-mediated | **QHV `qvm` Type-1 hypervisor** synthesising a guest partition | A genuine Type-1 partition boundary (host `QEMU_virt` ↔ guest `ARMv8_Foundation_Model`) now exists **in software** and is the central new attack surface. |
| Guests | QNX guest **+** Linux guest (peer VMs, not mutually trusted) | **QNX host (`qnx-qhv`) + QNX guest (`qnx-guest`)**; **no Linux guest** | All Linux-guest assets/threats (A2, A4; T6, T7, T8, T9, T10) **defer** — they are not present in the as-built leg. |
| IPC / network | virtio-net over `br0` + `tap-qnx`/`tap-linux`, live in Phase 2 | **Inert** — host io-sock stack down (`network stack down`, `Address family not supported`); qvm config ran **no-network** | The entire bridge/tap data-path asset+threat cluster (A5, A6; T1, T2, T3, T4, T8, T9, T11, T12, T13, T14, T15) **defers** for this leg. New IPC surface is the **qvm vdev / synthetic-platform** boundary, not `br0`. |
| Runtime location | AWS cloud (c7g.large Graviton) | **Local Windows build host**, QEMU-TCG; **no AWS in the demonstrated leg** | The build host **is** the runtime host in this leg. The Windows-host asset/threat surface (§A–§H: A11; T22–T28) is **retained and now also hosts execution**, not just the build. |
| Build host | x86_64 → (§A–§H) Windows | Windows (SDP 8.0.4, `C:\Users\<user>\qnx800`) | Unchanged from §A–§H; T22–T28 remain in force. |

**Honest framing of the boundary delta:** the as-built leg demonstrates
the **QHV software attack surface** (qvm config parsing, vdev
instantiation, guest isolation, EL2/VHE host bring-up) — it does **NOT**
demonstrate a hardware-isolation boundary. TCG emulates EL2 on a laptop;
there is no real RoT, no fuse-backed measured boot, no hardware
partitioning, and no timing/acceleration fidelity. A guest→host escape
found here is a finding about the *qvm software*, not a claim about
silicon-level isolation. Conversely, the *absence* of an escape here
proves nothing about hardware behaviour. The threats below are scoped
strictly to the software surface the as-built config exercises.

### AB. Asset-list delta

Phase-0 assets A1, A8, A9 (IFS binary, SDP install tree, build
scripts/repo) and §A–§H asset A11 (Windows user-profile) are
**retained** — they remain in the as-built leg. The following assets
are **added** (A12+) or **deferred** (present in the model but not
exercised in this leg).

**New / changed assets:**

| ID | Asset | Owner / Location | C | I | A | Au | Az | NR |
|----|-------|------------------|---|---|---|----|----|----|
| A12 | **QHV `qvm` hypervisor process** (the Type-1 host; TCB root for the guest partition) | QNX host `qnx-qhv`; `target/qnx/aarch64le/sbin/qvm` + `libhyp` | M | **H** (its integrity == the partition boundary integrity) | **H** (its availability == guest availability) | **H** | **H** (it authorises every guest vdev access / EL2 trap) | L |
| A13 | **`g2.conf` qvm configuration file** (defines guest memory map, vdevs, vCPU, image path) | QNX host fs; auto-generated by `post_start.custom` snippet | M | **H** (controls guest isolation & resource grants) | M | **H** | **H** | L |
| A14 | **Synthetic-platform vdev interface** (the `ARMv8_Foundation_Model` virtual devices qvm presents to the guest: virtio-blk, console, etc.) | qvm-internal; guest↔host shared rings | M | **H** (a malformed vdev access is the classic escape primitive) | **H** | M | **H** | L |
| A15 | **Guest↔host EL2 boundary** (trap-and-emulate path; the partition boundary itself) | qvm / EL2 (here: TCG-emulated EL2/VHE) | M | **H** | **H** | **H** | **H** | L |
| A16 | **Embedded guest image under `/data/hypervisor/`** (the guest IFS/disk that `--type=qemu --qvm=yes --guest=<dir>` bakes into the host image) | QNX host fs; staged at build time on the Windows host | M (NCEULA, as A1) | **H** (boot integrity of the guest partition) | M | **H** | M | L |
| A17 | **Host entropy / PRNG state** (the host RNG that seeds host **and** guest crypto, incl. sshd host keys / session keys at boot) | QNX host kernel `random`/`/dev/random` | **H** (predictable RNG output undermines all derived key material) | **H** | M | **H** | M | L |

A17 is promoted to a first-class asset specifically because the boot log
shows it **failing** (see T31). It was implicit (inside A3 "guest
runtime state") in the body; the as-built evidence makes it load-bearing
on its own.

**Deferred assets (modelled but not exercised in the as-built leg):**

- **A2** Ubuntu cloudimg, **A4** Linux guest runtime state — **no Linux
  guest** in this leg. Defer to whichever future leg reintroduces a
  Linux compute partition (Phase 2/3).
- **A5** virtio-net frames on `br0`, **A6** `br0` configuration — the
  network path **did not come up**; no bridge/tap exists in this leg.
  Defer.
- **A7** SSH keys / **A10** KVM/QEMU process boundary — A7 still applies
  to the (unused, in this leg) scp-to-Graviton path; A10's *KVM*
  framing is superseded by A12 (`qvm`) for the as-built leg, though the
  outer `qemu-system-aarch64 -accel tcg` process boundary on the
  Windows host is a real (TCG, not KVM) container around the whole stack.

Deferring an asset is **not** retiring it: the moment a future leg
restores KVM, the Linux guest, or the bridge, the corresponding
A2/A4/A5/A6 rows and their T-IDs re-activate at their existing ratings.

### AC. New threat scenarios (T29–T34)

Same 5-factor feasibility scheme as §5 (ET / SE / KoT / WoO / Eq, each
L/M/H; predominantly-L ⇒ High feasibility). Same impact dimensions
(S/F/O/P) as §4. **[CFI]** = candidate for joint cyber-FuSa interaction
review. Attacker model, unless stated, is **a process with code
execution inside the QNX guest partition** (the realistic hypervisor
threat model: the guest is assumed potentially hostile and the question
is whether it stays contained) — *plus*, for config/supply-chain
threats, an attacker who can influence the host filesystem on the
Windows build/runtime machine (the §A–§H foothold model).

#### QHV hypervisor / partition boundary

- **T29 [T][CFI]** — *Malicious or malformed `g2.conf` (A13) mis-configures
  the guest partition or compromises the qvm host.* The as-built config
  is **auto-generated at host boot** by a custom `post_start.custom`
  snippet, then consumed by `qvm @g2.conf`. A tampered or malformed
  config can (a) grant the guest a wider memory window / extra vdev than
  intended (mis-isolation), (b) point the guest-image path at an
  attacker-substituted image (chains to T33), or (c) trigger a
  config-parser fault in qvm. The boot log already shows one
  config-driven host-side fault:
  `[g2.conf:9] Failed to arm a resource manager: Function not implemented`
  — evidence that g2.conf directives reach privileged host paths and can
  fail there (availability angle: see T34).
  - Path: attacker writes/edits `g2.conf` (or the snippet that emits it)
    on the host fs → qvm parses attacker-controlled directives at boot →
    over-broad grant or parser fault.
  - ET: M, SE: M (must understand qvm config grammar + vdev model), KoT:
    M, WoO: M (boot-time / host-fs-write window), Eq: L → **Feasibility:
    Medium**.
  - Impact: S **H** (CFI: mis-isolated or mis-resourced Safety guest), F
    M, O **H**, P L → Max **H**.
  - Risk **4**. CFI: yes.

- **T30 [E][CFI]** — *Guest→host escape across the qvm vdev /
  synthetic-platform boundary (A14/A15).* The central hypervisor threat.
  The guest sees the synthetic `ARMv8_Foundation_Model` platform; every
  device it touches (virtio-blk `disk-qemu`, console, any synthesised
  vdev) is a trap-and-emulate surface handled by privileged qvm host
  code. A malformed descriptor ring, an out-of-bounds DMA-like offset, a
  vdev MMIO access qvm mishandles, or an EL2 trap path bug lets hostile
  guest code read/write host memory or execute in the host context —
  collapsing the partition boundary that is the entire point of the
  Type-1 model.
  - Path: hostile code in `qnx-guest` → crafts malformed vdev
    access / descriptor → qvm host-side handler bug → host memory
    disclosure or code execution at host privilege.
  - ET: H, SE: H (hypervisor escape-class expertise; vdev internals),
    KoT: H (need qvm/vdev implementation knowledge — closed source,
    NCEULA), WoO: M (continuous once guest runs), Eq: M → **Feasibility:
    Low**.
  - Impact: S **H** (CFI: host pwn == loss of the partition boundary ==
    both partitions), F M, O **H**, P M → Max **H**.
  - Risk **3**. CFI: yes. *This is the highest-impact, lowest-feasibility
    threat in the addendum — structurally analogous to the deferred
    KVM-escape threats T5/T10/T15, but now against `qvm` rather than KVM,
    and now demonstrable as a software surface (not assumed-away TCB).*

#### Entropy / boot-time crypto weakness (concrete as-built finding)

- **T31 [I][S][CFI]** — *PRNG-not-seeded yet sshd-started → predictable
  host keys / weak session crypto at boot (A17).* This is a **concrete,
  evidenced** weakness, not a hypothetical. The boot log shows, on **both
  host and guest**:
  `random: Could not initialize entropy`, `Unable to access /dev/random`,
  and `PRNG is not seeded` — immediately followed by `---> Starting sshd`.
  An sshd that generates or uses host keys / session material while the
  PRNG is unseeded can produce **low-entropy, predictable, or
  cross-boot-repeating key material**. The classic damage shape
  (cf. the 2008 Debian OpenSSL and embedded "factory-default host key"
  classes): an attacker who can predict or enumerate the key space can
  impersonate the host (spoofing), or recover/replay session keys to
  decrypt or MITM the SSH channel (information disclosure). Because the
  *same* unseeded condition affects host and guest, the weakness is
  **common-cause** across the partition boundary.
  - **Damage scenario:** predictable sshd host key on `qnx-qhv` (and
    `qnx-guest`) → (a) attacker pre-computes / brute-forces the host key
    and impersonates the management endpoint, harvesting any credential a
    developer presents; or (b) weak session keying allows passive
    decryption of the management session, exposing anything that session
    carries (commands to the host, future scp of NCEULA-restricted
    images). Safety angle: the SSH channel is the host/guest *management*
    path; a spoofed or decrypted management channel is a route to
    influence the Safety partition's host — hence CFI.
  - Path: boot reaches `Starting sshd` while `PRNG is not seeded` →
    sshd derives host/session key material from a degenerate RNG →
    attacker predicts/enumerates/recovers the key → host impersonation or
    session compromise. No guest-escape needed; reachable from any party
    who can reach the sshd port once networking exists.
  - ET: M (key prediction/enumeration depends on how degenerate the seed
    is — unmeasured here), SE: M, KoT: M, WoO: M (keys fixed at each
    boot; persistent if keys are persisted to the image), Eq: L →
    **Feasibility: Medium** (rated conservatively; could be **High** if
    the unseeded state proves fully deterministic — unmeasured, see
    honest-framing).
  - Impact: S M (CFI: management-channel compromise reaches the host of
    the Safety partition), F M (NCEULA blob exposure if it transits the
    weak channel), O M, P M → Max **M**.
  - Risk **3** (Medium impact × Medium feasibility). **Flagged as the
    most important *concrete* finding in this addendum** — the others are
    structural/architectural; this one is observed in the as-built log.
    Note: in the as-built leg networking is inert, so the *remote*
    exploit path is currently latent; the **defect (unseeded crypto at
    sshd start)** is nonetheless real and present in the image and
    becomes live the instant networking comes up. Rated on the
    networking-up assumption with the latency noted.

#### Supply-chain / integrity of the embedded guest image

- **T32 [T][CFI]** — *Tampered embedded guest image under
  `/data/hypervisor/` (A16) → the qvm host boots an attacker-controlled
  guest partition.* The `--type=qemu --qvm=yes --guest=<dir>` build bakes
  the guest IFS/disk into the host image under `/data/hypervisor/`, on
  the **Windows build host** (inheriting the full T22–T28 build-host
  surface). A tampered guest image is booted *trustingly* by qvm — there
  is no guest-image signature check in this study (cf. security-model.md
  §3, "Guest IPL signature check: No"). This is the QHV-specific analogue
  of T17 (tampered IFS) and T33's host-side twin, but it targets the
  *guest* partition image specifically and rides the existing Windows
  build-host threats.
  - Path: any of T22/T23/T25/T26/T28 (or direct edit of the staged guest
    dir) tampers the guest image before `mkqnximage` bakes it → host
    image embeds a backdoored guest → qvm boots it as the Safety
    partition.
  - ET: M, SE: M, KoT: M, WoO: M (build-time), Eq: L → **Feasibility:
    Medium**.
  - Impact: S **H** (CFI: corrupted Safety guest partition), F M, O **H**,
    P L → Max **H**.
  - Risk **4**. CFI: yes. *Inherits T23's specific concern: even a
    non-malicious AV quarantine of the guest blob mid-bake yields a
    truncated-but-bootable guest partition.*

#### Availability of the qvm host bring-up path

- **T34 [D][CFI]** — *qvm host-side resource-manager arm failure as an
  availability/DoS surface (A12).* The boot log shows
  `[g2.conf:9] Failed to arm a resource manager: Function not implemented`
  on the **host** during `qvm @g2.conf`. This is a concrete evidenced
  fault on the privileged host bring-up path: a config directive reaches
  a host resource-manager arm that is not implemented on this build and
  fails. Generalised: a config-reachable or guest-reachable code path
  that faults the qvm host (or a vdev backend, or the resource-manager
  registration) is an availability surface — if it can be driven to abort
  qvm or wedge a vdev, the guest partition stalls or never starts (the
  guest *did* reach `Startup complete` here, so this particular failure
  was non-fatal — but it proves the class of host-bring-up faults exists
  and is reachable from config).
  - Path: malformed/edge-case `g2.conf` directive (T29) **or** a
    guest-driven vdev pattern → host resource-manager / vdev arm fault →
    qvm host degrades or aborts → loss of guest (Safety) partition
    availability.
  - ET: L (a config edge case is cheap to reach), SE: M (need to know
    which directive faults the arm), KoT: M, WoO: M, Eq: L →
    **Feasibility: Medium** (toward High for the config-driven variant,
    given an evidenced fault already exists).
  - Impact: S **H** (CFI: loss of Safety-partition availability is a
    hazard pattern, mirroring T4 on the new boundary), F L, O **H**, P L →
    Max **H**.
  - Risk **4**. CFI: yes.

### AD. Damage scenarios (T29–T34 summary)

| Threat | S | F | O | P | Notes |
|--------|---|---|---|---|-------|
| T29 g2.conf tamper/malformed | **H** (CFI: mis-isolated/mis-resourced Safety guest) | M | **H** | L | Config reaches privileged host paths (evidenced). |
| T30 guest→host escape (vdev/EL2) | **H** (CFI: partition boundary collapse) | M | **H** | M | Highest impact; lowest feasibility. |
| T31 PRNG-unseeded + sshd | M (CFI: management-channel compromise) | M (NCEULA blob via weak channel) | M | M | Only *evidenced concrete* crypto defect; common-cause host+guest. |
| T32 tampered `/data/hypervisor/` guest image | **H** (CFI: corrupted Safety partition) | M | **H** | L | Rides T22–T28; no guest-image signature check. |
| T34 qvm resource-mgr arm fault (DoS) | **H** (CFI: loss of Safety-partition availability) | L | **H** | L | Evidenced non-fatal fault proves the class. |

### AE. Risk table (T29–T34)

Same coarse 21434-style Impact×Feasibility matrix as §6 (5 = highest).

| Threat | Impact | Feasibility | **Risk** | Cyber-FuSa flag |
|--------|--------|-------------|----------|-----------------|
| T29 Malicious/malformed `g2.conf` → mis-isolation or host fault | H | Medium | **4** | YES |
| T32 Tampered embedded guest image under `/data/hypervisor/` | H | Medium | **4** | YES |
| T34 qvm resource-manager arm fault → Safety-partition DoS | H | Medium | **4** | YES |
| T30 Guest→host escape across qvm vdev / EL2 boundary | H | Low | **3** | YES |
| T31 PRNG-not-seeded + sshd-started → predictable/weak host keys | M | Medium | **3** | YES |

**Top-of-stack for the as-built leg:**
1. **T29 / T32 / T34** (Risk 4, CFI) — the config-integrity (T29),
   guest-image-integrity (T32), and host-availability (T34) threats that
   sit directly on the new qvm partition boundary. T34 and T29 are
   partly *evidenced* by faults already visible in the boot log.
2. **T30** (Risk 3, CFI) — the canonical guest→host escape; highest
   impact, lowest feasibility, and the threat the whole Type-1 framing
   exists to resist.
3. **T31** (Risk 3, CFI) — the single **concrete, observed** crypto
   weakness (PRNG-unseeded sshd start); rated Medium feasibility with an
   explicit note it could be higher if the unseeded state proves
   deterministic.

Note on cross-leg comparison: the prior top-of-stack risks (T4 bridge
flood, T23 AV quarantine, T28 single-machine blast radius) are **not
retired**. T4 **defers** (no bridge in this leg). T23/T28 **remain
live** because the Windows build host still builds the IFS *and* the
embedded guest image (T32 explicitly inherits them). The as-built leg
therefore *adds* the qvm-boundary risks on top of the still-present
build-host risks; it does not replace them.

### AF. Cyber-FuSa interaction candidates (addendum additions)

New CFI-flagged threats: **T29, T30, T31, T32, T34** (all of them). The
strongest cyber-FuSa joins for the parallel FuSa-Analysis HARA:
- **T34 ↔ T4 / HE-02/03/06** (loss of Safety-partition availability) —
  the qvm-boundary analogue of the bridge-flood availability hazard.
- **T32 ↔ K2** (wrong/cached IFS) — now extended to the *guest
  partition* image baked under `/data/hypervisor/`.
- **T31** — a corrupted/predictable management-channel crypto state that
  is *common-cause across host and guest* (both unseeded) is a DFA-style
  common-cause pattern FuSa should see.

### AG. Honest framing — what this addendum does NOT demonstrate

- **TCG-on-a-laptop is a software surface, not a hardware boundary.**
  Every qvm-boundary threat (T29, T30, T34) is a finding about the
  **qvm software** (config parser, vdev backends, EL2/VHE trap paths) as
  exercised under emulation. It demonstrates the *attack surface exists
  and is reachable*; it demonstrates **nothing** about real
  hardware-partition isolation, RoT, fuse-backed secure boot, or timing.
  A real DRIVE OS hypervisor analysis would run against silicon EL2 with
  a hardware RoT in scope. (Pairs with CLAUDE.md "no Type-1 partition
  isolation … KVM-on-Linux is host-mediated, not certified Type-1" — and
  note QHV here is real *software* Type-1, but **not** hardware-isolated
  in this leg.)
- **The entropy finding is evidenced but not characterised.** T31 cites
  observed log lines (`PRNG is not seeded`, sshd started anyway). It does
  **not** measure how degenerate the seed actually is, whether host keys
  are regenerated per boot or persisted, or whether the weak keys are
  ever exposed (networking is inert in this leg). The Medium feasibility
  is conservative expert judgement; verification of actual key entropy is
  Cyber-Verification's job, not done here.
- **The escape threat T30 is enumerated, not attempted.** No fuzzing of
  the vdev interface, no exploitation attempt, no qvm source review was
  performed. The Low feasibility reflects the difficulty *and* the
  closed-source/NCEULA knowledge barrier — not a demonstrated
  containment guarantee.
- **No quantitative likelihood data**, single-developer review, and
  study-level L/M/H ratings — same caveats as §8 carry forward.
- **This addendum does not net the as-built leg against the
  KVM/dual-VM/bridge leg into a single verdict.** It records which
  assets/threats defer and which are added; it does not claim the
  as-built leg is "more" or "less" secure than the original design.

### AH. Open questions for Cyber-Design (additions; Cyber-Analysis does NOT answer these)

- **OQ-11**: What integrity binding should `g2.conf` (A13) carry, given
  it is **auto-generated at host boot** by a custom snippet and then
  drives privileged qvm host paths (T29/T34)? (Config signing,
  generation-time validation, a minimal/locked-down config schema —
  Cyber-Design's call.)
- **OQ-12**: Should the embedded guest image under `/data/hypervisor/`
  (A16) be signature-verified by the qvm host before boot (T32), given
  security-model.md §3 currently records "Guest IPL signature check:
  No"? Where does the trust anchor live in a no-RoT TCG leg vs. a future
  Orin silicon leg?
- **OQ-13**: **Entropy provisioning before sshd start (T31).** What
  should gate `Starting sshd` on a seeded PRNG, and how is entropy
  provisioned on a QNX qemu-virt build where `devr-virtio.so` is rejected
  as an entropy source and `/dev/random` is inaccessible? Is host-key
  regeneration-per-boot vs. persisted-key the safer posture here?
- **OQ-14**: How should the **guest→host vdev/EL2 boundary** (T30) be
  hardened or argued-down for a *study-level* programme — minimal vdev
  set, locked-down synthetic platform, or accepted as residual TCB risk
  the way KVM-escape (T5/T10/T15) was accepted in §1.2? Which framing is
  honest given qvm here is real Type-1 *software* but TCG-emulated EL2?
- **OQ-15**: Is the `qvm` host the right place to draw a **secure-boot /
  measured-boot** boundary (the host image embeds and launches the guest
  partition), and how should that be framed against the existing
  security-model.md §3 secure-boot gap table, which predates the QHV
  pull-forward and has no hypervisor row populated for the cloud leg?
- **OQ-16**: How should Cyber-Design treat the qvm host-bring-up
  availability surface (T34) — is the `Failed to arm a resource manager`
  fault a config-robustness requirement on qvm, a build-completeness
  issue (missing package, cf. the 2026-06-10 `target.qemuvirt`
  finding), or both? Coordinate with FuSa-Design (loss-of-Safety-partition
  availability overlaps T4 / HE-02/03/06).
