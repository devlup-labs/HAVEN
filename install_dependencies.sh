#!/bin/bash

set -e

echo "Updating package lists..."
sudo apt-get update

echo "Installing CMake, ARM GCC compiler, and other dependencies..."
sudo apt-get install -y cmake gcc-arm-none-eabi gnome-terminal wget python3

echo "Downloading Renode (v1.15.3)..."
wget https://github.com/renode/renode/releases/download/v1.15.3/renode_1.15.3_amd64.deb -O /tmp/renode.deb

echo "Installing Renode..."
sudo dpkg -i /tmp/renode.deb || sudo apt-get install -f -y

echo "Cleaning up..."
rm /tmp/renode.deb

echo "Dependencies installed successfully!"

