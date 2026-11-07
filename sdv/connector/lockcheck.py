#!/usr/bin/env python3
"""lockcheck.py -- hold a connector lock to the wheels it names and to what the SDK wheel declares (sdv/connector;
SDV Phase 4 WP0).

Standard library only. No network: it reads files a `pip download` put in a
directory, and never fetches anything itself.

    python3 sdv/connector/lockcheck.py wheels DIR [--arch aarch64] [--lock FILE] [--sdk FILE]
    python3 sdv/connector/lockcheck.py pair [--arch aarch64] [--lock FILE] [--sdk FILE]

WHY
  The connector's image installs its lock with `pip install --require-hashes --no-deps --only-binary=:all:`.
  --no-deps skips the resolver, so pip would install an awscrt that the pinned awsiotsdk does not declare and say
  nothing; the SDK names exactly one version (Requires-Dist: awscrt==<version>). sdk-requires.json records what
  the pinned awsiotsdk wheel's METADATA says, bound to that file by its sha256, and the tests hold both locks to
  the record (tests/test_sdv_connector.py). The record itself is only as good as the wheel it was read from, so
  `wheels` reads the real one again.

WHAT IT CHECKS
  wheels  DIR holds exactly the lock's files (each pin's `# <file>.whl` comment), each hashing to its pin's
          sha256; the SDK wheel's METADATA headers (Name, Version, Requires-Python, every Requires-Dist) equal the
          record; and `pair` below. Prints one JSON object; exit 1 on any problem.
  pair    the lock pins the record's wheel (version, sha256, file), and every unconditional Requires-Dist of the
          record is one exact pin (name==version) that the lock holds at that version.

--arch picks requirements.aarch64.lock; the record is one py3-none-any file for both architectures.

Does not demonstrate: that the wheels import or connect to anything, that `pip check` passes on the whole set
(prep WP3 runs it in the image build), or that a wheel is the file PyPI publishes (pip download --require-hashes
and PyPI's own digest say that; the run is in the Phase 4 notes).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
LOCKS = {"x86_64": HERE / "requirements.lock", "aarch64": HERE / "requirements.aarch64.lock"}
SDK_FILE = HERE / "sdk-requires.json"
PIN = re.compile(r"^([a-z0-9-]+)==(\S+) \\\n\s+--hash=sha256:([0-9a-f]{64})\n\s+# (\S+\.whl)$", re.M)
EXACT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)")
METADATA_FIELDS = ("name", "version", "requires_python", "requires_dist")

Pin = Tuple[str, str, str, str]          # name, version, sha256, wheel file


class LockError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lock_pins(path: Path) -> List[Pin]:
    """The lock's pins, each with its sha256 and the wheel its comment names; a pin without both is refused."""
    text = path.read_text(encoding="ascii")
    pins = PIN.findall(text)
    if len(pins) != len(re.findall(r"^[a-z0-9-]+==", text, re.M)):
        raise LockError("%s: a pin lacks its --hash line or its '# <file>.whl' comment" % path)
    if len({p[0] for p in pins}) != len(pins):
        raise LockError("%s pins a name twice" % path)
    return pins


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_metadata(path: Path) -> Dict[str, Any]:
    """The METADATA headers a wheel declares (the header block only: the description below it is free text)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.count("/") == 1 and n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise LockError("%s holds no dist-info/METADATA (or more than one)" % path.name)
        text = z.read(names[0]).decode("utf-8")
    headers: Dict[str, List[str]] = {}
    for line in text.replace("\r\n", "\n").split("\n\n", 1)[0].split("\n"):
        key, sep, value = line.partition(":")
        if sep and not line[:1].isspace():
            headers.setdefault(key.strip().lower(), []).append(value.strip())
    def one(key: str) -> Optional[str]:
        return headers[key][0] if headers.get(key) else None

    return {"name": one("name"), "version": one("version"), "requires_python": one("requires-python"),
            "requires_dist": headers.get("requires-dist", [])}


def pair_problems(pins: Sequence[Pin], sdk: Dict[str, Any]) -> List[str]:
    """Why the lock is not the SDK's own pair: the record's wheel pinned as it is, and every unconditional
    requirement of it one exact pin the lock holds."""
    by = {_norm(n): (v, h, w) for n, v, h, w in pins}
    who = "%s %s" % (sdk["name"], sdk["version"])
    problems: List[str] = []
    mine = by.get(_norm(sdk["name"]))
    if mine is None:
        problems.append("the lock has no pin for %s" % sdk["name"])
    elif mine != (sdk["version"], sdk["sha256"], sdk["wheel"]):
        problems.append("the lock pins %s %s as %s sha256 %s; the record is of %s sha256 %s"
                        % (sdk["name"], mine[0], mine[2], mine[1], sdk["wheel"], sdk["sha256"]))
    for req in sdk["requires_dist"]:
        if ";" in req:          # a marker: an extra, or a platform this image is not (the tests hold these to extras)
            continue
        m = EXACT.fullmatch(req.replace(" ", ""))
        if m is None:
            problems.append("%s declares %r, which is not one exact pin" % (who, req))
            continue
        got = by.get(_norm(m.group(1)))
        if got is None:
            problems.append("the lock has no pin for %s, which %s declares (%s)" % (m.group(1), who, req))
        elif got[0] != m.group(2):
            problems.append("the lock pins %s %s; %s declares %s" % (m.group(1), got[0], who, req))
    return problems


def check_wheels(lock: Path, wheels: Path, sdk: Dict[str, Any]) -> Dict[str, Any]:
    """A directory of downloaded wheels against a lock and the SDK record."""
    pins = lock_pins(lock)
    problems: List[str] = []
    wanted = {w: (n, h) for n, _v, h, w in pins}
    have = sorted(p.name for p in wheels.iterdir() if p.is_file())
    files = []
    for name in sorted(wanted):
        if name not in have:
            problems.append("%s is not in %s" % (name, wheels))
            continue
        got = sha256_file(wheels / name)
        files.append({"file": name, "sha256": got, "bytes": (wheels / name).stat().st_size})
        if got != wanted[name][1]:
            problems.append("%s hashes to %s, the lock says %s" % (name, got, wanted[name][1]))
    problems += ["%s is in %s and not in the lock" % (name, wheels) for name in have if name not in wanted]
    meta: Optional[Dict[str, Any]] = None
    if sdk["wheel"] in have:
        meta = wheel_metadata(wheels / sdk["wheel"])
        for field in METADATA_FIELDS:
            if meta[field] != sdk[field]:
                problems.append("%s declares %s %r, the record says %r" % (sdk["wheel"], field, meta[field], sdk[field]))
    problems += pair_problems(pins, sdk)
    return {"lock": lock.name, "pins": len(pins), "files": len(files), "wheels": files, "sdk_metadata": meta,
            "problems": problems, "ok": not problems}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for cmd in ("wheels", "pair"):
        s = sub.add_parser(cmd)
        if cmd == "wheels":
            s.add_argument("dir", help="the directory pip download filled for this lock")
        s.add_argument("--arch", choices=sorted(LOCKS), default="x86_64")
        s.add_argument("--lock", default=None, help="another lock file (default: this directory's, by --arch)")
        s.add_argument("--sdk", default=str(SDK_FILE), help="another SDK record (default: sdk-requires.json)")
    a = ap.parse_args(argv)
    lock = Path(a.lock) if a.lock else LOCKS[a.arch]
    try:
        sdk = json.loads(Path(a.sdk).read_text(encoding="utf-8"))
        if a.cmd == "pair":
            rec: Dict[str, Any] = {"lock": lock.name, "problems": pair_problems(lock_pins(lock), sdk)}
            rec["ok"] = not rec["problems"]
        else:
            rec = check_wheels(lock, Path(a.dir), sdk)
    except (LockError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print("lockcheck: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 1
    print(json.dumps(rec, indent=1, sort_keys=True))
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
