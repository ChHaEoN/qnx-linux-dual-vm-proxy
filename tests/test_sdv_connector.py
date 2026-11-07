"""The twin connector's packaging, the twin tests' gate, the connector's logic, its SDK uplink on a stand-in and its
image's build (sdv/connector, sdv/cloud, tests/twin_gate.py): SDV Phase 4 WP0, WP2 and WP3.

NO TEST IN THIS FILE MAY SKIP. The Phase 4 CI recipe fails the run when a test of this file, of
tests/test_twin_allowlist.py or the Monitor guard of tests/test_sdv_vss.py was skipped or did not run
(tests/twin_gate.py's skip check, read from pytest's junit report). An opt-in test (Docker, a pull, a network
read) therefore lives in tests/test_sdv_connector_probe.py, never here; a test here that needs the generated
catalogue or the vss venv asks tests/twin_gate.py for it, which skips without SDV_REQUIRE_GEN=1 and fails with
it.

Pure tests (standard library and pytest; no Docker, no network, no AWS call, no SDK import):
  * the layout: sdv/connector (the device side) and sdv/cloud (the account side) each carry a README that says
    what the directory is and what it is not;
  * the locks: each connector lock is the app lock of its architecture, every one of its 17 pins equal in
    version, sha256 and file, plus exactly awsiotsdk 1.31.0 and awscrt 0.36.1; the aarch64 lock is its x86_64
    twin with the native wheels swapped; each header names its platform, its install line and its check;
  * the SDK pair: sdk-requires.json records what the pinned awsiotsdk wheel declares, bound to that file by its
    sha256, and the lock's awscrt is the one version it declares (pip installs the lock with --no-deps, which
    would hide a mismatch);
  * lockcheck.py, the tool that compares a directory of downloaded wheels with a lock and with that record,
    against synthetic wheels: a wrong hash, a missing or an extra file, and an SDK wheel that declares another
    version each give a problem;
  * the test broker's pin: images.json's top-level test_only entry holds eclipse-mosquitto 2.0.22 as three
    sha256 digests and nothing else; it is not an upstream image, and nothing that starts, loads, bundles or
    scans the stack's images reads the entry;
  * the root CA's pin: ca.json holds the vendor's URL and a sha256 and nothing else, and no certificate file is
    under sdv/connector (the file is the device directory's ca.pem);
  * the gate: SDV_REQUIRE_GEN is read strictly (1, or off; anything else is refused); with it a missing
    catalogue or vss venv fails a twin test, without it the test skips, under a real pytest run too;
  * the skip check on real junit reports of seeded trees: a twin test skipped by a mark, through the gate, in
    a fixture, as an xfail, in a class or for one parameter is named; so are a Monitor guard that was skipped
    or did not run and a twin file of the tree none of whose tests ran; skips elsewhere are not;
  * the probes' pure parts: the paths probe 1 subscribes to are an actuator, an attribute and the eight
    AppState leaves, five of them strings, each a leaf of the generated catalogue and none under the Monitor
    branch; both probes refuse without their opt-in and refuse an output directory inside the repo; against a
    replaced docker, the databroker probe starts the pinned databroker with no network and removes it whatever
    happens, and the broker probe runs Mosquitto by its pinned digest on an --internal network with no
    published port and removes both; "whatever happens" includes a log that cannot be read and a removal that
    itself raises.

WP2, the connector's logic (the second half of this file). Fakes only: a fake signal source in place of the
databroker, a fake uplink in place of the SDK, a fake shadow written from our reading of the service's
documentation, a clock the test moves. No SDK is imported, nothing connects to anything. The ids are the design's
(twin-allowlist.md section 7) and the connector contract's list:
  * limits.py holds every design value, and the limiter's worst case is the one the plan states;
  * the plan's four: the allowlist the connector runs on excludes the whole excluded branch; AppState goes out
    only as a valid record; the spool record has two fields (the fourth, no docker.sock, is WP3's);
  * A4: a desired path list narrows by exact, case-sensitive membership and nothing else, at the function and at
    the connector; config reported echoes no rejected string; a narrowing that lower-cases or strips fails;
  * A5: the subscribe call names exactly the effective set, each an exact leaf, at the connector and in the
    request the databroker would be sent; a connector that subscribes to the project branch fails;
  * A6, at the egress, on the fake source (prep's marked departure from the design, which runs it on the pinned
    databroker: that form is WP3's opt-in canary run): a distinctive canary in every leaf of the excluded branch,
    enumerated from the generated catalogue, and in a fake console log, record directory and lock file; every
    publish captured at the fake uplink; no topic or payload names the excluded branch or carries a canary, the
    keys are the allowlist's, the AppState fields and the envelope's fixed fields, the source handed the connector
    nothing outside the allowlist, and the connector opened no file but its spool. Each publish is also held to
    the effective set in force when it was made (a batch's columns, a record's leaves, a document's values, a
    report's paths). Seeded: the A5 variant, and a frozen module with one excluded leaf forced in (every one of
    them in turn), each fail it. And the second layer alone: a source that hands over everything it holds,
    asked for or not, puts nothing more on the wire;
  * AppState: all eight leaves or none; an invalid record is dropped and counted, its value never logged; seq
    alone drives no shadow update, and the change rule compares as JSON does (true is not 1);
  * batching and shadow: the two cadences; no empty batch, and none counted by the batch counter; no shadow
    update inside 60 s; the flush at stop, with the last read's AppState record in its batch, also
    when it comes within a second of a telemetry publish (the stop waits the gap out, once); the 8 KB and 8-level
    guards; a narrowing or a rate change between two samples closes the open batch, so each row
    is as long as its own header; the next vss document nulls what left the effective set and a connection's
    first document nulls every allowlisted key that is absent;
  * the limiter: each cap at its exact value, and all of them at the fake uplink under a source that changes
    every tick and a config that flaps, driven through the real entry point, which builds the uplink wrapped.
    Every window is counted in whole milliseconds with both ends included, and the closed window is held from
    803 start instants, 602 of them with a window that crosses a power of two, where a float difference alone
    can say that a publish exactly 300 s old is already out;
  * the start spacing, which is what one process's limiter cannot hold: twelve processes a second apart on one
    spool directory, each through the real entry point with a limiter of its own, are one start and eleven
    refusals (status 4, nothing opened); a process begun every second for ten minutes is let in once every 120 s,
    three starts at the most in any closed 300 s; the stamp's form, its write-then-rename, its two ends in whole
    milliseconds, a stamp from the future, a file that is no stamp and a directory that cannot be written; a
    stamp that is a link or may not be read and a temporary name that is a directory are refused at every start;
    a start whose connect failed is a start, and the next one inside the spacing is refused;
  * config: read once at start, then its delta; a rate outside {1, 10}, a refused value and an unknown key cause
    no publish and are echoed nowhere (the echo check looks for something in every one of the 28 refused states,
    and a test holds that it would find it in an echo); a delta that overtakes the get's answer leaves the get
    answered, and a delta alone is no answer: nothing is sampled before the get is answered or its wait is
    over; reported holds the effective rate and path set only; with a shadow that
    re-sends the delta after every accepted update, N identical deltas give zero publishes; a resumed connection
    takes the whole desired state anew (a removed key means the default, a new shadow's lower version is not
    stale), sends the vss document again, and asks again for a get the limiter refused; a spool request in the
    get's answer is written without a delta;
  * a publish the uplink failed, which is not one the limiter refused: a far end that fails every publish for a
    while, with a report, a document or a get due. On the shadow topics one attempt a retry spacing and no more,
    whatever is due; the limiter refuses nothing afterwards (the failed attempts did not use up its window); the
    report of the settings in force, the next document and the stop's document go; a get that failed stays due
    and is asked again, at the start and on a later connection; a document that failed or that the limiter
    refused waits its own 60 s from that try; a telemetry publish, failed or refused, holds nothing back, and a
    failed batch is dropped; an UplinkError at the first get is a failed publish, no failed connect, through the
    real entry point. What the spacing does not mend is held as it stands: one kind that alone fails every time
    ends each step's shadow publishes where it stands in the order (the get, the document, the report);
  * the spool: two fields, both-null refused, a tag or a path-like scenario refused, at most 256 bytes, written
    by write-then-rename, and written nowhere else and by nothing else; the connector writes that record and its
    start stamp, and no third file; a write that failed is not remembered as written (the directory away, then
    back, the same request again), and is tried once a second at the most;
  * topics: the exact strings for example-thing and example_rule; the client id is the thing name;
  * the import graph: no module of sdv/connector but uplink_aws.py (WP3's) imports the SDK, none imports a burst
    tool, and each WP2 module imports the standard library and its siblings only;
  * the log: JSON lines that never hold the thing name, a topic, the endpoint or a certificate path;
  * no traceback, on either stream: whatever is raised while the connector is put together (the frozen module,
    the schema, the uplink's or the source's factory), while the connection is opened (connect, a subscription,
    the first get) or in the loop ends as an exit status and a sentence written beforehand, or as a log line
    with the error's class and place, never its text; in this process, and in a process of its own with a
    stand-in for uplink_aws.py. A class that is no Exception at all (SystemExit, a KeyboardInterrupt raised with
    a text) ends the same way at each of those places; only a KeyboardInterrupt with no argument, the
    interpreter's own, is passed on;
  * sizes: the largest batch at each rate and the largest shadow documents, computed and printed for WP5.

WP3, the SDK uplink and the image (the last part of this file). Still no SDK import, no Docker, no network: a stand-in
for the SDK's two modules that behaves as the pinned SDK was seen to behave at a local broker, and a replaced docker.
The real SDK at a real broker, the built image and the stack's full slice are tests/test_sdv_connector_broker.py
(opt-in); the stack's own hookup is tests/test_sdv_stack.py.
  * the uplink's design values are in limits.py; uplink_aws.py gives the SDK every setting itself (prep gap k: port
    8883, a clean session, the keep-alive, the operation time-out, the SDK's own reconnect timer, ca_filepath, SDK
    metrics off) on one connection built with mtls_from_path, and the CONNECT the far end sees is clean and carries no
    user name; an uplink that leaves one setting to the SDK shows in that CONNECT;
  * its settings come from the environment, and a bad one is refused without repeating it; the SDK is imported in
    one function of one module, and its own logging is switched on nowhere;
  * a publish is one acknowledged packet of the exact bytes; a message reaches its callback as bytes; whatever the
    SDK raises leaves the uplink as an UplinkError without the SDK's text; an error that is no Exception is passed on;
  * the binding hand-off of WP2: a publish the uplink reported as failed is never sent later. With the connection
    lost the SDK is asked nothing; a publish that slipped in between the loss and the SDK's callback, one in flight
    at the loss, and one the SDK says nothing about each stay off the wire when the far end is back and the SDK is
    left to do what it would. An uplink that kept the SDK's connection puts each of them on the wire;
  * the SDK's own reconnect timer is held at SDK_RECONNECT_HOLD_S at both ends, not at the uplink's back-off: the
    SDK writes its queue when its own reconnect is answered and calls on_connection_resumed only then, so a give-up
    from that callback comes too late (the hard review's wire run; the stand-in models the order). With the hold the
    SDK tries nothing while the uplink waits for a publish it handed to a connection the SDK knew was lost; with the
    SDK's default timer that publish, reported as failed, is on the wire;
  * nothing is handed to a connection that has shown no life for LINK_LIFE_MAX_S (THE CHOICE, g): with the uplink
    NEVER told of a loss, a publish tried at any moment from the loss to past the SDK's own reconnect is not sent,
    then or later; the hold alone leaves the last seconds before that reconnect open (the test's own control). A
    connection's life is the moment a request was BEGUN, and only what the SDK answered counts. The uplink's clock
    is one that goes on while the host is suspended, where the platform has it (g's point 4);
  * a lost connection is given up at once; the next one is a new SDK connection, opened at the first publish after
    a back-off that doubles to its cap, with the subscriptions made again and then on_resumed; a connection the SDK
    brings back by itself is disconnected again; close() is safe on an uplink that never connected;
  * a connect the SDK has not answered when the uplink stops waiting: the SDK refuses the disconnect and goes on
    connecting (the stand-in models that, and the far end's closing of an older connection for a newer one of the
    same client id). No other connection is asked for while it is unanswered; a connection that comes late is
    disconnected the moment the SDK reports it and nothing is ever sent through it; a late error asks for nothing.
    An uplink that forgets the unanswered connect loses a connection that was in use;
  * each wait for an answer of the SDK is as long as limits.py says (a request, a connect, the close), and
    CONNECT_WAIT_S does not cover everything the SDK may take: the SDK's own handshake wait is written out;
  * the real entry point, with no uplink handed in (it imports uplink_aws by name, as the image does), puts the
    limiter in front of the SDK uplink: every cap holds at what the SDK was handed, under the source that changes at
    every tick and the config that flaps; a missing SDK and a bad uplink setting are status 2, a failed connect 1;
  * the stop line carries the uplink's own counters beside the connector's and the limiter's (read through the
    limiter, as counts and nothing else), so a record shows a run in which the SDK came back by itself;
  * the Dockerfile: the base by index digest, the lock hash-checked with no resolver and then pip check, a check
    that no module shadows an installed one, a user of its own, one entry point, nothing fetched and nothing of a
    device; build_image.py: it stages exactly the modules the entry point imports, the schema and the frozen
    allowlist (no burst tool, no probe); it refuses a frozen module made from another catalogue, list or schema, and
    one that is not a fresh generation (the real generator, in the vss venv); it sends buildx for each platform with
    that architecture's lock, its own tag and the three labels, from a context outside the repo, and never pushes;
  * images.json's connector entry: both architectures' pins in the bridge entry's shape and the labels of this
    generation; in no other entry, and read by nothing that bundles or deploys.

SDV Phase 6 WP2, the updater's status record (status.py) and what `config` reported makes of it, on the same fakes:
  * status.py takes every record of the form (the three keys, any order and layout, 256 bytes at the most) and returns
    it whole; it refuses a 257-byte file, one that is not UTF-8 or not one JSON object, a duplicate key, another key
    set and each value outside the record's rules, each by a reason that holds no value; a missing file is `missing`,
    a directory, a FIFO, a file that may not be read or a link that loops in its place `unreadable`, and reading never
    blocks or raises;
  * a valid status goes into `config` reported beside the rate and the path set, and the report goes when only the
    status changed, once; an unchanged status is never reported again; a status that was reported and then vanishes
    or is refused is reported as three nulls (the shadow deletes them) in the next report and in every later one, each
    new connection's first among them, until a valid status is read, and so is one an earlier process or another host
    left in the shadow, which the next process learns from its get's answer (one too old to apply included); a status
    no report of which went out is never cleared; a refused status is counted and logged by its reason, and none of its
    values reaches a publish or the log; with no status record and none in the shadow the report is the rate and the
    path set as before; the entry point reads SDV_TWIN_STATUS, by default the directory the stack mounts;
  * status.py is one of the modules the image stages (build_image.MODULES).

Every value here is a pin, a design value or a synthetic fixture; none is a measurement. The identifiers are
placeholders (example-thing, example_rule, broker.example.invalid).

Does not demonstrate (WP2): the shadow service's real replies (the fake shadow is our reading of the
documentation), the SDK, the databroker (the kuksa source is driven by a fake stream here), a start on another
spool directory (the stack's rule, WP3), or any timing. Two tests promise less than their names where they run
on fakes alone: under Windows the real-signal test runs in this process with the handler called by hand (no
signal, no system clock), so only the POSIX run, which is CI's, covers a real SIGTERM; and the fake source's own
test can fail only on the fake.

Does not demonstrate (WP3): the SDK. The stand-in is our model of it, written after its source was read and its
behaviour seen at a local broker; a test here can fail only on that model. Nor that an image was built, that it
runs, or anything about a far end. Two things the stand-in models were seen at the real SDK only in the opt-in file:
the disconnect it refuses while connecting with the connection it reports afterwards, and the race of a publish
between a loss and the SDK's callback (the second not even there: the SDK cancelled every such publish in the runs
made, so that case rests on this model). That a far end closes an older connection for a newer one of the same
client id is the local broker's behaviour and the protocol's rule; the cloud service's is not seen here.
"""
import ast
import concurrent.futures
import hashlib
import importlib
import importlib.util
import io
import json
import os
import re
import signal
import struct
import subprocess
import sys
import threading
import time
import types
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONNECTOR_DIR = REPO / "sdv" / "connector"
CLOUD_DIR = REPO / "sdv" / "cloud"
BURST_DIR = CLOUD_DIR / "burst"          # the breaker's burst tool (prep gap y): another program, in another image
PROBES_DIR = CONNECTOR_DIR / "probes"
STACK_DIR = REPO / "sdv" / "stack"
APP_DIR = REPO / "sdv" / "apps" / "hard-brake-hazard"
SDK_FILE = CONNECTOR_DIR / "sdk-requires.json"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (str(STACK_DIR), str(APP_DIR)):
    if _d not in sys.path:
        sys.path.insert(0, _d)
import attribution as attr  # noqa: E402
import hazard  # noqa: E402

sys.dont_write_bytecode = _saved

IMAGES = json.loads((STACK_DIR / "images.json").read_text(encoding="utf-8"))
SHA = re.compile(r"sha256:[0-9a-f]{64}")
PIN = re.compile(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$", re.M)
LOCKS = ("requirements.lock", "requirements.aarch64.lock")
SDK_PAIR = {"awsiotsdk": "1.31.0", "awscrt": "0.36.1"}          # prep WP0: the pair the SDK declares
NATIVE = {"awscrt", "grpcio", "grpcio-tools", "protobuf", "wcwidth", "websockets"}
GUARD = "test_the_monitor_branch_is_generated_and_is_in_no_allowlist_file"      # tests/test_sdv_vss.py's


def _load(name: str, path: Path) -> Any:
    """A module by its file, no bytecode written beside it."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, path
    mod = importlib.util.module_from_spec(spec)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


@pytest.fixture(scope="module")
def gate() -> Any:
    return importlib.import_module("twin_gate")           # tests/twin_gate.py: pytest puts tests/ on sys.path


@pytest.fixture(scope="module")
def lockcheck() -> Any:
    return _load("sdv_connector_lockcheck", CONNECTOR_DIR / "lockcheck.py")


@pytest.fixture(scope="module")
def probe() -> Any:
    return _load("sdv_connector_probe", PROBES_DIR / "probe.py")


@pytest.fixture(scope="module")
def subprobe() -> Any:
    return _load("sdv_connector_subscribe_probe", PROBES_DIR / "subscribe_probe.py")


# ============================================================ the layout

@pytest.mark.parametrize("directory, side", [(CONNECTOR_DIR, "device side"), (CLOUD_DIR, "account side")])
def test_each_new_directory_carries_a_readme_that_says_what_it_is_and_what_it_is_not(directory, side):
    text = (directory / "README.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    assert text.startswith("# sdv/%s: " % directory.name) and "SDV Phase 4" in flat
    assert side in flat
    is_at, not_at = text.index("\n## What it is\n"), text.index("\n## What it is not\n")
    assert is_at < not_at and len(text[not_at:].strip().splitlines()) > 3          # the second section says something
    assert "scripts/twin" in flat          # says that directory is the old comparison tooling, not this


def test_the_readme_says_what_a_rerun_of_the_slice_with_the_claim_bridge_needs():
    """wp8-review-fix-exact (WP8 item 2, finding 2): the three things a re-run of the opt-in slice with the claim bridge needs and the
    runbook left out, in the README's account of the opt-in tests (white space and code marks aside)."""
    flat = " ".join((CONNECTOR_DIR / "README.md").read_text(encoding="utf-8").replace("`", "").split())
    for said in ("The test is skipped unless SDV_BRIDGE_IMAGE is set, for instance to the ID of sdv-local/vss-claim-bridge:0.1.0 in the "
                 "store. The amd64 bridge has no pin (images.json holds only the arm64 one), so that ID is held to this generation by the "
                 "image's labels alone.",
                 "The stack refuses a connector start within 120 s of the previous one in the same SDV_STATE: the tests give each run a "
                 "state directory of its own, and a re-run by hand in one directory has to wait.",
                 "The opt-in tests keep nothing: the stack's log, the connector's log and the observer's capture lie in pytest's "
                 "temporary directory and nothing copies them out, so a record of such a run needs a wrapper that does."):
        assert said in flat, said
    # what the sentences rest on, held where it can be: the bridge has an arm64 pin and no other; the stack's start spacing is 120 s
    pins = json.loads((REPO / "sdv" / "stack" / "images.json").read_text(encoding="utf-8"))["bridge"]
    assert list(pins) == ["about", "arm64", "labels"]
    assert "A connector start within 120 s of the previous one" in (REPO / "sdv" / "stack" / "stack.py").read_text(encoding="utf-8")
    assert "vss-claim-bridge:0.1.0" in (REPO / "sdv" / "bridge" / "build_image.py").read_text(encoding="utf-8")


def test_no_file_of_the_two_directories_spells_a_path_of_the_excluded_branch():
    """Prep gap d: a new file takes the excluded prefix from attribution.MONITOR_PREFIX and never writes it out."""
    prefix = attr.MONITOR_PREFIX.rstrip(".").lower()
    files = [p for d in (CONNECTOR_DIR, CLOUD_DIR) for p in sorted(d.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    files += [HERE / "twin_gate.py", HERE / "test_sdv_connector.py", HERE / "test_sdv_connector_probe.py", HERE / "test_sdv_connector_broker.py"]
    assert len(files) >= 30 and {"uplink_aws.py", "build_image.py", "Dockerfile", "uplink_driver.py", "canary_writer.py"} <= {p.name for p in files}
    for p in files:
        assert prefix not in p.read_text(encoding="utf-8", errors="replace").lower(), p


# ============================================================ the locks

def lock_pins(path: Path) -> List[Tuple[str, str, str, str]]:
    text = path.read_text(encoding="ascii")
    pins = PIN.findall(text)
    assert len(pins) == len(re.findall(r"^[a-z0-9-]+==", text, re.M)), path          # every pin carries its hash and its file
    names = [p[0] for p in pins]
    assert names == sorted(names) and len(names) == len(set(names)), path
    return pins


def _dist(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


@pytest.mark.parametrize("lock", LOCKS)
def test_the_connector_lock_is_the_app_lock_plus_exactly_the_sdk_pair_every_shared_pin_equal(lock):
    con, app = lock_pins(CONNECTOR_DIR / lock), lock_pins(APP_DIR / lock)
    assert len(app) == 17 and len(con) == 19
    assert [p for p in con if p[0] not in SDK_PAIR] == app          # version, sha256 and file, in the app lock's order
    assert {n: v for n, v, _h, _w in con if n in SDK_PAIR} == SDK_PAIR
    assert dict((n, v) for n, v, _h, _w in con)["kuksa-client"] == "0.6.0"


def test_the_aarch64_lock_is_its_x86_64_twin_with_the_native_wheels_swapped():
    """The form of tests/test_sdv_arm64.py's lock test, with awscrt's stable-ABI wheel among the native ones."""
    x86 = lock_pins(CONNECTOR_DIR / "requirements.lock")
    arm = lock_pins(CONNECTOR_DIR / "requirements.aarch64.lock")
    assert len(arm) == 19 and [(n, v) for n, v, _h, _w in arm] == [(n, v) for n, v, _h, _w in x86]
    native = set()
    for (name, ver, h, whl), (_n, _v, xh, xwhl) in zip(arm, x86):
        assert whl.startswith("%s-%s-" % (_dist(name), ver)) and xwhl.startswith("%s-%s-" % (_dist(name), ver)), name
        if xwhl.endswith("-py3-none-any.whl"):
            assert (whl, h) == (xwhl, xh), name                  # the same file, the same hash
            continue
        native.add(name)
        for wheel, arch in ((whl, "aarch64"), (xwhl, "x86_64")):
            m = re.fullmatch(r"[a-z0-9_]+-[^-]+-(cp312-cp312|cp310-abi3|cp311-abi3)-(\S+)\.whl", wheel)
            assert m, wheel
            assert all(p.startswith("manylinux") and p.endswith("_" + arch) for p in m.group(2).split(".")), wheel
        assert h != xh, name                                      # never the x86_64 wheel's hash
    assert native == NATIVE
    for pins in (x86, arm):          # awscrt ships no cp312 wheel: CPython 3.12 takes its cp311 stable-ABI one
        assert "-cp311-abi3-" in {n: w for n, _v, _h, w in pins}["awscrt"]
        assert {n: w for n, _v, _h, w in pins}["awsiotsdk"] == "awsiotsdk-1.31.0-py3-none-any.whl"


@pytest.mark.parametrize("lock, platform", [("requirements.lock", "x86_64"), ("requirements.aarch64.lock", "aarch64")])
def test_each_connector_lock_header_names_its_platform_its_install_and_its_check(lock, platform):
    text = (CONNECTOR_DIR / lock).read_text(encoding="ascii")
    head = " ".join(ln.lstrip("# ") for ln in text.split("\n") if ln.startswith("#"))
    assert head.startswith("%s -- " % lock) and "Project lock" in head and "SDV Phase 4 WP0" in head
    assert "CPython 3.12, Linux %s" % platform in head and "--require-hashes --no-deps --only-binary=:all:" in head
    assert "awsiotsdk 1.31.0" in head and "awscrt 0.36.1" in head and "sdk-requires.json" in head
    assert "2026-10-04" in head and "the digest PyPI publishes" in head
    assert "not resolved fresh" in head          # made with the app lock as constraints: a fresh resolve moves websockets
    if platform == "aarch64":
        assert "x86_64" not in head and "manylinux2014_aarch64" in head


# ============================================================ the SDK pair

def _sdk() -> Dict[str, Any]:
    return json.loads(SDK_FILE.read_text(encoding="utf-8"))


def test_the_sdk_record_is_one_wheels_metadata_bound_to_that_file_by_its_sha256():
    sdk = _sdk()
    assert set(sdk) == {"format", "about", "name", "version", "wheel", "sha256", "requires_dist", "requires_python", "read"}
    assert sdk["format"] == 1 and (sdk["name"], sdk["version"]) == ("awsiotsdk", "1.31.0")
    assert sdk["wheel"] == "awsiotsdk-1.31.0-py3-none-any.whl" and re.fullmatch(r"[0-9a-f]{64}", sdk["sha256"])
    assert isinstance(sdk["requires_dist"], list) and all(isinstance(r, str) for r in sdk["requires_dist"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", sdk["read"]) and sdk["requires_python"].startswith(">=3.")


@pytest.mark.parametrize("lock", LOCKS)
def test_the_locks_awscrt_is_the_one_version_the_pinned_sdk_wheel_declares(lock, lockcheck):
    """pip installs the lock with --no-deps, so nothing at install time would notice an awscrt the SDK does not
    declare. The record is of the very file the lock pins (a py3-none-any wheel: one file on both architectures)."""
    sdk = _sdk()
    pins = {n: (v, h, w) for n, v, h, w in lock_pins(CONNECTOR_DIR / lock)}
    assert (sdk["version"], sdk["sha256"], sdk["wheel"]) == pins["awsiotsdk"]
    run_time = [r for r in sdk["requires_dist"] if ";" not in r]
    assert run_time == ["awscrt==" + pins["awscrt"][0]]          # one exact pin, and the lock's
    assert all(re.search(r";\s*extra\s*==", r) for r in sdk["requires_dist"] if ";" in r)          # the rest are extras
    assert lockcheck.pair_problems(lockcheck.lock_pins(CONNECTOR_DIR / lock), sdk) == []


def test_lockcheck_refuses_a_lock_whose_pair_is_not_the_one_the_sdk_declares(lockcheck):
    sdk = _sdk()
    pins = lockcheck.lock_pins(CONNECTOR_DIR / "requirements.lock")
    moved = [(n, "0.37.0" if n == "awscrt" else v, h, w) for n, v, h, w in pins]
    assert lockcheck.pair_problems(moved, sdk) == ["the lock pins awscrt 0.37.0; awsiotsdk 1.31.0 declares awscrt==0.36.1"]
    other_file = [(n, v, "0" * 64 if n == "awsiotsdk" else h, w) for n, v, h, w in pins]
    assert lockcheck.pair_problems(other_file, sdk) == [
        "the lock pins awsiotsdk 1.31.0 as awsiotsdk-1.31.0-py3-none-any.whl sha256 %s; the record is of %s sha256 %s"
        % ("0" * 64, sdk["wheel"], sdk["sha256"])]
    gone = [p for p in pins if p[0] != "awscrt"]
    assert lockcheck.pair_problems(gone, sdk) == ["the lock has no pin for awscrt, which awsiotsdk 1.31.0 declares (awscrt==0.36.1)"]
    ranged = dict(sdk, requires_dist=["awscrt>=0.36.1"])
    assert lockcheck.pair_problems(pins, ranged) == ["awsiotsdk 1.31.0 declares 'awscrt>=0.36.1', which is not one exact pin"]


# ------------------------------------------------------------ lockcheck.py against synthetic wheels

def _wheel(path: Path, name: str, version: str, requires: Tuple[str, ...] = (), requires_python: str = ">=3.8") -> str:
    """A minimal wheel (a zip whose dist-info holds METADATA); returns its sha256."""
    meta = "Metadata-Version: 2.1\nName: %s\nVersion: %s\nRequires-Python: %s\n" % (name, version, requires_python)
    meta += "".join("Requires-Dist: %s\n" % r for r in requires) + "\nA long description.\nRequires-Dist: not-a-header==9\n"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("%s/__init__.py" % _dist(name), "")
        z.writestr("%s-%s.dist-info/METADATA" % (_dist(name), version), meta)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic(tmp_path: Path, crt: str = "2.0.0", declares: Tuple[str, ...] = ("fakecrt==2.0.0", "boto9>=1; extra == 'dev'")):
    """A wheel directory, a lock that pins it and the SDK record of its fakesdk wheel."""
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    files = {"fakecrt": ("fakecrt-%s-cp311-abi3-manylinux2014_x86_64.whl" % crt, crt, ()),
             "fakesdk": ("fakesdk-1.0.0-py3-none-any.whl", "1.0.0", declares)}
    lines = ["# requirements.lock -- synthetic"]
    sha = {}
    for name in sorted(files):
        fname, ver, req = files[name]
        sha[name] = _wheel(wheels / fname, name, ver, req)
        lines += ["%s==%s \\" % (name, ver), "    --hash=sha256:%s" % sha[name], "    # %s" % fname]
    lock = tmp_path / "requirements.lock"
    lock.write_text("\n".join(lines) + "\n", encoding="ascii")
    sdk = {"format": 1, "about": "synthetic", "name": "fakesdk", "version": "1.0.0", "wheel": files["fakesdk"][0],
           "sha256": sha["fakesdk"], "requires_dist": list(declares), "requires_python": ">=3.8", "read": "2026-10-04"}
    return lock, wheels, sdk


def test_lockcheck_accepts_a_directory_that_holds_exactly_the_locks_files(lockcheck, tmp_path):
    lock, wheels, sdk = _synthetic(tmp_path)
    rec = lockcheck.check_wheels(lock, wheels, sdk)
    assert rec["problems"] == [] and rec["ok"] is True and rec["files"] == 2
    assert rec["sdk_metadata"] == {"name": "fakesdk", "version": "1.0.0", "requires_python": ">=3.8",
                                   "requires_dist": ["fakecrt==2.0.0", "boto9>=1; extra == 'dev'"]}
    assert lockcheck.main(["wheels", str(wheels), "--lock", str(lock), "--sdk", _json(tmp_path, sdk)]) == 0


def _json(tmp_path: Path, obj: Any) -> str:
    p = tmp_path / "sdk.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_lockcheck_refuses_a_wheel_of_another_hash_a_missing_one_and_an_extra_file(lockcheck, tmp_path, capsys):
    lock, wheels, sdk = _synthetic(tmp_path)
    crt = wheels / "fakecrt-2.0.0-cp311-abi3-manylinux2014_x86_64.whl"
    good = crt.read_bytes()
    crt.write_bytes(good + b"\0")
    rec = lockcheck.check_wheels(lock, wheels, sdk)
    assert not rec["ok"] and len(rec["problems"]) == 1
    assert re.fullmatch(r"fakecrt-2\.0\.0-\S+\.whl hashes to [0-9a-f]{64}, the lock says [0-9a-f]{64}", rec["problems"][0])
    crt.unlink()
    assert lockcheck.check_wheels(lock, wheels, sdk)["problems"] == ["%s is not in %s" % (crt.name, wheels)]
    crt.write_bytes(good)
    (wheels / "stray-1.0-py3-none-any.whl").write_bytes(b"x")
    assert lockcheck.check_wheels(lock, wheels, sdk)["problems"] == ["stray-1.0-py3-none-any.whl is in %s and not in the lock" % wheels]
    assert lockcheck.main(["wheels", str(wheels), "--lock", str(lock), "--sdk", _json(tmp_path, sdk)]) == 1
    assert "not in the lock" in capsys.readouterr().out


def test_lockcheck_refuses_an_sdk_wheel_whose_metadata_is_not_the_record(lockcheck, tmp_path):
    """The record is what the tests hold the lock to, so the real wheel must say the same: a wheel that declares
    another version of its dependency than the record does is a difference, though the lock's hashes all hold."""
    lock, wheels, sdk = _synthetic(tmp_path, declares=("fakecrt==2.0.1",))
    stale = dict(sdk, requires_dist=["fakecrt==2.0.0"])
    rec = lockcheck.check_wheels(lock, wheels, stale)
    assert rec["problems"] == [
        "fakesdk-1.0.0-py3-none-any.whl declares requires_dist ['fakecrt==2.0.1'], the record says ['fakecrt==2.0.0']",
    ] and rec["sdk_metadata"]["requires_dist"] == ["fakecrt==2.0.1"]
    # and with the record right, the lock's fakecrt 2.0.0 is not the version declared
    assert lockcheck.check_wheels(lock, wheels, sdk)["problems"] == ["the lock pins fakecrt 2.0.0; fakesdk 1.0.0 declares fakecrt==2.0.1"]


def test_lockcheck_reads_only_the_metadata_headers(lockcheck, tmp_path):
    w = tmp_path / "a-1-py3-none-any.whl"
    _wheel(w, "a", "1", ("b==2", "c>=1; extra == 'dev'"), ">=3.9")
    assert lockcheck.wheel_metadata(w) == {"name": "a", "version": "1", "requires_python": ">=3.9",
                                           "requires_dist": ["b==2", "c>=1; extra == 'dev'"]}
    bad = tmp_path / "nometa-1-py3-none-any.whl"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("x.py", "")
    with pytest.raises(lockcheck.LockError, match="holds no dist-info/METADATA"):
        lockcheck.wheel_metadata(bad)


# ============================================================ the test broker's pin

MOSQUITTO = "eclipse-mosquitto"


def test_the_test_broker_is_pinned_as_three_digests_and_is_not_an_upstream_image():
    assert set(IMAGES["test_only"]) == {MOSQUITTO}
    pin = IMAGES["test_only"][MOSQUITTO]
    assert set(pin) == {"repo", "version", "index_digest", "amd64_manifest", "arm64_manifest", "read", "note"}
    assert (pin["repo"], pin["version"]) == ("docker.io/library/eclipse-mosquitto", "2.0.22")
    digests = [pin[k] for k in ("index_digest", "amd64_manifest", "arm64_manifest")]
    assert all(SHA.fullmatch(d) for d in digests) and len(set(digests)) == 3
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", pin["read"])
    # not an upstream image: pull_upstream would pull it on every prepare and want a revision label of it
    assert MOSQUITTO not in IMAGES["upstream"] and len(IMAGES["upstream"]) == 4
    assert MOSQUITTO not in IMAGES["local"] and MOSQUITTO not in IMAGES["base"]
    everything_else = json.dumps({k: v for k, v in IMAGES.items() if k not in ("test_only", "about")})
    assert "mosquitto" not in everything_else and not any(d in everything_else for d in digests)
    assert "test_only" in IMAGES["about"] and "never" in pin["note"]


def test_nothing_that_starts_loads_bundles_or_scans_the_stacks_images_reads_the_test_only_entry():
    readers = [STACK_DIR / "stack.py", STACK_DIR / "bundle.py", STACK_DIR / "step3.py", REPO / "sdv" / "arm64" / "arm64.py",
               REPO / "sdv" / "bridge" / "build_image.py", REPO / "orin-native" / "gpu-concurrency" / "vss_setup.py",
               REPO / "orin-native" / "gpu-concurrency" / "run-vss-setup.sh", REPO / "orin-native" / "gpu-concurrency" / "run-vss-suite.sh"]
    for f in readers:
        text = f.read_text(encoding="utf-8")
        assert "test_only" not in text and "mosquitto" not in text.lower(), f


def test_the_probe_names_the_test_broker_by_its_pinned_index_digest(probe):
    pin = IMAGES["test_only"][MOSQUITTO]
    assert probe.broker_ref(IMAGES) == "docker.io/library/eclipse-mosquitto@" + pin["index_digest"]
    with pytest.raises(probe.ProbeError, match="no test_only pin"):
        probe.broker_ref({k: v for k, v in IMAGES.items() if k != "test_only"})
    moved = json.loads(json.dumps(IMAGES))
    moved["test_only"][MOSQUITTO]["index_digest"] = "sha256:abc"
    with pytest.raises(probe.ProbeError, match="not sha256:<64 hex>"):
        probe.broker_ref(moved)


# ============================================================ the root CA's pin

def test_the_root_ca_is_pinned_by_its_url_and_sha256_and_its_file_is_not_here():
    """the root CA reference (WP3's bullet, carried over to A3): AmazonRootCA1.pem, a public file fetched once on the PC over
    HTTPS, pinned in ca.json by its URL and its sha256 and nothing else. The file itself is the device directory's
    ca.pem: no certificate file is under sdv/connector, and the image's staged list, held exactly below, has no
    ca.json and no CA."""
    raw = (CONNECTOR_DIR / "ca.json").read_bytes()
    assert raw.endswith(b"}\n") and b"\r" not in raw
    pin = json.loads(raw.decode("ascii"))
    assert isinstance(pin, dict) and list(pin) == ["url", "sha256"]
    assert pin["url"] == "https://www.amazontrust.com/repository/AmazonRootCA1.pem"
    assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    assert not [p for p in CONNECTOR_DIR.rglob("*") if p.suffix.lower() in (".pem", ".crt", ".cer", ".der", ".key")]


# ============================================================ the gate (tests/twin_gate.py)

def _outcome(call: Any) -> Tuple[str, Any]:
    """What a gate call did: ("returned", value), ("skipped", message) or ("failed", message). The outcome is caught
    here and compared by the test, never left to pytest.raises: a gate that skipped where it should have failed would
    raise pytest's skip through a `raises(fail)` block and skip the very test that checks it, which reads as a pass."""
    try:
        return "returned", call()
    except pytest.skip.Exception as exc:
        return "skipped", str(exc)
    except pytest.fail.Exception as exc:
        return "failed", str(exc)


def test_the_switch_is_read_strictly(gate, monkeypatch):
    assert gate.REQUIRE_ENV == "SDV_REQUIRE_GEN"
    monkeypatch.delenv(gate.REQUIRE_ENV, raising=False)
    assert _outcome(gate.required) == ("returned", False)
    for off in ("", "0"):
        monkeypatch.setenv(gate.REQUIRE_ENV, off)
        assert _outcome(gate.required) == ("returned", False)
    monkeypatch.setenv(gate.REQUIRE_ENV, "1")
    assert _outcome(gate.required) == ("returned", True)
    for bad in ("true", "yes", "2", " 1", "on"):          # a switch that a typo turns off would be a no-op
        monkeypatch.setenv(gate.REQUIRE_ENV, bad)
        how, why = _outcome(gate.required)
        assert how == "failed" and why.startswith("SDV_REQUIRE_GEN is %r: it is 1, or unset" % bad), (bad, how, why)
        assert _outcome(lambda: gate.missing("an input"))[0] == "failed"          # and so does every gate call under it


def test_a_missing_catalogue_skips_without_the_switch_and_fails_with_it(gate, monkeypatch, tmp_path):
    gen = tmp_path / "gen"
    monkeypatch.setenv("SDV_GEN", str(gen))
    monkeypatch.delenv(gate.REQUIRE_ENV, raising=False)
    how, why = _outcome(gate.catalogue)
    assert how == "skipped" and why.startswith("needs the generated catalogue in %s" % gen), (how, why)
    monkeypatch.setenv(gate.REQUIRE_ENV, "1")
    how, why = _outcome(gate.catalogue)
    assert how == "failed", (how, why)
    assert why.startswith("SDV_REQUIRE_GEN=1 and a twin test's input is missing: needs the generated catalogue in %s" % gen), why
    gen.mkdir()
    (gen / "vss-databroker.json").write_text("{}", encoding="utf-8")          # one of the two files is not the catalogue
    how, why = _outcome(gate.catalogue)
    assert how == "failed" and why.endswith(": no vss-ids.vspec"), (how, why)
    assert _outcome(lambda: gate.catalogue("vss-databroker.json")) == ("returned", gen)          # a test names the files it reads
    (gen / "vss-ids.vspec").write_text("", encoding="utf-8")
    assert _outcome(gate.catalogue) == ("returned", gen) and gate.CATALOGUE_FILES == ("vss-databroker.json", "vss-ids.vspec")
    monkeypatch.delenv(gate.REQUIRE_ENV)
    assert _outcome(gate.catalogue) == ("returned", gen)


def test_a_missing_vss_venv_skips_without_the_switch_and_fails_with_it(gate, monkeypatch, tmp_path):
    venv = tmp_path / "venv"
    monkeypatch.setenv("SDV_VENV", str(venv))
    monkeypatch.delenv(gate.REQUIRE_ENV, raising=False)
    how, why = _outcome(gate.vss_venv)
    assert how == "skipped" and why.startswith("needs the vss-tools venv %s " % venv), (how, why)
    monkeypatch.setenv(gate.REQUIRE_ENV, "1")
    how, why = _outcome(gate.vss_venv)
    assert how == "failed", (how, why)
    assert why.startswith("SDV_REQUIRE_GEN=1 and a twin test's input is missing: needs the vss-tools venv %s " % venv), why
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("", encoding="utf-8")          # an interpreter with no vss-tools is not the venv
    how, why = _outcome(gate.vss_venv)
    assert how == "failed" and why.endswith(": no bin/vspec"), (how, why)
    (venv / "bin" / "vspec").write_text("", encoding="utf-8")
    assert _outcome(gate.vss_venv) == ("returned", venv / "bin" / "python")
    monkeypatch.delenv(gate.REQUIRE_ENV)
    assert _outcome(gate.vss_venv) == ("returned", venv / "bin" / "python")


def _pytest(tree: Path, env_extra: Dict[str, str], *args: str) -> subprocess.CompletedProcess:
    """A real pytest run in a seeded tree, with tests/twin_gate.py importable and none of this run's switches."""
    env = {k: v for k, v in os.environ.items() if k not in ("SDV_REQUIRE_GEN", "SDV_GEN", "SDV_VENV", "PYTEST_ADDOPTS")}
    env.update(PYTHONPATH=str(HERE), PYTHONDONTWRITEBYTECODE="1")
    env.update(env_extra)
    return subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=str(tree), env=env,
                          capture_output=True, text=True, timeout=300)


TWIN_TEST = '''\
import twin_gate


def test_reads_the_catalogue():
    assert (twin_gate.catalogue() / "vss-databroker.json").is_file()


def test_runs_in_the_venv():
    assert twin_gate.vss_venv().name == "python"
'''


def test_under_pytest_a_twin_test_fails_with_the_switch_and_skips_without_it(tmp_path):
    (tmp_path / "test_twin.py").write_text(TWIN_TEST, encoding="utf-8")
    absent = {"SDV_GEN": str(tmp_path / "gen"), "SDV_VENV": str(tmp_path / "venv")}
    r = _pytest(tmp_path, absent)
    assert r.returncode == 0 and re.search(r"^2 skipped in ", r.stdout, re.M), r.stdout + r.stderr
    r = _pytest(tmp_path, dict(absent, SDV_REQUIRE_GEN="1"))
    assert r.returncode == 1 and re.search(r"^2 failed in ", r.stdout, re.M), r.stdout + r.stderr
    assert "skipped" not in r.stdout.splitlines()[-1] and r.stdout.count("SDV_REQUIRE_GEN=1 and a twin test's input is missing") >= 2
    r = _pytest(tmp_path, dict(absent, SDV_REQUIRE_GEN="yes"))          # a mistyped switch is not a quiet skip
    assert r.returncode == 1 and re.search(r"^2 failed in ", r.stdout, re.M), r.stdout + r.stderr
    for d, names in ((tmp_path / "gen", ("vss-databroker.json", "vss-ids.vspec")), (tmp_path / "venv" / "bin", ("python", "vspec"))):
        d.mkdir(parents=True)
        for n in names:
            (d / n).write_text("", encoding="utf-8")
    for extra in ({}, {"SDV_REQUIRE_GEN": "1"}):
        r = _pytest(tmp_path, dict(absent, **extra))
        assert r.returncode == 0 and re.search(r"^2 passed in ", r.stdout, re.M), r.stdout + r.stderr


# ============================================================ the skip check, on real junit reports of seeded trees

GUARD_FILE = "def %s():\n    pass\n\n\ndef test_the_literal_list():\n    import pytest\n    pytest.skip('no local literal list')\n" % GUARD
OK_FILE = "def test_ok():\n    pass\n"
SKIPS_FILE = '''\
import pytest
import twin_gate

NEEDS = pytest.mark.skipif(True, reason="by a mark")


@NEEDS
def test_by_mark():
    pass


def test_through_the_gate():
    twin_gate.missing("needs a thing that is not here")


@pytest.fixture
def absent():
    pytest.skip("by a fixture")


def test_by_fixture(absent):
    pass


@pytest.mark.xfail(reason="an expected failure is not a pass either")
def test_xfail():
    assert 0


class TestInClass:
    @pytest.mark.skip(reason="in a class")
    def test_method(self):
        pass


@pytest.mark.parametrize("n", [1, 2])
def test_param(n):
    if n == 2:
        pytest.skip("one parameter")


def test_ok():
    pass
'''


def _seed(tmp_path: Path, files: Dict[str, str]) -> Path:
    tree = tmp_path / "tree"
    for rel, text in files.items():
        p = tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tree


def _report(tree: Path, *args: str, rc: int = 0) -> str:
    out = tree / "junit.xml"
    r = _pytest(tree, {}, "-rs", "--junitxml=%s" % out, *args, "tests")
    assert r.returncode == rc, r.stdout + r.stderr
    return out.read_text(encoding="utf-8")


CLEAN = {"tests/test_sdv_vss.py": GUARD_FILE, "tests/test_sdv_connector.py": OK_FILE, "tests/test_twin_allowlist.py": OK_FILE,
         "tests/test_other.py": "import pytest\n\n\n@pytest.mark.skip(reason='opt-in')\ndef test_opt_in():\n    pass\n"}


def test_the_skip_check_passes_a_run_in_which_the_twin_tests_and_the_guard_ran(gate, tmp_path):
    tree = _seed(tmp_path, CLEAN)
    xml = _report(tree)
    assert xml.count("<skipped") == 2          # the literal-list test and the opt-in one: skips elsewhere are not its business
    assert gate.skip_problems(xml, tree) == []
    assert gate.TWIN_TEST_FILES == ("tests/test_twin_allowlist.py", "tests/test_sdv_connector.py")
    assert gate.MONITOR_GUARD == ("tests/test_sdv_vss.py", GUARD)
    # tests/test_twin_allowlist.py arrives with WP1: a tree without the file owes no test of it
    tree2 = _seed(tmp_path / "b", {k: v for k, v in CLEAN.items() if k != "tests/test_twin_allowlist.py"})
    assert gate.skip_problems(_report(tree2), tree2) == []


def test_the_skip_check_names_a_twin_test_however_it_was_skipped(gate, tmp_path):
    tree = _seed(tmp_path, dict(CLEAN, **{"tests/test_sdv_connector.py": SKIPS_FILE}))
    r = _pytest(tree, {}, "-rs", "tests")
    # why the check reads the junit report and not -rs's lines: -rs names the line a skip was raised at, and for a
    # skip raised in the gate that is the gate's own file, not the test's
    assert re.search(r"^SKIPPED \[1\] \S*twin_gate\.py:\d+: needs a thing that is not here$", r.stdout, re.M), r.stdout
    problems = gate.skip_problems(_report(tree), tree)
    assert problems == ["tests/test_sdv_connector.py::%s was skipped (%s)" % (name, why) for name, why in (
        ("test_by_mark", "by a mark"), ("test_through_the_gate", "needs a thing that is not here"),
        ("test_by_fixture", "by a fixture"), ("test_xfail", "an expected failure is not a pass either"),
        ("TestInClass::test_method", "in a class"), ("test_param[2]", "one parameter"))]


def test_the_skip_check_names_a_skipped_test_of_the_allowlist_file(gate, tmp_path):
    tree = _seed(tmp_path, dict(CLEAN, **{"tests/test_twin_allowlist.py": "import pytest\n\n\n@pytest.mark.skipif(True, reason='needs "
                                          "the generated catalogue')\ndef test_a1():\n    pass\n"}))
    assert gate.skip_problems(_report(tree), tree) == ["tests/test_twin_allowlist.py::test_a1 was skipped (needs the generated catalogue)"]


def test_the_skip_check_fails_when_the_guard_was_skipped_or_did_not_run(gate, tmp_path):
    marked = "import pytest\n\n\n@pytest.mark.skipif(True, reason='needs the vss-tools venv')\n" + GUARD_FILE
    tree = _seed(tmp_path / "a", dict(CLEAN, **{"tests/test_sdv_vss.py": marked}))
    assert gate.skip_problems(_report(tree), tree) == ["the Monitor guard tests/test_sdv_vss.py::%s was skipped (needs the vss-tools venv)" % GUARD]
    tree = _seed(tmp_path / "b", dict(CLEAN, **{"tests/test_sdv_vss.py": OK_FILE}))
    assert gate.skip_problems(_report(tree), tree) == ["the Monitor guard tests/test_sdv_vss.py::%s did not run" % GUARD]
    tree = _seed(tmp_path / "c", CLEAN)
    xml = _report(tree, "--deselect", "tests/test_sdv_vss.py::%s" % GUARD)
    assert gate.skip_problems(xml, tree) == ["the Monitor guard tests/test_sdv_vss.py::%s did not run" % GUARD]
    tree = _seed(tmp_path / "d", dict(CLEAN, **{"tests/test_sdv_vss.py": GUARD_FILE.replace("    pass\n", "    assert 0\n", 1)}))
    assert gate.skip_problems(_report(tree, rc=1), tree) == ["the Monitor guard tests/test_sdv_vss.py::%s failed" % GUARD]


def test_the_skip_check_fails_when_a_twin_file_of_the_tree_ran_no_test(gate, tmp_path):
    tree = _seed(tmp_path, CLEAN)
    xml = _report(tree, "--deselect", "tests/test_sdv_connector.py::test_ok")
    assert gate.skip_problems(xml, tree) == ["tests/test_sdv_connector.py is in the tree and none of its tests ran"]
    assert gate.skip_problems("<testsuites></testsuites>", tree)[0] == "the report holds no test case"


def test_the_skip_checks_command_line_exits_1_on_a_seeded_skip_and_0_on_a_clean_run(tmp_path):
    cli = [sys.executable, "-B", str(HERE / "twin_gate.py")]
    clean = _seed(tmp_path / "a", CLEAN)
    _report(clean)
    r = subprocess.run(cli + [str(clean / "junit.xml")], cwd=str(clean), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "twin_gate: 3 test(s) of the twin files and the Monitor guard ran, none skipped"
    seeded = _seed(tmp_path / "b", dict(CLEAN, **{"tests/test_sdv_connector.py": OK_FILE + "\n\ndef test_seeded():\n    import pytest\n"
                                                  "    pytest.skip('seeded')\n"}))
    _report(seeded)
    r = subprocess.run(cli + [str(seeded / "junit.xml")], cwd=str(seeded), capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "twin_gate: tests/test_sdv_connector.py::test_seeded was skipped (seeded)" in r.stdout, r.stdout + r.stderr
    for bad in ("missing.xml", "garbled.xml"):
        (clean / "garbled.xml").write_text("not xml", encoding="utf-8")
        r = subprocess.run(cli + [str(clean / bad)], cwd=str(clean), capture_output=True, text=True, timeout=120)
        assert r.returncode == 2 and "twin_gate: cannot read the junit report" in r.stderr, r.stdout + r.stderr
    r = subprocess.run(cli, cwd=str(clean), capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "usage" in r.stderr


# ============================================================ the probes' pure parts

def test_probe_1_subscribes_to_an_actuator_an_attribute_and_the_eight_appstate_leaves_five_of_them_strings(gate, probe):
    gen = gate.catalogue("vss-databroker.json")
    leaves = attr.leaf_nodes(json.loads((gen / "vss-databroker.json").read_text(encoding="utf-8")))
    paths = probe.probe_paths()
    assert paths == (hazard.HAZARD, attr.WHEELBASE) + hazard.LEAF_PATHS and len(paths) == 10 == len(set(paths))
    plan = probe.probe_plan(leaves)
    assert [e["path"] for e in plan] == list(paths)
    by = {e["path"]: e for e in plan}
    assert by[hazard.HAZARD]["type"] == "actuator" and by[attr.WHEELBASE]["type"] == "attribute"
    appstate = [by[p] for p in hazard.LEAF_PATHS]
    assert all(e["type"] == "sensor" for e in appstate)
    assert [e["datatype"] for e in appstate] == [dt for _prop, _leaf, dt in hazard.LEAVES]
    assert sum(1 for e in appstate if e["datatype"] == "string") == 5
    for e in plan:
        node = leaves[e["path"]]
        assert (e["type"], e["datatype"]) == (node["type"], node["datatype"]) and e["default"] == node.get("default")
        assert e["write"] != node.get("default") and ("allowed" not in node or e["write"] in node["allowed"]), e
        assert not e["path"].startswith(attr.MONITOR_PREFIX)
    assert set(paths) <= attr.ALLOWLIST_V1          # nothing the twin may not carry is probed
    assert by[attr.WHEELBASE]["default"] is not None          # the attribute's current value is its catalogue default


def test_the_probe_plan_refuses_a_path_that_is_no_leaf_and_one_under_the_excluded_branch(probe):
    node = {"type": "sensor", "datatype": "uint8"}
    with pytest.raises(probe.ProbeError, match="is not a leaf of the generated catalogue"):
        probe.probe_plan({}, paths=("Vehicle.NoSuch",))
    excluded = attr.MONITOR_PREFIX + "Anything"
    with pytest.raises(probe.ProbeError, match="lies under the branch the twin excludes"):
        probe.probe_plan({excluded: node}, paths=(excluded,))
    with pytest.raises(probe.ProbeError, match="no write value for datatype 'double'"):
        probe.probe_plan({"Vehicle.X": {"type": "sensor", "datatype": "double"}}, paths=("Vehicle.X",))
    assert probe.probe_plan({"Vehicle.X": dict(node, default=200)}, paths=("Vehicle.X",))[0]["write"] != 200


def test_the_in_container_probe_types_each_value_and_sums_up_what_the_databroker_did(subprobe):
    assert subprobe.value_field("boolean") == "bool" and subprobe.value_field("string") == "string"
    assert [subprobe.value_field(t) for t in ("uint8", "uint16", "uint32")] == ["uint32"] * 3
    with pytest.raises(ValueError, match="no kuksa.val.v2 value field for datatype 'double'"):
        subprobe.value_field("double")
    paths = {
        "A": {"plan": {"default": None, "write": True}, "first_before": {"in_response": True, "value": None},
              "write": {"result": "accepted"}, "later_write": {"arrived": True, "value": True},
              "first_after": {"in_response": True, "value": True}, "get_value": {"value": True}},
        "B": {"plan": {"default": 2700, "write": 2701}, "first_before": {"in_response": True, "value": 2700},
              "write": {"result": "refused INVALID_ARGUMENT: no"}, "later_write": {"arrived": False, "value": None},
              "first_after": {"in_response": True, "value": 2700}, "get_value": {"value": 2700}},
    }
    assert subprobe.summarise(paths) == {
        "default_in_first_response": {"B": True},          # only a path the catalogue gives a default has the question
        "write_accepted": {"A": True, "B": False},
        "later_write_arrives": {"A": True, "B": False},
        "first_response_carries_current_value": {"A": True, "B": True},          # B's current value is still its default
        "get_value_serves_current_value": {"A": True, "B": True},
    }


def test_both_probes_refuse_without_their_opt_in_and_an_output_directory_inside_the_repo(probe, monkeypatch, tmp_path, capsys):
    called: List[Tuple[str, ...]] = []
    monkeypatch.setattr(probe, "docker", lambda *a, **k: called.append(a))
    monkeypatch.delenv(probe.OPT_IN_ENV, raising=False)
    assert probe.OPT_IN_ENV == "SDV_CONNECTOR_PROBE"
    for cmd in ("databroker", "broker"):
        assert probe.main([cmd, "--out", str(tmp_path / cmd)]) == 2
        assert "SDV_CONNECTOR_PROBE=1" in capsys.readouterr().err
    monkeypatch.setenv(probe.OPT_IN_ENV, "1")
    for cmd in ("databroker", "broker"):
        assert probe.main([cmd, "--out", str(REPO / "sdv-out" / "probe")]) == 1
        assert "is inside the repo" in capsys.readouterr().err
    assert called == [] and not (REPO / "sdv-out" / "probe").exists()


class FakeDocker:
    """probe.docker replaced: every argument vector kept, canned answers by its first words."""

    def __init__(self, fail_on: Tuple[str, ...] = (), raise_at: Optional[Dict[str, int]] = None) -> None:
        self.calls: List[List[str]] = []
        self.fail_on = fail_on
        self.raise_at = dict(raise_at or {})   # {a first word: from which call of it on the command itself raises (it timed out)}
        self.present = True
        self.repo_digests: Any = None          # None: what the daemon lists for the reference asked about

    def __call__(self, *args: str, check: bool = True, timeout: float = 120) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        if args[0] in self.raise_at and len(self.named(args[0])) >= self.raise_at[args[0]]:
            raise subprocess.TimeoutExpired(["docker", args[0]], timeout)
        out, rc = "", 0
        if args[:2] == ("image", "inspect"):
            rc = 0 if self.present else 1
            # a Docker Hub library image is listed under its short name, as the daemon lists it
            listed = [args[-1].replace("docker.io/library/", "")] if self.repo_digests is None else self.repo_digests
            out = json.dumps([{"Id": "sha256:" + "ab" * 32, "Architecture": "amd64", "Os": "linux", "RepoDigests": listed}])
            if "-f" in args:
                out = "sha256:" + "cd" * 32
        elif args[:1] == ("logs",):
            out = "Listening on 127.0.0.1:55555\nmosquitto version 2.0.22 running\n"
        elif args[:1] == ("inspect",):
            out = "true" if "{{.State.Running}}" in args else json.dumps({"1883/tcp": None})
        elif args[:2] == ("network", "inspect"):
            out = "true"
        elif args[:1] == ("port",):
            out = ""
        elif args[:1] == ("run",) and "--rm" in args:
            out = json.dumps({"server": {"name": "databroker", "version": "0.7.1"}, "paths": {}, "summary": {}})
        if any(w in args for w in self.fail_on):
            rc, out = 1, ""
        p = subprocess.CompletedProcess(list(args), rc, out, "boom" if rc else "")
        if rc and check and args[:2] != ("image", "inspect"):
            raise AssertionError("unexpected checked failure in the fake: %r" % (args,))
        return p

    def named(self, *first: str) -> List[List[str]]:
        return [c for c in self.calls if tuple(c[:len(first)]) == first]


FORBIDDEN = {"-p", "--publish", "-P", "--publish-all", "--expose", "--privileged"}


def _hardened(args: List[str]) -> None:
    joined = " ".join(args)
    assert not FORBIDDEN & set(args) and "docker.sock" not in joined and "0.0.0.0" not in joined, args
    assert args[args.index("--cap-drop") + 1] == "ALL" and "no-new-privileges" in args and "--read-only" in args, args


def test_the_databroker_probe_starts_the_pinned_databroker_with_no_network_and_removes_it(gate, probe, monkeypatch, tmp_path):
    gen = gate.catalogue("vss-databroker.json")
    fake = FakeDocker()
    monkeypatch.setattr(probe, "docker", fake)
    rec = probe.databroker_probe(gen, tmp_path / "out")
    runs = fake.named("run")
    assert len(runs) == 2
    db, client = runs
    ref = "%s@%s" % (IMAGES["upstream"]["kuksa-databroker"]["repo"], IMAGES["upstream"]["kuksa-databroker"]["index_digest"])
    assert db[db.index("--name") + 1] == probe.DATABROKER_NAME and db[db.index("--network") + 1] == "none" and ref in db
    assert db[db.index(ref) + 1:] == ["--vss", "/in/vss-databroker.json", "--address", "127.0.0.1", "--port", "55555", "--insecure"]
    assert client[client.index("--network") + 1] == "container:" + probe.DATABROKER_NAME and "sha256:" + "cd" * 32 in client
    for args in runs:
        _hardened(args)
        assert not any(re.fullmatch(r"[a-z0-9._-]+/[a-z0-9._/-]+:[A-Za-z0-9_.-]+", a) for a in args), args          # no repo:tag
    assert not fake.named("pull") and not fake.named("build") and not fake.named("network")
    assert fake.calls[-1] == ["rm", "-f", probe.DATABROKER_NAME]
    staged = tmp_path / "out" / "in" / "vss-databroker.json"
    assert staged.read_bytes() == (gen / "vss-databroker.json").read_bytes()
    plan = json.loads((tmp_path / "out" / "in" / "plan.json").read_text(encoding="utf-8"))
    assert [e["path"] for e in plan] == list(probe.probe_paths())
    saved = json.loads((tmp_path / "out" / "databroker-probe.json").read_text(encoding="utf-8"))
    assert saved == rec and rec["databroker"] == ref and rec["catalogue_sha256"] == hashlib.sha256(staged.read_bytes()).hexdigest()
    assert rec["client_image"] == "sha256:" + "cd" * 32 and rec["result"]["server"]["version"] == "0.7.1"


def test_the_databroker_probe_removes_its_container_when_the_client_fails_and_never_touches_the_stacks(probe, gate, monkeypatch, tmp_path):
    fake = FakeDocker(fail_on=("--rm",))
    monkeypatch.setattr(probe, "docker", fake)
    with pytest.raises(probe.ProbeError, match="subscribe_probe.py failed"):
        probe.databroker_probe(gate.catalogue("vss-databroker.json"), tmp_path / "out")
    assert fake.calls[-1] == ["rm", "-f", probe.DATABROKER_NAME]
    names = {c[c.index("--name") + 1] for c in fake.calls if "--name" in c} | {c[-1] for c in fake.calls if c[:2] == ["rm", "-f"]}
    assert names == {probe.DATABROKER_NAME} and not probe.DATABROKER_NAME.startswith("sdv-stack-")
    assert not any(a.startswith("sdv-stack-") for c in fake.calls for a in c)


def test_the_broker_probe_runs_mosquitto_by_digest_on_an_internal_network_with_no_published_port_and_removes_both(probe, monkeypatch, tmp_path):
    fake = FakeDocker()
    monkeypatch.setattr(probe, "docker", fake)
    exchanges: List[Tuple[str, str]] = []

    def exchange(sub_topic: str, pub_topic: str, payload: str, wait_s: float) -> Dict[str, Any]:
        exchanges.append((sub_topic, pub_topic))
        return {"sub_topic": sub_topic, "pub_topic": pub_topic, "subscribed": True, "granted_qos": 1, "pub_rc": 0,
                "received": sub_topic != "#"}

    monkeypatch.setattr(probe, "exchange", exchange)
    rec = probe.broker_probe(tmp_path / "out")
    ref = probe.broker_ref(IMAGES)
    assert not fake.named("pull")          # present by its digest: nothing is pulled
    assert fake.named("network", "create") == [["network", "create", "--internal", "--label", probe.LABEL + "=broker", probe.NETWORK]]
    (run,) = fake.named("run")
    _hardened(run)
    assert run[run.index("--network") + 1] == probe.NETWORK and run[run.index("--name") + 1] == probe.BROKER_NAME and run[-1] == ref
    assert fake.calls[-2:] == [["rm", "-f", "-v", probe.BROKER_NAME], ["network", "rm", probe.NETWORK]]
    # -v both times, the stale one's removal and its own: the broker's image declares two volumes, so each of its
    # containers gets two anonymous ones, and a removal that does not name them leaves them in the store
    assert fake.named("rm") == [["rm", "-f", "-v", probe.BROKER_NAME]] * 2
    aws = [t for t in probe.AWS_TOPICS]
    assert aws == ["$aws/rules/example_rule/example-thing", "$aws/things/example-thing/shadow/name/vss/update"]
    assert exchanges[:3] == [(probe.NEUTRAL_TOPIC, probe.NEUTRAL_TOPIC)] + [(t, t) for t in aws]
    assert ("#", aws[0]) in exchanges and ("$aws/#", aws[0]) in exchanges
    assert rec["carries_exact_aws_topics"] is True and rec["image"] == ref and rec["network_internal"] is True
    assert rec["published_ports"] == [] and json.loads((tmp_path / "out" / "broker-probe.json").read_text(encoding="utf-8")) == rec
    assert not any("example.com" in json.dumps(c) or "amazonaws" in json.dumps(c) for c in fake.calls)


def test_the_broker_probe_pulls_only_by_the_pinned_digest_and_cleans_up_when_an_exchange_raises(probe, monkeypatch, tmp_path):
    fake = FakeDocker()
    fake.present = False
    monkeypatch.setattr(probe, "docker", fake)

    def exchange(*_a: Any, **_k: Any) -> Dict[str, Any]:
        raise probe.ProbeError("the subscriber never subscribed")

    monkeypatch.setattr(probe, "exchange", exchange)
    with pytest.raises(probe.ProbeError, match="is not in the image store after the pull"):
        probe.broker_probe(tmp_path / "a")
    assert fake.named("pull") == [["pull", "-q", probe.broker_ref(IMAGES)]] and not fake.named("run")
    fake.present = True
    with pytest.raises(probe.ProbeError, match="never subscribed"):
        probe.broker_probe(tmp_path / "b")
    assert fake.calls[-2:] == [["rm", "-f", "-v", probe.BROKER_NAME], ["network", "rm", probe.NETWORK]]
    # an image that answers to the reference but lists another digest, or the digest under another name, is not the pin
    ref = probe.broker_ref(IMAGES)
    assert probe.familiar(ref) == "eclipse-mosquitto@" + IMAGES["test_only"][MOSQUITTO]["index_digest"]
    assert probe.familiar("ghcr.io/a/b@sha256:x") == "ghcr.io/a/b@sha256:x" and probe.familiar("docker.io/a/b@sha256:x") == "a/b@sha256:x"
    started = (len(fake.named("run")), len(fake.named("network", "create")))
    for listed in (["eclipse-mosquitto@sha256:" + "0" * 64], ["other/eclipse-mosquitto@" + ref.split("@")[1]], []):
        fake.repo_digests = listed
        with pytest.raises(probe.ProbeError, match="is not among the image's repo digests"):
            probe.broker_probe(tmp_path / "c")
        assert (len(fake.named("run")), len(fake.named("network", "create"))) == started == (1, 1)          # nothing was started


def test_each_probe_removes_what_it_started_when_its_log_cannot_be_read_or_a_removal_fails(probe, gate, monkeypatch, tmp_path):
    """Each probe reads its container's log in its finally, before it removes the container (and the network). A read
    that raises there (`docker logs` timing out) skipped the removal, where the README says "whatever happens". The
    fake's first `logs` is the readiness wait's, its second the finally's; its first `rm` is the stale one's removal
    before anything is started, its second the finally's."""
    gen = gate.catalogue("vss-databroker.json")

    def exchange(sub_topic: str, pub_topic: str, payload: str, wait_s: float) -> Dict[str, Any]:
        return {"sub_topic": sub_topic, "pub_topic": pub_topic, "subscribed": True, "granted_qos": 1, "pub_rc": 0, "received": True}

    monkeypatch.setattr(probe, "exchange", exchange)
    fake = FakeDocker(raise_at={"logs": 2})
    monkeypatch.setattr(probe, "docker", fake)
    with pytest.raises(subprocess.TimeoutExpired):
        probe.databroker_probe(gen, tmp_path / "a")
    assert len(fake.named("logs")) == 2 and len(fake.named("run")) == 2          # it had started its container, and the client ran
    assert fake.calls[-1] == ["rm", "-f", probe.DATABROKER_NAME], "the log's read raised and the container was left"
    fake = FakeDocker(raise_at={"logs": 2})
    monkeypatch.setattr(probe, "docker", fake)
    with pytest.raises(subprocess.TimeoutExpired):
        probe.broker_probe(tmp_path / "b")
    assert len(fake.named("logs")) == 2 and len(fake.named("run")) == 1 and len(fake.named("network", "create")) == 1
    assert fake.calls[-2:] == [["rm", "-f", "-v", probe.BROKER_NAME], ["network", "rm", probe.NETWORK]], "the container and the network were left"
    # and the network goes when the container's own removal raises
    fake = FakeDocker(raise_at={"rm": 2})
    monkeypatch.setattr(probe, "docker", fake)
    with pytest.raises(subprocess.TimeoutExpired):
        probe.broker_probe(tmp_path / "c")
    assert fake.calls[-2:] == [["rm", "-f", "-v", probe.BROKER_NAME], ["network", "rm", probe.NETWORK]]
    assert (tmp_path / "c" / "mosquitto.log").is_file() and not (tmp_path / "c" / "broker-probe.json").exists()          # the log was kept, no record


def test_the_verdict_wants_the_control_and_both_exact_aws_topics(probe):
    def case(sub: str, pub: str, received: bool) -> Dict[str, Any]:
        return {"sub_topic": sub, "pub_topic": pub, "subscribed": True, "granted_qos": 1, "pub_rc": 0, "received": received}

    a, b = probe.AWS_TOPICS
    good = [case(probe.NEUTRAL_TOPIC, probe.NEUTRAL_TOPIC, True), case(a, a, True), case(b, b, True), case("#", a, False)]
    assert probe.broker_verdict(good) == {"control_ok": True, "carries_exact_aws_topics": True}
    assert probe.broker_verdict([good[0], case(a, a, True), case(b, b, False)])["carries_exact_aws_topics"] is False
    assert probe.broker_verdict([case(probe.NEUTRAL_TOPIC, probe.NEUTRAL_TOPIC, False)] + good[1:]) == {
        "control_ok": False, "carries_exact_aws_topics": False}          # a rig that cannot carry a neutral topic shows nothing
    assert probe.broker_verdict(good[:2])["carries_exact_aws_topics"] is False          # one of the two was never tried


# ====================================================================================================================
# WP2: the connector's logic. Fakes only: no SDK, no broker, no databroker, no network, no AWS call.
# ====================================================================================================================

TWIN_FROZEN = REPO / "sdv-out" / "twin" / "twin_allowlist.py"
SCHEMA_FILE = APP_DIR / "appstate.schema.json"
SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
EXAMPLE = SCHEMA["examples"][0]
THING, RULE = "example-thing", "example_rule"          # placeholders: no identifier is ever in the tree
EXCLUDED = attr.MONITOR_PREFIX[:-1]                    # the node the excluded prefix names
PROJECT = EXCLUDED.rsplit(".", 1)[0]                   # the project branch, its parent
WP2_MODULES = ("limits", "pathset", "source", "envelope", "shadowdoc", "limiter", "config", "spool", "startstamp", "topics", "uplink",
               "connector", "status")
T0_MS = 1_790_000_000_000                              # where the manual clock's wall time starts: a fixture, not a date read
IMAGE_ID = "sha256:" + "1" * 64
SCENARIO = "20990101-sigsim-43-brake"
# The service's topic strings, written out here and not taken from topics.py: the fake shadow and the checks below
# are the other side of the wire.
SHADOW_PREFIX = "$aws/things/%s/shadow/name/" % THING
TELEMETRY_TOPIC = "$aws/rules/%s/%s" % (RULE, THING)
VSS_UPDATE = SHADOW_PREFIX + "vss/update"
CONFIG_UPDATE = SHADOW_PREFIX + "config/update"
CONFIG_GET = SHADOW_PREFIX + "config/get"
CONFIG_DELTA = SHADOW_PREFIX + "config/update/delta"
LOG_EVENTS = {"start", "start-refused", "config-get", "config", "spool", "batch", "shadow", "appstate", "publish-failed",
              "connect-failed", "error", "stop", "status"}
STAMP = "started.json"                                 # the connector's other file, beside the spool record


def _fnv1_32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = (h * 0x01000193) % (1 << 32)
        h ^= b
    return h


@pytest.fixture(scope="module")
def twin() -> Any:
    """The connector's modules, imported as its image imports them: by name, from their own directory."""
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    if str(CONNECTOR_DIR) not in sys.path:
        sys.path.insert(0, str(CONNECTOR_DIR))
    try:
        mods = {name: importlib.import_module(name) for name in WP2_MODULES + ("appstate",)}
    finally:
        sys.dont_write_bytecode = saved
    for name, mod in mods.items():
        assert Path(str(mod.__file__)).resolve().parent == CONNECTOR_DIR.resolve(), (name, mod.__file__)
    return types.SimpleNamespace(**mods)


@pytest.fixture(scope="module")
def frozen(gate) -> Any:
    if not TWIN_FROZEN.is_file():
        gate.missing("needs the frozen allowlist %s: ~/sdv-venv/bin/python sdv/connector/gen_allowlist.py "
                     "(sdv/connector/README.md)" % TWIN_FROZEN)
    return _load("twin_allowlist_for_the_connector_tests", TWIN_FROZEN)


@pytest.fixture(scope="module")
def excluded_nodes(gate) -> Dict[str, Dict[str, Any]]:
    """Every leaf of the excluded branch, {path: its node with its staticUID}, enumerated from the generated catalogue
    (prep gap d: no path of that branch is written in this file)."""
    gen = gate.catalogue("vss-databroker.json", "vss-ids.vspec")
    leaves = attr.leaf_nodes(json.loads((gen / "vss-databroker.json").read_text(encoding="utf-8")))
    ids = (gen / "vss-ids.vspec").read_text(encoding="utf-8")
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(leaves):
        if not path.startswith(attr.MONITOR_PREFIX):
            continue
        m = re.search(r"^%s:\n(?:  .*\n)*?  staticUID: '(0x[0-9A-F]{8})'\n" % re.escape(path), ids, re.M)
        assert m, path
        out[path] = dict(leaves[path], uid=int(m.group(1), 16))
    assert len(out) == 22, "the excluded branch's leaves, enumerated from the catalogue, are not the 22 of today: %d" % len(out)
    return out


@pytest.fixture(scope="module")
def excluded_leaves(excluded_nodes) -> List[str]:
    return list(excluded_nodes)


def canaries_for(leaves: Sequence[str]) -> Dict[str, int]:
    """One distinctive number per leaf of the excluded branch. The fake source is untyped, so every leaf holds one
    (on the pinned databroker only the counters could: WP3's canary run)."""
    return {leaf: 3_141_592_000 + 7 * i for i, leaf in enumerate(leaves)}


def normal_values(allow: Any) -> Dict[str, Any]:
    """A normal value in every allowlisted path: the schema's example record in the AppState leaves."""
    out: Dict[str, Any] = {}
    for i, path in enumerate(allow.PATHS):
        if path in allow.APPSTATE_FIELDS:
            out[path] = EXAMPLE[allow.APPSTATE_FIELDS[path]]
        else:          # any other integer leaf (a module with a leaf forced in may hold one) gets 3
            out[path] = {"float": 1.25 * (i + 1), "boolean": True, "uint16": 2700}.get(allow.NODES[path][1], 3)
    return out


def strings_of(obj: Any) -> List[str]:
    """Every key and every string value of a parsed JSON document."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() for s in [k] + strings_of(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in strings_of(v)]
    return []


class FakeShadow:
    """The named-shadow service as we read its documentation (aws-map A3 and the shadow MQTT topics page), for one
    thing: an update merges (null removes a key, an array is replaced whole), bumps the version, is answered on
    update/accepted and, WHENEVER desired still differs from reported, on update/delta with every desired attribute
    that differs, after every accepted update, the device's own reported updates included; a get is answered on
    get/accepted, or on get/rejected (404) when the shadow does not exist. A reply reaches the device only on a topic
    it subscribed to. This is our reading, not the service: it compares top-level attributes only."""

    def __init__(self, uplink: Any) -> None:
        self.uplink = uplink
        self.docs: Dict[str, Dict[str, Any]] = {}
        self.sent: List[Tuple[str, Dict[str, Any]]] = []
        uplink.on_publish = self.on_publish

    def on_publish(self, topic: str, payload: bytes) -> None:
        if not topic.startswith(SHADOW_PREFIX):
            return
        name, _sep, op = topic[len(SHADOW_PREFIX):].partition("/")
        if op == "get":
            self._get(name)
        elif op == "update":
            self._update(name, payload)

    def _emit(self, name: str, suffix: str, doc: Dict[str, Any]) -> None:
        topic = SHADOW_PREFIX + name + "/" + suffix
        self.sent.append((topic, doc))
        assert len(self.sent) < 20000, "the fake shadow and the connector answer each other without end"
        self.uplink.deliver(topic, json.dumps(doc).encode("utf-8"))

    @staticmethod
    def _delta(doc: Dict[str, Any]) -> Dict[str, Any]:
        def same(a: Any, b: Any) -> bool:          # as JSON: true is not 1
            return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

        return {k: v for k, v in doc["desired"].items() if k not in doc["reported"] or not same(doc["reported"][k], v)}

    def _get(self, name: str) -> None:
        doc = self.docs.get(name)
        if doc is None:
            self._emit(name, "get/rejected", {"code": 404, "message": "No shadow exists with name: '%s'" % name})
            return
        state = {"desired": doc["desired"], "reported": doc["reported"]}
        if self._delta(doc):
            state["delta"] = self._delta(doc)
        self._emit(name, "get/accepted", {"state": state, "metadata": {}, "version": doc["version"], "timestamp": 1})

    def _update(self, name: str, payload: bytes) -> None:
        try:
            state = json.loads(payload)["state"]
            assert isinstance(state, dict) and set(state) <= {"desired", "reported"}
        except (ValueError, KeyError, TypeError, AssertionError):
            self._emit(name, "update/rejected", {"code": 400, "message": "Invalid JSON"})
            return
        if len(payload) > 8192:
            self._emit(name, "update/rejected", {"code": 413, "message": "The payload exceeds the maximum size allowed"})
            return
        doc = self.docs.setdefault(name, {"desired": {}, "reported": {}, "version": 0})
        for section, values in state.items():
            for k, v in values.items():
                if v is None:
                    doc[section].pop(k, None)
                else:
                    doc[section][k] = v
        doc["version"] += 1
        self._emit(name, "update/accepted", {"state": state, "version": doc["version"], "timestamp": 1})
        if self._delta(doc):
            self._emit(name, "update/delta", {"state": self._delta(doc), "metadata": {}, "version": doc["version"], "timestamp": 1})

    def cloud(self, name: str, desired: Dict[str, Any]) -> None:
        """The cloud side writes desired state."""
        self._update(name, json.dumps({"state": {"desired": desired}}).encode("utf-8"))

    def deltas(self, name: str = "config") -> List[Dict[str, Any]]:
        return [doc for topic, doc in self.sent if topic == SHADOW_PREFIX + name + "/update/delta"]


class Rig:
    """One connector on fakes: a manual clock, a fake uplink (wrapped by the entry point's builder), a fake shadow
    behind it, a fake source, a log in memory and a spool directory under the test's own."""

    def __init__(self, twin: Any, allow: Any, tmp_path: Path, values: Optional[Dict[str, Any]] = None, shadow: bool = True,
                 cls: Any = None, source: Any = None) -> None:
        self.twin, self.allow = twin, allow
        self.clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
        self.t0 = self.clock.monotonic()
        self.fake = twin.uplink.FakeUplink(clock=self.clock)
        self.topics = twin.topics.Topics(THING, RULE)
        self.shadow: Any = FakeShadow(self.fake) if shadow else None
        self.src = source if source is not None else twin.source.FakeSource(values)
        self.out = io.StringIO()
        self.audit: List[Tuple[str, List[str], bool]] = []          # what a run recorded with FileAudit, when it did
        self.planted: Dict[str, Path] = {}
        self.spool = tmp_path / "spool" / "v1"
        self.spool.mkdir(parents=True)
        self.status_dir = tmp_path / "status" / "v1"          # the updater's status record's directory: empty unless a test writes one
        self.status_dir.mkdir(parents=True)
        if cls is None:
            self.conn = twin.connector.build(self.fake, self.src, self.clock, self.topics, allow, SCHEMA, self.spool, self.out,
                                             status_dir=self.status_dir)
        else:          # a seeded variant of the connector, built as the entry point builds the real one
            self.conn = cls(twin.limiter.Limiter(self.fake, self.topics, self.clock), self.src, self.clock, self.topics, allow,
                            SCHEMA, self.spool, self.out, status_dir=self.status_dir)
        # For each publish the fake uplink took, in step with fake.published: the effective set before the step that
        # made it, and the effective set as it went. (A batch a narrowing closes was sampled under the first.)
        self.effective_at: List[Tuple[Tuple[str, ...], Tuple[str, ...]]] = []
        self._before: Tuple[str, ...] = tuple(self.conn.effective)
        taken = self.fake.publish

        def publish(topic: str, payload: bytes, qos: int = 1) -> None:
            taken(topic, payload, qos)
            self.effective_at.append((self._before, tuple(self.conn.effective)))

        self.fake.publish = publish

    def start(self) -> "Rig":
        self.conn.start()
        self._before = tuple(self.conn.effective)
        self.conn.step()
        return self

    def run(self, seconds: float, each: Optional[Callable[["Rig"], None]] = None) -> "Rig":
        """`seconds` of the manual clock in steps of 0.1 s (one tick at 10 Hz); `each` runs before every step."""
        for _ in range(int(round(seconds * 10))):
            self.clock.advance(0.1)
            if each is not None:
                each(self)
            self._before = tuple(self.conn.effective)
            self.conn.step()
        return self

    def stop(self) -> "Rig":
        self.conn.stop()
        return self

    def now(self) -> float:
        return round(self.clock.monotonic() - self.t0, 3)

    def at(self, topic: str) -> List[Any]:
        return [p for p in self.fake.published if p.topic == topic]

    def times(self, topic: str) -> List[float]:
        return [round(p.t - self.t0, 3) for p in self.at(topic)]

    def telemetry(self) -> List[Dict[str, Any]]:
        return [json.loads(p.payload) for p in self.at(TELEMETRY_TOPIC)]

    def vss(self) -> List[Dict[str, Any]]:
        return [json.loads(p.payload)["state"]["reported"] for p in self.at(VSS_UPDATE)]

    def reports(self) -> List[Dict[str, Any]]:
        return [json.loads(p.payload)["state"]["reported"] for p in self.at(CONFIG_UPDATE)]

    def log(self, event: Optional[str] = None) -> List[Dict[str, Any]]:
        lines = [json.loads(line) for line in self.out.getvalue().splitlines()]
        return [rec for rec in lines if event is None or rec["event"] == event]


class FileAudit:
    """What this process opened for writing, renamed, removed or made while recording, and everything it opened or
    listed under one directory: Python's own audit events, so nothing the connector does through os or open escapes
    it. The hook cannot be removed once added; it does nothing while not recording."""

    EVENTS = ("open", "os.rename", "os.remove", "os.mkdir", "os.rmdir", "os.truncate", "os.chmod", "os.link", "os.symlink",
              "os.listdir", "os.scandir")
    events: List[Tuple[str, Tuple[Any, ...]]] = []
    recording = False
    installed = False

    @classmethod
    def _hook(cls, event: str, args: Tuple[Any, ...]) -> None:
        if cls.recording and event in cls.EVENTS:
            cls.events.append((event, args))

    @classmethod
    def start(cls) -> None:
        if not cls.installed:
            sys.addaudithook(cls._hook)
            cls.installed = True
        cls.events = []
        cls.recording = True

    @classmethod
    def stop(cls) -> List[Tuple[str, List[str], bool]]:
        """[(event, the paths it names, whether it writes)], for the events that name a path."""
        cls.recording = False
        out = []
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        for event, args in cls.events:
            paths = [os.fsdecode(a) for a in args[:2] if isinstance(a, (str, bytes, os.PathLike))]
            if event == "open":
                paths = paths[:1]
                writes = bool(isinstance(args[2], int) and args[2] & write_flags)
            else:
                writes = event not in ("os.listdir", "os.scandir")
            if paths and not any("__pycache__" in p for p in paths):
                out.append((event, [os.path.abspath(p) for p in paths], writes))
        return out


def under(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def most_in_a_closed_window(times: Sequence[float], window_s: int = 300) -> int:
    """The most of these instants that any interval of `window_s` seconds holds, its two ends included, counted in
    whole milliseconds. The manual clock's instants are whole milliseconds and their floats are not: 2222.3 - 1922.3
    is 300.0000000000002, so a count made in floats would let a publish exactly 300 s after another fall outside."""
    ms = sorted(int(round(t * 1000)) for t in times)
    return max([len([u for u in ms if t <= u <= t + window_s * 1000]) for t in ms] or [0])


def smallest_gap_ms(times: Sequence[float]) -> int:
    """The smallest distance between two of these instants, in whole milliseconds."""
    ms = sorted(int(round(t * 1000)) for t in times)
    return min(b - a for a, b in zip(ms, ms[1:]))


class SdkError(Exception):
    """An exception class of somebody else's: what an SDK raises, and no UplinkError."""


# A text an error could carry: where the key is, where the broker is, and who the client is. No test may find a word
# of it, or a traceback, in anything the connector writes.
SECRET = "cannot read /run/sdv-local/device/device.key for broker.example.invalid:8883 (client id example-thing)"
SECRET_WORDS = ("cannot read", "/run/sdv-local", "device.key", "broker.example.invalid", "client id", "example-thing", "Traceback")


# ============================================================ limits.py

def test_wp2_every_design_value_is_in_limits_and_the_limiters_worst_case_is_the_plans(twin):
    L = twin.limits
    assert L.RATES_HZ == (1, 10) and L.DEFAULT_RATE_HZ == 1                       # gap g: 1 Hz or 10 Hz and nothing else
    assert L.BATCH_INTERVAL_S == {1: 60, 10: 10} and [L.batch_ticks(r) for r in L.RATES_HZ] == [60, 100]
    assert L.SHADOW_MIN_INTERVAL_S == 60 and L.FIRST_DOCUMENT_WAIT_S == 2.0       # gap h
    assert (L.LIMITER_WINDOW_S, L.TELEMETRY_MIN_GAP_S, L.TELEMETRY_MAX_PER_WINDOW, L.TELEMETRY_MAX_BYTES) == (300, 1.0, 60, 16384)
    assert (L.SHADOW_MAX_PER_WINDOW, L.SHADOW_MAX_BYTES) == (10, 4096)             # gap s
    assert (L.SHADOW_DOC_LIMIT_BYTES, L.SHADOW_DOC_MAX_DEPTH) == (8192, 8)         # the service's limits (aws-map A3.7)
    assert L.SPOOL_MAX_BYTES == 256 and L.START_SPACING_S == 120 and L.QOS == 1
    # gap i: three starts in a closed 300 s (at 0, 120 and 240 s), each with a limiter of its own; a stamp is 28 bytes
    assert (L.starts_per_window(), L.START_STAMP_MAX_BYTES) == (3, 64) and L.LIMITER_WINDOW_S // L.START_SPACING_S == 2
    # gap s: "Worst case in 5 minutes: 60 publishes and 983,040 bytes"
    assert L.worst_case() == {"window_s": 300, "telemetry_publishes": 60, "telemetry_bytes": 983040,
                              "shadow_publishes": 10, "shadow_bytes": 40960}
    # above normal traffic: 30 batches in 300 s at 10 Hz, one shadow document a minute
    assert max(300 // L.BATCH_INTERVAL_S[r] for r in L.RATES_HZ) == 30 < L.TELEMETRY_MAX_PER_WINDOW
    assert 300 // L.SHADOW_MIN_INTERVAL_S == 5 < L.SHADOW_MAX_PER_WINDOW
    assert L.SHADOW_MAX_BYTES < L.SHADOW_DOC_LIMIT_BYTES
    # after a shadow publish the uplink failed: the vss floor again, so that an uplink that fails every publish is asked
    # six times in a closed 300 s at the most (at 0, 60, ... 300 s), which leaves the window room for what follows
    assert L.SHADOW_RETRY_S == L.SHADOW_MIN_INTERVAL_S == 60 and L.LIMITER_WINDOW_S // L.SHADOW_RETRY_S + 1 == 6 < L.SHADOW_MAX_PER_WINDOW


# ============================================================ the plan's four (plan Phase 4 step 3)

def test_plan_1_the_allowlist_the_connector_runs_on_excludes_the_whole_excluded_branch(twin, frozen, excluded_leaves):
    """WP1 holds the list; here, the tuple the connector takes its effective set from, and what a desired list can
    make of it."""
    assert set(frozen.PATHS) == attr.ALLOWLIST_V1 and frozen.VERSION == attr.ALLOWLIST_VERSION
    assert not any(p == EXCLUDED or p.startswith(attr.MONITOR_PREFIX) for p in frozen.PATHS)
    assert not set(excluded_leaves) & set(frozen.PATHS)
    assert twin.pathset.effective(frozen.PATHS, None) == tuple(frozen.PATHS)
    assert twin.pathset.effective(frozen.PATHS, excluded_leaves + [EXCLUDED, PROJECT, attr.MONITOR_PREFIX]) == ()


def test_plan_2_appstate_goes_out_only_as_a_valid_record(twin, frozen, tmp_path):
    """Never leaf by leaf: one record per app, all of its leaves, validated; else nothing of it at all."""
    values = normal_values(frozen)
    state_leaf = [leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "state"][0]
    rig = Rig(twin, frozen, tmp_path, values).start().run(59)
    (batch,) = rig.telemetry()
    assert batch["appstate"] == [EXAMPLE] and not set(batch["paths"]) & set(frozen.APPSTATE_FIELDS)
    assert {leaf: rig.vss()[0][leaf] for leaf in frozen.APPSTATE_FIELDS} == {leaf: EXAMPLE[p] for leaf, p in frozen.APPSTATE_FIELDS.items()}
    rig.src.set(state_leaf, "exploded")          # one leaf no longer a value the schema allows: the whole record goes
    rig.run(61).stop()
    assert all(b["appstate"] == [] for b in rig.telemetry()[1:]) and len(rig.telemetry()) == 3
    assert all(rig.vss()[-1][leaf] is None for leaf in frozen.APPSTATE_FIELDS)
    assert "exploded" not in "".join(p.payload.decode("utf-8") for p in rig.fake.published) + rig.out.getvalue()


def test_plan_3_the_spool_record_has_two_fields(twin):
    S = twin.spool
    rec = S.record(IMAGE_ID, None)
    assert rec == {"image_id": IMAGE_ID, "scenario": None} and list(rec) == ["image_id", "scenario"] == list(S.FIELDS)
    assert json.loads(S.encode(S.record(None, SCENARIO))) == {"image_id": None, "scenario": SCENARIO}
    assert S.problems(dict(rec, force=True)) and S.problems({"image_id": IMAGE_ID}) and S.problems({})
    with pytest.raises(S.SpoolRefused):
        S.encode(dict(rec, force=True))


# ============================================================ A4: narrowing

def hostile_entries(allow: Any, excluded: Sequence[str]) -> List[Any]:
    """Desired path entries that are no exact member of the frozen tuple (design A4's list)."""
    some = allow.PATHS[1]
    out: List[Any] = list(excluded)                                                             # every leaf of the excluded branch
    out += [EXCLUDED, PROJECT, "Vehicle", attr.APPSTATE_PREFIX[:-1]] + list(allow.APPSTATE_BRANCHES)      # branches
    out += ["*", "#", "+", "?", "**", "Vehicle.*", "Vehicle.#", "Vehicle/+", PROJECT + ".*", EXCLUDED + ".#", attr.MONITOR_PREFIX + "+"]
    out += [some[:-1], some + "X", attr.MONITOR_PREFIX, PROJECT + ".", excluded[0][:-1]]        # prefixes and near misses
    out += [some.lower(), some.upper(), some.swapcase(), excluded[0].lower(), excluded[0].upper()]      # case variants
    out += [some + ".", "." + some, some + ".."]                                                # trailing and leading dots
    out += [" " + some, some + " ", "\t" + some, some + "\n", some + "\r\n", "\u00a0" + some, some + "\u200b",
            " " + excluded[0] + " "]                                                            # surrounding whitespace
    out += [some.replace("V", "\uff36", 1), some.replace("e", "\u0435", 1), some.replace(".", "\uff0e"),
            excluded[0].replace("V", "\uff36", 1)]                                              # full-width and other look-alikes
    out += [PROJECT + ".ControlCommand.Velocity", PROJECT + ".ControlCommand"]                  # Phase 8's branch
    out += [None, 7, True, 1.5, [some], {"path": some}]                                         # not strings at all
    return out


def narrowing_findings(narrow: Callable[[Sequence[str], Any], Sequence[str]], allow: Any, hostile: Sequence[Any]) -> List[str]:
    """Why `narrow` is not narrowing by exact membership: [] when it is (design A4)."""
    out: List[str] = []
    full = tuple(allow.PATHS)
    for entry in hostile:
        got = tuple(narrow(full, [entry]))
        if got != ():
            out.append("%r alone gives %r" % (entry, got))
    keep = (full[1], full[5])
    mixed = tuple(narrow(full, list(hostile[:9]) + [keep[1]] + list(hostile[9:]) + [keep[0], keep[0]]))
    if mixed != keep:
        out.append("the hostile list with two members gives %r" % (mixed,))
    if tuple(narrow(full, None)) != full:
        out.append("no list is not the whole tuple")
    if tuple(narrow(full, [])) != ():
        out.append("an empty list is not the empty set")
    if tuple(narrow(full, list(reversed(full)))) != full:
        out.append("the effective set is not in the frozen tuple's order")
    if not set(mixed) <= set(full):
        out.append("the effective set is no subset of the frozen tuple")
    return out


def test_a4_narrowing_is_exact_case_sensitive_membership_in_the_frozen_tuple(twin, frozen, excluded_leaves):
    hostile = hostile_entries(frozen, excluded_leaves)
    assert len(hostile) > 60 and all(e not in frozen.PATHS for e in hostile if isinstance(e, str))
    assert narrowing_findings(twin.pathset.effective, frozen, hostile) == []
    # a full-width look-alike is one normalisation away from a member, which is why nothing is normalised
    import unicodedata
    wide = frozen.PATHS[1].replace("V", "\uff36", 1)
    assert unicodedata.normalize("NFKC", wide) == frozen.PATHS[1] and twin.pathset.effective(frozen.PATHS, [wide]) == ()
    # the count of what was ignored, never the strings
    effective, ignored = twin.pathset.narrow(frozen.PATHS, hostile + [frozen.PATHS[0]])
    assert effective == (frozen.PATHS[0],) and ignored == len(hostile)
    for whole in ("*", frozen.PATHS[0], {"paths": []}, 7, True):          # a value that is no list is no narrowing at all
        with pytest.raises(TypeError):
            twin.pathset.narrow(frozen.PATHS, whole)


def test_a4_seeded_a_narrowing_that_lower_cases_or_strips_its_input_fails_the_check(frozen, excluded_leaves):
    hostile = hostile_entries(frozen, excluded_leaves)
    some = frozen.PATHS[1]

    def lowercasing(paths, desired):
        if desired is None:
            return tuple(paths)
        want = {d.lower() for d in desired if isinstance(d, str)}
        return tuple(p for p in paths if p.lower() in want)

    def stripping(paths, desired):
        if desired is None:
            return tuple(paths)
        want = {d.strip() for d in desired if isinstance(d, str)}
        return tuple(p for p in paths if p in want)

    low = narrowing_findings(lowercasing, frozen, hostile)
    assert [f for f in low if f.startswith("%r alone" % some.lower())] and [f for f in low if f.startswith("%r alone" % some.upper())]
    stripped = narrowing_findings(stripping, frozen, hostile)
    assert [f for f in stripped if f.startswith("%r alone" % (" " + some))] and [f for f in stripped if f.startswith("%r alone" % (some + "\n"))]


def test_a4_at_the_connector_a_hostile_desired_list_narrows_to_its_exact_members_and_reported_echoes_no_rejected_string(
        twin, frozen, excluded_leaves, tmp_path):
    hostile = hostile_entries(frozen, excluded_leaves)
    keep = (frozen.PATHS[0], frozen.PATHS[1])
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    rig.shadow.cloud("config", {"paths": hostile + [keep[1], keep[0]]})          # written while the connector was down
    rig.start().run(5)
    assert rig.conn.effective == keep and rig.src.calls[-1] == keep
    rig.shadow.cloud("config", {"paths": hostile})                               # nothing but rejected entries: the empty set
    rig.run(5)
    assert rig.conn.effective == () and rig.src.calls[-1] == ()
    rig.shadow.cloud("config", {"paths": "*"})                                   # no list: refused whole, nothing changes
    rig.run(5).stop()
    assert rig.conn.effective == ()
    assert rig.reports() == [{"rate_hz": 1, "paths": list(keep)}, {"rate_hz": 1, "paths": []}]
    # no rejected string anywhere on the wire or in the local log, escaped or not
    distinct = [e for e in hostile if isinstance(e, str) and len(e) > 3 and not any(e in p for p in frozen.PATHS)]
    assert len(distinct) > 45
    sent = [s for p in rig.fake.published if p.payload for s in strings_of(json.loads(p.payload))]
    sent += [p.topic for p in rig.fake.published] + [s for rec in rig.log() for s in strings_of(rec)]
    raw = "".join(p.payload.decode("utf-8") for p in rig.fake.published) + rig.out.getvalue()
    for entry in distinct:
        assert not any(entry in s for s in sent) and entry not in raw, entry
    assert all(set(s) <= set(frozen.PATHS) for s in rig.src.calls)


# ============================================================ A5: the subscribe call

def subscribe_findings(calls: Sequence[Sequence[str]], effective_sets: Sequence[Sequence[str]], allow: Any) -> List[str]:
    """Why these subscribe calls are not "exactly the effective set, each an exact leaf" (design A5): [] when they are."""
    out: List[str] = []
    if [tuple(c) for c in calls] != [tuple(e) for e in effective_sets]:
        out.append("the subscribe calls are not the effective sets, one call per set")
    for call in calls:
        extra = [p for p in call if p not in allow.PATHS]
        if extra:
            out.append("a subscribe call names %d path(s) that are no allowlisted leaf" % len(extra))
        if len(set(call)) != len(call):
            out.append("a subscribe call names a path twice")
    return out


def test_a5_the_subscribe_call_names_exactly_the_effective_set_each_an_exact_leaf(twin, frozen, excluded_leaves, tmp_path):
    narrowed = (frozen.PATHS[2], frozen.PATHS[6], frozen.PATHS[7])
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(3)
    assert rig.src.calls == [tuple(frozen.PATHS)]                                 # one call, the whole allowlist, nothing else
    rig.shadow.cloud("config", {"paths": [narrowed[2], narrowed[0], EXCLUDED, PROJECT, excluded_leaves[0], narrowed[1]]})
    rig.run(3)
    rig.shadow.cloud("config", {"rate_hz": 10})                                   # a rate change is no new subscription
    rig.run(3).stop()
    assert rig.src.calls == [tuple(frozen.PATHS), narrowed] and rig.conn.effective == narrowed
    assert subscribe_findings(rig.src.calls, [frozen.PATHS, narrowed], frozen) == []
    assert rig.src.handed == set(frozen.PATHS) and rig.src.closed == 1


def branch_subscriber(twin: Any) -> Any:
    """The seeded variant of designs A5 and A6: a connector that subscribes to the project branch."""

    class ByBranch(twin.connector.Connector):
        def _subscription(self):
            return (PROJECT,)

    return ByBranch


def test_a5_seeded_a_connector_that_subscribes_to_the_project_branch_fails_the_check(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen), cls=branch_subscriber(twin)).start().run(3).stop()
    assert rig.src.calls[0] == (PROJECT,)
    found = subscribe_findings(rig.src.calls, [frozen.PATHS], frozen)
    assert "the subscribe calls are not the effective sets, one call per set" in found
    assert "a subscribe call names 1 path(s) that are no allowlisted leaf" in found


class _Value:
    """A kuksa.val.v2 Value as far as the source reads it: at most one typed field set."""

    def __init__(self, field: Optional[str], value: Any) -> None:
        self._field = field
        if field is not None:
            setattr(self, field, value)

    def ListFields(self) -> List[Tuple[Any, Any]]:
        return [] if self._field is None else [(types.SimpleNamespace(name=self._field), getattr(self, self._field))]


def _dp(field: Optional[str] = None, value: Any = None) -> Any:
    return types.SimpleNamespace(value=_Value(field, value))


class _Call:
    """One Subscribe call: scripted responses, then it ends, fails, or blocks until it is cancelled."""

    def __init__(self, responses: Sequence[Dict[str, Any]], then: str) -> None:
        self.responses, self.then = list(responses), then
        self.cancelled = threading.Event()

    def __iter__(self) -> Any:
        for entries in self.responses:
            yield types.SimpleNamespace(entries=entries)
        if self.then == "fail":
            raise RuntimeError("UNAVAILABLE: failed to connect to all addresses; last error: ipv4:127.0.0.1:55555")
        if self.then == "block":
            self.cancelled.wait(20)
            raise RuntimeError("CANCELLED: locally cancelled by application")

    def cancel(self) -> None:
        self.cancelled.set()


class _Grpc:
    """grpc and kuksa.val.v2's two generated modules, as far as GrpcStream uses them."""

    def __init__(self, calls: Sequence[_Call]) -> None:
        self.calls = list(calls)
        self.requests: List[Any] = []
        self.opened = threading.Event()
        self.channels: List[Any] = []
        outer = self

        class Stub:
            def __init__(self, channel: Any) -> None:
                self.channel = channel

            def Subscribe(self, request: Any, wait_for_ready: Any = None) -> _Call:
                outer.requests.append((request, wait_for_ready))
                outer.opened.set()
                return outer.calls.pop(0) if outer.calls else _Call([], "block")

        self.grpc = types.SimpleNamespace(insecure_channel=self._channel)
        self.val = types.SimpleNamespace(SubscribeRequest=lambda **kw: types.SimpleNamespace(**kw))
        self.stubs = types.SimpleNamespace(VALStub=Stub)

    def _channel(self, target: str) -> Any:
        channel = types.SimpleNamespace(target=target, closed=False)
        channel.close = lambda: setattr(channel, "closed", True)
        self.channels.append(channel)
        return channel

    def modules(self) -> Tuple[Any, Any, Any]:
        return (self.grpc, self.val, self.stubs)


def _wait(what: Callable[[], bool], seconds: float = 10.0) -> bool:
    """Wait on the kuksa source's own thread; a bound on the test, not a timing."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if what():
            return True
        time.sleep(0.002)
    return what()


def test_a5_the_request_the_databroker_is_sent_names_exactly_the_effective_leaves(twin, frozen, excluded_leaves, tmp_path):
    """The same through the real kuksa source and a fake of the generated gRPC modules: what would go on the wire."""
    first_call = _Call([{p: _dp("float", 2.5) for p in frozen.PATHS[:3]}], "block")
    rpc = _Grpc([first_call])
    stream = twin.source.GrpcStream("127.0.0.1:55555", modules=rpc.modules())
    src = twin.source.KuksaSource(stream, sleep=lambda s: None)
    rig = Rig(twin, frozen, tmp_path, source=src).start()
    assert rpc.opened.wait(10) and [c.target for c in rpc.channels] == ["127.0.0.1:55555"]
    (request, wait_for_ready) = rpc.requests[0]
    assert request.signal_paths == list(frozen.PATHS) and request.buffer_size == twin.limits.SUBSCRIBE_BUFFER == 100
    assert wait_for_ready is True and vars(request).keys() == {"signal_paths", "buffer_size"}
    assert _wait(lambda: len(src.latest()) == 3)
    narrowed = (frozen.PATHS[4], frozen.PATHS[1])
    rpc.opened.clear()
    rig.shadow.cloud("config", {"paths": list(narrowed) + [EXCLUDED, excluded_leaves[3]]})
    rig.run(1)
    assert rpc.opened.wait(10) and first_call.cancelled.is_set()                  # the old stream is cancelled, not left open
    assert [r.signal_paths for r, _w in rpc.requests] == [list(frozen.PATHS), [frozen.PATHS[1], frozen.PATHS[4]]]
    # a path that is still asked for keeps its latest value while the new stream opens; the others' values are gone
    assert src.latest() == {frozen.PATHS[1]: 2.5}
    rig.stop()
    assert rpc.channels[0].closed and _wait(lambda: not src.alive())


def test_the_kuksa_source_keeps_the_latest_value_of_each_subscribed_leaf_and_retries_a_stream_that_ends(twin):
    a, b, c, other = "Vehicle.A", "Vehicle.B", "Vehicle.C", "Vehicle.NotAsked"
    first = _Call([{a: _dp("float", 1.5), b: _dp("bool", True), c: _dp(), other: _dp("uint32", 9)}, {a: _dp("float", 2.0)}], "fail")
    second = _Call([{a: _dp("float", 2.5), c: _dp("string", "running")}], "end")
    third = _Call([{b: _dp("bool", False), other: _dp("uint32", 9), a + ".Deeper": _dp("float", 1.0)}], "block")
    rpc = _Grpc([first, second, third])
    sleeps: List[float] = []
    src = twin.source.KuksaSource(twin.source.GrpcStream("127.0.0.1:55555", modules=rpc.modules()), sleep=sleeps.append)
    assert src.latest() == {}
    src.subscribe([a, b, c])
    assert _wait(lambda: len(rpc.requests) == 3 and b in src.latest())
    assert src.latest() == {b: False}          # the live stream also sent a path nobody asked for, and one under an asked path
    # a stream that failed or ended is opened again after the retry interval, with the same exact paths, and what the
    # dead stream had delivered is not kept: the next stream's first response carries the current values
    assert sleeps == [twin.limits.SOURCE_RETRY_S, twin.limits.SOURCE_RETRY_S] == [1.0, 1.0]
    assert [r.signal_paths for r, _w in rpc.requests] == [[a, b, c]] * 3
    assert src.counters == {"opened": 3, "responses": 4, "failed": 1, "ended": 1} and src.last_error == "RuntimeError"
    src.subscribe([])                                                            # an empty effective set opens no stream
    assert third.cancelled.is_set() and _wait(lambda: not src.alive()) and len(rpc.requests) == 3 and src.latest() == {}
    src.close()
    assert rpc.channels[0].closed
    # value_of: the one field a datapoint carries, or None
    assert twin.source.value_of(_dp("int32", -3)) == -3 and twin.source.value_of(_dp()) is None
    assert twin.source.value_of(_dp("string", "")) == "" and twin.source.value_of(_dp("bool", False)) is False


def test_the_fake_source_serves_a_branch_as_a_databroker_would_and_records_what_it_handed_over(twin):
    """A test of the tests' own fake: it can fail only on FakeSource, and shows nothing about a databroker. It is here
    because A5 and A6 rest on what the fake hands over for a branch and on what it records as handed over."""
    src = twin.source.FakeSource({"Vehicle.A.X": 1, "Vehicle.A.Y": None, "Vehicle.B": 2, "Vehicle.AB": 3},
                                 script=lambda n: {"Vehicle.B": 10 + n})
    assert src.latest() == {} and src.handed == set()
    src.subscribe(["Vehicle.A"])                                                 # a branch: every leaf under it, as the worst case
    assert src.latest() == {"Vehicle.A.X": 1} and src.handed == {"Vehicle.A.X"}
    src.subscribe(["Vehicle.B", "Vehicle.NoSuch"])
    assert src.latest() == {"Vehicle.B": 13} and src.latest() == {"Vehicle.B": 14}          # the script runs before each read
    assert src.reads == 4
    src.set("Vehicle.A.Y", "y")
    src.subscribe(("Vehicle.A.Y",))
    assert src.latest() == {"Vehicle.A.Y": "y"}
    assert src.calls == [("Vehicle.A",), ("Vehicle.B", "Vehicle.NoSuch"), ("Vehicle.A.Y",)]
    assert src.handed == {"Vehicle.A.X", "Vehicle.B", "Vehicle.A.Y"}
    src.close()
    assert src.closed == 1 and src.latest() == {}


# ============================================================ A6: the exclusion proof, at the egress

def plant(tmp_path: Path) -> Dict[str, Path]:
    """Canary strings where the QNX monitor's output lives on a real host: a console log, a record directory, a lock
    file. The connector has no path to any of them; A6 checks that it shows."""
    files = {"CANARY-console-5d1f0c": tmp_path / "console" / "qnx-console.log",
             "CANARY-record-91be27": tmp_path / "records" / "20990101T-run" / "bridge.jsonl",
             "CANARY-lock-c40a66": tmp_path / "lock" / "scenario.lock"}
    for canary, path in files.items():
        path.parent.mkdir(parents=True)
        path.write_text("monitor: REJECT seq=7 reason=21 %s\n" % canary, encoding="utf-8")
    return files


def egress_run(twin: Any, module: Any, allow: Any, excluded: Sequence[str], tmp_path: Path, cls: Any = None,
               short: bool = False) -> Tuple[Rig, List[str]]:
    """One whole life of a connector given `module` as its frozen allowlist: a hostile config waiting for it, values
    that change, a narrowing, the other rate, the full set again, a stop. Every leaf of the excluded branch holds a
    canary in the source, and canary strings lie in files beside the spool. Returns the rig and every canary's text."""
    canaries = canaries_for(excluded)
    planted = plant(tmp_path)
    values = dict(normal_values(allow), **canaries)
    seq_leaf = [leaf for leaf, prop in allow.APPSTATE_FIELDS.items() if prop == "seq"][0]
    floats = [p for p in allow.PATHS if allow.NODES[p][1] == "float"]

    def moving(n: int) -> Dict[str, Any]:
        return dict({p: 0.5 * n + i for i, p in enumerate(floats)}, **{seq_leaf: 42 + n})

    rig = Rig(twin, module, tmp_path, cls=cls, source=twin.source.FakeSource(values, script=moving))
    hostile = list(excluded) + [EXCLUDED, PROJECT, "*", "#", "+", attr.MONITOR_PREFIX + "#"]
    rig.shadow.cloud("config", {"paths": list(module.PATHS) + hostile, "rate_hz": 1, "image_id": IMAGE_ID, "scenario": SCENARIO,
                                "monitor": excluded[0]})
    FileAudit.start()
    try:
        rig.start().run(15 if short else 65)
        narrowed = [p for p in module.PATHS if p not in (allow.PATHS[3], allow.PATHS[6])]
        rig.shadow.cloud("config", {"paths": narrowed + hostile, "rate_hz": 10})
        rig.run(12 if short else 25)
        rig.shadow.cloud("config", {"paths": list(module.PATHS) + hostile, "rate_hz": 1})
        rig.run(5 if short else 65).stop()
    finally:
        rig.audit = FileAudit.stop()
    rig.planted = planted
    return rig, [str(c) for c in canaries.values()] + list(planted)


def egress_findings(rig: Any, canaries: Sequence[str]) -> List[str]:
    """Why this run's egress is not clean (design A6): [] when it is. Every publish is held to two sets. The allowlist
    is the design's set as the stack's attribution has it (WP1 holds the source list equal to it), not the frozen
    module the connector under test was given: that module is what a seeded case tampers with. The effective set is
    the one in force when the publish was made (Rig.effective_at): a batch's columns are the telemetry paths of the
    set it was sampled under, a record goes only when every AppState leaf is in that set, a vss document holds a
    value only for a path of the set, and a config report names exactly the set."""
    out: List[str] = []
    allowed, fields, low = set(attr.ALLOWLIST_V1), set(SCHEMA["properties"]), EXCLUDED.lower()
    assert len(rig.effective_at) == len(rig.fake.published)
    for n, p in enumerate(rig.fake.published):
        where = "publish %d" % n
        before, now = rig.effective_at[n]
        text = p.payload.decode("utf-8", errors="replace")
        doc: Any = None
        if p.topic == CONFIG_GET:          # a get carries nothing: whatever it does carry is looked at below, not parsed
            if text:
                out.append("%s: a get with a payload" % where)
        else:
            try:
                doc = json.loads(text)
            except ValueError:
                out.append("%s: a payload that is not JSON" % where)
            if doc is not None and not isinstance(doc, dict):
                out.append("%s: a payload that is not a JSON object" % where)
        named = [p.topic, text] + strings_of(doc)
        if p.topic not in (TELEMETRY_TOPIC, VSS_UPDATE, CONFIG_UPDATE, CONFIG_GET):
            out.append("%s goes to a topic that is not one of the connector's four" % where)
        if any(low in s.lower() for s in named):
            out.append("%s names the excluded branch" % where)
        if any(c in s for c in canaries for s in named):
            out.append("%s carries a canary" % where)
        if not isinstance(doc, dict):
            continue
        if p.topic == TELEMETRY_TOPIC:
            if list(doc) != list(rig.twin.envelope.FIELDS) or not set(doc["paths"]) <= allowed:
                out.append("%s: a batch whose keys are not the envelope's fixed fields and allowlisted paths" % where)
            columns = [list(rig.twin.envelope.telemetry_paths(rig.allow, e)) for e in (before, now)]
            if doc["paths"] not in columns:
                out.append("%s: a batch whose columns are not the telemetry paths of the effective set" % where)
            if any(len(row) != 1 + len(doc["paths"]) for row in doc["rows"]):
                out.append("%s: a row that is not as long as its header" % where)
            if any(not set(rec) <= fields or rig.twin.appstate.validate(SCHEMA, rec) for rec in doc["appstate"]):
                out.append("%s: an AppState record that does not validate" % where)
            if doc["appstate"] and not any(set(rig.allow.APPSTATE_FIELDS) <= set(e) for e in (before, now)):
                out.append("%s: an AppState record though a leaf of it is outside the effective set" % where)
        else:
            reported = doc.get("state", {}).get("reported")
            if set(doc) != {"state"} or set(doc["state"]) != {"reported"} or not isinstance(reported, dict):
                out.append("%s: a shadow update that is not reported state alone" % where)
            elif p.topic == VSS_UPDATE and not set(reported) <= allowed:
                out.append("%s: a vss document with a key outside the allowlist" % where)
            elif p.topic == VSS_UPDATE and not {k for k, v in reported.items() if v is not None} <= set(now):
                out.append("%s: a vss document with a value for a path outside the effective set" % where)
            elif p.topic == CONFIG_UPDATE and (set(reported) != {"rate_hz", "paths"} or not set(reported["paths"]) <= allowed):
                out.append("%s: a config report that is not the effective rate and path set" % where)
            elif p.topic == CONFIG_UPDATE and reported["paths"] != list(now):
                out.append("%s: a config report whose paths are not the effective set" % where)
    outside = sorted(rig.src.handed - allowed)
    if outside:
        out.append("the source handed the connector %d leaf value(s) outside the allowlist, %d of them of the excluded branch"
                   % (len(outside), len([p for p in outside if p.startswith(attr.MONITOR_PREFIX)])))
    for call in rig.src.calls:
        if not set(call) <= allowed:
            out.append("a subscribe call names a path that is no allowlisted leaf")
    touched = [(e, paths) for e, paths, _w in rig.audit if any(under(p, f.parent) for p in paths for f in rig.planted.values())]
    if touched:
        out.append("the connector touched %d path(s) beside its spool" % len(touched))
    stray = [(e, paths) for e, paths, writes in rig.audit if writes and not all(under(p, rig.spool) for p in paths)]
    if stray:
        out.append("the connector wrote outside its spool: %r" % (stray[:3],))
    return out


def test_a6_no_publish_names_the_excluded_branch_or_carries_a_canary(twin, frozen, excluded_leaves, tmp_path):
    rig, canaries = egress_run(twin, frozen, frozen, excluded_leaves, tmp_path)
    found = egress_findings(rig, canaries)
    assert found == [], "%d finding(s), of these kinds: %s" % (len(found), sorted({re.sub(r"^publish \d+", "a publish", f) for f in found}))
    # not clean by being empty: the canaries were there to be read, and every channel carried something
    assert all(rig.src.values[leaf] == int(c) for leaf, c in zip(excluded_leaves, canaries)) and len(canaries) == 22 + 3
    assert all(c in f.read_text(encoding="utf-8") for c, f in rig.planted.items())
    batches, docs, reports = rig.telemetry(), rig.vss(), rig.reports()
    assert len(batches) >= 5 and sum(len(b["rows"]) for b in batches) > 300 and any(b["appstate"] for b in batches)
    assert len(docs) >= 3 and all(set(d) == set(frozen.PATHS) for d in docs) and len(reports) == 3
    assert rig.src.handed == set(frozen.PATHS) and rig.src.reads > 300
    assert len(rig.at(CONFIG_GET)) == 1 and len(rig.shadow.deltas()) >= 3
    # the only files it wrote are its start stamp and the spool record, each by write-then-rename; the only one it
    # read is the stamp (absent at this first start), and it listed nothing
    assert sorted(p.name for p in rig.spool.iterdir()) == ["desired.json", STAMP]
    assert json.loads((rig.spool / "desired.json").read_text(encoding="utf-8")) == {"image_id": IMAGE_ID, "scenario": SCENARIO}
    assert json.loads((rig.spool / STAMP).read_text(encoding="utf-8")) == {"started_ms": T0_MS}
    assert [(e, [Path(p).name for p in paths]) for e, paths, writes in rig.audit if writes] == [
        ("open", [".started.json.tmp"]), ("os.rename", [".started.json.tmp", STAMP]),
        ("open", [".desired.json.tmp"]), ("os.rename", [".desired.json.tmp", "desired.json"])]
    assert [(e, [Path(p).name for p in paths]) for e, paths, writes in rig.audit
            if not writes and all(under(p, rig.spool) for p in paths)] == [("open", [STAMP])]


def test_a6_seeded_a_connector_that_subscribes_by_branch_fails_it(twin, frozen, excluded_leaves, tmp_path):
    rig, canaries = egress_run(twin, frozen, frozen, excluded_leaves, tmp_path, cls=branch_subscriber(twin), short=True)
    found = egress_findings(rig, canaries)
    assert "the source handed the connector 22 leaf value(s) outside the allowlist, 22 of them of the excluded branch" in found
    assert "a subscribe call names a path that is no allowlisted leaf" in found


def forced_module(tmp: Path, leaf: str, node: Dict[str, Any], tag: str) -> Any:
    """The frozen module with one leaf of the excluded branch forced in past the generator, by a careful hand: the path,
    its staticUID, its node, its channels and the digest over all seventeen, so the module's own import check passes."""
    text = TWIN_FROZEN.read_text(encoding="utf-8")
    uids = [int(x, 16) for x in re.findall(r"^    (0x[0-9A-F]{8}),$", text, re.M)]
    assert len(uids) == 16
    digest = _fnv1_32(struct.pack("<17I", node["uid"], *uids))
    for old, new in (("PATHS = (\n", "PATHS = (\n    %r,\n" % leaf),
                     ("STATIC_UIDS = (\n", "STATIC_UIDS = (\n    0x%08X,\n" % node["uid"]),
                     ("NODES = {\n", "NODES = {\n    %r: (%r, %r, %r),\n" % (leaf, node["type"], node["datatype"], node.get("unit"))),
                     ("CHANNELS = {\n", "CHANNELS = {\n    %r: ('S', 'T'),\n" % leaf)):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    text, n = re.subn(r"^DIGEST = 0x[0-9A-F]{8}$", "DIGEST = 0x%08X" % digest, text, flags=re.M)
    assert n == 1
    path = tmp / ("forced-%s" % tag) / "twin_allowlist.py"
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return _load("twin_allowlist_forced_%s" % tag, path)


def test_a6_seeded_a_frozen_module_with_one_excluded_leaf_forced_in_fails_it_for_every_such_leaf(twin, frozen, excluded_nodes, tmp_path):
    """Past the generator, the connector has no second list: whatever the frozen module names goes out. That is why
    the module is generated, checked against a fresh generation at the image build (WP3), and never mounted."""
    excluded = list(excluded_nodes)
    counters = 0
    for i, (leaf, node) in enumerate(excluded_nodes.items()):
        module = forced_module(tmp_path, leaf, node, str(i))
        assert leaf in module.PATHS and len(module.PATHS) == 17
        rig, canaries = egress_run(twin, module, frozen, excluded, tmp_path / ("run-%d" % i), short=True)
        found = egress_findings(rig, canaries)
        assert any(f.endswith("names the excluded branch") for f in found), leaf
        assert any("a key outside the allowlist" in f for f in found) and any("not the envelope's fixed fields" in f for f in found), leaf
        if node["datatype"] in ("uint32", "uint64"):          # a leaf that can hold the canary: its value reaches the fake uplink
            counters += 1
            assert any(f.endswith("carries a canary") for f in found), leaf
            assert any(str(canaries_for(excluded)[leaf]) in p.payload.decode("utf-8") for p in rig.at(TELEMETRY_TOPIC)), leaf
    assert counters == 16          # eight counters in each of the two claim sub-branches


def test_a6_a_source_that_hands_over_more_than_it_was_asked_for_puts_nothing_more_on_the_wire(twin, frozen, excluded_leaves, tmp_path):
    """The second layer alone. The first (the subscription) is taken away: this source hands over whatever it holds,
    asked for or not, as a databroker with a fault would. The connector keeps the values of its effective set and
    nothing else, so no canary goes out, and a leaf that was narrowed out completes no AppState record and fills no
    key though the source still delivers it."""

    class Deaf(twin.source.FakeSource):
        def latest(self) -> Dict[str, Any]:
            self.reads += 1
            out = {path: value for path, value in self.values.items() if value is not None}
            self.handed |= set(out)
            return out

    canaries = canaries_for(excluded_leaves)
    seq_leaf = [leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "seq"][0]
    gone = (frozen.PATHS[1], seq_leaf)
    rig = Rig(twin, frozen, tmp_path, source=Deaf(dict(normal_values(frozen), **canaries)))
    rig.shadow.cloud("config", {"paths": [p for p in frozen.PATHS if p not in gone]})
    rig.start().run(61).stop()
    assert rig.src.calls == [tuple(p for p in frozen.PATHS if p not in gone)]      # it asked for the effective set only
    assert rig.src.handed == set(frozen.PATHS) | set(excluded_leaves)             # and was handed everything all the same
    found = egress_findings(rig, [str(c) for c in canaries.values()])
    assert found == ["the source handed the connector 22 leaf value(s) outside the allowlist, 22 of them of the excluded branch"]
    batches, docs = rig.telemetry(), rig.vss()
    assert [len(b["rows"]) for b in batches] == [60, 2] and len(docs) == 2
    assert all(b["appstate"] == [] and frozen.PATHS[1] not in b["paths"] for b in batches)          # seven leaves are no record
    assert all(doc[leaf] is None for doc in docs for leaf in list(frozen.APPSTATE_FIELDS) + [frozen.PATHS[1]])
    assert all(doc[frozen.PATHS[0]] == 1.25 for doc in docs) and rig.conn.counters["appstate_dropped"] == 62 + 1


# ============================================================ AppState

def test_appstate_is_all_eight_leaves_or_none_a_narrowed_out_leaf_drops_the_record(twin, frozen, tmp_path):
    seq_leaf = [leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "seq"][0]
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(62)
    assert rig.telemetry()[0]["appstate"] == [EXAMPLE] and rig.conn.counters["appstate_dropped"] == 0
    rig.shadow.cloud("config", {"paths": [p for p in frozen.PATHS if p != seq_leaf]})          # seven of the eight remain
    rig.run(60).stop()
    first, closed_by_narrowing, *later = rig.telemetry()
    assert closed_by_narrowing["appstate"] == [EXAMPLE]                           # valid until the narrowing
    assert later and all(b["appstate"] == [] for b in later)                       # seven leaves are no record
    assert not any(set(b["paths"]) & set(frozen.APPSTATE_FIELDS) for b in rig.telemetry())      # and never rows
    last = rig.vss()[-1]
    assert [last[leaf] for leaf in frozen.APPSTATE_FIELDS] == [None] * 8          # all eight null, not seven values
    assert rig.conn.counters["appstate_dropped"] >= 59
    dropped = [rec for rec in rig.log("appstate") if rec["ok"] is False]
    assert len(dropped) == 1 and dropped[0]["reasons"] == ["missing seq"]          # logged once, on the change, not every tick


@pytest.mark.parametrize("prop, value, reason", [
    ("state", "exploded", "enum state"),
    ("schema_version", 2, "const schema_version"),
    ("app", "other-app", "app does not derive the sub-branch the record came from"),
    ("image_id", "hard-brake-hazard:latest", "pattern image_id"),
    ("seq", 0, "range seq"),
    ("hazard_requested", "CANARY-verdict", "type hazard_requested"),
])
def test_an_invalid_appstate_record_is_dropped_and_counted_and_its_value_is_never_logged(twin, frozen, tmp_path, prop, value, reason):
    leaf = [leaf for leaf, p in frozen.APPSTATE_FIELDS.items() if p == prop][0]
    values = dict(normal_values(frozen), **{leaf: value})
    rig = Rig(twin, frozen, tmp_path, values).start().run(59).stop()
    assert [b["appstate"] for b in rig.telemetry()] == [[]]
    assert all(doc[leaf_] is None for doc in rig.vss() for leaf_ in frozen.APPSTATE_FIELDS)
    assert rig.conn.counters["appstate_dropped"] == 60 + 1                         # every tick, and the read at stop
    (rec,) = rig.log("appstate")
    assert rec["ok"] is False and rec["reasons"] == [reason]
    if isinstance(value, str):
        assert value not in rig.out.getvalue() + "".join(p.payload.decode("utf-8") for p in rig.fake.published)


def test_seq_alone_drives_no_shadow_update(twin, frozen, tmp_path):
    seq_leaf = [leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "seq"][0]
    state_leaf = [leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "state"][0]
    beat = [42]

    def heartbeat(rig):
        if abs(rig.now() - round(rig.now())) < 1e-9:
            beat[0] += 1
            rig.src.set(seq_leaf, beat[0])

    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(200, each=heartbeat)
    assert rig.times(VSS_UPDATE) == [0.0] and beat[0] == 242                       # 200 heartbeats, no document after the first
    assert [b["appstate"][0]["seq"] for b in rig.telemetry()] == [42 + 59, 42 + 119, 42 + 179]      # telemetry carries it
    rig.src.set(state_leaf, "degraded")                                           # another value changes: one document, with seq as it is
    rig.run(1, each=heartbeat)
    assert rig.times(VSS_UPDATE) == [0.0, 201.0] and rig.vss()[-1][seq_leaf] == 243 and rig.vss()[-1][state_leaf] == "degraded"
    assert twin.shadowdoc.seq_keys(frozen) == frozenset([seq_leaf])
    # the change rule compares as JSON does, not as Python does: true is not 1, false is not 0, and 1 is not 1.0
    changed = twin.shadowdoc.changed
    assert [changed({"k": a}, {"k": b}) for a, b in ((True, 1), (0, False), (1, 1.0), (1, 1), (True, True), (None, None), (None, 0))] == [
        True, True, True, False, False, False, True]


# ============================================================ batching and the vss shadow

def test_a_batch_closes_every_60_s_at_1_hz_and_every_10_s_at_10_hz(twin, frozen, tmp_path):
    tpaths = list(twin.envelope.telemetry_paths(frozen, frozen.PATHS))
    assert len(tpaths) == 7 and attr.WHEELBASE not in tpaths and not set(tpaths) & set(frozen.APPSTATE_FIELDS)
    slow = Rig(twin, frozen, tmp_path / "slow", normal_values(frozen)).start().run(180)
    assert slow.conn.rate_hz == 1 and slow.times(TELEMETRY_TOPIC) == [59.0, 119.0, 179.0]
    for n, batch in enumerate(slow.telemetry()):
        assert list(batch) == ["v", "batch", "paths", "rows", "appstate"] and (batch["v"], batch["batch"]) == (1, n + 1)
        assert batch["paths"] == tpaths and len(batch["rows"]) == 60
        assert [row[0] for row in batch["rows"]] == [T0_MS + 1000 * (60 * n + k) for k in range(60)]
        assert all(len(row) == 8 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in row) for row in batch["rows"])
    assert slow.telemetry()[0]["rows"][0][1:] == [1.25, 2.5, 3.75, 5.0, 6.25, 3, 1]          # a boolean is 0 or 1
    fast = Rig(twin, frozen, tmp_path / "fast", normal_values(frozen))
    fast.shadow.cloud("config", {"rate_hz": 10})
    fast.start().run(30)
    assert fast.conn.rate_hz == 10 and fast.times(TELEMETRY_TOPIC) == [9.9, 19.9, 29.9]
    for n, batch in enumerate(fast.telemetry()):
        assert len(batch["rows"]) == 100 and [row[0] for row in batch["rows"]] == [T0_MS + 100 * (100 * n + k) for k in range(100)]
    assert all(p.qos == 1 for p in slow.fake.published + fast.fake.published)


def test_an_empty_batch_is_not_sent(twin, frozen, tmp_path):
    idle = Rig(twin, frozen, tmp_path / "idle", {}).start().run(200).stop()          # the databroker holds no value at all
    assert idle.at(TELEMETRY_TOPIC) == [] and idle.conn.counters["empty_batches"] == 4 and idle.conn.counters["sent_telemetry"] == 0
    assert len(idle.vss()) == 2 and all(v is None for doc in idle.vss() for v in doc.values())
    assert idle.times(VSS_UPDATE) == [2.0, 200.0]          # the first document waited for a value, 2 s at most
    # narrowed to a path that is not telemetry at all (the wheelbase goes to the shadow only): no batch either
    only_s = Rig(twin, frozen, tmp_path / "s", normal_values(frozen))
    only_s.shadow.cloud("config", {"paths": [attr.WHEELBASE]})
    only_s.start().run(130).stop()
    assert only_s.at(TELEMETRY_TOPIC) == [] and only_s.vss()[-1][attr.WHEELBASE] == 2700
    # narrowed to the app's eight leaves: no row, and the record alone is a batch
    app = Rig(twin, frozen, tmp_path / "app", normal_values(frozen))
    app.shadow.cloud("config", {"paths": list(frozen.APPSTATE_FIELDS)})
    app.start().run(59)
    assert app.telemetry() == [{"v": 1, "batch": 1, "paths": [], "rows": [], "appstate": [EXAMPLE]}]
    # a row is a sample: when no path has a value there is nothing to sample, and the tick adds no row
    late = Rig(twin, frozen, tmp_path / "late", {}).start().run(0.5)
    assert late.at(VSS_UPDATE) == []
    late.run(29.5)
    late.src.set(frozen.PATHS[1], 12.5)
    late.run(29)
    (batch,) = late.telemetry()
    assert [row[0] for row in batch["rows"]] == [T0_MS + 1000 * k for k in range(31, 60)]
    assert all(row[1:] == [None, 12.5, None, None, None, None, None] for row in batch["rows"])
    # the batch counter counts the batches that held something: the first one sent after two empty ones is batch 1
    quiet = Rig(twin, frozen, tmp_path / "quiet", {}).start().run(125)
    assert quiet.conn.counters["empty_batches"] == 2 and quiet.at(TELEMETRY_TOPIC) == []
    quiet.src.set(frozen.PATHS[1], 12.5)
    quiet.run(55)
    assert [(b["batch"], len(b["rows"])) for b in quiet.telemetry()] == [(1, 54)] and quiet.times(TELEMETRY_TOPIC) == [179.0]


def test_the_vss_document_goes_on_change_no_closer_than_60_s_and_once_at_stop(twin, frozen, tmp_path):
    speed = frozen.PATHS[1]
    rig = Rig(twin, frozen, tmp_path / "moving", normal_values(frozen)).start()
    rig.run(200, each=lambda r: r.src.set(speed, 10.0 + r.now()))                 # a value that changes every step
    assert rig.times(VSS_UPDATE) == [0.0, 60.0, 120.0, 180.0]
    assert [doc[speed] for doc in rig.vss()] == [2.5, 70.0, 130.0, 190.0]
    rig.stop()
    assert rig.times(VSS_UPDATE)[-1] == 200.0 and len(rig.vss()) == 5 and rig.vss()[-1][speed] == 210.0
    still = Rig(twin, frozen, tmp_path / "still", normal_values(frozen)).start().run(200)
    assert still.times(VSS_UPDATE) == [0.0]                                       # nothing changed: no document
    still.src.set(speed, 99.0)
    still.run(1)
    assert still.times(VSS_UPDATE) == [0.0, 201.0]                                # the first change after 60 s goes at the next tick
    still.src.set(speed, 98.0)
    still.run(59.9)
    assert len(still.vss()) == 2                                                  # and the next one waits its 60 s
    still.run(0.1)
    assert still.times(VSS_UPDATE) == [0.0, 201.0, 261.0]


def test_the_first_vss_document_waits_for_the_sources_first_value_two_seconds_at_most(twin, frozen, tmp_path):
    """A real subscription's first response arrives a moment after it is opened. A first document sent before it would
    be all null, and the next one is a minute away."""
    rig = Rig(twin, frozen, tmp_path / "a", {}).start().run(0.5)
    assert rig.at(VSS_UPDATE) == [] and len(rig.reports()) == 1                    # the config report does not wait
    for path, value in normal_values(frozen).items():
        rig.src.set(path, value)                                                  # the first response arrives
    rig.run(0.4)
    assert rig.at(VSS_UPDATE) == []                                               # no tick yet
    rig.run(0.1)
    assert rig.times(VSS_UPDATE) == [1.0] and all(v is not None for v in rig.vss()[0].values())
    never = Rig(twin, frozen, tmp_path / "b", {}).start().run(1.9)
    assert never.at(VSS_UPDATE) == []
    never.run(0.1)
    assert never.times(VSS_UPDATE) == [2.0] and all(v is None for v in never.vss()[0].values())          # then it clears what is there
    never.run(100)
    assert never.times(VSS_UPDATE) == [2.0]


def test_stop_flushes_one_batch_and_one_vss_document_then_closes(twin, frozen, tmp_path):
    seq_leaf = [leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "seq"][0]
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(30)
    assert rig.at(TELEMETRY_TOPIC) == [] and len(rig.vss()) == 1
    rig.src.set(frozen.PATHS[1], 77.0)
    rig.src.set(seq_leaf, EXAMPLE["seq"] + 4242)                                  # the app's record moved on since the last tick, too
    rig.clock.advance(0.5)
    before = len(rig.fake.published)
    rig.stop()
    flushed = rig.fake.published[before:]
    assert [p.topic for p in flushed] == [TELEMETRY_TOPIC, VSS_UPDATE]
    (batch,) = rig.telemetry()
    assert len(batch["rows"]) == 31 and [row[0] for row in batch["rows"]] == [T0_MS + 1000 * k for k in range(31)]
    assert rig.vss()[-1][frozen.PATHS[1]] == 77.0                                 # the last document reads the source once more
    assert batch["appstate"] == [dict(EXAMPLE, seq=EXAMPLE["seq"] + 4242)]        # and the stop's batch takes that last read's record
    assert rig.fake.closes == 1 and rig.src.closed == 1 and not rig.fake.connected
    stop = rig.log("stop")
    assert len(stop) == 1 and stop[0]["counters"]["sent_telemetry"] == 1 and stop[0]["counters"]["sent_vss"] == 2
    published = len(rig.fake.published)
    rig.conn.stop()                                                               # a second stop does nothing
    rig.conn.step()
    assert len(rig.fake.published) == published and rig.fake.closes == 1
    # a stop before the config was read flushes nothing: no subscription was made, so there is nothing to say
    early = Rig(twin, frozen, tmp_path / "early", normal_values(frozen), shadow=False)
    early.conn.start()
    early.conn.stop()
    assert [p.topic for p in early.fake.published] == [CONFIG_GET] and early.src.calls == []


def test_a_stop_within_a_second_of_a_telemetry_publish_waits_out_the_gap_and_still_sends_the_open_batch(twin, frozen, tmp_path):
    """The review's counterexample: a narrowing closes and sends the open batch at 30.1 s, the tick at 31.0 s opens the
    next one, and the stop comes at 31.0 s. The limiter refuses the flush for its one-second gap; dropped there, the
    last rows were counted and never sent, and "the open batch closed and sent" was not true. The gap is under a
    second, so the stop waits it out, once, and sends. A refusal for the window is another matter: waiting would be
    minutes, and a stop does not wait for that."""
    narrowed = [frozen.PATHS[0], frozen.PATHS[1]]
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(30)
    rig.shadow.cloud("config", {"paths": narrowed})
    rig.run(0.1)                                                                  # 30.1 s: the open batch, closed by the narrowing
    assert rig.times(TELEMETRY_TOPIC) == [30.1] and len(rig.telemetry()[0]["rows"]) == 31
    rig.run(0.9)                                                                  # 31.0 s: the tick opens the next batch, one row
    rig.stop()                                                                    # 0.9 s after that publish
    assert [len(b["rows"]) for b in rig.telemetry()] == [31, 1], "the stop's batch was refused for the gap and dropped"
    assert rig.telemetry()[1]["paths"] == narrowed and rig.telemetry()[1]["rows"][0][0] == T0_MS + 31_000
    assert rig.times(TELEMETRY_TOPIC) == [30.1, 31.101] and smallest_gap_ms([p.t for p in rig.at(TELEMETRY_TOPIC)]) == 1001
    assert [p.topic for p in rig.fake.published][-2:] == [TELEMETRY_TOPIC, VSS_UPDATE] and rig.times(VSS_UPDATE)[-1] == 31.101
    (stop,) = rig.log("stop")          # the first try is counted as what it was, a refusal; the second went
    assert (stop["counters"]["sent_telemetry"], stop["counters"]["refused_telemetry"]) == (2, 1) and stop["limiter"] == {"refused_rate": 1}
    # the window's cap at a stop: refused, dropped and counted, and the clock has not moved
    full = Rig(twin, frozen, tmp_path / "full", normal_values(frozen)).start().run(1)
    for _ in range(twin.limits.TELEMETRY_MAX_PER_WINDOW):                          # the window's 60, put there through the connector's own limiter
        full.clock.advance(1.0)
        full.conn.uplink.publish(TELEMETRY_TOPIC, b"{}")
    full.clock.advance(1.0)
    at = full.clock.monotonic()
    full.stop()
    assert full.clock.monotonic() == at and len(full.at(TELEMETRY_TOPIC)) == 60
    assert full.conn.counters["refused_telemetry"] == 1 and full.conn.uplink.counters == {"refused_window": 1}
    assert full.at(VSS_UPDATE)[-1].t == at                                        # the last document still goes
    # and only the stop waits: in the loop a batch refused for the gap is dropped as before, and the step takes no time
    loop = Rig(twin, frozen, tmp_path / "loop", normal_values(frozen))
    loop.shadow.cloud("config", {"rate_hz": 10})
    loop.start().run(2)
    loop.shadow.cloud("config", {"paths": narrowed})
    loop.run(0.1)                                                                 # 2.1 s: closed by the narrowing, and sent
    loop.run(0.4)                                                                 # four ticks into the next batch
    loop.shadow.cloud("config", {"paths": list(frozen.PATHS)})
    at = round(loop.clock.monotonic() + 0.1, 3)
    loop.run(0.1)                                                                 # 2.6 s: closed by the widening, 0.5 s after that publish
    assert loop.clock.monotonic() == at and loop.times(TELEMETRY_TOPIC) == [2.1]
    assert loop.conn.counters["refused_telemetry"] == 1 and loop.conn.uplink.counters == {"refused_rate": 1}
    # a refused telemetry publish holds no shadow publish back: the report of the widening went in that same step
    assert loop.times(CONFIG_UPDATE) == [0.0, 2.1, 2.6]


def test_the_shadow_guards_refuse_a_document_over_8_kb_or_deeper_than_8_levels(twin, frozen, tmp_path):
    S, L = twin.shadowdoc, twin.limits
    assert [S.depth(x) for x in (1, "a", None, {}, [], {"a": 1}, {"a": {"b": [1]}}, [[[]]])] == [0, 0, 0, 1, 1, 1, 3, 3]
    wrap = len(S.reported({"k": ""}))
    at_limit = {"k": "x" * (L.SHADOW_DOC_LIMIT_BYTES - wrap)}
    assert len(S.reported(at_limit)) == 8192 == L.SHADOW_DOC_LIMIT_BYTES
    with pytest.raises(S.DocRefused, match="8192"):
        S.reported({"k": "x" * (L.SHADOW_DOC_LIMIT_BYTES - wrap + 1)})

    def nested(levels):
        doc: Any = 1
        for _ in range(levels):
            doc = {"k": doc}
        return doc

    assert json.loads(S.reported(nested(6))) == {"state": {"reported": nested(6)}} and S.depth(json.loads(S.reported(nested(6)))) == 8
    with pytest.raises(S.DocRefused, match="8 levels"):
        S.reported(nested(7))
    with pytest.raises(S.DocRefused):
        S.reported({"k": float("nan")})                                           # not JSON at all
    # the connector sends every shadow document through the guard: a refused document is counted and never sent
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    real = S.reported

    def refusing(state):
        if "rate_hz" not in state:
            raise S.DocRefused("a vss document the guard refuses")
        return real(state)

    S.reported = refusing
    try:
        rig.start().run(70).stop()
    finally:
        S.reported = real
    assert rig.at(VSS_UPDATE) == [] and rig.conn.counters["doc_refused"] >= 2 and len(rig.reports()) == 1


def test_a_narrowing_between_two_samples_yields_two_batches_each_row_as_long_as_its_own_header(twin, frozen, tmp_path):
    tpaths = list(twin.envelope.telemetry_paths(frozen, frozen.PATHS))
    narrowed = [frozen.PATHS[5], frozen.PATHS[0], attr.WHEELBASE, frozen.PATHS[2]]
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(10)
    rig.clock.advance(0.5)
    rig.shadow.cloud("config", {"paths": narrowed})                               # lands between the samples at 10 s and 11 s
    rig.conn.step()
    assert rig.times(TELEMETRY_TOPIC) == [10.5]                                   # the open batch is closed and sent first
    rig.clock.advance(0.5)
    rig.conn.step()
    rig.run(9).stop()
    first, second = rig.telemetry()
    assert first["paths"] == tpaths and len(first["rows"]) == 11 and all(len(row) == 8 for row in first["rows"])
    assert second["paths"] == [frozen.PATHS[0], frozen.PATHS[2], frozen.PATHS[5]] and len(second["rows"]) == 10
    assert all(len(row) == 4 for row in second["rows"]) and second["rows"][0] == [T0_MS + 11000, 1.25, 3.75, 3]
    assert (first["batch"], second["batch"]) == (1, 2)
    assert first["rows"][-1][0] == T0_MS + 10000 and rig.reports()[-1]["paths"] == [frozen.PATHS[0], frozen.PATHS[2], frozen.PATHS[5], attr.WHEELBASE]


def test_a_rate_change_closes_the_open_batch_and_the_next_one_runs_at_the_new_rate(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(20)
    rig.shadow.cloud("config", {"rate_hz": 10})
    rig.run(11.5)
    rig.shadow.cloud("config", {"rate_hz": 1})
    rig.run(5).stop()
    one, ten, tail, last = rig.telemetry()
    assert rig.times(TELEMETRY_TOPIC) == [20.1, 30.0, 31.6, 36.5]
    assert [len(b["rows"]) for b in (one, ten, tail, last)] == [21, 100, 15, 5]
    assert [row[0] - T0_MS for row in ten["rows"]] == [20100 + 100 * k for k in range(100)]          # the new rate from the change on
    assert [row[0] - T0_MS for row in last["rows"]] == [31600 + 1000 * k for k in range(5)]
    assert rig.conn.counters["refused_telemetry"] == 0
    assert [r["rate_hz"] for r in rig.reports()] == [1, 10, 1]


def test_the_next_vss_document_nulls_what_left_the_effective_set_and_the_first_nulls_every_absent_key(twin, frozen, tmp_path):
    have = {frozen.PATHS[1]: 45.0, attr.WHEELBASE: 2700, frozen.PATHS[6]: False}
    rig = Rig(twin, frozen, tmp_path / "first", have).start()
    (first,) = rig.vss()
    assert list(first) == list(frozen.PATHS)                                      # every allowlisted key, in the tuple's order
    assert {k: v for k, v in first.items() if v is not None} == have              # a boolean stays a boolean in the shadow
    assert first[frozen.PATHS[6]] is False
    full = Rig(twin, frozen, tmp_path / "narrow", normal_values(frozen)).start().run(10)
    gone = [frozen.PATHS[1], frozen.PATHS[4], attr.WHEELBASE]
    full.shadow.cloud("config", {"paths": [p for p in frozen.PATHS if p not in gone]})
    full.run(49.9)
    assert len(full.vss()) == 1                                                   # the 60 s floor holds for a narrowing too
    full.run(0.1)
    before, after = full.vss()
    assert all(before[p] is not None for p in frozen.PATHS)
    assert [p for p in frozen.PATHS if after[p] is None] == gone and list(after) == list(frozen.PATHS)
    shadow = full.shadow.docs["vss"]["reported"]                                  # merged as the service merges: the keys are gone
    assert not set(gone) & set(shadow) and set(shadow) == set(frozen.PATHS) - set(gone)
    # the document's own filter, apart from the connector's: given a value for a path outside the effective set (and a
    # record for an app whose leaves are outside it), it holds null there all the same
    only = (frozen.PATHS[0], attr.WHEELBASE)
    state = twin.shadowdoc.vss_state(frozen, only, normal_values(frozen), {frozen.APPSTATE_BRANCHES[0]: EXAMPLE})
    assert list(state) == list(frozen.PATHS) and {k: v for k, v in state.items() if v is not None} == {frozen.PATHS[0]: 1.25, attr.WHEELBASE: 2700}


def test_a_row_is_positional_and_holds_numbers_only(twin, frozen):
    cell = twin.envelope.cell
    assert (cell("boolean", True), cell("boolean", False)) == (1, 0) and type(cell("boolean", True)) is int
    assert [cell("boolean", bad) for bad in (1, 0, "true", None, 1.0)] == [None] * 5
    assert cell("float", 1.5) == 1.5 and cell("double", -2) == -2
    assert [cell("float", bad) for bad in (float("nan"), float("inf"), float("-inf"), True, "1.5", None, [1.5])] == [None] * 7
    # an integer in a float leaf only as far as a double holds it exactly: beyond that it would print as hundreds of
    # digits, and one too large for a double at all must give null, not an error that ends the loop
    assert [cell("double", v) for v in (2 ** 53, -2 ** 53, 2 ** 53 + 1, -2 ** 53 - 1, 10 ** 300, 10 ** 400, -10 ** 400)] == [
        2 ** 53, -2 ** 53, None, None, None, None, None]
    assert cell("float", 1.7976931348623157e+308) == 1.7976931348623157e+308
    assert twin.shadowdoc.vss_state(frozen, frozen.PATHS, {frozen.PATHS[1]: 10 ** 400}, {})[frozen.PATHS[1]] is None
    assert [cell("int8", v) for v in (-128, 127, -129, 128, 1.0, True, "3")] == [-128, 127, None, None, None, None, None]
    assert [cell("uint16", v) for v in (0, 65535, 65536, -1)] == [0, 65535, None, None]
    assert [cell("uint32", v) for v in (2 ** 32 - 1, 2 ** 32)] == [2 ** 32 - 1, None]
    assert [cell("uint64", v) for v in (2 ** 64 - 1, 2 ** 64)] == [2 ** 64 - 1, None] and cell("int64", -2 ** 63) == -2 ** 63
    assert cell("string", "running") is None and cell("no-such-type", 1) is None          # never free text in a row
    paths = twin.envelope.telemetry_paths(frozen, frozen.PATHS)
    values = dict(normal_values(frozen), **{paths[0]: float("nan"), paths[2]: "fast"})
    row = twin.envelope.row(T0_MS, paths, values, frozen.NODES)
    assert row == [T0_MS, None, 2.5, None, 5.0, 6.25, 3, 1] and twin.envelope.has_value(row)
    assert not twin.envelope.has_value([T0_MS, None, None]) and not twin.envelope.has_value([T0_MS])
    payload = twin.envelope.encode(twin.envelope.batch(7, paths, [row], [EXAMPLE]))
    assert json.loads(payload) == {"v": 1, "batch": 7, "paths": list(paths), "rows": [row], "appstate": [EXAMPLE]}
    assert b" " not in payload and b"NaN" not in payload and payload.isascii()
    with pytest.raises(ValueError):
        twin.envelope.encode({"rows": [[float("inf")]]})
    # a narrowed set keeps the tuple's order; a string leaf outside AppState, or one that is not telemetry, is no column
    shuffled = (frozen.PATHS[5], attr.WHEELBASE, frozen.PATHS[9], frozen.PATHS[0])
    assert twin.envelope.telemetry_paths(frozen, shuffled) == (frozen.PATHS[0], frozen.PATHS[5])
    stringy = types.SimpleNamespace(PATHS=("A", "B"), CHANNELS={"A": ("S", "T"), "B": ("S", "T")}, APPSTATE_FIELDS={},
                                    NODES={"A": ("sensor", "string", None), "B": ("sensor", "float", None)})
    assert twin.envelope.telemetry_paths(stringy, ("A", "B")) == ("B",)
    assert twin.shadowdoc.vss_state(stringy, ("A", "B"), {"A": "free text", "B": 1.5}, {}) == {"A": None, "B": 1.5}


# ============================================================ the limiter

def _limiter(twin: Any) -> Tuple[Any, Any, Any, Any]:
    clock = twin.connector.ManualClock(t=5000.0, wall_ms=T0_MS)
    fake = twin.uplink.FakeUplink(clock=clock)
    topics = twin.topics.Topics(THING, RULE)
    lim = twin.limiter.Limiter(fake, topics, clock)
    lim.connect()
    return lim, fake, clock, topics


def _refused(twin: Any, lim: Any, topic: str, payload: bytes) -> Any:
    with pytest.raises(twin.limiter.LimitRefused) as exc:
        lim.publish(topic, payload)
    return exc.value


def test_the_limiter_holds_telemetry_to_one_publish_a_second_and_60_in_any_300_s(twin):
    lim, fake, clock, topics = _limiter(twin)
    assert topics.telemetry == TELEMETRY_TOPIC
    lim.publish(TELEMETRY_TOPIC, b"{}")
    clock.advance(0.999)
    why = _refused(twin, lim, TELEMETRY_TOPIC, b"{}")
    assert (why.why, round(why.retry_after_s, 3)) == ("rate", 0.001) and isinstance(why, twin.uplink.UplinkError)
    clock.advance(0.001)
    lim.publish(TELEMETRY_TOPIC, b"{}")                                           # exactly a second later
    for _ in range(58):
        clock.advance(1.0)
        lim.publish(TELEMETRY_TOPIC, b"{}")
    assert len(fake.published) == 60                                              # at 0 .. 59 s
    clock.advance(1.0)
    why = _refused(twin, lim, TELEMETRY_TOPIC, b"{}")
    assert why.why == "window" and 240.0 < why.retry_after_s < 240.01             # until the one at 0 s is more than 300 s old
    clock.advance(240.0)                                                          # 300 s after the first: 61 in [0, 300] would be 61 in 300 s
    assert _refused(twin, lim, TELEMETRY_TOPIC, b"{}").why == "window"
    clock.advance(0.001)
    lim.publish(TELEMETRY_TOPIC, b"{}")
    assert len(fake.published) == 61 and lim.counters == {"refused_rate": 1, "refused_window": 2}
    # a refused publish takes no place in the window, and never reaches the uplink
    times = [p.t for p in fake.published]
    assert smallest_gap_ms(times) == 1000 and most_in_a_closed_window(times) == 60


def test_the_limiters_window_is_closed_from_any_instant_and_not_only_from_one_a_float_holds_exactly(twin):
    """A float can stand a little off the instant it means: 2222.3 - 1922.3 is 300.0000000000002. A window compared in
    floats alone would call a publish that is exactly 300 s old "more than 300 s old" and let a 61st telemetry publish
    into [1922.3, 2222.3], an 11th shadow publish into [1900.3, 2200.3] (the review counted both). It happens where
    the window crosses a power of two, because the floats are spaced twice as wide beyond it. Held here from those two
    starts, from 600 more whose window crosses 1024, 2048 or 4096 s, and from 200 whose window crosses none, and
    counted in whole milliseconds. The other end is held too: a millisecond later the oldest publish is out."""
    L = twin.limits
    assert 2222.3 - 1922.3 > 300.0 and 2200.3 - 1900.3 > 300.0                     # the two the review found
    starts = [1922.3, 1900.3, 5000.0]
    for below in (1024, 2048, 4096):                                              # 200 starts in the 300 s below each
        starts += [below - 0.001 * (1 + (7919 * k) % 299_999) for k in range(200)]
    starts += [2100.0 + 0.001 * ((7919 * k) % 1_600_000) for k in range(200)]     # and 200 whose window crosses no power of two
    fooled = 0
    for start in starts:
        for topic, cap, step in ((TELEMETRY_TOPIC, L.TELEMETRY_MAX_PER_WINDOW, 5.0), (VSS_UPDATE, L.SHADOW_MAX_PER_WINDOW, 30.0)):
            clock = twin.connector.ManualClock(t=start, wall_ms=T0_MS)
            fake = twin.uplink.FakeUplink(clock=clock)
            lim = twin.limiter.Limiter(fake, twin.topics.Topics(THING, RULE), clock)
            lim.connect()
            first = clock.monotonic()
            for _ in range(cap):                                                  # the cap, spread over the window
                lim.publish(topic, b"{}")
                clock.advance(step)
            assert cap * step == L.LIMITER_WINDOW_S == 300                         # the clock now stands exactly 300 s after the first
            fooled += clock.monotonic() - first > L.LIMITER_WINDOW_S              # ... and its float may say "more than 300 s"
            assert _refused(twin, lim, topic, b"{}").why == "window", (start, topic)          # one more would be cap + 1 in a closed 300 s
            clock.advance(0.001)
            lim.publish(topic, b"{}")                                             # a millisecond later the first is out
            times = [p.t for p in fake.published]
            assert len(times) == cap + 1 and most_in_a_closed_window(times) == cap, (start, topic)
    print("limiter window: %d starts, %d of the %d runs with a float difference over 300 s" % (len(starts), fooled, 2 * len(starts)))
    assert fooled > 250          # not held by luck: in this many of the runs the floats alone say the first is already out
    # The one-second gap needs no guard: a publish 999 ms after the last is refused from every start, also where the
    # two instants lie on either side of a power of two. (One exactly 1000 ms after may be refused there too, when the
    # float difference rounds to just under 1.0: that keeps the cap, and is not held here either way.)
    for below in (1024, 2048, 4096):
        for k in range(1, 1000, 7):                                               # 143 starts in the second below each
            clock = twin.connector.ManualClock(t=below - 0.001 * k, wall_ms=T0_MS)
            fake = twin.uplink.FakeUplink(clock=clock)
            lim = twin.limiter.Limiter(fake, twin.topics.Topics(THING, RULE), clock)
            lim.connect()
            lim.publish(TELEMETRY_TOPIC, b"{}")
            clock.advance(0.999)
            assert _refused(twin, lim, TELEMETRY_TOPIC, b"{}").why == "rate", (below, k)
            clock.advance(0.002)
            lim.publish(TELEMETRY_TOPIC, b"{}")
            assert smallest_gap_ms([p.t for p in fake.published]) == 1001, (below, k)


def test_the_limiter_holds_both_shadows_together_to_10_publishes_in_any_300_s(twin):
    lim, fake, clock, _topics = _limiter(twin)
    for i in range(10):                                                           # no gap rule between shadow publishes
        lim.publish((VSS_UPDATE, CONFIG_UPDATE, CONFIG_GET)[i % 3], b"")
        clock.advance(0.01)
    why = _refused(twin, lim, VSS_UPDATE, b"{}")
    assert why.why == "window" and 299.89 < why.retry_after_s < 299.91
    assert _refused(twin, lim, CONFIG_UPDATE, b"{}").why == "window" and _refused(twin, lim, CONFIG_GET, b"").why == "window"
    lim.publish(TELEMETRY_TOPIC, b"{}")                                           # telemetry has its own window
    clock.advance(299.9)
    assert _refused(twin, lim, VSS_UPDATE, b"{}").why == "window"                 # the first is exactly 300 s old: still inside
    clock.advance(0.001)
    lim.publish(VSS_UPDATE, b"{}")
    assert len(fake.published) == 12


def test_a_payload_at_the_byte_cap_passes_and_one_above_is_never_sent(twin):
    lim, fake, clock, _topics = _limiter(twin)
    L = twin.limits
    lim.publish(TELEMETRY_TOPIC, b"x" * L.TELEMETRY_MAX_BYTES)
    clock.advance(1)
    why = _refused(twin, lim, TELEMETRY_TOPIC, b"x" * (L.TELEMETRY_MAX_BYTES + 1))
    assert (why.why, why.retry_after_s) == ("bytes", None)                        # waiting does not make it smaller
    lim.publish(VSS_UPDATE, b"x" * L.SHADOW_MAX_BYTES)
    assert _refused(twin, lim, VSS_UPDATE, b"x" * (L.SHADOW_MAX_BYTES + 1)).why == "bytes"
    assert _refused(twin, lim, CONFIG_UPDATE, b"x" * (L.SHADOW_MAX_BYTES + 1)).why == "bytes"
    assert _refused(twin, lim, TELEMETRY_TOPIC, b"x" * 131072).why == "bytes"
    assert [len(p.payload) for p in fake.published] == [16384, 4096]
    lim.publish(TELEMETRY_TOPIC, b"x" * 16384)                                    # the refused ones took no place in a window
    with pytest.raises(twin.limiter.LimitRefused) as exc:
        lim.publish(TELEMETRY_TOPIC, "a str is not a payload")
    assert exc.value.why == "payload" and len(fake.published) == 3


def test_the_limiter_passes_only_the_connectors_own_topics_and_counts_an_attempt_the_uplink_failed(twin):
    lim, fake, clock, topics = _limiter(twin)
    others = [SHADOW_PREFIX + "vss/get", SHADOW_PREFIX + "vss/delete", SHADOW_PREFIX + "config/delete", "$aws/rules/%s" % RULE,
              "$aws/rules/%s/other-thing" % RULE, "$aws/rules/other_rule/%s" % THING, "$aws/things/other-thing/shadow/name/vss/update",
              "$aws/things/%s/shadow/update" % THING, TELEMETRY_TOPIC + "/", TELEMETRY_TOPIC + "/#", "#", "sdv/probe", ""]
    for topic in others:
        assert _refused(twin, lim, topic, b"{}").why == "topic", topic
    assert fake.published == [] and lim.counters == {"refused_topic": len(others)}
    seen: List[Any] = []
    for topic in topics.subscribe:
        lim.subscribe(topic, lambda t, p: seen.append((t, p)))
    assert set(fake.subscriptions) == set(topics.subscribe)
    for topic in (CONFIG_UPDATE + "/accepted", SHADOW_PREFIX + "vss/update/accepted", SHADOW_PREFIX + "#", "$aws/#", "#", TELEMETRY_TOPIC):
        with pytest.raises(twin.limiter.LimitRefused):
            lim.subscribe(topic, lambda t, p: None)
    assert set(fake.subscriptions) == set(topics.subscribe)
    # an attempt the uplink failed may have reached the wire: it keeps its place in the window
    fake.fail_publish = lambda topic, payload: "timed out"
    for _ in range(10):
        with pytest.raises(twin.uplink.UplinkError) as exc:
            lim.publish(VSS_UPDATE, b"{}")
        assert not isinstance(exc.value, twin.limiter.LimitRefused)
    fake.fail_publish = None
    assert _refused(twin, lim, VSS_UPDATE, b"{}").why == "window" and fake.published == []
    lim.close()
    assert fake.closes == 1 and lim.inner is fake


def _entry(twin: Any, allow: Any, tmp_path: Path, src: Any, fake: Any, clock: Any, out: Any, handlers: Dict[int, Any],
           status_dir: Optional[Path] = None) -> Callable[[], int]:
    """The real entry point on fakes: connector.main with its uplink and source factories, a manual clock, and the
    signal handlers it installs captured instead of installed. The status record is read from `status_dir`, by default
    a directory that does not exist (no test reads the host's own)."""
    env = {"SDV_TWIN_THING": THING, "SDV_TWIN_RULE": RULE, "SDV_TWIN_SPOOL": str(tmp_path), "SDV_TWIN_SCHEMA": str(SCHEMA_FILE),
           "SDV_TWIN_ENDPOINT": "broker.example.invalid", "SDV_TWIN_KEY": "/run/sdv-local/device/device.key",
           "SDV_TWIN_STATUS": str(status_dir if status_dir is not None else tmp_path / "no-status-of-this-test")}

    def run() -> int:
        saved = twin.connector.signal.signal
        twin.connector.signal.signal = lambda signum, handler: handlers.__setitem__(signum, handler)
        try:
            return twin.connector.main([], env=env, make_uplink=lambda e, topics: fake, make_source=lambda target: src,
                                       clock=clock, out=out, frozen=allow)
        finally:
            twin.connector.signal.signal = saved

    return run


def test_every_cap_holds_at_the_uplink_under_a_source_that_changes_every_tick_and_a_config_that_flaps(twin, frozen, tmp_path, monkeypatch):
    """Through the real entry point, so the limiter that holds them is the one the entry point put there."""
    L = twin.limits
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    fake = twin.uplink.FakeUplink(clock=clock)
    shadow = FakeShadow(fake)
    floats = [p for p in frozen.PATHS if frozen.NODES[p][1] == "float"]
    seq_leaf = [leaf for leaf, prop in frozen.APPSTATE_FIELDS.items() if prop == "seq"][0]
    src = twin.source.FakeSource(normal_values(frozen))
    handlers: Dict[int, Any] = {}
    out = io.StringIO()
    n = [0]
    # Five narrowings in turn, so that the desired set is hardly ever the one last reported: the service puts into a
    # delta only what differs from reported, and a report the limiter held back leaves reported behind.
    sets = [[p for p in frozen.PATHS if p != gone] for gone in floats]

    def hostile(c):
        n[0] += 1
        for i, p in enumerate(floats):
            src.set(p, 0.25 * n[0] + i)                                            # every value moves at every tick
        src.set(seq_leaf, n[0])
        shadow.cloud("config", {"rate_hz": 10 if n[0] % 2 else 1, "paths": sets[n[0] % 5]})          # and the config flaps
        if c.monotonic() - 1000.0 >= 650.0:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    clock.on_sleep.append(hostile)
    built: List[Any] = []
    real_build = twin.connector.build
    monkeypatch.setattr(twin.connector, "build", lambda *a, **k: built.append(real_build(*a, **k)) or built[-1])
    assert _entry(twin, frozen, tmp_path, src, fake, clock, out, handlers)() == 0
    assert set(handlers) == {signal.SIGTERM, signal.SIGINT} and n[0] > 600 and len(sets) == 5
    telemetry = [p for p in fake.published if p.topic == TELEMETRY_TOPIC]
    shadows = [p for p in fake.published if p.topic != TELEMETRY_TOPIC]
    assert {p.topic for p in shadows} == {VSS_UPDATE, CONFIG_UPDATE, CONFIG_GET}
    times = [p.t for p in telemetry]
    assert smallest_gap_ms(times) >= 1000 * L.TELEMETRY_MIN_GAP_S                  # counted in whole milliseconds, ends included
    assert most_in_a_closed_window(times) == L.TELEMETRY_MAX_PER_WINDOW == 60
    assert max(len(p.payload) for p in telemetry) <= L.TELEMETRY_MAX_BYTES
    stimes = [p.t for p in shadows]
    assert most_in_a_closed_window(stimes) == L.SHADOW_MAX_PER_WINDOW == 10
    assert max(len(p.payload) for p in shadows) <= L.SHADOW_MAX_BYTES
    # not held by having nothing to send: the limiter refused, the connector dropped and counted, and went on
    (stop,) = [json.loads(line) for line in out.getvalue().splitlines() if '"event":"stop"' in line]
    assert stop["signal"] == int(signal.SIGTERM) and stop["counters"]["refused_telemetry"] > 300
    assert stop["counters"]["refused_config"] + stop["counters"]["refused_vss"] >= 3
    assert 120 <= len(telemetry) <= 180 and 20 <= len(shadows) <= 30
    assert {p.topic for p in shadows[-12:]} >= {VSS_UPDATE, CONFIG_UPDATE}          # the vss document is not starved by the config
    # and the entry point built the uplink wrapped: the connector holds the limiter and reaches the uplink through nothing else
    (conn,) = built
    assert type(conn.uplink) is twin.limiter.Limiter and conn.uplink.inner is fake
    assert not [k for k, v in vars(conn).items() if v is fake]


def test_the_entry_point_builds_the_uplink_wrapped_and_the_connector_refuses_one_that_is_not(twin, frozen, tmp_path):
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    fake, topics, src = twin.uplink.FakeUplink(clock=clock), twin.topics.Topics(THING, RULE), twin.source.FakeSource({})
    no_status = tmp_path / "no-status"
    conn = twin.connector.build(fake, src, clock, topics, frozen, SCHEMA, tmp_path, io.StringIO(), status_dir=no_status)
    assert type(conn) is twin.connector.Connector and type(conn.uplink) is twin.limiter.Limiter and conn.uplink.inner is fake
    assert conn.uplink.topics is topics and conn.uplink.clock is clock
    assert not [k for k, v in vars(conn).items() if v is fake]
    with pytest.raises(TypeError, match="limiter"):                               # no connector exists on a bare uplink
        twin.connector.Connector(fake, src, clock, topics, frozen, SCHEMA, tmp_path, io.StringIO(), status_dir=no_status)
    with pytest.raises(TypeError, match="limiter"):                               # nor on a limiter around a limiter's stand-in
        twin.connector.Connector(types.SimpleNamespace(inner=fake), src, clock, topics, frozen, SCHEMA, tmp_path, io.StringIO(),
                                 status_dir=no_status)


# ============================================================ the start spacing (gap i): what one process's limiter cannot hold

def one_process(twin: Any, allow: Any, spool: Path, clock: Any, shadow: Any, seconds: float,
                src: Any = None) -> Tuple[int, Any, Any, List[Dict[str, Any]]]:
    """One connector process on fakes, through the real entry point: an uplink, a limiter and a source of its own (a
    new process has nothing of the one before it but the spool directory, the host's clock and the far end), ended by
    SIGTERM `seconds` after it began. (its exit status, its uplink, its source, its log)"""
    fake = twin.uplink.FakeUplink(clock=clock)
    shadow.uplink, fake.on_publish = fake, shadow.on_publish                      # the service is the same for every process
    if src is None:
        src = twin.source.FakeSource(normal_values(allow))
    handlers: Dict[int, Any] = {}
    out = io.StringIO()
    began = clock.monotonic()

    def end(c: Any) -> None:
        if signal.SIGTERM in handlers and round(c.monotonic() - began, 3) >= seconds:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    clock.on_sleep.append(end)
    try:
        status = _entry(twin, allow, spool, src, fake, clock, out, handlers)()
    finally:
        clock.on_sleep.remove(end)
    return status, fake, src, [json.loads(line) for line in out.getvalue().splitlines()]


def starts_every_second(twin: Any, allow: Any, spool: Path, clock: Any, shadow: Any, count: int) -> List[Tuple[int, Any, Any, List[Dict[str, Any]]]]:
    """`count` processes on one spool directory, the k-th begun k seconds after the first: each lives a second when it
    is let in, and is begun again the moment it ended, as a restart policy or a crash loop would."""
    t0 = clock.monotonic()
    runs = []
    for k in range(count):
        clock.advance(max(round(t0 + k - clock.monotonic(), 3), 0.0))
        runs.append(one_process(twin, allow, spool, clock, shadow, 1.0))
    return runs


def shadow_times(runs: Sequence[Tuple[int, Any, Any, Any]]) -> List[float]:
    return [p.t for _status, fake, _src, _log in runs for p in fake.published if p.topic != TELEMETRY_TOPIC]


def test_twelve_starts_a_second_apart_on_one_spool_directory_are_one_start_and_eleven_refusals(twin, frozen, tmp_path, capsys):
    """The review's counterexample. The limiter is new in every process, so its windows hold nothing across starts:
    a start costs a get, a first vss document and a config report, and a stop a last document. Twelve processes a
    second apart, each well inside its own cap, were 48 shadow publishes in twelve seconds against 10 in any 300 s.
    Now a start within 120 s of the previous start on the same spool directory is refused before anything is opened."""
    L = twin.limits
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    shadow = FakeShadow(twin.uplink.FakeUplink(clock=clock))
    runs = starts_every_second(twin, frozen, tmp_path, clock, shadow, 12)
    worst = most_in_a_closed_window(shadow_times(runs))
    assert worst <= L.SHADOW_MAX_PER_WINDOW, "%d shadow publishes in one closed 300 s, from %d processes that each kept its own cap" % (
        worst, len([1 for status, _f, _s, _l in runs if status == 0]))
    assert [status for status, _fake, _src, _log in runs] == [0] + [4] * 11
    _status, first, _src, log = runs[0]
    assert [p.topic for p in first.published] == [CONFIG_GET, VSS_UPDATE, CONFIG_UPDATE, TELEMETRY_TOPIC, VSS_UPDATE]
    assert [rec["event"] for rec in log][0] == "start" and log[-1]["event"] == "stop"
    for k, (_status, fake, src, log) in enumerate(runs[1:], start=1):          # refused: nothing opened, nothing read, nothing sent
        assert (fake.connects, fake.published, fake.subscriptions, fake.closes) == (0, [], {}, 1), k
        assert (src.calls, src.reads, src.closed) == ([], 0, 1), k
        assert log == [{"event": "start-refused", "t": 1000.0 + k, "why": "spacing", "retry_after_s": 120.0 - k}], k
    stamp = tmp_path / STAMP
    assert json.loads(stamp.read_text(encoding="utf-8")) == {"started_ms": T0_MS}          # a refused start is no start: the stamp stays
    # the spacing's two ends, in whole milliseconds: 119.999 s after the previous start is refused, 120.000 s after passes
    clock.advance(round(1000.0 + L.START_SPACING_S - 0.001 - clock.monotonic(), 3))
    status, fake, _src, log = one_process(twin, frozen, tmp_path, clock, shadow, 1.0)
    assert status == 4 and fake.connects == 0 and log == [{"event": "start-refused", "t": 1119.999, "why": "spacing", "retry_after_s": 0.001}]
    clock.advance(0.001)
    status, fake, _src, log = one_process(twin, frozen, tmp_path, clock, shadow, 1.0)
    assert status == 0 and fake.connects == 1 and log[0]["event"] == "start" and len(fake.published) == 5
    assert json.loads(stamp.read_text(encoding="utf-8")) == {"started_ms": T0_MS + 1000 * L.START_SPACING_S}
    # however the connector is built: one made by hand on the same directory is refused by start() itself
    by_hand = twin.connector.build(twin.uplink.FakeUplink(clock=clock), twin.source.FakeSource({}), clock, twin.topics.Topics(THING, RULE),
                                   frozen, SCHEMA, tmp_path, io.StringIO(), status_dir=tmp_path / "no-status")
    with pytest.raises(twin.startstamp.StartRefused) as exc:
        by_hand.start()
    assert exc.value.why == "spacing" and by_hand.uplink.inner.connects == 0

    # a process that crashes is a start like any other: the one begun the moment it died is refused all the same
    class Crashing(twin.source.FakeSource):
        def latest(self) -> Dict[str, Any]:
            if self.reads >= 1:
                raise RuntimeError("the databroker went away")
            return super().latest()

    clock.advance(round(1000.0 + 2 * L.START_SPACING_S - clock.monotonic(), 3))
    status, fake, _src, log = one_process(twin, frozen, tmp_path, clock, shadow, 60.0, src=Crashing(normal_values(frozen)))
    assert status == 3 and [rec["event"] for rec in log if rec["event"] in ("start", "error", "stop")] == ["start", "error", "stop"]
    assert [p.topic for p in fake.published] == [CONFIG_GET, VSS_UPDATE, CONFIG_UPDATE, TELEMETRY_TOPIC] and clock.monotonic() == 1241.0
    status, fake, _src, log = one_process(twin, frozen, tmp_path, clock, shadow, 1.0)
    assert status == 4 and fake.connects == 0 and log == [{"event": "start-refused", "t": 1241.0, "why": "spacing", "retry_after_s": 119.0}]
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")          # a refusal is a log line and a status, never a traceback
    for _status, _fake, _src, log in runs:
        assert str(tmp_path) not in json.dumps(log) and STAMP not in json.dumps(log)          # and it names no file


def test_a_restart_loop_is_held_to_one_start_every_120_s_and_three_starts_in_any_closed_300_s(twin, frozen, tmp_path):
    """What a restart policy or a crash loop can cause on one spool directory: a process begun again every second for
    ten minutes. One start in 120 is let in, so no closed 300 s holds more than three, each with its own limiter.
    The count printed for WP5 is computed on fakes, a design value and no measurement."""
    L = twin.limits
    assert (L.START_SPACING_S, L.starts_per_window()) == (120, 3)
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    shadow = FakeShadow(twin.uplink.FakeUplink(clock=clock))
    runs = starts_every_second(twin, frozen, tmp_path, clock, shadow, 600)
    let_in = [k for k, (status, _fake, _src, _log) in enumerate(runs) if status == 0]
    assert let_in == list(range(0, 600, L.START_SPACING_S)) and {status for status, _f, _s, _l in runs} == {0, 4}
    assert most_in_a_closed_window([1000.0 + k for k in let_in]) == L.starts_per_window()
    per_cycle = [len([p for p in fake.published if p.topic != TELEMETRY_TOPIC]) for status, fake, _s, _l in runs if status == 0]
    assert set(per_cycle) == {4}                                                  # the get, the first document, the report, the last document
    worst = most_in_a_closed_window(shadow_times(runs))
    assert worst == L.starts_per_window() * 4 == 12
    print("start spacing (computed on fakes, a design value): a process begun every second for 600 s on one spool directory: %d starts "
          "let in, %d refused; at most %d shadow publishes in any closed 300 s (%d starts of 4), against %d for one process's limiter"
          % (len(let_in), 600 - len(let_in), worst, L.starts_per_window(), L.SHADOW_MAX_PER_WINDOW))


def _refused_start(twin: Any, directory: Path, wall_ms: int) -> Tuple[str, Optional[float]]:
    with pytest.raises(twin.startstamp.StartRefused) as exc:
        twin.startstamp.mark(directory, wall_ms)
    return exc.value.why, exc.value.retry_after_s


def test_the_start_stamp_is_one_field_written_by_write_then_rename_and_a_refused_start_leaves_it(twin, tmp_path):
    G, L = twin.startstamp, twin.limits
    spool = tmp_path / "spool"
    spool.mkdir()
    (tmp_path / "beside.txt").write_text("not the connector's", encoding="utf-8")
    stamp = spool / STAMP
    assert (G.FILE, G.FIELD, L.START_SPACING_S) == (STAMP, "started_ms", 120)
    FileAudit.start()
    try:
        G.mark(spool, T0_MS)                                                      # no stamp there: the first start
        first = stamp.read_bytes()
        assert _refused_start(twin, spool, T0_MS) == ("spacing", 120.0)           # the same instant again
        assert _refused_start(twin, spool, T0_MS + 1) == ("spacing", 119.999)
        assert _refused_start(twin, spool, T0_MS + 119_999) == ("spacing", 0.001)          # a millisecond short
        assert stamp.read_bytes() == first                                        # a refused start is no start: it stays
        G.mark(spool, T0_MS + 120_000)                                            # exactly 120 s after: let in
        assert _refused_start(twin, spool, T0_MS + 239_999) == ("spacing", 0.001)          # counted from the start that was let in
    finally:
        events = FileAudit.stop()
    assert first == b'{"started_ms":%d}' % T0_MS and len(first) == 28 <= L.START_STAMP_MAX_BYTES == 64
    assert stamp.read_bytes() == b'{"started_ms":%d}' % (T0_MS + 120_000) and G.encode(T0_MS) == first and G.parse(first) == T0_MS
    writes = [(e, [Path(p).name for p in paths]) for e, paths, w in events if w]
    assert writes == [("open", [".started.json.tmp"]), ("os.rename", [".started.json.tmp", STAMP])] * 2          # the two that were let in
    reads = [(e, [Path(p).name for p in paths]) for e, paths, w in events if not w]
    assert [r for r in reads if r[0] == "open" and r[1] == [STAMP]] and all(e == "open" for e, _names in reads)
    assert all(under(q, spool) for _e, paths, _w in events for q in paths)        # it reads, lists and writes nothing else
    assert sorted(q.name for q in spool.iterdir()) == [STAMP]                     # the temporary name is gone
    assert (tmp_path / "beside.txt").read_text(encoding="utf-8") == "not the connector's"
    for not_a_time in (None, "1790000000000", 1.5, True, -1):
        with pytest.raises(TypeError):
            G.mark(spool, not_a_time)


def test_a_stamp_from_the_future_and_a_file_that_is_no_stamp_are_refused_and_written_anew(twin, tmp_path):
    """To the side that keeps the spacing, and without locking the connector out for good: the start is refused, the
    stamp is written anew with this moment, and a start 120 s later passes."""
    G, L = twin.startstamp, twin.limits
    spool = tmp_path / "spool"
    spool.mkdir()
    stamp = spool / STAMP
    now = T0_MS
    stamp.write_bytes(G.encode(now + 1))                                          # a millisecond ahead: the wall clock was set back
    assert _refused_start(twin, spool, now) == ("clock", 120.0) and G.parse(stamp.read_bytes()) == now
    assert _refused_start(twin, spool, now + 119_999) == ("spacing", 0.001)
    G.mark(spool, now + 120_000)
    stamp.write_bytes(G.encode(now + 10 ** 12))                                   # decades ahead: still 120 s, not decades
    assert _refused_start(twin, spool, now + 500_000) == ("clock", 120.0)
    G.mark(spool, now + 620_000)
    no_stamps = [b"", b"{", b"[1790000000000]", b"1790000000000", b'"x"', b"null", b'{"started_ms":"1790000000000"}',
                 b'{"started_ms":1790000000000.0}', b'{"started_ms":true}', b'{"started_ms":-1}', b'{"started_ms":null}',
                 b'{"started_ms":1790000000000,"force":true}', b'{"started":1790000000000}', b"{}", b"\xff\xfe",
                 b'{"started_ms":1}' + b" " * 49, b"x" * 4096]
    assert len(no_stamps[-2]) == L.START_STAMP_MAX_BYTES + 1 and G.parse(b'{"started_ms":1}' + b" " * 48) == 1          # the cap, and one over
    t = now + 10_000_000
    for data in no_stamps:
        assert G.parse(data) is None, data
        stamp.write_bytes(data)
        assert _refused_start(twin, spool, t) == ("stamp", 120.0), data            # not read as "no previous start"
        assert G.parse(stamp.read_bytes()) == t, data                             # written anew
        t += 120_000
        G.mark(spool, t)                                                          # and 120 s later it is let in
        t += 120_000
    assert sorted(q.name for q in spool.iterdir()) == [STAMP]


def test_a_start_that_can_keep_no_stamp_is_refused_and_nothing_is_opened(twin, frozen, tmp_path, capsys):
    """No stamp, no start: a connector that cannot record its start would be one that no spacing holds."""
    absent, a_file = tmp_path / "no-such-directory", tmp_path / "a-file"
    a_file.write_text("not a directory", encoding="utf-8")
    for directory in (absent, a_file):
        assert _refused_start(twin, directory, T0_MS) == ("unwritable", None)
    assert not absent.exists() and a_file.read_text(encoding="utf-8") == "not a directory"          # it makes no directory
    is_dir = tmp_path / "stamp-is-a-directory"
    (is_dir / STAMP).mkdir(parents=True)
    assert _refused_start(twin, is_dir, T0_MS) == ("unwritable", None) and (is_dir / STAMP).is_dir()
    # Three more that are "cannot be read or written", and not "a file that is no stamp": the connector writes nothing
    # anew over what it cannot read, so each is refused at every start, with no time to wait for, until somebody takes
    # it away (startstamp.py names the three). An old, valid stamp is used: read after all, it would let the start in.
    old = twin.startstamp.encode(T0_MS - 10 ** 9)
    tmp_is_dir = tmp_path / "temporary-name-is-a-directory"
    (tmp_is_dir / twin.startstamp.TMP).mkdir(parents=True)
    (tmp_is_dir / STAMP).write_bytes(old)
    for later in (0, 10 ** 9):
        assert _refused_start(twin, tmp_is_dir, T0_MS + later) == ("unwritable", None) and (tmp_is_dir / STAMP).read_bytes() == old
    if hasattr(os, "O_NOFOLLOW"):          # POSIX, which is CI's: the stamp is opened O_NOFOLLOW and a link is never followed
        linked, elsewhere = tmp_path / "stamp-is-a-link", tmp_path / "elsewhere.json"
        linked.mkdir()
        elsewhere.write_bytes(old)
        os.symlink(str(elsewhere), str(linked / STAMP))
        for later in (0, 10 ** 9):
            assert _refused_start(twin, linked, T0_MS + later) == ("unwritable", None)
        assert (linked / STAMP).is_symlink() and elsewhere.read_bytes() == old          # not followed, not replaced, its target as it was
    if hasattr(os, "geteuid") and os.geteuid() != 0:          # a stamp nobody may read (root may read anything: nothing to hold there)
        unreadable = tmp_path / "stamp-is-unreadable"
        unreadable.mkdir()
        (unreadable / STAMP).write_bytes(old)
        os.chmod(str(unreadable / STAMP), 0)
        try:
            for later in (0, 10 ** 9):
                assert _refused_start(twin, unreadable, T0_MS + later) == ("unwritable", None)
        finally:
            os.chmod(str(unreadable / STAMP), 0o644)
        assert (unreadable / STAMP).read_bytes() == old
    # through the entry point: status 4, one log line that names no path, nothing opened, nothing on stderr
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    fake, src, out = twin.uplink.FakeUplink(clock=clock), twin.source.FakeSource(normal_values(frozen)), io.StringIO()
    clock.on_sleep.append(_raises(AssertionError("the loop began: nothing refused this start")))
    assert _entry(twin, frozen, absent, src, fake, clock, out, {})() == 4
    assert [json.loads(line) for line in out.getvalue().splitlines()] == [
        {"event": "start-refused", "t": 1000.0, "why": "unwritable", "retry_after_s": None}]
    assert (fake.connects, fake.published, fake.closes, src.calls, src.closed) == (0, [], 1, [], 1) and not absent.exists()
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "") and "no-such-directory" not in out.getvalue() and str(tmp_path) not in out.getvalue()
    assert set(twin.connector.LOG_EVENTS) == LOG_EVENTS


# ============================================================ config

def _quiet(rig: Rig, seconds: float = 5.0) -> int:
    """How many publishes, of any kind, the next `seconds` bring."""
    before = len(rig.fake.published)
    rig.run(seconds)
    return len(rig.fake.published) - before


def echo_fragments(desired: Dict[str, Any], known: Sequence[str], legitimate: Sequence[str]) -> List[str]:
    """What an echo of this desired state would have to hold, as text: each top-level key with its value, as compact
    JSON, as json.dumps spaces it and as Python prints it; each key the connector does not know, quoted; each string in
    it that is no allowlisted path, quoted. A key the connector knows and an allowlisted path are in honest traffic
    anyway and prove nothing by themselves; a key with a refused value is in none. Never empty for a state that
    names anything, whatever the length of its words."""
    out: List[str] = []
    for key, value in desired.items():
        out += ["%s:%s" % (json.dumps(key), json.dumps(value, separators=(",", ":"))), "%s: %s" % (json.dumps(key), json.dumps(value)),
                "%r: %r" % (key, value)]

    def walk(obj: Any, top: bool) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key not in legitimate and not (top and key in known):
                    out.append(json.dumps(key))
                walk(value, False)
        elif isinstance(obj, list):
            for value in obj:
                walk(value, False)
        elif isinstance(obj, str) and obj not in legitimate:
            out.append(json.dumps(obj))

    walk(desired, True)
    return out


def test_the_echo_check_looks_for_something_in_every_refused_state_and_finds_it_in_an_echo(twin, frozen):
    """The check below is only as good as what it looks for. For each refused state: it looks for something, and a
    text that did echo the state (as compact JSON, as spaced JSON, as Python prints a dict, or as any of those inside
    a JSON string, which is how a log line would carry it) holds what it looks for."""
    for desired in REFUSED_DESIRED:
        fragments = echo_fragments(desired, twin.config.KEYS, frozen.PATHS)
        assert fragments, desired
        echoes = [json.dumps(desired, separators=(",", ":")), json.dumps(desired), repr(desired)]
        echoes += [json.dumps({"event": "config", "desired": echo}) for echo in list(echoes)]
        for echo in echoes:
            assert any(f in echo or json.dumps(f)[1:-1] in echo for f in fragments), (desired, echo)
        # and nothing it looks for is in honest traffic: the report and the log line of the defaults, and of 10 Hz
        honest = "".join(twin.shadowdoc.reported(twin.shadowdoc.config_state(rate, frozen.PATHS)).decode("utf-8") for rate in (1, 10))
        honest += json.dumps({"event": "config", "paths": 16, "rate_hz": 10, "t": 1002.0}, sort_keys=True, separators=(",", ":"))
        assert not [f for f in fragments if f in honest], (desired, [f for f in fragments if f in honest])
    # the old check, words of five characters and more outside five names, looked for nothing in 16 of these 28
    old = [[w for w in strings_of(d) if len(w) >= 5 and w not in ("rate_hz", "paths", "Vehicle.Speed", "image_id", "scenario")]
           for d in REFUSED_DESIRED]
    assert (len(REFUSED_DESIRED), len([w for w in old if not w])) == (28, 16)


REFUSED_DESIRED: List[Dict[str, Any]] = [
    {"rate_hz": 5}, {"rate_hz": 0}, {"rate_hz": 100}, {"rate_hz": -1}, {"rate_hz": "10"}, {"rate_hz": 10.0}, {"rate_hz": True},
    {"rate_hz": [10]}, {"rate_hz": {"hz": 10}},
    {"paths": "*"}, {"paths": "Vehicle.Speed"}, {"paths": {"Vehicle.Speed": True}}, {"paths": 7},
    {"image_id": "hard-brake-hazard:latest"}, {"image_id": "sha256:" + "A" * 64}, {"image_id": IMAGE_ID + "\n"}, {"image_id": 7},
    {"scenario": "../etc"}, {"scenario": "a/b"}, {"scenario": "Upper-Case"}, {"scenario": SCENARIO + "\n"}, {"scenario": "x" * 49},
    {"scenario": ["a"]},
    {"bogus": "zz-unknown-key-value"}, {"widen": ["Vehicle.Speed"]}, {"interval_s": 1}, {"shadow_interval_s": 1},
    {"rate_hz": 5, "paths": "#", "image_id": "latest", "scenario": "..", "bogus": {"deep": ["zz-nested"]}},
]


@pytest.mark.parametrize("desired", REFUSED_DESIRED, ids=lambda d: json.dumps(d)[:60])
def test_a_refused_desired_value_causes_no_publish_at_all_and_is_echoed_nowhere(twin, frozen, tmp_path, desired):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(2)
    assert len(rig.reports()) == 1
    rig.shadow.cloud("config", desired)
    assert rig.shadow.deltas()[-1]["state"] == desired                            # the service did send it
    assert _quiet(rig) == 0                                                       # no report, no batch closed, nothing
    assert (rig.conn.rate_hz, rig.conn.effective) == (1, tuple(frozen.PATHS))
    assert [p.name for p in rig.spool.iterdir()] == [STAMP] and rig.conn.counters["ignored"] >= 1
    rig.shadow.cloud("config", {"rate_hz": 10})                                   # and a good value still takes effect afterwards
    rig.run(1).stop()
    assert rig.reports() == [{"rate_hz": 1, "paths": list(frozen.PATHS)}, {"rate_hz": 10, "paths": list(frozen.PATHS)}]
    everything = "".join(p.payload.decode("utf-8") for p in rig.fake.published) + rig.out.getvalue()
    fragments = echo_fragments(desired, twin.config.KEYS, frozen.PATHS)
    assert fragments, "nothing of this desired state would be looked for: the check could not fail"
    for fragment in fragments:          # as it stands, and as it would stand inside a JSON string (a log line's field)
        assert fragment not in everything and json.dumps(fragment)[1:-1] not in everything, fragment


def test_config_reported_holds_the_effective_rate_and_path_set_only(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    narrowed = [frozen.PATHS[9], frozen.PATHS[0]]
    rig.shadow.cloud("config", {"rate_hz": 10, "paths": narrowed, "image_id": IMAGE_ID, "scenario": SCENARIO, "bogus": 1})
    rig.start().run(3).stop()
    assert [json.loads(p.payload) for p in rig.at(CONFIG_UPDATE)] == [
        {"state": {"reported": {"rate_hz": 10, "paths": [frozen.PATHS[0], frozen.PATHS[9]]}}}]
    assert rig.shadow.docs["config"]["reported"] == {"rate_hz": 10, "paths": [frozen.PATHS[0], frozen.PATHS[9]]}
    # what the service still holds as different, and so repeats in every delta: nothing of it was reported
    assert rig.shadow.deltas()[-1]["state"] == {"paths": narrowed, "image_id": IMAGE_ID, "scenario": SCENARIO, "bogus": 1}
    assert twin.shadowdoc.config_state(10, (frozen.PATHS[0],)) == {"rate_hz": 10, "paths": [frozen.PATHS[0]]}
    assert twin.config.KEYS == ("rate_hz", "paths", "image_id", "scenario")


def test_n_identical_deltas_give_zero_publishes(twin, frozen, tmp_path):
    """Gap l. A delta repeats every desired attribute that still differs from reported after each accepted update. The
    image ID, the scenario, an unknown key and a refused value are never reported, so they are in every delta: a
    connector that answered each delta with a reported publish would loop until the limiter stopped it."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(2)
    desired = {"rate_hz": 10, "paths": [frozen.PATHS[1], frozen.PATHS[0]], "image_id": IMAGE_ID, "scenario": SCENARIO,
               "bogus": "zz", "interval_s": 1}
    rig.shadow.cloud("config", desired)
    rig.run(3)
    assert rig.reports() == [{"rate_hz": 1, "paths": list(frozen.PATHS)}, {"rate_hz": 10, "paths": [frozen.PATHS[0], frozen.PATHS[1]]}]
    # the fake shadow re-sent the delta after that accepted report, as the service does, and the connector stayed silent
    leftover = {k: v for k, v in desired.items() if k != "rate_hz"}          # paths too: desired's order is not the tuple's
    assert [d["state"] for d in rig.shadow.deltas()] == [desired, leftover]
    updates = len(rig.at(CONFIG_UPDATE))
    shadow_before = len([p for p in rig.fake.published if p.topic != TELEMETRY_TOPIC])
    delta = json.dumps(rig.shadow.deltas()[-1]).encode("utf-8")
    for _ in range(50):                                                           # N identical deltas, by hand
        assert rig.fake.deliver(CONFIG_DELTA, delta)
        rig.run(0.1)
    for _ in range(50):                                                           # and N more through the service's own re-send
        rig.shadow.cloud("config", {"bogus": "zz"})
        rig.run(0.1)
    assert len(rig.at(CONFIG_UPDATE)) == updates == 2
    assert len([p for p in rig.fake.published if p.topic != TELEMETRY_TOPIC]) == shadow_before
    assert rig.conn.counters["deltas"] >= 100 and rig.conn.counters["spool_written"] == 1
    assert json.loads((rig.spool / "desired.json").read_text(encoding="utf-8")) == {"image_id": IMAGE_ID, "scenario": SCENARIO}


def test_config_is_read_once_at_start_then_followed_by_its_delta_and_reported_once_per_connection(twin, frozen, tmp_path):
    # a config written while the connector was down is seen through the get (aws-map A3.5)
    rig = Rig(twin, frozen, tmp_path / "a", normal_values(frozen))
    rig.shadow.cloud("config", {"rate_hz": 10, "paths": [frozen.PATHS[0]]})
    rig.conn.start()
    assert [p.topic for p in rig.fake.published] == [CONFIG_GET] and rig.fake.published[0].payload == b""
    assert set(rig.fake.subscriptions) == set(rig.topics.subscribe) and rig.fake.connects == 1
    rig.conn.step()
    assert (rig.conn.rate_hz, rig.conn.effective) == (10, (frozen.PATHS[0],))
    assert [p.topic for p in rig.fake.published] == [CONFIG_GET, VSS_UPDATE, CONFIG_UPDATE]          # one report, after the get
    rig.run(20)
    assert len(rig.at(CONFIG_GET)) == 1 and len(rig.at(CONFIG_UPDATE)) == 1
    assert rig.log("config-get") == [{"event": "config-get", "outcome": "accepted", "t": 1000.0}]
    # no shadow yet (the first connection ever): get/rejected, and the defaults are reported
    fresh = Rig(twin, frozen, tmp_path / "b", normal_values(frozen)).start()
    assert fresh.reports() == [{"rate_hz": 1, "paths": list(frozen.PATHS)}] and fresh.log("config-get")[0]["outcome"] == "rejected"
    # no answer at all: the connector waits its bound, sends nothing meanwhile, then goes on with the defaults
    mute = Rig(twin, frozen, tmp_path / "c", normal_values(frozen), shadow=False).start()
    mute.run(twin.limits.CONFIG_GET_WAIT_S - 0.1)
    assert [p.topic for p in mute.fake.published] == [CONFIG_GET] and mute.src.calls == []
    mute.run(0.1)
    assert [p.topic for p in mute.fake.published] == [CONFIG_GET, VSS_UPDATE, CONFIG_UPDATE] and mute.src.calls == [tuple(frozen.PATHS)]
    assert mute.log("config-get")[0]["outcome"] == "timeout" and twin.limits.CONFIG_GET_WAIT_S == 5.0
    # an answer that comes late is still applied
    late = {"state": {"desired": {"rate_hz": 10}}, "version": 3, "timestamp": 1}
    assert mute.fake.deliver(CONFIG_GET + "/accepted", json.dumps(late).encode("utf-8"))
    mute.run(0.2)
    assert mute.conn.rate_hz == 10 and [r["rate_hz"] for r in mute.reports()] == [1, 10]
    # a new connection (the uplink resumed): the config is read again and reported once more, and no more than that
    rig.shadow.cloud("config", {"rate_hz": 1})
    rig.run(1)
    assert len(rig.at(CONFIG_UPDATE)) == 2
    rig.fake.resume()
    rig.run(30)
    assert len(rig.at(CONFIG_GET)) == 2 and len(rig.at(CONFIG_UPDATE)) == 3
    assert rig.reports()[-1] == {"rate_hz": 1, "paths": [frozen.PATHS[0]]}
    assert len(rig.log("config-get")) == 1          # the line is the start's: the answer to a later connection's get is applied and logs none


def test_a_delta_that_overtakes_the_gets_answer_does_not_leave_the_get_unanswered(twin, frozen, tmp_path):
    """The review's counterexample: the cloud writes `config` between the subscription and the get, and the delta
    (version 8) reaches the device before the get's answer (version 7). The answer is older than what was applied, so
    it is not applied; but it IS the answer to the get. Read as a mere stale message, it left the connector waiting
    its whole bound with nothing sampled or sent, though the service had answered, and the log said "timeout"."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen), shadow=False)
    rig.conn.start()
    delta = {"state": {"rate_hz": 10}, "metadata": {}, "version": 8, "timestamp": 1}
    answer = {"state": {"desired": {"rate_hz": 1, "paths": [frozen.PATHS[0]]}}, "metadata": {}, "version": 7, "timestamp": 1}
    assert rig.fake.deliver(CONFIG_DELTA, json.dumps(delta).encode("utf-8"))
    assert rig.fake.deliver(CONFIG_GET + "/accepted", json.dumps(answer).encode("utf-8"))
    rig.conn.step()
    assert rig.log("config-get") == [{"event": "config-get", "outcome": "accepted", "t": 1000.0}], "the get was answered"
    assert [p.topic for p in rig.fake.published] == [CONFIG_GET, VSS_UPDATE, CONFIG_UPDATE]          # at once, not 5 s later
    # the older state is not applied over the newer one: the delta's rate holds, and the answer's narrowing is not taken
    assert (rig.conn.rate_hz, rig.conn.effective) == (10, tuple(frozen.PATHS)) and rig.conn.counters["stale"] == 1
    assert rig.reports() == [{"rate_hz": 10, "paths": list(frozen.PATHS)}] and rig.src.calls == [tuple(frozen.PATHS)]
    rig.run(twin.limits.CONFIG_GET_WAIT_S + 1)
    assert len(rig.log("config-get")) == 1 and len(rig.at(CONFIG_GET)) == 1          # and no time-out follows
    # a stale answer after the get was answered is a late duplicate and nothing more
    assert rig.fake.deliver(CONFIG_GET + "/accepted", json.dumps(answer).encode("utf-8"))
    rig.run(0.2)
    assert rig.conn.counters["stale"] == 2 and (rig.conn.rate_hz, rig.conn.effective) == (10, tuple(frozen.PATHS))
    # and a delta alone is no answer to the get: it is applied, and nothing is sampled or sent until the get is answered
    # or its wait is over
    alone = Rig(twin, frozen, tmp_path / "alone", normal_values(frozen), shadow=False)
    alone.conn.start()
    assert alone.fake.deliver(CONFIG_DELTA, json.dumps(delta).encode("utf-8"))
    alone.run(twin.limits.CONFIG_GET_WAIT_S - 0.1)
    assert (alone.conn.rate_hz, alone.conn.counters["deltas"], alone.log("config-get")) == (10, 1, [])
    assert (alone.src.calls, alone.src.reads, [p.topic for p in alone.fake.published]) == ([], 0, [CONFIG_GET])
    alone.run(0.1)                                                                # the wait is over: on with what the delta said
    assert alone.log("config-get")[0]["outcome"] == "timeout" and alone.src.calls == [tuple(frozen.PATHS)]
    assert alone.reports() == [{"rate_hz": 10, "paths": list(frozen.PATHS)}]


def test_a_report_the_limiter_held_back_is_sent_when_it_may_be_and_the_device_and_the_shadow_meet_again(twin, frozen, tmp_path):
    """A delta names only what differs from REPORTED. While the limiter holds the reports back, reported is behind:
    if desired then returns to that stale value, the service sends no delta at all and the device keeps the newer
    setting it had applied. It still owes its report, sends it when the limiter allows, and the delta that answers it
    brings the two together. Nothing here loops, and nothing is queued."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(1)
    for i in range(12):                                                           # the config flaps faster than 10 reports in 300 s
        rig.shadow.cloud("config", {"rate_hz": 1 if i % 2 else 10})
        rig.run(1.1)
    assert rig.conn.counters["refused_config"] >= 1 and len(rig.at(CONFIG_UPDATE)) < 12
    held_at = rig.shadow.docs["config"]["reported"]["rate_hz"]
    device = 1 if held_at == 10 else 10
    rig.shadow.cloud("config", {"rate_hz": device})                               # the device takes this one, and cannot report it
    rig.run(1.1)
    assert rig.conn.rate_hz == device and rig.shadow.docs["config"]["reported"]["rate_hz"] == held_at
    deltas = len(rig.shadow.deltas())
    rig.shadow.cloud("config", {"rate_hz": held_at})                              # desired is what reported still says: no delta
    rig.run(5)
    assert len(rig.shadow.deltas()) == deltas and rig.conn.rate_hz == device      # the device was not told
    before = len(rig.at(CONFIG_UPDATE))
    rig.run(300)                                                                  # the window moves on
    assert rig.conn.rate_hz == held_at == rig.shadow.docs["config"]["reported"]["rate_hz"]
    assert [r["rate_hz"] for r in rig.reports()[before:]] == [device, held_at]    # its overdue report, the delta's answer, and no more
    times = [p.t for p in rig.fake.published if p.topic != TELEMETRY_TOPIC]
    assert most_in_a_closed_window(times) <= twin.limits.SHADOW_MAX_PER_WINDOW


def test_a_resumed_connection_takes_the_whole_desired_state_anew(twin, frozen, tmp_path):
    """A session starts clean, so a resumed connection is a new one as far as the shadows go, and what the cloud did
    meanwhile is in the answer to its get. A desired key that was removed is absent there, and absent in the whole
    state means the default: no delta could ever say so. The shadow may have been deleted and made anew, so its
    version starts again and the old connection's highest version must not make the answer look stale."""
    everything, narrowed = tuple(frozen.PATHS), (frozen.PATHS[1], attr.WHEELBASE)
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(1)
    rig.shadow.cloud("config", {"rate_hz": 10, "paths": list(narrowed)})
    rig.run(1)
    assert (rig.conn.rate_hz, rig.conn.effective) == (10, narrowed)
    # the cloud removes both keys: desired now equals nothing, so the service sends no delta and the device is not told
    deltas = len(rig.shadow.deltas())
    rig.shadow.cloud("config", {"rate_hz": None, "paths": None})
    rig.run(5)
    assert rig.shadow.docs["config"]["desired"] == {} and len(rig.shadow.deltas()) == deltas
    assert (rig.conn.rate_hz, rig.conn.effective) == (10, narrowed)
    rig.fake.resume()                                                             # the next connection reads the whole state
    rig.run(1)
    assert (rig.conn.rate_hz, rig.conn.effective) == (1, everything)              # a key the whole state does not name: the default
    assert rig.reports()[-1] == {"rate_hz": 1, "paths": list(everything)} and len(rig.at(CONFIG_GET)) == 2
    assert rig.src.calls == [everything, narrowed, everything]
    # narrowed again, by a delta whose version is well above anything a new shadow starts with
    rig.shadow.cloud("config", {"paths": list(narrowed)})
    rig.run(1)
    old = rig.shadow.docs["config"]["version"]
    assert rig.conn.effective == narrowed and old >= 5 and rig.conn.counters["stale"] == 0
    # while the connection is down the shadow is deleted and made anew: version 1, another desired state
    rig.shadow.docs["config"] = {"desired": {"rate_hz": 10}, "reported": {}, "version": 1}
    rig.fake.resume()
    rig.run(1)
    assert (rig.conn.rate_hz, rig.conn.effective) == (10, everything) and rig.conn.counters["stale"] == 0
    assert rig.reports()[-1] == {"rate_hz": 10, "paths": list(everything)} and len(rig.at(CONFIG_GET)) == 3
    assert rig.conn.counters["resumed"] == 2 and rig.shadow.docs["config"]["reported"] == rig.reports()[-1]


def test_a_resumed_connection_sends_the_vss_document_again_though_no_value_changed(twin, frozen, tmp_path):
    """Whatever the shadow held when the connection came back, the document that follows makes it whole: the change
    rule compares with the last document of this connection, and a new connection has none."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(70)
    assert rig.times(VSS_UPDATE) == [0.0]                                          # nothing changed: one document
    rig.shadow.docs["vss"]["reported"].clear()                                    # the shadow lost it meanwhile
    rig.fake.resume()
    rig.run(1)
    assert rig.times(VSS_UPDATE) == [0.0, 71.0] and rig.vss()[1] == rig.vss()[0]  # at the next tick, the same values
    assert set(rig.shadow.docs["vss"]["reported"]) == set(frozen.PATHS)
    rig.run(10)
    rig.fake.resume()                                                             # a new connection 10 s after a document:
    rig.run(49.9)
    assert len(rig.vss()) == 2                                                    # the 60 s floor holds for it too
    rig.run(0.1)
    assert rig.times(VSS_UPDATE) == [0.0, 71.0, 131.0]
    rig.run(100)
    assert len(rig.vss()) == 3 and rig.conn.counters["resumed"] == 2              # once per connection, then on change again
    assert len(rig.at(CONFIG_GET)) == 3 and len(rig.reports()) == 3 and rig.conn.counters["refused_vss"] == 0


def test_a_config_get_the_limiter_refused_is_asked_again_when_the_window_allows(twin, frozen, tmp_path):
    """Read once per connection means once it could be read. A get the limiter refused was never sent: it stays due,
    is not tried again before the moment the limiter named, and goes then."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(1)
    for i in range(7):          # seven reports: with the get, the first document and the first report, the window's ten
        rig.shadow.cloud("config", {"rate_hz": 1 if i % 2 else 10})
        rig.run(1)
    counters = rig.conn.counters
    assert len([p for p in rig.fake.published if p.topic != TELEMETRY_TOPIC]) == 10 == twin.limits.SHADOW_MAX_PER_WINDOW
    assert counters["refused_get"] == counters["refused_config"] == counters["refused_vss"] == 0
    rig.shadow.cloud("config", {"rate_hz": None})                                 # removed in the cloud: only a get will tell
    rig.fake.resume()                                                             # a new connection, and no room for its get
    rig.run(200)
    assert len(rig.at(CONFIG_GET)) == 1 and counters["refused_get"] == 1          # refused once, then not tried before its time
    assert rig.conn.rate_hz == 10
    rig.run(100)                                                                  # the window moves on: the get goes, and is answered
    assert len(rig.at(CONFIG_GET)) == 2 and counters["refused_get"] == 1 and counters["sent_get"] == 2
    assert rig.conn.rate_hz == 1 and rig.reports()[-1]["rate_hz"] == 1
    assert most_in_a_closed_window([p.t for p in rig.fake.published if p.topic != TELEMETRY_TOPIC]) <= twin.limits.SHADOW_MAX_PER_WINDOW


def test_a_spool_request_in_the_answer_to_the_get_is_written_without_a_delta(twin, frozen, tmp_path):
    """The service repeats a spool request in the delta that follows the first accepted report, which would hide a
    connector that took it from deltas only. Here nothing follows the answer."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen), shadow=False)
    rig.conn.start()
    answer = {"state": {"desired": {"image_id": IMAGE_ID, "scenario": SCENARIO, "rate_hz": 10}}, "version": 4, "timestamp": 1}
    assert rig.fake.deliver(CONFIG_GET + "/accepted", json.dumps(answer).encode("utf-8"))
    rig.conn.step()
    assert json.loads((rig.spool / "desired.json").read_text(encoding="utf-8")) == {"image_id": IMAGE_ID, "scenario": SCENARIO}
    assert rig.conn.rate_hz == 10 and rig.conn.counters["spool_written"] == 1 and rig.conn.counters["deltas"] == 0
    assert [(rec["ok"], rec["image_id"], rec["scenario"]) for rec in rig.log("spool")] == [(True, True, True)]


def test_a_full_desired_state_without_a_key_means_the_default_and_a_delta_without_it_means_no_change(twin, frozen):
    C = twin.config.Config(frozen.PATHS)
    assert (C.rate_hz, C.paths) == (1, tuple(frozen.PATHS))
    out = C.apply({"rate_hz": 10, "paths": [frozen.PATHS[3]]}, full=False)
    assert (out.changed, out.ignored, out.spool) == (True, 0, None) and (C.rate_hz, C.paths) == (10, (frozen.PATHS[3],))
    out = C.apply({"image_id": IMAGE_ID}, full=False)                              # a delta: what it does not name stays
    assert (out.changed, out.spool) == (False, {"image_id": IMAGE_ID, "scenario": None}) and C.rate_hz == 10
    out = C.apply({"scenario": SCENARIO, "image_id": "latest"}, full=False)       # each field on its own
    assert (out.changed, out.ignored, out.spool) == (False, 1, {"image_id": None, "scenario": SCENARIO})
    out = C.apply({"image_id": "latest", "scenario": "../etc"}, full=False)
    assert (out.changed, out.ignored, out.spool) == (False, 2, None)
    out = C.apply({"rate_hz": 7, "paths": "all"}, full=True)                       # refused values change nothing, full state or not
    assert (out.changed, out.ignored) == (False, 2) and (C.rate_hz, C.paths) == (10, (frozen.PATHS[3],))
    out = C.apply({}, full=True)                                                  # the whole desired state, naming nothing: the defaults
    assert out.changed and (C.rate_hz, C.paths) == (1, tuple(frozen.PATHS))
    for not_an_object in (None, [], "x", 7):
        out = C.apply(not_an_object, full=False)
        assert (out.changed, out.ignored, out.spool) == (False, 1, None)


def test_a_stale_an_oversized_and_a_garbled_config_message_change_nothing(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(1)

    def delta(state, version):
        return json.dumps({"state": state, "metadata": {}, "version": version, "timestamp": 1}).encode("utf-8")

    assert rig.fake.deliver(CONFIG_DELTA, delta({"rate_hz": 10}, 9))
    rig.run(0.5)
    assert rig.conn.rate_hz == 10
    assert rig.fake.deliver(CONFIG_DELTA, delta({"rate_hz": 1}, 8))                # older than what was applied: a late duplicate
    assert rig.fake.deliver(CONFIG_DELTA, b"{not json")
    assert rig.fake.deliver(CONFIG_DELTA, b'["a list"]')
    assert rig.fake.deliver(CONFIG_DELTA, b'{"state": "no object"}')
    assert rig.fake.deliver(CONFIG_DELTA, b"\xff\xfe")
    big = delta({"rate_hz": 1, "pad": "x" * twin.limits.INBOUND_MAX_BYTES}, 10)
    assert len(big) > twin.limits.INBOUND_MAX_BYTES == 32768 and rig.fake.deliver(CONFIG_DELTA, big)
    rig.run(0.5)
    assert rig.conn.rate_hz == 10 and rig.conn.counters["stale"] == 1 and rig.conn.counters["bad_messages"] == 5
    # the service refusing an update is counted, by its code and never by its text, and nothing is sent in answer
    before = len(rig.fake.published)
    for name in ("vss", "config"):
        rejected = json.dumps({"code": 413, "message": "payload too large for example-thing"}).encode("utf-8")
        assert rig.fake.deliver(SHADOW_PREFIX + name + "/update/rejected", rejected)
    rig.run(0.5)
    assert rig.conn.counters["rejected_vss"] == 1 and rig.conn.counters["rejected_config"] == 1
    assert [p.topic for p in rig.fake.published[before:]] == [] and "too large" not in rig.out.getvalue()
    # the inbox is bounded: a flood between two steps drops the oldest and is counted
    applied = rig.conn.counters["deltas"]
    for v in range(100):
        rig.fake.deliver(CONFIG_DELTA, delta({"rate_hz": 1 if v % 2 else 10}, 100 + v))
    rig.run(0.1)
    assert rig.conn.counters["inbox_overflow"] == 100 - twin.limits.INBOX_MAX and rig.conn.rate_hz == 1
    assert rig.conn.counters["deltas"] - applied == twin.limits.INBOX_MAX == 32          # the last 32; the rest were dropped unread


# ============================================================ a shadow publish the uplink failed (not one the limiter refused)

def fail_between(rig: Rig, start: float, end: float) -> List[Tuple[float, str]]:
    """From now on the far end fails every publish made while the rig's clock stands in [start, end): the uplink
    raises, with a text that names everything. Returns the list each such attempt is added to, (the rig's time, the
    topic): what was tried and failed, which fake.published does not hold."""
    attempts: List[Tuple[float, str]] = []

    def fail(topic: str, payload: bytes) -> Optional[str]:
        now = rig.now()
        if start <= now < end:
            attempts.append((now, topic))
            return "publish to %s timed out: %s" % (topic, SECRET)
        return None

    rig.fake.fail_publish = fail
    return attempts


def shadow_tries(rig: Rig, attempts: Sequence[Tuple[float, str]]) -> List[float]:
    """When anything was tried on a shadow topic, the rig's time: what the far end took, and what it failed."""
    return sorted([t for t, topic in attempts if topic != TELEMETRY_TOPIC] + [t for topic in (CONFIG_GET, VSS_UPDATE, CONFIG_UPDATE)
                                                                             for t in rig.times(topic)])


def _moving(rig: Rig) -> None:
    rig.src.set(rig.allow.PATHS[1], 10.0 + rig.now())                             # a value that changes at every step: a document is always due


@pytest.mark.parametrize("before, after", [(1, 10), (10, 1)])
def test_a_config_report_the_uplink_failed_is_tried_again_one_spacing_later_and_does_not_use_up_the_shadow_window(
        twin, frozen, tmp_path, before, after):
    """The re-check's counterexample. The far end fails every publish from 65 to 75 s, and at 66 s the cloud changes
    the rate. The report of the new rate fails. Tried again at every step of the loop, as it was, it failed six times
    in half a second; with the four shadow publishes before it that was the limiter's ten (an attempt the uplink
    failed keeps its place in the window), and once the far end was back nothing went to a shadow topic until the
    window freed: no document at 120 or 180 s, none at the stop, and the new rate never reported though the connector
    ran at it. Now nothing is tried on a shadow topic for SHADOW_RETRY_S after a shadow publish the uplink failed:
    one attempt, the report and the next document one spacing later, the stop's document, and nothing refused."""
    L = twin.limits
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    if before != L.DEFAULT_RATE_HZ:
        rig.shadow.cloud("config", {"rate_hz": before})
    rig.start()
    attempts = fail_between(rig, 65.0, 75.0)
    rig.run(66, each=_moving)
    assert rig.times(VSS_UPDATE) == [0.0, 60.0] and rig.times(CONFIG_UPDATE) == [0.0] and rig.conn.rate_hz == before
    rig.shadow.cloud("config", {"rate_hz": after})                                # 66 s: the delta is taken at the next step
    rig.run(134, each=_moving).stop()                                             # on to 200 s, and the stop
    assert [t for t, topic in attempts if topic == CONFIG_UPDATE] == [66.1], "a report the uplink failed was tried again inside the spacing"
    assert [topic for _t, topic in attempts if topic != CONFIG_UPDATE] == [TELEMETRY_TOPIC]          # the batch the change closed, at 66.1 s
    again = round(66.1 + L.SHADOW_RETRY_S, 3)
    assert rig.times(CONFIG_UPDATE) == [0.0, again], "the failed report was not sent when the spacing was over"
    assert rig.reports()[-1]["rate_hz"] == after == rig.conn.rate_hz              # the rate it runs at is the rate it reported
    assert rig.times(VSS_UPDATE) == [0.0, 60.0, again, round(again + L.SHADOW_MIN_INTERVAL_S, 3), 200.0]          # the next documents, and the stop's
    counters = rig.conn.counters
    assert (counters["failed_config"], counters["sent_config"], counters["sent_vss"], counters["failed_telemetry"]) == (1, 2, 5, 1)
    assert counters["refused_config"] == counters["refused_vss"] == counters["refused_get"] == 0
    assert rig.conn.uplink.counters == {}, "the limiter refused something: the failed attempts used up its window"
    tried = shadow_tries(rig, attempts)
    assert len(tried) == 9 and most_in_a_closed_window(tried) == 9 < L.SHADOW_MAX_PER_WINDOW
    failed = rig.log("publish-failed")
    assert sorted(rec["what"] for rec in failed) == ["config", "telemetry"] and all(rec["error"] == "UplinkError" for rec in failed)
    for word in SECRET_WORDS + ("$aws", "timed out"):
        assert word not in rig.out.getvalue(), word


def test_after_a_vss_document_the_uplink_failed_nothing_is_tried_on_a_shadow_topic_for_the_spacing(twin, frozen, tmp_path, monkeypatch):
    """Any shadow publish, not the report alone: the document due at 60 s fails, and a report that becomes due two
    seconds later (the far end is fine again) is not tried before the spacing is over either. One attempt a spacing,
    whatever is due. The failed document is not sent again as it was: the one that goes at 120 s is made then."""
    L = twin.limits
    rig = Rig(twin, frozen, tmp_path / "a", normal_values(frozen)).start()
    attempts = fail_between(rig, 59.5, 60.5)
    rig.run(62, each=_moving)
    assert attempts == [(60.0, VSS_UPDATE)] and rig.times(TELEMETRY_TOPIC) == [59.0]
    rig.shadow.cloud("config", {"rate_hz": 10})                                   # 62 s: a report is due from the next step on
    rig.run(57.9, each=_moving)                                                   # to 119.9 s
    assert rig.conn.rate_hz == 10 and rig.times(CONFIG_UPDATE) == [0.0] and rig.times(VSS_UPDATE) == [0.0], "tried inside the spacing"
    assert rig.times(TELEMETRY_TOPIC)[:3] == [59.0, 62.1, 72.0]                   # telemetry is not held: its batches went on
    rig.run(0.1, each=_moving)                                                    # 120.0 s: 60.0 + SHADOW_RETRY_S
    assert rig.times(VSS_UPDATE) == [0.0, 120.0] and rig.times(CONFIG_UPDATE) == [0.0, 120.0] and L.SHADOW_RETRY_S == 60
    assert rig.vss()[-1][frozen.PATHS[1]] == 10.0 + 120.0                         # the values of 120 s, not the failed document's
    rig.run(65, each=_moving).stop()
    assert rig.times(VSS_UPDATE) == [0.0, 120.0, 180.0, 185.0] and len(attempts) == 1 and rig.conn.uplink.counters == {}
    assert (rig.conn.counters["failed_vss"], rig.conn.counters["refused_vss"], rig.conn.counters["refused_config"]) == (1, 0, 0)
    # the stop does not wait for the spacing: its last document goes, ten seconds after the one that failed
    rig = Rig(twin, frozen, tmp_path / "stop", normal_values(frozen)).start()
    attempts = fail_between(rig, 59.5, 60.5)
    rig.run(70, each=_moving).stop()
    assert attempts == [(60.0, VSS_UPDATE)] and rig.times(VSS_UPDATE) == [0.0, 70.0] and rig.vss()[-1][frozen.PATHS[1]] == 80.0
    # The document's own 60 s is counted from its last try, sent or not, and is no part of the spacing. To tell the two
    # apart, the spacing is 10 s for this run: the report goes when the spacing is over, the failed document waits its 60 s.
    monkeypatch.setattr(L, "SHADOW_RETRY_S", 10)
    rig = Rig(twin, frozen, tmp_path / "b", normal_values(frozen)).start()
    attempts = fail_between(rig, 59.5, 60.5)
    rig.run(62, each=_moving)
    rig.shadow.cloud("config", {"rate_hz": 10})
    rig.run(58, each=_moving)
    assert attempts == [(60.0, VSS_UPDATE)] and rig.times(CONFIG_UPDATE) == [0.0, 70.0]
    assert rig.times(VSS_UPDATE) == [0.0, 120.0], "a document the uplink failed was tried again before its 60 s were over"


def test_a_vss_document_the_limiter_refused_waits_its_60_s_from_that_try_and_is_refused_once(twin, frozen, tmp_path):
    """The limiter's side of the same rule, which no test held: a document the limiter refused is not tried again at
    the next tick, though the moment the limiter named is a millisecond away. Ten shadow publishes stand in the
    window when the document of 300 s is due, three of them exactly 300 s old (the closed window still holds them)."""
    L = twin.limits
    narrowed = [p for p in frozen.PATHS if p != frozen.PATHS[0]]
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(241, each=_moving)
    for paths in (narrowed, list(frozen.PATHS), narrowed):                        # three reports, two seconds apart
        rig.shadow.cloud("config", {"paths": paths})
        rig.run(2, each=_moving)
    assert rig.times(VSS_UPDATE) == [0.0, 60.0, 120.0, 180.0, 240.0] and rig.times(CONFIG_UPDATE) == [0.0, 241.1, 243.1, 245.1]
    assert len(shadow_tries(rig, [])) == L.SHADOW_MAX_PER_WINDOW == 10            # with the get: the window's ten
    rig.run(53, each=_moving)                                                     # 300.0 s: the document is due, and refused
    assert rig.now() == 300.0 and rig.conn.counters["refused_vss"] == 1 and len(rig.vss()) == 5
    rig.run(59.9, each=_moving)                                                   # the window had room again from 300.001 s on
    assert rig.times(VSS_UPDATE)[-1] == 240.0 and rig.conn.counters["refused_vss"] == 1, "tried again before its 60 s were over"
    rig.run(0.1, each=_moving)
    assert rig.times(VSS_UPDATE) == [0.0, 60.0, 120.0, 180.0, 240.0, 360.0] and rig.conn.uplink.counters == {"refused_window": 1}
    assert most_in_a_closed_window(shadow_tries(rig, [])) == L.SHADOW_MAX_PER_WINDOW


def test_a_config_get_the_uplink_failed_stays_due_and_is_asked_again_one_spacing_later(twin, frozen, tmp_path):
    """Read once per connection means once it could be read. A get the uplink failed was dropped for good, as it was:
    logged, then the wait's time-out, and a `config` written while the connector was down was never read on that
    connection. Now it stays due and is asked again, one attempt a spacing, and nothing else is tried on a shadow
    topic meanwhile. Here the far end fails every publish for the first 130 s."""
    L = twin.limits
    rig = Rig(twin, frozen, tmp_path / "first", normal_values(frozen))
    rig.shadow.cloud("config", {"rate_hz": 10})                                   # written while the connector was down: only the get will tell
    attempts = fail_between(rig, 0.0, 130.0)
    rig.start().run(179.9, each=_moving)
    assert [a for a in attempts if a[1] != TELEMETRY_TOPIC] == [(0.0, CONFIG_GET), (60.0, CONFIG_GET), (120.0, CONFIG_GET)], \
        "a get the uplink failed is asked again once a spacing, and nothing else is tried on a shadow topic meanwhile"
    tried = shadow_tries(rig, attempts)                                           # nothing was sent yet: these are the failed ones
    assert tried == [0.0, 60.0, 120.0] and smallest_gap_ms(tried) == 1000 * L.SHADOW_RETRY_S
    # meanwhile it went on with the defaults once the get's wait was over, and sampled; its two batches failed with the rest
    assert rig.log("config-get") == [{"event": "config-get", "outcome": "timeout", "t": 1000.0 + L.CONFIG_GET_WAIT_S}]
    assert rig.conn.rate_hz == 1 and rig.src.calls == [tuple(frozen.PATHS)]
    assert [a for a in attempts if a[1] == TELEMETRY_TOPIC] == [(64.0, TELEMETRY_TOPIC), (124.0, TELEMETRY_TOPIC)]
    rig.run(0.1, each=_moving)                                                    # 180.0 s: the far end is back, and the get goes
    assert rig.times(CONFIG_GET) == [180.0] and rig.times(VSS_UPDATE) == [180.0] and rig.times(CONFIG_UPDATE) == [180.0]
    assert rig.conn.rate_hz == 10 and rig.reports() == [{"rate_hz": 10, "paths": list(frozen.PATHS)}]          # what the cloud had written
    assert len(rig.log("config-get")) == 1 and "connect-failed" not in [rec["event"] for rec in rig.log()]
    # a batch the uplink failed is dropped, not sent again: the first one that went is the third, with its own rows only
    assert [(b["batch"], len(b["rows"]), b["rows"][0][0]) for b in rig.telemetry()] == [(3, 55, T0_MS + 125_000)]
    rig.run(65, each=_moving).stop()
    assert rig.times(VSS_UPDATE) == [180.0, 240.0, 245.0]                         # the next document, and the stop's
    counters = rig.conn.counters
    assert (counters["failed_get"], counters["sent_get"], counters["refused_get"], counters["failed_telemetry"]) == (3, 1, 0, 2)
    assert rig.conn.uplink.counters == {} and most_in_a_closed_window(shadow_tries(rig, attempts)) == 8 < L.SHADOW_MAX_PER_WINDOW
    assert [rec["what"] for rec in rig.log("publish-failed")] == ["get", "get", "telemetry", "get", "telemetry"]
    # a new connection whose get fails (the far end fails for ten seconds while it is due): the same
    again = Rig(twin, frozen, tmp_path / "resumed", normal_values(frozen)).start().run(1, each=_moving)
    again.shadow.cloud("config", {"rate_hz": 10})
    again.run(1, each=_moving)
    again.shadow.cloud("config", {"rate_hz": None})                               # removed in the cloud: no delta says so, only a get
    attempts = fail_between(again, 100.0, 110.0)
    again.run(98, each=_moving)
    again.fake.resume()                                                           # 100 s: a new connection
    again.run(60, each=_moving)
    assert [a for a in attempts if a[1] != TELEMETRY_TOPIC] == [(100.1, CONFIG_GET)] and again.times(CONFIG_GET) == [0.0]
    assert again.conn.rate_hz == 10 and again.times(VSS_UPDATE) == [0.0, 60.0] and again.times(CONFIG_UPDATE) == [0.0, 1.1]
    again.run(0.1, each=_moving)                                                  # 160.1 s: one spacing after the failed get
    assert again.times(CONFIG_GET) == [0.0, 160.1] and again.conn.rate_hz == 1 and again.reports()[-1]["rate_hz"] == 1
    assert again.times(VSS_UPDATE) == [0.0, 60.0, 160.1] and again.times(CONFIG_UPDATE) == [0.0, 1.1, 160.1]
    again.run(4.9, each=_moving).stop()
    assert again.times(VSS_UPDATE)[-1] == 165.0 and again.conn.uplink.counters == {} and again.conn.counters["failed_get"] == 1


def test_one_kind_of_shadow_publish_that_alone_fails_every_time_ends_each_steps_shadow_publishes_where_it_stands(twin, frozen, tmp_path):
    """What the spacing does not mend, held as it is so that the docstring's sentence is no guess. The order in a step
    is the get, the document, the report, and the first that fails ends that step's shadow publishes. So a far end
    that fails the get alone, every time, sees neither a document nor a report tried (but the stop's document); one
    that fails the document alone sees no report; one that fails the report alone keeps nothing back. An uplink
    fails a connection, not one topic, as far as is known: whether a real one can do this is WP3's to look at."""
    L = twin.limits

    def only(rig: Rig, topic: str) -> List[float]:
        tried: List[float] = []

        def fail(t: str, payload: bytes) -> Optional[str]:
            if t != topic:
                return None
            tried.append(rig.now())
            return "publish to %s: %s" % (t, SECRET)

        rig.fake.fail_publish = fail
        return tried

    rig = Rig(twin, frozen, tmp_path / "get", normal_values(frozen))
    tried = only(rig, CONFIG_GET)
    rig.start().run(200, each=_moving).stop()
    assert tried == [0.0, 60.0, 120.0, 180.0] and rig.times(VSS_UPDATE) == [200.0] and rig.at(CONFIG_UPDATE) == []
    assert rig.times(TELEMETRY_TOPIC) == [64.0, 124.0, 184.0, 200.0] and rig.conn.uplink.counters == {}          # telemetry is not held
    rig = Rig(twin, frozen, tmp_path / "vss", normal_values(frozen))
    tried = only(rig, VSS_UPDATE)
    rig.start().run(200, each=_moving).stop()
    assert tried == [0.0, 60.0, 120.0, 180.0, 200.0] and rig.times(CONFIG_GET) == [0.0] and rig.at(CONFIG_UPDATE) == []
    rig = Rig(twin, frozen, tmp_path / "config", normal_values(frozen))
    tried = only(rig, CONFIG_UPDATE)
    rig.start().run(200, each=_moving).stop()
    assert tried == [0.0, 60.0, 120.0, 180.0] and rig.times(VSS_UPDATE) == [0.0, 60.0, 120.0, 180.0, 200.0]
    # its failed attempts and the documents share the window's ten: here they are exactly ten, and nothing was refused
    assert len(tried) + len(rig.at(VSS_UPDATE)) + len(rig.at(CONFIG_GET)) == L.SHADOW_MAX_PER_WINDOW and rig.conn.uplink.counters == {}


# ============================================================ the spool

def test_the_spool_record_is_two_fields_and_its_form_is_checked(twin):
    S = twin.spool
    assert S.FIELDS == ("image_id", "scenario") and S.FILE == "desired.json"
    good = [(IMAGE_ID, None), (None, SCENARIO), (IMAGE_ID, SCENARIO), (None, "a"), (None, "0" * 48), ("sha256:" + "0123456789abcdef" * 4, None)]
    for image_id, scenario in good:
        rec = S.record(image_id, scenario)
        assert S.problems(rec) == [] and json.loads(S.encode(rec)) == {"image_id": image_id, "scenario": scenario}
    bad = [
        ({"image_id": None, "scenario": None}, "both"),                           # both null
        ({"image_id": IMAGE_ID, "scenario": None, "force": True}, "fields"),      # a third field
        ({"image_id": IMAGE_ID}, "fields"), ({"scenario": SCENARIO}, "fields"), ({}, "fields"),
        ({"image_id": "hard-brake-hazard:latest", "scenario": None}, "image_id"),          # a tag instead of an ID
        ({"image_id": "sha256:" + "1" * 63, "scenario": None}, "image_id"),
        ({"image_id": "sha256:" + "1" * 65, "scenario": None}, "image_id"),
        ({"image_id": "sha256:" + "A" * 64, "scenario": None}, "image_id"),
        ({"image_id": "SHA256:" + "1" * 64, "scenario": None}, "image_id"),
        ({"image_id": IMAGE_ID + "\n", "scenario": None}, "image_id"),            # Python's $ would let this one through
        ({"image_id": 7, "scenario": None}, "image_id"),
        ({"image_id": None, "scenario": "../etc"}, "scenario"),                   # a path as a scenario
        ({"image_id": None, "scenario": "a/b"}, "scenario"), ({"image_id": None, "scenario": "a\\b"}, "scenario"),
        ({"image_id": None, "scenario": "a.b"}, "scenario"), ({"image_id": None, "scenario": "/abs"}, "scenario"),
        ({"image_id": None, "scenario": "-leading"}, "scenario"), ({"image_id": None, "scenario": "Upper"}, "scenario"),
        ({"image_id": None, "scenario": "a b"}, "scenario"), ({"image_id": None, "scenario": ""}, "scenario"),
        ({"image_id": None, "scenario": "x" * 49}, "scenario"), ({"image_id": None, "scenario": SCENARIO + "\n"}, "scenario"),
        ({"image_id": None, "scenario": ["a"]}, "scenario"), ({"image_id": None, "scenario": True}, "scenario"),
    ]
    for rec, word in bad:
        found = S.problems(rec)
        assert found and all(word in f for f in found), (rec, found)
        with pytest.raises(S.SpoolRefused):
            S.encode(rec)
    for not_a_record in (None, [], "x", [("image_id", IMAGE_ID), ("scenario", None)]):
        assert S.problems(not_a_record)
    with pytest.raises(S.SpoolRefused):
        S.record("latest", None)
    # the largest valid record is well under the cap, and the cap is held all the same
    largest = S.encode(S.record("sha256:" + "f" * 64, "z" * 48))
    assert len(largest) == 148 <= twin.limits.SPOOL_MAX_BYTES == 256 and largest.endswith(b'"}') and b"\n" not in largest


def test_the_spool_cap_of_256_bytes_is_held(twin, monkeypatch):
    S = twin.spool
    monkeypatch.setattr(twin.limits, "SPOOL_MAX_BYTES", 147)
    with pytest.raises(S.SpoolRefused, match="147"):
        S.encode(S.record("sha256:" + "f" * 64, "z" * 48))
    monkeypatch.setattr(twin.limits, "SPOOL_MAX_BYTES", 148)
    assert len(S.encode(S.record("sha256:" + "f" * 64, "z" * 48))) == 148


def test_the_spool_is_written_by_write_then_rename_and_nothing_else_is_ever_written(twin, tmp_path):
    S = twin.spool
    spool = tmp_path / "spool"
    spool.mkdir()
    (tmp_path / "beside.txt").write_text("not the connector's", encoding="utf-8")
    FileAudit.start()
    try:
        S.write(spool, S.record(IMAGE_ID, None))
        S.write(spool, S.record(None, SCENARIO))
        with pytest.raises(S.SpoolRefused):
            S.write(spool, {"image_id": IMAGE_ID, "scenario": None, "force": True})
        with pytest.raises(S.SpoolRefused):
            S.write(spool, {"image_id": None, "scenario": "../../beside.txt"})
    finally:
        events = FileAudit.stop()
    writes = [(e, [Path(p).name for p in paths]) for e, paths, w in events if w]
    assert writes == [("open", [".desired.json.tmp"]), ("os.rename", [".desired.json.tmp", "desired.json"])] * 2
    assert all(under(p, spool) for _e, paths, _w in events for p in paths)        # it reads, lists and writes nothing else
    assert sorted(p.name for p in spool.iterdir()) == ["desired.json"]            # the temporary name is gone: one file, whole
    assert (spool / "desired.json").read_bytes() == S.encode(S.record(None, SCENARIO))          # last writer wins
    assert (tmp_path / "beside.txt").read_text(encoding="utf-8") == "not the connector's"
    with pytest.raises(OSError):
        S.write(tmp_path / "no-such-directory", S.record(IMAGE_ID, None))          # it makes no directory


def test_the_connector_writes_an_image_id_or_a_scenario_into_the_spool_and_nowhere_else(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(1)
    assert [p.name for p in rig.spool.iterdir()] == [STAMP]                       # nothing desired: no record, only the start's stamp
    rig.shadow.cloud("config", {"image_id": IMAGE_ID})
    rig.run(0.1)
    assert json.loads((rig.spool / "desired.json").read_text(encoding="utf-8")) == {"image_id": IMAGE_ID, "scenario": None}
    other = "sha256:" + "2" * 64
    for image_id in (other, IMAGE_ID, other):                                     # three changes inside the next second: the last one wins
        rig.shadow.cloud("config", {"image_id": image_id, "scenario": SCENARIO})
        rig.run(0.1)
    assert rig.conn.counters["spool_written"] == 1 and twin.limits.SPOOL_MIN_GAP_S == 1.0
    rig.run(1)
    assert rig.conn.counters["spool_written"] == 2
    assert json.loads((rig.spool / "desired.json").read_text(encoding="utf-8")) == {"image_id": other, "scenario": SCENARIO}
    rig.shadow.cloud("config", {"scenario": "../etc", "image_id": "latest"})      # refused values: the file stays as it is
    rig.run(2).stop()
    assert json.loads((rig.spool / "desired.json").read_text(encoding="utf-8")) == {"image_id": other, "scenario": SCENARIO}
    assert rig.conn.counters["spool_written"] == 2 and sorted(p.name for p in rig.spool.iterdir()) == ["desired.json", STAMP]
    # nowhere else: not in any publish, not in config reported, not in the log (which says which fields, never what)
    everything = "".join(p.payload.decode("utf-8") for p in rig.fake.published) + rig.out.getvalue()
    for word in (IMAGE_ID, other, "1" * 64, "2" * 64, SCENARIO):
        assert word not in everything, word
    assert [(rec["image_id"], rec["scenario"]) for rec in rig.log("spool")] == [(True, False), (True, True)]
    # a spool that cannot be written is counted and does not stop the connector
    broken = Rig(twin, frozen, tmp_path / "broken", normal_values(frozen)).start()
    (broken.spool / STAMP).unlink()
    broken.spool.rmdir()
    broken.shadow.cloud("config", {"scenario": SCENARIO})
    broken.run(61)
    assert broken.conn.counters["spool_failed"] >= 1 and len(broken.telemetry()) == 1


def test_a_spool_write_that_failed_is_not_remembered_as_written(twin, frozen, tmp_path):
    """The re-check's probe: the spool directory is away when a request arrives and is back later. The service repeats
    the same request in every delta; remembered as written, as it was, that request was never written, and only a
    different one got through. Now a failed write is forgotten: the same request, when it comes again, is written, a
    second after the failed try at the earliest. Nothing is tried again by itself."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen)).start().run(10)
    away = rig.spool.with_name("away")
    stamp = (rig.spool / STAMP).read_bytes()
    rig.spool.rename(away)                                                        # 10 s: the directory is away
    rig.shadow.cloud("config", {"scenario": SCENARIO})
    delta = json.dumps(rig.shadow.deltas()[-1]).encode("utf-8")                   # the request, as the service will repeat it
    rig.run(0.1)
    counters = rig.conn.counters
    assert (counters["spool_failed"], counters["spool_written"]) == (1, 0)
    assert [(rec["ok"], rec["image_id"], rec["scenario"]) for rec in rig.log("spool")] == [(False, False, True)]
    for _ in range(30):                                                           # the same request at every step of the next 3 s
        assert rig.fake.deliver(CONFIG_DELTA, delta)
        rig.run(0.1)
    assert (counters["spool_failed"], counters["spool_written"]) == (4, 0)        # tried again, but once a second: the gap holds the retries
    away.rename(rig.spool)                                                        # the directory is back
    rig.run(10)
    assert counters["spool_written"] == 0 and sorted(p.name for p in rig.spool.iterdir()) == [STAMP]          # nothing by itself
    assert rig.fake.deliver(CONFIG_DELTA, delta)                                  # the same request again
    rig.run(0.1)
    assert (rig.spool / "desired.json").is_file(), "the request whose write had failed was taken as written"
    assert json.loads((rig.spool / "desired.json").read_text(encoding="utf-8")) == {"image_id": None, "scenario": SCENARIO}
    assert (counters["spool_failed"], counters["spool_written"]) == (4, 1) and (rig.spool / STAMP).read_bytes() == stamp
    for _ in range(30):                                                           # written, it is not written again
        assert rig.fake.deliver(CONFIG_DELTA, delta)
        rig.run(0.1)
    assert (counters["spool_failed"], counters["spool_written"]) == (4, 1) and [rec["ok"] for rec in rig.log("spool")] == [False] * 4 + [True]
    assert SCENARIO not in rig.out.getvalue() and str(tmp_path) not in rig.out.getvalue() and "away" not in rig.out.getvalue()


# ============================================================ the status record (SDV Phase 6 WP2; spec 2.4, section 4 items 1-3)
# The updater writes status.json (spec 2.4); status.py reads it; `config` reported carries it. Synthetic values: the image
# IDs are config digests made of one repeated digit, the scenario a name no recording has.

STATUS_IMAGE = "sha256:" + "2" * 64
STATUS_OTHER = "sha256:" + "3" * 64
STATUS_SCENARIO = "20990101-sigsim-44-drill"
NULLS = {"image_id": None, "scenario": None, "result": None}


def status_bytes(image_id: Optional[str] = STATUS_IMAGE, scenario: Optional[str] = None, result: Any = "applied") -> bytes:
    """The record as the updater writes it (spec 2.4): compact, ASCII, the three keys in order."""
    return json.dumps({"image_id": image_id, "scenario": scenario, "result": result}, separators=(",", ":")).encode("ascii")


def put_status(directory: Path, data: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "status.json").write_bytes(data)


def _no_t(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{k: v for k, v in rec.items() if k != "t"} for rec in records]


@pytest.mark.parametrize("image_id, scenario, result", [
    (STATUS_IMAGE, None, "applied"), (STATUS_IMAGE, STATUS_SCENARIO, "applied"), (STATUS_OTHER, None, "rolled-back"),
    (None, None, "rolled-back"), (STATUS_IMAGE, None, "refused"), (None, STATUS_SCENARIO, "refused"), (None, None, "refused"),
    (STATUS_IMAGE, "a", "applied"), (STATUS_IMAGE, "0" + "z-" * 23 + "z", "applied"),
])
def test_status_read_takes_every_record_of_the_form_and_returns_it_whole(twin, tmp_path, image_id, scenario, result):
    S = twin.status
    put_status(tmp_path, status_bytes(image_id, scenario, result))
    got = S.read(tmp_path)
    assert got.why is None and got.record == {"image_id": image_id, "scenario": scenario, "result": result}
    assert list(got.record) == list(S.KEYS) == ["image_id", "scenario", "result"]
    # another key order, spaces and a trailing newline are the same one JSON object of the three keys: taken. The reader
    # holds the record's content (spec 2.4's list of refusals); the compact form is the writer's
    loose = '{ "result": %s,\n  "scenario": %s, "image_id": %s }\n' % (json.dumps(result), json.dumps(scenario), json.dumps(image_id))
    put_status(tmp_path, loose.encode("ascii"))
    assert S.read(tmp_path) == got


REFUSED_STATUS = [
    (status_bytes() + b" " * (257 - len(status_bytes())), "too-large"),            # a good record but for its 257th byte
    (status_bytes(scenario="caf") + b" " * 300, "too-large"),
    (b'{"image_id":null,"scenario":"caf\xc3","result":"applied"}', "not-utf8"),
    (b"\xff\xfe" + status_bytes(), "not-utf8"),
    (b"", "not-json"), (b"{", "not-json"), (status_bytes() + status_bytes(), "not-json"),           # nothing, half, two objects
    (b"\xef\xbb\xbf" + status_bytes(), "not-json"),                                                   # a byte order mark
    (b"[]", "not-object"), (b'"applied"', "not-object"), (b"null", "not-object"), (b"7", "not-object"),
    (('{"image_id":"%s","image_id":"%s","scenario":null,"result":"applied"}' % (STATUS_IMAGE, STATUS_OTHER)).encode(), "duplicate-key"),
    (b'{"image_id":null,"scenario":null,"result":"applied","result":"refused"}', "duplicate-key"),
    (b'{"image_id":null,"scenario":null}', "keys"), (b"{}", "keys"),
    (b'{"image_id":null,"scenario":null,"result":"refused","cause":"pull-failed"}', "keys"),            # a cause is never in it
    (b'{"image_id":null,"scenario":null,"Result":"applied"}', "keys"),
    (status_bytes("hard-brake-hazard:1.1.0"), "image_id"), (status_bytes("sha256:" + "A" * 64), "image_id"),
    (status_bytes("sha256:" + "2" * 63), "image_id"), (status_bytes(STATUS_IMAGE + "\n"), "image_id"),
    (b'{"image_id":7,"scenario":null,"result":"applied"}', "image_id"), (b'{"image_id":[],"scenario":null,"result":"applied"}', "image_id"),
    (status_bytes(scenario="../etc"), "scenario"), (status_bytes(scenario=""), "scenario"), (status_bytes(scenario="x" * 49), "scenario"),
    (status_bytes(scenario="-leading"), "scenario"), (status_bytes(scenario=STATUS_SCENARIO + "\n"), "scenario"),
    (b'{"image_id":null,"scenario":true,"result":"applied"}', "scenario"),
    (status_bytes(result="ok"), "result"), (status_bytes(result="Applied"), "result"), (status_bytes(result=None), "result"),
    (status_bytes(result=True), "result"), (status_bytes(result=["applied"]), "result"), (status_bytes(result="applied "), "result"),
    (b'{"image_id":null,"scenario":null,"result":"applied","x":{"a":1,"a":2}}', "duplicate-key"),   # the hook fires at any depth, before the key set
    (b'{"image_id":NaN,"scenario":null,"result":"applied"}', "image_id"), (b'{"image_id":null,"scenario":null,"result":Infinity}', "result"),
    (b"   ", "not-json"), (b"\x00", "not-json"),
    (b'{"image_id":null,"scenario":7,"result":"applied"}', "scenario"), (status_bytes(scenario="a.b"), "scenario"),
    (status_bytes("SHA256:" + "2" * 64), "image_id"),
]


@pytest.mark.parametrize("data, why", REFUSED_STATUS)
def test_status_read_refuses_by_a_reason_that_holds_no_value(twin, tmp_path, data, why):
    S = twin.status
    put_status(tmp_path, data)
    got = S.read(tmp_path)
    assert got == (None, why) and why in S.REASONS
    planted = [w for w in ("hard-brake-hazard", "caf", "pull-failed", "../etc", STATUS_IMAGE, STATUS_OTHER, STATUS_SCENARIO) if w.encode() in data]
    assert not [w for w in planted if w in str(got)], "a refusal named a value of the record it refused"


def test_status_read_takes_256_bytes_says_missing_or_unreadable_and_never_blocks(twin, tmp_path):
    S = twin.status
    good = status_bytes(STATUS_IMAGE, STATUS_SCENARIO, "rolled-back")
    put_status(tmp_path, good + b" " * (S.MAX_BYTES - len(good)))
    assert len((tmp_path / "status.json").read_bytes()) == 256 and S.read(tmp_path).why is None
    put_status(tmp_path, good + b" " * (S.MAX_BYTES + 1 - len(good)))
    assert S.read(tmp_path) == (None, "too-large")
    (tmp_path / "status.json").unlink()
    assert S.read(tmp_path) == (None, S.MISSING) == (None, "missing")
    assert S.read(tmp_path / "no-such-directory") == (None, "missing")
    (tmp_path / "status.json").mkdir()                                            # a directory in its place
    assert S.read(tmp_path) == (None, "unreadable")
    (tmp_path / "status.json").rmdir()
    if hasattr(os, "mkfifo"):
        os.mkfifo(str(tmp_path / "status.json"))                                  # no writer: an open that waited would block, so
        got = []                                                                   # the read runs in a thread and a wait fails, never hangs
        reader = threading.Thread(target=lambda: got.append(S.read(tmp_path)), daemon=True)
        reader.start()
        reader.join(5)
        assert got == [(None, "unreadable")], "the read of a FIFO waited"
        (tmp_path / "status.json").unlink()
    # a file that may not be read and a link that loops are refusals of the open, not absences: "unreadable", never "missing"
    put_status(tmp_path, good)
    os.chmod(tmp_path / "status.json", 0)
    try:
        if hasattr(os, "geteuid") and os.geteuid() != 0:                          # root reads a file of mode 000
            assert S.read(tmp_path) == (None, "unreadable")
    finally:
        os.chmod(tmp_path / "status.json", 0o644)
    assert S.read(tmp_path).why is None
    (tmp_path / "status.json").unlink()
    os.symlink(str(tmp_path / "status.json"), str(tmp_path / "status.json"))   # a loop: ELOOP at the open
    assert S.read(tmp_path) == (None, "unreadable")


def test_status_names_its_file_its_keys_its_results_its_reasons_and_the_directory_the_stack_mounts(twin):
    S, C = twin.status, twin.connector
    assert (S.DEFAULT_STATUS_DIR, S.FILE, S.MAX_BYTES) == ("/run/sdv-local/status/v1", "status.json", 256)
    assert S.KEYS == ("image_id", "scenario", "result") and S.RESULTS == ("applied", "rolled-back", "refused")
    assert S.REASONS == ("missing", "unreadable", "too-large", "not-utf8", "not-json", "not-object", "duplicate-key", "keys", "image_id",
                         "scenario", "result") and S.MISSING == S.REASONS[0]
    assert (C.ENV_STATUS, C.DEFAULT_STATUS) == ("SDV_TWIN_STATUS", S.DEFAULT_STATUS_DIR)
    assert "status_refused" in C.COUNTERS and "status" in C.LOG_EVENTS


def test_config_reported_carries_the_updaters_status_beside_the_rate_and_the_paths(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path / "a", normal_values(frozen))
    put_status(rig.status_dir, status_bytes(STATUS_IMAGE, STATUS_SCENARIO, "applied"))
    rig.shadow.cloud("config", {"image_id": STATUS_IMAGE, "scenario": STATUS_SCENARIO})
    rig.start().run(3)
    want = {"rate_hz": 1, "paths": list(frozen.PATHS), "image_id": STATUS_IMAGE, "scenario": STATUS_SCENARIO, "result": "applied"}
    assert rig.reports() == [want] and list(rig.reports()[0]) == ["rate_hz", "paths", "image_id", "scenario", "result"]
    assert rig.shadow.docs["config"]["reported"] == want
    assert FakeShadow._delta(rig.shadow.docs["config"]) == {}, "desired equals reported: the service's delta holds neither any more"
    assert _no_t(rig.log("config")) == [{"event": "config", "rate_hz": 1, "paths": len(frozen.PATHS), "status": "reported"}]
    assert STATUS_IMAGE not in rig.out.getvalue() and STATUS_SCENARIO not in rig.out.getvalue()          # the log names no value
    # with no status record the report is the rate and the path set, as it was before Phase 6
    plain = Rig(twin, frozen, tmp_path / "b", normal_values(frozen)).start().run(3)
    assert plain.reports() == [{"rate_hz": 1, "paths": list(frozen.PATHS)}]
    assert _no_t(plain.log("config")) == [{"event": "config", "rate_hz": 1, "paths": len(frozen.PATHS)}] and plain.log("status") == []
    assert twin.shadowdoc.config_state(10, (frozen.PATHS[0],), {"image_id": None, "scenario": STATUS_SCENARIO, "result": "refused"}) == {
        "rate_hz": 10, "paths": [frozen.PATHS[0]], "image_id": None, "scenario": STATUS_SCENARIO, "result": "refused"}


def test_a_status_that_alone_changed_is_reported_once_and_an_unchanged_one_never_again(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    put_status(rig.status_dir, status_bytes(STATUS_IMAGE, None, "applied"))
    rig.start().run(5)
    assert len(rig.reports()) == 1
    put_status(rig.status_dir, status_bytes(STATUS_OTHER, None, "rolled-back"))          # the rate and the paths as they were
    rig.run(1)
    assert rig.reports()[1:] == [{"rate_hz": 1, "paths": list(frozen.PATHS), "image_id": STATUS_OTHER, "scenario": None, "result": "rolled-back"}]
    rig.run(30)
    assert len(rig.reports()) == 2, "an unchanged status, read at every tick, went again"
    loose = '{"result": "rolled-back", "scenario": null, "image_id": "%s"}\n' % STATUS_OTHER
    put_status(rig.status_dir, loose.encode("ascii"))                             # the same record in another layout: no change
    rig.run(5)
    assert len(rig.reports()) == 2
    put_status(rig.status_dir, status_bytes(STATUS_OTHER, None, "refused"))          # the result alone
    rig.run(1)
    assert len(rig.reports()) == 3 and rig.reports()[-1]["result"] == "refused" and rig.reports()[-1]["image_id"] == STATUS_OTHER
    assert [rec.get("status") for rec in rig.log("config")] == ["reported"] * 3


@pytest.mark.parametrize("how", ["removed", "refused"])
def test_a_status_that_vanishes_or_is_refused_after_it_was_reported_is_cleared_once_with_three_nulls(twin, frozen, tmp_path, how):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    put_status(rig.status_dir, status_bytes(STATUS_IMAGE, STATUS_SCENARIO, "applied"))
    rig.start().run(3)
    assert rig.reports()[-1]["image_id"] == STATUS_IMAGE
    if how == "removed":
        (rig.status_dir / "status.json").unlink()
    else:
        put_status(rig.status_dir, b'{"image_id":null,"scenario":null,"result":"applied","cause":"x"}')
    rig.run(2)
    assert rig.reports()[1:] == [dict({"rate_hz": 1, "paths": list(frozen.PATHS)}, **NULLS)]
    assert rig.shadow.docs["config"]["reported"] == {"rate_hz": 1, "paths": list(frozen.PATHS)}, "the service deleted the three keys"
    assert rig.log("config")[-1]["status"] == "cleared"
    rig.run(30)
    assert len(rig.reports()) == 2, "cleared once, not at every tick"
    rig.shadow.cloud("config", {"rate_hz": 10})                                   # a later report still clears: no stale image
    rig.run(1)
    assert rig.reports()[-1] == dict({"rate_hz": 10, "paths": list(frozen.PATHS)}, **NULLS) and len(rig.reports()) == 3
    put_status(rig.status_dir, status_bytes(STATUS_OTHER, None, "rolled-back"))           # and a valid status goes again
    rig.run(1)
    assert rig.reports()[-1] == {"rate_hz": 10, "paths": list(frozen.PATHS), "image_id": STATUS_OTHER, "scenario": None,
                                 "result": "rolled-back"}


def test_a_refused_status_is_counted_and_logged_by_its_reason_and_none_of_its_values_goes_anywhere(twin, frozen, tmp_path):
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    planted = ("planted-scenario-x", "planted-cause-y")
    bad = {"image_id": STATUS_OTHER, "scenario": planted[0], "result": "applied", "cause": planted[1]}
    put_status(rig.status_dir, json.dumps(bad).encode("ascii"))                   # another key set
    rig.start().run(5)
    assert rig.reports() == [{"rate_hz": 1, "paths": list(frozen.PATHS)}], "never shown, nothing to clear: the report as without one"
    assert rig.conn.counters["status_refused"] == 1
    dup = '{"image_id":"%s","image_id":"%s","scenario":"%s","result":"applied"}' % (STATUS_OTHER, STATUS_IMAGE, planted[0])
    put_status(rig.status_dir, dup.encode("ascii"))                                # another reason: counted and logged once more
    rig.run(3)
    rig.run(20)                                                                   # the same refusal at every tick: counted once
    assert rig.conn.counters["status_refused"] == 2 and len(rig.reports()) == 1
    assert _no_t(rig.log("status")) == [{"event": "status", "ok": False, "why": "keys"}, {"event": "status", "ok": False, "why": "duplicate-key"}]
    (rig.status_dir / "status.json").unlink()                                     # gone: logged, not counted as a refusal
    rig.run(2)
    assert rig.conn.counters["status_refused"] == 2 and _no_t(rig.log("status"))[-1] == {"event": "status", "ok": False, "why": "missing"}
    rig.stop()
    assert rig.log("stop")[0]["counters"]["status_refused"] == 2
    everything = "".join(p.payload.decode("utf-8") for p in rig.fake.published) + rig.out.getvalue()
    for word in planted + (STATUS_OTHER, STATUS_IMAGE):
        assert word not in everything, word


def test_a_new_connection_clears_a_status_this_process_reported_that_vanished_while_its_clearing_could_not_go(twin, frozen, tmp_path):
    """The shadow keeps what was reported across connections. A status this process reported, then lost while the far end
    failed every publish (the clearing report among them), is cleared by the first report of the next connection. Here that
    connection's get goes unanswered, so the clearing rests on this process's own memory and not on a get's answer."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    put_status(rig.status_dir, status_bytes(STATUS_IMAGE, None, "applied"))
    rig.start().run(3)
    assert rig.shadow.docs["config"]["reported"]["image_id"] == STATUS_IMAGE
    fail_between(rig, rig.now(), rig.now() + 30)
    (rig.status_dir / "status.json").unlink()
    rig.run(35)
    assert rig.shadow.docs["config"]["reported"]["image_id"] == STATUS_IMAGE, "the clearing report went though the far end failed it"
    gets = len(rig.at(CONFIG_GET))
    rig.shadow._get = lambda name: None                                           # the far end answers no get from now on
    rig.fake.resume()
    rig.run(40)                                                                   # past the retry spacing of the failed shadow publish
    assert len(rig.at(CONFIG_GET)) == gets + 1, "the new connection asked, and was not answered"
    assert rig.reports()[-1] == dict({"rate_hz": 1, "paths": list(frozen.PATHS)}, **NULLS)
    assert "image_id" not in rig.shadow.docs["config"]["reported"] and rig.conn.counters["resumed"] == 1


def test_a_status_every_report_of_which_failed_and_that_then_vanished_is_never_cleared_for_nothing_was_shown(twin, frozen, tmp_path):
    """A status counts as shown once a report with a status part went out. One whose every report failed and that was then
    gone before any went has put nothing into the shadow: the first report that goes carries the rate and the paths and no
    null keys, and its log line says nothing of a status."""
    rig = Rig(twin, frozen, tmp_path, normal_values(frozen))
    put_status(rig.status_dir, status_bytes(STATUS_IMAGE, STATUS_SCENARIO, "applied"))
    rig.fake.fail_publish = lambda topic, payload: "down" if topic == CONFIG_UPDATE else None
    rig.start().run(5)
    assert rig.reports() == [], "a report went though the far end failed them all"
    (rig.status_dir / "status.json").unlink()
    rig.fake.fail_publish = None
    rig.run(70)                                                                   # past the retry spacing of the failed shadow publish
    assert rig.reports() and all(report == {"rate_hz": 1, "paths": list(frozen.PATHS)} for report in rig.reports()), rig.reports()
    assert "status" not in rig.log("config")[-1], rig.log("config")[-1]


def _next_process(twin: Any, frozen: Any, rig: Rig, spool: Path, status_dir: Path) -> Tuple[Any, Any, "FakeShadow", io.StringIO]:
    """Another connector process on the rig's thing, built as the entry point builds one: a new uplink and limiter, the
    service's shadow as the earlier process left it (the service keeps it across the device's processes and hosts), and the
    spool and status directories given."""
    fake = twin.uplink.FakeUplink(clock=rig.clock)
    shadow = FakeShadow(fake)
    shadow.docs = rig.shadow.docs
    out = io.StringIO()
    conn = twin.connector.build(fake, twin.source.FakeSource(normal_values(frozen)), rig.clock, rig.topics, frozen, SCHEMA, spool, out,
                                status_dir=status_dir)
    conn.start()
    conn.step()
    for _ in range(30):
        rig.clock.advance(0.1)
        conn.step()
    return conn, fake, shadow, out


@pytest.mark.parametrize("how", ["restart", "another-host", "refused"])
def test_a_status_an_earlier_process_left_in_the_shadow_is_cleared_by_the_next_processs_first_report(twin, frozen, tmp_path, how):
    """Spec section 4 item 2: a status reported and then missing or refused is cleared, so the shadow never shows a stale
    image. The shadow keeps what a process reported after the process is gone: a host's restart clears /run, so the next
    process finds no record (and the updater writes none for a request it already processed: its mark is in its state);
    another host's connector on the thing reads its own empty status directory; or the record is refused. The next process
    learns from its get's answer that the shadow holds a status, and its first report clears it with three nulls."""
    rig = Rig(twin, frozen, tmp_path / "a", normal_values(frozen))
    put_status(rig.status_dir, status_bytes(STATUS_IMAGE, STATUS_SCENARIO, "applied"))
    rig.start().run(3).stop()
    assert rig.shadow.docs["config"]["reported"]["image_id"] == STATUS_IMAGE
    spool, status_dir = rig.spool, rig.status_dir
    if how == "restart":
        (status_dir / "status.json").unlink()
    elif how == "refused":
        put_status(status_dir, b'{"image_id":null,"scenario":null,"result":"applied","cause":"x"}')
    else:
        spool, status_dir = tmp_path / "b" / "spool" / "v1", tmp_path / "b" / "status" / "v1"
        spool.mkdir(parents=True)
        status_dir.mkdir(parents=True)
    rig.clock.advance(130.0)                                                      # past the start spacing on one spool directory
    conn, fake, shadow, out = _next_process(twin, frozen, rig, spool, status_dir)
    reports = [json.loads(p.payload)["state"]["reported"] for p in fake.published if p.topic == CONFIG_UPDATE]
    assert reports == [dict({"rate_hz": 1, "paths": list(frozen.PATHS)}, **NULLS)], reports
    assert shadow.docs["config"]["reported"] == {"rate_hz": 1, "paths": list(frozen.PATHS)}, "the stale image is gone"
    log = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [rec.get("status") for rec in log if rec["event"] == "config"] == ["cleared"]
    assert conn.counters["status_refused"] == (1 if how == "refused" else 0)
    assert STATUS_IMAGE not in out.getvalue() and STATUS_SCENARIO not in out.getvalue(), "nothing of the get's answer is logged"


def test_a_gets_answer_tells_whether_the_shadow_holds_a_status_and_one_too_old_to_apply_tells_it_too(twin, frozen, tmp_path):
    # a shadow that holds the rate and the paths only: the report is the rate and the path set, as before Phase 6
    plain = Rig(twin, frozen, tmp_path / "a", normal_values(frozen))
    plain.shadow.docs["config"] = {"desired": {}, "reported": {"rate_hz": 1, "paths": list(frozen.PATHS)}, "version": 4}
    plain.start().run(3)
    assert plain.log("config-get")[0]["outcome"] == "accepted" and plain.reports() == [{"rate_hz": 1, "paths": list(frozen.PATHS)}]
    # the shadow holds another process's status and this one reads a valid record: its own goes, whole, and no null
    own = Rig(twin, frozen, tmp_path / "b", normal_values(frozen))
    own.shadow.docs["config"] = {"desired": {}, "reported": {"rate_hz": 1, "paths": list(frozen.PATHS), "image_id": STATUS_OTHER,
                                                             "result": "rolled-back"}, "version": 4}
    put_status(own.status_dir, status_bytes(STATUS_IMAGE, None, "applied"))
    own.start().run(3)
    assert own.reports() == [{"rate_hz": 1, "paths": list(frozen.PATHS), "image_id": STATUS_IMAGE, "scenario": None, "result": "applied"}]
    # an answer older than the delta that overtook it is not applied, but what it shows of the shadow is taken (it clears a
    # key that is there and changes nothing where none is), and one key of the three is enough
    late = Rig(twin, frozen, tmp_path / "c", normal_values(frozen), shadow=False)
    late.conn.start()
    delta = {"state": {"rate_hz": 10}, "metadata": {}, "version": 8, "timestamp": 1}
    answer = {"state": {"desired": {}, "reported": {"rate_hz": 1, "paths": list(frozen.PATHS), "scenario": STATUS_SCENARIO}},
              "metadata": {}, "version": 7, "timestamp": 1}
    assert late.fake.deliver(CONFIG_DELTA, json.dumps(delta).encode("utf-8"))
    assert late.fake.deliver(CONFIG_GET + "/accepted", json.dumps(answer).encode("utf-8"))
    late.conn.step()
    assert late.conn.counters["stale"] == 1 and late.conn.rate_hz == 10
    assert late.reports() == [dict({"rate_hz": 10, "paths": list(frozen.PATHS)}, **NULLS)]
    assert STATUS_SCENARIO not in late.out.getvalue()


def test_the_entry_point_reads_the_status_where_sdv_twin_status_says_by_default_where_the_stack_mounts_it(twin, frozen, tmp_path):
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    spool = tmp_path / "spool"
    spool.mkdir()
    base = {"SDV_TWIN_THING": THING, "SDV_TWIN_RULE": RULE, "SDV_TWIN_SPOOL": str(spool), "SDV_TWIN_SCHEMA": str(SCHEMA_FILE)}

    def assembled(env: Dict[str, str]) -> Any:
        return twin.connector._assemble(env, lambda e, topics: twin.uplink.FakeUplink(clock=clock), lambda target: twin.source.FakeSource({}),
                                        clock, io.StringIO(), frozen)

    assert str(assembled(base).status_dir) == twin.status.DEFAULT_STATUS_DIR
    assert str(assembled(dict(base, SDV_TWIN_STATUS="")).status_dir) == twin.status.DEFAULT_STATUS_DIR
    sdir = tmp_path / "status"
    assert str(assembled(dict(base, SDV_TWIN_STATUS=str(sdir))).status_dir) == str(sdir)
    put_status(sdir, status_bytes(STATUS_IMAGE, STATUS_SCENARIO, "applied"))
    fake = twin.uplink.FakeUplink(clock=clock)
    FakeShadow(fake)
    handlers: Dict[int, Any] = {}

    def end(c: Any) -> None:
        if signal.SIGTERM in handlers and c.monotonic() - 1000.0 >= 5.0:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    clock.on_sleep.append(end)
    assert _entry(twin, frozen, spool, twin.source.FakeSource(normal_values(frozen)), fake, clock, io.StringIO(), handlers, status_dir=sdir)() == 0
    assert [json.loads(p.payload)["state"]["reported"] for p in fake.published if p.topic == CONFIG_UPDATE] == [
        {"rate_hz": 1, "paths": list(frozen.PATHS), "image_id": STATUS_IMAGE, "scenario": STATUS_SCENARIO, "result": "applied"}]


def test_status_py_is_one_of_the_modules_the_image_stages(build_image):
    assert "status.py" in build_image.MODULES and list(build_image.MODULES) == sorted(build_image.MODULES)
    assert "status.py" in build_image.staged(TWIN_FROZEN)


def test_the_readme_and_the_docstring_say_what_the_status_record_does(twin):
    """SDV Phase 6 WP2: the connector's README names the module, the variable, the clearing by three nulls, the counter and the
    image's module count, and says it does not judge what runs; the two modules' docstrings say the same, and both say that
    a get's answer showing a status in the shadow is what lets a later process clear it."""
    flat = " ".join((CONNECTOR_DIR / "README.md").read_text(encoding="utf-8").split())
    for words in ("`status.py`", "SDV_TWIN_STATUS", "three nulls", "`status_refused`", "fifteen modules", "Not a judge of what runs",
                  "the get's answer holds one in reported", "so the shadow keeps no stale image"):
        assert words in flat, words
    # the nulls ride the next report and every later one, not one report: the words of both texts say so
    assert ("as three nulls, which the service deletes, in the next report and in every later one (each new connection's first "
            "among them) until a valid status is read") in flat, "the README says the nulls ride one report only"
    doc = twin.connector.__doc__ or ""
    for words in ("SDV_TWIN_STATUS", "status_refused", "three nulls", "a get's answer holds one in reported"):
        assert words in doc, words
    assert ("as three nulls (the service deletes them) in the next report and in every later one, each new connection's first "
            "among them, until a valid status is read") in " ".join(doc.split()), "the docstring says the nulls ride one report only"
    assert "Does not demonstrate" in (twin.status.__doc__ or "")


# ============================================================ topics

def test_the_topic_strings_are_exact_and_the_client_id_is_the_thing_name(twin):
    t = twin.topics.Topics("example-thing", "example_rule")
    assert t.client_id == "example-thing" == t.thing
    assert t.telemetry == "$aws/rules/example_rule/example-thing"
    assert t.vss_update == "$aws/things/example-thing/shadow/name/vss/update"
    assert t.config_update == "$aws/things/example-thing/shadow/name/config/update"
    assert t.config_get == "$aws/things/example-thing/shadow/name/config/get"
    # gap j's lists, in its order: four to publish to, five to subscribe to, and nothing else
    assert t.publish == (t.telemetry, t.vss_update, t.config_update, t.config_get)
    assert t.subscribe == ("$aws/things/example-thing/shadow/name/config/get/accepted",
                           "$aws/things/example-thing/shadow/name/config/get/rejected",
                           "$aws/things/example-thing/shadow/name/config/update/delta",
                           "$aws/things/example-thing/shadow/name/config/update/rejected",
                           "$aws/things/example-thing/shadow/name/vss/update/rejected")
    assert t.subscribe == (t.config_get_accepted, t.config_get_rejected, t.config_update_delta, t.config_update_rejected, t.vss_update_rejected)
    every = t.publish + t.subscribe
    assert len(set(every)) == 9 and not any(c in topic for topic in every for c in "#+*? ")
    assert not any("vss/get" in topic or "delete" in topic or topic.endswith("update/accepted") or "documents" in topic for topic in every)
    assert twin.topics.SHADOWS == ("vss", "config")
    assert (t.telemetry, VSS_UPDATE, CONFIG_UPDATE, CONFIG_GET, CONFIG_DELTA) == (
        TELEMETRY_TOPIC, t.vss_update, t.config_update, t.config_get, t.config_update_delta)
    for thing, rule in (("", RULE), (THING, ""), ("a/b", RULE), ("a+b", RULE), ("#", RULE), ("a b", RULE), ("$aws", RULE),
                        (THING, "example-rule"), (THING, "a/b"), (THING, "+"), (THING, "a.b"), ("x" * 129, RULE), (THING, "x" * 129),
                        ("thing\n", RULE), (THING, "rule\n"), (None, RULE), (THING, 7)):
        with pytest.raises(twin.topics.TopicsError) as exc:
            twin.topics.Topics(thing, rule)
        assert "a/b" not in str(exc.value) and "$aws" not in str(exc.value)       # the refusal does not repeat the name
    assert twin.topics.Topics("Thing_1:a-b", "Rule_1").telemetry == "$aws/rules/Rule_1/Thing_1:a-b"


# ============================================================ the import graph

def _imports(path: Path) -> Set[str]:
    """The top-level name of every module a file imports, wherever in the file, with __import__ and import_module."""
    names: Set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "%s: a relative import" % path
            names.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if called in ("__import__", "import_module"):
                arg = node.args[0] if node.args else None
                literal = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                names.add(str(getattr(arg, "value", "")).split(".")[0] if literal else "<not a literal>")
    return names


def test_only_uplink_aws_imports_the_sdk_and_no_connector_module_imports_a_burst_tool(twin):
    sdk = {"awscrt", "awsiot"}
    files = sorted(p for p in CONNECTOR_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    assert {p.name for p in files} >= {m + ".py" for m in WP2_MODULES} | {"appstate.py", "gen_allowlist.py", "lockcheck.py"}
    for path in files:
        names = _imports(path)
        if path.name != "uplink_aws.py":                                          # WP3's file, the one place the SDK is imported
            assert not names & sdk, path
        assert not any(n.startswith("burst") for n in names), path                # gap y: the bursts are another program
        # ... which exists now (sdv/cloud/burst). No file of this directory names it anywhere but in the words of its own
        # docstring (the envelope's says who sends `v: 0`): no name, no string, no path in its code. The one exception
        # is the script that builds the tool's image, and that one loads nothing of it: it copies files
        if path.name != "build_image.py":
            text = path.read_text(encoding="utf-8")
            doc = ast.get_docstring(ast.parse(text), clean=False) or ""
            assert doc in text and "burst" not in text.replace(doc, "", 1).lower(), path
    assert "spec_from_file_location" not in "".join(ln for ln in BUILD_IMAGE.read_text(encoding="utf-8").splitlines() if "burst" in ln.lower())
    # the tool reaches the connector, never the other way round: its own modules are no file of this directory
    assert not [p for p in CONNECTOR_DIR.rglob("*") if p.name.lower().startswith("burst")]
    assert {p.name for p in BURST_DIR.glob("*.py")} == {"burst.py", "burst_link.py"}
    stdlib = set(sys.stdlib_module_names)
    own = set(WP2_MODULES) | {"appstate"}
    lazy = {"source": {"grpc", "kuksa"}, "connector": {"twin_allowlist", "uplink_aws"}}
    for name in WP2_MODULES:
        outside = _imports(CONNECTOR_DIR / (name + ".py")) - stdlib - own
        assert outside == lazy.get(name, set()), (name, outside)
    # and importing them all brought no SDK into the process
    loaded = {m.split(".")[0] for m in sys.modules}
    assert not loaded & (sdk | {"uplink_aws", "burst", "burst_link"})
    assert all(getattr(twin, name).__doc__ and "Does not demonstrate" in getattr(twin, name).__doc__ for name in WP2_MODULES)
    # limits.py is the one place: it imports nothing at all
    assert _imports(CONNECTOR_DIR / "limits.py") <= {"__future__", "typing"}


# ============================================================ the log, and the entry point

def test_the_log_is_json_lines_that_never_hold_the_thing_name_a_topic_the_endpoint_or_a_certificate_path(twin, frozen, tmp_path):
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    fake = twin.uplink.FakeUplink(clock=clock)
    shadow = FakeShadow(fake)
    src = twin.source.FakeSource(normal_values(frozen))
    handlers: Dict[int, Any] = {}
    out = io.StringIO()
    secret = "broker.example.invalid:8883 with /run/sdv-local/device/device.key"

    def events(c):
        t = c.monotonic() - 1000.0
        src.set(frozen.PATHS[1], t)
        if 65 <= t < 72:          # the uplink fails for a while, and says where and with what
            fake.fail_publish = lambda topic, payload: "publish to %s failed: %s" % (topic, secret)
        else:
            fake.fail_publish = None
        if t == 20:
            shadow.cloud("config", {"rate_hz": 10, "image_id": IMAGE_ID, "paths": [frozen.PATHS[1], THING, TELEMETRY_TOPIC, secret]})
        if t >= 130:
            handlers[signal.SIGINT](signal.SIGINT, None)

    clock.on_sleep.append(events)
    assert _entry(twin, frozen, tmp_path, src, fake, clock, out, handlers)() == 0
    text = out.getvalue()
    lines = [json.loads(line) for line in text.splitlines()]
    assert all(isinstance(rec, dict) and rec["event"] in LOG_EVENTS and isinstance(rec["t"], float) for rec in lines)
    assert all(line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":")) for line in text.splitlines())
    seen = {rec["event"] for rec in lines}
    assert seen >= {"start", "config-get", "config", "spool", "batch", "shadow", "publish-failed", "stop"}
    failed = [rec for rec in lines if rec["event"] == "publish-failed"]
    assert failed and all(set(rec) == {"event", "t", "what", "error"} and rec["error"] == "UplinkError" for rec in failed)
    for word in (THING, RULE, "$aws", "shadow/name", "broker.example.invalid", "/run/sdv-local", "device.key", "example",
                 str(tmp_path), "SDV_TWIN"):
        assert word not in text, word
    assert lines[0] == {"event": "start", "t": 1000.0, "allowlist_version": 1, "allowlist_digest": "0x%08X" % frozen.DIGEST,
                        "catalogue": frozen.CATALOGUE_SHA256[:12], "paths": 16, "rate_hz": 1}
    assert re.fullmatch(r"[0-9a-f]{12}", lines[0]["catalogue"])          # which generation it ran on: a prefix of the catalogue's sha256
    assert lines[-1]["event"] == "stop" and lines[-1]["signal"] == int(signal.SIGINT)
    assert lines[-1]["counters"]["failed_telemetry"] + lines[-1]["counters"]["failed_vss"] >= 1


def test_the_entry_point_refuses_a_missing_or_malformed_name_and_a_failed_connect_without_repeating_either(twin, frozen, tmp_path, capsys):
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    made: List[Any] = []

    def main(env, fake=None):
        return twin.connector.main([], env=env, make_uplink=lambda e, topics: made.append(topics) or fake,
                                   make_source=lambda target: twin.source.FakeSource({}), clock=clock, out=io.StringIO(), frozen=frozen)

    base = {"SDV_TWIN_SPOOL": str(tmp_path), "SDV_TWIN_SCHEMA": str(SCHEMA_FILE)}
    for env in (base, dict(base, SDV_TWIN_THING=THING), dict(base, SDV_TWIN_RULE=RULE), dict(base, SDV_TWIN_THING="", SDV_TWIN_RULE=RULE),
                dict(base, SDV_TWIN_THING="bad/thing+name", SDV_TWIN_RULE=RULE), dict(base, SDV_TWIN_THING=THING, SDV_TWIN_RULE="bad-rule")):
        assert main(env) == 2
        err = capsys.readouterr().err
        assert "SDV_TWIN_THING" in err and "SDV_TWIN_RULE" in err and "bad/thing+name" not in err and "bad-rule" not in err
    assert made == []                                                             # no uplink was built for any of them
    assert twin.connector.main(["--anything"], env=dict(base, SDV_TWIN_THING=THING, SDV_TWIN_RULE=RULE), make_uplink=None,
                               make_source=None, clock=clock, out=io.StringIO(), frozen=frozen) == 2          # it takes no argument
    assert "takes no argument" in capsys.readouterr().err
    fake = twin.uplink.FakeUplink(clock=clock)
    fake.fail_connect = "TLS handshake with broker.example.invalid:8883 failed (/run/sdv-local/device/device.crt)"
    out = io.StringIO()
    rc = twin.connector.main([], env=dict(base, SDV_TWIN_THING=THING, SDV_TWIN_RULE=RULE), make_uplink=lambda e, topics: fake,
                             make_source=lambda target: twin.source.FakeSource({}), clock=clock, out=out, frozen=frozen)
    assert rc == 1 and fake.published == [] and fake.closes == 1
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [rec["event"] for rec in lines] == ["start", "connect-failed"] and lines[1]["error"] == "UplinkError"
    assert "example" not in out.getvalue() and "device" not in out.getvalue() and capsys.readouterr().err == ""
    # a start whose connect failed was a start all the same: its stamp is kept, and the next one inside the spacing is refused
    working, out = twin.uplink.FakeUplink(clock=clock), io.StringIO()
    clock.on_sleep.append(_raises(AssertionError("the loop began: the start after a failed connect was not refused")))
    rc = twin.connector.main([], env=dict(base, SDV_TWIN_THING=THING, SDV_TWIN_RULE=RULE), make_uplink=lambda e, topics: working,
                             make_source=lambda target: twin.source.FakeSource({}), clock=clock, out=out, frozen=frozen)
    assert (rc, working.connects) == (4, 0) and [json.loads(line)["why"] for line in out.getvalue().splitlines()] == ["spacing"]


def _raises(exc: BaseException) -> Callable[..., Any]:
    def factory(*_args: Any) -> Any:
        raise exc

    return factory


def contained(call: Callable[..., Any], **kwargs: Any) -> Any:
    """call(**kwargs), with a SystemExit or a KeyboardInterrupt that leaves it turned into a failure of the test that
    called: left alone, a KeyboardInterrupt ends the whole pytest run, and a run that ended reads as nothing."""
    try:
        return call(**kwargs)
    except (SystemExit, KeyboardInterrupt) as exc:
        pytest.fail("a %s left the connector, where an error of any class ends as a log line and a status" % type(exc).__name__,
                    pytrace=False)


def test_an_error_before_the_loop_ends_as_a_status_and_one_fixed_line_and_never_as_its_text(twin, frozen, tmp_path, capsys, monkeypatch):
    """Whatever is raised while the connector is put together (the frozen module, the schema, the two factories)
    leaves the process as an exit status and one line that was written beforehand. A traceback would print the error's
    text, and that text can name the key's path, the endpoint or the thing: uplink_aws.py is told that it may."""
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    clock.on_sleep.append(_raises(AssertionError("the loop began: nothing refused this connector")))
    garbled, no_schema, absent = tmp_path / "garbled.json", tmp_path / "list.json", tmp_path / "device.key" / "appstate.schema.json"
    garbled.write_text('{"properties": ' + SECRET, encoding="utf-8")
    no_schema.write_text(json.dumps([SECRET]), encoding="utf-8")
    lacking = []          # a JSON object, but one of the three keywords the validator reads is not in it
    for keyword in ("properties", "propertyNames", "required"):
        lacking.append(tmp_path / ("lacks-%s.json" % keyword))
        lacking[-1].write_text(json.dumps(dict({k: v for k, v in SCHEMA.items() if k != keyword}, title=SECRET)), encoding="utf-8")
    handedit = tmp_path / "handedit"
    handedit.mkdir()
    (handedit / "twin_allowlist.py").write_text("raise ValueError(%r)\n" % SECRET, encoding="utf-8")

    def settings(schema: Path) -> Dict[str, str]:
        return {"SDV_TWIN_THING": THING, "SDV_TWIN_RULE": RULE, "SDV_TWIN_SPOOL": str(tmp_path), "SDV_TWIN_SCHEMA": str(schema),
                "SDV_TWIN_ENDPOINT": "broker.example.invalid", "SDV_TWIN_KEY": "/run/sdv-local/device/device.key",
                "SDV_TWIN_STATUS": str(tmp_path / "no-status-of-this-test")}

    def run(make_uplink: Any = None, make_source: Any = None, schema: Path = SCHEMA_FILE, allow: Any = frozen) -> Tuple[int, List[Any], str]:
        out = io.StringIO()
        rc = twin.connector.main([], env=settings(schema), make_uplink=make_uplink or (lambda e, topics: twin.uplink.FakeUplink(clock=clock)),
                                 make_source=make_source or (lambda target: twin.source.FakeSource({})), clock=clock, out=out, frozen=allow)
        captured = capsys.readouterr()
        for word in SECRET_WORDS + (str(tmp_path), "garbled", "handedit"):
            assert word not in out.getvalue() + captured.out + captured.err, word
        assert captured.out == "" and captured.err.count("\n") <= 1
        return rc, [json.loads(line) for line in out.getvalue().splitlines()], captured.err

    U, R = twin.uplink.UplinkError, twin.connector.REFUSALS
    assert set(R) == {"argument", "names", "allowlist", "schema", "sdk", "uplink", "databroker"}
    assert "uplink_aws.py" in R["sdk"] and "SDV_TWIN_SCHEMA" in R["schema"] and "twin_allowlist.py" in R["allowlist"] and "grpc" in R["databroker"]
    # a setting, or a part of the build, that is missing or wrong: status 2 and its one sentence on stderr, nothing in the log
    for case, kwargs, why in (
            ("the uplink's factory refuses its settings", {"make_uplink": _raises(U(SECRET))}, "uplink"),
            ("the build holds no uplink module", {"make_uplink": _raises(ImportError("No module named 'uplink_aws': " + SECRET))}, "sdk"),
            ("the build holds no databroker client", {"make_source": _raises(ImportError("No module named 'grpc': " + SECRET))}, "databroker"),
            ("the schema file is absent", {"schema": absent}, "schema"),
            ("the schema file is not JSON", {"schema": garbled}, "schema"),
            ("the schema file holds no schema", {"schema": no_schema}, "schema"),
            ("the schema file is an object without `properties`", {"schema": lacking[0]}, "schema"),
            ("the schema file is an object without `propertyNames`", {"schema": lacking[1]}, "schema"),
            ("the schema file is an object without `required`", {"schema": lacking[2]}, "schema")):
        rc, lines, err = run(**kwargs)
        assert (rc, lines, err) == (2, [], "connector: %s\n" % R[why]), case
    # the frozen module, when the entry point has to import it itself: absent, or refusing to import (its own check)
    monkeypatch.setitem(sys.modules, "twin_allowlist", None)
    assert run(allow=None) == (2, [], "connector: %s\n" % R["allowlist"])
    monkeypatch.delitem(sys.modules, "twin_allowlist")
    monkeypatch.syspath_prepend(str(handedit))
    assert run(allow=None) == (2, [], "connector: %s\n" % R["allowlist"]) and "twin_allowlist" not in sys.modules
    # only the table's sentences are ever printed: a refusal that carried a text of its own would not get it out
    assert run(make_uplink=_raises(twin.connector._Refused(SECRET))) == (2, [], "connector: it cannot be put together\n")
    # an error of a class nobody expected: status 3 and the log's error line, its class and where it was raised
    for case, kwargs in (("the uplink's factory", {"make_uplink": _raises(SdkError(SECRET))}),
                         ("the source's factory", {"make_source": _raises(SdkError(SECRET))})):
        rc, lines, err = run(**kwargs)
        assert rc == 3 and err == "" and len(lines) == 1, case
        (error,) = lines
        assert error == {"event": "error", "t": 1000.0, "error": "SdkError", "where": error["where"]}, case
        assert all(re.fullmatch(r"[a-z_]+\.py:\d+", frame) for frame in error["where"]) and len(error["where"]) >= 3
        assert error["where"][0].startswith("connector.py:") and error["where"][-1].startswith("test_sdv_connector.py:")
    # "Of any class" means of any class: one that is no Exception at all (a library that raises SystemExit or a
    # KeyboardInterrupt of its own, with a text) ends the same way. Left alone, SystemExit prints its text on stderr and
    # KeyboardInterrupt a traceback with it.
    for raised in (SystemExit(SECRET), KeyboardInterrupt(SECRET)):
        for kwargs in ({"make_uplink": _raises(raised)}, {"make_source": _raises(raised)}):
            rc, lines, err = contained(run, **kwargs)
            assert (rc, err) == (3, "") and [(rec["event"], rec["error"]) for rec in lines] == [("error", type(raised).__name__)], raised
            assert lines[0]["where"][0].startswith("connector.py:") and lines[0]["where"][-1].startswith("test_sdv_connector.py:")
    # The one thing passed on: a KeyboardInterrupt that carries no text, which is what the interpreter itself raises for
    # a SIGINT that comes before the connector's own handlers are installed. Nothing of it is logged or printed here.
    with pytest.raises(KeyboardInterrupt):
        run(make_uplink=_raises(KeyboardInterrupt()))
    assert capsys.readouterr() == ("", "")
    # and when the log itself cannot be written (stdout is gone), one sentence on stderr is all that is left to say
    gone = io.StringIO()
    gone.close()
    fake = twin.uplink.FakeUplink(clock=clock)
    assert twin.connector.main([], env=settings(SCHEMA_FILE), make_uplink=lambda e, topics: fake,
                               make_source=lambda target: twin.source.FakeSource({}), clock=clock, out=gone, frozen=frozen) == 3
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "connector: an error nobody expected, and the log cannot be written\n")
    assert fake.connects == 0 and fake.published == []                             # the start line comes first: nothing was opened


@pytest.mark.parametrize("stage, error, status, event", [
    ("connect", "SdkError", 3, "error"), ("subscribe", "SdkError", 3, "error"), ("publish", "SdkError", 3, "error"),
    ("connect", "SystemExit", 3, "error"), ("subscribe", "KeyboardInterrupt", 3, "error"), ("publish", "SystemExit", 3, "error"),
    ("connect", "UplinkError", 1, "connect-failed"), ("subscribe", "UplinkError", 1, "connect-failed")])
def test_an_error_while_the_connection_is_opened_ends_the_run_by_its_class_and_never_by_its_text(
        twin, frozen, tmp_path, capsys, stage, error, status, event):
    """connect, the five subscriptions and the first get come before the loop. An UplinkError at connect or at a
    subscription means the uplink could not be opened (status 1). An error of any other class, anywhere there (an
    SDK's own, which uplink_aws.py failed to wrap; or one that is no Exception at all, with a text), is the loop's
    unexpected error: status 3, its class and where it was raised. Neither prints a traceback. An UplinkError at the
    first get is neither: it is a failed publish, and the run goes on (the next test)."""
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    raised = {"SdkError": SdkError, "UplinkError": twin.uplink.UplinkError, "SystemExit": SystemExit, "KeyboardInterrupt": KeyboardInterrupt}[error]

    class Failing(twin.uplink.FakeUplink):
        def connect(self, on_resumed: Any = None) -> None:
            if stage == "connect":
                raise raised("AWS_IO_TLS_ERROR_NEGOTIATION_FAILURE: " + SECRET)
            super().connect(on_resumed)

        def subscribe(self, topic: str, callback: Any) -> None:
            if stage == "subscribe":
                raise raised("subscribe to %s: %s" % (topic, SECRET))
            super().subscribe(topic, callback)

        def publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
            if stage == "publish":
                raise raised("publish to %s: %s" % (topic, SECRET))
            super().publish(topic, payload, qos)

    fake, src, out = Failing(clock=clock), twin.source.FakeSource(normal_values(frozen)), io.StringIO()
    assert contained(_entry(twin, frozen, tmp_path, src, fake, clock, out, {})) == status
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [rec["event"] for rec in lines] == ["start", event] and lines[1]["error"] == error
    if status == 3:
        assert set(lines[1]) == {"event", "t", "error", "where"}
        assert all(re.fullmatch(r"[a-z_]+\.py:\d+", frame) for frame in lines[1]["where"])
        assert lines[1]["where"][0].startswith("connector.py:") and lines[1]["where"][-1].startswith("test_sdv_connector.py:")
    else:
        assert set(lines[1]) == {"event", "t", "error"}
    assert fake.published == [] and fake.closes == 1 and src.closed == 1 and src.calls == []
    captured = capsys.readouterr()
    for word in SECRET_WORDS + ("$aws", "shadow/name", "AWS_IO"):
        assert word not in out.getvalue() + captured.out + captured.err, word
    assert captured.out == "" and captured.err == ""


def test_an_uplink_error_at_the_first_get_is_a_failed_publish_and_the_run_goes_on(twin, frozen, tmp_path, capsys):
    """The connection is open and the subscriptions are made; the get is a publish like any other. When the uplink
    fails it (here with every other publish of the first ten seconds), that is no failed connect: the log says
    publish-failed, the connector goes on with the defaults once the get's wait is over, exits 0 at the stop, and has
    asked again one retry spacing after the failure. (The docstring said connect-failed and status 1; the code never
    did that.)"""
    L = twin.limits
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    fake = twin.uplink.FakeUplink(clock=clock)
    FakeShadow(fake)
    fake.fail_publish = lambda topic, payload: ("publish to %s: %s" % (topic, SECRET)) if clock.monotonic() < 1010.0 else None
    handlers: Dict[int, Any] = {}
    clock.on_sleep.append(lambda c: c.monotonic() >= 1070.0 and handlers[signal.SIGTERM](signal.SIGTERM, None))
    src, out = twin.source.FakeSource(normal_values(frozen)), io.StringIO()
    assert _entry(twin, frozen, tmp_path, src, fake, clock, out, handlers)() == 0
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    events = [rec["event"] for rec in lines]
    assert events[:3] == ["start", "publish-failed", "config-get"] and events[-1] == "stop" and "connect-failed" not in events
    assert lines[1] == {"event": "publish-failed", "t": 1000.0, "what": "get", "error": "UplinkError"}
    assert lines[2] == {"event": "config-get", "t": 1000.0 + L.CONFIG_GET_WAIT_S, "outcome": "timeout"}
    assert [rec["what"] for rec in lines if rec["event"] == "publish-failed"] == ["get"]          # one attempt, not one per step
    again = 1000.0 + L.SHADOW_RETRY_S
    assert [(p.topic, p.t) for p in fake.published if p.topic != TELEMETRY_TOPIC][:3] == [
        (CONFIG_GET, again), (VSS_UPDATE, again), (CONFIG_UPDATE, again)]
    counters = lines[-1]["counters"]
    assert (counters["failed_get"], counters["sent_get"], counters["refused_get"], lines[-1]["limiter"]) == (1, 1, 0, {})
    assert fake.connects == 1 and fake.closes == 1 and src.calls == [tuple(frozen.PATHS)]
    captured = capsys.readouterr()
    for word in SECRET_WORDS + ("$aws", "shadow/name"):
        assert word not in out.getvalue() + captured.out + captured.err, word
    assert (captured.out, captured.err) == ("", "")


ENTRY_DRIVER = '''\
import sys

sys.dont_write_bytecode = True
connector_dir, twin_dir, stub_dir, spool, schema = sys.argv[1:6]
sys.path[:0] = [connector_dir, twin_dir, stub_dir]          # as in the image: uplink_aws.py beside the modules
import connector
import source

env = {"SDV_TWIN_THING": "example-thing", "SDV_TWIN_RULE": "example_rule", "SDV_TWIN_SPOOL": spool, "SDV_TWIN_SCHEMA": schema,
       "SDV_TWIN_ENDPOINT": "broker.example.invalid", "SDV_TWIN_KEY": "/run/sdv-local/device/device.key",
       "SDV_TWIN_STATUS": spool + "-no-status"}
sys.exit(connector.main([], env=env, make_source=lambda target: source.FakeSource({})))
'''

STUB_UPLINK = '''\
"""A stand-in for the module that talks to the SDK. It fails the way MODE says, with a text that names everything."""
import uplink


class SdkError(Exception):
    """Somebody else's exception class: no UplinkError."""


class Broken:
    def __init__(self, text):
        self.text = text

    def connect(self, on_resumed=None):
        raise SdkError("AWS_IO_TLS_ERROR_NEGOTIATION_FAILURE: " + self.text)

    def close(self):
        pass


def from_env(env, topics):
    text = "cannot read %s for %s:8883 (client id %s)" % (env["SDV_TWIN_KEY"], env["SDV_TWIN_ENDPOINT"], topics.client_id)
    if MODE == "settings":
        raise uplink.UplinkError(text)
    if MODE == "no-sdk":
        import no_such_sdk_package
    if MODE == "exit":
        raise SystemExit(text)
    if MODE == "interrupt":
        raise KeyboardInterrupt(text)
    return Broken(text)
'''


@pytest.mark.parametrize("mode, status", [("settings", 2), ("no-sdk", 2), ("absent", 2), ("connect", 3), ("exit", 3), ("interrupt", 3),
                                          ("too-soon", 4)])
def test_the_real_entry_point_as_a_process_prints_no_traceback_when_its_uplink_cannot_be_built_or_opened(
        twin, frozen, tmp_path, mode, status):
    """The same in a process of its own, where a traceback would show: connector.main with no uplink factory handed
    in, so it imports uplink_aws by name as the image does. The module is a stand-in that refuses its settings, lacks
    its SDK, is absent, returns an uplink whose connect raises an SDK's own class, or raises a class that is no
    Exception at all with the text in it (SystemExit, which Python would print; KeyboardInterrupt, which it would trace
    back). In the last case the spool directory holds the stamp of a start a second ago, by the system's wall clock: the
    start is refused before that connect is ever called."""
    driver, staged, stub_dir, spool = tmp_path / "driver.py", tmp_path / "staged", tmp_path / "stub", tmp_path / "spool"
    for directory in (staged, stub_dir, spool):
        directory.mkdir()
    driver.write_text(ENTRY_DRIVER, encoding="utf-8")
    for name in WP2_MODULES + ("appstate",):          # the logic's modules side by side, as an image stages them, and no uplink_aws.py
        (staged / (name + ".py")).write_bytes((CONNECTOR_DIR / (name + ".py")).read_bytes())
    if mode != "absent":
        (stub_dir / "uplink_aws.py").write_text(STUB_UPLINK + "\n\nMODE = %r\n" % mode, encoding="utf-8")
    recorded = b'{"started_ms":%d}' % (int(time.time() * 1000) - 1000)          # a second ago: a small step of the clock changes nothing
    if mode == "too-soon":
        (spool / STAMP).write_bytes(recorded)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SDV_")}
    proc = subprocess.run([sys.executable, "-B", str(driver), str(staged), str(TWIN_FROZEN.parent), str(stub_dir), str(spool),
                           str(SCHEMA_FILE)], capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == status, (proc.stdout, proc.stderr)
    for word in SECRET_WORDS + ("AWS_IO", "no_such_sdk_package", str(tmp_path)):
        assert word not in proc.stdout + proc.stderr, word
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    if status == 2:          # nothing was started: one fixed line, and no log
        assert lines == [] and proc.stderr.startswith("connector: ") and proc.stderr.count("\n") == 1
        assert ("uplink_aws.py" in proc.stderr) == (mode != "settings")
    elif status == 4:          # refused by the stamp: one log line, nothing opened (the stand-in's connect would have raised)
        assert [(rec["event"], rec["why"]) for rec in lines] == [("start-refused", "spacing")] and proc.stderr == ""
        assert 60.0 < lines[0]["retry_after_s"] <= 119.0 and (spool / STAMP).read_bytes() == recorded
    elif mode == "connect":
        assert [rec["event"] for rec in lines] == ["start", "error"] and proc.stderr == ""
        assert lines[1]["error"] == "SdkError" and lines[1]["where"][0].startswith("connector.py:")
        assert lines[1]["where"][-1].startswith("uplink_aws.py:")
    else:          # raised while the uplink was built, before any start: the error line and nothing else, on either stream
        assert [(rec["event"], rec["error"]) for rec in lines] == [("error", {"exit": "SystemExit", "interrupt": "KeyboardInterrupt"}[mode])]
        assert lines[0]["where"][0].startswith("connector.py:") and lines[0]["where"][-1].startswith("uplink_aws.py:") and proc.stderr == ""
    # what could not be put together never started, and wrote nothing; the one that got as far as connect left its stamp
    assert [p.name for p in spool.iterdir()] == ([STAMP] if mode in ("connect", "too-soon") else [])


@pytest.mark.parametrize("raised", [RuntimeError, SystemExit, KeyboardInterrupt], ids=lambda c: c.__name__)
def test_an_error_nobody_expected_ends_the_loop_logged_by_class_and_place_and_never_by_its_text(twin, frozen, tmp_path, capsys, raised):
    """No traceback reaches the container's log: an error's text can name anything. What was already sampled still
    goes out; the source is not read again. The same for a class that is no Exception at all, raised with a text."""
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    fake = twin.uplink.FakeUplink(clock=clock)
    FakeShadow(fake)
    secret = "cannot reach broker.example.invalid with /run/sdv-local/device/device.key"

    class Breaking(twin.source.FakeSource):
        def latest(self):
            if self.reads >= 4:
                raise raised(secret)
            return super().latest()

    src = Breaking(normal_values(frozen))
    out = io.StringIO()
    assert contained(_entry(twin, frozen, tmp_path, src, fake, clock, out, {})) == 3
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [rec["event"] for rec in lines if rec["event"] in ("error", "batch", "stop")] == ["error", "batch", "stop"]
    (error,) = [rec for rec in lines if rec["event"] == "error"]
    assert set(error) == {"event", "t", "error", "where"} and error["error"] == raised.__name__
    assert all(re.fullmatch(r"[a-z_]+\.py:\d+", frame) for frame in error["where"]) and error["where"][0].startswith("connector.py:")
    assert error["where"][-1].startswith("test_sdv_connector.py:")
    (batch,) = [json.loads(p.payload) for p in fake.published if p.topic == TELEMETRY_TOPIC]
    assert len(batch["rows"]) == 4 and src.reads == 4                             # the rows it had; the source not read again
    assert len([p for p in fake.published if p.topic == VSS_UPDATE]) == 1         # and no last document of values nobody has
    assert fake.closes == 1 and src.closed == 1
    captured = capsys.readouterr()
    for word in ("broker.example.invalid", "device.key", "Traceback", "cannot reach"):
        assert word not in out.getvalue() + captured.err + captured.out, word


SIGTERM_DRIVER = '''\
import json
import sys

sys.dont_write_bytecode = True
connector_dir, twin_dir, out_file, values_file, spool, schema = sys.argv[1:7]
sys.path[:0] = [connector_dir, twin_dir]          # as in the image: the modules and the frozen allowlist side by side
import connector
import source
import uplink


class Recording(uplink.FakeUplink):
    def publish(self, topic, payload, qos=1):
        super().publish(topic, payload, qos)
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(json.dumps([topic, payload.decode("utf-8")]) + "\\n")
        if topic.endswith("/config/get"):
            self.deliver(topic + "/rejected", b'{"code": 404}')


values = json.load(open(values_file, encoding="utf-8"))
env = {"SDV_TWIN_THING": "example-thing", "SDV_TWIN_RULE": "example_rule", "SDV_TWIN_SPOOL": spool, "SDV_TWIN_SCHEMA": schema,
       "SDV_TWIN_STATUS": spool + "-no-status"}
sys.exit(connector.main([], env=env, make_uplink=lambda e, topics: Recording(), make_source=lambda target: source.FakeSource(values)))
'''


def test_a_real_sigterm_ends_the_real_loop_with_one_last_flush(twin, frozen, tmp_path):
    """The one test here on the real clock and a real signal: a process running connector.main (its own signal
    handlers, the system clock, the frozen module imported by name as in the image) is sent SIGTERM. The waits bound
    the test; they are not timings.

    UNDER WINDOWS THIS TEST DOES NOT DO WHAT ITS NAME SAYS. Windows has no SIGTERM a process can handle, so there the
    same path runs in this process, on the manual clock, with the handler the entry point installed called by hand:
    no real signal, no real clock, no second process. A Windows run of this file therefore says nothing about a real
    signal; the POSIX branch does, and CI runs in WSL."""
    if os.name != "posix":
        clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
        fake = twin.uplink.FakeUplink(clock=clock)
        FakeShadow(fake)
        handlers: Dict[int, Any] = {}
        clock.on_sleep.append(lambda c: c.monotonic() >= 1002.5 and handlers[signal.SIGTERM](signal.SIGTERM, None))
        out = io.StringIO()
        src = twin.source.FakeSource(normal_values(frozen))
        assert _entry(twin, frozen, tmp_path, src, fake, clock, out, handlers)() == 0
        assert [p.topic for p in fake.published][-2:] == [TELEMETRY_TOPIC, VSS_UPDATE]
        return
    driver, out_file, values_file = tmp_path / "driver.py", tmp_path / "published.jsonl", tmp_path / "values.json"
    spool = tmp_path / "spool"
    spool.mkdir()
    driver.write_text(SIGTERM_DRIVER, encoding="utf-8")
    values_file.write_text(json.dumps(normal_values(frozen)), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SDV_")}
    proc = subprocess.Popen([sys.executable, "-B", str(driver), str(CONNECTOR_DIR), str(TWIN_FROZEN.parent), str(out_file),
                             str(values_file), str(spool), str(SCHEMA_FILE)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)
    try:
        assert _wait(lambda: out_file.is_file() and out_file.read_text(encoding="utf-8").count("\n") >= 3, 30)
        time.sleep(2.2)                                                           # a few 1 Hz samples into the open batch
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, stderr
    published = [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines()]
    assert [t for t, _p in published] == [CONFIG_GET, VSS_UPDATE, CONFIG_UPDATE, TELEMETRY_TOPIC, VSS_UPDATE]
    batch = json.loads(published[3][1])
    assert 2 <= len(batch["rows"]) < 60 and batch["appstate"] == [EXAMPLE] and all(len(row) == 8 for row in batch["rows"])
    assert abs(batch["rows"][0][0] - time.time() * 1000) < 120_000                # Linux-host milliseconds, from the system clock
    lines = [json.loads(line) for line in stdout.splitlines()]
    assert lines[0]["event"] == "start" and lines[-1]["event"] == "stop" and lines[-1]["signal"] == int(signal.SIGTERM)
    assert stderr == "" and [p.name for p in spool.iterdir()] == [STAMP]
    stamp = json.loads((spool / STAMP).read_text(encoding="utf-8"))
    assert set(stamp) == {"started_ms"} and abs(stamp["started_ms"] - time.time() * 1000) < 120_000          # the system's wall clock


# ============================================================ sizes, for WP5

def test_the_largest_batch_at_each_rate_and_the_largest_shadow_documents_are_under_the_bounds(twin, frozen):
    """Computed, not measured: every value at its longest JSON text, every row and key present."""
    E, S, L = twin.envelope, twin.shadowdoc, twin.limits
    tpaths = E.telemetry_paths(frozen, frozen.PATHS)
    longest = {"float": -1.7976931348623157e+308, "int8": -128, "uint16": 65535, "boolean": True}
    assert len(json.dumps(longest["float"])) == 24                                # no finite double prints longer
    record = {"schema_version": 1, "app": "a" + "b" * 31, "app_version": "999.999.999", "image_id": "sha256:" + "f" * 64,
              "seq": 4294967295, "state": "degraded", "hazard_requested": False, "actuate_result": "unavailable"}
    assert twin.appstate.validate(SCHEMA, record) == [] and len(json.dumps(record, separators=(",", ":"))) < 320
    values = {p: longest[frozen.NODES[p][1]] for p in frozen.PATHS if p not in frozen.APPSTATE_FIELDS}
    row = E.row(9_999_999_999_999, tpaths, values, frozen.NODES)
    row_bytes = len(json.dumps(row, separators=(",", ":"))) + 1                   # and its comma
    sizes = {}
    for rate in L.RATES_HZ:
        rows = [row] * L.batch_ticks(rate)
        sizes[rate] = len(E.encode(E.batch(2 ** 53, tpaths, rows, [record] * len(frozen.APPSTATE_BRANCHES))))
        assert sizes[rate] <= L.TELEMETRY_MAX_BYTES, (rate, sizes[rate])
    overhead = sizes[1] - 60 * row_bytes + 1
    assert sizes[10] - sizes[1] == 40 * row_bytes
    # a representative batch: float32 values as the databroker hands them over (a float32 widened to a double)
    def f32(x):
        return struct.unpack("<f", struct.pack("<f", x))[0]

    typical = {}
    for rate in L.RATES_HZ:
        rows = []
        for k in range(L.batch_ticks(rate)):
            vals = {p: (f32(13.37 + 0.731 * k + i) if frozen.NODES[p][1] == "float" else 3 if frozen.NODES[p][1] == "int8" else True)
                    for i, p in enumerate(tpaths)}
            rows.append(E.row(T0_MS + k * (1000 // rate), tpaths, vals, frozen.NODES))
        typical[rate] = len(E.encode(E.batch(1234, tpaths, rows, [EXAMPLE])))
    record_by_leaf = {branch: record for branch in frozen.APPSTATE_BRANCHES}
    shadow_values = dict(values, **{p: False for p in values if frozen.NODES[p][1] == "boolean"})
    vss = len(S.reported(S.vss_state(frozen, frozen.PATHS, shadow_values, record_by_leaf)))
    vss_null = len(S.reported(S.vss_state(frozen, (), {}, {})))
    config = len(S.reported(S.config_state(10, frozen.PATHS)))
    assert vss_null < vss <= L.SHADOW_MAX_BYTES and config <= L.SHADOW_MAX_BYTES
    # Held, because WP5 derives from them: a change of the envelope's or the document's shape must show here. 1032 is
    # WP1's A11 bound of 1034 less two characters (A11 put schema_version at its datatype's bound, the schema fixes it at 1).
    assert (sizes[1], sizes[10], row_bytes, overhead, vss, vss_null, config) == (9467, 15387, 148, 588, 1032, 803, 746)
    print("WP2 sizes (computed from the envelope and the shadow document, not measured; bytes):")
    print("WP2 sizes: largest batch at 1 Hz (60 rows) %d, at 10 Hz (100 rows) %d; bound %d; a row at most %d, the rest %d"
          % (sizes[1], sizes[10], L.TELEMETRY_MAX_BYTES, row_bytes, overhead))
    print("WP2 sizes: a representative batch (synthetic float32 values) at 1 Hz %d, at 10 Hz %d; about %d a row"
          % (typical[1], typical[10], round((typical[10] - typical[1]) / 40.0)))
    print("WP2 sizes: largest vss document %d (every key null: %d), largest config report %d; bound %d"
          % (vss, vss_null, config, L.SHADOW_MAX_BYTES))
    print("WP2 sizes: limiter worst case in %(window_s)d s: %(telemetry_publishes)d telemetry publishes, %(telemetry_bytes)d bytes; "
          "%(shadow_publishes)d shadow publishes, %(shadow_bytes)d bytes" % L.worst_case())


# ====================================================================================================================
# WP3: the SDK uplink (uplink_aws.py) on a stand-in for the SDK, and the image's build (Dockerfile, build_image.py)
# against a replaced docker. No SDK is imported, nothing is built and nothing connects here. The real SDK at a local
# broker, the built image and the stack's full slice are tests/test_sdv_connector_broker.py (opt-in).
# ====================================================================================================================

UPLINK_AWS = CONNECTOR_DIR / "uplink_aws.py"
BUILD_IMAGE = CONNECTOR_DIR / "build_image.py"
DOCKERFILE = CONNECTOR_DIR / "Dockerfile"
ENDPOINT = "broker.example.invalid"          # a reserved name: nothing answers to it
SDK_METRICS_USER = "?SDK=IoTDeviceSDK/Python&Platform=Unix&Metadata=(a stand-in for what the SDK appends)"
STAGED_MODULES = WP2_MODULES + ("appstate", "uplink_aws")


class SdkFailure(Exception):
    """The SDK's own error class, as its AwsCrtError is one: no UplinkError, and its text names everything."""

    def __init__(self, name: str) -> None:
        super().__init__("%s: %s" % (name, SECRET))
        self.name = name


class FakeFuture(concurrent.futures.Future):          # type: ignore[type-arg]
    """The SDK's answer to one request. It records how long its user was ready to wait for it (sdk.waits: the request's
    kind and the time-out result() was given), and `at_wait` runs once when its user first waits: what happens between
    the SDK's answer and its user taking it."""

    def __init__(self, sdk: "FakeSdk", kind: str) -> None:
        super().__init__()
        self._sdk, self._kind = sdk, kind
        self.at_wait: Optional[Callable[[], Any]] = None

    def result(self, timeout: Optional[float] = None) -> Any:
        self._sdk.waits.append((self._kind, timeout))
        hook, self.at_wait = self.at_wait, None
        if hook is not None:
            hook()
        return super().result(timeout)


class FakeSdkConnection:
    """One SDK connection, as the pinned SDK was seen to behave at the local broker (uplink_aws.py's docstring, cases 1
    to 3; the opt-in broker tests hold the real one to the same): acknowledged when the far end answers; failed and
    forgotten after its own time-out when the far end is silent; cancelled at a lost connection under a clean session,
    kept and sent again with DUP without one; QUEUED when it is handed over while the connection is down, and sent when
    the SDK has reconnected by itself. A connection its user disconnected never connects again and sends nothing. A
    disconnect is taken only on a connection that is up or reconnecting: while the SDK is still CONNECTING it refuses
    one and goes on connecting, and it may answer with a connection after its user stopped waiting (answer_connects)."""

    def __init__(self, sdk: "FakeSdk", number: int, cert: str, key: str, kwargs: Dict[str, Any]) -> None:
        self.sdk, self.number, self.cert, self.key, self.kwargs = sdk, number, cert, key, kwargs
        self.state = "new"          # new, connecting, up, reconnecting (lost: the SDK's own reconnect is pending), disconnected
        self.subs: Dict[str, Any] = {}
        self.held: List[Tuple[str, bytes, Any]] = []          # what the SDK holds and has not written
        self.inflight: List[Tuple[str, bytes, Any]] = []      # written, not acknowledged
        self.pending: Any = None                               # the answer to a connect the SDK is still working on
        self.lost_at: Optional[float] = None                   # when it was lost, on the stand-in's clock
        self.disconnects = 0
        self.packets = 0

    def _future(self, kind: str = "other") -> Any:
        return FakeFuture(self.sdk, kind)

    def _call(self, name: str, **kwargs: Any) -> None:
        callback = self.kwargs.get(name)
        if callback is not None:
            callback(connection=self, **kwargs)

    def _connected(self, resumed: bool = False) -> None:
        k = self.kwargs
        # the far end keeps one connection for a client id: a CONNECT under an id that is connected closes the older one
        for other in self.sdk.built:
            if other is not self and other.state == "up" and other.kwargs["client_id"] == k["client_id"]:
                self.sdk.takeovers += 1
                self.sdk.lose(conn=other)
        metrics = k.get("enable_metrics_collection")
        metrics = True if metrics is None else bool(metrics)          # the builder's own reading of the keyword
        user = (k.get("username") or "") + (SDK_METRICS_USER if metrics else "")
        # the CONNECT packet as the far end sees it, with the SDK's defaults for whatever its caller left out
        self.sdk.connects.append({"connection": self.number, "host": k["endpoint"], "port": 443 if k.get("port") is None else k["port"],
                                  "client_id": k["client_id"], "clean": bool(k.get("clean_session") or False),
                                  "keep_alive": 1200 if k.get("keep_alive_secs") is None else k["keep_alive_secs"],
                                  "user": user or None, "will": k.get("will"), "resumed": resumed})
        self.state, self.subs = "up", ({} if k.get("clean_session") else self.subs)
        if resumed:
            self._call("on_connection_resumed", return_code=0, session_present=False)
        self._call("on_connection_success", callback_data=types.SimpleNamespace(return_code=0, session_present=False))

    def connect(self) -> Any:
        self.sdk.calls.append(("connect", self.number))
        future = self._future("connect")
        how = self.sdk.connect_fails
        if how == "hangs":                                 # still connecting when its user stops waiting; answered by answer_connects
            self.state, self.pending = "connecting", future
            if self.sdk.connect_wait_raises is not None:   # the wait itself is ended by this error (a KeyboardInterrupt)
                future.at_wait = _raises(self.sdk.connect_wait_raises)
            return future
        if how and how != "lost":
            self.state = "disconnected"                    # a first connect the SDK failed is not tried again by it
            future.set_exception(SdkFailure(how))
            return future
        self._connected()
        future.set_result({"session_present": False})
        if how == "lost":                                  # connected, answered, and lost before its user has taken the answer
            future.at_wait = self.sdk.lose
        return future

    def publish(self, topic: str, payload: Any, qos: Any, retain: bool = False) -> Any:
        self.sdk.calls.append(("publish", topic, self.number))
        assert qos is self.sdk.QoS.AT_LEAST_ONCE and retain is False and isinstance(payload, bytes)
        future = self._future("publish")
        self.packets += 1
        entry = (topic, payload, future)
        how = self.sdk.far_end
        if self.state != "up" or how == "mute":          # case 3 (queued for the next connection), or an SDK that just holds it
            self.held.append(entry)
        elif how == "answers":
            self.sdk.arrive(self, topic, payload, False)
            future.set_result({"packet_id": self.packets})
        elif how == "silent":                              # case 1: written, no answer, the SDK's own time-out; forgotten
            self.sdk.arrive(self, topic, payload, False, answered=False)
            future.set_exception(SdkFailure("AWS_ERROR_MQTT_TIMEOUT"))
        else:                                              # "lost": written, and the connection is lost before the answer (case 2)
            self.sdk.arrive(self, topic, payload, False, answered=False)
            self.inflight.append(entry)
            self.sdk.lose()
        return future, self.packets

    def subscribe(self, topic: str, qos: Any, callback: Any = None) -> Any:
        self.sdk.calls.append(("subscribe", topic, self.number))
        assert qos is self.sdk.QoS.AT_LEAST_ONCE
        future = self._future("subscribe")
        how = self.sdk.subscribe_fails
        if self.state != "up" or how == "hangs":
            return future, 1
        if how:
            future.set_exception(SdkFailure(how))
            return future, 1
        self.subs[topic] = callback
        future.set_result({"packet_id": 1, "topic": topic, "qos": qos})
        return future, 1

    def disconnect(self) -> Any:
        self.sdk.calls.append(("disconnect", self.number))
        self.disconnects += 1
        future = self._future("disconnect")
        if self.state in ("up", "reconnecting"):
            self.state = "disconnected"
            future.set_result({})
        else:          # new, connecting, disconnected: refused by the SDK, and a connect it is working on goes on
            future.set_exception(SdkFailure("AWS_ERROR_MQTT_NOT_CONNECTED"))
        return future


class FakeSdk:
    """A stand-in for the two SDK modules uplink_aws.py uses and for the far end behind them: every request the SDK was
    handed (calls), every connection it built (built), every CONNECT (connects) and every PUBLISH packet (wire) the far
    end saw. FakeShadow can stand behind it (on_publish, deliver)."""

    def __init__(self, clock: Any = None) -> None:
        self.clock = clock
        self.QoS = types.SimpleNamespace(AT_MOST_ONCE=object(), AT_LEAST_ONCE=object(), EXACTLY_ONCE=object())
        self.built: List[FakeSdkConnection] = []
        self.calls: List[Tuple[Any, ...]] = []
        self.connects: List[Dict[str, Any]] = []
        self.wire: List[Any] = []
        self.far_end = "answers"          # answers, silent, lost, mute
        self.connect_fails: Optional[str] = None          # an SDK error's name; "hangs"; "lost": connected, and lost before its user took the answer
        self.connect_wait_raises: Optional[BaseException] = None          # with "hangs": what ends its user's wait for the answer
        self.subscribe_fails: Optional[str] = None
        self.on_publish: Optional[Callable[[str, bytes], None]] = None
        self.unreported: List[FakeSdkConnection] = []          # lost, and the SDK has not called its user back yet
        self.waits: List[Tuple[str, Optional[float]]] = []     # every wait for an answer of the SDK: the request's kind, the time-out
        self.takeovers = 0                                     # connections the far end closed for a newer one of the same client id

    def modules(self) -> Tuple[Any, Any]:
        def other(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("the uplink builds its connection with mtls_from_path and with nothing else")

        builder = types.SimpleNamespace(mtls_from_path=self.mtls_from_path, mtls_from_bytes=other, mtls_with_pkcs11=other,
                                        mtls_with_pkcs12=other, websockets_with_default_aws_signing=other,
                                        websockets_with_custom_handshake=other, direct_with_custom_authorizer=other,
                                        websockets_with_custom_authorizer=other, new_default_builder=other)
        return types.SimpleNamespace(QoS=self.QoS), builder

    def mtls_from_path(self, cert_filepath: str, pri_key_filepath: str, **kwargs: Any) -> FakeSdkConnection:
        for required in ("endpoint", "client_id"):          # the builder's own check
            if not kwargs.get(required):
                raise TypeError("Builder needs keyword-only argument '%s'" % required)
        conn = FakeSdkConnection(self, len(self.built) + 1, cert_filepath, pri_key_filepath, kwargs)
        self.built.append(conn)
        return conn

    def arrive(self, conn: FakeSdkConnection, topic: str, payload: bytes, dup: bool, answered: bool = True) -> None:
        t = self.clock.monotonic() if self.clock is not None else None
        self.wire.append(types.SimpleNamespace(topic=topic, payload=bytes(payload), dup=dup, connection=conn.number, t=t))
        if answered and self.on_publish is not None:
            self.on_publish(topic, bytes(payload))

    def live(self) -> Optional[FakeSdkConnection]:
        up = [c for c in self.built if c.state == "up"]
        assert len(up) <= 1, "two connections under one client id"
        return up[0] if up else None

    def answer_connects(self, how: Optional[str] = None) -> int:
        """The SDK answers every connect it was still working on: with a connection, or with the error `how`. Returns
        how many it answered."""
        answered = 0
        for conn in list(self.built):
            if conn.state != "connecting":
                continue
            answered += 1
            if how:
                conn.state = "disconnected"
                conn.pending.set_exception(SdkFailure(how))
            else:
                conn._connected()
                conn.pending.set_result({"session_present": False})
        return answered

    def lose(self, silently: bool = False, conn: Optional[FakeSdkConnection] = None) -> None:
        """The connection is lost. Under a clean session the SDK cancels what was in flight; then it calls its user's
        interrupted callback (later, with `silently`: the race between the loss and the callback)."""
        conn = self.live() if conn is None else conn
        assert conn is not None
        conn.state = "reconnecting"
        conn.lost_at = self.clock.monotonic() if self.clock is not None else None
        if conn.kwargs.get("clean_session"):
            for _topic, _payload, future in conn.inflight:
                future.set_exception(SdkFailure("AWS_ERROR_MQTT_CANCELLED_FOR_CLEAN_SESSION"))
            conn.inflight = []
        if silently:
            self.unreported.append(conn)
        else:
            conn._call("on_connection_interrupted", error=SdkFailure("AWS_IO_SOCKET_CLOSED"))

    def report(self) -> None:
        """The interrupted callbacks that `lose(silently=True)` held back."""
        while self.unreported:
            self.unreported.pop(0)._call("on_connection_interrupted", error=SdkFailure("AWS_IO_SOCKET_CLOSED"))

    def come_back(self) -> None:
        """The far end can be reached again: every connection the SDK is still reconnecting comes back by itself, and
        what it kept goes out: what was in flight again, with DUP, then its queue."""
        for conn in self.built:
            if conn.state != "reconnecting":
                continue
            conn.state = "up"
            for topic, payload, future in conn.inflight:
                self.arrive(conn, topic, payload, True)
                future.set_result({"packet_id": 0})
            for topic, payload, future in conn.held:
                self.arrive(conn, topic, payload, False)
                future.set_result({"packet_id": 0})
            conn.inflight, conn.held = [], []
            conn._connected(resumed=True)

    def elapse(self) -> int:
        """The SDK's own reconnect timer, as the pinned SDK was seen to run it at the local broker (the hard review's
        wire run; the opt-in broker tests repeat it): a lost connection its user has not disconnected is tried again
        reconnect_min_timeout_secs after the loss (5 s when its user gave none; the far end is taken to be back). When
        that reconnect is answered the SDK WRITES ITS QUEUE FIRST and calls on_connection_resumed only then: a user
        that disconnects from that callback is too late for the queue, and what was written and not yet acknowledged
        is failed by the disconnect. Returns how many connections came back."""
        assert self.clock is not None
        back = 0
        for conn in self.built:
            timer = conn.kwargs.get("reconnect_min_timeout_secs")
            if conn.state != "reconnecting" or conn.lost_at is None or self.clock.monotonic() - conn.lost_at < (5 if timer is None else timer):
                continue
            back += 1
            written, conn.held = conn.held, []
            for topic, payload, _future in written:
                self.arrive(conn, topic, payload, False, answered=False)          # on the wire; its answer is still on its way
            conn._connected(resumed=True)                                         # the callback comes after the queue
            for topic, payload, future in written:
                if conn.state == "up":
                    future.set_result({"packet_id": 0})
                    if self.on_publish is not None:
                        self.on_publish(topic, bytes(payload))
                else:
                    future.set_exception(SdkFailure("AWS_ERROR_MQTT_CONNECTION_DISCONNECTING"))
        return back

    def unstick(self) -> None:
        """Whatever kept a connected SDK from writing is over: every connection that is up writes what it holds."""
        for conn in self.built:
            if conn.state == "up":
                for topic, payload, future in conn.held:
                    self.arrive(conn, topic, payload, False)
                    future.set_result({"packet_id": 0})
                conn.held = []

    def deliver(self, topic: str, payload: bytes) -> bool:
        """The far end publishes to the device: handed to the live connection's subscriber of exactly that topic."""
        conn = self.live()
        callback = conn.subs.get(topic) if conn is not None else None
        if callback is None:
            return False
        callback(topic=topic, payload=payload, dup=False, qos=self.QoS.AT_LEAST_ONCE, retain=False)
        return True

    def published(self, topic: Optional[str] = None) -> List[bytes]:
        return [p.payload for p in self.wire if topic is None or p.topic == topic]


@pytest.fixture
def aws(twin) -> Any:
    """uplink_aws.py, loaded by its file under a name of this test file's. The module's own name is not left in
    sys.modules: the import-graph test holds that importing the logic brings no uplink module in."""
    name = "sdv_connector_uplink_aws_under_test"
    mod = _load(name, UPLINK_AWS)
    assert mod.UplinkError is twin.uplink.UplinkError and mod.limits is twin.limits
    yield mod
    sys.modules.pop(name, None)


@pytest.fixture
def quick(twin, monkeypatch) -> Any:
    """The uplink's waits made short, for the tests that wait one out. (The values themselves are held by their test.)"""
    for name, value in (("OPERATION_TIMEOUT_S", 0.05), ("UPLINK_WAIT_MARGIN_S", 0.05), ("CONNECT_WAIT_S", 0.1), ("CLOSE_WAIT_S", 0.05)):
        monkeypatch.setattr(twin.limits, name, value)
    return twin.limits


def device_env(aws: Any, tmp_path: Path) -> Dict[str, str]:
    device = tmp_path / "device"
    device.mkdir(exist_ok=True)
    env = {aws.ENV_ENDPOINT: ENDPOINT}
    for name, file in ((aws.ENV_CERT, "device.crt"), (aws.ENV_KEY, "device.key"), (aws.ENV_CA, "ca.pem")):
        (device / file).write_text("a placeholder: no key and no certificate\n", encoding="utf-8")
        env[name] = str(device / file)
    return env


def aws_uplink(twin: Any, aws: Any, sdk: FakeSdk, tmp_path: Path, clock: Any = None) -> Any:
    settings = aws.settings_from(device_env(aws, tmp_path))
    if clock is None:
        return aws.AwsUplink(settings, twin.topics.Topics(THING, RULE).client_id, sdk.modules())
    return aws.AwsUplink(settings, twin.topics.Topics(THING, RULE).client_id, sdk.modules(), monotonic=clock.monotonic)


def test_wp3_the_uplinks_design_values_are_in_limits(twin):
    L = twin.limits
    assert (L.QOS, L.MQTT_PORT, L.KEEP_ALIVE_S, L.RECONNECT_MIN_S, L.RECONNECT_MAX_S) == (1, 8883, 60, 5, 60)          # gap k
    assert (L.OPERATION_TIMEOUT_S, L.UPLINK_WAIT_MARGIN_S, L.PING_TIMEOUT_S, L.TCP_CONNECT_TIMEOUT_S) == (5, 2.0, 3, 5)
    assert (L.CONNECT_WAIT_S, L.CLOSE_WAIT_S, L.SDK_TLS_NEGOTIATION_S) == (10.0, 2.0, 10)
    assert L.KEEP_ALIVE_S * 1000 > L.PING_TIMEOUT_S * 1000          # the SDK refuses a ping time-out at or above the keep-alive
    # What the 10 s wait covers: the TCP connect's time-out and the wait for the CONNECT's answer, the two the uplink sets.
    assert L.CONNECT_WAIT_S >= L.TCP_CONNECT_TIMEOUT_S + L.PING_TIMEOUT_S
    # What it does NOT cover: the TLS handshake between them has a wait of the SDK's own, which the builder takes no
    # keyword for. The three together are longer than the uplink waits, so the SDK can answer a connect, with a
    # connection, after the uplink reported it as failed: the late answer's test holds what the uplink does then.
    assert L.CONNECT_WAIT_S < L.TCP_CONNECT_TIMEOUT_S + L.SDK_TLS_NEGOTIATION_S + L.PING_TIMEOUT_S
    assert 0 < L.OPERATION_TIMEOUT_S < L.RECONNECT_MIN_S + L.UPLINK_WAIT_MARGIN_S < L.SHADOW_RETRY_S
    # The SDK's own reconnect timer is NOT the uplink's back-off: it is held far beyond every wait of the uplink's, so
    # that the SDK tries nothing of its own before the uplink has given a lost connection up. What it has to outlast:
    # the longest the connector goes without handing the uplink a publish (a batch a minute at 1 Hz, a document a
    # minute), the wait for that publish's answer, and the uplink's longest back-off; an hour is ten times their sum
    # and more.
    assert L.SDK_RECONNECT_HOLD_S == 3600
    longest_without_a_publish = max(max(L.BATCH_INTERVAL_S.values()), L.SHADOW_MIN_INTERVAL_S, L.SHADOW_RETRY_S)
    assert L.SDK_RECONNECT_HOLD_S >= 10 * (longest_without_a_publish + L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S + L.RECONNECT_MAX_S)
    assert L.SDK_RECONNECT_HOLD_S > L.LIMITER_WINDOW_S and L.SDK_RECONNECT_HOLD_S > L.RECONNECT_MAX_S > L.RECONNECT_MIN_S
    # THE CHOICE, g: nothing is handed to a connection that showed no life for LINK_LIFE_MAX_S. The latest hand-over and
    # the wait for its answer end before half the hold has gone, so the SDK's own first reconnect attempt (the hold after
    # it noticed a loss, and it cannot have noticed before the last answer) finds no request still open; the other half
    # is for the SDK's clock and the uplink's not running alike. And normal traffic never comes near it: the longest an
    # honest connector goes without an acknowledged publish is a batch interval, or a limiter window when it is refused.
    assert L.LINK_LIFE_MAX_S == 900
    assert 2 * (L.LINK_LIFE_MAX_S + L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S) <= L.SDK_RECONNECT_HOLD_S
    assert L.LINK_LIFE_MAX_S >= 3 * L.LIMITER_WINDOW_S and L.LINK_LIFE_MAX_S >= 10 * longest_without_a_publish


def test_the_uplink_gives_the_sdk_every_setting_itself_and_its_connect_is_clean_and_carries_no_sdk_metrics(twin, aws, tmp_path):
    """Prep gap k: one MQTT 3.1.1 connection built with mtls_from_path, every setting given, none left to the SDK:
    port 8883, clean_session, keep-alive, the operation time-out, the SDK's own reconnect timer, ca_filepath, SDK
    metrics off. The reconnect timer is the hold, at both ends, and not the uplink's own back-off: the uplink never
    uses a connection the SDK brings back, and the SDK's default (5 s to 60 s) raced the give-up (the hard review).
    The CONNECT the far end then sees is a clean session with a 60 s keep-alive and no user name at all (the SDK puts
    its name, version and features into the user name unless it is told not to)."""
    sdk, env, L = FakeSdk(), device_env(aws, tmp_path), twin.limits
    up = aws.from_env(env, twin.topics.Topics(THING, RULE), sdk=sdk.modules())
    assert sdk.built == [] and sdk.calls == []          # nothing is opened before connect()
    up.connect()
    (conn,) = sdk.built
    assert (conn.cert, conn.key) == (env[aws.ENV_CERT], env[aws.ENV_KEY])
    given = {k: v for k, v in conn.kwargs.items() if not k.startswith("on_connection_")}
    assert given == {"endpoint": ENDPOINT, "port": 8883, "client_id": THING, "clean_session": True, "keep_alive_secs": 60,
                     "ping_timeout_ms": 3000, "protocol_operation_timeout_ms": 5000, "tcp_connect_timeout_ms": 5000,
                     "reconnect_min_timeout_secs": 3600, "reconnect_max_timeout_secs": 3600, "ca_filepath": env[aws.ENV_CA],
                     "enable_metrics_collection": False}
    assert given == aws.connection_options(aws.settings_from(env), THING)
    assert given["clean_session"] is True and given["enable_metrics_collection"] is False          # the values, not something truthy or falsy
    assert given["port"] == L.MQTT_PORT and given["keep_alive_secs"] == L.KEEP_ALIVE_S
    assert given["protocol_operation_timeout_ms"] == L.OPERATION_TIMEOUT_S * 1000 > 0          # 0 is the SDK's: no time-out at all
    assert given["reconnect_min_timeout_secs"] == given["reconnect_max_timeout_secs"] == L.SDK_RECONNECT_HOLD_S          # no doubling: one value
    assert L.RECONNECT_MIN_S not in (given["reconnect_min_timeout_secs"], given["reconnect_max_timeout_secs"])          # the back-off is the uplink's
    assert sorted(k for k in conn.kwargs if k.startswith("on_connection_")) == ["on_connection_interrupted", "on_connection_resumed"]
    assert not {"username", "password", "will", "use_websockets", "http_proxy_options", "websocket_proxy_options", "ca_dirpath",
                "ca_bytes", "client_bootstrap", "cipher_pref"} & set(conn.kwargs)
    assert sdk.connects == [{"connection": 1, "host": ENDPOINT, "port": 8883, "client_id": THING, "clean": True, "keep_alive": 60,
                             "user": None, "will": None, "resumed": False}]
    assert sdk.calls == [("connect", 1)]


@pytest.mark.parametrize("left_out, seen", [("clean_session", ("clean", False)), ("enable_metrics_collection", ("user", SDK_METRICS_USER)),
                                            ("keep_alive_secs", ("keep_alive", 1200)), ("port", ("port", 443))])
def test_seeded_an_uplink_that_leaves_a_setting_to_the_sdk_shows_in_the_connect_the_far_end_sees(twin, aws, tmp_path, monkeypatch, left_out, seen):
    """The stand-in's defaults are the pinned SDK's (awsiotsdk 1.31.0's builder, read): a persistent session, SDK
    metrics in the user name, a 1200 s keep-alive, port 443. An uplink that leaves one of them out is seen."""
    real = aws.connection_options
    monkeypatch.setattr(aws, "connection_options", lambda settings, client_id: {k: v for k, v in real(settings, client_id).items() if k != left_out})
    sdk = FakeSdk()
    aws_uplink(twin, aws, sdk, tmp_path).connect()
    key, value = seen
    assert sdk.connects[0][key] == value


def test_the_uplinks_settings_come_from_the_environment_and_a_bad_one_is_refused_without_repeating_it(twin, aws, tmp_path, monkeypatch):
    env = device_env(aws, tmp_path)
    topics = twin.topics.Topics(THING, RULE)
    assert (aws.ENV_ENDPOINT, aws.ENV_CERT, aws.ENV_KEY, aws.ENV_CA) == ("SDV_TWIN_ENDPOINT", "SDV_TWIN_CERT", "SDV_TWIN_KEY", "SDV_TWIN_CA")
    assert aws.DEFAULT_FILES == {"SDV_TWIN_CERT": "/run/sdv-local/device/device.crt", "SDV_TWIN_KEY": "/run/sdv-local/device/device.key",
                                 "SDV_TWIN_CA": "/run/sdv-local/device/ca.pem"}
    s = aws.settings_from(env)
    assert s == (ENDPOINT, env[aws.ENV_CERT], env[aws.ENV_KEY], env[aws.ENV_CA])
    for good in ("a", "a-b.example", "192.0.2.7", "xn--bcher-kva.example", "a" * 63 + ".example"):
        assert aws.settings_from(dict(env, SDV_TWIN_ENDPOINT=good)).endpoint == good
    sdk = FakeSdk()
    bad = [None, "", "mqtts://" + ENDPOINT, ENDPOINT + ":8883", ENDPOINT + "/mqtt", " " + ENDPOINT, ENDPOINT + "\n", "-" + ENDPOINT,
           "a..example", "a_b.example", "a" * 64 + ".example", ".".join(["a" * 60] * 5), "[::1]", ENDPOINT + ".", "$aws", "a b"]
    for value in bad:
        e = {k: v for k, v in env.items() if k != aws.ENV_ENDPOINT}
        if value is not None:
            e[aws.ENV_ENDPOINT] = value
        with pytest.raises(twin.uplink.UplinkError) as caught:
            aws.from_env(e, topics, sdk=sdk.modules())
        assert "SDV_TWIN_ENDPOINT" in str(caught.value) and (not value or value not in str(caught.value))
    for name in (aws.ENV_CERT, aws.ENV_KEY, aws.ENV_CA):
        for value in (str(tmp_path / "device" / "no-such-file"), str(tmp_path / "device"), "device.key", "relative/" + name):
            with pytest.raises(twin.uplink.UplinkError) as caught:
                aws.from_env(dict(env, **{name: value}), topics, sdk=sdk.modules())
            assert name in str(caught.value) and value not in str(caught.value)
        without = {k: v for k, v in env.items() if k != name}          # left out: the device directory's file, which is not here
        with pytest.raises(twin.uplink.UplinkError, match=name):
            aws.from_env(without, topics, sdk=sdk.modules())
    assert sdk.built == [] and sdk.calls == []
    # an SDK that is not installed is the ImportError itself: the entry point has a sentence for it
    monkeypatch.setitem(sys.modules, "awscrt", None)
    monkeypatch.setitem(sys.modules, "awsiot", None)
    with pytest.raises(ImportError):
        aws.from_env(env, topics)
    with pytest.raises(twin.uplink.UplinkError):          # a setting is refused first, SDK or no SDK
        aws.from_env({}, topics)


def test_the_sdk_is_imported_in_one_function_of_one_module_and_its_logging_is_never_switched_on():
    tree = ast.parse(UPLINK_AWS.read_text(encoding="utf-8"))
    sdk = {"awscrt", "awsiot"}
    where = []
    for func in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(func):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in sdk:
                where.append((func.name, node.module, sorted(a.name for a in node.names)))
            elif isinstance(node, ast.Import) and {a.name.split(".")[0] for a in node.names} & sdk:
                where.append((func.name, None, sorted(a.name for a in node.names)))
    assert where == [("load_sdk", "awscrt", ["mqtt"]), ("load_sdk", "awsiot", ["mqtt_connection_builder"])]
    top = {(n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
           for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    assert top <= set(sys.stdlib_module_names) | {"limits", "uplink"} and not top & sdk
    assert _imports(UPLINK_AWS) - set(sys.stdlib_module_names) == {"limits", "uplink", "awscrt", "awsiot"}
    # the SDK's own logging writes what it likes to a file or a stream: it is switched on nowhere in the connector
    for path in sorted(p for p in CONNECTOR_DIR.rglob("*.py") if "__pycache__" not in p.parts):
        names = {n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", "") for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))}
        assert not names & {"init_logging", "set_log_level"}, path
    # one publish call and one subscribe call to the SDK in the whole file, each inside the waited request
    text = UPLINK_AWS.read_text(encoding="utf-8")
    assert text.count(".conn.publish(") == 1 and text.count(".conn.subscribe(") == 1 and text.count(".conn.connect(") == 1
    assert "resubscribe_existing_topics" not in text and ".reconnect(" not in text


def test_a_publish_is_one_acknowledged_packet_and_a_message_is_delivered_as_bytes(twin, aws, tmp_path):
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    with pytest.raises(twin.uplink.UplinkError):          # nothing before connect(), and the SDK is not asked
        up.publish(TELEMETRY_TOPIC, b"{}", 1)
    with pytest.raises(twin.uplink.UplinkError):
        up.subscribe(CONFIG_DELTA, lambda topic, payload: None)
    assert sdk.built == []
    resumed: List[int] = []
    up.connect(lambda: resumed.append(1))
    got: List[Tuple[str, Any]] = []
    up.subscribe(CONFIG_DELTA, lambda topic, payload: got.append((topic, payload)))
    payload = b'{"v":1,"rows":[[1,2.5,null]]}'
    assert up.publish(TELEMETRY_TOPIC, payload, 1) is None
    up.publish(VSS_UPDATE, bytearray(b'{"state":{}}'))          # the seam's default QoS is 1
    assert [(p.topic, p.payload, p.dup) for p in sdk.wire] == [(TELEMETRY_TOPIC, payload, False), (VSS_UPDATE, b'{"state":{}}', False)]
    for qos in (0, 2, None):
        with pytest.raises(twin.uplink.UplinkError):
            up.publish(TELEMETRY_TOPIC, b"{}", qos)
    assert len(sdk.wire) == 2 and len([c for c in sdk.calls if c[0] == "publish"]) == 2
    # what the SDK hands over (bytes, a bytearray, a memoryview) reaches the callback as bytes, by position
    for raw in (b'{"state":{"rate_hz":10}}', bytearray(b"x"), memoryview(b"y")):
        assert sdk.deliver(CONFIG_DELTA, raw)
    assert got == [(CONFIG_DELTA, b'{"state":{"rate_hz":10}}'), (CONFIG_DELTA, b"x"), (CONFIG_DELTA, b"y")]
    assert all(type(p) is bytes for _t, p in got) and not sdk.deliver(VSS_UPDATE, b"nobody subscribed to this")
    # a callback that raises does not raise on the SDK's thread
    up.subscribe(CONFIG_GET + "/accepted", _raises(RuntimeError(SECRET)))
    assert sdk.deliver(CONFIG_GET + "/accepted", b"{}") and up.counters["callback_errors"] == 1
    assert resumed == [] and len(sdk.built) == 1 and up.counters["opened"] == 1


def test_whatever_the_sdk_raises_leaves_the_uplink_as_an_uplink_error_without_its_text(twin, aws, quick, tmp_path):
    U = twin.uplink.UplinkError

    def refused(call: Callable[[], Any]) -> None:
        with pytest.raises(U) as caught:
            call()
        exc = caught.value
        assert type(exc) is U and exc.__cause__ is None and (exc.__context__ is None or exc.__suppress_context__)          # no SDK text in a chain
        for word in SECRET_WORDS + ("AWS_", "MQTT"):
            assert word not in str(exc), word

    # connect: failed by the SDK, and not answered within the uplink's wait. Either way the uplink has no connection and
    # uses what was built for nothing. The SDK is asked to disconnect it both times; while it is still connecting it
    # refuses that and goes on (what the uplink does when it answers after all is the late answer's test).
    for how, state in (("AWS_IO_TLS_ERROR_NEGOTIATION_FAILURE", "disconnected"), ("hangs", "connecting")):
        sdk = FakeSdk()
        sdk.connect_fails = how
        up = aws_uplink(twin, aws, sdk, tmp_path)
        refused(up.connect)
        assert [c.state for c in sdk.built] == [state] and sdk.calls == [("connect", 1), ("disconnect", 1)]
        assert up._link is None and (up.counters["opened"], up.counters["given_up"]) == (0, 1)
        refused(lambda up=up: up.publish(TELEMETRY_TOPIC, b"{}", 1))
        assert len(sdk.built) == 1 and sdk.wire == []          # a connect that never succeeded is not tried again by a publish
        assert not [c for c in sdk.calls if c[0] == "publish"] and sdk.built[0].held == []          # and the SDK was not handed it
    # a builder that refuses its arguments (an SDK of another version would): an UplinkError too
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up._client_id = ""
    refused(up.connect)
    # a subscription the SDK fails, and one it never answers (a SUBSCRIBE has no time-out of the SDK's own)
    for how, state in (("AWS_ERROR_MQTT_UNEXPECTED_HANGUP", "up"), ("hangs", "disconnected")):
        sdk = FakeSdk()
        up = aws_uplink(twin, aws, sdk, tmp_path)
        up.connect()
        sdk.subscribe_fails = how
        refused(lambda up=up: up.subscribe(CONFIG_DELTA, lambda topic, payload: None))
        assert sdk.built[0].state == state and up._subs == []
    # a publish the SDK fails by itself: the connection is kept, and the next publish goes out on it
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.connect()
    sdk.far_end = "silent"
    refused(lambda: up.publish(TELEMETRY_TOPIC, b"one", 1))
    sdk.far_end = "answers"
    up.publish(TELEMETRY_TOPIC, b"two", 1)
    assert len(sdk.built) == 1 and sdk.built[0].disconnects == 0 and [p.payload for p in sdk.wire] == [b"one", b"two"]
    # an error that is no Exception at all is passed on as it is, and the connection it came through is given up
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.connect()
    sdk.built[0].publish = _raises(KeyboardInterrupt(SECRET))
    with pytest.raises(KeyboardInterrupt):
        up.publish(TELEMETRY_TOPIC, b"{}", 1)
    assert sdk.built[0].state == "disconnected"


def test_a_publish_the_uplink_reported_as_failed_is_never_sent_later(twin, aws, quick, tmp_path):
    """The binding hand-off of WP2. The SDK queues a publish it is handed while its connection is down and sends it
    when it has reconnected by itself (seen at the local broker, whatever clean_session says), and without a clean
    session it sends an unacknowledged one again with DUP. So: (a) with the connection lost, the SDK is not asked at
    all; (b) a publish that slipped in between the loss and the SDK's callback stays in a connection that never
    connects again; (c) one in flight at the loss is cancelled and not sent again; (d) one the SDK says nothing about
    is given up with its connection. In each case the far end is then made reachable again and the SDK left to do what
    it would: nothing that was reported as failed arrives, and nothing arrives twice."""
    U = twin.uplink.UplinkError
    clock = twin.connector.ManualClock(t=1000.0)

    def rig() -> Tuple[FakeSdk, Any]:
        sdk = FakeSdk(clock)
        up = aws_uplink(twin, aws, sdk, tmp_path, clock)
        up.connect()
        up.publish(TELEMETRY_TOPIC, b"before", 1)
        return sdk, up

    def later(sdk: FakeSdk) -> List[bytes]:
        sdk.report()
        sdk.come_back()
        sdk.unstick()
        return sdk.published()

    # (a) lost, and the SDK said so: the connection is given up from the callback, at once, and the SDK is asked nothing
    sdk, up = rig()
    sdk.lose()
    conn = sdk.built[0]
    assert conn.state == "disconnected" and conn.disconnects == 1 and sdk.calls[-1] == ("disconnect", 1)
    asked = len(sdk.calls)
    for n in range(3):
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"failed-%d" % n, 1)
    assert len(sdk.calls) == asked and conn.held == []          # not handed over: nothing is in the SDK's queue
    assert later(sdk) == [b"before"] and len(sdk.built) == 1 and sdk.connects[-1]["resumed"] is False
    # (b) the race: the connection is lost, the SDK has not called back yet, and a publish is handed over
    sdk, up = rig()
    sdk.lose(silently=True)
    conn = sdk.built[0]
    with pytest.raises(U):
        up.publish(TELEMETRY_TOPIC, b"raced", 1)
    assert [p for _t, p, _f in conn.held] == [b"raced"]          # the SDK took it into its queue, and said nothing
    assert conn.state == "disconnected" and up.counters["undone"] == 1          # so the uplink gave that connection up
    assert later(sdk) == [b"before"] and [p for _t, p, _f in conn.held] == [b"raced"]          # it is still there, and stays there
    # (c) in flight when the connection is lost: cancelled by the SDK under the clean session, and not sent again
    sdk, up = rig()
    sdk.far_end = "lost"
    with pytest.raises(U):
        up.publish(TELEMETRY_TOPIC, b"in-flight", 1)
    assert sdk.built[0].state == "disconnected"
    assert later(sdk) == [b"before", b"in-flight"] and not any(p.dup for p in sdk.wire)          # written once, never again
    # (d) the SDK says nothing at all, connection up: given up, and what it held never goes out
    sdk, up = rig()
    sdk.far_end = "mute"
    with pytest.raises(U):
        up.publish(VSS_UPDATE, b"held", 1)
    assert sdk.built[0].state == "disconnected" and later(sdk) == [b"before"]
    # the same four with an SDK connection that was NOT given up would each put the failed publish on the wire: the
    # stand-in is not kind to the uplink
    for how, lost in (("answers", "silently"), ("mute", None)):
        sdk, up = rig()
        up._give_up = lambda link, wait_s=0.0: None          # an uplink that keeps the connection
        if lost:
            sdk.lose(silently=True)
        sdk.far_end = how
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"kept", 1)
        assert later(sdk) == [b"before", b"kept"], how


def test_the_sdks_own_reconnect_does_not_come_while_the_uplink_waits_for_a_publish_it_handed_to_a_lost_connection(twin, aws, tmp_path, monkeypatch):
    """The hard review's wire run (2026-10-08), on the stand-in. The connection is lost and the SDK knows it; its
    interrupted callback has not reached the uplink. A publish is made: the uplink believes the connection up and
    hands it over, and the SDK queues it. The uplink then waits OPERATION_TIMEOUT_S + UPLINK_WAIT_MARGIN_S for an
    answer (7 s as shipped) before it gives the connection up by itself.
    With the SDK's reconnect timer at its default, which is also what the uplink handed it before (5 s), the SDK
    reconnects inside that wait, writes its queue when the reconnect is answered and calls on_connection_resumed
    only then: the give-up from that callback is too late. The publish is reported as failed and is on the wire.
    With the timer held at SDK_RECONNECT_HOLD_S the SDK tries nothing in that time: the uplink's wait ends, the
    connection is given up (which ends the SDK's reconnecting), and what the SDK held never goes out, an hour later
    or ever. The clock is the stand-in's; the test's own wait for the answer is made short."""
    U = twin.uplink.UplinkError
    L = twin.limits
    waited = L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S          # as shipped: how long the uplink waits for one answer
    assert waited == 7.0 and L.RECONNECT_MIN_S < waited          # which is why the SDK's default timer raced it
    for name, value in (("OPERATION_TIMEOUT_S", 0.05), ("UPLINK_WAIT_MARGIN_S", 0.05)):
        monkeypatch.setattr(L, name, value)

    def run(timer: Optional[Tuple[int, int]]) -> Tuple[FakeSdk, Any, FakeSdkConnection]:
        clock = twin.connector.ManualClock(t=1000.0)
        sdk = FakeSdk(clock)
        up = aws_uplink(twin, aws, sdk, tmp_path, clock)
        real = aws.connection_options
        if timer is not None:          # the control: an uplink that hands the SDK this reconnect timer
            monkeypatch.setattr(aws, "connection_options", lambda settings, client_id: dict(
                real(settings, client_id), reconnect_min_timeout_secs=timer[0], reconnect_max_timeout_secs=timer[1]))
        try:
            up.connect()
        finally:
            monkeypatch.setattr(aws, "connection_options", real)
        up.publish(TELEMETRY_TOPIC, b"before", 1)
        conn = sdk.built[0]
        sdk.lose(silently=True)          # the SDK knows; the uplink was not told
        handed = conn.publish

        def publish(*args: Any, **kwargs: Any) -> Any:
            future, packet = handed(*args, **kwargs)

            def while_the_uplink_waits() -> None:
                clock.advance(waited)          # the whole of the uplink's wait for this answer goes by ...
                sdk.elapse()                   # ... and the SDK does what its own reconnect timer says

            future.at_wait = while_the_uplink_waits
            return future, packet

        conn.publish = publish          # type: ignore[method-assign]
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"raced", 1)
        return sdk, up, conn

    sdk, up, conn = run(None)          # the uplink as it is
    assert sdk.published() == [b"before"], "a publish reported as failed is on the wire: %s" % sdk.published()
    assert conn.kwargs["reconnect_min_timeout_secs"] == conn.kwargs["reconnect_max_timeout_secs"] == L.SDK_RECONNECT_HOLD_S
    assert (up.counters["undone"], up.counters["given_up"], up.counters["resumed_by_sdk"]) == (1, 1, 0)          # the uplink's own wait ended first
    assert conn.state == "disconnected" and [p for _t, p, _f in conn.held] == [b"raced"] and len(sdk.connects) == 1
    # ... and it stays there: the hold runs out, the late callback arrives, the far end is back, the SDK may do what it would
    sdk.clock.advance(2 * L.SDK_RECONNECT_HOLD_S)
    assert sdk.elapse() == 0
    sdk.report()
    sdk.come_back()
    sdk.unstick()
    assert sdk.published() == [b"before"] and [p for _t, p, _f in conn.held] == [b"raced"] and len(sdk.connects) == 1
    assert (up.counters["lost"], up.counters["resumed_by_sdk"], up.counters["given_up"]) == (1, 0, 1)
    # THE CONTROL: with the SDK's default timer, which is what the uplink handed it before, the stand-in is not kind.
    # The SDK's own reconnect is answered inside the uplink's wait, the queue is written, the callback comes after it.
    for timer in ((L.RECONNECT_MIN_S, L.RECONNECT_MAX_S), (L.RECONNECT_MIN_S, L.SDK_RECONNECT_HOLD_S)):
        sdk, up, conn = run(timer)
        assert sdk.published() == [b"before", b"raced"], timer          # reported as failed, and sent on the SDK's own reconnect
        assert [c["resumed"] for c in sdk.connects] == [False, True] and conn.state == "disconnected"
        assert (up.counters["resumed_by_sdk"], up.counters["undone"]) == (1, 0)          # the SDK came back by itself, and is counted
    # (a hold at the top end alone is none, the second control: the SDK's first attempt comes after its SHORTER wait)


def test_nothing_is_handed_to_a_connection_that_showed_no_life_so_the_sdks_own_reconnect_never_finds_a_publish_to_send(
        twin, aws, tmp_path, monkeypatch):
    """The binding hand-off, without the SDK's callback: a publish the uplink reported as failed is never sent later,
    WHENEVER, and WHETHER OR NOT, the SDK's word of a loss reaches the uplink (THE CHOICE, g). The hold alone left a
    window: an uplink that was never told and handed a publish over in the last seconds before the SDK's own
    reconnect (the SDK queues it, reconnects, writes its queue, and only then calls back).
    Here the uplink is NEVER told of the loss (the stand-in holds the callback back for good). A publish is tried at
    every moment a connector could try one, from the loss to past the SDK's own reconnect, each on a rig of its own;
    while the uplink waits for an answer the whole of its wait goes by and the SDK does what its timer says. Nothing
    the uplink reported as failed is on the wire, at any of them. The clock is the stand-in's, the values the shipped
    ones; the test's own wait for an answer is made short."""
    U = twin.uplink.UplinkError
    L = twin.limits
    waited = L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S          # as shipped
    hold, life = L.SDK_RECONNECT_HOLD_S, L.LINK_LIFE_MAX_S
    assert (waited, hold, life) == (7.0, 3600, 900)
    for name, value in (("OPERATION_TIMEOUT_S", 0.05), ("UPLINK_WAIT_MARGIN_S", 0.05)):
        monkeypatch.setattr(L, name, value)

    def rig() -> Tuple[Any, FakeSdk, Any, FakeSdkConnection]:
        clock = twin.connector.ManualClock(t=1000.0)
        sdk = FakeSdk(clock)
        up = aws_uplink(twin, aws, sdk, tmp_path, clock)
        up.connect()
        up.publish(TELEMETRY_TOPIC, b"before", 1)          # acknowledged at 1000.0: the connection's last sign of life
        conn = sdk.built[0]
        handed = conn.publish

        def publish(*args: Any, **kwargs: Any) -> Any:
            future, packet = handed(*args, **kwargs)

            def while_the_uplink_waits() -> None:
                clock.advance(waited)          # the whole of the uplink's wait for this answer goes by ...
                sdk.elapse()                   # ... and the SDK does what its own reconnect timer says

            if not future.done():
                future.at_wait = while_the_uplink_waits
            return future, packet

        conn.publish = publish          # type: ignore[method-assign]
        return clock, sdk, up, conn

    def left_alone(clock: Any, sdk: FakeSdk) -> List[bytes]:
        """The hold runs out twice over and the far end is back; the SDK may do what it would. No callback is handed on."""
        clock.advance(2 * hold)
        sdk.elapse()
        sdk.come_back()
        sdk.unstick()
        return sdk.published()

    # every moment after the loss at which the connector could try a publish, to the second around each edge
    moments = sorted(set([0.0, 1.0, 59.0, 60.0, 300.0, life - waited, life - 1.0, life, life + 0.001, life + 1.0, life + waited,
                          hold / 2.0, hold - 2 * waited, hold - waited - 0.001, hold - waited, hold - waited + 0.001, hold - 1.0,
                          hold - 0.001, hold, hold + 1.0, hold + waited, 2 * hold - 1.0]))
    seen = []
    for after in moments:
        clock, sdk, up, conn = rig()
        sdk.lose(silently=True)          # the SDK knows; the uplink is not told, now or ever
        clock.advance(after)
        came_back = sdk.elapse()         # (past the hold with nothing handed over: the SDK reconnects, with an empty queue)
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"raced", 1)
        handed_over = sdk.calls.count(("publish", TELEMETRY_TOPIC, 1)) == 2          # "before", and this one
        held = [p for _t, p, _f in conn.held]
        seen.append(types.SimpleNamespace(after=after, handed_over=handed_over, held=held, came_back=came_back, wire=left_alone(clock, sdk),
                                          state=conn.state, counters=dict(up.counters), connects=[c["resumed"] for c in sdk.connects]))
    # THE WIRE FIRST: at no moment is a publish that was reported as failed sent, then or later
    assert [(m.after, m.wire) for m in seen if m.wire != [b"before"]] == [], "a publish reported as failed is on the wire (seconds after the loss)"
    # within its life the connection is handed the publish; later the SDK is not asked for it at all
    assert [m.after for m in seen if m.handed_over is not (m.after <= life)] == []
    for m in seen:
        c = m.counters
        assert m.state == "disconnected" and c["lost"] == 0, m.after          # given up, and never by the SDK's word
        if m.after <= life:          # handed over, and the uplink's own wait gave the connection up long before the hold ran out
            assert (c["undone"], c["stale"], c["given_up"], m.came_back) == (1, 0, 1, 0), m.after
            assert m.held == [b"raced"] and m.connects == [False]          # held for good, never written
        elif m.after < hold:         # no life for too long: given up before anything was handed over
            assert (c["undone"], c["stale"], c["given_up"], m.came_back) == (0, 1, 1, 0), m.after
            assert m.held == [] and m.connects == [False] and c["resumed_by_sdk"] == 0
        else:                        # the SDK came back by itself first, with nothing to send; that connection is given up too
            assert (m.came_back, c["resumed_by_sdk"], c["stale"], c["undone"]) == (1, 1, 0, 0), m.after
            assert m.held == [] and m.connects == [False, True]
    # the wait that follows the latest hand-over ends before half the hold has gone: the spare is for two clocks (the
    # SDK's and the uplink's) that do not run alike
    assert 2 * (life + waited) <= hold
    # LIFE IS WHAT THE SDK ANSWERED. A publish the SDK failed is no sign of life (it says nothing of the connection); an
    # acknowledged one is, from the moment it was handed over.
    clock, sdk, up, conn = rig()
    clock.advance(life - 60.0)
    up.publish(TELEMETRY_TOPIC, b"alive", 1)          # acknowledged: the life starts again here
    sdk.far_end = "silent"                            # from here on the SDK fails every publish by its own time-out
    for _minute in range(int(life // 60)):
        clock.advance(60.0)
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"unanswered", 1)
    assert up.counters["stale"] == 0 and conn.state == "up"          # exactly `life` after the last answer: still handed over
    clock.advance(0.001)
    asked = len(sdk.calls)
    with pytest.raises(U):
        up.publish(TELEMETRY_TOPIC, b"too-late", 1)
    assert (up.counters["stale"], up.counters["given_up"], up.counters["not_connected"]) == (1, 1, 1) and conn.state == "disconnected"
    assert sdk.calls[asked:] == [("disconnect", 1)]          # the SDK was asked for the disconnect and for nothing else
    # ... AS OF THE MOMENT THE REQUEST WAS BEGUN, not of its answer: the SDK may have noticed a loss in between, and its
    # timer runs from there. A publish acknowledged 3 s after it was handed over leaves the life at the hand-over.
    clock = twin.connector.ManualClock(t=1000.0)
    sdk = FakeSdk(clock)
    up = aws_uplink(twin, aws, sdk, tmp_path, clock)
    up.connect()
    conn = sdk.built[0]
    handed = conn.publish

    def acknowledged_late(*args: Any, **kwargs: Any) -> Any:
        future, packet = handed(*args, **kwargs)
        if not future.done():
            future.at_wait = lambda: (clock.advance(3.0), sdk.unstick())
        return future, packet

    conn.publish = acknowledged_late          # type: ignore[method-assign]
    sdk.far_end = "mute"                      # the SDK holds each publish until the stand-in lets it write
    clock.advance(100.0)
    up.publish(TELEMETRY_TOPIC, b"slow", 1)          # begun at 1100, acknowledged at 1103
    assert clock.monotonic() == 1103.0 and sdk.published() == [b"slow"]
    clock.advance(life - 3.0)                 # 1100 + life: to the second, still inside its life
    up.publish(TELEMETRY_TOPIC, b"edge", 1)
    assert up.counters["stale"] == 0 and sdk.published() == [b"slow", b"edge"]
    clock.advance(life - 3.0 + 0.001)         # ("edge" was begun at 1100 + life and acknowledged 3 s later) a thousandth past
    with pytest.raises(U):
        up.publish(TELEMETRY_TOPIC, b"past", 1)
    assert up.counters["stale"] == 1 and sdk.published() == [b"slow", b"edge"]
    # ... and the same for the connect: a connection the SDK answered 4 s after it was asked for lives from the asking
    clock = twin.connector.ManualClock(t=1000.0)
    sdk = FakeSdk(clock)
    build = sdk.mtls_from_path

    def answered_late(*args: Any, **kwargs: Any) -> Any:
        conn = build(*args, **kwargs)
        connect = conn.connect

        def slow() -> Any:
            future = connect()
            future.at_wait = lambda: clock.advance(4.0)
            return future

        conn.connect = slow          # type: ignore[method-assign]
        return conn

    sdk.mtls_from_path = answered_late          # type: ignore[method-assign]
    up = aws_uplink(twin, aws, sdk, tmp_path, clock)
    up.connect()
    assert clock.monotonic() == 1004.0 and up._link is not None and (up._link.since, up._link.life) == (1004.0, 1000.0)
    clock.advance(life - 4.0 + 0.001)
    with pytest.raises(U):
        up.publish(TELEMETRY_TOPIC, b"past", 1)
    assert up.counters["stale"] == 1 and sdk.published() == []
    # ... the same for a subscription: nothing is handed to a connection that showed no life
    clock, sdk, up, conn = rig()
    clock.advance(life + 0.001)
    asked = len(sdk.calls)
    with pytest.raises(U):
        up.subscribe(VSS_UPDATE, lambda t, p: None)
    assert sdk.calls[asked:] == [("disconnect", 1)] and up.counters["stale"] == 1
    # ... and the next publish after the back-off opens the next connection, as after any loss
    clock.advance(L.RECONNECT_MIN_S)
    up.publish(TELEMETRY_TOPIC, b"next", 1)
    assert len(sdk.built) == 2 and sdk.published() == [b"before", b"next"]
    # A connection in normal use never comes near it: a publish a minute keeps its life a minute old.
    clock, sdk, up, conn = rig()
    for _minute in range(3 * int(hold // 60)):
        clock.advance(60.0)
        up.publish(TELEMETRY_TOPIC, b"tick", 1)
    assert (up.counters["stale"], up.counters["given_up"], len(sdk.built)) == (0, 0, 1)
    # THE CONTROL: an uplink without the rule (its life never runs out) hands the publish over in the last seconds
    # before the SDK's own reconnect, and the stand-in is not kind: reported as failed, and on the wire.
    monkeypatch.setattr(L, "LINK_LIFE_MAX_S", 10 * hold)
    leaked = []
    for after in (hold - waited + 0.001, hold - 1.0, hold - 0.001):
        clock, sdk, up, conn = rig()
        sdk.lose(silently=True)
        clock.advance(after)
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"raced", 1)
        leaked.append(left_alone(clock, sdk))
    assert leaked == [[b"before", b"raced"]] * 3


def test_the_uplinks_clock_goes_on_while_the_host_is_suspended_where_the_platform_has_such_a_clock(twin, aws, tmp_path):
    """THE CHOICE, g, point 4: the uplink's clock must not fall behind the SDK's. Which clock the SDK's native code
    reads was not examined; one that counts the time a host is suspended would run ahead of time.monotonic, which on
    Linux does not, and a publish could then be handed over after the SDK's own timer had run out. So the uplink
    reads CLOCK_BOOTTIME where there is one (Linux, where the connector runs), which counts the suspend, and
    time.monotonic elsewhere. Whichever the SDK reads, the uplink's is then not the slower one."""
    calls: List[Any] = []

    def clock_gettime(which: Any) -> float:
        calls.append(which)
        return 4242.5

    def refuses(which: Any) -> float:
        raise OSError(22, "Invalid argument")

    linux = types.SimpleNamespace(CLOCK_BOOTTIME=7, CLOCK_MONOTONIC=1, clock_gettime=clock_gettime, monotonic=lambda: 17.0)
    assert aws._clock(linux) == 4242.5 and calls == [7]          # the clock that counts a suspend, and no other
    assert aws._clock(types.SimpleNamespace(monotonic=lambda: 17.0)) == 17.0          # a platform without it
    refused = types.SimpleNamespace(CLOCK_BOOTTIME=7, clock_gettime=refuses, monotonic=lambda: 17.0)
    assert aws._clock(refused) == 17.0          # a kernel that refuses it
    # it is the clock an uplink has when it is given none, the one the entry point builds
    up = aws.AwsUplink(aws.settings_from(device_env(aws, tmp_path)), THING, FakeSdk().modules())
    assert up._monotonic is aws._clock
    a, b = aws._clock(), aws._clock()
    assert isinstance(a, float) and b >= a
    if hasattr(time, "CLOCK_BOOTTIME"):          # here, on Linux: it is that clock, to the second
        assert abs(aws._clock() - time.clock_gettime(time.CLOCK_BOOTTIME)) < 1.0


def test_a_lost_connection_is_given_up_and_the_next_is_a_new_sdk_connection_with_its_subscriptions_then_on_resumed(twin, aws, quick, tmp_path):
    U = twin.uplink.UplinkError
    clock = twin.connector.ManualClock(t=1000.0)
    sdk = FakeSdk(clock)
    up = aws_uplink(twin, aws, sdk, tmp_path, clock)
    order: List[Any] = []
    topics = twin.topics.Topics(THING, RULE)
    up.connect(lambda: order.append(("resumed", len(sdk.built), sorted(sdk.live().subs) == sorted(topics.subscribe), len(sdk.wire))))
    got: List[Tuple[str, bytes]] = []
    for topic in topics.subscribe:
        up.subscribe(topic, lambda t, p: got.append((t, p)))
    up.publish(TELEMETRY_TOPIC, b"one", 1)
    sdk.lose()
    first = sdk.built[0]
    assert first.state == "disconnected" and up.counters["lost"] == 1 and up.counters["given_up"] == 1
    clock.advance(4.999)
    with pytest.raises(U):
        up.publish(TELEMETRY_TOPIC, b"too-soon", 1)
    assert len(sdk.built) == 1          # no new connection before the back-off is over
    clock.advance(0.001)
    up.publish(TELEMETRY_TOPIC, b"two", 1)          # exactly RECONNECT_MIN_S after the loss: a new connection, and this publish on it
    second = sdk.built[1]
    assert second is not first and second.state == "up" and first.state == "disconnected" and first.disconnects == 1
    assert {k: v for k, v in second.kwargs.items() if not k.startswith("on_")} == {k: v for k, v in first.kwargs.items() if not k.startswith("on_")}
    assert sdk.connects[1]["clean"] is True and sdk.connects[1]["user"] is None and sdk.connects[1]["resumed"] is False
    # the subscriptions again, in their order, on the new connection; then on_resumed, once; then the publish
    tail = sdk.calls[sdk.calls.index(("connect", 2)):]
    assert tail == [("connect", 2)] + [("subscribe", t, 2) for t in topics.subscribe] + [("publish", TELEMETRY_TOPIC, 2)]
    assert order == [("resumed", 2, True, 1)]          # called with every subscription back and before the publish reached the wire
    assert [(p.payload, p.connection) for p in sdk.wire] == [(b"one", 1), (b"two", 2)]
    assert sdk.deliver(topics.config_update_delta, b"{}") and got == [(topics.config_update_delta, b"{}")]
    # a connection the SDK brings back by itself all the same is disconnected again, and nothing is sent through it
    first.state = "reconnecting"
    first.held.append((TELEMETRY_TOPIC, b"zombie", first._future()))
    second.state = "parked"          # (the stand-in allows one live connection; the zombie's return is what is looked at)
    first._connected(resumed=True)
    second.state = "up"
    assert first.state == "disconnected" and first.disconnects >= 2 and up.counters["resumed_by_sdk"] == 1
    assert [p for _t, p, _f in first.held] == [b"zombie"]          # what it held is still held
    assert up._link is not None and up._link.conn is second          # the connection in use is untouched by it
    up.publish(TELEMETRY_TOPIC, b"three", 1)
    assert [(p.payload, p.connection) for p in sdk.wire] == [(b"one", 1), (b"two", 2), (b"three", 2)] and len(order) == 1


def test_the_uplink_opens_the_next_connection_no_sooner_than_a_back_off_that_doubles_to_its_cap(twin, aws, quick, tmp_path):
    """Prep gaps k and af: what a client that is refused again and again can cause is a known rate. One attempt, on the
    caller's thread, at the first publish that comes when the wait is over; the wait is 5 s after a loss and doubles to
    60 s while attempts fail or connections live less than 60 s; after a connection that lived 60 s it is 5 s again."""
    U = twin.uplink.UplinkError
    L = twin.limits
    clock = twin.connector.ManualClock(t=1000.0)
    sdk = FakeSdk(clock)
    up = aws_uplink(twin, aws, sdk, tmp_path, clock)
    up.connect()
    up.subscribe(CONFIG_DELTA, lambda t, p: None)
    t0 = clock.monotonic()

    def attempts_until(seconds: float) -> List[float]:
        """A publish every 100 ms: when (after the loss) each new SDK connection was built."""
        seen: List[float] = []
        while round(clock.monotonic() - t0, 3) < seconds:
            clock.advance(0.1)
            before = len(sdk.built)
            try:
                up.publish(TELEMETRY_TOPIC, b"{}", 1)
            except U:
                pass
            if len(sdk.built) > before:
                seen.append(round(clock.monotonic() - t0, 3))
        return seen

    sdk.lose()
    assert sdk.built[0].state == "disconnected" and up._link is None          # given up: every attempt below is a new SDK connection
    sdk.connect_fails = "AWS_IO_SOCKET_CONNECTION_REFUSED"
    assert attempts_until(400.0) == [5.0, 15.0, 35.0, 75.0, 135.0, 195.0, 255.0, 315.0, 375.0]          # 5, 10, 20, 40, then 60 s apart
    assert all(c.state == "disconnected" for c in sdk.built) and len(sdk.built) == 10          # each failed attempt is given up too
    # it comes back: the attempt that is due succeeds, and the publish that made it goes out
    sdk.connect_fails = None
    assert attempts_until(440.0) == [435.0] and sdk.built[-1].state == "up" and len(sdk.wire) >= 1
    # lost again after 10 s of life: the wait goes on from where it was (60 s), not from 5 s
    t_up = clock.monotonic()
    while clock.monotonic() - t_up < 10.0:
        clock.advance(1.0)
        up.publish(TELEMETRY_TOPIC, b"{}", 1)
    sdk.lose()
    lost_at = round(clock.monotonic() - t0, 3)
    (again,) = attempts_until(lost_at + 70.0)
    assert again == round(lost_at + L.RECONNECT_MAX_S, 3)
    # after a connection that lived RECONNECT_MAX_S, the wait is RECONNECT_MIN_S again
    clock.advance(L.RECONNECT_MAX_S)
    sdk.lose()
    lost_at = round(clock.monotonic() - t0, 3)
    (again,) = attempts_until(lost_at + 9.0)
    assert again == round(lost_at + L.RECONNECT_MIN_S, 3)
    # a new connection whose subscription fails is no connection: given up, and the wait goes on
    sdk.lose()
    lost_at = round(clock.monotonic() - t0, 3)
    sdk.subscribe_fails = "AWS_ERROR_MQTT_UNEXPECTED_HANGUP"
    built = len(sdk.built)
    seen = attempts_until(lost_at + 31.0)
    # (the connection before it lived four seconds, so the wait went on doubling from 5 s: 10 s, then 20 s)
    assert seen == [round(lost_at + 10.0, 3), round(lost_at + 30.0, 3)] and all(c.state == "disconnected" for c in sdk.built[built:])
    assert up._link is None
    # a connection that is lost as it is opened was never the uplink's: no publish goes to it, and the wait goes on
    sdk.subscribe_fails, sdk.connect_fails = None, "lost"
    built, asked, t = len(sdk.built), len([c for c in sdk.calls if c[0] == "publish"]), round(clock.monotonic() - t0, 3)
    opened = up.counters["opened"]
    (again,) = attempts_until(t + 41.0)
    assert again == round(lost_at + 70.0, 3) and len(sdk.built) == built + 1 and sdk.built[-1].state == "disconnected"
    assert len([c for c in sdk.calls if c[0] == "publish"]) == asked and up._link is None
    dead = sdk.built[-1].number          # the SDK was asked to connect it and to disconnect it, and for nothing else: no subscription on it
    assert {c[0] for c in sdk.calls if c[-1] == dead} == {"connect", "disconnect"} and up.counters["opened"] == opened
    sdk.connect_fails = None
    (again,) = attempts_until(lost_at + 131.0)
    assert again == round(lost_at + 130.0, 3) and sdk.built[-1].state == "up"          # 60 s after that one: the cap


def test_a_connect_the_sdk_answers_after_the_uplink_stopped_waiting_is_disconnected_at_once_and_never_used(twin, aws, quick, tmp_path):
    """The SDK refuses a disconnect while it is still connecting and goes on connecting (seen at the pinned pair), and
    its own waits add up to more than CONNECT_WAIT_S: it can answer, with a connection, after the uplink reported the
    connect as failed. That connection is under the thing's client id and the uplink knows of none. So: (a) when the
    SDK answers, the connection is disconnected at once, counted, and nothing is ever sent through it; (b) while a
    connect is unanswered no other connection is asked for, by connect() or by a publish, because a second CONNECT
    under one client id makes the far end close whichever connection came first; (c) a late answer that is an error
    asks for nothing. The stand-in models the refused disconnect and the far end's rule, and is not kind: the control
    at the end runs an uplink that forgets the unanswered connect, and loses a connection that was in use."""
    U = twin.uplink.UplinkError
    L = twin.limits
    clock = twin.connector.ManualClock(t=1000.0)

    def published(sdk: FakeSdk, number: int) -> List[Any]:
        return [c for c in sdk.calls if c[0] in ("publish", "subscribe") and c[-1] == number]

    # (1) the first connect: the uplink stops waiting, the SDK does not stop connecting
    sdk = FakeSdk(clock)
    sdk.connect_fails = "hangs"
    up = aws_uplink(twin, aws, sdk, tmp_path, clock)
    with pytest.raises(U):
        up.connect()
    (first,) = sdk.built
    assert first.state == "connecting" and sdk.calls == [("connect", 1), ("disconnect", 1)]          # the disconnect was refused
    assert up._link is None and (up.counters["opened"], up.counters["given_up"], up.counters["late"]) == (0, 1, 0)
    sdk.connect_fails = None          # (the far end would take a connection now)
    with pytest.raises(U):          # (b) no second connect while the SDK has not answered the first
        up.connect()
    assert len(sdk.built) == 1 and sdk.connects == [] and up.counters["given_up"] == 1
    assert sdk.answer_connects() == 1          # the SDK answers after all, with a connection: the far end saw its CONNECT
    assert len(sdk.connects) == 1 and sdk.connects[0]["connection"] == 1
    assert first.state == "disconnected" and sdk.calls[-1] == ("disconnect", 1) and first.disconnects == 2          # (a) at once
    assert up._link is None and (up.counters["opened"], up.counters["late"], up.counters["callback_errors"]) == (0, 1, 0)
    with pytest.raises(U):
        up.publish(TELEMETRY_TOPIC, b"never", 1)
    assert published(sdk, 1) == [] and first.held == [] and sdk.wire == []          # nothing went to it, and nothing through it
    up.connect()          # answered: the next connect is a new SDK connection, and the far end closed nothing for it
    assert [c.state for c in sdk.built] == ["disconnected", "up"] and sdk.takeovers == 0
    up.publish(TELEMETRY_TOPIC, b"one", 1)
    assert [(p.payload, p.connection) for p in sdk.wire] == [(b"one", 2)] and up.counters["lost"] == 0

    # (1b) the wait for the answer is ended by an error that is no Exception: passed on as it is, and the same holds
    sdk = FakeSdk(clock)
    sdk.connect_fails, sdk.connect_wait_raises = "hangs", KeyboardInterrupt(SECRET)
    up = aws_uplink(twin, aws, sdk, tmp_path, clock)
    with pytest.raises(KeyboardInterrupt):
        up.connect()
    (first,) = sdk.built
    assert first.state == "connecting" and up._link is None and (up.counters["given_up"], up.counters["late"]) == (1, 0)
    with pytest.raises(U):
        up.connect()
    assert len(sdk.built) == 1          # (b): unanswered still
    assert sdk.answer_connects() == 1 and first.state == "disconnected" and up.counters["late"] == 1 and up._link is None          # (a)

    # (2) the connection after a loss: the attempt hangs, and the SDK answers ten minutes of refused publishes later
    def rig() -> Tuple[FakeSdk, Any, List[int]]:
        sdk = FakeSdk(clock)
        up = aws_uplink(twin, aws, sdk, tmp_path, clock)
        resumed: List[int] = []
        up.connect(lambda: resumed.append(len(sdk.built)))
        up.subscribe(CONFIG_DELTA, lambda t, p: None)
        up.publish(TELEMETRY_TOPIC, b"one", 1)
        sdk.lose()
        sdk.connect_fails = "hangs"
        clock.advance(L.RECONNECT_MIN_S)
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"opens-a-connect-that-hangs", 1)
        sdk.connect_fails = None
        assert [c.state for c in sdk.built] == ["disconnected", "connecting"] and up._link is None
        assert (up.counters["opened"], up.counters["lost"], up.counters["given_up"], up.counters["late"]) == (1, 1, 2, 0)
        return sdk, up, resumed

    sdk, up, resumed = rig()
    second = sdk.built[1]
    refused = up.counters["not_connected"]
    for _ in range(600):          # the back-off is long over (10 s): only the unanswered connect holds the next one back
        clock.advance(1.0)
        with pytest.raises(U):
            up.publish(TELEMETRY_TOPIC, b"while-unanswered", 1)
    assert len(sdk.built) == 2 and len(sdk.connects) == 1 and up.counters["not_connected"] == refused + 600          # (b)
    assert published(sdk, 2) == [] and second.held == []          # refused before the SDK was asked: nothing in its queue
    assert sdk.answer_connects() == 1
    assert second.state == "disconnected" and second.disconnects == 2 and up.counters["late"] == 1          # (a)
    assert up._link is None and resumed == [] and up.counters["opened"] == 1          # never taken into use, and nobody told it resumed
    assert len(sdk.connects) == 2 and second.subs == {} and published(sdk, 2) == []
    clock.advance(1.0)
    up.publish(TELEMETRY_TOPIC, b"two", 1)          # answered: this publish opens the third SDK connection and goes out on it
    third = sdk.built[2]
    assert [c.state for c in sdk.built] == ["disconnected", "disconnected", "up"] and resumed == [3] and sdk.takeovers == 0
    assert (up.counters["opened"], up.counters["lost"], up.counters["late"]) == (2, 1, 1)
    assert [(p.payload, p.connection) for p in sdk.wire] == [(b"one", 1), (b"two", 3)] and sorted(third.subs) == [CONFIG_DELTA]

    # (c) the late answer is an error (the SDK's own time-out): nothing to disconnect, and the next publish opens a new one
    sdk, up, resumed = rig()
    second = sdk.built[1]
    assert sdk.answer_connects("AWS_IO_TLS_NEGOTIATION_TIMEOUT") == 1
    assert second.state == "disconnected" and second.disconnects == 1 and sdk.connects[1:] == [] and up.counters["late"] == 0
    clock.advance(L.RECONNECT_MAX_S)
    up.publish(TELEMETRY_TOPIC, b"two", 1)
    assert sdk.built[2].state == "up" and resumed == [3] and [(p.payload, p.connection) for p in sdk.wire] == [(b"one", 1), (b"two", 3)]

    # the control: an uplink that forgets the unanswered connect opens the third connection beside it. When the SDK then
    # answers the second, the far end closes the third, which was in use, for it: a loss the uplink caused itself
    sdk, up, resumed = rig()
    up._connecting = None
    clock.advance(L.RECONNECT_MAX_S)
    up.publish(TELEMETRY_TOPIC, b"two", 1)
    assert [c.state for c in sdk.built] == ["disconnected", "connecting", "up"] and up.counters["lost"] == 1
    sdk.answer_connects()
    assert sdk.takeovers == 1 and up.counters["lost"] == 2 and up._link is None
    assert [c.state for c in sdk.built] == ["disconnected", "disconnected", "disconnected"]          # and the late one is not kept either


def test_the_uplink_waits_for_each_answer_of_the_sdk_as_long_as_limits_says(twin, aws, tmp_path):
    """The design values, at the waits themselves (nothing here is shortened, and nothing blocks: the stand-in has
    answered before it is waited for). A request: the SDK's operation time-out and the margin. A connect:
    CONNECT_WAIT_S. The close's DISCONNECT: CLOSE_WAIT_S. The disconnect that gives a connection up is not waited for
    at all: it runs on the SDK's own thread. The stack's stop grace is derived from these."""
    L = twin.limits
    request = L.OPERATION_TIMEOUT_S + L.UPLINK_WAIT_MARGIN_S
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.connect()
    up.subscribe(CONFIG_DELTA, lambda t, p: None)
    up.publish(TELEMETRY_TOPIC, b"{}", 1)
    assert sdk.waits == [("connect", L.CONNECT_WAIT_S), ("subscribe", request), ("publish", request)]
    assert (L.CONNECT_WAIT_S, request, L.CLOSE_WAIT_S) == (10.0, 7.0, 2.0)
    sdk.lose()
    assert sdk.calls[-1] == ("disconnect", 1) and len(sdk.waits) == 3          # given up from the callback: asked, and not waited for
    up.close()
    assert len(sdk.waits) == 3          # nothing is left to close
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.connect()
    up.close()
    assert sdk.waits == [("connect", L.CONNECT_WAIT_S), ("disconnect", L.CLOSE_WAIT_S)] and sdk.calls == [("connect", 1), ("disconnect", 1)]


def test_close_is_safe_on_an_uplink_that_never_connected_and_ends_everything(twin, aws, quick, tmp_path):
    U = twin.uplink.UplinkError
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.close()
    up.close()
    assert sdk.built == [] and sdk.calls == []          # a refused start closes what was built without having opened it
    with pytest.raises(U):
        up.connect()
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.connect()
    up.close()
    assert sdk.built[0].state == "disconnected" and sdk.calls[-1] == ("disconnect", 1)
    up.close()
    for call in (lambda: up.publish(TELEMETRY_TOPIC, b"{}", 1), lambda: up.subscribe(CONFIG_DELTA, lambda t, p: None), up.connect):
        with pytest.raises(U):
            call()
    assert len(sdk.built) == 1 and sdk.wire == []          # nothing is opened again after a close
    # a disconnect the SDK fails, or never completes, leaves close() quiet
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.connect()
    sdk.built[0].disconnect = _raises(SdkFailure("AWS_ERROR_MQTT_CONNECTION_DESTROYED"))
    up.close()
    sdk = FakeSdk()
    up = aws_uplink(twin, aws, sdk, tmp_path)
    up.connect()
    sdk.built[0].disconnect = lambda: sdk.built[0]._future()
    up.close()


def _entry_on_the_sdk_uplink(twin: Any, aws: Any, allow: Any, tmp_path: Path, src: Any, sdk: FakeSdk, clock: Any, out: Any,
                             handlers: Dict[int, Any], monkeypatch: Any, env_over: Optional[Dict[str, Any]] = None) -> Callable[[], int]:
    """The real entry point with NO uplink factory handed in: it imports uplink_aws by name, as the image does, and
    asks its from_env. Only the SDK underneath is the stand-in."""
    monkeypatch.setitem(sys.modules, "uplink_aws", aws)          # the module under test, by the name the entry point imports
    monkeypatch.setattr(aws, "load_sdk", sdk.modules)
    spool = tmp_path / "spool"
    spool.mkdir(exist_ok=True)
    env: Dict[str, Any] = dict(device_env(aws, tmp_path), SDV_TWIN_THING=THING, SDV_TWIN_RULE=RULE, SDV_TWIN_SPOOL=str(spool),
                               SDV_TWIN_SCHEMA=str(SCHEMA_FILE), SDV_TWIN_STATUS=str(tmp_path / "no-status-of-this-test"))
    env.update(env_over or {})
    env = {k: v for k, v in env.items() if v is not None}

    def run() -> int:
        saved = twin.connector.signal.signal
        twin.connector.signal.signal = lambda signum, handler: handlers.__setitem__(signum, handler)
        try:
            return twin.connector.main([], env=env, make_source=lambda target: src, clock=clock, out=out, frozen=allow)
        finally:
            twin.connector.signal.signal = saved

    return run


def test_the_real_entry_point_puts_the_limiter_in_front_of_the_sdk_uplink(twin, aws, frozen, tmp_path, monkeypatch):
    """WP2 held the caps at a fake uplink handed to the entry point. Here the entry point makes its own: uplink_aws,
    imported by name, on a stand-in for the SDK, under the source that changes at every tick and the config that flaps.
    What is counted is what the SDK was handed: every cap holds there, so nothing reaches the SDK past the limiter."""
    L = twin.limits
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    sdk = FakeSdk(clock)
    shadow = FakeShadow(sdk)
    floats = [p for p in frozen.PATHS if frozen.NODES[p][1] == "float"]
    src = twin.source.FakeSource(normal_values(frozen))
    handlers: Dict[int, Any] = {}
    out = io.StringIO()
    n = [0]
    sets = [[p for p in frozen.PATHS if p != gone] for gone in floats]

    def hostile(c):
        n[0] += 1
        for i, p in enumerate(floats):
            src.set(p, 0.25 * n[0] + i)
        shadow.cloud("config", {"rate_hz": 10 if n[0] % 2 else 1, "paths": sets[n[0] % 5]})
        if c.monotonic() - 1000.0 >= 650.0:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    clock.on_sleep.append(hostile)
    built: List[Any] = []
    real_build = twin.connector.build
    monkeypatch.setattr(twin.connector, "build", lambda *a, **k: built.append(real_build(*a, **k)) or built[-1])
    assert _entry_on_the_sdk_uplink(twin, aws, frozen, tmp_path, src, sdk, clock, out, handlers, monkeypatch)() == 0
    (conn,) = built
    assert type(conn.uplink) is twin.limiter.Limiter and type(conn.uplink.inner) is aws.AwsUplink
    assert not [k for k, v in vars(conn).items() if v is conn.uplink.inner]          # reached through the limiter and nothing else
    (sdk_conn,) = sdk.built
    assert sdk.connects[0]["client_id"] == THING and sdk.connects[0]["clean"] is True and sdk.connects[0]["user"] is None
    topics = twin.topics.Topics(THING, RULE)
    assert sorted(sdk_conn.subs) == sorted(topics.subscribe)
    asked = [c for c in sdk.calls if c[0] == "publish"]
    assert len(asked) == len(sdk.wire) and {c[1] for c in asked} == set(topics.publish)          # the four topics and no other
    telemetry = [p for p in sdk.wire if p.topic == TELEMETRY_TOPIC]
    shadows = [p for p in sdk.wire if p.topic != TELEMETRY_TOPIC]
    times = [p.t for p in telemetry]
    assert smallest_gap_ms(times) >= 1000 * L.TELEMETRY_MIN_GAP_S and most_in_a_closed_window(times) == L.TELEMETRY_MAX_PER_WINDOW == 60
    assert max(len(p.payload) for p in telemetry) <= L.TELEMETRY_MAX_BYTES
    assert most_in_a_closed_window([p.t for p in shadows]) == L.SHADOW_MAX_PER_WINDOW == 10
    assert max(len(p.payload) for p in shadows) <= L.SHADOW_MAX_BYTES and not any(p.dup for p in sdk.wire)
    (stop,) = [json.loads(line) for line in out.getvalue().splitlines() if '"event":"stop"' in line]
    assert stop["counters"]["refused_telemetry"] > 300 and sum(stop["limiter"].values()) > 300          # the limiter was what held them
    assert sdk.calls[-1] == ("disconnect", 1) and "uplink_aws" in sys.modules          # (the fixture takes the name out again)
    # the uplink's own counters are in the stop line too: every one of them, as the uplink has them at the end
    assert stop["uplink"] == dict(conn.uplink.inner.counters) and sorted(stop["uplink"]) == sorted(aws.COUNTERS)
    assert (stop["uplink"]["opened"], stop["uplink"]["given_up"], stop["uplink"]["resumed_by_sdk"], stop["uplink"]["lost"]) == (1, 1, 0, 0)


def test_the_stop_line_carries_the_uplinks_own_counters_so_a_run_in_which_the_sdk_came_back_by_itself_is_marked(
        twin, aws, frozen, tmp_path, monkeypatch):
    """WP3-verify-2's NIT 3 and the hard review's fix c. The uplink's counters were in no log line: a connector whose
    SDK never answered a connect, or whose SDK reconnected by itself (a connection under the thing's client id that
    nobody uses), ran on with nothing in its record to show it. The stop line now has them, read through the
    limiter: counts under plain names and nothing else, so the log's rule (no name, no topic, no value) holds whatever
    an uplink keeps in its counters."""
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    sdk = FakeSdk(clock)
    FakeShadow(sdk)
    src = twin.source.FakeSource(normal_values(frozen))
    handlers: Dict[int, Any] = {}
    out = io.StringIO()
    did: List[str] = []

    def events(c):
        t = c.monotonic() - 1000.0
        if t >= 20.0 and "lost" not in did:
            did.append("lost")
            sdk.lose()                                   # the SDK says so at once: given up from its callback
        if t >= 100.0 and "zombie" not in did and len(sdk.built) >= 2 and sdk.built[1].state == "up":
            did.append("zombie")                         # the SDK brings the connection it was told to drop back all the same
            first, second = sdk.built[0], sdk.built[1]
            first.state, second.state = "reconnecting", "parked"
            first._connected(resumed=True)
            second.state = "up"
        if t >= 130.0:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    clock.on_sleep.append(events)
    built: List[Any] = []
    real_build = twin.connector.build
    monkeypatch.setattr(twin.connector, "build", lambda *a, **k: built.append(real_build(*a, **k)) or built[-1])
    # (the uplink the entry point makes reads the real clock, on which this run takes no time: its back-off, held by
    # its own test, is made nothing here so that the publish after the loss opens the next connection)
    monkeypatch.setattr(twin.limits, "RECONNECT_MIN_S", 0)
    assert _entry_on_the_sdk_uplink(twin, aws, frozen, tmp_path, src, sdk, clock, out, handlers, monkeypatch)() == 0
    (conn,) = built
    assert did == ["lost", "zombie"] and len(sdk.built) == 2, (did, [c.state for c in sdk.built], out.getvalue()[-900:])
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    stop = lines[-1]
    assert stop["event"] == "stop" and {"counters", "limiter", "source", "signal", "uplink"} <= set(stop)
    inner = conn.uplink.inner
    assert stop["uplink"] == dict(inner.counters) == conn.uplink.below() and sorted(stop["uplink"]) == sorted(aws.COUNTERS)
    assert (stop["uplink"]["opened"], stop["uplink"]["lost"], stop["uplink"]["resumed_by_sdk"]) == (2, 1, 1)          # counted
    assert all(type(v) is int for v in stop["uplink"].values())
    assert conn.uplink.below() is not inner.counters          # a copy: the log's reader cannot move the uplink's counts
    # only the stop line has them, and the connector reaches them through the limiter and through nothing else
    assert not [rec for rec in lines[:-1] if "uplink" in rec] and not [k for k, v in vars(conn).items() if v is inner]
    # Counts and nothing else, whatever an uplink keeps there: a value that is no count, and a key that is no plain
    # name, do not reach the log (an uplink's own text could name the endpoint or a topic).
    topics = twin.topics.Topics(THING, RULE)
    limiter = twin.limiter.Limiter(types.SimpleNamespace(counters={
        "opened": 3, "late": True, "note": SECRET, "ratio": 0.5, "none": None, TELEMETRY_TOPIC: 1, "Upper": 1, "": 1, 7: 1,
        "x" * 41: 1, "resumed_by_sdk": 2}), topics, clock)
    assert limiter.below() == {"opened": 3, "resumed_by_sdk": 2}
    for none in (types.SimpleNamespace(), types.SimpleNamespace(counters=None), types.SimpleNamespace(counters=[("opened", 1)]),
                 twin.uplink.FakeUplink(clock)):
        assert twin.limiter.Limiter(none, topics, clock).below() == {}          # an uplink that keeps none


def test_the_real_entry_point_answers_a_missing_sdk_and_bad_uplink_settings_with_status_2_and_a_failed_connect_with_1(
        twin, aws, frozen, tmp_path, monkeypatch, capsys):
    clock = twin.connector.ManualClock(t=1000.0, wall_ms=T0_MS)
    clock.on_sleep.append(_raises(AssertionError("the loop began")))
    src = twin.source.FakeSource({})

    def run(sdk: FakeSdk, **env_over: Any) -> Tuple[int, str, str]:
        out = io.StringIO()
        with monkeypatch.context() as m:
            rc = _entry_on_the_sdk_uplink(twin, aws, frozen, tmp_path, src, sdk, clock, out, {}, m, env_over)()
        return rc, out.getvalue(), capsys.readouterr().err

    sdk = FakeSdk()
    for over in ({"SDV_TWIN_ENDPOINT": None}, {"SDV_TWIN_ENDPOINT": "mqtts://%s:8883" % ENDPOINT}, {"SDV_TWIN_KEY": str(tmp_path / "absent.key")}):
        rc, log, err = run(sdk, **over)
        assert (rc, log) == (2, "") and err == "connector: %s\n" % twin.connector.REFUSALS["uplink"]
        assert ENDPOINT not in err and "absent.key" not in err
    assert sdk.built == [] and not (tmp_path / "spool" / STAMP).exists()          # nothing was started: no stamp, no connection
    # no SDK in this build
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "uplink_aws", aws)
        m.setattr(aws, "load_sdk", _raises(ImportError("No module named 'awscrt' in " + SECRET)))
        out = io.StringIO()
        saved = twin.connector.signal.signal
        twin.connector.signal.signal = lambda signum, handler: None
        try:
            env = dict(device_env(aws, tmp_path), SDV_TWIN_THING=THING, SDV_TWIN_RULE=RULE, SDV_TWIN_SPOOL=str(tmp_path / "spool"),
                       SDV_TWIN_SCHEMA=str(SCHEMA_FILE), SDV_TWIN_STATUS=str(tmp_path / "no-status-of-this-test"))
            rc = twin.connector.main([], env=env, make_source=lambda target: src, clock=clock, out=out, frozen=frozen)
        finally:
            twin.connector.signal.signal = saved
    assert (rc, out.getvalue()) == (2, "") and capsys.readouterr().err == "connector: %s\n" % twin.connector.REFUSALS["sdk"]
    # the SDK refuses the handshake: connect-failed, status 1, by the error's class and never its text
    sdk = FakeSdk()
    sdk.connect_fails = "AWS_IO_TLS_ERROR_NEGOTIATION_FAILURE"
    rc, log, err = run(sdk)
    lines = [json.loads(line) for line in log.splitlines()]
    assert rc == 1 and [rec["event"] for rec in lines] == ["start", "connect-failed"] and lines[1]["error"] == "UplinkError" and err == ""
    for word in SECRET_WORDS + (ENDPOINT, "AWS_IO"):
        assert word not in log, word
    assert [c.state for c in sdk.built] == ["disconnected"]


# ============================================================ the image: Dockerfile and build_image.py

@pytest.fixture(scope="module")
def build_image() -> Any:
    return _load("sdv_connector_build_image", BUILD_IMAGE)          # not `build_image`: that name is the bridge's


def _local_imports(path: Path, own: Set[str]) -> Set[str]:
    return {n for n in _imports(path) if n in own}


def test_the_connector_dockerfile_pins_its_base_checks_the_lock_and_runs_as_no_root(build_image):
    text = DOCKERFILE.read_text(encoding="utf-8")
    code = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    base = IMAGES["base"]["python"]
    froms = [ln for ln in code if ln.startswith("FROM ")]
    assert froms == ["FROM %s:%s@%s" % (base["repo"], base["tag"], base["index_digest"])]          # one stage, by index digest
    flat = " ".join(" ".join(code).replace("\\", " ").split())
    # the lock, hash-checked, wheels only, no resolver; then pip check, because --no-deps would hide a wrong pair
    assert "pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock && pip check" in flat
    assert flat.count("pip install") == 1 and "COPY requirements.lock /tmp/requirements.lock" in flat
    # no staged module shadows an installed one: checked in the build, since the modules' names are plain
    assert "shadows an installed module" in flat and "importlib.util.find_spec" in flat
    (check,) = [ln for ln in code if "find_spec" in ln]          # one RUN, python's own, after the modules are copied in
    assert check.startswith('RUN python -c "import importlib.util, os, sys; sys.path = [p for p in sys.path if p not in (')
    assert check.endswith(' else 0)"')
    assert code.index(check) == code.index("COPY app/ /app/") + 1 and "sys.exit(" in check
    users = [ln.split()[1] for ln in code if ln.startswith("USER ")]
    assert users == ["10001:10001"] and code.index("USER 10001:10001") > max(i for i, ln in enumerate(code) if ln.startswith(("RUN ", "COPY ")))
    assert code[-1] == 'ENTRYPOINT ["python", "/app/connector.py"]' and "WORKDIR /app" in code and "COPY app/ /app/" in code
    assert not [ln for ln in code if ln.split()[0] in ("ADD", "EXPOSE", "VOLUME", "CMD", "SHELL", "ONBUILD", "HEALTHCHECK")]
    for word in ("docker.sock", "curl", "wget", "apt-get", "git ", "--privileged", "sudo", "chmod", "amazonaws", "SDV_TWIN_"):
        assert word not in flat, word          # nothing fetched but the lock's wheels; no setting of a device in the image
    # the three labels, set from build arguments: the allowlist the image bakes in and the generation it was made from
    args = sorted(ln.split()[1].split("=")[0] for ln in code if ln.startswith("ARG "))
    assert args == ["SDV_ALLOWLIST_DIGEST", "SDV_ALLOWLIST_VERSION", "SDV_CATALOGUE_SHA256"]
    for label, arg in (("sdv.twin.allowlist_version", "SDV_ALLOWLIST_VERSION"), ("sdv.twin.allowlist_digest", "SDV_ALLOWLIST_DIGEST"),
                       ("sdv.twin.catalogue_sha256", "SDV_CATALOGUE_SHA256")):
        assert '%s="${%s}"' % (label, arg) in flat
    assert sorted(build_image.LABELS.values()) == ["sdv.twin.allowlist_digest", "sdv.twin.allowlist_version", "sdv.twin.catalogue_sha256"]
    assert 'org.opencontainers.image.title="twin-connector"' in flat and build_image.TAG == "sdv-local/twin-connector:0.1.0"
    assert "PYTHONDONTWRITEBYTECODE=1" in flat and "PYTHONUNBUFFERED=1" in flat          # a read-only root; a log line at a time


def test_build_image_stages_exactly_the_modules_the_entry_point_imports_the_schema_and_the_frozen_allowlist(build_image, frozen):
    """Prep WP3 and gap y: the staged context is the connector's own modules, appstate.schema.json and the frozen
    allowlist, and nothing else: no burst tool, no probe, no generator, no lock checker, no source list, no test."""
    staged = build_image.staged(TWIN_FROZEN)
    assert sorted(staged) == sorted([m + ".py" for m in STAGED_MODULES] + ["twin_allowlist.py", "appstate.schema.json"])
    assert all(src.is_file() for src in staged.values())
    for name, src in staged.items():
        want = {"twin_allowlist.py": TWIN_FROZEN, "appstate.schema.json": SCHEMA_FILE}.get(name, CONNECTOR_DIR / name)
        assert src.resolve() == want.resolve(), name
    assert not [n for n in staged if "burst" in n.lower() or "probe" in n.lower() or n.startswith(("gen_", "lockcheck", "build_", "test"))]
    assert not any("/" in n or os.sep in n for n in staged)          # flat: the modules import each other by name
    # exactly what the entry point reaches: connector.py's imports of its own directory, followed to the end
    own = {p.stem for p in CONNECTOR_DIR.glob("*.py")} | {"twin_allowlist"}
    reached, todo = set(), ["connector"]
    while todo:
        name = todo.pop()
        if name in reached:
            continue
        reached.add(name)
        if name != "twin_allowlist":
            todo += sorted(_local_imports(CONNECTOR_DIR / (name + ".py"), own))
    assert reached == set(STAGED_MODULES) | {"twin_allowlist"}
    # and the image's tags are in no pin but the connector's own; a burst image has no pin at all (it is never pinned)
    pins = json.dumps(IMAGES).lower()
    assert "burst" not in pins and build_image.TAGS == {"amd64": build_image.TAG, "arm64": build_image.TAG + "-arm64"}
    assert "burst" not in " ".join(build_image.MODULES).lower()
    # THE BURST BUILD EXISTS NOW (build --burst). What "the build script knows no burst" held is held by what the script
    # does with it: its files are staged by a function of their own into a context of their own, none of them is in
    # the connector's staged list, its tag is none of the tags a pin can be written for, and the connector's context
    # holds no file of its directory (the buildx test below reads that context)
    own = set(build_image.BURST_MODULES)
    assert own == {"burst.py", "burst_link.py"} and not own & set(staged) and not own & {m for m in build_image.MODULES}
    assert build_image.BURST_TAG not in build_image.TAGS.values() and "burst" not in json.dumps(build_image.TAGS).lower()
    assert not [src for src in staged.values() if BURST_DIR.resolve() in src.resolve().parents]
    assert build_image.staged.__code__.co_names.count("BURST_MODULES") == 0 and "burst" not in " ".join(build_image.staged.__code__.co_names).lower()


class BuildDocker:
    """build_image's docker replaced: every argument vector kept, and at each build what the staged context holds."""

    def __init__(self, ids: Optional[Dict[str, str]] = None) -> None:
        self.calls: List[List[str]] = []
        self.contexts: List[Dict[str, bytes]] = []
        self.ids = ids if ids is not None else {}

    def __call__(self, *args: str, timeout: float = 120) -> str:
        self.calls.append(list(args))
        if args[:2] == ("buildx", "build"):
            ctx = Path(args[-1])
            self.contexts.append({str(p.relative_to(ctx)).replace(os.sep, "/"): p.read_bytes() for p in sorted(ctx.rglob("*")) if p.is_file()})
            self.ids[args[args.index("-t") + 1]] = "sha256:" + hashlib.sha256(args[args.index("--platform") + 1].encode()).hexdigest()
        return ""

    def image_id(self, ref: str) -> Optional[str]:
        return self.ids.get(ref)


@pytest.fixture
def staged_inputs(build_image, frozen, gate, tmp_path, monkeypatch) -> Any:
    """build_image.build against a replaced docker: the real modules, schema, generated catalogue and frozen allowlist."""
    fake = BuildDocker()
    monkeypatch.setattr(build_image, "docker", fake)
    monkeypatch.setattr(build_image, "image_id", fake.image_id)
    monkeypatch.setattr(build_image, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(build_image, "fresh_check", lambda gen, module: None)          # held by its own test, on the real generator
    return types.SimpleNamespace(docker=fake, gen=gate.catalogue("vss-ids.vspec"), frozen=TWIN_FROZEN)


@pytest.mark.parametrize("arch, platform, lock", [("amd64", "linux/amd64", "requirements.lock"),
                                                  ("arm64", "linux/arm64", "requirements.aarch64.lock")])
def test_build_image_sends_buildx_for_each_platform_with_its_own_lock_and_tag_and_the_three_labels(build_image, frozen, staged_inputs, tmp_path,
                                                                                                arch, platform, lock):
    rec = build_image.build(staged_inputs.gen, staged_inputs.frozen, arch=arch)
    (b,) = [c for c in staged_inputs.docker.calls if c[:2] == ["buildx", "build"]]
    ctx = b[-1]
    tag = build_image.TAGS[arch]
    labels = {"allowlist_version": str(frozen.VERSION), "allowlist_digest": "0x%08X" % frozen.DIGEST, "catalogue_sha256": frozen.CATALOGUE_SHA256}
    assert b == ["buildx", "build", "-q", "--platform", platform, "--provenance=false", "--sbom=false", "--load",
                 "--build-arg", "SDV_ALLOWLIST_VERSION=" + labels["allowlist_version"],
                 "--build-arg", "SDV_ALLOWLIST_DIGEST=" + labels["allowlist_digest"],
                 "--build-arg", "SDV_CATALOGUE_SHA256=" + labels["catalogue_sha256"],
                 "-f", str(Path(ctx) / "Dockerfile"), "-t", tag, ctx]
    assert not {"--push", "--privileged", "--network", "--secret", "--ssh", "--output", "-o"} & set(b)
    assert "/" not in tag.split(":")[0].replace("sdv-local/", "")          # a local name: no registry in it
    # the context: outside the repo, removed afterwards, and holding the Dockerfile, this architecture's lock and app/
    assert not ctx.startswith(str(REPO)) and ctx.startswith(str(tmp_path / "cache" / "connector-build")) and not Path(ctx).exists()
    (held,) = staged_inputs.docker.contexts
    assert sorted(held) == sorted(["Dockerfile", "requirements.lock"] + ["app/" + n for n in build_image.staged(TWIN_FROZEN)])
    assert held["requirements.lock"] == (CONNECTOR_DIR / lock).read_bytes() and held["Dockerfile"] == DOCKERFILE.read_bytes()
    assert held["app/twin_allowlist.py"] == TWIN_FROZEN.read_bytes() and held["app/uplink_aws.py"] == UPLINK_AWS.read_bytes()
    assert not [n for n in held if "burst" in n or "probe" in n or n.endswith((".pem", ".key", ".crt", ".env"))]
    assert rec["image_id"] == staged_inputs.docker.ids[tag] and rec["tag"] == tag and rec["arch"] == arch and rec["platform"] == platform
    assert rec["lock"] == "sdv/connector/" + lock and rec["lock_sha256"] == hashlib.sha256(held["requirements.lock"]).hexdigest()
    assert rec["labels"] == labels and rec["dockerfile_sha256"] == hashlib.sha256(held["Dockerfile"]).hexdigest()
    assert rec["staged"] == {n[len("app/"):]: hashlib.sha256(data).hexdigest() for n, data in held.items() if n.startswith("app/")}
    assert IMAGES["base"]["python"]["index_digest"] in rec["base"] and str(tmp_path) not in json.dumps(rec)


def test_build_image_refuses_a_stale_frozen_module_an_unknown_arch_and_a_staging_root_inside_the_repo(build_image, frozen, staged_inputs, tmp_path,
                                                                                                    monkeypatch):
    """At run time nothing checks the frozen module against a catalogue: the build is that gate. A module made from
    another catalogue, another source list or another schema is refused before docker is asked for anything."""
    B = build_image
    gen = tmp_path / "gen"
    gen.mkdir()
    ids = (staged_inputs.gen / "vss-ids.vspec").read_bytes()
    (gen / "vss-ids.vspec").write_bytes(ids + b"# one more line: another catalogue\n")
    with pytest.raises(B.BuildError, match="vss-ids.vspec .*is not the one .*was generated from"):
        B.build(gen, staged_inputs.frozen, arch="amd64")
    source, schema = tmp_path / "twin_allowlist.json", tmp_path / "appstate.schema.json"
    source.write_bytes(B.SOURCE_LIST.read_bytes() + b"\n")
    schema.write_bytes(B.SCHEMA.read_bytes() + b"\n")
    with monkeypatch.context() as m:
        m.setattr(B, "SOURCE_LIST", source)
        with pytest.raises(B.BuildError, match="twin_allowlist.json .*is not the one"):
            B.build(staged_inputs.gen, staged_inputs.frozen, arch="amd64")
    with monkeypatch.context() as m:
        m.setattr(B, "SCHEMA", schema)
        with pytest.raises(B.BuildError, match="appstate.schema.json .*is not the one"):
            B.build(staged_inputs.gen, staged_inputs.frozen, arch="amd64")
    broken = tmp_path / "twin_allowlist.py"
    broken.write_text(TWIN_FROZEN.read_text(encoding="utf-8").replace("VERSION = %d" % frozen.VERSION, "VERSION = %d +" % frozen.VERSION),
                      encoding="utf-8")
    with pytest.raises(B.BuildError, match="does not import"):
        B.build(staged_inputs.gen, broken, arch="amd64")
    with pytest.raises(B.BuildError, match="no frozen allowlist"):
        B.build(staged_inputs.gen, tmp_path / "absent.py", arch="amd64")
    with pytest.raises(B.BuildError, match="unknown --arch"):
        B.build(staged_inputs.gen, staged_inputs.frozen, arch="riscv64")
    with monkeypatch.context() as m:
        m.setattr(B, "CACHE", REPO / "sdv-out" / "cache-of-a-test")
        with pytest.raises(B.BuildError, match="inside the repo"):
            B.build(staged_inputs.gen, staged_inputs.frozen, arch="amd64")
    assert staged_inputs.docker.calls == [] and not (REPO / "sdv-out" / "cache-of-a-test").exists()
    # a build that exits 0 and leaves no image under its tag is an error, in the bridge's words
    with monkeypatch.context() as m:
        m.setattr(B, "image_id", lambda ref: None)
        with pytest.raises(B.BuildError, match="^the build left no image tagged %s$" % re.escape(B.TAG)):
            B.build(staged_inputs.gen, staged_inputs.frozen, arch="amd64")


def test_the_builds_gate_is_a_fresh_generation_so_a_careful_hand_edit_of_the_frozen_module_is_refused(build_image, frozen, gate, tmp_path,
                                                                                                    monkeypatch):
    """The module's own import check and its three recorded hashes pass a careful hand edit; a comparison with a fresh
    generation does not. The real generator runs here, in the vss venv (the gate fails this test without it)."""
    B = build_image
    monkeypatch.setenv("SDV_VENV", str(gate.vss_venv().parent.parent))
    gen = gate.catalogue("vss-ids.vspec")
    B.fresh_check(gen, TWIN_FROZEN)          # the tree's module is a fresh generation
    edited = tmp_path / "twin_allowlist.py"
    edited.write_text(TWIN_FROZEN.read_text(encoding="utf-8") + "\n# one line more, and every recorded hash still right\n", encoding="utf-8")
    assert B.check_inputs(gen, edited)["catalogue_sha256"] == frozen.CATALOGUE_SHA256          # the hashes alone pass it
    with pytest.raises(B.BuildError, match="not a fresh generation"):
        B.fresh_check(gen, edited)
    monkeypatch.setenv("SDV_VENV", str(tmp_path / "no-venv"))
    with pytest.raises(B.BuildError, match="vss-tools venv"):
        B.fresh_check(gen, TWIN_FROZEN)
    # build() runs it: with a generator that refuses, docker is never asked
    fake = BuildDocker()
    monkeypatch.setattr(B, "docker", fake)
    monkeypatch.setattr(B, "image_id", fake.image_id)
    monkeypatch.setattr(B, "CACHE", tmp_path / "cache")
    with pytest.raises(B.BuildError, match="vss-tools venv"):
        B.build(gen, TWIN_FROZEN, arch="amd64")
    assert fake.calls == []


def test_the_connector_images_are_pinned_in_the_bridge_entrys_shape_with_the_labels_of_this_generation(build_image, frozen):
    """images.json's top-level connector entry: each architecture's {id, config_digest, tag, lock} as the bridge's arm64
    member is, and the three labels the images were built with. Not under upstream, local or test_only; never pushed."""
    entry = IMAGES["connector"]
    assert set(entry) == {"about", "amd64", "arm64", "labels"}
    for arch, lock in (("amd64", "sdv/connector/requirements.lock"), ("arm64", "sdv/connector/requirements.aarch64.lock")):
        pin = entry[arch]
        assert set(pin) == set(IMAGES["bridge"]["arm64"]) == {"id", "config_digest", "tag", "lock"}
        assert SHA.fullmatch(pin["id"]) and SHA.fullmatch(pin["config_digest"]) and pin["id"] != pin["config_digest"]
        assert pin["tag"] == build_image.TAGS[arch] and pin["lock"] == lock and (REPO / lock).is_file()
    assert len({entry[a][k] for a in ("amd64", "arm64") for k in ("id", "config_digest")}) == 4
    assert entry["labels"] == {"sdv.twin.allowlist_version": str(frozen.VERSION), "sdv.twin.allowlist_digest": "0x%08X" % frozen.DIGEST,
                               "sdv.twin.catalogue_sha256": frozen.CATALOGUE_SHA256}
    assert "never pushed" in entry["about"] and "connector" in IMAGES["about"]
    for group in ("upstream", "local", "test_only", "base"):
        assert not [n for n in IMAGES[group] if "connector" in n]
    rest = json.dumps({k: v for k, v in IMAGES.items() if k not in ("connector", "about")})
    assert "twin-connector" not in rest and not any(entry[a]["id"] in rest for a in ("amd64", "arm64"))
    # nothing that loads, bundles or scans the slice's deploy set reads the entry: the connector joins no deploy set yet
    for f in (STACK_DIR / "bundle.py", STACK_DIR / "step3.py", REPO / "sdv" / "arm64" / "arm64.py", REPO / "sdv" / "bridge" / "build_image.py",
              REPO / "orin-native" / "gpu-concurrency" / "vss_setup.py", REPO / "orin-native" / "gpu-concurrency" / "run-vss-setup.sh"):
        assert "twin-connector" not in f.read_text(encoding="utf-8"), f


# ============================================================ the burst tool's own image (prep gap y): build --burst

BURST_STAGED = ("burst.py", "burst_link.py", "limits.py", "topics.py", "uplink.py", "uplink_aws.py")


def test_the_burst_tools_image_is_its_own_from_the_connectors_base_and_lock_and_is_never_pinned(build_image, tmp_path, monkeypatch, capsys):
    """Prep gap y, WP3's bullet on `--burst`: a test-only image of its own from the same base and lock; never pinned in
    images.json, never part of a deploy set; the connector's staged context holds no file of it. The build is run here
    against a replaced docker: what it stages, what it asks buildx for, and what it refuses."""
    B = build_image
    fake = BuildDocker()
    monkeypatch.setattr(B, "docker", fake)
    monkeypatch.setattr(B, "image_id", fake.image_id)
    monkeypatch.setattr(B, "CACHE", tmp_path / "cache")
    images_before = (STACK_DIR / "images.json").read_bytes()
    # what it stages: the tool's two files and the four modules of the connector they import by name, and nothing else
    staged = B.burst_staged()
    assert sorted(staged) == sorted(BURST_STAGED)
    for name, src in staged.items():
        want = (BURST_DIR if name in B.BURST_MODULES else CONNECTOR_DIR) / name
        assert src.resolve() == want.resolve() and src.is_file(), name
    own = {p.stem for p in BURST_DIR.glob("*.py")} | {p.stem for p in CONNECTOR_DIR.glob("*.py")}
    reached, todo = set(), ["burst"]
    while todo:          # exactly what the entry point reaches: burst.py's imports of the two directories, followed to the end
        name = todo.pop()
        if name in reached:
            continue
        reached.add(name)
        home = BURST_DIR if (BURST_DIR / (name + ".py")).is_file() else CONNECTOR_DIR
        todo += sorted(_local_imports(home / (name + ".py"), own))
    assert {n + ".py" for n in reached} == set(BURST_STAGED)
    # the Dockerfile: the connector's base by the same index digest, the same lock install, its own entry point and label
    text = (BURST_DIR / "Dockerfile").read_text(encoding="utf-8")
    code = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    theirs = [ln for ln in DOCKERFILE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    base = IMAGES["base"]["python"]
    assert [ln for ln in code if ln.startswith("FROM ")] == [ln for ln in theirs if ln.startswith("FROM ")] \
        == ["FROM %s:%s@%s" % (base["repo"], base["tag"], base["index_digest"])]
    flat = " ".join(" ".join(code).replace("\\", " ").split())
    assert "pip install --require-hashes --no-deps --only-binary=:all: -r /tmp/requirements.lock && pip check" in flat
    assert flat.count("pip install") == 1
    assert code[-1] == 'ENTRYPOINT ["python", "/app/burst.py"]' and [ln.split()[1] for ln in code if ln.startswith("USER ")] == ["10001:10001"]
    assert 'sdv.burst.test_only="1"' in flat and 'org.opencontainers.image.title="twin-burst"' in flat
    assert "sdv.stack" not in flat and "twin-connector" not in flat and "sdv.twin." not in flat          # no label of the stack's or the connector's
    assert not [ln for ln in code if ln.split()[0] in ("ADD", "EXPOSE", "VOLUME", "CMD", "SHELL", "ONBUILD", "HEALTHCHECK", "ARG")]
    for word in ("docker.sock", "curl", "wget", "apt-get", "git ", "--privileged", "sudo", "chmod", "amazonaws", "SDV_TWIN_", "thresholds"):
        assert word not in flat, word
    (check,) = [ln for ln in code if "find_spec" in ln]
    assert "names != ['burst', 'burst_link', 'limits', 'topics', 'uplink', 'uplink_aws']" in check          # the image holds these six and no other
    # the build: buildx for amd64 only, its own tag, a context of its own outside the repo, never pushed
    rec = B.build_burst()
    (b,) = [c for c in fake.calls if c[:2] == ["buildx", "build"]]
    ctx = b[-1]
    assert b == ["buildx", "build", "-q", "--platform", "linux/amd64", "--provenance=false", "--sbom=false", "--load",
                 "-f", str(Path(ctx) / "Dockerfile"), "-t", B.BURST_TAG, ctx]
    assert B.BURST_TAG == "sdv-local/twin-burst:test-only"
    assert not {"--push", "--privileged", "--network", "--secret", "--ssh", "--output", "-o"} & set(b)
    assert not ctx.startswith(str(REPO)) and ctx.startswith(str(tmp_path / "cache" / "burst-build")) and not Path(ctx).exists()
    (held,) = fake.contexts
    assert sorted(held) == sorted(["Dockerfile", "requirements.lock"] + ["app/" + n for n in BURST_STAGED])
    assert held["Dockerfile"] == (BURST_DIR / "Dockerfile").read_bytes()
    assert held["requirements.lock"] == (CONNECTOR_DIR / "requirements.lock").read_bytes()
    for name in BURST_STAGED:
        assert held["app/" + name] == ((BURST_DIR if name.startswith("burst") else CONNECTOR_DIR) / name).read_bytes(), name
    assert not [n for n in held if n.endswith((".pem", ".key", ".crt", ".env", ".json"))]          # nothing of a device, no thresholds file
    assert rec["image_id"] == fake.ids[B.BURST_TAG] and rec["tag"] == B.BURST_TAG and rec["arch"] == "amd64" and rec["pinned"] is False
    assert rec["lock"] == "sdv/connector/requirements.lock" and rec["dockerfile"] == "sdv/cloud/burst/Dockerfile"
    assert rec["staged"] == {n: hashlib.sha256(held["app/" + n]).hexdigest() for n in BURST_STAGED} and str(tmp_path) not in json.dumps(rec)
    # a Dockerfile on another base than the connector's is refused before docker is asked
    other = tmp_path / "Dockerfile"
    other.write_text(text.replace("@sha256:", "@sha256:0"), encoding="utf-8")
    calls = len(fake.calls)
    with monkeypatch.context() as m:
        m.setattr(B, "BURST_DOCKERFILE", other)
        with pytest.raises(B.BuildError, match="^Dockerfile is not on the connector's base "):
            B.build_burst()
    assert len(fake.calls) == calls
    # the command line: --burst builds that image and nothing else; it takes no pin, no arm64 and no allowlist
    assert B.main(["build", "--burst"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"burst"} and out["burst"]["tag"] == B.BURST_TAG and len([c for c in fake.calls if c[:2] == ["buildx", "build"]]) == 2
    for extra in (["--write-pins"], ["--arch", "arm64"], ["--arch", "all"], ["--arch", "all", "--write-pins"], ["--frozen", str(TWIN_FROZEN)],
                  ["--gen", str(tmp_path)]):
        before = len(fake.calls)
        assert B.main(["build", "--burst"] + extra) == 2, extra
        assert "build_image: --burst " in capsys.readouterr().err and len(fake.calls) == before, extra
    assert (STACK_DIR / "images.json").read_bytes() == images_before and "burst" not in images_before.decode("utf-8").lower()
    # and no pin can be written for it by the functions that write pins: the tag is none of theirs
    pins = {arch: {"id": "sha256:" + "1" * 64, "config_digest": "sha256:" + "2" * 64, "tag": B.TAGS[arch], "lock": "x"} for arch in B.ARCHES}
    labels = {"allowlist_version": "1", "allowlist_digest": "0x0", "catalogue_sha256": "0"}
    assert "burst" not in json.dumps(B.with_pins(IMAGES, pins, labels)).lower()
    # nothing that loads, bundles, scans or starts the slice names the tool, its directory or its image
    # (burst-verify-r1, problem 8, its mutants D1 and D2: the suite's script and its plan read images.json and start the slice on an
    # instance, so they are no less of what loads and starts it; nor is any script of scripts/aws, which starts a bare-metal session)
    aws_scripts = sorted((REPO / "scripts" / "aws").glob("*.sh"))
    assert aws_scripts
    for f in (STACK_DIR / "bundle.py", STACK_DIR / "step3.py", STACK_DIR / "stack.py", REPO / "sdv" / "arm64" / "arm64.py",
              REPO / "sdv" / "bridge" / "build_image.py", REPO / "orin-native" / "gpu-concurrency" / "vss_setup.py",
              REPO / "orin-native" / "gpu-concurrency" / "run-vss-setup.sh", REPO / "orin-native" / "gpu-concurrency" / "run-vss-suite.sh",
              REPO / "orin-native" / "gpu-concurrency" / "vss_suite.py", *aws_scripts):
        body = f.read_text(encoding="utf-8")
        assert "twin-burst" not in body and "cloud/burst" not in body and "burst_link" not in body and "burst.py" not in body, f


class BurstBuildDocker(BuildDocker):
    """BuildDocker that also answers the two calls build_burst makes after its build: the tags the image it replaced still holds
    (`inspect`), and the one JSON line a smoke run ends in (`run`)."""

    def __init__(self, ids: Optional[Dict[str, str]] = None, tags: Optional[List[str]] = None) -> None:
        super().__init__(ids)
        self.tags: List[str] = list(tags or [])

    def __call__(self, *args: str, timeout: float = 120) -> str:
        out = super().__call__(*args, timeout=timeout)
        if args[:3] == ("image", "inspect", "--format"):
            return json.dumps(self.tags)
        if args[:1] == ("run",):
            return "a line of the image's own\n" + json.dumps({"imports": "made up for this test"})
        return out


def test_the_burst_tools_image_build_removes_the_image_it_replaced_stays_outside_the_repo_and_runs_its_smoke_without_a_network(
        build_image, tmp_path, monkeypatch, capsys):
    """burst-verify-r2, problem 12 (its mutants G04, G05, G06 and G07): four things `build --burst` does that the test above does not
    hold. The image a rebuild replaced is removed when the build left it untagged, and not when it is tagged still; the build record
    may not be written inside the repo; nor may the context be staged inside it (both refused before docker is asked for anything);
    and the smoke run has no network, a read-only root, no capability and no new privileges."""
    B = build_image
    old = "sha256:" + "a" * 64

    def docker_with(tags: Optional[List[str]], ids: Optional[Dict[str, str]]) -> BurstBuildDocker:
        fake = BurstBuildDocker(ids, tags)
        monkeypatch.setattr(B, "docker", fake)
        monkeypatch.setattr(B, "image_id", fake.image_id)
        monkeypatch.setattr(B, "CACHE", tmp_path / "cache")
        return fake

    # (G04) an image the tag held before, left untagged by this build: removed; tagged still, or not there: nothing is removed
    fake = docker_with([], {B.BURST_TAG: old, old: old})
    rec = B.build_burst()
    assert [c for c in fake.calls if c[:2] == ["image", "rm"]] == [["image", "rm", old]]
    assert rec["replaced_image"] == {"id": old, "left": "removed (untagged by this build)"} and rec["image_id"] != old
    fake = docker_with(["somewhere/else:tag"], {B.BURST_TAG: old, old: old})
    rec = B.build_burst()
    assert not [c for c in fake.calls if c[:2] == ["image", "rm"]] and "replaced_image" not in rec
    fake = docker_with([], {})
    rec = B.build_burst()
    assert not [c for c in fake.calls if c[:1] == ["image"]] and "replaced_image" not in rec
    # (G05) the build record may not be written inside the repo: refused by the build's own words, before docker is asked
    inside = REPO / "sdv-out" / "burst-record-of-a-test.json"
    calls = len(fake.calls)
    assert B.main(["build", "--burst", "--out", str(inside)]) == 1
    assert "is inside the repo" in capsys.readouterr().err and len(fake.calls) == calls and not inside.exists()
    outside = tmp_path / "records" / "burst.json"
    assert B.main(["build", "--burst", "--out", str(outside)]) == 0
    assert json.loads(outside.read_text(encoding="utf-8"))["burst"]["tag"] == B.BURST_TAG and len(fake.calls) > calls
    capsys.readouterr()
    # (G06) the staging root may not be inside the repo: refused before docker is asked, and nothing is made there
    calls = len(fake.calls)
    with monkeypatch.context() as m:
        m.setattr(B, "CACHE", REPO / "sdv-out" / "cache-of-a-burst-test")
        with pytest.raises(B.BuildError, match="the staging root .* is inside the repo"):
            B.build_burst()
    assert len(fake.calls) == calls and not (REPO / "sdv-out" / "cache-of-a-burst-test").exists()
    # (G07) the smoke run: none unless asked for, and then with no network, a read-only root, no capability and no new privileges
    assert not [c for c in fake.calls if c[:1] == ["run"]]
    rec = B.build_burst(smoke=True)
    (smoke,) = [c for c in fake.calls if c[:1] == ["run"]]
    assert smoke == ["run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                     "--entrypoint", "python", rec["image_id"], "-c", B.BURST_SMOKE]
    assert rec["smoke"] == {"imports": "made up for this test"}
