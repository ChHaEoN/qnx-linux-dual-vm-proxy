# skills/digital-twin

> Study notes only — not certification evidence, not professional advice.

Paradigm references for engineering Digital Twins, particularly in
the automotive / SDV context where this project sits.

## Scope of this folder

- The **MIL → SIL → HIL → PIL** simulation-level progression and where a
  Digital Twin sits across it
- The distinction between a **Digital Twin** (real-time bidirectional
  mirror), **Digital Shadow** (one-way data flow), and **Digital Model**
  (offline)
- Twin-diff methodology: how to design measurements that isolate
  host-effects from code-effects (the load-bearing concern in this
  project's `docs/digital-twin-design.md`)

## Out of scope

- Industry-specific twin certifications (DIN 91383, ISO 23247) —
  noted as references only
- Real-time data-pipeline implementation (Kafka, MQTT, etc.) — this
  project's twin uses scp + rsync, not streaming
- Vendor-specific twin platforms (Ansys, Siemens Xcelerator,
  NVIDIA Omniverse) — paradigm only, not platform tutorials

## Where this skill is exercised in the repo

- [docs/digital-twin-design.md](../../docs/digital-twin-design.md) —
  applied design for this project's two twins
- [docs/architecture.md](../../docs/architecture.md) — the structural
  view of cloud + HW twin sides
- `scripts/twin/sync.sh` and `scripts/twin/diff-results.sh` — the
  concrete sync mechanism + diff workflow

## Open reading list (to be filled as Phase 4 lands)

- ISO 23247 — Digital Twin framework for manufacturing (one of the
  closest standards to what an automotive twin would look like)
- INCOSE Systems Engineering Handbook (V-model + simulation levels)
- AUTOSAR Adaptive Platform — for SDV-twin context (Phase 7)
