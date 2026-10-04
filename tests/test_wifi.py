"""The Wi-Fi test (Phase 3b / A6, 2026-09-29): the pieces of the rule run-wifi.sh fixed before any
run, the report end to end on synthetic rounds, and the harness's header. Every number here is
synthetic."""
import json
import os
import random
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
GC = os.path.join(HERE, "..", "orin-native", "gpu-concurrency")
sys.path.insert(0, GC)
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "ci"))
import irqconf_report as ir  # noqa: E402
import results_guard as rg  # noqa: E402
import wifi_report as wr  # noqa: E402

REPORT = os.path.join(GC, "wifi_report.py")
HARNESS = os.path.join(GC, "run-wifi.sh")
BASH = shutil.which("bash")


def test_the_switch_check_reads_both_states():
    s = {(1, "off"): [("yes", "unavailable"), ("yes", "unavailable")],
         (1, "on"): [("no", "connected"), ("no", "connected")],
         (2, "off"): [("yes", "unavailable"), ("no", "connected")],
         (2, "on"): [("no", "connecting"), ("no", "connected")]}
    assert wr.switch_ok(s, 1, "off") and wr.switch_ok(s, 1, "on")
    assert not wr.switch_ok(s, 2, "off") and not wr.switch_ok(s, 2, "on")
    assert not wr.switch_ok(s, 3, "on")


def _run(out, k, wifi_cost=80.0, bad_state=False, radio_stuck=False, n=1000, warm=200, seed=13):
    """Requests every 2250 us from 137 us past the host grid; guest timer events one in every
    2000 us. With the radio on, the Wi-Fi's interrupt about every 20 ms on core 0; an exchange
    with one in [t0 - 500, t0 + rtt] adds `wifi_cost` us with probability 0.6. With the radio
    off none (or, with radio_stuck, the same as on). 1 in 300 exchanges +50 us."""
    out.mkdir(parents=True)
    rng = random.Random(seed)
    clog, order, wstate = [], [], []
    for r in range(1, k + 1):
        for w in ("before", "after"):
            want = "0-5" if (bad_state and r == 2) else "3,5"
            clog.append("round %d %s udevd=%s pid1=%s gnome-shell=%s qemu=0-2" % (r, w, want, want, want))
        arms = ("on", "off") if r % 2 else ("off", "on")
        order.append("round %d order: %s" % (r, " ".join(arms)))
        for j, arm in enumerate(arms):
            tag = "%s_r%d" % (arm, r)
            base = 1e9 + r * 1e7 + j * 4e6
            span = (warm + n) * 2250.0
            gev = [g * 2000.0 + 1000.0 * rng.random() for g in range(int(span / 2000.0) + 2)]
            live = arm == "on" or radio_stuck
            wifi = sorted(rng.uniform(0, span) for _ in range(int(span / 20000.0))) if live else []
            lines, samples = [], []
            for i in range(warm + n):
                t0 = 137.0 + i * 2250.0
                lines.append("%.6f 004 X 130" % ((base + t0) / 1e6))
                if i < warm:
                    continue
                v = 180.0 + 8.0 * rng.random()
                if wifi and ir.device_near(t0, v, wifi) and rng.random() < 0.6:
                    v += wifi_cost
                elif rng.random() < 1.0 / 300:
                    v += 50.0
                samples.append(v / 1000.0)
            tk = ["%.6f 001 I kvm" % ((base + g) / 1e6) for g in gev[::2]]
            tk += ["%.6f 002 H kvm_bg_timer_expire" % ((base + g) / 1e6) for g in gev[1::2]]
            tk += ["%.6f 000 I IPI" % ((base + g + 7.0) / 1e6) for g in gev]
            tk += ["%.6f 000 I rtl88x2ce" % ((base + d) / 1e6) for d in wifi]
            (out / ("tk-%s.log" % tag)).write_text("\n".join(sorted(tk, key=lambda x: float(x.split()[0]))) + "\n")
            (out / ("tp-%s.log" % tag)).write_text("\n".join(lines) + "\n")
            (out / ("lat-%s.json" % tag)).write_text(json.dumps({"summary": {}, "samples_in_order": samples}))
            (out / ("wifi-%s.before" % tag)).write_text("277: 5000 0 0 0 0 0\n")
            (out / ("wifi-%s.after" % tag)).write_text("277: %d 0 0 0 0 0\n" % (5000 + len(wifi)))
            soft, nm = ("no", "connected") if arm == "on" else ("yes", "unavailable")
            for w in ("before", "after"):
                wstate.append("round %d %s %s rfkill_soft=%s nm=%s" % (r, arm, w, soft, nm))
    (out / "confine.log").write_text("\n".join(clog) + "\n")
    (out / "order.log").write_text("\n".join(order) + "\n")
    (out / "wifi-state.log").write_text("\n".join(wstate) + "\n")
    (out / "logins.txt").write_text("accepted=0\n")
    (out / "stamp.json").write_text(json.dumps({"pin": {"qemu": "0-2", "probe": 4},
                                                "wifi": {"interface": "wlan0", "driver": "rtl88x2ce", "irq": 277}}))


def _report(out):
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _line(s, tag):
    return s.split("  " + tag)[1].split("\n")[0]


def test_a_wifi_that_costs_the_tail_holds_everything(tmp_path):
    _run(tmp_path / "o", 40)
    s = _report(tmp_path / "o")
    for m in ("M1", "M2", "M3", "M4", "M5"):
        assert "FAILED" not in _line(s, m), s
    for p in ("P1", "P2", "P3", "P4"):
        assert "-> HELD" in _line(s, p), s


def test_a_harmless_wifi_refutes_the_mechanism(tmp_path):
    _run(tmp_path / "a", 40, wifi_cost=0.0)
    s = _report(tmp_path / "a")
    assert "-> REFUTED" in _line(s, "P4") and "-> HELD" in _line(s, "P3"), s
    assert "-> HELD" not in _line(s, "P1"), s


def test_failed_checks_void(tmp_path):
    _run(tmp_path / "a", 40, bad_state=True)
    s = _report(tmp_path / "a")
    assert "-> FAILED" in _line(s, "M2") and "VOID (M2 failed)" in _line(s, "P1"), s
    _run(tmp_path / "b", 40, radio_stuck=True)
    s = _report(tmp_path / "b")
    assert "-> FAILED" in _line(s, "M4") and "VOID (M4 failed)" in _line(s, "P2"), s
    _run(tmp_path / "c", 4)
    assert "not scored (k=4; the prediction is for k=40)" in _report(tmp_path / "c")


@pytest.mark.parametrize("stamp", [None, {"pin": {"qemu": "0-2", "probe": 4}},
                                   {"wifi": {"interface": "wlan0", "irq": 277}}, {"wifi": {"driver": ""}}])
def test_a_stamp_without_the_driver_name_is_refused_not_guessed(tmp_path, stamp):
    """The report used to fall back to one board's driver name. A record whose stamp does not
    say which interrupt is the Wi-Fi's cannot be scored against a name from somewhere else."""
    out = tmp_path / "o"
    _run(out, 4)
    if stamp is None:
        (out / "stamp.json").unlink()
    else:
        (out / "stamp.json").write_text(json.dumps(stamp))
    r = subprocess.run([sys.executable, REPORT, str(out), "1000", "200"], capture_output=True, text=True, timeout=900)
    assert r.returncode != 0, r.stdout
    assert "wifi.driver" in r.stderr and "stamp.json" in r.stderr, r.stderr
    assert "P1" not in r.stdout and "M4" not in r.stdout, "nothing is scored: " + r.stdout
    with pytest.raises(SystemExit):
        wr.wifi_name(str(out))


def test_the_driver_name_is_the_stamps(tmp_path):
    (tmp_path / "stamp.json").write_text(json.dumps({"wifi": {"interface": "wlan0", "driver": "examplewifi", "irq": 9}}))
    assert wr.wifi_name(str(tmp_path)) == "examplewifi"


def test_the_harness_parses_and_states_its_rule_and_prediction_before_any_code():
    if BASH is not None:
        r = subprocess.run([BASH, "-n", HARNESS], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
    text = open(HARNESS, encoding="utf-8").read()
    head, body = text.split("\nset -u\n", 1)
    for s in ("median DIFF(p99) <= -3 us", "EXCESS <= 0.8%", "|median DIFF(p50)| <= 2 us", "LIFT >= 3",
              "[t0 - 500 us, t0 + its round trip]", "It is not to be amended", "Scored only at k = 40",
              "The owner asked for this test", "never recorded", "odd rounds on then off",
              "This SSH session NOT on the Wi-Fi"):
        assert s in head, s
    assert "wifi_report.py" in body and 'BG=""' in body and "rfkill unblock" in body
    assert "would cut it" in body, "the harness refuses to run over the Wi-Fi it switches off"


def test_the_interface_is_the_running_systems_and_has_no_default_name():
    body = open(HARNESS, encoding="utf-8").read().split("\nset -u\n", 1)[1]
    assert 'WIFI_IF="${WIFI_IF:-$(m_wifi_if)}"\n[ -n "$WIFI_IF" ] || die ' in body and "set WIFI_IF" in body
    assert "WIFI_IF:-wl" not in body


def _harness(tmp_path, nets, **env):
    """run-wifi.sh against a fake /sys whose class/net holds `nets` ({name: wireless?})."""
    sys_root = tmp_path / "sys"
    (sys_root / "class" / "net").mkdir(parents=True)
    for name, wireless in nets.items():
        d = sys_root / "class" / "net" / name
        d.mkdir()
        if wireless:
            (d / "phy80211").mkdir()
        (d / "operstate").write_bytes(b"up\n")
    e = dict(os.environ, SYS_ROOT=str(sys_root).replace("\\", "/"), **env)
    for k in ("WIFI_IF", "CONSOLE"):
        if k not in env:
            e.pop(k, None)
    return subprocess.run([BASH, HARNESS], capture_output=True, text=True, timeout=60, env=e)


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_the_harness_takes_the_one_wireless_interface_and_asks_when_there_is_not_exactly_one(tmp_path):
    """No default name: the interface is the running system's one wireless interface, and with
    none or several the harness stops and asks for WIFI_IF. It gets no further here than its
    next required setting (CONSOLE), which is unset on purpose: nothing is switched."""
    r = _harness(tmp_path / "none", {"eth0": False, "lo": False})
    assert r.returncode != 0 and "set WIFI_IF" in r.stderr and "none" in r.stderr, r.stderr
    assert "CONSOLE" not in r.stderr, "it stopped at the interface, before anything else: " + r.stderr
    r = _harness(tmp_path / "two", {"wlan0": True, "wlan1": True})
    assert r.returncode != 0 and "set WIFI_IF" in r.stderr and "wlan0=up;wlan1=up" in r.stderr, r.stderr
    r = _harness(tmp_path / "one", {"eth0": False, "wlan0": True})
    assert r.returncode != 0 and "set WIFI_IF" not in r.stderr and "set CONSOLE" in r.stderr, r.stderr
    r = _harness(tmp_path / "given", {"eth0": False}, WIFI_IF="wlan7")
    assert r.returncode != 0 and "set WIFI_IF" not in r.stderr and "set CONSOLE" in r.stderr, r.stderr


def test_what_is_known_names_records_and_quotes_no_figure():
    text = open(HARNESS, encoding="utf-8").read()
    known = rg.known_sections(text)
    assert len(known) >= 5 and "20260929T-a6-orin-irqconf" in " ".join(line for _n, line in known)
    assert [f for _n, line in known for f in rg.figures(line)] == []
