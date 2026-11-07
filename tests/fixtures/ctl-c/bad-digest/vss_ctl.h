/* vss_ctl.h -- the kind 2 TEST FIXTURE of ../vss_ctl.h with one change: VSS_CTL_DIGEST is not the FNV-1 32 of
 * the seven UIDs (its last bit flipped). Synthetic, written by hand. A monitor built with it must refuse to serve:
 * `monitor: ctl contract inconsistent` on stderr, exit 2, before any serving line (the Phase 8 specification,
 * section 2.4; tests/test_monitor_ctl.py).
 */
#ifndef VSS_CTL_H
#define VSS_CTL_H

#define VSS_CTL_FORMAT 1u

/* slot 0: Vehicle.DualVm.ControlCommand.Velocity (p[2..5]) */
#define VSS_CTL_UID_SLOT0 0xC7100001u
/* slot 1: Vehicle.DualVm.ControlCommand.Acceleration (p[25..28]) */
#define VSS_CTL_UID_SLOT1 0xC7100002u
/* slot 2: Vehicle.DualVm.ControlCommand.Jerk (p[29..32]) */
#define VSS_CTL_UID_SLOT2 0xC7100003u
/* slot 3: Vehicle.DualVm.ControlCommand.SteeringTireAngle (p[33..36]) */
#define VSS_CTL_UID_SLOT3 0xC7100004u
/* slot 4: Vehicle.DualVm.ControlCommand.SteeringTireRotationRate (p[37..40]) */
#define VSS_CTL_UID_SLOT4 0xC7100005u
/* slot 5: Vehicle.DualVm.Motion.LongitudinalVelocity (p[41..44]) */
#define VSS_CTL_UID_SLOT5 0xC7100006u
/* slot 6: Vehicle.DualVm.ControlCommand.StampInterval (p[45..46]) */
#define VSS_CTL_UID_SLOT6 0xC7100007u

#define VSS_CTL_DIGEST 0x682F2F03u

#define VSS_CTL_DT_MAX_MS 200u
#define VSS_CTL_TOL17 0.5
#define VSS_CTL_OVERSPEED_FACTOR 1.2
#define VSS_CTL_OVERSPEED_MARGIN 2.0
#define VSS_CTL_ROLLBACK_V 0.5

/* X(id, l_mm, v_max, a_max, jerk_max, steer_max, steer_rate_max, lat_acc_max)
 * units: -, mm, m/s, m/s^2, m/s^3, rad, rad/s, m/s^2 */
#define VSS_CTL_PROFILE_TABLE(X) \
    X(1u, 2790u, 25.0, 5.0, 80.0, 1.0, 1.0, 5.0) \
    X(2u, 2790u, 3.0, 5.0, 80.0, 1.0, 1.0, 5.0)

#define VSS_CTL_PROFILE_COUNT 2u
#define VSS_CTL_PROFILE_IDS "1 2"

#endif /* VSS_CTL_H */
