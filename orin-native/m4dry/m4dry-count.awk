# m4dry-count.awk: per-window counts over
#   traceprinter -n -p 'M4H|%C|%Z|%z|%e|' -f <kev>
# Run as: gawk -F'|' -v w=<window> -v qpid=<pid|none> -f m4dry-count.awk
# Prints only M4D lines. gawk only: uses and() and strtonum().
# Each event is classified twice (m4-dryrun-design.md §5.4):
#  - by name: the subtype against the suffixes of the _NTO_TRACE_QVM_*
#    constants (sys/trace.h:286-293);
#  - by number: when the class looks like Class 10 (QVM, HYP or "Class 10"),
#    %e as an event number 0-7, bare or with class 10 in bits 10-14
#    (sys/trace.h:237-239, :370).
# How traceprinter prints the class, the subtype and %e is HYPOTHESIS, so the
# two classifications are counted separately and disagreements are reported.
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
# evnum: the Class-10 event number that %e carries, or -1.
# 31744 = 0x1f<<10 (the class bits), 10240 = 10<<10, 1023 = 0x3ff (the event bits).
function evnum(s,   v) {
	if (s ~ /^0[xX][0-9a-fA-F]+$/) v = strtonum(s)
	else if (s ~ /^[0-9]+$/) v = s + 0
	else return -1
	if (v <= 7) return v
	if (and(v, 31744) == 10240 && and(v, 1023) <= 7) return and(v, 1023)
	return -1
}
BEGIN {
	id["GUEST_ENTER"] = 0; id["GUEST_EXIT"] = 1; id["CREATE_VCPU_THREAD"] = 2
	id["RAISE_INTR"] = 3; id["LOWER_INTR"] = 4; id["TIMER_CREATE"] = 5
	id["TIMER_FIRE"] = 6; id["CYCLES"] = 7
}
/m4d-w1-start/  { mk_w1++ }
/m4d-ipc-start/ { mk_is++ }
/m4d-ipc-end/   { mk_ie++ }
$1 != "M4H"     { unformatted++; next }
{
	events++
	cls = trim($3); st = trim($4); ev = trim($5)
	hist[cls "|" st "|" ev]++
	isq = (toupper(cls) ~ /QVM|HYP|CLASS[ _]*0*10([^0-9]|$)/)
	byname = (st in id) ? id[st] : -1
	bynum = isq ? evnum(ev) : -1
	if (isq || byname >= 0) {
		qvm++
		if (byname >= 0) nname[byname]++
		if (bynum >= 0) nnum[bynum]++
		if (byname >= 0 && bynum >= 0) { if (byname == bynum) agree++; else conflict++ }
		else if (byname >= 0) name_only++
		else if (bynum >= 0) num_only++
		cid = (byname >= 0) ? byname : bynum
		if (cid >= 0) n[cid]++; else qother++
		if (byname != bynum && ndis++ < 3)
			print "M4D DISAGREE " w " name=" byname " num=" bynum " " substr($0, 1, 200)
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
		if (st ~ /THRUNNING|INT_ENTR|INT_EXIT/ && ksample[st]++ < 2) print "M4D SAMPLE " w " sub=" st " " substr($0, 1, 200)
	}
	if (qpid != "none" && st ~ /THRUNNING/ && match($0, /pid:[0-9]+/)) {
		p = substr($0, RSTART + 4, RLENGTH - 4)
		if (p == qpid && match($0, /tid:[0-9]+/)) thr[substr($0, RSTART + 4, RLENGTH - 4)]++
	}
}
END {
	nk = 0; np = 0
	for (h in hist) { nk++; if (np < 4096) { np++; print "M4D HIST " w " " h " " hist[h] } }
	printf "M4D QVM %s id0=%d id1=%d id2=%d id3=%d id4=%d id5=%d id6=%d id7=%d qvm_other=%d qvm_total=%d non_qvm=%d events=%d unformatted_lines=%d hist_keys=%d hist_printed=%d\n", w, n[0], n[1], n[2], n[3], n[4], n[5], n[6], n[7], qother, qvm, nonqvm, events, unformatted, nk, np
	printf "M4D QVMBY %s name=%d,%d,%d,%d,%d,%d,%d,%d num=%d,%d,%d,%d,%d,%d,%d,%d agree=%d name_only=%d num_only=%d conflict=%d\n", w, nname[0], nname[1], nname[2], nname[3], nname[4], nname[5], nname[6], nname[7], nnum[0], nnum[1], nnum[2], nnum[3], nnum[4], nnum[5], nnum[6], nnum[7], agree, name_only, num_only, conflict
	d = 0; for (o in offs) d++
	printf "M4D QVMFIELDS %s cycles_both_nonzero=%d cycles_zero_or_missing=%d exit_with_offset=%d offsets_distinct=%d exit_status_zero=%d\n", w, cyc_ok, cyc_bad, off_seen, d, status0
	t = 0; for (i in thr) if (t++ < 32) print "M4D QVMTID " w " tid=" i " thrunning=" thr[i]
	printf "M4D MARKERS %s w1_start=%d ipc_start=%d ipc_end=%d\n", w, mk_w1, mk_is, mk_ie
}
