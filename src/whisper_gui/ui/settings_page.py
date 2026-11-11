"""Dedicated sequential settings page that scrolls top-to-bottom within the main window."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.ui.llm_panel import LLMPanel
from whisper_gui.ui.settings_panel import SettingsPanel
from whisper_gui.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BG_SURFACE,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_TEXT,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
)


class ScrollBubbleFilter(QObject):
    """Filters wheel events on controls so mouse scrolling moves the page instead of changing values."""

    def __init__(self, scroll_area: QScrollArea) -> None:
        super().__init__()
        self.scroll_area = scroll_area

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Wheel:
            # If a combobox popup list is currently open, allow scrolling the list
            if isinstance(obj, QComboBox) and obj.view() and obj.view().isVisible():
                return False
            # Forward the wheel event to the scroll area so the page scrolls smoothly
            QApplication.sendEvent(self.scroll_area.verticalScrollBar(), event)
            return True
        return super().eventFilter(obj, event)


class SettingsPageWidget(QWidget):
    """Dedicated sequential in-window settings page."""

    back_requested = Signal()

    def __init__(
        self,
        settings_panel: SettingsPanel,
        llm_panel: LLMPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings_panel = settings_panel
        self.llm_panel = llm_panel
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # Top Navigation Bar
        nav_bar = QFrame()
        nav_bar.setObjectName("settings_nav_bar")
        nav_bar.setFixedHeight(48)
        nav_bar.setStyleSheet(f"""
            #settings_nav_bar {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(16, 0, 16, 0)
        nav_layout.setSpacing(14)
        nav_layout.setAlignment(Qt.AlignVCenter)

        self.btn_back = QPushButton("← Back to Transcribe")
        self.btn_back.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
                font-weight: 600;
                font-size: 12px;
                padding: 6px 16px;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY_HOVER};
            }}
        """)
        self.btn_back.clicked.connect(self.back_requested.emit)
        nav_layout.addWidget(self.btn_back)

        page_title = QLabel("Settings")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        page_title.setFont(title_font)
        page_title.setStyleSheet(f"color: {COLOR_TEXT_MAIN}; font-weight: 700;")
        nav_layout.addWidget(page_title)

        nav_layout.addStretch()
        layout.addWidget(nav_bar)

        # Sequential Scrollable Container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        # Centered container for optimal readability
        center_host = QWidget()
        center_host.setObjectName("settings_center_host")
        center_host.setStyleSheet("#settings_center_host { background: transparent; }")
        center_host_layout = QHBoxLayout(center_host)
        center_host_layout.setContentsMargins(0, 8, 0, 20)
        center_host_layout.setAlignment(Qt.AlignHCenter)

        content = QWidget()
        content.setObjectName("settings_content")
        content.setMaximumWidth(680)
        content.setStyleSheet("#settings_content { background: transparent; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(20)

        # Section 1: Speech Recognition & Storage/Memory
        sec1_frame = QFrame()
        sec1_frame.setObjectName("sec1_card")
        sec1_frame.setStyleSheet(f"""
            #sec1_card {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            #sec1_card QCheckBox, #sec1_card QLabel {{
                background-color: transparent;
            }}
        """)
        sec1_layout = QVBoxLayout(sec1_frame)
        sec1_layout.setContentsMargins(24, 20, 24, 20)
        sec1_layout.addWidget(self.settings_panel)
        content_layout.addWidget(sec1_frame)

        # Section 2: AI Speech Polishing
        sec2_frame = QFrame()
        sec2_frame.setObjectName("sec2_card")
        sec2_frame.setStyleSheet(f"""
            #sec2_card {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            #sec2_card QCheckBox, #sec2_card QLabel {{
                background-color: transparent;
            }}
        """)
        sec2_layout = QVBoxLayout(sec2_frame)
        sec2_layout.setContentsMargins(24, 20, 24, 20)
        sec2_layout.addWidget(self.llm_panel)
        content_layout.addWidget(sec2_frame)

        content_layout.addStretch()
        center_host_layout.addWidget(content)
        scroll.setWidget(center_host)
        layout.addWidget(scroll, stretch=1)

        # Forward mouse wheel over any inputs/dropdowns to scroll the settings page
        self.wheel_filter = ScrollBubbleFilter(scroll)
        for panel in (self.settings_panel, self.llm_panel):
            for child in panel.findChildren(QComboBox) + panel.findChildren(QSpinBox):
                child.installEventFilter(self.wheel_filter)
