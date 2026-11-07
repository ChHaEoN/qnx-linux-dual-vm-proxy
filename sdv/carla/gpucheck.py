"""gpucheck.py -- D21's read before every CARLA 0.10.0 server start: nothing else on the GPU, and enough of it free (sdv/carla).

Phase 8 WP9b (D21): no other GPU workload while a 0.10.0 server runs, and the
configured free-memory floor below. Runs on Windows before each 0.10.0 server start, beside
fwcheck.py --carla 0.10.0; it reads, it never stops, starts or changes anything.

    usage: gpucheck.py

THE READ (main only; the parsing and the check are pure functions): one PowerShell command (PS_SCRIPT): nvidia-smi's
total, used and free memory of the GPU in MiB (--query-gpu, csv, no header, no units); Get-Process for the names Carla*
(a server of either version, its launcher included) and ollama* (a local model); Get-NetTCPConnection's listeners on
CARLA's ports 2000-2002 and the Traffic Manager's 8000 (PORTS); and, for the record only, the processes whose path names
a GPU program this check knows (OTHER_PATTERN). The output is one JSON document with every non-ASCII character escaped
as \\uXXXX, so it reads the same whatever the console's code page; output that is not ASCII is a failed read. Each read
a clause decides on stops on an error (-ErrorAction Stop), so a cmdlet that fails is a failed read, never "none": a
wildcard name with no match and the unfiltered listener read write no error. Only the record's read of the other
processes continues past one (SilentlyContinue: a process it cannot read is missing from the record, which decides
nothing). The record shows a path under a user profile from the profile on (%USERPROFILE%\\..., USER_PROFILE_RE): redacted
at capture time.

THE CHECK, every failure its own line: free-vram (free memory below FREE_MIB_MIN; at it passes), carla-process,
ollama-process, listener (on a port of PORTS).

OUTPUT "gpucheck: PASS (free <n> MiB, at least <FREE_MIB_MIN>)", or one "gpucheck: FAIL: <clause>: <what>" per failure;
then the record, in WP9a's d21.json form (utc, carla_processes, ollama_processes, listening_2000_2002_8000, gpu_mib,
min_free_mib, other_gpu_relevant_processes), as JSON. Exit 0 only on PASS, 1 on FAIL, 2 when the read itself failed (a
GPU read that is not one line of three numbers, or a listener whose port is not an integer, included) or this is not
Windows: fwcheck's exit codes.

DOES NOT SHOW: that a server started after it has the memory it reads (another program may take some meanwhile), that
FREE_MIB_MIN is enough for a run longer or heavier than WP9a's probes, or anything about the GPU's clocks or temperature;
that the PowerShell read gives what a stand-in gives (the tests answer it with documents of its shape); that the record
of the other processes is complete (its read continues past a process it cannot read); that every user name in a path
is redacted (only the profile directory's own, at the start of a path).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# The owner's free-VRAM floor for a 0.10.0 server start, in MiB; a refusal threshold, written in one place.
# It reserves headroom for the interface, NPCs and longer drives; it is no memory-use or capacity result.
FREE_MIB_MIN = 9500
PORTS = (2000, 2001, 2002, 8000)            # CARLA's server (2000-2002) and a Traffic Manager (8000)
PROCESS_PATTERNS = ("Carla*", "ollama*")
OTHER_PATTERN = r"Google\\Play Games|CarlaUE4|CarlaUnreal|ollama|rviz|python"     # for the record only (WP9a's d21.json)
CLAUSES = ("free-vram", "carla-process", "ollama-process", "listener")
# A path under a user profile directory (drive, Users, the profile's name): the record shows %USERPROFILE% in its place.
USER_PROFILE_RE = re.compile(r"(?i)^[a-z]:\\users\\[^\\]+")

PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$gpu = @(& nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv,noheader,nounits)
if ($LASTEXITCODE -ne 0) { throw "nvidia-smi exited $LASTEXITCODE" }
$carla = @(Get-Process -Name 'Carla*' -ErrorAction Stop | ForEach-Object { [ordered]@{ Name = [string]$_.Name; Id = [int]$_.Id } })
$ollama = @(Get-Process -Name 'ollama*' -ErrorAction Stop | ForEach-Object { [ordered]@{ Name = [string]$_.Name; Id = [int]$_.Id } })
$listen = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -in %(ports)s } |
  ForEach-Object { [ordered]@{ LocalAddress = [string]$_.LocalAddress; LocalPort = [int]$_.LocalPort; OwningProcess = [int]$_.OwningProcess } })
$others = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ($_.Path -match '%(other)s') } |
  ForEach-Object { [ordered]@{ Name = [string]$_.Name; Id = [int]$_.Id; Path = [string]$_.Path } })
$doc = [ordered]@{ utc = (Get-Date).ToUniversalTime().ToString('o'); gpu = @($gpu | ForEach-Object { [string]$_ });
  carla = $carla; ollama = $ollama; listen = $listen; others = $others }
$json = ConvertTo-Json -Depth 4 -Compress -InputObject $doc
[regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
""" % {"ports": ", ".join(str(p) for p in PORTS), "other": OTHER_PATTERN}


@dataclass(frozen=True)
class Reading:
    utc: str
    total_mib: int
    used_mib: int
    free_mib: int
    carla: Tuple[str, ...]              # "Name(pid)"
    ollama: Tuple[str, ...]
    listeners: Tuple[str, ...]          # "address:port pid N", the ports of PORTS only
    others: Tuple[str, ...]             # "Name(pid) path", a user profile's path shown from the profile on (shown_path)


def _items(x: Any) -> List[Dict[str, Any]]:
    """A PowerShell list as a list (ConvertTo-Json may give one object, or null, for a list of one or none)."""
    if x is None:
        return []
    if isinstance(x, dict):
        return [x]
    if isinstance(x, list) and all(isinstance(v, dict) for v in x):
        return x
    raise ValueError("a list of objects is expected, got %r" % (x,))


def shown_path(path: Any) -> str:
    """A process's path as the record shows it: under a user profile, %USERPROFILE% in place of the drive, Users and the
    profile's name (redacted at capture time); any other path as it is."""
    return USER_PROFILE_RE.sub("%USERPROFILE%", str(path), count=1)


def parse(doc: Dict[str, Any]) -> Reading:
    """The PowerShell read's JSON document as a Reading; ValueError when the GPU read is not one line of three integers or a
    listener's port is not an integer (a listener dropped for its form would read as none)."""
    if not isinstance(doc, dict) or "gpu" not in doc:
        raise ValueError("the read holds no GPU memory line")
    gpu = doc["gpu"]
    lines = [gpu] if isinstance(gpu, str) else list(gpu or [])
    if len(lines) != 1:
        raise ValueError("nvidia-smi gave %d memory lines, not one (one GPU)" % len(lines))
    fields = [f.strip() for f in str(lines[0]).split(",")]
    if len(fields) != 3 or not all(f.isdigit() for f in fields):
        raise ValueError("nvidia-smi's memory line %r is not total, used, free in MiB" % (lines[0],))
    total, used, free = (int(f) for f in fields)
    procs = {k: tuple("%s(%s)" % (p.get("Name"), p.get("Id")) for p in _items(doc.get(k))) for k in ("carla", "ollama")}
    heard = _items(doc.get("listen"))
    for x in heard:                                 # the read casts the port with [int]: any other form is not its output
        port = x.get("LocalPort")
        if not isinstance(port, int) or isinstance(port, bool):
            raise ValueError("a listener's LocalPort %r is not an integer" % (port,))
    listen = tuple("%s:%s pid %s" % (x.get("LocalAddress"), x.get("LocalPort"), x.get("OwningProcess"))
                   for x in heard if x.get("LocalPort") in PORTS)
    others = tuple("%s(%s) %s" % (p.get("Name"), p.get("Id"), shown_path(p.get("Path"))) for p in _items(doc.get("others")))
    return Reading(str(doc.get("utc") or ""), total, used, free, procs["carla"], procs["ollama"], listen, others)


def check(r: Reading) -> List[Tuple[str, str]]:
    """Every failing (clause, what), in CLAUSES order."""
    out: List[Tuple[str, str]] = []
    if r.free_mib < FREE_MIB_MIN:
        out.append(("free-vram", "%d MiB free, below %d" % (r.free_mib, FREE_MIB_MIN)))
    out += [("carla-process", p) for p in r.carla]
    out += [("ollama-process", p) for p in r.ollama]
    out += [("listener", x) for x in r.listeners]
    return out


def result_lines(failures: Sequence[Tuple[str, str]], r: Reading) -> List[str]:
    if not failures:
        return ["gpucheck: PASS (free %d MiB, at least %d)" % (r.free_mib, FREE_MIB_MIN)]
    return ["gpucheck: FAIL: %s: %s" % (clause, what) for clause, what in failures]


def record(r: Reading) -> Dict[str, Any]:
    """The reading in WP9a's d21.json form."""
    return {"utc": r.utc, "carla_processes": list(r.carla), "ollama_processes": list(r.ollama),
            "listening_2000_2002_8000": list(r.listeners), "gpu_mib": {"total": r.total_mib, "used": r.used_mib, "free": r.free_mib},
            "min_free_mib": FREE_MIB_MIN, "other_gpu_relevant_processes": list(r.others)}


Runner = Callable[[List[str]], Tuple[int, str, str]]


def _powershell(cmd: List[str]) -> Tuple[int, str, str]:
    """The command's exit code, stdout and stderr; stdout that is not ASCII is a failed read (exit code -1)."""
    p = subprocess.run(cmd, capture_output=True, timeout=120)
    err = (p.stderr or b"").decode("utf-8", "replace")
    try:
        out = (p.stdout or b"").decode("ascii")
    except UnicodeDecodeError as e:
        return -1, "", "the read's output is not ASCII (%s); %s" % (e, err)
    return p.returncode, out, err


def command() -> List[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT]


def run(runner: Optional[Runner] = None) -> Tuple[int, List[str], Optional[Dict[str, Any]]]:
    """(exit code, output lines, the record or None) of one check: 0 PASS, 1 FAIL, 2 when the read failed."""
    rc, out, err = (runner or _powershell)(command())
    if rc != 0:
        return 2, ["gpucheck: the read failed (%d): %s" % (rc, (err or "").strip()[-400:])], None
    try:
        r = parse(json.loads(out))
    except (ValueError, TypeError, AttributeError) as e:
        return 2, ["gpucheck: the read is not the expected JSON: %s" % e], None
    lines = result_lines(check(r), r)
    return (0 if lines[0].startswith("gpucheck: PASS") else 1), lines, record(r)


def main(argv: Optional[Sequence[str]] = None, runner: Optional[Runner] = None, windows: Optional[bool] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.parse_args(argv)
    if not (os.name == "nt" if windows is None else windows):
        print("gpucheck: reads nvidia-smi and the processes on Windows, so it runs on Windows only", file=sys.stderr)
        return 2
    rc, lines, rec = run(runner)
    stream = sys.stderr if rc == 2 else sys.stdout
    for line in lines:
        print(line, file=stream)
    if rec is not None:
        print(json.dumps(rec, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
