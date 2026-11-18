"""Only one Alter Ego at a time.

Two copies would fight over the microphone, the push-to-talk key, Ollama and the
memory file. The first copy holds a lock file in the data folder; a second copy
that cannot take it asks the first to show itself, then quits:

    second copy --"show"--> local socket of the first copy --> character and chat appear

The lock (QLockFile) decides, because it is safe when two copies start at the same
moment and after a crash (a lock whose process is gone is taken over). The local
socket only carries the "show" message. Each data folder has its own lock, so a
scratch copy run with ALTER_EGO_DATA_DIR does not block the real one.

Alter Ego's helper processes (--tool-server, --voice-server, --check-voice) never
get here: main.py starts them before the app.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

LOCK_FILE = "alter_ego.lock"
NAME_ENV = "ALTER_EGO_INSTANCE_NAME"  # Tests use their own name, never the real one.
CONNECT_TIMEOUT_MS = 1000
SHOW = b"show\n"


def instance_name(folder: Path) -> str:
    """A name for the local socket, the same for every copy using this data folder."""
    override = os.environ.get(NAME_ENV)
    if override:
        return override
    digest = hashlib.sha1(str(folder.resolve()).lower().encode("utf-8")).hexdigest()[:12]
    return f"AlterEgo-{digest}"


class SingleInstance(QObject):
    show_requested = Signal()  # Another copy was started: the running one should come forward.

    def __init__(self, folder: Path, parent: QObject | None = None):
        super().__init__(parent)
        folder.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(folder / LOCK_FILE))
        self._lock.setStaleLockTime(0)  # Never stale by age, only when the process holding it is gone.
        self._name = instance_name(folder)
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """True when this is the only copy: it now holds the lock and listens for "show"."""
        if not self._lock.tryLock(0):
            return False
        server = QLocalServer(self)
        if not server.listen(self._name):
            QLocalServer.removeServer(self._name)  # Left over from a crash (Linux keeps the socket file).
            server.listen(self._name)
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def ask_running_copy_to_show(self) -> bool:
        """Tell the copy that holds the lock to show itself. False if it does not answer."""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
            return False
        socket.write(SHOW)
        socket.flush()
        socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()

    def _on_connection(self) -> None:
        server = self._server
        while server is not None and server.hasPendingConnections():
            socket = server.nextPendingConnection()
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            # The other copy disconnects right after writing: read what came first, then let go.
            socket.disconnected.connect(lambda socket=socket: (self._read(socket), socket.deleteLater()))
            if socket.bytesAvailable():
                self._read(socket)

    def _read(self, socket: QLocalSocket) -> None:
        if SHOW.strip() in bytes(socket.readAll()):
            self.show_requested.emit()
