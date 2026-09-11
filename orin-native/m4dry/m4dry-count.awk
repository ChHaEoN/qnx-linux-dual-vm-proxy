# m4dry-count.awk: per-window counts over
#   traceprinter -n -p 'M4H|%C|%Z|%z|' -f <kev>
# Run as: gawk -F'|' -v w=<window> -v qpid=<pid|none> -f m4dry-count.awk
# Prints only M4D lines. parse-m4dry.py's Counter is this file's port; change
# the two together (m4-dryrun-design.md §5.4, as amended in §13).
#
# Revision 3 (§13, D-a and D-b). Attempt 1 showed that traceprinter's %e prints
# an event sequence index, one higher per printed event, not the event ID. So
# the -p format no longer carries %e, and every event is classified by its
# printed class and subtype name only:
#  - class: QVM (VERIFIED, attempt 1); HYP and "Class 10" are still accepted;
#  - subtype: GUEST_ENTER 0, GUEST_EXIT 1, CREATE_VCPU_THREAD 2 and CYCLES 7
#    printed as the suffixes of the _NTO_TRACE_QVM_* constants
#    (sys/trace.h:286-293; VERIFIED, attempt 1);
#  - the interrupt events printed as INTR_RAISE and INTR_LOWER, the reverse
#    word order of the constants RAISE_INTR (3) and LOWER_INTR (4). Both
#    spellings are accepted, and mapping them to IDs 3 and 4 is HYPOTHESIS;
#  - no timer event appeared at the default settings, so both word orders are
#    accepted for TIMER_CREATE (5) and TIMER_FIRE (6) (HYPOTHESIS).
# A QVM-class event with any other subtype counts in qvm_other and is listed by
# name and count on an M4D QVMOTHER line. M4D HIST is keyed by class and
# subtype, so it is small and printed in full.
# Payloads are matched by field name only.
function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
function hexval(name) {
	if (match($0, name ":0x[0-9a-fA-F]+"))
		return substr($0, RSTART + length(name) + 3, RLENGTH - length(name) - 3)
	return ""
}
function nonzero(h) { return h ~ /[1-9a-fA-F]/ }
# canon: one spelling per hex value, so formatting cannot fake a new offset.
function canon(h) { h = tolower(h); sub(/^0+/, "", h); return h == "" ? "0" : h }
BEGIN {
	id["GUEST_ENTER"] = 0; id["GUEST_EXIT"] = 1; id["CREATE_VCPU_THREAD"] = 2
	id["INTR_RAISE"] = 3; id["RAISE_INTR"] = 3
	id["INTR_LOWER"] = 4; id["LOWER_INTR"] = 4
	id["TIMER_CREATE"] = 5; id["CREATE_TIMER"] = 5
	id["TIMER_FIRE"] = 6; id["FIRE_TIMER"] = 6
	id["CYCLES"] = 7
}
/m4d-w1-start/  { mk_w1++ }
/m4d-ipc-start/ { mk_is++ }
/m4d-ipc-end/   { mk_ie++ }
$1 != "M4H"     { unformatted++; next }
{
	events++
	cls = trim($3); st = trim($4)
	hist[cls "|" st]++
	isq = (toupper(cls) ~ /QVM|HYP|CLASS[ _]*0*10([^0-9]|$)/)
	cid = (st in id) ? id[st] : -1
	if (isq || cid >= 0) {
		qvm++
		if (cid >= 0) n[cid]++
		else { qother++; other[st]++ }
		if (cid == 7) {
			e = hexval("at_entry"); x = hexval("at_exit")
			if (e != "" && x != "" && nonzero(e) && nonzero(x)) cyc_ok++; else cyc_bad++
		}
		if (cid == 1) {
			o = hexval("clockcycles_offset")
			if (o != "") { off_seen++; offs[canon(o)] = 1 }
			s = hexval("status")
			if (s != "" && !nonzero(s)) status0++
		}
		sk = (cid >= 0) ? "id" cid : "sub=" st
		if (qsample[sk]++ < 3) print "M4D SAMPLE " w " " sk " " substr($0, 1, 200)
	} else {
		nonqvm++
		if (st ~ /THRUNNING|INT_/ && ksample[st]++ < 2) print "M4D SAMPLE " w " sub=" st " " substr($0, 1, 200)
	}
	if (qpid != "none" && st ~ /THRUNNING/ && match($0, /pid:[0-9]+/)) {
		p = substr($0, RSTART + 4, RLENGTH - 4)
		if (p == qpid && match($0, /tid:[0-9]+/)) thr[substr($0, RSTART + 4, RLENGTH - 4)]++
	}
}
END {
	nk = 0; np = 0
	for (h in hist) { nk++; if (np < 4096) { np++; print "M4D HIST " w " " h " " hist[h] } }
	no = 0; nop = 0
	for (s in other) { no++; if (nop < 64) { nop++; print "M4D QVMOTHER " w " sub=" s " n=" other[s] } }
	printf "M4D QVM %s id0=%d id1=%d id2=%d id3=%d id4=%d id5=%d id6=%d id7=%d qvm_other=%d qvm_total=%d non_qvm=%d events=%d unformatted_lines=%d hist_keys=%d hist_printed=%d other_names=%d other_printed=%d\n", w, n[0], n[1], n[2], n[3], n[4], n[5], n[6], n[7], qother, qvm, nonqvm, events, unformatted, nk, np, no, nop
	d = 0; for (o in offs) d++
	printf "M4D QVMFIELDS %s cycles_both_nonzero=%d cycles_zero_or_missing=%d exit_with_offset=%d offsets_distinct=%d exit_status_zero=%d\n", w, cyc_ok, cyc_bad, off_seen, d, status0
	t = 0; for (i in thr) if (t++ < 32) print "M4D QVMTID " w " tid=" i " thrunning=" thr[i]
	printf "M4D MARKERS %s w1_start=%d ipc_start=%d ipc_end=%d\n", w, mk_w1, mk_is, mk_ie
}
