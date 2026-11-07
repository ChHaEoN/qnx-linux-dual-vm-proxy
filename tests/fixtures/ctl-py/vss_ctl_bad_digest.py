"""vss_ctl_bad_digest.py -- the bad-digest twin of tests/fixtures/ctl-py/vss_ctl.py, for tests/test_sdv_ctl.py.

The same module with DIGEST one more than the FNV-1 32 of SLOT_UIDS, as a hand-edited contract would have it: the
loader refuses it. Its own file name (not bad-digest/vss_ctl.py) because mypy reads every .py under tests/ and two
files both named vss_ctl.py would be one module twice. Synthetic values only, as the fixture it copies.
"""

FORMAT = 1

SLOT_PATHS = (
    "Vehicle.DualVm.ControlCommand.Velocity",
    "Vehicle.DualVm.ControlCommand.Acceleration",
    "Vehicle.DualVm.ControlCommand.Jerk",
    "Vehicle.DualVm.ControlCommand.SteeringTireAngle",
    "Vehicle.DualVm.ControlCommand.SteeringTireRotationRate",
    "Vehicle.DualVm.Motion.LongitudinalVelocity",
    "Vehicle.DualVm.ControlCommand.StampInterval",
)
SLOT_UIDS = (0xC7100001, 0xC7100002, 0xC7100003, 0xC7100004, 0xC7100005, 0xC7100006, 0xC7100007)
DIGEST = 0x682F2F03

DT_MAX_MS = 200
TOL17 = 0.5
OVERSPEED_FACTOR = 1.2
OVERSPEED_MARGIN = 2.0
ROLLBACK_V = 0.5

PROFILES = {
    1: {"l_mm": 2790, "v_max": 25.0, "a_max": 5.0, "jerk_max": 80.0, "steer_max": 1.0, "steer_rate_max": 1.0,
        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": True},
    2: {"l_mm": 2790, "v_max": 3.0, "a_max": 5.0, "jerk_max": 80.0, "steer_max": 1.0, "steer_rate_max": 1.0,
        "lat_acc_max": 5.0, "run_window_max_ms": 30000, "compiled": True},
    3: {"l_mm": 2790, "v_max": 25.0, "a_max": 5.0, "jerk_max": 80.0, "steer_max": 0.5, "steer_rate_max": 1.0,
        "lat_acc_max": 5.0, "run_window_max_ms": None, "compiled": False},
}
COMPILED_PROFILE_IDS = (1, 2)
