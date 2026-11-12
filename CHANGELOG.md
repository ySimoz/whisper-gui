# Changelog

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
