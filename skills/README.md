# skills/ — engineering & normative-research paradigms

This folder catalogs **paradigms** I'm studying alongside the build:
when/why each framework is used, a template or checklist, and (later)
worked examples drawn from the project's actual phases.

> ⚠️ **These are study artifacts, not certification evidence.**
> Nothing in this folder constitutes formal compliance with any
> automotive or safety standard. Cited sources are pointers, not
> reproductions of normative text.

This is unrelated to Claude Code's built-in `/skill` system; it's a
plain-markdown knowledge base.

---

## Index

| Skill | Scope | Primary references (study only) |
|-------|-------|---------------------------------|
| [fmea/](fmea/) | FMEA: Item / Function / Failure Mode / Effect / Cause / S·O·D / RPN / Action | AIAG-VDA FMEA Handbook (1st ed., 2019); ISO 31000 (risk concepts) |
| [iso-26262/](iso-26262/) | Functional safety lifecycle, ASIL decomposition, parts overview | ISO 26262:2018 Parts 1–12 |
| [aspice/](aspice/) | Automotive SPICE PAM v3.1 — SWE.1–SWE.6, SUP, MAN | VDA QMC Automotive SPICE PAM v3.1 (2017) |
| [bsp-porting/](bsp-porting/) | Generic BSP porting workflow: discovery → bring-up → drivers → validation | Linux kernel docs; QNX BSP user's guide; ARM TRM(s) |
| [qnx-safety/](qnx-safety/) | QNX OS for Safety (QOS) vs SDP — feature & cert delta | BlackBerry QNX product pages (public) |
| [digital-twin/](digital-twin/) | MIL/SIL/HIL/PIL progression; twin vs shadow vs model; twin-diff methodology | INCOSE SE Handbook; ISO 23247 |
| [jetson-platform/](jetson-platform/) | L4T / JetPack 6, SDK Manager, Tegra device-tree, Jetson-vs-DRIVE-Orin honest gap | NVIDIA Jetson docs; L4T release notes |
| [tegra-virtualization/](tegra-virtualization/) | NVIDIA Hypervisor (public docs); Cortex-A78AE virt extensions; KVM-on-L4T limits | NVIDIA Hypervisor public docs; ARM ARM v8-A virt section |
| [cybersecurity-21434/](cybersecurity-21434/) | TARA, Cybersec Concept, TCR; STRIDE; secure-boot framing; cyber-FuSa interaction | ISO/SAE 21434:2021 |

---

## How to add a new skill

1. Create `skills/<name>/`.
2. Write `skills/<name>/README.md` with:
   - **When to use** (triggering situations)
   - **Why** (what problem it addresses)
   - **Scope** (what's included; what's deliberately out)
   - **Key references** (cite primary sources; do not paraphrase normative text loosely)
3. Add a template, checklist, or paradigm doc as appropriate.
4. After a Phase milestone, drop a worked example into `skills/<name>/examples/`
   (e.g. `phase-1-bringup-fmea.md`) — clearly separated from the paradigm's
   "study notes" by section heading.
5. Add a one-line entry to the index table above.

---

## Convention: study notes vs. applied work

Each skill doc uses two clearly separated sections:

```markdown
## Study notes
(general paradigm content; cited from primary sources)

## Applied to this project
(concrete examples drawn from the repo's phases — link to specific files,
results, findings docs)
```

Mixing the two erodes the "study artifact" framing. Keep them apart.
