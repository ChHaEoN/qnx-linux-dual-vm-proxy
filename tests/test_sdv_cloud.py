"""The twin's create and teardown driver (sdv/cloud/twinctl.py, sdv/cloud/templates/): SDV Phase 4 WP6.

NO AWS CALL IS MADE HERE, AND NO CREDENTIAL IS READ. The driver's executable is tests/twin_stub_aws.py, a stand-in
for the CLI written in Python: one account in a JSON file under the test's own directory, three logs of what
arrived. Every reply the stub gives is written from memory of the service's documentation, so these tests show the
driver consistent with that reading, never the reading itself.

A TEST FIXTURE IS CAPTURE DATA. The account id is the documentation account read backwards, the names say
"example", the address is in the documentation range, the endpoint's prefix, the certificate ids and the canonical
id are digests of a sentence, and the thresholds are invented counts. They are put together when the tests run and
stand in no file as written: `twinctl literals` refuses a value the work tree already holds, and these are its
literals.

What is held here (the driver contract, and the rules carried over from the hard review)
  plan       executes nothing (the stub's log of executed calls is empty; the control call arrived without a
             credential; every other call arrived with --generate-cli-skeleton, two empty credential files and the
             closed endpoint), and its rendered list is what the stub receives in a real run. A step whose input
             is not there (the thresholds file, the breaker's zip) is refused by name.
  documents  the device policy is topics.py and holds no wildcard; each service role has exactly its actions on
             its one resource; the operator role's policy is A1 row 3's statements; the function's resource policy
             is one statement per breaker alarm; the rule payload is one firehose action, batchMode false,
             ruleDisabled true; every alarm is notBreaching with gap q's dimensions and a threshold of the file;
             the bucket policy is its two Deny statements. A template that gains a wildcard, an action or another
             value fails every command that renders it.
  apply      refuses without an approval, with another step's, with one for a changed render, with one that was
             never shown, and under an identity that is not the operator role; refuses what exists and is not
             ours; a create that fails half-way leaves a state `teardown` finishes from.
  teardown   the table in reverse; the bucket is never emptied without the approval of that very step and
             listing; the thing is not deleted while a named shadow is listed; a certificate is INACTIVE and
             detached first; a step is safe to repeat. `verify-gone` fails on one extra name in a listing.
  restore    refused while a breaker alarm is missing, in ALARM or has its actions disabled.
  status     fails when the function's environment is not exactly the twin's certificates, and when an ACTIVE
             certificate of the account is outside the twin's set.
  output     no identifier shape, no literal and no local directory reaches stdout or stderr; a state, render or
             capture directory inside a work tree is refused before anything is made.
  encoded    no call asks for --log-type; a reply that holds LogResult is refused before anything is copied.
  literals   a value under 8 characters and a value the work tree already holds are refused by position.
  branch-scan (the one test that runs git; from Windows Git Bash, deselected in WSL) finds a literal that one
             commit of a fixture repository adds and the next removes, and one that is only in a commit message.
  names      a state records, salted, the names it was made under: under other names every command is refused, by
             the key's name and never by its value, until nothing stands and a new baseline takes the new names.
  after the first re-check (WP6-verify-1)
             an approval lets ONE run of its calls through; every call a command sends is one `plan` lists, and
             the operator role's rendered policy allows each of them and denies none; `status` makes its two
             assertions although another read is denied; a listing that says there is more is no whole listing;
             `trip` goes on without the literals file and on a state that cannot be read, and a refused trip
             prints the four calls by hand; a teardown needs no create-time input.
  after the hard review (fable-wp6) and the second re-check (WP6-verify-2)
             every command that sends a call reads the caller's identity first: the reads are held to the operator
             role like the writes, the stop to the account alone, and the runner sends nothing before that read;
             a teardown whose render stands on a value the state lost is refused, and a step with nothing to read
             is never "read back, not found"; a certificate whose reply was refused is torn down by the id the
             reply gave; the role, the profile and the notice's switch are names a state is bound to, and the
             first two are in every render's hash; a record of an action or of an owner-made role does not
             outlive what it stood on; a sample reply's member is read by its whole path, so `plan` is clean under
             a prefix of 8 characters; a step the state records stays in the table when its keys are taken out;
             the salt gone is said by its name; a step being deleted is not made again before it is recorded as
             deleted; a path of the names file in Git Bash's form is refused under Windows Python; IoT's own log
             group, when it was there before, is adopted by the owner's switch and never created or deleted.
  with the breaker (WP7's integration)
             THE FUNCTION IS THE REAL ONE: the stand-in runs the handler of sdv/cloud/breaker/breaker.py out of the
             zip the function was created from, over fake clients that act on the stand-in's account, so every
             trip, dry trip, alarm's test and status invoke here is that file's code and its own record. An
             approval covers the CONTENT of the zip and of the signing request, and the function is held to the
             hash the state recorded; a create whose reply is lost is on record before it is sent, and its
             teardown is settled by the listing, never taken back unread; a step with no read is never "not
             found" in `status` or `apply`; `recover` puts the certificate's id back from a reply of the state
             directory, and only once the account showed the one certificate that reply made; `build-breaker`
             writes the zip; the status invoke's two facts are printed; the function's environment and its
             role's policy name the same resources.
  the carried regression cases (WP7-tests20)
             each value a step's judge compares is changed in the account on its own (the bucket's ownership, versioning and
             lifecycle, the stream's status, the rule before and after go-live, the thing's attributes, the device policy, the
             Glue table, the workgroup, a log group's retention, the function's layer, VPC and URL, an alarm in ALARM, IoT
             logging's level and role) and the step says that one reason; a step stands only on a step recorded as made and
             proven (half made, not proven, being made); an invoke that ends in a function error is not recorded as done; a
             security group's IPv6 ranges are counted; the bucket's objects are not deleted by a caller the profile became after
             the listing, nor under an approval already spent; verify-gone counts a recorded step it could not read; the
             notice topic is not recorded as made while its subscription waits for the owner.
  after WP7's first verification (WP7-verify-r1)
             a step that stands, approved AGAIN with another zip or signing request at the path, is not "already made, as
             rendered"; a create the service ANSWERED with an error stays on record like one whose reply was lost (no error
             code is trusted to say that nothing was made), and the listing settles its teardown; a trip's write words are
             printed from the function's own record, in the form a write word has and in no other; an action's `done` is the
             record of its last run, and a run that does not come to its end takes it back with what stood on it.
  after WP7's second verification and its hard review (WP7-verify-r2, fable-wp7)
             `apply` reads the certificates' listing before it creates one and refuses a name neither the baseline nor a
             state knows (the stub's listing can be made to lag one read behind a create); a manual trip that ends in a
             function error takes the dry trip's record back; a trip whose invoke failed still prints the status, and a
             throttled one says that a run may be under way; a function error is said by its kind and by the file its
             message is read in; the status invoke names what the function-status reading records on addresses.
  the owner's two calls on WP7 (2026-10-12)
             the function's own failure message IS printed, and only when the error's type is the breaker's own and
             every clause of the message is one of the function's own sentence forms (a table the driver holds, and
             this file holds equal to breaker.py's source): any other type, a clause outside the table, a count that
             is not the clauses', a control character stay the read-by-hand sentence; `apply function` refuses a zip
             that is not the build of the breaker's source as it stands, its printed render says so, `plan` says so,
             and `status` says beside the function's line when the source has changed since the recorded build.
  WP8's fixes before A2 (the re-checks of 2026-10-12 and the owner's decision of that day)
             the operator role's Glue statement holds every resource the database's delete is authorised on, the
             user-defined functions among them, and none outside the prefix (the driver's own check matches no
             resource and could not see it); a trip's FIRST act is the file of the four calls by hand, in the state
             directory, so that no ending before its invoke is only a refusal: the file is written and its place
             said before the refusal is, it holds this twin's values as far as the names file and the state give
             them and never another twin's certificate, a call that lacks a value is a comment, and each open slot
             is said by its key; a trip is held to the account and not to the role or the profile a state was made
             under; the one region whose buckets take no LocationConstraint is refused where the names are read,
             by the key and never by the value.
  after the rehearsal of WP8 and the hard review of its fixes (wp8-review-fix)
             a trip needs no operator role: with the key gone from the names file, or not in its form, it says so and
             goes on; an invoke that was sent and whose answer is not known is said so, with the status, and is no trip
             "refused before the function was invoked"; the caller is read once more before a trip's status, and a
             profile that came to answer for another account gets no status; a reply to the read of the caller that
             names no account is an identity that could not be read; a call by hand keeps its values without a profile
             the names do not give, the file gives the read that finds the certificate's id, says whose set it is for,
             and the file a failed write got as far as is named when it holds the run's calls; a mistyped stop gets
             its file in the state directory its line names, and no word that could not be read is printed; with no
             CLI the console's way is named; a kind the owner added to the literals file (the region among them) is
             taken by every command and by a stop whose file is behind; a go-live step that was tripped reads as not
             live and its refusals name `restore`; of a function error only the kind goes into a capture unless the
             message is the function's own; the rehearsal's plan holds its calls to the twin's operator policy.
  after the last verification of WP8's fixes (verify-final, the package its critic left for before A2)
             of argparse's message for a line it could not read, an ambiguous option is cut at its `=`, and an argument an
             option ignored and a word quoted in either quotes are not printed; a mistyped stop that names its state
             directory twice gets its file in the last one, as argparse takes it; only the one region is refused, not a
             region beside it; and a state made under the default region records its names and is held to them.
  Phase 6 WP4 (the image transport: the image-transport contract)
             WITH NO NEW KEY NOTHING MOVES: every existing step renders, hashes, reads and lists as at the baseline
             recorded before Phase 6 WP4. The commands `status`, `exit-checks`, the teardown's order, `verify-gone`,
             `plan` and `literals` print as there
             (the values recorded from that tree before any edit, under a fixed salt, the rig's directory written as <base>);
             with the keys, only the operator role's policy and the calls outside the table change. TWIN_ECR=1 adds the ECR
             steps after every step of the twin's: a repository per app, IMMUTABLE, AES256, tagged, with no policy ever, its
             lifecycle of one rule; one that is there and not ours is refused; one with an image is not deleted. TWIN_PULL_ROLE
             adds the pull steps: the role trusted by the credential provider alone for the alias, its three ECR actions and no
             fourth, the alias for 3600 s, the IoT policy of one action, the certificate INACTIVE from the Orin's request and
             set ACTIVE and INACTIVE by its own printed hash, the thing only with its key; the pull role is bound once recorded.
             The operator policy gains each set of grants only with its key, ECR Public's writes denied in place of
             ecr-public:*; the wildcard exceptions gain the repositories and the token's * and nothing else. `status` says an
             ACTIVE pull certificate and fails on one outside both sets; `exit-checks` adds the ECR and pull rows and each
             fails on its finding. `push` prints its render and sends nothing without the approval; with it, the config digest
             is proved before anything is tagged (an index, another digest, another architecture refused), the password goes
             by a pipe and is left in no file, and the registry's digest is read back and recorded; `ecr-config` writes the
             host's file mode 0600 and prints nothing of it. Every call of the new steps and commands is one `plan` lists, and
             the operator policy lets each through. The docker stand-in is twin_stub_aws.py's --docker mode.

Standard library and pytest.

Does not demonstrate: that a call is authorised, that a name is free, what a real reply holds, or what a call
costs. The offline validation by the real CLI is the opt-in test at the end (SDV_TWINCTL_REAL_CLI=1, off by
default, Windows only since WSL has no CLI): it makes no AWS call and reads no credential, and is not part of the
recipe.
"""
import ast
import base64
import contextlib
import copy
import fnmatch
import getpass
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STUB = HERE / "twin_stub_aws.py"
TEMPLATES = REPO / "sdv" / "cloud" / "templates"


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


TW = _load("sdv_cloud_twinctl_under_test", REPO / "sdv" / "cloud" / "twinctl.py")
LS = _load("sdv_cloud_leakscan_under_test", REPO / "scripts" / "aws" / "leakscan.py")
TOPICS = _load("sdv_connector_topics_under_test", REPO / "sdv" / "connector" / "topics.py")


def j(*parts: str) -> str:
    """A fixture value, put together here: it stands in no file of the work tree as written."""
    return "".join(parts)


ACCOUNT = "123456789012"[::-1]                  # the documentation account, backwards
REGION = "eu-west-1"                            # any region but the one the driver refuses (TW.GLOBAL_REGION), and not its default
PREFIX = j("example", "twin", "zz")
THING = j(PREFIX, "-thing")
SUFFIX = j("0a1b2c", "3d4e5f", "zz")
ROLE = j("example", "-operator-role", "-zz")
PROFILE = j("example", "-operator", "-zz")
ADDRESS = j("owner", "-zz@", "example.com")
ENDPOINT_PREFIX = "a" + hashlib.sha256(b"the stub's endpoint").hexdigest()[:13]
ENDPOINT = j(ENDPOINT_PREFIX, "-ats.iot.", REGION, ".amazonaws.com")
CANONICAL = hashlib.sha256(b"the stub's canonical user").hexdigest()
CERT_1 = hashlib.sha256(b"stub certificate 1").hexdigest()      # what the stub gives its first certificate
SESSION_ARN = "arn:aws:sts::%s:assumed-role/%s/session" % (ACCOUNT, ROLE)
ROLES = {"operator-role": ROLE, "rule-role": PREFIX + "-rule-role", "firehose-role": PREFIX + "-firehose-role",
         "iot-logging-role": PREFIX + "-iot-logging-role", "breaker-role": PREFIX + "-breaker-role"}
IDENTIFIERS = (ACCOUNT, PREFIX, THING, SUFFIX, ROLE, PROFILE, ADDRESS, ENDPOINT_PREFIX, CANONICAL, CERT_1)
BREAKER = ("bytes", "records", "shadow", "publish", "failure")
# Invented counts: no design the owner chose, no figure derive.py wrote.
THRESHOLDS = {"Firehose.IncomingBytes": 2000000, "Firehose.IncomingRecords": 600, "IoT.UpdateThingShadow.Accepted": 26,
              "IoT.PublishIn.Success": 700, "IoT.RuleAction.Failure": 1, "IoT.RulesExecuted.per_execution": 610,
              "IoT.RulesExecuted.per_5kb_unit": 900, "Lambda.Errors": 1}
# What stands in for derive.py --check: it passes the file this module writes and refuses any other, by a name.
DERIVE_DOUBLE = '''import json, sys
args = sys.argv[1:]
if len(args) != 2 or args[0] != "--check":
    sys.exit(2)
with open(args[1]) as f:
    doc = json.load(f)
if doc.get("the_double_says") != "ok":
    sys.stderr.write("design estimate | refused: check-differs: the double refuses this file\\n")
    sys.exit(1)
'''
HASH = re.compile(r"render sha256: ([0-9a-f]{64})")
BREAKER_SOURCE = (REPO / "sdv" / "cloud" / "breaker" / "breaker.py").read_bytes()
BREAKER_ZIP = TW.zip_bytes(BREAKER_SOURCE)      # what `twinctl build-breaker` writes: the stub runs the handler out of it
COMMON = 7                                      # --region R --profile P --output json --no-cli-pager


def thresholds_doc(notice: bool) -> Dict[str, Any]:
    return {"the_double_says": "ok",
            "design": {"cap_usd": 10.0, "decided_cap_usd": 10.0, "n_days": 730.0 / 24.0, "things": 1, "alarms_priced": 7 if notice else 6,
                       "config_change_s": 60, "batch_bytes": 15387, "batch_bytes_largest": 15387, "share_messages": 0.3,
                       "share_bytes": 0.3, "share_shadow": 0.4, "period_s": 300, "periods_per_month": 8760},
            "thresholds": dict(THRESHOLDS)}


def new_account() -> Dict[str, Any]:
    return {"account": ACCOUNT, "region": REGION, "profile": PROFILE,
            "identity": {"UserId": j("AROA", "EXAMPLEEXAMPLEEX", ":session"), "Arn": SESSION_ARN},
            "endpoint": ENDPOINT, "canonical": CANONICAL, "buckets": {}, "log_groups": {}, "streams": {}, "rules": {}, "things": {},
            "certs": {}, "policies": {}, "glue": {}, "workgroups": {"primary": {"configuration": {}}}, "functions": {}, "topics": {},
            "alarms": {}, "roles": {}, "iot_logging": None, "faults": [],
            "account_block": {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True},
            "security_groups": [{"GroupId": "sg-0123abcd", "GroupName": "example", "IpPermissions": [
                {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "203.0.113.7/32"}], "Ipv6Ranges": []}]}]}


class Ran:
    def __init__(self, rc: int, out: str, err: str) -> None:
        self.rc, self.out, self.err = rc, out, err
        self.text = out + err


def twinctl(argv: List[str], env: Dict[str, str]) -> Ran:
    """twinctl's main in this process, with no TWIN_ or AWS_ variable but the ones given."""
    saved = dict(os.environ)
    out, err = io.StringIO(), io.StringIO()
    try:
        for k in list(os.environ):
            if k.startswith(("TWIN_", "AWS_")) or k == "STUB_AWS_DIR":
                del os.environ[k]
        os.environ.update(env)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = TW.main(argv)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return Ran(rc, out.getvalue(), err.getvalue())


class Rig:
    """A state directory, a stub account and the inputs the names file points at, under one base directory."""

    def __init__(self, base: Path, notice: bool = True, fresh: bool = True) -> None:
        self.base = base
        self.notice = notice
        self.state = base / "state"
        self.stub = base / "stub"
        self.inputs = base / "inputs"
        self.render = self.state / "render"
        self.said: List[Ran] = []
        self.extra: Dict[str, str] = {}
        if fresh:
            for d in (self.state, self.stub, self.inputs):
                d.mkdir(parents=True)
            (self.inputs / "thresholds.json").write_text(json.dumps(thresholds_doc(notice)), encoding="ascii")
            (self.inputs / "derive.py").write_text(DERIVE_DOUBLE, encoding="ascii")
            (self.inputs / "breaker.zip").write_bytes(BREAKER_ZIP)
            (self.inputs / "device.csr").write_text("a test's placeholder, not a signing request\n", encoding="ascii")
            self.put_account(new_account())
        self.write_names()

    def names(self) -> Dict[str, str]:
        v = {"TWIN_ACCOUNT": ACCOUNT, "TWIN_REGION": REGION, "TWIN_PROFILE": PROFILE, "TWIN_OPERATOR_ROLE": ROLE, "TWIN_PREFIX": PREFIX,
             "TWIN_THING": THING, "TWIN_BUCKET_SUFFIX": SUFFIX, "TWIN_NOTICE": "1" if self.notice else "0",
             "TWIN_THRESHOLDS": str(self.inputs / "thresholds.json"), "TWIN_SHARES": "0.3,0.3,0.4",
             "TWIN_BREAKER_ZIP": str(self.inputs / "breaker.zip"), "TWIN_CSR": str(self.inputs / "device.csr"),
             "TWIN_CERTIFICATE_OUT": str(self.inputs / "cert.pem"), "TWIN_REHEARSAL_CSR": str(self.inputs / "device.csr"),
             "TWIN_REHEARSAL_CERTIFICATE_OUT": str(self.inputs / "rehearsal-cert.pem")}
        if self.notice:
            v["TWIN_NOTICE_ADDRESS"] = ADDRESS
        return v

    def write_names(self, **change: Optional[str]) -> None:
        v: Dict[str, Optional[str]] = dict(self.names())
        v.update(change)
        text = "# the test's names file\n" + "".join("%s=%s\n" % (k, x) for k, x in sorted(v.items()) if x is not None)
        (self.state / "names.env").write_text(text, encoding="utf-8")

    def copy(self, base: Path, logs: bool = True) -> "Rig":
        """This rig as it stands, in another directory: the names file is written anew for the new place. Without
        `logs`, the stub's logs of what arrived so far are left behind."""
        shutil.copytree(str(self.base), str(base))
        if not logs:
            for name in ("log.jsonl", "skeleton.jsonl", "refused.jsonl", "unknown.jsonl"):
                if (base / "stub" / name).exists():
                    (base / "stub" / name).unlink()
        return Rig(base, self.notice, fresh=False)

    # --- the stub's account and logs
    def account(self) -> Dict[str, Any]:
        return json.loads((self.stub / "account.json").read_text(encoding="utf-8"))

    def put_account(self, account: Dict[str, Any]) -> None:
        (self.stub / "account.json").write_text(json.dumps(account, indent=1, sort_keys=True), encoding="utf-8")

    def edit(self, change: Any) -> None:
        a = self.account()
        change(a)
        self.put_account(a)

    def log(self, name: str = "log.jsonl") -> List[Dict[str, Any]]:
        p = self.stub / name
        return [json.loads(line) for line in p.read_text(encoding="utf-8").split("\n") if line.strip()] if p.is_file() else []

    def writes(self, since: int = 0) -> List[List[str]]:
        """The calls that changed the account, in order, without the common arguments the driver adds."""
        out = []
        for e in self.log()[since:]:
            if e["w"]:
                assert e["argv"][-COMMON:] == ["--region", REGION, "--profile", PROFILE, "--output", "json", "--no-cli-pager"], e["argv"]
                out.append(e["argv"][:-COMMON])
        return out

    # --- the driver
    def run(self, *argv: Any, env: Optional[Dict[str, str]] = None, expect: Optional[int] = None) -> Ran:
        given = {"TWIN_STATE": str(self.state), "TWIN_AWS": str(STUB), "STUB_AWS_DIR": str(self.stub)}
        given.update(self.extra)
        given.update(env or {})
        ran = twinctl([str(a) for a in argv], given)
        self.said.append(ran)
        rc = ran.rc
        if expect is not None and rc != expect:
            trace = self.state / "twinctl-error.log"
            pytest.fail("twinctl %s: exit %d, expected %d\n--- stdout\n%s\n--- stderr\n%s\n--- trace\n%s"
                        % (" ".join(str(a) for a in argv), rc, expect, ran.out, ran.err,
                           trace.read_text(encoding="utf-8") if trace.is_file() else "(none)"))
        return ran

    def shown(self, mode: str, step: str, *more: str) -> str:
        """Print the step's render and give its hash; nothing is done."""
        before = len(self.writes())
        ran = self.run(*more, mode, step, expect=3)
        assert len(self.writes()) == before, "printing a render changed the account"
        found = HASH.search(ran.out)
        assert found, ran.text
        return found.group(1)

    def go(self, mode: str, step: str, *more: str, expect: int = 0) -> Ran:
        """The step, shown and then approved as shown."""
        digest = self.shown(mode, step, *more)
        return self.run(*more, mode, step, "--approve", "%s:%s" % (step, digest), expect=expect)

    def plan(self) -> List[Dict[str, Any]]:
        return list(json.loads((self.render / "plan.json").read_text(encoding="utf-8"))["steps"])

    def doc(self, step: str, name: str) -> Any:
        return json.loads((self.render / step / (name + ".json")).read_text(encoding="ascii"))

    def owner_makes(self, step: str) -> None:
        """What the owner does by hand: the role, from the render, in the account."""
        role = ROLES[step]

        def add(a: Dict[str, Any]) -> None:
            a["roles"][role] = {"trust": self.doc(step, step + "-trust"), "policies": {role + "-policy": self.doc(step, step + "-policy")}}
        self.edit(add)

    def start(self) -> "Rig":
        self.run("literals", expect=0)
        self.run("baseline", expect=0)
        return self

    def build(self, until: Optional[str] = None) -> "Rig":
        """Every step of the table in order, each approved as shown, the owner's roles made from their renders."""
        self.start()
        self.run("plan", expect=0)
        for step in self.plan():
            if step["id"] == until:
                break
            if step["kind"] == "owner":
                self.run("apply", step["id"])                       # renders it with what the state now knows
                self.owner_makes(step["id"])
                self.run("apply", step["id"], expect=0)
            elif step["id"] == "notice-topic":
                # made, and not proven until the owner confirmed the subscription with the token from the e-mail: the same
                # approval then reads again
                digest = self.shown("apply", step["id"])
                pending = self.run("apply", step["id"], "--approve", "%s:%s" % (step["id"], digest), expect=1)
                assert "its subscription waits for the owner's confirmation" in pending.err
                self.edit(lambda a: a["topics"][list(a["topics"])[0]]["subscriptions"][0].update(confirmed=True))
                again = self.run("apply", step["id"], "--approve", "%s:%s" % (step["id"], digest), expect=0)
                assert "already made, nothing was created" in again.out
            elif step["kind"] in ("resource", "action"):
                self.go("apply", step["id"])
        return self


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """The whole table applied once, with the notice topic. Tests that change anything work on a copy."""
    return Rig(tmp_path_factory.mktemp("built") / "twin").build()


@pytest.fixture(scope="module")
def started(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """Literals and a baseline, nothing made. Tests that change anything work on a copy."""
    return Rig(tmp_path_factory.mktemp("started") / "twin").start()


@pytest.fixture
def rig(tmp_path: Path, started: Rig) -> Rig:
    return started.copy(tmp_path / "rig", logs=False)


@pytest.fixture
def twin(tmp_path: Path, built: Rig) -> Rig:
    return built.copy(tmp_path / "twin")


def every_call(rig: Rig, name: str = "plan.json") -> List[List[str]]:
    """Every call `plan` lists: each step's creates, reads and deletes, the calls outside the table, the listings."""
    doc = json.loads((rig.render / name).read_text(encoding="utf-8"))
    return [c for s in doc["steps"] + [doc["other"]] for kind in ("creates", "reads", "deletes") for c in s.get(kind, [])] + doc["listings"]


def sig(argv: List[str]) -> Any:
    """A call by its service, its operation and the options it gives, less the ones the runner adds to every call."""
    common = ("--region", "--profile", "--output", "--no-cli-pager")
    return (argv[0], argv[1], tuple(sorted(a for a in argv[2:] if a.startswith("--") and a not in common)))


def clean(text: str) -> List[str]:
    """What must never be printed and is in `text`: a shape the scanner knows, a literal, a fixture identifier."""
    found = ["%s (%d chars)" % (label, len(tok)) for label, tok in LS.findings(text, False, list(IDENTIFIERS))]
    return found + ["identifier %d" % i for i, value in enumerate(IDENTIFIERS) if value in text]


HAND_FILE = "trip-by-hand.txt"                  # in the state directory: what a trip writes before anything else


def by_hand(rig: Rig) -> Tuple[List[str], List[str]]:
    """The file a trip writes first: (its lines to run, its comment lines). LF, and nothing but the two kinds."""
    text = (rig.state / HAND_FILE).read_text(encoding="utf-8")
    assert text.endswith("\n") and "\r" not in text and "\n\n" not in text
    lines = text.split("\n")[:-1]
    assert all(x.startswith(("aws ", "# ")) for x in lines), lines
    return [x for x in lines if x.startswith("aws ")], [x for x in lines if x.startswith("# ")]


def whole_by_hand(prefix: str = PREFIX, thing: str = THING, cert: str = CERT_1, region: str = REGION, profile: str = PROFILE,
                  account: str = ACCOUNT) -> List[str]:
    """The manual stop's four calls with a twin's own values, as the lines the owner runs: written out here, not taken from the driver.
    With no profile (""), as the manual stop has them: the profile is then the shell's."""
    common = "--region %s" % region + (" --profile %s" % profile if profile else "")
    return ["aws iot disable-topic-rule --rule-name %s_telemetry %s" % (prefix, common),
            "aws iot update-certificate --certificate-id %s --new-status INACTIVE %s" % (cert, common),
            "aws iot-data delete-connection --client-id %s %s" % (thing, common),
            "aws iot detach-policy --policy-name %s-device --target arn:aws:iot:%s:%s:cert/%s %s" % (prefix, region, account, cert, common)]


# ================================================================================================= plan

def test_plan_executes_nothing_and_gives_every_call_to_the_cli_offline(rig: Rig) -> None:
    before = len(rig.log())
    # what the caller's own shell may hold: a profile, a key, a proxy that leads out. None of it reaches the CLI.
    ran = rig.run("plan", expect=0, env={"AWS_PROFILE": PROFILE, "AWS_ACCESS_KEY_ID": "a-key-of-the-callers-shell", "AWS_SESSION_TOKEN": "x",
                                         "AWS_DEFAULT_REGION": "eu-north-1", "HTTPS_PROXY": "http://proxy.example.com:8080",
                                         "AWS_ENDPOINT_URL": "https://example.com/"})
    assert rig.log()[before:] == [], "plan executed a call"
    assert not rig.log("unknown.jsonl")
    # the control: one real call under the offline settings, which arrived with no credential
    refused = rig.log("refused.jsonl")
    assert [e["argv"][:2] for e in refused] == [["sts", "get-caller-identity"]] and "--profile" not in refused[0]["argv"]
    skeleton = rig.log("skeleton.jsonl")
    assert skeleton
    for e in skeleton:
        argv = e["argv"]
        if e["env"] is None:                                        # a read whose sample reply the CLI itself refuses: read all the same
            assert tuple(argv[:2]) in {("iam", "get-role"), ("lambda", "list-functions"), ("cloudwatch", "describe-alarms"),
                                       ("iot", "list-certificates"), ("firehose", "describe-delivery-stream")}
            continue
        assert argv[argv.index("--generate-cli-skeleton") + 1] == "output" and "--profile" not in argv
        assert argv[argv.index("--endpoint-url") + 1] == TW.OFFLINE_ENDPOINT == "http://127.0.0.1:9"
        assert e["env"]["credentials_empty"] and e["env"]["config_empty"] and e["env"]["metadata_disabled"]
        assert e["env"]["proxy"] == TW.OFFLINE_ENDPOINT
        assert set(e["env"]["aws_variables"]) <= {"AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE", "AWS_EC2_METADATA_DISABLED", "AWS_PAGER",
                                                 "AWS_MAX_ATTEMPTS"}
    # every call of the table was read by the CLI: creates, reads, deletes and listings; and so was every call a command
    # sends that is no step's own (the identity, the tag query, the exit's reads, the trip, the lines by hand)
    planned = {tuple(c) for c in every_call(rig)}
    assert {tuple(call.argv()) for call, _names in TW.LISTINGS.values()} <= planned
    other = json.loads((rig.render / "plan.json").read_text(encoding="utf-8"))["other"]
    assert {tuple(c[:2]) for kind in ("creates", "reads") for c in other[kind]} >= {
        ("sts", "get-caller-identity"), ("resourcegroupstaggingapi", "get-resources"), ("iot", "describe-endpoint"), ("s3api", "delete-objects"),
        ("s3control", "get-public-access-block"), ("ec2", "describe-security-groups"), ("cognito-identity", "list-identity-pools"),
        ("apigateway", "get-rest-apis"), ("apigatewayv2", "get-apis"), ("iot-data", "get-thing-shadow"), ("iot-data", "delete-connection"),
        ("iot", "list-targets-for-policy"), ("iot", "list-authorizers"), ("iot", "list-domain-configurations"), ("lambda", "invoke")}
    tail = ["--generate-cli-skeleton", "output", "--region", REGION, "--endpoint-url", TW.OFFLINE_ENDPOINT, "--no-cli-pager"]

    def call_of(e: Dict[str, Any]) -> Tuple[str, ...]:
        return tuple(e["argv"][:e["argv"].index("--generate-cli-skeleton")])

    # one read goes through a region of its own (the account's Block Public Access, a second time): it keeps that region, as when it
    # is sent, and gets no second one; every other call is read under the twin's
    own = [e for e in skeleton if "--region" in call_of(e)]
    assert {call_of(e) for e in own} == {("s3control", "get-public-access-block", "--account-id", ACCOUNT, "--region", j("us-", "east-1"))}
    assert all(e["argv"][len(call_of(e)):] == tail[:2] + tail[4:] for e in own)
    assert all(e["argv"][-len(tail):] == tail for e in skeleton if e not in own)
    # but for the calls that take an output file: the CLI knows no skeleton for those, and the plan says how many
    no_skeleton = {c for c in planned if c[:2] in TW.SKELETON_UNSUPPORTED}
    assert {c[:2] for c in no_skeleton} == {("lambda", "invoke"), ("iot-data", "delete-thing-shadow"), ("iot-data", "get-thing-shadow")}
    assert len(no_skeleton) == 7                                    # the table's two invokes and the trip's, two shadows deleted, two read
    assert {call_of(e) for e in skeleton} == planned - no_skeleton and len(planned) > 100
    sample = len({tuple(e["argv"]) for e in skeleton if e["env"] is None})
    assert sample > 5 and ("Of %d distinct call(s) the CLI read %d offline; for %d of them its own sample reply then failed its own "
                           "validation, so only the options' names, the required options and each value's form were read and the model's "
                           "validation of the call's own arguments never ran; 7 take an output file and know no skeleton"
                           % (len(planned), len(planned) - 7, sample)) in ran.out
    # ... and plan NAMES those calls, by service and operation and no value, on a line before its summary and in plan.json
    named = sorted({"%s %s" % tuple(e["argv"][:2]) for e in skeleton if e["env"] is None})
    line = "  read by option names and value forms only (service and operation, no value): %s" % ", ".join(named)
    assert len(named) == 5 and line in ran.out.split("\n") and ran.out.index(line) < ran.out.index("plan: ")
    assert json.loads((rig.render / "plan.json").read_text(encoding="utf-8"))["read_names_and_forms_only"] == named
    assert "0 gap(s) in the operator role's policy" in ran.out
    assert "Nothing was executed" in ran.out and "provisional (certificate)" in ran.out and "0 refused by the CLI" in ran.out
    assert json.loads((rig.render / "plan.json").read_text(encoding="utf-8"))["validated_by_the_cli"] is True


HEAD = "aws: [ERROR]: An error occurred (ParamValidation): Parameter validation failed:\n"
THING_CALL = TW.W("iot", "create-thing", "--thing-name", THING)
SHORT_PREFIX = j("exam", "plzz")                # 8 characters: the shortest prefix the driver takes
WORKGROUP_CALL = TW.R("athena", "get-work-group", "--work-group", SHORT_PREFIX + "-twin")
ALARMS_CALL = TW.R("cloudwatch", "describe-alarms", "--alarm-names", "abc", "de")
GROUP_CALL = TW.W("logs", "create-log-group", "--log-group-name", "g", "--tags", "k=v")
# what CLI 2.35.1 said, offline, of its own sample reply to `athena get-work-group` (WP6-verify-2, w06): the second line's
# member begins with the word the option --work-group reads as, and its value is the length of a workgroup's name under a
# prefix of 8 characters
WORKGROUP_SAMPLE = "\n".join((
    "Invalid value for parameter WorkGroup.Configuration.BytesScannedCutoffPerQuery, value: 0, valid min value: 10000000",
    "Invalid length for parameter WorkGroup.Configuration.ExecutionRole, value: 13, valid min length: 20",
    "Invalid value for parameter WorkGroup.Configuration.EngineConfiguration.CoordinatorDpuSize, value: 0, valid min value: 1",
    "Invalid value for parameter WorkGroup.Configuration.EngineConfiguration.MaxConcurrentDpus, value: 0, valid min value: 2",
    "Invalid value for parameter WorkGroup.Configuration.EngineConfiguration.DefaultExecutorDpuSize, value: 0, valid min value: 1"))
FUNCTION_CALL = TW.W("lambda", "create-function", "--function-name", "f", "--timeout", "30", "--memory-size", "128", "--environment", "file:///x.json")
# the five calls whose documents are given by file, each with the words CLI 2.35.1 said offline of a document with a member
# missing or misspelt (wp8-item1's probe): the CLI's refusal of that document, never the sample reply's
TAGGING_CALL = TW.W("s3api", "put-bucket-tagging", "--bucket", "b", "--tagging", "file:///t.json")
RULE_CALL = TW.W("iot", "create-topic-rule", "--rule-name", "r", "--topic-rule-payload", "file:///p.json")
DATABASE_CALL = TW.W("glue", "create-database", "--database-input", "file:///d.json")
TABLE_CALL = TW.W("glue", "create-table", "--database-name", "d", "--table-input", "file:///t.json")
METRIC_ALARM_CALL = TW.W("cloudwatch", "put-metric-alarm", "--alarm-name", "a", "--dimensions", "file:///x.json")
FLAG_CALL = TW.W("iot", "create-certificate-from-csr", "--no-set-as-active")


@pytest.mark.parametrize("call,says,sample", [
    # the call's own: an argument that is missing, unknown, of the wrong type, or a file that is not there
    (THING_CALL, "aws: [ERROR]: An error occurred (ParamValidation): the following arguments are required: --thing-name", False),
    (THING_CALL, "usage: aws [options] <command>\n\naws: [ERROR]: Unknown options: --thing-nome, x", False),
    (THING_CALL, "aws: [ERROR]: invalid literal for int() with base 10: 'not-a-number'", False),
    (THING_CALL, "aws: [ERROR]: An error occurred (ParamValidation): Error parsing parameter '--policy': Unable to load paramfile", False),
    # under the sample's heading, but about an option this very call gave, with the value it gave: the call's own
    (THING_CALL, HEAD + "Invalid length for parameter thingName, value: %d, valid max length: 8" % len(THING), False),
    (FUNCTION_CALL, HEAD + "Invalid value for parameter Timeout, value: 30, valid max value: 10", False),
    (FUNCTION_CALL, HEAD + "Invalid type for parameter Environment.Variables, value: 1, type: <class 'int'>, valid types: <class 'dict'>", False),
    (FUNCTION_CALL, HEAD + "Invalid type for parameter Environment, value: x, type: <class 'str'>, valid types: <class 'dict'>", False),
    (THING_CALL, HEAD + "Invalid value for parameter X.Y, value: 0, valid min value: 1\nMissing required parameter in input: \"thingName\"", False),
    (THING_CALL, HEAD + "Unknown parameter in input: \"thingNome\", must be one of: thingName", False),
    (THING_CALL, HEAD, False),
    (THING_CALL, HEAD + "something nobody has seen yet", False),
    (THING_CALL, "usage: aws [options]\n" + HEAD + "Invalid value for parameter X.Y, value: 0, valid min value: 1", False),
    # the sample reply's own members with the sample's own values, as CLI 2.35.1 was seen to print them offline: some under
    # the names of options the call gave (Timeout, MemorySize), with values the call did not give
    (FUNCTION_CALL, HEAD + "Invalid value for parameter Timeout, value: 0, valid min value: 1\n"
                           "Invalid value for parameter MemorySize, value: 0, valid min value: 128\n"
                           "Invalid length for parameter RuntimeVersionConfig.RuntimeVersionArn, value: 17, valid min length: 26", True),
    (THING_CALL, HEAD + "Invalid length for parameter Table.ViewDefinition.Definer, value: 7, valid min length: 20\n"
                        "Missing required parameter in Table.Status.Details.RequestedChange: \"Name\"", True),
    (THING_CALL, HEAD + "Invalid length for parameter certificateId, value: 13, valid min length: 64", True),
    (THING_CALL, HEAD + "Invalid length for parameter thingName, value: 9, valid min length: 64", True),
    # a member that is missing or unknown in a document the call gave by file: the call's own refusal, whichever way the option is spelt
    (TAGGING_CALL, HEAD + 'Missing required parameter in Tagging.TagSet[0]: "Value"', False),
    (RULE_CALL, HEAD + 'Unknown parameter in topicRulePayload: "ruleDisabld", must be one of: sql, description, actions, ruleDisabled, '
                       'awsIotSqlVersion, errorAction', False),
    (RULE_CALL, HEAD + 'Missing required parameter in topicRulePayload.actions[0].firehose: "roleArn"', False),
    (DATABASE_CALL, HEAD + 'Missing required parameter in DatabaseInput: "Name"', False),
    (TABLE_CALL, HEAD + 'Unknown parameter in TableInput: "TableTyp", must be one of: Name, Description, Owner, LastAccessTime, '
                        'LastAnalyzedTime, Retention, StorageDescriptor, PartitionKeys, TableType, Parameters', False),
    (METRIC_ALARM_CALL, HEAD + 'Missing required parameter in Dimensions[0]: "Value"', False),
    (METRIC_ALARM_CALL, HEAD + 'Unknown parameter in Dimensions[0]: "Valu", must be one of: Name, Value', False),
    # ... or given as a structure in shorthand, or given with no value at all (the rule the `Invalid` lines have)
    (GROUP_CALL, HEAD + 'Missing required parameter in tags: "Value"', False),
    (FLAG_CALL, HEAD + 'Missing required parameter in NoSetAsActive: "x"', False),
    # the sample reply's own member, of an option the call did not give or gave as plain words: the reply's
    (WORKGROUP_CALL, HEAD + 'Missing required parameter in WorkGroup.Configuration.ResultConfiguration: "OutputLocation"', True),
    (ALARMS_CALL, HEAD + 'Unknown parameter in alarmNames: "x", must be one of: y', True),
    (THING_CALL, HEAD + 'Unknown parameter in Table.Status: "Details", must be one of: State', True),
    # the member is read by its whole path: a path that goes on into a member is not about an option given as plain words
    (WORKGROUP_CALL, HEAD + WORKGROUP_SAMPLE, True),
    (ALARMS_CALL, HEAD + "Invalid length for parameter AlarmNames[0].Label, value: 3, valid min length: 5", True),
    # ... an element of a list the call gave is the call's own, and so is a member of a structure it gave in shorthand
    (WORKGROUP_CALL, HEAD + "Invalid length for parameter WorkGroup, value: 13, valid max length: 8", False),
    (ALARMS_CALL, HEAD + "Invalid length for parameter AlarmNames[1], value: 2, valid min length: 5", False),
    (GROUP_CALL, HEAD + "Invalid length for parameter tags.k, value: 1, valid min length: 5", False),
])
def test_what_the_cli_says_after_reading_a_call_is_told_from_a_refusal_of_its_arguments(call: Any, says: str, sample: bool) -> None:
    assert TW.sample_only(call, says) is sample


def test_plan_fails_when_the_cli_refuses_a_calls_arguments(rig: Rig) -> None:
    rig.edit(lambda a: a.update(skeleton_says={
        "iot create-thing": "aws: [ERROR]: An error occurred (ParamValidation): the following arguments are required: --thing-name",
        "lambda create-function": HEAD + "Invalid value for parameter Timeout, value: 30, valid max value: 10"}))
    ran = rig.run("plan", expect=1)
    assert "iot create-thing: the CLI refuses its arguments:" in ran.err and "lambda create-function: the CLI refuses its arguments:" in ran.err
    assert " 2 refused by the CLI" in ran.out and ran.out.count("REFUSED BY THE CLI") == 2 and rig.log() == [] and not clean(ran.text)


def test_a_sample_reply_that_fails_the_clis_own_validation_is_not_the_calls_refusal(rig: Rig) -> None:
    """What CLI 2.35.1 was seen to say, offline, for calls whose arguments it had read: its sample reply's own members,
    with the sample's own values, some of them under the names of options the call gave (Timeout, MemorySize)."""
    seen = {
        "lambda create-function": HEAD + "Invalid value for parameter Timeout, value: 0, valid min value: 1\n"
                                         "Invalid value for parameter MemorySize, value: 0, valid min value: 128\n"
                                         "Invalid length for parameter RuntimeVersionConfig.RuntimeVersionArn, value: 17, valid min length: 26",
        "glue get-table": HEAD + "Invalid length for parameter Table.ViewDefinition.Definer, value: 7, valid min length: 20\n"
                                 "Missing required parameter in Table.Status.Details.RequestedChange: \"Name\"",
        "iot create-certificate-from-csr": HEAD + "Invalid length for parameter certificateId, value: 13, valid min length: 64",
        "athena get-work-group": HEAD + WORKGROUP_SAMPLE,
    }
    rig.edit(lambda a: a.update(skeleton_says=seen))
    ran = rig.run("plan", expect=0)
    assert "0 refused by the CLI" in ran.out and "REFUSED BY THE CLI" not in ran.out and "the CLI refuses" not in ran.text


def test_plan_is_clean_under_a_prefix_of_eight_characters(tmp_path: Path) -> None:
    """WP6-verify-2's SHOULD 2. A workgroup's name is the prefix and `-twin`: under the shortest prefix the driver takes
    it has 13 characters, the length the CLI's sample reply gives a member whose path begins with `WorkGroup`. The line
    was read as the call's own, and `plan` with the real CLI could never be clean under such a prefix."""
    rig = Rig(tmp_path / "twin")
    rig.extra = {"TWIN_PREFIX": SHORT_PREFIX, "TWIN_THING": SHORT_PREFIX + "-thing"}
    assert len(SHORT_PREFIX) == 8 and len(TW.Names(dict(rig.names(), **rig.extra)).workgroup) == 13
    rig.edit(lambda a: a.update(skeleton_says={"athena get-work-group": HEAD + WORKGROUP_SAMPLE}))
    rig.run("literals", expect=0)
    ran = rig.run("plan", expect=0)
    assert "0 refused by the CLI" in ran.out and "REFUSED BY THE CLI" not in ran.out and "the CLI refuses" not in ran.text
    assert not [v for v in (SHORT_PREFIX,) + IDENTIFIERS[2:] if v in ran.text]


def test_plan_gives_no_call_to_the_cli_when_the_control_call_goes_through(rig: Rig) -> None:
    rig.edit(lambda a: a.update(accept_without_profile=True))
    ran = rig.run("plan", expect=1)
    assert "offline-control" in ran.err and rig.log("skeleton.jsonl") == []
    assert [e["argv"][:2] for e in rig.log()] == [["sts", "get-caller-identity"]] and not rig.log()[0]["w"]


def test_plan_without_the_cli_says_so_and_checks_the_documents_only(rig: Rig) -> None:
    ran = rig.run("plan", "--no-cli", expect=0)
    assert rig.log() == [] and rig.log("skeleton.jsonl") == [] and rig.log("refused.jsonl") == []
    assert "NOT given to the CLI" in ran.out
    assert json.loads((rig.render / "plan.json").read_text(encoding="utf-8"))["validated_by_the_cli"] is False


def test_plans_rendered_list_is_what_the_stub_receives_in_a_real_run(built: Rig) -> None:
    twin = built
    real = twin.writes()
    twin.run("plan", "--no-cli", expect=0)
    assert twin.writes() == real
    steps = twin.plan()
    assert [c for s in steps for c in s["creates"]] == real and len(real) > 40
    assert not [s["id"] for s in steps if s.get("provisional") or s.get("refused")]
    # and nothing else ever reached the account in that run: every other call was a read
    assert not twin.log("unknown.jsonl")
    assert [s["id"] for s in steps if s["kind"] == "owner"] == ["operator-role", "rule-role", "firehose-role", "iot-logging-role", "breaker-role"]


def test_a_step_whose_input_is_not_there_is_refused_by_name_and_the_rest_is_still_rendered(rig: Rig) -> None:
    (rig.inputs / "thresholds.json").unlink()
    (rig.inputs / "breaker.zip").unlink()
    ran = rig.run("plan", "--no-cli", expect=1)
    lines = {line.split()[0]: line for line in ran.out.split("\n") if line.startswith("  ")}
    assert "REFUSED thresholds-missing" in lines["alarms"] and "REFUSED thresholds-missing" in lines["alarm-notice"]
    assert "REFUSED input-missing" in lines["function"] and "`twinctl build-breaker` makes" in lines["function"]
    assert " ok" in lines["bucket"] and " ok" in lines["rule"]
    assert rig.log() == []
    # and `apply` refuses the same steps, before anything is printed for approval
    assert "thresholds-missing" in rig.run("apply", "alarms", expect=1).err
    assert "input-missing" in rig.run("apply", "function", expect=1).err


@pytest.mark.parametrize("change,name", [
    (lambda r: (r.inputs / "derive.py").unlink(), "thresholds-check-unavailable"),
    (lambda r: (r.inputs / "thresholds.json").write_text(json.dumps(dict(thresholds_doc(True), the_double_says="no")), encoding="ascii"),
     "thresholds-check-failed"),
    (lambda r: r.write_names(TWIN_THRESHOLDS=None), "thresholds-unset"),
    (lambda r: r.write_names(TWIN_SHARES=None), "thresholds-design:shares"),
    (lambda r: r.write_names(TWIN_SHARES="0.4,0.4,0.2"), "thresholds-design:shares"),
    (lambda r: r.write_names(TWIN_THRESHOLDS=str(REPO / "sdv" / "cloud" / "thresholds.json")), "thresholds-inside-a-work-tree"),
])
def test_the_thresholds_file_is_refused_by_name(rig: Rig, change: Any, name: str) -> None:
    change(rig)
    ran = rig.run("apply", "alarms", expect=1)
    assert "refused: %s:" % name in ran.err and rig.log() == []
    if name == "thresholds-check-failed":
        assert "check-differs" in ran.err                           # derive.py's own refusal, by its name


@pytest.mark.parametrize("field,value", [("cap_usd", 12.0), ("n_days", 30.4), ("things", 2), ("alarms_priced", 6), ("config_change_s", 30),
                                         ("batch_bytes", 11618), ("share_shadow", 0.41)])
def test_a_design_field_that_is_not_the_decided_value_is_refused(rig: Rig, field: str, value: Any) -> None:
    doc = thresholds_doc(True)
    doc["design"][field] = value
    (rig.inputs / "thresholds.json").write_text(json.dumps(doc), encoding="ascii")
    ran = rig.run("apply", "alarms", expect=1)
    assert "refused: thresholds-design:%s:" % ("shares" if field.startswith("share") else field) in ran.err


def test_the_files_n_is_held_to_the_model_s_month_or_to_the_owners_n_of_the_names_file(rig: Rig) -> None:
    """The owner's N (31 days, the names-file contract) is a value of the names file, as the shares are."""
    doc = thresholds_doc(True)
    doc["design"]["n_days"] = 31.0
    (rig.inputs / "thresholds.json").write_text(json.dumps(doc), encoding="ascii")
    assert "refused: thresholds-design:n_days:" in rig.run("apply", "alarms", expect=1).err
    rig.write_names(TWIN_N_DAYS="31")
    assert "render sha256:" in rig.run("apply", "alarms", expect=3).out
    (rig.inputs / "thresholds.json").write_text(json.dumps(thresholds_doc(True)), encoding="ascii")
    assert "refused: thresholds-design:n_days:" in rig.run("apply", "alarms", expect=1).err         # the model's month is not the owner's 31
    rig.write_names(TWIN_N_DAYS="thirty-one")
    assert "refused: names-invalid: TWIN_N_DAYS" in rig.run("apply", "alarms", expect=1).err


@pytest.mark.parametrize("key,value", [("Firehose.IncomingBytes", 0), ("IoT.PublishIn.Success", 700.5), ("IoT.RuleAction.Failure", 2),
                                       ("Firehose.IncomingRecords", True), ("Lambda.Errors", None)])
def test_a_threshold_that_is_no_whole_count_is_refused(rig: Rig, key: str, value: Any) -> None:
    doc = thresholds_doc(True)
    doc["thresholds"][key] = value
    (rig.inputs / "thresholds.json").write_text(json.dumps(doc), encoding="ascii")
    assert "refused: thresholds-value:%s:" % key in rig.run("apply", "alarms", expect=1).err


# ================================================================================================= the rendered documents

@pytest.fixture(scope="module")
def planned(tmp_path_factory: pytest.TempPathFactory, built: Rig) -> Rig:
    """The built twin's renders, with the certificate known: every document as it is applied."""
    twin = built.copy(tmp_path_factory.mktemp("planned") / "twin")
    twin.run("plan", "--no-cli", expect=0)
    return twin


def statements(doc: Any) -> Dict[str, Any]:
    assert doc["Version"] == "2012-10-17"
    out = {st["Sid"]: st for st in doc["Statement"]}
    assert len(out) == len(doc["Statement"])
    return out


def listed(x: Any) -> List[Any]:
    return x if isinstance(x, list) else [x]


def iot_arn(kind: str, name: str) -> str:
    return "arn:aws:iot:%s:%s:%s/%s" % (REGION, ACCOUNT, kind, name)


def test_the_device_policy_has_exactly_the_topics_of_topics_py_and_no_wildcard(planned: Rig) -> None:
    doc = planned.doc("policy", "device-policy")
    st = statements(doc)
    t = TOPICS.Topics(THING, PREFIX + "_telemetry")
    assert set(st) == {"ConnectAsTheThing", "Publish", "Subscribe", "Receive"}
    assert st["ConnectAsTheThing"]["Action"] == "iot:Connect" and st["ConnectAsTheThing"]["Resource"] == iot_arn("client", t.client_id)
    assert st["ConnectAsTheThing"]["Condition"] == {"Bool": {"iot:Connection.Thing.IsAttached": "true"}}
    assert st["Publish"]["Action"] == "iot:Publish" and sorted(st["Publish"]["Resource"]) == sorted(iot_arn("topic", x) for x in t.publish)
    assert st["Subscribe"]["Action"] == "iot:Subscribe"
    assert sorted(st["Subscribe"]["Resource"]) == sorted(iot_arn("topicfilter", x) for x in t.subscribe)
    assert st["Receive"]["Action"] == "iot:Receive" and sorted(st["Receive"]["Resource"]) == sorted(iot_arn("topic", x) for x in t.subscribe)
    text = json.dumps(doc)
    assert "*" not in text and "?" not in text and "+" not in text and "#" not in text
    assert "Delete" not in text and "/get/accepted" in text and "vss/get" not in text and all(s["Effect"] == "Allow" for s in st.values())


def test_each_service_roles_policy_has_exactly_its_actions_each_on_its_one_resource(planned: Rig) -> None:
    bucket = "arn:aws:s3:::%s-telemetry-%s" % (PREFIX, SUFFIX)
    logs = "arn:aws:logs:%s:%s:log-group:" % (REGION, ACCOUNT)
    want = {
        "rule-role": {"PutToTheStream": (["firehose:PutRecord"], ["arn:aws:firehose:%s:%s:deliverystream/%s-telemetry" % (REGION, ACCOUNT, PREFIX)])},
        "firehose-role": {
            "Bucket": (["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"], [bucket]),
            "Objects": (["s3:AbortMultipartUpload", "s3:GetObject", "s3:PutObject"], [bucket + "/errors/*", bucket + "/telemetry/*"]),
            "ErrorLog": (["logs:PutLogEvents"], [logs + PREFIX + "-firehose-errors:log-stream:delivery"])},
        "iot-logging-role": {"Logs": (["logs:CreateLogStream", "logs:PutLogEvents"], [logs + "AWSIotLogsV2:log-stream:*"])},
        # gap t's list: no ListAttachedPolicies (it has no resource type), and the log resource ends in a stream wildcard
        "breaker-role": {
            "Certificate": (["iot:DescribeCertificate", "iot:DetachPolicy", "iot:UpdateCertificate"], [iot_arn("cert", CERT_1)]),
            "Rule": (["iot:DisableTopicRule", "iot:GetTopicRule"], [iot_arn("rule", PREFIX + "_telemetry")]),
            "Connection": (["iot:DeleteConnection"], [iot_arn("client", THING)]),
            "PolicyTargets": (["iot:ListTargetsForPolicy"], [iot_arn("policy", PREFIX + "-device")]),
            "Logs": (["logs:CreateLogStream", "logs:PutLogEvents"], [logs + "/aws/lambda/" + PREFIX + "-breaker:log-stream:*"])},
    }
    for step, expected in want.items():
        st = statements(planned.doc(step, step + "-policy"))
        got = {sid: (sorted(listed(s["Action"])), sorted(listed(s["Resource"]))) for sid, s in st.items()}
        assert got == expected, step
        assert all(s["Effect"] == "Allow" and set(s) == {"Sid", "Effect", "Action", "Resource"} for s in st.values()), step
    breaker = json.dumps(planned.doc("breaker-role", "breaker-role-policy"))
    for never in ("ListAttachedPolicies", "Enable", "AttachPolicy", "ACTIVE", "CreateLogGroup"):
        assert never not in breaker, never                           # it cannot undo itself


def test_each_trust_policy_names_one_service_and_this_account_or_the_account_alone(planned: Rig) -> None:
    services = {"rule-role": "iot.amazonaws.com", "firehose-role": "firehose.amazonaws.com", "iot-logging-role": "iot.amazonaws.com",
                "breaker-role": "lambda.amazonaws.com"}
    for step, service in services.items():
        st, = planned.doc(step, step + "-trust")["Statement"]
        assert st["Principal"] == {"Service": service} and st["Action"] == "sts:AssumeRole" and st["Effect"] == "Allow", step
        assert st["Condition"]["StringEquals"] == {"aws:SourceAccount": ACCOUNT}, step
    rule = planned.doc("rule-role", "rule-role-trust")["Statement"][0]
    assert rule["Condition"]["ArnLike"] == {"aws:SourceArn": iot_arn("rule", PREFIX + "_telemetry")}
    st, = planned.doc("operator-role", "operator-role-trust")["Statement"]
    assert st["Principal"] == {"AWS": "arn:aws:iam::%s:root" % ACCOUNT} and st["Condition"] == {"Bool": {"aws:MultiFactorAuthPresent": "true"}}


def test_the_operator_roles_policy_has_exactly_a1_row_3s_statements(planned: Rig) -> None:
    doc = planned.doc("operator-role", "operator-role-policy")
    st = statements(doc)
    iot = "arn:aws:iot:%s:%s:" % (REGION, ACCOUNT)
    assert list(st) == [
        "NoResourceType", "Things", "Certificates", "Rules", "Policies", "Clients", "Bucket", "AthenaResults", "LogGroups", "Stream", "Glue",
        "Workgroup", "Function", "FunctionInvokedByAlarmsOnly", "Topic", "TopicSubscribedByEmailOnly", "Alarms", "PassTheRuleRole",
        "PassTheFirehoseRole", "PassTheIotLoggingRole", "PassTheBreakerRole", "ReadTheRoles", "ApiListings", "DenyPublicPaths",
        "DenySubscriptionsThatAreNotEmail", "DenyInvokeGrantsToAnyoneButTheAlarms"]
    # the actions that have no resource type, on *, one by one; the plan's eleven of the IoT service are all there
    none = st["NoResourceType"]
    assert none["Resource"] == "*" and not [a for a in none["Action"] if "*" in a]
    for action in ("CreateCertificateFromCsr", "ListAttachedPolicies", "GetV2LoggingOptions", "SetV2LoggingOptions", "DescribeEndpoint",
                   "ListThings", "ListCertificates", "ListPolicies", "ListTopicRules", "ListAuthorizers", "ListDomainConfigurations"):
        assert "iot:" + action in none["Action"], action
    assert sorted(a for a in none["Action"] if not a.startswith("iot:")) == sorted([
        "s3:ListAllMyBuckets", "s3:GetAccountPublicAccessBlock", "logs:DescribeLogGroups", "firehose:ListDeliveryStreams", "glue:GetDatabases",
        "athena:ListWorkGroups", "lambda:ListFunctions", "sns:ListTopics", "cloudwatch:DescribeAlarms", "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics", "tag:GetResources", "ec2:DescribeSecurityGroups", "cognito-identity:ListIdentityPools"])
    # certificate actions on cert/*: an id no name prefix matches
    assert st["Certificates"]["Resource"] == iot + "cert/*"
    assert sorted(st["Certificates"]["Action"]) == sorted([
        "iot:UpdateCertificate", "iot:AttachPolicy", "iot:DetachPolicy", "iot:AttachThingPrincipal", "iot:DetachThingPrincipal",
        "iot:DescribeCertificate", "iot:DeleteCertificate"])
    # shadows and the v2 principal listing on the twin's things only
    assert st["Things"]["Resource"] == iot + "thing/" + PREFIX + "*"
    for action in ("GetThingShadow", "UpdateThingShadow", "DeleteThingShadow", "ListNamedShadowsForThing", "ListThingPrincipalsV2"):
        assert "iot:" + action in st["Things"]["Action"], action
    assert "cloudwatch:SetAlarmState" in st["Alarms"]["Action"]
    assert st["Alarms"]["Resource"] == "arn:aws:cloudwatch:%s:%s:alarm:%s*" % (REGION, ACCOUNT, PREFIX)
    # PassRole on the four service roles, each to its one service; no other IAM write
    passed = {sid: (s["Resource"], s["Condition"]) for sid, s in st.items() if listed(s["Action"]) == ["iam:PassRole"]}
    assert passed == {
        "PassTheRuleRole": ("arn:aws:iam::%s:role/%s" % (ACCOUNT, ROLES["rule-role"]),
                            {"StringEquals": {"iam:PassedToService": "iot.amazonaws.com"}}),
        "PassTheFirehoseRole": ("arn:aws:iam::%s:role/%s" % (ACCOUNT, ROLES["firehose-role"]),
                                {"StringEquals": {"iam:PassedToService": "firehose.amazonaws.com"}}),
        "PassTheIotLoggingRole": ("arn:aws:iam::%s:role/%s" % (ACCOUNT, ROLES["iot-logging-role"]),
                                  {"StringEquals": {"iam:PassedToService": "iot.amazonaws.com"}}),
        "PassTheBreakerRole": ("arn:aws:iam::%s:role/%s" % (ACCOUNT, ROLES["breaker-role"]),
                               {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}})}
    iam = sorted({a for s in st.values() if s["Effect"] == "Allow" for a in listed(s["Action"]) if a.startswith("iam:")})
    assert iam == ["iam:GetRole", "iam:GetRolePolicy", "iam:PassRole"]
    # PutObject only under athena-results/, Athena only on the twin's workgroup
    put = [sid for sid, s in st.items() if s["Effect"] == "Allow" and "s3:PutObject" in listed(s["Action"])]
    assert put == ["AthenaResults"] and st["AthenaResults"]["Resource"] == "arn:aws:s3:::%s-telemetry-%s/athena-results/*" % (PREFIX, SUFFIX)
    athena = [sid for sid, s in st.items() if any(a.startswith("athena:") and a != "athena:ListWorkGroups" for a in listed(s["Action"]))]
    assert athena == ["Workgroup"] and st["Workgroup"]["Resource"] == "arn:aws:athena:%s:%s:workgroup/%s*" % (REGION, ACCOUNT, PREFIX)
    # the explicit Deny: "not publicly reachable" is denied beforehand
    deny = st["DenyPublicPaths"]
    assert deny["Effect"] == "Deny" and deny["Resource"] == "*" and "Condition" not in deny
    for action in ("lambda:CreateFunctionUrlConfig", "iot:CreateAuthorizer", "iot:CreateDomainConfiguration", "apigateway:POST",
                   "cognito-identity:CreateIdentityPool", "cognito-identity:UpdateIdentityPool", "cognito-identity:SetIdentityPoolRoles",
                   "cognito-idp:*", "ecr-public:*", "s3:PutAccountPublicAccessBlock", "s3:PutBucketAcl", "s3:PutObjectAcl",
                   "iot:CreateTopicRuleDestination"):
        assert action in deny["Action"], action
    # an explicit Deny wins over an Allow of the same document: nothing this policy allows is named by a Deny that has no
    # condition (the first render allowed the exit's Cognito read and denied every Cognito action)
    denied = [d for s in st.values() if s["Effect"] == "Deny" and "Condition" not in s for d in listed(s["Action"])]
    allowed = sorted({a for s in st.values() if s["Effect"] == "Allow" for a in listed(s["Action"])})
    assert not [(a, d) for a in allowed for d in denied if fnmatch.fnmatchcase(a.lower(), d.lower())]
    assert "cognito-identity:*" not in deny["Action"] and "cognito-identity:ListIdentityPools" in none["Action"]
    assert "lambda:GetFunctionConcurrency" in st["Function"]["Action"]
    assert st["DenySubscriptionsThatAreNotEmail"] == {"Sid": "DenySubscriptionsThatAreNotEmail", "Effect": "Deny", "Resource": "*",
                                                      "Action": ["sns:Subscribe"], "Condition": {"StringNotEquals": {"sns:Protocol": "email"}}}
    assert st["DenyInvokeGrantsToAnyoneButTheAlarms"]["Condition"] == {
        "StringNotEquals": {"lambda:Principal": "lambda.alarms.cloudwatch.amazonaws.com"}}
    assert st["FunctionInvokedByAlarmsOnly"]["Action"] == ["lambda:AddPermission"]
    assert "lambda:AddPermission" not in st["Function"]["Action"] and "sns:Subscribe" not in st["Topic"]["Action"]
    # every statement's resources and condition, whole: a resource more, by its exact name, is no wildcard and passes the
    # driver's own rule; a condition less leaves an Allow wider than the plan's
    logs = "arn:aws:logs:%s:%s:log-group:" % (REGION, ACCOUNT)
    glue = "arn:aws:glue:%s:%s:" % (REGION, ACCOUNT)
    function = "arn:aws:lambda:%s:%s:function:%s*" % (REGION, ACCOUNT, PREFIX)
    topic = "arn:aws:sns:%s:%s:%s*" % (REGION, ACCOUNT, PREFIX)
    role = "arn:aws:iam::%s:role/" % ACCOUNT
    alarms_only = {"lambda:Principal": "lambda.alarms.cloudwatch.amazonaws.com"}
    held = {
        "NoResourceType": (["*"], None), "Things": ([iot + "thing/" + PREFIX + "*"], None), "Certificates": ([iot + "cert/*"], None),
        "Rules": ([iot + "rule/" + PREFIX + "*"], None), "Policies": ([iot + "policy/" + PREFIX + "*"], None),
        "Clients": ([iot + "client/" + PREFIX + "*"], None), "Bucket": (["arn:aws:s3:::" + PREFIX + "*"], None),
        "AthenaResults": (["arn:aws:s3:::%s-telemetry-%s/athena-results/*" % (PREFIX, SUFFIX)], None),
        "LogGroups": ([logs + PREFIX + "*", logs + "/aws/lambda/" + PREFIX + "*", logs + "AWSIotLogsV2*"], None),
        "Stream": (["arn:aws:firehose:%s:%s:deliverystream/%s*" % (REGION, ACCOUNT, PREFIX)], None),
        "Glue": ([glue + "catalog", glue + "database/" + PREFIX + "*", glue + "table/" + PREFIX + "*/*",
                  glue + "userDefinedFunction/" + PREFIX + "*/*"], None),
        "Workgroup": (["arn:aws:athena:%s:%s:workgroup/%s*" % (REGION, ACCOUNT, PREFIX)], None),
        "Function": ([function], None), "FunctionInvokedByAlarmsOnly": ([function], {"StringEquals": alarms_only}),
        "Topic": ([topic], None), "TopicSubscribedByEmailOnly": ([topic], {"StringEquals": {"sns:Protocol": "email"}}),
        "Alarms": (["arn:aws:cloudwatch:%s:%s:alarm:%s*" % (REGION, ACCOUNT, PREFIX)], None),
        "PassTheRuleRole": ([role + ROLES["rule-role"]], {"StringEquals": {"iam:PassedToService": "iot.amazonaws.com"}}),
        "PassTheFirehoseRole": ([role + ROLES["firehose-role"]], {"StringEquals": {"iam:PassedToService": "firehose.amazonaws.com"}}),
        "PassTheIotLoggingRole": ([role + ROLES["iot-logging-role"]], {"StringEquals": {"iam:PassedToService": "iot.amazonaws.com"}}),
        "PassTheBreakerRole": ([role + ROLES["breaker-role"]], {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}}),
        "ReadTheRoles": ([role + name for name in ROLES.values()], None),
        "ApiListings": (["arn:aws:apigateway:%s::/restapis" % REGION, "arn:aws:apigateway:%s::/apis" % REGION], None),
        "DenyPublicPaths": (["*"], None), "DenySubscriptionsThatAreNotEmail": (["*"], {"StringNotEquals": {"sns:Protocol": "email"}}),
        "DenyInvokeGrantsToAnyoneButTheAlarms": (["*"], {"StringNotEquals": alarms_only}),
    }
    assert {sid: (sorted(listed(s["Resource"])), s.get("Condition")) for sid, s in st.items()} == {
        sid: (sorted(resources), condition) for sid, (resources, condition) in held.items()}
    assert all(set(s) <= {"Sid", "Effect", "Action", "Resource", "Condition"} for s in st.values())
    # every Allow statement but the first is on resources of the account's own names; and the document fits an inline role policy
    for sid, s in st.items():
        if s["Effect"] == "Allow" and sid != "NoResourceType":
            assert all(r != "*" and (ACCOUNT in r or r.startswith("arn:aws:s3:::" + PREFIX) or r.startswith("arn:aws:apigateway:"))
                       for r in listed(s["Resource"])), sid
    assert len(json.dumps(doc, separators=(",", ":"))) < 10240


def test_the_functions_resource_policy_is_one_statement_per_breaker_alarm(planned: Rig) -> None:
    doc = planned.doc("function-policy", "function-policy")
    st = statements(doc)
    assert sorted(st) == sorted("alarm-" + k for k in BREAKER)
    function = "arn:aws:lambda:%s:%s:function:%s-breaker" % (REGION, ACCOUNT, PREFIX)
    for key in BREAKER:
        s = st["alarm-" + key]
        assert s == {"Sid": "alarm-" + key, "Effect": "Allow", "Principal": {"Service": "lambda.alarms.cloudwatch.amazonaws.com"},
                     "Action": "lambda:InvokeFunction", "Resource": function,
                     "Condition": {"StringEquals": {"AWS:SourceAccount": ACCOUNT},
                                   "ArnLike": {"AWS:SourceArn": "arn:aws:cloudwatch:%s:%s:alarm:%s-%s" % (REGION, ACCOUNT, PREFIX, key)}}}
    assert "*" not in json.dumps(doc)
    # and the calls that make it: one add-permission per alarm, each with one source ARN and the account
    calls = [c for s in planned.plan() if s["id"] == "function-policy" for c in s["creates"]]
    assert len(calls) == 5 and all(c[:2] == ["lambda", "add-permission"] and c.count("--source-arn") == 1
                                   and c[c.index("--source-account") + 1] == ACCOUNT for c in calls)


def test_the_rule_payload_is_one_firehose_action_batch_mode_off_and_disabled(planned: Rig) -> None:
    doc = planned.doc("rule", "rule-payload")
    assert doc["ruleDisabled"] is True and len(doc["actions"]) == 1 and list(doc["actions"][0]) == ["firehose"]
    fh = doc["actions"][0]["firehose"]
    assert fh == {"roleArn": "arn:aws:iam::%s:role/%s" % (ACCOUNT, ROLES["rule-role"]), "deliveryStreamName": PREFIX + "-telemetry",
                  "separator": "\n", "batchMode": False}
    assert doc["sql"] == "SELECT *, topic(1) AS thing, timestamp() AS rx_ms" and "principal" not in doc["sql"].lower()


def test_every_alarm_is_not_breaching_with_gap_qs_dimensions_and_a_threshold_of_the_file(planned: Rig) -> None:
    alarms = {a["Key"]: a for a in planned.doc("alarms", "alarms") + planned.doc("alarm-notice", "alarm-notice")}
    function = "arn:aws:lambda:%s:%s:function:%s-breaker" % (REGION, ACCOUNT, PREFIX)
    topic = "arn:aws:sns:%s:%s:%s-notice" % (REGION, ACCOUNT, PREFIX)
    stream = [{"Name": "DeliveryStreamName", "Value": PREFIX + "-telemetry"}]
    mqtt = [{"Name": "Protocol", "Value": "MQTT"}]
    want = {
        "bytes": ("AWS/Firehose", "IncomingBytes", stream, THRESHOLDS["Firehose.IncomingBytes"], [function, topic]),
        "records": ("AWS/Firehose", "IncomingRecords", stream, THRESHOLDS["Firehose.IncomingRecords"], [function, topic]),
        "shadow": ("AWS/IoT", "UpdateThingShadow.Accepted", mqtt, THRESHOLDS["IoT.UpdateThingShadow.Accepted"], [function, topic]),
        "publish": ("AWS/IoT", "PublishIn.Success", mqtt, THRESHOLDS["IoT.PublishIn.Success"], [function, topic]),
        "failure": ("AWS/IoT", "Failure", [{"Name": "RuleName", "Value": PREFIX + "_telemetry"}, {"Name": "ActionType", "Value": "Firehose"}],
                    1, [function, topic]),
        "errors": ("AWS/Lambda", "Errors", [{"Name": "FunctionName", "Value": PREFIX + "-breaker"}], 1, [topic]),
    }
    assert set(alarms) == set(want)
    for key, (namespace, metric, dims, threshold, actions) in want.items():
        a = alarms[key]
        assert (a["Namespace"], a["MetricName"], a["Dimensions"], a["Threshold"], a["AlarmActions"]) == (namespace, metric, dims, threshold, actions)
        assert a["TreatMissingData"] == "notBreaching" and a["Statistic"] == "Sum" and a["Period"] == 300 and a["EvaluationPeriods"] == 1
        assert a["DatapointsToAlarm"] == 1 and a["ComparisonOperator"] == "GreaterThanOrEqualToThreshold" and a["ActionsEnabled"] is True
        assert a["AlarmName"] == "%s-%s" % (PREFIX, key)
    # and the calls carry what the documents say
    calls = {c[c.index("--alarm-name") + 1]: c for s in planned.plan() if s["id"] in ("alarms", "alarm-notice") for c in s["creates"]}
    for a in alarms.values():
        c = calls[a["AlarmName"]]
        assert c[c.index("--treat-missing-data") + 1] == "notBreaching" and c[c.index("--threshold") + 1] == str(a["Threshold"])
        assert c[c.index("--period") + 1] == "300" and c[c.index("--statistic") + 1] == "Sum" and "--actions-enabled" in c
        dims_file = c[c.index("--dimensions") + 1]
        assert dims_file.startswith("file://") and json.loads(Path(dims_file[len("file://"):]).read_text(encoding="ascii")) == a["Dimensions"]


def test_without_the_notice_topic_there_are_five_alarms_that_target_the_function_alone(tmp_path: Path) -> None:
    rig = Rig(tmp_path / "twin", notice=False)
    rig.run("literals", expect=0)
    rig.run("plan", "--no-cli", expect=0)
    ids = [s["id"] for s in rig.plan()]
    assert "alarms" in ids and not [i for i in ids if i.startswith("notice") or i == "alarm-notice"]
    assert not [c for s in rig.plan() for c in s["creates"] if c[0] == "sns"]
    function = "arn:aws:lambda:%s:%s:function:%s-breaker" % (REGION, ACCOUNT, PREFIX)
    assert [a["AlarmActions"] for a in rig.doc("alarms", "alarms")] == [[function]] * 5
    # the alarm count the thresholds file priced has to be the one that is made
    (rig.inputs / "thresholds.json").write_text(json.dumps(thresholds_doc(True)), encoding="ascii")
    assert "thresholds-design:alarms_priced" in rig.run("apply", "alarms", expect=1).err


def test_the_bucket_policy_has_its_two_deny_statements_and_the_bucket_its_design_values(planned: Rig) -> None:
    bucket = "arn:aws:s3:::%s-telemetry-%s" % (PREFIX, SUFFIX)
    st = statements(planned.doc("bucket", "bucket-policy"))
    assert st == {
        "DenyRequestsWithoutTls": {"Sid": "DenyRequestsWithoutTls", "Effect": "Deny", "Principal": "*", "Action": "s3:*",
                                   "Resource": [bucket, bucket + "/*"], "Condition": {"Bool": {"aws:SecureTransport": "false"}}},
        "DenyPutOutsideTheThreePrefixes": {"Sid": "DenyPutOutsideTheThreePrefixes", "Effect": "Deny", "Principal": "*", "Action": "s3:PutObject",
                                           "NotResource": [bucket + "/telemetry/*", bucket + "/errors/*", bucket + "/athena-results/*"]}}
    assert planned.doc("bucket", "bucket-public-access-block") == {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True,
                                                                  "RestrictPublicBuckets": True}
    rules = {r["Filter"]["Prefix"]: r for r in planned.doc("bucket", "bucket-lifecycle")["Rules"]}
    assert {p: r.get("Expiration", {}).get("Days") for p, r in rules.items()} == {"telemetry/": 90, "errors/": 30, "athena-results/": 7, "": None}
    assert rules[""]["AbortIncompleteMultipartUpload"] == {"DaysAfterInitiation": 1}
    assert planned.doc("bucket", "bucket-encryption")["Rules"][0]["ApplyServerSideEncryptionByDefault"] == {"SSEAlgorithm": "AES256"}
    create = [c for s in planned.plan() if s["id"] == "bucket" for c in s["creates"]][0]
    assert create[:2] == ["s3api", "create-bucket"] and create[create.index("--object-ownership") + 1] == "BucketOwnerEnforced"
    dest = planned.doc("stream", "stream-destination")
    assert dest["BufferingHints"] == {"SizeInMBs": 5, "IntervalInSeconds": 300} and dest["CompressionFormat"] == "UNCOMPRESSED"
    assert planned.doc("workgroup", "workgroup-configuration")["BytesScannedCutoffPerQuery"] == 100000000
    table = planned.doc("glue", "glue-table")
    assert table["StorageDescriptor"]["Location"] == "s3://%s-telemetry-%s/telemetry/" % (PREFIX, SUFFIX)
    assert table["Parameters"]["storage.location.template"] == "s3://%s-telemetry-%s/telemetry/dt=${dt}/" % (PREFIX, SUFFIX)
    assert planned.doc("glue", "glue-database")["Name"] == PREFIX + "_twin" and table["Name"] == "telemetry"
    st, = planned.doc("notice-topic", "topic-policy")["Statement"]
    assert st["Principal"] == {"Service": "cloudwatch.amazonaws.com"} and st["Condition"] == {"StringEquals": {"aws:SourceAccount": ACCOUNT}}


def test_every_template_is_rendered_and_no_placeholder_or_local_path_is_left(planned: Rig) -> None:
    rendered = {p.stem for p in planned.render.rglob("*.json") if p.parent != planned.render and p.parent.name != "offline"}
    templates = {p.stem for p in TEMPLATES.glob("*.json")}
    # row 19's two wait for A4's readings and the rehearsal's shadow for the rehearsal: each has a test of its own below; and
    # Phase 6's wait for TWIN_ECR and TWIN_PULL_ROLE, the operator policy's two fragments among them (merged into its document,
    # never a document of their own): the tests of Phase 6 WP4 render them
    assert templates - rendered == {"alarm-rule-count", "function-policy-rule-count", "shadow-rehearsal", "repository-encryption",
                                    "repository-tags", "repository-lifecycle", "pull-role-trust", "pull-role-policy", "pull-policy",
                                    "operator-role-policy-ecr", "operator-role-policy-pull"}
    documents = [p for p in planned.render.rglob("*.json") if p.parent != planned.render and p.parent.name != "offline"]
    assert len(documents) >= 42
    for p in documents:
        text = p.read_text(encoding="ascii")
        assert "@@" not in text and "\r" not in text and text.endswith("\n") and json.loads(text) is not None, p.name
        assert str(planned.base) not in text and planned.base.as_posix() not in text and "file://" not in text, p.name
    for p in TEMPLATES.glob("*.json"):
        raw = p.read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n") and json.loads(raw.decode("ascii")) is not None, p.name
        assert not re.search(rb"[0-9]{12}|\.iot\.[a-z0-9-]+\.amazonaws|cert/[0-9a-f]", raw), p.name       # no account, no endpoint, no certificate


def test_row_19_is_a_step_once_its_readings_are_in_the_names_file(twin: Rig) -> None:
    assert not [s["id"] for s in twin.plan() if "rule-count" in s["id"]]
    twin.write_names(TWIN_RULE_COUNT_METRIC="RulesExecuted")
    assert "refused: input-unset:" in twin.run("apply", "rule-count-alarm", expect=1).err              # all three, or it is no render
    readings = {"TWIN_RULE_COUNT_METRIC": "RulesExecuted", "TWIN_RULE_COUNT_DIMENSIONS": "RuleName=%s_telemetry" % PREFIX,
                "TWIN_RULE_COUNT_READING": "per_execution"}
    twin.write_names(**readings)
    twin.run("plan", "--no-cli", expect=0)
    assert [s["id"] for s in twin.plan()][-2:] == ["rule-count-alarm", "alarm-test-rule-count"]
    alarm, = twin.doc("rule-count-alarm", "alarm-rule-count")
    assert (alarm["Namespace"], alarm["MetricName"]) == ("AWS/IoT", "RulesExecuted")
    assert alarm["Threshold"] == THRESHOLDS["IoT.RulesExecuted.per_execution"]
    assert alarm["Dimensions"] == [{"Name": "RuleName", "Value": PREFIX + "_telemetry"}] and alarm["TreatMissingData"] == "notBreaching"
    st, = twin.doc("rule-count-alarm", "function-policy-rule-count")["Statement"]
    assert st["Sid"] == "alarm-rule-count" and st["Condition"]["ArnLike"]["AWS:SourceArn"].endswith(":alarm:%s-rule-count" % PREFIX)
    since = len(twin.log())
    twin.go("apply", "rule-count-alarm")
    assert [c[:2] for c in twin.writes(since)] == [["cloudwatch", "put-metric-alarm"], ["lambda", "add-permission"]]
    assert len(twin.account()["functions"][PREFIX + "-breaker"]["statements"]) == 6
    # the sixth alarm is a breaker alarm from then on: its test trips, and a restore waits for it like for the others
    twin.go("apply", "alarm-test-rule-count")
    assert twin.account()["certs"][CERT_1]["status"] == "INACTIVE" and twin.account()["alarm_invokes"] == 6
    ran = twin.run("status", expect=0)
    assert re.search(r"alarm rule-count +OK; actions enabled; targets: the function, the notice topic", ran.out)
    assert "as rendered" in [line for line in ran.out.split("\n") if line.split()[:1] == ["function-policy"]][0]
    twin.edit(lambda a: a["alarms"]["%s-rule-count" % PREFIX].update(StateValue="ALARM"))
    assert "of 6 breaker alarm(s)" in twin.run("restore", expect=1).err
    # the other reading of the count takes the other figure of the file; and the teardown takes its statement back
    twin.write_names(**dict(readings, TWIN_RULE_COUNT_READING="per_5kb_unit"))
    twin.run("plan", "--no-cli", expect=0)
    assert twin.doc("rule-count-alarm", "alarm-rule-count")[0]["Threshold"] == THRESHOLDS["IoT.RulesExecuted.per_5kb_unit"]
    twin.write_names(**readings)
    twin.go("teardown", "rule-count-alarm")
    assert len(twin.account()["functions"][PREFIX + "-breaker"]["statements"]) == 5 and "%s-rule-count" % PREFIX not in twin.account()["alarms"]


def tampered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, change: Any) -> None:
    """The templates, copied, with one of them changed."""
    copy = tmp_path / "templates"
    shutil.copytree(str(TEMPLATES), str(copy))
    doc = json.loads((copy / (name + ".json")).read_text(encoding="ascii"))
    change(doc)
    (copy / (name + ".json")).write_text(json.dumps(doc, indent=2) + "\n", encoding="ascii")
    monkeypatch.setattr(TW, "TEMPLATES", copy)


def _allow(doc: Any, sid: str) -> Any:
    return [s for s in doc["Statement"] if s["Sid"] == sid][0]


@pytest.mark.parametrize("template,step,change", [
    ("device-policy", "policy", lambda d: _allow(d, "Publish")["Resource"].append("arn:aws:iot:@@REGION@@:@@ACCOUNT@@:topic/$aws/things/*")),
    ("device-policy", "policy", lambda d: _allow(d, "Subscribe").update(Action="iot:*")),
    ("device-policy", "policy", lambda d: _allow(d, "Publish")["Resource"].append(
        "arn:aws:iot:@@REGION@@:@@ACCOUNT@@:topic/$aws/things/@@THING@@/shadow/name/vss/get")),
    ("device-policy", "policy", lambda d: _allow(d, "ConnectAsTheThing").pop("Condition")),
    ("rule-role-policy", "rule-role", lambda d: _allow(d, "PutToTheStream").update(Resource="*")),
    ("rule-role-policy", "rule-role", lambda d: _allow(d, "PutToTheStream").update(Action=["firehose:PutRecord", "firehose:PutRecordBatch"])),
    ("firehose-role-policy", "firehose-role", lambda d: _allow(d, "Objects").update(Resource="@@BUCKET_ARN@@/*")),
    ("breaker-role-policy", "breaker-role", lambda d: _allow(d, "Certificate")["Action"].append("iot:ListAttachedPolicies")),
    ("breaker-role-policy", "breaker-role", lambda d: _allow(d, "Certificate").update(Resource="arn:aws:iot:@@REGION@@:@@ACCOUNT@@:cert/*")),
    ("breaker-role-policy", "breaker-role", lambda d: _allow(d, "Logs").update(Resource="*")),
    ("breaker-role-policy", "breaker-role", lambda d: _allow(d, "Rule").update(Action="iot:?etTopicRule")),
    ("operator-role-policy", "operator-role", lambda d: _allow(d, "Things").update(Resource="arn:aws:iot:@@REGION@@:@@ACCOUNT@@:thing/*")),
    ("operator-role-policy", "operator-role", lambda d: _allow(d, "NoResourceType")["Action"].append("iam:CreateRole")),
    ("operator-role-policy", "operator-role", lambda d: _allow(d, "Function")["Action"].append("lambda:*")),
    ("operator-role-policy", "operator-role", lambda d: d["Statement"].remove(_allow(d, "DenyPublicPaths"))),
    ("operator-role-policy", "operator-role", lambda d: _allow(d, "PassTheRuleRole").update(Resource="arn:aws:iam::@@ACCOUNT@@:role/*")),
    # WP8 (K1): the function resource the database's delete needs, wider than the prefix
    ("operator-role-policy", "operator-role", lambda d: _allow(d, "Glue")["Resource"].append(
        "arn:aws:glue:@@REGION@@:@@ACCOUNT@@:userDefinedFunction/*")),
    ("operator-role-trust", "operator-role", lambda d: d["Statement"][0].update(Principal={"AWS": "*"})),
    ("rule-role-trust", "rule-role", lambda d: d["Statement"][0]["Condition"].pop("StringEquals")),
    ("breaker-role-trust", "breaker-role", lambda d: d["Statement"][0].update(Principal={"Service": ["lambda.amazonaws.com", "iot.amazonaws.com"]})),
    ("rule-payload", "rule", lambda d: d["actions"][0]["firehose"].update(batchMode=True)),
    ("rule-payload", "rule", lambda d: d.update(ruleDisabled=False)),
    ("rule-payload", "rule", lambda d: d["actions"].append({"http": {"url": "https://example.com/"}})),
    ("rule-payload", "rule", lambda d: d.update(sql="SELECT *, principal() AS who, topic(1) AS thing")),
    ("alarms", "alarms", lambda d: d[2].update(TreatMissingData="breaching")),
    ("alarms", "alarms", lambda d: d[0].update(Threshold=5)),
    ("alarms", "alarms", lambda d: d[3]["Dimensions"].append({"Name": "ThingName", "Value": "@@THING@@"})),
    ("alarms", "alarms", lambda d: d[1].update(AlarmActions=[])),
    ("alarms", "alarms", lambda d: d.pop()),
    ("bucket-policy", "bucket", lambda d: d["Statement"].pop()),
    ("bucket-policy", "bucket", lambda d: d["Statement"].append({"Sid": "Open", "Effect": "Allow", "Principal": "*", "Action": "s3:GetObject",
                                                                  "Resource": "@@BUCKET_ARN@@/*"})),
    ("bucket-public-access-block", "bucket", lambda d: d.update(RestrictPublicBuckets=False)),
    ("bucket-lifecycle", "bucket", lambda d: d["Rules"][0]["Expiration"].update(Days=3650)),
    ("function-policy", "function-policy", lambda d: d["Statement"][0]["Condition"]["ArnLike"].update({"AWS:SourceArn": "@@ALARM_RECORDS_ARN@@"})),
    ("function-policy", "function-policy", lambda d: d["Statement"][0].update(Principal="*")),
    ("function-policy", "function-policy", lambda d: d["Statement"][0]["Condition"].pop("StringEquals")),
    ("topic-policy", "notice-topic", lambda d: d["Statement"][0].update(Principal={"AWS": "*"})),
    ("workgroup-configuration", "workgroup", lambda d: d.update(EnforceWorkGroupConfiguration=False)),
    ("stream-destination", "stream", lambda d: d.update(Prefix="@@THING@@/")),
    ("function-environment", "function", lambda d: d["Variables"].update(TWIN_EXTRA="@@ACCOUNT@@")),
    ("bucket-tagging", "bucket", lambda d: d["TagSet"][0].update(Value="@@NO_SUCH_NAME@@")),
])
def test_a_template_that_gains_a_wildcard_an_action_or_another_value_is_refused(rig: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                                                 template: str, step: str, change: Any) -> None:
    tampered(monkeypatch, tmp_path, template, change)
    ran = rig.run("plan", "--no-cli", expect=1)
    line = [x for x in ran.out.split("\n") if x.split()[:1] == [step]]
    want = "template-placeholder-unknown" if template == "bucket-tagging" else "document-refused:" + template
    assert len(line) == 1 and "REFUSED " + want in line[0], ran.out
    # and nothing of that step is ever printed for approval
    assert "refused: %s:" % want in rig.run("apply", step, expect=1).err and rig.log() == []


# ================================================================================================= apply

def test_apply_prints_and_does_nothing_without_an_approval(rig: Rig) -> None:
    ran = rig.run("apply", "bucket", expect=3)
    assert rig.log() == [] and HASH.search(ran.out) and "6 call(s), 6 document(s)" in ran.out
    assert "aws s3api create-bucket --bucket <prefix>-telemetry-<bucket-suffix>" in ran.out
    assert "file://<render>/bucket/bucket-policy.json" in ran.out and '"Sid": "DenyRequestsWithoutTls"' in ran.out
    assert rig.account()["buckets"] == {} and rig.run("status", expect=0)
    state = json.loads((rig.state / "state.json").read_text(encoding="utf-8"))
    assert "bucket" not in state["steps"]


def test_apply_refuses_an_approval_for_another_step_for_a_changed_render_and_one_never_shown(rig: Rig) -> None:
    bucket = rig.shown("apply", "bucket")
    thing = rig.shown("apply", "thing")
    calls = len(rig.log())
    # another step's approval, in both ways it can be given
    assert "approval-for-another-step" in rig.run("apply", "bucket", "--approve", "thing:" + thing, expect=1).err
    assert "approval-for-another-render" in rig.run("apply", "bucket", "--approve", "bucket:" + thing, expect=1).err
    assert "approval-for-another-step" in rig.run("apply", "bucket", "--approve", bucket, expect=1).err
    # the hash as it was printed, and nothing else: not in another case, not with a blank beside it
    for given in ("bucket:" + bucket.upper(), "bucket: " + bucket, "bucket:" + bucket + " ", " bucket:" + bucket, "bucket:" + bucket[:-1]):
        ran = rig.run("apply", "bucket", "--approve", given, expect=1)
        assert "refused: approval-for-another-" in ran.err, given
    # the render changed since it was shown: a value of the names file that goes into it (the template's turn is the next test)
    alarms = rig.shown("apply", "alarms")
    rig.extra = {"TWIN_FAILURE_ACTION_TYPE": "Lambda"}
    assert "approval-for-another-render" in rig.run("apply", "alarms", "--approve", "alarms:" + alarms, expect=1).err
    rig.extra = {}
    assert len(rig.log()) == calls and rig.account()["buckets"] == {} and rig.account()["alarms"] == {}
    # the right hash, never printed: an approval is for what was shown
    (rig.state / "approvals.jsonl").unlink()
    assert "approval-never-shown" in rig.run("apply", "bucket", "--approve", "bucket:" + bucket, expect=1).err
    assert len(rig.log()) == calls and rig.account()["buckets"] == {}
    # shown again, the same hash goes through
    assert rig.shown("apply", "bucket") == bucket
    rig.run("apply", "bucket", "--approve", "bucket:" + bucket, expect=0)
    assert list(rig.account()["buckets"]) == ["%s-telemetry-%s" % (PREFIX, SUFFIX)]


def test_a_changed_template_changes_the_hash(rig: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    before = rig.shown("apply", "firehose-log")
    assert rig.shown("apply", "firehose-log") == before
    bucket = rig.shown("apply", "bucket")
    tampered(monkeypatch, tmp_path, "bucket-tagging", lambda d: d["TagSet"].append({"Key": "second", "Value": "tag"}))
    assert "approval-for-another-render" in rig.run("apply", "bucket", "--approve", "bucket:" + bucket, expect=1).err
    assert rig.shown("apply", "bucket") != bucket and rig.account()["buckets"] == {}


@pytest.mark.parametrize("identity,name", [
    ({"Arn": j("arn:aws:iam::", ACCOUNT, ":user/example-user"), "UserId": j("AIDA", "EXAMPLEEXAMPLEEX")}, "identity-not-the-operator-role"),
    ({"Arn": j("arn:aws:sts::", ACCOUNT, ":assumed-role/another-role/session")}, "identity-not-the-operator-role"),
    ({"Arn": j("arn:aws:sts::", ACCOUNT, ":assumed-role/", ROLE, "-admin/session")}, "identity-not-the-operator-role"),
    ({"Arn": j("arn:aws:iam::", ACCOUNT, ":role/", ROLE)}, "identity-not-the-operator-role"),
    ({"Arn": j("arn:aws:iam::", ACCOUNT, ":root")}, "identity-not-the-operator-role"),
    ({"Arn": j("arn:aws:sts::", "123456789012", ":assumed-role/", ROLE, "/session"), "Account": "123456789012"}, "identity-other-account"),
])
def test_apply_and_teardown_refuse_a_caller_that_is_not_the_operator_role(rig: Rig, identity: Dict[str, str], name: str) -> None:
    rig.go("apply", "thing")
    rig.edit(lambda a: a.update(identity=dict({"UserId": "x"}, **identity)))
    for mode, step in (("apply", "bucket"), ("teardown", "thing")):
        before = rig.writes()
        ran = rig.go(mode, step, expect=1)
        assert "refused: %s:" % name in ran.err and rig.writes() == before
    assert rig.account()["buckets"] == {} and list(rig.account()["things"]) == [THING]
    assert not clean(rig.said[-1].text)


def test_an_action_with_a_wildcard_is_refused_even_when_the_expected_list_was_widened_to_hold_it(rig: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                               tmp_path: Path) -> None:
    """The two checks on a policy's actions are each other's second line: the exact set, and no wildcard at all."""
    tampered(monkeypatch, tmp_path, "rule-role-policy", lambda d: _allow(d, "PutToTheStream").update(Action="firehose:Put*"))
    monkeypatch.setitem(TW.ALLOWS, "rule-role-policy", ("firehose:Put*",))
    ran = rig.run("apply", "rule-role", expect=1)
    assert "refused: document-refused:rule-role-policy:" in ran.err and "allows an action with a wildcard" in ran.err
    assert rig.log() == []


def stub_runner(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The driver's runner by itself, with the stub as its executable: a test of the runner never names the real CLI."""
    monkeypatch.setenv("TWIN_AWS", str(STUB))
    monkeypatch.setenv("STUB_AWS_DIR", str(rig.stub))
    aws = TW.Aws(TW.Names(dict(rig.names())), rig.state)
    assert aws.exe == [sys.executable, str(STUB)]
    return aws


def test_a_write_is_refused_until_the_identity_was_read(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The last line behind `plan` and behind any command that forgot the check: the runner itself refuses a write."""
    aws = stub_runner(rig, monkeypatch)
    with pytest.raises(TW.TwinError) as e:
        aws.run(TW.W("iot", "create-thing", "--thing-name", "x"))
    assert e.value.name == "not-armed" and rig.log() == [] and rig.account()["things"] == {}


def test_a_create_that_fails_half_way_leaves_a_state_teardown_finishes_from(rig: Rig) -> None:
    rig.edit(lambda a: a["faults"].append({"service": "s3api", "op": "put-bucket-lifecycle-configuration", "code": "InternalError"}))
    ran = rig.go("apply", "bucket", expect=1)
    assert "call 4 of 6 failed (s3api put-bucket-lifecycle-configuration: InternalError)" in ran.err
    name = "%s-telemetry-%s" % (PREFIX, SUFFIX)
    assert list(rig.account()["buckets"]) == [name] and "policy" not in rig.account()["buckets"][name]
    step = json.loads((rig.state / "state.json").read_text(encoding="utf-8"))["steps"]["bucket"]
    assert step["status"] == "partial" and step["done"] == [0, 1, 2]
    # it is ours, half made: not made on top of, and not gone
    assert "half-made" in rig.go("apply", "bucket", expect=1).err
    assert "bucket" in rig.run("verify-gone", expect=1).out and "FOUND" in rig.said[-1].out
    # teardown finishes from that state
    rig.go("teardown", "bucket")
    assert rig.account()["buckets"] == {}
    rig.run("verify-gone", expect=0)
    # and the step can be made again, whole
    rig.go("apply", "bucket")
    assert rig.account()["buckets"][name]["policy"] and "as rendered" in rig.run("status", expect=0).out


def test_a_failure_before_the_first_reply_still_leaves_a_record(rig: Rig) -> None:
    rig.edit(lambda a: a["faults"].append({"service": "iot", "op": "create-thing", "code": "ThrottlingException"}))
    assert "call 1 of 1 failed (iot create-thing: ThrottlingException)" in rig.go("apply", "thing", expect=1).err
    assert json.loads((rig.state / "state.json").read_text(encoding="utf-8"))["steps"]["thing"]["status"] == "partial"
    rig.go("teardown", "thing")
    rig.go("apply", "thing")


def test_apply_refuses_what_exists_and_is_not_ours_and_does_not_touch_it(rig: Rig) -> None:
    name = "%s-telemetry-%s" % (PREFIX, SUFFIX)
    rig.edit(lambda a: a["buckets"].update({name: {"objects": ["theirs"], "ownership": "ObjectWriter"}}))
    ran = rig.go("apply", "bucket", expect=1)
    assert "refused: exists-not-ours:" in ran.err and rig.writes() == []
    assert rig.account()["buckets"][name] == {"objects": ["theirs"], "ownership": "ObjectWriter"}
    # nor is it deleted: the state records nothing made for the step
    assert "refused: not-ours:" in rig.run("teardown", "bucket", expect=1).err and rig.writes() == []
    # a log group of the service's own fixed name that was there before is not adopted either
    rig.edit(lambda a: a["log_groups"].update({"AWSIotLogsV2": {"streams": []}}))
    assert "refused: exists-not-ours:" in rig.go("apply", "iot-log-group", expect=1).err and rig.writes() == []
    # and what appears under a step's name AFTER its teardown was not made here either: not called gone, not deleted, not adopted
    rig.go("apply", "thing")
    rig.go("teardown", "thing")
    made = rig.writes()
    rig.edit(lambda a: a["things"].update({THING: {"shadows": {}, "principals": {}}}))
    ran = rig.run("teardown", "thing", expect=1)
    assert "refused: exists-not-ours:" in ran.err and "recorded as deleted; read, not found" not in ran.text
    assert "refused: exists-not-ours:" in rig.go("apply", "thing", expect=1).err
    assert rig.writes() == made and list(rig.account()["things"]) == [THING]


def test_apply_makes_reads_back_and_records_and_a_second_apply_creates_nothing(rig: Rig) -> None:
    ran = rig.go("apply", "bucket")
    assert "made; read back, as rendered; recorded" in ran.out
    made = rig.writes()
    assert [c[:2] for c in made] == [["s3api", "create-bucket"], ["s3api", "put-public-access-block"], ["s3api", "put-bucket-encryption"],
                                     ["s3api", "put-bucket-lifecycle-configuration"], ["s3api", "put-bucket-policy"],
                                     ["s3api", "put-bucket-tagging"]]
    assert "already made, nothing was created" in rig.go("apply", "bucket").out and rig.writes() == made
    # what is read back and is not the render is said, as states, and the step is not called proven
    name = "%s-telemetry-%s" % (PREFIX, SUFFIX)
    rig.edit(lambda a: a["buckets"][name].update(public=True, block=dict(a["buckets"][name]["block"], BlockPublicAcls=False)))
    ran = rig.go("apply", "bucket", expect=1)
    assert "its Block Public Access is not all four" in ran.err and "its policy status does not say it is not public" in ran.err
    assert rig.writes() == made


def test_a_step_stands_on_the_steps_before_it_and_on_what_the_state_knows(rig: Rig) -> None:
    assert "refused: step-needs:" in rig.go("apply", "stream", expect=1).err
    assert "refused: render-provisional:" in rig.run("apply", "attachments", expect=1).err
    assert "refused: step-unknown:" in rig.run("apply", "no-such-step", expect=1).err
    assert "refused: step-teardown-only:" in rig.run("apply", "bucket-objects", expect=1).err
    assert rig.writes() == []
    (rig.state / "baseline.json").unlink()
    assert "refused: no-baseline:" in rig.go("apply", "bucket", expect=1).err and rig.writes() == []


def test_the_functions_step_is_refused_until_the_artefact_exists(rig: Rig) -> None:
    (rig.inputs / "breaker.zip").unlink()
    ran = rig.run("apply", "function", expect=1)
    assert "refused: input-missing:" in ran.err and "TWIN_BREAKER_ZIP" in ran.err and rig.log() == []
    rig.write_names(TWIN_BREAKER_ZIP=None)
    assert "refused: input-unset:" in rig.run("apply", "function", expect=1).err


def test_an_owner_made_step_is_read_and_never_made(rig: Rig) -> None:
    ran = rig.run("apply", "rule-role", expect=1)
    assert "it is not there yet" in ran.err and '"Sid": "PutToTheStream"' in ran.out and rig.writes() == []
    rig.owner_makes("rule-role")
    assert "read, as rendered; recorded" in rig.run("apply", "rule-role", expect=0).out
    rig.edit(lambda a: a["roles"][ROLES["rule-role"]]["policies"][ROLES["rule-role"] + "-policy"]["Statement"][0].update(Resource="*"))
    assert "its policy is not the render" in rig.run("apply", "rule-role", expect=1).err
    # the breaker's role stands on the certificate: before it exists the render is provisional and is never recorded
    ran = rig.run("apply", "breaker-role", expect=1)
    assert "does not hold yet (certificate)" in ran.out and rig.writes() == []
    assert "refused: step-not-torn-down:" in rig.run("teardown", "rule-role", expect=1).err


def test_the_certificate_is_made_inactive_its_id_becomes_a_literal_and_its_file_goes_where_the_names_say(rig: Rig) -> None:
    ran = rig.go("apply", "certificate")
    account = rig.account()
    assert account["certs"] == {CERT_1: {"status": "INACTIVE", "policies": []}}
    create, = rig.writes()
    assert create[:2] == ["iot", "create-certificate-from-csr"] and "--no-set-as-active" in create and "--set-as-active" not in create
    assert (rig.inputs / "cert.pem").read_text(encoding="ascii").startswith("-----BEGIN ")
    assert CERT_1 in json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))["literals"]["certificate-id"]
    assert not clean(ran.text) and not clean(rig.run("status", expect=0).text)
    # a certificate that comes back ACTIVE is said, and the step is not proven
    rig.edit(lambda a: a["certs"][CERT_1].update(status="ACTIVE"))
    assert "it is ACTIVE before go-live" in rig.go("apply", "certificate", expect=1).err
    # the device directory is no place inside a work tree
    rig.write_names(TWIN_CERTIFICATE_OUT=str(REPO / "sdv" / "cloud" / "cert.pem"))
    assert "refused: inside-a-work-tree:" in rig.run("apply", "certificate", expect=1).err


# ================================================================================================= the whole table, and teardown

def test_the_built_twin_is_what_the_plan_describes_and_nothing_can_carry_traffic_before_go_live(built: Rig) -> None:
    a = built.account()
    assert a["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is False and a["certs"][CERT_1]["status"] == "ACTIVE"
    assert a["certs"][CERT_1]["policies"] == [PREFIX + "-device"]
    assert a["things"][THING]["principals"] == {iot_arn("cert", CERT_1): "EXCLUSIVE_THING"}
    # the order in which the account was changed: the rule and the certificate went live last, after the breaker ran
    made = [c[:2] for c in built.writes()]
    live = made.index(["iot", "enable-topic-rule"])
    assert made[live:] == [["iot", "enable-topic-rule"], ["iot", "update-certificate"]]
    assert made.index(["cloudwatch", "put-metric-alarm"]) < made.index(["lambda", "invoke"], made.index(["lambda", "add-permission"])) < live
    assert made.count(["cloudwatch", "set-alarm-state"]) == 5 and a["alarm_invokes"] == 5 and a["trips"] == 6
    assert made.index(["iot", "attach-policy"], made.index(["cloudwatch", "set-alarm-state"])) < live
    assert a["functions"][PREFIX + "-breaker"]["concurrency"] == 1 and len(a["functions"][PREFIX + "-breaker"]["statements"]) == 5
    assert sorted(a["alarms"]) == sorted("%s-%s" % (PREFIX, k) for k in BREAKER + ("errors",))
    assert a["iot_logging"] == {"roleArn": "arn:aws:iam::%s:role/%s" % (ACCOUNT, ROLES["iot-logging-role"]), "defaultLogLevel": "ERROR",
                                "disableAllLogs": False}
    assert a["log_groups"]["AWSIotLogsV2"]["retention"] == 30 and a["log_groups"]["/aws/lambda/" + PREFIX + "-breaker"]["retention"] == 30
    state = json.loads((built.state / "state.json").read_text(encoding="utf-8"))
    assert {s["status"] for s in state["steps"].values()} == {"created", "verified", "done"}
    assert not built.log("unknown.jsonl")


def test_go_live_is_refused_while_the_breaker_is_not_armed_or_the_policy_is_detached(built: Rig, tmp_path: Path) -> None:
    twin = Rig(tmp_path / "twin").build(until="go-live-rule")
    assert twin.account()["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is True and twin.account()["certs"][CERT_1]["status"] == "INACTIVE"
    alarm = "%s-%s" % (PREFIX, "shadow")
    twin.edit(lambda a: a["alarms"][alarm].update(StateValue="ALARM"))
    assert "refused: precondition:" in twin.go("apply", "go-live-rule", expect=1).err
    twin.edit(lambda a: a["alarms"][alarm].update(StateValue="OK"))
    twin.edit(lambda a: a["certs"][CERT_1].update(policies=[]))
    ran = twin.go("apply", "go-live-rule", expect=1)
    assert "refused: precondition:" in ran.err and "attached" in ran.err
    assert twin.account()["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is True
    # a twin that never was live is sent to no restore, and its two go-live steps read as not live, never as "not found"
    assert ran.err.rstrip().endswith("is attached again first)") and "restore" not in ran.err
    rows = status_lines(twin.run("status"))
    assert rows["go-live-rule"].endswith(TW.NOT_LIVE) and rows["go-live-certificate"].endswith(TW.NOT_LIVE)
    # the policy back, and the certificate attached to the thing in the way that is not exclusive
    twin.edit(lambda a: (a["certs"][CERT_1].update(policies=[PREFIX + "-device"]),
                         a["things"][THING]["principals"].update({iot_arn("cert", CERT_1): "NON_EXCLUSIVE_THING"})))
    ran = twin.go("apply", "go-live-rule", expect=1)
    assert "refused: precondition:" in ran.err and "attached" in ran.err
    assert twin.account()["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is True
    assert "refused: step-needs:" in twin.go("apply", "go-live-certificate", expect=1).err
    assert built.account()["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is False


def teardown_ids(rig: Rig) -> List[str]:
    return [line.split()[0] for line in rig.run("teardown", expect=0).out.split("\n") if line.startswith("  ")]


def test_teardown_is_the_table_in_reverse_and_a_step_is_refused_while_a_later_one_stands(twin: Rig) -> None:
    order = teardown_ids(twin)
    table = [s["id"] for s in twin.plan() if s["kind"] not in ("owner", "action")]
    assert order == list(reversed(table)) and order[0] == "go-live-certificate" and order[-2:] == ["bucket-objects", "bucket"]
    assert order.index("attachments") < order.index("policy") < order.index("certificate") < order.index("shadows") < order.index("thing")
    assert order.index("alarms") < order.index("function-policy") < order.index("function") < order.index("rule") < order.index("stream")
    before = twin.writes()
    for early in ("bucket", "thing", "certificate", "function", "rule", "alarms", "go-live-rule"):
        ran = twin.run("teardown", early, expect=1)
        assert "refused: teardown-order:" in ran.err, early
    assert twin.writes() == before
    # the first step of the reverse order goes; the one after it only then
    twin.go("teardown", "go-live-certificate")
    assert twin.account()["certs"][CERT_1]["status"] == "INACTIVE"
    assert "refused: teardown-order:" in twin.run("teardown", "iot-logging", expect=1).err
    twin.go("teardown", "go-live-rule")
    assert twin.account()["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is True
    twin.go("teardown", "iot-logging")
    assert twin.account()["iot_logging"]["disableAllLogs"] is True


def test_the_whole_teardown_leaves_nothing_and_verify_gone_passes(twin: Rig, built: Rig) -> None:
    # what the device and the stream left behind: two named shadows, and objects in the bucket
    bucket = "%s-telemetry-%s" % (PREFIX, SUFFIX)

    def traffic(a: Dict[str, Any]) -> None:
        a["things"][THING]["shadows"] = {"vss": {"state": {"reported": {}}}, "config": {"state": {"reported": {}}}}
        a["buckets"][bucket]["objects"] = ["telemetry/dt=2026-01-01/a", "telemetry/dt=2026-01-01/b", "errors/x"]
    twin.edit(traffic)
    assert "FOUND" in twin.run("verify-gone", expect=1).out
    # the inputs of the creates are gone since (the signing request is a throwaway, the zip a build's output): nothing that
    # reads or deletes needs them
    (twin.inputs / "device.csr").unlink()
    (twin.inputs / "breaker.zip").unlink()
    lines = {line.split()[0]: line for line in twin.run("status", expect=0).out.split("\n") if line.startswith("  ")}
    assert "as rendered" in lines["certificate"] and "not read" not in lines["function"]
    # the function is held to the hash the state recorded when it was made: with the zip gone it is still compared
    assert "as rendered" in lines["function"] and "the zip is no longer at its path" in lines["function"]
    # the manual stop's order: the exit's reads, a restore's render, the trip and its status, then the table in reverse
    twin.run("exit-checks", "--capture", twin.base / "capture", expect=1)
    twin.run("restore", expect=0)
    twin.run("trip", expect=0)
    since = len(twin.log())
    for step in teardown_ids(twin):
        twin.go("teardown", step)
    deleted = [c[:2] for c in twin.writes(since)]
    assert deleted.index(["iot-data", "delete-thing-shadow"]) < deleted.index(["iot", "delete-thing"])
    assert deleted.index(["s3api", "delete-objects"]) < deleted.index(["s3api", "delete-bucket"]) == len(deleted) - 1
    assert deleted.index(["iot", "detach-policy"]) < deleted.index(["iot", "delete-policy"]) < deleted.index(["iot", "delete-certificate"])
    a, fresh = twin.account(), new_account()
    for table in ("buckets", "log_groups", "streams", "rules", "things", "certs", "policies", "glue", "workgroups", "functions", "topics", "alarms"):
        assert a[table] == fresh[table], table
    assert a["iot_logging"]["disableAllLogs"] is True and set(a["roles"]) == set(ROLES.values())     # the owner removes the roles by hand
    ran = twin.run("verify-gone", expect=0)
    assert "verify-gone: gone" in ran.out and "FOUND" not in ran.out and " 0 resource(s)" in ran.out
    state = json.loads((twin.state / "state.json").read_text(encoding="utf-8"))["steps"]
    assert {s["status"] for k, s in state.items() if k in teardown_ids(twin)} == {"deleted"}
    assert not clean("".join(r.text for r in twin.said))
    # every step again: nothing is sent, nothing fails
    since = len(twin.log())
    for step in teardown_ids(twin):
        if step != "shadows":                                       # no record of its own: its listing is read with the thing's teardown
            assert "nothing was sent" in twin.run("teardown", step, expect=0).out, step
    assert twin.writes(since) == []
    # and of the whole life (the build, the commands above, the teardown, verify-gone) no call is one `plan` does not list:
    # what `plan` gives to the CLI and holds the operator role's policy to is what the commands send
    (twin.inputs / "device.csr").write_text("a test's placeholder, not a signing request\n", encoding="ascii")
    (twin.inputs / "breaker.zip").write_bytes(BREAKER_ZIP)
    twin.run("plan", "--no-cli", expect=0)
    listed_by_plan = {sig(c) for c in every_call(twin)}
    sent = {sig(e["argv"]) for e in twin.log()}
    assert sent - listed_by_plan == set() and len(sent) > 95


def test_the_bucket_is_never_emptied_without_the_approval_of_that_very_step_and_listing(rig: Rig) -> None:
    rig.go("apply", "bucket")
    bucket = "%s-telemetry-%s" % (PREFIX, SUFFIX)
    keys = ["telemetry/dt=2026-01-01/%04d" % i for i in range(1203)]
    rig.edit(lambda a: a["buckets"][bucket].update(objects=list(keys)))
    made = rig.writes()
    # the bucket's own step, approved, deletes no object and no bucket
    ran = rig.go("teardown", "bucket", expect=1)
    assert "refused: precondition:" in ran.err and "1203 object(s)" in ran.err and "bucket-objects" in ran.err
    assert rig.writes() == made and len(rig.account()["buckets"][bucket]["objects"]) == 1203
    # emptying it: printed, with what is listed, and nothing is done
    ran = rig.run("teardown", "bucket-objects", expect=3)
    assert "1203 object(s)" in ran.out and "PERMANENT" in ran.out and rig.writes() == made
    own = HASH.search(ran.out).group(1)                                                              # type: ignore[union-attr]
    # the bucket step's approval is not this step's
    other = rig.shown("teardown", "bucket")
    assert "approval-for-another-step" in rig.run("teardown", "bucket-objects", "--approve", "bucket:" + other, expect=1).err
    assert "approval-for-another-render" in rig.run("teardown", "bucket-objects", "--approve", "bucket-objects:" + other, expect=1).err
    # the listing changed since the yes: the approval is for what was listed then
    rig.edit(lambda a: a["buckets"][bucket]["objects"].append("telemetry/dt=2026-01-02/new"))
    assert "approval-for-another-render" in rig.run("teardown", "bucket-objects", "--approve", "bucket-objects:" + own, expect=1).err
    assert rig.writes() == made and len(rig.account()["buckets"][bucket]["objects"]) == 1204
    # its own approval, for this listing
    ran = rig.go("teardown", "bucket-objects")
    assert "1204 object(s) deleted" in ran.out and rig.account()["buckets"][bucket]["objects"] == []
    assert [c[:2] for c in rig.writes()[len(made):]] == [["s3api", "delete-objects"]] * 2          # 1000, then the rest
    assert not clean(ran.text)
    # empty: nothing to approve, nothing sent; and now the bucket goes
    since = len(rig.writes())
    assert "lists no object" in rig.run("teardown", "bucket-objects", expect=0).out and len(rig.writes()) == since
    rig.go("teardown", "bucket")
    assert rig.account()["buckets"] == {}
    assert "recorded as deleted; nothing was sent" in rig.run("teardown", "bucket-objects", expect=0).out


def test_the_thing_is_not_deleted_while_a_named_shadow_is_listed(rig: Rig) -> None:
    rig.go("apply", "thing")
    rig.edit(lambda a: a["things"][THING].update(shadows={"vss": {"state": {}}, "config": {"state": {}}, "other": {"state": {}}}))
    made = rig.writes()
    ran = rig.go("teardown", "thing", expect=1)
    assert "refused: precondition:" in ran.err and "3 named shadow(s)" in ran.err and rig.writes() == made
    assert list(rig.account()["things"]) == [THING]
    # the shadows' own step deletes the twin's two and says that one more is listed; the thing stays
    ran = rig.go("teardown", "shadows", expect=1)
    assert "still read" in ran.err and list(rig.account()["things"][THING]["shadows"]) == ["other"]
    assert "refused: precondition:" in rig.go("teardown", "thing", expect=1).err and list(rig.account()["things"]) == [THING]
    rig.edit(lambda a: a["things"][THING].update(shadows={}))
    assert "deleted; read back, not found" in rig.go("teardown", "shadows").out
    rig.go("teardown", "thing")
    assert rig.account()["things"] == {}
    assert [c[:2] for c in rig.writes()[len(made):]] == [["iot-data", "delete-thing-shadow"]] * 4 + [["iot", "delete-thing"]]


def test_a_certificate_is_inactive_and_detached_before_it_is_deleted(tmp_path: Path) -> None:
    twin = Rig(tmp_path / "twin").build(until="glue")
    made = twin.writes()
    assert "refused: teardown-order:" in twin.run("teardown", "certificate", expect=1).err
    # the policy first: with the attachments' record out of the way, its own precondition holds it while it has a target
    state = json.loads((twin.state / "state.json").read_text(encoding="utf-8"))
    state["steps"]["attachments"]["status"] = "deleted"
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    ran = twin.go("teardown", "policy", expect=1)
    assert "refused: precondition:" in ran.err and "the policy is still attached to 1 target(s)" in ran.err
    assert twin.writes() == made and list(twin.account()["policies"]) == [PREFIX + "-device"]
    # with the later steps' records out of the way, its own precondition still holds it
    state = json.loads((twin.state / "state.json").read_text(encoding="utf-8"))
    for later in ("policy", "attachments"):
        state["steps"][later]["status"] = "deleted"
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    ran = twin.go("teardown", "certificate", expect=1)
    assert "refused: precondition:" in ran.err and "a policy is still attached" in ran.err
    twin.edit(lambda a: a["certs"][CERT_1].update(policies=[]))
    assert "still attached to the thing" in twin.go("teardown", "certificate", expect=1).err
    twin.edit(lambda a: (a["things"][THING].update(principals={}), a["certs"][CERT_1].update(status="ACTIVE")))
    assert "the certificate is not INACTIVE" in twin.go("teardown", "certificate", expect=1).err
    assert twin.writes() == made and list(twin.account()["certs"]) == [CERT_1]
    twin.edit(lambda a: a["certs"][CERT_1].update(status="INACTIVE"))
    twin.go("teardown", "certificate")
    assert twin.account()["certs"] == {}


def test_a_delete_that_completes_later_is_not_called_gone(tmp_path: Path) -> None:
    twin = Rig(tmp_path / "twin").build(until="rule")
    twin.edit(lambda a: a.update(stream_delete_is_slow=True))
    ran = twin.go("teardown", "stream", expect=1)
    assert "still read" in ran.err and "verify-gone stream" in ran.err
    assert "FOUND" in twin.run("verify-gone", "stream", expect=1).out
    assert "refused: still-deleting:" in twin.go("apply", "stream", expect=1).err
    twin.edit(lambda a: a["streams"].clear())
    assert "not found" in twin.run("verify-gone", "stream", expect=0).out
    # created, deleted, verified gone, created again (rows 3, 4 and 13)
    twin.go("apply", "stream")
    assert list(twin.account()["streams"]) == [PREFIX + "-telemetry"]


def test_a_rule_that_is_answered_as_denied_is_absent_only_when_the_listing_lacks_it(tmp_path: Path) -> None:
    twin = Rig(tmp_path / "twin").build(until="rule")
    twin.edit(lambda a: a.update(rule_missing_is_unauthorized=True))
    twin.go("apply", "rule")
    assert twin.account()["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is True
    twin.go("teardown", "rule")
    assert twin.account()["rules"] == {} and "rule" in twin.run("verify-gone", "rule", expect=0).out
    # the DELETE of a rule that is not there is answered the same way: after a create that failed, the teardown the
    # message names does finish the step
    twin.edit(lambda a: a["faults"].append({"service": "iot", "op": "create-topic-rule", "code": "AccessDeniedException"}))
    ran = twin.go("apply", "rule", expect=1)
    assert "call 1 of 1 failed (iot create-topic-rule: AccessDeniedException)" in ran.err and "`twinctl teardown rule` finishes from it" in ran.err
    assert "deleted; read back, not found; recorded" in twin.go("teardown", "rule").out
    twin.go("apply", "rule")
    # a rule that IS listed and whose delete is denied: a failure, and the rule stands
    twin.edit(lambda a: a["faults"].append({"service": "iot", "op": "delete-topic-rule", "code": "UnauthorizedException"}))
    ran = twin.go("teardown", "rule", expect=1)
    assert "call 1 of 1 failed (iot delete-topic-rule: UnauthorizedException)" in ran.err and list(twin.account()["rules"]) == [PREFIX + "_telemetry"]


@pytest.mark.parametrize("leftover,what", [
    (lambda a: a["log_groups"].update({"somebody-elses-group": {"streams": []}}), "1 name(s) the baseline lacks"),
    (lambda a: a["things"].update({"another-thing": {"shadows": {}, "principals": {}}}), "1 name(s) the baseline lacks"),
    (lambda a: a["certs"].update({hashlib.sha256(b"a certificate nobody recorded").hexdigest(): {"status": "INACTIVE", "policies": []}}),
     "1 name(s) the baseline lacks"),
    (lambda a: a["alarms"].update({"an-alarm": {"AlarmName": "an-alarm", "tags": True}}), "1 tagged"),
    # a tagged resource of a kind none of the driver's listings holds: the tag query alone sees it
    (lambda a: a.update(tagged_only=["arn:aws:sqs:%s:%s:a-queue-nobody-listed" % (REGION, ACCOUNT)]),
     "0 found by name, 0 name(s) the baseline lacks, 1 tagged"),
    (lambda a: a["things"].update({THING: {"shadows": {}, "principals": {}}}), "1 found by name"),
])
def test_verify_gone_fails_on_one_extra_name_one_tagged_resource_or_one_thing_still_found(rig: Rig, leftover: Any, what: str) -> None:
    for step in ("thing", "firehose-log"):
        rig.go("apply", step)
    for step in ("thing", "firehose-log"):
        rig.go("teardown", step)
    assert "verify-gone: gone" in rig.run("verify-gone", expect=0).out
    writes = rig.writes()
    rig.edit(leftover)
    ran = rig.run("verify-gone", expect=1)
    assert "verify-gone: NOT gone" in ran.err and what in ran.err and rig.writes() == writes and not clean(ran.text)


def test_verify_gone_needs_the_baseline_and_a_baseline_is_taken_before_the_first_create(rig: Rig) -> None:
    listings = json.loads((rig.state / "baseline.json").read_text(encoding="utf-8"))["listings"]
    assert listings["workgroups"] == ["primary"] and set(listings) == set(TW.LISTINGS)
    assert all(v == [] for k, v in listings.items() if k != "workgroups")
    assert "refused: baseline-exists:" in rig.run("baseline", expect=1).err
    rig.run("baseline", "--again", expect=0)
    rig.go("apply", "thing")
    assert "refused: baseline-too-late:" in rig.run("baseline", "--again", expect=1).err
    assert rig.writes() == [["iot", "create-thing", "--thing-name", THING]]
    (rig.state / "baseline.json").unlink()
    assert "refused: no-baseline:" in rig.run("verify-gone", expect=1).err


# ================================================================================================= status, trip, restore

def test_status_prints_states_and_never_values_and_passes_on_the_built_twin(built: Rig, tmp_path: Path) -> None:
    twin = built.copy(tmp_path / "twin")
    before = twin.writes()
    ran = twin.run("status", expect=0)
    assert twin.writes() == before and not clean(ran.text)
    lines = {line.split()[0]: line for line in ran.out.split("\n") if line.startswith("  ")}
    for step in ("operator-role", "bucket", "stream", "rule", "certificate", "attachments", "function", "function-policy", "alarms", "alarm-notice",
                 "iot-logging", "go-live-rule", "go-live-certificate", "notice-topic", "breaker-role"):
        assert "as rendered" in lines[step], lines[step]
    assert "traffic: the rule is enabled" in ran.out
    assert "the certificate is ACTIVE; the policy is attached; the thing is attached (exclusive)" in ran.out
    for key in BREAKER:
        assert re.search(r"alarm %s +OK; actions enabled; targets: the function, the notice topic" % key, ran.out), key
    assert re.search(r"alarm errors +INSUFFICIENT_DATA; actions enabled; targets: the notice topic", ran.out)
    assert "the function's reserved concurrency: 1" in ran.out
    assert "ok: the function's environment names exactly the twin's 1 certificate(s)" in ran.out
    assert "ok: no ACTIVE certificate of the account is outside the twin's set (1 listed)" in ran.out


def test_status_prints_the_sha256_of_the_thresholds_file_the_alarms_are_rendered_from(built: Rig, tmp_path: Path) -> None:
    """The burst tool's hard review, SHOULD 2 (sdv/cloud/burst, its decision 6). The burst tool sizes a burst on a thresholds
    file and is given the sha256 of the file the account's alarms were rendered from: `status`, which holds the alarms to that
    file (`as rendered`, or how they differ), prints it after the alarms' lines. It is the hash of the file's BYTES as they
    stand, for a file load_thresholds takes; a file that is refused has no hash printed, and a refusal's name in its place.
    A hash, never a count of the file."""
    twin = built.copy(tmp_path / "twin")
    path = twin.inputs / "thresholds.json"
    said = "thresholds: the file the alarms are rendered from has sha256 %s (the burst tool takes it as --thresholds-sha256)"
    before = twin.writes()
    ran = twin.run("status", expect=0)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    out = ran.out.split("\n")
    assert [line for line in out if "thresholds" in line] == [said % digest] and re.fullmatch(r"[0-9a-f]{64}", digest)
    assert out.index(said % digest) == max(i for i, line in enumerate(out) if line.startswith("alarm ")) + 1          # right after the alarms' lines
    assert "as rendered" in [line for line in out if line.startswith("  alarms ")][0] and not clean(ran.text) and twin.writes() == before
    assert ran.out.count(digest) == 1 and digest not in ran.err
    counts = {str(v) for v in THRESHOLDS.values() if v != 1}
    assert not counts & set(re.findall(r"[0-9]+", (said % "").replace("sha256", "")))          # the line holds no count of the file
    # the BYTES are hashed: the same document written otherwise has another hash, and the alarms are as rendered still
    doc = json.loads(path.read_text(encoding="ascii"))
    path.write_text(json.dumps(doc, indent=1), encoding="ascii")
    ran = twin.run("status", expect=0)
    other = hashlib.sha256(path.read_bytes()).hexdigest()
    assert other != digest and (said % other) in ran.out.split("\n") and digest not in ran.text
    assert "as rendered" in [line for line in ran.out.split("\n") if line.startswith("  alarms ")][0]
    # a file with another threshold: the alarms' step says that it differs, beside that file's hash
    doc["thresholds"]["Firehose.IncomingRecords"] += 7
    path.write_text(json.dumps(doc), encoding="ascii")
    ran = twin.run("status")
    third = hashlib.sha256(path.read_bytes()).hexdigest()
    assert (said % third) in ran.out.split("\n") and "DIFFERS" in [line for line in ran.out.split("\n") if line.startswith("  alarms ")][0]
    # a file derive.py's own check refuses, and no file named: no hash is printed, and the refusal's name stands in its place
    path.write_text(json.dumps(dict(doc, the_double_says="no")), encoding="ascii")
    ran = twin.run("status")
    assert "thresholds: the file the alarms are rendered from: not read (thresholds-check-failed)" in ran.out.split("\n")
    assert "has sha256" not in ran.text and hashlib.sha256(path.read_bytes()).hexdigest() not in ran.text
    twin.write_names(TWIN_THRESHOLDS=None)
    ran = twin.run("status")
    assert "thresholds: the file the alarms are rendered from: not read (thresholds-unset)" in ran.out.split("\n") and "has sha256" not in ran.text
    assert twin.writes() == before


def test_status_prints_the_sha256_of_a_thresholds_file_the_names_file_gives_with_a_tilde_under_the_home_the_test_gives(
        built: Rig, tmp_path: Path) -> None:
    """burst-verify-final, problem 5 (its mutant X02; the ledger's burst-critic#7). The hash is read from the path load_thresholds
    takes, `~` expanded, and no test wrote TWIN_THRESHOLDS with one: without the expansion in the hash's read, `status` would say
    `not read (thresholds-missing)` for a file it had just taken, and the whole file passed. Here the names file gives
    `~/thresholds.json` and the process is given a home of the test's own (HOME and USERPROFILE, whichever the platform reads),
    which holds a file of other bytes than the inputs'; `status` prints that file's own sha256 and no other line about it."""
    twin = built.copy(tmp_path / "twin")
    home = tmp_path / "home"
    home.mkdir()
    shutil.copyfile(str(twin.inputs / "derive.py"), str(home / "derive.py"))
    doc = json.loads((twin.inputs / "thresholds.json").read_text(encoding="ascii"))
    (home / "thresholds.json").write_text(json.dumps(doc, indent=1), encoding="ascii")          # the same document, written otherwise
    twin.write_names(TWIN_THRESHOLDS="~/thresholds.json")
    before = twin.writes()
    ran = twin.run("status", env={"HOME": str(home), "USERPROFILE": str(home)}, expect=0)
    digest = hashlib.sha256((home / "thresholds.json").read_bytes()).hexdigest()
    assert digest != hashlib.sha256((twin.inputs / "thresholds.json").read_bytes()).hexdigest()
    said = "thresholds: the file the alarms are rendered from has sha256 %s (the burst tool takes it as --thresholds-sha256)"
    assert [line for line in ran.out.split("\n") if "thresholds" in line] == [said % digest]
    assert "not read" not in ran.text and not clean(ran.text) and twin.writes() == before


def test_status_fails_when_the_functions_environment_is_not_exactly_the_twins_certificates(twin: Rig) -> None:
    env = twin.account()["functions"][PREFIX + "-breaker"]["config"]["Environment"]["Variables"]
    assert env == {"TWIN_CERTIFICATE_ARNS": iot_arn("cert", CERT_1), "TWIN_CLIENT_IDS": THING, "TWIN_RULE": PREFIX + "_telemetry",
                   "TWIN_POLICY": PREFIX + "-device"}
    other = iot_arn("cert", hashlib.sha256(b"another certificate").hexdigest())
    for value in ("", other, iot_arn("cert", CERT_1) + "," + other):
        twin.edit(lambda a, v=value: a["functions"][PREFIX + "-breaker"]["config"]["Environment"]["Variables"].update(TWIN_CERTIFICATE_ARNS=v))
        ran = twin.run("status", expect=1)
        assert "FAIL: the certificates in the function's environment are not exactly the twin's" in ran.err and not clean(ran.text)


def test_status_fails_with_an_active_certificate_outside_the_twins_set(twin: Rig) -> None:
    other = hashlib.sha256(b"a certificate added later").hexdigest()
    twin.edit(lambda a: a["certs"].update({other: {"status": "INACTIVE", "policies": []}}))
    assert "is outside the twin's set (2 listed)" in twin.run("status", expect=0).out          # INACTIVE: listed, and no finding
    twin.edit(lambda a: a["certs"][other].update(status="ACTIVE"))
    ran = twin.run("status", expect=1)
    assert "FAIL: 1 ACTIVE certificate(s) of the account are outside the twin's set" in ran.err
    assert other not in ran.text and not clean(ran.text)


def test_trip_invokes_the_function_and_shows_the_cut_and_no_call_ever_asks_for_a_log_tail(twin: Rig, built: Rig) -> None:
    since = len(twin.log())
    ran = twin.run("trip", expect=0)
    invoke, = twin.writes(since)
    assert invoke[:2] == ["lambda", "invoke"] and "--log-type" not in invoke and invoke[invoke.index("--function-name") + 1] == PREFIX + "-breaker"
    payload = invoke[invoke.index("--payload") + 1]
    assert json.loads(Path(payload[len("file://"):]).read_text(encoding="ascii")) == {"manual": "trip"}
    assert "traffic: the rule is DISABLED" in ran.out and "the certificate is INACTIVE; the policy is NOT attached" in ran.out
    assert "trip: the function ran" in ran.out and not clean(ran.text)
    a = twin.account()
    assert a["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is True and a["certs"][CERT_1] == {"status": "INACTIVE", "policies": []}
    # the four calls by hand are written out, unredacted, in the state directory: the trip's first act (WP8's fixes, below)
    hand, _notes = by_hand(twin)
    assert [line.split()[1:3] for line in hand] == [["iot", "disable-topic-rule"], ["iot", "update-certificate"],
                                                    ["iot-data", "delete-connection"], ["iot", "detach-policy"]]
    assert CERT_1 in hand[1] and THING in hand[2] and "--profile " + PROFILE in hand[0] and not (twin.render / HAND_FILE).exists()
    # no call of the whole run, of the plan, of this trip: none asks for the function's log
    for rig in (built, twin):
        for name in ("log.jsonl", "skeleton.jsonl", "refused.jsonl"):
            assert not [e for e in rig.log(name) if any(a.startswith("--log-type") for a in e["argv"])], name
    assert not [c for s in twin.plan() for kind in ("creates", "reads", "deletes") for c in s.get(kind, []) if "--log-type" in c]
    assert [len(c) for s in built.plan() for c in s["creates"] if c[:2] == ["lambda", "invoke"]] == [9, 9]


def test_no_rendered_call_asks_for_a_reply_field_that_carries_encoded_text(rig: Rig) -> None:
    """The plan's own list, before anything runs: a function's invoke is never asked for its log tail."""
    rig.run("plan", "--no-cli", expect=0)
    calls = every_call(rig)
    invokes = [c for c in calls if c[:2] == ["lambda", "invoke"]]
    assert len(invokes) == 3 and len(calls) > 120                   # the status invoke, the dry trip, and `twinctl trip`
    for c in calls:
        assert not [a for a in c if a.startswith(TW.FORBIDDEN_OPTIONS) or "LogResult" in a or a.lower().startswith("--log-type")], c[:2]
    for c in invokes:                                               # the record is read through the payload's file, and only so
        assert c[-1].endswith(".json") and "/replies/payload-" in c[-1] and c[c.index("--cli-binary-format") + 1] == "raw-in-base64-out"


def test_the_runner_refuses_any_argv_that_asks_for_a_log_tail(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    aws = stub_runner(rig, monkeypatch)
    aws.arm()
    for extra in (["--log-type", "Tail"], ["--log-type=Tail"]):
        with pytest.raises(TW.TwinError) as e:
            aws.run(TW.W("lambda", "invoke", "--function-name", "x", *extra))
        assert e.value.name == "forbidden-option" and rig.log() == []
    assert TW.FORBIDDEN_OPTIONS == ("--log-type",) and TW.ENCODED_REPLY_FIELDS[0] == "LogResult"
    source = (REPO / "sdv" / "cloud" / "twinctl.py").read_text(encoding="utf-8")
    assert source.count('"--log-type"') == 1 and source.count('("LogResult",)') == 1         # each list stands once, in the driver
    assert TW.find_encoded({"a": [{"b": {"LogResult": "x"}}]}) == "LogResult" and TW.find_encoded({"StatusCode": 200}) is None


def test_a_trips_reply_and_record_are_copied_redacted_and_a_reply_with_logresult_is_refused_before_the_copy(twin: Rig, tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    ran = twin.run("trip", "--capture", capture, expect=0)
    assert sorted(p.name for p in capture.iterdir()) == ["trip-record.json", "trip-reply.json"]
    assert json.loads((capture / "trip-reply.json").read_text(encoding="utf-8")) == {"ExecutedVersion": "$LATEST", "StatusCode": 200}
    assert json.loads((capture / "trip-record.json").read_text(encoding="utf-8"))["mode"] == "trip"
    assert LS.scan(str(capture), list(IDENTIFIERS)) == [] and not clean(ran.text)
    # a reply that holds the field all the same. The block is under 64 characters: the redactor's own rule would not see it.
    block = base64.b64encode(b"the breaker cut " + THING.encode()).decode()
    assert len(block) < 64
    twin.edit(lambda a: a.update(invoke_log_result=block))
    second = tmp_path / "second"
    ran = twin.run("trip", "--capture", second, expect=1)
    assert "refused: reply-holds-encoded-text:" in ran.err and "LogResult" in ran.err and block not in ran.text
    assert not second.exists() and "traffic: the rule is DISABLED" in ran.out
    # a field nobody listed that holds encoded text all the same: the redactor's refusal is a stop, and the capture is whole or
    # not there (the reply, which is clean, is not left behind alone)
    twin.edit(lambda a: (a.pop("invoke_log_result"), a.update(record_extra={"note": base64.b64encode(b"what the function saw " * 6).decode()})))
    third = tmp_path / "third"
    ran = twin.run("trip", "--capture", third, expect=1)
    assert "refused: capture-refused:" in ran.err and "undecoded data" in ran.err and "a stop, not a retry" in ran.err and not third.exists()
    # only the replies on the driver's own list are ever copied
    with pytest.raises(TW.TwinError) as e:
        TW.capture_replies(TW.Twin(twin.state, None, False), [("iot", "describe-certificate", capture / "trip-reply.json", "x.json")],
                           tmp_path / "fourth")
    assert e.value.name == "reply-not-copied" and not (tmp_path / "fourth").exists()
    assert TW.COPIED_REPLIES == (("lambda", "invoke"), ("lambda", "invoke-payload"))


def test_a_function_that_did_not_run_is_said_and_the_status_still_follows(twin: Rig) -> None:
    twin.edit(lambda a: a.update(function_error=True))
    ran = twin.run("trip", expect=1)
    assert "RUN THE FOUR CALLS BY HAND" in ran.err and "traffic: the rule is" in ran.out
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "invoke", "code": "ResourceNotFoundException"}))
    ran = twin.run("trip", expect=1)
    assert "the invoke failed (ResourceNotFoundException). RUN THE FOUR CALLS BY HAND" in ran.err


def test_restore_is_refused_while_a_breaker_alarm_is_in_alarm_disabled_or_missing(twin: Rig) -> None:
    twin.run("trip", expect=0)
    since = len(twin.log())
    ran = twin.run("restore", expect=0)
    assert twin.writes(since) == [] and not clean(ran.text)
    calls = [line.split()[2:4] for line in ran.out.split("\n") if line.startswith("  run: ")]
    assert calls == [["iot", "attach-policy"], ["iot", "update-certificate"], ["iot", "enable-topic-rule"]]
    proofs = [line.split()[2:4] for line in ran.out.split("\n") if line.startswith("  proof: ")]
    assert proofs == [["iot", "list-attached-policies"], ["iot", "describe-certificate"], ["iot", "get-topic-rule"]]
    lines = (twin.render / "restore.txt").read_text(encoding="utf-8").split("\n")
    assert [line.split()[1:3] for line in lines if line] == [
        ["iot", "attach-policy"], ["iot", "list-attached-policies"], ["iot", "update-certificate"], ["iot", "describe-certificate"],
        ["iot", "enable-topic-rule"], ["iot", "get-topic-rule"]]
    assert "--new-status ACTIVE" in lines[2] and CERT_1 in lines[2] and PREFIX + "_telemetry" in lines[4]
    # it only renders: the account is as the trip left it
    assert twin.account()["certs"][CERT_1]["status"] == "INACTIVE"
    (twin.render / "restore.txt").unlink()
    for key in BREAKER:
        alarm = "%s-%s" % (PREFIX, key)
        for change, word in ((dict(StateValue="ALARM"), "1 are in ALARM"), (dict(ActionsEnabled=False), "1 have their actions disabled")):
            saved = twin.account()
            twin.edit(lambda a, name=alarm, c=change: a["alarms"][name].update(c))
            ran = twin.run("restore", expect=1)
            assert "refused: restore-refused:" in ran.err and word in ran.err and "aws " not in ran.text, (key, word)
            twin.put_account(saved)
        saved = twin.account()
        twin.edit(lambda a, name=alarm: a["alarms"].pop(name))
        assert "1 are not there" in twin.run("restore", expect=1).err
        twin.put_account(saved)
    assert not (twin.render / "restore.txt").exists()
    # the notice alarm is no breaker alarm: its state does not hold a restore back
    twin.edit(lambda a: a["alarms"]["%s-errors" % PREFIX].update(StateValue="ALARM"))
    twin.run("restore", expect=0)


# ================================================================================================= what is printed, and where things live

def test_no_identifier_shape_no_literal_and_no_local_directory_reaches_what_is_printed(built: Rig, tmp_path: Path) -> None:
    twin = built.copy(tmp_path / "twin")
    for argv in (["status"], ["plan", "--no-cli"], ["teardown"], ["verify-gone"], ["restore"], ["apply", "bucket"], ["apply", "operator-role"],
                 ["teardown", "go-live-certificate"], ["trip"], ["status"], ["apply", "alarms"], ["apply", "certificate"]):
        twin.run(*argv)
    said = built.said + twin.said
    assert len(said) > 60
    text = "".join(r.text for r in said)
    assert clean(text) == []
    for local in (str(built.base), str(twin.base), str(tmp_path), built.base.as_posix(), str(Path.home()), Path.home().as_posix()):
        assert local not in text, "a local directory is printed"
    user = getpass.getuser()
    assert len(user) < 3 or user not in text
    # what stands in their places
    for mask in ("<prefix>", "<thing>", "<bucket-suffix>", "<arn>", "<render>", "<state>", "<notice-address>", "<certificate-id>", "<account>"):
        assert mask in text, mask
    assert ENDPOINT not in text and "amazonaws.com" not in text.replace("lambda.alarms.cloudwatch.amazonaws.com", "").replace(
        "cloudwatch.amazonaws.com", "").replace("iot.amazonaws.com", "").replace("firehose.amazonaws.com", "").replace("lambda.amazonaws.com", "")


def test_a_refusal_of_the_redactor_withholds_the_line(rig: Rig) -> None:
    block = base64.b64encode(b"a reply that came base64 encoded and names the endpoint and the account " * 2).decode()
    TW.OUT = TW.Out()
    out = TW.OUT.clean("the reply was " + block)
    assert block not in out and out.startswith("(withheld: ") and "undecoded data" in out
    assert TW.OUT.clean("an address %s and the account %s" % (ADDRESS, "123456789012")) == "an address <e-mail> and the account <account>"


@pytest.mark.parametrize("argv", [["plan", "--no-cli"], ["literals"], ["baseline"], ["status"], ["apply", "bucket"], ["teardown"],
                                  ["verify-gone"], ["trip"], ["restore"], ["branch-scan"], ["exit-checks", "--capture", "CAPTURE"]])
def test_a_state_directory_inside_a_work_tree_is_refused_before_anything_is_made(rig: Rig, tmp_path: Path, argv: List[str]) -> None:
    inside = REPO / "sdv" / "cloud" / "twin-state-of-a-test"
    argv = [str(tmp_path / "capture") if a == "CAPTURE" else a for a in argv]
    for how in ("flag", "environment"):
        ran = rig.run(*(["--state", str(inside)] if how == "flag" else []), *argv, env={"TWIN_STATE": str(inside)} if how == "environment" else None,
                      expect=1)
        assert "refused: inside-a-work-tree:" in ran.err and "state directory" in ran.err and str(REPO) not in ran.text
        assert not inside.exists() and rig.log() == []
    # a directory that is itself a repository, and one below a repository that is not this one
    other = tmp_path / "another-checkout"
    (other / ".git").mkdir(parents=True)
    for place in (other, other / "deep" / "state"):
        assert "refused: inside-a-work-tree:" in rig.run("--state", str(place), *argv, expect=1).err
        assert not (other / "deep").exists() and list(other.iterdir()) == [other / ".git"]


def test_a_render_or_capture_directory_inside_a_work_tree_is_refused(rig: Rig, twin: Rig, tmp_path: Path) -> None:
    inside = REPO / "sdv-out" / "twin-render-of-a-test"
    for how in ("flag", "environment"):
        ran = rig.run(*(["--render", str(inside)] if how == "flag" else []), "plan", "--no-cli",
                      env={"TWIN_RENDER": str(inside)} if how == "environment" else None, expect=1)
        assert "refused: inside-a-work-tree:" in ran.err and "render directory" in ran.err and not inside.exists()
    assert not rig.render.exists()
    for command in (["trip", "--capture", str(REPO / "results" / "twin-capture-of-a-test")],
                    ["exit-checks", "--capture", str(REPO / "results" / "twin-capture-of-a-test")]):
        since = len(twin.log())
        ran = twin.run(*command, expect=1)
        assert "refused: inside-a-work-tree:" in ran.err and "capture directory" in ran.err and twin.log()[since:] == []
    assert not (REPO / "results" / "twin-capture-of-a-test").exists()
    # elsewhere it is used: the renders go where --render says, and nothing into the state directory
    elsewhere = tmp_path / "renders"
    rig.run("--render", elsewhere, "plan", "--no-cli", expect=0)
    assert (elsewhere / "plan.json").is_file() and (elsewhere / "bucket" / "bucket-policy.json").is_file() and not rig.render.exists()


def test_nothing_is_written_into_the_work_tree_by_a_whole_run(built: Rig) -> None:
    for d in (REPO / "sdv" / "cloud", REPO / "sdv" / "cloud" / "templates", REPO / "tests"):
        names = {p.name for p in d.iterdir()}
        assert not names & {"state.json", "names.env", "literals.json", "baseline.json", "approvals.jsonl", "salt", "render", "replies",
                            "account.json", "log.jsonl"}, d
    assert (built.state / "salt").is_file() and (built.state / "replies").is_dir() and (built.state / "approvals.jsonl").is_file()
    kept = [p.name for p in (built.state / "replies").iterdir() if re.match(r"\d{8}T\d{6}Z-", p.name) and p.name.endswith(".json")]
    assert len(kept) == len(built.log()) > 150 and any("create-certificate-from-csr" in n for n in kept)   # every raw reply stays in the state


# ================================================================================================= the names file, the literals

def test_the_names_file_is_strict_and_the_environment_wins(rig: Rig) -> None:
    (rig.state / "names.env").write_text((rig.state / "names.env").read_text(encoding="utf-8") + "TWIN_PREFFIX=x\n", encoding="utf-8")
    ran = rig.run("plan", "--no-cli", expect=1)
    assert "refused: names-key-unknown:" in ran.err and "line " in ran.err and "PREFFIX" not in ran.err
    rig.write_names()
    assert "refused: names-key-unknown:" in rig.run("plan", "--no-cli", env={"TWIN_BUCKET_SUFIX": "x"}, expect=1).err
    for key in ("TWIN_ACCOUNT", "TWIN_PREFIX", "TWIN_THING", "TWIN_NOTICE", "TWIN_PROFILE", "TWIN_OPERATOR_ROLE", "TWIN_BUCKET_SUFFIX"):
        rig.write_names(**{key: None})
        ran = rig.run("plan", "--no-cli", expect=1)
        assert "refused: names-missing: %s is not set" % key in ran.err, key
    for key, value in (("TWIN_ACCOUNT", "12345678901"), ("TWIN_PREFIX", "Example-Twin"), ("TWIN_PREFIX", "short"), ("TWIN_REGION", "nowhere"),
                       ("TWIN_THING", "another-thing-zz"), ("TWIN_NOTICE", "yes"), ("TWIN_BUCKET_SUFFIX", "UPPER123"),
                       ("TWIN_RULE_COUNT_READING", "per_minute")):
        rig.write_names(**{key: value})
        ran = rig.run("plan", "--no-cli", expect=1)
        assert "refused: names-invalid:" in ran.err and value not in ran.text, (key, value)
    # the notice's address is given when its step is reached: until then that one step is refused, and only that one
    rig.write_names(TWIN_NOTICE_ADDRESS=None)
    rig.run("literals", expect=0)
    ran = rig.run("plan", "--no-cli", expect=1)
    refused = [line.split()[0] for line in ran.out.split("\n") if " REFUSED " in line]
    assert refused == ["notice-topic"] and "REFUSED input-unset: TWIN_NOTICE_ADDRESS is not set" in ran.out
    assert "1 refused for an input that is not there" in ran.out
    rig.write_names()
    rig.run("literals", expect=0)
    # the environment wins over the file, and the switch keeps the file unread
    rig.write_names(TWIN_BUCKET_SUFFIX="filevalue00")
    rig.run("plan", "--no-cli", env={"TWIN_BUCKET_SUFFIX": SUFFIX}, expect=0)
    assert SUFFIX in json.dumps(rig.doc("bucket", "bucket-policy")) and "filevalue00" not in json.dumps(rig.doc("bucket", "bucket-policy"))
    # a byte order mark an editor left in front is no part of the first key, and CRLF line ends are no part of a value
    rig.write_names()
    text = (rig.state / "names.env").read_text(encoding="utf-8")
    (rig.state / "names.env").write_bytes(b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8"))
    rig.run("plan", "--no-cli", expect=0)
    (rig.state / "names.env").write_text("this is not a names file\n", encoding="utf-8")
    env = dict(rig.names(), TWIN_NO_NAMES_FILE="1")
    rig.run("plan", "--no-cli", env=env, expect=0)
    assert "refused: names-key-unknown:" in rig.run("plan", "--no-cli", env=rig.names(), expect=1).err


def test_the_env_example_names_every_key_and_only_placeholders() -> None:
    text = (REPO / "sdv" / "cloud" / ".env.example").read_text(encoding="utf-8")
    keys = set(re.findall(r"^#? ?(TWIN_[A-Z0-9_]+)=", text, re.M))
    assert keys == set(TW.NAME_KEYS)
    values = dict(re.findall(r"^(TWIN_[A-Z0-9_]+)=(.*)$", text, re.M))
    assert values["TWIN_ACCOUNT"] == "123456789012" and values["TWIN_PREFIX"] == "exampletwin" and values["TWIN_REGION"] == TW.REGION_DEFAULT
    for key, value in values.items():
        assert re.fullmatch(TW.NAME_KEYS[key][1], value), key
    # the certificate goes where the connector reads it (sdv/connector/README.md: device.crt in the device directory)
    assert "# TWIN_CERTIFICATE_OUT=/path/to/the/device/directory/device.crt\n" in text and "cert.pem" not in text.replace("rehearsal-cert.pem", "")


def test_literals_writes_the_file_prints_nothing_and_keeps_the_owners_own_kinds(tmp_path: Path) -> None:
    rig = Rig(tmp_path / "twin")
    ran = rig.run("literals", expect=0)
    assert ran.text == ""
    doc = json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))
    assert doc == {"v": 1, "literals": {"account": [ACCOUNT], "bucket-suffix": [SUFFIX], "notice-address": [ADDRESS], "operator-role": [ROLE],
                                        "prefix": [PREFIX], "profile": [PROFILE], "thing": [THING]}}
    # the owner's own kinds are carried over; the driver's own are written anew
    doc["literals"]["reference-names"] = ["a name of the owner's"]
    doc["literals"]["prefix"] = ["something stale"]
    (rig.state / "literals.json").write_text(json.dumps(doc), encoding="utf-8")
    rig.run("literals", expect=0)
    again = json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))["literals"]
    assert again["reference-names"] == ["a name of the owner's"] and again["prefix"] == [PREFIX]
    # after the baseline the endpoint's prefix and the canonical id are literals too, and the redactor has them
    rig.run("baseline", expect=0)
    lits = json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))["literals"]
    assert lits["endpoint-prefix"] == [ENDPOINT_PREFIX] and lits["canonical-user-id"] == [CANONICAL]
    assert TW.REDACT.redact_text("mqtts://%s:8883 owned by %s" % (ENDPOINT, CANONICAL), TW.REDACT.load_literals(rig.state)) == \
        "mqtts://<endpoint-prefix><endpoint>:8883 owned by <canonical-user-id>"


def test_literals_refuses_a_short_value_and_one_the_work_tree_already_holds_by_position(tmp_path: Path) -> None:
    rig = Rig(tmp_path / "twin")
    short = j("a@", "b.io")
    rig.write_names(TWIN_NOTICE_ADDRESS=short)
    ran = rig.run("literals", expect=1)
    assert "refused: literal-too-short: value 1 of the kind notice-address has 6 character(s)" in ran.err and short not in ran.text
    assert not (rig.state / "literals.json").exists()
    # a rule called `telemetry` would be cut out of every record that says it, and flag the connector's own log
    for key, value, kind in (("TWIN_PREFIX", "telemetry", "prefix"), ("TWIN_PROFILE", "connector", "profile"),
                             ("TWIN_ACCOUNT", "123456789012", "account"), ("TWIN_OPERATOR_ROLE", "hard-brake-hazard", "operator-role")):
        change = {key: value}
        if key == "TWIN_PREFIX":
            change["TWIN_THING"] = value + j("-thing", "-zz")
        rig.write_names(**change)
        ran = rig.run("literals", expect=1)
        assert "refused: literal-in-the-work-tree: value 1 of the kind %s is found in " % kind in ran.err, ran.text
        assert value not in ran.text.replace("literal-in-the-work-tree", "") and not (rig.state / "literals.json").exists()
    absent = j("no file of the tree ", "holds this sentence")
    assert TW.MIN_LITERAL == 8 and TW.tree_search([absent]) == {absent: 0}


def test_a_command_refuses_to_print_without_the_literals_or_with_a_file_that_is_behind_the_state(tmp_path: Path) -> None:
    rig = Rig(tmp_path / "twin")
    for argv in (["plan", "--no-cli"], ["status"], ["apply", "bucket"], ["baseline"], ["restore"], ["teardown"], ["verify-gone"]):
        ran = rig.run(*argv, expect=1)
        assert "refused: literals-refused:" in ran.err and "twinctl literals" in ran.err and rig.log() == [], argv
    rig.run("literals", expect=0)
    rig.write_names(TWIN_BUCKET_SUFFIX=j("ffeeddcc", "bbaa"))
    ran = rig.run("plan", "--no-cli", expect=1)
    assert "refused: literals-behind:" in ran.err and "bucket-suffix" in ran.err
    rig.run("literals", expect=0)
    rig.run("plan", "--no-cli", expect=0)


# ================================================================================================= the rehearsal (A2)

def test_the_rehearsal_is_the_kinds_that_need_no_service_role_under_names_of_their_own(rig: Rig) -> None:
    rig.run("--rehearsal", "plan", "--no-cli", expect=0)
    steps = json.loads((rig.render / "rehearsal-plan.json").read_text(encoding="utf-8"))["steps"]
    assert [s["id"] for s in steps] == ["bucket", "bucket-objects", "firehose-log", "thing", "shadows", "certificate", "policy", "attachments",
                                        "glue", "workgroup", "notice-topic", "alarms"]
    text = json.dumps(steps)
    for never in ("create-delivery-stream", "create-topic-rule", "create-function", '"iam"', "set-v2-logging-options", '"subscribe"',
                  "add-permission", '"invoke"'):
        assert never not in text, never
    rh = PREFIX + "rh"
    for step in ("bucket", "firehose-log", "thing", "policy", "glue", "workgroup", "notice-topic", "alarms"):
        rig.go("apply", step, "--rehearsal")
    rig.go("apply", "certificate", "--rehearsal")
    rig.go("apply", "attachments", "--rehearsal")
    rig.go("apply", "shadows", "--rehearsal")
    a = rig.account()
    assert list(a["buckets"]) == ["%s-telemetry-%s" % (rh, SUFFIX)] and list(a["things"]) == [rh + "-thing"]
    assert a["things"][rh + "-thing"]["shadows"] == {"rehearsal": {"state": {"desired": {"rehearsal": True}}}}
    assert a["certs"][CERT_1]["status"] == "INACTIVE" and a["certs"][CERT_1]["policies"] == [rh + "-device"]
    assert list(a["alarms"]) == [rh + "-bytes"]
    assert a["alarms"][rh + "-bytes"]["AlarmActions"] == [] and a["alarms"][rh + "-bytes"]["Threshold"] == 1.0
    assert list(a["topics"]) == ["arn:aws:sns:%s:%s:%s-notice" % (REGION, ACCOUNT, rh)] and a["topics"][list(a["topics"])[0]]["subscriptions"] == []
    assert a["log_groups"][rh + "-firehose-errors"]["streams"] == ["delivery"] and a["streams"] == {} and a["rules"] == {} and a["functions"] == {}
    # a state of its own: the twin's own steps are untouched, and its teardown is the rehearsal's table in reverse
    assert json.loads((rig.state / "state.json").read_text(encoding="utf-8"))["steps"] == {}
    order = [line.split()[0] for line in rig.run("--rehearsal", "teardown", expect=0).out.split("\n") if line.startswith("  ")]
    assert order == list(reversed([s["id"] for s in steps]))
    for step in order:
        if step == "bucket-objects":                                # an empty bucket: nothing to approve
            assert "lists no object" in rig.run("--rehearsal", "teardown", step, expect=0).out
        else:
            rig.go("teardown", step, "--rehearsal")
    rig.run("--rehearsal", "verify-gone", expect=0)
    a, fresh = rig.account(), new_account()
    assert all(a[t] == fresh[t] for t in ("buckets", "log_groups", "things", "certs", "policies", "glue", "workgroups", "topics", "alarms"))
    assert not clean("".join(r.text for r in rig.said))


# ================================================================================================= the exit's read-only checks (A5)

def live(twin: Rig) -> None:
    """What a replay leaves: the two shadows with allowlisted keys, and batches under the three prefixes."""
    allow = json.loads((REPO / "sdv" / "connector" / "twin_allowlist.json").read_text(encoding="utf-8"))["entries"]
    shadow = [e["path"] for e in allow if "S" in e["channels"]]
    bucket = "%s-telemetry-%s" % (PREFIX, SUFFIX)

    def change(a: Dict[str, Any]) -> None:
        a["things"][THING]["shadows"] = {"vss": {"state": {"reported": {p: 1 for p in shadow}}},
                                         "config": {"state": {"reported": {"rate_hz": 1, "paths": shadow[:3]}}}}
        a["buckets"][bucket]["objects"] = ["telemetry/dt=2026-01-01/a", "errors/x", "athena-results/q.csv"]
    twin.edit(change)


def test_exit_checks_reads_only_reduces_each_result_to_a_shape_and_leaves_a_clean_capture(twin: Rig, tmp_path: Path) -> None:
    live(twin)
    paths = tmp_path / "athena-paths.json"
    allow = json.loads((REPO / "sdv" / "connector" / "twin_allowlist.json").read_text(encoding="utf-8"))["entries"]
    paths.write_text(json.dumps([e["path"] for e in allow][:5]), encoding="utf-8")
    capture = tmp_path / "capture"
    since = len(twin.log())
    ran = twin.run("exit-checks", "--capture", capture, "--min-vss-keys", "5", "--athena-paths", paths, expect=0)
    assert twin.writes(since) == [] and not clean(ran.text)
    assert [p.name for p in capture.iterdir()] == ["exit-checks.json"] and LS.scan(str(capture), list(IDENTIFIERS)) == []
    summary = json.loads((capture / "exit-checks.json").read_text(encoding="utf-8"))
    results = {c["check"]: c for c in summary["checks"]}
    assert len(results) == 12 and {c["result"] for c in results.values()} == {"pass"}
    assert results["security groups"]["shape"] == {"groups": 1, "cidr_rules": 1, "open_to_the_world": 0, "tcp_22_from_one_address": 1}
    assert results["the bucket's top-level prefixes"]["shape"] == {"prefixes": ["athena-results/", "errors/", "telemetry/"],
                                                                   "objects_outside_a_prefix": 0}
    assert results["S11: the shadows' keys"]["shape"]["under_the_excluded_branch"] == 0
    # every value of the summary is a count, a boolean or a fixed word: no name of the account
    text = json.dumps(summary)
    assert not [v for v in IDENTIFIERS if v in text]
    # a second capture is not mixed into the first
    assert "refused: capture-not-empty:" in twin.run("exit-checks", "--capture", capture, expect=1).err


def test_a_regional_endpoint_that_has_not_heard_of_the_accounts_setting_is_told_from_a_setting_that_is_absent(tmp_path: Path) -> None:
    """The check passes only on the twin's own region. The second read keeps a late region from reading as an
    absent setting; these tests plant both replies and establish no propagation time."""
    twin = Rig(tmp_path / "another-region")
    twin.write_names(TWIN_REGION="eu-central-1")
    twin.start()

    def line(n: int) -> str:
        ran = twin.run("exit-checks", "--capture", tmp_path / ("capture-%d" % n), expect=1)        # nothing is made: only this line is read
        found = [x for x in ran.out.split("\n") if "account-level Block Public Access" in x]
        assert len(found) == 1 and not clean(ran.text)
        return found[0]

    assert line(1).split()[0] == "pass" and '{"true": 4, "true_read_through_us_east_1": 4}' in line(2)
    twin.edit(lambda a: a.update(account_block_not_yet_in=["eu-central-1"]))
    late = line(3)
    assert late.split()[0] == "FAIL" and '{"true": 0, "true_read_through_us_east_1": 4}' in late
    twin.edit(lambda a: a.update(account_block=None))
    assert '{"true": 0, "true_read_through_us_east_1": 0}' in line(4)
    reads = [e["argv"] for e in twin.log() if e["argv"][:2] == ["s3control", "get-public-access-block"]]
    assert all(a.count("--region") == 1 for a in reads) and {a[a.index("--region") + 1] for a in reads} == {"eu-central-1", "us-east-1"}


def _open(a: Dict[str, Any]) -> None:
    a["security_groups"][0]["IpPermissions"][0]["IpRanges"].append({"CidrIp": "0.0.0.0/0"})


def _monitor(a: Dict[str, Any]) -> None:
    prefix = _load("sdv_stack_attribution_under_test", REPO / "sdv" / "stack" / "attribution.py").MONITOR_PREFIX
    a["things"][THING]["shadows"]["vss"]["state"]["reported"][prefix + "Anything"] = 1


@pytest.mark.parametrize("change,check", [
    (lambda a: a.update(account_block=dict(a["account_block"], BlockPublicPolicy=False)), "account-level Block Public Access"),
    (lambda a: a["buckets"]["%s-telemetry-%s" % (PREFIX, SUFFIX)].update(public=True), "the bucket's policy status"),
    (_open, "security groups"),
    (lambda a: a["security_groups"][0]["IpPermissions"][0]["IpRanges"].append({"CidrIp": "203.0.113.8/32"}), "security groups"),
    (lambda a: a.update(authorizers=[{"authorizerName": "x"}]), "IoT authorizers"),
    (lambda a: a.update(domains=[{"domainConfigurationName": "x"}]), "IoT domain configurations"),
    (lambda a: a.update(pools=[{"IdentityPoolId": "x"}]), "Cognito identity pools"),
    (lambda a: a["functions"][PREFIX + "-breaker"]["urls"].append({"AuthType": "NONE"}), "the function: no URL, one statement per breaker alarm"),
    (lambda a: a["functions"][PREFIX + "-breaker"]["statements"][0]["Principal"].update(Service="*"),
     "the function: no URL, one statement per breaker alarm"),
    (lambda a: a["rules"][PREFIX + "_telemetry"]["actions"].append({"http": {"url": "https://example.com/"}}), "the rule's actions"),
    (lambda a: a.update(rest_apis=[{"id": "x"}]), "the topic's policy, the roles' trust policies, no API"),
    (lambda a: a["roles"][ROLE]["trust"]["Statement"][0].update(Principal={"AWS": "*"}), "the topic's policy, the roles' trust policies, no API"),
    (lambda a: a["buckets"]["%s-telemetry-%s" % (PREFIX, SUFFIX)]["objects"].append("elsewhere/x"), "the bucket's top-level prefixes"),
    (lambda a: a["buckets"]["%s-telemetry-%s" % (PREFIX, SUFFIX)]["objects"].append("loose"), "the bucket's top-level prefixes"),
    (lambda a: a["things"][THING]["shadows"]["vss"]["state"].update(reported={}), "S11: the shadows' keys"),
    (lambda a: a["things"][THING]["shadows"]["vss"]["state"]["reported"].update({"Vehicle.NotOnTheList": 1}), "S11: the shadows' keys"),
    (_monitor, "S11: the shadows' keys"),
    (lambda a: a["things"][THING]["shadows"]["config"]["state"]["reported"]["paths"].append("Vehicle.NotOnTheList"), "S11: the shadows' keys"),
])
def test_exit_checks_fails_on_each_public_path_and_on_a_key_outside_the_allowlist(twin: Rig, tmp_path: Path, change: Any, check: str) -> None:
    live(twin)
    twin.edit(change)
    ran = twin.run("exit-checks", "--capture", tmp_path / "capture", expect=1)
    failed = [line.split(None, 1)[1] for line in ran.out.split("\n") if line.startswith("  FAIL ")]
    assert len(failed) == 1 and failed[0].startswith(check), ran.out
    assert "not-run  S11: Athena's distinct paths" in ran.out and not clean(ran.text)                # not given: that is not a pass either


# ================================================================================================= after the first re-check (WP6-verify-1)

def calls_of(rig: Rig) -> List[Any]:
    return [TW.Call(c[0], c[1], tuple(c[2:]), False) for c in every_call(rig)]


def test_every_call_plan_lists_is_allowed_by_the_operator_roles_policy_and_denied_by_no_statement(planned: Rig) -> None:
    """The owner makes the operator role by hand from this render (A1 row 3): a call of the driver that the role does not
    let through costs a second pass through the console. Judged by the action's name and by the conditions a call
    itself settles; resources are not matched, and every action name is from memory, as the template's own are."""
    doc = planned.doc("operator-role", "operator-role-policy")
    calls = calls_of(planned)
    assert len({(c.service, c.op) for c in calls}) > 95
    assert TW.operator_gaps(doc, calls) == []
    # the Deny the first render had: every Cognito action, the exit's own read among them
    wide = copy.deepcopy(doc)
    _allow(wide, "DenyPublicPaths")["Action"].append("cognito-identity:*")
    assert TW.operator_gaps(wide, calls) == [
        "cognito-identity:ListIdentityPools (cognito-identity list-identity-pools) is denied by the statement DenyPublicPaths"]
    # an action no statement allows: the read the first render lacked
    short = copy.deepcopy(doc)
    _allow(short, "Function")["Action"].remove("lambda:GetFunctionConcurrency")
    assert TW.operator_gaps(short, calls) == ["lambda:GetFunctionConcurrency (lambda get-function-concurrency) is allowed by no statement"]
    # a statement with a condition is judged by what the call itself says: a subscription that is not e-mail, a grant to
    # another principal than the alarms', a role passed to another service than its statement's
    sms = TW.W("sns", "subscribe", "--topic-arn", "x", "--protocol", "sms", "--notification-endpoint", "y")
    assert TW.operator_gaps(doc, [sms]) == ["sns:Subscribe (sns subscribe) is denied by the statement DenySubscriptionsThatAreNotEmail"]
    grant = TW.W("lambda", "add-permission", "--function-name", "f", "--statement-id", "s", "--action", "lambda:InvokeFunction", "--principal",
                 "events.amazonaws.com")
    assert TW.operator_gaps(doc, [grant]) == [
        "lambda:AddPermission (lambda add-permission) is denied by the statement DenyInvokeGrantsToAnyoneButTheAlarms"]
    no_lambda = copy.deepcopy(doc)
    no_lambda["Statement"].remove(_allow(no_lambda, "PassTheBreakerRole"))
    assert TW.operator_gaps(no_lambda, calls) == ["iam:PassRole (lambda create-function) is allowed by no statement"]
    # what a call needs beside the action of its own name: the bucket's ownership, the tags, the role it passes
    assert TW.iam_actions(TW.W("s3api", "create-bucket", "--bucket", "b", "--object-ownership", "BucketOwnerEnforced")) == (
        "s3:CreateBucket", "s3:PutBucketOwnershipControls")
    assert TW.iam_actions(TW.W("lambda", "create-function", "--function-name", "f", "--role", "r", "--tags", "t")) == (
        "lambda:CreateFunction", "lambda:TagResource", "iam:PassRole")
    assert TW.iam_actions(TW.W("firehose", "create-delivery-stream", "--delivery-stream-name", "s", "--tags", "t")) == (
        "firehose:CreateDeliveryStream", "firehose:TagDeliveryStream", "iam:PassRole")
    assert TW.iam_actions(TW.R("sts", "get-caller-identity")) == ()
    assert TW.iam_actions(TW.R("s3api", "list-objects-v2", "--bucket", "b")) == ("s3:ListBucket",)
    assert TW.iam_actions(TW.R("s3control", "get-public-access-block", "--account-id", "a")) == ("s3:GetAccountPublicAccessBlock",)
    assert TW.iam_actions(TW.R("iot-data", "list-named-shadows-for-thing", "--thing-name", "t")) == ("iot:ListNamedShadowsForThing",)
    assert TW.iam_actions(TW.R("apigatewayv2", "get-apis")) == ("apigateway:GET",)
    assert TW.iam_actions(TW.W("lambda", "invoke", "--function-name", "f")) == ("lambda:InvokeFunction",)
    # a call nobody mapped is no pass
    assert TW.operator_gaps(doc, [TW.R("kms", "list-keys")]) == ["kms:ListKeys (kms list-keys) is allowed by no statement"]


def test_plan_fails_when_the_operator_roles_policy_does_not_let_a_call_of_the_driver_through(rig: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                             tmp_path: Path) -> None:
    """The template and the driver's second copy of its actions agree with each other, and the exit's own read is denied
    all the same: the first render's mistake, which only the calls themselves show."""
    tampered(monkeypatch, tmp_path, "operator-role-policy", lambda d: _allow(d, "DenyPublicPaths")["Action"].append("cognito-identity:*"))
    monkeypatch.setitem(TW.DENIES, "operator-role-policy", TW.OPERATOR_DENY + ("cognito-identity:*",))
    ran = rig.run("plan", "--no-cli", expect=1)
    assert ("the operator role's policy: cognito-identity:ListIdentityPools (cognito-identity list-identity-pools) is denied by the "
            "statement DenyPublicPaths") in ran.err
    assert "1 gap(s) in the operator role's policy" in ran.out and rig.log() == [] and not clean(ran.text)


def denied(call: str) -> Dict[str, Any]:
    return {"service": call.split()[0], "op": call.split()[1], "code": "AccessDeniedException", "times": 99}


def test_status_makes_its_two_assertions_although_another_read_is_denied(twin: Rig) -> None:
    other = hashlib.sha256(b"a certificate added later").hexdigest()
    twin.edit(lambda a: (a["certs"].update({other: {"status": "ACTIVE", "policies": []}}),
                         a["faults"].append(denied("lambda get-function-concurrency"))))
    ran = twin.run("status", expect=1)
    assert "refused: read-failed" not in ran.err
    assert "FAIL: 1 ACTIVE certificate(s) of the account are outside the twin's set" in ran.err
    assert "ok: the function's environment names exactly the twin's 1 certificate(s)" in ran.out
    assert "the function's reserved concurrency: not read (read-failed)" in ran.out and not clean(ran.text)
    # the stop still shows its status under the same denial
    ran = twin.run("trip", expect=1)
    assert "trip: the function ran" in ran.out and "traffic: the rule is DISABLED" in ran.out
    assert "FAIL: 1 ACTIVE certificate(s) of the account are outside the twin's set" in ran.err
    # a read an assertion itself stands on, denied: the assertion FAILS, it is not passed over
    twin.edit(lambda a: (a["certs"].pop(other), a["faults"].clear(), a["faults"].append(denied("iot list-certificates"))))
    ran = twin.run("status", expect=1)
    assert "FAIL: the account's certificates could not be listed (read-failed: " in ran.err and "ok: the function's environment" in ran.out
    twin.edit(lambda a: (a["faults"].clear(), a["faults"].append(denied("lambda get-function"))))
    ran = twin.run("status", expect=1)
    assert "FAIL: the function could not be read (read-failed: " in ran.err and "ok: no ACTIVE certificate" in ran.out


def test_a_state_refuses_every_command_under_other_names_than_the_ones_it_was_made_under(rig: Rig, tmp_path: Path) -> None:
    """A state records that a step was made, and under which names: with another suffix in the environment the same
    redacted render would send the delete to a bucket this state never made (WP6-verify-1, f04)."""
    rig.go("apply", "bucket")
    mine = "%s-telemetry-%s" % (PREFIX, SUFFIX)
    suffix = j("zz9zz9", "zz9zz9")
    other = "%s-telemetry-%s" % (PREFIX, suffix)
    rig.edit(lambda a: a["buckets"].update({other: dict(a["buckets"][mine], objects=[])}))          # a bucket of another name, never made here
    kept = {name: (rig.state / name).read_bytes() for name in ("state.json", "literals.json", "baseline.json")}
    names = json.loads(kept["state.json"].decode("ascii"))["names"]
    assert sorted(names) == ["TWIN_ACCOUNT", "TWIN_BUCKET_SUFFIX", "TWIN_NOTICE", "TWIN_OPERATOR_ROLE", "TWIN_PREFIX", "TWIN_PROFILE",
                             "TWIN_REGION", "TWIN_THING"]
    assert all(re.fullmatch(r"[0-9a-f]{32}", v) for v in names.values()) and len(set(names.values())) == 8     # salted fingerprints, no name
    calls = len(rig.log())
    commands = (["status"], ["literals"], ["plan", "--no-cli"], ["apply", "bucket"], ["teardown", "bucket"], ["teardown"], ["verify-gone"],
                ["baseline", "--again"], ["restore"], ["trip"], ["exit-checks", "--capture", str(tmp_path / "capture")])
    another = j("anothertwin", "zz")
    changes = (({"TWIN_BUCKET_SUFFIX": suffix}, "TWIN_BUCKET_SUFFIX"),
               ({"TWIN_PREFIX": another, "TWIN_THING": another + "-thing"}, "TWIN_PREFIX, TWIN_THING"),
               ({"TWIN_REGION": "eu-central-1"}, "TWIN_REGION"), ({"TWIN_ACCOUNT": "123456789012"}, "TWIN_ACCOUNT"))
    # every command but trip: since the owner's A4 answers of 2026-10-16 another suffix no longer ends a trip (its own test)
    for env, keys in changes:
        for argv in ([c for c in commands if c != ["trip"]] if keys == "TWIN_BUCKET_SUFFIX" else commands[:5]):
            ran = rig.run(*argv, env=env, expect=1)
            assert "refused: names-changed:" in ran.err and "(%s; no value is printed)" % keys in ran.err, (keys, argv)
            assert not [v for v in list(env.values()) + list(IDENTIFIERS) if v in ran.text], (keys, argv)
    assert len(rig.log()) == calls and set(rig.account()["buckets"]) == {mine, other}
    assert {name: (rig.state / name).read_bytes() for name in kept} == kept
    # the same from the names file itself, not only from the environment
    rig.write_names(TWIN_BUCKET_SUFFIX=suffix)
    assert "refused: names-changed:" in rig.run("teardown", "bucket", expect=1).err
    rig.write_names()
    # the rehearsal's state is bound like the twin's
    rig.go("apply", "thing", "--rehearsal")
    ran = rig.run("--rehearsal", "teardown", "thing", env={"TWIN_PREFIX": another, "TWIN_THING": another + "-thing"}, expect=1)
    assert "refused: names-changed:" in ran.err and list(rig.account()["things"]) == [PREFIX + "rh-thing"]
    rig.go("teardown", "thing", "--rehearsal")
    # under its own names the step goes as before, and the other bucket is not touched
    rig.go("teardown", "bucket")
    assert set(rig.account()["buckets"]) == {other}
    # nothing stands any more: now the names may change. `literals`, then a new baseline, take them; until then nothing else runs
    env = {"TWIN_BUCKET_SUFFIX": suffix}
    ran = rig.run("plan", "--no-cli", env=env, expect=1)
    assert "refused: names-changed:" in ran.err and "twinctl baseline --again" in ran.err
    rig.run("literals", env=env, expect=0)
    assert "refused: names-changed:" in rig.run("plan", "--no-cli", env=env, expect=1).err
    rig.run("baseline", "--again", env=env, expect=0)
    rig.run("plan", "--no-cli", env=env, expect=0)
    assert json.loads((rig.state / "state.json").read_text(encoding="utf-8"))["steps"] == {}        # under new names no step is recorded
    # and from then on the old names are the other names
    ran = rig.run("status", expect=1)
    assert "refused: names-changed:" in ran.err and "(TWIN_BUCKET_SUFFIX; no value is printed)" in ran.err


def test_an_approval_lets_one_run_of_its_calls_through_and_the_render_is_printed_again_before_the_next(rig: Rig) -> None:
    """Create, delete, create (rows 3, 4 and 13) is three approved steps: the second create's render is the first's, and
    so is its hash, so the hash alone cannot tell the two approvals apart. One printing lets one run through."""
    first = rig.shown("apply", "thing")
    rig.run("apply", "thing", "--approve", "thing:" + first, expect=0)
    made = rig.writes()
    # reading once more with the same approval is no second run: nothing is sent
    assert "already made, nothing was created" in rig.run("apply", "thing", "--approve", "thing:" + first, expect=0).out and rig.writes() == made
    gone = rig.shown("teardown", "thing")
    rig.run("teardown", "thing", "--approve", "thing:" + gone, expect=0)
    made = rig.writes()
    ran = rig.run("apply", "thing", "--approve", "thing:" + first, expect=1)
    assert "refused: approval-spent:" in ran.err and rig.writes() == made and rig.account()["things"] == {}
    assert rig.shown("apply", "thing") == first                     # the same render and the same hash, printed again
    rig.run("apply", "thing", "--approve", "thing:" + first, expect=0)
    assert list(rig.account()["things"]) == [THING]
    # a teardown's approval likewise
    made = rig.writes()
    ran = rig.run("teardown", "thing", "--approve", "thing:" + gone, expect=1)
    assert "refused: approval-spent:" in ran.err and rig.writes() == made and list(rig.account()["things"]) == [THING]
    # an approval that was refused before anything was sent is not spent
    bucket = rig.shown("apply", "bucket")
    session = rig.account()["identity"]
    rig.edit(lambda a: a.update(identity={"UserId": "x", "Arn": j("arn:aws:iam::", ACCOUNT, ":user/example-user")}))
    assert "refused: identity-not-the-operator-role:" in rig.run("apply", "bucket", "--approve", "bucket:" + bucket, expect=1).err
    rig.edit(lambda a: a.update(identity=session))
    rig.run("apply", "bucket", "--approve", "bucket:" + bucket, expect=0)
    events = [json.loads(line)["event"] for line in (rig.state / "approvals.jsonl").read_text(encoding="utf-8").split("\n") if line.strip()]
    assert events[-3:] == ["shown", "used", "spent"]                # printed; refused for the caller (no record); given again and let through


def test_an_action_runs_once_per_approval(twin: Rig) -> None:
    """One state change, one invoke: an alarm's test given twice with one approval tripped twice (WP6-verify-1, f06)."""
    for step, call in (("alarm-test-bytes", ["cloudwatch", "set-alarm-state"]), ("dry-trip", ["lambda", "invoke"])):
        digest = twin.shown("apply", step)
        since = len(twin.log())
        twin.run("apply", step, "--approve", "%s:%s" % (step, digest), expect=0)
        ran = twin.run("apply", step, "--approve", "%s:%s" % (step, digest), expect=1)
        assert "refused: approval-spent:" in ran.err and [c[:2] for c in twin.writes(since)] == [call], step
    assert twin.account()["alarm_invokes"] == 6
    spent = [json.loads(line)["event"] for line in (twin.state / "approvals.jsonl").read_text(encoding="utf-8").split("\n") if line.strip()]
    assert spent[-8:] == ["shown", "used", "spent", "used"] * 2      # given twice, let through once


@pytest.mark.parametrize("call,marker,argv", [
    # the three listings the CLI does not page by itself (its own paginator data, 2.35.1): the driver gets one page
    ("firehose list-delivery-streams", {"HasMoreDeliveryStreams": True}, ["verify-gone"]),
    ("athena list-work-groups", {"NextToken": "more"}, ["verify-gone"]),
    ("iot-data list-named-shadows-for-thing", {"nextToken": "more"}, ["teardown", "thing"]),
    # and any other read that says so
    ("iot list-certificates", {"nextMarker": "more"}, ["status"]),
    ("glue get-databases", {"NextToken": "more"}, ["baseline", "--again"]),
    ("s3api list-buckets", {"ContinuationToken": "more"}, ["baseline", "--again"]),
])
def test_a_listing_that_says_there_is_more_is_not_taken_for_the_whole_listing(rig: Rig, call: str, marker: Dict[str, Any], argv: List[str]) -> None:
    assert "verify-gone: gone" in rig.run("verify-gone", expect=0).out          # the tag query's empty token is no marker
    if argv[0] == "teardown":
        rig.go("apply", "thing")
    baseline = (rig.state / "baseline.json").read_bytes()
    rig.edit(lambda a: a.update(reply_extra={call: marker}))
    writes = rig.writes()
    ran = rig.go(*argv, expect=1) if argv[0] == "teardown" else rig.run(*argv, expect=1)
    assert "listing-incomplete" in ran.err and list(marker)[0] in ran.err and "verify-gone: gone" not in ran.text, ran.text
    assert rig.writes() == writes and (rig.state / "baseline.json").read_bytes() == baseline and not clean(ran.text)


def test_a_baseline_is_not_taken_again_while_either_set_stands(rig: Rig) -> None:
    """One baseline serves both states: taken again while the rehearsal's set stands, it would hold the rehearsal's names,
    and the listings' part of its `verify-gone` could no longer see a leftover."""
    rig.go("apply", "thing", "--rehearsal")
    before = (rig.state / "baseline.json").read_bytes()
    ran = rig.run("baseline", "--again", expect=1)
    assert "refused: baseline-too-late:" in ran.err and (rig.state / "baseline.json").read_bytes() == before
    rig.go("teardown", "thing", "--rehearsal")
    rig.run("baseline", "--again", expect=0)
    rig.go("apply", "thing")
    assert "refused: baseline-too-late:" in rig.run("--rehearsal", "baseline", "--again", expect=1).err


def test_an_approvals_file_with_a_cut_line_stops_nothing_and_the_next_record_starts_on_a_line_of_its_own(rig: Rig) -> None:
    thing = rig.shown("apply", "thing")
    path = rig.state / "approvals.jsonl"
    cut = '{"step": "bucket", "mode": "apply", "ha'
    path.write_text(path.read_text(encoding="utf-8") + cut, encoding="utf-8")          # a write that was interrupted
    bucket = rig.shown("apply", "bucket")
    rig.run("apply", "bucket", "--approve", "bucket:" + bucket, expect=0)
    rig.run("apply", "thing", "--approve", "thing:" + thing, expect=0)
    assert cut in path.read_text(encoding="utf-8").split("\n") and not (rig.state / "twinctl-error.log").exists()
    # a line that cannot be read can only fail to match: it is no approval
    gone = rig.shown("teardown", "thing")
    path.write_text("not json at all\n[1, 2]\n" + '"shown"\n', encoding="utf-8")
    assert "refused: approval-never-shown:" in rig.run("teardown", "thing", "--approve", "thing:" + gone, expect=1).err
    assert list(rig.account()["things"]) == [THING]


BY_HAND = ("aws iot disable-topic-rule --rule-name <RULE>", "aws iot update-certificate --certificate-id <CERT_ID> --new-status INACTIVE",
           "aws iot-data delete-connection --client-id <THING>", "aws iot detach-policy --policy-name <POLICY> --target <the certificate's ARN>")


def test_trip_is_not_stopped_by_a_literals_file_that_is_behind_or_gone_or_by_a_state_that_cannot_be_read(twin: Rig) -> None:
    """The one-command stop shared every refusal of the load: stopping is the safe direction, so it goes on with what it
    has, says what it lacked, and writes nothing over it."""
    path = twin.state / "literals.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["literals"].pop("certificate-id")
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert "refused: literals-behind:" in twin.run("status", expect=1).err
    since = len(twin.log())
    ran = twin.run("trip", expect=0)
    assert [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and "trip: the function ran" in ran.out
    assert "traffic: the rule is DISABLED" in ran.out and "the literals file is missing or behind (literals-behind)" in ran.err
    assert not clean(ran.text) and "certificate-id" not in json.loads(path.read_text(encoding="utf-8"))["literals"]
    masked = TW.OUT.clean("%s and %s" % (THING, CERT_1))            # the redactor that run printed with: the names' and the state's own values
    assert THING not in masked and PREFIX not in masked and CERT_1 not in masked
    path.unlink()
    since = len(twin.log())
    ran = twin.run("trip", expect=0)
    assert [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and "(literals-refused)" in ran.err and not clean(ran.text)
    assert not path.exists()                                        # the stop writes no literals file: `twinctl literals` does
    twin.run("literals", expect=0)
    # a state that cannot be read: the invoke goes by the names file alone, and the state is not written over
    whole = (twin.state / "state.json").read_bytes()
    cut = whole[:len(whole) // 2]
    (twin.state / "state.json").write_bytes(cut)
    assert "refused: state-unreadable:" in twin.run("status", expect=1).err
    since = len(twin.log())
    ran = twin.run("trip", expect=1)                                # it stopped; what it says of the certificates stands on no state, and FAILS
    assert [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and "trip: the function ran" in ran.out
    assert "the state cannot be read (state-unreadable)" in ran.err and "traffic: the rule is DISABLED" in ran.out
    assert (twin.state / "state.json").read_bytes() == cut and not clean(ran.text)
    (twin.state / "state.json").write_bytes(whole)
    # a trip that IS refused (a key nobody knows; a key in no form twinctl takes) says the manual stop's four calls by hand. Another
    # suffix than the state's was the second case until the owner's A4 answers of 2026-10-16: it ends a trip no more
    for env in ({"TWIN_PREFFIX": "x"}, {"TWIN_NOTICE": "2"}):
        since = len(twin.log())
        ran = twin.run("trip", env=env, expect=1)
        assert twin.log()[since:] == [] and "refused: names-" in ran.err and not clean(ran.text)
        for line in BY_HAND:
            assert line in ran.err, line
    # and no other command's refusal does
    assert BY_HAND[0] not in twin.run("status", env={"TWIN_PREFFIX": "x"}, expect=1).err


def test_a_step_that_stands_from_another_render_says_so_and_does_not_say_apply_again(twin: Rig) -> None:
    """Row 19's "the alarm made again": another ActionType, or another threshold, is another render of a step that stands."""
    twin.write_names(TWIN_FAILURE_ACTION_TYPE="Lambda")
    since = len(twin.log())
    ran = twin.go("apply", "alarms", expect=1)
    assert "already made, and what is read back is not the render" in ran.err and "the alarm failure is not the render" in ran.err
    assert "this render is not the one the step was made from" in ran.err and "apply again with the same approval" not in ran.err
    assert twin.writes(since) == []
    # a step that only waits (a subscription to confirm, a stream still being created) is told to read again, as before
    twin.write_names()
    twin.edit(lambda a: a["topics"][list(a["topics"])[0]]["subscriptions"][0].update(confirmed=False))
    ran = twin.go("apply", "notice-topic", expect=1)
    assert "apply again with the same approval reads it once more" in ran.err and "this render is not the one" not in ran.err


# ================================================================================================= after the hard review and WP6-verify-2

OTHER_ACCOUNT = "123456789012"                  # the documentation account: another one than the twin's
PROFILE_2 = j("example", "-second", "-zz")
ROLE_2 = j("example", "-second-role", "-zz")
CERT_2 = hashlib.sha256(b"stub certificate 2").hexdigest()      # what the stub gives its second certificate
OTHER_SOURCE = BREAKER_SOURCE + b"# built again\n"                # the same function with one more line: as after an edit of breaker.py
ANOTHER_ZIP = TW.zip_bytes(OTHER_SOURCE)                           # ... and its build: other bytes, another CodeSha256


def other_account(a: Dict[str, Any]) -> None:
    """The profile answers for another account: the same role's name there, as a profile repointed by hand would."""
    a.update(identity={"UserId": "x", "Account": OTHER_ACCOUNT, "Arn": j("arn:aws:sts::", OTHER_ACCOUNT, ":assumed-role/", ROLE, "/session")})


def state_of(rig: Rig) -> Dict[str, Any]:
    return dict(json.loads((rig.state / "state.json").read_text(encoding="utf-8")))


def status_of(rig: Rig, step: str) -> str:
    return str(state_of(rig)["steps"].get(step, {}).get("status", "absent"))


def forget(rig: Rig, fact: str) -> str:
    """The state without one fact a reply gave it, as a state.json put back from an older copy would be."""
    state = state_of(rig)
    value = state["facts"].pop(fact)
    (rig.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return str(value)


def standing_down_to(rig: Rig, last: str) -> List[str]:
    """The steps that stand, in teardown's order, down to `last`."""
    out = []
    for step in teardown_ids(rig):
        if status_of(rig, step) in TW.OURS:
            out.append(step)
        if step == last:
            break
    return out


@pytest.fixture(scope="module")
def attached(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """The table applied up to the two attachments (rows 1 to 8), without the notice. Tests work on a copy."""
    return Rig(tmp_path_factory.mktemp("attached") / "twin", notice=False).build(until="glue")


def test_every_command_that_sends_a_call_reads_the_callers_identity_first_and_refuses_another_account(twin: Rig, rig: Rig,
                                                                                                       tmp_path: Path) -> None:
    """The hard review's SHOULD 1. With the profile answering for another, empty account, `verify-gone` said gone on
    that account's listings while the twin stood, `status` passed both assertions on it, `exit-checks` passed its
    checks on it, and `trip` invoked its function of the twin's name."""
    bucket = "%s-telemetry-%s" % (PREFIX, SUFFIX)
    twin.edit(lambda a: a["buckets"][bucket].update(objects=["telemetry/dt=2026-01-01/a"]))
    trips = twin.account()["trips"]
    twin.edit(other_account)
    ran = Ran(0, "", "")
    for argv in (["verify-gone"], ["verify-gone", "bucket"], ["status"], ["restore"], ["exit-checks", "--capture", str(tmp_path / "capture")],
                 ["apply", "rule-role"], ["teardown", "bucket-objects"], ["trip"]):
        since = len(twin.log())
        ran = twin.run(*argv, expect=1)
        assert "refused: identity-other-account:" in ran.err, argv
        assert [e["argv"][:2] for e in twin.log()[since:]] == [["sts", "get-caller-identity"]], argv     # and nothing after that read
        assert "verify-gone: gone" not in ran.text and "ok: no ACTIVE certificate" not in ran.text and not clean(ran.text), argv
    for line in BY_HAND:                                             # the stop that was refused still says the four calls
        assert line in ran.err, line
    assert twin.account()["trips"] == trips and not (tmp_path / "capture").exists()
    # another role of the twin's own account: the reads are held to the operator role like the writes
    twin.edit(lambda a: a.update(identity={"UserId": "x", "Arn": j("arn:aws:sts::", ACCOUNT, ":assumed-role/another-role/session")}))
    for argv in (["verify-gone"], ["status"], ["restore"]):
        since = len(twin.log())
        ran = twin.run(*argv, expect=1)
        assert "refused: identity-not-the-operator-role:" in ran.err and len(twin.log()) == since + 1, argv
    # the stop is held to the account alone: whoever may invoke the function may stop the twin
    since = len(twin.log())
    ran = twin.run("trip", expect=0)
    assert twin.log()[since]["argv"][:2] == ["sts", "get-caller-identity"] and [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]]
    assert twin.account()["trips"] == trips + 1 and "traffic: the rule is DISABLED" in ran.out
    # and an identity that cannot be read does not stop the stop: it goes on, and says so
    twin.edit(lambda a: a["faults"].append({"service": "sts", "op": "get-caller-identity", "code": "Throttling"}))
    since = len(twin.log())
    ran = twin.run("trip", expect=0)
    assert "trip: the caller's identity could not be read (read-failed)" in ran.err and twin.account()["trips"] == trips + 2
    assert [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and not clean(ran.text)
    # a baseline of another account's listings is not stored, and a step recorded as deleted is not "read, not found" there
    rig.go("apply", "thing")
    rig.go("teardown", "thing")
    baseline = (rig.state / "baseline.json").read_bytes()
    rig.edit(other_account)
    for argv in (["baseline", "--again"], ["teardown", "thing"]):
        since = len(rig.log())
        ran = rig.run(*argv, expect=1)
        assert "refused: identity-other-account:" in ran.err and len(rig.log()) == since + 1, argv
    assert (rig.state / "baseline.json").read_bytes() == baseline


def test_the_runner_sends_no_call_before_the_callers_identity_was_read(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The last line behind a command that forgot the read: the runner itself sends nothing but the identity's read."""
    aws = stub_runner(rig, monkeypatch)
    with pytest.raises(TW.TwinError) as e:
        aws.read(TW.R("iot", "list-things"))
    assert e.value.name == "caller-not-read" and rig.log() == []
    assert aws.read(TW.c_identity())["Account"] == ACCOUNT and len(rig.log()) == 1
    with pytest.raises(TW.TwinError):                               # the read alone does not open the runner: the command's check does
        aws.read(TW.R("iot", "list-things"))
    aws.identified()
    assert aws.read(TW.R("iot", "list-things")) == {"things": []}


def test_trip_does_not_need_the_replies_directory_to_be_there(twin: Rig) -> None:
    """WP6-verify-2's NIT 3 (f16): the invoke's output file lies in <state>/replies, which was made after the call."""
    shutil.rmtree(str(twin.state / "replies"))
    twin.edit(lambda a: a["faults"].append({"service": "sts", "op": "get-caller-identity", "code": "Throttling", "times": 99}))
    ran = twin.run("trip")
    assert "trip: the function ran" in ran.out and "traffic: the rule is DISABLED" in ran.out and "the invoke failed" not in ran.err


def test_a_teardown_whose_render_stands_on_a_value_the_state_lost_is_refused_and_nothing_is_recorded_deleted(attached: Rig, twin: Rig,
                                                                                                             tmp_path: Path) -> None:
    """The hard review's SHOULD 2 (c04, c09). With the certificate's id gone from the state, `teardown attachments`
    printed two detach calls on the placeholder with their target masked, sent them, and recorded the step as deleted
    while the real certificate kept its policy; on the live twin the certificate stayed ACTIVE."""
    half = attached.copy(tmp_path / "half")
    assert forget(half, "certificate_id") == CERT_1
    made = half.writes()
    ran = half.run("teardown", "attachments", expect=1)
    assert "refused: render-provisional:" in ran.err and "(certificate)" in ran.err and "render sha256" not in ran.text
    assert half.writes() == made and status_of(half, "attachments") == "created"
    assert half.account()["certs"][CERT_1]["policies"] == [PREFIX + "-device"] and not clean(ran.text)
    # nor is it "not found" on no read (NIT 2): a step the state records as made is not settled, and stays recorded
    ran = half.run("verify-gone", "attachments", expect=1)
    assert re.search(r"by name +attachments +no read", ran.out) and "not found" not in ran.out
    assert "verify-gone: NOT gone: 1 found by name" in ran.err and status_of(half, "attachments") == "created"
    # the live twin: no step is recorded as deleted on the placeholder, and the certificate is not left ACTIVE behind such a record
    forget(twin, "certificate_id")
    made = twin.writes()
    ran = twin.run("teardown", "go-live-certificate", expect=1)
    assert "refused: render-provisional:" in ran.err and twin.writes() == made and status_of(twin, "go-live-certificate") == "created"
    assert twin.account()["certs"][CERT_1] == {"status": "ACTIVE", "policies": [PREFIX + "-device"]}
    assert "NOT gone" in twin.run("verify-gone", "go-live-certificate", expect=1).err


def test_a_certificate_whose_reply_was_refused_is_torn_down_by_its_id_and_one_with_no_id_is_never_called_deleted(rig: Rig, started: Rig,
                                                                                                                 tmp_path: Path) -> None:
    """The hard review's SHOULD 2 (c05) and NIT 2. The create goes through and its reply is refused: the step is
    `creating` with no id. `teardown certificate` then had no call and no read and still said "deleted; read back, not
    found; recorded", and no command could delete the certificate the account held."""
    # the reply holds an id under an ARN of another region: kept, unconfirmed, for this step's own read and teardown
    elsewhere = j("arn:aws:iot:", "eu-central-1:", ACCOUNT, ":cert/", CERT_1)
    rig.edit(lambda a: a.update(reply_extra={"iot create-certificate-from-csr": {"certificateArn": elsewhere}}))
    ran = rig.go("apply", "certificate", expect=1)
    assert "refused: reply-unreadable:" in ran.err and list(rig.account()["certs"]) == [CERT_1] and not clean(ran.text)
    rig.edit(lambda a: a.pop("reply_extra"))
    state = state_of(rig)
    assert state["steps"]["certificate"]["status"] == "creating" and state["steps"]["certificate"]["done"] == [0]
    assert state["facts"].get("certificate_id_unconfirmed") == CERT_1 and "certificate_id" not in state["facts"]
    assert CERT_1 in json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))["literals"]["certificate-id"]
    # no other step stands on an id that was not confirmed
    assert "refused: render-provisional:" in rig.run("apply", "attachments", expect=1).err
    assert "refused: half-made:" in rig.go("apply", "certificate", expect=1).err
    ran = rig.go("teardown", "certificate")
    assert rig.writes()[-1][:4] == ["iot", "delete-certificate", "--certificate-id", CERT_1] and rig.account()["certs"] == {}
    assert "deleted; read back, not found; recorded" in ran.out and status_of(rig, "certificate") == "deleted"
    assert "certificate_id_unconfirmed" not in state_of(rig)["facts"] and not clean(ran.text)
    ran = rig.run("verify-gone", expect=0)
    assert "verify-gone: gone" in ran.out and re.search(r"by name +certificate +no read", ran.out)
    since = len(rig.log())
    ran = rig.run("teardown", "certificate", expect=0)              # again: nothing is read, and that is what is said
    assert "recorded as deleted; it has no read" in ran.out and "read, not found" not in ran.out and rig.log()[since:] == []
    rig.go("apply", "certificate")
    assert list(rig.account()["certs"]) == [CERT_2] and state_of(rig)["facts"]["certificate_id"] == CERT_2
    # the reply holds no id at all: nothing can be read or deleted, and that is said, not "deleted"
    second = started.copy(tmp_path / "second", logs=False)
    second.edit(lambda a: a.update(reply_extra={"iot create-certificate-from-csr": {"certificateId": "not-an-id"}}))
    assert "refused: reply-unreadable:" in second.go("apply", "certificate", expect=1).err
    second.edit(lambda a: a.pop("reply_extra"))
    made = second.writes()
    ran = second.run("teardown", "certificate", expect=1)
    assert "refused: nothing-to-read:" in ran.err and "render sha256" not in ran.text and "read back, not found" not in ran.text
    assert second.writes() == made and status_of(second, "certificate") == "creating" and len(second.account()["certs"]) == 1
    ran = second.run("verify-gone", expect=1)
    assert re.search(r"by name +certificate +no read", ran.out) and not re.search(r"certificate +not found", ran.out)
    assert "NOT gone: 1 found by name, 1 name(s) the baseline lacks" in ran.err and status_of(second, "certificate") == "creating"
    # no create call went through at all: nothing was made, and the record is taken back, on the listing's word (an answered
    # error does not say that nothing was made: WP7-verify-r1's SHOULD 2) and never as "read back, not found"
    third = started.copy(tmp_path / "third", logs=False)
    third.edit(lambda a: a["faults"].append({"service": "iot", "op": "create-certificate-from-csr", "code": "ThrottlingException"}))
    assert "call 1 of 1 failed" in third.go("apply", "certificate", expect=1).err and status_of(third, "certificate") == "partial"
    made = third.writes()
    ran = third.run("teardown", "certificate", expect=0)
    assert "nothing of it stands: the record is taken back" in ran.out and "read back, not found" not in ran.text
    assert third.writes() == made and status_of(third, "certificate") == "absent"
    third.go("apply", "certificate")
    assert list(third.account()["certs"]) == [CERT_1]


def test_an_approval_printed_under_one_role_and_profile_is_none_under_another(rig: Rig) -> None:
    """The hard review's SHOULD 3 (c06, c06b). The role and the profile were in no hash and bound to no state: after one
    `twinctl literals` under another role and profile, the approval printed under the first let six creates through
    under the second."""
    first = rig.shown("apply", "bucket")
    other = {"TWIN_PROFILE": PROFILE_2, "TWIN_OPERATOR_ROLE": ROLE_2}
    session = j("arn:aws:sts::", ACCOUNT, ":assumed-role/", ROLE_2, "/session")
    rig.edit(lambda a: a.update(profile=PROFILE_2, identity={"UserId": "x", "Arn": session}))          # the account answers for the second
    approve = ["apply", "bucket", "--approve", "bucket:" + first]
    ran = rig.run(*approve, env=other, expect=1)
    assert "refused: names-changed:" in ran.err and "(TWIN_OPERATOR_ROLE, TWIN_PROFILE; no value is printed)" in ran.err
    # nothing stands, so the names may change, by `literals` and a new baseline: the approval of the first does not come along
    rig.run("literals", env=other, expect=0)
    assert "refused: names-changed:" in rig.run(*approve, env=other, expect=1).err
    rig.run("baseline", "--again", env=other, expect=0)
    ran = rig.run(*approve, env=other, expect=1)
    assert "refused: approval-for-another-render:" in ran.err and rig.writes() == [] and rig.account()["buckets"] == {}
    assert not [v for v in (PROFILE_2, ROLE_2) + IDENTIFIERS if v in ran.text]
    # printed under the second, it goes under the second
    rig.extra = dict(other)
    second = rig.shown("apply", "bucket")
    assert second != first
    rig.run("apply", "bucket", "--approve", "bucket:" + second, expect=0)
    assert [e["argv"][e["argv"].index("--profile") + 1] for e in rig.log() if e["w"]] == [PROFILE_2] * 6
    # and with a step standing, not even `literals` takes another role, profile or notice switch
    rig.extra = {}
    for argv in (["literals"], ["status"], ["teardown", "bucket"]):
        ran = rig.run(*argv, expect=1)
        assert "refused: names-changed:" in ran.err and "1 step(s) are recorded as standing" in ran.err, argv
    ran = rig.run("status", env=dict(other, TWIN_NOTICE="0"), expect=1)
    assert "refused: names-changed:" in ran.err and "(TWIN_NOTICE; no value is printed)" in ran.err
    assert sorted(state_of(rig)["names"]) == sorted(TW.BOUND_NAMES) and {"TWIN_OPERATOR_ROLE", "TWIN_PROFILE", "TWIN_NOTICE"} < set(TW.BOUND_NAMES)


def test_a_step_the_state_records_stays_in_the_table_when_its_keys_are_taken_out_of_the_names_file(twin: Rig) -> None:
    """The hard review's NIT 1. Row 19 is a step once its three keys are given, while the twin stands; with the keys taken
    out again after its alarm was made, `teardown rule-count-alarm` was step-unknown, the printed order left it out,
    and `verify-gone` read it by no name."""
    readings = {"TWIN_RULE_COUNT_METRIC": "RulesExecuted", "TWIN_RULE_COUNT_DIMENSIONS": "RuleName=%s_telemetry" % PREFIX,
                "TWIN_RULE_COUNT_READING": "per_execution"}
    assert "rule-count-alarm" not in teardown_ids(twin)
    twin.write_names(**readings)
    twin.go("apply", "rule-count-alarm")
    twin.write_names()
    assert teardown_ids(twin)[0] == "rule-count-alarm"
    made = twin.writes()
    ran = twin.run("teardown", "rule-count-alarm", expect=1)
    assert "refused: input-unset:" in ran.err and "step-unknown" not in ran.err
    ran = twin.run("verify-gone", expect=1)
    assert re.search(r"by name +rule-count-alarm +not read \(input-unset\)", ran.err) and "verify-gone: NOT gone" in ran.err
    assert re.search(r"rule-count-alarm +row 19 +created +not read \(input-unset\)", twin.run("status").out)
    assert "refused: teardown-order:" in twin.run("teardown", "go-live-certificate", expect=1).err and twin.writes() == made
    # with the keys back it is read and torn down, and only then it is no step again
    twin.write_names(**readings)
    twin.go("teardown", "rule-count-alarm")
    twin.write_names()
    assert "rule-count-alarm" not in teardown_ids(twin) and "%s-rule-count" % PREFIX not in twin.account()["alarms"]
    # the notice's switch is a name the state is bound to: the table of a twin made with the topic keeps the topic's steps
    ran = twin.run("teardown", env={"TWIN_NOTICE": "0"}, expect=1)
    assert "refused: names-changed:" in ran.err and "(TWIN_NOTICE; no value is printed)" in ran.err


def test_a_record_does_not_outlive_what_it_stood_on(started: Rig, tmp_path: Path, source_at: Path) -> None:
    """WP6-verify-2's SHOULD 1 (f14, f15). A dry trip, an alarm's test and an owner-made role's reading are records of
    the function, the alarms and the certificate as they were. With the function made again from another zip, go-live
    passed on a breaker that never ran; with the certificate made again, the function was created on a role whose
    policy named the old one."""
    twin = Rig(tmp_path / "twin", notice=False).build(until="go-live-rule")
    actions = ["dry-trip"] + ["alarm-test-" + k for k in BREAKER] + ["reattach-policy"]
    assert {status_of(twin, s) for s in actions + ["function-status"]} == {"done"}
    gone = standing_down_to(twin, "function")
    assert gone[-1] == "function" and "alarms" in gone and "function-policy" in gone
    for step in gone:
        twin.go("teardown", step)
    torn_down = {status_of(twin, s) for s in actions + ["function-status"]}
    rebuilt(twin, source_at, OTHER_SOURCE)                          # a breaker that turned out wrong: its source mended, and built again
    for step in reversed(gone):
        twin.go("apply", step)
    rule, since = PREFIX + "_telemetry", len(twin.log())
    ran = twin.go("apply", "go-live-rule", expect=1)
    assert "refused: step-needs:" in ran.err and "reattach-policy" in ran.err and twin.writes(since) == []
    assert twin.account()["rules"][rule]["ruleDisabled"] is True and twin.account()["certs"][CERT_1]["status"] == "INACTIVE"
    assert {status_of(twin, s) for s in actions + ["function-status"]} == {"stale"}
    assert torn_down == {"stale"}                                   # by the teardown itself, not only once the step was made again
    assert [r for r in twin.said
            if "teardown function: 2 record(s) stood on this step as it was and are taken back (function-status, dry-trip)" in r.out]
    lines = {line.split()[0]: line for line in twin.run("status", expect=0).out.split("\n") if line.startswith("  ")}
    assert re.search(r"dry-trip +row 17a +stale ", lines["dry-trip"])
    # the breaker runs again, on the function that stands now; only then does go-live pass
    for step in actions:
        assert "refused: step-needs:" in twin.go("apply", "go-live-rule", expect=1).err, step
        twin.go("apply", step)
    twin.go("apply", "go-live-rule")
    twin.go("apply", "go-live-certificate")
    assert twin.account()["rules"][rule]["ruleDisabled"] is False and twin.account()["certs"][CERT_1]["status"] == "ACTIVE"
    # f15: the certificate made again, with another id; the role the owner made names the first
    source_at.write_bytes(BREAKER_SOURCE)                           # a rig of its own, with the tree's source and its build
    second = Rig(tmp_path / "second", notice=False).build(until="function")
    assert status_of(second, "breaker-role") == "verified"
    gone = standing_down_to(second, "certificate")
    assert gone[0] == "breaker-log" and gone[-1] == "certificate"
    for step in gone:
        second.go("teardown", step)
    torn_down = {status_of(second, "breaker-role")}
    for step in reversed(gone):
        second.go("apply", step)
    assert list(second.account()["certs"]) == [CERT_2]
    ran = second.go("apply", "function", expect=1)
    assert "refused: step-needs:" in ran.err and "breaker-role" in ran.err and second.account()["functions"] == {}
    assert status_of(second, "breaker-role") == "stale" and torn_down == {"stale"}
    assert [r for r in second.said if "teardown certificate: 1 record(s) stood on this step as it was and are taken back (breaker-role)" in r.out]
    assert "its policy is not the render" in second.run("apply", "breaker-role", expect=1).err
    second.owner_makes("breaker-role")
    second.run("apply", "breaker-role", expect=0)
    second.go("apply", "function")
    variables = second.account()["functions"][PREFIX + "-breaker"]["config"]["Environment"]["Variables"]
    assert variables["TWIN_CERTIFICATE_ARNS"] == iot_arn("cert", CERT_2)
    # a step made anew takes the records back like its teardown does: a state whose teardown of it this driver did not record
    third = started.copy(tmp_path / "third", logs=False)
    state = state_of(third)
    state["steps"]["breaker-role"] = {"status": "verified"}
    (third.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    ran = third.go("apply", "certificate")
    assert "apply certificate: 1 record(s) stood on this step as it was and are taken back (breaker-role)" in ran.out
    assert status_of(third, "breaker-role") == "stale" and status_of(third, "certificate") == "created"


def test_the_salt_gone_is_said_by_its_name_and_has_a_way_back(rig: Rig) -> None:
    """The hard review's NIT 3. Without the salt every name read as another: names-changed with "give those names back"."""
    rig.go("apply", "thing")
    (rig.state / "salt").unlink()
    ran = Ran(0, "", "")
    for argv in (["status"], ["literals"], ["teardown", "thing"], ["trip"]):
        since = len(rig.log())
        ran = rig.run(*argv, expect=1)
        assert "refused: salt-missing:" in ran.err and "names-changed" not in ran.err and len(rig.log()) == since, argv
        assert not (rig.state / "salt").exists(), argv              # no new salt is made behind a state that was bound with the old one
    for line in BY_HAND:
        assert line in ran.err, line
    # the way back the refusal names: the entry `names` out of the state, knowingly; the next write binds it again
    state = state_of(rig)
    state.pop("names")
    (rig.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert "as rendered" in rig.run("status", expect=0).out and (rig.state / "salt").is_file()
    rig.go("teardown", "thing")
    assert sorted(state_of(rig)["names"]) == sorted(TW.BOUND_NAMES) and rig.account()["things"] == {}


def test_a_step_recorded_as_being_deleted_is_not_made_again_before_it_is_recorded_as_deleted(rig: Rig) -> None:
    """The hard review's NIT 4: `apply` on a step recorded `deleting` whose resource was not found made it again at once,
    while the teardown's own message says `verify-gone STEP` comes first."""
    rig.go("apply", "thing")
    state = state_of(rig)
    state["steps"]["thing"]["status"] = "deleting"                  # a teardown whose delete was accepted and had not completed
    (rig.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert "refused: still-deleting:" in rig.go("apply", "thing", expect=1).err
    rig.edit(lambda a: a["things"].clear())                         # it completes
    made = rig.writes()
    ran = rig.go("apply", "thing", expect=1)
    assert "refused: still-deleting:" in ran.err and "verify-gone thing" in ran.err and rig.writes() == made and rig.account()["things"] == {}
    assert "not found" in rig.run("verify-gone", "thing", expect=0).out and status_of(rig, "thing") == "deleted"
    rig.go("apply", "thing")
    assert list(rig.account()["things"]) == [THING]


def test_iots_own_log_group_that_was_there_before_is_adopted_by_the_owners_switch_and_never_created_or_deleted(rig: Rig) -> None:
    """The hard review's NIT 6. The service makes the group of its own fixed name once logging was ever on in the region;
    `apply iot-log-group` then refused it as not ours, for good, and offered the owner no choice."""
    rig.edit(lambda a: a["log_groups"].update({"AWSIotLogsV2": {"streams": []}}))
    ran = rig.go("apply", "iot-log-group", expect=1)
    assert "refused: exists-not-ours:" in ran.err and "TWIN_IOT_LOG_GROUP_ADOPT=1" in ran.err and "delete it by hand" in ran.err
    assert "TWIN_IOT_LOG_GROUP_ADOPT" not in rig.go("apply", "thing").text and rig.writes() == [["iot", "create-thing", "--thing-name", THING]]
    made = rig.writes()
    # the owner's switch: the step is the owner's kind now. It is read and held to the render, and nothing is created
    rig.write_names(TWIN_IOT_LOG_GROUP_ADOPT="1")
    ran = rig.run("apply", "iot-log-group", expect=1)
    assert "its retention is not 30 days" in ran.err and "it is there and is not the render" in ran.err and "render sha256" not in ran.text
    rig.edit(lambda a: a["log_groups"]["AWSIotLogsV2"].update(retention=30))          # the owner sets it by hand
    assert "read, as rendered; recorded" in rig.run("apply", "iot-log-group", expect=0).out and status_of(rig, "iot-log-group") == "verified"
    rig.run("plan", "--no-cli", expect=0)
    step, = [s for s in rig.plan() if s["id"] == "iot-log-group"]
    assert (step["kind"], step["creates"], step["deletes"]) == ("owner", [], [])
    assert [c[:2] for c in step["reads"]] == [["logs", "describe-log-groups"]]
    # never deleted here: no step of the teardown, and said as the owner's
    ran = rig.run("teardown", expect=0)
    assert "iot-log-group" not in teardown_ids(rig) and "was adopted stays, and is the owner's: iot-log-group" in ran.out
    assert "iot-log-group" not in [line for line in ran.out.split("\n") if "the roles made by hand" in line][0]
    assert "refused: step-not-torn-down:" in rig.run("teardown", "iot-log-group", expect=1).err
    assert "refused: step-not-a-resource:" in rig.run("verify-gone", "iot-log-group", expect=1).err    # not ours to call gone on no read
    # the switch taken out again: the record of a step that was only read is no record of something made here
    rig.write_names()
    assert "refused: not-ours:" in rig.run("teardown", "iot-log-group", expect=1).err
    assert "refused: exists-not-ours:" in rig.go("apply", "iot-log-group", expect=1).err
    assert rig.writes() == made and rig.account()["log_groups"] == {"AWSIotLogsV2": {"streams": [], "retention": 30}}
    # with the switch on and no such group there, nothing is adopted and nothing is made
    rig.write_names(TWIN_IOT_LOG_GROUP_ADOPT="1")
    rig.edit(lambda a: a["log_groups"].clear())
    ran = rig.run("apply", "iot-log-group", expect=1)
    assert "it is not there: nothing is adopted" in ran.err and rig.writes() == made
    # and a group the state records as MADE here stays the driver's to delete, whatever the switch says
    rig.write_names()
    state = state_of(rig)
    state["steps"].pop("iot-log-group")
    (rig.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    rig.go("apply", "iot-log-group")
    rig.write_names(TWIN_IOT_LOG_GROUP_ADOPT="1")
    assert "iot-log-group" in teardown_ids(rig)
    rig.go("teardown", "iot-log-group")
    assert rig.account()["log_groups"] == {}


def test_a_path_of_the_names_file_in_git_bashs_form_is_refused_under_windows_python(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hard review's NIT 5. Git Bash converts /e/... on a command line and in the environment, never in a file's text;
    Windows Python then looked for the path on the current drive, and the refusal was input-missing."""
    rig.write_names(TWIN_CSR="/e/device/device.csr")
    monkeypatch.setattr(TW, "WINDOWS", False, raising=False)
    assert "refused: input-missing:" in rig.run("apply", "certificate", expect=1).err         # elsewhere it is a path like any other
    monkeypatch.setattr(TW, "WINDOWS", True, raising=False)
    for argv in (["apply", "certificate"], ["status"], ["plan", "--no-cli"]):
        ran = rig.run(*argv, expect=1)
        assert "refused: names-path-form:" in ran.err and "TWIN_CSR" in ran.err and "X:/" in ran.err and "/e/device" not in ran.text, argv
    rig.write_names(TWIN_CSR="E:/device/device.csr")                # the form that file takes there
    assert "names-path-form" not in rig.run("plan", "--no-cli").err
    example = (REPO / "sdv" / "cloud" / ".env.example").read_text(encoding="utf-8")
    assert "names-path-form" in example and "E:/..." in example and "never as /e/..." in example


# ================================================================================================= with the breaker (WP7's integration)

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def status_lines(ran: Ran) -> Dict[str, str]:
    return {line.split()[0]: line for line in ran.out.split("\n") if line.startswith("  ")}


@pytest.fixture(scope="module")
def before_function(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """The table applied up to the breaker's role (rows 1 to 12), without the notice. Tests work on a copy."""
    return Rig(tmp_path_factory.mktemp("before-function") / "twin", notice=False).build(until="function")


@pytest.fixture
def source_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The breaker's source where the driver reads it, as a file a test may change: it starts as the tree's own."""
    path = tmp_path / "the-source-of-a-test" / "breaker.py"
    path.parent.mkdir()
    path.write_bytes(BREAKER_SOURCE)
    monkeypatch.setattr(TW, "BREAKER_SOURCE", path)
    return path


def rebuilt(rig: Rig, source_at: Path, source: bytes) -> None:
    """The source as `source`, and its build at the zip's path: what an edit of breaker.py and `build-breaker` leave."""
    source_at.write_bytes(source)
    (rig.inputs / "breaker.zip").write_bytes(TW.zip_bytes(source))


def test_an_approval_covers_the_zips_content_and_the_function_is_held_to_the_hash_that_was_approved(before_function: Rig, tmp_path: Path,
                                                                                                    source_at: Path) -> None:
    """WP6's critic, problem 5 (WP6-verify-2's NIT 2, w05). The render named the zip's PATH: with the zip replaced after
    the printing, the first approval created the function from the other zip, and `status` then compared the function
    with whatever lay at the path. (Since the zip is held to the source, 2026-10-12, "another zip" is here what it is
    in the field: the source edited and built again.)"""
    twin = before_function.copy(tmp_path / "twin")
    first = (twin.inputs / "breaker.zip").read_bytes()
    assert first == BREAKER_ZIP
    digest = twin.shown("apply", "function")
    shown = twin.said[-1].out
    rebuilt(twin, source_at, OTHER_SOURCE)                           # replaced after the printing
    since = len(twin.log())
    ran = twin.run("apply", "function", "--approve", "function:" + digest, expect=1)
    assert "refused: approval-for-another-render:" in ran.err and twin.writes(since) == [] and twin.account()["functions"] == {}
    assert "input TWIN_BREAKER_ZIP: sha256 %s" % sha(first) in shown                    # what was printed named the content
    assert base64.b64encode(hashlib.sha256(first).digest()).decode() in shown           # the form the service reports a function's code in
    second = twin.shown("apply", "function")                        # printed again it is another render, with the other hash
    assert second != digest and "sha256 %s" % sha(ANOTHER_ZIP) in twin.said[-1].out
    twin.run("apply", "function", "--approve", "function:" + second, expect=0)
    assert state_of(twin)["steps"]["function"]["inputs"] == {"TWIN_BREAKER_ZIP": sha(ANOTHER_ZIP)}
    # afterwards the function is held to the RECORDED hash, not to whatever lies at the path
    line = status_lines(twin.run("status"))["function"]
    assert "as rendered" in line and "the zip" not in line and "source" not in line
    rebuilt(twin, source_at, BREAKER_SOURCE)                        # the file at the path changed since: said, and no difference of the function
    line = status_lines(twin.run("status"))["function"]
    assert "as rendered" in line and "the zip at its path is not the one it was made from" in line and "DIFFERS" not in line
    # WP7-verify-r1, SHOULD 1. The step that stands, printed and approved AGAIN with that other file at the path: the render
    # that is approved names the other zip, and "already made ... as rendered" would be said of a function that is not it
    since = len(twin.log())
    third = twin.shown("apply", "function")
    assert third != second and "input TWIN_BREAKER_ZIP: sha256 %s" % sha(first) in twin.said[-1].out
    ran = twin.run("apply", "function", "--approve", "function:" + third, expect=1)
    assert "the file TWIN_BREAKER_ZIP names is not the one this step was made from" in ran.err and "as rendered" not in ran.text
    assert "this render is not the one the step was made from" in ran.err and "apply again with the same approval" not in ran.err
    assert twin.writes(since) == [] and status_of(twin, "function") == "created"
    assert state_of(twin)["steps"]["function"]["inputs"] == {"TWIN_BREAKER_ZIP": sha(ANOTHER_ZIP)}       # the recorded hash is unchanged
    assert twin.account()["functions"][PREFIX + "-breaker"]["config"]["CodeSha256"] == base64.b64encode(hashlib.sha256(ANOTHER_ZIP).digest()).decode()
    rebuilt(twin, source_at, OTHER_SOURCE)                          # with the zip it was made from at the path again, it reads as rendered
    assert "already made, nothing was created; read back, as rendered" in twin.go("apply", "function").out
    (twin.inputs / "breaker.zip").unlink()                          # gone: still compared, with what the state records
    line = status_lines(twin.run("status"))["function"]
    assert "as rendered" in line and "the zip is no longer at its path" in line and "cannot be compared" not in line
    name = PREFIX + "-breaker"
    twin.edit(lambda a: a["functions"][name]["config"].update(CodeSha256=base64.b64encode(hashlib.sha256(first).digest()).decode()))
    line = status_lines(twin.run("status"))["function"]
    assert "DIFFERS" in line and "its code is not the zip the state records (CodeSha256 differs)" in line
    assert not clean("".join(r.text for r in twin.said))


NOT_THE_BUILD = "the zip at TWIN_BREAKER_ZIP is NOT the build of the breaker's source as it stands"
SOURCE_CHANGED = "the breaker's source has changed since the build this function was made from"


def test_apply_function_refuses_a_zip_that_is_not_the_build_of_the_source_as_it_stands_and_status_says_when_the_source_changed(
        before_function: Rig, tmp_path: Path, source_at: Path) -> None:
    """WP7's critic, ledger WP7#9 (WP7-verify-final, NOTE 3.5b), DECIDED 2026-10-12. Nothing held the zip at TWIN_BREAKER_ZIP
    to the source: a zip built before breaker.py last changed, or any other zip, was printed with its hash, approved
    and created, and after a fix to breaker.py and no rebuild the account ran the old code with no word anywhere. The
    comparison is of built bytes: what `build-breaker` would write from the source now, against what lies at the path."""
    twin = before_function.copy(tmp_path / "twin")

    def function_events() -> list:
        path = twin.state / "approvals.jsonl"
        return [e for e in (json.loads(x) for x in path.read_text(encoding="utf-8").split("\n") if x) if e["step"] == "function"]

    # breaker.py was changed after the zip was built, and nobody built again
    source_at.write_bytes(OTHER_SOURCE)
    since = len(twin.log())
    ran = twin.run("apply", "function", expect=1)
    assert "refused: zip-not-the-source:" in ran.err and "`twinctl build-breaker`" in ran.err and twin.writes(since) == []
    assert "apply function (row 13)" in ran.out and NOT_THE_BUILD in ran.out                  # the render is printed, and says which it is
    assert "input TWIN_BREAKER_ZIP: sha256 %s" % sha(BREAKER_ZIP) in ran.out
    assert "to go on" not in ran.out and "--approve" not in ran.out and function_events() == []          # nothing to say yes to
    found = HASH.search(ran.out)
    assert found
    ran = twin.run("apply", "function", "--approve", "function:" + found.group(1), expect=1)
    assert "refused: zip-not-the-source:" in ran.err and twin.writes(since) == [] and twin.account()["functions"] == {}
    assert function_events() == [] and status_of(twin, "function") == "absent"
    # with an approval the render is NOT printed again: the run without one printed it, and the refusal on standard error is all
    # there is to say (burst-verify-r1, problem 8, its mutant X09: the code prints an unfit render only when there is no approval)
    assert ran.out == "", ran.out
    # any other zip at the path, with the source as it was: the same
    source_at.write_bytes(BREAKER_SOURCE)
    (twin.inputs / "breaker.zip").write_bytes(ANOTHER_ZIP)
    ran = twin.run("apply", "function", expect=1)
    assert "refused: zip-not-the-source:" in ran.err and NOT_THE_BUILD in ran.out and twin.writes(since) == []
    # the dry run says it of the same step, by the same name
    ran = twin.run("plan", "--no-cli", expect=1)
    assert "REFUSED zip-not-the-source" in status_lines(ran)["function"] and "1 refused for an input that is not there or not fit" in ran.out
    # a source that cannot be built, or is not there, is no source a zip can be the build of
    source_at.write_bytes(BREAKER_SOURCE.replace(b"\n", b"\r\n"))
    (twin.inputs / "breaker.zip").write_bytes(BREAKER_ZIP)
    assert "refused: source-has-a-carriage-return:" in twin.run("apply", "function", expect=1).err
    source_at.unlink()
    assert "refused: source-missing:" in twin.run("apply", "function", expect=1).err and twin.writes(since) == []
    # THE BUILT ZIP IS TAKEN, AND NO SUCH WORD IS PRINTED
    source_at.write_bytes(BREAKER_SOURCE)
    digest = twin.shown("apply", "function")
    assert "NOT the build" not in twin.said[-1].out and "to go on" in twin.said[-1].out
    twin.run("apply", "function", "--approve", "function:" + digest, expect=0)
    assert twin.account()["functions"][PREFIX + "-breaker"]["config"]["CodeSha256"] == base64.b64encode(hashlib.sha256(BREAKER_ZIP).digest()).decode()
    assert twin.run("plan", "--no-cli").rc == 0
    # STATUS: a word beside the function's line when the source has changed since the recorded build, and no failure
    plain = twin.run("status")
    line = status_lines(plain)["function"]
    assert "as rendered" in line and "source" not in line
    source_at.write_bytes(OTHER_SOURCE)
    ran = twin.run("status")
    line = status_lines(ran)["function"]
    assert "as rendered" in line and SOURCE_CHANGED in line and "DIFFERS" not in line and "the zip at its path" not in line
    assert ran.rc == plain.rc and "FAIL" not in ran.text             # the account still runs what was approved
    rebuilt(twin, source_at, OTHER_SOURCE)                          # built again and not yet applied: both words
    line = status_lines(twin.run("status"))["function"]
    assert SOURCE_CHANGED in line and "the zip at its path is not the one it was made from" in line and "as rendered" in line
    rebuilt(twin, source_at, BREAKER_SOURCE)
    assert "source" not in status_lines(twin.run("status"))["function"]
    for unbuildable in (BREAKER_SOURCE.replace(b"\n", b"\r\n"), None):
        if unbuildable is None:
            source_at.unlink()
        else:
            source_at.write_bytes(unbuildable)
        ran = twin.run("status")
        line = status_lines(ran)["function"]
        assert "as rendered" in line and "the breaker's source cannot be built as it stands" in line and ran.rc == plain.rc, unbuildable
    docstring = " ".join(str(TW.__doc__).split())
    assert "refuses a zip that is not the build of the breaker's source as it stands" in docstring
    assert not clean("".join(r.text for r in twin.said))


def test_an_approval_covers_the_content_of_the_signing_request(rig: Rig) -> None:
    """The same for the certificate's signing request: another request under the approved path made another certificate."""
    first = (rig.inputs / "device.csr").read_bytes()
    digest = rig.shown("apply", "certificate")
    shown = rig.said[-1].out
    other = b"another placeholder, written after the printing\n"
    (rig.inputs / "device.csr").write_bytes(other)
    ran = rig.run("apply", "certificate", "--approve", "certificate:" + digest, expect=1)
    assert "refused: approval-for-another-render:" in ran.err and rig.writes() == [] and rig.account()["certs"] == {}
    assert "input TWIN_CSR: sha256 %s" % sha(first) in shown
    second = rig.shown("apply", "certificate")
    assert second != digest and "input TWIN_CSR: sha256 %s" % sha(other) in rig.said[-1].out
    rig.run("apply", "certificate", "--approve", "certificate:" + second, expect=0)
    assert state_of(rig)["steps"]["certificate"]["inputs"] == {"TWIN_CSR": sha(other)} and len(rig.account()["certs"]) == 1
    # WP7-verify-r1, SHOULD 1. The certificate stands; printed and approved AGAIN with another request at the path, it is not
    # "already made ... as rendered": the render that is approved names a request this certificate was not made from
    (rig.inputs / "device.csr").write_bytes(first)
    made = rig.writes()
    third = rig.shown("apply", "certificate")
    assert third != second and "input TWIN_CSR: sha256 %s" % sha(first) in rig.said[-1].out
    ran = rig.run("apply", "certificate", "--approve", "certificate:" + third, expect=1)
    assert "the file TWIN_CSR names is not the one this step was made from" in ran.err and "as rendered" not in ran.text
    assert "this render is not the one the step was made from" in ran.err and "apply again with the same approval" not in ran.err
    assert rig.writes() == made and len(rig.account()["certs"]) == 1 and status_of(rig, "certificate") == "created"
    assert state_of(rig)["steps"]["certificate"]["inputs"] == {"TWIN_CSR": sha(other)}
    # and a state that records no hash for the step cannot say that the file is the one it was made from: no "as rendered"
    (rig.inputs / "device.csr").write_bytes(other)
    assert "already made, nothing was created; read back, as rendered" in rig.go("apply", "certificate").out
    state = state_of(rig)
    del state["steps"]["certificate"]["inputs"]
    (rig.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    ran = rig.go("apply", "certificate", expect=1)
    assert "the state records no hash of the file TWIN_CSR names" in ran.err and "as rendered" not in ran.text and rig.writes() == made
    assert "this render is not the one the step was made from" in ran.err and "apply again with the same approval" not in ran.err
    # the rehearsal's request is its own key
    rehearsal = rig.shown("apply", "certificate", "--rehearsal")
    assert "input TWIN_REHEARSAL_CSR: sha256 %s" % sha(other) in rig.said[-1].out and rehearsal != second
    assert not clean("".join(r.text for r in rig.said))


def test_a_function_whose_step_records_no_hash_of_its_zip_is_not_read_as_rendered(before_function: Rig, tmp_path: Path) -> None:
    """WP7-verify-r1#4 (W05). A state that records no hash of the zip a function was made from (a hand-edited one: every
    state this driver writes records one) cannot say that the code is the approved one. `status` does not read the
    function `as rendered` on that: it says its code cannot be compared."""
    twin = before_function.copy(tmp_path / "twin")
    twin.go("apply", "function")
    assert "as rendered" in status_lines(twin.run("status"))["function"] and "DIFFERS" not in status_lines(twin.said[-1])["function"]
    state = state_of(twin)
    del state["steps"]["function"]["inputs"]
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    line = status_lines(twin.run("status"))["function"]
    assert "DIFFERS" in line and "its code cannot be compared: the state records no hash of the zip it was made from" in line
    assert "as rendered" not in line and "CodeSha256" not in line                  # not a difference of the code either: it is not compared
    assert not clean("".join(r.text for r in twin.said))


def test_plan_records_the_content_hash_of_each_file_a_step_uploads_and_no_other_step_has_one(rig: Rig) -> None:
    """WP7-verify-r1#4 (W07). plan.json says, for the function and for the certificate, the sha256 of the file the render
    names (the zip, the signing request) and for the rehearsal's certificate the rehearsal's own request; no other step
    uploads a file."""
    rig.run("plan", expect=0)
    steps = {s["id"]: s for s in rig.plan()}
    assert (rig.inputs / "breaker.zip").read_bytes() == BREAKER_ZIP
    assert steps["function"]["inputs"] == {"TWIN_BREAKER_ZIP": sha(BREAKER_ZIP)}
    assert steps["certificate"]["inputs"] == {"TWIN_CSR": sha((rig.inputs / "device.csr").read_bytes())}
    assert sorted(step for step, entry in steps.items() if entry["inputs"]) == ["certificate", "function"]
    other = b"another placeholder, written before the plan is made again\n"
    (rig.inputs / "device.csr").write_bytes(other)
    rig.run("plan", expect=0)
    assert {s["id"]: s for s in rig.plan()}["certificate"]["inputs"] == {"TWIN_CSR": sha(other)}
    rig.run("--rehearsal", "plan", "--no-cli", expect=0)
    rehearsal = {s["id"]: s for s in json.loads((rig.render / "rehearsal-plan.json").read_text(encoding="utf-8"))["steps"]}
    assert rehearsal["certificate"]["inputs"] == {"TWIN_REHEARSAL_CSR": sha(other)}
    assert sorted(step for step, entry in rehearsal.items() if entry["inputs"]) == ["certificate"]


def lost(rig: Rig, status: str = "creating", certs: int = 1) -> None:
    """A create of the certificate went through and the state holds no id of what it made: the call is on record, the
    teardown is refused on the listing's word, no second certificate is made on top, and `verify-gone` sees the first."""
    assert len(rig.account()["certs"]) == certs                     # the create went through
    made = rig.writes()
    ran = rig.run("teardown", "certificate", expect=1)
    assert "refused: nothing-to-read:" in ran.err and "the record is taken back" not in ran.text and "render sha256" not in ran.text
    assert status_of(rig, "certificate") == status and rig.writes() == made
    step = state_of(rig)["steps"]["certificate"]
    assert step["sent"] == [0] and step["done"] == [] and "certificate_id" not in state_of(rig)["facts"]
    ran = rig.go("apply", "certificate", expect=1)                  # and no second certificate is made on top of the first
    assert "refused: half-made:" in ran.err and len(rig.account()["certs"]) == certs and rig.writes() == made
    ran = rig.run("verify-gone", expect=1)                          # the listing is what sees it
    assert "NOT gone: 1 found by name, 1 name(s) the baseline lacks" in ran.err and not clean(ran.text)


def test_a_create_whose_reply_is_lost_is_not_taken_back_by_its_teardown(started: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WP6's critic, problem 1 (WP6-verify-final's NIT 1, R2). The create goes through and its reply is lost: a reply that
    is no JSON, a call cut off before it answered, a run that ended there. The step was `creating` with no call recorded,
    so `teardown certificate` took the record back with exit 0 while the account held the certificate, and the next
    `apply certificate` made a second one."""
    # the CLI exits 0 and prints what is no JSON
    garbled = started.copy(tmp_path / "garbled", logs=False)
    garbled.edit(lambda a: a.update(reply_garbage={"iot create-certificate-from-csr": "what a CLI that misbehaves prints"}))
    assert "refused: reply-unreadable:" in garbled.go("apply", "certificate", expect=1).err
    garbled.edit(lambda a: a.pop("reply_garbage"))
    lost(garbled)
    # no reply of the state directory holds the id, so nothing can be put back; what the lost create made is deleted by hand,
    # and the teardown then takes the record back on the word of the one read that can see such a certificate: the listing
    assert "refused: no-reply-to-recover-from:" in garbled.run("recover", "certificate", expect=1).err
    garbled.edit(lambda a: a["certs"].clear())
    since = len(garbled.log())
    ran = garbled.run("teardown", "certificate", expect=0)
    assert "nothing of it stands: the record is taken back" in ran.out and status_of(garbled, "certificate") == "absent"
    assert [e["argv"][:2] for e in garbled.log()[since:]] == [["sts", "get-caller-identity"], ["iot", "list-certificates"]] and not clean(ran.text)
    garbled.go("apply", "certificate")
    assert len(garbled.account()["certs"]) == 1 and status_of(garbled, "certificate") == "created"
    # the call is cut off after the service took it: the CLI does not come to its end
    real = TW.subprocess.run

    def cut(end: Any) -> Any:
        def run(argv: List[str], **kw: Any) -> Any:
            done = real(argv, **kw)
            if "create-certificate-from-csr" in argv and "--generate-cli-skeleton" not in argv:
                raise end
            return done
        return run

    late = started.copy(tmp_path / "late", logs=False)
    digest = late.shown("apply", "certificate")
    with monkeypatch.context() as m:
        m.setattr(TW.subprocess, "run", cut(subprocess.TimeoutExpired(["aws"], 900)))
        assert "refused: cli-failed:" in late.run("apply", "certificate", "--approve", "certificate:" + digest, expect=1).err
    lost(late)
    # the run itself ends there (the process is killed, the power goes): what was sent is on record before it is sent
    killed = started.copy(tmp_path / "killed", logs=False)
    digest = killed.shown("apply", "certificate")
    with monkeypatch.context() as m:
        m.setattr(TW.subprocess, "run", cut(SystemExit(137)))
        with pytest.raises(SystemExit):
            killed.run("apply", "certificate", "--approve", "certificate:" + digest)
    lost(killed)
    # the CLI ends with an error of its own after the service took the call (a reply that never came): no answer of the
    # service says that the call did not go through, so it stays on record as sent. And a certificate that was in the
    # account BEFORE the baseline is nobody's stray: the listing is read less the baseline
    before = hashlib.sha256(b"a certificate that was there before the twin").hexdigest()
    timed = Rig(tmp_path / "timed")
    timed.edit(lambda a: a["certs"].update({before: {"status": "ACTIVE", "policies": []}}))
    timed.start()
    timed.edit(lambda a: a.update(reply_dies={"iot create-certificate-from-csr": 255}))
    assert "call 1 of 1 failed (iot create-certificate-from-csr: exit-255)" in timed.go("apply", "certificate", expect=1).err
    timed.edit(lambda a: a.pop("reply_dies"))
    lost(timed, status="partial", certs=2)
    timed.edit(lambda a: [a["certs"].pop(c) for c in list(a["certs"]) if c != before])       # ours, deleted by hand; the other's stays
    assert "nothing of it stands: the record is taken back" in timed.run("teardown", "certificate", expect=0).out
    assert status_of(timed, "certificate") == "absent" and list(timed.account()["certs"]) == [before]
    docstring = " ".join(str(TW.__doc__).split())
    assert "with none gone through its record is taken back" not in docstring and "a call whose reply was lost" in docstring
    assert "Every create call is on record before it is sent" in docstring


def test_a_create_the_service_answered_with_an_error_stays_on_record_and_the_listing_settles_its_teardown(started: Rig, tmp_path: Path) -> None:
    """WP7-verify-r1, SHOULD 2: what was left of WP6's critic, problem 1. The service takes the call, makes the certificate
    and ANSWERS WITH AN ERROR (a 5xx does not say that nothing was made). The call was taken off the record as one that
    never went through: `teardown certificate` took the record back unread with exit 0 while the account held the
    certificate, and the next `apply certificate` made a second one. No error code is trusted to say "nothing was made":
    every create call that was sent stays on record, and the listing's one read settles the teardown."""
    late = started.copy(tmp_path / "late", logs=False)
    late.edit(lambda a: a.update(reply_error={"iot create-certificate-from-csr": "InternalFailureException"}))
    ran = late.go("apply", "certificate", expect=1)
    assert "call 1 of 1 failed (iot create-certificate-from-csr: InternalFailureException)" in ran.err and not clean(ran.text)
    late.edit(lambda a: a.pop("reply_error"))
    lost(late, status="partial")                                    # the certificate is there: refused, never taken back unread
    # by hand, as for a reply that was lost: what the create made is deleted, and the teardown then takes the record back
    late.edit(lambda a: a["certs"].clear())
    since = len(late.log())
    ran = late.run("teardown", "certificate", expect=0)
    assert "nothing of it stands: the record is taken back" in ran.out and status_of(late, "certificate") == "absent"
    assert [e["argv"][:2] for e in late.log()[since:]] == [["sts", "get-caller-identity"], ["iot", "list-certificates"]]
    late.go("apply", "certificate")
    assert len(late.account()["certs"]) == 1 and status_of(late, "certificate") == "created"
    # an error with nothing made (a throttle) is on record all the same: one read of the listing takes the record back,
    # where it was taken back unread before. That read is the price of trusting no code
    refused = started.copy(tmp_path / "refused", logs=False)
    refused.edit(lambda a: a["faults"].append({"service": "iot", "op": "create-certificate-from-csr", "code": "ThrottlingException"}))
    assert "call 1 of 1 failed" in refused.go("apply", "certificate", expect=1).err
    step = state_of(refused)["steps"]["certificate"]
    assert (step["status"], step["sent"], step["done"]) == ("partial", [0], []) and refused.account()["certs"] == {}
    assert "refused: half-made:" in refused.go("apply", "certificate", expect=1).err and refused.account()["certs"] == {}
    since, made = len(refused.log()), refused.writes()
    ran = refused.run("teardown", "certificate", expect=0)
    assert "nothing of it stands: the record is taken back" in ran.out and "no create call of it is on record" not in ran.text
    assert [e["argv"][:2] for e in refused.log()[since:]] == [["sts", "get-caller-identity"], ["iot", "list-certificates"]]
    assert status_of(refused, "certificate") == "absent" and refused.writes() == made and not clean(ran.text)
    # the listing is read under the caller's identity, like every read: another account's answer settles nothing
    other = started.copy(tmp_path / "other", logs=False)
    other.edit(lambda a: a["faults"].append({"service": "iot", "op": "create-certificate-from-csr", "code": "InternalFailureException"}))
    assert "call 1 of 1 failed" in other.go("apply", "certificate", expect=1).err
    other.edit(other_account)
    assert "refused: identity-other-account:" in other.run("teardown", "certificate", expect=1).err
    assert status_of(other, "certificate") == "partial"
    # only a record with NO call on it is taken back unread: a run that ended before its first call was put on record
    never = started.copy(tmp_path / "never", logs=False)
    state = state_of(never)
    state["steps"]["certificate"] = {"status": "creating", "done": [], "sent": []}
    (never.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    since = len(never.log())
    ran = never.run("teardown", "certificate", expect=0)
    assert "no create call of it is on record as sent" in ran.out and never.log()[since:] == [] and status_of(never, "certificate") == "absent"
    # a step that is read by its name is torn down from such a record as before: its reads and its delete calls decide
    thing = started.copy(tmp_path / "thing", logs=False)
    thing.edit(lambda a: a.update(reply_error={"iot create-thing": "InternalFailureException"}))
    assert "call 1 of 1 failed (iot create-thing: InternalFailureException)" in thing.go("apply", "thing", expect=1).err
    thing.edit(lambda a: a.pop("reply_error"))
    step = state_of(thing)["steps"]["thing"]
    assert (step["status"], step["sent"], step["done"]) == ("partial", [0], []) and list(thing.account()["things"]) == [THING]
    assert "refused: half-made:" in thing.go("apply", "thing", expect=1).err
    assert "deleted; read back, not found; recorded" in thing.go("teardown", "thing").out and thing.account()["things"] == {}
    docstring = " ".join(str(TW.__doc__).split())
    assert "was answered by the service with an error is the record taken back unread" not in docstring
    assert "an error does not say that nothing was made" in docstring and "No record with a call on it is taken back unread" in docstring
    readme = " ".join((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8").split())
    assert "answered with an error" in readme and "does not say that nothing was made" in readme
    # WP7-verify-r2#6. The README counts what the throttled create above cost before its record was taken back: the two calls
    # that test held (the caller's identity, the listing), not "one read"
    assert "costs two calls, the caller's identity and the listing, before its record is taken back" in readme and "costs one read" not in readme


def lost_twin_certificate_beside_the_rehearsals(started: Rig, base: Path, unconfirmed: bool) -> Rig:
    """The rehearsal made a certificate (`unconfirmed`: its reply named another region, so the state kept the id as
    unconfirmed); then the twin's create went through and its reply was lost; the owner deleted what that one made, by hand.
    The account lists the rehearsal's certificate, which the twin's teardown must not take for a stray."""
    rig = started.copy(base, logs=False)
    if unconfirmed:
        elsewhere = j("arn:aws:iot:", "eu-central-1:", ACCOUNT, ":cert/", CERT_1)
        rig.edit(lambda a: a.update(reply_extra={"iot create-certificate-from-csr": {"certificateArn": elsewhere}}))
        assert "refused: reply-unreadable:" in rig.go("apply", "certificate", "--rehearsal", expect=1).err
        rig.edit(lambda a: a.pop("reply_extra"))
    else:
        rig.go("apply", "certificate", "--rehearsal")
    rig.edit(lambda a: a.update(reply_garbage={"iot create-certificate-from-csr": "what a CLI that misbehaves prints"}))
    assert "refused: reply-unreadable:" in rig.go("apply", "certificate", expect=1).err
    rig.edit(lambda a: a.pop("reply_garbage"))
    assert sorted(rig.account()["certs"]) == sorted([CERT_1, CERT_2])
    rig.edit(lambda a: a["certs"].pop(CERT_2))                      # what the lost create made, deleted by hand
    rehearsal = json.loads((rig.state / "rehearsal" / "state.json").read_text(encoding="utf-8"))
    assert rehearsal["facts"].get("certificate_id_unconfirmed" if unconfirmed else "certificate_id") == CERT_1
    assert state_of(rig)["steps"]["certificate"]["sent"] == [0] and "certificate_id" not in state_of(rig)["facts"]
    return rig


@pytest.mark.parametrize("unconfirmed", [False, True], ids=["the-rehearsals-certificate", "the-rehearsals-id-kept-unconfirmed"])
def test_a_lost_create_is_settled_on_the_listing_less_what_the_other_state_knows_and_no_more(started: Rig, tmp_path: Path,
                                                                                            unconfirmed: bool) -> None:
    """WP7-verify-r1#4 (W03, W04). The listing the teardown of a lost create reads holds the rehearsal's certificate beside
    the twin's: a name the baseline lacks, and one the OTHER state knows, by its confirmed id or by the id it kept as
    unconfirmed. Neither is a stray. A name no state knows still is."""
    rig = lost_twin_certificate_beside_the_rehearsals(started, tmp_path / "rig", unconfirmed)
    stray = hashlib.sha256(b"a certificate nobody knows").hexdigest()
    rig.edit(lambda a: a["certs"].update({stray: {"status": "INACTIVE", "policies": []}}))
    made = rig.writes()
    ran = rig.run("teardown", "certificate", expect=1)
    assert "refused: nothing-to-read:" in ran.err and "lists 1 name(s) of this kind" in ran.err and status_of(rig, "certificate") == "creating"
    rig.edit(lambda a: a["certs"].pop(stray))
    since = len(rig.log())
    ran = rig.run("teardown", "certificate", expect=0)
    assert "nothing of it stands: the record is taken back" in ran.out and "refused" not in ran.err and not clean(ran.text)
    assert [e["argv"][:2] for e in rig.log()[since:]] == [["sts", "get-caller-identity"], ["iot", "list-certificates"]]
    assert status_of(rig, "certificate") == "absent" and rig.writes() == made and list(rig.account()["certs"]) == [CERT_1]
    rehearsal = json.loads((rig.state / "rehearsal" / "state.json").read_text(encoding="utf-8"))
    assert rehearsal["steps"]["certificate"]["status"] in TW.OURS                  # the rehearsal's own certificate was not touched


# A PEM block that is no certificate, put together here (written out, its first line and a body would be a finding of the
# tree's own check): what the account answers for a certificate that is not the one a reply of the state made.
STUB_PEM_OF_ANOTHER = ("-----BEGIN " + "CERTIFICATE-----\n"
                       + base64.b64encode(b"EXAMPLE ONLY, made by a test: another certificate's body. " * 2).decode()
                       + "\n-----END " + "CERTIFICATE-----\n")


def reply_files(rig: Rig) -> List[Path]:
    return sorted((rig.state / "replies").glob("*-iot-create-certificate-from-csr-certificate.json"))


def test_recover_puts_the_certificates_id_back_from_a_reply_of_the_state_directory_once_the_account_showed_it(twin: Rig, tmp_path: Path) -> None:
    """WP6's critic, problem 3, the second half (WP6-verify-final's NIT 7; the hard review's c09). On a live twin whose
    state lost the certificate's id, every teardown whose render stands on it was refused until state.json was edited
    by hand: no command put a fact back from replies/."""
    forget(twin, "certificate_id")
    assert "refused: render-provisional:" in twin.run("teardown", "go-live-certificate", expect=1).err
    assert len(reply_files(twin)) == 1                              # the reply the runner itself wrote, when the certificate was made
    since = len(twin.log())
    digest = twin.shown("recover", "certificate")                   # printed like a step: nothing is sent, nothing is put back
    shown = twin.said[-1]
    assert twin.log()[since:] == [] and "certificate_id" not in state_of(twin)["facts"] and CERT_1 not in shown.text and not clean(shown.text)
    assert "1 reply file(s)" in shown.out and "name 1 certificate(s)" in shown.out and "it is never typed" in shown.out
    assert twin.run("recover", "certificate", CERT_1, expect=2).rc == 2             # there is no way to give it an id
    # held to the caller, like `apply`
    session = twin.account()["identity"]
    twin.edit(other_account)
    assert "refused: identity-other-account:" in twin.run("recover", "certificate", "--approve", "certificate:" + digest, expect=1).err
    twin.edit(lambda a: a.update(identity=session))
    assert "certificate_id" not in state_of(twin)["facts"]
    ran = twin.run("recover", "certificate", "--approve", "certificate:" + digest, expect=0)
    assert [e["argv"][:2] for e in twin.log()[since:] if e["rc"] == 0][-3:] == [["sts", "get-caller-identity"], ["iot", "describe-certificate"],
                                                                                  ["iot", "list-thing-principals-v2"]]
    assert twin.writes(since) == [] and state_of(twin)["facts"]["certificate_id"] == CERT_1 and status_of(twin, "certificate") == "created"
    assert CERT_1 in json.loads((twin.state / "literals.json").read_text(encoding="utf-8"))["literals"]["certificate-id"] and not clean(ran.text)
    # WP7-critic, ledger WP7#4 (WP7-verify-final's VT06): the trail of approvals.jsonl for this command: printed; refused for the
    # caller (no record); given again and let through, and spent
    trail = [json.loads(x) for x in (twin.state / "approvals.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
    assert [e["event"] for e in trail if e["mode"] == "recover" and e["step"] == "certificate"] == ["shown", "used", "spent"]
    assert {e["hash"] for e in trail if e["mode"] == "recover" and e["step"] == "certificate"} == {digest}
    lines = status_lines(twin.run("status", expect=0))
    assert "as rendered" in lines["certificate"] and "as rendered" in lines["attachments"] and "as rendered" in lines["go-live-certificate"]
    assert "refused: nothing-to-recover:" in twin.run("recover", "certificate", "--approve", "certificate:" + digest, expect=1).err
    twin.go("teardown", "go-live-certificate")                      # and the teardown that was refused goes on
    assert twin.account()["certs"][CERT_1]["status"] == "INACTIVE"
    for argv, name in ((["recover", "bucket"], "recover-not-this-step"), (["recover", "no-such-step"], "step-unknown")):
        assert "refused: %s:" % name in twin.run(*argv, expect=1).err


@pytest.mark.parametrize("case", ["another-pem", "not-attached", "in-the-baseline", "gone", "two-stand", "a-reply-of-another-region",
                                  "a-file-of-another-name", "an-approval-of-another-set", "described-under-another-accounts-arn",
                                  "described-under-another-regions-arn"])
def test_recover_puts_nothing_back_unless_exactly_one_certificate_of_the_replies_stands_and_is_the_twins_own(twin: Rig, case: str) -> None:
    forget(twin, "certificate_id")
    reply, = reply_files(twin)
    doc = json.loads(reply.read_text(encoding="utf-8"))
    name = "recover-not-decided"
    digest = twin.shown("recover", "certificate") if case != "in-the-baseline" else ""
    if case == "another-pem":                                       # the account's certificate of that id is not the one this reply made
        twin.edit(lambda a: a.update(pem_of={CERT_1: STUB_PEM_OF_ANOTHER}))
    elif case == "not-attached":                                    # the state records the attachments, and this one is not the thing's
        twin.edit(lambda a: a["things"][THING]["principals"].clear())
    elif case == "in-the-baseline":                                 # it was there before the twin: no reply makes it the twin's
        baseline = json.loads((twin.state / "baseline.json").read_text(encoding="utf-8"))
        baseline["listings"]["certificates"].append(CERT_1)
        (twin.state / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
        name = "no-reply-to-recover-from"
    elif case == "gone":                                            # the reply names a certificate the account no longer holds
        twin.edit(lambda a: (a["certs"].pop(CERT_1), a["things"][THING]["principals"].clear()))
    elif case == "two-stand":                                       # a second reply of this state names a second one that stands
        second = dict(doc, certificateId=CERT_2, certificateArn=iot_arn("cert", CERT_2), certificatePem=doc["certificatePem"])
        reply.with_name("0-" + reply.name).write_text(json.dumps(second), encoding="utf-8")
        twin.edit(lambda a: a["certs"].update({CERT_2: {"status": "INACTIVE", "policies": []}}))
        digest = twin.shown("recover", "certificate")
    elif case == "a-reply-of-another-region":                       # what _after_certificate refused is no candidate either
        reply.write_text(json.dumps(dict(doc, certificateArn=j("arn:aws:iot:", "eu-central-1:", ACCOUNT, ":cert/", CERT_1))), encoding="utf-8")
        name = "no-reply-to-recover-from"
    elif case == "a-file-of-another-name":                          # only a file the runner itself wrote for this step's create call
        reply.rename(reply.with_name("a-note-with-an-id.json"))
        name = "no-reply-to-recover-from"
    elif case in ("described-under-another-accounts-arn", "described-under-another-regions-arn"):
        # WP7-verify-r1#4 (W01). The account answers the id's read with the PEM the reply holds, and with an ARN that is not this
        # account's and region's: it is not shown to be the twin's own, though it stands, is attached and holds its reply's PEM
        elsewhere = j("arn:aws:iot:", REGION, ":", OTHER_ACCOUNT, ":cert/", CERT_1) if "account" in case else j(
            "arn:aws:iot:", "eu-central-1:", ACCOUNT, ":cert/", CERT_1)
        twin.edit(lambda a: a.update(arn_of={CERT_1: elsewhere}))
    elif case == "an-approval-of-another-set":                      # the approval is for the replies as they were printed
        reply.with_name("0-" + reply.name).write_text(json.dumps(dict(doc, certificateId=CERT_2, certificateArn=iot_arn("cert", CERT_2))),
                                                      encoding="utf-8")
        name = "approval-for-another-render"
    since = len(twin.log())
    argv = ["recover", "certificate"] + (["--approve", "certificate:" + digest] if digest else [])
    ran = twin.run(*argv, expect=1)
    assert "refused: %s:" % name in ran.err and "certificate_id" not in state_of(twin)["facts"] and twin.writes(since) == []
    assert status_of(twin, "certificate") == "created" and not clean(ran.text) and CERT_2 not in ran.text
    assert "refused: render-provisional:" in twin.run("teardown", "go-live-certificate", expect=1).err


def test_recover_compares_the_two_pems_by_their_text_and_not_by_their_line_ends(twin: Rig) -> None:
    """WP7-critic, ledger WP7#8 (WP7-verify-final's VT43). The account's reading of the certificate may carry the PEM with other
    line ends than the reply the CLI wrote (CRLF, a last line end more or less, a blank line after it): the same certificate.
    recover still puts the id back for each. (A PEM that differs in its text is the case "another-pem" above.)"""
    reply, = reply_files(twin)
    pem = json.loads(reply.read_text(encoding="utf-8"))["certificatePem"]
    assert "\n" in pem and "\r" not in pem
    variants = {"crlf": pem.replace("\n", "\r\n"), "one line end more": pem + "\n", "no last line end": pem.rstrip("\n"),
                "a blank line after": pem + "\r\n\r\n"}
    for name, variant in variants.items():
        assert variant != pem
        forget(twin, "certificate_id")
        twin.edit(lambda a, v=variant: a.update(pem_of={CERT_1: v}))
        digest = twin.shown("recover", "certificate")
        since = len(twin.log())
        ran = twin.run("recover", "certificate", "--approve", "certificate:" + digest, expect=0)
        assert state_of(twin)["facts"]["certificate_id"] == CERT_1 and twin.writes(since) == [] and not clean(ran.text), name


def test_a_recover_that_decided_nothing_has_spent_its_approval_and_a_new_printing_gives_another(twin: Rig) -> None:
    """WP7-verify-r1#4 (W02). One printing of a render lets ONE run of its reads through, as for every command that goes on
    an approval: a recover that ended `recover-not-decided` read the account under it, and the same approval given again
    is spent, without a new printing."""
    forget(twin, "certificate_id")
    digest = twin.shown("recover", "certificate")
    twin.edit(lambda a: a.update(pem_of={CERT_1: STUB_PEM_OF_ANOTHER}))
    argv = ["recover", "certificate", "--approve", "certificate:" + digest]
    assert "refused: recover-not-decided:" in twin.run(*argv, expect=1).err
    since = len(twin.log())
    ran = twin.run(*argv, expect=1)
    assert "refused: approval-spent:" in ran.err and "recover-not-decided" not in ran.err and not clean(ran.text)
    assert [e["argv"][:2] for e in twin.log()[since:]] == [["sts", "get-caller-identity"]]      # no read of the certificate again
    assert twin.writes(since) == [] and "certificate_id" not in state_of(twin)["facts"]
    # printed again, it is another printing: it is approved again, and (the account being what it is) refused again on its own account
    assert twin.shown("recover", "certificate") == digest
    since = len(twin.log())
    assert "refused: recover-not-decided:" in twin.run(*argv, expect=1).err
    assert any(e["argv"][:2] == ["iot", "describe-certificate"] for e in twin.log()[since:])


def test_recover_reads_again_a_certificate_whose_run_ended_between_the_reply_and_its_record(started: Rig, tmp_path: Path,
                                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    rig = started.copy(tmp_path / "ended", logs=False)
    digest = rig.shown("apply", "certificate")

    def ends(t: Any, index: int, reply: Any) -> None:
        raise SystemExit(137)

    with monkeypatch.context() as m:
        m.setattr(TW, "_after_certificate", ends)                   # the reply is written, the call is recorded, and the run ends there
        with pytest.raises(SystemExit):
            rig.run("apply", "certificate", "--approve", "certificate:" + digest)
    step = state_of(rig)["steps"]["certificate"]
    assert (step["status"], step["done"], step["sent"]) == ("creating", [0], [0]) and "certificate_id" not in state_of(rig)["facts"]
    assert "refused: nothing-to-read:" in rig.run("teardown", "certificate", expect=1).err and len(rig.account()["certs"]) == 1
    rig.go("recover", "certificate")
    assert state_of(rig)["facts"]["certificate_id"] == CERT_1 and status_of(rig, "certificate") == "unverified"
    assert "already made, nothing was created" in rig.go("apply", "certificate").out and status_of(rig, "certificate") == "created"
    assert len(rig.account()["certs"]) == 1 and len(reply_files(rig)) == 1
    # a state that records nothing made for the step takes nothing back, whatever a reply file says
    fresh = started.copy(tmp_path / "fresh", logs=False)
    (fresh.state / "replies").mkdir(exist_ok=True)
    shutil.copy(str(reply_files(rig)[0]), str(fresh.state / "replies"))
    fresh.edit(lambda a: a["certs"].update({CERT_1: {"status": "INACTIVE", "policies": []}}))
    assert "refused: not-ours:" in fresh.run("recover", "certificate", expect=1).err and "certificate_id" not in state_of(fresh)["facts"]


def test_a_step_with_no_read_is_never_called_not_found_by_status_or_by_apply(twin: Rig, rig: Rig) -> None:
    """WP6's critic, problem 3 (WP6-verify-final's NIT 2, P4). With the certificate's id gone from the state, `status`
    printed `created  not found` for three steps that had no read at all, and an approved `apply certificate` said
    "nothing of it is found: teardown clears the record"."""
    forget(twin, "certificate_id")
    since = len(twin.log())
    ran = twin.run("status", expect=1)
    lines = status_lines(ran)
    for step in ("certificate", "attachments", "go-live-certificate"):
        assert re.search(r"%s +row \S+ +created +no read: the state holds no id" % step, lines[step]), lines[step]
        assert "not found" not in lines[step]
    assert twin.writes(since) == [] and not clean(ran.text)
    made = twin.writes()
    ran = twin.go("apply", "certificate", expect=1)
    assert "refused: nothing-to-read:" in ran.err and "nothing of it is found" not in ran.text and "recorded-not-found" not in ran.text
    assert twin.writes() == made and status_of(twin, "certificate") == "created" and len(twin.account()["certs"]) == 1
    # before the certificate exists, the three steps are not "not found" either: nothing was read
    lines = status_lines(rig.run("status", expect=0))
    for step in ("certificate", "attachments", "go-live-certificate"):
        assert re.search(r"%s +row \S+ +absent +no read" % step, lines[step]) and "not found" not in lines[step], lines[step]
    assert re.search(r"thing +row 5 +absent +not found", lines["thing"])         # a step that WAS read and is not there keeps the word


def test_function_status_prints_the_two_facts_of_the_functions_own_record(before_function: Rig, tmp_path: Path) -> None:
    """A3 row 13: the status record names the runtime's SDK and whether its data-plane client has the call. The driver
    reads the invoke's verdict as before, and prints these two facts from the record's file."""
    twin = before_function.copy(tmp_path / "twin")
    twin.go("apply", "function")
    since = len(twin.log())
    ran = twin.go("apply", "function-status")
    assert [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and status_of(twin, "function-status") == "done"
    assert re.search(r"function-status: the runtime's boto3 is \S+; its data-plane client has DeleteConnection: yes", ran.out), ran.out
    record = json.loads((twin.state / "replies" / "payload-function-status.json").read_text(encoding="utf-8"))
    assert record["mode"] == "status" and record["has_delete_connection"] is True and not clean(ran.text)
    # and what the function-status reading records beside the two facts (the hard review's SHOULD 1): the function's connect time-out is per
    # address, and how many addresses its two endpoints' names resolve to is not known before the account is met
    assert "function-status: for the function-status reading: how many addresses" in ran.out and "per address" in ran.out
    # a record that does not hold the two facts in the form they have: said, and nothing of it is printed
    twin.edit(lambda a: a.update(record_extra={"boto3": "a version; with words", "has_delete_connection": "yes"}))
    ran = twin.go("apply", "function-status")
    assert "function-status: the record does not hold the two facts in their form: it is read by hand" in ran.out and "with words" not in ran.text


WRITES_SAID = "the function's record of its writes"


def test_a_trips_write_words_are_printed_from_the_functions_own_record_in_their_form_only(twin: Rig) -> None:
    """WP7-verify-r1, NIT 5 (A3 row 17a exists to show what each API answers when its work is already done). The write
    words of a dry trip's record stood in the payload's file only, and a write the service answered with an error on a
    twin that is cut already was `done` unseen."""
    ran = twin.go("apply", "dry-trip")                              # the built twin is live: each write does its work
    whole = "the rule's disable ok; certificate 1 of 1: deactivate ok, detach ok; connection 1 of 1: no-client-connected"
    assert [line for line in ran.out.split("\n") if WRITES_SAID in line] == ["dry-trip: %s: %s" % (WRITES_SAID, whole)], ran.out
    # row 17a's own case: the work is done already, and the service answers a write with an error that is no refusal
    twin.edit(lambda a: a.update(function_faults=[{"op": "update_certificate", "code": "InvalidRequestException", "status": 400}]))
    ran = twin.go("apply", "dry-trip")
    assert "certificate 1 of 1: deactivate answered:InvalidRequestException, detach ok" in ran.out and "ANSWERED WITH AN ERROR" in ran.out
    record = json.loads((twin.state / "replies" / "payload-dry-trip.json").read_text(encoding="utf-8"))
    assert record["certificates"][0]["write"] == "answered:InvalidRequestException" and record["cut"] is True
    assert status_of(twin, "dry-trip") == "done" and not clean(ran.text)
    # the stop says the same of its own record
    ran = twin.run("trip", expect=0)
    assert "trip: %s: %s" % (WRITES_SAID, whole) in ran.out and "ANSWERED WITH AN ERROR" not in ran.out and not clean(ran.text)
    # a record whose words are not in the form a write word has: said, and nothing of it is printed
    for extra in ({"rule": {"write": "a word; with text", "state": "disabled"}}, {"certificates": [{"write": "ok", "detach": "with text"}]},
                  {"connections": [{"write": "ok"}] * 17}, {"certificates": "with text"}, {"mode": "status"}):
        twin.edit(lambda a, planted=extra: a.update(record_extra=planted))
        ran = twin.go("apply", "dry-trip")
        assert "dry-trip: the record does not hold its write words in their form: it is read by hand" in ran.out, extra
        assert WRITES_SAID not in ran.out and "with text" not in ran.text
    twin.edit(lambda a: a.pop("record_extra"))
    # the status invoke makes no write: nothing is said of writes there
    assert WRITES_SAID not in twin.go("apply", "function-status").text and "write words" not in twin.said[-1].text
    # every word the function's record can hold for a write is one the driver prints, and no other is
    for word in ("ok", "answered", "answered:InvalidRequestException", "refused", "failed", "not-attempted", "no-client-connected", "unavailable"):
        assert TW.WRITE_WORD.fullmatch(word), word
    for word in ("", "OK", "answered:", "answered:with text", "answered:" + "x" * 65, "ok ", "detached", "arn:aws:iot"):
        assert not TW.WRITE_WORD.fullmatch(word), word


def test_a_run_of_an_action_that_does_not_come_to_its_end_takes_back_the_record_of_its_earlier_run(twin: Rig,
                                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """WP7-verify-r1, NIT 8. An action applied AGAIN that ended in a function error left its earlier `done`: the alarm
    tests and go-live stand on that record, and it then said "the breaker ran to its end" of a breaker whose last run
    did not. An action's `done` is the record of its LAST run."""
    after = ["alarm-test-" + k for k in BREAKER] + ["reattach-policy"]
    assert {status_of(twin, s) for s in ["dry-trip"] + after} == {"done"}
    digest = twin.shown("apply", "dry-trip")
    twin.edit(lambda a: a.update(function_faults=[{"op": "update_certificate", "code": "AccessDeniedException", "status": 403}]))
    ran = twin.run("apply", "dry-trip", "--approve", "dry-trip:" + digest, expect=1)
    assert "the function did not run to its end" in ran.err and "the record of its earlier run is taken back" in ran.err
    assert "apply dry-trip: 6 record(s) stood on this step as it was and are taken back" in ran.out
    assert status_of(twin, "dry-trip") == "stale" and {status_of(twin, s) for s in after} == {"stale"} and not clean(ran.text)
    assert re.search(r"dry-trip +row 17a +stale ", status_lines(twin.run("status"))["dry-trip"])
    # a step that needs it is refused until it ran again, to its end
    since = len(twin.log())
    assert "refused: step-needs:" in twin.go("apply", "alarm-test-bytes", expect=1).err and twin.writes(since) == []
    # an approval that is spent sends nothing: that is no run, and it changes no record
    assert "refused: approval-spent:" in twin.run("apply", "dry-trip", "--approve", "dry-trip:" + digest, expect=1).err
    assert "apply dry-trip: done; recorded" in twin.go("apply", "dry-trip").out and status_of(twin, "dry-trip") == "done"
    assert status_of(twin, "alarm-test-bytes") == "stale"           # what stood on it is applied again, each by itself
    twin.go("apply", "alarm-test-bytes")
    assert status_of(twin, "alarm-test-bytes") == "done"
    assert "refused: approval-spent:" in twin.run("apply", "dry-trip", "--approve", "dry-trip:" + digest, expect=1).err
    assert status_of(twin, "dry-trip") == "done"
    # a call that fails is a run that did not come to its end as well: the invoke itself is refused by the service
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "invoke", "code": "TooManyRequestsException"}))
    ran = twin.go("apply", "dry-trip", expect=1)
    assert "call 1 of 1 failed (lambda invoke: TooManyRequestsException)" in ran.err and "the record of its earlier run is taken back" in ran.err
    assert status_of(twin, "dry-trip") == "stale" and status_of(twin, "alarm-test-bytes") == "stale"
    # and so is a run whose reply cannot be read: how it ended is not known
    twin.go("apply", "dry-trip")
    assert status_of(twin, "dry-trip") == "done"
    twin.edit(lambda a: a.update(reply_garbage={"lambda invoke": "what a CLI that misbehaves prints"}))
    ran = twin.go("apply", "dry-trip", expect=1)
    assert "refused: reply-unreadable:" in ran.err and status_of(twin, "dry-trip") == "stale"
    twin.edit(lambda a: a.pop("reply_garbage"))
    real = TW.subprocess.run

    def at_the_invoke(end: BaseException, sent: bool) -> Any:
        def run(argv: List[str], **kw: Any) -> Any:
            if "invoke" not in argv:
                return real(argv, **kw)
            if sent:
                real(argv, **kw)
            raise end
        return run

    # ... or a CLI that is cut off after the service took the call
    twin.go("apply", "dry-trip")
    digest = twin.shown("apply", "dry-trip")
    with monkeypatch.context() as m:
        m.setattr(TW.subprocess, "run", at_the_invoke(subprocess.TimeoutExpired(["aws"], 900), sent=True))
        assert "refused: cli-failed:" in twin.run("apply", "dry-trip", "--approve", "dry-trip:" + digest, expect=1).err
    assert status_of(twin, "dry-trip") == "stale"
    # the runner's refusal BEFORE anything is sent (the CLI is not found any more) is no run at all: the record stands
    twin.go("apply", "dry-trip")
    digest = twin.shown("apply", "dry-trip")
    with monkeypatch.context() as m:
        m.setattr(TW.subprocess, "run", at_the_invoke(FileNotFoundError("aws"), sent=False))
        assert "refused: cli-missing:" in twin.run("apply", "dry-trip", "--approve", "dry-trip:" + digest, expect=1).err
    assert status_of(twin, "dry-trip") == "done"
    # a first run that fails has no earlier record to take back, and leaves none
    state = state_of(twin)
    del state["steps"]["function-status"]
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    twin.edit(lambda a: a.update(function_error=True))
    ran = twin.go("apply", "function-status", expect=1)
    assert "the function did not run to its end" in ran.err and "taken back" not in ran.text and status_of(twin, "function-status") == "absent"
    docstring = " ".join(str(TW.__doc__).split())
    assert "the record of its LAST run" in docstring


STATUS_SAID = "status (the twin):"
DETACH_REFUSED = {"op": "detach_policy", "code": "AccessDeniedException", "status": 403}


def test_a_trip_whose_invoke_fails_still_prints_the_status_and_a_throttle_says_that_a_run_may_be_under_way(twin: Rig) -> None:
    """The hard review of WP7 (fable-wp7), NIT 2. A trip whose invoke the service refused printed RUN THE FOUR CALLS BY HAND
    and returned without `status`, which the manual stop contract names as the proof for those calls. And under reserved
    concurrency 1 a throttled invoke means that a run of the function, an alarm's own, may be under way: the owner was
    sent to the calls by hand without the one read that shows a cut in progress."""
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "invoke", "code": "TooManyRequestsException"}))
    since = len(twin.log())
    ran = twin.run("trip", expect=1)
    assert STATUS_SAID in ran.out and "traffic: the rule is enabled" in ran.out and "the certificate is ACTIVE" in ran.out
    assert "trip: the invoke failed (TooManyRequestsException)" in ran.err and "A RUN OF THE FUNCTION MAY BE UNDER WAY" in ran.err
    assert "RUN THE FOUR CALLS BY HAND" in ran.err and ran.err.index("Read `status` below first") < ran.err.index("RUN THE FOUR CALLS BY HAND")
    assert [e["argv"][:2] for e in twin.log()[since:]][:2] == [["sts", "get-caller-identity"], ["lambda", "invoke"]]
    assert [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and not clean(ran.text)      # the status reads; it changes nothing
    # any other error of the invoke: the calls by hand as before, the status all the same, and no word of a run under way
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "invoke", "code": "ResourceNotFoundException"}))
    ran = twin.run("trip", expect=1)
    assert "the invoke failed (ResourceNotFoundException). RUN THE FOUR CALLS BY HAND" in ran.err and "UNDER WAY" not in ran.text
    assert STATUS_SAID in ran.out and "traffic: the rule is enabled" in ran.out
    # a CLI that is cut off after the service took the invoke: the function ran, and the status is where that shows
    twin.edit(lambda a: a.update(reply_dies={"lambda invoke": 255}))
    ran = twin.run("trip", expect=1)
    assert "the invoke failed (exit-255). RUN THE FOUR CALLS BY HAND" in ran.err and "UNDER WAY" not in ran.text
    assert STATUS_SAID in ran.out and "traffic: the rule is DISABLED" in ran.out
    assert "the certificate is INACTIVE; the policy is NOT attached" in ran.out
    # an invoke that failed says nothing of the function: the dry trip's record stands as it was
    assert status_of(twin, "dry-trip") == "done" and "taken back" not in "".join(r.text for r in twin.said[-3:])
    assert TW.THROTTLED == "TooManyRequestsException"


def test_a_manual_trip_that_ends_in_a_function_error_takes_the_dry_trips_record_back(twin: Rig) -> None:
    """WP7-verify-r2, NIT 5 (the case of WP7-verify-r1's NIT 8, reached through the other command that sends the same
    invoke). The alarm tests and go-live stand on "the dry trip ran to its end". A manual `trip` that ended in a function
    error, with one of the function's cuts refused, left that `done`: go-live was not refused after a trip that had
    shown the function cannot make one of its cuts. DECIDED: such a trip takes the dry trip's record back."""
    after = ["alarm-test-" + k for k in BREAKER] + ["reattach-policy"]
    assert {status_of(twin, s) for s in ["dry-trip"] + after} == {"done"}
    twin.edit(lambda a: a.update(function_faults=[dict(DETACH_REFUSED)]))
    ran = twin.run("trip", expect=1)
    assert "trip: the function did not run to its end" in ran.err and "RUN THE FOUR CALLS BY HAND" in ran.err and STATUS_SAID in ran.out
    assert status_of(twin, "dry-trip") == "stale" and {status_of(twin, s) for s in after} == {"stale"}
    assert state_of(twin)["steps"]["dry-trip"]["stale_for"] == "trip"
    assert "trip: the dry trip's record said that the function runs to its end: it is taken back" in ran.err
    assert "trip dry-trip: 6 record(s) stood on this step as it was and are taken back" in ran.out and not clean(ran.text)
    assert ran.out.index(STATUS_SAID) < ran.out.index("trip dry-trip: 6 record(s)")           # the status first: bookkeeping never hides it
    # a step that needs the dry trip is refused until it ran to its end again
    since = len(twin.log())
    assert "refused: step-needs:" in twin.go("apply", "alarm-test-bytes", expect=1).err and twin.writes(since) == []
    # a trip that runs clean afterwards puts no record back: `trip` is no action, and nobody approved it as one
    ran = twin.run("trip", expect=0)
    assert "trip: the function ran" in ran.out and status_of(twin, "dry-trip") == "stale" and "taken back" not in ran.text
    assert "apply dry-trip: done; recorded" in twin.go("apply", "dry-trip").out and status_of(twin, "dry-trip") == "done"
    ran = twin.run("trip", expect=0)                                # ... and takes none back either
    assert status_of(twin, "dry-trip") == "done" and "taken back" not in ran.text
    # on a state that cannot be read the stop goes on as before, and nothing is written over what is there
    garbled = b"{ this is no state"
    (twin.state / "state.json").write_bytes(garbled)
    twin.edit(lambda a: a.update(function_faults=[dict(DETACH_REFUSED)]))
    ran = twin.run("trip", expect=1)
    assert "the function did not run to its end" in ran.err and "taken back" not in ran.text and STATUS_SAID in ran.out
    assert (twin.state / "state.json").read_bytes() == garbled
    docstring = " ".join(str(TW.__doc__).split())
    assert "A manual `trip` whose invoke ends in a function error takes the dry trip's `done` back" in docstring
    readme = " ".join((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8").split())
    assert "A manual `trip` whose invoke ends in a function error takes the dry trip's `done` back" in readme


OWN_SAID = "%s: the function's error is its own verdict (BreakerError), and it says: %s (%s)"
NOT_ITS_FORMS = ("trip: the function's error is of the kind BreakerError (its own kind, but its message is not in the function's own sentence "
                 "forms); the message is read by hand, in the state directory's replies (payload-trip.json)")
OWN_ONE = "the trip did not complete: 1 failure(s): the rule is not disabled"
# Messages that are NOT in the function's own sentence forms, under the function's own type: a value of the environment, a control
# character, a count that is not the clauses', words after the last clause, a message of another kind or too long. The order is
# part of the list: the test below takes the first and the fifth through the command.
OUTSIDE_ITS_FORMS: List[Any] = [
    "the trip did not complete: 2 failure(s): the rule is not disabled; the thing %s is still connected" % THING,
    OWN_ONE + "; the thing %s is still connected" % THING, OWN_ONE + "; " + j("arn:aws:iot:", REGION, ":", ACCOUNT, ":cert/", CERT_1),
    "the trip did not complete: 1 failure(s): the rule %s-rule is not disabled" % PREFIX,
    OWN_ONE + "\x1b[2J", OWN_ONE + "\n", OWN_ONE + "\r", "\x07" + OWN_ONE, OWN_ONE + "; ", OWN_ONE + " ", OWN_ONE + ";the rule is not disabled",
    "the trip did not complete: 2 failure(s): the rule is not disabled",
    "the trip did not complete: 0 failure(s): ", "the restore did not complete: 1 failure(s): the rule is not disabled",
    "the trip did not complete: 1 failure(s): certificate x of 1 is not INACTIVE",
    "the trip did not complete: 1 failure(s): certificate 1 of 1: the call that deactivates it was answered with an error",
    "the trip did not complete: 1 failure(s): certificate 1 of 1234 is not INACTIVE",
    "the breaker stopped on an error no step names (a kind; with text): look at the state by hand",
    "the breaker stopped on an error no step names (KeyError): look at the state by hand, then at " + THING, "", 7, None, [OWN_ONE],
    # a head that counts FEWER failures than the message has clauses: both clauses are the function's own forms, the count is not
    # (burst-verify-r1, problem 8, its mutant X06). It stands before the last entry, which is the one that is too long.
    "the trip did not complete: 1 failure(s): the rule is not disabled; the rule is not disabled",
    "the trip did not complete: 999 failure(s): " + "; ".join(["the rule is not disabled"] * 999)]          # its forms, and too long


def breaker_forms() -> Tuple[List[str], List[str], Dict[str, str]]:
    """What breaker.py's SOURCE can say, read from its syntax tree: the sentence forms it appends to its failures (with `%d` and
    `%s` in them), its two heads, and the words it can put into a `%s` of the connection's sentence (_WHY)."""
    tree = ast.parse(BREAKER_SOURCE.decode("utf-8"))
    whys = {"refused": "was refused as not authorised", "failed": "got no answer"}
    forms: List[str] = []
    heads: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_WHY":
            assert ast.literal_eval(node.value) == whys
        if not isinstance(node, ast.Call) or not node.args:
            continue
        arg = node.args[0]
        text = arg.left if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod) else arg
        if not isinstance(text, ast.Constant) or not isinstance(text.value, str):
            continue
        if getattr(node.func, "attr", "") == "append" and getattr(getattr(node.func, "value", None), "id", "") in ("failures", "out"):
            forms.append(text.value)
        elif getattr(node.func, "id", "") == "BreakerError":
            heads.append(text.value)
    return forms, heads, whys


def clause_words(form: str, whys: Dict[str, str]) -> List[str]:
    """The words a form can take in its `%s`: none, the two reasons, and for the connection's delete a third."""
    if "%s" not in form:
        return [""]
    return sorted(whys.values()) + (["was answered with an error"] if form.startswith("client ") else [])


def test_a_function_error_is_said_by_its_kind_and_the_functions_own_message_is_printed_in_its_own_sentence_forms_only(twin: Rig,
                                                                                                                       tmp_path: Path) -> None:
    """The hard review of WP7 (fable-wp7), NIT 3; ledger WP7#1, DECIDED by the owner on 2026-10-12: print it. A run that
    ended in a function error printed the error's KIND and the name of the file its message is read in, and not the
    message. Printed now: the function's own failure message, ONLY when the error's type is the breaker's own AND every
    clause of the message is one of the function's own sentence forms. Anything else stays the read-by-hand sentence
    with the file's name: no value of the function's environment reaches the terminal by that road, and no control
    character."""
    twin.edit(lambda a: a.update(function_faults=[dict(DETACH_REFUSED)]))
    ran = twin.go("apply", "dry-trip", expect=1)
    assert "apply dry-trip: the function did not run to its end" in ran.err
    payload = json.loads((twin.state / "replies" / "payload-dry-trip.json").read_text(encoding="utf-8"))
    message = "the trip did not complete: 1 failure(s): certificate 1 of 1: the call that detaches the policy was refused as not authorised"
    assert payload["errorType"] == "BreakerError" and payload["errorMessage"] == message          # the real function's own words
    assert OWN_SAID % ("dry-trip", message, "payload-dry-trip.json") in ran.err and not clean(ran.text)
    # the runtime's own error, through the stop: the function did not get as far as its handler. Its kind, never its message
    twin.edit(lambda a: a.update(function_error=True))
    ran = twin.run("trip", expect=1)
    assert "trip: the function's error is of the kind Runtime.ImportModuleError (not the function's own verdict" in ran.err
    assert "payload-trip.json" in ran.err and STATUS_SAID in ran.out and "could not be loaded" not in ran.text
    # the record is stale since the dry trip's own failed run: a failed trip has nothing to take back twice
    assert status_of(twin, "dry-trip") == "stale" and "taken back" not in ran.text
    # a kind that is not in the form a kind has, or no kind at all: said, and nothing of it is printed
    for planted in ({"errorType": "a kind; with text"}, {"errorType": 7}, {"errorType": "x" * 65}, {"errorType": ""}):
        twin.edit(lambda a, extra=planted: a.update(record_extra=extra))
        ran = twin.run("trip", expect=1)
        assert "trip: the function's error is read by hand, in the state directory's replies (payload-trip.json)" in ran.err, planted
        assert "of the kind" not in ran.text and "with text" not in ran.text and "xxxx" not in ran.text, planted
    for kind in ("BreakerError", "Runtime.ImportModuleError", "Sandbox.Timedout", "KeyError", "Function.ResponseSizeTooLarge"):
        assert TW.ERROR_KIND.fullmatch(kind), kind
    for kind in ("", "with text", "arn:aws:iot", "a/b", "9lives", "x" * 65, "the-twin"):
        assert not TW.ERROR_KIND.fullmatch(kind), kind
    # THE MESSAGE'S ROAD. Through `trip` one case of each kind; then error_said() itself, which is all either command prints
    # of a function error, on a payload file of each case
    payload_file = tmp_path / "payload-trip.json"

    def said(kind: Any, message: Any) -> str:
        payload_file.write_text(json.dumps({"errorType": kind, "errorMessage": message, "requestId": "r", "stackTrace": []}), encoding="utf-8")
        text = TW.error_said(payload_file, "trip")
        assert not clean(text) and not [c for c in text if ord(c) < 32 or ord(c) == 127], repr(message)[:80]
        return str(text)

    def tripped(kind: str, message: Any) -> Ran:
        twin.edit(lambda a: a.update(record_extra={"errorType": kind, "errorMessage": message}))
        ran = twin.run("trip", expect=1)
        assert STATUS_SAID in ran.out and not clean(ran.text) and said(kind, message) in ran.err          # the one sentence, and the status
        return ran

    # A message in the function's own forms under ANOTHER type is not the function's: not printed
    own = OWN_ONE
    ran = tripped("KeyError", own)
    assert "the rule is not disabled" not in ran.text and "it says" not in ran.text
    for kind in ("KeyError", "Runtime.UserCodeSyntaxError", "BreakerErrors", "breakererror", "Breaker.BreakerError"):
        text = said(kind, own)
        assert text.startswith("trip: the function's error is of the kind %s (not the function's own verdict" % kind), kind
        assert "the rule is not disabled" not in text and "it says" not in text, kind
    # ... and under the function's own type, a message with ONE clause outside the table is not printed at all: a value of
    # the environment, a control character, a count that is not its clauses', words after the last clause
    outside = OUTSIDE_ITS_FORMS
    for case in outside:
        text = said("BreakerError", case)
        assert text == NOT_ITS_FORMS and "it says" not in text and "not disabled" not in text and "still connected" not in text, repr(case)[:80]
    assert [len(c) for c in outside if isinstance(c, str)][-1] > TW.OWN_MESSAGE_MAX
    for case in (outside[0], outside[4]):                           # a value of the environment; a control character: through the command
        ran = tripped("BreakerError", case)
        assert NOT_ITS_FORMS in ran.err and "it says" not in ran.text and "not disabled" not in ran.text and "\x1b" not in ran.text
    # ... while every clause in the table, with the count that is theirs, is printed as the function wrote it
    inside = ["the status did not complete: 2 failure(s): TWIN_RULE is not set; the policy's targets could not be read",
              "the trip did not complete: 3 failure(s): the rule: its disable call got no answer; certificate 2 of 2 is not INACTIVE; "
              "client 1 of 2: the call that deletes its connection was answered with an error",
              "the breaker stopped on an error no step names (RecursionError): look at the state by hand"]
    for sentence in inside:
        assert said("BreakerError", sentence) == OWN_SAID % ("trip", sentence, "payload-trip.json"), sentence
    assert OWN_SAID % ("trip", inside[1], "payload-trip.json") in tripped("BreakerError", inside[1]).err
    docstring = " ".join(str(TW.__doc__).split())
    assert "the function's own failure message is printed only when" in docstring


def test_the_table_of_the_functions_own_sentence_forms_is_what_breaker_py_can_raise_and_nothing_else() -> None:
    """The table the driver holds a message to is written out in twinctl.py, as the write words are. It is held equal to
    the function's SOURCE here: every sentence breaker.py appends to its failures, and its two messages, read from its
    syntax tree, with every word it can put into a `%s`. A sentence added to breaker.py fails this test until the table
    has it; a table entry no sentence of breaker.py matches fails it too."""
    forms, heads, whys = breaker_forms()
    assert len(forms) == 17 == len(set(forms)) == len(TW.OWN_CLAUSES) and sorted(heads) == [
        "the %s did not complete: %d failure(s): %s", "the breaker stopped on an error no step names (%s): look at the state by hand"]
    used = set()
    for form in forms:
        # the one sentence with a third word is the connection's delete (breaker.py: _WHY.get(how, ...))
        for word in clause_words(form, whys):
            for n in ("1", "2", "17", "999"):
                clause = form.replace("%d", n).replace("%s", word)
                hits = [i for i, pattern in enumerate(TW.OWN_CLAUSES) if pattern.fullmatch(clause)]
                assert len(hits) == 1, clause                       # one entry of the table, and no other
                used.add(hits[0])
                for head in ("trip", "status"):
                    assert TW.own_message("the %s did not complete: 1 failure(s): %s" % (head, clause)) is not None, clause
        if "%s" in form and not form.startswith("client "):
            assert not [p for p in TW.OWN_CLAUSES if p.fullmatch(form.replace("%d", "1").replace("%s", "was answered with an error"))], form
    assert used == set(range(len(TW.OWN_CLAUSES)))                  # no entry that no sentence of the function matches
    assert TW.own_message("the breaker stopped on an error no step names (KeyError): look at the state by hand") is not None
    # a digit of another script is no digit of the function's, and a number longer than the function ever counts is none
    for bad in ("certificate \u0661 of 1 is not INACTIVE", "certificate 1 of 1 is not INACTIVE\n", "certificate 1 of 1 is not inactive",
                "certificate 1000 of 1 is not INACTIVE", " the rule is not disabled", "the rule is not disabled.", ""):
        assert not [p for p in TW.OWN_CLAUSES if p.fullmatch(bad)], repr(bad)
    assert TW.OWN_ERROR == "BreakerError" and TW.OWN_MESSAGE_MAX == 4096


def test_the_one_slot_of_the_functions_own_sentences_that_is_no_fixed_word_takes_the_class_name_of_an_error_and_not_the_rules_name(
        tmp_path: Path) -> None:
    """burst-verify-r1, problem 13 (its walk, walk-1.txt). The sentence for an error no step names holds the one slot of the
    table that is neither a fixed word nor a count: the error's class, by its name. The table took ANY identifier there,
    and the rule's name (the prefix and `_telemetry`) is one: the message was printed with it, and what kept the name off
    the terminal was the redactor's mask of the prefix, not the table. The slot is held now to the name an error's class
    has (it ends in Error or Exception), which no name the driver forms for the twin has. What the table cannot hold
    back, a name of the twin that had that form, is the redactor's, through which everything printed goes; the function
    itself only ever writes a class's name there."""
    stopped = "the breaker stopped on an error no step names (%s): look at the state by hand"
    payload_file = tmp_path / "payload-trip.json"

    def said(message: str) -> str:
        payload_file.write_text(json.dumps({"errorType": "BreakerError", "errorMessage": message, "requestId": "r", "stackTrace": []}),
                                encoding="utf-8")
        return str(TW.error_said(payload_file, "trip"))

    rule = TOPICS.Topics(THING, PREFIX + "_telemetry").rule          # the walk's case: a name topics.py takes, in an identifier's form
    for name in (rule, PREFIX, PREFIX + "_policy", "example_thing", "telemetry", "x", "StopIteration", "error", "Errors", "KeyError_",
                 "an_Error_of_sorts", "9Error", "Key-Error", "Key Error", "", "x" * 60 + "Error"):
        assert TW.own_message(stopped % name) is None, name
        assert said(stopped % name) == NOT_ITS_FORMS, name
    for name in ("KeyError", "RecursionError", "ClientError", "EndpointConnectionError", "HTTPException", "Error", "Exception", "_PrivateError",
                 "x" * 55 + "Exception"):
        assert TW.own_message(stopped % name) == stopped % name, name
        assert said(stopped % name) == OWN_SAID % ("trip", stopped % name, "payload-trip.json"), name
    # what the table cannot hold back: a name of the twin in the form of an error's class. That one is the redactor's
    odd = PREFIX + "Error"
    text = said(stopped % odd)
    assert TW.own_message(stopped % odd) is not None and odd in text
    out = TW.Out()
    out.use({"prefix": [PREFIX]})
    printed = out.clean(text)
    assert PREFIX not in printed and "no step names (<prefix>Error): look at the state by hand" in printed
    # the words: the file's and the README's say which of the two holds a name back in that slot
    words = ("In the one slot of the table that is neither a fixed word nor a count, the class's name in the sentence for an error no step "
             "names, the table holds the form the name of an error's class has (it ends in Error or Exception)")
    rest = "a name of the twin that had that form is held back by the redactor, through which everything printed goes, and not by the table"
    for where in (str(TW.own_message.__doc__), (REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8")):
        folded = " ".join(where.replace("`", "").split())
        assert words in folded and rest in folded, where[:60]


@pytest.mark.parametrize("what", ["trip", "dry-trip"])
def test_error_said_prints_a_clause_of_the_function_in_every_form_with_every_word_and_count_as_the_one_sentence(tmp_path: Path, what: str) -> None:
    """burst-spec, h3 item 7 (the same cases as the table test above, taken through error_said(), which is all either command
    prints of a function error): every one of breaker.py's 17 sentence forms, with every word it can put into it and a count of
    one, two and three figures, as the only clause of a message with the head and the count that are its own: printed whole,
    as the function wrote it, and by nothing else. Then every message of the list of what is NOT in its forms, under the
    function's own type, for both commands: the read-by-hand sentence, the command's own name in front."""
    forms, _heads, whys = breaker_forms()
    payload_file = tmp_path / "payload-trip.json"

    def said(message: Any) -> str:
        payload_file.write_text(json.dumps({"errorType": "BreakerError", "errorMessage": message, "requestId": "r", "stackTrace": []}),
                                encoding="utf-8")
        return str(TW.error_said(payload_file, what))

    seen = 0
    for form in forms:
        for word in clause_words(form, whys):
            for n in ("1", "12", "999"):
                clause = form.replace("%d", n).replace("%s", word)
                message = "the trip did not complete: 1 failure(s): " + clause
                assert said(message) == OWN_SAID % (what, message, "payload-trip.json"), message
                seen += 1
    assert len(forms) == 17 and seen == 3 * sum(len(clause_words(form, whys)) for form in forms) > 3 * len(forms)
    for case in OUTSIDE_ITS_FORMS:
        text = said(case)
        assert text == what + NOT_ITS_FORMS[len("trip"):] and text.startswith(what + ": the function's error is of the kind BreakerError"), (
            what, repr(case)[:80])
        assert "it says" not in text and "not disabled" not in text and "still connected" not in text
        assert not [c for c in text if ord(c) < 32 or ord(c) == 127]


def test_a_certificate_nobody_knows_in_the_listing_stops_the_create_of_another(started: Rig, tmp_path: Path) -> None:
    """WP7-verify-r2, NIT 4: what was left of WP7-verify-r1's SHOULD 2. The teardown of a create whose outcome is not known
    takes the record back on ONE read of the certificates' listing. With a listing that does not show yet what the create
    made, it said "nothing of it stands", and the next `apply certificate` made a SECOND certificate. Whether the real
    listing lags is not established. DECIDED: `apply` reads the same listing before it creates a step that is read by an
    id only a reply gives, and refuses while it holds a name neither the baseline nor a state knows."""
    rig = started.copy(tmp_path / "lag", logs=False)
    rig.edit(lambda a: a.update(reply_error={"iot create-certificate-from-csr": "InternalFailureException"}))
    assert "call 1 of 1 failed" in rig.go("apply", "certificate", expect=1).err
    rig.edit(lambda a: (a.pop("reply_error"), a.update(listing_lags={"iot list-certificates": 1})))
    ran = rig.run("teardown", "certificate", expect=0)              # the listing does not show the certificate yet, for this one read
    taken = ran.out
    assert "the record is taken back" in taken and status_of(rig, "certificate") == "absent" and len(rig.account()["certs"]) == 1
    made, since = rig.writes(), len(rig.log())
    ran = rig.go("apply", "certificate", expect=1)
    assert "refused: listed-not-ours:" in ran.err and "lists 1 name(s)" in ran.err and not clean(ran.text)
    assert "This rests on ONE read of the listing" in taken         # and the teardown had said what its word stood on
    assert rig.writes() == made and len(rig.account()["certs"]) == 1 and status_of(rig, "certificate") == "absent"
    assert [e["argv"][:2] for e in rig.log()[since:]] == [["sts", "get-caller-identity"], ["iot", "list-certificates"]]
    assert "1 name(s) the baseline lacks" in rig.run("verify-gone", expect=1).err              # what the refusal sends the owner to
    # by hand, as the README says: what the lost create made is deleted, and a new printing's approval makes ONE certificate
    rig.edit(lambda a: a["certs"].clear())
    since = len(rig.log())
    rig.go("apply", "certificate")
    assert len(rig.account()["certs"]) == 1 and status_of(rig, "certificate") == "created"
    sent = [e["argv"][:2] for e in rig.log()[since:]]
    assert sent.index(["iot", "list-certificates"]) < sent.index(["iot", "create-certificate-from-csr"])     # read before the create
    # a certificate a state knows is no stray: the rehearsal's does not stop the twin's, nor the twin's the rehearsal's
    both = started.copy(tmp_path / "both", logs=False)
    both.go("apply", "certificate", "--rehearsal")
    both.go("apply", "certificate")
    assert sorted(both.account()["certs"]) == sorted([CERT_1, CERT_2])
    other = started.copy(tmp_path / "other", logs=False)
    other.go("apply", "certificate")
    other.go("apply", "certificate", "--rehearsal")
    assert sorted(other.account()["certs"]) == sorted([CERT_1, CERT_2])
    # nor is one the baseline listed: it was there before the twin
    old = Rig(tmp_path / "old")
    stranger = hashlib.sha256(b"a certificate that was there before the twin").hexdigest()
    old.edit(lambda a: a["certs"].update({stranger: {"status": "INACTIVE", "policies": []}}))
    old.start()
    old.go("apply", "certificate")
    assert len(old.account()["certs"]) == 2 and status_of(old, "certificate") == "created"
    # a listing that says there is more of it is no listing to create on: refused as in every read, and nothing is made
    more = started.copy(tmp_path / "more", logs=False)
    more.edit(lambda a: a.update(reply_extra={"iot list-certificates": {"nextMarker": "more"}}))
    ran = more.go("apply", "certificate", expect=1)
    assert "refused: listing-incomplete:" in ran.err and more.account()["certs"] == {} and status_of(more, "certificate") == "absent"
    docstring = " ".join(str(TW.__doc__).split())
    assert "`apply` reads that listing again before it creates" in docstring
    readme = " ".join((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8").split())
    assert "reads the same listing before it creates" in readme and "one read of a listing" in readme


def test_the_breakers_zip_is_built_by_a_command_of_its_own(rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """the breaker contract, "twinctl builds the zip": one entry, a fixed time and mode, the same bytes on every build."""
    target = rig.inputs / "built" / "breaker.zip"
    rig.write_names(TWIN_BREAKER_ZIP=str(target))
    ran = rig.run("build-breaker", expect=0)
    data = target.read_bytes()
    assert "sha256 %s" % sha(data) in ran.out and base64.b64encode(hashlib.sha256(data).digest()).decode() in ran.out
    assert rig.log() == [] and not clean(ran.text) and str(target) not in ran.text
    rig.run("build-breaker", expect=0)
    assert target.read_bytes() == data == BREAKER_ZIP               # a second build: the same bytes, and the ones every test here runs
    # neither the source nor the zip holds one of the state's literals
    literals = json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))["literals"]
    assert len(literals) >= 6 and not [v for values in literals.values() for v in values if v.encode() in data or v.encode() in BREAKER_SOURCE]
    assert LS.findings(data.decode("utf-8", "replace"), False, list(IDENTIFIERS)) == []
    # a target inside a work tree is refused, and so is a source a checkout gave carriage returns
    rig.write_names(TWIN_BREAKER_ZIP=str(REPO / "sdv" / "cloud" / "breaker.zip"))
    assert "refused: inside-a-work-tree:" in rig.run("build-breaker", expect=1).err and not (REPO / "sdv" / "cloud" / "breaker.zip").exists()
    rig.write_names(TWIN_BREAKER_ZIP=None)
    assert "refused: input-unset:" in rig.run("build-breaker", expect=1).err
    rig.write_names(TWIN_BREAKER_ZIP=str(target))
    source = tmp_path / "breaker.py"
    source.write_bytes((REPO / "sdv" / "cloud" / "breaker" / "breaker.py").read_bytes().replace(b"\n", b"\r\n"))
    monkeypatch.setattr(TW, "BREAKER_SOURCE", source)
    target.unlink()
    assert "refused: source-has-a-carriage-return:" in rig.run("build-breaker", expect=1).err and not target.exists()
    # a source that would hold one of the state's literals is refused by its position, never by the value
    source.write_bytes((REPO / "sdv" / "cloud" / "breaker" / "breaker.py").read_bytes() + ("# %s\n" % THING).encode())
    ran = rig.run("build-breaker", expect=1)
    assert "refused: source-holds-a-literal:" in ran.err and not target.exists() and not clean(ran.text)
    # and one whose handler is not there would be created and fail at its first invoke
    source.write_bytes(b"def another(event, context):\n    return None\n")
    assert "refused: source-has-no-handler:" in rig.run("build-breaker", expect=1).err and not target.exists()
    # WP7-critic, ledger WP7#7 (WP7-verify-final's VT32). A source that is no UTF-8 at all, or holds a NUL, compiles to nothing: the
    # same refusal and no zip, never an error no check names
    for text in (b"def handler(event, context):\n    return None\n# \xff\xfe\n", b"\xc3\x28", b"def handler(event, context):\n    return None\n\x00"):
        source.write_bytes(text)
        ran = rig.run("build-breaker", expect=1)
        assert "refused: source-has-no-handler:" in ran.err and not target.exists() and "no check names" not in ran.text, text


# ================================================================================================= guards of the driver's WP7 parts
# WP7-verify-r2#3: ten of that stage's own mutants of the parts of twinctl.py WP7 changed lived in the whole file. Each is on a
# guard for an input the real function, the real SDK or a state this driver wrote does not give, or on a line of words; none
# showed the code wrong. Each is held below by the one thing it changes (the last two by what the state holds afterwards).

def test_build_breaker_takes_a_handler_at_the_top_of_the_source_and_no_nested_one(rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WP7-verify-r2#3 (T01). A function nested in another, or a method of a class, is not what the handler setting
    `breaker.handler` names: created from such a source the function would fail at its first invoke. Refused, no zip."""
    target = rig.inputs / "built" / "breaker.zip"
    rig.write_names(TWIN_BREAKER_ZIP=str(target))
    source = tmp_path / "breaker.py"
    monkeypatch.setattr(TW, "BREAKER_SOURCE", source)
    nested = (b"def another(event, context):\n    def handler(event, context):\n        return None\n    return handler\n",
              b"class Holder:\n    def handler(self, event, context):\n        return None\n",
              b"async def another(event, context):\n    def handler(event, context):\n        return None\n")
    for text in nested:
        source.write_bytes(text)
        ran = rig.run("build-breaker", expect=1)
        assert "refused: source-has-no-handler:" in ran.err and not target.exists() and rig.log() == [], text
    # a handler at the top, beside a nested one of the same name, is what is wanted: built
    source.write_bytes(b"def helper():\n    def handler():\n        return None\n\n\ndef handler(event, context):\n    return None\n")
    ran = rig.run("build-breaker", expect=0)
    assert target.is_file() and "sha256 %s" % sha(target.read_bytes()) in ran.out


def test_a_recorded_hash_that_is_no_sha256_in_hex_is_no_hash_and_the_function_cannot_be_compared(before_function: Rig, tmp_path: Path) -> None:
    """WP7-verify-r2#3 (T02). A state this driver wrote records a sha256 in lower-case hex. Anything else in its place (a
    hand-edited state, a damaged one) is no hash: `status` says the code cannot be compared, as for a state with none. Taken
    for a hash, it ends the command on an error of its own, or (upper-case hex) reads as the approved code."""
    twin = before_function.copy(tmp_path / "twin")
    twin.go("apply", "function")
    state = state_of(twin)
    good = state["steps"]["function"]["inputs"]["TWIN_BREAKER_ZIP"]
    assert good == sha(BREAKER_ZIP) and "as rendered" in status_lines(twin.run("status"))["function"]
    for recorded in ("not a hash", good[:-1], good + "0", good.upper(), "g" * 64, " " + good, good + "\n", ""):
        state["steps"]["function"]["inputs"]["TWIN_BREAKER_ZIP"] = recorded
        (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
        ran = twin.run("status")
        assert "no check names" not in ran.text, (recorded, ran.err)       # a hash taken for one stops the command on an error of its own
        line = status_lines(ran)["function"]
        assert "DIFFERS" in line and "its code cannot be compared: the state records no hash of the zip it was made from" in line, recorded
        assert "as rendered" not in line and "CodeSha256" not in line, recorded
    assert not clean("".join(r.text for r in twin.said))


def test_the_render_of_a_signing_request_ends_after_its_sha256_and_only_the_zips_line_adds_the_form_the_service_reports(
        rig: Rig, before_function: Rig, tmp_path: Path) -> None:
    """WP7-verify-r2#3 (T03). The approval covers the CONTENT of every file a create uploads, and the render prints its sha256.
    The form the service reports a function's CODE in (base64) is the zip's alone: a signing request has no such form."""
    def input_lines(ran: Ran) -> List[str]:
        return [line.strip() for line in ran.out.split("\n") if line.strip().startswith("input ")]

    csr = (rig.inputs / "device.csr").read_bytes()
    rig.shown("apply", "certificate")
    assert input_lines(rig.said[-1]) == ["input TWIN_CSR: sha256 " + sha(csr)]
    rig.shown("apply", "certificate", "--rehearsal")
    assert input_lines(rig.said[-1]) == ["input TWIN_REHEARSAL_CSR: sha256 " + sha(csr)]
    twin = before_function.copy(tmp_path / "twin")
    twin.shown("apply", "function")
    form = base64.b64encode(hashlib.sha256(BREAKER_ZIP).digest()).decode()
    zip_line = "input TWIN_BREAKER_ZIP: sha256 %s; as the service reports a function's code: %s" % (sha(BREAKER_ZIP), form)
    assert input_lines(twin.said[-1]) == [zip_line]


def test_a_trips_record_with_entries_that_are_no_objects_is_read_by_hand_and_the_status_still_follows(twin: Rig) -> None:
    """WP7-verify-r2#3 (T05, T06). The write words are printed from the function's own record, in their form only. A record
    whose rule, certificates or connections are not objects is none of that form (the real function never gives one): said,
    and the `status` that is the proof for the calls by hand is still printed, not lost to an error after the invoke."""
    unread = "trip: the record does not hold its write words in their form: it is read by hand, in the state directory's replies"
    for planted in ({"certificates": ["x"]}, {"certificates": [None]}, {"connections": ["x"]}, {"connections": [7]},
                    {"rule": "x"}, {"rule": None}, {"rule": ["write"]}):
        twin.edit(lambda a, planted=planted: a.update(record_extra=planted))
        ran = twin.run("trip", expect=0)
        assert unread in ran.out and STATUS_SAID in ran.out and WRITES_SAID not in ran.out, planted
        assert "no check names" not in ran.text and not clean(ran.text), planted
    twin.edit(lambda a: a.pop("record_extra"))
    ran = twin.run("trip", expect=0)                                # the same trip with its record whole: the words are printed
    assert WRITES_SAID in ran.out and unread not in ran.out and STATUS_SAID in ran.out


def test_a_payload_file_that_cannot_be_opened_or_read_is_the_read_by_hand_sentence_and_ends_no_command(tmp_path: Path) -> None:
    """WP7-verify-r2#3 (T08). The function's record is read from the file the CLI wrote. A file that is not there, a path
    that is a directory, and bytes that are no text are all `read by hand`: the command goes on to its status. The same three
    paths are given to the other two readers of the record (WP7-critic, ledger WP7#5 and #6; WP7-verify-final's VT12 and VT13:
    each lived with an OSError let out of its reader and the whole file passing): error_said() and status_facts()."""
    directory = tmp_path / "a-directory.json"
    directory.mkdir()
    binary = tmp_path / "bytes.json"
    binary.write_bytes(b"\xff\xfe\x00 these are no text")
    status_unread = "function-status: the record does not hold the two facts in their form: it is read by hand, in the state directory's replies"
    for what in ("trip", "dry-trip"):
        unread = "%s: the record does not hold its write words in their form: it is read by hand, in the state directory's replies" % what
        for path in (tmp_path / "there-is-no-such-file.json", directory, binary):
            assert TW.trip_facts(path, what) == unread, (what, path.name)
            # error_said(): its read-by-hand sentence, with the file's name (this branch is the one a payload that cannot be read takes)
            said = "%s: the function's error is read by hand, in the state directory's replies (%s)" % (what, path.name)
            assert TW.error_said(path, what) == said, (what, path.name)
    for path in (tmp_path / "there-is-no-such-file.json", directory, binary):
        assert TW.status_facts(path) == status_unread, path.name


def test_status_offers_recover_for_a_step_the_state_made_and_for_one_it_never_made_it_does_not(twin: Rig, rig: Rig) -> None:
    """WP7-verify-r2#3 (T10). The line of a step with no read says where the way back is, when there is one to take: a step
    the state records as made, whose id it lost. A step never made has nothing to put back."""
    hint = "`twinctl recover certificate` puts it back from a reply"
    steps = ("certificate", "attachments", "go-live-certificate")
    fresh = status_lines(rig.run("status", expect=0))
    for step in steps:
        assert re.search(r"%s +row \S+ +absent +no read: the state holds no id to read it by" % step, fresh[step]), fresh[step]
        assert "recover" not in fresh[step], fresh[step]
    forget(twin, "certificate_id")
    gone = status_lines(twin.run("status", expect=1))
    for step in steps:
        assert re.search(r"%s +row \S+ +created +no read: the state holds no id to read it by" % step, gone[step]), gone[step]
        assert hint in gone[step], gone[step]


def test_status_facts_prints_a_version_of_digits_and_dots_and_a_boolean_and_nothing_else(tmp_path: Path) -> None:
    """WP7-verify-r2#3 (T13). The runtime's SDK version is printed only in the form it has (one to four groups of one to four
    digits, two to four groups in all); a version with letters, words or blanks in it is said, and nothing of it is printed."""
    said = "function-status: the record does not hold the two facts in their form: it is read by hand, in the state directory's replies"
    path = tmp_path / "status.json"

    def facts(record: Any) -> str:
        path.write_text(json.dumps(record), encoding="utf-8")
        return str(TW.status_facts(path))

    for version in ("1.4a.9", "1.40.0rc1", "1", "1.2.3.4.5", "12345.1", "1..2", "v1.2", "", " 1.2", "1.2\n", "1.2-beta", "1.2+x", "1.2.x",
                    1.2, None, ["1.2"]):
        assert facts({"boto3": version, "has_delete_connection": True}) == said, version
    for has in ("yes", "true", 1, None, [True]):
        assert facts({"boto3": "1.40.9", "has_delete_connection": has}) == said, has
    assert facts({"has_delete_connection": True}) == said and facts(["1.40.9"]) == said and facts("1.40.9") == said
    for version in ("1.40.9", "1.2", "1000.2000.3000.4000", "9999.9999"):          # the widest: four groups of four digits
        assert facts({"boto3": version, "has_delete_connection": True}) == (
            "function-status: the runtime's boto3 is %s; its data-plane client has DeleteConnection: yes" % version)
    assert "DeleteConnection: NO (" in facts({"boto3": "1.40.9", "has_delete_connection": False})


@pytest.mark.parametrize("status", ["creating", "partial"])
def test_recover_records_the_create_call_it_found_made_as_done_and_as_sent(started: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                         status: str) -> None:
    """WP7-verify-r2#3 (T14). A step half made, whose state is a copy older than the call's record, holds no call as sent or
    done. Once the account showed the certificate and recover put its id back, the step records both (`unverified`), so that
    the state says what the account showed; the next `apply` reads it again and records it made."""
    rig = started.copy(tmp_path / "older", logs=False)
    digest = rig.shown("apply", "certificate")

    def ends(t: Any, index: int, reply: Any) -> None:
        raise SystemExit(137)

    with monkeypatch.context() as m:
        m.setattr(TW, "_after_certificate", ends)                   # the reply is written, the call is recorded, and the run ends there
        with pytest.raises(SystemExit):
            rig.run("apply", "certificate", "--approve", "certificate:" + digest)
    state = state_of(rig)
    state["steps"]["certificate"].update(status=status, done=[], sent=[])           # the state as an older copy of it had it
    (rig.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert "certificate_id" not in state_of(rig)["facts"] and len(rig.account()["certs"]) == 1
    rig.go("recover", "certificate")
    step = state_of(rig)["steps"]["certificate"]
    assert (step["status"], step["done"], step["sent"]) == ("unverified", [0], [0]) and state_of(rig)["facts"]["certificate_id"] == CERT_1
    assert "already made, nothing was created" in rig.go("apply", "certificate").out and status_of(rig, "certificate") == "created"
    assert len(rig.account()["certs"]) == 1


def test_a_failing_run_of_an_action_whose_record_is_taken_back_already_takes_nothing_back_again(twin: Rig) -> None:
    """WP7-verify-r2#3 (T16). A run that does not come to its end takes the record of the action's earlier run back. When
    that record is taken back already (`stale`: the run before failed too) there is nothing to take back: no line says it
    is, and what stood on the record was taken back at the first failure."""
    after = ["alarm-test-" + k for k in BREAKER] + ["reattach-policy"]
    twin.edit(lambda a: a.update(function_faults=[dict(DETACH_REFUSED)]))
    first = twin.go("apply", "dry-trip", expect=1)
    assert "the record of its earlier run is taken back" in first.err and "6 record(s) stood on this step as it was and are taken back" in first.out
    assert status_of(twin, "dry-trip") == "stale" and {status_of(twin, s) for s in after} == {"stale"}
    twin.edit(lambda a: a.update(function_faults=[dict(DETACH_REFUSED)]))
    second = twin.go("apply", "dry-trip", expect=1)
    assert "apply dry-trip: the function did not run to its end" in second.err and "taken back" not in second.text, second.text
    assert status_of(twin, "dry-trip") == "stale" and {status_of(twin, s) for s in after} == {"stale"} and not clean(second.text)
    assert state_of(twin)["steps"]["dry-trip"]["stale_for"] == "dry-trip"


def test_the_functions_environment_and_its_roles_policy_name_the_same_resources(built: Rig) -> None:
    """IAM scopes each of the function's calls to one resource; the function takes what it calls with from its
    environment. The two documents are rendered from the same names: here they are held to each other, call by call."""
    a = built.account()
    env = a["functions"][PREFIX + "-breaker"]["config"]["Environment"]["Variables"]
    assert sorted(env) == ["TWIN_CERTIFICATE_ARNS", "TWIN_CLIENT_IDS", "TWIN_POLICY", "TWIN_RULE"]
    policy = a["roles"][ROLES["breaker-role"]]["policies"][ROLES["breaker-role"] + "-policy"]
    resource = {action: st["Resource"] for st in policy["Statement"] for action in TW._listed(st["Action"])}
    cert = env["TWIN_CERTIFICATE_ARNS"]
    assert cert == iot_arn("cert", CERT_1)
    for action in ("iot:UpdateCertificate", "iot:DetachPolicy", "iot:DescribeCertificate"):
        assert resource[action] == cert, action                     # DetachPolicy is scoped to its target, not to the policy
    for action in ("iot:DisableTopicRule", "iot:GetTopicRule"):
        assert resource[action] == iot_arn("rule", env["TWIN_RULE"]), action
    assert resource["iot:DeleteConnection"] == iot_arn("client", env["TWIN_CLIENT_IDS"])
    assert resource["iot:ListTargetsForPolicy"] == iot_arn("policy", env["TWIN_POLICY"])
    assert TW.HANDLER == "breaker.handler" and a["functions"][PREFIX + "-breaker"]["config"]["Handler"] == TW.HANDLER


# ================================================================================================= the judges and the gates a re-check found unheld
# WP7-tests20: regression cases for the judges and gates below; no mutation-run result is published here.

def _bucket(a: Dict[str, Any]) -> Dict[str, Any]:
    return a["buckets"]["%s-telemetry-%s" % (PREFIX, SUFFIX)]


def _breaker(a: Dict[str, Any]) -> Dict[str, Any]:
    return a["functions"][PREFIX + "-breaker"]


def _device_policy_widened(a: Dict[str, Any]) -> None:
    doc = json.loads(a["policies"][PREFIX + "-device"]["document"])
    doc["Statement"].append({"Sid": "Anything", "Effect": "Allow", "Action": "iot:Publish", "Resource": "*"})
    a["policies"][PREFIX + "-device"]["document"] = json.dumps(doc)


def _taken_down_from_go_live(rig: Rig) -> None:
    """The two go-live steps torn down, in teardown's order: the rule is disabled again and the state no longer says it is live."""
    rig.go("teardown", "go-live-certificate")
    rig.go("teardown", "go-live-rule")


LAYER = "arn:aws:lambda:%s:%s:layer:example:1" % (REGION, ACCOUNT)
VPC = {"SubnetIds": ["subnet-0aaaaaaaaaaaaaaa1"], "SecurityGroupIds": ["sg-0123abcd"]}      # ids tests/test_no_real_identifiers.py lists
OTHER_ROLE_ARN = "arn:aws:iam::%s:role/another-role" % ACCOUNT
# (step, what is done to the built twin first, what the account is then changed to, the one reason `apply` must give)
READ_BACK = [
    pytest.param("bucket", None, lambda a: _bucket(a).update(ownership="ObjectWriter"), "its object ownership is not bucket owner enforced",
                 id="bucket_ownership_not_enforced"),
    pytest.param("bucket", None, lambda a: _bucket(a).update(versioning="Enabled"), "versioning is on", id="bucket_versioning_on"),
    pytest.param("bucket", None, lambda a: _bucket(a)["lifecycle"]["Rules"][0]["Expiration"].update(Days=3650), "its lifecycle is not the render",
                 id="bucket_lifecycle_another"),
    pytest.param("stream", None, lambda a: a["streams"][PREFIX + "-telemetry"].update(status="CREATING"), "it is CREATING, not ACTIVE",
                 id="stream_still_creating"),
    pytest.param("stream", None, lambda a: a["streams"][PREFIX + "-telemetry"].update(status="FAILED"), "it is in another state, not ACTIVE",
                 id="stream_in_another_state"),
    pytest.param("rule", _taken_down_from_go_live, lambda a: a["rules"][PREFIX + "_telemetry"].update(ruleDisabled=False),
                 "it is enabled before go-live", id="rule_enabled_before_go_live"),
    pytest.param("rule", None, lambda a: a["rules"][PREFIX + "_telemetry"].update(ruleDisabled=True), "it is disabled (tripped, or not live)",
                 id="rule_disabled_after_go_live"),
    pytest.param("thing", None, lambda a: a["things"][THING].update(attributes={"owner": "somebody"}), "it has attributes",
                 id="thing_with_attributes"),
    pytest.param("policy", None, _device_policy_widened, "its document is not the render", id="device_policy_another"),
    pytest.param("glue", None, lambda a: a["glue"][PREFIX + "_twin"]["tables"]["telemetry"]["StorageDescriptor"].update(Location="s3://elsewhere/"),
                 "its table is not the render", id="glue_table_another"),
    pytest.param("workgroup", None, lambda a: a["workgroups"][PREFIX + "-twin"]["configuration"].update(BytesScannedCutoffPerQuery=1),
                 "its configuration is not the render", id="workgroup_configuration_another"),
    pytest.param("firehose-log", None, lambda a: a["log_groups"][PREFIX + "-firehose-errors"].update(retention=7),
                 "its retention is not %d days" % TW.RETENTION_DAYS, id="firehose_log_retention_another"),
    pytest.param("breaker-log", None, lambda a: a["log_groups"]["/aws/lambda/" + PREFIX + "-breaker"].update(retention=7),
                 "its retention is not %d days" % TW.RETENTION_DAYS, id="breaker_log_retention_another"),
    pytest.param("function", None, lambda a: _breaker(a)["config"].update(Layers=[{"Arn": LAYER}]), "it has a layer or a VPC",
                 id="function_with_a_layer"),
    pytest.param("function", None, lambda a: _breaker(a)["config"].update(VpcConfig=VPC), "it has a layer or a VPC", id="function_in_a_vpc"),
    pytest.param("function", None, lambda a: _breaker(a)["urls"].append({"AuthType": "NONE", "FunctionUrl": "https://example.invalid/"}),
                 "it has a function URL", id="function_with_a_url"),
    pytest.param("alarms", None, lambda a: a["alarms"][PREFIX + "-shadow"].update(StateValue="ALARM"), "the alarm shadow is in ALARM",
                 id="alarm_in_alarm"),
    pytest.param("alarm-notice", None, lambda a: a["alarms"][PREFIX + "-errors"].update(StateValue="ALARM"), "the alarm errors is in ALARM",
                 id="notice_alarm_in_alarm"),
    pytest.param("iot-logging", None, lambda a: a["iot_logging"].update(defaultLogLevel="DEBUG"), "it is not ERROR with the owner-made role",
                 id="iot_logging_level_another"),
    pytest.param("iot-logging", None, lambda a: a["iot_logging"].update(roleArn=OTHER_ROLE_ARN), "it is not ERROR with the owner-made role",
                 id="iot_logging_role_another"),
]


@pytest.mark.parametrize("step,setup,change,said", READ_BACK)
def test_a_step_read_back_otherwise_than_rendered_is_said_by_its_one_reason_and_nothing_is_made_again(twin: Rig, step: str, setup: Any,
                                                                                                      change: Any, said: str) -> None:
    """The proving reads of a step that stands are judged against its render again whenever it is applied (or `status` is
    asked): each value a judge compares is changed in the account on its own, and the step must say that one reason."""
    if setup is not None:
        setup(twin)
    writes = twin.writes()
    assert "already made, nothing was created" in twin.go("apply", step).out                # as the build left it, it reads as rendered
    twin.edit(change)
    ran = twin.go("apply", step, expect=1)
    assert "what is read back is not the render:" in ran.err
    assert [line for line in ran.err.split("\n") if line.startswith("  - ")] == ["  - " + said], ran.err
    assert twin.writes() == writes and not clean(ran.text)


@pytest.mark.parametrize("how", ["partial", "unverified", "creating"])
def test_a_step_stands_only_on_a_step_recorded_as_made_and_proven(tmp_path: Path, how: str) -> None:
    """A step that was half made, made and not proven, or is being made is not a ground to build on (the gate that the
    first step of the table to stand on another is refused by)."""
    if how == "unverified":                                         # made, and the account says the stream is still being created
        rig = Rig(tmp_path / "twin").build(until="stream")
        rig.edit(lambda a: a.update(stream_status="CREATING"))
        ran = rig.go("apply", "stream", expect=1)
        assert "it is CREATING, not ACTIVE" in ran.err
        blocker, consumer = "stream", "rule"
    else:
        rig = Rig(tmp_path / "twin").start()
        if how == "partial":
            rig.edit(lambda a: a["faults"].append({"service": "s3api", "op": "put-bucket-lifecycle-configuration", "code": "InternalError"}))
            rig.go("apply", "bucket", expect=1)
        else:
            rig.go("apply", "bucket")
            state = state_of(rig)
            state["steps"]["bucket"]["status"] = "creating"
            (rig.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
        blocker, consumer = "bucket", "glue"
    assert status_of(rig, blocker) == how
    writes = rig.writes()
    ran = rig.go("apply", consumer, expect=1)
    assert "refused: step-needs:" in ran.err and "the step %s is not recorded as made and proven" % blocker in ran.err
    assert rig.writes() == writes and status_of(rig, consumer) == "absent"


def test_a_function_that_ends_in_an_error_is_not_recorded_as_having_run(twin: Rig) -> None:
    """An invoke the runtime answers with a function error did not run to its end: the action says so, and does not record
    itself as done (the state it stands in is the one of a step that had not run yet)."""
    state = state_of(twin)
    del state["steps"]["function-status"]
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    twin.edit(lambda a: a.update(function_error=True))
    since = len(twin.log())
    ran = twin.go("apply", "function-status", expect=1)
    assert "the function did not run to its end" in ran.err and [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]]
    assert status_of(twin, "function-status") == "absent"
    twin.edit(lambda a: a.update(function_error=False))
    assert "apply function-status: done; recorded" in twin.go("apply", "function-status").out
    assert status_of(twin, "function-status") == "done"


def _open_to_the_world_in_ipv6(a: Dict[str, Any]) -> None:
    a["security_groups"][0]["IpPermissions"][0]["Ipv6Ranges"].append({"CidrIpv6": "::/0"})


def _another_ipv6_range(a: Dict[str, Any]) -> None:
    a["security_groups"][0]["IpPermissions"][0]["Ipv6Ranges"].append({"CidrIpv6": "2001:db8::/32"})


@pytest.mark.parametrize("change,shape", [
    (_open_to_the_world_in_ipv6, {"groups": 1, "cidr_rules": 2, "open_to_the_world": 1, "tcp_22_from_one_address": 1}),
    (_another_ipv6_range, {"groups": 1, "cidr_rules": 2, "open_to_the_world": 0, "tcp_22_from_one_address": 2}),
], ids=["ipv6_open_to_the_world", "ipv6_another_range"])
def test_exit_checks_counts_a_security_groups_ipv6_ranges_as_it_counts_its_ipv4_ones(twin: Rig, tmp_path: Path, change: Any,
                                                                                    shape: Dict[str, int]) -> None:
    live(twin)
    twin.edit(change)
    capture = tmp_path / "capture"
    ran = twin.run("exit-checks", "--capture", capture, expect=1)
    failed = [line.split(None, 1)[1] for line in ran.out.split("\n") if line.startswith("  FAIL ")]
    assert len(failed) == 1 and failed[0].startswith("security groups"), ran.out
    results = {c["check"]: c for c in json.loads((capture / "exit-checks.json").read_text(encoding="utf-8"))["checks"]}
    assert results["security groups"]["shape"] == shape


_DEFAULT_DOMAINS = [{"domainConfigurationName": "iot:Data-ATS", "serviceType": "DATA"},
                    {"domainConfigurationName": "iot:CredentialProvider", "serviceType": "CREDENTIAL_PROVIDER"}]


@pytest.mark.parametrize("domains,verdict,shape", [
    (_DEFAULT_DOMAINS, "pass", {"listed": 2, "custom": 0}),
    (_DEFAULT_DOMAINS + [{"domainConfigurationName": "iot:Jobs", "serviceType": "JOBS"}], "pass", {"listed": 3, "custom": 0}),
    (_DEFAULT_DOMAINS + [{"domainConfigurationName": "telemetry-domain", "serviceType": "DATA"}], "FAIL", {"listed": 3, "custom": 1}),
    ([{"serviceType": "DATA"}], "FAIL", {"listed": 1, "custom": 1}),
    ([{"domainConfigurationName": 7}], "FAIL", {"listed": 1, "custom": 1}),
    (["iot:Data-ATS"], "FAIL", {"listed": 1, "custom": 1}),
], ids=["the_two_defaults", "three_defaults", "a_custom_one", "no_name", "a_name_that_is_no_string", "no_object"])
def test_exit_checks_takes_the_default_endpoints_domain_configurations_and_fails_on_any_other(twin: Rig, tmp_path: Path, domains: Any,
                                                                                             verdict: str, shape: Dict[str, int]) -> None:
    """A5 (2026-10-16) listed iot:Data-ATS and iot:CredentialProvider in an account with no custom domain, and the check
    failed on them. A name with a colon is one no customer can make (CreateDomainConfiguration takes [\\w.-]+, a listing's
    names are [\\w.:-]+), so only a listed configuration without one is a custom domain; an entry that does not show its
    name as a string counts as one."""
    live(twin)
    twin.edit(lambda a: a.update(domains=domains))
    capture = tmp_path / "capture"
    ran = twin.run("exit-checks", "--capture", capture, expect=1)          # Athena's paths are not given: not met either way
    line = [x for x in ran.out.split("\n") if "IoT domain configurations" in x]
    assert len(line) == 1 and line[0].split()[0] == verdict, ran.out
    results = {c["check"]: c for c in json.loads((capture / "exit-checks.json").read_text(encoding="utf-8"))["checks"]}
    assert results["IoT domain configurations"]["shape"] == shape


def test_the_objects_are_not_deleted_by_a_caller_the_profile_became_after_the_listing(rig: Rig) -> None:
    """The listing that is approved is read under the operator role, and the read that arms the delete is another read: a
    profile repointed between the two is refused, whatever the first read said."""
    rig.go("apply", "bucket")
    keys = ["telemetry/dt=2026-01-01/%04d" % i for i in range(3)]
    rig.edit(lambda a: _bucket(a).update(objects=list(keys)))
    own = rig.shown("teardown", "bucket-objects")
    writes = rig.writes()
    session = rig.account()["identity"]
    rig.edit(lambda a: a.update(identity_then=[{"UserId": "x", "Arn": j("arn:aws:sts::", ACCOUNT, ":assumed-role/another-role/session")}]))
    ran = rig.run("teardown", "bucket-objects", "--approve", "bucket-objects:" + own, expect=1)
    assert "refused: identity-not-the-operator-role:" in ran.err and rig.writes() == writes and _bucket(rig.account())["objects"] == keys
    # refused before anything was sent: that approval is not spent, and the operator role's own session is let through
    rig.edit(lambda a: a.update(identity=session, identity_then=[]))
    ran = rig.run("teardown", "bucket-objects", "--approve", "bucket-objects:" + own, expect=0)
    assert "3 object(s) deleted" in ran.out and _bucket(rig.account())["objects"] == []


def test_the_approval_of_emptying_the_bucket_lets_one_run_through(rig: Rig) -> None:
    """Emptying the bucket is permanent: one printing of its listing lets one run through. The same keys listed again (a
    writer put them back) make the same listing and the same hash, and the earlier yes does not cover them."""
    rig.go("apply", "bucket")
    keys = ["telemetry/dt=2026-01-01/%04d" % i for i in range(3)]
    rig.edit(lambda a: _bucket(a).update(objects=list(keys)))
    own = rig.shown("teardown", "bucket-objects")
    rig.run("teardown", "bucket-objects", "--approve", "bucket-objects:" + own, expect=0)
    assert _bucket(rig.account())["objects"] == []
    writes = rig.writes()
    rig.edit(lambda a: _bucket(a).update(objects=list(keys)))
    ran = rig.run("teardown", "bucket-objects", "--approve", "bucket-objects:" + own, expect=1)
    assert "refused: approval-spent:" in ran.err and rig.writes() == writes and _bucket(rig.account())["objects"] == keys
    assert rig.shown("teardown", "bucket-objects") == own           # printed again: the same hash, and the owner's yes again
    rig.run("teardown", "bucket-objects", "--approve", "bucket-objects:" + own, expect=0)
    assert _bucket(rig.account())["objects"] == []


def test_the_notice_topic_is_not_recorded_as_made_while_its_subscription_waits_for_the_owner(rig: Rig) -> None:
    """The topic is made and the e-mail subscription is pending until the owner confirms it with the token from the mail:
    until then nothing the notice stands on is proven, and the same approval reads it again."""
    digest = rig.shown("apply", "notice-topic")
    ran = rig.run("apply", "notice-topic", "--approve", "notice-topic:" + digest, expect=1)
    assert "made, and what is read back is not the render:" in ran.err
    assert "its subscription waits for the owner's confirmation" in ran.err and status_of(rig, "notice-topic") == "unverified"
    assert len(rig.account()["topics"]) == 1
    rig.edit(lambda a: a["topics"][list(a["topics"])[0]]["subscriptions"][0].update(confirmed=True))
    again = rig.run("apply", "notice-topic", "--approve", "notice-topic:" + digest, expect=0)
    assert "already made, nothing was created" in again.out and status_of(rig, "notice-topic") == "created"


def test_verify_gone_does_not_call_gone_what_it_could_not_read(rig: Rig) -> None:
    """A recorded step whose read is refused (a denied call, not a "not found") is not settled: verify-gone counts it."""
    rig.go("apply", "thing")
    rig.go("teardown", "thing")
    assert "verify-gone: gone" in rig.run("verify-gone", expect=0).out
    rig.edit(lambda a: a["faults"].append({"service": "iot", "op": "describe-thing", "code": "AccessDeniedException"}))
    writes = rig.writes()
    ran = rig.run("verify-gone", expect=1)
    assert re.search(r"by name\s+thing\s+not read \(read-failed\)", ran.err), ran.err
    assert "verify-gone: NOT gone: 1 found by name" in ran.err and "verify-gone: gone" not in ran.text and rig.writes() == writes
    assert "verify-gone: gone" in rig.run("verify-gone", expect=0).out                           # the fault was one call's: read again, it is gone


# ================================================================================================= branch-scan (gap ab): the one test that runs git

def _git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.name=An Example", "-c", "user.email=example@example.com", "-c", "commit.gpgsign=false",
                           "-c", "core.autocrlf=false"] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=False)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8", "replace").strip()


def test_branch_scan_finds_a_literal_one_commit_adds_and_the_next_removes_and_one_only_in_a_commit_message(tmp_path: Path) -> None:
    """Runs git on a fixture repository under the temporary directory. From Windows Git Bash: sdv/stack/wsl-pytest.args
    deselects it in WSL, where no git runs for this work tree's tests."""
    repo = tmp_path / "fixture"
    repo.mkdir()
    added, said, kept, ignored, never = (j("thing-of-", "commit-two"), j("rule_in_a_", "message"), j("bucket-still-", "there"),
                                         j("name-in-an-", "ignored-file"), j("never-", "written"))
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "b.txt").write_text("the connector logs to %s\n" % added, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add b")
    (repo / "b.txt").write_text("the connector logs to a thing\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "take the name out of b")
    (repo / "c.txt").write_text("three\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c, for the rule %s" % said)
    state = tmp_path / "state"
    state.mkdir()

    def scan(literals: Dict[str, List[str]], *more: str) -> Ran:
        (state / "literals.json").write_text(json.dumps({"v": 1, "literals": literals}), encoding="utf-8")
        return twinctl(["--state", str(state), "branch-scan", "--repo", str(repo), "--base", base] + list(more), {})

    ran = scan({"thing": [never, added], "rule": [said]})
    assert ran.rc == 1 and "branch-scan: NOT clean" in ran.err
    found = sorted(line.strip() for line in ran.err.split("\n") if line.strip().startswith("FOUND"))
    assert len(found) == 2 and found[0].startswith("FOUND value 1 of the kind rule in commit messages: 1 (")
    assert found[1].startswith("FOUND value 2 of the kind thing in history: 2 (")        # the commit that adds it, the one that removes it
    assert not [v for v in (added, said, never) if v in ran.text]
    # a literal in a file that is tracked, and in one that is untracked and not ignored; an ignored file is not searched
    (repo / "a.txt").write_text("one %s\n" % kept, encoding="utf-8")
    (repo / "new.txt").write_text("untracked %s\n" % kept, encoding="utf-8")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "x.txt").write_text(ignored + "\n", encoding="utf-8")
    ran = scan({"bucket": [kept], "local": [ignored]})
    assert ran.rc == 1 and "FOUND value 1 of the kind bucket in files: 2 (a.txt, new.txt)" in ran.err and "kind local" not in ran.err
    # the record commit, on a branch of its own
    _git(repo, "checkout", "-q", "-b", "records", base)
    (repo / "record.txt").write_text("the capture names %s\n" % never, encoding="utf-8")
    _git(repo, "add", "record.txt")
    _git(repo, "commit", "-q", "-m", "a record")
    _git(repo, "checkout", "-q", "-")
    ran = scan({"thing": [never]})                                  # it is in no file and in no commit of this branch
    assert ran.rc == 0 and "branch-scan: clean" in ran.out
    ran = scan({"thing": [never]}, "--record", "records")
    assert ran.rc == 1 and "FOUND value 1 of the kind thing in history: 1 (" in ran.err and "and the record commit" in ran.out
    ran = scan({"thing": [never]}, "--record=--upload-pack=x")
    assert ran.rc == 1 and "revision-invalid" in ran.err
    # the state directory and its literals file are held to the same rule as everywhere
    assert "inside-a-work-tree" in twinctl(["--state", str(repo / "state"), "branch-scan", "--repo", str(repo)], {}).err
    (state / "literals.json").unlink()
    assert twinctl(["--state", str(state), "branch-scan", "--repo", str(repo), "--base", base], {}).rc == 1


# ================================================================================================= WP8's fixes before A2 (wp8-core): the
# operator policy's Glue statement (K1), the stop and its file of the four calls by hand (K2), the one region that is not taken (K3).
# Each test fails on the tree as it was.

def iam_matches(pattern: str, arn: str) -> bool:
    """A resource of a policy against an ARN, as the service matches one: `*` is any run of characters, the separators among
    them, `?` is one character, and nothing else is special."""
    return re.fullmatch("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern), arn, re.S) is not None


# What the service authorization reference lists as REQUIRED for glue:DeleteDatabase, as the re-check of 2026-10-12 read its page (the
# root catalog, the database, a table, a user-defined function), each by the form its ARN has after the account. From that reading,
# never from an account.
GLUE_DELETE_DATABASE_NEEDS = {"rootcatalog": "catalog", "database": "database/%(database)s", "table": "table/%(database)s/%(table)s",
                              "userdefinedfunction": "userDefinedFunction/%(database)s/%(function)s"}


def test_the_operator_roles_glue_statement_holds_every_resource_the_databases_delete_is_authorised_on_and_none_outside_the_prefix(
        planned: Rig) -> None:
    """K1 (the re-check of Codex's T12, D12-1). The teardown's `glue delete-database` is authorised on the catalog, the database,
    every table and EVERY USER-DEFINED FUNCTION in it; the statement had the first three, so the delete could be refused. The twin
    makes no function: the resource is there for the authorisation alone, and it is no wider than the prefix. The driver's own check
    of this policy against its calls judges actions and conditions and matches NO resource (operator_gaps()), so it could not see
    the gap: this test holds it, on the rendered document the owner makes the role from (A1 row 3)."""
    doc = planned.doc("operator-role", "operator-role-policy")
    st = statements(doc)["Glue"]
    resources = listed(st["Resource"])
    assert "glue:DeleteDatabase" in st["Action"] and st["Effect"] == "Allow" and "Condition" not in st
    delete, = [c for s in planned.plan() if s["id"] == "glue" for c in s["deletes"] if c[:2] == ["glue", "delete-database"]]
    twins = delete[delete.index("--name") + 1]
    rehearsals = str(TW.Names(dict(planned.names()), rehearsal=True).glue_database)      # A2 rehearses the kind under the same role
    assert twins == PREFIX + "_twin" and rehearsals.startswith(PREFIX) and rehearsals != twins
    glue = "arn:aws:glue:%s:%s:" % (REGION, ACCOUNT)
    for database in (twins, rehearsals):
        for kind, form in GLUE_DELETE_DATABASE_NEEDS.items():
            arn = glue + form % {"database": database, "table": "telemetry", "function": "a_function_nobody_made"}
            assert [r for r in resources if iam_matches(r, arn)], (kind, database == twins)
    # ... and nothing of a database that is not under the prefix, of another account or of another region
    outside = [glue + "userDefinedFunction/another_database/f", glue + "table/another_database/t", glue + "database/another_database",
               "arn:aws:glue:%s:%s:userDefinedFunction/%s/f" % (REGION, OTHER_ACCOUNT, twins),
               "arn:aws:glue:%s:%s:userDefinedFunction/%s/f" % ("eu-north-1", ACCOUNT, twins)]
    for i, arn in enumerate(outside):
        assert not [r for r in resources if iam_matches(r, arn)], i
    # the driver's second copy: the function resource is on its one list of the wildcards an Allow may hold, by its exact string
    exceptions = TW.wildcard_exceptions(TW.Names(dict(planned.names())))[("operator-role-policy", "Glue")]
    assert sorted(exceptions) == sorted(r for r in resources if "*" in r) and glue + "userDefinedFunction/" + PREFIX + "*/*" in exceptions
    # what the driver's own check sees of it: nothing. With the function resource taken out again it still reports no gap.
    short = copy.deepcopy(doc)
    _allow(short, "Glue")["Resource"] = [r for r in resources if "userDefinedFunction" not in r]
    assert len(_allow(short, "Glue")["Resource"]) == 3 and TW.operator_gaps(short, calls_of(planned)) == []


@pytest.mark.parametrize("argv", [["literals"], ["plan", "--no-cli"], ["baseline", "--again"], ["status"], ["apply", "bucket"], ["teardown"],
                                  ["teardown", "bucket"], ["verify-gone"], ["restore"], ["build-breaker"], ["recover", "certificate"],
                                  ["exit-checks", "--capture", "CAPTURE"], ["--rehearsal", "plan", "--no-cli"]],
                         ids=lambda argv: "-".join(a.strip("-").lower() for a in argv))
def test_the_one_region_the_twin_is_not_written_for_is_refused_where_the_names_are_read_by_its_key_and_never_by_its_value(
        rig: Rig, tmp_path: Path, argv: List[str]) -> None:
    """K3 (the re-check of Codex's T11, row L22; an old NIT of WP6). The bucket's create passes a LocationConstraint of the twin's
    region, which the service refuses for the one region whose buckets take none; and the exit's check reads the account's Block
    Public Access a second time THROUGH that region. Refused where the names are held to their form, so before anything is
    rendered, read or written and by every command alike: by the key's name, with the reason, and never with the value."""
    east = j("us-", "east-1")
    assert east not in (TW.REGION_DEFAULT, REGION)
    argv = [str(tmp_path / "capture") if a == "CAPTURE" else a for a in argv]
    kept = {p.name: p.read_bytes() for p in rig.state.iterdir() if p.is_file()}
    before = len(rig.log())
    for how in ("environment", "names-file"):
        if how == "names-file":
            rig.write_names(TWIN_REGION=east)
        ran = rig.run(*argv, env={"TWIN_REGION": east} if how == "environment" else None, expect=1)
        assert "twinctl: refused: names-region-not-taken: TWIN_REGION names the one region the twin is not written for" in ran.err, how
        assert "LocationConstraint" in ran.err and "a second time through it" in ran.err, how           # the reason, both halves
        assert east not in ran.text and "us-east" not in ran.text.lower() and "(the value is not printed)" in ran.err, how
        assert ran.out == "" and not clean(ran.text), how
    rig.write_names()
    assert len(rig.log()) == before and {p.name: p.read_bytes() for p in rig.state.iterdir() if p.is_file()} == kept
    assert not rig.render.exists()                                  # nothing was rendered for a twin the service would refuse
    assert TW.GLOBAL_REGION == east and not (tmp_path / "capture").exists()


def test_the_accounts_block_public_access_is_read_a_second_time_through_the_region_the_twin_never_lives_in(rig: Rig) -> None:
    """K3's other half, a pin and no new behaviour (it passes on the tree as it was, for any twin outside that region). The second
    read was written for a twin that lives in another region than the one it goes through; with that region refused as the twin's
    own it is always a second read, and `plan` lists both: once without a region of its own, once through that one."""
    rig.run("plan", "--no-cli", expect=0)
    other = json.loads((rig.render / "plan.json").read_text(encoding="utf-8"))["other"]
    blocks = [c for c in other["reads"] if c[:2] == ["s3control", "get-public-access-block"]]
    assert sorted(c[c.index("--region") + 1] if "--region" in c else "" for c in blocks) == ["", j("us-", "east-1")]


# --- K2: the stop

WRITTEN = ("trip: the four calls by hand (sdv/cloud/README.md), for when the function does not make the cut, are written out for this twin "
           "before anything else: ")
NOT_WRITTEN = "trip: the file of the four calls by hand could NOT be written (%s); a file of that name from an earlier trip is not this run's. "
OPEN = "trip: by hand, NOT FILLED IN there: "
ENDED = ("trip was refused before the function was invoked. THE SAME FOUR CALLS BY HAND (sdv/cloud/README.md), under the operator profile, with "
         "the twin's own names:")
AGAIN = "With this twin's own values, as far as the names file and the state give them, they are in %s (written before this refusal was said)."
REFUSALS = ("twinctl: refused:", "twinctl: stopped on an error no check names", "twinctl: the command line cannot be read")
ANOTHER = j("anothertwin", "zz")                # the prefix of another twin than the fixtures'
OTHER_NAMES = "the state's records were made under names the names file does not give now (%s): its certificate may be another twin's"


def told(rig: Rig, monkeypatch: pytest.MonkeyPatch, *argv: Any, env: Optional[Dict[str, str]] = None,
         state: bool = True) -> Tuple[Ran, List[str], Dict[str, Any]]:
    """One run of the driver (a trip, unless `argv` says otherwise): what it returned; everything it said, on both streams, in the
    order it was said and before the redactor; and what lay at the place of the file of the four calls by hand at the moment its
    refusal was said (`at`: how much had been said by then)."""
    said: List[str] = []
    seen: Dict[str, Any] = {}
    real = TW.say

    def say(text: str = "", err: bool = False, as_json: bool = False) -> None:
        if text.startswith(REFUSALS) and "at" not in seen:
            hand = rig.state / HAND_FILE
            seen.update(at=len(said), file=hand.read_bytes() if hand.is_file() else None)
        said.append(text)
        real(text, err, as_json)

    with monkeypatch.context() as m:
        m.setattr(TW, "say", say)
        if state:
            ran = rig.run(*(argv or ("trip",)), env=env)
        else:
            ran = twinctl([str(a) for a in (argv or ("trip",))], dict({"TWIN_AWS": str(STUB), "STUB_AWS_DIR": str(rig.stub)}, **(env or {})))
    return ran, said, seen


def the_file_came_first(rig: Rig, ran: Ran, said: List[str], seen: Dict[str, Any]) -> None:
    """A trip that ended before its invoke: the file of the four calls was written, and its place said, BEFORE the refusal was
    said; it was not written again; after the refusal the four calls are named once more, with the place; and of the file only its
    place reaches the terminal, by the state directory's mask."""
    hand = rig.state / HAND_FILE
    assert said[0] == WRITTEN + str(hand) and 0 < seen["at"] and seen["file"] is not None and seen["file"] == hand.read_bytes()
    after = said[seen["at"] + 1:]
    assert after == [ENDED] + ["  " + line for line in BY_HAND] + [AGAIN % hand], after
    assert "<state>" in ran.out and ran.out.count(HAND_FILE) == 1 and str(rig.state) not in ran.text and not clean(ran.text)
    for line in by_hand(rig)[0]:
        assert line not in ran.text                                 # a call with its values is in the file and nowhere else
    assert not (rig.render / HAND_FILE).exists()


def test_a_trips_first_act_is_the_file_of_the_four_calls_by_hand_and_no_ending_before_its_invoke_comes_without_it(
        twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """K2 (the owner's decision of 2026-10-12: write the by-hand file before the refusals). The file with the manual stop's four calls and
    the twin's own values was written once a trip had got as far as its invoke: a trip that was refused before that (a key nobody
    knows, other names than the state's, a caller of another account) printed the calls with placeholders and left no file. It is
    the trip's FIRST act now, in the state directory, and every refusal comes after it."""
    # a trip that runs: the file first, whole, and no word of a refusal
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 0 and seen == {} and said[0] == WRITTEN + str(twin.state / HAND_FILE) and ran.out.startswith("trip: the four calls by hand")
    assert [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and ENDED not in ran.text and OPEN not in ran.text
    lines, notes = by_hand(twin)
    assert lines == whole_by_hand() and len(notes) == 3 and "NOT FILLED IN" not in "".join(notes) and not clean(ran.text)
    assert re.fullmatch(r"# twinctl trip: the manual stop's four calls by hand, written at [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z as this "
                        r"trip's first act, before any of its checks\.", notes[0])
    for line in lines:
        assert line not in ran.text
    # ended before its invoke by a key nobody knows: the names file itself is whole, and so is the file
    (twin.state / HAND_FILE).unlink()
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PREFFIX": "x"})
    assert ran.rc == 1 and "refused: names-key-unknown:" in ran.err and twin.log()[since:] == []
    the_file_came_first(twin, ran, said, seen)
    assert by_hand(twin)[0] == whole_by_hand()
    # (a suffix that is not the state's no longer ends a trip, the owner's A4 answers of 2026-10-16: its own test, below)
    # ... by a render that cannot be made (the trip's own payload is not the trip's)
    (twin.state / HAND_FILE).unlink()
    tampered(monkeypatch, tmp_path, "invoke-trip", lambda d: d.update(manual="status"))
    ran, said, seen = told(twin, monkeypatch)
    monkeypatch.setattr(TW, "TEMPLATES", TEMPLATES)
    assert ran.rc == 1 and "refused: document-refused:invoke-trip:" in ran.err and twin.log()[since:] == []
    the_file_came_first(twin, ran, said, seen)
    assert by_hand(twin)[0] == whole_by_hand()
    # ... by where its capture or its renders would lie (inside a work tree): refused before the names are even read, and the
    # file was there before that
    for argv, place, what in ((["trip", "--capture", "PLACE"], REPO / "results" / "twin-capture-of-a-test", "capture directory"),
                              (["--render", "PLACE", "trip"], REPO / "sdv-out" / "twin-render-of-a-test", "render directory")):
        (twin.state / HAND_FILE).unlink()
        ran, said, seen = told(twin, monkeypatch, *[str(place) if a == "PLACE" else a for a in argv])
        assert ran.rc == 1 and "refused: inside-a-work-tree:" in ran.err and what in ran.err, what
        assert twin.log()[since:] == [] and not place.exists(), what
        the_file_came_first(twin, ran, said, seen)
        assert by_hand(twin)[0] == whole_by_hand(), what
    # ... by a caller of another account: refused after the one read of the caller, as before, and the file was there before that read
    (twin.state / HAND_FILE).unlink()
    trips = twin.account()["trips"]
    twin.edit(other_account)
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 1 and "refused: identity-other-account:" in ran.err and twin.account()["trips"] == trips
    assert [e["argv"][:2] for e in twin.log()[since:]] == [["sts", "get-caller-identity"]]
    the_file_came_first(twin, ran, said, seen)
    assert by_hand(twin)[0] == whole_by_hand()
    # no other command writes that file or names the calls
    (twin.state / HAND_FILE).unlink()
    ran = twin.run("status", expect=1)
    assert not (twin.state / HAND_FILE).exists() and BY_HAND[0] not in ran.text and "by hand" not in ran.text
    assert TW.STOP_BY_HAND == BY_HAND and TW.HAND_FILE == HAND_FILE


def test_the_calls_by_hand_never_hold_another_twins_value_and_every_slot_left_open_is_said_by_its_key(
        twin: Rig, rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """K2. FOR THIS TWIN, AS FAR AS THE NAMES FILE AND THE STATE GIVE IT. The names in the file are the names file's; the
    certificate's id is a fact of the state. A state that was made under another prefix, thing, account or region recorded another
    twin's certificate, and that id beside these names would send the owner's own deactivation to it: it is left out. A call that
    lacks a value is a comment with its slot left in (it runs nothing), and each open slot is said by the key its value comes
    from, in the file and on the terminal, with no value in either sentence."""
    common = "--region %s --profile %s" % (REGION, PROFILE)
    # the names file's twin is another one than the state's
    env = {"TWIN_PREFIX": ANOTHER, "TWIN_THING": ANOTHER + "-thing"}
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, env=env)
    assert ran.rc == 1 and "refused: names-changed:" in ran.err and "(TWIN_PREFIX, TWIN_THING; no value is printed)" in ran.err
    the_file_came_first(twin, ran, said, seen)
    theirs = whole_by_hand(prefix=ANOTHER, thing=ANOTHER + "-thing")
    lines, notes = by_hand(twin)
    text = (twin.state / HAND_FILE).read_text(encoding="utf-8")
    assert lines == [theirs[0], theirs[2]] and CERT_1 not in text and PREFIX not in text and twin.log()[since:] == []
    why = "certificate_id, a fact of the state: " + OTHER_NAMES % "TWIN_PREFIX, TWIN_THING"
    assert "# NOT FILLED IN (<CERT_ID>): aws iot update-certificate --certificate-id <CERT_ID> --new-status INACTIVE " + common in notes
    assert ("# NOT FILLED IN (<the certificate's ARN>): aws iot detach-policy --policy-name %s-device --target <the certificate's ARN> %s"
            % (ANOTHER, common)) in notes
    assert [n for n in notes if n.startswith("#   <CERT_ID>: " + why)] and [n for n in notes if n.startswith("#   <the certificate's ARN>: ")]
    assert [s for s in said if s.startswith(OPEN + "<CERT_ID>: " + why)] and (OPEN + "<CERT_ID>: " + why) in ran.err
    assert ANOTHER not in ran.text and not clean(ran.text)
    # a state of another account: the same, by that key
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_ACCOUNT": OTHER_ACCOUNT})
    assert ran.rc == 1 and "(TWIN_ACCOUNT; no value is printed)" in ran.err
    the_file_came_first(twin, ran, said, seen)
    mine = whole_by_hand()
    assert by_hand(twin)[0] == [mine[0], mine[2]] and CERT_1 not in (twin.state / HAND_FILE).read_text(encoding="utf-8")
    assert (OPEN + "<CERT_ID>: certificate_id, a fact of the state: " + OTHER_NAMES % "TWIN_ACCOUNT") in ran.err
    # a prefix that has not its form: what is made of it stays open, and so does the certificate of a state that cannot be held to it
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PREFIX": "Short"})
    assert ran.rc == 1 and "refused: names-invalid: TWIN_PREFIX" in ran.err
    the_file_came_first(twin, ran, said, seen)
    lines, notes = by_hand(twin)
    assert lines == [mine[2]] and len([n for n in notes if n.startswith("# NOT FILLED IN (")]) == 3
    assert "#   <RULE>, <POLICY>: TWIN_PREFIX is not given in the form twinctl takes for it" in notes
    assert (OPEN + "<RULE>, <POLICY>: TWIN_PREFIX is not given in the form twinctl takes for it") in ran.err and "Short" not in ran.text
    # a thing that does not begin with the prefix: one of the two is not this twin's, and neither is put in
    stray = j("unrelated", "-thing-zz")
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_THING": stray})
    assert ran.rc == 1 and "refused: names-invalid: TWIN_THING does not begin with TWIN_PREFIX" in ran.err
    the_file_came_first(twin, ran, said, seen)
    lines, notes = by_hand(twin)
    text = (twin.state / HAND_FILE).read_text(encoding="utf-8")
    assert lines == [] and stray not in text and PREFIX not in text and CERT_1 not in text and stray not in ran.text
    assert ("#   <RULE>, <THING>, <POLICY>: TWIN_THING does not begin with TWIN_PREFIX: one of the two is not this twin's, and neither is "
            "put in") in notes
    # the one region that is not taken: no call is whole without its region, and the value is in neither place
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_REGION": TW.GLOBAL_REGION})
    assert ran.rc == 1 and "refused: names-region-not-taken:" in ran.err
    the_file_came_first(twin, ran, said, seen)
    lines, notes = by_hand(twin)
    assert lines == [] and "#   <REGION>: TWIN_REGION names the one region the twin is not written for" in notes
    assert TW.GLOBAL_REGION not in (twin.state / HAND_FILE).read_text(encoding="utf-8") + ran.text and "--region <REGION>" in notes[3]
    # the salt gone: the names the state was made under cannot be compared, so its certificate is not put beside them; no salt is made
    (twin.state / "salt").rename(twin.state / "salt.kept")
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 1 and "refused: salt-missing:" in ran.err and not (twin.state / "salt").exists()
    the_file_came_first(twin, ran, said, seen)
    assert by_hand(twin)[0] == [mine[0], mine[2]] and (OPEN + "<CERT_ID>: certificate_id, a fact of the state: the state directory's file "
                                                      "`salt` is gone") in ran.err
    (twin.state / "salt.kept").rename(twin.state / "salt")
    # a state that cannot be read: the trip goes on, as before, and its file says what it could not take from the state
    whole = (twin.state / "state.json").read_bytes()
    (twin.state / "state.json").write_bytes(whole[:len(whole) // 2])
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch)
    assert seen == {} and [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and ENDED not in ran.text
    assert by_hand(twin)[0] == [mine[0], mine[2]] and (OPEN + "<CERT_ID>: certificate_id, a fact of the state: the state cannot be read "
                                                      "(state-unreadable)") in ran.err and not clean(ran.text)
    # a state that records as its certificate what has not the form of one (a state edited by hand): none of it goes into the file,
    # which is made of lines, and a second line of such a value would be a call nobody wrote
    edited = json.loads(whole.decode("utf-8"))
    edited["facts"]["certificate_id"] = CERT_1 + "\naws iot delete-thing --thing-name " + THING
    (twin.state / "state.json").write_text(json.dumps(edited), encoding="utf-8")
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PREFFIX": "x"})
    assert ran.rc == 1 and by_hand(twin)[0] == [mine[0], mine[2]] and "delete-thing" not in (twin.state / HAND_FILE).read_text(encoding="utf-8")
    assert (OPEN + "<CERT_ID>: certificate_id, a fact of the state: what the state records as its certificate has not the form of a "
            "certificate's id") in ran.err
    (twin.state / "state.json").write_bytes(whole)
    # a state that records no certificate (nothing was made yet): said so, and the trip is not ended by it before its invoke
    since = len(rig.log())
    ran, said, seen = told(rig, monkeypatch)
    assert ran.rc == 1 and seen == {} and [e["argv"][:2] for e in rig.log()[since:]][:2] == [["sts", "get-caller-identity"], ["lambda", "invoke"]]
    assert by_hand(rig)[0] == [mine[0], mine[2]] and "RUN THE FOUR CALLS BY HAND" in ran.err and ENDED not in ran.text
    assert (OPEN + "<CERT_ID>: certificate_id, a fact of the state: the state records no certificate") in ran.err and not clean(ran.text)
    # THE REHEARSAL'S SET IS ANOTHER SET: its names are the prefix's with two more letters, its thing is made of the prefix, and its
    # certificate is its own state's. Neither run of a trip takes the other set's certificate.
    twin.go("apply", "certificate", "--rehearsal")
    assert state_of(twin)["facts"]["certificate_id"] == CERT_1
    told(twin, monkeypatch, "--rehearsal", "trip")
    assert by_hand(twin)[0] == whole_by_hand(prefix=PREFIX + "rh", thing=PREFIX + "rh-thing", cert=CERT_2)
    told(twin, monkeypatch)
    assert by_hand(twin)[0] == whole_by_hand()
    ran, said, seen = told(twin, monkeypatch, "--rehearsal", "trip", env={"TWIN_PREFIX": "Short"})        # its thing is made of the prefix
    assert ran.rc == 1 and by_hand(twin)[0] == [] and CERT_2 not in (twin.state / HAND_FILE).read_text(encoding="utf-8")
    assert "#   <RULE>, <THING>, <POLICY>: TWIN_PREFIX is not given in the form twinctl takes for it" in by_hand(twin)[1]


# One fault in the names, by the row: what is taken out of the names file (None), what the environment gives instead, the refusal, which
# of the four calls are still lines to run, the names those lines hold when they are not the fixtures', and what is said of an open slot.
ONE_FAULT: List[Tuple[str, Dict[str, Optional[str]], Dict[str, str], str, List[int], Dict[str, str], Optional[str]]] = [
    ("the-suffix-is-not-set", {"TWIN_BUCKET_SUFFIX": None}, {}, "names-missing: TWIN_BUCKET_SUFFIX is not set", [0, 1, 2, 3], {}, None),
    ("the-profile-is-not-set", {"TWIN_PROFILE": None}, {}, "names-missing: TWIN_PROFILE is not set", [0, 1, 2, 3], {"profile": ""},
     "<PROFILE>: TWIN_PROFILE is not given: --profile is left off the calls"),
    ("the-account-is-not-set", {"TWIN_ACCOUNT": None}, {}, "names-missing: TWIN_ACCOUNT is not set", [0, 2], {},
     "<CERT_ID>: certificate_id, a fact of the state: " + OTHER_NAMES % "TWIN_ACCOUNT"),
    ("the-thing-is-not-set", {"TWIN_THING": None}, {}, "names-missing: TWIN_THING is not set", [0], {}, "<THING>: TWIN_THING is not given"),
    ("another-region-than-the-states", {}, {"TWIN_REGION": "eu-central-1"}, "names-changed:", [0, 2], {"region": "eu-central-1"},
     "<CERT_ID>: certificate_id, a fact of the state: " + OTHER_NAMES % "TWIN_REGION"),
    ("another-thing-of-the-same-prefix", {}, {"TWIN_THING": PREFIX + "-other-thing"}, "names-changed:", [0, 2],
     {"thing": PREFIX + "-other-thing"}, "<CERT_ID>: certificate_id, a fact of the state: " + OTHER_NAMES % "TWIN_THING"),
    ("the-notices-switch-is-not-set", {"TWIN_NOTICE": None}, {}, "names-missing: TWIN_NOTICE is not set", [0, 1, 2, 3], {}, None),
    ("the-prefix-is-not-set", {"TWIN_PREFIX": None}, {}, "names-missing: TWIN_PREFIX is not set", [2], {},
     "<RULE>, <POLICY>: TWIN_PREFIX is not given"),
    ("an-account-that-has-not-its-form", {}, {"TWIN_ACCOUNT": "12345678901"}, "names-invalid: TWIN_ACCOUNT", [0, 2], {},
     "<CERT_ID>: certificate_id, a fact of the state: " + OTHER_NAMES % "TWIN_ACCOUNT"),
    ("a-profile-that-has-not-its-form", {}, {"TWIN_PROFILE": "tiny-zz"}, "names-invalid: TWIN_PROFILE", [0, 1, 2, 3], {"profile": ""},
     "<PROFILE>: TWIN_PROFILE is not given in the form twinctl takes for it: --profile is left off the calls"),
    ("a-thing-that-has-not-its-form", {}, {"TWIN_THING": "bad/thing-zz"}, "names-invalid: TWIN_THING", [0], {},
     "<THING>: TWIN_THING is not given in the form twinctl takes for it"),
]


@pytest.mark.parametrize("file,env,refusal,runs,names,open_slot", [row[1:] for row in ONE_FAULT], ids=[row[0] for row in ONE_FAULT])
def test_one_fault_in_the_names_costs_a_stop_only_the_values_that_fault_takes(twin: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                              file: Dict[str, Optional[str]], env: Dict[str, str], refusal: str,
                                                                              runs: List[int], names: Dict[str, str],
                                                                              open_slot: Optional[str]) -> None:
    """K2. The trip is refused by the fault's own name, as every command is; its file was written first, from the stop's own reading
    of the names, which takes every value that is in order. A key the four calls are not made of (the role, the suffix, the notice's
    switch) costs the file nothing. One they are made of leaves its own slots open and no other; and the certificate of the state
    is put in only while all four names it is held to (the account, the region, the prefix, the thing) are the state's. A profile
    that is not there, or has not its form, makes no call a comment: the four are written without --profile, as the manual stop has
    them (the hard review of WP8's fixes, NIT 4), and the slot's line says so. The operator role's key is no row here: a stop
    needs no role (its own test, below)."""
    twin.write_names(**file)
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, env=env)
    assert ran.rc == 1 and "twinctl: refused: " + refusal in ran.err and twin.log()[since:] == []
    the_file_came_first(twin, ran, said, seen)
    whole = whole_by_hand(**names)
    lines, notes = by_hand(twin)
    assert lines == [whole[i] for i in runs] and len([n for n in notes if n.startswith("# NOT FILLED IN (")]) == 4 - len(runs)
    if open_slot is None:
        assert OPEN not in ran.text and "NOT FILLED IN" not in "".join(notes)
    else:
        assert OPEN + open_slot in ran.err and [n for n in notes if n.startswith("#   " + open_slot)]
    assert not [v for v in env.values() if len(v) > 1 and v in ran.text]


def test_the_default_region_is_put_into_the_calls_only_from_names_that_were_read_whole(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """K2. The region is the one name with a default. From names that were read whole and do not set it, the default is the twin's
    region and goes into the calls, as every command takes it. Once anything of the names was passed over unread (a line or a
    variable that is no KEY=VALUE of a known key, a file that cannot be read), what was passed over may have been this key,
    misspelt: the default is NOT put in its place, and the slot is said. A misspelt key must not read as unset, here either."""
    rig = Rig(tmp_path / "default-region")
    rig.write_names(TWIN_REGION=None)
    rig.start()
    default = whole_by_hand(region=TW.REGION_DEFAULT)
    ran, said, seen = told(rig, monkeypatch)
    assert seen == {} and by_hand(rig)[0] == [default[0], default[2]] and OPEN + "<REGION>" not in ran.text       # no certificate yet
    passed_over = ("<REGION>: TWIN_REGION is not given, and its default is not put in its place: something of the names was passed over "
                   "unread, and a misspelt key must not read as unset")
    for fault in ("a-variable-nobody-knows", "a-line-nobody-knows", "a-file-that-cannot-be-read"):
        env = {"TWIN_REGOIN": REGION} if fault == "a-variable-nobody-knows" else None
        if fault == "a-line-nobody-knows":
            names = (rig.state / "names.env").read_text(encoding="utf-8")
            (rig.state / "names.env").write_text(names + "TWIN_REGOIN=%s\n" % REGION, encoding="utf-8")
        if fault == "a-file-that-cannot-be-read":
            (rig.state / "names.env").write_bytes(b"\xff\xfe\xfd is no names file\n")
        ran, said, seen = told(rig, monkeypatch, env=env)
        refusal = "refused: names-unreadable:" if fault == "a-file-that-cannot-be-read" else "refused: names-key-unknown:"
        assert ran.rc == 1 and refusal in ran.err, fault
        the_file_came_first(rig, ran, said, seen)
        lines, notes = by_hand(rig)
        text = (rig.state / HAND_FILE).read_text(encoding="utf-8")
        assert lines == [] and TW.REGION_DEFAULT not in text and REGION not in text and "--region <REGION>" in notes[3], fault
        assert OPEN + passed_over in ran.err and "#   " + passed_over in notes, fault
        rig.write_names(TWIN_REGION=None)


SPELLED = "operator-role"                       # a role's name that the redactor's own mask for its kind spells: no literal can be made of it


@pytest.mark.parametrize("change", [{"TWIN_PROFILE": PROFILE_2}, {"TWIN_OPERATOR_ROLE": ROLE_2},
                                    {"TWIN_PROFILE": PROFILE_2, "TWIN_OPERATOR_ROLE": ROLE_2}, {"TWIN_OPERATOR_ROLE": SPELLED},
                                    {"TWIN_BUCKET_SUFFIX": j("zz9zz9", "zz9zz9")}, {"TWIN_NOTICE": "0"},
                                    {"TWIN_BUCKET_SUFFIX": j("zz9zz9", "zz9zz9"), "TWIN_NOTICE": "0", "TWIN_PROFILE": PROFILE_2}],
                         ids=["the-profile", "the-role", "both", "a-role-no-literal-can-be-made-of", "the-suffix", "the-notice",
                              "suffix-notice-and-profile"])
def test_a_trip_is_held_to_the_account_and_not_to_the_role_or_the_profile_the_state_was_made_under(twin: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                                   change: Dict[str, str]) -> None:
    """K2 (the owner's decision of 2026-10-12: `trip` is held to the account only, not to the role and profile bindings). The role
    and the profile are bound to a state so that no approval printed under one runs under another; a trip takes no approval. A
    profile renamed in the CLI's own configuration while the twin is live refused the one-command stop (names-changed). It goes on
    now, under the profile the names file gives, and says so by the keys' names; every other command stays refused, and so does a
    trip under any other name that is not the state's. Nor is it ended by a new name that `twinctl literals` would have refused
    (one a mask of the redactor spells): the literals file is behind under a new name, and the stop's own redactor leaves such a
    word out instead of refusing to be built. The owner's A4 answers of 2026-10-16 (question 13) ease the bucket's suffix and the
    notice's switch the same way: no call of a stop is made of either."""
    keys = ", ".join(sorted(change))
    if "TWIN_PROFILE" in change:
        twin.edit(lambda a: a.update(profile=PROFILE_2))            # the CLI's configuration answers under the new name
    names = state_of(twin)["names"]
    since = len(twin.log())
    ran = twin.run("status", env=change, expect=1)
    assert "refused: names-changed:" in ran.err and "(%s; no value is printed)" % keys in ran.err and twin.log()[since:] == []
    trips = twin.account()["trips"]
    ran, said, seen = told(twin, monkeypatch, env=change)
    assert seen == {} and "twinctl: refused" not in ran.err and ENDED not in ran.text and ran.rc == 0, ran.text
    assert twin.account()["trips"] == trips + 1 and "trip: the function ran" in ran.out and "traffic: the rule is DISABLED" in ran.out
    invoke, = [e["argv"] for e in twin.log()[since:] if e["argv"][:2] == ["lambda", "invoke"]]
    profile = change.get("TWIN_PROFILE", PROFILE)
    assert invoke[invoke.index("--profile") + 1] == profile
    assert ("trip: the names file gives another value than this state's records were made under for %s (no value is printed): the stop is "
            "held to the account and not to the operator role, the profile, the bucket's suffix or the notice's switch" % keys) in ran.err
    assert by_hand(twin)[0] == whole_by_hand(profile=profile)
    assert not [v for v in list(change.values()) if v in ran.text and v != SPELLED and len(v) > 1] and not clean(ran.text)
    if set(change) - {"TWIN_NOTICE"}:                               # the notice's switch is no literal: nothing is behind for it alone
        assert "the literals file is missing or behind (literals-behind)" in ran.err
    assert "redaction" not in ran.err
    assert state_of(twin)["names"] == names                         # the state keeps the names it was made under
    # with a name beside them that still holds a stop, the trip is refused for that name, and for that name alone. Every name that
    # still holds one is a name its four calls by hand are made of, so the file is not held to the fixture's lines here: the
    # one-fault table holds what each such name does to it.
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, env=dict(change, TWIN_REGION="eu-central-1"))
    assert ran.rc == 1 and "refused: names-changed:" in ran.err and "(TWIN_REGION; no value is printed)" in ran.err
    assert twin.log()[since:] == [] and twin.account()["trips"] == trips + 1
    assert TW.STOP_NOT_HELD == ("TWIN_OPERATOR_ROLE", "TWIN_PROFILE", "TWIN_BUCKET_SUFFIX", "TWIN_NOTICE")
    assert set(TW.STOP_NOT_HELD) < set(TW.BOUND_NAMES) and not set(TW.STOP_NOT_HELD) & set(TW.STOP_NAMES)


def test_the_stops_two_names_eased_on_2026_10_16_are_written_down_and_the_old_sentence_is_gone() -> None:
    """The owner's A4 answers of 2026-10-16, question 13: the bucket's suffix and the notice's switch hold the stop no more. The
    driver's docstring and the README say so in their own words, and neither still says that a trip under another suffix or
    notice's switch is refused like every command."""
    def fold(text: str) -> str:
        return " ".join(text.replace("`", "").split())

    doc = fold(str(TW.__doc__))
    readme = fold((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))
    for said in ("Nor another bucket suffix or notice's switch (the owner's A4 answers of 2026-10-16): no call of a stop is made of either.",
                 "Since the owner's A4 answers of 2026-10-16 the same holds for the bucket's suffix and the notice's switch",
                 "Under another account, region, prefix or thing a trip is refused like every command"):
        assert said in doc, said
    for said in ("Nor is it stopped by another bucket suffix or notice's switch (the owner's A4 answers of 2026-10-16): no call of a stop is "
                 "made of either.",
                 "Since the owner's A4 answers of 2026-10-16 the same holds for the bucket's suffix and the notice's switch",
                 "Under another account, region, prefix or thing it is refused like every command"):
        assert said in readme, said
    for where in (doc, readme):
        assert "thing, suffix or notice's switch" not in where


def test_a_trip_that_cannot_write_its_file_prints_the_four_calls_with_the_keys_their_slots_are_made_of(
        twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """K2. Where no file can be written (no state directory is named, it would lie in a work tree, the write fails) the four calls
    are printed with their slots, and each slot is said by the key it is made of: BEFORE the refusal, and once more after it. A
    trip is never ended by its own second net: with the file's place taken, it goes on to its invoke."""
    calls = ["  " + line for line in BY_HAND]
    # no state directory is named at all
    arrived = [len(twin.log(name)) for name in ("log.jsonl", "skeleton.jsonl", "refused.jsonl")]
    ran, said, seen = told(twin, monkeypatch, state=False)
    assert ran.rc == 1 and "refused: state-unset:" in ran.err
    head = NOT_WRITTEN % "no state directory is named" + "The four calls (sdv/cloud/README.md), under the operator profile:"
    assert said[:5] == [head] + calls and seen == {"at": 6, "file": None}
    keys = said[5]                                                  # what each slot is made of, by its key: no value, and every slot
    for word in ("TWIN_PREFIX", "TWIN_THING", "TWIN_REGION", "TWIN_ACCOUNT", "TWIN_PROFILE", "certificate_id", "<RULE>", "<POLICY>", "<THING>",
                 "<CERT_ID>", "TWIN_PREFIX_telemetry", "TWIN_PREFIX-device"):
        assert word in keys, word
    assert keys == TW.HAND_KEYS and keys in ran.err                 # ... and it reaches the terminal as it is: the redactor changes none of it
    assert said[7:] == [ENDED] + calls + [keys] and ran.out == "" and not clean(ran.text)
    assert [len(twin.log(name)) for name in ("log.jsonl", "skeleton.jsonl", "refused.jsonl")] == arrived          # nothing reached the CLI
    # a state directory that would lie inside a work tree: nothing is made there
    checkout = tmp_path / "another-checkout"
    (checkout / ".git").mkdir(parents=True)
    ran, said, seen = told(twin, monkeypatch, "--state", checkout / "state", "trip")
    assert ran.rc == 1 and "refused: inside-a-work-tree:" in ran.err and list(checkout.iterdir()) == [checkout / ".git"]
    assert said[0] == NOT_WRITTEN % "the state directory would lie inside a work tree, where nothing of a twin is written" + (
        "The four calls (sdv/cloud/README.md), under the operator profile:") and said[1:6] == calls + [keys] and said[-1] == keys
    # the file's own place is taken: said, with the calls and the keys, and THE TRIP GOES ON
    (twin.state / HAND_FILE).mkdir()
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 0 and seen == {} and [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]] and "traffic: the rule is DISABLED" in ran.out
    assert said[0].startswith(NOT_WRITTEN.split("(")[0] + "(an error no check names (") and said[1:6] == calls + [keys]
    assert ENDED not in ran.text and not clean(ran.text) and THING not in ran.text
    (twin.state / HAND_FILE).rmdir()
    for left in twin.state.glob(HAND_FILE + ".tmp"):
        left.unlink()
    # a stop that was mistyped: the file first, by the state directory the environment names, then the refusal, then the calls again
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, "trip", "--capure", tmp_path / "capture")
    assert ran.rc == 2 and "twinctl: the command line cannot be read" in ran.err and twin.log()[since:] == []
    the_file_came_first(twin, ran, said, seen)
    assert by_hand(twin)[0] == whole_by_hand()
    # ... and a command line that cannot be read and names no trip says nothing of the calls
    ran = twin.run("status", "--capure", "x", expect=2)
    assert BY_HAND[0] not in ran.text and "by hand" not in ran.text
    # a reply that cannot be written (the place of the replies is taken): an error no check names, after the file
    (twin.state / HAND_FILE).unlink()
    shutil.rmtree(str(twin.state / "replies"))
    (twin.state / "replies").write_text("not a directory\n", encoding="ascii")
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 1 and "twinctl: stopped on an error no check names (" in ran.err and twin.log()[since:] == []
    the_file_came_first(twin, ran, said, seen)
    assert by_hand(twin)[0] == whole_by_hand()


# --- the review of WP8's fixes (wp8-review-fix): what the rehearsal and the hard review found in the stop

WRITTEN_FOR = ("trip: the four calls by hand (sdv/cloud/README.md), for when the function does not make the cut, are written out for %s before "
               "anything else: ")
SENT = ("trip: THE INVOKE WAS SENT AND ITS ANSWER IS NOT KNOWN (%s): THE FUNCTION MAY HAVE RUN. Read `status` below first; if the cut is not "
        "there, RUN THE FOUR CALLS BY HAND.")
NO_ROLE = ("trip: the names file gives no usable TWIN_OPERATOR_ROLE (it %s): the stop needs none and goes on; every other command is refused "
           "until the key is given in its form")
MOVED = "trip: THE PROFILE NOW ANSWERS FOR ANOTHER ACCOUNT than the names file's: `status` is NOT read here"
FOUND_BY = "trip: by hand: where the certificate's id is not filled in, the file gives the read that finds it in the account."


@pytest.mark.parametrize("value,why,refusal", [(None, "is not set", "names-missing: TWIN_OPERATOR_ROLE is not set"),
                                               ("a role zz", "is not given in the form twinctl takes for it", "names-invalid: TWIN_OPERATOR_ROLE")],
                         ids=["the-key-is-gone", "the-value-has-not-its-form"])
def test_a_trip_needs_no_operator_role_and_goes_on_when_the_names_file_gives_none(twin: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                  value: Optional[str], why: str, refusal: str) -> None:
    """The hard review of WP8's fixes (fable-wp8), SHOULD 1. The owner's decision of 2026-10-12 holds the stop to the account
    only. A CHANGED role went on; a role whose KEY was gone from the names file, or whose value had not the form the driver
    takes (the line taken out after the role was deleted, the new name mistyped), still ended the trip before its invoke
    (names-missing, names-invalid), with the file of the four calls as the only help. The trip never uses the role: its
    invoke is made of the prefix and its identity check is the account alone. It goes on now, says the lack by the key and
    with no value, and the role's own step reads as not read. Every other command stays refused."""
    twin.write_names(TWIN_OPERATOR_ROLE=value)
    names = state_of(twin)["names"]
    since = len(twin.log())
    ran = twin.run("status", expect=1)
    assert "twinctl: refused: " + refusal in ran.err and twin.log()[since:] == []
    trips = twin.account()["trips"]
    ran, said, seen = told(twin, monkeypatch)
    assert seen == {} and ran.rc == 0 and "twinctl: refused" not in ran.err and ENDED not in ran.text, ran.text
    assert twin.account()["trips"] == trips + 1 and "trip: the function ran" in ran.out and "traffic: the rule is DISABLED" in ran.out
    assert NO_ROLE % why in ran.err and ran.err.count("TWIN_OPERATOR_ROLE") == 1 and "another value than this state's" not in ran.err
    assert re.search(r"^  operator-role +row A1\.3 +\S+ +not read \(names-missing\)$", ran.out, re.M), ran.out
    assert by_hand(twin)[0] == whole_by_hand() and OPEN not in ran.text and state_of(twin)["names"] == names
    assert not clean(ran.text) and (value is None or value not in ran.text)
    assert "literals-behind" not in ran.err                         # no literal is made of a role that is not there, and none is missed
    # a state that records no names yet is not bound to "no role" by such a trip's own write
    state = state_of(twin)
    del state["names"]
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    twin.edit(lambda a: a.update(function_error=True))
    ran = twin.run("trip", expect=1)
    assert status_of(twin, "dry-trip") == "stale" and "names" not in state_of(twin) and NO_ROLE % why in ran.err
    # ... and with the key back, the state takes the names with its next write, as a state that records none does
    twin.write_names()
    twin.edit(lambda a: a.pop("function_error"))
    twin.go("apply", "function-status")                             # an action that only reads: its record is the state's next write
    assert sorted(state_of(twin)["names"]) == sorted(TW.BOUND_NAMES) and state_of(twin)["names"] == names
    assert TW.STOP_NEEDS_NOT == ("TWIN_OPERATOR_ROLE",) and "TWIN_PROFILE" not in TW.STOP_NEEDS_NOT


def test_a_trip_whose_invoke_was_sent_and_whose_answer_is_not_known_says_so_and_the_status_follows(twin: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                                   tmp_path: Path) -> None:
    """The verification of WP8's fixes (verify-fixes#5). When the invoke was SENT and its reply could not be read (the CLI printed
    what is no JSON after the function did its work; a CLI cut off; a reply that could not be written), the trip ended
    `reply-unreadable`, said `trip was refused before the function was invoked` and printed no `status`, while the account was
    tripped. It says now that the function MAY HAVE RUN, and `status` follows, as it follows a failed invoke. What certainly
    sent nothing (no CLI; an error from before the CLI was run) stays a refusal before the invoke; and with no CLI that runs,
    the manual stop's console way is named after the calls (the rehearsal's item 5, NIT 5)."""
    hand = twin.state / HAND_FILE
    twin.edit(lambda a: a.update(reply_garbage={"lambda invoke": "<html>not what was asked for</html>"}))
    trips = twin.account()["trips"]
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 1 and seen == {} and twin.account()["trips"] == trips + 1
    assert SENT % "reply-unreadable" in ran.err and ENDED not in ran.text and "twinctl: refused" not in ran.err
    assert STATUS_SAID in ran.out and "traffic: the rule is DISABLED" in ran.out and "the certificate is INACTIVE" in ran.out
    assert said[-1] == "trip: the four calls by hand, with this twin's own values, are in %s" % hand and TW.CONSOLE_WAY not in ran.err
    assert not clean(ran.text) and str(twin.state) not in ran.text
    twin.edit(lambda a: a.pop("reply_garbage"))
    # a CLI that was cut off while the invoke was out: the same, and with no CLI that runs the console's way is named
    spawn = TW.Aws._spawn

    def cut_off(self: Any, argv: List[str], env: Optional[Dict[str, str]] = None) -> Any:
        done = spawn(self, argv, env)
        if argv[:2] == ["lambda", "invoke"]:
            TW.refuse("cli-failed", "the AWS CLI could not be run to its end (TimeoutExpired)")
        return done

    with monkeypatch.context() as m:
        m.setattr(TW.Aws, "_spawn", cut_off)
        ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 1 and seen == {} and SENT % "cli-failed" in ran.err and STATUS_SAID in ran.out and ENDED not in ran.text
    assert said[-1] == TW.CONSOLE_WAY and twin.account()["trips"] == trips + 2
    # an error no check names: AFTER the CLI ran it is an invoke that was sent, BEFORE it a trip that ended before its invoke
    run = TW.Aws.run
    for after in (True, False):
        def broken(self: Any, call: Any, label: str = "", after: bool = after) -> Any:
            if (call.service, call.op) != ("lambda", "invoke"):
                return run(self, call, label)
            if after:
                run(self, call, label)
            raise PermissionError("the place of the reply's own file")

        with monkeypatch.context() as m:
            m.setattr(TW.Aws, "run", broken)
            ran, said, seen = told(twin, monkeypatch)
        assert ran.rc == 1, after
        if after:
            assert seen == {} and SENT % "PermissionError" in ran.err and STATUS_SAID in ran.out and ENDED not in ran.text
        else:
            assert "twinctl: stopped on an error no check names (PermissionError)" in ran.err and "THE INVOKE WAS SENT" not in ran.text
            the_file_came_first(twin, ran, said, seen)
    assert twin.account()["trips"] == trips + 3
    # no CLI at all: nothing was sent, the trip is refused before its invoke, and after the calls the one way that needs no CLI
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_AWS": str(tmp_path / "no-such-cli")})
    assert ran.rc == 1 and "twinctl: refused: cli-missing:" in ran.err and twin.log()[since:] == [] and twin.account()["trips"] == trips + 3
    assert "trip: the caller's identity could not be read (cli-missing): the stop goes on" in ran.err
    last = said[seen["at"] + 1:]
    assert last == [ENDED] + ["  " + line for line in BY_HAND] + [AGAIN % hand, TW.CONSOLE_WAY], last
    assert "the manual stop's fourth way is the console" in TW.CONSOLE_WAY and not clean(ran.text)
    # ... and no other command's refusal names it
    ran = twin.run("status", env={"TWIN_AWS": str(tmp_path / "no-such-cli")}, expect=1)
    assert "refused: cli-missing:" in ran.err and "console" not in ran.text
    assert TW.INVOKE_NOT_SENT == ("cli-missing", "forbidden-option", "not-armed", "caller-not-read") and TW.NO_CLI == ("cli-missing", "cli-failed")


def test_a_trips_status_is_not_read_under_another_account_than_the_one_its_invoke_went_to(twin: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hard review of WP8's fixes (fable-wp8), NIT 3. The identity was read once, before the invoke, and `status` followed
    with no second read. A profile repointed between two calls of one command (the CLI's own configuration, edited meanwhile)
    made the status another account's: `not found` for every step and `ok: no ACTIVE certificate ...`, exit 0, a wrong
    all-clear where the manual stop reads its proof. The caller is read once more right before a trip's status: under another
    account no status is printed and the trip ends as a refusal. An identity that cannot be read then keeps no status back."""
    home = dict(twin.account()["identity"])
    away = dict(home, Account=OTHER_ACCOUNT)
    twin.edit(lambda a: a.update(identity_then=[away]))             # the profile answers for the twin's account once, then for another
    trips = twin.account()["trips"]
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 1 and seen == {} and twin.account()["trips"] == trips + 1 and "trip: the function ran" in ran.out
    assert [e["argv"][:2] for e in twin.log()[since:]] == [["sts", "get-caller-identity"], ["lambda", "invoke"], ["sts", "get-caller-identity"]]
    assert MOVED in ran.err and STATUS_SAID not in ran.out and "ok: " not in ran.out and "not found" not in ran.out
    assert "RUN THE FOUR CALLS BY HAND" in ran.err and "twinctl: refused" not in ran.err and not clean(ran.text)
    # the same after an invoke that failed: no status of the other account there either
    twin.edit(lambda a: (a.update(identity=home, identity_then=[away]),
                         a["faults"].append({"service": "lambda", "op": "invoke", "code": "ResourceNotFoundException"})))
    ran = twin.run("trip", expect=1)
    assert "the invoke failed (ResourceNotFoundException). RUN THE FOUR CALLS BY HAND" in ran.err and MOVED in ran.err
    assert STATUS_SAID not in ran.out and "ok: " not in ran.out
    # an identity that cannot be read before the status keeps no status back, as it stops no trip
    twin.edit(lambda a: a.update(identity=home, reply_garbage={"sts get-caller-identity": "not json"}))
    since = len(twin.log())
    ran = twin.run("trip", expect=0)
    assert "trip: the caller's identity could not be read (reply-unreadable): the stop goes on" in ran.err and MOVED not in ran.err
    assert STATUS_SAID in ran.out and "ok: no ACTIVE certificate of the account is outside the twin's set" in ran.out
    assert [e["argv"][:2] for e in twin.log()[since:]][:3] == [["sts", "get-caller-identity"], ["lambda", "invoke"], ["sts", "get-caller-identity"]]
    # and every other command still reads the caller first, once: the status command prints nothing under another account
    twin.edit(lambda a: (a.pop("reply_garbage"), a.update(identity=away)))
    ran = twin.run("status", expect=1)
    assert "refused: identity-other-account:" in ran.err and STATUS_SAID not in ran.out


@pytest.mark.parametrize("reply", ["{}", "[]", '""', '{"Account": "12345"}', '{"Account": 7}', '{"Account": "1234567890123"}'])
def test_a_reply_to_the_read_of_the_caller_that_names_no_account_is_an_identity_that_could_not_be_read(twin: Rig, reply: str) -> None:
    """The verification of WP8's fixes (verify-fixes#8). A reply that came back with exit 0 and named no account (an empty one, one
    in another shape) refused the stop as `identity-other-account`, while every other reply that cannot be read (denied, no
    JSON, cut off) lets it go on. Only a reply that NAMES an account, twelve digits, can name another one."""
    twin.edit(lambda a: a.update(reply_garbage={"sts get-caller-identity": reply}))
    trips = twin.account()["trips"]
    ran = twin.run("trip", expect=0)
    assert "trip: the caller's identity could not be read (identity-unreadable): the stop goes on" in ran.err
    assert "identity-other-account" not in ran.err and twin.account()["trips"] == trips + 1 and STATUS_SAID in ran.out and MOVED not in ran.err
    # a reply that names another account is refused as before, by the one read
    twin.edit(lambda a: a.pop("reply_garbage"))
    twin.edit(other_account)
    since = len(twin.log())
    ran = twin.run("trip", expect=1)
    assert "refused: identity-other-account:" in ran.err and twin.account()["trips"] == trips + 1
    assert [e["argv"][:2] for e in twin.log()[since:]] == [["sts", "get-caller-identity"]]


def test_a_call_by_hand_keeps_its_values_without_a_profile_and_the_file_gives_the_read_that_finds_the_certificates_id(
        twin: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The hard review of WP8's fixes (fable-wp8), NIT 4, and the rehearsal's item 5, NIT 3. With the profile's slot alone open,
    every one of the four calls was a comment although every other value was there, for a value the manual stop never puts into
    the calls. And with the certificate's id open, the two calls that keep the device out were comments and the file said
    only that the id is a fact of the state. The calls are written without --profile now where the names give none, and the
    file gives, as a comment, the read that finds the id in the account: by the policy's name, or by the thing's."""
    common = "--region %s --profile %s" % (REGION, PROFILE)
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PROFILE": "tiny-zz"})
    assert ran.rc == 1 and "refused: names-invalid: TWIN_PROFILE" in ran.err
    the_file_came_first(twin, ran, said, seen)
    lines, notes = by_hand(twin)
    text = (twin.state / HAND_FILE).read_text(encoding="utf-8")
    assert lines == whole_by_hand(profile="") and "--profile" not in "".join(lines) and "<PROFILE>" not in "".join(lines)
    left_off = "<PROFILE>: TWIN_PROFILE is not given in the form twinctl takes for it" + TW.PROFILE_LEFT_OFF
    assert "#   " + left_off in notes and OPEN + left_off in ran.err and TW.FIND_CERT not in notes and "tiny-zz" not in ran.text + text
    assert "run them under the operator profile (AWS_PROFILE, or --profile NAME on each line)" in TW.PROFILE_LEFT_OFF
    # the certificate's id open (the names file's twin is another than the state's): the read, by that twin's policy
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PREFIX": ANOTHER, "TWIN_THING": ANOTHER + "-thing"})
    lines, notes = by_hand(twin)
    assert notes[-2:] == [TW.FIND_CERT, "#   aws iot list-targets-for-policy --policy-name %s-device %s" % (ANOTHER, common)]
    assert FOUND_BY in ran.err and len(lines) == 2 and ANOTHER not in ran.text          # a comment: the lines to run stay the manual stop's
    assert "a read that changes nothing" in TW.FIND_CERT and "what follows `cert/`" in TW.FIND_CERT
    # ... by the thing's name where the prefix, and with it the policy's name, is not given
    twin.write_names(TWIN_PREFIX=None)
    ran, said, seen = told(twin, monkeypatch)
    assert by_hand(twin)[1][-2:] == [TW.FIND_CERT, "#   aws iot list-thing-principals-v2 --thing-name %s %s" % (THING, common)]
    assert FOUND_BY in ran.err and THING not in ran.text
    twin.write_names()
    # ... without the profile when that is not given either, and not at all without the region: the read is no more whole than a call
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PROFILE": "tiny-zz", "TWIN_ACCOUNT": OTHER_ACCOUNT})
    assert by_hand(twin)[1][-1] == "#   aws iot list-targets-for-policy --policy-name %s-device --region %s" % (PREFIX, REGION)
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_REGION": TW.GLOBAL_REGION})
    assert TW.FIND_CERT not in by_hand(twin)[1] and FOUND_BY not in ran.text
    # ... and not where the id is there
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 0 and TW.FIND_CERT not in by_hand(twin)[1] and FOUND_BY not in ran.text and by_hand(twin)[0] == whole_by_hand()
    # both reads are calls the operator role's policy lets through
    policy = twin.doc("operator-role", "operator-role-policy")
    assert TW.operator_gaps(policy, [TW.R("iot", "list-targets-for-policy", "--policy-name", "x"),
                                     TW.R("iot", "list-thing-principals-v2", "--thing-name", "x")]) == []


def test_a_rehearsals_trip_says_in_its_file_and_on_the_terminal_whose_set_the_calls_are(twin: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The verification of WP8's fixes (verify-fixes#7). `--rehearsal trip` writes the same file, with the rehearsal's rule, thing
    and certificate, and its head and the terminal said `this twin`. One file name serves both sets; each run says whose it
    wrote, in the file and on the terminal, and a trip of the twin writes the twin's again."""
    hand = twin.state / HAND_FILE
    ran, said, seen = told(twin, monkeypatch, "--rehearsal", "trip")
    assert said[0] == WRITTEN_FOR % "the rehearsal's set" + str(hand) and "this twin" not in ran.out.split("\n")[0]
    assert by_hand(twin)[1][1] == ("# For THE REHEARSAL'S SET (--rehearsal) and NOT the twin, as far as the names file and the state give "
                                   "them. They are for when the function did not make the cut:")
    assert by_hand(twin)[0][0] == whole_by_hand(prefix=PREFIX + "rh")[0]
    ran, said, seen = told(twin, monkeypatch, "--rehearsal", "trip", env={"TWIN_PREFFIX": "x"})
    assert ran.rc == 1 and said[-1] == ("With the rehearsal's set's own values, as far as the names file and the state give them, they are "
                                        "in %s (written before this refusal was said)." % hand)
    ran, said, seen = told(twin, monkeypatch)
    assert said[0] == WRITTEN + str(hand) == WRITTEN_FOR % "this twin" + str(hand) and by_hand(twin)[0] == whole_by_hand()
    assert by_hand(twin)[1][1].startswith("# For this twin, as far as the names file and the state give them.")
    assert AGAIN == ("With this twin's own values, as far as the names file and the state give them, they are in %s (written before this "
                     "refusal was said).")


def test_the_file_a_failed_write_got_as_far_as_is_named_when_it_holds_this_runs_calls_and_taken_away_when_it_does_not(
        twin: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rehearsal's item 5, NIT 6. When the file's own place was taken, the terminal said that the file could NOT be written,
    while this run's four calls lay whole in the file the write had got as far as, which nothing named and nothing removed.
    It is named now, and is the run's file from there on; one that does not hold the calls whole is taken away."""
    hand, tmp = twin.state / HAND_FILE, twin.state / (HAND_FILE + ".tmp")
    hand.mkdir()                                                    # the file's own place is taken
    ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 0 and seen == {} and said[0].startswith(NOT_WRITTEN.split("(")[0] + "(an error no check names (")
    assert said[5] == TW.HAND_KEYS and said[6] == ("trip: THIS RUN'S four calls, for this twin, are whole in %s all the same: the write got "
                                                  "as far as that file and could not put it in the file's place." % tmp)
    assert [x for x in tmp.read_text(encoding="utf-8").split("\n") if x.startswith("aws ")] == whole_by_hand()
    assert "<state>" in ran.err and str(twin.state) not in ran.text and not clean(ran.text)
    # ... and a trip that then ends before its invoke names the calls once more by that file
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PREFFIX": "x"})
    assert ran.rc == 1 and said[-1] == AGAIN % tmp and TW.HAND_KEYS not in said[seen["at"]:]
    hand.rmdir()
    tmp.unlink()
    # a first file that does not hold this run's calls whole is nobody's: taken away, and not named
    whole = TW.write_atomic

    def half(path: Path, data: bytes) -> None:
        if path.name != HAND_FILE:
            whole(path, data)
            return
        path.with_name(path.name + ".tmp").write_bytes(data[:len(data) // 2])
        raise OSError(28, "no space left on the device")

    with monkeypatch.context() as m:
        m.setattr(TW, "write_atomic", half)
        ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 0 and not tmp.exists() and not hand.exists() and "THIS RUN'S" not in ran.text and said[5] == TW.HAND_KEYS
    assert said[0] == NOT_WRITTEN % "an error no check names (OSError)" + "The four calls (sdv/cloud/README.md), under the operator profile:"


def test_a_mistyped_stop_gets_its_file_in_the_state_directory_its_line_names_and_no_word_it_could_not_read_is_printed(
        twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The verification of WP8's fixes (verify-fixes#4) and its hard review (fable-wp8, NIT 2). A mistyped stop that named its
    state directory by `--state DIR` got no file and was told that no state directory is named, which was not so; and with
    the option after the command's word, argparse's own message printed the directory as typed, where no literal and no
    mask was loaded yet. The directory is read from the line's own words now: the file is written there, the directory is
    masked, and of the words that could not be read only the options' names are printed."""
    hand = twin.state / HAND_FILE
    lines = [(["trip", "--state", str(twin.state), "--capure", "x"], "--state --capure and 2 word(s)"),
             (["--state=" + str(twin.state), "trip", "--capure", "x"], "--capure and 1 word(s)"),
             (["trip", "--capure=x", "--state=" + str(twin.state)], "--capure --state; no value")]
    for argv, said_of_it in lines:
        if hand.exists():
            hand.unlink()
        since = len(twin.log())
        ran, said, seen = told(twin, monkeypatch, *argv, state=False)
        assert ran.rc == 2 and twin.log()[since:] == [] and "no state directory is named" not in ran.text, argv
        the_file_came_first(twin, ran, said, seen)
        assert by_hand(twin)[0] == whole_by_hand() and ("unrecognized arguments: " + said_of_it) in ran.err, (argv, ran.err)
        assert "; no value typed is printed); --help lists the commands" in ran.err
    # the line's own directory comes before the environment's, as on a line that can be read
    other = tmp_path / "another-state"
    other.mkdir()
    hand.unlink()
    ran, said, seen = told(twin, monkeypatch, "trip", "--state", twin.state, "--capure", "x", env={"TWIN_STATE": str(other)}, state=False)
    assert hand.is_file() and list(other.iterdir()) == [] and str(twin.state) not in ran.text
    # a word typed after an option nobody knows is not printed: at this point no literal is loaded that could mask it
    ran = twin.run("trip", "--profile", PROFILE, expect=2)
    assert "unrecognized arguments: --profile and 1 word(s) that are not printed; no value typed is printed" in ran.err and PROFILE not in ran.text
    ran = twin.run("status", "--capure=" + THING, PREFIX, expect=2)
    assert "unrecognized arguments: --capure and 1 word(s) that are not printed" in ran.err and PREFIX not in ran.text and "by hand" not in ran.text
    ran = twin.run(PREFIX, expect=2)
    assert "invalid choice: (the word is not printed) (choose from" in ran.err and PREFIX not in ran.text and "trip" in ran.err
    assert TW.said_unreadable("the following arguments are required: command") == "the following arguments are required: command"
    assert TW.said_unreadable("argument --min-vss-keys: invalid int value: 'x9'") == ("argument --min-vss-keys: invalid int value: (the word is "
                                                                                      "not printed)")
    assert TW.typed_state(["--state", "a", "trip", "--state=b"]) == "b" and TW.typed_state(["trip", "--state"]) == "" and TW.typed_state([]) == ""


def test_an_ambiguous_option_an_argument_an_option_ignored_and_a_quoted_word_print_nothing_that_was_typed_after_the_option(
        twin: Rig) -> None:
    """The last verification of WP8's fixes (verify-final#1, N1). said_unreadable() masked `unrecognized arguments` and a word
    argparse calls invalid, but two other forms of its message print a word as typed: `ambiguous option: --r=VALUE could match
    --render, --rehearsal` and `argument --rehearsal: ignored explicit argument 'VALUE'` (a renamed profile typed after the
    wrong option, before any literal is loaded); and a word argparse quotes in double quotes, because it holds a single
    quote, passed the mask of an invalid one. The option is cut at its `=` now and the quoted word masked in either quotes, so
    that of the words a line could not read only the options' names are printed, as the README and the docstring say."""
    typed = PROFILE_2
    ambiguous = "ambiguous option: --%s=(the word is not printed) could match --render, --rehearsal"
    ignored = "argument --%s: ignored explicit argument (the word is not printed)"
    hand = twin.state / HAND_FILE
    for argv, said_of_it in ((["--r=" + typed, "trip"], ambiguous % "r"),
                             (["--re=" + typed, "trip"], ambiguous % "re"),
                             (["--r=%s could match --render" % typed, "trip"], ambiguous % "r"),
                             (["--r=" + typed, "status"], ambiguous % "r"),
                             (["--rehearsal=" + typed, "trip"], ignored % "rehearsal"),
                             (["--rehearsal=%s'" % typed, "trip"], ignored % "rehearsal"),
                             (["baseline", "--again=" + typed], ignored % "again"),
                             (["exit-checks", "--capture", "x", "--min-vss-keys", typed + "'"], "argument --min-vss-keys: invalid int value: (the "
                                                                                                 "word is not printed)"),
                             ([typed + "'"], "invalid choice: (the word is not printed) (choose from")):
        if hand.exists():
            hand.unlink()
        ran = twin.run(*argv, expect=2)
        assert "twinctl: the command line cannot be read (" in ran.err and said_of_it in ran.err, (argv, ran.err)
        assert typed not in ran.text and str(twin.state) not in ran.text and not clean(ran.text), argv
        assert hand.is_file() == ("trip" in argv), argv
    # an option typed with nothing after it is its name alone, and stays whole
    ran = twin.run("--re", "x", "trip", expect=2)
    assert "(ambiguous option: --re could match --render, --rehearsal)" in ran.err
    for message, said in (("ambiguous option: --r=a=b could match --x could match --render, --rehearsal",
                           "ambiguous option: --r=(the word is not printed) could match --render, --rehearsal"),
                          ("argument --rehearsal: ignored explicit argument 'a\\'b\"c'", ignored % "rehearsal"),
                          ("argument --min-vss-keys: invalid int value: \"x'9\"",
                           "argument --min-vss-keys: invalid int value: (the word is not printed)"),
                          ("argument command: invalid choice: \"it's\" (choose from 'literals', 'trip')",
                           "argument command: invalid choice: (the word is not printed) (choose from 'literals', 'trip')")):
        assert TW.said_unreadable(message) == said, message

    def fold(text: str) -> str:
        return " ".join(text.replace("`", "").split())

    said = "of the words it could not read only the options' names are printed, each as typed up to its =."
    assert said in fold(str(TW.__doc__)) and said in fold((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))


def test_a_mistyped_stop_that_names_its_state_directory_twice_gets_its_file_in_the_last_one_as_argparse_takes_it(
        twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The last verification of WP8's fixes (verify-final, live mutant V08: typed_state() taking the FIRST `--state` of a line
    passed every test, none of which typed two in the same form). argparse takes the last `--state` of a line it can read; the
    words of a line it cannot read are read the same way, so the file of the four calls goes where the state would have been."""
    other = tmp_path / "another-state"
    other.mkdir()
    assert TW.parser().parse_args(["--state", str(other), "--state", str(twin.state), "status"]).state == str(twin.state)
    hand = twin.state / HAND_FILE
    for argv in (["--state", other, "--state", twin.state, "trip", "--capure", "x"],
                 ["trip", "--state", other, "--capure", "x", "--state", twin.state],
                 ["--state=%s" % other, "trip", "--state", twin.state, "--capure", "x"]):
        if hand.exists():
            hand.unlink()
        ran, said, seen = told(twin, monkeypatch, *argv, state=False)
        assert ran.rc == 2 and list(other.iterdir()) == [] and str(other) not in ran.text, argv
        the_file_came_first(twin, ran, said, seen)
        assert by_hand(twin)[0] == whole_by_hand(), argv
    assert TW.typed_state(["--state", "a", "--state", "b", "trip"]) == "b" and TW.typed_state(["--state=a", "--state", "b"]) == "b"


def test_only_the_one_region_is_refused_and_its_neighbours_are_regions_like_any_other(tmp_path: Path) -> None:
    """The last verification of WP8's fixes (verify-final, live mutant V22: every `us-east-*` region refused passed every test).
    K3 refuses the ONE region whose buckets take no LocationConstraint, by its whole name; a region beside it is taken, and its
    bucket is rendered with that region as its constraint."""
    for region in (j("us-", "east-2"), j("us-", "west-2")):
        rig = Rig(tmp_path / region)
        rig.write_names(TWIN_REGION=region)
        rig.run("literals", expect=0)
        ran = rig.run("plan", "--no-cli", expect=0)
        assert "names-region-not-taken" not in ran.text and rig.doc("bucket", "bucket-location") == {"LocationConstraint": region}, region


def test_a_state_made_under_the_default_region_records_its_names_and_holds_every_command_to_them(tmp_path: Path) -> None:
    """The last verification of WP8's fixes (verify-final, live mutant V24, the one that matters: with the clause
    `or k == "TWIN_REGION"` gone from names_changed(), a state made under a names file that leaves the region to its default
    records no names, and every names-changed refusal is off for it; no test built such a twin and looked at its binding).
    The region is the one bound name with a default: a state made under the default records it with the others, a command
    under another region is refused by the key, and the default given by its value is the same name."""
    rig = Rig(tmp_path / "default-region")
    rig.write_names(TWIN_REGION=None)
    rig.start()
    names = state_of(rig)["names"]
    assert sorted(names) == sorted(TW.BOUND_NAMES)
    for argv in (["plan", "--no-cli"], ["status"], ["trip"]):
        ran = rig.run(*argv, env={"TWIN_REGION": REGION}, expect=1)
        assert "refused: names-changed:" in ran.err and "(TWIN_REGION; no value is printed)" in ran.err and REGION not in ran.text, argv
    rig.write_names(TWIN_REGION=TW.REGION_DEFAULT)
    rig.run("plan", "--no-cli", expect=0)
    assert state_of(rig)["names"] == names


def test_a_kind_the_owner_added_to_the_literals_file_is_taken_by_every_command_and_by_a_stop_whose_file_is_behind(
        twin: Rig, rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rehearsal's item 5, SHOULD 1, and the verification of WP8's fixes (verify-fixes#6). THE REGION IS NO LITERAL OF THE
    DRIVER'S: the one document that holds nothing else, the bucket's location, prints it. An owner who keeps it off the terminal
    adds a kind `region` to the literals file by hand; `twinctl literals` keeps a kind that is not its own. And a stop whose
    literals file is behind (it always is under another profile or role) printed a value of such a kind, because its own
    redactor held the names file's and the state's values only: it takes the kinds a readable file holds as well now."""
    word = j("a-word-of", "-the-owner", "-zz")
    ran = rig.run("apply", "bucket", expect=3)
    assert '"LocationConstraint": "%s"' % REGION in ran.out          # what is so without the kind: the region is printed
    for r in (twin, rig):
        path = r.state / "literals.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["literals"].update({"owners-own": [word], "region": [REGION]})
        path.write_text(json.dumps(doc), encoding="utf-8")
    ran = rig.run("apply", "bucket", expect=3)
    assert '"LocationConstraint": "<region>"' in ran.out and REGION not in ran.text and not clean(ran.text)
    rig.run("literals", expect=0)
    kept = json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))["literals"]
    assert kept["region"] == [REGION] and kept["owners-own"] == [word] and "region" not in TW.OWN_KINDS
    assert REGION not in rig.go("apply", "bucket").text and list(rig.account()["buckets"]) == ["%s-telemetry-%s" % (PREFIX, SUFFIX)]
    # the built twin: a word of the owner's kind that a reply holds is masked by every command ...
    twin.edit(lambda a: a["alarms"][PREFIX + "-bytes"].update(StateValue=word))
    ran = twin.run("status")
    assert "<owners-own>" in ran.out and word not in ran.text and REGION not in ran.text
    # ... and by a stop under a renamed profile, whose literals file is behind
    twin.edit(lambda a: a.update(profile=PROFILE_2))
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PROFILE": PROFILE_2})
    assert "the literals file is missing or behind (literals-behind)" in ran.err and "trip: the function ran" in ran.out
    assert "<owners-own>" in ran.out and word not in ran.text and PROFILE_2 not in ran.text and REGION not in ran.text and not clean(ran.text)
    # a file the redactor does not take (here: of another version) gives nothing, and ends no stop: the names file's and the
    # state's own values still go
    (twin.state / "literals.json").write_text(json.dumps({"v": 2, "literals": {"owners-own": [word]}}), encoding="utf-8")
    ran = twin.run("trip", env={"TWIN_PROFILE": PROFILE_2})
    assert "(literals-refused)" in ran.err and word in ran.out and PROFILE_2 not in ran.text and THING not in ran.text and "redaction" not in ran.err


def test_after_a_trip_the_go_live_steps_read_as_not_live_and_what_refuses_them_names_restore(twin: Rig) -> None:
    """The rehearsal's item 5, NIT 2. After a trip, `status` and `verify-gone` said `not found` of go-live-rule and of
    go-live-certificate beside `DIFFERS: it is disabled` of the rule: the rule and the certificate are there, and are not live.
    And `apply go-live-rule`, approved again, was refused with the sentence written for the alarm tests, then with
    `recorded-not-found ... teardown clears the record`, neither of which names what the owner does after a trip."""
    twin.run("trip", expect=0)
    rows = status_lines(twin.run("status"))
    for step in ("go-live-rule", "go-live-certificate"):
        assert rows[step].endswith("created    " + TW.NOT_LIVE) and "not found" not in rows[step], rows[step]
    assert TW.NOT_LIVE == "not live (tripped, or not made live)" and TW.GO_LIVE == ("go-live-rule", "go-live-certificate")
    assert "DIFFERS: " in rows["rule"] and rows["bucket"].endswith("as rendered")
    ran = twin.go("apply", "go-live-rule", expect=1)
    assert "refused: precondition:" in ran.err and "(after an alarm's test the policy is attached again first). " + TW.AFTER_A_TRIP in ran.err
    assert "`twinctl restore` (sdv/cloud/README.md) gives the three calls that make it live again" in TW.AFTER_A_TRIP
    # with the policy attached again by hand and nothing else put back
    twin.edit(lambda a: a["certs"][CERT_1].update(policies=[PREFIX + "-device"]))
    ran = twin.go("apply", "go-live-rule", expect=1)
    assert "refused: recorded-not-found:" in ran.err and "`twinctl teardown go-live-rule` clears the record. " + TW.AFTER_A_TRIP in ran.err
    assert twin.account()["rules"][PREFIX + "_telemetry"]["ruleDisabled"] is True
    ran = twin.run("verify-gone", expect=1)
    assert re.search(r"^  by name   go-live-rule +not live \(tripped, or not made live\)$", ran.out, re.M), ran.out
    assert re.search(r"^  by name   go-live-certificate +not live \(tripped, or not made live\)$", ran.out, re.M), ran.out


def test_of_a_function_error_only_its_kind_goes_into_a_capture_unless_its_message_is_the_functions_own(twin: Rig, tmp_path: Path) -> None:
    """The rehearsal's item 5, NIT 4. `trip --capture` copied a function error's payload with its message, redacted by the
    redactor alone, while the terminal withholds that same message when it is not in the function's own sentence forms. The
    rule of the terminal holds for the copy now: the kind, in the form a kind has, and a sentence in the message's place."""
    planted = "KeyError: the environment said %s and a word nobody listed, zq7" % j("some", "thing", "-private")
    twin.edit(lambda a: a.update(function_error=True, record_extra={"errorType": "KeyError", "errorMessage": planted, "stackTrace": [planted]}))
    ran = twin.run("trip", "--capture", tmp_path / "one", expect=1)
    assert json.loads((tmp_path / "one" / "trip-record.json").read_text(encoding="utf-8")) == {"errorType": "KeyError",
                                                                                              "errorMessage": TW.WITHHELD_MESSAGE}
    assert "zq7" not in "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "one").iterdir()) + ran.text
    assert "zq7" in (twin.state / "replies" / "payload-trip.json").read_text(encoding="utf-8")       # the whole payload stays where it was
    # the function's own type with a message outside its forms; a kind that has not the form of one
    for n, (kind, message, want) in enumerate([("BreakerError", OUTSIDE_ITS_FORMS[0], "BreakerError"), ("a kind; zq7", OWN_ONE, TW.NO_KIND),
                                               (7, OWN_ONE, TW.NO_KIND)]):
        twin.edit(lambda a, kind=kind, message=message: a.update(record_extra={"errorType": kind, "errorMessage": message}))
        twin.run("trip", "--capture", tmp_path / ("more-%d" % n), expect=1)
        got = json.loads((tmp_path / ("more-%d" % n) / "trip-record.json").read_text(encoding="utf-8"))
        assert got == {"errorType": want, "errorMessage": TW.WITHHELD_MESSAGE}, kind
    # the function's own failure message, in its own sentence forms, goes as the function wrote it; and so does a record of a run
    twin.edit(lambda a: a.update(record_extra={"errorType": "BreakerError", "errorMessage": OWN_ONE}))
    twin.run("trip", "--capture", tmp_path / "own", expect=1)
    got = json.loads((tmp_path / "own" / "trip-record.json").read_text(encoding="utf-8"))
    assert got["errorType"] == "BreakerError" and got["errorMessage"] == OWN_ONE
    twin.edit(lambda a: (a.pop("record_extra"), a.pop("function_error")))
    twin.run("trip", "--capture", tmp_path / "ran", expect=0)
    assert json.loads((tmp_path / "ran" / "trip-record.json").read_text(encoding="utf-8"))["mode"] == "trip"
    assert TW.captured_payload({"mode": "trip"}, b"as it came") == b"as it came" and TW.captured_payload([], b"x") == b"x"
    assert "withheld from the capture" in TW.WITHHELD_MESSAGE


def test_the_rehearsals_plan_holds_its_calls_to_the_twins_operator_policy(rig: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The verification of the rehearsal (verify-rehearsal#2). `--rehearsal plan` held none of its calls to the operator role's
    policy (`not rendered here: not held`), although A2 sends them under that role and one operation stands in the rehearsal's
    plan alone: the shadow's update. The twin's policy is rendered from the same names now, written nowhere, and held to
    them; a policy that cannot be rendered holds nothing, which is said and fails the plan."""
    ran = rig.run("--rehearsal", "plan", "--no-cli", expect=0)
    assert "0 gap(s) in the operator role's policy." in ran.out and "not held" not in ran.out
    plan = json.loads((rig.render / "rehearsal-plan.json").read_text(encoding="utf-8"))
    alone = ["iot-data", "update-thing-shadow"]
    assert plan["operator_policy_gaps"] == [] and alone in [c[:2] for c in every_call(rig, "rehearsal-plan.json")]
    assert not [p for p in rig.render.rglob("operator-role*") if p.name != "offline"]          # written nowhere
    rig.run("plan", "--no-cli", expect=0)
    assert alone not in [c[:2] for c in every_call(rig)]            # the twin's own plan lists no such call
    tampered(monkeypatch, tmp_path, "operator-role-policy", lambda d: _allow(d, "DenyPublicPaths")["Action"].append("iot:UpdateThingShadow"))
    monkeypatch.setitem(TW.DENIES, "operator-role-policy", TW.OPERATOR_DENY + ("iot:UpdateThingShadow",))
    assert "0 gap(s) in the operator role's policy." in rig.run("plan", "--no-cli", expect=0).out          # ... so only the rehearsal's net sees it
    ran = rig.run("--rehearsal", "plan", "--no-cli", expect=1)
    assert ("the operator role's policy: iot:UpdateThingShadow (iot-data update-thing-shadow) is denied by the statement "
            "DenyPublicPaths") in ran.err and "1 gap(s) in the operator role's policy." in ran.out and not clean(ran.text)
    assert json.loads((rig.render / "rehearsal-plan.json").read_text(encoding="utf-8"))["operator_policy_gaps"] != []
    # a policy that cannot be rendered holds nothing
    monkeypatch.setitem(TW.DENIES, "operator-role-policy", TW.OPERATOR_DENY)
    ran = rig.run("--rehearsal", "plan", "--no-cli", expect=1)
    assert "the operator role's policy could not be rendered for the rehearsal's calls (document-refused:operator-role-policy)" in ran.err
    assert "(the role's policy is not rendered here: not held)" in ran.out and "1 refused for an input that is not there or not fit" in ran.out


def test_the_docstring_the_readme_and_the_names_template_say_what_the_review_of_wp8s_fixes_decided() -> None:
    """The sentences this round's fixes are written down in stand in the driver's docstring, in the README and in the names
    template (white space and code marks aside): each said something else before, or nothing."""
    def fold(text: str) -> str:
        return " ".join(text.replace("`", "").split())

    doc = fold(str(TW.__doc__))
    readme = fold((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))
    example = fold((REPO / "sdv" / "cloud" / ".env.example").read_text(encoding="utf-8").replace("\n# ", "\n"))
    for said in ("THE STOP NEEDS NO OPERATOR ROLE: a names file that lost TWIN_OPERATOR_ROLE, or gives it in a form the driver does not take, is "
                 "said by the key and the trip goes on",
                 "A reply to the read of the caller that names no account is an identity that could not be read, not another account.",
                 "AN INVOKE THAT WAS SENT AND WHOSE ANSWER IS NOT KNOWN (a reply that is no JSON, a CLI cut off, a reply that could not be "
                 "written) is said so: the function may have run, status follows, and the trip is not called refused before its invoke.",
                 "THE CALLER IS READ ONCE MORE BEFORE A TRIP'S STATUS: when the profile now answers for another account, no status is printed",
                 "IN THE FILE a call is written without --profile where the names file gives none in its form",
                 "where the certificate's id is open, a comment gives the read that finds it in the account",
                 "the file it got as far as (trip-by-hand.txt.tmp) is named if it holds this run's calls whole",
                 "in the state directory it names by --state or by TWIN_STATE; of the words it could not read only the options' names are printed",
                 "With no CLI that runs, the manual stop's console way is named after the calls.",
                 "A go-live step whose rule or certificate is read and is not live says not live (tripped, or not made live)",
                 "With --rehearsal, whose table holds no role, the twin's policy is rendered from the same names, written nowhere, and held to "
                 "the rehearsal's calls",
                 "Of a function error only its kind goes into a capture, unless its message is the function's own in its own sentence forms",
                 "THE REGION IS NO LITERAL OF THE DRIVER'S: the redactor does not treat a region as an identifier",
                 "a stop whose literals file is behind (another role or profile) still takes the kinds the file holds"):
        assert said in doc, said
    for said in ("The stop needs no operator role: a names file that lost TWIN_OPERATOR_ROLE, or gives it in a form the driver does not "
                 "take, is said by the key and the trip goes on.",
                 "An invoke that was sent and whose answer is not known (a reply that is no JSON, a CLI cut off) is said so: the function may "
                 "have run, status follows, and the trip is not called refused before its invoke.",
                 "The caller is read once more before a trip's status: when the profile now answers for another account, no status is printed",
                 "In the file a call is written without --profile where the names file gives none in its form",
                 "a comment gives the read that finds the certificate's id where the state does not give it",
                 "a rehearsal's trip says in the file's head and on the terminal that the file is the rehearsal's set's",
                 "the file it got as far as (trip-by-hand.txt.tmp) is named if it holds this run's calls whole",
                 "of the words it could not read only the options' names are printed",
                 "With no CLI that runs, the plan's console way is named after the calls.",
                 "After a trip under a renamed profile or role, trip is the only command that runs: status, restore and teardown stay refused "
                 "(names-changed) until the names file gives the names of the state again",
                 "Until then the status that the trip itself printed is the one proof at hand.",
                 "A go-live step whose rule or certificate is read and is not live says not live (tripped, or not made live): what a trip "
                 "leaves is there.",
                 "with --rehearsal, whose table holds no role, the twin's policy is rendered from the same names, written nowhere, and held to "
                 "the rehearsal's calls, which are sent under that role too",
                 "Of a function error only its kind goes into a capture, unless its message is the function's own in its own sentence forms",
                 "The region is no literal of the driver's.",
                 "Whether the region is kept so is the owner's to say before the first step in the account.",
                 "A capture is called clean only by a scan with the state's literals",
                 "Both scan commands list the first 50 findings and, when there are more, a count of every shape"):
        assert said in readme, said
    for said in ("Nor does a trip need the role's key: with TWIN_OPERATOR_ROLE gone from this file, or not in its form, it says so and goes "
                 "on (every other command is refused). The profile it does need: every call is sent under it.",
                 "The region is no literal: the bucket's location document prints it"):
        assert said in example, said


def test_the_docstring_the_readme_and_the_names_template_say_what_wp8_fixed() -> None:
    """The sentences WP8's fixes are written down in stand in the driver's docstring, in the README and in the names template, each in
    its own words (white space and code marks aside): each said something else before, or nothing."""
    def fold(text: str) -> str:
        return " ".join(text.replace("`", "").split())

    doc = fold(str(TW.__doc__))
    readme = fold((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))
    example = fold((REPO / "sdv" / "cloud" / ".env.example").read_text(encoding="utf-8").replace("\n# ", "\n"))
    for said in ("ITS FIRST ACT is the file of the manual stop's four calls by hand, <state>/trip-by-hand.txt, written before anything of the trip "
                 "can be refused",
                 "THE STOP IS HELD TO THE ACCOUNT ONLY.",
                 "NO ENDING OF A TRIP IS ONLY A REFUSAL",
                 "trip is not held to the role or to the profile",
                 "us-east-1 is refused where the names are read, by the key and never by the value (names-region-not-taken)"):
        assert said in doc, said
    for said in ("Its first act is the file of the four calls by hand, <state>/trip-by-hand.txt, written before anything of the trip can be "
                 "refused",
                 "or by another operator role or profile than the state was made under: it is held to the account only, and a caller of "
                 "another account is refused",
                 "No ending of a trip is only a refusal",
                 "One exception, the owner's decision of 2026-10-12: trip is not held to the role or to the profile.",
                 "us-east-1 is refused where the names are read (names-region-not-taken), by the key and never by the value",
                 "plan knows which actions a call needs, not which resources an action is authorised on",
                 "(trip-by-hand.txt, unredacted) are in the state directory"):
        assert said in readme, said
    for said in ("Any region but us-east-1: twinctl refuses that one where it reads the names (names-region-not-taken)",
                 "trip alone is not held to these two: under another profile or role than the state's it goes on, under the profile given "
                 "here."):
        assert said in example, said
    assert "A trip that is refused prints the four calls by hand." not in readme
    assert "A trip that is refused prints the manual stop's four calls" not in doc


# ================================================================================================= wp8-review-fix-exact

def test_a_state_that_records_no_names_yet_gives_its_certificate_to_the_calls_by_hand(twin: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """wp8-verify-fixes, mutant O01. The certificate's id is held to the names a state was made under (STOP_NAMES). A state that
    records NO names is taken as the driver takes it everywhere: it is bound with its next write, and its certificate is this
    twin's. That is the state the salt-missing refusal tells the owner to make (take the entry `names` out of state.json): a stop
    right after it must still get all four calls. Nothing held it: with such a state read as another twin's the whole file passed."""
    state = json.loads((twin.state / "state.json").read_text(encoding="utf-8"))
    assert isinstance(state.pop("names"), dict) and state["facts"]["certificate_id"] == CERT_1
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PREFFIX": "x"})          # ended before its invoke: nothing is sent or written
    assert ran.rc == 1 and "refused: names-key-unknown:" in ran.err and twin.log()[since:] == []
    the_file_came_first(twin, ran, said, seen)
    assert by_hand(twin)[0] == whole_by_hand() and OPEN not in ran.text
    assert "names" not in json.loads((twin.state / "state.json").read_text(encoding="utf-8"))
    # ... and with the salt gone as well, which is where that advice is given: no salt is read for a state that records no names
    (twin.state / "salt").rename(twin.state / "salt.kept")
    ran, said, seen = told(twin, monkeypatch, env={"TWIN_PREFFIX": "x"})
    assert ran.rc == 1 and by_hand(twin)[0] == whole_by_hand() and OPEN not in ran.text and not (twin.state / "salt").exists()


def test_a_mistyped_stop_of_the_rehearsal_gets_the_rehearsals_set_and_never_the_twins(twin: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                      tmp_path: Path) -> None:
    """wp8-verify-fixes, mutant O02. A command line that names `--rehearsal trip` and cannot be read gets the file first, for the
    REHEARSAL's set: its names and its own state's certificate. Nothing held which set a mistyped stop writes: with the twin's set
    written for it (the twin's rule, thing and certificate, under a sentence that says `this twin`) the whole file passed."""
    twin.go("apply", "certificate", "--rehearsal")
    since = len(twin.log())
    ran, said, seen = told(twin, monkeypatch, "--rehearsal", "trip", "--capure", tmp_path / "capture")
    assert ran.rc == 2 and "twinctl: the command line cannot be read" in ran.err and twin.log()[since:] == []
    hand = twin.state / HAND_FILE
    assert said[0] == WRITTEN_FOR % "the rehearsal's set" + str(hand) and 0 < seen["at"] and seen["file"] == hand.read_bytes()
    assert said[-1] == ("With the rehearsal's set's own values, as far as the names file and the state give them, they are in %s (written "
                        "before this refusal was said)." % hand)
    assert by_hand(twin)[0] == whole_by_hand(prefix=PREFIX + "rh", thing=PREFIX + "rh-thing", cert=CERT_2)
    assert CERT_1 not in hand.read_text(encoding="utf-8")


def test_a_trip_is_not_ended_by_an_error_of_its_own_file_that_is_no_error_of_the_system(twin: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """wp8-verify-fixes, mutant O25. hand_first NEVER RAISES: whatever its own file could not do, the stop goes on. The tests gave it
    a write that fails, which is an error of the system; with its net narrowed to those the whole file passed. Here the making of
    the file's text raises an error of another class: the calls and their keys are printed, and the trip goes on to its invoke."""
    def broken(_state_dir: Path, _rehearsal: bool) -> Tuple[str, List[str]]:
        raise RuntimeError("an error of the test's own")

    since = len(twin.log())
    with monkeypatch.context() as m:
        m.setattr(TW, "hand_text", broken)
        ran, said, seen = told(twin, monkeypatch)
    assert ran.rc == 0 and seen == {} and [c[:2] for c in twin.writes(since)] == [["lambda", "invoke"]]
    assert said[0] == NOT_WRITTEN % "an error no check names (RuntimeError)" + "The four calls (sdv/cloud/README.md), under the operator profile:"
    assert said[1:6] == ["  " + line for line in BY_HAND] + [TW.HAND_KEYS] and not (twin.state / HAND_FILE).exists()
    assert ENDED not in ran.text and "an error of the test's own" not in ran.text and not clean(ran.text)


def test_plan_without_the_clis_reading_names_no_call_as_read_by_forms_only(rig: Rig) -> None:
    """wp8-review-fix-exact, item1#2. With --no-cli no call is given to the CLI, so none is said to have been read by option names and
    value forms only: no such line is printed and plan.json holds an empty list."""
    ran = rig.run("plan", "--no-cli", expect=0)
    assert "read by option names" not in ran.out and "The calls were NOT given to the CLI" in ran.out
    assert json.loads((rig.render / "plan.json").read_text(encoding="utf-8"))["read_names_and_forms_only"] == []


def test_plan_lists_the_certificates_delete_and_the_principals_read_among_the_calls_outside_the_table_from_any_state(
        rig: Rig, planned: Rig) -> None:
    """wp8-review-fix-exact, item1#4 (wp8-item1, finding 3). The table lists `iot delete-certificate` and `iot list-thing-principals-v2`
    only once the state holds the certificate's id, so that from the state the operator role is made from (no id) plan gave neither to
    the CLI and held the operator role's policy to neither. The calls outside the table list both: with the placeholder id where the
    state has none, with the id where it has."""
    rig.run("plan", "--no-cli", expect=0)
    other = json.loads((rig.render / "plan.json").read_text(encoding="utf-8"))["other"]
    assert ["iot", "delete-certificate", "--certificate-id", TW.PROVISIONAL_CERT_ID] in other["creates"]
    assert ["iot", "list-thing-principals-v2", "--thing-name", THING] in other["reads"]
    other = json.loads((planned.render / "plan.json").read_text(encoding="utf-8"))["other"]
    assert ["iot", "delete-certificate", "--certificate-id", CERT_1] in other["creates"]
    assert ["iot", "list-thing-principals-v2", "--thing-name", THING] in other["reads"]


def test_the_operator_roles_put_object_takes_the_one_buckets_athena_results_and_no_other_key(rig: Rig) -> None:
    """wp8-review-fix-exact, item1#3. A `*` of IAM takes `/` as well: the resource that read `arn:aws:s3:::<prefix>*/athena-results/*`
    took any key that HOLDS `/athena-results/`, such as telemetry/x/athena-results/y, which the bucket policy lets through because it
    lies under telemetry/. The statement names the one bucket now, and its key wildcard follows the one prefix. The plan is run
    in the test itself: a render the driver's list of wildcard exceptions does not take is refused, and that is the test's failure."""
    rig.run("plan", "--no-cli", expect=0)
    bucket = "%s-telemetry-%s" % (PREFIX, SUFFIX)
    resource = statements(rig.doc("operator-role", "operator-role-policy"))["AthenaResults"]["Resource"]
    assert resource == "arn:aws:s3:::%s/athena-results/*" % bucket and resource.count("*") == 1

    def takes(key: str) -> bool:
        return fnmatch.fnmatchcase("arn:aws:s3:::" + key, resource)

    assert takes(bucket + "/athena-results/q.csv") and takes(bucket + "/athena-results/a/b.csv")
    for key in (bucket + "/telemetry/x/athena-results/y", bucket + "/errors/athena-results/y", PREFIX + "-other/athena-results/q.csv",
                bucket + "x/athena-results/q.csv", bucket + "/athena-results"):
        assert not takes(key), key


def test_the_docstring_and_the_readme_say_what_the_exact_fixes_decided() -> None:
    """wp8-review-fix-exact. The sentences this round is written down in stand in the driver's docstrings and in the README (white
    space and code marks aside): the calls plan read by names and forms only, and the certificate's id of a state that records no
    names; each said something else before."""
    def fold(text: str) -> str:
        return " ".join(text.replace("`", "").split())

    doc, readme = fold(str(TW.__doc__)), fold((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))
    validate = fold(str(TW.Aws.validate.__doc__))
    stop = fold(str(TW.stop_certificate.__doc__))
    forms = "only the options' names, the required options and each value's form were read"
    assert forms in doc and forms in validate and forms in readme
    assert "the service model's validation of the call's own arguments never ran" in doc
    assert "the service model's validation of the call's own arguments never ran" in readme
    assert ("For such a call only the options' names, the required options and each value's form were read: the service model's "
            "validation of the call's own arguments never ran") in readme
    assert "plan names these calls by service and operation (no value) on a line and in plan.json (read_names_and_forms_only)" in doc
    assert ("plan names these calls by service and operation, no value, on a line before its summary and in plan.json "
            "(read_names_and_forms_only)") in readme
    assert "a member that is missing or unknown in a document the call gave by file or as a structure is the call's own refusal" in readme
    assert "which says nothing of the arguments" not in doc + readme and "after the arguments were read" not in doc + readme
    narrowed = ("state that records no names yet (one made before its first write, or one whose entry names was taken out on the "
                "salt-missing advice) gives its certificate with no comparison")
    assert narrowed in doc and narrowed in stop
    assert ("(a state that records no names yet, one made before its first write or one whose entry names was taken out on the "
            "salt-missing advice, gives its certificate with no comparison)") in readme
    assert "another twin's id is never put beside this twin's names" not in doc
    assert "Otherwise another twin's id is not put beside this twin's names." in doc


# ================================================================================================= Phase 6 WP4: what stands as it was

# A salt of the test's own, written into a copy of a rig, so that a render's hash can be held: a state's own salt is random.
FIXED_SALT = hashlib.sha256(b"a test's salt, fixed so that a render's hash can be held: no state's").digest()


def renders_of(rig: Rig, tmp: Path, rehearsal: bool = False, env: Optional[Dict[str, str]] = None,
               only: Optional[Any] = None) -> Dict[str, str]:
    """EVERY STEP'S RENDER, ONE DIGEST A STEP (Phase 6 spec section 5, item 1): of the hash `apply` prints (render_hash over the
    creates of the strict render), the hash `teardown` prints (over the deletes of the render a teardown makes) and the reads
    and the listing `status`, `verify-gone` and `plan` send, in a copy of the rig whose salt is FIXED_SALT and with the rig's
    own directory written as <base> (the one part of a call that moves with the test's directory, on either platform); and
    the same of OTHER, the calls outside the table. A render that is refused is held by the refusal's name. `only` keeps
    the steps of those ids. 24 hex digits a step: 96 bits, and a short line per step in the table below."""
    copy = rig.copy(tmp, logs=False)
    (copy.state / "salt").write_bytes(FIXED_SALT)
    # the signing request's bytes as a POSIX checkout writes them: an approval covers an input's content, and Windows Python's
    # text mode would end the fixture's line otherwise
    (copy.inputs / "device.csr").write_bytes(b"a test's placeholder, not a signing request\n")
    base = copy.base.as_posix()

    def norm(calls: List[Any]) -> List[Any]:
        return [TW.Call(c.service, c.op, tuple(a.replace(base, "<base>") for a in c.args), c.write) for c in calls]

    saved = dict(os.environ)
    out: Dict[str, str] = {}
    try:
        for k in list(os.environ):
            if k.startswith(("TWIN_", "AWS_")):
                del os.environ[k]
        os.environ.update(env or {})
        t = TW.Twin(copy.state, None, rehearsal)
        for step in t.steps + [TW.OTHER]:
            if only is not None and step.id not in only:
                continue
            parts = []
            for strict, mode in ((True, "apply"), (False, "teardown")):
                try:
                    rd = t.render(step, strict)
                    parts.append(TW.render_hash(t, rd, mode, norm(rd.built.creates if strict else rd.built.deletes)))
                    if not strict:
                        reads = [c for _k, c in rd.built.reads] + ([TW.LISTINGS[step.listing][0]] if step.listing else [])
                        parts.append(json.dumps([c.argv() for c in norm(reads)]))
                except TW.TwinError as e:
                    parts.append("refused:" + e.name)
            out[step.id] = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return out


def outputs_of(rig: Rig, tmp: Path) -> Dict[str, str]:
    """What `status`, `exit-checks`, `teardown` (the order), `verify-gone` and `plan --no-cli` print on a copy of the rig, and the
    literals file `literals` writes, each by the sha256 of its exit status, stdout and stderr (the local directories are masked
    by the driver's own names for them, and `plan`'s render directory with them)."""
    copy = rig.copy(tmp, logs=False)
    out = {}
    for name, argv in (("status", ["status"]), ("exit-checks", ["exit-checks", "--capture", copy.base / "capture"]),
                       ("teardown", ["teardown"]), ("verify-gone", ["verify-gone"]), ("plan", ["plan", "--no-cli"]),
                       ("literals", ["literals"])):
        ran = copy.run(*argv)
        text = ran.out + "\0" + ran.err + ("\0" + (copy.state / "literals.json").read_text(encoding="utf-8") if name == "literals" else "")
        out[name] = hashlib.sha256(("%d\0%s" % (ran.rc, text)).encode("utf-8")).hexdigest()[:24]
    return out


# What `renders_of` and `outputs_of` gave at the baseline recorded before any edit of Phase 6 WP4 (the
# source comparison uses these tests' names, inputs and stub). The function pins include the publication scrub's
# comment/docstring-only breaker source change, because its zip holds those bytes. Every other render pin is retained.
# `status`, `exit-checks`, the teardown's order, `verify-gone`, `plan` and `literals` keep their output pins while
# neither TWIN_ECR nor TWIN_PULL_ROLE is given.
HELD_RENDERS: Dict[str, Dict[str, str]] = {
    "started": {
        "alarm-notice": "761e5d5930bab9754cb12256", "alarm-test-bytes": "2f5d0dc5cf6d61453481db07",
        "alarm-test-failure": "93e7ae2359259c7290d73ab2", "alarm-test-publish": "a2b8e6c7eb821fe1a88016c5",
        "alarm-test-records": "c26ad12baa9d98cddea65e43", "alarm-test-shadow": "ea123ebba523f6b55df1f505",
        "alarms": "be0985d920d1306dfcd7da38", "attachments": "6a545eb26a4bdfab2ed65be6", "breaker-log": "50eb8be37d3c93c17356b001",
        "breaker-role": "ff8750e242bbac07a51911ea", "bucket": "c2468954899ef2576b0f819f", "bucket-objects": "d29dbbf789c7a4024184ef16",
        "certificate": "69f5d958b0d287178e31fc70", "dry-trip": "20f1349f6f72f05e3b80d57d", "firehose-log": "b27f58761077a8d69bd380aa",
        "firehose-role": "52b4063fc0dd410031a14239", "function": "1679ef280c645d7436d66502",
        "function-concurrency": "5c23891335a46ae6c96b0cde", "function-policy": "fc64402f0278e78b65efad7a",
        "function-status": "542638ef90824ac0721e569d", "glue": "6005f8206c1392f53b3b31ba",
        "go-live-certificate": "d622ea0bf70d89506c99f298", "go-live-rule": "ca6a41e0ac33922663fad61d",
        "iot-log-group": "7c657ecb8e9fc8cb54d8573f", "iot-logging": "3ada0c1842f191f933141c45",
        "iot-logging-role": "f15be7e6fa3727af9ed8f862", "notice-topic": "f1a77942eab9f85824f72197",
        "operator-role": "4f3d53c3b98510094f3927a6", "other": "b78d2adac96901f796ae3c13", "policy": "cbd15c00f093ec54281e9765",
        "reattach-policy": "03b961fcdaf32b7dc2ee4eee", "rule": "c910f1ebb26414851eb2fc59", "rule-role": "229917c50254bed294f75b4b",
        "shadows": "12b38ae2867afda5da7ad58a", "stream": "5f2a2097042db0dce2a4fcac", "thing": "afbe91b8071a55990ed6394d",
        "workgroup": "d148bafc807d43dacc045878"},
    "started-no-notice": {
        "alarm-test-bytes": "2f5d0dc5cf6d61453481db07", "alarm-test-failure": "93e7ae2359259c7290d73ab2",
        "alarm-test-publish": "a2b8e6c7eb821fe1a88016c5", "alarm-test-records": "c26ad12baa9d98cddea65e43",
        "alarm-test-shadow": "ea123ebba523f6b55df1f505", "alarms": "eb8944fba45677a635e68c43", "attachments": "6a545eb26a4bdfab2ed65be6",
        "breaker-log": "50eb8be37d3c93c17356b001", "breaker-role": "ff8750e242bbac07a51911ea", "bucket": "c2468954899ef2576b0f819f",
        "bucket-objects": "d29dbbf789c7a4024184ef16", "certificate": "69f5d958b0d287178e31fc70", "dry-trip": "20f1349f6f72f05e3b80d57d",
        "firehose-log": "b27f58761077a8d69bd380aa", "firehose-role": "52b4063fc0dd410031a14239", "function": "1679ef280c645d7436d66502",
        "function-concurrency": "5c23891335a46ae6c96b0cde", "function-policy": "fc64402f0278e78b65efad7a",
        "function-status": "542638ef90824ac0721e569d", "glue": "6005f8206c1392f53b3b31ba",
        "go-live-certificate": "d622ea0bf70d89506c99f298", "go-live-rule": "ca6a41e0ac33922663fad61d",
        "iot-log-group": "7c657ecb8e9fc8cb54d8573f", "iot-logging": "3ada0c1842f191f933141c45",
        "iot-logging-role": "f15be7e6fa3727af9ed8f862", "operator-role": "4f3d53c3b98510094f3927a6", "other": "b78d2adac96901f796ae3c13",
        "policy": "cbd15c00f093ec54281e9765", "reattach-policy": "03b961fcdaf32b7dc2ee4eee", "rule": "c910f1ebb26414851eb2fc59",
        "rule-role": "229917c50254bed294f75b4b", "shadows": "12b38ae2867afda5da7ad58a", "stream": "5f2a2097042db0dce2a4fcac",
        "thing": "afbe91b8071a55990ed6394d", "workgroup": "d148bafc807d43dacc045878"},
    "built": {
        "alarm-notice": "761e5d5930bab9754cb12256", "alarm-test-bytes": "2f5d0dc5cf6d61453481db07",
        "alarm-test-failure": "93e7ae2359259c7290d73ab2", "alarm-test-publish": "a2b8e6c7eb821fe1a88016c5",
        "alarm-test-records": "c26ad12baa9d98cddea65e43", "alarm-test-shadow": "ea123ebba523f6b55df1f505",
        "alarms": "be0985d920d1306dfcd7da38", "attachments": "4eebedafe2a7b510ca7e32d4", "breaker-log": "50eb8be37d3c93c17356b001",
        "breaker-role": "46b0f093626945e1a223ed7c", "bucket": "c2468954899ef2576b0f819f", "bucket-objects": "d29dbbf789c7a4024184ef16",
        "certificate": "3a04a3140ad836f9e344efbb", "dry-trip": "20f1349f6f72f05e3b80d57d", "firehose-log": "b27f58761077a8d69bd380aa",
        "firehose-role": "52b4063fc0dd410031a14239", "function": "e79ed8fe1e219fb2ce3792c6",
        "function-concurrency": "5c23891335a46ae6c96b0cde", "function-policy": "fc64402f0278e78b65efad7a",
        "function-status": "542638ef90824ac0721e569d", "glue": "6005f8206c1392f53b3b31ba",
        "go-live-certificate": "a02d59eb96e3d873c5834ecd", "go-live-rule": "ca6a41e0ac33922663fad61d",
        "iot-log-group": "7c657ecb8e9fc8cb54d8573f", "iot-logging": "3ada0c1842f191f933141c45",
        "iot-logging-role": "f15be7e6fa3727af9ed8f862", "notice-topic": "f1a77942eab9f85824f72197",
        "operator-role": "4f3d53c3b98510094f3927a6", "other": "a63afb265c8656658cee8f9f", "policy": "cbd15c00f093ec54281e9765",
        "reattach-policy": "34ebcbea6cb7d909622cfa21", "rule": "c910f1ebb26414851eb2fc59", "rule-role": "229917c50254bed294f75b4b",
        "shadows": "12b38ae2867afda5da7ad58a", "stream": "5f2a2097042db0dce2a4fcac", "thing": "afbe91b8071a55990ed6394d",
        "workgroup": "d148bafc807d43dacc045878"},
    "built-row-19": {
        "alarm-test-rule-count": "f8342449bab31f0fba8af58a", "rule-count-alarm": "a493fb6816bc02a92d7e6ecc"},
    "rehearsal": {
        "alarms": "a3f52713bea40d223dde9a0d", "attachments": "b6de61782111aad781fc4880", "bucket": "3732d815cf727af32f4f5e06",
        "bucket-objects": "5138883cba77ebd8d5d9c15c", "certificate": "22262728fc33aba3cbf9a525",
        "firehose-log": "fe7b7c9603e55788995b1de2", "glue": "392b26fe0df5b5a6b4ec6f4f", "notice-topic": "ae6759213f5e2ad1b2684c14",
        "other": "312d760f7be5fa45af4d9101", "policy": "cab05655204006a7ae81eed2", "shadows": "91a75b06aacf7583da7c6710",
        "thing": "541995a3a513ffd77f15318a", "workgroup": "42f6a3ff24328a85a8be4a5e"},
}
HELD_OUTPUTS: Dict[str, str] = {
    "status": "3199b568b7ed1294e7fb7db1", "exit-checks": "3fe407b4d315d1f1b1686cbc", "teardown": "805f963739ce433f4926032a",
    "verify-gone": "e39606e6890d1a745187f7ad", "plan": "1577874a8c01ef80a98b05f7", "literals": "14f9b0f887a57759b5822b51"}


@pytest.mark.parametrize("variant", sorted(HELD_RENDERS))
def test_every_existing_step_renders_as_at_the_image_transport_baseline_without_a_new_key(variant: str, started: Rig, built: Rig,
                                                                                       tmp_path: Path) -> None:
    """Phase 6 spec section 5, item 1: with TWIN_ECR unset and no TWIN_PULL_ROLE, every existing step's render, its hash as `apply`
    and `teardown` print it, its reads and its listing keep the held pins, the operator role's policy among them; the
    calls outside the table too. The function zip's pin includes the publication scrub's prose-only source change. Held
    from the started and built rig, without the notice, with row 19's readings and for the rehearsal's set."""
    readings = {"TWIN_RULE_COUNT_METRIC": "RulesExecuted", "TWIN_RULE_COUNT_DIMENSIONS": "RuleName=%s_telemetry" % PREFIX,
                "TWIN_RULE_COUNT_READING": "per_execution"}
    if variant == "started-no-notice":
        got = renders_of(Rig(tmp_path / "quiet", notice=False).start(), tmp_path / "copy")
    elif variant == "built-row-19":
        got = renders_of(built, tmp_path / "copy", env=readings, only=set(HELD_RENDERS[variant]))
    else:
        got = renders_of(built if variant == "built" else started, tmp_path / "copy", rehearsal=variant == "rehearsal")
    assert {k: v for k, v in got.items() if v != HELD_RENDERS[variant].get(k)} == {} and set(got) == set(HELD_RENDERS[variant])


def test_existing_commands_print_as_at_the_image_transport_baseline(built: Rig, tmp_path: Path) -> None:
    """Item 1 for what the commands print: with no new key, each prints on the built twin what it printed at that baseline."""
    got = outputs_of(built, tmp_path / "copy")
    assert {k: v for k, v in got.items() if v != HELD_OUTPUTS[k]} == {}


# ================================================================================================= Phase 6 WP4: ECR and the pull identity

PULL_ROLE = j("example", "-pull-role", "-zz")
PULL_THING = j(PREFIX, "-pull-thing")
CRED_PREFIX = "c" + hashlib.sha256(b"the stub's credential endpoint").hexdigest()[:13]
CRED_ENDPOINT = j(CRED_PREFIX, ".credentials.iot.", REGION, ".amazonaws.com")
REGISTRY = j(ACCOUNT, ".dkr.ecr.", REGION, ".amazonaws.com")
ECR_PASSWORD = j("a-test-password", "-that-is-no-token")
REPOSITORY = "sdv-twin/hard-brake-hazard"
ALIAS = "sdv-twin-ecr-pull"
ALIAS_ARN = "arn:aws:iot:%s:%s:rolealias/%s" % (REGION, ACCOUNT, ALIAS)
REPOSITORIES_ARN = "arn:aws:ecr:%s:%s:repository/sdv-twin/*" % (REGION, ACCOUNT)
PHASE6_IDENTIFIERS = (PULL_ROLE, CRED_PREFIX, CRED_ENDPOINT, REGISTRY, ECR_PASSWORD)
ECR_STEPS = ["ecr-repository", "ecr-lifecycle"]
PULL_STEPS = ["pull-role", "role-alias", "pull-policy", "pull-certificate", "pull-attachment", "pull-active", "pull-inactive"]
# ECR Public's actions of the access levels Write, Permissions management and Tagging, as the Service Authorization Reference's
# ECR Public page lists them (read 2026-10-17)
ECR_PUBLIC_WRITES = sorted(["ecr-public:BatchDeleteImage", "ecr-public:CompleteLayerUpload", "ecr-public:CreateRepository",
                            "ecr-public:DeleteRepository", "ecr-public:DeleteRepositoryPolicy", "ecr-public:InitiateLayerUpload",
                            "ecr-public:PutImage", "ecr-public:PutRegistryCatalogData", "ecr-public:PutRepositoryCatalogData",
                            "ecr-public:SetRepositoryPolicy", "ecr-public:TagResource", "ecr-public:UntagResource",
                            "ecr-public:UploadLayerPart"])


def clean6(text: str) -> List[str]:
    """clean(), and none of Phase 6's own fixture identifiers either."""
    return clean(text) + ["phase 6 identifier %d" % i for i, value in enumerate(PHASE6_IDENTIFIERS) if value in text]


def with_keys(rig: Rig, ecr: bool = True, pull: bool = True, thing: bool = False) -> Rig:
    """The rig with Phase 6's keys in its environment, the Orin's placeholder signing request, the stub's credential endpoint and
    registry password, and the literals written again (the pull role is a literal)."""
    if ecr:
        rig.extra["TWIN_ECR"] = "1"
    if pull:
        (rig.inputs / "orin.csr").write_bytes(b"the Orin's placeholder, not a signing request\n")
        rig.extra.update(TWIN_PULL_ROLE=PULL_ROLE, TWIN_ORIN_CSR=str(rig.inputs / "orin.csr"),
                         TWIN_ORIN_CERTIFICATE_OUT=str(rig.inputs / "orin.crt"))
    if thing:
        rig.extra["TWIN_PULL_THING"] = PULL_THING
    rig.edit(lambda a: a.update(credential_endpoint=CRED_ENDPOINT, ecr_password=ECR_PASSWORD))
    rig.run("literals", expect=0)
    return rig


def owner_makes_pull_role(rig: Rig) -> None:
    """The owner makes the pull role by hand, from its render."""
    rig.run("apply", "pull-role", expect=1)                         # rendered; not there yet
    rig.edit(lambda a: a["roles"].update({PULL_ROLE: {"trust": rig.doc("pull-role", "pull-role-trust"),
                                                      "policies": {PULL_ROLE + "-policy": rig.doc("pull-role", "pull-role-policy")}}}))
    rig.run("apply", "pull-role", expect=0)


def build_phase6(rig: Rig) -> Rig:
    """The ECR steps (with TWIN_ECR) and the pull steps (rows B1-B3), each approved as shown; the two actions are left out."""
    steps = (ECR_STEPS if rig.extra.get("TWIN_ECR") == "1" else []) + PULL_STEPS[:3] + (["pull-thing"] if "TWIN_PULL_THING" in rig.extra else [])
    for step in steps + ["pull-certificate", "pull-attachment"]:
        if step == "pull-role":
            owner_makes_pull_role(rig)
        else:
            rig.go("apply", step)
    return rig


@pytest.fixture(scope="module")
def phase6(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """Literals and a baseline, then the ECR and pull steps (rows B1-B3): nothing of the twin's own table is made."""
    rig = with_keys(Rig(tmp_path_factory.mktemp("phase6") / "twin").start())
    rig.run("plan", "--no-cli", expect=0)
    return build_phase6(rig)


@pytest.fixture
def p6(tmp_path: Path, phase6: Rig) -> Rig:
    return with_keys(phase6.copy(tmp_path / "p6"))


def step_ids(rig: Rig) -> List[str]:
    rig.run("plan", "--no-cli", expect=0)
    return [s["id"] for s in rig.plan()]


PULL_POLICY = PREFIX + "-ecr-pull"


def set_status(r: Rig, step: str, status: str) -> None:
    p = r.state / "state.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    s["steps"][step]["status"] = status
    p.write_text(json.dumps(s, indent=1), encoding="utf-8")


def facts(r: Rig) -> Dict[str, Any]:
    return json.loads((r.state / "state.json").read_text(encoding="utf-8"))["facts"]


def test_with_the_new_keys_every_existing_step_but_the_operator_roles_renders_as_before(started: Rig, built: Rig, tmp_path: Path) -> None:
    """Item 1, the other way round: the new keys add steps, the operator role's new statements and the new calls outside the
    table, and change no other existing step's render; TWIN_ECR=0 is the same as no key."""
    pull = (tmp_path / "orin.csr")
    pull.write_bytes(b"the Orin's placeholder, not a signing request\n")
    keys = {"TWIN_ECR": "1", "TWIN_PULL_ROLE": PULL_ROLE, "TWIN_ORIN_CSR": str(pull), "TWIN_ORIN_CERTIFICATE_OUT": str(tmp_path / "orin.crt")}
    for variant, rig in (("started", started), ("built", built)):
        got = renders_of(rig, tmp_path / variant, env=keys, only=set(HELD_RENDERS[variant]))
        assert {k for k, v in got.items() if v != HELD_RENDERS[variant][k]} == {"operator-role", "other"}, variant
        got = renders_of(rig, tmp_path / (variant + "-ecr"), env={"TWIN_ECR": "1"}, only=set(HELD_RENDERS[variant]))
        assert {k for k, v in got.items() if v != HELD_RENDERS[variant][k]} == {"operator-role", "other"}, variant
        assert renders_of(rig, tmp_path / (variant + "-zero"), env={"TWIN_ECR": "0"}) == HELD_RENDERS[variant]


def test_the_ecr_steps_are_in_the_table_only_with_twin_ecr_and_after_every_existing_step(rig: Rig, built: Rig, tmp_path: Path) -> None:
    before = step_ids(rig)
    assert not [s for s in before if s.startswith(("ecr-", "pull-")) or s == "role-alias"]
    rig.extra["TWIN_ECR"] = "0"
    assert step_ids(rig) == before
    rig.extra["TWIN_ECR"] = "1"
    assert step_ids(rig) == before + ECR_STEPS
    # on the built twin too, after row 19's steps: so a teardown removes them first
    twin = built.copy(tmp_path / "twin")
    twin.write_names(TWIN_RULE_COUNT_METRIC="RulesExecuted", TWIN_RULE_COUNT_DIMENSIONS="RuleName=%s_telemetry" % PREFIX,
                     TWIN_RULE_COUNT_READING="per_execution")
    with_keys(twin)
    ids = step_ids(twin)
    assert ids[-len(ECR_STEPS + PULL_STEPS):] == ECR_STEPS + PULL_STEPS and ids.index("alarm-test-rule-count") < ids.index("ecr-repository")
    assert teardown_ids(twin)[:7] == ["pull-attachment", "pull-certificate", "pull-policy", "role-alias", "ecr-lifecycle", "ecr-repository",
                                      "rule-count-alarm"]
    assert not clean6("".join(r.text for r in twin.said))


def test_the_repository_is_immutable_aes256_tagged_has_no_policy_and_its_lifecycle_keeps_ten(rig: Rig) -> None:
    """Item 2: create-repository with IMMUTABLE, AES256 given explicitly and the twin's tag, no scanning configuration; one
    lifecycle rule, priority 1, any tag status, more than 10; no call of any command sets a repository policy."""
    with_keys(rig, pull=False)
    rig.run("plan", "--no-cli", expect=0)
    plan = {s["id"]: s for s in rig.plan()}
    create, = plan["ecr-repository"]["creates"]
    assert create == ["ecr", "create-repository", "--repository-name", REPOSITORY, "--image-tag-mutability", "IMMUTABLE",
                      "--encryption-configuration", "file://" + (rig.render / "ecr-repository" / "repository-encryption.json").as_posix(),
                      "--tags", "file://" + (rig.render / "ecr-repository" / "repository-tags.json").as_posix()]
    assert rig.doc("ecr-repository", "repository-encryption") == {"encryptionType": "AES256"}
    assert rig.doc("ecr-repository", "repository-tags") == [{"Key": "dualvm-twin", "Value": PREFIX}]
    assert rig.doc("ecr-lifecycle", "repository-lifecycle") == {"rules": [{
        "rulePriority": 1, "description": "keep the newest 10 images of the repository", "action": {"type": "expire"},
        "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 10}}]}
    assert plan["ecr-lifecycle"]["creates"] == [["ecr", "put-lifecycle-policy", "--repository-name", REPOSITORY, "--lifecycle-policy-text",
                                                 "file://" + (rig.render / "ecr-lifecycle" / "repository-lifecycle.json").as_posix()]]
    text = json.dumps(every_call(rig))
    assert "set-repository-policy" not in text and "put-registry-policy" not in text and "image-scanning" not in text
    assert TW.ECR_APPS == ("hard-brake-hazard",) and TW.LIFECYCLE_KEEP == 10
    rig.go("apply", "ecr-repository")
    rig.go("apply", "ecr-lifecycle")
    r = rig.account()["repositories"][REPOSITORY]
    assert (r["mutability"], r["encryption"], r["policy"], r["tags"]) == ("IMMUTABLE", {"encryptionType": "AES256"}, None, True)
    assert json.loads(r["lifecycle"]) == rig.doc("ecr-lifecycle", "repository-lifecycle")
    lines = {line.split()[0]: line for line in rig.run("status", expect=0).out.split("\n") if line.startswith("  ")}
    assert "as rendered" in lines["ecr-repository"] and "as rendered" in lines["ecr-lifecycle"]
    assert not clean6("".join(x.text for x in rig.said))


@pytest.mark.parametrize("change,said", [
    (lambda r: r.update(mutability="MUTABLE"), "sdv-twin/hard-brake-hazard: its tags are not IMMUTABLE"),
    (lambda r: r.update(encryption={"encryptionType": "KMS"}), "sdv-twin/hard-brake-hazard: its encryption is not AES256"),
    (lambda r: r.update(policy=json.dumps({"Version": TW.V, "Statement": []})), "sdv-twin/hard-brake-hazard has a repository policy"),
])
def test_a_repository_read_back_otherwise_than_rendered_says_why(p6: Rig, change: Any, said: str) -> None:
    p6.edit(lambda a: change(a["repositories"][REPOSITORY]))
    line = [x for x in p6.run("status").out.split("\n") if x.split()[:1] == ["ecr-repository"]][0]
    assert "DIFFERS: " + said in line


def test_a_lifecycle_policy_read_back_otherwise_than_rendered_says_so(p6: Rig) -> None:
    """verify#9: the lifecycle step compares what it reads with its render (the rule's selection included), not only that a policy
    document is there."""
    other = {"rules": [{"rulePriority": 1, "description": "keep the newest 10 images of the repository", "action": {"type": "expire"},
                        "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 1000}}]}
    p6.edit(lambda a: a["repositories"][REPOSITORY].update(lifecycle=json.dumps(other)))
    line = [x for x in p6.run("status").out.split("\n") if x.split()[:1] == ["ecr-lifecycle"]][0]
    assert "DIFFERS: sdv-twin/hard-brake-hazard: its lifecycle policy is not the render" in line


def test_a_repository_that_is_there_and_not_ours_is_refused_and_not_touched(rig: Rig) -> None:
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(repositories={REPOSITORY: {"mutability": "MUTABLE", "encryption": {"encryptionType": "AES256"},
                                                           "policy": None, "lifecycle": None, "images": [], "tags": False}}))
    digest = rig.shown("apply", "ecr-repository")
    ran = rig.run("apply", "ecr-repository", "--approve", "ecr-repository:" + digest, expect=1)
    assert "refused: exists-not-ours:" in ran.err and rig.writes() == []
    assert rig.account()["repositories"][REPOSITORY]["mutability"] == "MUTABLE"


def test_the_ecr_steps_are_torn_down_after_the_pull_steps_and_a_repository_with_images_is_emptied_first(p6: Rig) -> None:
    """A repository is not deleted while it holds an image (no --force): emptying it is by hand (the README says how)."""
    for step in ("pull-attachment", "pull-certificate", "pull-policy", "role-alias"):
        p6.go("teardown", step)
    assert "refused: teardown-order:" in p6.run("teardown", "ecr-repository", expect=1).err       # the lifecycle stands
    p6.go("teardown", "ecr-lifecycle")
    p6.edit(lambda a: a["repositories"][REPOSITORY]["images"].append({"imageDigest": "sha256:" + "a" * 64, "imageTags": ["1.0.0-arm64"]}))
    digest = p6.shown("teardown", "ecr-repository")
    ran = p6.run("teardown", "ecr-repository", "--approve", "ecr-repository:" + digest, expect=1)
    assert "refused: precondition: the repository sdv-twin/hard-brake-hazard holds 1 image(s)" in ran.err
    assert REPOSITORY in p6.account()["repositories"]
    p6.edit(lambda a: a["repositories"][REPOSITORY]["images"].clear())
    p6.go("teardown", "ecr-repository")
    deletes = [c for c in p6.writes() if c[1].startswith("delete-")]
    assert all("--force" not in c for c in deletes) and p6.account()["repositories"] == {}
    assert "verify-gone: gone" in p6.run("verify-gone", expect=0).out
    assert not clean6("".join(x.text for x in p6.said))


# --- the pull identity

def test_the_pull_steps_are_in_the_table_only_with_twin_pull_role_and_the_thing_only_with_its_key(rig: Rig) -> None:
    before = step_ids(rig)
    with_keys(rig, ecr=False)
    assert step_ids(rig) == before + PULL_STEPS
    rig.extra["TWIN_PULL_THING"] = PULL_THING
    rig.run("literals", expect=0)
    assert step_ids(rig) == before + PULL_STEPS[:3] + ["pull-thing"] + PULL_STEPS[3:]
    plan = {s["id"]: s for s in rig.plan()}
    assert plan["pull-role"]["kind"] == "owner" and plan["pull-active"]["kind"] == plan["pull-inactive"]["kind"] == "action"
    rig.extra["TWIN_PULL_THING"] = j("another", "-thing-zz")
    assert "refused: names-invalid: TWIN_PULL_THING does not begin with TWIN_PREFIX" in rig.run("plan", "--no-cli", expect=1).err


def test_the_pull_roles_trust_is_the_credential_provider_alone_and_its_policy_the_three_ecr_actions(rig: Rig) -> None:
    """Item 3: trust exactly credentials.iot.amazonaws.com with sts:AssumeRole, held to this account and the role alias (the IoT
    guide's confused-deputy example for the credential provider); the policy GetAuthorizationToken on * and BatchGetImage and
    GetDownloadUrlForLayer on the twin's repositories, and nothing else (no BatchImportUpstreamImage)."""
    with_keys(rig, ecr=False)
    rig.run("plan", "--no-cli", expect=0)
    assert rig.doc("pull-role", "pull-role-trust") == {"Version": TW.V, "Statement": [{
        "Sid": "TheCredentialProvider", "Effect": "Allow", "Principal": {"Service": "credentials.iot.amazonaws.com"},
        "Action": "sts:AssumeRole", "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT}, "ArnLike": {"aws:SourceArn": ALIAS_ARN}}}]}
    assert rig.doc("pull-role", "pull-role-policy") == {"Version": TW.V, "Statement": [
        {"Sid": "GetTheToken", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
        {"Sid": "PullFromTheTwinsRepositories", "Effect": "Allow", "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
         "Resource": REPOSITORIES_ARN}]}
    assert TW.TRUSTS["pull-role-trust"] == "credentials.iot.amazonaws.com"
    assert sorted(TW.ALLOWS["pull-role-policy"]) == ["ecr:BatchGetImage", "ecr:GetAuthorizationToken", "ecr:GetDownloadUrlForLayer"]
    assert TW.ALLOWS["pull-policy"] == ("iot:AssumeRoleWithCertificate",)


def test_the_role_alias_is_the_pull_role_for_3600_s_and_the_pull_policy_one_action_on_that_alias(rig: Rig) -> None:
    with_keys(rig, ecr=False)
    rig.run("plan", "--no-cli", expect=0)
    plan = {s["id"]: s for s in rig.plan()}
    assert plan["role-alias"]["creates"] == [["iot", "create-role-alias", "--role-alias", ALIAS, "--role-arn",
                                              "arn:aws:iam::%s:role/%s" % (ACCOUNT, PULL_ROLE), "--credential-duration-seconds", "3600"]]
    assert plan["role-alias"]["reads"] == [["iot", "describe-role-alias", "--role-alias", ALIAS]]
    assert rig.doc("pull-policy", "pull-policy") == {"Version": TW.V, "Statement": [{
        "Sid": "AssumeThePullRoleAlias", "Effect": "Allow", "Action": "iot:AssumeRoleWithCertificate", "Resource": ALIAS_ARN}]}
    assert plan["pull-policy"]["creates"][0][:4] == ["iot", "create-policy", "--policy-name", PREFIX + "-ecr-pull"]
    assert TW.ROLE_ALIAS == ALIAS and TW.ROLE_ALIAS_SECONDS == 3600


@pytest.mark.parametrize("template,step,change", [
    ("pull-role-policy", "pull-role", lambda d: _allow(d, "PullFromTheTwinsRepositories")["Action"].append("ecr:BatchImportUpstreamImage")),
    ("pull-role-policy", "pull-role", lambda d: _allow(d, "PullFromTheTwinsRepositories").update(Resource="*")),
    ("pull-role-policy", "pull-role", lambda d: _allow(d, "GetTheToken").update(Action=["ecr:GetAuthorizationToken", "ecr:BatchGetImage"])),
    ("pull-role-trust", "pull-role", lambda d: d["Statement"][0]["Principal"].update(Service="iot.amazonaws.com")),
    ("pull-role-trust", "pull-role", lambda d: d["Statement"][0]["Condition"].pop("ArnLike")),
    ("pull-policy", "pull-policy", lambda d: d["Statement"][0].update(Action=["iot:AssumeRoleWithCertificate", "iot:Connect"])),
    ("pull-policy", "pull-policy", lambda d: d["Statement"][0].update(Resource="arn:aws:iot:@@REGION@@:@@ACCOUNT@@:rolealias/*")),
    ("repository-encryption", "ecr-repository", lambda d: d.update(encryptionType="KMS")),
    ("repository-lifecycle", "ecr-lifecycle", lambda d: d["rules"][0]["selection"].update(countNumber=1000)),
])
def test_a_phase6_template_that_gains_an_action_another_resource_or_another_value_is_refused(rig: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                                            tmp_path: Path, template: str, step: str,
                                                                                            change: Any) -> None:
    with_keys(rig)
    tampered(monkeypatch, tmp_path, template, change)
    ran = rig.run("plan", "--no-cli", expect=1)
    line = [x for x in ran.out.split("\n") if x.split()[:1] == [step]]
    assert len(line) == 1 and "REFUSED document-refused:" + template in line[0], ran.out
    assert rig.log() == []


def test_the_pull_certificate_is_made_inactive_from_the_orins_csr_and_set_active_and_inactive_by_its_printed_hash(rig: Rig) -> None:
    with_keys(rig, ecr=False)
    owner_makes_pull_role(rig)
    for step in ("role-alias", "pull-policy", "pull-certificate"):
        rig.go("apply", step)
    since = len(rig.log())
    rig.go("apply", "pull-attachment")
    cert, = [c for c, x in rig.account()["certs"].items()]
    arn = "arn:aws:iot:%s:%s:cert/%s" % (REGION, ACCOUNT, cert)
    assert rig.writes(since) == [["iot", "attach-policy", "--policy-name", PREFIX + "-ecr-pull", "--target", arn]]
    create = [c for c in rig.writes() if c[1] == "create-certificate-from-csr"][0]
    assert "--no-set-as-active" in create and create[create.index("--certificate-signing-request") + 1].endswith("/orin.csr")
    assert (rig.inputs / "orin.crt").read_text(encoding="ascii").startswith("-----BEGIN ")
    a = rig.account()
    assert a["certs"][cert] == {"status": "INACTIVE", "policies": [PREFIX + "-ecr-pull"]}
    assert a["role_aliases"][ALIAS] == {"roleArn": "arn:aws:iam::%s:role/%s" % (ACCOUNT, PULL_ROLE), "credentialDurationSeconds": 3600}
    # a board day: ACTIVE by its printed hash, INACTIVE after it by its own; one printing lets one run through
    digest = rig.shown("apply", "pull-active")
    rig.run("apply", "pull-active", "--approve", "pull-active:" + digest, expect=0)
    assert rig.account()["certs"][cert]["status"] == "ACTIVE"
    assert "refused: approval-spent:" in rig.run("apply", "pull-active", "--approve", "pull-active:" + digest, expect=1).err
    rig.go("apply", "pull-inactive")
    assert rig.account()["certs"][cert]["status"] == "INACTIVE"
    assert [c[-2:] for c in rig.writes() if c[1] == "update-certificate"] == [["--new-status", "ACTIVE"], ["--new-status", "INACTIVE"]]
    # its id is a literal, and the twin's certificate step is not refused by it as a name nobody knows
    lits = json.loads((rig.state / "literals.json").read_text(encoding="utf-8"))["literals"]
    assert lits["certificate-id"] == [cert] and lits["pull-role"] == [PULL_ROLE]
    rig.go("apply", "certificate")
    assert not clean6("".join(x.text for x in rig.said)) and cert not in "".join(x.text for x in rig.said)


def test_the_pull_certificate_is_inactive_and_detached_before_its_teardown_and_a_thing_is_attached_only_when_given(rig: Rig) -> None:
    with_keys(rig, thing=True)
    build_phase6(rig)
    cert, = list(rig.account()["certs"])
    arn = "arn:aws:iot:%s:%s:cert/%s" % (REGION, ACCOUNT, cert)
    assert rig.account()["things"][PULL_THING]["principals"] == {arn: "EXCLUSIVE_THING"}
    # verify#11: the attachment is judged exclusive, not only there
    rig.edit(lambda a: a["things"][PULL_THING]["principals"].update({arn: "NON_EXCLUSIVE_THING"}))
    line = [x for x in rig.run("status").out.split("\n") if x.split()[:1] == ["pull-attachment"]][0]
    assert "DIFFERS: the pull certificate's attachment to the pull thing is not exclusive" in line
    rig.edit(lambda a: a["things"][PULL_THING]["principals"].update({arn: "EXCLUSIVE_THING"}))
    rig.go("apply", "pull-active")
    rig.go("teardown", "pull-attachment")
    digest = rig.shown("teardown", "pull-certificate")
    ran = rig.run("teardown", "pull-certificate", "--approve", "pull-certificate:" + digest, expect=1)
    assert "refused: precondition: the pull certificate is not INACTIVE" in ran.err and cert in rig.account()["certs"]
    rig.go("apply", "pull-inactive")
    for step in ("pull-certificate", "pull-thing", "pull-policy", "role-alias"):
        rig.go("teardown", step)
    a = rig.account()
    assert a["certs"] == {} and a["role_aliases"] == {} and PULL_THING not in a["things"] and PREFIX + "-ecr-pull" not in a["policies"]


def test_the_pull_role_is_bound_once_recorded_and_the_stop_is_not_held_to_it(p6: Rig) -> None:
    p6.extra["TWIN_PULL_ROLE"] = j("another", "-pull-role", "-zz")
    for argv in (["status"], ["plan", "--no-cli"], ["apply", "role-alias"]):
        ran = p6.run(*argv, expect=1)
        assert "refused: names-changed: " in ran.err and "TWIN_PULL_ROLE" in ran.err and PULL_ROLE not in ran.text, argv
    # the stop is not held to it: no call of a stop is made of the pull role (this rig has no function, so its invoke fails after)
    ran = p6.run("trip")
    assert "refused: names-changed" not in ran.err and "(nor to the pull role)" in ran.err and PULL_ROLE not in ran.text
    assert [e["argv"][:2] for e in p6.log() if e["w"]][-1:] == [["lambda", "invoke"]]
    del p6.extra["TWIN_PULL_ROLE"]
    ran = p6.run("status", expect=1)
    assert "refused: names-changed: " in ran.err and "TWIN_PULL_ROLE" in ran.err
    p6.extra["TWIN_PULL_ROLE"] = PULL_ROLE
    p6.run("status", expect=0)


def test_a_state_with_the_pull_steps_and_the_ecr_steps_keeps_them_in_its_table_when_the_keys_are_taken_out(p6: Rig) -> None:
    p6.go("teardown", "pull-attachment")
    p6.extra["TWIN_ECR"] = "0"
    ids = [line.split()[0] for line in p6.run("teardown", expect=0).out.split("\n") if line.startswith("  ")]
    assert ids[:5] == ["pull-attachment", "pull-certificate", "pull-policy", "role-alias", "ecr-lifecycle"]


def test_the_pull_role_stays_bound_while_any_pull_step_is_on_record_so_for_good_once_read(p6: Rig) -> None:
    """The decision on the late binding's reach (verify#3): TWIN_PULL_ROLE is held while any pull step is on record, the owner's read
    of the role (`verified`) and a record taken back (`stale`) as well as a resource that stands. twinctl never deletes the owner's pull
    role, so once `apply pull-role` has read it the binding stays for good, as TWIN_OPERATOR_ROLE's does; the way out is the twin's
    own: once nothing stands, `literals` and then `baseline --again` take the new names."""
    for step in ("pull-attachment", "pull-certificate", "pull-policy", "role-alias"):
        p6.go("teardown", step)
    steps = json.loads((p6.state / "state.json").read_text(encoding="utf-8"))["steps"]
    assert steps["pull-role"]["status"] == "verified" and {steps[s]["status"] for s in PULL_STEPS[1:5]} == {"deleted"}
    another = j("another", "-pull-role", "-zz")
    p6.extra["TWIN_PULL_ROLE"] = another
    for argv in (["status"], ["plan", "--no-cli"], ["literals"]):
        ran = p6.run(*argv, expect=1)
        assert "refused: names-changed: " in ran.err and "TWIN_PULL_ROLE" in ran.err and "2 step(s) are recorded as standing" in ran.err, argv
    del p6.extra["TWIN_PULL_ROLE"]
    assert "refused: names-changed: " in p6.run("status", expect=1).err
    # nothing stands once the ECR steps are torn down too: `literals` and then `baseline --again` take the new names
    p6.extra["TWIN_PULL_ROLE"] = PULL_ROLE
    for step in ("ecr-lifecycle", "ecr-repository"):
        p6.go("teardown", step)
    p6.extra["TWIN_PULL_ROLE"] = another
    assert "refused: names-changed: " in p6.run("status", expect=1).err and "Nothing is recorded as standing" in p6.said[-1].err
    p6.run("literals", expect=0)
    p6.run("baseline", "--again", expect=0)
    ran = p6.run("status", expect=0)
    assert "names-changed" not in ran.err and another not in ran.text


def test_the_pull_role_is_free_again_once_every_pull_step_is_deleted_and_bound_again_by_the_next_record(rig: Rig) -> None:
    """verify#21: the binding is held while a pull step is on record, and not after: a pull step made and deleted, with no other one
    on record, leaves another pull role free, and the next pull step recorded binds that one."""
    with_keys(rig, ecr=False)
    rig.go("apply", "pull-policy")
    another = j("another", "-pull-role", "-zz")
    rig.extra["TWIN_PULL_ROLE"] = another
    assert "refused: names-changed: " in rig.run("status", expect=1).err            # the pull policy stands
    rig.extra["TWIN_PULL_ROLE"] = PULL_ROLE
    rig.go("teardown", "pull-policy")
    rig.extra["TWIN_PULL_ROLE"] = another
    rig.run("literals", expect=0)
    assert "names-changed" not in rig.run("status", expect=0).err
    rig.go("apply", "pull-policy")                                   # bound again, to the value it was made under
    rig.extra["TWIN_PULL_ROLE"] = PULL_ROLE
    ran = rig.run("status", expect=1)
    assert "refused: names-changed: " in ran.err and "TWIN_PULL_ROLE" in ran.err


def test_the_pull_thing_is_bound_once_its_step_is_recorded_and_free_again_once_it_is_deleted(rig: Rig) -> None:
    """fable#3: TWIN_PULL_THING is bound from pull-thing's first record and held while that step is on record. Under another thing the
    teardown of pull-attachment would send its detach to a thing that holds nothing, take "not found" for gone and record the
    attachment deleted while the old thing kept the certificate. The stop is not held to it: no call of a stop is made of it."""
    with_keys(rig, thing=True)
    build_phase6(rig)
    another = j(PREFIX, "-pull-thing-two")
    rig.extra["TWIN_PULL_THING"] = another
    before = rig.writes()
    for argv in (["literals"], ["status"], ["teardown", "pull-attachment"]):
        ran = rig.run(*argv, expect=1)
        assert "refused: names-changed: " in ran.err and "TWIN_PULL_THING" in ran.err and another not in ran.text, argv
    assert rig.writes() == before
    ran = rig.run("trip")
    assert "refused: names-changed" not in ran.err and "(nor to the pull thing)" in ran.err
    # given back, torn down in order (the attachment, the certificate, the thing): then another thing is free, and bound by its record
    rig.extra["TWIN_PULL_THING"] = PULL_THING
    for step in ("pull-attachment", "pull-certificate", "pull-thing"):
        rig.go("teardown", step)
    rig.extra["TWIN_PULL_THING"] = another
    rig.run("literals", expect=0)
    assert "names-changed" not in rig.run("status", expect=0).err
    rig.go("apply", "pull-thing")
    assert another in rig.account()["things"] and PULL_THING not in rig.account()["things"]
    rig.extra["TWIN_PULL_THING"] = PULL_THING
    ran = rig.run("status", expect=1)
    assert "refused: names-changed: " in ran.err and "TWIN_PULL_THING" in ran.err


def test_the_owners_read_of_the_pull_role_binds_it_with_no_other_pull_step_recorded(rig: Rig) -> None:
    """verify#20: `apply pull-role` binds TWIN_PULL_ROLE itself (bind_late on the owner's step): with that the only pull step on record,
    the value it was read under goes on being taken, and another is refused. Without the binding the first command after the read
    would be refused under the very value it was read under."""
    with_keys(rig, ecr=False)
    owner_makes_pull_role(rig)
    assert "names-changed" not in rig.run("status", expect=0).err
    another = j("another", "-pull-role", "-zz")
    rig.extra["TWIN_PULL_ROLE"] = another
    ran = rig.run("status", expect=1)
    assert "refused: names-changed: " in ran.err and "TWIN_PULL_ROLE" in ran.err and another not in ran.text


def test_a_role_alias_that_is_not_the_twins_is_neither_a_leftover_nor_in_the_way(rig: Rig) -> None:
    """verify#22: the role-alias listing is held to the twin's namespace (sdv-twin...): an alias of someone else's is not ours to
    find at `verify-gone`."""
    with_keys(rig, ecr=False)
    owner_makes_pull_role(rig)
    rig.edit(lambda a: a.setdefault("role_aliases", {}).update({"someone-elses-alias-zz": {
        "roleArn": "arn:aws:iam::%s:role/someone-elses-role-zz" % ACCOUNT, "credentialDurationSeconds": 3600}}))
    rig.go("apply", "role-alias")
    rig.go("teardown", "role-alias")
    assert list(rig.account()["role_aliases"]) == ["someone-elses-alias-zz"]
    assert "verify-gone: gone" in rig.run("verify-gone", expect=0).out


def test_the_pull_policy_is_not_deleted_while_it_is_attached_to_a_certificate_the_state_does_not_record(p6: Rig) -> None:
    """verify#12: the pull policy's own precondition (its targets, read before the delete) holds it, whatever the state records."""
    for step in ("pull-attachment", "pull-certificate"):
        p6.go("teardown", step)
    nobody = hashlib.sha256(b"a certificate nobody made").hexdigest()
    p6.edit(lambda a: a["certs"].update({nobody: {"status": "INACTIVE", "policies": [PREFIX + "-ecr-pull"]}}))
    before = len(p6.writes())
    digest = p6.shown("teardown", "pull-policy")
    ran = p6.run("teardown", "pull-policy", "--approve", "pull-policy:" + digest, expect=1)
    assert "refused: precondition: the pull policy is still attached to 1 target(s)" in ran.err
    assert PREFIX + "-ecr-pull" in p6.account()["policies"] and len(p6.writes()) == before


# c04: the pull certificate is not deleted while a policy the state no longer records is attached to it
def test_the_pull_certificate_is_not_deleted_while_a_policy_is_attached_to_it_by_hand(p6: Rig) -> None:
    cert, = list(p6.account()["certs"])
    p6.go("teardown", "pull-attachment")
    p6.edit(lambda a: a["certs"][cert]["policies"].append(PULL_POLICY))
    made = len(p6.writes())
    digest = p6.shown("teardown", "pull-certificate")
    ran = p6.run("teardown", "pull-certificate", "--approve", "pull-certificate:" + digest, expect=1)
    assert "refused: precondition: a policy is still attached to the pull certificate" in ran.err
    assert len(p6.writes()) == made and cert in p6.account()["certs"]


# c05: nor while the pull thing holds it
def test_the_pull_certificate_is_not_deleted_while_the_pull_thing_holds_it(started: Rig, tmp_path: Path) -> None:
    r = started.copy(tmp_path / "t", logs=False)
    with_keys(r, ecr=False, thing=True)
    build_phase6(r)
    cert, = list(r.account()["certs"])
    arn = "arn:aws:iot:%s:%s:cert/%s" % (REGION, ACCOUNT, cert)
    r.go("teardown", "pull-attachment")
    r.edit(lambda a: a["things"][PULL_THING]["principals"].update({arn: "EXCLUSIVE_THING"}))
    made = len(r.writes())
    digest = r.shown("teardown", "pull-certificate")
    ran = r.run("teardown", "pull-certificate", "--approve", "pull-certificate:" + digest, expect=1)
    assert "refused: precondition: the pull certificate is still attached to the pull thing" in ran.err
    assert len(r.writes()) == made and cert in r.account()["certs"]


# c15: the id a refused reply gave for the pull certificate is forgotten once its teardown found nothing
def test_the_pull_certificates_unconfirmed_id_is_forgotten_once_it_is_torn_down(rig: Rig) -> None:
    with_keys(rig, ecr=False)
    elsewhere = "arn:aws:iot:eu-central-1:%s:cert/%s" % (ACCOUNT, CERT_1)
    rig.edit(lambda a: a.update(reply_extra={"iot create-certificate-from-csr": {"certificateArn": elsewhere}}))
    assert "refused: reply-unreadable:" in rig.go("apply", "pull-certificate", expect=1).err
    rig.edit(lambda a: a.pop("reply_extra"))
    assert facts(rig).get("pull_certificate_id_unconfirmed") == CERT_1 and "pull_certificate_id" not in facts(rig)
    rig.go("teardown", "pull-certificate")
    assert rig.account()["certs"] == {} and "pull_certificate_id_unconfirmed" not in facts(rig)


def test_the_pull_certificate_is_not_written_inside_a_work_tree(rig: Rig) -> None:
    """verify#19: where the pull certificate's PEM goes is held outside every work tree, before the create call is sent."""
    with_keys(rig, ecr=False)
    owner_makes_pull_role(rig)
    for step in ("role-alias", "pull-policy"):
        rig.go("apply", step)
    rig.extra["TWIN_ORIN_CERTIFICATE_OUT"] = str(REPO / "orin.crt")
    before = len(rig.writes())
    ran = rig.run("apply", "pull-certificate", expect=1)
    assert "refused: inside-a-work-tree:" in ran.err and "the pull certificate's file" in ran.err
    ran = rig.run("apply", "pull-certificate", "--approve", "pull-certificate:" + "0" * 64, expect=1)
    assert "refused: inside-a-work-tree:" in ran.err
    assert not (REPO / "orin.crt").exists() and len(rig.writes()) == before and rig.account()["certs"] == {}


def test_twin_ecr_0_takes_effect_only_once_no_ecr_step_stands(rig: Rig, tmp_path: Path) -> None:
    """fable#2 and verify#4: while an ECR step stands its steps stay in the table, and TWIN_ECR follows them: the operator policy keeps
    the grants they need, `plan` lists push's calls, the exit keeps its ECR rows. Once both are torn down the key decides again."""
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")
    rig.go("apply", "ecr-lifecycle")
    rig.run("plan", "--no-cli", expect=0)
    with_grants = rig.doc("operator-role", "operator-role-policy")
    rig.extra["TWIN_ECR"] = "0"
    ran = rig.run("plan", "--no-cli", expect=0)
    assert "0 gap(s) in the operator role's policy" in ran.out and rig.doc("operator-role", "operator-role-policy") == with_grants
    assert [s["id"] for s in rig.plan()][-2:] == ECR_STEPS
    planned = {sig(c) for c in every_call(rig)}
    assert {("ecr", "get-login-password", ()), ("ecr", "describe-images", ("--image-ids", "--repository-name"))} <= planned
    rig.run("exit-checks", "--capture", tmp_path / "capture", expect=1)
    results = [c["check"] for c in json.loads((tmp_path / "capture" / "exit-checks.json").read_text(encoding="utf-8"))["checks"]]
    assert len([r for r in results if r.startswith("ECR")]) == 5 and len(results) == 12 + 5
    since = len(rig.log())
    digest = printed_hash(rig.run(*push_argv(store, cfg), expect=3))
    rig.run(*push_argv(store, cfg) + ["--approve", "push:" + digest], expect=0)
    assert {sig(e["argv"]) for e in rig.log()[since:]} - planned == set()
    # emptied by hand and torn down: the key decides again, and with it no ECR step and no ECR grant
    rig.edit(lambda a: a["repositories"][REPOSITORY]["images"].clear())
    for step in ("ecr-lifecycle", "ecr-repository"):
        rig.go("teardown", step)
    rig.run("plan", "--no-cli", expect=0)
    assert not [s for s in rig.plan() if s["id"] in ECR_STEPS]
    assert "EcrRepositories" not in {s["Sid"] for s in rig.doc("operator-role", "operator-role-policy")["Statement"]}
    assert not clean6("".join(x.text for x in rig.said))


# c22: TWIN_ECR follows a recorded ECR step in any standing form, not only `created`
@pytest.mark.parametrize("status", ["unverified", "deleting"])
def test_twin_ecr_0_keeps_the_grants_while_the_repository_stands_in_any_form(rig: Rig, status: str) -> None:
    with_keys(rig, pull=False)
    rig.go("apply", "ecr-repository")
    set_status(rig, "ecr-repository", status)
    rig.extra["TWIN_ECR"] = "0"
    ran = rig.run("plan", "--no-cli", expect=0)
    assert "0 gap(s) in the operator role's policy" in ran.out
    assert "EcrRepositories" in {s["Sid"] for s in rig.doc("operator-role", "operator-role-policy")["Statement"]}


# --- status

def test_status_says_an_active_pull_certificate_and_fails_on_an_active_one_outside_both_sets(built: Rig, tmp_path: Path) -> None:
    """Item 4: the function's certificates are exactly the data set; an ACTIVE certificate outside the union fails; the pull
    certificate ACTIVE is said, never a failure."""
    twin = with_keys(built.copy(tmp_path / "twin"), ecr=False)
    build_phase6(twin)
    ran = twin.run("status", expect=0)
    assert "the pull certificate is INACTIVE" in ran.out
    assert "ok: the function's environment names exactly the twin's 1 certificate(s)" in ran.out
    assert "ok: no ACTIVE certificate of the account is outside the twin's set and the pull certificate (2 listed)" in ran.out
    twin.go("apply", "pull-active")
    ran = twin.run("status", expect=0)
    assert "the pull certificate is ACTIVE: active: a board day (`twinctl apply pull-inactive` ends it)" in ran.out
    assert "FAIL" not in ran.text and not clean6(ran.text)
    other = hashlib.sha256(b"a certificate nobody made").hexdigest()
    twin.edit(lambda a: a["certs"].update({other: {"status": "ACTIVE", "policies": []}}))
    ran = twin.run("status", expect=1)
    assert ("FAIL: 1 ACTIVE certificate(s) of the account are outside the twin's set and the pull certificate: the breaker does not act "
            "on them") in ran.err
    # the function's environment holds the data certificate alone: with the pull certificate in it too, that fails
    pull = [c for c in twin.account()["certs"] if c not in (CERT_1, other)][0]
    twin.edit(lambda a: (a["certs"].pop(other), a["functions"][PREFIX + "-breaker"]["config"]["Environment"]["Variables"].update(
        TWIN_CERTIFICATE_ARNS=iot_arn("cert", CERT_1) + "," + iot_arn("cert", pull))))
    assert "FAIL: the certificates in the function's environment are not exactly the twin's" in twin.run("status", expect=1).err


def test_a_pull_certificate_whose_step_is_recorded_deleted_is_no_longer_in_the_pull_set(built: Rig, tmp_path: Path) -> None:
    """verify#18: the pull set is the pull certificate WHILE its step stands. With the record taken to `deleted` and the certificate
    still ACTIVE in the account, it is a certificate outside both sets: status fails on it."""
    twin = with_keys(built.copy(tmp_path / "twin"), ecr=False)
    build_phase6(twin)
    twin.go("apply", "pull-active")
    twin.go("teardown", "pull-attachment")
    state = json.loads((twin.state / "state.json").read_text(encoding="utf-8"))
    state["steps"]["pull-certificate"]["status"] = "deleted"
    (twin.state / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert [c["status"] for c in twin.account()["certs"].values()].count("ACTIVE") == 2
    ran = twin.run("status", expect=1)
    assert "FAIL: 1 ACTIVE certificate(s) of the account are outside the twin's set: the breaker does not act on them" in ran.err


# --- the operator policy (D8)

def operator_doc(rig: Rig) -> Any:
    rig.run("plan", "--no-cli", expect=0)
    return rig.doc("operator-role", "operator-role-policy")


def test_the_operator_policy_gains_the_ecr_and_the_pull_grants_only_with_their_keys(rig: Rig) -> None:
    base = operator_doc(rig)
    with_keys(rig, pull=False)
    ecr = statements(operator_doc(rig))
    rig.extra.pop("TWIN_ECR")
    with_keys(rig, ecr=False)
    pull = statements(operator_doc(rig))
    with_keys(rig)
    both = statements(operator_doc(rig))
    old = statements(base)
    # ECR: the reads with no resource type on *, every repository action on the twin's repositories, ECR Public's writes denied
    assert list(ecr) == list(old)[:-3] + ["EcrRepositories"] + list(old)[-3:]
    assert sorted(set(ecr["NoResourceType"]["Action"]) - set(old["NoResourceType"]["Action"])) == sorted([
        "ecr:GetAuthorizationToken", "ecr:DescribeRegistry", "ecr:GetRegistryPolicy", "ecr:DescribePullThroughCacheRules",
        "ecr:GetRegistryScanningConfiguration", "ecr:DescribeRepositories", "ecr-public:DescribeRepositories"])
    assert ecr["EcrRepositories"] == {"Sid": "EcrRepositories", "Effect": "Allow", "Resource": REPOSITORIES_ARN, "Action": [
        "ecr:CreateRepository", "ecr:DeleteRepository", "ecr:TagResource", "ecr:PutLifecyclePolicy", "ecr:GetLifecyclePolicy",
        "ecr:DeleteLifecyclePolicy", "ecr:GetRepositoryPolicy", "ecr:ListImages", "ecr:DescribeImages", "ecr:BatchDeleteImage",
        "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage",
        "ecr:BatchGetImage"]}
    deny = ecr["DenyPublicPaths"]["Action"]
    assert "ecr-public:*" not in deny and sorted(a for a in deny if a.startswith("ecr-public:")) == ECR_PUBLIC_WRITES
    assert [a for a in deny if not a.startswith("ecr-public:")] == [a for a in old["DenyPublicPaths"]["Action"] if a != "ecr-public:*"]
    allowed = {a for s in ecr.values() if s["Effect"] == "Allow" for a in listed(s["Action"])}
    assert not [(a, d) for a in allowed for d in deny if fnmatch.fnmatchcase(a.lower(), d.lower())]
    assert sorted(TW.ECR_PUBLIC_WRITES) == ECR_PUBLIC_WRITES
    # the pull identity: the alias's create, describe and delete on that alias, its listing on *, the pull role's reads and PassRole
    assert list(pull) == list(old)[:-3] + ["PullRoleAlias", "ReadAndPassThePullRole"] + list(old)[-3:]
    assert set(pull["NoResourceType"]["Action"]) - set(old["NoResourceType"]["Action"]) == {"iot:ListRoleAliases"}
    assert pull["PullRoleAlias"] == {"Sid": "PullRoleAlias", "Effect": "Allow", "Resource": ALIAS_ARN,
                                     "Action": ["iot:CreateRoleAlias", "iot:DescribeRoleAlias", "iot:DeleteRoleAlias"]}
    assert pull["ReadAndPassThePullRole"] == {"Sid": "ReadAndPassThePullRole", "Effect": "Allow",
                                              "Resource": "arn:aws:iam::%s:role/%s" % (ACCOUNT, PULL_ROLE),
                                              "Action": ["iam:GetRole", "iam:GetRolePolicy", "iam:PassRole"]}
    assert "ecr-public:*" in pull["DenyPublicPaths"]["Action"]                  # narrowed with TWIN_ECR only
    # both: the two sets of additions and nothing else; every other statement as it was
    assert list(both) == list(old)[:-3] + ["EcrRepositories", "PullRoleAlias", "ReadAndPassThePullRole"] + list(old)[-3:]
    for sid in old:
        if sid not in ("NoResourceType", "DenyPublicPaths"):
            assert both[sid] == old[sid], sid
    assert len(json.dumps({"Version": TW.V, "Statement": list(both.values())}, separators=(",", ":"))) < 10240


def test_the_wildcard_exceptions_gain_the_twins_repositories_and_the_pull_tokens_star_and_nothing_else(rig: Rig) -> None:
    names = dict(rig.names(), TWIN_ECR="1", TWIN_PULL_ROLE=PULL_ROLE)
    got = TW.wildcard_exceptions(TW.Names(names))
    base = TW.wildcard_exceptions(TW.Names(dict(rig.names())))
    added = {k: v for k, v in got.items() if k not in base or base[k] != v}
    assert added == {("operator-role-policy", "EcrRepositories"): (REPOSITORIES_ARN,),
                     ("pull-role-policy", "PullFromTheTwinsRepositories"): (REPOSITORIES_ARN,), ("pull-role-policy", "GetTheToken"): ("*",)}
    assert all(k in got and got[k] == v for k, v in base.items())


# --- exit-checks (item 6)

def test_exit_checks_with_the_new_keys_adds_the_ecr_and_pull_reads_and_each_passes_on_the_made_steps(p6: Rig, tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    since = len(p6.log())
    ran = p6.run("exit-checks", "--capture", capture, expect=1)                # the twin's own checks fail on a twin that is not made
    assert p6.writes(since) == [] and not clean6(ran.text)
    results = {c["check"]: c for c in json.loads((capture / "exit-checks.json").read_text(encoding="utf-8"))["checks"]}
    new = ["ECR: no repository policy on a sdv-twin/ repository", "ECR: no registry policy",
           "ECR: no replication rule and no pull-through cache rule", "ECR Public holds no repository",
           "ECR: the repositories are exactly the expected ones, IMMUTABLE, AES256", "the pull role: its trust and its policy as rendered",
           "the role alias: the pull role, 3600 s", "the pull policy as rendered", "the pull certificate carries the pull policy and no other"]
    assert list(results)[-len(new):] == new and len(results) == 12 + len(new)
    assert {results[k]["result"] for k in new} == {"pass"}
    assert results["ECR: no replication rule and no pull-through cache rule"]["shape"] == {"replication_rules": 0, "pull_through_cache_rules": 0,
                                                                                          "scan_type": "BASIC"}
    assert results["ECR: the repositories are exactly the expected ones, IMMUTABLE, AES256"]["shape"] == {
        "expected": 1, "listed": 1, "immutable": 1, "aes256": 1}
    public = [e["argv"] for e in p6.log()[since:] if e["argv"][:2] == ["ecr-public", "describe-repositories"]]
    assert len(public) == 1 and public[0][public[0].index("--region") + 1] == "us-east-1" and public[0].count("--region") == 1


@pytest.mark.parametrize("change,check", [
    (lambda a: a["repositories"][REPOSITORY].update(policy=json.dumps({"Version": TW.V, "Statement": []})),
     "ECR: no repository policy on a sdv-twin/ repository"),
    (lambda a: a.update(registry_policy=json.dumps({"Version": TW.V, "Statement": []})), "ECR: no registry policy"),
    (lambda a: a.update(replication_rules=[{"destinations": [{"region": "eu-north-1", "registryId": "x"}]}]),
     "ECR: no replication rule and no pull-through cache rule"),
    (lambda a: a.update(cache_rules=[{"ecrRepositoryPrefix": "x", "upstreamRegistryUrl": "public.ecr.aws"}]),
     "ECR: no replication rule and no pull-through cache rule"),
    (lambda a: a.update(public_repositories=[{"repositoryName": "x"}]), "ECR Public holds no repository"),
    (lambda a: a["repositories"][REPOSITORY].update(mutability="MUTABLE"), "ECR: the repositories are exactly the expected ones, IMMUTABLE, AES256"),
    (lambda a: a["repositories"].update({"sdv-twin/another": dict(a["repositories"][REPOSITORY], images=[])}),
     "ECR: the repositories are exactly the expected ones, IMMUTABLE, AES256"),
    (lambda a: a["roles"][PULL_ROLE]["trust"]["Statement"][0]["Principal"].update(Service="iot.amazonaws.com"),
     "the pull role: its trust and its policy as rendered"),
    (lambda a: a["role_aliases"][ALIAS].update(credentialDurationSeconds=43200), "the role alias: the pull role, 3600 s"),
    (lambda a: a["policies"][PREFIX + "-ecr-pull"].update(document=json.dumps({"Version": TW.V, "Statement": [
        {"Sid": "x", "Effect": "Allow", "Action": "iot:*", "Resource": "*"}]})), "the pull policy as rendered"),
    (lambda a: [c["policies"].append(PREFIX + "-device") for c in a["certs"].values()],
     "the pull certificate carries the pull policy and no other"),
    # verify#10 and #23: the alias names the pull role; the repositories are AES256
    (lambda a: a["role_aliases"][ALIAS].update(roleArn="arn:aws:iam::%s:role/another-role-zz" % ACCOUNT),
     "the role alias: the pull role, 3600 s"),
    (lambda a: a["repositories"][REPOSITORY].update(encryption={"encryptionType": "KMS"}),
     "ECR: the repositories are exactly the expected ones, IMMUTABLE, AES256"),
])
def test_exit_checks_fails_on_each_ecr_and_pull_finding(p6: Rig, tmp_path: Path, change: Any, check: str) -> None:
    p6.edit(lambda a: a["policies"].setdefault(PREFIX + "-device", {"document": "{}", "tags": False}))
    p6.run("exit-checks", "--capture", tmp_path / "before", expect=1)
    before = {c["check"]: c["result"] for c in json.loads((tmp_path / "before" / "exit-checks.json").read_text(encoding="utf-8"))["checks"]}
    p6.edit(change)
    ran = p6.run("exit-checks", "--capture", tmp_path / "capture", expect=1)
    after = {c["check"]: c["result"] for c in json.loads((tmp_path / "capture" / "exit-checks.json").read_text(encoding="utf-8"))["checks"]}
    assert [k for k in after if after[k] != before[k]] == [check] and after[check] == "FAIL" and not clean6(ran.text)


def test_exit_checks_say_a_scan_type_out_of_its_form_by_that_and_never_by_its_text(p6: Rig, tmp_path: Path) -> None:
    """verify#24: the registry's scan type is printed (it is a closed word of ECR's) only when it is in that form; a reply that holds
    other text is said as `(not in its form)`, in the table and in the capture."""
    p6.edit(lambda a: a.update(scan_type="a free text 123"))
    ran = p6.run("exit-checks", "--capture", tmp_path / "capture", expect=1)
    text = (tmp_path / "capture" / "exit-checks.json").read_text(encoding="utf-8")
    results = {c["check"]: c for c in json.loads(text)["checks"]}
    row = results["ECR: no replication rule and no pull-through cache rule"]
    assert row["result"] == "pass" and row["shape"]["scan_type"] == "(not in its form)"
    assert "free text" not in text and "free text" not in ran.text


# --- push (item 7)

def stub_image(arch: str = "arm64", index: bool = False, os_name: str = "linux") -> Tuple[str, str, Dict[str, str]]:
    """An image as the docker stand-in's `save` gives it: (its store ID, its config digest, its blobs in base64 by digest). With
    `index`, the store ID names an OCI index over the one manifest, as a pulled multi-platform image's does; `os_name` is the
    operating system its config names."""
    config = json.dumps({"architecture": arch, "os": os_name, "config": {}, "rootfs": {"type": "layers", "diff_ids": []}}, sort_keys=True).encode()
    cfg = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json", "layers": [],
                           "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": cfg, "size": len(config)}},
                          sort_keys=True).encode()
    store = "sha256:" + hashlib.sha256(manifest).hexdigest()
    blobs = {cfg: config, store: manifest}
    if index:
        top = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
            {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": store, "size": len(manifest),
             "platform": {"architecture": arch, "os": "linux"}}]}, sort_keys=True).encode()
        store = "sha256:" + hashlib.sha256(top).hexdigest()
        blobs[store] = top
    return store, cfg, {d: base64.b64encode(b).decode("ascii") for d, b in blobs.items()}


def docker_prefix() -> str:
    return " ".join([Path(sys.executable).as_posix(), STUB.as_posix(), "--docker"])


def push_argv(store: str, cfg: str, version: str = "1.1.0") -> List[str]:
    return ["push", "--app", "hard-brake-hazard", "--version", version, "--arch", "arm64", "--store-id", store, "--config-digest", cfg,
            "--docker", docker_prefix()]


def docker_log(rig: Rig) -> List[List[str]]:
    return [e["argv"] for e in rig.log("docker.jsonl")]


def test_push_prints_its_render_and_sends_nothing_without_the_approval_or_before_the_repository_is_made(rig: Rig) -> None:
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    ran = rig.run(*push_argv(store, cfg), expect=1)
    assert "refused: push-needs-repository:" in ran.err and rig.log() == [] and docker_log(rig) == []
    rig.go("apply", "ecr-repository")
    since = len(rig.log())
    ran = rig.run(*push_argv(store, cfg), expect=3)
    assert rig.log()[since:] == [] and docker_log(rig) == []
    for line in ("  repository: sdv-twin/hard-brake-hazard", "  tag: 1.1.0-arm64", "  store ID: " + store, "  config digest: " + cfg,
                 "  aws ecr get-login-password",
                 "  aws ecr describe-images --repository-name sdv-twin/hard-brake-hazard --image-ids imageTag=1.1.0-arm64"):
        assert line in ran.out.split("\n"), line
    found = HASH.search(ran.out)
    assert found and "--approve push:" + found.group(1) in ran.out and REGISTRY not in ran.text and not clean6(ran.text)
    # another render's approval is refused before anything is sent
    assert "refused: approval-for-another-render:" in rig.run(*push_argv(store, cfg, "1.1.1") + ["--approve", "push:" + found.group(1)],
                                                             expect=1).err
    assert rig.log()[since:] == [] and docker_log(rig) == []


def printed_hash(ran: Ran) -> str:
    found = HASH.search(ran.out)
    assert found, ran.text
    return found.group(1)


def test_push_proves_the_config_digest_logs_in_by_stdin_pushes_reads_the_digest_back_and_records_it(rig: Rig, tmp_path: Path) -> None:
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")
    digest = printed_hash(rig.run(*push_argv(store, cfg), expect=3))
    since = len(rig.log())
    ran = rig.run(*push_argv(store, cfg) + ["--approve", "push:" + digest], expect=0)
    ref = REGISTRY + "/" + REPOSITORY + ":1.1.0-arm64"
    logged = docker_log(rig)
    assert [a[:1] if a[0] != "--config" else ["--config"] + a[2:3] for a in logged] == [["save"], ["image"], ["tag"], ["--config", "login"],
                                                                                        ["--config", "push"], ["rmi"]]
    assert logged[0] == ["save", store] and logged[1] == ["image", "inspect", store] and logged[2] == ["tag", store, ref]
    assert logged[5] == ["rmi", ref]
    assert logged[3][2:] == ["login", "--username", "AWS", "--password-stdin", REGISTRY] and logged[4][2:] == ["push", ref]
    config = Path(logged[3][1])
    assert logged[4][1] == logged[3][1] and not config.exists()        # the one temporary directory, removed after the push
    # the password went by the pipe: on no argv, of docker's or of the CLI's, and in no file that is left
    sent = [e["argv"] for e in rig.log()[since:]]
    assert ["ecr", "get-login-password"] in [a[:2] for a in sent] and not [a for a in sent + logged if ECR_PASSWORD in " ".join(a)]
    for root in (rig.base, tmp_path):
        for p in root.rglob("*"):
            if p.is_file():
                assert ECR_PASSWORD.encode() not in p.read_bytes() or p.name == "account.json", p
                assert base64.b64encode(("AWS:" + ECR_PASSWORD).encode()) not in p.read_bytes(), p
    assert rig.account()["repositories"][REPOSITORY]["images"] == [{"imageDigest": store, "imageTags": ["1.1.0-arm64"]}]
    assert rig.account()["docker_tags"] == {}
    pushes = json.loads((rig.state / "state.json").read_text(encoding="utf-8"))["pushes"]
    assert pushes == {REPOSITORY + ":1.1.0-arm64": {"tag": "1.1.0-arm64", "store_id": store, "manifest_digest": store, "config_digest": cfg,
                                                     "status": "pushed", "at": pushes[REPOSITORY + ":1.1.0-arm64"]["at"]}}
    assert not [x for x in rig.run("status", expect=0).out.split("\n") if x.startswith("push ")]         # status lists pushes not pushed
    assert "push: sdv-twin/hard-brake-hazard:1.1.0-arm64 pushed; the registry's manifest digest is the store ID; recorded." in ran.out
    assert REGISTRY not in ran.text and not clean6(ran.text)
    assert "refused: approval-spent:" in rig.run(*push_argv(store, cfg) + ["--approve", "push:" + digest], expect=1).err


@pytest.mark.parametrize("case,refusal", [("index", "store-id-names-an-index"), ("config", "config-digest-differs"),
                                          ("arch", "image-not-the-arch"), ("os", "image-not-the-arch"), ("blob", "save-stream-unreadable"),
                                          ("registry", "pushed-digest-differs"), ("two-details", "pushed-digest-differs")])
def test_push_refuses_an_index_another_config_digest_and_a_digest_the_registry_does_not_give_back(rig: Rig, case: str, refusal: str) -> None:
    """The refusals of the proof (an index, another config digest, another architecture or operating system, a blob that does not hash
    to the digest it is filed under: verify#13, #16) leave docker's log at `save` alone; the read-back's (another digest, or two
    images under the tag: verify#14) come after the push and stay on record as `unverified`."""
    store, cfg, blobs = stub_image(arch="amd64" if case == "arch" else "arm64", index=case == "index",
                                   os_name="windows" if case == "os" else "linux")
    _other_store, other_cfg, _blobs = stub_image(arch="riscv64")
    ref = REGISTRY + "/" + REPOSITORY + ":1.1.0-arm64"
    if case == "blob":                                              # the manifest and one more byte (a space is still JSON)
        blobs[store] = base64.b64encode(base64.b64decode(blobs[store]) + b" ").decode("ascii")
    plant: Dict[str, Any] = {"docker_images": {store: blobs}}
    if case == "registry":
        plant["push_digest"] = {ref: "sha256:" + "b" * 64}
    if case == "two-details":                                       # a read-back that lists two images under the tag, the first the store ID
        plant["reply_extra"] = {"ecr describe-images": {"imageDetails": [{"imageDigest": store, "imageTags": ["1.1.0-arm64"]},
                                                                         {"imageDigest": "sha256:" + "c" * 64, "imageTags": ["1.1.0-arm64"]}]}}
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(plant))
    rig.go("apply", "ecr-repository")
    argv = push_argv(store, other_cfg if case == "config" else cfg)
    digest = printed_hash(rig.run(*argv, expect=3))
    ran = rig.run(*argv + ["--approve", "push:" + digest], expect=1)
    assert "refused: %s:" % refusal in ran.err and not clean6(ran.text)
    state = json.loads((rig.state / "state.json").read_text(encoding="utf-8"))
    if case not in ("registry", "two-details"):                     # refused before anything is tagged, logged in or pushed
        assert "pushes" not in state
        assert [a[0] for a in docker_log(rig)] == ["save"] and rig.account()["repositories"][REPOSITORY]["images"] == []
    else:                                                           # the tag stands in the registry (immutable), and is said so
        assert "the tag 1.1.0-arm64 stands in the repository with another digest" in ran.err and "nothing is recorded" not in ran.err
        assert rig.account()["docker_tags"] == {}
        # the push was on record before it was sent, and stays there: unverified (fable#4)
        assert state["pushes"] == {REPOSITORY + ":1.1.0-arm64": {"tag": "1.1.0-arm64", "store_id": store, "config_digest": cfg,
                                                                  "status": "unverified", "at": state["pushes"][REPOSITORY + ":1.1.0-arm64"]["at"]}}


def test_a_push_is_on_record_before_it_is_sent_and_stays_there_however_it_ended(rig: Rig) -> None:
    """fable#4: a push is recorded (`sending`) before `docker push` is sent, as every create is: one whose docker push failed stays
    `sending` (a push that ended in an error may still have put the image), one whose read-back fails or does not give the store ID
    stays `unverified`, and `status` lists each push that is not `pushed`. A login that failed sent no push: nothing is recorded."""
    store, cfg, blobs = stub_image()
    key = REPOSITORY + ":1.1.0-arm64"
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")

    def pushes() -> Dict[str, Any]:
        return dict(json.loads((rig.state / "state.json").read_text(encoding="utf-8")).get("pushes", {}))

    def push() -> Ran:
        digest = printed_hash(rig.run(*push_argv(store, cfg), expect=3))
        return rig.run(*push_argv(store, cfg) + ["--approve", "push:" + digest], expect=1)

    def said() -> List[str]:
        return [x for x in rig.run("status", expect=0).out.split("\n") if x.startswith("push ")]

    rig.edit(lambda a: a.update(reply_error={"ecr get-login-password": "AccessDeniedException"}))
    assert "refused: login-failed:" in push().err and pushes() == {} and said() == []
    # the tag stands already (the repository is immutable): docker's push fails, and the push stays on record as sent
    rig.edit(lambda a: (a.pop("reply_error"), a["repositories"][REPOSITORY]["images"].append(
        {"imageDigest": "sha256:" + "c" * 64, "imageTags": ["1.1.0-arm64"]})))
    ran = push()
    assert "refused: docker-failed: docker push exited 1" in ran.err and "stays on record as sent" in ran.err
    assert {k: v for k, v in pushes()[key].items() if k != "at"} == {"tag": "1.1.0-arm64", "store_id": store, "config_digest": cfg,
                                                                     "status": "sending"}
    assert said() == ["push %s: sending: it was sent, and how it ended is not known; the repository's image listing says whether it "
                      "stands" % key]
    # the read-back is refused: unverified
    rig.edit(lambda a: (a["repositories"][REPOSITORY]["images"].clear(),
                        a.update(faults=[{"service": "ecr", "op": "describe-images", "code": "AccessDeniedException"}])))
    assert "refused: read-failed: ecr describe-images failed" in push().err and pushes()[key]["status"] == "unverified"
    assert said() == ["push %s: unverified: its read-back did not give the store ID; the repository's image listing says what stands "
                      "under the tag" % key]
    assert rig.account()["repositories"][REPOSITORY]["images"] == [{"imageDigest": store, "imageTags": ["1.1.0-arm64"]}]
    assert not clean6("".join(x.text for x in rig.said))


@pytest.mark.parametrize("names", [[], [REGISTRY + "/" + REPOSITORY + ":1.1.0-arm64"]], ids=["no-name", "the-registrys-reference-only"])
def test_push_refuses_an_image_with_no_other_name_before_anything_is_tagged(rig: Rig, names: List[str]) -> None:
    """fable#8: the local tag goes by `docker rmi <the registry's reference>`, which removes an image whose only name it was. An image
    with no other name (docker image inspect's RepoTags) is refused before anything is tagged, logged in or pushed: the rmi only ever
    untags."""
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}, docker_names={store: names}))
    rig.go("apply", "ecr-repository")
    digest = printed_hash(rig.run(*push_argv(store, cfg), expect=3))
    ran = rig.run(*push_argv(store, cfg) + ["--approve", "push:" + digest], expect=1)
    assert "refused: push-image-unnamed:" in ran.err and not clean6(ran.text)
    assert docker_log(rig) == [["save", store], ["image", "inspect", store]]
    a = rig.account()
    assert a.get("docker_tags", {}) == {} and a["repositories"][REPOSITORY]["images"] == []
    assert "pushes" not in json.loads((rig.state / "state.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case,refusal", [("index", "store-id-names-an-index"), ("config", "config-digest-differs"),
                                          ("arch", "image-not-the-arch"), ("unnamed", "push-image-unnamed")])
def test_a_push_refused_before_anything_is_tagged_does_not_spend_its_approval(rig: Rig, case: str, refusal: str) -> None:
    """fable#5: an approval is spent by the first thing done under it, as `apply` spends after its reads. A push that the proof of the
    save stream or the image's names refused tagged, logged in and sent nothing: the same printing still stands, and the retry meets
    the same refusal (not `approval-spent`). One whose cause is taken away goes through under it, once."""
    store, cfg, blobs = stub_image(arch="amd64" if case == "arch" else "arm64", index=case == "index")
    _other_store, other_cfg, _blobs = stub_image(arch="riscv64")
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}, docker_names={store: []} if case == "unnamed" else {}))
    rig.go("apply", "ecr-repository")
    argv = push_argv(store, other_cfg if case == "config" else cfg)
    approved = argv + ["--approve", "push:" + printed_hash(rig.run(*argv, expect=3))]
    for _ in range(2):
        ran = rig.run(*approved, expect=1)
        assert "refused: %s:" % refusal in ran.err and "approval-spent" not in ran.err, ran.err
    assert "pushes" not in json.loads((rig.state / "state.json").read_text(encoding="utf-8"))
    assert [a[0] for a in docker_log(rig) if a[0] in ("tag", "rmi", "push") or "login" in a] == []
    if case == "unnamed":
        rig.edit(lambda a: a["docker_names"].update({store: ["sdv-local/an-image:built-here"]}))
        rig.run(*approved, expect=0)
        assert rig.account()["repositories"][REPOSITORY]["images"] == [{"imageDigest": store, "imageTags": ["1.1.0-arm64"]}]
        assert "refused: approval-spent:" in rig.run(*approved, expect=1).err


def test_push_refuses_a_temporary_docker_directory_inside_a_work_tree_and_leaves_nothing_tagged(rig: Rig, tmp_path: Path,
                                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """verify#15: the directory docker's login would be written to is made under the temporary directory (TMPDIR), and one that lies
    inside a work tree is refused after the tag and before the login: the tag goes again, the directory is removed, nothing is sent."""
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")
    digest = printed_hash(rig.run(*push_argv(store, cfg), expect=3))
    tree = tmp_path / "a-work-tree"
    (tree / ".git").mkdir(parents=True)
    (tree / "tmp").mkdir()
    with monkeypatch.context() as m:
        m.setattr(tempfile, "tempdir", str(tree / "tmp"))
        ran = rig.run(*push_argv(store, cfg) + ["--approve", "push:" + digest], expect=1)
    assert "refused: inside-a-work-tree:" in ran.err and "temporary docker directory" in ran.err
    logged = docker_log(rig)
    assert [a[0] for a in logged] == ["save", "image", "tag", "rmi"] and not [a for a in logged if "login" in a or "push" in a]
    assert list((tree / "tmp").iterdir()) == [] and rig.account()["docker_tags"] == {}
    assert rig.account()["repositories"][REPOSITORY]["images"] == [] and "pushes" not in json.loads(
        (rig.state / "state.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("change,refusal", [(dict(version="1.1"), "push-version-invalid"),
                                            (dict(version="1.1.0.a"), "push-version-invalid"),
                                            (dict(store="sha256:" + "A" * 64), "push-digest-invalid"),
                                            (dict(cfg="sha256:" + "a" * 63), "push-digest-invalid"),
                                            (dict(docker=""), "push-docker-invalid")])
def test_push_refuses_an_argument_out_of_its_form_before_anything_is_sent(rig: Rig, change: Dict[str, str], refusal: str) -> None:
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")
    argv = push_argv(change.get("store", store), change.get("cfg", cfg), change.get("version", "1.1.0"))
    if "docker" in change:
        argv[argv.index("--docker") + 1] = change["docker"]
    since = len(rig.log())
    ran = rig.run(*argv, expect=1)
    assert "refused: %s:" % refusal in ran.err and rig.log()[since:] == [] and docker_log(rig) == [] and not clean6(ran.text)


# c01: push holds the repository's step to `created` (made and proven), not to any record of it
@pytest.mark.parametrize("status", ["creating", "unverified", "deleting"])
def test_push_is_refused_while_the_repository_is_recorded_but_not_made_and_proven(rig: Rig, status: str) -> None:
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")
    set_status(rig, "ecr-repository", status)
    since = len(rig.log())
    ran = rig.run(*push_argv(store, cfg), expect=1)
    assert "refused: push-needs-repository:" in ran.err and docker_log(rig) == [] and rig.log()[since:] == []


# c03: an approved push reads the caller first, and runs no docker under another identity
def test_an_approved_push_under_another_identity_is_refused_before_docker_runs(rig: Rig) -> None:
    store, cfg, blobs = stub_image()
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")
    argv = push_argv(store, cfg)
    digest = printed_hash(rig.run(*argv, expect=3))
    rig.edit(lambda a: a.update(identity={"UserId": "x", "Arn": "arn:aws:iam::%s:user/example-user" % ACCOUNT}))
    ran = rig.run(*argv + ["--approve", "push:" + digest], expect=1)
    assert "refused: identity-not-the-operator-role:" in ran.err and docker_log(rig) == []
    assert rig.account()["repositories"][REPOSITORY]["images"] == []


# c16: a store ID whose blob is a manifest of another media type (an artifact's) is refused before anything is tagged
def test_push_refuses_a_manifest_of_another_media_type(rig: Rig) -> None:
    config = json.dumps({"architecture": "arm64", "os": "linux", "config": {}, "rootfs": {"type": "layers", "diff_ids": []}}).encode()
    cfg = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.artifact.manifest.v1+json", "layers": [],
                           "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": cfg, "size": len(config)}}).encode()
    store = "sha256:" + hashlib.sha256(manifest).hexdigest()
    blobs = {d: base64.b64encode(b).decode("ascii") for d, b in ((cfg, config), (store, manifest))}
    with_keys(rig, pull=False)
    rig.edit(lambda a: a.update(docker_images={store: blobs}))
    rig.go("apply", "ecr-repository")
    argv = push_argv(store, cfg)
    ran = rig.run(*argv + ["--approve", "push:" + printed_hash(rig.run(*argv, expect=3))], expect=1)
    assert "refused: save-stream-unreadable:" in ran.err and [a[0] for a in docker_log(rig)] == ["save"]


def test_docker_path_gives_wsls_docker_a_drive_path_as_mnt(tmp_path: Path) -> None:
    here = os.path.abspath(str(tmp_path))
    assert TW.docker_path(["docker"], tmp_path) == here
    assert TW.docker_path(["wsl.exe", "-d", "Ubuntu-24.04", "--", "docker"], tmp_path) == (
        here if os.name != "nt" else "/mnt/" + here[0].lower() + here[2:].replace(chr(92), "/"))


@pytest.mark.skipif(os.name != "nt", reason="a drive path is a Windows path")
def test_docker_path_reads_a_drive_path_for_a_prefix_whose_first_word_is_wsl_and_for_no_other() -> None:
    assert TW.docker_path(["wsl.exe", "--", "docker"], Path("C:/Users/x/Temp/d")) == "/mnt/c/Users/x/Temp/d"
    assert TW.docker_path(["C:/Windows/System32/wsl.exe", "--", "docker"], Path("D:/t")) == "/mnt/d/t"
    assert TW.docker_path(["docker"], Path("C:/Users/x")) == os.path.abspath("C:/Users/x")


# --- ecr-config (item 8)

def test_ecr_config_writes_the_pulling_hosts_file_mode_0600_and_prints_nothing_of_it(p6: Rig, tmp_path: Path) -> None:
    out = tmp_path / "board" / "ecr.json"
    out.parent.mkdir()
    since = len(p6.log())
    ran = p6.run("ecr-config", "--out", out, expect=0)
    assert json.loads(out.read_text(encoding="ascii")) == {"credential_endpoint": CRED_ENDPOINT, "role_alias": ALIAS, "region": REGION,
                                                          "registry": REGISTRY}
    if os.name != "nt":
        assert (out.stat().st_mode & 0o777) == 0o600
    sent = [e["argv"] for e in p6.log()[since:]]
    assert [a[:2] for a in sent] == [["sts", "get-caller-identity"], ["iot", "describe-endpoint"]]
    assert sent[1][2:4] == ["--endpoint-type", "iot:CredentialProvider"]
    assert CRED_ENDPOINT not in ran.text and REGISTRY not in ran.text and ACCOUNT not in ran.text and not clean6(ran.text)
    assert "its content is not printed" in ran.out
    assert "refused: inside-a-work-tree:" in p6.run("ecr-config", "--out", REPO / "ecr.json", expect=1).err
    assert not (REPO / "ecr.json").exists()
    # verify#17: a reply that names the DATA endpoint (a host not of the credential provider's form) is no credential endpoint
    p6.edit(lambda a: a.update(credential_endpoint=ENDPOINT))
    again = tmp_path / "board" / "data-endpoint.json"
    ran = p6.run("ecr-config", "--out", again, expect=1)
    assert "refused: endpoint-unreadable:" in ran.err and not again.exists() and not list(again.parent.glob("*.tmp"))
    assert ENDPOINT not in ran.text and ENDPOINT_PREFIX not in ran.text
    p6.edit(lambda a: a.update(credential_endpoint=CRED_ENDPOINT))
    # before the role alias is made there is nothing to pull with
    for step in ("pull-attachment", "pull-certificate", "pull-policy", "role-alias"):
        p6.go("teardown", step)
    assert "refused: ecr-config-needs-role-alias:" in p6.run("ecr-config", "--out", tmp_path / "again.json", expect=1).err


# c02: ecr-config holds the role alias's step to `created`
@pytest.mark.parametrize("status", ["creating", "unverified", "deleting"])
def test_ecr_config_is_refused_while_the_role_alias_is_recorded_but_not_made_and_proven(p6: Rig, tmp_path: Path, status: str) -> None:
    set_status(p6, "role-alias", status)
    out = tmp_path / "board" / "ecr.json"
    since = len(p6.log())
    ran = p6.run("ecr-config", "--out", out, expect=1)
    assert "refused: ecr-config-needs-role-alias:" in ran.err and not out.exists() and p6.log()[since:] == []


# --- every call, planned and let through

def test_every_call_of_the_new_steps_and_commands_is_one_plan_lists_and_the_operator_policy_lets_through(p6: Rig, tmp_path: Path) -> None:
    store, cfg, blobs = stub_image()
    p6.edit(lambda a: a.update(docker_images={store: blobs}))
    digest = printed_hash(p6.run(*push_argv(store, cfg), expect=3))
    p6.run(*push_argv(store, cfg) + ["--approve", "push:" + digest], expect=0)
    p6.run("ecr-config", "--out", tmp_path / "ecr.json", expect=0)
    p6.run("exit-checks", "--capture", tmp_path / "capture", expect=1)
    p6.run("status", expect=0)
    p6.go("apply", "pull-active")
    p6.go("apply", "pull-inactive")
    p6.edit(lambda a: a["repositories"][REPOSITORY]["images"].clear())
    for step in ("pull-attachment", "pull-certificate", "pull-policy", "role-alias", "ecr-lifecycle", "ecr-repository"):
        p6.go("teardown", step)
    p6.run("verify-gone", expect=0)
    p6.run("plan", "--no-cli", expect=0)
    planned = {sig(c) for c in every_call(p6)}
    sent = {sig(e["argv"]) for e in p6.log()}
    assert sent - planned == set()
    new = {s for s in sent if s[0] in ("ecr", "ecr-public") or s[1].endswith("role-alias") or s[1] == "list-role-aliases"}
    assert len(new) >= 17
    doc = p6.doc("operator-role", "operator-role-policy")
    assert TW.operator_gaps(doc, calls_of(p6)) == []
    assert TW.iam_actions(TW.R("ecr", "get-login-password")) == ("ecr:GetAuthorizationToken",)
    assert TW.iam_actions(TW.W("iot", "create-role-alias", "--role-alias", ALIAS, "--role-arn", "r")) == ("iot:CreateRoleAlias", "iam:PassRole")
    assert TW.iam_actions(TW.W("ecr", "create-repository", "--repository-name", REPOSITORY, "--tags", "t")) == (
        "ecr:CreateRepository", "ecr:TagResource")
    assert not clean6("".join(x.text for x in p6.said))


def test_the_names_keys_hold_phase6s_keys_and_the_pull_role_and_the_pull_thing_are_bound_late() -> None:
    for key, pattern in (("TWIN_ECR", r"[01]"), ("TWIN_PULL_ROLE", r"[A-Za-z0-9_.-]{8,64}"), ("TWIN_PULL_THING", r"[A-Za-z0-9_-]{8,128}")):
        assert TW.NAME_KEYS[key] == (False, pattern), key
    assert {"TWIN_ORIN_CSR", "TWIN_ORIN_CERTIFICATE_OUT"} <= set(TW.PATH_KEYS)
    # each late key with the steps whose record binds it and holds it (fable#3: the pull thing by its own step)
    assert TW.LATE_BOUND == {"TWIN_PULL_ROLE": TW.PULL_STEPS, "TWIN_PULL_THING": ("pull-thing",)}
    assert not set(TW.LATE_BOUND) & set(TW.BOUND_NAMES + TW.STOP_NAMES)


def test_the_docstring_the_readme_and_the_names_template_say_what_phase6_wp4_added() -> None:
    """The sentences Phase 6 WP4's additions are written down in stand in the driver's docstring, in the README and in the names
    template (white space and code marks aside): each said something else before, or nothing."""
    def fold(text: str) -> str:
        return " ".join(text.replace("`", "").split())

    doc = fold(str(TW.__doc__))
    readme = fold((REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8"))
    example = fold((REPO / "sdv" / "cloud" / ".env.example").read_text(encoding="utf-8").replace("\n# ", "\n"))
    for said in ("NOTHING OF IT IS THERE UNTIL ITS KEY IS: with TWIN_ECR unset or 0 and no TWIN_PULL_ROLE, every render, hash, status and "
                 "exit-checks is the one the twin stands on",
                 "The pull role is BOUND ONCE RECORDED (LATE_BOUND), not with a state's first write",
                 "the password on no argv, in no reply file and in no file but that directory's, which is removed in a finally with the tag",
                 "Refused while the step role-alias is not recorded as made and proven.",
                 # the review's fixes (p6-wp4-fix): the late bindings' reach (verify#3, fable#3), TWIN_ECR (fable#2), push (fable#4, #8)
                 "held while any pull step is on record, the owner's read of the role and a record taken back as stale among them: twinctl "
                 "never deletes the owner's pull role, so once apply pull-role has read it the binding stays for good, as "
                 "TWIN_OPERATOR_ROLE's does",
                 "TWIN_PULL_THING is BOUND ONCE pull-thing IS RECORDED, and held while that step is on record",
                 "TWIN_ECR=0 takes effect only once no ECR step stands",
                 "the push recorded in the state before it is sent (status sending, in pushes: the tag, the store ID, the config digest)",
                 "an image with no other name than the registry's reference is refused before anything is tagged"):
        assert said in doc, said
    for said in ("Nothing of it is there until its key is given",
                 "Its teardown is refused while the repository holds an image (the delete takes no --force)",
                 "It prints one line, the token's expiry, and no host, key id, token or path.",
                 "needed no new shape: the credential provider's host (<prefix>.credentials.iot.<region>.amazonaws.com) is a form of the "
                 "endpoint's shape and goes whole",
                 "TWIN_ECR=0 takes effect only once no ECR step stands",
                 "held while any pull step is on record: once apply pull-role has read the role, for good (twinctl never deletes it)",
                 "Its tag is made and not read back by the step, as no step of the twin reads its tag back",
                 "whether ECR answers that listing to this policy is first seen at B2, under the remade policy",
                 "The push is on record before it is sent (sending), and stays there however it ended",
                 "An image with no other name than the registry's reference is refused before anything is tagged (push-image-unnamed), so "
                 "that the rmi only ever untags",
                 # the fixes of p6-wp4-fix-exact: logout (verify#2), the approval of a push refused before anything is tagged (fable#5)
                 "removes the file whatever docker answered: a logout that docker refused is said (exit 1), and the file with the token is "
                 "gone all the same",
                 "A push refused by the proof of the image, or for its want of a name, tagged nothing and spends no approval"):
        assert said in readme, said
    for said in ("Bound once a pull step is recorded, and held while any pull step is on record, the owner's read of the role and an "
                 "action's run included: every command but trip is then refused under another value, or none.",
                 "twinctl never deletes the pull role, so once apply pull-role has read it the binding stays for good, as "
                 "TWIN_OPERATOR_ROLE's does; once nothing stands, literals and then baseline --again take new names.",
                 "TWIN_ECR=0 takes effect only once no ECR step stands",
                 "Bound once pull-thing is recorded, and held while that step is on record.",
                 "Only if B3 finds that a certificate attached to no thing gets no credentials (wp0-facts C9)"):
        assert said in example, said
    # what the texts said before the fix, and no longer may (verify#3: wider than the code)
    assert "while one stands, every command but trip is refused" not in example


# ================================================================================================= the real CLI, offline (opt-in)

@pytest.mark.skipif(os.environ.get("SDV_TWINCTL_REAL_CLI") != "1", reason="opt-in: SDV_TWINCTL_REAL_CLI=1 (the real CLI, offline; no AWS call)")
@pytest.mark.parametrize("prefix", [PREFIX, SHORT_PREFIX], ids=["the-fixtures-prefix", "a-prefix-of-eight"])
def test_plan_over_the_whole_table_validates_offline_with_the_real_cli(tmp_path: Path, prefix: str) -> None:
    """The real `aws`, asked only to read arguments (--generate-cli-skeleton output) under two empty credential files,
    no AWS_ variable of the caller, instance metadata off, the proxies and the endpoint pointed at a closed local
    port, and only after a control call under those settings failed. It makes no AWS call and reads no credential.
    Off by default; WSL has no CLI, so it runs under Windows Python."""
    exe = shutil.which("aws")
    assert exe, "the AWS CLI is not on PATH"
    rig = Rig(tmp_path / "twin")
    rig.extra = {"TWIN_PREFIX": prefix, "TWIN_THING": prefix + "-thing"}
    rig.run("literals", expect=0)
    rig.extra["TWIN_AWS"] = exe
    ran = rig.run("plan")
    assert ran.rc == 0, ran.text
    assert "0 refused by the CLI" in ran.out and "7 take an output file and know no skeleton" in ran.out
    assert rig.log() == [] and rig.log("skeleton.jsonl") == [] and rig.log("refused.jsonl") == []      # the stub saw nothing: the real CLI ran
