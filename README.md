# 🎙️ Whisper GUI

A simple and powerful desktop application built with **Python**, **Qt (PySide6)**, **ffmpeg**, and **faster-whisper**. It automates audio transcription and exports polished Word (`.docx`) documents, allowing you to choose the exact audio length or range you want to transcribe.

---

## ✨ Features

- **📂 Easy Audio Import**:
  - Add tracks via file picker or **drag-and-drop** directly into the application.
  - Supports MP3, WAV, M4A, AAC, FLAC, OGG, OPUS, WMA, MP4, MKV, and more.
  - Queue multiple audio files for batch transcription.

- **✂️ Flexible Audio Length & Slicing (ffmpeg)**:
  - **Full Audio**: Transcribe the complete audio file.
  - **Custom Time Range**: Set exact Start and End times (`HH:MM:SS`) using time spinners or the visual slider.
  - **Quick Presets**: "First 5m", "First 10m", "First 15m", "First 30m", or "Full Length" buttons.
  - Slices audio with frame accuracy using ffmpeg and converts directly to 16kHz mono WAV for optimal Whisper speed.

- **🧠 Whisper Large Model & Fast Inference**:
  - Uses `faster-whisper` with the **`large-v3-turbo`** model by default (highest accuracy and speed balance).
  - Also supports `large-v3`, `medium`, `small`, `base`, and `tiny`.
  - CPU inference optimized with `int8` quantization and configurable thread count (default 6 threads for i7 6-core CPUs).
  - Voice Activity Detection (VAD) filter enabled by default to skip silent gaps.
  - Multilingual support: Auto-detect or select specific languages (Italian, English, Spanish, French, German, etc.).

- **📄 Polished Word (.docx) Export**:
  - Generates clean Microsoft Word documents (`.docx`) using `python-docx`.
  - Formatted metadata header: source file, audio duration, transcribed range, date/time, model, language, and speed factor.
  - Includes timestamp markers `[00:01:23 → 00:01:30]` or clean flowing paragraphs.
  - One-click buttons to **Open Word Document** or **Open Folder**.

- **⚡ Responsive, Non-Blocking UI**:
  - Background `QThread` execution prevents GUI freezes.
  - Live streaming preview: see transcribed sentences and timestamps in real time.
  - Progress bar with completion percentage and real-time processing speed multiplier (e.g. `20x real-time`).
  - Stop button cleanly terminates ffmpeg and Whisper without hanging.

---

## 🚀 Quick Start

### 1. Requirements

- Linux or macOS (or Windows)
- Python 3.10+
- `ffmpeg` and `ffprobe` installed on your system (e.g. `sudo pacman -S ffmpeg` or `sudo apt install ffmpeg`)
- [uv](https://docs.astral.sh/uv/) (recommended) or standard `pip`

### 2. Setup

Clone or open the repository, then create the virtual environment:

```bash
# Using uv (recommended)
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Or using standard Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Run the Application

Launch the desktop GUI:

```bash
python main.py
```

or via the command line script:

```bash
whisper-gui
```

---

## 🖥️ How to Use

1. **Add Audio Tracks**:
   - Click **➕ Add Audio Files** or drag and drop audio files from your file manager onto the queue.
2. **Select Length to Transcribe**:
   - Click any track in the queue.
   - Choose **Full Audio**, a **Quick Preset** (e.g. *First 15m*), or **Custom Time Range** to set start/end timestamps.
3. **Configure Model & Options**:
   - Select your desired model (default: `large-v3-turbo`).
   - Choose language (default: `Auto-detect`) or specify language (e.g., `Italian (it)`).
   - Set output directory or leave as default (saves alongside the audio file).
4. **Start Transcription**:
   - Click **▶ Start Transcription**.
   - Watch segments stream into the live transcript viewer with timestamps and progress metrics.
5. **Open Document**:
   - When finished, click **📄 Open Word Document (.docx)** to open the transcript in your office suite or **📁 Open Folder** to view the file.

---

## 📦 Bundling as a Standalone Application

You can bundle Whisper GUI into a standalone desktop application (`.exe` on Windows, `.app` on macOS, or standalone binary on Linux) using PyInstaller:

```bash
python scripts/bundle_app.py
```

This uses the included [`whisper_gui.spec`](file:///home/simo/Documents/whisper-gui/whisper_gui.spec) configuration, which bundles all faster-whisper assets, CTranslate2 binaries, Word `.docx` templates, and PySide6 Qt libraries into `dist/WhisperGUI`.

### Bundling FFmpeg (Optional)
If you wish to distribute the app to users who do not have system `ffmpeg` installed:
- Simply place the `ffmpeg` and `ffprobe` binaries (or `ffmpeg.exe` / `ffprobe.exe` on Windows) inside a `bin/` directory at the project root before running `python scripts/bundle_app.py`.
- The application will automatically find and use the bundled binaries across any OS!

---

## 🧪 Running Tests

A full suite of unit and integration tests is included:

```bash
.venv/bin/pytest -v
```

Tests cover:
- Cross-platform process termination and binary finding
- Audio probing (`ffprobe`) and ffmpeg duration trimming
- Graceful cancellation of ffmpeg processes
- Word (`.docx`) document structure, tables, and timestamp styles
- Qt GUI widgets (Range Selector, Settings, Track List, Transcript Viewer)
- Non-fullscreen responsive layout scaling
- End-to-end background worker pipeline
