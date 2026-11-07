/* Phase 3b (Orin, QNX guest under KVM): the Safety end of a cross-partition
 * service.
 *
 * KVM here boots our startup-qemu-virt; this is not a QNX-supported
 * configuration, and no timing claim attaches to the boot.
 *
 * WHAT THIS IS
 *
 * L4T owns the GPU and runs the perception work (TensorRT); this program runs
 * in the QNX guest and plays the role a Safety partition plays in a DRIVE OS
 * style split: it does not perceive anything itself, it *checks* what the
 * Compute side claims, and answers with a verdict.
 *
 * It is a deliberate step up from ipc-test/qnx-server-net/server.c, which
 * echoes frames verbatim. This one interprets the payload, applies plausibility
 * rules, and writes its own verdict into the reply -- so the reply says
 * something the Compute side did not already know.
 *
 * WIRE FORMAT (reuses ipc-test/common/frame.h, 64 bytes fixed)
 *
 *   offset 0  : uint64 seq             (initiator's, echoed back unchanged)
 *   offset 8  : uint64 tstamp_cycles   (initiator's, echoed back unchanged)
 *   payload[0]      : uint8  class id     (0..9, an mnist digit)
 *   payload[1]      : uint8  confidence   (0..100, percent)
 *   payload[2..5]   : uint32 inference_us (Compute side's own model time)
 *   payload[6]      : uint8  verdict      <- WRITTEN BY THIS PROGRAM
 *   payload[7]      : uint8  reason       <- WRITTEN BY THIS PROGRAM
 *   payload[8..23]  : measurement-design section 3.3: echoed, or in the stamp
 *                     mode written with t_in and t_out (see OD15 below)
 *   payload[24]     : uint8  claim kind   (0 mnist, 1 vlm; see CLAIM KINDS)
 *   payload[25..47] : kind-specific, echoed unchanged
 *
 * The initiator's seq and timestamp are never touched, exactly as in
 * qnx-server-net: only the initiator interprets a clock, so there is no
 * cross-OS clock to reconcile. Nothing but payload[6] and [7] is ever written --
 * except by the stamp mode (OD15, below), which also writes payload[8..23].
 *
 * CLAIM KINDS (owner decision OD13, 2026-09-23)
 *
 *   kind 0, mnist : the 2026-09-18 TensorRT claim. Its rules are unchanged, and
 *                   so is everything they read: payload[25..47] is ignored. The
 *                   latency probe's frame is all zeros past [5], so every A6
 *                   run rides on this path; CI pins it at every boundary.
 *   kind 1, vlm   : a vision-language model's digit claim, from llama.cpp on
 *                   L4T. The same class and confidence slots, [2..5] the
 *                   model's own time (prompt plus generation, image encode
 *                   included), and in payload[25..47]:
 *                     [25]      uint8  model id (1 = SmolVLM-500M-Instruct Q8_0)
 *                     [26..27]  uint16 prompt tokens
 *                     [28..29]  uint16 generated tokens
 *                     [30..33]  uint32 prompt_us
 *                     [34..37]  uint32 generated_us
 *                     [38..41]  uint32 client wall time, us (not judged)
 *                     [42..45]  uint32 the digit tokens' share of probability
 *                               at the answer position, parts per million
 *                               (not judged; recorded so a renormalised
 *                               confidence cannot hide a spread distribution)
 *                     [46..47]  reserved, zero
 *   kind 4, vss   : only in the vss build (MONITOR_EXT_KINDS, below; sdv
 *                   Phase 2): five vehicle signals with their own meaning of
 *                   payload[0..5] and [25..47]. Every other build rejects it
 *                   as it rejects any other kind. Only kind 4's REJECT lines
 *                   are rate-limited (vss_log(), below); the vss build also
 *                   announces its rules after the claim kinds line, and
 *                   refuses to serve when its compiled catalogue digest is
 *                   not that of its compiled UIDs.
 *   any other kind: rejected, reason claim-kind-unknown.
 *
 * The kind is dispatched inside check_claim(), which only judge_frame() calls,
 * so all four transports carry both kinds with no change to any of them.
 *
 * WHAT THIS IS NOT
 *
 * Not a safety mechanism in any ISO 26262 sense, and no ASIL claim attaches to
 * it. The rules below are plausibility checks chosen to be legible, not a
 * validated diagnostic. It shows the *shape* of a safety partition checking a
 * compute partition across a real VM boundary; it does not show freedom from
 * interference, and the boundary here is KVM (Linux owns this guest's memory),
 * not a certified Type-1 partition.
 *
 * TWO TRANSPORTS, ONE JUDGEMENT (owner decision OD12, 2026-09-21)
 *
 *   monitor [PORT]        TCP, one client at a time (the original)
 *   monitor PORT udp      UDP, one 64-byte frame per datagram
 *
 * Both paths call judge_frame(), so a claim gets the same verdict whichever
 * transport carried it -- the point of a UDP arm is to vary the transport and
 * nothing else. A datagram that is not exactly one frame is dropped without a
 * reply and counted: on UDP there is no stream to resynchronise, and replying
 * to a fragment would hand the initiator bytes it did not send. The UDP socket
 * does NOT set SO_REUSEADDR, so a second UDP monitor on the same port fails to
 * bind -- the ladder relies on that to refuse a leftover server.
 *
 * A THIRD TRANSPORT: SHARED MEMORY (OD12, 2026-09-22)
 *
 *   monitor shm SPEC      one request/reply slot in shared memory (shm_chan.h)
 *
 * SPEC is resolved by whichever shm_map_*.c was linked in: on the host a file
 * path under /dev/shm, in the guest "ivshmem" (QEMU's ivshmem PCI device). This
 * file has no #ifdef for it -- the guest and the host still build one source.
 * The same judge_frame() again. There is no interrupt: the loop polls. It spins
 * while requests are arriving and, 50 ms after the last one, falls back to
 * looking every 10 ms, so a monitor left running between arms costs a wake-up
 * every 10 ms rather than a whole core. The first frames after a quiet spell
 * wait for that 10 ms look -- the probe's warm-up frames absorb it.
 * SPEC may end in @OFFSET to place the slot inside the region.
 *
 * AND ITS NOTIFIED VARIANT (OD12, 2026-09-22)
 *
 *   monitor shmkick SPEC@OFFSET KICK   the same slot; the server sleeps until a
 *                                      kick byte arrives on KICK, and tells the
 *                                      client its reply is ready by a kick byte
 *                                      back or by a doorbell (shm_chan.h)
 *   monitor shmcfg SPEC                configure the shared-memory device once and
 *                                      exit (the guest; a host has nothing to do)
 *
 * Nobody spins in shmkick: the server blocks in the kick channel's read. The
 * judgement is judge_frame() again.
 *
 * AND A SERVICE MODE WITH A DEADLINE (owner decision OD14, 2026-09-23)
 *
 *   monitor PORT svc DEADLINE_MS   TCP as the original, plus a liveness
 *                                  deadline on the claim stream (serve_svc)
 *
 * A function of its own, so that no mode above changes and each change's cost
 * stays separable (OD13). The judgement is judge_frame() again.
 *
 * AND GUEST-SIDE TIMESTAMPS (owner decision OD15, 2026-09-23)
 *
 *   monitor PORT stamp    the TCP mode, writing into every claim's reply
 *                            payload[8..15]   t_in,  just after the frame is read
 *                            payload[16..23]  t_out, just before it is written
 *                         both uint64 LE ns from CLOCK_MONOTONIC (measurement-
 *                         design 3.3). t_out - t_in is the monitor's own time
 *                         on its own clock, so no clock is synchronised with
 *                         anyone's. A sentinel is echoed untouched, unstamped.
 *
 * The one mode that writes a reply byte other than payload[6] and [7]; every
 * other mode still writes only those. The plain TCP mode shares its loop and
 * pays two not-taken tests of `stamp` per frame for it (unmeasured: the OD15
 * run's plain arms run this binary too).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <time.h>
#include <poll.h>
#include <fcntl.h>

#include "frame.h"
#include "frame_io.h"
#include "shm_chan.h"
#include "shm_map.h"

/* The extension-kind switch (sdv Phase 2; kind 4 wire specification, section 11).
 * MONITOR_EXT_KINDS is a bitmask of the extension kinds a build knows: 0x10 vss
 * (kind 4), 0x14 ctl, 0x1C gap. It is undefined in every existing build, which
 * compiles exactly as before: everything it gates sits in bare #if blocks, and
 * every guard tests definedness explicitly rather than let an undefined macro
 * read as 0. The lineage is cumulative, so any other defined value is refused. */
#if defined(MONITOR_EXT_KINDS)
#  if MONITOR_EXT_KINDS != 0x10 && MONITOR_EXT_KINDS != 0x14 && MONITOR_EXT_KINDS != 0x1C
#    error "MONITOR_EXT_KINDS must be 0x10 (vss), 0x14 (ctl) or 0x1C (gap)"
#  endif
/* A deviation from section 11 (Phase 2 design decision d), narrowed in Phase 8
 * (WP1a) when kind 2 landed: kind 3 does not exist yet, so a gap build would
 * answer it with claim-kind-unknown while its name says it knows it. This
 * #error goes when kind 3 lands. */
#  if MONITOR_EXT_KINDS == 0x1C
#    error "MONITOR_EXT_KINDS 0x1C (gap): not implemented"
#  endif
#endif

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
/* Generated by sdv/vss/generate.py into sdv-out/gen (never committed); the
 * build passes that directory with -I. */
#include "vss_contract.h"
#include "vss_profiles.h"
#include <float.h>
#  if !defined(VSS_CONTRACT_FORMAT) || VSS_CONTRACT_FORMAT != 1u
#    error "vss_contract.h is not contract format 1: regenerate it with sdv/vss/generate.py"
#  endif
/* Rule 26 is computed in double, and the Python reference does it in double.
 * A wider evaluation method (x87, FLT_EVAL_METHOD 2) would compute something
 * else, so a build that cannot say it evaluates in the operands' type stops. */
#  if !defined(__FLT_EVAL_METHOD__) || __FLT_EVAL_METHOD__ != 0
#    error "the vss build needs __FLT_EVAL_METHOD__ defined and 0 (each operation in its own type)"
#  endif
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
/* CLAIM KIND 2, ctl (sdv Phase 8, WP1a; the kind 2 frame and rules of the Phase
 * 8 specification, sections 2.1-2.5): one Control command of the planning
 * stack's command gate, packed by the claim node into this frame. Only in the
 * ctl build (MONITOR_EXT_KINDS 0x14, which carries kind 4 too); every other
 * build rejects it as any other unknown kind. Its own meaning of payload[0..5]
 * and [25..47] (below), its reasons 11-19 beside the shared 8, 9 and 10, its
 * own REJECT line and limiter (ctl_log(), below), and its rules announced after
 * kind 4's. It reuses kind 4's f32_at(), any_nonzero(), dabs(), vss_tan() and
 * vss_fnv1_32(), and VSS_M_PER_MM and VSS_CATALOG_VERSION of vss_contract.h.
 *
 * Its contract, vss_ctl.h, is searched on the include path. sdv/vss/generate.py
 * is to write it into sdv-out/gen beside vss_contract.h (never committed; WP1b);
 * until then tests/test_monitor_ctl.py compiles against a hand-written fixture.
 * Like kind 4's, the monitor refuses to serve when the contract's digest is not
 * that of its compiled UIDs, and also when a compiled profile's steer_max is
 * outside (0, 1.0] rad, its l_mm is 0 or its id is another row's
 * (ctl_contract_consistent()).
 *
 * What it is not: kind 2 is advisory, judged beside the control loop and never
 * in it; a REJECT is a line and a reply, not an actuation, and its limits are a
 * plausibility envelope of the gate's own output, not a validated diagnostic. */
#include "vss_ctl.h"
#  if !defined(VSS_CTL_FORMAT) || VSS_CTL_FORMAT != 1u
#    error "vss_ctl.h is not ctl contract format 1: regenerate it with sdv/vss/generate.py"
#  endif
#endif

#define DEFAULT_PORT 7100

/* payload offsets */
#define P_CLASS      0u
#define P_CONF       1u
#define P_INFER_US   2u
#define P_VERDICT    6u
#define P_REASON     7u
#define P_KIND       24u
#define P_T_IN        8u   /* stamp mode (OD15): uint64 ns, just after the read  */
#define P_T_OUT      16u   /* stamp mode (OD15): uint64 ns, just before the write */

/* kind 1 (vlm) fields, payload[25..47] */
#define P_VLM_MODEL        25u
#define P_VLM_PROMPT_US    30u
#define P_VLM_GEN_US       34u

/* claim kinds */
#define KIND_MNIST   0u
#define KIND_VLM     1u

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
/* kind 4, vss (the kind 4 wire specification, section 2): four f32 signals
 * and the gear, each slot's VSS identity implied by its position, the set
 * bound to one catalogue by a digest. [6..7] are the verdict and reason as for
 * every kind, [8..23] are zero in a request (the stamp mode writes them after
 * the judgement), [24] is the kind. Little-endian throughout. */
#define KIND_VSS        4u
#define P_VSS_FLAGS     0u   /* uint8 presence: b0 v, b1 a_x, b2 delta, b3 psi_dot, b4 gear */
#define P_VSS_PROFILE   1u   /* uint8 profile id, a key into the compiled table */
#define P_VSS_DIGEST    2u   /* uint32 catalogue digest */
#define P_VSS_STAMP     8u   /* [8..23], zero in a request */
#define P_VSS_V        25u   /* f32 signed longitudinal speed, m/s */
#define P_VSS_AX       29u   /* f32 longitudinal acceleration, m/s^2 */
#define P_VSS_DELTA    33u   /* f32 road-wheel steering angle, degrees */
#define P_VSS_PSI_DOT  37u   /* f32 yaw rate, degrees/s */
#define P_VSS_AGE      41u   /* uint16 age of the oldest value, ms */
#define P_VSS_GEAR     43u   /* int8 current gear */
#define P_VSS_RESERVED 44u   /* [44..47], zero */
#define F_SPEED      0x01u
#define F_ACCEL      0x02u
#define F_STEER      0x04u
#define F_YAW        0x08u
#define F_GEAR       0x10u
#define F_SLOTS      0x1Fu   /* b0..b4: "a value is present" */
#define F_RESERVED   0xE0u   /* b5..b7: zero */
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
/* kind 2, ctl (the Phase 8 specification, section 2.2): the command's six f32
 * values and the stamp interval, each slot's VSS identity implied by its
 * position; no digest on the wire, so the contract binds by the self-check
 * alone. [6..7] are the verdict and reason as for every kind, [8..23] are zero
 * in a request (the stamp mode writes them after the judgement), [24] is the
 * kind. Little-endian throughout. "All zero bytes" is four 0x00: -0.0 is not. */
#define KIND_CTL         2u
#define P_CTL_FLAGS      0u   /* uint8: b0 acceleration, b1 jerk, b2 steering rate defined; b3 odometry fresh */
#define P_CTL_PROFILE    1u   /* uint8 profile id, a key into the compiled table (0 is never bound) */
#define P_CTL_V_CMD      2u   /* f32 longitudinal velocity command, m/s, always present */
#define P_CTL_STAMP      8u   /* [8..23], zero in a request */
#define P_CTL_ACCEL     25u   /* f32 acceleration, m/s^2 (b0) */
#define P_CTL_JERK      29u   /* f32 jerk, m/s^3 (b1) */
#define P_CTL_DELTA     33u   /* f32 steering tire angle, rad, positive left, always present */
#define P_CTL_RATE      37u   /* f32 steering tire rotation rate, rad/s (b2) */
#define P_CTL_V_MEAS    41u   /* f32 measured speed, m/s (b3) */
#define P_CTL_INTERVAL  45u   /* uint16 the ROS stamp interval, ms, saturated at 0xFFFF */
#define P_CTL_RESERVED  47u   /* zero */
#define CF_ACCEL      0x01u
#define CF_JERK       0x02u
#define CF_RATE       0x04u
#define CF_ODOM       0x08u
#define CF_RESERVED   0xF0u   /* b4..b7: zero */
#endif

/* vlm models this monitor has a configured bound for */
#define VLM_MODEL_SMOLVLM_500M 1u

/* verdicts */
#define V_ACCEPT     0u
#define V_REJECT     1u

/* Reasons (why a frame was rejected; 0 when accepted).
 *
 * Prefixed RSN_ rather than R_: <unistd.h> already defines R_OK as the
 * test-for-read-permission bit for access(2), and shadowing it here compiled
 * but warned. A reason code in a monitor that silently aliases a libc access
 * mode is the kind of ambiguity this program is supposed to not have. */
#define RSN_OK             0u
#define RSN_CLASS_RANGE    1u   /* class id outside the model's label set    */
#define RSN_CONF_RANGE     2u   /* confidence not a percentage               */
#define RSN_CONF_LOW       3u   /* below the acceptance threshold            */
#define RSN_INFER_IMPLAUS  4u   /* inference time implausible for this model */
#define RSN_KIND_UNKNOWN   5u   /* payload[24] names no claim kind            */
#define RSN_MODEL_UNBOUND  6u   /* a vlm this monitor has no configured bound for */
#define RSN_TIME_INCONSIST 7u   /* the claimed time is not the sum of its parts */

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
/* Kind 4's reasons (wire specification section 6). 8, 9 and 10 have the names
 * kinds 2 and 3 will share; 11-20 stay theirs; kind 4's own start at 21. */
#define RSN_PROFILE_UNBOUND  8u   /* payload[1] is no compiled profile (0 never is) */
#define RSN_NOT_FINITE       9u   /* a present f32 is an infinity or a NaN         */
#define RSN_FLAGS_INVALID   10u   /* reserved bits or bytes, an absent slot's bytes, an age of nothing */
#define RSN_VSS_CATALOG     21u   /* the digest is not this build's catalogue      */
#define RSN_VSS_STALE       22u   /* the oldest value is older than AGE_MAX        */
#define RSN_VSS_SPEED       23u   /* |v| over the profile's v_max                  */
#define RSN_VSS_ACCEL       24u   /* |a_x| over a_max                              */
#define RSN_VSS_STEER       25u   /* |delta| over delta_max                        */
#define RSN_VSS_YAW         26u   /* the yaw rate is not the kinematic one within tol */
#define RSN_VSS_GEAR        27u   /* the gear against the direction of travel      */
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
/* Kind 2's own reasons (the Phase 8 specification, section 2.3), beside the
 * shared 8, 9 and 10 above. 20 is kind 3's and is not built here. */
#define RSN_CTL_INTERVAL     11u  /* the stamp interval over DT_MAX_MS             */
#define RSN_CTL_SPEED        12u  /* |v_cmd| over the profile's v_max              */
#define RSN_CTL_ACCEL        13u  /* b0 and |a| over a_max                         */
#define RSN_CTL_JERK         14u  /* b1 and |j| over jerk_max                      */
#define RSN_CTL_STEER        15u  /* |delta| over steer_max                        */
#define RSN_CTL_STEER_RATE   16u  /* b2 and |rate| over steer_rate_max             */
#define RSN_CTL_LAT_ACCEL    17u  /* b3 and v_meas^2 tan|delta| / L over lat_acc_max + TOL17 */
#define RSN_CTL_OVERSPEED    18u  /* b3 and |v_meas| over the overspeed bound of |v_cmd| */
#define RSN_CTL_ROLLING_BACK 19u  /* b3, v_meas below -ROLLBACK_V while v_cmd >= 0 */
#endif

/* Acceptance threshold, percent. Chosen for the demo, not derived from any
 * hazard analysis -- see "WHAT THIS IS NOT" above. It applies to both kinds;
 * the vlm confidences it was set against are in record
 * `20260923T-a6-orin-vlm-characterize` (held locally). */
#define CONF_MIN     60u

/* The mnist bound: a claim over 100 ms is taken as not from that engine on
 * that device, so it is not plausible. Generous on purpose: this rejects
 * nonsense, it does not police performance. */
#define INFER_US_MAX 100000u

/* The vlm plausibility threshold (OD13): retained from
 * `20260923T-a6-orin-vlm-characterize`. It is not a deadline or a
 * validated performance bound. Only the configured model is admitted. */
#define VLM_INFER_US_MAX 1000000u

static volatile sig_atomic_t g_stop = 0;

static uint64_t now_ns(void);   /* CLOCK_MONOTONIC; defined with the shm transport */

static void on_signal(int sig)
{
	(void)sig;
	g_stop = 1;
}

static uint32_t get_u32_le(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
	       ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
static uint16_t get_u16_le(const uint8_t *p)
{
	return (uint16_t)((unsigned)p[0] | ((unsigned)p[1] << 8));
}

/* f32_at() copies four bytes into a float and widens it, which is exact only
 * for a binary32 float and a binary64 double. */
_Static_assert(sizeof(float) == sizeof(uint32_t) && FLT_RADIX == 2 && FLT_MANT_DIG == 24 && FLT_MAX_EXP == 128
               && DBL_MANT_DIG == 53, "the vss build needs a binary32 float and a binary64 double");

/* The f32 at payload[off], widened to double (exact): assembled as a u32 from
 * its bytes, as get_u32_le() does, and copied into a float -- never a pointer
 * cast, the fields are unaligned. */
static double f32_at(const uint8_t *p, unsigned off)
{
	uint32_t const u = get_u32_le(&p[off]);
	float f;

	memcpy(&f, &u, sizeof(f));
	return (double)f;
}

static int any_nonzero(const uint8_t *b, size_t n)
{
	size_t i;

	for (i = 0; i < n; i++) {
		if (b[i] != 0u) {
			return 1;
		}
	}
	return 0;
}

/* The f32 slots 0..3, whose presence bits are b0..b3; slot 4 (b4) is the gear. */
static const uint8_t vss_f32_slot[4] = { P_VSS_V, P_VSS_AX, P_VSS_DELTA, P_VSS_PSI_DOT };

/* Reason 10's slot rule: a slot whose bit is clear is all zero bytes (-0.0,
 * 0x80000000, is not). */
static int absent_slot_nonzero(const uint8_t *p, uint8_t f)
{
	unsigned s;

	for (s = 0; s < 4u; s++) {
		if (!(f & (1u << s)) && any_nonzero(&p[vss_f32_slot[s]], 4u)) {
			return 1;
		}
	}
	return !(f & F_GEAR) && p[P_VSS_GEAR] != 0u;
}

/* Reason 9: a present f32 whose exponent bits are all ones, an infinity or a
 * NaN. Subnormals and -0.0 are finite. No <math.h>. */
static int present_nonfinite(const uint8_t *p, uint8_t f)
{
	unsigned s;

	for (s = 0; s < 4u; s++) {
		if ((f & (1u << s)) && ((get_u32_le(&p[vss_f32_slot[s]]) >> 23) & 0xFFu) == 0xFFu) {
			return 1;
		}
	}
	return 0;
}

/* |x| without <math.h>. A NaN never reaches it: reason 9 is judged first. */
static double dabs(double x)
{
	return x < 0.0 ? -x : x;
}
#endif

/* Kind 0, the mnist claim: the 2026-09-18 rules, unchanged. Returns the
 * verdict, and sets *reason. */
static uint8_t check_mnist(const uint8_t *payload, uint8_t *reason)
{
	uint8_t const cls  = payload[P_CLASS];
	uint8_t const conf = payload[P_CONF];
	uint32_t const us  = get_u32_le(&payload[P_INFER_US]);

	if (cls > 9u) {
		*reason = RSN_CLASS_RANGE;
		return V_REJECT;
	}
	if (conf > 100u) {
		*reason = RSN_CONF_RANGE;
		return V_REJECT;
	}
	if (us > INFER_US_MAX) {
		*reason = RSN_INFER_IMPLAUS;
		return V_REJECT;
	}
	if (conf < CONF_MIN) {
		*reason = RSN_CONF_LOW;
		return V_REJECT;
	}

	*reason = RSN_OK;
	return V_ACCEPT;
}

/* Kind 1, the vlm claim (OD13). The same class and confidence checks, then the
 * two things a vlm claim carries that the mnist one does not: which model made
 * it, and its time in parts. In order, first failure wins:
 *
 *   class > 9                        class-out-of-range
 *   conf > 100                       confidence-not-a-percentage
 *   model has no configured bound    vlm-model-unbounded
 *   total != prompt_us + gen_us      vlm-time-inconsistent
 *   total > VLM_INFER_US_MAX         inference-time-implausible
 *   conf < CONF_MIN                  confidence-below-threshold
 *
 * The sum is the one recomputation this monitor can actually do: it cannot know
 * whether the model is right, but it can refuse a total that its own parts
 * contradict. It comes before the bound, because a bound checked on a total
 * that does not add up means nothing. */
static uint8_t check_vlm(const uint8_t *payload, uint8_t *reason)
{
	uint8_t const cls   = payload[P_CLASS];
	uint8_t const conf  = payload[P_CONF];
	uint8_t const model = payload[P_VLM_MODEL];
	uint32_t const us   = get_u32_le(&payload[P_INFER_US]);
	uint64_t const sum  = (uint64_t)get_u32_le(&payload[P_VLM_PROMPT_US]) +
	                      (uint64_t)get_u32_le(&payload[P_VLM_GEN_US]);

	if (cls > 9u) {
		*reason = RSN_CLASS_RANGE;
		return V_REJECT;
	}
	if (conf > 100u) {
		*reason = RSN_CONF_RANGE;
		return V_REJECT;
	}
	if (model != VLM_MODEL_SMOLVLM_500M) {
		*reason = RSN_MODEL_UNBOUND;
		return V_REJECT;
	}
	if ((uint64_t)us != sum) {
		*reason = RSN_TIME_INCONSIST;
		return V_REJECT;
	}
	if (us > VLM_INFER_US_MAX) {
		*reason = RSN_INFER_IMPLAUS;
		return V_REJECT;
	}
	if (conf < CONF_MIN) {
		*reason = RSN_CONF_LOW;
		return V_REJECT;
	}

	*reason = RSN_OK;
	return V_ACCEPT;
}

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
/* Kind 4's profiles (wire specification section 5): one source vehicle's
 * wheelbase and one limit set each, compiled in from the generated
 * vss_profiles.h and found by the payload's id. Nothing in a profile is ever
 * on the wire. ay26_max 0.0 means rule 26 has no lateral-acceleration bound. */
struct vss_profile {
	uint8_t  id;
	uint16_t l_mm;          /* wheelbase, mm */
	double   v_max;         /* m/s */
	double   a_max;         /* m/s^2 */
	double   delta_max;     /* degrees */
	double   v26_lo;        /* rule 26's |v| window, m/s, both ends inclusive */
	double   v26_hi;
	double   ay26_max;      /* m/s^2; 0.0 = no bound */
	double   tol26;         /* degrees/s */
	double   v_tol;         /* m/s */
};

#define VSS_PROFILE_ROW(id, l_mm, v_max, a_max, delta_max, v26_lo, v26_hi, ay26_max, tol26, v_tol) \
	{ (id), (l_mm), (v_max), (a_max), (delta_max), (v26_lo), (v26_hi), (ay26_max), (tol26), (v_tol) },
static const struct vss_profile vss_profiles[] = {
	VSS_PROFILE_TABLE(VSS_PROFILE_ROW)
};
#undef VSS_PROFILE_ROW

/* Every row's id is 1..255: id 0 is reserved and never bound (wire
 * specification 5.1), and the payload carries the id in one byte. The generator
 * refuses both; this holds a hand-written vss_profiles.h to the same rule, so
 * the C table can never bind an id sdv/frame/rules.py's Tables refuses (FOUND BY
 * REVIEW, WP2+3: a row with id 0 compiled and was bound). A row outside the
 * range is a compile error, also without -Werror. */
#define VSS_PROFILE_ID_OK(id, l_mm, v_max, a_max, delta_max, v26_lo, v26_hi, ay26_max, tol26, v_tol) \
	_Static_assert((id) >= 1u && (id) <= 255u, "a vss profile id is 1..255: id 0 is never bound (spec 5.1)");
VSS_PROFILE_TABLE(VSS_PROFILE_ID_OK)
#undef VSS_PROFILE_ID_OK
_Static_assert(sizeof(vss_profiles) / sizeof(vss_profiles[0]) <= 255u, "at most one vss profile per id");

/* The one lookup of the table: the row with this id, or NULL (reason 8). */
static const struct vss_profile *vss_profile_find(uint8_t id)
{
	size_t i;

	for (i = 0; i < sizeof(vss_profiles) / sizeof(vss_profiles[0]); i++) {
		if (vss_profiles[i].id == id) {
			return &vss_profiles[i];
		}
	}
	return NULL;
}

/* tan without libm (wire specification 7.2): s(x) / c(x), the Taylor
 * polynomials of sin through x^13 and of cos through x^14, by Horner in x^2
 * with the highest power innermost, in double, for 0 <= x <= 1.0 rad. Rule 25
 * runs first and delta_max is at most 57 degrees, so |delta| stays inside.
 * Each coefficient is the double nearest (-1)^k / n!, printed with %.17g from
 * sdv/frame/rules.py's TAN_SIN_COEFFS and TAN_COS_COEFFS, and the loops are its
 * vss_tan()'s arrangement: where the compiler does not contract a multiply-add
 * (the vss builds pass -ffp-contract=off) the two agree bit for bit. The
 * specification requires only |vss_tan(x) - tan(x)| <= 1e-9 on [0, 1]. */
static const double vss_tan_sin[7] = {       /* x^1, x^3, ..., x^13 */
	1, -0.16666666666666666, 0.0083333333333333332, -0.00019841269841269841,
	2.7557319223985893e-06, -2.505210838544172e-08, 1.6059043836821613e-10
};
static const double vss_tan_cos[8] = {       /* x^0, x^2, ..., x^14 */
	1, -0.5, 0.041666666666666664, -0.0013888888888888889,
	2.4801587301587302e-05, -2.7557319223985888e-07, 2.08767569878681e-09, -1.1470745597729725e-11
};

static double vss_tan(double x)
{
	double const x2 = x * x;
	double s = vss_tan_sin[6];
	double c = vss_tan_cos[7];
	int k;

	for (k = 5; k >= 0; k--) {
		s = vss_tan_sin[k] + x2 * s;
	}
	s = x * s;
	for (k = 6; k >= 0; k--) {
		c = vss_tan_cos[k] + x2 * c;
	}
	return s / c;
}

/* Rule 26's two kinematic quantities (wire specification 7.1) from |v| [m/s],
 * |delta| [degrees] and L [mm], evaluated left to right as written there and
 * as sdv/frame/rules.py's kinematics() does: L is multiplied by VSS_M_PER_MM,
 * never divided by 1000, and a_y_kin reuses psi_dot_kin (no second tan).
 *   psi_dot_kin [deg/s] = VSS_DEG_PER_RAD * |v| * tan(|delta| * VSS_RAD_PER_DEG) / L_m
 *   a_y_kin [m/s^2]     = |v| * psi_dot_kin * VSS_RAD_PER_DEG */
static void vss_kinematics(double av, double ad, unsigned l_mm, double *kin, double *ay)
{
	double const l_m = (double)l_mm * VSS_M_PER_MM;

	*kin = VSS_DEG_PER_RAD * av * vss_tan(ad * VSS_RAD_PER_DEG) / l_m;
	*ay = av * *kin * VSS_RAD_PER_DEG;
}

/* Kind 4 (wire specification section 6). Reasons in the order 10, 8, 21, 9,
 * 22, 23, 24, 25, 26, 27; the first failure wins. Comparisons are strict, so a
 * value exactly at a limit is accepted; window bounds are inclusive. The
 * verdict is a function of the payload and the compiled tables only.
 * sdv/frame/rules.py's check_vss() is the reference it is tested against.
 *
 *   10 flags-invalid         a reserved flag bit; a byte of [8..23] or of
 *                            [44..47]; a byte of an absent slot (-0.0 counts);
 *                            an age with no value present
 *   8  profile-unbound       payload[1] is no compiled profile
 *   21 vss-catalog-mismatch  the digest is not VSS_CATALOG_DIGEST
 *   9  field-not-finite      a present f32 is an infinity or a NaN
 *   22 vss-stale             the age is over VSS_AGE_MAX_MS
 *   23 vss-speed             b0 and |v| > v_max
 *   24 vss-accel             b1 and |a_x| > a_max
 *   25 vss-steer             b2 and |delta| > delta_max
 *   26 vss-yaw-inconsistent  b0, b2 and b3; v26_lo <= |v| <= v26_hi; no a_y
 *                            bound, or a_y_kin within it; and
 *                            | |psi_dot| - psi_dot_kin | > tol
 *   27 vss-gear-direction    b0 and b4; gear > 0 and v < -v_tol, or gear < 0
 *                            and v > v_tol (gear 0 is never checked)
 *
 * An empty frame (no flags, age 0) passes every rule and is accepted. */
static uint8_t check_vss(const uint8_t *p, uint8_t *reason)
{
	uint8_t const f = p[P_VSS_FLAGS];
	const struct vss_profile *pr;
	double v, ax, d, y, av, ad;
	int g;

	/* 10 */
	if ((f & F_RESERVED) || any_nonzero(&p[P_VSS_STAMP], 16u) || any_nonzero(&p[P_VSS_RESERVED], 4u)
	    || absent_slot_nonzero(p, f)
	    || ((f & F_SLOTS) == 0u && (p[P_VSS_AGE] | p[P_VSS_AGE + 1u]) != 0)) {
		*reason = RSN_FLAGS_INVALID;
		return V_REJECT;
	}
	/* 8 */
	pr = vss_profile_find(p[P_VSS_PROFILE]);
	if (pr == NULL) {
		*reason = RSN_PROFILE_UNBOUND;
		return V_REJECT;
	}
	/* 21 */
	if (get_u32_le(&p[P_VSS_DIGEST]) != VSS_CATALOG_DIGEST) {
		*reason = RSN_VSS_CATALOG;
		return V_REJECT;
	}
	/* 9 */
	if (present_nonfinite(p, f)) {
		*reason = RSN_NOT_FINITE;
		return V_REJECT;
	}
	/* 22 */
	if ((unsigned)get_u16_le(&p[P_VSS_AGE]) > VSS_AGE_MAX_MS) {
		*reason = RSN_VSS_STALE;
		return V_REJECT;
	}
	v = f32_at(p, P_VSS_V);
	ax = f32_at(p, P_VSS_AX);
	d = f32_at(p, P_VSS_DELTA);
	y = f32_at(p, P_VSS_PSI_DOT);
	g = (int)(int8_t)p[P_VSS_GEAR];
	av = dabs(v);
	ad = dabs(d);
	/* 23, 24, 25 */
	if ((f & F_SPEED) && av > pr->v_max) {
		*reason = RSN_VSS_SPEED;
		return V_REJECT;
	}
	if ((f & F_ACCEL) && dabs(ax) > pr->a_max) {
		*reason = RSN_VSS_ACCEL;
		return V_REJECT;
	}
	if ((f & F_STEER) && ad > pr->delta_max) {
		*reason = RSN_VSS_STEER;
		return V_REJECT;
	}
	/* 26 */
	if ((f & (F_SPEED | F_STEER | F_YAW)) == (F_SPEED | F_STEER | F_YAW)
	    && av >= pr->v26_lo && av <= pr->v26_hi) {
		double kin, ay;

		vss_kinematics(av, ad, pr->l_mm, &kin, &ay);
		if ((pr->ay26_max == 0.0 || ay <= pr->ay26_max) && dabs(dabs(y) - kin) > pr->tol26) {
			*reason = RSN_VSS_YAW;
			return V_REJECT;
		}
	}
	/* 27 */
	if ((f & (F_SPEED | F_GEAR)) == (F_SPEED | F_GEAR)
	    && ((g > 0 && v < -pr->v_tol) || (g < 0 && v > pr->v_tol))) {
		*reason = RSN_VSS_GEAR;
		return V_REJECT;
	}

	*reason = RSN_OK;
	return V_ACCEPT;
}
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
/* Kind 2's profiles (the Phase 8 specification, sections 2.3 and 2.4): one
 * vehicle's wheelbase and one limit set each, compiled in from vss_ctl.h and
 * found by the payload's id. Nothing in a profile is ever on the wire. */
struct ctl_profile {
	uint8_t  id;
	uint16_t l_mm;            /* wheelbase, mm */
	double   v_max;           /* m/s */
	double   a_max;           /* m/s^2 */
	double   jerk_max;        /* m/s^3 */
	double   steer_max;       /* rad; 0 < steer_max <= 1.0, which the self-check holds */
	double   steer_rate_max;  /* rad/s */
	double   lat_acc_max;     /* m/s^2 */
};

#define CTL_PROFILE_ROW(id, l_mm, v_max, a_max, jerk_max, steer_max, steer_rate_max, lat_acc_max) \
	{ (id), (l_mm), (v_max), (a_max), (jerk_max), (steer_max), (steer_rate_max), (lat_acc_max) },
static const struct ctl_profile ctl_profiles[] = {
	VSS_CTL_PROFILE_TABLE(CTL_PROFILE_ROW)
};
#undef CTL_PROFILE_ROW

/* Every row's id is 1..255, as for kind 4: id 0 is never bound, and the payload
 * carries the id in one byte. A row outside the range, or a count that is not
 * the table's, is a compile error, also without -Werror. */
#define CTL_PROFILE_ID_OK(id, l_mm, v_max, a_max, jerk_max, steer_max, steer_rate_max, lat_acc_max) \
	_Static_assert((id) >= 1u && (id) <= 255u, "a ctl profile id is 1..255: id 0 is never bound");
VSS_CTL_PROFILE_TABLE(CTL_PROFILE_ID_OK)
#undef CTL_PROFILE_ID_OK
_Static_assert(sizeof(ctl_profiles) / sizeof(ctl_profiles[0]) == VSS_CTL_PROFILE_COUNT,
               "VSS_CTL_PROFILE_COUNT is the number of rows of VSS_CTL_PROFILE_TABLE");
/* The stamp interval saturates at 0xFFFF, and the first Control after a
 * silence carries that value: rule 11 must reject it. At 0xFFFF or above,
 * rule 11's comparison could never be true, which gcc reports only under
 * -Wextra; here it is a compile error, also without -Werror. */
_Static_assert(VSS_CTL_DT_MAX_MS < 0xFFFFu,
               "VSS_CTL_DT_MAX_MS is below 0xFFFF: a saturated interval (0xFFFF) fails rule 11");

/* The one lookup of the table: the row with this id, or NULL (reason 8). */
static const struct ctl_profile *ctl_profile_find(uint8_t id)
{
	size_t i;

	for (i = 0; i < sizeof(ctl_profiles) / sizeof(ctl_profiles[0]); i++) {
		if (ctl_profiles[i].id == id) {
			return &ctl_profiles[i];
		}
	}
	return NULL;
}

/* Reason 9 on one slot: its exponent bits all ones, an infinity or a NaN.
 * Subnormals and -0.0 are finite. No <math.h>. */
static int ctl_nonfinite(const uint8_t *p, unsigned off)
{
	return ((get_u32_le(&p[off]) >> 23) & 0xFFu) == 0xFFu;
}

/* Reason 10 on one optional slot: its flag clear and a byte of it non-zero
 * (-0.0, 0x80000000, is not all zero bytes). */
static int ctl_undefined_nonzero(const uint8_t *p, uint8_t f, uint8_t bit, unsigned off)
{
	return !(f & bit) && any_nonzero(&p[off], 4u);
}

/* Kind 2 (the Phase 8 specification, section 2.3). Reasons in the order 10, 8,
 * 9, 11, 12, ..., 19; the first failure wins. Comparisons are strict, so a
 * value exactly at a limit is accepted; f32 values are widened to double
 * exactly before any arithmetic. Stateless: the verdict is a function of the
 * payload and the compiled table only. A rule whose flag is clear is skipped.
 *
 *   10 flags-invalid     b4..b7; a byte of [8..23]; [47]; an undefined slot
 *                        (acceleration without b0, jerk without b1, steering
 *                        rate without b2, v_meas without b3) not all zero bytes
 *   8  profile-unbound   payload[1] is no compiled profile
 *   9  field-not-finite  v_cmd, delta or a defined optional slot non-finite
 *   11 ctl-interval      [45..46] > VSS_CTL_DT_MAX_MS
 *   12 ctl-speed         |v_cmd| > v_max
 *   13 ctl-accel         b0 and |a| > a_max
 *   14 ctl-jerk          b1 and |j| > jerk_max
 *   15 ctl-steer         |delta| > steer_max
 *   16 ctl-steer-rate    b2 and |rate| > steer_rate_max
 *   17 ctl-lat-accel     b3 and v_meas * v_meas * tan(|delta|) / L_m >
 *                        lat_acc_max + VSS_CTL_TOL17, in double in that order,
 *                        tan = vss_tan() (rule 15 keeps |delta| <= steer_max
 *                        <= 1.0 rad, its domain), L_m = l_mm * VSS_M_PER_MM
 *   18 ctl-overspeed     b3 and |v_meas| > VSS_CTL_OVERSPEED_FACTOR * |v_cmd|
 *                        + VSS_CTL_OVERSPEED_MARGIN
 *   19 ctl-rolling-back  b3 and v_meas < -VSS_CTL_ROLLBACK_V and v_cmd >= 0
 *
 * Every value but |delta| is read before the rules, a non-finite one too
 * (reading it into a double traps nothing); none reaches arithmetic before rule
 * 9 has passed, and |delta| is taken right after it. */
static uint8_t check_ctl(const uint8_t *p, uint8_t *reason)
{
	uint8_t const f = p[P_CTL_FLAGS];
	double const v_cmd = f32_at(p, P_CTL_V_CMD);
	double const a = f32_at(p, P_CTL_ACCEL);
	double const j = f32_at(p, P_CTL_JERK);
	double const rate = f32_at(p, P_CTL_RATE);
	double const v_meas = f32_at(p, P_CTL_V_MEAS);
	double ad;
	const struct ctl_profile *pr;

	/* 10 */
	if ((f & CF_RESERVED) || any_nonzero(&p[P_CTL_STAMP], 16u) || p[P_CTL_RESERVED] != 0u
	    || ctl_undefined_nonzero(p, f, CF_ACCEL, P_CTL_ACCEL) || ctl_undefined_nonzero(p, f, CF_JERK, P_CTL_JERK)
	    || ctl_undefined_nonzero(p, f, CF_RATE, P_CTL_RATE)
	    || ctl_undefined_nonzero(p, f, CF_ODOM, P_CTL_V_MEAS)) {
		*reason = RSN_FLAGS_INVALID;
		return V_REJECT;
	}
	/* 8 */
	pr = ctl_profile_find(p[P_CTL_PROFILE]);
	if (pr == NULL) {
		*reason = RSN_PROFILE_UNBOUND;
		return V_REJECT;
	}
	/* 9 */
	if (ctl_nonfinite(p, P_CTL_V_CMD) || ctl_nonfinite(p, P_CTL_DELTA)
	    || ((f & CF_ACCEL) && ctl_nonfinite(p, P_CTL_ACCEL)) || ((f & CF_JERK) && ctl_nonfinite(p, P_CTL_JERK))
	    || ((f & CF_RATE) && ctl_nonfinite(p, P_CTL_RATE)) || ((f & CF_ODOM) && ctl_nonfinite(p, P_CTL_V_MEAS))) {
		*reason = RSN_NOT_FINITE;
		return V_REJECT;
	}
	ad = dabs(f32_at(p, P_CTL_DELTA));  /* after 9: a NaN never reaches dabs() */
	/* 11 */
	if ((unsigned)get_u16_le(&p[P_CTL_INTERVAL]) > VSS_CTL_DT_MAX_MS) {
		*reason = RSN_CTL_INTERVAL;
		return V_REJECT;
	}
	/* 12 */
	if (dabs(v_cmd) > pr->v_max) {
		*reason = RSN_CTL_SPEED;
		return V_REJECT;
	}
	/* 13 */
	if ((f & CF_ACCEL) && dabs(a) > pr->a_max) {
		*reason = RSN_CTL_ACCEL;
		return V_REJECT;
	}
	/* 14 */
	if ((f & CF_JERK) && dabs(j) > pr->jerk_max) {
		*reason = RSN_CTL_JERK;
		return V_REJECT;
	}
	/* 15 */
	if (ad > pr->steer_max) {
		*reason = RSN_CTL_STEER;
		return V_REJECT;
	}
	/* 16 */
	if ((f & CF_RATE) && dabs(rate) > pr->steer_rate_max) {
		*reason = RSN_CTL_STEER_RATE;
		return V_REJECT;
	}
	/* 17 */
	if ((f & CF_ODOM)
	    && v_meas * v_meas * vss_tan(ad) / ((double)pr->l_mm * VSS_M_PER_MM) > pr->lat_acc_max + VSS_CTL_TOL17) {
		*reason = RSN_CTL_LAT_ACCEL;
		return V_REJECT;
	}
	/* 18 */
	if ((f & CF_ODOM) && dabs(v_meas) > VSS_CTL_OVERSPEED_FACTOR * dabs(v_cmd) + VSS_CTL_OVERSPEED_MARGIN) {
		*reason = RSN_CTL_OVERSPEED;
		return V_REJECT;
	}
	/* 19 */
	if ((f & CF_ODOM) && v_meas < -VSS_CTL_ROLLBACK_V && v_cmd >= 0.0) {
		*reason = RSN_CTL_ROLLING_BACK;
		return V_REJECT;
	}

	*reason = RSN_OK;
	return V_ACCEPT;
}
#endif

/* Returns the verdict, and sets *reason. */
static uint8_t check_claim(const uint8_t *payload, uint8_t *reason)
{
	switch (payload[P_KIND]) {
	case KIND_MNIST: return check_mnist(payload, reason);
	case KIND_VLM:   return check_vlm(payload, reason);
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	case KIND_VSS:   return check_vss(payload, reason);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	case KIND_CTL:   return check_ctl(payload, reason);
#endif
	default:
		*reason = RSN_KIND_UNKNOWN;
		return V_REJECT;
	}
}

static const char *reason_name(uint8_t r)
{
	switch (r) {
	case RSN_OK:            return "ok";
	case RSN_CLASS_RANGE:   return "class-out-of-range";
	case RSN_CONF_RANGE:    return "confidence-not-a-percentage";
	case RSN_CONF_LOW:      return "confidence-below-threshold";
	case RSN_INFER_IMPLAUS: return "inference-time-implausible";
	case RSN_KIND_UNKNOWN:  return "claim-kind-unknown";
	case RSN_MODEL_UNBOUND: return "vlm-model-unbounded";
	case RSN_TIME_INCONSIST: return "vlm-time-inconsistent";
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	case RSN_PROFILE_UNBOUND: return "profile-unbound";
	case RSN_NOT_FINITE:      return "field-not-finite";
	case RSN_FLAGS_INVALID:   return "flags-invalid";
	case RSN_VSS_CATALOG:     return "vss-catalog-mismatch";
	case RSN_VSS_STALE:       return "vss-stale";
	case RSN_VSS_SPEED:       return "vss-speed";
	case RSN_VSS_ACCEL:       return "vss-accel";
	case RSN_VSS_STEER:       return "vss-steer";
	case RSN_VSS_YAW:         return "vss-yaw-inconsistent";
	case RSN_VSS_GEAR:        return "vss-gear-direction";
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	case RSN_CTL_INTERVAL:     return "ctl-interval";
	case RSN_CTL_SPEED:        return "ctl-speed";
	case RSN_CTL_ACCEL:        return "ctl-accel";
	case RSN_CTL_JERK:         return "ctl-jerk";
	case RSN_CTL_STEER:        return "ctl-steer";
	case RSN_CTL_STEER_RATE:   return "ctl-steer-rate";
	case RSN_CTL_LAT_ACCEL:    return "ctl-lat-accel";
	case RSN_CTL_OVERSPEED:    return "ctl-overspeed";
	case RSN_CTL_ROLLING_BACK: return "ctl-rolling-back";
#endif
	default:              return "unknown";
	}
}

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
/* THE STARTUP SELF-CHECK (wire specification 4.3). FNV-1 32 -- multiply, then
 * xor; not FNV-1a -- the hash vss-tools uses for staticUIDs and the generator
 * for VSS_CATALOG_DIGEST. */
static uint32_t vss_fnv1_32(const uint8_t *b, size_t n)
{
	uint32_t h = 0x811C9DC5u;
	size_t i;

	for (i = 0; i < n; i++) {
		h *= 0x01000193u;
		h ^= b[i];
	}
	return h;
}

/* The catalogue digest of five UIDs: each serialised as four little-endian
 * bytes BY SHIFTS, in slot order, as the generator does -- never by copying a
 * uint32_t, which would follow the host's byte order. */
static uint32_t vss_uids_digest(const uint32_t uid[5])
{
	uint8_t b[20];
	unsigned i;

	for (i = 0; i < 5u; i++) {
		b[4u * i + 0u] = (uint8_t)((uid[i] >> 0) & 0xFFu);
		b[4u * i + 1u] = (uint8_t)((uid[i] >> 8) & 0xFFu);
		b[4u * i + 2u] = (uint8_t)((uid[i] >> 16) & 0xFFu);
		b[4u * i + 3u] = (uint8_t)((uid[i] >> 24) & 0xFFu);
	}
	return vss_fnv1_32(b, sizeof(b));
}

/* 1 when the compiled VSS_CATALOG_DIGEST is the digest of the compiled UIDs.
 * main() refuses to serve otherwise (exit 2), so an image built from a
 * hand-edited vss_contract.h never listens. */
static int vss_contract_consistent(void)
{
	uint32_t const uid[5] = { VSS_UID_SLOT0, VSS_UID_SLOT1, VSS_UID_SLOT2, VSS_UID_SLOT3, VSS_UID_SLOT4 };

	return vss_uids_digest(uid) == (uint32_t)VSS_CATALOG_DIGEST;
}

/* The announcement (wire specification 12): right after the claim kinds line,
 * in every serving mode, the rules this build judges kind 4 by. The profile
 * lines and the id list come from the compiled table itself. Every format is a
 * literal: a profile's a_y bound is formatted into its own buffer first. */
static void vss_announce(void)
{
	char ids[4u * 256u];
	size_t n = 0, i;

	ids[0] = '\0';
	for (i = 0; i < sizeof(vss_profiles) / sizeof(vss_profiles[0]); i++) {
		int const k = snprintf(ids + n, sizeof(ids) - n, "%s%u", n != 0u ? " " : "", (unsigned)vss_profiles[i].id);

		if (k < 0 || (size_t)k >= sizeof(ids) - n) {
			break;  /* cannot happen: at most 255 ids of at most 4 characters */
		}
		n += (size_t)k;
	}
	printf("monitor: vss rules: kind 4, catalog 0x%08X (vss %s), age_max %u ms, profiles %s\n",
	       (unsigned)VSS_CATALOG_DIGEST, VSS_CATALOG_VERSION, (unsigned)VSS_AGE_MAX_MS, ids);
	for (i = 0; i < sizeof(vss_profiles) / sizeof(vss_profiles[0]); i++) {
		const struct vss_profile *pr = &vss_profiles[i];
		char ay[32];
		const char *ay_max = "none";

		if (pr->ay26_max != 0.0) {
			snprintf(ay, sizeof(ay), "%g m/s^2", pr->ay26_max);
			ay_max = ay;
		}
		printf("monitor: vss profile %u: L %u mm, v_max %g m/s, a_max %g m/s^2, steer_max %g deg, "
		       "yaw check %g..%g m/s ay_max %s tol %g deg/s, gear v_tol %g m/s\n",
		       (unsigned)pr->id, (unsigned)pr->l_mm, pr->v_max, pr->a_max, pr->delta_max,
		       pr->v26_lo, pr->v26_hi, ay_max, pr->tol26, pr->v_tol);
	}
	fflush(stdout);
}

/* THE KIND 4 CONSOLE LIMITER (wire specification 12; Phase 2 design decision
 * a; the cap decided by the owner on 2026-10-01). Kind 4 only: kinds 0 and 1
 * and every unknown kind still print one line per reject.
 *
 *   1. A kind 4 REJECT line is printed only when its reason differs from the
 *      previous kind 4 frame's reason, an ACCEPT counting as reason 0.
 *   2. Buckets are one-second windows of CLOCK_MONOTONIC (now / 1 s). A bucket
 *      in which a line was suppressed gets one summary line, printed when the
 *      first kind 4 frame of a later bucket arrives, or by the session-end
 *      flush just before the transport's done:/quiet:/burst: line.
 *   3. At most VSS_LOG_CAP individual lines per bucket; the rest are counted
 *      into the summary, never lost.
 *   4. The summary's seen, rejected and suppressed are the bucket's own, and
 *      `by reason:` counts its suppressed lines, so lines + suppressed =
 *      rejected in every bucket. The session-end flush, vss_log_end(), prints
 *      a pending summary and resets everything -- rule 1's previous reason and
 *      the line count too -- so each session's first kind 4 reject prints.
 *
 * Process-global and unlocked: every transport here judges from one thread.
 * someip.c judges from two, and never defines the switch; a build of it that
 * did would need a lock, and its own binary name (wire specification 11). */
#define VSS_LOG_CAP        11u                  /* lines per bucket: the designed 10 Hz, plus one */
#define VSS_LOG_BUCKET_NS  1000000000ull        /* the summary interval, 1 s */
#define VSS_LOG_REASONS    32u                  /* by_reason[] covers the reason bytes 0..31 */
_Static_assert(RSN_PROFILE_UNBOUND < VSS_LOG_REASONS && RSN_NOT_FINITE < VSS_LOG_REASONS
               && RSN_FLAGS_INVALID < VSS_LOG_REASONS && RSN_VSS_CATALOG < VSS_LOG_REASONS
               && RSN_VSS_STALE < VSS_LOG_REASONS && RSN_VSS_SPEED < VSS_LOG_REASONS
               && RSN_VSS_ACCEL < VSS_LOG_REASONS && RSN_VSS_STEER < VSS_LOG_REASONS
               && RSN_VSS_YAW < VSS_LOG_REASONS && RSN_VSS_GEAR < VSS_LOG_REASONS,
               "every reason check_vss() gives indexes by_reason[]");

struct vss_log {
	uint64_t bucket;                /* the open bucket, now / VSS_LOG_BUCKET_NS */
	int open;                       /* a kind 4 frame has opened it in this session */
	uint8_t prev;                   /* rule 1: the previous kind 4 frame's reason, an ACCEPT 0 */
	unsigned lines;                 /* rule 3: individual lines printed in the open bucket */
	unsigned long long seen, rejected, suppressed;          /* the open bucket's own */
	unsigned long long by_reason[VSS_LOG_REASONS];          /* its suppressed lines, by reason */
};

/* All zero is a session's start: no bucket open, previous reason 0. */
static struct vss_log g_vss_log;

/* The open bucket's summary line, if a line was suppressed in it. */
static void vss_log_summary(const struct vss_log *lg)
{
	char list[VSS_LOG_REASONS * 26u];       /* " %u=%llu" is at most 24 characters */
	size_t n = 0;
	unsigned r;

	if (lg->suppressed == 0u) {
		return;
	}
	list[0] = '\0';
	for (r = 0; r < VSS_LOG_REASONS; r++) {
		if (lg->by_reason[r] != 0u) {
			int const k = snprintf(list + n, sizeof(list) - n, " %u=%llu", r, lg->by_reason[r]);

			if (k < 0 || (size_t)k >= sizeof(list) - n) {
				break;  /* cannot happen: the buffer holds every entry */
			}
			n += (size_t)k;
		}
	}
	printf("monitor: vss summary: seen=%llu rejected=%llu suppressed=%llu by reason:%s\n",
	       lg->seen, lg->rejected, lg->suppressed, list);
	fflush(stdout);
}

/* One judged kind 4 frame (buf holds its verdict and reason already), at `now`
 * on CLOCK_MONOTONIC. `now` is a parameter so tests/vss_driver.c can script it. */
static void vss_log(struct vss_log *lg, const uint8_t *buf, uint8_t reason, uint64_t now)
{
	uint64_t const bucket = now / VSS_LOG_BUCKET_NS;

	if (!lg->open || bucket != lg->bucket) {
		uint8_t const prev = lg->prev;

		vss_log_summary(lg);
		memset(lg, 0, sizeof(*lg));
		lg->prev = prev;                /* rule 1 runs on across buckets */
		lg->bucket = bucket;
		lg->open = 1;
	}
	lg->seen++;
	if (reason != RSN_OK) {
		lg->rejected++;
		if (reason != lg->prev && lg->lines < VSS_LOG_CAP) {
			lg->lines++;
			printf("monitor: REJECT seq=%llu kind=vss profile=%u reason=%s\n",
			       (unsigned long long)frame_get_u64(&buf[0]),
			       (unsigned)buf[FRAME_HEADER_BYTES + P_VSS_PROFILE], reason_name(reason));
			fflush(stdout);
		} else {
			lg->suppressed++;
			lg->by_reason[reason]++;        /* below VSS_LOG_REASONS: asserted above */
		}
	}
	lg->prev = reason;
}

/* The session-end flush hook: called immediately before each transport's
 * client done:, udp done:, shm quiet:, shm done:, shm-kick burst: and shm-kick
 * done: line, all of which stay byte-identical. */
static void vss_log_end(struct vss_log *lg)
{
	vss_log_summary(lg);
	memset(lg, 0, sizeof(*lg));
}
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
/* KIND 2'S STARTUP SELF-CHECK (the Phase 8 specification, section 2.4): the
 * digest of the seven slot UIDs, each serialised as four little-endian bytes BY
 * SHIFTS, in slot order, hashed with vss_fnv1_32() -- never by copying a
 * uint32_t, which would follow the host's byte order. */
static uint32_t ctl_uids_digest(const uint32_t uid[7])
{
	uint8_t b[28];
	unsigned i;

	for (i = 0; i < 7u; i++) {
		b[4u * i + 0u] = (uint8_t)((uid[i] >> 0) & 0xFFu);
		b[4u * i + 1u] = (uint8_t)((uid[i] >> 8) & 0xFFu);
		b[4u * i + 2u] = (uint8_t)((uid[i] >> 16) & 0xFFu);
		b[4u * i + 3u] = (uint8_t)((uid[i] >> 24) & 0xFFu);
	}
	return vss_fnv1_32(b, sizeof(b));
}

/* 1 when the compiled VSS_CTL_DIGEST is the digest of the compiled UIDs and
 * every compiled profile has 0 < steer_max <= 1.0 rad, which keeps rule 17's
 * vss_tan() inside its domain (rule 15 runs first) -- the invariant the Python
 * loader of the same contract refuses to load without -- an l_mm above 0,
 * which rule 17 divides by, and an id no other row has, as ctl_profile_find()
 * finds only the first. main() refuses to serve otherwise (exit 2), so an image
 * built from a hand-edited vss_ctl.h never listens. */
static int ctl_contract_consistent(void)
{
	uint32_t const uid[7] = { VSS_CTL_UID_SLOT0, VSS_CTL_UID_SLOT1, VSS_CTL_UID_SLOT2, VSS_CTL_UID_SLOT3,
	                          VSS_CTL_UID_SLOT4, VSS_CTL_UID_SLOT5, VSS_CTL_UID_SLOT6 };
	size_t i, j;

	if (ctl_uids_digest(uid) != (uint32_t)VSS_CTL_DIGEST) {
		return 0;
	}
	for (i = 0; i < sizeof(ctl_profiles) / sizeof(ctl_profiles[0]); i++) {
		if (!(ctl_profiles[i].steer_max > 0.0 && ctl_profiles[i].steer_max <= 1.0)) {
			return 0;
		}
		if (ctl_profiles[i].l_mm == 0u) {
			return 0;
		}
		for (j = 0; j < i; j++) {
			if (ctl_profiles[j].id == ctl_profiles[i].id) {
				return 0;
			}
		}
	}
	return 1;
}

/* The announcement (the Phase 8 specification, section 2.5): right after the
 * vss rules: and vss profile lines, in every serving mode, the rules this build
 * judges kind 2 by. The profile lines and the id list come from the compiled
 * table itself. Neither line contains "claim kinds:", which the harnesses grep. */
static void ctl_announce(void)
{
	char ids[4u * 256u];
	size_t n = 0, i;

	ids[0] = '\0';
	for (i = 0; i < sizeof(ctl_profiles) / sizeof(ctl_profiles[0]); i++) {
		int const k = snprintf(ids + n, sizeof(ids) - n, "%s%u", n != 0u ? " " : "", (unsigned)ctl_profiles[i].id);

		if (k < 0 || (size_t)k >= sizeof(ids) - n) {
			break;  /* cannot happen: at most 255 ids of at most 4 characters */
		}
		n += (size_t)k;
	}
	printf("monitor: ctl rules: kind 2, catalog 0x%08X (vss %s), dt_max %u ms, overspeed %g x v_cmd + %g m/s, "
	       "rollback %g m/s, tol17 %g m/s^2, profiles %s\n",
	       (unsigned)VSS_CTL_DIGEST, VSS_CATALOG_VERSION, (unsigned)VSS_CTL_DT_MAX_MS,
	       (double)VSS_CTL_OVERSPEED_FACTOR, (double)VSS_CTL_OVERSPEED_MARGIN, (double)VSS_CTL_ROLLBACK_V,
	       (double)VSS_CTL_TOL17, ids);
	for (i = 0; i < sizeof(ctl_profiles) / sizeof(ctl_profiles[0]); i++) {
		const struct ctl_profile *pr = &ctl_profiles[i];

		printf("monitor: ctl profile %u: L %u mm, v_max %g m/s, a_max %g m/s^2, jerk_max %g m/s^3, steer_max %g rad, "
		       "steer_rate_max %g rad/s, lat_acc_max %g m/s^2\n",
		       (unsigned)pr->id, (unsigned)pr->l_mm, pr->v_max, pr->a_max, pr->jerk_max, pr->steer_max,
		       pr->steer_rate_max, pr->lat_acc_max);
	}
	fflush(stdout);
}

/* THE KIND 2 CONSOLE LIMITER (the Phase 8 specification, section 2.5; design
 * point a, D6): kind 4's four rules (vss_log(), above) with a state of its own
 * and a cap of its own, so kind 4's lines and kinds 0, 1 and every unknown
 * kind's stay as they are.
 *
 *   1. A kind 2 REJECT line is printed only when its reason differs from the
 *      previous kind 2 frame's reason, an ACCEPT counting as reason 0.
 *   2. Buckets are one-second windows of CLOCK_MONOTONIC (now / 1 s). A bucket
 *      in which a line was suppressed gets one summary line, printed when the
 *      first kind 2 frame of a later bucket arrives, or by the session-end
 *      flush just before the transport's done:/quiet:/burst: line.
 *   3. At most CTL_LOG_CAP individual lines per bucket; the rest are counted
 *      into the summary, never lost.
 *   4. The summary's seen, rejected and suppressed are the bucket's own, and
 *      `by reason:` counts its suppressed lines, so lines + suppressed =
 *      rejected in every bucket. The session-end flush, ctl_log_end(), prints
 *      a pending summary and resets everything, so each session's first kind 2
 *      reject prints.
 *
 * Process-global and unlocked, as kind 4's: every transport here judges from
 * one thread. */
#define CTL_LOG_CAP        34u                  /* lines per bucket: the control rate plus one (D6) */
#define CTL_LOG_BUCKET_NS  1000000000ull        /* the summary interval, 1 s */
#define CTL_LOG_REASONS    32u                  /* by_reason[] covers the reason bytes 0..31 */
_Static_assert(RSN_PROFILE_UNBOUND < CTL_LOG_REASONS && RSN_NOT_FINITE < CTL_LOG_REASONS
               && RSN_FLAGS_INVALID < CTL_LOG_REASONS && RSN_CTL_INTERVAL < CTL_LOG_REASONS
               && RSN_CTL_SPEED < CTL_LOG_REASONS && RSN_CTL_ACCEL < CTL_LOG_REASONS
               && RSN_CTL_JERK < CTL_LOG_REASONS && RSN_CTL_STEER < CTL_LOG_REASONS
               && RSN_CTL_STEER_RATE < CTL_LOG_REASONS && RSN_CTL_LAT_ACCEL < CTL_LOG_REASONS
               && RSN_CTL_OVERSPEED < CTL_LOG_REASONS && RSN_CTL_ROLLING_BACK < CTL_LOG_REASONS,
               "every reason check_ctl() gives indexes by_reason[]");

struct ctl_log {
	uint64_t bucket;                /* the open bucket, now / CTL_LOG_BUCKET_NS */
	int open;                       /* a kind 2 frame has opened it in this session */
	uint8_t prev;                   /* rule 1: the previous kind 2 frame's reason, an ACCEPT 0 */
	unsigned lines;                 /* rule 3: individual lines printed in the open bucket */
	unsigned long long seen, rejected, suppressed;          /* the open bucket's own */
	unsigned long long by_reason[CTL_LOG_REASONS];          /* its suppressed lines, by reason */
};

/* All zero is a session's start: no bucket open, previous reason 0. */
static struct ctl_log g_ctl_log;

/* The open bucket's summary line, if a line was suppressed in it. */
static void ctl_log_summary(const struct ctl_log *lg)
{
	char list[CTL_LOG_REASONS * 26u];       /* " %u=%llu" is at most 24 characters */
	size_t n = 0;
	unsigned r;

	if (lg->suppressed == 0u) {
		return;
	}
	list[0] = '\0';
	for (r = 0; r < CTL_LOG_REASONS; r++) {
		if (lg->by_reason[r] != 0u) {
			int const k = snprintf(list + n, sizeof(list) - n, " %u=%llu", r, lg->by_reason[r]);

			if (k < 0 || (size_t)k >= sizeof(list) - n) {
				break;  /* cannot happen: the buffer holds every entry */
			}
			n += (size_t)k;
		}
	}
	printf("monitor: ctl summary: seen=%llu rejected=%llu suppressed=%llu by reason:%s\n",
	       lg->seen, lg->rejected, lg->suppressed, list);
	fflush(stdout);
}

/* One judged kind 2 frame (buf holds its verdict and reason already), at `now`
 * on CLOCK_MONOTONIC. `now` is a parameter so tests/ctl_driver.c can script it.
 * check_ctl() gives only reasons below CTL_LOG_REASONS (asserted above). */
static void ctl_log(struct ctl_log *lg, const uint8_t *buf, uint8_t reason, uint64_t now)
{
	uint64_t const bucket = now / CTL_LOG_BUCKET_NS;

	if (!lg->open || bucket != lg->bucket) {
		uint8_t const prev = lg->prev;

		ctl_log_summary(lg);
		memset(lg, 0, sizeof(*lg));
		lg->prev = prev;                /* rule 1 runs on across buckets */
		lg->bucket = bucket;
		lg->open = 1;
	}
	lg->seen++;
	if (reason != RSN_OK) {
		lg->rejected++;
		if (reason != lg->prev && lg->lines < CTL_LOG_CAP) {
			lg->lines++;
			printf("monitor: REJECT seq=%llu kind=ctl profile=%u reason=%s\n",
			       (unsigned long long)frame_get_u64(&buf[0]),
			       (unsigned)buf[FRAME_HEADER_BYTES + P_CTL_PROFILE], reason_name(reason));
			fflush(stdout);
		} else {
			lg->suppressed++;
			lg->by_reason[reason]++;
		}
	}
	lg->prev = reason;
}

/* The session-end flush hook: called immediately before each transport's
 * session-end line, right before vss_log_end(), so a kind 2 summary comes
 * first. */
static void ctl_log_end(struct ctl_log *lg)
{
	ctl_log_summary(lg);
	memset(lg, 0, sizeof(*lg));
}
#endif

/* Judge one non-sentinel frame in place: write verdict and reason into the
 * payload, log a reject. Shared by every transport. Returns the verdict. */
static uint8_t judge_frame(uint8_t *buf)
{
	uint8_t reason = RSN_OK;
	uint8_t const verdict = check_claim(&buf[FRAME_HEADER_BYTES], &reason);

	buf[FRAME_HEADER_BYTES + P_VERDICT] = verdict;
	buf[FRAME_HEADER_BYTES + P_REASON]  = reason;

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	/* Kind 4 goes to its limiter, accepted or not (rule 1 counts an ACCEPT),
	 * with the one clock read the limiter needs. The kind is compared first,
	 * so kinds 0 and 1 read no clock. */
	if (buf[FRAME_HEADER_BYTES + P_KIND] == KIND_VSS) {
		vss_log(&g_vss_log, buf, reason, now_ns());
		return verdict;
	}
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	/* Kind 2 goes to its own limiter in the same way, never to the generic
	 * line below; kinds 0 and 1 still read no clock. */
	if (buf[FRAME_HEADER_BYTES + P_KIND] == KIND_CTL) {
		ctl_log(&g_ctl_log, buf, reason, now_ns());
		return verdict;
	}
#endif
	if (verdict != V_ACCEPT) {
		/* Log only rejects: an accepted frame is the common case and
		 * flooding the console would itself be a hazard on a
		 * serial-consoled guest. The mnist line is byte-for-byte the
		 * 2026-09-18 one, so that console record still reads the same. */
		uint8_t const *p = &buf[FRAME_HEADER_BYTES];
		unsigned long long const seq = (unsigned long long)frame_get_u64(&buf[0]);
		if (p[P_KIND] == KIND_MNIST) {
			printf("monitor: REJECT seq=%llu class=%u conf=%u us=%u reason=%s\n",
			       seq, p[P_CLASS], p[P_CONF], get_u32_le(&p[P_INFER_US]),
			       reason_name(reason));
		} else if (p[P_KIND] == KIND_VLM) {
			printf("monitor: REJECT seq=%llu kind=vlm model=%u class=%u conf=%u us=%u reason=%s\n",
			       seq, p[P_VLM_MODEL], p[P_CLASS], p[P_CONF], get_u32_le(&p[P_INFER_US]),
			       reason_name(reason));
		} else {
			printf("monitor: REJECT seq=%llu kind=%u reason=%s\n",
			       seq, p[P_KIND], reason_name(reason));
		}
		fflush(stdout);
	}
	return verdict;
}

/* stamp (OD15): write t_in and t_out into payload[8..23] of every claim's reply
 * -- the only case in which a reply byte other than [6] and [7] is written.
 * With stamp == 0 this is the original TCP loop, plus two tests per frame. */
static int serve_one_client(int cfd, int stamp)
{
	uint8_t buf[FRAME_TOTAL_BYTES];
	unsigned long long seen = 0, accepted = 0, rejected = 0;

	for (;;) {
		uint64_t t_in = 0;

		if (g_stop) {
			break;
		}
		int const rc = frameio_read_frame(cfd, buf);
		if (stamp) {
			t_in = now_ns();
		}
		if (rc > 0) {
			break;      /* clean EOF: the client finished and hung up */
		}
		if (rc < 0) {
			/* Short read mid-frame or a socket error. Distinguished
			 * from EOF on purpose: a truncated frame is a protocol
			 * fault, and silently treating it as a polite disconnect
			 * would hide exactly the kind of fault this program
			 * exists to notice. */
			fprintf(stderr, "monitor: frame read failed: %s\n",
			        strerror(errno));
			break;
		}

		/* A sentinel is a keepalive carrying no claim. Echo it untouched
		 * and never count it -- treating it as a claim would invent a
		 * verdict about data that was never sent. */
		if (frame_get_u64(&buf[0]) == FRAME_SENTINEL_SEQ) {
			if (frameio_write_frame(cfd, buf) != 0) {
				break;
			}
			continue;
		}

		seen++;
		if (judge_frame(buf) == V_ACCEPT) {
			accepted++;
		} else {
			rejected++;
		}

		if (stamp) {
			frame_put_u64(&buf[FRAME_HEADER_BYTES + P_T_IN], t_in);
			frame_put_u64(&buf[FRAME_HEADER_BYTES + P_T_OUT], now_ns());
		}
		if (frameio_write_frame(cfd, buf) != 0) {
			break;
		}
	}

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	ctl_log_end(&g_ctl_log);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	vss_log_end(&g_vss_log);
#endif
	printf("monitor: client done: seen=%llu accepted=%llu rejected=%llu\n",
	       seen, accepted, rejected);
	fflush(stdout);
	return 0;
}

/* UDP: one frame per datagram, the reply to the sender's address. The receive
 * buffer is larger than a frame on purpose -- an oversize datagram must be SEEN
 * as oversize and dropped, not silently truncated to 64 bytes and answered. */
static int serve_udp(int port)
{
	struct sockaddr_in addr;
	uint8_t buf[2048];
	unsigned long long seen = 0, accepted = 0, rejected = 0, dropped = 0;
	int fd = socket(AF_INET, SOCK_DGRAM, 0);

	if (fd < 0) {
		fprintf(stderr, "monitor: socket(udp): %s\n", strerror(errno));
		return 1;
	}
	memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_addr.s_addr = htonl(INADDR_ANY);
	addr.sin_port = htons((uint16_t)port);
	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
		fprintf(stderr, "monitor: bind(%d/udp): %s\n", port, strerror(errno));
		close(fd);
		return 1;
	}

	printf("monitor: safety monitor listening on :%d/udp (frame=%u bytes, conf_min=%u%%)\n",
	       port, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN);
	fflush(stdout);

	while (!g_stop) {
		struct sockaddr_in peer;
		socklen_t plen = sizeof(peer);
		ssize_t const n = recvfrom(fd, buf, sizeof(buf), 0,
		                           (struct sockaddr *)&peer, &plen);
		if (n < 0) {
			if (errno == EINTR) {
				continue;
			}
			fprintf(stderr, "monitor: recvfrom: %s\n", strerror(errno));
			break;
		}
		if (n != (ssize_t)FRAME_TOTAL_BYTES) {
			dropped++;
			continue;
		}
		if (frame_get_u64(&buf[0]) != FRAME_SENTINEL_SEQ) {
			seen++;
			if (judge_frame(buf) == V_ACCEPT) {
				accepted++;
			} else {
				rejected++;
			}
		}
		if (sendto(fd, buf, FRAME_TOTAL_BYTES, 0, (struct sockaddr *)&peer, plen)
		    != (ssize_t)FRAME_TOTAL_BYTES) {
			fprintf(stderr, "monitor: sendto: %s\n", strerror(errno));
		}
	}

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	ctl_log_end(&g_ctl_log);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	vss_log_end(&g_vss_log);
#endif
	printf("monitor: udp done: seen=%llu accepted=%llu rejected=%llu dropped=%llu\n",
	       seen, accepted, rejected, dropped);
	fflush(stdout);
	close(fd);
	return 0;
}

/* "NAME@OFFSET" -> NAME in `name`, OFFSET in *off (0 when there is none).
 * Pure string work, so it stays in the shared source. */
static int split_spec(const char *spec, char *name, size_t name_len, size_t *off)
{
	const char *at = strrchr(spec, '@');
	size_t n = at ? (size_t)(at - spec) : strlen(spec);
	char *end = NULL;

	if (n == 0u || n >= name_len) {
		return -1;
	}
	memcpy(name, spec, n);
	name[n] = '\0';
	*off = 0u;
	if (at != NULL) {
		unsigned long long v;
		/* strtoull() takes a sign and wraps it: "-4096" would become a huge
		 * multiple of 64 that passes every later check (FOUND BY CODE REVIEW). */
		if (at[1] < '0' || at[1] > '9') {
			return -1;
		}
		v = strtoull(at + 1, &end, 0);
		if (end == at + 1 || *end != '\0' || (v % SHM_CHAN_LINE) != 0u || v > (1ull << 40)) {
			return -1;
		}
		*off = (size_t)v;
	}
	return 0;
}

#define SHM_SPIN_NS  50000000ull   /* keep spinning this long after a request */
#define SHM_IDLE_NS  10000000L     /* then look this often */
#define SHM_SPIN_CHECK 4096u       /* spins between clock reads */

static uint64_t now_ns(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

/* Shared memory: one request outstanding, answered in place (shm_chan.h). */
static int serve_shm(const char *spec)
{
	uint8_t buf[FRAME_TOTAL_BYTES];
	unsigned long long seen = 0, accepted = 0, rejected = 0, jumps = 0;
	unsigned long long seen_at_quiet = 0;
	char what[320], name[256];
	size_t len = 0, off = 0;
	uint64_t last, active;
	unsigned spins = 0;
	int quiet = 1;
	void *base;

	if (split_spec(spec, name, sizeof(name), &off) != 0) {
		fprintf(stderr, "monitor: bad shm spec '%s' (NAME or NAME@OFFSET, OFFSET a multiple of %u)\n",
		        spec, (unsigned)SHM_CHAN_LINE);
		return 2;
	}
	base = shm_map(name, &len, what, sizeof(what));
	if (base == NULL) {
		return 1;
	}
	if (off > len || len - off < SHM_CHAN_MIN_BYTES) {
		fprintf(stderr, "monitor: slot @%zu does not fit a %zu-byte region\n", off, len);
		return 1;
	}
	base = (uint8_t *)base + off;
	if (off != 0u) {
		size_t const l = strlen(what);
		snprintf(what + l, sizeof(what) - l, ", slot @%zu", off);
	}

	/* Take the slot over. Not serving (magic 0) while it is set up; a
	 * request left in it from before this server started is NOT answered --
	 * its client is gone, and answering would hand a later client a reply to
	 * a frame it never sent. */
	__atomic_store_n(shm_chan_u32(base, SHM_CHAN_OFF_MAGIC), 0u, __ATOMIC_RELEASE);
	last = shm_chan_load(base, SHM_CHAN_OFF_REQ_SEQ);
	shm_chan_store(base, SHM_CHAN_OFF_RSP_SEQ, last);
	*shm_chan_u32(base, SHM_CHAN_OFF_VERSION) = SHM_CHAN_VERSION;
	__atomic_store_n(shm_chan_u32(base, SHM_CHAN_OFF_MAGIC), SHM_CHAN_MAGIC, __ATOMIC_RELEASE);

	printf("monitor: safety monitor serving shm on %s (frame=%u bytes, conf_min=%u%%)\n",
	       what, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN);
	fflush(stdout);

	active = now_ns();
	while (!g_stop) {
		uint64_t const cur = shm_chan_load(base, SHM_CHAN_OFF_REQ_SEQ);

		if (cur == last) {
			shm_chan_relax();
			if (++spins < SHM_SPIN_CHECK) {
				continue;
			}
			spins = 0;
			if (now_ns() - active > SHM_SPIN_NS) {
				struct timespec const idle = { 0, SHM_IDLE_NS };
				if (!quiet) {
					/* One line per burst of traffic, so a console
					 * shows sessions the way the TCP path's
					 * "client done" lines do. */
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
					ctl_log_end(&g_ctl_log);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
					vss_log_end(&g_vss_log);
#endif
					printf("monitor: shm quiet: seen=%llu accepted=%llu rejected=%llu (%llu this burst)\n",
					       seen, accepted, rejected, seen - seen_at_quiet);
					fflush(stdout);
					seen_at_quiet = seen;
					quiet = 1;
				}
				nanosleep(&idle, NULL);
			}
			continue;
		}
		/* A client publishes previous + 1. Anything else means a second
		 * client, or a client that lost count: still answered (the
		 * client waits for exactly this value), but counted. */
		if (cur != last + 1u) {
			jumps++;
		}
		shm_chan_get_frame(base, SHM_CHAN_OFF_REQ, buf);
		if (frame_get_u64(&buf[0]) != FRAME_SENTINEL_SEQ) {
			seen++;
			if (judge_frame(buf) == V_ACCEPT) {
				accepted++;
			} else {
				rejected++;
			}
		}
		shm_chan_put_frame(base, SHM_CHAN_OFF_RSP, buf);
		shm_chan_store(base, SHM_CHAN_OFF_RSP_SEQ, cur);
		last = cur;
		active = now_ns();
		quiet = 0;
	}

	__atomic_store_n(shm_chan_u32(base, SHM_CHAN_OFF_MAGIC), 0u, __ATOMIC_RELEASE);
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	ctl_log_end(&g_ctl_log);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	vss_log_end(&g_vss_log);
#endif
	printf("monitor: shm done: seen=%llu accepted=%llu rejected=%llu jumps=%llu\n",
	       seen, accepted, rejected, jumps);
	fflush(stdout);
	return 0;
}

/* The notified variant: one request outstanding, answered in place, the
 * client told by a kick byte or a doorbell (shm_chan.h). */
static int serve_kick(const char *spec, const char *kick)
{
	uint8_t buf[FRAME_TOTAL_BYTES];
	unsigned long long seen = 0, accepted = 0, rejected = 0, jumps = 0, stale = 0;
	unsigned long long seen_at_burst = 0;
	char what[384], name[256];
	size_t off = 0;
	uint64_t last, last_req_ns = 0;
	void *slot = NULL;
	struct shm_kick *k;
	struct shm_kick_stats st;

	if (split_spec(spec, name, sizeof(name), &off) != 0) {
		fprintf(stderr, "monitor: bad shm spec '%s' (NAME or NAME@OFFSET, OFFSET a multiple of %u)\n",
		        spec, (unsigned)SHM_CHAN_LINE);
		return 2;
	}
	k = shm_kick_open(name, off, kick, &slot, what, sizeof(what));
	if (k == NULL) {
		return 1;
	}
	/* Take the slot over, as the polling server does: a request left from
	 * before this server is not answered. Its own magic, so a polling client
	 * refuses it rather than spinning on a server that will never look. */
	__atomic_store_n(shm_chan_u32(slot, SHM_CHAN_OFF_MAGIC), 0u, __ATOMIC_RELEASE);
	last = shm_chan_load(slot, SHM_CHAN_OFF_REQ_SEQ);
	shm_chan_store(slot, SHM_CHAN_OFF_RSP_SEQ, last);
	*shm_chan_u32(slot, SHM_CHAN_OFF_VERSION) = SHM_CHAN_VERSION;
	__atomic_store_n(shm_chan_u32(slot, SHM_CHAN_OFF_MAGIC), SHM_CHAN_MAGIC_KICK, __ATOMIC_RELEASE);

	printf("monitor: safety monitor serving shm-kick on %s (frame=%u bytes, conf_min=%u%%)\n",
	       what, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN);
	fflush(stdout);

	while (!g_stop) {
		int handled = 0;
		int const r = shm_kick_wait(k);

		if (r < 0) {
			fprintf(stderr, "monitor: shm-kick wait failed: %s\n", strerror(errno));
			break;
		}
		if (r == 0) {
			continue;
		}
		for (;;) {
			uint64_t const cur = shm_chan_load(slot, SHM_CHAN_OFF_REQ_SEQ);
			uint32_t via, peer, count;
			uint64_t const now = now_ns();

			if (cur == last) {
				break;
			}
			if (seen > seen_at_burst && now - last_req_ns > 1000000000ull) {
				/* A second without requests ends a burst: one line per
				 * session, as the other servers print. */
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
				ctl_log_end(&g_ctl_log);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
				vss_log_end(&g_vss_log);
#endif
				printf("monitor: shm-kick burst: seen=%llu accepted=%llu rejected=%llu (%llu this burst)\n",
				       seen, accepted, rejected, seen - seen_at_burst);
				fflush(stdout);
				seen_at_burst = seen;
			}
			last_req_ns = now;
			if (cur != last + 1u) {
				jumps++;
			}
			via = shm_chan_load32(slot, SHM_CHAN_OFF_REPLY_VIA);
			peer = shm_chan_load32(slot, SHM_CHAN_OFF_CLIENT_PEER);
			count = shm_chan_load32(slot, SHM_CHAN_OFF_RING_COUNT);
			shm_chan_get_frame(slot, SHM_CHAN_OFF_REQ, buf);
			if (frame_get_u64(&buf[0]) != FRAME_SENTINEL_SEQ) {
				seen++;
				if (judge_frame(buf) == V_ACCEPT) {
					accepted++;
				} else {
					rejected++;
				}
			}
			shm_chan_put_frame(slot, SHM_CHAN_OFF_RSP, buf);
			shm_chan_store(slot, SHM_CHAN_OFF_RSP_SEQ, cur);
			last = cur;
			handled = 1;
			(void)shm_kick_notify(k, via, peer, count);   /* failures are counted inside */
		}
		if (!handled) {
			stale++;        /* a kick that found no new request */
		}
	}

	shm_kick_get_stats(k, &st);
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	ctl_log_end(&g_ctl_log);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	vss_log_end(&g_vss_log);
#endif
	printf("monitor: shm-kick done: seen=%llu accepted=%llu rejected=%llu jumps=%llu stale=%llu "
	       "kick_bytes=%llu echoes=%llu stray=%llu notify_kicks=%llu rings=%llu ring_misses=%llu "
	       "notify_fail=%llu clients=%llu\n",
	       seen, accepted, rejected, jumps, stale, st.kick_bytes, st.echoes, st.stray_bytes,
	       st.notify_kicks, st.rings, st.ring_misses, st.notify_fail, st.clients);
	fflush(stdout);
	return 0;
}

/* THE SERVICE MODE (OD14): monitor PORT svc DEADLINE_MS. TCP as the original,
 * one client at a time, the same judge_frame(), and two rules on top:
 *
 *   LIVENESS. The deadline is armed by the first claim judged. If DEADLINE_MS
 *   pass with no further claim -- whether the client is connected and quiet,
 *   has hung up, or has stalled mid-frame -- the monitor prints one LIVENESS
 *   MISS line carrying the silence it measured on its own monotonic clock, and
 *   at the next claim one LIVENESS RESTORED line. Any judged claim counts,
 *   accepted or rejected: liveness is not correctness. A sentinel does not: a
 *   pipeline that only sends keepalives has stopped producing claims.
 *
 *   A STALLED CONNECTION IS CLOSED. A client that delivers no complete frame,
 *   claim or sentinel, for DEADLINE_MS is disconnected, mid-frame or not; so is
 *   one that leaves its reply untaken for DEADLINE_MS after the frame it
 *   answers arrived. The monitor serves one client at a time, so without this a
 *   hung Compute side would hold the only slot and a restarted one could never
 *   connect -- the RESTORED line could never come. A client that holds one
 *   connection open must reconnect after a silence.
 *
 * No verdict changes: a MISS is a line on the console, not a reply, and only
 * payload[6] and [7] are ever written. The client's socket is non-blocking and
 * EVERY wait in this mode -- accept, read and write -- is a poll() that sleeps
 * until the earlier limit, with both checked before it; so a silence is
 * reported within a scheduler tick of its deadline, not whenever the next frame
 * happens to come. A claim that ends a silence of DEADLINE_MS or more gets its
 * MISS then its RESTORED even if it beat the timer to it by less than that tick,
 * on either path. A monitor that nothing has claimed to yet waits without a
 * deadline.
 *
 * FOUND BY REVIEW, 2026-09-23: the first version wrote replies with
 * frameio_write_frame() on a BLOCKING socket. A live client that stopped
 * reading its verdicts filled the send buffer and parked the monitor in
 * write() -- no MISS, the slot held, and SIGTERM retried away by the EINTR
 * loop. No client in this repo does that; the mode exists for ones that do. */
#define SVC_DEADLINE_MS_MAX 60000u

struct liveness {
	uint64_t deadline_ns;
	uint64_t last_claim_ns;         /* when the last claim arrived */
	unsigned long long last_seq;
	unsigned long long misses;
	int armed;                      /* a claim has been judged */
	int missed;                     /* the current silence has been reported */
	uint64_t restored_gap_ns;       /* a RESTORED line owed, printed after the reply */
	unsigned long long restored_seq;
};

/* When the running liveness deadline falls due; 0 when none is running (not
 * armed yet, or this silence already reported). */
static uint64_t live_due(const struct liveness *lv)
{
	return (lv->armed && !lv->missed) ? lv->last_claim_ns + lv->deadline_ns : 0;
}

/* Print the RESTORED line a claim is owed, if any. */
static void live_flush(struct liveness *lv)
{
	if (lv->restored_gap_ns == 0) {
		return;
	}
	printf("monitor: LIVENESS RESTORED: seq=%llu after %llu ms without a claim\n",
	       lv->restored_seq, (unsigned long long)(lv->restored_gap_ns / 1000000u));
	fflush(stdout);
	lv->restored_gap_ns = 0;
}

/* Report the current silence, once, if its deadline has passed. A RESTORED
 * still owed for the claim that began this silence goes out first, so the
 * console never shows a MISS before the RESTORED that preceded it. */
static void live_check(struct liveness *lv, uint64_t now)
{
	uint64_t const due = live_due(lv);

	if (due == 0 || now < due) {
		return;
	}
	live_flush(lv);
	lv->missed = 1;
	lv->misses++;
	printf("monitor: LIVENESS MISS: no claim for %llu ms since seq=%llu (deadline %llu ms, miss %llu)\n",
	       (unsigned long long)((now - lv->last_claim_ns) / 1000000u), lv->last_seq,
	       (unsigned long long)(lv->deadline_ns / 1000000u), lv->misses);
	fflush(stdout);
}

/* A claim arrived at `at`: the Compute side is alive. Registered BEFORE its
 * reply is written, so a reply that stalls cannot be counted as silence; the
 * RESTORED line it may be owed is only noted here, and live_flush() prints it
 * after the reply, so the console never delays one. */
static void live_claim(struct liveness *lv, unsigned long long seq, uint64_t at)
{
	if (lv->missed) {
		lv->restored_gap_ns = at - lv->last_claim_ns;     /* > 0: a miss means >= the deadline */
		lv->restored_seq = seq;
	}
	lv->armed = 1;
	lv->missed = 0;
	lv->last_claim_ns = at;
	lv->last_seq = seq;
}

/* poll()'s timeout until the earlier of two instants (0 = no such instant),
 * rounded UP to a millisecond so the wait never ends before it; -1 for none. */
static int wait_ms(uint64_t now, uint64_t a, uint64_t b)
{
	uint64_t due = a;

	if (b != 0 && (due == 0 || b < due)) {
		due = b;
	}
	if (due == 0) {
		return -1;
	}
	if (now >= due) {
		return 0;
	}
	return (int)((due - now + 999999u) / 1000000u);
}

/* One frame from a service client, both limits running. Returns 0 for a frame,
 * 1 for a clean hang-up or a stop, 2 when the connection delivered no complete
 * frame by conn_due, -1 for an error or a frame cut short. */
static int svc_read_frame(int cfd, uint8_t *buf, struct liveness *lv, uint64_t conn_due)
{
	size_t got = 0;

	while (got < FRAME_TOTAL_BYTES) {
		uint64_t const now = now_ns();
		struct pollfd pfd;
		int pr;
		ssize_t n;

		if (g_stop) {
			return 1;
		}
		live_check(lv, now);
		if (now >= conn_due) {
			return 2;
		}
		pfd.fd = cfd;
		pfd.events = POLLIN;
		pfd.revents = 0;
		pr = poll(&pfd, 1, wait_ms(now, live_due(lv), conn_due));
		if (pr < 0) {
			if (errno == EINTR) {
				continue;
			}
			return -1;
		}
		if (pr == 0) {
			continue;       /* a limit passed: the top of the loop reports it */
		}
		n = read(cfd, buf + got, FRAME_TOTAL_BYTES - got);
		if (n > 0) {
			got += (size_t)n;
		} else if (n == 0) {
			return (got == 0) ? 1 : -1;     /* EOF mid-frame is a protocol error */
		} else if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
			return -1;
		}
	}
	return 0;
}

/* The reply, both limits running, on the non-blocking client socket: a client
 * that does not take it by conn_due is closed like one that sends nothing.
 * Returns 0 when it is written, 1 on a stop, 2 when conn_due passed, -1 for an
 * error (a client that hung up: SIGPIPE is ignored, so that is EPIPE). */
static int svc_write_frame(int cfd, const uint8_t *buf, struct liveness *lv, uint64_t conn_due)
{
	size_t put = 0;

	while (put < FRAME_TOTAL_BYTES) {
		uint64_t const now = now_ns();
		struct pollfd pfd;
		int pr;
		ssize_t n;

		if (g_stop) {
			return 1;
		}
		live_check(lv, now);
		if (now >= conn_due) {
			return 2;
		}
		n = write(cfd, buf + put, FRAME_TOTAL_BYTES - put);
		if (n > 0) {
			put += (size_t)n;
			continue;
		}
		if (n < 0 && errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
			return -1;
		}
		/* The send buffer is full: wait for room, or for a limit. */
		pfd.fd = cfd;
		pfd.events = POLLOUT;
		pfd.revents = 0;
		pr = poll(&pfd, 1, wait_ms(now, live_due(lv), conn_due));
		if (pr < 0 && errno != EINTR) {
			return -1;
		}
	}
	return 0;
}

static void serve_svc_client(int cfd, struct liveness *lv)
{
	uint8_t buf[FRAME_TOTAL_BYTES];
	unsigned long long seen = 0, accepted = 0, rejected = 0;
	unsigned long long const d_ms = (unsigned long long)(lv->deadline_ns / 1000000u);
	uint64_t conn_due = now_ns() + lv->deadline_ns;

	for (;;) {
		int const rc = svc_read_frame(cfd, buf, lv, conn_due);
		uint64_t at;
		unsigned long long seq;
		int wrc;

		if (rc == 1) {
			break;
		}
		if (rc == 2) {
			printf("monitor: client closed: no complete frame for %llu ms\n", d_ms);
			fflush(stdout);
			break;
		}
		if (rc < 0) {
			fprintf(stderr, "monitor: frame read failed: %s\n", strerror(errno));
			break;
		}
		at = now_ns();
		conn_due = at + lv->deadline_ns;
		/* A frame that beat poll()'s timer to a silence already past its
		 * deadline: report the silence first, as the accept path would. */
		live_check(lv, at);

		/* A sentinel keeps the connection open but is not a claim, so it
		 * is not a sign of life: echoed untouched, never counted. */
		seq = (unsigned long long)frame_get_u64(&buf[0]);
		if (seq != FRAME_SENTINEL_SEQ) {
			seen++;
			if (judge_frame(buf) == V_ACCEPT) {
				accepted++;
			} else {
				rejected++;
			}
			live_claim(lv, seq, at);        /* it arrived: counts even if its reply fails */
		}
		wrc = svc_write_frame(cfd, buf, lv, conn_due);
		live_flush(lv);                         /* a RESTORED line, after the reply */
		if (wrc == 2) {
			printf("monitor: client closed: reply not taken for %llu ms\n", d_ms);
			fflush(stdout);
		}
		if (wrc != 0) {
			break;
		}
	}

#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	ctl_log_end(&g_ctl_log);
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	vss_log_end(&g_vss_log);
#endif
	printf("monitor: client done: seen=%llu accepted=%llu rejected=%llu\n",
	       seen, accepted, rejected);
	fflush(stdout);
}

static int serve_svc(int port, unsigned deadline_ms)
{
	struct liveness lv;
	struct sockaddr_in addr;
	int lfd, fl, opt = 1;

	memset(&lv, 0, sizeof(lv));
	lv.deadline_ns = (uint64_t)deadline_ms * 1000000u;

	lfd = socket(AF_INET, SOCK_STREAM, 0);
	if (lfd < 0) {
		fprintf(stderr, "monitor: socket: %s\n", strerror(errno));
		return 1;
	}
	setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
	/* Non-blocking, so a connection reset between poll() and accept() cannot
	 * park the monitor in accept() past a deadline. */
	fl = fcntl(lfd, F_GETFL, 0);
	if (fl < 0 || fcntl(lfd, F_SETFL, fl | O_NONBLOCK) != 0) {
		fprintf(stderr, "monitor: fcntl: %s\n", strerror(errno));
		close(lfd);
		return 1;
	}

	memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_addr.s_addr = htonl(INADDR_ANY);
	addr.sin_port = htons((uint16_t)port);

	if (bind(lfd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
		fprintf(stderr, "monitor: bind(%d): %s\n", port, strerror(errno));
		close(lfd);
		return 1;
	}
	if (listen(lfd, 4) != 0) {
		fprintf(stderr, "monitor: listen: %s\n", strerror(errno));
		close(lfd);
		return 1;
	}

	printf("monitor: service monitor listening on :%d (frame=%u bytes, conf_min=%u%%), liveness deadline %u ms\n",
	       port, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN, deadline_ms);
	fflush(stdout);

	while (!g_stop) {
		uint64_t const now = now_ns();
		struct pollfd pfd;
		int pr, cfd;

		live_check(&lv, now);
		pfd.fd = lfd;
		pfd.events = POLLIN;
		pfd.revents = 0;
		pr = poll(&pfd, 1, wait_ms(now, live_due(&lv), 0));
		if (pr < 0) {
			if (errno == EINTR) {
				continue;
			}
			fprintf(stderr, "monitor: poll: %s\n", strerror(errno));
			break;
		}
		if (pr == 0) {
			continue;
		}
		cfd = accept(lfd, NULL, NULL);
		if (cfd < 0) {
			if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK || errno == ECONNABORTED) {
				continue;
			}
			fprintf(stderr, "monitor: accept: %s\n", strerror(errno));
			break;
		}
		/* Non-blocking, set explicitly rather than inherited: whether an
		 * accepted socket inherits the listener's O_NONBLOCK differs between
		 * socket stacks, so the flag is set here on every platform. Every
		 * read and write on it waits in poll() with the limits running. */
		fl = fcntl(cfd, F_GETFL, 0);
		if (fl < 0 || fcntl(cfd, F_SETFL, fl | O_NONBLOCK) != 0) {
			fprintf(stderr, "monitor: fcntl(client): %s\n", strerror(errno));
			close(cfd);
			continue;
		}
		setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));
		serve_svc_client(cfd, &lv);
		close(cfd);
	}

	close(lfd);
	printf("monitor: stopped (liveness misses=%llu)\n", lv.misses);
	return 0;
}

int main(int argc, char **argv)
{
	int const port = (argc > 1) ? atoi(argv[1]) : DEFAULT_PORT;
	struct sigaction sa;
	struct sockaddr_in addr;
	int lfd, opt = 1, stamp = 0;

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_signal;
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGTERM, &sa, NULL);
	signal(SIGPIPE, SIG_IGN);

	if (argc > 1 && strcmp(argv[1], "shmcfg") == 0) {
		char what[320];
		if (argc != 3) {
			fprintf(stderr, "monitor: usage: monitor shmcfg SPEC\n");
			return 2;
		}
		if (shm_configure(argv[2], what, sizeof(what)) != 0) {
			return 1;
		}
		printf("monitor: shm configured: %s\n", what);
		fflush(stdout);
		return 0;
	}
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	/* The startup self-check (wire specification 4.3): before any serving
	 * mode prints a line, so a broken image prints no claim kinds line and
	 * never listens. shmcfg above serves nothing and is not checked. */
	if (!vss_contract_consistent()) {
		fprintf(stderr, "monitor: vss contract inconsistent\n");
		return 2;
	}
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	/* Kind 2's self-check (the Phase 8 specification, section 2.4), right
	 * after kind 4's and like it before any serving line. */
	if (!ctl_contract_consistent()) {
		fprintf(stderr, "monitor: ctl contract inconsistent\n");
		return 2;
	}
#endif
	/* Every serving mode says which claim kinds it judges and with what
	 * bounds, on its own line: the guest console then shows which rules a
	 * run was judged by, and an image can be checked for this build by the
	 * string alone. The existing banners are left word for word, because
	 * the harnesses grep them. */
	printf("monitor: claim kinds: 0 mnist (us <= %u), 1 vlm model %u (us <= %u), conf_min=%u%%\n",
	       INFER_US_MAX, VLM_MODEL_SMOLVLM_500M, VLM_INFER_US_MAX, CONF_MIN);
	fflush(stdout);
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x10)
	vss_announce();         /* the vss rules: and vss profile lines (wire specification 12) */
#endif
#if defined(MONITOR_EXT_KINDS) && (MONITOR_EXT_KINDS & 0x04)
	ctl_announce();         /* the ctl rules: and ctl profile lines (Phase 8 specification 2.5) */
#endif
	if (argc > 1 && strcmp(argv[1], "shmkick") == 0) {
		if (argc != 4) {
			fprintf(stderr, "monitor: usage: monitor shmkick SPEC[@OFFSET] KICK\n");
			return 2;
		}
		return serve_kick(argv[2], argv[3]);
	}
	if (argc > 1 && strcmp(argv[1], "shm") == 0) {
		if (argc != 3) {
			fprintf(stderr, "monitor: usage: monitor shm SPEC (a /dev/shm file on a host, 'ivshmem' in the guest)\n");
			return 2;
		}
		return serve_shm(argv[2]);
	}
	if (argc > 2) {
		if (strcmp(argv[2], "udp") == 0) {
			return serve_udp(port);
		}
		if (strcmp(argv[2], "svc") == 0) {
			/* Digits only, 1..SVC_DEADLINE_MS_MAX: strtoul alone would
			 * take " 5", "-1" (as a huge value) or "2000ms". */
			unsigned long ms = 0;
			char *end = NULL;

			if (argc == 4 && argv[3][0] >= '0' && argv[3][0] <= '9') {
				errno = 0;
				ms = strtoul(argv[3], &end, 10);
				if (errno != 0 || *end != '\0') {
					ms = 0;
				}
			}
			if (ms == 0 || ms > SVC_DEADLINE_MS_MAX) {
				fprintf(stderr, "monitor: usage: monitor PORT svc DEADLINE_MS (1..%u)\n",
				        SVC_DEADLINE_MS_MAX);
				return 2;
			}
			return serve_svc(port, (unsigned)ms);
		}
		if (strcmp(argv[2], "stamp") != 0 || argc != 3) {
			/* Refuse an unknown transport word rather than guess. (Only the
			 * word is checked: the port is still atoi(argv[1]), as before.) */
			fprintf(stderr, "monitor: unknown transport '%s' (only 'udp', or none for tcp; shm is 'monitor shm SPEC')\n",
			        argv[2]);
			return 2;
		}
		stamp = 1;      /* OD15: the TCP mode below, stamping every claim's reply */
	}

	lfd = socket(AF_INET, SOCK_STREAM, 0);
	if (lfd < 0) {
		fprintf(stderr, "monitor: socket: %s\n", strerror(errno));
		return 1;
	}
	setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

	memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_addr.s_addr = htonl(INADDR_ANY);
	addr.sin_port = htons((uint16_t)port);

	if (bind(lfd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
		fprintf(stderr, "monitor: bind(%d): %s\n", port, strerror(errno));
		close(lfd);
		return 1;
	}
	if (listen(lfd, 4) != 0) {
		fprintf(stderr, "monitor: listen: %s\n", strerror(errno));
		close(lfd);
		return 1;
	}

	printf("monitor: safety monitor listening on :%d (frame=%u bytes, conf_min=%u%%)\n",
	       port, (unsigned)FRAME_TOTAL_BYTES, (unsigned)CONF_MIN);
	if (stamp) {
		/* A line of its own: the banner above is grepped word for word. */
		printf("monitor: stamping replies on :%d: t_in payload[8..15], t_out payload[16..23], CLOCK_MONOTONIC ns\n",
		       port);
	}
	fflush(stdout);

	while (!g_stop) {
		int cfd = accept(lfd, NULL, NULL);
		if (cfd < 0) {
			if (errno == EINTR) {
				continue;
			}
			fprintf(stderr, "monitor: accept: %s\n", strerror(errno));
			break;
		}
		setsockopt(cfd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));
		serve_one_client(cfd, stamp);
		close(cfd);
	}

	close(lfd);
	printf("monitor: stopped\n");
	return 0;
}
