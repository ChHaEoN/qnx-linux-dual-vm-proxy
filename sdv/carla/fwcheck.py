"""fwcheck.py -- the firewall predicate that gates every CARLA server start (sdv/carla), Phase 7 spec 2.5.

CARLA's server listens on every interface (0.0.0.0, ports 2000-2002) and has no bind
option, and a Traffic Manager listens on 0.0.0.0:8000 inside the client that starts one, so the Windows firewall is what
keeps the LAN out. The owner sets the rules by hand (plan decision D2); this module only reads them and says whether
they are what the phase needs. It never writes a rule or a setting.

    usage: fwcheck.py --for windows-client|wsl [--no-tm] [--carla 0.9.16|0.10.0]     (also: carla_capture.py fwcheck --for ...,
                                                                                    follow010.py fwcheck --for ...)

THE CARLA VERSION (--carla; Phase 8 spec-2 10.2, D17, D23): which server's exe the predicate judges and whose client venv's
interpreters P4 reads, CARLA_TARGETS[--carla]. The default, 0.9.16, is Phase 7's: EXE_PATH, EXE_NAME and VENV below,
the behaviour and the output line as before the choice existed. 0.10.0 names 0.10.0's server exe, its file name and its
client venv E:\\CARLA\\venv312-010, and
its output lines say "CARLA 0.10.0" after the <for>. The read itself is the same for both.

THE READ (main only; the parsing and the predicate are pure functions): one PowerShell command, every firewall cmdlet
with -PolicyStore ActiveStore (without it they read the PersistentStore only, so a rule a policy adds would be missed):
Get-NetFirewallProfile; Get-NetFirewallRule for the inbound rules, and each rule's application, service, port, address
and interface filters read through the pipeline, rule by rule (a non-elevated shell is denied the port, address and
interface filters in bulk, not per rule: WP0's read), joined to the rule by InstanceID; each rule's Owner and its
application filter's Package; a program's path with its environment variables expanded; and Get-NetIPAddress of the
IPv4 addresses whose interface alias begins WSL_ALIAS_PREFIX. The output is one JSON document with every non-ASCII
character escaped as \\uXXXX, so it reads the same whatever the console's code page; output that is not ASCII is a failed
read. main also reads the client's interpreters (P4): the base python.exe of VENV's pyvenv.cfg (its home line) and the
venv's own.

THE PREDICATE
  P1  every firewall profile is enabled, and its default inbound action is Block or NotConfigured.
  P2  every enabled inbound allow rule (Allow, or an allow bypass: an allow rule with OverrideBlockRules) that P2 judges
      is TCP, with every local port inside 2000-2002, and scoped to the WSL adapter: every interface alias begins
      WSL_ALIAS_PREFIX, or every remote address lies inside an IPv4 subnet of an up WSL adapter. P2 judges a rule that
      (a) names the CARLA exe (its path in any letter case, or a program of the exe's file name at any path: a copy
      elsewhere is the same server, and a rule for it may be meant for this one); or (b) is unbound -- it names no
      program, no service, no package and no Owner SID (a Store app's network-isolation rule admits only its own
      container) -- and its local ports meet 2000-2002 ("Any" meets them; the protocol is one that carries ports, or
      Any); or (c) names another program and gives a local port or range overlapping 2000-2002 by number (spec section
      11's case). (a) and (c) widen spec 2.5's judged set and can only add a FAIL: P3 counts only 2.5's own P2 rules
      (the exe by its path, or an unbound rule). Block rules and disabled rules pass. With no WSL adapter up, an
      address-scoped rule fails, since its subnet cannot be read.
  P4  (unless --no-tm) every enabled inbound allow rule that names one of the client's interpreters (its path in any
      letter case), or that is unbound and whose local ports meet 8000 ("Any" meets it; a widening of spec 2.5 that can
      only add a FAIL: such a rule admits the interpreter too), is TCP, with every local port 8000 (the Traffic
      Manager's port), and scoped to the WSL adapter as P2 requires. --no-tm is for a client that starts no Traffic
      Manager, and the output line says P4 was not applied.
  P3  (--for wsl only) at least one of 2.5's own P2 rules (the exe by its path, or an unbound rule) passes P2, and no
      enabled block rule for the exe applies to the WSL adapter: an explicit block wins over an explicit allow
      (Microsoft's rule order); a rule P2 judges through (a)'s other path or (c) is not one. The adapter's own profile
      is not read (no cmdlet above reads it), so a block rule for the exe counts on every profile unless its interface
      aliases leave the WSL adapter out. An allow bypass is not a block rule.
  read  an enabled inbound allow rule whose filters could not be read (an empty program, protocol, port, address or
        interface list) fails: nothing is judged as passing that was not read. A rule whose service filter was not read
        counts as naming no service, and one with no Owner or Package read as having none: both put it among the
        rules P2 judges, never out of them.

OUTPUT one line, "fwcheck: PASS (<for>)" (with --no-tm, "fwcheck: PASS (<for>, no TM: P4 not applied)"), or one
"fwcheck: FAIL (<for>): <clause>: <rule display name>" per failing rule (P1 names the profile); exit 0 only on PASS, 1 on
FAIL, 2 when the read itself failed (the interpreters' included) or this is not Windows.

DOES NOT SHOW: that the rules work (it reads them; it sends no packet); anything about the Hyper-V firewall that sits
between WSL and the host; an allow rule for another program with local ports Any (it admits only that program, and
judging it would fail every PC); that the PowerShell read gives what a stand-in gives (the tests answer it with
fixtures; it has not been run against a real firewall by them).
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

EXE_PATH = r"E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe"
EXE_NAME = "CarlaUE4-Win64-Shipping.exe"
VENV = r"E:\CARLA\venv312"
PORT_LO, PORT_HI = 2000, 2002
TM_PORT = 8000
WSL_ALIAS_PREFIX = "vEthernet (WSL"
FOR_CHOICES = ("windows-client", "wsl")
CARLA_DEFAULT = "0.9.16"
# --carla: (the server's exe, its file name, the client's venv) per CARLA version; 0.9.16's are the three above.
CARLA_TARGETS: Dict[str, Tuple[str, str, str]] = {
    "0.9.16": (EXE_PATH, EXE_NAME, VENV),
    "0.10.0": (r"E:\CARLA\Carla-0.10.0-Win64-Shipping\CarlaUnreal\Binaries\Win64\CarlaUnreal-Win64-Shipping.exe",
               "CarlaUnreal-Win64-Shipping.exe", r"E:\CARLA\venv312-010"),
}
CARLA_CHOICES = tuple(CARLA_TARGETS)
ALLOW_ACTIONS = ("allow", "allowbypass", "2", "3")
BLOCK_ACTIONS = ("block", "4")
PORT_PROTOCOLS = ("tcp", "udp", "6", "17", "any")
NO_P2_RULE = "(no WSL-scoped allow rule)"

PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$st = 'ActiveStore'
function S($x) { if ($null -eq $x) { ,@() } else { ,@($x | ForEach-Object { [string]$_ }) } }
function X($x) { if ($null -eq $x) { ,@() } else { ,@($x | ForEach-Object { [Environment]::ExpandEnvironmentVariables([string]$_) }) } }
function IX($xs) { $h = @{}; foreach ($x in $xs) { $h[[string]$x.InstanceID] = $x }; $h }
$inbound = @(Get-NetFirewallRule -PolicyStore $st -Direction Inbound)
$app = IX ($inbound | Get-NetFirewallApplicationFilter -PolicyStore $st)
$svc = IX ($inbound | Get-NetFirewallServiceFilter -PolicyStore $st)
$port = IX ($inbound | Get-NetFirewallPortFilter -PolicyStore $st)
$addr = IX ($inbound | Get-NetFirewallAddressFilter -PolicyStore $st)
$ifc = IX ($inbound | Get-NetFirewallInterfaceFilter -PolicyStore $st)
$profiles = @(Get-NetFirewallProfile -PolicyStore $st | ForEach-Object {
  [ordered]@{ Name = [string]$_.Name; Enabled = [string]$_.Enabled; DefaultInboundAction = [string]$_.DefaultInboundAction } })
$rules = @($inbound | ForEach-Object {
  $k = [string]$_.InstanceID
  $p = $port[$k]
  $a = $app[$k]
  [ordered]@{ Name = [string]$_.Name; DisplayName = [string]$_.DisplayName; Enabled = [string]$_.Enabled;
    Direction = [string]$_.Direction; Action = [string]$_.Action; Profile = [string]$_.Profile; Owner = [string]$_.Owner;
    Program = (X $a.Program); Package = $(if ($null -eq $a) { '' } else { [string]$a.Package }); Service = (S $svc[$k].Service);
    Protocol = $(if ($null -eq $p) { '' } else { [string]$p.Protocol });
    LocalPort = (S $p.LocalPort); RemoteAddress = (S $addr[$k].RemoteAddress); InterfaceAlias = (S $ifc[$k].InterfaceAlias) } })
$wsl = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.InterfaceAlias -like 'vEthernet (WSL*' } | ForEach-Object {
  [ordered]@{ InterfaceAlias = [string]$_.InterfaceAlias; IPAddress = [string]$_.IPAddress; PrefixLength = [int]$_.PrefixLength } })
$json = ConvertTo-Json -Depth 6 -Compress -InputObject ([ordered]@{ profiles = $profiles; rules = $rules; wsl = $wsl })
[regex]::Replace($json, '[^\x00-\x7F]', { param($m) '\u{0:x4}' -f [int][char]$m.Value })
"""


@dataclass(frozen=True)
class Profile:
    name: str
    enabled: str
    default_inbound: str


@dataclass(frozen=True)
class Rule:
    display: str
    enabled: bool
    inbound: bool
    action: str
    programs: Tuple[str, ...]
    protocol: str
    local_ports: Tuple[str, ...]
    remote: Tuple[str, ...]
    aliases: Tuple[str, ...]
    services: Tuple[str, ...] = ()
    package: str = ""
    owner: str = ""

    @property
    def allow(self) -> bool:
        return self.action.lower() in ALLOW_ACTIONS

    @property
    def block(self) -> bool:
        return self.action.lower() in BLOCK_ACTIONS


@dataclass(frozen=True)
class Snapshot:
    profiles: Tuple[Profile, ...]
    rules: Tuple[Rule, ...]
    wsl_nets: Tuple[Any, ...]          # ipaddress.IPv4Network of every up WSL adapter


def _truth(x: Any) -> bool:
    return x is True or str(x).strip().lower() in ("true", "1")


def _list(x: Any) -> Tuple[str, ...]:
    if x is None:
        return ()
    if isinstance(x, (list, tuple)):
        return tuple(str(v) for v in x if v is not None and str(v) != "")
    return (str(x),) if str(x) != "" else ()


def parse(doc: Dict[str, Any]) -> Snapshot:
    """The PowerShell read's JSON document as a Snapshot."""
    profiles = tuple(Profile(str(p.get("Name")), str(p.get("Enabled")), str(p.get("DefaultInboundAction")))
                     for p in doc.get("profiles") or ())
    rules = tuple(Rule(display=str(r.get("DisplayName") or r.get("Name")), enabled=_truth(r.get("Enabled")),
                       inbound=str(r.get("Direction")).lower() in ("inbound", "1"), action=str(r.get("Action") or ""),
                       programs=_list(r.get("Program")), protocol=str(r.get("Protocol") or ""),
                       local_ports=_list(r.get("LocalPort")), remote=_list(r.get("RemoteAddress")),
                       aliases=_list(r.get("InterfaceAlias")), services=_list(r.get("Service")),
                       package=str(r.get("Package") or ""), owner=str(r.get("Owner") or ""))
                  for r in doc.get("rules") or ())
    nets = []
    for a in doc.get("wsl") or ():
        if str(a.get("InterfaceAlias", "")).startswith(WSL_ALIAS_PREFIX):
            nets.append(ipaddress.ip_network("%s/%d" % (a["IPAddress"], int(a["PrefixLength"])), strict=False))
    return Snapshot(profiles, rules, tuple(nets))


def _path_key(program: str) -> str:
    return program.replace("/", "\\").strip().lower()


def names_exe(program: str, carla: str = CARLA_DEFAULT) -> bool:
    exe_path, exe_name, _venv = CARLA_TARGETS[carla]
    p = _path_key(program)
    return p == exe_path.lower() or p.rsplit("\\", 1)[-1] == exe_name.lower()


def names_interpreter(program: str, interpreters: Sequence[str]) -> bool:
    p = _path_key(program)
    return any(p == _path_key(x) for x in interpreters)


def _is_any(x: str) -> bool:
    return x.strip().lower() in ("any", "*", "")


def names_program(rule: Rule) -> bool:
    return any(not _is_any(p) for p in rule.programs)


def unbound(rule: Rule) -> bool:
    """No program, no service, no package and no Owner SID: the rule admits any program's traffic."""
    return (not names_program(rule) and all(_is_any(s) for s in rule.services) and _is_any(rule.package)
            and not rule.owner.strip())


def _port_range(entry: str) -> Optional[Tuple[int, int]]:
    """A port number or range given in a rule, or None for a keyword (Any, RPC, ...)."""
    e = entry.strip()
    lo, sep, hi = e.partition("-")
    if lo.isdigit() and (not sep or hi.isdigit()):
        return int(lo), int(hi if sep else lo)
    return None


def ports_meet(entries: Sequence[str], lo: int = PORT_LO, hi: int = PORT_HI) -> bool:
    """A port number or range given in the rule overlaps lo-hi (a keyword is not a port given)."""
    for e in entries:
        r = _port_range(e)
        if r is not None and r[0] <= hi and r[1] >= lo:
            return True
    return False


def ports_meet_any(rule: Rule) -> bool:
    """The rule's local ports meet 2000-2002 with "Any" meeting them, for a protocol that carries ports (or Any)."""
    if rule.protocol.strip().lower() not in PORT_PROTOCOLS:
        return False
    return any(e.strip().lower() == "any" for e in rule.local_ports) or ports_meet(rule.local_ports)


def ports_inside(entries: Sequence[str], lo: int = PORT_LO, hi: int = PORT_HI) -> bool:
    if not entries:
        return False
    for e in entries:
        r = _port_range(e)
        if r is None or r[0] < lo or r[1] > hi or r[0] > r[1]:
            return False
    return True


def _address_inside(entry: str, nets: Sequence[Any]) -> bool:
    """A remote address entry (an address, a prefix, an address/mask or a range a-b) inside one WSL subnet."""
    e = entry.strip()
    try:
        if "-" in e:
            lo_s, hi_s = e.split("-", 1)
            lo, hi = ipaddress.ip_address(lo_s.strip()), ipaddress.ip_address(hi_s.strip())
            return any(lo in n and hi in n for n in nets)
        if "/" in e:
            net = ipaddress.ip_network(e, strict=False)
            return any(net.version == n.version and net.subnet_of(n) for n in nets)
        addr = ipaddress.ip_address(e)
    except ValueError:
        return False                     # a keyword (Any, LocalSubnet, ...) is not inside a subnet
    return any(addr in n for n in nets)


def scoped_to_wsl(rule: Rule, nets: Sequence[Any]) -> bool:
    if rule.aliases and all(a.startswith(WSL_ALIAS_PREFIX) for a in rule.aliases):
        return True
    return bool(nets) and bool(rule.remote) and all(_address_inside(e, nets) for e in rule.remote)


def _allow_in(rule: Rule) -> bool:
    return rule.enabled and rule.inbound and rule.allow


def judged_by_p2(rule: Rule, carla: str = CARLA_DEFAULT) -> bool:
    """An enabled inbound allow rule of the module docstring's (a), (b) or (c)."""
    if not _allow_in(rule):
        return False
    if any(names_exe(p, carla) for p in rule.programs):
        return True
    if unbound(rule):
        return ports_meet_any(rule)
    return names_program(rule) and ports_meet(rule.local_ports)


def judged_by_p4(rule: Rule, interpreters: Sequence[str]) -> bool:
    """An enabled inbound allow rule that names one of the client's interpreters, or an unbound one whose local ports meet
    the Traffic Manager's port ("Any" meeting it, for a protocol that carries ports)."""
    if not _allow_in(rule):
        return False
    if any(names_interpreter(p, interpreters) for p in rule.programs):
        return True
    return (unbound(rule) and rule.protocol.strip().lower() in PORT_PROTOCOLS
            and (any(e.strip().lower() == "any" for e in rule.local_ports) or ports_meet(rule.local_ports, TM_PORT, TM_PORT)))


def unread(rule: Rule) -> bool:
    return _allow_in(rule) and not (rule.programs and rule.protocol and rule.local_ports and rule.remote and rule.aliases)


def _tcp(rule: Rule) -> bool:
    return rule.protocol.strip().upper() in ("TCP", "6")


def passes_p2(rule: Rule, nets: Sequence[Any]) -> bool:
    return _tcp(rule) and ports_inside(rule.local_ports) and scoped_to_wsl(rule, nets)


def passes_p4(rule: Rule, nets: Sequence[Any]) -> bool:
    return _tcp(rule) and ports_inside(rule.local_ports, TM_PORT, TM_PORT) and scoped_to_wsl(rule, nets)


def check(snap: Snapshot, for_: str, interpreters: Sequence[str] = (), tm: bool = True,
          carla: str = CARLA_DEFAULT) -> List[Tuple[str, str]]:
    """Every failing (clause, name), in order: profiles (P1), then rules in the read's order (read, P2, P4), then P3.
    P4 is applied when tm is true (a client that runs a Traffic Manager). carla names the server whose exe is judged."""
    if for_ not in FOR_CHOICES:
        raise ValueError("--for is one of %s" % ", ".join(FOR_CHOICES))
    exe_path = CARLA_TARGETS[carla][0]
    out: List[Tuple[str, str]] = []
    if not snap.profiles:
        out.append(("P1", "(no firewall profile read)"))
    for p in snap.profiles:
        if p.enabled.strip().lower() != "true" or p.default_inbound.strip().lower() not in ("block", "notconfigured"):
            out.append(("P1", p.name))
    p2_rules = 0
    for r in snap.rules:
        if unread(r):
            out.append(("read", r.display))
            continue
        if judged_by_p2(r, carla):
            if passes_p2(r, snap.wsl_nets):
                if any(_path_key(p) == exe_path.lower() for p in r.programs) or unbound(r):
                    p2_rules += 1
            else:
                out.append(("P2", r.display))
        if tm and judged_by_p4(r, interpreters) and not passes_p4(r, snap.wsl_nets):
            out.append(("P4", r.display))
    if for_ == "wsl":
        if p2_rules == 0:
            out.append(("P3", NO_P2_RULE))
        for r in snap.rules:
            if (r.enabled and r.inbound and r.block and any(names_exe(p, carla) for p in r.programs)
                    and (not r.aliases or "any" in (a.lower() for a in r.aliases)
                         or any(a.startswith(WSL_ALIAS_PREFIX) for a in r.aliases))):
                out.append(("P3", r.display))
    return out


def result_lines(failures: Sequence[Tuple[str, str]], for_: str, tm: bool = True, carla: str = CARLA_DEFAULT) -> List[str]:
    tag = for_ if carla == CARLA_DEFAULT else "%s, CARLA %s" % (for_, carla)
    tag = tag if tm else "%s, no TM: P4 not applied" % tag
    if not failures:
        return ["fwcheck: PASS (%s)" % tag]
    return ["fwcheck: FAIL (%s): %s: %s" % (tag, clause, name) for clause, name in failures]


def interpreters_of(pyvenv_cfg: str, venv: str = VENV) -> Tuple[str, ...]:
    """The client's interpreters: the base python.exe of a venv's pyvenv.cfg (its home line) and the venv's own."""
    home = None
    for line in pyvenv_cfg.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "home":
            home = value.strip()
            break
    if not home:
        raise ValueError("pyvenv.cfg has no home line")
    return (str(PureWindowsPath(home) / "python.exe"), str(PureWindowsPath(venv) / "Scripts" / "python.exe"))


def read_interpreters(venv: str = VENV) -> Tuple[str, ...]:
    with open(str(PureWindowsPath(venv) / "pyvenv.cfg"), encoding="utf-8") as f:
        return interpreters_of(f.read(), venv)


Runner = Callable[[List[str]], Tuple[int, str, str]]


def _powershell(cmd: List[str]) -> Tuple[int, str, str]:
    """The command's exit code, stdout and stderr. The read escapes every non-ASCII character as \\uXXXX, so stdout is ASCII
    whatever the console's code page (a rule name in the code page's own letters once stopped the read); stdout that is not
    ASCII is a failed read (exit code -1), never decoded by a guess."""
    p = subprocess.run(cmd, capture_output=True, timeout=300)
    err = (p.stderr or b"").decode("utf-8", "replace")
    try:
        out = (p.stdout or b"").decode("ascii")
    except UnicodeDecodeError as e:
        return -1, "", "the read's output is not ASCII (%s); %s" % (e, err)
    return p.returncode, out, err


def command() -> List[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT]


def run(for_: str, runner: Optional[Runner] = None, tm: bool = True,
        interpreters: Optional[Callable[[], Sequence[str]]] = None, carla: str = CARLA_DEFAULT) -> Tuple[int, List[str]]:
    """(exit code, output lines) of one check: 0 PASS, 1 FAIL, 2 when the read failed. carla names the server (--carla)."""
    venv = CARLA_TARGETS[carla][2]
    names: Sequence[str] = ()
    if tm:
        try:
            names = tuple((interpreters or (lambda: read_interpreters(venv)))())
        except (OSError, ValueError) as e:
            return 2, ["fwcheck: the client's interpreters could not be read (P4): %s" % e]
        if not names:
            return 2, ["fwcheck: no interpreter of the client was read (P4)"]
    rc, out, err = (runner or _powershell)(command())
    if rc != 0:
        return 2, ["fwcheck: the firewall read failed (%d): %s" % (rc, (err or "").strip()[-400:])]
    try:
        snap = parse(json.loads(out))
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        return 2, ["fwcheck: the firewall read is not the expected JSON: %s" % e]
    lines = result_lines(check(snap, for_, names, tm, carla), for_, tm, carla)
    return (0 if lines[0].startswith("fwcheck: PASS") else 1), lines


def main(argv: Optional[Sequence[str]] = None, runner: Optional[Runner] = None, windows: Optional[bool] = None,
         interpreters: Optional[Callable[[], Sequence[str]]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--for", dest="for_", required=True, choices=FOR_CHOICES)
    ap.add_argument("--no-tm", action="store_true", help="P4 not applied: for a client that runs no Traffic Manager")
    ap.add_argument("--carla", choices=CARLA_CHOICES, default=CARLA_DEFAULT, help="the CARLA server whose exe is judged")
    a = ap.parse_args(argv)
    if not (os.name == "nt" if windows is None else windows):
        print("fwcheck: reads the Windows firewall, so it runs on Windows only", file=sys.stderr)
        return 2
    rc, lines = run(a.for_, runner, not a.no_tm, interpreters, a.carla)
    stream = sys.stderr if rc == 2 else sys.stdout
    for line in lines:
        print(line, file=stream)
    return rc


if __name__ == "__main__":
    sys.exit(main())
