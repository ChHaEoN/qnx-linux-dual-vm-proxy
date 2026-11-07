/* vss_driver.c -- the kind 4 test driver (sdv Phase 2; the kind 4 wire
 * specification, section 16.1).
 *
 * It includes monitor.c with main renamed, as ipc-test/qnx-someip/someip.c does,
 * so it reaches the monitor's statics and sees exactly the translation unit the
 * vss build compiles: tests/test_monitor_vss.py and tests/test_monitor_kind4.py
 * build it with the vss build's flags (-DMONITOR_EXT_KINDS=0x10
 * -ffp-contract=off -I sdv-out/gen) under -Wformat=2 -Wundef -Werror, which is
 * C5's driver compile. One mode per run:
 *
 *   vss_driver           the generated contract's constants as monitor.c's own
 *                        includes see them, and the X-macro table (C5, C20, C30)
 *   vss_driver table     the monitor's compiled struct table, row by row, and
 *                        what vss_profile_find() returns for every id 0..255 (C31)
 *   vss_driver reasons   reason_name() for every reason byte 0..255
 *   vss_driver coeffs    vss_tan()'s coefficients, as %a (C19)
 *   vss_driver tan       one x per stdin line (any strtod form): vss_tan(x) as %a (C19)
 *   vss_driver kin       "|v| |delta| L_mm" per stdin line: vss_kinematics()'s
 *                        psi_dot_kin and a_y_kin as %a (C19)
 *   vss_driver judge     one 64-byte frame per stdin line, 128 hex digits:
 *                        "verdict reason name" from the monitor's check_claim(),
 *                        which judge_frame() calls for every transport
 *   vss_driver fnv       bytes in hex per stdin line (an empty line is no bytes):
 *                        vss_fnv1_32() as %08X (C29)
 *   vss_driver uids      five hex UIDs per stdin line: vss_uids_digest(), the
 *                        self-check's serialisation by shifts, as %08X (C29)
 *   vss_driver selfcheck the self-check on the compiled contract: "computed X
 *                        header X consistent N"
 *   vss_driver log       the kind 4 console limiter with a scripted clock, one
 *                        event per stdin line (C24-C27):
 *                          F NOW_NS SEQ PROFILE REASON   vss_log() on a frame
 *                                                        with that seq and id
 *                          E                             vss_log_end(), the
 *                                                        session-end flush
 *                        stdout carries exactly the lines the limiter prints
 *
 * WP4 added the last four (sdv Phase 2).
 *
 * What this does NOT show: anything about the guest build. qcc output cannot
 * run here, and this is gcc on the PC.
 */
#if !defined(MONITOR_EXT_KINDS)
#error "build the driver as the vss build is built: -DMONITOR_EXT_KINDS=0x10 -I sdv-out/gen"
#endif

#define main monitor_main
#include "../ipc-test/qnx-safety-monitor/monitor.c"
#undef main

#define VSS_DRIVER_PROFILE(id, l_mm, v_max, a_max, delta_max, v26_lo, v26_hi, ay26_max, tol26, v_tol) \
	printf("profile %u %u %a %a %a %a %a %a %a %a\n", (unsigned)(id), (unsigned)(l_mm), \
	       (double)(v_max), (double)(a_max), (double)(delta_max), (double)(v26_lo), \
	       (double)(v26_hi), (double)(ay26_max), (double)(tol26), (double)(v_tol));

static void drv_contract(void)
{
	printf("ext_kinds 0x%02X\n", (unsigned)MONITOR_EXT_KINDS);
	printf("format %u\n", (unsigned)VSS_CONTRACT_FORMAT);
	printf("flt_eval_method %d\n", (int)__FLT_EVAL_METHOD__);
	printf("uids %08X %08X %08X %08X %08X\n", (unsigned)VSS_UID_SLOT0, (unsigned)VSS_UID_SLOT1,
	       (unsigned)VSS_UID_SLOT2, (unsigned)VSS_UID_SLOT3, (unsigned)VSS_UID_SLOT4);
	printf("digest %08X\n", (unsigned)VSS_CATALOG_DIGEST);
	printf("age_max_ms %u\n", (unsigned)VSS_AGE_MAX_MS);
	printf("consts %a %a %a\n", (double)VSS_DEG_PER_RAD, (double)VSS_RAD_PER_DEG, (double)VSS_M_PER_MM);
	VSS_PROFILE_TABLE(VSS_DRIVER_PROFILE)
	printf("ids %s count %u\n", VSS_PROFILE_IDS, (unsigned)VSS_PROFILE_COUNT);
}

static void drv_table(void)
{
	size_t i;
	unsigned id;

	for (i = 0; i < sizeof(vss_profiles) / sizeof(vss_profiles[0]); i++) {
		const struct vss_profile *r = &vss_profiles[i];
		printf("row %u %u %a %a %a %a %a %a %a %a\n", (unsigned)r->id, (unsigned)r->l_mm, r->v_max, r->a_max,
		       r->delta_max, r->v26_lo, r->v26_hi, r->ay26_max, r->tol26, r->v_tol);
	}
	for (id = 0; id < 256u; id++) {
		const struct vss_profile *r = vss_profile_find((uint8_t)id);
		printf("find %u %d\n", id, r == NULL ? -1 : (int)(r - vss_profiles));
	}
}

static void drv_reasons(void)
{
	unsigned r;

	for (r = 0; r < 256u; r++) {
		printf("reason %u %s\n", r, reason_name((uint8_t)r));
	}
}

static void drv_coeffs(void)
{
	size_t i;

	printf("sin");
	for (i = 0; i < sizeof(vss_tan_sin) / sizeof(vss_tan_sin[0]); i++) {
		printf(" %a", vss_tan_sin[i]);
	}
	printf("\ncos");
	for (i = 0; i < sizeof(vss_tan_cos) / sizeof(vss_tan_cos[0]); i++) {
		printf(" %a", vss_tan_cos[i]);
	}
	printf("\n");
}

/* One stdin line without its newline; 0 at the end of input. A line that does
 * not fit is an error, never split. */
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
		fprintf(stderr, "vss_driver: an input line longer than %u bytes\n", (unsigned)n - 2u);
		exit(2);
	}
	return 1;
}

static void drv_bad(const char *what, const char *line)
{
	fprintf(stderr, "vss_driver: not %s: '%s'\n", what, line);
	exit(2);
}

static double drv_double(const char *s, char **end, const char *line)
{
	double x;

	errno = 0;
	x = strtod(s, end);
	if (*end == s || errno != 0) {
		drv_bad("a number", line);
	}
	return x;
}

static void drv_tan(void)
{
	char line[512];

	while (drv_line(line, sizeof(line))) {
		char *end = NULL;
		double const x = drv_double(line, &end, line);

		if (*end != '\0') {
			drv_bad("one number", line);
		}
		printf("%a\n", vss_tan(x));
	}
}

static void drv_kin(void)
{
	char line[512];

	while (drv_line(line, sizeof(line))) {
		char *end = NULL;
		double const av = drv_double(line, &end, line);
		double const ad = drv_double(end, &end, line);
		unsigned long l_mm;
		const char *s = end;
		double kin, ay;

		errno = 0;
		l_mm = strtoul(s, &end, 10);
		if (end == s || *end != '\0' || errno != 0 || l_mm > 0xFFFFul) {
			drv_bad("|v| |delta| L_mm", line);
		}
		vss_kinematics(av, ad, (unsigned)l_mm, &kin, &ay);
		printf("%a %a\n", kin, ay);
	}
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

static void drv_fnv(void)
{
	char line[512];

	while (drv_line(line, sizeof(line))) {
		uint8_t b[sizeof(line) / 2u];
		size_t const n = strlen(line) / 2u;
		size_t i;

		if (strlen(line) % 2u != 0u) {
			drv_bad("bytes in hex", line);
		}
		for (i = 0; i < n; i++) {
			int const hi = drv_hex((unsigned char)line[2u * i]);
			int const lo = drv_hex((unsigned char)line[2u * i + 1u]);

			if (hi < 0 || lo < 0) {
				drv_bad("bytes in hex", line);
			}
			b[i] = (uint8_t)(hi * 16 + lo);
		}
		printf("%08X\n", (unsigned)vss_fnv1_32(b, n));
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
		uint32_t uid[5];
		char *end = line;
		unsigned i;

		for (i = 0; i < 5u; i++) {
			uid[i] = (uint32_t)drv_ull(end, &end, 16, 0xFFFFFFFFull, line);
		}
		if (*end != '\0') {
			drv_bad("five hex UIDs", line);
		}
		printf("%08X\n", (unsigned)vss_uids_digest(uid));
	}
}

static void drv_selfcheck(void)
{
	uint32_t const uid[5] = { VSS_UID_SLOT0, VSS_UID_SLOT1, VSS_UID_SLOT2, VSS_UID_SLOT3, VSS_UID_SLOT4 };

	printf("computed %08X header %08X consistent %d\n", (unsigned)vss_uids_digest(uid),
	       (unsigned)VSS_CATALOG_DIGEST, vss_contract_consistent());
}

/* The limiter on its own instance (all zero: a session's start), its clock
 * scripted by the input; the frame it sees carries only the seq and the id,
 * which are all its line prints besides the reason. */
static void drv_log(void)
{
	struct vss_log lg;
	char line[512];

	memset(&lg, 0, sizeof(lg));
	while (drv_line(line, sizeof(line))) {
		if (strcmp(line, "E") == 0) {
			vss_log_end(&lg);
		} else if (line[0] == 'F' && line[1] == ' ') {
			uint8_t buf[FRAME_TOTAL_BYTES];
			char *end = line + 2;
			unsigned long long const now = drv_ull(end, &end, 10, ~0ull, line);
			unsigned long long const seq = drv_ull(end, &end, 10, ~0ull, line);
			unsigned long long const id = drv_ull(end, &end, 10, 255u, line);
			unsigned long long const reason = drv_ull(end, &end, 10, VSS_LOG_REASONS - 1u, line);

			if (*end != '\0') {
				drv_bad("F NOW_NS SEQ PROFILE REASON", line);
			}
			memset(buf, 0, sizeof(buf));
			frame_put_u64(&buf[0], (uint64_t)seq);
			buf[FRAME_HEADER_BYTES + P_VSS_PROFILE] = (uint8_t)id;
			buf[FRAME_HEADER_BYTES + P_KIND] = KIND_VSS;
			vss_log(&lg, buf, (uint8_t)reason, (uint64_t)now);
		} else {
			drv_bad("F NOW_NS SEQ PROFILE REASON, or E", line);
		}
	}
	fflush(stdout);
}

int main(int argc, char **argv)
{
	if (argc == 1) {
		drv_contract();
		return 0;
	}
	if (argc == 2) {
		if (strcmp(argv[1], "table") == 0) {
			drv_table();
			return 0;
		}
		if (strcmp(argv[1], "reasons") == 0) {
			drv_reasons();
			return 0;
		}
		if (strcmp(argv[1], "coeffs") == 0) {
			drv_coeffs();
			return 0;
		}
		if (strcmp(argv[1], "tan") == 0) {
			drv_tan();
			return 0;
		}
		if (strcmp(argv[1], "kin") == 0) {
			drv_kin();
			return 0;
		}
		if (strcmp(argv[1], "judge") == 0) {
			drv_judge();
			return 0;
		}
		if (strcmp(argv[1], "fnv") == 0) {
			drv_fnv();
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
	fprintf(stderr, "vss_driver: usage: vss_driver [table|reasons|coeffs|tan|kin|judge|fnv|uids|selfcheck|log]\n");
	return 2;
}
