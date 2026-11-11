"""Multi-format exporters for Whisper transcriptions (Word, PDF, Markdown, Plain Text)."""

from __future__ import annotations

import datetime
import html
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QApplication

from whisper_gui.audio_utils import format_seconds
from whisper_gui.docx_exporter import export_transcript_to_docx
from whisper_gui.models import (
    AudioInfo,
    SliceConfig,
    TranscriptionConfig,
    TranscriptionResult,
)


def _get_slice_desc(slice_config: SliceConfig | None, duration: float) -> str:
    if not slice_config or slice_config.is_full(duration):
        return "Entire Audio"
    start_sec = max(0.0, slice_config.start_sec)
    end_sec = slice_config.effective_end(duration)
    slice_dur = slice_config.effective_duration(duration)
    return f"{format_seconds(start_sec)} - {format_seconds(end_sec)} ({format_seconds(slice_dur)})"


def export_transcript_to_txt(
    output_path: str | Path,
    track_info: AudioInfo | None = None,
    slice_config: SliceConfig | None = None,
    transcription_config: TranscriptionConfig | None = None,
    result: TranscriptionResult | None = None,
) -> Path:
    """Export the transcription to a clean, formatted plain text (.txt) file."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("AUDIO TRANSCRIPTION")
    lines.append("=" * 60)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"Export Date:     {now_str}")

    if track_info:
        lines.append(f"Source File:     {track_info.filename}")
        lines.append(f"Original Length: {track_info.duration_formatted}")

    if slice_config and track_info:
        lines.append(f"Transcribed:     {_get_slice_desc(slice_config, track_info.duration)}")

    if transcription_config and result:
        lang = result.detected_language or transcription_config.language or "auto"
        lines.append(f"Whisper Model:   {transcription_config.model_name} (Language: {lang})")

    lines.append("-" * 60)
    lines.append("")

    # 1. Polished Text
    if result and result.polished_text:
        model_name = result.llm_model_used or "AI Polisher"
        lines.append(f"--- POLISHED TRANSCRIPT ({model_name}) ---")
        lines.append(result.polished_text.strip())
        lines.append("")

    # 2. Raw Transcript
    include_raw = True
    include_timestamps = True
    if transcription_config:
        include_timestamps = transcription_config.include_timestamps_in_docx
        if transcription_config.llm_config and result and result.polished_text:
            include_raw = transcription_config.llm_config.include_raw_in_docx

    if result and include_raw:
        if result.polished_text:
            lines.append("--- DETAILED TRANSCRIPT ---")

        if result.segments:
            for seg in result.segments:
                if include_timestamps:
                    lines.append(f"{seg.formatted_timerange} {seg.text}")
                else:
                    lines.append(seg.text)
        elif result.full_text:
            lines.append(result.full_text.strip())

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_file


def export_transcript_to_md(
    output_path: str | Path,
    track_info: AudioInfo | None = None,
    slice_config: SliceConfig | None = None,
    transcription_config: TranscriptionConfig | None = None,
    result: TranscriptionResult | None = None,
) -> Path:
    """Export the transcription to a structured Markdown (.md) document."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Audio Transcription")
    lines.append("")

    # Metadata table
    lines.append("| Property | Details |")
    lines.append("| :--- | :--- |")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"| **Export Date** | `{now_str}` |")

    if track_info:
        lines.append(f"| **Source File** | `{track_info.filename}` |")
        lines.append(f"| **Duration** | `{track_info.duration_formatted}` |")

    if slice_config and track_info:
        lines.append(f"| **Slice Range** | `{_get_slice_desc(slice_config, track_info.duration)}` |")

    if transcription_config and result:
        lang = result.detected_language or transcription_config.language or "auto"
        lines.append(f"| **Model** | `{transcription_config.model_name}` ({lang}) |")

    lines.append("")

    # 1. Polished Text
    if result and result.polished_text:
        model_name = result.llm_model_used or "AI Polisher"
        lines.append(f"## Polished Transcript ({model_name})")
        lines.append("")
        lines.append(result.polished_text.strip())
        lines.append("")

    # 2. Detailed Segments
    include_raw = True
    include_timestamps = True
    if transcription_config:
        include_timestamps = transcription_config.include_timestamps_in_docx
        if transcription_config.llm_config and result and result.polished_text:
            include_raw = transcription_config.llm_config.include_raw_in_docx

    if result and include_raw:
        lines.append("## Detailed Transcript")
        lines.append("")

        if result.segments:
            for seg in result.segments:
                if include_timestamps:
                    lines.append(f"- **`{seg.formatted_timerange}`** {seg.text}")
                else:
                    lines.append(f"- {seg.text}")
        elif result.full_text:
            lines.append(result.full_text.strip())
        lines.append("")

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_file


def export_transcript_to_pdf(
    output_path: str | Path,
    track_info: AudioInfo | None = None,
    slice_config: SliceConfig | None = None,
    transcription_config: TranscriptionConfig | None = None,
    result: TranscriptionResult | None = None,
) -> Path:
    """Export the transcription to a publication-quality PDF using QPdfWriter and QTextDocument."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Ensure QApplication instance exists for QTextDocument / QPdfWriter
    _ = QApplication.instance() or QApplication([])

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_filename = html.escape(track_info.filename) if track_info else "Audio Source"
    duration_str = track_info.duration_formatted if track_info else "--:--"

    slice_str = "Entire Audio"
    if slice_config and track_info:
        slice_str = _get_slice_desc(slice_config, track_info.duration)
    slice_str = html.escape(slice_str)

    model_str = "faster-whisper"
    if transcription_config and result:
        lang = result.detected_language or transcription_config.language or "auto"
        model_str = f"{transcription_config.model_name} ({lang})"
    model_str = html.escape(model_str)

    html_parts: list[str] = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset='utf-8'>",
        "<style>",
        "  body { font-family: Helvetica, Arial, sans-serif; color: #1E293B; font-size: 10pt; line-height: 1.5; margin: 0; padding: 0; }",
        "  h1 { font-size: 20pt; color: #0F172A; margin: 0 0 4px 0; font-weight: bold; }",
        "  .subtitle { font-size: 9.5pt; color: #64748B; margin-bottom: 16px; }",
        "  table.meta-table { width: 100%; border-collapse: collapse; background-color: #F8FAFC; border: 1px solid #CBD5E1; margin-bottom: 20px; }",
        "  table.meta-table td { padding: 6px 10px; border: 1px solid #E2E8F0; font-size: 9pt; }",
        "  .meta-label { font-weight: bold; color: #475569; width: 22%; }",
        "  .meta-val { color: #0F172A; }",
        "  h2 { font-size: 13pt; color: #2563EB; border-bottom: 1px solid #E2E8F0; padding-bottom: 4px; margin-top: 18px; margin-bottom: 8px; }",
        "  .polished-box { background-color: #F8FAFC; border-left: 3px solid #2563EB; padding: 10px 14px; margin-bottom: 16px; font-size: 10pt; line-height: 1.6; }",
        "  table.seg-table { width: 100%; border-collapse: collapse; margin-top: 6px; }",
        "  table.seg-table td { padding: 4px 0; vertical-align: top; }",
        "  .seg-time { color: #2563EB; font-weight: bold; font-family: 'Courier New', Courier, monospace; font-size: 8.5pt; width: 130px; white-space: nowrap; }",
        "  .seg-text { color: #1E293B; font-size: 9.5pt; padding-left: 8px; }",
        "</style>",
        "</head>",
        "<body>",
        "  <h1>Audio Transcription</h1>",
        f"  <div class='subtitle'>Source: <b>{source_filename}</b> &bull; Generated: {now_str}</div>",
        "  <table class='meta-table' cellpadding='6' cellspacing='0'>",
        "    <tr>",
        f"      <td class='meta-label'>Source File</td><td class='meta-val'>{source_filename}</td>",
        f"      <td class='meta-label'>Length</td><td class='meta-val'>{duration_str}</td>",
        "    </tr>",
        "    <tr>",
        f"      <td class='meta-label'>Model</td><td class='meta-val'>{model_str}</td>",
        f"      <td class='meta-label'>Slice Range</td><td class='meta-val'>{slice_str}</td>",
        "    </tr>",
        "  </table>",
    ]

    # Polished speech section
    if result and result.polished_text:
        model_name = html.escape(result.llm_model_used or "AI Polisher")
        html_parts.append(f"  <h2>Polished Speech ({model_name})</h2>")
        polished_html = html.escape(result.polished_text.strip()).replace("\n\n", "</p><p>").replace("\n", "<br>")
        html_parts.append(f"  <div class='polished-box'><p>{polished_html}</p></div>")

    # Detailed transcript section
    include_raw = True
    include_timestamps = True
    if transcription_config:
        include_timestamps = transcription_config.include_timestamps_in_docx
        if transcription_config.llm_config and result and result.polished_text:
            include_raw = transcription_config.llm_config.include_raw_in_docx

    if result and include_raw:
        html_parts.append("  <h2>Detailed Transcript</h2>")
        if result.segments:
            html_parts.append("  <table class='seg-table' cellpadding='3' cellspacing='0'>")
            for seg in result.segments:
                seg_text = html.escape(seg.text)
                if include_timestamps:
                    time_badge = html.escape(seg.formatted_timerange)
                    html_parts.append(
                        f"    <tr><td class='seg-time'>{time_badge}</td><td class='seg-text'>{seg_text}</td></tr>"
                    )
                else:
                    html_parts.append(f"    <tr><td colspan='2' class='seg-text'>{seg_text}</td></tr>")
            html_parts.append("  </table>")
        elif result.full_text:
            escaped_full = html.escape(result.full_text.strip()).replace("\n", "<br>")
            html_parts.append(f"  <p>{escaped_full}</p>")

    html_parts.append("</body>")
    html_parts.append("</html>")

    doc = QTextDocument()
    doc.setHtml("\n".join(html_parts))

    writer = QPdfWriter(str(out_file))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18))
    doc.print_(writer)

    return out_file


def export_transcript(
    format_name: str,
    output_path: str | Path,
    track_info: AudioInfo | None = None,
    slice_config: SliceConfig | None = None,
    transcription_config: TranscriptionConfig | None = None,
    result: TranscriptionResult | None = None,
) -> Path:
    """Unified entrypoint for exporting a transcription to any supported format.

    Args:
        format_name: 'docx', 'pdf', 'md', or 'txt'.
        output_path: Target path for the exported file.
        track_info: Audio track information.
        slice_config: Slicing configuration applied.
        transcription_config: Whisper transcription settings.
        result: Transcription result.

    Returns:
        Resolved Path to the saved document.
    """
    fmt = format_name.lower().lstrip(".")
    if fmt == "docx":
        # Ensure track_info and config have defaults if None
        ti = track_info or AudioInfo(path=Path(output_path), filename=Path(output_path).name, duration=0.0)
        sc = slice_config or SliceConfig()
        tc = transcription_config or TranscriptionConfig()
        tr = result or TranscriptionResult()
        return export_transcript_to_docx(output_path, ti, sc, tc, tr)
    elif fmt == "pdf":
        return export_transcript_to_pdf(output_path, track_info, slice_config, transcription_config, result)
    elif fmt == "md":
        return export_transcript_to_md(output_path, track_info, slice_config, transcription_config, result)
    elif fmt == "txt":
        return export_transcript_to_txt(output_path, track_info, slice_config, transcription_config, result)
    else:
        raise ValueError(f"Unsupported export format '{format_name}'. Expected docx, pdf, md, or txt.")
