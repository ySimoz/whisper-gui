#!/usr/bin/env bash
# ==============================================================================
# Whisper GUI - Linux Automated Setup & Launcher
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Starting Whisper GUI (Linux) ==="

# 1. Check Python
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is not installed on this system."
    echo "Please install Python 3.10+: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

# 2. Check FFmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "Warning: ffmpeg was not found in PATH."
    echo "Whisper GUI requires FFmpeg for audio processing."
    echo "Install with: sudo apt install ffmpeg  (Ubuntu/Debian) or sudo dnf install ffmpeg (Fedora)"
    echo "Continuing anyway, but audio loading might fail if FFmpeg is not bundled..."
fi

# 3. Virtual Environment Setup
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    NEED_INSTALL=1
fi

source "$VENV_DIR/bin/activate"

# 4. Check or Install Dependencies
if [ "$NEED_INSTALL" = "1" ] || [ "$1" = "--install" ]; then
    echo "Installing application dependencies..."
    pip install --upgrade pip
    pip install -e .
fi

# 5. Launch Application
echo "Launching Whisper GUI..."
exec python "$SCRIPT_DIR/main.py" "$@"
