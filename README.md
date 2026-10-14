# Whisper GUI

A fast, modern desktop application built with **Python**, **Qt (PySide6)**, **FFmpeg**, **faster-whisper**, and optional **LLM Speech Polishing (DeepSeek V4.1 Flash, OpenAI, Groq)**. It automates audio transcription, trims and slices audio to your desired range, refines speech disfluencies, and exports formatted Microsoft Word (`.docx`) documents.

Runs natively on **Linux**, **macOS** (Apple Silicon M1-M4 & Intel), and **Windows**.

---

## Features

- **Queue & Audio Import**:
  - Add single audio files or entire folders.
  - Full **drag-and-drop** support.
  - Supports MP3, WAV, M4A, AAC, FLAC, OGG, OPUS, WMA, MP4, MKV, WEBM, and MOV.
- **Audio Length Trimming (FFmpeg)**:
  - Transcribe full tracks or select custom Start and End times (`HH:MM:SS`) with a responsive slider.
  - Frame-accurate audio extraction and conversion to 16kHz mono WAV for Whisper inference.
- **Faster-Whisper Inference & RAM Management**:
  - Uses `faster-whisper` with `large-v3-turbo` by default (highest accuracy and speed).
  - Also supports `large-v3`, `medium`, `small`, `base`, and `tiny`.
  - First-time automatic download from HuggingFace, followed by offline disk caching.
  - Live RAM monitor and instant **Unload Model** button to free system memory.
- **LLM Speech Polishing (Optional)**:
  - Automatically cleans transcription disfluencies (pauses, "umms", "uhs", repetitions, grammar slips) using **DeepSeek V4.1 Flash** (`deepseek-flash`), OpenAI (`gpt-4o-mini`), Groq (`llama-3.3-70b-versatile`), or any custom OpenAI-compatible endpoint.
  - Import your own `.md` instruction file or edit prompts live in the UI.
  - Preserves raw Whisper segments in real time while offering a dual view (Raw vs Polished).
- **Microsoft Word (.docx) Export**:
  - Outputs styled `.docx` files with metadata headers, timestamps, and polished text.
  - One-click buttons to **Open Document** in your default office suite or **Open Folder** in file manager / Finder.

---

## Automated 1-Click Launchers

To run Whisper GUI on another computer with automated environment setup:

### On Linux
```bash
git clone <your-repo-url>
cd whisper-gui
./run_linux.sh
```
*`run_linux.sh` automatically checks for `python3` and `ffmpeg`, creates `.venv`, installs dependencies, and launches the application.*

### On macOS
```bash
git clone <your-repo-url>
cd whisper-gui
./run_macos.sh
```
*`run_macos.sh` automatically configures Homebrew paths (`/opt/homebrew/bin` on Apple Silicon or `/usr/local/bin` on Intel), sets up `.venv`, and launches the application.*

---

## Manual Setup & Development

If you prefer using standard Python or `uv`:

```bash
# 1. Clone repository
git clone <your-repo-url>
cd whisper-gui

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Run tests (43 unit & integration tests)
pytest -v

# 5. Launch application
python main.py
```

---

## Shipping as a Standalone Desktop Application

To distribute Whisper GUI to other computers without requiring users to install Python:

```bash
# Activate your virtual environment and install PyInstaller
pip install pyinstaller

# Run the automated build script
python scripts/bundle_app.py
```

- **On Linux**: Produces a standalone distribution folder at `dist/WhisperGUI/` with executable `dist/WhisperGUI/WhisperGUI`.
- **On macOS**: Produces a native double-clickable application bundle at `dist/WhisperGUI.app` that can be dragged into `/Applications`.
- **On Windows**: Produces `dist/WhisperGUI/WhisperGUI.exe`.

---

## Setting Up Your GitHub Repository

To share the code or build automated releases across computers:

### 1. Initialize and Commit Local Changes
```bash
cd whisper-gui

# Verify git status
git status

# Stage all files
git add .

# Create initial release commit
git commit -m "feat: complete whisper transcriber with llm polishing and cross-platform support"
```

### 2. Create a Remote Repository on GitHub
1. Go to [github.com/new](https://github.com/new).
2. Set the repository name (e.g. `whisper-gui`).
3. Leave "Initialize with README", ".gitignore", and "license" unchecked (they already exist locally).
4. Click **Create repository**.

### 3. Push to GitHub
```bash
# Set your main branch
git branch -M main

# Add your remote repository (replace with your GitHub username)
git remote add origin https://github.com/<your-username>/whisper-gui.git

# Push your code
git push -u origin main
```

---

## Automated GitHub Actions (Cloud Builds for macOS & Linux)

The repository includes a GitHub Actions workflow in `.github/workflows/build-releases.yml`.

- Every push and pull request runs automated test suites on both **Ubuntu** and **macOS**.
- To build downloadable standalone releases for all platforms automatically:
  ```bash
  git tag v1.0.0
  git push origin v1.0.0
  ```
  GitHub Actions will automatically compile:
  - `WhisperGUI-linux-x86_64.tar.gz`
  - `WhisperGUI-macos.zip` (containing `WhisperGUI.app`)
  and attach them directly to your GitHub Releases page for direct download!
