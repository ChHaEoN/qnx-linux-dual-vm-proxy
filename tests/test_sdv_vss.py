"""The SDV slice's VSS contract (sdv/vss/generate.py): SDV plan Phase 1 step 3.

Two groups. The pure checks -- FNV-1 test vectors and byte order, the staticUID parse rule, the .fidl
refusal (the helper, and the whole run with a .fidl member or input), the DBC reader, the profile
file's invariants (the spec 5.4 bounds are constants of the generator) and every derived constant, the
refusal of a tampered archive and of a wrong embedded commit, the forbidden digests, the venv-against-
lock check on a fake venv, the Vehicle.Speed, overlay-as-written and dbc2vss-signal checks on crafted
catalogues, the vehicle layer (its wheelbase taken from the profile file and following it, each refusal,
and its UID and default checks on crafted catalogues), the previous-generation and baseline drift rules,
and the committed uid-baseline.txt itself
-- import generate.py and run anywhere with Python 3.11+ (tomllib); none needs PyYAML, vss-tools or
the network. The one exception to "anywhere" is the fake venv, whose python is a #!/bin/sh shim: those
tests need a POSIX shell and skip on Windows.

The generation tests run generate.py in WSL's vss-tools venv (~/sdv-venv, built from
sdv/vss/requirements.lock as sdv/vss/README.md says; SDV_VENV overrides the path) and skip with that
reason when it is absent. The first of them fetches the pinned VSS archive into ~/sdv-cache (SDV_CACHE)
unless it is there already. They check: two runs byte-identical, the second validating in place
against the first; the digest recomputed here from the id exporter's output, independently of the
generator; the committed uid-baseline.txt equal to what the pinned inputs generate, a missing one
created only on request and byte-identical to the committed one, and a drift from it (a changed slot
unit, a renamed project branch, a new project-branch node) refused until accepted; a moved staticUID
refused against the previous generation by the generator's own path-by-path diff even when vss-tools'
validation says nothing; a restated standard unit, a dbc2vss signal slice.dbc lacks, a Vehicle.Speed
without min 0, a forbidden digest and an overlay entry the id output or the mapping JSON does not carry
as written (the last two by tampering with vss-tools' output inside the run) each refused; Vehicle.Speed
min 0 and the signed Motion.LongitudinalVelocity; the Monitor branch generated and in no allowlist
file; the id file and the CAN mapping built from overlay.vspec and the vehicle layer alone, with no
ControlCommand node, and the ControlCommand layer (Phase 8 WP1b) loaded for the databroker catalogues'
exports only; the vehicle layer's
Wheelbase default in both JSON files with no staticUID moved, and a layer that moves one or loses its
default refused end to end; the two JSON files agreeing but for the ControlCommand branch; both C headers
compiling under -Werror and agreeing with the Python module bit for bit (gcc, skipped without it). No
generation test may rewrite the committed uid-baseline.txt: each run that accepts a change is given a
copy.

Phase 7 WP2 (the freeze of profile 3, the CARLA ego's; local notes, the profile-freeze rules) adds, pure: profile 3
compiled on the values WP0's CARLA probes read, each held once in profiles.toml under a `# PROBED (` line and once here
in PROBED, so a re-read changes those two places; its a_y bound the owner's D8 value, narrowed in the spec's quarter
steps only as far as the joint-grid budget would need, tol and the window unchanged; the generator refusing a rule-26
margin below the envelope's margin_target (a synthetic uncompiled row's as a compiled profile's) and accepting one
exactly at it, and a profile file that breaks an invariant before the venv and any vss-tools
run; one vehicle layer per run type with a live default (sigsim, carla), the carla layer refused while profile 3 holds a
stand-in L (a stand-in delta_max alone keeps it) and a live-default run type without a layer refused (held by a compiled
profile or by an uncompiled row); the stand-in
cases on a synthetic row, since no generated row holds a stand-in now. Against a generation: the carla layer
and vss-databroker-carla.json (the databroker catalogue with that layer, equal to vss-databroker.json but for the
Wheelbase default), the manifest's vehicle_layer object unchanged beside vehicle_layers and databroker_catalogues, both
layers refused end to end when they move a staticUID or lose their default, a generation refused while profile 3 holds
a stand-in L, and every sigsim output byte for byte what the base tree generated before the freeze (the
databroker catalogue once the ControlCommand branch Phase 8's WP1b adds to it is taken out; tests/test_sdv_vss_ctl.py
holds the kind 2 contract that WP1b generates beside these files), and vss_contract.py and vss_profiles.h byte for byte
what the generation of Phase 8's WP3b writes (BASE_KIND4_SHA256: the two files of WP1b's unchanged set that a kind 4
profile change moves, so they live in this file).

Phase 8 WP3b (the two run types, profiles 4 and 5; local notes, the per-run-type contract rules) adds, pure: the
run types planning-sim and carla-autoware, each with its vehicle layer (the L of its live-default profile) and its
databroker catalogue; profile 4 (the planning simulator's sample vehicle) compiled on values WP4a read in the running
simulator, each held once in profiles.toml under a `# READ (` line and once here in READ, with the planning-sim
envelope's skew row (the simulator's timer, which replaces slice.dbc's period for that envelope alone) and the smallest
one-decimal tol26 that keeps the envelope's margin; profile 5 (the CARLA 0.10.0 taxi) uncompiled, its L and delta_max
in PROBED, on the carla010 envelope whose four rows are stand-ins (the carla envelope's values) until WP3c's freeze; the
two new refusals (a compiled profile on an envelope that holds a stand-in row; a skew_ms row on an envelope that is not a
planning-sim one), with the skew row tied to the run types whose rule-26 triple comes from one timer (SKEW_ROW_RUN_TYPES:
a profile on a planning-sim envelope is the live default of those only, and theirs stands on one); the margin refusal for
both new profiles. Against a generation: every sigsim and carla output and both kind 2 files byte for byte what this
package's base tree generated (BASE_P8_SHA256), the two new layers and catalogues, and profile 4 in the
generated tables with profile 5 left out of the C one.

The confidentiality check reads its literals from a local file (SDV_CONFIDENTIAL_LITERALS, default
~/sdv-cache/confidential-literals.txt) that never enters the repo, and skips when there is none.

The assertions distinguish design values and derived arithmetic from READ configuration values and PROBED source
parameters. The latter retain their provenance; this test does not independently establish them.
"""
import copy
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
VSSDIR = REPO / "sdv" / "vss"
GENERATE = VSSDIR / "generate.py"
VENV = Path(os.environ.get("SDV_VENV", "~/sdv-venv")).expanduser()
VENV_PY = VENV / "bin" / "python"
CACHE = Path(os.environ.get("SDV_CACHE", "~/sdv-cache")).expanduser()
LITERALS = Path(os.environ.get("SDV_CONFIDENTIAL_LITERALS", "~/sdv-cache/confidential-literals.txt")).expanduser()
UID_BASELINE = VSSDIR / "uid-baseline.txt"
# What the committed baseline held when this file was imported; no test may change it.
_COMMITTED_BASELINE = UID_BASELINE.read_bytes() if UID_BASELINE.is_file() else None

NEEDS_VENV = pytest.mark.skipif(
    not (VENV / "bin" / "vspec").exists() or not VENV_PY.exists(),
    reason="needs the vss-tools venv ~/sdv-venv built from sdv/vss/requirements.lock (sdv/vss/README.md; WSL Ubuntu-24.04)")

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None  # type: ignore[assignment]
NEEDS_TOML = pytest.mark.skipif(tomllib is None, reason="profiles.toml needs Python 3.11+ (tomllib)")

SLOT_SIGNALS = ("LongVel", "LongAccel", "SteerAngleRow1", "YawRate", "CurrentGear")
MAPPED = ("Vehicle.DualVm.Motion.LongitudinalVelocity", "Vehicle.Speed", "Vehicle.Acceleration.Longitudinal",
          "Vehicle.Chassis.Axle.Row1.SteeringAngle", "Vehicle.AngularVelocity.Yaw",
          "Vehicle.Powertrain.Transmission.CurrentGear")

# PROBED: profile 3's values, with the provenance markers F7, F4 and F8. The envelope rows were fitted locally;
# the readings are not published. This dict is the tests' one copy, and profiles.toml marks
# each key with a line starting `# PROBED (` right above it: a re-read changes this dict and those lines, and the
# generation is made again; no other test holds them (each reads the profile file or the generation).
PROBED = {
    ("profiles.3", "l_mm"): 2819,                       # F7: the ego blueprint's wheelbase, mm
    ("profiles.3", "delta_max"): 57.0,                  # F4's rule on F3's source: min(57, ceil(single-track maximum + 5))
    ("envelopes.carla", "steer_rate"): 9.2,             # F8, the delta-skew row: the smallest tenth >= 1.1 x the worst read
    ("envelopes.carla", "accel_while_steering"): 1.5,   # F8, the v-skew row: likewise
    ("envelopes.carla", "launch_accel"): 2.2,           # F8, the launch after the reverse: likewise
    ("envelopes.carla", "understeer_gradient"): 2.8,    # F8, the understeer row: likewise
    ("profiles.5", "l_mm"): 2940,                       # Phase 8 WP9a E4: the 0.10.0 taxi's wheelbase, mm (spec-2 2.4)
    ("profiles.5", "delta_max"): 57.0,                  # Phase 8 WP9a section 8: the same rule on the taxi; the cap binds
}
# READ: the values profile 4 and the planning-sim envelope rest on, from WP4a's reads of Autoware 1.9.0's planning
# simulator (the named configuration parameters; spec-2 2.4). This dict is the tests' one copy. profiles.toml marks
# each key with a line starting `# READ (` right above it: a re-read changes both places and regenerates; no other
# test holds them.
READ = {
    ("profiles.4", "l_mm"): 2790,                            # P1: sample_vehicle's vehicle_info.wheel_base, mm
    ("profiles.4", "delta_max"): 57.0,                       # P9: the simulator's steer_lim 1.0 rad by the delta_max rule; the cap binds
    ("profiles.4", "v26_hi"): 5.0,                           # P8: the smallest whole m/s above the planner's max_vel 4.17
    ("envelopes.planning-sim", "wheelbase_mm"): 2790,        # P1, as the profile's L (generate.py refuses another)
    ("envelopes.planning-sim", "cruise_speed"): 4.17,        # P8: the planner's max_vel
    ("envelopes.planning-sim", "turn_speed_max"): 4.17,      # P8: likewise
    ("envelopes.planning-sim", "steer_max"): 57.3,           # P9: the simulator's steer_lim 1.0 rad, in deg, up to a tenth
    ("envelopes.planning-sim", "steer_rate"): 57.3,          # P2: the gate's steer_rate_lim_for_steer_cmd 1.0 rad/s, likewise
    ("envelopes.planning-sim", "accel_while_steering"): 5.0,  # P2: the gate's lon_acc_lim_for_lon_vel, its loosest cell
    ("envelopes.planning-sim", "launch_accel"): 5.0,         # P2: likewise
    ("envelopes.planning-sim", "braking_max"): 5.0,          # P2: likewise
    ("envelopes.planning-sim", "skew_ms"): 25,               # P9: the simulator's timer_sampling_time_ms (G7: one node, 40 Hz)
}
# Spec-2 2.1 and 2.2: the two run types WP3b adds, their catalogues' names, and the envelopes of profiles 4 and 5.
P8_RUN_TYPES = ("planning-sim", "carla-autoware")
P8_CATALOGUES = {"planning-sim": "vss-databroker-planning-sim.json", "carla-autoware": "vss-databroker-carla-autoware.json"}
P8_LAYERS = ("vehicle-planning-sim.vspec", "vehicle-carla-autoware.vspec")
# Spec-2 2.4: the carla010 envelope's four rows are stand-ins, the carla envelope's values, until WP3c's freeze.
CARLA010_STAND_IN = ("steer_rate", "accel_while_steering", "launch_accel", "understeer_gradient")
# The planning-sim envelope's margin over its summed rows (spec-2 2.4, sigsim's), and tol26's step (one decimal).
PLANNING_SIM_MARGIN = 1.5
TOL26_STEP = 0.1
# The owner's D8: profile 3's a_y bound, unless its budget needs it narrower; spec 5 item 2 narrows it in these steps
# (then v26_hi in steps of 1 m/s), and tol never moves.
D8_AY26_MAX = 2.0
AY26_STEP = 0.25
# What the unedited base tree generated before the freeze, SHA-256 of each output the freeze must leave
# byte for byte (the unchanged-output contract; recorded by the Phase 7 WP2 stage from a generation of the unedited tree). A later
# deliberate change to the overlay, slice.dbc or the VSS pins moves them and records them again.
BASE_SIGSIM_SHA256 = {
    "vss-ids.vspec": "83fe361177a89171a2e3f06a2d1f325df1adfbdec0fddd43ecabebf60e4950a2",
    "vss-can-mapping.json": "d8d69e2f6634e450aa23ff1ab9040a8ab227d30797fe7b1e58a0f1437dc8f8be",
    "vss-databroker.json": "beac13d5fb33c65e8cbf4461776331cbfa14876467276bc6cf19f0ddf882f31e",
    "vehicle-sigsim.vspec": "f94e7846b108d81f503ec06877abfdbda4625cafaedc4593eba63a1b9c582064",
    "vss_contract.h": "1942767ac4a6915a2fda17fc312be52076cb6218e28f020eaaa4cdc41ce09a67",
}
# The two kind 4 files a kind 4 profile change moves. WP1b recorded them from Phase 8's base tree
# before its kind 2 contract joined, which had to leave them byte for byte (spec-2 2.2). WP3b's profiles 4 and 5 move both
# (spec-2 2.2: profile 4's row in vss_profiles.h, both profiles and their envelopes in vss_contract.py), so they are
# recorded again here as WP3b's generation writes them: the kind 2 inputs and any later change that is not a kind 4
# profile change must still leave them byte for byte. WP3c's freeze of profile 5 moves them again and records them again.
# tests/test_sdv_vss_ctl.py holds the rest of WP1b's unchanged set.
BASE_KIND4_SHA256 = {
    "vss_contract.py": "e8dca2c0f3e0fd917af539c9831dabe6b571dffd4b1165a0eac8e085ffd48c9d",
    "vss_profiles.h": "cd43b20eb0550fb7d67857a4e8a4275edd9d834697bc846a1ab16530439e4d63",
}
# Every output the two run types must leave byte for byte (spec-2 2.2: every sigsim and carla output, vss_ctl.h and
# vss_ctl.py), from a generation of the unedited WP3b base tree. The databroker
# catalogues are whole here, the ControlCommand branch included. A later deliberate change to the overlay, slice.dbc,
# the VSS pins or the kind 2 inputs moves them and records them again.
BASE_P8_SHA256 = {
    "vss-ids.vspec": "83fe361177a89171a2e3f06a2d1f325df1adfbdec0fddd43ecabebf60e4950a2",
    "vss-can-mapping.json": "d8d69e2f6634e450aa23ff1ab9040a8ab227d30797fe7b1e58a0f1437dc8f8be",
    "vss-databroker.json": "210e82190a39a56f797d386ede81f50ef0a6c93a18e9a0fd714f9515d3ff9e48",
    "vss-databroker-carla.json": "ab4f6c41c7365ce019762ae2aa187a7f9f2ddb32f4640801dafedf09e91ccdb8",
    "vehicle-sigsim.vspec": "f94e7846b108d81f503ec06877abfdbda4625cafaedc4593eba63a1b9c582064",
    "vehicle-carla.vspec": "3e39502458b324a803f99ab727802f4470d8cb94cfaec1127ebf386a3241a730",
    "vss_contract.h": "1942767ac4a6915a2fda17fc312be52076cb6218e28f020eaaa4cdc41ce09a67",
    "vss_ctl.h": "de63a4c03ba4897ef5f1162a125c4423410d51b9e80cf3d99b0a26552d8353e5",
    "vss_ctl.py": "c6f6a75a7784451e79e37c7e534ccc02e49af6b58ab18d3e9b576b753adf6fe9",
}
# The manifest's vehicle_layer object, which sdv/stack/stack.py reads: its keys as they were before the freeze.
LAYER_KEYS = ("file", "run_type", "profile_id", "source_vehicle", "path", "default", "default_from")


def _load(name, path):
    """Import a file by path without leaving bytecode beside it."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


gen = _load("sdv_vss_generate", GENERATE)


def _fnv1_32(data):
    """FNV-1 32 written out again here, so the digest check does not lean on the generator's copy."""
    h = 0x811C9DC5
    for b in data:
        h = (h * 0x01000193) % (1 << 32)
        h ^= b
    return h


def _dbc():
    return gen.parse_dbc((VSSDIR / "slice.dbc").read_text(encoding="utf-8"))


def _profiles():
    assert tomllib is not None
    with open(VSSDIR / "profiles.toml", "rb") as f:
        return tomllib.load(f)


# ============================================================ pure: the digest

@pytest.mark.parametrize("data,want", [(b"", 0x811C9DC5), (b"a", 0x050C5D7E), (b"foobar", 0x31F0B262)])
def test_fnv1_32_test_vectors(data, want):
    assert gen.fnv1_32(data) == want
    assert _fnv1_32(data) == want


def test_digest_serialises_uids_little_endian_in_slot_order():
    uids = (0x0A1B2C3D, 0x01020304, 0xDEADBEEF, 0x12345678, 0x9ABCDEF0)
    assert gen.uid_bytes_le(uids).hex() == "3d2c1b0a04030201efbeadde78563412f0debc9a"
    assert gen.catalog_digest(uids) == 0xC30680E3
    # The big-endian serialisation hashes differently, so a byte-order slip on either side fails.
    assert _fnv1_32(struct.pack(">5I", *uids)) == 0xFA2112AB
    assert gen.catalog_digest(tuple(reversed(uids))) != 0xC30680E3


@pytest.mark.parametrize("bad", ["0x0a1b2c3d", "0x0A1B2C3", "0x0A1B2C3D0", "0A1B2C3D", " 0x0A1B2C3D", "0x0A1B2C3G", 0x0A1B2C3D, None])
def test_a_malformed_static_uid_is_refused(bad):
    with pytest.raises(gen.Refusal):
        gen.parse_uid(bad)


def test_a_well_formed_static_uid_is_parsed():
    assert gen.parse_uid("0x0A1B2C3D") == 0x0A1B2C3D


def test_the_forbidden_digests_are_all_zeros_and_all_ones():
    assert gen.FORBIDDEN_DIGESTS == (0x00000000, 0xFFFFFFFF)


@pytest.mark.parametrize("digest", [0x00000000, 0xFFFFFFFF])
def test_a_forbidden_digest_is_refused(digest):
    with pytest.raises(gen.Refusal, match="forbidden"):
        gen.check_digest(digest)


@pytest.mark.parametrize("digest", [0x00000001, 0x0A1B2C3D, 0xFFFFFFFE])
def test_any_other_digest_is_accepted(digest):
    assert gen.check_digest(digest) == digest


def test_fidl_inputs_are_found_in_any_case():
    assert gen.fidl_names(["a/spec/x.vspec", "b/VSS.FIDL", "c/vss.fidl", "d/fidl.txt"]) == ["b/VSS.FIDL", "c/vss.fidl"]


def test_the_sdv_tree_holds_no_fidl_file():
    assert gen.fidl_names(str(p) for p in (REPO / "sdv").rglob("*")) == []


# ============================================================ pure: the archive refusals

def _tampered_copy(tmp_path):
    real = CACHE / gen.ARCHIVE_NAME
    if real.exists():
        data = bytearray(real.read_bytes())
        data[len(data) // 2] ^= 0xFF
    else:
        data = bytearray(b"not the pinned archive")
    p = tmp_path / gen.ARCHIVE_NAME
    p.write_bytes(bytes(data))
    return p


def test_a_tampered_archive_is_refused_before_anything_is_read_or_written(tmp_path, capsys):
    archive = _tampered_copy(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "vss-ids.vspec").write_bytes(b"the previous generation")
    rc = gen.main(["--archive", str(archive), "--out", str(out), "--cache", str(tmp_path / "cache"),
                   "--venv", str(tmp_path / "no-venv")])
    err = capsys.readouterr().err
    assert rc == 1
    assert "sha256 mismatch" in err and gen.ARCHIVE_SHA256 in err
    assert sorted(p.name for p in out.iterdir()) == ["vss-ids.vspec"]
    assert (out / "vss-ids.vspec").read_bytes() == b"the previous generation"
    assert not (tmp_path / "cache").exists()


def _archive_with_commit(path, commit, extra_members=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": commit}) as tf:
        body = b"Vehicle:\n  type: branch\n  description: x\n"
        info = tarfile.TarInfo(gen.ARCHIVE_ROOT + "/spec/VehicleSignalSpecification.vspec")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
        for name in extra_members:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))
    path.write_bytes(buf.getvalue())
    return hashlib.sha256(buf.getvalue()).hexdigest()


def test_an_archive_with_another_embedded_commit_is_refused(tmp_path, monkeypatch, capsys):
    archive = tmp_path / gen.ARCHIVE_NAME
    sha = _archive_with_commit(archive, "0" * 40)
    monkeypatch.setattr(gen, "ARCHIVE_SHA256", sha)
    rc = gen.main(["--archive", str(archive), "--out", str(tmp_path / "out"), "--cache", str(tmp_path / "cache"),
                   "--venv", str(tmp_path / "no-venv")])
    err = capsys.readouterr().err
    assert rc == 1
    assert "embedded commit" in err and gen.ARCHIVE_COMMIT in err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("where", ["archive member", "input file"])
def test_a_fidl_file_among_the_inputs_aborts_the_whole_run(tmp_path, monkeypatch, capsys, where):
    """Plan 3.3: the generator never takes Franca input. The archive is otherwise the pinned one (its sha256
    is monkeypatched to the test archive's, its commit is the pin), and --venv points nowhere, so a run that
    got past the .fidl check would refuse for the missing venv instead and never name the file."""
    archive = tmp_path / gen.ARCHIVE_NAME
    member = gen.ARCHIVE_ROOT + "/spec/VehicleSignalSpecification.fidl"
    monkeypatch.setattr(gen, "ARCHIVE_SHA256", _archive_with_commit(archive, gen.ARCHIVE_COMMIT, (member,) if where == "archive member" else ()))
    out = tmp_path / "out"
    out.mkdir()
    (out / "vss-ids.vspec").write_bytes(b"the previous generation")
    argv = ["--archive", str(archive), "--out", str(out), "--cache", str(tmp_path / "cache"), "--venv", str(tmp_path / "no-venv")]
    culprit = member
    if where == "input file":
        overlay = tmp_path / "overlay.FIDL"
        overlay.write_text("Vehicle:\n  type: branch\n  description: x\n", encoding="utf-8")
        argv += ["--overlay", str(overlay)]
        culprit = str(overlay)
    rc = gen.main(argv)
    err = capsys.readouterr().err
    assert rc == 1
    assert "a .fidl file among the inputs" in err and culprit in err
    assert "no vss-tools venv" not in err
    assert sorted(p.name for p in out.iterdir()) == ["vss-ids.vspec"]
    assert (out / "vss-ids.vspec").read_bytes() == b"the previous generation"
    assert not (tmp_path / "cache").exists()


@NEEDS_TOML
def test_a_profile_file_that_breaks_an_invariant_is_refused_before_the_venv_and_any_export(tmp_path, monkeypatch, capsys):
    """The profile file's invariants need no catalogue, so a refused profiles.toml costs no vss-tools run: the generator
    checks them right after the archive and the .fidl check, before the venv. The archive is otherwise the pinned one
    (its sha256 monkeypatched to the test archive's, as in the .fidl case) and --venv points nowhere, so a run that got
    past the check would refuse for the missing venv instead. The rule-26 margins stay after the exports (derive():
    they need the slots' DBC signals from the generated mapping)."""
    archive = tmp_path / gen.ARCHIVE_NAME
    monkeypatch.setattr(gen, "ARCHIVE_SHA256", _archive_with_commit(archive, gen.ARCHIVE_COMMIT))
    profiles = tmp_path / "profiles.toml"
    profiles.write_text((VSSDIR / "profiles.toml").read_text(encoding="utf-8") + "\n[invariants]\nl_mm_max = 60000\n",
                        encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "vss-ids.vspec").write_bytes(b"the previous generation")
    rc = gen.main(["--archive", str(archive), "--profiles", str(profiles), "--out", str(out), "--cache", str(tmp_path / "cache"),
                   "--venv", str(tmp_path / "no-venv")])
    err = capsys.readouterr().err
    assert rc == 1
    assert "REFUSED: profiles.toml: profiles.toml carries an [invariants] table" in err
    assert "no vss-tools venv" not in err
    assert sorted(p.name for p in out.iterdir()) == ["vss-ids.vspec"]
    assert (out / "vss-ids.vspec").read_bytes() == b"the previous generation"
    assert not (tmp_path / "cache").exists()


def test_the_build_input_is_the_source_tag_archive_never_a_release_attachment():
    assert "/archive/refs/tags/" in gen.ARCHIVE_URL and "/releases/" not in gen.ARCHIVE_URL
    assert gen.ARCHIVE_URL.endswith("/" + gen.VSS_TAG + ".tar.gz")


# ============================================================ pure: the venv against the lock

NEEDS_SHELL = pytest.mark.skipif(sys.platform == "win32", reason="the fake venv's python is a #!/bin/sh shim")


def _lock_pins():
    return gen.read_lock(VSSDIR / "requirements.lock")


def _fake_venv(tmp_path, dists, exit_code=0, with_vspec=True):
    """A venv that is only a directory: bin/vspec present and bin/python a shell shim that prints `dists`
    (or fails), which is all check_venv() asks of it."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    if with_vspec:
        (venv / "bin" / "vspec").write_text("#!/bin/sh\n", encoding="utf-8")
    (venv / "dists.json").write_text(json.dumps(dists), encoding="utf-8")
    shim = venv / "bin" / "python"
    shim.write_text('#!/bin/sh\nif [ %d -ne 0 ]; then echo "cannot list" >&2; exit %d; fi\ncat "$(dirname "$0")/../dists.json"\n'
                    % (exit_code, exit_code), encoding="utf-8")
    os.chmod(shim, 0o755)
    return venv


def test_the_lock_pins_vss_tools_at_the_generators_version():
    assert _lock_pins()["vss-tools"] == gen.VSS_TOOLS_VERSION


@NEEDS_SHELL
def test_a_venv_that_equals_the_lock_is_accepted(tmp_path):
    pins = _lock_pins()
    venv = _fake_venv(tmp_path, sorted([n, v] for n, v in pins.items()) + [["pip", "0.0.1"]])
    vspec, listed = gen.check_venv(venv, VSSDIR / "requirements.lock")
    assert vspec == venv / "bin" / "vspec"
    assert listed == sorted("%s==%s" % (n, v) for n, v in pins.items())


@NEEDS_SHELL
def test_a_venv_with_a_wrong_version_is_refused_and_names_the_package(tmp_path):
    pins = _lock_pins()
    dists = [[n, "0.0.0" if n == "pyyaml" else v] for n, v in sorted(pins.items())]
    assert any(n == "pyyaml" for n, _v in dists)
    with pytest.raises(gen.Refusal, match=r"differs from requirements\.lock.*pyyaml==%s \(installed 0\.0\.0\)" % re.escape(pins["pyyaml"])):
        gen.check_venv(_fake_venv(tmp_path, dists), VSSDIR / "requirements.lock")


@NEEDS_SHELL
def test_a_venv_missing_a_pinned_package_is_refused(tmp_path):
    pins = _lock_pins()
    dists = [[n, v] for n, v in sorted(pins.items()) if n != "pyyaml"]
    with pytest.raises(gen.Refusal, match=r"pyyaml==.* \(installed none\)"):
        gen.check_venv(_fake_venv(tmp_path, dists), VSSDIR / "requirements.lock")


@NEEDS_SHELL
def test_a_venv_whose_python_cannot_list_its_packages_is_refused(tmp_path):
    with pytest.raises(gen.Refusal, match="cannot list the venv's packages: cannot list"):
        gen.check_venv(_fake_venv(tmp_path, [], exit_code=3), VSSDIR / "requirements.lock")


@NEEDS_SHELL
def test_a_venv_without_vspec_is_refused(tmp_path):
    with pytest.raises(gen.Refusal, match="no vss-tools venv"):
        gen.check_venv(_fake_venv(tmp_path, [], with_vspec=False), VSSDIR / "requirements.lock")


@NEEDS_SHELL
def test_a_venv_and_lock_that_agree_on_another_vss_tools_are_still_refused(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("vss-tools==6.1.0 \\\n    --hash=sha256:00\n", encoding="utf-8")
    venv = _fake_venv(tmp_path, [["vss-tools", "6.1.0"]])
    with pytest.raises(gen.Refusal, match=r"vss-tools 6\.1\.0 installed, %s pinned" % re.escape(gen.VSS_TOOLS_VERSION)):
        gen.check_venv(venv, lock)


# ============================================================ pure: the catalogue checks on crafted data

_DROP = object()        # in a test's changes: remove the key instead of setting it


def _speed(**changes):
    node = {"type": "sensor", "datatype": "float", "unit": "km/h", "min": 0}
    for k, v in changes.items():
        if v is _DROP:
            del node[k]
        else:
            node[k] = v
    return {"Vehicle.Speed": node}


@pytest.mark.parametrize("changes", [{}, {"min": 0.0}])
def test_vehicle_speed_as_decided_passes(changes):
    assert gen.speed_problems(_speed(**changes)) == []


@pytest.mark.parametrize("changes,why", [
    ({"unit": "m/s"}, "unit is 'm/s'"),
    ({"unit": _DROP}, "unit is None"),
    ({"type": "actuator"}, "type is 'actuator'"),
    ({"datatype": "double"}, "datatype is 'double'"),
    ({"min": _DROP}, "min is None"),
    ({"min": -1}, "min is -1"),
    ({"min": 0.5}, "min is 0.5"),
    ({"min": False}, "min is False"),
    ({"min": "0"}, "min is '0'"),
])
def test_vehicle_speed_that_is_not_a_sensor_float_km_h_with_min_0_is_refused(changes, why):
    problems = gen.speed_problems(_speed(**changes))
    assert len(problems) == 1 and problems[0].startswith("Vehicle.Speed: ") and why in problems[0], problems


def test_a_catalogue_without_vehicle_speed_is_refused():
    assert gen.speed_problems({}) == ["Vehicle.Speed: missing from the generated catalogue"]


def _crafted():
    """One overlay entry, and the id output and mapping JSON that carry it exactly as written."""
    entry = {"type": "sensor", "datatype": "float", "unit": "m/s", "min": 0, "max": 9, "allowed": ["a", "b"],
             "description": "d", "comment": "c", "dbc2vss": {"signal": "S", "interval_ms": 0}}
    ids = {"Vehicle.X.A": {k: entry[k] for k in ("type", "datatype", "unit", "min", "max", "allowed")}}
    mapping = {"Vehicle.X.A": {k: entry[k] for k in ("description", "comment", "dbc2vss")}}
    return {"Vehicle.X.A": entry}, ids, mapping


def test_an_overlay_entry_that_reaches_the_catalogue_as_written_passes():
    overlay, ids, mapping = _crafted()
    assert gen.overlay_differences(overlay, ids, mapping) == []


@pytest.mark.parametrize("side,key,value", [
    ("ids", "type", "actuator"), ("ids", "datatype", "double"), ("ids", "unit", "km/h"), ("ids", "min", 1),
    ("ids", "max", 10), ("ids", "allowed", ["A", "b"]),
    ("mapping", "description", "other"), ("mapping", "comment", "other"), ("mapping", "dbc2vss", {"signal": "T", "interval_ms": 0}),
])
def test_an_overlay_attribute_the_catalogue_does_not_carry_as_written_is_refused(side, key, value):
    """A unit test on crafted data, because no natural case exists: vss-tools 6.0.0 under --strict carried every
    attribute tried (empty, padded and multi-line comments, upper-case allowed values, a transform) through
    unchanged. The end-to-end wiring is tested by tampering with vss-tools' output inside a run."""
    overlay, ids, mapping = _crafted()
    (ids if side == "ids" else mapping)["Vehicle.X.A"][key] = value
    problems = gen.overlay_differences(overlay, ids, mapping)
    assert len(problems) == 1 and problems[0].startswith("Vehicle.X.A: " + key), problems


@pytest.mark.parametrize("dropped", ["ids", "mapping"])
def test_an_overlay_entry_missing_from_the_catalogue_is_refused(dropped):
    overlay, ids, mapping = _crafted()
    del (ids if dropped == "ids" else mapping)["Vehicle.X.A"]
    assert gen.overlay_differences(overlay, ids, mapping) == ["Vehicle.X.A: overlay entry not in the generated catalogue"]


def test_an_attribute_dropped_from_the_id_output_is_refused_too():
    overlay, ids, mapping = _crafted()
    del ids["Vehicle.X.A"]["min"]
    assert gen.overlay_differences(overlay, ids, mapping) == ["Vehicle.X.A: min is None in the id output, 0 in the overlay"]


def test_dbc_signal_problems_lists_a_signal_slice_dbc_does_not_define():
    mapping = {"Vehicle.A": {"dbc2vss": {"signal": "LongVel"}}, "Vehicle.B": {"dbc2vss": {"signal": "NoSuchSignal"}}, "Vehicle.C": {}}
    assert gen.dbc_signal_problems(mapping, _dbc()) == ["Vehicle.B: dbc2vss signal 'NoSuchSignal' is not defined in slice.dbc"]
    del mapping["Vehicle.B"]
    assert gen.dbc_signal_problems(mapping, _dbc()) == []


# ============================================================ pure: the vehicle layer (wire spec 5.6, 14.5; design decision g)

def _sigsim_l(doc):
    """The L the layer must carry, found here independently of generate.py: the profile run type sigsim
    takes by default."""
    return next(p["l_mm"] for p in doc["profiles"] if "sigsim" in p.get("live_default_for", []))


@NEEDS_TOML
def test_the_vehicle_layer_carries_the_live_default_sigsim_profiles_l():
    doc = _profiles()
    layer = gen.vehicle_layer(doc)
    assert layer["file"] == gen.VEHICLE_LAYER == "vehicle-sigsim.vspec" and gen.VEHICLE_LAYER in gen.OUT_FILES
    assert (layer["run_type"], layer["path"], layer["profile_id"]) == ("sigsim", "Vehicle.Chassis.Wheelbase", 1)
    assert layer["default"] == _sigsim_l(doc) and layer["source_vehicle"] == _p(doc, 1)["source_vehicle"]
    text = gen.render_vehicle_layer(layer)
    body = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert body == ["Vehicle.Chassis.Wheelbase:", "  default: %d" % _sigsim_l(doc)]
    assert text.endswith("\n") and "GENERATED" in text.splitlines()[0]


@NEEDS_TOML
@pytest.mark.parametrize("l_mm", [1000, 2650, 6000])
def test_the_vehicle_layers_default_follows_the_profile_file_and_is_no_literal(l_mm):
    """The wheelbase is the profile file's: move L (on every profile of the vehicle and its envelope, as the
    profile invariants require) and the layer follows."""
    doc = copy.deepcopy(_profiles())
    for p in doc["profiles"]:
        if p["source_vehicle"] == _p(doc, 1)["source_vehicle"]:
            p["l_mm"] = l_mm
    doc["envelopes"]["sigsim"]["wheelbase_mm"] = l_mm
    assert gen.check_profiles(doc, _dbc()) == []
    layer = gen.vehicle_layer(doc)
    assert layer["default"] == l_mm
    assert "  default: %d" % l_mm in gen.render_vehicle_layer(layer).splitlines()


@NEEDS_TOML
@pytest.mark.parametrize("name, mutate, why", [
    ("no live default", lambda d: _p(d, 1).update(live_default_for=[]), "has 0 live-default profiles"),
    ("two live defaults", lambda d: _p(d, 2).update(live_default_for=["sigsim"]), "has 2 live-default profiles"),
    ("a stand-in L", lambda d: _p(d, 1).update(stand_in=["l_mm"]), "is a stand-in"),
    ("two wheelbases for one vehicle", lambda d: _p(d, 2).update(l_mm=2800), "one vehicle, one wheelbase"),
    ("no source vehicle", lambda d: _p(d, 1).pop("source_vehicle"), "names no source_vehicle"),
    ("L out of bounds", lambda d: _p(d, 1).update(l_mm=0), "is not an integer in 1000..6000"),
])
def test_a_vehicle_layer_that_cannot_name_one_wheelbase_is_refused(name, mutate, why):
    doc = copy.deepcopy(_profiles())
    mutate(doc)
    with pytest.raises(gen.Refusal, match=re.escape(why)):
        gen.vehicle_layer(doc)


def _layer_case():
    layer = {"file": "vehicle-sigsim.vspec", "path": "Vehicle.Chassis.Wheelbase", "default": 2650}
    node = {"type": "attribute", "datatype": "uint16", "unit": "mm", "staticUID": "0x0A0B0C0D"}      # synthetic, not the stock UID
    return layer, {layer["path"]: dict(node)}, {layer["path"]: dict(node)}, {layer["path"]: {"type": "attribute", "default": 2650}}


def test_a_vehicle_layer_that_reached_the_catalogue_and_moved_no_uid_passes():
    layer, stock, ids, mapping = _layer_case()
    assert gen.vehicle_layer_problems(layer, stock, ids, mapping) == []


def test_a_vehicle_layer_that_moved_the_nodes_static_uid_is_refused():
    """The UID check: `default` is not a staticUID input, so a layer that moves the node's UID restated
    something that is (a unit, min, max, allowed, a datatype)."""
    layer, stock, ids, mapping = _layer_case()
    ids[layer["path"]]["staticUID"] = "0x12345678"
    problems = gen.vehicle_layer_problems(layer, stock, ids, mapping)
    assert problems == ["Vehicle.Chassis.Wheelbase: the vehicle layer vehicle-sigsim.vspec moved its staticUID from the stock "
                        "tree's 0x0A0B0C0D to 0x12345678"]


@pytest.mark.parametrize("where, key, value, why", [
    ("mapping", "default", 0, "default 0 in the mapping JSON, the vehicle layer vehicle-sigsim.vspec sets 2650"),
    ("mapping", "default", None, "default None in the mapping JSON"),
    ("mapping", "default", True, "default True in the mapping JSON"),
    ("ids", "unit", "cm", "is attribute in cm, the vehicle layer needs an attribute in mm"),
    ("ids", "type", "sensor", "is sensor in mm, the vehicle layer needs an attribute in mm"),
])
def test_a_vehicle_layer_that_did_not_reach_the_catalogue_as_generated_is_refused(where, key, value, why):
    layer, stock, ids, mapping = _layer_case()
    if value is None:
        del {"ids": ids, "mapping": mapping}[where][layer["path"]][key]
    else:
        {"ids": ids, "mapping": mapping}[where][layer["path"]][key] = value
    problems = gen.vehicle_layer_problems(layer, stock, ids, mapping)
    assert len(problems) == 1 and why in problems[0], problems


@pytest.mark.parametrize("missing", ["stock", "ids", "mapping"])
def test_a_vehicle_layer_whose_node_is_missing_is_refused(missing):
    layer, stock, ids, mapping = _layer_case()
    del {"stock": stock, "ids": ids, "mapping": mapping}[missing][layer["path"]]
    problems = gen.vehicle_layer_problems(layer, stock, ids, mapping)
    assert len(problems) == 1 and "not in the" in problems[0], problems


# ============================================================ pure: one vehicle layer per run type (Phase 7 WP2; spec 2.6)

def _live_l(doc, run_type):
    """The L run_type's layer must carry, found here independently of generate.py: its live-default profile's."""
    return next(p["l_mm"] for p in doc["profiles"] if run_type in p.get("live_default_for", []))


@NEEDS_TOML
def test_there_is_one_vehicle_layer_per_run_type_with_a_live_default():
    """Since Phase 8's WP3b four run types: sigsim and carla first, in their places, then planning-sim and carla-autoware
    (test_the_planning_sim_and_carla_autoware_layers_carry_profile_4s_and_profile_5s_l holds the two new layers)."""
    doc = _profiles()
    layers = gen.vehicle_layers(doc)
    assert gen.VEHICLE_RUN_TYPES == ("sigsim", "carla") + P8_RUN_TYPES and list(layers) == list(gen.VEHICLE_RUN_TYPES)
    assert sorted(layers) == sorted({rt for p in doc["profiles"] for rt in p["live_default_for"]})
    assert layers["sigsim"] == gen.vehicle_layer(doc) and layers["sigsim"]["file"] == gen.VEHICLE_LAYER == "vehicle-sigsim.vspec"
    carla = layers["carla"]
    assert (carla["file"], carla["run_type"], carla["path"], carla["profile_id"]) == ("vehicle-carla.vspec", "carla",
                                                                                      "Vehicle.Chassis.Wheelbase", 3)
    assert carla["default"] == _live_l(doc, "carla") == PROBED[("profiles.3", "l_mm")]
    assert carla["source_vehicle"] == _p(doc, 3)["source_vehicle"] == "carla-ego"
    assert carla["default_from"] == "profiles.toml: l_mm of profile 3, the live-default profile of run type carla"
    assert set(carla) == set(layers["sigsim"]) and set(LAYER_KEYS) <= set(carla)
    body = [ln for ln in gen.render_vehicle_layer(carla).splitlines() if ln and not ln.startswith("#")]
    assert body == ["Vehicle.Chassis.Wheelbase:", "  default: %d" % _live_l(doc, "carla")]
    for name in ("vehicle-sigsim.vspec", "vehicle-carla.vspec", "vss-databroker.json", "vss-databroker-carla.json"):
        assert name in gen.OUT_FILES, name
    assert gen.DATABROKER_CATALOGUES == dict({"sigsim": "vss-databroker.json", "carla": "vss-databroker-carla.json"}, **P8_CATALOGUES)


@NEEDS_TOML
def test_the_planning_sim_and_carla_autoware_layers_carry_profile_4s_and_profile_5s_l():
    """Spec-2 2.1 and 2.2: each new run type's layer is the Wheelbase default its live-default profile's L names (profile 4's
    READ L for planning-sim, profile 5's PROBED L for carla-autoware: profile 5 is uncompiled, but its L is no stand-in, so
    its layer stands), found here independently of generate.py; both layer files and both catalogues are outputs, under
    exactly 2.1's names, after the sigsim and carla ones."""
    doc = _profiles()
    layers = gen.vehicle_layers(doc)
    want = {"planning-sim": (4, READ[("profiles.4", "l_mm")], "autoware-sample-vehicle"),
            "carla-autoware": (5, PROBED[("profiles.5", "l_mm")], "carla010-taxi")}
    for rt, (pid, l_mm, vehicle) in want.items():
        layer = layers[rt]
        assert (layer["file"], layer["run_type"], layer["path"]) == ("vehicle-%s.vspec" % rt, rt, "Vehicle.Chassis.Wheelbase")
        assert (layer["profile_id"], layer["default"], layer["source_vehicle"]) == (pid, l_mm, vehicle) and _live_l(doc, rt) == l_mm
        assert layer["default_from"] == "profiles.toml: l_mm of profile %d, the live-default profile of run type %s" % (pid, rt)
        body = [ln for ln in gen.render_vehicle_layer(layer).splitlines() if ln and not ln.startswith("#")]
        assert body == ["Vehicle.Chassis.Wheelbase:", "  default: %d" % l_mm]
    assert layers["carla-autoware"]["default"] != layers["carla"]["default"], "the 0.10.0 taxi is not the 0.9.16 ego"
    assert tuple(gen.DATABROKER_CATALOGUES[rt] for rt in P8_RUN_TYPES) == tuple(P8_CATALOGUES[rt] for rt in P8_RUN_TYPES)
    names = list(gen.OUT_FILES)
    for name in P8_LAYERS + tuple(P8_CATALOGUES.values()):
        assert names.count(name) == 1, name
    assert names.index("vss-databroker-carla.json") < names.index(P8_CATALOGUES["planning-sim"])
    assert names.index("vehicle-carla.vspec") < names.index(P8_LAYERS[0]) < names.index(P8_LAYERS[1])


@NEEDS_TOML
@pytest.mark.parametrize("rt, pid", [("planning-sim", 4), ("carla-autoware", 5)])
def test_a_new_run_types_layer_follows_its_live_defaults_l_and_is_no_literal(rt, pid):
    """A layer's Wheelbase is its live default's L whatever it is: move it (with every profile of that vehicle and, for
    profile 4, its envelope's wheelbase) and the layer follows; give the run type to another profile and the layer takes
    that profile's L."""
    doc = copy.deepcopy(_profiles())
    for p in doc["profiles"]:
        if p["source_vehicle"] == _p(doc, pid)["source_vehicle"]:
            p["l_mm"] = 2650
    if pid == 4:
        doc["envelopes"]["planning-sim"]["wheelbase_mm"] = 2650
    assert gen.check_profiles(doc, _dbc()) == []
    assert gen.vehicle_layers(doc)[rt]["default"] == 2650
    doc = copy.deepcopy(_profiles())
    _p(doc, pid)["live_default_for"] = []
    _p(doc, 1)["live_default_for"] = ["sigsim", rt]
    layer = gen.vehicle_layers(doc)[rt]
    assert (layer["profile_id"], layer["default"]) == (1, _p(doc, 1)["l_mm"])
    # the layer follows any live default; the profile file's check refuses a planning-sim run type's off its envelope
    assert any("its live-default profile 1 is on envelope sigsim" in p for p in gen.check_profiles(doc, _dbc())) == \
        (rt in gen.SKEW_ROW_RUN_TYPES)


@NEEDS_TOML
@pytest.mark.parametrize("stand_in", [["l_mm"], ["l_mm", "delta_max"]])
def test_the_carla_layer_is_refused_while_profile_3_holds_a_stand_in_l(stand_in):
    """As today's sigsim layer: no catalogue may declare a stand-in L as a vehicle's wheelbase, so a generation whose
    carla live default (profile 3) holds one is refused, whatever its other run type's layer would be."""
    doc = copy.deepcopy(_profiles())
    _p(doc, 3).update(stand_in=stand_in, compiled=False)
    assert gen.check_profiles(doc, _dbc()) == []
    assert gen.vehicle_layer(doc)["run_type"] == "sigsim"                  # the sigsim layer alone is still fine
    with pytest.raises(gen.Refusal, match=re.escape("profile 3's l_mm is a stand-in")):
        gen.vehicle_layers(doc)


@NEEDS_TOML
def test_a_live_default_whose_only_stand_in_is_delta_max_keeps_its_layer():
    """Phase 7 spec 5 item 3's "as today": a layer carries L alone, so only a stand-in L refuses it, as it refused the
    sigsim layer before Phase 7. A carla live default whose one stand-in is delta_max (so uncompiled: the guest never
    judges under it) still gets its layer with its L, and generate.py's docstring and the README state that rule, not
    a wider one (the docstring once said "no single non-stand-in live-default profile")."""
    doc = copy.deepcopy(_profiles())
    _p(doc, 3).update(stand_in=["delta_max"], compiled=False)
    assert gen.check_profiles(doc, _dbc()) == []
    layer = gen.vehicle_layers(doc)["carla"]
    assert (layer["profile_id"], layer["default"]) == (3, _p(doc, 3)["l_mm"])
    docstring = " ".join((gen.__doc__ or "").split())
    assert "whose live-default profile's L is a stand-in" in docstring and "non-stand-in" not in docstring
    readme = " ".join((VSSDIR / "README.md").read_text(encoding="utf-8").split())
    assert "whose profile's L is a stand-in" in readme and "non-stand-in" not in readme


@NEEDS_TOML
def test_a_run_type_with_a_live_default_but_no_vehicle_layer_is_refused():
    """A layer per run type with a live default: a run type that profiles.toml gives a live default and generate.py no
    layer would leave its catalogue serving another vehicle's wheelbase, so the generation is refused."""
    doc = copy.deepcopy(_profiles())
    _p(doc, 2).update(live_default_for=["planning"])
    assert gen.check_profiles(doc, _dbc()) == []
    with pytest.raises(gen.Refusal, match=r"run type\(s\) 'planning' have a live-default profile in profiles\.toml but no vehicle layer"):
        gen.vehicle_layers(doc)


@NEEDS_TOML
def test_an_uncompiled_row_with_a_live_default_but_no_vehicle_layer_is_refused():
    """The sibling case gives the run type to compiled profile 2; the refusal counts every profile's live defaults, so a
    synthetic uncompiled row alone holding 'planning' (profile 2 and the rest as they are) is refused the same way."""
    doc = copy.deepcopy(_profiles())
    doc["profiles"].append(_stand_in_row(doc, live_default_for=["planning"]))
    assert gen.check_profiles(doc, _dbc()) == []
    assert doc["profiles"][-1]["compiled"] is False and "planning" not in _p(doc, 2)["live_default_for"]
    with pytest.raises(gen.Refusal, match=re.escape("run type(s) 'planning' have a live-default profile in profiles.toml but no vehicle layer")):
        gen.vehicle_layers(doc)


@NEEDS_TOML
def test_a_profile_naming_a_known_and_an_unknown_run_type_is_refused():
    """The missing-layer refusal reads every run type a profile names, not only its first."""
    doc = copy.deepcopy(_profiles())
    _p(doc, 1).update(live_default_for=["sigsim", "planning"])
    assert gen.check_profiles(doc, _dbc()) == []
    with pytest.raises(gen.Refusal, match=re.escape("run type(s) 'planning' have a live-default profile in profiles.toml but no vehicle layer")):
        gen.vehicle_layers(doc)


def test_the_readme_outputs_table_names_every_output():
    rows = [ln.split("|")[1] for ln in (VSSDIR / "README.md").read_text(encoding="utf-8").splitlines() if ln.startswith("| `")]
    for name in gen.OUT_FILES:
        assert any("`%s`" % name in cell for cell in rows), name


def test_the_readme_says_where_the_carla_exports_layer_is_recorded():
    """Since Phase 8's WP3b there are three such exports' layers, not one: the sentence names them all."""
    readme = " ".join((VSSDIR / "README.md").read_text(encoding="utf-8").split())
    assert ("`vss_tools.overlays` names the main catalogue's two layers, every other run type's exports' layer is in "
            "`commands`") in readme


@NEEDS_TOML
@pytest.mark.parametrize("run_type", ["sigsim", "carla"] + list(P8_RUN_TYPES))
def test_a_run_type_with_no_live_default_is_refused_its_layer(run_type):
    doc = copy.deepcopy(_profiles())
    for p in doc["profiles"]:
        p["live_default_for"] = [rt for rt in p["live_default_for"] if rt != run_type]
    with pytest.raises(gen.Refusal, match=re.escape("run type %r has 0 live-default profiles" % run_type)):
        gen.vehicle_layers(doc)


@NEEDS_TOML
@pytest.mark.parametrize("l_mm", [1000, 2650, 6000])
def test_the_carla_layers_default_follows_profile_3s_l_and_is_no_literal(l_mm):
    """The carla layer's wheelbase is the profile file's: move profile 3's L and the layer follows."""
    doc = copy.deepcopy(_profiles())
    for p in doc["profiles"]:
        if p["source_vehicle"] == _p(doc, 3)["source_vehicle"]:
            p["l_mm"] = l_mm
    assert gen.check_profiles(doc, _dbc()) == []
    layer = gen.vehicle_layer(doc, "carla")
    assert layer["default"] == l_mm
    assert "  default: %d" % l_mm in gen.render_vehicle_layer(layer).splitlines()


@NEEDS_TOML
@pytest.mark.parametrize("name, mutate, why", [
    ("no live default", lambda d: _p(d, 3).update(live_default_for=[]), "has 0 live-default profiles"),
    ("two live defaults", lambda d: _p(d, 1).update(live_default_for=["sigsim", "carla"]), "has 2 live-default profiles"),
    ("a stand-in L", lambda d: _p(d, 3).update(stand_in=["l_mm"], compiled=False), "is a stand-in"),
    ("two wheelbases for one vehicle",
     lambda d: d["profiles"].append(_stand_in_row(d, source_vehicle="carla-ego", stand_in=[], l_mm=2700)),
     "one vehicle, one wheelbase"),
    ("no source vehicle", lambda d: _p(d, 3).pop("source_vehicle"), "names no source_vehicle"),
    ("L out of bounds", lambda d: _p(d, 3).update(l_mm=0), "is not an integer in 1000..6000"),
])
def test_a_carla_layer_that_cannot_name_one_wheelbase_is_refused(name, mutate, why):
    """The carla layer's refusals are the sigsim layer's, on profile 3."""
    doc = copy.deepcopy(_profiles())
    mutate(doc)
    with pytest.raises(gen.Refusal, match=re.escape(why)):
        gen.vehicle_layer(doc, "carla")


@NEEDS_TOML
@pytest.mark.parametrize("rt, pid", [("planning-sim", 4), ("carla-autoware", 5)])
@pytest.mark.parametrize("name, mutate, why", [
    ("no live default", lambda d, pid, rt: _p(d, pid).update(live_default_for=[]), "has 0 live-default profiles"),
    ("two live defaults", lambda d, pid, rt: _p(d, 1).update(live_default_for=["sigsim", rt]), "has 2 live-default profiles"),
    ("a stand-in L", lambda d, pid, rt: _p(d, pid).update(stand_in=["l_mm"], compiled=False), "is a stand-in"),
    ("two wheelbases for one vehicle",
     lambda d, pid, rt: d["profiles"].append(_stand_in_row(d, source_vehicle=_p(d, pid)["source_vehicle"], stand_in=[], l_mm=2700)),
     "one vehicle, one wheelbase"),
    ("no source vehicle", lambda d, pid, rt: _p(d, pid).pop("source_vehicle"), "names no source_vehicle"),
    ("L out of bounds", lambda d, pid, rt: _p(d, pid).update(l_mm=0), "is not an integer in 1000..6000"),
])
def test_a_new_run_types_layer_that_cannot_name_one_wheelbase_is_refused(rt, pid, name, mutate, why):
    """The new run types' layers refuse as the carla layer does (spec-2 2.2)."""
    doc = copy.deepcopy(_profiles())
    mutate(doc, pid, rt)
    with pytest.raises(gen.Refusal, match=re.escape(why)):
        gen.vehicle_layer(doc, rt)


# ============================================================ pure: drift from the previous generation and from the baseline

def test_uid_changes_are_found_path_by_path():
    prev = {"Vehicle.A": {"staticUID": "0x00000001"}, "Vehicle.B": {"staticUID": "0x00000002"}, "Vehicle.C": {"staticUID": "0x00000003"}}
    now = {"Vehicle.A": {"staticUID": "0x00000001"}, "Vehicle.B": {"staticUID": "0x0000000F"}, "Vehicle.D": {"staticUID": "0x00000004"}}
    assert gen.uid_changes(prev, now) == (["Vehicle.B"], ["Vehicle.C"], ["Vehicle.D"])
    # A swap keeps every UID in the file and moves two paths: only a path-by-path diff sees it.
    swapped = {"Vehicle.A": {"staticUID": "0x00000002"}, "Vehicle.B": {"staticUID": "0x00000001"}}
    assert gen.uid_changes({"Vehicle.A": prev["Vehicle.A"], "Vehicle.B": prev["Vehicle.B"]}, swapped) == (["Vehicle.A", "Vehicle.B"], [], [])


def test_the_previous_generation_refuses_on_a_changed_or_removed_uid_alone_with_vss_tools_silent():
    """The generator's own diff decides; vss-tools' validation is a cross-check (it matches by UID first and
    exits 0 on a breaking change). Each source of drift refuses without the others."""
    assert gen.previous_drift([], [], []) == []
    assert gen.previous_drift(["Vehicle.A"], [], []) == ["changed: Vehicle.A"]
    assert gen.previous_drift([], ["Vehicle.B"], []) == ["removed: Vehicle.B"]
    assert gen.previous_drift([], [], ["[Validation] BREAKING CHANGE: x"]) == ["vss-tools: [Validation] BREAKING CHANGE: x"]
    assert gen.previous_drift(["Vehicle.A"], ["Vehicle.B"], []) == ["changed: Vehicle.A", "removed: Vehicle.B"]


def _ids_for_baseline():
    return {p: {"staticUID": "0x%08X" % (i + 1)} for i, p in enumerate([
        "Vehicle.Acceleration.Longitudinal", "Vehicle.Acceleration.Vertical", "Vehicle.DualVm", "Vehicle.DualVm.Motion",
        "Vehicle.DualVm.Motion.LongitudinalVelocity", "Vehicle.DualVmX.Motion", "Vehicle.Speed"])}


def test_the_baseline_lists_the_slots_and_every_node_of_the_project_branch_only():
    ids = _ids_for_baseline()
    ids["Vehicle.AngularVelocity.Yaw"] = {"staticUID": "0x00000009"}
    assert gen.baseline_paths(ids, "DualVm") == [
        "Vehicle.Acceleration.Longitudinal", "Vehicle.AngularVelocity.Yaw", "Vehicle.DualVm", "Vehicle.DualVm.Motion",
        "Vehicle.DualVm.Motion.LongitudinalVelocity"]
    assert "Vehicle.DualVm.Motion.LongitudinalVelocity" not in gen.baseline_paths(ids, "Other")


def test_the_baseline_drift_names_each_change_removal_addition_and_a_moved_digest():
    base = (0x0A1B2C3D, {"Vehicle.A": 1, "Vehicle.B": 2, "Vehicle.C": 3})
    assert gen.baseline_drift(base, 0x0A1B2C3D, {"Vehicle.A": 1, "Vehicle.B": 2, "Vehicle.C": 3}) == []
    assert gen.baseline_drift(base, 0x0A1B2C3D, {"Vehicle.A": 1, "Vehicle.B": 9, "Vehicle.C": 3}) == ["changed: Vehicle.B"]
    assert gen.baseline_drift(base, 0x0A1B2C3D, {"Vehicle.A": 1, "Vehicle.B": 2}) == ["removed: Vehicle.C"]
    assert gen.baseline_drift(base, 0x0A1B2C3D, {"Vehicle.A": 1, "Vehicle.B": 2, "Vehicle.C": 3, "Vehicle.D": 4}) == ["added: Vehicle.D"]
    assert gen.baseline_drift(base, 0x0A1B2C3E, dict(base[1])) == ["digest: 0x0A1B2C3D in the baseline, 0x0A1B2C3E now"]
    # The digest comes first, so a long list of nodes cannot push it out of a capped refusal.
    assert gen.baseline_drift(base, 0x0A1B2C3E, {"Vehicle.A": 9, "Vehicle.B": 2}) == [
        "digest: 0x0A1B2C3D in the baseline, 0x0A1B2C3E now", "changed: Vehicle.A", "removed: Vehicle.C"]


def test_a_long_refusal_detail_says_how_much_was_left_out():
    assert gen.first_lines(["a", "b", "c"], 5) == ["a", "b", "c"]
    assert gen.first_lines(list("abcdef"), 4) == ["a", "b", "c", "d", "... and 2 more"]


def test_the_baseline_renders_sorted_and_reads_back_the_same():
    uids = {"Vehicle.B": 0x00000002, "Vehicle.A": 0x0A1B2C3D}
    text = gen.render_baseline(0x0A1B2C3D, uids)
    assert text.endswith("\ndigest 0x0A1B2C3D\nVehicle.A 0x0A1B2C3D\nVehicle.B 0x00000002\n") and "\r" not in text
    assert gen.parse_baseline(text) == (0x0A1B2C3D, uids)


@pytest.mark.parametrize("text,why", [
    ("Vehicle.A 0x0A1B2C3D\n", "no digest line"),
    ("digest 0x0A1B2C3D\n", "lists no node"),
    ("digest 0x0A1B2C3D\ndigest 0x0A1B2C3D\nVehicle.A 0x0A1B2C3D\n", "given twice"),
    ("digest 0x0A1B2C3D\nVehicle.A 0x0A1B2C3D\nVehicle.A 0x0A1B2C3D\n", "listed twice"),
    ("digest 0x0A1B2C3D\nVehicle.A 0x0a1b2c3d\n", "malformed staticUID"),
    ("digest 0x0A1B2C3\nVehicle.A 0x0A1B2C3D\n", "malformed staticUID"),
    ("digest 0x0A1B2C3D\nA 0x0A1B2C3D\n", "not a node path"),
    ("digest 0x0A1B2C3D\nVehicle.A 0x0A1B2C3D extra\n", "expected '<path> <staticUID>'"),
])
def test_a_malformed_baseline_is_refused(text, why):
    with pytest.raises(gen.Refusal, match=why):
        gen.parse_baseline(text)


def test_the_committed_uid_baseline_is_canonical_and_its_digest_follows_its_slots():
    """No venv needed: the committed file is exactly what render_baseline() writes for what it says, its
    digest is the FNV-1 of its own five slot UIDs (recomputed here with this file's own FNV code), and it
    lists nothing but the slots and the project branch. Since Phase 8's WP1b the project branch includes the
    ControlCommand layer: its nodes in the file are exactly overlay-ctl.vspec's entries (read here as text)."""
    text = UID_BASELINE.read_text(encoding="utf-8")
    assert "\r" not in text
    digest, uids = gen.parse_baseline(text)
    assert gen.render_baseline(digest, uids) == text
    slots = gen.slot_paths(gen.DEFAULT_BRANCH)
    assert all(p in uids for p in slots)
    slot_uids = [uids[p] for p in slots]
    assert digest == _fnv1_32(struct.pack("<5I", *slot_uids)) == gen.catalog_digest(slot_uids)
    root = gen.branch_path(gen.DEFAULT_BRANCH)
    assert all(p in slots or p == root or p.startswith(root + ".") for p in uids)
    assert root in uids
    entries = re.findall(r"^(Vehicle\.[A-Za-z0-9.]+):\s*$", (VSSDIR / "overlay-ctl.vspec").read_text(encoding="utf-8"), re.M)
    assert entries and all(p == root + ".ControlCommand" or p.startswith(root + ".ControlCommand.") for p in entries)
    assert sorted(p for p in uids if p == root + ".ControlCommand" or p.startswith(root + ".ControlCommand.")) == sorted(entries)
    assert gen.check_digest(digest) == digest


# ============================================================ pure: slice.dbc

def test_the_dbc_reader_reads_the_slice_dbc_periods_factors_and_units():
    dbc = _dbc()
    msgs = dbc["messages"]
    assert sorted(msgs) == ["SliceDynamics", "SliceGear"]
    assert (msgs["SliceDynamics"]["id"], msgs["SliceDynamics"]["period_ms"]) == (0x100, 20)
    assert (msgs["SliceGear"]["id"], msgs["SliceGear"]["period_ms"]) == (0x101, 50)
    sig = msgs["SliceDynamics"]["signals"]
    assert [(n, s["factor"], s["unit"]) for n, s in sig.items()] == [
        ("LongVel", 0.01, "m/s"), ("LongAccel", 0.001, "m/s^2"), ("SteerAngleRow1", 0.01, "degrees"), ("YawRate", 0.01, "degrees/s")]
    assert all(s["signed"] and s["little_endian"] and s["length"] == 16 for s in sig.values())
    gear = msgs["SliceGear"]["signals"]["CurrentGear"]
    assert (gear["factor"], gear["unit"], gear["min"], gear["max"], gear["length"]) == (1.0, "", -128.0, 127.0, 8)
    assert dbc["signal_message"] == {"LongVel": "SliceDynamics", "LongAccel": "SliceDynamics", "SteerAngleRow1": "SliceDynamics",
                                     "YawRate": "SliceDynamics", "CurrentGear": "SliceGear"}


@pytest.mark.parametrize("text,why", [
    ('BO_ 256 A: 8 X\n SG_ S : 0|16@1- (1,0) [0|1] "" Y\nBO_ 257 B: 8 X\n SG_ S : 0|8@1- (1,0) [0|1] "" Y\n', "not unique"),
    ('BO_ 256 A: 8 X\n SG_ S : 0|16@1- (1,0) "" Y\n', "cannot read"),
    ('VERSION ""\nBS_:\n', "no message"),
    ('BO_ 256 A: 8 X\nBA_ "GenMsgCycleTime" BO_ 999 20;\n', "unknown message id"),
])
def test_the_dbc_reader_refuses_what_it_cannot_read_unambiguously(text, why):
    with pytest.raises(gen.Refusal, match=why):
        gen.parse_dbc(text)


# ============================================================ pure: profiles.toml and derived constants

@NEEDS_TOML
def test_the_profile_file_passes_its_invariants():
    assert gen.check_profiles(_profiles(), _dbc()) == []


def _p(doc, pid):
    return next(p for p in doc["profiles"] if p["id"] == pid)


def _stand_in_row(doc, **changes):
    """A synthetic profile row with stand-in values under the first id no profile and no reservation takes: the
    stand-in case, now that no generated row holds one (Phase 7 froze profile 3). Profile 3's limits on the carla
    envelope, its own source vehicle, uncompiled, no live default."""
    used = {p["id"] for p in doc["profiles"]} | {int(k) for k in doc["reserved_ids"]}
    row = dict(copy.deepcopy(_p(doc, 3)), id=min(set(range(1, 256)) - used), source_vehicle="synthetic-stand-in-car",
               stand_in=["l_mm", "delta_max"], compiled=False, live_default_for=[])
    row.update(changes)
    return row


MUTATIONS = {
    "not f32-exact": (lambda d: _p(d, 1).update(v_max=0.1), "binary32"),
    "id 0": (lambda d: _p(d, 1).update(id=0), "1..255"),
    # Since Phase 8's WP3b binds id 4 (profile 4, the planning-sim vehicle it was reserved for), 0 is the one reservation
    # left, and 0 is outside 1..255 anyway: a synthetic reservation in range holds the rule.
    "reserved id": (lambda d: (d["reserved_ids"].update({"200": "a synthetic reservation"}), _p(d, 3).update(id=200)), "reserved"),
    "duplicate id": (lambda d: _p(d, 2).update(id=1), "not unique"),
    "L zero": (lambda d: _p(d, 1).update(l_mm=0), "l_mm"),
    "L not integral": (lambda d: _p(d, 3).update(l_mm=2699.5), "l_mm"),
    "L off the envelope": (lambda d: _p(d, 2).update(l_mm=2800), "wheelbase_mm"),
    "delta_max past tan's domain": (lambda d: _p(d, 1).update(delta_max=58.0), "delta_max"),
    "empty window": (lambda d: _p(d, 1).update(v26_lo=20.0), "v26_lo < v26_hi"),
    "tol at the error bound": (lambda d: _p(d, 1).update(tol26=0.5), "tol26 must be >="),
    "a_y bound zero": (lambda d: _p(d, 3).update(ay26_max=0.0), "ay26_max"),
    "v_tol zero": (lambda d: _p(d, 1).update(v_tol=0.0), "v_tol must be > 0"),
    "two live defaults": (lambda d: _p(d, 2).update(live_default_for=["sigsim"]), "two live-default"),
    "stand-in compiled": (lambda d: d["profiles"].append(_stand_in_row(d, compiled=True)), "must not be compiled"),
    "A too large": (lambda d: d.update(pipeline_allowance_ms=151), "max(GenMsgCycleTime)"),
    "AGE_MAX saturates": (lambda d: d.update(age_max_ms=0xFFFF), "age_max_ms"),
    "0 not reserved": (lambda d: d["reserved_ids"].pop("0"), "reserved_ids must include 0"),
    "L past the upper bound": (lambda d: _p(d, 3).update(l_mm=6001), "1000..6000"),
    "L below the lower bound": (lambda d: _p(d, 3).update(l_mm=999), "1000..6000"),
    "delta_max just past 57 deg": (lambda d: _p(d, 3).update(delta_max=57.5), "delta_max must be in"),
    "an [invariants] table back in the file": (lambda d: d.update(invariants={"l_mm_max": 60000, "delta_max_limit": 90.0}), "[invariants]"),
    "a relaxed bound in an [invariants] table": (lambda d: (d.update(invariants={"l_mm_max": 60000}), _p(d, 3).update(l_mm=59000)),
                                                 "1000..6000"),
}


@NEEDS_TOML
@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_every_profile_invariant_refuses(name):
    doc = copy.deepcopy(_profiles())
    mutate, why = MUTATIONS[name]
    mutate(doc)
    problems = gen.check_profiles(doc, _dbc())
    assert any(why in p for p in problems), problems
    with pytest.raises(gen.Refusal):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)


def test_the_invariant_bounds_are_the_spec_values():
    """Kind 4 wire spec 5.4 (with 7.2 for the tan domain and 7.3 for the error bound): constants of the
    generator, not settings of the file they constrain."""
    assert (gen.L_MM_MIN, gen.L_MM_MAX, gen.DELTA_MAX_LIMIT_DEG, gen.PSI_DOT_KIN_ERROR_BOUND, gen.TOL_OVER_ERROR_MIN) == (
        1000, 6000, 57.0, 1e-5, 1e5)


@NEEDS_TOML
def test_the_profile_file_carries_none_of_the_invariant_bounds():
    doc = _profiles()
    assert "invariants" not in doc
    text = (VSSDIR / "profiles.toml").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(l_mm_min|l_mm_max|delta_max_limit|psi_dot_kin_error_bound|tol_over_error_min)\s*=", text, re.M)


@NEEDS_TOML
@pytest.mark.parametrize("changes", [{"l_mm": 1000}, {"l_mm": 6000}, {"delta_max": 57.0}, {"tol26": 1e-5 * 1e5}])
def test_a_value_exactly_at_a_bound_is_accepted(changes):
    doc = copy.deepcopy(_profiles())
    _p(doc, 3).update(changes)
    assert gen.check_profiles(doc, _dbc()) == []


@NEEDS_TOML
def test_the_derived_constants_are_the_ones_the_wire_spec_computed():
    """Spec 7.4 computed profile 3's joint-grid numbers on its stand-ins (L 2700 mm, delta_max 40 deg, a_y bound 2.0):
    the method still gives them there. The frozen profile 3's own budget is held by its rule below (the PROBED values),
    and its attribution spread is (k_attr - 1) steps whatever they are."""
    d = gen.derive(_profiles(), _dbc(), SLOT_SIGNALS)
    assert d["rule26_message"] == "SliceDynamics"
    assert d["pacing_interval_ms"] == 50 and d["repeat_cap_ms"] == 70
    assert d["rtf_gap"] == 50 / 70
    assert d["rtf_22"] == {"SliceDynamics": 50 / 130, "SliceGear": 50 / 70}
    assert d["rtf_22_run"] == 50 / 70
    assert d["spread_exceeded_ms"] == 30
    b1, b3 = d["rule26_budget"][1], d["rule26_budget"][3]
    assert sorted(d["attribution_spread_ms"]) == [1, 2, 3, 4, 5]
    assert d["attribution_spread_ms"][1] == d["attribution_spread_ms"][2] == 31
    assert b3["k_attr"] >= 2 and d["attribution_spread_ms"][3] == (b3["k_attr"] - 1) * 50
    assert b1["attribution_spread_exact_ms"] == pytest.approx(30.4, abs=0.05)
    assert b1["total"] == pytest.approx(2.0, abs=0.02)
    assert (b1["delta_row"], b1["v_row"], b1["quant_row"]) == pytest.approx((1.48, 0.46, 0.042), abs=0.005)
    spec = copy.deepcopy(_profiles())
    _p(spec, 3).update(l_mm=2700, delta_max=40.0, ay26_max=2.0)
    spec["envelopes"]["carla"].update(steer_rate=10.0, accel_while_steering=3.0, launch_accel=3.0, understeer_gradient=6.0)
    s = gen.derive(spec, _dbc(), SLOT_SIGNALS)
    s3 = s["rule26_budget"][3]
    assert s3["k_attr"] == 2 and s["attribution_spread_ms"][3] == 50
    assert s3["joint_worst_by_steps"] == pytest.approx((6.57, 8.59), abs=0.005)
    assert d["half_lsb"] == {"v": 0.005, "delta": 0.005, "psi_dot": 0.005}


@NEEDS_TOML
def test_every_profile_keeps_its_envelope_margin_and_quantisation_well_below_tol():
    doc = _profiles()
    d = gen.derive(doc, _dbc(), SLOT_SIGNALS)
    for p in doc["profiles"]:
        b = d["rule26_budget"][p["id"]]
        assert b["margin"] >= b["margin_target"], (p["id"], b)
        # slice.dbc asks the quantisation bound to sit "well below" tol; read here as at most a tenth.
        assert d["quant_bound"][p["id"]] <= p["tol26"] / 10, p["id"]


@NEEDS_TOML
def test_the_attribution_spread_follows_tol():
    doc = copy.deepcopy(_profiles())
    _p(doc, 1).update(tol26=4.0)
    d = gen.derive(doc, _dbc(), SLOT_SIGNALS)
    assert d["rule26_budget"][1]["attribution_spread_exact_ms"] == pytest.approx(40.7, abs=0.05)
    assert d["attribution_spread_ms"][1] == 41


@NEEDS_TOML
def test_the_accounting_threshold_and_repeat_cap_follow_the_dbc_period():
    dbc = _dbc()
    dbc["messages"]["SliceDynamics"]["period_ms"] = 10
    d = gen.derive(_profiles(), dbc, SLOT_SIGNALS)
    assert d["spread_exceeded_ms"] == 15 and d["repeat_cap_ms"] == 60
    assert d["rule26_budget"][1]["skew_ms"] == 10
    # The attribution spread is where the rows reach tol, whatever the period: it does not move.
    assert d["attribution_spread_ms"][1] == 31


@NEEDS_TOML
def test_rule_26s_inputs_must_share_one_dbc_message():
    dbc = _dbc()
    dbc["signal_message"]["YawRate"] = "SliceGear"
    with pytest.raises(gen.Refusal, match="share one DBC message"):
        gen.derive(_profiles(), dbc, SLOT_SIGNALS)


@NEEDS_TOML
@pytest.mark.parametrize("pid", [1, 3, 4, 5])
def test_a_budget_that_does_not_close_is_refused(pid):
    """tol below the honest worst at one skew: sigsim's rows at one period (spec 7.4's 1.5 deg/s), profile 3's joint worst
    at one step (a tenth below it, so the case holds whatever a re-read makes the PROBED values); since Phase 8's WP3b
    profile 4's summed rows at the planning-sim skew and profile 5's joint worst on its stand-in rows, each a tenth below."""
    doc = copy.deepcopy(_profiles())
    tol = 1.5 if pid == 1 else 0.9 * gen.derive(doc, _dbc(), SLOT_SIGNALS)["rule26_budget"][pid]["total"]
    _p(doc, pid).update(tol26=tol)
    with pytest.raises(gen.Refusal, match="does not close"):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)


@NEEDS_TOML
@pytest.mark.parametrize("pid", [1, 3, 4, 5])
def test_a_margin_below_the_envelopes_target_is_refused(pid):
    """Spec 7.4 and Phase 7 spec 5 item 2: a budget that closes (tol above the honest worst) with less than its
    envelope's margin_target over it is refused by the generator, not only by a test of the profile file. Since Phase 8's
    WP3b for both new profiles too (spec-2 section 4 item 2): profile 4 on the planning-sim envelope, compiled, and profile
    5 on its stand-in rows, uncompiled."""
    doc = copy.deepcopy(_profiles())
    b = gen.derive(doc, _dbc(), SLOT_SIGNALS)["rule26_budget"][pid]
    tol = 0.99 * b["margin_target"] * b["total"]
    assert tol > b["total"], "premise: the budget still closes, so only the margin can refuse it"
    _p(doc, pid).update(tol26=tol)
    assert gen.check_profiles(doc, _dbc()) == []
    why = "profile %d: the rule-26 margin over tol is %.4f, below envelope %s's margin_target %r" % (
        pid, 0.99 * b["margin_target"], _p(doc, pid)["envelope"], b["margin_target"])
    with pytest.raises(gen.Refusal, match=re.escape(why)):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)


@NEEDS_TOML
def test_a_margin_below_the_envelopes_target_is_refused_for_an_uncompiled_row_too():
    """The margin refusal is for every profile, not only the compiled ones (the core's choice under Phase 7 spec 5 item 2):
    a synthetic uncompiled row, profile 3's limits under its own id, whose tol leaves a hair under the envelope's
    margin_target over the row's derived honest worst is refused with the margin message naming the row's id."""
    doc = copy.deepcopy(_profiles())
    row = _stand_in_row(doc)
    doc["profiles"].append(row)
    assert row["compiled"] is False and row["id"] not in (1, 2, 3)
    b = gen.derive(doc, _dbc(), SLOT_SIGNALS)["rule26_budget"][row["id"]]
    row["tol26"] = 0.99 * b["margin_target"] * b["total"]
    assert row["tol26"] > b["total"], "premise: the budget still closes, so only the margin can refuse it"
    assert gen.check_profiles(doc, _dbc()) == []
    why = "profile %d: the rule-26 margin over tol is %.4f, below envelope %s's margin_target %r" % (
        row["id"], 0.99 * b["margin_target"], row["envelope"], b["margin_target"])
    with pytest.raises(gen.Refusal, match=re.escape(why)):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)


@NEEDS_TOML
def test_a_margin_exactly_at_the_envelopes_target_is_accepted(monkeypatch):
    """Phase 7 spec 5 item 2 asks for a margin of at least the envelope's margin_target: the refusal is for less than it,
    not for equal. derive is handed the real joint-grid budget with its margin set to the target exactly (the one
    boundary no profile of the file sits on) and accepts it."""
    doc = _profiles()
    real, seen = gen.joint_grid_budget, []

    def at_the_target(p, env, *args, **kwargs):
        seen.append(p["id"])
        return dict(real(p, env, *args, **kwargs), margin=env["margin_target"])

    monkeypatch.setattr(gen, "joint_grid_budget", at_the_target)
    d = gen.derive(doc, _dbc(), SLOT_SIGNALS)
    assert 3 in seen, "premise: profile 3's budget came through the replaced function"
    assert d["rule26_budget"][3]["margin"] == d["rule26_budget"][3]["margin_target"] == doc["envelopes"]["carla"]["margin_target"]


@NEEDS_TOML
def test_only_fully_defined_profiles_are_compiled():
    """Since Phase 8's WP3b profiles 1-4 are compiled and profile 5 is not: its own values hold no stand-in, but its
    envelope's rows do (spec-2 2.4), so the profile with every value read and every row it rests on read is the compiled
    set. A synthetic stand-in row beside them passes the file's invariants uncompiled and never joins it."""
    doc = copy.deepcopy(_profiles())
    assert [p["id"] for p in gen.compiled_profiles(doc)] == [1, 2, 3, 4]
    assert all(not p["stand_in"] and not doc["envelopes"][p["envelope"]].get("stand_in") for p in gen.compiled_profiles(doc))
    assert _p(doc, 5)["compiled"] is False and doc["envelopes"][_p(doc, 5)["envelope"]]["stand_in"]
    row = _stand_in_row(doc)
    doc["profiles"].append(row)
    assert gen.check_profiles(doc, _dbc()) == []
    assert [p["id"] for p in gen.compiled_profiles(doc)] == [1, 2, 3, 4] and row["id"] not in (1, 2, 3, 4, 5)


# ============================================================ pure: profile 3 frozen (Phase 7 WP2; spec 5 items 1 and 2)

def _with_probed(doc, values=None):
    """doc with every PROBED value (or every one of VALUES: READ) set where profiles.toml holds it."""
    doc = copy.deepcopy(doc)
    for (table, key), value in (PROBED if values is None else values).items():
        kind, name = table.split(".", 1)
        (_p(doc, int(name)) if kind == "profiles" else doc[kind][name])[key] = value
    return doc


_MARKER = re.compile(r"^# PROBED \(")
_READ_MARKER = re.compile(r"^# READ \(")
_STAND_IN_MARKER = re.compile(r"^# STAND-IN \(")
# A table's name may carry a hyphen since Phase 8's WP3b ([envelopes.planning-sim]).
_TABLE = re.compile(r"^\[\[?([a-z0-9_.-]+)\]\]?\s*$")
_ASSIGN = re.compile(r"^([a-z0-9_]+)\s*=\s*(.+?)\s*$")


def _probed_lines(text, marker=_MARKER):
    """{(table, key): value} of each assignment of profiles.toml whose comment block starts a line with
    `# PROBED (` (or the MARKER given: `# READ (`; a profile's table named profiles.<id>); a blank line or a table ends a
    block."""
    assert tomllib is not None
    out, table, pid, marked = {}, "", None, False
    for line in text.splitlines():
        if marker.match(line):
            marked = True
        elif not line.strip():
            marked = False
        elif line.startswith("#"):
            continue
        elif _TABLE.match(line):
            table, pid, marked = _TABLE.match(line).group(1), None, False
        else:
            m = _ASSIGN.match(line)
            assert m, line
            if table == "profiles" and m.group(1) == "id":
                pid = int(m.group(2))
            if marked:
                where = "profiles.%s" % pid if table == "profiles" else table
                assert (where, m.group(1)) not in out, (where, m.group(1))
                out[(where, m.group(1))] = tomllib.loads("v = " + m.group(2))["v"]
                marked = False
    return out


@NEEDS_TOML
def test_the_probed_values_are_marked_in_the_profile_file_and_held_once():
    """Phase 7 spec 5 item 1: every value WP0's probes set is marked `# PROBED (` in profiles.toml, holds there what
    PROBED holds, and no row still waits for a probe; the envelope rows say where they come from and carry no reading."""
    text = (VSSDIR / "profiles.toml").read_text(encoding="utf-8")
    marked = _probed_lines(text)
    assert marked == PROBED and all(type(marked[k]) is type(v) for k, v in PROBED.items())
    assert _with_probed(_profiles()) == _profiles(), "the file holds every PROBED value where it is marked"
    assert "PENDING-PROBE" not in text and "UNVERIFIED" not in text and "until the envelope read" not in text
    rows = [k for (table, k) in PROBED if table == "envelopes.carla"]
    for line in text.splitlines():
        if _MARKER.match(line) and "F8" in line:
            assert "fitted locally; the readings are not published" in line, line
    assert sum(1 for line in text.splitlines() if _MARKER.match(line) and "F8" in line) == len(rows) == 4
    # Profile 5's two (Phase 8 WP3b) name WP9a's facts, and the carla010 envelope's rows are no PROBED value: they are
    # stand-ins, marked so (test_profile_5_is_uncompiled_on_its_stand_in_envelope).
    assert [k for k in PROBED if k[0] == "profiles.5"] == [("profiles.5", "l_mm"), ("profiles.5", "delta_max")]
    for line in text.splitlines():
        if _MARKER.match(line) and "WP9a" in line:
            assert line.startswith("# PROBED (Phase 8 WP9a "), line
    assert sum(1 for line in text.splitlines() if _MARKER.match(line) and "WP9a" in line) == 2
    assert not [k for k in PROBED if k[0] == "envelopes.carla010"]
    # Each L is the one of them no other number of these files stands for: written once in the profile file, once in this
    # file's PROBED, and in no other file this package owns.
    for key in (("profiles.3", "l_mm"), ("profiles.5", "l_mm")):
        lit = re.compile(r"(?<![\w.])%d(?![\w.])" % PROBED[key])
        assert len(lit.findall(text)) == 1, key
        assert len(lit.findall(Path(__file__).read_text(encoding="utf-8"))) == 1, key
        for f in (GENERATE, VSSDIR / "README.md", HERE / "test_monitor_kind4.py", HERE / "test_monitor_kind4_console.py",
                  HERE / "test_sdv_bridge.py", HERE / "test_sdv_frame.py"):
            assert not lit.findall(f.read_text(encoding="utf-8")), (key, f)


@NEEDS_TOML
def test_profile_3_is_frozen_on_the_probed_values():
    """Spec 5 item 1 (D6-D8): compiled, no stand-in, L and delta_max the PROBED values (delta_max whole degrees within
    the tan domain, F4's rule), and every other limit as it was: v_max, a_max (D7), the window, tol26, v_tol."""
    doc = _profiles()
    p = _p(doc, 3)
    assert (p["source_vehicle"], p["limit_set"], p["envelope"]) == ("carla-ego", "nominal", "carla")
    assert p["compiled"] is True and p["stand_in"] == []
    assert p["l_mm"] == PROBED[("profiles.3", "l_mm")]
    assert p["delta_max"] == PROBED[("profiles.3", "delta_max")] <= gen.DELTA_MAX_LIMIT_DEG
    assert float(p["delta_max"]).is_integer() and gen.f32_exact(p["delta_max"])
    assert (p["v_max"], p["a_max"], p["v26_lo"], p["v26_hi"], p["tol26"], p["v_tol"]) == (40.0, 10.0, 1.0, 10.0, 8.0, 1.0)
    assert p["live_default_for"] == ["carla"] and gen.check_profiles(doc, _dbc()) == []
    assert doc["envelopes"]["carla"]["budget"] == "joint-grid" and doc["envelopes"]["carla"]["margin_target"] == 1.2


def _half_lsb():
    sig = _dbc()["messages"]["SliceDynamics"]["signals"]
    return tuple(sig[s]["factor"] / 2.0 for s in ("LongVel", "SteerAngleRow1", "YawRate"))


def _one_step_margin(doc, pid):
    """The joint-grid margin over tol at one step (spec 7.4), 0.0 when the budget does not close."""
    p = _p(doc, pid)
    try:
        return gen.joint_grid_budget(p, doc["envelopes"][p["envelope"]], _half_lsb(), doc["carla_step_ms"], doc["rule26"])["margin"]
    except gen.Refusal:
        return 0.0


def _widest_closing_ay(doc, pid=3):
    """Spec 5 item 2's rule: D8's bound, narrowed by AY26_STEP until the joint-grid margin reaches the envelope's
    margin_target; None when no step above zero does (then the v26_hi step, then the owner's call)."""
    target = doc["envelopes"][_p(doc, pid)["envelope"]]["margin_target"]
    k = 0
    while D8_AY26_MAX - k * AY26_STEP > 0:
        trial = copy.deepcopy(doc)
        _p(trial, pid)["ay26_max"] = D8_AY26_MAX - k * AY26_STEP
        if _one_step_margin(trial, pid) >= target:
            return D8_AY26_MAX - k * AY26_STEP
        k += 1
    return None


@NEEDS_TOML
def test_profile_3s_a_y_bound_is_d8s_narrowed_only_as_far_as_its_budget_needs():
    """On the PROBED values: the file's ay26_max is the widest quarter step from D8's that closes the budget with the
    envelope's margin_target, never wider than D8's (a bound narrowed further than the budget needs, or widened past
    D8's, is refused here), and tol and v26_hi are not what moved."""
    doc = _profiles()
    want = _widest_closing_ay(_with_probed(doc))
    assert want is not None, "no a_y step closes profile 3's budget: the v26_hi step (spec 5 item 2), then the owner's call"
    p = _p(doc, 3)
    assert p["ay26_max"] == want <= D8_AY26_MAX and gen.f32_exact(want)
    if want < D8_AY26_MAX:
        wider = copy.deepcopy(doc)
        _p(wider, 3)["ay26_max"] = want + AY26_STEP
        assert _one_step_margin(wider, 3) < doc["envelopes"]["carla"]["margin_target"]
    assert _one_step_margin(doc, 3) >= doc["envelopes"]["carla"]["margin_target"]
    assert (p["tol26"], p["v26_hi"]) == (8.0, 10.0)


# ============================================================ pure: profiles 4 and 5 (Phase 8 WP3b; spec-2 2.4, section 4)

def _rows_summed_total(l_mm, v_hi, env, skew_ms):
    """Spec 7.4's summed rows written out again here, not read from generate.py: the delta-skew row at (v26_hi, delta 0),
    the v-skew row at the envelope's product bound accel_while_steering x tan(turn_steer_max), and the quantisation row
    at (v26_hi, 0), each at skew_ms of skew; deg/s."""
    L = l_mm / 1000.0
    _hv, hd, hpsi = _half_lsb()
    s = skew_ms / 1000.0
    delta_row = v_hi / L * env["steer_rate"] * s
    v_row = 180.0 / math.pi * env["accel_while_steering"] * math.tan(math.radians(env["turn_steer_max"])) / L * s
    return delta_row + v_row + v_hi / L * hd + hpsi


@NEEDS_TOML
def test_profile_4_is_compiled_on_the_read_values():
    """Spec-2 2.4: the planning simulator's sample vehicle on the planning-sim envelope, compiled with no stand-in. L,
    delta_max and v26_hi are the READ values: delta_max by the rule profile 3's comment states, min(57, ceil(the source's
    single-track maximum + 5)) whole degrees, on the simulator's looser steer_lim (the cap binds); v26_hi the smallest whole
    m/s above the planner's max_vel. v_max and a_max are profile 1's, v26_lo and v_tol every profile's. No a_y bound: the
    simulator's DELAY_STEER_ACC_GEARED model is a kinematic bicycle with no slip (its source at 1.0.0, read by the WP3b
    stage; local notes). Run type planning-sim's live default; id 4, which is no longer reserved (0 alone is)."""
    doc = _profiles()
    p = _p(doc, 4)
    assert (p["source_vehicle"], p["limit_set"], p["envelope"]) == ("autoware-sample-vehicle", "nominal", "planning-sim")
    assert p["compiled"] is True and p["stand_in"] == [] and p["live_default_for"] == ["planning-sim"]
    assert p["l_mm"] == READ[("profiles.4", "l_mm")]
    steer_lim_deg = READ[("envelopes.planning-sim", "steer_max")]
    assert p["delta_max"] == READ[("profiles.4", "delta_max")] == min(gen.DELTA_MAX_LIMIT_DEG, math.ceil(steer_lim_deg + 5))
    assert p["v26_hi"] == READ[("profiles.4", "v26_hi")] == math.floor(READ[("envelopes.planning-sim", "cruise_speed")]) + 1 == 5.0
    assert (p["v_max"], p["a_max"], p["v26_lo"], p["v_tol"]) == (40.0, 10.0, 1.0, 1.0)
    assert (p["v_max"], p["a_max"]) == (_p(doc, 1)["v_max"], _p(doc, 1)["a_max"])
    assert p["ay26_max"] == "none"
    assert {int(k) for k in doc["reserved_ids"]} == {0}
    assert gen.check_profiles(doc, _dbc()) == []


@NEEDS_TOML
def test_the_planning_sim_envelope_is_sigsims_row_set_with_the_simulators_skew():
    """Spec-2 2.4: rows-summed with sigsim's margin_target and row set, plus skew_ms (25: the simulator's timer); its
    wheelbase the profile's L; no stand-in row. The three design rows no read bounds stay inside what the reads bound: no
    turning or braking angle past the simulator's steer limit, no reverse speed past the planner's top speed."""
    doc = _profiles()
    env, sigsim = doc["envelopes"]["planning-sim"], doc["envelopes"]["sigsim"]
    assert set(env) == set(sigsim) | {"skew_ms"} and "stand_in" not in env
    assert (env["budget"], env["margin_target"]) == ("rows-summed", PLANNING_SIM_MARGIN) == (sigsim["budget"], sigsim["margin_target"])
    assert env["wheelbase_mm"] == _p(doc, 4)["l_mm"]
    assert env["skew_ms"] == READ[("envelopes.planning-sim", "skew_ms")] == 25 and type(env["skew_ms"]) is int
    assert env["turn_steer_max"] <= env["steer_max"] and env["braking_steer_max"] <= env["steer_max"]
    assert env["reverse_speed_max"] <= env["cruise_speed"]
    assert [p["id"] for p in doc["profiles"] if p["envelope"] == "planning-sim"] == [4]


@NEEDS_TOML
def test_the_read_values_are_marked_in_the_profile_file_and_held_once():
    """Spec-2 section 4 item 2: every value WP4a's reads set is marked `# READ (W4 <fact>` in profiles.toml, naming its
    fact, holds there what READ holds, and is not also a PROBED value; profile 4's L (with the envelope's wheelbase, which
    must equal it) is written twice in the profile file, twice in this file's READ, and in no other file this package owns."""
    text = (VSSDIR / "profiles.toml").read_text(encoding="utf-8")
    marked = _probed_lines(text, _READ_MARKER)
    assert marked == READ and all(type(marked[k]) is type(v) for k, v in READ.items())
    assert _with_probed(_profiles(), READ) == _profiles(), "the file holds every READ value where it is marked"
    reads = [line for line in text.splitlines() if _READ_MARKER.match(line)]
    assert len(reads) == len(READ) and all(re.match(r"^# READ \(W4 [PG]\d+(, [PG]\d+)*\): ", line) for line in reads), reads
    assert not set(READ) & set(PROBED)
    lit = re.compile(r"(?<![\w.])%d(?![\w.])" % READ[("profiles.4", "l_mm")])
    assert len(lit.findall(text)) == 2
    assert len(lit.findall(Path(__file__).read_text(encoding="utf-8"))) == 2
    for f in (GENERATE, VSSDIR / "README.md", HERE / "test_monitor_kind4.py", HERE / "test_monitor_kind4_console.py",
              HERE / "test_sdv_bridge.py", HERE / "test_sdv_frame.py"):
        assert not lit.findall(f.read_text(encoding="utf-8")), f


@NEEDS_TOML
def test_profile_4s_tol26_is_the_smallest_tenth_that_keeps_the_planning_sim_margin():
    """Spec-2 2.4: the summed rows at the planning-sim skew (the envelope's own 25 ms, not slice.dbc's period) on the READ
    rows and the design turn_steer_max, written out here; tol26 is the smallest one-decimal value with at least the
    envelope's margin over them: it keeps the margin, a tenth less does not, and the generator refuses that one."""
    doc = _profiles()
    p, env = _p(doc, 4), doc["envelopes"]["planning-sim"]
    total = _rows_summed_total(p["l_mm"], p["v26_hi"], env, 25)
    b = gen.derive(doc, _dbc(), SLOT_SIGNALS)["rule26_budget"][4]
    assert b["method"] == "rows-summed" and b["skew_ms"] == 25 and b["total"] == pytest.approx(total, rel=1e-12)
    tenths = round(p["tol26"] / TOL26_STEP)
    assert p["tol26"] == round(tenths * TOL26_STEP, 1), "tol26 has one decimal"
    assert p["tol26"] / total >= PLANNING_SIM_MARGIN > (tenths - 1) * TOL26_STEP / total
    assert b["margin"] >= b["margin_target"] == PLANNING_SIM_MARGIN
    lower = copy.deepcopy(doc)
    _p(lower, 4)["tol26"] = round((tenths - 1) * TOL26_STEP, 1)
    with pytest.raises(gen.Refusal, match=re.escape("profile 4: the rule-26 margin over tol is")):
        gen.derive(lower, _dbc(), SLOT_SIGNALS)


@NEEDS_TOML
def test_the_planning_sim_skew_row_replaces_the_dbc_period_for_that_envelope_alone():
    """Spec-2 2.4: in a planning-sim run no CAN message carries rule 26's triple, and the simulator publishes all three on
    its one timer, so profile 4's summed rows take the envelope's skew_ms; every other rows-summed profile keeps
    slice.dbc's period of the message that carries the triple, and follows it when it moves, while profile 4's does not."""
    d = gen.derive(_profiles(), _dbc(), SLOT_SIGNALS)
    period = _dbc()["messages"]["SliceDynamics"]["period_ms"]
    assert period != 25, "premise: the two skews differ, so the test can tell them apart"
    assert d["rule26_budget"][4]["skew_ms"] == 25
    assert d["rule26_budget"][1]["skew_ms"] == d["rule26_budget"][2]["skew_ms"] == period
    dbc = _dbc()
    dbc["messages"]["SliceDynamics"]["period_ms"] = 10
    moved = gen.derive(_profiles(), dbc, SLOT_SIGNALS)
    assert moved["rule26_budget"][1]["skew_ms"] == 10 and moved["rule26_budget"][4] == d["rule26_budget"][4]


SKEW_PROBLEM = "a skew_ms row on an envelope that is not a planning-sim one"


@NEEDS_TOML
@pytest.mark.parametrize("envelope", ["sigsim", "carla", "carla010", "a copy of planning-sim under another name"])
def test_a_skew_ms_row_is_refused_on_an_envelope_that_is_not_a_planning_sim_one(envelope):
    """Spec-2 2.4's second new refusal: the skew row replaces slice.dbc's period for the planning-sim envelope only; on any
    other envelope (a rows-summed one, a joint-grid one, or the planning-sim rows under another name) it is refused, so
    no envelope's skew can be moved off the period of the message that carries rule 26's triple by a row."""
    doc = copy.deepcopy(_profiles())
    if envelope.startswith("a copy"):
        envelope = "planning-sim-copy"
        doc["envelopes"][envelope] = doc["envelopes"].pop("planning-sim")
        _p(doc, 4)["envelope"] = envelope
    else:
        doc["envelopes"][envelope]["skew_ms"] = 25
    problems = gen.check_profiles(doc, _dbc())
    assert [p for p in problems if SKEW_PROBLEM in p] == [
        "envelope %s: %s (its skew is slice.dbc's period of the message that carries rule 26's triple)" % (envelope, SKEW_PROBLEM)]
    with pytest.raises(gen.Refusal, match=re.escape(SKEW_PROBLEM)):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)


@NEEDS_TOML
@pytest.mark.parametrize("value", [0, -25, 25.0, True, "25"])
def test_a_planning_sim_skew_that_is_not_a_positive_whole_ms_is_refused(value):
    doc = copy.deepcopy(_profiles())
    doc["envelopes"]["planning-sim"]["skew_ms"] = value
    assert "envelope planning-sim: skew_ms must be a positive integer (ms)" in gen.check_profiles(doc, _dbc())


@NEEDS_TOML
def test_a_skew_ms_row_on_an_envelope_whose_budget_is_not_rows_summed_is_refused():
    """The joint-grid budget counts whole steps and never reads a skew row, so a planning-sim envelope made joint-grid would
    carry a row nothing uses: refused rather than silently ignored."""
    doc = copy.deepcopy(_profiles())
    doc["envelopes"]["planning-sim"]["budget"] = "joint-grid"
    assert "envelope planning-sim: skew_ms is a rows-summed budget's row, this envelope's budget is 'joint-grid'" in \
        gen.check_profiles(doc, _dbc())


@NEEDS_TOML
def test_the_skew_row_is_tied_to_the_run_types_whose_triple_comes_from_one_timer():
    """The planning-sim skew row describes a run type, not a name: SKEW_ROW_RUN_TYPES are the run types whose rule-26
    triple comes from the simulator's one timer, each a vehicle run type, and the file as it stands gives each of them its
    live default on a SKEW_ROW_ENVELOPES envelope and makes no profile there the live default of any other run type."""
    doc = _profiles()
    assert gen.SKEW_ROW_RUN_TYPES == ("planning-sim",) and set(gen.SKEW_ROW_RUN_TYPES) <= set(gen.VEHICLE_RUN_TYPES)
    live = {rt: p for p in doc["profiles"] for rt in p["live_default_for"]}
    assert {rt for rt, p in live.items() if p["envelope"] in gen.SKEW_ROW_ENVELOPES} == set(gen.SKEW_ROW_RUN_TYPES)
    assert gen.check_profiles(doc, _dbc()) == []


@NEEDS_TOML
@pytest.mark.parametrize("run_type, owner", [("carla", 3), ("sigsim", 1), ("carla-autoware", 5)])
def test_a_profile_on_a_planning_sim_envelope_is_refused_as_the_live_default_of_another_run_type(run_type, owner):
    """The hard review's C5: profile 4 made carla's live default too (profile 3 nobody's). Without this refusal the carla
    layer would carry profile 4's L and a CAN run type's live default would be budgeted at the simulator's 25 ms skew, not
    slice.dbc's period; likewise for sigsim and carla-autoware. Refused with the profile, its envelope and the run type
    named, by check_profiles (so before the venv) and by derive."""
    doc = copy.deepcopy(_profiles())
    _p(doc, owner)["live_default_for"] = [rt for rt in _p(doc, owner)["live_default_for"] if rt != run_type]
    _p(doc, 4)["live_default_for"] = ["planning-sim", run_type]
    want = ("profile 4: on the planning-sim envelope planning-sim, so it may be the live default of a planning-sim run type "
            "only (SKEW_ROW_RUN_TYPES), not of %r" % run_type)
    assert gen.check_profiles(doc, _dbc()) == [want]
    with pytest.raises(gen.Refusal, match=re.escape(want)):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)


@NEEDS_TOML
@pytest.mark.parametrize("owner", [1, 2, 3, 5])
def test_a_planning_sim_run_types_live_default_on_another_envelope_is_refused(owner):
    """The hard review's C7: profile 1 (a CAN vehicle's L, on the sigsim envelope) made planning-sim's live default and
    profile 4 nobody's. Without this refusal the planning-sim layer would carry profile 1's L while profile 4 stayed compiled
    at the skew of a run type it is no live default of; likewise for each other profile. Refused with the run type, the
    profile and its envelope named."""
    doc = copy.deepcopy(_profiles())
    _p(doc, 4)["live_default_for"] = []
    _p(doc, owner)["live_default_for"] = _p(doc, owner)["live_default_for"] + ["planning-sim"]
    want = ("run type 'planning-sim': its live-default profile %d is on envelope %s, not a planning-sim one "
            "(SKEW_ROW_ENVELOPES: planning-sim)" % (owner, _p(doc, owner)["envelope"]))
    assert gen.check_profiles(doc, _dbc()) == [want]
    with pytest.raises(gen.Refusal, match=re.escape(want)):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)


_LIVE_DEFAULT_EDITS = {
    "planning-sim-profile-made-carlas": (
        (('live_default_for = ["carla"]\n', 'live_default_for = []\n'),
         ('live_default_for = ["planning-sim"]\n', 'live_default_for = ["planning-sim", "carla"]\n')),
        "profile 4: on the planning-sim envelope planning-sim, so it may be the live default of a planning-sim run type only "
        "(SKEW_ROW_RUN_TYPES), not of 'carla'"),
    "sigsim-profile-made-planning-sims": (
        (('live_default_for = ["planning-sim"]\n', 'live_default_for = []\n'),
         ('live_default_for = ["sigsim"]\n', 'live_default_for = ["sigsim", "planning-sim"]\n')),
        "run type 'planning-sim': its live-default profile 1 is on envelope sigsim, not a planning-sim one "
        "(SKEW_ROW_ENVELOPES: planning-sim)"),
}


@NEEDS_TOML
@pytest.mark.parametrize("case", sorted(_LIVE_DEFAULT_EDITS))
def test_a_live_default_that_parts_the_skew_row_from_its_run_type_is_refused_before_the_venv(tmp_path, monkeypatch, capsys, case):
    """End to end, on the profile file's text: either edit of the two above is refused with the profile file's
    invariants, right after the archive and before the venv (--venv points nowhere, so a run past the check would refuse
    for the venv instead), and the previous generation stays as it was."""
    archive = tmp_path / gen.ARCHIVE_NAME
    monkeypatch.setattr(gen, "ARCHIVE_SHA256", _archive_with_commit(archive, gen.ARCHIVE_COMMIT))
    text = (VSSDIR / "profiles.toml").read_text(encoding="utf-8")
    edits, want = _LIVE_DEFAULT_EDITS[case]
    for old, new in edits:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(text, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "vss-ids.vspec").write_bytes(b"the previous generation")
    rc = gen.main(["--archive", str(archive), "--profiles", str(profiles), "--out", str(out), "--cache", str(tmp_path / "cache"),
                   "--venv", str(tmp_path / "no-venv")])
    err = capsys.readouterr().err
    assert rc == 1
    assert "generate.py: REFUSED: profiles.toml: %s\n" % want in err
    assert "no vss-tools venv" not in err
    assert sorted(p.name for p in out.iterdir()) == ["vss-ids.vspec"]
    assert (out / "vss-ids.vspec").read_bytes() == b"the previous generation"
    assert not (tmp_path / "cache").exists()


@NEEDS_TOML
def test_profile_5_is_uncompiled_on_its_stand_in_envelope():
    """Spec-2 2.4 (D18): the CARLA 0.10.0 taxi on the carla010 envelope, uncompiled until WP3c. Its own values hold no
    stand-in: L and delta_max PROBED, the rest profile 3's (v_max and a_max D7's, the window, tol26 and v_tol); its a_y
    bound D8's narrowed by the same rule (test_profile_5s_budget_...). The envelope's four rows are stand-ins, the carla
    envelope's values, listed in its stand_in and each marked `# STAND-IN (` in the file. Run type carla-autoware's live
    default."""
    doc = _profiles()
    p, three = _p(doc, 5), _p(doc, 3)
    assert (p["source_vehicle"], p["limit_set"], p["envelope"]) == ("carla010-taxi", "nominal", "carla010")
    assert p["compiled"] is False and p["stand_in"] == [] and p["live_default_for"] == ["carla-autoware"]
    assert p["l_mm"] == PROBED[("profiles.5", "l_mm")] and p["delta_max"] == PROBED[("profiles.5", "delta_max")]
    assert float(p["delta_max"]).is_integer() and p["delta_max"] <= gen.DELTA_MAX_LIMIT_DEG
    assert (p["v_max"], p["a_max"], p["v26_lo"], p["v26_hi"], p["tol26"], p["v_tol"]) == (40.0, 10.0, 1.0, 10.0, 8.0, 1.0)
    assert all(p[k] == three[k] for k in ("v_max", "a_max", "v26_lo", "v26_hi", "tol26", "v_tol"))
    env, carla = doc["envelopes"]["carla010"], doc["envelopes"]["carla"]
    assert (env["budget"], env["margin_target"]) == ("joint-grid", 1.2) and "skew_ms" not in env and "wheelbase_mm" not in env
    assert tuple(env["stand_in"]) == CARLA010_STAND_IN
    assert {k: v for k, v in env.items() if k != "stand_in"} == carla
    text = (VSSDIR / "profiles.toml").read_text(encoding="utf-8")
    assert _probed_lines(text, _STAND_IN_MARKER) == {("envelopes.carla010", k): carla[k] for k in CARLA010_STAND_IN}
    assert [p["id"] for p in doc["profiles"] if p["envelope"] == "carla010"] == [5]
    assert gen.check_profiles(doc, _dbc()) == []


@NEEDS_TOML
def test_profile_5s_budget_keeps_its_envelopes_margin_on_the_stand_ins_with_d8s_bound_narrowed_only_as_needed():
    """Spec-2 section 4 item 2: profile 5's joint-grid margin, computed on the stand-in rows (informative until WP3c), must
    hold; its a_y bound is the widest quarter step from D8's that keeps it (Phase 7 spec 5 item 2's rule, as profile 3's),
    and tol and v26_hi are not what moved."""
    doc = _profiles()
    want = _widest_closing_ay(doc, 5)
    assert want is not None, "no a_y step closes profile 5's budget: the v26_hi step, then the owner's call"
    p = _p(doc, 5)
    assert p["ay26_max"] == want <= D8_AY26_MAX and gen.f32_exact(want)
    if want < D8_AY26_MAX:
        wider = copy.deepcopy(doc)
        _p(wider, 5)["ay26_max"] = want + AY26_STEP
        assert _one_step_margin(wider, 5) < doc["envelopes"]["carla010"]["margin_target"]
    b = gen.derive(doc, _dbc(), SLOT_SIGNALS)["rule26_budget"][5]
    assert b["method"] == "joint-grid" and b["margin"] >= b["margin_target"] == 1.2
    assert (p["tol26"], p["v26_hi"]) == (8.0, 10.0)


@NEEDS_TOML
def test_a_compiled_profile_on_an_envelope_that_holds_a_stand_in_row_is_refused():
    """Spec-2 2.4's first new refusal: profile 5 compiled while the carla010 envelope holds stand-in rows is refused, the
    message naming the profile, the envelope and its rows; so is a compiled profile 3 once its own envelope lists a row as a
    stand-in. With the list emptied (what WP3c's freeze does, beside the rows) profile 5 compiles."""
    doc = copy.deepcopy(_profiles())
    _p(doc, 5)["compiled"] = True
    want = "profile 5: compiled on envelope carla010, which holds stand-in rows (%s)" % ", ".join(CARLA010_STAND_IN)
    assert want in gen.check_profiles(doc, _dbc())
    with pytest.raises(gen.Refusal, match=re.escape(want)):
        gen.derive(doc, _dbc(), SLOT_SIGNALS)
    doc = copy.deepcopy(_profiles())
    doc["envelopes"]["carla"]["stand_in"] = ["understeer_gradient"]
    assert "profile 3: compiled on envelope carla, which holds stand-in rows (understeer_gradient)" in gen.check_profiles(doc, _dbc())
    doc = copy.deepcopy(_profiles())
    doc["envelopes"]["carla010"]["stand_in"] = []
    _p(doc, 5)["compiled"] = True
    assert gen.check_profiles(doc, _dbc()) == []


@NEEDS_TOML
@pytest.mark.parametrize("stand_in", [["steer_rate", "no_such_row"], "steer_rate", ["budget"], ["margin_target"], [1], ["stand_in"],
                                      ["wheelbase_mm"]])
def test_an_envelopes_stand_in_list_names_only_its_own_rows(stand_in):
    doc = copy.deepcopy(_profiles())
    doc["envelopes"]["carla010"]["stand_in"] = stand_in
    assert any(p.startswith("envelope carla010: stand_in must be a list of this envelope's own row names")
               for p in gen.check_profiles(doc, _dbc()))


@NEEDS_TOML
@pytest.mark.parametrize("envelope", ["sigsim", "planning-sim"])
def test_an_envelopes_wheelbase_is_no_row_that_its_stand_in_list_may_name(envelope):
    """carla010 holds no wheelbase_mm, so the case above is refused whether or not the key counts as a row; these two
    envelopes hold one, which is the profiles' L and not a budget row: naming it is refused, and the refusal's list of rows
    does not offer it."""
    doc = copy.deepcopy(_profiles())
    assert isinstance(doc["envelopes"][envelope].get("wheelbase_mm"), int)
    doc["envelopes"][envelope]["stand_in"] = ["wheelbase_mm"]
    refused = [p for p in gen.check_profiles(doc, _dbc())
               if p.startswith("envelope %s: stand_in must be a list of this envelope's own row names" % envelope)]
    assert len(refused) == 1 and "wheelbase_mm" not in refused[0], refused


@NEEDS_TOML
@pytest.mark.parametrize("field", ["l_mm", "delta_max", "v26_hi"])
def test_profile_4_compiled_with_a_stand_in_is_refused(field):
    doc = copy.deepcopy(_profiles())
    _p(doc, 4)["stand_in"] = [field]
    assert "profile 4: a profile with stand-in values (%s) must not be compiled" % field in gen.check_profiles(doc, _dbc())


@NEEDS_TOML
def test_the_new_profiles_leave_the_sigsim_and_carla_budgets_and_every_shared_constant_as_they_were():
    """Spec-2 2.4: the sigsim and carla budget outputs stay byte for byte. Derived with and without profiles 4 and 5 (and
    their envelopes, with id 4 reserved again), profiles 1-3's budgets, spreads and quantisation bounds and every constant
    shared by all profiles are equal."""
    doc = _profiles()
    old = copy.deepcopy(doc)
    old["profiles"] = [p for p in old["profiles"] if p["id"] in (1, 2, 3)]
    for name in ("planning-sim", "carla010"):
        del old["envelopes"][name]
    old["reserved_ids"]["4"] = "planning-sim vehicle (Phase 8.0)"
    d, before = gen.derive(doc, _dbc(), SLOT_SIGNALS), gen.derive(old, _dbc(), SLOT_SIGNALS)
    for pid in (1, 2, 3):
        assert d["rule26_budget"][pid] == before["rule26_budget"][pid], pid
        assert d["attribution_spread_ms"][pid] == before["attribution_spread_ms"][pid], pid
        assert d["quant_bound"][pid] == before["quant_bound"][pid], pid
    assert {k: v for k, v in d.items() if k not in ("rule26_budget", "attribution_spread_ms", "quant_bound")} == \
        {k: v for k, v in before.items() if k not in ("rule26_budget", "attribution_spread_ms", "quant_bound")}


def test_the_stock_units_yaml_has_every_unit_kind_4_needs():
    """Phase 1 builds on stock VSS 6.0 units: every kind 4 unit is there, and the Phase 8 ones are not."""
    archive = CACHE / gen.ARCHIVE_NAME
    if not archive.exists():
        pytest.skip("the pinned VSS archive is not in %s yet (the first generation run fetches it)" % CACHE)
    if gen.sha256_file(archive) != gen.ARCHIVE_SHA256:
        pytest.fail("the cached archive does not match its pin")
    with tarfile.open(archive, "r:gz") as tf:
        f = tf.extractfile(gen.ARCHIVE_ROOT + "/spec/units.yaml")
        assert f is not None
        text = f.read().decode("utf-8")
    keys = set(re.findall(r"^([^\s#][^:]*):\s*$", text, re.M))
    assert set(gen.KIND4_UNITS) <= keys
    assert "rad" not in keys and "m/s^3" not in keys


# ============================================================ generation (needs the venv)

def _run(*args):
    argv = [str(a) for a in args]
    # A run that accepts a UID change rewrites the baseline it is given: it must never be the committed one.
    assert "--accept-uid-change" not in argv or "--uid-baseline" in argv, "give an accepting run its own copy of the baseline"
    return subprocess.run([str(VENV_PY), str(GENERATE)] + argv, capture_output=True, text=True, timeout=900)


# generate.py imported inside the venv, with a patch applied before main() runs. `after(label, fn)` calls
# fn(work_dir) right after the vss-tools run of that label ("id export", "json export", ...), i.e. it lets a
# test hand the generator vss-tools output that differs from the overlay, which no real vss-tools run does.
_DRIVER = r"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("generate_under_test", sys.argv[1])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
_real_run_vspec = g.run_vspec
def after(label, tamper):
    def run_vspec(vspec, args, cwd, what, allow_warnings=False):
        lines = _real_run_vspec(vspec, args, cwd, what, allow_warnings)
        if what == label:
            tamper(cwd)
        return lines
    g.run_vspec = run_vspec
exec(sys.argv[2])
sys.exit(g.main(sys.argv[3:]))
"""


def _run_patched(patch, *args):
    argv = [str(a) for a in args]
    assert "--accept-uid-change" not in argv or "--uid-baseline" in argv, "give an accepting run its own copy of the baseline"
    return subprocess.run([str(VENV_PY), "-B", "-c", _DRIVER, str(GENERATE), patch] + argv, capture_output=True, text=True, timeout=900)


def _committed_baseline_is_untouched():
    assert UID_BASELINE.read_bytes() == _COMMITTED_BASELINE


def _yaml_as_json(path):
    code = "import json, sys, yaml; json.dump(yaml.load(open(sys.argv[1]), Loader=yaml.CSafeLoader), sys.stdout)"
    r = subprocess.run([str(VENV_PY), "-c", code, str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@pytest.fixture(scope="session")
def baseline(tmp_path_factory):
    if not (VENV / "bin" / "vspec").exists():
        pytest.skip("needs the vss-tools venv ~/sdv-venv (sdv/vss/README.md)")
    out = tmp_path_factory.mktemp("sdv") / "base"
    r = _run("--out", out, "--no-previous")
    assert r.returncode == 0, r.stderr
    return {"out": out, "mod": _load("vss_contract_base", out / "vss_contract.py"), "stdout": r.stdout}


def _outputs(d):
    return {p.name: p.read_bytes() for p in sorted(Path(d).iterdir()) if p.is_file()}


@NEEDS_VENV
def test_two_runs_are_byte_identical_the_second_validating_in_place(baseline, tmp_path):
    again = tmp_path / "gen"
    shutil.copytree(baseline["out"], again)
    (again / "__pycache__").mkdir(exist_ok=True)          # what importing vss_contract.py in place leaves
    (again / "__pycache__" / "vss_contract.cpython-312.pyc").write_bytes(b"stale")
    r = _run("--out", again)
    assert r.returncode == 0, r.stderr
    assert "0 changed, 0 removed, 0 added; vss-tools validation: 0 line(s)" in r.stdout
    assert "uid-baseline.txt: %d node(s), unchanged" % len(gen.parse_baseline(UID_BASELINE.read_text(encoding="utf-8"))[1]) in r.stdout
    assert _outputs(again) == _outputs(baseline["out"])
    assert sorted(_outputs(again)) == sorted(gen.OUT_FILES)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["gen"]          # no staging or old directory left


def _c_macros(path):
    return dict(re.findall(r"^#define (\w+) (.+)$", Path(path).read_text(encoding="utf-8"), re.M))


@NEEDS_VENV
def test_the_digest_recomputed_here_from_the_id_output_matches_both_constant_files(baseline):
    ids = _yaml_as_json(baseline["out"] / "vss-ids.vspec")
    mod = baseline["mod"]
    uids = []
    for path in mod.SLOT_PATHS:
        text = ids[path]["staticUID"]
        assert re.fullmatch(r"0x[0-9A-F]{8}", text)
        uids.append(int(text, 16))
    digest = _fnv1_32(struct.pack("<5I", *uids))
    assert digest not in (0, 0xFFFFFFFF)
    assert tuple(uids) == mod.SLOT_UIDS
    assert digest == mod.CATALOG_DIGEST
    macros = _c_macros(baseline["out"] / "vss_contract.h")
    assert macros["VSS_CATALOG_DIGEST"] == "0x%08Xu" % digest
    assert [macros["VSS_UID_SLOT%d" % i] for i in range(5)] == ["0x%08Xu" % u for u in uids]
    assert "0x%08X" % digest in baseline["stdout"]
    manifest = json.loads((baseline["out"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind4"]["catalog_digest"] == "0x%08X" % digest


@NEEDS_VENV
def test_each_slot_uid_is_the_fnv1_of_its_identifier_lower_cased(baseline):
    """The staticUID inputs as vss-tools 6.0.0 assembles them (name, unit, datatype, type, allowed, min,
    max; lower-cased when case-insensitive), recomputed here for the five slots and Vehicle.Speed."""
    ids = _yaml_as_json(baseline["out"] / "vss-ids.vspec")
    for path in baseline["mod"].SLOT_PATHS + ("Vehicle.Speed",):
        n = ids[path]
        ident = "%s: unit: %s, datatype: %s, type: %sallowed: %smin: %smax: %s" % (
            path, n.get("unit", ""), n.get("datatype", ""), n["type"], n.get("allowed", ""), n.get("min", ""), n.get("max", ""))
        assert "0x%08X" % _fnv1_32(ident.lower().encode()) == n["staticUID"], path


def _overlay_variant(tmp_path, old, new, count=1):
    text = (VSSDIR / "overlay.vspec").read_text(encoding="utf-8")
    assert text.count(old) == count, (old, text.count(old))
    p = tmp_path / "overlay.vspec"
    p.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
    return p


@NEEDS_VENV
def test_a_slot_unit_change_moves_the_digest_and_is_refused_against_the_previous_generation(baseline, tmp_path):
    overlay = _overlay_variant(tmp_path, "  datatype: float\n  unit: m/s\n  description: \"Signed longitudinal",
                               "  datatype: float\n  unit: km/h\n  description: \"Signed longitudinal")
    refused = tmp_path / "refused"
    r = _run("--overlay", overlay, "--out", refused, "--previous-ids", baseline["out"] / "vss-ids.vspec")
    assert r.returncode == 1
    assert "staticUIDs moved" in r.stderr and "changed: Vehicle.DualVm.Motion.LongitudinalVelocity" in r.stderr
    assert not refused.exists()
    accepted = tmp_path / "accepted"
    copy = tmp_path / "uid-baseline.txt"
    copy.write_bytes(UID_BASELINE.read_bytes())
    r = _run("--overlay", overlay, "--out", accepted, "--previous-ids", baseline["out"] / "vss-ids.vspec", "--accept-uid-change",
             "--uid-baseline", copy)
    assert r.returncode == 0, r.stderr
    mod, base = _load("vss_contract_unit", accepted / "vss_contract.py"), baseline["mod"]
    assert mod.SLOT_UNITS[0] == "km/h"
    assert mod.CATALOG_DIGEST != base.CATALOG_DIGEST
    assert mod.SLOT_UIDS[0] != base.SLOT_UIDS[0] and mod.SLOT_UIDS[1:] == base.SLOT_UIDS[1:]
    _committed_baseline_is_untouched()


def _set_uid(text, path, uid):
    """The id output with one node's staticUID replaced (a hand edit of a previous generation)."""
    pattern = re.compile(r"(^%s:\n(?: .*\n)*?  staticUID: ')0x[0-9A-F]{8}(')" % re.escape(path), re.M)
    new, n = pattern.subn(lambda m: m.group(1) + uid + m.group(2), text)
    assert n == 1, path
    return new


def _uid_in(text, path):
    m = re.search(r"^%s:\n(?: .*\n)*?  staticUID: '(0x[0-9A-F]{8})'" % re.escape(path), text, re.M)
    assert m, path
    return m.group(1)


@NEEDS_VENV
def test_a_hand_edited_previous_generation_is_refused_by_the_generators_own_uid_diff(baseline, tmp_path):
    """One slot's staticUID altered in a copy of the previous vss-ids.vspec (same paths, valid YAML). vss-tools'
    own validation flags that too (a breaking change), so this shows the letter of the rule."""
    text = (baseline["out"] / "vss-ids.vspec").read_text(encoding="utf-8")
    path = "Vehicle.Powertrain.Transmission.CurrentGear"
    previous = tmp_path / "previous-ids.vspec"
    previous.write_text(_set_uid(text, path, "0x00000001"), encoding="utf-8", newline="\n")
    r = _run("--out", tmp_path / "out", "--previous-ids", previous)
    assert r.returncode == 1
    assert "staticUIDs moved since the previous generation" in r.stderr and "changed: " + path in r.stderr
    assert "differ from the committed baseline" not in r.stderr       # the committed baseline agrees with this generation
    assert not (tmp_path / "out").exists()


@NEEDS_VENV
def test_the_uid_diff_refuses_where_vss_tools_validation_says_nothing(baseline, tmp_path):
    """Two slots' staticUIDs swapped in the previous generation: every UID is still in the file, so vss-tools
    matches each node to the other's entry by UID and reports no breaking change; only the generator's path-by-
    path diff sees that two paths moved. (With one UID altered vss-tools flags it as well, so that case cannot
    tell the two judges apart.)"""
    text = (baseline["out"] / "vss-ids.vspec").read_text(encoding="utf-8")
    a, b = "Vehicle.Acceleration.Longitudinal", "Vehicle.AngularVelocity.Yaw"
    ua, ub = _uid_in(text, a), _uid_in(text, b)
    assert ua != ub
    previous = tmp_path / "previous-ids.vspec"
    previous.write_text(_set_uid(_set_uid(text, a, ub), b, ua), encoding="utf-8", newline="\n")
    r = _run("--out", tmp_path / "out", "--previous-ids", previous)
    assert r.returncode == 1
    assert "changed: " + a in r.stderr and "changed: " + b in r.stderr
    assert "vss-tools:" not in r.stderr and "removed:" not in r.stderr
    assert "differ from the committed baseline" not in r.stderr
    assert not (tmp_path / "out").exists()
    # The same previous generation is accepted when the change is (the run still leaves the baseline alone).
    copy = tmp_path / "uid-baseline.txt"
    copy.write_bytes(UID_BASELINE.read_bytes())
    r = _run("--out", tmp_path / "out", "--previous-ids", previous, "--accept-uid-change", "--uid-baseline", copy)
    assert r.returncode == 0, r.stderr
    assert "2 changed, 0 removed, 0 added" in r.stdout and "(accepted)" in r.stdout
    assert copy.read_bytes() == UID_BASELINE.read_bytes()
    _committed_baseline_is_untouched()


@NEEDS_VENV
def test_the_committed_uid_baseline_is_what_the_pinned_inputs_generate(baseline):
    """Since Phase 8's WP1b the baseline also lists the ControlCommand layer's eleven nodes, which vss-ids.vspec does not
    carry (it stays the export without the layer): those lines are held against the databroker catalogue's nodes, each UID
    vss-tools' identifier of the node's own attributes (name, unit, datatype, type, allowed, min, max; lower-cased),
    recomputed here; every other line against the id file, as before."""
    ids = _yaml_as_json(baseline["out"] / "vss-ids.vspec")
    mod = baseline["mod"]
    digest, uids = gen.parse_baseline(UID_BASELINE.read_text(encoding="utf-8"))
    branch = [p for p in ids if p == "Vehicle.DualVm" or p.startswith("Vehicle.DualVm.")]
    broker = gen.json_nodes(json.loads((baseline["out"] / "vss-databroker.json").read_text(encoding="utf-8")))
    ctl = [p for p in broker if p == "Vehicle.DualVm.ControlCommand" or p.startswith("Vehicle.DualVm.ControlCommand.")]
    assert len(ctl) == 11 and not set(ctl) & set(ids)
    assert sorted(uids) == sorted(set(branch) | set(mod.SLOT_PATHS) | set(ctl))
    for path, uid in uids.items():
        if path in ctl:
            n = broker[path]
            ident = "%s: unit: %s, datatype: %s, type: %sallowed: %smin: %smax: %s" % (
                path, n.get("unit", ""), n.get("datatype", ""), n["type"], n.get("allowed", ""), n.get("min", ""), n.get("max", ""))
            assert uid == _fnv1_32(ident.lower().encode()), path
        else:
            assert ids[path]["staticUID"] == "0x%08X" % uid, path
    assert digest == mod.CATALOG_DIGEST
    assert [uids[p] for p in mod.SLOT_PATHS] == list(mod.SLOT_UIDS)


@NEEDS_VENV
def test_a_drift_from_the_uid_baseline_is_refused_until_accepted_and_then_stable(baseline, tmp_path):
    overlay = _overlay_variant(tmp_path, "  datatype: float\n  unit: m/s\n  description: \"Signed longitudinal",
                               "  datatype: float\n  unit: km/h\n  description: \"Signed longitudinal")
    copy = tmp_path / "uid-baseline.txt"
    copy.write_bytes(UID_BASELINE.read_bytes())
    r = _run("--overlay", overlay, "--out", tmp_path / "refused", "--no-previous", "--uid-baseline", copy)
    assert r.returncode == 1
    assert "differ from the committed baseline" in r.stderr and "changed: Vehicle.DualVm.Motion.LongitudinalVelocity" in r.stderr
    assert "digest: 0x%08X in the baseline" % baseline["mod"].CATALOG_DIGEST in r.stderr
    assert "since the previous generation" not in r.stderr
    assert not (tmp_path / "refused").exists()
    assert copy.read_bytes() == UID_BASELINE.read_bytes()             # a refusal rewrites nothing
    r = _run("--overlay", overlay, "--out", tmp_path / "accepted", "--no-previous", "--uid-baseline", copy, "--accept-uid-change")
    assert r.returncode == 0, r.stderr
    mod = _load("vss_contract_baseline_drift", tmp_path / "accepted" / "vss_contract.py")
    digest, uids = gen.parse_baseline(copy.read_text(encoding="utf-8"))
    assert digest == mod.CATALOG_DIGEST != baseline["mod"].CATALOG_DIGEST
    assert uids["Vehicle.DualVm.Motion.LongitudinalVelocity"] == mod.SLOT_UIDS[0]
    assert gen.render_baseline(digest, uids) == copy.read_text(encoding="utf-8")
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith(".")) == []     # no temporary file left behind
    r = _run("--overlay", overlay, "--out", tmp_path / "again", "--no-previous", "--uid-baseline", copy)
    assert r.returncode == 0, r.stderr
    assert "unchanged" in r.stdout
    _committed_baseline_is_untouched()


@NEEDS_VENV
def test_a_new_node_under_the_project_branch_is_a_drift_from_the_uid_baseline(baseline, tmp_path):
    text = (VSSDIR / "overlay.vspec").read_text(encoding="utf-8")
    overlay = tmp_path / "overlay.vspec"
    overlay.write_text(text + "\nVehicle.DualVm.Motion.Extra:\n  type: sensor\n  datatype: float\n  unit: m/s\n"
                       "  description: \"A node the baseline does not list.\"\n", encoding="utf-8", newline="\n")
    r = _run("--overlay", overlay, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1
    assert "added: Vehicle.DualVm.Motion.Extra" in r.stderr and "changed:" not in r.stderr and "removed:" not in r.stderr
    assert "digest:" not in r.stderr                                    # the slots did not move
    assert not (tmp_path / "out").exists()
    _committed_baseline_is_untouched()


@NEEDS_VENV
def test_a_missing_uid_baseline_is_refused_and_created_only_on_request(baseline, tmp_path):
    missing = tmp_path / "elsewhere" / "uid-baseline.txt"
    r = _run("--out", tmp_path / "refused", "--no-previous", "--uid-baseline", missing)
    assert r.returncode == 1 and "no UID baseline at" in r.stderr and "--accept-uid-change" in r.stderr
    assert not missing.parent.exists() and not (tmp_path / "refused").exists()
    r = _run("--out", tmp_path / "created", "--no-previous", "--uid-baseline", missing, "--accept-uid-change")
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in missing.parent.iterdir()) == ["uid-baseline.txt"]
    assert missing.read_bytes() == UID_BASELINE.read_bytes()          # what the generator writes is what is committed
    _committed_baseline_is_untouched()


@NEEDS_VENV
def test_renaming_the_project_branch_moves_the_digest(baseline, tmp_path):
    overlay = _overlay_variant(tmp_path, "Vehicle.DualVm", "Vehicle.DualVmTest",
                               count=(VSSDIR / "overlay.vspec").read_text(encoding="utf-8").count("Vehicle.DualVm"))
    # Phase 8 WP1b loads the ControlCommand layer too, which names the branch: the rename covers both layers.
    ctl = tmp_path / "overlay-ctl.vspec"
    ctl.write_text((VSSDIR / "overlay-ctl.vspec").read_text(encoding="utf-8").replace("Vehicle.DualVm", "Vehicle.DualVmTest"),
                   encoding="utf-8", newline="\n")
    r = _run("--overlay", overlay, "--overlay-ctl", ctl, "--out", tmp_path / "wrong-branch", "--no-previous")
    assert r.returncode == 1 and "added outside the project branch Vehicle.DualVm" in r.stderr
    r = _run("--overlay", overlay, "--overlay-ctl", ctl, "--out", tmp_path / "unaccepted", "--no-previous", "--project-branch", "DualVmTest")
    assert r.returncode == 1
    # The detail is capped (first_lines): the digest comes first and the removed nodes sort from the branch itself.
    assert "differ from the committed baseline" in r.stderr and "  removed: Vehicle.DualVm\n" in r.stderr
    assert "digest: 0x%08X in the baseline" % baseline["mod"].CATALOG_DIGEST in r.stderr
    assert re.search(r"\.\.\. and \d+ more", r.stderr)
    assert not (tmp_path / "unaccepted").exists()
    copy = tmp_path / "uid-baseline.txt"
    copy.write_bytes(UID_BASELINE.read_bytes())
    r = _run("--overlay", overlay, "--overlay-ctl", ctl, "--out", tmp_path / "renamed", "--no-previous", "--project-branch", "DualVmTest",
             "--accept-uid-change", "--uid-baseline", copy)
    assert r.returncode == 0, r.stderr
    mod, base = _load("vss_contract_branch", tmp_path / "renamed" / "vss_contract.py"), baseline["mod"]
    assert mod.PROJECT_BRANCH == "Vehicle.DualVmTest"
    assert mod.SLOT_PATHS[0] == "Vehicle.DualVmTest.Motion.LongitudinalVelocity"
    assert mod.CATALOG_DIGEST != base.CATALOG_DIGEST
    assert mod.SLOT_UIDS[1:] == base.SLOT_UIDS[1:]
    assert "Vehicle.DualVmTest.Motion.LongitudinalVelocity" in gen.parse_baseline(copy.read_text(encoding="utf-8"))[1]
    _committed_baseline_is_untouched()


@NEEDS_VENV
def test_a_restated_standard_unit_is_refused(tmp_path):
    overlay = _overlay_variant(tmp_path, "Vehicle.Acceleration.Longitudinal:\n  type: sensor\n  datatype: float\n",
                               "Vehicle.Acceleration.Longitudinal:\n  type: sensor\n  datatype: float\n  unit: m/s\n")
    r = _run("--overlay", overlay, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1
    assert "Vehicle.Acceleration.Longitudinal: staticUID" in r.stderr and "stock tree" in r.stderr
    assert not (tmp_path / "out").exists()


@NEEDS_VENV
def test_a_dbc2vss_signal_slice_dbc_does_not_define_is_refused(tmp_path):
    overlay = _overlay_variant(tmp_path, "    signal: LongAccel\n", "    signal: LongAccelX\n")
    r = _run("--overlay", overlay, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1
    assert "Vehicle.Acceleration.Longitudinal: dbc2vss signal 'LongAccelX' is not defined in slice.dbc" in r.stderr
    assert not (tmp_path / "out").exists()


@NEEDS_VENV
def test_a_vehicle_speed_without_min_0_is_refused(tmp_path):
    """Vehicle.Speed is exempt from the stock comparison (its UID changes on purpose), so nothing but its own
    check holds the decision that it is never negative."""
    overlay = _overlay_variant(tmp_path, "  datatype: float\n  min: 0\n  comment: \"Never negative", "  datatype: float\n  comment: \"Never negative")
    r = _run("--overlay", overlay, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1
    assert "Vehicle.Speed: min is None, the catalogue needs 0" in r.stderr
    assert not (tmp_path / "out").exists()


_TAMPER_ID_UNIT = r'''
import re
def tamper(cwd):
    p = cwd / "vss-ids.vspec"
    new, n = re.subn(r"(Vehicle\.DualVm\.Motion\.LongitudinalVelocity:\n(?: .*\n)*?  unit: )m/s\n", r"\1km/h\n", p.read_text(), count=1)
    assert n == 1
    p.write_text(new)
after("id export", tamper)
'''
_TAMPER_MAPPING_COMMENT = r'''
import json
def tamper(cwd):
    p = cwd / "vss-can-mapping.json"
    tree = json.loads(p.read_text())
    tree["Vehicle"]["children"]["Speed"]["comment"] = "not what the overlay says"
    p.write_text(json.dumps(tree, indent=2))
after("json export", tamper)
'''
_TAMPER_MAPPING_NODE = r'''
import json
def tamper(cwd):
    p = cwd / "vss-can-mapping.json"
    tree = json.loads(p.read_text())
    del tree["Vehicle"]["children"]["DualVm"]["children"]["Motion"]
    p.write_text(json.dumps(tree, indent=2))
after("json export", tamper)
'''


@NEEDS_VENV
@pytest.mark.parametrize("patch,expected", [
    (_TAMPER_ID_UNIT, "Vehicle.DualVm.Motion.LongitudinalVelocity: unit is 'km/h' in the id output, 'm/s' in the overlay"),
    (_TAMPER_MAPPING_COMMENT, "Vehicle.Speed: comment differs between the overlay and the mapping JSON"),
    (_TAMPER_MAPPING_NODE, "the mapping JSON and the id output list different nodes"),
])
def test_an_overlay_entry_the_vss_tools_output_does_not_carry_as_written_is_refused_end_to_end(baseline, tmp_path, patch, expected):
    """The wiring of overlay_differences() and of the node-set check: vss-tools' own output is altered inside the
    run (a real run carries every overlay attribute through, so the refusal cannot be reached by an overlay)."""
    r = _run_patched(patch, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the generated catalogue fails its checks" in r.stderr and expected in r.stderr
    assert not (tmp_path / "out").exists()


@NEEDS_VENV
def test_a_forbidden_digest_is_refused_end_to_end(baseline, tmp_path):
    r = _run_patched("g.catalog_digest = lambda uids: 0xFFFFFFFF", "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the catalogue digest is 0xFFFFFFFF, which is forbidden" in r.stderr
    assert not (tmp_path / "out").exists()


@NEEDS_VENV
def test_the_id_file_and_the_can_mapping_keep_their_layers_and_the_ctl_layer_joins_the_databroker_exports_only(baseline):
    """Was test_the_overlay_and_the_vehicle_layer_are_the_only_layers_and_no_control_command_node_is_generated. Phase 8's
    WP1b loads ControlCommand (overlay-ctl.vspec, with units-project.yaml and quantities-project.yaml) for the databroker
    catalogues and the kind 2 contract: the id file and the CAN mapping are still exported from the overlay and the
    vehicle layer alone on the stock unit files, with no ControlCommand node (the twin connector's pin holds the id file's
    sha256, and no CAN signal maps to ControlCommand), and every export that loads the layer is named here, in order.
    From Phase 2 the vehicle layer follows the overlay (design decision g), and the ctl layer comes between them. Since
    Phase 8's WP3b the two new run types' id and json exports follow carla's, each with its own layer."""
    ids = _yaml_as_json(baseline["out"] / "vss-ids.vspec")
    manifest = json.loads((baseline["out"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["vss_tools"]["overlays"] == ["overlay.vspec", "vehicle-sigsim.vspec"]
    cmds = manifest["commands"]
    assert len(cmds) == 11              # id, json, stock; the ctl layer's id and json; carla's, planning-sim's, carla-autoware's
    for c in cmds[:3]:
        assert not any(s in c for s in ("overlay-ctl", "units-project", "quantities-project")), c
    for c in cmds[:2]:                                                   # the id and json exports, in that order
        assert "-l overlay.vspec -l vehicle-sigsim.vspec " in c, c
    assert " -l " not in cmds[2]                                         # the stock tree has no layer at all
    units = "-u <v6.0>/spec/units.yaml -u units-project.yaml -q <v6.0>/spec/quantities.yaml -q quantities-project.yaml "
    layers = [l for rt in ("sigsim", "carla") + P8_RUN_TYPES for l in ("vehicle-%s.vspec" % rt,) * 2]
    for c, kind, layer in zip(cmds[3:], ("export id ", "export json ") * 4, layers, strict=True):
        assert c.startswith("vspec " + kind) and units in c and "-l overlay.vspec -l overlay-ctl.vspec -l %s " % layer in c, c
    assert not [p for p in ids if p.startswith("Vehicle.DualVm.ControlCommand")]
    assert "Vehicle.DualVm.ControlCommand" not in ids
    broker = gen.json_nodes(json.loads((baseline["out"] / "vss-databroker.json").read_text(encoding="utf-8")))
    assert broker["Vehicle.DualVm.ControlCommand"]["type"] == "branch"
    assert len([p for p in broker if p.startswith("Vehicle.DualVm.ControlCommand.")]) == 10


@NEEDS_VENV
def test_the_vehicle_layer_sets_the_wheelbase_default_in_both_json_files_and_moves_no_uid(baseline):
    out = baseline["out"]
    want = _sigsim_l(_profiles())
    text = (out / "vehicle-sigsim.vspec").read_text(encoding="utf-8")
    assert text == gen.render_vehicle_layer(gen.vehicle_layer(_profiles()))
    for name in ("vss-can-mapping.json", "vss-databroker.json"):
        node = gen.json_nodes(json.loads((out / name).read_text(encoding="utf-8")))["Vehicle.Chassis.Wheelbase"]
        assert (node["type"], node["datatype"], node["unit"], node["default"]) == ("attribute", "uint16", "mm", want), name
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["vehicle_layer"]["default"] == want and manifest["vehicle_layer"]["file"] == "vehicle-sigsim.vspec"
    assert manifest["vehicle_layer"]["profile_id"] == baseline["mod"].LIVE_DEFAULT_PROFILE["sigsim"]
    assert manifest["outputs"]["vehicle-sigsim.vspec"]["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    # The layer moves no staticUID: the id output carries no default, so it is what the overlay alone gives
    # (the stock comparison in the run, and the committed baseline, which this run left unchanged).
    assert "default" not in _yaml_as_json(out / "vss-ids.vspec")["Vehicle.Chassis.Wheelbase"]
    assert "uid-baseline.txt: %d node(s), unchanged" % len(gen.parse_baseline(UID_BASELINE.read_text(encoding="utf-8"))[1]) \
        in baseline["stdout"]
    _committed_baseline_is_untouched()


_LAYER_MOVES_A_UID = r'''
_render = g.render_vehicle_layer
g.render_vehicle_layer = lambda layer: _render(layer) + "  min: 1\n"
'''
_LAYER_DEFAULT_LOST = r'''
import json
def tamper(cwd):
    p = cwd / "vss-can-mapping.json"
    tree = json.loads(p.read_text())
    tree["Vehicle"]["children"]["Chassis"]["children"]["Wheelbase"]["default"] = 0
    p.write_text(json.dumps(tree, indent=2))
after("json export", tamper)
'''


@NEEDS_VENV
@pytest.mark.parametrize("patch, expected", [
    (_LAYER_MOVES_A_UID, "Vehicle.Chassis.Wheelbase: the vehicle layer vehicle-sigsim.vspec moved its staticUID from the stock tree's"),
    (_LAYER_DEFAULT_LOST, "Vehicle.Chassis.Wheelbase: default 0 in the mapping JSON, the vehicle layer vehicle-sigsim.vspec sets"),
])
def test_a_vehicle_layer_that_moves_a_uid_or_loses_its_default_is_refused_end_to_end(baseline, tmp_path, patch, expected):
    """The wiring of vehicle_layer_problems(): a layer that restates a staticUID input (min) on its node, and a
    mapping JSON whose Wheelbase default vss-tools did not carry (tampered inside the run). The refusal names the
    layer, not only the stock comparison."""
    r = _run_patched(patch, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the generated catalogue fails its checks" in r.stderr and expected in r.stderr, r.stderr
    assert not (tmp_path / "out").exists()
    _committed_baseline_is_untouched()


# ============================================================ generation: the run-type layers and the freeze (Phase 7 WP2)

@NEEDS_VENV
def test_the_freeze_leaves_every_sigsim_output_byte_for_byte(baseline):
    """Spec 2.6: the freeze and the carla layer move none of the files the sigsim run, the stack and the guest's
    contract read. vss_contract.h carries the digest, so it also holds the digest's place; the committed baseline is
    checked by the UID tests. Since Phase 8's WP1b the databroker catalogue also serves the ControlCommand branch (spec-2
    2.2): with that branch taken out and the rest dumped as generate.py dumps it, it is the base tree's byte for byte."""
    out = baseline["out"]

    def content(name):
        data = (out / name).read_bytes()
        if name == "vss-databroker.json":
            tree = json.loads(data.decode("utf-8"))
            assert tree["Vehicle"]["children"]["DualVm"]["children"].pop("ControlCommand")["type"] == "branch"
            data = json.dumps(tree, indent=2, sort_keys=True).encode("utf-8")
        return data

    got = {name: hashlib.sha256(content(name)).hexdigest() for name in BASE_SIGSIM_SHA256}
    assert got == BASE_SIGSIM_SHA256
    assert baseline["mod"].CATALOG_DIGEST == gen.parse_baseline(UID_BASELINE.read_text(encoding="utf-8"))[0]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name, sha in BASE_SIGSIM_SHA256.items():
        want = hashlib.sha256((out / name).read_bytes()).hexdigest() if name == "vss-databroker.json" else sha
        assert manifest["outputs"][name]["sha256"] == want, name


@NEEDS_VENV
def test_the_two_run_types_leave_every_sigsim_and_carla_output_and_both_kind_2_files_byte_for_byte(baseline):
    """Spec-2 2.2 (Phase 8 WP3b): the two new run types and profiles 4 and 5 move none of the files the sigsim and carla
    runs, the stack, the guest's kind 4 contract and the kind 2 contract read: each is what this package's base tree
    generated, byte for byte, the databroker catalogues whole (BASE_P8_SHA256; the manifest records the same),
    and the kind 4 digest is the committed baseline's."""
    out = baseline["out"]
    assert {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in BASE_P8_SHA256} == BASE_P8_SHA256
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert {name: manifest["outputs"][name]["sha256"] for name in BASE_P8_SHA256} == BASE_P8_SHA256
    assert baseline["mod"].CATALOG_DIGEST == gen.parse_baseline(UID_BASELINE.read_text(encoding="utf-8"))[0]
    assert manifest["kind4"]["catalog_digest"] == "0x%08X" % baseline["mod"].CATALOG_DIGEST


@NEEDS_VENV
def test_the_planning_sim_and_carla_autoware_layers_and_catalogues_are_generated(baseline):
    """Spec-2 2.1 and 2.2: each new run type's layer file is its rendered layer, its databroker catalogue the sigsim one
    but for the Wheelbase default (the run type's live-default L) and carries no dbc2vss; the manifest's vehicle_layers and
    databroker_catalogues name both, with the same keys as the others, and outputs covers the four files."""
    out, doc = baseline["out"], _profiles()
    sigsim = json.loads((out / "vss-databroker.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for rt, layer_file in zip(P8_RUN_TYPES, P8_LAYERS, strict=True):
        want = _live_l(doc, rt)
        text = (out / layer_file).read_text(encoding="utf-8")
        assert text == gen.render_vehicle_layer(gen.vehicle_layer(doc, rt)) and "  default: %d\n" % want in text, rt
        raw = (out / P8_CATALOGUES[rt]).read_bytes()
        tree = json.loads(raw.decode("utf-8"))
        node = gen.json_nodes(tree)["Vehicle.Chassis.Wheelbase"]
        assert (node["type"], node["datatype"], node["unit"], node["default"]) == ("attribute", "uint16", "mm", want), rt
        like = copy.deepcopy(sigsim)
        gen.json_nodes(like)["Vehicle.Chassis.Wheelbase"]["default"] = want     # json_nodes gives the tree's own dicts
        assert tree == like, "the %s catalogue is the sigsim one but for the Wheelbase default" % rt
        assert b"dbc2vss" not in raw and raw == json.dumps(tree, indent=2, sort_keys=True).encode("utf-8")
        assert manifest["vehicle_layers"][rt] == {k: gen.vehicle_layer(doc, rt)[k] for k in LAYER_KEYS}
        assert manifest["databroker_catalogues"][rt] == P8_CATALOGUES[rt]
        for name in (layer_file, P8_CATALOGUES[rt]):
            data = (out / name).read_bytes()
            assert manifest["outputs"][name] == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}, name
    assert manifest["vehicle_layers"]["planning-sim"]["default"] != manifest["vehicle_layers"]["carla-autoware"]["default"]


@NEEDS_VENV
def test_profile_4_is_compiled_into_the_generated_tables_and_profile_5_is_python_only(baseline):
    """Spec-2 2.2: vss_profiles.h gains profile 4's row and no profile 5 row (make ctl's row-4 guard reads the first, and a
    guest built from this generation answers profile 5 with reason 8); vss_contract.py lists both, each equal to its
    profiles.toml row, with both run types' live defaults, profile 4's summed rows at the planning-sim skew, both margins
    kept, and the two envelopes with their skew row and stand-in list; 0 is the one reserved id left."""
    mod, doc, out = baseline["mod"], _profiles(), baseline["out"]
    assert mod.COMPILED_PROFILE_IDS == (1, 2, 3, 4) and mod.RESERVED_PROFILE_IDS == (0,)
    assert mod.LIVE_DEFAULT_PROFILE == {"sigsim": 1, "carla": 3, "planning-sim": 4, "carla-autoware": 5}
    rows = {r["id"]: r for r in mod.PROFILES}
    assert sorted(rows) == [1, 2, 3, 4, 5]
    for pid in (4, 5):
        p = _p(doc, pid)
        assert all(rows[pid][k] == p[k] for k in ("l_mm", "v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "tol26", "v_tol")), pid
        assert rows[pid]["compiled"] is p["compiled"] and rows[pid]["stand_in"] == () and rows[pid]["envelope"] == p["envelope"]
    assert rows[4]["ay26_max"] is None and rows[5]["ay26_max"] == _p(doc, 5)["ay26_max"]
    macros = _c_macros(out / "vss_profiles.h")
    assert macros["VSS_PROFILE_COUNT"] == "4u" and macros["VSS_PROFILE_IDS"] == '"1 2 3 4"'
    text = (out / "vss_profiles.h").read_text(encoding="utf-8")
    assert text.count("X(4u, %du, " % _p(doc, 4)["l_mm"]) == 1 and "X(5u," not in text
    assert mod.ENVELOPES["planning-sim"]["skew_ms"] == 25 and tuple(mod.ENVELOPES["carla010"]["stand_in"]) == CARLA010_STAND_IN
    assert mod.RULE26_BUDGET[4]["skew_ms"] == 25 and mod.RULE26_BUDGET[4]["margin"] >= mod.ENVELOPES["planning-sim"]["margin_target"]
    assert mod.RULE26_BUDGET[5]["margin"] >= mod.ENVELOPES["carla010"]["margin_target"]


@NEEDS_VENV
def test_the_kind_2_contract_leaves_vss_contract_py_and_vss_profiles_h_byte_for_byte(baseline):
    """Spec-2 2.2 (Phase 8 WP1b): vss_contract.py and vss_profiles.h are, byte for byte, what the last kind 4 profile
    change wrote, beside the kind 2 contract (BASE_KIND4_SHA256: since Phase 8's WP3b its profiles 4 and 5; the manifest
    records the same)."""
    out = baseline["out"]
    assert {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in BASE_KIND4_SHA256} == BASE_KIND4_SHA256
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert {name: manifest["outputs"][name]["sha256"] for name in BASE_KIND4_SHA256} == BASE_KIND4_SHA256


@NEEDS_VENV
def test_the_carla_layer_and_its_databroker_catalogue_are_generated(baseline):
    out, doc = baseline["out"], _profiles()
    want = _live_l(doc, "carla")
    text = (out / "vehicle-carla.vspec").read_text(encoding="utf-8")
    assert text == gen.render_vehicle_layer(gen.vehicle_layer(doc, "carla")) and "  default: %d\n" % want in text
    sigsim = json.loads((out / "vss-databroker.json").read_text(encoding="utf-8"))
    carla = json.loads((out / "vss-databroker-carla.json").read_text(encoding="utf-8"))
    node = gen.json_nodes(carla)["Vehicle.Chassis.Wheelbase"]
    assert (node["type"], node["datatype"], node["unit"], node["default"]) == ("attribute", "uint16", "mm", want)
    assert gen.json_nodes(sigsim)["Vehicle.Chassis.Wheelbase"]["default"] == _live_l(doc, "sigsim") != want
    gen.json_nodes(sigsim)["Vehicle.Chassis.Wheelbase"]["default"] = want     # json_nodes gives the tree's own dicts
    assert carla == sigsim, "the carla catalogue is the sigsim one but for the Wheelbase default"
    raw = (out / "vss-databroker-carla.json").read_bytes()
    assert b"dbc2vss" not in raw and raw == json.dumps(carla, indent=2, sort_keys=True).encode("utf-8")


@NEEDS_VENV
def test_the_manifest_keeps_its_vehicle_layer_and_names_each_run_types_layer_and_catalogue(baseline):
    """Spec 2.6: `vehicle_layer` stays the sigsim layer's object with today's keys (sdv/stack/stack.py reads it);
    `vehicle_layers` adds the carla layer's with the same keys, `databroker_catalogues` names both catalogues, and
    `outputs` covers the two new files. Since Phase 8's WP3b both also name the two new run types (spec-2 2.2), and
    nothing else."""
    out, doc = baseline["out"], _profiles()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    sigsim, carla = gen.vehicle_layer(doc, "sigsim"), gen.vehicle_layer(doc, "carla")
    assert manifest["vehicle_layer"] == {k: sigsim[k] for k in LAYER_KEYS}
    assert manifest["vehicle_layer"]["file"] == "vehicle-sigsim.vspec" and manifest["vehicle_layer"]["profile_id"] == 1
    assert manifest["vehicle_layers"] == dict({"sigsim": manifest["vehicle_layer"], "carla": {k: carla[k] for k in LAYER_KEYS}},
                                              **{rt: {k: gen.vehicle_layer(doc, rt)[k] for k in LAYER_KEYS} for rt in P8_RUN_TYPES})
    assert manifest["vehicle_layers"]["carla"]["default"] == _live_l(doc, "carla")
    assert manifest["databroker_catalogues"] == dict({"sigsim": "vss-databroker.json", "carla": "vss-databroker-carla.json"},
                                                     **P8_CATALOGUES)
    for name in ("vehicle-carla.vspec", "vss-databroker-carla.json"):
        data = (out / name).read_bytes()
        assert manifest["outputs"][name] == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}, name
    assert manifest["vss_tools"]["overlays"] == ["overlay.vspec", "vehicle-sigsim.vspec"]
    assert "every profile's rule-26 budget keeps its envelope's margin_target over tol" in manifest["checks"]


@NEEDS_VENV
def test_profile_3_is_compiled_into_the_generated_tables(baseline):
    """The freeze reaches both constant files: profile 3 in vss_profiles.h's table (the guest's) and in
    COMPILED_PROFILE_IDS, with its a_y bound; its row equal to profiles.toml's. Since Phase 8's WP3b profile 4 joins both
    after it (test_profile_4_is_compiled_into_the_generated_tables_and_profile_5_is_python_only), so this holds profile 3's
    place: in both, and run type carla's live default."""
    mod, doc = baseline["mod"], _profiles()
    assert mod.COMPILED_PROFILE_IDS[:3] == (1, 2, 3) and mod.LIVE_DEFAULT_PROFILE["carla"] == 3
    row = next(r for r in mod.PROFILES if r["id"] == 3)
    p = _p(doc, 3)
    assert row["compiled"] is True and row["stand_in"] == () and row["ay26_max"] == p["ay26_max"]
    assert all(row[k] == p[k] for k in ("l_mm", "v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "tol26", "v_tol"))
    macros = _c_macros(baseline["out"] / "vss_profiles.h")
    assert macros["VSS_PROFILE_IDS"].strip('"').split()[:3] == ["1", "2", "3"]
    assert "X(3u, %du, " % p["l_mm"] in (baseline["out"] / "vss_profiles.h").read_text(encoding="utf-8")
    assert mod.RULE26_BUDGET[3]["margin"] >= mod.ENVELOPES["carla"]["margin_target"]


_CARLA_LAYER_MOVES_A_UID = r'''
_render = g.render_vehicle_layer
g.render_vehicle_layer = lambda layer: _render(layer) + ("  min: 1\n" if layer["run_type"] == "carla" else "")
'''
_CARLA_DEFAULT_LOST = r'''
import json
def tamper(cwd):
    p = cwd / "vss-can-mapping-carla.json"
    tree = json.loads(p.read_text())
    tree["Vehicle"]["children"]["Chassis"]["children"]["Wheelbase"]["default"] = 0
    p.write_text(json.dumps(tree, indent=2))
after("carla json export", tamper)
'''


@NEEDS_VENV
@pytest.mark.parametrize("patch, expected", [
    (_CARLA_LAYER_MOVES_A_UID, "Vehicle.Chassis.Wheelbase: the vehicle layer vehicle-carla.vspec moved its staticUID from the stock tree's"),
    (_CARLA_DEFAULT_LOST, "Vehicle.Chassis.Wheelbase: default 0 in the mapping JSON, the vehicle layer vehicle-carla.vspec sets"),
])
def test_a_carla_layer_that_moves_a_uid_or_loses_its_default_is_refused_end_to_end(baseline, tmp_path, patch, expected):
    """The carla layer is checked by the same vehicle_layer_problems() on its own exports (spec 5 item 3), with the
    sigsim layer untouched: the refusal names the carla layer."""
    r = _run_patched(patch, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the generated catalogue fails its checks" in r.stderr and expected in r.stderr, r.stderr
    assert "vehicle-sigsim.vspec" not in r.stderr
    assert not (tmp_path / "out").exists()
    _committed_baseline_is_untouched()


_NEW_LAYER_MOVES_A_UID = r'''
_render = g.render_vehicle_layer
g.render_vehicle_layer = lambda layer: _render(layer) + ("  min: 1\n" if layer["run_type"] == RT else "")
'''
_NEW_LAYER_DEFAULT_LOST = r'''
import json
def tamper(cwd):
    p = cwd / ("vss-can-mapping-%s.json" % RT)
    tree = json.loads(p.read_text())
    tree["Vehicle"]["children"]["Chassis"]["children"]["Wheelbase"]["default"] = 0
    p.write_text(json.dumps(tree, indent=2))
after("%s json export" % RT, tamper)
'''


@NEEDS_VENV
@pytest.mark.parametrize("rt", ["planning-sim", "carla-autoware"])
@pytest.mark.parametrize("patch, expected", [
    (_NEW_LAYER_MOVES_A_UID, "Vehicle.Chassis.Wheelbase: the vehicle layer vehicle-%s.vspec moved its staticUID from the stock tree's"),
    (_NEW_LAYER_DEFAULT_LOST, "Vehicle.Chassis.Wheelbase: default 0 in the mapping JSON, the vehicle layer vehicle-%s.vspec sets"),
], ids=["moves-a-uid", "default-lost"])
def test_a_new_run_types_layer_that_moves_a_uid_or_loses_its_default_is_refused_end_to_end(baseline, tmp_path, rt, patch, expected):
    """Spec-2 section 4 item 1: each new run type's layer is checked by vehicle_layer_problems() on its own exports, as the
    carla layer is; the refusal names that layer and neither the sigsim nor the carla one."""
    r = _run_patched("RT = %r\n" % rt + patch, "--out", tmp_path / "out", "--no-previous")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the generated catalogue fails its checks" in r.stderr and expected % rt in r.stderr, r.stderr
    assert "vehicle-sigsim.vspec" not in r.stderr and "vehicle-carla.vspec" not in r.stderr
    assert not (tmp_path / "out").exists()
    _committed_baseline_is_untouched()


@NEEDS_VENV
def test_a_generation_is_refused_while_the_carla_live_default_holds_a_stand_in_l(baseline, tmp_path):
    text = (VSSDIR / "profiles.toml").read_text(encoding="utf-8")
    head, sep, tail = text.partition("[[profiles]]\nid = 3\n")
    assert sep and tail.count("compiled = true\n") >= 1 and tail.count("stand_in = []\n") >= 1
    tail = tail.replace("compiled = true\n", "compiled = false\n", 1).replace("stand_in = []\n", 'stand_in = ["l_mm"]\n', 1)
    profiles = tmp_path / "profiles.toml"
    profiles.write_text(head + sep + tail, encoding="utf-8", newline="\n")
    r = _run("--profiles", profiles, "--archive", CACHE / gen.ARCHIVE_NAME, "--cache", tmp_path / "cache", "--out", tmp_path / "out",
             "--no-previous")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "the vehicle layer: profile 3's l_mm is a stand-in" in r.stderr
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "cache").exists()


@NEEDS_VENV
def test_vehicle_speed_is_never_negative_and_the_signed_velocity_is_in_m_per_s(baseline):
    ids = _yaml_as_json(baseline["out"] / "vss-ids.vspec")
    speed, motion = ids["Vehicle.Speed"], ids["Vehicle.DualVm.Motion.LongitudinalVelocity"]
    assert (speed["type"], speed["datatype"], speed["unit"], speed["min"]) == ("sensor", "float", "km/h", 0)
    assert "max" not in speed
    assert (motion["type"], motion["datatype"], motion["unit"]) == ("sensor", "float", "m/s")
    assert "min" not in motion and "max" not in motion        # signed: a float with no lower bound
    broker = gen.json_nodes(json.loads((baseline["out"] / "vss-databroker.json").read_text(encoding="utf-8")))
    assert broker["Vehicle.Speed"]["min"] == 0 and broker["Vehicle.Speed"]["unit"] == "km/h"
    assert broker["Vehicle.DualVm.Motion.LongitudinalVelocity"]["unit"] == "m/s"
    mapping = gen.json_nodes(json.loads((baseline["out"] / "vss-can-mapping.json").read_text(encoding="utf-8")))
    assert mapping["Vehicle.Speed"]["dbc2vss"] == {"signal": "LongVel", "interval_ms": 0, "on_change": False,
                                                   "transform": {"math": "abs(x) * 3.6"}}


@NEEDS_VENV
def test_the_monitor_branch_is_generated_and_is_in_no_allowlist_file(baseline):
    ids = _yaml_as_json(baseline["out"] / "vss-ids.vspec")
    assert ids["Vehicle.DualVm.Monitor"]["type"] == "branch"
    for claim in ("VssClaim", "CtlClaim"):
        assert ids["Vehicle.DualVm.Monitor.%s" % claim]["type"] == "branch"
        assert ids["Vehicle.DualVm.Monitor.%s.Reason" % claim]["max"] == 27
    allowlists = [p for root in (REPO / "sdv", REPO / "scripts", REPO / "tests", baseline["out"])
                  for p in root.rglob("*") if p.is_file() and "allowlist" in p.name.lower()]
    for p in allowlists:
        assert "dualvm.monitor" not in p.read_text(encoding="utf-8", errors="replace").lower(), p
    assert not any("allowlist" in n for n in gen.OUT_FILES)


@NEEDS_VENV
def test_the_databroker_json_is_the_mapping_json_without_dbc2vss_plus_the_control_command_branch(baseline):
    """Was test_the_databroker_json_is_the_mapping_json_without_dbc2vss: since Phase 8's WP1b the databroker catalogue
    also serves the ControlCommand branch, which the CAN mapping does not carry (spec-2 2.2); the rest is unchanged."""
    mapping = json.loads((baseline["out"] / "vss-can-mapping.json").read_text(encoding="utf-8"))
    broker = json.loads((baseline["out"] / "vss-databroker.json").read_text(encoding="utf-8"))
    ctl = broker["Vehicle"]["children"]["DualVm"]["children"].pop("ControlCommand")
    assert ctl["type"] == "branch" and "dbc2vss" not in json.dumps(ctl)
    assert gen.strip_key(mapping, "dbc2vss") == broker
    nodes = gen.json_nodes(mapping)
    assert sorted(p for p, n in nodes.items() if "dbc2vss" in n) == sorted(MAPPED)
    # The one overlay entry on an instantiated path reaches Row1 only.
    assert "dbc2vss" not in nodes["Vehicle.Chassis.Axle.Row2.SteeringAngle"]
    assert nodes["Vehicle.DualVm.AppState.HardBrakeHazard.State"]["allowed"] == ["starting", "running", "degraded", "stopping"]


@NEEDS_VENV
def test_case_insensitive_uids_and_every_output_hash_are_recorded(baseline):
    out = baseline["out"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["vss_tools"]["uid_case_sensitive"] is False and manifest["vss_tools"]["version"] == "6.0.0"
    assert baseline["mod"].UID_CASE_SENSITIVE is False
    assert _c_macros(out / "vss_contract.h")["VSS_UID_CASE_SENSITIVE"] == "0"
    for name, rec in manifest["outputs"].items():
        data = (out / name).read_bytes()
        assert rec == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    assert sorted(manifest["outputs"]) == sorted(n for n in gen.OUT_FILES if n != "manifest.json")
    text = (out / "manifest.json").read_text(encoding="utf-8")
    assert "/home/" not in text and "/mnt/" not in text and str(Path.home()) not in text
    assert manifest["kind4"]["kind4_units_in_stock_units_yaml"] == list(gen.KIND4_UNITS)


@NEEDS_VENV
def test_the_dbc_units_equal_the_generated_slot_units(baseline):
    mod = baseline["mod"]
    assert mod.SLOT_UNITS == ("m/s", "m/s^2", "degrees", "degrees/s", None)
    assert mod.SLOT_DBC_UNITS == mod.SLOT_UNITS
    assert mod.SLOT_DATATYPES == ("float", "float", "float", "float", "int8")
    assert mod.SLOT_DBC_SIGNALS == SLOT_SIGNALS


C_PROBE = r"""
#include <stdint.h>
#include <stdio.h>
#include "vss_contract.h"
#include "vss_profiles.h"

static uint32_t fnv1(const uint8_t *p, unsigned n)
{
    uint32_t h = 0x811C9DC5u;
    unsigned i;
    for (i = 0; i < n; i++) { h *= 0x01000193u; h ^= p[i]; }
    return h;
}

#define ROW(id, l, vm, am, dm, lo, hi, ay, tol, vt) \
    printf("profile %u %u %a %a %a %a %a %a %a %a\n", (unsigned)(id), (unsigned)(l), vm, am, dm, lo, hi, ay, tol, vt);

int main(void)
{
    const uint32_t u[5] = { VSS_UID_SLOT0, VSS_UID_SLOT1, VSS_UID_SLOT2, VSS_UID_SLOT3, VSS_UID_SLOT4 };
    uint8_t b[20];
    int i;
    for (i = 0; i < 5; i++) {
        b[4 * i + 0] = (uint8_t)((u[i] >> 0) & 0xFFu);
        b[4 * i + 1] = (uint8_t)((u[i] >> 8) & 0xFFu);
        b[4 * i + 2] = (uint8_t)((u[i] >> 16) & 0xFFu);
        b[4 * i + 3] = (uint8_t)((u[i] >> 24) & 0xFFu);
    }
    printf("digest %08X %08X\n", (unsigned)fnv1(b, 20), (unsigned)VSS_CATALOG_DIGEST);
    printf("age %u case %d version %s commit %s\n", (unsigned)VSS_AGE_MAX_MS, VSS_UID_CASE_SENSITIVE, VSS_CATALOG_VERSION, VSS_CATALOG_COMMIT);
    printf("consts %a %a %a\n", VSS_DEG_PER_RAD, VSS_RAD_PER_DEG, VSS_M_PER_MM);
    VSS_PROFILE_TABLE(ROW)
    printf("ids %s count %u\n", VSS_PROFILE_IDS, (unsigned)VSS_PROFILE_COUNT);
    return 0;
}
"""


@NEEDS_VENV
def test_both_c_headers_compile_under_werror_and_agree_with_python_bit_for_bit(baseline, tmp_path):
    gcc = shutil.which("gcc")
    if gcc is None or sys.platform == "win32":
        pytest.skip("needs gcc (WSL Ubuntu-24.04)")
    flags = ["-std=gnu99", "-Wall", "-Wextra", "-Werror", "-I", str(baseline["out"])]
    unused = tmp_path / "unused.c"
    unused.write_text('#include "vss_contract.h"\n#include "vss_profiles.h"\nint main(void) { return 0; }\n', encoding="utf-8")
    subprocess.run([gcc] + flags + ["-o", str(tmp_path / "unused"), str(unused)], check=True, capture_output=True)
    probe = tmp_path / "probe.c"
    probe.write_text(C_PROBE, encoding="utf-8")
    subprocess.run([gcc] + flags + ["-o", str(tmp_path / "probe"), str(probe)], check=True, capture_output=True)
    lines = subprocess.run([str(tmp_path / "probe")], check=True, capture_output=True, text=True).stdout.splitlines()
    mod = baseline["mod"]
    assert lines[0] == "digest %08X %08X" % (mod.CATALOG_DIGEST, mod.CATALOG_DIGEST)
    assert lines[1] == "age %d case 0 version %s commit %s" % (mod.AGE_MAX_MS, mod.VSS_VERSION, mod.VSS_COMMIT)
    assert [float.fromhex(x) for x in lines[2].split()[1:]] == [mod.DEG_PER_RAD, mod.RAD_PER_DEG, mod.M_PER_MM]
    assert mod.DEG_PER_RAD == 180 / 3.141592653589793 and mod.M_PER_MM == 1 / 1000
    rows = [ln.split()[1:] for ln in lines if ln.startswith("profile ")]
    compiled = [p for p in mod.PROFILES if p["compiled"]]
    assert [p["id"] for p in compiled] == list(mod.COMPILED_PROFILE_IDS)
    assert len(rows) == len(compiled)
    for row, p in zip(rows, compiled):
        assert (int(row[0]), int(row[1])) == (p["id"], p["l_mm"])
        want = [p["v_max"], p["a_max"], p["delta_max"], p["v26_lo"], p["v26_hi"],
                0.0 if p["ay26_max"] is None else p["ay26_max"], p["tol26"], p["v_tol"]]
        assert [float.fromhex(x) for x in row[2:]] == want
    assert lines[-1] == "ids %s count %d" % (" ".join(str(i) for i in mod.COMPILED_PROFILE_IDS), len(compiled))


# ============================================================ confidentiality

def test_no_confidential_literal_in_the_sdv_tree_or_its_output():
    """Third-party names are kept in a local literal file outside the repo and never enter a file of the tree
    or of its output. They are not written here either: the owner holds the list, and this skips without it."""
    if not LITERALS.is_file():
        pytest.skip("no local literal list at %s (set SDV_CONFIDENTIAL_LITERALS); the owner holds the names" % LITERALS)
    literals = [ln.strip().lower() for ln in LITERALS.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
    assert literals, "the literal list is empty"
    roots = [REPO / "sdv", REPO / "sdv-out"] + sorted(HERE.glob("test_sdv_*.py"))
    files = [f for r in roots if r.exists() for f in ([r] if r.is_file() else r.rglob("*")) if f.is_file()]
    assert files
    hits = []
    for f in files:
        text = f.read_bytes().decode("utf-8", errors="replace").lower()
        hits += ["%s: literal #%d" % (f.relative_to(REPO), i) for i, lit in enumerate(literals, 1) if lit in text]
    assert not hits, hits
