#!/usr/bin/env python3
"""aw_setup.py -- run-aw-setup.sh's readings of its inputs and its record, setup.json; and what run-aw-suite.sh shares with
it (2.7's DDS file, the meminfo reading). SDV Phase 8 WP6 9.2.

Standard library only, and Python 3.10 (the instance's system python3 runs it). The facts and the record's writer are
vss_setup.py's (its FACTS, its one-line writer), imported from beside it. Run by the harness, one subcommand per call; a
refusal prints its reason on one line (several joined by "; ") and exits 1.

  vss-setup --setup SETUP_JSON --host-mode M --facts D
        run-vss-setup.sh's raw/setup.json: its status DONE and its host_mode M (none is a1-metal, which the aw session
        never is: the owner, 2026-10-24). Facts into D (setup_status, setup_host_mode).
  inputs --aw-in DIR --inputs-env F --repo-tar T --facts D --txt OUT
        the aw inputs (THE AW INPUTS below): aw-inputs.json and every file it lists, each of its sha256 and in inputs.env's
        FILES with that sha256 (as remote-ladder.sh's setup checked it before it moved the aw files out of in/), nothing
        else in DIR, and its commit the repo tarball's (the pax header git get-tar-commit-id reads). Facts into D/inputs;
        OUT (inputs.txt, 2.11) gets one line per file, `NAME SHA256 ok|<why>`, then the commits.
  scan --scan F --images IMAGES_JSON --facts D --txt OUT
        9.1's aw-scan.json: its image_digest must be the digest this harness pulls (images.json's
        autoware.arm64.manifest_digest); its verdict, finding and ELF counts and exceptions applied are recorded, the
        verdict not required (the owner's decision of 2026-10-24). Facts into D/scan; one line appended to OUT (inputs.txt):
        the reference to pull and the scan's.
  ref --images IMAGES_JSON
        prints the reference this harness pulls and the suite runs: autoware.repo@autoware.arm64.manifest_digest.
  dds --env ROS_ENV_JSON --out XML
        2.7's ROS environment: writes cyclonedds_single_host, as it is, to XML (made with its directory) and prints
        `DOMAIN RMW`. Refused: a format other than 1, a domain that is not an integer in 0..232, an empty rmw or XML.
  stage-map --tar T --scenario S --dest D --facts F
        aw-map.tar into D/<the scenario's map name>/: exactly the scenario's map files, each a regular file under that one
        directory, each of the scenario's sha256 (a link, a device, an absolute path, a "..", another file or a missing
        one refused before anything is written); D/<name> must not exist yet. Facts into F (map, files, files_ok).
  inspect --ref R --facts D
        `docker image inspect R`'s JSON on stdin: the ID, RepoDigests, Os and Architecture as facts (never the raw
        inspect); exit 1 unless RepoDigests holds R.
  meminfo --file F
        prints /proc/meminfo's MemAvailable in kB, or nothing (exit 1) when it cannot be read.
  record --work W --out F --status S --status-line L --at A --reason R --steps "NAME ..." --host-mode M
        setup.json from W: steps.tsv (n, name, UTC start and end, whole seconds, exit status, outcome), the facts under
        W/facts, written whole (a temporary file beside F, then a rename): status, the steps and those not run, the image
        pulled (its reference and the ID read back), budget_short (D7's rule, for the suite's preflight) and every fact.

THE AW INPUTS (METAL_FILES beside the upload bundle, each name beginning `aw-`; remote-ladder.sh's setup checks their
hashes and moves them from in/ to aw-in/, since run-vss-setup.sh's `bundle.py verify` refuses a file in in/ that
bundle.json does not list):
  aw-inputs.json  {"format": 1, "commit": "<40 hex>", "files": {"<aw-name>": "<sha256>", ...}}: the commit the inputs
                  were made for (the repo tarball's) and every other aw input with its sha256; it must list aw-scan.json
                  and aw-map.tar
  aw-scan.json    9.1's output for the arm64 image ({"format": 1, "image_digest", "elf_files", "findings",
                  "exceptions_applied", "verdict"})
  aw-map.tar      the scenario's map: <map name>/<file> for exactly the files the scenario names

Does not demonstrate: anything; it reads and writes what the harness gives it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
from typing import Any, Dict, List, Optional, Tuple

sys.dont_write_bytecode = True                  # nothing written into the tarball's tree by the import below
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vss_setup as vs  # noqa: E402

FORMAT = 1
AW_NAME = re.compile(r"aw-[A-Za-z0-9._-]+")      # an aw input's name (remote-ladder.sh moves every FILES name of this form)
INPUTS = "aw-inputs.json"
NEEDED = ("aw-scan.json", "aw-map.tar")          # the two inputs this harness reads
SHA = re.compile(r"[0-9a-f]{64}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
# images.json's autoware.repo (pull_ref); aw_suite.py's IMAGE_REF reuses it
REPOSITORY = re.compile(r"[a-z0-9.-]+(?:/[a-z0-9._-]+)+")
COMMIT = re.compile(r"[0-9a-f]{40}")
FILES_LINE = re.compile(r"^FILES=([A-Za-z0-9._: -]*)$", re.M)
MEM_AVAILABLE = re.compile(r"^MemAvailable:\s+(\d+) kB$", re.M)
ABOUT = ("run-aw-setup.sh's record (SDV Phase 8 WP6 9.2): the aw inputs checked, the scenario's map staged, the "
         "Autoware arm64 image pulled by its digest and read back, its SIGILL smoke under the project entrypoint, "
         "MemAvailable around them and D7's 30-minute rule, with 2.12's host check before and after the stem.")
NOTE = ("A functional session: no field is a measurement and nothing is pre-registered. Docker is up on this host. Values "
        "under operational_s are whole seconds of this session's own steps (the pull's wall time is a fact of the record, "
        "not a timing of the image or the network), never compared across hosts.")


def one(exc: BaseException) -> str:
    return " ".join(str(exc).split())


def refuse(problems: List[str]) -> int:
    print(vs.one_line_join(problems))
    return 1


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str, what: str) -> Tuple[Any, Optional[str]]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except OSError as exc:
        return None, "%s cannot be read: %s" % (what, exc.strerror or one(exc))
    except ValueError as exc:
        return None, "%s does not parse as JSON: %s" % (what, one(exc))


# --- run-vss-setup.sh's record ---------------------------------------------------------------------------------------

def cmd_vss_setup(a: argparse.Namespace) -> int:
    doc, why = load_json(a.setup, "rec/vss-setup/raw/setup.json")
    if why:
        return refuse([why])
    if not isinstance(doc, dict):
        return refuse(["rec/vss-setup/raw/setup.json is not a JSON object"])
    status, mode = doc.get("status"), doc.get("host_mode", "a1-metal")
    vs.put(a.facts, "setup_status", str(status))
    vs.put(a.facts, "setup_host_mode", str(mode))
    problems = []
    if status != "DONE":
        problems.append("rec/vss-setup/raw/setup.json says status %r, not DONE" % (status,))
    if mode != a.host_mode:
        problems.append("rec/vss-setup/raw/setup.json records host mode %s (none is a1-metal), not this harness's %s: the "
                        "Autoware image runs on the c7g-metal role and the Orin only (the owner, 2026-10-24)"
                        % (mode, a.host_mode))
    return refuse(problems) if problems else 0


# --- the aw inputs ------------------------------------------------------------------------------------------------------

def files_of(inputs_env: str) -> Tuple[Dict[str, str], Optional[str]]:
    """inputs.env's FILES words, {name: sha256}."""
    try:
        with open(inputs_env, encoding="utf-8") as f:
            text = f.read()
    except OSError as exc:
        return {}, "inputs.env cannot be read: %s" % (exc.strerror or one(exc))
    m = FILES_LINE.search(text)
    if not m:
        return {}, "inputs.env has no FILES line: the aw inputs come in METAL_FILES"
    out: Dict[str, str] = {}
    for w in m.group(1).split():
        name, _sep, sha = w.partition(":")
        out[name] = sha
    return out, None


def repo_commit(repo_tar: str) -> Tuple[Optional[str], Optional[str]]:
    """The commit git archive wrote into the repo tarball's pax header (what git get-tar-commit-id reads)."""
    try:
        with tarfile.open(repo_tar, "r:") as t:
            c = (t.pax_headers or {}).get("comment")
    except (OSError, tarfile.TarError) as exc:
        return None, "the repo tarball cannot be read as a tar: %s" % one(exc)
    if not isinstance(c, str) or not COMMIT.fullmatch(c):
        return None, "the repo tarball carries no commit (the pax header git get-tar-commit-id reads)"
    return c, None


def inputs_problems(aw_in: str, inputs_env: str, repo_tar: str, facts: str) -> Tuple[List[str], List[str]]:
    """THE AW INPUTS' checks: (refusals, inputs.txt's lines)."""
    problems: List[str] = []
    txt: List[str] = []
    files, why = files_of(inputs_env)
    if why:
        return [why], txt
    path = os.path.join(aw_in, INPUTS)
    doc, why = load_json(path, "aw-in/%s" % INPUTS)
    if why:
        return [why + " (the aw inputs come in METAL_FILES, and setup moves them to aw-in/)"], txt
    listed: Dict[str, Any] = {}
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        problems.append("%s is not {\"format\": 1, ...}" % INPUTS)
    else:
        raw = doc.get("files")
        listed = raw if isinstance(raw, dict) else {}
        if not isinstance(raw, dict):
            problems.append("%s holds no files object" % INPUTS)
    own = sha256_file(path)
    if files.get(INPUTS) != own:
        problems.append("%s is %s in inputs.env's FILES, and %s here" % (INPUTS, files.get(INPUTS, "absent"), own))
    txt.append("%s %s %s" % (INPUTS, own, "ok" if files.get(INPUTS) == own else "not FILES' hash"))
    good: Dict[str, str] = {}
    for name in sorted(listed):
        want = listed[name]
        if not isinstance(name, str) or not AW_NAME.fullmatch(name) or name == INPUTS:
            problems.append("%s lists %r: an aw input is named aw-* and is not %s itself" % (INPUTS, name, INPUTS))
            continue
        if not isinstance(want, str) or not SHA.fullmatch(want):
            problems.append("%s gives %s no sha256" % (INPUTS, name))
            continue
        p = os.path.join(aw_in, name)
        if not os.path.isfile(p):
            problems.append("aw-in/%s is missing: %s lists it" % (name, INPUTS))
            txt.append("%s %s missing" % (name, want))
            continue
        got = sha256_file(p)
        if got != want:
            problems.append("aw-in/%s hashes to %s, and %s says %s" % (name, got, INPUTS, want))
            txt.append("%s %s hash differs" % (name, got))
            continue
        if name not in files:
            problems.append("%s is not in inputs.env's FILES: setup did not check it" % name)
            txt.append("%s %s not in FILES" % (name, got))
            continue
        if files[name] != got:
            problems.append("%s is %s in inputs.env's FILES, and %s here" % (name, files[name], got))
            txt.append("%s %s not FILES' hash" % (name, got))
            continue
        good[name] = got
        txt.append("%s %s ok" % (name, got))
    for name in NEEDED:
        if name not in listed:
            problems.append("%s does not list %s, which this harness reads" % (INPUTS, name))
    try:
        present = sorted(os.listdir(aw_in))
    except OSError as exc:
        present = []
        problems.append("aw-in cannot be listed: %s" % (exc.strerror or one(exc)))
    extra = [n for n in present if n != INPUTS and n not in listed]
    for n in extra:
        problems.append("aw-in/%s is there, and %s does not list it" % (n, INPUTS))
    commit = doc.get("commit") if isinstance(doc, dict) else None
    rc, why = repo_commit(repo_tar)
    if why:
        problems.append(why)
    elif commit != rc:
        problems.append("%s's commit %r is not the repo tarball's %s" % (INPUTS, commit, rc))
    txt.append("commit %s (aw-inputs.json)" % (commit if isinstance(commit, str) else "none"))
    txt.append("repo commit %s (the repo tarball's pax header)" % (rc or "none"))
    d = os.path.join(facts, "inputs")
    vs.put(d, "commit", str(commit))
    vs.put(d, "repo_commit", str(rc))
    os.makedirs(os.path.join(d, "files"), exist_ok=True)      # the object exists even when it holds nothing
    for name, got in sorted(good.items()):
        vs.put(os.path.join(d, "files"), name, got)
    vs.put(d, "files_ok", not problems)
    return problems, txt


def cmd_inputs(a: argparse.Namespace) -> int:
    problems, txt = inputs_problems(a.aw_in, a.inputs_env, a.repo_tar, a.facts)
    with open(a.txt, "w", encoding="utf-8", newline="\n") as f:
        f.write("# the aw inputs as run-aw-setup.sh checked them (spec-2 2.11): NAME SHA256 and its check\n")
        for ln in txt:
            f.write(ln + "\n")
    return refuse(problems) if problems else 0


# --- images.json and the scan --------------------------------------------------------------------------------------------

def pull_ref(images: str) -> Tuple[Optional[str], Optional[str]]:
    doc, why = load_json(images, "sdv/stack/images.json")
    if why:
        return None, why
    try:
        aw = doc["autoware"]
        repo, digest = aw["repo"], aw["arm64"]["manifest_digest"]
    except (KeyError, TypeError):
        return None, "images.json names no autoware.repo and autoware.arm64.manifest_digest"
    if not isinstance(repo, str) or not REPOSITORY.fullmatch(repo):
        return None, "images.json's autoware.repo %r is not a repository" % (repo,)
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        return None, "images.json's autoware.arm64.manifest_digest %r is not one sha256 digest" % (digest,)
    return "%s@%s" % (repo, digest), None


def cmd_ref(a: argparse.Namespace) -> int:
    ref, why = pull_ref(a.images)
    if why:
        return refuse([why])
    print(ref)
    return 0


def cmd_scan(a: argparse.Namespace) -> int:
    ref, why = pull_ref(a.images)
    if why:
        return refuse([why])
    assert ref is not None
    digest = ref.split("@", 1)[1]
    doc, why = load_json(a.scan, "aw-in/aw-scan.json")
    if why:
        return refuse([why])
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return refuse(["aw-scan.json is not 9.1's form ({\"format\": 1, ...})"])
    d = os.path.join(a.facts, "scan")
    got = doc.get("image_digest")
    vs.put(d, "image_digest", str(got))
    vs.put(d, "digest_matches", got == digest)
    vs.put(d, "verdict", str(doc.get("verdict")))
    for key in ("findings", "exceptions_applied"):
        v = doc.get(key)
        vs.put(d, key, len(v) if isinstance(v, list) else str(v))
    v = doc.get("elf_files")
    if isinstance(v, list):                     # 9.1's whole record lists every ELF read: their count, never the list
        v = len(v)
    vs.put(d, "elf_files", v if isinstance(v, int) and not isinstance(v, bool) else str(v))
    with open(a.txt, "a", encoding="utf-8", newline="\n") as f:
        f.write("image %s (images.json's autoware.arm64); aw-scan.json's image_digest %s, verdict %s, recorded\n"
                % (ref, "matches" if got == digest else "differs", doc.get("verdict")))
    if got != digest:
        return refuse(["aw-scan.json's image_digest %r is not the digest to pull %s (images.json's "
                       "autoware.arm64.manifest_digest): the scan is of another image" % (got, digest)])
    return 0


# --- 2.7's DDS file -------------------------------------------------------------------------------------------------------

def cmd_dds(a: argparse.Namespace) -> int:
    doc, why = load_json(a.env, "sdv/aw/ros-env.json")
    if why:
        return refuse([why])
    problems = []
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return refuse(["sdv/aw/ros-env.json is not {\"format\": 1, ...}"])
    dom, rmw, xml = doc.get("ros_domain_id"), doc.get("rmw"), doc.get("cyclonedds_single_host")
    if not isinstance(dom, int) or isinstance(dom, bool) or not 0 <= dom <= 232:
        problems.append("ros-env.json's ros_domain_id %r is not a ROS domain" % (dom,))
    if not isinstance(rmw, str) or not re.fullmatch(r"[a-z0-9_]+", rmw):
        problems.append("ros-env.json's rmw %r is not an rmw name" % (rmw,))
    if not isinstance(xml, str) or not xml.strip():
        problems.append("ros-env.json holds no cyclonedds_single_host")
    if problems or not isinstance(xml, str) or not isinstance(dom, int):
        return refuse(problems)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)
    print("%d %s" % (dom, rmw))
    return 0


# --- the map ------------------------------------------------------------------------------------------------------------

def map_of(scenario: str) -> Tuple[Optional[str], Dict[str, str], Optional[str]]:
    doc, why = load_json(scenario, "the scenario")
    if why:
        return None, {}, why
    try:
        name, files = doc["map"]["name"], doc["map"]["files"]
    except (KeyError, TypeError):
        return None, {}, "the scenario names no map (map.name, map.files)"
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in (".", ".."):
        return None, {}, "the scenario's map name %r is not one directory name" % (name,)
    if not isinstance(files, dict) or not files or not all(
            isinstance(k, str) and re.fullmatch(r"[A-Za-z0-9._-]+", k) and isinstance(v, str) and SHA.fullmatch(v)
            for k, v in files.items()):
        return None, {}, "the scenario's map.files is not {file: sha256}"
    return name, dict(files), None


def cmd_stage_map(a: argparse.Namespace) -> int:
    name, files, why = map_of(a.scenario)
    if why:
        return refuse([why])
    assert name is not None
    dest = os.path.join(a.dest, name)
    vs.put(a.facts, "map", name)
    if os.path.lexists(dest):
        return refuse(["VSS_HOME/aw/map/%s exists already" % name])
    problems: List[str] = []
    data: Dict[str, bytes] = {}
    try:
        with tarfile.open(a.tar, "r:") as t:
            for m in t.getmembers():
                parts = m.name.split("/")
                if m.isdir() and m.name.rstrip("/") == name:
                    continue
                if not m.isreg():
                    problems.append("aw-map.tar holds %s, which is not a regular file (a link, a device or a directory)"
                                    % m.name)
                    continue
                if m.name.startswith("/") or ".." in parts or len(parts) != 2 or parts[0] != name:
                    problems.append("aw-map.tar holds %s, which is not %s/<file>" % (m.name, name))
                    continue
                if parts[1] not in files:
                    problems.append("aw-map.tar holds %s, which the scenario does not name" % m.name)
                    continue
                if parts[1] in data:
                    problems.append("aw-map.tar holds %s twice" % m.name)
                    continue
                f = t.extractfile(m)
                data[parts[1]] = f.read() if f is not None else b""
    except (OSError, tarfile.TarError) as exc:
        return refuse(["aw-map.tar cannot be read as a tar: %s" % one(exc)])
    for n in sorted(files):
        if n not in data:
            problems.append("aw-map.tar holds no %s/%s, which the scenario names" % (name, n))
            continue
        got = hashlib.sha256(data[n]).hexdigest()
        vs.put(os.path.join(a.facts, "files"), n, got)
        if got != files[n]:
            problems.append("aw-map.tar's %s/%s hashes to %s, and the scenario says %s" % (name, n, got, files[n]))
    vs.put(a.facts, "files_ok", not problems)
    if problems:
        return refuse(problems)
    os.makedirs(dest)
    for n, b in sorted(data.items()):
        with open(os.path.join(dest, n), "wb") as f:
            f.write(b)
    return 0


# --- what docker reads back ---------------------------------------------------------------------------------------------

def cmd_inspect(a: argparse.Namespace) -> int:
    try:
        doc = json.loads(sys.stdin.read() or "null")
    except ValueError as exc:
        return refuse(["docker image inspect printed no JSON: %s" % one(exc)])
    img = doc[0] if isinstance(doc, list) and doc and isinstance(doc[0], dict) else None
    if img is None:
        return refuse(["docker image inspect printed no image"])
    if "@" not in a.ref:
        return refuse(["the reference %s has no '@', so it is not <repo>@sha256:<64 lowercase hex>, the form "
                       "run-aw-setup.sh pulls and run-aw-suite.sh runs (spec-2 2.6): the image read back is not checked "
                       "against it" % a.ref])
    digest = a.ref.split("@", 1)[1]
    rd = [str(x) for x in (img.get("RepoDigests") or [])]
    vs.put(a.facts, "image_id", str(img.get("Id")))
    vs.put(a.facts, "id_is_digest", img.get("Id") == digest)
    vs.put(a.facts, "repo_digests", rd)
    vs.put(a.facts, "in_repo_digests", a.ref in rd)
    vs.put(a.facts, "os", str(img.get("Os")))
    vs.put(a.facts, "architecture", str(img.get("Architecture")))
    if a.ref not in rd:
        return refuse(["the image read back has RepoDigests %s, which do not hold %s" % (rd, a.ref)])
    return 0


def mem_available(path: str) -> Optional[int]:
    try:
        with open(path, encoding="utf-8") as f:
            m = MEM_AVAILABLE.search(f.read())
    except OSError:
        return None
    return int(m.group(1)) if m else None


def cmd_meminfo(a: argparse.Namespace) -> int:
    v = mem_available(a.file)
    if v is None:
        return 1
    print(v)
    return 0


# --- the record -----------------------------------------------------------------------------------------------------------

def cmd_record(a: argparse.Namespace) -> int:
    declared = a.steps.split()
    steps = []
    for n, name, start, end, secs, rc, outcome in vs.read_rows(os.path.join(a.work, "steps.tsv"), 7):
        steps.append({"n": vs.as_int(n), "name": name, "start_utc": start, "end_utc": end,
                      "operational_s": {"step": vs.as_int(secs)}, "rc": vs.as_int(rc), "outcome": outcome})
    ran = {s["name"] for s in steps}
    facts = vs.read_facts(os.path.join(a.work, "facts"))
    p, b = facts.get("pull"), facts.get("budget")
    pull: Dict[str, Any] = p if isinstance(p, dict) else {}
    budget: Dict[str, Any] = b if isinstance(b, dict) else {}
    doc: Dict[str, Any] = {"format": FORMAT, "harness": "run-aw-setup.sh", "host_mode": a.host_mode, "about": ABOUT,
                           "note": NOTE, "status": a.status, "status_line": a.status_line, "at": a.at or None,
                           "reason": a.reason or None, "steps": steps, "not_run": [s for s in declared if s not in ran],
                           "image": {"ref": pull.get("ref"), "id": pull.get("image_id")},
                           "budget_short": budget.get("budget_short") if isinstance(budget.get("budget_short"), bool)
                           else None, "facts": facts}
    vs.write_json(a.out, doc)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("vss-setup")
    for x in ("--setup", "--host-mode", "--facts"):
        p.add_argument(x, required=True)
    p = sub.add_parser("inputs")
    for x in ("--aw-in", "--inputs-env", "--repo-tar", "--facts", "--txt"):
        p.add_argument(x, required=True)
    p = sub.add_parser("scan")
    for x in ("--scan", "--images", "--facts", "--txt"):
        p.add_argument(x, required=True)
    p = sub.add_parser("ref")
    p.add_argument("--images", required=True)
    p = sub.add_parser("dds")
    p.add_argument("--env", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("stage-map")
    for x in ("--tar", "--scenario", "--dest", "--facts"):
        p.add_argument(x, required=True)
    p = sub.add_parser("inspect")
    p.add_argument("--ref", required=True)
    p.add_argument("--facts", required=True)
    p = sub.add_parser("meminfo")
    p.add_argument("--file", required=True)
    p = sub.add_parser("record")
    for x in ("--work", "--out", "--status", "--status-line", "--steps", "--host-mode"):
        p.add_argument(x, required=True)
    p.add_argument("--at", default="")
    p.add_argument("--reason", default="")
    a = ap.parse_args(argv)
    return {"vss-setup": cmd_vss_setup, "inputs": cmd_inputs, "scan": cmd_scan, "ref": cmd_ref, "dds": cmd_dds,
            "stage-map": cmd_stage_map, "inspect": cmd_inspect, "meminfo": cmd_meminfo, "record": cmd_record}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
