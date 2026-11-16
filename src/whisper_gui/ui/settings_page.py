"""Dedicated sequential settings page that scrolls top-to-bottom within the main window."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
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

from whisper_gui.i18n import tr
from whisper_gui.ui.llm_panel import LLMPanel
from whisper_gui.ui.settings_panel import SettingsPanel
from whisper_gui.ui.theme import get_palette, load_ui_icon


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
        self.nav_bar = QFrame()
        self.nav_bar.setObjectName("settings_nav_bar")
        self.nav_bar.setFixedHeight(48)
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(12, 0, 12, 0)
        nav_layout.setSpacing(12)
        nav_layout.setAlignment(Qt.AlignVCenter)

        self.btn_back = QPushButton(tr("settings_page.back"))
        self.btn_back.setFixedHeight(32)
        self.btn_back.setIconSize(QSize(16, 16))
        self.btn_back.setStyleSheet("padding: 4px 12px; font-size: 12px; font-weight: 500;")
        self.btn_back.clicked.connect(self.back_requested.emit)
        nav_layout.addWidget(self.btn_back)

        self.page_title = QLabel(tr("settings_page.title"))
        nav_layout.addWidget(self.page_title)

        nav_layout.addStretch()
        layout.addWidget(self.nav_bar)

        # Sequential Scrollable Container
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        # Centered container for optimal readability
        center_host = QWidget()
        center_host.setObjectName("settings_center_host")
        center_host.setStyleSheet("#settings_center_host { background: transparent; }")
        center_host_layout = QHBoxLayout(center_host)
        center_host_layout.setContentsMargins(16, 12, 16, 24)
        center_host_layout.setAlignment(Qt.AlignHCenter)

        content = QWidget()
        content.setObjectName("settings_content")
        content.setMaximumWidth(680)
        content.setStyleSheet("#settings_content { background: transparent; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        # Section 1: Speech Recognition & Storage/Memory
        self.sec1_frame = QFrame()
        self.sec1_frame.setObjectName("sec1_card")
        sec1_layout = QVBoxLayout(self.sec1_frame)
        sec1_layout.setContentsMargins(24, 24, 24, 24)
        sec1_layout.addWidget(self.settings_panel)
        content_layout.addWidget(self.sec1_frame)

        # Section 2: Transcript Polishing
        self.sec2_frame = QFrame()
        self.sec2_frame.setObjectName("sec2_card")
        sec2_layout = QVBoxLayout(self.sec2_frame)
        sec2_layout.setContentsMargins(24, 24, 24, 24)
        sec2_layout.addWidget(self.llm_panel)
        content_layout.addWidget(self.sec2_frame)

        content_layout.addStretch()
        center_host_layout.addWidget(content)
        self.scroll_area.setWidget(center_host)
        layout.addWidget(self.scroll_area, stretch=1)

        # Forward mouse wheel over any inputs/dropdowns to scroll the settings page
        self.wheel_filter = ScrollBubbleFilter(self.scroll_area)
        for panel in (self.settings_panel, self.llm_panel):
            for child in panel.findChildren(QComboBox) + panel.findChildren(QSpinBox):
                child.installEventFilter(self.wheel_filter)

        self.apply_theme()

    def scroll_to_llm(self) -> None:
        """Scroll the settings page so the LLM Transcript Polishing card is visible."""
        self.scroll_area.ensureWidgetVisible(self.sec2_frame, 0, 20)

    def retranslate_ui(self) -> None:
        """Update static labels to the active application language."""
        self.btn_back.setText(tr("settings_page.back"))
        self.page_title.setText(tr("settings_page.title"))

    def apply_theme(self) -> None:
        """Apply the active palette to the settings page container and cards."""
        p = get_palette()
        self.nav_bar.setStyleSheet(f"""
            #settings_nav_bar {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.btn_back.setIcon(load_ui_icon("arrow-left"))
        self.page_title.setStyleSheet(f"color: {p.text_main}; font-size: 14px; font-weight: 500;")
        self.sec1_frame.setStyleSheet(f"""
            #sec1_card {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            #sec1_card QCheckBox, #sec1_card QLabel, #sec1_card #settings_panel {{
                background-color: transparent;
            }}
        """)
        self.sec2_frame.setStyleSheet(f"""
            #sec2_card {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            #sec2_card QCheckBox, #sec2_card QLabel, #sec2_card #llm_panel, #sec2_card #llm_controls_container {{
                background-color: transparent;
            }}
        """)
