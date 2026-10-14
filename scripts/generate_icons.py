#!/usr/bin/env python3
"""Generate PNG, ICO, and ICNS icon assets from minimal_whisper.svg for desktop application bundling."""

import struct
import sys
from pathlib import Path


def generate_icons() -> None:
    project_root = Path(__file__).resolve().parent.parent

    # Locate source SVG
    svg_candidates = [
        project_root / "src" / "assets" / "minimal_whisper.svg",
        project_root / "assets" / "minimal_whisper.svg",
    ]
    svg_path = next((p for p in svg_candidates if p.is_file()), None)
    if not svg_path:
        print(f"Error: Could not locate minimal_whisper.svg in {svg_candidates}")
        sys.exit(1)

    print(f"Loading source SVG icon: {svg_path}")

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QIcon, QPixmap
    from PySide6.QtWidgets import QApplication

    # Qt app instance required for QPixmap operations
    app = QApplication.instance()
    if not app:
        app = QApplication(["--platform", "offscreen"])

    icon = QIcon(str(svg_path))
    if icon.isNull():
        print(f"Error: Failed to load icon from {svg_path}")
        sys.exit(1)

    def get_png_bytes(size: int) -> bytes:
        pix = icon.pixmap(size, size)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        pix.save(buf, "PNG")
        return bytes(ba)

    # 1. High-resolution PNG (1024x1024)
    png_1024 = get_png_bytes(1024)

    # 2. Apple ICNS file
    icns_types = [
        (16, b"icp4"),
        (32, b"icp5"),
        (64, b"ic12"),
        (128, b"ic07"),
        (256, b"ic08"),
        (512, b"ic09"),
        (1024, b"ic10"),
    ]
    chunks = []
    for sz, tag in icns_types:
        data = get_png_bytes(sz)
        chunk = tag + struct.pack(">I", len(data) + 8) + data
        chunks.append(chunk)

    body = b"".join(chunks)
    total_len = len(body) + 8
    icns_bytes = b"icns" + struct.pack(">I", total_len) + body

    # 3. Windows ICO file
    ico_sizes = [16, 32, 48, 64, 128, 256]
    entries = []
    images = []
    offset = 6 + 16 * len(ico_sizes)
    for sz in ico_sizes:
        data = get_png_bytes(sz)
        w = 0 if sz == 256 else sz
        h = 0 if sz == 256 else sz
        entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
        entries.append(entry)
        images.append(data)
        offset += len(data)

    ico_header = struct.pack("<HHH", 0, 1, len(ico_sizes))
    ico_bytes = ico_header + b"".join(entries) + b"".join(images)

    # Output to both assets/ and src/assets/ directories
    target_dirs = [
        project_root / "assets",
        project_root / "src" / "assets",
    ]

    for d in target_dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / "icon.png").write_bytes(png_1024)
        (d / "icon.icns").write_bytes(icns_bytes)
        (d / "icon.ico").write_bytes(ico_bytes)
        # Ensure minimal_whisper.svg is also synced
        if svg_path != d / "minimal_whisper.svg":
            import shutil
            shutil.copy2(svg_path, d / "minimal_whisper.svg")

        print(f"Generated icon assets in: {d}")


if __name__ == "__main__":
    generate_icons()
