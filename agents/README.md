# Agents

Sub-prompt templates for the 14 agents in the project's roster. Each
agent file follows the same shape:

1. **Role one-liner** — what industry role this agent maps to.
2. **Primary responsibilities** — three to five bullets.
3. **Inputs** — what work products this agent consumes from upstream agents.
4. **Outputs** — what work products this agent produces, with file paths.
5. **Handoff** — which agent(s) consume this agent's output next.
6. **Sub-prompt template** — the actual prompt body to paste into a delegated session.

## The 14 agents

| File | Role |
|---|---|
| [research.md](research.md) | 🔍 Research |
| [architect.md](architect.md) | 📐 Architect / Planner |
| [implementation.md](implementation.md) | 🏗️ Implementation |
| [test.md](test.md) | 🧪 Test / V&V |
| [fusa-analysis.md](fusa-analysis.md) | 🛡️ FuSa-Analysis (HARA / FMEA / DFA) |
| [fusa-design.md](fusa-design.md) | 🛡️ FuSa-Design (FSC / TSR / SafMech) |
| [fusa-verification.md](fusa-verification.md) | 🛡️ FuSa-Verification (FMEDA / FIA / residual risk) |
| [cyber-analysis.md](cyber-analysis.md) | 🔐 Cyber-Analysis (TARA) |
| [cyber-design.md](cyber-design.md) | 🔐 Cyber-Design (Cybersec Concept / TCR) |
| [cyber-verification.md](cyber-verification.md) | 🔐 Cyber-Verification (pen-test / fuzz / audit) |
| [docs.md](docs.md) | 📝 Docs |
| [comparison.md](comparison.md) | 📊 Comparison |
| [skills.md](skills.md) | 🎓 Skills |
| [twin-sync.md](twin-sync.md) | 🧭 Twin Sync (Phase 3+) |

## Coordination flow

The full flow is documented in
[../CLAUDE.md](../CLAUDE.md#agents-delegate-work-to-these-roles).
Short version:

- **Research → Architect → Implementation → Test** for each Phase milestone
- **FuSa (3) and Cybersecurity (3)** review at every Phase boundary; both follow Analysis → Design → Verification (V-model order)
- **FuSa-Design ↔ Cyber-Design** pair-review for cyber-FuSa interaction analysis
- **Docs / Comparison / Skills** are continuous; pull from other agents' outputs
