"""Character expressions: which images exist and which one is showing.

Each expression is a single, complete PNG (CRT frame included). This module
only knows about *what* to show; drawing it is the character window's job.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QPixmap


class Expression(Enum):
    # The value is the part of the filename after "AlterEgo_".
    HAPPY = "Happy"
    TALK = "Talk"
    PASSION_TALK = "PassionTalk"
    SHY_TALK = "ShyTalk"
    SIDE_TALK = "SideTalk"
    SAD = "Sad"
    SURPRISED_TALK = "SuprisedTalk"  # Spelling matches the supplied asset file.
    SWEAT_TALK = "SweatTalk"

    @property
    def filename(self) -> str:
        return f"AlterEgo_{self.value}.png"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    Expression.HAPPY: "Happy",
    Expression.TALK: "Talk",
    Expression.PASSION_TALK: "Passionate",
    Expression.SHY_TALK: "Shy",
    Expression.SIDE_TALK: "Side glance",
    Expression.SAD: "Sad",
    Expression.SURPRISED_TALK: "Surprised",
    Expression.SWEAT_TALK: "Nervous",
}


class ExpressionManager(QObject):
    """Loads every expression image and tracks the current expression.

    Must be created after QApplication exists, because QPixmap needs it.
    """

    # Emitted with (new_expression, previous_expression).
    expression_changed = Signal(object, object)

    def __init__(self, animations_dir: Path, default: Expression = Expression.HAPPY):
        super().__init__()
        self._pixmaps: dict[Expression, QPixmap] = {}
        self.missing: list[Path] = []

        for expression in Expression:
            path = animations_dir / expression.filename
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.missing.append(path)
            else:
                self._pixmaps[expression] = pixmap

        if self.missing:
            print("Warning: could not load these expression images:")
            for path in self.missing:
                print(f"  {path}")

        self._current = default

    @property
    def current(self) -> Expression:
        return self._current

    def pixmap(self, expression: Expression | None = None) -> QPixmap:
        """Return the image for an expression (current by default).

        Returns a null QPixmap if that image failed to load.
        """
        return self._pixmaps.get(expression or self._current, QPixmap())

    def base_size(self) -> QSize | None:
        """Pixel size of the loaded artwork, or None if nothing loaded."""
        for pixmap in self._pixmaps.values():
            return pixmap.size()
        return None

    def set_expression(self, expression: Expression) -> None:
        if expression == self._current:
            return
        previous = self._current
        self._current = expression
        self.expression_changed.emit(expression, previous)
