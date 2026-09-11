/*
 * Copyright 2026 the qnx-linux-dual-vm-proxy authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * trcctl — put a marker into a running kernel trace, or stop it.
 *
 * Phase 3b, checklist 7b: the M4 dry run's trace control, specified in
 * results/orin-native-port/20260909T1100Z/m4-dryrun-design.md §5.2, D3 and D8
 * (revision 2).
 *
 * tracelogger in ring mode writes its events only when it gets SIGINT or when
 * some process calls TraceEvent(_NTO_TRACE_STOP), and then exits ([tracelogger],
 * VENDOR_CLAIM). A background job in a non-interactive shell may start with
 * SIGINT ignored, and bwait passes dispositions through unchanged (bwait.c:276),
 * so the dry run stops the ring from a separate process first and signals only
 * if that fails. The same process brackets the workload with user string events,
 * which show in the trace itself whether the ring held the whole window.
 *
 *   trcctl -m ID TEXT   TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT, ID, TEXT)
 *                       (sys/trace.h:63); ID 0-1023 (:163-164), TEXT 1-63 bytes
 *   trcctl -x           TraceEvent(_NTO_TRACE_STOP) (sys/trace.h:42)
 *
 * One line each:
 *
 *   TRCCTL insert id=<n> text=<t> rc=<r> errno=<e>
 *   TRCCTL stop rc=<r> errno=<e>
 *
 * errno is 0 unless TraceEvent() returned -1. Control commands such as STOP need
 * the PROCMGR_AID_TRACE ability, which root is allowed; inserting a user event
 * needs none ([traceevent]). That the event is captured is a separate question,
 * which the probe capture answers on every run.
 *
 * The dry run's marker IDs: 1 m4d-probe, 10 m4d-w1-start, 20 m4d-ipc-start,
 * 21 m4d-ipc-end.
 *
 * What it deliberately does not do: no retry and no wait. The caller bounds the
 * wait for tracelogger to exit.
 *
 * Exit: 0 when TraceEvent() did not return -1, 1 when it did, 2 on a malformed
 * command line.
 */

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/neutrino.h>
#include <sys/trace.h>

#define MAX_TEXT        63u

static int
usage(void)
{
	fprintf(stderr,
	        "usage: trcctl -m ID TEXT   insert a user string event (ID 0-%u, TEXT 1-%u bytes)\n"
	        "       trcctl -x           TraceEvent(_NTO_TRACE_STOP)\n"
	        "  exit: 0 TraceEvent() did not return -1, 1 it did, 2 usage\n",
	        (unsigned)_NTO_TRACE_USERLAST, MAX_TEXT);
	return 2;
}

static int
stop(void)
{
	int const rc = TraceEvent((int)_NTO_TRACE_STOP);
	int const e  = (rc == -1) ? errno : 0;

	printf("TRCCTL stop rc=%d errno=%d\n", rc, e);
	fflush(stdout);
	return (rc == -1) ? 1 : 0;
}

static int
insert(const char *const id_arg, const char *const text)
{
	char         *end = NULL;
	unsigned long id;
	size_t const  len = strlen(text);

	if (id_arg[0] < '0' || id_arg[0] > '9') {
		return usage();
	}
	errno = 0;
	id = strtoul(id_arg, &end, 10);
	if (errno != 0 || *end != '\0' || id > _NTO_TRACE_USERLAST || len < 1u || len > MAX_TEXT) {
		return usage();
	}

	int const rc = TraceEvent((int)_NTO_TRACE_INSERTUSRSTREVENT, (int)id, text);
	int const e  = (rc == -1) ? errno : 0;

	printf("TRCCTL insert id=%lu text=%s rc=%d errno=%d\n", id, text, rc, e);
	fflush(stdout);
	return (rc == -1) ? 1 : 0;
}

int
main(int argc, char **argv)
{
	if (argc == 2 && strcmp(argv[1], "-x") == 0) {
		return stop();
	}
	if (argc == 4 && strcmp(argv[1], "-m") == 0) {
		return insert(argv[2], argv[3]);
	}
	return usage();
}
