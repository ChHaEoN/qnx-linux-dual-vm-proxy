"""Service and session lists must survive serialization into a harness's stamp."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

GC = Path(__file__).resolve().parent.parent / "orin-native" / "gpu-concurrency"
BASH = shutil.which("bash")
HARNESSES = ("clock", "confine", "guesttick", "irqconf", "metal", "natural", "partition", "tick", "wifi")


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
@pytest.mark.parametrize("name", HARNESSES)
@pytest.mark.parametrize("multiple", (False, True))
def test_unit_lists_preserve_every_target_in_json(tmp_path, name, multiple):
    lines = (GC / ("run-%s.sh" % name)).read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('UNITS="system.slice'))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("for u in $UNITS;"))
    assignment = "\n".join(lines[start:end])
    # Execute the actual stamp argument, rather than a duplicate of its quoting.
    argument = next(line.strip() for line in lines if "units $UNITS" in line and line.rstrip().endswith("\\"))[:-1]
    services = ["user@1001.service"] + (["user@1002.service"] if multiple else [])
    scopes = ["session-42.scope"] + (["session-43.scope", "session-44.scope"] if multiple else [])
    stub = tmp_path / "systemctl"
    stub.write_text("#!/usr/bin/env bash\ncase \"$*\" in *user@*) printf '%s\\n' "
                    + " ".join(services) + ";; *) printf '%s\\n' " + " ".join(scopes) + ";; esac\n")
    stub.chmod(0o755)
    script = """
set -u
ME=session-42.scope
ALL=0-5; CONF_CORES=3,5; ZONE_TYPE=test-zone; TZ=/tmp/test-zone
VCPU_CORES=0,1; OTHER_CORES=2; CORE_AUX=5; INJ_SRC=unused; SEED=1
CPAT=(open confined confined open)
_sha() { printf 'synthetic'; }
""" + assignment + "\nprintf '{%s}\\n' " + argument + "\n"
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    result = subprocess.run([BASH, "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    stamp = json.loads(result.stdout)
    value = next(iter(stamp.values()))
    recorded = value.split("units ", 1)[1]
    expected = ["system.slice", "init.scope"] + services + scopes[1:]
    assert recorded.split()[:len(expected)] == expected
    assert "session-42.scope" not in value
