"""The slice's local stack (sdv/stack) and its first app (sdv/apps/hard-brake-hazard): SDV plan Phase 1
steps 6 and 7 and the exit test.

Pure tests (standard library; no Docker, no databroker, no bus):
  * every container image is referenced by digest: upstream images as repo@index-digest, the local
    images' base by digest, local images run by image ID; the start arguments of every component in
    both feeds bind nothing but loopback, publish no port, never run privileged or mount docker.sock;
  * the listener checks themselves (ss and /proc/net parsing, the loopback test, the verdict);
  * the AppState schema carries no Monitor-derived field; the app's leaf map equals the schema's;
    the app writes only the allowlisted AppState leaves and actuates only the hazard light; its
    records validate against the schema; and its actions are identical whatever the Monitor branch
    does (the design's differential test A8, with a seeded variant that must fail it);
  * the decision function at its threshold edges, in both directions of travel, at standstill, on
    stale and non-finite inputs;
  * the attribution table: exactly one writer per signal on the real configurations, and each check
    failing on a seeded violation;
  * the replay checks: alignment of recorded against decoded values, the windows, the mapping; the
    v2 witness compared exactly (a comparison of nothing is not a pass) and its verdict gate by gate,
    each failing on its own on a synthetic log; the databroker's lag counts per subscriber capacity;
    the verdict holding all three listener snapshots and every value witness; the behaviour key and
    the window gate reading only the app's own log and the mock provider's own (analyse() on a
    synthetic replay directory: a recorder that dropped updates changes neither the key nor the
    verdict, a differing actuation or mock write does, and so does a mock log with any line above INFO
    -- the mock logs each write just before making it -- though its three writes are right), the key's
    fields pinned one by one, and the recorder's hazard rows only reported;
  * the load check's probe list holding every enum node of the 6.1 file;
  * the recording's provenance: the seed, the log's hashes, summary.json (the windows' source) and
    the DBC staged by sha256 from the cache, each refusal on a synthetic recording directory, and
    the exact Windows export command a missing DBC is refused with, and where it runs;
  * Context.prepare's wiring on a synthetic recording, catalogue and DBC (no Docker, no decoding):
    the windows follow summary.json, the seed is the manifest line's and a --seed that disagrees is
    refused before anything is written;
  * the app's shell (app.py, with stand-ins for kuksa-client): a burst of Monitor updates cannot
    hold up or degrade a heartbeat, and main() gives each stream the lock that keeps it so;
  * the WSL argument file deselects exactly the tests that run git against the checkout, and the
    README's commands say where the export runs and print the deselected count;
  * the bridge mode (SDV Phase 2 WP8), on synthetic values that are not the generated ones: the vehicle
    layer's binding, spec 5.6's two Wheelbase branches, the run header and C12a (the recorded CARLA
    source_rtf included), C3, C5, C12b and its operands, the listener allowance by PID, `replay`'s exit
    gates, the bridge's wheelbase record against the prediction, and the probes' pure parts;
  * --images loaded (SDV Phase 3 WP1), against a fake docker whose `pull` would bring a missing image back:
    prepare takes images.json's pinned set (the upstream images by index digest, the local images and the
    witness by their arm64 pins, the bridge by its arm64 pin) and runs neither pull nor build; it refuses,
    still without pulling, a missing image, another image ID, linux/amd64, a revision label or repo digest
    that differs, and a SDV_BRIDGE_IMAGE that is not the bridge's arm64 pin; build mode is today's path;
    every command of main passes --images through;
  * SDV_HOST_ROLE and guest mode (SDV Phase 3 WP2): the role reaches the manifest, the run header and its run_id,
    and a value outside pc, a1-metal, c7g-metal (2026-10-17) and orin is refused; c7g-metal is held to what a1-metal is
    held to in every role loop (no cpuset or hook required, a guest host of its own refused, the PC's probes allowed);
    a guest-mode Context refuses a loopback or non-IPv4 host, a
    missing console or image, no bridge, and guest options in native mode; prepare in guest mode builds no native
    monitor and records the guest's component (the image's name and sha256, the host, port 7160, `7160 svc 500`);
    up() starts no native monitor in guest mode and allows no listener; record_close reads the console path it is
    given; stack.py's own replay refuses guest mode. Off the PC a guest host that is one of this host's own addresses
    (`ip -j -4 addr show`, replaced) is refused; the component records host_local (true on the PC's stand-in, false,
    or null when the addresses cannot be read);
  * the twin connector (SDV Phase 4 WP3), against a replaced docker: one more container a run may start, not one of
    the six; the design's A10 (exactly three mounts, the host's namespace, a read-only root, no capability, no
    published port, no docker.sock, the host user and never root, restart policy no, and neither the endpoint nor a
    name on the argument vector); refused without the vcan feed, beside the guest monitor mode, on loaded images and
    without its image or device directory, each before anything is started or written; the image taken by ID, of
    this generation, and no root image; started after the app and the bridge and before the listener snapshot,
    stopped with SIGTERM after the app and before the databroker; the start spacing held by the stack's own stamp
    whatever the run directory; a fake run's directory holding no endpoint, name or certificate path; the
    connector's result and its gate;
  * placement on the Orin (SDV Phase 5 WP1), against a replaced docker and a stand-in hook script: with neither
    SDV_CONTAINER_CPUSET nor SDV_AFTER_START set no container gets --cpuset-cpus, no hook runs and every argument
    vector is a pre-Phase-5 context's; with the cpuset set every container (the probes' too) gets --cpuset-cpus right
    after the common flags and nothing else moves; an empty, malformed or duplicated list, or one holding core 0, 1, 2
    or 4, is refused before anything is written, as are role orin without the cpuset, role orin without the hook beside
    either monitor, and a hook that shlex cannot split or that is empty; the hook runs after each successful container
    start with the container's name last and no shell, its exit status and last lines kept, and a non-zero exit, a
    timeout or a hook that cannot start fails the start naming the container; a replay's and a step-3 run's result.json
    carry the records; the run manifest records the cpuset and the hook's argv; on the Orin main refuses loadcheck,
    ageprobe, wheelbaseprobe and exit-test before anything is written;
  * SDV Phase 6 WP2 (spec section 4 items 5-9), against a replaced docker: the common flags and every container's argv
    written out word for word, the app's the one that changed (APP_IMAGE_ID is its config digest, the image still its
    store ID, in both images modes; a start without a proved config digest is refused); the config digest read from a
    `docker save` stream with the manifest and the config hash-checked and an index refused, opened through its own
    seam (docker_stream, which every test replaces) and killed on an error nobody expected, and build mode proving
    the app's after its build; `up --app external` starting every container but the app and waiting for no app (vcan
    only, on up only, the run manifest saying so); the CAN-provider fix: `up --app external` starts the CAN provider
    once up() has returned, with the run's /up label, and waits for its ready line, so drill.py run's container list
    holds it; the default `up` starts none and prints what it printed; a CAN provider that does not start, never logs
    ready or is interrupted takes the stack down, and down removes it; SDV_SPOOL_DIR and SDV_STATUS_DIR taken both or
    neither, each an existing directory outside the repo, mounted at the connector's paths and never made, read by a
    run with a connector only and taken by up --app external --connector only; the twin-control marker
    (SDV_TWIN_CONTROL_MARKER) refusing replay --bridge, prepare --bridge, a Context with a bridge and the bridge's own
    start before anything starts, and nothing without a bridge;
  * a CARLA recording (SDV Phase 7 WP3b; spec-2 sections 2.1, 2.2 and 5), on synthetic recordings and generations: the
    log by its line's generator and recording.path (bundle.py's table, held equal to sdv/inject/inject.py's), a mismatched
    pair or another name refused naming both, its hashes; the run type's generation pair (sigsim exactly today's whatever
    else the generation holds, carla its vehicle_layers and databroker_catalogues entries, each file's hash checked, a
    generation without them refusing a CARLA recording before anything is written); the log staged under its own name and
    named in every argument vector, the carla catalogue staged as in/vss-databroker.json and its vehicle layer in the
    scenario table and the run manifest; the run header and C12a in each bridge mode (run_type carla, source_rtf the
    line's, the scenario entry's source with its rtf); the encoder's provenance reported, never required; the oracle on a
    CARLA trip; the bridge's Wheelbase start check passing profile 3 with the carla catalogue and failing with the sigsim
    one; WP1's fake take encoded against this tree's generation (tests/test_sdv_phase7_contract.py's builders) and its
    injected twin prepared; and a sigsim run's in/, argument vectors and records on the frozen generation equal to the
    base's (SIGSIM_BASE_GOLDEN, with the publication's simulator source identity only). What the records name: the guest component's
    build file by its image's name (ifs-vss.build, ifs-vss-carla.build, generic words for any other image), the table
    held to the build files that start the vss monitor; loadcheck loading a CARLA run's staged catalogue beside the
    generation's sigsim one (a sigsim run's four as before); a CARLA run's CAN provider rows naming the carla feeder
    (version, town, seed, vehicle) as their upstream, every other column attribution.py's own;
  * the ros feed (SDV Phase 8 WP3d; spec-2 2.5, 2.6, 2.12 and 5), on a synthetic planning-sim generation, synthetic
    images.json pins and a replaced docker, host check, native monitor, pulls and builds: attribution.py's planning-sim
    table (the feeder for the slots, Vehicle.Speed and every ControlCommand and CtlClaim leaf, the bridge or none for
    VssClaim, the catalogue for the Wheelbase, nothing else) passing with sdv/rosvss/mapping.py's write set (read) on the
    synthetic and on this tree's generation, and its check failing on a second writer of a slot path, a feeder write to
    VssClaim, any Wheelbase writer, a row with another writer, an extra or a missing row and a witness off the owned
    paths; the command line's refusals (another run type, --run-type, --bridge or the monitor options on another feed,
    replay, exit-test, --app, --connector, --seed, --images loaded, a role but pc) before anything is written, and main
    handing the bridge mode and the monitor options to the RosContext; prepare's refusals (no planning-sim pair, broker
    without profile 4 compiled, a feeder image that is not images.json's by ID, labels, entrypoint, user, architecture or
    tag, a host user that is not aw's uid) before anything is written, and its records (run_type, the feeder's image ID
    and base digest, the catalogue's sha256, the staged catalogue and XML, only the databroker pulled and the recorder
    built, the table and its checks, the run header and C12a); up_ros's order (the host check, the databroker, the
    witness, the monitor and the bridge in broker mode, the feeder last; never the CAN provider, mock, recorder or app),
    the feeder's docker run written out (COMMON, --user aw, 2.7's environment, the ID, never privileged, a capability, a
    /proc or /sys mount or X11) and aw_argv_problems refusing each forbidden flag before docker runs; a host check that
    cannot be read refusing the run, a failed start swept with the host check read after, a changed setting named; down
    removing the feeder with the rest, reading the host check and failing on a change, and stopping a left native
    monitor only while its pid runs its binary; the feeder's topics and QoS against W4's publishers, read from WP3a's
    unchanged modules; the CAN-provider fix's five test-only NITs (its critic's proposal).

Tests that need the generated catalogue (sdv-out/gen, sdv/vss/README.md) skip without it; the one
that reads the real recording directory (read-only) skips without it, and so does the one that reads WP5a's CARLA
pair (~/sdv-recordings/20261019-carla-1 and its -inj twin, read only).

The integration test runs the whole exit test (stack.py exit-test: three replays in --dumpfile mode,
three on vcan0, the catalogue load check) and is skipped unless SDV_STACK=1; it needs WSL
Ubuntu-24.04's Docker Engine, sudo -n for vcan0, the sim venv and the recording, and writes only under
~/sdv-runs/.

Every number here is a design value of the app or the stack, a value of the generated contract, or a
synthetic fixture; none is a measurement.
"""
import ast
import asyncio
import datetime
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STACK_DIR = REPO / "sdv" / "stack"
APP_DIR = REPO / "sdv" / "apps" / "hard-brake-hazard"
CONNECTOR_DIR = REPO / "sdv" / "connector"
GEN = Path(os.environ.get("SDV_GEN", str(REPO / "sdv-out" / "gen"))).expanduser()
SIM_PY = Path(os.environ.get("SDV_SIM_VENV", "~/sdv-sim-venv")).expanduser() / "bin" / "python"
SCHEMA_FILE = APP_DIR / "appstate.schema.json"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")

_saved = sys.dont_write_bytecode
for _d in (str(STACK_DIR), str(APP_DIR), str(CONNECTOR_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import appstate  # noqa: E402
import attribution as attr  # noqa: E402
import hazard  # noqa: E402
import replaycheck as rc  # noqa: E402
import stack  # noqa: E402

sys.dont_write_bytecode = _saved

SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
IMAGES = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))
IMG = "sha256:" + "ab" * 32          # a synthetic image ID (a store ID)
APP_CFG = "sha256:" + "fe" * 32      # the app image's synthetic config digest: APP_IMAGE_ID since SDV Phase 6 WP2 (spec 2.1)
WITNESS_PATHS = tuple(attr.SLOT_PATHS) + ("Vehicle.Speed",)      # what the CAN provider writes
HAVE_GEN = (GEN / "vss-databroker.json").exists() and (GEN / "vss-can-mapping.json").exists()
NEEDS_GEN = pytest.mark.skipif(not HAVE_GEN, reason="needs the generated catalogue in %s (sdv/vss/README.md)" % GEN)
# Synthetic run values -- a vehicle's wheelbase, AGE_MAX, a kind 4 digest -- plainly not profiles.toml's or the
# generation's, so no fixture pins a generated value; the tests that need the real ones read the contract.
SYN_L_MM = 2468
SYN_OTHER_L_MM = 2345          # another vehicle's wheelbase
SYN_AGE_MAX_MS = 240
SYN_DIGEST = "0x12345678"      # CONTRACT_PY's CATALOG_DIGEST
SYN_OTHER_DIGEST = "0x87654321"


REAL_DOCKER_STREAM = getattr(stack, "docker_stream", None)          # the seam itself, taken before the fixture below replaces it


def _no_docker_stream(*args: str) -> Any:
    raise AssertionError("a test reached stack.docker_stream (a docker %s against the daemon) without a fake of its own" % " ".join(args[:1]))


@pytest.fixture(autouse=True)
def _no_host_twin_settings(monkeypatch, tmp_path_factory):
    """No test reads this host's own twin-control marker or a host spool or status setting (SDV Phase 6 WP2): the marker
    variable names a path no test makes unless it sets the variable itself, and SDV_SPOOL_DIR and SDV_STATUS_DIR are unset.
    And no test reaches the daemon through the stack's stream seam (docker_stream, the `docker save` of build mode's proof)
    unless it replaced the seam itself: one that does fails here, loudly."""
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(tmp_path_factory.getbasetemp() / "no-twin-control-marker-here"))
    monkeypatch.delenv("SDV_SPOOL_DIR", raising=False)
    monkeypatch.delenv("SDV_STATUS_DIR", raising=False)
    monkeypatch.setattr(stack, "docker_stream", _no_docker_stream, raising=False)


# --- images by digest -----------------------------------------------------------------------------

def test_upstream_images_are_pinned_by_index_digest():
    for name, u in IMAGES["upstream"].items():
        for key in ("index_digest", "amd64_manifest", "arm64_manifest"):
            assert re.fullmatch(r"sha256:[0-9a-f]{64}", u[key]), (name, key)
        assert re.fullmatch(r"[0-9a-f]{40}", u["revision"]), name
        assert DIGEST.search(stack.upstream_ref(IMAGES, name)), name
    assert set(IMAGES["upstream"]) == {attr.DATABROKER, attr.CAN_PROVIDER, "kuksa-csv-provider", attr.MOCK_PROVIDER}
    assert IMAGES["upstream"]["kuksa-databroker"]["version"] == "0.7.1"
    assert IMAGES["upstream"]["kuksa-can-provider"]["version"] == "0.5.0"
    assert IMAGES["upstream"]["kuksa-csv-provider"]["version"] == "0.4.6"


def test_every_from_line_and_image_reference_carries_a_digest():
    base = IMAGES["base"]["python"]
    files = [APP_DIR / "Dockerfile", STACK_DIR / "recorder" / "Dockerfile"]
    for f in files:
        froms = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.startswith("FROM ")]
        assert froms, f
        for ln in froms:
            assert DIGEST.search(ln), (f, ln)
            assert base["index_digest"] in ln, (f, ln)
    # no registry reference anywhere in the stack's code without a digest
    ref = re.compile(r"\b(?:ghcr\.io|docker\.io|quay\.io)/[A-Za-z0-9_./-]+(?:[:@][A-Za-z0-9_.:-]+)?")
    for f in [STACK_DIR / "stack.py", STACK_DIR / "images.json", APP_DIR / "Dockerfile", STACK_DIR / "recorder" / "Dockerfile"]:
        for m in ref.finditer(f.read_text(encoding="utf-8")):
            text = m.group(0)
            if text.endswith(("/", "-")) or "raw.githubusercontent" in text:
                continue
            tail = f.read_text(encoding="utf-8")[m.start():m.start() + len(text) + 80]
            is_repo_field = f.suffix == ".json" and ":" not in text.split("/", 1)[1]
            assert is_repo_field or DIGEST.search(tail), (f.name, text)


def _lock_pins(lock: Path):
    text = lock.read_text(encoding="ascii")
    pins = re.findall(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})$", text, re.M)
    assert len(pins) == len(re.findall(r"^[a-z0-9-]+==", text, re.M)), lock      # every pin carries its hash
    return pins


@pytest.mark.parametrize("lock", ["requirements.lock", "requirements.aarch64.lock"])
def test_locks_pin_every_package_with_a_hash(lock):
    app = _lock_pins(APP_DIR / lock)
    rec = _lock_pins(STACK_DIR / "recorder" / lock)
    names = [p[0] for p in app]
    assert len(names) == len(set(names)) and dict((n, v) for n, v, _h in app)["kuksa-client"] == "0.6.0"
    assert app == rec                                     # one resolution for both images, per architecture


def _image_index(args: List[str]) -> int:
    """Position of the image in a `docker run` vector: the first repo@digest or bare image ID."""
    for i, a in enumerate(args):
        if DIGEST.search(a) or re.fullmatch(r"sha256:[0-9a-f]{64}", a):
            return i
    raise AssertionError("no image by digest or ID in %r" % args)


def _fake_ctx(tmp_path):
    ids = {attr.APP: IMG, attr.RECORDER: "sha256:" + "cd" * 32}
    return types.SimpleNamespace(images=IMAGES, image_ids=lambda: ids, in_dir=tmp_path / "in",
                                 components={attr.APP: {"image_id": IMG, "config_digest": APP_CFG}},
                                 recorded=["Vehicle.Speed", hazard.HAZARD], witness_paths=sorted(WITNESS_PATHS))


@pytest.fixture
def started(tmp_path, monkeypatch):
    """The docker argument vectors stack.start() produces for every component in both feeds."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    calls: Dict[str, Dict[str, List[str]]] = {}
    current = {"feed": ""}

    def fake_docker(*args, **_kw):
        calls.setdefault(current["feed"], {})[args[args.index("--name") + 1]] = list(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(stack, "docker", fake_docker)
    ctx = _fake_ctx(tmp_path)
    for feed in stack.FEEDS:
        current["feed"] = feed
        for comp in stack.NAMES:
            stack.start(ctx, comp, feed, tmp_path / "r", "test/run")
    return calls


def test_start_runs_images_by_digest_or_id(started):
    for feed, byname in started.items():
        for name, args in byname.items():
            img = args[_image_index(args)]
            upstream = [stack.upstream_ref(IMAGES, n) for n in IMAGES["upstream"]]
            assert img in upstream or img in (IMG, "sha256:" + "cd" * 32), (feed, name, img)
            assert not any(re.fullmatch(r"[a-z0-9._-]+/[a-z0-9._/-]+:[A-Za-z0-9_.-]+", a) for a in args), (feed, name)   # no repo:tag


def test_nothing_binds_beyond_loopback(started):
    for feed, byname in started.items():
        assert len(byname) == len(stack.NAMES) == 6
        for name, args in byname.items():
            joined = " ".join(args)
            opts = args[:_image_index(args)]
            assert "0.0.0.0" not in joined and "[::]" not in joined, (feed, name)
            assert not {"-p", "--publish", "-P", "--publish-all", "--expose"} & set(opts), (feed, name)
            assert "--privileged" not in opts and "docker.sock" not in joined
            assert args[args.index("--cap-drop") + 1] == "ALL"
            assert "no-new-privileges" in args
            net = args[args.index("--network") + 1]
            if feed == "vcan":
                assert net == "host"
            elif name == stack.NAMES[attr.DATABROKER]:
                assert net == "none"
            else:
                assert net == "container:" + stack.NAMES[attr.DATABROKER]
        db = byname[stack.NAMES[attr.DATABROKER]]
        assert db[db.index("--address") + 1] == "127.0.0.1"
        assert "KUKSA_DATABROKER_ADDR=127.0.0.1" in db and "--insecure" in db
        mock = byname[stack.NAMES[attr.MOCK_PROVIDER]]
        assert "MOCK_ADDR=127.0.0.1:50053" in mock and "VDB_ADDRESS=127.0.0.1:55555" in mock
        assert "grpc://127.0.0.1:55555" in byname[stack.NAMES[attr.CAN_PROVIDER]]
        app = byname[stack.NAMES[attr.APP]]
        # SDV Phase 6 WP2, deliberately: APP_IMAGE_ID is the app's config digest (spec 2.1), the image still runs by its store ID
        assert "APP_IMAGE_ID=" + APP_CFG in app and "APP_IMAGE_ID=" + IMG not in app and app[-1] == IMG


def test_feed_arguments(started):
    dump = started["dumpfile"][stack.NAMES[attr.CAN_PROVIDER]]
    vcan = started["vcan"][stack.NAMES[attr.CAN_PROVIDER]]
    assert "--dumpfile" in dump and "--use-socketcan" not in dump
    assert "--use-socketcan" in vcan and "--dumpfile" not in vcan
    for args in (dump, vcan):
        assert args[args.index("--canport") + 1] == "vcan0" and "--no-val2dbc" in args and "--no-infinite" in args


def test_the_witness_runs_in_the_recorder_image_on_the_can_fed_paths(started):
    for feed, byname in started.items():
        args = byname[stack.NAMES[stack.WITNESS]]
        i = _image_index(args)
        assert args[i] == "sha256:" + "cd" * 32                       # the recorder image, by ID
        assert args[i - 2:i] == ["--entrypoint", "python"]
        assert "%s:/witness.py:ro" % stack.WITNESS_FILE in args and "--read-only" in args
        assert args[i + 1:i + 4] == ["/witness.py", "127.0.0.1:55555", "/out/" + stack.WITNESS_LOG]
        assert args[i + 4:] == sorted(WITNESS_PATHS), feed


def test_the_witness_buffer_is_the_databrokers_largest_and_its_lag_capacity():
    text = stack.WITNESS_FILE.read_text(encoding="utf-8")
    m = re.search(r"^BUFFER_SIZE = (\d+)$", text, re.M)
    assert m is not None
    buf = int(m.group(1))
    assert buf == 1000 and stack.WITNESS_CAPACITY == buf + 1
    assert "buffer_size=BUFFER_SIZE" in text and "wait_for_ready=True" in text
    assert "signal.SIGTERM" in text                                   # PID 1 ignores an unhandled SIGTERM


# --- listeners ------------------------------------------------------------------------------------

SS = """\
tcp   LISTEN 0      128        127.0.0.1:55555      0.0.0.0:*    users:(("databroker",pid=4242,fd=9))
tcp   LISTEN 0      4096         0.0.0.0:111        0.0.0.0:*    users:(("rpcbind",pid=7,fd=4))
udp   UNCONN 0      0       127.0.0.53%lo:53        0.0.0.0:*    users:(("resolved",pid=8,fd=13))
tcp   LISTEN 0      4096           [::1]:631           [::]:*    users:(("cupsd",pid=9,fd=7))
tcp   LISTEN 0      4096            [::]:22            [::]:*    users:(("sshd",pid=10,fd=3))
"""


def test_parse_ss_and_loopback():
    socks = stack.parse_ss(SS)
    assert [s["local"] for s in socks] == ["127.0.0.1:55555", "0.0.0.0:111", "127.0.0.53%lo:53", "[::1]:631", "[::]:22"]
    assert [stack.is_loopback(s["local"]) for s in socks] == [True, False, True, True, False]
    assert stack.owner_pids(socks[0]["process"]) == [4242]
    for addr in ("192.0.2.1:80", "203.0.113.9:55555", "*:55555", "[::ffff:192.0.2.1]:1"):
        assert not stack.is_loopback(addr), addr
    assert stack.is_loopback("[::ffff:127.0.0.1]:55555")


def test_parse_proc_net():
    tcp = ("  sl  local_address rem_address   st\n"
           "   0: 0100007F:D903 00000000:0000 0A 00000000:00000000\n"
           "   1: 00000000:006F 00000000:0000 0A 00000000:00000000\n"
           "   2: 0100007F:D903 0100007F:9C40 01 00000000:00000000\n")
    assert stack.parse_proc_net(tcp, False) == ["127.0.0.1:55555", "0.0.0.0:111"]
    tcp6 = ("  sl  local_address                         rem_address                           st\n"
            "   0: 00000000000000000000000001000000:D903 00000000000000000000000000000000:0000 0A\n"
            "   1: 00000000000000000000000000000000:0016 00000000000000000000000000000000:0000 0A\n")
    assert stack.parse_proc_net(tcp6, True) == ["[::1]:55555", "[::]:22"]


def test_listener_verdict():
    before = {"with_owners": True, "sockets": stack.parse_ss(SS)[1:]}
    during = {"with_owners": True, "sockets": stack.parse_ss(SS) + stack.parse_ss(
        'udp UNCONN 0 0 0.0.0.0:41703 0.0.0.0:* users:(("other",pid=77,fd=3))')}
    v = stack.listener_verdict(before, during, None, [4242])
    assert v["ok"] and [s["local"] for s in v["added_by_stack"]] == ["127.0.0.1:55555"]
    assert [s["local"] for s in v["added_by_other_processes"]] == ["0.0.0.0:41703"]
    bad = {"with_owners": True, "sockets": during["sockets"] + stack.parse_ss(
        'tcp LISTEN 0 5 0.0.0.0:50053 0.0.0.0:* users:(("python",pid=4243,fd=5))')}
    assert not stack.listener_verdict(before, bad, None, [4242, 4243])["ok"]
    no_owner = dict(during, with_owners=False)
    assert not stack.listener_verdict(before, no_owner, None, [4242])["ok"]        # without owners every addition counts
    ns = {"proc_net": ["tcp 127.0.0.1:55555"], "ss_in_namespace": None}
    assert stack.listener_verdict(before, {"with_owners": True, "sockets": before["sockets"]}, ns, [])["ok"]
    ns_bad = {"proc_net": ["tcp 0.0.0.0:55555"], "ss_in_namespace": None}
    assert not stack.listener_verdict(before, {"with_owners": True, "sockets": before["sockets"]}, ns_bad, [])["ok"]


MONITOR_PID = 5000
MONITOR_ALLOWANCE = {"pid": MONITOR_PID, "proto": "tcp", "port": 7160, "why": "test"}


def _with(*lines):
    """The host's listeners during a run: SS plus the given ss lines."""
    return {"with_owners": True, "sockets": stack.parse_ss(SS + "\n".join(lines) + "\n")}


@pytest.mark.parametrize("line, allowed, ok", [
    # the native vss monitor's INADDR_ANY bind, by the PID the stack started: allowed
    ('tcp LISTEN 0 4 0.0.0.0:7160 0.0.0.0:* users:(("monitor-vss",pid=5000,fd=3))', [MONITOR_ALLOWANCE], True),
    # by PID, not by name: the same PID under another program name is still the stack's monitor
    ('tcp LISTEN 0 4 0.0.0.0:7160 0.0.0.0:* users:(("a-renamed-binary",pid=5000,fd=3))', [MONITOR_ALLOWANCE], True),
    # the monitor's name on a stack PID that is not the monitor's (a container's process): refused
    ('tcp LISTEN 0 4 0.0.0.0:7160 0.0.0.0:* users:(("monitor-vss",pid=4243,fd=3))', [MONITOR_ALLOWANCE], False),
    # the monitor's PID on another port or protocol: refused
    ('tcp LISTEN 0 4 0.0.0.0:7161 0.0.0.0:* users:(("monitor-vss",pid=5000,fd=3))', [MONITOR_ALLOWANCE], False),
    ('udp UNCONN 0 0 0.0.0.0:7160 0.0.0.0:* users:(("monitor-vss",pid=5000,fd=4))', [MONITOR_ALLOWANCE], False),
    # no allowance at all: the stack's non-loopback listener is refused as before
    ('tcp LISTEN 0 4 0.0.0.0:7160 0.0.0.0:* users:(("monitor-vss",pid=4243,fd=3))', [], False),
])
def test_the_native_monitors_inaddr_any_listener_is_allowed_by_its_pid_only(line, allowed, ok):
    before = {"with_owners": True, "sockets": stack.parse_ss(SS)[1:]}
    v = stack.listener_verdict(before, _with(line), None, [4242, 4243], allowed)
    assert v["ok"] is ok, v
    if ok:
        assert [s["local"] for s in v["allowed_by_pid"]] == ["0.0.0.0:7160"] and not v["added_not_loopback"]
    else:
        assert not v["allowed_by_pid"] and v["added_not_loopback"]
    assert v["preexisting_not_loopback"]           # rpcbind and sshd, there before the stack: never held against it


def test_without_owners_no_listener_can_be_allowed_by_pid():
    before = {"with_owners": True, "sockets": stack.parse_ss(SS)[1:]}
    during = dict(_with('tcp LISTEN 0 4 0.0.0.0:7160 0.0.0.0:* users:(("monitor-vss",pid=5000,fd=3))'), with_owners=False)
    v = stack.listener_verdict(before, during, None, [4242], [MONITOR_ALLOWANCE])
    assert not v["ok"] and not v["allowed_by_pid"]


def test_the_monitors_pid_counts_as_the_stacks_and_its_loopback_listeners_stay_free():
    before = {"with_owners": True, "sockets": stack.parse_ss(SS)[1:]}
    v = stack.listener_verdict(before, _with('tcp LISTEN 0 4 127.0.0.1:9 0.0.0.0:* users:(("monitor-vss",pid=5000,fd=5))'), None, [4242],
                               [MONITOR_ALLOWANCE])
    assert v["ok"] and MONITOR_PID in v["stack_pids"] and v["added_by_stack"][-1]["local"] == "127.0.0.1:9"


def _replay_result(**over):
    """A replay's result.json as verdict() reads it, every check passing."""
    ok = {"ok": True}
    r = {"feed": "dumpfile", "behaviour_key": {"decisions": [[True, "a"]]}, "decisions": ok,
         "lights": {"mock_log": ok, "recorder": {"consistent": ok}},
         "values": {"ok": True, "exact": True}, "witness_values": ok, "app_values": ok,
         "listeners": ok, "listeners_feed": ok, "listeners_end": ok}
    r.update(over)
    return r


def test_the_verdict_holds_every_listener_snapshot_and_every_value_witness():
    good = [_replay_result() for _ in range(3)]
    v = stack.verdict(None, good, "dumpfile", 3)
    assert v["ok"] and v["only_loopback_listeners"] and v["values_equal_decoded"] and v["recorder_values_exact_replays"] == 3
    assert v["recorder_lights_consistent_replays"] == 3
    for key in ("listeners", "listeners_feed", "listeners_end"):
        bad = good[:2] + [_replay_result(**{key: {"ok": False}})]
        assert not stack.verdict(None, bad, "dumpfile", 3)["ok"], key
    missing_end = good[:2] + [{k: v for k, v in _replay_result().items() if k != "listeners_end"}]
    assert not stack.verdict(None, missing_end, "dumpfile", 3)["only_loopback_listeners"]
    for key in ("witness_values", "app_values"):
        v = stack.verdict(None, good[:2] + [_replay_result(**{key: {"ok": False}})], "dumpfile", 3)
        assert not v["ok"] and not v["values_equal_decoded"], key
    aligned = stack.verdict(None, good[:2] + [_replay_result(values={"ok": True, "exact": False})], "dumpfile", 3)
    assert aligned["ok"] and aligned["recorder_values_exact_replays"] == 2
    # the light: the mock provider's own writes are a gate; the recorder's hazard rows are reported and counted, never a gate
    mock_late = stack.verdict(None, good[:2] + [_replay_result(lights={"mock_log": {"ok": False}, "recorder": {"consistent": {"ok": True}}})],
                              "dumpfile", 3)
    assert not mock_late["ok"] and not mock_late["lights_in_window"]
    inconsistent = stack.verdict(None, good[:2] + [_replay_result(lights={"mock_log": {"ok": True}, "recorder": {"consistent": {"ok": False}}})],
                                 "dumpfile", 3)
    assert inconsistent["ok"] and inconsistent["lights_in_window"] and inconsistent["recorder_lights_consistent_replays"] == 2
    no_decisions = stack.verdict(None, good[:2] + [_replay_result(decisions={"ok": False})], "dumpfile", 3)
    assert not no_decisions["ok"] and not no_decisions["lights_in_window"]


def test_docker_log_times():
    text = ("2026-01-02T03:04:05.250000000Z INFO:mock_service:Feeding 'Vehicle.Body.Lights.Hazard.IsSignaling' with value True\n"
            "2026-01-02T03:04:06Z INFO:mock_service:something else\n")
    got = stack.docker_log_times(text, r"with value (True|False)")
    assert len(got) == 1 and got[0][1].endswith("True")
    epoch = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc).timestamp()
    assert got[0][0] == pytest.approx(epoch + 0.25)


# --- the recording, its summary and its DBC -------------------------------------------------------

SEGMENTS = [["cruise", 0, 100], ["hard brake", 100, 160], ["stopped", 160, 200], ["reverse", 200, 260]]


SYN_LOGS = {"sigsim": "sigsim.log", "carla": "carla.log"}      # a recording's log by its generator (spec-2 2.1), this file's spelling


def _recording(tmp_path, seed=7, name="20260101-sigsim-7", **over):
    """A synthetic recording directory as sigsim writes it (manifest-line.json, sigsim.log, its
    sha256 file, summary.json). `over` replaces: line_sha, listed_sha, dbc_sha (the line's DBC
    sha256), summary_name, trip_seed, params_seed, params (the trip's whole params value), segments
    (None leaves the key out), messages, no_summary, summary_raw (summary.json's text, verbatim).
    SDV Phase 7 WP3b: gen, the line's source.generator (sigsim, the default, writes exactly what it wrote before;
    carla writes a CARLA recording's line: profile 3, the carla vehicle at SYN_OTHER_L_MM, the encoder's five params
    and an rtf, which its trip carries too, with encoder_sha256 when given); log, the file the log is written to (by
    default the generator's); path_log, the basename the line's recording.path names (by default log); listed_name,
    the file name <log>.sha256 gives after the hash."""
    d = tmp_path / name
    d.mkdir()
    gen = over.get("gen", "sigsim")
    log_name = over.get("log", SYN_LOGS.get(gen, "sigsim.log"))
    log = b"(0.000000) vcan0 100#0000000000000000\n(0.020000) vcan0 100#0000000000000000\n"
    (d / log_name).write_bytes(log)
    sha = hashlib.sha256(log).hexdigest()
    path = "~/rec/%s/%s" % (name, over.get("path_log", log_name))
    if gen == "carla":
        line = {"name": name, "profile_id": 3,
                "recording": {"format": "candump-log", "path": path, "sha256": over.get("line_sha", sha)},
                "source": {"generator": gen, "vehicle": {"name": "carla-ego", "wheelbase_mm": SYN_OTHER_L_MM},
                           "params": {"catalog_digest": SYN_DIGEST, "dbc_sha256": over.get("dbc_sha", "e5" * 32), "seed": seed,
                                      "town": "Town01", "version": "0.9.16"},
                           "rtf": dict(RTF)}}
    else:
        line = {"name": name, "profile_id": 1,
                "recording": {"format": "candump-log", "path": path, "sha256": over.get("line_sha", sha)},
                "source": {"generator": gen, "vehicle": {"name": "sigsim-design-car", "wheelbase_mm": SYN_L_MM},
                           "params": {"dbc_sha256": over.get("dbc_sha", "e5" * 32), "seed": seed, "sigsim_sha256": "f6" * 32}}}
    (d / "manifest-line.json").write_text(json.dumps(line), encoding="ascii")
    (d / (log_name + ".sha256")).write_text("%s  %s\n" % (over.get("listed_sha", sha), over.get("listed_name", log_name)), encoding="ascii")
    trip = {"seed": over.get("trip_seed", seed), "params": over["params"] if "params" in over else {"seed": over.get("params_seed", seed)},
            "segments": over.get("segments", SEGMENTS), "messages": over.get("messages", {"SliceDynamics": 2})}
    if gen == "carla":
        trip["rtf"] = dict(RTF)
        if "encoder_sha256" in over:
            trip["encoder_sha256"] = over["encoder_sha256"]
    if trip["segments"] is None:
        del trip["segments"]
    if "summary_raw" in over:
        (d / "summary.json").write_text(over["summary_raw"], encoding="utf-8")
    elif not over.get("no_summary"):
        (d / "summary.json").write_text(json.dumps({"name": over.get("summary_name", name), "trip": trip}), encoding="utf-8")
    return d, line, sha


def test_a_consistent_recording_gives_its_identity_seed_and_summary(tmp_path):
    d, line, sha = _recording(tmp_path)
    rec = stack.recording_identity(d)
    assert rec["sha256"] == sha and rec["manifest_line"] == line
    assert rec["manifest_line_sha256"] == hashlib.sha256((d / "manifest-line.json").read_bytes()).hexdigest()
    assert stack.recording_seed(line, None) == 7 and stack.recording_seed(line, 7) == 7
    summ = stack.recording_summary(d, line)
    assert summ["hard_brake_ms"] == [100, 160] and summ["trip"]["segments"] == SEGMENTS
    assert summ["sha256"] == hashlib.sha256((d / "summary.json").read_bytes()).hexdigest()
    assert stack.check_summary_counts(summ["trip"], [(0, "SliceDynamics", {}), (20, "SliceDynamics", {})]) == {"SliceDynamics": 2}


def test_the_seed_is_the_recordings_and_a_disagreeing_seed_is_refused(tmp_path):
    _d, line, _sha = _recording(tmp_path)
    with pytest.raises(stack.StackError, match="--seed 1 disagrees"):
        stack.recording_seed(line, 1)
    # a seed that is not an integer is refused, a bool (an int to Python) and a string included
    for not_a_seed in ("7", True, 7.0, None):
        bad = json.loads(json.dumps(line))
        bad["source"]["params"]["seed"] = not_a_seed
        with pytest.raises(stack.StackError, match="not an integer"):
            stack.recording_seed(bad, None)


@pytest.mark.parametrize("over, match", [
    ({"line_sha": "00" * 32}, "its manifest line says"),
    ({"listed_sha": "00" * 32}, "sigsim.log.sha256 says"),
])
def test_a_recording_whose_log_does_not_hash_to_its_records_is_refused(tmp_path, over, match):
    d, _line, _sha = _recording(tmp_path, **over)
    with pytest.raises(stack.StackError, match=match):
        stack.recording_identity(d)


@pytest.mark.parametrize("over, match", [
    ({"no_summary": True}, "no readable summary.json"),
    ({"summary_name": "20260101-sigsim-8"}, "does not describe this recording: name"),
    ({"trip_seed": 8}, "trip.seed 8"),
    ({"params_seed": 8}, "trip.params.seed 8"),
    ({"params": 5}, "trip.params.seed 5"),
    ({"segments": [s for s in SEGMENTS if s[0] != "hard brake"]}, "0 'hard brake' segments"),
    ({"segments": SEGMENTS + [["hard brake", 300, 360]]}, "2 'hard brake' segments"),
    # no trip.segments to read a hard brake from, in each way a summary can lack them: a clear
    # refusal, not a KeyError or an AttributeError out of the code that reads them
    ({"segments": None}, "no trip.segments"),
    ({"segments": {"hard brake": [100, 160]}}, "no trip.segments"),
    ({"summary_raw": json.dumps({"name": "20260101-sigsim-7"})}, "no trip.segments"),
    ({"summary_raw": json.dumps({"name": "20260101-sigsim-7", "trip": [["hard brake", 100, 160]]})}, "no trip.segments"),
    ({"summary_raw": json.dumps([["hard brake", 100, 160]])}, "no trip.segments"),
    # segments that are not [name, start_ms, end_ms] lists
    ({"segments": [["hard brake", 100]]}, "not a list of"),
    ({"segments": [["hard brake", 100, "soon"]]}, "not a list of"),
    ({"segments": [7]}, "not a list of"),
    # a summary that is not JSON (a torn write)
    ({"summary_raw": '{"name": "20260101-sigsim-7", "trip": {"seg'}, "not valid JSON"),
])
def test_a_summary_that_is_not_the_recordings_is_refused(tmp_path, over, match):
    d, line, _sha = _recording(tmp_path, **over)
    with pytest.raises(stack.StackError, match=match):
        stack.recording_summary(d, line)


def test_a_summary_whose_message_counts_are_not_the_logs_is_refused():
    with pytest.raises(stack.StackError, match="frames per message"):
        stack.check_summary_counts({"messages": {"SliceDynamics": 3}}, [(0, "SliceDynamics", {}), (20, "SliceDynamics", {})])
    with pytest.raises(stack.StackError, match="frames per message"):
        stack.check_summary_counts({"messages": {"SliceDynamics": 1}}, [(0, "SliceDynamics", {}), (0, "SliceGear", {})])


def test_the_windows_are_the_summarys_hard_brake_segment(tmp_path):
    d, line, _sha = _recording(tmp_path)
    summ = stack.recording_summary(d, line)
    frames = []
    for t in range(0, 261, 20):
        v = 15.0 if t < 160 else (0.0 if t < 220 else -0.5)
        frames.append((t, "SliceDynamics", {"LongVel": v, "LongAccel": -6.0 if 100 <= t < 160 else 0.0}))
    w = rc.expected_windows(summ["trip"], frames, "LongVel", 20)
    assert w["hard_brake_ms"] == summ["hard_brake_ms"] == [100, 160]
    assert w["on_window_ms"] == [80, 160] and w["off_window_ms"] == [140, 220]
    assert "summary.json" in w["source"]


def test_sigsim_provenance_is_reported_not_required(tmp_path):
    _d, line, _sha = _recording(tmp_path)
    f = tmp_path / "sigsim.py"
    f.write_bytes(b"print(1)\n")
    now = hashlib.sha256(b"print(1)\n").hexdigest()
    p = stack.sigsim_provenance(line, f)
    assert p["current_sha256"] == now and p["recording_sigsim_sha256"] == "f6" * 32 and p["current_equals_recording"] is False
    line["source"]["params"]["sigsim_sha256"] = now
    assert stack.sigsim_provenance(line, f)["current_equals_recording"] is True
    missing = stack.sigsim_provenance(line, tmp_path / "gone.py")
    assert missing["current_sha256"] is None and missing["current_equals_recording"] is False


def test_windows_paths_and_the_main_checkout(tmp_path, monkeypatch):
    assert stack.windows_path("/mnt/e/Project/x/y", None) == "E:\\Project\\x\\y"
    assert stack.windows_path("E:/Project/x", None) == "E:\\Project\\x"
    assert stack.windows_path("/home/u/sdv-cache/dbc/a.dbc", "Distro-1") == "\\\\wsl.localhost\\Distro-1\\home\\u\\sdv-cache\\dbc\\a.dbc"
    with pytest.raises(stack.StackError):
        stack.windows_path("relative/path", None)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: E:/Project/main-checkout/.git/worktrees/wt\n", encoding="utf-8")
    assert stack.main_checkout(wt) == "E:\\Project\\main-checkout"
    (wt / ".git").write_text("gitdir: E:/elsewhere/not-a-git-dir\n", encoding="utf-8")
    with pytest.raises(stack.StackError, match="does not name"):
        stack.main_checkout(wt)
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Distro-1")
    assert stack.main_checkout(main) == stack.windows_path(str(main), "Distro-1")


DBC_BYTES = b'VERSION ""\n\nBO_ 256 SliceDynamics: 8 Vector__XXX\n'
EXPORT_ADVICE = "run it in PowerShell or cmd; in Git Bash use cmd //c with the argument in single quotes"


def _dbc_rig(tmp_path, monkeypatch, known=True):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Distro-1")
    sha = hashlib.sha256(DBC_BYTES).hexdigest()
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: E:/Project/main-checkout/.git/worktrees/wt\n", encoding="utf-8")
    sources = {sha: {"commit": "c0" * 20, "path": "sdv/vss/slice.dbc", "git_blob": stack.git_blob_sha1(DBC_BYTES)}} if known else {}
    working = tmp_path / "slice.dbc"
    working.write_bytes(b"// an edited comment\n" + DBC_BYTES)
    return sha, wt, sources, working


def test_a_missing_dbc_is_refused_with_the_exact_export_command(tmp_path, monkeypatch):
    sha, wt, sources, working = _dbc_rig(tmp_path, monkeypatch)
    cache = tmp_path / "cache"
    with pytest.raises(stack.StackError) as exc:
        stack.resolve_dbc(sha, cache, sources, wt, working)
    dest = stack.windows_path(str((cache / "dbc" / ("%s.dbc" % sha)).absolute()), "Distro-1")
    cmd = 'cmd /c "git -C E:\\Project\\main-checkout show %s:sdv/vss/slice.dbc > %s"' % ("c0" * 20, dest)
    assert cmd in str(exc.value)
    # where it runs: PowerShell or cmd as it stands; Git Bash (which rewrites /c, and whose double quotes
    # collapse the leading \\ of the UNC path) with cmd //c and the argument in single quotes
    assert EXPORT_ADVICE in str(exc.value) and stack.EXPORT_SHELL in str(exc.value)
    assert (cache / "dbc").is_dir()                     # the export has a directory to write into
    assert not (cache / "dbc" / ("%s.dbc" % sha)).exists()


def test_a_dbc_no_commit_is_known_for_is_refused_without_guessing(tmp_path, monkeypatch):
    sha, wt, _sources, working = _dbc_rig(tmp_path, monkeypatch, known=False)
    with pytest.raises(stack.StackError) as exc:
        stack.resolve_dbc(sha, tmp_path / "cache", {}, wt, working)
    msg = str(exc.value)
    assert "git -C E:\\Project\\main-checkout log --all --format=%H -- sdv/vss/slice.dbc" in msg
    assert "show <commit>:sdv/vss/slice.dbc" in msg and "never picks a commit" in msg
    assert EXPORT_ADVICE in msg      # the export command is cmd's here too


def test_a_cached_dbc_must_have_its_sha256_and_git_blob(tmp_path, monkeypatch):
    sha, wt, sources, working = _dbc_rig(tmp_path, monkeypatch)
    cache = tmp_path / "cache"
    (cache / "dbc").mkdir(parents=True)
    cached = cache / "dbc" / ("%s.dbc" % sha)
    cached.write_bytes(DBC_BYTES + b"\n")
    with pytest.raises(stack.StackError, match="hashes to"):
        stack.resolve_dbc(sha, cache, sources, wt, working)
    cached.write_bytes(DBC_BYTES)
    wrong_blob = {sha: dict(sources[sha], git_blob="00" * 20)}
    with pytest.raises(stack.StackError, match="git blob"):
        stack.resolve_dbc(sha, cache, wrong_blob, wt, working)
    got = stack.resolve_dbc(sha, cache, sources, wt, working)
    assert got["path"] == str(cached.absolute()) and got["git_blob"] == sources[sha]["git_blob"] and got["source"] == sources[sha]
    assert got["working_copy_sha256"] != sha and got["working_copy_body_equal"] is True     # never staged, only reported


def test_the_dbc_sources_file_names_the_recordings_dbc():
    sources = stack.load_dbc_sources()
    for sha, src in sources.items():
        assert re.fullmatch(r"[0-9a-f]{64}", sha) and re.fullmatch(r"[0-9a-f]{40}", src["commit"])
        assert re.fullmatch(r"[0-9a-f]{40}", src["git_blob"]) and src["path"] == "sdv/vss/slice.dbc"
    rec = stack.RECORDING_DIR / "manifest-line.json"
    if rec.exists():
        assert json.loads(rec.read_text(encoding="ascii"))["source"]["params"]["dbc_sha256"] in sources


@pytest.mark.skipif(not (stack.RECORDING_DIR / "summary.json").exists(), reason="needs the recording (SDV_RECORDING)")
def test_the_real_recording_is_consistent_with_its_summary():
    """Read-only: the recording directory's own files agree with each other (no decode, no run)."""
    rec = stack.recording_identity(stack.RECORDING_DIR)
    line = rec["manifest_line"]
    seed = stack.recording_seed(line, None)
    summ = stack.recording_summary(stack.RECORDING_DIR, line)
    assert summ["trip"]["seed"] == seed and summ["hard_brake_ms"] == list(rc.hard_brake_segment(summ["trip"]))
    cached = stack.CACHE / "dbc" / ("%s.dbc" % line["source"]["params"]["dbc_sha256"])
    if cached.exists():
        assert stack.resolve_dbc(line["source"]["params"]["dbc_sha256"])["path"] == str(cached.absolute())


# --- how prepare() wires it together ---------------------------------------------------------------
# Context.prepare on a synthetic recording directory, catalogue and DBC, with no Docker (the two
# docker calls and time_sync stand in) and no decoding (cantools and python-can are in the sim venv,
# not in CI's): replaycheck.decode_recording is replaced by frames of a trip with one hard brake, so
# what is tested is where prepare takes its windows and its seed from, not the decoding.

TINY_DBC = b"""\
VERSION ""

BO_ 256 SliceDynamics: 8 SIGSRC
 SG_ LongVel : 0|16@1- (0.01,0) [-327.68|327.67] "m/s" VSSRX
 SG_ LongAccel : 16|16@1- (0.001,0) [-32.768|32.767] "m/s^2" VSSRX
 SG_ SteerAngleRow1 : 32|16@1- (0.01,0) [-327.68|327.67] "degrees" VSSRX
 SG_ YawRate : 48|16@1- (0.01,0) [-327.68|327.67] "degrees/s" VSSRX

BO_ 257 SliceGear: 8 SIGSRC
 SG_ CurrentGear : 0|8@1- (1,0) [-128|127] "" VSSRX

BA_ "GenMsgCycleTime" BO_ 256 20;
BA_ "GenMsgCycleTime" BO_ 257 50;
"""

CONTRACT_PY = """\
VSS_COMMIT = %r
VSS_ARCHIVE_SHA256 = %r
VSS_TOOLS_VERSION = "0.0.0"
CATALOG_DIGEST = 0x12345678
DBC_PERIOD_MS = {"SliceDynamics": 20, "SliceGear": 50}
RULE26_DBC_MESSAGE = "SliceDynamics"
AGE_MAX_MS = %d
PROFILES = ()
""" % ("c1" * 20, "d2" * 32, SYN_AGE_MAX_MS)


def _nest(nodes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """{path: leaf node} as a vss-tools JSON tree (branches with children)."""
    tree: Dict[str, Any] = {}
    for path, node in nodes.items():
        *branches, leaf = path.split(".")
        level = tree
        for b in branches:
            level = level.setdefault(b, {"type": "branch", "children": {}})["children"]
        level[leaf] = node
    return tree


def _trip_frames():
    """The decoded frames of a trip with one hard brake at 100..160 ms and the vehicle moving again
    (in reverse) from 220 ms: what predict() turns into the lights on at 100 and off at 160."""
    frames = []
    v = 15.0
    for t in range(0, 261, 20):
        a = -6.0 if 100 <= t < 160 else 0.0
        if t >= 160:
            v = 0.0
        if t >= 220:
            v = -0.5
        frames.append((t, "SliceDynamics", {"LongVel": v, "LongAccel": a}))
        if 100 <= t < 160:
            v -= 5.0
    return frames


# What a bridge run's prepare also reads from the contract (synthetic values): the table, the compiled ids, the
# live defaults and the project branch the bridge's write-back paths hang under.
BRIDGE_CONTRACT_PY = CONTRACT_PY + """\
PROJECT_BRANCH = "Vehicle.DualVm"
PROFILES = ({"id": 1, "l_mm": %(l)d, "source_vehicle": "sigsim-design-car"},
            {"id": 2, "l_mm": %(l)d, "source_vehicle": "sigsim-design-car", "run_window_max_ms": 30000},
            {"id": 3, "l_mm": %(other)d, "source_vehicle": "carla-ego"})
COMPILED_PROFILE_IDS = (1, 2)
LIVE_DEFAULT_PROFILE = {"sigsim": 1, "carla": 3}
""" % {"l": SYN_L_MM, "other": SYN_OTHER_L_MM}
# The frozen generation's contract (SDV Phase 7, WP2's freeze): the same synthetic table with profile 3 compiled.
FROZEN_CONTRACT_PY = BRIDGE_CONTRACT_PY.replace("COMPILED_PROFILE_IDS = (1, 2)\n", "COMPILED_PROFILE_IDS = (1, 2, 3)\n")
LAYER = "vehicle-sigsim.vspec"
CARLA_LAYER, CARLA_CATALOGUE = "vehicle-carla.vspec", "vss-databroker-carla.json"     # generate.py's names for the carla pair


def _prepare_rig(tmp_path, monkeypatch, hard_brake=(100, 160), seed=7, bridge=False, layer_default=None, frozen=False, **rec_over):
    """Everything prepare(pull=False, build=False) reads, synthetic, and stack's paths pointed at it.
    hard_brake is the [start, end] ms of the hard-brake segment in the recording's summary.json. bridge: the
    catalogue carries every Monitor.VssClaim leaf the bridge writes and the contract what a bridge run reads;
    layer_default: a generated vehicle layer whose Wheelbase default it is (None: a generation without one).
    frozen (SDV Phase 7 WP3b): the generation after WP2's freeze, as generate.py writes it: the contract compiles
    profile 3, and beside vehicle_layer (sigsim's, layer_default, SYN_L_MM unless given) the manifest names
    vehicle_layers {sigsim, carla} and databroker_catalogues {sigsim, carla}, the carla catalogue serving profile 3's L
    (SYN_OTHER_L_MM) as its Wheelbase default, each file listed in its outputs. rec_over takes _recording's gen, log,
    path_log, listed_name and encoder_sha256 too."""
    if frozen and layer_default is None:
        layer_default = SYN_L_MM
    cat, mapping, _dbc = _synthetic()
    if bridge or frozen:
        for leaf in stack.bridge_core().WRITEBACK_LEAVES:
            cat.setdefault("Vehicle.DualVm.Monitor.VssClaim." + leaf, {"type": "sensor", "datatype": "uint32"})
    if layer_default is not None:
        cat["Vehicle.Chassis.Wheelbase"] = dict(cat["Vehicle.Chassis.Wheelbase"], default=layer_default)
    dbc_sha = hashlib.sha256(TINY_DBC).hexdigest()
    segments = [[n, *(hard_brake if n == "hard brake" else (a, b))] for n, a, b in SEGMENTS]
    rec_over.setdefault("messages", {"SliceDynamics": len(_trip_frames())})
    rec, _line, _sha = _recording(tmp_path, seed=seed, dbc_sha=dbc_sha, segments=segments, **rec_over)
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "vss-databroker.json").write_text(json.dumps(_nest(cat)), encoding="utf-8")
    (gen / "vss-can-mapping.json").write_text(json.dumps(_nest({p: dict(n, dbc2vss=mapping[p]) if p in mapping else n
                                                                for p, n in cat.items()})), encoding="utf-8")
    (gen / "vss_contract.py").write_text(FROZEN_CONTRACT_PY if frozen else BRIDGE_CONTRACT_PY if bridge else CONTRACT_PY, encoding="utf-8")
    overlay = tmp_path / "overlay.vspec"
    overlay.write_text("# a synthetic overlay\n", encoding="utf-8")
    man: Dict[str, Any] = {"inputs": {"overlay.vspec": stack.sha256_file(overlay), "slice.dbc": dbc_sha}}
    if layer_default is not None:
        text = "Vehicle.Chassis.Wheelbase:\n  default: %d\n" % layer_default
        (gen / LAYER).write_text(text, encoding="utf-8")
        man["vehicle_layer"] = {"file": LAYER, "run_type": "sigsim", "profile_id": 1, "source_vehicle": "sigsim-design-car",
                                "path": "Vehicle.Chassis.Wheelbase", "default": layer_default}
        man["outputs"] = {LAYER: {"sha256": hashlib.sha256(text.encode()).hexdigest(), "bytes": len(text)}}
    if frozen:
        text = "Vehicle.Chassis.Wheelbase:\n  default: %d\n" % SYN_OTHER_L_MM
        (gen / CARLA_LAYER).write_text(text, encoding="utf-8")
        carla_cat = dict(cat, **{"Vehicle.Chassis.Wheelbase": dict(cat["Vehicle.Chassis.Wheelbase"], default=SYN_OTHER_L_MM)})
        (gen / CARLA_CATALOGUE).write_text(json.dumps(_nest(carla_cat)), encoding="utf-8")
        man["vehicle_layers"] = {"sigsim": dict(man["vehicle_layer"]),
                                 "carla": {"file": CARLA_LAYER, "run_type": "carla", "profile_id": 3, "source_vehicle": "carla-ego",
                                           "path": "Vehicle.Chassis.Wheelbase", "default": SYN_OTHER_L_MM}}
        man["databroker_catalogues"] = {"sigsim": "vss-databroker.json", "carla": CARLA_CATALOGUE}
        for f in (CARLA_LAYER, CARLA_CATALOGUE, "vss-databroker.json"):
            data = (gen / f).read_bytes()
            man["outputs"][f] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    (gen / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    cache = tmp_path / "cache"
    (cache / "dbc").mkdir(parents=True)
    (cache / "dbc" / ("%s.dbc" % dbc_sha)).write_bytes(TINY_DBC)
    sources = {dbc_sha: {"commit": "c0" * 20, "path": "sdv/vss/slice.dbc", "git_blob": stack.git_blob_sha1(TINY_DBC)}}
    seen = {}

    def fake_decode(log_path, dbc_path, mapping, _transforms):
        seen.update(log=Path(log_path), dbc=Path(dbc_path), paths=sorted(mapping))
        return {"values": {p: [] for p in mapping}, "half_lsb": {p: 0.0 for p in mapping}, "frames": _trip_frames()}

    for name, value in (("GEN", gen), ("OVERLAY", overlay), ("CACHE", cache), ("RECORDING_DIR", rec)):
        monkeypatch.setattr(stack, name, value)
    monkeypatch.setattr(stack, "load_dbc_sources", lambda: sources)
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: subprocess.CompletedProcess(a, 0, "27.0\n", ""))
    monkeypatch.setattr(stack, "time_sync", lambda: {"daemon": "none", "synchronised": False})
    monkeypatch.setattr(rc, "decode_recording", fake_decode)
    return types.SimpleNamespace(rec=rec, seen=seen, summary=rec / "summary.json", runs=tmp_path / "runs", gen=gen, overlay=overlay)


def _prepare(rig, name, cli_seed=None, bridge="none"):
    ctx = stack.Context(rig.runs / name, cli_seed, bridge)
    return ctx, ctx.prepare(pull=False, build=False)


def test_the_rig_is_a_catalogue_and_a_mapping_the_stack_can_read(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    ctx, man = _prepare(rig, "a")
    cat, mapping, _dbc = _synthetic()
    assert ctx.catalogue == cat and ctx.mapping == mapping and not [c for c in man["scenario_checks"] if not c[1]]
    assert rig.seen["log"] == rig.runs / "a" / "in" / "sigsim.log" and rig.seen["dbc"].read_bytes() == TINY_DBC     # the staged copies
    assert rig.seen["paths"] == sorted(mapping)
    assert ctx.witness_paths == sorted(ctx.mapping) and len(ctx.witness_paths) == len(mapping)    # every path the CAN provider writes


@pytest.mark.parametrize("segment, on, off", [
    ([100, 160], [80, 160], [140, 220]),
    ([90, 160], [70, 160], [140, 220]),        # summary.json's hard brake starts earlier: the on window's lower edge follows
    ([100, 170], [80, 170], [150, 220]),       # ... ends later: the on window's upper and the off window's lower edge follow
])
def test_prepare_derives_the_windows_from_the_recordings_summary(tmp_path, monkeypatch, segment, on, off):
    rig = _prepare_rig(tmp_path, monkeypatch, hard_brake=segment)
    ctx, man = _prepare(rig, "a")
    want = hashlib.sha256(rig.summary.read_bytes()).hexdigest()
    assert ctx.windows["hard_brake_ms"] == segment
    assert ctx.windows["on_window_ms"] == on and ctx.windows["off_window_ms"] == off
    assert man["expected"]["windows"] == ctx.windows and ctx.windows["summary_sha256"] == want
    assert man["recording"]["summary"]["sha256"] == want and man["recording"]["summary"]["hard_brake_ms"] == segment
    assert want in man["expected"]["windows_from"]
    assert [(p["t_rec_ms"], p["hazard"]) for p in ctx.prediction] == [(100, True), (160, False)]     # from the frames, not the summary
    assert json.loads((rig.runs / "a" / "manifest.json").read_text(encoding="utf-8"))["expected"]["windows"] == ctx.windows


def test_prepare_takes_the_seed_from_the_manifest_line(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, seed=7)
    ctx, man = _prepare(rig, "a")
    assert ctx.seed == 7 and man["recording"]["seed"] == 7 and man["recording"]["cli_seed"] is None
    assert "manifest line" in man["recording"]["seed_from"]
    writers = [r for r in ctx.rows if r["writer"] == attr.CAN_PROVIDER]
    assert writers and all(r["upstream"] == "sigsim seed 7" for r in writers)
    assert ctx.scenario["source"]["params"]["seed"] == 7
    ctx, man = _prepare(rig, "b", cli_seed=7)              # a --seed that agrees is accepted and changes nothing
    assert ctx.seed == 7 and man["recording"]["seed"] == 7 and man["recording"]["cli_seed"] == 7


def test_prepare_refuses_a_cli_seed_that_disagrees_before_writing_anything(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, seed=7)
    with pytest.raises(stack.StackError, match="--seed 8 disagrees"):
        _prepare(rig, "a", cli_seed=8)
    assert not (rig.runs / "a").exists() and "log" not in rig.seen           # no run directory, nothing staged or decoded


def test_prepare_refuses_windows_that_the_recording_does_not_switch_in(tmp_path, monkeypatch):
    # summary.json puts the hard brake nowhere near where the frames' lights would switch (100 and 160)
    rig = _prepare_rig(tmp_path, monkeypatch, hard_brake=(20, 60))
    with pytest.raises(stack.StackError, match=r"does not switch once inside the windows summary\.json gives"):
        _prepare(rig, "a")


def test_prepare_refuses_a_hard_brake_after_which_nothing_moves_with_a_message(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, hard_brake=(100, 300))      # no frame after 300 ms: no off window to derive
    with pytest.raises(stack.StackError, match="windows cannot be derived"):
        _prepare(rig, "a")


def test_prepare_refuses_a_summary_whose_frame_counts_are_not_the_logs(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, messages={"SliceDynamics": len(_trip_frames()) + 1})
    with pytest.raises(stack.StackError, match="frames per message"):
        _prepare(rig, "a")


def test_prepare_reports_but_does_not_require_the_current_sigsim(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    _ctx, man = _prepare(rig, "a")
    sig = man["recording"]["sigsim"]
    assert sig["recording_sigsim_sha256"] == "f6" * 32 and sig["current_equals_recording"] is False     # refused on neither


# --- the vehicle layer, the bridge's run header and C12a (Phase 2 WP8) -------------------------------

def test_without_a_bridge_the_header_items_and_the_age_clock_are_null_and_c12a_holds(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    ctx, man = _prepare(rig, "a")
    h = ctx.run_header("dumpfile-1", "dumpfile")
    assert (h["bridge_mode"], h["profile_id"], h["profile_source"], h["age_max_ms"], h["demo_odd_window"]) == ("none", None, None, None, None)
    assert h["time_sync"] == {"daemon": "none", "synchronised": False, "age_clock": None} == man["time_sync"]
    assert ctx.check_header(h)[1], ctx.check_header(h)
    bad = dict(h, time_sync=dict(h["time_sync"], age_clock="realtime"))      # no bridge reads ages: no age clock
    assert not ctx.check_header(bad)[1] and "age_clock must be null" in ctx.check_header(bad)[2]


def test_a_broker_run_header_carries_the_bridge_items_and_the_brokers_age_clock(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True, layer_default=SYN_L_MM)
    ctx, man = _prepare(rig, "a", bridge="broker")
    h = ctx.run_header("vcan-1", "vcan")
    assert (h["bridge_mode"], h["profile_id"], h["profile_source"], h["age_max_ms"], h["demo_odd_window"]) == (
        "broker", 1, "scenario", SYN_AGE_MAX_MS, None)
    assert h["profile_id"] == ctx.scenario["profile_id"] and h["age_max_ms"] == ctx.contract.AGE_MAX_MS
    assert h["time_sync"]["age_clock"] == "realtime" == stack.AGE_CLOCK["broker"] == man["time_sync"]["age_clock"]
    assert h["source_vehicle"] == {"name": "sigsim-design-car", "wheelbase_mm": SYN_L_MM}
    c12a = ctx.check_header(h)
    assert c12a[1], c12a
    assert man["bridge"]["mode"] == "broker" and man["bridge"]["writes"] == stack.bridge_writes(ctx.contract)
    assert man["bridge"]["wheelbase"] == dict(ctx.wheelbase, served=True, value_mm=SYN_L_MM, l_mm=SYN_L_MM)


@pytest.mark.parametrize("change, why", [
    ({"time_sync": {"daemon": "none", "synchronised": False, "age_clock": None}}, "age_clock None must name the clock"),
    ({"time_sync": {"daemon": "none", "synchronised": False}}, "must name the clock"),
    ({"time_sync": {"daemon": "none", "synchronised": False, "age_clock": "monotonic"}}, "is not the broker mode's age source clock 'realtime'"),
    ({"time_sync": {"age_clock": "realtime"}}, "time_sync not filled"),
    ({"profile_id": 2}, "is not the scenario entry's 1"),
    ({"profile_id": 3}, "is not compiled into the guest's table"),
    ({"profile_id": 9}, "profile 9 is not bound"),
    ({"profile_source": "live-default", "profile_id": 2}, "is not run type 'sigsim''s default 1"),
    ({"profile_source": "guessed"}, "profile_source 'guessed' is not scenario or live-default"),
    ({"profile_source": None}, "profile_source must be set with a bridge"),
    ({"age_max_ms": SYN_AGE_MAX_MS + 1}, "age_max_ms %d != generated %d" % (SYN_AGE_MAX_MS + 1, SYN_AGE_MAX_MS)),
    ({"age_max_ms": None}, "age_max_ms must be set with a bridge"),
    ({"source_vehicle": {"name": "sigsim-design-car", "wheelbase_mm": SYN_OTHER_L_MM}},
     "source vehicle wheelbase %d != profile L %d" % (SYN_OTHER_L_MM, SYN_L_MM)),
    ({"demo_odd_window": {"profile_id": 2, "start_s": 1, "duration_s": 30.5}}, "at most 30000 ms"),
    ({"demo_odd_window": {"profile_id": 1, "start_s": 1, "duration_s": 5}}, "must name the demo-ODD profile"),
    ({"demo_odd_window": {"profile_id": 2, "start_s": -1, "duration_s": 5}}, "must start at >= 0 s"),
    ({"bridge_mode": "carrier-pigeon"}, "is not none, broker, can or replay"),
])
def test_c12a_refuses_a_bridge_header_that_does_not_describe_the_run(tmp_path, monkeypatch, change, why):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True, layer_default=SYN_L_MM)
    ctx, _man = _prepare(rig, "a", bridge="broker")
    h = dict(ctx.run_header("vcan-1", "vcan"), **change)
    c = ctx.check_header(h)
    assert not c[1] and why in c[2], c


def test_c12a_takes_a_demo_window_inside_the_profiles_run_window_and_a_live_default(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True, layer_default=SYN_L_MM)
    ctx, _man = _prepare(rig, "a", bridge="broker")
    h = dict(ctx.run_header("vcan-1", "vcan"), demo_odd_window={"profile_id": 2, "start_s": 0, "duration_s": 30})
    assert ctx.check_header(h)[1]
    live = dict(ctx.run_header("vcan-1", "vcan"), profile_source="live-default")
    assert attr.check_header(live, {1: {"l_mm": SYN_L_MM}}, SYN_AGE_MAX_MS, live_defaults={"sigsim": 1}, age_clock="realtime")[1]


@pytest.mark.parametrize("layer_default", [0, SYN_OTHER_L_MM])
def test_broker_mode_refuses_a_catalogue_that_serves_another_wheelbase_before_writing(tmp_path, monkeypatch, layer_default):
    """Spec 5.6, at the stack: a served Wheelbase that is not the profile's L (VSS 6.0's default 0, or another
    vehicle's layer) is what the bridge refuses to start on; prepare refuses it before any run directory exists.
    Without a bridge the same catalogue is fine (the recording does not depend on it)."""
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True, layer_default=layer_default)
    with pytest.raises(stack.StackError, match="not the profile's L %d mm .*the bridge would refuse to start" % SYN_L_MM):
        _prepare(rig, "a", bridge="broker")
    assert not (rig.runs / "a").exists()
    _prepare(rig, "b")


def test_broker_mode_starts_on_a_catalogue_that_serves_no_wheelbase_and_records_the_bridges_note(tmp_path, monkeypatch):
    """Spec 5.6's other branch: a catalogue whose Wheelbase has no default serves none, the bridge starts with its
    note, and so does prepare, with the note in the run manifest; L is then checked against the declared vehicle
    only (C12a, which holds here and still bites on another vehicle)."""
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    assert "default" not in attr.leaf_nodes(json.loads((rig.gen / "vss-databroker.json").read_text(encoding="utf-8")))[attr.WHEELBASE]
    ctx, man = _prepare(rig, "a", bridge="broker")
    assert man["bridge"]["wheelbase"] == ctx.wheelbase
    assert {k: ctx.wheelbase[k] for k in ("served", "l_mm", "note")} == {"served": False, "l_mm": SYN_L_MM, "note": stack.WHEELBASE_NOTE}
    h = ctx.run_header("vcan-1", "vcan")
    assert ctx.check_header(h)[1]
    other = dict(h, source_vehicle={"name": "sigsim-design-car", "wheelbase_mm": SYN_OTHER_L_MM})
    assert not ctx.check_header(other)[1]


@pytest.mark.parametrize("served, why", [
    (None, None), (SYN_L_MM, None), (True, "the bridge would refuse"), (SYN_OTHER_L_MM, "the bridge would refuse"),
])
def test_served_wheelbase_follows_both_branches_of_spec_5_6(served, why):
    node: Dict[str, Any] = {"type": "attribute", "datatype": "uint16", "unit": "mm"}
    if served is not None:
        node["default"] = served
    tree = {"Vehicle": {"type": "branch", "children": {"Chassis": {"type": "branch", "children": {"Wheelbase": node}}}}}
    vehicle = {"name": "sigsim-design-car", "wheelbase_mm": SYN_L_MM}
    if why:
        with pytest.raises(stack.StackError, match=why):
            stack.served_wheelbase(tree, SYN_L_MM, vehicle, None)
        return
    got = stack.served_wheelbase(tree, SYN_L_MM, vehicle, None)
    assert got["served"] is (served is not None) and got["l_mm"] == SYN_L_MM
    assert got.get("value_mm") == served and (got.get("note") == stack.WHEELBASE_NOTE) is (served is None)
    # a catalogue without the node serves nothing too (the bridge reads NOT_FOUND as not served)
    assert stack.served_wheelbase({"Vehicle": {"type": "branch", "children": {}}}, SYN_L_MM, vehicle, None)["served"] is False


def test_the_wheelbase_note_is_the_bridges():
    stack.bridge_core()             # the sources module imports the core by name
    sys.path.insert(0, str(stack.BRIDGE_DIR))
    try:
        import bridge_sources as src_mod
    finally:
        sys.path.remove(str(stack.BRIDGE_DIR))
    assert stack.WHEELBASE_NOTE == src_mod.WHEELBASE_NOTE


def test_the_vehicle_layer_is_recorded_and_binds_nothing_but_its_own_hash(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, layer_default=SYN_L_MM)
    ctx, man = _prepare(rig, "a")
    want = hashlib.sha256((rig.gen / LAYER).read_bytes()).hexdigest()
    assert man["catalogue"]["vehicle_layer_sha256"] == "sha256:" + want
    assert {r["path"]: r for r in ctx.rows}["Vehicle.Chassis.Wheelbase"]["ingress"] == "catalogue:" + LAYER
    # inputs other than the DBC and the overlay may change (a new generate.py, a profile file): prepare still binds
    m = json.loads((rig.gen / "manifest.json").read_text(encoding="utf-8"))
    m["inputs"].update({"generate.py": "11" * 32, "profiles.toml": "22" * 32})
    (rig.gen / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    _prepare(rig, "b")
    # the overlay is part of the binding
    rig.overlay.write_text("# another overlay\n", encoding="utf-8")
    with pytest.raises(stack.StackError, match="was not generated from these inputs"):
        _prepare(rig, "c")


def test_a_vehicle_layer_that_is_not_its_manifests_is_refused(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, layer_default=SYN_L_MM)
    (rig.gen / LAYER).write_text("Vehicle.Chassis.Wheelbase:\n  default: 2650\n", encoding="utf-8")
    with pytest.raises(stack.StackError, match="vehicle layer vehicle-sigsim.vspec hashes to"):
        _prepare(rig, "a")


def test_without_a_vehicle_layer_the_wheelbase_row_says_the_value_is_vss_60s_default(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    ctx, man = _prepare(rig, "a")
    assert man["catalogue"]["vehicle_layer_sha256"] is None
    assert {r["path"]: r for r in ctx.rows}["Vehicle.Chassis.Wheelbase"]["ingress"] == "catalogue:vss-6.0-default"


def test_a_broker_runs_table_gives_the_monitor_leaves_to_the_bridge_and_checks_c3(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True, layer_default=SYN_L_MM)
    ctx, man = _prepare(rig, "a", bridge="broker")
    by = {r["path"]: r for r in ctx.rows}
    writes = stack.bridge_writes(ctx.contract)
    assert len(writes) == len(stack.bridge_core().WRITEBACK_LEAVES) and all(p.startswith("Vehicle.DualVm.Monitor.VssClaim.") for p in writes)
    assert all(by[p]["writer"] == attr.BRIDGE and by[p]["cloud"] == "no" for p in writes)
    assert all(by[p]["writer"] == attr.BRIDGE for p in stack.MONITOR_DISPLAY)      # the app's display leaves are the bridge's now
    checks = {c[0]: c for c in man["scenario_checks"]}
    assert checks["C3"][1] and checks["C2"][1] and checks["C5"][1], checks
    # without a bridge there is no C3 and the display leaves are unowned
    (tmp_path / "n").mkdir()
    rig2 = _prepare_rig(tmp_path / "n", monkeypatch)
    ctx2, man2 = _prepare(rig2, "a")
    assert "C3" not in {c[0] for c in man2["scenario_checks"]}
    assert all({r["path"]: r for r in ctx2.rows}[p]["writer"] == "none" for p in stack.MONITOR_DISPLAY)


def test_the_age_clock_of_each_bridge_mode_is_the_bridges_own_source_clock():
    """AGE_CLOCK (the header's time_sync.age_clock) and the clocks the bridge's sources age on are one fact."""
    bs = stack.bridge_core()        # loads the core; the sources module imports it by name
    sys.path.insert(0, str(stack.BRIDGE_DIR))
    try:
        import bridge_sources as src_mod
    finally:
        sys.path.remove(str(stack.BRIDGE_DIR))
    named = {"broker": src_mod.BrokerSource.clock, "can": src_mod.CanSource.clock, "replay": src_mod.ReplaySource.clock}
    as_header = {m: "realtime" if c == "CLOCK_REALTIME" else "monotonic" if c.startswith("CLOCK_MONOTONIC") else c for m, c in named.items()}
    assert as_header == stack.AGE_CLOCK and set(stack.AGE_CLOCK) == set(bs.MODES)
    assert stack.age_clock("none") is None and stack.age_clock("broker") == "realtime"
    with pytest.raises(stack.StackError):
        stack.age_clock("carrier-pigeon")


# --- --images loaded: inspected, never pulled or built (SDV Phase 3 WP1) -----------------------------
# Context.prepare on the rig with images="loaded", against a fake docker that serves `image inspect` from a table of
# images.json's real pins with synthetic inspect records (linux/arm64; the upstream ones with their pinned revision label
# and repo digest; the bridge with this rig's generation's labels) and logs every call. Its `pull` would put a missing
# image back, so a path that fell back to pulling would pass prepare: the refusals below are the loaded path's own.
REVISION = "org.opencontainers.image.revision"


def _loaded_infos(contract_sha: str, dbc_sha: str) -> Dict[str, Dict[str, Any]]:
    infos: Dict[str, Dict[str, Any]] = {}
    for name, u in IMAGES["upstream"].items():
        ref = stack.upstream_ref(IMAGES, name)
        infos[ref] = {"Id": u["index_digest"], "Architecture": "arm64", "Os": "linux", "Config": {"Labels": {REVISION: u["revision"]}},
                      "RepoTags": [ref], "RepoDigests": [ref]}
    for spec in IMAGES["local"].values():
        pin = spec["arm64"]
        infos[pin["id"]] = {"Id": pin["id"], "Architecture": "arm64", "Os": "linux", "Config": {"Labels": {}}, "RepoTags": [pin["tag"]]}
    pin = IMAGES["bridge"]["arm64"]
    infos[pin["id"]] = {"Id": pin["id"], "Architecture": "arm64", "Os": "linux", "RepoTags": [pin["tag"]],
                        "Config": {"Labels": {"sdv.kind4.catalog_digest": SYN_DIGEST, "sdv.kind4.contract_sha256": contract_sha,
                                              "sdv.kind4.dbc_sha256": dbc_sha}}}
    return infos


@pytest.fixture
def loaded_rig(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True, layer_default=SYN_L_MM)
    infos = _loaded_infos(hashlib.sha256(BRIDGE_CONTRACT_PY.encode()).hexdigest(), hashlib.sha256(TINY_DBC).hexdigest())
    good = json.loads(json.dumps(infos))
    calls: List[List[str]] = []

    def fake_docker(*args, check=True, timeout=120):
        calls.append(list(args))
        rc, out, err = 0, "", ""
        if args[:2] == ("image", "inspect"):
            info = infos.get(args[-1])
            if info is None:
                rc, err = 1, "Error response from daemon: No such image: %s" % args[-1]
            else:
                out = json.dumps([info])
        elif args[:1] == ("pull",):
            infos[args[-1]] = good[args[-1]]                  # a pull would bring the image back
        elif args[:1] in (("version",), ("info",)):
            out = "29.6.2\n"
        else:
            rc, err = 1, "the loaded path never runs docker %s" % args[0]
        if check and rc:
            raise stack.StackError("docker %s failed (%d): %s" % (" ".join(args[:3]), rc, err))
        return subprocess.CompletedProcess(args, rc, out, err)

    def never(*_a, **_kw):
        raise AssertionError("the loaded path pulled or built")

    monkeypatch.setattr(stack, "docker", fake_docker)
    monkeypatch.setattr(stack, "pull_upstream", never)
    monkeypatch.setattr(stack, "build_local", never)
    monkeypatch.setattr(stack, "build_native_monitor", lambda out: {"class": "platform", "form": "native", "sha256": "0" * 64})
    monkeypatch.setenv(stack.BRIDGE_IMAGE_ENV, IMAGES["bridge"]["arm64"]["id"])
    return types.SimpleNamespace(rig=rig, infos=infos, calls=calls)


def _prepare_loaded(lr, name, images="loaded", pull=True, build=True):
    ctx = stack.Context(lr.rig.runs / name, None, "broker")
    return ctx, ctx.prepare(pull=pull, build=build, bridge_parts=True, images=images)


def _pulled_or_built(calls):
    return [c for c in calls if c[:1] in (["pull"], ["build"], ["buildx"], ["load"])]


def test_the_loaded_path_takes_the_pinned_set_and_never_pulls_or_builds(loaded_rig):
    ctx, man = _prepare_loaded(loaded_rig, "a")
    comp = ctx.components
    for name, u in IMAGES["upstream"].items():
        assert comp[name]["image_id"] == u["index_digest"] and comp[name]["revision"] == u["revision"] and comp[name]["arch"] == "arm64"
        assert comp[name]["ref"] == stack.upstream_ref(IMAGES, name) and comp[name]["pull"]["via"] == "upstream"
    for name, spec in IMAGES["local"].items():
        assert comp[name]["image_id"] == spec["arm64"]["id"] and comp[name]["tag"] == spec["arm64"]["tag"]
        assert comp[name]["pull"]["via"] == "loaded" and comp[name]["config_digest"] == spec["arm64"]["config_digest"]
    assert comp[attr.APP]["app_version"] == IMAGES["local"][attr.APP]["app_version"] and "source" in comp[attr.RECORDER]
    assert comp[stack.WITNESS]["image_id"] == IMAGES["local"][attr.RECORDER]["arm64"]["id"]
    assert comp[attr.BRIDGE]["image_id"] == IMAGES["bridge"]["arm64"]["id"] and comp[attr.BRIDGE]["pull"]["via"] == "loaded"
    assert man["docker"]["images"] == "loaded" and "never pulled or built" in man["docker"]["images_note"]
    assert "sdv/stack/bundle.py" in man["stack_files"]
    assert not _pulled_or_built(loaded_rig.calls)
    assert {tuple(c[:2]) for c in loaded_rig.calls} <= {("image", "inspect"), ("version", "-f"), ("info", "-f")}


def _change(lr, ref, **kw):
    lr.infos[ref] = dict(lr.infos[ref], **kw)


UP = "kuksa-can-provider"


@pytest.mark.parametrize("which, change, why", [
    ("upstream", None, "is not in the image store"),
    ("upstream", {"Id": "sha256:" + "4" * 64}, "image ID sha256:%s, not the pinned index digest" % ("4" * 64)),
    ("upstream", {"Architecture": "amd64"}, "linux/amd64, not linux/arm64"),
    ("upstream", {"Config": {"Labels": {REVISION: "5" * 40}}}, "revision label '%s', pinned" % ("5" * 40)),
    ("upstream", {"RepoDigests": []}, "is not among the image's repo digests"),
    ("app", None, "is not in the image store"),
    ("app", {"Id": "sha256:" + "6" * 64}, "image ID sha256:%s, pinned" % ("6" * 64)),
    ("recorder", {"Architecture": "amd64"}, "linux/amd64, not linux/arm64"),
    ("bridge", None, "No such image"),
    ("bridge", {"Architecture": "amd64"}, "linux/amd64, not linux/arm64"),
])
def test_the_loaded_path_refuses_each_check_and_never_pulls(loaded_rig, which, change, why):
    ref = {"upstream": stack.upstream_ref(IMAGES, UP), "app": IMAGES["local"][attr.APP]["arm64"]["id"],
           "recorder": IMAGES["local"][attr.RECORDER]["arm64"]["id"], "bridge": IMAGES["bridge"]["arm64"]["id"]}[which]
    if change is None:
        del loaded_rig.infos[ref]
    else:
        _change(loaded_rig, ref, **change)
    with pytest.raises(stack.StackError, match=re.escape(why)):
        _prepare_loaded(loaded_rig, "a")
    assert not _pulled_or_built(loaded_rig.calls)


def test_in_loaded_mode_the_bridge_must_be_its_arm64_pin(loaded_rig, monkeypatch):
    other = "sha256:" + "ef" * 32
    loaded_rig.infos[other] = dict(loaded_rig.infos[IMAGES["bridge"]["arm64"]["id"]], Id=other)    # the same labels: today's check passes
    monkeypatch.setenv(stack.BRIDGE_IMAGE_ENV, other)
    with pytest.raises(stack.StackError, match="the bridge's arm64 pin %s" % IMAGES["bridge"]["arm64"]["id"]):
        _prepare_loaded(loaded_rig, "a", pull=False, build=False)
    ctx, _man = _prepare_loaded(loaded_rig, "b", images="build", pull=False, build=False)      # build mode takes any labelled image
    assert ctx.components[attr.BRIDGE]["image_id"] == other


def test_build_mode_is_todays_path_and_an_unknown_mode_is_refused_before_anything_is_written(loaded_rig, monkeypatch):
    got = []
    monkeypatch.setattr(stack, "pull_upstream", lambda images: got.append("pull") or {})
    monkeypatch.setattr(stack, "build_local", lambda images: got.append("build") or {attr.RECORDER: {"image_id": "sha256:" + "cd" * 32}})
    _ctx, man = _prepare_loaded(loaded_rig, "a", images="build")
    assert got == ["pull", "build"] and man["docker"]["images"] == "build"
    assert not [c for c in loaded_rig.calls if c[:2] == ["image", "inspect"] and c[-1] != IMAGES["bridge"]["arm64"]["id"]]
    with pytest.raises(stack.StackError, match="--images 'pulled'"):
        _prepare_loaded(loaded_rig, "b", images="pulled")
    assert not (loaded_rig.rig.runs / "b").exists()


@pytest.mark.parametrize("cmd", ["prepare", "replay", "exit-test", "up", "loadcheck", "ageprobe", "wheelbaseprobe"])
def test_main_passes_the_images_mode_to_prepare(tmp_path, monkeypatch, cmd):
    seen = []

    class Stop(Exception):
        pass

    class FakeContext:
        def __init__(self, run_dir, seed, bridge):
            self.run_dir = run_dir

        def prepare(self, images="build"):
            seen.append(images)
            raise Stop()

    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "Context", FakeContext)
    extra = ["--feed", "vcan"] if cmd in ("replay", "up") else []
    for args in ([cmd, "--images", "loaded"], [cmd]):
        with pytest.raises(Stop):
            stack.main(args + extra + ["--name", "n%d" % len(seen)])
    assert seen == ["loaded", "build"]
    with pytest.raises(SystemExit):
        stack.main([cmd, "--images", "pulled"])


# --- SDV_HOST_ROLE and guest mode (SDV Phase 3 WP2) --------------------------------------------------
GUEST = "192.0.2.10"         # a documentation address (RFC 5737), never a real one


def test_sdv_host_role_reaches_the_manifest_the_header_and_the_run_id_and_another_value_is_refused(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    monkeypatch.delenv(stack.HOST_ROLE_ENV, raising=False)
    ctx, man = _prepare(rig, "a")
    h = ctx.run_header("dumpfile-1", "dumpfile")
    assert man["host_role"] == h["host_role"] == "pc" and h["run_id"].startswith("aT-pc-vss-")
    monkeypatch.setenv("SDV_HOST_ROLE", "a1-metal")
    ctx, man = _prepare(rig, "b")
    h = ctx.run_header("dumpfile-1", "dumpfile")
    assert man["host_role"] == h["host_role"] == "a1-metal" and h["run_id"].startswith("bT-a1-metal-vss-") and ctx.check_header(h)[1]
    monkeypatch.setenv("SDV_HOST_ROLE", "c7g-metal")
    ctx, man = _prepare(rig, "d")
    h = ctx.run_header("dumpfile-1", "dumpfile")
    assert man["host_role"] == h["host_role"] == "c7g-metal" and h["run_id"].startswith("dT-c7g-metal-vss-") and ctx.check_header(h)[1]
    assert stack.HOST_ROLE_ENV == "SDV_HOST_ROLE" and stack.HOST_ROLES == ("pc", "a1-metal", "c7g-metal", "orin")
    for bad in ("cloud", "", "PC", "a1.metal", "orin ", "c7g.metal", "c7g", "C7G-METAL"):
        monkeypatch.setenv("SDV_HOST_ROLE", bad)
        with pytest.raises(stack.StackError, match="SDV_HOST_ROLE"):
            _prepare(rig, "c")
        assert not (rig.runs / "c").exists()


def _guest_files(tmp_path):
    console = tmp_path / "serial.log"
    console.write_bytes(b"")
    image = tmp_path / "ifs-stand-in.bin"
    image.write_bytes(b"a stand-in image")
    return console, image


def test_prepare_in_guest_mode_builds_no_native_monitor_and_records_the_guests_component(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    console, image = _guest_files(tmp_path)

    def never(*_a, **_kw):
        raise AssertionError("guest mode built the native monitor")
    monkeypatch.setattr(stack, "build_native_monitor", never)
    monkeypatch.setattr(stack, "bridge_image", lambda contract, dbc, pin=None: {"class": "platform", "form": "container", "image_id": IMG})
    ctx = stack.Context(rig.runs / "g", None, "replay", monitor="guest", guest_host=GUEST, guest_console=console, guest_image=image)
    man = ctx.prepare(pull=False, build=False, bridge_parts=True)
    comp = man["components"][stack.VSS_MONITOR_GUEST]
    assert stack.VSS_MONITOR not in man["components"] and stack.monitor_component(ctx) is ctx.components[stack.VSS_MONITOR_GUEST]
    assert comp["form"] == "guest" and comp["image"] == image.name and comp["sha256"] == hashlib.sha256(b"a stand-in image").hexdigest()
    assert (comp["host"], comp["port"], comp["run_as"]) == (GUEST, 7160, "7160 svc 500")
    assert str(tmp_path) not in json.dumps(comp), "the image's file name, never its path"
    assert man["bridge"]["monitor"] == "guest" and "QNX guest" in man["bridge"]["note"] and "no timing" in man["bridge"]["note"]
    assert stack.monitor_host(ctx) == GUEST and stack.allowances(ctx) == []
    # native, on the same rig: the native monitor is built and taken, and the bridge's host is the loopback
    built: List[Path] = []
    monkeypatch.setattr(stack, "build_native_monitor", lambda out: built.append(out) or {"form": "native", "sha256": "0" * 64})
    ctx = stack.Context(rig.runs / "n", None, "replay")
    man = ctx.prepare(pull=False, build=False, bridge_parts=True)
    assert built == [rig.runs / "n" / "bin" / stack.MONITOR_BIN] and stack.VSS_MONITOR_GUEST not in man["components"]
    assert stack.monitor_component(ctx)["form"] == "native" and stack.monitor_host(ctx) == "127.0.0.1"
    assert man["bridge"]["monitor"] == "native" and man["bridge"]["note"] == stack.BRIDGE_NOTES["replay"]


@pytest.mark.parametrize("kw, why", [
    (dict(guest_host="127.0.0.1"), "loopback"),
    (dict(guest_host="127.9.9.9"), "loopback"),
    (dict(guest_host="0.0.0.0"), "loopback"),
    (dict(guest_host="localhost"), "not an IPv4 address"),
    (dict(guest_host="::1"), "not an IPv4 address"),
    (dict(guest_host=None), "not an IPv4 address"),
    (dict(guest_console=None), "no guest console"),
    (dict(guest_image="missing"), "no guest image"),
    (dict(bridge="none"), "needs a bridge mode"),
    (dict(monitor="native"), "--monitor guest"),
    (dict(monitor="qemu"), "--monitor 'qemu'"),
])
def test_a_guest_context_is_refused_before_anything_is_written(tmp_path, monkeypatch, kw, why):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    console, image = _guest_files(tmp_path)
    args: Dict[str, Any] = dict(monitor="guest", guest_host=GUEST, guest_console=console, guest_image=image)
    args.update(kw)
    if args.get("guest_image") == "missing":
        args["guest_image"] = tmp_path / "missing.bin"
    bridge = args.pop("bridge", "replay")
    with pytest.raises(stack.StackError, match=re.escape(why)):
        stack.Context(rig.runs / "g", None, bridge, **args)
    assert not (rig.runs / "g").exists()


def test_a_guest_host_that_is_this_hosts_own_address_is_refused_off_the_pc_and_recorded_on_it(tmp_path, monkeypatch):
    """Guest mode judges over br0: on a1-metal or orin a --guest-host that is one of this host's own addresses would have
    the run judged by whatever listens here (a native monitor), so it is refused before anything is written. On the PC the
    stand-in guest is this host by design: accepted, and the component records whether the host is local (unknown when the
    addresses cannot be read)."""
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    console, image = _guest_files(tmp_path)

    def never(*_a, **_kw):
        raise AssertionError("guest mode built the native monitor")
    monkeypatch.setattr(stack, "build_native_monitor", never)
    monkeypatch.setattr(stack, "bridge_image", lambda contract, dbc, pin=None: {"class": "platform", "form": "container", "image_id": IMG})
    monkeypatch.setattr(stack, "local_ipv4", lambda: ["192.0.2.1", GUEST], raising=False)
    kw: Dict[str, Any] = dict(monitor="guest", guest_host=GUEST, guest_console=console, guest_image=image)
    for role in ("a1-metal", "c7g-metal", "orin"):
        monkeypatch.setenv("SDV_HOST_ROLE", role)
        with pytest.raises(stack.StackError, match="one of this host's own addresses"):
            stack.Context(rig.runs / "g", None, "replay", **kw)
        assert not (rig.runs / "g").exists()
    seen = {}
    for name, role, local in (("p", "pc", ["192.0.2.1", GUEST]), ("a", "a1-metal", ["192.0.2.1"]), ("u", "a1-metal", None)):
        monkeypatch.setenv("SDV_HOST_ROLE", role)
        monkeypatch.setattr(stack, "local_ipv4", lambda local=local: local)
        man = stack.Context(rig.runs / name, None, "replay", **kw).prepare(pull=False, build=False, bridge_parts=True)
        seen[name] = man["components"][stack.VSS_MONITOR_GUEST]["host_local"]
    assert seen == {"p": True, "a": False, "u": None}, seen


def test_this_hosts_ipv4_addresses_are_read_from_ip_json():
    doc = [{"ifname": "lo", "addr_info": [{"family": "inet", "local": "127.0.0.1"}]},
           {"ifname": "br0", "addr_info": [{"family": "inet", "local": "192.168.100.1"}, {"family": "inet6", "local": "fe80::1"}]},
           {"ifname": "eth0", "addr_info": []}]
    assert stack.ipv4_of(json.dumps(doc)) == ["127.0.0.1", "192.168.100.1"]
    assert stack.ipv4_of("not json") is None and stack.ipv4_of("{}") is None
    if shutil.which("ip") and sys.platform.startswith("linux"):
        got = stack.local_ipv4()
        assert got is not None and "127.0.0.1" in got, got


@pytest.mark.parametrize("mode", ["native", "guest"])
def test_up_starts_the_native_monitor_in_native_mode_only_and_guest_mode_allows_no_listener(tmp_path, monkeypatch, mode):
    started: List[str] = []
    allowed: List[Any] = []
    monkeypatch.setattr(stack, "remove_stack", lambda: None)
    monkeypatch.setattr(stack, "host_listeners", lambda: {"with_owners": True, "sockets": []})
    monkeypatch.setattr(stack, "ensure_vcan", lambda: {"created": False})
    monkeypatch.setattr(stack, "start", lambda ctx, comp, feed, rd, label: started.append(comp))
    monkeypatch.setattr(stack, "wait_log", lambda *a, **kw: None)
    monkeypatch.setattr(stack, "wait_for", lambda *a, **kw: None)
    monkeypatch.setattr(stack, "start_bridge", lambda ctx, feed, rd, label, header: started.append("bridge"))
    monkeypatch.setattr(stack, "listeners_now", lambda info, feed, suffix, al=(): allowed.append(list(al)))

    def start_monitor(ctx, rd, info):
        started.append("monitor")
        ctx.monitor = types.SimpleNamespace(allowance=lambda: {"pid": 4242, "proto": "tcp", "port": 7160, "why": "the native monitor"})
    monkeypatch.setattr(stack, "start_monitor", start_monitor)
    guest = {"host": GUEST, "console": tmp_path / "serial.log", "image": tmp_path / "i.bin"} if mode == "guest" else None
    ctx = types.SimpleNamespace(bridge="broker", monitor=None, monitor_mode=mode, guest=guest)
    info = stack.up(ctx, "vcan", tmp_path / "u", "x/u", {"bridge_mode": "broker"})
    parts = [attr.DATABROKER, attr.MOCK_PROVIDER, attr.RECORDER, stack.WITNESS, attr.APP]
    if mode == "native":
        assert started == ["monitor"] + parts + ["bridge"] and allowed == [[ctx.monitor.allowance()]]
    else:
        assert started == parts + ["bridge"] and allowed == [[]] and stack.allowances(ctx) == []
        assert info["monitor"] == {"form": "guest", "host": GUEST, "port": 7160}


def test_record_close_reads_the_console_path_it_is_given(tmp_path):
    d = _close_dir(tmp_path, "monitor: claim kinds: ...\n", [_connect()])          # its monitor.log holds no rules line
    other = tmp_path / "guest-console.log"
    other.write_text("monitor: claim kinds: ...\n" + _monitor_rules_line() + "\n", encoding="utf-8")
    h = _bridge_header()
    assert stack.record_close(h, d, other)[1] and h["header_check"] == "ok"
    assert not stack.record_close(_bridge_header(), d)[1], "without a path: monitor.log, as before"
    c = stack.record_close(_bridge_header(), d, tmp_path / "absent.log")
    assert not c[1] and "no monitor console was captured" in c[2]


def test_stacks_own_replay_runs_the_native_monitor_only(tmp_path):
    ctx = types.SimpleNamespace(bridge="broker", monitor_mode="guest", run_dir=tmp_path / "runs" / "y")
    with pytest.raises(stack.StackError, match="step3.py"):
        stack.replay_once(ctx, "vcan", "vcan-1")
    assert not (tmp_path / "runs").exists()


# --- the AppState schema and the app's writes -----------------------------------------------------

TRIPWIRE = re.compile(SCHEMA["propertyNames"]["not"]["pattern"])


def test_schema_has_no_monitor_derived_field():
    props = SCHEMA["properties"]
    assert SCHEMA["additionalProperties"] is False and set(SCHEMA["required"]) == set(props)
    for name, p in props.items():
        assert not TRIPWIRE.search(name), name
        assert p["x-provenance"] in ("app-build", "updater-start", "app-runtime"), name
        assert "Monitor" not in p["x-vss-leaf"], name
    # the tripwire bites on the names a leak would use
    for leak in ("last_verdict", "monitor_state", "guest_connected", "reject_count", "claim_age"):
        assert TRIPWIRE.search(leak), leak


def test_leaf_map_equals_the_schema():
    props = SCHEMA["properties"]
    assert [p for p, _l, _t in hazard.LEAVES] == SCHEMA["required"]
    for prop, leaf, dt in hazard.LEAVES:
        m = re.fullmatch(r"AppState\.<App>\.(\w+) \((\w+), (\w+)(?:, allowed: (.*))?\)", props[prop]["x-vss-leaf"])
        assert m, prop
        assert (m.group(1), m.group(3)) == (leaf, dt), prop
        if m.group(4):
            assert [s.strip() for s in m.group(4).split(",")] == props[prop]["enum"]
    assert hazard.BRANCH == "Vehicle.DualVm.AppState.HardBrakeHazard" == attr.app_branch(hazard.APP_NAME)
    assert list(hazard.LIFECYCLE) == props["state"]["enum"] and list(hazard.ACTUATE_RESULTS) == props["actuate_result"]["enum"]


@NEEDS_GEN
def test_leaf_map_equals_the_generated_catalogue():
    cat = attr.leaf_nodes(json.loads((GEN / "vss-databroker.json").read_text(encoding="utf-8")))
    under = sorted(p for p in cat if p.startswith(hazard.BRANCH + "."))
    assert under == sorted(hazard.LEAF_PATHS)
    for prop, leaf, dt in hazard.LEAVES:
        node = cat[hazard.BRANCH + "." + leaf]
        assert (node["type"], node["datatype"]) == ("sensor", dt), leaf
        if "enum" in SCHEMA["properties"][prop]:
            assert node.get("allowed") == SCHEMA["properties"][prop]["enum"], leaf
    for p in hazard.INPUTS + hazard.MONITOR_DISPLAY + (hazard.HAZARD,):
        assert p in cat, p


def _validate(record: Dict[str, Any]) -> List[str]:
    """The flat AppState schema's check, with the keywords it uses: the twin connector's validator
    (sdv/connector/appstate.py, where this function's body moved in SDV Phase 4 WP1), so the app's records are held
    to the one the connector forwards them by."""
    return appstate.validate(SCHEMA, record)


def test_schema_example_validates_and_a_leak_does_not():
    assert _validate(SCHEMA["examples"][0]) == []
    leaked = dict(SCHEMA["examples"][0], last_verdict=1)
    assert _validate(leaked)


def _trip_inputs(dt=0.02):
    """A synthetic sequence of (path, value, t): standstill, cruise, a hard stop, standstill."""
    out = []
    t = 0.0
    v = 0.0
    phases = [(50, 0.0, 0.0), (100, 15.0, 0.0), (125, None, -6.0), (50, 0.0, 0.0)]
    for n, vset, a in phases:
        for _ in range(n):
            if vset is None:
                v = max(0.0, v + a * dt)
            else:
                v = vset
            acc = a if (vset is None and v > 0.0) else 0.0
            out.append((hazard.INPUT_V, v, t))
            out.append((hazard.INPUT_A, acc, t))
            t += dt
    return out


def _run(app, events):
    """Drive the core as app.py does: every Actuate answered ok at once."""
    acts: List[Any] = []
    for e in events:
        kind = e[0]
        if kind == "input":
            new = app.on_input(e[1], e[2], e[3])
        elif kind == "monitor":
            new = app.on_monitor(e[1], e[2], e[3])
        elif kind == "beat":
            new = app.on_heartbeat(e[1])
        elif kind == "subscribed":
            new = app.on_subscribed(e[1])
        else:
            new = app.on_stop(e[1])
        for a in new:
            acts.append(a)
            if isinstance(a, hazard.Actuate):
                acts += app.on_actuated(a.value, "ok", e[-1])
    return acts


def _events(monitor):
    ev: List[Any] = [("beat", 0.0), ("subscribed", 0.001)]
    beat = 1.0
    for path, val, t in _trip_inputs():
        while t >= beat:
            ev.append(("beat", beat))
            beat += 1.0
        ev.append(("input", path, val, t))
    ev += [("beat", beat), ("beat", beat + 1.0), ("stop", beat + 1.5)]
    # interleave the Monitor history, by time
    for m in monitor:
        ev.append(m)
    return sorted(ev, key=lambda e: e[-1])


MONITOR_HISTORIES = {
    "absent": [],
    "empty": [("monitor", hazard.MONITOR_DISPLAY[0], None, 0.5), ("monitor", hazard.MONITOR_DISPLAY[1], None, 0.5)],
    "all accept": [("monitor", hazard.MONITOR_DISPLAY[0], 0, 0.1 + i * 0.1) for i in range(60)],
    "reject, lost": [("monitor", hazard.MONITOR_DISPLAY[0], 1, 2.0), ("monitor", hazard.MONITOR_DISPLAY[1], 22, 2.0)],
    "stale": [("monitor", hazard.MONITOR_DISPLAY[0], 0, 0.01)],
}


def _effects(acts):
    """What leaves the app: its writes and actuations, and every log record except the display's."""
    out = []
    for a in acts:
        if isinstance(a, hazard.Note):
            if a.record["event"] == "monitor-display":
                continue
            out.append(("note", json.dumps(a.record, sort_keys=True)))
        else:
            out.append((type(a).__name__, repr(a)))
    return out


def test_appstate_is_independent_of_the_monitor_branch():
    """The design's test A8: identical effects under every Monitor history."""
    runs = {k: _effects(_run(hazard.App(image_id=IMG), _events(h))) for k, h in MONITOR_HISTORIES.items()}
    ref = runs["absent"]
    assert any(e[0] == "Actuate" for e in ref)
    for k, eff in runs.items():
        assert eff == ref, k


class _LeakyApp(hazard.App):
    """A seeded violation: reports degraded while the displayed verdict is a reject."""

    def on_monitor(self, path, value, t):
        if path.endswith(".Verdict"):
            self._verdict = value
        return super().on_monitor(path, value, t)

    def state(self, t):
        if getattr(self, "_verdict", None) == 1:
            return "degraded"
        return super().state(t)


class _FreshnessLeakyApp(hazard.App):
    """A seeded violation: reports degraded while no Monitor value arrived in the last second."""

    def on_monitor(self, path, value, t):
        self._seen = t
        return super().on_monitor(path, value, t)

    def state(self, t):
        if t - getattr(self, "_seen", -10.0) > 1.0 and not self.stopping:
            return "degraded"
        return super().state(t)


def test_the_independence_test_catches_a_leak():
    ok = _effects(_run(_LeakyApp(image_id=IMG), _events(MONITOR_HISTORIES["absent"])))
    leak = _effects(_run(_LeakyApp(image_id=IMG), _events(MONITOR_HISTORIES["reject, lost"])))
    assert ok != leak
    fresh = _effects(_run(_FreshnessLeakyApp(image_id=IMG), _events(MONITOR_HISTORIES["all accept"])))
    stale = _effects(_run(_FreshnessLeakyApp(image_id=IMG), _events(MONITOR_HISTORIES["stale"])))
    assert fresh != stale


def test_the_app_writes_only_allowlisted_appstate_leaves_and_actuates_only_the_hazard_light():
    acts = []
    for h in MONITOR_HISTORIES.values():
        acts += _run(hazard.App(image_id=IMG), _events(h))
    written = {p for a in acts if isinstance(a, hazard.Publish) for p, _v, _t in a.leaves}
    actuated = {a.path for a in acts if isinstance(a, hazard.Actuate)}
    assert written == set(hazard.WRITES) == set(hazard.LEAF_PATHS)
    assert written <= attr.ALLOWLIST_V1
    assert not any(p.startswith(attr.MONITOR_PREFIX) for p in written | actuated)
    assert actuated == set(hazard.ACTUATES) == {"Vehicle.Body.Lights.Hazard.IsSignaling"}
    for a in acts:
        if isinstance(a, hazard.Note) and a.record["event"] == "heartbeat":
            assert _validate(a.record["record"]) == [], a.record


def test_heartbeat_sequence_and_lifecycle():
    acts = _run(hazard.App(image_id=IMG), _events([]))
    beats = [a.record["record"] for a in acts if isinstance(a, hazard.Note) and a.record["event"] == "heartbeat"]
    assert [b["seq"] for b in beats] == list(range(1, len(beats) + 1))
    assert beats[0]["state"] == "starting" and beats[-1]["state"] == "stopping"
    assert rc.collapse(beats, ("state", "hazard_requested", "actuate_result"))[:1] == [("starting", False, "none")]
    decisions = [a.record for a in acts if isinstance(a, hazard.Note) and a.record["event"] == "decision"]
    assert [d["hazard"] for d in decisions] == [True, False]


def test_the_app_refuses_a_malformed_image_id():
    for bad in ("", "sha256:" + "A" * 64, "sha256:" + "a" * 63, "hard-brake-hazard:1.0.0", IMG + "0"):
        with pytest.raises(ValueError):
            hazard.App(image_id=bad)
    with pytest.raises(ValueError):
        hazard.App(image_id=IMG).record(0.0)          # no heartbeat yet


# --- the decision function ------------------------------------------------------------------------

def test_deceleration_signs():
    assert hazard.deceleration(15.0, -6.0) == 6.0          # braking forward
    assert hazard.deceleration(-2.0, 2.0) == 2.0           # braking in reverse
    assert hazard.deceleration(-2.0, -1.5) == -1.5         # accelerating in reverse
    assert hazard.deceleration(15.0, 2.5) == -2.5          # accelerating forward
    assert hazard.deceleration(0.0, -10.0) == 0.0          # standstill: no braking
    assert hazard.deceleration(-0.0, 10.0) == 0.0


def test_decide_at_its_edges():
    on, off = hazard.DECEL_ON_MPS2, hazard.DECEL_OFF_MPS2
    assert (on, off) == (4.0, 3.0)
    assert hazard.decide(False, on) is False                          # exactly the threshold: strict
    assert hazard.decide(False, math.nextafter(on, math.inf)) is True
    assert hazard.decide(True, off) is True                           # exactly the release: strict
    assert hazard.decide(True, math.nextafter(off, -math.inf)) is False
    assert hazard.decide(True, 3.5) is True and hazard.decide(False, 3.5) is False   # hysteresis band
    for x in (math.nan, math.inf, -math.inf):
        assert hazard.decide(False, x) is False and hazard.decide(True, x) is True


def _decide_on(v, a, t_v=0.0, t_a=0.0, now=0.0):
    app = hazard.App(image_id=IMG)
    app.on_subscribed(0.0)
    app.on_input(hazard.INPUT_V, v, t_v)
    acts = app.on_input(hazard.INPUT_A, a, max(t_a, now))
    return [x.value for x in acts if isinstance(x, hazard.Actuate)]


def test_decisions_in_both_directions_and_at_standstill():
    assert _decide_on(15.0, -4.001) == [True]
    assert _decide_on(15.0, -4.0) == []
    assert _decide_on(-1.0, 4.001) == [True]           # braking hard in reverse
    assert _decide_on(-1.0, -6.0) == []                # accelerating in reverse
    assert _decide_on(0.0, -6.0) == []                 # standing
    assert _decide_on(15.0, math.nan) == [] and _decide_on(math.inf, -6.0) == []


def test_no_decision_from_a_stale_input():
    d = hazard.INPUT_DEADLINE_S
    assert _decide_on(15.0, -6.0, t_v=0.0, now=d) == [True]                              # at the deadline: fresh
    assert _decide_on(15.0, -6.0, t_v=0.0, now=math.nextafter(d, math.inf)) == []        # beyond it: stale
    app = hazard.App(image_id=IMG)
    app.on_subscribed(0.0)
    app.on_input(hazard.INPUT_V, 15.0, 0.0)
    assert app.state(0.0) == "degraded"                # an input missing
    app.on_input(hazard.INPUT_A, 0.0, 0.0)
    assert app.state(d) == "running" and app.state(d + 0.01) == "degraded"
    app.on_input(hazard.INPUT_V, 15.0, 1.0)
    app.on_input(hazard.INPUT_A, -6.0, 1.0)
    app.on_actuated(True, "error", 1.0)
    assert app.state(1.0) == "degraded"                # the last Actuate failed
    with pytest.raises(ValueError):
        app.on_actuated(True, "none", 1.0)


# --- the attribution table ------------------------------------------------------------------------

def _synthetic():
    def node(t, dt, unit=None, **kw):
        n = {"type": t, "datatype": dt}
        if unit:
            n["unit"] = unit
        n.update(kw)
        return n
    cat = {
        "Vehicle.DualVm.Motion.LongitudinalVelocity": node("sensor", "float", "m/s"),
        "Vehicle.Acceleration.Longitudinal": node("sensor", "float", "m/s^2"),
        "Vehicle.Chassis.Axle.Row1.SteeringAngle": node("sensor", "float", "degrees"),
        "Vehicle.AngularVelocity.Yaw": node("sensor", "float", "degrees/s"),
        "Vehicle.Powertrain.Transmission.CurrentGear": node("sensor", "int8"),
        "Vehicle.Speed": node("sensor", "float", "km/h", min=0),
        "Vehicle.Body.Lights.Hazard.IsSignaling": node("actuator", "boolean"),
        "Vehicle.Chassis.Wheelbase": node("attribute", "uint16", "mm"),
        "Vehicle.DualVm.Monitor.VssClaim.Verdict": node("sensor", "uint8"),
        "Vehicle.DualVm.Monitor.VssClaim.Reason": node("sensor", "uint8"),
    }
    for _p, leaf, dt in hazard.LEAVES:
        cat[hazard.BRANCH + "." + leaf] = node("sensor", dt)
    sig = {"Vehicle.DualVm.Motion.LongitudinalVelocity": "LongVel", "Vehicle.Acceleration.Longitudinal": "LongAccel",
           "Vehicle.Chassis.Axle.Row1.SteeringAngle": "SteerAngleRow1", "Vehicle.AngularVelocity.Yaw": "YawRate",
           "Vehicle.Powertrain.Transmission.CurrentGear": "CurrentGear", "Vehicle.Speed": "LongVel"}
    mapping = {p: {"signal": s, "interval_ms": 0, "on_change": False} for p, s in sig.items()}
    mapping["Vehicle.Speed"]["transform"] = {"math": "abs(x) * 3.6"}
    dbc = {"messages": {"SliceDynamics": {"id": 0x100, "signals": {"LongVel": {"unit": "m/s"}, "LongAccel": {"unit": "m/s^2"},
                                                                   "SteerAngleRow1": {"unit": "degrees"}, "YawRate": {"unit": "degrees/s"}}},
                        "SliceGear": {"id": 0x101, "signals": {"CurrentGear": {"unit": ""}}}},
           "signal_message": {"LongVel": "SliceDynamics", "LongAccel": "SliceDynamics", "SteerAngleRow1": "SliceDynamics",
                              "YawRate": "SliceDynamics", "CurrentGear": "SliceGear"}}
    return cat, mapping, dbc


def _rows_and_checks(mock=("Vehicle.Body.Lights.Hazard.IsSignaling",), mapping_edit=None, rows_edit=None):
    cat, mapping, dbc = _synthetic()
    rows = attr.scenario_rows(cat, mapping, dbc, list(mock), attr.APP, hazard.WRITES, list(hazard.MONITOR_DISPLAY),
                              list(cat), 7)
    if rows_edit:
        rows = rows_edit(rows)
    m2 = json.loads(json.dumps(mapping))
    if mapping_edit:
        mapping_edit(m2)
    ws = {attr.CAN_PROVIDER: list(m2), attr.MOCK_PROVIDER: list(mock), attr.APP: list(hazard.WRITES)}
    return rows, {c[0]: c for c in attr.check_rows(rows, cat, m2, dbc, ws, attr.APP)}


def test_attribution_one_writer_per_signal():
    rows, checks = _rows_and_checks()
    assert all(c[1] for c in checks.values()), checks
    writers: Dict[str, List[str]] = {}
    for r in rows:
        writers.setdefault(r["path"], []).append(r["writer"])
    assert all(len(w) == 1 for w in writers.values())
    by = {r["path"]: r for r in rows}
    assert by["Vehicle.Speed"]["ingress"] == "can:0x100/LongVel abs*3.6"
    assert by["Vehicle.Speed"]["transform_units"] == {"in": "m/s", "out": "km/h"}
    assert by["Vehicle.Body.Lights.Hazard.IsSignaling"]["role"] == "actuation-provider"
    assert by["Vehicle.Chassis.Wheelbase"]["writer"] == "catalogue"
    assert all(by[p]["writer"] == "none" and by[p]["cloud"] == "no" for p in hazard.MONITOR_DISPLAY)
    assert [by[p]["kind4_slot"] for p in attr.SLOT_PATHS] == [0, 1, 2, 3, 4]


def test_attribution_checks_bite():
    # a second writer of Vehicle.Speed (the mock image's own sample behaviour animates it)
    _r, c = _rows_and_checks(mock=("Vehicle.Body.Lights.Hazard.IsSignaling", "Vehicle.Speed"))
    assert not c["C2"][1] and not c["C1"][1]
    # a duplicated row
    _r, c = _rows_and_checks(rows_edit=lambda rows: rows + [rows[0]])
    assert not c["C1"][1]
    # a transform that does not convert
    _r, c = _rows_and_checks(mapping_edit=lambda m: m["Vehicle.Speed"].update(transform={"math": "abs(x)"}))
    assert not c["C4"][1] and not c["C9"][1]
    # an AppState leaf claimed by another writer
    _r, c = _rows_and_checks(rows_edit=lambda rows: [dict(r, writer="kuksa-mock-provider") if r["path"] == hazard.LEAF_PATHS[0] else r
                                                     for r in rows])
    assert not c["C6"][1]
    # the actuator without its actuation provider
    _r, c = _rows_and_checks(rows_edit=lambda rows: [dict(r, role="provider") if r["role"] == "actuation-provider" else r for r in rows])
    assert not c["C7"][1]
    # a Monitor row said to go to the cloud
    _r, c = _rows_and_checks(rows_edit=lambda rows: [dict(r, cloud="yes") if r["path"].startswith(attr.MONITOR_PREFIX) else r
                                                     for r in rows])
    assert not c["C11"][1]
    # a Monitor row written by the app
    _r, c = _rows_and_checks(rows_edit=lambda rows: [dict(r, writer=attr.APP) if r["path"].startswith(attr.MONITOR_PREFIX) else r
                                                     for r in rows])
    assert not c["C5"][1]


def test_attribution_images_and_header():
    rows, _c = _rows_and_checks()
    ids = {attr.CAN_PROVIDER: "sha256:" + "a1" * 32, attr.MOCK_PROVIDER: "sha256:" + "b2" * 32, attr.APP: IMG}
    run_rows = attr.run_rows(rows, ids)
    assert attr.check_images(run_rows, dict(ids))[1]
    assert not attr.check_images(run_rows, dict(ids, **{attr.APP: "sha256:" + "c3" * 32}))[1]
    assert not attr.check_images(run_rows, {k: v for k, v in ids.items() if k != attr.MOCK_PROVIDER})[1]
    header = {"bridge_mode": "none", "profile_id": None, "profile_source": None, "age_max_ms": None, "demo_odd_window": None,
              "source_vehicle": {"name": "sigsim-design-car", "wheelbase_mm": SYN_L_MM}, "time_sync": {"daemon": "none", "synchronised": False},
              "run_type": "sigsim", "source_rtf": None,
              "recordings": [{"role": "candump", "sha256": "sha256:" + "d4" * 32}], "dbc_sha256": "sha256:" + "e5" * 32}
    assert attr.check_header(header, {}, SYN_AGE_MAX_MS)[1]
    assert not attr.check_header(dict(header, profile_id=1), {}, SYN_AGE_MAX_MS)[1]
    assert not attr.check_header(dict(header, time_sync={}), {}, SYN_AGE_MAX_MS)[1]
    assert attr.check_recording(header, "d4" * 32, "sha256:" + "e5" * 32)[1]
    assert not attr.check_recording(header, "f6" * 32, "sha256:" + "e5" * 32)[1]
    assert not attr.check_recording(header, "d4" * 32, "sha256:" + "f6" * 32)[1]


def test_c3_and_c5_bite_on_a_bridge_table():
    bridge_paths = ["Vehicle.DualVm.Monitor.VssClaim.Verdict", "Vehicle.DualVm.Monitor.VssClaim.Reason"]
    cat, mapping, dbc = _synthetic()
    rows = attr.scenario_rows(cat, mapping, dbc, ["Vehicle.Body.Lights.Hazard.IsSignaling"], attr.APP, hazard.WRITES,
                              list(hazard.MONITOR_DISPLAY), list(cat), 7, bridge_writes=bridge_paths)
    ws = {attr.CAN_PROVIDER: list(mapping), attr.MOCK_PROVIDER: ["Vehicle.Body.Lights.Hazard.IsSignaling"], attr.APP: list(hazard.WRITES),
          attr.BRIDGE: bridge_paths}
    ok = {c[0]: c for c in attr.check_rows(rows, cat, mapping, dbc, ws, attr.APP, bridge_mode="broker")}
    assert all(c[1] for c in ok.values()) and "C3" in ok, ok
    # a slot left without a writer in broker mode: its frames could only ever carry flag 0
    no_yaw = [dict(r, writer="none") if r["path"] == "Vehicle.AngularVelocity.Yaw" else r for r in rows]
    c = {c[0]: c for c in attr.check_rows(no_yaw, cat, mapping, dbc, dict(ws, **{attr.CAN_PROVIDER: [p for p in mapping if "Yaw" not in p]}),
                                           attr.APP, bridge_mode="broker")}
    assert not c["C3"][1] and "Vehicle.AngularVelocity.Yaw" in c["C3"][2]
    # the bridge configured to write outside Monitor.VssClaim
    c = {c[0]: c for c in attr.check_rows(rows, cat, mapping, dbc, dict(ws, **{attr.BRIDGE: bridge_paths + ["Vehicle.Speed"]}),
                                           attr.APP, bridge_mode="broker")}
    assert not c["C5"][1] and "Vehicle.Speed (configured for the bridge)" in c["C5"][2]


# --- C12b: the record-close check and its two operands ---------------------------------------------

def _monitor_rules_line(digest=SYN_DIGEST, age=SYN_AGE_MAX_MS, profiles="1 2"):
    """A `monitor: vss rules:` line in monitor.c's own format, read from the source (wire spec 12)."""
    src = (REPO / "ipc-test" / "qnx-safety-monitor" / "monitor.c").read_text(encoding="utf-8")
    m = re.search(r'printf\("(monitor: vss rules: [^"]*)\\n"', src)
    assert m is not None, "monitor.c lost its vss rules printf"
    fmt = m.group(1).replace("0x%08X", "%s")
    return fmt % (digest, "6.0", age, profiles)


def _bridge_header(**over):
    h = {"bridge_mode": "broker", "run_type": "sigsim", "profile_id": 1, "age_max_ms": SYN_AGE_MAX_MS, "source_rtf": None,
         "catalogue": {"kind4_digest": SYN_DIGEST}}
    h.update(over)
    return h


def _connect(**over):
    rec = {"event": "connect", "digest": SYN_DIGEST, "age_max_ms": SYN_AGE_MAX_MS, "profile_id": 1, "mode": "broker", "profile_source": "scenario"}
    rec.update(over)
    return rec


def test_c12b_passes_on_a_rules_line_and_a_connect_record_that_agree_with_the_header():
    console = "monitor: claim kinds: ...\n" + _monitor_rules_line() + "\nmonitor: service monitor listening on :7160\n"
    c = attr.check_close(_bridge_header(), console, [{"event": "start"}, _connect(), _connect()])
    assert c[1] and "1 vss rules line(s), 2 bridge connect record(s)" in c[2], c
    assert attr.header_check(c) == "ok"


@pytest.mark.parametrize("console, records, why", [
    (None, [_connect()], "no monitor console was captured"),
    ("monitor: claim kinds: ...\n", [_connect()], "holds no 'monitor: vss rules:' line"),
    (_monitor_rules_line(digest=SYN_OTHER_DIGEST), [_connect()], "vss rules: catalog " + SYN_OTHER_DIGEST),
    (_monitor_rules_line(age=300), [_connect()], "vss rules: age_max 300 ms"),
    (_monitor_rules_line(profiles="2"), [_connect()], "do not list the header's profile 1"),
    (_monitor_rules_line(), None, "no bridge log was captured"),
    (_monitor_rules_line(), [{"event": "start"}], "holds no connect record"),
    (_monitor_rules_line(), [_connect(digest=SYN_OTHER_DIGEST)], "bridge connect: digest '%s'" % SYN_OTHER_DIGEST),
    (_monitor_rules_line(), [_connect(), _connect(age_max_ms=300)], "bridge connect: age_max_ms 300"),
    (_monitor_rules_line(), [_connect(profile_id=2)], "bridge connect: profile_id 2"),
    (_monitor_rules_line(), [_connect(mode="replay")], "bridge connect: mode 'replay'"),
])
def test_c12b_fails_on_a_missing_or_disagreeing_operand(console, records, why):
    c = attr.check_close(_bridge_header(), console, records)
    assert not c[1] and why in c[2], c
    assert attr.header_check(c).startswith("failed C12b: ")


def test_c12b_without_a_bridge_or_a_carla_source_has_no_operand_and_a_carla_run_needs_its_rtf():
    none = attr.check_close(_bridge_header(bridge_mode="none"), None, None)
    assert none[1] and "no operand" in none[2]
    carla = _bridge_header(bridge_mode="none", run_type="carla")
    assert not attr.check_close(carla, None, None)[1]
    assert not attr.check_close(dict(carla, source_rtf={"min": 0.9, "mean": 0.95, "max": 1.2}), None, None)[1]
    assert attr.check_close(dict(carla, source_rtf={"min": 0.9, "mean": 0.95, "max": 1.0}), None, None)[1]


def test_the_bridges_connect_record_carries_what_c12b_reads():
    """The keys check_close reads are the ones the bridge core's connect log writes (spec 14.3 item 6)."""
    src = (stack.BRIDGE_DIR / "vss_claim_bridge.py").read_text(encoding="utf-8")
    body = src[src.index("    def run_items(self)"):src.index("    def _refuse_on_stamp")]
    for key in ('"digest"', '"profile_id"', '"age_max_ms"', '"mode"'):
        assert key in body, key
    assert 'self.log.write("connect", ' in src and "**self.run_items()" in src[src.index('self.log.write("connect", '):][:120]


def _close_dir(tmp_path, console, records):
    d = tmp_path / "replay"
    (d / "bridge").mkdir(parents=True)
    if console is not None:
        (d / "monitor.log").write_text(console, encoding="utf-8")
    if records is not None:
        (d / "bridge" / "bridge.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records) + '{"event": "torn', encoding="utf-8")
    return d


def test_record_close_reads_the_replays_monitor_log_and_bridge_log_and_writes_header_check(tmp_path):
    h = _bridge_header()
    c = stack.record_close(h, _close_dir(tmp_path, _monitor_rules_line() + "\n", [_connect()]))
    assert c[1] and h["header_check"] == "ok"
    h = _bridge_header()
    c = stack.record_close(h, _close_dir(tmp_path / "x", "monitor: claim kinds: ...\n", [_connect()]))
    assert not c[1] and h["header_check"].startswith("failed C12b: ") and "vss rules" in h["header_check"]
    h = _bridge_header()
    c = stack.record_close(h, _close_dir(tmp_path / "y", None, None))
    assert not c[1] and "no monitor console" in h["header_check"] and "no bridge log" in h["header_check"]
    h = _bridge_header(bridge_mode="none")
    assert stack.record_close(h, _close_dir(tmp_path / "z", None, None))[1] and h["header_check"] == "ok"


def _bridge_ctx(tmp_path):
    ids = {attr.APP: IMG, attr.RECORDER: "sha256:" + "cd" * 32, attr.BRIDGE: "sha256:" + "ef" * 32}
    return types.SimpleNamespace(images=IMAGES, image_ids=lambda: ids, in_dir=tmp_path / "in", bridge="broker",
                                 recorded=["Vehicle.Speed", hazard.HAZARD], witness_paths=sorted(WITNESS_PATHS))


def test_the_bridge_container_runs_as_its_dockerfile_says_on_the_hosts_namespace_only(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    calls: List[List[str]] = []
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: calls.append(list(a)) or subprocess.CompletedProcess(a, 0, "", ""))
    ctx = _bridge_ctx(tmp_path)
    rd = tmp_path / "r"
    with pytest.raises(stack.StackError, match="needs .*bridge-header.json"):
        stack.start(ctx, attr.BRIDGE, "vcan", rd, "test/run")
    (rd / "bridge").mkdir(parents=True)
    (rd / "scenario.lock").touch()
    (rd / "bridge-header.json").write_text("{}", encoding="utf-8")
    stack.start(ctx, attr.BRIDGE, "vcan", rd, "test/run")
    args = calls[-1]
    i = _image_index(args)
    opts, cmd = args[:i], args[i + 1:]
    assert args[i] == "sha256:" + "ef" * 32 and args[args.index("--name") + 1] == stack.BRIDGE_CONTAINER
    assert opts[opts.index("--network") + 1] == "host" and "--read-only" in opts and args[args.index("--cap-drop") + 1] == "ALL"
    assert opts[opts.index("--user") + 1] == "%d:%d" % (os.getuid(), os.getgid())
    assert "type=bind,src=%s,dst=/run/lock/sdv-scenario.lock" % (rd / "scenario.lock") in opts
    assert "%s:/out" % (rd / "bridge") in opts and "%s:/header.json:ro" % (rd / "bridge-header.json") in opts
    assert not {"-p", "--publish", "-P", "--privileged"} & set(opts) and "docker.sock" not in " ".join(args)
    assert cmd == ["run", "--host", "127.0.0.1", "--port", "7160", "--header", "/header.json", "--broker", "127.0.0.1:55555", "--out", "/out"]
    with pytest.raises(stack.StackError, match="needs --feed vcan"):
        stack.start(ctx, attr.BRIDGE, "dumpfile", rd, "test/run")


def test_broker_mode_is_refused_on_the_dumpfile_feed_before_anything_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    with pytest.raises(stack.StackError, match="needs --feed vcan"):
        stack.main(["replay", "--bridge", "broker", "--feed", "dumpfile", "--name", "x"])
    assert not (tmp_path / "runs").exists()
    ctx = types.SimpleNamespace(bridge="broker", run_dir=tmp_path / "runs" / "y")
    with pytest.raises(stack.StackError, match="needs --feed vcan"):
        stack.replay_once(ctx, "dumpfile", "dumpfile-1")
    with pytest.raises(stack.StackError, match="needs --feed vcan"):
        stack.up(ctx, "dumpfile", tmp_path / "u", "x/u", {})


# --- replay's exit status, the wheelbase record, C12a's CARLA operand, the probes' pure parts (WP8 round 2) -----

def _gated_result(feed="vcan", mode="broker", drop=(), **over):
    """One replay's result as replay_once() returns it, every gate passing; `over` replaces items, `drop` removes them."""
    r: Dict[str, Any] = {"replay": feed + "-1", "feed": feed, "bridge_mode": mode,
                         "values": {"ok": True}, "witness_values": {"ok": True}, "app_values": {"ok": True},
                         "decisions": {"ok": True}, "lights": {"mock_log": {"ok": True}},
                         "listeners": {"ok": True}, "listeners_feed": {"ok": True}, "listeners_end": {"ok": True},
                         "c12b": ["C12b", True, "checked"]}
    if feed == "vcan":
        r["vcan_capture"] = {"identical": True}
    if mode != "none":
        r["bridge"] = {"ok": True}
    r.update(over)
    for k in drop:
        del r[k]
    return r


@pytest.mark.parametrize("args, failed", [
    ({}, []),
    ({"listeners_end": {"ok": False}}, ["listeners"]),
    ({"listeners_feed": {"ok": False}}, ["listeners"]),
    ({"listeners": {"ok": False}}, ["listeners"]),
    ({"drop": ("listeners_end",)}, ["listeners"]),
    ({"vcan_capture": {"identical": False}}, ["bus_frames_identical"]),
    ({"drop": ("vcan_capture",)}, ["bus_frames_identical"]),
    ({"bridge": {"ok": False}}, ["bridge"]),
    ({"drop": ("bridge",)}, ["bridge"]),
    ({"c12b": ["C12b", False, "no bridge log was captured"]}, ["c12b"]),
    ({"witness_values": {"ok": False}}, ["values"]),
    ({"decisions": {"ok": False}}, ["decisions"]),
    ({"lights": {"mock_log": {"ok": False}}}, ["lights"]),
])
def test_replay_gates_hold_every_listener_snapshot_the_bus_and_the_bridge(args, failed):
    gates = stack.replay_gates(_gated_result(**args))
    assert sorted(k for k, v in gates.items() if not v) == failed, gates
    assert set(gates) == {"values", "decisions", "lights", "listeners", "c12b", "bus_frames_identical", "bridge"}


def test_replay_gates_without_a_bridge_on_the_dumpfile_feed_have_no_bus_or_bridge_gate():
    gates = stack.replay_gates(_gated_result(feed="dumpfile", mode="none"))
    assert gates == {"values": True, "decisions": True, "lights": True, "listeners": True, "c12b": True}
    assert not stack.replay_gates(_gated_result(feed="dumpfile", mode="none", listeners_end={"ok": False}))["listeners"]


def test_the_replay_command_exits_1_when_only_its_last_listener_snapshot_failed(tmp_path, monkeypatch):
    """`stack.py replay`'s exit status is replay_gates(): a broker replay whose third snapshot shows a listener the
    stack must not have added fails, though every other gate held."""
    class FakeContext:
        def __init__(self, run_dir, seed, bridge):
            self.run_dir, self.bridge = run_dir, bridge

        def prepare(self, images="build"):
            return {}

    got = {"r": _gated_result(listeners_end={"ok": False})}
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "Context", FakeContext)
    monkeypatch.setattr(stack, "replay_once", lambda _ctx, _feed, _rid: got["r"])
    assert stack.main(["replay", "--feed", "vcan", "--bridge", "broker", "--name", "a"]) == 1
    got["r"] = _gated_result(vcan_capture={"identical": False})
    assert stack.main(["replay", "--feed", "vcan", "--bridge", "broker", "--name", "b"]) == 1
    got["r"] = _gated_result()
    assert stack.main(["replay", "--feed", "vcan", "--bridge", "broker", "--name", "c"]) == 0


SERVED = {"path": attr.WHEELBASE, "served": True, "value_mm": SYN_L_MM, "l_mm": SYN_L_MM}
NOT_SERVED = {"path": attr.WHEELBASE, "served": False, "l_mm": SYN_L_MM, "note": stack.WHEELBASE_NOTE}


def _wb(**kw):
    return dict({"event": "wheelbase", "path": attr.WHEELBASE, "t_mono": 1}, **kw)


@pytest.mark.parametrize("predicted, logged, agrees", [
    (SERVED, [_wb(served=True, value_mm=SYN_L_MM, l_mm=SYN_L_MM)], True),
    (SERVED, [_wb(served=True, value_mm=SYN_OTHER_L_MM, l_mm=SYN_L_MM)], False),
    (SERVED, [_wb(served=False, l_mm=SYN_L_MM, note=stack.WHEELBASE_NOTE)], False),
    (NOT_SERVED, [_wb(served=False, l_mm=SYN_L_MM, note=stack.WHEELBASE_NOTE)], True),
    (NOT_SERVED, [_wb(served=True, value_mm=SYN_L_MM, l_mm=SYN_L_MM)], False),
    (SERVED, [], False),
    (SERVED, [_wb(served=True, value_mm=SYN_L_MM, l_mm=SYN_L_MM)] * 2, False),
    (None, [], None),
])
def test_the_bridges_wheelbase_record_is_compared_with_the_prediction(predicted, logged, agrees):
    assert stack.wheelbase_agrees(predicted, [{"event": "start"}] + logged)["agrees"] is agrees


def _bridge_dir(tmp_path, records):
    d = tmp_path / "replay"
    (d / "bridge").mkdir(parents=True)
    (d / "bridge" / "summary.json").write_text(json.dumps({"counters": {"packed": 1, "replied": 1}, "identity": {"holds": True},
                                                           "ticks_identity": {"holds": True}, "fatal": None}), encoding="utf-8")
    (d / "bridge" / "replies.jsonl").write_text(json.dumps({"event": "reply", "reason": 0, "src_now_ns": 5}) + "\n", encoding="utf-8")
    (d / "bridge" / "bridge.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return d


def test_a_bridge_result_whose_wheelbase_record_disagrees_with_the_prediction_is_not_ok(tmp_path):
    clock = {"player_start_realtime_ns": 1, "player_end_realtime_ns": 10}
    good = stack.bridge_result(_bridge_dir(tmp_path / "a", [_wb(served=True, value_mm=SYN_L_MM, l_mm=SYN_L_MM)]), clock, SERVED)
    assert good["ok"] and good["wheelbase"]["agrees"] is True, good
    bad = stack.bridge_result(_bridge_dir(tmp_path / "b", [_wb(served=False, l_mm=SYN_L_MM, note=stack.WHEELBASE_NOTE)]), clock, SERVED)
    assert not bad["ok"] and bad["wheelbase"]["agrees"] is False
    assert stack.bridge_result(_bridge_dir(tmp_path / "c", []), clock, None)["ok"]       # no prediction: not compared


RTF = {"min": 0.9, "mean": 0.95, "max": 1.0}


def _carla_header(**over):
    h = {"bridge_mode": "none", "profile_id": None, "profile_source": None, "age_max_ms": None, "demo_odd_window": None,
         "source_vehicle": {"name": "carla-ego", "wheelbase_mm": SYN_OTHER_L_MM},
         "time_sync": {"daemon": "none", "synchronised": False, "age_clock": None},
         "run_type": "carla", "feed": "recording", "source_rtf": dict(RTF)}
    h.update(over)
    return h


@pytest.mark.parametrize("header, operand, why", [
    (_carla_header(), dict(RTF), None),
    (_carla_header(), dict(RTF, max=0.99), "is not the scenario entry's source.rtf"),
    (_carla_header(source_rtf=None), dict(RTF), "is not the scenario entry's source.rtf"),
    (_carla_header(), None, "needs the scenario entry's source.rtf"),
    (_carla_header(run_type="carla-autoware"), dict(RTF, min=0.5), "is not the scenario entry's source.rtf"),
    (_carla_header(feed="live", source_rtf=None), None, None),               # a live feed's comes at record close (C12b)
    (_carla_header(run_type="sigsim", source_rtf=None), None, None),
    (_carla_header(run_type="sigsim"), dict(RTF), "source_rtf is only for CARLA-sourced runs"),
])
def test_c12a_takes_a_recorded_carla_feeds_rtf_from_the_scenario_entry(header, operand, why):
    c = attr.check_header(header, {}, SYN_AGE_MAX_MS, scenario_source_rtf=operand)
    assert c[1] is (why is None) and (why is None or why in c[2]), c


def test_the_context_gives_c12a_the_scenario_entrys_rtf(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    ctx, _man = _prepare(rig, "a")
    h = ctx.run_header("dumpfile-1", "dumpfile")
    assert ctx.check_header(h)[1]
    carla = dict(h, run_type="carla", source_rtf=dict(RTF))
    assert "needs the scenario entry's source.rtf" in ctx.check_header(carla)[2]        # the sigsim entry has none
    ctx.scenario["source"] = dict(ctx.scenario["source"], rtf=dict(RTF))
    assert ctx.check_header(carla)[1]


def _tree(default=SYN_L_MM):
    wb: Dict[str, Any] = {"type": "attribute", "datatype": "uint16", "unit": "mm", "description": "x"}
    if default is not None:
        wb["default"] = default
    return {"Vehicle": {"type": "branch", "children": {"Chassis": {"type": "branch", "children": {
        "Wheelbase": wb, "Track": {"type": "attribute", "datatype": "uint16", "unit": "mm", "default": 1}}}}}}


def test_the_wheelbase_probe_strips_one_default_and_reads_a_value_as_the_bridge_does():
    tree = _tree()
    bare = stack.without_default(tree, attr.WHEELBASE)
    assert stack.catalogue_default(tree, attr.WHEELBASE) == SYN_L_MM and stack.catalogue_default(bare, attr.WHEELBASE) is None
    want = attr.leaf_nodes(tree)
    want[attr.WHEELBASE] = {k: v for k, v in want[attr.WHEELBASE].items() if k != "default"}
    assert attr.leaf_nodes(bare) == want and stack.catalogue_default(tree, attr.WHEELBASE) == SYN_L_MM     # the copy only
    assert stack.probe_served({"known": True, "value": {"uint32": SYN_L_MM}}) == SYN_L_MM
    for entry in ({"known": True, "value": None}, {"known": False}, {"known": True, "value_error": "NOT_FOUND: x"}, {}):
        assert stack.probe_served(entry) is None, entry


@pytest.mark.parametrize("serves, agrees", [
    ({"staged": SYN_L_MM, "no-default": None}, True),
    ({"staged": SYN_L_MM, "no-default": 0}, False),          # a databroker that served a type default would refute it
    ({"staged": None, "no-default": None}, False),           # one that ignored the catalogue default too
])
def test_the_wheelbase_probe_says_whether_the_databroker_served_what_the_catalogue_predicts(tmp_path, monkeypatch, serves, agrees):
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "vss-databroker.json").write_text(json.dumps(_tree()), encoding="utf-8")
    seen = []

    def fake_load(_ctx, name, path, probe_paths, _out):
        seen.append((name, stack.catalogue_default(json.loads(Path(path).read_text(encoding="utf-8")), attr.WHEELBASE), list(probe_paths)))
        v = serves[name]
        return {"name": name, "loads": True, "probe": {"paths": {attr.WHEELBASE: {"known": True, "value": None if v is None else {"uint32": v}}}}}

    monkeypatch.setattr(stack, "load_catalogue", fake_load)
    ctx = types.SimpleNamespace(in_dir=in_dir, images=IMAGES, image_ids=lambda: {attr.RECORDER: IMG})
    res = stack.wheelbase_probe(ctx, tmp_path / "out")
    assert seen == [("staged", SYN_L_MM, [attr.WHEELBASE]), ("no-default", None, [attr.WHEELBASE])]
    assert res["agrees"] is agrees and json.loads((tmp_path / "out" / "wheelbase.json").read_text(encoding="utf-8")) == res


AGEPROBE_STUBS = ("grpc", "google", "google.protobuf", "google.protobuf.timestamp_pb2", "kuksa", "kuksa.val",
                  "kuksa.val.v1", "kuksa.val.v1.types_pb2", "kuksa.val.v1.val_pb2", "kuksa.val.v1.val_pb2_grpc",
                  "kuksa.val.v2", "kuksa.val.v2.types_pb2", "kuksa.val.v2.val_pb2", "kuksa.val.v2.val_pb2_grpc")


def _ageclock_probe(monkeypatch):
    """ageclock_probe.py loaded with stand-ins for grpc, protobuf and kuksa-client (only its pure parts are used)."""
    for name in AGEPROBE_STUBS:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    for name in AGEPROBE_STUBS:
        parent, _, leaf = name.rpartition(".")
        if parent:
            setattr(sys.modules[parent], leaf, sys.modules[name])
    sys.modules["google.protobuf.timestamp_pb2"].Timestamp = object
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("_ageclock_probe_under_test", str(stack.AGEPROBE_FILE))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_age_probe_classifies_a_served_timestamp_by_the_clocks_around_its_write(monkeypatch):
    p = _ageclock_probe(monkeypatch)
    before, after = {"realtime_ns": 1000, "monotonic_ns": 10}, {"realtime_ns": 2000, "monotonic_ns": 20}
    assert [p.classify(t, before, after) for t in (1000, 1500, 2000)] == ["receipt-realtime"] * 3
    assert p.classify(400, before, after, explicit=400) == "explicit"
    assert p.classify(1500, before, after, explicit=1500) == "receipt-realtime"       # inside the window wins
    assert p.classify(15, before, after) == "monotonic"
    assert p.classify(999, before, after) == "other" and p.classify(2001, before, after, explicit=400) == "other"
    assert p.classify(None, before, after) == "none"


def _readings(p, where="receipt-realtime", v1=7, v2=7, increasing=True, notifications=None):
    w = {"where": {"v1_get_ns": where, "v2_getvalue_ns": where}, "read_back": {"v1_get_ns": v1, "v2_getvalue_ns": v2}}
    ok = {"where": {"v1_get_ns": "receipt-realtime", "v2_getvalue_ns": "receipt-realtime"}, "read_back": {"v1_get_ns": 1, "v2_getvalue_ns": 1}}
    rep = {"writes": [ok] * p.REPEATS, "read_back_increasing": increasing,
           "notifications": p.REPEATS if notifications is None else notifications}
    return [ok, w], [rep, dict(rep, read_back_increasing=True, notifications=p.REPEATS)]


@pytest.mark.parametrize("kw, want", [
    ({}, {"stamped_on_receipt": True, "explicit_timestamp_served": False, "clock": "CLOCK_REALTIME",
          "repeat_refreshes": True, "repeat_notifies_v2": True, "v1_v2_agree": True}),
    ({"where": "explicit"}, {"stamped_on_receipt": False, "explicit_timestamp_served": True, "clock": "undetermined"}),
    ({"where": "monotonic"}, {"stamped_on_receipt": False, "explicit_timestamp_served": False, "clock": "undetermined"}),
    ({"where": "other"}, {"stamped_on_receipt": False, "clock": "undetermined"}),
    ({"increasing": False}, {"repeat_refreshes": False, "stamped_on_receipt": True}),
    ({"notifications": 2}, {"repeat_notifies_v2": False}),
    ({"notifications": 4}, {"repeat_notifies_v2": False}),
    ({"v2": 8}, {"v1_v2_agree": False}),
])
def test_the_age_probes_verdict_follows_its_readings(monkeypatch, kw, want):
    p = _ageclock_probe(monkeypatch)
    assert p.REPEATS == 3
    v = p.verdict(*_readings(p, **kw))
    assert {k: v[k] for k in want} == want, v


NATIVE = sys.platform.startswith("linux") and shutil.which("gcc") is not None and (GEN / "vss_contract.h").exists()


@pytest.mark.skipif(not NATIVE, reason="needs Linux, gcc and the generated contract headers (sdv-out/gen)")
def test_the_native_vss_monitor_announces_its_rules_and_its_inaddr_any_listener_is_allowed_by_pid(tmp_path):
    """The real operands: monitor.c's vss build for the host (build-monitor-native.sh into a non-default OUT),
    run as svc on a free port; its console carries the vss rules line C12b reads, with this generation's digest,
    AGE_MAX and compiled profiles; and the listener check allows its INADDR_ANY bind by its PID, not another's."""
    import socket as _socket
    out = tmp_path / "bin" / stack.MONITOR_BIN
    comp = stack.build_native_monitor(out)
    assert comp["path"] == str(out) and comp["sha256"] == stack.sha256_file(out) and out.with_name(out.name + ".source-sha256").is_file()
    assert "MONITOR_EXT_KINDS=0x10" in comp["build"] and str(Path.home() / "ladder") not in comp["path"]
    s = _socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    contract = stack.load_contract()
    mon = stack.NativeMonitor(out, tmp_path / "monitor.log", port=port)
    try:
        mon.wait_listening(20)
        rules = attr.vss_rules_lines(mon.text())
        assert rules == [{"catalog": "0x%08X" % contract.CATALOG_DIGEST, "age_max_ms": contract.AGE_MAX_MS,
                          "profiles": list(contract.COMPILED_PROFILE_IDS)}]
        header = _bridge_header(profile_id=contract.COMPILED_PROFILE_IDS[0], age_max_ms=contract.AGE_MAX_MS,
                                catalogue={"kind4_digest": "0x%08X" % contract.CATALOG_DIGEST})
        connect = _connect(digest="0x%08X" % contract.CATALOG_DIGEST, age_max_ms=contract.AGE_MAX_MS, profile_id=contract.COMPILED_PROFILE_IDS[0])
        assert attr.check_close(header, mon.text(), [connect])[1]
        now = stack.host_listeners()                                          # sudo -n ss -ltnupH, as a run takes it
        mine = [x for x in now["sockets"] if stack.local_port(x["local"]) == port and x["proto"] == "tcp"]
        if not now["with_owners"] or not mine:
            pytest.skip("no listener owners here (sudo -n ss): the PID half of this test needs them")
        assert mon.pid in stack.owner_pids(mine[0]["process"]), mine
        assert not stack.is_loopback(mine[0]["local"])                       # INADDR_ANY, as in the guest
        before = {"with_owners": True, "sockets": []}
        during = {"with_owners": True, "sockets": mine}
        assert stack.listener_verdict(before, during, None, [], [dict(mon.allowance(), port=port)])["ok"]
        assert not stack.listener_verdict(before, during, None, [mon.pid], [dict(mon.allowance(), port=port, pid=mon.pid + 1)])["ok"]
    finally:
        code = mon.stop()
    assert code == 0 and "monitor: stopped (liveness misses=" in mon.text()


def test_the_real_mock_file_mocks_only_the_hazard_light():
    assert attr.mock_paths(attr.MOCK_FILE.read_text(encoding="utf-8")) == ["Vehicle.Body.Lights.Hazard.IsSignaling"]


@NEEDS_GEN
def test_the_real_configuration_passes_every_check():
    cat = attr.leaf_nodes(json.loads((GEN / "vss-databroker.json").read_text(encoding="utf-8")))
    mapping = attr.dbc2vss_entries(json.loads((GEN / "vss-can-mapping.json").read_text(encoding="utf-8")))
    dbc = attr.parse_dbc((REPO / "sdv" / "vss" / "slice.dbc").read_text(encoding="utf-8"))
    mock = attr.mock_paths(attr.MOCK_FILE.read_text(encoding="utf-8"))
    rows = attr.scenario_rows(cat, mapping, dbc, mock, attr.APP, hazard.WRITES, list(hazard.MONITOR_DISPLAY), list(cat), 1)
    ws = {attr.CAN_PROVIDER: list(mapping), attr.MOCK_PROVIDER: mock, attr.APP: list(hazard.WRITES)}
    checks = attr.check_rows(rows, cat, mapping, dbc, ws, attr.APP)
    assert all(c[1] for c in checks), [c for c in checks if not c[1]]
    assert sorted(mapping) == sorted(list(attr.SLOT_PATHS) + ["Vehicle.Speed"])


def test_transforms():
    f = attr.transform_function({"transform": {"math": "abs(x) * 3.6"}})
    assert f(-2.0) == pytest.approx(7.2) and f(1.0) == pytest.approx(3.6)
    assert attr.canonical_transform({"transform": {"math": "abs(x) * 3.6"}}) == "abs*3.6"
    assert attr.canonical_transform({"signal": "x"}) is None
    for bad in ("__import__('os').system('true')", "x.real", "y * 2", "pow(x, 2)", "[x][0]"):
        with pytest.raises(ValueError):
            attr.transform_function({"transform": {"math": bad}})


# --- the replay checks ----------------------------------------------------------------------------

def test_align_and_compare():
    exp = [0.0, 0.0, 15.0, 15.0, 15.0, 14.88, 14.76, 14.64]
    assert rc.align(exp, exp, 0.005)["skipped"] == []
    one_missing = exp[:3] + exp[4:]
    a = rc.align(exp, one_missing, 0.005)
    assert a["ok"] and len(a["skipped"]) == 1
    wrong = exp[:5] + [14.87] + exp[6:]
    assert not rc.align(exp, wrong, 0.005)["ok"]
    gap = exp[:1] + exp[6:]
    assert not rc.align(exp, gap, 0.005)["ok"]                # five in a row missing: beyond MAX_GAP
    res = rc.compare_values({"p": exp}, {"p": 0.005}, {"p": one_missing}, allowed_misses=1)
    assert res["ok"] and not res["exact"] and res["unrecorded_total"] == 1
    assert not rc.compare_values({"p": exp}, {"p": 0.005}, {"p": one_missing}, allowed_misses=0)["ok"]
    assert rc.compare_values({"p": exp}, {"p": 0.005}, {"p": list(exp)}, allowed_misses=0)["exact"]
    assert rc.broker_misses("x lagged, missed 1 signal updates\ny lagged, missed 2 signal updates\n") == 3


def test_expected_windows_and_prediction():
    summary = {"segments": [["cruise again", 0, 100], ["hard brake", 100, 160], ["stopped", 160, 200], ["reverse", 200, 260]]}
    frames = []
    v = 15.0
    for t in range(0, 261, 20):
        a = -6.0 if 100 <= t < 160 else 0.0
        if t >= 160:
            v = 0.0
        if t >= 220:
            v = -0.5
        frames.append((t, "SliceDynamics", {"LongVel": v, "LongAccel": a}))
        if 100 <= t < 160:
            v -= 5.0
    w = rc.expected_windows(summary, frames, "LongVel", 20)
    assert w["on_window_ms"] == [80, 160] and w["off_window_ms"] == [140, 220] and w["anchor"]["t_rec_ms"] == 0
    p = rc.predict(frames, "LongVel", "LongAccel", hazard)
    assert [(x["t_rec_ms"], x["hazard"]) for x in p] == [(100, True), (160, False)]
    decisions = [{"hazard": True, "t_rec_ms": 101.0}, {"hazard": False, "t_rec_ms": 160.5}]
    assert rc.window_verdict(decisions, w)["ok"]
    assert not rc.window_verdict(decisions + [{"hazard": True, "t_rec_ms": 230.0}], w)["ok"]
    assert not rc.window_verdict([{"hazard": True, "t_rec_ms": 60.0}, {"hazard": False, "t_rec_ms": 160.0}], w)["ok"]
    with pytest.raises(ValueError):
        rc.expected_windows({"segments": []}, frames, "LongVel", 20)


def test_recorder_csv_time_and_mapping(tmp_path):
    f = tmp_path / "rec.csv"
    f.write_text("field,signal,value,delay\ncurrent,A,0,0.0\ncurrent,B,False,0.5\ntarget,B,True,0.25\ncurrent,A,1.5,0.25\n", encoding="utf-8")
    rows = rc.read_recorder_csv(f)
    assert [r["t"] for r in rows] == [0.0, 0.5, 0.75, 1.0]
    assert rc.series(rows, "B") == [(0.5, False)] and rc.series(rows, "B", "target") == [(0.75, True)]
    assert rc.anchor_time(rc.series(rows, "A")) == 1.0
    assert rc.to_rec_ms(1.25, 1.0, 1520) == pytest.approx(1770.0)
    assert rc.parse_value("7") == 7 and rc.parse_value("0.5") == 0.5 and rc.parse_value("x") == "x"


def test_broker_lags_by_subscriber_capacity():
    log = ("WARN Slow subscriber with capacity 1 lagged, missed 2 signal updates\n"
           "WARN Slow subscriber with capacity 101 lagged, missed 5 signal updates\n"
           "WARN Slow subscriber with capacity 1 lagged, missed 1 signal updates\n"
           "WARN Slow subscriber with capacity 1001 lagged, missed 7 signal updates\n")
    assert rc.broker_misses(log) == 15
    assert rc.broker_misses(log, capacity=1) == 3 and rc.broker_misses(log, capacity=1001) == 7
    assert rc.broker_misses(log, capacity=11) == 0
    assert rc.broker_lags(log) == {"1": 3, "101": 5, "1001": 7}


def _witness_log(path, values, initial=(), stop=True, tail="", stop_counts=None, extra=(), stop_record=None):
    """witness.py's log: start, subscribed, every value, then `extra` records (as the program writes a
    stream-ended before its stop), then the stop record with the counts of the values (or stop_counts,
    or stop_record, verbatim)."""
    lines = [{"event": "start"}, {"event": "subscribed"}]
    for p, vs in values.items():
        lines += [{"event": "value", "path": p, "value": v, "initial": (p, i) in initial, "t": 0.0} for i, v in enumerate(vs)]
    lines += list(extra)
    if stop_record is not None:
        lines.append(stop_record)
    elif stop:
        lines.append({"event": "stop", "counts": stop_counts if stop_counts is not None else {p: len(vs) for p, vs in values.items()}})
    path.write_text("".join(json.dumps(x) + "\n" for x in lines) + tail, encoding="utf-8")


def test_the_witness_is_compared_exactly(tmp_path):
    decoded = {"V": [0.0, 15.0, 14.88, 14.76], "G": [0, 1, 1]}
    f32 = {"V": [rc.f32(x) for x in decoded["V"]], "G": [0, 1, 1]}
    half = {"V": 0.005, "G": 0.5}
    f = tmp_path / "w.jsonl"
    _witness_log(f, f32)
    w = rc.read_witness(f)
    assert w["values"] == f32 and w["initial_values"] == 0 and [r["event"] for r in w["records"]] == ["start", "subscribed", "stop"]
    res = rc.compare_exact(decoded, w["values"], half)
    assert res["ok"] and all(p["within_half_lsb"] for p in res["paths"].values()) and res["compared_total"] == 7
    # one value missing, anywhere: no allowance
    assert not rc.compare_exact(decoded, {"V": f32["V"][:1] + f32["V"][2:], "G": f32["G"]}, half)["ok"]
    # a value within half an LSB but not the decoded value rounded to float32
    near = {"V": f32["V"][:2] + [f32["V"][2] + 0.001] + f32["V"][3:], "G": f32["G"]}
    r2 = rc.compare_exact(decoded, near, half)
    assert not r2["ok"] and r2["paths"]["V"]["first_mismatch"]["index"] == 2 and r2["paths"]["V"]["within_half_lsb"]
    # a path nobody expected fails the comparison, whatever else matches; one expected but never witnessed too
    unexpected = rc.compare_exact(decoded, dict(f32, X=[1.0]))
    assert unexpected["unexpected_paths"] == ["X"] and not unexpected["ok"]
    assert all(p["ok"] for p in unexpected["paths"].values())           # every expected path is exact: only X fails it
    assert not rc.compare_exact(decoded, {"V": f32["V"]})["ok"]
    # nothing compared is not agreement: no expected path, or expected paths with no value at all
    for expected, got in (({"p": []}, {}), ({}, {}), ({"p": []}, {"p": []}), ({"p": [], "q": []}, {})):
        nothing = rc.compare_exact(expected, got)
        assert not nothing["ok"] and nothing["compared_total"] == 0, (expected, got)
    assert rc.compare_exact({"p": [1.0]}, {"p": [1.0]})["ok"]
    # a line being written: refused when strict, the whole lines before it otherwise
    _witness_log(f, f32, stop=False, tail='{"event": "val')
    with pytest.raises(ValueError):
        rc.read_witness(f)
    assert rc.read_witness(f, strict=False)["values"] == f32
    _witness_log(f, f32, initial={("G", 0)})
    assert rc.read_witness(f)["initial_values"] == 1


WV_DECODED = {"V": [0.0, 15.0, 14.88, 14.76], "G": [0, 1, 1]}
WV_HALF = {"V": 0.005, "G": 0.5}
WV_GATES = {"values_exact", "log_read", "no_initial_values", "no_stream_errors", "stop_counts_equal_log", "no_broker_lag"}
# what the databroker logs for other subscribers: the recorder and the mock provider (capacity 1), the app (101)
OTHERS_LAG = ("WARN Slow subscriber with capacity 1 lagged, missed 2 signal updates\n"
              "WARN Slow subscriber with capacity 101 lagged, missed 3 signal updates\n")


def _wv_verdict(tmp_path, values=None, read_error=None, broker_log="", **log_kw):
    """The witness verdict on a witness log written to a file and read back, as analyse() does: by
    default every decoded value, exactly as the databroker stores it, and a stop record that agrees."""
    f32 = {p: [rc.f32(float(x)) if p == "V" else x for x in vs] for p, vs in WV_DECODED.items()} if values is None else values
    f = tmp_path / "witness.jsonl"
    _witness_log(f, f32, **log_kw)
    wit, err = rc.load_witness(f)
    assert err is None
    return rc.witness_verdict(WV_DECODED, WV_HALF, wit, read_error, broker_log)


def test_a_witness_that_saw_everything_passes_every_gate(tmp_path):
    v = _wv_verdict(tmp_path, broker_log=OTHERS_LAG)            # the lags of other subscribers are not the witness's
    assert v["ok"] and set(v["gates"]) == WV_GATES and all(v["gates"].values())
    assert v["broker_lagged"] == 0 and v["initial_values"] == 0 and v["errors"] == [] and v["read_error"] is None
    assert v["stop_counts_equal_log"] and v["compared_total"] == 7


@pytest.mark.parametrize("gate, kw", [
    # each case is complete and right in every other respect, so the named gate is the only one to fail
    ("no_initial_values", dict(initial={("G", 0)})),                                        # a value from the initial notification
    ("stop_counts_equal_log", dict(stop=False)),                                            # no stop record: the witness did not stop cleanly
    ("stop_counts_equal_log", dict(stop_counts={"V": 3, "G": 3})),                          # a stop record short of the log's values
    ("stop_counts_equal_log", dict(stop_counts={"V": 4, "G": 3, "X": 1})),                  # ... or counting a path the log lacks
    ("stop_counts_equal_log", dict(stop_counts={"V": 4})),                                  # ... or omitting a path the log has
    ("stop_counts_equal_log", dict(stop_record={"event": "stop", "signal": 15})),            # a stop record with no counts: judged, not a KeyError
    ("stop_counts_equal_log", dict(stop_record={"event": "stop", "counts": [4, 3]})),        # ... or with counts that are not per path
    ("no_broker_lag", dict(broker_log=OTHERS_LAG + "WARN Slow subscriber with capacity 1001 lagged, missed 1 signal updates\n")),
    ("log_read", dict(read_error="OSError: the log vanished")),                             # (read_error comes from load_witness)
    ("no_stream_errors", dict(extra=[{"event": "stream-ended"}])),
    ("no_stream_errors", dict(extra=[{"event": "subscription-error", "code": "UNAVAILABLE"}])),
    ("values_exact", dict(values={"V": [0.0, 15.0, 14.76], "G": [0, 1, 1]})),               # a value the witness never got (its stop agrees)
])
def test_each_witness_gate_fails_on_its_own(tmp_path, gate, kw):
    v = _wv_verdict(tmp_path, **kw)
    assert [g for g, ok in v["gates"].items() if not ok] == [gate]
    assert not v["ok"]


def test_the_witness_verdict_reports_what_each_gate_saw(tmp_path):
    v = _wv_verdict(tmp_path, initial={("V", 0), ("G", 0)}, extra=[{"event": "stream-ended"}],
                    broker_log="WARN Slow subscriber with capacity 1001 lagged, missed 4 signal updates\n", read_error="OSError: x")
    assert v["initial_values"] == 2 and [e["event"] for e in v["errors"]] == ["stream-ended"]
    assert v["broker_lagged"] == 4 and v["read_error"] == "OSError: x"
    assert v["gates"] == {"values_exact": True, "log_read": False, "no_initial_values": False, "no_stream_errors": False,
                          "stop_counts_equal_log": True, "no_broker_lag": False} and not v["ok"]


def test_an_unreadable_or_torn_witness_log_is_judged_not_raised(tmp_path):
    wit, err = rc.load_witness(tmp_path / "gone.jsonl")
    assert wit == {"values": {}, "initial_values": 0, "records": []} and err is not None and err.startswith("FileNotFoundError")
    f = tmp_path / "torn.jsonl"
    _witness_log(f, {"V": [1.0, 2.0]}, stop=False, tail='{"event": "val')
    torn, err2 = rc.load_witness(f)
    assert torn == wit and err2 is not None and err2.startswith("JSONDecodeError")
    for w, e in ((wit, err), (torn, err2)):
        v = rc.witness_verdict(WV_DECODED, WV_HALF, w, e, "")
        assert not v["ok"] and v["read_error"] == e and not v["gates"]["log_read"]
    _witness_log(f, {"V": [1.0, 2.0]})
    whole, err3 = rc.load_witness(f)
    assert err3 is None and whole["values"] == {"V": [1.0, 2.0]}


# --- the hazard light: what the behaviour key and the window gate read ----------------------------
# The recorder is a kuksa.val.v1 subscriber with a buffer of one: the databroker drops an update when
# it lags. A replay's key and its window gate must therefore read only the app's own log and the mock
# provider's own log; the recorder's hazard rows are reported. The functions are tested on their own
# (rc.behaviour_key, rc.mock_gate, rc.recorder_light_view) and, where a mistake would be in how
# analyse() and verdict() wire them, on a synthetic replay directory as the stack leaves one.

W0 = 1_800_000_000.0         # wall clock (epoch seconds) of the synthetic trip's first frame
M0 = 5000.0                  # the app's monotonic clock at that frame
LAG1 = "WARN Slow subscriber with capacity 1 lagged, missed %d signal updates\n"
DEFAULT_MOCK = ((-2.0, False), (0.105, True), (0.165, False))      # seconds from the first frame: the initial feed, on, off
# the hazard rows of the recorder's CSV: name -> (ms in recording time, field, value)
SYN_HAZARD_ROWS = {"initial": (-2000, "current", False), "target_on": (100, "target", True), "current_on": (105, "current", True),
                   "target_off": (160, "target", False), "current_off": (165, "current", False)}


def _syn_ctx():
    frames = _trip_frames()
    values = {hazard.INPUT_V: [f[2]["LongVel"] for f in frames], hazard.INPUT_A: [f[2]["LongAccel"] for f in frames]}
    return types.SimpleNamespace(
        mapping={hazard.INPUT_V: {"signal": "LongVel"}, hazard.INPUT_A: {"signal": "LongAccel"}},
        decoded={"values": values, "half_lsb": {p: 0.005 for p in values}, "frames": frames},
        windows=rc.expected_windows({"segments": SEGMENTS}, frames, "LongVel", 20), hz=hazard, image_ids=lambda: {attr.APP: IMG})


def _syn_app_records(results=("ok", "ok")):
    """The app's JSON-lines records over the synthetic trip: the core driven as app.py drives it (every
    Actuate answered 1 ms later with the next of `results`, a heartbeat every 100 ms), each record with
    its monotonic t and the wall clock t_wall of the same instant."""
    app = hazard.App(image_id=IMG)
    answers = list(results)
    out = []

    def log(acts, t):
        for a in acts:
            if isinstance(a, hazard.Note):
                out.append(dict(a.record, t_wall=W0 + (a.record["t"] - M0)))
            elif isinstance(a, hazard.Actuate):
                log(app.on_actuated(a.value, answers.pop(0), t + 0.001), t)
    log(app.on_subscribed(M0 - 0.5), M0 - 0.5)
    log(app.on_heartbeat(M0 - 0.4), M0 - 0.4)
    for t_ms, _name, dec in _trip_frames():
        t = M0 + t_ms / 1000.0
        log(app.on_input(hazard.INPUT_V, dec["LongVel"], t), t)
        log(app.on_input(hazard.INPUT_A, dec["LongAccel"], t), t)
        if t_ms % 100 == 0:
            log(app.on_heartbeat(t), t)
    log(app.on_stop(M0 + 0.3), M0 + 0.3)
    return out


# the mock provider's start-up lines, as its container log shows them (every line an INFO record)
MOCK_PREAMBLE = ["INFO:mock_service:Initialization ...",
                 "INFO:mock_service:Connecting to Data Broker [127.0.0.1:55555]",
                 "INFO:kuksa_client.grpc:No Root CA present, it will not be possible to use a secure connection!",
                 "INFO:kuksa_client.grpc:Establishing insecure channel",
                 "INFO:mock_service:Databroker connected!",
                 "INFO:mock_service:Datapoint added/removed",
                 "INFO:mock_service:Subscribing to 1 mocked datapoints..."]
RUNNING = "INFO:mock_service:Running behavior for Vehicle.Body.Lights.Hazard.IsSignaling"
FEEDING = "INFO:mock_service:Feeding 'Vehicle.Body.Lights.Hazard.IsSignaling' with value %s"
# what a failed write leaves after its 'Feeding' line: the shape of a traceback, as logging.exception writes it
MOCK_ERROR = ["ERROR:mock_service:the write failed",
              "Traceback (most recent call last):",
              '  File "mock.py", line 1, in main_loop',
              "    write()",
              "kuksa_client.grpc.VSSClientError: the write failed"]
MOCK_THREAD_ERROR = ["Exception in thread databroker-connector:",
                     "Traceback (most recent call last):",
                     '  File "mock.py", line 1, in run',
                     "kuksa_client.grpc.VSSClientError: the write failed"]


def _stamped(lines, dt=-3.0, at=0):
    """`docker logs -t` text: dockerd's receive stamp, one space, each line. The stamps are seconds from the
    synthetic trip's first frame: line `at` is at dt, the others 0.1 ms apart around it."""
    out = []
    for i, body in enumerate(lines):
        t = datetime.datetime.fromtimestamp(W0 + dt + 0.0001 * (i - at), tz=datetime.timezone.utc)
        out.append("%s %s\n" % (t.strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z", body))
    return "".join(out)


def _syn_mock_log(writes, after=None):
    """The mock provider's container log as `docker logs -t` gives it: its start-up lines, then a 'Feeding' line per
    write (each after the first following a 'Running behavior' line). `after` maps a write's index to the raw lines
    (no stamp) that follow its 'Feeding' line: what a write that failed would leave."""
    out = [_stamped(MOCK_PREAMBLE)]
    for i, (dt, value) in enumerate(writes):
        out.append(_stamped(([RUNNING] if i else []) + [FEEDING % value] + list((after or {}).get(i, ())), dt, at=1 if i else 0))
    return "".join(out)


def _syn_recorder_csv(drop_hazard=(), drop_can=()):
    """The recorder's CSV of the synthetic trip, as rows in time order with their delays; a capacity-1
    v1 subscriber loses updates, so `drop_hazard` (names of SYN_HAZARD_ROWS) and `drop_can` (the
    velocity's rows, by recording time in ms) are left out."""
    events = []
    for t_ms, _name, dec in _trip_frames():
        if t_ms not in drop_can:
            events.append((t_ms, 0, "current", hazard.INPUT_V, dec["LongVel"]))
        events.append((t_ms, 1, "current", hazard.INPUT_A, dec["LongAccel"]))
    for name, (t_ms, fld, value) in SYN_HAZARD_ROWS.items():
        if name not in drop_hazard:
            events.append((t_ms, 2, fld, hazard.HAZARD, value))
    events.sort(key=lambda e: e[:2])
    lines = ["field,signal,value,delay"]
    prev = events[0][0]
    for t_ms, _order, fld, signal, value in events:
        lines.append("%s,%s,%s,%s" % (fld, signal, value, (t_ms - prev) / 1000.0))
        prev = t_ms
    return "\n".join(lines) + "\n"


def _syn_replay(tmp_path, name, drop_hazard=(), drop_can=(), lags=0, mock=DEFAULT_MOCK, results=("ok", "ok"), drop_actuation=None,
                broker_log=None, witness="whole", mock_after=None, mock_text=None, records_edit=None):
    """A replay directory with the five files analyse() reads. The app's records come from the core,
    the mock's log from `mock` (seconds from the first frame, value; `mock_after` adds lines after a
    write's, see _syn_mock_log; or is `mock_text`, verbatim), the recorder's CSV from the rows
    that survived, the databroker's log says `lags` updates missed by capacity-1 subscribers (or is
    `broker_log`, verbatim), the witness's log is whole, `torn` (a line cut off) or `missing`.
    `records_edit` maps the app's records to the ones its log holds (a record altered after the app wrote it)."""
    d = tmp_path / name
    d.mkdir()
    ctx_values = _syn_ctx().decoded["values"]
    records = _syn_app_records(results)
    if drop_actuation is not None:          # the app's log lacks one of its actuations
        records = [r for r in records if not (r.get("event") == "actuate" and r["value"] is drop_actuation)]
    if records_edit is not None:
        records = records_edit(records)
    (d / "hard-brake-hazard.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    (d / ("%s.log" % attr.MOCK_PROVIDER)).write_text(_syn_mock_log(mock, mock_after) if mock_text is None else mock_text, encoding="utf-8")
    (d / "vss-recorder.csv").write_text(_syn_recorder_csv(drop_hazard, drop_can), encoding="utf-8")
    (d / ("%s.log" % attr.DATABROKER)).write_text(broker_log if broker_log is not None else (LAG1 % lags if lags else ""), encoding="utf-8")
    if witness != "missing":
        _witness_log(d / stack.WITNESS_LOG, ctx_values, tail='{"event": "val' if witness == "torn" else "")
    return d


def _syn_result(ctx, replay_dir):
    """analyse()'s result for one replay, completed as replay_once completes it (the feed and the
    three listener snapshots, all clean)."""
    r = stack.analyse(ctx, replay_dir)
    ok = {"ok": True}
    r.update(feed="dumpfile", listeners=ok, listeners_feed=ok, listeners_end=ok)
    return r


def _key(result):
    return json.dumps(result["behaviour_key"], sort_keys=True)


def test_the_synthetic_replay_passes_every_check_so_the_variants_below_are_not_vacuous(tmp_path):
    ctx = _syn_ctx()
    rs = [_syn_result(ctx, _syn_replay(tmp_path, "full-%d" % i)) for i in range(3)]
    v = stack.verdict(ctx, rs, "dumpfile", 3)
    assert v["ok"] and v["same_behaviour"] and v["lights_in_window"] and v["recorder_values_exact_replays"] == 3
    assert v["recorder_lights_consistent_replays"] == 3
    r = rs[0]
    assert r["values"]["exact"] and r["witness_values"]["ok"] and r["app_values"]["ok"] and r["decisions"]["ok"]
    assert r["lights"]["mock_log"]["ok"] and r["lights"]["recorder"]["in_window"] and r["lights"]["recorder"]["consistent"]["exact"]
    assert r["lights"]["mock_log"]["clean"] and r["lights"]["mock_log"]["offending_lines"] == [] and r["lights"]["mock_log"]["offending_total"] == 0
    assert [m["value"] for m in r["lights"]["mock_log"]["writes"]] == [False, True, False]
    assert [round(m["t_rec_ms"]) for m in r["lights"]["mock_log"]["writes"][1:]] == [105, 165]
    # analyse()'s key, field by field. The synthetic trip brakes at 15.0 m/s with an acceleration of -6.0 m/s^2: the app
    # decides hazard on at the acceleration (the trigger), and off when the velocity reaches 0.0; each decision carries the
    # v and a it was made on. The app's state sequence is (state, hazard_requested, actuate_result) as it changed.
    assert r["behaviour_key"]["decisions"] == [[True, hazard.INPUT_A, 15.0, -6.0], [False, hazard.INPUT_V, 0.0, -6.0]]
    assert r["behaviour_key"]["targets"] == [[True, "ok"], [False, "ok"]] and r["behaviour_key"]["lights"] == [False, True, False]
    assert r["behaviour_key"]["appstate"] == [["degraded", False, "none"], ["running", False, "none"], ["running", True, "ok"],
                                              ["running", False, "ok"], ["stopping", False, "ok"]]
    assert r["appstate_sequence"] == r["behaviour_key"]["appstate"] and r["app_decisions_reproduced_offline"] is True


@pytest.mark.parametrize("drop, lags", [
    (("target_off",), 1),                    # the case seen once: the recorder lost the last target
    (("target_on",), 1),
    (("current_on",), 1),                    # a lost current value: the old window gate needed exactly one on and one off
    (("current_off",), 1),
    (("target_on", "current_on", "target_off", "current_off"), 4),
    (("target_off",), 0),                     # ... and with no lag logged at all
])
def test_a_recorder_that_dropped_updates_changes_neither_the_key_nor_the_verdict(tmp_path, drop, lags):
    ctx = _syn_ctx()
    full = [_syn_result(ctx, _syn_replay(tmp_path, "full-%d" % i)) for i in range(2)]
    lossy = _syn_result(ctx, _syn_replay(tmp_path, "lossy", drop_hazard=drop, lags=lags))
    assert [r["lights"]["recorder"]["targets"] for r in full] == [[True, False]] * 2
    assert lossy["lights"]["recorder"]["targets"] == [v for n, v in (("target_on", True), ("target_off", False)) if n not in drop]
    assert _key(lossy) == _key(full[0]) == _key(full[1])
    v = stack.verdict(ctx, full + [lossy], "dumpfile", 3)
    assert v["same_behaviour"] and v["lights_in_window"] and v["ok"]
    # what the recorder lost is reported, bounded by the lags the databroker logged
    view = lossy["lights"]["recorder"]
    assert view["consistent"]["unrecorded_total"] == len(drop) and view["consistent"]["ok"] == (lags >= len(drop))
    assert v["recorder_lights_consistent_replays"] == 2 + (lags >= len(drop))


def test_the_recorders_hazard_view_is_reported_with_the_lags_its_can_rows_do_not_use(tmp_path):
    """The recorder lost a velocity row and the last target, and the databroker logged one lag: the lag is
    spoken for by the CAN-fed row, so the hazard rows are not consistent (reported); with two lags they are.
    The recorder's CAN rows are judged as before (aligned within the lags), and neither moves the verdict's key."""
    ctx = _syn_ctx()
    one = _syn_result(ctx, _syn_replay(tmp_path, "one", drop_hazard=("target_off",), drop_can=(40,), lags=1))
    two = _syn_result(ctx, _syn_replay(tmp_path, "two", drop_hazard=("target_off",), drop_can=(40,), lags=2))
    assert one["values"]["unrecorded_total"] == two["values"]["unrecorded_total"] == 1 and one["values"]["ok"] and two["values"]["ok"]
    assert not one["lights"]["recorder"]["consistent"]["ok"] and two["lights"]["recorder"]["consistent"]["ok"]
    assert _key(one) == _key(two)


def test_analyse_gives_the_witness_verdict_its_log_its_read_error_and_the_witness_capacity(tmp_path):
    """analyse()'s call into rc.witness_verdict, which the gates' own tests cannot see: a lag the
    databroker logged for a capacity-1001 subscriber, a torn witness log and a missing one each fail
    the replay's witness and so the verdict; the lags of other subscribers do not."""
    ctx = _syn_ctx()
    others = _syn_result(ctx, _syn_replay(tmp_path, "others", broker_log=OTHERS_LAG))
    assert others["witness_values"]["ok"] and others["witness_values"]["broker_lagged"] == 0
    lagged = _syn_result(ctx, _syn_replay(
        tmp_path, "lagged", broker_log=OTHERS_LAG + "WARN Slow subscriber with capacity 1001 lagged, missed 1 signal updates\n"))
    assert [g for g, ok in lagged["witness_values"]["gates"].items() if not ok] == ["no_broker_lag"]
    assert lagged["witness_values"]["broker_lagged"] == 1
    torn = _syn_result(ctx, _syn_replay(tmp_path, "torn", witness="torn"))
    assert not torn["witness_values"]["gates"]["log_read"] and torn["witness_values"]["read_error"].startswith("JSONDecodeError")
    missing = _syn_result(ctx, _syn_replay(tmp_path, "missing", witness="missing"))
    assert not missing["witness_values"]["gates"]["log_read"] and missing["witness_values"]["read_error"].startswith("FileNotFoundError")
    for bad in (lagged, torn, missing):
        v = stack.verdict(ctx, [others, others, bad], "dumpfile", 3)
        assert not v["witness_values_exact"] and not v["ok"]


def test_a_differing_actuation_or_mock_write_changes_the_key_or_fails_the_gate(tmp_path):
    ctx = _syn_ctx()
    base = [_syn_result(ctx, _syn_replay(tmp_path, "base-%d" % i)) for i in range(2)]

    def verdict_with(variant):
        return stack.verdict(ctx, base + [variant], "dumpfile", 3)
    # the app's own actuations: an outcome that differs, an actuation missing from its log
    errored = _syn_result(ctx, _syn_replay(tmp_path, "errored", results=("ok", "error")))
    assert _key(errored) != _key(base[0]) and errored["behaviour_key"]["targets"] == [[True, "ok"], [False, "error"]]
    assert not verdict_with(errored)["same_behaviour"]
    no_off = _syn_result(ctx, _syn_replay(tmp_path, "no-off", drop_actuation=False))
    assert no_off["behaviour_key"]["targets"] == [[True, "ok"]] and no_off["behaviour_key"]["decisions"] == base[0]["behaviour_key"]["decisions"]
    assert not verdict_with(no_off)["same_behaviour"]
    # the mock provider's own writes: an extra pair, none at all
    extra = _syn_result(ctx, _syn_replay(tmp_path, "extra", mock=DEFAULT_MOCK + ((0.18, True), (0.2, False))))
    assert extra["behaviour_key"]["lights"] == [False, True, False, True, False] and not extra["lights"]["mock_log"]["ok"]
    assert not verdict_with(extra)["same_behaviour"] and not verdict_with(extra)["lights_in_window"]
    silent = _syn_result(ctx, _syn_replay(tmp_path, "silent", mock=()))
    assert silent["behaviour_key"]["lights"] == [] and not silent["lights"]["mock_log"]["ok"]
    assert not verdict_with(silent)["same_behaviour"] and not verdict_with(silent)["ok"]
    # ... the right writes outside their windows (the key does not read time; the gate does)
    late = _syn_result(ctx, _syn_replay(tmp_path, "late", mock=((-2.0, False), (0.105, True), (0.4, False))))
    early = _syn_result(ctx, _syn_replay(tmp_path, "early", mock=((-2.0, False), (0.03, True), (0.165, False))))
    for r in (late, early):
        assert _key(r) == _key(base[0]) and not r["lights"]["mock_log"]["ok"]
        v = verdict_with(r)
        assert v["same_behaviour"] and not v["lights_in_window"] and not v["ok"]
    # ... and in the wrong order, each inside its own window (a False, then a True)
    swapped = _syn_result(ctx, _syn_replay(tmp_path, "swapped", mock=((-2.0, False), (0.145, False), (0.15, True))))
    assert not swapped["lights"]["mock_log"]["ok"] and not verdict_with(swapped)["lights_in_window"]


@pytest.mark.parametrize("after", [
    {2: MOCK_ERROR},                                  # the third write (False, the light stays on) failed: a traceback after the third 'Feeding' line
    {0: MOCK_THREAD_ERROR},                           # the initial write failed: 'Exception in thread databroker-connector'
    {1: MOCK_ERROR},                                  # the second write failed (in the real mock that also ends its loop and so the third line)
    {2: ["WARNING:mock_service:Feeding failed"]},     # a warning alone
    {2: ["ERROR:mock_service:the write failed"]},     # an error line alone
], ids=["traceback-after-the-third-write", "thread-exception-after-the-initial-write", "traceback-after-the-second-write",
        "a-warning-after-the-third-write", "an-error-line-after-the-third-write"])
def test_a_mock_log_with_a_line_above_info_fails_the_gate_and_the_verdict_though_its_three_writes_are_right(tmp_path, after):
    """analyse()'s wiring of rc.mock_log_clean: the mock's three 'Feeding' lines are right and inside their
    windows, and the log holds the lines a failed write would leave. The behaviour key does not read the
    level of a line, so the gate alone has to fail: lights.mock_log.ok, `lights_in_window` and `ok`."""
    ctx = _syn_ctx()
    base = [_syn_result(ctx, _syn_replay(tmp_path, "base-%d" % i)) for i in range(2)]
    bad = _syn_result(ctx, _syn_replay(tmp_path, "bad", mock_after=after))
    m = bad["lights"]["mock_log"]
    assert [w["value"] for w in m["writes"]] == [False, True, False] and rc.mock_gate(m["writes"], ctx.windows, True)
    extra = [line for i in sorted(after) for line in after[i]]
    assert m["clean"] is False and m["ok"] is False
    assert _bodies(m["offending_lines"]) == extra and m["offending_total"] == len(extra)
    assert _key(bad) == _key(base[0])
    v = stack.verdict(ctx, base + [bad], "dumpfile", 3)
    assert v["same_behaviour"] and v["witness_values_exact"] and not v["lights_in_window"] and not v["ok"]
    assert [k for k, x in v.items() if isinstance(x, bool) and not x] == ["lights_in_window", "ok"]


def test_the_lines_a_mock_log_names_are_bounded_and_counted(tmp_path):
    ctx = _syn_ctx()
    flood = ["ERROR:mock_service:%d" % i for i in range(200)]
    m = _syn_result(ctx, _syn_replay(tmp_path, "flood", mock_after={2: flood}))["lights"]["mock_log"]
    assert not m["ok"] and m["offending_total"] == 200
    assert _bodies(m["offending_lines"]) == flood[:stack.MOCK_OFFENDING_KEPT] and len(m["offending_lines"]) == stack.MOCK_OFFENDING_KEPT


def test_a_mock_log_that_is_whole_but_for_one_stampless_line_fails_the_gate(tmp_path):
    ctx = _syn_ctx()
    text = _syn_mock_log(DEFAULT_MOCK) + "INFO:mock_service:a line dockerd did not stamp\n"
    m = _syn_result(ctx, _syn_replay(tmp_path, "stampless", mock_text=text))["lights"]["mock_log"]
    assert [w["value"] for w in m["writes"]] == [False, True, False] and not m["ok"]
    assert m["offending_lines"] == ["INFO:mock_service:a line dockerd did not stamp"]


def test_a_logged_decision_the_apps_inputs_do_not_give_is_reported_and_changes_the_key(tmp_path):
    """analyse() recomputes the app's decisions from the inputs it logged (app_decisions_reproduced_offline,
    reported) and keys the replay by the decisions it logged. A decision record altered after the app wrote
    it (its v, its a, its trigger) is not reproduced and is in the key; an input altered so the app would
    not have decided it is not reproduced either, and the key still holds what the app logged."""
    ctx = _syn_ctx()
    base = _syn_result(ctx, _syn_replay(tmp_path, "base"))

    def alter_decision(field, value):
        def edit(records):
            hit = [r for r in records if r.get("event") == "decision" and r["hazard"]]
            assert len(hit) == 1 and hit[0][field] != value
            return [dict(r, **{field: value}) if r is hit[0] else r for r in records]
        return edit
    for field, value in (("v", 14.0), ("a", -5.0), ("trigger", hazard.INPUT_V)):
        r = _syn_result(ctx, _syn_replay(tmp_path, "alt-" + field, records_edit=alter_decision(field, value)))
        assert r["app_decisions_reproduced_offline"] is False, field
        assert _key(r) != _key(base) and r["behaviour_key"]["decisions"][0][{"v": 2, "a": 3, "trigger": 1}[field]] == value, field

    def brake_not_felt(records):
        braking = [r for r in records if r.get("event") == "input" and r.get("path") == hazard.INPUT_A and r["value"] == -6.0]
        assert braking
        return [dict(r, value=-1.0) if r in braking else r for r in records]
    inputs = _syn_result(ctx, _syn_replay(tmp_path, "alt-input", records_edit=brake_not_felt))
    assert inputs["app_decisions_reproduced_offline"] is False and _key(inputs) == _key(base)


def test_a_verdict_over_fewer_replays_than_were_asked_for_is_not_ok_on_that_alone(tmp_path):
    ctx = _syn_ctx()
    rs = [_syn_result(ctx, _syn_replay(tmp_path, "r-%d" % i)) for i in range(3)]
    assert stack.verdict(ctx, rs, "dumpfile", 3)["ok"]
    two = stack.verdict(ctx, rs[:2], "dumpfile", 3)
    assert two["replays"] == 2 and not two["same_behaviour"] and not two["ok"]
    assert [k for k, x in two.items() if isinstance(x, bool) and not x] == ["same_behaviour", "ok"]
    assert not stack.verdict(ctx, [], "dumpfile", 3)["ok"]


def _w(t, value):
    return {"value": value, "t_rec_ms": t}


def test_the_behaviour_key_is_what_the_app_and_the_mock_did_and_nothing_of_time():
    dec = [(True, "A", 15.0, -6.0), (False, "V", 0.0, -6.0)]
    act = [{"value": True, "result": "ok", "t_rec_ms": 100.0}, {"value": False, "result": "ok", "t_rec_ms": 160.0}]
    mock = [_w(-2000.0, False), _w(105.0, True), _w(165.0, False)]
    beats = [("starting", False, "none"), ("running", True, "ok")]
    key = rc.behaviour_key(dec, act, mock, beats)
    assert key == {"decisions": [[True, "A", 15.0, -6.0], [False, "V", 0.0, -6.0]], "targets": [[True, "ok"], [False, "ok"]],
                   "lights": [False, True, False], "appstate": [["starting", False, "none"], ["running", True, "ok"]]}
    # no time in it
    later = [dict(a, t_rec_ms=a["t_rec_ms"] + 7.0) for a in act]
    assert rc.behaviour_key(dec, later, [_w(m["t_rec_ms"] + 3.0, m["value"]) for m in mock], beats) == key
    # each part of it counts
    assert rc.behaviour_key(dec[:1], act, mock, beats) != key
    assert rc.behaviour_key(dec, act[:1], mock, beats) != key
    assert rc.behaviour_key(dec, [dict(act[0], value=False)] + act[1:], mock, beats) != key
    assert rc.behaviour_key(dec, [dict(act[0], result="error")] + act[1:], mock, beats) != key
    assert rc.behaviour_key(dec, act, mock[:2], beats) != key
    assert rc.behaviour_key(dec, act, mock[:2] + [_w(165.0, True)], beats) != key
    assert rc.behaviour_key(dec, act, mock, beats[:1]) != key


W_GATE = {"on_window_ms": [80, 160], "off_window_ms": [140, 220]}
GOOD_WRITES = [_w(-2000.0, False), _w(105.0, True), _w(165.0, False)]


def _gate(writes, clean=True):
    return rc.mock_gate(writes, W_GATE, clean)


def test_the_mock_gate_wants_three_writes_in_order_inside_their_windows():
    assert _gate(GOOD_WRITES)
    assert not _gate([]) and not _gate([_w(-2000.0, False)])
    assert not _gate([_w(105.0, True), _w(165.0, False)])                                     # no initial value
    assert not _gate([_w(-2000.0, False), _w(105.0, True), _w(165.0, False), _w(170.0, False)])    # a fourth write
    assert not _gate([_w(-2000.0, True), _w(105.0, True), _w(165.0, False)])                  # starts on
    assert not _gate([_w(-2000.0, False), _w(145.0, False), _w(150.0, True)])                 # off before on, each in a window
    assert not _gate([_w(-2000.0, False), _w(105.0, True), _w(105.0, True)])
    assert not _gate([_w(-2000.0, False), _w(70.0, True), _w(165.0, False)])                  # on before its window
    assert not _gate([_w(-2000.0, False), _w(160.0, True), _w(165.0, False)])                 # the window is half open
    assert not _gate([_w(-2000.0, False), _w(105.0, True), _w(230.0, False)])                 # off after its window
    assert not _gate([_w(-2000.0, False), _w(105.0, True), _w(None, False)])                  # no time to judge


def test_the_mock_gate_wants_the_log_clean_whatever_the_writes():
    """The mock logs a write just before it makes it, so three right 'Feeding' lines in their windows are
    not enough: a log that is not clean (rc.mock_log_clean) fails the gate on the same writes."""
    assert _gate(GOOD_WRITES, True) is True
    assert _gate(GOOD_WRITES, False) is False
    assert _gate([], False) is False


# --- the mock provider's log: every line an INFO record -------------------------------------------
# The mock logs 'Feeding ... with value X' just before it calls the databroker (the pinned image's
# mockservice.py, as the r4 critic read it) and its client raises an exception its own handler does not
# catch, so a write that failed leaves the line and then an error: a traceback after the third line, or
# 'Exception in thread' after the initial one. The gate reads the 'Feeding' lines, so it also reads
# the level of every line of the log.

FEEDS = [FEEDING % False, RUNNING, FEEDING % True, RUNNING, FEEDING % False]


def _bodies(offending):
    """The lines rc.mock_log_offending names, without dockerd's stamp (the stamp, one space, the line)."""
    return [x.split(" ", 1)[1] for x in offending]


def test_a_real_shaped_mock_log_is_clean():
    text = _stamped(MOCK_PREAMBLE + FEEDS)
    assert rc.mock_log_clean(text) is True and rc.mock_log_offending(text) == []
    assert rc.mock_log_clean(text.rstrip("\n"))                  # with or without the last newline
    assert rc.mock_log_clean(text.replace("\n", "\r\n"))         # written through a text file on Windows
    assert rc.mock_log_clean("2026-10-01T00:47:47Z INFO:mock_service:no fraction of a second, as dockerd may print a stamp")
    assert rc.mock_log_clean(_stamped(["INFO:mock_service:no Traceback, ERROR or WARNING here: the level is what counts"]))
    assert rc.mock_log_clean("")                                 # nothing to object to; the gate still wants its three writes
    assert not _gate([], rc.mock_log_clean(""))


def test_a_traceback_after_the_third_feeding_line_is_not_clean():
    text = _stamped(MOCK_PREAMBLE + FEEDS + MOCK_ERROR)
    assert rc.mock_log_clean(text) is False
    assert _bodies(rc.mock_log_offending(text)) == MOCK_ERROR       # every line of it, in order, and none of the INFO lines
    assert rc.mock_log_clean(_stamped(MOCK_PREAMBLE + FEEDS))        # ... the same log without it is clean


def test_an_exception_in_a_thread_after_the_initial_feeding_line_is_not_clean():
    text = _stamped(MOCK_PREAMBLE + FEEDS[:1] + MOCK_THREAD_ERROR)
    assert rc.mock_log_clean(text) is False and _bodies(rc.mock_log_offending(text)) == MOCK_THREAD_ERROR


def test_an_error_line_is_not_clean():
    text = _stamped(MOCK_PREAMBLE + FEEDS + ["ERROR:mock_service:the write failed"])
    assert rc.mock_log_clean(text) is False and _bodies(rc.mock_log_offending(text)) == ["ERROR:mock_service:the write failed"]


def test_a_warning_line_is_not_clean():
    text = _stamped(MOCK_PREAMBLE + FEEDS[:1] + ["WARNING:mock_service:Feeding failed"] + FEEDS[1:])
    assert rc.mock_log_clean(text) is False and _bodies(rc.mock_log_offending(text)) == ["WARNING:mock_service:Feeding failed"]


@pytest.mark.parametrize("line", [
    "CRITICAL:mock_service:x", "DEBUG:mock_service:x", "Traceback (most recent call last):", "Exception in thread databroker-connector:",
    '  File "mock.py", line 1, in main_loop', "kuksa_client.grpc.VSSClientError: the write failed",
    "", " INFO:mock_service:x", "INFO", "INFO:", "INFO::x", "info:mock_service:x", "XINFO:mock_service:x", "WARN:mock_service:x",
])
def test_only_an_info_record_is_clean(line):
    """A line that is not 'INFO:<logger>:<message>' fails the log, anywhere in it."""
    text = _stamped(MOCK_PREAMBLE[:3] + [line] + MOCK_PREAMBLE[3:])
    assert rc.mock_log_clean(text) is False and _bodies(rc.mock_log_offending(text)) == [line]


def test_a_line_without_dockerds_stamp_is_not_clean():
    lines = ["INFO:mock_service:Databroker connected!", "INFO:mock_service:no stamp on this one"]
    stamped_first = _stamped(lines[:1]) + lines[1] + "\n"
    assert rc.mock_log_clean(stamped_first) is False and rc.mock_log_offending(stamped_first) == [lines[1]]
    for bare in ("2026-10-01T00:47:47.633297870Z", "2026-10-01T00:47:47.633297870Z  INFO:mock_service:two spaces",
                 "2026-10-01 00:47:47.633297870 INFO:mock_service:no T and no Z", "   "):
        assert rc.mock_log_clean(_stamped(lines[:1]) + bare + "\n") is False, bare


def _csv_rows(current, target=(), t0=1.0):
    """Recorder rows of the hazard light: its currents, then its targets, each at 0.1 s steps."""
    rows = [{"field": "current", "signal": rc.V_PATH, "value": 15.0, "t": t0}]
    rows += [{"field": "current", "signal": rc.HAZARD, "value": v, "t": t0 + 0.1 * i} for i, v in enumerate(current)]
    rows += [{"field": "target", "signal": rc.HAZARD, "value": v, "t": t0 + 0.05 + 0.1 * i} for i, v in enumerate(target)]
    return rows


def test_the_recorders_light_view_is_a_lag_bounded_subsequence_of_the_mock_and_the_app():
    w = {"on_window_ms": [80, 160], "off_window_ms": [140, 220]}
    mock = [_w(-2000.0, False), _w(105.0, True), _w(165.0, False)]
    act = [{"value": True, "result": "ok"}, {"value": False, "result": "ok"}]

    def view(current, target, allowed):
        return rc.recorder_light_view(_csv_rows(current, target), 1.0, mock, act, allowed, w, 0)
    full = view([False, True, False], [True, False], 0)
    assert full["consistent"]["ok"] and full["consistent"]["exact"] and full["targets"] == [True, False]
    assert [c["value"] for c in full["changes"]] == [False, True, False]
    one = view([False, True, False], [True], 1)                      # the last target lost, one lag logged
    assert one["consistent"]["ok"] and not one["consistent"]["exact"] and one["consistent"]["unrecorded_total"] == 1
    assert not view([False, True, False], [True], 0)["consistent"]["ok"]                            # nothing logged for it
    assert not view([False, False], [True], 1)["consistent"]["ok"]                                   # two lost, one logged
    assert view([False, False], [True], 2)["consistent"]["ok"]
    assert not view([False, True, True], [True, False], 3)["consistent"]["ok"]                      # not a subsequence of the mock's writes
    assert not view([False, True, False, True], [True, False], 5)["consistent"]["ok"]               # a row the mock never wrote
    assert not view([False, True, False], [False, True], 5)["consistent"]["ok"]                     # targets out of order
    assert not view([], [], 3)["consistent"]["ok"] and view([], [], 5)["consistent"]["ok"]           # a recorder that saw nothing: all five lost
    # the window check on the recorder's own rows is reported as it was, and is not the consistency
    assert full["in_window"] and not view([False, False], [True, False], 1)["in_window"]
    assert not view([False, True, False, True], [True, False], 5)["in_window"]                       # on twice
    shifted = rc.recorder_light_view(_csv_rows([True, False], [True, False]), 0.9, mock, act, 5, w, 0)      # on at 100 ms, off at 200 ms ...
    assert not shifted["in_window"] and [c["t_rec_ms"] for c in shifted["changes"]] == pytest.approx([100.0, 200.0])    # ... but it did not start off
    assert not rc.recorder_light_view(_csv_rows([False, True, False], [True, False]), None, mock, act, 0, w, 0)["in_window"]
    assert not rc.recorder_light_view(_csv_rows([False, True, False], [True, False]), 0.5, mock, act, 0, w, 0)["in_window"]   # 500 ms late


# --- the load check's probe list ------------------------------------------------------------------

ENUM_NODES = ["Vehicle.Exterior.PrecipitationType", "Vehicle.Exterior.RoadObstruction", "Vehicle.Exterior.RoadSurfaceCondition",
              "Vehicle.Exterior.RoadSurfaceContaminant", "Vehicle.Exterior.VisibilityCondition"]


def _tree_with_enum_nodes(enum_nodes):
    nodes = {p: {"type": "sensor", "datatype": "uint8", "enum": {"UNKNOWN": 0, "OTHER": 1}} for p in enum_nodes}
    nodes.update({"Vehicle.Speed": {"type": "sensor", "datatype": "float", "unit": "km/h"},
                  "Vehicle.Exterior.AirTemperature": {"type": "sensor", "datatype": "float", "unit": "celsius"},
                  "Vehicle.Cabin.Door.Row1.DriverSide.IsOpen": {"type": "sensor", "datatype": "boolean"}})
    return _nest(nodes)


def test_the_load_check_probes_every_enum_node_of_the_61_file_not_only_the_one_it_writes():
    tree = _tree_with_enum_nodes(ENUM_NODES)
    enum = stack.enum_nodes_of(tree)
    assert enum == ENUM_NODES                                       # the file's enum nodes, and no node without an enum
    argv = stack.loadcheck_probe(enum)
    assert argv[:4] == ["--write", stack.ROAD_SURFACE + "=4", "--write", stack.ROAD_SURFACE + "=200"]
    paths = argv[4:]
    assert all(p in paths for p in ENUM_NODES) and len(paths) == len(set(paths))
    assert set(stack.PROBE_PATHS) <= set(paths) and "Vehicle.Exterior.AirTemperature" not in paths
    # a file whose enum nodes lack the written one still probes it; a different set is probed as it is
    other = ["Vehicle.A.Mode", "Vehicle.B.Mode"]
    argv2 = stack.loadcheck_probe(stack.enum_nodes_of(_tree_with_enum_nodes(other)))
    assert set(argv2[4:]) == set(stack.PROBE_PATHS) | {stack.ROAD_SURFACE} | set(other)


def test_loadcheck_gives_every_catalogue_the_probe_list_built_from_the_61_files_enum_nodes(tmp_path, monkeypatch):
    """loadcheck's own wiring, with no Docker: the 6.1 file's enum nodes reach the probe of each of the
    four catalogues (load_catalogue is replaced by a recorder of its arguments)."""
    cache = tmp_path / "cache"
    (cache / "s2-check").mkdir(parents=True)
    (cache / "s2-check" / "b-mapping.json").write_text(json.dumps(_tree_with_enum_nodes(ENUM_NODES)), encoding="utf-8")
    (cache / "s2-check" / "overlay.vspec").write_text("# a synthetic overlay\n", encoding="utf-8")
    gen = tmp_path / "gen"
    gen.mkdir()
    for name in ("vss-databroker.json", "vss-can-mapping.json"):
        (gen / name).write_text(json.dumps(_nest({"Vehicle.Speed": {"type": "sensor", "datatype": "float"}})), encoding="utf-8")
    seen = []
    monkeypatch.setattr(stack, "CACHE", cache)
    monkeypatch.setattr(stack, "GEN", gen)
    monkeypatch.setattr(stack, "load_catalogue", lambda _ctx, name, _path, probe, _out: seen.append((name, list(probe))) or {"name": name})
    res = stack.loadcheck(None, tmp_path / "out")
    assert [n for n, _p in seen] == ["6.0-databroker", "6.0-mapping", "6.1-mapping", "6.1-databroker"]
    assert all(p == stack.loadcheck_probe(ENUM_NODES) for _n, p in seen)
    assert all(e in seen[0][1] for e in ENUM_NODES) and res["enum_nodes_in_6.1_file"] == ENUM_NODES and res["probe_args"] == seen[0][1]


@pytest.mark.skipif(not (stack.CACHE / "s2-check" / "b-mapping.json").exists(), reason="needs the stage-1 S2 check's 6.1 file under SDV_CACHE")
def test_the_load_check_probe_list_holds_every_enum_node_of_the_real_61_file():
    tree = json.loads((stack.CACHE / "s2-check" / "b-mapping.json").read_text(encoding="utf-8"))
    enum = stack.enum_nodes_of(tree)
    assert stack.ROAD_SURFACE in enum
    assert set(enum) <= set(stack.loadcheck_probe(enum))


# --- the app's shell: the heartbeat and the Monitor display ---------------------------------------

def _import_app(monkeypatch):
    """sdv/apps/hard-brake-hazard/app.py with stand-ins for kuksa-client, which the pure tests do not
    install (the app image does); no bytecode written."""
    mods = {n: types.ModuleType(n) for n in ("kuksa", "kuksa.val", "kuksa.val.v2", "kuksa.val.v2.val_pb2",
                                             "kuksa_client", "kuksa_client.grpc", "kuksa_client.grpc.aio")}
    mods["kuksa.val.v2.val_pb2"].SubscribeRequest = lambda **kw: types.SimpleNamespace(**kw)
    mods["kuksa.val.v2"].val_pb2 = mods["kuksa.val.v2.val_pb2"]
    mods["kuksa.val"].v2 = mods["kuksa.val.v2"]
    mods["kuksa"].val = mods["kuksa.val"]
    g = mods["kuksa_client.grpc"]

    class _Arg:
        def __init__(self, *a, **kw):
            self.a, self.kw = a, kw
    for n in ("DataEntry", "Datapoint", "EntryUpdate", "Metadata"):
        setattr(g, n, _Arg)
    g.DataType = types.SimpleNamespace(UINT8=1, UINT32=2, STRING=3, BOOLEAN=4)
    g.Field = types.SimpleNamespace(VALUE=1, ACTUATOR_TARGET=2)
    g.VSSClientError = type("VSSClientError", (Exception,), {})
    mods["kuksa_client.grpc.aio"].VSSClient = object
    g.aio = mods["kuksa_client.grpc.aio"]
    mods["kuksa_client"].grpc = g
    for n, m in mods.items():
        monkeypatch.setitem(sys.modules, n, m)
    spec = importlib.util.spec_from_file_location("_hbh_app_under_test", str(APP_DIR / "app.py"))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


class _Value:
    """A kuksa.val.v2 Value carrying one uint32 (what app._value reads)."""

    def __init__(self, v):
        self.uint32 = v

    def ListFields(self):
        return [(types.SimpleNamespace(name="uint32"), self.uint32)]


def _response(entries):
    return types.SimpleNamespace(entries={p: types.SimpleNamespace(value=_Value(v)) for p, v in entries.items()})


class _Client:
    def __init__(self, streams):
        self.client_stub_v2 = types.SimpleNamespace(Subscribe=lambda req: streams[tuple(req.signal_paths)]())
        self.sets: List[Any] = []

    async def set(self, updates, try_v2=False):
        self.sets.append((updates, try_v2))


def test_a_monitor_burst_cannot_degrade_a_heartbeat(monkeypatch):
    """The review's freshness coupling: the Monitor display must never hold up a heartbeat, and a
    heartbeat held up by an actuation in flight is judged at the time it fell due. On the old shell
    (one lock for everything, the heartbeat's time read after taking it) the burst waits behind the
    actuation and the heartbeat reads its fresh inputs as stale: degraded."""
    appmod = _import_app(monkeypatch)
    clock = [10.0]
    monkeypatch.setattr(appmod, "time", types.SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0.0))
    records: List[Dict[str, Any]] = []
    log = types.SimpleNamespace(write=records.append)
    burst = 50

    async def monitor_stream():
        for i in range(burst):
            await asyncio.sleep(0)
            yield _response({hazard.MONITOR_DISPLAY[0]: i % 2, hazard.MONITOR_DISPLAY[1]: i})
        await asyncio.Event().wait()                 # the stream stays open

    core = hazard.App(image_id=IMG)
    core.on_subscribed(10.0)
    core.on_input(hazard.INPUT_V, 15.0, 10.0)
    core.on_input(hazard.INPUT_A, 0.0, 10.0)

    def displayed():
        return sum(1 for r in records if r.get("event") == "monitor-display")

    async def scenario():
        shell = appmod.Shell(core, _Client({tuple(hazard.MONITOR_DISPLAY): monitor_stream}), log)
        # 1. an actuation in flight holds the shared lock while the burst arrives and a heartbeat falls due
        await shell.lock.acquire()
        mon = asyncio.create_task(shell.subscribe(list(hazard.MONITOR_DISPLAY), False, "on_monitor", shell.display_lock))
        beat = asyncio.create_task(shell.beat())
        for _ in range(20 * burst):
            await asyncio.sleep(0)
            if displayed() == 2 * burst:
                break
        assert displayed() == 2 * burst              # the whole burst was displayed without the shared lock
        assert not beat.done()                       # the heartbeat waits for the actuation only
        clock[0] = 10.0 + hazard.INPUT_DEADLINE_S + 2.0
        shell.lock.release()
        await beat
        # 2. the display lock itself is held (a display in progress): a heartbeat does not wait for it
        core.on_input(hazard.INPUT_V, 15.0, clock[0])
        core.on_input(hazard.INPUT_A, 0.0, clock[0])
        await shell.display_lock.acquire()
        await asyncio.wait_for(shell.beat(), timeout=5)
        shell.display_lock.release()
        mon.cancel()
        await asyncio.gather(mon, return_exceptions=True)

    asyncio.run(scenario())
    beats = [r["record"]["state"] for r in records if r.get("event") == "heartbeat"]
    assert beats == ["running", "running"]
    assert [r["t"] for r in records if r.get("event") == "heartbeat"][0] == 10.0


def test_main_hands_the_monitor_subscription_the_display_lock_and_the_inputs_the_shared_one():
    """The test above passes display_lock to subscribe() itself; this holds main()'s own wiring (the
    tasks it starts), which it cannot see: each stream's lock is the fourth argument of its
    Shell.subscribe call, found by the handler named as the third."""
    import ast
    tree = ast.parse((APP_DIR / "app.py").read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "subscribe"]
    wired = {}
    for c in calls:
        assert len(c.args) == 4 and isinstance(c.args[2], ast.Constant) and isinstance(c.args[2].value, str), ast.dump(c)
        wired[c.args[2].value] = ast.unparse(c.args[3])
    assert len(calls) == 2 and wired == {"on_input": "shell.lock", "on_monitor": "shell.display_lock"}


# --- running the whole suite in WSL without git on this worktree ----------------------------------

RIG_FILES = ("test_aws_tooling.py", "test_aws_noble.py")     # the second takes the first's fixture, by its name


def _rig_tests():
    """file::name of every test that takes the driver's rig, in the two files that have one."""
    import ast
    ids = []
    for f in RIG_FILES:
        tree = ast.parse((HERE / f).read_text(encoding="utf-8"))
        ids += ["tests/%s::%s" % (f, n.name) for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name.startswith("test_") and "rig" in [a.arg for a in n.args.args]]
    return sorted(ids)


def _twinctl_git_tests():
    """The tests of tests/test_sdv_cloud.py whose own code runs git (its _git helper): the plan allows one."""
    import ast
    text = (HERE / "test_sdv_cloud.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    return sorted(n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                  and "_git(" in ast.get_source_segment(text, n))


def test_the_wsl_argument_file_deselects_every_test_that_runs_git_on_the_repo():
    """sdv/stack/wsl-pytest.args (sdv/stack/README.md): every test whose code runs git against the
    checkout -- the `rig` tests of test_aws_tooling.py and of test_aws_noble.py run drive-metal.sh's main, whose outside_repo
    runs `git -C scripts/aws rev-parse`, and claims_lib.repo_slug_from_git runs `git remote` on the
    repo root -- and (plan Phase 4 WP6) the one test of test_sdv_cloud.py that runs git at all: the
    twin driver's branch-scan, whose command searches this checkout by default (the test gives it a
    fixture repository). One argument per line (pytest reads @file that way): no blank line, no comment."""
    lines = (STACK_DIR / "wsl-pytest.args").read_text(encoding="ascii").split("\n")
    assert lines[-1] == "" and all(lines[:-1])
    ids = [ln[len("--deselect="):] for ln in lines[:-1]]
    assert all(ln.startswith("--deselect=tests/") for ln in lines[:-1])
    want = _rig_tests() + ["tests/test_claims_lib.py::test_repo_slug_from_git_remote"]
    assert {i.split("::")[0] for i in _rig_tests()} == {"tests/" + f for f in RIG_FILES}
    want += ["tests/test_sdv_cloud.py::" + n for n in _twinctl_git_tests()]
    assert sorted(ids) == sorted(want) and len(_rig_tests()) >= 26 and len(_twinctl_git_tests()) == 1
    for i in ids:
        f, name = i.split("::")
        assert re.search(r"^def %s\(" % re.escape(name), (REPO / f).read_text(encoding="utf-8"), re.M), i


def test_the_readme_commands_say_where_the_export_runs_and_print_the_deselected_count():
    """sdv/stack/README.md: the DBC export command is cmd's (PowerShell or cmd; in Git Bash cmd //c with
    the argument in single quotes), and the two whole-run commands (WSL: everything but the git tests; Windows: those) override
    pyproject's addopts, whose -q would add to the command's own and hide the totals line, the
    deselected count included."""
    text = " ".join((STACK_DIR / "README.md").read_text(encoding="utf-8").split())
    assert "Run it in PowerShell or cmd; in Git Bash use `cmd //c` with the argument in single quotes" in text
    assert "-m pytest -q -o addopts= -p no:cacheprovider @sdv/stack/wsl-pytest.args" in text
    assert ("-m pytest -q -o addopts= -p no:cacheprovider tests/test_aws_tooling.py tests/test_aws_noble.py "
            "tests/test_claims_lib.py::test_repo_slug_from_git_remote "
            "tests/test_sdv_cloud.py::%s" % _twinctl_git_tests()[0]) in text
    assert re.search(r'^addopts\s*=\s*"[^"]*-q', (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M)   # why the override


def test_the_readme_says_where_each_placement_variable_is_required_and_that_the_pcs_probes_refuse_on_the_orin():
    """sdv/stack/README.md's Placement section: both variables by name, where each is required, which cores the list may not
    hold, how the hook is split, and the four PC-only commands that refuse on the Orin."""
    text = " ".join((STACK_DIR / "README.md").read_text(encoding="utf-8").split())
    section = text[text.index("## Placement on the Orin (SDV Phase 5 WP1)"):]
    section = section[:section.index(" ## ", 1)]
    for words in ("**`SDV_CONTAINER_CPUSET`**", "It is **required on `orin`** and allowed on any role",
                  "holds core 0, 1, 2 or 4 is refused on every role", "**`SDV_AFTER_START`**",
                  "split with shlex and never given to a shell", "**required on `orin` beside either monitor**",
                  "On `orin` all four are refused before anything is written",
                  "`loadcheck`", "`ageprobe`", "`wheelbaseprobe`", "`exit-test`",
                  "the throwaway containers of `loadcheck`, `ageprobe` and `wheelbaseprobe`",
                  "(never after the probes' throwaway ones)"):
        assert words in section, words


def test_the_readme_and_the_docstring_name_phase_6s_variables_and_modes():
    """SDV Phase 6 WP2: sdv/stack/README.md names the host spool and status variables, the twin-control marker and its
    default, the external app and what APP_IMAGE_ID is; the module docstring has the four sections that say the same."""
    text = " ".join((STACK_DIR / "README.md").read_text(encoding="utf-8").split())
    for words in ("SDV_SPOOL_DIR", "SDV_STATUS_DIR", "both or neither", "SDV_TWIN_CONTROL_MARKER", "/run/sdv-local/twin-control",
                  "up --feed vcan --app external", "`APP_IMAGE_ID` is the app's config digest", "the stack never makes either",
                  "Taken only by `up --app external --connector`", "A run with no connector does not read them"):
        assert words in text, words
    doc = stack.__doc__ or ""
    for words in ("IMAGE IDS (SDV Phase 6 WP2", "APP (up --app; SDV Phase 6 WP2)", "HOST SPOOL AND STATUS (SDV Phase 6 WP2)",
                  "TWIN CONTROL (SDV Phase 6 WP2; owner decision D11)"):
        assert words in doc, words
    flat = " ".join(doc.split())
    for words in ("Taken only by up --app external --connector", "Read when a context with a connector is made, and by no other run"):
        assert words in flat, words


def test_the_docs_claim_no_more_than_the_locks_the_run_directories_and_the_recorder_source_show():
    """Three corrections of the r3 review, pinned: the two locks have the same pins (not the same
    bytes: their headers differ), the witness's behaviour in a replay is each run's record, and the
    ~= 0.5.2 range is the csv-provider repository's requirements.txt's (recorder.py names no version)."""
    readme = " ".join((STACK_DIR / "README.md").read_text(encoding="utf-8").split())
    assert "byte for byte" not in readme and "has not yet run in a replay" not in readme
    assert "the same pinned versions and hashes as the app's lock" in readme and "holds the pins equal" in readme
    assert "Whether the witness held every value in a given run is that run's record." in readme
    witness = " ".join((STACK_DIR / "witness.py").read_text(encoding="utf-8").split())
    assert "the same pinned versions and hashes as the app's lock" in witness and "same hash-checked lock" not in witness
    for f in (STACK_DIR / "recorder" / "Dockerfile", STACK_DIR / "recorder" / "requirements.lock"):
        text = " ".join(f.read_text(encoding="utf-8").split()).replace("# ", "")
        assert "requirements.txt" in text and "30a92880" in text and "recorder.py itself names no version" in text, f.name
        assert "recorder.py declares" not in text and "recorder.py itself declares" not in text, f.name
    cached = stack.CACHE / "csv-recorder-0.4.6" / "recorder.py"
    if cached.exists():
        assert not re.search(r"kuksa[-_]client\s*[~=<>!]", cached.read_text(encoding="utf-8"))      # the source carries no version specifier


# --- the twin connector in the stack (SDV Phase 4 WP3) ---------------------------------------------
# Against a replaced docker: nothing is started, nothing connects. The identifiers are placeholders on a reserved name.

CONNECTOR_IMG = "sha256:" + "c0" * 32
DEVICE_WORDS = ("device-endpoint.example.invalid", "example-thing", "example_rule")
DEVICE_ENV = "SDV_TWIN_ENDPOINT=%s\nSDV_TWIN_THING=%s\nSDV_TWIN_RULE=%s\n" % DEVICE_WORDS
T_WALL_MS = 1_790_000_000_000          # a fixture, not a date read
CONNECTOR_LOG = "\n".join([
    '2099-01-01T00:00:00.100000000Z {"allowlist_digest":"0x0BADF00D","allowlist_version":1,"catalogue":"83fe361177a8","event":"start","paths":16,'
    '"rate_hz":1,"t":1.0}',
    '2099-01-01T00:00:00.300000000Z {"event":"config-get","outcome":"rejected","t":1.2}',
    '2099-01-01T00:00:01.000000000Z {"bytes":803,"event":"shadow","name":"vss","t":2.0,"values":3}',
    '2099-01-01T00:00:40.000000000Z {"batch":1,"bytes":4000,"event":"batch","rows":40,"t":41.0}',
    '2099-01-01T00:00:40.100000000Z {"counters":{"sent_telemetry":1,"sent_vss":2,"failed_vss":0},"event":"stop","limiter":{},"signal":15,'
    '"source":{},"t":41.1,"uplink":{"given_up":1,"opened":1,"resumed_by_sdk":0}}']) + "\n"


def _device_dir(tmp_path, monkeypatch):
    """A device directory as the stack wants one (its environment file and three files that are no key), the connector's
    image named by ID, and the host's state directory under the test's own."""
    d = tmp_path / "device-directory-of-this-test"
    d.mkdir()
    (d / "connector.env").write_text(DEVICE_ENV, encoding="utf-8")
    for name in ("device.key", "device.crt", "ca.pem"):
        (d / name).write_text("a placeholder: no key and no certificate\n", encoding="utf-8")
    monkeypatch.setenv("SDV_DEVICE_DIR", str(d))
    monkeypatch.setenv("SDV_CONNECTOR_IMAGE", CONNECTOR_IMG)
    monkeypatch.setattr(stack, "STATE", tmp_path / "state")
    return d


def _connector_ctx(tmp_path, **over):
    ids = {attr.APP: IMG, attr.RECORDER: "sha256:" + "cd" * 32, stack.CONNECTOR: CONNECTOR_IMG}
    kw: Dict[str, Any] = dict(images=IMAGES, image_ids=lambda: ids, in_dir=tmp_path / "in", bridge="none", connector=True,
                              monitor=None, monitor_mode="native", guest=None, recorded=["Vehicle.Speed", hazard.HAZARD],
                              witness_paths=sorted(WITNESS_PATHS))
    kw.update(over)
    return types.SimpleNamespace(**kw)


class ConnectorDocker:
    """stack.docker replaced: every argument vector kept; the connector's container runs and has logged what `log` holds."""

    def __init__(self, log: str = CONNECTOR_LOG, running: str = "true 0", labels: Any = None, image: Any = None) -> None:
        self.calls: List[List[str]] = []
        self.log, self.running, self.labels, self.image = log, running, labels, image

    def __call__(self, *args: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        out = ""
        if args[:2] == ("image", "inspect"):
            info = {"Id": args[-1], "Config": {"Labels": self.labels or {}, "User": "10001:10001"}, "RepoTags": ["sdv-local/twin-connector:0.1.0"]}
            info.update(self.image or {})
            out = json.dumps([info])
        elif args[:1] == ("logs",):
            out = self.log
        elif args[:1] == ("inspect",):
            out = self.running if "{{.State.Running}} {{.State.ExitCode}}" in args else "exited 0"
        elif args[:1] == ("version",):
            out = "27.0\n"
        return subprocess.CompletedProcess(list(args), 0, out, "")

    def runs(self) -> List[List[str]]:
        return [c for c in self.calls if c[:1] == ["run"]]


def test_the_connector_is_one_more_container_a_run_may_start_and_the_six_of_phase_1_stay_six():
    assert len(stack.NAMES) == 6 and stack.CONNECTOR not in stack.NAMES
    assert stack.CONTAINERS == dict(stack.NAMES, **{attr.BRIDGE: "sdv-stack-bridge", stack.CONNECTOR: "sdv-stack-connector"})
    assert stack.CONNECTOR == "twin-connector" and len(set(stack.CONTAINERS.values())) == 8
    assert stack.CONNECTOR_MOUNTS == {"spool": "/run/sdv-local/spool/v1", "status": "/run/sdv-local/status/v1",
                                      "device": "/run/sdv-local/device"}


def test_a10_the_connector_container_has_three_mounts_the_hosts_namespace_a_read_only_root_and_no_name_on_its_argv(tmp_path, monkeypatch):
    """Design twin-allowlist.md A10, in the form of the bridge's argument test: exactly three mounts (the replay's spool
    read-write, its status read-only, the device directory read-only), the host's namespace, a read-only root, every
    capability dropped, no published port, no docker.sock, the host user (never root), restart policy no; and neither
    the endpoint nor the thing's or the rule's name on the argv: they come in by --env-file from the device directory.
    The dumpfile feed is refused."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = ConnectorDocker()
    monkeypatch.setattr(stack, "docker", fake)
    device = _device_dir(tmp_path, monkeypatch)
    ctx = _connector_ctx(tmp_path)
    rd = tmp_path / "r"
    with pytest.raises(stack.StackError, match="the connector needs .*spool"):
        stack.start(ctx, stack.CONNECTOR, "vcan", rd, "test/run")
    (rd / "spool").mkdir(parents=True)
    (rd / "status").mkdir()
    assert fake.runs() == []
    stack.start(ctx, stack.CONNECTOR, "vcan", rd, "test/run")
    (args,) = fake.runs()
    i = _image_index(args)
    opts, cmd = args[:i], args[i + 1:]
    assert args[i] == CONNECTOR_IMG and cmd == []                      # the image's own entry point, and no argument at all
    assert args[args.index("--name") + 1] == stack.CONNECTOR_CONTAINER
    assert opts[opts.index("--network") + 1] == "host" and opts.count("--network") == 1 and "--read-only" in opts
    assert args[args.index("--cap-drop") + 1] == "ALL" and "no-new-privileges" in args
    assert opts[opts.index("--user") + 1] == "%d:%d" % (os.getuid(), os.getgid()) and os.getuid() != 0
    assert opts[opts.index("--restart") + 1] == "no"
    mounts = [opts[k + 1] for k, a in enumerate(opts) if a == "--mount"]
    assert mounts == ["type=bind,src=%s,dst=/run/sdv-local/spool/v1" % (rd / "spool"),
                      "type=bind,src=%s,dst=/run/sdv-local/status/v1,readonly" % (rd / "status"),
                      "type=bind,src=%s,dst=/run/sdv-local/device,readonly" % device]
    # three mounts and no other way in: no -v (which makes a missing source), no tmpfs, no other container's volumes
    assert not {"-v", "--volume", "--tmpfs", "--volumes-from", "--device", "--pid", "--ipc", "--privileged", "--cap-add"} & set(opts)
    assert not {"-p", "--publish", "-P", "--publish-all", "--expose"} & set(opts)
    joined = " ".join(args)
    assert "docker.sock" not in joined and "/var/run" not in joined and "0.0.0.0" not in joined
    # the endpoint and the two names: through the device directory's environment file, and nowhere on the argv
    assert opts[opts.index("--env-file") + 1] == str(device / "connector.env") and opts.count("--env-file") == 1
    assert not {"-e", "--env"} & set(opts)
    for word in DEVICE_WORDS:
        assert word not in joined, word
    for feed in ("dumpfile", "none"):
        with pytest.raises(stack.StackError, match="--connector needs --feed vcan"):
            stack.start(ctx, stack.CONNECTOR, feed, rd, "test/run")
        with pytest.raises(stack.StackError, match="--connector needs --feed vcan"):
            stack.net_of(feed, stack.CONNECTOR)
    assert stack.net_of("vcan", stack.CONNECTOR) == ["--network", "host"] and len(fake.runs()) == 1


def test_the_stack_never_starts_the_connector_as_root(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = ConnectorDocker()
    monkeypatch.setattr(stack, "docker", fake)
    _device_dir(tmp_path, monkeypatch)
    rd = tmp_path / "r"
    (rd / "spool").mkdir(parents=True)
    (rd / "status").mkdir()
    monkeypatch.setattr(os, "getuid", lambda: 0)
    with pytest.raises(stack.StackError, match="never run as root"):
        stack.start(_connector_ctx(tmp_path), stack.CONNECTOR, "vcan", rd, "test/run")
    assert fake.runs() == []


def test_the_connector_is_refused_without_the_vcan_feed_before_anything_runs(tmp_path, monkeypatch):
    def touched(*_a, **_kw):          # were a refusal missing, this test would otherwise start a real stack
        raise AssertionError("the stack reached docker, the listeners or the recording though the connector was to be refused")

    for name in ("docker", "run", "remove_stack", "host_listeners", "start", "recording_identity"):
        monkeypatch.setattr(stack, name, touched)
    monkeypatch.setattr(stack, "STATE", tmp_path / "state")
    monkeypatch.delenv("SDV_DEVICE_DIR", raising=False)
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    for args in (["replay", "--connector", "--feed", "dumpfile", "--name", "x"], ["replay", "--connector", "--name", "x"],
                 ["up", "--connector", "--feed", "dumpfile", "--name", "x"], ["up", "--connector", "--name", "x"]):
        with pytest.raises(stack.StackError, match="--connector needs --feed vcan"):
            stack.main(args)
    assert not (tmp_path / "runs").exists()
    for cmd in ("prepare", "exit-test", "loadcheck", "ageprobe", "wheelbaseprobe"):          # only replay and up take one
        with pytest.raises(SystemExit):
            stack.main([cmd, "--connector", "--name", "x"])
    ctx = _connector_ctx(tmp_path, run_dir=tmp_path / "runs" / "y")
    with pytest.raises(stack.StackError, match="--connector needs --feed vcan"):
        stack.replay_once(ctx, "dumpfile", "dumpfile-1")
    with pytest.raises(stack.StackError, match="--connector needs --feed vcan"):
        stack.up(ctx, "dumpfile", tmp_path / "u", "x/u", None)
    assert not (tmp_path / "runs").exists() and not (tmp_path / "u").exists()


def test_main_hands_the_connector_switch_to_the_context_and_leaves_every_other_call_as_it_was(tmp_path, monkeypatch):
    seen: List[Any] = []

    class Stop(Exception):
        pass

    class FakeContext:
        def __init__(self, *args, **kwargs):
            seen.append((len(args), args[2], kwargs))

        def prepare(self, images="build"):
            raise Stop()

    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "Context", FakeContext)
    for i, args in enumerate((["replay", "--feed", "vcan", "--connector"], ["up", "--feed", "vcan", "--connector"],
                              ["replay", "--feed", "vcan", "--connector", "--bridge", "broker"], ["replay", "--feed", "vcan"],
                              ["up", "--feed", "vcan"], ["prepare"])):
        with pytest.raises(Stop):
            stack.main(args + ["--name", "n%d" % i])
    assert seen == [(3, "none", {"connector": True}), (3, "none", {"connector": True}), (3, "broker", {"connector": True}),
                    (3, "none", {}), (3, "none", {}), (3, "none", {})]


def test_a_connector_is_refused_beside_the_guest_monitor_mode(tmp_path, monkeypatch):
    """Without the refusal, "no QNX guest runs beside the connector" would be a property of today's command line and no
    rule: step3.py builds its own contexts. Refused where a context is made, before anything is written, and at up()."""
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    console, image = _guest_files(tmp_path)
    with pytest.raises(stack.StackError, match="guest monitor mode"):
        stack.Context(rig.runs / "g", None, "broker", monitor="guest", guest_host=GUEST, guest_console=console, guest_image=image,
                      connector=True)
    assert not (rig.runs / "g").exists()
    started: List[str] = []
    monkeypatch.setattr(stack, "remove_stack", lambda: started.append("remove"))
    monkeypatch.setattr(stack, "start", lambda ctx, comp, feed, rd, label: started.append(comp))
    monkeypatch.setattr(stack, "start_monitor", lambda ctx, rd, info: started.append("monitor"))
    monkeypatch.setattr(stack, "host_listeners", lambda: started.append("listeners") or {"with_owners": True, "sockets": []})
    for name in ("docker", "run", "ensure_vcan", "wait_log", "wait_for"):          # were the refusal missing, nothing real is reached
        monkeypatch.setattr(stack, name, lambda *a, name=name, **kw: started.append(name))
    monkeypatch.setattr(stack, "STATE", tmp_path / "state")
    ctx = _connector_ctx(tmp_path, bridge="broker", monitor_mode="guest", guest={"host": GUEST, "console": console, "image": image})
    with pytest.raises(stack.StackError, match="guest monitor mode"):
        stack.up(ctx, "vcan", tmp_path / "u", "x/u", {"bridge_mode": "broker"})
    assert started == [] and not (tmp_path / "u").exists()


@pytest.mark.parametrize("bridge", ["none", "broker"])
def test_up_starts_the_connector_after_the_app_and_the_bridge_and_before_the_listener_snapshot(tmp_path, monkeypatch, bridge):
    order: List[str] = []
    monkeypatch.setattr(stack, "remove_stack", lambda: None)
    monkeypatch.setattr(stack, "host_listeners", lambda: {"with_owners": True, "sockets": []})
    monkeypatch.setattr(stack, "ensure_vcan", lambda: {"created": False})
    monkeypatch.setattr(stack, "start", lambda ctx, comp, feed, rd, label: order.append(comp))
    monkeypatch.setattr(stack, "wait_log", lambda *a, **kw: None)
    monkeypatch.setattr(stack, "wait_for", lambda *a, **kw: None)
    monkeypatch.setattr(stack, "start_bridge", lambda ctx, feed, rd, label, header: order.append("bridge"))
    monkeypatch.setattr(stack, "start_monitor", lambda ctx, rd, info: order.append("monitor"))
    monkeypatch.setattr(stack, "listeners_now", lambda info, feed, suffix, al=(): order.append("listeners"))
    monkeypatch.setattr(stack, "connector_checks", lambda ctx, feed: order.append("checks"))
    monkeypatch.setattr(stack, "start_connector", lambda ctx, feed, rd, label: order.append("connector"))
    header = {"bridge_mode": bridge} if bridge != "none" else None
    stack.up(_connector_ctx(tmp_path, bridge=bridge), "vcan", tmp_path / "u", "x/u", header)
    parts = [attr.DATABROKER, attr.MOCK_PROVIDER, attr.RECORDER, stack.WITNESS, attr.APP]
    with_bridge = bridge != "none"
    assert order == ["checks"] + ["monitor"] * with_bridge + parts + ["bridge"] * with_bridge + ["connector", "listeners"]
    del order[:]
    stack.up(_connector_ctx(tmp_path, bridge=bridge, connector=False), "vcan", tmp_path / "v", "x/v", header)
    assert "connector" not in order and "checks" not in order and order[-1] == "listeners"
    # a context that knows no connector at all (Phase 1's, step3.py's own) starts none
    del order[:]
    stack.up(types.SimpleNamespace(bridge="none", monitor=None, monitor_mode="native"), "vcan", tmp_path / "w", "x/w", None)
    assert order == parts + ["listeners"]


def test_start_connector_makes_its_two_directories_keeps_the_stacks_stamp_and_waits_for_the_start_line(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = ConnectorDocker()
    monkeypatch.setattr(stack, "docker", fake)
    monkeypatch.setattr(stack, "wall_ms", lambda: T_WALL_MS)
    _device_dir(tmp_path, monkeypatch)
    rd = tmp_path / "runs" / "a" / "vcan-1"
    rd.mkdir(parents=True)
    stack.start_connector(_connector_ctx(tmp_path), "vcan", rd, "a/vcan-1")
    assert sorted(p.name for p in rd.iterdir()) == ["spool", "status"] and not list((rd / "status").iterdir()) and not list((rd / "spool").iterdir())
    stamp = tmp_path / "state" / "twin" / "started.json"
    assert json.loads(stamp.read_text(encoding="utf-8")) == {"started_ms": T_WALL_MS}          # the connector's own stamp, in the host's state
    assert len(fake.runs()) == 1 and [c for c in fake.calls if c[:1] == ["logs"]]
    # a connector that ended before it logged its start: the stack says which exit status that is, and starts no feed
    for k, (status, why) in enumerate(((2, "could not be put together"), (4, "its own start stamp"), (1, "uplink could not be opened"))):
        monkeypatch.setattr(stack, "wall_ms", lambda k=k: T_WALL_MS + (k + 1) * 200_000)
        early = ConnectorDocker(log="connector: a fixed sentence\n", running="false %d" % status)
        monkeypatch.setattr(stack, "docker", early)
        other = tmp_path / "runs" / ("b%d" % status) / "vcan-1"
        other.mkdir(parents=True)
        with pytest.raises(stack.StackError, match="the connector stopped before its start line: exit %d.*%s" % (status, why)):
            stack.start_connector(_connector_ctx(tmp_path), "vcan", other, "b/vcan-1")


def test_a_second_connector_start_within_the_spacing_is_refused_by_the_stacks_own_stamp_whatever_the_run_directory(tmp_path, monkeypatch):
    """Prep gap i. The connector's own stamp lies in its spool directory, and each replay has a new one: twelve starts on
    twelve run directories would be twelve starts. The stack keeps the same stamp (startstamp.py's) in the host's
    state directory, which outlives every run directory, and refuses a start inside the spacing before anything runs."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = ConnectorDocker()
    now = [T_WALL_MS]
    monkeypatch.setattr(stack, "docker", fake)
    monkeypatch.setattr(stack, "wall_ms", lambda: now[0])
    _device_dir(tmp_path, monkeypatch)
    ctx = _connector_ctx(tmp_path)
    spacing = stack.connector_part("limits").START_SPACING_S
    assert spacing == 120
    stack.connector_checks(ctx, "vcan")                                # nothing started yet: nothing to wait for
    first = tmp_path / "runs" / "a" / "vcan-1"
    first.mkdir(parents=True)
    stack.start_connector(ctx, "vcan", first, "a/vcan-1")
    stamp = tmp_path / "state" / "twin" / "started.json"
    kept = stamp.read_bytes()
    for k, dt in enumerate((1, 1_000, 60_000, spacing * 1000 - 1)):
        now[0] = T_WALL_MS + dt
        other = tmp_path / "runs" / ("b%d" % k) / "vcan-1"
        other.mkdir(parents=True)
        with pytest.raises(stack.StackError, match="start spacing"):
            stack.connector_checks(ctx, "vcan")
        with pytest.raises(stack.StackError, match="start spacing"):
            stack.start_connector(ctx, "vcan", other, "b/vcan-1")
        assert len(fake.runs()) == 1 and stamp.read_bytes() == kept and not list(other.iterdir())          # a refused start is no start
    # up() refuses before anything is started, removed or made
    touched: List[str] = []
    with monkeypatch.context() as m:
        m.setattr(stack, "remove_stack", lambda: touched.append("remove"))
        m.setattr(stack, "start", lambda *a, **k: touched.append("start"))
        for name in ("host_listeners", "ensure_vcan", "wait_log", "wait_for"):          # were the refusal missing, nothing real is reached
            m.setattr(stack, name, lambda *a, name=name, **k: touched.append(name))
        with pytest.raises(stack.StackError, match="start spacing: wait 1 s"):
            stack.up(ctx, "vcan", tmp_path / "runs" / "c" / "vcan-1", "c/vcan-1", None)
    assert touched == [] and not (tmp_path / "runs" / "c").exists()
    now[0] = T_WALL_MS + spacing * 1000                                # exactly the spacing later: let in
    stack.connector_checks(ctx, "vcan")
    later = tmp_path / "runs" / "d" / "vcan-1"
    later.mkdir(parents=True)
    stack.start_connector(ctx, "vcan", later, "d/vcan-1")
    assert len(fake.runs()) == 2 and json.loads(stamp.read_text(encoding="utf-8")) == {"started_ms": now[0]}
    # the state directory is never inside the repo
    monkeypatch.setattr(stack, "STATE", REPO / "sdv-out" / "state-of-a-test")
    with pytest.raises(stack.StackError, match="inside the repo"):
        stack.connector_checks(ctx, "vcan")
    assert not (REPO / "sdv-out" / "state-of-a-test").exists()


def _connector_labels(gen: Path) -> Dict[str, str]:
    return {"sdv.twin.allowlist_version": str(attr.ALLOWLIST_VERSION), "sdv.twin.allowlist_digest": "0x0BADF00D",
            "sdv.twin.catalogue_sha256": stack.sha256_file(gen / "vss-ids.vspec")}


def test_the_connector_image_is_taken_by_id_and_must_be_this_generations_and_no_root_image(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    (rig.gen / "vss-ids.vspec").write_text("a synthetic id file\n", encoding="utf-8")
    _device_dir(tmp_path, monkeypatch)
    good = _connector_labels(rig.gen)
    fake = ConnectorDocker(labels=good)
    monkeypatch.setattr(stack, "docker", fake)
    comp = stack.connector_image()
    assert comp["image_id"] == CONNECTOR_IMG and comp["class"] == "platform" and comp["form"] == "container" and comp["labels"] == good
    assert comp["pull"] == {"via": "local-build", "built_by": "sdv/connector/build_image.py"} and comp["user"] == "10001:10001"
    for ref in ("", "sdv-local/twin-connector:0.1.0", "sha256:" + "c0" * 31, "c0" * 32):
        monkeypatch.setenv("SDV_CONNECTOR_IMAGE", ref)
        with pytest.raises(stack.StackError, match="SDV_CONNECTOR_IMAGE"):
            stack.connector_image()
    monkeypatch.setenv("SDV_CONNECTOR_IMAGE", CONNECTOR_IMG)
    for labels, why in ((dict(good, **{"sdv.twin.catalogue_sha256": "e" * 64}), "another generation"),
                        (dict(good, **{"sdv.twin.allowlist_version": "2"}), "another generation"),
                        ({k: v for k, v in good.items() if k != "sdv.twin.allowlist_digest"}, "another generation"),
                        (dict(good, **{"sdv.twin.allowlist_digest": "unset"}), "another generation"), ({}, "another generation")):
        monkeypatch.setattr(stack, "docker", ConnectorDocker(labels=labels))
        with pytest.raises(stack.StackError, match=why):
            stack.connector_image()
    for user in ("", "0", "root", "0:0", "root:root", "0:10001"):
        monkeypatch.setattr(stack, "docker", ConnectorDocker(labels=good, image={"Config": {"Labels": good, "User": user}}))
        with pytest.raises(stack.StackError, match="root"):
            stack.connector_image()
    monkeypatch.setattr(stack, "docker", ConnectorDocker(labels=good, image={"Id": "sha256:" + "d1" * 32}))
    with pytest.raises(stack.StackError, match="whose image ID is"):
        stack.connector_image()


def test_prepare_refuses_a_connector_without_its_device_directory_or_on_loaded_images_before_anything_is_written(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    (rig.gen / "vss-ids.vspec").write_text("a synthetic id file\n", encoding="utf-8")
    device = _device_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(stack, "connector_image", lambda: {"class": "platform", "form": "container", "image_id": CONNECTOR_IMG})

    def refused(name, why, **kw):
        with pytest.raises(stack.StackError, match=why):
            stack.Context(rig.runs / name, None, "none", connector=True).prepare(pull=False, build=False, **kw)
        assert not (rig.runs / name).exists()

    refused("a", "an aarch64 host's connector is Phase 5's", images="loaded")
    monkeypatch.delenv("SDV_DEVICE_DIR")
    refused("b", "SDV_DEVICE_DIR")
    monkeypatch.setenv("SDV_DEVICE_DIR", str(tmp_path / "no-such-directory"))
    refused("c", "SDV_DEVICE_DIR")
    (device / "connector.env").unlink()
    monkeypatch.setenv("SDV_DEVICE_DIR", str(device))
    refused("d", "connector.env")
    inside = REPO / "sdv-out"
    monkeypatch.setenv("SDV_DEVICE_DIR", str(inside))
    refused("e", "inside the repo")
    monkeypatch.setenv("SDV_DEVICE_DIR", "relative/device")
    refused("f", "SDV_DEVICE_DIR")
    # and with everything there it is one more component of the run manifest, and a context without one records none
    (device / "connector.env").write_text(DEVICE_ENV, encoding="utf-8")
    monkeypatch.setenv("SDV_DEVICE_DIR", str(device))
    ctx = stack.Context(rig.runs / "g", None, "none", connector=True)
    man = ctx.prepare(pull=False, build=False)
    assert man["components"][stack.CONNECTOR]["image_id"] == CONNECTOR_IMG and ctx.image_ids()[stack.CONNECTOR] == CONNECTOR_IMG
    assert man["twin"]["connector"] is True and man["twin"]["allowlist_version"] == attr.ALLOWLIST_VERSION
    _ctx, plain = _prepare(rig, "h")
    assert stack.CONNECTOR not in plain["components"] and "twin" not in plain


def test_the_run_directory_of_a_fake_run_holds_no_endpoint_thing_rule_or_certificate_path(tmp_path, monkeypatch):
    """Everything the stack itself writes for a run with a connector: the run manifest, the run header, the start's
    records, the collected logs and states, the connector's result, and the host's state directory. None of it holds the
    endpoint, the thing's or the rule's name, the device directory's path or a name of a file in it. (The connector's own
    log and what the real docker writes are seen only by the opt-in full slice.)"""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch)
    (rig.gen / "vss-ids.vspec").write_text("a synthetic id file\n", encoding="utf-8")
    device = _device_dir(tmp_path, monkeypatch)
    fake = ConnectorDocker(labels=_connector_labels(rig.gen), running="true 0")
    monkeypatch.setattr(stack, "docker", fake)
    monkeypatch.setattr(stack, "wall_ms", lambda: T_WALL_MS)
    ctx = stack.Context(rig.runs / "c", None, "none", connector=True)
    ctx.prepare(pull=False, build=False)
    rd = rig.runs / "c" / "vcan-1"
    rd.mkdir()
    info: Dict[str, Any] = {"feed": "vcan"}
    stack.connector_checks(ctx, "vcan")
    stack.start_connector(ctx, "vcan", rd, "c/vcan-1")
    stack.write_json(rd / "listeners.json", info)
    stack.write_json(rd / "attribution.json", {"header": ctx.run_header("vcan-1", "vcan")})
    states = stack.collect(rd)
    result = {"replay": "vcan-1", "containers": states, "connector": stack.connector_result(rd, states)}
    stack.write_json(rd / "result.json", result)
    assert result["connector"]["ok"] is True and (rd / ("%s.log" % stack.CONNECTOR)).read_text(encoding="utf-8") == CONNECTOR_LOG
    files = [p for root in (rig.runs / "c", tmp_path / "state") for p in sorted(root.rglob("*")) if p.is_file()]
    assert len(files) >= 16 and {"manifest.json", "result.json", "attribution.json", "started.json", "twin-connector.log"} <= {p.name for p in files}
    forbidden = DEVICE_WORDS + (str(device), device.name, "connector.env", "device.key", "device.crt", "ca.pem", "SDV_TWIN_ENDPOINT")
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for word in forbidden:
            assert word not in text, (p.name, word)
    # not clean by never having had them: the argument vector the stack handed docker names the device directory twice
    (run,) = fake.runs()
    assert sum(str(device) in a for a in run) == 2


def test_the_connector_is_stopped_with_sigterm_after_the_app_and_before_the_databroker(monkeypatch):
    """Its last flush reads the databroker once more and sends a batch and a document, so it is stopped while the
    databroker still runs, with a grace that covers two publishes each waited for. `docker stop` is SIGTERM, then KILL."""
    calls: List[Any] = []
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: calls.append(list(a)) or subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(stack.time, "sleep", lambda s: calls.append("settle"))
    stack.stop_containers(types.SimpleNamespace(bridge="broker", connector=True))
    N = stack.NAMES
    assert calls == [["stop", "-t", "10", N[attr.CAN_PROVIDER]], ["stop", "-t", "10", N[attr.APP]], "settle",
                     ["stop", "-t", "10", N[stack.WITNESS]], ["stop", "-t", "10", stack.BRIDGE_CONTAINER],
                     ["stop", "-t", str(stack.CONNECTOR_STOP_S), stack.CONNECTOR_CONTAINER],
                     ["stop", "-t", "3", N[attr.RECORDER]], ["stop", "-t", "3", N[attr.MOCK_PROVIDER]], ["stop", "-t", "3", N[attr.DATABROKER]]]
    L = stack.connector_part("limits")
    assert stack.CONNECTOR_STOP_S >= 2 * (L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S) + L.CONNECT_WAIT_S + L.CLOSE_WAIT_S + L.TELEMETRY_MIN_GAP_S
    del calls[:]
    stack.stop_containers(types.SimpleNamespace(bridge="none"))          # Phase 1's context: no bridge, no connector
    assert [c[-1] for c in calls if c != "settle"] == [N[attr.CAN_PROVIDER], N[attr.APP], N[stack.WITNESS], N[attr.RECORDER],
                                                       N[attr.MOCK_PROVIDER], N[attr.DATABROKER]]


def test_the_connectors_result_is_its_exit_status_and_its_logs_first_and_last_lines_and_a_gate_of_the_replay(tmp_path):
    def result(log, state="exited 0"):
        d = tmp_path / ("r%d" % len(list(tmp_path.iterdir())))
        d.mkdir()
        if log is not None:
            (d / ("%s.log" % stack.CONNECTOR)).write_text(log, encoding="utf-8")
        return stack.connector_result(d, {stack.CONNECTOR: state} if state else {})

    good = result(CONNECTOR_LOG)
    assert good["ok"] is True and good["exit"] == 0 and good["exit_means"] == "stopped"
    assert good["events"] == {"start": 1, "config-get": 1, "shadow": 1, "batch": 1, "stop": 1}
    assert good["counters"] == {"sent_telemetry": 1, "sent_vss": 2, "failed_vss": 0} and good["start"]["allowlist_version"] == 1
    # the uplink's own counters are copied from the stop line too (resumed_by_sdk counts an SDK that came back by
    # itself); a log with no stop line has none, as it has no other counter
    assert good["uplink"] == {"given_up": 1, "opened": 1, "resumed_by_sdk": 0} and good["limiter"] == {}
    lines = CONNECTOR_LOG.splitlines()
    cut = result("\n".join(lines[:-1]) + "\n")
    assert (cut["uplink"], cut["limiter"], cut["counters"]) == (None, None, None)
    assert result(CONNECTOR_LOG.replace(',"uplink":{"given_up":1,"opened":1,"resumed_by_sdk":0}', ""))["uplink"] is None          # an older log
    for log, state in (("\n".join(lines[:-1]) + "\n", "exited 0"),          # no stop line: its last flush did not end
                       (CONNECTOR_LOG, "exited 137"),                          # killed after its grace
                       (CONNECTOR_LOG, "exited 3"), (CONNECTOR_LOG, "running 0"), (CONNECTOR_LOG, None), (None, "exited 0"),
                       ("\n".join(lines[1:]) + "\n", "exited 0"),            # no start line
                       ("2099-01-01T00:00:00.1Z connector: one fixed sentence\n", "exited 2")):
        assert result(log, state)["ok"] is False, (log, state)
    assert result(CONNECTOR_LOG, "exited 4")["exit_means"] == stack.CONNECTOR_EXITS[4]
    # the replay's gates: one more when the replay had a connector, none when it had none
    r = _gated_result(mode="none", connector=good)
    assert stack.replay_gates(r)["connector"] is True and not stack.replay_gates(dict(r, connector={"ok": False}))["connector"]
    assert "connector" not in stack.replay_gates(_gated_result(mode="none"))


# --- placement on the Orin (SDV Phase 5 WP1): SDV_CONTAINER_CPUSET and SDV_AFTER_START ---------------------
# stack.py's PLACEMENT: the CPUs every container may run on, and the command run after each container start (plan 3.7).
# PLACE_CPUSET is the plan's design value for the Orin; the hook is a stand-in script that logs its argument vector.
# Nothing here runs on a board, a QEMU or a real docker.
PLACE_CPUSET = "3,5"
REC_IMG = "sha256:" + "cd" * 32
BRIDGE_IMG = "sha256:" + "ef" * 32
HOOK_PY = """\
import os
import sys
import time
with open(os.environ["SDV_TEST_HOOK_LOG"], "a", encoding="utf-8") as f:
    f.write("hook %s\\n" % " ".join(sys.argv[1:]))
mode = os.environ.get("SDV_TEST_HOOK_MODE", "ok")
if mode == "sleep":
    time.sleep(60)
print("a first line")
print("tag=%s threads=4 moved=0 all_on=yes" % sys.argv[-1])
print("a line on stderr", file=sys.stderr)
sys.exit(3 if mode == "fail" else 0)
"""


def _placement_env(monkeypatch, cpuset=None, hook=None, role=None):
    """SDV_CONTAINER_CPUSET, SDV_AFTER_START and SDV_HOST_ROLE as given; None: unset."""
    for name, value in (("SDV_CONTAINER_CPUSET", cpuset), ("SDV_AFTER_START", hook), ("SDV_HOST_ROLE", role)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _hook(tmp_path, monkeypatch, *extra):
    """The stand-in hook in a directory whose name holds a space, the SDV_AFTER_START value that runs it with `extra`
    after it (shlex-quoted), and the log it and the fake docker append to."""
    d = tmp_path / "hook dir"
    d.mkdir(exist_ok=True)
    script = d / "hook.py"
    script.write_text(HOOK_PY, encoding="utf-8")
    log = tmp_path / "order.log"
    monkeypatch.setenv("SDV_TEST_HOOK_LOG", str(log))
    monkeypatch.delenv("SDV_TEST_HOOK_MODE", raising=False)
    return shlex.join([sys.executable, str(script)] + list(extra)), script, log


class OrderDocker:
    """stack.docker replaced: every argument vector kept, and each `run` written to the hook's log, so the log holds the
    starts and the hooks in the order they happened. fail_run: the run of that container name fails."""

    def __init__(self, log: Path, fail_run: str = "", bridge_dir: Any = None) -> None:
        self.log, self.fail_run, self.bridge_dir = log, fail_run, bridge_dir
        self.calls: List[List[str]] = []

    def __call__(self, *args: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        out = ""
        if args[:1] == ("run",):
            name = args[args.index("--name") + 1]
            if name == self.fail_run:
                raise stack.StackError("docker run failed (125): a synthetic failure")
            with open(self.log, "a", encoding="utf-8") as f:
                f.write("docker run %s\n" % name)
            if name == stack.BRIDGE_CONTAINER and self.bridge_dir is not None:
                (self.bridge_dir / "bridge.jsonl").write_text('{"event": "start"}\n', encoding="utf-8")
        elif args[:1] == ("inspect",):
            out = "true"
        return subprocess.CompletedProcess(list(args), 0, out, "")

    def runs(self) -> List[List[str]]:
        return [c for c in self.calls if c[:1] == ["run"]]


def _placed_ctx(rig, name, bridge="broker", **kw):
    """A real Context (it reads the three variables) on the prepare rig, with the image IDs start() needs."""
    ctx = stack.Context(rig.runs / name, None, bridge, **kw)
    ctx.components = {attr.APP: {"image_id": IMG, "config_digest": APP_CFG}, attr.RECORDER: {"image_id": REC_IMG},
                      attr.BRIDGE: {"image_id": BRIDGE_IMG}}
    return ctx


def _todays_ctx(ctx):
    """The same run as a context that knows neither variable, as every test before Phase 5 makes one."""
    return types.SimpleNamespace(images=IMAGES, image_ids=ctx.image_ids, in_dir=ctx.in_dir, recorded=ctx.recorded,
                                 witness_paths=ctx.witness_paths, bridge=ctx.bridge, monitor_mode="native", guest=None,
                                 components=ctx.components)


def _start_all(ctx, rd, monkeypatch, log, feeds=stack.FEEDS):
    """start() for the six of Phase 1 in each feed, then the bridge (vcan): {"feed:container": argv}."""
    fake = OrderDocker(log)
    monkeypatch.setattr(stack, "docker", fake)
    (rd / "bridge").mkdir(parents=True, exist_ok=True)
    (rd / "scenario.lock").touch()
    (rd / "bridge-header.json").write_text("{}", encoding="utf-8")
    keys = []
    for feed in feeds:
        for comp in stack.NAMES:
            stack.start(ctx, comp, feed, rd, "test/run")
            keys.append("%s:%s" % (feed, stack.NAMES[comp]))
    stack.start(ctx, attr.BRIDGE, "vcan", rd, "test/run")
    keys.append("vcan:" + stack.BRIDGE_CONTAINER)
    runs = fake.runs()
    assert len(runs) == len(keys)
    return dict(zip(keys, runs))


def test_with_neither_variable_set_no_container_gets_a_cpuset_no_hook_runs_and_every_argv_is_todays(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    _env, _script, log = _hook(tmp_path, monkeypatch)
    for role in (None, "pc", "a1-metal", "c7g-metal"):
        _placement_env(monkeypatch, role=role)
        ctx = _placed_ctx(rig, "n-%s" % role)
        assert ctx.cpuset is None and ctx.after_start is None
        rd = tmp_path / ("r-%s" % role)
        placed = _start_all(ctx, rd, monkeypatch, log)
        assert log.read_text(encoding="utf-8").splitlines() == ["docker run %s" % k.split(":", 1)[1] for k in placed], "no hook ran"
        log.unlink()
        assert placed == _start_all(_todays_ctx(ctx), rd, monkeypatch, log), "byte for byte the argv of a context before Phase 5"
        log.unlink()
        assert not any("--cpuset-cpus" in a for args in placed.values() for a in args)
        assert ctx.after_start_records == [] and stack.hook_records(ctx) is None


@pytest.mark.parametrize("role", [None, "a1-metal", "orin"])
def test_a_cpuset_reaches_every_container_right_after_the_common_flags_and_no_other_flag_moves(tmp_path, monkeypatch, role):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    env, _script, log = _hook(tmp_path, monkeypatch)
    _placement_env(monkeypatch, cpuset=PLACE_CPUSET, hook=env if role == "orin" else None, role=role)     # orin needs the hook
    ctx = _placed_ctx(rig, "c")
    assert ctx.cpuset == PLACE_CPUSET and (ctx.after_start is None) is (role != "orin")
    rd = tmp_path / "r"
    placed = _start_all(ctx, rd, monkeypatch, log)
    today = _start_all(_todays_ctx(ctx), rd, monkeypatch, log)
    assert len(placed) == 2 * len(stack.NAMES) + 1
    for key, args in placed.items():
        base = today[key]
        i = base.index("--memory-swap") + 2          # the end of the common flags
        assert base[i - len(stack.COMMON):i] == stack.COMMON, key
        assert args == base[:i] + ["--cpuset-cpus", PLACE_CPUSET] + base[i:], key
    # the connector takes it as every other container does (its start needs its device directory)
    fake = ConnectorDocker()
    monkeypatch.setattr(stack, "docker", fake)
    _device_dir(tmp_path, monkeypatch)
    (rd / "spool").mkdir()
    (rd / "status").mkdir()
    stack.start(_connector_ctx(tmp_path, cpuset=PLACE_CPUSET), stack.CONNECTOR, "vcan", rd, "test/run")
    stack.start(_connector_ctx(tmp_path), stack.CONNECTOR, "vcan", rd, "test/run")
    placed_c, today_c = fake.runs()
    i = today_c.index("--memory-swap") + 2
    assert placed_c == today_c[:i] + ["--cpuset-cpus", PLACE_CPUSET] + today_c[i:]


def test_the_probes_docker_runs_take_the_cpuset_too(tmp_path, monkeypatch):
    """loadcheck's and ageprobe's throwaway databroker and probe containers use the common flags as well: with
    SDV_CONTAINER_CPUSET set (the PC rehearsal; on the Orin both commands are refused) each of their runs holds it once."""
    in_dir = tmp_path / "in"
    in_dir.mkdir()
    (in_dir / "vss-databroker.json").write_text("{}", encoding="utf-8")
    calls: List[List[str]] = []
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: calls.append(list(a)) or subprocess.CompletedProcess(a, 0, "{}", ""))
    monkeypatch.setattr(stack, "wait_log", lambda *a, **kw: None)
    monkeypatch.setattr(stack, "ageprobe_args", lambda contract: [])
    for cpuset, want in ((PLACE_CPUSET, [["--cpuset-cpus", PLACE_CPUSET]] * 4), (None, [])):
        del calls[:]
        ctx = types.SimpleNamespace(in_dir=in_dir, images=IMAGES, image_ids=lambda: {attr.RECORDER: REC_IMG}, contract=None, cpuset=cpuset)
        stack.load_catalogue(ctx, "x", in_dir / "vss-databroker.json", [], tmp_path / "out")
        stack.age_probe(ctx, tmp_path / "age")
        runs = [c for c in calls if c[:1] == ["run"]]
        assert len(runs) == 4
        got = [c[c.index("--cpuset-cpus"):c.index("--cpuset-cpus") + 2] for c in runs if "--cpuset-cpus" in c]
        assert got == want and all(c.count("--cpuset-cpus") == (1 if cpuset else 0) for c in runs)


@pytest.mark.parametrize("value, why", [
    ("", "is set but empty"),
    ("4", "holds CPU 4"), ("3,4", "holds CPU 4"), ("5,4,3", "holds CPU 4"),
    ("0", "holds CPU 0"), ("1,3", "holds CPU 1"), ("3,2", "holds CPU 2"), ("0,1,2,4", "holds CPU 0, 1, 2, 4"),
    ("3,3", "names a CPU twice"),
    ("3-5", "not a CPU list"), ("3, 5", "not a CPU list"), (" 3", "not a CPU list"), ("3,", "not a CPU list"),
    (",3", "not a CPU list"), ("-3", "not a CPU list"), ("x", "not a CPU list"), ("03", "not a CPU list"), ("3;5", "not a CPU list"),
    ("3,5 ", "not a CPU list"), ("\t3", "not a CPU list"), ("3,,5", "not a CPU list"), ("+3", "not a CPU list"),
    ("3.0", "not a CPU list"), ("00", "not a CPU list"), ("2,4", "holds CPU 2, 4"), ("4,4", "names a CPU twice"),
    ("6,4,6", "names a CPU twice"),
])
def test_a_cpuset_that_is_empty_malformed_or_holds_qemus_or_the_probes_cores_is_refused_before_anything_is_written(
        tmp_path, monkeypatch, value, why):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    for role in ("pc", "a1-metal", "c7g-metal", "orin"):
        _placement_env(monkeypatch, cpuset=value, role=role)
        with pytest.raises(stack.StackError, match="SDV_CONTAINER_CPUSET") as e:
            stack.Context(rig.runs / "x", None, "broker")
        assert why in str(e.value), (role, str(e.value))
        assert not (rig.runs / "x").exists()


@pytest.mark.parametrize("value", ["3", "5", "3,5", "5,3", "3,5,6", "7", "10", "6", "3,6", "11,12", "5,3,6"])
def test_a_cpu_list_off_qemus_and_the_probes_cores_is_taken_as_given(tmp_path, monkeypatch, value):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    for role in ("pc", "orin"):
        _placement_env(monkeypatch, cpuset=value, hook="/opt/x/repin" if role == "orin" else None, role=role)
        assert stack.Context(rig.runs / "x", None, "broker").cpuset == value


def test_role_orin_needs_a_cpuset_and_a_hook_beside_either_monitor_each_refused_before_anything_is_written(tmp_path, monkeypatch):
    """On orin the cpuset is required, and so is the hook beside the native monitor as beside the guest's (the stack
    knows the board only by its role, and a guest may run beside a native-monitor run, so no container starts there
    without the re-pin after it). Off the Orin neither is required."""
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    console, image = _guest_files(tmp_path)
    monkeypatch.setattr(stack, "local_ipv4", lambda: ["192.0.2.1"])
    guest: Dict[str, Any] = dict(monitor="guest", guest_host=GUEST, guest_console=console, guest_image=image)
    hook = "/opt/someone/vss-repin.sh"          # never run here: a Context only splits it
    for cpuset, after, kw, refused in ((None, None, {}, "SDV_CONTAINER_CPUSET"), (None, hook, guest, "SDV_CONTAINER_CPUSET"),
                                       (None, hook, {}, "SDV_CONTAINER_CPUSET"), (PLACE_CPUSET, None, guest, "SDV_AFTER_START"),
                                       (PLACE_CPUSET, None, {}, "SDV_AFTER_START")):
        _placement_env(monkeypatch, cpuset=cpuset, hook=after, role="orin")
        with pytest.raises(stack.StackError, match=refused) as e:
            stack.Context(rig.runs / "o", None, "replay", **kw)
        assert "orin" in str(e.value) and hook not in str(e.value) and not (rig.runs / "o").exists()
    _placement_env(monkeypatch, cpuset=PLACE_CPUSET, hook=hook, role="orin")
    native = stack.Context(rig.runs / "o", None, "replay")
    assert (native.cpuset, native.after_start) == (PLACE_CPUSET, [hook]), "the native monitor takes the hook too"
    with_guest = stack.Context(rig.runs / "o", None, "replay", **guest)
    assert (with_guest.cpuset, with_guest.after_start) == (PLACE_CPUSET, [hook])
    for role in (None, "pc", "a1-metal", "c7g-metal"):          # neither is required off the Orin
        _placement_env(monkeypatch, role=role)
        for k in ({}, guest):
            ctx = stack.Context(rig.runs / "o", None, "replay", **k)
            assert (ctx.cpuset, ctx.after_start) == (None, None)
    assert not (rig.runs / "o").exists()


@pytest.mark.parametrize("value, why", [
    ("", "is set but empty"), ("   ", "is set but empty"),
    ("'/opt/someone/vss-repin.sh", "cannot be split"), ('/opt/someone/vss-repin.sh "boot', "cannot be split"),
    ("\t", "is set but empty"), ("\n", "is set but empty"), ("/opt/someone/vss-repin.sh \\", "cannot be split"),
    ("\"/opt/someone/x", "cannot be split"),
])
def test_an_after_start_that_shlex_cannot_split_or_that_is_empty_is_refused_before_anything_is_written(tmp_path, monkeypatch, value, why):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    for role, cpuset in (("pc", None), ("a1-metal", None), ("c7g-metal", None), ("orin", PLACE_CPUSET)):
        _placement_env(monkeypatch, cpuset=cpuset, hook=value, role=role)
        with pytest.raises(stack.StackError, match="SDV_AFTER_START") as e:
            stack.Context(rig.runs / "h", None, "broker")
        assert why in str(e.value) and "/opt/someone" not in str(e.value), str(e.value)
        assert not (rig.runs / "h").exists()
    _placement_env(monkeypatch, hook='/opt/x/repin "a b" $HOME ;')
    assert stack.Context(rig.runs / "h", None, "broker").after_start == ["/opt/x/repin", "a b", "$HOME", ";"]


def test_the_hook_runs_after_each_container_start_with_the_containers_name_last_and_never_through_a_shell(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    env, script, log = _hook(tmp_path, monkeypatch, "$HOME", ";", "two words")
    _placement_env(monkeypatch, hook=env)          # the PC rehearsal: allowed on any role
    ctx = _placed_ctx(rig, "h")
    assert ctx.after_start == [sys.executable, str(script), "$HOME", ";", "two words"], "the argv as given, split by shlex"
    placed = _start_all(ctx, tmp_path / "r", monkeypatch, log, feeds=("vcan",))
    names = [k.split(":", 1)[1] for k in placed]
    assert names == list(stack.NAMES.values()) + [stack.BRIDGE_CONTAINER]
    want = [line for n in names for line in ("docker run %s" % n, "hook $HOME ; two words %s" % n)]
    assert log.read_text(encoding="utf-8").splitlines() == want, "each hook after its container's start, the name last, no shell"
    recs = ctx.after_start_records
    assert [r["container"] for r in recs] == names and stack.hook_records(ctx) == recs
    for n, r in zip(names, recs):
        assert r == {"container": n, "exit": 0, "output": ["a first line", "tag=%s threads=4 moved=0 all_on=yes" % n],
                     "stderr": ["a line on stderr"], "error": None}, r
    # a container whose docker run fails was never started: no hook runs for it
    log.unlink()
    stack.new_hook_records(ctx)
    monkeypatch.setattr(stack, "docker", OrderDocker(log, fail_run=stack.NAMES[attr.DATABROKER]))
    with pytest.raises(stack.StackError, match="synthetic failure"):
        stack.start(ctx, attr.DATABROKER, "vcan", tmp_path / "r", "test/run")
    assert not log.exists() and ctx.after_start_records == []


def test_the_hook_keeps_the_last_lines_of_its_output(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    _placement_env(monkeypatch, hook=shlex.join([sys.executable, "-c", "for i in range(9): print('line %d' % i)"]))
    ctx = _placed_ctx(rig, "k")
    monkeypatch.setattr(stack, "docker", OrderDocker(tmp_path / "order.log"))
    stack.start(ctx, attr.DATABROKER, "vcan", tmp_path / "r", "test/run")
    (rec,) = ctx.after_start_records
    assert rec["output"] == ["line %d" % i for i in range(9 - stack.AFTER_START_KEPT, 9)] and rec["stderr"] == []


@pytest.mark.parametrize("mode, why, code", [
    ("fail", "exit 3", 3),
    ("sleep", "did not end within", None),
    ("missing", "could not be started", None),
])
def test_a_hook_that_fails_times_out_or_cannot_start_fails_the_start_with_a_refusal_naming_the_container(tmp_path, monkeypatch, mode, why, code):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    env, _script, log = _hook(tmp_path, monkeypatch)
    if mode == "missing":
        env = shlex.quote(str(tmp_path / "no such hook"))
    monkeypatch.setenv("SDV_TEST_HOOK_MODE", mode)
    monkeypatch.setattr(stack, "AFTER_START_TIMEOUT_S", 1.0)
    _placement_env(monkeypatch, cpuset=PLACE_CPUSET, hook=env, role="orin")
    ctx = _placed_ctx(rig, "f")
    fake = OrderDocker(log)
    monkeypatch.setattr(stack, "docker", fake)
    name = stack.NAMES[attr.DATABROKER]
    with pytest.raises(stack.StackError) as e:
        stack.start(ctx, attr.DATABROKER, "vcan", tmp_path / "r", "test/run")
    msg = str(e.value)
    assert "SDV_AFTER_START" in msg and name in msg and why in msg, msg
    assert [c[c.index("--name") + 1] for c in fake.runs()] == [name], "the container was started: the run's own paths remove it"
    (rec,) = ctx.after_start_records
    assert rec["container"] == name and rec["exit"] == code and (rec["error"] is None) == (mode == "fail"), rec
    if mode == "fail":
        assert rec["output"][-1].startswith("tag=" + name) and rec["stderr"] == ["a line on stderr"]


def test_a_hook_that_exits_1_as_vss_repin_does_off_its_cores_fails_the_start(tmp_path, monkeypatch):
    """vss-repin.sh exits 1 when a thread reads back off QEMU's cores (3 when no QEMU or two): exit 1 fails the start too."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    _placement_env(monkeypatch, cpuset=PLACE_CPUSET, role="orin",
                   hook=shlex.join([sys.executable, "-c", "import sys; print('repin tag=%s on_cores=no' % sys.argv[1]); sys.exit(1)"]))
    ctx = _placed_ctx(rig, "e1")
    monkeypatch.setattr(stack, "docker", OrderDocker(tmp_path / "order.log"))
    with pytest.raises(stack.StackError, match="exit 1"):
        stack.start(ctx, attr.DATABROKER, "vcan", tmp_path / "r", "test/run")
    (rec,) = ctx.after_start_records
    assert rec["exit"] == 1 and rec["output"] == ["repin tag=%s on_cores=no" % stack.NAMES[attr.DATABROKER]], rec


def test_a_hook_that_times_out_after_printing_keeps_its_lines_as_text(tmp_path, monkeypatch):
    """A timeout's partial output comes back as bytes whatever text= said: the record keeps it as text (it goes to JSON)."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    _placement_env(monkeypatch, hook=shlex.join([sys.executable, "-c", "import time; print('before the stall', flush=True); time.sleep(60)"]))
    monkeypatch.setattr(stack, "AFTER_START_TIMEOUT_S", 1.0)
    ctx = _placed_ctx(rig, "t")
    monkeypatch.setattr(stack, "docker", OrderDocker(tmp_path / "order.log"))
    with pytest.raises(stack.StackError, match="did not end within"):
        stack.start(ctx, attr.DATABROKER, "vcan", tmp_path / "r", "test/run")
    (rec,) = ctx.after_start_records
    assert rec["output"] == ["before the stall"] and json.loads(json.dumps(rec)) == rec, rec


def test_main_refuses_the_pc_only_probes_on_the_orin_before_anything_is_written(tmp_path, monkeypatch):
    """loadcheck, ageprobe and wheelbaseprobe start containers outside start(); exit-test ends with loadcheck. On the Orin
    each is refused before a Context exists, so before anything is pulled, written or started."""
    def touched(*_a, **_kw):
        raise AssertionError("the stack went on though the command was to be refused")

    for name in ("docker", "run", "remove_stack", "Context", "loadcheck", "age_probe", "wheelbase_probe", "load_catalogue"):
        monkeypatch.setattr(stack, name, touched)
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    for cpuset, hook in ((PLACE_CPUSET, None), (PLACE_CPUSET, "/opt/x/repin"), (None, None)):
        _placement_env(monkeypatch, cpuset=cpuset, hook=hook, role="orin")
        for cmd in ("loadcheck", "ageprobe", "wheelbaseprobe", "exit-test"):
            with pytest.raises(stack.StackError, match=re.escape(cmd)) as e:
                stack.main([cmd, "--name", "x"])
            assert "SDV_HOST_ROLE=orin" in str(e.value)
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("cmd, extra", [("up", ["--feed", "vcan"]), ("replay", ["--feed", "vcan", "--bridge", "broker"]),
                                        ("replay", []), ("prepare", [])])
def test_on_the_orin_main_refuses_a_native_monitor_run_without_the_hook_before_anything_is_written(tmp_path, monkeypatch, cmd, extra):
    """stack.py's own commands run the native monitor (or none), and on orin each needs SDV_AFTER_START as a guest-mode
    run does: without it the Context refuses before anything is pulled, written or started."""
    _prepare_rig(tmp_path, monkeypatch, bridge=True)

    def touched(*_a, **_kw):
        raise AssertionError("the stack went on though the command was to be refused")

    for name in ("docker", "run", "remove_stack", "up", "replay_once", "build_native_monitor", "ensure_vcan"):
        monkeypatch.setattr(stack, name, touched, raising=False)
    monkeypatch.setattr(stack, "RUNS", tmp_path / "orin-runs")
    _placement_env(monkeypatch, cpuset=PLACE_CPUSET, role="orin")
    with pytest.raises(stack.StackError, match="SDV_AFTER_START") as e:
        stack.main([cmd, "--name", "x"] + extra)
    assert "SDV_HOST_ROLE=orin" in str(e.value) and not (tmp_path / "orin-runs").exists()


@pytest.mark.parametrize("cmd", ["loadcheck", "ageprobe", "wheelbaseprobe", "exit-test", "prepare", "replay", "up"])
def test_off_the_orin_main_takes_every_command_as_before_and_on_it_the_run_commands(tmp_path, monkeypatch, cmd):
    seen: List[Any] = []

    class Stop(Exception):
        pass

    class FakeContext:
        def __init__(self, run_dir, seed, bridge):
            seen.append(run_dir)

        def prepare(self, images="build"):
            raise Stop()

    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "Context", FakeContext)
    extra = ["--feed", "vcan"] if cmd in ("replay", "up") else []
    roles = ("pc", "a1-metal", "c7g-metal", "orin") if cmd in ("prepare", "replay", "up") else ("pc", "a1-metal", "c7g-metal")
    for i, role in enumerate(roles):
        _placement_env(monkeypatch, cpuset=PLACE_CPUSET if role == "orin" else None, role=role)
        with pytest.raises(Stop):
            stack.main([cmd, "--name", "n%d" % i] + extra)
    assert len(seen) == len(roles)


def test_the_run_manifest_records_the_cpuset_and_the_hooks_argv_or_that_none_was_set(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    _placement_env(monkeypatch)
    _ctx, man = _prepare(rig, "a")
    p = man["placement"]
    assert (p["cpuset"], p["after_start"]) == (None, None) and "not set" in p["cpuset_note"] and "not set" in p["after_start_note"]
    _placement_env(monkeypatch, cpuset=PLACE_CPUSET, hook="/opt/x/vss-repin.sh 'a b'", role="orin")
    _ctx, man = _prepare(rig, "b")
    p = man["placement"]
    assert (p["cpuset"], p["after_start"]) == (PLACE_CPUSET, ["/opt/x/vss-repin.sh", "a b"]) and man["host_role"] == "orin"
    assert "--cpuset-cpus 3,5" in p["cpuset_note"] and "container's name" in p["after_start_note"]
    assert json.loads((rig.runs / "b" / "manifest.json").read_text(encoding="utf-8"))["placement"] == p


def _replay_ctx(tmp_path, after_start):
    """A context replay_once can run with every outside call replaced; its hook is the given argv (None: none)."""
    return types.SimpleNamespace(bridge="none", monitor_mode="native", monitor=None, guest=None, run_dir=tmp_path / "runs" / "p",
                                 run_header=lambda rid, feed: {"run_id": rid}, check_header=lambda h: ("C12a", True, "synthetic"),
                                 rows=[], image_ids=lambda: {}, staged={"sigsim.log": "ab" * 32}, scenario={"dbc_sha256": "x"},
                                 manifest={"scenario_checks": []}, decoded={"values": {rc.V_PATH: [], attr.SLOT_PATHS[4]: []}},
                                 images=IMAGES, in_dir=tmp_path / "in", cpuset=None, after_start=after_start, after_start_records=[])


def _replay_fakes(monkeypatch, log, seen):
    def fake_up(ctx, feed, rd, label, header=None):
        rd.mkdir(parents=True, exist_ok=True)
        stack.start(ctx, attr.DATABROKER, feed, rd, label)
        return {"feed": feed, "listeners_before": {}, "listeners": {"ok": True}}

    def listeners_now(info, feed, suffix, allowed=()):
        info["listeners" + suffix] = {"ok": True}

    monkeypatch.setattr(stack, "docker", OrderDocker(log))
    for name, fn in (("up", fake_up), ("listeners_now", listeners_now), ("wait_log", lambda *a, **kw: None),
                     ("wait_for", lambda *a, **kw: None), ("stop_containers", lambda ctx: None), ("collect", lambda rd: {}),
                     ("remove_stack", lambda: seen.append("remove")), ("analyse", lambda ctx, rd: {}),
                     ("record_close", lambda header, rd, console=None: ("C12b", True, "synthetic"))):
        monkeypatch.setattr(stack, name, fn)
    monkeypatch.setattr(stack, "VCAN_READY_S", 0.0)
    for name, fn in (("check_recording", lambda header, sha, dbc: ("C10", True, "synthetic")), ("run_rows", lambda rows, ids: []),
                     ("check_images", lambda rows, running: ("C8", True, "synthetic")), ("render_markdown", lambda h, r: "")):
        monkeypatch.setattr(attr, name, fn)


def test_a_replay_carries_its_own_hook_records_in_start_order_and_a_failing_hook_stops_it_and_removes_the_stack(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    env, _script, log = _hook(tmp_path, monkeypatch)
    seen: List[str] = []
    _replay_fakes(monkeypatch, log, seen)
    ctx = _replay_ctx(tmp_path, shlex.split(env))
    order = [stack.NAMES[attr.DATABROKER], stack.NAMES[attr.CAN_PROVIDER]]
    for k in (1, 2):
        r = stack.replay_once(ctx, "dumpfile", "dumpfile-%d" % k)
        assert [h["container"] for h in r["after_start"]] == order and all(h["exit"] == 0 for h in r["after_start"]), "its own records only"
        on_disk = json.loads((ctx.run_dir / ("dumpfile-%d" % k) / "result.json").read_text(encoding="utf-8"))
        assert on_disk["after_start"] == r["after_start"]
    assert log.read_text(encoding="utf-8").splitlines() == ["docker run %s" % n if j % 2 == 0 else "hook %s" % n
                                                            for _k in (1, 2) for n in order for j in (0, 1)]
    # without a hook the result carries no record and no key
    r = stack.replay_once(_replay_ctx(tmp_path / "n", None), "dumpfile", "dumpfile-1")
    assert "after_start" not in r
    # a failing hook stops the replay as a failed start does: the stack is removed, and no result.json is written
    del seen[:]
    monkeypatch.setenv("SDV_TEST_HOOK_MODE", "fail")
    with pytest.raises(stack.StackError, match=stack.NAMES[attr.DATABROKER]):
        stack.replay_once(ctx, "dumpfile", "dumpfile-3")
    assert seen == ["remove"] and not (ctx.run_dir / "dumpfile-3" / "result.json").exists()


def _step3():
    """sdv/stack/step3.py, which builds on this module (its tests are tests/test_sdv_step3.py's; here only what it carries of
    the stack's hook)."""
    if str(STACK_DIR) not in sys.path:
        sys.path.insert(0, str(STACK_DIR))
    return importlib.import_module("step3")


def test_step3_carries_the_hook_records_into_result_json_and_a_failing_hook_fails_the_run_naming_the_bridge(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    step3 = _step3()
    env, _script, log = _hook(tmp_path, monkeypatch)

    class Halt(Exception):
        pass

    def drive_replay(plan, ops):
        raise Halt()

    for name, fn in (("remove_stack", lambda: None), ("host_listeners", lambda: {"with_owners": True, "sockets": []}),
                     ("start_monitor", lambda ctx, rd, info: None), ("collect", lambda rd: {}),
                     ("listeners_now", lambda info, feed, suffix, allowed=(): info.__setitem__("listeners" + suffix, {"ok": True}))):
        monkeypatch.setattr(stack, name, fn)
    monkeypatch.setattr(stack, "VCAN_READY_S", 0.0)
    monkeypatch.setattr(step3, "drive_replay", drive_replay)
    monkeypatch.setattr(attr, "check_recording", lambda header, sha, dbc: ("C10", True, "synthetic"))
    plan = {"mode": "replay", "spec": "s", "run": "to_end", "events_file": None, "script": {"format": 1, "steps": []}}

    def ctx_for(name):
        return types.SimpleNamespace(
            bridge="replay", run_dir=tmp_path / "runs" / name, run_header=lambda rid, feed: {"run_id": rid},
            check_header=lambda h: ("C12a", True, "synthetic"), staged={"sigsim.log": "ab" * 32}, scenario={"dbc_sha256": "x"}, rows=[],
            manifest={"scenario_checks": []}, components={attr.BRIDGE: {"image_id": BRIDGE_IMG}, stack.VSS_MONITOR: {"sha256": "0" * 64}},
            image_ids=lambda: {attr.BRIDGE: BRIDGE_IMG}, monitor_mode="native", monitor=None, guest=None, in_dir=tmp_path / "in",
            images=IMAGES, cpuset=None, after_start=shlex.split(env), after_start_records=[])

    ctx = ctx_for("ok")
    for mode, raised, run_id in (("ok", Halt, "s-replay-1"), ("ok", Halt, "s-replay-2"), ("fail", stack.StackError, "s-replay-3")):
        monkeypatch.setenv("SDV_TEST_HOOK_MODE", mode)
        rd = ctx.run_dir / run_id
        monkeypatch.setattr(stack, "docker", OrderDocker(log, bridge_dir=rd / "bridge"))
        with pytest.raises(raised) as e:
            step3.run_one(ctx, plan, run_id)
        if mode == "fail":
            assert stack.BRIDGE_CONTAINER in str(e.value) and "SDV_AFTER_START" in str(e.value)
        (rec,) = json.loads((rd / "result.json").read_text(encoding="utf-8"))["after_start"]          # this run's record only
        assert rec["container"] == stack.BRIDGE_CONTAINER and rec["exit"] == (0 if mode == "ok" else 3), rec
    # a context with no hook writes no record and no key
    monkeypatch.setenv("SDV_TEST_HOOK_MODE", "ok")
    ctx = ctx_for("none")
    ctx.after_start = None
    rd = ctx.run_dir / "s-replay-1"
    monkeypatch.setattr(stack, "docker", OrderDocker(log, bridge_dir=rd / "bridge"))
    with pytest.raises(Halt):
        step3.run_one(ctx, plan, "s-replay-1")
    assert "after_start" not in json.loads((rd / "result.json").read_text(encoding="utf-8"))


def test_step3_keeps_the_hook_key_with_no_record_when_a_run_stops_before_its_first_container(tmp_path, monkeypatch):
    step3 = _step3()
    env, _script, log = _hook(tmp_path, monkeypatch)

    def no_listeners():
        raise stack.StackError("synthetic: the listeners could not be read")

    for name, fn in (("remove_stack", lambda: None), ("host_listeners", no_listeners), ("collect", lambda rd: {})):
        monkeypatch.setattr(stack, name, fn)
    monkeypatch.setattr(attr, "check_recording", lambda header, sha, dbc: ("C10", True, "synthetic"))
    plan = {"mode": "replay", "spec": "s", "run": "to_end", "events_file": None, "script": {"format": 1, "steps": []}}
    ctx = types.SimpleNamespace(
        bridge="replay", run_dir=tmp_path / "runs" / "e", run_header=lambda rid, feed: {"run_id": rid},
        check_header=lambda h: ("C12a", True, "synthetic"), staged={"sigsim.log": "ab" * 32}, scenario={"dbc_sha256": "x"}, rows=[],
        manifest={"scenario_checks": []}, components={attr.BRIDGE: {"image_id": BRIDGE_IMG}, stack.VSS_MONITOR: {"sha256": "0" * 64}},
        image_ids=lambda: {attr.BRIDGE: BRIDGE_IMG}, monitor_mode="native", monitor=None, guest=None, in_dir=tmp_path / "in",
        images=IMAGES, cpuset=None, after_start=shlex.split(env), after_start_records=[])
    with pytest.raises(stack.StackError, match="synthetic"):
        step3.run_one(ctx, plan, "s-replay-1")
    assert json.loads((ctx.run_dir / "s-replay-1" / "result.json").read_text(encoding="utf-8"))["after_start"] == []
    assert not log.exists(), "no container started, so no hook ran"


# --- SDV Phase 6 WP2: the app's image identity, the app outside the stack, host spool and status, the marker ---------
# spec.md 2.1, 2.2, 2.7 and section 4 items 5-9. Against a replaced docker and synthetic contexts: nothing here starts a
# container, writes under /run or reads this host's own marker (the autouse fixture above points the variable elsewhere).
COMMON_PHASE1 = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-opt", "max-size=10m", "--memory", "512m",
                 "--memory-swap", "512m"]


def _phase6_ctx(tmp_path, **over):
    """A context with every image start() needs, the app's config digest among them, a broker bridge and a connector."""
    ids = {attr.APP: IMG, attr.RECORDER: REC_IMG, attr.BRIDGE: BRIDGE_IMG, stack.CONNECTOR: CONNECTOR_IMG}
    kw: Dict[str, Any] = dict(images=IMAGES, image_ids=lambda: ids, in_dir=tmp_path / "in", recorded=["Vehicle.Speed", hazard.HAZARD],
                              witness_paths=sorted(WITNESS_PATHS), bridge="broker", monitor=None, monitor_mode="native", guest=None,
                              connector=True, components={attr.APP: {"image_id": IMG, "config_digest": APP_CFG}})
    kw.update(over)
    return types.SimpleNamespace(**kw)


def test_the_common_flags_are_phase_1s_word_for_word():
    assert stack.COMMON == COMMON_PHASE1


def test_every_containers_argv_is_written_out_and_the_apps_alone_changed_in_phase_6(tmp_path, monkeypatch):
    """Spec section 4 items 8 and 9: COMMON and every other container's argument vector are what they were; the app's
    changed, deliberately, in one place: APP_IMAGE_ID is the app's config digest, and the image still runs by its store ID."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    runs: Dict[str, List[str]] = {}
    current = [""]

    def fake(*args, **_kw):
        if args[:1] == ("run",):
            runs["%s:%s" % (current[0], args[args.index("--name") + 1])] = list(args)
        return subprocess.CompletedProcess(list(args), 0, "", "")

    monkeypatch.setattr(stack, "docker", fake)
    device = _device_dir(tmp_path, monkeypatch)
    ctx = _phase6_ctx(tmp_path)
    rd = tmp_path / "r"
    for d in ("bridge", "spool", "status"):
        (rd / d).mkdir(parents=True)
    (rd / "scenario.lock").touch()
    (rd / "bridge-header.json").write_text("{}", encoding="utf-8")
    for feed in stack.FEEDS:
        current[0] = feed
        for comp in stack.NAMES:
            stack.start(ctx, comp, feed, rd, "test/run")
    current[0] = "vcan"
    stack.start(ctx, attr.BRIDGE, "vcan", rd, "test/run")
    stack.start(ctx, stack.CONNECTOR, "vcan", rd, "test/run")
    uid, ins, out = "%d:%d" % (os.getuid(), os.getgid()), "%s:/in:ro" % ctx.in_dir, "%s:/out" % rd
    want: Dict[str, List[str]] = {}
    for feed in stack.FEEDS:
        def head(name: str, feed: str = feed) -> List[str]:
            net = (["--network", "host"] if feed == "vcan" else ["--network", "none"] if name == "sdv-stack-databroker"
                   else ["--network", "container:sdv-stack-databroker"])
            return ["run", "-d", "--name", name, "--label", "sdv.stack.run=test/run"] + COMMON_PHASE1 + net

        want[feed + ":sdv-stack-databroker"] = head("sdv-stack-databroker") + [
            "--read-only", "-e", "KUKSA_DATABROKER_ADDR=127.0.0.1", "-v", ins, stack.upstream_ref(IMAGES, attr.DATABROKER),
            "--vss", "/in/vss-databroker.json", "--address", "127.0.0.1", "--port", "55555", "--insecure"]
        want[feed + ":sdv-stack-mock-provider"] = head("sdv-stack-mock-provider") + [
            "-e", "VDB_ADDRESS=127.0.0.1:55555", "-e", "MOCK_ADDR=127.0.0.1:50053", "-v", "%s:/mock/mock.py:ro" % stack.MOCK_FILE,
            stack.upstream_ref(IMAGES, attr.MOCK_PROVIDER)]
        want[feed + ":sdv-stack-recorder"] = head("sdv-stack-recorder") + [
            "--read-only", "--user", uid, "-v", out, REC_IMG, "-a", "127.0.0.1", "-p", "55555", "-f", "/out/vss-recorder.csv", "-l", "INFO",
            "-s", "Vehicle.Speed", hazard.HAZARD]
        want[feed + ":sdv-stack-witness"] = head("sdv-stack-witness") + [
            "--read-only", "--user", uid, "-v", out, "-v", "%s:/witness.py:ro" % stack.WITNESS_FILE, "--entrypoint", "python", REC_IMG,
            "/witness.py", "127.0.0.1:55555", "/out/vss-witness.jsonl"] + sorted(WITNESS_PATHS)
        want[feed + ":sdv-stack-app"] = head("sdv-stack-app") + [
            "--read-only", "--user", uid, "-v", out, "-e", "APP_IMAGE_ID=" + APP_CFG, "-e", "KUKSA_ADDRESS=127.0.0.1:55555",
            "-e", "HBH_LOG=/out/hard-brake-hazard.jsonl", IMG]
        want[feed + ":sdv-stack-can-provider"] = head("sdv-stack-can-provider") + [
            "--read-only", "--tmpfs", "/tmp:rw,exec,size=256m", "-v", ins, stack.upstream_ref(IMAGES, attr.CAN_PROVIDER),
            "grpc://127.0.0.1:55555", "--config", "/in/can-provider.ini", "--dbcfile", "/in/slice.dbc", "--mapping",
            "/in/vss-can-mapping.json", "--dbc2val", "--no-val2dbc", "--no-infinite"] + (
            ["--dumpfile", "/in/sigsim.log", "--canport", "vcan0"] if feed == "dumpfile" else ["--use-socketcan", "--canport", "vcan0"])
    host = ["--label", "sdv.stack.run=test/run"] + COMMON_PHASE1 + ["--network", "host"]
    want["vcan:sdv-stack-bridge"] = ["run", "-d", "--name", "sdv-stack-bridge"] + host + [
        "--read-only", "--user", uid, "--mount", "type=bind,src=%s,dst=/run/lock/sdv-scenario.lock" % (rd / "scenario.lock"),
        "-v", "%s:/out" % (rd / "bridge"), "-v", "%s:/header.json:ro" % (rd / "bridge-header.json"), BRIDGE_IMG, "run", "--host",
        "127.0.0.1", "--port", "7160", "--header", "/header.json", "--broker", "127.0.0.1:55555", "--out", "/out"]
    want["vcan:sdv-stack-connector"] = ["run", "-d", "--name", "sdv-stack-connector"] + host + [
        "--read-only", "--user", uid, "--restart", "no", "--mount", "type=bind,src=%s,dst=/run/sdv-local/spool/v1" % (rd / "spool"),
        "--mount", "type=bind,src=%s,dst=/run/sdv-local/status/v1,readonly" % (rd / "status"),
        "--mount", "type=bind,src=%s,dst=/run/sdv-local/device,readonly" % device, "--env-file", str(device / "connector.env"), CONNECTOR_IMG]
    assert sorted(runs) == sorted(want)
    assert [k for k in sorted(want) if runs[k] != want[k]] == [], "an argument vector differs from the one written out"


@pytest.mark.parametrize("components", [
    {}, {attr.APP: {"image_id": IMG}}, {attr.APP: {"image_id": IMG, "config_digest": None}},
    {attr.APP: {"image_id": IMG, "config_digest": "sha256:" + "FE" * 32}}, {attr.APP: {"image_id": IMG, "config_digest": APP_CFG[:-1]}},
    {attr.APP: {"image_id": IMG, "config_digest": "fe" * 32}},
])
def test_the_app_is_never_started_without_a_proved_config_digest(tmp_path, monkeypatch, components):
    calls: List[Any] = []
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    with pytest.raises(stack.StackError, match="config digest"):
        stack.start(_phase6_ctx(tmp_path, components=components), attr.APP, "vcan", tmp_path / "r", "test/run")
    assert calls == []


def _oci_blobs(media: str = "application/vnd.oci.image.manifest.v1+json") -> Any:
    """A synthetic image as a save stream holds it: (the manifest's digest, the config's digest, {digest: blob})."""
    config = json.dumps({"architecture": "amd64", "os": "linux", "rootfs": {"type": "layers", "diff_ids": []}}, sort_keys=True).encode()
    cfg = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = json.dumps({"schemaVersion": 2, "mediaType": media, "layers": [],
                           "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": cfg, "size": len(config)}},
                          sort_keys=True).encode()
    man = "sha256:" + hashlib.sha256(manifest).hexdigest()
    return man, cfg, {man: manifest, cfg: config}


def _save_stream(blobs: Dict[str, bytes]) -> Any:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        members = [("oci-layout", b'{"imageLayoutVersion": "1.0.0"}')] + [("blobs/sha256/" + d.split(":", 1)[1], b) for d, b in blobs.items()]
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


def test_the_config_digest_is_read_from_a_save_stream_with_the_manifest_and_the_config_hash_checked_and_an_index_refused():
    for media in ("application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"):
        man, cfg, blobs = _oci_blobs(media)
        assert stack.config_digest_from_save(_save_stream(blobs), man) == cfg
    man, cfg, blobs = _oci_blobs()
    index = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                        "manifests": [{"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": man, "size": len(blobs[man])}]}).encode()
    idx = "sha256:" + hashlib.sha256(index).hexdigest()
    cases = [(dict(blobs, **{idx: index}), idx, "single-platform"),                                  # the store ID names an index
             ({man: blobs[man] + b" ", cfg: blobs[cfg]}, man, "does not hash"),                       # the manifest is not its ID's
             ({man: blobs[man], cfg: blobs[cfg] + b" "}, man, "does not hash"),                       # the config is not its digest's
             ({man: blobs[man]}, man, "no blob"), ({cfg: blobs[cfg]}, man, "no blob")]
    for b, sid, why in cases:
        with pytest.raises(stack.StackError, match="config digest") as e:
            stack.config_digest_from_save(_save_stream(b), sid)
        assert why in str(e.value), str(e.value)


def _no_popen(*args: Any, **_kw: Any) -> Any:
    raise AssertionError("a process was opened past the stack's docker seams: %s" % (args[:1],))


def test_saved_config_digest_runs_docker_save_of_the_store_id_and_refuses_a_save_that_failed(monkeypatch):
    man, cfg, blobs = _oci_blobs()
    seen: List[List[str]] = []
    code = [0]
    streamed = [blobs]

    class FakeSave:
        def __init__(self, args):
            seen.append(list(args))
            self.stdout, self.stderr = _save_stream(streamed[0]), io.BytesIO(b"Error response from daemon: a synthetic failure")

        def wait(self, timeout=None):
            return code[0]

        def kill(self):
            raise AssertionError("an expected outcome killed the save")

    monkeypatch.setattr(stack.subprocess, "Popen", _no_popen)
    monkeypatch.setattr(stack, "docker_stream", lambda *args: FakeSave(args), raising=False)
    assert stack.saved_config_digest(man) == cfg and seen == [["save", man]]
    code[0] = 1
    with pytest.raises(stack.StackError, match="docker save"):
        stack.saved_config_digest(man)
    code[0] = 0
    streamed[0] = {cfg: blobs[cfg]}          # a save that exited 0 whose stream proves nothing (no manifest blob) gives no digest
    with pytest.raises(stack.StackError, match="config digest"):
        stack.saved_config_digest(man)


def test_saved_config_digest_drains_the_save_before_it_reads_its_stderr(monkeypatch):
    """A stream config_digest_from_save gives up on (here no tar at all, so it stops after its first block) is still read
    to its end before the save's stderr is: a real save still writing into a pipe nobody drains would block that read,
    and the wait after it."""

    class Drained(io.BytesIO):
        at_eof = False

        def read(self, n=-1):
            chunk = super().read(n)
            if not chunk:
                self.at_eof = True
            return chunk

    class FakeSave:
        def __init__(self, args):
            self.stdout, self.stderr = Drained(b"not a tar" * 200000), self

        def read(self, _n=-1):
            assert self.stdout.at_eof, "the save's stderr was read before its stdout was drained: a real save would block here"
            return b""

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("an expected outcome killed the save")

    monkeypatch.setattr(stack.subprocess, "Popen", _no_popen)
    monkeypatch.setattr(stack, "docker_stream", lambda *args: FakeSave(args), raising=False)
    with pytest.raises(stack.StackError, match="no tar"):
        stack.saved_config_digest("sha256:" + "ab" * 32)


def test_saved_config_digest_opens_docker_save_through_the_stacks_own_seam_which_every_test_replaces(monkeypatch):
    """Every docker call of stack.py goes through a seam the tests replace: docker() for a command that ends, docker_stream()
    for the one stream read as it comes (build mode's `docker save`). saved_config_digest opens no process itself, and a test
    that reaches it without a fake of its own fails at the autouse fixture's stand-in instead of asking the daemon."""
    monkeypatch.setattr(stack.subprocess, "Popen", _no_popen)
    with pytest.raises(AssertionError, match="without a fake of its own"):
        stack.saved_config_digest("sha256:" + "ab" * 32)
    assert REAL_DOCKER_STREAM is not None, "stack.py has no docker_stream seam"
    opened: List[Any] = []
    monkeypatch.setattr(stack.subprocess, "Popen", lambda argv, **kw: opened.append((list(argv), kw)) or "a process")
    assert REAL_DOCKER_STREAM("save", IMG) == "a process"          # the seam: docker and its arguments, both streams piped
    assert opened == [(["docker", "save", IMG], {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE})]


def test_saved_config_digest_kills_the_save_when_its_reader_fails_unexpectedly_so_no_pipe_read_blocks(monkeypatch):
    """An error nobody expected while the stream is read (sdv/arm64/a64scan.py that cannot be read: OSError; an interrupt)
    leaves the save writing into a pipe nobody drains, and reading its stderr to the end would then wait for ever, before
    the bounded wait. The save is killed first, and the error goes on as it was."""
    man, _cfg, blobs = _oci_blobs()

    class StillWriting:
        killed = False

        def __init__(self):
            self.stdout, self.stderr = _save_stream(blobs), self

        def read(self, _n=-1):
            if not self.killed:
                raise AssertionError("the save's stderr was read to its end while it still writes into an undrained pipe: this blocks")
            return b""

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return -9 if self.killed else 0

    proc = StillWriting()
    monkeypatch.setattr(stack.subprocess, "Popen", _no_popen)
    monkeypatch.setattr(stack, "docker_stream", lambda *args: proc, raising=False)

    def unreadable() -> Any:
        raise OSError(13, "synthetic: a64scan.py cannot be read")
    monkeypatch.setattr(stack, "_a64scan", unreadable)
    with pytest.raises(OSError, match="synthetic: a64scan.py cannot be read"):
        stack.saved_config_digest(man)
    assert proc.killed


def test_build_mode_proves_the_apps_config_digest_after_its_build_and_keeps_it_beside_its_store_id(tmp_path, monkeypatch):
    built: Dict[str, str] = {}

    def fake(*args, check=True, timeout=None):
        if args[:1] == ("build",):
            tag = args[args.index("-t") + 1]
            built[tag] = "sha256:" + hashlib.sha256(tag.encode()).hexdigest()
        out = built.get(args[-1], "") if args[:2] == ("image", "inspect") else ""
        return subprocess.CompletedProcess(list(args), 0, out + "\n", "")

    monkeypatch.setattr(stack, "docker", fake)
    monkeypatch.setattr(stack, "fetch_recorder_source", lambda images: tmp_path)
    proved: List[str] = []
    monkeypatch.setattr(stack, "saved_config_digest", lambda sid: proved.append(sid) or APP_CFG)
    out = stack.build_local(IMAGES)
    app = built[IMAGES["local"][attr.APP]["tag"]]
    assert out[attr.APP]["image_id"] == app and out[attr.APP]["config_digest"] == APP_CFG and proved == [app]
    assert "config_digest" not in out[attr.RECORDER]

    def unproved(sid):
        raise stack.StackError("synthetic: no config digest proved for %s" % sid)
    monkeypatch.setattr(stack, "saved_config_digest", unproved)
    with pytest.raises(stack.StackError, match="synthetic: no config digest"):
        stack.build_local(IMAGES)


def test_loaded_mode_starts_the_app_by_its_pinned_id_with_its_pinned_config_digest(loaded_rig, monkeypatch, tmp_path):
    ctx, man = _prepare_loaded(loaded_rig, "a")
    pin = IMAGES["local"][attr.APP]["arm64"]
    assert (man["components"][attr.APP]["image_id"], man["components"][attr.APP]["config_digest"]) == (pin["id"], pin["config_digest"])
    runs: List[List[str]] = []
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: runs.append(list(a)) or subprocess.CompletedProcess(a, 0, "", ""))
    stack.start(ctx, attr.APP, "vcan", tmp_path / "r", "test/run")
    (app,) = runs
    assert "APP_IMAGE_ID=" + pin["config_digest"] in app and "APP_IMAGE_ID=" + pin["id"] not in app and app[-1] == pin["id"]


def _up_fakes(monkeypatch, order, waited):
    monkeypatch.setattr(stack, "remove_stack", lambda: None)
    monkeypatch.setattr(stack, "host_listeners", lambda: {"with_owners": True, "sockets": []})
    monkeypatch.setattr(stack, "ensure_vcan", lambda: {"created": False})
    monkeypatch.setattr(stack, "start", lambda ctx, comp, feed, rd, label: order.append(comp))
    monkeypatch.setattr(stack, "wait_log", lambda name, pattern, timeout: waited.append(name))
    monkeypatch.setattr(stack, "wait_for", lambda pred, timeout, what, poll=0.2: waited.append(what))
    monkeypatch.setattr(stack, "start_bridge", lambda ctx, feed, rd, label, header: order.append("bridge"))
    monkeypatch.setattr(stack, "start_monitor", lambda ctx, rd, info: order.append("monitor"))
    monkeypatch.setattr(stack, "listeners_now", lambda info, feed, suffix, al=(): order.append("listeners"))
    monkeypatch.setattr(stack, "connector_checks", lambda ctx, feed: order.append("checks"))
    monkeypatch.setattr(stack, "start_connector", lambda ctx, feed, rd, label: order.append("connector"))


def test_up_with_an_external_app_starts_every_container_but_the_app_and_waits_for_no_app(tmp_path, monkeypatch):
    order: List[str] = []
    waited: List[str] = []
    _up_fakes(monkeypatch, order, waited)
    parts = [attr.DATABROKER, attr.MOCK_PROVIDER, attr.RECORDER, stack.WITNESS]
    for bridge in ("none", "broker"):
        del order[:], waited[:]
        b = bridge != "none"
        header = {"bridge_mode": bridge} if b else None
        stack.up(_phase6_ctx(tmp_path, bridge=bridge, app="external"), "vcan", tmp_path / ("u-" + bridge), "x/u", header)
        assert order == ["checks"] + ["monitor"] * b + parts + ["bridge"] * b + ["connector", "listeners"]
        assert waited == [stack.NAMES[attr.DATABROKER], stack.NAMES[attr.MOCK_PROVIDER],
                          "the recorder's first rows (the hazard light's initial value, the wheelbase)", "the witness's subscription"], waited
    # the stack's own app, by name and in a context that names no app mode (Phase 1's, step3.py's), as before
    for ctx in (_phase6_ctx(tmp_path, bridge="none", app="stack"), types.SimpleNamespace(bridge="none", monitor=None, monitor_mode="native")):
        del order[:], waited[:]
        stack.up(ctx, "vcan", tmp_path / "s", "x/s", None)
        assert attr.APP in order and [w for w in waited if "the app's" in w]
    # an external app on the dumpfile feed would sit on the host's network beside a databroker it cannot reach: refused
    # before anything is started, removed or made

    def touched(*_a, **_kw):
        raise AssertionError("the stack went on though the run was to be refused")
    for name in ("remove_stack", "host_listeners", "ensure_vcan", "start", "wait_log", "wait_for", "connector_checks"):
        monkeypatch.setattr(stack, name, touched)
    with pytest.raises(stack.StackError, match="--app external needs --feed vcan"):
        stack.up(_phase6_ctx(tmp_path, bridge="none", connector=False, app="external"), "dumpfile", tmp_path / "d", "x/d", None)
    assert not (tmp_path / "d").exists()


def test_main_hands_app_external_to_the_context_on_up_only_and_only_with_the_vcan_feed(tmp_path, monkeypatch):
    seen: List[Any] = []

    class Stop(Exception):
        pass

    class FakeContext:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs)

        def prepare(self, images="build"):
            raise Stop()

    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "Context", FakeContext)
    for i, (args, kw) in enumerate(((["up", "--feed", "vcan", "--app", "external"], {"app": "external"}),
                                    (["up", "--feed", "vcan", "--app", "stack"], {}), (["up", "--feed", "vcan"], {}),
                                    (["up", "--feed", "vcan", "--app", "external", "--connector"], {"connector": True, "app": "external"}))):
        with pytest.raises(Stop):
            stack.main(args + ["--name", "n%d" % i])
        assert seen[-1] == kw, args
    n = len(seen)
    for args in (["up", "--app", "external"], ["up", "--feed", "dumpfile", "--app", "external"]):
        with pytest.raises(stack.StackError, match="--app external needs --feed vcan"):
            stack.main(args + ["--name", "d"])
    assert len(seen) == n and not (tmp_path / "runs").exists()
    for cmd in ("replay", "exit-test", "prepare", "loadcheck", "ageprobe", "wheelbaseprobe"):          # their gates read the app
        with pytest.raises(SystemExit):
            stack.main([cmd, "--app", "external", "--name", "x"])
    with pytest.raises(SystemExit):
        stack.main(["up", "--feed", "vcan", "--app", "updater", "--name", "x"])


class StackDocker:
    """stack.docker replaced by a small model of the daemon's containers (SDV Phase 6, the CAN-provider fix); no docker
    command runs. `run -d --name N --label sdv.stack.run=L ...` makes N, running, with that label; `ps` lists by --filter
    label=KEY or label=KEY=VALUE (-a: every container, else the running ones; the IDs of -q are the names here, as are
    --format {{.Names}}'s); `rm -f` removes; `inspect -f {{.State.Running}} N` says whether N runs (exit 1 when there is no
    N); `logs N` gives N's line. can, what the CAN provider does: "ready" logs its ready line; "silent" logs an earlier line
    and never its ready line; "stops" ends before its ready line; "fails" is created and its start fails as docker run's
    does; "interrupted": the wait for its ready line is cut by an interrupt (KeyboardInterrupt from its `logs`); "hangs": its
    `logs` runs past docker()'s timeout (subprocess.TimeoutExpired, as subprocess.run raises it). Every run
    goes into `events` too, which the fakes of _up_main add to, so the list holds what happened in its order."""

    LINES = {"sdv-stack-databroker": "INFO databroker: Listening on 127.0.0.1:55555",
             "sdv-stack-mock-provider": "INFO mock: Feeding 'Vehicle.Body.Lights.Hazard.IsSignaling' with value False",
             "sdv-stack-can-provider": "INFO dbcfeeder: Starting to receive CAN messages"}
    EARLIER = "INFO dbcfeeder: Reading DBC file /in/slice.dbc"

    def __init__(self, can: str = "ready") -> None:
        self.can = can
        self.containers: Dict[str, Dict[str, Any]] = {}
        self.calls: List[List[str]] = []
        self.events: List[str] = []
        self.run_dir: Any = None          # the run directory main made (_up_main sets it, whether main returned or raised)
        self.snapshot_feeds: List[str] = []          # the feed of every listener snapshot, in order (_up_main's listeners_now)

    def __call__(self, *args: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        a = list(args)
        self.calls.append(a)
        out, code = "", 0
        can_name = stack.NAMES[attr.CAN_PROVIDER]
        if a[:1] == ["run"]:
            name = a[a.index("--name") + 1]
            is_can = name == can_name
            self.events.append("run " + name)
            line = self.EARLIER if is_can and self.can != "ready" else self.LINES.get(name, "")
            self.containers[name] = {"label": a[a.index("--label") + 1], "running": not (is_can and self.can in ("stops", "fails")),
                                     "line": line}
            if is_can and self.can == "fails":
                raise stack.StackError("docker run -d --name failed (125): docker: Error response from daemon: a synthetic failure to start")
        elif a[:1] == ["ps"]:
            out = "".join(n + "\n" for n in self.listed(a))
        elif a[:2] == ["rm", "-f"]:
            for n in a[2:]:
                self.containers.pop(n, None)
        elif a[:1] == ["inspect"]:
            c = self.containers.get(a[-1])
            out, code = ("true" if c["running"] else "false", 0) if c is not None else ("", 1)
        elif a[:1] == ["logs"]:
            if a[-1] == can_name and self.can == "interrupted":
                raise KeyboardInterrupt()
            if a[-1] == can_name and self.can == "hangs":
                raise subprocess.TimeoutExpired(["docker", "logs"], 60)
            c = self.containers.get(a[-1])
            out, code = (c["line"] + "\n", 0) if c is not None else ("", 1)
        return subprocess.CompletedProcess(a, code, out, "")

    def listed(self, a: List[str]) -> List[str]:
        every = any(x in ("-a", "-aq", "-qa") for x in a)
        want = a[a.index("--filter") + 1][len("label="):] if "--filter" in a else None
        out = []
        for name, c in self.containers.items():
            key = c["label"].split("=", 1)[0]
            if (every or c["running"]) and (want is None or want == (c["label"] if "=" in want else key)):
                out.append(name)
        return out

    def runs(self) -> List[List[str]]:
        return [c for c in self.calls if c[:1] == ["run"]]


UP_FILE_WAITS = ("the recorder's first rows", "the witness's subscription", "the app's subscription")      # up()'s waits on files
UP_VCAN_READY_S = 0.0123          # a synthetic VCAN_READY_S, so the sleep before the feed snapshot is told apart in the events


def _up_main(tmp_path, monkeypatch, fake, *extra):
    """stack.main(["up", "--feed", "vcan", "--name", "u", *extra]) with up() and start() as they are, against `fake` (a
    StackDocker). The context is a test's (_phase6_ctx: no bridge, no connector, the app mode main hands it); only what reaches
    past docker is replaced: the host's listeners (a fixed verdict per snapshot, its suffix kept in fake.events: "_up" for
    up()'s own), vcan0, the waits on the files the recorder, the witness and the app write, and the module's sleep (each kept
    in fake.events). wait_log runs as it is, each call kept in fake.events, under a START_TIMEOUT_S of 0.6 s. Returns main's
    exit status and the run directory."""
    _placement_env(monkeypatch)
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    made: List[Any] = []

    def context(run_dir, seed, bridge, **kw):
        made.append(_phase6_ctx(tmp_path, bridge=bridge, connector=bool(kw.get("connector")), app=kw.get("app", "stack"),
                                run_dir=run_dir, prepare=lambda images="build": None))
        return made[-1]

    real_wait_for, real_wait_log = stack.wait_for, stack.wait_log

    def wait_for(pred, timeout, what, poll=0.2):
        if what.startswith(UP_FILE_WAITS):
            fake.events.append("waited for " + what)
            return
        real_wait_for(pred, timeout, what, poll)

    def wait_log(name, pattern, timeout):
        fake.events.append("wait_log %s /%s/ %g" % (name, pattern, timeout))
        real_wait_log(name, pattern, timeout)

    def listeners_now(info, feed, suffix, allowed=()):
        fake.events.append("listeners" + (suffix or "_up"))
        fake.snapshot_feeds.append(feed)
        info["listeners" + suffix] = {"ok": suffix != "_feed", "snapshot": suffix or "up"}

    def sleep(seconds):
        fake.events.append("sleep %g" % seconds)
        time.sleep(seconds)

    clock = {k: getattr(time, k) for k in dir(time) if not k.startswith("__")}
    clock["sleep"] = sleep
    for name, fn in (("Context", context), ("docker", fake), ("host_listeners", lambda: {"with_owners": True, "sockets": []}),
                     ("ensure_vcan", lambda: {"created": False}), ("wait_for", wait_for), ("wait_log", wait_log),
                     ("listeners_now", listeners_now), ("time", types.SimpleNamespace(**clock)),
                     ("VCAN_READY_S", UP_VCAN_READY_S), ("START_TIMEOUT_S", 0.6)):
        monkeypatch.setattr(stack, name, fn)
    try:
        rc = stack.main(["up", "--feed", "vcan", "--name", "u"] + list(extra))
    finally:
        fake.run_dir = made[0].run_dir if made else None
    return rc, made[0].run_dir


def _drill(monkeypatch):
    """sdv/drill/drill.py, imported by its file under a name of this module's own and read only: its import puts the
    connector's directory on sys.path and sets dont_write_bytecode, and both are put back after the test."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
    spec = importlib.util.spec_from_file_location("stack_tests_drill", REPO / "sdv" / "drill" / "drill.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CAN_READY_WAIT = "wait_log sdv-stack-can-provider /Starting to receive CAN messages|Using DBC reader/ 0.6"
UP_FOUR = ["sdv-stack-databroker", "sdv-stack-mock-provider", "sdv-stack-recorder", "sdv-stack-witness"]


@pytest.mark.parametrize("images", [[], ["--images", "build"], ["--images", "loaded"]])
def test_up_with_an_external_app_starts_the_can_provider_after_up_with_the_runs_up_label_and_waits_for_its_ready_line(
        tmp_path, monkeypatch, capsys, images):
    """The CAN-provider fix, spec section 2 items 1 and 5 and section 3's first case: `up --feed vcan --app external` starts
    every container but the app, then, once up() has returned (after its listener snapshot, so after the witness), the CAN
    provider exactly as start() starts it for live (the same argument vector, the run's `<run>/up` label), waits for its
    ready line with live's pattern and START_TIMEOUT_S, sleeps VCAN_READY_S, takes the `_feed` snapshot and writes it with
    up's listener record (up/listeners.json). The printed record and the "stack running" line stay; a line names the CAN
    provider as started. The container list drill.py run reads (its own label and names, imported) then holds it."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = StackDocker()
    rc, run_dir = _up_main(tmp_path, monkeypatch, fake, "--app", "external", *images)
    assert rc == 0
    can = stack.NAMES[attr.CAN_PROVIDER]
    label = "%s=%s/up" % (stack.LABEL, run_dir.name)
    assert [e[4:] for e in fake.events if e.startswith("run ")] == UP_FOUR + [can], fake.events
    tail = fake.events[fake.events.index("listeners_up"):]
    assert tail == ["listeners_up", "run " + can, CAN_READY_WAIT, "sleep %g" % UP_VCAN_READY_S, "listeners_feed"], tail
    runs = {r[r.index("--name") + 1]: r for r in fake.runs()}
    assert all(r[r.index("--label") + 1] == label for r in runs.values()), "every container carries the run's /up label"
    twin = StackDocker()          # the argument vector start() builds for the CAN provider on the vcan feed, as live's start
    monkeypatch.setattr(stack, "docker", twin)
    stack.start(_phase6_ctx(tmp_path, bridge="none", connector=False, app="external"), attr.CAN_PROVIDER, "vcan", run_dir / "up",
                "%s/up" % run_dir.name)
    assert runs[can] == twin.runs()[0] and runs[can][-3:] == ["--use-socketcan", "--canport", "vcan0"]
    record = json.loads((run_dir / "up" / "listeners.json").read_text(encoding="utf-8"))
    assert record["listeners"] == {"ok": True, "snapshot": "up"} and record["listeners_feed"] == {"ok": False, "snapshot": "_feed"}
    assert record["feed"] == "vcan" and "listeners_before" in record
    assert fake.snapshot_feeds == ["vcan", "vcan"], fake.snapshot_feeds          # up()'s own and the _feed one
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0] == "prepared %s" % run_dir and lines[-1] == "stack running; stop it with: stack.py down", out
    assert json.dumps({"ok": True, "snapshot": "up"}, indent=1) in out, "the printed record (info['listeners']) stays"
    started = [ln for ln in lines if "CAN provider" in ln and can in ln and "started" in ln]
    assert len(started) == 1, out
    assert "ok False" in started[0], out
    assert out.index(started[0]) < out.index(json.dumps({"ok": True, "snapshot": "up"}, indent=1)), out
    # the contract with drill.py run: its label and its names, its own `docker ps --filter label=<label>=<run>/up` query
    drill = _drill(monkeypatch)
    listed = fake("ps", "--filter", "label=%s=%s/up" % (drill.STACK_LABEL, run_dir.name), "--format", "{{.Names}}").stdout.split()
    assert drill.CAN_PROVIDER_CONTAINER in listed and drill.DATABROKER_CONTAINER in listed, listed
    assert stack.NAMES[attr.APP] not in listed, "the app stays the updater's to start"


@pytest.mark.parametrize("extra", [[], ["--app", "stack"]])
def test_up_with_the_stacks_own_app_starts_no_can_provider_and_prints_what_it_printed(tmp_path, monkeypatch, capsys, extra):
    """Spec section 2 item 3: `up` with the stack's own app (the default, or --app stack) is unchanged byte for byte in what
    it starts and prints; its feed belongs to the run that follows. No CAN provider, no feed snapshot, no listener file."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = StackDocker()
    rc, run_dir = _up_main(tmp_path, monkeypatch, fake, *extra)
    assert rc == 0
    assert [e[4:] for e in fake.events if e.startswith("run ")] == UP_FOUR + [stack.NAMES[attr.APP]], fake.events
    assert fake.events[-1] == "listeners_up" and not [e for e in fake.events if stack.NAMES[attr.CAN_PROVIDER] in e], fake.events
    assert capsys.readouterr().out == "prepared %s\n%s\nstack running; stop it with: stack.py down\n" % (
        run_dir, json.dumps({"ok": True, "snapshot": "up"}, indent=1))
    assert sorted(os.listdir(run_dir / "up")) == []
    assert stack.NAMES[attr.CAN_PROVIDER] not in fake.listed(["ps", "-a"])


@pytest.mark.parametrize("can, why", [("silent", "timed out after"), ("stops", "stopped while waiting"),
                                      ("fails", "a synthetic failure to start"), ("interrupted", None), ("hangs", None)])
def test_a_can_provider_that_does_not_start_or_never_logs_ready_takes_the_stack_down_and_up_fails_with_the_reason(
        tmp_path, monkeypatch, capsys, can, why):
    """Spec section 2 item 2 and section 3's third case: a CAN provider that never logs its ready line, ends before it, or
    whose start fails takes the stack down (down's own teardown, the CAN provider included) and `up` fails with the reason
    (main raises StackError; run as a script that is `stack.py: <reason>` and exit 1). An interrupt during the wait, or a
    docker call in it that runs past its timeout (subprocess.TimeoutExpired), takes it down too and goes on as it was.
    Nothing is left: the stand-in's container list is empty after."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = StackDocker(can=can)
    if why is None:
        with pytest.raises(subprocess.TimeoutExpired if can == "hangs" else KeyboardInterrupt):
            _up_main(tmp_path, monkeypatch, fake, "--app", "external")
    else:
        with pytest.raises(stack.StackError) as e:
            _up_main(tmp_path, monkeypatch, fake, "--app", "external")
        msg = str(e.value)
        assert stack.NAMES[attr.CAN_PROVIDER] in msg and why in msg and "taken down" in msg, msg
    assert fake.containers == {} and fake.listed(["ps", "-aq", "--filter", "label=" + stack.LABEL]) == []
    removed = [n for c in fake.calls if c[:2] == ["rm", "-f"] for n in c[2:]]
    assert sorted(removed) == sorted(UP_FOUR + [stack.NAMES[attr.CAN_PROVIDER]]), removed
    assert "listeners_feed" not in fake.events and not (fake.run_dir / "up" / "listeners.json").exists()
    out = capsys.readouterr().out
    assert "stack running" not in out and "CAN provider started" not in out, out
    assert '"snapshot": "up"' not in out, out          # a failed up prints no listener record


def test_down_after_up_with_an_external_app_removes_the_can_provider_too(tmp_path, monkeypatch):
    """Spec section 2 item 4 and section 3's fourth case: `down` (remove_stack, unchanged) removes every container of the
    stack `up --app external` left running, the CAN provider included."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = StackDocker()
    rc, run_dir = _up_main(tmp_path, monkeypatch, fake, "--app", "external")
    assert rc == 0 and sorted(fake.listed(["ps"])) == sorted(UP_FOUR + [stack.NAMES[attr.CAN_PROVIDER]])
    del fake.calls[:]
    assert stack.main(["down"]) == 0
    assert fake.containers == {}
    (rm,) = [c for c in fake.calls if c[:1] == ["rm"]]
    assert rm[:2] == ["rm", "-f"] and sorted(rm[2:]) == sorted(UP_FOUR + [stack.NAMES[attr.CAN_PROVIDER]]), rm


def test_the_readme_says_up_with_an_external_app_starts_the_can_provider_and_what_a_failed_start_does():
    """Spec section 2 item 5: sdv/stack/README.md's `up --app external` paragraph says the CAN provider is among what it
    starts, where in the order it comes, why (the drill's vcan0 player reaches the databroker through it), where the listener
    record goes, and that one that does not start takes the stack down; the module docstring's APP paragraph names where it
    comes and the teardown too."""
    text = " ".join((STACK_DIR / "README.md").read_text(encoding="utf-8").split())
    for words in ("**`up --app external`** starts every container but the app, the CAN provider included, and waits for no app",
                  "comes last, once the rest of the stack serves",
                  "the vcan0 player of the updater's drill (`drill.py run`) reaches the databroker", "`up/listeners.json`",
                  "never logs its ready line takes the stack down (`down`'s teardown), and `up` fails with the reason",
                  "with the stack's own app starts what it started before, and no CAN provider"):
        assert words in text, words
    doc = " ".join((stack.__doc__ or "").split())          # the module docstring's APP paragraph says the same
    for words in ("but the app, the CAN provider included, which comes last, once up() has returned",
                  "takes the stack down (down's teardown), and up fails with the reason"):
        assert words in doc, words


def _fake_connector(monkeypatch):
    """The twin connector as up() starts it with --connector, reduced to what the CAN-provider fix reads: connector_checks
    a no-op, and start_connector one `docker run` of stack.CONNECTOR_CONTAINER with the run's label through stack.docker (a
    StackDocker once _up_main has set it), so the run order, the container list and the teardown hold it as they hold the
    rest of the stack. Its own checks, stamp, directories and start line are other tests' (none of this package's)."""
    monkeypatch.setattr(stack, "connector_checks", lambda ctx, feed: None)

    def start_connector(ctx, feed, replay_dir, run_label):
        stack.docker("run", "-d", "--name", stack.CONNECTOR_CONTAINER, "--label", "%s=%s" % (stack.LABEL, run_label), "connector")
    monkeypatch.setattr(stack, "start_connector", start_connector)


@pytest.mark.parametrize("can", ["ready", "silent"])
def test_up_with_an_external_app_and_the_connector_starts_the_can_provider_after_the_connector_and_a_failure_takes_both_down(
        tmp_path, monkeypatch, capsys, can):
    """The form drill.py's --via twin relies on, `up --feed vcan --app external --connector` (the connector reading the
    host's spool): up() starts the connector after the witness, and the CAN provider comes after it, once up() has returned,
    with the run's /up label and its ready line waited for, so drill.py run's container list holds both, and down removes
    both. A CAN provider that never logs its ready line takes the connector down with the rest of the stack, and up fails."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = StackDocker(can=can)
    _fake_connector(monkeypatch)
    can_name, conn = stack.NAMES[attr.CAN_PROVIDER], stack.CONNECTOR_CONTAINER
    if can == "silent":
        with pytest.raises(stack.StackError, match="timed out after") as e:
            _up_main(tmp_path, monkeypatch, fake, "--app", "external", "--connector")
        assert can_name in str(e.value) and "taken down" in str(e.value), str(e.value)
        assert [x[4:] for x in fake.events if x.startswith("run ")] == UP_FOUR + [conn, can_name], fake.events
        assert fake.containers == {} and fake.listed(["ps", "-aq", "--filter", "label=" + stack.LABEL]) == []
        removed = [n for c in fake.calls if c[:2] == ["rm", "-f"] for n in c[2:]]
        assert sorted(removed) == sorted(UP_FOUR + [conn, can_name]), removed
        assert "stack running" not in capsys.readouterr().out
        return
    rc, run_dir = _up_main(tmp_path, monkeypatch, fake, "--app", "external", "--connector")
    assert rc == 0
    assert [x[4:] for x in fake.events if x.startswith("run ")] == UP_FOUR + [conn, can_name], fake.events
    tail = fake.events[fake.events.index("listeners_up"):]
    assert tail[:3] == ["listeners_up", "run " + can_name, CAN_READY_WAIT], tail
    label = "%s=%s/up" % (stack.LABEL, run_dir.name)
    labels = {r[r.index("--name") + 1]: r[r.index("--label") + 1] for r in fake.runs()}
    assert labels == {n: label for n in UP_FOUR + [conn, can_name]}, "every container carries the run's /up label: %s" % labels
    drill = _drill(monkeypatch)
    listed = fake("ps", "--filter", "label=%s=%s/up" % (drill.STACK_LABEL, run_dir.name), "--format", "{{.Names}}").stdout.split()
    assert drill.CAN_PROVIDER_CONTAINER in listed and conn in listed, listed
    assert capsys.readouterr().out.splitlines()[-1] == "stack running; stop it with: stack.py down"
    del fake.calls[:]
    assert stack.main(["down"]) == 0
    assert fake.containers == {}
    (rm,) = [c for c in fake.calls if c[:1] == ["rm"]]
    assert rm[:2] == ["rm", "-f"] and sorted(rm[2:]) == sorted(UP_FOUR + [conn, can_name]), rm


class TeardownFails(StackDocker):
    """A StackDocker whose teardown fails once the CAN provider has been run (a double fault). how "gone": the daemon has
    gone away, and every later `ps` fails as docker()'s check makes a failed call fail (StackError, the command's first
    words and docker's own); "rm-hangs": `rm -f` runs past docker()'s timeout (subprocess.TimeoutExpired, as
    subprocess.run raises it) and removes nothing; "rm-interrupted": a second interrupt comes during `rm -f` (a
    KeyboardInterrupt from it)."""

    GONE = "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?"

    def __init__(self, can: str, how: str) -> None:
        super().__init__(can=can)
        self.how = how

    def __call__(self, *args: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        if stack.NAMES[attr.CAN_PROVIDER] in self.containers:
            if self.how == "gone" and args[:1] == ("ps",):
                self.calls.append(list(args))
                if check:
                    raise stack.StackError("%s failed (1): %s" % (" ".join(("docker",) + args[:3]), self.GONE))
                return subprocess.CompletedProcess(list(args), 1, "", self.GONE)
            if self.how == "rm-hangs" and args[:1] == ("rm",):
                self.calls.append(list(args))
                raise subprocess.TimeoutExpired(["docker"] + list(args), timeout)
            if self.how == "rm-interrupted" and args[:1] == ("rm",):
                self.calls.append(list(args))
                raise KeyboardInterrupt()
        return super().__call__(*args, check=check, timeout=timeout)


@pytest.mark.parametrize("can, why, how, teardown", [
    ("silent", "s waiting for sdv-stack-can-provider to log", "gone", TeardownFails.GONE),
    ("fails", "a synthetic failure to start", "gone", TeardownFails.GONE),
    ("interrupted", "KeyboardInterrupt", "gone", TeardownFails.GONE),
    ("silent", "s waiting for sdv-stack-can-provider to log", "rm-hangs", "TimeoutExpired: Command '['docker', 'rm', '-f'")],
    ids=["silent-gone", "fails-gone", "interrupted-gone", "silent-rm-hangs"])
def test_a_can_provider_failure_whose_teardown_fails_too_says_both_and_that_the_stack_may_still_be_running(
        tmp_path, monkeypatch, capsys, can, why, how, teardown):
    """A double fault: the teardown (remove_stack) itself fails while a CAN provider that did not start, never logged its
    ready line or was interrupted is handled (the daemon gone, or a docker call past its timeout). `up` fails with one
    StackError, the one line the __main__ handler prints (it prints str() alone, never __context__), that names the CAN
    provider, its reason (an interrupt by its type), the teardown's own failure (anything but a StackError by its type
    too), that the stack's containers may still be running, and how to list and remove them. On this stand-in the
    teardown removed nothing, so every container is still there."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = TeardownFails(can, how)
    with pytest.raises(stack.StackError) as e:
        _up_main(tmp_path, monkeypatch, fake, "--app", "external")
    msg = str(e.value)
    for words in (stack.NAMES[attr.CAN_PROVIDER], why, teardown, "taking the stack down failed too", "may still be running",
                  "docker ps --filter label=" + stack.LABEL, "stack.py down removes them"):
        assert words in msg, (words, msg)
    assert sorted(fake.containers) == sorted(UP_FOUR + [stack.NAMES[attr.CAN_PROVIDER]]), fake.containers
    assert "listeners_feed" not in fake.events and not (fake.run_dir / "up" / "listeners.json").exists()
    out = capsys.readouterr().out
    assert "stack running" not in out and "CAN provider started" not in out, out


def test_a_second_interrupt_during_the_can_providers_teardown_goes_on_as_an_interrupt(tmp_path, monkeypatch, capsys):
    """A second interrupt while a CAN provider that never logged its ready line is being taken down is no double fault: it
    goes on as an interrupt (only an Exception from the teardown becomes the one StackError that names both)."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = TeardownFails("silent", "rm-interrupted")
    with pytest.raises(KeyboardInterrupt):
        _up_main(tmp_path, monkeypatch, fake, "--app", "external")
    assert "stack running" not in capsys.readouterr().out


def test_a_can_provider_whose_after_start_hook_fails_takes_the_stack_down_and_up_says_the_hook_failed(tmp_path, monkeypatch, capsys):
    """A CAN provider that started but whose SDV_AFTER_START hook failed (start() raises after its docker run, as
    run_after_start does on a non-zero exit) is taken down with the rest of the stack, and up's reason says the hook failed."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = StackDocker()
    can = stack.NAMES[attr.CAN_PROVIDER]

    def after_start(ctx, name):
        if name == can:
            raise stack.StackError("%s after %s started: exit 7 (no output)" % (stack.AFTER_START_ENV, name))
    monkeypatch.setattr(stack, "run_after_start", after_start)
    with pytest.raises(stack.StackError) as e:
        _up_main(tmp_path, monkeypatch, fake, "--app", "external")
    msg = str(e.value)
    assert "failed its after-start hook" in msg and "SDV_AFTER_START after %s started: exit 7" % can in msg, msg
    assert fake.containers == {} and "stack running" not in capsys.readouterr().out


def test_the_run_manifests_note_on_an_external_app_says_up_waits_for_no_app_and_starts_the_can_provider():
    """APP_NOTES["external"], the app_note every `up --app external` run manifest carries: up starts every container but
    the app, the CAN provider included, and waits for no app. It never says up waits for none: up waits for the CAN
    provider's ready line, as it waits for the databroker's, the mock's, the recorder's and the witness's."""
    note = stack.APP_NOTES["external"]
    assert "starts every container but the app, the CAN provider included, and waits for no app;" in note, note
    assert "waits for none" not in note and "updater" in note, note


def test_the_run_manifest_says_who_starts_the_app_and_a_replay_takes_only_the_stacks_own(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    man = stack.Context(rig.runs / "e", None, "none", app="external").prepare(pull=False, build=False)
    assert man["app"] == "external" and "updater" in man["app_note"]
    assert json.loads((rig.runs / "e" / "manifest.json").read_text(encoding="utf-8"))["app"] == "external"
    _ctx, man = _prepare(rig, "s")
    assert man["app"] == "stack" and "this run starts" in man["app_note"]
    with pytest.raises(stack.StackError, match="--app 'updater'"):
        stack.Context(rig.runs / "x", None, "none", app="updater")
    assert not (rig.runs / "x").exists()
    def touched(*_a, **_kw):
        raise AssertionError("the replay went on though its context's app is external")
    for name in ("up", "remove_stack", "collect", "docker", "run"):
        monkeypatch.setattr(stack, name, touched)
    ctx = _replay_ctx(tmp_path, None)
    ctx.app = "external"
    for feed in stack.FEEDS:
        with pytest.raises(stack.StackError, match="a replay judges the app it starts itself"):
            stack.replay_once(ctx, feed, "%s-1" % feed)
    assert not ctx.run_dir.exists()


def _host_ctx(rig: Any, name: str) -> Any:
    """The one context that takes the host's spool and status: up --app external --connector's."""
    return stack.Context(rig.runs / name, None, "none", connector=True, app="external")


def test_host_spool_and_status_directories_are_taken_both_or_neither_and_each_must_exist_outside_the_repo(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch)
    spool, status = tmp_path / "host-spool", tmp_path / "host-status"
    spool.mkdir()
    status.mkdir()
    a_file = tmp_path / "a-file"
    a_file.write_text("not a directory\n", encoding="utf-8")
    cases = [({"SDV_SPOOL_DIR": str(spool)}, "both or neither"), ({"SDV_STATUS_DIR": str(status)}, "both or neither"),
             ({"SDV_SPOOL_DIR": str(tmp_path / "gone"), "SDV_STATUS_DIR": str(status)}, "SDV_SPOOL_DIR"),
             ({"SDV_SPOOL_DIR": str(spool), "SDV_STATUS_DIR": str(a_file)}, "SDV_STATUS_DIR"),
             ({"SDV_SPOOL_DIR": "relative/spool", "SDV_STATUS_DIR": str(status)}, "SDV_SPOOL_DIR"),
             ({"SDV_SPOOL_DIR": str(spool), "SDV_STATUS_DIR": ""}, "SDV_STATUS_DIR"),
             ({"SDV_SPOOL_DIR": str(REPO / "sdv"), "SDV_STATUS_DIR": str(status)}, "inside the repo"),
             ({"SDV_SPOOL_DIR": str(spool), "SDV_STATUS_DIR": str(REPO)}, "inside the repo")]
    for env, why in cases:
        for name in ("SDV_SPOOL_DIR", "SDV_STATUS_DIR"):
            monkeypatch.delenv(name, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(stack.StackError, match=why) as e:
            _host_ctx(rig, "x")
        assert str(tmp_path) not in str(e.value) and str(REPO) not in str(e.value), "a refusal names the variable, never its value"
        assert not (rig.runs / "x").exists()
    # a relative name of a directory that exists is refused too: the rule is the absolute form, not only that the directory is there
    here = os.getcwd()
    (tmp_path / "rel-spool").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SDV_SPOOL_DIR", "rel-spool")
    monkeypatch.setenv("SDV_STATUS_DIR", str(status))
    with pytest.raises(stack.StackError, match="SDV_SPOOL_DIR must be the absolute path") as e:
        _host_ctx(rig, "x")
    assert "rel-spool" not in str(e.value)
    assert not (rig.runs / "x").exists()
    monkeypatch.chdir(here)
    monkeypatch.setenv("SDV_SPOOL_DIR", str(spool))
    monkeypatch.setenv("SDV_STATUS_DIR", str(status))
    assert _host_ctx(rig, "h").host_dirs == (spool, status)
    monkeypatch.delenv("SDV_SPOOL_DIR")
    monkeypatch.delenv("SDV_STATUS_DIR")
    assert _host_ctx(rig, "h").host_dirs is None
    # with a connector the run manifest says which directories it was given, and never their paths
    (rig.gen / "vss-ids.vspec").write_text("a synthetic id file\n", encoding="utf-8")
    _device_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(stack, "connector_image", lambda: {"class": "platform", "form": "container", "image_id": CONNECTOR_IMG})
    monkeypatch.setenv("SDV_SPOOL_DIR", str(spool))
    monkeypatch.setenv("SDV_STATUS_DIR", str(status))
    man = _host_ctx(rig, "c").prepare(pull=False, build=False)
    assert "SDV_SPOOL_DIR" in man["twin"]["spool_status"] and str(tmp_path) not in json.dumps(man["twin"])
    monkeypatch.delenv("SDV_SPOOL_DIR")
    monkeypatch.delenv("SDV_STATUS_DIR")
    man = stack.Context(rig.runs / "d", None, "none", connector=True).prepare(pull=False, build=False)
    assert "the replay's own" in man["twin"]["spool_status"]


def test_host_spool_and_status_are_read_only_by_a_run_with_a_connector(tmp_path, monkeypatch):
    """Spec 2.7: when set, the CONNECTOR mounts them. A run with no connector (exit-test, step3.py, a replay or an up
    without --connector) does not read them, so the drill's shell, which exports both before the updater's launcher has
    made the directories, refuses nothing that has no connector; a run with one is held to every rule of the pair."""
    rig = _prepare_rig(tmp_path, monkeypatch)
    status = tmp_path / "host-status"
    status.mkdir()
    pairs = [{"SDV_SPOOL_DIR": str(tmp_path / "not-made-yet"), "SDV_STATUS_DIR": str(status)}, {"SDV_SPOOL_DIR": str(status)},
             {"SDV_SPOOL_DIR": "relative/spool", "SDV_STATUS_DIR": ""}, {"SDV_SPOOL_DIR": str(REPO / "sdv"), "SDV_STATUS_DIR": str(status)}]
    for env in pairs:
        for name in ("SDV_SPOOL_DIR", "SDV_STATUS_DIR"):
            monkeypatch.delenv(name, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        for app in ("stack", "external"):
            assert stack.Context(rig.runs / "n", None, "none", app=app).host_dirs is None, (env, app)
        with pytest.raises(stack.StackError, match="SDV_SPOOL_DIR|SDV_STATUS_DIR"):
            _host_ctx(rig, "c")
    assert not (rig.runs / "n").exists() and not (rig.runs / "c").exists()


def test_host_spool_and_status_are_taken_only_by_up_with_an_external_app_and_refused_beside_the_stacks_own_app(tmp_path, monkeypatch):
    """With the host's spool the twin's requests reach the updater, which starts its app outside the stack. A run that starts
    the stack's own app with a connector (replay --connector, up --connector) would put that second app on the databroker
    beside the one the replay judges: refused before anything is written, naming the variables and never their values.
    up --app external --connector takes them."""
    rig = _prepare_rig(tmp_path, monkeypatch)
    spool, status = tmp_path / "host-spool", tmp_path / "host-status"
    spool.mkdir()
    status.mkdir()
    monkeypatch.setenv("SDV_SPOOL_DIR", str(spool))
    monkeypatch.setenv("SDV_STATUS_DIR", str(status))
    with pytest.raises(stack.StackError, match="taken only by up --app external --connector") as e:
        stack.Context(rig.runs / "s", None, "none", connector=True)
    assert "SDV_SPOOL_DIR" in str(e.value) and "SDV_STATUS_DIR" in str(e.value) and str(tmp_path) not in str(e.value)
    assert not (rig.runs / "s").exists()
    assert _host_ctx(rig, "e").host_dirs == (spool, status)

    class Stop(Exception):
        pass

    def stop(*_a: Any, **_kw: Any) -> Any:
        raise Stop()
    monkeypatch.setattr(stack.Context, "prepare", stop)          # a context that was made goes no further than this
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs-main")
    for args in (["replay", "--feed", "vcan", "--connector"], ["up", "--feed", "vcan", "--connector"],
                 ["up", "--feed", "vcan", "--app", "stack", "--connector"]):
        with pytest.raises(stack.StackError, match="taken only by up --app external --connector"):
            stack.main(args + ["--name", "m"])
    for args in (["up", "--feed", "vcan", "--app", "external", "--connector"], ["replay", "--feed", "vcan"], ["up", "--feed", "vcan"]):
        with pytest.raises(Stop):
            stack.main(args + ["--name", "m"])
    assert not (tmp_path / "runs-main").exists()


def test_host_spool_and_status_directories_may_be_one_directory_or_a_link_outside_the_repo_but_not_a_link_into_it(tmp_path, monkeypatch):
    """Spec 2.7: each must lie outside the repo. inside_repo resolves a link, so a link into the repo is inside it; an empty
    value still counts as set; one directory named by both variables is taken as given."""
    rig = _prepare_rig(tmp_path, monkeypatch)
    here, status = tmp_path / "one-directory", tmp_path / "host-status"
    here.mkdir()
    status.mkdir()
    out_link, in_link = tmp_path / "link-out", tmp_path / "link-in"
    out_link.symlink_to(here, target_is_directory=True)
    in_link.symlink_to(REPO / "sdv", target_is_directory=True)

    def given(spool, stat):
        for name in ("SDV_SPOOL_DIR", "SDV_STATUS_DIR"):
            monkeypatch.delenv(name, raising=False)
        for name, value in (("SDV_SPOOL_DIR", spool), ("SDV_STATUS_DIR", stat)):
            if value is not None:
                monkeypatch.setenv(name, str(value))

    given(here, here)                                                             # (a) one directory for both
    assert _host_ctx(rig, "a").host_dirs == (here, here)
    given(out_link, status)                                                       # (b) a link, outside the repo, to a directory outside it
    got = _host_ctx(rig, "b").host_dirs
    assert got is not None and got[0].resolve() == here.resolve() and got[1] == status
    refused = [(in_link, status, "inside the repo"),                              # (c) a link outside the repo to one inside it
               ("", None, "both or neither")]                                     # (d) an empty value is set, and the other is not
    for spool, stat, why in refused:
        given(spool, stat)
        with pytest.raises(stack.StackError, match=why) as e:
            _host_ctx(rig, "x")
        assert str(tmp_path) not in str(e.value) and str(REPO) not in str(e.value), "a refusal names the variable, never its value"
        assert not (rig.runs / "x").exists()


def test_the_connector_mounts_the_host_spool_and_status_at_its_own_paths_and_the_stack_makes_neither(tmp_path, monkeypatch):
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = ConnectorDocker()
    monkeypatch.setattr(stack, "docker", fake)
    monkeypatch.setattr(stack, "wall_ms", lambda: T_WALL_MS)
    device = _device_dir(tmp_path, monkeypatch)
    spool, status = tmp_path / "host-spool", tmp_path / "host-status"
    spool.mkdir()
    status.mkdir()
    ctx = _connector_ctx(tmp_path, host_dirs=(spool, status))
    rd = tmp_path / "runs" / "a" / "vcan-1"
    rd.mkdir(parents=True)
    stack.start_connector(ctx, "vcan", rd, "a/vcan-1")
    assert list(rd.iterdir()) == [] and list(spool.iterdir()) == [] and list(status.iterdir()) == [], "the stack made something"
    (run,) = fake.runs()
    mounts = [run[k + 1] for k, a in enumerate(run) if a == "--mount"]
    assert mounts == ["type=bind,src=%s,dst=/run/sdv-local/spool/v1" % spool, "type=bind,src=%s,dst=/run/sdv-local/status/v1,readonly" % status,
                      "type=bind,src=%s,dst=/run/sdv-local/device,readonly" % device]
    assert stack.connector_part("status").DEFAULT_STATUS_DIR == stack.CONNECTOR_MOUNTS["status"], "the connector reads where the stack mounts"
    # a host directory gone by the start is refused, never made, before the stack's start stamp is touched, naming the variable
    stamp = stack.connector_state_dir(make=False) / stack.connector_part("startstamp").FILE
    stamped = json.loads(stamp.read_text(encoding="utf-8"))
    status.rmdir()
    monkeypatch.setattr(stack, "wall_ms", lambda: T_WALL_MS + 200_000)
    other = tmp_path / "runs" / "b" / "vcan-1"
    other.mkdir(parents=True)
    with pytest.raises(stack.StackError, match="the connector needs") as e:
        stack.start_connector(ctx, "vcan", other, "b/vcan-1")
    assert str(tmp_path) not in str(e.value), "a refusal names the variable, never its value"
    assert json.loads(stamp.read_text(encoding="utf-8")) == stamped, "the refused start rewrote the stack's start stamp"
    assert not status.exists() and list(other.iterdir()) == [] and len(fake.runs()) == 1
    # the directory gone between start_connector's check and the container's own (a race): the same refusal, the same words
    status.mkdir()
    monkeypatch.setattr(stack, "mark_connector_start", status.rmdir)
    with pytest.raises(stack.StackError, match="the connector needs") as e:
        stack.start_connector(ctx, "vcan", other, "b/vcan-1")
    assert "SDV_STATUS_DIR" in str(e.value) and str(tmp_path) not in str(e.value), "the host's paths were printed"
    assert not status.exists() and len(fake.runs()) == 1


def test_a_bridge_run_is_refused_while_the_twin_control_marker_exists_before_any_context_is_made(tmp_path, monkeypatch):
    """D11 (spec 2.7, section 4 item 7): while the marker exists no bridge starts. replay --bridge and prepare --bridge are
    refused before a Context exists; without a bridge the marker changes nothing. Its existence is the mode: a file, a
    directory and a link to nothing are each a marker."""
    marker = tmp_path / "twin-control"
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(marker))
    seen: List[str] = []

    class Stop(Exception):
        pass

    class FakeContext:
        def __init__(self, *args, **kwargs):
            seen.append(args[2])

        def prepare(self, images="build"):
            raise Stop()

    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "Context", FakeContext)
    bridged = (["replay", "--feed", "vcan", "--bridge", "broker"], ["prepare", "--bridge", "broker"],
               ["replay", "--feed", "vcan", "--bridge", "broker", "--connector"])
    plain = (["replay", "--feed", "vcan"], ["prepare"], ["up", "--feed", "vcan"], ["replay"], ["exit-test"],
             ["up", "--feed", "vcan", "--app", "external", "--connector"])
    for i, args in enumerate(bridged + plain):          # no marker: every command as before
        with pytest.raises(Stop):
            stack.main(args + ["--name", "a%d" % i])
    assert seen == ["broker"] * 3 + ["none"] * 6
    for kind, make, remove in (("file", marker.touch, marker.unlink), ("directory", marker.mkdir, marker.rmdir),
                               ("dangling link", lambda: marker.symlink_to(tmp_path / "nothing-there"), marker.unlink)):
        make()
        for i, args in enumerate(bridged):
            with pytest.raises(stack.StackError, match="twin-control marker") as e:
                stack.main(args + ["--name", "b%d" % i])
            assert "SDV_TWIN_CONTROL_MARKER" in str(e.value), kind
        n = len(seen)
        for i, args in enumerate(plain):
            with pytest.raises(Stop):
                stack.main(args + ["--name", "c%d" % i])
        assert len(seen) == n + len(plain), kind
        remove()
    assert not (tmp_path / "runs").exists()


def test_a_context_with_a_bridge_and_the_bridges_own_start_are_refused_while_the_marker_exists(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True)
    marker = tmp_path / "twin-control"
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(marker))
    marker.touch()
    for mode in ("broker", "can", "replay"):          # step3.py makes its own contexts: refused there too
        with pytest.raises(stack.StackError, match="twin-control marker"):
            stack.Context(rig.runs / "m", None, mode)
        assert not (rig.runs / "m").exists()
    assert stack.Context(rig.runs / "n", None, "none").bridge == "none"

    def touched(*_a, **_kw):
        raise AssertionError("docker was asked though the bridge was to be refused")
    monkeypatch.setattr(stack, "docker", touched)
    rd = tmp_path / "r"
    rd.mkdir()
    ctx = _phase6_ctx(tmp_path)
    with pytest.raises(stack.StackError, match="twin-control marker"):          # the last moment before a bridge container
        stack.start_bridge(ctx, "vcan", rd, "x/r", {"bridge_mode": "broker"})
    assert list(rd.iterdir()) == []
    marker.unlink()
    with pytest.raises(AssertionError, match="docker was asked"):          # absent again: the start goes on to its docker run
        stack.start_bridge(ctx, "vcan", rd, "x/r", {"bridge_mode": "broker"})


def test_the_twin_control_markers_default_its_variable_and_a_marker_that_cannot_be_read(tmp_path, monkeypatch):
    assert (stack.TWIN_CONTROL_MARKER, stack.TWIN_CONTROL_ENV) == ("/run/sdv-local/twin-control", "SDV_TWIN_CONTROL_MARKER")
    monkeypatch.delenv("SDV_TWIN_CONTROL_MARKER")
    assert stack.twin_control_marker() == Path("/run/sdv-local/twin-control")
    for bad in ("", "relative/twin-control"):
        monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", bad)
        with pytest.raises(stack.StackError, match="must be an absolute path"):          # the setting's own refusal, not the marker's
            stack.refuse_bridge_in_twin_control("broker")
        stack.refuse_bridge_in_twin_control("none")          # no bridge: the marker is not even looked for
    marker = tmp_path / "twin-control"
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(marker))
    stack.refuse_bridge_in_twin_control("broker")
    marker.touch()
    stack.refuse_bridge_in_twin_control("none")
    marker.unlink()
    real = os.lstat

    def denied(path, *a, **kw):
        if os.fspath(path) == str(marker):
            raise PermissionError(13, "Permission denied")
        return real(path, *a, **kw)
    monkeypatch.setattr(stack.os, "lstat", denied)
    with pytest.raises(stack.StackError, match="cannot tell"):          # a marker that cannot be looked for counts as one
        stack.refuse_bridge_in_twin_control("broker")


@pytest.mark.parametrize("kind", ["parent-is-a-file", "link-to-a-file", "link-to-a-directory", "relative-path"])
def test_the_twin_control_marker_path_that_is_under_a_file_a_link_or_not_absolute(tmp_path, monkeypatch, kind):
    """A path whose parent is a regular file is no marker (NotADirectoryError is absence, as FileNotFoundError is); a link
    to a file or to a directory is an entry at the path, so it is one; a relative path is refused as the setting."""
    if kind == "parent-is-a-file":
        (tmp_path / "a-file").write_text("not a directory\n", encoding="utf-8")
        monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(tmp_path / "a-file" / "twin-control"))
        stack.refuse_bridge_in_twin_control("broker")
        return
    if kind == "relative-path":
        monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", "./twin-control")
        with pytest.raises(stack.StackError, match="SDV_TWIN_CONTROL_MARKER"):
            stack.refuse_bridge_in_twin_control("broker")
        return
    target = tmp_path / "target"
    if kind == "link-to-a-file":
        target.write_text("a file\n", encoding="utf-8")
    else:
        target.mkdir()
    marker = tmp_path / "twin-control"
    marker.symlink_to(target, target_is_directory=target.is_dir())
    monkeypatch.setenv("SDV_TWIN_CONTROL_MARKER", str(marker))
    with pytest.raises(stack.StackError, match="twin-control marker"):
        stack.refuse_bridge_in_twin_control("broker")


# --- a CARLA recording (SDV Phase 7 WP3b; spec-2 sections 2.1, 2.2 and 5) -------------------------------------------------
# The stack takes a recording of either kind: its log by its line's generator and the basename of its recording.path
# (sigsim.log or carla.log, sdv/inject/inject.py's LOG_NAMES), staged under its own name; its run type's catalogue and
# vehicle layer from the generation (a sigsim run exactly today's); its run header's run_type and source_rtf from its
# line. Synthetic recordings and generations on the rig above; WP1's fake take encoded against this tree's generation
# (tests/test_sdv_phase7_contract.py's builders and stand-ins); one test reads WP5a's real pair and skips without it.

CARLA_HONEST_DIR = Path("~/sdv-recordings").expanduser() / "20261019-carla-1"      # spec-2 2.3's CARLA_HONEST, read only
NEEDS_CARLA_PAIR = pytest.mark.skipif(not (CARLA_HONEST_DIR.parent / (CARLA_HONEST_DIR.name + "-inj") / "events.json").is_file()
                                      or not (CARLA_HONEST_DIR / "carla.log").is_file(),
                                      reason="needs WP5a's CARLA pair %s and its -inj twin (read only)" % CARLA_HONEST_DIR)
# The synthetic sigsim run's normalized text (_sigsim_run_text) on this file's rig: (sha256, lines). It is the base
# rig's value with sigsim.py's source identity (the three manifests' recording.sigsim.current_sha256) updated for a later
# comment-only edit of sigsim.py; every other byte is the base's, so any change to a sigsim run's in/, its argument
# vectors or its records changes it. Regenerate it only from the reference stack.py on this rig, never from changed
# behaviour.
SIGSIM_BASE_GOLDEN = ("16840f54a2369780fd5eaee5a61ba2518929efd09e178502682185cb33392739", 1089)


def _inject_module():
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        d = str(REPO / "sdv" / "inject")
        if d not in sys.path:
            sys.path.insert(0, d)
        import inject
    finally:
        sys.dont_write_bytecode = saved
    return inject


def test_the_stacks_log_table_is_the_injectors_and_its_encoder_modules_the_encoders():
    """Spec-2 2.1: one table, spelled once more in bundle.py (standard library only, Python 3.10) and held equal here;
    the stack reads it through bundle.py. The encoder modules the CARLA provenance reports are sdv/carla/encode.py's."""
    inj = _inject_module()
    assert stack.bd.LOG_NAMES == inj.LOG_NAMES == {"sigsim": "sigsim.log", "carla": "carla.log"}
    assert stack.LOG_NAMES is stack.bd.LOG_NAMES
    tree = ast.parse((REPO / "sdv" / "carla" / "encode.py").read_text(encoding="utf-8"))
    mods = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
            and [getattr(t, "id", None) for t in n.targets] == ["ENCODER_MODULES"]]
    assert mods == [stack.CARLA_ENCODER_MODULES]


def test_a_carla_recording_gives_its_identity_by_its_carla_log(tmp_path):
    d, line, sha = _recording(tmp_path, gen="carla", name="20260101-carla-7")
    rec = stack.recording_identity(d)
    assert (rec["log_name"], rec["run_type"], rec["sha256"], rec["log"]) == ("carla.log", "carla", sha, str(d / "carla.log"))
    assert rec["manifest_line"] == line and not (d / "sigsim.log").exists()
    (tmp_path / "s").mkdir()
    s, _line, ssha = _recording(tmp_path / "s", seed=7)
    got = stack.recording_identity(s)
    assert (got["log_name"], got["run_type"], got["sha256"]) == ("sigsim.log", "sigsim", ssha)


@pytest.mark.parametrize("over, both", [
    ({"gen": "carla", "path_log": "sigsim.log", "log": "sigsim.log"}, ("'carla'", "'sigsim.log'")),
    ({"gen": "sigsim", "path_log": "carla.log", "log": "carla.log"}, ("'sigsim'", "'carla.log'")),
    ({"gen": "carla", "path_log": "drive.log", "log": "drive.log"}, ("'carla'", "'drive.log'")),
    ({"gen": "vtd", "path_log": "sigsim.log"}, ("'vtd'", "'sigsim.log'")),
    ({"gen": "carla", "path_log": "carla.log", "log": "sigsim.log"}, ("no readable carla.log",)),     # the file is not the one named
])
def test_a_mismatched_generator_and_log_or_another_name_is_refused_naming_both(tmp_path, over, both):
    d, _line, _sha = _recording(tmp_path, **over)
    with pytest.raises(stack.StackError) as exc:
        stack.recording_identity(d)
    assert all(w in str(exc.value) for w in both), str(exc.value)


@pytest.mark.parametrize("over, match", [
    ({"line_sha": "00" * 32}, "carla.log hashes to [0-9a-f]{64}, its manifest line says"),
    ({"listed_sha": "00" * 32}, "carla.log hashes to [0-9a-f]{64}, carla.log.sha256 says"),
    ({"listed_name": "sigsim.log"}, r"carla.log.sha256 names \['sigsim.log'\], not carla.log"),
])
def test_a_carla_recording_whose_log_does_not_hash_to_its_records_is_refused(tmp_path, over, match):
    d, _line, _sha = _recording(tmp_path, gen="carla", **over)
    with pytest.raises(stack.StackError, match=match):
        stack.recording_identity(d)


def test_a_sigsim_run_uses_todays_pair_whatever_else_the_generation_holds(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, frozen=True)
    man = json.loads((rig.gen / "manifest.json").read_text(encoding="utf-8"))
    man["vehicle_layers"]["sigsim"] = dict(man["vehicle_layers"]["sigsim"], file=CARLA_LAYER)    # never read for sigsim
    man["databroker_catalogues"]["sigsim"] = CARLA_CATALOGUE
    pair = stack.generation_pair(man, "sigsim")
    assert pair["run_type"] == "sigsim" and pair["catalogue"] == "vss-databroker.json"
    assert pair["vehicle_layer"]["file"] == LAYER and pair["vehicle_layer"]["sha256"] == stack.sha256_file(rig.gen / LAYER)
    del man["vehicle_layers"], man["databroker_catalogues"]
    assert stack.generation_pair(man, "sigsim") == pair, "a pre-freeze generation runs sigsim as before"


def test_a_carla_run_uses_the_generations_carla_layer_and_catalogue(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, frozen=True)
    man = json.loads((rig.gen / "manifest.json").read_text(encoding="utf-8"))
    pair = stack.generation_pair(man, "carla")
    assert pair["run_type"] == "carla" and pair["catalogue"] == CARLA_CATALOGUE
    assert pair["vehicle_layer"]["file"] == CARLA_LAYER and pair["vehicle_layer"]["sha256"] == stack.sha256_file(rig.gen / CARLA_LAYER)
    for f in (CARLA_LAYER, CARLA_CATALOGUE):
        (rig.gen / f).write_bytes((rig.gen / f).read_bytes() + b"\n")
        with pytest.raises(stack.StackError, match="hashes to"):
            stack.generation_pair(man, "carla")
        (rig.gen / f).write_bytes((rig.gen / f).read_bytes()[:-1])


@pytest.mark.parametrize("drop", ["vehicle_layers", "databroker_catalogues", "both", "carla-entry"])
def test_a_pre_freeze_generation_refuses_a_carla_recording(tmp_path, monkeypatch, drop):
    rig = _prepare_rig(tmp_path, monkeypatch, frozen=True)
    man = json.loads((rig.gen / "manifest.json").read_text(encoding="utf-8"))
    if drop in ("vehicle_layers", "both"):
        del man["vehicle_layers"]
    if drop in ("databroker_catalogues", "both"):
        del man["databroker_catalogues"]
    if drop == "carla-entry":
        del man["vehicle_layers"]["carla"]
    with pytest.raises(stack.StackError, match="the generation has no carla"):
        stack.generation_pair(man, "carla")


def _frozen_carla(tmp_path, monkeypatch, bridge="broker", **over):
    rig = _prepare_rig(tmp_path, monkeypatch, frozen=True, gen="carla", name="20260101-carla-7", **over)
    ctx, man = _prepare(rig, "c", bridge=bridge)
    return rig, ctx, man


def test_prepare_stages_a_carla_recordings_log_under_its_own_name_and_the_carla_catalogue(tmp_path, monkeypatch):
    rig, ctx, man = _frozen_carla(tmp_path, monkeypatch)
    in_dir = rig.runs / "c" / "in"
    assert sorted(os.listdir(in_dir)) == ["can-provider.ini", "carla.log", "slice.dbc", "vss-can-mapping.json", "vss-databroker.json"]
    assert (in_dir / "carla.log").read_bytes() == (rig.rec / "carla.log").read_bytes()
    assert (in_dir / "vss-databroker.json").read_bytes() == (rig.gen / CARLA_CATALOGUE).read_bytes()
    assert rig.seen["log"] == in_dir / "carla.log", "decoded from the staged log, by its name"
    assert ctx.log_name == "carla.log" and ctx.run_type == "carla" and set(ctx.staged) == set(os.listdir(in_dir))
    assert man["staged_inputs_sha256"]["carla.log"] == man["recording"]["sha256"] and "sigsim.log" not in man["staged_inputs_sha256"]
    cat = man["catalogue"]
    assert cat["databroker_json_sha256"] == "sha256:" + stack.sha256_file(rig.gen / CARLA_CATALOGUE)
    assert cat["vehicle_layer_sha256"] == "sha256:" + stack.sha256_file(rig.gen / CARLA_LAYER)
    own = json.loads((rig.runs / "c" / "ownership.json").read_text(encoding="utf-8"))
    wb = [r for r in own["rows"] if r["path"] == attr.WHEELBASE]
    assert [r["ingress"] for r in wb] == ["catalogue:" + CARLA_LAYER]
    assert ctx.wheelbase == dict(ctx.wheelbase, served=True, value_mm=SYN_OTHER_L_MM, l_mm=SYN_OTHER_L_MM), ctx.wheelbase
    assert own["source"]["rtf"] == RTF and own["profile_id"] == 3


@pytest.mark.parametrize("gen", ["carla", "sigsim"])
def test_prepare_refuses_a_staged_log_that_differs_from_the_recording(tmp_path, monkeypatch, gen):
    """The copy prepare stages under the log's own name is hashed against the recording's: a copy that reads back as other
    bytes is refused, for a carla.log as for a sigsim.log (the check is keyed by the log's name, not by sigsim's)."""
    log = SYN_LOGS[gen]
    rig = _prepare_rig(tmp_path, monkeypatch, frozen=True, **({"gen": "carla", "name": "20260101-carla-7"} if gen == "carla" else {}))
    real = shutil.copyfile

    def copyfile(src, dst, **kw):
        out = real(src, dst, **kw)
        if Path(dst).name == log:
            Path(dst).write_bytes(b"(0.000000) vcan0 100#00\n")
        return out
    monkeypatch.setattr(stack.shutil, "copyfile", copyfile)
    with pytest.raises(stack.StackError, match="the staged recording differs from the recording"):
        _prepare(rig, "c")


def test_prepare_on_a_sigsim_recording_of_a_frozen_generation_stages_the_sigsim_pair(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, frozen=True)
    ctx, man = _prepare(rig, "s", bridge="broker")
    in_dir = rig.runs / "s" / "in"
    assert sorted(os.listdir(in_dir)) == ["can-provider.ini", "sigsim.log", "slice.dbc", "vss-can-mapping.json", "vss-databroker.json"]
    assert (in_dir / "vss-databroker.json").read_bytes() == (rig.gen / "vss-databroker.json").read_bytes()
    assert man["catalogue"]["vehicle_layer_sha256"] == "sha256:" + stack.sha256_file(rig.gen / LAYER)
    own = json.loads((rig.runs / "s" / "ownership.json").read_text(encoding="utf-8"))
    assert [r["ingress"] for r in own["rows"] if r["path"] == attr.WHEELBASE] == ["catalogue:" + LAYER]
    h = ctx.run_header("vcan-1", "vcan")
    assert (h["run_type"], h["feed"], h["source_rtf"], h["profile_id"]) == ("sigsim", "recording", None, 1)
    assert "sigsim" in man["recording"] and "carla" not in man["recording"]
    ctx.scenario["source"] = dict(ctx.scenario["source"], rtf=dict(RTF))      # a sigsim line that carried an rtf
    assert ctx.run_header("vcan-1", "vcan")["source_rtf"] is None, "source_rtf is a CARLA run's only"


def test_the_sigsim_catalogue_for_a_carla_broker_run_is_refused_as_the_bridge_would_refuse_it(tmp_path, monkeypatch):
    """The staged catalogue is what the databroker serves: the carla run's predicted Wheelbase is profile 3's L. Were the
    sigsim catalogue staged instead, its default (profile 1's L) would be refused before anything starts."""
    rig, ctx, _man = _frozen_carla(tmp_path, monkeypatch)
    sig = json.loads((rig.gen / "vss-databroker.json").read_text(encoding="utf-8"))
    with pytest.raises(stack.StackError, match="not the profile's L"):
        stack.served_wheelbase(sig, SYN_OTHER_L_MM, {"name": "carla-ego", "wheelbase_mm": SYN_OTHER_L_MM}, None)
    assert stack.served_wheelbase(ctx.catalogue_tree, SYN_OTHER_L_MM, {}, None)["value_mm"] == SYN_OTHER_L_MM


@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
def test_the_run_header_of_a_carla_replay_in_each_mode(tmp_path, monkeypatch, mode):
    _rig, ctx, _man = _frozen_carla(tmp_path, monkeypatch, bridge=mode)
    feed = {"broker": "vcan", "can": "vcan", "replay": "none"}[mode]
    h = ctx.run_header("x-1", feed)
    assert (h["run_type"], h["feed"], h["bridge_mode"], h["profile_id"], h["profile_source"]) == ("carla", "recording", mode, 3, "scenario")
    assert h["source_rtf"] == RTF and h["source_rtf"] is not ctx.scenario["source"]["rtf"]
    assert h["source_vehicle"] == {"name": "carla-ego", "wheelbase_mm": SYN_OTHER_L_MM}
    assert ctx.scenario["source"]["rtf"] == RTF, "the scenario entry's source is the line's, rtf included"
    c12a = ctx.check_header(h)
    assert c12a[1], c12a
    assert not ctx.check_header(dict(h, source_rtf=None))[1] and not ctx.check_header(dict(h, run_type="sigsim"))[1]
    rec = [r for r in h["recordings"] if r["role"] == "candump"]
    assert rec == [{"role": "candump", "path": "~/rec/20260101-carla-7/carla.log", "sha256": "sha256:" + ctx.staged["carla.log"]}]
    assert attr.check_recording(h, ctx.staged["carla.log"], ctx.scenario["dbc_sha256"])[1]


def _argv_rig(ctx, tmp_path, monkeypatch):
    """stack.start()'s argument vectors on a prepared context: the images it runs (synthetic IDs), docker replaced."""
    calls: List[List[str]] = []

    def fake_docker(*args, **_kw):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(stack, "docker", fake_docker)
    ctx.components.update({attr.APP: {"image_id": IMG, "config_digest": APP_CFG}, attr.RECORDER: {"image_id": "sha256:" + "cd" * 32},
                           attr.BRIDGE: {"image_id": "sha256:" + "ef" * 32}, attr.DATABROKER: {"image_id": "sha256:" + "a1" * 32},
                           attr.MOCK_PROVIDER: {"image_id": "sha256:" + "a2" * 32}, attr.CAN_PROVIDER: {"image_id": "sha256:" + "a3" * 32}})
    rd = tmp_path / "argv-replay"
    (rd / "bridge").mkdir(parents=True)
    (rd / "scenario.lock").touch()
    (rd / "bridge-header.json").write_text("{}", encoding="utf-8")
    return calls, rd


@pytest.mark.parametrize("mode", ["broker", "can", "replay"])
def test_every_argv_that_names_the_recording_names_the_staged_carla_log(tmp_path, monkeypatch, mode):
    _rig, ctx, _man = _frozen_carla(tmp_path, monkeypatch, bridge=mode)
    calls, rd = _argv_rig(ctx, tmp_path, monkeypatch)
    for feed in stack.FEEDS:
        stack.start(ctx, attr.CAN_PROVIDER, feed, rd, "t/r")
    stack.start(ctx, attr.BRIDGE, {"replay": "none"}.get(mode, "vcan"), rd, "t/r")
    joined = [" ".join(c) for c in calls]
    assert not [j for j in joined if "sigsim.log" in j], joined
    assert "--dumpfile /in/carla.log --canport vcan0" in joined[0] and "--use-socketcan" in joined[1]
    if mode == "replay":
        assert "--log /in/carla.log --dbc /in/slice.dbc" in joined[2]
    if mode in ("can", "replay"):
        assert "%s:/in:ro" % ctx.in_dir in joined[2]


def test_a_replay_plays_checks_and_compares_the_staged_log_by_its_name(tmp_path, monkeypatch):
    """stack.py's own vcan replay (replay_once, every outside call replaced): the player plays the log the context staged,
    C10 takes its sha256, and the bus capture is compared with that file's frames (a CARLA run's carla.log; the context
    holds no sigsim.log)."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    seen: List[str] = []
    _replay_fakes(monkeypatch, tmp_path / "order.log", seen)
    got: Dict[str, Any] = {"played": [], "framed": []}
    monkeypatch.setattr(attr, "check_recording", lambda header, sha, dbc: (got.update(sha=sha), ("C10", True, "synthetic"))[1])
    monkeypatch.setattr(stack, "run", lambda cmd, **_kw: (got["played"].append(list(cmd)), subprocess.CompletedProcess(cmd, 0, "", ""))[1])
    monkeypatch.setattr(stack, "log_frames", lambda path: (got["framed"].append(Path(path)), [(0x100, b"\0" * 8)])[1])

    class Capture:
        def close(self):
            return [(0x100, b"\0" * 8)]
    monkeypatch.setattr(stack, "VcanCapture", Capture)
    ctx = _replay_ctx(tmp_path, None)
    ctx.log_name, ctx.staged = "carla.log", {"carla.log": "cd" * 32}
    r = stack.replay_once(ctx, "vcan", "vcan-1")
    assert got["played"][-1][-1] == str(tmp_path / "in" / "carla.log") and got["framed"] == [tmp_path / "in" / "carla.log"]
    assert got["sha"] == "cd" * 32 and r["vcan_capture"]["identical"] is True


def test_carla_provenance_is_reported_never_required(tmp_path, monkeypatch):
    other = {m: "0" * 64 for m in stack.CARLA_ENCODER_MODULES}
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _rig, _ctx, man = _frozen_carla(tmp_path / "a", monkeypatch, encoder_sha256=other)
    prov = man["recording"]["carla"]
    assert "sigsim" not in man["recording"]
    assert prov["recording_encoder_sha256"] == other and prov["current_equals_recording"] is False
    assert prov["current_sha256"] == {m: stack.sha256_file(REPO / m) for m in stack.CARLA_ENCODER_MODULES}
    _rig, _ctx, man = _frozen_carla(tmp_path / "b", monkeypatch)        # a trip without encoder_sha256, as a rewrite's is (inject's TRIP_KEPT)
    assert man["recording"]["carla"]["recording_encoder_sha256"] is None
    assert man["recording"]["carla"]["current_equals_recording"] is False
    now = {m: stack.sha256_file(REPO / m) for m in stack.CARLA_ENCODER_MODULES}
    assert stack.carla_provenance({"encoder_sha256": now})["current_equals_recording"] is True


CARLA_SEGMENTS = [["start", 0, 40], ["route drive", 40, 100], ["hard brake", 100, 160], ["stopped", 160, 200], ["reverse", 200, 260],
                  ["reverse stop", 260, 280], ["stopped in reverse", 280, 300]]


def test_a_carla_trip_meets_the_oracle_and_one_that_does_not_is_refused_before_anything_starts(tmp_path, monkeypatch):
    """Spec-2 5 item 5: replaycheck's one hard brake and the vehicle moving after it. A CARLA trip's route drive and
    reverse segments meet it unchanged; without its hard brake, with two, or with nothing moving after it, prepare refuses
    before a run directory is made."""
    d, line, _sha = _recording(tmp_path, gen="carla", segments=CARLA_SEGMENTS)
    assert stack.recording_summary(d, line)["hard_brake_ms"] == [100, 160]
    for i, segs in enumerate([[s for s in CARLA_SEGMENTS if s[0] != "hard brake"], CARLA_SEGMENTS + [["hard brake", 300, 320]]]):
        (tmp_path / str(i)).mkdir()
        bad, bline, _ = _recording(tmp_path / str(i), gen="carla", segments=segs)
        with pytest.raises(stack.StackError, match="'hard brake' segments"):
            stack.recording_summary(bad, bline)
    (tmp_path / "late").mkdir()
    rig = _prepare_rig(tmp_path / "late", monkeypatch, frozen=True, gen="carla", hard_brake=(100, 300))
    with pytest.raises(stack.StackError, match="windows cannot be derived"):
        _prepare(rig, "c", bridge="broker")


def test_a_carla_recording_on_a_pre_freeze_generation_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    rig = _prepare_rig(tmp_path, monkeypatch, bridge=True, layer_default=SYN_L_MM, gen="carla", name="20260101-carla-7")
    with pytest.raises(stack.StackError, match="the generation has no carla vehicle layer"):
        _prepare(rig, "c", bridge="broker")
    assert not (rig.runs / "c").exists() and "log" not in rig.seen


def _stand_in_decode(db):
    """replaycheck.decode_recording's shape through a cantools stand-in (tests/test_sdv_phase7_contract.py's StandInDB):
    frames (t_ms, message, {signal: value}), each mapping path's values after its transform, half LSBs of 0."""
    line_rx = re.compile(r"^\((\d+)\.(\d{6})\) \S+ ([0-9A-F]{3})#([0-9A-F]*)$")

    def decode(log_path, dbc_path, mapping, transforms):
        by_signal: Dict[str, List[str]] = {}
        for p, block in mapping.items():
            by_signal.setdefault(block["signal"], []).append(p)
        values: Dict[str, List[Any]] = {p: [] for p in mapping}
        frames, t0 = [], None
        for ln in Path(log_path).read_text(encoding="ascii").splitlines():
            m = line_rx.match(ln)
            assert m is not None, ln
            t_us = int(m.group(1)) * 1_000_000 + int(m.group(2))
            t0 = t_us if t0 is None else t0
            msg = db.get_message_by_frame_id(int(m.group(3), 16))
            dec = dict(msg.decode(bytes.fromhex(m.group(4)), decode_choices=False, scaling=True))
            frames.append((int(round((t_us - t0) / 1000.0)), msg.name, dec))
            for sig, v in dec.items():
                for p in by_signal.get(sig, ()):
                    values[p].append(transforms[p](v))
        return {"values": values, "half_lsb": {p: 0.0 for p in mapping}, "frames": frames}
    return decode


@pytest.fixture(scope="module")
def fake_carla(tmp_path_factory):
    """WP1's fake take encoded by WP1's encoder against this tree's generation, and its injected twin by WP3a's injector,
    with tests/test_sdv_phase7_contract.py's builders and stand-ins (cantools and python-can are the sim venv's), in pytest's
    tmp only."""
    tp7 = importlib.import_module("test_sdv_phase7_contract")
    if tp7.C is None or not (GEN / "vss_contract.py").is_file():
        pytest.skip("needs the generated contract (sdv-out/gen)")
    rc_take, _carla, take = tp7.tsc.run_take(tmp_path_factory.mktemp("take"), name=tp7.NAME, seed=tp7.SEED)
    assert rc_take == 0
    out = tmp_path_factory.mktemp("rec") / tp7.NAME
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tp7.encode, "load_dbc", lambda contract, path=None: tp7.tsc.FakeDb())
        mp.setattr(tp7.encode, "read_log", tp7.tsc.fake_read_log)
        res = tp7.encode.record(take, out, tp7.NAME, contract=tp7.C)
    assert res["recorded"] is True and res["verify"]["ok"] is True, res["verify"]["problems"]
    db = tp7.StandInDB(tp7.tsbs.SLICE_TEXT)
    built = tp7.inj.build(out, tp7.INJ_NAME, db, tp7.C, tp7.inj.bs.SLICE_DBC)
    dest = tmp_path_factory.mktemp("inj") / tp7.INJ_NAME
    tp7.inj.write(built, dest)
    return types.SimpleNamespace(dir=out, inj=dest, db=db, C=tp7.C)


def _real_gen_prepare(rec_dir, db, tmp_path, monkeypatch, bridge="broker"):
    """Context.prepare on rec_dir against this tree's generation and slice.dbc (no Docker: the two docker calls, time_sync
    and the decode stand in; the DBC from a cache in tmp_path holding the repo's slice.dbc)."""
    sha = stack.sha256_file(stack.SLICE_DBC)
    (tmp_path / "cache" / "dbc").mkdir(parents=True)
    shutil.copyfile(stack.SLICE_DBC, tmp_path / "cache" / "dbc" / ("%s.dbc" % sha))
    for name in ("SDV_HOST_ROLE", "SDV_CONTAINER_CPUSET", "SDV_AFTER_START"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(stack, "RECORDING_DIR", rec_dir)
    monkeypatch.setattr(stack, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(stack, "docker", lambda *a, **_kw: subprocess.CompletedProcess(a, 0, "27.0\n", ""))
    monkeypatch.setattr(stack, "time_sync", lambda: {"daemon": "none", "synchronised": False})
    monkeypatch.setattr(rc, "decode_recording", _stand_in_decode(db))
    ctx = stack.Context(tmp_path / "runs" / "r", None, bridge)
    return ctx, ctx.prepare(pull=False, build=False)


@NEEDS_GEN
@pytest.mark.parametrize("which", ["honest", "injected"])
def test_a_carla_recording_of_the_fake_take_prepares_against_this_trees_generation(fake_carla, tmp_path, monkeypatch, which):
    rec_dir = fake_carla.dir if which == "honest" else fake_carla.inj
    ctx, man = _real_gen_prepare(rec_dir, fake_carla.db, tmp_path, monkeypatch)
    in_dir = tmp_path / "runs" / "r" / "in"
    assert sorted(os.listdir(in_dir)) == ["can-provider.ini", "carla.log", "slice.dbc", "vss-can-mapping.json", "vss-databroker.json"]
    gm = json.loads((GEN / "manifest.json").read_text(encoding="utf-8"))
    assert (in_dir / "vss-databroker.json").read_bytes() == (GEN / gm["databroker_catalogues"]["carla"]).read_bytes()
    pid = int(fake_carla.C.LIVE_DEFAULT_PROFILE["carla"])
    l_mm = {int(p["id"]): p for p in fake_carla.C.PROFILES}[pid]["l_mm"]
    assert ctx.wheelbase == dict(ctx.wheelbase, served=True, value_mm=l_mm), ctx.wheelbase
    line = json.loads((rec_dir / "manifest-line.json").read_text(encoding="ascii"))
    h = ctx.run_header("vcan-1", "vcan")
    assert (h["run_type"], h["profile_id"], h["source_rtf"]) == ("carla", pid, line["source"]["rtf"])
    assert ctx.check_header(h)[1], ctx.check_header(h)
    assert man["catalogue"]["vehicle_layer_sha256"] == "sha256:" + stack.sha256_file(GEN / gm["vehicle_layers"]["carla"]["file"])
    enc = man["recording"]["carla"]["recording_encoder_sha256"]
    assert (enc is None) is (which == "injected"), "a rewrite's trip drops the encoder's hashes"


@NEEDS_GEN
def test_the_bridges_start_check_passes_profile_3_with_the_carla_catalogue_and_fails_with_the_sigsim_one():
    """Spec-2 5's tests: the broker source's Wheelbase start check (sdv/bridge/bridge_sources.py) on profile 3 against what
    each generated catalogue serves (its default: databroker 0.7.1 serves an unwritten attribute's default), and the stack's
    prediction of the same."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for d in (REPO / "sdv" / "frame", REPO / "sdv" / "bridge"):
            if str(d) not in sys.path:
                sys.path.insert(0, str(d))
        import bridge_sources as bsrc
    finally:
        sys.dont_write_bytecode = saved
    c = stack.load_contract()
    gm = json.loads((GEN / "manifest.json").read_text(encoding="utf-8"))
    pid = int(c.LIVE_DEFAULT_PROFILE["carla"])
    l_mm = {int(p["id"]): p for p in c.PROFILES}[pid]["l_mm"]

    class Client:
        def __init__(self, served):
            self.served = served

        def value_types(self, paths):
            return dict(zip(c.SLOT_PATHS, c.SLOT_DATATYPES))

        def get_value(self, path):
            assert path == bsrc.WHEELBASE_PATH
            return (self.served is not None, self.served)
    trees = {rt: json.loads((GEN / f).read_text(encoding="utf-8")) for rt, f in gm["databroker_catalogues"].items()}
    served = {rt: stack.catalogue_default(t, attr.WHEELBASE) for rt, t in trees.items()}
    rec = bsrc.BrokerSource(Client(served["carla"]), c).start_checks(l_mm)
    assert rec == dict(rec, served=True, value_mm=l_mm), rec
    with pytest.raises(bsrc.BridgeError, match="not the profile's L"):
        bsrc.BrokerSource(Client(served["sigsim"]), c).start_checks(l_mm)
    vehicle = {"name": "vehicle.toyota.prius", "wheelbase_mm": l_mm}
    assert stack.served_wheelbase(trees["carla"], l_mm, vehicle, None)["value_mm"] == l_mm
    with pytest.raises(stack.StackError, match="not the profile's L"):
        stack.served_wheelbase(trees["sigsim"], l_mm, vehicle, None)


@NEEDS_GEN
@NEEDS_CARLA_PAIR
def test_the_real_carla_pair_passes_the_stacks_recording_checks():
    """Read only: WP5a's pair (spec-2 2.3's CARLA_HONEST and its -inj twin) by the stack's own checks: identity by
    carla.log, the seed, the summary's one hard brake, the run type's generation pair, and the line's wheelbase, profile 3's
    L and the carla catalogue's default all one value. Nothing is decoded, staged or run."""
    c = stack.load_contract()
    gm = json.loads((GEN / "manifest.json").read_text(encoding="utf-8"))
    pair = stack.generation_pair(gm, "carla")
    tree = json.loads((GEN / pair["catalogue"]).read_text(encoding="utf-8"))
    for d in (CARLA_HONEST_DIR, CARLA_HONEST_DIR.parent / (CARLA_HONEST_DIR.name + "-inj")):
        rec = stack.recording_identity(d)
        line = rec["manifest_line"]
        assert (rec["log_name"], rec["run_type"], line["profile_id"]) == ("carla.log", "carla", int(c.LIVE_DEFAULT_PROFILE["carla"]))
        assert stack.recording_seed(line, None) == line["source"]["params"]["seed"]
        summ = stack.recording_summary(d, line)
        assert summ["hard_brake_ms"] == list(rc.hard_brake_segment(summ["trip"]))
        l_mm = {int(p["id"]): p for p in c.PROFILES}[line["profile_id"]]["l_mm"]
        assert line["source"]["vehicle"]["wheelbase_mm"] == l_mm == stack.catalogue_default(tree, attr.WHEELBASE)
        assert set(line["source"]["rtf"]) == {"min", "mean", "max"}


# The run's records name what the run used (the WP3b review's findings): the guest image's own build file, the run
# type's catalogue in the load check, and the CARLA feeder as the CAN provider's upstream.

@pytest.mark.parametrize("image, build", [
    ("ifs-vss.bin", "ipc-test/qnx-safety-monitor/ifs-vss.build"),
    ("ifs-vss-carla.bin", "ipc-test/qnx-safety-monitor/ifs-vss-carla.build"),
    ("ifs-ctl.bin", "ipc-test/qnx-safety-monitor/ifs-ctl.build"),
], ids=["ifs-vss", "ifs-vss-carla", "ifs-ctl"])
def test_a_guest_components_started_by_names_the_build_file_of_its_image(tmp_path, monkeypatch, image, build):
    """Guest mode's component names the build file that made the image it ran (spec-2 2.3: plan carla's image is
    ifs-vss-carla.bin), never ifs-vss.build for every image."""
    monkeypatch.setattr(stack, "local_ipv4", lambda: [])
    (tmp_path / image).write_bytes(b"a stand-in image")
    comp = stack.guest_component({"host": GUEST, "image": tmp_path / image})
    assert comp["image"] == image and comp["started_by"] == "%s (qnx-safety-monitor 7160 svc 500)" % build, comp["started_by"]


def test_a_guest_image_of_another_name_names_no_build_file_of_this_tree(tmp_path, monkeypatch):
    """An image whose name is not in the table (the tests' stand-ins, any other image) names no build file: the record says
    only that the image's own build file started the monitor so."""
    monkeypatch.setattr(stack, "local_ipv4", lambda: [])
    (tmp_path / "ifs-stand-in.bin").write_bytes(b"a stand-in image")
    got = stack.guest_component({"host": GUEST, "image": tmp_path / "ifs-stand-in.bin"})["started_by"]
    assert ".build" not in got and "ifs-vss" not in got, got
    assert got == "the image's own build file, not one this tree names (qnx-safety-monitor 7160 svc 500)", got


def test_the_guest_build_table_is_every_build_file_that_starts_the_vss_monitor():
    """GUEST_IMAGE_BUILDS holds exactly the build files of this tree whose start lines run `qnx-safety-monitor 7160 svc 500`,
    each under its image's name (its stem)."""
    d = REPO / "ipc-test" / "qnx-safety-monitor"
    start = re.compile(r"^/proc/boot/qnx-safety-monitor 7160 svc 500 &$", re.M)
    starts = sorted("ipc-test/qnx-safety-monitor/" + p.name for p in d.glob("*.build")
                    if start.search(p.read_text(encoding="utf-8", errors="replace")))
    assert sorted(stack.GUEST_IMAGE_BUILDS.values()) == starts and len(starts) == 3, starts
    assert all(Path(image).suffix == ".bin" and Path(image).stem == Path(build).stem for image, build in stack.GUEST_IMAGE_BUILDS.items())


def _s2_cache(cache):
    """The stage-1 S2 check's two files loadcheck reads, synthetic, under cache/s2-check."""
    (cache / "s2-check").mkdir(parents=True, exist_ok=True)
    (cache / "s2-check" / "b-mapping.json").write_text(json.dumps(_tree_with_enum_nodes(ENUM_NODES)), encoding="utf-8")
    (cache / "s2-check" / "overlay.vspec").write_text("# a synthetic overlay\n", encoding="utf-8")


def test_loadcheck_on_a_carla_run_also_loads_the_catalogue_the_run_staged(tmp_path, monkeypatch):
    """The load check loads the generation's sigsim catalogue as before and, for a run whose run type stages another
    (spec-2 2.2: databroker_catalogues[<run type>]), that one too; a sigsim run's load check is the four of before."""
    (tmp_path / "c").mkdir()
    rig, ctx, _man = _frozen_carla(tmp_path / "c", monkeypatch)
    _s2_cache(stack.CACHE)
    seen: List[Any] = []
    monkeypatch.setattr(stack, "load_catalogue", lambda _ctx, name, path, _probe, _out: seen.append((name, Path(path))) or {"name": name})
    res = stack.loadcheck(ctx, tmp_path / "out-c")
    assert seen[:2] == [("6.0-databroker", rig.gen / "vss-databroker.json"), ("6.0-databroker-carla", rig.gen / CARLA_CATALOGUE)], seen
    assert [n for n, _p in seen[2:]] == ["6.0-mapping", "6.1-mapping", "6.1-databroker"]
    assert [c["name"] for c in res["catalogues"]] == [n for n, _p in seen]
    assert (rig.runs / "c" / "in" / "vss-databroker.json").read_bytes() == (rig.gen / CARLA_CATALOGUE).read_bytes()
    seen.clear()
    (tmp_path / "s").mkdir()
    srig = _prepare_rig(tmp_path / "s", monkeypatch, frozen=True)
    sctx, _sman = _prepare(srig, "s", bridge="broker")
    _s2_cache(stack.CACHE)
    stack.loadcheck(sctx, tmp_path / "out-s")
    assert [n for n, _p in seen] == ["6.0-databroker", "6.0-mapping", "6.1-mapping", "6.1-databroker"]
    assert seen[0][1] == srig.gen / "vss-databroker.json"


def test_a_carla_runs_can_provider_rows_name_the_carla_feeder_as_their_upstream(tmp_path, monkeypatch):
    """attribution-table section 4's carla column: the CAN provider's rows of a CARLA run name the feeder (its version, town,
    seed and vehicle, from the line), never sigsim; every other column and row is attribution.scenario_rows' own."""
    rig, ctx, _man = _frozen_carla(tmp_path, monkeypatch)
    want = "carla-feeder (0.9.16, Town01, seed 7, carla-ego)"
    own = json.loads((rig.runs / "c" / "ownership.json").read_text(encoding="utf-8"))
    can = [r for r in own["rows"] if r["writer"] == attr.CAN_PROVIDER]
    assert can and [r["upstream"] for r in can] == [want] * len(can), [r["upstream"] for r in can]
    assert not [r for r in own["rows"] if "sigsim" in r["upstream"]], own["rows"]
    ids = {r["writer"]: "sha256:" + "ab" * 32 for r in ctx.rows}          # the writers' image IDs, synthetic (nothing is built)
    run_can = [r for r in attr.run_rows(ctx.rows, ids) if r["writer"] == attr.CAN_PROVIDER]
    assert [r["upstream"] for r in run_can] == [want] * len(can)
    plain = attr.scenario_rows(ctx.catalogue, ctx.mapping, ctx.dbc, ctx.mock_writes, attr.APP, ctx.hz.WRITES, list(stack.MONITOR_DISPLAY),
                               ctx.recorded, 7, bridge_writes=ctx.bridge_writes, vehicle_layer=CARLA_LAYER)
    assert [dict(r, upstream=None) for r in own["rows"]] == [dict(r, upstream=None) for r in plain]
    assert [list(r) for r in ctx.rows] == [list(r) for r in plain], "the keys and their order are attribution's"


@NEEDS_GEN
def test_the_fake_takes_rows_name_the_feeder_with_the_encoders_version_town_and_vehicle(fake_carla, tmp_path, monkeypatch):
    tp7 = importlib.import_module("test_sdv_phase7_contract")
    ctx, _man = _real_gen_prepare(fake_carla.dir, fake_carla.db, tmp_path, monkeypatch)
    want = "carla-feeder (%s, %s, seed %d, %s)" % (tp7.encode.VERSION, tp7.encode.TOWN, ctx.seed, tp7.encode.BLUEPRINT)
    ups = {r["upstream"] for r in ctx.rows if r["writer"] == attr.CAN_PROVIDER}
    assert ups == {want}, ups


def _sigsim_run_text(tmp_path, monkeypatch):
    """A synthetic sigsim run as the stack makes it on the frozen rig, normalized (the rig's path, the tree's, the clock's
    times, the run directories' dates, the host user, the stack files' hashes): its in/ file names and bytes, its run manifest and
    scenario table, the run header and C12a in each bridge mode, the scenario rows with image IDs, and every container's
    argument vector in both feeds (the bridge's in each mode). Uses only what the base's stack.py has."""
    for name in ("SDV_HOST_ROLE", "SDV_CONTAINER_CPUSET", "SDV_AFTER_START"):
        monkeypatch.delenv(name, raising=False)
    rig = _prepare_rig(tmp_path, monkeypatch, frozen=True)
    base = str(tmp_path)
    lines: List[str] = []

    def norm(t):
        t = t.replace(base, "<BASE>").replace(str(stack.REPO), "<REPO>").replace("%d:%d" % (os.getuid(), os.getgid()), "<UID>")
        t = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "<UTC>", t)
        return re.sub(r"(?<![0-9])20\d{6}(?=[T-])", "<DATE>", t)
    ctxs = {mode: _prepare(rig, mode, bridge=mode)[0] for mode in ("broker", "can", "replay")}     # before docker is replaced below
    for mode, ctx in ctxs.items():
        run = rig.runs / mode
        for f in sorted(os.listdir(run / "in")):
            lines.append("in\t%s\t%s\t%s" % (mode, f, stack.sha256_file(run / "in" / f)))
        man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        man["stack_files"] = sorted(man["stack_files"])          # their hashes are the code's, not the run's
        lines.append("manifest\t%s\t%s" % (mode, norm(json.dumps(man, sort_keys=True))))
        lines.append("ownership\t%s\t%s" % (mode, norm((run / "ownership.json").read_text(encoding="utf-8"))))
        feed = {"broker": "vcan", "can": "vcan", "replay": "none"}[mode]
        h = ctx.run_header("%s-1" % mode, feed)
        lines.append("header\t%s\t%s\t%s" % (mode, norm(json.dumps(h, sort_keys=True)), json.dumps(list(ctx.check_header(h)))))
        calls, rd = _argv_rig(ctx, tmp_path / ("argv-" + mode), monkeypatch)
        lines.append("rows\t%s\t%s" % (mode, norm(json.dumps(attr.run_rows(ctx.rows, ctx.image_ids()), sort_keys=True))))
        if mode == "broker":
            for f in stack.FEEDS:
                for comp in stack.NAMES:
                    stack.start(ctx, comp, f, rd, "t/run")
        stack.start(ctx, attr.BRIDGE, feed, rd, "t/run")
        lines += ["argv\t%s\t%s" % (mode, norm(json.dumps(c))) for c in calls]
    return "\n".join(lines) + "\n"


def test_a_sigsim_runs_in_argv_and_records_are_the_bases_byte_for_byte(tmp_path, monkeypatch):
    """Spec-2 5 item 2: a sigsim run's in/ file names and bytes, its argument vectors and its records, on a frozen
    generation that holds the carla pair beside sigsim's, retain the baseline bytes apart from the publication's
    simulator source identity (SIGSIM_BASE_GOLDEN above)."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    text = _sigsim_run_text(tmp_path, monkeypatch)
    got = (hashlib.sha256(text.encode("utf-8")).hexdigest(), text.count("\n"))
    (tmp_path / "sigsim-run-normalized.txt").write_text(text, encoding="utf-8")
    assert got == SIGSIM_BASE_GOLDEN, ("the sigsim run is not the base's: %d lines, sha256 %s (the base's: %d, %s); this run's "
                                       "normalized text is in %s" % (got[1], got[0], SIGSIM_BASE_GOLDEN[1], SIGSIM_BASE_GOLDEN[0],
                                                                     tmp_path / "sigsim-run-normalized.txt"))


# --- the ros feed (SDV Phase 8 WP3d; spec-2 2.5, 2.6, 2.12 and 5) -----------------------------------------------------

ROSVSS_DIR = REPO / "sdv" / "rosvss"
FEEDER_IMG = "sha256:" + "f3" * 32          # the feeder image's synthetic store ID (a synthetic images.json rosvss pin)
FEEDER_CFG = "sha256:" + "f4" * 32
AW_BASE = "sha256:" + "a7" * 32              # a synthetic autoware amd64 manifest digest
SYN_ROSVSS: Dict[str, Any] = {
    "about": "synthetic",
    "amd64": {"id": FEEDER_IMG, "config_digest": FEEDER_CFG, "tag": "sdv-rosvss:local", "lock": "sdv/rosvss/requirements.lock"},
    "labels": {"sdv.rosvss.base_digest": AW_BASE, "sdv.rosvss.lock_sha256": "1a" * 32, "sdv.rosvss.sources_sha256": "2b" * 32}}
SYN_AUTOWARE: Dict[str, Any] = {
    "about": "synthetic", "repo": "ghcr.io/autowarefoundation/autoware", "tag": "universe-jazzy-1.9.0", "release": "1.9.0",
    "trust": "first-use", "index_digest": "sha256:" + "a6" * 32,
    "amd64": {"manifest_digest": AW_BASE, "image_id": "sha256:" + "a6" * 32, "store": "containerd", "pulled": "2026-01-01"},
    "arm64": {"manifest_digest": "sha256:" + "a8" * 32, "pulled": None}, "entrypoint": "never run (2.12)"}
PS_LAYER, PS_CATALOGUE = "vehicle-planning-sim.vspec", "vss-databroker-planning-sim.json"     # generate.py's names
ROS_HOST = ("format=1\nlo.flags=LOOPBACK,UP,LOWER_UP\nnet.core.rmem_max=1111111\nnet.ipv4.ipfrag_time=22\n"
            "net.ipv4.ipfrag_high_thresh=3333333\n")      # synthetic values: no reading of any host (spec-2 14)
DB_REF = "ghcr.io/eclipse-kuksa/kuksa-databroker@" + IMAGES["upstream"]["kuksa-databroker"]["index_digest"]


def _rosvss_module(name: str) -> Any:
    """A module of sdv/rosvss (WP3a's, read only), loaded by its file under a name of this module's own. Its plain-name
    imports (update, mapping, vsswriter) are made with the package's directory first on sys.path; sys.path and those names
    in sys.modules are put back after, so no other test module sees a change."""
    key = "stack_tests_rosvss_" + name
    if key in sys.modules:
        return sys.modules[key]
    plain = ("update", "mapping", "vsswriter", "kuksa_out", "feeder_node")
    saved_path, saved_bytecode = list(sys.path), sys.dont_write_bytecode
    saved = {n: sys.modules.get(n) for n in plain}
    try:
        sys.path.insert(0, str(ROSVSS_DIR))
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location(key, str(ROSVSS_DIR / (name + ".py")))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved_path
        sys.dont_write_bytecode = saved_bytecode
        for n, m in saved.items():
            if m is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = m
    sys.modules[key] = mod
    return mod


def _ps_catalogue(layer_default=SYN_L_MM) -> Dict[str, Dict[str, Any]]:
    """A synthetic planning-sim catalogue: _synthetic()'s leaves, every Monitor.VssClaim leaf the bridge writes back, and every
    path of the feeder's planning-sim write set (its datatypes as mapping.DATATYPES gives them), the Wheelbase's default
    layer_default."""
    cat, _mapping, _dbc = _synthetic()
    for leaf in stack.bridge_core().WRITEBACK_LEAVES:
        cat.setdefault(attr.VSSCLAIM_PREFIX + leaf, {"type": "sensor", "datatype": "uint32"})
    m = _rosvss_module("mapping")
    for p in sorted(m.write_set(m.PLANNING_SIM)):
        cat.setdefault(p, {"type": "sensor", "datatype": m.DATATYPES[p]})
    cat["Vehicle.Chassis.Wheelbase"] = dict(cat["Vehicle.Chassis.Wheelbase"], default=layer_default)
    return cat


ROS_CONTRACT_PY = CONTRACT_PY + """\
PROJECT_BRANCH = "Vehicle.DualVm"
PROFILES = ({"id": 1, "l_mm": %(other)d, "source_vehicle": "sigsim-design-car"},
            {"id": 4, "l_mm": %(l)d, "source_vehicle": "synthetic-sample-vehicle"})
COMPILED_PROFILE_IDS = %(compiled)s
LIVE_DEFAULT_PROFILE = {"sigsim": 1, "planning-sim": 4}
"""


class RosDocker:
    """stack.docker replaced by a small model of the daemon for a ros run (no docker command runs). `run -d --name N --label
    K=V ...` makes N, running, with every label it was given and the image it names; `ps` lists by --filter label=KEY or
    label=KEY=VALUE (-a: every container, else the running ones), printing the names, or with --format {{index .Labels
    "KEY"}} that label's value; `rm -f` removes; `inspect -f FORMAT N` fills {{.State.Running}} and {{.Image}} in FORMAT (an
    exited container still names its image, as docker's does); `logs N` gives N's ready line; `top N` gives one pid;
    `image inspect` answers for the feeder's image (image: the record, None: no such image) and its tag (tag_id: the ID
    the tag names, None: no tag); `version` and `info` a word each. feeder "ready" logs its start record, "silent" never
    does, "stops" ends before it, "other" logs one record that is not the start record (OTHER); feeder_live N: the feeder
    answers the first N reads of its state running and has exited by the next (None: it runs on). Every run and rm goes
    into `events`."""

    READY = {"sdv-stack-databroker": "INFO databroker: Listening on 127.0.0.1:55555",
             "ros-vss-feeder": '{"databroker":"127.0.0.1:55555","event":"start","mono_ns":1,"writer":"ros-vss-feeder"}'}
    OTHER = '{"event":"refused","mono_ns":1,"reason":"a synthetic record that is not the start record","writer":"ros-vss-feeder"}'

    def __init__(self, feeder: str = "ready", image: Any = "default", tag_id: Any = FEEDER_IMG, feeder_live: Any = None) -> None:
        self.feeder, self.tag_id, self.feeder_live = feeder, tag_id, feeder_live
        self.image = ({"Id": FEEDER_IMG, "Architecture": "amd64", "RepoTags": ["sdv-rosvss:local"],
                       "Config": {"Labels": dict(SYN_ROSVSS["labels"]), "Entrypoint": ["/sdv-aw/aw-entrypoint.sh"], "User": "aw"}}
                      if image == "default" else image)
        self.containers: Dict[str, Dict[str, Any]] = {}
        self.calls: List[List[str]] = []
        self.events: List[str] = []

    def __call__(self, *args: str, check: bool = True, timeout: Any = 120) -> subprocess.CompletedProcess:
        a = list(args)
        self.calls.append(a)
        out, code = "", 0
        if a[:1] == ["run"]:
            name = a[a.index("--name") + 1]
            self.events.append("run " + name)
            labels = dict(a[i + 1].split("=", 1) for i, x in enumerate(a) if x == "--label")
            image = next(x for x in a if re.fullmatch(r"sha256:[0-9a-f]{64}", x) or DIGEST.search(x))
            silent = name == stack.FEEDER_CONTAINER and self.feeder not in ("ready", "other")
            line = self.OTHER if name == stack.FEEDER_CONTAINER and self.feeder == "other" else self.READY.get(name, "")
            self.containers[name] = {"labels": labels, "image": image, "line": "" if silent else line,
                                     "running": not (name == stack.FEEDER_CONTAINER and self.feeder == "stops")}
        elif a[:1] == ["ps"]:
            every = "-a" in a or "-aq" in a
            want = a[a.index("--filter") + 1][len("label="):] if "--filter" in a else None
            key, _, value = (want or "").partition("=")
            fmt = a[a.index("--format") + 1] if "--format" in a else None
            rows = []
            for name, c in self.containers.items():
                if (every or c["running"]) and (want is None or (key in c["labels"] and (not value or c["labels"][key] == value))):
                    m = re.fullmatch(r'\{\{index \.Labels "([^"]+)"\}\}', fmt or "")
                    rows.append(c["labels"].get(m.group(1), "") if m else name)
            out = "".join(r + "\n" for r in rows)
        elif a[:2] == ["rm", "-f"]:
            self.events.append("rm " + " ".join(sorted(a[2:])))
            for n in a[2:]:
                self.containers.pop(n, None)
        elif a[:2] == ["image", "inspect"]:
            ref = a[-1]
            info = self.image if ref == FEEDER_IMG else (dict(self.image, Id=self.tag_id) if ref == "sdv-rosvss:local" and self.tag_id
                                                          and self.image else None)
            out, code = (json.dumps([info]), 0) if info is not None else ("", 1)
        elif a[:1] == ["inspect"]:
            seen = self.containers.get(a[-1])
            fmt = a[a.index("-f") + 1]
            if seen is None:
                out, code = "", 1
            else:
                if "{{.State.Running}}" in fmt and a[-1] == stack.FEEDER_CONTAINER and self.feeder_live is not None:
                    if self.feeder_live <= 0:
                        seen["running"] = False
                    self.feeder_live -= 1
                out = fmt.replace("{{.State.Running}}", "true" if seen["running"] else "false").replace("{{.Image}}", seen["image"])
        elif a[:1] == ["logs"]:
            logged = self.containers.get(a[-1])
            out, code = (logged["line"] + "\n", 0) if logged is not None else ("", 1)
        elif a[:1] == ["top"]:
            out, code = ("PID\n%d\n" % (1000 + list(self.containers).index(a[1])), 0) if a[1] in self.containers else ("", 1)
        elif a[:1] in (["version"], ["info"]):
            out = "27.0"
        return subprocess.CompletedProcess(a, code, out, "")

    def runs(self) -> List[List[str]]:
        return [c for c in self.calls if c[:1] == ["run"]]


class FakeMonitor:
    """The native vss monitor's stand-in (start_monitor replaced): a pid, its argv, its allowance and a stop that counts."""

    def __init__(self, binary: Path, log: Path) -> None:
        self.pid, self.argv, self.log, self.port, self.stopped = 4242, [str(binary), "7160", "svc", "500"], log, 7160, 0

    def allowance(self) -> Dict[str, Any]:
        return {"pid": self.pid, "proto": "tcp", "port": self.port, "why": "the stand-in's"}

    def stop(self) -> int:
        self.stopped += 1
        return 0


def _hostcheck_fake(readings: List[Any], calls: List[List[str]], events: List[str]):
    """hostcheck_run replaced: a reading pops the next of readings (an int: that exit status, nothing printed); --compare
    BEFORE AFTER is the script's own rule on the two files (exit 1 and one `changed` line per setting that differs). Each
    call is kept in calls and, as "hostcheck", in events (the fake docker's), so their order shows."""
    def hostcheck_run(args):
        calls.append(["hostcheck"] + list(args))
        events.append("hostcheck" + ("" if not args else " " + args[0]))
        if not args:
            r = readings.pop(0)
            if isinstance(r, int):
                return subprocess.CompletedProcess(args, r, "", "hostcheck.sh: cannot read: sysctl -n net.core.rmem_max failed\n")
            return subprocess.CompletedProcess(args, 0, r, "")
        before, after = (dict(ln.split("=", 1) for ln in Path(f).read_text(encoding="utf-8").splitlines()) for f in args[1:])
        changed = ["changed %s before=%s after=%s" % (k, before[k], after[k]) for k in before if k != "format" and before[k] != after[k]]
        return subprocess.CompletedProcess(args, 1 if changed else 0, "".join(c + "\n" for c in changed), "")
    return hostcheck_run


def _ros_rig(tmp_path, monkeypatch, compiled=(1, 4), layer_default=SYN_L_MM, gen_pair=True, feeder="ready", image="default",
             tag_id=FEEDER_IMG, readings=None):
    """A synthetic planning-sim generation (manifest, catalogue, vehicle layer, contract; its sigsim catalogue another file
    than the planning-sim one, so a run that stages the wrong one shows), images.json with synthetic autoware and rosvss
    entries, a RosDocker as stack.docker, the host check, the native monitor (each FakeMonitor start_monitor makes is kept
    in monitors), pulls and builds replaced, the waits on files skipped (each kept in the fake's events), FEEDER_SETTLE_S 0
    (one read of the feeder's state after its start record). gen_pair False: a generation made before WP3b, with no
    planning-sim pair. readings: the host check's, in order (default: the same reading twice)."""
    _placement_env(monkeypatch)
    cat = _ps_catalogue(layer_default)
    gen = tmp_path / "gen"
    gen.mkdir()
    (gen / "vss-databroker.json").write_text(json.dumps(_nest(_synthetic()[0])), encoding="utf-8")    # the sigsim catalogue: not PS_CATALOGUE
    (gen / "vss-can-mapping.json").write_text(json.dumps(_nest(cat)), encoding="utf-8")
    (gen / PS_CATALOGUE).write_text(json.dumps(_nest(cat)), encoding="utf-8")
    text = "Vehicle.Chassis.Wheelbase:\n  default: %d\n" % layer_default
    (gen / PS_LAYER).write_text(text, encoding="utf-8")
    (gen / "vss_contract.py").write_text(ROS_CONTRACT_PY % {"l": SYN_L_MM, "other": SYN_OTHER_L_MM, "compiled": repr(tuple(compiled))},
                                         encoding="utf-8")
    overlay = tmp_path / "overlay.vspec"
    overlay.write_text("# a synthetic overlay\n", encoding="utf-8")
    dbc_sha = hashlib.sha256(TINY_DBC).hexdigest()
    man: Dict[str, Any] = {"inputs": {"overlay.vspec": stack.sha256_file(overlay), "slice.dbc": dbc_sha}, "outputs": {}}
    if gen_pair:
        man["vehicle_layers"] = {"planning-sim": {"file": PS_LAYER, "run_type": "planning-sim", "profile_id": 4,
                                                  "source_vehicle": "synthetic-sample-vehicle", "path": "Vehicle.Chassis.Wheelbase",
                                                  "default": layer_default}}
        man["databroker_catalogues"] = {"sigsim": "vss-databroker.json", "planning-sim": PS_CATALOGUE}
    for f in (PS_LAYER, PS_CATALOGUE, "vss-databroker.json"):
        data = (gen / f).read_bytes()
        man["outputs"][f] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    (gen / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    images = dict(json.loads(json.dumps(IMAGES)), autoware=json.loads(json.dumps(SYN_AUTOWARE)), rosvss=json.loads(json.dumps(SYN_ROSVSS)))
    fake = RosDocker(feeder=feeder, image=image, tag_id=tag_id)
    hc_calls: List[List[str]] = []
    pulled: List[Any] = []
    built: List[Any] = []
    monitors: List[Any] = []

    def pull_upstream(imgs):
        pulled.append(sorted(imgs["upstream"]))
        return {attr.DATABROKER: {"class": "platform", "form": "container", "image_id": "sha256:" + "db" * 32, "ref": DB_REF}}

    def build_local(imgs):
        built.append(sorted(imgs["local"]))
        return {attr.RECORDER: {"class": "platform", "form": "container", "image_id": REC_IMG, "tag": "t"}}

    def start_monitor(ctx, replay_dir, info):
        ctx.monitor = FakeMonitor(Path(ctx.components[stack.VSS_MONITOR]["path"]), replay_dir / "monitor.log")
        monitors.append(ctx.monitor)
        fake.events.append("monitor")
        info["monitor"] = {"pid": ctx.monitor.pid, "argv": ctx.monitor.argv}

    real_wait_for = stack.wait_for

    def wait_for(pred, timeout, what, poll=0.2):
        if what.startswith(("the witness's subscription", "the bridge's start record")):
            fake.events.append("waited for " + what.split(" (")[0])
            return
        real_wait_for(pred, timeout, what, poll)

    for name, value in (("GEN", gen), ("OVERLAY", overlay), ("RUNS", tmp_path / "runs"), ("docker", fake),
                        ("load_images", lambda: images),
                        ("hostcheck_run", _hostcheck_fake(list(readings or [ROS_HOST, ROS_HOST]), hc_calls, fake.events)),
                        ("time_sync", lambda: {"daemon": "none", "synchronised": False}), ("pull_upstream", pull_upstream),
                        ("build_local", build_local), ("start_monitor", start_monitor), ("wait_for", wait_for),
                        ("host_listeners", lambda: {"with_owners": True, "sockets": []}), ("host_uid", lambda: 1000),
                        ("START_TIMEOUT_S", 0.6),
                        ("bridge_image", lambda c, dbc, pin=None: {"class": "platform", "form": "container", "image_id": BRIDGE_IMG}),
                        ("build_native_monitor", lambda out: {"class": "platform", "form": "native", "path": str(out), "sha256": "0" * 64})):
        monkeypatch.setattr(stack, name, value)
    monkeypatch.setattr(stack, "FEEDER_SETTLE_S", 0.0)       # one read of the feeder's state after its start record
    return types.SimpleNamespace(gen=gen, runs=tmp_path / "runs", cat=cat, images=images, fake=fake, hc=hc_calls, pulled=pulled,
                                 built=built, monitors=monitors, dbc_sha=dbc_sha)


def _ros_ctx(rig, name="r", bridge="none", prepare=True, **kw):
    ctx = stack.RosContext(rig.runs / name, bridge, **kw)
    if prepare:
        ctx.prepare()
    return ctx


def _feeder_rows(rows):
    return sorted(r["path"] for r in rows if r["writer"] == attr.FEEDER)


def test_the_planning_sim_table_gives_the_feeder_the_slots_speed_and_the_overlay_and_the_wheelbase_to_the_catalogue():
    """Spec-2 2.5: ros-vss-feeder for SLOT_PATHS, Vehicle.Speed, every ControlCommand and every CtlClaim leaf; the claim
    bridge for VssClaim in broker mode (otherwise none); catalogue:vehicle-planning-sim.vspec for the Wheelbase; nothing
    else. The checks pass on it with the feeder's configured write set (mapping.py's, read) and the bridge's."""
    cat = _ps_catalogue()
    m = _rosvss_module("mapping")
    feeder_set = sorted(m.write_set(m.PLANNING_SIM))
    bridge_paths = sorted(attr.VSSCLAIM_PREFIX + leaf for leaf in stack.bridge_core().WRITEBACK_LEAVES)
    for mode, writes in (("none", []), ("broker", bridge_paths)):
        owned = feeder_set + writes
        rows = attr.planning_sim_rows(cat, PS_LAYER, bridge_writes=writes, witnessed=owned)
        by = {r["path"]: r for r in rows}
        assert len(by) == len(rows)
        assert _feeder_rows(rows) == feeder_set == sorted(list(attr.SLOT_PATHS) + ["Vehicle.Speed"] + [
            p for p in cat if p.startswith((attr.CONTROL_COMMAND_PREFIX, attr.CTLCLAIM_PREFIX))])
        vss = sorted(p for p in by if p.startswith(attr.VSSCLAIM_PREFIX))
        assert vss == bridge_paths and all(by[p]["writer"] == (attr.BRIDGE if mode == "broker" else "none") for p in vss)
        wb = by["Vehicle.Chassis.Wheelbase"]
        assert (wb["writer"], wb["ingress"]) == ("catalogue", "catalogue:" + PS_LAYER)
        assert set(by) == set(feeder_set) | set(bridge_paths) | {"Vehicle.Chassis.Wheelbase"}, "nothing else written"
        assert [by[p]["kind4_slot"] for p in attr.SLOT_PATHS] == [0, 1, 2, 3, 4]
        assert all(by[p]["cloud"] == "no" for p in by if p.startswith(attr.MONITOR_PREFIX))
        assert all(by[p]["ingress"] == "ros:" + attr.PLANNING_SIM_TOPICS.get(p, attr.VERDICT_TOPIC) for p in feeder_set)
        assert all(by[p]["recorded_in"] == ["vss-witness"] for p in owned) and wb["recorded_in"] == ["none"]
        ws = {attr.FEEDER: feeder_set}
        if writes:
            ws[attr.BRIDGE] = writes
        checks = {c[0]: c for c in attr.check_planning_sim(rows, cat, ws, PS_LAYER, bridge_mode=mode, witnessed=owned)}
        assert all(c[1] for c in checks.values()), checks
        assert {"C1", "C2", "C5", "C11", attr.PLANNING_SIM_CHECK} <= set(checks) and ("C3" in checks) == (mode == "broker")


@pytest.mark.parametrize("what, fails", [
    ("a second writer of a slot path", {"C2", "C2-planning-sim"}), ("the bridge writing a slot path too", {"C2", "C5"}),
    ("the feeder writing VssClaim", {"C2", "C2-planning-sim"}), ("a feeder row for VssClaim", {"C5", "C2-planning-sim"}),
    ("the feeder writing the wheelbase", {"C2", "C2-planning-sim"}), ("another writer of the wheelbase", {"C2", "C2-planning-sim"}),
    ("a wheelbase row by the feeder", {"C2-planning-sim"}), ("a wheelbase row from another layer", {"C2-planning-sim"}),
    ("a ControlCommand row by the bridge", {"C5", "C2-planning-sim"}), ("an extra row", {"C2-planning-sim"}),
    ("a CtlClaim row by the bridge", {"C5", "C2-planning-sim"}), ("the witness on another path set", {"C2-planning-sim"}),
    ("a row dropped", {"C3", "C2-planning-sim"}), ("the witness on one path more", {"C2-planning-sim"})])
def test_the_planning_sim_check_refuses_each_breach_of_the_table(what, fails):
    """Spec-2 2.5 and 13 (WP3d): a second writer of a slot path, a feeder write to VssClaim, any Wheelbase writer, a row the
    table gives another writer, a row it does not hold, a missing row, a witness that does not watch exactly the owned
    paths: each fails the checks named (broker mode, the bridge writing its write-back leaves), so a breach the design's
    checks catch is caught by the planning-sim table's own too, and the other way round, wherever both apply."""
    cat = _ps_catalogue()
    m = _rosvss_module("mapping")
    feeder_set = sorted(m.write_set(m.PLANNING_SIM))
    bridge_paths = sorted(attr.VSSCLAIM_PREFIX + leaf for leaf in stack.bridge_core().WRITEBACK_LEAVES)
    owned = feeder_set + bridge_paths
    rows = attr.planning_sim_rows(cat, PS_LAYER, bridge_writes=bridge_paths, witnessed=owned)
    ws: Dict[str, List[str]] = {attr.FEEDER: list(feeder_set), attr.BRIDGE: list(bridge_paths)}
    witnessed = list(owned)
    slot, vss, wb = attr.SLOT_PATHS[0], bridge_paths[0], "Vehicle.Chassis.Wheelbase"
    cc = next(p for p in feeder_set if p.startswith(attr.CONTROL_COMMAND_PREFIX))
    ctl = next(p for p in feeder_set if p.startswith(attr.CTLCLAIM_PREFIX))

    def rewrite(path, **kw):
        return [dict(r, **kw) if r["path"] == path else r for r in rows]
    if what == "a second writer of a slot path":
        ws[attr.CAN_PROVIDER] = [slot]
    elif what == "the bridge writing a slot path too":
        ws[attr.BRIDGE].append(slot)
    elif what == "the feeder writing VssClaim":
        ws[attr.FEEDER].append(vss)
    elif what == "a feeder row for VssClaim":
        rows = rewrite(vss, writer=attr.FEEDER)
        ws[attr.FEEDER].append(vss)
        ws[attr.BRIDGE].remove(vss)
    elif what == "the feeder writing the wheelbase":
        ws[attr.FEEDER].append(wb)
    elif what == "another writer of the wheelbase":
        ws["kuksa-mock-provider"] = [wb]
    elif what == "a wheelbase row by the feeder":
        rows = rewrite(wb, writer=attr.FEEDER, ingress="ros:/vehicle/status/velocity_status")
        ws[attr.FEEDER].append(wb)
    elif what == "a wheelbase row from another layer":
        rows = rewrite(wb, ingress="catalogue:vehicle-sigsim.vspec")
    elif what == "a ControlCommand row by the bridge":
        rows = rewrite(cc, writer=attr.BRIDGE)
        ws[attr.FEEDER].remove(cc)
        ws[attr.BRIDGE].append(cc)
    elif what == "an extra row":
        rows = rows + [dict(rows[0], path=hazard.HAZARD, node=attr.node_text(cat[hazard.HAZARD]), writer="kuksa-mock-provider",
                            kind4_slot="-")]
        ws["kuksa-mock-provider"] = [hazard.HAZARD]
    elif what == "a CtlClaim row by the bridge":
        rows = rewrite(ctl, writer=attr.BRIDGE)
        ws[attr.FEEDER].remove(ctl)
        ws[attr.BRIDGE].append(ctl)
    elif what == "the witness on another path set":
        witnessed.remove(slot)
    elif what == "the witness on one path more":
        witnessed.append(wb)          # a path no one owns (the catalogue sets the Wheelbase)
    elif what == "a row dropped":
        rows = [r for r in rows if r["path"] != slot]
        ws[attr.FEEDER].remove(slot)
        witnessed.remove(slot)
    checks = attr.check_planning_sim(rows, cat, ws, PS_LAYER, bridge_mode="broker", witnessed=witnessed)
    failed = {c[0] for c in checks if not c[1]}
    assert attr.PLANNING_SIM_CHECK == "C2-planning-sim" and fails <= failed, (what, fails, checks)


def test_the_planning_sim_table_on_this_trees_generation_is_the_feeders_write_set():
    """On the generated planning-sim catalogue (sdv-out/gen; skipped without it, failed under SDV_REQUIRE_GEN=1): the
    feeder's rows are mapping.py's planning-sim write set exactly, the topics the table names are the feeder's planning-sim
    subscriptions, and every check passes in both bridge modes with the bridge's real write-back paths."""
    path = GEN / PS_CATALOGUE
    if not path.is_file():
        if os.environ.get("SDV_REQUIRE_GEN") == "1":
            pytest.fail("SDV_REQUIRE_GEN=1 and the generated planning-sim catalogue is missing: %s" % path)
        pytest.skip("needs the generated planning-sim catalogue in %s (sdv/vss/README.md)" % GEN)
    cat = attr.leaf_nodes(json.loads(path.read_text(encoding="utf-8")))
    m = _rosvss_module("mapping")
    feeder = sorted(m.write_set(m.PLANNING_SIM))
    fn = _rosvss_module("feeder_node")
    assert set(attr.PLANNING_SIM_TOPICS.values()) | {attr.VERDICT_TOPIC} == {s[0] for s in fn.subscriptions(m.PLANNING_SIM)}
    assert attr.FEEDER == m.WRITER and stack.rosvss_mapping().write_set(m.PLANNING_SIM) == m.write_set(m.PLANNING_SIM)
    for mode in ("none", "broker"):
        writes = stack.bridge_writes(stack.load_contract()) if mode == "broker" else []
        owned = feeder + writes
        rows = attr.planning_sim_rows(cat, PS_LAYER, bridge_writes=writes, witnessed=owned)
        assert _feeder_rows(rows) == feeder
        ws = {attr.FEEDER: feeder, **({attr.BRIDGE: writes} if writes else {})}
        checks = attr.check_planning_sim(rows, cat, ws, PS_LAYER, bridge_mode=mode, witnessed=owned)
        assert all(c[1] for c in checks), checks


def test_the_feeder_is_no_container_of_the_lists_the_harnesses_hold_and_its_names_are_2_1s():
    """The feeder is one more container a ros run starts, outside NAMES and CONTAINERS (the six of Phase 1, the bridge and
    the connector, which run-vss-suite.sh's and the drill harness's fallback lists hold equal); its container's name and
    writer are spec-2 2.1's; the ros feed is no member of FEEDS, so exit-test's default feeds stay the two."""
    assert stack.FEEDER_CONTAINER == "ros-vss-feeder" == attr.FEEDER and stack.FEEDER == attr.FEEDER
    assert stack.FEEDER_CONTAINER not in stack.CONTAINERS.values() and stack.FEEDER not in stack.CONTAINERS
    assert stack.FEEDS == ("dumpfile", "vcan") and stack.ROS_FEED == "ros" and stack.ROS_RUN_TYPE == "planning-sim"
    assert stack.net_of("ros", attr.DATABROKER) == ["--network", "host"] == stack.net_of("ros", stack.WITNESS) == \
        stack.net_of("ros", attr.BRIDGE)
    assert stack.net_of("dumpfile", attr.DATABROKER) == ["--network", "none"]


@pytest.mark.parametrize("argv, why", [
    (["up", "--feed", "ros"], "--feed ros needs --run-type planning-sim"),
    (["up", "--feed", "ros", "--run-type", "carla-autoware"], "CAN path"),
    (["up", "--feed", "ros", "--run-type", "sigsim"], "--feed ros needs --run-type planning-sim"),
    (["up", "--feed", "vcan", "--run-type", "planning-sim"], "--run-type is the ros feed's"),
    (["up", "--run-type", "planning-sim"], "--run-type is the ros feed's"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--app", "external"], "--app"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--app", "stack"], "--app"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--connector"], "--connector"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--images", "loaded"], "amd64"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--seed", "7"], "--seed"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--monitor", "guest"], "--monitor"),
    (["up", "--feed", "vcan", "--bridge", "broker"], "--bridge"),
    (["up", "--feed", "vcan", "--monitor", "native"], "--monitor"),
    (["replay", "--feed", "ros"], "replay"),
    (["exit-test", "--feeds", "dumpfile", "ros"], "exit-test"),
    (["up", "--feed", "ros", "--run-type", "carla"], "--feed ros needs --run-type planning-sim"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--guest-host", "192.0.2.1"], "--monitor"),
    (["up", "--feed", "dumpfile", "--guest-console", "c"], "--monitor"),
    (["up", "--feed", "vcan", "--bridge", "none"], "--bridge"),
    (["exit-test", "--feeds", "ros"], "exit-test"),
    (["replay", "--feed", "ros", "--bridge", "broker"], "replay"),
    (["up", "--feed", "ros", "--run-type", "planning-sim", "--bridge", "broker", "--guest-host", "192.0.2.1"], "guest mode's")])
def test_the_ros_feed_is_refused_with_its_reason_before_anything_is_written_or_started(tmp_path, monkeypatch, argv, why):
    """Spec-2 2.5's refusals that the command line decides: --feed ros with another run type (a carla-autoware drive's
    standard signals come from the CAN path) or none; --run-type with another feed; replay, exit-test, --app and --connector
    with --feed ros; and this package's own: --images loaded (the feeder's image is amd64 only), --seed (no recording),
    the monitor options without --bridge broker, the guest's options without --monitor guest (with a bridge: they are
    guest mode's, never the native monitor's), and --bridge or the monitor options on another feed's up (which never took
    them). Each before a context is made, docker is asked or the run directory is written."""
    def touched(*_a, **_kw):
        raise AssertionError("the stack went on though the run was to be refused")
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    for name in ("Context", "RosContext", "docker", "remove_stack", "hostcheck_run"):
        monkeypatch.setattr(stack, name, touched)
    _placement_env(monkeypatch)
    with pytest.raises(stack.StackError) as e:
        stack.main(argv + ["--name", "x"])
    assert why in str(e.value), str(e.value)
    assert not (tmp_path / "runs").exists()


def test_the_ros_feed_is_refused_off_the_pc(tmp_path, monkeypatch):
    """The feeder's image is amd64 only (spec-2 section 0 item 5): a ros run on any other host role is refused before
    anything is written."""
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "RosContext", lambda *a, **k: (_ for _ in ()).throw(AssertionError("made")))
    for role in ("a1-metal", "c7g-metal", "orin"):
        _placement_env(monkeypatch, role=role, cpuset="3", hook="true")
        with pytest.raises(stack.StackError, match="amd64"):
            stack.main(["up", "--feed", "ros", "--run-type", "planning-sim", "--name", "x"])
    assert not (tmp_path / "runs").exists()


def test_main_hands_the_ros_feed_its_bridge_and_monitor_options_and_leaves_every_other_up_as_it_was(tmp_path, monkeypatch):
    """up --feed ros makes a RosContext with the bridge mode, the monitor mode (native when none is given) and the three
    guest options as given (step3.py's names), every time, so that Context's own refusals see them; up on the other feeds
    makes the Context it made before, with no bridge."""
    seen: List[Any] = []

    class Stop(Exception):
        pass

    def ros_context(run_dir, bridge="none", **kw):
        seen.append(("ros", bridge, kw))
        raise Stop()

    def context(run_dir, seed, bridge, **kw):
        seen.append(("ctx", bridge, kw))
        raise Stop()
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(stack, "RosContext", ros_context)
    monkeypatch.setattr(stack, "Context", context)
    _placement_env(monkeypatch)
    base = ["up", "--feed", "ros", "--run-type", "planning-sim"]
    native = {"monitor": "native", "guest_host": None, "guest_console": None, "guest_image": None}
    for i, (args, want) in enumerate((
            (base, ("ros", "none", native)),
            (base + ["--bridge", "none"], ("ros", "none", native)),
            (base + ["--bridge", "broker"], ("ros", "broker", native)),
            (base + ["--bridge", "broker", "--monitor", "native"], ("ros", "broker", native)),
            (base + ["--bridge", "broker", "--monitor", "guest", "--guest-host", "192.0.2.10", "--guest-console", "c", "--guest-image", "i"],
             ("ros", "broker", {"monitor": "guest", "guest_host": "192.0.2.10", "guest_console": "c", "guest_image": "i"})),
            (["up", "--feed", "vcan"], ("ctx", "none", {})), (["up"], ("ctx", "none", {})))):
        with pytest.raises(Stop):
            stack.main(args + ["--name", "n%d" % i])
        assert seen[-1] == want, (args, seen[-1])


def test_prepare_refuses_a_generation_without_the_planning_sim_pair_before_anything_is_written(tmp_path, monkeypatch):
    rig = _ros_rig(tmp_path, monkeypatch, gen_pair=False)
    with pytest.raises(stack.StackError, match="planning-sim"):
        _ros_ctx(rig)
    assert not rig.runs.exists() and not rig.fake.runs()


def test_prepare_refuses_broker_mode_while_profile_4_is_not_compiled_before_anything_is_written(tmp_path, monkeypatch):
    """Spec-2 2.5: --bridge broker while the planning-sim live default (profile 4) is not compiled: every frame would get
    reason 8. Without a bridge the run goes on."""
    rig = _ros_rig(tmp_path, monkeypatch, compiled=(1,))
    with pytest.raises(stack.StackError, match="reason 8"):
        _ros_ctx(rig, "b", bridge="broker")
    assert not (rig.runs / "b").exists()
    _ros_ctx(rig, "n", bridge="none")
    assert (rig.runs / "n" / "manifest.json").is_file()


@pytest.mark.parametrize("which, why", [("absent", "not present"), ("id", "image ID"), ("labels", "sdv.rosvss.sources_sha256"),
                                        ("entrypoint", "entrypoint"), ("root", "root"), ("no-user", "root"), ("arm64", "amd64"),
                                        ("tag", "re-pin")])
def test_prepare_refuses_a_feeder_image_that_is_not_images_jsons(tmp_path, monkeypatch, which, why):
    """Spec-2 2.5: a feeder image whose ID is not images.json's is refused before anything is written: one that is not
    present, whose ID differs, whose labels are not the pin's, whose entrypoint is not the project's (the base's would
    run), that runs as root (or names no user), that is not amd64, or one whose tag names another build (rebuilt without a
    re-pin)."""
    good = RosDocker().image
    cfg = good["Config"]
    image = {"absent": None, "id": dict(good, Id="sha256:" + "e1" * 32),
             "labels": dict(good, Config=dict(cfg, Labels=dict(cfg["Labels"], **{"sdv.rosvss.sources_sha256": "3c" * 32}))),
             "entrypoint": dict(good, Config=dict(cfg, Entrypoint=["/docker-entrypoint.sh"])),
             "root": dict(good, Config=dict(cfg, User="root")), "no-user": dict(good, Config=dict(cfg, User="")),
             "arm64": dict(good, Architecture="arm64"), "tag": good}[which]
    rig = _ros_rig(tmp_path, monkeypatch, image=image, tag_id="sha256:" + "e2" * 32 if which == "tag" else FEEDER_IMG)
    with pytest.raises(stack.StackError) as e:
        _ros_ctx(rig)
    assert why in str(e.value), str(e.value)
    assert not rig.runs.exists() and not rig.fake.runs()


def test_prepare_refuses_a_host_user_that_is_not_the_images_aw(tmp_path, monkeypatch):
    rig = _ros_rig(tmp_path, monkeypatch)
    monkeypatch.setattr(stack, "host_uid", lambda: 1001)
    with pytest.raises(stack.StackError, match="uid"):
        _ros_ctx(rig)
    assert not rig.runs.exists()


@pytest.mark.parametrize("bridge", ["none", "broker"])
def test_prepare_records_the_run_type_the_feeders_image_its_base_the_catalogue_and_the_planning_sim_table(tmp_path, monkeypatch, bridge):
    """Spec-2 2.5: the run manifest records run_type planning-sim, the feeder's image ID, its base's digest and the
    catalogue's sha256; the planning-sim catalogue is staged as in/vss-databroker.json and ros-env.json's XML as
    in/cyclonedds.xml; only the databroker is pulled and only the recorder built (the witness's image); the scenario
    table is the planning-sim table and every check passes; the witness watches exactly the owned paths."""
    rig = _ros_rig(tmp_path, monkeypatch)
    ctx = _ros_ctx(rig, "p", bridge=bridge)
    run = rig.runs / "p"
    man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert man["run_type"] == "planning-sim" and man["feed"] == "ros"
    feed = man["ros_feed"]
    assert feed["run_type"] == "planning-sim" and feed["feeder_image_id"] == FEEDER_IMG and feed["feeder_base_digest"] == AW_BASE
    assert feed["catalogue_sha256"] == "sha256:" + stack.sha256_file(rig.gen / PS_CATALOGUE) == man["catalogue"]["databroker_json_sha256"]
    assert man["components"][attr.FEEDER]["image_id"] == FEEDER_IMG and man["components"][attr.FEEDER]["config_digest"] == FEEDER_CFG
    assert (rig.gen / "vss-databroker.json").read_bytes() != (rig.gen / PS_CATALOGUE).read_bytes(), "the rig's two catalogues differ"
    assert (run / "in" / "vss-databroker.json").read_bytes() == (rig.gen / PS_CATALOGUE).read_bytes()
    env = json.loads((REPO / "sdv" / "aw" / "ros-env.json").read_text(encoding="utf-8"))
    assert (run / "in" / "cyclonedds.xml").read_text(encoding="utf-8") == env["cyclonedds_single_host"]
    assert rig.pulled == [[attr.DATABROKER]] and rig.built == [[attr.RECORDER]]
    for comp in (attr.CAN_PROVIDER, attr.MOCK_PROVIDER, attr.APP, stack.CONNECTOR):
        assert comp not in man["components"], comp
    assert all(c[1] for c in man["scenario_checks"]), man["scenario_checks"]
    rows = json.loads((run / "ownership.json").read_text(encoding="utf-8"))["rows"]
    m = _rosvss_module("mapping")
    assert _feeder_rows(rows) == sorted(m.write_set(m.PLANNING_SIM))
    owned = sorted(r["path"] for r in rows if r["writer"] not in ("none", "catalogue"))
    assert ctx.witness_paths == owned and feed["witness_paths"] == owned
    assert (bridge == "broker") == any(r["writer"] == attr.BRIDGE for r in rows)
    assert man["bridge"]["mode"] == bridge and (stack.VSS_MONITOR in man["components"]) == (bridge == "broker")
    if bridge == "broker":
        assert man["bridge"]["wheelbase"]["served"] is True and man["bridge"]["wheelbase"]["value_mm"] == SYN_L_MM
    h = ctx.run_header("up", "ros")
    assert (h["run_type"], h["feed"], h["source_rtf"], h["recordings"]) == ("planning-sim", "ros", None, [])
    assert h["profile_id"] == (4 if bridge == "broker" else None) and h["profile_source"] == ("live-default" if bridge == "broker" else None)
    assert h["source_vehicle"] == {"name": "synthetic-sample-vehicle", "wheelbase_mm": SYN_L_MM} and ctx.check_header(h)[1], ctx.check_header(h)


def _ros_up(rig, bridge="none", name="u", **kw):
    ctx = _ros_ctx(rig, name, bridge=bridge, **kw)
    info = stack.up_ros(ctx, ctx.run_dir / "up", "%s/up" % ctx.run_dir.name)
    return ctx, info


@pytest.mark.parametrize("bridge", ["none", "broker"])
def test_up_ros_starts_the_databroker_the_witness_the_bridge_and_the_feeder_last_and_never_the_can_provider_mock_or_app(
        tmp_path, monkeypatch, bridge):
    """Spec-2 2.5: the host check is read before the first container starts; then the databroker, the witness, in broker
    mode the native monitor (first) and the claim bridge, and the feeder last, as the feed; never the CAN provider, the
    mock provider, the recorder's CAN path or an app; the listener snapshot counts the feeder's processes as the stack's;
    in broker mode up/monitor.json names the started monitor by its full path (the one down compares with /proc)."""
    rig = _ros_rig(tmp_path, monkeypatch)
    ctx, info = _ros_up(rig, bridge)
    ev = rig.fake.events
    starts = [e[4:] for e in ev if e.startswith("run ")]
    want = ["sdv-stack-databroker", "sdv-stack-witness"] + (["sdv-stack-bridge"] if bridge == "broker" else []) + ["ros-vss-feeder"]
    assert starts == want, ev
    assert (ev.index("monitor") < ev.index("run sdv-stack-databroker")) if bridge == "broker" else "monitor" not in ev
    assert ev[0] == "hostcheck" and ev.count("hostcheck") == 1, "one reading before any container; the after-reading is the sweep's"
    assert rig.hc == [["hostcheck"]] and (ctx.run_dir / "host-before.txt").read_text(encoding="utf-8") == ROS_HOST
    for name in (stack.NAMES[attr.CAN_PROVIDER], stack.NAMES[attr.MOCK_PROVIDER], stack.NAMES[attr.APP], stack.NAMES[attr.RECORDER]):
        assert name not in starts
    feeder_pid = 1000 + list(rig.fake.containers).index(stack.FEEDER_CONTAINER)
    assert feeder_pid in info["listeners"]["stack_pids"], info["listeners"]
    assert json.loads((ctx.run_dir / "up" / "listeners.json").read_text(encoding="utf-8"))["feed"] == "ros"
    table = json.loads((ctx.run_dir / "up" / "attribution.json").read_text(encoding="utf-8"))
    c8 = [c for c in table["checks"] if c[0] == "C8"]
    assert c8 and c8[0][1], table["checks"]
    witness = rig.fake.runs()[1]
    assert witness[-len(ctx.witness_paths):] == ctx.witness_paths
    if bridge == "broker":
        hdr = json.loads((ctx.run_dir / "up" / "bridge-header.json").read_text(encoding="utf-8"))
        assert hdr["profile_id"] == 4 and hdr["profile_source"] == "live-default" and hdr["run_type"] == "planning-sim"
        bridge_argv = rig.fake.runs()[2]
        assert bridge_argv[bridge_argv.index("--broker") + 1] == "127.0.0.1:55555"
        mon = json.loads((ctx.run_dir / "up" / "monitor.json").read_text(encoding="utf-8"))
        assert mon["pid"] == 4242 and ctx.monitor is None, "the native monitor is left running for down to stop"
        (started,) = rig.monitors          # down signals the pid only while /proc says it runs this binary: the full path, not its name
        assert mon["binary"] == ctx.components[stack.VSS_MONITOR]["path"] == started.argv[0] and Path(mon["binary"]).is_absolute(), mon


def test_up_ros_in_guest_mode_starts_no_native_monitor_points_the_bridge_at_the_guest_and_down_closes_the_run(tmp_path, monkeypatch):
    """Spec-2 2.5 runs the ros feed with the stack's existing monitor options: with --monitor guest (the guest's host,
    console and image given) the run starts and builds no native monitor (no monitor event, no up/monitor.json, the native
    monitor's component not in the manifest), the bridge's --host is the guest's address, the manifest holds the guest's
    component, and down closes the run (the sweep, then the host check read after and compared). The addresses are
    documentation values; this host's own are not read."""
    rig = _ros_rig(tmp_path, monkeypatch)
    console, image = _guest_files(tmp_path)
    monkeypatch.setattr(stack, "local_ipv4", lambda: [])
    assert _ros_main_up(rig, "--bridge", "broker", "--monitor", "guest", "--guest-host", GUEST, "--guest-console", str(console),
                        "--guest-image", str(image)) == 0
    (run,) = list(rig.runs.iterdir())
    ev = rig.fake.events
    assert "monitor" not in ev and rig.monitors == [] and not (run / "up" / "monitor.json").exists(), ev
    assert [e[4:] for e in ev if e.startswith("run ")] == ["sdv-stack-databroker", "sdv-stack-witness", "sdv-stack-bridge", "ros-vss-feeder"], ev
    bridge_argv = rig.fake.runs()[2]
    assert bridge_argv[bridge_argv.index("--host") + 1] == GUEST, bridge_argv
    man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert stack.VSS_MONITOR_GUEST in man["components"] and stack.VSS_MONITOR not in man["components"], sorted(man["components"])
    assert man["components"][stack.VSS_MONITOR_GUEST]["host"] == GUEST and man["bridge"]["monitor"] == "guest"
    assert stack.main(["down"]) == 0
    assert rig.fake.containers == {} and rig.hc[-1][1] == "--compare"
    assert (run / "host-after.txt").read_text(encoding="utf-8") == ROS_HOST
    assert json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_up_ros_gives_every_container_the_runs_cpuset_and_runs_the_after_start_hook_after_each_start_the_feeders_too(tmp_path, monkeypatch):
    """SDV_CONTAINER_CPUSET and SDV_AFTER_START (PLACEMENT) reach the ros feed's feeder as they reach every container of the
    stack: --cpuset-cpus right after the common flags, once, and the hook run with the container's name right after its
    docker run, so the log holds each start and its hook in order, the feeder's last. The hook is the stand-in of the other
    placement tests."""
    rig = _ros_rig(tmp_path, monkeypatch)
    env, _script, log = _hook(tmp_path, monkeypatch)
    _placement_env(monkeypatch, cpuset=PLACE_CPUSET, hook=env)
    daemon = stack.docker

    def docker(*args, **kw):
        if args[:1] == ("run",):
            with open(log, "a", encoding="utf-8") as f:
                f.write("docker run %s\n" % args[args.index("--name") + 1])
        return daemon(*args, **kw)
    monkeypatch.setattr(stack, "docker", docker)
    ctx, _info = _ros_up(rig)
    names = ["sdv-stack-databroker", "sdv-stack-witness", stack.FEEDER_CONTAINER]
    assert log.read_text(encoding="utf-8").splitlines() == [line for n in names for line in ("docker run " + n, "hook " + n)]
    assert [r["container"] for r in ctx.after_start_records] == names and all(r["exit"] == 0 for r in ctx.after_start_records)
    assert len(rig.fake.runs()) == len(names)
    for argv in rig.fake.runs():
        assert argv.count("--cpuset-cpus") == 1 and argv[argv.index("--cpuset-cpus") + 1] == PLACE_CPUSET, argv
    (feeder,) = [r for r in rig.fake.runs() if r[r.index("--name") + 1] == stack.FEEDER_CONTAINER]
    k = feeder.index(stack.COMMON[0])
    assert feeder[k:k + len(stack.COMMON) + 2] == stack.COMMON + ["--cpuset-cpus", PLACE_CPUSET], feeder


def test_the_feeders_docker_run_holds_common_and_2_12s_flags_and_none_of_the_forbidden_ones(tmp_path, monkeypatch):
    """Spec-2 2.5, 2.7, 2.12: the feeder by images.json's ID (never a tag) with --run-type planning-sim and the broker's
    loopback address; the stack's COMMON flags (every capability dropped, no-new-privileges), the host's network, --user
    aw, 2.7's environment (domain 73, Cyclone, the single-host XML by file, ROS_LOG_DIR under the run directory), its own
    entrypoint (no --entrypoint); never --privileged, --cap-add, a /proc/sys or /sys mount or the X11 socket."""
    rig = _ros_rig(tmp_path, monkeypatch)
    ctx, _info = _ros_up(rig)
    (argv,) = [r for r in rig.fake.runs() if r[r.index("--name") + 1] == "ros-vss-feeder"]
    i = argv.index(FEEDER_IMG)
    assert argv[i:] == [FEEDER_IMG, "/opt/sdv-rosvss/venv/bin/python", "/app/sdv/rosvss/feeder_node.py", "--run-type", "planning-sim",
                        "--databroker", "127.0.0.1:55555"], argv
    opts = argv[:i]
    k = opts.index(stack.COMMON[0])
    assert opts[k:k + len(stack.COMMON)] == stack.COMMON, opts
    assert opts[opts.index("--network") + 1] == "host" and opts[opts.index("--user") + 1] == "aw"
    labels = [opts[j + 1] for j, x in enumerate(opts) if x == "--label"]
    assert labels == ["%s=%s/up" % (stack.LABEL, ctx.run_dir.name), "%s=%s" % (stack.ROS_LABEL, ctx.run_dir)], labels
    env = [opts[j + 1] for j, x in enumerate(opts) if x == "-e"]
    assert env == ["ROS_DOMAIN_ID=73", "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp", "CYCLONEDDS_URI=file:///sdv-in/cyclonedds.xml",
                   "ROS_LOG_DIR=/sdv-ros-log"], env
    vols = [opts[j + 1] for j, x in enumerate(opts) if x == "-v"]
    assert vols == ["%s:/sdv-in:ro" % ctx.in_dir, "%s:/sdv-ros-log" % (ctx.run_dir / "up" / "ros-log")], vols
    joined = " ".join(argv)
    for flag in ("--privileged", "--cap-add", "--entrypoint", "-p", "--publish", "-P", "--publish-all"):
        assert flag not in opts and not [o for o in opts if o.startswith(flag + "=")], flag
    for word in ("/proc", ":/sys", "X11", "DISPLAY", "docker.sock", "0.0.0.0"):
        assert word not in joined, word
    assert not any(re.fullmatch(r"[a-z0-9._-]+/[a-z0-9._/-]+:[A-Za-z0-9_.-]+", a) or a == "sdv-rosvss:local" for a in argv)
    assert stack.aw_argv_problems(argv) == []


@pytest.mark.parametrize("change, why", [
    (lambda a: a[:2] + ["--privileged"] + a[2:], "--privileged"),
    (lambda a: a[:2] + ["--cap-add", "NET_ADMIN"] + a[2:], "--cap-add"),
    (lambda a: a[:2] + ["--cap-add=SYS_ADMIN"] + a[2:], "--cap-add"),
    (lambda a: a[:2] + ["-v", "/proc/sys:/proc/sys"] + a[2:], "/proc/sys"),
    (lambda a: a[:2] + ["--volume=/sys:/sys:rw"] + a[2:], "/sys"),
    (lambda a: a[:2] + ["--mount", "type=bind,src=/proc,dst=/host-proc"] + a[2:], "/proc"),
    (lambda a: a[:2] + ["-v", "/tmp/.X11-unix:/tmp/.X11-unix"] + a[2:], "X11"),
    (lambda a: a[:2] + ["-e", "DISPLAY=:0"] + a[2:], "X11"),
    (lambda a: [x for x in a if x not in ("--cap-drop", "ALL")], "--cap-drop ALL"),
    (lambda a: [x for x in a if x != "no-new-privileges"], "no-new-privileges"),
    (lambda a: [("root" if x == "aw" else x) for x in a], "--user aw"),
    (lambda a: a[:2] + ["--privileged=true"] + a[2:], "--privileged"),
    (lambda a: a[:2] + ["--cap-add=ALL"] + a[2:], "--cap-add"),
    (lambda a: a[:2] + ["--mount", "type=bind,source=/sys/fs/cgroup,target=/x"] + a[2:], "/sys"),
    (lambda a: a[:2] + ["--volume", "/proc:/p"] + a[2:], "/proc"),
    (lambda a: a[:2] + ["-e", "XAUTHORITY=/x"] + a[2:], "X11"),
    (lambda a: a[:2] + ["--env", "DISPLAY=:1"] + a[2:], "X11"),
    (lambda a: a[:2] + ["--user=root"] + a[2:], "--user aw"),
    (lambda a: a[:2] + ["-u", "root"] + a[2:], "the user given: root, aw"),
    (lambda a: a[:2] + ["-uroot"] + a[2:], "user given: root"),
    (lambda a: a[:2] + ["-du", "root"] + a[2:], "given: root, aw"),
    (lambda a: a[:2] + ["-v/proc:/x"] + a[2:], "/proc:/x"),
    (lambda a: a[:2] + ["-v", "/:/host"] + a[2:], "the host's root"),
    (lambda a: a[:2] + ["-v", "/var/run/docker.sock:/var/run/docker.sock"] + a[2:], "the docker socket"),
    (lambda a: a[:2] + ["--mount", "type=bind,source=/run/docker.sock,target=/d"] + a[2:], "docker socket mounted (type="),
    (lambda a: a[:2] + ["--pid", "host"] + a[2:], "--pid host"),
    (lambda a: a[:2] + ["--ipc=host"] + a[2:], "--ipc host"),
    (lambda a: a[:2] + ["--userns", "host"] + a[2:], "--userns host"),
    (lambda a: a[:2] + ["-eDISPLAY=:0"] + a[2:], "X11 (DISPLAY=:0)"),
    (lambda a: [("NET_RAW" if x == "ALL" else x) for x in a], "no --cap-drop ALL")])
def test_a_feeder_docker_run_with_a_forbidden_flag_is_refused_before_docker_runs(tmp_path, monkeypatch, change, why):
    """Spec-2 13 (WP3d): aw_argv_problems refuses a docker run of the feeder that is privileged, adds a capability,
    mounts /proc, /proc/sys or /sys, the X11 socket or a display, drops less than every capability, lacks
    no-new-privileges or does not run as aw; start_feeder refuses such an argv before docker is asked, and nothing of
    the feeder starts. Each option is read in every form docker takes: the short ones (-u, -v, -e) with their value
    apart, attached or after a cluster of docker run's boolean short options; and a mount of the host's root or the
    docker socket and the host's pid, ipc or user namespace are refused too."""
    rig = _ros_rig(tmp_path, monkeypatch)
    ctx = _ros_ctx(rig)
    good = stack.feeder_argv(ctx, ctx.run_dir / "up", "x/up")
    assert stack.aw_argv_problems(good) == []
    bad = change(list(good))
    problems = stack.aw_argv_problems(bad)
    assert problems and any(why in p for p in problems), problems
    monkeypatch.setattr(stack, "feeder_argv", lambda c, d, label: bad)
    (ctx.run_dir / "up").mkdir(parents=True, exist_ok=True)
    with pytest.raises(stack.StackError, match="2.12"):
        stack.start_feeder(ctx, ctx.run_dir / "up", "x/up")
    assert not rig.fake.runs()


def test_a_run_whose_host_check_cannot_be_read_is_refused_before_any_container_starts(tmp_path, monkeypatch):
    rig = _ros_rig(tmp_path, monkeypatch, readings=[2])
    ctx = _ros_ctx(rig)
    with pytest.raises(stack.StackError, match="host check"):
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    # docker is asked which ros runs are left (a read), and nothing else: no sweep's list (ps -aq), no rm, no run
    assert not [c for c in rig.fake.calls if c[:1] in (["run"], ["rm"]) or c[:2] == ["ps", "-aq"]], rig.fake.calls
    assert [c[:2] for c in rig.fake.calls if c[:1] == ["ps"]] == [["ps", "-a"]], rig.fake.calls
    assert not (ctx.run_dir / "host-before.txt").exists()


@pytest.mark.parametrize("feeder", ["silent", "stops"])
def test_a_ros_run_whose_feeder_never_logs_its_start_is_swept_and_its_host_check_read_after(tmp_path, monkeypatch, feeder):
    """A feeder that never logs its start record (a refused start exits 2), or ends before it: the run is swept (the
    native monitor stopped, every container of the stack removed), the host check read again after the sweep and compared,
    and up fails naming the feeder; nothing is left."""
    rig = _ros_rig(tmp_path, monkeypatch, feeder=feeder)
    ctx = _ros_ctx(rig, bridge="broker")
    with pytest.raises(stack.StackError) as e:
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    assert "ros-vss-feeder" in str(e.value) and "host check" in str(e.value), str(e.value)
    assert rig.fake.containers == {}
    assert [c[1:2] for c in rig.hc] == [[], [], ["--compare"]], rig.hc
    assert (ctx.run_dir / "host-after.txt").read_text(encoding="utf-8") == ROS_HOST
    assert json.loads((ctx.run_dir / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_a_changed_host_setting_during_a_failed_ros_run_is_named(tmp_path, monkeypatch):
    rig = _ros_rig(tmp_path, monkeypatch, feeder="silent", readings=[ROS_HOST, ROS_HOST.replace("rmem_max=1111111", "rmem_max=2147483647")])
    ctx = _ros_ctx(rig)
    with pytest.raises(stack.StackError, match="changed net.core.rmem_max before=1111111 after=2147483647"):
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")


def _ros_main_up(rig, *extra):
    return stack.main(["up", "--feed", "ros", "--run-type", "planning-sim", "--name", "m"] + list(extra))


def test_down_after_a_ros_up_removes_the_feeder_with_the_rest_and_reads_the_host_check_after_the_sweep(tmp_path, monkeypatch, capsys):
    """Spec-2 2.5: `up --feed ros` leaves the stack running and says so; `down` removes the feeder with the rest (the
    stack's label), then reads the host check into the run's directory and compares it with the reading before: the
    same, down exits 0."""
    rig = _ros_rig(tmp_path, monkeypatch)
    assert _ros_main_up(rig) == 0
    out = capsys.readouterr().out
    assert "stack running" in out and "stack.py down" in out and "host check" in out, out
    run = next(rig.runs.iterdir())
    assert sorted(rig.fake.containers) == sorted(["sdv-stack-databroker", "sdv-stack-witness", "ros-vss-feeder"])
    assert stack.main(["down"]) == 0
    assert rig.fake.containers == {}
    assert (run / "host-after.txt").read_text(encoding="utf-8") == ROS_HOST and rig.hc[-1][1] == "--compare"
    assert json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_a_changed_host_setting_fails_down_with_the_setting_named(tmp_path, monkeypatch):
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST, ROS_HOST.replace("LOOPBACK,UP,LOWER_UP", "LOOPBACK,MULTICAST,UP,LOWER_UP")])
    assert _ros_main_up(rig) == 0
    with pytest.raises(stack.StackError, match="changed lo.flags before=LOOPBACK,UP,LOWER_UP after=LOOPBACK,MULTICAST,UP,LOWER_UP"):
        stack.main(["down"])
    assert rig.fake.containers == {}, "the sweep ran before the check that failed"


def test_down_stops_the_native_monitor_a_broker_ros_up_left_and_only_that_process(tmp_path, monkeypatch):
    """With --bridge broker the native monitor outlives `up` (its pid in up/monitor.json); `down` signals it only when
    /proc says that pid still runs the monitor's binary, and leaves any other process alone."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 4)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    run = next(rig.runs.iterdir())
    mon = json.loads((run / "up" / "monitor.json").read_text(encoding="utf-8"))
    signals: List[Any] = []
    alive = {"argv0": mon["binary"]}

    def signal_process(pid, sig):
        signals.append((pid, sig))
        alive["argv0"] = None
    monkeypatch.setattr(stack, "proc_argv0", lambda pid: alive["argv0"] if pid == mon["pid"] else None)
    monkeypatch.setattr(stack, "signal_process", signal_process)
    assert stack.main(["down"]) == 0
    assert signals == [(4242, stack.signal.SIGTERM)], signals
    assert json.loads((run / "up" / "monitor-stop.json").read_text(encoding="utf-8"))["stopped"] == "on SIGTERM"
    # another process holds the pid by the next down: left alone
    assert _ros_main_up(rig, "--bridge", "broker", "--name", "m2") == 0
    alive["argv0"] = "/usr/bin/python3"
    del signals[:]
    assert stack.main(["down"]) == 0 and signals == []


def _left_monitor(monkeypatch, run: Path) -> List[Any]:
    """down's /proc read and its signal replaced for the native monitor RUN left (up/monitor.json): its pid runs its binary
    until it is signalled. Returns the list every signal goes into."""
    mon = json.loads((run / "up" / "monitor.json").read_text(encoding="utf-8"))
    alive = {"argv0": mon["binary"]}
    signals: List[Any] = []

    def signal_process(pid, sig):
        signals.append((pid, sig))
        alive["argv0"] = None
    monkeypatch.setattr(stack, "proc_argv0", lambda pid: alive["argv0"] if pid == mon["pid"] else None)
    monkeypatch.setattr(stack, "signal_process", signal_process)
    return signals


def test_a_second_ros_up_is_refused_while_a_ros_run_is_up_and_down_then_closes_the_first(tmp_path, monkeypatch):
    """Spec-2 2.5, 2.12: a ros up while another ros run is still up is refused before anything is written, swept or
    read. Its sweep would remove the first run's feeder, and with it the label down finds that run by, but neither stop
    the native monitor the first run left (which would hold :7160 for every later broker-mode start) nor read its host
    check after. The first run is left as it was; down then stops its monitor and reads its host check after the sweep,
    and the next up goes on."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 4)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (first,) = list(rig.runs.iterdir())
    signals = _left_monitor(monkeypatch, first)
    calls, events, hc = len(rig.fake.calls), len(rig.fake.events), len(rig.hc)
    for extra in ([], ["--bridge", "broker"]):
        with pytest.raises(stack.StackError) as e:
            _ros_main_up(rig, "--name", "second", *extra)
        msg = str(e.value)
        assert "a ros run is still up" in msg and str(first) in msg and "stack.py down first" in msg, msg
    assert list(rig.runs.iterdir()) == [first], "nothing of the refused runs is written"
    assert [c[:2] for c in rig.fake.calls[calls:]] == [["ps", "-a"]] * 2, "docker is only asked which ros runs are up"
    assert rig.fake.events[events:] == [] and len(rig.hc) == hc and signals == []
    assert sorted(rig.fake.containers) == sorted(["sdv-stack-databroker", "sdv-stack-witness", "sdv-stack-bridge", "ros-vss-feeder"])
    assert stack.main(["down"]) == 0
    assert signals == [(4242, stack.signal.SIGTERM)] and rig.fake.containers == {}
    assert (first / "host-after.txt").read_text(encoding="utf-8") == ROS_HOST
    assert json.loads((first / "host-check.json").read_text(encoding="utf-8"))["same"] is True
    assert _ros_main_up(rig, "--name", "third") == 0, "a closed run holds nothing up"


def test_up_ros_asks_which_ros_runs_are_left_before_its_sweep_and_its_host_check(tmp_path, monkeypatch):
    """up_ros itself (a harness's way in, past main) refuses while a ros run is left, before its leftover sweep and before
    the host check is read: nothing of the first run is removed, and the refused run has no host-before.txt, so it is no
    open run either."""
    rig = _ros_rig(tmp_path, monkeypatch)
    _ros_up(rig, "broker", name="a")
    ctx = _ros_ctx(rig, "b")
    events, hc = len(rig.fake.events), len(rig.hc)
    with pytest.raises(stack.StackError, match="a ros run is still up"):
        stack.up_ros(ctx, ctx.run_dir / "up", "b/up")
    assert rig.fake.events[events:] == [] and len(rig.hc) == hc, rig.fake.events[events:]
    assert not (ctx.run_dir / "host-before.txt").exists() and stack.FEEDER_CONTAINER in rig.fake.containers


def test_down_closes_a_ros_run_that_another_commands_sweep_removed(tmp_path, monkeypatch):
    """Every other start (up on the other feeds, replay, exit-test, live and the probes) removes the stack's containers
    first, as it did before WP3d, and so the feeder with the label down finds a ros run by. The run's directory still
    says it is open (host-before.txt, no host-check.json): a ros up is refused until down, and down stops the native
    monitor the run left and reads its host check after; a second down finds nothing more to close."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 3)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    signals = _left_monitor(monkeypatch, run)
    stack.remove_stack()          # what up(), replay, exit-test, live and the probes do first
    assert rig.fake.containers == {} and stack.ros_runs_up() == []
    with pytest.raises(stack.StackError, match="a ros run is still up"):
        _ros_main_up(rig, "--name", "again")
    assert stack.main(["down"]) == 0
    assert signals == [(4242, stack.signal.SIGTERM)]
    assert (run / "host-after.txt").read_text(encoding="utf-8") == ROS_HOST and rig.hc[-1][1] == "--compare"
    assert json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True
    hc = len(rig.hc)
    assert stack.main(["down"]) == 0 and len(rig.hc) == hc and len(signals) == 1


def test_an_open_ros_run_is_a_ros_runs_directory_with_its_host_check_before_and_no_record_after(tmp_path, monkeypatch):
    """ros_runs_open: the directories under RUNS whose manifest says feed ros and which hold host-before.txt but no
    host-check.json (the record host_check_after always writes, a comparison that could not be made included). A closed
    run, another feed's run, a run never started and a directory without a manifest are none."""
    runs = tmp_path / "runs"
    monkeypatch.setattr(stack, "RUNS", runs)
    assert stack.ros_runs_open() == []

    def run_dir(name, feed="ros", before=True, record=False, manifest=True):
        d = runs / name
        d.mkdir(parents=True)
        if manifest:
            (d / "manifest.json").write_text(json.dumps({"format": 1, "feed": feed}), encoding="utf-8")
        if before:
            (d / "host-before.txt").write_text(ROS_HOST, encoding="utf-8")
        if record:
            (d / "host-check.json").write_text("{}", encoding="utf-8")
        return d
    left = run_dir("20260101-open")
    run_dir("20260101-closed", record=True)
    run_dir("20260101-vcan", feed="vcan")
    run_dir("20260101-never", before=False)
    run_dir("20260101-nomanifest", manifest=False)
    (runs / "20260101-file").write_text("x", encoding="utf-8")
    assert stack.ros_runs_open() == [left]


def test_down_finds_a_ros_run_by_its_feeders_label_when_the_runs_root_has_moved(tmp_path, monkeypatch):
    """The feeder's sdv.stack.ros-run label holds the run directory, so down closes a ros run whose directory is not under
    the RUNS of the down (SDV_RUNS set otherwise): its host check is read after the sweep there."""
    rig = _ros_rig(tmp_path, monkeypatch)
    assert _ros_main_up(rig) == 0
    (run,) = list(rig.runs.iterdir())
    monkeypatch.setattr(stack, "RUNS", tmp_path / "elsewhere")
    assert stack.main(["down"]) == 0
    assert (run / "host-after.txt").read_text(encoding="utf-8") == ROS_HOST
    assert json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_a_run_header_that_fails_c12a_is_refused_before_the_host_check_so_no_run_is_left_open(tmp_path, monkeypatch):
    """C12a is checked before the host check is read (both before any container starts): a run refused there leaves no
    host-before.txt, so no later up is refused for it and down has nothing to close."""
    rig = _ros_rig(tmp_path, monkeypatch)
    ctx = _ros_ctx(rig)
    monkeypatch.setattr(ctx, "check_header", lambda h: ("C12a", False, "a synthetic refusal"))
    with pytest.raises(stack.StackError, match="C12a failed: a synthetic refusal"):
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    assert rig.hc == [] and not rig.fake.runs() and not (ctx.run_dir / "host-before.txt").exists()
    assert stack.ros_runs_open() == []


@pytest.mark.parametrize("live, settle", [(1, 0.0), (2, 0.3)])
def test_a_feeder_that_exits_right_after_its_start_record_fails_up_and_is_swept(tmp_path, monkeypatch, capsys, live, settle):
    """feeder_node.py (WP3a's, unchanged) logs its start record before rclpy.init, its node and its subscriptions, so a
    feeder whose ROS side fails (the DDS file, its log directory) exits just after the line up waits for. up reads the
    feeder's state again through FEEDER_SETTLE_S after that line, every FEEDER_SETTLE_POLL_S: a feeder that is not
    running fails the run with the feeder named and its last log lines, the run swept (the native monitor stopped, none
    left in up/monitor.json) and its host check read after; up never says the stack runs. live: the reads of its state
    the feeder answers running (wait_log's is the first); settle: the window (0: one read)."""
    rig = _ros_rig(tmp_path, monkeypatch)
    rig.fake.feeder_live = live
    monkeypatch.setattr(stack, "FEEDER_SETTLE_S", settle)
    monkeypatch.setattr(stack, "FEEDER_SETTLE_POLL_S", 0.05)
    with pytest.raises(stack.StackError) as e:
        _ros_main_up(rig, "--bridge", "broker")
    msg = str(e.value)
    assert "ros-vss-feeder exited right after its start record" in msg and '"event":"start"' in msg and "host check" in msg, msg
    assert "stack running" not in capsys.readouterr().out
    assert rig.fake.containers == {} and [c[1:2] for c in rig.hc] == [[], [], ["--compare"]], rig.hc
    (run,) = list(rig.runs.iterdir())
    assert not (run / "up" / "monitor.json").exists() and (run / "host-check.json").is_file()


def test_c8_takes_the_feeders_image_only_from_a_running_container(tmp_path, monkeypatch):
    """C8 reads the feeder's image with its state: a feeder that has exited by then still names its image to docker
    inspect, and C8 then says the writer is not running, which fails the run (swept, its host check read after) instead
    of passing on an exited container."""
    rig = _ros_rig(tmp_path, monkeypatch)
    real = stack.start_feeder

    def start_then_exit(ctx, up_dir, run_label):
        name = real(ctx, up_dir, run_label)
        rig.fake.containers[name]["running"] = False
        return name
    monkeypatch.setattr(stack, "start_feeder", start_then_exit)
    ctx = _ros_ctx(rig)
    with pytest.raises(stack.StackError) as e:
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    assert "C8 failed" in str(e.value) and "writer ros-vss-feeder is not running" in str(e.value), str(e.value)
    table = json.loads((ctx.run_dir / "up" / "attribution.json").read_text(encoding="utf-8"))
    assert [c for c in table["checks"] if c[0] == "C8"][0][1] is False
    assert rig.fake.containers == {} and (ctx.run_dir / "host-check.json").is_file()


@pytest.mark.parametrize("extra", [
    ["--guest-host", "192.0.2.1"], ["--guest-console", "c"], ["--guest-image", "i"],
    ["--monitor", "native", "--guest-host", "192.0.2.1", "--guest-console", "c", "--guest-image", "i"]])
def test_the_guest_options_without_monitor_guest_are_refused_on_the_ros_feed(tmp_path, monkeypatch, extra):
    """--guest-host, --guest-console or --guest-image with --bridge broker but without --monitor guest are refused (they are
    guest mode's, not the native monitor's: ros_cli_refusals, in Context's words) before docker is asked or anything is
    read or written, instead of being dropped while a native monitor judges the run."""
    def touched(*_a, **_kw):
        raise AssertionError("the stack went on though the run was to be refused")
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    for name in ("docker", "remove_stack", "hostcheck_run", "load_images", "load_contract"):
        monkeypatch.setattr(stack, name, touched)
    _placement_env(monkeypatch)
    with pytest.raises(stack.StackError, match="guest mode's"):
        stack.main(["up", "--feed", "ros", "--run-type", "planning-sim", "--bridge", "broker", "--name", "g"] + extra)
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("opts", [{"guest_host": "192.0.2.1"}, {"guest_console": "c"}, {"guest_image": "i"},
                                  {"monitor": "native", "guest_host": "192.0.2.1", "guest_console": "c", "guest_image": "i"}],
                         ids=["host", "console", "image", "native-and-all-three"])
def test_ros_main_hands_context_the_guest_options_so_its_own_refusal_holds_without_the_command_lines(tmp_path, monkeypatch, opts):
    """ros_main called with the guest's options but not --monitor guest (the command line's refusals not made, as a harness
    that calls it would) hands the RosContext the monitor mode and all three options, so Context's own refusal (guest
    mode's) stops it before docker is asked or anything is read or written: they are never dropped."""
    def touched(*_a, **_kw):
        raise AssertionError("the stack went on though the run was to be refused")
    monkeypatch.setattr(stack, "RUNS", tmp_path / "runs")
    for name in ("docker", "remove_stack", "hostcheck_run", "load_images", "load_contract"):
        monkeypatch.setattr(stack, name, touched)
    _placement_env(monkeypatch)
    ns = types.SimpleNamespace(name="g", bridge="broker", monitor=None, guest_host=None, guest_console=None, guest_image=None,
                               images="build")
    for key, value in opts.items():
        setattr(ns, key, value)
    with pytest.raises(stack.StackError, match="guest mode's"):
        stack.ros_main(ns)    # type: ignore[arg-type]
    assert not (tmp_path / "runs").exists()


def test_the_feeders_topics_and_qos_match_the_planning_sims_publishers_as_w4_read_them():
    """Spec-2 5 item 3: the feeder's planning-sim subscriptions are the four vehicle topics and the verdict, never the claim
    topic; each matches its publisher's QoS as W4 read it (G6, G7: RELIABLE KEEP_LAST 1 VOLATILE; the claim node's verdict:
    RELIABLE KEEP_LAST 10 VOLATILE), a BEST_EFFORT or RELIABLE subscriber matching a RELIABLE publisher and a VOLATILE one
    any; /localization/acceleration is one of them; velocity_status's stamp_ns is its header's stamp; lateral_velocity
    and control_time are not mapped. Nothing of WP3a's is changed: this reads it."""
    fn = _rosvss_module("feeder_node")
    up = _rosvss_module("update")
    subs = fn.subscriptions("planning-sim")
    assert [s[0] for s in subs] == list(stack.ROS_FEED_PUBLISHERS), subs
    # READ (W4 G6, G7), held here once more: a re-read changes both places
    read = {"reliability": "RELIABLE", "history": "KEEP_LAST", "durability": "VOLATILE"}
    for topic, pub in stack.ROS_FEED_PUBLISHERS.items():
        want = dict(read, depth=10, publisher="ctl_claim_node") if topic == "/qnx_monitor/verdict" else \
            dict(read, depth=1, publisher="simple_planning_simulator")
        assert {k: pub[k] for k in want} == want, (topic, pub)
    assert "/control/command/control_cmd" not in [s[0] for s in subs] and "/localization/acceleration" in stack.ROS_FEED_PUBLISHERS
    ctl = (REPO / "sdv" / "ctl" / "ctl_claim_node.py").read_text(encoding="utf-8")
    assert "VERDICT_DEPTH = 10" in ctl and "reliability=ReliabilityPolicy.RELIABLE" in ctl
    for topic, _module, cls, kind, _rts in subs:
        pub = stack.ROS_FEED_PUBLISHERS[topic]
        reliability, depth = fn.QOS[kind]
        assert reliability == "BEST_EFFORT" or pub["reliability"] == "RELIABLE", (topic, reliability, pub)
        assert pub["durability"] == "VOLATILE" and pub["history"] == "KEEP_LAST", (topic, pub)
        assert depth == (1 if kind == "vehicle" else 10) and pub["depth"] == depth, (topic, depth, pub)
        assert pub["type"].endswith("/" + cls), (topic, pub["type"], cls)
    assert "DurabilityPolicy.VOLATILE" in (ROSVSS_DIR / "feeder_node.py").read_text(encoding="utf-8")
    assert "lateral_velocity" not in json.dumps(up.FIELDS) and "control_time" not in json.dumps(up.FIELDS)
    msg = types.SimpleNamespace(header=types.SimpleNamespace(stamp=types.SimpleNamespace(sec=12, nanosec=345)),
                                longitudinal_velocity=1.5, heading_rate=0.25, lateral_velocity=9.0)
    assert up.from_velocity(msg, 77)["stamp_ns"] == 12 * 10 ** 9 + 345


def test_the_feeders_command_is_the_images():
    """The program and the venv's Python the stack starts the feeder with are the Dockerfile's CMD, and the entrypoint the
    image's own (sdv/aw's script copied in)."""
    text = (ROSVSS_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["%s", "%s"]' % (stack.FEEDER_PYTHON, stack.FEEDER_PROGRAM) in text
    assert 'ENTRYPOINT ["%s"]' % stack.AW_ENTRYPOINT in text and stack.AW_USER == "aw"


# --- the ros feed: the host check's reading and comparison, the sweeps, the witness's paths (spec-2 2.5, 2.12, 13) ----------

@pytest.mark.parametrize("garbage", ["a zero exit and no format line\n", ""], ids=["no-format-line", "empty"])
def test_a_host_reading_without_its_format_line_is_no_reading_before_a_run_or_after_its_sweep(tmp_path, monkeypatch, garbage):
    """The host check script's reading begins with its format line: an exit 0 with other output (or none) is no reading.
    Before the run it is refused with nothing written, swept or started; after the sweep it is an after-reading that
    cannot be read (never `same`), and the failed run says it could not be compared."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[garbage])
    ctx = _ros_ctx(rig)
    with pytest.raises(stack.StackError, match="cannot be read"):
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    assert not [c for c in rig.fake.calls if c[:1] in (["run"], ["rm"]) or c[:2] == ["ps", "-aq"]], rig.fake.calls
    assert not (ctx.run_dir / "host-before.txt").exists()
    (tmp_path / "after").mkdir()
    rig = _ros_rig(tmp_path / "after", monkeypatch, feeder="silent", readings=[ROS_HOST, garbage])
    ctx = _ros_ctx(rig)
    with pytest.raises(stack.StackError, match="could not be compared") as e:
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    assert "cannot be read" in str(e.value), str(e.value)
    rec = json.loads((ctx.run_dir / "host-check.json").read_text(encoding="utf-8"))
    assert rec["same"] is False and rec["changed"] == [] and "cannot be read" in rec["error"], rec
    assert not (ctx.run_dir / "host-after.txt").exists(), "a garbled after-reading is not kept as one"


def test_a_host_comparison_that_cannot_be_made_is_no_agreement_and_fails_down(tmp_path, monkeypatch):
    """hostcheck.sh --compare exits 0 (the same) or 1 (a difference); any other exit is a comparison that failed, which is
    no agreement: the record says so (same false, the exit, the error) and down fails naming it, instead of reading the
    four settings as unchanged."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig) == 0
    real = stack.hostcheck_run

    def compare_fails(args):
        if args[:1] == ["--compare"]:
            return subprocess.CompletedProcess(args, 2, "", "hostcheck.sh: cannot compare: a reading has no format line\n")
        return real(args)
    monkeypatch.setattr(stack, "hostcheck_run", compare_fails)
    with pytest.raises(stack.StackError, match=r"could not be compared: the comparison failed \(exit 2\)"):
        stack.main(["down"])
    (run,) = list(rig.runs.iterdir())
    rec = json.loads((run / "host-check.json").read_text(encoding="utf-8"))
    assert rec["same"] is False and rec["exit"] == 2 and rec["changed"] == [] and "comparison failed" in rec["error"], rec


def test_down_fails_a_ros_run_that_has_no_host_before_reading_and_reads_nothing_for_it(tmp_path, monkeypatch):
    """A ros run directory without host-before.txt has nothing to compare an after-reading with: down_ros names the run and
    the missing file and fails, never passing it as unchanged, and reads no host check for it."""
    def no_reading(args):
        raise AssertionError("an after-reading was taken for a run with no before-reading")
    monkeypatch.setattr(stack, "hostcheck_run", no_reading)
    run = tmp_path / "20260101-r"
    (run / "up").mkdir(parents=True)
    with pytest.raises(stack.StackError, match=r"20260101-r: no host-before\.txt to compare with"):
        stack.down_ros([run])
    assert not (run / "host-after.txt").exists() and not (run / "host-check.json").exists()


def test_a_failed_broker_ros_up_stops_the_native_monitor_it_started_and_leaves_none_for_down(tmp_path, monkeypatch):
    """The sweep of a ros up that fails (here the feeder never logs its start record) stops the native monitor the run
    started, once, and records none in up/monitor.json: the monitor would otherwise keep :7160 for every later start."""
    rig = _ros_rig(tmp_path, monkeypatch, feeder="silent")
    started: List[Any] = []
    rig_start_monitor = stack.start_monitor

    def start_monitor(ctx, replay_dir, info):
        rig_start_monitor(ctx, replay_dir, info)
        started.append(ctx.monitor)
    monkeypatch.setattr(stack, "start_monitor", start_monitor)
    ctx = _ros_ctx(rig, bridge="broker")
    with pytest.raises(stack.StackError, match="ros-vss-feeder"):
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    assert [m.stopped for m in started] == [1] and ctx.monitor is None
    assert not (ctx.run_dir / "up" / "monitor.json").exists(), "nothing is left for down to stop"


def test_down_kills_a_native_monitor_that_ignores_sigterm_and_says_so(tmp_path, monkeypatch):
    """stop_left_monitor sends SIGTERM and waits MONITOR_STOP_S; a monitor still running its binary then gets SIGKILL, and
    up/monitor-stop.json says it went on SIGKILL (a process that exits on SIGTERM is not killed: the test above)."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    mon = json.loads((run / "up" / "monitor.json").read_text(encoding="utf-8"))
    signals: List[Any] = []
    alive = {"yes": True}

    def signal_process(pid, sig):
        signals.append((pid, sig))
        if sig == stack.signal.SIGKILL:
            alive["yes"] = False
    monkeypatch.setattr(stack, "proc_argv0", lambda pid: mon["binary"] if pid == mon["pid"] and alive["yes"] else None)
    monkeypatch.setattr(stack, "signal_process", signal_process)
    monkeypatch.setattr(stack, "MONITOR_STOP_S", 0.0)
    assert stack.main(["down"]) == 0
    assert signals == [(4242, stack.signal.SIGTERM), (4242, stack.signal.SIGKILL)], signals
    assert json.loads((run / "up" / "monitor-stop.json").read_text(encoding="utf-8"))["stopped"].startswith("on SIGKILL")


def test_down_waits_for_a_native_monitor_that_is_slow_to_end_on_sigterm_and_does_not_kill_it(tmp_path, monkeypatch):
    """stop_left_monitor reads /proc again after SIGTERM until the pid no longer runs the monitor's binary (or MONITOR_STOP_S
    has passed): a monitor that still runs its binary for two reads after SIGTERM and then ends gets SIGTERM only, never
    SIGKILL straight after it (it would lose its stopped line), and up/monitor-stop.json says it went on SIGTERM."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    mon = json.loads((run / "up" / "monitor.json").read_text(encoding="utf-8"))
    signals: List[Any] = []
    after_term = {"reads": 0}

    def proc_argv0(pid):
        if pid != mon["pid"]:
            return None
        if not signals:
            return mon["binary"]
        after_term["reads"] += 1
        return mon["binary"] if after_term["reads"] <= 2 else None
    monkeypatch.setattr(stack, "proc_argv0", proc_argv0)
    monkeypatch.setattr(stack, "signal_process", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(stack.time, "sleep", lambda _s: None)          # the pauses between the reads
    assert stack.main(["down"]) == 0
    assert signals == [(4242, stack.signal.SIGTERM)], signals
    assert after_term["reads"] > 2, "the monitor was read until it was gone"
    assert json.loads((run / "up" / "monitor-stop.json").read_text(encoding="utf-8"))["stopped"] == "on SIGTERM"


def _down_listings() -> List[List[str]]:
    """The two docker calls a down made before WP3d's down-path fix when it found nothing to remove: the ros runs'
    listing (ros_runs_up) and remove_stack's."""
    return [["ps", "-a", "--filter", "label=" + stack.ROS_LABEL, "--format", '{{index .Labels "%s"}}' % stack.ROS_LABEL],
            ["ps", "-aq", "--filter", "label=" + stack.LABEL]]


def _down_events(rig, monkeypatch) -> List[Any]:
    """down's calls in one order (WP3d's down-path fix): stack.docker wrapped so that each `docker stop` joins the
    RosDocker's events as "stop ARGS", beside its "rm ..." and the host check's "hostcheck ..." entries, and
    stack.signal_process (a test's own when set first) so that each signal joins them as "signal". Returns the keyword
    arguments of each stop call, in order."""
    daemon, signal_process = stack.docker, stack.signal_process
    stops: List[Any] = []

    def docker(*args, **kw):
        if args[:1] == ("stop",):
            rig.fake.events.append("stop " + " ".join(args[1:]))
            stops.append(dict(kw))
        return daemon(*args, **kw)

    def signal(pid, sig):
        rig.fake.events.append("signal")
        signal_process(pid, sig)
    monkeypatch.setattr(stack, "docker", docker)
    monkeypatch.setattr(stack, "signal_process", signal)
    return stops


def test_down_after_a_broker_ros_up_stops_the_bridge_then_the_witness_before_it_removes_the_stack(tmp_path, monkeypatch):
    """WP3d's down-path fix (7.2's R6 row; spec-2 2.5's down bullet, whose feeder is still removed by the rm -f alone):
    after `up --feed ros --bridge broker`, down gives the claim bridge and then the witness `docker stop -t 10` with
    check=False, in the order the replay and live paths end them (the bridge's own stop, then stop_containers' witness):
    SIGTERM, so the bridge drains and writes its stop event and summary.json, and the witness's stop record comes after
    the bridge's last write-back; both before remove_stack's `docker rm -f`, which kills them without either. The bridge
    stops while the native monitor still runs (down signals it after the sweep), the host check is read after it all,
    and no other container is stopped."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    _left_monitor(monkeypatch, run)
    stops = _down_events(rig, monkeypatch)
    n, m = len(rig.fake.events), len(rig.fake.calls)
    assert stack.main(["down"]) == 0
    listing = ["ps", "--filter", "label=%s=%s/up" % (stack.LABEL, run.name), "--format", "{{.Names}}"]
    assert [c for c in rig.fake.calls[m:] if c[:1] == ["ps"]] == [_down_listings()[0], listing, _down_listings()[1]], rig.fake.calls[m:]
    ev = rig.fake.events[n:]
    witness, bridge = "stop -t 10 " + stack.NAMES[stack.WITNESS], "stop -t 10 " + stack.BRIDGE_CONTAINER
    assert [e for e in ev if e.startswith("stop ")] == [bridge, witness], ev
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(bridge) < ev.index(witness) < ev.index(rm) < ev.index("signal") < ev.index("hostcheck --compare"), ev
    assert stops == [{"check": False}] * 2, stops
    assert rig.fake.containers == {} and json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_down_stops_the_bridge_and_the_witness_of_a_ros_run_found_by_its_feeders_label_alone(tmp_path, monkeypatch):
    """A ros run whose directory is not under this down's RUNS (another SDV_RUNS at up) is found by its feeder's label
    alone (ros_runs_up); down still stops its bridge and then its witness before the `rm -f`."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    _left_monitor(monkeypatch, run)
    monkeypatch.setattr(stack, "RUNS", tmp_path / "other-runs")
    assert stack.ros_runs_open() == []
    stops = _down_events(rig, monkeypatch)
    n = len(rig.fake.events)
    assert stack.main(["down"]) == 0
    ev = rig.fake.events[n:]
    witness, bridge = "stop -t 10 " + stack.NAMES[stack.WITNESS], "stop -t 10 " + stack.BRIDGE_CONTAINER
    assert [e for e in ev if e.startswith("stop ")] == [bridge, witness], ev
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(witness) < ev.index(rm) and stops == [{"check": False}] * 2, (ev, stops)


def test_down_after_a_guest_mode_ros_up_stops_the_bridge_then_the_witness_and_signals_no_monitor(tmp_path, monkeypatch):
    """WP3d's down-path fix in guest mode: `up --feed ros --bridge broker --monitor guest` starts a bridge and no native
    monitor (no up/monitor.json), so down gives the claim bridge and then the witness `docker stop -t 10` with check=False,
    both before remove_stack's `docker rm -f`, and signals no process: there is no native monitor to stop. The addresses
    are documentation values; this host's own are not read."""
    rig = _ros_rig(tmp_path, monkeypatch)
    console, image = _guest_files(tmp_path)
    monkeypatch.setattr(stack, "local_ipv4", lambda: [])
    assert _ros_main_up(rig, "--bridge", "broker", "--monitor", "guest", "--guest-host", GUEST, "--guest-console", str(console),
                        "--guest-image", str(image)) == 0
    stops = _down_events(rig, monkeypatch)
    n = len(rig.fake.events)
    assert stack.main(["down"]) == 0
    ev = rig.fake.events[n:]
    witness, bridge = "stop -t 10 " + stack.NAMES[stack.WITNESS], "stop -t 10 " + stack.BRIDGE_CONTAINER
    assert [e for e in ev if e.startswith("stop ")] == [bridge, witness], ev
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(bridge) < ev.index(witness) < ev.index(rm), ev
    assert "signal" not in ev, ev
    assert stops == [{"check": False}] * 2, stops
    assert rig.fake.containers == {}


def test_down_after_a_ros_up_without_the_bridge_stops_the_witness_alone(tmp_path, monkeypatch):
    """down stops only a container of the stack that runs: after `up --feed ros` with --bridge none, which starts no
    bridge, down stops the witness before the `rm -f` and makes no stop call for the bridge, so no stop of a container
    that is not there is tried."""
    rig = _ros_rig(tmp_path, monkeypatch)
    assert _ros_main_up(rig) == 0
    stops = _down_events(rig, monkeypatch)
    n = len(rig.fake.events)
    assert stack.main(["down"]) == 0
    ev = rig.fake.events[n:]
    witness = "stop -t 10 " + stack.NAMES[stack.WITNESS]
    assert [e for e in ev if e.startswith("stop ")] == [witness], ev
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(witness) < ev.index(rm) and stops == [{"check": False}], (ev, stops)
    assert rig.fake.containers == {}


def test_down_with_no_stack_container_makes_the_calls_it_made_before_and_no_stop_call(tmp_path, monkeypatch):
    """A down with no stack is a no-op apart from the calls it made before WP3d's down-path fix: with nothing up and no
    ros run, its docker calls are exactly the ros runs' listing and remove_stack's. A ros run whose containers another
    start's sweep removed (its directory still open, so down closes it) gets no stop call at all: none that could fail.
    A running container that holds the witness's name without the stack's label is not the stack's: neither stopped nor
    removed."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert stack.main(["down"]) == 0
    assert rig.fake.calls == _down_listings(), rig.fake.calls
    assert _ros_main_up(rig) == 0
    (run,) = list(rig.runs.iterdir())
    stack.remove_stack()          # what up() on another feed, replay, exit-test, live and the probes do first
    foreign = {"labels": {"another.label": "x"}, "image": IMG, "line": "", "running": True}
    rig.fake.containers[stack.NAMES[stack.WITNESS]] = foreign
    n = len(rig.fake.calls)
    assert stack.main(["down"]) == 0
    assert not [c for c in rig.fake.calls[n:] if c[:1] == ["stop"]], rig.fake.calls[n:]
    assert rig.fake.containers == {stack.NAMES[stack.WITNESS]: foreign}, rig.fake.containers
    assert json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_down_whose_docker_cannot_list_fails_as_it_did_and_stops_nothing(tmp_path, monkeypatch):
    """A down that finds an open ros run while docker answers no listing makes no stop call and fails where it failed
    before WP3d's down-path fix: at remove_stack's listing, with its words (stack.run's), so a failed listing of what runs
    is no new way for down to fail."""
    runs = tmp_path / "runs"
    run = runs / "20260101-r"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"format": 1, "feed": "ros"}), encoding="utf-8")
    (run / "host-before.txt").write_text(ROS_HOST, encoding="utf-8")
    monkeypatch.setattr(stack, "RUNS", runs)
    calls: List[List[str]] = []

    def docker(*args, check=True, timeout=120):
        calls.append(list(args))
        p = subprocess.CompletedProcess(list(args), 1, "", "Cannot connect to the Docker daemon (a synthetic failure)")
        if check:          # as stack.run fails a checked call: the command's first four words, its exit and its stderr
            raise stack.StackError("%s failed (%d): %s" % (" ".join(["docker"] + list(args)[:3]), p.returncode, p.stderr))
        return p
    monkeypatch.setattr(stack, "docker", docker)
    with pytest.raises(stack.StackError, match=r"^docker ps -aq --filter failed \(1\): Cannot connect"):
        stack.main(["down"])
    assert stack.ros_runs_open() == [run] and not [c for c in calls if c[:1] == ["stop"]], calls


def test_down_stops_nothing_when_the_listing_of_a_ros_runs_containers_fails_though_it_printed_their_names(tmp_path, monkeypatch):
    """down reads its listing of a ros run's own containers (WP3d's down-path fix) only when docker answered it: after
    `up --feed ros --bridge broker`, that listing exits 1 with the bridge's and the witness's names on its stdout (a
    synthetic failure: a real daemon prints nothing there), and down makes no stop call, while remove_stack's `rm -f`
    still removes the stack, so a failed listing is no new way for down to stop a container or to fail."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    _left_monitor(monkeypatch, run)
    stops = _down_events(rig, monkeypatch)
    daemon = stack.docker
    listing = ["ps", "--filter", "label=%s=%s/up" % (stack.LABEL, run.name), "--format", "{{.Names}}"]
    answered: List[Any] = []

    def docker(*args, **kw):
        if list(args) == listing:
            answered.append(dict(kw))
            names = "%s\n%s\n" % (stack.BRIDGE_CONTAINER, stack.NAMES[stack.WITNESS])
            return subprocess.CompletedProcess(list(args), 1, names, "a synthetic failure")
        return daemon(*args, **kw)
    monkeypatch.setattr(stack, "docker", docker)
    n = len(rig.fake.events)
    assert stack.main(["down"]) == 0
    assert answered == [{"check": False}], answered
    assert stops == [] and not [e for e in rig.fake.events[n:] if e.startswith("stop ")], rig.fake.events[n:]
    assert rig.fake.containers == {} and json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_down_with_no_ros_run_does_what_it_did_before_and_stops_no_container(tmp_path, monkeypatch):
    """sdv/stack/README.md's `down`: a down with no ros run does what it did before. After `up --feed vcan` (the witness
    and the app among its containers, no ros run) down's docker calls are the ros runs' listing, remove_stack's listing
    and its `rm -f` of every container, as before WP3d's down-path fix: no listing of its own and no stop."""
    if not hasattr(os, "getuid"):
        pytest.skip("POSIX only (the stack runs in WSL)")
    fake = StackDocker()
    rc, _run_dir = _up_main(tmp_path, monkeypatch, fake)
    assert rc == 0 and stack.NAMES[stack.WITNESS] in fake.listed(["ps"]), fake.containers
    del fake.calls[:]
    assert stack.main(["down"]) == 0
    assert [c[:2] if c[:1] == ["rm"] else c for c in fake.calls] == _down_listings() + [["rm", "-f"]], fake.calls
    assert fake.containers == {}


def test_down_stops_no_container_of_another_start_while_a_swept_ros_runs_directory_is_open(tmp_path, monkeypatch):
    """down lists each ros run's own containers only, so another start's get what they got before WP3d's down-path fix
    (spec-2 5 item 1: every other feed's behaviour unchanged): after `up --feed ros`, another start sweeps the run's
    containers and leaves its directory open (as `up` on the vcan feed does), and that start's witness, claim bridge and
    app run with its own run's label. down closes the ros run with one listing more than before the fix, by the ros run's
    own label (sdv.stack.run=<its directory's name>/up), which names none of them: no stop call, and remove_stack's
    `rm -f` removes them as it did."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig) == 0
    (run,) = list(rig.runs.iterdir())
    stack.remove_stack()          # what up() on another feed does first
    for name in (stack.NAMES[stack.WITNESS], stack.BRIDGE_CONTAINER, stack.NAMES[attr.APP]):
        rig.fake("run", "-d", "--name", name, "--label", stack.LABEL + "=20260101-vcan/up", IMG)
    stops = _down_events(rig, monkeypatch)
    n, m = len(rig.fake.events), len(rig.fake.calls)
    assert stack.main(["down"]) == 0
    assert stops == [] and not [e for e in rig.fake.events[n:] if e.startswith("stop ")], rig.fake.events[n:]
    listing = ["ps", "--filter", "label=%s=%s/up" % (stack.LABEL, run.name), "--format", "{{.Names}}"]
    assert [c for c in rig.fake.calls[m:] if c[:1] == ["ps"]] == [_down_listings()[0], listing, _down_listings()[1]], rig.fake.calls[m:]
    assert rig.fake.containers == {} and json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_down_stops_the_bridge_and_the_witness_of_an_open_ros_run_whose_feeder_is_gone(tmp_path, monkeypatch):
    """down finds a ros run's bridge and witness by the run's own label, not by its feeder: after `up --feed ros --bridge
    broker`, with the feeder removed outside the stack (`docker rm`, or a prune after it exited) and the run's directory
    still open, down still gives the bridge and then the witness `docker stop -t 10` before the `rm -f`."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    _left_monitor(monkeypatch, run)
    del rig.fake.containers[stack.FEEDER_CONTAINER]
    assert stack.ros_runs_up() == [] and stack.ros_runs_open() == [run]
    stops = _down_events(rig, monkeypatch)
    n = len(rig.fake.events)
    assert stack.main(["down"]) == 0
    ev = rig.fake.events[n:]
    witness, bridge = "stop -t 10 " + stack.NAMES[stack.WITNESS], "stop -t 10 " + stack.BRIDGE_CONTAINER
    assert [e for e in ev if e.startswith("stop ")] == [bridge, witness], ev
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(witness) < ev.index(rm) and stops == [{"check": False}] * 2, (ev, stops)
    assert rig.fake.containers == {}


# --- Regression checks for the down path ---------------------------------------------------------------------------

def test_down_stops_the_bridge_and_the_witness_of_the_ros_run_that_runs_though_an_open_swept_run_sorts_first(tmp_path, monkeypatch):
    """down lists the containers of every ros run it found, not of the first alone: run B is up with --bridge broker under
    another SDV_RUNS (so its directory sorts last) and run A is a ros run another start swept, its directory under RUNS
    still open, so ros_runs_left() is [A, B]. A's listing names nothing; B's names its bridge and witness, which get
    `docker stop -t 10`, the bridge first, both after B's listing and before the `rm -f`; both runs are closed."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 3)
    monkeypatch.setattr(stack, "RUNS", tmp_path / "zz-runs")
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (b,) = list((tmp_path / "zz-runs").iterdir())
    _left_monitor(monkeypatch, b)
    monkeypatch.setattr(stack, "RUNS", rig.runs)
    a = rig.runs / "20260101-a"
    a.mkdir(parents=True)
    (a / "manifest.json").write_text(json.dumps({"format": 1, "feed": "ros"}), encoding="utf-8")
    (a / "host-before.txt").write_text(ROS_HOST, encoding="utf-8")
    assert stack.ros_runs_left() == [a, b]
    stops = _down_events(rig, monkeypatch)
    daemon = stack.docker

    def docker(*args, **kw):          # each run's own listing joins the events too, so the stops' place after B's shows
        if args[:2] == ("ps", "--filter") and args[2].startswith("label=%s=" % stack.LABEL):
            rig.fake.events.append("list " + args[2].split("=", 2)[2])
        return daemon(*args, **kw)
    monkeypatch.setattr(stack, "docker", docker)
    n = len(rig.fake.events)
    assert stack.main(["down"]) == 0
    ev = rig.fake.events[n:]
    witness, bridge = "stop -t 10 " + stack.NAMES[stack.WITNESS], "stop -t 10 " + stack.BRIDGE_CONTAINER
    lists = ["list %s/up" % a.name, "list %s/up" % b.name]
    assert [e for e in ev if e.startswith(("list ", "stop "))] == lists + [bridge, witness], ev
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(witness) < ev.index(rm) and stops == [{"check": False}] * 2, (ev, stops)
    assert rig.fake.containers == {}
    assert all(json.loads((d / "host-check.json").read_text(encoding="utf-8"))["same"] is True for d in (a, b))


def test_down_goes_on_when_every_stop_it_makes_exits_1_with_no_such_container(tmp_path, monkeypatch):
    """down does not read a `docker stop`'s exit (check=False): after `up --feed ros --bridge broker`, every stop down makes
    exits 1 with docker's "No such container" (as when a container ends and is removed between the listing and its stop;
    the stand-in keeps both, so the `rm -f` still names them here), and down still exits 0, having asked the bridge's and
    then the witness's stop before the `rm -f`, which removes the stack; it then stops the native monitor and reads the
    host check after the sweep, the same."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker") == 0
    (run,) = list(rig.runs.iterdir())
    signals = _left_monitor(monkeypatch, run)
    daemon = stack.docker
    answered: List[int] = []

    def docker(*args, **kw):
        if args[:1] == ("stop",):
            p = subprocess.CompletedProcess(list(args), 1, "", "Error response from daemon: No such container: %s\n" % args[-1])
            answered.append(p.returncode)
            if kw.get("check", True):          # as stack.run fails a checked call: its first four words, exit and stderr
                raise stack.StackError("%s failed (%d): %s" % (" ".join(["docker"] + list(args)[:3]), p.returncode, p.stderr))
            return p
        return daemon(*args, **kw)
    monkeypatch.setattr(stack, "docker", docker)
    stops = _down_events(rig, monkeypatch)
    n = len(rig.fake.events)
    assert stack.main(["down"]) == 0
    ev = rig.fake.events[n:]
    witness, bridge = "stop -t 10 " + stack.NAMES[stack.WITNESS], "stop -t 10 " + stack.BRIDGE_CONTAINER
    assert [e for e in ev if e.startswith("stop ")] == [bridge, witness] and answered == [1, 1], (ev, answered)
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(witness) < ev.index(rm) < ev.index("signal") < ev.index("hostcheck --compare"), ev
    assert stops == [{"check": False}] * 2 and signals == [(4242, stack.signal.SIGTERM)], (stops, signals)
    assert rig.fake.containers == {} and json.loads((run / "host-check.json").read_text(encoding="utf-8"))["same"] is True


def test_down_lists_a_ros_run_whose_name_holds_a_dot_by_its_whole_directory_name(tmp_path, monkeypatch):
    """The run's own label is sdv.stack.run=<the run directory's whole name>/up: after `up --feed ros --bridge broker --name
    r6.d1`, the run's directory ending -r6.d1, down lists the run by that whole name (not by a stem cut at the dot) and
    gives its bridge and then its witness `docker stop -t 10` before the `rm -f`."""
    rig = _ros_rig(tmp_path, monkeypatch, readings=[ROS_HOST] * 2)
    assert _ros_main_up(rig, "--bridge", "broker", "--name", "r6.d1") == 0
    (run,) = list(rig.runs.iterdir())
    assert run.name.endswith("-r6.d1"), run.name
    _left_monitor(monkeypatch, run)
    stops = _down_events(rig, monkeypatch)
    n, m = len(rig.fake.events), len(rig.fake.calls)
    assert stack.main(["down"]) == 0
    listing = ["ps", "--filter", "label=%s=%s/up" % (stack.LABEL, run.name), "--format", "{{.Names}}"]
    assert [c for c in rig.fake.calls[m:] if c[:1] == ["ps"]] == [_down_listings()[0], listing, _down_listings()[1]], rig.fake.calls[m:]
    ev = rig.fake.events[n:]
    witness, bridge = "stop -t 10 " + stack.NAMES[stack.WITNESS], "stop -t 10 " + stack.BRIDGE_CONTAINER
    assert [e for e in ev if e.startswith("stop ")] == [bridge, witness], ev
    (rm,) = [e for e in ev if e.startswith("rm ")]
    assert ev.index(bridge) < ev.index(witness) < ev.index(rm) and stops == [{"check": False}] * 2, (ev, stops)
    assert rig.fake.containers == {}


def test_a_rosvss_pin_whose_base_label_is_not_the_autoware_manifest_digest_is_refused_though_the_image_carries_it(tmp_path, monkeypatch):
    """images.json's rosvss labels must name the base images.json's autoware.amd64 manifest digest: a pin whose base label is
    another digest is refused even when the image carries exactly the labels the pin lists (the labels-equal check alone
    would pass it), before anything is written or started."""
    other = "sha256:" + "ee" * 32
    rig = _ros_rig(tmp_path, monkeypatch)
    rig.images["rosvss"]["labels"]["sdv.rosvss.base_digest"] = other
    rig.fake.image["Config"]["Labels"]["sdv.rosvss.base_digest"] = other
    with pytest.raises(stack.StackError, match="name the base"):
        _ros_ctx(rig)
    assert not rig.runs.exists() and not rig.fake.runs()


def test_up_ros_removes_the_stacks_leftover_containers_before_it_starts_the_first(tmp_path, monkeypatch):
    """A container of the stack left by an earlier run (here the recorder's, which a ros run never starts) is removed before
    the run's first container starts, so nothing of another run is judged or listed as this run's."""
    rig = _ros_rig(tmp_path, monkeypatch)
    left = stack.NAMES[attr.RECORDER]
    rig.fake.containers[left] = {"labels": {stack.LABEL: "old/up"}, "image": IMG, "line": "", "running": True}
    _ros_up(rig)
    ev = rig.fake.events
    assert "rm " + left in ev and ev.index("rm " + left) < ev.index("run sdv-stack-databroker"), ev
    assert left not in rig.fake.containers


def test_up_ros_log_exists_before_the_feeders_docker_run_so_docker_does_not_make_it_as_root(tmp_path, monkeypatch):
    """The feeder runs as aw (uid 1000) and writes up/ros-log: the directory is made by the host user before the feeder's
    docker run (docker would make a missing bind source as root, and aw could not write it)."""
    rig = _ros_rig(tmp_path, monkeypatch)
    daemon = stack.docker
    seen: List[Any] = []

    def docker(*args, **kw):
        if args[:1] == ("run",) and stack.FEEDER_CONTAINER in args:
            sources = [Path(a.rsplit(":", 1)[0]) for a in args if a.endswith(":" + stack.ROS_LOG_IN)]
            seen.append([(p, p.is_dir()) for p in sources])
        return daemon(*args, **kw)
    monkeypatch.setattr(stack, "docker", docker)
    ctx, _info = _ros_up(rig)
    assert seen == [[(ctx.run_dir / "up" / "ros-log", True)]], seen


def test_a_feeder_whose_first_record_is_not_its_start_record_is_not_started(tmp_path, monkeypatch):
    """The feeder counts as started on its start record only (FEEDER_READY): a feeder that logs another record and no start
    record fails the run (swept, its host check read after) at the wait for the start record."""
    rig = _ros_rig(tmp_path, monkeypatch, feeder="other")
    ctx = _ros_ctx(rig)
    with pytest.raises(stack.StackError) as e:
        stack.up_ros(ctx, ctx.run_dir / "up", "x/up")
    assert "ros-vss-feeder to log" in str(e.value) and "host check" in str(e.value), str(e.value)
    assert rig.fake.containers == {} and (ctx.run_dir / "host-check.json").is_file()


def test_the_none_mode_table_gives_the_bridge_nothing_though_its_rows_and_write_set_say_otherwise():
    """Without a bridge (--bridge none) no component writes VssClaim: rows that give the bridge its write-back leaves, with
    the bridge configured to write them, fail the planning-sim check in none mode (the table's writer is none), and the
    same rows and write sets pass in broker mode."""
    cat = _ps_catalogue()
    m = _rosvss_module("mapping")
    feeder_set = sorted(m.write_set(m.PLANNING_SIM))
    bridge_paths = sorted(attr.VSSCLAIM_PREFIX + leaf for leaf in stack.bridge_core().WRITEBACK_LEAVES)
    owned = feeder_set + bridge_paths
    rows = attr.planning_sim_rows(cat, PS_LAYER, bridge_writes=bridge_paths, witnessed=owned)
    ws = {attr.FEEDER: feeder_set, attr.BRIDGE: bridge_paths}
    checks = {c[0]: c for c in attr.check_planning_sim(rows, cat, ws, PS_LAYER, bridge_mode="none", witnessed=owned)}
    assert checks[attr.PLANNING_SIM_CHECK][1] is False and "the table's writer is none" in checks[attr.PLANNING_SIM_CHECK][2], checks
    broker = attr.check_planning_sim(rows, cat, ws, PS_LAYER, bridge_mode="broker", witnessed=owned)
    assert all(c[1] for c in broker), broker


# --- the exit test (opt-in) -----------------------------------------------------------------------

@pytest.mark.skipif(os.environ.get("SDV_STACK") != "1", reason="the stack's exit test runs only with SDV_STACK=1 (Docker, sudo -n, ~10 min)")
def test_exit_test():
    name = "pytest-exit-%d" % int(time.time())
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([str(SIM_PY), str(STACK_DIR / "stack.py"), "exit-test", "--name", name], capture_output=True, text=True,
                       env=env, cwd=str(REPO), timeout=3600)
    assert p.returncode == 0, (p.stdout[-3000:], p.stderr[-3000:])
    runs = Path(os.environ.get("SDV_RUNS", "~/sdv-runs")).expanduser()
    summary = json.loads(next(runs.glob("*-%s" % name)).joinpath("exit-test.json").read_text(encoding="utf-8"))
    assert [v["feed"] for v in summary["verdicts"]] == ["dumpfile", "vcan"]
    assert all(v["ok"] and v["same_behaviour"] and v["replays"] == 3 for v in summary["verdicts"])
    assert all(v["witness_values_exact"] and v["only_loopback_listeners"] for v in summary["verdicts"])
    assert all(c["loads"] for c in summary["loadcheck"]["catalogues"])
