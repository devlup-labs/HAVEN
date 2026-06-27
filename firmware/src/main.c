#include <stdint.h>

static inline void haven_print(const char *s) {
    register const char *r1 asm("r1") = s;
    asm volatile(
        "mov r0,#4\n"
        "bkpt 0xAB"
        :
        :
        "r"(r1)
        :
        "r0"
    );
}

void main(void) {
      haven_print("HAVEN boot\n");
      while(1);
  }


