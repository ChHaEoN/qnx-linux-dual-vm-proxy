# FMEA worksheet template

> Copy this file to `examples/<phase-or-incident>-fmea.md` and fill in.
> Keep one row per failure mode. Sort by RPN descending after scoring.

---

## Header

- **Subject** (system / module / phase under analysis):
- **Type**: D-FMEA / P-FMEA-lite
- **Date**:
- **Reviewer(s)**: self-review (this is a study artifact, not a sign-off)
- **Reference**: link to relevant `docs/findings/phase-N-*.md`

## Scoring scale (1–5, not AIAG-VDA-calibrated)

| Score | Severity (S) | Occurrence (O) | Detection (D) |
|-------|--------------|----------------|---------------|
| 1 | Negligible | Very rare | Almost certain to detect pre-release |
| 2 | Minor | Rare | Likely to detect |
| 3 | Moderate | Occasional | May or may not detect |
| 4 | Major | Frequent | Unlikely to detect |
| 5 | Critical | Very frequent | Almost certain to miss |

**RPN** = S × O × D (range 1–125). Flag any row with **S ≥ 4 OR RPN ≥ 40**
for action regardless of pure RPN ranking (per AIAG-VDA Action Priority spirit).

## Worksheet

| # | Item | Function | Failure Mode | Effect | Cause | S | O | D | RPN | Detection / Mitigation | Action owner |
|---|------|----------|--------------|--------|-------|---|---|---|-----|------------------------|--------------|
| 1 |      |          |              |        |       |   |   |   |     |                        |              |
| 2 |      |          |              |        |       |   |   |   |     |                        |              |
| 3 |      |          |              |        |       |   |   |   |     |                        |              |

## Top-priority actions (S ≥ 4 OR RPN ≥ 40)

- [ ] (filled per FMEA)

## Notes

- Document any assumptions used to assign S/O/D.
- If a failure mode lacks a current detection mechanism, the action is
  **add detection**, not just "be careful."
- Re-score after mitigation; archive both pre- and post-mitigation versions.
