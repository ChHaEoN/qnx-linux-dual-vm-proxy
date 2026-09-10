/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * The INTID 28 probe: is the EL2 virtual timer wired to this core's
 * redistributor?
 *
 * Under -Q enable,el2-host the library gives procnto its clock on INTID 28, the
 * Non-secure EL2 virtual timer's PPI, unconditionally
 * (lib/aarch64/init_qtime_v8gt.c:56-57), and nothing checks that anything
 * drives it. With E2H set at EL2 the CNTV_* names reach CNTHV_*_EL2
 * (VENDOR_CLAIM, Arm register descriptions), so that is the timer procnto
 * would program. Whether it is wired on this board is unknown:
 *
 *   - the device tree's timer node lists PPIs 13, 14, 11 and 10 and no
 *     hyp-virt entry (results/orin-native-port/20260909T1100Z/
 *     research-tegra234.md:109);
 *   - the only timer PPI Linux uses at EL2 here is INTID 26
 *     (results/orin-native-port/20260909T1100Z/raw/orin-firmware-el.txt:46);
 *   - under QEMU, a host whose EL2 virtual timer was left unconnected ran user
 *     space and then stalled at its first timed wait
 *     (logs/sample-boot/orin-qhv-tcg-q111-nohypvirt-control.log). On this
 *     board that would be a hang, a power cycle and an empty black box.
 *
 * So the question is asked here, on every core, before procnto: does asserting
 * CNTHV's output make INTID 28 pending at this core's redistributor, in the
 * Non-secure view procnto has? Anything short of "wired" stops the run by name
 * with a warm reset under -tstop, the default (main.c).
 *
 * Nothing is ever taken. The GIC wrapper calls this after the library's per-CPU
 * GIC init, which put every SGI/PPI in Group 1 NS at priority 0xA0, cleared
 * pending, and disabled all of them but SGI0 (lib/aarch64/gic_v3.c:1484-1500),
 * and with DAIF masked (lib/aarch64/_start_el1.S:62). A disabled level PPI still
 * shows pending while its input is asserted and is never forwarded
 * (VENDOR_CLAIM, GICv3 specification §12.11.5). That this GIC-600 behaves so is
 * not assumed: a positive control on INTID 26, the EL2 physical timer, runs
 * first on the same core, and an "absent" verdict is allowed only when that
 * control has just passed.
 *
 * Never written: ISENABLER0, ICENABLER0, ICFGR1, IGROUPR0, any IPRIORITYR,
 * DAIF. Never read: ICC_IAR*. ICPENDR0 is written only for a bit that is
 * pending, edge-configured, disabled and inactive. Both EL2 timers end with
 * their control at 0 and their compare value as found.
 *
 * Every wait has two bounds: the generic counter against t234_cps(), which is
 * valid on every core once CPU0's init_qtime has run, and an iteration cap.
 * With every bound hit a core spends about 0.3 s here, far inside the 15 s AP
 * start deadline (t234_startup.h).
 *
 * Specification: results/orin-native-port/20260909T1100Z/m1b-design.md §4,
 * whose step numbers the comments below use. This file compiles; nothing in it
 * has run on the board.
 */

#include "t234_startup.h"
#include <aarch64/gic_v3.h>

/*
 * The EL2 virtual timer has no name at the SDP's default -march: its assembler
 * rejects cnthv_ctl_el2. The encodings are the Arm ones (op0=3 op1=4 CRn=14
 * CRm=3), spelled out the way the library spells ICC_SRE_EL2
 * (lib/aarch64/_start_el1.S:190). The EL2 physical timer is used by name.
 */
#define T234_CNTHV_CTL          S3_4_C14_C3_1   /* CNTHV_CTL_EL2  */
#define T234_CNTHV_CVAL         S3_4_C14_C3_2   /* CNTHV_CVAL_EL2 */

/* Control bits, the same in CNTHP_CTL_EL2 and CNTHV_CTL_EL2. */
#define CNT_ENABLE              1u
#define CNT_IMASK               2u
#define CNT_ISTATUS             4u

#define B26                     (1u << 26)      /* NS EL2 physical timer, Linux's arch_timer at EL2 */
#define B28                     (1u << 28)      /* NS EL2 virtual timer, qtime->intr under el2-host */

/*
 * The second bound on every wait. The counter is the bound meant to end one;
 * a cap matters only if the counter itself does not advance.
 */
#define T234_HVT_POLL_CAP       (1u << 20)      /* the 20 ms pending polls */
#define T234_HVT_ISTATUS_CAP    (1u << 28)      /* the 100 ms ISTATUS wait */

/* GICR_WAKER ProcessorSleep | ChildrenAsleep, the bits init_intrinfo.c waits on. */
#define T234_WAKER_ASLEEP       0x6u

/* Which EL2 timer a run uses. */
#define T234_HVT_HP             0               /* CNTHP, INTID 26 */
#define T234_HVT_HV             1               /* CNTHV, INTID 28 */

/* What one timer run saw, printed raw on its CNTHP or CNTHV line. */
struct t234_hvt_run {
	unsigned	pre;        /* ISTATUS read right after arming           */
	_Uint32t	early;      /* ISPENDR0 read right after arming          */
	unsigned	istatus;    /* ISTATUS when the wait for it ended        */
	unsigned	t_ms;       /* counter time from arming to that moment   */
	_Uint32t	on;         /* ISPENDR0 once the bit rose, or at a bound */
	_Uint32t	mask;       /* ISPENDR0 once the bit fell after IMASK    */
	_Uint32t	off;        /* ISPENDR0 after the control went back to 0 */
};

const char *
t234_hvt_verdict_name(int const verdict)
{
	switch (verdict) {
	case T234_HVT_WIRED:        return "wired";
	case T234_HVT_ABSENT:       return "absent";
	case T234_HVT_INCONCLUSIVE: return "inconclusive";
	default:                    break;
	}
	return "unknown";
}

/*
 * Timer register access. The SDP macros paste the register name into the
 * instruction (aarch64/inline.h:98-127 in the SDP headers), so a name cannot
 * be a variable: each accessor chooses between two literal names, and the one
 * run sequence below serves both timers with nothing else different.
 */
static _Uint64t
t234_hvt_ctl_rd(int const t)
{
	if (t == T234_HVT_HV) {
		return aa64_sr_rd64(T234_CNTHV_CTL);
	}
	return aa64_sr_rd64(cnthp_ctl_el2);
}

static void
t234_hvt_ctl_wr(int const t, _Uint64t const v)
{
	if (t == T234_HVT_HV) {
		aa64_sr_wr64(T234_CNTHV_CTL, v);
	} else {
		aa64_sr_wr64(cnthp_ctl_el2, v);
	}
}

static void
t234_hvt_cval_wr(int const t, _Uint64t const v)
{
	if (t == T234_HVT_HV) {
		aa64_sr_wr64(T234_CNTHV_CVAL, v);
	} else {
		aa64_sr_wr64(cnthp_cval_el2, v);
	}
}

/* The ICFGR1 edge bit of PPI n (16..31): bit 2*(n-16)+1 (VENDOR_CLAIM, GICv3 §12.11.8). */
static unsigned
t234_hvt_edge(_Uint32t const cfg1, unsigned const n)
{
	return (cfg1 >> (2u * (n - 16u) + 1u)) & 1u;
}

/*
 * Read ISPENDR0 until (value & bits) == want, for at most 20 ms of the counter
 * and T234_HVT_POLL_CAP further reads. Returns the last value read.
 */
static _Uint32t
t234_hvt_poll(paddr_t const sgi, _Uint32t const bits, _Uint32t const want,
              _Uint64t const cps)
{
	_Uint64t const dl = aa64_sr_rd64(cntpct_el0) + cps / 50u;
	_Uint32t       v  = in32(sgi + ARM_GICR_ISPENDR0);
	unsigned       n;

	for (n = 0; (v & bits) != want && n < T234_HVT_POLL_CAP; ++n) {
		if (aa64_sr_rd64(cntpct_el0) >= dl) {
			break;
		}
		v = in32(sgi + ARM_GICR_ISPENDR0);
	}
	return v;
}

/*
 * Clear the pending latch of INTID 26 and 28, each only if it is pending,
 * edge-configured, not enabled and not active. A level-sensitive bit is left
 * alone: its pending state follows its input, which the caller has already
 * deasserted.
 */
static void
t234_hvt_clear_edge(paddr_t const sgi)
{
	static const unsigned ppi[2] = { 26u, 28u };
	_Uint32t const pend = in32(sgi + ARM_GICR_ISPENDR0);
	_Uint32t const en   = in32(sgi + ARM_GICR_ISENABLER0);
	_Uint32t const act  = in32(sgi + ARM_GICR_ISACTIVER0);
	_Uint32t const cfg1 = in32(sgi + ARM_GICR_ICFGR1);
	unsigned       i;

	for (i = 0; i < 2u; ++i) {
		_Uint32t const b = 1u << ppi[i];

		if ((pend & b) != 0 && (en & b) == 0 && (act & b) == 0 &&
		    t234_hvt_edge(cfg1, ppi[i]) != 0) {
			out32(sgi + ARM_GICR_ICPENDR0, b);
		}
	}
}

/*
 * One timer, steps 4.1-4.8 (and step 6 for CNTHV): arm it 2 ms ahead, wait for
 * ISTATUS, watch its bit rise, mask the output, watch the bit fall, disarm.
 *
 * Both EL2 timers compare against the physical count, with the virtual offset
 * treated as 0 under E2H=1, TGE=1 (VENDOR_CLAIM), and at_el2 zeroed CNTVOFF_EL2
 * anyway (lib/aarch64/_start_el1.S:180), so CVAL = CNTPCT + delta is right for
 * both.
 */
static void
t234_hvt_run(int const t, paddr_t const sgi, _Uint32t const bit,
             _Uint64t const cps, struct t234_hvt_run *const r)
{
	_Uint64t const t0 = aa64_sr_rd64(cntpct_el0);
	_Uint64t const dl = t0 + cps / 10u;
	unsigned       n;

	/* 4.1-4.2: output enabled, because IMASK is 0. */
	t234_hvt_cval_wr(t, t0 + cps / 500u);
	t234_hvt_ctl_wr(t, CNT_ENABLE);
	isb();

	/* 4.3 */
	r->pre   = (t234_hvt_ctl_rd(t) & CNT_ISTATUS) != 0;
	r->early = in32(sgi + ARM_GICR_ISPENDR0);

	/* 4.4: 100 ms of the counter or T234_HVT_ISTATUS_CAP reads. */
	for (n = 0; (t234_hvt_ctl_rd(t) & CNT_ISTATUS) == 0 && n < T234_HVT_ISTATUS_CAP; ++n) {
		if (aa64_sr_rd64(cntpct_el0) >= dl) {
			break;
		}
	}
	r->istatus = (t234_hvt_ctl_rd(t) & CNT_ISTATUS) != 0;
	r->t_ms    = (unsigned)(((aa64_sr_rd64(cntpct_el0) - t0) * 1000u) / cps);

	/* 4.5 */
	if (r->istatus) {
		r->on = t234_hvt_poll(sgi, bit, bit, cps);
	} else {
		r->on = in32(sgi + ARM_GICR_ISPENDR0);
	}

	/* 4.6: the output deasserts; ISTATUS stays valid while ENABLE is 1 (VENDOR_CLAIM). */
	t234_hvt_ctl_wr(t, CNT_ENABLE | CNT_IMASK);
	isb();

	/* 4.7 */
	r->mask = t234_hvt_poll(sgi, bit, 0, cps);

	/* 4.8 */
	t234_hvt_ctl_wr(t, 0);
	isb();
	r->off = in32(sgi + ARM_GICR_ISPENDR0);
}

static void
t234_hvt_print_run(unsigned const cpu, const char *const name, unsigned const ppi,
                   _Uint32t const base, const struct t234_hvt_run *const r,
                   _Uint32t const moved)
{
	if (debug_flag > 1) {
		kprintf("t234: hvtimer cpu %d %s ppi=%d pre=%d base=%x early=%x on=%x mask=%x off=%x istatus=%d t_ms=%d moved=%x\n",
		        cpu, name, ppi, r->pre, base, r->early, r->on, r->mask,
		        r->off, r->istatus, r->t_ms, moved);
	}
}

/*
 * Step 7. No timer left enabled, which is the state the library itself leaves
 * (hyp_enable_el2_host zeroes CNTHP_CTL_EL2, lib/aarch64/hypervisor_enable.S:26;
 * on CPU0 init_qtime zeroes CNTHV through the alias,
 * lib/aarch64/init_qtime_v8gt.c:66), both compare values as found, and any edge
 * latch the runs left cleared.
 */
static void
t234_hvt_restore(paddr_t const sgi, _Uint64t const hpcval0, _Uint64t const hvcval0)
{
	aa64_sr_wr64(cnthp_ctl_el2, 0);
	aa64_sr_wr64(T234_CNTHV_CTL, 0);
	aa64_sr_wr64(cnthp_cval_el2, hpcval0);
	aa64_sr_wr64(T234_CNTHV_CVAL, hvcval0);
	isb();
	t234_hvt_clear_edge(sgi);
}

/* "ppiNN" for the lowest set bit of bits, which is non-zero, in decimal. */
static const char *
t234_hvt_ppi_reason(char *const buf, _Uint32t const bits)
{
	unsigned b = 0;
	unsigned i = 0;

	while (b < 31u && ((bits >> b) & 1u) == 0) {
		++b;
	}
	buf[i++] = 'p';
	buf[i++] = 'p';
	buf[i++] = 'i';
	if (b >= 10u) {
		buf[i++] = (char)('0' + (b / 10u));
	}
	buf[i++] = (char)('0' + (b % 10u));
	buf[i]   = '\0';
	return buf;
}

/*
 * The verdict line, always printed, then the policy. Under -tstop a verdict
 * other than wired crashes here, so that the crash text carries the reason;
 * crash() ends in crash_done's PSCI SYSTEM_RESET, a warm reset the black box
 * survives. Whether that reset takes the board down when a secondary issues it
 * is still unknown; if it does not, CPU0's 15 s start deadline fires with
 * stage 0x44 and resets from CPU0.
 *
 * residue is read here on every path, so a "stuck" verdict, which stops before
 * any CNTHP line, still shows which of 26 and 28 stayed pending.
 */
static int
t234_hvt_finish(unsigned const cpu, paddr_t const sgi, int const verdict,
                const char *const reason, int const intr)
{
	_Uint32t const    residue = in32(sgi + ARM_GICR_ISPENDR0) & (B26 | B28);
	const char *const vname   = t234_hvt_verdict_name(verdict);

	kprintf("t234: hvtimer cpu %d verdict=%s reason=%s residue=%x qtime_intr=%d\n",
	        cpu, vname, reason, residue, intr);

	if (verdict != T234_HVT_WIRED && t234_hvt_policy == T234_HVT_STOP) {
		crash("t234: hvtimer STOP cpu %d verdict=%s reason=%s: el2-host gives procnto its clock on INTID %d, which this core has not shown wired; stopping before procnto (fallback: -Q enable,el1-host, images el1h-p*)\n",
		      cpu, vname, reason, intr);
	}
	return verdict;
}

/*
 * Called from the GIC wrapper (init_intrinfo.c, step 8) under el2-host only,
 * policy stop or continue, once that core has shown EL2 with E2H and TGE set.
 * sgi is the SGI/PPI frame of the redistributor the library bound, already
 * checked against the board table. Returns the verdict; under -tstop it does
 * not return unless the verdict is wired.
 */
int
t234_hvt_probe(unsigned const cpu, paddr_t const sgi)
{
	paddr_t const       frame   = sgi - ARM_GICR_SGI_BASE_OFFSET;
	_Uint64t const      cps     = t234_cps();
	int const           intr    = (int)lsp.qtime.p->intr;
	int                 verdict = T234_HVT_INCONCLUSIVE;
	const char         *reason  = NULL;
	struct t234_hvt_run hp;
	struct t234_hvt_run hv;
	_Uint32t            gicd_ctlr, igroupr0, isen, isact, cfg1, prio26, prio28;
	_Uint32t            base, moved;
	_Uint64t            cntvoff, hpctl0, hvctl0, hpcval0, hvcval0;
	unsigned            sec, edge26, edge28, rose26, fell26, ctl_ok;
	char                ppi[8];

	/* 1. Guards. If either fails, no timer is touched. */
	if ((aa64_sr_rd64(daif) & 0xc0u) != 0xc0u) {
		return t234_hvt_finish(cpu, sgi, T234_HVT_INCONCLUSIVE, "daif", intr);
	}
	if ((in32(frame + ARM_GICR_WAKER) & T234_WAKER_ASLEEP) != 0) {
		return t234_hvt_finish(cpu, sgi, T234_HVT_INCONCLUSIVE, "asleep", intr);
	}

	/*
	 * 2. Context, read only. IGROUPR0 is printed and never judged: it is RAZ/WI
	 * to Non-secure software when GICD_CTLR.DS is 0 (VENDOR_CLAIM, GICv3
	 * §12.11.12). On a secondary hvctl is the first reading of what CPU_ON
	 * leaves in CNTHV_CTL_EL2, which nothing else on that core writes.
	 */
	gicd_ctlr = in32(T234_GICD_BASE + ARM_GICD_CTLR);
	sec       = (in32(T234_GICD_BASE + ARM_GICD_TYPER) & GICD_TYPER_SecurityExtn) != 0;
	igroupr0  = in32(sgi + ARM_GICR_IGROUPR0);
	isen      = in32(sgi + ARM_GICR_ISENABLER0);
	isact     = in32(sgi + ARM_GICR_ISACTIVER0);
	cfg1      = in32(sgi + ARM_GICR_ICFGR1);
	prio26    = (in32(sgi + ARM_GICR_IPRIORITYR6) >> 16) & 0xffu;
	prio28    = in32(sgi + ARM_GICR_IPRIORITYR7) & 0xffu;
	edge26    = t234_hvt_edge(cfg1, 26u);
	edge28    = t234_hvt_edge(cfg1, 28u);
	cntvoff   = aa64_sr_rd64(cntvoff_el2);
	hpctl0    = aa64_sr_rd64(cnthp_ctl_el2);
	hvctl0    = aa64_sr_rd64(T234_CNTHV_CTL);
	hpcval0   = aa64_sr_rd64(cnthp_cval_el2);
	hvcval0   = aa64_sr_rd64(T234_CNTHV_CVAL);

	if (debug_flag > 1) {
		kprintf("t234: hvtimer cpu %d ctx gicd_ctlr=%x sec=%d igroupr0=%x isen=%x isact=%x cfg1=%x prio26=%x prio28=%x cntvoff=%L hpctl=%x hvctl=%x\n",
		        cpu, gicd_ctlr, sec, igroupr0, isen, isact, cfg1, prio26,
		        prio28, cntvoff, (unsigned)hpctl0, (unsigned)hvctl0);
	}

	/* 3. Quiesce: both outputs deassert, then 26 and 28 must leave pending. */
	aa64_sr_wr64(cnthp_ctl_el2, 0);
	aa64_sr_wr64(T234_CNTHV_CTL, 0);
	isb();
	(void)t234_hvt_poll(sgi, B26 | B28, 0, cps);
	t234_hvt_clear_edge(sgi);
	base = in32(sgi + ARM_GICR_ISPENDR0) & (B26 | B28);
	if (base != 0) {
		t234_hvt_restore(sgi, hpcval0, hvcval0);
		return t234_hvt_finish(cpu, sgi, T234_HVT_INCONCLUSIVE, "stuck", intr);
	}

	/* 4. Positive control on INTID 26. */
	t234_hvt_run(T234_HVT_HP, sgi, B26, cps, &hp);
	rose26 = (hp.on & B26) != 0 && (base & B26) == 0;
	fell26 = (hp.mask & B26) == 0;
	ctl_ok = hp.istatus != 0 && rose26 && (fell26 || edge26 != 0);
	moved  = hp.on & ~base & ~hp.mask;
	t234_hvt_print_run(cpu, "CNTHP", 26u, base, &hp, moved);

	/*
	 * 5. Security, before CNTHV is armed. After the library's Non-secure write
	 * of 0xA0 to every SGI/PPI priority, a Non-secure Group 1 field reads back
	 * non-zero, and a Group 0 or Secure Group 1 field is RAZ/WI to Non-secure
	 * software (VENDOR_CLAIM, GICv3 §12.11.19). INTID 26 is Non-secure on this
	 * firmware, because Linux at NS-EL2 took it, so it is the reference: if 26
	 * reads 0 the rule itself does not hold here. CNTHV is not armed when 28
	 * looks Secure, because a Secure PPI firmware may have enabled could reach
	 * EL3 (HYPOTHESIS).
	 */
	if (sec != 0 && prio26 == 0) {
		verdict = T234_HVT_INCONCLUSIVE;
		reason  = "prio";
	} else if (sec != 0 && prio28 == 0) {
		verdict = T234_HVT_ABSENT;
		reason  = "secure-group";
	}

	if (reason != NULL) {
		if (debug_flag > 1) {
			kprintf("t234: hvtimer cpu %d CNTHV ppi=28 not armed (%s)\n", cpu, reason);
		}
	} else {
		unsigned rose28, fell28, wired28;
		_Uint32t moved_hv;

		/* 6. The same test on INTID 28. */
		t234_hvt_run(T234_HVT_HV, sgi, B28, cps, &hv);
		rose28   = (hv.on & B28) != 0 && (base & B28) == 0;
		fell28   = (hv.mask & B28) == 0;
		moved_hv = hv.on & ~base & ~hv.mask;
		wired28  = hv.istatus != 0 && rose28 && (fell28 || edge28 != 0);
		t234_hvt_print_run(cpu, "CNTHV", 28u, base, &hv, moved_hv);

		/*
		 * Verdicts, in the design's order (§4.4). Positive evidence for 28
		 * does not need the control; "absent" is emitted only when the control
		 * has just shown, on this core, that the readback works.
		 */
		if (hv.istatus == 0) {
			verdict = T234_HVT_INCONCLUSIVE;
			reason  = "hv-istatus";
		} else if (wired28) {
			verdict = T234_HVT_WIRED;
			reason  = ctl_ok ? "ok" : "control-failed";
		} else if (rose28 && !fell28 && edge28 == 0) {
			verdict = T234_HVT_INCONCLUSIVE;
			reason  = "no-deassert";
		} else if (!ctl_ok) {
			verdict = T234_HVT_INCONCLUSIVE;
			reason  = "control";
		} else if ((moved_hv & ~B28) != 0) {
			verdict = T234_HVT_ABSENT;
			reason  = t234_hvt_ppi_reason(ppi, moved_hv & ~B28);
		} else {
			verdict = T234_HVT_ABSENT;
			reason  = "no-ppi";
		}
	}

	/* 7. Restore, then the verdict line and the policy. */
	t234_hvt_restore(sgi, hpcval0, hvcval0);
	return t234_hvt_finish(cpu, sgi, verdict, reason, intr);
}
