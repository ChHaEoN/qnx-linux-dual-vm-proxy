"""compare-ifs.py (2026-09-26): accept a derived guest image only if exactly the expected files
differ and exactly the files named after --added are added. dumpifs is replaced by a stub
extract() over plain directories, so no QNX tool runs here."""
import importlib.util
import os

HERE = os.path.dirname(__file__)
PATH = os.path.join(HERE, "..", "ipc-test", "qnx-safety-monitor", "compare-ifs.py")
spec = importlib.util.spec_from_file_location("compare_ifs", PATH)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def _image(root, files):
    root.mkdir()
    out = {}
    for name, data in files.items():
        p = root / name.replace("/", "_")
        p.write_bytes(data)
        out[name] = str(p)
    return out


def _run(tmp_path, monkeypatch, old, new, args):
    imgs = {"OLD": _image(tmp_path / "old", old), "NEW": _image(tmp_path / "new", new)}
    monkeypatch.setattr(ci, "extract", lambda image, into: imgs[image])
    return ci.main(["compare-ifs.py", "OLD", "NEW"] + args)


BASE = {"proc/boot/monitor": b"m", "proc/boot/startup-script": b"s1", "proc/boot/build.date": b"d1"}


def test_an_expected_addition_is_accepted_and_an_unexpected_one_refused(tmp_path, monkeypatch, capsys):
    new = dict(BASE, **{"proc/boot/startup-script": b"s2", "proc/boot/build.date": b"d2", "proc/boot/qnx-clockctl": b"c"})
    (tmp_path / "a").mkdir()
    rc = _run(tmp_path / "a", monkeypatch, BASE, new,
              ["proc/boot/startup-script", "proc/boot/build.date", "--added", "proc/boot/qnx-clockctl"])
    assert rc == 0 and "ACCEPT" in capsys.readouterr().out
    (tmp_path / "b").mkdir()
    rc = _run(tmp_path / "b", monkeypatch, BASE, new, ["proc/boot/startup-script", "proc/boot/build.date"])
    assert rc == 1 and "NOT EXPECTED" in capsys.readouterr().out


def test_a_missing_addition_or_a_changed_monitor_is_refused(tmp_path, monkeypatch, capsys):
    new = dict(BASE, **{"proc/boot/startup-script": b"s2"})
    (tmp_path / "a").mkdir()
    rc = _run(tmp_path / "a", monkeypatch, BASE, new, ["proc/boot/startup-script", "--added", "proc/boot/qnx-clockctl"])
    assert rc == 1 and "expected to be added but is not" in capsys.readouterr().out
    new = dict(BASE, **{"proc/boot/startup-script": b"s2", "proc/boot/monitor": b"M", "proc/boot/x": b"x"})
    (tmp_path / "b").mkdir()
    rc = _run(tmp_path / "b", monkeypatch, BASE, new, ["proc/boot/startup-script", "--added", "proc/boot/x"])
    assert rc == 1 and "proc/boot/monitor   <-- NOT EXPECTED" in capsys.readouterr().out
