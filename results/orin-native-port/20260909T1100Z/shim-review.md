# Adversarial review of the M0 shim (2026-09-09)

Four independent reviewers over `orin-native/shim/t234-shim.S` and `build-shim.sh`, one lens each, run on a
cheaper model tier than the authoring pass. Every reviewer assembled the file with the real toolchain and
disassembled the result rather than reading it alone; two also reproduced build failures. Nothing was edited
by the reviewers.

## Two lenses came back clean

- **ARM architecture correctness.** System-register access at EL2 with VHE still set on entry; the
  `CNTP_CTL_EL0`/`CNTV_CTL_EL0` aliasing in both `E2H` states; `VBAR_EL2` alignment and which of the sixteen
  vector slots can fire; barrier placement around the `HCR_EL2.E2H` change; `DC CIVAC` with the MMU off; the
  `movz`/`movk` immediate constructions. Checked by disassembling the encoded immediates, not by eye. No
  defects.
- **Stackless register discipline.** Every control-flow path traced against the register convention: whether
  `putc`'s clobbers reach a live value, whether `puts` and `puthex64` can collide on their saved return
  registers, whether `x2` survives the nested call in `puthex64`, whether the exception path's use of `x25`
  is safe. All three modes assemble with zero warnings. No defects.

## Five findings, all applied

| # | Severity | What | Fix applied |
|---|---|---|---|
| 1 | MAJOR | The TCU poll was bounded by an instruction count, not a deadline, and a timed-out byte vanished with no counter. If the SPE has stopped draining the mailbox — the exact thing M0 exists to test — a whole bank line of uncalibrated spins eats into WDT0's two minutes, and the operator cannot tell "console dead" from "shim hung". | The bound is now a real deadline read off `CNTFRQ_EL0`/`CNTPCT_EL0` (~15.6 ms at this board's 31.25 MHz), and dropped bytes are counted in `x16` and printed as `TCUDROPS=` before the mode action. |
| 2 | MAJOR | The shim is 8 KiB, but the plan still described a 4 KiB page with the IFS at `0x80081000` in five places, including the jump formula and the `od` size check. Building an M1 IFS from the plan's literal text would bake in an address wrong by exactly one page. | Plan §3.1, §3.2, §3.3, §6.1 M0 and the first-actions checklist all corrected to 8 KiB and `0x80082000`. The build script already fails if the page is not exactly 8192 bytes, so the two cannot drift again. |
| 3 | MAJOR | `build-shim.sh` could not concatenate an IFS at all, by either kind of path — reproduced. A relative path was resolved after the script had already `cd`'d into the output directory; an absolute path passed the existence check and then failed at `cat`, because prepending the QNX bin directory to `PATH` shadows the shell's coreutils with Windows-native `cat.exe`, which cannot open an MSYS-style path. | The IFS path is resolved to absolute before any `cd`, and the QNX bin directory is appended to `PATH` rather than prepended. Verified: a relative path now produces `t234-qnx.kimg`, and the IFS bytes land at offset `0x2000` intact. |
| 4 | MINOR | The black-box writer had no capacity bound. Not reachable by anything this shim prints, but the same routine is meant to stay live through QNX startup, and running off the end would write outside the reserved carveout. | The cursor stops at the console zone's data capacity. |
| 5 | MINOR | `image_size` was rounded to 2 MiB with the comment attributing that to kexec's placement alignment. The 2 MiB figure is the alignment of the *base address* the kernel picks, not a size granularity, so the rounding silently over-reserved up to 2 MiB. | Rounded to a page instead, with the comment corrected. |

## A note on the plan-versus-code gap

Finding 2 is the one worth remembering. The code was right and the document was stale: the shim grew to
8 KiB for a real architectural reason (the vector table must be 2 KiB-aligned and is itself 2 KiB, and the
handler has to sit clear of all sixteen slots), and the size was verified by the build, but nobody propagated
it back. A plan that is followed literally by someone else is a specification, and a stale specification that
still reads as verified is worse than an obviously incomplete one.
