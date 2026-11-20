"""`twinctl update-code function`: the breaker function's code replaced in place (SDV Phase 4, the breaker's code update).

NO AWS CALL IS MADE HERE, AND NO CREDENTIAL IS READ: this file drives tests/test_sdv_cloud.py's rig and its stand-in for the
CLI (tests/twin_stub_aws.py). That stand-in models neither `lambda update-function-code` nor `lambda wait`. STAND_IN below,
written into each test's own directory, adds the two to its table and runs it; every other call is the stand-in's own. Its
update keeps the zip it was given and the code's sha256 in the form the service reports it, and changes nothing else of the
function but the LastUpdateStatus a test plants (`update_status`); its wait answers at once. Both are written from memory of
the documentation, as every reply of the stand-in is.

THE CASE IS THE LIVE ONE: a twin made whole from the source's build, the source edited since (one comment more) and built
again at the zip's path. What is held here:
  the render     the update, the wait and the read-back, the zip's sha256 in both forms and the render's hash; nothing is sent
                 without the approval, and an approval is the render's as it was shown, for one run.
  the refusals   before any write, each by its name: the function not recorded as made, or not found; a zip that is not the
                 source's build; the zip the function was made from; any difference of the function from its render but its
                 code; a caller that is not the operator role.
  the update     one write; the read-back's CodeSha256 is the new zip's, the state records that zip as the function's input,
                 `status` reads the function as rendered and says nothing more of the source; function-status and the dry
                 trip are recorded as needing to run again and `status` says so; nothing else of the function, its
                 concurrency, its policy or the alarms changes.
  a failed call  the function is recorded as `updating` with the call on record and nothing is retried; `status`, or a new
                 update-code, reads its code and settles the record to the zip it is, or refuses when it is neither.
  the role       the operator role's policy holds lambda:UpdateFunctionCode while a code update is due or on record, and only
                 then (with neither, every render is the one tests/test_sdv_cloud.py pins); `plan` then covers the update's calls
                 and holds the policy to them.

Does not demonstrate: what the real service answers to the update or the wait, what a CLI other than 2.35.1 says of the two
calls offline (2.35.1's words, captured once, are held below as text), or that the role the owner changes by hand is the render.
LastUpdateStatus (Successful, Failed, InProgress) and its meaning are from the documentation as remembered; STAND_IN's
`update_status` plant writes them, and no live account was read.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

import test_sdv_cloud as tc

TW = tc.TW
Rig = tc.Rig

NEW_SOURCE = tc.BREAKER_SOURCE + b"# the source edited since the function was made: one comment more, as batch 1's edit was\n"
NEW_ZIP = TW.zip_bytes(NEW_SOURCE)
OLD_ZIP = tc.BREAKER_ZIP
NEWER_SOURCE = NEW_SOURCE + b"# and edited once more\n"
FUNCTION = tc.PREFIX + "-breaker"
CODE_DIFFERS = "its code is not the zip the state records (CodeSha256 differs)"
UPDATE = "lambda:UpdateFunctionCode"
RUN_AGAIN = ("function-status", "dry-trip")
TAKEN_BACK = ["alarm-test-" + k for k in tc.BREAKER] + ["reattach-policy"]      # what stood on the old code through the dry trip

# The stand-in with the two calls it does not model. The waiter's name is a word with no option before it, which the stand-in's
# parser refuses: it is handed on as `--waiter NAME`, and sent() puts it back as it was sent.
STAND_IN = '''import base64
import hashlib
import importlib.util
import os
import sys

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("twin_stub_aws_with_the_update", @STUB@)
stub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stub)


def update_code(a, o, out):
    f = stub.fn(a, o)
    code = stub.one(o, "--zip-file")
    if not isinstance(code, bytes):
        raise stub.Err("ParamValidation", "--zip-file is a blob: fileb://")
    if a.get("update_ignored"):                  # a test's plant: answered as done, and the code is not replaced
        return f["config"]
    f["config"]["CodeSha256"] = base64.b64encode(hashlib.sha256(code).digest()).decode()
    if a.get("update_status"):                   # a test's plant: the LastUpdateStatus the update leaves (the stand-in's has none)
        f["config"]["LastUpdateStatus"] = a["update_status"]
    stub.function_zip(os.environ["STUB_AWS_DIR"], stub.one(o, "--function-name")).write_bytes(code)
    return f["config"]


def wait(a, o, out):
    if stub.one(o, "--waiter") != "function-updated-v2":
        raise stub.Err("ParamValidation", "the stand-in models one waiter")
    stub.fn(a, o)
    return None


stub.OPS[("lambda", "update-function-code")] = (update_code, True)
stub.OPS[("lambda", "wait")] = (wait, False)
argv = sys.argv[1:]
if argv[:2] == ["lambda", "wait"] and len(argv) > 2 and not argv[2].startswith("--"):
    argv = ["lambda", "wait", "--waiter"] + argv[2:]
sys.exit(stub.main(argv))
'''


def code_of(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """The whole table applied once from the source's build, without the notice. Tests work on a copy."""
    return Rig(tmp_path_factory.mktemp("update-code") / "twin", notice=False).build()


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The breaker's source where the driver reads it, edited since the function was made."""
    path = tmp_path / "the-source" / "breaker.py"
    path.parent.mkdir()
    path.write_bytes(NEW_SOURCE)
    monkeypatch.setattr(TW, "BREAKER_SOURCE", path)
    return path


def edited(rig: Rig, tmp_path: Path) -> Rig:
    """The edited source built again at the zip's path, and the rig driven through STAND_IN."""
    (rig.inputs / "breaker.zip").write_bytes(NEW_ZIP)
    stand_in = tmp_path / "stand_in.py"
    stand_in.write_text(STAND_IN.replace("@STUB@", repr(str(tc.STUB))), encoding="utf-8")
    rig.extra["TWIN_AWS"] = str(stand_in)
    return rig


@pytest.fixture
def twin(tmp_path: Path, made: Rig, source: Path) -> Rig:
    """The made twin with the edited source built again at the zip's path, driven through STAND_IN."""
    return edited(made.copy(tmp_path / "twin"), tmp_path)


@pytest.fixture
def early(tmp_path: Path, source: Path) -> Rig:
    """The twin made up to go-live and not live yet, from the build of the source as it was; then edited, as `twin` is."""
    source.write_bytes(tc.BREAKER_SOURCE)
    rig = Rig(tmp_path / "early", notice=False).build(until="go-live-rule")
    source.write_bytes(NEW_SOURCE)
    return edited(rig, tmp_path)


def granted(rig: Rig) -> None:
    """What the owner does by hand before the first update: the operator role changed to its render, which holds the update's
    action now (IAM)."""
    assert "its policy is not the render" in rig.run("apply", "operator-role", expect=1).err
    rig.owner_makes("operator-role")
    rig.run("apply", "operator-role", expect=0)


def shown(rig: Rig) -> str:
    """The update's render printed, with nothing sent; its hash."""
    before = len(rig.log())
    ran = rig.run("update-code", "function", expect=3)
    assert rig.log()[before:] == [], "printing the render sent a call"
    found = tc.HASH.search(ran.out)
    assert found, ran.text
    return found.group(1)


def approve(rig: Rig, digest: str, expect: int) -> tc.Ran:
    return rig.run("update-code", "function", "--approve", "function-code:" + digest, expect=expect)


def entry(rig: Rig) -> Dict[str, Any]:
    return dict(tc.state_of(rig)["steps"]["function"])


def config(rig: Rig) -> Dict[str, Any]:
    return dict(rig.account()["functions"][FUNCTION]["config"])


def sent(rig: Rig, since: int = 0) -> List[List[str]]:
    """Every call that arrived since, as it was sent: the stand-in's `--waiter` put back as the waiter's word."""
    out = []
    for e in rig.log()[since:]:
        argv = list(e["argv"])
        if argv[:3] == ["lambda", "wait", "--waiter"]:
            argv = ["lambda", "wait"] + argv[3:]
        out.append(argv)
    return out


def events(rig: Rig) -> List[Dict[str, Any]]:
    path = rig.state / "approvals.jsonl"
    found = [json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x.strip()] if path.is_file() else []
    return [e for e in found if e["step"] == "function-code"]


def updates(rig: Rig, since: int = 0) -> List[List[str]]:
    return [c for c in rig.writes(since) if c[:2] == ["lambda", "update-function-code"]]


# ================================================================================================= the render and the approval

def test_the_render_names_the_update_the_wait_and_the_read_back_and_sends_nothing_without_the_approval(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    out = twin.said[-1].out
    assert "update-code function-code (row 13)" in out and "3 call(s), 0 document(s):" in out
    calls = [line.strip() for line in out.split("\n") if line.startswith("  aws ")]
    assert [c.split()[1:3] for c in calls] == [["lambda", "update-function-code"], ["lambda", "wait"], ["lambda", "get-function"]]
    assert "--zip-file fileb://" in calls[0] and "wait function-updated-v2 --function-name" in calls[1]
    assert "input TWIN_BREAKER_ZIP: sha256 %s; as the service reports a function's code: %s" % (sha(NEW_ZIP), code_of(NEW_ZIP)) in out
    assert "render sha256: %s" % digest in out and "this replaces the code alone" in out
    assert "to go on, once the owner said yes to this: twinctl update-code function --approve function-code:%s" % digest in out
    assert [(e["mode"], e["hash"], e["event"]) for e in events(twin)] == [("update-code", digest, "shown")]
    assert config(twin)["CodeSha256"] == code_of(OLD_ZIP) and entry(twin)["status"] == "created"
    assert not tc.clean(twin.said[-1].text)


def test_the_approval_is_the_renders_as_it_was_shown_and_names_this_step(twin: Rig, source: Path) -> None:
    granted(twin)
    digest = shown(twin)
    since = len(twin.log())
    ran = twin.run("update-code", "function", "--approve", "function:" + digest, expect=1)
    assert "refused: approval-for-another-step:" in ran.err
    assert "refused: approval-for-another-render:" in approve(twin, "0" * 64, 1).err
    # the source edited and built once more after the printing: another render, and its approval is refused
    source.write_bytes(NEWER_SOURCE)
    (twin.inputs / "breaker.zip").write_bytes(TW.zip_bytes(NEWER_SOURCE))
    assert "refused: approval-for-another-render:" in approve(twin, digest, 1).err
    # back to the zip that was shown; a render that was never printed is not approved
    source.write_bytes(NEW_SOURCE)
    (twin.inputs / "breaker.zip").write_bytes(NEW_ZIP)
    (twin.state / "approvals.jsonl").unlink()
    assert "refused: approval-never-shown:" in approve(twin, digest, 1).err
    assert twin.log()[since:] == [] and config(twin)["CodeSha256"] == code_of(OLD_ZIP)


# ================================================================================================= the refusals before any write

def test_a_zip_that_is_not_the_sources_build_is_refused_as_apply_function_refuses_it(twin: Rig, source: Path) -> None:
    granted(twin)
    source.write_bytes(NEWER_SOURCE)                                # edited after the zip was built, and not built again
    since = len(twin.log())
    ran = twin.run("update-code", "function", expect=1)
    assert "refused: zip-not-the-source:" in ran.err and "`twinctl build-breaker`" in ran.err
    assert tc.NOT_THE_BUILD in ran.out and "to go on" not in ran.out and events(twin) == []       # printed, and nothing to say yes to
    ran = approve(twin, "0" * 64, 1)
    assert "refused: zip-not-the-source:" in ran.err and ran.out == ""
    assert twin.log()[since:] == [] and events(twin) == []


def test_the_zip_the_function_was_made_from_is_nothing_to_update(twin: Rig, source: Path) -> None:
    source.write_bytes(tc.BREAKER_SOURCE)
    (twin.inputs / "breaker.zip").write_bytes(OLD_ZIP)
    since = len(twin.log())
    ran = twin.run("update-code", "function", expect=1)
    assert "refused: nothing-to-update:" in ran.err and ran.out == "" and twin.log()[since:] == [] and events(twin) == []


def test_a_function_not_recorded_as_made_or_not_found_is_refused_before_any_write(twin: Rig, tmp_path: Path) -> None:
    started = Rig(tmp_path / "started", notice=False).start()
    since = len(started.log())
    assert "refused: function-not-made:" in started.run("update-code", "function", expect=1).err and started.log()[since:] == []
    granted(twin)
    digest = shown(twin)
    tc.set_status(twin, "function", "unverified")                   # made, and not read back as rendered
    since = len(twin.log())
    assert "refused: function-not-made:" in approve(twin, digest, 1).err and twin.log()[since:] == []
    tc.set_status(twin, "function", "created")
    twin.edit(lambda a: a["functions"].clear())                     # gone from the account
    assert "refused: function-not-found:" in approve(twin, digest, 1).err and twin.writes(since) == []
    assert "spent" not in [e["event"] for e in events(twin)]


def test_any_difference_of_the_function_but_its_code_is_printed_and_nothing_is_sent(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=31))
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert "refused: function-differs:" in ran.err and "its configuration is not the render" in ran.err
    assert twin.writes(since) == [] and entry(twin)["inputs"] == {"TWIN_BREAKER_ZIP": sha(OLD_ZIP)} and entry(twin)["status"] == "created"
    # refused before the approval was spent: the function as rendered again, the same approval goes through
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=30))
    approve(twin, digest, 0)
    assert config(twin)["CodeSha256"] == code_of(NEW_ZIP)


def _fn(a: Dict[str, Any]) -> Dict[str, Any]:
    return a["functions"][FUNCTION]


def _cfg(a: Dict[str, Any]) -> Dict[str, Any]:
    return _fn(a)["config"]


S1 = "its configuration is not the render (runtime, architecture, handler, role, memory, time-out)"
DIFFERENCES: List[Any] = [
    ("runtime", lambda a: _cfg(a).update(Runtime="python3.11"), S1),
    ("handler", lambda a: _cfg(a).update(Handler="breaker.other"), S1),
    ("role", lambda a: _cfg(a).update(Role="arn:aws:iam::%s:role/%s-another-role" % (tc.ACCOUNT, tc.PREFIX)), S1),
    ("memory", lambda a: _cfg(a).update(MemorySize=256), S1),
    ("architecture", lambda a: _cfg(a).update(Architectures=["x86_64"]), S1),
    ("environment", lambda a: _cfg(a)["Environment"]["Variables"].update(TWIN_RULE="another_rule"), "its environment is not the render"),
    ("layer", lambda a: _cfg(a).update(Layers=[{"Arn": "arn:aws:lambda:%s:%s:layer:example:1" % (tc.REGION, tc.ACCOUNT)}]),
     "it has a layer or a VPC"),
    ("vpc", lambda a: _cfg(a).update(VpcConfig={"SubnetIds": ["subnet-0aaaaaaaaaaaaaaa1"]}), "it has a layer or a VPC"),
    ("url", lambda a: _fn(a)["urls"].append({"FunctionUrl": "https://example.com/"}), "it has a function URL"),
]


@pytest.mark.parametrize("change, said", [d[1:] for d in DIFFERENCES], ids=[d[0] for d in DIFFERENCES])
def test_each_difference_of_the_function_but_its_code_is_refused_by_its_own_sentence(twin: Rig, change: Callable[[Dict[str, Any]], None],
                                                                                    said: str) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(change)
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert "refused: function-differs:" in ran.err
    assert "  - " + said in ran.err
    assert twin.writes(since) == []
    assert config(twin)["CodeSha256"] == code_of(OLD_ZIP)
    assert entry(twin)["status"] == "created"


def test_a_code_that_is_neither_zip_is_the_one_difference_let_through(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(CodeSha256=code_of(b"code that nobody built")))
    approve(twin, digest, 0)
    assert config(twin)["CodeSha256"] == code_of(NEW_ZIP) and entry(twin)["inputs"] == {"TWIN_BREAKER_ZIP": sha(NEW_ZIP)}


def test_the_caller_is_held_to_the_operator_role_before_any_write(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update(identity={"UserId": "x", "Arn": tc.j("arn:aws:sts::", tc.ACCOUNT, ":assumed-role/another-role/session")}))
    since = len(twin.log())
    assert "refused: identity-not-the-operator-role:" in approve(twin, digest, 1).err
    assert [c[:2] for c in sent(twin, since)] == [["sts", "get-caller-identity"]]
    twin.edit(tc.other_account)
    since = len(twin.log())
    assert "refused: identity-other-account:" in approve(twin, digest, 1).err
    assert [c[:2] for c in sent(twin, since)] == [["sts", "get-caller-identity"]]
    assert config(twin)["CodeSha256"] == code_of(OLD_ZIP)
    assert "used" not in [e["event"] for e in events(twin)]


# ================================================================================================= the update

def test_one_approval_replaces_the_code_alone_and_the_function_reads_as_rendered_after_it(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    before = twin.account()
    since = len(twin.log())
    ran = approve(twin, digest, 0)
    zip_url = TW.file_url(twin.inputs / "breaker.zip", binary=True)
    assert twin.writes(since) == [["lambda", "update-function-code", "--function-name", FUNCTION, "--zip-file", zip_url]]
    assert [c[:2] for c in sent(twin, since)] == [["sts", "get-caller-identity"], ["lambda", "get-function"], ["lambda", "list-function-url-configs"],
                                                  ["lambda", "update-function-code"], ["lambda", "wait"], ["lambda", "get-function"]]
    assert ["lambda", "wait", "function-updated-v2", "--function-name", FUNCTION] == sent(twin, since)[4][:5]
    # the code alone: the function's every other field, its concurrency, its policy, its URLs, the alarms and the roles are as before
    after = twin.account()
    assert config(twin)["CodeSha256"] == code_of(NEW_ZIP)
    assert {k: v for k, v in config(twin).items() if k != "CodeSha256"} == {k: v for k, v in before["functions"][FUNCTION]["config"].items()
                                                                           if k != "CodeSha256"}
    assert {k: v for k, v in after["functions"][FUNCTION].items() if k != "config"} == {k: v for k, v in before["functions"][FUNCTION].items()
                                                                                       if k != "config"}
    assert after["alarms"] == before["alarms"] and after["roles"] == before["roles"] and list(after["functions"]) == [FUNCTION]
    # the state records the new zip as the function's input, and the code update
    e = entry(twin)
    assert e["status"] == "created" and e["inputs"] == {"TWIN_BREAKER_ZIP": sha(NEW_ZIP)} and "update" not in e
    assert [(u["from"], u["to"]) for u in e["code_updates"]] == [(sha(OLD_ZIP), sha(NEW_ZIP))]
    assert [u["render"] for u in e["code_updates"]] == [digest]
    for step in RUN_AGAIN:
        assert tc.state_of(twin)["steps"][step]["status"] == "stale" and tc.state_of(twin)["steps"][step]["stale_for"] == "function-code", step
        assert step in ran.out, step
    assert [tc.status_of(twin, step) for step in TAKEN_BACK] == ["stale"] * len(TAKEN_BACK)          # critic#2
    assert [(e["event"]) for e in events(twin)] == ["shown", "used", "spent"]
    # status: the function as rendered, nothing more of the source; the two actions to run again, said so
    lines = tc.status_lines(twin.run("status", expect=0))
    assert "as rendered" in lines["function"] and tc.SOURCE_CHANGED not in lines["function"] and "the zip at its path" not in lines["function"]
    for step in RUN_AGAIN:
        assert " stale " in lines[step] and "`twinctl apply %s` runs it again" % step in lines[step], step
    assert "as rendered" in lines["operator-role"]
    # the two run again on the function as it is now, and status says no more of it
    for step in RUN_AGAIN:
        twin.go("apply", step)
    lines = tc.status_lines(twin.run("status", expect=0))
    assert [step for step in RUN_AGAIN if " done " not in lines[step] or "runs it again" in lines[step]] == []
    assert not tc.clean("".join(r.text for r in twin.said))


def test_what_stood_on_the_old_code_is_taken_back_and_go_live_waits_until_the_breaker_ran_on_the_new_one(early: Rig) -> None:
    """critic#2 (p4-bu-critic's case C10): the invariant of tests/test_sdv_cloud.py::test_a_record_does_not_outlive_what_it_stood_on
    (WP6-verify-2's SHOULD 1), reached through the code update. The alarm tests and reattach-policy stood on a dry trip of the
    code that was there: they are taken back with it, as when the function is made anew, and go-live waits for the breaker to
    run on the new code."""
    assert [tc.status_of(early, step) for step in list(RUN_AGAIN) + TAKEN_BACK] == ["done"] * (len(RUN_AGAIN) + len(TAKEN_BACK))
    granted(early)
    ran = approve(early, shown(early), 0)
    steps = tc.state_of(early)["steps"]
    assert {step: (steps[step]["status"], steps[step]["stale_for"]) for step in RUN_AGAIN} == {step: ("stale", "function-code")
                                                                                               for step in RUN_AGAIN}
    assert {step: (steps[step]["status"], steps[step].get("stale_for")) for step in TAKEN_BACK} == {step: ("stale", "function")
                                                                                                      for step in TAKEN_BACK}
    assert ("update-code function: %d record(s) stood on this step as it was and are taken back (%s)" % (len(TAKEN_BACK), ", ".join(TAKEN_BACK))
            in ran.out)
    rule, since = tc.PREFIX + "_telemetry", len(early.log())
    went = early.go("apply", "go-live-rule", expect=1)
    assert "refused: step-needs:" in went.err and "reattach-policy" in went.err and early.writes(since) == []
    assert early.account()["rules"][rule]["ruleDisabled"] is True
    # the breaker runs again on the new code, each action by its own approval; only then does go-live pass
    for step in list(RUN_AGAIN) + TAKEN_BACK:
        assert "refused: step-needs:" in early.go("apply", "go-live-rule", expect=1).err, step
        early.go("apply", step)
    early.go("apply", "go-live-rule")
    assert early.account()["rules"][rule]["ruleDisabled"] is False


@pytest.mark.parametrize("step", ["go-live-rule", "alarm-test-bytes", "reattach-policy"])
def test_while_an_update_is_unsettled_no_step_that_stands_on_the_function_is_applied(early: Rig, step: str) -> None:
    """r2c#1 (critic2's case C10): the steps that stand on the function through the dry trip, not only those whose own needs name it,
    wait while its record is `updating`; nothing is read or sent."""
    granted(early)
    digest = shown(early)
    early.edit(lambda a: a.update(reply_garbage={"lambda update-function-code": "a reply that is no JSON"}))
    approve(early, digest, 1)
    early.edit(lambda a: a.pop("reply_garbage"))
    assert entry(early)["status"] == "updating"
    since = len(early.log())
    assert "refused: still-updating:" in early.go("apply", step, expect=1).err and early.log()[since:] == []


def test_the_read_back_is_compared_with_the_new_zip(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update(update_ignored=True))              # the service answers, and the code is not replaced
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert len(updates(twin, since)) == 1 and "still the zip it was made from" in ran.err
    e = entry(twin)
    assert e["status"] == "created" and e["inputs"] == {"TWIN_BREAKER_ZIP": sha(OLD_ZIP)} and "update" not in e and not e.get("code_updates")
    assert [tc.status_of(twin, step) for step in RUN_AGAIN] == ["done", "done"]
    assert [tc.status_of(twin, step) for step in TAKEN_BACK] == ["done"] * len(TAKEN_BACK)          # the old code still runs: none taken back


# ================================================================================================= a call that fails, or whose reply is lost

def test_a_failed_update_is_recorded_as_updating_never_retried_and_settled_by_status(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "update-function-code", "code": "AccessDeniedException"}))
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert len(updates(twin, since)) == 1 and "AccessDeniedException" in ran.err and "nothing is retried" in ran.err
    e = entry(twin)
    assert e["status"] == "updating" and e["update"]["sent"] == [0] and (e["update"]["from"], e["update"]["to"]) == (sha(OLD_ZIP), sha(NEW_ZIP))
    assert e["inputs"] == {"TWIN_BREAKER_ZIP": sha(OLD_ZIP)} and [tc.status_of(twin, step) for step in RUN_AGAIN] == ["done", "done"]
    # while it is not settled: the function stands (teardown's order holds it), nothing that needs it runs, and it is not made again
    assert "refused: teardown-order:" in twin.run("teardown", "breaker-log", expect=1).err
    assert "refused: step-needs:" in twin.go("apply", "function-status", expect=1).err
    assert "refused: still-updating:" in twin.go("apply", "function", expect=1).err
    assert updates(twin, since) == updates(twin, since)[:1] and len(twin.writes(since)) == 1
    twin.run("apply", "operator-role", expect=0)                # the granted role still reads as rendered while the update is unsettled
    # status reads the code and settles the record: the update did not go through, the function runs the zip it was made from
    ran = twin.run("status", expect=0)
    assert "update-code function:" in ran.text and "the zip it was made from" in ran.text
    e = entry(twin)
    assert e["status"] == "created" and "update" not in e and e["inputs"] == {"TWIN_BREAKER_ZIP": sha(OLD_ZIP)}
    # ONE approval lets ONE run through: the failed run spent it
    assert "refused: approval-spent:" in approve(twin, digest, 1).err and len(updates(twin, since)) == 1
    approve(twin, shown(twin), 0)
    assert config(twin)["CodeSha256"] == code_of(NEW_ZIP) and len(updates(twin, since)) == 2


def test_a_lost_reply_is_recorded_as_updating_and_a_new_update_code_settles_it_to_the_new_zip(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update(reply_garbage={"lambda update-function-code": "a reply that is no JSON"}))
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert "refused: reply-unreadable:" in ran.err and len(updates(twin, since)) == 1
    assert entry(twin)["status"] == "updating" and config(twin)["CodeSha256"] == code_of(NEW_ZIP)       # the work was done
    twin.edit(lambda a: a.pop("reply_garbage"))
    ran = twin.run("update-code", "function", expect=1)              # it reads first, and settles the record to the zip it is
    assert "update-code function:" in ran.out and "refused: nothing-to-update:" in ran.err and len(updates(twin, since)) == 1
    e = entry(twin)
    assert e["status"] == "created" and e["inputs"] == {"TWIN_BREAKER_ZIP": sha(NEW_ZIP)} and "update" not in e
    assert [tc.status_of(twin, step) for step in RUN_AGAIN] == ["stale", "stale"]
    assert "as rendered" in tc.status_lines(twin.run("status", expect=0))["function"]


LOST: List[Any] = [
    ("reply_garbage", "a reply that is no JSON", "refused: reply-unreadable:"),
    ("reply_dies", 255, "call 1 of 2 failed (lambda update-function-code: exit-255)"),
    ("reply_error", "ServiceException", "call 1 of 2 failed (lambda update-function-code: ServiceException)"),
]


@pytest.mark.parametrize("plant, value, said", LOST, ids=[p[0] for p in LOST])
def test_an_update_whose_reply_is_lost_is_settled_to_the_new_zip_by_status(twin: Rig, plant: str, value: Any, said: str) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update({plant: {"lambda update-function-code": value}}))
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert said in ran.err
    assert entry(twin)["update"]["sent"] == [0]                     # the call is on record, whether or not it answered
    if plant == "reply_garbage":
        assert "how it ended is not known" in ran.err
    assert len(updates(twin, since)) == 1
    assert entry(twin)["status"] == "updating"
    assert config(twin)["CodeSha256"] == code_of(NEW_ZIP)
    twin.edit(lambda a: a.pop(plant))
    ran = twin.run("status", expect=0)
    assert "update-code function:" in ran.out
    assert entry(twin)["status"] == "created"
    assert entry(twin)["inputs"] == {"TWIN_BREAKER_ZIP": sha(NEW_ZIP)}
    assert [tc.status_of(twin, s) for s in RUN_AGAIN] == ["stale", "stale"]
    assert "as rendered" in tc.status_lines(ran)["function"] and " created " in tc.status_lines(ran)["function"]


def test_a_wait_that_fails_leaves_the_update_on_record_and_status_settles_it(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "wait", "code": "WaiterFailure"}))
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert "call 2 of 2 failed (lambda wait: WaiterFailure)" in ran.err
    assert entry(twin)["update"]["sent"] == [0, 1]
    assert entry(twin)["status"] == "updating"
    assert len(updates(twin, since)) == 1
    twin.run("status", expect=0)
    assert entry(twin)["status"] == "created"
    assert entry(twin)["inputs"] == {"TWIN_BREAKER_ZIP": sha(NEW_ZIP)}
    assert "update" not in entry(twin)


def test_a_failed_last_update_settles_to_the_old_zip_whatever_the_code_reads(twin: Rig) -> None:
    """r3c#1 (i): the wait fails, the configuration keeps the CodeSha256 the update set and says LastUpdateStatus Failed: the
    previous code runs, and the record must not say the new zip does."""
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update(update_status="Failed"))
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "wait", "code": "WaiterFailure"}))
    approve(twin, digest, 1)
    assert entry(twin)["status"] == "updating" and config(twin)["CodeSha256"] == code_of(NEW_ZIP)
    ran = twin.run("status", expect=0)
    e = entry(twin)
    assert e["status"] == "created" and e["inputs"] == {"TWIN_BREAKER_ZIP": sha(OLD_ZIP)} and "update" not in e and not e.get("code_updates")
    assert "LastUpdateStatus) is Failed" in ran.err and "previous code runs" in ran.err
    assert [tc.status_of(twin, step) for step in RUN_AGAIN] == ["done", "done"]
    assert "DIFFERS" in tc.status_lines(ran)["function"]


def test_a_failed_read_back_in_the_run_that_sent_the_update_ends_refused(twin: Rig) -> None:
    """N2 (critic2-r4): settle_update()'s Failed branch in the run that sent the update (the stand-in's wait answers at once): the
    run ends refused, and the function is recorded as made from the zip it was made from."""
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update(update_status="Failed"))
    ran = approve(twin, digest, 1)
    assert "LastUpdateStatus) is Failed" in ran.err
    assert entry(twin)["status"] == "created" and entry(twin)["inputs"] == {"TWIN_BREAKER_ZIP": sha(OLD_ZIP)}


def test_an_update_in_progress_is_not_settled_and_nothing_is_sent(early: Rig) -> None:
    """r3c#1 (ii): LastUpdateStatus InProgress: refused by name, the record stays `updating`; once it reads Successful the record
    settles to the new zip."""
    granted(early)
    digest = shown(early)
    early.edit(lambda a: a.update(update_status="InProgress"))
    assert "refused: update-in-progress:" in approve(early, digest, 1).err
    assert entry(early)["status"] == "updating" and "update" in entry(early)
    since = len(early.log())
    ran = early.run("status", expect=0)
    assert "not settled (update-in-progress)" in ran.out and entry(early)["status"] == "updating"
    assert "refused: update-in-progress:" in early.run("update-code", "function", expect=1).err
    assert "refused: still-updating:" in early.go("apply", "go-live-rule", expect=1).err
    assert early.writes(since) == []
    early.edit(lambda a: a["functions"][FUNCTION]["config"].update(LastUpdateStatus="Successful"))
    early.run("status", expect=0)
    assert entry(early)["status"] == "created" and entry(early)["inputs"] == {"TWIN_BREAKER_ZIP": sha(NEW_ZIP)}


def test_an_update_whose_code_reads_as_neither_zip_stays_updating_and_is_refused(twin: Rig) -> None:
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "update-function-code", "code": "ServiceException"}))
    approve(twin, digest, 1)
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(CodeSha256=code_of(b"code that nobody built")))
    ran = twin.run("status", expect=0)
    assert "update-unsettled" in ran.out and entry(twin)["status"] == "updating"
    since = len(twin.log())
    assert "refused: update-unsettled:" in twin.run("update-code", "function", expect=1).err and twin.writes(since) == []
    assert entry(twin)["status"] == "updating"


def _edit_state(rig: Rig, change: Callable[[Dict[str, Any]], None]) -> None:
    path = rig.state / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    change(state)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def test_a_trip_is_not_stopped_before_its_invoke_by_a_function_record_whose_inputs_are_no_mapping(twin: Rig) -> None:
    """critic2#1: update_grant() runs in every command's Twin, the stop's among them; a state edited by hand must not end it first."""
    _edit_state(twin, lambda s: s["steps"]["function"].update(inputs=["no", "mapping"]))
    since = len(twin.log())
    twin.run("trip")
    assert [c[:2] for c in twin.writes(since)][:1] == [["lambda", "invoke"]]


def test_the_settle_of_an_update_is_held_to_the_caller(twin: Rig) -> None:
    """critic#4: a read answered by another account must not settle the twin's record on that account's function."""
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update(reply_garbage={"lambda update-function-code": "a reply that is no JSON"}))
    approve(twin, digest, 1)
    twin.edit(lambda a: a.pop("reply_garbage"))
    assert entry(twin)["status"] == "updating"
    twin.edit(tc.other_account)
    since = len(twin.log())
    ran = twin.run("update-code", "function", expect=1)
    assert "refused: identity-other-account:" in ran.err
    assert [c[:2] for c in sent(twin, since)] == [["sts", "get-caller-identity"]]
    assert entry(twin)["status"] == "updating"


def test_only_a_record_that_is_done_is_marked_to_run_again(twin: Rig) -> None:
    """K1: a record that is not `done` (here, one that is absent) is not made by the update."""
    _edit_state(twin, lambda s: s["steps"].pop("dry-trip"))
    granted(twin)
    approve(twin, shown(twin), 0)
    steps = tc.state_of(twin)["steps"]
    assert "dry-trip" not in steps and steps["function-status"]["status"] == "stale"


def test_a_record_that_is_stale_already_stays_as_it_is(twin: Rig) -> None:
    """run_again(): a record stale for another cause is not marked anew for the code update."""
    _edit_state(twin, lambda s: s["steps"]["function-status"].update(status="stale", stale_for="function"))
    granted(twin)
    approve(twin, shown(twin), 0)
    assert tc.state_of(twin)["steps"]["function-status"]["stale_for"] == "function"


def test_status_says_to_run_again_only_of_a_record_stale_for_the_update(twin: Rig) -> None:
    """K2: a stale record whose cause is another step's is not said to need a run for the code update."""
    def other_cause(s: Dict[str, Any]) -> None:
        s["steps"]["function-status"].update(status="stale", stale_for="function")
    _edit_state(twin, other_cause)
    lines = tc.status_lines(twin.run("status", expect=0))
    assert "function-status" in lines and "replaced in place" not in lines["function-status"]


def test_the_policy_holds_the_update_only_while_the_function_stands(twin: Rig) -> None:
    """K3: a function that is gone, with its inputs still recorded and the source changed, is no update due."""
    twin.run("plan", "--no-cli", expect=0)
    assert UPDATE in [a for s in twin.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function" for a in s["Action"]]
    tc.set_status(twin, "function", "deleted")
    twin.run("plan", "--no-cli", expect=0)
    assert UPDATE not in [a for s in twin.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function" for a in s["Action"]]


def test_update_code_names_only_the_function(twin: Rig) -> None:
    """K5: the parser takes no other step."""
    since = len(twin.log())
    twin.run("update-code", "alarms", expect=2)
    assert twin.log()[since:] == []


def test_two_updates_in_a_row_are_both_on_record(twin: Rig, source: Path) -> None:
    """r2c#2: the code_updates history keeps every update, not the last alone."""
    granted(twin)
    approve(twin, shown(twin), 0)
    source.write_bytes(NEWER_SOURCE)
    (twin.inputs / "breaker.zip").write_bytes(TW.zip_bytes(NEWER_SOURCE))
    approve(twin, shown(twin), 0)
    assert [(u["from"], u["to"]) for u in entry(twin)["code_updates"]] == [(sha(OLD_ZIP), sha(NEW_ZIP)),
                                                                          (sha(NEW_ZIP), sha(TW.zip_bytes(NEWER_SOURCE)))]


def test_a_function_record_with_no_hash_of_its_zip_makes_no_update_due(twin: Rig) -> None:
    """r2c#3: update_grant() has nothing to compare the source's build with."""
    _edit_state(twin, lambda s: s["steps"]["function"].pop("inputs"))
    twin.run("apply", "operator-role", expect=0)
    assert UPDATE not in [a for s in twin.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function" for a in s["Action"]]


def test_a_state_that_records_no_hash_of_the_zip_is_not_let_through(twin: Rig) -> None:
    """K7: the code cannot be compared, which is a difference like the others."""
    granted(twin)
    digest = shown(twin)
    _edit_state(twin, lambda s: s["steps"]["function"].pop("inputs"))
    since = len(twin.log())
    ran = approve(twin, digest, 1)
    assert "refused: function-differs:" in ran.err and "its code cannot be compared" in ran.err and twin.writes(since) == []


def test_a_source_that_cannot_be_built_makes_no_update_due(twin: Rig, source: Path) -> None:
    """critic2#7: update_grant()'s docstring says so; with the source gone the role's policy holds no update action."""
    source.unlink()
    twin.run("apply", "operator-role", expect=0)
    assert UPDATE not in [a for s in twin.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function" for a in s["Action"]]


def test_once_on_record_the_grant_outlives_a_teardown_of_the_function(tmp_path: Path, source: Path) -> None:
    """critic2#4: update_grant() keeps the action for good once a code update is on record (the role the owner changed keeps it)."""
    source.write_bytes(tc.BREAKER_SOURCE)
    rig = Rig(tmp_path / "f", notice=False).build(until="function-concurrency")
    source.write_bytes(NEW_SOURCE)
    edited(rig, tmp_path)
    granted(rig)
    approve(rig, shown(rig), 0)
    rig.go("teardown", "function")
    assert tc.status_of(rig, "function") == "deleted"
    rig.run("apply", "operator-role", expect=0)


def test_update_code_settles_a_refused_update_to_the_old_zip_and_prints_the_render_again(twin: Rig) -> None:
    """critic2#5: settle_update()'s message promises that update-code then prints the render again (exit 3)."""
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "update-function-code", "code": "ResourceConflictException"}))
    approve(twin, digest, 1)
    since = len(twin.log())
    ran = twin.run("update-code", "function", expect=3)
    found = tc.HASH.search(ran.out)
    assert "still the zip it was made from" in ran.err and found and found.group(1) == digest and twin.writes(since) == []
    assert entry(twin)["status"] == "created" and "update" not in entry(twin)


def test_an_update_whose_function_is_gone_stays_updating_and_is_not_settled(twin: Rig) -> None:
    """critic2#2: a function that is not found is neither zip; it is not settled as made from the old one."""
    granted(twin)
    digest = shown(twin)
    twin.edit(lambda a: a.update(reply_garbage={"lambda update-function-code": "a reply that is no JSON"}))
    approve(twin, digest, 1)
    twin.edit(lambda a: (a.pop("reply_garbage"), a["functions"].clear()))
    ran = twin.run("status", expect=0)
    assert "update-code function: not settled (update-unsettled)" in ran.out and entry(twin)["status"] == "updating"
    since = len(twin.log())
    assert "refused: update-unsettled:" in twin.run("update-code", "function", expect=1).err and twin.writes(since) == []
    assert entry(twin)["status"] == "updating"


# What CLI 2.35.1 said offline of the two calls, given --generate-cli-skeleton output (cli-probe, 2026-11-14): the CLI's own sample
# reply failing its own validation. Lines end in LF here (the capture's CRLF dropped); the probe's function name is in neither.
UPDATE_FUNCTION_CODE_SAID = (
    "\n"
    "aws: [ERROR]: An error occurred (ParamValidation): Parameter validation failed:\n"
    "Invalid value for parameter Timeout, value: 0, valid min value: 1\n"
    "Invalid value for parameter MemorySize, value: 0, valid min value: 128\n"
    "Invalid value for parameter EphemeralStorage.Size, value: 0, valid min value: 512\n"
    "Invalid length for parameter RuntimeVersionConfig.RuntimeVersionArn, value: 17, valid min length: 26" "\n"
    "Invalid value for parameter CapacityProviderConfig.LambdaManagedInstancesCapacityProviderConfig.PerE"
    "xecutionEnvironmentMaxConcurrency, value: 0, valid min value: 1\n"
    "Invalid value for parameter CapacityProviderConfig.LambdaManagedInstancesCapacityProviderConfig.Exec"
    "utionEnvironmentMemoryGiBPerVCpu, value: 0.0, valid min value: 2.0\n"
    "Invalid value for parameter DurableConfig.RetentionPeriodInDays, value: 0, valid min value: 1\n"
    "Invalid value for parameter DurableConfig.ExecutionTimeout, value: 0, valid min value: 1\n"
)
WAIT_SAID = (
    "\n"
    "aws: [ERROR]: An error occurred (ParamValidation): Parameter validation failed:\n"
    "Invalid value for parameter Configuration.Timeout, value: 0, valid min value: 1\n"
    "Invalid value for parameter Configuration.MemorySize, value: 0, valid min value: 128\n"
    "Invalid value for parameter Configuration.EphemeralStorage.Size, value: 0, valid min value: 512\n"
    "Invalid length for parameter Configuration.RuntimeVersionConfig.RuntimeVersionArn, value: 17, valid " "min length: 26\n"
    "Invalid value for parameter Configuration.CapacityProviderConfig.LambdaManagedInstancesCapacityProvi"
    "derConfig.PerExecutionEnvironmentMaxConcurrency, value: 0, valid min value: 1\n"
    "Invalid value for parameter Configuration.CapacityProviderConfig.LambdaManagedInstancesCapacityProvi"
    "derConfig.ExecutionEnvironmentMemoryGiBPerVCpu, value: 0.0, valid min value: 2.0\n"
    "Invalid value for parameter Configuration.DurableConfig.RetentionPeriodInDays, value: 0, valid min v" "alue: 1\n"
    "Invalid value for parameter Configuration.DurableConfig.ExecutionTimeout, value: 0, valid min value:" " 1\n"
    "Invalid length for parameter TagsError.ErrorCode, value: 9, valid min length: 10\n"
    "Invalid length for parameter TagsError.Message, value: 7, valid min length: 84\n"
)


@pytest.mark.parametrize("which, said", [(0, UPDATE_FUNCTION_CODE_SAID), (1, WAIT_SAID)])
def test_the_real_clis_offline_reading_of_each_new_call_is_placed_as_its_own_sample_failing(twin: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                             which: int, said: str) -> None:
    """The text was captured offline from CLI 2.35.1 on 2026-11-14 (a made-up function name, no credential, the closed port) from
    `update-function-code` and `wait function-updated-v2`. The calls are update-code's step's own (its Built), with the name made up.
    It shows the driver places that reading as the sample's, as the CLI said it then; the real service's answer is not covered."""
    for k in list(os.environ):
        if k.startswith(("TWIN_", "AWS_")) or k == "STUB_AWS_DIR":
            monkeypatch.delenv(k)
    built = TW.Twin(twin.state, None, False).render(TW.FUNCTION_CODE).built
    assert [c.op for c in built.creates] == ["update-function-code", "wait"]
    call = built.creates[which]
    call = TW.Call(call.service, call.op, tuple("twin-breaker-made-up-0000" if a == FUNCTION else a for a in call.args), call.write)
    assert "twin-breaker-made-up-0000" in call.args
    assert TW.sample_only(call, said) is True


def test_no_pinned_render_moves_while_no_update_is_due(tmp_path: Path) -> None:
    """The grant-always mutant: with no plan run and the function not made, the operator role's Function statement has no update."""
    r = Rig(tmp_path / "s", notice=False).start()
    r.run("apply", "operator-role")
    statement = [s for s in r.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function"]
    assert statement and UPDATE not in [a for s in statement for a in s["Action"]]


# ================================================================================================= the operator role and plan

def test_the_operator_policy_holds_the_update_only_while_it_is_due_or_on_record_and_plan_covers_its_calls(made: Rig, twin: Rig, source: Path,
                                                                                                         tmp_path: Path) -> None:
    def function_actions(rig: Rig) -> List[str]:
        return [a for s in rig.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function" for a in s["Action"]]

    # not due (the function stands on the build of the source as it stands): the policy as tests/test_sdv_cloud.py pins it, and no
    # update in plan
    source.write_bytes(tc.BREAKER_SOURCE)
    plain = made.copy(tmp_path / "plain")
    plain.run("plan", "--no-cli", expect=0)
    assert UPDATE not in function_actions(plain) and "function-code" not in [s["id"] for s in plain.plan()]
    source.write_bytes(NEW_SOURCE)
    # due: the policy holds the action, plan lists the update's calls, gives them to the CLI and holds the policy to them
    ran = twin.run("plan", expect=0)
    assert UPDATE in function_actions(twin) and "0 gap(s) in the operator role's policy" in ran.out and UPDATE in ran.out
    step, = [s for s in twin.plan() if s["id"] == "function-code"]
    assert [c[:3] for c in step["creates"]] == [["lambda", "update-function-code", "--function-name"], ["lambda", "wait", "function-updated-v2"]]
    assert [c[:2] for c in step["reads"]] == [["lambda", "get-function"]] and step["deletes"] == []
    skeletons = [e["argv"][:2] for e in twin.log("skeleton.jsonl")]
    assert ["lambda", "update-function-code"] in skeletons and ["lambda", "wait"] in skeletons
    calls = [TW.Call(c[0], c[1], tuple(c[2:]), False) for c in step["creates"] + step["reads"]]
    assert TW.operator_gaps(twin.doc("operator-role", "operator-role-policy"), calls) == []
    without = copy.deepcopy(twin.doc("operator-role", "operator-role-policy"))
    tc._allow(without, "Function")["Action"].remove(UPDATE)
    assert TW.operator_gaps(without, calls) == ["%s (lambda update-function-code) is allowed by no statement" % UPDATE]
    # the role the owner made before reads as not the render (the live gap) until it is changed by hand
    assert "its policy is not the render" in tc.status_lines(twin.run("status", expect=0))["operator-role"]
    granted(twin)
    since = len(twin.log())
    approve(twin, shown(twin), 0)
    # once on record the action stays, with the source's build recorded: the role is read as rendered
    twin.run("plan", "--no-cli", expect=0)
    assert UPDATE in function_actions(twin) and "as rendered" in tc.status_lines(twin.run("status", expect=0))["operator-role"]
    # every call the update sent is one plan lists
    listed = {tc.sig(c) for c in tc.every_call(twin)}
    assert {tc.sig(c) for c in sent(twin, since)} - listed == set()


def fold(text: str) -> str:
    return " ".join(text.split())


def test_the_readme_and_the_docstring_say_what_update_code_does() -> None:
    readme = fold((tc.REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))
    doc = fold(str(TW.__doc__))
    for text in (readme, doc):
        assert "update-code function" in text and "function-code:HASH" in text
        assert "breaker.py" in text and "function-status" in text and "dry trip" in text
    assert "**Replacing the function's code in place.**" in readme and "by hand (IAM)" in readme
    # critic#2: what stood on the old code is taken back, and on a live twin running it again cuts
    assert "the alarm tests and `reattach-policy` are `stale` too" in readme and "the alarm tests and reattach-policy are `stale` too" in doc
    for text in (readme, doc):
        assert "on a twin that is live the dry trip and each alarm test cut as a trip does" in text
    assert "after a source change of `breaker/breaker.py` alone, `twinctl update-code function` (below)" in readme
    # r2c#4 (critic2#3's wording): restore gives the calls, and the old wording does not come back
    for text in (readme, doc):
        assert "restore` gives the calls that make it live again" in text
    # r3c#1: LastUpdateStatus is read first, and its three values are said to be from the documentation as remembered
    assert "It reads the function's `LastUpdateStatus` first" in readme and "after its LastUpdateStatus (InProgress: refused" in doc
    for text in (readme, doc):
        assert "update-in-progress" in text and "documentation as remembered" in text
    assert "makes it live again" not in ((tc.REPO / "sdv" / "cloud" / "twinctl.py").read_text(encoding="utf-8")
                                         + (tc.REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))


README_WIDTH = 120                                      # the README's prose around the entry: the paragraphs before it and after it


def test_the_readmes_update_code_entry_is_within_the_width_of_its_neighbours() -> None:
    """r2c#5 (NIT package 9, item 3.4): the README's update-code entry, from its bold lead to the next bold lead, is wrapped to the
    width of the paragraphs around it."""
    text = (tc.REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8")
    start = text.index("**Replacing the function's code in place.**")
    end = text.index("\n\n**", start)
    before = text[:start].rstrip("\n").rsplit("\n\n", 1)[-1]
    after = text[end + 2:].split("\n\n", 1)[0]
    assert max(len(line) for line in (before + "\n" + after).split("\n")) <= README_WIDTH
    wide = [(n, len(line)) for n, line in enumerate(text[start:end].split("\n")) if len(line) > README_WIDTH]
    assert wide == [], wide
