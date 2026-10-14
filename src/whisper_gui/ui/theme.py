"""Theme definitions and application stylesheets.

Primary color: #21EBD5 (Electric Mint/Cyan)
Secondary color: #FF5C9E (Neon Pink/Magenta)
Aesthetic: Crisp borders, high contrast, clean modern dark surfaces without blurry glow.
"""

from __future__ import annotations

# Color Palette Constants
COLOR_PRIMARY = "#21EBD5"
COLOR_PRIMARY_HOVER = "#4BF0DF"
COLOR_PRIMARY_PRESSED = "#18C6B4"
COLOR_PRIMARY_TEXT = "#0A141A"

COLOR_SECONDARY = "#FF5C9E"
COLOR_SECONDARY_HOVER = "#FF7EB3"
COLOR_SECONDARY_PRESSED = "#E04787"
COLOR_SECONDARY_TEXT = "#180610"

# Refined Slate/Indigo Backgrounds (Lighter, warmer, avoids heavy pitch-black)
COLOR_BG_WINDOW = "#171B26"
COLOR_BG_SURFACE = "#202637"
COLOR_BG_INPUT = "#181D2A"
COLOR_BG_PANEL_ALT = "#1B202F"

# Crisp structural borders
COLOR_BORDER = "#333E56"
COLOR_BORDER_LIGHT = "#445373"
COLOR_BORDER_PRIMARY = "#21EBD5"
COLOR_BORDER_SECONDARY = "#FF5C9E"

# Typography
COLOR_TEXT_MAIN = "#F3F6FD"
COLOR_TEXT_MUTED = "#A2ADC2"
COLOR_TEXT_HINT = "#717E96"

GLOBAL_STYLESHEET = f"""
/* Global Window & Typography */
QMainWindow, QWidget {{
    background-color: {COLOR_BG_WINDOW};
    color: {COLOR_TEXT_MAIN};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 12px;
}}

/* Crisp Frames & Panels */
QFrame, QGroupBox {{
    background-color: {COLOR_BG_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
}}

QGroupBox {{
    margin-top: 18px;
    padding-top: 10px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
    color: {COLOR_PRIMARY};
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* Form Controls & Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_PRIMARY_TEXT};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {COLOR_PRIMARY};
    background-color: #22293B;
}}

QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background-color: #191E2B;
    color: {COLOR_TEXT_HINT};
    border: 1px solid #283145;
}}

/* Dropdowns / ComboBox */
QComboBox {{
    padding: 4px 10px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid {COLOR_BORDER};
}}

QComboBox QAbstractItemView {{
    background-color: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_PRIMARY_TEXT};
    outline: none;
}}

/* Standard PushButtons */
QPushButton {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 5px 12px;
    font-weight: 500;
}}

QPushButton:hover {{
    border: 1px solid {COLOR_PRIMARY};
    color: {COLOR_PRIMARY};
    background-color: #262F42;
}}

QPushButton:pressed {{
    background-color: #1D2332;
}}

QPushButton:disabled {{
    background-color: #191E2B;
    color: {COLOR_TEXT_HINT};
    border: 1px solid #283145;
}}

/* Tabs Widget */
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    background-color: {COLOR_BG_SURFACE};
    top: -1px;
}}

QTabBar::tab {{
    background: #1B202E;
    color: {COLOR_TEXT_MUTED};
    padding: 7px 16px;
    font-weight: 600;
    font-size: 11px;
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 3px;
}}

QTabBar::tab:selected {{
    background: {COLOR_BG_SURFACE};
    color: {COLOR_PRIMARY};
    border: 1px solid {COLOR_BORDER};
    border-top: 2px solid {COLOR_PRIMARY};
    border-bottom: 1px solid {COLOR_BG_SURFACE};
}}

QTabBar::tab:hover:!selected {{
    color: {COLOR_TEXT_MAIN};
    background: #242C3E;
}}

/* Table Widget */
QTableWidget {{
    background-color: {COLOR_BG_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    gridline-color: #293347;
    color: {COLOR_TEXT_MAIN};
    selection-background-color: #25394E;
    selection-color: {COLOR_TEXT_MAIN};
}}

QHeaderView::section {{
    background-color: #1B202F;
    color: {COLOR_PRIMARY};
    padding: 6px 8px;
    border: none;
    border-bottom: 2px solid {COLOR_PRIMARY};
    border-right: 1px solid {COLOR_BORDER};
    font-weight: bold;
    font-size: 11px;
}}

/* CheckBoxes & Radio Buttons */
QCheckBox, QRadioButton {{
    color: {COLOR_TEXT_MAIN};
    spacing: 6px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    background-color: {COLOR_BG_INPUT};
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border: 1px solid {COLOR_PRIMARY};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border: 1px solid {COLOR_PRIMARY};
}}

/* Progress Bar with Cyan-to-Pink gradient */
QProgressBar {{
    background-color: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    text-align: center;
    color: {COLOR_TEXT_MAIN};
    font-weight: bold;
    font-size: 10px;
    height: 14px;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLOR_PRIMARY}, stop:0.7 {COLOR_PRIMARY}, stop:1 {COLOR_SECONDARY});
    border-radius: 3px;
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 6px;
    background: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{
    background: {COLOR_PRIMARY};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {COLOR_PRIMARY};
    border: 1px solid #14B8A6;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}}

QSlider::handle:horizontal:hover {{
    background: {COLOR_PRIMARY_HOVER};
    border: 1px solid {COLOR_SECONDARY};
}}

/* Splitters */
QSplitter::handle {{
    background-color: {COLOR_BG_WINDOW};
}}

QSplitter::handle:horizontal {{
    width: 5px;
}}

QSplitter::handle:vertical {{
    height: 5px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {COLOR_BG_WINDOW};
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: #2E374A;
    min-height: 20px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: {COLOR_PRIMARY};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: {COLOR_BG_WINDOW};
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: #2E374A;
    min-width: 20px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {COLOR_PRIMARY};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""
