"""Adding or removing the GPU pack from the Spoken replies menu (core/gpu_pack.py does the work).

    "Use my NVIDIA GPU..." -> look up the size -> ask (Download / Not now) -> download with a
    progress window (can be cancelled) -> "Done!" -> the voice restarts on the GPU

Every step runs on a worker (core/updates.UpdateJob), so the window never freezes.
Questions use the same on-top boxes as the file questions, so they never hide
behind the character.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QThread
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from .core import gpu_pack
from .core.updates import UpdateError, UpdateJob
from .tool_approval import on_top_box, show_on_top


class GpuPackPrompt(QObject):
    def __init__(self, on_change: Callable[[], None], parent: QObject | None = None):
        """`on_change` runs after the pack was added or removed: the app restarts the voice."""
        super().__init__(parent)
        self._on_change = on_change
        self._jobs: set[UpdateJob] = set()
        self._dialog: QProgressDialog | None = None

    @property
    def busy(self) -> bool:
        return bool(self._jobs)

    def offer(self) -> None:
        """Look up the download size, then ask."""
        if self.busy:
            return
        self._show_progress("Checking the GPU pack...", cancel=False)
        job = UpdateJob(lambda progress, cancelled: _work(gpu_pack.find_wheels))
        job.succeeded.connect(self._ask)
        job.failed.connect(self._failed)
        self._run(job)

    def remove(self) -> None:
        box = on_top_box("Stop using the GPU pack? My voice will run on the processor again, a bit slower, "
                         "and the pack's files are deleted.")
        stop = box.addButton("Stop using it", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Keep it", QMessageBox.ButtonRole.RejectRole)
        show_on_top(box)
        if box.clickedButton() is stop:
            gpu_pack.remove()
            self._on_change()

    # ----- Steps -----

    def _ask(self, wheels: list) -> None:
        self._close_progress()
        size = sum(wheel.size for wheel in wheels)
        shown = f"about {size / 1024 ** 3:.1f} GB" if size else "a few GB"
        box = on_top_box(
            "Um... I can use your NVIDIA graphics card for my voice. It makes me speak about 3 times faster.\n\n"
            f"It's a one-time download of {shown} from pytorch.org. It doesn't change how much memory I use.")
        download = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        show_on_top(box)
        if box.clickedButton() is not download:
            return
        self._show_progress("Downloading the GPU pack...", cancel=True)
        job = UpdateJob(lambda progress, cancelled: _work(lambda: gpu_pack.install(wheels, progress, cancelled)))
        job.progress.connect(self._on_progress)
        job.succeeded.connect(self._installed)
        job.failed.connect(self._failed)
        if self._dialog is not None:
            self._dialog.canceled.connect(job.requestInterruption)
        self._run(job)

    def _installed(self, name: str) -> None:
        self._close_progress()
        self._on_change()
        self._tell(f"Done! My voice will use {name} from now on.")

    def _failed(self, reason: str) -> None:
        cancelled = self._dialog is not None and self._dialog.wasCanceled()
        self._close_progress()
        print(f"Alter Ego: GPU pack: {reason}")
        if not cancelled:
            self._tell(f"Sorry... {reason}", warning=True)

    # ----- Helpers -----

    def _run(self, job: UpdateJob) -> None:
        self._jobs.add(job)
        job.finished.connect(lambda job=job: (self._jobs.discard(job), job.deleteLater()))
        job.start(QThread.Priority.LowPriority)

    def wait(self) -> None:
        """Quitting: stop a download and wait for its worker."""
        for job in list(self._jobs):
            job.requestInterruption()
            job.wait(5000)

    def _show_progress(self, text: str, cancel: bool) -> None:
        dialog = QProgressDialog(text, "Cancel" if cancel else "", 0, 0)
        dialog.setWindowTitle("Alter Ego - GPU pack")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if not cancel:
            dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.show()
        self._dialog = dialog

    def _on_progress(self, text: str, percent: int) -> None:
        dialog = self._dialog
        if dialog is None:
            return
        dialog.setLabelText(text)
        if percent < 0:
            dialog.setRange(0, 0)
        else:
            dialog.setRange(0, 100)
            dialog.setValue(percent)

    def _close_progress(self) -> None:
        dialog, self._dialog = self._dialog, None
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()

    @staticmethod
    def _tell(text: str, warning: bool = False) -> None:
        box = on_top_box(text, QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Information)
        show_on_top(box)


def _work(action: Callable[[], object]) -> object:
    """Run a GPU-pack step on the worker; its errors come back as plain sentences."""
    try:
        return action()
    except gpu_pack.GpuPackError as error:
        raise UpdateError(str(error)) from None
