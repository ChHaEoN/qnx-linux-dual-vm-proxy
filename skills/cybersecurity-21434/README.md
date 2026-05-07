# skills/cybersecurity-21434

> Study notes only — not certification evidence, not professional advice.

Paradigm references for ISO/SAE 21434 ("Road vehicles — Cybersecurity
engineering"), the cybersecurity counterpart to ISO 26262 in
automotive engineering. Used to scope the Cyber-Analysis,
Cyber-Design, and Cyber-Verification agents and the
[../../docs/security-model.md](../../docs/security-model.md) STRIDE
table.

## Scope of this folder

- **Item Definition + TARA** (Threat Analysis and Risk Assessment):
  asset identification, cybersecurity properties (CIA + AAA),
  threat scenarios, damage scenarios, attack-path analysis,
  attack-feasibility rating, risk determination
- **Cybersecurity Concept + Technical Cybersecurity Requirements**
- **Verification & Validation**: pen-testing, fuzzing, vulnerability
  management process
- **Cyber-FuSa interaction**: how cybersecurity threats can become
  safety hazards, and how FuSa mechanisms can introduce new attack
  surface — the joint review the FuSa-Design and Cyber-Design agents
  do at phase gates
- **STRIDE** as the threat-modelling vocabulary used in this project
- **Secure Boot** framing: hardware root-of-trust → first-stage
  bootloader → kernel → hypervisor → guest IPL chain

## Out of scope

- Real CVE intake / vulnerability disclosure pipelines (this is a
  personal project; no real intake)
- Specific HSM / TPM / fuse-provisioning workflows (paradigm only)
- Penetration testing tooling tutorials (Burp, Metasploit, etc.) —
  this is a paradigm folder, not a workshop

## Where this skill is exercised in the repo

- [docs/security-model.md](../../docs/security-model.md) — STRIDE
  table + secure-boot framing + NCEULA audit + supply-chain hygiene
- [agents/cyber-analysis.md](../../agents/cyber-analysis.md),
  [agents/cyber-design.md](../../agents/cyber-design.md),
  [agents/cyber-verification.md](../../agents/cyber-verification.md)
  — the three sub-prompt templates

## Pair with

- [skills/iso-26262/](../iso-26262/) — the FuSa counterpart; cyber
  and FuSa cross-review at every phase gate
- [skills/aspice/](../aspice/) — process framing that wraps both

## Honest gap

This project does not produce 21434 work products in any auditable
form. The TARA, the Cybersecurity Concept, and the verification
artefacts are **illustrative**: they show that the project owner can
discuss 21434 vocabulary fluently and apply the methodology to a
real (if small) system, not that the project has been audited.
