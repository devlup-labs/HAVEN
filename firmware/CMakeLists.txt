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

# NODE_ID selects which node this ELF is provisioned as. Each ring node needs
# its own ELF (e.g. cmake -B build2 -DNODE_ID=2).
set(NODE_ID "1" CACHE STRING "Node id this firmware image is provisioned as (1..20)")
add_compile_definitions(HAVEN_NODE_ID=${NODE_ID})

if(DEFINED HAVEN_MAX_ADJ_NODES)
    add_compile_definitions(HAVEN_MAX_ADJ_NODES=${HAVEN_MAX_ADJ_NODES})
endif()

if(DEFINED HAVEN_ECHO_THRESHOLD)
    add_compile_definitions(HAVEN_ECHO_THRESHOLD=${HAVEN_ECHO_THRESHOLD})
endif()

if(DEFINED HAVEN_PROV_NUM_NODES)
    add_compile_definitions(HAVEN_PROV_NUM_NODES=${HAVEN_PROV_NUM_NODES})
endif()


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
