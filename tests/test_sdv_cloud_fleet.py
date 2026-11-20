"""Video 3's fleet, the cloud package (fleet P2): twinctl's steps for cars B and C, `update-config function`, and the breaker's set.

NO AWS CALL IS MADE HERE, AND NO CREDENTIAL IS READ: this file drives tests/test_sdv_cloud.py's rig and its stand-in for the
CLI (tests/twin_stub_aws.py), with tests/test_sdv_cloud_update_code.py's two update calls and one more, written into each test's
own directory: `lambda update-function-configuration`, which sets the function's time-out and environment and nothing else, as
the stand-in's other replies are written from memory of the documentation. Every invoke runs sdv/cloud/breaker/breaker.py's
handler out of the function's zip, so every dry trip and alarm test here is the real code over the set the function names.

THE NUMBERING: car A is the twin's own thing, certificate and policy; car B is 2 and car C is 3 (fleet P1's instances). The
fixture values are put together when the tests run: things and policies under the rig's prefix, documentation values only.

What is held here
  the keys        each fleet key refused by the key and never by the value: `_3` without `_2`, a thing without the prefix, a
                  thing equal to the twin's, the pull thing's, the other car's or the rehearsal's; each car's thing bound once
                  the first of its steps is recorded, fleet-policy-k alone among them, and the stop not held to it.
  the steps       the seven steps of each car after every existing step, car 2's before car 3's, each rendered, read, judged
                  and torn down; the shadows' teardown based on the car's thing and their words the car's, the twin's unchanged.
  the set         the cars whose attachments stand; the renders that take it (the environment, the time-out, the breaker role,
                  reattach-policy); a car joining or leaving takes back what stood on the set; only the highest car leaves; a set
                  change refused while a fleet certificate is ACTIVE, while a code update is due (both directions; the change
                  back let through) and while the function's update is unsettled.
  update-config   its render and approval, every refusal, the record of hashes only, the settle of each settler on each kind
                  of record and the config rule's cases, run_again with its take-back, and the operator grant only with its key.
  fleet-active-k  each check of its pre and its needs, each refused by its name with nothing sent; fleet-inactive-k never
                  refused by an unsettled update, an ACTIVE certificate, a code update due or a stale record.
  status          the lists exactly the set's and paired by position, the time-out against the count, a set car's ACTIVE
                  certificate no failure only while the breaker's proof stands; with no fleet key, today's lines.
  the rest        restore with no fleet ACTIVE call, restore and go-live refused while the function names what is gone,
                  fleet-still-covered and its waiver on a twin read as cut, the stop's file for one, two and three cars, the
                  literals, exit-checks' rows per car, plan with the fleet, and one whole life in P4's order.

Does not demonstrate: anything in the account (IAM's reading of either role, IoT's three exclusive attachments, a list in the
breaker role), what the real service answers to `update-function-configuration` or its wait, any timing or cost, or the
fleet's traffic. The time-outs and counts are design values.
"""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

import test_sdv_cloud as tc
import test_sdv_cloud_update_code as uc

TW = tc.TW
Rig = tc.Rig

THINGS = {2: tc.j(tc.PREFIX, "-car-b"), 3: tc.j(tc.PREFIX, "-car-c")}
POLICY = tc.PREFIX + "-device"
POLICIES = {2: tc.PREFIX + "-device-2", 3: tc.PREFIX + "-device-3"}
FUNCTION = tc.PREFIX + "-breaker"
RULE = tc.PREFIX + "_telemetry"
CONFIG_ACTION = "lambda:UpdateFunctionConfiguration"
TESTS = ["alarm-test-" + k for k in tc.BREAKER]
RERUN = ["function-status", "dry-trip"] + TESTS + ["reattach-policy"]
SET_RECORDS = ["breaker-role"] + RERUN                                          # what stands on the set, the fleet-active-j's besides
STEPS = ("fleet-thing-%d", "fleet-shadows-%d", "fleet-certificate-%d", "fleet-policy-%d", "fleet-attachments-%d", "fleet-active-%d",
         "fleet-inactive-%d")

# The stand-in with update-code's two calls (tests/test_sdv_cloud_update_code.py) and the configuration's update: it sets the
# function's Timeout and Environment as given and nothing else; `config_ignored` answers and changes nothing; `config_status`
# leaves that LastUpdateStatus.
CONFIG_OPS = '''
def update_config(a, o, out):
    f = stub.fn(a, o)
    if not a.get("config_ignored"):
        if "--timeout" in o:
            f["config"]["Timeout"] = int(stub.one(o, "--timeout"))
        if "--environment" in o:
            f["config"]["Environment"] = stub.js(o, "--environment")
    if a.get("config_status"):
        f["config"]["LastUpdateStatus"] = a["config_status"]
    return f["config"]


stub.OPS[("lambda", "update-function-configuration")] = (update_config, True)
'''
STAND_IN = uc.STAND_IN.replace("argv = sys.argv[1:]\n", CONFIG_OPS + "argv = sys.argv[1:]\n")
assert STAND_IN != uc.STAND_IN


def arn(cert: str) -> str:
    return "arn:aws:iot:%s:%s:cert/%s" % (tc.REGION, tc.ACCOUNT, cert)


def client_arn(thing: str) -> str:
    return "arn:aws:iot:%s:%s:client/%s" % (tc.REGION, tc.ACCOUNT, thing)


def policy_arn(policy: str) -> str:
    return "arn:aws:iot:%s:%s:policy/%s" % (tc.REGION, tc.ACCOUNT, policy)


def with_fleet(rig: Rig, cars: Any = (2, 3)) -> Rig:
    """The rig driven through STAND_IN, with the fleet's keys for `cars` in its environment and their placeholder requests."""
    stand_in = rig.base / "stand_in_fleet.py"
    stand_in.write_text(STAND_IN.replace("@STUB@", repr(str(tc.STUB))), encoding="utf-8")
    rig.extra["TWIN_AWS"] = str(stand_in)
    for k in cars:
        csr = rig.inputs / ("device-%d.csr" % k)
        csr.write_bytes(b"car %d's placeholder, not a signing request\n" % k)
        rig.extra.update({"TWIN_FLEET_THING_%d" % k: THINGS[k], "TWIN_FLEET_CSR_%d" % k: str(csr),
                          "TWIN_FLEET_CERTIFICATE_OUT_%d" % k: str(rig.inputs / ("device-%d.crt" % k))})
    rig.run("literals", expect=0)
    return rig


def join(rig: Rig, k: int) -> None:
    for step in ("fleet-thing-%d", "fleet-certificate-%d", "fleet-policy-%d", "fleet-attachments-%d"):
        rig.go("apply", step % k)


def remake_role(rig: Rig) -> None:
    """The owner remakes the breaker role by hand from its render, then `apply breaker-role` reads it."""
    rig.run("apply", "breaker-role")
    rig.owner_makes("breaker-role")
    rig.run("apply", "breaker-role", expect=0)


def shown_config(rig: Rig) -> str:
    before = len(rig.log())
    ran = rig.run("update-config", "function", expect=3)
    assert rig.log()[before:] == [], "printing the render sent a call"
    found = tc.HASH.search(ran.out)
    assert found, ran.text
    return found.group(1)


def configure(rig: Rig, expect: int = 0) -> tc.Ran:
    return rig.run("update-config", "function", "--approve", "function-config:" + shown_config(rig), expect=expect)


def rerun(rig: Rig, steps: Any = None) -> None:
    for step in steps or RERUN:
        rig.go("apply", step)


def cert_of(rig: Rig, k: int) -> str:
    return str(tc.facts(rig)["fleet_certificate_id_%d" % k])


def status_of(rig: Rig, step: str) -> str:
    return str(tc.state_of(rig)["steps"].get(step, {}).get("status", "absent"))


def env_of(rig: Rig) -> Dict[str, str]:
    return dict(rig.account()["functions"][FUNCTION]["config"]["Environment"]["Variables"])


def fn_config(rig: Rig) -> Dict[str, Any]:
    return dict(rig.account()["functions"][FUNCTION]["config"])


def function_entry(rig: Rig) -> Dict[str, Any]:
    return dict(tc.state_of(rig)["steps"]["function"])


def set_cert(rig: Rig, cert: str, status: str) -> None:
    rig.edit(lambda a: a["certs"][cert].update(status=status))


def edit_state(rig: Rig, change: Any) -> None:
    uc._edit_state(rig, change)


def mark(rig: Rig, step: str, status: str) -> None:
    edit_state(rig, lambda s: s["steps"].setdefault(step, {}).update(status=status))


def fails(ran: tc.Ran) -> List[str]:
    return [line for line in ran.err.split("\n") if line.startswith("FAIL: ")]


@pytest.fixture(scope="module")
def started(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """Literals and a baseline, nothing made, without the notice."""
    return Rig(tmp_path_factory.mktemp("fleet-started") / "twin", notice=False).start()


@pytest.fixture
def rig(tmp_path: Path, started: Rig) -> Rig:
    return started.copy(tmp_path / "rig", logs=False)


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """The twin's whole table applied from the source's build, without the notice: car A alone, live."""
    return Rig(tmp_path_factory.mktemp("fleet-made") / "twin", notice=False).build()


@pytest.fixture(scope="module")
def ready(tmp_path_factory: pytest.TempPathFactory, made: Rig) -> Rig:
    """Cars B and C joined, the breaker role remade, the function's configuration updated, the breaker run again on the set:
    P4's steps 3-6. No fleet certificate is ACTIVE."""
    rig = with_fleet(made.copy(tmp_path_factory.mktemp("fleet-ready") / "twin"))
    join(rig, 2)
    join(rig, 3)
    remake_role(rig)
    configure(rig)
    rerun(rig)
    return rig


@pytest.fixture(scope="module")
def active(tmp_path_factory: pytest.TempPathFactory, ready: Rig) -> Rig:
    """`ready` with both fleet certificates made ACTIVE through fleet-active-k: P4's step 8."""
    rig = with_fleet(ready.copy(tmp_path_factory.mktemp("fleet-active") / "twin"))
    rig.go("apply", "fleet-active-2")
    rig.go("apply", "fleet-active-3")
    return rig


@pytest.fixture(scope="module")
def joined_once(tmp_path_factory: pytest.TempPathFactory, made: Rig) -> Rig:
    """Car B joined, the breaker role remade, function-status and the dry trip run again: update-config's starting point."""
    rig = with_fleet(made.copy(tmp_path_factory.mktemp("fleet-joined") / "twin"))
    join(rig, 2)
    remake_role(rig)
    rerun(rig, ["function-status", "dry-trip"])
    return rig


@pytest.fixture
def twin(tmp_path: Path, made: Rig) -> Rig:
    return with_fleet(made.copy(tmp_path / "twin"))


@pytest.fixture
def joined(tmp_path: Path, joined_once: Rig) -> Rig:
    return with_fleet(joined_once.copy(tmp_path / "joined"))


@pytest.fixture
def both(tmp_path: Path, ready: Rig) -> Rig:
    return with_fleet(ready.copy(tmp_path / "both"))


@pytest.fixture
def live(tmp_path: Path, active: Rig) -> Rig:
    return with_fleet(active.copy(tmp_path / "live"))


# ================================================================================================= the keys

def test_the_six_keys_are_names_of_the_names_file_and_the_example_gives_each_commented() -> None:
    for k in TW.FLEET_CARS:
        assert TW.NAME_KEYS["TWIN_FLEET_THING_%d" % k] == (False, r"[A-Za-z0-9_-]{8,128}")
        assert "TWIN_FLEET_CSR_%d" % k in TW.PATH_KEYS and "TWIN_FLEET_CERTIFICATE_OUT_%d" % k in TW.PATH_KEYS
    assert TW.FLEET_CARS == (2, 3)
    text = (tc.REPO / "sdv" / "cloud" / ".env.example").read_text(encoding="utf-8")
    for k in TW.FLEET_CARS:
        assert re.search(r"^# TWIN_FLEET_THING_%d=exampletwin-[a-z0-9-]+$" % k, text, re.M), k
        assert re.search(r"^# TWIN_FLEET_CSR_%d=/path/\S+device-%d\S*\.csr$" % (k, k), text, re.M), k
        assert re.search(r"^# TWIN_FLEET_CERTIFICATE_OUT_%d=/path/\S+device-%d\S*\.crt$" % (k, k), text, re.M), k
    # BOUND_NAMES and STOP_NAMES are unchanged; each car's thing is bound once a step of its car is recorded
    assert TW.BOUND_NAMES == ("TWIN_ACCOUNT", "TWIN_REGION", "TWIN_PREFIX", "TWIN_THING", "TWIN_BUCKET_SUFFIX", "TWIN_OPERATOR_ROLE",
                              "TWIN_PROFILE", "TWIN_NOTICE")
    assert TW.STOP_NAMES == ("TWIN_ACCOUNT", "TWIN_REGION", "TWIN_PREFIX", "TWIN_THING")
    for k in TW.FLEET_CARS:
        assert TW.FLEET_BOUND["TWIN_FLEET_THING_%d" % k] == tuple(s % k for s in STEPS) == TW.ALL_LATE_BOUND["TWIN_FLEET_THING_%d" % k]
    assert TW.ALL_LATE_BOUND == dict(TW.LATE_BOUND, **TW.FLEET_BOUND) and not set(TW.FLEET_BOUND) & set(TW.BOUND_NAMES + TW.STOP_NAMES)


KEY_FAULTS: List[Any] = [
    ("three-without-two", {"TWIN_FLEET_THING_3": THINGS[3]}, "TWIN_FLEET_THING_3"),
    ("no-prefix", {"TWIN_FLEET_THING_2": tc.j("another", "-car-zz-b")}, "TWIN_FLEET_THING_2"),
    ("the-twins-thing", {"TWIN_FLEET_THING_2": tc.THING}, "TWIN_FLEET_THING_2"),
    ("the-other-car", {"TWIN_FLEET_THING_2": THINGS[2], "TWIN_FLEET_THING_3": THINGS[2]}, "TWIN_FLEET_THING_3"),
    ("the-pull-thing", {"TWIN_FLEET_THING_2": tc.PULL_THING, "TWIN_PULL_THING": tc.PULL_THING}, "TWIN_FLEET_THING_2"),
    ("the-rehearsals-thing", {"TWIN_FLEET_THING_2": tc.j(tc.PREFIX, "rh-thing")}, "TWIN_FLEET_THING_2"),
    ("car-3-the-twins-thing", {"TWIN_FLEET_THING_2": THINGS[2], "TWIN_FLEET_THING_3": tc.THING}, "TWIN_FLEET_THING_3"),
    ("car-3-the-rehearsals-thing", {"TWIN_FLEET_THING_2": THINGS[2], "TWIN_FLEET_THING_3": tc.j(tc.PREFIX, "rh-thing")}, "TWIN_FLEET_THING_3"),
    ("seven-characters", {"TWIN_FLEET_THING_2": "car-zz2"}, "TWIN_FLEET_THING_2"),
]


@pytest.mark.parametrize("keys, key", [c[1:] for c in KEY_FAULTS], ids=[c[0] for c in KEY_FAULTS])
def test_a_fleet_key_is_refused_by_the_key_and_never_by_the_value(rig: Rig, keys: Dict[str, str], key: str) -> None:
    rig.extra.update(keys)
    ran = rig.run("plan", "--no-cli", expect=1)
    assert "refused: names-invalid:" in ran.err and key in ran.err
    for value in keys.values():
        assert value not in ran.text
    assert rig.log() == []


def test_with_the_keys_in_order_the_plan_takes_them(rig: Rig) -> None:
    with_fleet(rig)
    rig.run("plan", "--no-cli", expect=0)
    ids = [s["id"] for s in rig.plan()]
    assert [i for i in ids if i.startswith("fleet-")] == [s % 2 for s in STEPS] + [s % 3 for s in STEPS]


def test_a_cars_thing_is_bound_once_the_first_of_its_steps_is_recorded_and_held_while_any_is(twin: Rig) -> None:
    twin.extra["TWIN_FLEET_THING_2"] = tc.j(tc.PREFIX, "-car-other")
    twin.run("literals", expect=0)
    twin.run("plan", "--no-cli", expect=0)                          # no step of car 2 on record: another name is taken
    with_fleet(twin)
    twin.go("apply", "fleet-policy-2")                              # its render is made of the thing's name: bound from here
    twin.extra["TWIN_FLEET_THING_2"] = tc.j(tc.PREFIX, "-car-other")
    ran = twin.run("plan", "--no-cli", expect=1)
    assert "refused: names-changed:" in ran.err and "TWIN_FLEET_THING_2" in ran.err and "car-other" not in ran.text
    since = len(twin.log())
    ran = twin.run("trip")                                          # the stop is not held to a fleet key
    assert [c[:2] for c in twin.writes(since)][:1] == [["lambda", "invoke"]] and "names-changed" not in ran.text
    # car 3's key is not bound by car 2's step
    with_fleet(twin)
    twin.extra["TWIN_FLEET_THING_3"] = tc.j(tc.PREFIX, "-car-third")
    twin.run("literals", expect=0)
    twin.run("plan", "--no-cli", expect=0)


# ================================================================================================= the steps

def test_the_fleets_steps_come_after_every_step_car_2s_before_car_3s_and_a_teardown_takes_car_3_first(twin: Rig) -> None:
    before = [s.id for s in TW.Twin(twin.state, None, False).steps]
    twin.run("plan", "--no-cli", expect=0)
    ids = [s["id"] for s in twin.plan() if s["kind"] != "update"]       # the table: update-config's step is walked after it
    fleet = [s % 2 for s in STEPS] + [s % 3 for s in STEPS]
    assert ids[-len(fleet):] == fleet and ids[:-len(fleet)] == [i for i in before if not i.startswith("fleet-")]
    order = tc.teardown_ids(twin)
    assert order[:10] == ["fleet-attachments-3", "fleet-policy-3", "fleet-certificate-3", "fleet-shadows-3", "fleet-thing-3",
                          "fleet-attachments-2", "fleet-policy-2", "fleet-certificate-2", "fleet-shadows-2", "fleet-thing-2"]
    kinds = {s["id"]: s["kind"] for s in twin.plan()}
    assert [kinds[s % 2] for s in STEPS] == ["resource", "appears", "resource", "resource", "resource", "action", "action"]
    # with only car 2's key, only car 2's steps
    only = with_fleet(Rig(twin.base.parent / "only", notice=False).start(), cars=(2,))
    only.run("plan", "--no-cli", expect=0)
    assert [s["id"] for s in only.plan() if s["id"].startswith("fleet-")] == [s % 2 for s in STEPS]


def test_each_fleet_step_is_rendered_made_read_and_judged_for_its_own_car(twin: Rig) -> None:
    join(twin, 2)
    a = twin.account()
    cert = cert_of(twin, 2)
    assert THINGS[2] in a["things"] and a["certs"][cert]["status"] == "INACTIVE" and a["certs"][cert]["policies"] == [POLICIES[2]]
    assert a["things"][THINGS[2]]["principals"] == {arn(cert): "EXCLUSIVE_THING"}
    assert (twin.inputs / "device-2.crt").is_file()
    policy = json.loads(a["policies"][POLICIES[2]]["document"])
    text = json.dumps(policy)
    assert THINGS[2] in text and tc.THING not in text and client_arn(THINGS[2]) in text
    connect, = [s for s in policy["Statement"] if s["Action"] == "iot:Connect"]
    assert connect["Resource"] == client_arn(THINGS[2]) and connect["Condition"] == {"Bool": {"iot:Connection.Thing.IsAttached": "true"}}
    assert a["policies"][POLICIES[2]]["tags"] is True                      # created with its tags (the stand-in keeps that it had some)
    # read: each as rendered; the certificate ACTIVE or INACTIVE is no difference, and its state is said
    lines = tc.status_lines(twin.run("status"))
    for step in ("fleet-thing-2", "fleet-certificate-2", "fleet-policy-2", "fleet-attachments-2"):
        assert " created " in lines[step] and "as rendered" in lines[step], (step, lines[step])
    assert "not found" in lines["fleet-shadows-2"]
    set_cert(twin, cert, "ACTIVE")
    assert "as rendered" in tc.status_lines(twin.run("status"))["fleet-certificate-2"]
    set_cert(twin, cert, "INACTIVE")
    # each judge says its own car's difference
    twin.edit(lambda x: x["things"][THINGS[2]]["principals"].update({arn(cert): "NON_EXCLUSIVE_THING"}))
    assert "the certificate's attachment to the thing is not exclusive" in tc.status_lines(twin.run("status"))["fleet-attachments-2"]
    twin.edit(lambda x: x["policies"][POLICIES[2]].update(document=json.dumps({"Version": "2012-10-17", "Statement": []})))
    assert "its document is not the render" in tc.status_lines(twin.run("status"))["fleet-policy-2"]
    # the twin's own steps read as before
    assert "as rendered" in tc.status_lines(twin.run("status"))["attachments"]
    assert not tc.clean("".join(r.text for r in twin.said))


def test_the_fleets_shadows_are_based_on_the_cars_thing_and_their_words_are_the_cars(twin: Rig) -> None:
    join(twin, 2)
    ran = twin.run("apply", "fleet-shadows-2", expect=0)
    assert "approved with `fleet-active-2`" in ran.out and "`teardown fleet-shadows-2` deletes them before the thing" in ran.out
    assert "go-live" not in ran.out
    ran = twin.run("apply", "shadows", expect=0)                    # the twin's own words, unchanged
    assert ran.out.strip().endswith("are approved with go-live. `status` lists them; `teardown shadows` deletes them before the thing.")
    # the car's thing has its two named shadows; the teardown deletes those, the twin's stay
    twin.edit(lambda a: (a["things"][THINGS[2]]["shadows"].update({"vss": {"state": {"reported": {}}}, "config": {"state": {}}}),
                         a["things"][tc.THING]["shadows"].update({"vss": {"state": {"reported": {}}}})))
    twin.go("teardown", "fleet-attachments-2")
    twin.go("teardown", "fleet-policy-2")
    twin.go("teardown", "fleet-certificate-2")
    tc.set_status(twin, "thing", "absent")                          # the twin's thing is no base of the car's shadows: car 2's thing is
    ran = twin.go("teardown", "fleet-shadows-2")
    tc.set_status(twin, "thing", "created")
    assert twin.account()["things"][THINGS[2]]["shadows"] == {} and twin.account()["things"][tc.THING]["shadows"] != {}
    deletes = [c for c in twin.writes() if c[:2] == ["iot-data", "delete-thing-shadow"]]
    assert {c[c.index("--thing-name") + 1] for c in deletes} == {THINGS[2]}
    twin.go("teardown", "fleet-thing-2")
    assert THINGS[2] not in twin.account()["things"]


def test_the_fleet_thing_is_not_deleted_while_its_shadows_are_listed(twin: Rig) -> None:
    twin.go("apply", "fleet-thing-2")
    twin.edit(lambda a: a["things"][THINGS[2]]["shadows"].update({"vss": {"state": {}}}))
    since = len(twin.log())
    ran = twin.go("teardown", "fleet-thing-2", expect=1)
    assert "refused: precondition:" in ran.err and "named shadow(s) are listed" in ran.err and twin.writes(since) == []


def test_the_fleet_certificate_is_held_to_the_listing_and_recover_puts_its_id_back(twin: Rig) -> None:
    assert "fleet-certificate-2" in TW.RECOVERABLE and TW.CERT_FACTS["fleet-certificate-2"][0] == "fleet_certificate_id_2"
    twin.go("apply", "fleet-thing-2")
    # a certificate nobody knows in the listing: nothing is created on top of it
    twin.edit(lambda a: a["certs"].update({"0" * 63 + "f": {"status": "INACTIVE", "policies": []}}))
    since = len(twin.log())
    ran = twin.go("apply", "fleet-certificate-2", expect=1)
    assert "refused: listed-not-ours:" in ran.err and twin.writes(since) == []
    twin.edit(lambda a: a["certs"].pop("0" * 63 + "f"))
    twin.go("apply", "fleet-certificate-2")
    cert = cert_of(twin, 2)
    # the state loses the id: recover takes it back from the reply of this state directory
    edit_state(twin, lambda s: s["facts"].pop("fleet_certificate_id_2"))
    assert "no read" in tc.status_lines(twin.run("status"))["fleet-certificate-2"]
    twin.go("recover", "fleet-certificate-2")
    assert cert_of(twin, 2) == cert


def test_recover_holds_a_fleet_certificate_to_its_cars_thing_once_the_cars_attachments_stand(twin: Rig) -> None:
    """p2nit#5 (critic c17): with car B's attachments recorded, `recover fleet-certificate-2` puts the id back only when the account
    shows the certificate attached to car B's thing; detached by hand it is refused, recover-not-decided, and nothing is put back."""
    join(twin, 2)
    cert = cert_of(twin, 2)
    edit_state(twin, lambda s: s["facts"].pop("fleet_certificate_id_2"))
    held = twin.account()["things"][THINGS[2]]["principals"]
    assert arn(cert) in held, held
    twin.edit(lambda a: a["things"][THINGS[2]]["principals"].pop(arn(cert)))
    since = len(twin.log())
    ran = twin.go("recover", "fleet-certificate-2", expect=1)
    assert "refused: recover-not-decided:" in ran.err and "car 2's thing" in ran.err and twin.writes(since) == []
    assert "fleet_certificate_id_2" not in tc.facts(twin)
    twin.edit(lambda a: a["things"][THINGS[2]]["principals"].update({arn(cert): held[arn(cert)]}))
    twin.go("recover", "fleet-certificate-2")
    assert cert_of(twin, 2) == cert


def test_recover_puts_car_cs_certificate_back_once_it_is_attached_to_car_cs_thing(both: Rig) -> None:
    """With both cars' attachments standing, `recover fleet-certificate-3` holds car C's certificate to car C's thing, not car B's."""
    cert = cert_of(both, 3)
    edit_state(both, lambda s: s["facts"].pop("fleet_certificate_id_3"))
    both.go("recover", "fleet-certificate-3")
    assert cert_of(both, 3) == cert


def test_recover_reads_car_cs_thing_by_car_cs_attachments_whatever_car_bs_are(both: Rig) -> None:
    """Car C's attachments on record and car B's taken back: `recover fleet-certificate-3` still reads car C's thing, and car C's
    certificate detached from it by hand is refused, recover-not-decided, with nothing put back."""
    cert = cert_of(both, 3)
    edit_state(both, lambda s: (s["facts"].pop("fleet_certificate_id_3"), s["steps"]["fleet-attachments-2"].update(status="deleted")))
    both.edit(lambda a: a["things"][THINGS[3]]["principals"].pop(arn(cert)))
    since = len(both.log())
    ran = both.go("recover", "fleet-certificate-3", expect=1)
    assert "refused: recover-not-decided:" in ran.err and "car 3's thing" in ran.err and both.writes(since) == []
    assert "fleet_certificate_id_3" not in tc.facts(both)
    # car C's attachments taken back as well: its thing is not read, and the id goes back on its reply's PEM alone
    edit_state(both, lambda s: s["steps"]["fleet-attachments-3"].update(status="deleted"))
    since = len(both.log())
    both.go("recover", "fleet-certificate-3")
    assert cert_of(both, 3) == cert and [e for e in both.log()[since:] if e["argv"][:2] == ["iot", "list-thing-principals-v2"]] == []


@pytest.mark.parametrize("status", TW.OURS)
def test_recover_reads_car_cs_thing_while_car_cs_attachments_are_in_any_status_of_ours(both: Rig, status: str) -> None:
    cert = cert_of(both, 3)
    edit_state(both, lambda s: (s["facts"].pop("fleet_certificate_id_3"), s["steps"]["fleet-attachments-3"].update(status=status)))
    since = len(both.log())
    both.go("recover", "fleet-certificate-3")
    assert cert_of(both, 3) == cert and [e for e in both.log()[since:] if e["argv"][:2] == ["iot", "list-thing-principals-v2"]] != []


def test_the_certificates_teardown_needs_it_inactive_and_detached(twin: Rig) -> None:
    join(twin, 2)
    cert = cert_of(twin, 2)
    twin.go("teardown", "fleet-attachments-2")                      # the table in reverse: attachments, policy, certificate
    twin.go("teardown", "fleet-policy-2")
    set_cert(twin, cert, "ACTIVE")
    since = len(twin.log())
    ran = twin.go("teardown", "fleet-certificate-2", expect=1)
    assert "refused: precondition:" in ran.err and "not INACTIVE" in ran.err and twin.writes(since) == []
    set_cert(twin, cert, "INACTIVE")
    twin.go("teardown", "fleet-certificate-2")
    assert cert not in twin.account()["certs"]


# ================================================================================================= the set and the renders that take it

def test_the_set_is_the_cars_whose_attachments_stand_and_the_renders_take_it(twin: Rig) -> None:
    for step in ("fleet-thing-2", "fleet-certificate-2", "fleet-policy-2"):
        twin.go("apply", step)
    t = TW.Twin(twin.state, None, False)
    assert TW.fleet_set(t) == []
    twin.run("plan", "--no-cli", expect=0)
    assert twin.doc("function", "function-environment")["Variables"] == {
        "TWIN_CERTIFICATE_ARNS": arn(tc.CERT_1), "TWIN_CLIENT_IDS": tc.THING, "TWIN_RULE": RULE, "TWIN_POLICY": POLICY}
    twin.go("apply", "fleet-attachments-2")
    assert TW.fleet_set(TW.Twin(twin.state, None, False)) == [2]
    twin.run("plan", "--no-cli", expect=0)
    cert = cert_of(twin, 2)
    assert twin.doc("function", "function-environment")["Variables"] == {
        "TWIN_CERTIFICATE_ARNS": "%s,%s" % (arn(tc.CERT_1), arn(cert)), "TWIN_CLIENT_IDS": "%s,%s" % (tc.THING, THINGS[2]),
        "TWIN_RULE": RULE, "TWIN_POLICY": "%s,%s" % (POLICY, POLICIES[2])}
    function, = [s for s in twin.plan() if s["id"] == "function"]
    create, = function["creates"]
    assert create[create.index("--timeout") + 1] == "45"
    role = {s["Sid"]: s for s in twin.doc("breaker-role", "breaker-role-policy")["Statement"]}
    assert role["Certificate"]["Resource"] == [arn(tc.CERT_1), arn(cert)]
    assert role["Connection"]["Resource"] == [client_arn(tc.THING), client_arn(THINGS[2])]
    assert role["PolicyTargets"]["Resource"] == [policy_arn(POLICY), policy_arn(POLICIES[2])]
    assert sorted(role["Certificate"]["Action"]) == sorted(["iot:UpdateCertificate", "iot:DetachPolicy", "iot:DescribeCertificate"])
    reattach, = [s for s in twin.plan() if s["id"] == "reattach-policy"]
    assert reattach["creates"] == [["iot", "attach-policy", "--policy-name", POLICY, "--target", arn(tc.CERT_1)],
                                   ["iot", "attach-policy", "--policy-name", POLICIES[2], "--target", arn(cert)]]


def test_a_car_whose_attachments_are_torn_down_leaves_the_set_and_the_one_car_renders_come_back(twin: Rig) -> None:
    join(twin, 2)
    twin.go("teardown", "fleet-attachments-2")
    assert TW.fleet_set(TW.Twin(twin.state, None, False)) == []
    twin.run("plan", "--no-cli", expect=0)
    env = twin.doc("function", "function-environment")["Variables"]
    assert env["TWIN_POLICY"] == POLICY and env["TWIN_CERTIFICATE_ARNS"] == arn(tc.CERT_1)
    role = {s["Sid"]: s for s in twin.doc("breaker-role", "breaker-role-policy")["Statement"]}
    assert role["Certificate"]["Resource"] == arn(tc.CERT_1)                # a string, as the one-car render has it
    function, = [s for s in twin.plan() if s["id"] == "function"]
    create, = function["creates"]
    assert create[create.index("--timeout") + 1] == "30"


def test_a_car_joining_the_set_takes_back_what_stood_on_it(twin: Rig) -> None:
    remake = [s for s in SET_RECORDS if status_of(twin, s) in ("done", "verified")]
    assert remake == SET_RECORDS
    for step in ("fleet-thing-2", "fleet-certificate-2", "fleet-policy-2"):
        twin.go("apply", step)
    assert [status_of(twin, s) for s in SET_RECORDS] == [("verified" if s == "breaker-role" else "done") for s in SET_RECORDS]
    ran = twin.go("apply", "fleet-attachments-2")
    assert [status_of(twin, s) for s in SET_RECORDS] == ["stale"] * len(SET_RECORDS)
    assert "the breaker's set changed" in ran.out
    # go-live and anything that stands on them wait for the breaker to run again on the set
    assert "refused: step-needs:" in twin.go("apply", "alarm-test-bytes", expect=1).err


def test_a_car_leaving_the_set_takes_back_what_stood_on_it_the_fleet_active_records_among_them(both: Rig) -> None:
    both.go("apply", "fleet-active-2")
    both.go("apply", "fleet-inactive-2")
    assert status_of(both, "fleet-active-2") == "done"
    both.go("teardown", "fleet-attachments-3")
    assert [status_of(both, s) for s in SET_RECORDS + ["fleet-active-2"]] == ["stale"] * (len(SET_RECORDS) + 1)
    assert TW.fleet_set(TW.Twin(both.state, None, False)) == [2]


def test_only_the_highest_car_whose_steps_stand_can_leave(both: Rig) -> None:
    since = len(both.log())
    ran = both.run("teardown", "fleet-attachments-2", expect=1)     # refused before its render is printed
    assert "refused: teardown-order:" in ran.err and "fleet-attachments-3" in ran.err and both.writes(since) == []
    both.go("teardown", "fleet-attachments-3")                      # car C leaves first
    since = len(both.log())
    ran = both.run("teardown", "fleet-attachments-2", expect=1)     # and while its other steps stand, car B cannot
    assert "refused: teardown-order:" in ran.err and "fleet-policy-3" in ran.err and both.writes(since) == []
    assert TW.fleet_set(TW.Twin(both.state, None, False)) == [2]


@pytest.mark.parametrize("how", ["apply", "teardown"])
def test_a_set_change_is_refused_while_a_fleet_certificate_reads_active(both: Rig, how: str) -> None:
    step = "fleet-attachments-3"
    if how == "apply":
        both.go("teardown", step)                                   # car C out of the set: its joining again is the set change
    set_cert(both, cert_of(both, 2), "ACTIVE")                      # car B's certificate ACTIVE: no set change
    since = len(both.log())
    ran = both.go(how, step, expect=1)
    assert "refused: fleet-active-standing:" in ran.err and both.writes(since) == []
    reads = [c[:2] for c in tc_sent(both, since)]
    assert ["iot", "describe-certificate"] in reads                 # each made fleet certificate is read first
    set_cert(both, cert_of(both, 2), "INACTIVE")
    both.go(how, step)


def tc_sent(rig: Rig, since: int = 0) -> List[List[str]]:
    return uc.sent(rig, since)


def edited_source(rig: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The breaker's source edited and built again at the zip's path: a code update is due."""
    path = tmp_path / "the-source" / "breaker.py"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(uc.NEW_SOURCE)
    monkeypatch.setattr(TW, "BREAKER_SOURCE", path)
    (rig.inputs / "breaker.zip").write_bytes(uc.NEW_ZIP)


def test_a_join_is_refused_code_first_while_a_code_update_is_due(twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for step in ("fleet-thing-2", "fleet-certificate-2", "fleet-policy-2"):
        twin.go("apply", step)
    edited_source(twin, monkeypatch, tmp_path)
    since = len(twin.log())
    ran = twin.go("apply", "fleet-attachments-2", expect=1)
    assert "refused: code-first:" in ran.err and "update-code function" in ran.err and twin.writes(since) == []
    assert status_of(twin, "fleet-attachments-2") == "absent"


def test_a_leave_is_refused_code_first_on_a_twin_that_is_not_read_as_cut_and_the_change_back_is_let_through(
        both: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    both.edit(lambda a: a["rules"][RULE].update(ruleDisabled=False))            # the twin not read as cut: its rule is enabled
    # a set of B and C on a function that names both: a leave is no change back, and is refused while a code update is due
    edited_source(both, monkeypatch, tmp_path)
    since = len(both.log())
    ran = both.go("teardown", "fleet-attachments-3", expect=1)
    assert "refused: code-first:" in ran.err and both.writes(since) == []
    # the function named B alone (car C joined after the last update-config): car C's leaving is the change back
    both.edit(lambda a: a["functions"][FUNCTION]["config"]["Environment"]["Variables"].update(
        TWIN_CERTIFICATE_ARNS="%s,%s" % (arn(tc.CERT_1), arn(cert_of(both, 2))), TWIN_CLIENT_IDS="%s,%s" % (tc.THING, THINGS[2]),
        TWIN_POLICY="%s,%s" % (POLICY, POLICIES[2])))
    both.go("teardown", "fleet-attachments-3")
    # and car C joining again is no change back: refused
    ran = both.go("apply", "fleet-attachments-3", expect=1)
    assert "refused: code-first:" in ran.err


def test_a_leave_with_a_code_update_due_is_let_through_on_a_twin_read_as_cut(both: Rig, monkeypatch: pytest.MonkeyPatch,
                                                                            tmp_path: Path) -> None:
    edited_source(both, monkeypatch, tmp_path)
    assert both.account()["rules"][RULE]["ruleDisabled"] is True            # cut by the alarm tests, and not restored
    both.go("teardown", "fleet-attachments-3")


def test_two_cars_joined_before_update_config_and_a_code_update_due_leave_toward_what_the_function_names(
        twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """fable#2, verify#2 (review S1 for two cars): both cars joined before update-config (P4's step 3: the function names car A alone),
    then a code update due on a twin that is NOT read as cut. Car C's leaving moves the set toward what the function names and is let
    through; its other steps go, the function naming none of them; car B's leaving is then the change back, and update-code has its
    way. Before, every command was refused but `trip`."""
    join(twin, 2)
    join(twin, 3)
    assert twin.account()["rules"][RULE]["ruleDisabled"] is False             # live: no waiver
    one_car = env_of(twin)
    assert one_car["TWIN_POLICY"] == POLICY
    edited_source(twin, monkeypatch, tmp_path)
    assert "refused: code-first:" in twin.run("update-config", "function", expect=1).err
    since = len(twin.log())
    twin.go("teardown", "fleet-attachments-3")
    assert [w[:2] for w in twin.writes(since)] == [["iot", "detach-thing-principal"], ["iot", "detach-policy"]]
    assert TW.fleet_set(TW.Twin(twin.state, None, False)) == [2] and env_of(twin) == one_car
    # a join is no such move: car C joining again names a car the function does not
    assert "refused: code-first:" in twin.go("apply", "fleet-attachments-3", expect=1).err
    for step in ("fleet-policy-3", "fleet-certificate-3", "fleet-thing-3"):
        twin.go("teardown", step)
    twin.go("teardown", "fleet-attachments-2")                                # the change back: the function names car A alone
    uc.granted(twin)
    uc.approve(twin, uc.shown(twin), 0)
    assert fn_config(twin)["CodeSha256"] == uc.code_of(uc.NEW_ZIP) and env_of(twin) == one_car


@pytest.mark.parametrize("how", ["apply", "teardown"])
def test_a_set_change_is_refused_while_the_functions_update_is_unsettled(both: Rig, how: str) -> None:
    if how == "apply":
        both.go("teardown", "fleet-attachments-3")
    edit_state(both, lambda s: s["steps"]["function"].update(status="updating", update={"kind": "config", "from": "0" * 64, "to": "1" * 64,
                                                                                         "render": "2" * 64, "sent": [0]}))
    since = len(both.log())
    ran = both.go(how, "fleet-attachments-3", expect=1)
    assert "refused: still-updating: the function's update is on record and not settled" in ran.err and both.writes(since) == []


# ================================================================================================= update-config function

def test_update_config_prints_its_render_and_runs_by_its_own_approval(joined: Rig) -> None:
    twin = joined                                                   # the join took function-status and the dry trip back: run again
    digest = shown_config(twin)
    out = twin.said[-1].out
    assert "update-config function-config (row 13)" in out and "3 call(s), 1 document(s):" in out
    calls = [line.strip() for line in out.split("\n") if line.startswith("  aws ")]
    assert [c.split()[1:3] for c in calls] == [["lambda", "update-function-configuration"], ["lambda", "wait"], ["lambda", "get-function"]]
    assert "--timeout 45 --environment file://" in calls[0] and "wait function-updated-v2" in calls[1]
    assert "to go on, once the owner said yes to this: twinctl update-config function --approve function-config:%s" % digest in out
    assert "refused: approval-for-another-step:" in twin.run("update-config", "function", "--approve", "function-code:" + digest, expect=1).err
    since = len(twin.log())
    ran = twin.run("update-config", "function", "--approve", "function-config:" + digest, expect=0)
    writes = twin.writes(since)
    assert [w[:2] for w in writes] == [["lambda", "update-function-configuration"]]
    assert fn_config(twin)["Timeout"] == 45 and env_of(twin) == twin.doc("function-config", "function-environment")["Variables"]
    # nothing else of the function changed
    assert fn_config(twin)["CodeSha256"] == uc.code_of(uc.OLD_ZIP) and fn_config(twin)["MemorySize"] == 128
    e = function_entry(twin)
    assert e["status"] == "created" and "update" not in e and len(e["config_updates"]) == 1
    u, = e["config_updates"]
    assert re.fullmatch(r"[0-9a-f]{64}", u["from"]) and re.fullmatch(r"[0-9a-f]{64}", u["to"]) and u["render"] == digest
    # function-status and the dry trip run again; what stood on the function is taken back
    for step in ("function-status", "dry-trip"):
        assert tc.state_of(twin)["steps"][step]["stale_for"] == "function-config" and step in ran.out
    assert [status_of(twin, s) for s in TESTS + ["reattach-policy"]] == ["stale"] * (len(TESTS) + 1)
    lines = tc.status_lines(twin.run("status"))
    assert "as rendered" in lines["function"] and "configuration was updated in place" in lines["function-status"]
    # one printing lets one run through: with something to update again, the same approval is spent
    assert "refused: nothing-to-update:" in twin.run("update-config", "function", "--approve", "function-config:" + digest, expect=1).err
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=30))
    assert "refused: approval-spent:" in twin.run("update-config", "function", "--approve", "function-config:" + digest, expect=1).err
    assert not tc.clean("".join(r.text for r in twin.said))


def test_the_record_and_the_output_of_update_config_hold_hashes_and_never_the_variables(joined: Rig) -> None:
    twin = joined
    twin.edit(lambda a: a.update(reply_garbage={"lambda update-function-configuration": "a reply that is no JSON"}))
    ran = configure(twin, expect=1)
    e = function_entry(twin)
    assert e["status"] == "updating" and e["update"]["kind"] == "config" and e["update"]["sent"] == [0]
    record = json.dumps(e)
    for value in (THINGS[2], tc.THING, cert_of(twin, 2), tc.ACCOUNT, POLICIES[2]):
        assert value not in record, value
    assert e["update"]["from"] == TW.config_hash(30, {"TWIN_CERTIFICATE_ARNS": arn(tc.CERT_1), "TWIN_CLIENT_IDS": tc.THING, "TWIN_RULE": RULE,
                                                       "TWIN_POLICY": POLICY})
    assert e["update"]["from"] not in ran.text and e["update"]["to"] not in ran.text
    twin.edit(lambda a: a.pop("reply_garbage"))
    ran = twin.run("status")
    e = function_entry(twin)
    assert e["status"] == "created" and len(e["config_updates"]) == 1 and e["config_updates"][0]["from"] not in ran.text
    assert not tc.clean(ran.text)


def test_config_hash_is_the_sha256_of_the_canonical_time_out_and_variables() -> None:
    v = {"B": "2", "A": "1"}
    assert TW.config_hash(45, v) == TW.config_hash(45, dict(sorted(v.items())))
    assert TW.config_hash(45, v) != TW.config_hash(30, v) and TW.config_hash(45, v) != TW.config_hash(45, dict(v, A="x"))
    assert TW.config_hash(45, v) == hashlib.sha256(json.dumps({"Timeout": 45, "Variables": v}, sort_keys=True, separators=(",", ":"))
                                                   .encode("utf-8")).hexdigest()


def test_update_config_is_refused_before_any_write_each_by_its_name(twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # nothing to update: the one-car function is the one-car render
    since = len(twin.log())
    ran = configure(twin, expect=1)
    assert "refused: nothing-to-update:" in ran.err and twin.writes(since) == []
    join(twin, 2)
    # the breaker role as read does not allow car 2's ARNs (the owner has not remade it): breaker-role-short
    since = len(twin.log())
    ran = configure(twin, expect=1)
    assert "refused: breaker-role-short:" in ran.err and twin.writes(since) == []
    remake_role(twin)
    # a car of the set whose attachments are not created: step-needs
    tc.set_status(twin, "fleet-attachments-2", "unverified")
    assert "refused: step-needs:" in twin.run("update-config", "function", expect=1).err
    tc.set_status(twin, "fleet-attachments-2", "created")
    # any difference of the function but its time-out and environment: printed, and refused
    digest = shown_config(twin)
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(MemorySize=256))
    since = len(twin.log())
    ran = twin.run("update-config", "function", "--approve", "function-config:" + digest, expect=1)
    assert "refused: function-differs:" in ran.err and "its configuration is not the render" in ran.err and twin.writes(since) == []
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(MemorySize=128, CodeSha256=uc.code_of(b"code nobody built")))
    ran = twin.run("update-config", "function", "--approve", "function-config:" + digest, expect=1)
    assert "refused: function-differs:" in ran.err and uc.CODE_DIFFERS in ran.err
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(CodeSha256=uc.code_of(uc.OLD_ZIP)))
    # a fleet certificate ACTIVE: fleet-active-standing
    set_cert(twin, cert_of(twin, 2), "ACTIVE")
    ran = twin.run("update-config", "function", "--approve", "function-config:" + digest, expect=1)
    assert "refused: fleet-active-standing:" in ran.err and twin.writes(since) == []
    set_cert(twin, cert_of(twin, 2), "INACTIVE")
    # a caller that is not the operator role
    saved = twin.account()
    twin.edit(lambda a: a.update(identity={"UserId": "x", "Arn": tc.j("arn:aws:sts::", tc.ACCOUNT, ":assumed-role/another-role/session")}))
    assert "refused: identity-not-the-operator-role:" in twin.run("update-config", "function", "--approve", "function-config:" + digest,
                                                                   expect=1).err
    twin.put_account(saved)
    # the function gone
    twin.edit(lambda a: a["functions"].clear())
    assert "refused: function-not-found:" in twin.run("update-config", "function", "--approve", "function-config:" + digest, expect=1).err
    twin.put_account(saved)
    # a code update due: code first
    edited_source(twin, monkeypatch, tmp_path)
    ran = twin.run("update-config", "function", expect=1)
    assert "refused: code-first:" in ran.err and "update-code function" in ran.err
    assert twin.writes(since) == []
    # not recorded as made
    started = with_fleet(Rig(tmp_path / "started", notice=False).start())
    assert "refused: function-not-made:" in started.run("update-config", "function", expect=1).err


def test_a_leave_runs_update_config_on_the_wider_role_and_the_owner_narrows_it_after(both: Rig) -> None:
    both.go("teardown", "fleet-attachments-3")                    # car C leaves; the role still allows B and C
    configure(both)
    assert env_of(both)["TWIN_POLICY"] == "%s,%s" % (POLICY, POLICIES[2])
    # the role as read is wider than its render now: it differs, and the owner narrows it by hand
    assert "its policy is not the render" in tc.status_lines(both.run("status"))["breaker-role"]
    remake_role(both)
    assert "as rendered" in tc.status_lines(both.run("status"))["breaker-role"]


@pytest.mark.parametrize("sid, drops", [("PolicyTargets", "policy-3"), ("Connection", "client-3"), ("Certificate", "cert-3"),
                                        ("Certificate", "DetachPolicy"), ("Certificate", "DescribeCertificate"),
                                        ("Certificate", "UpdateCertificate"), ("Certificate", "cert-1"), ("Connection", "client-1"),
                                        ("PolicyTargets", "policy-1"), ("Certificate", "apart"), ("Certificate", "cert-3-denied")],
                         ids=["a-policy-arn", "a-client-arn", "a-certificate-arn", "the-detach-action", "the-describe-action",
                              "the-update-action", "the-twins-certificate-arn", "the-twins-client-arn", "the-twins-policy-arn",
                              "the-actions-and-the-arns-apart", "a-certificate-arn-in-a-deny"])
def test_a_role_without_one_of_the_sets_arns_is_breaker_role_short(both: Rig, sid: str, drops: str) -> None:
    """p2nit#3 (critic c13) is the last case: car C's certificate ARN is taken out of the Allow statement and held, with the same
    three actions, by a Deny statement alone. A Deny statement allows nothing here: an action and ARN that only a Deny statement
    holds are not allowed."""
    both.go("teardown", "fleet-attachments-3")
    both.go("apply", "fleet-attachments-3")                        # the set changed; the function names B and C already
    configure(both, expect=1)                                       # nothing to update
    role = tc.ROLES["breaker-role"]
    car_c = {"policy-3": POLICIES[3], "client-3": THINGS[3], "cert-3": cert_of(both, 3), "cert-3-denied": cert_of(both, 3),
             "cert-1": tc.CERT_1, "client-1": client_arn(tc.THING), "policy-1": policy_arn(tc.PREFIX + "-device")}.get(drops, "")

    def narrow(a: Dict[str, Any]) -> None:
        doc = a["roles"][role]["policies"][role + "-policy"]
        hit = [st for st in doc["Statement"] if st["Sid"] == sid]
        assert hit, sid
        for st in hit:
            if drops in ("DetachPolicy", "DescribeCertificate", "UpdateCertificate"):
                st["Action"] = [x for x in (st["Action"] if isinstance(st["Action"], list) else [st["Action"]]) if x != "iot:" + drops]
            elif drops == "apart":                              # the three actions on another ARN; the set's ARNs under another action
                doc["Statement"].append({"Sid": "Apart", "Effect": "Allow", "Action": ["iot:ListCertificates"], "Resource": st["Resource"]})
                st["Resource"] = [arn("0" * 64)]
            elif drops in ("client-1", "policy-1"):             # the twin's own ARN alone (a car's policy name starts with the twin's)
                st["Resource"] = [r for r in (st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]) if r != car_c]
            else:
                st["Resource"] = [r for r in (st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]) if car_c not in r]
        if drops == "cert-3-denied":
            actions = hit[0]["Action"] if isinstance(hit[0]["Action"], list) else [hit[0]["Action"]]
            assert sorted(actions) == ["iot:DescribeCertificate", "iot:DetachPolicy", "iot:UpdateCertificate"], actions
            doc["Statement"].append({"Sid": "DenyCarC", "Effect": "Deny", "Action": list(actions), "Resource": [arn(car_c)]})
    both.edit(narrow)
    both.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=30))      # something to update
    since = len(both.log())
    ran = configure(both, expect=1)
    assert "refused: breaker-role-short:" in ran.err and both.writes(since) == []


SETTLES: List[Any] = [
    # (the stand-in's plants before the send, the reading after it)
    ("to", {}, "updated"),
    ("from", {"config_ignored": True}, "not-updated"),
    ("neither", {}, "unsettled"),
    ("failed-to", {"config_status": "Failed"}, "updated"),
    ("failed-from", {"config_ignored": True, "config_status": "Failed"}, "not-updated"),
    ("failed-neither", {"config_status": "Failed"}, "unsettled"),
]


@pytest.mark.parametrize("plants, reading", [s[1:] for s in SETTLES], ids=[s[0] for s in SETTLES])
@pytest.mark.parametrize("settler", ["status", "update-config", "update-code"])
def test_a_config_record_is_settled_by_its_own_fields_against_the_recorded_hashes(joined: Rig, settler: str, plants: Dict[str, Any],
                                                                                   reading: str) -> None:
    """The config rule (review S7, S8), by each settler (review S6): the wait fails, so the record stays `updating`; then the time-out
    and environment as read decide against the recorded hashes. `Failed` adds its word and never overrides the fields."""
    twin = joined
    marked = ["function-status", "dry-trip"]
    twin.edit(lambda a: (a.update(plants), a["faults"].append({"service": "lambda", "op": "wait", "code": "WaiterFailure"})))
    ran = configure(twin, expect=1)
    assert "call 2 of 2 failed (lambda wait: WaiterFailure)" in ran.err and function_entry(twin)["status"] == "updating"
    if reading == "unsettled":                                      # the function reads as neither: another time-out than both
        twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=33))
    ran = twin.run(*(["status"] if settler == "status" else [settler, "function"]))
    e = function_entry(twin)
    if reading == "updated":
        assert e["status"] == "created" and "update" not in e and len(e["config_updates"]) == 1, ran.text
        assert [status_of(twin, s) for s in marked] == ["stale", "stale"]
    elif reading == "not-updated":
        assert e["status"] == "created" and "update" not in e and not e.get("config_updates"), ran.text
        assert [status_of(twin, s) for s in marked] == ["done", "done"]
    else:
        assert e["status"] == "updating" and "update-unsettled" in ran.text, ran.text
    assert ("the service reports the last update Failed" in ran.text) is ("config_status" in plants)
    assert not tc.clean(ran.text)


def test_a_config_record_in_progress_is_refused_and_stays_updating(joined: Rig) -> None:
    twin = joined
    twin.edit(lambda a: a.update(config_status="InProgress"))
    ran = configure(twin, expect=1)
    assert "refused: update-in-progress:" in ran.err and function_entry(twin)["status"] == "updating"
    since = len(twin.log())
    for argv in (["status"], ["update-config", "function"], ["update-code", "function"]):
        ran = twin.run(*argv)
        assert "update-in-progress" in ran.text and function_entry(twin)["status"] == "updating", argv
    assert twin.writes(since) == []
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(LastUpdateStatus="Successful"))
    twin.run("status")
    assert function_entry(twin)["status"] == "created" and len(function_entry(twin)["config_updates"]) == 1


def test_a_config_record_is_settled_against_the_recorded_to_after_the_render_moved(joined: Rig) -> None:
    twin = joined
    twin.edit(lambda a: a["faults"].append({"service": "lambda", "op": "wait", "code": "WaiterFailure"}))
    configure(twin, expect=1)
    assert function_entry(twin)["status"] == "updating"
    # the render moves (car 2's attachments recorded otherwise, by hand): the function as read is still the recorded `to`
    edit_state(twin, lambda s: s["steps"]["fleet-attachments-2"].update(status="deleted"))
    twin.run("status")
    e = function_entry(twin)
    assert e["status"] == "created" and len(e["config_updates"]) == 1


@pytest.mark.parametrize("kind", [None, "code"])
@pytest.mark.parametrize("settler", ["status", "update-config", "update-code"])
def test_a_code_record_is_settled_as_merged_by_every_settler(twin: Rig, kind: Any, settler: str) -> None:
    """A record with no kind (the merged update-code's) or "code" is settled by settle_update: by LastUpdateStatus, then CodeSha256."""
    update: Dict[str, Any] = {"from": uc.sha(uc.OLD_ZIP), "to": uc.sha(uc.NEW_ZIP), "render": "0" * 64, "sent": [0]}
    if kind:
        update["kind"] = kind
    edit_state(twin, lambda s: s["steps"]["function"].update(status="updating", update=update))
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(CodeSha256=uc.code_of(uc.OLD_ZIP)))
    ran = twin.run(*(["status"] if settler == "status" else [settler, "function"]))
    e = function_entry(twin)
    assert e["status"] == "created" and "update" not in e and "still the zip it was made from" in ran.text, ran.text
    # a code record whose code reads as the new zip: settled to it, whatever its environment says
    edit_state(twin, lambda s: s["steps"]["function"].update(status="updating", update=update))
    twin.edit(lambda a: a["functions"][FUNCTION]["config"].update(CodeSha256=uc.code_of(uc.NEW_ZIP), Timeout=31))
    twin.run("status")
    assert function_entry(twin)["inputs"] == {"TWIN_BREAKER_ZIP": uc.sha(uc.NEW_ZIP)}


def test_the_operator_grant_appears_only_with_a_fleet_key_or_a_config_update_on_record(twin: Rig, made: Rig, tmp_path: Path) -> None:
    def function_actions(rig: Rig) -> List[str]:
        return [a for s in rig.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function" for a in s["Action"]]

    plain = made.copy(tmp_path / "plain")
    plain.run("plan", "--no-cli", expect=0)
    assert CONFIG_ACTION not in function_actions(plain) and "function-config" not in [s["id"] for s in plain.plan()]
    twin.run("plan", "--no-cli", expect=0)
    assert CONFIG_ACTION in function_actions(twin)
    step, = [s for s in twin.plan() if s["id"] == "function-config"]
    assert [c[:2] for c in step["creates"]] == [["lambda", "update-function-configuration"], ["lambda", "wait"]]
    calls = [TW.Call(c[0], c[1], tuple(c[2:]), False) for c in step["creates"] + step["reads"]]
    without = copy.deepcopy(twin.doc("operator-role", "operator-role-policy"))
    tc._allow(without, "Function")["Action"].remove(CONFIG_ACTION)
    assert TW.operator_gaps(without, calls) == ["%s (lambda update-function-configuration) is allowed by no statement" % CONFIG_ACTION]
    assert TW.operator_gaps(twin.doc("operator-role", "operator-role-policy"), calls) == []
    # a config update on record keeps the grant with the keys taken out
    edit_state(twin, lambda s: s["steps"]["function"].update(config_updates=[{"from": "0" * 64, "to": "1" * 64, "render": "2" * 64,
                                                                               "at": "2026-01-01T00:00:00Z"}]))
    for k in TW.FLEET_CARS:
        for key in ("TWIN_FLEET_THING_%d", "TWIN_FLEET_CSR_%d", "TWIN_FLEET_CERTIFICATE_OUT_%d"):
            twin.extra.pop(key % k)
    twin.run("literals", expect=0)
    twin.run("plan", "--no-cli", expect=0)
    assert CONFIG_ACTION in function_actions(twin)


def no_twin_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in [k for k in os.environ if k.startswith(("TWIN_", "AWS_")) or k == "STUB_AWS_DIR"]:
        monkeypatch.delenv(k)


def operator_policy(state: Path, render: Path) -> Any:
    """The operator role's policy as twinctl renders it, in this process: no command, no plan and no CLI."""
    t = TW.Twin(state, render, False)
    return t.render(t.step("operator-role")).render.obj("operator-role-policy")


def test_the_configuration_grant_is_rendered_only_with_a_fleet_key_or_its_record_judged_by_value(rig: Rig,
                                                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """fable#7 (mutant 26): the operator policy of a twin that has made nothing, rendered here with no plan, so that a grant rendered
    without its key is seen by value and not through the stand-in's refusal of the update's calls that plan would then walk."""
    no_twin_variables(monkeypatch)

    def function_actions() -> List[str]:
        return [a for s in operator_policy(rig.state, rig.render)["Statement"] if s["Sid"] == "Function" for a in s["Action"]]
    assert CONFIG_ACTION not in function_actions() and TW.UPDATE_ACTION not in function_actions()
    monkeypatch.setenv("TWIN_FLEET_THING_2", THINGS[2])
    assert CONFIG_ACTION in function_actions() and TW.UPDATE_ACTION not in function_actions()
    monkeypatch.delenv("TWIN_FLEET_THING_2")
    assert CONFIG_ACTION not in function_actions()
    # p2nit#2 (critic c10): a configuration update `updating`, with no key and nothing settled on record, asks for the grant alone
    edit_state(rig, lambda s: s["steps"].setdefault("function", {}).update(update={"kind": "config", "from": "0" * 64, "to": "1" * 64,
                                                                                    "render": "2" * 64, "sent": []}))
    assert CONFIG_ACTION in function_actions() and TW.UPDATE_ACTION not in function_actions()
    edit_state(rig, lambda s: s["steps"]["function"].pop("update"))
    assert CONFIG_ACTION not in function_actions()
    edit_state(rig, lambda s: s["steps"].setdefault("function", {}).update(config_updates=[
        {"from": "0" * 64, "to": "1" * 64, "render": "2" * 64, "at": "2026-01-01T00:00:00Z"}]))
    assert CONFIG_ACTION in function_actions()


# IAM'S QUOTA FOR A ROLE'S INLINE POLICIES, as read on AWS's IAM quotas page ("IAM and AWS STS quotas") on 2026-11-15 for the owner's
# decision of that day: 10,240 characters for the sum of all inline policies on one role, whitespace not counted,
# and it cannot be raised. The operator role has the one inline policy, which the owner's remake replaces.
ROLE_INLINE_LIMIT = 10240


def test_the_operator_policy_with_every_grant_and_the_longest_names_is_within_iams_inline_limit_for_a_role(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """verify#1, fable#3 (the owner's decision of 2026-11-15): the operator role keeps its one inline policy, as
    rendered, and this holds the render within IAM's limit for a role, with every key that adds grants given (Phase 6's ECR, pull role
    and pull thing, the notice, a fleet key for the configuration update's grant, a code update on record for the code's) and the
    longest prefix the key takes. The other names it is made of are at the longest their keys take too, and the region's name is one
    of 14 characters (its key's form has no bound; no region's name is longer, from memory). No measured size is pinned."""
    no_twin_variables(monkeypatch)

    def longest(key: str, base: str, fill: str) -> str:
        """`base` filled out to the longest value the key's form takes."""
        pattern = TW.NAME_KEYS[key][1]
        value = base
        while re.fullmatch(pattern, value + fill):
            value += fill
        assert re.fullmatch(pattern, value) and len(value) > len(base), key
        return value

    prefix = longest("TWIN_PREFIX", tc.PREFIX, "0")
    names = {"TWIN_NO_NAMES_FILE": "1", "TWIN_ACCOUNT": tc.ACCOUNT, "TWIN_REGION": "ap-southeast-1", "TWIN_PROFILE": tc.PROFILE,
             "TWIN_OPERATOR_ROLE": longest("TWIN_OPERATOR_ROLE", tc.ROLE, "0"), "TWIN_PREFIX": prefix, "TWIN_THING": prefix + "-thing",
             "TWIN_BUCKET_SUFFIX": longest("TWIN_BUCKET_SUFFIX", tc.SUFFIX, "0"), "TWIN_NOTICE": "1", "TWIN_NOTICE_ADDRESS": tc.ADDRESS,
             "TWIN_ECR": "1", "TWIN_PULL_ROLE": longest("TWIN_PULL_ROLE", tc.PULL_ROLE, "0"), "TWIN_PULL_THING": prefix + "-pull-thing",
             "TWIN_FLEET_THING_2": prefix + "-car-b", "TWIN_FLEET_THING_3": prefix + "-car-c"}
    for key, value in names.items():
        monkeypatch.setenv(key, value)
    state = tmp_path / "state"
    state.mkdir()
    (state / "state.json").write_text(json.dumps({"v": 1, "facts": {}, "steps": {"function": {"code_updates": [
        {"from": "0" * 64, "to": "1" * 64, "render": "2" * 64, "at": "2026-01-01T00:00:00Z"}]}}}), encoding="utf-8")
    doc = operator_policy(state, tmp_path / "render")
    sids = [s["Sid"] for s in doc["Statement"]]
    assert {"EcrRepositories", "PullRoleAlias", "ReadAndPassThePullRole", "Topic"} <= set(sids)          # every part of the grants
    function, = [s for s in doc["Statement"] if s["Sid"] == "Function"]
    assert {TW.UPDATE_ACTION, CONFIG_ACTION} <= set(function["Action"])
    assert len("".join(json.dumps(doc).split())) <= ROLE_INLINE_LIMIT


# ================================================================================================= fleet-active-k and fleet-inactive-k

def test_fleet_active_makes_the_cars_certificate_active_through_its_pre_and_status_says_a_fleet_session(both: Rig) -> None:
    since = len(both.log())
    both.go("apply", "fleet-active-2")
    assert both.writes(since) == [["iot", "update-certificate", "--certificate-id", cert_of(both, 2), "--new-status", "ACTIVE"]]
    ran = both.run("status", expect=0)
    assert "active: a fleet session (`twinctl apply fleet-inactive-2` ends it)" in ran.out and not fails(ran)
    both.go("apply", "fleet-inactive-2")
    assert both.account()["certs"][cert_of(both, 2)]["status"] == "INACTIVE"


PRE: List[Any] = [
    ("an-alarm-in-alarm", lambda rig: rig.edit(lambda a: a["alarms"]["%s-bytes" % tc.PREFIX].update(StateValue="ALARM")), "breaker-not-armed"),
    ("an-alarm-disabled", lambda rig: rig.edit(lambda a: a["alarms"]["%s-shadow" % tc.PREFIX].update(ActionsEnabled=False)), "breaker-not-armed"),
    ("policy-detached", lambda rig: rig.edit(lambda a: a["certs"][cert_of(rig, 2)].update(policies=[])), "fleet-not-attached"),
    ("thing-not-exclusive", lambda rig: rig.edit(lambda a: a["things"][THINGS[2]]["principals"].update(
        {arn(cert_of(rig, 2)): "NON_EXCLUSIVE_THING"})), "fleet-not-attached"),
    ("environment-not-the-sets", lambda rig: rig.edit(lambda a: a["functions"][FUNCTION]["config"]["Environment"]["Variables"].update(
        TWIN_POLICY=POLICY)), "function-not-the-sets"),
    ("time-out-not-the-sets", lambda rig: rig.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=30)), "function-not-the-sets"),
    ("code-not-the-recorded-zip", lambda rig: rig.edit(lambda a: a["functions"][FUNCTION]["config"].update(
        CodeSha256=uc.code_of(b"code nobody built"))), "function-not-the-sets"),
    ("updating", lambda rig: tc.set_status(rig, "function", "updating"), "still-updating"),
    ("role-differs", lambda rig: rig.edit(lambda a: a["roles"][tc.ROLES["breaker-role"]]["policies"][tc.ROLES["breaker-role"] + "-policy"]
                                          ["Statement"].pop()), "breaker-role-not-rendered"),
    ("dry-trip-one-name", lambda rig: payload(rig, lambda r: r["counts"].pop("policies")), "dry-trip-not-covering"),
    ("dry-trip-not-cut", lambda rig: payload(rig, lambda r: r.update(cut=False)), "dry-trip-not-covering"),
    ("dry-trip-cut-a-number", lambda rig: payload(rig, lambda r: r.update(cut=1)), "dry-trip-not-covering"),
    # p2nit#1 (critic c06): a record of another mode than the trip's, its counts and its cut those of the set, covers nothing
    ("dry-trip-a-status", lambda rig: payload(rig, lambda r: r.update(mode="status")), "dry-trip-not-covering"),
    ("dry-trip-no-mode", lambda rig: payload(rig, lambda r: r.pop("mode")), "dry-trip-not-covering"),
    ("dry-trip-fewer-certificates", lambda rig: payload(rig, lambda r: r["counts"].update(certificates=2)), "dry-trip-not-covering"),
    ("dry-trip-fewer-client-ids", lambda rig: payload(rig, lambda r: r["counts"].update(client_ids=2)), "dry-trip-not-covering"),
    ("dry-trip-more-certificates", lambda rig: payload(rig, lambda r: r["counts"].update(certificates=4)), "dry-trip-not-covering"),
    ("dry-trip-more-client-ids", lambda rig: payload(rig, lambda r: r["counts"].update(client_ids=4)), "dry-trip-not-covering"),
    ("dry-trip-more-policies", lambda rig: payload(rig, lambda r: r["counts"].update(policies=4)), "dry-trip-not-covering"),
    ("dry-trip-no-record", lambda rig: (rig.state / "replies" / "payload-dry-trip.json").write_text("no record", encoding="utf-8"),
     "dry-trip-not-covering"),
    ("dry-trip-stale", lambda rig: mark(rig, "dry-trip", "stale"), "dry-trip-not-covering"),
    # verify#14: status's proof holds function-status `done`, and so does the pre (a set change takes it back with the rest)
    ("function-status-stale", lambda rig: mark(rig, "function-status", "stale"), "function-status-not-done"),
]


def payload(rig: Rig, change: Any) -> None:
    path = rig.state / "replies" / "payload-dry-trip.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    change(record)
    path.write_text(json.dumps(record), encoding="utf-8")


@pytest.mark.parametrize("change, name", [p[1:] for p in PRE], ids=[p[0] for p in PRE])
def test_each_check_of_fleet_actives_pre_is_refused_by_its_own_name_and_nothing_is_sent(both: Rig, change: Any, name: str) -> None:
    digest = both.shown("apply", "fleet-active-2")
    change(both)
    since = len(both.log())
    ran = both.run("apply", "fleet-active-2", "--approve", "fleet-active-2:" + digest, expect=1)
    assert "refused: %s:" % name in ran.err and both.writes(since) == []
    assert both.account()["certs"][cert_of(both, 2)]["status"] == "INACTIVE"


PRE_3: List[Any] = [
    ("an-alarm-in-alarm", lambda rig: rig.edit(lambda a: a["alarms"]["%s-bytes" % tc.PREFIX].update(StateValue="ALARM")), "breaker-not-armed"),
    ("an-alarm-disabled", lambda rig: rig.edit(lambda a: a["alarms"]["%s-shadow" % tc.PREFIX].update(ActionsEnabled=False)), "breaker-not-armed"),
    ("policy-detached", lambda rig: rig.edit(lambda a: a["certs"][cert_of(rig, 3)].update(policies=[])), "fleet-not-attached"),
    ("thing-not-exclusive", lambda rig: rig.edit(lambda a: a["things"][THINGS[3]]["principals"].update(
        {arn(cert_of(rig, 3)): "NON_EXCLUSIVE_THING"})), "fleet-not-attached"),
    ("environment-not-the-sets", lambda rig: rig.edit(lambda a: a["functions"][FUNCTION]["config"]["Environment"]["Variables"].update(
        TWIN_POLICY=POLICY)), "function-not-the-sets"),
    ("time-out-not-the-sets", lambda rig: rig.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=30)), "function-not-the-sets"),
    ("code-not-the-recorded-zip", lambda rig: rig.edit(lambda a: a["functions"][FUNCTION]["config"].update(
        CodeSha256=uc.code_of(b"code nobody built"))), "function-not-the-sets"),
    ("updating", lambda rig: tc.set_status(rig, "function", "updating"), "still-updating"),
    ("role-differs", lambda rig: rig.edit(lambda a: a["roles"][tc.ROLES["breaker-role"]]["policies"][tc.ROLES["breaker-role"] + "-policy"]
                                          ["Statement"].pop()), "breaker-role-not-rendered"),
    ("dry-trip-one-name", lambda rig: payload(rig, lambda r: r["counts"].pop("policies")), "dry-trip-not-covering"),
    ("dry-trip-not-cut", lambda rig: payload(rig, lambda r: r.update(cut=False)), "dry-trip-not-covering"),
    ("dry-trip-cut-a-number", lambda rig: payload(rig, lambda r: r.update(cut=1)), "dry-trip-not-covering"),
    ("dry-trip-a-status", lambda rig: payload(rig, lambda r: r.update(mode="status")), "dry-trip-not-covering"),
    ("dry-trip-no-mode", lambda rig: payload(rig, lambda r: r.pop("mode")), "dry-trip-not-covering"),
    ("dry-trip-fewer-certificates", lambda rig: payload(rig, lambda r: r["counts"].update(certificates=2)), "dry-trip-not-covering"),
    ("dry-trip-fewer-client-ids", lambda rig: payload(rig, lambda r: r["counts"].update(client_ids=2)), "dry-trip-not-covering"),
    ("dry-trip-more-certificates", lambda rig: payload(rig, lambda r: r["counts"].update(certificates=4)), "dry-trip-not-covering"),
    ("dry-trip-more-client-ids", lambda rig: payload(rig, lambda r: r["counts"].update(client_ids=4)), "dry-trip-not-covering"),
    ("dry-trip-more-policies", lambda rig: payload(rig, lambda r: r["counts"].update(policies=4)), "dry-trip-not-covering"),
    ("dry-trip-no-record", lambda rig: (rig.state / "replies" / "payload-dry-trip.json").write_text("no record", encoding="utf-8"),
     "dry-trip-not-covering"),
    ("dry-trip-stale", lambda rig: mark(rig, "dry-trip", "stale"), "dry-trip-not-covering"),
    ("function-status-stale", lambda rig: mark(rig, "function-status", "stale"), "function-status-not-done"),
]


@pytest.mark.parametrize("change, name", [p[1:] for p in PRE_3], ids=["car3-" + p[0] for p in PRE_3])
def test_each_check_of_fleet_actives_pre_is_refused_by_its_own_name_for_car_3_and_nothing_is_sent(both: Rig, change: Any, name: str) -> None:
    digest = both.shown("apply", "fleet-active-3")
    change(both)
    since = len(both.log())
    ran = both.run("apply", "fleet-active-3", "--approve", "fleet-active-3:" + digest, expect=1)
    assert "refused: %s:" % name in ran.err and both.writes(since) == []
    assert both.account()["certs"][cert_of(both, 3)]["status"] == "INACTIVE"


def test_fleet_active_is_refused_code_first_while_a_code_update_is_due(both: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    digest = both.shown("apply", "fleet-active-2")
    edited_source(both, monkeypatch, tmp_path)
    since = len(both.log())
    ran = both.run("apply", "fleet-active-2", "--approve", "fleet-active-2:" + digest, expect=1)
    assert "refused: code-first:" in ran.err and both.writes(since) == []


@pytest.mark.parametrize("need", ["reattach-policy", "fleet-attachments-2"])
def test_fleet_active_stands_on_reattach_policy_and_its_cars_attachments(both: Rig, need: str) -> None:
    mark(both, need, "stale" if need == "reattach-policy" else "unverified")
    since = len(both.log())
    ran = both.go("apply", "fleet-active-2", expect=1)
    assert "refused: step-needs:" in ran.err and need in ran.err and both.writes(since) == []


def test_fleet_inactive_is_never_refused_by_an_unsettled_update_an_active_certificate_a_code_update_due_or_a_stale_record(
        live: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    edited_source(live, monkeypatch, tmp_path)
    tc.set_status(live, "function", "updating")
    for step in RERUN + ["breaker-role", "fleet-active-2", "fleet-active-3"]:
        mark(live, step, "stale")
    assert live.account()["certs"][cert_of(live, 3)]["status"] == "ACTIVE"
    since = len(live.log())
    live.go("apply", "fleet-inactive-2")
    assert live.writes(since) == [["iot", "update-certificate", "--certificate-id", cert_of(live, 2), "--new-status", "INACTIVE"]]
    live.go("apply", "fleet-inactive-3")
    assert all(live.account()["certs"][cert_of(live, k)]["status"] == "INACTIVE" for k in (2, 3))


# ================================================================================================= status

def test_status_with_the_set_covered_and_both_fleet_certificates_active_fails_nothing(live: Rig) -> None:
    ran = live.run("status", expect=0)
    for k in (2, 3):
        assert "active: a fleet session (`twinctl apply fleet-inactive-%d` ends it)" % k in ran.out
        assert "traffic: car %d's certificate is ACTIVE; its policy is attached; its thing is attached (exclusive)" % k in ran.out
    assert "ok: the function's environment names exactly the twin's 3 certificate(s)" in ran.out
    assert "ok: the function's client ids and policies are the set's, paired by position" in ran.out
    assert "ok: the function's time-out holds the count of its lists" in ran.out
    assert not tc.clean(ran.text)


PROOFS: List[Any] = [
    ("fleet-active-2", "fleet-active-2"), ("function-status", "function-status"), ("dry-trip", "dry-trip"),
    ("an-alarm-test", "alarm-test-shadow"), ("reattach-policy", "reattach-policy")] + [("alarm-test-" + k, "alarm-test-" + k) for k in tc.BREAKER]


@pytest.mark.parametrize("step", [p[1] for p in PROOFS], ids=[p[0] for p in PROOFS])
def test_a_set_cars_active_certificate_fails_status_once_a_record_of_the_proof_is_taken_back(live: Rig, step: str) -> None:
    mark(live, step, "stale")
    ran = live.run("status", expect=1)
    assert "FAIL: a fleet certificate is ACTIVE and the breaker's proof is taken back: `twinctl apply fleet-inactive-2`" in ran.err


def test_a_set_cars_active_certificate_fails_status_after_update_code(live: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "the-source" / "breaker.py"
    source.parent.mkdir()
    source.write_bytes(uc.NEW_SOURCE)
    monkeypatch.setattr(TW, "BREAKER_SOURCE", source)
    uc.edited(live, tmp_path)
    with_fleet(live)
    uc.granted(live)
    uc.approve(live, uc.shown(live), 0)                              # no refusal: update-code is not held to the fleet
    ran = live.run("status", expect=1)
    for k in (2, 3):
        assert "FAIL: a fleet certificate is ACTIVE and the breaker's proof is taken back: `twinctl apply fleet-inactive-%d`" % k in ran.err


def test_a_set_cars_active_certificate_fails_status_when_the_role_reads_otherwise(live: Rig) -> None:
    live.edit(lambda a: a["roles"][tc.ROLES["breaker-role"]]["policies"][tc.ROLES["breaker-role"] + "-policy"]["Statement"].pop())
    ran = live.run("status", expect=1)
    assert "FAIL: a fleet certificate is ACTIVE and the breaker's proof is taken back: `twinctl apply fleet-inactive-2`" in ran.err


def test_a_set_cars_active_certificate_fails_status_after_a_set_change(both: Rig) -> None:
    both.go("apply", "fleet-active-2")
    both.go("apply", "fleet-inactive-2")
    both.go("teardown", "fleet-attachments-3")                      # the set changed: fleet-active-2's record is taken back
    set_cert(both, cert_of(both, 2), "ACTIVE")                      # and car B's certificate is ACTIVE by hand
    ran = both.run("status", expect=1)
    assert "FAIL: a fleet certificate is ACTIVE and the breaker's proof is taken back: `twinctl apply fleet-inactive-2`" in ran.err


def test_a_made_fleet_certificate_outside_the_set_fails_status_when_active(both: Rig) -> None:
    both.go("teardown", "fleet-attachments-3")
    set_cert(both, cert_of(both, 3), "ACTIVE")
    ran = both.run("status", expect=1)
    assert any("ACTIVE certificate(s) of the account are outside" in line for line in fails(ran))


def test_a_trip_that_leaves_a_set_cars_certificate_active_fails_its_own_status(live: Rig) -> None:
    """verify#15: a `twinctl trip` that ends in a function error prints its status before the dry trip's record is taken back; that
    status called a set car's ACTIVE certificate "a fleet session". A trip's status is its proof: a set car's certificate still ACTIVE
    after it is the cut that did not reach it, and FAILs there."""
    live.edit(lambda a: a.update(function_faults=[{"op": "update_certificate", "ignored": True, "times": 3}]))
    ran = live.run("trip", expect=1)
    assert "a fleet session" not in ran.text
    for k in (2, 3):
        assert live.account()["certs"][cert_of(live, k)]["status"] == "ACTIVE"
        assert ("FAIL: car %d's certificate is still ACTIVE after the trip: the cut did not reach it. Its three calls by hand (the "
                "trip's file), then `twinctl status`" % k) in ran.err
    assert status_of(live, "dry-trip") == "stale"                   # and the dry trip's record is taken back, as before
    ran = live.run("status", expect=1)
    assert "FAIL: a fleet certificate is ACTIVE and the breaker's proof is taken back: `twinctl apply fleet-inactive-2`" in ran.err


@pytest.mark.parametrize("change", ["in-alarm", "actions-disabled", "missing"])
def test_a_set_cars_active_certificate_fails_status_while_a_breaker_alarm_is_not_armed(live: Rig, change: str) -> None:
    """verify#15 (an alarm's own invoke that did not cut is not seen by twinctl): status's proof holds what fleet-active-k's pre held
    first, every breaker alarm there, not in ALARM, with its actions enabled. While one is not, a set car's ACTIVE certificate FAILs."""
    alarm = "%s-bytes" % tc.PREFIX
    live.edit(lambda a: a["alarms"][alarm].update(StateValue="ALARM") if change == "in-alarm" else
              a["alarms"][alarm].update(ActionsEnabled=False) if change == "actions-disabled" else a["alarms"].pop(alarm))
    ran = live.run("status", expect=1)
    assert "a fleet session" not in ran.out
    for k in (2, 3):
        assert "FAIL: a fleet certificate is ACTIVE and the breaker's proof is taken back: `twinctl apply fleet-inactive-%d`" % k in ran.err


LISTS: List[Any] = [
    ("policies-crossed", lambda v: v.update(TWIN_POLICY=",".join([POLICY, POLICIES[3], POLICIES[2]])), "paired by position"),
    ("one-policy-name", lambda v: v.update(TWIN_POLICY=POLICY), "paired by position"),
    ("a-client-id-short", lambda v: v.update(TWIN_CLIENT_IDS=",".join([tc.THING, THINGS[2]])), "client ids"),
    ("a-certificate-short", lambda v: v.update(TWIN_CERTIFICATE_ARNS=v["TWIN_CERTIFICATE_ARNS"].rsplit(",", 1)[0]), "exactly the twin's"),
]


@pytest.mark.parametrize("change, said", [c[1:] for c in LISTS], ids=[c[0] for c in LISTS])
def test_status_fails_unless_the_functions_lists_are_exactly_the_sets_paired_by_position(both: Rig, change: Any, said: str) -> None:
    both.edit(lambda a: change(a["functions"][FUNCTION]["config"]["Environment"]["Variables"]))
    ran = both.run("status", expect=1)
    assert any(said in line for line in fails(ran)), ran.err


def test_status_fails_when_the_functions_time_out_is_under_the_count_of_its_own_lists(both: Rig, made: Rig, tmp_path: Path) -> None:
    both.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=41))       # three cars: counted at 42 s
    ran = both.run("status", expect=1)
    assert any("time-out" in line and "under the count" in line for line in fails(ran))
    both.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=42))
    assert not [line for line in fails(both.run("status")) if "time-out" in line]
    # with no fleet key it runs too, and prints only on a failure
    plain = made.copy(tmp_path / "plain")
    ran = plain.run("status", expect=0)
    assert "time-out" not in ran.text and "client ids" not in ran.text
    plain.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=21))      # one car: counted at 22 s
    ran = plain.run("status", expect=1)
    assert any("time-out" in line for line in fails(ran))
    plain.edit(lambda a: a["functions"][FUNCTION]["config"].update(Timeout=30))
    plain.edit(lambda a: a["functions"][FUNCTION]["config"]["Environment"]["Variables"].update(TWIN_CLIENT_IDS="x" + tc.THING))
    assert any("client ids" in line for line in fails(plain.run("status", expect=1)))


def test_between_a_join_and_update_config_assertion_one_fails_and_the_function_line_says_why(twin: Rig) -> None:
    join(twin, 2)
    ran = twin.run("status", expect=1)
    assert any("not exactly the twin's" in line for line in fails(ran))
    line = tc.status_lines(ran)["function"]
    assert "DIFFERS" in line and "`twinctl update-config function`" in line


# ================================================================================================= restore, go-live, the stop

def test_restore_gives_the_twins_three_calls_and_one_attach_for_each_set_car_and_never_makes_a_fleet_certificate_active(both: Rig) -> None:
    since = len(both.log())
    ran = both.run("restore", expect=0)
    assert both.writes(since) == []
    calls = [line.split()[2:4] for line in ran.out.split("\n") if line.startswith("  run: ")]
    assert calls == [["iot", "attach-policy"], ["iot", "update-certificate"], ["iot", "enable-topic-rule"], ["iot", "attach-policy"],
                     ["iot", "attach-policy"]]
    runs = [line for line in ran.out.split("\n") if line.startswith("  run: ")]
    assert "--new-status ACTIVE" in runs[1] and not [r for r in runs if "ACTIVE" in r and r is not runs[1]]
    assert "these three, each read before the next" in ran.out and "and one call for each fleet car of the set" in ran.out
    text = (both.render / "restore.txt").read_text(encoding="utf-8")
    assert text.count("--new-status ACTIVE") == 1


def test_restore_and_go_live_are_refused_while_the_function_names_what_is_gone(both: Rig) -> None:
    both.edit(lambda a: a["policies"].pop(POLICIES[3]))
    ran = both.run("restore", expect=1)
    assert "refused: fleet-named-gone:" in ran.err and "aws " not in ran.out
    since = len(both.log())
    ran = both.go("apply", "go-live-rule", expect=1)
    assert "refused: fleet-named-gone:" in ran.err and both.writes(since) == []


def test_with_no_fleet_key_restore_and_the_stops_lines_are_todays(made: Rig, tmp_path: Path) -> None:
    plain = made.copy(tmp_path / "plain")
    plain.run("trip")
    ran = plain.run("restore", expect=0)
    assert "fleet" not in ran.text
    lines, comments = tc.by_hand(plain)
    assert len(lines) == 4 and not [c for c in comments if "fleet" in c]


def test_the_stops_file_holds_three_calls_for_each_fleet_car_whose_certificate_the_state_records(both: Rig) -> None:
    ran = both.run("trip")
    lines, comments = tc.by_hand(both)
    assert len(lines) == 4 + 3 * 2
    assert "and three calls for each fleet car" in "\n".join(comments) and "and three calls for each fleet car" in ran.text
    for k in (2, 3):
        cert = cert_of(both, k)
        car = [x for x in lines if cert in x or THINGS[k] in x]
        assert [x.split()[1:3] for x in car] == [["iot", "update-certificate"], ["iot-data", "delete-connection"], ["iot", "detach-policy"]]
        assert "--new-status INACTIVE" in car[0] and "--client-id %s" % THINGS[k] in car[1]
        assert "--policy-name %s --target %s" % (POLICIES[k], arn(cert)) in car[2]
    assert not tc.clean(ran.text)


def test_the_stops_file_for_one_fleet_car(twin: Rig) -> None:
    for step in ("fleet-thing-2", "fleet-certificate-2"):
        twin.go("apply", step)
    twin.run("trip")
    lines, _comments = tc.by_hand(twin)
    assert len(lines) == 4 + 3


def test_the_stops_file_leaves_a_fleet_thing_the_names_file_does_not_give_as_a_commented_slot(both: Rig) -> None:
    both.extra.pop("TWIN_FLEET_THING_3")
    both.extra.pop("TWIN_FLEET_CSR_3")
    both.extra.pop("TWIN_FLEET_CERTIFICATE_OUT_3")
    both.run("trip")
    lines, comments = tc.by_hand(both)
    assert len(lines) == 4 + 3 + 2                                  # car C's delete-connection is a comment: its thing is not given
    assert any(c.startswith("# NOT FILLED IN (<FLEET_THING_3>)") and "delete-connection" in c for c in comments)
    assert any("TWIN_FLEET_THING_3" in c for c in comments)


@pytest.mark.parametrize("how", ["names-not-the-states", "salt-gone", "state-unreadable"])
def test_the_stops_file_keeps_each_fleet_cars_calls_with_its_certificate_as_a_slot_when_the_state_is_not_comparable(both: Rig,
                                                                                                                  how: str) -> None:
    """fable#1, verify#3 (the calls-by-hand rule): where the state's names cannot be compared with the names file's (another TWIN_THING,
    the salt gone) or the state cannot be read, the twin's own certificate stays a commented slot with its reason; so does each fleet
    car's, and its three calls stay in the file with the head line, the thing filled from the names file, and the read that finds the
    id. Before, the fleet's calls were dropped without a word."""
    certs = {k: cert_of(both, k) for k in (2, 3)}
    env: Dict[str, str] = {}
    if how == "names-not-the-states":
        env["TWIN_THING"] = tc.j(tc.PREFIX, "-thing-other")
    elif how == "salt-gone":
        (both.state / "salt").unlink()
    else:
        (both.state / "state.json").write_text("no state of this version\n", encoding="utf-8")
    ran = both.run("trip", env=env)
    lines, comments = tc.by_hand(both)
    text = "\n".join(lines + comments)
    assert TW.FLEET_HEAD in comments and "and three calls for each fleet car" in ran.out
    assert any(x.startswith("# NOT FILLED IN (<CERT_ID>): aws iot update-certificate") for x in comments)   # the twin's own, as before
    for k in (2, 3):
        assert certs[k] not in text                                 # the id is not put beside these names
        slot, arn_slot = "<FLEET_CERT_ID_%d>" % k, "<car %d's certificate's ARN>" % k
        assert "# NOT FILLED IN (%s): aws iot update-certificate --certificate-id %s --new-status INACTIVE" % (slot, slot) in text
        assert [x for x in lines if x.startswith("aws iot-data delete-connection --client-id %s " % THINGS[k])]
        assert "# NOT FILLED IN (%s): aws iot detach-policy --policy-name %s --target %s" % (arn_slot, POLICIES[k], arn_slot) in text
        assert any(c.startswith("#   %s: fleet_certificate_id_%d, a fact of the state: " % (slot, k)) for c in comments), comments
        assert any(c.startswith("#   aws iot list-targets-for-policy --policy-name %s " % POLICIES[k]) for c in comments), comments
    assert "NOT FILLED IN there: <FLEET_CERT_ID_2>: fleet_certificate_id_2" in ran.err and not tc.clean(ran.text)


def test_trip_is_held_to_the_account_only_and_not_to_a_fleet_key(both: Rig) -> None:
    both.extra["TWIN_FLEET_THING_2"] = tc.j(tc.PREFIX, "-car-renamed")
    since = len(both.log())
    both.run("trip")
    assert [c[:2] for c in both.writes(since)][:1] == [["lambda", "invoke"]]


def test_a_car_whose_steps_are_on_record_stays_in_the_table_without_its_key(both: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """p2nit#6 (critic c18): a car is in the table while its key is given, and whatever the names file says once the state
    records one of its steps. With the six fleet keys taken out, a stop (the one command the binding does not refuse then) still
    lists both cars' steps."""
    for k in TW.FLEET_CARS:
        for key in ("TWIN_FLEET_THING_%d", "TWIN_FLEET_CSR_%d", "TWIN_FLEET_CERTIFICATE_OUT_%d"):
            both.extra.pop(key % k)
    since = len(both.log())
    ran = both.run("trip")
    assert [c[:2] for c in both.writes(since)][:1] == [["lambda", "invoke"]], ran.text
    lines = tc.status_lines(ran)
    assert "fleet-thing-2" in lines and "fleet-attachments-3" in lines, sorted(lines)
    no_twin_variables(monkeypatch)
    assert TW.Twin(both.state, None, False, stop=True).fleet_cars == [2, 3]
    edit_state(both, lambda s: [s["steps"][step].update(status="deleted") for step in TW.fleet_steps(3) if step in s["steps"]])
    assert TW.Twin(both.state, None, False, stop=True).fleet_cars == [2], "car 3's steps all deleted, its key not given: out of the table"


# ================================================================================================= teardown: fleet-still-covered

def test_a_fleet_policy_or_certificate_the_functions_environment_names_is_not_torn_down_unless_the_twin_reads_as_cut(both: Rig) -> None:
    both.edit(lambda a: a["rules"][RULE].update(ruleDisabled=False))            # not read as cut: the rule is enabled
    both.go("teardown", "fleet-attachments-3")
    for step in ("fleet-policy-3", "fleet-certificate-3"):          # the table in reverse
        since = len(both.log())
        ran = both.go("teardown", step, expect=1)
        assert "refused: fleet-still-covered:" in ran.err and both.writes(since) == [], step
        both.edit(lambda a: a["rules"][RULE].update(ruleDisabled=True))         # read as cut: waived
        both.go("teardown", step)
        both.edit(lambda a: a["rules"][RULE].update(ruleDisabled=False))
    assert POLICIES[3] not in both.account()["policies"] and cert_of(both, 3) not in both.account()["certs"]


def test_the_waiver_is_read_and_never_taken_from_the_states_record(both: Rig) -> None:
    both.go("teardown", "fleet-attachments-3")
    # the state records the twin as cut (its go-live steps deleted), and the account reads otherwise: one certificate ACTIVE
    for step in ("go-live-certificate", "go-live-rule"):
        mark(both, step, "deleted")
    both.edit(lambda a: a["certs"][tc.CERT_1].update(status="ACTIVE"))
    ran = both.go("teardown", "fleet-policy-3", expect=1)
    assert "refused: fleet-still-covered:" in ran.err


# ================================================================================================= literals, exit-checks, plan

def test_literals_take_the_fleets_things_and_its_certificates_ids(both: Rig) -> None:
    literals = json.loads((both.state / "literals.json").read_text(encoding="utf-8"))["literals"]
    assert sorted(literals["fleet-thing"]) == sorted(THINGS.values())
    assert {cert_of(both, 2), cert_of(both, 3)} <= set(literals["certificate-id"])
    assert "fleet-thing" in TW.OWN_KINDS
    ran = both.run("status")
    for value in list(THINGS.values()) + [cert_of(both, 2)]:
        assert value not in ran.text


def test_exit_checks_reads_the_shadows_of_each_car_whose_thing_is_on_record(both: Rig, tmp_path: Path) -> None:
    def rows(rig: Rig, name: str) -> Dict[str, Any]:
        rig.run("exit-checks", "--capture", tmp_path / name)
        doc = json.loads((tmp_path / name / "exit-checks.json").read_text(encoding="utf-8"))
        return {c["check"]: c for c in doc["checks"]}

    found = rows(both, "a")
    for k in (2, 3):
        row = found["S11: the shadows' keys of fleet car %d" % k]
        assert row["result"] == "pass" and row["shape"]["named_shadows"] == 0      # no shadow yet, no fleet-active-k run: no failure
    # a run of fleet-active-2 on record: its "at least one vss key" part applies
    both.go("apply", "fleet-active-2")
    both.go("apply", "fleet-inactive-2")
    assert rows(both, "b")["S11: the shadows' keys of fleet car 2"]["result"] == "FAIL"
    vss = {"state": {"reported": {sorted(TW._allowlist()[1])[0]: 1.0}}}                    # a key of the allowlist
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].update({"vss": vss}))
    assert rows(both, "c")["S11: the shadows' keys of fleet car 2"]["result"] == "pass"
    # p2nit#4 (critic c15): a config shadow's path outside the allowlist, and outside the excluded branch, fails the car's row
    assert "config" not in both.account()["things"][THINGS[2]]["shadows"]
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].update({"config": {"state": {"reported": {"paths": ["Vehicle.NotOnTheAllowlist"]}}}}))
    row = rows(both, "c1")["S11: the shadows' keys of fleet car 2"]
    assert row["result"] == "FAIL" and row["shape"]["outside_the_allowlist"] == 1 and row["shape"]["under_the_excluded_branch"] == 0, row
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"]["config"]["state"]["reported"].update(paths=[TW._monitor_prefix() + "Anything"]))
    row = rows(both, "c1b")["S11: the shadows' keys of fleet car 2"]
    assert row["result"] == "FAIL" and row["shape"]["under_the_excluded_branch"] == 1, row
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].pop("config"))
    # the thing made again after that run: its vss part does not apply until a run on the new making
    made = tc.state_of(both)["steps"]["fleet-thing-2"]["made"]
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].pop("vss"))
    edit_state(both, lambda st: st["steps"]["fleet-thing-2"].update(made="a-later-making"))
    assert rows(both, "c2")["S11: the shadows' keys of fleet car 2"]["result"] == "pass"
    edit_state(both, lambda st: st["steps"]["fleet-thing-2"].update(made=made))
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].update({"vss": vss}))
    # a car that left the set keeps its row; a car whose thing is gone has none
    both.go("teardown", "fleet-attachments-3")
    assert "S11: the shadows' keys of fleet car 3" in rows(both, "d")
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].update({"vss": {"state": {"reported": {"Monitor.Anything": 1}}}}))
    assert rows(both, "e")["S11: the shadows' keys of fleet car 2"]["result"] == "FAIL"
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].update({"vss": {"state": {"reported": {TW._monitor_prefix() + "Anything": 1}}}}))
    row = rows(both, "e2")["S11: the shadows' keys of fleet car 2"]
    assert row["result"] == "FAIL" and row["shape"]["under_the_excluded_branch"] == 1, row
    under = [TW._monitor_prefix() + "Other", TW._monitor_prefix() + "More"]
    both.edit(lambda a: a["things"][THINGS[2]]["shadows"].update({"config": {"state": {"reported": {"paths": under}}}}))
    row = rows(both, "e3")["S11: the shadows' keys of fleet car 2"]
    assert row["result"] == "FAIL" and row["shape"]["under_the_excluded_branch"] == 3, row


def test_plan_renders_every_fleet_step_and_update_config_and_holds_the_operator_policy_to_them(both: Rig) -> None:
    ran = both.run("plan", expect=0)
    assert "0 gap(s) in the operator role's policy" in ran.out
    ids = [s["id"] for s in both.plan()]
    assert "function-config" in ids and [i for i in ids if i.startswith("fleet-")] == [s % 2 for s in STEPS] + [s % 3 for s in STEPS]
    skeletons = [e["argv"][:2] for e in both.log("skeleton.jsonl")]
    assert ["lambda", "update-function-configuration"] in skeletons
    listed = {tc.sig(c) for c in tc.every_call(both)}
    assert {tc.sig(c) for c in uc.sent(both)} - listed == set()


# ================================================================================================= one whole life, in P4's order

def test_one_whole_life_in_p4s_order_then_a_cars_leaving_then_a_whole_teardown_with_no_update_config(
        made: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = made.copy(tmp_path / "life")
    # before the session: the source edited and built (a code update due), the six keys set, an offline plan
    edited_source(rig, monkeypatch, tmp_path)
    with_fleet(rig)
    rig.run("plan", "--no-cli", expect=0)
    # 0: the owner remakes the operator role from its render, which holds both update grants
    statement = [s for s in rig.doc("operator-role", "operator-role-policy")["Statement"] if s["Sid"] == "Function"][0]
    assert {uc.UPDATE, CONFIG_ACTION} <= set(statement["Action"])
    uc.granted(rig)
    # 1b: a trip on the old code: the twin is cut before its guard changes
    rig.run("trip", expect=0)
    # 2: update-code carries the new code, on the one-car environment; then function-status
    uc.approve(rig, uc.shown(rig), 0)
    rig.go("apply", "function-status")
    # 3: the cars join; from here assertion 1 fails until update-config
    join(rig, 2)
    join(rig, 3)
    assert fails(rig.run("status", expect=1))
    # 4: the breaker role remade; 5: update-config
    remake_role(rig)
    configure(rig)
    # 6: function-status, the dry trip, the alarm tests, reattach-policy, then restore's calls by hand
    rerun(rig)
    restore = rig.run("restore", expect=0)
    assert "and one call for each fleet car of the set" in restore.out
    # 7: status: both assertions ok
    assert not fails(rig.run("status", expect=0))
    # 8: the fleet certificates ACTIVE; 9: INACTIVE again
    rig.go("apply", "fleet-active-2")
    rig.go("apply", "fleet-active-3")
    assert not fails(rig.run("status", expect=0))
    rig.go("apply", "fleet-inactive-2")
    rig.go("apply", "fleet-inactive-3")
    assert not fails(rig.run("status", expect=0))
    # a car's leaving: car C's attachments, update-config on the wider role, the role narrowed, the breaker run again
    rig.go("teardown", "fleet-attachments-3")
    configure(rig)
    remake_role(rig)
    rerun(rig)
    for step in ("fleet-policy-3", "fleet-certificate-3", "fleet-thing-3"):
        rig.go("teardown", step)
    assert not fails(rig.run("status", expect=0))
    # the whole teardown, S10's last resort: a trip, then car B's steps with the waivers, no IAM change and no update-config
    rig.run("trip")
    for step in ("fleet-attachments-2", "fleet-policy-2", "fleet-certificate-2", "fleet-thing-2"):
        rig.go("teardown", step)
    assert [s for s in TW.Twin(rig.state, None, False).standing() if s.startswith("fleet-")] == []
    assert [w for w in rig.writes() if w[:2] == ["lambda", "update-function-configuration"]] and len(
        [w for w in rig.writes() if w[:2] == ["lambda", "update-function-configuration"]]) == 2
    # with the fleet gone the function still names car B: restore and go-live are refused until a new configuration, or the whole teardown
    assert "refused: fleet-named-gone:" in rig.run("restore", expect=1).err
    assert not tc.clean("".join(r.text for r in rig.said))


# What CLI 2.35.1 said offline of `lambda update-function-configuration`, given --generate-cli-skeleton output (v3-p2-core's probe,
# 2026-11-15, made as the breaker update's cli-probe: a made-up function name, documentation values, no credential, the closed
# port): the CLI's own sample reply failing its own validation. Lines end in LF here (the capture's CRLF dropped).
UPDATE_FUNCTION_CONFIGURATION_SAID = (
    "\n"
    "aws: [ERROR]: An error occurred (ParamValidation): Parameter validation failed:\n"
    "Invalid value for parameter Timeout, value: 0, valid min value: 1\n"
    "Invalid value for parameter MemorySize, value: 0, valid min value: 128\n"
    "Invalid value for parameter EphemeralStorage.Size, value: 0, valid min value: 512\n"
    "Invalid length for parameter RuntimeVersionConfig.RuntimeVersionArn, value: 17, valid min length: 26\n"
    "Invalid value for parameter CapacityProviderConfig.LambdaManagedInstancesCapacityProviderConfig.PerE"
    "xecutionEnvironmentMaxConcurrency, value: 0, valid min value: 1\n"
    "Invalid value for parameter CapacityProviderConfig.LambdaManagedInstancesCapacityProviderConfig.Exec"
    "utionEnvironmentMemoryGiBPerVCpu, value: 0.0, valid min value: 2.0\n"
    "Invalid value for parameter DurableConfig.RetentionPeriodInDays, value: 0, valid min value: 1\n"
    "Invalid value for parameter DurableConfig.ExecutionTimeout, value: 0, valid min value: 1\n"
)


def test_the_real_clis_offline_reading_of_the_configuration_update_is_placed_as_its_own_sample_failing(
        twin: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The text was captured offline from CLI 2.35.1 (v3-p2-core's probe). The call is update-config's step's own (its Built), with
    the function's name made up: the driver places that reading as the sample's, so `plan` reads it `read, sample fails`, and a
    time-out the call gives that is the sample's own figure would be the call's own refusal. The real service's answer is not covered."""
    for k in [k for k in os.environ if k.startswith(("TWIN_", "AWS_")) or k == "STUB_AWS_DIR"]:
        monkeypatch.delenv(k)
    built = TW.Twin(twin.state, None, False).render(TW.FUNCTION_CONFIG).built
    assert [c.op for c in built.creates] == ["update-function-configuration", "wait"]
    call = built.creates[0]
    call = TW.Call(call.service, call.op, tuple("twin-breaker-made-up-0000" if a == FUNCTION else a for a in call.args), call.write)
    assert "twin-breaker-made-up-0000" in call.args and "--timeout" in call.args
    assert TW.sample_only(call, UPDATE_FUNCTION_CONFIGURATION_SAID) is True
    zero = TW.Call(call.service, call.op, tuple("0" if a == "30" else a for a in call.args), call.write)
    assert TW.sample_only(zero, UPDATE_FUNCTION_CONFIGURATION_SAID) is False


def test_a_standing_fleet_attachment_read_again_is_no_set_change(both: Rig) -> None:
    """`apply fleet-attachments-k` on a step that stands reads it again and changes no set: no set change's refusal, no take-back."""
    set_cert(both, cert_of(both, 2), "ACTIVE")
    since = len(both.log())
    ran = both.go("apply", "fleet-attachments-3")
    assert "already made, nothing was created" in ran.out and both.writes(since) == [] and "the breaker's set changed" not in ran.out
    assert status_of(both, "reattach-policy") == "done"


def test_a_stop_is_not_refused_by_a_fleet_keys_fault(made: Rig, tmp_path: Path) -> None:
    """The stop is held to the account only: a fleet key's fault is said, the fleet's things are left out, and the invoke goes; every
    other command is refused by the key."""
    rig = made.copy(tmp_path / "stop")
    rig.extra["TWIN_FLEET_THING_3"] = THINGS[3]                     # car C without car B
    assert "refused: names-invalid:" in rig.run("status", expect=1).err
    since = len(rig.log())
    ran = rig.run("trip")
    assert [c[:2] for c in rig.writes(since)][:1] == [["lambda", "invoke"]]
    assert "fleet things are not taken" in ran.err and "TWIN_FLEET_THING_3" in ran.err and THINGS[3] not in ran.text


@pytest.mark.parametrize("key, value", [("TWIN_FLEET_THING_2", "car-zz2"), ("TWIN_FLEET_THING_3", tc.j(tc.PREFIX, "-car c")),
                                        ("TWIN_FLEET_CSR_2", "a\x01path")], ids=["seven-characters", "a-space", "a-control-character"])
def test_a_stop_is_not_refused_by_a_fleet_key_that_has_not_its_form(made: Rig, tmp_path: Path, key: str, value: str) -> None:
    """fable#4: a fault between the fleet keys let the stop go, and a fleet key whose value has not its key's form refused it before
    its invoke. The six fleet keys are eased in a stop as STOP_NEEDS_NOT's key is: left out, said by the key, and the invoke goes;
    every other command is refused by the key, as before."""
    rig = made.copy(tmp_path / "stop")
    rig.extra[key] = value
    assert "refused: names-invalid:" in rig.run("status", expect=1).err
    since = len(rig.log())
    ran = rig.run("trip")
    assert [c[:2] for c in rig.writes(since)][:1] == [["lambda", "invoke"]]
    assert "the names file gives no usable %s (it is not given in the form twinctl takes for it): the stop needs none and goes on" % key in ran.err
    assert value not in ran.text and "refused:" not in ran.err


def test_the_readme_and_the_docstring_say_the_fleets_calls_by_hand_and_restores_in_whole_sentences() -> None:
    """verify#13: three sentences of README and one of the docstring were fragments ("With a fleet car's certificate on record, and
    three calls for each fleet car ..."). Each is a whole sentence, and no phrase a test holds moved."""
    readme = " ".join((tc.REPO / "sdv" / "cloud" / "README.md").read_text(encoding="utf-8").split())
    doc = " ".join(str(TW.__doc__).split())
    for text in (readme, doc):
        assert "certificate on record, and three calls" not in text and "certificate on record, and one call" not in text
    assert ("With a fleet car's certificate on record, the file also holds three calls for each fleet car (its certificate INACTIVE, its "
            "connection deleted, its own policy detached), by the same rule.") in readme
    assert ("With a fleet car's certificate on record, it also gives one call for each fleet car of the set, its policy attached again; "
            "it never makes a fleet certificate ACTIVE") in readme
    assert ("**`restore`** gives the twin's three calls and, with a fleet car's certificate on record, one call for each fleet car of the "
            "set (its policy attached again).") in readme
    assert ("The stop's file holds the four calls and, with a fleet car's certificate on record, three calls for each fleet car.") in readme
    assert ("With a fleet car's certificate on record (fleet P2), the file also holds three calls for each fleet car, after the four: its "
            "certificate INACTIVE, its connection deleted, its own policy detached.") in doc


DOC_WIDTH = 120                                         # THE COMMANDS' entries around the two: apply's before, status's after


def test_the_docstrings_update_code_and_update_config_entries_are_within_the_width_of_their_neighbours() -> None:
    """r2c#5's real line (NIT package 10, item 2): twinctl's module docstring, THE COMMANDS, the update-code and the update-config
    entries, from the update-code line to the status line, are wrapped to the width of the entries around them."""
    lines = str(TW.__doc__).split("\n")
    apply, start = lines.index(next(x for x in lines if x.startswith("  apply STEP "))), lines.index("  update-code function")
    end = lines.index(next(x for x in lines if x.startswith("  status ")))
    after = lines.index(next(x for x in lines if x.startswith("  trip ")))
    assert apply < start < lines.index("  update-config function") < end < after
    assert max(len(line) for line in lines[apply:start] + lines[end:after]) <= DOC_WIDTH
    wide = [(n, len(line)) for n, line in enumerate(lines[start:end], start) if len(line) > DOC_WIDTH]
    assert wide == [], wide


def test_a_trips_status_says_one_failure_when_the_sets_environment_cannot_be_rendered(both: Rig) -> None:
    """fable#5: a stop whose fleet things are not taken (car C's key without car B's), with both cars' steps on record: the set's
    environment cannot be rendered, and the trip's status said so and then printed both comparisons' FAIL lines against nothing. It
    is one failure, said once."""
    del both.extra["TWIN_FLEET_THING_2"]
    ran = both.run("trip")
    said = fails(ran)
    assert [line for line in said if "the set's environment could not be rendered" in line] == [
        "FAIL: the set's environment could not be rendered (names-missing): the function's client ids and policies are not compared "
        "with it"], said
    assert not [line for line in said if "client ids in the function's environment" in line or "policies in the function's" in line]


# ================================================================================================= verify's and the hard review's missing assertions

TEARDOWN = ("fleet-attachments-%d", "fleet-policy-%d", "fleet-certificate-%d", "fleet-thing-%d")


def test_the_functions_environment_for_three_cars_names_each_cars_certificate_client_id_and_policy_in_car_order(both: Rig) -> None:
    """fable#6: the three-car environment held by value, in car order (a set car left out of any of the lists, or the lists crossed)."""
    assert env_of(both) == {"TWIN_CERTIFICATE_ARNS": ",".join([arn(tc.CERT_1), arn(cert_of(both, 2)), arn(cert_of(both, 3))]),
                            "TWIN_CLIENT_IDS": ",".join([tc.THING, THINGS[2], THINGS[3]]), "TWIN_RULE": RULE,
                            "TWIN_POLICY": ",".join([POLICY, POLICIES[2], POLICIES[3]])}
    assert fn_config(both)["Timeout"] == 45


def test_the_whole_teardown_with_both_cars_named_needs_no_update_config(both: Rig) -> None:
    """verify#4, the whole teardown's last resort: a trip, then car C's steps and car B's in reverse while the function names both; car C's
    certificate, deleted under the waiver, is then not found, and the twin still reads as cut."""
    since = len(both.log())
    both.run("trip")
    for k in (3, 2):
        for step in TEARDOWN:
            both.go("teardown", step % k)
    assert [s for s in TW.Twin(both.state, None, False).standing() if s.startswith("fleet-")] == []
    assert not [w for w in both.writes(since) if w[:2] == ["lambda", "update-function-configuration"]]


def test_the_sets_dry_trip_detaches_each_cars_own_policy_in_the_account(both: Rig) -> None:
    """verify#5, the breaker's pairs end to end: after a dry trip on the set of three, every certificate of the set is INACTIVE and
    carries no policy (a pair crossed in the render reads as cut while each car's own policy stays attached)."""
    both.go("apply", "dry-trip")
    certs = both.account()["certs"]
    for cert in (tc.CERT_1, cert_of(both, 2), cert_of(both, 3)):
        assert certs[cert]["status"] == "INACTIVE" and certs[cert]["policies"] == [], cert
    env = env_of(both)
    pairs = list(zip(env["TWIN_CERTIFICATE_ARNS"].split(","), env["TWIN_POLICY"].split(",")))
    assert pairs == [(arn(tc.CERT_1), POLICY), (arn(cert_of(both, 2)), POLICIES[2]), (arn(cert_of(both, 3)), POLICIES[3])]


def test_restore_is_refused_while_the_function_names_a_certificate_that_is_not_found(both: Rig) -> None:
    """verify#6: fleet-named-gone's certificate half (the policy half is tested beside restore)."""
    cert = cert_of(both, 3)
    both.edit(lambda a: a["certs"].pop(cert))
    ran = both.run("restore", expect=1)
    assert "refused: fleet-named-gone:" in ran.err and "certificate that is not found" in ran.err


def test_named_gone_judges_every_certificate_the_environment_names_when_the_state_has_no_id_of_car_a(both: Rig,
                                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """p2nit#7 (verify#12, fable#8), in this process: no command reaches it. With no certificate_id in the state there is no car A's
    id to pass over, so each certificate the function's environment names is read, and car C's, not found, refuses fleet-named-gone
    (the old `or "-"` passed over every ARN, each of which holds a "-")."""
    cert = cert_of(both, 3)
    edit_state(both, lambda s: s["facts"].pop("certificate_id"))
    both.edit(lambda a: a["certs"].pop(cert))
    no_twin_variables(monkeypatch)
    for key, value in dict(both.extra, TWIN_STATE=str(both.state), STUB_AWS_DIR=str(both.stub)).items():
        monkeypatch.setenv(key, value)
    t = TW.Twin(both.state, None, False)
    t.aws.identified()                                              # reads only: the caller's read stands in a command before it
    with pytest.raises(TW.TwinError) as refused:
        TW.named_gone(t)
    assert refused.value.name == "fleet-named-gone" and "certificate that is not found" in refused.value.detail
    assert [e["argv"][:2] for e in both.log()][-1] == ["iot", "describe-certificate"]


def test_a_set_change_is_refused_while_a_made_certificate_outside_the_set_reads_active(twin: Rig) -> None:
    """verify#7: car C's certificate is made and not in the set (its attachments never joined); ACTIVE, it still stands in the way
    of car B's joining."""
    for step in ("fleet-thing-2", "fleet-certificate-2", "fleet-policy-2", "fleet-thing-3", "fleet-certificate-3"):
        twin.go("apply", step)
    set_cert(twin, cert_of(twin, 3), "ACTIVE")
    since = len(twin.log())
    ran = twin.go("apply", "fleet-attachments-2", expect=1)
    assert "refused: fleet-active-standing:" in ran.err and twin.writes(since) == []


def test_update_config_is_refused_while_a_made_certificate_outside_the_set_reads_active(joined: Rig) -> None:
    """verify#7: the same standing refusal of update-config, for a made certificate outside the set."""
    for step in ("fleet-thing-3", "fleet-certificate-3"):
        joined.go("apply", step)
    set_cert(joined, cert_of(joined, 3), "ACTIVE")
    since = len(joined.log())
    ran = configure(joined, expect=1)
    assert "refused: fleet-active-standing:" in ran.err and joined.writes(since) == []


def test_the_stops_file_leaves_a_fleet_thing_given_otherwise_than_bound_as_a_slot(both: Rig) -> None:
    """verify#8: a fleet thing the names file gives as another (prefixed) name than the state's records were bound to is no call's
    value: it stays a commented slot, and its name is in no line."""
    renamed = tc.j(tc.PREFIX, "-car-renamed")
    both.extra["TWIN_FLEET_THING_2"] = renamed
    both.run("trip")
    lines, comments = tc.by_hand(both)
    assert not [x for x in lines if renamed in x] and not [x for x in lines if "delete-connection" in x and THINGS[2] in x]
    assert any(c.startswith("# NOT FILLED IN (<FLEET_THING_2>)") and "delete-connection" in c for c in comments)


def test_a_join_on_a_twin_read_as_cut_is_still_refused_code_first(twin: Rig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """verify#9: the waiver for a twin read as cut is for a leave only."""
    twin.run("trip")
    for step in ("fleet-thing-2", "fleet-certificate-2", "fleet-policy-2"):
        twin.go("apply", step)
    edited_source(twin, monkeypatch, tmp_path)
    ran = twin.go("apply", "fleet-attachments-2", expect=1)
    assert "refused: code-first:" in ran.err


def test_the_stops_file_leaves_a_fleet_thing_without_the_prefix_as_a_slot_where_the_state_cannot_be_compared(both: Rig) -> None:
    """verify#11 (v68): with the salt gone the thing is the names file's as it stands; one that does not begin with the prefix is
    still no call's value (the commented slot says so)."""
    (both.state / "salt").unlink()
    both.extra["TWIN_FLEET_THING_2"] = "elsewhere-car-b"
    both.run("trip")
    lines, comments = tc.by_hand(both)
    assert not [x for x in lines if "elsewhere-car-b" in x]
    assert any(c.startswith("# NOT FILLED IN (<FLEET_THING_2>)") and "delete-connection" in c for c in comments)


def test_a_twin_whose_environment_names_something_that_is_no_certificate_arn_is_not_read_as_cut(both: Rig) -> None:
    """verify#11 (v12): the rule disabled and every named certificate INACTIVE, but one entry of the environment is no ARN: not cut."""
    both.run("trip")
    both.go("teardown", "fleet-attachments-3")
    listed = env_of(both)["TWIN_CERTIFICATE_ARNS"] + ",not-a-certificate-arn"
    both.edit(lambda a: a["functions"][FUNCTION]["config"]["Environment"]["Variables"].update(TWIN_CERTIFICATE_ARNS=listed))
    since = len(both.log())
    ran = both.go("teardown", "fleet-policy-3", expect=1)
    assert "refused: fleet-still-covered:" in ran.err and both.writes(since) == []


def test_restore_after_car_c_left_the_set_attaches_for_car_b_alone(both: Rig) -> None:
    """verify#11 (v44): restore attaches the policy of each car of the SET, not of each car the table has a certificate for."""
    both.go("teardown", "fleet-attachments-3")
    ran = both.run("restore", expect=0)
    runs = [line for line in ran.out.split("\n") if line.startswith("  run: ")]
    assert [r.split()[2:4] for r in runs] == [["iot", "attach-policy"], ["iot", "update-certificate"], ["iot", "enable-topic-rule"],
                                              ["iot", "attach-policy"]]
    assert "-device-2 " in runs[3] and not [r for r in runs if "-device-3" in r]               # the output is scrubbed of the prefix


def test_a_go_live_after_a_trip_says_the_restores_fleet_sentence(both: Rig) -> None:
    """verify#11 (v37): the go-live refused on a recorded-not-live twin names the restore, and its call for each fleet car."""
    both.run("trip")
    ran = both.go("apply", "go-live-rule", expect=1)
    assert "and one call for each fleet car of the set" in ran.err and "`twinctl restore`" in ran.err


def test_plan_holds_each_fleet_cars_delete_connection_and_shadow_reads_among_the_calls_outside_the_table(both: Rig) -> None:
    """verify#11 (v39): the calls no step owns, as plan lists them, hold car k's delete-connection and its get-thing-shadow reads."""
    both.run("plan", expect=0)
    other = json.loads((both.render / "plan.json").read_text(encoding="utf-8"))["other"]
    for k in (2, 3):
        assert [c for c in other["creates"] if c[:2] == ["iot-data", "delete-connection"] and THINGS[k] in c], k
        assert [c for c in other["reads"] if c[:2] == ["iot-data", "get-thing-shadow"] and THINGS[k] in c], k


def test_a_certificate_still_on_its_thing_is_not_torn_down(twin: Rig) -> None:
    """verify#11 (v59): a fleet certificate that is INACTIVE and has no policy, but is still on its thing, is not deleted."""
    join(twin, 2)
    twin.go("teardown", "fleet-attachments-2")
    twin.go("teardown", "fleet-policy-2")
    cert = cert_of(twin, 2)
    twin.edit(lambda a: a["things"][THINGS[2]]["principals"].update({arn(cert): "EXCLUSIVE_THING"}))
    since = len(twin.log())
    ran = twin.go("teardown", "fleet-certificate-2", expect=1)
    assert "still attached to its thing" in ran.err and twin.writes(since) == []
