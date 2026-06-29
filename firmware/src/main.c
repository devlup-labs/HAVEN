#include <stdint.h>

static inline void haven_print(const char *s) {
    register int r0 asm("r0") = 4; // SYS_WRITE0
    register const char *r1 asm("r1") = s;
    asm volatile(
        "bkpt 0xAB"
        :
        : "r"(r0), "r"(r1)
        : "memory"
    );
}

int main(void) {
    haven_print("HAVEN boot\n");
    while(1);
    return 0;
}


