#!/bin/bash

set -e

# Navigate to the directory containing this script
cd "$(dirname "$0")"

# Flag handling
FLAG_CLEAN=0
FLAG_RUN=0
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -c) FLAG_CLEAN=1 ;;
        -r) FLAG_RUN=1 ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [ "$FLAG_CLEAN" -eq 1 ]; then
    rm -rf build
fi

cmake -B build
cmake --build build

if [ -f build/haven.elf ]; then
    echo ""
    echo "Done!"

    if [ "$FLAG_RUN" -eq 1 ]; then
        echo ""
        echo "---------- Firmware Output ----------"
        qemu-system-arm -M lm3s6965evb -nographic -kernel build/haven.elf -semihosting
    fi

    exit 0
else
    echo "Failed!"
    exit 1
fi