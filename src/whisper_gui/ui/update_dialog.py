"""Update notification dialog and background Qt workers for Whisper GUI."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from whisper_gui import __version__
from whisper_gui.i18n import tr
from whisper_gui.platform_utils import is_bundled, reveal_file_in_os
from whisper_gui.ui.theme import build_stylesheet, fixed_mono_font, get_palette
from whisper_gui.updater import (
    ReleaseInfo,
    apply_update_and_relaunch,
    download_release_asset,
    extract_release_archive,
    fetch_latest_release,
    get_install_target,
    is_writable_target,
)


class UpdateCheckWorker(QThread):
    """Background worker that queries GitHub Releases without blocking startup."""

    update_available = Signal(object)
    no_update = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        release = fetch_latest_release(__version__)
        if self.isInterruptionRequested():
            return
        if release is not None:
            self.update_available.emit(release)
        else:
            self.no_update.emit()


class UpdateInstallWorker(QThread):
    """Background worker that downloads, extracts, and schedules update replacement."""

    progress = Signal(int, int)
    status_changed = Signal(str)
    relaunch_ready = Signal()
    permission_fallback = Signal(str)
    failed = Signal(str)

    def __init__(self, release: ReleaseInfo, parent=None) -> None:
        super().__init__(parent)
        self.release = release
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        if not self.release.download_url:
            self.failed.emit(tr("update.no_asset"))
            return

        stage_dir = Path(tempfile.mkdtemp(prefix="whisper_gui_update_"))
        archive_name = self.release.asset_name or "WhisperGUI-update.zip"
        archive_path = stage_dir / archive_name

        try:
            self.status_changed.emit(tr("update.downloading_file", name=archive_name))
            download_release_asset(
                self.release.download_url,
                archive_path,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                cancel_check=lambda: self._cancel_requested or self.isInterruptionRequested(),
            )

            self.status_changed.emit(tr("update.extracting"))
            extract_dir = stage_dir / "extracted"
            extracted_app = extract_release_archive(archive_path, extract_dir)
            archive_path.unlink(missing_ok=True)

            target = get_install_target()
            if target is None or not is_writable_target(target):
                self.permission_fallback.emit(str(extracted_app))
                return

            self.status_changed.emit(tr("update.installing"))
            apply_update_and_relaunch(extracted_app, target)
            self.relaunch_ready.emit()
        except InterruptedError:
            self.failed.emit("cancelled")
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Modal prompt displaying the new version, changelog, and update actions."""

    def __init__(self, release: ReleaseInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.release = release
        self._worker: UpdateInstallWorker | None = None
        self._can_self_update = is_bundled() and bool(release.download_url)

        self.setWindowTitle(tr("update.window_title"))
        self.setMinimumSize(500, 380)
        self.resize(540, 420)
        p = get_palette()
        self.setStyleSheet(
            build_stylesheet(p)
            + f"""
            QDialog {{
                background-color: {p.bg_window};
                color: {p.text_main};
            }}
        """
        )
        self._build_ui()

    def _build_ui(self) -> None:
        p = get_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel(tr("update.heading"))
        title.setStyleSheet(f"color: {p.text_main}; font-size: 14px; font-weight: 500;")
        header_row.addWidget(title)
        header_row.addStretch()

        version_badge = QLabel(f"v{__version__} → {self.release.tag_name}")
        version_badge.setFont(fixed_mono_font(12))
        version_badge.setStyleSheet(f"""
            QLabel {{
                background-color: {p.bg_surface};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: 500;
            }}
        """)
        header_row.addWidget(version_badge)
        layout.addLayout(header_row)

        changelog_label = QLabel(tr("update.changelog"))
        changelog_label.setStyleSheet(f"color: {p.text_muted}; font-weight: 500; font-size: 12px;")
        layout.addWidget(changelog_label)

        self.txt_changelog = QTextBrowser(self)
        self.txt_changelog.setOpenExternalLinks(True)
        self.txt_changelog.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {p.bg_input};
                color: {p.text_main};
                border: 1px solid {p.border};
                border-radius: 8px;
                padding: 12px;
                font-size: 12px;
            }}
        """)
        self.txt_changelog.setMarkdown(self.release.changelog or tr("update.no_changelog"))
        layout.addWidget(self.txt_changelog, stretch=1)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")
        self.lbl_status.hide()
        layout.addWidget(self.lbl_status)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_cancel = QPushButton(tr("update.cancel"), self)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.btn_cancel)

        action_label = tr("update.update_now") if self._can_self_update else tr("update.download_github")
        self.btn_update = QPushButton(action_label, self)
        self.btn_update.setDefault(True)
        self.btn_update.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.primary};
                color: {p.primary_text};
                border: 1px solid {p.primary};
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {p.primary_hover};
                border-color: {p.primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {p.primary_pressed};
            }}
            QPushButton:disabled {{
                background-color: {p.bg_surface};
                color: {p.text_hint};
                border-color: {p.border};
            }}
        """)
        self.btn_update.clicked.connect(self._on_update_clicked)
        btn_row.addWidget(self.btn_update)
        layout.addLayout(btn_row)

    def _on_update_clicked(self) -> None:
        if not self._can_self_update:
            QDesktopServices.openUrl(QUrl(self.release.html_url))
            self.accept()
            return

        self.btn_update.setEnabled(False)
        self.lbl_status.setText(tr("update.starting_download"))
        self.lbl_status.show()
        self.progress_bar.setRange(0, 0)  # Indeterminate until Content-Length arrives
        self.progress_bar.show()

        self._worker = UpdateInstallWorker(self.release, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.status_changed.connect(self.lbl_status.setText)
        self._worker.relaunch_ready.connect(self._on_relaunch_ready)
        self._worker.permission_fallback.connect(self._on_permission_fallback)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_cancel_clicked(self) -> None:
        if self._worker and self._worker.isRunning():
            self.lbl_status.setText(tr("update.cancelling_download"))
            self.btn_cancel.setEnabled(False)
            self._worker.request_cancel()
            return
        self.reject()

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)
            pct = min(100, int((downloaded * 100) / total))
            self.progress_bar.setValue(pct)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.lbl_status.setText(tr("update.downloading_pct", done=mb_done, total=mb_total, pct=pct))
        else:
            mb_done = downloaded / (1024 * 1024)
            self.lbl_status.setText(tr("update.downloading_mb", done=mb_done))

    def _on_relaunch_ready(self) -> None:
        self._worker = None
        self.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_permission_fallback(self, extracted_path: str) -> None:
        self._worker = None
        self.progress_bar.hide()
        self.lbl_status.setText(tr("update.admin_required"))
        reveal_file_in_os(extracted_path)
        QMessageBox.information(
            self,
            tr("update.manual_title"),
            tr("update.manual_body", path=extracted_path),
        )
        self.accept()

    def _on_failed(self, error_msg: str) -> None:
        self._worker = None
        self.progress_bar.hide()
        self.btn_update.setEnabled(True)
        self.btn_cancel.setEnabled(True)

        if error_msg == "cancelled":
            self.lbl_status.setText(tr("update.cancelled"))
            return

        self.lbl_status.setText(tr("update.failed_status", error=error_msg))
        QMessageBox.warning(self, tr("update.failed_title"), tr("update.failed_body", error=error_msg))

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.request_cancel()
            self._worker.wait(2000)
        super().closeEvent(event)
