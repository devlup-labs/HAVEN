#include<stdint.h>

extern void main(void);
void Reset_Handler(void);

extern uint32_t _estack;
extern uint32_t _sidata;
extern uint32_t _sdata;
extern uint32_t _edata;
extern uint32_t _sbss;
extern uint32_t _ebss;

//vector table
__attribute__((section(".isr_vector")))
void(*const vector_table[])(void) = {
    (void(*)(void))& _estack,
    Reset_Handler
};

//RESET_HANDLER
void Reset_Handler(void){
    
    // copy variabkes from FLASH to RAM
    uint32_t *src, *dst;
    *src = _sidata;
    *dst = _sdata;

    while(dst < &_edata){
        *dst = *src;
        dst++;
        src++;
    }


    //set uninitialized values to 0
    dst = _sbss;
    while(dst < &_ebss){
        *dst = 0;
        dst++;
    }
    
    //call main
    main();
}
