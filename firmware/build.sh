#!/bin/bash

set -e
# Navigate to the directory containing this script
cd "$(dirname "$0")"

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