"""twin_gate.py -- fail, do not skip: the gate every twin test file reads, and the CI recipe's skip check (SDV
Phase 4 WP0).

WHY
  The twin's tests carry an exclusion proof: nothing the QNX monitor produces reaches the cloud (owner decision
  S11). Several of them need the generated catalogue (sdv-out/gen) or the vss-tools venv, and the branch's other
  tests skip without those. A skipped exclusion proof must not read as a pass, so the twin's tests get a switch
  and the CI recipe a check, and neither is trusted alone: the switch could be mistyped or simply not read by a
  new test, and the check could be dropped from the recipe.

THE GATE (imported by the twin test files: tests/test_sdv_connector.py, tests/test_sdv_connector_probe.py and,
from WP1, tests/test_twin_allowlist.py)
  catalogue(*names)  the generated outputs' directory (SDV_GEN, default sdv-out/gen), every named file present
                     (default: vss-databroker.json and vss-ids.vspec);
  vss_venv()         the vss-tools venv's python (SDV_VENV, default ~/sdv-venv), with its vspec beside it;
  missing(what)      what both call when the input is not there: pytest.skip without the switch, pytest.fail
                     with it.
  The switch is the environment variable SDV_REQUIRE_GEN, read strictly at each call: 1 turns a missing input
  into a failure; unset, empty or 0 leaves the skip; any other value fails the test that reads it, because a
  mistyped switch that quietly meant "off" would be the no-op this file exists to prevent.

THE SKIP CHECK (the Phase 4 CI recipe's last step: python tests/twin_gate.py JUNIT.xml, from the tree's root)
  Reads pytest's junit report and fails (exit 1, one line per finding) when
    - a test of TWIN_TEST_FILES was skipped, by a mark, through the gate, in a fixture, or as an xfail;
    - a file of TWIN_TEST_FILES is in the tree and none of its tests is in the report (deselected, not collected);
    - the Monitor guard (MONITOR_GUARD: the test of tests/test_sdv_vss.py that holds the Monitor branch out of
      every allowlist file) is not in the report, or is there as anything but a pass. That test is not edited
      and still skips without the venv, switch or no switch; this check is what holds it.
  Exit 2: the report cannot be read. It reads the junit report, by test id, and not the lines pytest -rs
  prints: those name the line a skip was raised at, which for a skip raised here or in a fixture is not the
  test's file (tests/test_sdv_connector.py shows one). So no opt-in test may live in a file of TWIN_TEST_FILES:
  it would be skipped by default and fail every CI run. Opt-in twin tests go to tests/test_sdv_connector_probe.py.

Does not demonstrate: that a twin test proves what its name says; that a test outside TWIN_TEST_FILES and the
guard ran (a skip elsewhere is not this check's business); anything about a run made without the recipe. The
connector's tests in the stack's file are such tests outside it: tests/test_sdv_stack.py holds how the stack
starts the connector (three mounts, no docker.sock, never root, the vcan feed only), and five of those skip on
a host that is not POSIX. The recipe runs in WSL, where they run; this check would not notice if they did not.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, NamedTuple, NoReturn, Optional, Sequence

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

REQUIRE_ENV = "SDV_REQUIRE_GEN"
CATALOGUE_FILES = ("vss-databroker.json", "vss-ids.vspec")
VENV_FILES = ("bin/python", "bin/vspec")

TWIN_TEST_FILES = ("tests/test_twin_allowlist.py", "tests/test_sdv_connector.py")
MONITOR_GUARD = ("tests/test_sdv_vss.py", "test_the_monitor_branch_is_generated_and_is_in_no_allowlist_file")


# --- the gate ---------------------------------------------------------------------------------------

def required() -> bool:
    """Whether SDV_REQUIRE_GEN turns a missing input into a failure. Read strictly: 1, or off."""
    value = os.environ.get(REQUIRE_ENV)
    if value is None or value in ("", "0"):
        return False
    if value == "1":
        return True
    pytest.fail("%s is %r: it is 1, or unset (a mistyped switch must not read as off)" % (REQUIRE_ENV, value), pytrace=False)


def missing(what: str) -> NoReturn:
    """A twin test's input is not there: fail with the switch, skip without it."""
    if required():
        pytest.fail("%s=1 and a twin test's input is missing: %s" % (REQUIRE_ENV, what), pytrace=False)
    pytest.skip(what)


def gen_dir() -> Path:
    return Path(os.environ.get("SDV_GEN", str(REPO / "sdv-out" / "gen"))).expanduser()


def venv_dir() -> Path:
    return Path(os.environ.get("SDV_VENV", "~/sdv-venv")).expanduser()


def catalogue(*names: str) -> Path:
    """The generated outputs' directory with every named file in it (default CATALOGUE_FILES); else missing()."""
    gen = gen_dir()
    absent = [n for n in (names or CATALOGUE_FILES) if not (gen / n).is_file()]
    if absent:
        missing("needs the generated catalogue in %s (sdv/vss/README.md): no %s" % (gen, ", ".join(absent)))
    return gen


def vss_venv() -> Path:
    """The vss-tools venv's python, with vspec beside it; else missing()."""
    venv = venv_dir()
    absent = [n for n in VENV_FILES if not (venv / n).exists()]
    if absent:
        missing("needs the vss-tools venv %s built from sdv/vss/requirements.lock (sdv/vss/README.md; WSL Ubuntu-24.04): no %s"
                % (venv, ", ".join(absent)))
    return venv / "bin" / "python"


# --- the skip check ---------------------------------------------------------------------------------

class Case(NamedTuple):
    module: str          # the junit classname's module part, as a path: tests/test_x.py
    name: str            # the rest of the test id: test_y, test_y[param], TestClass::test_y
    outcome: str         # passed, skipped, failed or error
    why: str


def junit_cases(xml_text: str, files: Sequence[str]) -> List[Case]:
    """The report's test cases that belong to one of `files`. pytest writes a case's classname as its module's
    dotted path, followed by its class when it has one."""
    out: List[Case] = []
    mods = {f[:-len(".py")].replace("/", "."): f for f in files}
    for tc in ET.fromstring(xml_text).iter("testcase"):
        classname, name = tc.get("classname") or "", tc.get("name") or ""
        owner: Optional[str] = None
        for mod in mods:
            if classname == mod or classname.startswith(mod + "."):
                owner = mod
        if owner is None:
            continue
        inner = classname[len(owner):].lstrip(".")
        outcome, why = "passed", ""
        for child in tc:
            if child.tag in ("skipped", "failure", "error"):
                outcome = {"failure": "failed"}.get(child.tag, child.tag)
                why = child.get("message") or ""
                break
        out.append(Case(mods[owner], "::".join(inner.split(".") + [name]) if inner else name, outcome, why))
    return out


def skip_problems(xml_text: str, repo: Path) -> List[str]:
    """Why this report is not a run in which the twin's tests and the Monitor guard all ran: [] when it is."""
    problems: List[str] = []
    if not list(ET.fromstring(xml_text).iter("testcase")):
        problems.append("the report holds no test case")
    for rel in TWIN_TEST_FILES:
        cases = junit_cases(xml_text, [rel])
        problems += ["%s::%s was skipped (%s)" % (rel, c.name, c.why) for c in cases if c.outcome == "skipped"]
        if not cases and (repo / rel).is_file():
            problems.append("%s is in the tree and none of its tests ran" % rel)
    rel, guard = MONITOR_GUARD
    runs = [c for c in junit_cases(xml_text, [rel]) if c.name == guard or c.name.startswith(guard + "[")]
    if not runs:
        problems.append("the Monitor guard %s::%s did not run" % (rel, guard))
    for c in runs:
        if c.outcome != "passed":
            problems.append("the Monitor guard %s::%s %s" % (rel, c.name, "was skipped (%s)" % c.why if c.outcome == "skipped" else c.outcome))
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: twin_gate.py JUNIT.xml   (from the tree's root; the skip check of the Phase 4 CI recipe)", file=sys.stderr)
        return 2
    try:
        xml_text = Path(args[0]).read_text(encoding="utf-8")
        problems = skip_problems(xml_text, Path.cwd())
        ran = len(junit_cases(xml_text, list(TWIN_TEST_FILES))) + 1
    except (OSError, ET.ParseError) as exc:
        print("twin_gate: cannot read the junit report %s: %s" % (args[0], exc), file=sys.stderr)
        return 2
    for p in problems:
        print("twin_gate: %s" % p)
    if problems:
        return 1
    print("twin_gate: %d test(s) of the twin files and the Monitor guard ran, none skipped" % ran)
    return 0


if __name__ == "__main__":
    sys.exit(main())
