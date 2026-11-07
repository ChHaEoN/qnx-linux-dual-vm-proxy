#!/usr/bin/env python3
"""aw_suite.py -- run-aw-suite.sh's plans, its readings of setup's record, the generation's contract, the guest's console and
the staged map, each unit's record (unit.json) and the suite's (suite.json). SDV Phase 8 WP6 9.2.

Standard library only, and Python 3.10 (the instance's system python3 runs it). It shares vss_setup.py's record format
(its FACTS, its one-line writer) and aw_setup.py's readings, imported from beside it. Run by the harness, one subcommand
per call; a refusal prints its reason on one line (several joined by "; ") and exits 1.

  plan --plan a1|a2|b1|b2|s
        the plan's units in order (THE PLANS below), one per line, tab-separated: NN, NAME, CLAIM, KILL, RECORD, SAMPLE
        (each 0 or 1: the claim node, the controller kill, the bag and its export, the sizing sampler) and the claim
        node's own arguments, space-separated (none for a unit without them). Exit 1 for another plan.
  setup --setup SETUP_JSON --host-mode M --facts D
        run-aw-setup.sh's raw/setup.json: status DONE, budget_short false (D7's rule: true means under 30 minutes were
        left after the pull, and the suite does not run), host_mode M; prints `REF ID`, the image setup pulled and the ID
        it read back.
  contract --file VSS_CTL_PY --facts D
        the generation's kind 2 contract, read as text (never imported): its DIGEST and COMPILED_PROFILE_IDS, which must
        hold the base profile and the demo profile (SENT_PROFILES); prints `DIGEST`.
  rules --console F --digest DIGEST --facts D
        the guest console's `monitor: ctl rules:` lines (NUL and CR removed): at least one, all alike, its catalog the
        contract's DIGEST and its profiles holding SENT_PROFILES; facts into D (lines, catalog, digest_matches,
        profiles); prints the count.
  map-check --map-dir D --scenario S --facts F
        the staged map D/<the scenario's map name>/ holds exactly the scenario's files, each of its sha256; prints the
        map's name.
  engaged --file SCENARIO_JSONL
        exit 0 when the scenario driver's log holds a line with step engage and outcome done (the drive is in autonomous
        mode: the controller kill waits for it), else 1.
  component --name NAME
        `ros2 component list`'s output on stdin (a container's line, then `  ID  /path/node` for each node it holds):
        prints `CONTAINER ID` of the one node whose last path segment is NAME, which `ros2 component unload` takes; a
        list with none, or with two, is refused.
  slice --console F --from N --to M --out O
        the console's bytes N to M into O: the part of the one guest console a unit saw.
  unit-json --work W --name NAME --unit-dir D --plan P --out F
        a unit's unit.json from its facts (W/facts/NAME), the records the harness copied into D (replies.jsonl: its
        summary, the replies counted and by reason; scenario.jsonl: each step's outcome and state) and, for the sizing
        unit, its samples (W/units/NAME/samples.txt: MemAvailable and docker stats at a fixed spacing).
  record --work W --out F --plan P --status S --status-line L --at A --reason R --host-mode M --guest-host G
        suite.json from W/plan.tsv and the facts under W/facts, written whole (a temporary file beside F, then a rename):
        the preflight's facts, the guest's, every planned unit in order with its state (ran, sim-failed, sim-not-up,
        failed, step-timeout, or not-run when no fact names one) and its facts, the units not run, the host check, the
        sweep, the status. Every string is one line.

THE PLANS, each unit a fresh planning simulator (aw-sim), the claim node
(aw-claim-node) to the guest's :7150 started before the scenario driver (aw-scenario) sets the route (W4 G2, 2.8):
  a1  01-psim: one planning-sim run of the scenario, no claim node (A1)
  a2  01-honest: the scenario with the claim node; 02-inject: the scenario again with each injection of WP2's list at its
      own fixed seq (A2: the first QNX-guest judgement of Autoware commands on an ARM edge)
  b1  OP's B1 verdict table: 01-honest, recorded as a bag (outside the record) and exported by ctl_export.py; 02-inject
  b2  OP's B2 verdict table: 01-kill (the controller, the composable node controller_node_exe, unloaded from its component
      container inside aw-sim once the drive is engaged); 02-inject (each reason at its fixed seq, profile0 the unknown
      profile); 03-demo (profile 2's bounded window)
  s   01-sizing: the honest scenario with the claim node, MemAvailable and docker stats sampled by the harness
B1's dummy and moving objects of OP's table need a scenario form 2.8 does not have: B1 is the honest route and the
injection table (spec-2 9.2). The intake pause (OP's node-injected silence) is in no plan: spec-2 9.2 lists none.

DESIGN VALUES (not measured, each with its reason): INJECT_FIRST_SEQ, INJECT_SPACING, DEMO_WINDOW below.

Does not demonstrate: anything; it reads and writes what the harness gives it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True                  # nothing written into the tarball's tree by the imports below
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aw_setup as aws  # noqa: E402
import vss_setup as vs  # noqa: E402

FORMAT = 1
# WP2's injections (sdv/ctl/ctlclient.py's INJECTIONS, in its order; a test holds the two equal), each at its own seq.
INJECTIONS = ("nan", "undef", "reserved", "profile0", "kind9", "interval", "speed", "accel", "jerk", "steer", "steer-rate",
              "lat-accel", "overspeed", "rolling-back")
INJECT_FIRST_SEQ = 50    # about 1.5 s of Controls after the first (the gate's 30 ms period, W4 G3): past the launch
INJECT_SPACING = 25      # 24 honest Controls between two injections, so each injected frame's reply stands alone
DEMO_WINDOW = (5000, 10000)   # profile 2 from 5 s after the first frame for 10 s: inside run_window_max_ms (30000)
SENT_PROFILES = (1, 2)   # the claim node's base profile (its default) and the demo profile (b2's window)
PLANS: Dict[str, Tuple[Tuple[str, Dict[str, bool]], ...]] = {
    "a1": (("psim", {"claim": False}),),
    "a2": (("honest", {}), ("inject", {"inject": True})),
    "b1": (("honest", {"record": True}), ("inject", {"inject": True})),
    "b2": (("kill", {"kill": True}), ("inject", {"inject": True}), ("demo", {"demo": True})),
    "s": (("sizing", {"sample": True}),),
}
# monitor.c's `monitor: ctl rules:` line, searched where it starts in a console line (another process's boot text can come
# before it on the same line) and ending the line: a line with text after its profiles is not counted. Its middle (the %g
# constants and their units) holds no ':', so it cannot run on into another monitor's line and end at that line's profiles
CTL_RULES = re.compile(r"monitor: ctl rules: kind 2, catalog (0x[0-9A-F]{8}) \(vss [^)]*\), dt_max (\d+) ms, [^:]*, "
                       r"profiles ([0-9 ]+)$")
DIGEST_LINE = re.compile(r"^DIGEST = (0x[0-9A-Fa-f]{8})$", re.M)
PROFILES_LINE = re.compile(r"^COMPILED_PROFILE_IDS = \(([0-9, ]*)\)$", re.M)
SAMPLE_HEAD = re.compile(r"^== t (-?\d+) mem (\S+)$")
# setup.json's image.ref in spec-2 2.6's whole form, as aw_setup.py ref prints it: the repository by aw_setup.py's
# REPOSITORY (pull_ref's rule: no ':', so no tag before the '@'), then '@' and one sha256 digest of 64 lowercase hex
# (its DIGEST), nothing after it; each in a group of its own, so an alternation in either cannot leak past the '@'
IMAGE_REF = re.compile("(?:%s)@(?:%s)" % (aws.REPOSITORY.pattern, aws.DIGEST.pattern))
ABOUT = ("run-aw-suite.sh's record (SDV Phase 8 WP6 9.2): Autoware's planning simulator driven through the "
         "scenario on this host, each unit's Control judged by the QNX guest's ctl monitor on :7150 through the claim "
         "node, every container under 2.12, with 2.12's host check before and after the stem.")
NOTE = ("A functional session, with operational records and no benchmark claim; nothing is pre-registered. "
        "Docker is up on this host. Values "
        "under operational_s are whole seconds of this session's own units, and the sizing unit's samples are a "
        "pre-screen read by the harness itself, never compared across hosts and never a figure of the guest.")


def claim_args(unit: Dict[str, bool]) -> List[str]:
    """The claim node's own arguments for a unit (beyond --host, --port, --contract, --out)."""
    out: List[str] = []
    if unit.get("inject"):
        for k, mode in enumerate(INJECTIONS):
            out += ["--inject", "%d:%s" % (INJECT_FIRST_SEQ + k * INJECT_SPACING, mode)]
    if unit.get("demo"):
        out += ["--demo", "%d:%d" % DEMO_WINDOW]
    return out


def plan_rows(plan: str) -> List[List[str]]:
    if plan not in PLANS:
        raise ValueError("PLAN %r is none of %s" % (plan, ", ".join(PLANS)))
    rows = []
    for n, (name, unit) in enumerate(PLANS[plan], start=1):
        flags = [unit.get("claim", True), unit.get("kill", False), unit.get("record", False), unit.get("sample", False)]
        rows.append(["%02d" % n, "%02d-%s" % (n, name)] + ["1" if f else "0" for f in flags] + [" ".join(claim_args(unit))])
    return rows


def cmd_plan(a: argparse.Namespace) -> int:
    try:
        rows = plan_rows(a.plan)
    except ValueError:
        print("PLAN %r is not a1, a2, b1, b2 or s" % a.plan, file=sys.stderr)
        return 1
    for r in rows:
        print("\t".join(r))
    return 0


def cmd_setup(a: argparse.Namespace) -> int:
    doc, why = aws.load_json(a.setup, "rec/aw-setup/raw/setup.json")
    if why:
        return aws.refuse([why])
    if not isinstance(doc, dict):
        return aws.refuse(["rec/aw-setup/raw/setup.json is not a JSON object"])
    status, short, mode = doc.get("status"), doc.get("budget_short"), doc.get("host_mode", "a1-metal")
    im = doc.get("image")
    image: Dict[str, Any] = im if isinstance(im, dict) else {}
    ref, iid = image.get("ref"), image.get("id")
    vs.put(a.facts, "aw_setup_status", str(status))
    vs.put(a.facts, "aw_setup_host_mode", str(mode))
    vs.put(a.facts, "budget_short", str(short) if not isinstance(short, bool) else short)
    problems = []
    if status != "DONE":
        problems.append("rec/aw-setup/raw/setup.json says status %r, not DONE" % (status,))
    if short is not False:
        problems.append("rec/aw-setup/raw/setup.json records budget_short %s: under 30 minutes were left before stop_at "
                        "after its pull (D7's rule), so the suite does not run" % json.dumps(short))
    if mode != a.host_mode:
        problems.append("rec/aw-setup/raw/setup.json records host mode %s (none is a1-metal), not this suite's %s"
                        % (mode, a.host_mode))
    if not isinstance(ref, str) or not IMAGE_REF.fullmatch(ref):
        problems.append("rec/aw-setup/raw/setup.json names no image pulled by its digest (image.ref)")
    if problems:
        return aws.refuse(problems)
    vs.put(a.facts, "image_ref", str(ref))
    vs.put(a.facts, "image_id", str(iid))
    print("%s %s" % (ref, iid))
    return 0


def contract_of(path: str) -> Tuple[Optional[str], List[int], Optional[str]]:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        return None, [], "VSS_HOME/gen/vss_ctl.py cannot be read (%s): run-vss-setup.sh stages the generation" % (
            exc.strerror or aws.one(exc))
    d, p = DIGEST_LINE.search(text), PROFILES_LINE.search(text)
    if not d or not p:
        return None, [], "VSS_HOME/gen/vss_ctl.py holds no DIGEST or COMPILED_PROFILE_IDS line: not the generation's"
    ids = [int(x) for x in p.group(1).replace(",", " ").split()]
    return "0x%08X" % int(d.group(1), 16), ids, None


def cmd_contract(a: argparse.Namespace) -> int:
    digest, ids, why = contract_of(a.file)
    if why:
        return aws.refuse([why])
    vs.put(a.facts, "ctl_digest", str(digest))
    vs.put(a.facts, "ctl_profiles", [str(i) for i in ids])
    missing = [p for p in SENT_PROFILES if p not in ids]
    if missing:
        return aws.refuse(["VSS_HOME/gen/vss_ctl.py compiles profiles %s, not %s: the claim node's base profile is 1 and "
                           "b2's window sends profile 2" % (", ".join(str(i) for i in ids) or "none",
                                                              " and ".join(str(p) for p in SENT_PROFILES))])
    print(digest)
    return 0


def cmd_rules(a: argparse.Namespace) -> int:
    try:
        with open(a.console, "rb") as f:
            text = f.read().replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", "replace")
    except OSError:
        text = ""
    found = []
    for line in text.splitlines():
        m = CTL_RULES.search(line.strip())
        if m:
            found.append((m.group(1), tuple(int(x) for x in m.group(3).split())))
    vs.put(a.facts, "lines", len(found))
    print(len(found))
    if not found:
        return aws.refuse(["the guest's console holds no `ctl rules:` line: its image is not the ctl monitor's (WP5's "
                           "ifs-ctl.bin), or its :7150 process did not start"])
    if len(set(found)) != 1:
        return aws.refuse(["the guest's `ctl rules:` lines disagree: %s" % sorted(set(found))])
    catalog, profiles = found[0]
    vs.put(a.facts, "catalog", catalog)
    vs.put(a.facts, "digest_matches", catalog == a.digest)
    vs.put(a.facts, "profiles", [str(p) for p in profiles])
    problems = []
    if catalog != a.digest:
        problems.append("the guest's `ctl rules:` catalog %s is not vss_ctl.py's DIGEST %s: the guest judges another kind "
                        "2 contract than the claim node packs by" % (catalog, a.digest))
    missing = [p for p in SENT_PROFILES if p not in profiles]
    if missing:
        problems.append("the guest's `ctl rules:` profiles %s lack profile %s, which the plans send"
                        % (list(profiles), " and ".join(str(p) for p in missing)))
    return aws.refuse(problems) if problems else 0


def cmd_map_check(a: argparse.Namespace) -> int:
    name, files, why = aws.map_of(a.scenario)
    if why:
        return aws.refuse([why])
    assert name is not None
    d = os.path.join(a.map_dir, name)
    vs.put(a.facts, "map", name)
    problems = []
    try:
        present = sorted(os.listdir(d))
    except OSError as exc:
        return aws.refuse(["VSS_HOME/aw/map/%s cannot be listed (%s): run-aw-setup.sh stages it" % (
            name, exc.strerror or aws.one(exc))])
    for n in present:
        if n not in files:
            problems.append("VSS_HOME/aw/map/%s/%s is not one of the scenario's map files" % (name, n))
    for n, want in sorted(files.items()):
        p = os.path.join(d, n)
        if not os.path.isfile(p):
            problems.append("VSS_HOME/aw/map/%s/%s is missing" % (name, n))
            continue
        got = aws.sha256_file(p)
        if got != want:
            problems.append("VSS_HOME/aw/map/%s/%s hashes to %s, and the scenario says %s" % (name, n, got, want))
    vs.put(a.facts, "map_ok", not problems)
    if problems:
        return aws.refuse(problems)
    print(name)
    return 0


def scenario_lines(path: str) -> List[Dict[str, Any]]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                try:
                    doc = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(doc, dict):
                    out.append(doc)
    except OSError:
        pass
    return out


def cmd_engaged(a: argparse.Namespace) -> int:
    for d in scenario_lines(a.file):
        if d.get("step") == "engage" and d.get("outcome") == "done":
            return 0
    return 1


COMPONENT_LINE = re.compile(r"^\s+(\d+)\s+(/\S+)$")


def cmd_component(a: argparse.Namespace) -> int:
    container, found = "", []
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        m = COMPONENT_LINE.match(line)
        if m is None:
            container = line.strip()
        elif container and m.group(2).rsplit("/", 1)[-1] == a.name:
            found.append("%s %s" % (container, m.group(1)))
    if len(found) != 1:
        print("`ros2 component list` lists %d node(s) named %s in a component container: %s" % (
            len(found), a.name, "; ".join(found) or "none"), file=sys.stderr)
        return 1
    print(found[0])
    return 0


def cmd_slice(a: argparse.Namespace) -> int:
    try:
        with open(a.console, "rb") as f:
            f.seek(max(0, a.from_))
            data = f.read(max(0, a.to - a.from_))
    except OSError:
        data = b""
    with open(a.out, "wb") as g:
        g.write(data)
    return 0


def replies_of(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    summary: Any = None
    by_reason: Dict[str, int] = {}
    replied, lines = 0, 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            try:
                doc = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(doc, dict):
                continue
            if "summary" in doc:
                summary = doc["summary"]
            elif "seq" in doc:
                lines += 1
                if doc.get("outcome") == "replied":
                    replied += 1
                    k = str(doc.get("reason"))
                    by_reason[k] = by_reason.get(k, 0) + 1
    return {"frames": lines, "replied": replied, "by_reason": dict(sorted(by_reason.items(), key=lambda kv: int(kv[0])
                                                                           if kv[0].isdigit() else -1)),
            "summary": summary}


def samples_of(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return out
    for ln in text.splitlines():
        m = SAMPLE_HEAD.match(ln)
        if m:
            mem = m.group(2)
            out.append({"t_s": int(m.group(1)), "mem_available_kb": int(mem) if mem.isdigit() else mem, "containers": []})
        elif out and "\t" in ln:
            cells = ln.split("\t")
            out[-1]["containers"].append({"name": cells[0], "cpu": cells[1] if len(cells) > 1 else "",
                                          "mem": cells[2] if len(cells) > 2 else ""})
    return out


def cmd_unit_json(a: argparse.Namespace) -> int:
    facts = vs.read_facts(os.path.join(a.work, "facts", a.name))
    guest = a.name == "guest"                   # the guest's facts (facts/guest), its record 00-guest
    doc: Dict[str, Any] = {"format": FORMAT, "harness": "run-aw-suite.sh", "plan": a.plan,
                           "unit": "00-guest" if guest else a.name}
    doc.update(guest_section(facts) if guest else facts)
    doc["state"] = facts.get("state") or "not-run"
    if not guest:
        doc["replies"] = replies_of(os.path.join(a.unit_dir, "replies.jsonl"))
        doc["scenario"] = [{"step": d.get("step"), "outcome": d.get("outcome"), "state": d.get("state")}
                           for d in scenario_lines(os.path.join(a.unit_dir, "scenario.jsonl"))]
        if facts.get("sample") is True:
            doc["samples"] = samples_of(os.path.join(a.work, "units", a.name, "samples.txt"))
    doc["kept"] = sorted(n for n in os.listdir(a.unit_dir) if n != "unit.json") if os.path.isdir(a.unit_dir) else []
    vs.write_json(a.out, doc)
    return 0


def guest_section(g: Any) -> Dict[str, Any]:
    out = dict(g) if isinstance(g, dict) else {}
    cr = out.get("ctl_rules")
    if isinstance(cr, dict) and isinstance(cr.get("profiles"), list):
        cr = dict(cr)
        cr["profiles"] = [int(x) for x in cr["profiles"] if str(x).isdigit()]
        out["ctl_rules"] = cr
    return out


def cmd_record(a: argparse.Namespace) -> int:
    rows = vs.read_rows(os.path.join(a.work, "plan.tsv"), 7)
    facts = vs.read_facts(os.path.join(a.work, "facts"))
    units: List[Dict[str, Any]] = []
    not_run: List[str] = []
    for nn, name, *_rest in rows:
        f = dict(facts.get(name) or {})
        state = f.pop("state", None) or "not-run"
        e: Dict[str, Any] = {"nn": nn, "name": name, "state": state}
        e.update(f)
        units.append(e)
        if state == "not-run":
            not_run.append(name)
    pf = facts.get("preflight")
    pre: Dict[str, Any] = pf if isinstance(pf, dict) else {}
    doc: Dict[str, Any] = {"format": FORMAT, "harness": "run-aw-suite.sh", "host_mode": a.host_mode, "about": ABOUT,
                           "note": NOTE, "plan": a.plan or None, "status": a.status, "status_line": a.status_line,
                           "at": a.at or None, "reason": a.reason or None, "guest_host": a.guest_host,
                           "image": pre.get("image_ref"), "preflight": pre, "guest": guest_section(facts.get("guest")),
                           "units": units, "not_run": not_run, "host_check": facts.get("host_check") or {},
                           "stop": facts.get("stop") or {}}
    vs.write_json(a.out, doc)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--plan", required=True)
    p = sub.add_parser("setup")
    for x in ("--setup", "--host-mode", "--facts"):
        p.add_argument(x, required=True)
    p = sub.add_parser("contract")
    p.add_argument("--file", required=True)
    p.add_argument("--facts", required=True)
    p = sub.add_parser("rules")
    for x in ("--console", "--digest", "--facts"):
        p.add_argument(x, required=True)
    p = sub.add_parser("map-check")
    for x in ("--map-dir", "--scenario", "--facts"):
        p.add_argument(x, required=True)
    p = sub.add_parser("engaged")
    p.add_argument("--file", required=True)
    p = sub.add_parser("component")
    p.add_argument("--name", required=True)
    p = sub.add_parser("slice")
    p.add_argument("--console", required=True)
    p.add_argument("--from", dest="from_", type=int, required=True)
    p.add_argument("--to", type=int, required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("unit-json")
    for x in ("--work", "--name", "--unit-dir", "--plan", "--out"):
        p.add_argument(x, required=True)
    p = sub.add_parser("record")
    for x in ("--work", "--out", "--status", "--status-line", "--host-mode", "--guest-host"):
        p.add_argument(x, required=True)
    for x in ("--plan", "--at", "--reason"):
        p.add_argument(x, default="")
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "setup": cmd_setup, "contract": cmd_contract, "rules": cmd_rules, "map-check": cmd_map_check,
            "engaged": cmd_engaged, "component": cmd_component, "slice": cmd_slice, "unit-json": cmd_unit_json,
            "record": cmd_record}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
