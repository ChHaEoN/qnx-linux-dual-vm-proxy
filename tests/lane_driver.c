/* lane_driver.c -- the kind 6 test driver (C2b S3).
 *
 * It includes monitor.c with main renamed, on tests/ctl_driver.c's pattern, so it reaches the monitor's statics
 * and sees exactly the translation unit a lane build compiles: tests/test_monitor_lane.py builds it with a lane
 * build's flags (-DMONITOR_EXT_KINDS=0x50 or 0x54 -ffp-contract=off -I sdv-out/gen) under -Wformat=2 -Wundef
 * -Werror. One mode per run:
 *
 *   lane_driver constants  the switch value, the limiter's cap, the sin polynomial's domain and its coefficients
 *                          lane_sin_c[0..4] (%a)
 *   lane_driver table      the monitor's compiled profile table, row by row (%a), and what lane_profile_find()
 *                          returns for every id 0..255
 *   lane_driver reasons    reason_name() for every reason byte 0..255
 *   lane_driver judge      one 64-byte frame per stdin line, 128 hex digits: "verdict reason name" from the
 *                          monitor's check_claim(), which judge_frame() calls for every transport
 *   lane_driver sin        one hex float per stdin line (Python's float.hex()): lane_sin() of it, as %a
 *   lane_driver imminent   "ID FLAGS OFFSET HEADING ROOM SPEED" per stdin line, ID and FLAGS decimal, the rest hex
 *                          floats: rule 31's predicate lane_imminent() on that id's row, 0 or 1
 *   lane_driver selfcheck  the self-check on the compiled table: "consistent N"
 *   lane_driver log        the kind 6 console limiter with a scripted clock, one event per stdin line:
 *                            F NOW_NS SEQ PROFILE REASON   lane_log() on a frame with that seq and id
 *                            E                             lane_log_end(), the session-end flush
 *                          stdout carries exactly the lines the limiter prints
 *
 * What this does NOT show: anything about the guest build. qcc output cannot run here, and this is gcc on the PC.
 */
#if !defined(MONITOR_EXT_KINDS)
#error "build the driver as a lane build is built: -DMONITOR_EXT_KINDS=0x50 (or 0x54) -I sdv-out/gen"
#endif

#define main monitor_main
#include "../ipc-test/qnx-safety-monitor/monitor.c"
#undef main

static void drv_constants(void)
{
	printf("ext_kinds 0x%02X\n", (unsigned)MONITOR_EXT_KINDS);
	printf("log_cap %u\n", (unsigned)LANE_LOG_CAP);
	printf("sin_domain %a\n", (double)LANE_SIN_DOMAIN);
	printf("sin_c %a %a %a %a %a\n", lane_sin_c[0], lane_sin_c[1], lane_sin_c[2], lane_sin_c[3], lane_sin_c[4]);
	printf("rows %u\n", (unsigned)(sizeof(lane_profiles) / sizeof(lane_profiles[0])));
}

static void drv_table(void)
{
	size_t i;
	unsigned id;

	for (i = 0; i < sizeof(lane_profiles) / sizeof(lane_profiles[0]); i++) {
		const struct lane_profile *r = &lane_profiles[i];
		printf("row %u %u %a %a %a %a %a %a %a\n", (unsigned)r->id, (unsigned)r->conf_min, r->width_min,
		       r->width_max, r->k_max, r->h_max, r->veh_half_w, r->v_min, r->tlc_min);
	}
	for (id = 0; id < 256u; id++) {
		const struct lane_profile *r = lane_profile_find((uint8_t)id);
		printf("find %u %d\n", id, r == NULL ? -1 : (int)(r - lane_profiles));
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
		fprintf(stderr, "lane_driver: an input line longer than %u bytes\n", (unsigned)n - 2u);
		exit(2);
	}
	return 1;
}

static void drv_bad(const char *what, const char *line)
{
	fprintf(stderr, "lane_driver: not %s: '%s'\n", what, line);
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

static unsigned long long drv_ull(const char *s, char **end, unsigned long long max, const char *line)
{
	unsigned long long x;

	while (*s == ' ') {
		s++;
	}
	if (*s < '0' || *s > '9') {
		drv_bad("an unsigned number", line);     /* strtoull would take a sign, and wrap it */
	}
	errno = 0;
	x = strtoull(s, end, 10);
	if (*end == s || errno != 0 || x > max) {
		drv_bad("an unsigned number in range", line);
	}
	return x;
}

/* A hex float as Python's float.hex() writes it ("0x1.8000000000000p+1", "-0x0.0p+0"): strtod reads it exactly. */
static double drv_double(const char *s, char **end, const char *line)
{
	double x;

	while (*s == ' ') {
		s++;
	}
	if (!(s[0] == '0' || (s[0] == '-' && s[1] == '0'))) {
		drv_bad("a hex float", line);
	}
	x = strtod(s, end);
	if (*end == s) {
		drv_bad("a hex float", line);
	}
	return x;
}

static void drv_sin(void)
{
	char line[512];

	while (drv_line(line, sizeof(line))) {
		char *end = line;
		double const x = drv_double(line, &end, line);

		if (*end != '\0') {
			drv_bad("one hex float", line);
		}
		printf("%a\n", lane_sin(x));
	}
}

static void drv_imminent(void)
{
	char line[512];

	while (drv_line(line, sizeof(line))) {
		char *end = line;
		unsigned long long const id = drv_ull(end, &end, 255u, line);
		unsigned long long const f = drv_ull(end, &end, 255u, line);
		double const off = drv_double(end, &end, line);
		double const h = drv_double(end, &end, line);
		double const room = drv_double(end, &end, line);
		double const sp = drv_double(end, &end, line);
		const struct lane_profile *pr = lane_profile_find((uint8_t)id);

		if (*end != '\0' || pr == NULL) {
			drv_bad("ID FLAGS OFFSET HEADING ROOM SPEED with a compiled id", line);
		}
		printf("%d\n", lane_imminent(pr, (uint8_t)f, off, h, room, sp));
	}
}

static void drv_selfcheck(void)
{
	printf("consistent %d\n", lane_table_consistent());
}

/* The limiter on its own instance (all zero: a session's start), its clock scripted by the input; the frame
 * it sees carries only the seq and the id, which are all its line prints besides the reason. */
static void drv_log(void)
{
	struct lane_log lg;
	char line[512];

	memset(&lg, 0, sizeof(lg));
	while (drv_line(line, sizeof(line))) {
		if (strcmp(line, "E") == 0) {
			lane_log_end(&lg);
		} else if (line[0] == 'F' && line[1] == ' ') {
			uint8_t buf[FRAME_TOTAL_BYTES];
			char *end = line + 2;
			unsigned long long const now = drv_ull(end, &end, ~0ull, line);
			unsigned long long const seq = drv_ull(end, &end, ~0ull, line);
			unsigned long long const id = drv_ull(end, &end, 255u, line);
			unsigned long long const reason = drv_ull(end, &end, LANE_LOG_REASONS - 1u, line);

			if (*end != '\0') {
				drv_bad("F NOW_NS SEQ PROFILE REASON", line);
			}
			memset(buf, 0, sizeof(buf));
			frame_put_u64(&buf[0], (uint64_t)seq);
			buf[FRAME_HEADER_BYTES + P_LANE_PROFILE] = (uint8_t)id;
			buf[FRAME_HEADER_BYTES + P_KIND] = KIND_LANE;
			lane_log(&lg, buf, (uint8_t)reason, (uint64_t)now);
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
		if (strcmp(argv[1], "sin") == 0) {
			drv_sin();
			return 0;
		}
		if (strcmp(argv[1], "imminent") == 0) {
			drv_imminent();
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
	fprintf(stderr, "lane_driver: usage: lane_driver constants|table|reasons|judge|sin|imminent|selfcheck|log\n");
	return 2;
}
