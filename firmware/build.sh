#!/bin/bash

set -e
cd firmware

if [ "$1" == "-c" ]; then
    rm -rf build
fi

cmake -B build
cmake --build build

if [ -f build/haven.elf ]; then
    echo "Done!"
    exit 0
else
    echo "Failed!"
    exit 1
fi