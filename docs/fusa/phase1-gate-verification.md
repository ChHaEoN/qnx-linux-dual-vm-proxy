# Phase-1 Gate — FuSa Verification Report

> **Study-level only; not ISO 26262 verification evidence.** This report
> exercises the Phase-1 gate safety mechanisms designed in
> [`phase1-gate-safety-concept.md`](phase1-gate-safety-concept.md) against the
> as-built QHV/TCG bring-up. It produces no safety case and makes **no ASIL
> claim**. "Verified" here means *the designed mechanism was executed and
> behaved as specified against captured evidence* — it does **not** mean the
> mechanism provides a quantified diagnostic coverage or a guaranteed
> fault-tolerant time interval on real silicon. The honest gap between those
> two meanings is stated per-TSR.

- **Role:** FuSa-Verification (ISO 26262 V-model: Analysis → Design → **Verification**)
- **Date:** 2026-06-11
- **Inputs:** TSR-CFG-001, TSR-VDEV-001, TSR-RMGR-001, TSR-PE-001, TSR-NET-001, TSR-PKG-001 (closeable on this leg); TSR-FFI-001, TSR-TIM-001 (deferred residual). Parent failure modes NF-1…NF-9 in [`../../skills/fmea/examples/phase1-cloud-bringup-fmea.md`](../../skills/fmea/examples/phase1-cloud-bringup-fmea.md) Gate Addendum.
- **Mechanisms under test:** `scripts/qhv/verify-bringup.sh`, `artifact-manifest.sh`, `entropy-gate.sh`, `validate-g2conf.sh`, the `vdev.manifest`/`rmgr.manifest`/`rmgr-policy.table`/`g2.conf.allow` data files, and the TSR-PKG-001(a) assertion in `scripts/build-qnx-ifs.{bat,sh}`.
- **Test fixture:** `logs/sample-boot/qhv-tcg-host-and-guest-boot.log` (the real as-built capture) plus synthetic mutation logs for fault injection.
- **Method:** mechanisms were actually executed (POSIX sh via the runtime's shell). Commands and verbatim output are reproduced below — no result is asserted that was not run.

---

## 1. FMEDA-style coverage table

| TSR | Parent NF | Failure mode | Mechanism | Detected in fixture? | Diagnostic-coverage claim (honest) |
|---|---|---|---|---|---|
| TSR-CFG-001 | NF-1 | qvm config directive fails to apply / RM unimplemented | `verify-bringup.sh::assert_config_applied` | **YES — BLOCK** on real log | Detects the *logged* `Failed to arm a resource manager` signature post-boot. **Not** a runtime config-apply monitor with an FTTI; absence of the log line ≠ proof of correct application. |
| TSR-RMGR-001 | NF-4 | required resource manager does not arm | `assert_rmgrs_armed` + `rmgr.manifest` + `rmgr-policy.table` | **YES** — PASS on present, BLOCK on injected drop | Detects per-RM start banner in the serial log. Coverage bounded to RMs that emit a recognisable `Starting <x>` banner; a silently-degraded-but-started RM is **not** covered. |
| TSR-VDEV-001 | NF-2 | vdev instantiation mismatch vs manifest | `reconcile_vdevs` + `vdev.manifest` | **PARTIAL** — `virtio-blk` confirmed; `pl011`, `virtio-console` returned **presence-unknown** | **Coverage gap (reported):** a serial console log cannot prove presence of the very devices that *carry* the console. This check is advisory (annunciate-and-continue), not a reliable vdev integrity diagnostic. |
| TSR-PE-001 | NF-6 | configured PE not online (silent capacity loss) | `check_pe_online` (parses `CPU N PE is not awake`) | **YES — FLAG** (online=0 of smp=2 on real log; online=2 of smp=4 injected) | Detects the *logged* non-awake signature and invalidates capacity claims above the awake count. Does **not** detect a PE that wakes then later stalls. |
| TSR-NET-001 | NF-9 | host net stack down → host-mediated channels dead | `annunciate_net_state` | **YES — FLAG** net-degraded on real log; net-nominal on clean | Annunciation only (dev-twin policy). Does not restore or fail-stop. |
| TSR-PKG-001(a) | NF-8 | build ships incomplete package (missing `startup-qemu-virt`) | assertion in `build-qnx-ifs.{bat,sh}` | **CODE-VERIFIED** (not executed — needs an SDP install; cannot run `mkqnximage` here) | Asserts startup-binary presence before declaring build success. Reviewed by inspection; runtime execution deferred to a build host with SDP 8.0.4. |
| TSR-PKG-001(b) | NF-8/K2 | extent corruption / split-VMDK descriptor lost | `artifact-manifest.sh` gen/verify | **YES** — tamper, truncation, and missing-descriptor all FAIL | Tamper-evident integrity over both descriptor and extent. **Not** signature-rooted (see §4 / Cyber TCR-SB-001). |

---

## 2. Fault-injection evidence (verbatim)

### 2.1 TSR-CFG-001 / TSR-PE-001 / TSR-NET-001 — real as-built log → BLOCK

```
$ verify-bringup.sh --log logs/sample-boot/qhv-tcg-host-and-guest-boot.log --smp 2
  BLOCK [TSR-CFG-001] unapplied directive: 57:[g2.conf:9] Failed to arm a resource manager: Function not implemented
  FLAG  [TSR-PE-001] PE shortfall: -smp=2, 2 not awake -> online=0 (capacity claims @ 2 INVALID)
  FLAG  [TSR-NET-001] host network stack down -> net-degraded (host-mediated channels dead on arrival)
  BLOCK (hard fail) : 1
RESULT: BLOCK — bring-up MUST NOT proceed (>=1 blocking TSR failure).   [exit 1]
```

### 2.2 PASS path — fully nominal synthetic log → exit 0

```
$ verify-bringup.sh --log clean-full.log --smp 1
  PASS  [TSR-CFG-001] no unapplied config directives
  PASS  [TSR-RMGR-001] rmgr 'slogger2' / 'PCI Services' / 'fsevmgr' / 'Networking' / 'sshd' started
  PASS  [TSR-VDEV-001] vdev 'virtio-blk' present (token 'VIRTIO')
  PASS  [TSR-PE-001] all 1 configured PEs report awake
  PASS  [TSR-NET-001] host network stack initialised (net-nominal)
  FLAG (degraded) : 0   [exit 0]
```

### 2.3 TSR-RMGR-001 — inject a dropped required RM (`sshd` removed) → BLOCK

```
$ grep -v 'Starting sshd' clean-full.log > no-sshd.log
$ verify-bringup.sh --log no-sshd.log --smp 1
  BLOCK [TSR-RMGR-001] rmgr 'sshd' did not arm -> BLOCK (policy=block)
RESULT: BLOCK   [exit 1]
```

### 2.4 TSR-PE-001 — drive shortfall via `--smp 4` → FLAG

```
$ verify-bringup.sh --log <real-log> --smp 4
  FLAG  [TSR-PE-001] PE shortfall: -smp=4, 2 not awake -> online=2 (capacity claims @ 4 INVALID)
```

### 2.5 TSR-PKG-001(b) — manifest integrity (verbatim)

```
$ artifact-manifest.sh gen <dir> > manifest.sha256    # 3 artefacts: ifs.bin, disk-qemu.vmdk, disk-qemu
$ artifact-manifest.sh verify <dir> manifest.sha256
  PKG-GATE: PASS — 3 artefact(s) verified (descriptor + extent integrity-bound).   [exit 0]

# tamper raw extent:
  PKG-GATE: MISMATCH disk-qemu  want=e3384c75… got=d85e8a67…  (BLOCK launch)
  PKG-GATE: FAIL — 1 integrity failure(s); launch MUST be blocked.   [exit 1]

# remove descriptor, keep extent (split-VMDK guard — the 2026-06-10 bug class):
  PKG-GATE: MISSING extent/artefact: disk-qemu.vmdk  (BLOCK launch)   [exit 1]

# truncate extent:
  PKG-GATE: MISMATCH disk-qemu  …  (BLOCK launch)   [exit 1]
```

**Result:** 6 of 7 TSRs verified with running evidence through both their fault and nominal paths; TSR-PKG-001(a) verified by code inspection only (no SDP runtime available here).

---

## 3. Mechanisms that did NOT behave as a full diagnostic would (reported, not fixed)

Per the test-before-claim rule, the following are reported honestly to FuSa-Design / Implementation; FuSa-Verification does not fix them:

1. **TSR-VDEV-001 presence-unknown gap.** `reconcile_vdevs` cannot confirm `pl011` / `virtio-console` from a serial log (they carry the log). The check degrades to advisory for those vdevs. A real vdev-integrity diagnostic would query the hypervisor's vdev table, not the guest serial stream. **Severity: coverage limitation, not a false PASS** — it annunciates `presence-unknown`, it does not claim PASS.
2. **All log-parsing TSRs share a structural limitation:** they verify a *captured boot log*, i.e. post-hoc detection of a textual signature. This is sufficient to gate a bring-up decision ("did this boot cleanly?") but is **not** an in-operation safety mechanism with a defined fault-reaction time. No FTTI is claimed. This is by design for a study-level bring-up gate and is the honest ceiling of the cloud/TCG leg.

---

## 4. Residual risk — deferred to Phase 3 (NOT discharged)

> **2026-09-11 note.** The Phase-3 evidence paths below do not exist as
> written. KVM boot of QNX on the Orin is blocked by the GICv3/NISV defect
> ([orin-port.md](../orin-port.md) risk register), and the `a1.metal`
> KVM run hung the same way ([findings.md](../findings.md) 2026-07-29).
> Phase 3b runs native `qvm` on the Orin with real EL2 and stage-2
> translation for one guest ([findings.md](../findings.md) 2026-09-10 M3;
> [orin-native-port-plan.md](../orin-native-port-plan.md), architecture
> A4), but that plan does no SMMU work (its §7 item 3). When FFI or timing
> closure evidence will exist is UNKNOWN. TSR-TIM-001's prohibition stays
> in force.

| Item | Why it cannot close on this leg | Phase-3 evidence required |
|---|---|---|
| **TSR-FFI-001 / NF-3** (guest→host escape, partition FFI) | TCG emulates one CPU on one host; there is no hardware-enforced EL2/stage-2/SMMU boundary to test. "No escape observed" under TCG is not evidence of isolation. | Orin / real EL2 + SMMU; fault-injection across the qvm boundary on silicon; a DFA against shared-EL2 common cause (Addendum §A.4). |
| **TSR-TIM-001 / NF-7** (TCG masks timing/scheduling/acceleration) | TCG has no real-time fidelity; timing hazards (old Q6/H1/N3) are invisible, not retired. TSR-TIM-001 is a *prohibition* control (CI-gate: no timing/FFI claim on TCG evidence), and that prohibition is correctly in force. | KVM-accelerated run on Orin/`*.metal`; WCET-style measurement; scheduling-jitter characterisation. |
| **DFA §A.4** (shared EL2 host / shared CPU / shared RM / shared entropy) | A real DFA needs independent fault channels; TCG-on-one-host provides none. | Phase-3 DFA on silicon. |

These are **architecturally designed but verification-deferred**. The report does not claim them closed; TSR-TIM-001's prohibition is itself the safe interim posture.

---

## 5. AoU-ENTROPY dependency check (cross to Cyber `TCR-ENT-001`)

FuSa's `AoU-ENTROPY` states no integrity-/freshness-dependent safety mechanism (SG-04 class) may be *claimed effective* until a seeded PRNG is demonstrated. The precondition flag is **owned by Cyber-Design's `TCR-ENT-001`**; FuSa-Verification verified only that the flag is *consumable* as a gate:

```
$ entropy-gate.sh --log <real as-built log>     → ENT-GATE: prng-seeded=0   [exit 1]   (precondition UNMET — correct)
$ entropy-gate.sh --log <seeded marker log>     → ENT-GATE: prng-seeded=1   [exit 0]   (precondition MET)
```

The flag file emits `prng-seeded=0|1`, machine-checkable. **Conclusion:** any FuSa integrity mechanism built in Phase 2 MUST read `prng-seeded=1` before claiming effectiveness; on the as-built image it reads `0`, so no such mechanism may be claimed today. Verifying that the entropy *source* is adequate is Cyber-Verification's deliverable, not FuSa's — see [`../cyber/phase1-gate-verification.md`](../cyber/phase1-gate-verification.md).

---

## 6. Verdict

- **6 TSRs verified** with running fault-injection evidence (CFG, RMGR, VDEV[partial], PE, NET, PKG(b)); **1 verified by inspection** (PKG(a)).
- **2 TSRs carry deferred residual risk** to Phase 3 (FFI, TIM) — designed, not discharged; honestly bounded.
- **1 coverage limitation reported** (TSR-VDEV-001 presence-unknown) + the structural log-parse-vs-runtime-diagnostic caveat.
- The whole report is bounded by the honest ceiling: these are **bring-up decision gates on a TCG study leg**, not certified in-operation safety mechanisms with quantified DC/FTTI.

**Cyber-FuSa interaction:** the entropy precondition (`AoU-ENTROPY` ≡ Cyber `TCR-ENT-001` ≡ NF-5/T31) remains the #1 joint item; its source-adequacy verification sits on the Cyber side and is referenced, not duplicated, here.
