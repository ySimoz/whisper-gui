"""Theme definitions and application stylesheets.

Matte graphite audio-workstation palette:
- Neutral graphite surfaces with hairline borders and one restrained accent.
- Tabular monospace helpers for timecodes and metrics.
- Uniform 16px SVG line icons.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QIcon

from whisper_gui.platform_utils import get_asset_path

# Accent & Semantic Palette
COLOR_PRIMARY = "#2563EB"
COLOR_PRIMARY_HOVER = "#3B82F6"
COLOR_PRIMARY_PRESSED = "#1D4ED8"
COLOR_PRIMARY_TEXT = "#FFFFFF"

COLOR_SECONDARY = "#E5484D"
COLOR_SECONDARY_HOVER = "#F06368"
COLOR_SECONDARY_PRESSED = "#C93B40"
COLOR_SECONDARY_TEXT = "#FFFFFF"

COLOR_POSITIVE = "#4CC38A"
COLOR_WARNING = "#E5A93B"
COLOR_NEGATIVE = "#E5484D"

# Graphite Neutral Ramp
COLOR_BG_WINDOW = "#141415"
COLOR_BG_SURFACE = "#19191B"
COLOR_BG_RAISED = "#232325"
COLOR_BG_INPUT = "#0F0F10"
COLOR_BG_PANEL_ALT = "#161618"

# Hairline Structural Borders
COLOR_BORDER = "#2B2B2E"
COLOR_BORDER_LIGHT = "#3C3C40"
COLOR_BORDER_PRIMARY = "#3B82F6"
COLOR_BORDER_SECONDARY = "#E5484D"

# Typography
COLOR_TEXT_MAIN = "#EDEDED"
COLOR_TEXT_SECONDARY = "#A1A1A6"
COLOR_TEXT_MUTED = "#85858B"
COLOR_TEXT_HINT = "#68686E"

_check_asset = get_asset_path("check.svg")
CHECK_ICON_URL = _check_asset.as_posix() if _check_asset else ""

_chevron_asset = get_asset_path("icons/chevron-down.svg")
CHEVRON_ICON_URL = _chevron_asset.as_posix() if _chevron_asset else ""


def load_ui_icon(name: str) -> QIcon:
    """Load a 16px line icon from assets/icons/<name>.svg."""
    path = get_asset_path(f"icons/{name}.svg")
    if path:
        return QIcon(str(path))
    return QIcon()


def fixed_mono_font(point_size: int | None = None) -> QFont:
    """Return the platform fixed-width font for tabular timecodes and counts."""
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    if point_size is not None:
        font.setPointSize(point_size)
    return font


GLOBAL_STYLESHEET = f"""
/* Global Window & Typography */
QMainWindow, QWidget {{
    background-color: {COLOR_BG_WINDOW};
    color: {COLOR_TEXT_MAIN};
    font-size: 13px;
    font-weight: 400;
}}

/* Containers & Surface Cards */
.QFrame {{
    background-color: {COLOR_BG_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
}}

/* Text Labels */
QLabel {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    color: {COLOR_TEXT_MAIN};
}}

QGroupBox {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 500;
}}

/* Form Controls & Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_PRIMARY_TEXT};
}}

QSpinBox, QDoubleSpinBox, QTimeEdit {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_PRIMARY_TEXT};
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTimeEdit:hover, QComboBox:hover {{
    border: 1px solid {COLOR_BORDER_LIGHT};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QComboBox:focus {{
    border: 1px solid {COLOR_PRIMARY};
}}

QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTimeEdit:disabled {{
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
    width: 28px;
    border: none;
    border-left: 1px solid {COLOR_BORDER};
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background-color: transparent;
}}

QComboBox::drop-down:hover {{
    background-color: {COLOR_BG_RAISED};
}}

QComboBox::down-arrow {{
    image: url({CHEVRON_ICON_URL});
    width: 14px;
    height: 14px;
}}

QComboBox QAbstractItemView,
QComboBox QListView {{
    background-color: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {COLOR_BG_RAISED};
    selection-color: {COLOR_TEXT_MAIN};
    outline: none;
}}

QComboBox QAbstractItemView::item,
QComboBox QListView::item {{
    min-height: 28px;
    padding: 4px 8px;
    border-radius: 4px;
}}

QComboBox QAbstractItemView::item:hover,
QComboBox QListView::item:hover {{
    background-color: {COLOR_BG_RAISED};
    color: {COLOR_TEXT_MAIN};
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

/* PushButtons */
QPushButton {{
    background-color: {COLOR_BG_RAISED};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER_LIGHT};
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 500;
    font-size: 12px;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: #2C2C30;
    border: 1px solid #4A4A50;
}}

QPushButton:pressed {{
    background-color: {COLOR_BG_SURFACE};
    border: 1px solid {COLOR_BORDER};
}}

QPushButton:disabled {{
    background-color: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_HINT};
    border: 1px solid {COLOR_BORDER};
}}

/* Tabs Widget */
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    background-color: {COLOR_BG_SURFACE};
    top: -1px;
}}

QTabBar::tab {{
    background: {COLOR_BG_WINDOW};
    color: {COLOR_TEXT_MUTED};
    padding: 8px 16px;
    font-weight: 500;
    font-size: 12px;
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}}

QTabBar::tab:selected {{
    background: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_MAIN};
    border: 1px solid {COLOR_BORDER};
    border-top: 2px solid {COLOR_PRIMARY};
    border-bottom: 1px solid {COLOR_BG_SURFACE};
}}

QTabBar::tab:hover:!selected {{
    color: {COLOR_TEXT_MAIN};
    background: {COLOR_BG_RAISED};
}}

/* Table Widget */
QTableWidget, QTableView {{
    background-color: {COLOR_BG_INPUT};
    alternate-background-color: {COLOR_BG_PANEL_ALT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    gridline-color: {COLOR_BORDER};
    color: {COLOR_TEXT_MAIN};
    selection-background-color: {COLOR_BG_RAISED};
    selection-color: {COLOR_TEXT_MAIN};
}}

QHeaderView::section {{
    background-color: {COLOR_BG_SURFACE};
    color: {COLOR_TEXT_MUTED};
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    border-right: 1px solid {COLOR_BORDER};
    font-weight: 500;
    font-size: 11px;
}}

/* CheckBoxes */
QCheckBox {{
    background-color: transparent;
    color: {COLOR_TEXT_MAIN};
    spacing: 8px;
    min-height: 24px;
    padding: 2px 0px;
    font-size: 13px;
}}

QCheckBox:hover {{
    color: #FFFFFF;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {COLOR_BORDER_LIGHT};
    border-radius: 4px;
    background-color: {COLOR_BG_INPUT};
}}

QCheckBox::indicator:hover {{
    border: 1.5px solid {COLOR_PRIMARY_HOVER};
    background-color: {COLOR_BG_RAISED};
}}

QCheckBox::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border: 1.5px solid {COLOR_PRIMARY};
    image: url({CHECK_ICON_URL});
}}

QCheckBox::indicator:checked:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
    border: 1.5px solid {COLOR_PRIMARY_HOVER};
}}

QCheckBox:disabled {{
    color: {COLOR_TEXT_HINT};
}}

QCheckBox::indicator:disabled {{
    border-color: {COLOR_BORDER};
    background-color: {COLOR_BG_SURFACE};
}}

/* Radio Buttons (distinct circular indicator) */
QRadioButton {{
    background-color: transparent;
    color: {COLOR_TEXT_MAIN};
    spacing: 8px;
    min-height: 24px;
    padding: 2px 0px;
    font-size: 13px;
}}

QRadioButton:hover {{
    color: #FFFFFF;
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {COLOR_BORDER_LIGHT};
    border-radius: 9px;
    background-color: {COLOR_BG_INPUT};
}}

QRadioButton::indicator:hover {{
    border: 1px solid {COLOR_PRIMARY_HOVER};
    background-color: {COLOR_BG_RAISED};
}}

QRadioButton::indicator:checked {{
    width: 8px;
    height: 8px;
    background-color: {COLOR_BG_INPUT};
    border: 5px solid {COLOR_PRIMARY};
    border-radius: 9px;
}}

QRadioButton:disabled {{
    color: {COLOR_TEXT_HINT};
}}

QRadioButton::indicator:disabled {{
    border-color: {COLOR_BORDER};
    background-color: {COLOR_BG_SURFACE};
}}

/* Progress Bar (Solid, clean bar) */
QProgressBar {{
    background-color: {COLOR_BG_INPUT};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    text-align: center;
    color: {COLOR_TEXT_MAIN};
    font-weight: 500;
    font-size: 11px;
    height: 8px;
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
    background: {COLOR_TEXT_MAIN};
    border: 2px solid {COLOR_PRIMARY};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: #FFFFFF;
    border: 2px solid {COLOR_PRIMARY_HOVER};
}}

/* Splitters */
QSplitter::handle {{
    background-color: {COLOR_BORDER};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {COLOR_BG_WINDOW};
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {COLOR_BORDER_LIGHT};
    min-height: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {COLOR_TEXT_MUTED};
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
    background: {COLOR_BORDER_LIGHT};
    min-width: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {COLOR_TEXT_MUTED};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
"""
