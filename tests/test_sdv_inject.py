"""The injected recordings of Phase 2 step 3 and their events file (sdv/inject/inject.py; sdv Phase 2, WP9).

What is tested, and how. Everything reads the sigsim recording 20260930-sigsim-1b (read only; skipped without it)
and writes only under pytest's tmp_path:

- The done check: the tool rewrites the recording into a new directory (in process, with the stand-in for cantools'
  database that tests/test_sdv_bridge_sources.py builds from slice.dbc, plus the signal ranges the rewrite reads);
  then this file's own driver replays the rewritten sigsim.log offline through the bridge's replay mode
  (bridge_sources.ReplaySource on a fake clock, the bridge's Intake, HeldValues and ClaimCore.tick: its packing, on
  its tick grid), once per run of the events file -- the stop run with its replay realisation of 22 (an intake
  pause at the stop), the to_end run with nothing stopped -- judges every packed frame with rules.judge_frame, and
  gets exactly the run's event-to-reason set built from the events' intended reasons (reasonsets.reason_set on its
  windows shifted by the run's own replay-anchored origin), every tick inside an injected span rejected with that
  event's reason (at least two ticks each), ACCEPT on every other tick before the run's reference (the stop, or the
  file's last frame), then ACCEPT until the first 22 and 22 after it, the first 22 at most AGE_MAX plus one tick
  after the reference with an age within AGE_MAX plus one tick (spec 14.1, P9), and at least two 22 ticks in each of
  the run's two 22 windows. The events file's computed reasons must equal the intended ones. The source recording's
  files hash the same before the rewrite, after it, and after every test.
- The stop is checked, not assumed: the stop run replayed without its stop lacks (stop, 22), and the to_end run's
  windows do not fit the stop run's replies.
- The rewrite itself: against the source, only the events' frames differ, each only in its event's signal; every
  value is beyond its limit in the generated profile table and inside slice.dbc's range; the yaw event sits where
  sigsim's rule26_above_tol counter counts (its predicate counts exactly that counter on the decoded source) with
  psi_dot_kin above tol by more than the generated QUANT_BOUND; the gear event's frames all move forward faster than
  v_tol by more than the generated half LSB of v; the windows are ordered, disjoint, separated, and each run's two 22
  windows come last.
- The new directory passes the stack's own provenance checks of a recording (sdv/stack/stack.py recording_identity,
  recording_seed, recording_summary, check_summary_counts; replaycheck's expected windows and the hard-brake app's
  predicted switches, which equal the source's), its summary trip keeps only the fields that still describe it, and
  its manifest line keeps the scenario entry's limits.
- `check`: passes on the new directory; refuses a tampered reason, an events file of another format, one made with
  another contract, and a DBC that is not the contract's generation; warns and skips the source diff when the
  source is gone.
- In the sim venv (skipped without it): every frame decodes with cantools (database loaded strict) and python-can's
  log reader; the stack's decode_recording path gives the same counts, windows and switches; the command line run
  there with real cantools writes a byte-identical log and the same events; its `check` passes; it refuses an
  existing destination.
- The recording made for WP10 (~/sdv-recordings/20261002-sigsim-1b-inj4, if present): `check` passes, its log and
  events equal a fresh rewrite's. The recording names the reference inject.py by its pinned SHA-256. A fresh rewrite
  names the current tool, and both runs replay to its events. A sigsim rewrite is that
  recording byte for byte in all five files but for two hashes, the tool's and the contract's (the generation's
  identity, which `check` holds), and the paths and the hashes over events.json that follow from them: Phase 7's
  WP3a changed the tool and nothing a sigsim rewrite writes. Under a generation with another contract (Phase 7's
  frozen profile 3) `check` refuses that recording until it is re-made on that tree, and a re-made one moves the
  pinned sha256.
- A CARLA source (Phase 7 WP3a; the tool's A CARLA SOURCE), built here from the sigsim recording: relabelled carla,
  its log renamed carla.log, the five params of a CARLA line, a synthetic rtf, profile 1 and its wheelbase (so the
  compiled table judges it), a synthetic steps.jsonl. It is rewritten into carla.log with the sigsim rewrite's frames
  and events; the new line keeps its rtf unchanged, events.json's rewritten_from records it (a sigsim rewrite's has
  none), and the line carries its five params and the rewrite's three; summary.json's trip keeps the rtf, the time
  base and the gaps; steps.jsonl is not copied and summary.json says so; `check` passes, and refuses a line whose rtf
  is not summary.json's, not events.json's (with the source there and with it gone) or not the source's, and an
  events file that names another log. A stray sigsim.log beside carla.log is never read. Refused before anything is
  written: params that would exceed eight with the rewrite's three, a value over 64 characters or one that is neither
  an integer nor a string, params that are not an object (an InjectError, on the command line too, not a traceback),
  a carla source with no rtf, a malformed one or one that is not its summary.json's trip rtf, a sigsim source with
  one, a log name that is not its generator's, a recording.path that is not a scenario entry path
  (manifest-classes.md section 9), and a .sha256 that names another file; a destination whose path is not a scenario
  entry path is refused before it is created. The stack's own checks read and validate the CARLA rewrite by the
  log its manifest line names.
- Refusals: an existing destination (left as it was), one inside the repository, a source whose log does not match its
  manifest line, a source name reused, a DBC that is not the contract's generation, and a source whose manifest line
  names another DBC or another catalogue digest than the contract's; each writes nothing.
- The separation between windows is held to the specification's one-second summary interval (spec 15), a value of
  this file's own, not to the tool's SEPARATION_NS.

What this does NOT show: any timing; what a live mode (can, broker) samples (WP10's runs); that the guest judges as
the Python reference does (the monitor's own tests); that a real CARLA recording is rewritten (the CARLA source here
is the sigsim recording relabelled, under profile 1; the Phase 7 integration branch's contract test rewrites one the
encoder made on a fake simulator); the stack replaying a CARLA recording (WP3b).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

import test_sdv_bridge_sources as tsbs
import test_sdv_frame as tsf

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
INJECT_DIR = REPO / "sdv" / "inject"
STACK_DIR = REPO / "sdv" / "stack"

_saved = sys.dont_write_bytecode
sys.dont_write_bytecode = True
for _d in (INJECT_DIR, STACK_DIR):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
import inject as inj  # noqa: E402
import stack as stack_module  # noqa: E402, F401

sys.dont_write_bytecode = _saved

vb, bs, rs, rules, vf = inj.vb, inj.bs, inj.rs, inj.rules, inj.vf
C = tsf.C
MS = 1_000_000
TWO_TICKS = 2                 # the wire specification's 14.2: an event's window spans at least two bridge ticks
SUMMARY_INTERVAL_NS = 1_000_000_000     # the wire specification's 15: the guest's one-second log-summary interval
RUNS = ("stop", "to_end")

SRC = Path(os.environ.get("SDV_INJECT_SOURCE", "~/sdv-recordings/20260930-sigsim-1b")).expanduser()
NAME = "20261002-sigsim-1b-inj4"
MADE = Path("~/sdv-recordings").expanduser() / NAME
# events.json names the inject.py that made the reference recording. The recording was regenerated on 2026-10-18
# with the frozen profile 3 generation because check verifies the generation's contract. The pre-freeze copy is an
# archive. A sigsim rewrite moves no
# frame, so the re-made recording is the frozen one but for this hash, the contract's and what follows from them, as
# test_a_sigsim_rewrite_is_the_wp10_recording_byte_for_byte_but_for_two_hashes holds of a fresh rewrite. A generation with
# another contract sha256 needs inj4 re-made again, and a re-made inj4 names the tool that re-made it: change this constant with it.
WP10_TOOL_SHA256 = "4038e6f04091bcd989b042625581c010013b0d9934ec0f6ad32ac0f462c78425"
SIGSIM_REWRITE_KEYS = {"from", "events", "events_sha256", "tool", "trip_fields_dropped", "note"}     # summary.json's rewrite
CARLA_LOG = "carla.log"
CARLA_TOWN, CARLA_VERSION, CARLA_BLUEPRINT = "Town01", "0.9.16", "vehicle.toyota.prius"     # a CARLA line's (spec 2.1, 2.3)
CARLA_TIMESTAMPS = "feeder send schedule from zero"                                         # its trip's time base (spec 2.3)
# A CARLA source's rtf here: synthetic, read from nothing, with digits enough that any rounding of it would show.
SYN_RTF = {"max": 0.999987654321, "mean": 0.93125, "min": 0.871234567891234}
SIM_PY = tsbs.SIM_PY
NEEDS_SRC = pytest.mark.skipif(not (SRC / "sigsim.log").is_file(), reason="needs the sigsim recording %s (read only)" % SRC)
pytestmark = [tsf.NEEDS_CONTRACT, NEEDS_SRC]


class StandInDB(tsbs.StandInDB):
    """tests/test_sdv_bridge_sources.py's stand-in for cantools' database (exact, cantools' arithmetic), plus what the
    rewrite reads: get_message_by_frame_id and each signal's minimum, maximum and scale (slice.dbc's)."""

    def __init__(self, text):
        super().__init__(text)
        parsed = tsbs.attr.parse_dbc(text)["messages"]
        for m in self.messages:
            for s in m.signals:
                spec = parsed[m.name]["signals"][s.name]
                s.minimum, s.maximum, s.scale = spec["min"], spec["max"], spec["factor"]
        self._by_id = {m.frame_id: m for m in self.messages}

    def get_message_by_frame_id(self, frame_id):
        return self._by_id[frame_id]


def tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def jload(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


SOURCE_BEFORE = tree_hashes(SRC) if (SRC / "sigsim.log").is_file() else {}


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    before = tree_hashes(SRC)
    db = StandInDB(tsbs.SLICE_TEXT)
    built = inj.build(SRC, NAME, db, C, bs.SLICE_DBC)
    dest = tmp_path_factory.mktemp("rec") / NAME
    out = inj.write(built, dest)
    yield types.SimpleNamespace(dir=dest, out=out, db=db, before=before, after=tree_hashes(SRC),
                                doc=jload(dest / "events.json"), line=jload(dest / "manifest-line.json"))
    assert tree_hashes(SRC) == before == SOURCE_BEFORE, "the source recording changed"


# ============================================================ this file's own replay of a log (the replay-mode bridge)

def replay(log, db, line, stop_ns, until_ns):
    """Every reply record a replay-mode bridge would log for this file, judged by the reference rules, and the run's
    origin: ReplaySource on a fake clock (its start reading anchors the grid), its batches offered to the bridge's
    Intake before the tick that follows them, ClaimCore.tick packing from the held values each tick, the intake
    paused for every batch due at or after stop_ns if one is given (the stop run's replay realisation of 22), and
    ticks through until_ns past the file's first frame."""
    cfg = vb.Config(host="127.0.0.1", port=1, mode="replay", profile_id=line["profile_id"], profile_source="scenario",
                    source_vehicle=dict(line["source"]["vehicle"]))
    tables, problems = vb.bind(cfg, C)
    assert not problems, problems
    frames = bs.read_candump(log)
    now = [7 * 10**12]
    src = bs.ReplaySource(bs.SlotDecoder(db, C), frames, clock=lambda: now[0],
                          sleep=lambda s: now.__setitem__(0, now[0] + int(s * 1e9) + 1))
    log_ = vb.EventLog()
    src.attach_log(log_.write)
    start = now[0]
    src.now_ns()
    anchor = rs.replay_anchor(log_.records)
    due = [(now[0], b) for b in src.updates()]
    hv, core = vb.HeldValues(), vb.ClaimCore(cfg, C, tables, log_)
    intake = vb.Intake(hv, log_)
    replies, n = [], 0
    while True:
        wall = start + n * vb.TICK_NS
        while due and due[0][0] < wall:
            at, batch = due.pop(0)
            if stop_ns is not None and at - anchor >= stop_ns:
                intake.paused.set()
            intake.offer(batch)
        now[0] = wall
        t = src.now_ns()
        if t - anchor > until_ns:
            break
        if core.tick(hv.snapshot(), t, wall) is not None:
            q = core.take()
            verdict, reason = rules.judge_frame(q.frame, tables)
            ok, rec = core.reply(q, rules.reply(q.frame, tables))
            assert ok and (rec["verdict"], rec["reason"]) == (verdict, reason), rec
            replies.append(rec)
        n += 1
    return replies, anchor


def run_list(doc, run):
    return list(doc["events"]) + list(doc["runs"][run]["events"])


def until_of(doc):
    return max(r["run_through_ns"] for r in doc["runs"].values())


def check_run(log, db, doc, line, run):
    """The done check on one log and one run: the reason set equals the run's intended one, tick by tick inside the
    spans, before the reference, and from it on (the first 22 within AGE_MAX plus one tick, spec 14.1 and P9)."""
    r = doc["runs"][run]
    evs = run_list(doc, run)
    stop = r["realisation"]["replay"].get("at_offset_ns")
    assert stop == r["stop_ns"] and (stop is None) == (run == "to_end")
    replies, anchor = replay(log, db, line, stop, until_of(doc))
    assert [e.get("reason") for e in evs] == [e["intended_reason"] for e in evs], [(e["event"], e.get("reason")) for e in evs]
    expected = {(e["event"], e["intended_reason"]) for e in evs}
    res = rs.compare(expected, rs.reason_set(replies, rs.shift_windows(evs, anchor)))
    assert res["ok"], res
    spans = [(e["injected_ns"][0], e["injected_ns"][1], e) for e in doc["events"]]
    first_w, rest_w = evs[-2], evs[-1]
    ref = r["reference_ns"]
    assert first_w["t0_ns"] == ref and first_w["t1_ns"] == rest_w["t0_ns"] and rest_w["t1_ns"] == inj.OPEN_END_NS
    rejected = {e["event"]: 0 for e in evs}
    after = []
    for rr in replies:
        off = rr["src_now_ns"] - anchor
        owner = [e for a, b, e in spans if a <= off < b]
        if owner:
            assert (rr["verdict"], rr["reason"]) == (rules.V_REJECT, owner[0]["intended_reason"]), (run, off // MS, rr)
            rejected[owner[0]["event"]] += 1
        elif off < ref:
            assert (rr["verdict"], rr["reason"]) == (rules.V_ACCEPT, rules.RSN_OK), (run, off // MS, rr)
        else:
            after.append((off, rr))
    first = next(i for i, (_off, rr) in enumerate(after) if rr["verdict"])
    assert all(not rr["verdict"] for _o, rr in after[:first]) and all(rr["reason"] == rules.RSN_VSS_STALE for _o, rr in after[first:])
    t_first, r0 = after[first]
    assert t_first - ref <= C.AGE_MAX_MS * MS + vb.TICK_NS, (run, (t_first - ref) // MS)
    assert C.AGE_MAX_MS < r0["age_ms"] <= C.AGE_MAX_MS + vb.TICK_NS // MS, (run, r0)
    assert first_w["t0_ns"] <= t_first < first_w["t1_ns"]
    rejected[first_w["event"]] = sum(1 for off, rr in after if rr["verdict"] and off < first_w["t1_ns"])
    rejected[rest_w["event"]] = sum(1 for off, rr in after if rr["verdict"] and off >= rest_w["t0_ns"])
    assert after[-1][0] + vb.TICK_NS >= r["run_through_ns"], (run, after[-1][0] // MS)
    assert all(k >= TWO_TICKS for k in rejected.values()), (run, rejected)
    return replies, anchor, rejected


# ============================================================ the done check

def test_the_rewritten_file_replays_to_exactly_the_events_reasons_and_accept_elsewhere(made):
    assert [e["event"] for e in made.doc["events"]] == ["speed", "accel", "steer", "yaw", "gear"]
    assert [e["intended_reason"] for e in made.doc["events"]] == [rules.RSN_VSS_SPEED, rules.RSN_VSS_ACCEL, rules.RSN_VSS_STEER,
                                                                  rules.RSN_VSS_YAW, rules.RSN_VSS_GEAR]
    assert {run: [e["event"] for e in made.doc["runs"][run]["events"]] for run in RUNS} == {
        "stop": ["stop", "stop-held"], "to_end": ["end", "end-held"]}
    for run in RUNS:
        replies, anchor, rejected = check_run(made.dir / "sigsim.log", made.db, made.doc, made.line, run)
        for e in run_list(made.doc, run):
            assert e["reason"] == e["intended_reason"] and e["reason_name"] == rules.REASON_NAMES[e["intended_reason"]]
            assert e["replay"]["rejected_ticks"] == rejected[e["event"]], (run, e["event"])
        assert sum(1 for r in replies if r["verdict"]) == sum(rejected.values())
    assert made.before == made.after == tree_hashes(SRC) == SOURCE_BEFORE


def test_a_run_whose_stop_is_not_realised_fails_the_stop_runs_set(made):
    """The stop run's first 22 window must hold a 22: replayed without its stop, the file's end gives the 22s, in the
    open-ended window only, so (stop, 22) is missing; and the to_end run's windows do not fit the stop run's replies."""
    log, doc = made.dir / "sigsim.log", made.doc
    stop_evs = run_list(doc, "stop")
    replies, anchor = replay(log, made.db, made.line, None, until_of(doc))
    res = rs.compare({(e["event"], e["intended_reason"]) for e in stop_evs}, rs.reason_set(replies, rs.shift_windows(stop_evs, anchor)))
    assert not res["ok"] and res["missing"] == [("stop", rules.RSN_VSS_STALE)] and res["extra"] == [], res
    replies, anchor = replay(log, made.db, made.line, doc["runs"]["stop"]["stop_ns"], until_of(doc))
    end_evs = run_list(doc, "to_end")
    res = rs.compare({(e["event"], e["intended_reason"]) for e in end_evs}, rs.reason_set(replies, rs.shift_windows(end_evs, anchor)))
    assert not res["ok"] and (None, rules.RSN_VSS_STALE) in res["extra"], res


def test_the_tools_judge_refuses_a_first_22_later_than_age_max_plus_one_tick(made):
    """inject.judge_run's own P9 bounds: the stop run as made passes; with its first 22 tick missing (the next one has
    an age past AGE_MAX plus one tick), or with the stop realised two ticks late (its first 22 then comes more than
    AGE_MAX plus one tick after the stop the events file names), it refuses. One tick late still passes here: this
    file's first 22 comes two ticks after the stop, inside the bound."""
    doc = made.doc
    stop = doc["runs"]["stop"]
    frames = bs.read_candump(made.dir / "sigsim.log")
    cfg = inj.bridge_config(made.line)

    def events():
        return [{k: v for k, v in e.items() if k not in inj.JUDGED_KEYS} for e in run_list(doc, "stop")]

    rp = inj.replay_offline(frames, made.db, C, cfg, stop["run_through_ns"], stop_ns=stop["stop_ns"])
    inj.judge_run(rp, events(), stop["run_through_ns"], C)
    i = next(k for k, (off, r) in enumerate(rp.offsets()) if off >= stop["stop_ns"] and r["verdict"])
    late = inj.Replay(rp.anchor_ns, rp.records[:i] + rp.records[i + 1:], rp.counters, rp.intake)
    with pytest.raises(inj.InjectError, match="the first 22 has age"):
        inj.judge_run(late, events(), stop["run_through_ns"], C)
    rp = inj.replay_offline(frames, made.db, C, cfg, stop["run_through_ns"], stop_ns=stop["stop_ns"] + vb.TICK_NS)
    inj.judge_run(rp, events(), stop["run_through_ns"], C)
    rp = inj.replay_offline(frames, made.db, C, cfg, stop["run_through_ns"], stop_ns=stop["stop_ns"] + 2 * vb.TICK_NS)
    with pytest.raises(inj.InjectError, match="not within AGE_MAX plus one tick"):
        inj.judge_run(rp, events(), stop["run_through_ns"], C)


def test_the_source_replays_to_accept_everywhere_before_the_file_ends(made):
    """The same driver on the unrewritten source: no reject before the to_end run's reference, so every reject of the
    rewritten file before it comes from its rewrite."""
    end = made.doc["runs"]["to_end"]["reference_ns"]
    replies, anchor = replay(SRC / "sigsim.log", made.db, jload(SRC / "manifest-line.json"), None, until_of(made.doc))
    assert replies and all(not r["verdict"] for r in replies if r["src_now_ns"] - anchor < end)


# ============================================================ the rewrite

def profile():
    return {r["id"]: r for r in C.PROFILES}[jload(SRC / "manifest-line.json")["profile_id"]]


def decoded_lines(path, db):
    out = []
    for t_us, cid, data in bs.read_candump(path):
        m = db.get_message_by_frame_id(cid)
        out.append((t_us, cid, m, m.decode(data, decode_choices=False, scaling=True)))
    return out


def test_only_the_events_frames_change_each_only_in_its_signal_and_beyond_its_limit(made):
    old, new = decoded_lines(SRC / "sigsim.log", made.db), decoded_lines(made.dir / "sigsim.log", made.db)
    assert [(t, c) for t, c, _m, _v in old] == [(t, c) for t, c, _m, _v in new]
    t0 = old[0][0]
    rewrites = made.doc["events"]
    changed = {e["event"]: 0 for e in rewrites}
    for (t, cid, _m, a), (_t, _c, _m2, b) in zip(old, new):
        diff = {k for k in a if a[k] != b[k]}
        if not diff:
            continue
        off = (t - t0) * 1000
        owner = [e for e in rewrites if e["injected_ns"][0] <= off < e["injected_ns"][1] and e["rewrite"]["can_id"] == cid]
        assert len(owner) == 1 and diff <= {owner[0]["rewrite"]["signal"]}, (t, diff)
        assert b[owner[0]["rewrite"]["signal"]] == owner[0]["rewrite"]["value"]
        changed[owner[0]["event"]] += 1
    pr = profile()
    for e in rewrites:
        w = e["rewrite"]
        slot = w["slot"]
        assert changed[e["event"]] == w["frames"] > 0
        assert (w["message"], w["signal"], w["vss_path"]) == (C.SLOT_DBC_MESSAGES[slot], C.SLOT_DBC_SIGNALS[slot], C.SLOT_PATHS[slot])
        sig = made.db.get_message_by_name(w["message"]).get_signal_by_name(w["signal"])
        assert sig.minimum <= w["value"] <= sig.maximum
        period = C.DBC_PERIOD_MS[w["message"]] * MS
        assert w["frames"] == (e["injected_ns"][1] - e["injected_ns"][0]) // period
    by = {e["event"]: e["rewrite"]["value"] for e in rewrites}
    assert by["speed"] > pr["v_max"] and abs(by["accel"]) > pr["a_max"] and abs(by["steer"]) > pr["delta_max"]
    assert by["yaw"] == 0.0 and by["gear"] < 0


def test_every_event_spans_at_least_two_ticks_inside_ordered_separated_windows(made):
    evs = made.doc["events"]
    allowance = C.PIPELINE_ALLOWANCE_MS * MS
    for e in evs:
        a, b = e["injected_ns"]
        assert b - a >= TWO_TICKS * vb.TICK_NS and a % vb.TICK_NS == 0 and b % vb.TICK_NS == 0
        assert (e["t0_ns"], e["t1_ns"]) == (a - allowance, b + allowance)
    # The separation: at least the summary interval (spec 15), held against this file's value, never the tool's own
    # SEPARATION_NS, so a separation of 0 fails here and not only through the stored recording's design block.
    assert evs[0]["t0_ns"] >= SUMMARY_INTERVAL_NS
    for p, q in zip(evs, evs[1:]):
        assert q["t0_ns"] - p["t1_ns"] >= SUMMARY_INTERVAL_NS
    first22 = (C.AGE_MAX_MS + C.PIPELINE_ALLOWANCE_MS) * MS + vb.TICK_NS
    last = (bs.read_candump(made.dir / "sigsim.log")[-1][0] - bs.read_candump(made.dir / "sigsim.log")[0][0]) * 1000
    stop, end = made.doc["runs"]["stop"], made.doc["runs"]["to_end"]
    assert stop["reference_ns"] == stop["stop_ns"] and stop["stop_ns"] - evs[-1]["t1_ns"] >= SUMMARY_INTERVAL_NS
    assert stop["stop_ns"] >= made.doc["checks"]["app_windows"]["off_window_ms"][1] * MS + SUMMARY_INTERVAL_NS
    assert end["reference_ns"] == last and end["stop_ns"] is None and stop["run_through_ns"] <= last
    for run in (stop, end):
        f, h = run["events"]
        assert (f["t0_ns"], f["t1_ns"], h["t0_ns"], h["t1_ns"]) == (run["reference_ns"], run["reference_ns"] + first22,
                                                                    run["reference_ns"] + first22, inj.OPEN_END_NS)
        assert h["open_end"] and f["rewrite"] is None and h["rewrite"] is None
        assert run["run_through_ns"] - h["t0_ns"] >= TWO_TICKS * vb.TICK_NS + allowance
        assert set(run["realisation"]) == set(vb.MODES)
    assert {m: r["action"] for m, r in stop["realisation"].items()} == {
        "broker": "stop the can-provider", "can": "stop the player", "replay": "pause the intake"}
    assert all(r["at_offset_ns"] == stop["stop_ns"] and r["undone"] is False for r in stop["realisation"].values())
    assert all("at_offset_ns" not in r and r["action"].startswith("none") for r in end["realisation"].values())


def test_the_yaw_and_gear_events_sit_where_their_rules_must_fire_with_a_margin(made):
    """The predicate counts exactly summary.json's rule26_above_tol on the decoded source; every frame of the yaw
    event's window satisfies it with psi_dot_kin above tol by more than the generated QUANT_BOUND, and every frame of
    the gear event's window moves forward faster than v_tol by more than the generated half LSB of v."""
    tables = rules.Tables.from_contract(C)
    pid = profile()["id"]
    pr = tables.profiles[pid]
    dyn = [(t, v) for t, _c, m, v in decoded_lines(SRC / "sigsim.log", made.db) if m.name == C.SLOT_DBC_MESSAGES[0]]
    t0 = dyn[0][0]

    def excess(v):
        av, ad = abs(vf.f32(v[C.SLOT_DBC_SIGNALS[0]])), abs(vf.f32(v[C.SLOT_DBC_SIGNALS[2]]))
        if not (pr.v26_lo <= av <= pr.v26_hi and ad <= pr.delta_max):
            return None
        kin, ay = rules.kinematics(av, ad, pr.l_mm, tables)
        return kin - pr.tol26 if (pr.ay26_max == 0.0 or ay <= pr.ay26_max) else None

    fires = [v for _t, v in dyn if (excess(v) or 0.0) > 0.0]
    assert len(fires) == jload(SRC / "summary.json")["verify"]["judge"]["rule26_above_tol"] == made.doc["checks"]["rule26_predicate_count"]
    ev = {e["event"]: e for e in made.doc["events"]}
    in_win = {k: [v for t, v in dyn if ev[k]["t0_ns"] <= (t - t0) * 1000 < ev[k]["t1_ns"]] for k in ("yaw", "gear")}
    yaw_margin, gear_margin = C.QUANT_BOUND[pid], C.DBC_HALF_LSB["v"]
    assert in_win["yaw"] and all((excess(v) or 0.0) > yaw_margin for v in in_win["yaw"])
    assert ev["yaw"]["rewrite"]["condition"]["least_excess"] == min(excess(v) for v in in_win["yaw"])
    assert ev["yaw"]["rewrite"]["condition"]["value"] == yaw_margin
    gear_ex = [vf.f32(v[C.SLOT_DBC_SIGNALS[0]]) - pr.v_tol for v in in_win["gear"]]
    assert gear_ex and all(x > gear_margin for x in gear_ex)
    assert ev["gear"]["rewrite"]["condition"]["least_excess"] == min(gear_ex) and ev["gear"]["rewrite"]["condition"]["value"] == gear_margin


def test_the_yaw_and_gear_conditions_need_more_than_their_margin(made):
    """The placement conditions themselves (this recording's margins are wide, so its windows alone cannot show it): a
    frame whose excess over tol or v_tol is exactly the margin is refused, one just past it is taken."""
    tables = rules.Tables.from_contract(C)
    pid = profile()["id"]
    pr = tables.profiles[pid]
    need = inj.margins(C, pid)
    yaw, gear = (next(k for k in inj.SLOT_EVENTS if k.event == n) for n in ("yaw", "gear"))
    dyn = [{i: inj.held(i, v[C.SLOT_DBC_SIGNALS[i]]) for i in range(4)} for _t, _c, m, v in decoded_lines(SRC / "sigsim.log", made.db)
           if m.name == C.SLOT_DBC_MESSAGES[0]]
    vals = next(v for v in dyn if (inj.rule26_excess(v, pr, tables) or 0.0) > 0.0)
    ex = inj.rule26_excess(vals, pr, tables)
    assert inj._condition(yaw, vals, pr, tables, {**need, inj.SLOT_YAW: dict(need[inj.SLOT_YAW], value=ex)}) is None
    assert inj._condition(yaw, vals, pr, tables, {**need, inj.SLOT_YAW: dict(need[inj.SLOT_YAW], value=ex / 2)}) == (0, ex)
    m = need[inj.SLOT_GEAR]["value"]
    for v, ok in ((pr.v_tol + m / 2, False), (pr.v_tol + 2 * m, True)):      # inside the margin, past it
        got = inj._condition(gear, {**vals, inj.SLOT_V: v}, pr, tables, need)
        assert (got is not None) == ok, (v, got)
    v = pr.v_tol + 2 * m
    at = {**need, inj.SLOT_GEAR: dict(need[inj.SLOT_GEAR], value=v - pr.v_tol)}
    assert inj._condition(gear, {**vals, inj.SLOT_V: v}, pr, tables, at) is None        # exactly at it


# ============================================================ the stack's provenance checks

def _stack():
    saved = sys.dont_write_bytecode
    try:
        import stack
    finally:
        sys.dont_write_bytecode = saved
    return stack


def stand_in_decode(path, db):
    """(t_ms, message, {signal: value}) as replaycheck.decode_recording gives them, through the stand-in."""
    out = []
    lines = decoded_lines(path, db)
    t0 = lines[0][0]
    for t, _c, m, v in lines:
        out.append((int(round((t - t0) / 1000.0)), m.name, dict(v)))
    return out


def test_the_new_directory_passes_the_stacks_provenance_checks_and_keeps_the_apps_switches(made):
    st = _stack()
    rc = st.rc
    ident = st.recording_identity(made.dir)
    line = ident["manifest_line"]
    assert line == made.line and line["name"] == NAME and line["recording"]["sha256"] == made.out["sha256"]
    assert st.recording_seed(line, None) == jload(SRC / "manifest-line.json")["source"]["params"]["seed"]
    summ = st.recording_summary(made.dir, line)
    frames = stand_in_decode(made.dir / "sigsim.log", made.db)
    assert st.check_summary_counts(summ["trip"], frames) == summ["trip"]["messages"]
    v_sig, a_sig = C.SLOT_DBC_SIGNALS[0], C.SLOT_DBC_SIGNALS[1]
    win = rc.expected_windows(summ["trip"], frames, v_sig, C.DBC_PERIOD_MS[C.RULE26_DBC_MESSAGE])
    pred = rc.predict(frames, v_sig, a_sig, rc.hazard_module())
    assert len(pred) == 2 and pred[0]["hazard"] and not pred[1]["hazard"]
    assert rc.in_window(pred[0]["t_rec_ms"], win["on_window_ms"]) and rc.in_window(pred[1]["t_rec_ms"], win["off_window_ms"])
    src_frames = stand_in_decode(SRC / "sigsim.log", made.db)
    assert pred == rc.predict(src_frames, v_sig, a_sig, rc.hazard_module())
    assert win == rc.expected_windows(summ["trip"], src_frames, v_sig, C.DBC_PERIOD_MS[C.RULE26_DBC_MESSAGE])
    # summary.json: the source's trip cut to the fields that still describe the file, the rest named as dropped
    src_trip = jload(SRC / "summary.json")["trip"]
    whole = jload(made.dir / "summary.json")
    assert set(whole["trip"]) == set(inj.TRIP_KEPT) & set(src_trip) and all(whole["trip"][k] == src_trip[k] for k in whole["trip"])
    assert whole["rewrite"]["trip_fields_dropped"] == sorted(set(src_trip) - set(inj.TRIP_KEPT))
    assert {"v_range", "a_range", "delta_range", "gear_changes"} <= set(whole["rewrite"]["trip_fields_dropped"])
    assert set(whole["rewrite"]) == SIGSIM_REWRITE_KEYS          # a sigsim rewrite names nothing as not copied
    # the line: the source's, with its own name, path and sha256, and the rewrite named in three params
    src_line = jload(SRC / "manifest-line.json")
    params = line["source"]["params"]
    assert {k: v for k, v in params.items() if not k.startswith("rewrite_")} == src_line["source"]["params"]
    assert params["rewrite_of"] == src_line["name"] and params["rewrite_of_sha256"] == src_line["recording"]["sha256"]
    assert params["rewrite_events_sha256"] == hashlib.sha256((made.dir / "events.json").read_bytes()).hexdigest()
    assert len(params) <= inj.PARAMS_MAX and all(len(str(v)) <= inj.PARAM_LEN_MAX for v in params.values())
    assert set(line) == set(src_line) and set(line["source"]) == set(src_line["source"])
    assert "rtf" not in line["source"]                          # a sigsim line has none (manifest-classes.md section 4)
    assert "rtf" not in made.doc["rewritten_from"]              # nor does a sigsim rewrite's events.json
    assert line["source"]["vehicle"] == src_line["source"]["vehicle"] and line["profile_id"] == src_line["profile_id"]
    assert line["recording"]["path"] == str(made.dir / "sigsim.log")
    assert (made.dir / "sigsim.log.sha256").read_text(encoding="ascii") == "%s  sigsim.log\n" % made.out["sha256"]
    doc = made.doc
    assert doc["format"] == inj.EVENTS_FORMAT
    assert doc["recording"]["sha256"] == made.out["sha256"] and doc["rewritten_from"]["log_sha256"] == src_line["recording"]["sha256"]
    assert doc["contract"]["digest"] == "0x%08X" % C.CATALOG_DIGEST and doc["dbc_sha256"] == src_line["source"]["params"]["dbc_sha256"]


# ============================================================ check

def put_events(rec, doc):
    """events.json rewritten, and the two hashes that name it (manifest line, summary) made to match."""
    raw = (json.dumps(doc, sort_keys=True, indent=1) + "\n").encode("ascii")
    (rec / "events.json").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    line = jload(rec / "manifest-line.json")
    line["source"]["params"]["rewrite_events_sha256"] = sha
    (rec / "manifest-line.json").write_text(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
    summ = jload(rec / "summary.json")
    summ["rewrite"]["events_sha256"] = sha
    (rec / "summary.json").write_text(json.dumps(summ, sort_keys=True, indent=1) + "\n", encoding="ascii")


def test_check_passes_on_the_new_directory_and_fails_on_a_tampered_copy(made, tmp_path):
    res = inj.check(made.dir, made.db, C, bs.SLICE_DBC)
    assert res["ok"] and res["runs"] == {run: [(e["event"], e["reason"]) for e in run_list(made.doc, run)] for run in RUNS}
    assert res["source"]["diff"] == {e["event"]: e["rewrite"]["frames"] for e in made.doc["events"]}
    bad = tmp_path / NAME
    shutil.copytree(made.dir, bad)
    doc = jload(bad / "events.json")
    doc["events"][0]["reason"] = rules.RSN_VSS_ACCEL          # a reason the replay does not give
    raw = (json.dumps(doc, sort_keys=True, indent=1) + "\n").encode("ascii")
    (bad / "events.json").write_bytes(raw)
    with pytest.raises(inj.InjectError, match="events.json's sha256"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)
    put_events(bad, doc)
    with pytest.raises(inj.InjectError, match="the replay gives 23, events.json says 24"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)
    doc = jload(made.dir / "events.json")
    doc["runs"]["stop"]["events"][0]["t1_ns"] += vb.TICK_NS     # a first 22 window that is not the design's
    doc["runs"]["stop"]["events"][1]["t0_ns"] += vb.TICK_NS
    put_events(bad, doc)
    with pytest.raises(inj.InjectError, match="the stop run's 22 windows are not the design's"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)


def test_check_refuses_another_format_another_contract_and_another_dbc(made, tmp_path):
    bad = tmp_path / NAME
    shutil.copytree(made.dir, bad)
    doc = jload(made.dir / "events.json")
    put_events(bad, dict(doc, format=1))
    with pytest.raises(inj.InjectError, match="format 1"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)
    put_events(bad, dict(doc, contract=dict(doc["contract"], sha256="0" * 64)))
    with pytest.raises(inj.InjectError, match="another contract"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)
    put_events(bad, dict(doc, dbc_sha256="0" * 64))
    with pytest.raises(inj.InjectError, match="names another DBC"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)
    other = tmp_path / "slice.dbc"
    other.write_text(tsbs.SLICE_TEXT + "\n// another file, the same body\n", encoding="utf-8")
    with pytest.raises(vb.BridgeError, match="not the one the contract was generated from"):
        inj.check(made.dir, made.db, C, other)


def test_check_warns_and_skips_the_source_diff_when_the_source_is_gone(made, tmp_path, capsys):
    rec = tmp_path / NAME
    shutil.copytree(made.dir, rec)
    doc = jload(made.dir / "events.json")
    gone = tmp_path / "gone"
    put_events(rec, dict(doc, rewritten_from=dict(doc["rewritten_from"], dir=str(gone))))
    res = inj.check(rec, made.db, C, bs.SLICE_DBC)
    assert res["ok"] and "diff" not in res["source"] and str(gone) in res["source"]["skipped"]
    assert "warning" in capsys.readouterr().err


# ============================================================ the sim venv: real cantools and python-can

SIM_SCRIPT = r"""
import json, sys
sys.dont_write_bytecode = True
inject_dir, stack_dir, rec, src = sys.argv[1:5]
sys.path[:0] = [inject_dir, stack_dir]
import can, cantools
import inject as inj
import stack as st
import attribution as attr
rc = st.rc
line = json.load(open(rec + "/manifest-line.json"))
dbc = st.resolve_dbc(line["source"]["params"]["dbc_sha256"])["path"]
db = cantools.database.load_file(dbc, strict=True)
n = 0
for m in can.LogReader(rec + "/sigsim.log"):
    db.get_message_by_frame_id(m.arbitration_id).decode(bytes(m.data), decode_choices=False)
    n += 1
mapping = attr.dbc2vss_entries(json.load(open(str(st.GEN / "vss-can-mapping.json"))))
tf = {p: attr.transform_function(b) for p, b in mapping.items()}
out = {"frames": n}
for name, d in (("rec", rec), ("src", src)):
    summ = st.recording_summary(__import__("pathlib").Path(d), json.load(open(d + "/manifest-line.json")))
    dec = rc.decode_recording(__import__("pathlib").Path(d + "/sigsim.log"), __import__("pathlib").Path(dbc), mapping, tf)
    counts = st.check_summary_counts(summ["trip"], dec["frames"])
    c = inj.vf.load_contract()
    win = rc.expected_windows(summ["trip"], dec["frames"], mapping[rc.V_PATH]["signal"], int(c.DBC_PERIOD_MS[c.RULE26_DBC_MESSAGE]))
    pred = rc.predict(dec["frames"], mapping[rc.V_PATH]["signal"], mapping[rc.A_PATH]["signal"], rc.hazard_module())
    out[name] = {"counts": counts, "windows": win, "prediction": pred}
print(json.dumps(out))
"""


def sim(*args, timeout=300):
    return subprocess.run([str(SIM_PY), *map(str, args)], capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), cwd=str(REPO))


@tsbs.NEEDS_SIM
def test_real_cantools_decodes_every_frame_and_the_stacks_decode_path_agrees(made):
    r = sim("-c", SIM_SCRIPT, INJECT_DIR, STACK_DIR, made.dir, SRC)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["frames"] == len(bs.read_candump(made.dir / "sigsim.log"))
    assert out["rec"]["counts"] == out["src"]["counts"]
    assert out["rec"]["windows"] == out["src"]["windows"] and out["rec"]["prediction"] == out["src"]["prediction"]
    assert len(out["rec"]["prediction"]) == 2


@tsbs.NEEDS_SIM
def test_the_command_line_with_real_cantools_writes_the_same_recording_and_its_check_passes(made, tmp_path):
    dest = tmp_path / NAME
    r = sim(INJECT_DIR / "inject.py", "rewrite", "--from", SRC, "--name", NAME, "--out", dest)
    assert r.returncode == 0, r.stderr[-3000:]
    assert (dest / "sigsim.log").read_bytes() == (made.dir / "sigsim.log").read_bytes()
    doc = jload(dest / "events.json")
    assert doc["events"] == made.doc["events"] and doc["runs"] == made.doc["runs"]
    assert jload(dest / "manifest-line.json")["recording"]["path"] == str(dest / "sigsim.log")
    r = sim(INJECT_DIR / "inject.py", "check", dest)
    assert r.returncode == 0, r.stderr[-3000:]
    assert json.loads(r.stdout)["ok"] is True
    r = sim(INJECT_DIR / "inject.py", "rewrite", "--from", SRC, "--name", NAME, "--out", dest)
    assert r.returncode == 1 and "FileExistsError" in r.stderr, r.stderr[-2000:]
    assert tree_hashes(SRC) == SOURCE_BEFORE


@pytest.mark.skipif(not (MADE / "events.json").is_file(), reason="the WP10 recording %s is not there" % MADE)
def test_the_recording_made_for_wp10_checks_and_equals_a_fresh_rewrite(made):
    res = inj.check(MADE, made.db, C, bs.SLICE_DBC)
    assert res["ok"] and "diff" in res["source"]
    assert (MADE / "sigsim.log").read_bytes() == (made.dir / "sigsim.log").read_bytes()
    doc = jload(MADE / "events.json")
    assert doc["events"] == made.doc["events"] and doc["runs"] == made.doc["runs"]
    # The recording names the reference inject.py. A fresh rewrite names the current tool. The next test checks
    # the rest of a sigsim rewrite.
    assert doc["tool"] == {"path": "sdv/inject/inject.py", "sha256": WP10_TOOL_SHA256}
    assert made.doc["tool"] == {"path": "sdv/inject/inject.py", "sha256": inj.tool_sha256()}
    assert jload(MADE / "manifest-line.json")["recording"]["path"] == "~/sdv-recordings/%s/sigsim.log" % NAME
    for run in RUNS:
        check_run(MADE / "sigsim.log", made.db, doc, jload(MADE / "manifest-line.json"), run)


def dump_doc(doc):
    """events.json's and summary.json's form, as inject.write writes them."""
    return (json.dumps(doc, sort_keys=True, indent=1) + "\n").encode("ascii")


def dump_line(line):
    """manifest-line.json's form (compact, sorted keys), as inject.write writes it."""
    return (json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


@pytest.mark.skipif(not (MADE / "events.json").is_file(), reason="the WP10 recording %s is not there" % MADE)
def test_a_sigsim_rewrite_is_the_wp10_recording_byte_for_byte_but_for_two_hashes(made):
    """Phase 7 spec 6 item 3: a sigsim source's output is unchanged. The fresh rewrite's five files against the WP10
    recording's, byte for byte, once two hashes are put to this tree's values: the tool's sha256 (the recording names
    the inject.py it was made with) and the contract's (the generation's identity, held by `check` in the test above,
    so that a generation which leaves profile 1 and the digest alone leaves this test green). Everything else that
    differs follows from those two and the directory: events.json's sha256 in the line and in summary.json, the
    tool in summary.json, the line's path and summary.json's dir. Each stored file is first shown to be in the form
    the writer writes, so the comparison is of bytes, not of a re-serialisation."""
    for n in ("sigsim.log", "sigsim.log.sha256"):
        assert (made.dir / n).read_bytes() == (MADE / n).read_bytes(), n
    assert sorted(p.name for p in made.dir.iterdir()) == sorted(p.name for p in MADE.iterdir())
    raw = {n: (MADE / n).read_bytes() for n in ("events.json", "summary.json", "manifest-line.json")}
    old = {n: json.loads(b.decode("ascii")) for n, b in raw.items()}
    assert dump_doc(old["events.json"]) == raw["events.json"] and dump_doc(old["summary.json"]) == raw["summary.json"]
    assert dump_line(old["manifest-line.json"]) == raw["manifest-line.json"]
    assert old["events.json"]["tool"]["sha256"] == WP10_TOOL_SHA256
    tool = {"path": "sdv/inject/inject.py", "sha256": inj.tool_sha256()}
    want_events = dict(old["events.json"], tool=tool, contract=dict(old["events.json"]["contract"], sha256=vb.contract_sha256(C)))
    new_events = (made.dir / "events.json").read_bytes()
    assert new_events == dump_doc(want_events)
    events_sha = hashlib.sha256(new_events).hexdigest()
    summ = old["summary.json"]
    want_summary = dict(summ, dir=str(made.dir), rewrite=dict(summ["rewrite"], events_sha256=events_sha, tool=tool))
    assert (made.dir / "summary.json").read_bytes() == dump_doc(want_summary)
    line = old["manifest-line.json"]
    want_line = dict(line, recording=dict(line["recording"], path=str(made.dir / "sigsim.log")),
                     source=dict(line["source"], params=dict(line["source"]["params"], rewrite_events_sha256=events_sha)))
    assert (made.dir / "manifest-line.json").read_bytes() == dump_line(want_line)


# ============================================================ refusals: nothing written

def test_an_existing_destination_is_refused_and_left_as_it_was(made, tmp_path):
    built = inj.build(SRC, NAME, made.db, C, bs.SLICE_DBC)
    dest = tmp_path / NAME
    dest.mkdir()
    (dest / "keep").write_text("somebody's", encoding="ascii")
    with pytest.raises(FileExistsError):
        inj.write(built, dest)
    assert sorted(p.name for p in dest.iterdir()) == ["keep"]


def test_a_failure_while_writing_removes_what_was_written(made, tmp_path, monkeypatch):
    built = inj.build(SRC, NAME, made.db, C, bs.SLICE_DBC)

    def boom(*_a, **_k):
        raise OSError("no space left (simulated)")

    monkeypatch.setattr(inj, "manifest_line", boom)
    with pytest.raises(OSError, match="simulated"):
        inj.write(built, tmp_path / NAME)
    assert not (tmp_path / NAME).exists() and tree_hashes(SRC) == SOURCE_BEFORE


def test_a_destination_inside_the_repository_or_misnamed_is_refused(made, tmp_path):
    built = inj.build(SRC, NAME, made.db, C, bs.SLICE_DBC)
    inside = REPO / "sdv-out" / NAME
    with pytest.raises(inj.InjectError, match="inside the repository"):
        inj.write(built, inside)
    assert not inside.exists()
    with pytest.raises(inj.InjectError, match="not named"):
        inj.write(built, tmp_path / "other-name")
    assert not (tmp_path / "other-name").exists()


def test_a_source_that_does_not_check_a_reused_name_and_a_foreign_dbc_are_refused(made, tmp_path):
    copy = tmp_path / "src"
    shutil.copytree(SRC, copy)
    log = copy / "sigsim.log"
    raw = bytearray(log.read_bytes())
    raw[-2] ^= 1                                               # one hex digit of the last frame
    log.write_bytes(bytes(raw))
    with pytest.raises(inj.InjectError, match="hashes to"):
        inj.build(copy, NAME, made.db, C, bs.SLICE_DBC)
    with pytest.raises(inj.InjectError, match="a name of its own"):
        inj.build(SRC, jload(SRC / "manifest-line.json")["name"], made.db, C, bs.SLICE_DBC)
    with pytest.raises(inj.InjectError, match="not a manifest-line name"):
        inj.build(SRC, "Not_A_Name", made.db, C, bs.SLICE_DBC)
    other = tmp_path / "slice.dbc"
    other.write_text(tsbs.SLICE_TEXT + "\n// another file\n", encoding="utf-8")
    with pytest.raises(vb.BridgeError, match="not the one the contract was generated from"):
        inj.build(SRC, NAME, made.db, C, other)
    assert not list(tmp_path.glob(NAME)) and tree_hashes(SRC) == SOURCE_BEFORE


def test_a_source_whose_line_names_another_dbc_or_another_catalogue_digest_is_refused(made, tmp_path):
    """build's own two refusals behind the DBC's generation check: the DBC given is the contract's generation, but the
    source's manifest line says it was encoded with another DBC, or made for another catalogue digest. The copy's
    line is edited in its params only (read_source holds the line to the log's sha256, which is unchanged)."""
    line = jload(SRC / "manifest-line.json")
    syn_sha, syn_digest = "0" * 64, "0x00000001"        # synthetic: neither is the generation's
    assert line["source"]["params"]["dbc_sha256"] != syn_sha and "0x%08X" % C.CATALOG_DIGEST != syn_digest
    for key, value, why in (("dbc_sha256", syn_sha, "not the one the source was encoded with"),
                            ("catalog_digest", syn_digest, "catalogue digest %s, the contract's is" % syn_digest)):
        copy = tmp_path / key
        shutil.copytree(SRC, copy)
        edited = json.loads(json.dumps(line))
        edited["source"]["params"][key] = value
        (copy / "manifest-line.json").write_text(json.dumps(edited, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
        inj.read_source(copy)                                   # the copy itself checks: only build's refusal is left
        with pytest.raises(inj.InjectError, match=why):
            inj.build(copy, NAME, made.db, C, bs.SLICE_DBC)
    assert not list(tmp_path.rglob(NAME)) and tree_hashes(SRC) == SOURCE_BEFORE


# ============================================================ a CARLA source (Phase 7 WP3a)

def carla_shaped(root, generator="carla", log=CARLA_LOG, rtf=SYN_RTF, extra_params=None, decoy=False, path=None, trip_rtf=None):
    """A CARLA-shaped source built from the sigsim recording (Phase 7 spec 6 item 4), in a new directory under root,
    returned: the sigsim log's bytes under the log name given, with its .sha256 in sha256sum's form; a synthetic
    steps.jsonl; a line with the generator given, the five params of a CARLA line (spec 2.3: the source's catalogue
    digest and DBC sha256, its seed, the town and the version) and any extra, the rtf given (none when None), CARLA's
    blueprint as the vehicle with profile 1's wheelbase, profile 1, and the recording.path given (by default the
    ~/sdv-recordings form of spec 2.3); summary.json the source's with its trip made CARLA-shaped (the line's params,
    the rtf, or trip_rtf when given, the time base, no gaps, a take and an encoder entry), sigsim's verify block kept, so
    the yaw event's counter is the recording's own. decoy adds a sigsim.log that is not the log."""
    src_line = jload(SRC / "manifest-line.json")
    seed = src_line["source"]["params"]["seed"]
    name = "20261017-carla-%d" % seed
    d = Path(root) / name
    d.mkdir()
    raw = (SRC / "sigsim.log").read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    (d / log).write_bytes(raw)
    (d / (log + ".sha256")).write_bytes(("%s  %s\n" % (sha, log)).encode("ascii"))
    (d / "steps.jsonl").write_bytes(b'{"i": 0, "synthetic": true}\n')
    if decoy:
        (d / "sigsim.log").write_bytes(b"not the log of this recording\n")
    params = {"catalog_digest": src_line["source"]["params"]["catalog_digest"], "dbc_sha256": src_line["source"]["params"]["dbc_sha256"],
              "seed": seed, "town": CARLA_TOWN, "version": CARLA_VERSION}
    params.update(extra_params or {})
    source = {"generator": generator, "params": params, "vehicle": {"name": CARLA_BLUEPRINT, "wheelbase_mm": profile()["l_mm"]}}
    if rtf is not None:
        source["rtf"] = rtf
    line = {"name": name, "profile_id": profile()["id"], "source": source,
            "recording": {"format": "candump-log", "path": path or "~/sdv-recordings/%s/%s" % (name, log), "sha256": sha}}
    (d / "manifest-line.json").write_bytes(dump_line(line))
    summ = jload(SRC / "summary.json")
    summ.update(name=name, dir=str(d))
    summ["trip"].update(params=dict(params), gaps=[], timestamps=CARLA_TIMESTAMPS, take={"name": name, "take_sha256": "0" * 64},
                        encoder_sha256={"sdv/carla/encode.py": "0" * 64})
    if rtf is not None or trip_rtf is not None:
        summ["trip"]["rtf"] = rtf if trip_rtf is None else trip_rtf
    (d / "summary.json").write_bytes(dump_doc(summ))
    return d


@pytest.fixture(scope="module")
def carla(tmp_path_factory, made):
    src = carla_shaped(tmp_path_factory.mktemp("carla-src"))
    before = tree_hashes(src)
    name = src.name + "-inj"
    built = inj.build(src, name, made.db, C, bs.SLICE_DBC)
    dest = tmp_path_factory.mktemp("carla-rec") / name
    out = inj.write(built, dest)
    yield types.SimpleNamespace(src=src, dir=dest, name=name, out=out, before=before, after=tree_hashes(src),
                                doc=jload(dest / "events.json"), line=jload(dest / "manifest-line.json"),
                                summary=jload(dest / "summary.json"))
    assert tree_hashes(src) == before, "the CARLA-shaped source changed"


def test_a_carla_source_is_rewritten_into_its_own_log_with_its_rtf_and_eight_params_and_checks(made, carla):
    """Spec 6 items 1, 2 and 4: the new recording keeps the source's log name, the frames and the events are the sigsim
    rewrite's (the tool reads frames, not names), the line's rtf is the source's unchanged and events.json's
    rewritten_from records it, its params are the source's five and the rewrite's three, summary.json's trip keeps the
    rtf, the time base and the gaps (each still true of a file whose frames did not move), steps.jsonl is not copied
    and summary.json says so; `check` passes and diffs the rewrite against the source's own carla.log."""
    assert sorted(p.name for p in carla.dir.iterdir()) == sorted(
        [CARLA_LOG, CARLA_LOG + ".sha256", "events.json", "summary.json", "manifest-line.json"])
    assert (carla.dir / CARLA_LOG).read_bytes() == (made.dir / "sigsim.log").read_bytes()
    assert (carla.dir / (CARLA_LOG + ".sha256")).read_text(encoding="ascii") == "%s  %s\n" % (carla.out["sha256"], CARLA_LOG)
    assert carla.doc["events"] == made.doc["events"] and carla.doc["runs"] == made.doc["runs"]
    assert carla.doc["recording"] == {"name": carla.name, "log": CARLA_LOG, "sha256": carla.out["sha256"]}
    src_line = jload(carla.src / "manifest-line.json")
    line = carla.line
    assert line["source"]["generator"] == "carla" and line["recording"]["path"] == str(carla.dir / CARLA_LOG)
    assert line["source"]["rtf"] == src_line["source"]["rtf"] == SYN_RTF
    assert dump_line(line["source"]["rtf"]) == dump_line(SYN_RTF)              # the same text: no figure rounded
    assert carla.doc["rewritten_from"]["rtf"] == SYN_RTF                         # the rtf the rewrite copied, on record
    params = line["source"]["params"]
    assert len(src_line["source"]["params"]) == 5 and len(params) == inj.PARAMS_MAX
    assert {k: v for k, v in params.items() if not k.startswith("rewrite_")} == src_line["source"]["params"]
    assert params["rewrite_of"] == src_line["name"] and params["rewrite_of_sha256"] == src_line["recording"]["sha256"]
    assert params["rewrite_events_sha256"] == hashlib.sha256((carla.dir / "events.json").read_bytes()).hexdigest()
    assert line["source"]["vehicle"] == src_line["source"]["vehicle"] and line["profile_id"] == src_line["profile_id"]
    src_trip = jload(carla.src / "summary.json")["trip"]
    summ = carla.summary
    assert set(summ["trip"]) == set(inj.TRIP_KEPT) & set(src_trip) and {"rtf", "timestamps", "gaps"} <= set(summ["trip"])
    assert summ["trip"]["rtf"] == SYN_RTF and all(summ["trip"][k] == src_trip[k] for k in summ["trip"])
    assert {"gear_changes", "take", "encoder_sha256"} <= set(summ["rewrite"]["trip_fields_dropped"])
    assert "gaps" not in summ["rewrite"]["trip_fields_dropped"]
    assert set(summ["rewrite"]) == SIGSIM_REWRITE_KEYS | {"not_copied"}
    assert list(summ["rewrite"]["not_copied"]) == ["steps.jsonl"] and "regenera" in summ["rewrite"]["not_copied"]["steps.jsonl"]
    res = inj.check(carla.dir, made.db, C, bs.SLICE_DBC)
    assert res["ok"] and res["runs"] == {run: [(e["event"], e["reason"]) for e in run_list(carla.doc, run)] for run in RUNS}
    assert res["source"]["diff"] == {e["event"]: e["rewrite"]["frames"] for e in carla.doc["events"]}
    assert carla.before == carla.after == tree_hashes(carla.src)


def test_a_stray_sigsim_log_beside_a_carla_log_is_never_read(made, tmp_path):
    """The log is the one the line names: a sigsim.log beside carla.log (bytes that are no log at all) changes nothing,
    the frames rewritten are the sigsim rewrite's, and the new recording has no sigsim.log. (No module fixture: a
    tool that reads the wrong log fails here, not at a fixture's setup.)"""
    src = carla_shaped(tmp_path, decoy=True)
    name = src.name + "-inj"
    built = inj.build(src, name, made.db, C, bs.SLICE_DBC)
    assert "sigsim.log" not in built.source.hashes and built.log_text.encode("ascii") == (made.dir / "sigsim.log").read_bytes()
    (tmp_path / "out").mkdir()
    inj.write(built, tmp_path / "out" / name)
    assert sorted(p.name for p in (tmp_path / "out" / name).iterdir()) == sorted(
        [CARLA_LOG, CARLA_LOG + ".sha256", "events.json", "summary.json", "manifest-line.json"])


def test_check_refuses_a_carla_rewrite_whose_rtf_or_log_is_not_its_own(made, carla, tmp_path, capsys):
    """The rewrite copies the rtf unchanged into the line and into events.json's rewritten_from, and `check` holds the
    line's rtf to summary.json's trip rtf, to events.json's and, when the source is there, to the source's. A line
    whose rtf alone was changed (still well formed) fails the first; one changed with its summary fails the second,
    with the source there and with it gone (where nothing else would see it: the rtf becomes the run header's
    source_rtf); one changed in all three fails the source's. A line with its rtf dropped fails the rtf rule itself;
    an events file that names another log than the recording's names another recording."""
    other = dict(SYN_RTF, mean=0.95)                                 # a well-formed rtf that is not the source's
    doc = jload(carla.dir / "events.json")

    def set_rtf(rec, summary=False):
        ln = jload(rec / "manifest-line.json")
        (rec / "manifest-line.json").write_bytes(dump_line(dict(ln, source=dict(ln["source"], rtf=other))))
        if summary:
            s = jload(rec / "summary.json")
            (rec / "summary.json").write_bytes(dump_doc(dict(s, trip=dict(s["trip"], rtf=other))))

    for where in ("there", "away"):
        bad = tmp_path / where / carla.name
        shutil.copytree(carla.dir, bad)
        if where == "away":                                          # the source gone, as check sees it
            put_events(bad, dict(doc, rewritten_from=dict(doc["rewritten_from"], dir=str(tmp_path / "no-source"))))
            res = inj.check(bad, made.db, C, bs.SLICE_DBC)
            assert res["ok"] and "diff" not in res["source"] and "warning" in capsys.readouterr().err
        set_rtf(bad)
        with pytest.raises(inj.InjectError, match="summary.json's trip rtf .* is not the manifest line's"):
            inj.check(bad, made.db, C, bs.SLICE_DBC)
        set_rtf(bad, summary=True)
        with pytest.raises(inj.InjectError, match="the manifest line's rtf .* is not the one events.json says the rewrite copied"):
            inj.check(bad, made.db, C, bs.SLICE_DBC)
    bad = tmp_path / "there" / carla.name                            # its line and summary carry the other rtf
    put_events(bad, dict(doc, rewritten_from=dict(doc["rewritten_from"], rtf=other)))
    with pytest.raises(inj.InjectError, match="rtf .* is not its source's"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)
    bad = tmp_path / carla.name
    shutil.copytree(carla.dir, bad)
    line = jload(carla.dir / "manifest-line.json")
    (bad / "manifest-line.json").write_bytes(dump_line(dict(line, source={k: v for k, v in line["source"].items() if k != "rtf"})))
    with pytest.raises(inj.InjectError, match="a carla source has no rtf"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)
    (bad / "manifest-line.json").write_bytes(dump_line(line))
    doc = jload(carla.dir / "events.json")
    put_events(bad, dict(doc, recording=dict(doc["recording"], log="sigsim.log")))
    with pytest.raises(inj.InjectError, match="events.json names another recording"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)


def test_check_refuses_a_carla_rewrite_whose_events_file_has_no_rtf_record(made, carla, tmp_path):
    """`check` holds the line's rtf to the one events.json records always: an events file whose rewritten_from lost its
    rtf (its sha256 put back into the line and the summary) is refused, though the source is there and agrees."""
    bad = tmp_path / carla.name
    shutil.copytree(carla.dir, bad)
    doc = jload(carla.dir / "events.json")
    put_events(bad, dict(doc, rewritten_from={k: v for k, v in doc["rewritten_from"].items() if k != "rtf"}))
    with pytest.raises(inj.InjectError, match="the manifest line's rtf .* is not the one events.json says the rewrite copied"):
        inj.check(bad, made.db, C, bs.SLICE_DBC)


@pytest.mark.parametrize("extra, why", [
    pytest.param({"spawn_index": 64}, "would carry 9 values", id="sixth-param"),                     # 6 + 3 > 8
    pytest.param({"town": "t" * 65}, r"\['town'\] longer than 64 characters", id="long-value"),      # five, one too long
    pytest.param({"spawn_index": 64, "weather": "clear", "layers": "all"}, "would carry 11 values", id="eight-params"),
    pytest.param({"version": "v" * 65}, r"\['version'\] longer than 64 characters", id="long-version"),
    pytest.param({"spawn_index": 64, "town": "t" * 65}, r"would carry 9 values.*\['town'\] longer than 64 characters", id="both"),
    pytest.param({"town": 1.5}, r"source.params \['town'\] are not integers or strings", id="float-value"),
    pytest.param({"town": True}, r"source.params \['town'\] are not integers or strings", id="bool-value"),
    pytest.param({"town": None}, r"source.params \['town'\] are not integers or strings", id="null-value"),
    pytest.param({"town": ["Town01"]}, r"source.params \['town'\] are not integers or strings", id="list-value"),
    pytest.param({"version": 916.0, "town": {"name": "Town01"}}, r"source.params \['town', 'version'\] are not integers or strings",
                 id="two-values"),
])
def test_a_source_whose_params_would_break_the_scenario_entrys_limits_is_refused_before_anything_is_written(made, tmp_path, extra, why):
    """Spec 6 item 2: source.params at most eight (manifest-classes.md section 4) once the rewrite's three are added,
    each an integer or a string, a string at most 64 characters (its section 9 schema): refused by build, before any
    directory exists (the source itself checks)."""
    src = carla_shaped(tmp_path, extra_params=extra)
    inj.read_source(src)
    with pytest.raises(inj.InjectError, match=why):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_param_is_an_integer_of_any_size_or_a_string():
    """The scenario entry's params are integers or strings (manifest-classes.md section 9: type [integer, string]): a
    bool (an int to Python, not to JSON), a float (1.0 too), null, a list or an object is refused, each key named. The
    schema bounds no integer, so neither does this: a 70-digit integer is taken, as zero and a negative one are."""
    assert inj.params_problems({"seed": 10 ** 70, "town": "Town01", "zero": 0, "below": -1}) == []
    assert inj.params_problems({"a": True, "b": 1.0, "c": None, "d": [], "e": {}}) == [
        "source.params ['a', 'b', 'c', 'd', 'e'] are not integers or strings"]


def test_a_manifest_line_whose_params_is_not_an_object_is_refused(made, tmp_path, capsys):
    """A source whose source.params is not a JSON object is refused when it is read, as an InjectError, before anything
    is written: not an AttributeError at the seed's read, which the command line printed as a traceback with no
    refusal line. params_problems keeps its own guard for a caller that hands it one."""
    src = carla_shaped(tmp_path)
    line = jload(src / "manifest-line.json")
    for params in (["seed", 7], "seed=7", 7, None):
        (src / "manifest-line.json").write_bytes(dump_line(dict(line, source=dict(line["source"], params=params))))
        with pytest.raises(inj.InjectError, match="its manifest line's source.params is not an object"):
            inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    dest = tmp_path / "out" / (src.name + "-inj")
    assert inj.main(["rewrite", "--from", str(src), "--name", dest.name, "--out", str(dest)], load_db=lambda _p, _c: made.db) == 1
    assert "inject: InjectError: " in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == [src.name]
    assert inj.params_problems(["seed", 7]) == ["source.params is not an object: ['seed', 7]"]


@pytest.mark.parametrize("body", [pytest.param(b"[1, 2]\n", id="a-list"), pytest.param(b"\"x\"\n", id="a-string"),
                                  pytest.param(b"3\n", id="a-number"), pytest.param(b"null\n", id="null")])
def test_a_summary_that_is_not_an_object_is_refused(made, tmp_path, body):
    """A source whose summary.json is not a JSON object (a list, a string, a number or null) is refused when it is
    read, as an InjectError (not an AttributeError, which the command line printed as a traceback), before anything
    is written."""
    src = carla_shaped(tmp_path)
    (src / "summary.json").write_bytes(body)
    with pytest.raises(inj.InjectError, match="its summary.json is not an object"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_param_of_exactly_64_characters_is_accepted(made, tmp_path):
    """The 64-character limit is inclusive (manifest-classes.md section 9's maxLength): a CARLA source whose town is 64
    characters long is rewritten, and its new line carries the value unchanged."""
    src = carla_shaped(tmp_path, extra_params={"town": "t" * 64})
    name = src.name + "-inj"
    built = inj.build(src, name, made.db, C, bs.SLICE_DBC)
    (tmp_path / "out").mkdir()
    inj.write(built, tmp_path / "out" / name)
    assert jload(tmp_path / "out" / name / "manifest-line.json")["source"]["params"]["town"] == "t" * 64


def test_the_params_limits_are_inclusive():
    """manifest-classes.md section 4's eight values and section 9's maxLength of 64, both inclusive, held without a
    fixture: the sigsim source's own params are five, two of them 64 characters long, so under a mutant that makes
    either limit exclusive every fixture errors at setup and no test fails."""
    five = {"a": 1, "b": 2, "c": 3, "d": 4, "e": "t" * 64}
    assert inj.params_problems(five) == []
    msg = "source.params would carry 9 values with the rewrite's 3, more than the scenario entry's 8"
    assert inj.params_problems(dict(five, f=6)) == [msg]
    assert inj.params_problems({"town": "t" * 65}) == ["source.params ['town'] longer than 64 characters"]


@pytest.mark.parametrize("key", [pytest.param(k, id=k) for k in ("rewrite_of", "rewrite_of_sha256", "rewrite_events_sha256")])
def test_a_source_that_already_carries_a_rewrite_param_is_refused_before_anything_is_written(made, tmp_path, key):
    """Spec 6 item 2: a source whose params would break the entry is refused before anything is written. A source of five
    params, one of them a rewrite's (a rewrite of a rewrite), passes the cap (5 + 3 = 8), so only the clash rule stops it
    here: build refuses it with the other params rules, and manifest_line's own check stays as the write-time guard, which
    would refuse it only after the new directory and some of its files existed. (A CARLA line's town gives way to the
    rewrite's key, to keep five.)"""
    src = carla_shaped(tmp_path)
    line = jload(src / "manifest-line.json")
    params = {k: v for k, v in line["source"]["params"].items() if k != "town"}
    params[key] = "x" * 8
    assert len(params) == 5
    (src / "manifest-line.json").write_bytes(dump_line(dict(line, source=dict(line["source"], params=params))))
    inj.read_source(src)                                          # the source itself checks: only build's refusal is left
    msg = "source.params already carry ['%s']: a rewrite of a rewrite is not supported" % key
    assert inj.params_problems(params) == [msg]
    with pytest.raises(inj.InjectError, match=r"would break the scenario entry's limits: source\.params already carry "
                                              r"\['%s'\]: a rewrite of a rewrite is not supported" % key):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


@pytest.mark.parametrize("generator, rtf, why", [
    pytest.param("carla", None, "a carla source has no rtf", id="no-rtf"),
    pytest.param("carla", dict(SYN_RTF, min=0.95), "does not hold min <= mean <= max", id="min-above-mean"),
    pytest.param("carla", dict(SYN_RTF, min=0), r"not a number above 0: \['min'\]", id="min-zero"),
    pytest.param("sigsim", SYN_RTF, "a sigsim source carries an rtf", id="sigsim-with-rtf"),
    pytest.param("carla", {"max": SYN_RTF["max"], "min": SYN_RTF["min"]}, r"is not \{min, mean, max\}", id="no-mean"),
    pytest.param("carla", dict(SYN_RTF, median=0.9), r"is not \{min, mean, max\}", id="extra-key"),
    pytest.param("carla", [0.5, 0.75, 1.0], r"is not \{min, mean, max\}", id="a-list"),
    pytest.param("carla", dict(SYN_RTF, max=True), r"not a number above 0: \['max'\]", id="max-bool"),
    pytest.param("carla", dict(SYN_RTF, mean="0.93"), r"not a number above 0: \['mean'\]", id="mean-string"),
    pytest.param("carla", dict(SYN_RTF, min=-0.5), r"not a number above 0: \['min'\]", id="min-negative"),
    pytest.param("carla", dict(SYN_RTF, max=float("inf")), r"not a number above 0: \['max'\]", id="max-infinite"),
    pytest.param("carla", dict(SYN_RTF, mean=1.01), "does not hold min <= mean <= max", id="mean-above-max"),
    pytest.param("carla", ["max", "mean", "min"], r"is not \{min, mean, max\}", id="key-name-list"),
])
def test_a_missing_or_malformed_rtf_is_refused(made, tmp_path, generator, rtf, why):
    """source.rtf as the scenario entry has it (manifest-classes.md section 4): required exactly for a carla source,
    {min, mean, max}, each a number above 0, min <= mean <= max. Refused when the source is read."""
    log = CARLA_LOG if generator == "carla" else "sigsim.log"
    src = carla_shaped(tmp_path, generator=generator, log=log, rtf=rtf)
    with pytest.raises(inj.InjectError, match=why):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_sigsim_line_whose_rtf_is_null_is_refused(made, tmp_path):
    """A sigsim line carries no rtf at all: one whose rtf is null is refused when it is read, before anything is
    written (not a TypeError when the rewrite copies it)."""
    src = carla_shaped(tmp_path, generator="sigsim", log="sigsim.log", rtf=None)
    line = jload(src / "manifest-line.json")
    (src / "manifest-line.json").write_bytes(dump_line(dict(line, source=dict(line["source"], rtf=None))))
    with pytest.raises(inj.InjectError, match="a sigsim source carries an rtf"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_carla_source_whose_summary_rtf_is_not_its_lines_is_refused(made, tmp_path):
    """summary.json's trip rtf, where the trip has one, is the line's (spec 2.3 puts the take's rtf in both): a source
    whose two differ is refused when it is read, before anything is written, so a rewrite never copies two rtfs that
    disagree into its line and its summary."""
    src = carla_shaped(tmp_path, trip_rtf=dict(SYN_RTF, mean=0.95))
    with pytest.raises(inj.InjectError, match="summary.json's trip rtf .* is not the manifest line's"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


@pytest.mark.parametrize("rtf", [
    pytest.param({"max": 0.8, "mean": 0.8, "min": 0.8}, id="all-equal"),
    pytest.param({"max": 1, "mean": 1, "min": 1}, id="integers"),
    pytest.param({"max": 1.4, "mean": 1.1, "min": 0.6}, id="max-above-1"),
])
def test_an_rtf_at_the_rules_edges_is_read(tmp_path, rtf):
    """source.rtf's rule at its edges (manifest-classes.md section 4): min <= mean <= max holds with equality, an
    integer is a number, and a max above 1 is not refused here (C12b flags every run of it): each is read."""
    src = carla_shaped(tmp_path, rtf=rtf)
    assert inj.read_source(src).line["source"]["rtf"] == rtf


def test_a_carla_trip_without_an_rtf_is_read(tmp_path):
    """summary.json's trip rtf is held to the line's only where the trip has one: a carla source whose trip carries
    none is read, its line's rtf as it is."""
    src = carla_shaped(tmp_path)
    summ = jload(src / "summary.json")
    del summ["trip"]["rtf"]
    (src / "summary.json").write_bytes(dump_doc(summ))
    assert inj.read_source(src).line["source"]["rtf"] == SYN_RTF


@pytest.mark.parametrize("generator, log, why", [
    pytest.param("carla", "recording.log", "the recording's log is 'recording.log': a carla recording's log is carla.log",
                 id="carla-recording-log"),
    pytest.param("carla", "sigsim.log", "the recording's log is 'sigsim.log': a carla recording's log is carla.log",
                 id="carla-sigsim-log"),
    pytest.param("planning-sim", CARLA_LOG, "the source's generator is 'planning-sim': this tool reads carla and sigsim "
                 "recordings only", id="planning-sim"),
    pytest.param("sigsim", CARLA_LOG, "the recording's log is 'carla.log': a sigsim recording's log is sigsim.log", id="sigsim-carla-log"),
    pytest.param("carla", "CARLA.log", "the recording's log is 'CARLA.log': a carla recording's log is carla.log", id="carla-upper-case"),
    pytest.param("carla", "carla.log.txt", "the recording's log is 'carla.log.txt': a carla recording's log is carla.log", id="carla-suffix"),
])
def test_a_log_name_that_is_not_its_generators_is_refused(made, tmp_path, generator, log, why):
    """Spec 6 item 1: the log is the basename of the line's recording.path, sigsim.log for sigsim and carla.log for
    carla (spec 2.3); any other name is refused, though the file is there and hashes as its line says, and so is a
    generator that has no log name here (the scenario entry's third, planning-sim)."""
    src = carla_shaped(tmp_path, generator=generator, log=log, rtf=SYN_RTF if generator == "carla" else None)
    with pytest.raises(inj.InjectError, match=why):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


@pytest.mark.parametrize("generator", [pytest.param(["carla"], id="a-list"), pytest.param({"carla": 1}, id="an-object"),
                                       pytest.param(None, id="null")])
def test_a_generator_that_is_not_a_string_is_refused(made, tmp_path, generator):
    """source.generator must be one this tool reads: one that is not a string is refused as an InjectError (not a
    TypeError at the log-name table), before anything is written."""
    src = carla_shaped(tmp_path)
    line = jload(src / "manifest-line.json")
    (src / "manifest-line.json").write_bytes(dump_line(dict(line, source=dict(line["source"], generator=generator))))
    with pytest.raises(inj.InjectError, match="this tool reads carla and sigsim recordings only"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_manifest_line_with_no_path_or_not_an_object_is_refused(made, tmp_path):
    """Spec 6 item 1: the log's name is the line's recording.path's basename, so a line that names no path, or is not
    a JSON object, is refused as an InjectError (not a TypeError or an AttributeError), before anything is written."""
    src = carla_shaped(tmp_path)
    line = jload(src / "manifest-line.json")
    no_path = dict(line, recording={k: v for k, v in line["recording"].items() if k != "path"})
    (src / "manifest-line.json").write_bytes(dump_line(no_path))
    with pytest.raises(inj.InjectError, match="names no recording.path"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    (src / "manifest-line.json").write_bytes(dump_line([line]))
    with pytest.raises(inj.InjectError, match="its manifest line is not an object"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_carla_source_whose_sha256_file_does_not_hold_is_refused(made, tmp_path):
    """Spec 6 item 1: the log's .sha256 beside it must hold for it, as sigsim.log.sha256 must for a sigsim source."""
    src = carla_shaped(tmp_path)
    (src / "carla.log.sha256").write_bytes(("%s  carla.log\n" % ("0" * 64)).encode("ascii"))
    with pytest.raises(inj.InjectError, match=r"carla\.log\.sha256 says 0{64}"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_scenario_entry_path_is_the_schemas():
    """manifest-classes.md section 9's path: ~ or /, then 1 to 255 characters of [A-Za-z0-9._/-], and no .. segment
    (both ends of the 255 held; a name of three dots is no .. segment)."""
    ok = ["~/sdv-recordings/n/carla.log", "/tmp/pytest-of-u/pytest-1/rec0/n/sigsim.log", "/" + "d/" * 123 + "carla.log",
          "~/a/.../carla.log", "/a"]
    bad = ["", "~", "/", "carla.log", "rel/carla.log", "~/a/../carla.log", "/..", "/a/..", "/a/b c/carla.log",
           "/" + "d/" * 123 + "xcarla.log", "C:/r/carla.log", "~/r/carla.log\n", None, 7]
    assert [p for p in ok if not inj.is_scenario_path(p)] == []
    assert [p for p in bad if inj.is_scenario_path(p)] == []


@pytest.mark.parametrize("path", [
    pytest.param("carla.log", id="bare-name"),
    pytest.param("rel/dir/carla.log", id="relative"),
    pytest.param("~/sdv-recordings/x/../carla.log", id="dot-dot"),
    pytest.param("/recordings/with space/carla.log", id="a-space"),
    pytest.param("C:/recordings/carla.log", id="a-drive"),
    pytest.param("/" + "d/" * 128 + "carla.log", id="too-long"),
])
def test_a_recording_path_that_is_not_a_scenario_entry_path_is_refused(made, tmp_path, path):
    """The line's recording.path is a scenario entry's path (manifest-classes.md section 9) whose basename is the log:
    one that is not is refused when the source is read, though its basename is carla.log and the log is there and
    hashes as the line says. (Its directory is not held to where the source lies: a recording may be copied.)"""
    src = carla_shaped(tmp_path, path=path)
    with pytest.raises(inj.InjectError, match="the recording.path .* is not a scenario entry path"):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]


def test_a_destination_whose_path_is_not_a_scenario_entry_path_is_refused(made, tmp_path):
    """The new line's path is a scenario entry path too, or `check` (and the manifest's loader) would refuse what
    `rewrite` wrote: a destination under a directory whose name holds a space is refused before it is created."""
    built = inj.build(SRC, NAME, made.db, C, bs.SLICE_DBC)
    parent = tmp_path / "with space"
    parent.mkdir()
    with pytest.raises(inj.InjectError, match="refused: the new recording's path .* is not a scenario entry path"):
        inj.write(built, parent / NAME)
    assert list(parent.iterdir()) == [] and tree_hashes(SRC) == SOURCE_BEFORE


def test_a_relative_destination_is_written_with_its_resolved_path(made, tmp_path, monkeypatch):
    """The destination's path is held to the scenario entry's as the line will carry it (path_form: resolved, or the
    ~ form under ~/sdv-recordings): a relative destination, as `--out rel/NAME` gives, is written, and its line's path
    is the resolved one."""
    built = inj.build(SRC, NAME, made.db, C, bs.SLICE_DBC)
    monkeypatch.chdir(tmp_path)
    Path("rel").mkdir()
    inj.write(built, Path("rel") / NAME)
    path = jload(tmp_path / "rel" / NAME / "manifest-line.json")["recording"]["path"]
    assert path == str(tmp_path.resolve() / "rel" / NAME / "sigsim.log") and inj.is_scenario_path(path)


@pytest.mark.parametrize("listed, why", [
    pytest.param("{sha}  sigsim.log\n", r"carla\.log\.sha256 names \['sigsim\.log'\], not carla\.log", id="sigsim-name"),
    pytest.param("{sha}  something.else\n", r"carla\.log\.sha256 names \['something\.else'\], not carla\.log", id="other-name"),
    pytest.param("{sha}  carla.log extra\n", r"carla\.log\.sha256 names \['carla\.log', 'extra'\], not carla\.log", id="two-names"),
])
def test_a_sha256_file_that_names_another_file_is_refused(made, tmp_path, listed, why):
    """The log's .sha256 is sha256sum's line for the log: the hash, and the log's own name where it gives one (spec 2.3:
    `<sha256>  carla.log`). One that names another file, or more than the log, is refused though its hash holds; one
    that gives the hash alone is read as the stack reads it (sdv/stack/stack.py recording_identity reads the hash)."""
    src = carla_shaped(tmp_path)
    sha = jload(src / "manifest-line.json")["recording"]["sha256"]
    (src / "carla.log.sha256").write_bytes(listed.format(sha=sha).encode("ascii"))
    with pytest.raises(inj.InjectError, match=why):
        inj.build(src, src.name + "-inj", made.db, C, bs.SLICE_DBC)
    assert [p.name for p in tmp_path.iterdir()] == [src.name]
    (src / "carla.log.sha256").write_bytes((sha + "\n").encode("ascii"))
    assert inj.read_source(src).log_name == CARLA_LOG


def test_the_stacks_own_checks_accept_a_carla_rewrite(made, carla):
    """The stack's provenance checks of a recording (as for the sigsim rewrite above) on the CARLA rewrite."""
    st = _stack()
    rc = st.rc
    line = st.recording_identity(carla.dir)["manifest_line"]
    assert line == carla.line
    assert st.recording_seed(line, None) == jload(carla.src / "manifest-line.json")["source"]["params"]["seed"]
    summ = st.recording_summary(carla.dir, line)
    frames = stand_in_decode(carla.dir / CARLA_LOG, made.db)
    assert st.check_summary_counts(summ["trip"], frames) == summ["trip"]["messages"]
    v_sig, a_sig = C.SLOT_DBC_SIGNALS[0], C.SLOT_DBC_SIGNALS[1]
    win = rc.expected_windows(summ["trip"], frames, v_sig, C.DBC_PERIOD_MS[C.RULE26_DBC_MESSAGE])
    pred = rc.predict(frames, v_sig, a_sig, rc.hazard_module())
    assert len(pred) == 2 and rc.in_window(pred[0]["t_rec_ms"], win["on_window_ms"])
    assert rc.in_window(pred[1]["t_rec_ms"], win["off_window_ms"])


def test_the_tool_imports_no_third_party_module_at_import_time():
    """cantools is imported only by the command line's DBC loader (the in-process path takes any database object)."""
    code = ("import sys; sys.dont_write_bytecode = True; sys.path.insert(0, %r); import inject; "
            "print(sorted(m for m in ('cantools', 'can', 'grpc', 'kuksa_client') if m in sys.modules))" % str(INJECT_DIR))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "[]", (r.stdout, r.stderr[-2000:])
