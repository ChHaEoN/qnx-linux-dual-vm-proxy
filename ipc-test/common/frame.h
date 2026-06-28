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
