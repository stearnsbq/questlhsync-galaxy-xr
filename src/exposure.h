/* Metadata is a duration in ns. Zero is unknown, never a short exposure. */
static int gxr_accept_exposure(unsigned long exposure, unsigned long cutoff) {
    return exposure > 0 && exposure <= cutoff;
}

/* Bound while parsing: atoi can wrap a malformed environment value. */
static unsigned long gxr_parse_exposure(const char *text) {
    unsigned long value = 0;
    if (!text || !*text) return 0;
    for (; *text; text++) {
        if (*text < '0' || *text > '9') return 0;
        value = value * 10 + (unsigned long)(*text - '0');
        if (value > 10000000UL) return 0;
    }
    return value;
}
