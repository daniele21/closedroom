#!/bin/bash
# local-asr-server setup script for macOS and other systems
set -e

echo "============================================="
echo "Starting local-asr-server setup..."
echo "============================================="

OS="$(uname -s)"

if [ "$OS" = "Darwin" ]; then
    echo "macOS detected."
    if ! command -v brew &> /dev/null; then
        echo "WARNING: Homebrew not found. Homebrew is required to install system dependencies."
        echo "Please install Homebrew from https://brew.sh/ and run this script again."
        exit 1
    fi

    echo "Installing FFmpeg via Homebrew..."
    brew install ffmpeg
    
    echo ""
    echo "============================================="
    echo "macOS AUDIO SETUP:"
    echo "Multi-Output devices are created automatically"
    echo "when you start a recording. No manual setup needed."
    echo ""
    echo "Run 'local-asr doctor' to verify the configuration."
    echo "============================================="
    echo ""
else
    echo "Non-macOS system ($OS) detected."
    echo "Please make sure 'ffmpeg' is installed manually via your package manager."
fi

# Install Python package and dependencies
PACKAGE_SPEC="."
if [ "$OS" = "Darwin" ]; then
    PACKAGE_SPEC=".[app]"
fi
if command -v uv &> /dev/null; then
    echo "Using 'uv' to install package in editable mode..."
    uv pip install -e "$PACKAGE_SPEC"
else
    echo "Using 'pip' to install package in editable mode..."
    pip install -e "$PACKAGE_SPEC"
fi

echo "============================================="
echo "Setup completed successfully!"
echo "Run the server with: local-asr serve"
echo "============================================="
