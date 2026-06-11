# Phase 5 — Security model (cybersecurity overlay)

> **Study-level only; not 21434 evidence. TARA here is illustrative,
> not the work-product a real programme would audit.**

> **Status:** scaffold. Phase 5 starts after Phase 4 (twin diff)
> lands so the threat model can be applied to a *measured* system,
> not a hypothetical one. §2 below has been pre-populated with a
> Phase 1 starting-point TARA (cloud twin only, pre-IPC) by the
> Cyber-Analysis agent — see [tara/phase1-cloud-tara.md](tara/phase1-cloud-tara.md)
> for the full underlying analysis. Likelihood/Impact ratings are
> qualitative L/M/H using ISO/SAE 21434 vocabulary.

This document is the cybersecurity-overlay deliverable. It pairs with
the FuSa overlay (FMEA worksheets in `skills/fmea/examples/`) — both
are **study-level** artefacts, not certification evidence. The aim is
to demonstrate that the project can be discussed in ISO/SAE 21434 and
ISO 26262 vocabulary without overclaiming compliance.

---

## 1. Scope of analysis

Boundary of the system under analysis:

> **Topology note (ADR-002, ratified 2026-06-11):** the bullets below and the
> STRIDE tables in §2 are a pre-Phase-4 scaffold written against the original
> two-VM-over-`br0` cloud design, which the QHV pivot **falsified** for the
> cloud leg. Per [ADR-002](phase2-topology-decision.md) the cloud leg is
> QNX-host ↔ QNX-guest over the `qvm` `virtio-console` vdev (no `br0`/tap,
> host `io-sock` down); the `br0`/virtio-net heterogeneous path lives on
> **Phase 3 / Orin** only. The `br0`-based threats below therefore apply to the
> Orin leg (Phase 3+); the cloud-leg threat model is reconciled in the Gate
> Addendum of [tara/phase1-cloud-tara.md](tara/phase1-cloud-tara.md). These
> tables are re-derived against the measured system when Phase 5 starts.

- The QNX Safety guest (in QEMU)
- The Linux Compute side — **Phase 3 / Orin only** (L4T native); there is no Linux guest on the cloud leg (ADR-002)
- The IPC channel between them: cloud leg = QNX-host ↔ QNX-guest over the `qvm` `virtio-console` vdev; Orin leg = virtio-net via host bridge `br0`
- The host kernel (Linux on Graviton or L4T on Orin) — included as **trusted base**, not as part of attack surface
- The QNX IFS build pipeline on the cloud-twin x86_64 build host

Out of scope:

- AWS account-level security (IAM, network ACLs) — repo policy only states "do not commit `.pem`/`.env`"
- Physical security of the Orin Nano dev kit
- Any hypothetical CAN / Ethernet / wireless attack surface (none in this design)
- DRIVE OS production security posture (this is a personal project, not a customer engagement)

---

## 2. STRIDE threat model (per-component skeleton)

> Phase 1 cloud-twin starting-point ratings populated by the
> Cyber-Analysis agent. The Mitigation column references mechanisms
> Cyber-Design **will specify** in Phase 5 — these are placeholders,
> not commitments produced by Cyber-Analysis. Ratings are L/M/H per
> ISO/SAE 21434-style qualitative scales (see TARA doc for the rubric).

### 2.1 QNX Safety guest

| Threat | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Spoofed `linux-client` connecting to `qnx-server` | **S**poofing | M — single-host attacker on `br0` can craft any source MAC/IP; no auth in Phase 1 | M — wrong commands reach Safety guest; *cyber-FuSa candidate* if Phase 2 IPC carries any safety-relevant payload | Static IP allow-list on QNX side; future: mTLS |
| Frame replay | **T**ampering | L — Phase 1 has no live IPC traffic to replay; rises to M in Phase 2 once `qnx-server` is up | M — duplicate command may re-arm a Safety action; *cyber-FuSa candidate* | Sequence-number monotonicity check |
| Repudiation of message origin | **R**epudiation | L — same-host attack surface; logs sit on host fs | L — no audit obligation in study scope | Log sequence + timestamp pairs at server |
| Frame disclosure (eavesdrop on `br0`) | **I**nformation Disclosure | M — anyone with root on the runtime host can `tcpdump br0`; cleartext virtio-net | L — Phase 1 boot traffic carries no secrets; rises to M only if SSH keys or NCEULA-restricted blobs ever traverse `br0` | Threat is host-internal; encryption deferred |
| Flooding causing buffer exhaustion | **D**enial of Service | M — co-resident Linux guest can saturate `tap-qnx` trivially; no rate limiting | M — QNX boot or Phase 2 listener stalls; *cyber-FuSa candidate* (loss-of-availability of Safety guest is a hazard pattern) | Rate limit on accept(); bounded queue |
| Privilege escalation via virtio-net driver | **E**levation of Privilege | L — QNX virtio-net is mature, KVM virtio backend is well-audited; no public 0-day on Phase 1 baseline | H — guest→host break = full runtime-host compromise = both VMs lost; *cyber-FuSa candidate* | QNX guest runs as least-privileged user; rely on QEMU isolation |

### 2.2 Linux Compute side

| Threat | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Spoofed `qnx-server` peer (rogue process binds to expected port) | **S**poofing | M — Linux cloudimg ships with broad userspace; any local process can bind unprivileged ports | M — `linux-client` mis-routes commands; *cyber-FuSa candidate* in Phase 2 | Static peer-IP pinning; future: mTLS |
| Tampered cloudimg (supply-chain) | **T**ampering | L — Ubuntu cloudimg fetched over HTTPS with apt signing; checksum verified on download | H — compromised guest kernel = persistent foothold in runtime host's KVM scheduling domain | Pin cloudimg SHA256 in `bootstrap-runtime-host.sh`; signed apt repos |
| Repudiation of guest-side command origin | **R**epudiation | L — single-developer scope | L — no audit need in study scope | Same as §2.1 |
| Cleartext payload eavesdrop via host `tcpdump` | **I**nformation Disclosure | M — root-on-host trivially captures bridge traffic | L (Phase 1 boot only) → M (Phase 2 IPC payloads) | Encryption deferred; payload kept non-secret in Phase 1 |
| Inbound `br0` flood from QNX side or external | **D**enial of Service | M — no firewalling in `setup-bridge.sh`; bridge is open within host namespace | L — Linux kernel network stack absorbs reasonable load; M only at sustained line-rate | Bounded socket buffers; future: nftables on `br0` |
| Container/guest-kernel exploit reaching host | **E**levation of Privilege | L — Ubuntu kernel CVE patch latency; KVM hardened | H — full runtime-host compromise; *cyber-FuSa candidate* | Keep host & guest kernels patched; KVM isolation as trust boundary |

### 2.3 Host bridge `br0`

| Threat | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Misbehaving guest spoofs the *other* guest's MAC on the bridge | **S**poofing | H — Linux bridge does not validate source MAC by default; trivial with `ip link set address` inside a guest | M — peer guest receives forged frames; *cyber-FuSa candidate* in Phase 2 | Future: bridge MAC-filter / ebtables rules |
| Tampered bridge config (`brctl` / `ip link` after bring-up) | **T**ampering | M — anyone with `CAP_NET_ADMIN` on the host can reconfigure; SSH access = root in this lab | H — silent re-routing of all inter-VM IPC; *cyber-FuSa candidate* | Bridge bring-up by systemd unit; config diff tripwire (deferred) |
| Repudiation of bridge config changes | **R**epudiation | M — no auditd by default | L — single-developer scope | Future: auditd rules on `ip`/`brctl` |
| Promiscuous capture on `br0` | **I**nformation Disclosure | H — `tcpdump -i br0` is one command; bridge is by design a shared L2 domain | L (Phase 1) → M (Phase 2 once payloads carry semantically meaningful data) | Bridge is host-internal only; no external exposure; payload encryption deferred |
| Broadcast / ARP flood across bridge | **D**enial of Service | M — no storm control on Linux bridges by default | M — both guests degrade simultaneously; *cyber-FuSa candidate* (common-cause loss) | Future: Linux bridge `flood` controls / port rate limits |
| Bridge → host kernel pivot via L2 stack vuln | **E**levation of Privilege | L — Linux bridging is mature code | H — host kernel compromise = full collapse of trust model; *cyber-FuSa candidate* | Keep host kernel patched; bridge attack surface is the trusted base per §1 scope |

### 2.4 IFS build pipeline

| Threat | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Attacker authenticates to build host with stolen SSH key | **S**poofing | M — SSH key sits on dev workstation (Macbook); no hardware-backed key in Phase 1 | H — attacker can build & sign arbitrary IFS that the runtime host will boot trustingly | Future: hardware-backed SSH (Secure Enclave / YubiKey); `.ssh/config` hardening |
| Tampered `mkqnximage` inputs (build script, config, kernel-args) | **T**ampering | L — repo is single-developer git; PRs reviewed by self | H — silently malicious IFS reaches both twins; *cyber-FuSa candidate* (corrupted Safety guest = direct hazard) | Git history as audit; future: signed commits |
| Accidental commit of QNX SDK / IFS binary (NCEULA breach) | **R**epudiation / compliance | M — easy to mistype `git add`; `.gitignore` is conservative but not absolute | M — license breach (legal/operational impact, not safety); reputational | `.gitignore` covers `*.bin`/`*.img`/`*.vmdk`/`output/`/`qnx800/`; manual audit per Phase boundary (see §4) |
| `scp` of IFS over untrusted network leaks binary | **I**nformation Disclosure | L — scp uses SSH; AWS internal traffic only | M — NCEULA breach if intercepted blob redistributed | Default SSH transport; do not put IFS on public buckets |
| Build-host CPU starvation / runaway build | **D**enial of Service | L — single-tenant t3.medium | L — delayed build only; no safety impact | Cost discipline; teardown.sh |
| Compromised build host produces backdoored IFS | **E**levation of Privilege | L — t3.medium is single-purpose; hardened Ubuntu | H — every downstream guest boots untrusted code; *cyber-FuSa candidate* | Build host treated as part of TCB; future: ephemeral build host per release |

---

## 3. Secure-boot framing

The project does **not** implement a secure-boot chain. This section
exists so the gap is documented rather than glossed over.

| Layer | Real DRIVE OS | Cloud twin | HW twin |
|---|---|---|---|
| Hardware root of trust | Tegra fuses | None | Orin Nano fuses exist but not used by this project |
| First-stage bootloader | NVIDIA-signed | QEMU UEFI (unsigned) | JetPack UEFI (default) |
| OS kernel signature check | Yes | No | No (default JetPack does *measured* boot but the project does not extend it) |
| Hypervisor signature check | Yes | n/a (no HV) | n/a (no HV) |
| Guest IPL signature check | Yes | No (mkqnximage IFS, unsigned) | No (same IFS) |

**What the project can study (not implement):** the bootloader chain
paradigm itself, walked through in `skills/bsp-porting/` and the
forthcoming `skills/cybersecurity-21434/`.

---

## 4. NCEULA compliance audit

The QNX Everywhere NCEULA imposes specific redistribution constraints
that are **directly checkable in the repo**:

| Check | Pass criterion | Tool |
|---|---|---|
| No QNX SDK files committed | `find . -path ./.git -prune -o -size +50k -print` returns no QNX-derived files | one-liner |
| No QNX IFS / disk images committed | `git log --all --diff-filter=A --name-only` shows no `*.bin`, `*.img`, `*.vmdk` ever staged | git-fsck-equivalent |
| No QNX kernel / qcc-built ELFs | `find . -name '*.elf' -o -name '*.qnx*'` empty | grep |
| `.gitignore` covers all of the above | spot-check | manual |

The Cybersecurity Agent runs this audit at every Phase boundary.

---

## 5. Supply-chain hygiene

| Concern | Mitigation in this repo |
|---|---|
| AWS credentials leak via committed `.pem` | `.gitignore` excludes `*.pem`, `*.key`, `.env` |
| Hard-coded EC2 instance IDs in scripts | All scripts read from env or take args; `.ec2-instance-id` is `.gitignore`'d |
| Unauthenticated package install | `bootstrap-*.sh` uses `apt-get` (signed repos) only; no `curl | bash` patterns |
| Third-party github code injected without review | `joexue/qemu-virt` is the only third-party BSP candidate; pinned to a specific commit when used (Phase 2+) |

---

## 6. ISO/SAE 21434 framing (study-level)

The project's threat model and supply-chain hygiene map onto 21434
work-product categories like this — for *study* and interview
discussion, **not** as compliance evidence:

| 21434 work product | This project's analogue |
|---|---|
| TARA (threat analysis & risk assessment) | §2 STRIDE table above (qualitative, no risk values) |
| Cybersecurity concept | §1 scope + §3 secure-boot gap framing |
| Supplier capability evaluation | n/a — no suppliers; all components are open-source or under NCEULA |
| Vulnerability management | Project is personal; no real CVE intake; framing only |

The intent is that the project owner can fluently discuss what each
21434 work product *is* and how a real DRIVE OS programme would
produce it, without claiming to have produced one here.

---

## 2026-05-07 amendment — build-host pivot

> **Study-level only; not 21434 evidence. TARA here is illustrative,
> not the work-product a real programme would audit.**

The 2026-05-07 [findings.md](findings.md) entry pivots the primary
build host from "AWS t3.medium x86_64 Ubuntu" to "**local Windows
PC**", with EC2 retained as a documented fallback. As a side effect,
the dev workstation (formerly: Macbook macOS) and the build host
(formerly: separate EC2 instance) collapse into a **single Windows
machine** that now plays both roles. The runtime host (c7g.large
Graviton) is unchanged.

The detailed amendment to the threat catalogue — including the new
threat IDs **T22..T28**, the revised feasibility ratings for **T16,
T20, T21**, and the new asset **A11** (Windows user-profile
directory) — lives in [tara/phase1-cloud-tara.md](tara/phase1-cloud-tara.md)
under the same date heading. Only the STRIDE rows that change because
of the pivot are restated below; the §2 tables above are otherwise
unchanged.

The pivot is best understood as a **friction/cost optimisation whose
net security effect is non-obvious**: it removes the SSH-between-two-hosts
boundary and the entire EC2-build-host attack surface (IMDS, IAM-role,
keypair, snapshot exfiltration), but it adds Windows-native surfaces
(NTFS ACLs, Defender / SmartScreen telemetry, optional consumer
cloud-sync clients, Windows-native QNX SW Center installer supply
chain) and it concentrates source-tree + build-environment + IFS
production + scp credentials onto a **single foothold target**. See
the TARA amendment §H for the full honest-framing paragraph.

### Revised STRIDE rows (delta only)

The rows below replace the corresponding rows in §2.1–§2.4 *only when
the primary path (Windows build host) is in use*. The fallback path
(EC2 build host) retains the §2 ratings.

#### 2.4 IFS build pipeline — revised rows

| Threat | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Attacker authenticates to build host with stolen SSH key (revised: T16) | **S**poofing | **H** — single Windows PC holds private key, source tree, SDP install, and scp credentials in one place; `%USERPROFILE%\.ssh\` ACL hardening is not enforced by ssh on Windows the way 0600 is on POSIX | H — attacker can build & sign arbitrary IFS that the runtime host will boot trustingly, *and* ship it in the same session | Cyber-Design to specify; Cyber-Analysis does not propose |
| Build-host CPU starvation / runaway build (revised: T20) | **D**enial of Service | M — multi-tenant developer PC (browser, IDE, video calls) vs. previous single-purpose t3.medium | L — delivery delay only; integrity unaffected | Cyber-Design to specify |
| Compromised build host produces backdoored IFS (revised: T21) | **E**levation of Privilege | M — general-purpose Windows PC has materially broader attack surface than single-purpose hardened Ubuntu EC2 (web browsing, email, third-party software updates, USB, OEM utilities) | H — every downstream guest boots untrusted code; *cyber-FuSa candidate* | Cyber-Design to specify; treat build host as part of TCB |

#### 2.4 IFS build pipeline — new rows

| Threat | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| QNX Software Center Windows-native installer supply-chain compromise (T22) | **T**ampering | L — vendor-distribution attack; one-shot per release | H — malicious SDP install tree → backdoored IFS → *cyber-FuSa candidate* | Cyber-Design to specify |
| Windows Defender / third-party AV quarantines `mkqnximage` artefact mid-build, producing a truncated IFS (T23) | **T**ampering (against A1 integrity; non-malicious actor) | H — on-access scanning of large generated binaries is a known integrity-failure mode; no attacker required | H — corrupted Safety guest IFS may boot into a degraded state; *cyber-FuSa candidate* | Cyber-Design to specify; coordinate with FuSa-Design |
| OneDrive / Dropbox / iCloud-for-Windows silently syncs SDP install tree, repo, IFS, or `%USERPROFILE%\.ssh\` to a personal cloud account (T24) | **I**nformation Disclosure | H — default Windows installs increasingly redirect `Documents` to OneDrive without prominent UI; automatic / continuous | M — NCEULA breach (A8 / A1 redistribution) and key-material exposure if `.ssh` is in a synced root; chains into T16 | Cyber-Design to specify; coordinate with NCEULA audit (§4) |
| Windows local-privilege-escalation pivot into build pipeline (T25) | **E**levation of Privilege | M — known LPE attack surface from third-party services / UAC-bypass on consumer Windows | H — chains into T21; *cyber-FuSa candidate* | Cyber-Design to specify |
| NTFS ACL / Win32-OpenSSH key-permission mismatch exposes `%USERPROFILE%\.ssh\id_*` to other local accounts or services (T26) | **S**poofing | H — Win32-OpenSSH does not enforce 0600-equivalent permissions automatically; many tutorials skip the `icacls` step | M — chains into T16 / T21 once on runtime host | Cyber-Design to specify |
| Windows SmartScreen / Defender cloud-protection auto-submission of build artefacts to Microsoft (T27) | **I**nformation Disclosure | H — automatic by default for unfamiliar binaries on consumer Windows | M — NCEULA: blob copy on Microsoft infrastructure outside developer's licensed possession | Cyber-Design to specify; coordinate with NCEULA audit (§4) |
| Single-machine compromise yields source + build env + IFS production + scp credentials in one foothold (T28; topology blast-radius amplifier) | **E**levation of Privilege | H (post-foothold; gating rate is the upstream foothold threat) | H — *cyber-FuSa candidate*; structural delta from the Phase 0 two-host model | Cyber-Design to specify; modelling-choice question OQ-7 in TARA amendment |

### What this amendment does NOT demonstrate

- It remains a **study-level** STRIDE delta, not 21434 audit evidence.
- The new Windows-native ratings are **enumerated, not measured**. T23 (AV quarantine), T24 (cloud-sync), T26 (NTFS ACL drift), and T27 (SmartScreen submission) have not been verified against a default-configured Windows 11 build host in this repo. The ratings are expert-judgement, consistent with the rest of §2.
- The **net security delta** vs. the old EC2 topology has not been quantified. This amendment lists added surfaces; the TARA amendment §H lists removed surfaces. They are **not** netted into a single verdict, because doing so would require a probability-weighted attack-tree model the project does not have. The honest framing is: the pivot is a cost / friction optimisation whose security effect is non-obvious, and the single biggest open concern is the topology blast-radius concentration captured in T28.
