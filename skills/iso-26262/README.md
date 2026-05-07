# skills/iso-26262 — Functional Safety (study scope)

> **Phase 0 study notes** — paradigm and study scope only.
> ⚠️ This repo produces **no** ISO 26262 work products and makes **no** ASIL claim.
> Cited part numbers are pointers, not reproductions of normative text.

---

## When to (study) this

- When the JD or interview asks about safety-critical SW lifecycle
- When framing the *gap* between this software proxy and a real DRIVE OS
  Safety partition (which targets ASIL-D)
- When sketching how a future, real safety case would be structured

## Why

Understanding the lifecycle and ASIL decomposition concepts lets you talk
about NVIDIA DRIVE OS / QOS positioning credibly *without* claiming
compliance you haven't earned. The honest framing is the win.

## Scope (in vs. out)

**In scope (study):**
- ISO 26262:2018 Parts 1–12 — what each part is for, at one paragraph each
- Safety lifecycle: concept → product development (system → HW → SW)
  → production → operation → decommission
- ASIL determination (S × E × C → ASIL A/B/C/D, plus QM)
- ASIL decomposition rules (independence, redundancy)

**Out of scope (this repo):**
- Any actual safety case, HARA, FSC, TSC, FMEDA work product
- Any traceability to a hazard analysis
- Tool qualification (Part 8, clause 11)

## Files

- [`checklist.md`](checklist.md) — per-part study checklist with reference slots

## Key references (study only)

- ISO 26262:2018 — *Road vehicles — Functional safety*, Parts 1–12
  (purchase from ISO; do not reproduce normative text in this repo)
- ISO 21448 (SOTIF) — out of scope here, noted only as adjacent standard
- "ISO 26262 in plain English" community summaries — useful for framing,
  not for compliance evidence

---

## Study notes

### Parts at a glance (one line each, study-level)

| Part | Title (paraphrased) | Why it matters here |
|------|---------------------|---------------------|
| 1 | Vocabulary | Disambiguates "fault / error / failure," ASIL, item, element |
| 2 | Management of functional safety | Safety culture, roles |
| 3 | Concept phase | Item definition, HARA, ASIL determination |
| 4 | System level | System-level safety requirements |
| 5 | Hardware level | HW safety reqs, FMEDA, metrics (SPFM/LFM/PMHF) |
| 6 | **Software level** | **Most relevant to a SW SE — SW lifecycle, methods, MISRA** |
| 7 | Production / operation | Field monitoring |
| 8 | Supporting processes | Tool qualification, change mgmt, traceability |
| 9 | ASIL-oriented analyses | Decomposition, dependent failures |
| 10 | Guideline | Informative only |
| 11 | Adaptation for semiconductors | Relevant for SoC / vGPU IP suppliers |
| 12 | Adaptation for motorcycles | Out of scope |

### ASIL determination (study-level summary)

ASIL = function of (Severity, Exposure, Controllability) at the hazardous
event. Tables in Part 3 map the (S, E, C) triple to ASIL A–D or QM. Decomposition
allows splitting an ASIL-X requirement into two lower-ASIL elements *if* they
are independent — Part 9 is the gatekeeper.

## Applied to this project

The Phase 3 comparison doc (`docs/nvidia-drive-os-comparison.md`) cites Part 6
(SW lifecycle) when describing the gap between this software proxy and a
DRIVE OS Safety partition. No claims of compliance are made or implied.
