"""test_sdv_phase6_contract.py -- the contract between SDV Phase 6's three packages, held after their merge (the
integration stage, the updater contract section 6).

WP1 (sdv/ota), WP2 (sdv/connector, sdv/stack) and WP4 (sdv/cloud) were written at the
same time, each in its own worktree, each seeing the others only through spec section 2's interfaces: no package
imports a module another package added. This file is the one place that imports both sides of each interface and holds
one against the other, each side by its own code:
  * the status record (spec 2.4): every record WP1's write_status writes, WP2's status.read accepts with the same three
    values, also while a write is under way; every value WP2's reader refuses, WP1's writer refuses before it touches a
    file, case by case; the directory, the file and the bound are one on both sides, and 2.2's;
  * the spool record (spec 2.3): every record sdv/connector/spool.py writes, WP1's reader reads back as written; every
    record spool.py's rules refuse, WP1's reader refuses with the same findings; the directory, the file and the bound
    are one on both sides, and 2.2's; spool.py is 2.3's own, byte for byte (the pinned one's): both connector images bake
    it in (build_image.MODULES), so a change to it is a rebuild with new pins;
  * the app's start (spec 2.6): WP1's app_run_argv holds stack.COMMON verbatim, the cpuset where the stack's
    common_flags() puts it, and 2.6's flags in 2.6's order, and nothing else (2.6's leading `docker` is the updater's
    Docker prefix, which goes in front of app_run_argv's argv);
  * the twin-control marker (spec 2.2, 2.7): one default in sdv/ota and sdv/stack, and no other marker path in either;
    on every kind of entry at the path the updater never takes a scenario request while the stack would let a bridge
    start, and an entry plainly there or plainly absent is one answer on both sides;
  * the registry credentials directory (spec 2.2): ecrlogin.py's default and the updater's, compared as normalised
    paths (2.2 writes a trailing slash, neither package does);
  * the registry file (spec 2.5; section 5 item 8): the keys `twinctl ecr-config` writes are exactly the ones ecrlogin.py
    requires, and the updater's registry_host reads the same file's `registry`.

And WP3 (sdv/drill) and WP6 (run-ota-drill.sh, capture.py's whitelist), merged after them, each seeing the other only
through the OTA drill contract section 2.1, held to each other and to sdv/ota and sdv/stack (spec-2 sections 2.1 to 2.3, 3, 4):
  * the session's tar (2.3; section 4 item 2): build_drill.py save's three-image save and its two-line sum file, of
    documentation images, with the pins it saved, pass the harness's own preflight readers (its drill-tool.py, cut out of
    the harness and run in this process: files, tarsum, repocommit, pins, tarindex), and drill.py's check_save takes the
    same save; the two agree on saves whose index.json lists other digests (in another order, a pin missing, a fourth
    image, a pin twice), while tarindex, which reads only the listed digests, takes three index.json layouts check_save
    refuses (a pin listed as an index, a second index.json, one over 4 MiB); the harness's pin walk over
    sdv/drill/drill-images.json yields read_pins's three pins; the three files have one name in all four places;
  * the harness's command lines (2.1): its two drill.py calls, expanded with its own variables, parse with drill.py's
    parser to what the harness means, with 2.1's options only; the host roles are one set in stack.py, drill.py, the
    updater's choices and schema, and the harness takes two of them;
  * WP1's log as drill.py reads it (2.2; section 1): WP1's own Updater, on the manifest the harness's manifest call writes,
    answers the drill's six records so that drill.py's outcome over WP1's own log, and WP1's status file, give each step
    what drill.EXPECTED (2.2's table) says: the record event's mark, the status event, the refusal steps and the rollback
    event are WP1's, never a copy of the table;
  * the run's record (section 4 item 4): drill.py run by the harness's command line, on a manifest drill.py manifest made
    from build_drill.py's save by the harness's command line and the updater's own check passed, against stand-ins (WP1's
    own unit launcher run in this process, and behind the unit it starts WP1's own `run`, its Updater, on the unit's own
    command line, with a Docker daemon and a heartbeat source standing in), writes exactly the files the harness keeps,
    each on capture.py's whitelist (detach.log never), and a verdict the harness's tool reads; a run whose last step gets
    no answer exits 1 only after writing that record, and the harness takes it as a run that ran;
  * the names: the drill's constants and the updater's and the stack's, the harness's paths, unit and labels, and the
    stack run drill.py reads as stack.py lays it out. `stack.py up` as the harness calls it, run whole through
    stack.main against a Docker stand-in, must leave every container drill.py run requires running.

Every digest, account id and host here is a documentation value, but for spool.py's own sha256 (2.3). Nothing here
starts a process or a container, reaches the network, or writes outside pytest's temporary directory.

Does not demonstrate: that the packages work together on a host (no updater, connector or stack runs here: WP5 and the
drill), that the records mean the same on both sides (only their forms, places and bounds are held), that a status the
connector reports reaches the twin's shadow, that a directory ecrlogin.py logs in to is one a docker pull can use, or
that the updater and the stack read an entry whose existence is in doubt alike (only the safe direction is held). Of the
drill and its harness: anything on an instance (no Docker, systemd, vcan or sudo runs: WP1's Updater runs in this process,
and its Docker daemon and the databroker its health check reads are stand-ins, so no real load, start, heartbeat or
rollback is shown), that the drill passes there, that a real `docker save` has the documentation layout used here, that
stack.py's containers start (stack.main runs against a docker stand-in), or the harness's shell around its tool (its own
tests hold that).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import fnmatch
import hashlib
import importlib
import importlib.util
import inspect
import io
import itertools
import json
import os
import posixpath
import re
import shlex
import stat
import sys
import tarfile
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OTA_DIR = REPO / "sdv" / "ota"
CONNECTOR_DIR = REPO / "sdv" / "connector"
STACK_DIR = REPO / "sdv" / "stack"
ECRLOGIN_FILE = REPO / "sdv" / "cloud" / "ecrlogin.py"

# spec 2.2's table, as written there (the spool and the status as files, the credentials directory with its slash)
SPEC_SPOOL = "/run/sdv-local/spool/v1/desired.json"
SPEC_STATUS = "/run/sdv-local/status/v1/status.json"
SPEC_DOCKER_CONFIG = "/run/sdv-local/ota/docker/"
SPEC_MARKER = "/run/sdv-local/twin-control"
SPEC_RESULTS = ("applied", "rolled-back", "refused")              # spec 2.4
SPEC_STATUS_MAX_BYTES = 256                                       # spec 2.4
SPEC_SPOOL_MAX_BYTES = 256                                        # spec section 3 item 3; limits.SPOOL_MAX_BYTES
# spec 2.3: sdv/connector/spool.py as pinned here is the writer and the definition, and no package changes it
SPEC_SPOOL_PY_SHA256 = "sha256:88deb0049ab01591308ca4577d2953c59807e233336222b3ff05b7328acd073e"
# spec 2.6, word for word around <COMMON exactly as stack.COMMON> [--cpuset-cpus <cpuset>]
SPEC_START_HEAD = "run -d --name sdv-ota-app --label sdv.ota.app={name} --label sdv.ota.image={image_id}"
SPEC_START_TAIL = ("--network host --read-only --tmpfs /out:rw,nosuid,nodev,noexec,size=16m -e APP_IMAGE_ID={image_id} "
                   "-e KUKSA_ADDRESS=127.0.0.1:55555 -e HBH_LOG=/out/hard-brake-hazard.jsonl --restart no {reference}")

APP = "hard-brake-hazard"
IMG_A = "sha256:" + "0" * 64
IMG_B = "sha256:" + "0123456789abcdef" * 4
IMG_F = "sha256:" + "f" * 64
STORE = "sha256:" + "5e" * 32
REGISTRY = "123456789012.dkr.ecr.us-east-1.amazonaws.com"          # AWS's documentation account id
ECR_REF = REGISTRY + "/sdv-twin/hard-brake-hazard@sha256:" + "d1" * 32
S42 = "20990101-sigsim-42"
LONGEST = "a" + "-" * 47                                          # the longest scenario name: 48 characters
RUN_REQUIRED = ["--manifest", "m.json", "--host-role", "pc", "--arch", "amd64", "--state", "state"]
# WP1's status writer sets the file's mode with os.fchmod, which Windows Python lacks: a case that has it write runs on POSIX
WRITES_STATUS = pytest.mark.skipif(not hasattr(os, "fchmod"), reason="WP1's status writer calls os.fchmod: the updater runs on Linux")


def _import(directory: Path, name: str) -> Any:
    """A module imported as its own package imports it: by name, from its own directory, and from no other."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    try:
        mod = importlib.import_module(name)
    finally:
        sys.dont_write_bytecode = saved
    assert Path(str(mod.__file__)).resolve().parent == directory.resolve(), (name, mod.__file__)
    return mod


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


@pytest.fixture(scope="module")
def ota() -> Any:
    """WP1's entry point, as the unit imports it."""
    return _import(OTA_DIR, "ota_lite")


@pytest.fixture(scope="module")
def status() -> Any:
    """WP2's reader of the status record."""
    return _import(CONNECTOR_DIR, "status")


@pytest.fixture(scope="module")
def spool() -> Any:
    """The spool record's writer and definition (spec 2.3; unchanged by every package)."""
    return _import(CONNECTOR_DIR, "spool")


@pytest.fixture(scope="module")
def connector() -> Any:
    """WP2's connector, for the directories it reads and writes by default."""
    return _import(CONNECTOR_DIR, "connector")


@pytest.fixture(scope="module")
def stack() -> Any:
    return _import(STACK_DIR, "stack")


@pytest.fixture(scope="module")
def ecrlogin() -> Any:
    """WP4's login, by its file, as tests/test_sdv_ecrlogin.py loads it."""
    return _load("sdv_cloud_ecrlogin_for_the_phase6_contract", ECRLOGIN_FILE)


def _norm(path: Any) -> str:
    return posixpath.normpath(str(path))


# ============================================================ the status record (spec 2.4): WP1 writes, WP2 reads

def test_the_status_record_is_one_record_on_both_sides(ota, status, connector, stack):
    """The file, the directory and the bound WP1 writes to are the ones WP2 reads, and 2.2's and 2.4's: the updater's
    default, the connector's default, and the path the stack mounts the host's status directory at in the connector."""
    assert ota.STATUS_FILE == status.FILE == posixpath.basename(SPEC_STATUS)
    want = posixpath.dirname(SPEC_STATUS)
    assert ota.STATUS_DIR == status.DEFAULT_STATUS_DIR == connector.DEFAULT_STATUS == stack.CONNECTOR_MOUNTS["status"] == want
    assert ota.STATUS_MAX_BYTES == status.MAX_BYTES == SPEC_STATUS_MAX_BYTES
    assert tuple(ota.RESULTS) == tuple(status.RESULTS) == SPEC_RESULTS
    assert tuple(status.KEYS) == ("image_id", "scenario", "result")
    assert ota.STATUS_TMP != status.FILE and "/" not in ota.STATUS_TMP          # the rename's source is never the reader's file


@WRITES_STATUS
@pytest.mark.parametrize("image_id,scenario,result", list(itertools.product(
    [None, IMG_A, IMG_B], [None, "0", "a-", S42, LONGEST], SPEC_RESULTS)))
def test_every_status_wp1_writes_wp2_reads_back_with_the_same_values(ota, status, tmp_path, image_id, scenario, result):
    path = ota.write_status(tmp_path, image_id, scenario, result)
    assert path == tmp_path / status.FILE and len(path.read_bytes()) <= status.MAX_BYTES
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o644                    # 2.2, 2.4: the connector's user reads it
    got = status.read(tmp_path)
    assert got == ({"image_id": image_id, "scenario": scenario, "result": result}, None)
    assert got.record is not None and list(got.record) == list(status.KEYS)


@WRITES_STATUS
def test_a_status_read_while_wp1_writes_gets_the_last_record_whole(ota, status, tmp_path, monkeypatch):
    """WP1 writes through its temporary file and a rename; WP2 reads only status.json: a read at any moment of a write
    gets the last record whole, then the new one."""
    ota.write_status(tmp_path, IMG_A, None, "applied")
    seen: List[Any] = []
    real = ota.os.replace

    def replace(src: Any, dst: Any) -> None:
        seen.append(status.read(tmp_path))          # the new record is written in full, not yet renamed
        real(src, dst)
    monkeypatch.setattr(ota.os, "replace", replace)
    ota.write_status(tmp_path, IMG_B, S42, "rolled-back")
    monkeypatch.undo()
    assert seen == [({"image_id": IMG_A, "scenario": None, "result": "applied"}, None)]
    assert status.read(tmp_path) == ({"image_id": IMG_B, "scenario": S42, "result": "rolled-back"}, None)


# Each value WP2's reader refuses, by the key it is refused for (status.REASONS: image_id, scenario, result); a record
# of another layout (another key set, a duplicate key, not UTF-8, not one object, too large) WP1 cannot write: its
# writer takes the three values only and encodes them itself, and the longest record it can write is held above.
STATUS_REFUSALS = [
    ("image_id", "sha256:" + "A" * 64, "upper-case-hex"),
    ("image_id", "sha256:" + "0" * 63, "63-digits"),
    ("image_id", "sha256:" + "0" * 65, "65-digits"),
    ("image_id", IMG_A + "\n", "a-trailing-newline"),
    ("image_id", "0" * 64, "no-prefix"),
    ("image_id", "sha512:" + "0" * 64, "another-algorithm"),
    ("image_id", " " + IMG_A, "a-leading-space"),
    ("image_id", "", "empty"),
    ("image_id", 0, "a-number"),
    ("image_id", True, "a-boolean"),
    ("image_id", [IMG_A], "a-list"),
    ("scenario", "", "empty"),
    ("scenario", "-a", "a-leading-dash"),
    ("scenario", "A", "upper-case"),
    ("scenario", "a" * 49, "49-characters"),
    ("scenario", "a/b", "a-slash"),
    ("scenario", "a.b", "a-dot"),
    ("scenario", "a b", "a-space"),
    ("scenario", "a_b", "an-underscore"),
    ("scenario", "a\n", "a-trailing-newline"),
    ("scenario", "café", "not-ascii"),
    ("scenario", 1, "a-number"),
    ("scenario", {"name": "a"}, "an-object"),
    ("result", "Applied", "capitalised"),
    ("result", "rolled_back", "an-underscore"),
    ("result", "applied\n", "a-trailing-newline"),
    ("result", "ok", "another-word"),
    ("result", "", "empty"),
    ("result", None, "null"),
    ("result", 0, "a-number"),
    ("result", ["applied"], "a-list"),
    ("image_id", "sha256:" + "0" * 64 + " ", "a-trailing-space"),
    ("image_id", "SHA256:" + "0" * 64, "upper-case-prefix"),
    ("image_id", {"digest": IMG_A}, "an-object"),
    ("scenario", "a\t", "a-tab"),
    ("scenario", "a\\b", "a-backslash"),
    ("scenario", True, "a-boolean"),
    ("result", "APPLIED", "upper-case"),
    ("result", "rolled-back ", "a-trailing-space"),
    ("result", True, "a-boolean"),
]


@WRITES_STATUS
@pytest.mark.parametrize("key,value", [(k, v) for k, v, _ in STATUS_REFUSALS], ids=["%s-%s" % (k, i) for k, _, i in STATUS_REFUSALS])
def test_every_value_wp2_refuses_wp1_never_writes(ota, status, tmp_path, key, value):
    rec = {"image_id": IMG_A, "scenario": S42, "result": "applied"}
    rec[key] = value
    assert status.parse(json.dumps(rec, separators=(",", ":")).encode("ascii")) == (None, key)     # WP2 refuses it, for that key
    before = ota.write_status(tmp_path, IMG_B, None, "refused").read_bytes()
    with pytest.raises(ota.StatusRefused):
        ota.write_status(tmp_path, rec["image_id"], rec["scenario"], rec["result"])
    assert sorted(p.name for p in tmp_path.iterdir()) == [status.FILE]              # no temporary file left
    assert (tmp_path / status.FILE).read_bytes() == before
    assert status.read(tmp_path) == ({"image_id": IMG_B, "scenario": None, "result": "refused"}, None)


# ============================================================ the spool record (spec 2.3): spool.py writes, WP1 reads

def test_the_spool_record_is_one_record_on_both_sides(ota, spool, connector, stack):
    """The file, the directory and the bound spool.py writes to (in the connector's container, at the same path as on the
    host, 2.2) are the ones WP1 reads, and 2.2's."""
    limits = _import(CONNECTOR_DIR, "limits")
    assert ota.SPOOL_FILE == spool.FILE == posixpath.basename(SPEC_SPOOL)
    want = posixpath.dirname(SPEC_SPOOL)
    assert ota.SPOOL_DIR == connector.DEFAULT_SPOOL == stack.CONNECTOR_MOUNTS["spool"] == want
    assert ota.SPOOL_MAX_BYTES == limits.SPOOL_MAX_BYTES == SPEC_SPOOL_MAX_BYTES
    assert len(spool.encode(spool.record(IMG_F, LONGEST))) <= ota.SPOOL_MAX_BYTES     # the longest record spool.py writes


def test_spool_py_is_the_definition_2_3_names_byte_for_byte(spool):
    """Spec 2.3: spool.py as pinned is the spool record's writer and definition, and no package changes it, a docstring
    included. Both connector images bake it in (build_image.MODULES), and on the host the image's copy writes the spool,
    so the records this file holds WP1's reader against are the writer's only while the tree's bytes are 2.3's. A change
    to spool.py is a connector rebuild with new pins (images.json's own about) and a new value here, together.
    build_image.py is read, not imported: sdv/bridge has a module of that name too."""
    tree = ast.parse((CONNECTOR_DIR / "build_image.py").read_text(encoding="utf-8"))
    modules = [ast.literal_eval(n.value) for n in tree.body
               if isinstance(n, ast.Assign) and [getattr(t, "id", None) for t in n.targets] == ["MODULES"]]
    assert len(modules) == 1 and "spool.py" in modules[0]
    assert "sha256:" + hashlib.sha256(Path(str(spool.__file__)).read_bytes()).hexdigest() == SPEC_SPOOL_PY_SHA256


@pytest.mark.parametrize("image_id,scenario", [(IMG_A, None), (None, "0"), (IMG_B, S42), (IMG_F, LONGEST), (None, "z" * 48)])
def test_every_record_spool_writes_wp1s_reader_reads_back_as_written(ota, spool, tmp_path, image_id, scenario):
    spool.write(tmp_path, spool.record(image_id, scenario))
    data = ota.read_spool(tmp_path)
    assert data == spool.encode({"image_id": image_id, "scenario": scenario})
    assert ota.parse_spool(data) == {"image_id": image_id, "scenario": scenario}


# Records spool.py's rules refuse (spool.problems), each as a writer that did not check would put it in the file, in
# spool.py's own encoding.
SPOOL_REFUSALS = [
    ({"image_id": IMG_A}, "one-field"),
    ({}, "no-field"),
    ({"image_id": IMG_A, "scenario": None, "version": None}, "a-third-field"),
    ({"image": IMG_A, "scenario": None}, "another-field-name"),
    ({"image_id": None, "scenario": None}, "both-null"),
    ({"image_id": "sha256:" + "A" * 64, "scenario": None}, "image-upper-case-hex"),
    ({"image_id": "sha256:" + "0" * 63, "scenario": None}, "image-63-digits"),
    ({"image_id": IMG_A + "\n", "scenario": None}, "image-a-trailing-newline"),
    ({"image_id": "0" * 64, "scenario": None}, "image-no-prefix"),
    ({"image_id": "hard-brake-hazard:1.1.0", "scenario": None}, "image-a-tag"),
    ({"image_id": 0, "scenario": None}, "image-a-number"),
    ({"image_id": True, "scenario": None}, "image-a-boolean"),
    ({"image_id": None, "scenario": ""}, "scenario-empty"),
    ({"image_id": None, "scenario": "-a"}, "scenario-a-leading-dash"),
    ({"image_id": None, "scenario": "A"}, "scenario-upper-case"),
    ({"image_id": None, "scenario": "a" * 49}, "scenario-49-characters"),
    ({"image_id": None, "scenario": "../a"}, "scenario-a-path"),
    ({"image_id": None, "scenario": "a.b"}, "scenario-a-dot"),
    ({"image_id": None, "scenario": "a\\b"}, "scenario-a-backslash"),
    ({"image_id": None, "scenario": "a b"}, "scenario-a-space"),
    ({"image_id": None, "scenario": "a\n"}, "scenario-a-trailing-newline"),
    ({"image_id": None, "scenario": "café"}, "scenario-not-ascii"),
    ({"image_id": None, "scenario": ["a"]}, "scenario-a-list"),
    ({"image_id": "sha256:" + "A" * 64, "scenario": "-a"}, "both-wrong"),
    ({"image_id": IMG_A + " ", "scenario": None}, "image-a-trailing-space"),
    ({"image_id": "sha256:" + "0" * 65, "scenario": None}, "image-65-digits"),
    ({"image_id": None, "scenario": "a\t"}, "scenario-a-tab"),
    ({"image_id": None, "scenario": True}, "scenario-a-boolean"),
    ({"image_id": [IMG_A], "scenario": None}, "image-a-list"),
    ([IMG_A, None], "a-list"),
    (IMG_A, "a-string"),
    (None, "null"),
    (7, "a-number"),
]


@pytest.mark.parametrize("rec", [r for r, _ in SPOOL_REFUSALS], ids=[i for _, i in SPOOL_REFUSALS])
def test_every_record_spool_refuses_wp1s_reader_refuses_for_the_same_findings(ota, spool, tmp_path, rec):
    found = spool.problems(rec)
    assert found
    with pytest.raises(spool.SpoolRefused):
        spool.write(tmp_path, rec)
    assert list(tmp_path.iterdir()) == []                                           # spool.py wrote nothing
    (tmp_path / spool.FILE).write_bytes(json.dumps(rec, separators=(",", ":")).encode("ascii"))
    with pytest.raises(ota.SpoolRefused) as refused:
        ota.parse_spool(ota.read_spool(tmp_path))
    if isinstance(rec, dict):
        assert (refused.value.step, refused.value.reason) == ("3", "; ".join(found))  # the form's rules: spool.py's findings
    else:
        assert refused.value.step == "2"                                            # not one JSON object: before the form


# ============================================================ the app's start (spec 2.6)

def _spec_start(stack: Any, name: str, image_id: str, reference: str, cpuset: Any) -> List[str]:
    values = {"name": name, "image_id": image_id, "reference": reference}
    return (SPEC_START_HEAD.format(**values).split() + list(stack.COMMON) + (["--cpuset-cpus", cpuset] if cpuset is not None else [])
            + SPEC_START_TAIL.format(**values).split())


@pytest.mark.parametrize("name,image_id,reference,cpuset", [
    (APP, IMG_A, STORE, None), (APP, IMG_B, STORE, "3,5"), (APP, IMG_F, ECR_REF, "5"), ("other-app", IMG_A, ECR_REF, None),
], ids=["store-id", "store-id-cpuset", "ecr-reference-cpuset", "another-app-ecr-reference"])
def test_the_apps_start_holds_stack_common_verbatim_and_the_specs_flags_in_order(ota, stack, name, image_id, reference, cpuset):
    argv = ota.app_run_argv(name, image_id, reference, cpuset)
    assert argv == _spec_start(stack, name, image_id, reference, cpuset)
    n = len(stack.COMMON)
    at = [i for i in range(len(argv) - n + 1) if argv[i:i + n] == list(stack.COMMON)]
    assert at == [SPEC_START_HEAD.count(" ") + 1]                                   # once, right after the two labels
    flags = argv[at[0]:argv.index("--network")]
    assert flags == stack.common_flags(types.SimpleNamespace(cpuset=cpuset))        # the stack's own COMMON and cpuset


# ============================================================ the twin-control marker (spec 2.2, 2.7)

def test_the_twin_control_markers_default_is_one_in_sdv_ota_and_sdv_stack(ota, stack, monkeypatch):
    monkeypatch.delenv(stack.TWIN_CONTROL_ENV, raising=False)
    assert ota.TWIN_CONTROL_MARKER == stack.TWIN_CONTROL_MARKER == SPEC_MARKER
    assert stack.twin_control_marker() == Path(SPEC_MARKER)
    run = ota.build_parser().parse_args(["run"] + RUN_REQUIRED)
    unit = ota.build_parser().parse_args(["unit", "start"] + RUN_REQUIRED)
    assert run.marker == unit.marker == SPEC_MARKER
    assert inspect.signature(ota.Updater).parameters["marker"].default == SPEC_MARKER


def test_no_other_twin_control_path_stands_in_sdv_ota_or_sdv_stack():
    """Every string constant of the two packages' modules that names a path under /run/sdv-local/twin is 2.2's marker,
    so no module (step3.py included, which reads the marker through stack.py) has a default of its own."""
    found: Dict[str, Set[str]] = {}
    for package in (OTA_DIR, STACK_DIR):
        for path in sorted(package.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/run/sdv-local/twin"):
                    found.setdefault(node.value, set()).add(package.name)
    assert found == {SPEC_MARKER: {"ota", "stack"}}, found                          # in both packages, and no other path


# Spec 2.2 says only that the marker's existence is the mode. An entry plainly there (a file, a directory, a link to a
# file) or plainly absent gets one answer on both sides (True: the marker). For an entry whose existence is in doubt (a
# link to nothing, a link loop, a parent that cannot be searched; None) the updater (os.path.exists) and the stack (lstat,
# and an entry it cannot look for counts) may answer apart, but only one way: the updater never takes a scenario request
# while the stack would let a bridge start.
MARKER_KINDS = {"absent": False, "a-file": True, "a-directory": True, "a-link-to-a-file": True,
                "a-dangling-link": None, "a-link-loop": None, "an-unsearchable-parent": None}


class _NoApp:
    """Docker as the updater asks it during a scenario-only record: no sdv-ota-app runs."""

    def status(self, name: str) -> None:
        return None


def _marker_entry(base: Path, kind: str) -> Path:
    base.mkdir()
    marker = base / "twin-control"
    if kind == "a-file":
        marker.write_bytes(b"")
    elif kind == "a-directory":
        marker.mkdir()
    elif kind == "a-link-to-a-file":
        (base / "real").write_bytes(b"")
        marker.symlink_to(base / "real")
    elif kind == "a-dangling-link":
        marker.symlink_to(base / "nowhere")
    elif kind == "a-link-loop":
        marker.symlink_to(marker)
    elif kind == "an-unsearchable-parent":                     # as root the parent is searchable: a plain file then
        (base / "shut").mkdir()
        marker = base / "shut" / "twin-control"
        marker.write_bytes(b"")
        marker.parent.chmod(0)
    return marker


@pytest.mark.skipif(sys.platform == "win32", reason="links, modes and the scenario lock's flock are POSIX's")
@pytest.mark.parametrize("kind", list(MARKER_KINDS))
def test_the_updater_never_takes_a_scenario_while_the_stack_would_let_a_bridge_start(ota, stack, spool, tmp_path, monkeypatch, kind):
    """The real Updater, over a scenario-only record spool.py writes (a defined scenario, its recording's sha256 right,
    a free lock, no app running), takes it exactly when it sees the marker; the stack's refusal that every bridge start
    calls (refuse_twin_control) is asked about the same path."""
    recording, lock = tmp_path / "recording.bin", tmp_path / "scenario.lock"
    recording.write_bytes(b"recording")
    lock.write_bytes(b"")
    dirs = {d: tmp_path / d for d in ("spool", "status", "runtime", "state")}
    for d in dirs.values():
        d.mkdir()
    manifest = {"components": [], "scenarios": [
        {"name": S42, "recording": {"path": str(recording), "sha256": "sha256:" + hashlib.sha256(b"recording").hexdigest()}}]}
    marker = _marker_entry(tmp_path / "m", kind)
    monkeypatch.setenv(stack.TWIN_CONTROL_ENV, str(marker))
    try:
        updater = ota.Updater(manifest, dirs["state"], spool_dir=dirs["spool"], status_dir=dirs["status"],
                              runtime_dir=dirs["runtime"], docker_config=tmp_path / "docker", marker=marker, lock=lock, docker=_NoApp())
        spool.write(dirs["spool"], spool.record(None, S42))
        result = updater.poll_once()
        try:
            stack.refuse_twin_control()
            bridge_starts = True
        except stack.StackError:
            bridge_starts = False
    finally:
        marker.parent.chmod(0o700)
    log = [json.loads(line) for line in (dirs["state"] / ota.LOG_FILE).read_text(encoding="utf-8").splitlines()]
    no_marker = [e for e in log if e["event"] == "refused" and e["step"] == "8" and "no twin-control marker" in e["reason"]]
    assert result in ("applied", "refused") and (result == "refused") == bool(no_marker)    # refused for the marker alone
    takes = result == "applied"
    assert not (takes and bridge_starts), kind
    if MARKER_KINDS[kind] is not None:
        assert takes == (not bridge_starts) == MARKER_KINDS[kind], kind


# ============================================================ the registry credentials directory (spec 2.2)

def test_ecrlogins_and_the_updaters_default_credentials_directory_are_2_2s(ota, ecrlogin, monkeypatch):
    want = _norm(SPEC_DOCKER_CONFIG)
    assert _norm(ecrlogin.DOCKER_CONFIG_DIR) == _norm(ota.DOCKER_CONFIG_DIR) == want
    seen: List[Any] = []
    monkeypatch.setattr(ecrlogin, "login", lambda config, device, docker_config, prefix, **_kw: seen.append(("login", docker_config)) or "-")
    monkeypatch.setattr(ecrlogin, "logout", lambda docker_config, prefix: seen.append(("logout", docker_config)) or False)
    assert ecrlogin.main(["login", "--config", "config.json", "--device", "device"]) == 0
    assert ecrlogin.main(["logout"]) == 0
    assert [(k, _norm(v)) for k, v in seen] == [("login", want), ("logout", want)]
    run = ota.build_parser().parse_args(["run"] + RUN_REQUIRED)
    unit = ota.build_parser().parse_args(["unit", "start"] + RUN_REQUIRED)
    assert _norm(run.docker_config) == _norm(unit.docker_config) == want
    assert _norm(inspect.signature(ota.Updater).parameters["docker_config"].default) == want


# ============================================================ the registry file (spec 2.5; section 5 item 8)

def test_the_registry_file_twinctl_writes_is_the_one_ecrlogin_and_the_updater_read(ota, ecrlogin, tmp_path):
    """`twinctl ecr-config` writes one JSON object (cmd_ecr_config's one dict literal, read here by AST: the writer itself
    runs only against AWS or its stand-in); ecrlogin.read_config takes exactly those keys, and the updater's registry_host
    reads the same file's `registry`. A file of that shape on documentation values, in twinctl's own encoding and mode
    (write_private), is taken by both readers."""
    source = (REPO / "sdv" / "cloud" / "twinctl.py").read_text(encoding="utf-8")
    writer = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "cmd_ecr_config")
    literals = [n for n in ast.walk(writer) if isinstance(n, ast.Dict) and n.keys]
    assert len(literals) == 1
    written = [k.value for k in literals[0].keys if isinstance(k, ast.Constant)]
    assert sorted(written) == sorted(ecrlogin.CONFIG_KEYS) == ["credential_endpoint", "region", "registry", "role_alias"]
    doc = {"credential_endpoint": "aexample000000.credentials.iot.us-east-1.amazonaws.com", "role_alias": ecrlogin.ROLE_ALIAS,
           "region": "us-east-1", "registry": REGISTRY}
    path = tmp_path / "ecr.json"
    path.write_bytes((json.dumps(doc, indent=1) + "\n").encode("ascii"))
    os.chmod(path, 0o600)
    assert ecrlogin.read_config(str(path)) == doc
    if os.name != "nt":                                                                # registry_host holds the mode
        assert ota.registry_host(path) == REGISTRY


# ============================================================ Phase 6 WP3 and WP6: the drill and its bare-metal harness

DRILL_DIR = REPO / "sdv" / "drill"
G_DIR = REPO / "orin-native" / "gpu-concurrency"
HARNESS = G_DIR / "run-ota-drill.sh"
LADDER = REPO / "scripts" / "aws" / "remote-ladder.sh"
CAPTURE = REPO / "scripts" / "aws" / "capture.py"
STACK_FILE = STACK_DIR / "stack.py"
SCHEMA_FILE = OTA_DIR / "manifest.schema.json"
# spec-2 2.1, word for word (the usage block's alignment spaces aside)
SPEC_DRILL = {
    "manifest": "drill.py manifest --host-role R --arch amd64|arm64 --transport local-build|tar|ecr --stack-run DIR --out FILE "
                "[--pins FILE] [--store-ids FILE] [--tar FILE] [--recording DIR]",
    "run": "drill.py run --manifest FILE --state DIR --record DIR --stack-run DIR --sim-python PY --ota-python PY "
           "[--via spool|twin] [--cpuset LIST] [--registry-file F] [--docker-config D] [--home D] "
           "[--spool-dir D] [--status-dir D] [--sudo PREFIX] [--docker PREFIX] [--step-timeout-s N]",
    "compare": "drill.py compare --host ROLE=DIR [--host ROLE=DIR ...] --out DIR",
}
COMMIT = "0123456789abcdef0123456789abcdef01234567"                # a documentation commit
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER = "application/vnd.oci.image.layer.v1.tar"
# the harness phase's environment for run-ota-drill.sh (remote-ladder.sh), on documentation paths: words only, nothing is made
SESSION = {"W": "/session/a1", "OUT": "/session/a1/rec/ota-drill/raw", "STATUS": "/session/a1/rec/ota-drill/status",
           "DRILL_IN": "/session/a1/drill-in", "VSS_HOME": "/session/a1/sdv"}
RUN_NAME = "20990101-"                       # the up run's directory: <YYYYMMDD>-<the harness's STACK_NAME>, a far date
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="the manifest's path form, the launcher's uid and modes are POSIX's")
STACK_POSIX = pytest.mark.skipif(not hasattr(os, "getuid"), reason="stack.py's start() runs containers as os.getuid()'s user: POSIX's")


@pytest.fixture(scope="module")
def drill() -> Any:
    """WP3's drill.py, by name from sdv/drill as its command line imports it (and build_drill.py imports it)."""
    return _import(DRILL_DIR, "drill")


@pytest.fixture(scope="module")
def bd(drill) -> Any:
    """WP3's build_drill.py."""
    return _import(DRILL_DIR, "build_drill")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --- the harness, read as bash reads it ------------------------------------------------------------------------------

def _sh(path: Path = HARNESS) -> str:
    return path.read_text(encoding="utf-8")


def _sh_vars(text: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """A script's top-level assignments (column 0): its scalars, unquoted, without a trailing comment (a command
    substitution is left out), and its arrays' words."""
    arrays = {m.group(1): m.group(2).split() for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=\(([^)]*)\)", text, re.M)}
    scalars: Dict[str, str] = {}
    for m in re.finditer(r'^([A-Z][A-Z0-9_]*)=(?:"([^"]*)"|([^\s"(]*))[ \t]*(?:#.*)?$', text, re.M):
        if "$(" not in (m.group(2) or ""):
            scalars[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return scalars, arrays


_SH_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?-)([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand(word: str, env: Dict[str, str], scalars: Dict[str, str]) -> str:
    """A word of the harness with its variables expanded as bash would: env first (the phase's, and what the harness sets
    while it runs), then the harness's own top-level scalars; a variable that neither sets fails the test."""
    def one(m: Any) -> str:
        name = m.group(1) or m.group(4)
        value = env[name] if name in env else _expand(scalars[name], env, scalars) if name in scalars else None
        if (m.group(2) == "-" and value is None) or (m.group(2) == ":-" and not value):
            return _expand(m.group(3), env, scalars)
        assert value is not None, "the harness reads %s, which neither the phase nor the harness sets" % name
        return value
    return _SH_VAR.sub(one, word)


def _sh_function(text: str, name: str) -> str:
    m = re.search(r"^%s\(\) \{(.*?)^\}$" % re.escape(name), text, re.M | re.S)
    assert m is not None, name
    return m.group(1)


def _drill_calls(env: Dict[str, str]) -> Dict[str, List[str]]:
    """The harness's drill.py command lines (`"$DRILL" CMD ... < /dev/null`), each word expanded: CMD -> argv."""
    text = _sh()
    scalars, _arrays = _sh_vars(text)
    calls: Dict[str, List[str]] = {}
    for m in re.finditer(r'"\$DRILL" ([a-z]+) (.*?) < /dev/null', re.sub(r"\\\n[ \t]*", " ", text)):
        assert m.group(1) not in calls, m.group(1)
        calls[m.group(1)] = [m.group(1)] + [_expand(w, env, scalars) for w in shlex.split(m.group(2))]
    return calls


def _harness_tool(tmp_path: Path) -> Any:
    """The harness's own drill-tool.py, as write_tool writes it (the heredoc between <<'PY' and PY), from a copy here."""
    m = re.search(r"<<'PY'\n(.*?)\nPY\n", _sh(), re.S)
    assert m is not None
    path = tmp_path / "drill-tool.py"
    path.write_bytes((m.group(1) + "\n").encode("utf-8"))
    return _load("run_ota_drill_tool_for_the_phase6_contract", path)


def _tool(tool: Any, capsys: Any, monkeypatch: Any, *argv: Any) -> Tuple[int, str]:
    """One `tool CMD ARGS...` of the harness: its exit status and its output (a refusal's reason is its one line), with
    vss_setup.py beside the harness (DRILL_HERE) for its facts; the path entry and the module it adds are undone."""
    monkeypatch.setenv("DRILL_HERE", str(G_DIR))
    capsys.readouterr()
    path, mods = list(sys.path), set(sys.modules)
    try:
        rc = tool.main([str(a) for a in argv])
    finally:
        sys.path[:] = path
        for k in set(sys.modules) - mods:
            f = getattr(sys.modules[k], "__file__", None)
            if f and Path(f).resolve().parent == G_DIR.resolve():
                del sys.modules[k]
    return rc, capsys.readouterr().out


def _capture_excluded() -> Callable[[str], str]:
    """capture.py's vss_excluded over its VSS_WHITELIST, NEVER_DIRS and NEVER_FILES, cut out of its source (the script
    runs at import): why a vss record leaves a path out, "" when it publishes it."""
    tree = ast.parse(CAPTURE.read_text(encoding="utf-8"))
    names = ("VSS_WHITELIST", "NEVER_DIRS", "NEVER_FILES")
    keep: List[ast.stmt] = [n for n in tree.body
                            if (isinstance(n, ast.Assign) and [getattr(t, "id", None) for t in n.targets] in [[x] for x in names])
                            or (isinstance(n, ast.FunctionDef) and n.name == "vss_excluded")]
    assert len(keep) == 4
    ns: Dict[str, Any] = {"fnmatch": fnmatch}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(CAPTURE), "exec"), ns)
    return ns["vss_excluded"]


# --- the drill's images, as the containerd store keeps them, and docker save's tar of them ---------------------------

def _image(version: str, layers: Sequence[bytes], entrypoint: Sequence[str]) -> Dict[str, Any]:
    config = json.dumps({"architecture": "arm64", "os": "linux", "config": {"Entrypoint": list(entrypoint)},
                         "rootfs": {"type": "layers", "diff_ids": [_sha256(x) for x in layers]}}, sort_keys=True).encode("ascii")
    manifest = json.dumps({"schemaVersion": 2, "mediaType": OCI_MANIFEST,
                           "config": {"mediaType": OCI_CONFIG, "digest": _sha256(config), "size": len(config)},
                           "layers": [{"mediaType": OCI_LAYER, "digest": _sha256(x), "size": len(x)} for x in layers]},
                          sort_keys=True).encode("ascii")
    return {"version": version, "id": _sha256(manifest), "config_digest": _sha256(config), "manifest": manifest, "config": config,
            "layers": list(layers)}


APP_ENTRYPOINT = ["python", "/app/app.py"]                     # the drill's app: it runs and publishes its heartbeat
BROKEN_ENTRYPOINT = ["python", "-c", "raise SystemExit(3)"]     # v3's: it exits at once, before any heartbeat


def _drill_images() -> List[Dict[str, Any]]:
    """Spec-2 2.3's three on documentation bytes: v2 is v1 plus one layer, v3 is v2 with another entrypoint and no layer."""
    one, two = b"the drill's v1 layer (documentation bytes)\n", b"the layer v2 adds: /app/hazard.py (documentation bytes)\n"
    return [_image("1.0.0", [one], APP_ENTRYPOINT), _image("1.1.0", [one, two], APP_ENTRYPOINT),
            _image("1.2.0", [one, two], BROKEN_ENTRYPOINT)]


def _desc(img: Dict[str, Any]) -> Dict[str, Any]:
    return {"mediaType": OCI_MANIFEST, "digest": img["id"], "size": len(img["manifest"])}


def _save_files(images: Sequence[Dict[str, Any]]) -> Dict[str, bytes]:
    """`docker save ID...` under the containerd image store: oci-layout, index.json listing each image's manifest, the
    legacy manifest.json and every blob once."""
    files = {"oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
             "index.json": json.dumps({"schemaVersion": 2, "mediaType": OCI_INDEX, "manifests": [_desc(i) for i in images]}).encode("ascii"),
             "manifest.json": json.dumps([{"Config": "blobs/sha256/" + i["config_digest"][7:], "RepoTags": None,
                                           "Layers": ["blobs/sha256/" + _sha256(x)[7:] for x in i["layers"]]}
                                          for i in images]).encode("ascii")}
    for i in images:
        for data in [i["manifest"], i["config"]] + i["layers"]:
            files["blobs/sha256/" + _sha256(data)[7:]] = data
    return files


def _tar_bytes(files: Dict[str, bytes], prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for d in ("blobs", "blobs/sha256"):
            ti = tarfile.TarInfo(prefix + d)
            ti.type, ti.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(ti)
        for name, data in files.items():
            ti = tarfile.TarInfo(prefix + name)
            ti.size, ti.mode = len(data), 0o644
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def _pins_record(bd: Any, images: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """build_drill.py build --arch arm64's record of these images, in build_on's form, for its pins_doc."""
    def pair(i: Dict[str, Any]) -> Dict[str, str]:
        return {"id": i["id"], "config_digest": i["config_digest"]}
    v1, v2, v3 = images
    return {"pins": {"1.0.0": dict(pair(v1), tag="sdv-local/hard-brake-hazard:1.0.0-arm64"),
                     "1.1.0": dict(pair(v2), tag=bd.TAG % "1.1.0-arm64", base=pair(v1)),
                     "1.2.0": dict(pair(v3), tag=bd.TAG % "1.2.0-arm64", base=pair(v2))},
            "edits": [[old.strip(), new.strip()] for old, new in bd.EDITS], "v3_entrypoint": list(bd.V3_ENTRYPOINT)}


class _SaveStore:
    """docker for build_drill.py save: `save -o TAR ID...` writes docker save's tar of those IDs of this store."""

    def __init__(self, drill: Any, images: Sequence[Dict[str, Any]]) -> None:
        self.drill, self.by_id = drill, {i["id"]: i for i in images}

    def run(self, args: Sequence[str], timeout: float = 0.0) -> Any:
        assert list(args[:2]) == ["save", "-o"], args
        Path(args[2]).write_bytes(_tar_bytes(_save_files([self.by_id[i] for i in args[3:]])))
        return self.drill.Done(0, "", "")


def _saved(drill: Any, bd: Any, monkeypatch: Any, capsys: Any, drill_in: Path, images: Sequence[Dict[str, Any]]) -> str:
    """build_drill.py save as the orchestrator runs it before a session (REPO_COMMIT set, --out DRILL_IN/<the harness's
    tar name>), on a stand-in store of the three images, its pins written by its own pins_doc into drill_in: the tar's
    sha256 it printed."""
    scalars, _arrays = _sh_vars(_sh())
    drill_in.mkdir(parents=True)
    pins = drill_in / drill.PINS_FILE.name
    drill.write_json(pins, bd.pins_doc(_pins_record(bd, images)))
    monkeypatch.setattr(bd, "PINS_FILE", pins)
    monkeypatch.setenv("REPO_COMMIT", COMMIT)
    capsys.readouterr()
    tar = drill_in / posixpath.basename(_expand(scalars["TAR"], SESSION, scalars))
    assert bd.main(["save", "--out", str(tar)], docker=_SaveStore(drill, images)) == 0
    return capsys.readouterr().out.strip()


def _repo_tar(path: Path, commit: str) -> None:
    """A repo tarball as `git archive <commit>` writes it: the commit in its pax global header's comment."""
    with tarfile.open(str(path), "w", format=tarfile.PAX_FORMAT, pax_headers={"comment": commit}) as tf:
        data = b"a repo tarball's member (documentation bytes)\n"
        ti = tarfile.TarInfo("README.md")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))


# --- the session's tar: build_drill.py save, the harness's preflight readers, drill.py's check_save (spec-2 2.3; 4 item 2)

def test_build_drills_save_passes_the_harnesss_preflight_readers_and_drill_pys_check(drill, bd, tmp_path, monkeypatch, capsys):
    """build_drill.py save's tar and two-line sum file and the pins it saved, carried to drill-in/ with inputs.env's FILES
    naming each by its sha256, pass the harness's readers in its preflight's order -- files, tarsum, repocommit (the commits
    agree), pins, tarindex -- and drill.py's check_save (drill.py manifest's check of the --tar) proves the same three."""
    scalars, arrays = _sh_vars(_sh())
    names = arrays["DRILL_FILES"]
    images = _drill_images()
    drill_in = tmp_path / "drill-in"
    printed = _saved(drill, bd, monkeypatch, capsys, drill_in, images)
    assert sorted(p.name for p in drill_in.iterdir()) == sorted(names)            # the save, its sum file, the pins
    pins_file, tar, tarsum = (drill_in / posixpath.basename(_expand(scalars[k], SESSION, scalars)) for k in ("PINS", "TAR", "TARSUM"))
    inputs = tmp_path / "inputs.env"
    inputs.write_bytes(("REPO_COMMIT=%s\nFILES=%s\n" % (COMMIT, " ".join("%s:%s" % (n, _sha256((drill_in / n).read_bytes())[7:])
                                                                          for n in names))).encode("ascii"))
    tool = _harness_tool(tmp_path)
    rc, out = _tool(tool, capsys, monkeypatch, "files", inputs, drill_in, tmp_path / "facts", *names)
    assert rc == 0, out
    tarhex = dict(ln.split() for ln in out.splitlines())[tar.name]
    assert tarhex == printed == _sha256(tar.read_bytes())[7:]
    assert _tool(tool, capsys, monkeypatch, "tarsum", tarsum, tarhex) == (0, COMMIT + "\n")
    _repo_tar(tmp_path / "repo.tar", COMMIT)
    assert _tool(tool, capsys, monkeypatch, "repocommit", tmp_path / "repo.tar") == (0, COMMIT + "\n")
    pins = drill.read_pins(pins_file)
    rc, out = _tool(tool, capsys, monkeypatch, "pins", pins_file)
    assert rc == 0 and out.splitlines() == ["%s %s" % (pins[v]["id"], pins[v]["config_digest"]) for v in drill.VERSIONS], out
    (tmp_path / "pins.txt").write_bytes(out.encode("ascii"))
    assert _tool(tool, capsys, monkeypatch, "tarindex", tar, tmp_path / "pins.txt") == (0, "3\n")
    with drill.OciTar(tar) as t:
        proved = drill.check_save(t, pins, "arm64")
    assert {v: proved[v][2] for v in drill.VERSIONS} == {v: pins[v]["config_digest"] for v in drill.VERSIONS}


def _extra(files: Dict[str, bytes]) -> None:
    other = _image("9.9.9", [b"an image the pins do not hold (documentation bytes)\n"], ["python"])
    files.update(_save_files(_drill_images() + [other]))


def _relist(files: Dict[str, bytes], how: Callable[[List[Any]], Any]) -> None:
    idx = json.loads(files["index.json"])
    idx["manifests"] = how(idx["manifests"])
    files["index.json"] = json.dumps(idx).encode("ascii")


# Saves that differ from build_drill.py save's in their index.json (and one that does not): (case, change, prefix,
# (tarindex takes it, check_save takes it)). The harness's tarindex is check_save's first condition, made before anything
# starts: the two agree on the digests the index lists; a descriptor's media type, a second index.json and index.json's
# size are check_save's alone, like its proofs (blobs, config digests, the architecture).
INDEX_CASES: List[Tuple[str, Callable[[Dict[str, bytes]], Any], str, Tuple[bool, bool]]] = [
    ("as-saved", lambda f: None, "", (True, True)),
    ("listed-in-reverse", lambda f: _relist(f, lambda m: m[::-1]), "", (True, True)),
    ("dot-slash-names", lambda f: None, "./", (True, True)),
    ("a-pin-not-listed", lambda f: _relist(f, lambda m: m[:2]), "", (False, False)),
    ("a-fourth-image-listed", _extra, "", (False, False)),
    ("a-pin-listed-twice", lambda f: _relist(f, lambda m: m + m[:1]), "", (False, False)),
    ("no-index-json", lambda f: f.pop("index.json"), "", (False, False)),
    ("index-json-not-json", lambda f: f.update({"index.json": b"not json"}), "", (False, False)),
    ("manifests-not-a-list", lambda f: _relist(f, lambda m: {}), "", (False, False)),
    ("a-listed-entry-not-an-object", lambda f: _relist(f, lambda m: m + [m[0]["digest"]]), "", (False, False)),
    ("a-layer-not-of-its-digest", lambda f: f.update({"blobs/sha256/" + _sha256(_drill_images()[1]["layers"][1])[7:]: b"x"}), "",
     (True, False)),
    ("a-pin-listed-as-an-index", lambda f: _relist(f, lambda m: [dict(m[0], mediaType=OCI_INDEX)] + m[1:]), "", (True, False)),
    ("a-second-index-json", lambda f: f.update({"./index.json": f["index.json"]}), "", (True, False)),
    ("an-index-json-over-4-mib", lambda f: f.update({"index.json": f["index.json"] + b" " * (4 << 20)}), "", (True, False)),
]


@pytest.mark.parametrize("change,prefix,want", [c[1:] for c in INDEX_CASES], ids=[c[0] for c in INDEX_CASES])
def test_the_harnesss_tarindex_agrees_with_drill_pys_check_save(drill, bd, tmp_path, monkeypatch, capsys, change, prefix, want):
    images = _drill_images()
    pins_file = tmp_path / "drill-images.json"
    drill.write_json(pins_file, bd.pins_doc(_pins_record(bd, images)))
    tool = _harness_tool(tmp_path)
    rc, out = _tool(tool, capsys, monkeypatch, "pins", pins_file)
    assert rc == 0, out
    (tmp_path / "pins.txt").write_bytes(out.encode("ascii"))
    files = _save_files(images)
    change(files)
    tar = tmp_path / "sdv-drill.tar"
    tar.write_bytes(_tar_bytes(files, prefix))
    rc, out = _tool(tool, capsys, monkeypatch, "tarindex", tar, tmp_path / "pins.txt")
    try:
        with drill.OciTar(tar) as t:
            drill.check_save(t, drill.read_pins(pins_file), "arm64")
        taken = True
    except drill.DrillError:
        taken = False
    assert (rc == 0, taken) == want, out


def test_the_harnesss_pin_walk_over_drill_images_json_yields_read_pins_three(drill, tmp_path, monkeypatch, capsys):
    """The pins the session carries are sdv/drill/drill-images.json byte for byte (the preflight's cmp): the harness's walk
    over every object holding an id and a config_digest yields drill.py's three, in order, each once (a base that names a
    version's pair counts once; a base naming another pair would add a fourth and refuse the session's save)."""
    pins = drill.read_pins(drill.PINS_FILE)
    rc, out = _tool(_harness_tool(tmp_path), capsys, monkeypatch, "pins", drill.PINS_FILE)
    assert rc == 0 and out.splitlines() == ["%s %s" % (pins[v]["id"], pins[v]["config_digest"]) for v in drill.VERSIONS], out


# --- the harness's command lines and names (spec-2 2.1; section 4 items 1, 3 and 4) ----------------------------------

def _options(line: str) -> Tuple[Set[str], Set[str]]:
    """A 2.1 line's options, and those outside brackets (required)."""
    return set(re.findall(r"--[a-z][a-z0-9-]*", line)), set(re.findall(r"--[a-z][a-z0-9-]*", re.sub(r"\[[^\]]*\]", "", line)))


def _subparser(parser: Any, path: Sequence[str]) -> Any:
    for name in path:
        parser = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices[name]
    return parser


@pytest.mark.parametrize("vss_host,role", [(None, "a1-metal"), ("c7g-metal", "c7g-metal")], ids=["vss-host-unset", "c7g-metal"])
def test_the_harness_calls_drill_py_by_2_1s_command_lines(drill, ota, vss_host, role):
    """Spec-2 2.1, word for word: drill.py's parser takes exactly the options of 2.1's three lines (compare's too), the
    required ones and the choice words each writes (`--arch amd64|arm64`, `--transport local-build|tar|ecr`, `--via
    spool|twin`); the harness's two calls use only 2.1's options with every required one, and each parses to what the
    harness means: the role VSS_HOST names (unset, a1-metal), tar transport with the session's pins and tar, the up run,
    the updater's spool and status directories, local spool records, `sudo -n`, no CPU list (off the Orin), the design
    value's step timeout (300, which is also drill.py's constant)."""
    env = dict(SESSION, STACK_RUN=SESSION["VSS_HOME"] + "/drill-work/runs/%sota-drill" % RUN_NAME)
    if vss_host is not None:
        env["VSS_HOST"] = vss_host
    calls = _drill_calls(env)
    assert sorted(calls) == ["manifest", "run"]
    for cmd, line in SPEC_DRILL.items():                          # all three of 2.1's lines, compare's too: the parser takes them
        spec, required = _options(line)
        sub = _subparser(drill.build_parser(), [cmd])
        assert {s for a in sub._actions for s in a.option_strings if s.startswith("--") and s != "--help"} == spec, cmd
        assert {s for a in sub._actions for s in a.option_strings if a.required} == required, cmd
        for opt, alts in re.findall(r"(--[a-z][a-z0-9-]*) ([a-z0-9-]+(?:\|[a-z0-9-]+)+)", line):       # 2.1's choice words
            assert set(next(a for a in sub._actions if opt in a.option_strings).choices) == set(alts.split("|")), (cmd, opt)
    assert drill.STEP_TIMEOUT_S == 300                            # 2.1's design value
    got = {}
    for cmd, argv in calls.items():
        spec, required = _options(SPEC_DRILL[cmd])
        used = {w for w in argv if w.startswith("--")}
        assert used <= spec and required <= used, (cmd, sorted(used - spec), sorted(required - used))
        try:
            got[cmd] = drill.build_parser().parse_args(argv)
        except SystemExit:
            pytest.fail("drill.py's parser refuses the harness's %s line: %s" % (cmd, argv))
    work, din, home = SESSION["VSS_HOME"] + "/drill-work", SESSION["DRILL_IN"], SESSION["VSS_HOME"]
    m, r = got["manifest"], got["run"]
    assert (m.host_role, m.arch, m.transport, m.stack_run, m.out) == (role, "arm64", "tar", env["STACK_RUN"], work + "/manifest.json")
    assert (m.pins, m.tar, m.store_ids, m.recording) == (din + "/drill-images.json", din + "/sdv-drill.tar", None, None)
    assert (r.manifest, r.stack_run, r.state, r.record) == (m.out, m.stack_run, work + "/ota-state", work + "/record")
    assert (r.sim_python, r.ota_python) == (home + "/venv/bin/python", home + "/ota-venv/bin/python")
    assert (r.via, shlex.split(r.sudo), r.cpuset, r.registry_file, r.docker, r.step_timeout_s) == (
        "spool", ["sudo", "-n"], None, None, "docker", 300)
    assert r.spool_dir == drill.SPOOL_DIR == ota.SPOOL_DIR and r.status_dir == drill.STATUS_DIR == ota.STATUS_DIR


def test_the_host_roles_are_one_set_in_the_stack_the_drill_the_updater_its_schema_and_the_harness(drill, ota, stack):
    """Spec-2 section 3 item 2 and section 4 item 1: drill.py's roles are stack.py's HOST_ROLES read at run time; the
    updater's (its HOST_ROLES, the choices of check, run and unit start, the manifest schema's host_role enum) are the same
    set, c7g-metal included; the harness takes a1-metal (VSS_HOST unset) and c7g-metal, two of them; the drill's CPU-list
    role is one of them."""
    roles = set(drill.host_roles())
    assert roles == set(stack.HOST_ROLES) == set(ota.HOST_ROLES) and {"a1-metal", "c7g-metal", drill.CPUSET_ROLE} <= roles
    assert set(json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["properties"]["host_role"]["enum"]) == roles
    for path in (["check"], ["run"], ["unit", "start"]):
        assert set(next(a for a in _subparser(ota.build_parser(), path)._actions if "--host-role" in a.option_strings).choices) == roles
    text = _sh()
    arm = re.search(r'case "\$HOST_MODE" in\s*\n\s*([a-z0-9|-]+)\)', _sh_function(text, "host_refusal"))
    assert arm is not None and set(arm.group(1).split("|")) == {"a1-metal", "c7g-metal"} <= roles
    scalars, _arrays = _sh_vars(text)
    assert _expand(scalars["HOST_MODE"], {}, scalars) == "a1-metal"


# drill.py's constants that name what another package defines: (drill.py's name, the package, its name)
DRILL_SAME = [
    ("TWIN_CONTROL_MARKER", "ota", "TWIN_CONTROL_MARKER"), ("SPOOL_DIR", "ota", "SPOOL_DIR"), ("STATUS_DIR", "ota", "STATUS_DIR"),
    ("APP_CONTAINER", "ota", "APP_CONTAINER"), ("UNIT", "ota", "UNIT"), ("LOG_FILE", "ota", "LOG_FILE"),
    ("STATE_FILE", "ota", "STATE_FILE"), ("STATUS_FILE", "ota", "STATUS_FILE"), ("STATUS_MAX_BYTES", "ota", "STATUS_MAX_BYTES"),
    ("REGISTRY_PLACEHOLDER", "ota", "REGISTRY_PLACEHOLDER"), ("STACK_LABEL", "stack", "LABEL"),
    ("TWIN_CONTROL_ENV", "stack", "TWIN_CONTROL_ENV"), ("TWIN_CONTROL_MARKER", "stack", "TWIN_CONTROL_MARKER"), ("VCAN", "stack", "VCAN"),
]


@pytest.mark.parametrize("name,package,theirs", DRILL_SAME, ids=["%s-%s" % (p, n) for n, p, _t in DRILL_SAME])
def test_the_drills_constants_are_the_updaters_and_the_stacks(drill, ota, stack, name, package, theirs):
    assert getattr(drill, name) == getattr({"ota": ota, "stack": stack}[package], theirs)


def test_the_drill_asks_the_updater_it_runs_and_waits_out_every_state_it_calls_active(drill, ota, spool):
    """The updater the drill runs (OTA_LITE) is this tree's sdv/ota/ota_lite.py; every state ota_lite.py calls active the
    drill refuses too (its own list may hold more); the one role on which the updater requires a CPU list is the drill's
    CPUSET_ROLE; the ecr repository the drill names is the updater's prefix and the app; its spool writer is spool.py."""
    assert Path(drill.OTA_LITE).resolve() == Path(str(ota.__file__)).resolve()
    assert set(ota.ACTIVE_STATES) <= set(drill.ACTIVE_STATES)
    needing = []
    for role in ota.HOST_ROLES:
        try:
            ota.cpu_list(None, role, "--cpuset")
        except ValueError:
            needing.append(role)
    assert needing == [drill.CPUSET_ROLE]
    assert drill.ECR_REPOSITORY == ota.ota_manifest.ECR_REPO_PREFIX + drill.APP
    assert drill.spool is spool


def test_the_harness_names_the_drills_files_the_updaters_paths_unit_and_labels(drill, bd, ota, stack):
    """The harness and the ladder name the drill's three files as build_drill.py save and drill.py do (the pins file, the
    save, the save's name + .sha256); the harness's repo paths are this tree's drill.py, stack.py, pins and the updater's
    proof; its spool and status directories, unit, labels and fallback container are the updater's and the drill's; what it
    keeps from the updater's own state directory when a capped drill left no copy is the updater's log and state; and the
    environment names it hands stack.py (the host role in preflight's STACK_ENV, the two directories in unit_up) are the
    names stack.py reads them by."""
    text = _sh()
    scalars, arrays = _sh_vars(text)
    ladder, _ladder_arrays = _sh_vars(_sh(LADDER))
    tar = posixpath.basename(_expand(scalars["TAR"], SESSION, scalars))
    names = [drill.PINS_FILE.name, tar, tar + ".sha256"]
    assert arrays["DRILL_FILES"] == names == ladder["DRILL_FILES"].split()
    assert [posixpath.basename(_expand(scalars[k], SESSION, scalars)) for k in ("PINS", "TAR", "TARSUM")] == names
    repo = _expand(scalars["REPO"], SESSION, scalars)                                 # the session's repo tarball, unpacked
    for var, path in (("DRILL", Path(str(drill.__file__))), ("STACK", Path(drill.STACK_FILE)), ("REPO_PINS", Path(drill.PINS_FILE)),
                      ("OTA_DOCKER", Path(str(ota.ota_docker.__file__)))):
        assert REPO / posixpath.relpath(_expand(scalars[var], SESSION, scalars), repo) == path.resolve(), var
    assert scalars["SPOOL_DIR"] == drill.SPOOL_DIR == ota.SPOOL_DIR and scalars["STATUS_DIR"] == drill.STATUS_DIR == ota.STATUS_DIR
    assert scalars["UNIT"] == drill.UNIT == ota.UNIT
    assert '%s="$HOST_MODE"' % stack.HOST_ROLE_ENV in _sh_function(text, "preflight")          # the names stack.py reads them by
    assert '%s="$SPOOL_DIR" %s="$STATUS_DIR"' % (stack.SPOOL_DIR_ENV, stack.STATUS_DIR_ENV) in _sh_function(text, "unit_up")
    assert arrays["LABELS"] == [ota.APP_LABEL, stack.LABEL] and stack.LABEL == drill.STACK_LABEL
    assert arrays["FALLBACK_NAMES"][0] == ota.APP_CONTAINER == drill.APP_CONTAINER
    fallback = re.search(r"for n in ([^;]+); do", _sh_function(text, "keep_record"))
    assert fallback is not None and fallback.group(1).split() == [ota.LOG_FILE, ota.STATE_FILE] == [drill.LOG_FILE, drill.STATE_FILE]


# --- the stack run drill.py reads, as stack.py lays it out ------------------------------------------------------------

def _stack_run_layout(stack: Any) -> Dict[str, str]:
    """Where stack.py up puts what drill.py run reads, from stack.py's own source: main's one up() call (`up(ctx, a.feed,
    run_dir / "up", "%s/up" % run_dir.name)`: the up directory's name and the run label's form), the staged inputs'
    directory (`self.in_dir = run_dir / "in"`), and the sigsim recording's staged name (LOG_NAMES)."""
    tree = ast.parse(STACK_FILE.read_text(encoding="utf-8"))
    main = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert len(main) == 1
    ups = [n for n in ast.walk(main[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "up"]
    assert len(ups) == 1 and len(ups[0].args) == 4
    up_dir, label = ups[0].args[2], ups[0].args[3]
    assert isinstance(up_dir, ast.BinOp) and isinstance(up_dir.op, ast.Div) and isinstance(up_dir.right, ast.Constant)
    assert isinstance(label, ast.BinOp) and isinstance(label.op, ast.Mod) and isinstance(label.left, ast.Constant)
    ins = [n.value.right.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and len(n.targets) == 1
           and isinstance(n.targets[0], ast.Attribute) and n.targets[0].attr == "in_dir" and isinstance(n.value, ast.BinOp)
           and isinstance(n.value.right, ast.Constant)]
    assert len(ins) == 1
    return {"up": str(up_dir.right.value), "label": str(label.left.value), "in": str(ins[0]), "log": str(stack.LOG_NAMES["sigsim"])}


def _dict_keys(tree: Any, target: str) -> Set[str]:
    """The keys every dict literal stack.py assigns to self.<target> holds (each run kind's writer)."""
    found = [n.value for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Dict)
             and any(isinstance(t, ast.Attribute) and t.attr == target for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
    assert found, target
    return set.intersection(*({str(k.value) for k in d.keys if isinstance(k, ast.Constant)} for d in found))


def _recording_keys(tree: Any) -> Set[str]:
    """The keys every recording dict literal holds that stack.py writes into a dict it assigns to self.scenario: the replay
    writer's (a run with no recording, a live one, writes null there and has none)."""
    found: List[ast.Dict] = []
    for n in ast.walk(tree):
        if not (isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Dict)):
            continue
        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
        if any(isinstance(t, ast.Attribute) and t.attr == "scenario" for t in targets):
            found += [v for k, v in zip(n.value.keys, n.value.values)
                      if isinstance(k, ast.Constant) and k.value == "recording" and isinstance(v, ast.Dict)]
    assert found, "no dict stack.py assigns to self.scenario writes its recording as a dict"
    return set.intersection(*({str(k.value) for k in d.keys if isinstance(k, ast.Constant)} for d in found))


def test_the_stack_run_drill_py_reads_is_the_one_stack_py_writes(drill, stack):
    """drill.py manifest and run read stack.py's run manifest (format, host_role, app: `external`, one of stack.py's app
    modes), its scenario table ownership.json, the staged recording and the up directory as stack.py lays them out, and
    look for the databroker and the CAN provider by stack.py's container names under its run label. Where stack.py has
    more than one writer of the manifest or of the scenario table (a run kind each), the keys held are those every
    writer's literal has. Of the scenario table the keys are held, not their values: scenario, recording, source and
    profile_id, and the replay writer's recording's path, sha256 and format (drill.py passes the format into the
    manifest's scenario entry, where the updater's schema requires it)."""
    tree = ast.parse(STACK_FILE.read_text(encoding="utf-8"))
    lay = _stack_run_layout(stack)
    assert all(lay.values()) and "%s" in lay["label"]
    assert "external" in stack.APP_MODES
    assert {"format", "host_role", "app", "scenario_table"} <= _dict_keys(tree, "manifest")
    assert {"format", "scenario", "recording", "source", "profile_id"} <= _dict_keys(tree, "scenario")
    assert {"path", "sha256", "format"} <= _recording_keys(tree)
    assert drill.DATABROKER_CONTAINER == stack.NAMES[stack.attr.DATABROKER]
    assert drill.CAN_PROVIDER_CONTAINER == stack.NAMES[stack.attr.CAN_PROVIDER]
    assert drill.STACK_LABEL == stack.LABEL


class _StandInError(Exception):
    """A call a stand-in does not know: never the expected failure of the strict xfail below."""


class _StackDaemon:
    """stack.docker replaced by a model of the daemon's containers; no docker command runs. `run -d --name N --label K=V
    ...` makes N, running, with that label (none stops here); `ps`, with or without -a and -q, lists them by `--filter
    label=K` or `label=K=V`, by name (-q's IDs are the names here, as --format {{.Names}}'s); `rm -f` removes; `inspect` and
    `logs` answer for N. Any other call is a _StandInError."""

    def __init__(self) -> None:
        self.labels: Dict[str, str] = {}
        self.calls: List[List[str]] = []

    def __call__(self, *args: str, check: bool = True, timeout: Any = 120) -> Any:
        a = [str(x) for x in args]
        self.calls.append(a)
        out, code = "", 0
        if a[:2] == ["run", "-d"]:
            self.labels[a[a.index("--name") + 1]] = a[a.index("--label") + 1]
            out = "%064x\n" % len(self.calls)
        elif a[:1] == ["ps"]:
            want = a[a.index("--filter") + 1][len("label="):] if "--filter" in a else None
            out = "".join(n + "\n" for n, lab in self.labels.items() if want is None or want in (lab, lab.split("=", 1)[0]))
        elif a[:2] == ["rm", "-f"]:
            for n in a[2:]:
                self.labels.pop(n, None)
        elif a[:1] in (["inspect"], ["logs"]):
            out, code = ("true\n" if a[:1] == ["inspect"] else "", 0) if a[-1] in self.labels else ("", 1)
        else:
            raise _StandInError("a docker call the stack's stand-in does not know: %r" % a)
        return types.SimpleNamespace(args=a, returncode=code, stdout=out, stderr="")


def _stack_up_external(stack: Any, drill: Any, tmp_path: Path, monkeypatch: Any) -> Tuple[int, List[str]]:
    """`stack.py up` as the harness calls it (unit_up's words, expanded with its own variables), run whole through
    stack.main against _StackDaemon: main's own path from its command line through up() and whatever else it calls, start()
    building every container's argv. Replaced is only what reaches past docker: the context (start()'s attributes, a prepare
    that neither pulls nor builds), the host's listeners, vcan0, the waits for a log line or a file (each passes at once) and
    the module's sleep. Returns main's exit status and the containers drill.py run finds up: its own query, `docker ps
    --filter label=<STACK_LABEL>=<run>/up --format {{.Names}}`."""
    text = re.sub(r"\\\n[ \t]*", " ", _sh())
    scalars, _arrays = _sh_vars(_sh())
    m = re.search(r'"\$STACK" up (.*?) < /dev/null', text)
    assert m is not None
    argv = ["up"] + [_expand(w, {}, scalars) for w in shlex.split(m.group(1))]
    daemon = _StackDaemon()
    made: List[Path] = []

    def context(run_dir: Path, _seed: Any, bridge: str, **kw: Any) -> Any:
        made.append(run_dir)
        return types.SimpleNamespace(
            run_dir=run_dir, images=stack.load_images(), image_ids=lambda: {stack.attr.APP: IMG_A, stack.attr.RECORDER: IMG_B},
            in_dir=run_dir / "in", recorded=["Vehicle.Speed"], witness_paths=["Vehicle.Speed"], bridge=bridge, monitor=None,
            monitor_mode="native", guest=None, connector=bool(kw.get("connector")), app=kw.get("app", "stack"),
            components={stack.attr.APP: {"image_id": IMG_A, "config_digest": IMG_F}}, prepare=lambda images="build": None)

    def listeners_now(info: Dict[str, Any], feed: str, suffix: str, allowed: Any = ()) -> None:
        info["listeners" + suffix] = {"ok": True}
    clock = {k: getattr(stack.time, k) for k in dir(stack.time) if not k.startswith("__")}
    clock["sleep"] = lambda _s: None
    for name, value in (("RUNS", tmp_path / "runs"), ("Context", context), ("docker", daemon),
                        ("host_listeners", lambda: {"with_owners": True, "sockets": []}), ("ensure_vcan", lambda: {"created": False}),
                        ("wait_for", lambda *_a, **_kw: None), ("wait_log", lambda *_a, **_kw: None), ("listeners_now", listeners_now),
                        ("time", types.SimpleNamespace(**clock))):
        monkeypatch.setattr(stack, name, value)
    rc = stack.main(argv)
    if len(made) != 1:
        raise _StandInError("stack.main made %d contexts" % len(made))
    listed = daemon("ps", "--filter", "label=%s=%s/up" % (drill.STACK_LABEL, made[0].name), "--format", "{{.Names}}").stdout.split()
    return rc, listed


@STACK_POSIX
def test_stack_py_up_with_an_external_app_starts_the_databroker_and_never_the_app(drill, ota, stack, tmp_path, monkeypatch, capsys):
    """`stack.py up` as the harness calls it, run whole (_stack_up_external), exits 0 and leaves the databroker running under
    the run's `<run>/up` label, where drill.py run looks for it, and never the app, which is the updater's to start. The
    container-set check below runs the same."""
    rc, listed = _stack_up_external(stack, drill, tmp_path, monkeypatch)
    assert rc == 0 and drill.DATABROKER_CONTAINER in listed, listed
    assert stack.NAMES[stack.attr.APP] not in listed and ota.APP_CONTAINER not in listed, listed


@STACK_POSIX
def test_stack_py_up_with_an_external_app_starts_every_container_drill_py_run_requires(drill, stack, tmp_path, monkeypatch, capsys):
    _rc, listed = _stack_up_external(stack, drill, tmp_path, monkeypatch)
    required = {drill.DATABROKER_CONTAINER, drill.CAN_PROVIDER_CONTAINER}
    assert required <= set(listed), sorted(required - set(listed))


# --- a session: the harness's manifest and run calls on build_drill.py's save (spec-2 2.1-2.3; section 4 items 3, 4) -----

class _Daemon:
    """Docker under WP1's own Docker class (sdv/ota/ota_docker.py, docker()), met through its call() and save_blobs(), the
    two that reach a process; nothing runs and nothing is pulled. `load -i TAR` keeps a docker-save tar of one image in the
    store under its manifest digest (the image's ID under the containerd store); `run -d` starts a container from an image
    of the store: one whose entrypoint is the drill's app's runs and publishes a heartbeat at every read (_Heartbeats), any
    other exits at once (v3's); `container inspect` reads its state or its sdv.ota.image label, `image inspect` the store,
    `stop -t N` stops it, `rm` removes a stopped one, `ps -a --filter label=K` lists by label. Any other call fails."""

    def __init__(self, ota: Any) -> None:
        self.ota = ota
        self.versions = {i["config_digest"]: i["version"] for i in _drill_images()}      # the version each image carries
        self.store: Dict[str, Dict[str, bytes]] = {}
        self.containers: Dict[str, Dict[str, Any]] = {}
        self.calls: List[List[str]] = []

    def docker(self) -> Any:
        def call(_d: Any, args: Sequence[str], env: Any = None, timeout: float = 0.0) -> Any:
            return self.call(args)

        def save_blobs(_d: Any, ref: str) -> Dict[str, bytes]:
            if ref not in self.store:
                raise self.ota.ota_docker.DockerError("docker save: exit 1")
            return dict(self.store[ref])
        return type("DaemonDocker", (self.ota.ota_docker.Docker,), {"call": call, "save_blobs": save_blobs})()

    def _load(self, path: str) -> str:
        blobs: Dict[str, bytes] = {}
        index: Any = None
        with tarfile.open(path, "r:") as tf:
            for mem in tf.getmembers():
                name, f = (mem.name[2:] if mem.name.startswith("./") else mem.name), (tf.extractfile(mem) if mem.isreg() else None)
                if f is not None and name == "index.json":
                    index = json.loads(f.read())
                elif f is not None and name.startswith("blobs/sha256/"):
                    blobs["sha256:" + name.rsplit("/", 1)[1]] = f.read()
        [desc] = index["manifests"]
        self.store[desc["digest"]] = blobs
        return str(desc["digest"])

    def call(self, args: Sequence[str]) -> Any:
        a, res = [str(x) for x in args], self.ota.ota_docker.Result
        self.calls.append(a)
        c = self.containers.get(a[-1])
        if a[:2] == ["load", "-i"] and len(a) == 3:
            return res(0, "Loaded image ID: %s\n" % self._load(a[2]), "")
        if a[:3] == ["container", "inspect", "--format"] and len(a) == 5:
            fields = {"{{.State.Status}}": "state", '{{index .Config.Labels "%s"}}' % self.ota.IMAGE_LABEL: "image"}
            return res(0, "%s\n" % c[fields[a[3]]], "") if c is not None else res(1, "", "Error: No such container")
        if a[:4] == ["image", "inspect", "--format", "{{.Id}}"] and len(a) == 5:
            return res(0, a[4] + "\n", "") if a[4] in self.store else res(1, "", "Error: No such image")
        if a[:2] == ["stop", "-t"] and len(a) == 4 and c is not None:
            c["state"] = "exited"
            return res(0, a[3] + "\n", "")
        if a[:1] == ["rm"] and len(a) == 2 and c is not None and c["state"] != "running":
            del self.containers[a[1]]
            return res(0, a[1] + "\n", "")
        if a[:2] == ["run", "-d"]:
            opts = dict(zip(a, a[1:]))
            labels = dict(v.split("=", 1) for k, v in zip(a, a[1:]) if k == "--label")
            env = dict(v.split("=", 1) for k, v in zip(a, a[1:]) if k == "-e")
            blobs = self.store.get(a[-1])
            if blobs is None or opts["--name"] in self.containers:
                return res(125, "", "Error: no such image here (nothing is pulled), or the name is in use")
            cd = json.loads(blobs[a[-1]])["config"]["digest"]
            runs = json.loads(blobs[cd])["config"]["Entrypoint"] == APP_ENTRYPOINT
            self.containers[opts["--name"]] = {"labels": labels, "env": env, "config_digest": cd, "seq": 0,
                                               "image": labels.get(self.ota.IMAGE_LABEL), "state": "running" if runs else "exited"}
            return res(0, "%064x\n" % len(self.calls), "")
        if a[:3] == ["ps", "-a", "--filter"] and a[4:] == ["--format", "{{.Names}}"] and a[3].startswith("label="):
            return res(0, "".join(n + "\n" for n, x in self.containers.items() if a[3][len("label="):] in x["labels"]), "")
        raise AssertionError("a docker call the daemon stand-in does not answer: %r" % a)


class _Heartbeats:
    """The databroker as WP1's health check reads it (read(paths)): while the app container runs, each read gives its next
    heartbeat on the leaves WP1's own leaf map names -- the app's name and APP_IMAGE_ID from its start, the version its
    image carries, seq rising from 1 after each start, state running; nothing while none runs."""

    def __init__(self, ota: Any, daemon: _Daemon) -> None:
        self.ota, self.daemon = ota, daemon
        _branch, self.fields = ota.ota_health.leaf_fields(APP)

    def read(self, paths: Sequence[str]) -> Dict[str, Any]:
        c = self.daemon.containers.get(self.ota.APP_CONTAINER)
        if c is None or c["state"] != "running":
            return {p: None for p in paths}
        c["seq"] += 1
        rec = {"schema_version": 1, "app": c["labels"][self.ota.APP_LABEL], "app_version": self.daemon.versions[c["config_digest"]],
               "image_id": c["env"]["APP_IMAGE_ID"], "seq": c["seq"], "state": "running", "hazard_requested": False,
               "actuate_result": "none"}
        return {p: rec.get(self.fields[p]) for p in paths}


def _wp1_updater_kw(ota: Any, daemon: _Daemon) -> Dict[str, Any]:
    """What a host gives WP1's Updater (ota_lite.main's keywords, Updater's own) here: WP1's Docker over the daemon, the
    heartbeats, a monotonic clock its own sleeps advance, a documentation wall clock, and no after-start hook."""
    t = [0.0]

    def sleep(seconds: float) -> None:
        t[0] += seconds
    return {"docker": daemon.docker(), "source_factory": lambda: _Heartbeats(ota, daemon), "clock": lambda: t[0],
            "wall": lambda: 1800000000.0, "sleep": sleep, "hook": lambda _argv: 0}


class _Player:
    def __init__(self, cmd: Sequence[str]) -> None:
        self.cmd: List[str] = list(cmd)
        self.rc: Optional[int] = None

    def poll(self) -> Optional[int]:
        return self.rc

    def terminate(self) -> None:
        self.rc = -15

    def kill(self) -> None:
        self.rc = -9

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        return self.rc


class _MetalHost:
    """The instance as drill.py meets it through its runner (stand-ins only): the stack's containers up under stack.py's
    run label for the up run; the unit ota-lite inactive until WP1's own launcher starts it; `sudo -n cat` reading the
    updater's own files; WP1's ota_lite.main, in this process, for check, unit start, unit stop and teardown (its own
    systemctl, install and systemd-run calls come back here); and behind the unit, WP1's own `run` on the very command line
    the launcher gave systemd-run, once for each new record in the spool, polled when drill.py reads the updater's log
    (`--once`: its manifest check, its Updater, its log and its status writer), against the Docker daemon stand-in (_Daemon:
    no sdv-ota-app container at first) and the heartbeats. The unit answers the first `answers` records it is given; at the
    next it hangs, as a unit whose updater stopped."""

    def __init__(self, ota: Any, drill: Any, stack_names: Sequence[str], stack_label: str) -> None:
        self.ota, self.drill, self.stack_names, self.stack_label = ota, drill, list(stack_names), stack_label
        self.a: Any = None                 # drill.py run's arguments, once the run is called
        self.unit = "inactive"
        self.ota_calls: List[List[str]] = []
        self.refused: List[str] = []
        self.launched: List[List[str]] = []
        self.installs: List[List[str]] = []             # the launcher's `install -d -m M -o U -g G PATH`, as it called them
        self.daemon = _Daemon(ota)
        self.kw = _wp1_updater_kw(ota, self.daemon)
        self.unit_run: Optional[List[str]] = None       # the unit's `run ...`, as the launcher gave it to systemd-run
        self.answers = len(drill.STEPS)
        self.seen: List[bytes] = []
        self.polls = 0

    def __call__(self, cmd: Sequence[str]) -> Any:
        cmd, done = [str(c) for c in cmd], self.drill.Done
        if cmd[1:3] == ["-B", str(self.drill.OTA_LITE)]:
            return self._ota(cmd[3:])
        if cmd[:2] == ["docker", "ps"] and "--filter" in cmd:
            ours = cmd[cmd.index("--filter") + 1] == "label=" + self.stack_label
            return done(0, "".join(n + "\n" for n in self.stack_names) if ours else "", "")
        if cmd == ["systemctl", "is-active", self.ota.UNIT]:
            return done(0 if self.unit == "active" else 3, self.unit + "\n", "")
        rest = cmd[2:] if cmd[:2] == ["sudo", "-n"] else None
        if rest is not None and rest[:2] == ["cat", "--"]:
            return self._cat(rest[2])
        if rest is not None and rest[:2] == ["install", "-d"]:
            self.installs.append(rest)
            return done(0, "", "")
        if rest is not None and rest[:1] == ["systemd-run"]:
            self.launched.append(rest)
            at = rest.index(str(Path(str(self.ota.__file__)).resolve()))
            self.unit_run = rest[at + 1:] if rest[at - 1] == "-B" else None
            self.unit = "active"
            return done(0, "", "")
        if rest == ["systemctl", "stop", self.ota.UNIT]:
            self.unit = "inactive"
            return done(0, "", "")
        raise AssertionError("a call the instance stand-in does not know: %r" % cmd)

    def _main(self, args: List[str], **kw: Any) -> Any:
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = self.ota.main(args, runner=self, **kw)
        except SystemExit:
            self.refused.append("ota_lite.py's parser refuses %r: %s" % (args, err.getvalue().strip()))
            rc = 2
        return self.drill.Done(rc, out.getvalue(), err.getvalue())

    def _ota(self, args: List[str]) -> Any:
        self.ota_calls.append(args)
        return self._main(args, docker=self.kw["docker"])

    def _unit_poll(self) -> None:
        """The unit's poll of a new record in the spool: WP1's own `run --once` on the launcher's command line, while the
        unit is active and the record is one of the first `answers` it is given. A spool with nothing new in it is a poll
        that does nothing (WP1's mark), so none is run for it."""
        data = self.ota.read_spool(self.a.spool_dir)
        if self.unit != "active" or self.unit_run is None or data is None or (self.seen and self.seen[-1] == data):
            return
        self.seen.append(data)
        if len(self.seen) > self.answers:
            return                                  # it hangs: this record and every later one go unanswered
        r = self._main(self.unit_run + ["--once"], **self.kw)
        self.polls += 1
        if r.returncode != 0:
            self.refused.append("the unit's run exited %d: %s" % (r.returncode, r.stderr.strip()))

    def _cat(self, path: str) -> Any:
        done, p = self.drill.Done, Path(path)
        if path == "/dev/null":
            return done(0, "", "")
        state = Path(os.path.abspath(self.a.state))
        if p == state / self.ota.LOG_FILE:
            self._unit_poll()
        if p in (state / self.ota.LOG_FILE, state / self.ota.STATE_FILE):
            return done(0, p.read_text(encoding="utf-8"), "") if p.is_file() else done(1, "", "cat: %s: No such file or directory" % p.name)
        raise AssertionError("sudo -n cat of a file the updater does not write: %s" % path)


def _metal_session(tmp_path: Path, drill: Any, bd: Any, ota: Any, stack: Any, monkeypatch: Any, capsys: Any,
                   vss_host: Optional[str]) -> Dict[str, Any]:
    """What run-ota-drill.sh holds when its manifest unit starts (spec-2 section 4 item 3), on documentation values here:
    drill-in/ as setup left it (build_drill.py save's tar, its sum file, the pins it saved), VSS_HOME's two pythons
    (stand-in files: nothing runs them), the up run's directory as stack.py lays it out (drill-work/runs/<run>: its run
    manifest with app external and the host's role, ownership.json, the staged recording, up/); then the harness's
    manifest call, through drill.py, with the updater's own check run here. The harness's environment comes back with it."""
    text = _sh()
    scalars, _arrays = _sh_vars(text)
    w = tmp_path / "a1"
    env = {"W": str(w), "OUT": str(w / "rec" / "ota-drill" / "raw"), "STATUS": str(w / "rec" / "ota-drill" / "status"),
           "DRILL_IN": str(w / "drill-in"), "VSS_HOME": str(w / "sdv")}
    if vss_host is not None:
        env["VSS_HOST"] = vss_host
    role = _expand(scalars["HOST_MODE"], env, scalars)
    images = _drill_images()
    _saved(drill, bd, monkeypatch, capsys, Path(env["DRILL_IN"]), images)
    lay = _stack_run_layout(stack)
    run = Path(_expand(scalars["RUNS"], env, scalars)) / (RUN_NAME + scalars["STACK_NAME"])
    (run / lay["in"]).mkdir(parents=True)
    (run / lay["up"]).mkdir()
    recording = b"(0.000000) vcan0 123#0000000000000000\n"
    (run / lay["in"] / lay["log"]).write_bytes(recording)
    drill.write_json(run / "manifest.json", {"format": 1, "run": run.name, "host_role": role, "app": "external"})
    drill.write_json(run / "ownership.json", {
        "format": 1, "scenario": scalars["RECORDING"],
        "recording": {"path": "recordings/%s/sigsim.log" % scalars["RECORDING"], "sha256": _sha256(recording), "format": "candump-log"},
        "source": {"generator": "sigsim", "vehicle": {"name": "sigsim-design-car", "wheelbase_mm": 2700}, "params": {"seed": 1}},
        "profile_id": 1, "rows": []})
    for var in ("SIM_PY", "OTA_PY"):
        py = Path(_expand(scalars[var], env, scalars))
        py.parent.mkdir(parents=True)
        py.write_bytes(b"#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
    env["STACK_RUN"] = str(run)
    # every stack container but the app runs, the CAN provider included (stack.py up --app external starts it)
    names = [n for n in stack.NAMES.values() if n != stack.NAMES[stack.attr.APP]]
    host = _MetalHost(ota, drill, names, "%s=%s" % (stack.LABEL, lay["label"] % run.name))
    capsys.readouterr()
    rc = drill.main(_drill_calls(env)["manifest"], runner=host)
    return {"env": env, "role": role, "run": run, "host": host, "rc": rc, "out": capsys.readouterr(), "scalars": scalars,
            "work": Path(_expand(scalars["WORK"], env, scalars)), "pins": drill.read_pins(Path(env["DRILL_IN"]) / drill.PINS_FILE.name)}


@POSIX_ONLY
@pytest.mark.parametrize("vss_host", [None, "c7g-metal"], ids=["vss-host-unset", "c7g-metal"])
def test_the_harnesss_manifest_call_on_build_drills_save_passes_the_updaters_check(drill, bd, ota, stack, tmp_path, monkeypatch,
                                                                                  capsys, vss_host):
    """Spec-2 2.1 and 2.3: drill.py manifest, called as the harness calls it on build_drill.py save's tar, writes the
    host's manifest, which the updater's own check takes for the harness's role; each version's tar, split beside it in
    drill-work/drill-tars, is one image the updater's tar reader reads as that version's pinned ID."""
    s = _metal_session(tmp_path, drill, bd, ota, stack, monkeypatch, capsys, vss_host)
    assert s["rc"] == 0 and not s["host"].refused, (s["out"], s["host"].refused)
    assert s["host"].ota_calls == [["check", "--manifest", str(s["work"] / "manifest.json"), "--host-role", s["role"], "--arch", "arm64"]]
    assert "the manifest is ok" in s["out"].out
    m = json.loads((s["work"] / "manifest.json").read_text(encoding="utf-8"))
    assert (m["host_role"], m["arch"], [x["name"] for x in m["scenarios"]]) == (s["role"], "arm64", [s["scalars"]["RECORDING"]])
    apps = {c["app_version"]: c for c in m["components"] if c["class"] == "app"}
    assert sorted(apps) == list(drill.VERSIONS)
    for v, c in apps.items():
        part = Path(c["pull"]["tar_path"])
        assert (c["pull"]["via"], part.parent, c["image_id"]) == ("tar", s["work"] / drill.TAR_DIR, s["pins"][v]["config_digest"])
        assert ota.ota_docker.tar_manifest_digest(part) == s["pins"][v]["id"] and c["pull"]["tar_sha256"] == _sha256(part.read_bytes())


@POSIX_ONLY
def test_wp1s_updater_answers_the_drills_six_records_as_drill_py_reads_its_log(drill, bd, ota, stack, spool, tmp_path, monkeypatch,
                                                                               capsys):
    """Spec-2 2.2 and section 1, each side by its own code: WP1's Updater, on the manifest the harness's manifest call
    writes (transport tar; the updater's check passed) as `run` loads it, with the twin-control marker absent, the Docker
    daemon stand-in under WP1's own Docker class and the heartbeats (v1 and v2 healthy, v3 exiting at once), is given the
    drill's six records (drill.py run's own, written by spool.py) one poll each. drill.py's outcome over WP1's own log
    and the status file WP1 wrote give each step what drill.EXPECTED says: the record event's mark, the status event, the
    refusal steps 5, 4 and 8 and step 3's rollback event are WP1's, read as drill.py reads them."""
    s = _metal_session(tmp_path, drill, bd, ota, stack, monkeypatch, capsys, None)
    assert s["rc"] == 0, s["out"]
    path = s["work"] / "manifest.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    run = drill.Run(drill.build_parser().parse_args(_drill_calls(s["env"])["run"]), s["host"], _Player, lambda: 0.0, lambda _s: None)
    run.ids = drill.drill_ids(raw)
    dirs = {d: tmp_path / d for d in ("state", "spool", "status")}
    for d in dirs.values():
        d.mkdir()
    daemon = _Daemon(ota)
    updater = ota.Updater(ota.ota_manifest.load(str(path), s["role"], "arm64"), dirs["state"], spool_dir=dirs["spool"],
                          status_dir=dirs["status"], runtime_dir=tmp_path / "runtime", docker_config=tmp_path / "docker",
                          marker=tmp_path / "twin-control", lock=tmp_path / "scenario.lock", **_wp1_updater_kw(ota, daemon))
    log = dirs["state"] / ota.LOG_FILE

    def events() -> List[Dict[str, Any]]:
        return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
    versions = drill.app_versions(raw)
    for n, asks, rec in run.records():
        start = len(events())
        spool.write(dirs["spool"], rec)
        result = updater.poll_once()
        found = drill.outcome(events(), drill.sha256_bytes(spool.encode(rec)), start)
        assert found is not None, (n, asks, "no answer drill.py can read in WP1's log", events()[start:])
        st = json.loads((dirs["status"] / drill.STATUS_FILE).read_bytes())
        assert list(st) == ["image_id", "scenario", "result"], st                    # drill.py run's own check of the form
        got = (versions.get(st["image_id"]) if st["image_id"] is not None else None, st["scenario"], st["result"], found["refused_step"],
               found["rollback"])
        assert (result, got) == (drill.EXPECTED[n][2], drill.EXPECTED[n]), (n, asks, events()[start:])
    assert [c["config_digest"] for c in daemon.containers.values()] == [run.ids["1.1.0"]]       # v2 runs: v3 rolled back to it


@POSIX_ONLY
@pytest.mark.parametrize("vss_host", [None, "c7g-metal"], ids=["vss-host-unset", "c7g-metal"])
def test_a_run_by_the_harnesss_command_line_writes_a_record_the_harness_keeps_and_capture_publishes(drill, bd, ota, stack, tmp_path,
                                                                                                   monkeypatch, capsys, vss_host):
    """Spec-2 section 4 item 4: drill.py run, called as the harness calls it (its state directory made first, as the
    harness makes it; the host's spool and status directories here in the test's), against the instance's stand-in, starts
    the unit through WP1's own launcher with no CPU list, on the updater's venv python the harness made, the spool
    directory the login's (it writes the records) and the status directory 0755 (it reads status.json), plays the up
    run's staged recording with the sim venv's python,
    gets every step answered by WP1's own `run` behind that unit (on the launcher's command line: its spool, status and
    state directories and the marker drill.py passed), ends with WP1's teardown removing the app container the updater
    left, and writes exactly the files the harness keeps from its record -- drill-result.json, the updater's log and state, a
    status file per step -- each on capture.py's whitelist under ota-drill/raw (the stem's detach.log never), with a
    verdict the harness's tool reads. The harness gives drill.py run no REPO_COMMIT (remote-ladder.sh reads it from
    inputs.env and exports none), so the record's repo_commit is null, which spec-2 2.2 allows; the commit stands in
    drill.json's drill_tar_commit and repo_commit facts."""
    s = _metal_session(tmp_path, drill, bd, ota, stack, monkeypatch, capsys, vss_host)
    assert s["rc"] == 0, s["out"]
    env = dict(s["env"], SPOOL_DIR=str(tmp_path / "spool"), STATUS_DIR=str(tmp_path / "status"))
    for d in ("spool", "status", "proc", "net/vcan0"):
        (tmp_path / d).mkdir(parents=True)
    monkeypatch.setattr(drill, "PROC", str(tmp_path / "proc"))
    monkeypatch.setattr(drill, "NET_SYSFS", str(tmp_path / "net"))
    monkeypatch.setenv(drill.TWIN_CONTROL_ENV, str(tmp_path / "twin-control"))
    argv = _drill_calls(env)["run"]
    host = s["host"]
    host.a = drill.build_parser().parse_args(argv)
    assert 'mkdir -p "$WORK/ota-state"' in _sh_function(_sh(), "unit_drill")
    Path(host.a.state).mkdir()
    players: List[_Player] = []

    def popen(cmd: Sequence[str]) -> _Player:
        players.append(_Player(cmd))
        return players[-1]
    ticks = itertools.count()
    monkeypatch.delenv("REPO_COMMIT")              # build_drill.py save's (_saved); the harness gives drill.py run none
    rc = drill.main(argv, runner=host, popen=popen, clock=lambda: next(ticks) / 4.0, sleep=lambda _s: None)
    assert rc == 0 and not host.refused, (capsys.readouterr(), host.refused)
    record = Path(host.a.record)
    res = json.loads((record / drill.RESULT_FILE).read_text(encoding="utf-8"))
    assert (res["verdict"], res["host_role"], res["transport"], res["via"], res["repo_commit"]) == ("ok", s["role"], "tar", "spool", None)
    assert [c[:2] for c in host.ota_calls] == [["check", "--manifest"], ["unit", "start"], ["unit", "stop"], ["teardown", "--docker"]]
    [launch] = host.launched
    assert not [w for w in launch if "AllowedCPUs" in w or w in ("--cpuset", "--cpus")], launch
    assert launch[launch.index("--host-role") + 1] == s["role"] and launch[launch.index("--state") + 1] == host.a.state
    assert launch[launch.index("--collect") + 1] == host.a.ota_python        # the unit runs the updater's venv python the harness made
    installs = {c[-1]: c[2:-1] for c in host.installs}                         # path -> the launcher's -m M -o U -g G for it
    assert installs[os.path.abspath(host.a.spool_dir)] == ["-m", "0755", "-o", str(os.getuid()), "-g", str(os.getgid())]   # the login's
    assert installs[os.path.abspath(host.a.status_dir)][:2] == ["-m", "0755"]                    # the login reads status.json
    lay = _stack_run_layout(stack)
    assert [p.cmd for p in players] == [[host.a.sim_python, "-m", "can.player", "-i", "socketcan", "-c", stack.VCAN,
                                         str(s["run"] / lay["in"] / lay["log"])]]
    written = sorted(os.listdir(str(record)))
    text = _sh()
    keep = _sh_function(text, "keep_record")
    literal, globs = re.findall(r'"\$WORK/record/([^"$]+)"', keep), re.findall(r'"\$WORK/record"/([^\s;]+)', keep)
    assert set(literal) <= set(written) and globs, (literal, globs, written)
    assert [n for n in written if n in literal or any(fnmatch.fnmatchcase(n, g) for g in globs)] == written
    assert written == sorted([drill.RESULT_FILE, ota.LOG_FILE, ota.STATE_FILE] + ["status-%d.json" % n for n in range(1, 7)])
    assert re.findall(r'"\$WORK/record/([^"$]+)"', _sh_function(text, "unit_drill")) == [drill.RESULT_FILE]
    excluded = _capture_excluded()
    assert {n: excluded("ota-drill/raw/" + n) for n in written} == {n: "" for n in written}
    assert excluded("ota-drill/detach.log") == "not on the vss whitelist"
    assert _tool(_harness_tool(tmp_path), capsys, monkeypatch, "verdict", record / drill.RESULT_FILE) == (0, "ok\n")
    assert host.polls and res["end"]["teardown_exit"] == 0 and not host.daemon.containers, (host.polls, res["end"], host.daemon.containers)


@POSIX_ONLY
def test_a_run_whose_last_step_gets_no_answer_exits_1_after_writing_the_record_the_harness_takes(drill, bd, ota, stack, tmp_path,
                                                                                                monkeypatch, capsys):
    """The WP6 critic's item: drill.py run exits 0 or 1 only after writing drill-result.json. Called as the harness calls
    it (no --step-timeout-s: the design value), against a unit that answers five records and hangs on the sixth: exit 1,
    the six steps in the record, step 6 timed out with no answer, verdict not ok, the end run all the same (unit stop,
    teardown, the updater's log and state copied). The harness takes exit 1 as a run that ran (unit_drill's case arm, then
    its check for drill-result.json), keeps what capture.py publishes, and its tool reads `not ok`."""
    s = _metal_session(tmp_path, drill, bd, ota, stack, monkeypatch, capsys, None)
    assert s["rc"] == 0, s["out"]
    env = dict(s["env"], SPOOL_DIR=str(tmp_path / "spool"), STATUS_DIR=str(tmp_path / "status"))
    for d in ("spool", "status", "proc", "net/vcan0"):
        (tmp_path / d).mkdir(parents=True)
    monkeypatch.setattr(drill, "PROC", str(tmp_path / "proc"))
    monkeypatch.setattr(drill, "NET_SYSFS", str(tmp_path / "net"))
    monkeypatch.setenv(drill.TWIN_CONTROL_ENV, str(tmp_path / "twin-control"))
    monkeypatch.delenv("REPO_COMMIT")              # build_drill.py save's (_saved): the harness gives drill.py run none
    argv = _drill_calls(env)["run"]
    host = s["host"]
    host.a = drill.build_parser().parse_args(argv)
    host.answers = len(drill.STEPS) - 1
    Path(host.a.state).mkdir()
    ticks = itertools.count()
    rc = drill.main(argv, runner=host, popen=_Player, clock=lambda: next(ticks) / 4.0, sleep=lambda _s: None)
    assert rc == 1 and not host.refused, (capsys.readouterr(), host.refused)
    record = Path(host.a.record)
    assert (record / drill.RESULT_FILE).is_file(), sorted(os.listdir(str(record)))
    res = json.loads((record / drill.RESULT_FILE).read_text(encoding="utf-8"))
    assert (res["verdict"], res["repo_commit"]) == ("not ok", None)
    want = [(n, drill.EXPECTED[n][2], False) for n in range(1, 6)] + [(6, None, True)]
    assert [(x["n"], x["result"], x["timed_out"]) for x in res["steps"]] == want, res["steps"]
    assert [c[:2] for c in host.ota_calls] == [["check", "--manifest"], ["unit", "start"], ["unit", "stop"], ["teardown", "--docker"]]
    assert (host.unit, host.daemon.containers, res["end"]["copied_ota_lite"], res["end"]["copied_state"]) == ("inactive", {}, True, True)
    written = sorted(os.listdir(str(record)))
    assert written == sorted([drill.RESULT_FILE, ota.LOG_FILE, ota.STATE_FILE] + ["status-%d.json" % n for n in range(1, 6)])
    unit = _sh_function(_sh(), "unit_drill")
    arms = re.search(r'case "\$RC" in\s*\n\s*([0-9|]+)\) ;;', unit)
    assert arms is not None and "1" in arms.group(1).split("|") and '[ -f "$WORK/record/%s" ]' % drill.RESULT_FILE in unit
    excluded = _capture_excluded()
    assert {n: excluded("ota-drill/raw/" + n) for n in written} == {n: "" for n in written}
    assert _tool(_harness_tool(tmp_path), capsys, monkeypatch, "verdict", record / drill.RESULT_FILE) == (0, "not ok\n")
