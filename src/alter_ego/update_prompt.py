"""Asking the user about a new version, and showing the update while it downloads.

    check(manual) --worker--> newer release? --ask--> Update now ----> download (progress window)
                                                 ├─> Not now                 └─> start the hand-over, quit
                                                 └─> Skip this version (remembered in updates.skipped)

The check runs at start-up when updates.check is on (the default), and from
AI -> Check for updates now. Nothing is downloaded before the user says yes.
The work itself is in core/updates.py, on a worker thread; this module only asks
and draws.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from .core import updates
from .core.updates import Method, Release, Relaunch, UpdateJob
from .settings.config import Config

NOTES_PREVIEW_CHARS = 1200


class UpdatePrompt(QObject):
    def __init__(self, config: Config, quit_app: Callable[[], None],
                 parent_widget: Callable[[], QWidget | None] = lambda: None, parent: QObject | None = None):
        super().__init__(parent)
        self._config = config
        self._quit_app = quit_app
        self._parent_widget = parent_widget
        self._job: UpdateJob | None = None
        self._progress: QProgressDialog | None = None
        self._manual = False
        self._jobs: set[UpdateJob] = set()  # kept alive until each one has finished
        self.method: Method | None = updates.install_method()

    @property
    def busy(self) -> bool:
        return self._job is not None

    def check(self, manual: bool = False) -> None:
        """Look for a new release on a worker; `manual` also reports "no update" and offers skipped versions."""
        if self._job is not None:
            return
        self._manual = manual
        job = UpdateJob(lambda _progress, _cancelled: updates.check_latest())
        # Bound methods, not lambdas: a lambda would run on the worker thread, these are queued to the GUI thread.
        job.succeeded.connect(self._on_checked)
        job.failed.connect(self._on_check_failed)
        self._run(job)

    def wait(self, timeout_ms: int = 3000) -> None:
        """Used when quitting: stop a download and wait a little for the worker."""
        for job in list(self._jobs):
            job.requestInterruption()
            job.wait(timeout_ms)

    # ----- GUI thread -----

    def _run(self, job: UpdateJob) -> None:
        self._job = job
        self._jobs.add(job)
        job.finished.connect(self._on_job_finished)
        job.start(QThread.Priority.LowPriority)

    def _on_job_finished(self) -> None:
        job = self.sender()
        if isinstance(job, UpdateJob):
            self._jobs.discard(job)
            if self._job is job:
                self._job = None
            job.deleteLater()

    def _on_checked(self, release: Release | None) -> None:
        manual = self._manual
        self._job = None  # The check is over; "Update now" may start the download job.
        skipped = str(self._config.get("updates", "skipped", "") or "")
        if not updates.should_offer(release, skipped, manual):
            print(f"Alter Ego: no new version (this is v{updates.__version__}).")
            if manual:
                self._tell(f"I'm already the newest version, v{updates.__version__}. Yay!")
            return
        assert release is not None
        print(f"Alter Ego: version {release.version} is out.")
        self._ask(release)

    def _on_check_failed(self, reason: str) -> None:
        self._job = None
        print(f"Alter Ego: update check failed: {reason}")
        if self._manual:
            self._tell(reason, warning=True)

    def _ask(self, release: Release) -> None:
        asset = release.asset_for(self.method)
        box = QMessageBox(self._parent_widget())
        box.setWindowTitle("Alter Ego")
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if asset is not None:
            size = f"It's a {_size(asset.size)} download. " if asset.size else ""
            box.setText(
                f"Um... there's a new version of me, v{release.version}! Can I update myself now?\n\n"
                f"{size}I'll close for a moment and start again by myself when it's done. "
                "Your settings and our memories stay."
            )
            install = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setText(
                f"Um... there's a new version of me, v{release.version}! I can't install it myself here, "
                "but I can open the download page for you."
            )
            install = box.addButton("Open the download page", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        if release.notes:
            notes = release.notes
            if len(notes) > NOTES_PREVIEW_CHARS:
                notes = notes[:NOTES_PREVIEW_CHARS].rstrip() + "\n..."
            box.setDetailedText(notes)
        box.setDefaultButton(install)
        box.exec()

        clicked = box.clickedButton()
        if clicked is skip:
            self._config.set("updates", "skipped", release.version)
            self._config.save()
        elif clicked is install:
            if asset is None:
                QDesktopServices.openUrl(QUrl(release.page_url))
            else:
                self._install(release)

    def _install(self, release: Release) -> None:
        method = self.method
        assert method is not None
        dialog = QProgressDialog("Downloading the new version...", "Cancel", 0, 100, self._parent_widget())
        dialog.setWindowTitle("Alter Ego - Update")
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        self._progress = dialog

        job = UpdateJob(lambda progress, cancelled: updates.prepare(release, method, progress, cancelled))
        job.progress.connect(self._on_progress)
        job.succeeded.connect(self._on_ready)
        job.failed.connect(self._on_install_failed)
        dialog.canceled.connect(job.requestInterruption)
        self._run(job)
        dialog.show()

    def _on_progress(self, text: str, percent: int) -> None:
        dialog = self._progress
        if dialog is None:
            return
        dialog.setLabelText(text)
        if percent < 0:
            dialog.setRange(0, 0)  # Busy, without a percentage.
        else:
            dialog.setRange(0, 100)
            dialog.setValue(percent)

    def _close_progress(self) -> None:
        dialog, self._progress = self._progress, None
        if dialog is not None:
            dialog.canceled.disconnect()
            dialog.close()
            dialog.deleteLater()

    def _on_ready(self, relaunch: Relaunch) -> None:
        self._close_progress()
        try:
            relaunch.start()
        except updates.UpdateError as error:
            self._tell(str(error), warning=True)
            return
        print("Alter Ego: updating; see you in a moment.")
        self._quit_app()

    def _on_install_failed(self, reason: str) -> None:
        cancelled = self._progress is not None and self._progress.wasCanceled()
        self._close_progress()
        print(f"Alter Ego: update failed: {reason}")
        if not cancelled:
            self._tell(f"Sorry... {reason}", warning=True)

    def _tell(self, text: str, warning: bool = False) -> None:
        box = QMessageBox(self._parent_widget())
        box.setWindowTitle("Alter Ego")
        box.setIcon(QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setText(text)
        box.exec()


def _size(size: int) -> str:
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    return f"{max(1, round(size / 1_000_000))} MB"
