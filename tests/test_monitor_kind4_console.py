"""kind4-spec 16.1 C3, C4, C24-C27 and C29's C half: the vss monitor's console (sdv Phase 2, WP4).

Under MONITOR_EXT_KINDS & 0x10, monitor.c gains its console work (the kind 4 wire specification, sections
4.3 and 12; Phase 2 design decision a; the owner's cap of 11 per second, 2026-10-01):

- the startup self-check: after shmcfg and before any serving mode prints, FNV-1 over the five compiled UIDs,
  each serialised as four little-endian bytes by shifts, must be the compiled VSS_CATALOG_DIGEST; otherwise
  `monitor: vss contract inconsistent` on stderr, exit 2, no claim kinds line, nothing listens;
- the announcement right after the unchanged claim kinds line, in every serving mode: `monitor: vss rules:`
  and one `monitor: vss profile N:` line per compiled id, both from the compiled table;
- the kind 4 limiter: `monitor: REJECT seq=N kind=vss profile=P reason=NAME` only when the reason differs from
  the previous kind 4 frame's (an ACCEPT is reason 0); at most 11 such lines per one-second bucket of
  CLOCK_MONOTONIC; one `monitor: vss summary:` line per bucket with a suppressed line, its counters the
  bucket's own and `by reason:` its suppressed lines; and a session-end flush immediately before each
  transport's client done:, udp done:, shm quiet:, shm done:, shm-kick burst: and shm-kick done: line, which
  prints a pending summary and resets everything, rule 1's previous reason and the line count included;
- a compile-time guard: a profile row whose id is outside 1..255 does not compile (FOUND BY REVIEW, WP2+3: a
  hand-written row with id 0 was bound, while rules.Tables refuses id 0).

What is tested, and how:
- The limiter in tests/vss_driver.c's `log` mode, its clock scripted (deterministic): C24 (one reason
  persisting: one line, every other reject in a summary), C25 (alternating reasons: a bucket of 11 arrivals at
  the designed 10 Hz, one of them the frame queued behind a delayed reply, prints all 11 and no summary; a
  bucket of 12 puts exactly one into its summary), rule 1 against the previous FRAME's reason (not the last
  printed one, and an ACCEPT as 0), and C27's resets. Each scenario's output is written out here from the
  specification AND compared with limiter_model(), a stateful-input reference built differently from
  monitor.c on purpose (rules.py is stateless by design, so the limiter's reference lives here).
- End to end, where the monitor's own clock places the bucket edges, only what no edge can move: rule 1, which
  rejects print in a session small enough that the cap cannot bind, and lines + suppressed = rejected (C24, C25
  over UDP; C21 in tests/test_monitor_kind4.py). C26: kinds 0, 1 and unknown kinds are never limited and
  byte-identical to the default build's lines, and do not move kind 4's rule 1. C27 on every transport: TCP,
  stamp and svc (two connections), UDP, the shm slot (bursts ended by `shm quiet:`, the last one by the stop's
  `shm done:` whenever no quiet line came first) and shm-kick (two bursts over an ivshmem server and a kick
  socket); the sessions are split by the end lines' own counts, so a slow host that splits a shm burst
  changes the expectation, not the verdict. A text check pins each of the seven flush hooks right before its
  line.
- C3, C4: the opening lines of every serving mode in both builds; the formats from spec 12, the a_y bound's
  `%g m/s^2` form from a second build with test profiles; in both builds each compiled profile's ay_max is its
  generated row's, read from the contract's rows (since Phase 7 WP2 froze profile 3 the generated table holds a
  bounded profile, so this is no longer "no compiled profile has an a_y bound").
- C29's C half: the monitor's FNV-1 on spec 4.2's vectors, its UID serialisation on the little- and big-endian
  pair, and the self-check on the compiled contract. The exit-2 path: a temporary vss_contract.h with one UID
  (each slot in turn) or the digest edited.
- The clock read: run under an LD_PRELOAD counter of clock_gettime(), the UDP monitor reads the clock once per
  kind 4 frame and never for kinds 0, 1 or unknown, so the kind compare comes before now_ns().

What this does NOT show: anything about the guest build (qcc output cannot run here); any timing (the bucket
edges end to end are wherever the PC's clock puts them); the limiter under someip.c's two threads, which never
define the switch.

Needs gcc on Linux (WSL Ubuntu-24.04 or CI's tooling job) and the generated contract in sdv-out/gen; the shm
leg needs x86-64 (tests/monitor_corpus.py), the shm-kick leg Linux eventfds.
"""
import collections
import dataclasses
import mmap
import os
import random
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

import pytest

import monitor_corpus as mc
import test_monitor_kind4 as tmk
import test_monitor_vss as tmv
import test_sdv_frame as tsf

rules = tsf.rules
vf = tsf.vf
C = tsf.C
H = vf.FRAME_HEADER_BYTES

pytestmark = [tsf.NEEDS_CONTRACT, tmv.NEEDS_GEN]

CAP = 11                        # kind 4 REJECT lines per bucket (spec 12 item 3; the owner, 2026-10-01)
S = 1_000_000_000               # one bucket, ns (spec 12 item 2)
MS = 1_000_000

# Spec 12's formats and the claim kinds line, written out here, never read from monitor.c.
CLAIM_KINDS = "monitor: claim kinds: 0 mnist (us <= 100000), 1 vlm model 1 (us <= 1000000), conf_min=60%\n"
RULES_LINE = "monitor: vss rules: kind 4, catalog 0x%08X (vss %s), age_max %d ms, profiles %s\n"
PROFILE_LINE = ("monitor: vss profile %d: L %d mm, v_max %g m/s, a_max %g m/s^2, steer_max %g deg, "
                "yaw check %g..%g m/s ay_max %s tol %g deg/s, gear v_tol %g m/s\n")
REJECT_LINE = "monitor: REJECT seq=%d kind=vss profile=%d reason=%s\n"
SUMMARY_LINE = "monitor: vss summary: seen=%d rejected=%d suppressed=%d by reason:%s\n"
INCONSISTENT = "monitor: vss contract inconsistent\n"
MNIST_REJECT = "monitor: REJECT seq=%d class=10 conf=95 us=124 reason=class-out-of-range\n"

NAMES = dict(tsf.SPEC_NAMES)
NAMES[0] = "ok"

# Words of the lines the harnesses grep (spec 12: no announcement line may carry one).
HARNESS_WORDS = ("claim kinds:", "listening on", "serving shm", "stamping replies", "REJECT", "client done", "client closed",
                 "udp done", "shm quiet", "shm done", "shm-kick", "LIVENESS", "stopped")


def k4(seq, reason=0):
    """A kind 4 frame under the nominal profile that the oracle judges `reason` (0: an honest frame)."""
    f = tsf.honest() if reason == 0 else tsf._mutations()[reason](tsf.honest())
    f = tmk.with_seq(f, seq)
    assert rules.judge_frame(f, tsf.tables())[1] == reason
    return f


def mnist_reject(seq):
    return mc.mnist(seq, 10, 95, 124)          # class 10: kind 0, class-out-of-range


# ============================================================ builds

@pytest.fixture(scope="module")
def vss(tmp_path_factory):
    return tmk._build(tmv._gcc(), tmv.GEN, tmp_path_factory.mktemp("console"))


@pytest.fixture(scope="module")
def default_monitor(tmp_path_factory):
    """The default build, with the golden's native_servers line (C1)."""
    out = tmp_path_factory.mktemp("console-default") / "monitor"
    r = subprocess.run(mc.gcc_command(tmv._gcc(), str(tmv.REPO), str(out)), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


def _gen_with(tmp_path, contract=None, profiles=None):
    """A copy of the generated contract, with vss_contract.h's text or vss_profiles.h replaced."""
    gen = tmp_path / "gen"
    gen.mkdir()
    for h in tmv.GEN_HEADERS:
        shutil.copy2(tmv.GEN / h, gen / h)
    if contract is not None:
        (gen / "vss_contract.h").write_text(contract, encoding="ascii")
    if profiles is not None:
        (gen / "vss_profiles.h").write_text(profiles, encoding="ascii")
    return gen


# ============================================================ the limiter's reference

def limiter_model(events):
    """Spec 12 items 1-4 as a function of a whole event list: ("F", now_ns, seq, profile, reason) for a judged
    kind 4 frame, ("E",) for the session-end flush. Built unlike monitor.c's running state on purpose: each
    session's frames are cut into runs of one bucket (now // 1 s); a frame is a candidate when it is a reject
    whose reason differs from the frame before it in its session (0 before the first; an ACCEPT is 0); a bucket
    prints its first CAP candidates and suppresses every other reject; its summary follows its own lines when a
    later bucket of the session, or the session's end, follows it. A session not yet ended keeps its last
    bucket's summary pending, unprinted."""
    out = []

    def session(frames, ended):
        runs, prev = [], 0
        for now, seq, pid, reason in frames:
            if not runs or runs[-1][0] != now // S:
                runs.append((now // S, []))
            runs[-1][1].append((seq, pid, reason, reason != 0 and reason != prev))
            prev = reason
        for i, (_bucket, fr) in enumerate(runs):
            printed = set([j for j, f in enumerate(fr) if f[3]][:CAP])
            out.extend(REJECT_LINE % (fr[j][0], fr[j][1], NAMES[fr[j][2]]) for j in sorted(printed))
            supp = [f[2] for j, f in enumerate(fr) if f[2] != 0 and j not in printed]
            if supp and (i + 1 < len(runs) or ended):
                by = "".join(" %d=%d" % (r, supp.count(r)) for r in sorted(set(supp)))
                out.append(SUMMARY_LINE % (len(fr), sum(1 for f in fr if f[2] != 0), len(supp), by))

    frames = []
    for ev in events:
        if ev[0] == "E":
            session(frames, True)
            frames = []
        else:
            frames.append(ev[1:])
    session(frames, False)
    return out


def driver_log(driver, events):
    """The lines the monitor's own vss_log()/vss_log_end() print for these events (tests/vss_driver.c log)."""
    text = "".join(("E" if ev[0] == "E" else "F %d %d %d %d" % ev[1:]) + "\n" for ev in events)
    r = subprocess.run([driver, "log"], input=text, capture_output=True, text=True)
    assert r.returncode == 0 and not r.stderr, (r.returncode, r.stderr)
    return r.stdout.splitlines(keepends=True)


def ev(t_ns, seq, reason, pid=1):
    return ("F", t_ns, seq, pid, reason)


END = ("E",)


def run(times_ms, reasons, seq0=1):
    """Frames at these instants (ms), with these reasons, seqs from seq0."""
    return [ev(t * MS, seq0 + i, r) for i, (t, r) in enumerate(zip(times_ms, reasons))]


def lines_and_suppressed(events, out):
    """Total kind 4 REJECT lines and summarised suppressed lines of `out`, beside the rejects of `events`."""
    printed, suppressed = tmk.kind4_console(out)
    rejects = sum(1 for e in events if e[0] == "F" and e[4] != 0)
    return len(printed), sum(suppressed.values()), rejects


def check_against_model(driver, events, want):
    got = driver_log(driver, events)
    assert got == want, "the monitor's limiter against the specification, written out"
    assert limiter_model(events) == want, "the reference model against the specification, written out"
    return got


# ============================================================ C24-C27 in the driver, clock scripted

def test_c24_one_persisting_reason_prints_once_and_each_bucket_summarises_its_suppressed_lines(vss):
    jitter = (0, 7, -5, 12, -9, 3, 0, -2, 8, -11)
    times = [50 + 100 * i + jitter[i % 10] for i in range(35)]          # 10 Hz with jitter, 3.4 s
    per_bucket = collections.Counter(t // 1000 for t in times)
    assert per_bucket == {0: 10, 1: 10, 2: 10, 3: 5}, "premise: the instants fill these buckets"
    events = run(times, [23] * 35) + [END]
    want = [REJECT_LINE % (1, 1, "vss-speed"),
            SUMMARY_LINE % (10, 10, 9, " 23=9"),            # bucket 0: its one line, nine suppressed
            SUMMARY_LINE % (10, 10, 10, " 23=10"),          # buckets 1 and 2: printed when bucket 2 and 3 open
            SUMMARY_LINE % (10, 10, 10, " 23=10"),
            SUMMARY_LINE % (5, 5, 5, " 23=5")]               # bucket 3: printed by the session-end flush
    got = check_against_model(vss["driver"], events, want)
    lines, supp, rejects = lines_and_suppressed(events, got)
    assert lines + supp == rejects == 35
    assert lines <= 1 + (times[-1] - times[0]) / 1000, "C24: lines <= 1 + elapsed seconds"


def test_c24_a_flood_of_one_reason_in_one_bucket_and_an_accept_between_rejects(vss):
    flood = run([i // 2 for i in range(1000)], [22] * 1000) + [END]      # 1000 frames in 0.5 s
    check_against_model(vss["driver"], flood, [REJECT_LINE % (1, 1, "vss-stale"), SUMMARY_LINE % (1000, 1000, 999, " 22=999")])
    # Rule 1: an ACCEPT counts as reason 0, so the reject after it prints again.
    acc = run([100, 200, 300, 400, 500], [23, 23, 0, 23, 23], seq0=1) + [END]
    check_against_model(vss["driver"], acc, [REJECT_LINE % (1, 1, "vss-speed"), REJECT_LINE % (4, 1, "vss-speed"),
                                             SUMMARY_LINE % (5, 4, 2, " 23=2")])


def c25_events():
    """Alternating reasons 23, 24 (each frame differs from the one before it, so rule 1 never holds a line back):
    bucket 1, 11 arrivals at the designed 10 Hz, the fourth tick 40 ms late after a delayed reply and the frame
    queued behind it sent 1 ms later; bucket 2, 12 arrivals; bucket 3, its first frame repeating the reason of
    bucket 2's twelfth, which the cap suppressed; bucket 4, a flood of 50; then the session's end."""
    b1 = [1000, 1100, 1200, 1340, 1341, 1400, 1500, 1600, 1700, 1800, 1900]
    b2 = [2000 + 80 * i for i in range(12)]
    b3 = [3000 + 100 * i for i in range(10)]
    b4 = [4000 + 10 * i for i in range(50)]
    assert [len({t // 1000 for t in b}) for b in (b1, b2, b3, b4)] == [1, 1, 1, 1]
    alt = [23 if i % 2 == 0 else 24 for i in range(len(b1) + len(b2))]   # b1: 23 first; b2: 24 first, its 12th 23
    assert alt[len(b1):][-1] == 23
    b3_reasons = [23] + [24 if i % 2 == 0 else 23 for i in range(9)]       # repeats 23, then alternates
    b4_reasons = [23 if i % 2 == 0 else 24 for i in range(50)]
    return run(b1 + b2 + b3 + b4, alt + b3_reasons + b4_reasons) + [END]


def test_c25_eleven_arrivals_print_all_and_twelve_put_exactly_one_into_the_summary(vss):
    events = c25_events()
    f = [e for e in events if e[0] == "F"]
    line = [REJECT_LINE % (e[2], 1, NAMES[e[4]]) for e in f]
    b1, b2, b3, b4 = f[:11], f[11:23], f[23:33], f[33:]
    want = (line[:11]                                        # bucket 1: all 11 print, and no summary follows
            + line[11:22]                                    # bucket 2: eleven lines ...
            + [SUMMARY_LINE % (12, 12, 1, " 23=1")]           # ... and its twelfth in the summary
            + line[24:33]                                    # bucket 3: its first repeats the suppressed 23 (rule 1)
            + [SUMMARY_LINE % (10, 10, 1, " 23=1")]
            + line[33:44]                                    # bucket 4: eleven of 50, the rest by reason
            + [SUMMARY_LINE % (50, 50, 39, " 23=%d 24=%d" % (25 - 6, 25 - 5))])
    assert (len(b1), len(b2), len(b3), len(b4)) == (11, 12, 10, 50)
    assert [e[4] for e in b4[:11]].count(23) == 6, "premise: bucket 4 prints six 23s and five 24s"
    got = check_against_model(vss["driver"], events, want)
    lines, supp, rejects = lines_and_suppressed(events, got)
    assert lines + supp == rejects
    assert REJECT_LINE % (b3[0][2], 1, "vss-speed") not in got, \
        "rule 1 compares with the previous FRAME's reason, here one the cap suppressed, not with the last line printed"


def test_c25_the_cap_counts_rejects_between_accepts(vss):
    # Every 23 follows an ACCEPT, so each is a candidate: the cap alone holds the twelfth back.
    events = run([10 * i for i in range(30)], [23, 0] * 15) + [END]
    want = [REJECT_LINE % (1 + 2 * i, 1, "vss-speed") for i in range(11)] + [SUMMARY_LINE % (30, 15, 4, " 23=4")]
    check_against_model(vss["driver"], events, want)


def test_c27_the_session_end_flush_prints_the_pending_summary_and_resets_rule_1_and_the_cap(vss):
    alt11 = [24 if i % 2 == 0 else 23 for i in range(11)]                    # ends on 24
    events = (run([100, 200], [23, 23], seq0=1) + [END]                      # A: a summary at its end
              + run([300], [23], seq0=3) + [END]                             # B: A's last reason, a new session: prints
              + run([400 + i for i in range(11)], alt11, seq0=4) + [END]     # C: the cap reached in bucket 0
              + run([600, 610], [23, 24], seq0=15) + [END]                   # D: same bucket, the line count reset
              + [END]                                                        # nothing pending: nothing printed
              + run([700, 710], [22, 22], seq0=17) + [END])                  # E: counters from zero, not D's
    want = ([REJECT_LINE % (1, 1, "vss-speed"), SUMMARY_LINE % (2, 2, 1, " 23=1"), REJECT_LINE % (3, 1, "vss-speed")]
            + [REJECT_LINE % (4 + i, 1, NAMES[r]) for i, r in enumerate(alt11)]
            + [REJECT_LINE % (15, 1, "vss-speed"), REJECT_LINE % (16, 1, "vss-accel"),
               REJECT_LINE % (17, 1, "vss-stale"), SUMMARY_LINE % (2, 2, 1, " 22=1")])
    check_against_model(vss["driver"], events, want)


def test_c27_a_summary_pending_at_a_bucket_edge_is_printed_once(vss):
    # Suppressed in bucket 0, the flush then prints it; the next bucket's first frame finds nothing to print.
    events = run([900, 950], [26, 26]) + [END] + run([1100, 1150], [26, 26], seq0=3) + [END]
    want = [REJECT_LINE % (1, 1, "vss-yaw-inconsistent"), SUMMARY_LINE % (2, 2, 1, " 26=1"),
            REJECT_LINE % (3, 1, "vss-yaw-inconsistent"), SUMMARY_LINE % (2, 2, 1, " 26=1")]
    check_against_model(vss["driver"], events, want)


def test_the_limiter_matches_the_model_on_seeded_streams(vss):
    """Seeded mixed streams: the reasons drawn from a few, gaps from 0 to 1.5 s, flushes at random."""
    rng = random.Random(2427)
    for _ in range(20):
        events, t, seq = [], rng.randrange(3 * S), 1
        for _ in range(rng.randrange(50, 400)):
            if rng.random() < 0.02:
                events.append(END)
                continue
            t += rng.choice((0, 1 * MS, 30 * MS, 100 * MS, rng.randrange(1500 * MS)))
            events.append(ev(t, seq, rng.choice((0, 0, 23, 24, 26, 22, 10, 8, 21, 27, 9, 25)), rng.choice((1, 2, 0))))
            seq += 1
        events.append(END)
        got = driver_log(vss["driver"], events)
        assert got == limiter_model(events)
        lines, supp, rejects = lines_and_suppressed(events, got)
        assert lines + supp == rejects


# ============================================================ C24-C26 end to end over UDP: what no bucket edge moves

def _udp_run(binary, frames):
    u = tmk.Udp(binary)
    try:
        replies = u.exchange(frames)
    finally:
        rc = u.close()
    assert rc == 0 and not u.proc.err, (rc, b"".join(u.proc.err))
    return replies, [ln.decode("ascii") for ln in u.proc.out]


def _before_done(out):
    i = [j for j, ln in enumerate(out) if ln.startswith("monitor: udp done: ")]
    assert len(i) == 1, out
    return out[i[0] - 1]


def test_c24_end_to_end_one_persisting_reason_prints_once(vss):
    t = tsf.tables()
    frames = [k4(s, 23) for s in range(1, 201)]
    t0 = time.monotonic()
    replies, out = _udp_run(vss["monitor"], frames)
    elapsed = time.monotonic() - t0
    assert replies == [rules.reply(f, t) for f in frames]
    printed, suppressed = tmk.kind4_console(out)
    assert printed == [(1, tsf.nominal(), "vss-speed")], "rule 1 alone decides it: no bucket edge can add a line"
    assert len(printed) + sum(suppressed.values()) == 200 and set(suppressed) == {23}, "lines + suppressed = rejected"
    sums = [tmk.parse_summary(ln) for ln in out if ln.startswith("monitor: vss summary:")]
    assert len(sums) <= int(elapsed) + 2, "at most one summary per bucket the run touched"
    assert all(seen == rejected for seen, rejected, _s, _b in sums) and sum(r - s for _x, r, s, _b in sums) <= 1
    assert _before_done(out).startswith("monitor: vss summary:"), "the last frame was suppressed: its summary closes the run"


def test_c25_end_to_end_alternating_reasons_at_most_11_lines_a_bucket(vss):
    t = tsf.tables()
    frames = [k4(s, 23 if s % 2 else 24) for s in range(1, 301)]
    t0 = time.monotonic()
    replies, out = _udp_run(vss["monitor"], frames)
    elapsed = time.monotonic() - t0
    assert replies == [rules.reply(f, t) for f in frames]
    printed, suppressed = tmk.kind4_console(out)
    seqs = [s for s, _, _ in printed]
    assert seqs[:CAP] == list(range(1, CAP + 1)), "whatever the edges, the first 11 candidates print"
    assert len(printed) <= CAP * (int(elapsed) + 2), "at most 11 lines in each bucket the run touched"
    assert collections.Counter(23 if s % 2 else 24 for s in seqs) + suppressed == collections.Counter({23: 150, 24: 150})


def test_c26_kinds_0_1_and_unknown_are_never_limited_and_leave_kind_4s_rule_1_alone(vss, default_monitor):
    m, v, u = mnist_reject(500), mc.vlm(600, model=2), mc.vlm(700, kind=7)
    k = [k4(s, 23) for s in range(1, 6)]
    frames = [k[0], m, m, m, k[1], v, v, v, k[2], u, u, u, k[3], m, v, u, k[4]]
    _, vss_out = _udp_run(vss["monitor"], frames)
    _, def_out = _udp_run(default_monitor, frames)

    def others(out):
        return [ln for ln in out if ln.startswith("monitor: REJECT ") and " kind=vss " not in ln and " kind=4 " not in ln]

    want = ([MNIST_REJECT % 500] * 3
            + ["monitor: REJECT seq=600 kind=vlm model=2 class=3 conf=95 us=260000 reason=vlm-model-unbounded\n"] * 3
            + ["monitor: REJECT seq=700 kind=7 reason=claim-kind-unknown\n"] * 3
            + [MNIST_REJECT % 500, "monitor: REJECT seq=600 kind=vlm model=2 class=3 conf=95 us=260000 reason=vlm-model-unbounded\n",
               "monitor: REJECT seq=700 kind=7 reason=claim-kind-unknown\n"])
    assert others(vss_out) == others(def_out) == want, "one line per reject, byte-identical to the default build's"
    printed, suppressed = tmk.kind4_console(vss_out)
    assert printed == [(1, tsf.nominal(), "vss-speed")], "the frames of other kinds between them are not kind 4 frames"
    assert suppressed == {23: 4}
    sums = [tmk.parse_summary(ln) for ln in vss_out if ln.startswith("monitor: vss summary:")]
    assert sum(s[0] for s in sums) <= 5, "a summary's seen counts kind 4 frames only"


# ============================================================ C27 end to end: the flush hooks on every transport

END_RE = re.compile(r"monitor: (client done|udp done|shm quiet|shm done|shm-kick burst|shm-kick done): "
                    r"seen=(\d+) accepted=(\d+) rejected=(\d+)(.*)\n\Z")


def c27_session(seq0):
    """[23, ACCEPT, 23, a kind 0 reject, 23]: whatever its bucket edges, its two kind 4 lines and the kind 0 line
    print, its last 23 is suppressed (so a summary is pending at its end), and the next session's first 23 prints
    only if the flush reset rule 1."""
    return [k4(seq0, 23), k4(seq0 + 1, 0), k4(seq0 + 2, 23), mnist_reject(seq0 + 3), k4(seq0 + 4, 23)]


def expect_session(frames):
    """(REJECT lines, suppressed kind 4 rejects by reason, whether a summary must close it) for one session. Every
    session here has fewer candidates than the cap, so rule 1 alone decides, whatever the bucket edges."""
    t = tsf.tables()
    prev, lines, supp, closes = 0, [], collections.Counter(), False
    for f in frames:
        seq = struct.unpack_from("<Q", f)[0]
        if f[H + vf.P_KIND] != 4:
            assert f[H + vf.P_KIND] == 0 and f[H] == 10
            lines.append(MNIST_REJECT % seq)
            continue
        r = rules.judge_frame(f, t)[1]
        closes = bool(r) and r == prev
        if r and r != prev:
            lines.append(REJECT_LINE % (seq, f[H + vf.P_PROFILE], NAMES[r]))
        elif r:
            supp[r] += 1
        prev = r
    assert sum(1 for ln in lines if " kind=vss " in ln) <= CAP
    return lines, supp, closes


def check_sessions(out, frames):
    """Split the console at its session-end lines, each session's frames counted from those lines (a client done:
    line counts its connection, a quiet: or burst: line its burst, a cumulative done: line the rest), and hold each
    session to expect_session(): its REJECT lines, its summaries counting exactly its suppressed lines, and a
    summary right before its end line when one is pending. Returns the end lines' words, in order."""
    words, start, used = [], 0, 0
    for i, ln in enumerate(out):
        m = END_RE.match(ln)
        if not m:
            continue
        word, seen = m.group(1), int(m.group(2))
        burst = re.search(r"\((\d+) this burst\)", m.group(5))
        n = int(burst.group(1)) if burst else (seen if word == "client done" else seen - used)
        mine = frames[used:used + n]
        assert len(mine) == n, (word, n, used, len(frames))
        lines, supp, closes = expect_session(mine)
        seg = out[start:i]
        assert [x for x in seg if x.startswith("monitor: REJECT ")] == lines, (word, seg)
        sums = [tmk.parse_summary(x) for x in seg if x.startswith("monitor: vss summary:")]
        got = collections.Counter()
        for s in sums:
            got.update(s[3])
        assert got == supp, ("each session's summaries count its own suppressed lines", word, seg)
        if closes:
            assert out[i - 1].startswith("monitor: vss summary:"), ("the flush puts the pending summary first", word, seg)
        accepted = sum(1 for f in mine if f[H + vf.P_KIND] == 4 and rules.judge_frame(f, tsf.tables())[1] == 0)
        if word == "client done":
            assert (int(m.group(3)), int(m.group(4))) == (accepted, n - accepted), ln
        words.append(word)
        used += n
        start = i + 1
    assert used == len(frames), (used, len(frames))
    assert not [x for x in out[start:] if x.startswith(("monitor: REJECT ", "monitor: vss summary:"))], out[start:]
    return words


@pytest.mark.parametrize("mode", ["tcp", "stamp", "svc"])
def test_c27_tcp_stamp_and_svc_flush_before_client_done(vss, mode):
    words = {"tcp": [], "stamp": ["stamp"], "svc": ["svc", "60000"]}[mode]
    sessions = [c27_session(1), c27_session(6)]
    proc, port = mc._start_on_port(vss["monitor"], words, socket.SOCK_STREAM, mc.BANNER[mode])
    try:
        replies = []
        for n, sess in enumerate(sessions, 1):
            replies += mc._drive_stream(port, [("f", f, None) for f in sess])
            proc.wait_for(b"monitor: client done:", n=n)
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err
    frames = sessions[0] + sessions[1]
    assert [bytes.fromhex(r[1])[H + 6:H + 8] for r in replies] == [rules.reply(f, tsf.tables())[H + 6:H + 8] if f[H + 24] == 4
                                                                   else b"\x01\x01" for f in frames]
    out = [ln.decode("ascii") for ln in proc.out]
    assert check_sessions(out, frames) == ["client done", "client done"]


def test_c27_udp_flushes_before_udp_done(vss):
    frames = c27_session(1)
    _, out = _udp_run(vss["monitor"], frames)
    assert check_sessions(out, frames) == ["udp done"]


def _shm_send(mm, frame):
    # Slice assignments (one memcpy each), never struct.pack_into: CPython zero-fills the target before it packs,
    # and a monitor spinning on req_seq can judge that intervening zero as a request of its own.
    mm[mc.OFF_REQ:mc.OFF_REQ + 64] = frame
    seq = struct.unpack_from("<Q", mm, mc.OFF_REQ_SEQ)[0] + 1
    mm[mc.OFF_REQ_SEQ:mc.OFF_REQ_SEQ + 8] = struct.pack("<Q", seq)
    end = time.monotonic() + mc.REPLY_TIMEOUT
    while struct.unpack_from("<Q", mm, mc.OFF_RSP_SEQ)[0] != seq:
        assert time.monotonic() < end, "no shm reply"
        time.sleep(0.0002)
    return bytes(mm[mc.OFF_RSP:mc.OFF_RSP + 64])


def test_c27_shm_flushes_before_shm_quiet_and_shm_done(vss, tmp_path):
    """Three bursts on the polling slot: the first two end at their `shm quiet:` lines, the third at the stop's
    `shm done:`, sent at once after its last reply (it ends at a quiet line instead if the host stalls the stop
    by the slot's 50 ms; the split follows the console's own counts either way)."""
    if not mc.shm_client_ok():
        pytest.skip("the shm client needs x86-64 (tests/monitor_corpus.py)")
    path = str(tmp_path / "slot")
    with open(path, "wb") as fh:
        fh.write(b"\0" * mc.SHM_FILE_BYTES)
    sessions = [c27_session(1), c27_session(6), c27_session(11)]
    proc = mc._Proc([vss["monitor"], "shm", path])
    try:
        proc.wait_for(mc.BANNER["shm"])
        with open(path, "r+b") as fh:
            mm = mmap.mmap(fh.fileno(), 0)
        try:
            for n, sess in enumerate(sessions, 1):
                for f in sess:
                    _shm_send(mm, f)
                if n < len(sessions):
                    time.sleep(0.2)                                  # four times the slot's quiet interval
                    proc.wait_for(b"monitor: shm quiet:", n=n)
        finally:
            mm.close()
        proc.p.send_signal(signal.SIGTERM)
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err
    out = [ln.decode("ascii") for ln in proc.out]
    words = check_sessions(out, sessions[0] + sessions[1] + sessions[2])
    assert words[-1] == "shm done" and words.count("shm quiet") >= 2, words


IVSHMEM_SERVER_PY = tmv.REPO / "orin-native" / "gpu-concurrency" / "ivshmem_server.py"
KICK_SLOT = 4096


class _KickRig:
    """An ivshmem server (the repo's own), the vss monitor in shmkick mode on it, and a kick client: each frame
    goes into the slot, asks for its reply by a kick byte, and is kicked with one."""

    def __init__(self, binary):
        self.d = tempfile.mkdtemp(prefix="k4c", dir="/tmp")         # UNIX socket paths are limited to 107 bytes
        self.srv = self.proc = self.sock = self.mm = None
        shm = os.path.join(self.d, "srv.shm")
        with open(shm, "wb") as fh:
            fh.write(b"\0" * (1 << 20))
        path = os.path.join(self.d, "srv.sock")
        ready = path + ".ready"
        self.srv = subprocess.Popen([sys.executable, str(IVSHMEM_SERVER_PY), "--socket", path, "--shm", shm, "--ready", ready],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        end = time.monotonic() + 10
        while not (os.path.exists(ready) and os.path.getsize(ready) > 0):
            assert time.monotonic() < end and self.srv.poll() is None, "the ivshmem server never became ready"
            time.sleep(0.02)
        kick = os.path.join(self.d, "kick.sock")
        self.proc = mc._Proc([binary, "shmkick", "%s@%d" % (path, KICK_SLOT), kick])
        self.proc.wait_for(b"monitor: safety monitor serving shm-kick on ")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(mc.REPLY_TIMEOUT)
        self.sock.connect(kick)
        with open(shm, "r+b") as fh:
            self.mm = mmap.mmap(fh.fileno(), 0)
        self.seq = struct.unpack_from("<Q", self.mm, KICK_SLOT + mc.OFF_REQ_SEQ)[0]

    def exchange(self, frame):
        base = KICK_SLOT
        self.mm[base + mc.OFF_REQ:base + mc.OFF_REQ + 64] = frame      # slice assignments: see _shm_send
        self.mm[base + 72:base + 76] = struct.pack("<I", 0)            # reply_via: a kick byte (shm_chan.h)
        self.seq += 1
        self.mm[base + mc.OFF_REQ_SEQ:base + mc.OFF_REQ_SEQ + 8] = struct.pack("<Q", self.seq)
        self.sock.sendall(b"K")
        assert self.sock.recv(1) == b"K", "no kick back"
        assert struct.unpack_from("<Q", self.mm, base + mc.OFF_RSP_SEQ)[0] == self.seq
        return bytes(self.mm[base + mc.OFF_RSP:base + mc.OFF_RSP + 64])

    def close(self):
        """Stop everything; the monitor's exit code."""
        try:
            if self.sock is not None:
                self.sock.close()
            if self.mm is not None:
                self.mm.close()
            return self.proc.stop() if self.proc is not None else None
        finally:
            if self.proc is not None:
                self.proc.kill()
            if self.srv is not None:
                self.srv.terminate()
                try:
                    self.srv.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.srv.kill()
                    self.srv.wait()
            shutil.rmtree(self.d, ignore_errors=True)


def test_c27_shm_kick_flushes_before_its_burst_and_done_lines_and_opens_with_the_announcement(vss):
    if not hasattr(os, "eventfd"):
        pytest.skip("the ivshmem server needs Linux eventfds")
    t = tsf.tables()
    sessions = [c27_session(1), c27_session(6)]
    rig = _KickRig(vss["monitor"])
    try:
        replies = [rig.exchange(f) for f in sessions[0]]
        time.sleep(1.2)                                              # a second without requests ends a burst
        replies += [rig.exchange(f) for f in sessions[1]]
    finally:
        rc = rig.close()
    assert rc == 0 and not rig.proc.err, b"".join(rig.proc.err)
    frames = sessions[0] + sessions[1]
    assert replies == [rules.reply(f, t) if f[H + 24] == 4 else f[:H + 6] + b"\x01\x01" + f[H + 8:] for f in frames]
    out = [ln.decode("ascii") for ln in rig.proc.out]
    ann = announcement(t)
    assert out[:1 + len(ann)] == [CLAIM_KINDS] + ann, "C4 in the shm-kick mode"
    assert check_sessions(out, frames) == ["shm-kick burst", "shm-kick done"]


SESSION_END_PRINTS = ('printf("monitor: client done: ', 'printf("monitor: udp done: ', 'printf("monitor: shm quiet: ',
                      'printf("monitor: shm done: ', 'printf("monitor: shm-kick burst: ', 'printf("monitor: shm-kick done: ')
HOOK = ["#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)", "vss_log_end(&g_vss_log);", "#endif"]


def test_c27_each_session_end_line_has_its_flush_hook_right_before_it():
    """The seven lines of spec 12 (two client done:, one each of the rest), each immediately after the bare #if
    block of the flush hook, and no hook anywhere else. The end-to-end tests above cover them behaviourally;
    this pins the one (shm done:) whose stop can race the slot's quiet line."""
    src = [ln.strip() for ln in tmv.MONITOR_C.read_text(encoding="ascii").splitlines()]
    ends = [i for i, ln in enumerate(src) if ln.startswith(SESSION_END_PRINTS)]
    assert collections.Counter(src[i][:src[i].index(":", 17)] for i in ends) == collections.Counter(
        {'printf("monitor: client done': 2, 'printf("monitor: udp done': 1, 'printf("monitor: shm quiet': 1,
         'printf("monitor: shm done': 1, 'printf("monitor: shm-kick burst': 1, 'printf("monitor: shm-kick done': 1})
    for i in ends:
        assert src[i - 3:i] == HOOK, src[i - 4:i + 1]
    assert [i for i, ln in enumerate(src) if ln == HOOK[1]] == [i - 2 for i in ends]


# ============================================================ C3, C4: the opening lines

def announcement(t, ids=None):
    """Spec 12's two formats for the tables `t`: the vss rules line, then one vss profile line per id."""
    ids = list(tmk.COMPILED) if ids is None else ids
    out = [RULES_LINE % (C.CATALOG_DIGEST, C.VSS_VERSION, C.AGE_MAX_MS, " ".join(str(i) for i in ids))]
    for i in ids:
        p = t.profiles[i]
        ay = "none" if p.ay26_max == 0.0 else "%g m/s^2" % p.ay26_max
        out.append(PROFILE_LINE % (p.id, p.l_mm, p.v_max, p.a_max, p.delta_max, p.v26_lo, p.v26_hi, ay, p.tol26, p.v_tol))
    return out


OPEN_MODES = ("udp", "tcp", "stamp", "svc", "shm")


def _opening(binary, mode, workdir):
    """A monitor's stdout from its start through its banner, in one serving mode, its port as <port>."""
    port = None
    if mode == "shm":
        path = os.path.join(str(workdir), "slot")
        with open(path, "wb") as fh:
            fh.write(b"\0" * mc.SHM_FILE_BYTES)
        proc = mc._Proc([binary, "shm", path])
    else:
        words = {"udp": ["udp"], "tcp": [], "stamp": ["stamp"], "svc": ["svc", "500"]}[mode]
        proc, port = mc._start_on_port(binary, words, socket.SOCK_DGRAM if mode == "udp" else socket.SOCK_STREAM, mc.BANNER[mode])
    try:
        proc.wait_for(mc.BANNER[mode])
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err
    out = [ln.decode("ascii") for ln in proc.out]
    return [re.sub(r":%d(?!\d)" % port, ":<port>", ln) if port is not None else ln for ln in out]


@pytest.mark.parametrize("mode", OPEN_MODES)
def test_c3_c4_every_serving_mode_opens_with_the_claim_kinds_line_then_the_announcement(vss, default_monitor, mode, tmp_path):
    t = tsf.tables()
    ann = announcement(t)
    got = _opening(vss["monitor"], mode, tmp_path)
    base = _opening(default_monitor, mode, tmp_path)
    assert base[0] == got[0] == CLAIM_KINDS, "C3: the claim kinds line, unchanged in both builds"
    assert got[1:1 + len(ann)] == ann, "C4: right after it, spec 12's formats"
    assert got[1 + len(ann):] == base[1:], "everything after the announcement is the default build's, byte for byte"
    assert not [ln for ln in base if "vss" in ln], "the default build announces nothing"
    assert sum(ln.startswith("monitor: vss rules:") for ln in got) == 1
    assert sum(ln.startswith("monitor: vss profile ") for ln in got) == len(tmk.COMPILED)
    m = re.search(r" catalog 0x([0-9A-F]{8}) ", got[1])
    assert m and int(m.group(1), 16) == C.CATALOG_DIGEST == vf.digest_of(C.SLOT_UIDS), "the printed digest is the contract's"
    for ln in ann:
        assert not [w for w in HARNESS_WORDS if w in ln], ln
        assert not ln.startswith(tuple(b.decode() for b in mc.BANNER.values()))
    assert_each_compiled_ay_max_is_its_rows(got[2:2 + len(tmk.COMPILED)])


def ay_max_text(row):
    """Spec 12's ay_max field for a generated profile row: `none` for no bound (None in the Python table), else `%g m/s^2`."""
    return "none" if row["ay26_max"] is None else "%g m/s^2" % row["ay26_max"]


def assert_each_compiled_ay_max_is_its_rows(lines):
    """The profile lines of a vss build from the generated table: one per compiled id, each with its generated row's a_y
    bound (read from the contract's rows, not through rules.Tables), and at least one of them a bound (Phase 7 froze
    profile 3, the CARLA ego's, with one), so the check is never only of `none`."""
    rows = {int(r["id"]): r for r in C.PROFILES}
    by_id = {int(re.match(r"monitor: vss profile (\d+):", ln).group(1)): ln for ln in lines}
    assert sorted(by_id) == sorted(tmk.COMPILED)
    checked = []
    for i in tmk.COMPILED:
        assert " ay_max %s tol " % ay_max_text(rows[i]) in by_id[i], (i, by_id[i])
        checked.append(i)
    assert checked == list(tmk.COMPILED) and any(rows[i]["ay26_max"] is not None for i in checked), \
        "every compiled profile's line checked, an a_y-bounded one among them"


def test_c4_shmcfg_prints_neither_the_claim_kinds_line_nor_the_announcement(vss, default_monitor):
    for binary in (vss["monitor"], default_monitor):
        r = subprocess.run([binary, "shmcfg", "ivshmem"], capture_output=True, text=True, timeout=10)
        assert r.returncode == 0 and not r.stderr, r
        assert r.stdout.startswith("monitor: shm configured: ") and len(r.stdout.splitlines()) == 1, r.stdout


@pytest.fixture(scope="module")
def ay_build(tmp_path_factory):
    """A second vss build whose table adds two test-only profiles with an a_y bound (2.0 and 1.5 m/s^2) under
    fresh ids, bound in Python under the same ids."""
    d = tmp_path_factory.mktemp("ay-console")
    base = rules.Profile.from_row(next(r for r in C.PROFILES if int(r["id"]) == tsf.ay_bounded()))
    used = {int(r["id"]) for r in C.PROFILES} | set(C.RESERVED_PROFILE_IDS)
    fresh = sorted(set(range(1, 256)) - used)[:2]
    tests = [dataclasses.replace(base, id=fresh[0], ay26_max=2.0), dataclasses.replace(base, id=fresh[1], ay26_max=1.5, tol26=8.5)]
    t = rules.Tables.from_contract(C, profiles=tests)
    ids = list(tmk.COMPILED) + fresh
    gen = _gen_with(d, profiles=tmk._render_profiles_h([t.profiles[i] for i in ids]))
    return {"bins": tmk._build(tmv._gcc(), gen, d, names=("monitor",)), "t": t, "ids": ids, "fresh": fresh}


def test_c4_the_a_y_bound_prints_as_g_m_per_s2(ay_build, tmp_path):
    t, ids, fresh = ay_build["t"], ay_build["ids"], ay_build["fresh"]
    got = _opening(ay_build["bins"]["monitor"], "udp", tmp_path)
    assert got[1:2 + len(ids)] == announcement(t, ids)
    assert got[1].endswith(", profiles %s\n" % " ".join(str(i) for i in ids)), "the ids come from the compiled table"
    by_id = {int(re.match(r"monitor: vss profile (\d+):", ln).group(1)): ln for ln in got[2:2 + len(ids)]}
    assert " ay_max 2 m/s^2 tol " in by_id[fresh[0]] and " ay_max 1.5 m/s^2 tol 8.5 deg/s," in by_id[fresh[1]]
    assert_each_compiled_ay_max_is_its_rows([by_id[i] for i in tmk.COMPILED])


# ============================================================ C29's C half and the startup self-check

FNV_VECTORS = (("", 0x811C9DC5), (b"a".hex(), 0x050C5D7E), (b"foobar".hex(), 0x31F0B262),
               ("3d2c1b0a04030201efbeadde78563412f0debc9a", 0xC30680E3))       # spec 4.2's table
FNV_BE = 0xFA2112AB                                                             # the same UIDs big-endian: must differ


def test_c29_the_monitors_fnv1_gives_spec_4_2s_vectors(vss):
    got = [int(x, 16) for x in tmk.driver_lines(vss["driver"], "fnv", [h for h, _ in FNV_VECTORS])]
    assert got == [w for _, w in FNV_VECTORS]
    be = b"".join(struct.pack(">I", u) for u in tsf.VECTOR_UIDS).hex()
    assert int(tmk.driver_lines(vss["driver"], "fnv", [be])[0], 16) == FNV_BE != FNV_VECTORS[-1][1]
    rng = random.Random(29)
    blobs = [bytes(rng.randrange(256) for _ in range(rng.randrange(0, 255))) for _ in range(300)]
    got = [int(x, 16) for x in tmk.driver_lines(vss["driver"], "fnv", [b.hex() for b in blobs])]
    assert got == [vf.fnv1_32(b) for b in blobs], "the C FNV-1 is vssframe.fnv1_32"


def test_c29_the_self_check_serialises_each_uid_little_endian_by_shifts(vss):
    swapped = [struct.unpack("<I", struct.pack(">I", u))[0] for u in tsf.VECTOR_UIDS]
    rows = [tsf.VECTOR_UIDS, swapped, C.SLOT_UIDS]
    got = [int(x, 16) for x in tmk.driver_lines(vss["driver"], "uids", [" ".join("%08X" % u for u in r) for r in rows])]
    assert got == [FNV_VECTORS[-1][1], FNV_BE, C.CATALOG_DIGEST]
    assert tmk.driver_lines(vss["driver"], "selfcheck") == ["computed %08X header %08X consistent 1" % (C.CATALOG_DIGEST, C.CATALOG_DIGEST)]


def _edited_contract(what):
    text = (tmv.GEN / "vss_contract.h").read_text(encoding="ascii")
    if what == "digest":
        old = "#define VSS_CATALOG_DIGEST 0x%08Xu\n" % C.CATALOG_DIGEST
        new = "#define VSS_CATALOG_DIGEST 0x%08Xu\n" % (C.CATALOG_DIGEST ^ 0x80)
    else:
        old = "#define VSS_UID_SLOT%d 0x%08Xu\n" % (what, C.SLOT_UIDS[what])
        new = "#define VSS_UID_SLOT%d 0x%08Xu\n" % (what, C.SLOT_UIDS[what] ^ 0x100)
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _refuses(binary, argv):
    r = subprocess.run([binary] + argv, capture_output=True, timeout=10)
    assert (r.returncode, r.stdout, r.stderr) == (2, b"", INCONSISTENT.encode()), (argv, r)


@pytest.mark.parametrize("what", [0, 1, 2, 3, 4, "digest"])
def test_a_hand_edited_contract_exits_2_before_the_claim_kinds_line(what, tmp_path):
    """One UID edited (or the digest), the rest as generated: the build compiles, and the monitor exits 2 with the
    message on stderr, no claim kinds line and no banner (spec 4.3; no 16.1 test covers it)."""
    gen = _gen_with(tmp_path, contract=_edited_contract(what))
    binary = tmk._build(tmv._gcc(), gen, tmp_path, names=("monitor",))["monitor"]
    port = str(mc._free_port(socket.SOCK_DGRAM))
    _refuses(binary, [port, "udp"])
    if what == 2:
        for argv in ([port], [port, "stamp"], [port, "svc", "500"], ["shm", str(tmp_path / "slot")],
                     ["shmkick", str(tmp_path / "srv.sock") + "@4096", str(tmp_path / "kick.sock")]):
            _refuses(binary, argv)
        r = subprocess.run([binary, "shmcfg", "ivshmem"], capture_output=True, text=True, timeout=10)
        assert r.returncode == 0 and r.stdout.startswith("monitor: shm configured: "), "shmcfg serves nothing and is not checked"


# ============================================================ the profile-id guard

@pytest.mark.parametrize("pid,compiles", [(0, False), (256, False), (258, False), (255, True)])
def test_a_profile_row_outside_1_to_255_does_not_compile(pid, compiles, tmp_path):
    """The C side of rules.Tables refusing id 0 (FOUND BY REVIEW, WP2+3): a row with id 0, or one the payload's
    byte cannot carry, stops the build -- also without -Werror, as the qcc recipe and the native script build."""
    t = tsf.tables()
    rows = [t.profiles[i] for i in tmk.COMPILED] + [dataclasses.replace(t.profiles[tmk.COMPILED[0]], id=pid)]
    gen = _gen_with(tmp_path, profiles=tmk._render_profiles_h(rows))
    for flags in (tmv.VSS_FLAGS, tuple(f for f in tmv.VSS_FLAGS if f != "-Werror")):
        r = tmv._compile_object(tmv._gcc(), flags, tmp_path, gen=gen)
        if compiles:
            assert r.returncode == 0, r.stderr
        else:
            assert r.returncode != 0 and "a vss profile id is 1..255" in r.stderr, r.stderr
    if pid == 0:
        with pytest.raises(ValueError, match="reserved"):
            rules.Tables.from_contract(C, profiles=[rows[-1]])


# ============================================================ the clock read: kinds 0 and 1 pay none

CLOCK_SHIM = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static unsigned long g_calls;

int clock_gettime(clockid_t id, struct timespec *ts)
{
	static int (*real)(clockid_t, struct timespec *);

	if (real == NULL) {
		void *sym = dlsym(RTLD_NEXT, "clock_gettime");

		memcpy(&real, &sym, sizeof(real));
	}
	__atomic_add_fetch(&g_calls, 1ul, __ATOMIC_RELAXED);
	return real(id, ts);
}

__attribute__((destructor)) static void report(void)
{
	const char *path = getenv("VSS_CLOCK_COUNT");
	FILE *f = path != NULL ? fopen(path, "w") : NULL;

	if (f != NULL) {
		fprintf(f, "%lu\n", g_calls);
		fclose(f);
	}
}
"""


@pytest.fixture(scope="module")
def clock_shim(tmp_path_factory):
    d = tmp_path_factory.mktemp("shim")
    (d / "clockcount.c").write_text(CLOCK_SHIM, encoding="ascii")
    r = subprocess.run([tmv._gcc(), "-O2", "-Wall", "-Werror", "-shared", "-fPIC", "-o", str(d / "clockcount.so"),
                        str(d / "clockcount.c"), "-ldl"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(d / "clockcount.so")


def _clock_reads(binary, shim, frames, workdir):
    """clock_gettime() calls of a UDP monitor that judged `frames`, counted by an LD_PRELOAD shim."""
    count = workdir / "clock-count"
    port = mc._free_port(socket.SOCK_DGRAM)
    proc = mc._Proc(["env", "LD_PRELOAD=" + shim, "VSS_CLOCK_COUNT=" + str(count), binary, str(port), "udp"])
    try:
        proc.wait_for(mc.BANNER["udp"])
        replies = mc._drive_udp(port, [("f", f, None) for f in frames])
        rc = proc.stop()
    except BaseException:
        proc.kill()
        raise
    assert rc == 0 and not proc.err and all(r[1] is not None for r in replies)
    return int(count.read_text(encoding="ascii"))


def test_kinds_0_and_1_read_no_clock_and_kind_4_reads_one_per_frame(vss, default_monitor, clock_shim, tmp_path):
    """The kind compare comes before any now_ns(), so kinds 0 and 1 (and unknown kinds) pay no clock
    read; a kind 4 frame pays exactly one, the limiter's. UDP reads the clock nowhere else."""
    others = [mc.mnist(10, 3, 95, 124), mnist_reject(11), mc.vlm(12), mc.vlm(13, model=2), mc.vlm(14, kind=7)] * 4
    kind4 = [k4(s, r) for s, r in zip(range(100, 107), (0, 23, 23, 24, 0, 8, 10))]
    runs = {}
    for name, binary, frames in (("vss, other kinds", vss["monitor"], others),
                                 ("vss, mixed", vss["monitor"], others + kind4 + others),
                                 ("default, mixed", default_monitor, others + kind4)):
        d = tmp_path / name.replace(", ", "-")
        d.mkdir()
        runs[name] = _clock_reads(binary, clock_shim, frames, d)
    assert runs == {"vss, other kinds": 0, "vss, mixed": len(kind4), "default, mixed": 0}, runs
