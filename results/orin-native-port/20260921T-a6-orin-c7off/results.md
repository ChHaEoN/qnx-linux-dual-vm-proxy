# A6 campaign on the Orin, deep idle state disabled — 2026-09-21

The same three experiments as [`../20260921T-a6-orin/`](../20260921T-a6-orin/),
re-run with the board's cpuidle `state1` (`c7`, declared exit latency 5000 µs)
disabled on all six cores and WFI kept. **The analysis and every figure are in
that directory's [results.md](../20260921T-a6-orin/results.md)**, which covers
both conditions side by side; this one exists only to say what differs here.

It was run to test a confound found in the first set: an idle reference that was
"the machine, free to sleep" rather than "the machine, unloaded". It was a
falsification in the design's own sense — change the variable, don't argue from
distribution shapes.

**Configuration difference, and only this:** `CSTATE=shallow`, which disabled
every idle state with exit latency above 10 µs — six states, one per core — and
restored and verified them after each run. Every stamp records
`"cstate_policy": "shallow"` and the states it disabled.

**Run directories on the board:** ladder `20260921T125844Z`, interference
`20260921T130114Z`, saturation `20260921T130957Z`. All three passed the
completeness gate.

**Provenance:** library `b42e13955e1b`, run-ladder `a7928dca0b7d`,
run-interference `3217c44242f1`, run-saturation `cabfaa249328` — committed
exactly as run in `48fb342`, before the comment corrections that followed.
The saturation stamp carries the false `known_confound` line described in the
main record.
