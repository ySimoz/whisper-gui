"""In-window transcript history page for browsing and reopening completed transcripts."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.history import HistoryEntry, TranscriptHistoryStore
from whisper_gui.i18n import tr
from whisper_gui.ui.theme import fixed_mono_font, get_palette, load_ui_icon


class HistoryRowWidget(QWidget):
    """Single transcript entry row inside the history list."""

    open_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, entry: HistoryEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("history_row")
        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)

        info_col = QVBoxLayout()
        info_col.setSpacing(4)

        self.lbl_title = QLabel(self.entry.filename)
        info_col.addWidget(self.lbl_title)

        meta_parts = [self.entry.formatted_date(), self.entry.formatted_duration()]
        if self.entry.model_name:
            meta_parts.append(self.entry.model_name)
        if self.entry.detected_language:
            meta_parts.append(self.entry.detected_language)
        if self.entry.polished_text and self.entry.polished_text.strip():
            meta_parts.append(tr("history.badge_polished"))

        self.lbl_meta = QLabel(" · ".join(meta_parts))
        self.lbl_meta.setFont(fixed_mono_font(11))
        info_col.addWidget(self.lbl_meta)

        preview = self.entry.preview_text(140)
        self.lbl_preview = QLabel(preview or tr("history.empty_preview"))
        self.lbl_preview.setWordWrap(False)
        info_col.addWidget(self.lbl_preview)

        row.addLayout(info_col, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.setAlignment(Qt.AlignVCenter)

        self.btn_open = QPushButton(tr("history.open_btn"))
        self.btn_open.setFixedHeight(32)
        self.btn_open.clicked.connect(lambda: self.open_requested.emit(self.entry.id))
        actions.addWidget(self.btn_open)

        self.btn_delete = QPushButton()
        self.btn_delete.setObjectName("history_delete_btn")
        self.btn_delete.setIconSize(QSize(14, 14))
        self.btn_delete.setFixedSize(28, 28)
        self.btn_delete.setToolTip(tr("history.delete_tooltip"))
        self.btn_delete.setStyleSheet("padding: 0px;")
        self.btn_delete.clicked.connect(lambda: self.delete_requested.emit(self.entry.id))
        actions.addWidget(self.btn_delete)

        row.addLayout(actions)

    def apply_theme(self) -> None:
        p = get_palette()
        self.setStyleSheet("#history_row { background: transparent; }")
        self.lbl_title.setStyleSheet(f"color: {p.text_main}; font-size: 13px; font-weight: 500;")
        self.lbl_meta.setStyleSheet(f"color: {p.text_muted};")
        self.lbl_preview.setStyleSheet(f"color: {p.text_secondary}; font-size: 12px;")
        self.btn_open.setStyleSheet("padding: 4px 12px; font-size: 12px; font-weight: 500;")
        self.btn_delete.setIcon(load_ui_icon("close"))


class HistoryPageWidget(QWidget):
    """Dedicated in-window page for searching, opening, and pruning saved transcripts."""

    back_requested = Signal()
    open_entry_requested = Signal(str)

    def __init__(
        self,
        store: TranscriptHistoryStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._row_widgets: list[HistoryRowWidget] = []
        self._dividers: list[QFrame] = []
        self._total_count = 0
        self._shown_count = 0
        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # Top navigation bar matching SettingsPageWidget
        self.nav_bar = QFrame()
        self.nav_bar.setObjectName("history_nav_bar")
        self.nav_bar.setFixedHeight(48)
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(12, 0, 12, 0)
        nav_layout.setSpacing(12)
        nav_layout.setAlignment(Qt.AlignVCenter)

        self.btn_back = QPushButton(tr("settings_page.back"))
        self.btn_back.setIconSize(QSize(16, 16))
        self.btn_back.setStyleSheet("padding: 6px 12px; font-size: 12px; font-weight: 500;")
        self.btn_back.clicked.connect(self.back_requested.emit)
        nav_layout.addWidget(self.btn_back)

        self.page_title = QLabel(tr("history.title"))
        nav_layout.addWidget(self.page_title)

        nav_layout.addStretch()

        self.btn_clear_all = QPushButton(tr("history.clear_all"))
        self.btn_clear_all.setFixedHeight(32)
        self.btn_clear_all.setEnabled(False)
        self.btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        nav_layout.addWidget(self.btn_clear_all)

        layout.addWidget(self.nav_bar)

        # Scrollable centered container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        center_host = QWidget()
        center_host.setObjectName("history_center_host")
        center_host.setStyleSheet("#history_center_host { background: transparent; }")
        center_layout = QHBoxLayout(center_host)
        center_layout.setContentsMargins(0, 8, 0, 20)
        center_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        content = QWidget()
        content.setObjectName("history_content")
        content.setMinimumWidth(520)
        content.setMaximumWidth(720)
        content.setStyleSheet("#history_content { background: transparent; }")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        # Search + count row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText(tr("history.search_placeholder"))
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setFixedHeight(36)
        self.txt_search.textChanged.connect(lambda _text: self.refresh_entries())
        filter_row.addWidget(self.txt_search, stretch=1)

        self.lbl_count = QLabel(tr("history.count_plural", count=0))
        self.lbl_count.setFont(fixed_mono_font(12))
        filter_row.addWidget(self.lbl_count)
        content_layout.addLayout(filter_row)

        # Entries card
        self.entries_card = QFrame()
        self.entries_card.setObjectName("history_entries_card")
        self.entries_layout = QVBoxLayout(self.entries_card)
        self.entries_layout.setContentsMargins(0, 0, 0, 0)
        self.entries_layout.setSpacing(0)
        content_layout.addWidget(self.entries_card)

        # Empty state card
        self.empty_card = QFrame()
        self.empty_card.setObjectName("history_empty_card")
        empty_layout = QVBoxLayout(self.empty_card)
        empty_layout.setContentsMargins(24, 32, 24, 32)
        empty_layout.setSpacing(4)
        empty_layout.setAlignment(Qt.AlignCenter)

        self.lbl_empty_title = QLabel(tr("history.empty_title"))
        self.lbl_empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.lbl_empty_title)

        self.lbl_empty_sub = QLabel(tr("history.empty_body"))
        self.lbl_empty_sub.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.lbl_empty_sub)
        content_layout.addWidget(self.empty_card)

        content_layout.addStretch()
        center_layout.addWidget(content, stretch=1)
        scroll.setWidget(center_host)
        layout.addWidget(scroll, stretch=1)

    def refresh_entries(self) -> None:
        """Reload entries from disk and rebuild the filtered list."""
        query = self.txt_search.text().strip()
        all_entries = self.store.list_entries()
        self._total_count = len(all_entries)
        entries = self.store.list_entries(query=query) if query else all_entries
        self._shown_count = len(entries)

        # Clear existing rows and dividers
        while self.entries_layout.count():
            item = self.entries_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._row_widgets.clear()
        self._dividers.clear()

        p = get_palette()
        for idx, entry in enumerate(entries):
            if idx > 0:
                divider = QFrame()
                divider.setFrameShape(QFrame.HLine)
                divider.setFixedHeight(1)
                divider.setStyleSheet(f"background-color: {p.border}; border: none;")
                self._dividers.append(divider)
                self.entries_layout.addWidget(divider)

            row_widget = HistoryRowWidget(entry, self.entries_card)
            row_widget.open_requested.connect(self.open_entry_requested.emit)
            row_widget.delete_requested.connect(self._on_delete_entry_clicked)
            self._row_widgets.append(row_widget)
            self.entries_layout.addWidget(row_widget)

        has_entries = len(entries) > 0
        self.entries_card.setVisible(has_entries)
        self.empty_card.setVisible(not has_entries)
        self.btn_clear_all.setEnabled(self._total_count > 0)

        self._update_empty_and_count_labels(query)

    def _update_empty_and_count_labels(self, query: str) -> None:
        count = self._shown_count
        key = "history.count_singular" if count == 1 else "history.count_plural"
        self.lbl_count.setText(tr(key, count=count))
        if query:
            self.lbl_empty_title.setText(tr("history.no_matches_title"))
            self.lbl_empty_sub.setText(tr("history.no_matches_body"))
        else:
            self.lbl_empty_title.setText(tr("history.empty_title"))
            self.lbl_empty_sub.setText(tr("history.empty_body"))

    def _on_delete_entry_clicked(self, entry_id: str) -> None:
        if self.store.delete_entry(entry_id):
            self.refresh_entries()

    def _on_clear_all_clicked(self) -> None:
        if self._total_count == 0:
            return
        reply = QMessageBox.question(
            self,
            tr("history.clear_title"),
            tr("history.clear_body"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.store.clear()
            self.refresh_entries()

    def retranslate_ui(self) -> None:
        """Update visible labels for the active language."""
        self.btn_back.setText(tr("settings_page.back"))
        self.page_title.setText(tr("history.title"))
        self.btn_clear_all.setText(tr("history.clear_all"))
        self.txt_search.setPlaceholderText(tr("history.search_placeholder"))
        self.refresh_entries()

    def apply_theme(self) -> None:
        """Apply active ThemePalette across navigation bar, search, cards, and rows."""
        p = get_palette()
        self.nav_bar.setStyleSheet(f"""
            #history_nav_bar {{
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
        self.lbl_count.setStyleSheet(f"color: {p.text_muted};")
        self.entries_card.setStyleSheet(f"""
            #history_entries_card {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.empty_card.setStyleSheet(f"""
            #history_empty_card {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_empty_title.setStyleSheet(f"color: {p.text_main}; font-size: 14px; font-weight: 500;")
        self.lbl_empty_sub.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")

        for divider in self._dividers:
            divider.setStyleSheet(f"background-color: {p.border}; border: none;")
        for row_widget in self._row_widgets:
            row_widget.apply_theme()
