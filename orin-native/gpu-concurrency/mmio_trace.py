#!/usr/bin/env python3
"""mmio_trace.py reduce < trace > counts.json -- KVM's MMIO aborts in one ftrace window, counted per
guest-physical address (Phase 3b / A6, 2026-09-29; run-mmio.sh).

Reads the text of /sys/kernel/tracing/trace with two events on:
  kvm_mmio            "mmio <type> len <n> gpa 0x<gpa> val 0x<val>"; arm64 KVM (Linux 5.15,
                      arch/arm64/kvm/mmio.c) traces it in io_mem_abort for every MMIO abort it
                      decodes -- "unsatisfied-read" for a read, "write" for a write -- before it
                      knows who will handle the access, and "read" again when a read completes,
                      in the kernel or back from userspace
  kvm_userspace_exit  "reason KVM_EXIT_MMIO (6)" when an access goes out to QEMU
An access is one "unsatisfied-read" or one "write". It was handled in userspace when the next
KVM event on the same thread is a kvm_userspace_exit with reason KVM_EXIT_MMIO; otherwise KVM
handled it in the kernel.

Writes JSON: per "gpa|r" and "gpa|w" (gpa in hex) the accesses, and how many of them went to
userspace; the completed reads; the userspace exits by reason; KVM_EXIT_MMIO exits with no access
before them on their thread (a window's edge can leave one per vCPU); the lines parsed, of any
event, beside the buffer's entries; the first and last timestamps. Exits 2, writing nothing, if
the trace does not show that no event was lost (the entries-in-buffer/entries-written header
missing or unequal, or a LOST line, with or without a count), or if any line that is neither a
comment nor blank does not parse. The JSON carries no pid, comm or value; the raw trace a harness
keeps carries all three.
"""
import json
import re
import sys

HEADER = re.compile(r"^#\s*entries-in-buffer/entries-written:\s*(\d+)/(\d+)")
LOST = re.compile(r"\[LOST (?:\d+ )?EVENTS\]")
PREFIX = re.compile(r"^\s*(.+?)-(\d+)\s+\[(\d+)\]\s+(?:\S+\s+)?(\d+\.\d+):\s+(\w+):\s+(.*)$")
MMIO = re.compile(r"^mmio (unsatisfied-read|read|write) len (\d+) gpa 0x([0-9a-fA-F]+) val 0x[0-9a-fA-F]+")
UEXIT = re.compile(r"^reason (\S+) \((-?\d+)\)")


def reduce(lines):
    header = None
    acc, user, completed, reasons = {}, {}, {}, {}
    pending = {}   # pid -> the key of its last access, until the thread's next KVM event
    events, matched, unpaired, first, last = 0, 0, 0, None, None
    for no, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if LOST.search(line):
            return None, "lost events: a LOST line at line %d" % no
        if line.startswith("#"):
            h = HEADER.match(line)
            if h:
                header = (int(h.group(1)), int(h.group(2)))
                if header[0] != header[1]:
                    return None, "lost events: entries-in-buffer %d, entries-written %d" % header
            continue
        if not line.strip():
            continue
        m = PREFIX.match(line)
        if not m:
            return None, "an unparsed line at line %d" % no
        matched += 1
        if m.group(5) not in ("kvm_mmio", "kvm_userspace_exit"):
            continue
        pid, ts, ev, body = m.group(2), float(m.group(4)), m.group(5), m.group(6)
        events += 1
        first = ts if first is None else first
        last = ts
        if ev == "kvm_mmio":
            mm = MMIO.match(body)
            if not mm:
                return None, "an unparsed kvm_mmio line at line %d" % no
            kind, gpa = mm.group(1), int(mm.group(3), 16)
            if kind == "read":
                key = "%#x|r" % gpa
                completed[key] = completed.get(key, 0) + 1
                pending.pop(pid, None)
                continue
            key = "%#x|%s" % (gpa, "w" if kind == "write" else "r")
            acc[key] = acc.get(key, 0) + 1
            pending[pid] = key
        else:
            um = UEXIT.match(body)
            if not um:
                return None, "an unparsed kvm_userspace_exit line at line %d" % no
            reasons[um.group(1)] = reasons.get(um.group(1), 0) + 1
            key = pending.pop(pid, None)
            if um.group(1) == "KVM_EXIT_MMIO":
                if key is None:
                    unpaired += 1
                else:
                    user[key] = user.get(key, 0) + 1
    if header is None:
        return None, "no entries-in-buffer/entries-written header: cannot tell whether events were lost"
    return {"events": events, "lines_matched": matched, "entries": header[0], "first_ts": first,
            "last_ts": last, "accesses": acc, "to_userspace": user, "reads_completed": completed,
            "userspace_exits": reasons, "unpaired_mmio_exits": unpaired}, None


def main(argv):
    if argv[:1] != ["reduce"]:
        print("usage: mmio_trace.py reduce < trace > counts.json", file=sys.stderr)
        return 1
    doc, err = reduce(sys.stdin)
    if err:
        print("mmio_trace: %s" % err, file=sys.stderr)
        return 2
    json.dump(doc, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
