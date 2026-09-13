# README verification (2026-09-09)

Four reviewers over the whole of `README.md` after the Phase 3b track was added, one lens each, on the
cheaper model tier. **No lens came back clean** — eleven findings, four of them MAJOR, and every one was a
statement the file made about itself rather than a fact about the hardware.

## What it caught

| Severity | Finding | Applied |
|---|---|---|
| MAJOR | The claim-count overclaim survived in a third place. Two of the three edits that fixed "a read-only board pass refuted four claims" landed; the roadmap Phase 3 hand-off kept the old wording, so the file contradicted itself about how its own evidence was gathered. Two lenses found it independently. | Reworded to match the other two. |
| MAJOR | One reviewer sharpened the point further: of the three claims actually refuted, one was corrected by a compile-only Windows build with no board involved, so crediting a board pass for all four misdescribes the method twice over. | The corrected wording separates review from board evidence. |
| MAJOR | The Phase 4 row still called ADR-003 "Proposed". It was written before the decision and missed when the other three references were updated — including the row directly above it, which already said ADR-003 had chosen. | Updated. |
| MINOR | The layout tree had grown a second copy of the plan entry, differing only in wording. | Duplicate removed. |
| MINOR | The layout tree said `startup/` was not written yet; it now holds the board-directory spec and the layout-verification buildfile. | Description updated. |
| MINOR | The roadmap said two compile-only results were verified; the section below it lists three. | Corrected to three. |

## Why this was worth running

Every MAJOR finding is a self-inconsistency introduced by editing the same file across several commits — the
kind that a careful author misses precisely because they know what they meant. None of them would have been
caught by re-reading the diff, because each is a contradiction between a line being changed and a line that
was not. The plan-versus-code gap the shim review found a few hours earlier is the same failure in a
different medium.

The reviewers also confirmed, by checking each target against the filesystem, that every markdown link and
every path in the layout tree resolves.
