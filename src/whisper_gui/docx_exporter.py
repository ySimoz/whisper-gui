"""Word (.docx) export for Whisper transcriptions."""

from __future__ import annotations

import datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Pt, RGBColor

from whisper_gui.audio_utils import format_seconds
from whisper_gui.models import AudioInfo, SliceConfig, TranscriptionConfig, TranscriptionResult


def _set_cell_background(cell, hex_color: str) -> None:
    """Sets background shading of a docx table cell."""
    shading_xml = f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>'
    cell._tc.get_or_add_tcPr().append(parse_xml(shading_xml))


def _set_cell_margins(cell, top=100, bottom=100, left=150, right=150) -> None:
    """Sets internal padding for a table cell in twentieths of a point (dxa)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for margin_name, val in [("top", top), ("bottom", bottom), ("left", left), ("right", right)]:
        node = OxmlElement(f"w:{margin_name}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def export_transcript_to_docx(
    output_path: str | Path,
    track_info: AudioInfo,
    slice_config: SliceConfig,
    transcription_config: TranscriptionConfig,
    result: TranscriptionResult,
) -> Path:
    """Export the transcription result into a polished Microsoft Word (.docx) document.

    Args:
        output_path: Target path for the .docx file.
        track_info: Original audio metadata.
        slice_config: Applied slicing configuration.
        transcription_config: Transcription configuration (model, language, etc.).
        result: Transcription result containing segments, language, timings.

    Returns:
        Resolved Path to the saved document.
    """
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()

    # Standard 1-inch margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # Base typography styling
    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Calibri"
    normal_style.font.size = Pt(11)
    normal_style.font.color.rgb = RGBColor(33, 37, 41)
    normal_style.paragraph_format.line_spacing = 1.15
    normal_style.paragraph_format.space_after = Pt(6)

    # Document Header / Title
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_after = Pt(2)
    title_p.paragraph_format.space_before = Pt(0)
    title_run = title_p.add_run("Audio Transcription")
    title_run.font.size = Pt(22)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(26, 82, 118)  # Deep professional blue

    # Subtitle / Filename
    subtitle_p = doc.add_paragraph()
    subtitle_p.paragraph_format.space_after = Pt(16)
    sub_run = subtitle_p.add_run(f"Source file: {track_info.filename}")
    sub_run.font.size = Pt(12)
    sub_run.font.italic = True
    sub_run.font.color.rgb = RGBColor(108, 117, 125)

    # Metadata Summary Table
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_sec = max(0.0, slice_config.start_sec)
    end_sec = slice_config.effective_end(track_info.duration)
    slice_dur = slice_config.effective_duration(track_info.duration)

    range_desc = (
        "Entire Audio"
        if slice_config.is_full(track_info.duration)
        else f"{format_seconds(start_sec)} → {format_seconds(end_sec)} ({format_seconds(slice_dur)})"
    )

    lang_display = result.detected_language or (transcription_config.language or "Auto-detected")
    if result.language_probability > 0:
        lang_display += f" ({result.language_probability * 100:.1f}% confidence)"

    speed_text = (
        f"{result.elapsed_time:.1f}s ({result.speed_factor:.2f}x real-time)"
        if result.elapsed_time > 0
        else "N/A"
    )

    metadata_rows = [
        ("Source File", track_info.filename),
        ("Original Duration", track_info.duration_formatted),
        ("Transcribed Range", range_desc),
        ("Date & Time", now_str),
        ("Whisper Model", f"{transcription_config.model_name} (faster-whisper)"),
        ("Detected Language", lang_display),
        ("Processing Time", speed_text),
    ]

    table = doc.add_table(rows=len(metadata_rows), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    col_widths = (Inches(2.0), Inches(4.5))

    for row_idx, (label, val) in enumerate(metadata_rows):
        row = table.rows[row_idx]
        bg_color = "F8F9FA" if row_idx % 2 == 0 else "FFFFFF"

        cell_label = row.cells[0]
        cell_val = row.cells[1]

        cell_label.width = col_widths[0]
        cell_val.width = col_widths[1]

        _set_cell_background(cell_label, bg_color)
        _set_cell_background(cell_val, bg_color)
        _set_cell_margins(cell_label, top=80, bottom=80, left=120, right=120)
        _set_cell_margins(cell_val, top=80, bottom=80, left=120, right=120)

        p_lbl = cell_label.paragraphs[0]
        p_lbl.paragraph_format.space_after = Pt(0)
        lbl_run = p_lbl.add_run(label)
        lbl_run.font.bold = True
        lbl_run.font.size = Pt(9.5)
        lbl_run.font.color.rgb = RGBColor(73, 80, 87)

        p_val = cell_val.paragraphs[0]
        p_val.paragraph_format.space_after = Pt(0)
        val_run = p_val.add_run(val)
        val_run.font.size = Pt(9.5)
        val_run.font.color.rgb = RGBColor(33, 37, 41)

    # Add space after table
    post_table_p = doc.add_paragraph()
    post_table_p.paragraph_format.space_before = Pt(12)
    post_table_p.paragraph_format.space_after = Pt(8)

    # Section Heading: Transcript
    heading = doc.add_heading(level=1)
    heading.paragraph_format.space_before = Pt(12)
    heading.paragraph_format.space_after = Pt(10)
    h_run = heading.add_run("Transcript")
    h_run.font.size = Pt(16)
    h_run.font.color.rgb = RGBColor(26, 82, 118)

    # Transcription Body
    if not result.segments:
        # Fallback to full_text if no segments
        if result.full_text.strip():
            p = doc.add_paragraph(result.full_text.strip())
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_after = Pt(8)
        else:
            p = doc.add_paragraph("No speech detected in audio file.")
            p.italic = True
    else:
        if transcription_config.include_timestamps_in_docx:
            # Output segments with timestamps
            for seg in result.segments:
                seg_text = seg.text.strip()
                if not seg_text:
                    continue
                p = doc.add_paragraph()
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.space_after = Pt(5)

                # Format timestamp offset relative to original track
                actual_start = start_sec + seg.start
                actual_end = start_sec + seg.end
                ts_str = f"[{format_seconds(actual_start)} → {format_seconds(actual_end)}] "

                ts_run = p.add_run(ts_str)
                ts_run.font.bold = True
                ts_run.font.size = Pt(9.5)
                ts_run.font.color.rgb = RGBColor(41, 128, 185)  # Soft blue

                text_run = p.add_run(seg_text)
                text_run.font.size = Pt(11)
        else:
            # Flowing paragraphs grouped logically
            # Group every 3-5 segments or on punctuation
            current_paragraph_texts: list[str] = []
            for seg in result.segments:
                seg_text = seg.text.strip()
                if not seg_text:
                    continue
                current_paragraph_texts.append(seg_text)
                if len(current_paragraph_texts) >= 4 or seg_text.endswith((".", "!", "?")):
                    p = doc.add_paragraph(" ".join(current_paragraph_texts))
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.space_after = Pt(8)
                    current_paragraph_texts = []

            if current_paragraph_texts:
                p = doc.add_paragraph(" ".join(current_paragraph_texts))
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.space_after = Pt(8)

    try:
        doc.save(str(out_file))
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot save Word document '{out_file.name}': The file is currently open or locked in another program "
            f"(such as Microsoft Word or LibreOffice). Please close it and try again."
        ) from exc
    return out_file
