#include "../src/exposure.h"
#define CHECK(expr) do { if (!(expr)) return __LINE__; } while (0)
int main(void) {
    CHECK(gxr_parse_exposure("10000000") == 10000000UL);
    CHECK(gxr_parse_exposure("3000000") == 3000000UL);
    CHECK(!gxr_parse_exposure("10000001"));
    CHECK(!gxr_parse_exposure("4297967296"));
    CHECK(!gxr_parse_exposure("99999999999999999999999999999"));
    CHECK(!gxr_parse_exposure("-1"));
    CHECK(!gxr_parse_exposure("5ms"));
    CHECK(!gxr_parse_exposure(""));
    CHECK(!gxr_parse_exposure(0));
    CHECK(!gxr_parse_exposure("0"));
    CHECK(!gxr_accept_exposure(0, 10000000UL));
    CHECK(gxr_accept_exposure(10000000UL, 10000000UL));
    CHECK(!gxr_accept_exposure(10000001UL, 10000000UL));
    CHECK(gxr_accept_exposure(3000000UL, 3000000UL));
    CHECK(!gxr_accept_exposure(3000001UL, 3000000UL));
    /* Sampled exposure range in the external tester's recording. */
    unsigned long samples[] = {3088800,3376800,3484800,3808800,3924000,
        4284000,4413600,5436000,6300000,6890400,7092000,7308000,7754400,7984800};
    for (unsigned int i=0; i<sizeof(samples)/sizeof(samples[0]); i++) {
        CHECK(!gxr_accept_exposure(samples[i], 3000000UL));
        CHECK(gxr_accept_exposure(samples[i], 10000000UL));
    }
    CHECK(!gxr_accept_exposure(7984800UL, 5000000UL));
    return 0;
}
