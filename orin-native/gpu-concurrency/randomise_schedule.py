#!/usr/bin/env python3
"""randomise_schedule.py -- the randomisation schedule of run-randomise.sh (Phase 3b / A6,
2026-10-17), drawn from one master seed before any run.

  randomise_schedule.py --seed N [--out FILE]    write the schedule (stdout without --out) and
                                                 print its sha256 (to stderr without --out)
  randomise_schedule.py --verify FILE            re-derive FILE from its own master seed; exit 0
                                                 and print its sha256 only when the bytes agree

WHAT IT DRAWS, every draw from one stream seeded by the master seed, in this order:
  1. the first scored board boot's S pattern, FRRF or RFFR; b1, b3 and b5 run it and b2, b4 and
     b6 the other;
  2. the bootstrap seed of the report's P4 interval (0 .. 2^32 - 1);
  3. the smoke board boot's pattern, FR or RF;
  4. board boot by board boot (b0, the smoke, then b1 .. b6), VM boot by VM boot:
     - for an R VM boot, the permutation of QEMU's three thread groups (vCPU 0, vCPU 1, every
       other thread) onto cores 0, 1 and 2, one of the six, then its pad;
     - the order of the four cells (O, L): a permutation of FF FR RF RR (the smoke boot runs
       the first two of it);
     - round by round (r = 1 ..): for an O-random round the order of the four arms; for an
       L-random round the host monitor's pad, the namespace monitor's pad, then for each probe
       launch, arms A to D, its pad and its PYTHONHASHSEED.
  Round 0 of every VM boot is the settling round: the arms in the ladder's order A B C D, every
  launch fixed. A pad is E bytes, E uniform over 0, 16, ..., 4080; a hash seed is uniform over
  0 .. 2^32 - 1.

THE LEVELS, as the harness launches them:
  F (fixed)   env -i with the fixed list below, then setarch -R (ADDR_NO_RANDOMIZE); the
              probe gets PYTHONHASHSEED=0. QEMU's threads: vCPU 0 on core 1, vCPU 1 on core 2,
              every other thread on core 0 (pin=1,2,0).
  R (random)  env -i with the fixed list and A6PAD of E bytes (the letter x), ASLR as the
              kernel draws it; the probe gets its drawn PYTHONHASHSEED. QEMU's threads by the
              drawn permutation.
  Each launch line states the size of the environment the launch will carry, which the harness
  reads back from /proc/PID/environ.

WHY random() ALONE. The schedule is drawn on one machine and its hash checked on another, under
another Python. random() is the one method whose sequence Python promises not to change for a given
seed; randrange, choice, shuffle and sample are not. So every integer is int(random() * n) and every
permutation a Fisher-Yates shuffle written here.

THE FILE. Plain lines, LF, in a fixed shape the harness greps and parse() checks:
  a6-randomise-schedule 1
  master_seed N
  bootstrap_seed N
  env <the fixed list>
  first_pattern FRRF|RFFR
  boot <tag> smoke|scored <pattern>
  vm <tag> v<n> S=F|R norand=0|1 pad=-|E env=BYTES pin=V0,V1,REST cells=<cell>,...
  round <tag> v<n> r<k> cell=settle|<cell> O=F|R L=F|R order=<arm>,<arm>,<arm>,<arm>
  mon <tag> v<n> r<k> host|ns norand=0|1 pad=-|E env=BYTES
  probe <tag> v<n> r<k> A|B|C|D norand=0|1 pad=-|E hashseed=N env=BYTES
"""
import argparse
import hashlib
import os
import random
import sys

FORMAT = "a6-randomise-schedule 1"
FIXED_ENV = ("PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C")
ARMS = ("A", "B", "C", "D")
CELLS = ("FF", "FR", "RF", "RR")
PADS = tuple(range(0, 4081, 16))
HASHSEEDS = 2 ** 32
F_PIN = (1, 2, 0)
PINS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
PATTERNS = ("FRRF", "RFFR")
SMOKE = "b0"
SCORED = ("b1", "b2", "b3", "b4", "b5", "b6")
SCORED_VMS, SCORED_ROUNDS = 4, 4
SMOKE_VMS, SMOKE_ROUNDS = 2, 2


class _Stream(object):
    """Integers and permutations from random() alone (see WHY random() ALONE)."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def below(self, n):
        return min(n - 1, int(self.r.random() * n))

    def permutation(self, items):
        a = list(items)
        for i in range(len(a) - 1, 0, -1):
            j = self.below(i + 1)
            a[i], a[j] = a[j], a[i]
        return a


def launch_env(pad, hashseed=None):
    """The environment a launch carries: the fixed list, PYTHONHASHSEED for the probe, A6PAD for
    a random layout. pad None is a fixed layout."""
    env = list(FIXED_ENV)
    if hashseed is not None:
        env.append("PYTHONHASHSEED=%d" % hashseed)
    if pad is not None:
        env.append("A6PAD=" + "x" * pad)
    return env


def env_bytes(env):
    """The size of /proc/PID/environ for that environment: every entry and its NUL."""
    return sum(len(e.encode("utf-8")) + 1 for e in env)


def _pad(p):
    return "-" if p is None else str(p)


def generate(master_seed):
    if not isinstance(master_seed, int) or master_seed < 0:
        raise ValueError("the master seed is a non-negative integer")
    st = _Stream(master_seed)
    first = PATTERNS[st.below(2)]
    other = PATTERNS[1] if first == PATTERNS[0] else PATTERNS[0]
    bootstrap = st.below(HASHSEEDS)
    smoke = ("FR", "RF")[st.below(2)]
    out = [FORMAT, "master_seed %d" % master_seed, "bootstrap_seed %d" % bootstrap,
           "env " + " ".join(FIXED_ENV), "first_pattern " + first]
    boots = [(SMOKE, "smoke", smoke, SMOKE_ROUNDS)]
    boots += [(tag, "scored", first if i % 2 == 0 else other, SCORED_ROUNDS) for i, tag in enumerate(SCORED)]
    for tag, kind, pattern, nrounds in boots:
        out.append("boot %s %s %s" % (tag, kind, pattern))
        for v, s in enumerate(pattern, 1):
            if s == "F":
                pin, vpad, norand = F_PIN, None, 1
            else:
                pin = PINS[st.below(len(PINS))]
                vpad, norand = PADS[st.below(len(PADS))], 0
            cells = st.permutation(CELLS)[:nrounds]
            out.append("vm %s v%d S=%s norand=%d pad=%s env=%d pin=%s cells=%s" % (
                tag, v, s, norand, _pad(vpad), env_bytes(launch_env(vpad)), ",".join(str(c) for c in pin),
                ",".join(cells)))
            for r in range(nrounds + 1):
                if r == 0:
                    cell, o, lay, order = "settle", "F", "F", list(ARMS)
                else:
                    cell = cells[r - 1]
                    o, lay = cell[0], cell[1]
                    order = list(ARMS) if o == "F" else st.permutation(ARMS)
                out.append("round %s v%d r%d cell=%s O=%s L=%s order=%s" % (tag, v, r, cell, o, lay, ",".join(order)))
                mons = {}
                for who in ("host", "ns"):
                    mons[who] = None if lay == "F" else PADS[st.below(len(PADS))]
                probes = {}
                for a in ARMS:
                    if lay == "F":
                        probes[a] = (None, 0)
                    else:
                        p = PADS[st.below(len(PADS))]
                        probes[a] = (p, st.below(HASHSEEDS))
                for who in ("host", "ns"):
                    p = mons[who]
                    out.append("mon %s v%d r%d %s norand=%d pad=%s env=%d" % (
                        tag, v, r, who, 1 if p is None else 0, _pad(p), env_bytes(launch_env(p))))
                for a in ARMS:
                    p, hs = probes[a]
                    out.append("probe %s v%d r%d %s norand=%d pad=%s hashseed=%d env=%d" % (
                        tag, v, r, a, 1 if p is None else 0, _pad(p), hs, env_bytes(launch_env(p, hashseed=hs))))
    return "\n".join(out) + "\n"


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _kv(tokens, keys):
    d = {}
    for t in tokens:
        k, sep, v = t.partition("=")
        if not sep or k in d:
            raise ValueError("not key=value: %r" % t)
        d[k] = v
    if sorted(d) != sorted(keys):
        raise ValueError("keys %s, expected %s" % (sorted(d), sorted(keys)))
    return d


def _int(s, lo=0, hi=None):
    if not s.isdigit():
        raise ValueError("not a number: %r" % s)
    n = int(s)
    if n < lo or (hi is not None and n > hi):
        raise ValueError("out of range: %r" % s)
    return n


def _padv(s):
    if s == "-":
        return None
    p = _int(s)
    if p not in PADS:
        raise ValueError("not a pad of the grid: %r" % s)
    return p


def _launch(d, probe=False):
    norand = _int(d["norand"], 0, 1)
    pad = _padv(d["pad"])
    if (pad is None) != (norand == 1):
        raise ValueError("a fixed launch has no pad and a random one has one")
    hs = _int(d["hashseed"], 0, HASHSEEDS - 1) if probe else None
    env = _int(d["env"])
    if env != env_bytes(launch_env(pad, hashseed=hs)):
        raise ValueError("env=%d is not the size of that launch's environment" % env)
    out = {"norand": norand, "pad": pad, "env": env}
    if probe:
        out["hashseed"] = hs
    return out


def parse(text):
    """The schedule as a dict, or ValueError for anything that is not a file generate() writes:
    every line of a known shape, every launch's environment size its own, every board boot,
    VM boot, round and launch present exactly once."""
    lines = text.split("\n")
    if not text.endswith("\n") or "\r" in text:
        raise ValueError("not LF lines")
    lines = lines[:-1]
    if len(lines) < 5 or lines[0] != FORMAT:
        raise ValueError("not a %r file" % FORMAT)
    head = [ln.split(" ", 1) for ln in lines[1:5]]
    if [h[0] for h in head] != ["master_seed", "bootstrap_seed", "env", "first_pattern"] or any(len(h) != 2 for h in head):
        raise ValueError("header lines out of shape")
    s = {"master_seed": _int(head[0][1]), "bootstrap_seed": _int(head[1][1], 0, HASHSEEDS - 1),
         "first_pattern": head[3][1], "boots": {}}
    if head[2][1] != " ".join(FIXED_ENV):
        raise ValueError("env line %r is not the fixed list" % head[2][1])
    if s["first_pattern"] not in PATTERNS:
        raise ValueError("first_pattern %r" % s["first_pattern"])
    for ln in lines[5:]:
        t = ln.split(" ")
        kind = t[0]
        if kind == "boot":
            if len(t) != 4 or t[1] in s["boots"] or t[1] not in (SMOKE,) + SCORED:
                raise ValueError("boot line %r" % ln)
            want = "smoke" if t[1] == SMOKE else "scored"
            if t[2] != want:
                raise ValueError("boot line %r" % ln)
            s["boots"][t[1]] = {"kind": t[2], "pattern": t[3], "vms": {}}
            continue
        if kind not in ("vm", "round", "mon", "probe") or len(t) < 3:
            raise ValueError("unknown line %r" % ln)
        b = s["boots"].get(t[1])
        if b is None or not t[2].startswith("v"):
            raise ValueError("line before its boot: %r" % ln)
        v = _int(t[2][1:], 1, 4)
        if kind == "vm":
            if v in b["vms"]:
                raise ValueError("vm twice: %r" % ln)
            d = _kv(t[3:], ("S", "norand", "pad", "env", "pin", "cells"))
            lau = _launch(d)
            pin = tuple(_int(x, 0, 2) for x in d["pin"].split(","))
            cells = d["cells"].split(",")
            if d["S"] not in ("F", "R") or sorted(pin) != [0, 1, 2] or any(c not in CELLS for c in cells) \
                    or len(set(cells)) != len(cells):
                raise ValueError("vm line %r" % ln)
            if (d["S"] == "F") != (lau["norand"] == 1) or (d["S"] == "F" and pin != F_PIN):
                raise ValueError("vm line %r" % ln)
            b["vms"][v] = dict(lau, S=d["S"], pin=pin, cells=cells, rounds={})
            continue
        vm = b["vms"].get(v)
        if vm is None or len(t) < 4 or not t[3].startswith("r"):
            raise ValueError("line before its vm: %r" % ln)
        r = _int(t[3][1:], 0, 4)
        if kind == "round":
            if r in vm["rounds"]:
                raise ValueError("round twice: %r" % ln)
            d = _kv(t[4:], ("cell", "O", "L", "order"))
            order = d["order"].split(",")
            if sorted(order) != sorted(ARMS):
                raise ValueError("round line %r" % ln)
            if r == 0:
                if (d["cell"], d["O"], d["L"]) != ("settle", "F", "F"):
                    raise ValueError("round 0 is the settling round: %r" % ln)
            elif r > len(vm["cells"]) or d["cell"] != vm["cells"][r - 1] or d["O"] + d["L"] != d["cell"]:
                raise ValueError("round line %r" % ln)
            if d["O"] == "F" and order != list(ARMS):
                raise ValueError("a fixed order is the ladder's: %r" % ln)
            vm["rounds"][r] = {"cell": d["cell"], "O": d["O"], "L": d["L"], "order": order, "mon": {}, "probe": {}}
            continue
        rd = vm["rounds"].get(r)
        if rd is None or len(t) < 5:
            raise ValueError("line before its round: %r" % ln)
        who = t[4]
        if kind == "mon":
            if who not in ("host", "ns") or who in rd["mon"]:
                raise ValueError("mon line %r" % ln)
            lau = _launch(_kv(t[5:], ("norand", "pad", "env")))
            rd["mon"][who] = lau
        else:
            if who not in ARMS or who in rd["probe"]:
                raise ValueError("probe line %r" % ln)
            lau = _launch(_kv(t[5:], ("norand", "pad", "hashseed", "env")), probe=True)
            rd["probe"][who] = lau
        if (lau["norand"] == 1) != (rd["L"] == "F") or (who in ARMS and rd["L"] == "F" and lau["hashseed"] != 0):
            raise ValueError("a launch that does not follow its round's L: %r" % ln)
    if list(s["boots"]) != [SMOKE] + list(SCORED):
        raise ValueError("board boots %s" % list(s["boots"]))
    for tag, b in s["boots"].items():
        nvm, nr = (SMOKE_VMS, SMOKE_ROUNDS) if tag == SMOKE else (SCORED_VMS, SCORED_ROUNDS)
        if sorted(b["vms"]) != list(range(1, nvm + 1)) or "".join(b["vms"][v]["S"] for v in sorted(b["vms"])) != b["pattern"]:
            raise ValueError("board boot %s is not whole" % tag)
        for vm in b["vms"].values():
            if len(vm["cells"]) != nr or sorted(vm["rounds"]) != list(range(nr + 1)):
                raise ValueError("a VM boot of %s is not whole" % tag)
            for rd in vm["rounds"].values():
                if sorted(rd["mon"]) != ["host", "ns"] or sorted(rd["probe"]) != list(ARMS):
                    raise ValueError("a round of %s is not whole" % tag)
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seed", type=int, help="the master seed")
    g.add_argument("--verify", metavar="FILE", help="re-derive FILE from its master seed")
    ap.add_argument("--out", help="write here (refused if it exists)")
    a = ap.parse_args(argv)
    if a.verify:
        raw = open(a.verify, "rb").read()
        try:
            text = raw.decode("utf-8")
            seed = parse(text)["master_seed"]
        except (UnicodeDecodeError, ValueError) as e:
            print("randomise_schedule: %s is not a schedule: %s" % (a.verify, e), file=sys.stderr)
            return 1
        if generate(seed).encode("utf-8") != raw:
            print("randomise_schedule: %s does not re-derive from its master seed %d" % (a.verify, seed), file=sys.stderr)
            return 1
        print("%s  %s (re-derived from master seed %d)" % (hashlib.sha256(raw).hexdigest(), a.verify, seed))
        return 0
    if a.seed < 0:
        print("randomise_schedule: the master seed is a non-negative integer", file=sys.stderr)
        return 2
    text = generate(a.seed)
    digest = sha256(text)
    if not a.out:
        sys.stdout.write(text)
        print("sha256 %s" % digest, file=sys.stderr)
        return 0
    if os.path.lexists(a.out):
        print("randomise_schedule: %s exists; refusing to overwrite it" % a.out, file=sys.stderr)
        return 1
    with open(a.out, "x", newline="\n", encoding="utf-8") as f:
        f.write(text)
    print("%s  %s" % (digest, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
