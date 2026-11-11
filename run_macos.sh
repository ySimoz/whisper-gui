#!/usr/bin/env bash
# ==============================================================================
# Whisper GUI - macOS Automated Setup & Launcher
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Starting Whisper GUI (macOS) ==="

# 1. Ensure Homebrew paths are in PATH
if [ -d "/opt/homebrew/bin" ]; then
    export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
elif [ -d "/usr/local/bin" ]; then
    export PATH="/usr/local/bin:$PATH"
fi

# 2. Check Python (prefer Python 3.12/3.11 for ML & onnxruntime wheel compatibility)
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Error: Python 3 is not installed on this system."
    echo "Install Python 3.12 via Homebrew: brew install python@3.12"
    exit 1
fi

# 3. Check FFmpeg
if ! command -v ffmpeg &>/dev/null; then
    echo "Warning: ffmpeg was not detected."
    echo "Whisper GUI requires FFmpeg for audio processing."
    echo "Install via Homebrew: brew install ffmpeg"
    echo "Continuing anyway..."
fi

# 4. Virtual Environment Setup
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    NEED_INSTALL=1
fi

source "$VENV_DIR/bin/activate"

# 5. Check or Install Dependencies
if [ "$NEED_INSTALL" = "1" ] || [ "$1" = "--install" ]; then
    echo "Installing application dependencies..."
    pip install --upgrade pip
    pip install -e .
fi

# 6. Launch Application
echo "Launching Whisper GUI..."
exec python "$SCRIPT_DIR/main.py" "$@"
