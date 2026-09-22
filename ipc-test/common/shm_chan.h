/* A6, OD12 (2026-09-22) -- one request/reply slot in shared memory.
 *
 * The third transport beside TCP and UDP: the same 64-byte frame (frame.h),
 * carried through memory both ends map, instead of through a network stack.
 * Across the partition that memory is QEMU's ivshmem device -- a file in the
 * host's /dev/shm that QEMU exposes to the guest as PCI BAR2 -- and on the host
 * it is the same kind of file mapped directly. The judgement stays in
 * monitor.c; this header only moves frames.
 *
 * LAYOUT (byte offsets into the region; every field on its own 64-byte line, so
 * the line one side polls is never the line the other side is filling):
 *
 *   0    u32 magic     SHM_CHAN_MAGIC once the server is serving, else 0
 *   4    u32 version   SHM_CHAN_VERSION
 *   64   u64 req_seq   written by the client, LAST, with release
 *   128  frame[64]     the request
 *   192  u64 rsp_seq   written by the server, LAST, with release
 *   256  frame[64]     the reply
 *
 * PROTOCOL. One request outstanding, as on the other transports. The client
 * fills the request frame, then publishes req_seq = previous + 1 with a
 * store-release. The server, seeing req_seq change (load-acquire), reads the
 * frame, judges it, fills the reply frame and publishes rsp_seq = that req_seq
 * with a store-release. The client waits for rsp_seq to equal what it
 * published. req_seq is a doorbell counter, separate from the frame's own seq,
 * because a sentinel frame's seq is UINT64_MAX and must still be deliverable.
 *
 * WHY ACQUIRE/RELEASE AND NOT volatile. Armv8 is weakly ordered: two plain
 * stores from one core can become visible to another core in either order. A
 * reader that saw the new req_seq could otherwise read a stale frame. The
 * builtins below compile to STLR/LDAR on aarch64, on gcc and on qcc (which is
 * gcc), and are equally correct on x86-64, where CI runs.
 *
 * CROSS-VM COHERENCE. Across KVM this relies on the guest mapping BAR2 as
 * normal CACHEABLE memory (see shm_map_qnx.c). Without FEAT_S2FWB, which the
 * A78AE does not have, a guest mapping it uncached would combine with the
 * host's cacheable mapping into mismatched attributes, and Arm then does not
 * promise coherence between the two views.
 *
 * WAITING IS BY POLLING, in the slot's first use (magic "SHM1"): the plain
 * ivshmem device has no interrupt, and a polling waiter holds its core.
 *
 * THE NOTIFIED VARIANT (OD12, 2026-09-22; magic "SHK1"). The same slot, but
 * nobody spins: the client adds, in the request line and before the release of
 * req_seq, how it wants to be told (reply_via) and its ivshmem peer id
 * (client_peer), then sends one kick byte to the server over a stream; the
 * server, woken by that byte, answers in the slot and then notifies the client
 *   SHM_VIA_KICK      one kick byte back over the same stream
 *   SHM_VIA_DOORBELL  a doorbell to client_peer (in the guest: the ivshmem
 *                     Doorbell register, which KVM turns into a write to the
 *                     client's eventfd; on a host: that eventfd directly)
 *   SHM_VIA_BURST     a test only: ring_count doorbells, to show the path
 * The kick bytes are fixed values, so a byte that is anything else is counted as
 * stray rather than taken as a kick. SHM_ECHO_BYTE asks for no slot work at
 * all: the server sends SHM_ECHO_BYTE straight back -- the bare notification
 * round trip. A server of one kind publishes only its own magic, so a polling
 * client and a notified server can never pair silently.
 */
#ifndef IPC_TEST_SHM_CHAN_H
#define IPC_TEST_SHM_CHAN_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#include "frame.h"

#define SHM_CHAN_MAGIC     0x314D4853u    /* "SHM1", little-endian: a polling server */
#define SHM_CHAN_MAGIC_KICK 0x314B4853u   /* "SHK1": a notified server */
#define SHM_CHAN_VERSION   1u
#define SHM_CHAN_LINE      64u
#define SHM_CHAN_OFF_MAGIC     0u
#define SHM_CHAN_OFF_VERSION   4u
#define SHM_CHAN_OFF_REQ_SEQ   64u
#define SHM_CHAN_OFF_REPLY_VIA 72u        /* u32, notified variant only */
#define SHM_CHAN_OFF_CLIENT_PEER 76u      /* u32, notified variant only */
#define SHM_CHAN_OFF_RING_COUNT 80u       /* u32, SHM_VIA_BURST only */
#define SHM_CHAN_OFF_REQ       128u
#define SHM_CHAN_OFF_RSP_SEQ   192u
#define SHM_CHAN_OFF_RSP       256u
#define SHM_CHAN_MIN_BYTES     4096u      /* the layout needs 320; a page is mapped */

#define SHM_VIA_KICK      0u
#define SHM_VIA_DOORBELL  1u
#define SHM_VIA_BURST     3u
#define SHM_KICK_BYTE     'K'              /* "a request is in the slot" / "the reply is" */
#define SHM_ECHO_BYTE     'E'              /* "send this byte back", no slot */
#define SHM_BURST_MAX     100000u

static inline uint64_t *shm_chan_u64(void *base, size_t off)
{
	return (uint64_t *)((uint8_t *)base + off);
}

static inline uint32_t *shm_chan_u32(void *base, size_t off)
{
	return (uint32_t *)((uint8_t *)base + off);
}

static inline uint64_t shm_chan_load(void *base, size_t off)
{
	return __atomic_load_n(shm_chan_u64(base, off), __ATOMIC_ACQUIRE);
}

static inline void shm_chan_store(void *base, size_t off, uint64_t v)
{
	__atomic_store_n(shm_chan_u64(base, off), v, __ATOMIC_RELEASE);
}

static inline int shm_chan_ready_as(void *base, uint32_t magic)
{
	return __atomic_load_n(shm_chan_u32(base, SHM_CHAN_OFF_MAGIC), __ATOMIC_ACQUIRE) == magic
	    && *shm_chan_u32(base, SHM_CHAN_OFF_VERSION) == SHM_CHAN_VERSION;
}

static inline int shm_chan_ready(void *base)
{
	return shm_chan_ready_as(base, SHM_CHAN_MAGIC);
}

static inline uint32_t shm_chan_load32(void *base, size_t off)
{
	return __atomic_load_n(shm_chan_u32(base, off), __ATOMIC_RELAXED);
}

static inline void shm_chan_store32(void *base, size_t off, uint32_t v)
{
	__atomic_store_n(shm_chan_u32(base, off), v, __ATOMIC_RELAXED);
}

/* The frames are copied with memcpy AFTER the acquire (reader) or BEFORE the
 * release (writer); the ordering comes from the seq accesses, not the copy. */
static inline void shm_chan_get_frame(void *base, size_t off, uint8_t *dst)
{
	memcpy(dst, (uint8_t *)base + off, FRAME_TOTAL_BYTES);
}

static inline void shm_chan_put_frame(void *base, size_t off, const uint8_t *src)
{
	memcpy((uint8_t *)base + off, src, FRAME_TOTAL_BYTES);
}

/* A spin-wait hint that is NOT trapped by KVM (WFE is, by default, and would
 * turn the spin into a vCPU exit). A no-op elsewhere. */
static inline void shm_chan_relax(void)
{
#if defined(__aarch64__)
	__asm__ __volatile__("yield" ::: "memory");
#elif defined(__x86_64__) || defined(__i386__)
	__asm__ __volatile__("pause" ::: "memory");
#endif
}

#endif /* IPC_TEST_SHM_CHAN_H */
