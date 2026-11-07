#!/usr/bin/env python3
"""vss_setup.py -- run-vss-setup.sh's records: its facts into setup.json and probes.json, and the few readings it takes
from other tools' output. plan Phase 3 (WP4), 2026-10-03.

Standard library only, and Python 3.10 (the instance's system python3, before the venv exists): nothing here may need a
later Python. Run by the harness, one subcommand per call:

  record --work W --out F --status S --status-line L --at A --reason R --steps "NAME ..." [--host-mode orin|c7g-metal]
        setup.json from W: steps.tsv (one row per step run: n, name, UTC start and end, whole seconds, exit status,
        outcome), the facts under W/facts and W/skip.tsv (mode, step, reason), written whole: a temporary file beside
        F, then a rename. --host-mode (the Orin mode's, and the c7g-metal mode's: the a1.metal path on c7g.metal)
        puts host_mode after harness; without it the document is an a1.metal setup's, with no host_mode key
        (run-vss-suite.sh reads none as a1-metal).
  orin-check --facts D --default-deadline PATH --subtree PATH
        the Orin mode's checks before step 1 (run-vss-suite.sh runs the same through vss_suite.py):
        QNX_METAL_DEADLINE_FILE set and not the deadline library's default PATH (that
        file belongs to an AWS instance); VSS_REPIN an absolute path of an executable file, every character a letter,
        a digit or one of ./_+- (the suite passes it to step 3 as SDV_AFTER_START, which shlex splits); `cpuset` among
        the controllers of --subtree (system.slice's cgroup.subtree_control: turning it on is a host change, and plan
        3.7 wants it on before the guest); SDV_CONTAINER_CPUSET by CPUSET RULE below. It reads those three variables
        from its environment. Facts into D (host_mode, and container_cpuset, repin and system_slice_cpuset as found);
        prints its refusals on one line, joined by "; ", and exits 1 when there is any.
  probes-json --work W --out F
        probes.json from W/probes/<image>/ and the probes' rows of W/skip.tsv, written the same way.
  rules --console F --images IMAGES_JSON --facts D
        C12b's reading of a guest console: NUL and CR removed, every `monitor: vss rules:` line parsed with
        attribution.py's pattern (a test holds the two equal), their count, whether all that parse agree, the catalog
        and whether it is the bridge pin's label, the profile list they agree on (profiles, one per line; none when no
        line parses or two disagree: SDV Phase 7 WP3b, which run-vss-suite.sh's PLAN=carla preflight
        reads), and whether the :7160 banner appears (information only: banners interleave). Facts into D; prints the
        count.
  log --dir D
        a recording directory's log by its manifest line (SDV Phase 7 WP3b): the basename of the line's
        recording.path when it is its source.generator's (LOG_NAMES: sigsim.log for sigsim, carla.log for carla); prints
        it. A line that cannot be read, is no JSON object, or pairs a generator with another log (another name, another
        generator) prints its refusal on one line, naming both, and exits 1. run-vss-setup.sh stages each rec-*.tar by it,
        and run-vss-suite.sh's PLAN=carla preflight (vss_suite.py recordings) reads it the same way.
  smoke   latency_probe.py's output on stdin; prints `result_line yes|no`, `bad N|none`, `rej N|none` and nothing else:
        the probe's latency fields never leave this process.
  bundle --facts D --prefix P
        bundle.py's one JSON record on stdin (its last line that is a JSON object): ok, commit, problems, and the
        loaded or upstream images' selected fields, as facts P* in D; prints each problem. Never the raw record.
  driver-type   `docker info -f '{{json .DriverStatus}}'` on stdin; prints its driver-type, or nothing.
  field --file F --key K        prints a top-level string of a JSON file (exit 1 when there is none).
  images --file IMAGES_JSON [--kind upstream]
        `upstream NAME REPO@INDEX_DIGEST`, `local NAME ID` and `bridge bridge ID` lines from images.json.
  iptables-counts   `iptables-save` on stdin; prints `TABLE=N ...` (the -A rules per table, in order), or `no tables`.
  guest-verdict --work W
        three lines for the close's run.log (wait-run prints its last 30): the guest step's verdict and the smokes, whether
        run-vss-suite.sh takes this setup's guest or why it will refuse it (guest_problems, the rule the suite applies),
        and the skip list.

THE GUEST RULE. Setup records its guest's readiness, C12b and catalog as information and goes
on. The suite boots the same image against the same images.json, so a guest that booted here with any of GUEST_NEEDS not
true is one the suite cannot judge: it refuses the setup at its preflight. A guest that did not boot is not judged here:
each suite run boots afresh and records its own boot.

CPUSET RULE. SDV_CONTAINER_CPUSET is a CPU list N[,N...] of
distinct decimal integers, with no space, no range and no leading zero; never empty; and never holding 0, 1 or 2
(QEMU's cores on the Orin) or 4 (the probe's core). The setup's probe containers and the stack's containers take it as
--cpuset-cpus, and the suite runs step 3 under `taskset -c` with it.

FACTS. The harness keeps each fact as a file W/facts/<step>/<key>.<type> (a key holding "/" is a nested object): .s a
string, .i an integer, .b true or false, .lines an array of lines. The writer turns every string that holds a line break
into an array of its lines, over the whole document, so every JSON string the harness writes is one line; a
multi-line output becomes an array of lines, never a string.

Does not demonstrate: anything; it only reads and writes what the harness gives it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

FORMAT = 1
# attribution.py's _VSS_RULES (sdv/stack/attribution.py), kept equal by tests/test_vss_harness.py
VSS_RULES = re.compile(r"^monitor: vss rules: kind 4, catalog (0x[0-9A-F]{8}) \(vss [^)]*\), age_max (\d+) ms, profiles ([0-9 ]+)$")
BANNER_7160 = "service monitor listening on :7160 "     # stack.py's text of the :7160 banner
CATALOG_LABEL = "sdv.kind4.catalog_digest"
SETUP_ABOUT = ("run-vss-setup.sh's record (sdv-local, plan Phase 3 WP4): Docker, the images, the venv, vcan and the "
               "staged inputs brought up on this host for run-vss-suite.sh, the guest's smokes before and after Docker, "
               "and each image's SIGILL probe.")
NOTE = ("A functional session: no field is a measurement and nothing is pre-registered. Docker is up on this host. Values "
        "under operational_s are whole seconds of this session's own steps (decision 16's input), not timings of the guest.")
PROBES_ABOUT = ("run-vss-setup.sh's SIGILL probes (plan Phase 3 WP4, prep gap 4f): each image's start-up run on this host, "
                "its exit status, and the kernel's 'undefined instruction' lines logged since it began.")
GUEST_NEEDS = ("ready_7160", "c12b_ok", "catalog_is_bridge_label")     # the module docstring, THE GUEST RULE
# A recording's log by its manifest line's source.generator (the module docstring, log): sdv/inject/inject.py's
# LOG_NAMES, held equal by tests/test_vss_harness.py (standard library only, so this module keeps its own copy).
LOG_NAMES = {"sigsim": "sigsim.log", "carla": "carla.log"}
MANIFEST_LINE = "manifest-line.json"
# The module docstring, CPUSET RULE: QEMU's cores 0-2 and the probe's core 4 on the Orin are never a container's
NOT_CONTAINER_CPUS = (0, 1, 2, 4)
CPU_LIST = re.compile(r"(0|[1-9][0-9]*)(,(0|[1-9][0-9]*))*")
REPIN_PATH = re.compile(r"/[A-Za-z0-9._/+-]+")                       # one shlex word, nothing to quote


def one_line(o: Any) -> Any:
    """The document with every string that holds a line break turned into the array of its lines."""
    if isinstance(o, dict):
        return {k: one_line(v) for k, v in o.items()}
    if isinstance(o, list):
        return [one_line(v) for v in o]
    if isinstance(o, str) and ("\n" in o or "\r" in o):
        return o.splitlines()
    return o


def write_json(path: str, doc: Dict[str, Any]) -> None:
    """The document, whole: a temporary file beside path, then a rename."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(one_line(doc), f, indent=1)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_text(path: str) -> str:
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "replace")


def read_facts(d: str) -> Dict[str, Any]:
    """The facts under d (the module docstring, FACTS)."""
    out: Dict[str, Any] = {}
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isdir(p):
            out[name] = read_facts(p)
            continue
        key, _dot, kind = name.rpartition(".")
        if not key:
            continue
        text = read_text(p)
        if kind == "i":
            try:
                out[key] = int(text.strip())
            except ValueError:
                out[key] = text
        elif kind == "b":
            out[key] = text.strip() == "true"
        elif kind == "lines":
            out[key] = text.splitlines()
        else:
            out[key] = text
    return out


def read_rows(path: str, width: int) -> List[List[str]]:
    if not os.path.exists(path):
        return []
    rows = []
    for ln in read_text(path).splitlines():
        if ln.strip():
            cells = ln.split("\t")
            rows.append((cells + [""] * width)[:width])
    return rows


def skips(work: str, step: Optional[str] = None) -> List[Dict[str, str]]:
    out = []
    for mode, st, why in read_rows(os.path.join(work, "skip.tsv"), 3):
        if step is None or st == step:
            out.append({"mode": mode, "step": st, "reason": why})
    return out


def as_int(s: str) -> Any:
    try:
        return int(s)
    except ValueError:
        return s


def cmd_record(a: argparse.Namespace) -> int:
    declared = a.steps.split()
    steps = []
    for n, name, start, end, secs, rc, outcome in read_rows(os.path.join(a.work, "steps.tsv"), 7):
        steps.append({"n": as_int(n), "name": name, "start_utc": start, "end_utc": end, "operational_s": {"step": as_int(secs)},
                      "rc": as_int(rc), "outcome": outcome})
    ran = {s["name"] for s in steps}
    sk = skips(a.work)
    doc: Dict[str, Any] = {"format": FORMAT, "harness": "run-vss-setup.sh"}
    if a.host_mode:
        doc["host_mode"] = a.host_mode
    doc.update({"about": SETUP_ABOUT, "note": NOTE, "status": a.status,
                "status_line": a.status_line, "at": a.at or None, "reason": a.reason or None, "steps": steps,
                "not_run": [s for s in declared if s not in ran], "skip_modes": sorted({s["mode"] for s in sk}), "skip": sk,
                "facts": read_facts(os.path.join(a.work, "facts"))})
    write_json(a.out, doc)
    return 0


def cpuset_problem(value: Optional[str]) -> Optional[str]:
    """SDV_CONTAINER_CPUSET's value against the module docstring's CPUSET RULE: None when it holds, else why not."""
    if value is None:
        return "SDV_CONTAINER_CPUSET is not set: the Orin mode places every container by it"
    if value == "":
        return "SDV_CONTAINER_CPUSET is empty"
    if not CPU_LIST.fullmatch(value):
        return "SDV_CONTAINER_CPUSET is not a CPU list N[,N...] of decimal integers (no space, no range, no leading zero)"
    cpus = [int(x) for x in value.split(",")]
    if len(set(cpus)) != len(cpus):
        return "SDV_CONTAINER_CPUSET names a CPU twice"
    held = sorted(set(cpus) & set(NOT_CONTAINER_CPUS))
    if held:
        return ("SDV_CONTAINER_CPUSET holds %s: QEMU's cores (0-2) and the probe's core (4) are never a container's"
                % ", ".join(str(c) for c in held))
    return None


def orin_problems(env: Dict[str, str], default_deadline: str, subtree: str, facts: str) -> List[str]:
    """The Orin mode's checks (the module docstring, orin-check), each refusal a sentence; facts into FACTS."""
    problems = []
    put(facts, "host_mode", "orin")
    deadline = env.get("QNX_METAL_DEADLINE_FILE", "")
    if not deadline:
        problems.append("QNX_METAL_DEADLINE_FILE is not set (or is empty): the Orin mode's deadline is a file the helper "
                        "writes, never the deadline library's default, which belongs to an AWS instance")
    elif os.path.realpath(deadline) == os.path.realpath(default_deadline):
        problems.append("QNX_METAL_DEADLINE_FILE is the deadline library's default (%s), which belongs to an AWS instance"
                        % default_deadline)
    repin = env.get("VSS_REPIN")
    if repin is not None:
        put(facts, "repin", repin)
    if not repin:
        problems.append("VSS_REPIN is not set: the Orin mode re-pins QEMU through it after each boot")
    elif not repin.startswith("/"):
        problems.append("VSS_REPIN is not an absolute path")
    elif not REPIN_PATH.fullmatch(repin):
        problems.append("VSS_REPIN holds a character other than a letter, a digit or ./_+- (SDV_AFTER_START is split "
                        "with shlex)")
    elif not (os.path.isfile(repin) and os.access(repin, os.X_OK)):
        problems.append("VSS_REPIN is not an executable file")
    try:
        controllers = read_text(subtree).split()
    except OSError:
        controllers = None
        problems.append("%s cannot be read: whether system.slice has the cpuset controller is not known" % subtree)
    if controllers is not None:
        put(facts, "system_slice_cpuset", "cpuset" in controllers)
        if "cpuset" not in controllers:
            problems.append("cpuset is not among system.slice's subtree controllers (%s): turning it on is a host change, "
                            "and plan 3.7 wants it on before the guest" % subtree)
    cpuset = env.get("SDV_CONTAINER_CPUSET")
    if cpuset is not None:
        put(facts, "container_cpuset", cpuset)
    why = cpuset_problem(cpuset)
    if why:
        problems.append(why)
    return problems


def cmd_orin_check(a: argparse.Namespace) -> int:
    problems = orin_problems(dict(os.environ), a.default_deadline, a.subtree, a.facts)
    if problems:
        print(one_line_join(problems))
        return 1
    return 0


def one_line_join(items: List[str]) -> str:
    return "; ".join(" ".join(x.split()) for x in items)


def cmd_probes_json(a: argparse.Namespace) -> int:
    sk = skips(a.work, "probes")
    doc = {"format": FORMAT, "about": PROBES_ABOUT, "note": NOTE, "probes": read_facts(os.path.join(a.work, "probes")),
           "skip_modes": sorted({s["mode"] for s in sk}), "skip": sk}
    write_json(a.out, doc)
    return 0


def put(d: str, key: str, value: Any) -> None:
    """One fact file (the module docstring, FACTS)."""
    if isinstance(value, bool):
        kind, text = "b", "true" if value else "false"
    elif isinstance(value, int):
        kind, text = "i", str(value)
    elif isinstance(value, list):
        kind, text = "lines", "".join("%s\n" % x for x in value)
    else:
        kind, text = "s", "" if value is None else str(value)
    p = os.path.join(d, "%s.%s" % (key, kind))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    for old in ("s", "i", "b", "lines"):          # a fact rewritten with another type replaces the old one
        q = os.path.join(d, "%s.%s" % (key, old))
        if q != p and os.path.exists(q):
            os.remove(q)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def cmd_rules(a: argparse.Namespace) -> int:
    try:
        with open(a.console, "rb") as f:
            text = f.read().replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", "replace")
        readable = True
    except OSError:
        text, readable = "", False                 # recorded as such: C12b then has no line to read
    put(a.facts, "console_readable", readable)
    found = []
    for line in text.splitlines():
        m = VSS_RULES.match(line.strip())
        if m:
            found.append((m.group(1), int(m.group(2)), tuple(int(x) for x in m.group(3).split())))
    agree = bool(found) and len(set(found)) == 1
    catalog = found[0][0] if agree else ""
    label = ""
    try:
        with open(a.images, encoding="utf-8") as f:
            label = str(((json.load(f).get("bridge") or {}).get("labels") or {}).get(CATALOG_LABEL) or "")
    except (OSError, ValueError):
        label = ""
    put(a.facts, "c12b_lines", len(found))
    put(a.facts, "c12b_agree", agree)
    put(a.facts, "c12b_ok", agree)                # at least one line that parses, and all that parse agree
    put(a.facts, "catalog", catalog)
    put(a.facts, "catalog_is_bridge_label", bool(catalog) and catalog == label)
    put(a.facts, "profiles", [str(p) for p in found[0][2]] if agree else [])     # the list the lines agree on (SDV Phase 7 WP3b)
    put(a.facts, "banner_7160_seen", BANNER_7160 in text)
    print(len(found))
    return 0


def log_name(d: str) -> Tuple[Optional[str], str]:
    """The log a recording directory's manifest line names (the module docstring, log): (its name, ""), or (None, why)."""
    where = os.path.join(os.path.basename(os.path.normpath(d)), MANIFEST_LINE)
    try:
        line = json.loads(read_text(os.path.join(d, MANIFEST_LINE)))
    except OSError as exc:
        return None, "%s cannot be read: %s" % (where, exc.strerror or exc)
    except ValueError:
        line = None
    if not isinstance(line, dict):
        return None, "%s is not a JSON object" % where
    rec, source = line.get("recording"), line.get("source")
    gen = source.get("generator") if isinstance(source, dict) else None
    path = rec.get("path") if isinstance(rec, dict) else None
    base = path.rsplit("/", 1)[-1] if isinstance(path, str) else None
    if not isinstance(gen, str) or gen not in LOG_NAMES:
        return None, "%s pairs generator %r with the log %r: this harness reads %s recordings only" % (
            where, gen, base, " and ".join(sorted(LOG_NAMES)))
    if base != LOG_NAMES[gen]:
        return None, "%s pairs generator %r with the log %r: a %s recording's log is %s" % (where, gen, base, gen, LOG_NAMES[gen])
    return base, ""


def cmd_log(a: argparse.Namespace) -> int:
    name, why = log_name(a.dir)
    if name is None:
        print(one_line_join([why]))
        return 1
    print(name)
    return 0


def cmd_smoke(_a: argparse.Namespace) -> int:
    res = None
    for line in sys.stdin.read().splitlines():
        if line.startswith("RESULT "):
            try:
                doc = json.loads(line[len("RESULT "):])
            except ValueError:
                continue
            if isinstance(doc, dict):
                res = doc
    if res is None:
        print("result_line no\nbad none\nrej none")
        return 0
    bad, rej = res.get("bad"), res.get("rejected_by_monitor")
    print("result_line yes")
    print("bad %s" % (bad if isinstance(bad, int) and not isinstance(bad, bool) else "none"))
    print("rej %s" % (rej if isinstance(rej, int) and not isinstance(rej, bool) else "none"))
    return 0


def last_record(text: str) -> Optional[Dict[str, Any]]:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict):
                return doc
    return None


def cmd_bundle(a: argparse.Namespace) -> int:
    rec = last_record(sys.stdin.read())
    p = a.prefix
    if rec is None:
        rec = {"ok": False, "problems": ["bundle.py printed no JSON record"]}
    problems = [str(x) for x in (rec.get("problems") or [])]
    put(a.facts, p + "ok", rec.get("ok") is True)
    put(a.facts, p + "problems", [ln for x in problems for ln in x.splitlines()])
    if isinstance(rec.get("commit"), str):
        put(a.facts, p + "commit", rec["commit"])
    docker = rec.get("docker")
    if isinstance(docker, dict):
        put(a.facts, p + "docker_server", str(docker.get("server")))
        put(a.facts, p + "docker_driver_type", str(docker.get("driver_type")))
    loaded = rec.get("loaded_images")
    if isinstance(loaded, dict):
        put(a.facts, p + "loaded_images", ["%s %s %s" % (n, (v or {}).get("id"), (v or {}).get("platform"))
                                            for n, v in sorted(loaded.items())])
    images = rec.get("images")
    if isinstance(images, dict) and rec.get("tool") == "bundle.py verify-upstream":
        put(a.facts, p + "images", ["%s %s %s revision %s in_repo_digests %s" % (
            n, (v or {}).get("id"), (v or {}).get("platform"), (v or {}).get("revision"), (v or {}).get("in_repo_digests"))
            for n, v in sorted(images.items())])
    for x in problems:
        print("bundle.py: %s" % x)
    return 0


def cmd_driver_type(_a: argparse.Namespace) -> int:
    try:
        pairs = json.loads(sys.stdin.read() or "null") or []
        value = dict((str(k), str(v)) for k, v in pairs).get("driver-type", "")
    except (ValueError, TypeError):
        value = ""
    print(value)
    return 0


def cmd_field(a: argparse.Namespace) -> int:
    try:
        with open(a.file, encoding="utf-8") as f:
            value = json.load(f).get(a.key)
    except (OSError, ValueError, AttributeError):
        return 1
    if not isinstance(value, str):
        return 1
    print(value)
    return 0


def cmd_images(a: argparse.Namespace) -> int:
    with open(a.file, encoding="utf-8") as f:
        images = json.load(f)
    for name, u in sorted(images["upstream"].items()):
        print("upstream %s %s@%s" % (name, u["repo"], u["index_digest"]))
    if a.kind == "upstream":
        return 0
    for name, spec in sorted(images["local"].items()):
        print("local %s %s" % (name, spec["arm64"]["id"]))
    print("bridge bridge %s" % images["bridge"]["arm64"]["id"])
    return 0


def word(v: Any) -> str:
    return "missing" if v is None else json.dumps(v)


def guest_problems(g: Any) -> Optional[List[str]]:
    """THE GUEST RULE (module docstring) over setup.json's facts.guest: None when it holds no verdict (no boolean booted),
    [] when the suite takes it (the guest passed, or did not boot here), else each of GUEST_NEEDS that is not true."""
    if not isinstance(g, dict) or not isinstance(g.get("booted"), bool):
        return None
    if not g["booted"]:
        return []
    return ["%s is %s" % (k, word(g.get(k))) for k in GUEST_NEEDS if g.get(k) is not True]


def cmd_guest_verdict(a: argparse.Namespace) -> int:
    facts = read_facts(os.path.join(a.work, "facts"))
    g = facts.get("guest")
    smokes = ", ".join("smoke %d %s" % (n, "PASS" if (facts.get("smoke-%d" % n) or {}).get("pass") is True else "FAIL")
                       for n in (1, 2))
    gd: Dict[str, Any] = g if isinstance(g, dict) else {}
    shown = ("booted",) if gd.get("booted") is False else ("booted",) + GUEST_NEEDS
    print("the guest's verdict (step 3): %s; %s" % (", ".join("%s %s" % (k, word(gd.get(k))) for k in shown), smokes))
    problems = guest_problems(g)
    if problems is None:
        print("run-vss-suite.sh will refuse this setup: setup.json will hold no guest verdict")
    elif problems:
        print("run-vss-suite.sh will refuse this setup: its guest booted, but %s" % "; ".join(problems))
    elif gd.get("booted") is False:
        print("run-vss-suite.sh takes this setup: its guest did not boot here, and each suite run boots its own")
    else:
        print("run-vss-suite.sh takes this setup's guest")
    print("the skip list: %s" % (" ".join(sorted({s["mode"] for s in skips(a.work)})) or "none"))
    return 0


def cmd_iptables_counts(_a: argparse.Namespace) -> int:
    counts: Dict[str, int] = {}
    table = ""
    for line in sys.stdin.read().splitlines():
        if line.startswith("*"):
            table = line[1:].strip()
            counts.setdefault(table, 0)
        elif line.startswith("-A") and table:
            counts[table] += 1
    print(" ".join("%s=%d" % kv for kv in counts.items()) if counts else "no tables")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    for x in ("--work", "--out", "--status", "--status-line", "--steps"):
        r.add_argument(x, required=True)
    r.add_argument("--at", default="")
    r.add_argument("--reason", default="")
    r.add_argument("--host-mode", default="")
    o = sub.add_parser("orin-check")
    for x in ("--facts", "--default-deadline", "--subtree"):
        o.add_argument(x, required=True)
    p = sub.add_parser("probes-json")
    p.add_argument("--work", required=True)
    p.add_argument("--out", required=True)
    u = sub.add_parser("rules")
    u.add_argument("--console", required=True)
    u.add_argument("--images", required=True)
    u.add_argument("--facts", required=True)
    sub.add_parser("smoke")
    b = sub.add_parser("bundle")
    b.add_argument("--facts", required=True)
    b.add_argument("--prefix", required=True)
    sub.add_parser("driver-type")
    f = sub.add_parser("field")
    f.add_argument("--file", required=True)
    f.add_argument("--key", required=True)
    i = sub.add_parser("images")
    i.add_argument("--file", required=True)
    i.add_argument("--kind", choices=("upstream", "all"), default="all")
    sub.add_parser("iptables-counts")
    g = sub.add_parser("guest-verdict")
    g.add_argument("--work", required=True)
    lg = sub.add_parser("log")
    lg.add_argument("--dir", required=True)
    a = ap.parse_args(argv)
    return {"record": cmd_record, "probes-json": cmd_probes_json, "rules": cmd_rules, "smoke": cmd_smoke, "bundle": cmd_bundle,
            "driver-type": cmd_driver_type, "field": cmd_field, "images": cmd_images,
            "iptables-counts": cmd_iptables_counts, "guest-verdict": cmd_guest_verdict, "orin-check": cmd_orin_check,
            "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
