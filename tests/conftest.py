"""pytest configuration.

Two import problems this file solves, both structural rather than incidental:

1. The repo is not a Python package. scripts/ci/ and orin-native/ are trees of
   standalone tools, so the repo root and scripts/ci must go on sys.path before
   anything under test can be imported.

2. Seven of the ten tracked Python tools have HYPHENATED filenames
   (parse-m4.py, kpf-decode.py, ...), which are not importable module names.
   `load_tool()` loads them by path so their pure functions can be tested
   without renaming files that board scripts and PowerShell launchers invoke
   by name.
"""
import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

for path in (REPO_ROOT, os.path.join(REPO_ROOT, "scripts", "ci")):
    if path not in sys.path:
        sys.path.insert(0, path)


def load_tool(relpath, name=None):
    """Import a tool by file path, for hyphenated or non-package modules."""
    full = os.path.join(REPO_ROOT, relpath)
    mod_name = name or os.path.basename(relpath).replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(mod_name, full)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def repo_root():
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_dir():
    return FIXTURES


@pytest.fixture(scope="session")
def latency_probe():
    return load_tool(os.path.join("orin-native", "gpu-concurrency", "latency_probe.py"))
