# skills/fmea — Failure Mode and Effects Analysis

> **Phase 0 study notes** — paradigm only. Worked examples land in `examples/`
> after each Phase milestone. Not a certification artifact.

---

## When to use

- Before a bring-up: enumerate what can fail at each layer (boot, virtio-net,
  IPC heartbeat, sync). Decide where to instrument.
- After an incident: post-hoc analysis to capture the failure mode, effect,
  cause chain, and corrective action.
- Before a phase milestone: sanity-check that the test plan exercises the
  highest-RPN failure modes.

## Why

FMEA forces **structured thinking under uncertainty**. The discipline of
naming each failure mode and scoring Severity × Occurrence × Detection makes
hidden assumptions visible, and gives a defensible reason to spend test
effort *here* rather than *there*.

## Scope (in vs. out)

**In scope for this repo:**
- Design FMEA (D-FMEA) of the proxy IPC and bring-up path
- Process FMEA-lite (P-FMEA) of the EC2 + QEMU launch flow
- Severity / Occurrence / Detection scoring on a small 1–5 scale
  (we don't pretend to have AIAG-VDA-grade calibration data)

**Out of scope:**
- Formal AIAG-VDA-traceable FMEAs (would require team review + sign-off)
- Functional Safety FMEDA (requires a safety case — not done here)

## Key references (study only)

- AIAG-VDA FMEA Handbook, 1st ed., 2019 — primary methodology source
- ISO 26262-5 (Hardware) — for FMEDA framing only, not applied here
- IEC 60812 — Failure modes and effects analysis (FMEA and FMECA), 2018

## Files

- [`template.md`](template.md) — empty FMEA worksheet (Item / Function /
  Failure Mode / Effect / Cause / S·O·D / RPN / Action)
- `examples/` (Phase 1+) — worked examples drawn from real bring-ups

---

## Study notes

- **D-FMEA vs P-FMEA**: D-FMEA targets *what could fail in the design*;
  P-FMEA targets *what could fail in the manufacturing/deployment process*.
  For software, the analogue of P-FMEA is build/release pipeline analysis.
- **RPN (Risk Priority Number) = S × O × D**. AIAG-VDA 2019 deprecates pure
  RPN ranking in favor of "Action Priority" tables (High/Medium/Low). For
  this repo's lightweight use we keep RPN as a sortable single number but
  flag this as a known divergence from the current handbook.
- **Detection (D)** is often misunderstood — it's "how likely we catch it
  *before release*," not "how likely we catch it after deploy."

## Applied to this project

(Empty in Phase 0; populated in `examples/` per phase. First entry expected
after Phase 1: `examples/phase-1-bringup-fmea.md`.)
