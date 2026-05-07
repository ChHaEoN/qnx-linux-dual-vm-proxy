# skills/aspice — Automotive SPICE (study scope)

> **Phase 0 study notes** — paradigm and study scope only.
> ⚠️ This repo produces **no** ASPICE assessment evidence.
> Cited PA / BP IDs are study pointers, not assessment artifacts.

---

## When to (study) this

- When the JD or interview mentions ASPICE, capability levels, or VDA QMC
- When framing how a Tier-1 customer's SW process would absorb a port of
  AVOS / DRIVE OS into their program
- When discussing requirements traceability in the SE role

## Why

ASPICE (PAM v3.1, 2017) is the de-facto SW process model for automotive
Tier-1s and OEMs in Europe. As an SE supporting customers, even at study
level you should recognize the process-area structure so customer
conversations don't surprise you.

## Scope (in vs. out)

**In scope (study):**
- PAM v3.1 process areas: SWE.1–SWE.6, SUP, MAN
- Capability Levels 0–5 conceptually
- Bidirectional traceability concept
- Base Practices (BP) and Generic Practices (GP) at the *what-they-mean* level

**Out of scope (this repo):**
- Any actual assessment, gap analysis, or improvement plan
- Capability Level claims of any kind
- Process area customization or tailoring artifacts

## Files

- [`process-areas.md`](process-areas.md) — per-PA study checklist

## Key references (study only)

- VDA QMC, *Automotive SPICE Process Assessment / Reference Model v3.1*, 2017
  (purchase from VDA QMC; do not reproduce normative text)
- intacs/ECQA training material for capability-level concepts
- v4.0 has been released — note the version difference if cited

---

## Study notes

### Process-area shortlist (most-relevant to SW SE role)

| PA | Title | Why it matters here |
|----|-------|---------------------|
| SYS.1 | Requirements Elicitation | Customer-facing — gather program reqs |
| SYS.2 | System Requirements Analysis | Where program-level reqs land |
| SYS.3 | System Architectural Design | Where dual-VM partition would be a system-level decision |
| **SWE.1** | **Software Requirements Analysis** | Most-cited in interviews |
| **SWE.2** | **Software Architectural Design** | Where IPC and partition design fit |
| SWE.3 | Software Detailed Design and Unit Construction | |
| SWE.4 | Software Unit Verification | |
| SWE.5 | Software Integration and Integration Verification | |
| **SWE.6** | **Software Qualification Test** | Acceptance criteria — customer-facing |
| SUP.1 | Quality Assurance | |
| SUP.8 | Configuration Management | Trace links live here |
| SUP.9 | Problem Resolution Management | |
| SUP.10 | Change Request Management | |
| MAN.3 | Project Management | |

### Capability Levels (0–5, paraphrased)

| Level | Name | Spirit |
|-------|------|--------|
| 0 | Incomplete | The PA isn't done |
| 1 | Performed | The PA is done — outputs exist |
| 2 | Managed | The PA is planned, monitored, work-products controlled |
| 3 | Established | A defined, tailored process is followed |
| 4 | Predictable | Statistically managed |
| 5 | Innovating | Continuous improvement |

Most automotive programs target **CL2** for SWE.* PAs at minimum.

## Applied to this project

- The interview narrative (`docs/interview-narrative.md`) uses the SWE.1–SWE.6
  vocabulary when describing the customer port path — so the framing is
  recognizable to a Tier-1 / OEM interviewer — without claiming any CL.
- No ASPICE assessment is performed or implied.
