# ASPICE process-areas study checklist (PAM v3.1)

> Track personal study progress. NOT an assessment checklist.
> Mark `[x]` when you can summarize the PA's purpose, key Base Practices,
> and at least one typical work product in your own words.

---

## SYS — System engineering

### SYS.1 Requirements Elicitation
- [ ] Understand stakeholder requirements gathering
- [ ] Typical work products: stakeholder requirements list, change record
- Notes: _______

### SYS.2 System Requirements Analysis
- [ ] Distinguish stakeholder vs system requirements
- [ ] Bidirectional traceability stakeholder ↔ system reqs
- Notes: _______

### SYS.3 System Architectural Design
- [ ] System architecture: elements, interfaces, dynamic behavior
- [ ] Allocation of system requirements to elements
- Notes: _______

### SYS.4 System Integration and Integration Verification
- [ ] Integration strategy
- Notes: _______

### SYS.5 System Qualification Test
- [ ] Acceptance criteria from system reqs
- Notes: _______

---

## SWE — Software engineering ⭐ (most-relevant)

### SWE.1 Software Requirements Analysis ⭐
- [ ] SW reqs derived from system reqs
- [ ] Functional vs non-functional reqs
- [ ] Trace SYS.2 → SWE.1
- Notes: _______

### SWE.2 Software Architectural Design ⭐
- [ ] SW architecture: components, interfaces, dynamic behavior
- [ ] Resource consumption objectives
- [ ] Allocation of SW reqs to components
- Notes: _______

### SWE.3 Software Detailed Design and Unit Construction
- [ ] Detailed design notations
- [ ] Coding standards (often MISRA-C in automotive)
- Notes: _______

### SWE.4 Software Unit Verification
- [ ] Unit test strategy
- [ ] Coverage criteria
- Notes: _______

### SWE.5 Software Integration and Integration Verification
- [ ] SW integration strategy
- [ ] Trace SWE.2 → SWE.5
- Notes: _______

### SWE.6 Software Qualification Test ⭐
- [ ] SW qualification test against SWE.1
- [ ] Trace SWE.1 → SWE.6
- Notes: _______

---

## SUP — Supporting

### SUP.1 Quality Assurance
- [ ] QA independence from project
- Notes: _______

### SUP.8 Configuration Management
- [ ] Baselines, branches, version control
- [ ] Where traceability links are stored
- Notes: _______

### SUP.9 Problem Resolution Management
- [ ] Defect lifecycle, root-cause analysis
- Notes: _______

### SUP.10 Change Request Management
- [ ] Impact analysis, change records
- Notes: _______

---

## MAN — Management

### MAN.3 Project Management
- [ ] Estimation, scheduling, monitoring
- Notes: _______

---

## Cross-cutting concepts

- [ ] **Bidirectional traceability** — what links to what across SYS.2 ↔ SWE.1 ↔ SWE.6
- [ ] **Capability Level 2 vs 3** — the bar most programs target for SWE.*
- [ ] **Generic Practices (GP)** — how CL is *achieved*; BP is *what* is done

---

## Self-review questions (interview-style)

- [ ] "Walk me through the trace links for a single SW requirement from
      stakeholder need to qualification test."
- [ ] "What's a typical CL2 SWE.2 work product?"
- [ ] "How does a customer-facing SE typically interact with SWE.1 and SWE.6?"
- [ ] "Where in ASPICE does the dual-VM partition decision live — SYS.3 or SWE.2?"
- [ ] "What changed between PAM v3.1 and v4.0?" (high-level only)
