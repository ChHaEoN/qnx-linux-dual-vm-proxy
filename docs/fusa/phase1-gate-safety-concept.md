# Phase-1 Gate — Functional Safety Concept + Technical Safety Requirements

> **Study-level only; not certification evidence. Safety Goals here would not
> satisfy a real ISO 26262 audit.**
>
> This document is a Phase-1 study artefact for the qnx-linux-dual-vm-proxy
> Digital Twin project. It is modelled on ISO 26262 Part 3 (Functional Safety
> Concept) and Part 4 (Technical Safety Concept / Technical Safety Requirements),
> applied to a software-only, non-vehicle item that has no nominal driver, no
> road exposure, and (in this leg) no hardware acceleration. It produces **no
> safety case** and makes **no ASIL claim** about the deployed system. ASIL tags
> are carried forward from the FuSa-Analysis worksheet purely so traceability
> reads correctly; they are illustrative. Every mechanism below is paired with
> an explicit statement of what it does **not** demonstrate, per `CLAUDE.md`.

- **Role:** FuSa-Design (ISO 26262 Part 3/4/5/6 architect, study-level)
- **Date:** 2026-06-11
- **Input artefact:** [`skills/fmea/examples/phase1-cloud-bringup-fmea.md`](../../skills/fmea/examples/phase1-cloud-bringup-fmea.md) — **Phase-1 Gate Addendum (2026-06-11)**, failure modes NF-1…NF-9, Safety Goals SG-A1…SG-A7, DFA §A.4, hand-off §A.6 (OQ-A1…OQ-A7)
- **Evidence:** [`logs/sample-boot/qhv-tcg-host-and-guest-boot.log`](../../logs/sample-boot/qhv-tcg-host-and-guest-boot.log)
- **Architecture context:** [`docs/findings.md`](../findings.md) 2026-06-11 (QHV/TCG) + 2026-06-10 (IFS build / split VMDK)
- **Downstream consumers:** Implementation agent (briefs in §6), FuSa-Verification (evidence asks in §7), Cyber-Design (interaction items in §8)

---

## 1. Scope & inputs

### 1.1 As-built item this concept designs against

The Phase-1 cloud leg is, **as built**, a single QNX host (`qnx-qhv`, machine
`QEMU_virt`) running the QHV `qvm` Type-1 hypervisor, which hosts **one** QNX
guest (`qnx-guest`, synthetic machine `ARMv8_Foundation_Model`) under
**QEMU-TCG** pure emulation. There is **no KVM**, **no Linux guest**, and the
**network/IPC data path is inert** (host io-sock stack down, `qvm` run
no-network). The only realised partition boundary is the `qvm` synthetic
platform. This concept therefore designs mechanisms for the `qvm`/host-resource
boundary and the build→runtime artefact path — not for the (deferred) cross-VM
IPC data path.

### 1.2 Findings this concept addresses

| Finding | Short name | Safety Goal | Designed here? |
|---|---|---|---|
| **NF-1** | `qvm` config parse/validation failure → silently divergent guest | SG-A1 | Yes — TSR-CFG-001 |
| **NF-2** | vdev instantiation failure → guest degraded silently | SG-A2 | Yes — TSR-VDEV-001 |
| **NF-4** | Host resource manager fails to arm yet host proceeds | SG-A4 | Yes — TSR-RMGR-001 |
| **NF-6** | SMP PEs not awake → silent degraded core availability | SG-A6 | Yes — TSR-PE-001 |
| **NF-8** | Incomplete / split build artefact boots wrong image | SG-10 (extends K2) | Yes — TSR-PKG-001 |
| **NF-9** | Host net stack down → host-mediated channels dead on arrival | SG-A2 | Yes — TSR-NET-001 (degradation-annunciation only) |
| **NF-5** | PRNG never seeded (host + guest) | SG-A5 | **Assumption-of-use only** — owned by Cyber-Design (§3.3, §8); referenced as a precondition, not re-specified |

### 1.3 Findings explicitly deferred (no TCG evidence path)

| Finding | Short name | Safety Goal | Why deferred |
|---|---|---|---|
| **NF-3** | Guest escape / FFI breach across the synthetic-platform boundary | SG-A3 | Cannot be exercised on one host under TCG (FMEA §A.4). A single guest under emulation with no adversarial load is an isolation *architecture demo*, not an isolation *test*. Mechanism designed at concept level (§4, TSR-FFI-001) but **residual risk stays open**; closure routed to Phase 3 (Orin, real EL2/SMMU). |
| **NF-7** | TCG-only execution masks the timing/scheduling/acceleration failure class | SG-A7 | TCG is a functional emulator, not a timing model. **No** timing / FTTI / FFI claim may be asserted on TCG evidence. The concept's response is a *prohibition* (TSR-TIM-001), not a detector — see §4 and §5. |
| **DFA §A.4** | Shared EL2 host / shared CPU / shared resource-manager / shared entropy common-cause | — | Real DFA cannot be closed on the cloud leg; carried to Phase 3 as an assumption-of-use. |

These are recorded as **assumptions of use** and **deferred verification**, not
as discharged. This concept does not pretend TCG evidence can close them.

---

## 2. Functional Safety Concept (concept level)

The safety strategy for the QHV/`qvm` boundary in this leg is **fail-loud,
fail-safe bring-up**: every place where the Phase-1 evidence shows the system
came up **degraded but proceeded silently** is converted into an explicit,
detectable, annunciated condition that either blocks the next bring-up step or
transitions to a defined safe state, rather than continuing into a silently
divergent configuration. The boundary is not yet asked to deliver any timing or
isolation *guarantee* (TCG cannot back one); it is asked to be **honest about
its own state** at each bring-up checkpoint.

Concretely, the concept rests on four pillars, each serving Safety Goals carried
forward from the FuSa-Analysis worksheet:

1. **Configuration & resource integrity at launch** — a `qvm` configuration or
   vdev set that fails validation must **block guest start** rather than boot a
   divergent platform (SG-A1, SG-A2). Serves the boot-availability intent of
   SG-01 by making "what booted" trustworthy.
2. **Fail-loud host bring-up** — a host resource manager or network stack that
   fails to arm must annunciate a lost capability and drive a defined boot
   policy, not silently advertise a service it cannot back (SG-A4, SG-A2).
3. **Capacity honesty** — any later capacity/deadline argument must verify PE
   (core) availability **online**, never assume it from `-smp` config (SG-A6).
   This is an *enabling* requirement for Phase-3 timing work, not a timing claim
   itself.
4. **Build→runtime artefact integrity** — the image that boots must be
   cryptographically bound to the approved build artefact **and** verified
   package-complete and extent-complete (SG-10, extending the worksheet's K2).

A fifth, cross-cutting pillar is **integrity-mechanism honesty**: any safety
mechanism that relies on cryptographic freshness or integrity (relevant to
SG-03 / SG-04 when the IPC data path arrives in Phase 2) must declare an
explicit dependency on a **seeded PRNG**, which is **not** provided in this leg
(NF-5) and is **owned by Cyber-Design** as an entropy-before-use control. This
concept treats a seeded PRNG as a precondition (assumption of use), not as
something it provisions.

The concept deliberately asserts **no temporal or spatial FFI claim** on this
leg (SG-A7 prohibition). The `qvm` synthetic boundary is acknowledged as the
project's only partition-isolation *architecture*, with its residual-risk
argument written in §4/§5 and its *verification* deferred to Phase 3.

---

## 3. Safety-mechanism design overview

### 3.1 Mechanism catalogue

| SafMech | Mechanism class (ISO 26262-5/6 flavour) | Serves | Implementable on this leg? |
|---|---|---|---|
| **SM-CFG** | Configuration schema-validation gate before guest launch | SG-A1 | Yes (host-side script + `qvm` exit-code check) |
| **SM-VDEV** | vdev manifest reconciliation (declared-vs-instantiated) | SG-A2 | Yes (parse `qvm` startup output / expected-vdev list) |
| **SM-RMGR** | Resource-manager arm-success gate + fail-loud boot policy | SG-A4 | Yes (parse host startup, assert each RM armed) |
| **SM-PE** | Online PE-count check vs. configured core count | SG-A6 | Yes (`pidin`/syspage PE-awake probe at host + guest) |
| **SM-PKG** | Build-time package-completeness + per-extent checksum/integrity gate | SG-10 | Yes (build-host script, already partly exists for Orin) |
| **SM-NET** | Host-service degradation annunciation (not provisioning) | SG-A2 | Yes (annunciate-only; cannot fix io-sock here) |
| **SM-FFI** | Partition-boundary residual-risk argument + assumption-of-use | SG-A3 | **Architecture only** — verification deferred to Phase 3 |
| **SM-TIM** | Prohibition control: forbid timing/FFI claims on TCG | SG-A7 | Yes as a *process/gate* control; not a runtime mechanism |

### 3.2 Diagnostic-coverage assumption framing

For the implementable mechanisms (SM-CFG, SM-VDEV, SM-RMGR, SM-PE, SM-PKG,
SM-NET) the **diagnostic coverage assumption** is *detection of the catalogued
cause at bring-up*, not run-time fault coverage. None of these mechanisms is a
continuous online monitor in this leg; they are **bring-up checkpoint** gates.
Quantified DC (low/medium/high per ISO 26262-5 Annex D) is **not** claimed here
— that is FuSa-Verification's FMEDA task (§7). What is claimed is *observability*:
each mechanism converts a previously-silent degraded state into a detectable,
logged, blocking event.

### 3.3 Assumption-of-use dependency on Cyber-Design (NF-5)

Any mechanism in this concept that would later rely on cryptographic integrity
or freshness (notably the future SG-03 freshness counter and SG-04 payload
integrity layer designed in Phase 2) carries the following **assumption of
use**:

> **AoU-ENTROPY:** No integrity- or freshness-dependent safety mechanism may be
> *claimed effective* until a seeded PRNG / cryptographic-quality entropy source
> is demonstrated available on the relevant instance (host and guest). The
> provisioning of that entropy source is **owned by Cyber-Design** — concretely
> **`TCR-ENT-001`** (seeded-PRNG fail-secure gate for key-using services,
> responding to NF-5 / Cyber threat T31). FuSa-Design does
> **not** re-specify this control; it references it as a precondition and flags
> it as a cyber-FuSa interaction item (§8).

The Phase-1 evidence shows this precondition is **currently unmet** on both
instances (`PRNG is not seeded`, `Could not initialize entropy`), so any SG-04-
class integrity mechanism is, today, **born weak** — which is exactly why it is
gated behind AoU-ENTROPY rather than claimed.

---

## 4. Technical Safety Requirements (TSR table + specs)

> TSR IDs are unique and stable so FuSa-Verification can trace them. Parent SG
> and (illustrative) ASIL are carried from the FuSa-Analysis worksheet. FTTI
> values are **bring-up budgets** at the checkpoint, expressed in study-level
> terms; on the TCG leg FTTI is wall-clock at bring-up, **not** a real-time
> deadline (TCG cannot represent one — see TSR-TIM-001).

| TSR ID | Parent SG | ASIL (illus.) | FTTI (study) | Mitigates | Allocated component | Allocated SafMech |
|---|---|---|---|---|---|---|
| **TSR-CFG-001** | SG-A1 | B | Pre-launch (block before guest start) | NF-1 | host launch wrapper + `g2.conf` | SM-CFG |
| **TSR-VDEV-001** | SG-A2 | B | Guest-init checkpoint | NF-2 | `qvm` vdev model + host post-start check | SM-VDEV |
| **TSR-RMGR-001** | SG-A4 | B | Host-init checkpoint | NF-4 | `qnx-qhv` host startup + policy gate | SM-RMGR |
| **TSR-PE-001** | SG-A6 | C | Host- and guest-init checkpoint | NF-6 | host + guest syspage probe | SM-PE |
| **TSR-NET-001** | SG-A2 | B | Host-init checkpoint | NF-9 | host io-sock init + annunciator | SM-NET |
| **TSR-PKG-001** | SG-10 | B | Build-time + pre-launch | NF-8 (extends K2) | build-host packaging + runtime verify | SM-PKG |
| **TSR-FFI-001** | SG-A3 | D | (deferred — Phase 3) | NF-3 | `qvm`/synthetic-platform boundary | SM-FFI |
| **TSR-TIM-001** | SG-A7 | D | (process gate) | NF-7 | concept/process; CI gate | SM-TIM |

### TSR-CFG-001 — Config schema-validation gate before guest launch

- **Requirement text:** The host launch path shall validate the `qvm`
  configuration (`g2.conf`) against an expected schema/resource manifest, and a
  configuration that fails validation — including any directive reported as
  unapplied (e.g. `Failed to arm a resource manager: Function not implemented`)
  — shall **block guest start** rather than proceed with a silently divergent
  resource set. The block shall be logged with the failing directive.
- **Mitigates:** NF-1.
- **SafMech (SM-CFG):** Pre-launch validator parses `g2.conf`, checks each
  declared resource/vdev against an allow-list and against the running build's
  capability set; the launch wrapper inspects `qvm` startup output for
  per-directive failure lines and refuses to declare bring-up complete if any
  declared directive did not take effect.
- **When it triggers:** before/at `qvm @g2.conf`, at the host post-start
  checkpoint.
- **DC assumption:** detection of the catalogued config-divergence cause at
  bring-up; not a run-time monitor.
- **What it does NOT demonstrate:** it does not prove the *applied* config is
  itself safe — only that what was requested matches what took effect. It does
  not validate `qvm` internal correctness, and on TCG it cannot show the
  resulting platform behaves correctly under load.

### TSR-VDEV-001 — vdev manifest reconciliation

- **Requirement text:** The set of virtual devices the guest depends on shall be
  enumerated in a manifest; absence of any manifested vdev at guest init shall be
  **detectable and annunciated**, not silently degraded. A guest that boots
  missing a manifested vdev shall not be reported as a nominal bring-up.
- **Mitigates:** NF-2.
- **SafMech (SM-VDEV):** declared-vs-instantiated reconciliation — the launch
  wrapper compares the manifest against the vdevs `qvm` actually instantiated and
  against guest-side presence checks (e.g. `vtnet0` existence when net is
  manifested). Mismatch ⇒ annunciate + non-nominal status.
- **When it triggers:** guest-init checkpoint.
- **DC assumption:** detection of a missing manifested vdev at bring-up.
- **What it does NOT demonstrate:** it does not exercise the vdev under traffic
  (the net path is inert this leg), so it proves *presence*, not *correct
  function*. Function-under-load coverage is Phase 2.

### TSR-RMGR-001 — Resource-manager arm-success gate + fail-loud policy

- **Requirement text:** Each host resource manager the bring-up depends on shall
  report successful arming; a resource manager that fails to arm (e.g. `Failed to
  arm a resource manager: Function not implemented`) shall cause the host to
  **annunciate the lost capability and apply a defined boot policy** (fail-loud /
  enter a restricted safe-state for the dev twin), and shall **not** leave the
  host advertising a capability it cannot provide.
- **Mitigates:** NF-4.
- **SafMech (SM-RMGR):** arm-success assertion list parsed from host startup; a
  policy table maps each unarmed RM to {block, degrade-announced, ignore-by-
  exception}. Default is **block/announce**; any "ignore" entry is an explicit,
  reviewed exception (the dev-twin allowance).
- **When it triggers:** host-init checkpoint, before guest auto-start.
- **DC assumption:** detection of the unarmed-RM cause at host bring-up.
- **What it does NOT demonstrate:** it does not repair the missing RM (e.g. it
  cannot make io-sock initialise on this build); it makes the degradation
  *loud*, not *absent*. The OQ-A1 policy decision — whether the dev twin is
  *allowed* to proceed degraded — is recorded here as **annunciate-and-allow for
  the dev twin only**, with the same condition treated as **block** on any leg
  that asserts a safety claim.

### TSR-PE-001 — Online PE-count check before any capacity claim

- **Requirement text:** The number of processing elements (cores) actually
  online shall be verified at host and guest init and compared against the
  configured count (`-smp`); any capacity or deadline argument shall be predicated
  on the **online** PE count, never the configured count. A shortfall (e.g.
  `CPU 0/1 PE is not awake`) shall be annunciated and shall invalidate any
  capacity claim that assumed the configured count.
- **Mitigates:** NF-6.
- **SafMech (SM-PE):** syspage / `pidin` PE-awake probe at both instances;
  emits online-PE count to the bring-up log; a downstream capacity argument that
  cites a core count must cite *this* value.
- **When it triggers:** host- and guest-init checkpoints.
- **DC assumption:** detection of PE-shortfall at bring-up.
- **What it does NOT demonstrate:** it is an **enabling** requirement for Phase-3
  timing work. It does **not** itself make any timing/deadline claim (forbidden
  on TCG by TSR-TIM-001). It proves how many cores are awake, not that they meet
  any deadline.

### TSR-NET-001 — Host-service degradation annunciation

- **Requirement text:** Failure of the host network stack to initialise shall be
  **annunciated** so that any host-mediated channel (future health / heartbeat /
  telemetry) that assumes host networking is known to be dead on arrival rather
  than silently absent. A bring-up worked around by running `qvm` no-network
  shall be recorded as **net-degraded**, not nominal.
- **Mitigates:** NF-9.
- **SafMech (SM-NET):** annunciation-only — parse host startup for
  `network stack down` / `Address family not supported`; set a `net-degraded`
  bring-up flag consumed by any later channel-availability assumption.
- **When it triggers:** host-init checkpoint.
- **DC assumption:** detection of host-net-down at bring-up.
- **What it does NOT demonstrate:** it does **not** fix io-sock and does not
  provision a working channel; it makes the absence explicit. Any safety
  mechanism that would ride host networking is therefore **gated** on clearing
  this flag (an assumption of use for Phase 2/3).

### TSR-PKG-001 — Build→runtime package-completeness + integrity gate

- **Requirement text:** The image executed at runtime shall be (a) built from a
  **complete** package set (the required startup binary, e.g. `startup-qemu-virt`
  via `target.qemuvirt`, present), and (b) cryptographically bound to the
  approved build artefact across **every** extent of the boot media, including
  the split-VMDK descriptor **and** its separate raw extent. A missing startup
  binary, a missing extent, or a checksum mismatch shall **block launch**.
- **Mitigates:** NF-8 (extends worksheet K2 / SG-10).
- **SafMech (SM-PKG):** build-time completeness check (assert startup binary
  present before declaring build success) + per-extent `sha256sum` manifest
  generated at build and re-verified at runtime, covering the 169-byte
  `monolithicFlat` descriptor and the ~150 MB raw extent as **separate** checksum
  targets.
- **When it triggers:** build-time (completeness) and pre-launch (integrity).
- **DC assumption:** detection of incomplete/corrupt/mismatched artefacts at the
  build→runtime boundary.
- **What it does NOT demonstrate:** it binds *identity and completeness*, not
  *functional correctness* of the image; a complete, intact, wrong-but-matching
  config still boots. It also does not establish a signing trust root (that is a
  Cyber-Design secure-boot concern, not duplicated here).

### TSR-FFI-001 — Partition-boundary residual-risk argument (deferred verification)

- **Requirement text:** A fault within the guest partition shall not propagate to
  the `qnx-qhv` host or to any sibling partition (freedom from interference).
  **On the cloud/TCG leg this requirement is asserted at architecture level only
  and its verification is deferred**: TCG-on-one-host cannot demonstrate spatial
  isolation (no real MMU/SMMU stage-2, no real EL2 trap cost) or temporal
  isolation (no contention model). Closure is routed to Phase 3 (Orin, real
  EL2/SMMU) fault injection.
- **Mitigates:** NF-3 (residual risk **open**).
- **SafMech (SM-FFI):** the `qvm` synthetic-platform boundary is the *mechanism*
  (the guest sees `ARMv8_Foundation_Model`, not the host `QEMU_virt`); the
  **assumption of use** is that hardware-enforced stage-2 isolation backs it on
  real silicon. No diagnostic is claimed on this leg.
- **DC assumption:** none claimed on TCG (explicitly).
- **What it does NOT demonstrate:** the two distinct machine banners prove a
  software partition *architecture*, **not** containment of a fault from one
  partition to another (NF-3 untested). This is the project's only FFI claim and
  it is **not discharged** here.

### TSR-TIM-001 — Prohibition: no timing/FFI claim on TCG evidence

- **Requirement text:** No timing, scheduling, FTTI, or hardware-partition-
  isolation claim shall be asserted, in any artefact, on the basis of TCG-only
  execution. Boot "passing" under TCG is a **functional** result only. Any such
  claim shall be routed to a Phase-3 (Orin / real EL2-KVM, or metal) evidence
  path.
- **Mitigates:** NF-7 (supersedes the cloud-leg visibility of Q6 / H1 / N3).
- **SafMech (SM-TIM):** a *process/gate* control — a CI / review gate that
  rejects any artefact asserting a timing or FFI guarantee citing only TCG
  evidence. Not a runtime mechanism.
- **DC assumption:** n/a (process control).
- **What it does NOT demonstrate:** this is a guardrail against false
  confidence, not a positive safety property. It does not make the timing
  hazards go away — it keeps them **visible as open** until real silicon exposes
  them.

---

## 5. Deferred / open residual risk

The following are **not discharged** by this concept and remain open residual
risk, carried as assumptions of use to Phase 3 (Orin, real EL2/KVM/SMMU):

| Item | Safety Goal | Disposition | Where it closes |
|---|---|---|---|
| **NF-3** guest escape / spatial+temporal FFI | SG-A3 (TSR-FFI-001) | Architecture-only on this leg; **residual risk open**. A single emulated guest under no adversarial load is not an isolation test. | Phase 3 fault injection on real EL2/SMMU |
| **NF-7** TCG masks timing/scheduling/acceleration class | SG-A7 (TSR-TIM-001) | Addressed by **prohibition**, not detection. Timing hazards Q6/H1/N3 are invisible here, not retired. | Phase 3 (KVM/Orin) or metal |
| **DFA §A.4** shared EL2 host / shared CPU / shared RM / shared entropy common-cause | — | Real DFA cannot be closed on the cloud leg. | Phase 3 DFA |
| **NF-5** unseeded PRNG (precondition for any integrity mechanism) | SG-A5 / SG-04 | **Owned by Cyber-Design** (AoU-ENTROPY → **`TCR-ENT-001`**). FuSa-Design references it as a precondition; does not provision it. | Cyber-Design `TCR-ENT-001`; integrity mechanisms unlocked in Phase 2 once met |

Stating these plainly: the cloud/TCG leg **cannot** demonstrate hardware-
enforced partition isolation or any real-time timing property. Designing
TSR-FFI-001 and TSR-TIM-001 here documents *intent and discipline*; it does
**not** constitute evidence that the properties hold.

---

## 6. Implementation brief (hand-off to Implementation agent)

Concrete asks for the Implementation agent. All paths absolute. These are
bring-up checkpoint gates that wrap the existing QHV launch path; none requires
modifying QNX internals.

1. **`E:\Project\qnx-linux-dual-vm-proxy\scripts\qhv\verify-bringup.sh`** (new)
   — single host-side bring-up verifier consuming the serial/boot log and
   emitting a structured bring-up status. Suggested signatures:
   - `assert_config_applied <g2_conf_path> <boot_log>` → TSR-CFG-001 (fail if any
     `Failed to arm a resource manager` / unapplied directive).
   - `reconcile_vdevs <vdev_manifest> <boot_log>` → TSR-VDEV-001.
   - `assert_rmgrs_armed <rmgr_manifest> <boot_log> <policy_table>` → TSR-RMGR-001.
   - `check_pe_online <expected_smp> <boot_log>` → TSR-PE-001 (parse
     `CPU N PE is not awake`).
   - `annunciate_net_state <boot_log>` → TSR-NET-001 (set `net-degraded` flag).
   - Exit non-zero (block) on any TSR-CFG-001 / TSR-RMGR-001 / TSR-PKG-001
     failure; annunciate-and-continue (dev-twin policy) on TSR-NET-001 /
     TSR-VDEV-001 / TSR-PE-001, with the degraded flag recorded.
2. **`E:\Project\qnx-linux-dual-vm-proxy\scripts\build-qnx-ifs.bat`** (extend) —
   add a **package-completeness assertion** (startup binary present, e.g.
   `startup-qemu-virt`) before declaring build success → TSR-PKG-001(a).
3. **`E:\Project\qnx-linux-dual-vm-proxy\scripts\qhv\artifact-manifest.sh`** (new)
   — generate a per-extent `sha256` manifest covering **both** the `.vmdk`
   descriptor and the raw extent; re-verify pre-launch → TSR-PKG-001(b).
   `gen_manifest <artifact_dir> > manifest.sha256` /
   `verify_manifest <artifact_dir> <manifest.sha256>`.
4. **Manifests** (new, under `E:\Project\qnx-linux-dual-vm-proxy\scripts\qhv\`):
   `vdev.manifest`, `rmgr.manifest`, `rmgr-policy.table` — the expected-vdev /
   expected-RM / per-RM-policy inputs the verifier reads.
5. **AoU-ENTROPY gate (stub):** any future integrity/freshness module must check
   a `prng-seeded` precondition flag before claiming effectiveness — coordinate
   the flag's producer with Cyber-Design (do **not** implement entropy
   provisioning here).

---

## 7. Hand-off to FuSa-Verification (evidence each TSR will need)

FuSa-Verification owns *proving* these; this section only names the evidence
class, it does not perform the verification.

| TSR | Verification evidence class | Notes for FMEDA / fault-injection |
|---|---|---|
| TSR-CFG-001 | Fault injection: feed a malformed/unsupported `g2.conf`; assert guest start is **blocked** and logged | Closeable on TCG |
| TSR-VDEV-001 | Fault injection: drop a manifested vdev; assert annunciation + non-nominal status | Closeable on TCG (presence only; function-under-load → Phase 2) |
| TSR-RMGR-001 | Fault injection: force an RM arm-failure; assert policy applied (block/announce) | Closeable on TCG |
| TSR-PE-001 | Boot with fewer awake PEs than `-smp`; assert shortfall annunciated and capacity claims invalidated | Closeable on TCG (count only; timing → Phase 3) |
| TSR-NET-001 | Confirm `net-degraded` flag set when io-sock down; confirm downstream channels gated | Closeable on TCG |
| TSR-PKG-001 | Corrupt one extent / omit startup binary; assert build/launch **blocks**; checksum-mismatch test | Closeable on build host |
| TSR-FFI-001 | **Deferred → Phase 3**: spatial/temporal isolation fault injection on real EL2/SMMU. **Do not attempt to close on TCG.** | FMEDA invalid on TCG |
| TSR-TIM-001 | Process-gate audit: confirm no artefact asserts timing/FFI on TCG-only evidence | Audit, not fault injection |

**Re-scoping note (carried from FMEA §A.6):** NF-3, NF-7, and the §A.4 DFA are
**not closeable on the cloud/TCG leg**. Any FMEDA or fault-injection result for
TSR-FFI-001 or any timing claim must come from a Phase-3 (Orin, real EL2/KVM,
real stage-2) evidence path. Closing FFI or a timing claim against TCG evidence
would be invalid.

---

## 8. Cyber-FuSa interaction items (pair-review with Cyber-Design)

Flagged at the phase boundary per `CLAUDE.md` (any safety mechanism whose
failure mode introduces, or depends on, an attack-surface item):

1. **NF-5 / AoU-ENTROPY → Cyber `TCR-ENT-001` (ownership: Cyber-Design).** The unseeded PRNG on host
   **and** guest is owned by Cyber-Design as an entropy-before-use control (`TCR-ENT-001`).
   FuSa-Design's SG-04-class integrity mechanisms (Phase 2) **depend** on it.
   Interaction: a FuSa integrity mechanism built before this control is in place
   would be *born weak* — a safety mechanism failure that is simultaneously a
   cyber weakness. **Agenda item #1** for the gate.
2. **TSR-NET-001 / NF-9.** Annunciating host-net-down is also a cyber-relevant
   signal: a future host-mediated health/heartbeat channel is a new attack
   surface once it exists. Joint review of whether that channel needs
   authentication (Cyber-Design) when it is built in Phase 2.
3. **TSR-PKG-001 / NF-8 / K2.** This concept binds *identity + completeness* via
   checksums but explicitly does **not** establish a signing trust root — that is
   Cyber-Design's secure-boot / artefact-signing concern. Interaction: checksum
   integrity without a trust root is tamper-evident, not tamper-proof. Confirm
   the division of labour so SG-10 isn't double-counted or under-covered.
4. **TSR-FFI-001 / NF-3 (carried from FMEA §A.6 cyber-FuSa list, recharacterised
   H4).** The shared EL2 host / `qvm` common-cause is both a freedom-from-
   interference (safety) and an elevation-of-privilege (cyber) concern. Joint
   residual-risk argument needed at Phase 3.

---

## 9. Traceability summary

| Finding | Safety Goal | TSR | SafMech | Status |
|---|---|---|---|---|
| NF-1 | SG-A1 | TSR-CFG-001 | SM-CFG | Designed (closeable on TCG) |
| NF-2 | SG-A2 | TSR-VDEV-001 | SM-VDEV | Designed (presence-only on TCG) |
| NF-4 | SG-A4 | TSR-RMGR-001 | SM-RMGR | Designed (closeable on TCG) |
| NF-6 | SG-A6 | TSR-PE-001 | SM-PE | Designed (count-only; enabling for Phase 3) |
| NF-9 | SG-A2 | TSR-NET-001 | SM-NET | Designed (annunciate-only) |
| NF-8 | SG-10 | TSR-PKG-001 | SM-PKG | Designed (closeable on build host) |
| NF-3 | SG-A3 | TSR-FFI-001 | SM-FFI | Architecture-only; **residual open → Phase 3** |
| NF-7 | SG-A7 | TSR-TIM-001 | SM-TIM | Prohibition control; **residual open → Phase 3** |
| NF-5 | SG-A5/SG-04 | (AoU-ENTROPY) | — | **Assumption of use; owned by Cyber-Design** |

8 TSRs total: 6 closeable on this leg, 2 (TSR-FFI-001, TSR-TIM-001) designed but
with residual risk deferred to Phase 3. NF-5 carried as an assumption of use,
not a TSR FuSa-Design owns.
