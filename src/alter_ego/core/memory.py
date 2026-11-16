"""Persistent memory: conversations are saved in a SQLite database.

Before v0.4.0 everything Alter Ego heard was gone when the app quit. Now a
MemoryStore listens to a Conversation and writes every message to
data/memory.db (standard library sqlite3, no extra dependencies). On the
next start the latest conversation is loaded back, so the chat continues
where it left off and the AI gets the recent history as context.

Model:

- A *conversation* is everything between two uses of "clear". Clearing the
  chat ends the current conversation and the next message starts a new one.
  Old conversations stay in the database (nothing is shown from them yet;
  a later version can use them for long-term recall).
- Only the newest conversation that was not cleared is restored at start.
- "Forget everything" deletes all rows.

The store only ever runs on the GUI thread: Qt delivers the Conversation
signals there, and sqlite3 connections must stay on one thread anyway.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject

from ..expressions import Expression
from .conversation import Conversation, Message, Role

MEMORY_FILENAME = "memory.db"
SCHEMA_VERSION = 1
# How many messages of the latest conversation are shown again after a restart.
RESTORE_LIMIT = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    text            TEXT NOT NULL,
    expression      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages(conversation_id, id);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MemoryStore(QObject):
    def __init__(self, path: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.commit()

        self._conversation: Conversation | None = None
        self._conversation_id: int | None = None  # Row of the conversation being recorded, once it has a message.
        self._row_ids: dict[int, int] = {}       # id(message) -> messages.id, for messages currently on screen.

    # ----- Lifecycle -----

    def restore(self, conversation: Conversation, limit: int = RESTORE_LIMIT) -> int:
        """Load the latest unfinished conversation into `conversation`. Returns how many messages were added.

        Call this before the chat window is connected, so the restored messages
        appear instantly instead of being typed out one by one.
        """
        row = self._db.execute(
            "SELECT id FROM conversations WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 0
        conversation_id = int(row[0])

        rows = self._db.execute(
            "SELECT id, role, text, expression, created_at FROM messages "
            "WHERE conversation_id = ? AND text != '' ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        rows.reverse()  # Newest-first for the LIMIT, oldest-first for display.

        self._conversation_id = conversation_id
        for row_id, role, text, expression, created_at in rows:
            message = Message(
                _role_from_db(role),
                text,
                timestamp=_parse_time(created_at),
                expression=_expression_from_db(expression),
            )
            self._row_ids[id(message)] = int(row_id)
            conversation.add(message)
        return len(rows)

    def attach(self, conversation: Conversation) -> None:
        """Start recording `conversation`. Messages already in it are saved too. Safe to call twice."""
        if self._conversation is conversation:
            return
        self.detach()
        self._conversation = conversation
        conversation.message_added.connect(self._on_message_added)
        conversation.message_updated.connect(self._on_message_updated)
        conversation.cleared.connect(self._on_cleared)
        for message in conversation.messages:
            if id(message) not in self._row_ids:
                self._on_message_added(message)

    def detach(self) -> None:
        """Stop recording. What is already saved stays saved."""
        conversation = self._conversation
        if conversation is None:
            return
        conversation.message_added.disconnect(self._on_message_added)
        conversation.message_updated.disconnect(self._on_message_updated)
        conversation.cleared.disconnect(self._on_cleared)
        self._conversation = None

    def close(self) -> None:
        """Flush replies that were still streaming, then close the database."""
        if self._conversation is not None:
            for message in self._conversation.messages:
                if not message.complete:
                    self._write_message(message)
            self.detach()
        self._db.commit()
        self._db.close()

    # ----- Queries -----

    @property
    def recording(self) -> bool:
        return self._conversation is not None

    def stats(self) -> tuple[int, int]:
        """(number of conversations, number of messages) in the database."""
        conversations = self._db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        messages = self._db.execute("SELECT COUNT(*) FROM messages WHERE text != ''").fetchone()[0]
        return int(conversations), int(messages)

    def forget_all(self) -> None:
        """Delete every conversation. The messages currently on screen are forgotten too,
        so the caller normally clears the Conversation as well."""
        self._db.execute("DELETE FROM messages")
        self._db.execute("DELETE FROM conversations")
        self._db.commit()
        self._db.execute("VACUUM")
        self._conversation_id = None
        self._row_ids.clear()

    # ----- Conversation signals -----

    def _on_message_added(self, message: Message) -> None:
        if self._conversation_id is None:
            cursor = self._db.execute(
                "INSERT INTO conversations (started_at) VALUES (?)",
                (message.timestamp.isoformat(timespec="seconds"),),
            )
            self._conversation_id = int(cursor.lastrowid)
        cursor = self._db.execute(
            "INSERT INTO messages (conversation_id, role, text, expression, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                self._conversation_id,
                message.role.value,
                message.text,
                _expression_to_db(message.expression),
                message.timestamp.isoformat(timespec="seconds"),
            ),
        )
        self._row_ids[id(message)] = int(cursor.lastrowid)
        self._db.commit()

    def _on_message_updated(self, message: Message) -> None:
        # Streaming replies change many times a second; write once, when they finish.
        if message.complete:
            self._write_message(message)

    def _on_cleared(self) -> None:
        if self._conversation_id is not None:
            self._db.execute(
                "DELETE FROM conversations WHERE id = ? AND NOT EXISTS "
                "(SELECT 1 FROM messages WHERE conversation_id = ? AND text != '')",
                (self._conversation_id, self._conversation_id),
            )
            self._db.execute(
                "UPDATE conversations SET ended_at = ? WHERE id = ?", (_now(), self._conversation_id)
            )
            self._db.commit()
        self._conversation_id = None
        self._row_ids.clear()

    def _write_message(self, message: Message) -> None:
        row_id = self._row_ids.get(id(message))
        if row_id is None:
            return  # Not one of ours (for example a reply that outlived a clear).
        self._db.execute(
            "UPDATE messages SET text = ?, expression = ? WHERE id = ?",
            (message.text, _expression_to_db(message.expression), row_id),
        )
        self._db.commit()


# ----- Converting between Python values and database columns -----

def _role_from_db(value: str) -> Role:
    try:
        return Role(value)
    except ValueError:
        return Role.ASSISTANT


def _expression_to_db(expression: Expression | None) -> str | None:
    return None if expression is None else expression.name


def _expression_from_db(value: str | None) -> Expression | None:
    if not value:
        return None
    try:
        return Expression[value]
    except KeyError:
        return None


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now()
