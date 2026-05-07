# Phase 5 — Security model (cybersecurity overlay)

> **Status:** scaffold. Phase 5 starts after Phase 4 (twin diff)
> lands so the threat model can be applied to a *measured* system,
> not a hypothetical one.

This document is the cybersecurity-overlay deliverable. It pairs with
the FuSa overlay (FMEA worksheets in `skills/fmea/examples/`) — both
are **study-level** artefacts, not certification evidence. The aim is
to demonstrate that the project can be discussed in ISO/SAE 21434 and
ISO 26262 vocabulary without overclaiming compliance.

---

## 1. Scope of analysis

Boundary of the system under analysis:

- The QNX Safety guest (in QEMU)
- The Linux Compute side (Ubuntu in QEMU on cloud twin; L4T native on HW twin)
- The IPC channel between them (virtio-net via host bridge `br0`)
- The host kernel (Linux on Graviton or L4T on Orin) — included as **trusted base**, not as part of attack surface
- The QNX IFS build pipeline on the cloud-twin x86_64 build host

Out of scope:

- AWS account-level security (IAM, network ACLs) — repo policy only states "do not commit `.pem`/`.env`"
- Physical security of the Orin Nano dev kit
- Any hypothetical CAN / Ethernet / wireless attack surface (none in this design)
- DRIVE OS production security posture (this is a personal project, not a customer engagement)

---

## 2. STRIDE threat model (per-component skeleton)

> Filled per component during Phase 5. Skeleton below; ratings are
> placeholders (`L/M/H`) until the agent walks through each entry.

### 2.1 QNX Safety guest

| Threat | STRIDE | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Spoofed `linux-client` connecting to `qnx-server` | **S**poofing | _TBD_ | _TBD_ | Static IP allow-list on QNX side; future: mTLS |
| Frame replay | **T**ampering | _TBD_ | _TBD_ | Sequence-number monotonicity check |
| Repudiation of message origin | **R**epudiation | _TBD_ | _TBD_ | Log sequence + timestamp pairs at server |
| Frame disclosure (eavesdrop on `br0`) | **I**nformation Disclosure | _TBD_ | _TBD_ | Threat is host-internal; encryption deferred |
| Flooding causing buffer exhaustion | **D**enial of Service | _TBD_ | _TBD_ | Rate limit on accept(); bounded queue |
| Privilege escalation via virtio-net driver | **E**levation of Privilege | _TBD_ | _TBD_ | QNX guest runs as least-privileged user; rely on QEMU isolation |

### 2.2 Linux Compute side

> _Same template applied. Filled in Phase 5._

### 2.3 Host bridge `br0`

> _Threat model focuses on whether a misbehaving guest can affect the
> other guest via the bridge. Filled in Phase 5._

### 2.4 IFS build pipeline

> _Threat model focuses on the cloud-twin build host: SSH key handling,
> NCEULA compliance, accidental binary commits. Filled in Phase 5._

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
