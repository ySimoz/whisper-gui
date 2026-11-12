# Changelog

## v0.2.1

### What's New
- **Per-Track Transcript Switching:** Selecting any track in a multi-track batch reloads its own raw/polished transcript and export paths, while live transcription streams cleanly to the active track.
- **Re-Polish Without Re-Transcribing:** Added a **Polish / Re-polish** button on completed transcripts to run or retry LLM polishing without re-running Whisper.
- **Inline Editing, Search & Subtitles Export:** Edit transcripts directly in the viewer before exporting, search with `Ctrl/Cmd+F`, and export to **SubRip (`.srt`)** and **WebVTT (`.vtt`)**.
- **Trim Dialog Audio Preview:** Play/pause and preview your selected `[Start → End]` range directly inside the Trim Audio dialog.

### Security & Settings
- **OS-Native API Key Storage:** Stores LLM API keys in macOS Keychain, Windows DPAPI, or Linux `secret-tool` (with automatic migration from legacy plain-text `QSettings`), documented in `README.md`.
- **Model Cache Cleanup & Manual Update Check:** View cached model size, delete unused Whisper models from disk, and trigger **Check for Updates** from Settings.

## v0.2.0

### What's New
- **In-App Auto-Updater:** Checks GitHub Releases on launch when online and prompts with a **New Version Available** dialog, full release changelog, **Update Now**, and **Cancel** buttons.
- **One-Click Self-Update:** Bundled desktop builds download the update package with live progress, extract it safely, swap the app, and relaunch automatically (or reveal the update if the folder needs admin rights).
- **Anthropic Claude AI Polishing:** Added Anthropic Claude provider support and official Claude models to the AI Transcript Polisher.

### Build & Packaging
- Added free macOS ad-hoc code signing (`codesign`) and symlink-safe archiving (`ditto`) in CI release builds.
- Synced bundled app metadata and `CFBundleVersion` dynamically with the release tag.

## v0.1.0

### Highlights
- **Local-First Audio Transcription:** Offline transcription via `faster-whisper` (`large-v3-turbo` by default).
- **Multi-Format Export:** Export transcripts to `.docx`, `.pdf`, `.md`, and `.txt`.
- **Lateral Tracks Drawer & FFmpeg Trimming:** Queue multiple tracks and extract exact audio ranges without modifying source files.
- **Optional AI Polishing:** Disfluency removal and grammar cleanup via DeepSeek, OpenAI, or custom endpoints.
