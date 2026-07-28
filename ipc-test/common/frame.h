/* Phase 2 (cloud, QNX<->QNX over qvm virtio-console) — shared wire contract.
 *
 * Fixed-width echo frame exchanged between the QHV host initiator
 * (qnx-host-client) and the QNX guest endpoint (qnx-server) across the qvm
 * virtio-console vdev (ADR-002 / docs/phase2-topology-decision.md). Both ends
 * are QNX, so this is a SINGLE-OS measurement using ClockCycles(); there is no
 * cross-clock skew on this leg (the Linux end, with clock_gettime, only appears
 * at Phase 3 / Orin).
 *
 * Honest framing: this is a study-level mechanism-alive proxy across a
 * TCG-emulated qvm EL2/EL1 boundary, not a transport benchmark. The on-wire
 * RTT is dominated by TCG emulation overhead, not a meaningful transport cost.
 *
 * The format is defined once here and shared by both translation units so the
 * two ends cannot drift. Multi-byte fields are serialised little-endian on the
 * wire via explicit pack/unpack helpers, so the contract is endian-independent
 * even though both current ends are aarch64le.
 */
#ifndef IPC_TEST_FRAME_H
#define IPC_TEST_FRAME_H

#include <stdint.h>
#include <stddef.h>

/* Wire layout (FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES, fixed width):
 *   offset 0  : uint64_t seq            (monotonic, little-endian)
 *   offset 8  : uint64_t tstamp_cycles  (ClockCycles() at send, little-endian)
 *   offset 16 : uint8_t  payload[FRAME_PAYLOAD_BYTES]
 * The payload is echoed back unmodified; seq + tstamp let the initiator match
 * replies and compute RTT without per-frame parsing cost on the latency path. */
#define FRAME_HEADER_BYTES   16u
#define FRAME_PAYLOAD_BYTES  48u
#define FRAME_TOTAL_BYTES    (FRAME_HEADER_BYTES + FRAME_PAYLOAD_BYTES)

typedef struct {
    uint64_t seq;
    uint64_t tstamp_cycles;
    uint8_t  payload[FRAME_PAYLOAD_BYTES];
} ipc_frame_t;

/* Reserved seq value marking a KICK-SAFE SENTINEL frame (2026-07-28,
 * docs/findings.md): a no-op/keepalive both ends may treat as carrying no
 * data-correctness meaning. Real traffic's seq space is 0..(warmup+iters-1),
 * always far below UINT64_MAX, so this value can never collide with a real
 * frame. The echo side (qnx-server) needs NO special handling -- it already
 * echoes every frame verbatim regardless of seq, so a sentinel bounces back
 * unmodified for free. Only an INITIATOR needs to recognise this value: use
 * it (not a resend of the real in-flight frame) as the write-side "kick" that
 * recovers from a missed read-ready notification, since a stale sentinel
 * echo is safe to discard whereas a stale duplicate of a REAL frame corrupts
 * the next iteration's alignment (see ipc-test/qnx-host-client/README.md). */
#define FRAME_SENTINEL_SEQ  UINT64_MAX

static inline int frame_is_sentinel(const ipc_frame_t *f)
{
    return f->seq == FRAME_SENTINEL_SEQ;
}

static inline void frame_put_u64(uint8_t *p, uint64_t v)
{
    p[0] = (uint8_t)(v & 0xffu);
    p[1] = (uint8_t)((v >> 8) & 0xffu);
    p[2] = (uint8_t)((v >> 16) & 0xffu);
    p[3] = (uint8_t)((v >> 24) & 0xffu);
    p[4] = (uint8_t)((v >> 32) & 0xffu);
    p[5] = (uint8_t)((v >> 40) & 0xffu);
    p[6] = (uint8_t)((v >> 48) & 0xffu);
    p[7] = (uint8_t)((v >> 56) & 0xffu);
}

static inline uint64_t frame_get_u64(const uint8_t *p)
{
    return  (uint64_t)p[0]
         | ((uint64_t)p[1] << 8)
         | ((uint64_t)p[2] << 16)
         | ((uint64_t)p[3] << 24)
         | ((uint64_t)p[4] << 32)
         | ((uint64_t)p[5] << 40)
         | ((uint64_t)p[6] << 48)
         | ((uint64_t)p[7] << 56);
}

/* Serialise a frame into a FRAME_TOTAL_BYTES buffer. */
static inline void frame_pack(const ipc_frame_t *f, uint8_t *buf)
{
    frame_put_u64(buf, f->seq);
    frame_put_u64(buf + 8, f->tstamp_cycles);
    for (size_t i = 0; i < FRAME_PAYLOAD_BYTES; ++i) {
        buf[FRAME_HEADER_BYTES + i] = f->payload[i];
    }
}

/* Deserialise a FRAME_TOTAL_BYTES buffer into a frame. */
static inline void frame_unpack(const uint8_t *buf, ipc_frame_t *f)
{
    f->seq = frame_get_u64(buf);
    f->tstamp_cycles = frame_get_u64(buf + 8);
    for (size_t i = 0; i < FRAME_PAYLOAD_BYTES; ++i) {
        f->payload[i] = buf[FRAME_HEADER_BYTES + i];
    }
}

#endif /* IPC_TEST_FRAME_H */
