ENTRY(Reset_Handler)

MEMORY {
    FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 256K
    RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 64K
}

/* Top of the stack */ 
_estack = ORIGIN(RAM) + LENGTH(RAM);

SECTIONS {

    .text : {
        . = ALIGN(4);
        *(.text)
        *(.text*)
        *(.rodata)
        *(rodata*)
        . = ALIGN(4);
    } > FLASH

    .data : {
        . = ALIGN(4);
        *(.data)
        *(.data*)
        . = ALIGN(4);
    } > RAM AT > FLASH

    .bss : {
        . = ALIGN(4);
        *(.bss)
        *(.bss*)
        . = ALIGN(4);
    } > RAM
}