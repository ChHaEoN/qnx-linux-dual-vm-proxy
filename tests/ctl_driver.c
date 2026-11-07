/* ctl_driver.c -- the kind 2 test driver (Phase 8 WP1a; the Phase 8 specification, section 3 item 4).
 *
 * It includes monitor.c with main renamed, on tests/vss_driver.c's pattern, so it reaches the monitor's statics
 * and sees exactly the translation unit the ctl build compiles: tests/test_monitor_ctl.py builds it with the ctl
 * build's flags (-DMONITOR_EXT_KINDS=0x14 -ffp-contract=off -I sdv-out/gen -I <a directory holding vss_ctl.h>)
 * under -Wformat=2 -Wundef -Werror. One mode per run:
 *
 *   ctl_driver constants  the kind 2 contract's constants as monitor.c's own includes see them, and the
 *                         X-macro table
 *   ctl_driver table      the monitor's compiled struct table, row by row, and what ctl_profile_find()
 *                         returns for every id 0..255
 *   ctl_driver reasons    reason_name() for every reason byte 0..255
 *   ctl_driver judge      one 64-byte frame per stdin line, 128 hex digits: "verdict reason name" from the
 *                         monitor's check_claim(), which judge_frame() calls for every transport
 *   ctl_driver uids       seven hex UIDs per stdin line: ctl_uids_digest(), the self-check's serialisation
 *                         by shifts, as %08X
 *   ctl_driver selfcheck  the self-check on the compiled contract: "computed X header X consistent N"
 *   ctl_driver log        the kind 2 console limiter with a scripted clock, one event per stdin line:
 *                           F NOW_NS SEQ PROFILE REASON   ctl_log() on a frame with that seq and id
 *                           E                             ctl_log_end(), the session-end flush
 *                         stdout carries exactly the lines the limiter prints
 *
 * What this does NOT show: anything about the guest build. qcc output cannot run here, and this is gcc on the PC.
 */
#if !defined(MONITOR_EXT_KINDS)
#error "build the driver as the ctl build is built: -DMONITOR_EXT_KINDS=0x14 -I sdv-out/gen -I <vss_ctl.h's directory>"
#endif

#define main monitor_main
#include "../ipc-test/qnx-safety-monitor/monitor.c"
#undef main

#define CTL_DRIVER_PROFILE(id, l_mm, v_max, a_max, jerk_max, steer_max, steer_rate_max, lat_acc_max) \
	printf("profile %u %u %a %a %a %a %a %a\n", (unsigned)(id), (unsigned)(l_mm), (double)(v_max), \
	       (double)(a_max), (double)(jerk_max), (double)(steer_max), (double)(steer_rate_max), \
	       (double)(lat_acc_max));

static void drv_constants(void)
{
	printf("ext_kinds 0x%02X\n", (unsigned)MONITOR_EXT_KINDS);
	printf("format %u\n", (unsigned)VSS_CTL_FORMAT);
	printf("uids %08X %08X %08X %08X %08X %08X %08X\n", (unsigned)VSS_CTL_UID_SLOT0, (unsigned)VSS_CTL_UID_SLOT1,
	       (unsigned)VSS_CTL_UID_SLOT2, (unsigned)VSS_CTL_UID_SLOT3, (unsigned)VSS_CTL_UID_SLOT4,
	       (unsigned)VSS_CTL_UID_SLOT5, (unsigned)VSS_CTL_UID_SLOT6);
	printf("digest %08X\n", (unsigned)VSS_CTL_DIGEST);
	printf("dt_max_ms %u\n", (unsigned)VSS_CTL_DT_MAX_MS);
	printf("consts %a %a %a %a\n", (double)VSS_CTL_TOL17, (double)VSS_CTL_OVERSPEED_FACTOR,
	       (double)VSS_CTL_OVERSPEED_MARGIN, (double)VSS_CTL_ROLLBACK_V);
	printf("m_per_mm %a\n", (double)VSS_M_PER_MM);
	VSS_CTL_PROFILE_TABLE(CTL_DRIVER_PROFILE)
	printf("ids %s count %u\n", VSS_CTL_PROFILE_IDS, (unsigned)VSS_CTL_PROFILE_COUNT);
	printf("log_cap %u\n", (unsigned)CTL_LOG_CAP);
}

static void drv_table(void)
{
	size_t i;
	unsigned id;

	for (i = 0; i < sizeof(ctl_profiles) / sizeof(ctl_profiles[0]); i++) {
		const struct ctl_profile *r = &ctl_profiles[i];
		printf("row %u %u %a %a %a %a %a %a\n", (unsigned)r->id, (unsigned)r->l_mm, r->v_max, r->a_max,
		       r->jerk_max, r->steer_max, r->steer_rate_max, r->lat_acc_max);
	}
	for (id = 0; id < 256u; id++) {
		const struct ctl_profile *r = ctl_profile_find((uint8_t)id);
		printf("find %u %d\n", id, r == NULL ? -1 : (int)(r - ctl_profiles));
	}
}

static void drv_reasons(void)
{
	unsigned r;

	for (r = 0; r < 256u; r++) {
		printf("reason %u %s\n", r, reason_name((uint8_t)r));
	}
}

/* One stdin line without its newline; 0 at the end of input. A line that does not fit is an error, never
 * split. */
static int drv_line(char *buf, size_t n)
{
	size_t len;

	if (fgets(buf, (int)n, stdin) == NULL) {
		return 0;
	}
	len = strlen(buf);
	if (len > 0u && buf[len - 1u] == '\n') {
		buf[--len] = '\0';
	} else if (!feof(stdin)) {
		fprintf(stderr, "ctl_driver: an input line longer than %u bytes\n", (unsigned)n - 2u);
		exit(2);
	}
	return 1;
}

static void drv_bad(const char *what, const char *line)
{
	fprintf(stderr, "ctl_driver: not %s: '%s'\n", what, line);
	exit(2);
}

static int drv_hex(int c)
{
	if (c >= '0' && c <= '9') {
		return c - '0';
	}
	if (c >= 'a' && c <= 'f') {
		return c - 'a' + 10;
	}
	if (c >= 'A' && c <= 'F') {
		return c - 'A' + 10;
	}
	return -1;
}

static void drv_judge(void)
{
	char line[512];

	while (drv_line(line, sizeof(line))) {
		uint8_t buf[FRAME_TOTAL_BYTES];
		uint8_t reason = RSN_OK;
		uint8_t verdict;
		size_t i;

		if (strlen(line) != 2u * FRAME_TOTAL_BYTES) {
			drv_bad("a 64-byte frame in hex", line);
		}
		for (i = 0; i < FRAME_TOTAL_BYTES; i++) {
			int const hi = drv_hex((unsigned char)line[2u * i]);
			int const lo = drv_hex((unsigned char)line[2u * i + 1u]);

			if (hi < 0 || lo < 0) {
				drv_bad("a 64-byte frame in hex", line);
			}
			buf[i] = (uint8_t)(hi * 16 + lo);
		}
		verdict = check_claim(&buf[FRAME_HEADER_BYTES], &reason);
		printf("%u %u %s\n", (unsigned)verdict, (unsigned)reason, reason_name(reason));
	}
}

static unsigned long long drv_ull(const char *s, char **end, int base, unsigned long long max, const char *line)
{
	unsigned long long x;

	while (*s == ' ') {
		s++;
	}
	if (base == 16 ? drv_hex((unsigned char)*s) < 0 : (*s < '0' || *s > '9')) {
		drv_bad("an unsigned number", line);     /* strtoull would take a sign, and wrap it */
	}
	errno = 0;
	x = strtoull(s, end, base);
	if (*end == s || errno != 0 || x > max) {
		drv_bad("an unsigned number in range", line);
	}
	return x;
}

static void drv_uids(void)
{
	char line[512];

	while (drv_line(line, sizeof(line))) {
		uint32_t uid[7];
		char *end = line;
		unsigned i;

		for (i = 0; i < 7u; i++) {
			uid[i] = (uint32_t)drv_ull(end, &end, 16, 0xFFFFFFFFull, line);
		}
		if (*end != '\0') {
			drv_bad("seven hex UIDs", line);
		}
		printf("%08X\n", (unsigned)ctl_uids_digest(uid));
	}
}

static void drv_selfcheck(void)
{
	uint32_t const uid[7] = { VSS_CTL_UID_SLOT0, VSS_CTL_UID_SLOT1, VSS_CTL_UID_SLOT2, VSS_CTL_UID_SLOT3,
	                          VSS_CTL_UID_SLOT4, VSS_CTL_UID_SLOT5, VSS_CTL_UID_SLOT6 };

	printf("computed %08X header %08X consistent %d\n", (unsigned)ctl_uids_digest(uid),
	       (unsigned)VSS_CTL_DIGEST, ctl_contract_consistent());
}

/* The limiter on its own instance (all zero: a session's start), its clock scripted by the input; the frame
 * it sees carries only the seq and the id, which are all its line prints besides the reason. */
static void drv_log(void)
{
	struct ctl_log lg;
	char line[512];

	memset(&lg, 0, sizeof(lg));
	while (drv_line(line, sizeof(line))) {
		if (strcmp(line, "E") == 0) {
			ctl_log_end(&lg);
		} else if (line[0] == 'F' && line[1] == ' ') {
			uint8_t buf[FRAME_TOTAL_BYTES];
			char *end = line + 2;
			unsigned long long const now = drv_ull(end, &end, 10, ~0ull, line);
			unsigned long long const seq = drv_ull(end, &end, 10, ~0ull, line);
			unsigned long long const id = drv_ull(end, &end, 10, 255u, line);
			unsigned long long const reason = drv_ull(end, &end, 10, CTL_LOG_REASONS - 1u, line);

			if (*end != '\0') {
				drv_bad("F NOW_NS SEQ PROFILE REASON", line);
			}
			memset(buf, 0, sizeof(buf));
			frame_put_u64(&buf[0], (uint64_t)seq);
			buf[FRAME_HEADER_BYTES + P_CTL_PROFILE] = (uint8_t)id;
			buf[FRAME_HEADER_BYTES + P_KIND] = KIND_CTL;
			ctl_log(&lg, buf, (uint8_t)reason, (uint64_t)now);
		} else {
			drv_bad("F NOW_NS SEQ PROFILE REASON, or E", line);
		}
	}
	fflush(stdout);
}

int main(int argc, char **argv)
{
	if (argc == 2) {
		if (strcmp(argv[1], "constants") == 0) {
			drv_constants();
			return 0;
		}
		if (strcmp(argv[1], "table") == 0) {
			drv_table();
			return 0;
		}
		if (strcmp(argv[1], "reasons") == 0) {
			drv_reasons();
			return 0;
		}
		if (strcmp(argv[1], "judge") == 0) {
			drv_judge();
			return 0;
		}
		if (strcmp(argv[1], "uids") == 0) {
			drv_uids();
			return 0;
		}
		if (strcmp(argv[1], "selfcheck") == 0) {
			drv_selfcheck();
			return 0;
		}
		if (strcmp(argv[1], "log") == 0) {
			drv_log();
			return 0;
		}
	}
	fprintf(stderr, "ctl_driver: usage: ctl_driver constants|table|reasons|judge|uids|selfcheck|log\n");
	return 2;
}
