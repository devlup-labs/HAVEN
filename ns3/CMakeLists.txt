cmake_minimum_required(VERSION 3.10)
project(haven_ns3 CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(PkgConfig REQUIRED)
pkg_check_modules(ZMQ REQUIRED libzmq)

# Find ns-3 libraries from the build directory
set(NS3_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../ns-3-dev")
set(NS3_BUILD_DIR "${NS3_DIR}/build")

include_directories(
    ${NS3_DIR}/build/include
    ${NS3_DIR}/src/core/model
    ${NS3_DIR}/src/network/model
    ${NS3_DIR}/src/point-to-point/model
    ${ZMQ_INCLUDE_DIRS}
)

link_directories(
    ${NS3_BUILD_DIR}/lib
    ${ZMQ_LIBRARY_DIRS}
)

add_executable(haven_csim haven_csim.cc)
target_link_libraries(haven_csim
    PRIVATE
    ${NS3_BUILD_DIR}/lib/libns3-dev-point-to-point-default.so
    ${NS3_BUILD_DIR}/lib/libns3-dev-network-default.so
    ${NS3_BUILD_DIR}/lib/libns3-dev-core-default.so
    ${ZMQ_LIBRARIES}
)
