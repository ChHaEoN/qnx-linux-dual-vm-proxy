#!/usr/bin/env python3
"""generate.py -- generate the VSS contract of the SDV slice from pinned inputs.

    usage: ~/sdv-venv/bin/python sdv/vss/generate.py [--out DIR] [--cache DIR] [--venv DIR]
               [--archive FILE] [--overlay FILE] [--profiles FILE] [--dbc FILE]
               [--overlay-ctl FILE] [--units-project FILE] [--quantities-project FILE] [--profiles-ctl FILE]
               [--project-branch NAME] [--previous-ids FILE | --no-previous]
               [--uid-baseline FILE] [--accept-uid-change]

Run it in WSL Ubuntu-24.04, with the venv built from requirements.lock (README.md). Exit 0 when
every output was written; 1 on any refusal, with the reason on stderr and nothing in --out touched;
2 on a usage error.

INPUTS, each pinned or in this directory:
  - the VSS v6.0 source-tag archive (GitHub's archive of the tag, never a release attachment: the
    attachments include a .fidl file). Fetched once into --cache, then checked against its sha256
    and against the commit its pax header records; only its spec/ tree is extracted, and units.yaml
    and quantities.yaml are checked against their own sha256.
  - vss-tools 6.0.0 in --venv, whose installed versions must equal requirements.lock's pins.
  - overlay.vspec (the one overlay), profiles.toml (the kind 4 profile table and the pipeline
    constants) and slice.dbc (the periods, factors and units of the five kind 4 signals).
  - overlay-ctl.vspec (the ControlCommand layer), units-project.yaml and quantities-project.yaml (the
    units rad and m/s^3 and the quantity jerk it needs, D5) and profiles-ctl.toml (the kind 2 profile
    table and the constants of its rules): the kind 2 contract's inputs (Phase 8 WP1b).
  - uid-baseline.txt (--uid-baseline), the committed staticUIDs of the five slots and of every node
    of the project branch, with the catalogue digest. It is the one thing a fresh checkout has to
    compare a generation against, because no generated file is committed. Only --accept-uid-change
    writes it, and only when a generation differs from it or it is missing.

OUTPUTS, into --out (default <repo>/sdv-out/gen, ignored by git), all or nothing:
  vss-ids.vspec          the id exporter's output: every node with its staticUID (without the ControlCommand layer)
  vss-can-mapping.json   the JSON catalogue with the dbc2vss mapping, for the CAN provider (without that layer)
  vss-databroker.json    the same catalogue with the ControlCommand layer and without dbc2vss, for the
                         databroker's --vss (run type sigsim)
  vss-databroker-carla.json  the databroker catalogue exported with run type carla's vehicle layer instead
  vss-databroker-planning-sim.json, vss-databroker-carla-autoware.json
                         likewise with run type planning-sim's and carla-autoware's (Phase 8 WP3b)
  vehicle-sigsim.vspec   the per-vehicle layers, one per run type with a live default (VEHICLE_RUN_TYPES),
  vehicle-carla.vspec    generated from profiles.toml and loaded after the overlay: Vehicle.Chassis.Wheelbase's
  vehicle-planning-sim.vspec, vehicle-carla-autoware.vspec
                         catalogue default = the L of that run type's live-default profile (wire spec 5.6,
                         14.5; Phase 2 design decision g; Phase 7 WP2; Phase 8 WP3b). The first three files and the
                         manifest's vehicle_layer carry the sigsim layer, which the stack reads
  vss_contract.h         the monitor's contract: slot UIDs, catalogue digest, AGE_MAX, constants
  vss_profiles.h         the compiled profiles as an X-macro table
  vss_contract.py        the same for Python, plus every value the monitor never uses and every
                         constant derived from them
  vss_ctl.h              the kind 2 contract for the monitor's ctl build: the seven kind 2 slot UIDs, their
                         digest, the constants of rules 11 and 17-19, the compiled kind 2 profiles as an X-macro table
  vss_ctl.py             the same for Python (sdv/ctl loads it by path), with every kind 2 profile
  manifest.json          inputs, pins, options, checks and each output's sha256
Every output is a pure function of the inputs: no timestamp, no absolute path, no run state, so two
runs are byte-identical.

THE KIND 2 CONTRACT (Phase 8 WP1b; the Phase 8 specification, 2.2-2.4). The ControlCommand layer joins
the exports that need it and no other: an id export and a JSON export of each run type, with
overlay-ctl.vspec between overlay.vspec and the vehicle layer and units-project.yaml and
quantities-project.yaml after the stock unit and quantity files. Their JSON exports are the databroker
catalogues, so every catalogue serves the ControlCommand nodes; vss-ids.vspec and vss-can-mapping.json
stay the exports without the layer, byte for byte as before (the twin connector's image pins the id
file's sha256, and no CAN signal maps to ControlCommand). The layer may add its own entries under
Vehicle.<branch>.ControlCommand and nothing else, move no other node, carry no dbc2vss block, and must
reach the catalogue as written. The seven kind 2 slot UIDs are read from the id export with the layer, as
kind 4's five are from vss-ids.vspec; VSS_CTL_DIGEST is FNV-1 32 over them as u32 little-endian in slot
order (the catalogue digest's construction), refused when all zeros or all ones. uid-baseline.txt lists the
layer's nodes beside the project branch's others. No kind 4 output and not the kind 4 digest depends on any
kind 2 input.

THE CATALOGUE DIGEST (the kind 4 wire specification, section 4.2). Each kind 4 slot's staticUID
("0x%08X" in the id output, parsed exactly), serialised as u32 little-endian in slot order 0..4 (20
bytes), hashed with FNV-1 32 (offset basis 0x811C9DC5, prime 0x01000193, multiply then xor), the
function vss-tools itself uses for staticUIDs. UIDs are case-insensitive (vss-tools' default; the
manifest and both constant files record it). 0x00000000 and 0xFFFFFFFF are refused.

REFUSALS (exit 1): an archive whose sha256 or embedded commit differs from the pin; a .fidl file
among the inputs; a venv whose versions differ from the lock; any vss-tools error or warning under
--strict; a malformed staticUID; a slot missing, not a sensor, or of another datatype; a standard
node whose staticUID differs from an overlay-free build of the same tree (Vehicle.Speed excepted,
for its min 0) or an added node outside the project branch; a Vehicle.Speed that is not a sensor,
float, km/h with min 0; an overlay entry that does not reach the catalogue as written; a dbc2vss
signal slice.dbc does not define; a vehicle layer whose run type has no single live-default profile or
whose live-default profile's L is a stand-in (a stand-in delta_max alone keeps the layer, which carries L
only), whose source vehicle has two wheelbases, whose node moved its staticUID or is not an attribute in mm,
or whose default did not reach the JSON, each layer on its own exports; a run type with a live-default
profile and no layer here; a staticUID that changed or disappeared since the previous
generation, and any drift from the committed baseline (a changed, removed or added staticUID, a
moved digest, or no baseline), unless --accept-uid-change; a forbidden digest; a profile-file
invariant (checked before the venv and any vss-tools run; the bounds are constants of this file, and a
profiles.toml that carries an [invariants] table is refused); a derived constant that is undefined; a
rule-26 budget that keeps less than its envelope's margin_target over tol (after the exports: it needs
the slots' DBC signals from the generated mapping); a compiled profile on an envelope that holds a stand-in row, an
envelope's stand_in that names anything but its own rows, a skew_ms row on an envelope that is not a planning-sim one
(SKEW_ROW_ENVELOPES), on one whose budget is not rows-summed, or that is not a positive whole ms, and a profile on a
planning-sim envelope that is the live default of a run type outside SKEW_ROW_RUN_TYPES, or a run type of those whose
live default is on another envelope (Phase 8 WP3b; all with the profile file's invariants); a profile file that is not
TOML. For kind 2: a
profiles-ctl.toml refusal (spec 2.3, listed in the file's own header; checked with profiles.toml's, before
the venv; a number past a double's range is not finite); a ControlCommand layer
that adds anything but its own entries under Vehicle.<branch>.ControlCommand, changes another node,
carries a dbc2vss block, does not reach the catalogue as written, or whose databroker catalogue differs
from the CAN mapping by more than its branch; a kind 2 slot that is missing or not a sensor of the wire's
datatype; a forbidden kind 2 digest.

DOES NOT DEMONSTRATE. That the databroker or the CAN provider load these files, that any value
reaches the QNX guest, or that any limit is right. The digest binds two builds to one catalogue;
it stops an honest mismatch only, never a dishonest writer on the Linux side. Nor that the databroker
serves the ControlCommand nodes or anything writes them, or that a kind 2 limit is right for a run.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

FORMAT = 1

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# --- pins (Phase 0 step 3) --------------------------------------------------------------------------
VSS_TAG = "v6.0"
VSS_VERSION = "6.0"
ARCHIVE_URL = "https://github.com/COVESA/vehicle_signal_specification/archive/refs/tags/v6.0.tar.gz"
ARCHIVE_NAME = "vss-v6.0.tar.gz"
ARCHIVE_SHA256 = "db0d241d9fca1c5ec0abd262f7ebb0b832030fb1b7af4607a96eeb77f3274455"
ARCHIVE_COMMIT = "20c609bf95c73b51d483fb8f81a099d1d5b73066"
ARCHIVE_ROOT = "vehicle_signal_specification-6.0"
UNITS_SHA256 = "f43f6240011f2191d376c24a6ff21429ac7f776da661a1ebc7fb4dcd6a8f0497"
QUANTITIES_SHA256 = "442e8505cab7b94f5c74fb3d81ab2cd89098d31f79090c240c1f40f67d16b944"
VSS_TOOLS_VERSION = "6.0.0"
VSS_TOOLS_WHEEL_SHA256 = "2365642e317633ca4b6e7aad50833d86ef3d13e03c256ed0a13bfb3a3aa3865f"

# --- fixed choices ------------------------------------------------------------------------------------
CASE_SENSITIVE = False          # vss-tools' default; flipping it changes every UID
EXTENDED_ATTRIBUTES = ("dbc2vss",)
DEFAULT_BRANCH = "DualVm"       # the project branch, Vehicle.<name>
SPEED_PATH = "Vehicle.Speed"    # the one standard node whose UID the overlay changes (min 0)

# The five kind 4 slots (wire spec 4.1): path, VSS type and datatype. The datatype is the wire
# encoding (f32 or i8), so another one is a layout change and refused; the unit is emitted as found,
# because the digest binds it.
SLOTS = (
    ("Vehicle.{branch}.Motion.LongitudinalVelocity", "sensor", "float"),
    ("Vehicle.Acceleration.Longitudinal", "sensor", "float"),
    ("Vehicle.Chassis.Axle.Row1.SteeringAngle", "sensor", "float"),
    ("Vehicle.AngularVelocity.Yaw", "sensor", "float"),
    ("Vehicle.Powertrain.Transmission.CurrentGear", "sensor", "int8"),
)
RULE26_SLOTS = (0, 2, 3)        # v, delta, psi_dot: one DBC message, one instant
# Units kind 4 needs from the stock units.yaml (plan 3.3), plus Vehicle.Speed's km/h.
KIND4_UNITS = ("m/s", "m/s^2", "degrees", "degrees/s", "ms", "mm", "km/h")

UID_RE = re.compile(r"^0x[0-9A-F]{8}$")
FORBIDDEN_DIGESTS = (0x00000000, 0xFFFFFFFF)
FNV_OFFSET = 0x811C9DC5
FNV_PRIME = 0x01000193

# The bounds profiles.toml is checked against (kind 4 wire specification 5.4; the reasons are the
# spec's). They are constants of this generator and not settings of the profile file: a file that
# could relax the bounds it is checked against would check nothing, and generate.py refuses a
# profiles.toml that carries an [invariants] table. Changing one is a change to the wire spec.
L_MM_MIN = 1000                 # spec 5.4: catches the VSS Wheelbase default 0, covers cars and light trucks,
L_MM_MAX = 6000                 # and bounds the error term of spec 7.3
DELTA_MAX_LIMIT_DEG = 57.0      # spec 7.2: the polynomial tan covers |x| <= 1.0 rad, and 57 deg = 0.9948 rad;
                                # rule 25 precedes 26, so |delta| <= delta_max <= 57 deg keeps tan inside its domain
PSI_DOT_KIN_ERROR_BOUND = 1.0e-5   # spec 7.3: design bound of the C psi_dot_kin against Python's math, deg/s (with
                                # L >= 1000 mm, |v| <= 20 m/s and delta <= 57 deg the error stays below 2e-6 deg/s)
TOL_OVER_ERROR_MIN = 1.0e5      # spec 5.4: tol26 must exceed that bound by at least this factor
# The envelopes whose rule-26 triple no CAN message carries (the Phase 8 specification, 2.4): Autoware's planning
# simulator publishes velocity, heading rate and steering on one timer, so its envelope's skew_ms row replaces slice.dbc's
# period of the message carrying the triple. On every other envelope that period is the skew, and the row is refused.
SKEW_ROW_ENVELOPES = ("planning-sim",)
# The run types whose rule-26 triple comes from that one timer (the planning simulator's), not from a CAN message: a
# profile on a SKEW_ROW_ENVELOPES envelope may be the live default of these only, and each of these takes its live default
# from such an envelope, so a live_default_for list cannot part the skew row from the run type it describes (Phase 8 WP3b).
SKEW_ROW_RUN_TYPES = ("planning-sim",)
# An envelope's keys that are not rows: what its stand_in list may not name (Phase 8 WP3b). skew_ms stays a row, as the
# specification (2.4) words it.
ENVELOPE_META_KEYS = ("budget", "margin_target", "stand_in", "wheelbase_mm")

# Vehicle.Speed is a magnitude in km/h and never negative: the owner's decision, written into
# overlay.vspec. It is not a kind 4 slot, so the digest does not cover it; the generator does.
SPEED_UNIT = "km/h"
BASELINE_NAME = "uid-baseline.txt"
BASELINE_HEADER = (
    "# uid-baseline.txt -- the committed staticUIDs of the SDV slice's VSS contract (sdv/vss)",
    "#",
    "# Written by `generate.py --accept-uid-change`, never by hand: a hand",
    "# edit that does not match what the generator writes fails the test that regenerates it. Every value",
    "# is a design value computed from the pinned inputs, never a measurement.",
    "#",
    "# WHAT IT IS. generate.py compares every generation with this file and refuses on any drift: a",
    "# staticUID of one of the five kind 4 slots or of any node of the project branch that changed, that",
    "# disappeared or that is new, or a catalogue digest that moved. No generated file is committed, so",
    "# without this file a fresh checkout has nothing to compare against, and an overlay edit that moves",
    "# a slot's staticUID (a unit, min or max on a slot; a renamed branch) would pass and silently change",
    "# the digest that a guest image is built with. The nodes are listed because a new node under",
    "# the project branch is a change of the contract too. `digest` is FNV-1 32 over the five slot UIDs",
    "# in slot order, as u32 little-endian (generate.py holds the definition); each other line is a node",
    "# path and its staticUID (upper-case hex, vss-tools' case-insensitive default).",
    "#",
    "# DOES NOT DEMONSTRATE. That any of these values is right, that a guest image built from them exists,",
    "# or that the databroker accepts them. It records what the pinned inputs produced when the file was",
    "# last written, so that the next change to them is a decision and not an accident.",
)

DEG_PER_RAD = 180.0 / math.pi
RAD_PER_DEG = math.pi / 180.0
M_PER_MM = 1.0 / 1000.0

# The per-vehicle layers (kind 4 wire specification 5.6, 14.5; Phase 2 design decision g). VSS 6.0 ships
# Vehicle.Chassis.Wheelbase with the catalogue default 0, and databroker 0.7.1 serves an attribute's
# catalogue default, so a broker-mode claim bridge would read 0 and refuse to start (a served value that is
# not the profile's L). A layer is generated, never written by hand: one node, the wheelbase's `default:`
# set to the L of the live-default profile of its run type in profiles.toml, loaded after the overlay.
# `default` is not a staticUID input, so no UID moves; vehicle_layer_problems() checks it anyway. A
# databroker serves one Wheelbase, so a catalogue describes one source vehicle: one layer per run type with a
# live default (Phase 7 WP2), each exported into its own databroker catalogue. CATALOGUE_RUN_TYPE's layer is
# the one vss-ids.vspec, vss-can-mapping.json, vss-databroker.json and the manifest's vehicle_layer carry, as
# they did when a generation had one layer (the stack reads them); the others add their layer file and
# databroker catalogue beside them. Phase 8's WP3b adds planning-sim (Autoware's planning simulator, profile 4)
# and carla-autoware (the CARLA 0.10.0 closed loop, profile 5), after the two before them (the Phase 8
# specification, 2.1 and 2.2).
VEHICLE_RUN_TYPES = ("sigsim", "carla", "planning-sim", "carla-autoware")
CATALOGUE_RUN_TYPE = "sigsim"
DATABROKER_CATALOGUES = {"sigsim": "vss-databroker.json", "carla": "vss-databroker-carla.json",
                         "planning-sim": "vss-databroker-planning-sim.json",
                         "carla-autoware": "vss-databroker-carla-autoware.json"}
WHEELBASE_PATH = "Vehicle.Chassis.Wheelbase"
WHEELBASE_UNIT = "mm"           # the unit of a profile's l_mm (profiles.toml UNITS); the node must carry it
VEHICLE_LAYER = "vehicle-%s.vspec" % CATALOGUE_RUN_TYPE
# The manifest's layer objects (vehicle_layer, and each of vehicle_layers), keys as the stack reads them.
LAYER_KEYS = ("file", "run_type", "profile_id", "source_vehicle", "path", "default", "default_from")

# --- the kind 2 contract (Phase 8 WP1b; the Phase 8 specification, 2.2-2.4) ----------------------------
# The seven kind 2 slots (spec 2.4) in slot order: path, VSS type and the wire's datatype; then each slot's
# payload offsets (spec 2.2). Slot 5 is kind 4's slot 0 node: v_meas maps to Motion.LongitudinalVelocity.
CTL_SLOTS = (
    ("Vehicle.{branch}.ControlCommand.Velocity", "sensor", "float"),
    ("Vehicle.{branch}.ControlCommand.Acceleration", "sensor", "float"),
    ("Vehicle.{branch}.ControlCommand.Jerk", "sensor", "float"),
    ("Vehicle.{branch}.ControlCommand.SteeringTireAngle", "sensor", "float"),
    ("Vehicle.{branch}.ControlCommand.SteeringTireRotationRate", "sensor", "float"),
    ("Vehicle.{branch}.Motion.LongitudinalVelocity", "sensor", "float"),
    ("Vehicle.{branch}.ControlCommand.StampInterval", "sensor", "uint16"),
)
CTL_SLOT_OFFSETS = ("p[2..5]", "p[25..28]", "p[29..32]", "p[33..36]", "p[37..40]", "p[41..44]", "p[45..46]")
CTL_NODE = "ControlCommand"     # the layer's branch, under the project branch
CTL_FORMAT = 1
CTL_FILES = ("vss_ctl.h", "vss_ctl.py")
CTL_OVERLAY = "overlay-ctl.vspec"
CTL_UNITS_FILE = "units-project.yaml"
CTL_QUANTITIES_FILE = "quantities-project.yaml"
CTL_PROFILES_FILE = "profiles-ctl.toml"
# The bounds profiles-ctl.toml is checked against (spec 2.3): constants of this generator, as kind 4's are, never
# settings of the file; a profiles-ctl.toml that carries an [invariants] table is refused. l_mm takes kind 4's bounds.
CTL_STEER_MAX_LIMIT = 1.0       # rad: rule 15 runs before 17, so rule 17 takes tan only inside [0, 1] (vss_tan's domain)
CTL_DT_MAX_MS_MIN = 1
CTL_DT_MAX_MS_MAX = 0xFFFE      # the stamp interval saturates at 0xFFFF, which rule 11 must always reject
CTL_DEMO_PROFILE = 2            # the demo profile: compiled only with its bounded run window (WP2's --demo)
CTL_SOURCES = ("gate-dump", "design")
CTL_TOP_KEYS = ("format", "dt_max_ms", "tol17", "overspeed_factor", "overspeed_margin", "rollback_v", "profiles")
CTL_CONSTANTS = ("tol17", "overspeed_factor", "overspeed_margin", "rollback_v")
# A profile's fields, the ones a stand_in list may name.
CTL_FIELDS = ("l_mm", "v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max", "lat_acc_max", "run_window_max_ms")
CTL_ROW_KEYS = ("id", "source") + CTL_FIELDS + ("compiled", "stand_in")
CTL_LIMITS = ("v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max", "lat_acc_max")
# The limits compared with an f32 field widened exactly; lat_acc_max is compared in double with tol17 added (rule 17).
CTL_F32_LIMITS = ("v_max", "a_max", "jerk_max", "steer_max", "steer_rate_max")

OUT_FILES = (("vss-ids.vspec", "vss-can-mapping.json")
             + tuple(DATABROKER_CATALOGUES[rt] for rt in VEHICLE_RUN_TYPES)
             + tuple("vehicle-%s.vspec" % rt for rt in VEHICLE_RUN_TYPES)
             + ("vss_contract.h", "vss_profiles.h", "vss_contract.py") + CTL_FILES + ("manifest.json",))
# What importing vss_contract.py in place leaves behind; replaced with the directory, never kept.
OUT_TOLERATED = ("__pycache__",)
F32_LIMITS = ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "v_tol")
C_PROFILE_COLUMNS = ("id", "l_mm", "v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "ay26_max", "tol26", "v_tol")
VALIDATION_REFUSE = ("BREAKING CHANGE", "DELETED ATTRIBUTE", "SEMANTIC NAME CHANGE")


class Refusal(Exception):
    """A reason to write nothing."""


# ================================================================ pure functions (no PyYAML, no venv)

def fnv1_32(data: bytes) -> int:
    """FNV-1 32: multiply, then xor (not FNV-1a); the function vss-tools hashes staticUIDs with."""
    h = FNV_OFFSET
    for b in data:
        h = (h * FNV_PRIME) & 0xFFFFFFFF
        h ^= b
    return h


def uid_bytes_le(uids) -> bytes:
    """The five UIDs as u32 little-endian, by shifts (never the host's byte order)."""
    out = bytearray()
    for u in uids:
        out += bytes(((u >> 0) & 0xFF, (u >> 8) & 0xFF, (u >> 16) & 0xFF, (u >> 24) & 0xFF))
    return bytes(out)


def catalog_digest(uids) -> int:
    return fnv1_32(uid_bytes_le(uids))


def check_digest(digest, what="catalogue digest") -> int:
    """Wire spec 4.2, step 5: a catalogue digest of all zeros or all ones is refused (it is what a
    guest without a catalogue, or a memory that was never written, would report). The kind 2 digest
    is held to the same rule (Phase 8 specification 2.2), named by `what`."""
    if digest in FORBIDDEN_DIGESTS:
        raise Refusal("the %s is 0x%08X, which is forbidden; change an overlay name" % (what, digest))
    return digest


def parse_uid(text, where="") -> int:
    if not isinstance(text, str) or not UID_RE.match(text):
        raise Refusal("malformed staticUID %r%s: expected exactly 0x followed by 8 upper-case hex digits" % (text, where))
    return int(text, 16)


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fidl_names(names):
    """Every name that is a .fidl file (plan 3.3: the generator never takes Franca input)."""
    return sorted(n for n in names if str(n).lower().endswith(".fidl"))


def f32_exact(x) -> bool:
    return struct.unpack("<f", struct.pack("<f", float(x)))[0] == float(x)


def branch_path(branch) -> str:
    return "Vehicle." + branch


def slot_paths(branch):
    return tuple(p.format(branch=branch) for p, _t, _d in SLOTS)


# --- slice.dbc ------------------------------------------------------------------------------------

_BO = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)")
_SG = re.compile(r"^SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([^,]+),([^)]+)\)\s*\[([^|]+)\|([^\]]+)\]\s*\"([^\"]*)\"")
_CYCLE = re.compile(r"^BA_\s+\"GenMsgCycleTime\"\s+BO_\s+(\d+)\s+(\d+)\s*;")


def parse_dbc(text):
    """The parts of a DBC this generator needs: messages, their GenMsgCycleTime, and each signal's
    factor, offset, range and unit. A minimal reader for the project's own file, not a DBC parser:
    // lines are comments; BO_ opens a message and its SG_ lines follow; signal names must be unique
    (the CAN provider maps by signal name alone)."""
    messages, by_id, signal_message = {}, {}, {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        m = _BO.match(line)
        if m:
            current = m.group(2)
            if current in messages:
                raise Refusal("slice.dbc: message %s defined twice" % current)
            messages[current] = {"id": int(m.group(1)), "dlc": int(m.group(3)), "period_ms": None, "signals": {}}
            by_id[int(m.group(1))] = current
            continue
        if line.startswith("SG_ "):
            m = _SG.match(line)
            if not m:
                raise Refusal("slice.dbc: cannot read the signal line %r" % line)
            if current is None:
                raise Refusal("slice.dbc: signal %s outside a message" % m.group(1))
            name = m.group(1)
            if name in signal_message:
                raise Refusal("slice.dbc: signal name %s is not unique" % name)
            messages[current]["signals"][name] = {
                "start": int(m.group(2)), "length": int(m.group(3)), "little_endian": m.group(4) == "1",
                "signed": m.group(5) == "-", "factor": float(m.group(6)), "offset": float(m.group(7)),
                "min": float(m.group(8)), "max": float(m.group(9)), "unit": m.group(10)}
            signal_message[name] = current
            continue
        current = None
        m = _CYCLE.match(line)
        if m:
            mid, period = int(m.group(1)), int(m.group(2))
            if mid not in by_id:
                raise Refusal("slice.dbc: GenMsgCycleTime for unknown message id %d" % mid)
            messages[by_id[mid]]["period_ms"] = period
    if not messages:
        raise Refusal("slice.dbc: no message found")
    return {"messages": messages, "signal_message": signal_message}


# --- profiles.toml --------------------------------------------------------------------------------

def load_toml(path, label="profiles.toml"):
    """A profile file (LABEL names it in a refusal) as a dict; a file that is not TOML is refused, not a traceback."""
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11
        raise Refusal("%s needs Python >= 3.11 (tomllib); run with ~/sdv-venv/bin/python" % label) from None
    with open(path, "rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise Refusal("%s: not valid TOML (%s)" % (label, e)) from None


def _ay(p):
    v = p.get("ay26_max")
    if v == "none":
        return None
    return v


def check_profiles(doc, dbc):
    """Every refusal of profiles.toml (wire spec 5.4, 15; slice.dbc DESIGN VALUES (5)). Returns a
    list of problems; empty means the file may be emitted."""
    problems = []
    if "invariants" in doc:
        problems.append("profiles.toml carries an [invariants] table: the bounds are constants of generate.py (spec 5.4), "
                        "not a setting of the file they check")
    envs = doc.get("envelopes", {})
    reserved = {int(k) for k in doc.get("reserved_ids", {})}
    if 0 not in reserved:
        problems.append("reserved_ids must include 0 (a frame without a profile is always reason 8)")
    age, allowance = doc.get("age_max_ms"), doc.get("pipeline_allowance_ms")
    if not isinstance(age, int) or not 0 < age < 0xFFFF:
        problems.append("age_max_ms must be an integer in 1..0xFFFE (a saturated age must always fail 22)")
    if not isinstance(allowance, int) or allowance < 0:
        problems.append("pipeline_allowance_ms must be a non-negative integer")
    if not isinstance(doc.get("carla_step_ms"), int) or doc.get("carla_step_ms", 0) <= 0:
        problems.append("carla_step_ms must be a positive integer")
    periods = [m["period_ms"] for m in dbc["messages"].values()]
    if any(not isinstance(p, int) or p <= 0 for p in periods):
        problems.append("slice.dbc: every message needs a positive GenMsgCycleTime")
    elif isinstance(age, int) and isinstance(allowance, int) and 2 * max(periods) + allowance > age:
        problems.append("2 x max(GenMsgCycleTime) + pipeline_allowance_ms > age_max_ms (%d + %d > %d)" % (2 * max(periods), allowance, age))
    # The envelopes' own rules (the Phase 8 specification, 2.4): a stand_in names the envelope's own rows; a skew_ms row
    # stands only on a planning-sim envelope, whose budget sums its rows at that skew.
    for name, env in sorted(envs.items()):
        rows = [k for k in env if k not in ENVELOPE_META_KEYS]
        stand_in = env.get("stand_in", [])
        if not isinstance(stand_in, list) or not all(isinstance(s, str) and s in rows for s in stand_in):
            problems.append("envelope %s: stand_in must be a list of this envelope's own row names (%s)" % (name, ", ".join(rows)))
        if "skew_ms" in env:
            skew = env["skew_ms"]
            if name not in SKEW_ROW_ENVELOPES:
                problems.append("envelope %s: a skew_ms row on an envelope that is not a planning-sim one (its skew is slice.dbc's "
                                "period of the message that carries rule 26's triple)" % name)
            elif env.get("budget") != "rows-summed":
                problems.append("envelope %s: skew_ms is a rows-summed budget's row, this envelope's budget is %r" % (name, env.get("budget")))
            elif not isinstance(skew, int) or isinstance(skew, bool) or skew <= 0:
                problems.append("envelope %s: skew_ms must be a positive integer (ms)" % name)
    seen, live = set(), {}
    for p in doc.get("profiles", []):
        pid = p.get("id")
        tag = "profile %r" % (pid,)
        if not isinstance(pid, int) or not 1 <= pid <= 255:
            problems.append("%s: id must be an integer in 1..255" % tag)
        if pid in seen:
            problems.append("%s: id is not unique" % tag)
        if pid in reserved:
            problems.append("%s: id is reserved" % tag)
        seen.add(pid)
        lmm = p.get("l_mm")
        if not isinstance(lmm, int) or isinstance(lmm, bool) or not L_MM_MIN <= lmm <= L_MM_MAX:
            problems.append("%s: l_mm must be an integer in %d..%d" % (tag, L_MM_MIN, L_MM_MAX))
        nonnum = [k for k in ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi", "tol26", "v_tol")
                  if not isinstance(p.get(k), (int, float)) or isinstance(p.get(k), bool)]
        if nonnum:
            problems.append("%s: %s must be numbers" % (tag, ", ".join(nonnum)))
            continue
        for k in ("v_max", "a_max", "tol26", "v_tol"):
            if not p[k] > 0:
                problems.append("%s: %s must be > 0" % (tag, k))
        if not 0 < p["delta_max"] <= DELTA_MAX_LIMIT_DEG:
            problems.append("%s: delta_max must be in (0, %s] (the tan domain)" % (tag, DELTA_MAX_LIMIT_DEG))
        if not 0 < p["v26_lo"] < p["v26_hi"]:
            problems.append("%s: need 0 < v26_lo < v26_hi" % tag)
        need = PSI_DOT_KIN_ERROR_BOUND * TOL_OVER_ERROR_MIN
        if p["tol26"] < need:
            problems.append("%s: tol26 must be >= %r (the rule-26 error bound x %r)" % (tag, need, TOL_OVER_ERROR_MIN))
        for k in F32_LIMITS:
            if not f32_exact(p[k]):
                problems.append("%s: %s = %r is not exactly representable in binary32" % (tag, k, p[k]))
        ay = p.get("ay26_max")
        if not (ay == "none" or (isinstance(ay, (int, float)) and not isinstance(ay, bool) and ay > 0)):
            problems.append("%s: ay26_max must be \"none\" or > 0" % tag)
        if p.get("envelope") not in envs:
            problems.append("%s: envelope %r is not defined" % (tag, p.get("envelope")))
        else:
            if envs[p["envelope"]].get("wheelbase_mm") not in (None, lmm):
                problems.append("%s: l_mm %r differs from envelope %s's wheelbase_mm %r" % (tag, lmm, p["envelope"],
                                                                                            envs[p["envelope"]]["wheelbase_mm"]))
            # A compiled profile's budget rests on its envelope's rows, so none of them may be a stand-in (Phase 8 spec 2.4).
            env_stand_in = envs[p["envelope"]].get("stand_in")
            if p.get("compiled") is True and isinstance(env_stand_in, list) and env_stand_in:
                problems.append("%s: compiled on envelope %s, which holds stand-in rows (%s)" % (tag, p["envelope"],
                                                                                              ", ".join(str(s) for s in env_stand_in)))
        if not isinstance(p.get("compiled"), bool):
            problems.append("%s: compiled must be true or false" % tag)
        if p.get("stand_in") and p.get("compiled"):
            problems.append("%s: a profile with stand-in values (%s) must not be compiled" % (tag, ", ".join(p["stand_in"])))
        for run_type in p.get("live_default_for", []):
            if run_type in live:
                problems.append("run type %r has two live-default profiles (%r, %r)" % (run_type, live[run_type], pid))
            live[run_type] = pid
    # The skew row describes a run type, not a name (Phase 8 WP3b): a profile on a planning-sim envelope is the live default
    # of a planning-sim run type only, and a planning-sim run type's live default stands on a planning-sim envelope.
    envelope_of = {p.get("id"): p.get("envelope") for p in doc.get("profiles", [])}
    for run_type, pid in live.items():
        on_skew_row = envelope_of.get(pid) in SKEW_ROW_ENVELOPES
        if on_skew_row and run_type not in SKEW_ROW_RUN_TYPES:
            problems.append("profile %r: on the planning-sim envelope %s, so it may be the live default of a planning-sim run type "
                            "only (SKEW_ROW_RUN_TYPES), not of %r" % (pid, envelope_of[pid], run_type))
        elif run_type in SKEW_ROW_RUN_TYPES and not on_skew_row:
            problems.append("run type %r: its live-default profile %r is on envelope %s, not a planning-sim one (SKEW_ROW_ENVELOPES: %s)"
                            % (run_type, pid, envelope_of.get(pid), ", ".join(SKEW_ROW_ENVELOPES)))
    if not seen:
        problems.append("no profile defined")
    return problems


# --- derived constants ------------------------------------------------------------------------------

def rows_summed_budget(p, env, half_lsb, skew_ms):
    """sigsim-style budget (wire spec 7.4): rows summed at the pinned operating points -- the
    delta-skew row at (v26_hi, delta 0), the v-skew row at the envelope's product bound, the
    quantisation row at (v26_hi, 0). Linear in the skew s, so the attribution spread is where the
    rows reach tol, rounded up to a whole ms."""
    L = p["l_mm"] * M_PER_MM
    vhi = float(p["v26_hi"])
    hv, hd, hpsi = half_lsb
    coef_d = (vhi / L) * env["steer_rate"]                                     # deg/s per s of skew
    coef_v = DEG_PER_RAD * env["accel_while_steering"] * math.tan(env["turn_steer_max"] * RAD_PER_DEG) / L
    quant = DEG_PER_RAD * math.tan(0.0) / L * hv + (vhi / L) * 1.0 * hd + hpsi
    skew = skew_ms / 1000.0
    total = (coef_d + coef_v) * skew + quant
    exact = (p["tol26"] - quant) / (coef_d + coef_v) * 1000.0
    if exact <= skew_ms:
        raise Refusal("profile %d: the rule-26 budget does not close (rows at the %d ms skew reach tol)" % (p["id"], skew_ms))
    return {"method": "rows-summed", "skew_ms": skew_ms, "delta_row": coef_d * skew, "v_row": coef_v * skew,
            "quant_row": quant, "total": total, "margin": p["tol26"] / total,
            "attribution_spread_exact_ms": exact, "attribution_spread_ms": int(math.ceil(exact))}


def joint_worst(L, vlo, vhi, dmax, skew_s, env, aymax, g, n, half_lsb):
    """Joint worst honest rule-26 error (wire spec 7.4, CARLA): every row at one operating point
    (v, delta) over an n x n grid, restricted to a_y_kin <= aymax. Returns (total, v, delta, a_y)."""
    hv, hd, hpsi = half_lsb
    best = (0.0, 0.0, 0.0, 0.0)
    for i in range(n):
        v = vlo + (vhi - vlo) * i / (n - 1)
        for j in range(n):
            dd = dmax * j / (n - 1)
            d = dd * RAD_PER_DEG
            t = math.tan(d)
            c = math.cos(d)
            s2 = 1.0 / (c * c)
            ay = v * v * t / L
            if aymax is not None and ay > aymax:
                continue
            under = (v / L) * env["understeer_gradient"] * ay / g
            dskew = (v / L) * s2 * (env["steer_rate"] * skew_s)
            vskew = DEG_PER_RAD * t / L * (env["accel_while_steering"] * skew_s)
            quant = DEG_PER_RAD * t / L * hv + (v / L) * s2 * hd + hpsi
            tot = under + dskew + vskew + quant
            if tot > best[0]:
                best = (tot, v, dd, ay)
    return best


def joint_grid_budget(p, env, half_lsb, step_ms, rule26):
    """CARLA-style budget: k_attr is the smallest whole number of steps whose joint worst exceeds
    tol; the attribution spread is (k_attr - 1) steps, because the pacing keeps step boundaries at
    least one step of wall time apart (wire spec 7.4)."""
    L = p["l_mm"] * M_PER_MM
    worst = []
    for k in range(1, int(rule26["k_attr_search_max"]) + 1):
        w = joint_worst(L, float(p["v26_lo"]), float(p["v26_hi"]), float(p["delta_max"]), k * step_ms / 1000.0,
                        env, _ay(p), float(rule26["g"]), int(rule26["grid_points"]), half_lsb)
        worst.append(w)
        if w[0] > p["tol26"]:
            break
    else:
        raise Refusal("profile %d: no step count up to %s exceeds tol; k_attr is undefined" % (p["id"], rule26["k_attr_search_max"]))
    k_attr = len(worst)
    if k_attr == 1:
        raise Refusal("profile %d: the rule-26 budget does not close at one step (joint worst %.3f > tol)" % (p["id"], worst[0][0]))
    return {"method": "joint-grid", "step_ms": step_ms, "joint_worst_by_steps": tuple(w[0] for w in worst),
            "worst_point_one_step": {"v": worst[0][1], "delta": worst[0][2], "a_y_kin": worst[0][3]},
            "total": worst[0][0], "margin": p["tol26"] / worst[0][0], "k_attr": k_attr,
            "attribution_spread_ms": (k_attr - 1) * step_ms}


def quant_bound(p, half_lsb):
    """slice.dbc's resolution bound of psi_dot_kin for a profile: half an LSB of v, delta and psi_dot
    at (v26_hi, delta_max)."""
    L = p["l_mm"] * M_PER_MM
    hv, hd, hpsi = half_lsb
    d = p["delta_max"] * RAD_PER_DEG
    c = math.cos(d)
    return DEG_PER_RAD * math.tan(d) / L * hv + p["v26_hi"] / L * (1.0 / (c * c)) * hd + hpsi


def derive(doc, dbc, slot_signals):
    """Every constant the profile file and slice.dbc imply (wire spec 5.5, 14.2, 15; slice.dbc
    DESIGN VALUES (2), (5)). slot_signals: the DBC signal of each slot, in slot order."""
    problems = check_profiles(doc, dbc)
    if problems:
        raise Refusal("profiles.toml: " + "; ".join(problems))
    sm = dbc["signal_message"]
    for i, s in enumerate(slot_signals):
        if s not in sm:
            raise Refusal("slot %d's dbc2vss signal %r is not in slice.dbc" % (i, s))
    msg_of = [sm[s] for s in slot_signals]
    r26 = {msg_of[i] for i in RULE26_SLOTS}
    if len(r26) != 1:
        raise Refusal("rule 26's three inputs (slots 0, 2, 3) must share one DBC message, found %s" % sorted(r26))
    r26_msg = r26.pop()
    period = {m: dbc["messages"][m]["period_ms"] for m in sorted(set(msg_of))}
    p26 = period[r26_msg]
    step = doc["carla_step_ms"]
    age, allowance = doc["age_max_ms"], doc["pipeline_allowance_ms"]
    cap = step + p26
    rtf22 = {}
    for m, pm in period.items():
        den = age - allowance - 2 * pm + cap
        if den <= 0:
            raise Refusal("RTF_22 for %s is undefined (AGE_MAX - A - 2 x period + cap = %d)" % (m, den))
        rtf22[m] = step / den
    if (3 * p26) % 2:
        raise Refusal("the spread accounting threshold (1.5 x %d ms) is not a whole ms" % p26)
    sig = dbc["messages"]
    half = tuple(sig[msg_of[i]]["signals"][slot_signals[i]]["factor"] / 2.0 for i in RULE26_SLOTS)
    budgets, spreads, quants = {}, {}, {}
    for p in doc["profiles"]:
        env = doc["envelopes"][p["envelope"]]
        if env["budget"] == "rows-summed":
            # The skew is one period of the message carrying rule 26's triple, unless the envelope is a planning-sim one,
            # whose skew_ms row replaces it (check_profiles refuses the row on any other envelope).
            b = rows_summed_budget(p, env, half, env.get("skew_ms", p26))
        elif env["budget"] == "joint-grid":
            b = joint_grid_budget(p, env, half, step, doc["rule26"])
        else:
            raise Refusal("envelope %s: unknown budget method %r" % (p["envelope"], env["budget"]))
        # Spec 7.4 (Phase 7 spec 5 item 2): a budget that closes must also keep the envelope's margin over the honest
        # worst. Short of it, the a_y bound narrows (then v26_hi); tol never moves.
        if b["margin"] < env["margin_target"]:
            raise Refusal("profile %d: the rule-26 margin over tol is %.4f, below envelope %s's margin_target %r (spec 7.4): "
                          "narrow ay26_max, then v26_hi; tol never moves" % (p["id"], b["margin"], p["envelope"], env["margin_target"]))
        b["margin_target"] = env["margin_target"]
        budgets[p["id"]] = b
        spreads[p["id"]] = b["attribution_spread_ms"]
        quants[p["id"]] = quant_bound(p, half)
    return {
        "rule26_message": r26_msg, "slot_messages": tuple(msg_of), "periods_ms": period,
        "half_lsb": {"v": half[0], "delta": half[1], "psi_dot": half[2]},
        "pacing_interval_ms": step, "repeat_cap_ms": cap, "rtf_gap": step / cap,
        "rtf_22": rtf22, "rtf_22_run": max(rtf22.values()),
        "spread_exceeded_ms": (3 * p26) // 2, "attribution_spread_ms": spreads,
        "rule26_budget": budgets, "quant_bound": quants,
    }


# --- profiles-ctl.toml and the kind 2 slots (Phase 8 WP1b) ---------------------------------------------

def ctl_slot_paths(branch):
    return tuple(p.format(branch=branch) for p, _t, _d in CTL_SLOTS)


def ctl_digest(uids) -> int:
    """VSS_CTL_DIGEST (the Phase 8 specification, 2.2): FNV-1 32 over the seven kind 2 slot UIDs as u32
    little-endian in slot order, the catalogue digest's construction over the kind 2 slots."""
    if len(uids) != len(CTL_SLOTS):
        raise Refusal("the kind 2 digest is over the %d slot UIDs, not %d" % (len(CTL_SLOTS), len(uids)))
    return catalog_digest(uids)


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _integer(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _finite(x) -> bool:
    try:
        return math.isfinite(x)
    except OverflowError:       # an integer past a double's range (tomllib bounds none): no finite double, as both files need
        return False


def _ctl_f32_exact(x) -> bool:
    try:
        return f32_exact(x)
    except OverflowError:       # past binary32's range: struct will not pack it, so it is no binary32 value
        return False


def check_ctl_profiles(doc):
    """Every refusal of profiles-ctl.toml (the Phase 8 specification, 2.3; the file's header lists them).
    Returns a list of problems; empty means the kind 2 contract may be written."""
    problems = []
    if "invariants" in doc:
        problems.append("profiles-ctl.toml carries an [invariants] table: the bounds are constants of generate.py, not a "
                        "setting of the file they check")
    unknown = sorted(str(k) for k in doc if k not in CTL_TOP_KEYS + ("invariants",))
    if unknown:
        problems.append("unknown top-level key(s): %s" % ", ".join(unknown))
    if not _integer(doc.get("format")) or doc.get("format") != CTL_FORMAT:
        problems.append("format must be %d" % CTL_FORMAT)
    dt = doc.get("dt_max_ms")
    if not _integer(dt) or not CTL_DT_MAX_MS_MIN <= dt <= CTL_DT_MAX_MS_MAX:
        problems.append("dt_max_ms must be an integer in %d..0x%04X (rule 11 must reject a saturated interval, 0xFFFF)"
                        % (CTL_DT_MAX_MS_MIN, CTL_DT_MAX_MS_MAX))
    for k in CTL_CONSTANTS:
        v = doc.get(k)
        if not _number(v) or not _finite(v) or not v >= 0:
            problems.append("%s must be a finite number >= 0" % k)
    rows = doc.get("profiles", [])
    if not isinstance(rows, list) or not all(isinstance(p, dict) for p in rows):
        return problems + ["profiles must be an array of tables ([[profiles]])"]
    seen, compiled = set(), 0
    for p in rows:
        pid = p.get("id")
        tag = "profile %r" % (pid,)
        unknown = sorted(str(k) for k in p if k not in CTL_ROW_KEYS)
        if unknown:
            problems.append("%s: unknown key(s) %s" % (tag, ", ".join(unknown)))
        if not _integer(pid) or not 1 <= pid <= 255:
            problems.append("%s: id must be an integer in 1..255 (0 is never bound)" % tag)
        elif pid in seen:
            problems.append("%s: id is not unique" % tag)
        else:
            seen.add(pid)
        if p.get("source") not in CTL_SOURCES:
            problems.append("%s: source must be one of %s" % (tag, ", ".join(CTL_SOURCES)))
        lmm = p.get("l_mm")
        if not _integer(lmm) or not L_MM_MIN <= lmm <= L_MM_MAX:
            problems.append("%s: l_mm must be an integer in %d..%d" % (tag, L_MM_MIN, L_MM_MAX))
        nonnum = [k for k in CTL_LIMITS if not _number(p.get(k))]
        if nonnum:
            problems.append("%s: %s must be numbers" % (tag, ", ".join(nonnum)))
        else:
            for k in CTL_LIMITS:
                if not _finite(p[k]) or not p[k] > 0:
                    problems.append("%s: %s must be a finite number > 0" % (tag, k))
            if not 0 < p["steer_max"] <= CTL_STEER_MAX_LIMIT:
                problems.append("%s: steer_max must be in (0, %r] rad (rule 17 takes tan only inside [0, 1])" % (tag, CTL_STEER_MAX_LIMIT))
            for k in CTL_F32_LIMITS:
                if not _ctl_f32_exact(p[k]):
                    problems.append("%s: %s = %r is not exactly representable in binary32" % (tag, k, p[k]))
        window = p.get("run_window_max_ms")
        if window is not None and (not _integer(window) or not window > 0):
            problems.append("%s: run_window_max_ms must be absent or a positive integer" % tag)
        if type(p.get("compiled")) is not bool:
            problems.append("%s: compiled must be true or false" % tag)
        stand_in = p.get("stand_in", [])
        if not isinstance(stand_in, list) or not all(s in CTL_FIELDS for s in stand_in):
            problems.append("%s: stand_in must be a list of this table's field names (%s)" % (tag, ", ".join(CTL_FIELDS)))
        elif stand_in and p.get("compiled") is True:
            problems.append("%s: a profile with stand-in values (%s) must not be compiled" % (tag, ", ".join(stand_in)))
        if pid == CTL_DEMO_PROFILE and p.get("compiled") is True and window is None:
            problems.append("profile %d is compiled without run_window_max_ms: the demo profile is used only inside a bounded "
                            "window" % CTL_DEMO_PROFILE)
        if p.get("compiled") is True:
            compiled += 1
    if not compiled:
        problems.append("no compiled profile: the ctl build would answer every kind 2 frame with reason 8")
    return problems


def ctl_compiled_profiles(doc):
    return [p for p in sorted(doc["profiles"], key=lambda q: q["id"]) if p["compiled"] is True]


# --- comparisons of id outputs ------------------------------------------------------------------------

def stock_differences(stock, full, branch):
    """Standard nodes whose UID differs from the overlay-free build (Vehicle.Speed excepted), and
    added nodes outside the project branch."""
    problems = []
    for path, node in stock.items():
        if path not in full:
            problems.append("%s: in the stock tree, missing with the overlay" % path)
        elif path != SPEED_PATH and full[path]["staticUID"] != node["staticUID"]:
            problems.append("%s: staticUID %s differs from the stock tree's %s (a restated type, datatype, unit, "
                            "min, max or allowed)" % (path, full[path]["staticUID"], node["staticUID"]))
    root = branch_path(branch)
    for path in full:
        if path not in stock and not (path == root or path.startswith(root + ".")):
            problems.append("%s: added outside the project branch %s" % (path, root))
    return problems


def uid_changes(previous, current):
    """(changed, removed, added) between two id outputs, by path."""
    changed = sorted(p for p in previous if p in current and previous[p].get("staticUID") != current[p].get("staticUID"))
    removed = sorted(p for p in previous if p not in current)
    added = sorted(p for p in current if p not in previous)
    return changed, removed, added


def previous_drift(changed, removed, flagged):
    """The lines that refuse a run against the previous generation: a staticUID that changed or
    disappeared, or one of vss-tools' own breaking-change lines. The path-by-path diff is what
    decides; vss-tools' validation matches by UID first and exits 0 on a breaking change, so it
    is a cross-check and never the only judge. Added nodes are not drift."""
    return ["changed: " + p for p in changed] + ["removed: " + p for p in removed] + ["vss-tools: " + v for v in flagged]


# --- the committed UID baseline ---------------------------------------------------------------------------

def baseline_paths(ids, branch):
    """The nodes the baseline lists: the five slots and every node of the project branch."""
    root = branch_path(branch)
    slots = set(slot_paths(branch))
    return sorted(p for p in ids if p in slots or p == root or p.startswith(root + "."))


def render_baseline(digest, uids) -> str:
    """The baseline file's exact text: a fixed header, the digest, then one line per node, sorted.
    uids: {path: staticUID as an int}."""
    lines = list(BASELINE_HEADER) + ["", "digest 0x%08X" % digest]
    lines += ["%s 0x%08X" % (path, uids[path]) for path in sorted(uids)]
    return "\n".join(lines) + "\n"


def parse_baseline(text):
    """(digest, {path: uid}) of a baseline file. Anything else than comments, blank lines, one
    `digest` line and `<path> <staticUID>` lines is refused."""
    digest, uids = None, {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise Refusal("%s line %d: expected '<path> <staticUID>' or 'digest <value>', got %r" % (BASELINE_NAME, n, line))
        key, value = parts
        if key == "digest":
            if digest is not None:
                raise Refusal("%s line %d: the digest is given twice" % (BASELINE_NAME, n))
            digest = parse_uid(value, " in %s line %d" % (BASELINE_NAME, n))
            continue
        if not key.startswith("Vehicle."):
            raise Refusal("%s line %d: %r is not a node path (Vehicle.<...>)" % (BASELINE_NAME, n, key))
        if key in uids:
            raise Refusal("%s line %d: %s is listed twice" % (BASELINE_NAME, n, key))
        uids[key] = parse_uid(value, " in %s line %d" % (BASELINE_NAME, n))
    if digest is None:
        raise Refusal("%s has no digest line" % BASELINE_NAME)
    if not uids:
        raise Refusal("%s lists no node" % BASELINE_NAME)
    return digest, uids


def baseline_drift(baseline, digest, uids):
    """The lines that refuse a run against the baseline: a moved digest (first, so a long list of
    nodes never hides it), then each changed, removed or added node. An added node counts, because the
    baseline lists the whole project branch."""
    b_digest, b_uids = baseline
    lines = []
    if b_digest != digest:
        lines.append("digest: 0x%08X in the baseline, 0x%08X now" % (b_digest, digest))
    lines += ["changed: " + p for p in sorted(b_uids) if p in uids and b_uids[p] != uids[p]]
    lines += ["removed: " + p for p in sorted(b_uids) if p not in uids]
    lines += ["added: " + p for p in sorted(uids) if p not in b_uids]
    return lines


def first_lines(lines, n=40):
    """At most n lines of a refusal's detail, and a count of what was left out."""
    return list(lines[:n]) + (["... and %d more" % (len(lines) - n)] if len(lines) > n else [])


def write_baseline(path, text):
    """Replace the baseline whole or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.tmp-%d" % (path.name, os.getpid()))
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def speed_problems(ids):
    """Vehicle.Speed must be a sensor, a float, in km/h and never negative (min 0). Its UID is the
    one the overlay changes on purpose, so the stock comparison exempts it; this holds the decision."""
    n = ids.get(SPEED_PATH)
    if n is None:
        return ["%s: missing from the generated catalogue" % SPEED_PATH]
    problems = ["%s: %s is %r, the catalogue needs %r" % (SPEED_PATH, k, n.get(k), want)
                for k, want in (("type", "sensor"), ("datatype", "float"), ("unit", SPEED_UNIT)) if n.get(k) != want]
    low = n.get("min")
    if isinstance(low, bool) or not isinstance(low, (int, float)) or low != 0:
        problems.append("%s: min is %r, the catalogue needs 0 (never negative)" % (SPEED_PATH, low))
    return problems


def dbc_signal_problems(mapping, dbc):
    """Every dbc2vss signal of the mapping must be defined in slice.dbc."""
    problems = []
    for path, node in sorted(mapping.items()):
        m = node.get("dbc2vss")
        if m is not None and m.get("signal") not in dbc["signal_message"]:
            problems.append("%s: dbc2vss signal %r is not defined in slice.dbc" % (path, m.get("signal")))
    return problems


def json_nodes(tree):
    """{path: node} of a vss-tools JSON export."""
    out = {}

    def walk(prefix, node):
        out[prefix] = node
        for name, child in node.get("children", {}).items():
            walk(prefix + "." + name, child)

    for name, node in tree.items():
        walk(name, node)
    return out


def strip_key(obj, key):
    if isinstance(obj, dict):
        return {k: strip_key(v, key) for k, v in obj.items() if k != key}
    if isinstance(obj, list):
        return [strip_key(v, key) for v in obj]
    return obj


def vehicle_layers(doc):
    """One per-vehicle layer per run type with a live default, {run type: vehicle_layer(doc, run type)} in
    VEHICLE_RUN_TYPES' order. A run type that profiles.toml gives a live-default profile but that has no layer here is
    refused: its catalogue would serve another vehicle's wheelbase."""
    named = {rt for p in doc.get("profiles", []) for rt in p.get("live_default_for", [])}
    extra = sorted((rt for rt in named if rt not in VEHICLE_RUN_TYPES), key=str)
    if extra:
        raise Refusal("the vehicle layers: run type(s) %s have a live-default profile in profiles.toml but no vehicle layer in "
                      "generate.py (VEHICLE_RUN_TYPES: %s)" % (", ".join(repr(rt) for rt in extra), ", ".join(VEHICLE_RUN_TYPES)))
    return {rt: vehicle_layer(doc, rt) for rt in VEHICLE_RUN_TYPES}


def vehicle_layer(doc, run_type=CATALOGUE_RUN_TYPE):
    """The per-vehicle layer of run_type: the live-default profile of that run type in profiles.toml names the
    source vehicle, and its l_mm is the wheelbase the catalogue's default carries. Refused when the run type
    has no live-default profile, when that profile's L is a stand-in, or when two profiles of the same source
    vehicle disagree on L (one vehicle, one wheelbase). Returns the layer's record; render_vehicle_layer gives
    its text."""
    profiles = doc.get("profiles", [])
    chosen = [p for p in profiles if run_type in p.get("live_default_for", [])]
    if len(chosen) != 1:
        raise Refusal("the vehicle layer: run type %r has %d live-default profiles in profiles.toml, it needs exactly one"
                      % (run_type, len(chosen)))
    p = chosen[0]
    if "l_mm" in p.get("stand_in", ()):
        raise Refusal("the vehicle layer: profile %r's l_mm is a stand-in, so no catalogue may declare it as a vehicle's "
                      "wheelbase" % (p.get("id"),))
    lmm = p.get("l_mm")
    if not isinstance(lmm, int) or isinstance(lmm, bool) or not L_MM_MIN <= lmm <= L_MM_MAX:
        raise Refusal("the vehicle layer: profile %r's l_mm %r is not an integer in %d..%d" % (p.get("id"), lmm, L_MM_MIN, L_MM_MAX))
    vehicle = p.get("source_vehicle")
    if not isinstance(vehicle, str) or not vehicle:
        raise Refusal("the vehicle layer: profile %r names no source_vehicle" % (p.get("id"),))
    others = sorted((q.get("id"), q.get("l_mm")) for q in profiles if q.get("source_vehicle") == vehicle and q.get("l_mm") != lmm)
    if others:
        raise Refusal("the vehicle layer: source vehicle %r has wheelbase %d mm in profile %r but %s elsewhere: one vehicle, "
                      "one wheelbase" % (vehicle, lmm, p.get("id"), ", ".join("%r in profile %r" % (q[1], q[0]) for q in others)))
    return {"file": "vehicle-%s.vspec" % run_type, "run_type": run_type, "profile_id": p["id"], "source_vehicle": vehicle,
            "path": WHEELBASE_PATH, "default": lmm,
            "default_from": "profiles.toml: l_mm of profile %d, the live-default profile of run type %s" % (p["id"], run_type)}


def render_vehicle_layer(layer) -> str:
    """The layer's exact text: a header that says where its one value came from, then the one node."""
    lines = [
        "# %s -- GENERATED by sdv/vss/generate.py from profiles.toml. Do not edit; never commit (sdv-out/ is ignored)." % layer["file"],
        "#",
        "# The per-vehicle layer of run type %s (kind 4 wire specification 5.6, 14.5): the catalogue default of" % layer["run_type"],
        "# %s is the source vehicle's wheelbase in mm, %s." % (layer["path"], layer["default_from"]),
        "# Source vehicle: %s. Loaded after overlay.vspec. `default` is not a staticUID input, so no UID moves" % layer["source_vehicle"],
        "# (generate.py checks that the node keeps the stock tree's staticUID).",
        "%s:" % layer["path"],
        "  default: %d" % layer["default"],
        "",
    ]
    return "\n".join(lines)


def vehicle_layer_problems(layer, stock, ids, mapping):
    """The layer reached the catalogue as generated and moved no staticUID: the node keeps the stock tree's
    staticUID, is an attribute in mm, and the mapping JSON (and so the databroker JSON) carries the layer's
    default."""
    path = layer["path"]
    if path not in stock:
        return ["%s: the vehicle layer's node is not in the stock tree" % path]
    if path not in ids or path not in mapping:
        return ["%s: the vehicle layer's node is not in the generated catalogue" % path]
    problems = []
    if ids[path].get("staticUID") != stock[path].get("staticUID"):
        problems.append("%s: the vehicle layer %s moved its staticUID from the stock tree's %s to %s" % (
            path, layer["file"], stock[path].get("staticUID"), ids[path].get("staticUID")))
    if ids[path].get("type") != "attribute" or ids[path].get("unit") != WHEELBASE_UNIT:
        problems.append("%s: is %s in %s, the vehicle layer needs an attribute in %s" % (
            path, ids[path].get("type"), ids[path].get("unit"), WHEELBASE_UNIT))
    got = mapping[path].get("default")
    if isinstance(got, bool) or got != layer["default"]:
        problems.append("%s: default %r in the mapping JSON, the vehicle layer %s sets %r" % (path, got, layer["file"], layer["default"]))
    return problems


def overlay_differences(overlay, ids, mapping):
    """Overlay entries that did not reach the catalogue as written."""
    problems = []
    for path, attrs in overlay.items():
        if path not in ids or path not in mapping:
            problems.append("%s: overlay entry not in the generated catalogue" % path)
            continue
        for k in ("type", "datatype", "unit", "min", "max", "allowed"):
            if k in attrs and ids[path].get(k) != attrs[k]:
                problems.append("%s: %s is %r in the id output, %r in the overlay" % (path, k, ids[path].get(k), attrs[k]))
        for k in ("description", "comment") + EXTENDED_ATTRIBUTES:
            if k in attrs and mapping[path].get(k) != attrs[k]:
                problems.append("%s: %s differs between the overlay and the mapping JSON" % (path, k))
    return problems


def ctl_layer_problems(ids, ids_ctl, entries, ctl_tree, mapping_tree, branch):
    """The ControlCommand layer (overlay-ctl.vspec) reached the catalogue as written and moved nothing else:
    its entries lie under Vehicle.<branch>.ControlCommand and carry no dbc2vss block (no CAN signal maps to
    them, and vss-can-mapping.json is exported without the layer); the id export with the layer is the one
    without it plus exactly the entries, every other node unchanged; the JSON export with it lists the same
    nodes, carries each entry as written, and is the mapping JSON but for the ControlCommand branch. ids and
    mapping_tree are the exports without the layer."""
    root = branch_path(branch) + "." + CTL_NODE
    problems = []
    for path, attrs in sorted(entries.items()):
        if not (path == root or path.startswith(root + ".")):
            problems.append("%s: overlay-ctl.vspec entry outside %s" % (path, root))
        if isinstance(attrs, dict) and any(k in attrs for k in EXTENDED_ATTRIBUTES):
            problems.append("%s: overlay-ctl.vspec carries a dbc2vss block (no CAN signal maps to ControlCommand)" % path)
    problems += ["%s: the ControlCommand layer changed this node" % p for p in sorted(ids) if ids_ctl.get(p) != ids[p]]
    added = set(ids_ctl) - set(ids)
    if added != set(entries):
        problems.append("the ControlCommand layer added nodes that are not its entries, or not all of them: %s"
                        % ", ".join(first_lines(sorted(added ^ set(entries)), 20)))
    nodes = json_nodes(ctl_tree)
    if set(nodes) != set(ids_ctl):
        problems.append("the ctl JSON export and the ctl id export list different nodes (%d vs %d)" % (len(nodes), len(ids_ctl)))
    problems += overlay_differences(entries, ids_ctl, nodes)
    rest = copy.deepcopy(ctl_tree)
    parts = root.split(".")
    parent = rest.get(parts[0], {})
    for name in parts[1:-1]:
        parent = parent.get("children", {}).get(name, {})
    parent.get("children", {}).pop(parts[-1], None)
    if rest != mapping_tree:
        problems.append("the databroker catalogue differs from the mapping JSON beyond the ControlCommand branch")
    return problems


# --- rendering ----------------------------------------------------------------------------------------

def c_double(x) -> str:
    s = "%.17g" % float(x)
    return s if any(ch in s for ch in ".en") else s + ".0"


def py(x) -> str:
    """A deterministic Python literal: repr for scalars, sorted keys for dicts."""
    if isinstance(x, dict):
        return "{" + ", ".join("%s: %s" % (py(k), py(v)) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))) + "}"
    if isinstance(x, (list, tuple)):
        if len(x) == 1:
            return "(" + py(x[0]) + ",)"
        return "(" + ", ".join(py(v) for v in x) + ")"
    return repr(x)


def render_c_contract(ctx) -> str:
    lines = [
        "/* vss_contract.h -- GENERATED by sdv/vss/generate.py. Do not edit; never commit (sdv-out/ is ignored).",
        " *",
        " * The kind 4 catalogue contract: each slot's VSS staticUID, the catalogue digest (FNV-1 32 over the",
        " * five UIDs as u32 little-endian in slot order), AGE_MAX and the conversion constants of rule 26.",
        " * Macros only, so a translation unit that uses none of them still compiles under -Werror.",
        " * Inputs: VSS %s source archive sha256 %s," % (VSS_TAG, ARCHIVE_SHA256),
        " * commit %s; vss-tools %s; staticUIDs %s." % (ARCHIVE_COMMIT, VSS_TOOLS_VERSION,
                                                        "case-sensitive" if CASE_SENSITIVE else "case-insensitive"),
        " */",
        "#ifndef VSS_CONTRACT_H",
        "#define VSS_CONTRACT_H",
        "",
        "#define VSS_CONTRACT_FORMAT %du" % FORMAT,
        "#define VSS_CATALOG_VERSION \"%s\"" % VSS_VERSION,
        "#define VSS_CATALOG_COMMIT \"%s\"" % ARCHIVE_COMMIT,
        "#define VSS_UID_CASE_SENSITIVE %d" % (1 if CASE_SENSITIVE else 0),
        "",
    ]
    for i, (path, uid) in enumerate(zip(ctx["slot_paths"], ctx["slot_uids"])):
        n = ctx["slot_nodes"][i]
        lines.append("/* slot %d: %s (%s, %s, %s) */" % (i, path, n["type"], n["datatype"], n.get("unit", "no unit")))
        lines.append("#define VSS_UID_SLOT%d 0x%08Xu" % (i, uid))
    lines += [
        "",
        "#define VSS_CATALOG_DIGEST 0x%08Xu" % ctx["digest"],
        "",
        "#define VSS_AGE_MAX_MS %du" % ctx["profiles_doc"]["age_max_ms"],
        "",
        "/* double literals printed with %.17g, which round-trips a double exactly */",
        "#define VSS_DEG_PER_RAD %s" % c_double(DEG_PER_RAD),
        "#define VSS_RAD_PER_DEG %s" % c_double(RAD_PER_DEG),
        "#define VSS_M_PER_MM %s" % c_double(M_PER_MM),
        "",
        "#endif /* VSS_CONTRACT_H */",
        "",
    ]
    return "\n".join(lines)


def compiled_profiles(doc):
    return [p for p in sorted(doc["profiles"], key=lambda q: q["id"]) if p["compiled"]]


def render_c_profiles(ctx) -> str:
    doc = ctx["profiles_doc"]
    rows = compiled_profiles(doc)
    lines = [
        "/* vss_profiles.h -- GENERATED by sdv/vss/generate.py from profiles.toml. Do not edit; never commit.",
        " *",
        " * The compiled kind 4 profiles, one X() per profile, for exactly one lookup function:",
        " *   X(id, l_mm, v_max, a_max, delta_max, v26_lo, v26_hi, ay26_max, tol26, v_tol)",
        " * units: -, mm, m/s, m/s^2, deg, m/s, m/s, m/s^2 (0.0 = no a_y bound), deg/s, m/s.",
        " * Profiles with stand-in values are not here (vss_contract.py lists them).",
        " */",
        "#ifndef VSS_PROFILES_H",
        "#define VSS_PROFILES_H",
        "",
        "#define VSS_PROFILE_TABLE(X) \\",
    ]
    for n, p in enumerate(rows):
        ay = _ay(p)
        vals = ["%du" % p["id"], "%du" % p["l_mm"]] + [c_double(p[k]) for k in ("v_max", "a_max", "delta_max", "v26_lo", "v26_hi")]
        vals += [c_double(0.0 if ay is None else ay), c_double(p["tol26"]), c_double(p["v_tol"])]
        lines.append("    X(%s)%s" % (", ".join(vals), " \\" if n < len(rows) - 1 else ""))
    lines += [
        "",
        "#define VSS_PROFILE_COUNT %du" % len(rows),
        "#define VSS_PROFILE_IDS \"%s\"" % " ".join(str(p["id"]) for p in rows),
        "",
        "#endif /* VSS_PROFILES_H */",
        "",
    ]
    return "\n".join(lines)


def render_python(ctx) -> str:
    doc, d = ctx["profiles_doc"], ctx["derived"]
    profiles = []
    for p in sorted(doc["profiles"], key=lambda q: q["id"]):
        q = {k: v for k, v in p.items()}
        q["ay26_max"] = _ay(p)
        q["stand_in"] = tuple(p.get("stand_in", ()))
        q["live_default_for"] = tuple(p.get("live_default_for", ()))
        profiles.append(q)
    live = {rt: p["id"] for p in doc["profiles"] for rt in p.get("live_default_for", [])}
    L: list[str] = []
    w = L.append
    w('"""vss_contract.py -- GENERATED by sdv/vss/generate.py. Do not edit; never commit (sdv-out/ is ignored).')
    w("")
    w("The kind 4 contract for Python (the claim bridge, the feeders, the launcher, the tests): the same")
    w("slot UIDs, digest and profile table as vss_contract.h and vss_profiles.h, plus what the monitor never")
    w("uses -- the pipeline allowance A, the CARLA step, the envelope rows -- and every constant derived")
    w("from them. Every number is a design value or computed from design values; none is a measurement.")
    w('"""')
    w("")
    w("FORMAT = %d" % FORMAT)
    w("VSS_TAG = %r" % VSS_TAG)
    w("VSS_VERSION = %r" % VSS_VERSION)
    w("VSS_COMMIT = %r" % ARCHIVE_COMMIT)
    w("VSS_ARCHIVE_SHA256 = %r" % ARCHIVE_SHA256)
    w("VSS_TOOLS_VERSION = %r" % VSS_TOOLS_VERSION)
    w("UID_CASE_SENSITIVE = %r" % CASE_SENSITIVE)
    w("PROJECT_BRANCH = %r" % branch_path(ctx["branch"]))
    w("")
    w("# The five kind 4 slots, in slot order (payload offsets: the wire specification, section 2).")
    w("SLOT_PATHS = %s" % py(tuple(ctx["slot_paths"])))
    w("SLOT_TYPES = %s" % py(tuple(n["type"] for n in ctx["slot_nodes"])))
    w("SLOT_DATATYPES = %s" % py(tuple(n["datatype"] for n in ctx["slot_nodes"])))
    w("SLOT_UNITS = %s" % py(tuple(n.get("unit") for n in ctx["slot_nodes"])))
    w("SLOT_UIDS = (%s)" % ", ".join("0x%08X" % u for u in ctx["slot_uids"]))
    w("CATALOG_DIGEST = 0x%08X" % ctx["digest"])
    w("")
    w("# The CAN side of each slot (slice.dbc through the overlay's dbc2vss): signal, message, unit.")
    w("SLOT_DBC_SIGNALS = %s" % py(tuple(ctx["slot_signals"])))
    w("SLOT_DBC_MESSAGES = %s" % py(d["slot_messages"]))
    w("SLOT_DBC_UNITS = %s" % py(tuple(ctx["slot_dbc_units"])))
    w("DBC_PERIOD_MS = %s" % py(d["periods_ms"]))
    w("RULE26_DBC_MESSAGE = %r" % d["rule26_message"])
    w("# Half an LSB of v [m/s], delta [deg] and psi_dot [deg/s]: the quantisation rows of rule 26.")
    w("DBC_HALF_LSB = %s" % py(d["half_lsb"]))
    w("")
    w("AGE_MAX_MS = %d" % doc["age_max_ms"])
    w("PIPELINE_ALLOWANCE_MS = %d" % doc["pipeline_allowance_ms"])
    w("CARLA_STEP_MS = %d" % doc["carla_step_ms"])
    w("DEG_PER_RAD = %r" % DEG_PER_RAD)
    w("RAD_PER_DEG = %r" % RAD_PER_DEG)
    w("M_PER_MM = %r" % M_PER_MM)
    w("")
    w("# CARLA feeder (slice.dbc DESIGN VALUES (2)): a step made current at most once per pacing interval;")
    w("# a step repeated only while no older than the repeat cap (one step + one period of RULE26_DBC_MESSAGE).")
    w("FEEDER_PACING_INTERVAL_MS = %d" % d["pacing_interval_ms"])
    w("FEEDER_REPEAT_CAP_MS = %d" % d["repeat_cap_ms"])
    w("# Gap onset step / cap, and the honest-22 real-time factor per message,")
    w("# step / (AGE_MAX - A - 2 x period + cap); run level = the largest (slice.dbc DESIGN VALUES (5)).")
    w("RTF_GAP = %r" % d["rtf_gap"])
    w("RTF_22 = %s" % py(d["rtf_22"]))
    w("RTF_22_RUN = %r" % d["rtf_22_run"])
    w("")
    w("# The bridge's rule-26 spread thresholds (wire spec 14.2), whole ms, compared at the timestamps' own")
    w("# resolution: accounting (one period + half a period) and attribution (per profile, from the budget).")
    w("SPREAD_EXCEEDED_MS = %d" % d["spread_exceeded_ms"])
    w("ATTRIBUTION_SPREAD_MS = %s" % py(d["attribution_spread_ms"]))
    w("")
    w("# Every profile of profiles.toml; COMPILED_PROFILE_IDS are the ones in vss_profiles.h. ay26_max None =")
    w("# no a_y bound (0.0 in the C table). A profile with stand_in values is never compiled.")
    w("PROFILES = (")
    for q in profiles:
        w("    %s," % py(q))
    w(")")
    w("COMPILED_PROFILE_IDS = %s" % py(tuple(p["id"] for p in compiled_profiles(doc))))
    w("RESERVED_PROFILE_IDS = %s" % py(tuple(sorted(int(k) for k in doc.get("reserved_ids", {})))))
    w("LIVE_DEFAULT_PROFILE = %s" % py(live))
    w("ENVELOPES = %s" % py(doc["envelopes"]))
    w("RULE26_PARAMETERS = %s" % py(doc["rule26"]))
    w("# Each profile's rule-26 budget: rows, total, margin over tol, attribution spread (wire spec 7.4).")
    w("RULE26_BUDGET = %s" % py(d["rule26_budget"]))
    w("# slice.dbc's quantisation bound of psi_dot_kin at (v26_hi, delta_max), deg/s.")
    w("QUANT_BOUND = %s" % py(d["quant_bound"]))
    w("")
    return "\n".join(L)


def render_c_ctl(ctx) -> str:
    """vss_ctl.h (the Phase 8 specification, 2.4): exactly 2.4's macros; the compiled kind 2 profiles only.
    ctx: slot_paths, slot_nodes, slot_uids, digest and doc (profiles-ctl.toml)."""
    doc = ctx["doc"]
    rows = ctl_compiled_profiles(doc)
    lines = [
        "/* vss_ctl.h -- GENERATED by sdv/vss/generate.py from overlay-ctl.vspec and profiles-ctl.toml. Do not edit; never",
        " * commit (sdv-out/ is ignored).",
        " *",
        " * The kind 2 contract (the Phase 8 specification, 2.4): each kind 2 slot's VSS staticUID, their digest (FNV-1 32",
        " * over the seven UIDs as u32 little-endian in slot order, the kind 4 catalogue digest's construction), the",
        " * constants of rules 11 and 17-19, and the compiled kind 2 profiles as an X-macro table. Macros only; included",
        " * by monitor.c's ctl build alone (MONITOR_EXT_KINDS 0x14), searched on the include path.",
        " * Inputs: VSS %s source archive sha256 %s," % (VSS_TAG, ARCHIVE_SHA256),
        " * commit %s; vss-tools %s; staticUIDs %s." % (ARCHIVE_COMMIT, VSS_TOOLS_VERSION,
                                                        "case-sensitive" if CASE_SENSITIVE else "case-insensitive"),
        " */",
        "#ifndef VSS_CTL_H",
        "#define VSS_CTL_H",
        "",
        "#define VSS_CTL_FORMAT %du" % CTL_FORMAT,
        "",
    ]
    for i, (path, uid) in enumerate(zip(ctx["slot_paths"], ctx["slot_uids"])):
        n = ctx["slot_nodes"][i]
        lines.append("/* slot %d: %s (%s, %s, %s; %s) */" % (i, path, n["type"], n["datatype"], n.get("unit", "no unit"),
                                                             CTL_SLOT_OFFSETS[i]))
        lines.append("#define VSS_CTL_UID_SLOT%d 0x%08Xu" % (i, uid))
    lines += [
        "",
        "#define VSS_CTL_DIGEST 0x%08Xu" % ctx["digest"],
        "",
        "#define VSS_CTL_DT_MAX_MS %du" % doc["dt_max_ms"],
        "/* double literals printed with %.17g, which round-trips a double exactly */",
        "#define VSS_CTL_TOL17 %s" % c_double(doc["tol17"]),
        "#define VSS_CTL_OVERSPEED_FACTOR %s" % c_double(doc["overspeed_factor"]),
        "#define VSS_CTL_OVERSPEED_MARGIN %s" % c_double(doc["overspeed_margin"]),
        "#define VSS_CTL_ROLLBACK_V %s" % c_double(doc["rollback_v"]),
        "",
        "/* One X() per compiled kind 2 profile, for exactly one lookup function:",
        " *   X(id, l_mm, v_max, a_max, jerk_max, steer_max, steer_rate_max, lat_acc_max)",
        " * units: -, mm, m/s, m/s^2, m/s^3, rad, rad/s, m/s^2. Profiles with stand-in values are not here",
        " * (vss_ctl.py lists every profile). */",
        "#define VSS_CTL_PROFILE_TABLE(X) \\",
    ]
    for n, p in enumerate(rows):
        vals = ["%du" % p["id"], "%du" % p["l_mm"]] + [c_double(p[k]) for k in CTL_LIMITS]
        lines.append("    X(%s)%s" % (", ".join(vals), " \\" if n < len(rows) - 1 else ""))
    lines += [
        "",
        "#define VSS_CTL_PROFILE_COUNT %du" % len(rows),
        "#define VSS_CTL_PROFILE_IDS \"%s\"" % " ".join(str(p["id"]) for p in rows),
        "",
        "#endif /* VSS_CTL_H */",
        "",
    ]
    return "\n".join(lines)


def render_python_ctl(ctx) -> str:
    """vss_ctl.py (the Phase 8 specification, 2.4): exactly 2.4's names, every profile with the nine keys WP2's
    loader holds a row to (a profile's source and stand-ins stay in profiles-ctl.toml and a comment)."""
    doc = ctx["doc"]
    L: list[str] = []
    w = L.append
    w('"""vss_ctl.py -- GENERATED by sdv/vss/generate.py from overlay-ctl.vspec and profiles-ctl.toml. Do not edit; never')
    w("commit (sdv-out/ is ignored).")
    w("")
    w("The kind 2 contract for Python (the Phase 8 specification, 2.4), loaded by path (sdv/ctl/ctlframe.py's loader):")
    w("the same slot UIDs, digest, constants and compiled profiles as vss_ctl.h, plus every profile of profiles-ctl.toml")
    w("with its run window. Every number is a parameter READ from the planning stack's configuration or a design value;")
    w("none is a measurement.")
    w('"""')
    w("")
    w("FORMAT = %d" % CTL_FORMAT)
    w("")
    w("# The seven kind 2 slots, in slot order (payload offsets: the Phase 8 specification, 2.2).")
    w("SLOT_PATHS = %s" % py(tuple(ctx["slot_paths"])))
    w("SLOT_UIDS = (%s)" % ", ".join("0x%08X" % u for u in ctx["slot_uids"]))
    w("# FNV-1 32 over SLOT_UIDS, each as four little-endian bytes, in slot order.")
    w("DIGEST = 0x%08X" % ctx["digest"])
    w("")
    w("DT_MAX_MS = %d" % doc["dt_max_ms"])
    w("TOL17 = %r" % float(doc["tol17"]))
    w("OVERSPEED_FACTOR = %r" % float(doc["overspeed_factor"]))
    w("OVERSPEED_MARGIN = %r" % float(doc["overspeed_margin"]))
    w("ROLLBACK_V = %r" % float(doc["rollback_v"]))
    w("")
    w("# Every profile of profiles-ctl.toml, by id; COMPILED_PROFILE_IDS are the ones in vss_ctl.h. A profile with")
    w("# stand-in values is never compiled.")
    w("PROFILES = {")
    for p in sorted(doc["profiles"], key=lambda q: q["id"]):
        row = dict({k: float(p[k]) for k in CTL_LIMITS}, l_mm=p["l_mm"], run_window_max_ms=p.get("run_window_max_ms"),
                   compiled=p["compiled"])
        w("    # profile %d: source %s; stand-in: %s" % (p["id"], p["source"], ", ".join(p.get("stand_in", [])) or "none"))
        w("    %d: %s," % (p["id"], py(row)))
    w("}")
    w("COMPILED_PROFILE_IDS = %s" % py(tuple(p["id"] for p in ctl_compiled_profiles(doc))))
    w("")
    return "\n".join(L)


# ================================================================ I/O

def _yaml():
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        raise Refusal("PyYAML is missing: run generate.py with ~/sdv-venv/bin/python (README.md)") from None
    return yaml


def load_yaml(path):
    yaml = _yaml()
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))


def fetch_archive(dest):
    if "/archive/refs/tags/" not in ARCHIVE_URL or "/releases/" in ARCHIVE_URL:
        raise Refusal("the build input is the source-tag archive, never a release attachment")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    print("generate.py: fetching %s" % ARCHIVE_URL)
    req = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "sdv-vss-generate"})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(part, dest)


def verify_archive(path):
    """sha256 first (nothing is opened before it matches), then the commit git archive recorded."""
    got = sha256_file(path)
    if got != ARCHIVE_SHA256:
        raise Refusal("sha256 mismatch for %s: got %s, pinned %s. Nothing was extracted; inspect or remove the file."
                      % (path.name, got, ARCHIVE_SHA256))
    with tarfile.open(path, "r:gz") as tf:
        commit = tf.pax_headers.get("comment")
        names = tf.getnames()
    if commit != ARCHIVE_COMMIT:
        raise Refusal("%s: embedded commit %r, pinned %s" % (path.name, commit, ARCHIVE_COMMIT))
    return names


def extract_spec(archive, dest):
    prefix = ARCHIVE_ROOT + "/spec"
    with tarfile.open(archive, "r:gz") as tf:
        members = [m for m in tf.getmembers() if m.name == prefix or m.name.startswith(prefix + "/")]
        for m in members:
            if not (m.isfile() or m.isdir()) or m.name.startswith("/") or ".." in Path(m.name).parts:
                raise Refusal("archive member %s is not a plain file or directory under %s" % (m.name, prefix))
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, members=members, filter="data")
        else:  # pragma: no cover - Python without extraction filters
            tf.extractall(dest, members=members)
    spec = dest / prefix
    for name, want in (("units.yaml", UNITS_SHA256), ("quantities.yaml", QUANTITIES_SHA256)):
        got = sha256_file(spec / name)
        if got != want:
            raise Refusal("spec/%s: sha256 %s, pinned %s" % (name, got, want))
    return spec


def read_lock(path):
    pins = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", line)
        if m:
            pins[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return pins


_DISTS = ("import importlib.metadata as m, json, re; "
          "print(json.dumps(sorted([re.sub(r'[-_.]+', '-', d.metadata['Name']).lower(), d.version] for d in m.distributions())))")


def check_venv(venv, lock):
    vspec, python = venv / "bin" / "vspec", venv / "bin" / "python"
    if not vspec.exists() or not python.exists():
        raise Refusal("no vss-tools venv at %s: build it from requirements.lock (README.md)" % venv)
    out = subprocess.run([str(python), "-c", _DISTS], capture_output=True, text=True)
    if out.returncode != 0:
        raise Refusal("cannot list the venv's packages: %s" % out.stderr.strip()[-500:])
    installed = {n: v for n, v in json.loads(out.stdout)}
    pins = read_lock(lock)
    wrong = ["%s==%s (installed %s)" % (n, v, installed.get(n, "none")) for n, v in sorted(pins.items()) if installed.get(n) != v]
    if wrong:
        raise Refusal("the venv differs from requirements.lock: " + ", ".join(wrong))
    if installed.get("vss-tools") != VSS_TOOLS_VERSION:
        raise Refusal("vss-tools %s installed, %s pinned" % (installed.get("vss-tools"), VSS_TOOLS_VERSION))
    return vspec, sorted("%s==%s" % (n, pins[n]) for n in pins)


_LEVEL = re.compile(r"\b(WARNING|ERROR|CRITICAL)\b")


def run_vspec(vspec, args, cwd, what, allow_warnings=False):
    env = dict(os.environ, COLUMNS="4000", TERM="dumb", NO_COLOR="1")
    p = subprocess.run([str(vspec)] + args, cwd=str(cwd), env=env, capture_output=True, text=True)
    log = (p.stdout or "") + (p.stderr or "")
    lines = [" ".join(line.split()) for line in log.splitlines()]
    if p.returncode != 0:
        raise Refusal("vss-tools (%s) exited %d:\n  %s" % (what, p.returncode, "\n  ".join(ln[:300] for ln in lines if ln)[-3000:]))
    bad = [ln for ln in lines if _LEVEL.search(ln)]
    if bad and not allow_warnings:
        raise Refusal("vss-tools (%s) warned under --strict:\n  %s" % (what, "\n  ".join(b[:300] for b in bad[:20])))
    return lines


def validation_lines(lines):
    out = []
    for ln in lines:
        i = ln.find("[Validation]")
        if i >= 0:
            out.append(re.sub(r"\s+\S+\.py:\d+$", "", ln[i:]).strip())
    return out


def write_outputs(out, files):
    """All or nothing: write into a staging directory beside --out, then swap it in."""
    if out.exists():
        extra = sorted(p.name for p in out.iterdir() if p.name not in OUT_FILES + OUT_TOLERATED)
        if extra:
            raise Refusal("%s holds files generate.py did not write (%s); refusing to replace it" % (out, ", ".join(extra)))
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".%s.staging-" % out.name, dir=str(out.parent)))
    try:
        for name, data in files.items():
            (staging / name).write_bytes(data)
        if out.exists():
            old = out.parent / (".%s.old-%d" % (out.name, os.getpid()))
            os.rename(out, old)
            os.rename(staging, out)
            shutil.rmtree(old)
        else:
            os.rename(staging, out)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


# ================================================================ main

def parse_args(argv):
    ap = argparse.ArgumentParser(prog="generate.py", description="Generate the VSS contract of the SDV slice.")
    ap.add_argument("--out", type=Path, default=REPO / "sdv-out" / "gen")
    ap.add_argument("--cache", type=Path, default=Path("~/sdv-cache").expanduser())
    ap.add_argument("--venv", type=Path, default=Path("~/sdv-venv").expanduser())
    ap.add_argument("--archive", type=Path, help="use this archive instead of the cached download (still sha256-checked)")
    ap.add_argument("--overlay", type=Path, default=HERE / "overlay.vspec")
    ap.add_argument("--profiles", type=Path, default=HERE / "profiles.toml")
    ap.add_argument("--dbc", type=Path, default=HERE / "slice.dbc")
    ap.add_argument("--lock", type=Path, default=HERE / "requirements.lock")
    ap.add_argument("--overlay-ctl", type=Path, default=HERE / CTL_OVERLAY, help="the ControlCommand layer (Phase 8)")
    ap.add_argument("--units-project", type=Path, default=HERE / CTL_UNITS_FILE)
    ap.add_argument("--quantities-project", type=Path, default=HERE / CTL_QUANTITIES_FILE)
    ap.add_argument("--profiles-ctl", type=Path, default=HERE / CTL_PROFILES_FILE, help="the kind 2 profile table (Phase 8)")
    ap.add_argument("--project-branch", default=DEFAULT_BRANCH, help="the project branch's name under Vehicle (default %(default)s)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--previous-ids", type=Path, help="the id output to check staticUIDs against (default: --out's vss-ids.vspec, if any)")
    g.add_argument("--no-previous", action="store_true", help="do not check staticUIDs against a previous generation")
    ap.add_argument("--uid-baseline", type=Path, default=HERE / BASELINE_NAME,
                    help="the committed staticUID baseline every generation is checked against (default %(default)s)")
    ap.add_argument("--accept-uid-change", action="store_true",
                    help="accept a drift of the staticUIDs from the previous generation and from the baseline, and rewrite the baseline "
                         "(also creates a missing one)")
    return ap.parse_args(argv)


def generate(a):
    notes = []
    branch = a.project_branch
    if not re.match(r"^[A-Z][A-Za-z0-9]*$", branch):
        raise Refusal("--project-branch must be one CamelCase name, got %r" % branch)
    inputs = {"overlay.vspec": a.overlay, "profiles.toml": a.profiles, "slice.dbc": a.dbc, "requirements.lock": a.lock,
              CTL_OVERLAY: a.overlay_ctl, CTL_UNITS_FILE: a.units_project, CTL_QUANTITIES_FILE: a.quantities_project,
              CTL_PROFILES_FILE: a.profiles_ctl}
    for label, path in inputs.items():
        if not path.is_file():
            raise Refusal("%s not found at %s" % (label, path))

    # 1. The archive: sha256 and commit before anything else reads it.
    archive = a.archive or (a.cache / ARCHIVE_NAME)
    if a.archive is None and not archive.exists():
        fetch_archive(archive)
    names = verify_archive(archive)
    fidl = fidl_names(list(names) + [str(p) for p in inputs.values()])
    if fidl:
        raise Refusal("a .fidl file among the inputs: %s" % ", ".join(fidl))

    # The profile file against its invariants: they need no catalogue, so a refused file costs no vss-tools run.
    # derive() checks them again in step 7 together with the rule-26 margins, which need the slots' DBC signals from
    # the generated mapping.
    dbc = parse_dbc(a.dbc.read_text(encoding="utf-8"))
    doc = load_toml(a.profiles)
    problems = check_profiles(doc, dbc)
    if problems:
        raise Refusal("profiles.toml: " + "; ".join(problems))
    # The kind 2 profile file against its refusals (Phase 8 specification 2.3), as early and for the same reason.
    ctl_doc = load_toml(a.profiles_ctl, CTL_PROFILES_FILE)
    problems = check_ctl_profiles(ctl_doc)
    if problems:
        raise Refusal("profiles-ctl.toml: " + "; ".join(problems))

    # 2. The tools.
    vspec, venv_pins = check_venv(a.venv, a.lock)

    # 3. The previous generation, read before anything is written.
    previous_path = None
    if not a.no_previous:
        previous_path = a.previous_ids or (a.out / "vss-ids.vspec")
        if a.previous_ids is None and not previous_path.exists():
            previous_path = None
        elif not previous_path.exists():
            raise Refusal("--previous-ids %s not found" % previous_path)

    overlay = load_yaml(a.overlay)
    if not isinstance(overlay, dict):
        raise Refusal("overlay.vspec is not a mapping of node paths")
    overlay_ctl = load_yaml(a.overlay_ctl)
    if not isinstance(overlay_ctl, dict):
        raise Refusal("%s is not a mapping of node paths" % CTL_OVERLAY)
    run_layers = vehicle_layers(doc)
    layer = run_layers[CATALOGUE_RUN_TYPE]
    layer_texts = {rt: render_vehicle_layer(lay) for rt, lay in run_layers.items()}
    others = [rt for rt in VEHICLE_RUN_TYPES if rt != CATALOGUE_RUN_TYPE]

    a.cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gen-", dir=str(a.cache)) as tmp:
        work = Path(tmp)
        spec = extract_spec(archive, work)
        units_text = (spec / "units.yaml").read_text(encoding="utf-8")
        unit_keys = set(re.findall(r"^([^\s#][^:]*):\s*$", units_text, re.M))
        missing_units = [u for u in KIND4_UNITS if u not in unit_keys]
        if missing_units:
            raise Refusal("VSS %s units.yaml lacks units kind 4 needs: %s" % (VSS_VERSION, ", ".join(missing_units)))
        shutil.copyfile(a.overlay, work / "overlay.vspec")
        shutil.copyfile(a.overlay_ctl, work / CTL_OVERLAY)
        shutil.copyfile(a.units_project, work / CTL_UNITS_FILE)
        shutil.copyfile(a.quantities_project, work / CTL_QUANTITIES_FILE)
        for rt, lay in run_layers.items():
            (work / lay["file"]).write_bytes(layer_texts[rt].encode("utf-8"))
        rel = ARCHIVE_ROOT + "/"
        root = ["-s", rel + "spec/VehicleSignalSpecification.vspec", "-u", rel + "spec/units.yaml", "-q", rel + "spec/quantities.yaml"]
        # The ControlCommand layer's exports load the project unit and quantity files after the stock ones (D5).
        ctl_root = ["-s", rel + "spec/VehicleSignalSpecification.vspec", "-u", rel + "spec/units.yaml", "-u", CTL_UNITS_FILE,
                    "-q", rel + "spec/quantities.yaml", "-q", CTL_QUANTITIES_FILE]
        ext = []
        for e in EXTENDED_ATTRIBUTES:
            ext += ["-e", e]
        case = ["--case-sensitive"] if CASE_SENSITIVE else []

        def with_layer(rt):
            # The overlay first, then the vehicle layer (overlay.vspec BUILD): a later -l wins on the node they share.
            return ["-l", "overlay.vspec", "-l", run_layers[rt]["file"]]

        def with_ctl_layer(rt):
            # overlay-ctl.vspec attaches under the branch overlay.vspec defines, so it follows it (its BUILD block).
            return ["-l", "overlay.vspec", "-l", CTL_OVERLAY, "-l", run_layers[rt]["file"]]

        layers = with_layer(CATALOGUE_RUN_TYPE)
        cmd_ids = ["export", "id"] + root + layers + ext + ["--strict"] + case + ["-o", "vss-ids.vspec"]
        cmd_json = ["export", "json"] + root + layers + ext + ["--strict", "--pretty", "-o", "vss-can-mapping.json"]
        cmd_stock = ["export", "id"] + root + ["--strict"] + case + ["-o", "stock-ids.vspec"]
        run_vspec(vspec, cmd_ids, work, "id export")
        run_vspec(vspec, cmd_json, work, "json export")
        run_vspec(vspec, cmd_stock, work, "stock id export")
        # The same two exports with the ControlCommand layer: the kind 2 slots' UIDs and the databroker catalogue.
        ctl_layers = with_ctl_layer(CATALOGUE_RUN_TYPE)
        cmd_ctl_ids = ["export", "id"] + ctl_root + ctl_layers + ext + ["--strict"] + case + ["-o", "vss-ids-ctl.vspec"]
        cmd_ctl_json = ["export", "json"] + ctl_root + ctl_layers + ext + ["--strict", "--pretty", "-o", "vss-json-ctl.json"]
        run_vspec(vspec, cmd_ctl_ids, work, "ctl id export")
        run_vspec(vspec, cmd_ctl_json, work, "ctl json export")
        # Every other run type's layer: the same id and json exports with its layer instead (and the ControlCommand
        # layer, which its databroker catalogue serves too), for its own vehicle_layer_problems() and that catalogue.
        cmd_others = []
        for rt in others:
            cmd_rt = (["export", "id"] + ctl_root + with_ctl_layer(rt) + ext + ["--strict"] + case + ["-o", "vss-ids-%s.vspec" % rt],
                      ["export", "json"] + ctl_root + with_ctl_layer(rt) + ext + ["--strict", "--pretty", "-o", "vss-can-mapping-%s.json" % rt])
            run_vspec(vspec, cmd_rt[0], work, "%s id export" % rt)
            run_vspec(vspec, cmd_rt[1], work, "%s json export" % rt)
            cmd_others += cmd_rt
        validation = []
        if previous_path is not None:
            shutil.copyfile(previous_path, work / "previous-ids.vspec")
            cmd_val = (["export", "id"] + root + layers + ext + ["-e", "staticUID", "--strict"] + case
                       + ["--validate-static-uid", "previous-ids.vspec", "--validate-only", "-o", "unused.vspec"])
            validation = validation_lines(run_vspec(vspec, cmd_val, work, "static-UID validation", allow_warnings=True))

        ids_bytes = (work / "vss-ids.vspec").read_bytes()
        mapping_bytes = (work / "vss-can-mapping.json").read_bytes()
        ids = load_yaml(work / "vss-ids.vspec")
        ids_ctl = load_yaml(work / "vss-ids-ctl.vspec")
        ctl_tree = json.loads((work / "vss-json-ctl.json").read_text(encoding="utf-8"))
        stock = load_yaml(work / "stock-ids.vspec")
        previous = load_yaml(work / "previous-ids.vspec") if previous_path is not None else None
        other_ids = {rt: load_yaml(work / ("vss-ids-%s.vspec" % rt)) for rt in others}
        other_trees = {rt: json.loads((work / ("vss-can-mapping-%s.json" % rt)).read_text(encoding="utf-8")) for rt in others}

    # 4. The catalogue.
    for path, node in ids.items():
        parse_uid(node.get("staticUID"), " at %s" % path)
    for path, node in ids_ctl.items():
        parse_uid(node.get("staticUID"), " at %s (the ctl id export)" % path)
    mapping_tree = json.loads(mapping_bytes.decode("utf-8"))
    mapping = json_nodes(mapping_tree)
    # The vehicle layer's own check first, so its refusal names the layer; the stock comparison below
    # would also see a moved Wheelbase UID, without saying which input moved it.
    problems = vehicle_layer_problems(layer, stock, ids, mapping)
    for rt in others:
        problems += vehicle_layer_problems(run_layers[rt], stock, other_ids[rt], json_nodes(other_trees[rt]))
    problems += stock_differences(stock, ids, branch)
    if set(mapping) != set(ids):
        problems.append("the mapping JSON and the id output list different nodes (%d vs %d)" % (len(mapping), len(ids)))
    problems += overlay_differences(overlay, ids, mapping)
    problems += ctl_layer_problems(ids, ids_ctl, overlay_ctl, ctl_tree, mapping_tree, branch)
    problems += dbc_signal_problems(mapping, dbc)
    problems += speed_problems(ids)
    if problems:
        raise Refusal("the generated catalogue fails its checks:\n  " + "\n  ".join(problems[:40]))

    # 5. The slots and the digest.
    paths = slot_paths(branch)
    nodes, uids, signals, dbc_units = [], [], [], []
    for i, (path, (_p, vtype, datatype)) in enumerate(zip(paths, SLOTS)):
        if path not in ids:
            raise Refusal("slot %d: %s is not in the generated catalogue" % (i, path))
        n = ids[path]
        if n.get("type") != vtype or n.get("datatype") != datatype:
            raise Refusal("slot %d: %s is %s %s, the wire needs %s %s" % (i, path, n.get("type"), n.get("datatype"), vtype, datatype))
        m = mapping[path].get("dbc2vss") or {}
        if "signal" not in m:
            raise Refusal("slot %d: %s has no dbc2vss signal" % (i, path))
        nodes.append({k: n[k] for k in ("type", "datatype", "unit") if k in n})
        uids.append(parse_uid(n["staticUID"], " at slot %d" % i))
        signals.append(m["signal"])
        s = dbc["messages"][dbc["signal_message"][m["signal"]]]["signals"][m["signal"]]
        dbc_units.append(s["unit"] or None)
    digest = check_digest(catalog_digest(uids))
    # The kind 2 slots, from the id export with the ControlCommand layer, as kind 4's from vss-ids.vspec.
    ctl_paths = ctl_slot_paths(branch)
    ctl_nodes, ctl_uids = [], []
    for i, (path, (_p, vtype, datatype)) in enumerate(zip(ctl_paths, CTL_SLOTS)):
        if path not in ids_ctl:
            raise Refusal("kind 2 slot %d: %s is not in the generated catalogue" % (i, path))
        n = ids_ctl[path]
        if n.get("type") != vtype or n.get("datatype") != datatype:
            raise Refusal("kind 2 slot %d: %s is %s %s, the wire needs %s %s" % (i, path, n.get("type"), n.get("datatype"), vtype, datatype))
        ctl_nodes.append({k: n[k] for k in ("type", "datatype", "unit") if k in n})
        ctl_uids.append(parse_uid(n["staticUID"], " at kind 2 slot %d" % i))
    ctl_dig = check_digest(ctl_digest(ctl_uids), "kind 2 digest")
    notes.append("kind 2 digest 0x%08X (%s)" % (ctl_dig, ", ".join(CTL_FILES)))

    # 6. Against the previous generation and against the committed baseline. Both are read before
    # anything is written, and every source of drift is reported together.
    drift = []
    if previous is not None:
        changed, removed, added = uid_changes(previous, ids)
        flagged = [v for v in validation if any(k in v for k in VALIDATION_REFUSE)]
        lines = previous_drift(changed, removed, flagged)
        if lines:
            drift.append("staticUIDs moved since the previous generation (%s):\n  %s" % (previous_path, "\n  ".join(first_lines(lines))))
        notes.append("previous generation %s: %d changed, %d removed, %d added; vss-tools validation: %d line(s)%s"
                     % (previous_path, len(changed), len(removed), len(added), len(validation), " (accepted)" if lines else ""))
        for v in validation[:20]:
            notes.append("  " + v)
    else:
        notes.append("no previous generation to check staticUIDs against")
    # The baseline's nodes come from the id export with the ControlCommand layer: the layer's nodes are the project branch's.
    scope = {p: parse_uid(ids_ctl[p]["staticUID"], " at %s" % p) for p in baseline_paths(ids_ctl, branch)}
    baseline = parse_baseline(a.uid_baseline.read_text(encoding="utf-8")) if a.uid_baseline.is_file() else None
    if baseline is None:
        baseline_lines = ["no UID baseline at %s" % a.uid_baseline]
    else:
        baseline_lines = baseline_drift(baseline, digest, scope)
    if baseline_lines:
        drift.append("staticUIDs differ from the committed baseline (%s):\n  %s" % (a.uid_baseline, "\n  ".join(first_lines(baseline_lines))))
    if drift and not a.accept_uid_change:
        raise Refusal("\n".join(drift) + "\nrerun with --accept-uid-change if intended; it also rewrites (or creates) the baseline")
    notes.append("baseline %s: %d node(s), %s" % (a.uid_baseline.name, len(scope), "rewritten (accepted)" if baseline_lines else "unchanged"))

    # 7. Profiles and derived constants.
    derived = derive(doc, dbc, signals)

    ctx = {"branch": branch, "slot_paths": paths, "slot_nodes": nodes, "slot_uids": uids, "digest": digest,
           "slot_signals": signals, "slot_dbc_units": dbc_units, "profiles_doc": doc, "derived": derived}
    ctl_ctx = {"slot_paths": ctl_paths, "slot_nodes": ctl_nodes, "slot_uids": ctl_uids, "digest": ctl_dig, "doc": ctl_doc}
    # The databroker catalogue is the JSON export with the ControlCommand layer (it serves those nodes), less dbc2vss.
    databroker = json.dumps(strip_key(ctl_tree, "dbc2vss"), indent=2, sort_keys=True).encode("utf-8")
    files = {
        "vss-ids.vspec": ids_bytes,
        "vss-can-mapping.json": mapping_bytes,
        DATABROKER_CATALOGUES[CATALOGUE_RUN_TYPE]: databroker,
        layer["file"]: layer_texts[CATALOGUE_RUN_TYPE].encode("utf-8"),
        "vss_contract.h": render_c_contract(ctx).encode("utf-8"),
        "vss_profiles.h": render_c_profiles(ctx).encode("utf-8"),
        "vss_contract.py": render_python(ctx).encode("utf-8"),
        "vss_ctl.h": render_c_ctl(ctl_ctx).encode("utf-8"),
        "vss_ctl.py": render_python_ctl(ctl_ctx).encode("utf-8"),
    }
    for rt in others:
        files[DATABROKER_CATALOGUES[rt]] = json.dumps(strip_key(other_trees[rt], "dbc2vss"), indent=2, sort_keys=True).encode("utf-8")
        files[run_layers[rt]["file"]] = layer_texts[rt].encode("utf-8")
    manifest = {
        "format": FORMAT,
        "generator": "sdv/vss/generate.py",
        "vss": {"tag": VSS_TAG, "version": VSS_VERSION, "archive": ARCHIVE_NAME, "archive_url": ARCHIVE_URL,
                "archive_sha256": ARCHIVE_SHA256, "commit": ARCHIVE_COMMIT,
                "units_sha256": UNITS_SHA256, "quantities_sha256": QUANTITIES_SHA256},
        "vss_tools": {"version": VSS_TOOLS_VERSION, "wheel_sha256": VSS_TOOLS_WHEEL_SHA256, "strict": True,
                      "uid_case_sensitive": CASE_SENSITIVE, "extended_attributes": list(EXTENDED_ATTRIBUTES),
                      "units": ["<v6.0>/spec/units.yaml"], "quantities": ["<v6.0>/spec/quantities.yaml"],
                      "overlays": ["overlay.vspec", layer["file"]],
                      # The ControlCommand layer's exports: which files they make and which they never touch.
                      "ctl_layer": {"overlay": CTL_OVERLAY, "units": ["<v6.0>/spec/units.yaml", CTL_UNITS_FILE],
                                    "quantities": ["<v6.0>/spec/quantities.yaml", CTL_QUANTITIES_FILE],
                                    "loaded_for": [DATABROKER_CATALOGUES[rt] for rt in VEHICLE_RUN_TYPES] + list(CTL_FILES)
                                    + [BASELINE_NAME],
                                    "not_loaded_for": ["vss-ids.vspec", "vss-can-mapping.json"]}},
        # Generated from profiles.toml (an input above), so it is an output, not an input: its sha256 is in
        # outputs, and the run header's catalogue.vehicle_layer_sha256 records it. vehicle_layer is the sigsim
        # layer's object as it was when a generation had one layer (the stack reads it); vehicle_layers has every
        # run type's, databroker_catalogues each run type's catalogue.
        "vehicle_layer": {k: layer[k] for k in LAYER_KEYS},
        "vehicle_layers": {rt: {k: run_layers[rt][k] for k in LAYER_KEYS} for rt in VEHICLE_RUN_TYPES},
        "databroker_catalogues": {rt: DATABROKER_CATALOGUES[rt] for rt in VEHICLE_RUN_TYPES},
        "venv": venv_pins,
        "inputs": dict(sorted([(label, sha256_file(path)) for label, path in inputs.items()]
                              + [("generate.py", sha256_file(Path(__file__).resolve()))])),
        "project_branch": branch_path(branch),
        "commands": ["vspec " + " ".join(c).replace(rel, "<v6.0>/")
                     for c in [cmd_ids, cmd_json, cmd_stock, cmd_ctl_ids, cmd_ctl_json] + cmd_others],
        "kind4": {"slots": [{"slot": i, "path": p, "staticUID": "0x%08X" % u, "dbc_signal": s}
                            for i, (p, u, s) in enumerate(zip(paths, uids, signals))],
                  "catalog_digest": "0x%08X" % digest, "kind4_units_in_stock_units_yaml": list(KIND4_UNITS)},
        # The kind 2 contract (Phase 8 specification 2.2), in exactly this shape; its two files are in outputs.
        "ctl_contract": {"format": CTL_FORMAT, "digest": "0x%08X" % ctl_dig, "files": list(CTL_FILES),
                         "profiles_ctl_sha256": sha256_file(a.profiles_ctl)},
        "checks": ["archive sha256 and embedded commit", "units.yaml and quantities.yaml sha256", "no .fidl input",
                   "venv equals requirements.lock", "vss-tools --strict without warnings",
                   "every staticUID matches ^0x[0-9A-F]{8}$", "standard nodes' UIDs equal the overlay-free build except Vehicle.Speed",
                   "added nodes only under the project branch", "overlay entries reach the catalogue as written",
                   "mapping JSON and id output list the same nodes", "every dbc2vss signal is in slice.dbc",
                   "Vehicle.Speed is a sensor, float, km/h with min 0",
                   "each run type's vehicle layer sets Vehicle.Chassis.Wheelbase's default to its profile's L and moves no "
                   "staticUID, on its own exports",
                   "slots are sensors of the wire's datatypes", "digest is neither 0x00000000 nor 0xFFFFFFFF",
                   "staticUIDs unchanged against the previous generation (when there is one)",
                   "slot and project-branch staticUIDs and the digest equal the committed baseline (rewritten only under --accept-uid-change)",
                   "profiles.toml against the spec 5.4 bounds (constants of generate.py) and its invariants", "derived constants defined",
                   "every profile's rule-26 budget keeps its envelope's margin_target over tol",
                   "no compiled profile on an envelope that holds a stand-in row; a skew_ms row only on a planning-sim envelope",
                   "profiles-ctl.toml against its refusals (Phase 8 specification 2.3; the bounds are constants of generate.py)",
                   "the ControlCommand layer adds its own entries under the project branch's ControlCommand alone, moves no other "
                   "node, carries no dbc2vss block and reaches the catalogue as written",
                   "kind 2 slots are sensors of the wire's datatypes", "the kind 2 digest is neither 0x00000000 nor 0xFFFFFFFF"],
        "outputs": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in sorted(files.items())},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    write_outputs(a.out, files)
    if baseline_lines:          # only reached under --accept-uid-change; a refusal above wrote nothing at all
        write_baseline(a.uid_baseline, render_baseline(digest, scope))
    return digest, files, notes


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        digest, files, notes = generate(a)
    except Refusal as e:
        print("generate.py: REFUSED: %s" % e, file=sys.stderr)
        return 1
    print("generate.py: VSS %s (commit %s), vss-tools %s, staticUIDs %s"
          % (VSS_TAG, ARCHIVE_COMMIT, VSS_TOOLS_VERSION, "case-sensitive" if CASE_SENSITIVE else "case-insensitive"))
    for n in notes:
        print("generate.py: " + n)
    print("generate.py: kind 4 catalogue digest 0x%08X" % digest)
    for name in OUT_FILES:
        print("generate.py: wrote %s (%d bytes)" % (a.out / name, len(files[name])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
