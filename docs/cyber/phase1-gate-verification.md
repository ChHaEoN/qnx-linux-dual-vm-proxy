# Phase-1 Gate — Cyber Verification Report

> **Study-level only; not ISO/SAE 21434 verification evidence.** This report
> exercises the Phase-1 gate security mechanisms designed in
> [`phase1-gate-cybersecurity-concept.md`](phase1-gate-cybersecurity-concept.md)
> against the as-built QHV/TCG bring-up. "Verified" means *the designed
> mechanism was executed and behaved as specified against captured evidence*
> — it does **not** assert a quantified residual risk or an audited security
> case. Where a control's real-world strength depends on a Root of Trust that
> does not exist on the TCG leg, that gap is stated explicitly.

- **Role:** Cyber-Verification (21434 V-model: Analysis → Design → **Verification**)
- **Date:** 2026-06-11
- **Inputs:** TCR-ENT-001 (load-bearing), TCR-CFG-001/002, TCR-IMG-001, TCR-AVL-001, TCR-HYP-001, TCR-SB-001. Parent threats T29–T34 in [`../tara/phase1-cloud-tara.md`](../tara/phase1-cloud-tara.md) Gate Addendum.
- **Mechanisms under test:** `scripts/qhv/entropy-gate.sh`, `validate-g2conf.sh`, `artifact-manifest.sh`, `verify-bringup.sh`, `g2.conf.allow`.
- **Test fixture:** `logs/sample-boot/qhv-tcg-host-and-guest-boot.log` + synthetic adversarial inputs.
- **Method:** mechanisms actually executed; commands + verbatim output below. A small g2.conf fuzz harness was run. No result asserted that was not run.

---

## 1. TCR-ENT-001 — seeded-PRNG fail-secure gate (LOAD-BEARING, threat T31)

T31 is the only *concretely evidenced* defect from the gate analysis: the as-built
log shows `PRNG is not seeded` yet `sshd` starts. TCR-ENT-001 requires that no
key-using service start against an unseeded PRNG (fail-secure). Verified through
both states:

```
$ entropy-gate.sh --log <real as-built log>
  ENT-GATE: PRNG unseeded - sshd withheld (fail-secure)
  ENT-GATE: prng-seeded=0   [exit 1]          ← REFUSE: correct, the defect state withholds sshd

$ entropy-gate.sh --log <seeded-marker log>
  ENT-GATE: prng-seeded=1
  ENT-GATE: entropy precondition MET - key-using services may start   [exit 0]

$ entropy-gate.sh --live          (this host)
  ENT-GATE: prng-seeded=1   [exit 0]          ← live /dev/random readable + entropy_avail ok
```

**Verdict: PASS.** The gate fails secure on the evidenced defect (would withhold
sshd, preventing the predictable-host-key / Debian-OpenSSL damage class) and
permits only on positive seeded evidence. The `prng-seeded=0|1` flag is the
machine-checkable precondition that FuSa's `AoU-ENTROPY` consumes
(cross-ref [`../fusa/phase1-gate-verification.md`](../fusa/phase1-gate-verification.md) §5).

**Honest gap:** the gate *withholds* services; it does **not** *provision*
entropy. On the as-built image the precondition stays UNMET — the correct fix
(a real entropy source: virtio-rng wired through, or the Tegra hardware TRNG on
Orin) is Phase-2/Phase-3 work. Until then the safe posture is "sshd withheld",
which is availability-reducing by design.

---

## 2. TCR-CFG-001 — `g2.conf` validation fuzz harness (threat T29)

A fuzz harness threw legitimate and adversarial configs at `validate-g2conf.sh`
against the locked `g2.conf.allow`:

| Input | Intent | Result | Exit |
|---|---|---|---|
| `g2.good.conf` (as-built no-net config) | legitimate | **ACCEPT** | 0 |
| `g2.passthru.conf` (`vdev passthru`) | DMA/passthrough escape surface | **REJECT** — `forbidden vdev type 'passthru'` | 1 |
| `g2.exec.conf` (`exec /bin/sh`) | arbitrary host command | **REJECT** — `forbidden directive 'exec'` | 1 |
| `g2.net.conf` (`vdev virtio-net`) | reintroduce inert/forbidden net path (least-vdev) | **REJECT** — `forbidden vdev type 'virtio-net'` | 1 |
| `g2.garbage.conf` (4 KB of `A`) | malformed/oversized line | **REJECT** — `forbidden directive 'AAAA…'` | 1 |
| `nonexistent path` | input error | **REJECT** | 2 |
| **`g2.empty.conf` (zero bytes)** | contentless config | **REJECT** *(initial run ACCEPTed — see CV-1, now fixed)* | 1 |

**Verdict: PASS. One finding (CV-1) was raised on first run and has since been fixed and re-verified — see below.**

### 🟢 FINDING CV-1 (RAISED then FIXED + re-verified): empty `g2.conf` was accepted (fail-open edge)

**Status: CLOSED 2026-06-11.** Raised by this verification pass, fixed by
Implementation (required-directive floor added to `validate-g2conf.sh`), and
re-verified here.

`validate-g2conf.sh` enforces an **allow-list** — it rejects any line whose
keyword/vdev-type is not permitted. An **empty** config contains *no forbidden*
directives, so it passes (exit 0). The validator verifies *absence of the
forbidden* but never asserts *presence of the required* (`system`, `load`,
`cpu`, at least one boot vdev). A zero-byte or comment-only `g2.conf` would
satisfy the gate yet cannot launch a valid guest — and, more importantly for
21434, an attacker who can **truncate** the generated config to empty defeats
the validate-before-use intent without tripping the gate. This is a
fail-**open** edge in a control whose whole job is to fail closed.

- **Class:** completeness gap (validate-forbidden-absence, not required-presence).
- **Fix:** `validate-g2conf.sh` now enforces a **required-directive floor** —
  `system`, `ram`, `cpu`, `load` must each appear and at least one `vdev` must be
  declared; any missing one is a fail-closed violation alongside the forbidden
  ones. (V-model note: the finding was raised by Verification and fixed by
  Implementation; this re-verification only confirms closure.)
- **Re-verification (verbatim):**

```
=== regression: legitimate + forbidden cases unchanged ===
g2.good.conf      -> ACCEPT (exit 0)
g2.passthru.conf  -> REJECT (exit 1)  forbidden vdev type 'passthru'
g2.exec.conf      -> REJECT (exit 1)  forbidden directive 'exec'
g2.net.conf       -> REJECT (exit 1)  forbidden vdev type 'virtio-net'
=== CV-1 fix: incomplete configs now fail closed ===
g2.empty.conf     -> REJECT (exit 1)  missing required directive 'system' (… ram, cpu, load, no vdev)
g2.comments.conf  -> REJECT (exit 1)  missing required directive 'system'
g2.trunc.conf     -> REJECT (exit 1)  missing required directive 'load'
g2.noload.conf    -> REJECT (exit 1)  missing required directive 'load'
```

  A truncate-to-empty (or truncate-past-`load`) attack on the generated config
  now trips the gate. This composes with — and does not replace — the deferred
  config-integrity controls (TCR-IMG-001 / TCR-CFG-002 hash/ACL over `g2.conf`),
  which would additionally bind the config against in-place tampering.

---

## 3. TCR-IMG-001 — guest-image / artefact integrity (threat T32)

```
$ artifact-manifest.sh gen <dir> > manifest.sha256       # ifs.bin + disk-qemu.vmdk + disk-qemu
$ artifact-manifest.sh verify <dir> manifest.sha256
  PKG-GATE: PASS — 3 artefact(s) verified (descriptor + extent integrity-bound).   [exit 0]

# tampered extent  → MISMATCH disk-qemu … (BLOCK launch)      [exit 1]
# missing .vmdk    → MISSING extent/artefact: disk-qemu.vmdk  [exit 1]
# truncated extent → MISMATCH disk-qemu … (BLOCK launch)      [exit 1]
```

**Verdict: PASS** for tamper-evidence over both the descriptor and the raw
extent (closing the 2026-06-10 split-VMDK class).

**Study-only gap (explicit):** a SHA-256 manifest is **tamper-evident, not
tamper-resistant**. It detects accidental corruption and an attacker on an
*untrusted transport* who cannot also rewrite the manifest. It does **not**
stop an attacker with write access to both the image and `manifest.sha256` —
that requires a signature rooted in a hardware Root of Trust (the deferred
**TCR-SB-001** / secure-boot anchor, Phase 3 / Orin). The mechanism itself
prints this caveat: `manifest is tamper-evident only; RoT-rooted signing is
study-only (TCR-SB-001)`.

---

## 4. TCR-AVL-001 — deterministic handling of qvm arm failure (threat T34)

T34 is the availability/DoS surface evidenced by
`Failed to arm a resource manager: Function not implemented`. TCR-AVL-001
requires this resolve to a deterministic, signalled state rather than an
ambiguous continue. Verified via `verify-bringup.sh` on the real log:

```
  BLOCK [TSR-CFG-001] unapplied directive: 57:[g2.conf:9] Failed to arm a resource manager: Function not implemented
  RESULT: BLOCK — bring-up MUST NOT proceed.   [exit 1]
```

**Verdict: PASS** — the arm failure is resolved to a deterministic BLOCK, not
silently ignored. (Honest scope: this gates the *bring-up decision*; it is not
an in-operation watchdog with a reaction time. Shared boundary with FuSa
TSR-CFG-001 — same evidence, safety + availability lenses.)

---

## 5. TCR-HYP-001 — least-vdev (threat T30, partial)

Least-vdev is enforced at the **config-validation** layer: `g2.conf.allow`
omits `virtio-net` and `passthru`, and §2 shows both are rejected. **Verdict:
PASS at the config layer.** This bounds *which* vdevs may be declared — it does
**not** verify runtime isolation of the vdevs that *are* present. The actual
guest→host escape threat (**T30**) across the vdev/EL2 boundary is **not**
testable here (§6).

---

## 6. Pen-test plan + residual (deferred to Phase 3)

| Threat | Why untestable on TCG leg | Phase-3 pen-test |
|---|---|---|
| **T30** guest→host escape across qvm vdev/EL2 boundary | TCG synthesises the boundary in software on one host; "no escape" under TCG is not evidence of hardware isolation | On Orin/`*.metal`: fuzz the virtio-blk/console vdev backends from a hostile guest; attempt stage-2 / SMMU bypass; measure blast radius of a guest crash on the `qnx-qhv` host. |
| **TCR-SB-001** secure-boot / signed `g2.conf` + signed guest image | no RoT / fused key / measured boot on the TCG leg | Tegra secure-boot chain; signature verification against a fused key before `qvm` consumes config/image. |
| **TCR-CFG-002** filesystem ACL on `post_start.custom` + emitted `g2.conf` | not meaningfully exercisable on the build-host scratch tree; belongs on the runtime QNX host | Verify least-privilege write perms on the config-generation path on the deployed host. |

These residuals are honestly **open**, not closed. T30 in particular is the
canonical hypervisor threat and the project's single most-deferred claim.

---

## 7. NCEULA + supply-chain audit

| Check | Result |
|---|---|
| Any QNX binary / IFS / disk image tracked in git? | **NONE** — `git ls-files` matches no `*.ifs/*.bin/*.vmdk/*.img/disk-qemu/procnto/startup-*`. NCEULA-clean (scripts + logs only). |
| `.gitignore` guards build artefacts? | **YES** — `*.bin`, `**/ifs*.bin`, `**/disk-qemu.*`, `qnx800/`, mkqnximage build trees all ignored. |
| `scripts/qhv/` tracked content | scripts + data files only (`*.sh`, `*.manifest`, `*.table`, `g2.conf.allow`, `README.md`, `post_start.custom`). |
| Supply-chain build integrity | TSR-PKG-001(a) package-completeness assertion (`startup-qemu-virt` present) + (b) per-extent manifest give a build→runtime integrity chain. **Gap:** the chain is checksum-rooted, not signature-rooted — see §3 / TCR-SB-001. |

**Audit verdict: PASS** (NCEULA hygiene intact; supply-chain controls present at
the implementable floor, signing deferred).

---

## 8. Verdict summary

- **5 TCRs verified** with running evidence (ENT-001, CFG-001, IMG-001, AVL-001, HYP-001[config-layer]); **TCR-CFG-002 / TCR-SB-001** deferred to the runtime host / Phase 3.
- **1 fail-open finding raised & closed: CV-1** — empty `g2.conf` was accepted (required-presence not asserted); fixed via a required-directive floor in `validate-g2conf.sh` and re-verified (regression-clean).
- **Residuals honestly open:** T30 hardware isolation, RoT-rooted signing — Phase 3 / Orin.
- **NCEULA + supply-chain audit: PASS.**
- **Cyber-FuSa interaction items confirmed:** TCR-ENT-001 (≡ FuSa NF-5/AoU-ENTROPY) verified fail-secure and its flag confirmed consumable by FuSa; TCR-AVL-001 shares evidence with FuSa TSR-CFG-001 (availability + safety lenses on the same arm-failure).
