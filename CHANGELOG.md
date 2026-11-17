# Changelog

## v0.2.6

### What's New
- **Right-Click Track Actions (`Rename` & `Remove`):** Replaced the sidebar `Remove` button with a themed right-click context menu on queue rows (`Rename`, `Remove`) synced across the drawer, active track card, and track selector, and removed `+` prefixes from `Add Files` and `Add Folder`.

### Refinements & Fixes
- **Two-Line Tracks Drawer Hierarchy:** Replaced the nested bordered 3-column queue table with a borderless `_TrackRowDelegate` layout showing full-width track names above mono duration metadata and status dots, eliminating horizontal truncation, column headers, and zebra stripes.
- **Uniform Main Page Card Spacing:** Removed the vertical `QSplitter` separator line and widened `main_splitter` to a `12px` transparent gutter matching the rest of the workspace.

## v0.2.5

### What's New
- **Waveform Trim Scrubber & Synced Playback:** Added PyAV waveform peak visualization (`WaveformScrubberWidget`) with draggable `[` `]` bounds and playhead inside `TrimAudioDialog`, plus a borderless `TranscriptView` playback bar (`0.75x`–`2.0x`) with click-to-seek timestamps and live segment highlighting.
- **LLM Polishing Presets & Inline Recovery:** Added 5 built-in prompts (`Default`, `Meeting Notes`, `Action Items`, `Executive Summary`, `Q&A`) via a quick preset menu on the polish button and `LLMPanel`, live elapsed polish timer, `Stop` support for `PolishWorker`, and a non-blocking inline error bar (`Retry` / `LLM settings`).
- **Transcript History, Batch Export & Download Progress:** Added persistent local `History` (`HistoryPageWidget`) to reopen past transcripts in two clicks, drawer `Export All` for multi-track queues, and live byte/MB progress with cancellation when downloading HuggingFace Whisper models.
- **Live Transcription ETA & Speed Telemetry:** Displays active playback ratio (`x`) and remaining ETA while transcribing.

### Refinements & Fixes
- **Single-Frame Dropdown Popups & Consistent Heights:** Fixed macOS `QComboBox` popups rendering an outer dark `QComboBoxPrivateContainer` window border and inconsistent option-dependent height via `style_combobox()`, `_ComboContainerPopupFilter`, and unified `style_menu()` styling across settings, LLM, track, and transcript menus.
- **Cross-Platform `TrimAudioDialog` & Media Lifecycle Stability:** Stacked `RangeSelectorWidget` mode radios, time controls, and length readout with `_sync_dialog_size()` to prevent clipping under Windows/Linux fonts, guarded `QMediaPlayer` against empty audio files, and excluded `PySide6==6.12.0` on Python `< 3.12` to prevent CPython `bool_dealloc` teardown crashes.
- **Inline Edit Persistence & UI Cleanup:** Preserved manual raw transcript edits across `Raw`/`Polished` tabs, track switches, History reopening, and multi-format exports (`raw_segments_stale`); standardized `32px` button heights, `8px` radii, and `4px`/`12px`/`24px` spacing across panels.

## v0.2.4

### What's New
- **Italian Localization (`en` / `it`) & Live Language Switching:** Added complete Italian translations across the workspace, dialogs, track statuses, background workers, LLM connection feedback, and exported documents (`.docx`, `.pdf`, `.md`, `.txt`), with an **App Language** selector in **Settings → Appearance** that switches the UI immediately and persists via `QSettings`.
- **Bilingual Parity Guardrails:** Added automated key/placeholder parity and AST `tr()` coverage tests (`tests/test_i18n.py`) plus `.agents/rules/i18n.md` to keep English and Italian synchronized in future changes.

## v0.2.3

### What's New
- **Apple-Style Interactive Toggle Switches:** Replaced settings and toolbar checkboxes with smooth `ToggleSwitch` pill switches supporting both click-to-toggle and continuous mouse-drag switching with mid-drag cancellation snap-back.
- **Simplified App Logo & Icon Bundle:** Removed the waves from `minimal_whisper.svg`, scaled the cream pen nib up by `1.18x` optically centered inside the `#1A1C96` tile, and regenerated crisp `icon.png`, `icon.icns`, and `icon.ico` assets.

## v0.2.2

### What's New
- **Switchable Color Themes & Drop Transition:** Choose between **Graphite** (dark) and **Blush Pink** (`#F8C8DC` / `#F3CFC6` soft pastel) in **Settings → Appearance**, with an instant radial drop reveal animation and persisted theme preference.
- **Refined Graphite UI & Icons:** Unified matte Graphite palette (`#141415`–`#232325`), tabular monospace timecodes and metrics, crisp 2x HiDPI SVG line icons (`load_ui_icon`), clean `QComboBox` chevrons, and circular radio indicators.
- **Improved Layout & Rendering:** Two-row Trim Audio range controls, readable `Track` column sizing in the tracks drawer, and a `4px` borderless progress bar.

### Bug Fixes
- **HiDPI Retina SVG Icon Rendering:** Fixed `devicePixelRatio` scaling in `load_tinted_pixmap()` and `swatch_icon()` so toolbar, settings, dropzone, and preview buttons render full-frame without quarter-cropping on macOS Retina displays.
- **Continuous Dropzone Border:** Replaced Qt stylesheet dashed border with continuous `QPainterPath` rendering and neutral Graphite hover state.
- **Settings Button Clipping:** Fixed `QPushButton` CSS `min-height` overflow so **Check for Updates** and compact action buttons render cleanly without bottom clipping.

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
