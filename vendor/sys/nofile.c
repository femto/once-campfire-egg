/* Raises the soft limit on open files to the hard one, as servers do (the
 * Rust app does it at start): each WebSocket holds two descriptors here, and
 * containers often start with a soft limit of 1024. Returns the limit then
 * in force, or -1 if it cannot be read. */
#include <sys/resource.h>
#ifdef __APPLE__
#include <limits.h>
#endif

long cf_raise_nofile(void) {
    struct rlimit limit;
    if (getrlimit(RLIMIT_NOFILE, &limit) != 0) return -1;
    if (limit.rlim_cur < limit.rlim_max) {
        struct rlimit raised = limit;
        raised.rlim_cur = limit.rlim_max;
#ifdef __APPLE__
        /* macOS refuses more than OPEN_MAX for a process. */
        if (raised.rlim_cur > OPEN_MAX) raised.rlim_cur = OPEN_MAX;
#endif
        if (setrlimit(RLIMIT_NOFILE, &raised) == 0) limit = raised;
    }
    return limit.rlim_cur == RLIM_INFINITY ? 0x7fffffffL : (long)limit.rlim_cur;
}
