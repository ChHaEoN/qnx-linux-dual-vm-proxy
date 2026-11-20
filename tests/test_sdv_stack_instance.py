"""The stack's fleet instance and its feed gate (sdv/stack/stack.py, module docstring INSTANCE): video 3's fleet, package
P1 (the fleet runner, sdv/stack/fleet.py, starts one stack.py replay per car with SDV_STACK_INSTANCE=<k>).

Pure tests (standard library; no Docker, no bus, no databroker): stack.py is loaded afresh from its file under a name of
these tests' own, with SDV_STACK_INSTANCE and SDV_STACK_FEED_GATE set as each test needs, since the stack reads them at
import as it reads SDV_GEN to SDV_CACHE; docker, the player and the bus are replaced.
  * unset or empty: every constant, container name, label, port and interface, start()'s argument vector of every
    container in both feeds, remove_stack's and ensure_vcan's calls and a replay's record are today's, written out here as
    literals;
  * instance 1, 2 and 3: each name gains -f<k>, the interface is vcanf<k>, the databroker's port 55560 + k and the mock
    provider's 50060 + k, every container carries sdv.stack.instance=<k> beside the run label, and the connector gets
    SDV_TWIN_DATABROKER for its own databroker: every argument vector is today's with exactly those words changed;
  * remove_stack removes every labelled container (a fleet's included) when no instance is set, and only its own
    instance's containers in an instance run;
  * main() refuses, in an instance run, every command but replay, another feed than vcan, a bridge, no connector,
    --images loaded and a host role other than pc (one host_role() does not know among them), each with its own
    sentence naming SDV_STACK_INSTANCE and before anything is pulled, written or started; any other instance value, and
    the gate given alone or not an existing absolute directory outside the repo;
  * the gate: ready-<k> written (by write-then-rename) once the start checks pass, no CAN provider, player or capture
    before go, the player and the capture on the instance's own interface, the record's gate; abort, or the wait running
    out, ends the replay through its finally with only this instance's containers removed, and the INSTANCE section and
    gate_wait's docstring say that finally collects and removes, stopping nothing.

Does not demonstrate: anything about Docker, the bus or a databroker (each is replaced); that the cars' feeds start at
one instant (only after one go); any timing.
"""
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STACK_DIR = REPO / "sdv" / "stack"
IMAGES = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))
INSTANCE_ENV, GATE_ENV = "SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE"
APP_IMG = "sha256:" + "ab" * 32         # synthetic image IDs and the app's synthetic config digest
APP_CFG = "sha256:" + "fe" * 32
REC_IMG = "sha256:" + "cd" * 32
BRIDGE_IMG = "sha256:" + "be" * 32
CONN_IMG = "sha256:" + "c0" * 32
RECORDED = ["Vehicle.Speed", "Vehicle.Body.Lights.Hazard.IsSignaling"]
WITNESS_PATHS = ["Vehicle.DualVm.Motion.LongitudinalVelocity", "Vehicle.Speed"]
POSIX = pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only (the stack runs in WSL)")

_MODULES: Dict[Tuple[Optional[str], Optional[str]], Any] = {}


def load_stack(instance: Optional[str] = None, gate: Optional[str] = None) -> Any:
    """stack.py executed afresh from its file with the two variables as given (None: unset), under a module name of these
    tests' own; the environment is restored after, and no bytecode is written."""
    key = (instance, gate)
    if key in _MODULES:
        return _MODULES[key]
    saved = {n: os.environ.get(n) for n in (INSTANCE_ENV, GATE_ENV)}
    saved_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for name, value in ((INSTANCE_ENV, instance), (GATE_ENV, gate)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        spec = importlib.util.spec_from_file_location("_stack_under_instance_test_%d" % len(_MODULES), str(STACK_DIR / "stack.py"))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        sys.dont_write_bytecode = saved_bytecode
    _MODULES[key] = mod
    return mod


@pytest.fixture(autouse=True)
def _no_host_settings(monkeypatch, tmp_path_factory):
    """No test reads this host's twin-control marker, spool or status setting, or its host role."""
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(tmp_path_factory.getbasetemp() / "no-twin-control-marker-here"))
    for name in ("SDV_SPOOL_DIR", "SDV_STATUS_DIR", "SDV_HOST_ROLE", "SDV_CONTAINER_CPUSET", "SDV_AFTER_START", INSTANCE_ENV, GATE_ENV):
        monkeypatch.delenv(name, raising=False)


# --- today's literals -----------------------------------------------------------------------------------------------

TODAYS_NAMES = {"kuksa-databroker": "sdv-stack-databroker", "kuksa-mock-provider": "sdv-stack-mock-provider",
                "kuksa-csv-provider-recorder": "sdv-stack-recorder", "vss-witness": "sdv-stack-witness",
                "hard-brake-hazard": "sdv-stack-app", "kuksa-can-provider": "sdv-stack-can-provider"}
TODAYS_CONTAINERS = dict(TODAYS_NAMES, **{"vss-claim-bridge": "sdv-stack-bridge", "twin-connector": "sdv-stack-connector"})


def upstream(name: str) -> str:
    u = IMAGES["upstream"][name]
    return "%s@%s" % (u["repo"], u["index_digest"])


def todays_argv(feed: str, rd: Path, ind: Path, dev: Path, uid: str) -> Dict[str, List[str]]:
    """start()'s argument vector of every container as it is today (written out, not computed from the module), with the
    run label test/run, the replay directory rd, the staged inputs ind and the device directory dev."""
    common = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-opt", "max-size=10m", "--memory", "512m",
              "--memory-swap", "512m"]

    def base(name: str, net: List[str]) -> List[str]:
        return ["run", "-d", "--name", name, "--label", "sdv.stack.run=test/run"] + common + net

    host = ["--network", "host"]
    other = host if feed == "vcan" else ["--network", "container:sdv-stack-databroker"]
    can_tail = (["--use-socketcan", "--canport", "vcan0"] if feed == "vcan" else ["--dumpfile", "/in/sigsim.log", "--canport", "vcan0"])
    out = {
        "sdv-stack-databroker": base("sdv-stack-databroker", host if feed == "vcan" else ["--network", "none"]) + [
            "--read-only", "-e", "KUKSA_DATABROKER_ADDR=127.0.0.1", "-v", "%s:/in:ro" % ind, upstream("kuksa-databroker"),
            "--vss", "/in/vss-databroker.json", "--address", "127.0.0.1", "--port", "55555", "--insecure"],
        "sdv-stack-mock-provider": base("sdv-stack-mock-provider", other) + [
            "-e", "VDB_ADDRESS=127.0.0.1:55555", "-e", "MOCK_ADDR=127.0.0.1:50053", "-v", "%s:/mock/mock.py:ro" % (STACK_DIR / "mock" / "mock.py"),
            upstream("kuksa-mock-provider")],
        "sdv-stack-recorder": base("sdv-stack-recorder", other) + [
            "--read-only", "--user", uid, "-v", "%s:/out" % rd, REC_IMG, "-a", "127.0.0.1", "-p", "55555", "-f", "/out/vss-recorder.csv",
            "-l", "INFO", "-s"] + RECORDED,
        "sdv-stack-witness": base("sdv-stack-witness", other) + [
            "--read-only", "--user", uid, "-v", "%s:/out" % rd, "-v", "%s:/witness.py:ro" % (STACK_DIR / "witness.py"), "--entrypoint", "python",
            REC_IMG, "/witness.py", "127.0.0.1:55555", "/out/vss-witness.jsonl"] + WITNESS_PATHS,
        "sdv-stack-app": base("sdv-stack-app", other) + [
            "--read-only", "--user", uid, "-v", "%s:/out" % rd, "-e", "APP_IMAGE_ID=" + APP_CFG, "-e", "KUKSA_ADDRESS=127.0.0.1:55555",
            "-e", "HBH_LOG=/out/hard-brake-hazard.jsonl", APP_IMG],
        "sdv-stack-can-provider": base("sdv-stack-can-provider", other) + [
            "--read-only", "--tmpfs", "/tmp:rw,exec,size=256m", "-v", "%s:/in:ro" % ind, upstream("kuksa-can-provider"),
            "grpc://127.0.0.1:55555", "--config", "/in/can-provider.ini", "--dbcfile", "/in/slice.dbc", "--mapping", "/in/vss-can-mapping.json",
            "--dbc2val", "--no-val2dbc", "--no-infinite"] + can_tail,
    }
    if feed == "vcan":
        out["sdv-stack-bridge"] = base("sdv-stack-bridge", host) + [
            "--read-only", "--user", uid, "--mount", "type=bind,src=%s,dst=/run/lock/sdv-scenario.lock" % (rd / "scenario.lock"),
            "-v", "%s:/out" % (rd / "bridge"), "-v", "%s:/header.json:ro" % (rd / "bridge-header.json"), BRIDGE_IMG, "run", "--host", "127.0.0.1",
            "--port", "7160", "--header", "/header.json", "--broker", "127.0.0.1:55555", "--out", "/out"]
        out["sdv-stack-connector"] = base("sdv-stack-connector", host) + [
            "--read-only", "--user", uid, "--restart", "no", "--mount", "type=bind,src=%s,dst=/run/sdv-local/spool/v1" % (rd / "spool"),
            "--mount", "type=bind,src=%s,dst=/run/sdv-local/status/v1,readonly" % (rd / "status"),
            "--mount", "type=bind,src=%s,dst=/run/sdv-local/device,readonly" % dev, "--env-file", str(dev / "connector.env"), CONN_IMG]
    return out


def instance_form(argv: List[str], k: int) -> List[str]:
    """Today's argument vector as instance k's must be: the container's name with -f<k>, the instance label after the run
    label, the databroker's port 55560 + k, the mock provider's 50060 + k, the interface vcanf<k>, and the connector's
    SDV_TWIN_DATABROKER before its --env-file. Nothing else changes."""
    out: List[str] = []
    for i, a in enumerate(argv):
        if a == "--env-file":
            out += ["-e", "SDV_TWIN_DATABROKER=127.0.0.1:%d" % (55560 + k)]
        if i > 0 and argv[i - 1] == "--name":
            out.append(a + "-f%d" % k)
        else:
            out.append(a.replace("55555", str(55560 + k)).replace("50053", str(50060 + k)).replace("vcan0", "vcanf%d" % k))
        if i > 0 and argv[i - 1] == "--label" and a.startswith("sdv.stack.run="):
            out += ["--label", "sdv.stack.instance=%d" % k]
    return out


class TableDocker:
    """stack.docker replaced by a table of containers: `run` adds one with its name and labels, `ps -aq --filter
    label=K[=V]` lists the matching ones, `rm -f` removes them; every argument vector is kept."""

    def __init__(self, pre: Tuple[Tuple[str, str, Dict[str, str]], ...] = ()) -> None:
        self.containers: Dict[str, Dict[str, Any]] = {cid: {"name": n, "labels": dict(lab)} for cid, n, lab in pre}
        self.calls: List[List[str]] = []
        self.serial = 0

    def __call__(self, *args: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        a = list(args)
        self.calls.append(a)
        out = ""
        if a[:1] == ["run"]:
            labels = dict(a[i + 1].split("=", 1) for i, x in enumerate(a) if x == "--label")
            self.serial += 1
            self.containers["new%02d" % self.serial] = {"name": a[a.index("--name") + 1], "labels": labels}
        elif a[:2] == ["ps", "-aq"]:
            key, sep, value = a[a.index("--filter") + 1][len("label="):].partition("=")
            out = "\n".join(cid for cid, c in self.containers.items() if key in c["labels"] and (not sep or c["labels"][key] == value))
        elif a[:2] == ["rm", "-f"]:
            for cid in a[2:]:
                self.containers.pop(cid, None)
        return subprocess.CompletedProcess(a, 0, out, "")

    def runs(self) -> List[List[str]]:
        return [c for c in self.calls if c[:1] == ["run"]]

    def names(self) -> List[str]:
        return sorted(c["name"] for c in self.containers.values())


def fake_ctx(tmp_path: Path) -> Any:
    ids = {"hard-brake-hazard": APP_IMG, "kuksa-csv-provider-recorder": REC_IMG, "vss-claim-bridge": BRIDGE_IMG, "twin-connector": CONN_IMG}
    return types.SimpleNamespace(images=IMAGES, image_ids=lambda: ids, in_dir=tmp_path / "in", bridge="broker", monitor_mode="native",
                                 guest=None, components={"hard-brake-hazard": {"image_id": APP_IMG, "config_digest": APP_CFG}},
                                 recorded=list(RECORDED), witness_paths=list(WITNESS_PATHS), cpuset=None, after_start=None)


def start_all(s: Any, tmp_path: Path, monkeypatch: Any, feed: str) -> Dict[str, List[str]]:
    """start() for every container a run may start on this feed (the bridge and the connector on vcan only):
    {container name: argv}."""
    fake = TableDocker()
    monkeypatch.setattr(s, "docker", fake)
    rd = tmp_path / "r"
    for d in (rd / "bridge", rd / "spool", rd / "status"):
        d.mkdir(parents=True, exist_ok=True)
    (rd / "scenario.lock").touch()
    (rd / "bridge-header.json").write_text("{}", encoding="utf-8")
    dev = tmp_path / "device"
    dev.mkdir(exist_ok=True)
    (dev / "connector.env").write_text("SDV_TWIN_THING=example-thing\n", encoding="ascii")
    monkeypatch.setenv("SDV_DEVICE_DIR", str(dev))
    ctx = fake_ctx(tmp_path)
    comps = list(s.NAMES) + ([s.attr.BRIDGE, s.CONNECTOR] if feed == "vcan" else [])
    for comp in comps:
        s.start(ctx, comp, feed, rd, "test/run")
    runs = fake.runs()
    assert len(runs) == len(comps)
    return {r[r.index("--name") + 1]: r for r in runs}


# --- unset: today's ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [None, ""])
def test_unset_or_empty_every_constant_is_todays(raw):
    s = load_stack(raw)
    assert s.INSTANCE is None
    assert s.NAMES == TODAYS_NAMES and s.CONTAINERS == TODAYS_CONTAINERS
    assert (s.BRIDGE_CONTAINER, s.CONNECTOR_CONTAINER) == ("sdv-stack-bridge", "sdv-stack-connector")
    assert (s.VCAN, s.BROKER_HOST, s.BROKER_PORT, s.BROKER, s.MOCK_PORT, s.LABEL) == ("vcan0", "127.0.0.1", 55555, "127.0.0.1:55555", 50053,
                                                                                       "sdv.stack.run")


@POSIX
@pytest.mark.parametrize("raw", [None, ""])
@pytest.mark.parametrize("feed", ["dumpfile", "vcan"])
def test_unset_every_argument_vector_is_todays_literal(tmp_path, monkeypatch, raw, feed):
    s = load_stack(raw)
    got = start_all(s, tmp_path, monkeypatch, feed)
    want = todays_argv(feed, tmp_path / "r", tmp_path / "in", tmp_path / "device", "%d:%d" % (os.getuid(), os.getgid()))
    assert sorted(got) == sorted(want)
    for name in want:
        assert got[name] == want[name], name


@pytest.mark.parametrize("raw", [None, ""])
def test_unset_remove_stack_and_ensure_vcan_make_todays_calls(monkeypatch, raw):
    s = load_stack(raw)
    fake = TableDocker((("c1", "sdv-stack-databroker", {"sdv.stack.run": "x/vcan-1"}),
                        ("c2", "sdv-stack-witness-f2", {"sdv.stack.run": "y/vcan-1", "sdv.stack.instance": "2"}),
                        ("c3", "someone-else", {"other": "1"})))
    monkeypatch.setattr(s, "docker", fake)
    s.remove_stack()
    assert fake.calls == [["ps", "-aq", "--filter", "label=sdv.stack.run"], ["rm", "-f", "c1", "c2"]]
    assert fake.names() == ["someone-else"], "the default run removes every labelled container, a fleet's included"
    calls: List[List[str]] = []
    monkeypatch.setattr(s, "run", lambda cmd, check=True, timeout=None, input_text=None: calls.append(list(cmd)) or
                        subprocess.CompletedProcess(cmd, 1 if cmd[:3] == ["ip", "link", "show"] else 0, "", ""))
    assert s.ensure_vcan() == {"created": True, "how": "sudo -n modprobe vcan; ip link add dev vcan0 type vcan; ip link set up vcan0"}
    assert calls == [["ip", "link", "show", "vcan0"], ["sudo", "-n", "modprobe", "vcan"],
                     ["sudo", "-n", "ip", "link", "add", "dev", "vcan0", "type", "vcan"], ["sudo", "-n", "ip", "link", "set", "up", "vcan0"]]


# --- instance k ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("k", [1, 2, 3])
def test_instance_k_names_its_containers_its_interface_and_its_two_ports(k):
    s = load_stack(str(k))
    assert s.INSTANCE == k
    assert s.NAMES == {comp: name + "-f%d" % k for comp, name in TODAYS_NAMES.items()}
    assert s.CONTAINERS == {comp: name + "-f%d" % k for comp, name in TODAYS_CONTAINERS.items()}
    assert (s.BRIDGE_CONTAINER, s.CONNECTOR_CONTAINER) == ("sdv-stack-bridge-f%d" % k, "sdv-stack-connector-f%d" % k)
    assert (s.VCAN, s.BROKER_HOST, s.BROKER_PORT, s.BROKER, s.MOCK_PORT, s.LABEL) == (
        "vcanf%d" % k, "127.0.0.1", 55560 + k, "127.0.0.1:%d" % (55560 + k), 50060 + k, "sdv.stack.run")


@POSIX
@pytest.mark.parametrize("k", [1, 2, 3])
def test_instance_k_argument_vectors_are_todays_with_only_its_names_ports_interface_labels_and_the_connectors_databroker(
        tmp_path, monkeypatch, k):
    s = load_stack(str(k))
    got = start_all(s, tmp_path, monkeypatch, "vcan")
    want = todays_argv("vcan", tmp_path / "r", tmp_path / "in", tmp_path / "device", "%d:%d" % (os.getuid(), os.getgid()))
    assert sorted(got) == sorted(name + "-f%d" % k for name in want)
    for name, argv in want.items():
        assert got[name + "-f%d" % k] == instance_form(argv, k), name
    connector = got["sdv-stack-connector-f%d" % k]
    i = connector.index("-e")
    assert connector[i:i + 3] == ["-e", "SDV_TWIN_DATABROKER=127.0.0.1:%d" % (55560 + k), "--env-file"]
    for argv in got.values():
        joined = " ".join(argv)
        assert "55555" not in joined and "50053" not in joined and "vcan0" not in joined
        assert argv[argv.index("--label") + 2:argv.index("--label") + 4] == ["--label", "sdv.stack.instance=%d" % k]


@pytest.mark.parametrize("k", [1, 2, 3])
def test_instance_k_ensure_vcan_makes_its_own_interface(monkeypatch, k):
    s = load_stack(str(k))
    calls: List[List[str]] = []
    monkeypatch.setattr(s, "run", lambda cmd, check=True, timeout=None, input_text=None: calls.append(list(cmd)) or
                        subprocess.CompletedProcess(cmd, 1 if cmd[:3] == ["ip", "link", "show"] else 0, "", ""))
    v = "vcanf%d" % k
    assert s.ensure_vcan() == {"created": True, "how": "sudo -n modprobe vcan; ip link add dev %s type vcan; ip link set up %s" % (v, v)}
    assert calls == [["ip", "link", "show", v], ["sudo", "-n", "modprobe", "vcan"], ["sudo", "-n", "ip", "link", "add", "dev", v, "type", "vcan"],
                     ["sudo", "-n", "ip", "link", "set", "up", v]]


FLEET = (("d0", "sdv-stack-databroker", {"sdv.stack.run": "one/vcan-1"}),
         ("d1", "sdv-stack-databroker-f1", {"sdv.stack.run": "f-A/vcan-1", "sdv.stack.instance": "1"}),
         ("d2", "sdv-stack-databroker-f2", {"sdv.stack.run": "f-B/vcan-1", "sdv.stack.instance": "2"}),
         ("w2", "sdv-stack-witness-f2", {"sdv.stack.run": "f-B/vcan-1", "sdv.stack.instance": "2"}),
         ("d3", "sdv-stack-databroker-f3", {"sdv.stack.run": "f-C/vcan-1", "sdv.stack.instance": "3"}),
         ("x9", "someone-else", {"other": "1"}))


@pytest.mark.parametrize("k", [1, 2, 3])
def test_remove_stack_in_an_instance_run_removes_only_that_instances_containers(monkeypatch, k):
    s = load_stack(str(k))
    fake = TableDocker(FLEET)
    monkeypatch.setattr(s, "docker", fake)
    s.remove_stack()
    assert fake.calls[0] == ["ps", "-aq", "--filter", "label=sdv.stack.instance=%d" % k]
    gone = sorted(n for _cid, n, lab in FLEET if lab.get("sdv.stack.instance") == str(k))
    assert fake.names() == sorted(n for _cid, n, _lab in FLEET if n not in gone)


# --- main()'s refusals -----------------------------------------------------------------------------------------------

def untouched(s: Any, monkeypatch: Any, tmp_path: Path) -> Path:
    """Every way main() could pull, write or start anything, replaced by a failure; RUNS pointed at a directory that must
    stay absent."""
    def touched(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("the stack went on though the run was to be refused")

    for name in ("docker", "run", "remove_stack", "Context", "RosContext", "new_run_dir", "live_main", "ros_main", "ros_runs_left",
                 "loadcheck", "age_probe", "wheelbase_probe", "ensure_vcan", "up", "replay_once"):
        monkeypatch.setattr(s, name, touched)
    runs = tmp_path / "runs"
    monkeypatch.setattr(s, "RUNS", runs)
    return runs


GOOD = ["replay", "--name", "f-B", "--feed", "vcan", "--bridge", "none", "--connector"]
REFUSED = [
    (["prepare", "--name", "x", "--bridge", "none"], "replay"),
    (["exit-test", "--name", "x"], "replay"),
    (["up", "--name", "x", "--feed", "vcan", "--connector"], "replay"),
    (["down"], "replay"),
    (["loadcheck", "--name", "x"], "replay"),
    (["ageprobe", "--name", "x"], "replay"),
    (["wheelbaseprobe", "--name", "x"], "replay"),
    (["live", "--name", "x", "--bridge", "broker", "--feeder-out", "/nowhere/take"], "replay"),
    (["replay", "--name", "x", "--feed", "dumpfile", "--bridge", "none", "--connector"], "--feed vcan"),
    (["replay", "--name", "x", "--feed", "vcan", "--bridge", "broker", "--connector"], "--bridge none"),
    (["replay", "--name", "x", "--feed", "vcan", "--bridge", "none"], "--connector"),
    (["replay", "--name", "x", "--feed", "vcan", "--connector"] + ["--images", "loaded"], "--images"),
]


@pytest.mark.parametrize("argv, words", REFUSED)
def test_an_instance_run_refuses_all_but_a_vcan_replay_with_the_connector_and_no_bridge_before_anything_is_written(
        tmp_path, monkeypatch, argv, words):
    s = load_stack("2")
    runs = untouched(s, monkeypatch, tmp_path)
    with pytest.raises(s.StackError) as e:
        s.main(argv)
    assert INSTANCE_ENV in str(e.value) and words in str(e.value), str(e.value)
    assert not runs.exists()


@pytest.mark.parametrize("role", ["a1-metal", "c7g-metal", "orin", "a-laptop"])
def test_an_instance_run_off_the_pc_is_refused_before_anything_is_written(tmp_path, monkeypatch, role):
    s = load_stack("3")
    runs = untouched(s, monkeypatch, tmp_path)
    monkeypatch.setenv("SDV_HOST_ROLE", role)
    if role == "orin":
        monkeypatch.setenv("SDV_CONTAINER_CPUSET", "3,5")
    with pytest.raises(s.StackError) as e:
        s.main(GOOD)
    assert INSTANCE_ENV in str(e.value) and "pc" in str(e.value), str(e.value)
    assert not runs.exists()


def test_each_refusal_of_an_instance_run_has_its_own_sentence(tmp_path, monkeypatch):
    s = load_stack("1")
    untouched(s, monkeypatch, tmp_path)
    said = set()
    for argv in (["down"], REFUSED[8][0], REFUSED[9][0], REFUSED[10][0], REFUSED[11][0]):
        with pytest.raises(s.StackError) as e:
            s.main(argv)
        said.add(str(e.value))
    monkeypatch.setenv("SDV_HOST_ROLE", "a1-metal")
    with pytest.raises(s.StackError) as e:
        s.main(GOOD)
    said.add(str(e.value))
    assert len(said) == 6, said


class Stop(Exception):
    pass


@pytest.mark.parametrize("k", ["1", "2", "3"])
def test_an_instance_run_of_a_vcan_replay_with_the_connector_and_no_bridge_on_the_pc_goes_on_to_its_context(tmp_path, monkeypatch, k):
    s = load_stack(k)
    seen: List[Any] = []

    class FakeContext:
        def __init__(self, run_dir: Path, seed: Any, bridge: str, **kw: Any) -> None:
            seen.append((run_dir.name, bridge, kw))
            raise Stop()

    monkeypatch.setattr(s, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(s, "Context", FakeContext)
    for role in (None, "pc"):
        if role is None:
            monkeypatch.delenv("SDV_HOST_ROLE", raising=False)
        else:
            monkeypatch.setenv("SDV_HOST_ROLE", role)
        with pytest.raises(Stop):
            s.main(GOOD)
    assert [x[1:] for x in seen] == [("none", {"connector": True})] * 2


@pytest.mark.parametrize("raw", ["0", "4", "f1", "01", " 1", "1 ", "-1", "one", "12", "1.0"])
def test_any_other_instance_value_is_refused_by_main_and_the_constants_stay_todays(tmp_path, monkeypatch, raw):
    s = load_stack(raw)
    assert s.INSTANCE is None and s.NAMES == TODAYS_NAMES and s.CONTAINERS == TODAYS_CONTAINERS
    assert (s.VCAN, s.BROKER_PORT, s.MOCK_PORT) == ("vcan0", 55555, 50053)
    runs = untouched(s, monkeypatch, tmp_path)
    for argv in (GOOD, ["down"], ["up", "--name", "x"]):
        with pytest.raises(s.StackError) as e:
            s.main(argv)
        assert INSTANCE_ENV in str(e.value)
    assert not runs.exists()


def test_the_feed_gate_given_alone_is_refused(tmp_path, monkeypatch):
    gate = tmp_path / "gate"
    gate.mkdir()
    for instance in (None, ""):
        s = load_stack(instance, str(gate))
        runs = untouched(s, monkeypatch, tmp_path)
        for argv in (GOOD, ["down"], ["replay", "--name", "x"]):
            with pytest.raises(s.StackError) as e:
                s.main(argv)
            assert GATE_ENV in str(e.value) and INSTANCE_ENV in str(e.value), str(e.value)
            assert str(gate) not in str(e.value)
        assert not runs.exists()


@pytest.mark.parametrize("which", ["empty", "relative", "missing", "a file", "inside the repo"])
def test_a_feed_gate_that_is_not_an_existing_absolute_directory_outside_the_repo_is_refused(tmp_path, monkeypatch, which):
    (tmp_path / "file").write_text("x", encoding="ascii")
    if which == "relative":          # the relative directory exists, so only its being relative can refuse it
        monkeypatch.chdir(tmp_path)
        (tmp_path / "gate").mkdir()
    raw = {"empty": "", "relative": "gate", "missing": str(tmp_path / "no-such-gate"), "a file": str(tmp_path / "file"),
           "inside the repo": str(STACK_DIR)}[which]
    s = load_stack("2", raw)
    runs = untouched(s, monkeypatch, tmp_path)
    with pytest.raises(s.StackError) as e:
        s.main(GOOD)
    assert GATE_ENV in str(e.value), str(e.value)
    assert not runs.exists()


def test_the_feed_gate_with_an_instance_goes_on_to_the_context(tmp_path, monkeypatch):
    gate = tmp_path / "gate"
    gate.mkdir()
    s = load_stack("2", str(gate))

    def context(*_a: Any, **_kw: Any) -> Any:
        raise Stop()

    monkeypatch.setattr(s, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(s, "Context", context)
    with pytest.raises(Stop):
        s.main(GOOD)
    assert s.feed_gate() == gate


# --- the gate in replay_once -----------------------------------------------------------------------------------------

class FakeBus:
    """VcanCapture's python-can, replaced: the channel it opened, and no frame."""
    channels: List[str] = []

    def __init__(self, interface: str, channel: str) -> None:
        FakeBus.channels.append(channel)

    def recv(self, timeout: float = 0.0) -> None:
        time.sleep(min(timeout, 0.05))
        return None

    def shutdown(self) -> None:
        pass


def replay_rig(s: Any, tmp_path: Path, monkeypatch: Any, gate: Optional[Path]) -> types.SimpleNamespace:
    """replay_once with every outside call replaced: docker by a table holding another instance's and a one-stack run's
    container, up() by a start of the databroker alone, the player by a record of its argv, the bus by FakeBus."""
    fake = TableDocker(FLEET)
    monkeypatch.setattr(s, "docker", fake)
    players: List[List[str]] = []
    collected: List[str] = []

    def fake_run(cmd: Any, check: bool = True, timeout: Any = None, input_text: Any = None) -> subprocess.CompletedProcess:
        players.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_up(ctx: Any, feed: str, rd: Path, label: str, header: Any = None) -> Dict[str, Any]:
        rd.mkdir(parents=True, exist_ok=True)
        s.start(ctx, s.attr.DATABROKER, feed, rd, label)
        return {"feed": feed, "listeners_before": {}, "listeners": {"ok": True}}

    def listeners_now(info: Dict[str, Any], feed: str, suffix: str, allowed: Any = ()) -> None:
        info["listeners" + suffix] = {"ok": True}

    def collect(rd: Path) -> Dict[str, Any]:
        collected.append(rd.name)
        return {}

    fakes: List[Tuple[str, Any]] = [
        ("up", fake_up), ("listeners_now", listeners_now), ("wait_log", lambda *a, **kw: None), ("wait_for", lambda *a, **kw: None),
        ("stop_containers", lambda ctx: None), ("collect", collect), ("analyse", lambda ctx, rd: {}), ("run", fake_run),
        ("log_frames", lambda path: []), ("record_close", lambda header, rd, console=None: ("C12b", True, "synthetic")),
        ("player_bound_s", lambda log: 300)]          # the bound's own tests: tests/test_sdv_stack_playerbound.py
    for name, fn in fakes:
        monkeypatch.setattr(s, name, fn)
    monkeypatch.setattr(s, "VCAN_READY_S", 0.0)
    monkeypatch.setattr(s, "FEED_GATE_RAW", None if gate is None else str(gate))
    attr_fakes: List[Tuple[str, Any]] = [
        ("check_recording", lambda header, sha, dbc: ("C10", True, "synthetic")), ("run_rows", lambda rows, ids: []),
        ("check_images", lambda rows, running: ("C8", True, "synthetic")), ("render_markdown", lambda h, r: "")]
    for name, fn in attr_fakes:
        monkeypatch.setattr(s.attr, name, fn)
    FakeBus.channels = []
    monkeypatch.setitem(sys.modules, "can", types.SimpleNamespace(Bus=FakeBus))
    (tmp_path / "in").mkdir(exist_ok=True)
    ctx = types.SimpleNamespace(bridge="none", monitor_mode="native", monitor=None, guest=None, run_dir=tmp_path / "runs" / "20990101-f-B",
                                run_header=lambda rid, feed: {"run_id": rid}, check_header=lambda h: ("C12a", True, "synthetic"),
                                rows=[], image_ids=lambda: {}, staged={"sigsim.log": "ab" * 32}, scenario={"dbc_sha256": "x"},
                                manifest={"scenario_checks": []}, decoded={"values": {s.rc.V_PATH: [], s.attr.SLOT_PATHS[4]: []}},
                                images=IMAGES, in_dir=tmp_path / "in", cpuset=None, after_start=None, after_start_records=[])
    return types.SimpleNamespace(ctx=ctx, docker=fake, players=players, collected=collected)


def feed_started(rig: types.SimpleNamespace, s: Any) -> bool:
    can = s.NAMES[s.attr.CAN_PROVIDER]
    return bool(rig.players) or bool(FakeBus.channels) or any(r[r.index("--name") + 1] == can for r in rig.docker.runs())


class Replay(threading.Thread):
    """replay_once in a thread of its own, its result or its error kept."""

    def __init__(self, s: Any, ctx: Any) -> None:
        super().__init__(daemon=True)
        self.s, self.ctx = s, ctx
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[BaseException] = None

    def run(self) -> None:
        try:
            self.result = self.s.replay_once(self.ctx, "vcan", "vcan-1")
        except BaseException as exc:  # noqa: BLE001 -- the test reads it
            self.error = exc


def wait_file(path: Path, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists():
            return True
        time.sleep(0.02)
    return path.exists()


def test_the_gate_writes_ready_and_starts_no_feed_before_go_and_then_the_feed_on_the_instances_own_interface(tmp_path, monkeypatch):
    s = load_stack("2")
    gate = tmp_path / "gate"
    gate.mkdir()
    replaced: List[Tuple[str, str]] = []
    real_replace = os.replace

    def recording_replace(src: Any, dst: Any) -> None:
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(s.os, "replace", recording_replace)
    rig = replay_rig(s, tmp_path, monkeypatch, gate)
    t = Replay(s, rig.ctx)
    t.start()
    assert wait_file(gate / "ready-2"), "no ready-2 in the gate"
    assert [c for c in replaced if c[1].startswith(str(gate))] == [(str(gate / ".ready-2.tmp"), str(gate / "ready-2"))], \
        "ready-2 is written by write-then-rename: once, from its temporary file"
    ready = json.loads((gate / "ready-2").read_text(encoding="utf-8"))
    assert set(ready) == {"instance", "ready_ms"} and ready["instance"] == 2 and isinstance(ready["ready_ms"], int)
    time.sleep(0.6)
    assert sorted(p.name for p in gate.iterdir()) == ["ready-2"], "written by write-then-rename: nothing else is left in the gate"
    assert not feed_started(rig, s), "the feed started before go"
    assert t.is_alive()
    before_go = int(time.time() * 1000)
    (gate / "go").write_text("", encoding="ascii")
    t.join(30)
    assert not t.is_alive() and t.error is None, t.error
    assert rig.players and rig.players[0][rig.players[0].index("-c") + 1] == "vcanf2", rig.players
    assert FakeBus.channels == ["vcanf2"]
    can = [r for r in rig.docker.runs() if r[r.index("--name") + 1] == "sdv-stack-can-provider-f2"]
    assert len(can) == 1 and can[0][-2:] == ["--canport", "vcanf2"]
    assert t.result is not None
    g = t.result["gate"]
    assert set(g) == {"ready_ms", "go_seen_ms"} and g["ready_ms"] == ready["ready_ms"] and g["go_seen_ms"] >= before_go - 5
    on_disk = json.loads((rig.ctx.run_dir / "vcan-1" / "result.json").read_text(encoding="utf-8"))
    assert on_disk["gate"] == g


@pytest.mark.parametrize("how", ["abort", "abort with go", "the wait running out"])
def test_abort_or_the_wait_running_out_ends_the_replay_through_finally_with_only_this_instance_removed(tmp_path, monkeypatch, how):
    s = load_stack("2")
    gate = tmp_path / "gate"
    gate.mkdir()
    rig = replay_rig(s, tmp_path, monkeypatch, gate)
    if how == "the wait running out":
        monkeypatch.setattr(s, "GATE_WAIT_S", 1.0)
    t = Replay(s, rig.ctx)
    t.start()
    assert wait_file(gate / "ready-2")
    ready_seen = time.monotonic()
    if how != "the wait running out":
        (gate / "abort").write_text("car C ended before it was ready\n", encoding="ascii")
    if how == "abort with go":
        (gate / "go").write_text("", encoding="ascii")
    t.join(15)
    if t.is_alive():          # the replay did not end: release it, then fail
        (gate / "abort").write_text("", encoding="ascii")
        t.join(15)
        pytest.fail("the replay went on waiting after %s" % how)
    if how == "the wait running out":
        assert time.monotonic() - ready_seen < 5.0, "the wait ran well past GATE_WAIT_S (1 s here)"
    assert isinstance(t.error, s.StackError), t.error
    assert GATE_ENV in str(t.error) and str(gate) in str(t.error), str(t.error)
    assert not feed_started(rig, s), "the feed started"
    assert rig.collected == ["vcan-1"], "the finally ran its collect"
    assert rig.docker.names() == sorted(n for _cid, n, lab in FLEET if lab.get("sdv.stack.instance") != "2"), "only this instance's removed"
    assert ["ps", "-aq", "--filter", "label=sdv.stack.instance=2"] in rig.docker.calls
    assert not (rig.ctx.run_dir / "vcan-1" / "result.json").exists()


def test_a_car_whose_start_checks_fail_refuses_before_its_gate_so_it_writes_no_ready_and_starts_no_feed(tmp_path, monkeypatch):
    """The gate is after the start checks: a failed check ends the replay (through its finally) without ready-<k>, so the fleet
    never takes the car for ready and no other car's feed is held for it."""
    s = load_stack("2")
    gate = tmp_path / "gate"
    gate.mkdir()
    rig = replay_rig(s, tmp_path, monkeypatch, gate)
    monkeypatch.setattr(s, "GATE_WAIT_S", 1.0)          # a replay that waits at its gate anyway ends in a second, not in ten minutes
    rig.ctx.check_header = lambda h: ("C12a", False, "synthetic")
    with pytest.raises(s.StackError, match="refused to start the feed"):
        s.replay_once(rig.ctx, "vcan", "vcan-1")
    assert not (gate / "ready-2").exists() and list(gate.iterdir()) == []
    assert not feed_started(rig, s), "the feed started"
    assert rig.collected == ["vcan-1"], "the finally ran its collect"


def test_an_instance_run_without_a_gate_starts_its_feed_at_once_and_records_no_go(tmp_path, monkeypatch):
    s = load_stack("3")
    rig = replay_rig(s, tmp_path, monkeypatch, None)
    r = s.replay_once(rig.ctx, "vcan", "vcan-1")
    assert set(r["gate"]) == {"ready_ms", "go_seen_ms"} and isinstance(r["gate"]["ready_ms"], int) and r["gate"]["go_seen_ms"] is None
    assert rig.players[0][rig.players[0].index("-c") + 1] == "vcanf3" and FakeBus.channels == ["vcanf3"]


@pytest.mark.parametrize("raw", [None, ""])
def test_unset_a_replay_has_no_gate_and_plays_on_vcan0(tmp_path, monkeypatch, raw):
    s = load_stack(raw)
    rig = replay_rig(s, tmp_path, monkeypatch, None)
    r = s.replay_once(rig.ctx, "vcan", "vcan-1")
    assert "gate" not in r
    assert "gate" not in json.loads((rig.ctx.run_dir / "vcan-1" / "result.json").read_text(encoding="utf-8"))
    assert rig.players == [[str(s.SIM_PY), "-m", "can.player", "-i", "socketcan", "-c", "vcan0", str(tmp_path / "in" / "sigsim.log")]]
    assert FakeBus.channels == ["vcan0"]
    can = [r for r in rig.docker.runs() if r[r.index("--name") + 1] == "sdv-stack-can-provider"]
    assert len(can) == 1 and can[0][-2:] == ["--canport", "vcan0"] and "sdv.stack.instance=" not in " ".join(can[0])
    assert rig.docker.names() == ["someone-else"], "the default replay's end removes every labelled container"


def test_the_module_docstring_has_an_instance_section_with_what_it_does_not_show():
    doc = load_stack().__doc__
    assert "\nINSTANCE " in doc
    section = doc.split("\nINSTANCE ", 1)[1].split("\n\n", 1)[0]
    for words in ("SDV_STACK_INSTANCE", "SDV_STACK_FEED_GATE", "vcanf", "sdv.stack.instance", "SDV_TWIN_DATABROKER", "ready-", "abort",
                  "Does not demonstrate"):
        assert words in section, words


def test_the_instance_section_and_gate_wait_say_the_finally_collects_and_removes_and_stops_nothing():
    """An abort, or the wait running out, ends the replay through replay_once's finally, which collects and removes this
    instance's containers by docker rm -f (remove_stack) and stops none first (stop_containers is in the try body alone):
    the INSTANCE section and gate_wait's docstring say so, and neither says the finally stops."""
    s = load_stack()
    section = " ".join(s.__doc__.split("\nINSTANCE ", 1)[1].split("\n\n", 1)[0].split())
    gate = " ".join((s.gate_wait.__doc__ or "").split())
    assert ("which ends the replay through its finally: collect, and this instance's containers removed by docker rm -f (nothing is "
            "stopped first, so a ready car's connector ends without its stop document).") in section, section
    assert "(collect, and this instance's containers removed by docker rm -f; nothing is stopped first)" in gate, gate
    assert "stop, collect" not in section and "stop, collect" not in gate
    fin = inspect.getsource(s.replay_once).split("    finally:\n", 1)[1].split("    result.update(analyse", 1)[0]
    assert "stop_containers" not in fin and "collect(" in fin and "remove_stack()" in fin, fin
    assert 'docker("rm", "-f", *ids' in inspect.getsource(s.remove_stack)


def test_the_instance_section_says_only_main_refuses_so_the_stacks_importers_take_a_leftover_instance():
    """step3.py and sdv/arm64/arm64.py import stack.py, and only stack.py's main() refuses SDV_STACK_INSTANCE: a leftover one
    gives them an instance's names, its vcanf<k> and a remove_stack() of that instance alone. The section says so."""
    doc = load_stack().__doc__
    shown = " ".join(doc.split("\nINSTANCE ", 1)[1].split("\n\n", 1)[0].split("Does not demonstrate", 1)[1].split())
    for words in ("only stack.py's main() refuses", "sdv/stack/step3.py", "sdv/arm64/arm64.py", "remove_stack()"):
        assert words in shown, words