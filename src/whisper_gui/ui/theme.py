"""Theme definitions, palettes, and application stylesheets.

Supports switchable Graphite (dark) and Blush Pink (#F8C8DC / #F3CFC6) themes
with hairline borders, tabular monospace helpers, and tinted 16px SVG icons.
"""

from __future__ import annotations

from dataclasses import dataclass
import weakref

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QListView,
    QMenu,
    QStyle,
    QStyleOptionButton,
)

from whisper_gui.platform_utils import get_asset_path

_check_asset = get_asset_path("check.svg")
CHECK_ICON_URL = _check_asset.as_posix() if _check_asset else ""

_chevron_asset = get_asset_path("icons/chevron-down.svg")
CHEVRON_ICON_URL = _chevron_asset.as_posix() if _chevron_asset else ""

_chevron_dark_asset = get_asset_path("icons/chevron-down-dark.svg")
CHEVRON_DARK_ICON_URL = _chevron_dark_asset.as_posix() if _chevron_dark_asset else CHEVRON_ICON_URL


@dataclass(frozen=True)
class ThemePalette:
    """Color and asset tokens for a complete application theme."""

    name: str
    label: str
    bg_window: str
    bg_surface: str
    bg_raised: str
    bg_input: str
    bg_panel_alt: str
    border: str
    border_light: str
    button_hover_bg: str
    button_hover_border: str
    text_main: str
    text_secondary: str
    text_muted: str
    text_hint: str
    text_hover: str
    primary: str
    primary_hover: str
    primary_pressed: str
    primary_text: str
    secondary: str
    secondary_hover: str
    secondary_pressed: str
    secondary_text: str
    positive: str
    warning: str
    negative: str
    chevron_url: str


GRAPHITE_PALETTE = ThemePalette(
    name="graphite",
    label="Graphite",
    bg_window="#141415",
    bg_surface="#19191B",
    bg_raised="#232325",
    bg_input="#0F0F10",
    bg_panel_alt="#161618",
    border="#2B2B2E",
    border_light="#3C3C40",
    button_hover_bg="#2C2C30",
    button_hover_border="#4A4A50",
    text_main="#EDEDED",
    text_secondary="#A1A1A6",
    text_muted="#85858B",
    text_hint="#68686E",
    text_hover="#FFFFFF",
    primary="#2563EB",
    primary_hover="#3B82F6",
    primary_pressed="#1D4ED8",
    primary_text="#FFFFFF",
    secondary="#E5484D",
    secondary_hover="#F06368",
    secondary_pressed="#C93B40",
    secondary_text="#FFFFFF",
    positive="#4CC38A",
    warning="#E5A93B",
    negative="#E5484D",
    chevron_url=CHEVRON_ICON_URL,
)

BLUSH_PALETTE = ThemePalette(
    name="blush",
    label="Blush Pink",
    bg_window="#F3CFC6",
    bg_surface="#F8C8DC",
    bg_raised="#F9DAE6",
    bg_input="#FAE6EE",
    bg_panel_alt="#F8D8E4",
    border="#E0B4C5",
    border_light="#CF9CB1",
    button_hover_bg="#FBE2EB",
    button_hover_border="#BC849B",
    text_main="#52323F",
    text_secondary="#694754",
    text_muted="#72505D",
    text_hint="#967582",
    text_hover="#3E222E",
    primary="#A84269",
    primary_hover="#96365B",
    primary_pressed="#822C4D",
    primary_text="#FFFFFF",
    secondary="#B94656",
    secondary_hover="#A63A49",
    secondary_pressed="#8F303D",
    secondary_text="#FFFFFF",
    positive="#276E51",
    warning="#87571A",
    negative="#B94656",
    chevron_url=CHEVRON_DARK_ICON_URL,
)

THEMES: dict[str, ThemePalette] = {
    "graphite": GRAPHITE_PALETTE,
    "blush": BLUSH_PALETTE,
}

_active_palette: ThemePalette = GRAPHITE_PALETTE

# Backward-compatible module-level tokens (synced on set_theme)
COLOR_PRIMARY = GRAPHITE_PALETTE.primary
COLOR_PRIMARY_HOVER = GRAPHITE_PALETTE.primary_hover
COLOR_PRIMARY_PRESSED = GRAPHITE_PALETTE.primary_pressed
COLOR_PRIMARY_TEXT = GRAPHITE_PALETTE.primary_text

COLOR_SECONDARY = GRAPHITE_PALETTE.secondary
COLOR_SECONDARY_HOVER = GRAPHITE_PALETTE.secondary_hover
COLOR_SECONDARY_PRESSED = GRAPHITE_PALETTE.secondary_pressed
COLOR_SECONDARY_TEXT = GRAPHITE_PALETTE.secondary_text

COLOR_POSITIVE = GRAPHITE_PALETTE.positive
COLOR_WARNING = GRAPHITE_PALETTE.warning
COLOR_NEGATIVE = GRAPHITE_PALETTE.negative

COLOR_BG_WINDOW = GRAPHITE_PALETTE.bg_window
COLOR_BG_SURFACE = GRAPHITE_PALETTE.bg_surface
COLOR_BG_RAISED = GRAPHITE_PALETTE.bg_raised
COLOR_BG_INPUT = GRAPHITE_PALETTE.bg_input
COLOR_BG_PANEL_ALT = GRAPHITE_PALETTE.bg_panel_alt

COLOR_BORDER = GRAPHITE_PALETTE.border
COLOR_BORDER_LIGHT = GRAPHITE_PALETTE.border_light
COLOR_BORDER_PRIMARY = GRAPHITE_PALETTE.primary_hover
COLOR_BORDER_SECONDARY = GRAPHITE_PALETTE.secondary

COLOR_TEXT_MAIN = GRAPHITE_PALETTE.text_main
COLOR_TEXT_SECONDARY = GRAPHITE_PALETTE.text_secondary
COLOR_TEXT_MUTED = GRAPHITE_PALETTE.text_muted
COLOR_TEXT_HINT = GRAPHITE_PALETTE.text_hint


def get_palette() -> ThemePalette:
    """Return the currently active theme palette."""
    return _active_palette


def get_theme_name() -> str:
    """Return the active theme key ('graphite' or 'blush')."""
    return _active_palette.name


def load_tinted_pixmap(rel_path: str, size: QSize | int, color: str | None = None) -> QPixmap:
    """Load an SVG/image asset and tint it cleanly at 2x HiDPI resolution."""
    path = get_asset_path(rel_path)
    if not path:
        return QPixmap()
    qsize = QSize(size, size) if isinstance(size, int) else size
    dpr = 2.0
    tinted = QPixmap(int(qsize.width() * dpr), int(qsize.height() * dpr))
    tinted.setDevicePixelRatio(dpr)
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    logical_rect = QRect(QPoint(0, 0), qsize)
    QIcon(str(path)).paint(painter, logical_rect)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(logical_rect, QColor(color or _active_palette.text_secondary))
    painter.end()
    return tinted


def load_ui_icon(name: str, color: str | None = None) -> QIcon:
    """Load a 16px line icon from assets/icons/<name>.svg tinted to the current palette."""
    pixmap = load_tinted_pixmap(f"icons/{name}.svg", 16, color)
    return QIcon(pixmap) if not pixmap.isNull() else QIcon()


def swatch_icon(primary_hex: str, secondary_hex: str, border_hex: str) -> QIcon:
    """Create a crisp 14px two-tone circular swatch icon for theme selector buttons."""
    size = 14
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(1.0, 1.0, size - 2.0, size - 2.0)

    clip = QPainterPath()
    clip.addEllipse(rect)
    painter.setClipPath(clip)
    painter.fillRect(QRectF(rect.left(), rect.top(), rect.width() / 2.0 + 0.5, rect.height()), QColor(primary_hex))
    painter.fillRect(QRectF(rect.center().x(), rect.top(), rect.width() / 2.0 + 0.5, rect.height()), QColor(secondary_hex))
    painter.setClipping(False)

    painter.setPen(QColor(border_hex))
    painter.drawEllipse(rect)
    painter.end()
    return QIcon(pm)


def fixed_mono_font(point_size: int | None = None) -> QFont:
    """Return the platform fixed-width font for tabular timecodes and counts."""
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    if point_size is not None:
        font.setPointSize(point_size)
    return font


class _ComboContainerPopupFilter(QObject):
    """Snap QComboBox popup container to exact combo width and a 4px vertical gap without QProxyStyle."""

    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)
        self._combo_ref = weakref.ref(combo)
        self._guard = False

    def _snap(self, container) -> None:
        if self._guard:
            return
        combo = self._combo_ref()
        if combo is None or container is None:
            return
        self._guard = True
        try:
            top_left = combo.mapToGlobal(QPoint(0, 0))
            w = combo.width()
            h = container.height()
            if w <= 0 or h <= 0:
                return
            below_y = top_left.y() + combo.height() + 4
            above_y = top_left.y() - h - 4
            flipped_above = (container.y() + h / 2.0) < (top_left.y() + combo.height() / 2.0)
            new_y = above_y if flipped_above else below_y
            target = (top_left.x(), new_y, w, h)
            current = (container.x(), container.y(), container.width(), container.height())
            if current != target:
                container.setGeometry(*target)
        finally:
            self._guard = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Show, QEvent.Type.Move, QEvent.Type.Resize):
            self._snap(obj)
        return False


def style_combobox(combo: QComboBox, max_visible: int = 10) -> QComboBox:
    """Configure a QComboBox for single-frame, index-invariant popup rendering."""
    view = combo.view()
    if not isinstance(view, QListView):
        view = QListView()
        combo.setView(view)

    combo.setMaxVisibleItems(max_visible)
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setUniformItemSizes(True)

    container = view.parentWidget()
    if container is not None:
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        container.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        if isinstance(container, QFrame):
            container.setFrameShape(QFrame.Shape.NoFrame)
        container.setContentsMargins(0, 0, 0, 0)
        if container.layout() is not None:
            container.layout().setContentsMargins(0, 0, 0, 0)
        if not any(isinstance(ch, _ComboContainerPopupFilter) for ch in combo.children()):
            popup_filter = _ComboContainerPopupFilter(combo)
            container.installEventFilter(popup_filter)

    return combo


def menu_stylesheet(p: ThemePalette | None = None) -> str:
    """Return the shared QMenu stylesheet with a single hairline border and 4px grid."""
    t = p or _active_palette
    return f"""
        QMenu {{
            background-color: {t.bg_surface};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 20px 6px 12px;
            border-radius: 4px;
            color: {t.text_main};
        }}
        QMenu::item:selected {{
            background-color: {t.bg_raised};
            color: {t.text_main};
        }}
    """


def style_menu(menu: QMenu) -> QMenu:
    """Configure a QMenu popup window with clean transparent corners."""
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    return menu


class ToggleSwitch(QCheckBox):
    """Apple-style pill toggle switch supporting both click-to-toggle and smooth drag."""

    _TRACK_W = 36
    _TRACK_H = 20
    _GAP = 8
    _KNOB_D = 16.0
    _TRAVEL_PX = 16.0  # _TRACK_W - _KNOB_D - 2 * 2px inset
    _DRAG_THRESHOLD = 3.0

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if self.isChecked() else 0.0
        self._pressed = False
        self._dragging = False
        self._press_x = 0.0
        self._press_pos = self._pos
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self.toggled.connect(self._on_toggled)

    def _on_anim_value(self, value) -> None:
        self._pos = float(value)
        self.update()

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        if not self.isVisible() or abs(self._pos - target) < 0.005:
            self._pos = target
            self.update()
            return
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_toggled(self, checked: bool) -> None:
        self._animate_to(1.0 if checked else 0.0)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self._anim.stop()
            self._pressed = True
            self._dragging = False
            self._press_x = event.position().x()
            self._press_pos = self._pos
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed and (event.buttons() & Qt.LeftButton):
            dx = event.position().x() - self._press_x
            if not self._dragging and abs(dx) >= self._DRAG_THRESHOLD:
                self._dragging = True
            if self._dragging:
                self._pos = max(0.0, min(1.0, self._press_pos + dx / self._TRAVEL_PX))
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._pressed:
            was_dragging = self._dragging
            self._pressed = False
            self._dragging = False
            if was_dragging:
                target_checked = self._pos >= 0.5
                if target_checked != self.isChecked():
                    self.setChecked(target_checked)
                else:
                    # Drag stopped short of midpoint: animate smoothly back instead of hanging
                    self._animate_to(1.0 if target_checked else 0.0)
            elif self.rect().contains(event.position().toPoint()):
                self.click()
            else:
                self._animate_to(1.0 if self.isChecked() else 0.0)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def sizeHint(self) -> QSize:
        self.ensurePolished()
        fm = self.fontMetrics()
        text_w = fm.horizontalAdvance(self.text()) if self.text() else 0
        w = self._TRACK_W + (self._GAP + text_w if text_w else 0) + 4
        h = max(self._TRACK_H + 4, fm.height() + 4)
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        opt = QStyleOptionButton()
        self.initStyleOption(opt)

        p = get_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        t = self._pos
        hovered = bool(opt.state & QStyle.State_MouseOver)
        enabled = self.isEnabled()

        off_color = QColor(p.button_hover_bg) if p.name == "graphite" else QColor(p.border)
        on_color = QColor(p.primary_hover if hovered else p.primary)
        r = round(off_color.red() * (1.0 - t) + on_color.red() * t)
        g = round(off_color.green() * (1.0 - t) + on_color.green() * t)
        b = round(off_color.blue() * (1.0 - t) + on_color.blue() * t)
        track_color = QColor(r, g, b)

        track_y = (self.height() - self._TRACK_H) / 2.0
        track_rect = QRectF(0.5, track_y + 0.5, self._TRACK_W - 1.0, self._TRACK_H - 1.0)
        radius = (self._TRACK_H - 1.0) / 2.0

        if not enabled:
            painter.setOpacity(0.45)

        painter.setBrush(track_color)
        if t < 0.99:
            painter.setPen(QColor(p.button_hover_border if hovered else p.border_light))
        else:
            painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(track_rect, radius, radius)

        knob_d = 16.0
        knob_margin = (self._TRACK_H - knob_d) / 2.0
        knob_x = knob_margin + (self._TRACK_W - knob_d - 2.0 * knob_margin) * t
        knob_y = track_y + knob_margin
        knob_rect = QRectF(knob_x, knob_y, knob_d, knob_d)

        knob_color = QColor("#FFFFFF") if (p.name != "graphite" or t > 0.25) else QColor("#D4D4D8")
        painter.setBrush(knob_color)
        painter.setPen(QColor(0, 0, 0, 26))
        painter.drawEllipse(knob_rect)

        if self.text():
            painter.setFont(self.font())
            painter.setPen(opt.palette.windowText().color())
            text_rect = QRectF(
                self._TRACK_W + self._GAP,
                0,
                max(0, self.width() - (self._TRACK_W + self._GAP)),
                self.height(),
            )
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())

        painter.end()


def build_stylesheet(p: ThemePalette | None = None) -> str:
    """Build the complete application stylesheet for the given palette."""
    t = p or _active_palette
    return f"""
/* Global Window & Typography */
QMainWindow, QWidget {{
    background-color: {t.bg_window};
    color: {t.text_main};
    font-size: 13px;
    font-weight: 400;
}}

/* Containers & Surface Cards */
.QFrame {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border};
    border-radius: 12px;
}}

/* Text Labels */
QLabel {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    color: {t.text_main};
}}

QGroupBox {{
    border: 1px solid {t.border};
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 500;
}}

/* Form Controls & Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background-color: {t.bg_input};
    color: {t.text_main};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 8px 12px;
    selection-background-color: {t.primary};
    selection-color: {t.primary_text};
}}

QSpinBox, QDoubleSpinBox, QTimeEdit {{
    background-color: {t.bg_input};
    color: {t.text_main};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: {t.primary};
    selection-color: {t.primary_text};
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTimeEdit:hover, QComboBox:hover {{
    border: 1px solid {t.border_light};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QComboBox:focus {{
    border: 1px solid {t.primary};
}}

QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QTimeEdit:disabled {{
    background-color: {t.bg_input};
    color: {t.text_hint};
    border: 1px solid {t.border};
}}

/* Dropdowns / ComboBox */
QComboBox {{
    combobox-popup: 0;
    padding: 8px 12px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border: none;
    border-left: 1px solid {t.border};
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    background-color: transparent;
}}

QComboBox::drop-down:hover {{
    background-color: {t.bg_raised};
}}

QComboBox::down-arrow {{
    image: url({t.chevron_url});
    width: 14px;
    height: 14px;
}}

QComboBoxPrivateContainer {{
    background-color: transparent;
    border: none;
    margin: 0px;
    padding: 0px;
}}

QComboBox QAbstractItemView,
QComboBox QListView {{
    background-color: {t.bg_surface};
    color: {t.text_main};
    border: 1px solid {t.border};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {t.bg_raised};
    selection-color: {t.text_main};
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
    background-color: {t.bg_raised};
    color: {t.text_main};
}}

QComboBox QAbstractItemView::item:selected,
QComboBox QListView::item:selected {{
    background-color: {t.primary};
    color: {t.primary_text};
}}

QComboBox QAbstractItemView #qt_scrollarea_vcontainer,
QComboBox QListView #qt_scrollarea_vcontainer {{
    background-color: transparent;
    border: none;
}}

QComboBox QAbstractItemView QScrollBar:vertical,
QComboBox QListView QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 4px 2px 4px 0px;
}}

QComboBox QAbstractItemView QScrollBar::handle:vertical,
QComboBox QListView QScrollBar::handle:vertical {{
    background: {t.border_light};
    min-height: 24px;
    border-radius: 3px;
}}

QComboBox QAbstractItemView QScrollBar::handle:vertical:hover,
QComboBox QListView QScrollBar::handle:vertical:hover {{
    background: {t.text_muted};
}}

QComboBox QAbstractItemView QScrollBar::add-line:vertical,
QComboBox QAbstractItemView QScrollBar::sub-line:vertical,
QComboBox QListView QScrollBar::add-line:vertical,
QComboBox QListView QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QComboBox QLineEdit {{
    background-color: transparent;
    border: none;
    padding: 0px;
    color: {t.text_main};
}}

/* PushButtons */
QPushButton {{
    background-color: {t.bg_raised};
    color: {t.text_main};
    border: 1px solid {t.border_light};
    border-radius: 8px;
    padding: 4px 12px;
    font-weight: 500;
    font-size: 12px;
    min-height: 22px;
}}

QPushButton:hover {{
    background-color: {t.button_hover_bg};
    border: 1px solid {t.button_hover_border};
}}

QPushButton:pressed {{
    background-color: {t.bg_surface};
    border: 1px solid {t.border};
}}

QPushButton:disabled {{
    background-color: {t.bg_surface};
    color: {t.text_hint};
    border: 1px solid {t.border};
}}

/* Tabs Widget */
QTabWidget::pane {{
    border: 1px solid {t.border};
    border-radius: 8px;
    background-color: {t.bg_surface};
    top: -1px;
}}

QTabBar::tab {{
    background: {t.bg_window};
    color: {t.text_muted};
    padding: 8px 16px;
    font-weight: 500;
    font-size: 12px;
    border: 1px solid {t.border};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}}

QTabBar::tab:selected {{
    background: {t.bg_surface};
    color: {t.text_main};
    border: 1px solid {t.border};
    border-top: 2px solid {t.primary};
    border-bottom: 1px solid {t.bg_surface};
}}

QTabBar::tab:hover:!selected {{
    color: {t.text_main};
    background: {t.bg_raised};
}}

/* Table Widget */
QTableWidget, QTableView {{
    background-color: {t.bg_input};
    alternate-background-color: {t.bg_panel_alt};
    border: 1px solid {t.border};
    border-radius: 8px;
    gridline-color: {t.border};
    color: {t.text_main};
    selection-background-color: {t.bg_raised};
    selection-color: {t.text_main};
}}

QHeaderView::section {{
    background-color: {t.bg_surface};
    color: {t.text_muted};
    padding: 6px 12px;
    border: none;
    border-bottom: 1px solid {t.border};
    font-weight: 500;
    font-size: 11px;
}}

/* CheckBoxes */
QCheckBox {{
    background-color: transparent;
    color: {t.text_main};
    spacing: 8px;
    min-height: 24px;
    padding: 2px 0px;
    font-size: 13px;
}}

QCheckBox:hover {{
    color: {t.text_hover};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {t.border_light};
    border-radius: 4px;
    background-color: {t.bg_input};
}}

QCheckBox::indicator:hover {{
    border: 1.5px solid {t.primary_hover};
    background-color: {t.bg_raised};
}}

QCheckBox::indicator:checked {{
    background-color: {t.primary};
    border: 1.5px solid {t.primary};
    image: url({CHECK_ICON_URL});
}}

QCheckBox::indicator:checked:hover {{
    background-color: {t.primary_hover};
    border: 1.5px solid {t.primary_hover};
}}

QCheckBox:disabled {{
    color: {t.text_hint};
}}

QCheckBox::indicator:disabled {{
    border-color: {t.border};
    background-color: {t.bg_surface};
}}

/* Radio Buttons (distinct circular indicator) */
QRadioButton {{
    background-color: transparent;
    color: {t.text_main};
    spacing: 8px;
    min-height: 24px;
    padding: 2px 0px;
    font-size: 13px;
}}

QRadioButton:hover {{
    color: {t.text_hover};
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {t.border_light};
    border-radius: 9px;
    background-color: {t.bg_input};
}}

QRadioButton::indicator:hover {{
    border: 1px solid {t.primary_hover};
    background-color: {t.bg_raised};
}}

QRadioButton::indicator:checked {{
    width: 8px;
    height: 8px;
    background-color: {t.bg_input};
    border: 5px solid {t.primary};
    border-radius: 9px;
}}

QRadioButton:disabled {{
    color: {t.text_hint};
}}

QRadioButton::indicator:disabled {{
    border-color: {t.border};
    background-color: {t.bg_surface};
}}

/* Progress Bar */
QProgressBar {{
    background-color: {t.bg_raised};
    border: none;
    border-radius: 2px;
    text-align: center;
    color: {t.text_main};
    font-weight: 500;
    font-size: 11px;
    height: 4px;
}}

QProgressBar::chunk {{
    background-color: {t.primary};
    border-radius: 2px;
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 6px;
    background: {t.bg_input};
    border: 1px solid {t.border};
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{
    background: {t.primary};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {t.text_main};
    border: 2px solid {t.primary};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: {t.text_hover};
    border: 2px solid {t.primary_hover};
}}

/* Splitters */
QSplitter::handle {{
    background-color: {t.border};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {t.bg_window};
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {t.border_light};
    min-height: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {t.text_muted};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: {t.bg_window};
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {t.border_light};
    min-width: 24px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {t.text_muted};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Status Bar */
QStatusBar {{
    background-color: {t.bg_window};
    color: {t.text_muted};
    border-top: 1px solid {t.border};
    font-size: 12px;
    padding: 2px 12px;
}}

{menu_stylesheet(t)}
"""


def set_theme(name: str) -> ThemePalette:
    """Switch the active palette and refresh exported module tokens."""
    global _active_palette
    global COLOR_PRIMARY, COLOR_PRIMARY_HOVER, COLOR_PRIMARY_PRESSED, COLOR_PRIMARY_TEXT
    global COLOR_SECONDARY, COLOR_SECONDARY_HOVER, COLOR_SECONDARY_PRESSED, COLOR_SECONDARY_TEXT
    global COLOR_POSITIVE, COLOR_WARNING, COLOR_NEGATIVE
    global COLOR_BG_WINDOW, COLOR_BG_SURFACE, COLOR_BG_RAISED, COLOR_BG_INPUT, COLOR_BG_PANEL_ALT
    global COLOR_BORDER, COLOR_BORDER_LIGHT, COLOR_BORDER_PRIMARY, COLOR_BORDER_SECONDARY
    global COLOR_TEXT_MAIN, COLOR_TEXT_SECONDARY, COLOR_TEXT_MUTED, COLOR_TEXT_HINT
    global GLOBAL_STYLESHEET

    palette = THEMES.get(name, GRAPHITE_PALETTE)
    _active_palette = palette

    COLOR_PRIMARY = palette.primary
    COLOR_PRIMARY_HOVER = palette.primary_hover
    COLOR_PRIMARY_PRESSED = palette.primary_pressed
    COLOR_PRIMARY_TEXT = palette.primary_text

    COLOR_SECONDARY = palette.secondary
    COLOR_SECONDARY_HOVER = palette.secondary_hover
    COLOR_SECONDARY_PRESSED = palette.secondary_pressed
    COLOR_SECONDARY_TEXT = palette.secondary_text

    COLOR_POSITIVE = palette.positive
    COLOR_WARNING = palette.warning
    COLOR_NEGATIVE = palette.negative

    COLOR_BG_WINDOW = palette.bg_window
    COLOR_BG_SURFACE = palette.bg_surface
    COLOR_BG_RAISED = palette.bg_raised
    COLOR_BG_INPUT = palette.bg_input
    COLOR_BG_PANEL_ALT = palette.bg_panel_alt

    COLOR_BORDER = palette.border
    COLOR_BORDER_LIGHT = palette.border_light
    COLOR_BORDER_PRIMARY = palette.primary_hover
    COLOR_BORDER_SECONDARY = palette.secondary

    COLOR_TEXT_MAIN = palette.text_main
    COLOR_TEXT_SECONDARY = palette.text_secondary
    COLOR_TEXT_MUTED = palette.text_muted
    COLOR_TEXT_HINT = palette.text_hint

    GLOBAL_STYLESHEET = build_stylesheet(palette)
    return palette


GLOBAL_STYLESHEET = build_stylesheet(GRAPHITE_PALETTE)
