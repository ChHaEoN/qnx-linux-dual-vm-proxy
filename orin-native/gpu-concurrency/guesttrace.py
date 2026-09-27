#!/usr/bin/env python3
"""guesttrace.py -- parse a QNX kernel event trace as qnx-tracectl hands it back (traceprinter's
text), and cut each read() a client sends to io-sock into segments (Phase 3b / A6, 2026-09-27;
run-trace.sh, trace_report.py).

THE TEXT. traceprinter prints one event per line, "t:0xLOW CPU:NN CLASS :EVENT args"; some events
put their arguments on continuation lines. LOW is the low 32 bits of the guest's cycle counter
(TRACE_CYCLES_PER_SEC in the header); a CONTROL :TIME event carries the high bits, and events are
in time order, so a decrease of LOW is a wrap.

THE SEGMENTS, for one read (a client's MSG_SENDV of an _IO_READ, type 0x0101, to io-sock), on one
CPU (every event must be on CPU 0):
  t0  the client's KER_CALL MSG_SENDV
  t1  the io-sock thread W's KER_EXIT MSG_RECEIVE* with the rcvid of the client's SND_MESSAGE
  t2  W's KER_CALL MSG_REPLY* or MSG_ERROR* with that rcvid
  t2e W's KER_EXIT of that call
  t4  W's next KER_CALL MSG_RECEIVE* (it blocks for the next message); t5 if the client runs first
  t5  the client's KER_EXIT MSG_SENDV
  A = t1 - t0    the send: the kernel delivers the message and switches to W
  B = t2 - t1    io-sock's work before it replies, its own kernel calls included
  R = t2e - t2   the reply call: the kernel copies the reply and readies the client
  Cw = t4 - t2e  io-sock's work after the reply, until W blocks again
  Ck = t5 - t4   the switch back: W's receive call, and the client's return
Also per read: the kernel calls W makes in B and in Cw (count and time, by name), and the time
threads other than the client and W ran inside [t0, t5] (idle, other io-sock threads, other).
"""
import re
import statistics as st

EV = re.compile(r"t:0x([0-9a-f]+) CPU:(\d+) (\w+)\s*:(\S+)\s*(.*)$")
IO_READ, IO_WRITE = 0x0101, 0x0102


def sections(text):
    """Split a qnx-tracectl reply into its sections: {"tracelogger": ..., "traceprinter": ...,
    "pidin": ...}, each the text between "=== NAME" and "=== NAME rc R", plus "rc" per section."""
    out, rc = {}, {}
    for m in re.finditer(r"^=== (\w+)\n(.*?)^=== \1 rc (-?\d+)$", text, re.M | re.S):
        out[m.group(1)] = m.group(2)
        rc[m.group(1)] = int(m.group(3))
    out["rc"] = rc
    return out


class Trace:
    """Events as (t_cycles, cpu, cls, name, args_text), names of processes and threads, and the
    header's attributes."""

    def __init__(self, text):
        self.attrs, self.events, self.procs, self.threads = {}, [], {}, {}
        self.buffers = []
        cur = None
        for line in text.split("\n"):
            if line.startswith("t:0x"):
                m = EV.match(line.rstrip())
                if m:
                    cur = [int(m.group(1), 16), int(m.group(2)), m.group(3), m.group(4), m.group(5).strip()]
                    self.events.append(cur)
                else:
                    cur = None
                continue
            s = line.strip()
            if cur is not None and s and line[:1] == " " and ":" in s and not s.startswith("--"):
                cur[4] = (cur[4] + " " + s).strip()
                continue
            m = re.match(r"\s*(TRACE_\w+):: (.*)$", line)
            if m:
                self.attrs[m.group(1)] = m.group(2).strip()
        self.hz = float(self.attrs.get("TRACE_CYCLES_PER_SEC", "0") or 0)
        high, last = 0, None
        for e in self.events:
            if e[2] == "CONTROL" and e[3] == "TIME":
                m = re.search(r"msb:0x([0-9a-f]+)", e[4])
                if m:
                    high = int(m.group(1), 16) << 32
            if last is not None and e[0] + high < last:
                high += 1 << 32
            e[0] += high
            last = e[0]
            if e[2] == "CONTROL" and e[3] == "BUFFER":
                m = re.search(r"sequence = (\d+)", e[4])
                if m:
                    self.buffers.append(int(m.group(1)))
            elif e[2] == "PROCESS" and e[3] == "PROCCREATE_NAME":
                m = re.search(r"\bpid:(\d+) name:(\S+)", e[4])
                if m:
                    self.procs[int(m.group(1))] = m.group(2)
            elif e[2] == "PROCESS" and e[3] == "PROCTHREAD_NAME":
                m = re.search(r"\bpid:(\d+) tid:(\d+) name:(.*)$", e[4])
                if m:
                    self.threads[(int(m.group(1)), int(m.group(2)))] = m.group(3).strip()

    def us(self, cycles):
        return cycles * 1e6 / self.hz

    def cpus(self):
        return sorted({e[1] for e in self.events})

    def buffers_contiguous(self):
        return all(b == a + 1 for a, b in zip(self.buffers, self.buffers[1:]))

    def pid_of(self, suffix):
        """Every pid whose process name ends in suffix."""
        return sorted(p for p, n in self.procs.items() if n.endswith(suffix))


def _pidtid(args):
    m = re.search(r"pid:(\d+) tid:(\d+)", args)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _rcvid(args):
    m = re.search(r"rcvid:(0x[0-9a-f]+)", args)
    return int(m.group(1), 16) if m else None


def messages(tr, server_pid):
    """Every message a thread sends to server_pid, in order: dicts with the client (pid, tid), the
    message type (low 16 bits of its first word), t0 (the client's KER_CALL) and the rcvid, and,
    once seen, t5 (the client's KER_EXIT of the same call). The running thread is the last
    THRUNNING's; one CPU is assumed (the caller checks cpus())."""
    running, pending, out = None, {}, []
    ev = tr.events
    for i, (t, _cpu, cls, name, args) in enumerate(ev):
        if cls == "THREAD" and name == "THRUNNING":
            running = _pidtid(args)
        elif cls == "KER_CALL" and name.startswith("MSG_SENDV") and running is not None:
            m = re.search(r'msg\[0\]:"[^"]*" \((0x[0-9a-f]+)', args)
            typ = int(m.group(1), 16) & 0xFFFF if m else None
            # the SND_MESSAGE that follows names the server and the rcvid
            for j in range(i + 1, min(i + 4, len(ev))):
                if ev[j][2] == "COMM" and ev[j][3] == "SND_MESSAGE":
                    mm = re.search(r"rcvid:(0x[0-9a-f]+) pid:(\d+)", ev[j][4])
                    if mm and int(mm.group(2)) == server_pid:
                        msg = {"client": running, "type": typ, "t0": t, "rcvid": int(mm.group(1), 16), "i0": i}
                        out.append(msg)
                        pending[running] = msg
                    break
        elif cls == "KER_EXIT" and name.startswith("MSG_SENDV") and running in pending:
            msg = pending.pop(running)
            msg["t5"], msg["i5"] = t, i
    return [m for m in out if "t5" in m]


def segments(tr, msg, server_pid):
    """Cut one message into A, B, R, Cw, Ck (cycles) and describe what ran; None if a boundary is
    missing (the reason in the second value)."""
    ev = tr.events
    running, w = msg["client"], None
    t1 = t2 = t2e = t4 = None
    kc = {"B": {}, "Cw": {}}
    open_call = None
    others = {"idle": 0, "io-sock": 0, "other": 0}
    last_t = msg["t0"]
    for i in range(msg["i0"], msg["i5"] + 1):
        t, _cpu, cls, name, args = ev[i]
        if running is not None and running != msg["client"] and running != w:
            key = "idle" if running[0] == 1 and tr.threads.get(running, "").startswith("idle") else (
                "io-sock" if running[0] == server_pid else "other")
            others[key] += t - last_t
        last_t = t
        if cls == "THREAD" and name == "THRUNNING":
            running = _pidtid(args)
            continue
        if running is None or running[0] != server_pid:
            continue
        if t1 is None:
            if cls == "KER_EXIT" and name.startswith("MSG_RECEIVE") and _rcvid(args) == msg["rcvid"]:
                t1, w = t, running
            continue
        if running != w:
            continue
        phase = "B" if t2 is None else ("Cw" if t2e is not None and t4 is None else None)
        if t2 is None and cls == "KER_CALL" and re.match(r"MSG_(REPLY|ERROR)", name) and _rcvid(args) == msg["rcvid"]:
            t2 = t
            continue
        if t2 is not None and t2e is None:
            if cls == "KER_EXIT" and re.match(r"MSG_(REPLY|ERROR)", name):
                t2e = t
            continue
        if t2e is not None and t4 is None and cls == "KER_CALL" and name.startswith("MSG_RECEIVE"):
            t4 = t
            continue
        if phase and cls == "KER_CALL":
            open_call = (name.split("/")[0], t)
        elif phase and cls == "KER_EXIT" and open_call and open_call[0] == name.split("/")[0]:
            n, d = kc[phase].get(open_call[0], (0, 0))
            kc[phase][open_call[0]] = (n + 1, d + t - open_call[1])
            open_call = None
    if t1 is None:
        return None, "no receive"
    if t2 is None or t2e is None:
        return None, "no reply"
    t5 = msg["t5"]
    if t4 is None or t4 > t5:
        t4 = t5
    seg = {"A": t1 - msg["t0"], "B": t2 - t1, "R": t2e - t2, "Cw": t4 - t2e, "Ck": t5 - t4,
           "total": t5 - msg["t0"], "w": w, "kc": kc, "others": others}
    return seg, ""


def pick_second_reads(msgs, gap_cycles):
    """The network case: a client's _IO_READ whose previous message to the server, from the same
    thread, was an _IO_READ that lasted >= gap_cycles (it blocked until the frame came)."""
    last, out = {}, []
    for m in msgs:
        p = last.get(m["client"])
        if m["type"] == IO_READ and p is not None and p["type"] == IO_READ and p["t5"] - p["t0"] >= gap_cycles:
            out.append(m)
        last[m["client"]] = m
    return out


def pick_loopback_reads(msgs, gap_cycles):
    """The loopback case (qnx-ipcbench's spaced sock op): a client's _IO_READ whose two previous
    messages to the server, from the same thread, were an _IO_WRITE and then an _IO_READ, with the
    write sent >= gap_cycles after the message before it ended (the 2 ms sleep)."""
    hist, out = {}, []
    for m in msgs:
        h = hist.setdefault(m["client"], [])
        if (m["type"] == IO_READ and len(h) >= 3 and h[-1]["type"] == IO_READ and h[-2]["type"] == IO_WRITE
                and h[-2]["t0"] - h[-3]["t5"] >= gap_cycles):
            out.append(m)
        h.append(m)
        del h[:-3]
    return out


def summarise(tr, segs):
    """Medians (us) of each segment, the kernel calls W made per read, and the others."""
    if not segs:
        return None
    s = {k: st.median(tr.us(x[k]) for x in segs) for k in ("A", "B", "R", "Cw", "Ck", "total")}
    s["n"] = len(segs)
    for key in ("idle", "io-sock", "other"):
        s["others_" + key] = st.mean(tr.us(x["others"][key]) for x in segs)
    for ph in ("B", "Cw"):
        names = sorted({k for x in segs for k in x["kc"][ph]})
        s["kc_" + ph] = {k: (sum(x["kc"][ph].get(k, (0, 0))[0] for x in segs) / len(segs),
                             st.median(tr.us(x["kc"][ph].get(k, (0, 0))[1]) for x in segs)) for k in names}
    ws = {}
    for x in segs:
        ws[tr.threads.get(x["w"], "?")] = ws.get(tr.threads.get(x["w"], "?"), 0) + 1
    s["w_names"] = ws
    return s
