#!/usr/bin/env python3
"""liveness_demo.py -- the liveness deadline's synthetic demo (OD14), run by
liveness-demo.sh on L4T against the deadline-mode monitor in ifs-live.bin.

Phase 3b / A6. Pre-built kind-1 claims -- latency_probe.build_vlm_frame(), one
honest SmolVLM-500M answer as the 2026-09-23 characterisation measured it -- are
sent at controlled cadences, and every expected outcome is read back from the
guest's own serial console, never inferred from the client side. No model runs.

EVERY SCENARIO OPENS WITH A RESTORED AND CLOSES WITH A MISS. Each one starts
from a silence the monitor has already reported, so its first claim prints one
LIVENESS RESTORED; and each ends with a silence, so the monitor prints one
LIVENESS MISS for it. A claim on a connection of its own is the hung-up case:
between two such claims the monitor waits in accept(), with no client at all.

  steady       10 claims, one every 0.25 D                     no miss inside
  under        5 claims, 0.9 D apart                           no miss inside
  over         5 claims, 1.1 D apart                           a miss in every gap
  rejects      10 claims 0.25 D apart, every other one class 42
                                                               no miss: a rejected
                                                               claim is still life
  quiet        one connection: a claim, then nothing           MISS, and the
                                                               connection closed
  mid-frame    one connection: a claim, then 30 bytes          MISS, closed, and the
                                                               half frame never judged
  keepalive    one connection: a claim, then sentinels every   MISS while the
               0.25 D                                          sentinels still flow;
                                                               the connection stays
  lockout      a connection that says nothing, and a claim     the silent one is
               queued behind it                                closed; the claim is
                                                               served within D

Two times per MISS: the silence the guest measured on its own monotonic clock
(the MISS line's "no claim for N ms"), and the host's, from the reply to the
last claim to seeing the line in the console file -- which adds the serial
path. From the reply, not the send: a claim queued behind a hung client is read
by the monitor only when it is accepted, and its silence starts there.
Neither is a latency figure for the service; both show the deadline is kept.

Usage: liveness_demo.py --host GUEST --port 7102 --console LOG --out DIR
Exit 0 only if every check in every scenario holds.
"""
import argparse
import hashlib
import json
import os
import re
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gpu-concurrency"))
import latency_probe as lp  # noqa: E402

SENTINEL = 0xFFFFFFFFFFFFFFFF
BANNER = re.compile(r"service monitor listening on :(\d+) \(frame=64 bytes, conf_min=\d+%\), "
                    r"liveness deadline (\d+) ms")
SLACK_S = 0.25           # how late a report may be before it counts as not kept


class Console:
    """The guest's serial console as the launcher writes it on the host: every
    new line, stamped with the host's monotonic clock when it was first seen."""

    def __init__(self, path):
        self.f = open(path, "rb")
        self.head = self.f.read().replace(b"\0", b"").replace(b"\r", b"").decode("utf-8", "replace")
        self.part = b""
        self.lines = []
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            data = self.f.read()
            if not data:
                time.sleep(0.002)
                continue
            t = time.monotonic()
            data = (self.part + data).replace(b"\0", b"").replace(b"\r", b"")
            *full, self.part = data.split(b"\n")
            with self.lock:
                self.lines.extend((t, x.decode("utf-8", "replace")) for x in full)

    def mark(self):
        with self.lock:
            return len(self.lines)

    def since(self, i):
        with self.lock:
            return list(self.lines[i:])

    def wait_for(self, text, after, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for t, line in self.since(after):
                if text in line:
                    return t, line
            time.sleep(0.002)
        return None


def recv_all(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            break
        b += c
    return b


def frame(seq, cls=None):
    """The pre-built honest claim, its verdict and reason bytes poisoned to 0xEE:
    the monitor never reads them, so an ACCEPT of 00 00 in a reply is one it
    wrote, not one the request carried (found by review)."""
    f = bytearray(lp.build_vlm_frame(seq))
    f[16 + 6] = f[16 + 7] = 0xEE
    if cls is not None:
        f[16] = cls
    return bytes(f)


def sentinel():
    """A keepalive the monitor must echo untouched: a REJECTable body (class 42)
    with poisoned verdict bytes, so a monitor that judged it would change the
    echo and print a REJECT line (found by review)."""
    f = bytearray(frame(0, cls=42))
    f[0:8] = SENTINEL.to_bytes(8, "little")
    return bytes(f)


def boot_state(con):
    """What the deadline-mode monitor has printed so far: 'never' (no LIVENESS
    line: no claim has armed it, or one did within the last deadline), 'silence'
    (the last one is a MISS) or 'armed' (the last one is a RESTORED)."""
    lv = [line for line in con.head.splitlines() if "LIVENESS" in line]
    lv += [line for _t, line in con.since(0) if "LIVENESS" in line]
    if not lv:
        return "never"
    return "silence" if "LIVENESS MISS" in lv[-1] else "armed"


def connect(host, port):
    s = socket.create_connection((host, port), timeout=15)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


class Scenario:
    def __init__(self, con, name, d):
        self.con, self.name, self.d = con, name, d
        self.start = con.mark()
        self.sent = []          # (seq, host time its reply arrived)
        self.checks = []        # (what, ok, detail)
        self.notes = {}

    def claim(self, host, port, seq, cls=None):
        """One claim on a connection of its own, as vlm_client.py sends them."""
        with connect(host, port) as s:
            s.sendall(frame(seq, cls))
            r = recv_all(s, 64)
        self.sent.append((seq, time.monotonic()))
        return r

    def check(self, what, ok, detail=""):
        """ok=None records a check as NOT APPLICABLE: shown, never counted."""
        self.checks.append((what, None if ok is None else bool(ok), detail))

    def finish(self):
        """Wait for THIS scenario's trailing silence to be reported -- the MISS
        naming its last claim, not any MISS: `over` prints one in every gap --
        then judge the window. That the MISS came, and named that claim, is a
        check of its own (found by review: a MISS naming an earlier seq passed)."""
        last_seq, last = self.sent[-1]
        wait = max(0.0, last + self.d + SLACK_S + 1.0 - time.monotonic())
        hit = self.con.wait_for("since seq=%d " % last_seq, self.start, wait + 0.5)
        self.check("the trailing MISS names seq %d, the last claim" % last_seq, hit is not None)
        time.sleep(0.3)
        self.lines = self.con.since(self.start)
        self.misses = []
        for t, line in self.lines:
            m = re.search(r"LIVENESS MISS: no claim for (\d+) ms since seq=(\d+)", line)
            if not m:
                continue
            seq = int(m.group(2))
            sent = [ts for s, ts in self.sent if s == seq]
            self.misses.append({"since_seq": seq, "guest_ms": int(m.group(1)),
                                "host_ms": round((t - sent[-1]) * 1000.0, 1) if sent else None})
        return self

    def count(self, text):
        return sum(1 for _t, line in self.lines if text in line)

    def expect_counts(self, restored, missed, closed=0):
        self.check("LIVENESS RESTORED x%d" % restored, self.count("LIVENESS RESTORED") == restored,
                   "saw %d" % self.count("LIVENESS RESTORED"))
        self.check("LIVENESS MISS x%d" % missed, self.count("LIVENESS MISS") == missed,
                   "saw %d" % self.count("LIVENESS MISS"))
        self.check("client closed x%d" % closed, self.count("client closed") == closed,
                   "saw %d" % self.count("client closed"))

    def expect_deadline_kept(self):
        d_ms = self.d * 1000.0
        for m in self.misses:
            self.check("MISS since seq=%d kept the deadline" % m["since_seq"],
                       d_ms <= m["guest_ms"] < d_ms + SLACK_S * 1000
                       and m["host_ms"] is not None and d_ms - 5 <= m["host_ms"] < d_ms + SLACK_S * 1000,
                       "guest %d ms, host %s ms" % (m["guest_ms"], m["host_ms"]))

    def result(self):
        return {"scenario": self.name, "sent": [s for s, _t in self.sent], "misses": self.misses,
                "notes": self.notes,
                "checks": [{"what": w, "ok": ok, "detail": det} for w, ok, det in self.checks],
                "console": [line for _t, line in self.lines]}


def run(a, con, d):
    host, port = a.host, a.port
    out = []
    seq = [1000]

    def nxt():
        seq[0] += 1
        return seq[0]

    # Arm. On a boot nothing has claimed to, the monitor must sit through a whole
    # deadline printing nothing, and the first claim must print no RESTORED. On a
    # boot already armed that property cannot be seen: it is recorded as NOT
    # APPLICABLE, never as passed, and the first claim must instead RESTORE the
    # silence already reported. (Found by review: the first version passed it
    # vacuously on an armed boot.)
    sc = Scenario(con, "arm", d)
    state = boot_state(con)
    if state == "never":
        time.sleep(d + SLACK_S)
        state = boot_state(con)         # a claim within the last deadline shows up now
        if state == "never":
            sc.check("no LIVENESS line through a whole deadline before the first claim", True)
    if state == "armed":                # a claim just before us: wait for its silence
        time.sleep(d + SLACK_S)
        state = boot_state(con)
        if state != "silence":
            sys.exit("FATAL: the monitor is armed and has not reported a silence -- something is claiming to it")
    sc.notes["boot"] = state
    sc.claim(host, port, nxt())
    sc.finish()
    if state == "never":
        sc.expect_counts(0, 1)
    else:
        sc.check("no deadline before the first claim of the boot", None, "boot already armed")
        sc.expect_counts(1, 1)
        sc.check("the RESTORED names this claim", sc.count("LIVENESS RESTORED: seq=%d " % sc.sent[0][0]) == 1)
    sc.check("the claim ACCEPTed and was judged", sc.count("client done: seen=1 accepted=1 rejected=0") == 1)
    sc.expect_deadline_kept()
    out.append(sc.result())

    for name, n, gap, restored, missed in (("steady", 10, 0.25, 1, 1), ("under", 5, 0.9, 1, 1),
                                           ("over", 5, 1.1, 5, 5)):
        sc = Scenario(con, name, d)
        for i in range(n):
            r = sc.claim(host, port, nxt())
            sc.check("seq %d ACCEPTed" % sc.sent[-1][0], r[16 + 6:16 + 8] == b"\x00\x00", r[16 + 6:16 + 8].hex())
            if i < n - 1:
                time.sleep(gap * d)
        sc.finish()
        sc.expect_counts(restored, missed)
        sc.expect_deadline_kept()
        out.append(sc.result())

    # One accepted claim, then only rejected ones for 1.5 D: a monitor that took
    # only an accepted claim as life would report a silence inside the run.
    # (Found by review: alternating them never left accepted claims a deadline
    # apart, so the first version could not show the rule.)
    sc = Scenario(con, "rejects", d)
    for i in range(7):
        r = sc.claim(host, port, nxt(), cls=42 if i else None)
        want = b"\x01\x01" if i else b"\x00\x00"
        sc.check("seq %d verdict" % sc.sent[-1][0], r[16 + 6:16 + 8] == want, r[16 + 6:16 + 8].hex())
        if i < 6:
            time.sleep(0.25 * d)
    sc.finish()
    sc.expect_counts(1, 1)
    sc.check("6 REJECT lines, class-out-of-range", sc.count("reason=class-out-of-range") == 6,
             "saw %d" % sc.count("reason=class-out-of-range"))
    sc.expect_deadline_kept()
    out.append(sc.result())

    # One connection held open, then silent: the monitor reports the silence and
    # hangs up, so a restarted Compute side can get the only slot.
    sc = Scenario(con, "quiet", d)
    with connect(host, port) as s:
        q = nxt()
        s.sendall(frame(q))
        recv_all(s, 64)
        t = time.monotonic()
        sc.sent.append((q, t))
        s.settimeout(d + 5)
        eof = s.recv(64)
        sc.notes["eof_after_ms"] = round((time.monotonic() - t) * 1000.0, 1)
    sc.check("the monitor hung up on the silent connection", eof == b"", repr(eof[:8]))
    sc.finish()
    sc.expect_counts(1, 1, closed=1)
    sc.expect_deadline_kept()
    out.append(sc.result())

    # A frame cut short: without poll() the monitor would sit in read() until it
    # completed, and the deadline would pass unreported.
    sc = Scenario(con, "mid-frame", d)
    with connect(host, port) as s:
        q = nxt()
        s.sendall(frame(q))
        recv_all(s, 64)
        t = time.monotonic()
        sc.sent.append((q, t))
        s.sendall(frame(nxt())[:30])
        s.settimeout(d + 5)
        eof = s.recv(64)
    sc.check("the half frame's connection was closed", eof == b"", repr(eof[:8]))
    sc.finish()
    sc.expect_counts(1, 1, closed=1)
    sc.check("the half frame was never judged", sc.count("client done: seen=1 accepted=1 rejected=0") == 1)
    sc.expect_deadline_kept()
    out.append(sc.result())

    # Keepalives flowing, no claims: the monitor reports the silence anyway, and
    # keeps the connection, because frames are arriving.
    sc = Scenario(con, "keepalive", d)
    with connect(host, port) as s:
        q = nxt()
        s.sendall(frame(q))
        recv_all(s, 64)
        t = time.monotonic()
        sc.sent.append((q, t))
        k = sentinel()
        sent, echoed, t_last_sentinel = 0, 0, t
        while time.monotonic() - t < 2.5 * d:
            time.sleep(0.25 * d)
            s.sendall(k)
            sent += 1
            echoed += recv_all(s, 64) == k
            t_last_sentinel = time.monotonic()
        sc.notes["sentinels"] = {"sent": sent, "echoed_unchanged": echoed}
    sc.finish()
    sc.expect_counts(1, 1, closed=0)
    hit = [tl for tl, line in sc.lines if "LIVENESS MISS" in line]
    sc.check("the MISS came while sentinels were still flowing", hit and hit[0] < t_last_sentinel)
    sc.check("every sentinel echoed byte for byte", sent >= 9 and echoed == sent, "%d of %d" % (echoed, sent))
    sc.check("no sentinel was judged", sc.count("REJECT") == 0
             and sc.count("client done: seen=1 accepted=1 rejected=0") == 1)
    sc.expect_deadline_kept()
    out.append(sc.result())

    # A hung client holding the only slot, and a claim queued behind it.
    sc = Scenario(con, "lockout", d)
    hung = connect(host, port)
    try:
        time.sleep(0.1 * d)                 # the hung client is accepted first
        t0 = time.monotonic()
        r = sc.claim(host, port, nxt())
        waited = time.monotonic() - t0
    finally:
        hung.close()
    sc.notes["queued_claim_waited_ms"] = round(waited * 1000.0, 1)
    sc.check("the queued claim ACCEPTed", r[16 + 6:16 + 8] == b"\x00\x00", r[16 + 6:16 + 8].hex())
    sc.check("the queued claim was served within the deadline", 0.5 * d <= waited < d + SLACK_S,
             "%.0f ms" % (waited * 1000.0))
    sc.finish()
    sc.expect_counts(1, 1, closed=1)
    sc.expect_deadline_kept()
    out.append(sc.result())
    return out


def stamp(a, d):
    def sha(p):
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    s = {"experiment": "liveness-demo", "publishes_timing": False,
         "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "service_port": a.port, "deadline_ms": int(d * 1000),
         "liveness_demo_sha256": sha(os.path.abspath(__file__)),
         "latency_probe_sha256": sha(lp.__file__)}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            argv = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == b"qemu-system-aarch64" and b"-kernel" in argv:
            k = argv[argv.index(b"-kernel") + 1].decode()
            if not os.path.isabs(k):        # relative to QEMU's cwd, not ours (lib-measure.sh's 2026-09-22 fix)
                try:
                    k = os.path.join(os.readlink("/proc/%s/cwd" % pid), k)
                except OSError:
                    pass
            s["guest_ifs"] = os.path.basename(k)            # a basename: no host path is published
            try:
                s["guest_ifs_sha256"] = sha(k)
            except OSError:
                s["guest_ifs_sha256"] = "unreadable"
    try:
        s["board"] = open("/proc/device-tree/model", "rb").read().rstrip(b"\0").decode()
        s["l4t"] = open("/etc/nv_tegra_release").readline().strip()
    except OSError:
        pass
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=7102)
    ap.add_argument("--console", required=True, help="the guest console log the launcher writes")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    con = Console(a.console)
    banners = [m for m in BANNER.finditer(con.head) if int(m.group(1)) == a.port]
    if not banners:
        sys.exit("FATAL: the console shows no deadline-mode monitor on :%d -- is this ifs-live?" % a.port)
    d = int(banners[-1].group(2)) / 1000.0
    os.makedirs(a.out, exist_ok=False)
    st = stamp(a, d)

    results = run(a, con, d)
    bad = na = 0
    rows = []
    for r in results:
        judged = [c for c in r["checks"] if c["ok"] is not None]
        fails = [c for c in judged if not c["ok"]]
        skipped = [c for c in r["checks"] if c["ok"] is None]
        bad += len(fails)
        na += len(skipped)
        ms = ", ".join("%d/%s" % (m["guest_ms"], m["host_ms"]) for m in r["misses"])
        rows.append("%-10s checks %2d/%-2d  misses (guest/host ms): %s%s%s" % (
            r["scenario"], len(judged) - len(fails), len(judged), ms or "-",
            "".join("\n    NOT APPLICABLE %s: %s" % (c["what"], c["detail"]) for c in skipped),
            "".join("\n    FAILED %s: %s" % (c["what"], c["detail"]) for c in fails)))
    st["checks_failed"] = bad
    st["checks_not_applicable"] = na
    with open(os.path.join(a.out, "liveness.json"), "w") as f:
        json.dump({"deadline_ms": int(d * 1000), "scenarios": results}, f, indent=1)
    with open(os.path.join(a.out, "stamp.json"), "w") as f:
        json.dump(st, f, indent=1)
    with open(os.path.join(a.out, "summary.txt"), "w") as f:
        f.write("\n".join(rows) + "\n")
    print("\n".join(rows))
    print("%s: %d check(s) failed" % ("PASS" if bad == 0 else "FAIL", bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
