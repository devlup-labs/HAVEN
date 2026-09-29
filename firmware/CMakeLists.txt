cmake_minimum_required(VERSION 3.10)

set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

project(haven_firmware C)
set(CPU_FLAGS "-mcpu=cortex-m3 -mthumb")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${CPU_FLAGS} -O0 -g -Wall")
set(LINKER_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/linker.ld")


file(GLOB_RECURSE SOURCES
    CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c
)

add_executable(haven.elf ${SOURCES})
target_include_directories(haven.elf PRIVATE include)

add_compile_definitions(MBEDTLS_CONFIG_FILE="${CMAKE_CURRENT_SOURCE_DIR}/include/mbedtls_config.h")

target_link_options(haven.elf PRIVATE
    -T ${LINKER_SCRIPT}
    -nostartfiles
    --specs=nosys.specs
)

set(ENABLE_PROGRAMS OFF CACHE BOOL "" FORCE)
set(ENABLE_TESTING OFF CACHE BOOL "" FORCE)

add_subdirectory(mbedtls)
target_link_libraries(haven.elf mbedtls)
