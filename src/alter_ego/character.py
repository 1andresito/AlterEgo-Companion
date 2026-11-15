from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QActionGroup, QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from .expressions import Expression, ExpressionManager


# Size of the supplied artwork. Used as a fallback when no image could be loaded.
FALLBACK_SOURCE_SIZE = QSize(676, 391)

# The green "screen" inside the CRT frame, in source-image pixels.
# CRT effects are clipped to this area so they never touch the frame or glow.
SOURCE_SCREEN_RECT = QRect(26, 26, 623, 339)

# Window size presets, as a fraction of the source artwork size.
SIZE_PRESETS = {
    "Small": 0.45,
    "Medium": 0.6,
    "Large": 0.8,
    "Full size": 1.0,
}
DEFAULT_SIZE = "Medium"

# Crossfade duration when switching expressions.
TRANSITION_MS = 220

# A faint bright band sweeps down the screen now and then, like a CRT refresh.
SWEEP_INTERVAL_MS = 7000
SWEEP_DURATION_MS = 1600

# TV static when the character appears (static clears to reveal the face) and
# disappears (static takes over, then the window hides).
STATIC_APPEAR_MS = 700
STATIC_DISAPPEAR_MS = 450
NOISE_FRAME_MS = 33            # ~30 new noise frames per second
NOISE_SIZE = QSize(128, 72)    # Low-res noise, stretched pixelated over the screen

# Mouse movement (in pixels) below this counts as a click, not a drag.
CLICK_DRAG_THRESHOLD = 4


class CharacterWindow(QWidget):
    # The user clicked the character (without dragging) or chose "Chat..." from the menu.
    activated = Signal()
    # The window was moved, by dragging or by code.
    moved = Signal()

    def __init__(self, expressions: ExpressionManager):
        super().__init__()
        self.setWindowTitle("Alter Ego")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._expressions = expressions
        self._source_size = expressions.base_size() or FALLBACK_SOURCE_SIZE
        self._size_name = DEFAULT_SIZE
        self._scale = SIZE_PRESETS[DEFAULT_SIZE]
        self._drag_offset: QPoint | None = None
        self._press_position: QPoint | None = None
        self._dragging = False

        # Optional hook: app.py sets this to add menus the character itself
        # knows nothing about (the AI settings), keeping this file UI-only.
        self.extra_menu_builder: Callable[[QMenu], object] | None = None

        # Pre-scaled images, keyed by expression. Cleared whenever the size changes.
        self._scaled_cache: dict[Expression, QPixmap] = {}

        # Crossfade state: the old expression fades out while the new one fades in.
        self._previous: Expression | None = None
        self._fade = 1.0
        self._fade_animation = QVariantAnimation(self)
        self._fade_animation.setStartValue(0.0)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.setDuration(TRANSITION_MS)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_animation.valueChanged.connect(self._on_fade_step)
        self._fade_animation.finished.connect(self._on_fade_finished)
        expressions.expression_changed.connect(self._on_expression_changed)

        # Refresh sweep: a timer starts a short animation, so nothing repaints while idle.
        self._sweep_position: float | None = None
        self._sweep_animation = QVariantAnimation(self)
        self._sweep_animation.setStartValue(-0.2)
        self._sweep_animation.setEndValue(1.2)
        self._sweep_animation.setDuration(SWEEP_DURATION_MS)
        self._sweep_animation.valueChanged.connect(self._on_sweep_step)
        self._sweep_animation.finished.connect(self._on_sweep_finished)
        self._sweep_timer = QTimer(self)
        self._sweep_timer.timeout.connect(self._sweep_animation.start)
        self._sweep_timer.start(SWEEP_INTERVAL_MS)

        # TV static: _static_level is how much static covers the screen (0 = none, 1 = all).
        self._static_level = 0.0
        self._static_phase: str | None = None  # "appear", "disappear" or None
        self._noise = self._make_noise()
        self._noise_frame = 0
        self._static_animation = QVariantAnimation(self)
        self._static_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._static_animation.valueChanged.connect(self._on_static_step)
        self._static_animation.finished.connect(self._on_static_finished)
        self._noise_timer = QTimer(self)
        self._noise_timer.setInterval(NOISE_FRAME_MS)
        self._noise_timer.timeout.connect(self._next_noise_frame)

        self._apply_size()

    # ----- Appear / disappear -----

    def appear(self) -> None:
        """Show the window with a burst of static that clears to reveal the face."""
        if self.isVisible() and self._static_phase is None:
            self.raise_()
            return
        self._static_phase = "appear"
        self.show()
        self.raise_()
        self._run_static(start=1.0, end=0.0, duration_ms=STATIC_APPEAR_MS)

    def disappear(self) -> None:
        """Fill the screen with static, then hide the window."""
        if not self.isVisible() or self._static_phase == "disappear":
            return
        self._static_phase = "disappear"
        self._run_static(start=self._static_level, end=1.0, duration_ms=STATIC_DISAPPEAR_MS)

    def _run_static(self, start: float, end: float, duration_ms: int) -> None:
        self._static_animation.stop()
        self._static_animation.setStartValue(start)
        self._static_animation.setEndValue(end)
        self._static_animation.setDuration(duration_ms)
        self._static_animation.start()
        self._noise_timer.start()

    def _on_static_step(self, value: float) -> None:
        self._static_level = value
        self.update()

    def _on_static_finished(self) -> None:
        self._noise_timer.stop()
        phase, self._static_phase = self._static_phase, None
        self._static_level = 0.0
        if phase == "disappear":
            self.hide()
        self.update()

    def _next_noise_frame(self) -> None:
        self._noise = self._make_noise()
        self._noise_frame += 1
        self.update()

    @staticmethod
    def _make_noise() -> QImage:
        """A small image of random grey pixels. os.urandom is the fastest way to get many random bytes."""
        width, height = NOISE_SIZE.width(), NOISE_SIZE.height()
        data = os.urandom(width * height)
        # QImage does not copy the buffer, so .copy() keeps the pixels alive after `data` is gone.
        return QImage(data, width, height, width, QImage.Format.Format_Grayscale8).copy()

    # ----- Size -----

    def set_size_preset(self, name: str) -> None:
        if name not in SIZE_PRESETS:
            return
        self._size_name = name
        self._scale = SIZE_PRESETS[name]
        self._apply_size()

    def _apply_size(self) -> None:
        self._scaled_cache.clear()
        self.setFixedSize(
            round(self._source_size.width() * self._scale),
            round(self._source_size.height() * self._scale),
        )
        self.update()

    def _scaled_pixmap(self, expression: Expression) -> QPixmap:
        """Return the expression image scaled to the window, using a cache.

        Scaling once with SmoothTransformation looks much better than letting the
        painter stretch the image every frame: the thin CRT scanlines in the
        artwork would otherwise shimmer (moiré) at smaller sizes.
        """
        cached = self._scaled_cache.get(expression)
        if cached is not None:
            return cached

        source = self._expressions.pixmap(expression)
        if source.isNull():
            return source

        # On high-DPI screens (e.g. 150% scaling) render at physical resolution.
        ratio = self.devicePixelRatioF()
        scaled = source.scaled(
            self.size() * ratio,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self._scaled_cache[expression] = scaled
        return scaled

    # ----- Animations -----

    def _on_expression_changed(self, new: Expression, previous: Expression) -> None:
        self._previous = previous
        self._fade_animation.stop()
        self._fade_animation.start()

    def _on_fade_step(self, value: float) -> None:
        self._fade = value
        self.update()

    def _on_fade_finished(self) -> None:
        self._previous = None
        self._fade = 1.0
        self.update()

    def _on_sweep_step(self, value: float) -> None:
        self._sweep_position = value
        self.update()

    def _on_sweep_finished(self) -> None:
        self._sweep_position = None
        self.update()

    # ----- Painting -----

    def _screen_rect(self) -> QRectF:
        """The inner CRT screen, converted from source pixels to window pixels."""
        r = SOURCE_SCREEN_RECT
        s = self._scale
        return QRectF(r.x() * s, r.y() * s, r.width() * s, r.height() * s)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        current = self._scaled_pixmap(self._expressions.current)
        if current.isNull():
            self._paint_missing_placeholder(painter)
            painter.end()
            return

        if self._previous is not None and self._fade < 1.0:
            previous = self._scaled_pixmap(self._previous)
            if not previous.isNull():
                painter.drawPixmap(0, 0, previous)
            painter.setOpacity(self._fade)
        painter.drawPixmap(0, 0, current)
        painter.setOpacity(1.0)

        if self._sweep_position is not None:
            self._paint_sweep(painter)
        if self._static_level > 0.0:
            self._paint_static(painter)

        painter.end()

    def _paint_static(self, painter: QPainter) -> None:
        screen = self._screen_rect()
        level = min(max(self._static_level, 0.0), 1.0)

        painter.save()
        painter.setClipRect(screen)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)  # keep the pixels crunchy

        # Random grey noise, then tinted green by multiplying with the CRT colour.
        painter.setOpacity(level)
        painter.drawImage(screen, self._noise)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        painter.fillRect(screen, QColor(150, 255, 110))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        # A dark band rolling down the screen, like a badly tuned TV.
        band_height = screen.height() * 0.18
        offset = (self._noise_frame * screen.height() * 0.06) % (screen.height() + band_height)
        band = QRectF(screen.left(), screen.top() - band_height + offset, screen.width(), band_height)
        painter.setOpacity(level * 0.45)
        painter.fillRect(band, QColor(0, 10, 0))

        painter.restore()

    def _paint_sweep(self, painter: QPainter) -> None:
        screen = self._screen_rect()
        band_height = screen.height() * 0.22
        center_y = screen.top() + screen.height() * self._sweep_position

        gradient = QLinearGradient(0, center_y - band_height / 2, 0, center_y + band_height / 2)
        gradient.setColorAt(0.0, QColor(210, 255, 170, 0))
        gradient.setColorAt(0.5, QColor(210, 255, 170, 52))
        gradient.setColorAt(1.0, QColor(210, 255, 170, 0))

        painter.save()
        painter.setClipRect(screen)
        painter.fillRect(screen, gradient)
        painter.restore()

    def _paint_missing_placeholder(self, painter: QPainter) -> None:
        """Simple stand-in so the app still runs if an image is missing."""
        screen = self._screen_rect()
        painter.setPen(QPen(QColor("#b7ff9a"), 2))
        painter.setBrush(QColor("#2f6d12"))
        painter.drawRoundedRect(screen, 4, 4)

        painter.setPen(QColor("#e4ffd6"))
        painter.setFont(QFont("Consolas", 9))
        painter.drawText(
            screen,
            Qt.AlignmentFlag.AlignCenter,
            f"ALTER EGO\n\nmissing image:\n{self._expressions.current.filename}",
        )

    # ----- Mouse -----

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            global_position = event.globalPosition().toPoint()
            self._press_position = global_position
            self._drag_offset = global_position - self.frameGeometry().topLeft()
            self._dragging = False
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.show_context_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        global_position = event.globalPosition().toPoint()
        # Ignore tiny jitters, so a click with a slightly shaky hand stays a click.
        if not self._dragging:
            distance = (global_position - self._press_position).manhattanLength()
            if distance < CLICK_DRAG_THRESHOLD:
                return
            self._dragging = True
        self.move(global_position - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            was_click = self._drag_offset is not None and not self._dragging
            self._drag_offset = None
            self._press_position = None
            self._dragging = False
            event.accept()
            if was_click:
                self.activated.emit()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.moved.emit()

    # ----- Menus -----

    def show_context_menu(self, global_position: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("Chat...", self.activated.emit)
        menu.addSeparator()
        self._add_size_menu(menu)
        if self.extra_menu_builder is not None:
            self.extra_menu_builder(menu)
        menu.addSeparator()
        menu.addAction("Hide Alter Ego", self.disappear)
        menu.addAction("Quit", QApplication.quit)
        menu.exec(global_position)

    def _add_size_menu(self, parent: QMenu) -> None:
        size_menu = parent.addMenu("Size")
        group = QActionGroup(size_menu)
        for name in SIZE_PRESETS:
            action = size_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self._size_name)
            group.addAction(action)
            # name=name freezes the loop value; a plain lambda would see only the last name.
            action.triggered.connect(lambda checked=False, name=name: self.set_size_preset(name))
