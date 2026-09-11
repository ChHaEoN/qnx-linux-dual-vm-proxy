# Phase-1 Gate — Cybersecurity Concept + Technical Cybersecurity Requirements (TCRs)

> **Study-level only; not 21434 evidence. Mechanisms specified here are
> illustrative; a real programme would have a far more developed
> key-management story.**

**Discipline / role:** Cyber-Design (ISO/SAE 21434 §9 Cybersecurity
Concept; §10 product-development requirement decomposition).
**Date:** 2026-06-11.
**Status:** Phase-1 gate deliverable. Responds to, and traces against,
the **Phase-1 Gate Addendum (2026-06-11)** in
[../tara/phase1-cloud-tara.md](../tara/phase1-cloud-tara.md) (threats
**T29–T34**, assets **A12–A17**, open questions **OQ-11…OQ-16**).

This artefact **designs** mitigations for threats already found by
Cyber-Analysis. It does **not** find new threats (that was the TARA's
job) and it does **not** prove the mitigations work (that is
Cyber-Verification's job — see §5 hand-off). Where a mechanism cannot be
implemented on the as-built TCG leg, it is marked
`study-only — would be implemented as <X> in a real programme`.

---

## 1. Scope & inputs

### 1.1 What this concept addresses

The as-built Phase-1 cloud leg (per the 2026-06-11 findings entry) is a
**QNX host running QHV (`qvm`) that boots a QNX guest under QEMU-TCG**,
on the **local Windows machine** (which is build host *and* runtime host
in this leg), with **networking inert** and **no Linux guest, no KVM, no
AWS**. The new attack surface is the **`qvm` software TCB** and its
config / image / boot-time-crypto inputs — *not* the `br0` bridge of the
TARA body.

This concept decomposes a Cybersecurity Goal per gate threat and writes
one or more TCRs against each:

| Gate threat | One-line | Risk (TARA) | Addressed here by |
|---|---|---|---|
| **T31** | PRNG-not-seeded yet `sshd` started → predictable/weak host & session keys (host **and** guest, common-cause) | 3 | **TCR-ENT-001** (load-bearing) + TCR-ENT-002 |
| **T29** | Malicious/malformed `g2.conf` (A13) → guest mis-isolation or qvm host fault | 4 | TCR-CFG-001, TCR-CFG-002 |
| **T32** | Tampered embedded guest image under `/data/hypervisor/` (A16) → qvm boots attacker-controlled partition | 4 | TCR-IMG-001 |
| **T34** | qvm resource-manager-arm failure → loss of Safety-partition availability | 4 | TCR-AVL-001 |
| **T30** | Guest→host escape across qvm vdev / EL2 boundary (A14/A15) | 3 | TCR-HYP-001 (hardening + honest residual) |
| **OQ-15 / OQ-12** | Secure-/measured-boot boundary at the `qvm` host | — | TCR-SB-001 (framing + study-only chain) |

### 1.2 Inputs consumed

- TARA gate addendum AA–AH: boundary delta, assets A12–A17, threats
  T29–T34, risk table AE, open questions OQ-11…OQ-16.
- Evidence:
  [../../logs/sample-boot/qhv-tcg-host-and-guest-boot.log](../../logs/sample-boot/qhv-tcg-host-and-guest-boot.log)
  — the `PRNG is not seeded` / `Could not initialize entropy` /
  `Unable to access /dev/random` lines on **both** host and guest,
  `---> Starting sshd` reached anyway, and
  `[g2.conf:9] Failed to arm a resource manager: Function not implemented`.
- [security-model.md](../security-model.md) §3 secure-boot gap table
  (currently "Guest IPL signature check: No") and §4 NCEULA audit.

### 1.3 Residuals explicitly deferred to Phase 3 (and why)

- **T30 hardware-isolation residual.** The vdev/EL2 partition boundary
  can be *hardened in software* here (TCR-HYP-001), but it **cannot be
  demonstrated as a real isolation boundary on the TCG leg**: TCG
  emulates EL2 on a laptop with no hardware root-of-trust, no fuse-backed
  measured boot, no real hardware partitioning, and no timing fidelity. A
  guest→host escape found here is a finding about the *qvm software*; the
  *absence* of one proves nothing about silicon. The hardware-isolation
  argument is therefore **deferred to Phase 3 (Orin / real EL2)**. See §4.
- **Trust-anchor location for image/config signing.** A no-RoT TCG leg
  has nowhere to root a hardware-backed signature chain. The verification
  *logic* (TCR-IMG-001, TCR-CFG-001, TCR-SB-001) is specifiable now; the
  *anchor* (Tegra fuses / measured boot) is **study-only** until Phase 3.
- **Remote-exploit latency of T31.** Networking is inert in this leg, so
  the *remote* path of T31 is latent — but the **defect is present in the
  image now** and goes live the instant networking comes up, so the
  entropy TCR is written as a Phase-1 requirement, not deferred.

> **2026-09-11 note.** Real EL2 now exists natively: Phase 3b runs `qvm` on
> the Orin, entered by kexec from L4T
> ([orin-native-port-plan.md](../orin-native-port-plan.md), architecture
> A4). That plan does no SMMU work (its §7 item 3), rules out reflash and
> UEFI-variable writes on its primary path (its §1 non-goals), and runs
> with Secure Boot
> disabled (its §3.1). It plans no fuse or measured-boot work. The T30
> hardware-isolation closure path and the trust-anchor location are
> UNKNOWN.

---

## 2. Cybersecurity Concept (security strategy for the QHV/qvm TCB)

**One-paragraph concept.** In the as-built leg the security-relevant
trust base collapses onto a small set of QHV software assets, and the
strategy is to protect each at its own layer rather than rely on a
hardware boundary the leg does not have. **`qvm` (A12) is the TCB root**:
its integrity *is* the partition-boundary integrity, so everything that
feeds it must be integrity-bound before it executes. The two integrity-
critical inputs are the **`g2.conf` configuration (A13)** — which defines
the guest memory map, vdev grants and image path, and is auto-generated
at host boot — and the **embedded guest image under `/data/hypervisor/`
(A16)** — which `qvm` boots *trustingly* today. The concept therefore
puts a **validate-before-use gate** in front of both: `g2.conf` is
schema-validated (and, study-only, signed) against a locked-down minimal
template before `qvm` consumes it, and the guest image is
signature-verified before launch, so a tampered config or image
(T29/T32, riding the Windows build-host threats T22–T28) is **rejected,
not booted**. The **vdev/EL2 boundary (A14/A15)** is hardened by
*minimising* the synthetic platform qvm presents (least-vdev), and the
**resource-manager-arm path (T34)** is made fail-deterministic so a
config- or guest-driven host fault degrades into a clean, observable
refusal rather than an ambiguous wedge. Finally, **entropy/PRNG state
(A17) is treated as a first-class security asset**: because it seeds host
*and* guest crypto and is observably failing at `sshd` start, the
concept makes a **seeded-PRNG precondition a hard gate** in front of
every key-generating/key-using service, failing those services *secure*
(not starting) rather than letting them emit predictable keys. The
recurring honest caveat: under TCG with no RoT, these mechanisms
demonstrate the **design discipline and the software-layer controls**,
not a hardware-isolated, attested system — that is Phase 3's job.

### 2.1 Asset → TCB-layer mapping

| Asset | Role in TCB | Protecting TCR(s) |
|---|---|---|
| **A12** `qvm` process (TCB root) | Partition boundary integrity & availability | TCR-HYP-001, TCR-AVL-001, TCR-SB-001 |
| **A13** `g2.conf` | Integrity-critical input (defines isolation) | TCR-CFG-001, TCR-CFG-002 |
| **A16** embedded guest image | Integrity-critical input (boot integrity) | TCR-IMG-001 |
| **A14/A15** vdev / EL2 boundary | The partition boundary itself | TCR-HYP-001 |
| **A17** host/guest entropy & PRNG | Seeds all derived key material | **TCR-ENT-001**, TCR-ENT-002 |

### 2.2 Trust-boundary assumptions

- The **Windows build/runtime host** is part of the TCB in this leg and
  carries the §A–§H surface (T22–T28). The integrity gates here reduce
  the *blast radius* of a build-host compromise (a tampered config/image
  is caught at launch) but do **not** remove the build-host as a trust
  dependency — see OQ-7 / T28 (single-machine blast radius).
- The `qvm` binary, `libhyp` and the QNX kernel `random` driver are
  trusted-as-shipped (closed-source, NCEULA); this concept can require
  *how they are invoked and gated*, not patch their internals.

---

## 3. Technical Cybersecurity Requirements (TCRs)

> ID convention: `TCR-<domain>-NNN`. IDs are **stable and unique** for
> Cyber-Verification and FuSa-Design traceability. Domains:
> `ENT` entropy, `CFG` config, `IMG` guest image, `AVL` availability,
> `HYP` hypervisor boundary, `SB` secure-boot.

### 3.1 Entropy / boot-time crypto — **T31** (Cybersecurity Goal: no key-using service ever runs against an unseeded PRNG)

> **This is the load-bearing TCR of this concept** — T31 is the only
> *concretely evidenced* defect in either Phase-1 gate addendum (cyber or
> FuSa NF-5). FuSa-Design cites **TCR-ENT-001** as a precondition for
> integrity-based safety mechanisms. The ID is fixed and must not be
> renumbered.

#### TCR-ENT-001 — Seeded-PRNG precondition gate for key-using services (fail-secure)

| Field | Value |
|---|---|
| **Parent Goal** | G-ENT: derived key material is never produced from a degenerate RNG |
| **Mitigates** | **T31** (≡ FuSa **NF-5**); asset **A17** |
| **Allocated component** | QNX host (`qnx-qhv`) and QNX guest (`qnx-guest`) startup sequence; `sshd` and any key-generating/key-using service |
| **Allocated mechanism** | Entropy-readiness gate + fail-secure refusal |

**Requirement text.** On **both** the QHV host and the guest, the system
SHALL NOT start `sshd` — or any service that generates or uses
cryptographic key material — until the kernel PRNG has been **seeded to
full strength** from a valid entropy source. If sufficient entropy is
**not** available at the point a key-using service would start, that
service SHALL **fail secure**: it SHALL NOT start and SHALL NOT generate,
load, or use any key, and the condition SHALL be logged as a security
event. The system SHALL NOT fall back to starting `sshd` against an
unseeded PRNG (the exact behaviour observed in the boot log:
`PRNG is not seeded` immediately followed by `---> Starting sshd`).

**Mechanism spec.**
- *What it does.* Inserts an explicit gate between "entropy
  initialisation" and "start key-using services" in the QNX startup
  script. The gate checks that a usable entropy source exists
  (`/dev/random` accessible **and** the PRNG reports seeded) before
  releasing `sshd`/key services.
- *When it triggers.* At every boot, on host and guest, before
  `---> Starting sshd`.
- *Fail-secure behaviour.* If the check fails, the gate **blocks**
  `sshd` start and emits a distinct log marker (e.g.
  `ENT-GATE: PRNG unseeded — sshd withheld (fail-secure)`), so the
  absence of `sshd` is observable rather than silent. The boot may
  continue for non-key services; **only** key-using services are
  withheld.
- *Entropy provisioning (answers OQ-13).* On this qemu-virt build the
  default source fails: `devr-virtio.so` is **rejected** as an entropy
  source and `/dev/random` is inaccessible. The required posture, in
  priority order:
  1. Provide a **working entropy source** before the gate — preferred:
     a virtio-rng / paravirtual RNG vdev presented by `qvm` to the
     guest, and a host-side RNG the QNX `random` driver accepts.
     *(study-only on the TCG leg: a real programme roots this in a
     hardware TRNG / RoT-seeded entropy; on Orin this becomes the Tegra
     hardware RNG — Phase 3.)*
  2. If (1) is unavailable, **block** key-using services (fail-secure) —
     this TCR's hard floor. **A withheld `sshd` is the correct outcome,
     not a regression.**
  3. **Do not** mask the problem with a fixed/seed-file or persisted
     host key generated under the unseeded condition — that reproduces
     the Debian-OpenSSL / factory-default-host-key damage class T31 cites.
- *Key-management story.* sshd host keys SHALL be **generated only after
  the gate passes**. Posture decision (OQ-13): **regenerate-per-boot from
  a properly-seeded PRNG is preferred over persisting a key** on this
  study leg, because a key persisted from a *first* unseeded boot would
  freeze a weak key into the image (worst case of T31). In a real
  programme the host key would be **provisioned from / wrapped by a
  hardware key store** (HSM / Tegra key slots) —
  `study-only — would be implemented as HSM-backed/fused-key provisioning
  in a real programme`. Until then: ephemeral, post-gate, full-entropy
  keys.
- *Assumptions about environment.* Assumes the startup script ordering is
  under project control (it is — the guest auto-start is already injected
  via `post_start.custom`), and that *some* entropy source can be made
  available or the service can be cleanly withheld.

**Cyber-FuSa interaction (FLAGGED — hand to FuSa-Analysis).** TCR-ENT-001
has a fail-secure failure mode that **withholds `sshd`**. If `sshd` (or
another key-using service gated here) is on a path that a safety
mechanism *depends on for availability* — e.g. FuSa-Design intends to use
the management channel or an integrity check that needs key material —
then "fail-secure = service withheld" converts a **confidentiality/
integrity control into an availability loss** of that path. T31 is also a
**common-cause** weakness (host *and* guest unseeded together), which is a
DFA pattern. **Action:** FuSa-Design must confirm that withholding a
key-using service on entropy failure does not itself create a safety
hazard; if it does, FuSa-Analysis owns the hazard and a *safe-state on
entropy failure* must be defined jointly. This is the primary cyber-FuSa
interaction item of this concept.

#### TCR-ENT-002 — Entropy-source health surfaced as a boot security signal

| Field | Value |
|---|---|
| **Parent Goal** | G-ENT |
| **Mitigates** | **T31** (detection/observability arm); asset **A17** |
| **Allocated component** | QNX host + guest logging (slogger2) |
| **Allocated mechanism** | Structured boot-time entropy-state log marker |

**Requirement text.** The system SHALL emit a **structured, parseable**
log record stating the entropy/PRNG state at the moment key-using
services are (or are not) released, on host and guest, so that the
seeded-vs-unseeded condition is machine-checkable post-boot rather than
inferred from incidental driver chatter. This makes TCR-ENT-001's gate
**verifiable** (see §5).

---

### 3.2 `g2.conf` integrity & validation — **T29** (Goal: `qvm` never consumes an unvalidated config that can mis-isolate the guest or fault the host)

#### TCR-CFG-001 — Validate `g2.conf` against a locked-down schema before `qvm` consumes it

| Field | Value |
|---|---|
| **Parent Goal** | G-CFG: the partition config that `qvm` executes is exactly the intended, minimal config |
| **Mitigates** | **T29** (mis-isolation + config-parser fault); contributes to **T34**; asset **A13** |
| **Allocated component** | The `post_start.custom` snippet that emits `g2.conf`; a validation step before `qvm @g2.conf` |
| **Allocated mechanism** | Generate-time schema validation against a minimal allow-list template |

**Requirement text.** Before `qvm @g2.conf` is invoked, the
auto-generated `g2.conf` (A13) SHALL be **validated against a
locked-down, minimal schema/template** that (a) pins the guest memory
window to the intended size and base, (b) enumerates *only* the vdevs the
guest is intended to receive (least-vdev — see TCR-HYP-001), and (c)
pins the guest-image path to the expected `/data/hypervisor/` location.
If validation fails, `qvm` SHALL NOT be launched (fail-closed); the boot
SHALL stop at a clear security-event marker rather than proceed with an
unvalidated config.

**Mechanism spec.**
- *What it does.* Turns the implicit, free-form generated config into a
  checked artefact: the generator is constrained to a template and the
  emitted file is diffed/validated against that template before use.
- *When it triggers.* At host boot, between config generation and
  `qvm @g2.conf`.
- *Why it matters here.* The boot log already shows a config directive
  reaching a privileged host path and faulting
  (`[g2.conf:9] Failed to arm a resource manager`) — concrete evidence
  that `g2.conf` directives reach privileged code and can fail there.
  Validation bounds *which* directives can ever be emitted.
- *Key-management / integrity story.* On this leg, integrity is by
  **construction + schema validation** (the config is generated locally
  from a pinned template, then checked). Cryptographic **signing** of
  `g2.conf` (answers OQ-11) is specified as the stronger posture:
  `study-only — would be implemented as a signed config validated against
  a key in a hardware-backed store before qvm consumes it`. On a no-RoT
  TCG leg there is no trustworthy anchor for the signature, so generate-
  time validation against a locked template is the implementable floor;
  signing activates when Phase 3 supplies a trust anchor.

#### TCR-CFG-002 — Restrict write access to the config generator and its output

| Field | Value |
|---|---|
| **Parent Goal** | G-CFG |
| **Mitigates** | **T29** (tamper precondition); assets **A13**, plus build-host surface T22–T28 |
| **Allocated component** | Host filesystem ACLs on `post_start.custom` + emitted `g2.conf` |
| **Allocated mechanism** | Least-privilege write protection on the config-generation path |

**Requirement text.** The `g2.conf` generator snippet and its output
SHALL be writable only by the privileged build/boot identity, so that a
non-privileged process cannot edit the directives `qvm` will execute.
*(On the Windows build host this is an NTFS-ACL / `icacls` obligation —
note it inherits the T26 "Win32-OpenSSH does not enforce 0600-equivalent"
weakness; `study-only — a real programme would enforce this via a
hardened, single-purpose build identity, not a consumer Windows account`.)*

---

### 3.3 Embedded guest-image integrity — **T32** (Goal: `qvm` boots only an authentic, unmodified guest partition image)

#### TCR-IMG-001 — Signature-verify the embedded guest image before qvm launch

| Field | Value |
|---|---|
| **Parent Goal** | G-IMG: the guest partition `qvm` boots is the one that was built and signed |
| **Mitigates** | **T32** (tampered `/data/hypervisor/` image); asset **A16**; inherits build-host T22–T28 (incl. T23 AV-quarantine truncation) |
| **Allocated component** | qvm host launch path / `post_start.custom`; verification step before `qvm @g2.conf` |
| **Allocated mechanism** | Cryptographic signature + integrity (hash) verification of the guest image, fail-closed |

**Requirement text.** Before `qvm` boots the embedded guest image under
`/data/hypervisor/` (A16), the host SHALL verify the image's
**cryptographic signature and integrity hash** against a trust anchor.
If verification fails — including the **non-malicious truncation** case
where AV (T23) or a partial write left a corrupted-but-bootable image —
`qvm` SHALL NOT boot the guest (fail-closed) and SHALL log a security
event. (Directly answers OQ-12 and closes the current
security-model.md §3 "Guest IPL signature check: No" gap for this leg's
guest image.)

**Mechanism spec.**
- *What it does.* Adds the missing guest-IPL integrity check: a
  detached signature over the guest image (or its manifest), verified at
  host boot before launch.
- *When it triggers.* At host boot, before `qvm @g2.conf`, after
  TCR-CFG-001 has pinned the image path.
- *Trust-anchor / key-management story (answers OQ-12).* The signing key
  pair is generated at build time; the **public verification key** is
  embedded in / pinned to the host image, and the guest image is signed
  with the private key on the build host. On the **TCG leg there is no
  RoT**, so the verification key is only as trustworthy as the host image
  carrying it — i.e. this demonstrates the *check*, not a *rooted* chain.
  `study-only — in a real programme the verification key chains to a
  hardware root of trust (Tegra fuses) and the guest image is verified by
  a measured-boot chain; on Orin (Phase 3) the anchor moves into
  silicon`. The build-time **private signing key** SHALL be held off the
  general-purpose Windows account in a real programme (HSM / fused key
  slot); on this leg it is `study-only` file-based.
- *Honest residual.* Because the anchor lives in the (mutable, on the
  build host) host image, an attacker who can rewrite the host image can
  also rewrite the embedded public key — so on the TCG leg this raises
  the bar against *guest-only* tampering but does **not** defeat a full
  build-host compromise (T28). That residual is the build-host /
  secure-boot problem, picked up by TCR-SB-001 and deferred to Phase 3.

---

### 3.4 qvm host bring-up availability — **T34** (Goal: a config- or guest-driven host fault degrades safely and observably, not into an ambiguous wedge)

#### TCR-AVL-001 — Deterministic, observable handling of qvm resource-manager-arm failure

| Field | Value |
|---|---|
| **Parent Goal** | G-AVL: loss of the Safety partition is bounded, detected, and signalled |
| **Mitigates** | **T34** (resource-manager-arm DoS); related to **T29**; asset **A12** |
| **Allocated component** | qvm host bring-up path; `post_start.custom`; the resource-manager arm step |
| **Allocated mechanism** | Fail-deterministic + healthcheck + signalled degradation |

**Requirement text.** A failure on the qvm host bring-up path — concretely
the evidenced `[g2.conf:9] Failed to arm a resource manager: Function not
implemented` — SHALL resolve to a **deterministic, signalled state**: the
host SHALL either (a) bring the guest partition up cleanly, or (b) refuse
and emit an explicit "guest partition unavailable" security/health event,
but SHALL NOT enter an **ambiguous partially-armed state** where the guest
may be running with a vdev or resource manager silently missing. The
arm-failure condition SHALL be detectable post-boot (not inferred from
incidental log text).

**Mechanism spec.**
- *What it does.* Wraps the resource-manager arm in an explicit
  success/failure check and a post-launch healthcheck of the guest
  partition's expected vdevs, so a missing arm is caught rather than
  tolerated.
- *Root-cause coordination (answers OQ-16).* The evidenced failure is
  ambiguous between (i) a **config-robustness** issue (a `g2.conf`
  directive that should never have been emitted — bounded by TCR-CFG-001)
  and (ii) a **build-completeness** issue (a missing package / unimplemented
  resource manager on this SDP build, cf. the 2026-06-10
  `target.qemuvirt` finding). This TCR requires the failure be *handled
  deterministically* regardless of which root cause; the build-completeness
  fix is a build-host action, not a runtime control.
- *Key-management story.* None — this is an availability/integrity-of-
  bring-up control, no key material involved.

**Cyber-FuSa interaction (FLAGGED).** "Loss of Safety-partition
availability" is a hazard pattern (TARA AF maps T34 ↔ T4 / HE-02/03/06).
The choice between "refuse and signal" vs. "degrade and continue" is a
**joint cyber-FuSa decision**: the safe state on qvm bring-up failure must
be defined with FuSa-Design, not by cyber alone. Hand the safe-state
definition to FuSa-Analysis/Design.

---

### 3.5 Guest→host vdev/EL2 boundary hardening — **T30** (Goal: minimise and harden the partition-escape surface; argue the residual honestly)

#### TCR-HYP-001 — Least-vdev synthetic platform + boundary-hardening posture (with honest TCG residual)

| Field | Value |
|---|---|
| **Parent Goal** | G-HYP: the guest→host escape surface is as small as the design allows; residual risk is stated, not hidden |
| **Mitigates (partially)** | **T30** (guest→host escape across A14/A15) |
| **Allocated component** | `g2.conf` vdev set; the synthetic `ARMv8_Foundation_Model` platform qvm presents |
| **Allocated mechanism** | Attack-surface minimisation (least-vdev) + accepted-residual framing |

**Requirement text.** The synthetic platform `qvm` presents to the guest
SHALL expose the **minimum set of vdevs** required for the guest to boot
and perform its function (least-vdev), enumerated and pinned via
TCR-CFG-001. Every vdev *not* required SHALL be absent from `g2.conf`, so
the trap-and-emulate surface reachable by hostile guest code is minimised.
The residual escape risk across the vdev/EL2 boundary SHALL be **documented
as accepted residual TCB risk for the TCG leg** and carried forward to
Phase 3.

**Mechanism spec.**
- *What it does.* Shrinks the attack surface of T30 by removing vdevs an
  attacker could target; it does **not** make the boundary unescapable.
- *Honest residual (answers OQ-14).* T30 is **enumerated, not attempted**
  in the TARA (no fuzzing, no exploit attempt, no qvm source review —
  closed-source/NCEULA). Under **TCG on a laptop the EL2 boundary is
  emulated**, so even a clean run here proves nothing about silicon
  isolation. The honest posture: harden by minimisation now, and treat
  the *isolation guarantee* the way §1.2 of the original TARA accepted
  KVM-escape (T5/T10/T15) — as **residual TCB risk**, explicitly deferred.
  `study-only — a real programme would harden this against silicon EL2
  with a hardware RoT in scope and a fuzzed/audited vdev backend`.
- *Key-management story.* None.

**Cyber-FuSa interaction (FLAGGED).** A guest→host escape collapses the
partition boundary = both partitions lost (CFI in TARA). Reducing the vdev
set could, in principle, remove a vdev a safety function relies on — so the
least-vdev list must be agreed with FuSa-Design so minimisation does not
strip a safety-relevant device. Joint review item.

---

### 3.6 Secure-/measured-boot boundary for the qvm host — **OQ-15** (Goal: name where the boot trust chain should anchor; close the §3 gap-table hypervisor row)

#### TCR-SB-001 — Establish the qvm host as the cloud-leg secure-boot boundary (framing + study-only chain)

| Field | Value |
|---|---|
| **Parent Goal** | G-SB: there is a defined, documented boot trust boundary that covers the hypervisor + the guest partition it launches |
| **Mitigates (framing)** | Trust-anchor dependency under **T29/T32**; answers **OQ-15** |
| **Allocated component** | qvm host image + boot chain; security-model.md §3 gap table (hypervisor row) |
| **Allocated mechanism** | Designate `qvm` host as the measured-boot boundary; chain config + guest-image verification to it |

**Requirement text.** The **`qvm` host image** SHALL be designated the
secure-/measured-boot boundary for the cloud leg, because it embeds and
launches the guest partition: a verified host image is the precondition
for trusting the in-host verification keys used by TCR-CFG-001 and
TCR-IMG-001. The security-model.md §3 secure-boot gap table SHALL be
updated to add a **hypervisor row for the cloud leg** (currently absent;
it predates the QHV pull-forward), recording the present state honestly:
host image **unsigned/unmeasured** on the TCG leg.

**Mechanism spec.**
- *What it does.* Names the trust boundary so the other integrity TCRs
  have a place to anchor, and makes the gap explicit in §3 instead of
  leaving the hypervisor row blank.
- *Honest residual.* On the TCG leg there is **no hardware RoT, no
  fuse-backed first-stage, no measured boot** — QEMU UEFI is unsigned. So
  this TCR **documents the boundary and the gap**; it does not implement a
  rooted chain. `study-only — would be implemented as a Tegra-fuse-rooted,
  measured-boot chain that verifies the qvm host image, which then verifies
  g2.conf and the guest image; on Orin (Phase 3) the anchor is silicon`.
- *Key-management story.* The verification keys for TCR-CFG-001/IMG-001
  ultimately chain to this boundary; with no RoT they are only as
  trustworthy as the host image. The full chain is **deferred to Phase 3**.

---

## 4. Deferred / residual risk

| Item | Residual | Why deferred | Re-activates |
|---|---|---|---|
| **T30 hardware isolation** | The vdev/EL2 partition boundary cannot be demonstrated as a *real* isolation boundary; TCG emulates EL2 on a laptop with no RoT, no measured boot, no hardware partitioning, no timing fidelity. TCR-HYP-001 hardens the *software* surface (least-vdev) but the isolation guarantee is **accepted residual TCB risk**. | A genuine isolation argument needs silicon EL2 + a hardware RoT in scope. Neither exists on this leg. | **Phase 3 (Orin / real silicon)** — fuzz/audit the vdev backend against real EL2. |
| **Trust anchor for signing** (TCR-CFG-001, TCR-IMG-001, TCR-SB-001) | The verification keys live in the (mutable) host image; no rooted chain. Defeats guest-only tampering, not a full build-host compromise (T28). | No-RoT TCG leg has nowhere to root a hardware-backed chain. | **Phase 3** — Tegra-fuse-rooted measured boot. |
| **HSM-backed key custody** (sshd host key, config/image signing keys) | Keys are file-based / ephemeral on a consumer Windows account; inherits T26 ACL weakness. | No HSM / hardware key store on this leg. | Real programme — HSM / fused key slots. |
| **T31 remote-exploit path** | The *defect* (unseeded crypto at sshd start) is present **now** and addressed **now** by TCR-ENT-001 — *not* deferred. Only the *remote reachability* is latent because networking is inert. | Networking did not come up in this leg. | The instant networking comes up — hence the TCR is a Phase-1 requirement. |

**Stated plainly:** T30's hardware-isolation claim is the one residual
this concept cannot retire on the TCG leg. It is **assigned to Phase 3**.
Everything else has an implementable software floor *now* with the
cryptographic/rooted upgrade marked `study-only`.

---

## 5. Hand-off to Cyber-Verification

Each TCR's evidence need is listed below. Cyber-Verification **plans and
runs** these; Cyber-Design does **not** perform verification here.

| TCR | Threat | Evidence Cyber-Verification should produce |
|---|---|---|
| **TCR-ENT-001** | T31 | **Entropy-gate test**: boot host+guest with the gate in place; assert `sshd` does **not** start while PRNG is unseeded (fail-secure), and **does** start once a working entropy source is provided. Negative test: confirm no host key is generated under the unseeded condition. Characterise actual seed entropy (the TARA notes this was *not* measured). |
| **TCR-ENT-002** | T31 | Parse the structured entropy-state log marker on host+guest; confirm it is present and machine-checkable at every boot. |
| **TCR-CFG-001** | T29 | **Fuzz the `g2.conf` parser/validator**: malformed/over-broad configs must be rejected before `qvm` launch (fail-closed). Confirm the locked-down schema rejects extra vdevs / oversized memory windows / wrong image paths. |
| **TCR-CFG-002** | T29 | Verify write-ACLs on the generator snippet + emitted config; attempt non-privileged edit and confirm refusal. |
| **TCR-IMG-001** | T32 | **Signature-check test**: tamper the embedded guest image (incl. a truncation to emulate T23 AV-quarantine) and confirm `qvm` refuses to boot it (fail-closed). Confirm a genuine image boots. |
| **TCR-AVL-001** | T34 | Drive the resource-manager-arm failure (and a config edge case via TCR-CFG-001 fuzzing); confirm a deterministic signalled state, no ambiguous partial-arm, and post-boot detectability. |
| **TCR-HYP-001** | T30 | **Pen-test / vdev-fuzzing plan** against the minimal vdev set (enumerated, honestly scoped: software surface under TCG only). Confirm absent vdevs are truly absent from the guest's synthetic platform. Document that escape *containment* is **not** provable on TCG. |
| **TCR-SB-001** | OQ-15 | Confirm the §3 gap table now carries an honest cloud-leg hypervisor row; verify (Phase 3) the rooted chain once silicon is available. |

**Cyber-FuSa interaction items flagged for joint review with FuSa-Design /
FuSa-Analysis** (do not resolve unilaterally):

1. **TCR-ENT-001 / T31** — fail-secure withholds `sshd`/key-using
   services; confirm this does not starve a safety mechanism that depends
   on that path. **Plus** T31 is **common-cause** (host+guest unseeded
   together) — a DFA pattern. FuSa-Design referenced TCR-ENT-001 as a
   precondition for integrity-based safety mechanisms; this is the primary
   join.
2. **TCR-AVL-001 / T34** — the safe state on qvm bring-up failure
   ("refuse + signal" vs "degrade + continue") is a joint cyber-FuSa
   decision; loss-of-Safety-partition-availability overlaps T4 /
   HE-02/03/06.
3. **TCR-HYP-001 / T30** — least-vdev minimisation must not strip a
   safety-relevant device; agree the vdev list with FuSa-Design.
```
