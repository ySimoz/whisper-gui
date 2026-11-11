"""Theme definitions and application stylesheets.

Minimal Swiss & AI-native palette:
- High contrast, WCAG AA compliant.
- No decorative gradients or glows.
- Clean slate surfaces with solid accent states.
"""

from __future__ import annotations

from whisper_gui.platform_utils import get_asset_path

# Color Palette Constants
COLOR_PRIMARY = "#2563EB"
COLOR_PRIMARY_HOVER = "#3B82F6"
COLOR_PRIMARY_PRESSED = "#1D4ED8"
COLOR_PRIMARY_TEXT = "#FFFFFF"

COLOR_SECONDARY = "#E11D48"
COLOR_SECONDARY_HOVER = "#F43F5E"
COLOR_SECONDARY_PRESSED = "#BE123C"
COLOR_SECONDARY_TEXT = "#FFFFFF"

# Refined Slate Surfaces
COLOR_BG_WINDOW = "#0F172A"
COLOR_BG_SURFACE = "#1E293B"
COLOR_BG_INPUT = "#0B0F19"
COLOR_BG_PANEL_ALT = "#1E293B"

# Crisp structural borders
COLOR_BORDER = "#334155"
COLOR_BORDER_LIGHT = "#475569"
COLOR_BORDER_PRIMARY = "#3B82F6"
COLOR_BORDER_SECONDARY = "#E11D48"

# Typography
COLOR_TEXT_MAIN = "#F8FAFC"
COLOR_TEXT_MUTED = "#94A3B8"
COLOR_TEXT_HINT = "#64748B"

_check_asset = get_asset_path("check.svg")
CHECK_ICON_URL = _check_asset.as_posix() if _check_asset else ""

GLOBAL_STYLESHEET = f"""
/* Global Window & Typography */
QMainWindow, QWidget {{
    background-color: {COLOR_BG_WINDOW};
    color: {COLOR_TEXT_MAIN};
    font-size: 13px;
}}

/* Containers & Surface Cards (use .QFrame to avoid applying borders to QLabel subclasses) */
.QFrame {{
    background-color: {COLOR_BG_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
}}

/* Text Labels: Zero borders, zero backgrounds, pure typography (eliminates false button boxes) */
QLabel {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 1px 0px;
    color: {COLOR_TEXT_MAIN};
}}

QGroupBox {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: 600;
}}

/* Form Controls & Inputs (Sunken, distinct input well) */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_PRIMARY_TEXT};
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{
    border: 1px solid {COLOR_BORDER_LIGHT};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1.5px solid {COLOR_PRIMARY};
    background-color: #060911;
}}

QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_HINT};
    border: 1px solid {COLOR_BORDER};
}}

/* Dropdowns / ComboBox */
QComboBox {{
    padding: 8px 12px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border-left: 1px solid {COLOR_BORDER};
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #172030;
}}

QComboBox::drop-down:hover {{
    background-color: #222F43;
}}

QComboBox QAbstractItemView,
QComboBox QListView {{
    background-color: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    padding: 4px;
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_PRIMARY_TEXT};
    outline: none;
}}

QComboBox QAbstractItemView::item,
QComboBox QListView::item {{
    min-height: 28px;
    padding: 4px 8px;
    border-radius: 3px;
}}

QComboBox QAbstractItemView::item:hover,
QComboBox QListView::item:hover {{
    background-color: #334155;
    color: #FFFFFF;
}}

QComboBox QAbstractItemView::item:selected,
QComboBox QListView::item:selected {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_PRIMARY_TEXT};
}}

QComboBox QLineEdit {{
    background-color: transparent;
    border: none;
    padding: 0px;
    color: {COLOR_TEXT_MAIN};
}}

/* Interactive PushButtons (Clearly raised, elevated slate background distinct from flat cards and labels) */
QPushButton {{
    background-color: #334155;
    color: #F8FAFC;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
    font-size: 12px;
    min-height: 22px;
}}

QPushButton:hover {{
    background-color: #475569;
    border: 1px solid #64748B;
    color: #FFFFFF;
}}

QPushButton:pressed {{
    background-color: #1E293B;
    border: 1px solid #334155;
}}

QPushButton:disabled {{
    background-color: #151D2A;
    color: {COLOR_TEXT_HINT};
    border: 1px solid #243042;
}}

/* Tabs Widget */
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    background-color: {COLOR_BG_SURFACE};
    top: -1px;
}}

QTabBar::tab {{
    background: {COLOR_BG_WINDOW};
    color: {COLOR_TEXT_MUTED};
    padding: 8px 16px;
    font-weight: 600;
    font-size: 12px;
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 4px;
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
    background: #172030;
}}

/* Table Widget */
QTableWidget {{
    background-color: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    gridline-color: {COLOR_BORDER};
    color: {COLOR_TEXT_MAIN};
    selection-background-color: #1E3A5F;
    selection-color: {COLOR_TEXT_MAIN};
}}

QHeaderView::section {{
    background-color: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_MUTED};
    padding: 6px 10px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    border-right: 1px solid {COLOR_BORDER};
    font-weight: 600;
    font-size: 11px;
}}

/* CheckBoxes & Radio Buttons */
QCheckBox, QRadioButton {{
    background-color: transparent;
    color: {COLOR_TEXT_MAIN};
    spacing: 10px;
    min-height: 24px;
    padding: 2px 0px;
    font-size: 13px;
}}

QCheckBox:hover, QRadioButton:hover {{
    color: #FFFFFF;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1.5px solid {COLOR_BORDER_LIGHT};
    border-radius: 4px;
    background-color: {COLOR_BG_INPUT};
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border: 1.5px solid {COLOR_PRIMARY_HOVER};
    background-color: #172030;
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border: 1.5px solid {COLOR_PRIMARY};
    image: url({CHECK_ICON_URL});
}}

QCheckBox::indicator:checked:hover, QRadioButton::indicator:checked:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
    border: 1.5px solid {COLOR_PRIMARY_HOVER};
}}

QCheckBox:disabled, QRadioButton:disabled {{
    color: {COLOR_TEXT_HINT};
}}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {COLOR_BORDER};
    background-color: #151D2A;
}}

/* Progress Bar (Solid, no gradient) */
QProgressBar {{
    background-color: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    text-align: center;
    color: {COLOR_TEXT_MAIN};
    font-weight: 600;
    font-size: 11px;
    height: 16px;
}}

QProgressBar::chunk {{
    background-color: {COLOR_PRIMARY};
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
    border: 1px solid {COLOR_BORDER_LIGHT};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: {COLOR_PRIMARY_HOVER};
}}

/* Splitters */
QSplitter::handle {{
    background-color: {COLOR_BORDER};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {COLOR_BG_WINDOW};
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {COLOR_BORDER};
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {COLOR_BORDER_LIGHT};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: {COLOR_BG_WINDOW};
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {COLOR_BORDER};
    min-width: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {COLOR_BORDER_LIGHT};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""
