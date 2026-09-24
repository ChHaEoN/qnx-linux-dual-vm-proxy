#!/usr/bin/env python3
"""blockpath_trace.py -- reduce an ftrace of one arm to the events of one
exchange's host-side path, and cut it into segments per exchange (Phase 3b /
A6, 2026-09-24; run-blockpath.sh).

  reduce --map ROLE:PID[,ROLE:PID...]   the trace file on stdin (roles m, v0, v1:
      QEMU's main thread and its two vCPU threads). Writes one line per event,
      "seconds core EVENT fields", and nothing else: no other process's name or
      pid, no kernel address. Exits 2 on lost events, a missing header or an
      unparsed line. The events, and what each line keeps:
        X len             net_dev_xmit on tap-qnx      a frame into the guest's tap
        R len             netif_receive_skb, tap-qnx   a frame out of the guest
        I num level ctx   kvm_irq_line                 an interrupt line set by ctx
        W who ctx         sched_waking of m, v0 or v1  woken by ctx
        S who             sched_switch into m, v0, v1  now running on this core
        K wait|poll ns ctx  kvm_vcpu_wakeup            ctx's halt ended (blocked or polled)
      ctx is the role of the running task, or "o" for any other.
  segments FILE [--min-len N]           one reduced file: one JSON line per
      exchange with its segments, then a summary line.

THE SEGMENTS of one exchange, all on the host's mono clock:
  T0   the request into the tap (X, len >= --min-len)
  I    the first rising interrupt line after T0, on the interrupt number that most
       often follows a request (the virtio-net SPI)
  V    the first halt end (K) after I, on any vCPU: that vCPU is running again
  TX   the first waking of QEMU's main thread after V by a vCPU (the guest's
       transmit notify, through an ioeventfd)
  OUT  the first frame out of the tap after TX (R, len >= --min-len): the reply
  A = I - T0 (the host and QEMU take the request in), B = V - I (the vCPU comes
  out of its halt: a poll that sees the interrupt, or a wake-up, a schedule-in and
  the vcpu_load), C = TX - V (the guest's work, including any wake-ups of the
  other vCPU), D = OUT - TX (QEMU hands the reply to the host).
  Also counted inside [I, TX]: halts that ended blocked and polled, and for each
  blocked one the wake-up's latency (W to S) and the load (S to K). And inside
  [V, OUT], every waking of QEMU's main thread by a vCPU ("m_wakes"): if the guest
  also notifies its receive queue before it transmits, the first such waking is
  not the transmit, and the C/D boundary moves (A+B+C+D does not).
An exchange missing any of the five marks is counted and skipped, never guessed.
Each row keeps k, the request's index in the trace (0-based), so a row can be matched
to the probe's own sample for the same exchange (run-tailpath.sh).
"""
import argparse
import json
import re
import statistics as st
import sys
from collections import Counter

HEADER = re.compile(r"^#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)")
LOST = re.compile(r"\[LOST \d+ EVENTS\]")
PREFIX = re.compile(r"^\s*(.+?)-(\d+)\s+\[(\d+)\]\s+(?:\S+\s+)?(\d+\.\d+):\s+(\w+):\s+(.*)$")
EVENTS = ("net_dev_xmit", "netif_receive_skb", "kvm_irq_line", "sched_waking", "sched_switch", "kvm_vcpu_wakeup")


def parse_map(spec):
    m = {}
    for part in spec.split(","):
        role, _, pid = part.partition(":")
        if role not in ("m", "v0", "v1") or not pid.isdigit():
            raise ValueError("bad --map entry %r (want m|v0|v1:PID)" % part)
        m[int(pid)] = role
    return m


def _f(body, key):
    m = re.search(r"(?:^|\s)%s=(\S+)" % re.escape(key), body)
    return m.group(1) if m else None


def reduce(lines, pid_role, tap="tap-qnx"):
    """(list of reduced lines, error)."""
    seen_header, out = False, []
    for no, line in enumerate(lines, 1):
        if LOST.search(line):
            return None, "lost events: a LOST line at line %d" % no
        h = HEADER.match(line)
        if h:
            seen_header = True
            if h.group(1) != h.group(2):
                return None, "lost events: entries-in-buffer %s, entries-written %s" % (h.group(1), h.group(2))
            continue
        if line.startswith("#") or not line.strip():
            continue
        m = PREFIX.match(line)
        if not m or m.group(5) not in EVENTS:
            return None, "unparsed line at line %d" % no      # its text names other processes: not echoed
        pid, core, ts, ev, body = int(m.group(2)), m.group(3), m.group(4), m.group(5), m.group(6)
        ctx = pid_role.get(pid, "o")
        if ev in ("net_dev_xmit", "netif_receive_skb"):
            if _f(body, "dev") != tap:
                return None, "a %s on a device other than %s at line %d: the filter failed" % (ev, tap, no)
            out.append("%s %s %s %s" % (ts, core, "X" if ev == "net_dev_xmit" else "R", _f(body, "len")))
        elif ev == "kvm_irq_line":
            mm = re.search(r"num: (\d+), level: (\d+)", body)
            if not mm:
                return None, "unparsed kvm_irq_line at line %d" % no
            out.append("%s %s I %s %s %s" % (ts, core, mm.group(1), mm.group(2), ctx))
        elif ev == "sched_waking":
            who = pid_role.get(int(_f(body, "pid") or -1))
            if who is None:
                return None, "a sched_waking of a thread not in the map at line %d: the filter failed" % no
            out.append("%s %s W %s %s" % (ts, core, who, ctx))
        elif ev == "sched_switch":
            who = pid_role.get(int(_f(body, "next_pid") or -1))
            if who is None:
                return None, "a sched_switch into a thread not in the map at line %d: the filter failed" % no
            out.append("%s %s S %s" % (ts, core, who))
        else:  # kvm_vcpu_wakeup
            mm = re.match(r"(wait|poll) time (\d+) ns", body)
            if not mm:
                return None, "unparsed kvm_vcpu_wakeup at line %d" % no
            out.append("%s %s K %s %s %s" % (ts, core, mm.group(1), mm.group(2), ctx))
    if not seen_header:
        return None, "no entries-in-buffer/entries-written header: cannot tell whether events were lost"
    return out, None


def read(path):
    ev = []
    for line in open(path, encoding="utf-8"):
        f = line.split()
        if len(f) >= 3:
            ev.append((float(f[0]) * 1e6, int(f[1]), f[2], f[3:]))   # microseconds
    ev.sort(key=lambda e: e[0])
    return ev


def segments(ev, min_len=100, req_len=None):
    """(per-exchange dicts, summary dict). A request is a frame into the tap of
    length >= min_len, or, with req_len, of exactly that length (2026-09-24,
    run-tailpath.sh's smoke run: a 101-byte frame that was not the probe's counted
    as a request, and the round could not be aligned with the probe)."""
    reqs = [i for i, e in enumerate(ev) if e[2] == "X"
            and (int(e[3][0]) == req_len if req_len else int(e[3][0]) >= min_len)]
    # The interrupt number that most often rises first after a request.
    firsts = Counter()
    for k, i in enumerate(reqs):
        end = reqs[k + 1] if k + 1 < len(reqs) else len(ev)
        for e in ev[i + 1:end]:
            if e[2] == "I" and e[3][1] == "1":
                firsts[e[3][0]] += 1
                break
    irq = firsts.most_common(1)[0][0] if firsts else None
    rows, skipped = [], Counter()
    for k, i in enumerate(reqs):
        end = reqs[k + 1] if k + 1 < len(reqs) else len(ev)
        win = ev[i:end]
        t0 = win[0][0]

        def first(pred, after):
            for e in win:
                if e[0] >= after and pred(e):
                    return e
            return None
        ei = first(lambda e: e[2] == "I" and e[3][0] == irq and e[3][1] == "1", t0)
        if ei is None:
            skipped["no interrupt"] += 1
            continue
        ev_v = first(lambda e: e[2] == "K", ei[0])
        if ev_v is None:
            skipped["no halt end"] += 1
            continue
        etx = first(lambda e: e[2] == "W" and e[3][0] == "m" and e[3][1] in ("v0", "v1"), ev_v[0])
        if etx is None:
            skipped["no transmit notify"] += 1
            continue
        eout = first(lambda e: e[2] == "R" and int(e[3][0]) >= min_len, etx[0])
        if eout is None:
            skipped["no reply"] += 1
            continue
        blocked = polled = 0
        wake_lat, load_lat = [], []
        for e in win:
            if not (ei[0] <= e[0] <= etx[0]) or e[2] != "K":
                continue
            if e[3][0] == "poll":
                polled += 1
                continue
            blocked += 1
            who = e[3][2]
            sw = [x for x in win if x[2] == "S" and x[3][0] == who and x[0] <= e[0]]
            wk = [x for x in win if x[2] == "W" and x[3][0] == who and sw and x[0] <= sw[-1][0]]
            if sw and wk:
                wake_lat.append(sw[-1][0] - wk[-1][0])
                load_lat.append(e[0] - sw[-1][0])
        m_wakes = sum(1 for e in win if eout[0] >= e[0] >= ev_v[0] and e[2] == "W" and e[3][0] == "m"
                      and e[3][1] in ("v0", "v1"))
        rows.append({"k": k, "m_wakes": m_wakes, "t0": t0, "A": ei[0] - t0, "B": ev_v[0] - ei[0], "C": etx[0] - ev_v[0],
                     "D": eout[0] - etx[0], "total": eout[0] - t0, "v_first": ev_v[3][0],
                     "v_ctx": ev_v[3][2], "blocked": blocked, "polled": polled,
                     "wake_us": sum(wake_lat), "load_us": sum(load_lat)})
    summ = {"requests": len(reqs), "segmented": len(rows), "skipped": dict(skipped), "irq": irq,
            "req_len": req_len}
    if rows:
        for key in ("A", "B", "C", "D", "total", "blocked", "polled", "wake_us", "load_us", "m_wakes"):
            summ[key + "_p50"] = st.median(r[key] for r in rows)
        summ["first_halt_blocked_share"] = sum(r["v_first"] == "wait" for r in rows) / len(rows)
    return rows, summ


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reduce")
    r.add_argument("--map", required=True)
    s = sub.add_parser("segments")
    s.add_argument("file")
    s.add_argument("--min-len", type=int, default=100)
    a = ap.parse_args(argv)
    if a.cmd == "reduce":
        try:
            pid_role = parse_map(a.map)
        except ValueError as e:
            print("blockpath_trace: %s" % e, file=sys.stderr)
            return 2
        out, err = reduce(sys.stdin, pid_role)
        if err:
            print("blockpath_trace: %s" % err, file=sys.stderr)
            return 2
        sys.stdout.write("".join(l + "\n" for l in out))
        return 0
    rows, summ = segments(read(a.file), a.min_len)
    for row in rows:
        print(json.dumps(row, sort_keys=True))
    print(json.dumps({"summary": summ}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
