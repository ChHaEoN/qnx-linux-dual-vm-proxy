# ISO 26262 study checklist

> Track personal study progress. NOT a compliance checklist.
> Mark `[x]` when you can summarize the part in your own words and cite
> at least one secondary source (textbook, course, conference talk).

---

## Per-part checklist

### Part 1 — Vocabulary
- [ ] Can distinguish: fault → error → failure
- [ ] Can define: item, element, system, component (in 26262 sense)
- [ ] Can define: ASIL, QM, safety goal, safety requirement
- Source(s) studied: _______

### Part 2 — Management of functional safety
- [ ] Roles: safety manager, project manager, assessor
- [ ] Confirmation measures: review, audit, assessment — distinguish
- Source(s) studied: _______

### Part 3 — Concept phase ⭐ (most-asked in interviews)
- [ ] Item definition: scope, boundary, interfaces
- [ ] HARA: Hazard Analysis and Risk Assessment workflow
- [ ] ASIL determination: S × E × C lookup
- [ ] Functional Safety Concept (FSC)
- Source(s) studied: _______

### Part 4 — System level
- [ ] Technical Safety Concept (TSC)
- [ ] System-level architectural design
- [ ] Allocation of safety reqs to HW vs SW
- Source(s) studied: _______

### Part 5 — Hardware level
- [ ] FMEDA basics (Single Point Fault Metric, Latent Fault Metric, PMHF)
- [ ] Fault metric thresholds per ASIL
- [ ] Random vs systematic faults
- Source(s) studied: _______

### Part 6 — Software level ⭐ (most-relevant to SE role)
- [ ] SW lifecycle: requirements → architecture → unit → integration → testing
- [ ] SW architectural design notations (per Table 2)
- [ ] MISRA-C role and limits (it's *one* method, not *the* method)
- [ ] Coverage criteria per ASIL (statement / branch / MC/DC)
- [ ] Tool qualification dependencies (links Part 8)
- Source(s) studied: _______

### Part 7 — Production / operation
- [ ] Field monitoring obligations
- Source(s) studied: _______

### Part 8 — Supporting processes
- [ ] Configuration management vs change management
- [ ] Traceability requirements
- [ ] Tool Confidence Level (TCL) calculation
- Source(s) studied: _______

### Part 9 — ASIL-oriented analyses
- [ ] ASIL decomposition rules and independence requirements
- [ ] Dependent failure analysis (DFA)
- [ ] Common-cause and cascading failure
- Source(s) studied: _______

### Part 10 — Guideline
- [ ] (Informative; skim only)

### Part 11 — Semiconductors ⭐ (relevant for NVIDIA SoC context)
- [ ] Distributed development between SoC and integrator
- [ ] Failure rate accounting for digital, analog, memory blocks
- Source(s) studied: _______

### Part 12 — Motorcycles
- [ ] (Out of scope; skim only)

---

## Adjacent standards

- [ ] ISO 21448 (SOTIF) — when 26262 isn't enough (perception, ML)
- [ ] ISO/SAE 21434 — cybersecurity (often paired with 26262)
- [ ] UNECE R155 / R156 — type approval implications

---

## Self-review questions (interview-style)

- [ ] "How would you decompose an ASIL-D requirement into two ASIL-B elements?"
- [ ] "Where does a hypervisor's freedom-from-interference argument fit in 26262?"
- [ ] "What's a Tool Confidence Level and why does it matter for a compiler?"
- [ ] "If a Linux kernel is in the safety path, what 26262-6 challenges does that create?"
- [ ] "How is QNX OS for Safety positioned vs. plain QNX SDP w.r.t. 26262?"
