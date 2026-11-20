#!/usr/bin/env python3
"""fleet.py -- two or three simulated cars replayed at once on the PC, one stack instance a car (video 3's fleet, package P1).

Runs in WSL Ubuntu-24.04 with the sim venv's Python, from the repo root:

    ~/sdv-sim-venv/bin/python sdv/stack/fleet.py check --car A=REC_DIR --car B=REC_DIR [--car C=REC_DIR]
    SDV_CONNECTOR_IMAGE=<id> SDV_DEVICE_DIR_A=<dir> SDV_DEVICE_DIR_B=<dir> [SDV_DEVICE_DIR_C=<dir>] \\
      ~/sdv-sim-venv/bin/python sdv/stack/fleet.py run --name NAME --car A=REC_DIR --car B=REC_DIR [--car C=REC_DIR]

Standard library only, beside stack.py, which it imports and whose rules it calls: recording_identity, resolve_dbc, the
generation's pair and catalogue identity, the decoder (replaycheck.decode_recording with the generated mapping), the
device directory's rule (device_dir), connector_part's startstamp.py and limits.py, host_listeners and replay_gates. It
re-implements none of them.

THE CARS  Two or three, labelled A, B and C in that order; car A is stack instance 1, B 2, C 3 (stack.py's module docstring,
  INSTANCE: its own container names, vcanf<k>, its own databroker and mock provider ports, its containers' own label).

CHECK  writes nothing. For each car: the recording as the stack identifies it (its manifest line, its log's two hashes), its
  DBC from the cache (a DBC that is not there is refused without the cache being touched), a run type the stack takes (the
  generation's pair for it, and a generation made from the recording's DBC and the overlay as it is now); moves: the
  stack's V_PATH decoded from the log as the stack decodes it, its first and its last sample with |v| > 0.1 m/s
  (trip_summary.py's rule) at least MIN_MOVING_S apart by the log's own times; distinct: the recording's sha256 is no other
  car's. One line a car, `<label> <recording name> <run type> moves: yes|no distinct: yes|no`, and no other value. Exit 0
  when every car moves and all are distinct, 1 otherwise, 2 for a command line or a recording the stack refuses (nothing on
  stdout then).

RUN  Refused (exit 2, before anything is written, made or started; each refusal names the variable or the car, never a
  value): SDV_STACK_INSTANCE, SDV_STACK_FEED_GATE, SDV_DEVICE_DIR, SDV_SPOOL_DIR or SDV_STATUS_DIR in its own environment
  (set at all); a NAME that is not one word of [A-Za-z0-9._-] beginning with a letter or a digit; a car check would not
  pass; a car whose bound on its player the stack refuses (stack.py's player_bound_s for the car's own log: a bound over
  PLAYER_BOUND_MAX_S, no frame, not in time order, unreadable), or whose log (its first to its last frame, as the stack
  decodes it) ends less than PLAYER_MARGIN_S inside that bound, or past it (such a replay would end at the bound, not at
  the log's end); SDV_CONNECTOR_IMAGE unset or empty, or an image the stack's own rule refuses (connector_image:
  an ID sha256:<64 hex>, in the store, of this generation, not root; the ID is never printed); SDV_HOST_ROLE other than pc
  (host_role's); a car's SDV_DEVICE_DIR_<L> unset, or one the stack's device directory rule refuses (not absolute, not a
  directory, inside the repo, no connector.env), or whose connector.env sets SDV_TWIN_DATABROKER (the stack sets each car's
  own) or names no SDV_TWIN_THING; two cars with one device directory, or with one SDV_TWIN_THING (compared, never printed);
  the state directory inside the repo; the run directory SDV_RUNS/<YYYYMMDD>-<NAME> inside the repo, or existing; any
  car's identity stamp inside START_SPACING_S, from the future, no stamp or unreadable (read by startstamp.py's own parse;
  the fleet writes no car's stamp, so the refusal names the file under SDV_STATE to remove); docker unable to list the
  containers, or ss the listeners; any container labelled sdv.stack.run; an instance's databroker or mock provider port
  already listened on (TCP); last, the fleet stamp, by startstamp.mark itself (step 1): inside START_SPACING_S or
  unwritable it refuses and leaves the stamp, no stamp or from the future it refuses once and writes it anew, so those
  refusals end. Not checked here: sudo -n for a car's vcanf<k> (the stack needs it only when the interface is not there
  yet), so a car whose stack refuses that ends before its ready, after the fleet stamp is marked.
  Then, in order:
  1. the fleet stamp, <STATE>/fleet/started.json, through startstamp.mark: one fleet start per START_SPACING_S;
  2. one car process at a time, in a process group of its own, `stack.py replay --name <NAME>-<L> --feed vcan --bridge none
     --connector`, with SDV_STACK_INSTANCE=<k>, SDV_STACK_FEED_GATE=<run>/gate, SDV_RECORDING, SDV_RUNS=<run>/car-<L>,
     SDV_DEVICE_DIR (the car's), SDV_CONNECTOR_IMAGE and SDV_STATE: car A's the caller's (unset, the stack's default), so car
     A and a one-car run on the same device directory hold each other START_SPACING_S apart; B's and C's
     <STATE>/fleet/car-<L>, each its own stack stamp. The five refused variables and every SDV_DEVICE_DIR_<L> are not in its
     environment. Its stdout and stderr go to <run>/car-<L>/stack.log with every device directory's path, the names of the
     files in it and the values of its connector.env masked (SDV_TWIN_THING's, SDV_TWIN_ENDPOINT's and SDV_TWIN_RULE's
     whatever their length, every other one of MASK_MIN characters or more; a NAME line alone by the value docker passes
     through, the fleet's own). Car k+1 starts only once <run>/gate/ready-<k> exists, so no two prepares overlap;
  3. once every car is ready and, at a last look, none has ended, <run>/gate/go. When a car ends before go, gives no ready
     within GATE_WAIT_S of its start, or the fleet is interrupted (SIGINT, SIGTERM) or fails before go: <run>/gate/abort (its
     reason, in words), no later car started, and one SIGINT to a started car that is not ready yet (it would go on to its
     up(), its connector's start among it; its stack's finally removes what it started); the ready ones end at the gate;
  4. every started car waited for, each bounded by CAR_TIMEOUT_S from its start: past it one SIGINT, so that the stack's
     finally removes its containers; STOP_GRACE_S after the fleet's SIGINT, a SIGKILL to the car's process group (the
     stack and what it started: its player, docker's clients) and its instance's containers removed by the stack's
     instance label (docker rm -f), said on stderr. A SIGINT or SIGTERM to the fleet after go gives every running car one
     SIGINT: each car is in a group of its own, so a terminal's interrupt reaches the fleet alone and no car gets two
     (a second one could cut short the finally that removes its containers). Then <run>/fleet.json, and a failure of the
     fleet's own is raised after it.
  fleet.json: {"v": 1, "fleet", "utc_start", "utc_end", "cars": [{"label", "instance", "recording": {"name", "sha256",
  "run_type"}, "run", "result", "witness", "stack_exit", "ready_ms", "gates", "connector": {"ok", "exit", "exit_means"}}],
  "gate": {"go_ms", "abort"}, "window": {"day", "from_ms", "to_ms", "day_at_stop"}, "ok"}. Every path is relative to the
  run directory: run is car-<L>, result and witness the car's replay's result.json and vss-witness.jsonl (the input to
  trip_summary.py --local), null when there is none. gate.abort is the abort's reason, or after go the interrupt's (no
  abort file then: the cars are past the gate). window means what video 3's window.txt means: the UTC day and the wall
  clock in ms at the fleet's start, and after the last car's exit. ok: no abort, every stack_exit 0, every gate of
  replay_gates true, and none of the masked words anywhere under the run directory (searched after the cars end).
  stdout: per car its label and `gates:` with replay_gates' JSON (null when it has none), then `fleet: ok` or
  `fleet: NOT ok`; the progress goes to stderr, in words. Exit 0 when ok, 1 otherwise, 2 for a refusal.
  The record and everything under the run directory hold no device directory's path, no name of a file in it and no value
  of connector.env.

DESIGN VALUES (none a claim): MIN_MOVING_S (40 s: the fleet's shortest drive moves for longer than
  MIN_MOVING_S, and 40 s still refuses a parked car or a drive that barely moves), GATE_WAIT_S (stack.py's, 600 s), CAR_TIMEOUT_S (1800 s, video 3's
  one-car upload's), STOP_GRACE_S, POLL_S, MASK_MIN, PLAYER_MARGIN_S (10 s: python-can's own start before the log's first
  frame, inside the stack's own PLAYER_HEADROOM_S). While stack.py's PLAYER_HEADROOM_S is larger than PLAYER_MARGIN_S, no
  log the stack takes ends less than PLAYER_MARGIN_S inside its bound, so run's refusal of such a car is a guard against
  a later change of the headroom, not a refusal a recording meets.

Does not demonstrate: the cloud (a local broker's ACL is not the cloud's policy, and a certificate there can connect under
another client id); any timing, or that the feeds start at one instant (each starts after the one go); the PC's capacity;
anything about a one-stack run started while a fleet runs, which removes the fleet's containers: the rule is that nothing
else runs. A fleet's cars are recordings replayed together on one PC, not a multi-car simulation.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO, Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import stack  # noqa: E402

STACK_PY = HERE / "stack.py"                  # each car's process (a test points this at a stand-in)
PYTHON = sys.executable                       # the sim venv's, as the fleet runs under it
LABELS = ("A", "B", "C")
MIN_MOVING_S = 40                             # a car moves when its first and last moving samples are this far apart (a design value:
                                              # the fleet's shortest drive moves for longer than MIN_MOVING_S, and 40 s still refuses a
                                              # parked car or a drive that barely moves)
MOVING_MPS = 0.1                              # |v| above this is moving (trip_summary.py's MOVING)
GATE_WAIT_S = stack.GATE_WAIT_S               # how long a car may take from its start to its ready (the stack's own wait for go)
CAR_TIMEOUT_S = 1800.0                        # each car's process, from its start (video 3's one-car upload's bound)
STOP_GRACE_S = 120.0                          # after a SIGINT to a car past its bound, before a SIGKILL
POLL_S = 0.2
MASK_MIN = 6                                  # a connector.env value this long or longer is masked in the cars' logs and searched for
PLAYER_MARGIN_S = 10                          # a log must end this far inside the stack's bound on its player (a design value)
DEVICE_ENV = "SDV_DEVICE_DIR_%s"              # each car's device directory
REFUSED_ENV = (stack.INSTANCE_ENV, stack.FEED_GATE_ENV, stack.DEVICE_DIR_ENV, stack.SPOOL_DIR_ENV, stack.STATUS_DIR_ENV)
THING_ENV, DATABROKER_ENV = "SDV_TWIN_THING", "SDV_TWIN_DATABROKER"        # the connector's names (sdv/connector/connector.py)
IDENTITY_ENV = (THING_ENV, "SDV_TWIN_ENDPOINT", "SDV_TWIN_RULE")           # the identity: masked and searched for whatever their length
NAME_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
REPLAY = "vcan-1"                             # the stack's replay directory for `replay --feed vcan`
EXIT_OK, EXIT_NOT_OK, EXIT_REFUSED = 0, 1, 2


class Refused(Exception):
    """A refusal: exit 2, its words on stderr."""


def say(text: str) -> None:
    print("fleet.py: %s" % text, file=sys.stderr, flush=True)


# --- the cars and check ---------------------------------------------------------------------------------------------------

def parse_cars(words: Sequence[str]) -> List[Tuple[str, Path]]:
    """--car L=REC_DIR, two or three, labelled A, B, C in that order."""
    cars: List[Tuple[str, Path]] = []
    for w in words:
        label, sep, raw = w.partition("=")
        if not sep or not raw:
            raise Refused("--car takes LABEL=REC_DIR: %r is not one" % (label if sep else "a car without ="))
        cars.append((label, Path(os.path.abspath(os.path.expanduser(raw)))))
    labels = tuple(label for label, _rec in cars)
    if labels not in (LABELS[:2], LABELS):
        raise Refused("the cars are two or three, labelled A, B and C in that order: got %s" % (", ".join(labels) or "none"))
    return cars


def moving_span_ms(samples: Sequence[Tuple[int, float]]) -> int:
    """The log's own time between its first and its last sample with |v| > MOVING_MPS, in ms (0 when fewer than two)."""
    moving = [t for t, v in samples if abs(v) > MOVING_MPS]
    return moving[-1] - moving[0] if moving else 0


def check_car(label: str, rec_dir: Path) -> Dict[str, Any]:
    """One car's recording, as the stack takes it: its identity, its DBC from the cache (refused before the cache is
    touched when it is not there), its run type's generation pair and catalogue identity, and its V_PATH samples decoded as
    the stack decodes them, and the log it identified (run's bound reads it, so a recording is identified once). A refusal
    of the stack's is a Refused naming the car."""
    try:
        rec = stack.recording_identity(rec_dir)
        sha = rec["manifest_line"]["source"]["params"]["dbc_sha256"]
        if not (stack.CACHE / "dbc" / ("%s.dbc" % sha)).is_file() and not (stack.CACHE / "dbc").is_dir():
            raise stack.StackError("the recording's DBC (sha256 %s) is not in the cache's dbc directory, which does not exist: export it "
                                   "as `stack.py replay` of this recording says" % sha)
        dbc = stack.resolve_dbc(sha)
        pair = stack.generation_pair(stack.generation_manifest(), rec["run_type"])
        stack.catalogue_identity(stack.load_contract(), dbc["wanted_sha256"], pair)
        mapping = stack.attr.dbc2vss_entries(json.loads((stack.GEN / "vss-can-mapping.json").read_text(encoding="utf-8")))
        transforms = {p: stack.attr.transform_function(b) for p, b in mapping.items()}
        decoded = stack.rc.decode_recording(Path(rec["log"]), Path(dbc["path"]), mapping, transforms)
    except Exception as exc:          # the stack's refusals, and whatever its decoder raises on a log it cannot read
        raise Refused("car %s: the stack refuses its recording: %s" % (label, exc)) from None
    signal_name, tf = mapping[stack.rc.V_PATH]["signal"], transforms[stack.rc.V_PATH]
    samples = [(int(t), float(tf(dec[signal_name]))) for t, _name, dec in decoded["frames"] if signal_name in dec]
    frames = decoded["frames"]
    span_ms = int(frames[-1][0]) - int(frames[0][0]) if frames else 0          # the log's first to its last frame (run's player bound)
    return {"label": label, "dir": rec_dir, "name": rec_dir.name, "sha256": rec["sha256"], "run_type": rec["run_type"], "span_ms": span_ms,
            "log": Path(rec["log"]), "moves": moving_span_ms(samples) >= MIN_MOVING_S * 1000}


def check_cars(cars: Sequence[Tuple[str, Path]]) -> List[Dict[str, Any]]:
    out = [check_car(label, rec) for label, rec in cars]
    for c in out:
        c["distinct"] = [o["sha256"] for o in out].count(c["sha256"]) == 1
    return out


def check_line(c: Dict[str, Any]) -> str:
    return "%s %s %s moves: %s distinct: %s" % (c["label"], c["name"], c["run_type"], "yes" if c["moves"] else "no",
                                                 "yes" if c["distinct"] else "no")


def check_main(a: argparse.Namespace) -> int:
    checked = check_cars(parse_cars(a.car))
    for c in checked:
        print(check_line(c))
    return EXIT_OK if all(c["moves"] and c["distinct"] for c in checked) else EXIT_NOT_OK


# --- run's refusals -------------------------------------------------------------------------------------------------------

def env_file(path: Path) -> Dict[str, Optional[str]]:
    """An --env-file's names and values as docker reads them: a line's leading blanks dropped, empty and # lines skipped,
    NAME=value (the value as written), or NAME alone (passed through from the caller: None). The last line of a name wins."""
    out: Dict[str, Optional[str]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.lstrip()
        if not s or s.startswith("#"):
            continue
        name, sep, value = s.partition("=")
        out[name] = value if sep else None
    return out


def device_of(label: str) -> Tuple[Path, Dict[str, Optional[str]]]:
    """A car's device directory by stack.py's own rule (device_dir, read with SDV_DEVICE_DIR set to the car's for the call
    alone; its words name the car's variable) and its connector.env, which may not set SDV_TWIN_DATABROKER and must name
    SDV_TWIN_THING."""
    var = DEVICE_ENV % label
    raw = os.environ.get(var)
    if not raw:
        raise Refused("car %s: set %s to the car's device directory (an absolute path outside the repo holding connector.env)" % (label, var))
    os.environ[stack.DEVICE_DIR_ENV] = raw
    try:
        d = stack.device_dir()
    except stack.StackError as exc:
        raise Refused("car %s: %s" % (label, str(exc).replace(stack.DEVICE_DIR_ENV, var))) from None
    finally:
        os.environ.pop(stack.DEVICE_DIR_ENV, None)
    try:
        env = env_file(d / stack.CONNECTOR_ENV_FILE)
    except OSError:
        raise Refused("car %s: the %s of %s cannot be read" % (label, stack.CONNECTOR_ENV_FILE, var)) from None
    if DATABROKER_ENV in env:
        raise Refused("car %s: the %s of %s sets %s: the stack gives each car its own databroker, so the device directory names none"
                      % (label, stack.CONNECTOR_ENV_FILE, var, DATABROKER_ENV))
    if not env.get(THING_ENV):
        raise Refused("car %s: the %s of %s names no %s: a car is one device identity" % (label, stack.CONNECTOR_ENV_FILE, var, THING_ENV))
    return d, env


def stamp_reading(directory: Path, now_ms: int) -> Tuple[str, int]:
    """A start stamp in `directory` read now, by startstamp.py's file and parse and limits.py's spacing: ("none", 0) when
    there is none, ("unreadable", 0), ("no stamp", 0), ("from the future", 0), ("spacing", the seconds left), or
    ("passes", 0)."""
    ss, limits = stack.connector_part("startstamp"), stack.connector_part("limits")
    try:
        data = (directory / ss.FILE).read_bytes()
    except FileNotFoundError:
        return "none", 0
    except OSError:
        return "unreadable", 0
    previous = ss.parse(data)
    if previous is None:
        return "no stamp", 0
    if now_ms < previous:
        return "from the future", 0
    left = limits.START_SPACING_S * 1000 - (now_ms - previous)
    if left > 0:
        return "spacing", -(-left // 1000)
    return "passes", 0


def stamp_place(directory: Path) -> str:
    """A stamp's place as a refusal names it: under the state directory, by its variable, never by its path."""
    place = Path(os.path.abspath(str(directory))).relative_to(os.path.abspath(str(stack.STATE))).as_posix()
    return "%s/%s under %s" % (place, stack.connector_part("startstamp").FILE, stack.STATE_ENV)


def mark_refusal(why: str, retry_after_s: Optional[float]) -> str:
    """The words for startstamp.mark's refusal of the fleet's own stamp. Its rows: a stamp from the future or one that is no
    stamp is written anew with this moment, so those refusals end START_SPACING_S from now."""
    place = stamp_place(stack.STATE / "fleet")
    if why in ("clock", "stamp"):
        return ("the fleet: its start stamp (%s) was %s: startstamp.mark refuses this start once, and the stamp is written anew, so "
                "a fleet starts again START_SPACING_S from now" % (place, "from the future" if why == "clock" else "no stamp"))
    if why == "spacing":
        left = -(-(retry_after_s or 0) // 1)
        return "the fleet: its start stamp is inside the start spacing: wait %d s (a fleet starts once per START_SPACING_S)" % left
    return "the fleet: its start stamp (%s) cannot be read or written: nothing is written over it, take it away" % place


def car_state(label: str) -> Optional[Path]:
    """A car's SDV_STATE: car A's the caller's (None: left as it is, the stack's default when unset), B's and C's their own."""
    return None if label == "A" else Path(os.path.abspath(str(stack.STATE / "fleet" / ("car-%s" % label))))


def identity_stamp_dir(label: str) -> Path:
    """Where a car's stack keeps its connector start stamp: stack.py's connector_state_dir under the car's state directory."""
    rel = stack.connector_state_dir(make=False).relative_to(stack.STATE)
    state = car_state(label)
    return (stack.STATE if state is None else state) / rel


def run_dir_of(name: str) -> Path:
    """SDV_RUNS/<YYYYMMDD>-<NAME>, the local date as stack.py's new_run_dir names a run."""
    return Path(os.path.abspath(str(stack.RUNS / ("%s-%s" % (datetime.datetime.now().strftime("%Y%m%d"), name)))))


def player_bound_s(rec_dir: Path) -> int:
    """The stack's bound on the player of one car's recording, in seconds: stack.py's player_bound_s for the log the stack
    identifies it by (recording_identity's). A StackError when the stack refuses it. For a caller outside run (the opt-in
    broker test's guard): run reads the same bound from the log check_car identified, so it identifies no recording twice."""
    return stack.player_bound_s(Path(stack.recording_identity(rec_dir)["log"]))


def image_and_role_refusal() -> None:
    """The connector image by the stack's own rule (connector_image: an ID in the store, of this generation, not root; the
    ID masked in its words) and the host role by its own (host_role: pc), before anything is written, so that no stamp holds
    a retry back. A refusal names the variable, never its value."""
    ref = os.environ.get(stack.CONNECTOR_IMAGE_ENV, "")
    try:
        stack.connector_image()
    except stack.StackError as exc:
        words = str(exc).replace(repr(ref), "<its value>")
        raise Refused("%s: the stack refuses the image it names: %s" % (stack.CONNECTOR_IMAGE_ENV, words.replace(ref, "<the image>")
                                                                         if len(ref) >= MASK_MIN else words)) from None
    except (OSError, subprocess.SubprocessError, ValueError, LookupError, TypeError):
        raise Refused("%s: docker cannot inspect the image it names, so the fleet cannot tell that the stack takes it"
                      % stack.CONNECTOR_IMAGE_ENV) from None
    try:
        role: Optional[str] = stack.host_role()
    except stack.StackError:
        role = None
    if role != "pc":
        raise Refused("%s is not pc: a fleet runs on the PC alone (each car's stack refuses an instance run on any other role)"
                      % stack.HOST_ROLE_ENV)


def refusals(a: argparse.Namespace) -> Dict[str, Any]:
    """Every refusal of run, in order, before anything is written, made or started; what run needs from them."""
    for var in REFUSED_ENV:
        if var in os.environ:
            raise Refused("%s is set: the fleet sets each car's own, so its own environment holds none (unset it)" % var)
    if not NAME_RX.fullmatch(a.name or ""):
        raise Refused("--name is one word of letters, digits, '.', '_' and '-', beginning with a letter or a digit")
    cars = parse_cars(a.car)
    checked = check_cars(cars)
    for c in checked:
        if not (c["moves"] and c["distinct"]):
            raise Refused("car %s would not pass check (%s)" % (c["label"], check_line(c).split(" ", 3)[3]))
    for c in checked:
        try:
            bound = stack.player_bound_s(c["log"])          # the log check_car identified, not identified again
        except stack.StackError as exc:
            raise Refused("car %s: the stack refuses the bound on its player: %s" % (c["label"], exc)) from None
        if c["span_ms"] >= (bound - PLAYER_MARGIN_S) * 1000:
            raise Refused("car %s: its recording's log ends less than %d s inside the stack's bound on its player (stack.py's "
                          "player_bound_s for its log), or past it: its replay would end at the bound, not at the log's end"
                          % (c["label"], PLAYER_MARGIN_S))
    if not os.environ.get(stack.CONNECTOR_IMAGE_ENV):
        raise Refused("%s is not set: every car runs the one connector image, by its ID" % stack.CONNECTOR_IMAGE_ENV)
    image_and_role_refusal()
    devices = [device_of(c["label"]) for c in checked]
    for i, (di, ei) in enumerate(devices):
        for j in range(i):
            dj, ej = devices[j]
            li, lj = checked[i]["label"], checked[j]["label"]
            if di.resolve() == dj.resolve():
                raise Refused("car %s and car %s have one device directory (%s, %s): one identity a car" % (lj, li, DEVICE_ENV % lj, DEVICE_ENV % li))
            if ei.get(THING_ENV) == ej.get(THING_ENV):
                raise Refused("car %s and car %s have one %s in their %s: one identity a car" % (lj, li, THING_ENV, stack.CONNECTOR_ENV_FILE))
    run = run_dir_of(a.name)
    if stack.inside_repo(stack.STATE):
        raise Refused("the state directory is inside the repo: set %s to a directory outside it" % stack.STATE_ENV)
    if stack.inside_repo(run):
        raise Refused("the run directory would be inside the repo: set SDV_RUNS to a directory outside it")
    if run.exists():
        raise Refused("the run directory %s exists: pick another --name" % run.name)
    now = stack.wall_ms()
    # The fleet's own stamp is read once, by startstamp.mark in run_main, after every refusal here and before anything is
    # written: inside the spacing or unwritable it refuses and leaves the stamp; no stamp or from the future, it refuses
    # once and writes it anew, so those refusals end.
    for c in checked:
        where = identity_stamp_dir(c["label"])
        what, left = stamp_reading(where, now)
        if what == "spacing":
            raise Refused("car %s: its start stamp is inside the start spacing: wait %d s" % (c["label"], left))
        if what in ("unreadable", "no stamp", "from the future"):
            raise Refused("car %s: its identity's start stamp (%s) %s: remove it (the car's stack writes a new one at its next "
                          "connector start; the fleet writes no car's stamp)"
                          % (c["label"], stamp_place(where), "cannot be read" if what == "unreadable" else "is " + what))
    try:
        p = stack.docker("ps", "-aq", "--filter", "label=" + stack.LABEL, check=False)
    except (OSError, subprocess.SubprocessError):
        p = None
    if p is None or p.returncode != 0:
        raise Refused("docker cannot list the containers labelled %s, so the fleet cannot tell that no stack runs" % stack.LABEL)
    if (p.stdout or "").split():
        raise Refused("containers labelled %s exist: a stack runs, or one was left (stack.py down removes them)" % stack.LABEL)
    try:
        sockets = stack.host_listeners()["sockets"]
    except (stack.StackError, OSError, subprocess.SubprocessError):
        raise Refused("the host's listeners cannot be read (ss), so the fleet cannot tell that its ports are free") from None
    listening = {stack.local_port(s["local"]) for s in sockets if s.get("proto") == "tcp"}
    for k, c in enumerate(checked, 1):
        for what, port in (("databroker", stack.FLEET_BROKER_PORT_BASE + k), ("mock provider", stack.FLEET_MOCK_PORT_BASE + k)):
            if port in listening:
                raise Refused("car %s: its %s port %d is already listened on" % (c["label"], what, port))
    return {"checked": checked, "devices": devices, "run": run}


# --- run ------------------------------------------------------------------------------------------------------------------

def masks_of(devices: Sequence[Tuple[Path, Dict[str, Optional[str]]]]) -> List[Tuple[str, str]]:
    """The words no file under the run may hold, longest first, each with what a car's log shows instead: every device
    directory's path (as given and resolved), the names of the files in it, and each connector.env value (a NAME line alone
    by the value docker passes through: the fleet's own, which each car's environment carries). The identity's values
    (IDENTITY_ENV) whatever their length; every other word of MASK_MIN characters or more (a shorter one is neither
    masked nor searched for)."""
    words: Dict[str, str] = {}
    always: List[str] = []
    for d, env in devices:
        for p in {str(d), str(d.resolve())}:
            words[p] = "<device>"
        try:
            names = os.listdir(str(d))
        except OSError:
            names = []
        for name in names:
            words.setdefault(name, "<device file>")
        for key, value in env.items():
            value = os.environ.get(key) if value is None else value
            if value:
                words.setdefault(value, "<device value>")
                if key in IDENTITY_ENV:
                    always.append(value)
    return sorted(((w, instead) for w, instead in words.items() if len(w) >= MASK_MIN or w in always), key=lambda kv: -len(kv[0]))


def masked(text: str, masks: Sequence[Tuple[str, str]]) -> str:
    for word, instead in masks:
        text = text.replace(word, instead)
    return text


class CarLog(threading.Thread):
    """A car's stdout and stderr into its stack.log, line by line, masked."""

    def __init__(self, src: IO[bytes], dest: Path, masks: Sequence[Tuple[str, str]]) -> None:
        super().__init__(daemon=True)
        self.src, self.dest, self.masks = src, dest, list(masks)

    def run(self) -> None:
        with open(self.dest, "w", encoding="utf-8") as out:
            for raw in iter(self.src.readline, b""):
                out.write(masked(raw.decode("utf-8", "replace"), self.masks))
                out.flush()


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(".%s.tmp" % path.name)
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def sweep_instance(k: int) -> str:
    """Instance k's containers removed (docker rm -f) by the stack's own instance label: what a killed car's stack left. The
    words for stderr."""
    flt = "label=%s=%d" % (stack.INSTANCE_LABEL, k)
    try:
        ids = stack.docker("ps", "-aq", "--filter", flt, check=False).stdout.split()
        if ids:
            stack.docker("rm", "-f", *ids, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return "killed; its instance's containers could not be listed or removed (`docker ps -a --filter %s` lists them)" % flt
    return "killed; its instance's containers removed" if ids else "killed; no container of its instance was left"


class Signals:
    """SIGINT and SIGTERM while the fleet runs, in its main thread: the first one's name, kept for the fleet's loops to read,
    so that nothing is raised in the middle of a start or a write. The handlers before are put back after."""

    def __init__(self) -> None:
        self.got: Optional[str] = None
        self.before: Dict[int, Any] = {}

    def note(self, signum: int, _frame: Any) -> None:
        if self.got is None:
            self.got = signal.Signals(signum).name

    def __enter__(self) -> "Signals":
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                self.before[sig] = signal.signal(sig, self.note)
        return self

    def __exit__(self, *_exc: Any) -> None:
        for sig, handler in self.before.items():
            signal.signal(sig, signal.SIG_DFL if handler is None else handler)


class Car:
    """One car's process and what the fleet saw of it."""

    def __init__(self, k: int, check: Dict[str, Any], device: Path) -> None:
        self.k, self.check, self.device = k, check, device
        self.label = check["label"]
        self.proc: Optional["subprocess.Popen[bytes]"] = None
        self.log: Optional[CarLog] = None
        self.started = 0.0
        self.ready_ms: Optional[int] = None
        self.interrupted_at: Optional[float] = None          # when the fleet sent its one SIGINT
        self.killed = False

    def env(self, run: Path) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in REFUSED_ENV and not any(k == DEVICE_ENV % L for L in LABELS)}
        env.update({stack.INSTANCE_ENV: str(self.k), stack.FEED_GATE_ENV: str(run / "gate"), "SDV_RECORDING": str(self.check["dir"]),
                    "SDV_RUNS": str(run / ("car-%s" % self.label)), stack.DEVICE_DIR_ENV: str(self.device)})
        state = car_state(self.label)
        if state is not None:
            env[stack.STATE_ENV] = str(state)
        elif stack.STATE_ENV in os.environ:          # car A's is the caller's, made absolute as the others are: the car runs in the repo
            env[stack.STATE_ENV] = os.path.abspath(str(stack.STATE))
        return env

    def start(self, name: str, run: Path, masks: Sequence[Tuple[str, str]]) -> None:
        argv = [PYTHON, str(STACK_PY), "replay", "--name", "%s-%s" % (name, self.label), "--feed", "vcan", "--bridge", "none", "--connector"]
        # a process group of its own: a terminal's interrupt reaches the fleet alone, which gives each car one SIGINT, and a
        # kill takes what the car started with it (its player, docker's clients)
        own_group: Dict[str, Any] = {"process_group": 0} if sys.version_info >= (3, 11) else {"preexec_fn": os.setpgrp}
        self.proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env(run),
                                     cwd=str(stack.REPO), **own_group)
        assert self.proc.stdout is not None
        self.log = CarLog(self.proc.stdout, run / ("car-%s" % self.label) / "stack.log", masks)
        self.log.start()
        self.started = time.monotonic()

    def ended(self) -> bool:
        return self.proc is not None and self.proc.poll() is not None

    def read_ready(self, gate: Path) -> bool:
        p = gate / (stack.GATE_READY % self.k)
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if isinstance(doc, dict) and doc.get("instance") == self.k and isinstance(doc.get("ready_ms"), int):
            self.ready_ms = doc["ready_ms"]
            return True
        return False

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def interrupt(self) -> None:
        """One SIGINT to the car's stack, never a second (it could cut short the finally that removes its containers)."""
        if self.proc is not None and self.proc.poll() is None and self.interrupted_at is None:
            self.proc.send_signal(signal.SIGINT)
            self.interrupted_at = time.monotonic()

    def bound(self) -> None:
        """Past CAR_TIMEOUT_S, a SIGINT (the stack's finally removes its containers); STOP_GRACE_S after the fleet's SIGINT,
        whatever sent it, a kill."""
        if self.proc is None or self.proc.poll() is not None or self.killed:
            return
        now = time.monotonic()
        over = now - self.started - CAR_TIMEOUT_S
        if over > 0 and self.interrupted_at is None:
            say("car %s ran past %d s: interrupted" % (self.label, CAR_TIMEOUT_S))
            self.interrupt()
        elif self.interrupted_at is not None and now - self.interrupted_at > STOP_GRACE_S:
            say("car %s did not end within %d s of its interrupt: killed" % (self.label, STOP_GRACE_S))
            self.kill()

    def kill(self) -> None:
        """A SIGKILL to the car's process group (the stack and what it started: its player, docker's clients); its stack's
        finally never runs, so its instance's containers, its connector among them, are removed here by their label."""
        assert self.proc is not None
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except OSError:
            self.proc.kill()
        self.killed = True
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            pass
        say("car %s: %s" % (self.label, sweep_instance(self.k)))

    def finish(self) -> Optional[int]:
        if self.proc is None:
            return None
        code = self.proc.wait()
        if self.log is not None:
            self.log.join(30)
        return code


def find_replay(run: Path, name: str, label: str) -> Optional[Path]:
    """The car's replay directory, <run>/car-<L>/<YYYYMMDD>-<NAME>-<L>/vcan-1, when there is exactly one."""
    root = run / ("car-%s" % label)
    rx = re.compile(r"\d{8}-%s-%s" % (re.escape(name), label))
    found = [d / REPLAY for d in sorted(root.iterdir()) if d.is_dir() and rx.fullmatch(d.name) and (d / REPLAY).is_dir()] if root.is_dir() else []
    return found[0] if len(found) == 1 else None


def car_record(car: Car, run: Path, name: str, code: Optional[int]) -> Dict[str, Any]:
    c = car.check
    rec: Dict[str, Any] = {"label": car.label, "instance": car.k,
                           "recording": {"name": c["name"], "sha256": c["sha256"], "run_type": c["run_type"]},
                           "run": "car-%s" % car.label, "result": None, "witness": None, "stack_exit": code, "ready_ms": car.ready_ms,
                           "gates": None, "connector": None}
    replay = find_replay(run, name, car.label)
    if replay is None:
        return rec
    if (replay / "result.json").is_file():
        rec["result"] = str((replay / "result.json").relative_to(run).as_posix())
        try:
            result = json.loads((replay / "result.json").read_text(encoding="utf-8"))
            rec["gates"] = stack.replay_gates(result)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            result = {}
        conn = result.get("connector") if isinstance(result, dict) else None
        if isinstance(conn, dict):
            rec["connector"] = {"ok": conn.get("ok"), "exit": conn.get("exit"), "exit_means": conn.get("exit_means")}
    if (replay / stack.WITNESS_LOG).is_file():
        rec["witness"] = str((replay / stack.WITNESS_LOG).relative_to(run).as_posix())
    return rec


def holds_a_mask(run: Path, masks: Sequence[Tuple[str, str]]) -> List[str]:
    """The files under the run directory that hold a masked word (their paths, relative), searched as bytes."""
    words = [w.encode("utf-8") for w, _instead in masks]
    out = []
    for p in sorted(run.rglob("*")):
        if not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if any(w in data for w in words):
            out.append(p.relative_to(run).as_posix())
    return out


def utc_day() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def start_cars(cars: Sequence[Car], name: str, run: Path, gate: Path, masks: Sequence[Tuple[str, str]], signals: Signals) -> Optional[str]:
    """RUN's step 2: each car started once the one before it is ready, so no two prepares overlap. None once every car is
    ready and, at a last look, none has ended; else the reason for an abort, in words."""
    for car in cars:
        if signals.got is not None:
            return "the fleet was interrupted (%s) before go" % signals.got
        say("car %s: started (instance %d)" % (car.label, car.k))
        car.start(name, run, masks)
        while car.ready_ms is None:
            if car.read_ready(gate):
                say("car %s: ready" % car.label)
                break
            ended = [x for x in cars if x.ended()]
            if ended:
                return "car %s ended before go" % ended[0].label if ended[0] is not car else "car %s ended before it was ready" % car.label
            if time.monotonic() - car.started > GATE_WAIT_S:
                return "car %s gave no ready within %d s" % (car.label, GATE_WAIT_S)
            if signals.got is not None:
                return "the fleet was interrupted (%s) before go" % signals.got
            time.sleep(POLL_S)
    ended = [x for x in cars if x.ended()]          # a last look: a car may have ended in the poll that saw the last ready
    if ended:
        return "car %s ended before go" % ended[0].label
    return None


def wait_cars(cars: Sequence[Car], signals: Signals, after_go: bool) -> Optional[str]:
    """RUN's step 4: every started car to its end, each bounded (Car.bound). A SIGINT or SIGTERM to the fleet after go gives
    every running car one SIGINT (before go the abort ends the ready cars at the gate, and the one still preparing had
    its SIGINT then); its reason, or None."""
    stopped: Optional[str] = None
    while any(car.running() for car in cars):
        if after_go and signals.got is not None and stopped is None:
            stopped = "the fleet was interrupted (%s) after go: every running car interrupted" % signals.got
            say(stopped)
            for car in cars:
                car.interrupt()
        for car in cars:
            car.bound()
        time.sleep(POLL_S)
    return stopped


def drive(cars: Sequence[Car], name: str, run: Path, gate: Path, masks: Sequence[Tuple[str, str]],
          signals: Signals) -> Tuple[Optional[str], Optional[int], Optional[BaseException]]:
    """RUN's steps 2 to 4: the cars started, then go or abort, then every car waited for. The abort's reason (after go, the
    interrupt's), go's wall clock in ms, and a failure of the fleet's own, raised once the record is written."""
    abort: Optional[str] = None
    go_ms: Optional[int] = None
    failure: Optional[BaseException] = None
    try:
        abort = start_cars(cars, name, run, gate, masks, signals)
        if abort is None:
            go_ms = stack.wall_ms()
            write_atomic(gate / stack.GATE_GO, json.dumps({"go_ms": go_ms}) + "\n")
            say("go")
    except BaseException as exc:          # the fleet's own, while it starts the cars (off the main thread, an interrupt too)
        failure = None if isinstance(exc, KeyboardInterrupt) else exc
        abort = "the fleet was interrupted before go" if failure is None else "the fleet failed before go (%s)" % type(exc).__name__
    if abort is not None:
        write_atomic(gate / stack.GATE_ABORT, abort + "\n")
        say("abort: %s" % abort)
        for car in cars:
            if car.ready_ms is None:          # still preparing: it would go on to its up(), its connector's start among it
                car.interrupt()
    stopped = wait_cars(cars, signals, go_ms is not None)
    return (abort if abort is not None else stopped), go_ms, failure


def write_record(name: str, run: Path, cars: Sequence[Car], masks: Sequence[Tuple[str, str]], abort: Optional[str], go_ms: Optional[int],
                 start: Tuple[int, str, str]) -> int:
    """<run>/fleet.json once every car has ended, the search for a masked word under the run, stdout; the exit status."""
    from_ms, day, utc_start = start
    codes: Dict[str, Optional[int]] = {}
    for car in cars:
        codes[car.label] = car.finish()
    to_ms, day_at_stop, utc_end = stack.wall_ms(), utc_day(), stack.utc_now()
    records = [car_record(car, run, name, codes[car.label]) for car in cars]
    ok = abort is None and all(r["stack_exit"] == 0 and r["gates"] is not None and all(r["gates"].values()) for r in records)
    doc = {"v": 1, "fleet": name, "utc_start": utc_start, "utc_end": utc_end, "cars": records, "gate": {"go_ms": go_ms, "abort": abort},
           "window": {"day": day, "from_ms": from_ms, "to_ms": to_ms, "day_at_stop": day_at_stop}, "ok": ok}
    stack.write_json(run / "fleet.json", doc)
    leaked = holds_a_mask(run, masks)
    if leaked:
        doc["ok"] = ok = False
        stack.write_json(run / "fleet.json", doc)
        say("a device item is under the run directory, in %s: the fleet is not ok" % ", ".join(leaked))
    for r in records:
        print("%s gates: %s" % (r["label"], json.dumps(r["gates"], sort_keys=True)))
    print("fleet: %s" % ("ok" if ok else "NOT ok"), flush=True)
    return EXIT_OK if ok else EXIT_NOT_OK


def run_main(a: argparse.Namespace) -> int:
    ready = refusals(a)
    checked, devices, run = ready["checked"], ready["devices"], ready["run"]
    ss = stack.connector_part("startstamp")
    start = (stack.wall_ms(), utc_day(), stack.utc_now())
    fleet_dir = stack.STATE / "fleet"
    fleet_dir.mkdir(parents=True, exist_ok=True)
    try:
        ss.mark(fleet_dir, stack.wall_ms())
    except ss.StartRefused as refused:
        raise Refused(mark_refusal(refused.why, refused.retry_after_s)) from None
    gate = run / "gate"
    gate.mkdir(parents=True)
    for c in checked:
        (run / ("car-%s" % c["label"])).mkdir()
    masks = masks_of(devices)
    cars = [Car(k, c, devices[k - 1][0]) for k, c in enumerate(checked, 1)]
    with Signals() as signals:          # from the first car's start to the record: an interrupt is read, never raised
        abort, go_ms, failure = drive(cars, a.name, run, gate, masks, signals)
        code = write_record(a.name, run, cars, masks, abort, go_ms, start)
    if failure is not None:
        raise failure
    return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check", help="each car's recording as the stack takes it: moves, distinct; writes nothing")
    ck.add_argument("--car", action="append", default=[], metavar="L=REC_DIR")
    rn = sub.add_parser("run", help="the cars at once, one stack instance a car (the module docstring, RUN)")
    rn.add_argument("--name", required=True)
    rn.add_argument("--car", action="append", default=[], metavar="L=REC_DIR")
    a = ap.parse_args(argv)
    try:
        return check_main(a) if a.cmd == "check" else run_main(a)
    except Refused as exc:
        say(str(exc))
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
