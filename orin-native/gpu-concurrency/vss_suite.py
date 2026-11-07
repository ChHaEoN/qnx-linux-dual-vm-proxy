#!/usr/bin/env python3
"""vss_suite.py -- run-vss-suite.sh's plan, its :7160 readiness probe, its readings of step 3's directories, and its record
suite.json. plan Phase 3 (WP5), 2026-10-03.

Standard library only, and Python 3.10 (the instance's system python3): nothing here may need a later Python. It shares
vss_setup.py's record format (its FACTS, its one-line writer), imported from beside it. Run by the harness, one subcommand
per call:

  plan --plan v1|v2|carla --runs-file STEP3_RUNS_JSON
        the plan's units in order, one per line, tab-separated:
          run      NN  NN-<spec>-<mode>      SPEC  MODE  RECORDING
          compare  NN  NN-compare-<modes>    WHEN  MODES (space-separated)
        v1: replay honest, then broker honest; no compare. v2: broker, then replay with injected-stop
        once more (for the frame comparison), then can, each over SPECS; then the exit compare over broker and replay
        (WHEN always), and one over all three modes (WHEN can-complete: only when can finished all six). carla (SDV Phase
        7 WP3b): v2's units and compares over the CARLA pair. RECORDING is the name of the spec's recording
        in the plan's pair (PLAN_RECORDINGS; step3-runs.json's kind: honest or injected). Exit 1 for another plan.
  recordings --plan-tsv PLAN_TSV --recordings DIR --setup SETUP_JSON --facts D
        PLAN=carla's preflight (SDV Phase 7 WP3b): for each recording the plan names (PLAN_TSV's sixth
        column), the log its manifest line names (vss_setup.py's log reading) must be under DIR/<name>/, and the line's
        profile_id must be among the profiles setup's guest step recorded from its console's `vss rules:` lines
        (setup.json's facts.guest.profiles: a read, not a name check). Facts into D (setup_profiles; recordings, one line
        per recording: its name, log and profile); prints the refusals on one line, joined by "; ", and exits 1 when
        there is any. v1 and v2 do not call it: their preflight is as it was.
  setup --setup SETUP_JSON --skips FILE [--facts D] [--host-mode orin|c7g-metal]
        run-vss-setup.sh's record read: its status must be DONE, its host mode this suite's (--host-mode, given in the
        Orin and c7g-metal modes only; without it a1-metal, and a setup.json that records no host_mode is an a1.metal
        setup's: a setup of another mode is refused, and with --host-mode its host mode goes into D/setup_host_mode), it
        must hold its
        skip list, and its guest step's verdict must pass vss_setup.py's THE GUEST RULE (a guest that booted there with
        :7160 not ready, C12b not ok or a catalog that is not the bridge's label is one this suite cannot judge: the same
        image, the same images.json); that verdict's booted, ready_7160, c12b_ok and catalog_is_bridge_label go into
        D/setup_guest. FILE gets one line per skipped mode, `MODE<TAB>REASON` (setup's reasons for it, joined). Prints
        `skip MODE ...`, or on a refusal its reason on one line and exit 1.
  orin-check --facts D --default-deadline PATH --subtree PATH
        vss_setup.py's orin-check, the same rules.
  bridge-pin --images IMAGES_JSON
        prints images.json's bridge.arm64.id (SDV_BRIDGE_IMAGE: an image ID cannot travel in LADDER_ENV); exit 1 when it
        is not one sha256 digest.
  ready --host H --port P --tries N --bound S --gap S --settle S --console FILE --facts D
        the :7160 readiness: up to N attempts, each socket.create_connection((H, P), timeout=S).close() in one
        step -- no byte sent, no descriptor held -- S2 (--gap) apart. Once one connects, --settle seconds (past the
        guest's 500 ms deadline, so a probe held open past it would by now show as `client closed:`), then the console's
        freshness read as step3.py's gate reads it (FRESH_* below, kept equal to step3.py's by a test), and whether the
        :7160 banner appears (information only: banners interleave). Facts into D; prints `yes` or `no`.
  run-facts --runs DIR --name NAME --console FILE --facts D
        step 3's directory for the run NAME (DIR/<YYYYMMDD>-NAME, stack.new_run_dir's form) and its one result.json:
        whether each was found, the directory relative to DIR's parent, the run, its ok and its gates; and the console's
        sha256 and size. Prints the directory's absolute path when found.
  compare-facts --runs DIR --name NAME --facts D
        the compare's compare.json: found, its ok, its left-out runs, and per group (spec) its ok and problems.
  record --work W --out F --setup SETUP_JSON --plan P --status S --status-line L --at A --reason R
         [--host-mode orin --cpuset LIST | --host-mode c7g-metal]
        suite.json from W/plan.tsv (the plan, as `plan` printed it) and the facts under W/facts, written whole (a
        temporary file beside F, then a rename): every planned unit in order, each with its state (ran, skipped,
        boot-failed, not-ready, step-timeout, not-compared, or not-run when no fact names one) and its facts; the units
        not run; setup's skip list; the run after which the plan was listed (plan_stopped_after: a run not ready on
        :7160 while none had been, or in the Orin mode a run whose pin failed while none had been pinned), or null; the
        stop's facts; the status. Every string is one line. --host-mode (the Orin mode's, and the c7g-metal mode's
        with no --cpuset) puts host_mode and container_cpuset (--cpuset, or null) after harness; without it the
        document is an a1.metal suite's, with neither key.

Does not demonstrate: anything; it reads and writes what the harness and step 3 give it, and its probe opens and closes
one connection.

KVM here boots our startup-qemu-virt; this is not a QNX-supported
configuration, and no timing claim attaches to the boot.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True                  # nothing written into the tarball's tree by the import below
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vss_setup as vs  # noqa: E402

FORMAT = 1
SPECS = ("honest", "inject", "pause-tick", "pause-both", "injected-to-end", "injected-stop")
# The plans' recordings, each plan's honest one and its injected twin: sdv/stack/bundle.py's table,
# held equal by tests/test_vss_harness.py. carla's pair is Phase 7 WP5a's CARLA_HONEST and its -inj twin.
PLAN_RECORDINGS = {
    "v1": {"honest": "20260930-sigsim-1b", "injected": "20261002-sigsim-1b-inj4"},
    "v2": {"honest": "20260930-sigsim-1b", "injected": "20261002-sigsim-1b-inj4"},
    "carla": {"honest": "20261019-carla-1", "injected": "20261019-carla-1-inj"},
}
PLANS = tuple(PLAN_RECORDINGS)
MODES = ("broker", "can", "replay")
# step3.py's own (its GUEST MODE and freshness gate), kept equal by tests/test_vss_harness.py
GUEST_HOST = "192.168.100.10"         # the guest's static address on br0 (launch-qnx-kvm-bridged.sh's :7100 probe)
FRESH_LIVENESS = "LIVENESS"
FRESH_CLOSED = "client closed:"
FRESH_DONE_RX = re.compile(r"client done: seen=(\d+)")
RUN_DIR = re.compile(r"^\d{8}-(.+)$")          # stack.new_run_dir: SDV_RUNS/<YYYYMMDD>-<name>
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]+$")
ABOUT = ("run-vss-suite.sh's record (sdv-local, plan Phase 3 WP5): the VSS slice's step-3 runs on this host, each judged by "
         "the QNX guest's vss monitor on :7160 after a fresh boot, and the plan's comparisons.")
NOTE = ("A functional session: no field is a measurement and nothing is pre-registered. Docker is up on this host. Values "
        "under operational_s are whole seconds of this session's own units (a boot, a step-3 call, a compare), not timings "
        "of the guest or of the claim path.")


def one_line_text(s: str) -> str:
    return " ".join(s.replace("\t", " ").splitlines())


# --- plan -----------------------------------------------------------------------------------------------------------

def plan_units(plan: str, specs: Dict[str, Any]) -> List[Tuple[str, ...]]:
    """The plan's units in order (module docstring, plan)."""
    if plan == "v1":
        runs = [("honest", "replay"), ("honest", "broker")]
        compares: List[Tuple[Tuple[str, ...], str]] = []
    elif plan in ("v2", "carla"):            # carla: v2's units and compares over the CARLA pair
        runs = ([(s, "broker") for s in SPECS] + [(s, "replay") for s in SPECS] + [("injected-stop", "replay")]
                + [(s, "can") for s in SPECS])
        compares = [(("broker", "replay"), "always"), (("broker", "replay", "can"), "can-complete")]
    else:
        raise ValueError("no plan %r: %s" % (plan, ", ".join(PLANS)))
    recordings = PLAN_RECORDINGS[plan]
    out: List[Tuple[str, ...]] = []
    n = 0
    for spec, mode in runs:
        n += 1
        kind = specs[spec]["recording"]
        if kind not in recordings:
            raise ValueError("spec %s names a %r recording, which this harness has none of" % (spec, kind))
        out.append(("run", "%02d" % n, "%02d-%s-%s" % (n, spec, mode), spec, mode, recordings[kind]))
    for modes, when in compares:
        n += 1
        out.append(("compare", "%02d" % n, "%02d-compare-%s" % (n, "-".join(modes)), when, " ".join(modes)))
    return out


def cmd_plan(a: argparse.Namespace) -> int:
    try:
        with open(a.runs_file, encoding="utf-8") as f:
            specs = json.load(f)["specs"]
        units = plan_units(a.plan, specs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("the plan: %s" % one_line_text(str(exc)), file=sys.stderr)
        return 1
    for u in units:
        print("\t".join(u))
    return 0


# --- setup's record ----------------------------------------------------------------------------------------------------

def cmd_setup(a: argparse.Namespace) -> int:
    try:
        with open(a.setup, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        print("%s cannot be read: %s" % (a.setup, one_line_text(str(exc))))
        return 1
    if not isinstance(doc, dict) or doc.get("status") != "DONE":
        print("%s says status %r, not DONE" % (a.setup, doc.get("status") if isinstance(doc, dict) else None))
        return 1
    want, got = a.host_mode or "a1-metal", doc.get("host_mode", "a1-metal")
    if a.facts and a.host_mode is not None:
        vs.put(a.facts, "setup_host_mode", str(got))
    if got != want:
        print("%s records host mode %s (a setup.json with none is an a1.metal setup's), not this suite's %s: a setup of "
              "the other mode is refused" % (a.setup, one_line_text(str(got)), want))
        return 1
    modes, skip = doc.get("skip_modes"), doc.get("skip")
    if not isinstance(modes, list) or not isinstance(skip, list):
        print("%s holds no skip list (skip_modes and skip)" % a.setup)
        return 1
    unknown = sorted({str(m) for m in modes} - set(MODES))
    if unknown:
        print("%s skips modes the suite does not have: %s" % (a.setup, " ".join(unknown)))
        return 1
    facts = doc.get("facts")
    guest = facts.get("guest") if isinstance(facts, dict) else None
    if a.facts and isinstance(guest, dict):
        for k in ("booted",) + vs.GUEST_NEEDS:
            if k in guest:
                vs.put(os.path.join(a.facts, "setup_guest"), k, guest[k])
    problems = vs.guest_problems(guest)
    if problems is None:
        print("%s holds no guest verdict (facts.guest.booted): run-vss-setup.sh's step 3 records one" % a.setup)
        return 1
    if problems:
        print("%s: its guest booted, but %s: this suite boots the same image against the same images.json, so it cannot "
              "judge a run there (gap 4q)" % (a.setup, "; ".join(problems)))
        return 1
    reasons: Dict[str, List[str]] = {}
    for s in skip:
        if isinstance(s, dict):
            reasons.setdefault(str(s.get("mode")), []).append("%s: %s" % (s.get("step"), s.get("reason")))
    with open(a.skips, "w", encoding="utf-8", newline="\n") as f:
        for m in sorted({str(x) for x in modes}):
            f.write("%s\t%s\n" % (m, one_line_text("; ".join(reasons.get(m, [])) or "in setup.json's skip_modes")))
    print("skip %s" % (" ".join(sorted({str(x) for x in modes})) or "none"))
    return 0


def recordings_problems(names: List[str], rec_root: str, setup: Any, facts: str) -> List[str]:
    """The module docstring's recordings: each recording's own log (by its manifest line) under rec_root, and its line's
    profile among setup.json's facts.guest.profiles; facts into FACTS. Each refusal is a sentence."""
    problems = []
    guest = (setup.get("facts") or {}).get("guest") if isinstance(setup, dict) else None
    listed = guest.get("profiles") if isinstance(guest, dict) else None
    profiles = sorted({int(x) for x in listed if str(x).isdigit()}) if isinstance(listed, list) else None
    if isinstance(listed, list):
        vs.put(facts, "setup_profiles", [str(x) for x in listed])
    if profiles is None:
        problems.append("setup.json records no `vss rules:` profiles (facts.guest.profiles: run-vss-setup.sh's guest step "
                        "records them when its guest boots): PLAN=carla needs the list the image's lines agree on")
    seen = []
    for name in names:
        d = os.path.join(rec_root, name)
        log, why = vs.log_name(d)
        if log is None:
            problems.append("VSS_HOME/recordings/%s: %s" % (name, why))
            continue
        if not os.access(os.path.join(d, log), os.R_OK):
            problems.append("no VSS_HOME/recordings/%s/%s: setup did not stage it" % (name, log))
        with open(os.path.join(d, vs.MANIFEST_LINE), encoding="utf-8") as f:
            pid = json.load(f).get("profile_id")
        seen.append("%s %s profile %s" % (name, log, pid))
        if profiles is not None and pid not in profiles:
            problems.append("recording %s is judged under profile %s, which setup's `vss rules:` profiles %s do not list: the "
                            "image setup booted cannot judge it" % (name, pid, profiles))
    vs.put(facts, "recordings", seen)
    return problems


def cmd_recordings(a: argparse.Namespace) -> int:
    names = sorted({row[5] for row in vs.read_rows(a.plan_tsv, 6) if row[0] == "run"})
    try:
        with open(a.setup, encoding="utf-8") as f:
            setup = json.load(f)
    except (OSError, ValueError) as exc:
        print("%s cannot be read: %s" % (a.setup, one_line_text(str(exc))))
        return 1
    problems = recordings_problems(names, a.recordings, setup, a.facts)
    if problems:
        print(vs.one_line_join(problems))
        return 1
    return 0


def cmd_bridge_pin(a: argparse.Namespace) -> int:
    try:
        with open(a.images, encoding="utf-8") as f:
            pin = json.load(f)["bridge"]["arm64"]["id"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("images.json names no bridge.arm64.id: %s" % one_line_text(str(exc)))
        return 1
    if not isinstance(pin, str) or not DIGEST.match(pin):
        print("images.json's bridge.arm64.id %r is not one sha256 digest" % (pin,))
        return 1
    print(pin)
    return 0


# --- the readiness probe and the console ---------------------------------------------------------------------------------

def strip_console(raw: bytes) -> str:
    """step3.py's strip_console: every NUL and CR removed, anything that is not UTF-8 replaced."""
    return raw.replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", errors="replace")


def freshness(text: str) -> List[str]:
    """step3.py's freshness gate's problems, each anywhere in a line: a LIVENESS line, a `client closed:`, a `client done:`
    with seen above 0."""
    problems = []
    if FRESH_LIVENESS in text:
        problems.append("%d LIVENESS line(s)" % text.count(FRESH_LIVENESS))
    if FRESH_CLOSED in text:
        problems.append("%d `client closed:` line(s): what a probe held open past the guest's deadline leaves"
                        % text.count(FRESH_CLOSED))
    seen = [int(s) for s in FRESH_DONE_RX.findall(text)]
    if any(s > 0 for s in seen):
        problems.append("a `client done:` with seen above 0 (%s)" % ", ".join(str(s) for s in seen if s > 0))
    return problems


def cmd_ready(a: argparse.Namespace) -> int:
    attempts, ok, err = 0, False, ""
    for i in range(1, a.tries + 1):
        attempts = i
        try:
            socket.create_connection((a.host, a.port), timeout=a.bound).close()   # one step: opened, closed, no byte
            ok = True
            break
        except OSError as exc:
            err = type(exc).__name__
        if i < a.tries:
            time.sleep(a.gap)
    vs.put(a.facts, "ready_7160", ok)
    vs.put(a.facts, "ready_7160_attempts", attempts)
    if not ok:
        vs.put(a.facts, "ready_7160_error", err)
    else:
        time.sleep(a.settle)
    try:
        with open(a.console, "rb") as f:
            text = strip_console(f.read())
    except OSError:
        vs.put(a.facts, "console_readable", False)
        print("yes" if ok else "no")
        return 0
    vs.put(a.facts, "console_readable", True)
    vs.put(a.facts, "banner_7160_seen", vs.BANNER_7160 in text)
    if ok:
        problems = freshness(text)
        vs.put(a.facts, "fresh_before_step3", not problems)
        vs.put(a.facts, "fresh_problems", problems)
    print("yes" if ok else "no")
    return 0


# --- step 3's directories ----------------------------------------------------------------------------------------------

def run_dirs(runs: str, name: str) -> List[str]:
    out = []
    for d in sorted(glob.glob(os.path.join(runs, "*"))):
        m = RUN_DIR.match(os.path.basename(d))
        if m and m.group(1) == name and os.path.isdir(d):
            out.append(d)
    return out


def rel_dir(runs: str, d: str) -> str:
    return "%s/%s" % (os.path.basename(os.path.normpath(runs)), os.path.basename(d))


def cmd_run_facts(a: argparse.Namespace) -> int:
    try:
        with open(a.console, "rb") as f:
            raw = f.read()
        vs.put(a.facts, "console_sha256", hashlib.sha256(raw).hexdigest())
        vs.put(a.facts, "console_bytes", len(raw))
    except OSError:
        vs.put(a.facts, "console_sha256", "unreadable")
    dirs = run_dirs(a.runs, a.name)
    if len(dirs) != 1:
        vs.put(a.facts, "dir_found", False)
        vs.put(a.facts, "dirs_matching", len(dirs))
        vs.put(a.facts, "result", False)
        return 0
    d = dirs[0]
    vs.put(a.facts, "dir_found", True)
    vs.put(a.facts, "dir", rel_dir(a.runs, d))
    vs.put(a.facts, "step3_json", os.path.isfile(os.path.join(d, "step3.json")))
    results = []
    for p in sorted(glob.glob(os.path.join(d, "*", "result.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(r, dict) and r.get("step3") == 1:
            results.append(r)
    if len(results) != 1:
        vs.put(a.facts, "result", False)
        vs.put(a.facts, "results_found", len(results))
        print(d)
        return 0
    r = results[0]
    vs.put(a.facts, "result", True)
    vs.put(a.facts, "run", str(r.get("run")))
    vs.put(a.facts, "result_ok", r.get("ok") is True)
    gates = r.get("gates")
    if isinstance(gates, dict):
        for k, v in sorted(gates.items()):
            key = str(k) if SAFE_KEY.match(str(k)) else "gate-%d" % len(str(k))
            vs.put(os.path.join(a.facts, "gates"), key, v is True)
    if isinstance(r.get("c12b_lines"), int) and not isinstance(r.get("c12b_lines"), bool):
        vs.put(a.facts, "c12b_lines", r["c12b_lines"])
    print(d)
    return 0


def cmd_compare_facts(a: argparse.Namespace) -> int:
    dirs = run_dirs(a.runs, a.name)
    if len(dirs) != 1:
        vs.put(a.facts, "compare_json", False)
        return 0
    vs.put(a.facts, "dir", rel_dir(a.runs, dirs[0]))
    try:
        with open(os.path.join(dirs[0], "compare.json"), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        vs.put(a.facts, "compare_json", False)
        return 0
    vs.put(a.facts, "compare_json", True)
    vs.put(a.facts, "compare_ok", isinstance(doc, dict) and doc.get("ok") is True)
    if not isinstance(doc, dict):
        return 0
    left = doc.get("left_out")
    if isinstance(left, list):
        vs.put(a.facts, "left_out", [str(x.get("run") if isinstance(x, dict) else x) for x in left])
    groups = doc.get("groups")
    if isinstance(groups, list):
        for i, g in enumerate(groups):
            if not isinstance(g, dict):
                continue
            spec = str(g.get("spec"))
            key = spec if SAFE_KEY.match(spec) else "group-%d" % (i + 1)
            gd = os.path.join(a.facts, "groups", key)
            vs.put(gd, "ok", g.get("ok") is True)
            vs.put(gd, "problems", [str(p) for p in (g.get("problems") or [])])
    return 0


# --- the record -----------------------------------------------------------------------------------------------------------

def cmd_record(a: argparse.Namespace) -> int:
    units = vs.read_rows(os.path.join(a.work, "plan.tsv"), 6)
    facts = vs.read_facts(os.path.join(a.work, "facts"))
    skip_modes: List[str] = []
    skip: List[Any] = []
    try:
        with open(a.setup, encoding="utf-8") as f:
            sdoc = json.load(f)
        if isinstance(sdoc, dict):
            skip_modes = sorted(str(m) for m in (sdoc.get("skip_modes") or []))
            skip = [s for s in (sdoc.get("skip") or []) if isinstance(s, dict)]
    except (OSError, ValueError):
        pass
    runs: List[Dict[str, Any]] = []
    compares: List[Dict[str, Any]] = []
    not_run: List[str] = []
    for kind, nn, name, x, y, z in units:
        f = dict(facts.get(name) or {})
        state = f.pop("state", None) or "not-run"
        e: Dict[str, Any]
        if kind == "run":
            e = {"nn": nn, "name": name, "spec": x, "mode": y, "recording": z, "state": state}
            e.update(f)
            e["ok"] = state == "ran" and f.get("step3_exit") == 0 and f.get("result_ok") is True
            runs.append(e)
        elif kind == "compare":
            e = {"nn": nn, "name": name, "when": x, "state": state}
            e.update(f)
            e["modes"] = y.split()
            e["ok"] = state == "ran" and f.get("exit") == 0 and f.get("compare_ok") is True
            compares.append(e)
        else:
            continue
        if state == "not-run":
            not_run.append(name)
    suite = facts.get("suite") or {}
    doc: Dict[str, Any] = {"format": FORMAT, "harness": "run-vss-suite.sh"}
    if a.host_mode:
        doc.update({"host_mode": a.host_mode, "container_cpuset": a.cpuset or None})
    doc.update({"about": ABOUT, "note": NOTE, "plan": a.plan or None,
                "status": a.status, "status_line": a.status_line, "at": a.at or None, "reason": a.reason or None,
                "skip_modes": skip_modes, "skip": skip, "preflight": facts.get("preflight") or {}, "runs": runs,
                "compares": compares, "not_run": not_run,
                "can_complete": suite.get("can_complete") if isinstance(suite, dict) else None,
                "plan_stopped_after": suite.get("plan_stopped_after") if isinstance(suite, dict) else None,
                "stop": facts.get("stop") or {}})
    vs.write_json(a.out, doc)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--plan", required=True)
    p.add_argument("--runs-file", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--setup", required=True)
    s.add_argument("--skips", required=True)
    s.add_argument("--facts", default="")
    s.add_argument("--host-mode", default=None)
    o = sub.add_parser("orin-check")
    for x in ("--facts", "--default-deadline", "--subtree"):
        o.add_argument(x, required=True)
    b = sub.add_parser("bridge-pin")
    b.add_argument("--images", required=True)
    rec = sub.add_parser("recordings")
    for x in ("--plan-tsv", "--recordings", "--setup", "--facts"):
        rec.add_argument(x, required=True)
    r = sub.add_parser("ready")
    r.add_argument("--host", required=True)
    r.add_argument("--port", type=int, required=True)
    r.add_argument("--tries", type=int, required=True)
    r.add_argument("--bound", type=float, required=True)
    r.add_argument("--gap", type=float, required=True)
    r.add_argument("--settle", type=float, required=True)
    r.add_argument("--console", required=True)
    r.add_argument("--facts", required=True)
    f = sub.add_parser("run-facts")
    for x in ("--runs", "--name", "--console", "--facts"):
        f.add_argument(x, required=True)
    c = sub.add_parser("compare-facts")
    for x in ("--runs", "--name", "--facts"):
        c.add_argument(x, required=True)
    w = sub.add_parser("record")
    for x in ("--work", "--out", "--setup", "--status", "--status-line"):
        w.add_argument(x, required=True)
    for x in ("--plan", "--at", "--reason", "--host-mode", "--cpuset"):
        w.add_argument(x, default="")
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "setup": cmd_setup, "bridge-pin": cmd_bridge_pin, "ready": cmd_ready, "run-facts": cmd_run_facts,
            "compare-facts": cmd_compare_facts, "record": cmd_record, "orin-check": vs.cmd_orin_check,
            "recordings": cmd_recordings}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
