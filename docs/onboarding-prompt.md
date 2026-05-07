# Session-resume prompt — onboarding template

> **Phase 0.** Snapshot of the prompt actually used to resume work on
> 2026-05-07 after migrating the dev driver from M1 Max macOS to a local
> Windows PC. Captured for reuse — re-open this file when starting a
> fresh Claude Code session and adapt the dated / factual lines (commit
> hash, AWS credit remaining, top-of-stack pending item) to current
> reality before pasting.
>
> **What this is NOT:** a clean parameterised template; it is a
> point-in-time snapshot. Lines marked with a date or specific commit
> hash should be re-derived (`git log --oneline -5`, current AWS billing
> dashboard, current PENDING list) before each reuse — do not paste
> stale facts into a new session.

---

## How to reuse

1. Run `git log --oneline -5` and replace the commit reference + count.
2. Re-check the AWS Cost Explorer dashboard and replace the credit /
   days-remaining figure.
3. Re-derive the **PENDING** list from the previous session's notes or
   chat — do not assume the items below are still un-committed.
4. Re-confirm the **TASK** ordering matches the next milestone you want
   to drive.
5. Paste into a new Claude Code session as the first user message.

---

## Prompt body (copy from the line below)

```
Picking up qnx-linux-dual-vm-proxy on Windows after migrating from M1 Max macOS.

CONTEXT
- CLAUDE.md is the project guide (already loaded as project instructions). Re-read it now to refresh.
- 5 commits so far on main; last is e4f22c3 (F1 tightening to Linux x86_64 only). Run git log --oneline -5 to confirm.
- 14 custom subagents live in .claude/agents/. They should load natively in this session — verify by attempting a subagent_type: research Task tool call with a trivial no-op prompt and reporting whether the agent type was found. If not found, fall back to general-purpose with role-injection prompts.
- AWS Free Plan: $100 credit / ~98 days remaining. Budget alert ($80 monthly) and Cost Anomaly Detection (daily summary, $5/day) are already configured by the user.

PENDING (decided in prior conversation, not yet committed)
We empirically confirmed QNX SDP 8.0 SW Center ships BOTH Linux x86_64 AND Windows host installers — not just Linux as F1 currently states. Build host therefore pivots from "AWS t3.medium x86_64 Ubuntu" to "LOCAL WINDOWS PC" — saving AWS credit + removing all ssh/X11/browser-flow friction.

Doc edits needed (this is the next commit):
- docs/bsp-selection.md F1: replace "Linux x86_64 only" with "Linux x86_64 native + Windows native; macOS still not supported in 8.0"
- README.md architecture diagram: replace "Build Host (x86_64 EC2)" with "Local Windows PC (build)"; keep Graviton runtime as is
- CLAUDE.md "Tech stack" section: build host = local Windows is primary; AWS EC2 x86_64 is fallback
- docs/architecture.md "Cloud twin — hybrid build/runtime" section: Windows local primary, EC2 fallback
- scripts/README.md: add Windows-native walkthrough at the top; mark the existing EC2 walkthrough as "Fallback (if no local x86_64 host)"
- scripts/bootstrap-build-host.sh: add header banner stating it is the AWS fallback path
- NEW: scripts/build-qnx-ifs.bat — Windows cmd equivalent of build-qnx-ifs.sh (calls qnxsdp-env.bat, then mkqnximage)
- agents/research.md, agents/implementation.md: minor updates if they reference build-host platform

TASK
1. First action: read CLAUDE.md, run git log --oneline -5, and test subagent_type: research. Report a 6-line orientation summary: phase status, agent count + .claude/agents loading test result, last 3 commits, AWS guardrails state per docs, top-of-stack pending item, what you think the immediate next action is.
2. Wait for my explicit "go".
3. After my go: dispatch the architect agent first to lock the decision (Windows local primary, AWS EC2 fallback) — output to docs/findings.md as a Phase 0 amendment entry. Then dispatch the implementation agent to perform the file edits listed under PENDING. They can run sequentially (architect first, then implementation reads architect's decision).
4. Prepare a single commit with a clear message; show me git diff --stat and the commit message draft for review BEFORE running git commit. Do not push automatically.

PARALLEL WORK
I'm installing QNX SDP 8.0 on this Windows machine in parallel (downloading the SW Center .exe from myQNX, ~45 min total including download + install). Do NOT touch any QNX install topic, scripts/build-qnx-ifs.sh execution, or anything that needs the SDP environment — that's manual on my end. Stick to doc/script edits only.

VOICE / TONE
- No emojis unless I ask
- No trailing summaries unless asked
- Honest framing: every claim paired with what it does NOT demonstrate
- File references in markdown link form: [foo.md](relative/path/foo.md)
- Match my brevity: a yes/no answer is better than a paragraph when I asked yes/no
```

---

## Notes for the next refresh of this template (post-Day-1)

After Phase 1 cloud-twin bring-up actually lands and the Windows pivot
has been validated end-to-end on real silicon, this template should be
revised to:

- Drop the "M1 Max → Windows migration" framing (no longer the active
  delta) and replace it with whatever the next active delta is.
- Replace **PENDING** wording with a direct pointer to the live
  `docs/findings.md` Phase-N gate-review entry.
- Drop the "test subagent_type: research" smoke-test step once
  `.claude/agents/` loading has been confirmed stable across machines
  for >1 session.
- Generalise **TASK** step 3 from "architect → implementation" into a
  reference to the project's standard Phase-gate flow already in
  `CLAUDE.md`.

These are deferred deliberately; templating before Phase 1 lands risks
baking pre-pivot framing into the reusable artefact.
