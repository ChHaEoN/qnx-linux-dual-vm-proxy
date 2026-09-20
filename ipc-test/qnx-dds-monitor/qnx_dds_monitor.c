/* QNX-side DDS subscriber, shaped like ipc-test/qnx-safety-monitor/monitor.c:
   Compute publishes a Claim, Safety judges it and publishes a Verdict.
   Functional only -- no timing claim. */
#include "dds/dds.h"
#include "av.h"
#include <stdio.h>

#define CONF_MIN 60u
#define INFER_US_MAX 100000u

int main(void)
{
    dds_entity_t p = dds_create_participant(DDS_DOMAIN_DEFAULT, NULL, NULL);
    if (p < 0) { printf("participant: %s\n", dds_strretcode(-p)); return 1; }

    dds_entity_t tc = dds_create_topic(p, &av_Claim_desc, "AvClaim", NULL, NULL);
    dds_entity_t tv = dds_create_topic(p, &av_Verdict_desc, "AvVerdict", NULL, NULL);
    if (tc < 0 || tv < 0) { printf("topic failed\n"); return 1; }

    dds_qos_t *q = dds_create_qos();
    dds_qset_reliability(q, DDS_RELIABILITY_RELIABLE, DDS_SECS(1));
    dds_qset_history(q, DDS_HISTORY_KEEP_ALL, 0);

    dds_entity_t r = dds_create_reader(p, tc, q, NULL);
    dds_entity_t w = dds_create_writer(p, tv, q, NULL);
    if (r < 0 || w < 0) { printf("endpoint failed\n"); return 1; }

    printf("qnx-dds-monitor: waiting for claims\n");
    fflush(stdout);

    void *s[1] = { NULL };
    dds_sample_info_t si[1];
    unsigned seen = 0;

    for (;;) {
        dds_return_t n = dds_take(r, s, si, 1, 1);
        if (n > 0 && si[0].valid_data) {
            av_Claim *c = (av_Claim *)s[0];
            av_Verdict v;
            v.seq = c->seq;
            v.reason = 0;
            if (c->cls > 7)                     v.reason = 1;
            else if (c->conf > 100)             v.reason = 2;
            else if (c->conf < CONF_MIN)        v.reason = 3;
            else if (c->inference_us > INFER_US_MAX) v.reason = 4;
            v.accepted = (unsigned char)(v.reason == 0);
            dds_write(w, &v);
            printf("claim seq=%llu cls=%u conf=%u us=%u -> %s (reason=%u)\n",
                   (unsigned long long)c->seq, c->cls, c->conf, c->inference_us,
                   v.accepted ? "ACCEPT" : "REJECT", v.reason);
            fflush(stdout);
            dds_return_loan(r, s, n);
            if (++seen >= 20) break;
        }
        dds_sleepfor(DDS_MSECS(20));
    }
    dds_delete(p);
    return 0;
}
