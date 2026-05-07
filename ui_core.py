from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

from config_loader import AppConfig, load_config
from logging_utils import LOGGER_NAME, setup_logging
from pet_state import PetState


WINDOW_FLAGS = (
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.Tool
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.NoDropShadowWindowHint
)

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_DONOTROUND = 1
DWM_COLOR_NONE = 0xFFFFFFFE

SUPPORTED_FRAME_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg", ".bmp"}
FRAME_SUFFIX_PRIORITY = (".png", ".webp", ".jpg", ".jpeg", ".bmp")
RESIZE_MARGIN = 10
RESIZE_LEFT = 1
RESIZE_TOP = 2
RESIZE_RIGHT = 4
RESIZE_BOTTOM = 8
STATE_ANIMATION_FRAME_MS = {
    PetState.IDLE: 90,
    PetState.GREETING: 66,
    PetState.LISTENING: 74,
    PetState.REVIEWING: 72,
    PetState.DRAGGING: 52,
    PetState.RESIZING: 54,
    PetState.THINKING: 82,
    PetState.ANGRY: 58,
    PetState.HAPPY: 56,
    PetState.CODING: 62,
    PetState.SLEEPY: 105,
    PetState.CONFUSED: 78,
    PetState.SURPRISED: 58,
    PetState.PROUD: 88,
    PetState.BORED: 110,
}


def _remove_system_window_outline(widget: QWidget) -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes
        from ctypes import wintypes

        # Windows can draw a 1px DWM outline around transparent frameless windows.
        hwnd = wintypes.HWND(int(widget.winId()))
        dwm_set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute

        corner_preference = ctypes.c_int(DWMWCP_DONOTROUND)
        dwm_set_window_attribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner_preference),
            ctypes.sizeof(corner_preference),
        )

        border_color = ctypes.c_uint(DWM_COLOR_NONE)
        dwm_set_window_attribute(
            hwnd,
            DWMWA_BORDER_COLOR,
            ctypes.byref(border_color),
            ctypes.sizeof(border_color),
        )
    except (AttributeError, OSError, ValueError):
        logging.getLogger(LOGGER_NAME).debug(
            "Unable to disable the system window outline.",
            exc_info=True,
        )


class BubbleMessageWidget(QWidget):
    def __init__(self) -> None:
        super().__init__(None, WINDOW_FLAGS | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        _remove_system_window_outline(self)

        self._anchor_rect = QRect()
        self._tail_on_left = True
        self._padding_x = 16
        self._padding_y = 12
        self._tail_size = 16

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            "color: white; font-size: 13px; line-height: 1.3;"
        )
        self._label.setMaximumWidth(260)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def set_anchor_rect(self, anchor_rect: QRect) -> None:
        self._anchor_rect = QRect(anchor_rect)
        if self.isVisible():
            self._place_near_anchor()

    def show_message(self, text: str, duration_ms: int = 5000) -> None:
        message = text.strip()
        if not message:
            self.hide()
            return

        self._label.setText(message)
        self._label.adjustSize()

        width = self._label.sizeHint().width() + (self._padding_x * 2) + self._tail_size
        height = self._label.sizeHint().height() + (self._padding_y * 2)
        self.resize(width, height)

        self._apply_label_geometry()
        self._place_near_anchor()
        self.show()
        _remove_system_window_outline(self)
        self.raise_()
        self._hide_timer.start(max(500, duration_ms))

    def paintEvent(self, event: QEvent) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(26, 31, 38, 232))

        if self._tail_on_left:
            body_rect = QRectF(self._tail_size, 0, self.width() - self._tail_size, self.height() - 1)
            tail_base_x = float(self._tail_size)
            tail_tip_x = 2.0
        else:
            body_rect = QRectF(0, 0, self.width() - self._tail_size, self.height() - 1)
            tail_base_x = float(self.width() - self._tail_size)
            tail_tip_x = float(self.width() - 2)

        center_y = self.height() * 0.56
        path = QPainterPath()
        path.addRoundedRect(body_rect, 18, 18)
        path.moveTo(tail_base_x, center_y - 11)
        path.lineTo(tail_tip_x, center_y)
        path.lineTo(tail_base_x, center_y + 11)
        path.closeSubpath()

        painter.drawPath(path)

    def _apply_label_geometry(self) -> None:
        x = self._padding_x + (self._tail_size if self._tail_on_left else 0)
        self._label.setGeometry(
            x,
            self._padding_y,
            self.width() - self._tail_size - (self._padding_x * 2),
            self.height() - (self._padding_y * 2),
        )

    def _place_near_anchor(self) -> None:
        if self._anchor_rect.isNull():
            return

        screen = QApplication.screenAt(self._anchor_rect.center()) or QApplication.primaryScreen()
        screen_rect = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        target_x = self._anchor_rect.right() + 18
        target_y = self._anchor_rect.top() + 8
        self._tail_on_left = True

        if target_x + self.width() > screen_rect.right() - 8:
            target_x = self._anchor_rect.left() - self.width() - 18
            self._tail_on_left = False

        target_x = max(screen_rect.left() + 8, min(target_x, screen_rect.right() - self.width() - 8))
        target_y = max(screen_rect.top() + 8, min(target_y, screen_rect.bottom() - self.height() - 8))

        self._apply_label_geometry()
        self.move(target_x, target_y)
        self.update()


class ChatInputWidget(QWidget):
    submitted = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None, WINDOW_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        _remove_system_window_outline(self)
        self._anchor_rect = QRect()

        self._line_edit = QLineEdit(self)
        self._line_edit.setPlaceholderText("说点什么吧...")
        self._line_edit.returnPressed.connect(self._emit_submission)
        self._line_edit.installEventFilter(self)
        self._line_edit.setStyleSheet(
            """
            QLineEdit {
                background: rgba(17, 20, 24, 235);
                color: white;
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 14px;
                padding: 8px 12px;
                font-size: 13px;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._line_edit)
        self.resize(240, 44)

    def set_anchor_rect(self, anchor_rect: QRect) -> None:
        self._anchor_rect = QRect(anchor_rect)
        if self.isVisible():
            self._place_near_anchor()

    def show_input(self) -> None:
        self._line_edit.clear()
        self._place_near_anchor()
        self.show()
        _remove_system_window_outline(self)
        self.raise_()
        self.activateWindow()
        self._line_edit.setFocus()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._line_edit and event.type() == QEvent.Type.KeyPress:
            key_event = event
            if getattr(key_event, "key", lambda: None)() == Qt.Key.Key_Escape:
                self.hide()
                self.cancelled.emit()
                return True

        if watched is self._line_edit and event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self._cancel_if_unfocused)

        return super().eventFilter(watched, event)

    def _emit_submission(self) -> None:
        text = self._line_edit.text().strip()
        self.hide()
        if text:
            self.submitted.emit(text)

    def _cancel_if_unfocused(self) -> None:
        if self.isVisible() and not self._line_edit.hasFocus():
            self.hide()
            self.cancelled.emit()

    def _place_near_anchor(self) -> None:
        if self._anchor_rect.isNull():
            return

        screen = QApplication.screenAt(self._anchor_rect.center()) or QApplication.primaryScreen()
        screen_rect = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        target_x = self._anchor_rect.right() + 18
        target_y = self._anchor_rect.bottom() - self.height()
        if target_x + self.width() > screen_rect.right() - 8:
            target_x = self._anchor_rect.left() - self.width() - 18

        target_x = max(screen_rect.left() + 8, min(target_x, screen_rect.right() - self.width() - 8))
        target_y = max(screen_rect.top() + 8, min(target_y, screen_rect.bottom() - self.height() - 8))
        self.move(target_x, target_y)


class PetSpriteLabel(QLabel):
    drag_pressed = pyqtSignal(object)
    drag_moved = pyqtSignal(object)
    drag_released = pyqtSignal(object)
    resize_pressed = pyqtSignal(object)
    resize_moved = pyqtSignal(object)
    resize_released = pyqtSignal(object)
    wheel_scaled = pyqtSignal(int)
    double_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sprite_pixmap = QPixmap()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def set_sprite_pixmap(self, pixmap: QPixmap) -> None:
        self._sprite_pixmap = pixmap
        self.update()

    def paintEvent(self, event: QEvent) -> None:
        _ = event
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self._sprite_pixmap.isNull():
            target = QRect(
                (self.width() - self._sprite_pixmap.width()) // 2,
                (self.height() - self._sprite_pixmap.height()) // 2,
                self._sprite_pixmap.width(),
                self._sprite_pixmap.height(),
            )
            painter.drawPixmap(target, self._sprite_pixmap)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pressed.emit(event)
        elif event.button() == Qt.MouseButton.RightButton:
            self.resize_pressed.emit(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.drag_moved.emit(event)
        self.resize_moved.emit(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_released.emit(event)
        elif event.button() == Qt.MouseButton.RightButton:
            self.resize_released.emit(event)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.wheel_scaled.emit(event.angleDelta().y())
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class PetWindow(QWidget):
    chat_submitted = pyqtSignal(str)
    chat_opened = pyqtSignal()
    chat_cancelled = pyqtSignal()
    drag_started = pyqtSignal()
    drag_finished = pyqtSignal()
    resize_started = pyqtSignal()
    resize_finished = pyqtSignal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__(None, WINDOW_FLAGS)
        self._config = config
        self._drag_offset: QPoint | None = None
        self._resize_start_pos: QPoint | None = None
        self._resize_start_size = self._clamp_sprite_size(config.runtime.sprite_size)
        self._resize_start_geometry = QRect()
        self._resize_edges = 0
        self._sprite_size = self._resize_start_size
        self._positioned = False
        self._pixmap_cache: dict[PetState, QPixmap] = {}
        self._frame_cache: dict[PetState, list[QPixmap]] = {}
        self._animation_frames: list[QPixmap] = []
        self._animation_index = 0
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._advance_animation_frame)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")
        self.setWindowTitle("CodingPet")

        self._bubble = BubbleMessageWidget()
        self._chat_input = ChatInputWidget()

        self._sprite = PetSpriteLabel(self)
        self._sprite.setCursor(Qt.CursorShape.OpenHandCursor)
        self._sprite.setStyleSheet("background: transparent; border: none;")
        self._sprite.drag_pressed.connect(self._start_drag)
        self._sprite.drag_moved.connect(self._drag_move)
        self._sprite.drag_released.connect(self._end_drag)
        self._sprite.resize_pressed.connect(self._start_resize)
        self._sprite.resize_moved.connect(self._resize_move)
        self._sprite.resize_released.connect(self._end_resize)
        self._sprite.wheel_scaled.connect(self._wheel_resize)
        self._sprite.double_clicked.connect(self.show_chat_input)

        self._chat_input.submitted.connect(self.chat_submitted.emit)
        self._chat_input.cancelled.connect(self.chat_cancelled.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._sprite)

        self._config.assets_dir.mkdir(parents=True, exist_ok=True)
        self.set_state(PetState.IDLE)

    def set_state(self, state: PetState | str) -> None:
        normalized = state if isinstance(state, PetState) else PetState.from_emotion(state)
        self._animation_frames = self._load_state_frames(normalized)
        if not self._animation_frames:
            self._animation_frames = [self._build_placeholder_pixmap()]

        self._animation_index = 0
        self._apply_animation_frame()

        if len(self._animation_frames) > 1:
            self._animation_timer.start(STATE_ANIMATION_FRAME_MS.get(normalized, 120))
        else:
            self._animation_timer.stop()

    def show_message(self, text: str, duration_ms: int | None = None) -> None:
        self._bubble.set_anchor_rect(self.frameGeometry())
        self._bubble.show_message(text, duration_ms or self._config.runtime.message_duration_ms)

    def show_chat_input(self) -> None:
        self._chat_input.set_anchor_rect(self.frameGeometry())
        self._chat_input.show_input()
        self.chat_opened.emit()

    def moveEvent(self, event: QEvent) -> None:
        super().moveEvent(event)
        self._refresh_overlay_positions()

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        _remove_system_window_outline(self)
        if not self._positioned:
            self._move_to_default_position()
            self._positioned = True
        self._refresh_overlay_positions()

    def closeEvent(self, event: QEvent) -> None:
        self._animation_timer.stop()
        self._bubble.close()
        self._chat_input.close()
        super().closeEvent(event)

    def _refresh_overlay_positions(self) -> None:
        anchor = self.frameGeometry()
        self._bubble.set_anchor_rect(anchor)
        self._chat_input.set_anchor_rect(anchor)

    def _start_drag(self, event: QMouseEvent) -> None:
        resize_edges = self._resize_edges_at(event.position().toPoint())
        if resize_edges:
            self._begin_edge_resize(event, resize_edges)
            return

        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        self._sprite.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.drag_started.emit()

    def _drag_move(self, event: QMouseEvent) -> None:
        if self._resize_edges:
            self._edge_resize_move(event)
            return

        if self._drag_offset is None:
            self._update_hover_cursor(event.position().toPoint())
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _end_drag(self, event: QMouseEvent) -> None:
        _ = event
        had_dragging = self._drag_offset is not None
        self._drag_offset = None
        self._resize_edges = 0
        self._resize_start_pos = None
        self._sprite.setCursor(Qt.CursorShape.OpenHandCursor)
        if had_dragging:
            self.drag_finished.emit()

    def _start_resize(self, event: QMouseEvent) -> None:
        edges = self._resize_edges_at(event.position().toPoint()) or (RESIZE_RIGHT | RESIZE_BOTTOM)
        self._begin_edge_resize(event, edges)

    def _begin_edge_resize(self, event: QMouseEvent, edges: int) -> None:
        self._resize_start_pos = event.globalPosition().toPoint()
        self._resize_start_size = self._sprite_size
        self._resize_start_geometry = self.frameGeometry()
        self._resize_edges = edges
        self._sprite.setCursor(self._cursor_for_edges(edges))
        self.resize_started.emit()

    def _resize_move(self, event: QMouseEvent) -> None:
        if self._resize_edges:
            self._edge_resize_move(event)
            return
        if event.buttons() & Qt.MouseButton.RightButton:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            self._set_sprite_size(self._resize_start_size + max(delta.x(), -delta.y()))

    def _end_resize(self, event: QMouseEvent) -> None:
        _ = event
        had_resize = self._resize_start_pos is not None or self._resize_edges != 0
        self._resize_start_pos = None
        self._resize_edges = 0
        self._sprite.setCursor(Qt.CursorShape.OpenHandCursor)
        if had_resize:
            self.resize_finished.emit()

    def _edge_resize_move(self, event: QMouseEvent) -> None:
        if self._resize_start_pos is None or not (
            event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        ):
            return

        delta = event.globalPosition().toPoint() - self._resize_start_pos
        candidates: list[int] = []
        if self._resize_edges & RESIZE_RIGHT:
            candidates.append(self._resize_start_size + delta.x())
        if self._resize_edges & RESIZE_LEFT:
            candidates.append(self._resize_start_size - delta.x())
        if self._resize_edges & RESIZE_BOTTOM:
            candidates.append(self._resize_start_size + delta.y())
        if self._resize_edges & RESIZE_TOP:
            candidates.append(self._resize_start_size - delta.y())

        if not candidates:
            return

        self._set_sprite_size(max(candidates))
        x = self.x()
        y = self.y()
        if self._resize_edges & RESIZE_LEFT:
            x = self._resize_start_geometry.right() - self.width() + 1
        if self._resize_edges & RESIZE_TOP:
            y = self._resize_start_geometry.bottom() - self.height() + 1
        self.move(x, y)

    def _wheel_resize(self, delta_y: int) -> None:
        step = 20 if delta_y > 0 else -20
        self._set_sprite_size(self._current_sprite_size() + step)

    def _current_sprite_size(self) -> int:
        return self._sprite_size

    def _set_sprite_size(self, size: int) -> None:
        self._sprite_size = self._clamp_sprite_size(size)
        self._apply_animation_frame()

    def _clamp_sprite_size(self, size: int) -> int:
        return max(
            self._config.runtime.sprite_min_size,
            min(self._config.runtime.sprite_max_size, size),
        )

    def _resize_edges_at(self, pos: QPoint) -> int:
        edges = 0
        if pos.x() <= RESIZE_MARGIN:
            edges |= RESIZE_LEFT
        elif pos.x() >= self.width() - RESIZE_MARGIN:
            edges |= RESIZE_RIGHT
        if pos.y() <= RESIZE_MARGIN:
            edges |= RESIZE_TOP
        elif pos.y() >= self.height() - RESIZE_MARGIN:
            edges |= RESIZE_BOTTOM
        return edges

    def _update_hover_cursor(self, pos: QPoint) -> None:
        self._sprite.setCursor(self._cursor_for_edges(self._resize_edges_at(pos)))

    def _cursor_for_edges(self, edges: int) -> Qt.CursorShape:
        if edges in (RESIZE_LEFT | RESIZE_TOP, RESIZE_RIGHT | RESIZE_BOTTOM):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (RESIZE_RIGHT | RESIZE_TOP, RESIZE_LEFT | RESIZE_BOTTOM):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & (RESIZE_LEFT | RESIZE_RIGHT):
            return Qt.CursorShape.SizeHorCursor
        if edges & (RESIZE_TOP | RESIZE_BOTTOM):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.OpenHandCursor

    def _move_to_default_position(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.move(100, 100)
            return

        available = screen.availableGeometry()
        self.move(
            available.right() - self.width() - 48,
            available.bottom() - self.height() - 64,
        )

    def _load_state_pixmap(self, state: PetState) -> QPixmap:
        if state in self._pixmap_cache:
            return self._pixmap_cache[state]

        logger = logging.getLogger(LOGGER_NAME)
        path = self._find_state_asset_path(state)
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._pixmap_cache[state] = pixmap
            return pixmap

        logger.warning("Failed to load asset for state '%s': %s", state.value, path)
        if state is not PetState.IDLE:
            return self._load_state_pixmap(PetState.IDLE)

        placeholder = self._build_placeholder_pixmap()
        self._pixmap_cache[state] = placeholder
        return placeholder

    def _find_state_asset_path(self, state: PetState) -> Path:
        base_name = self._config.assets_dir / state.value
        for suffix in FRAME_SUFFIX_PRIORITY:
            candidate = base_name.with_suffix(suffix)
            if candidate.exists():
                return candidate
        return self._config.assets_dir / state.asset_filename

    def _load_state_frames(self, state: PetState) -> list[QPixmap]:
        if state in self._frame_cache:
            return self._frame_cache[state]

        frame_dir = self._config.assets_dir / state.value
        if frame_dir.is_dir():
            frames = self._load_frames_from_directory(frame_dir)
            if frames:
                self._frame_cache[state] = frames
                return frames

        pixmap = self._load_state_pixmap(state)
        if not pixmap.isNull():
            frames = [pixmap]
            self._frame_cache[state] = frames
            return frames

        if state is not PetState.IDLE:
            return self._load_state_frames(PetState.IDLE)
        return []

    def _load_frames_from_directory(self, frame_dir: Path) -> list[QPixmap]:
        logger = logging.getLogger(LOGGER_NAME)
        frames: list[QPixmap] = []
        paths = self._frame_paths_for_directory(frame_dir)
        for path in paths:

            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                logger.warning("Failed to load animation frame: %s", path)
                continue
            frames.append(pixmap)
        if frames:
            logger.info("Loaded %d animation frames from %s", len(frames), frame_dir)
        return frames

    def _frame_paths_for_directory(self, frame_dir: Path) -> list[Path]:
        for suffix in FRAME_SUFFIX_PRIORITY:
            paths = sorted(frame_dir.glob(f"frame_*{suffix}"))
            if paths:
                return paths
        return [
            path for path in sorted(frame_dir.iterdir())
            if path.suffix.lower() in SUPPORTED_FRAME_SUFFIXES and path.is_file()
        ]

    def _scale_sprite_frame(self, pixmap: QPixmap) -> QPixmap:
        return pixmap.scaled(
            self._sprite_size,
            self._sprite_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _apply_animation_frame(self) -> None:
        if not self._animation_frames:
            return

        source_frame = self._animation_frames[self._animation_index]
        frame = self._scale_sprite_frame(source_frame)
        self._sprite.set_sprite_pixmap(frame)
        self._sprite.setFixedSize(frame.size())
        self.setFixedSize(frame.size())
        self.update()
        self._refresh_overlay_positions()

    def _advance_animation_frame(self) -> None:
        if len(self._animation_frames) <= 1:
            return

        self._animation_index = (self._animation_index + 1) % len(self._animation_frames)
        self._apply_animation_frame()

    def _build_placeholder_pixmap(self) -> QPixmap:
        pixmap = QPixmap(240, 240)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(84, 194, 255, 220))
        painter.drawEllipse(34, 12, 172, 172)

        painter.setBrush(QColor(255, 255, 255, 250))
        painter.drawRoundedRect(72, 156, 96, 62, 28, 28)

        painter.setBrush(QColor(16, 23, 31, 240))
        painter.drawEllipse(88, 86, 16, 24)
        painter.drawEllipse(136, 86, 16, 24)
        painter.drawRoundedRect(94, 124, 52, 10, 5, 5)
        painter.end()

        return pixmap


def run_preview(config_path: str = "config.yaml") -> int:
    setup_logging()
    logger = logging.getLogger(LOGGER_NAME)
    config = load_config(config_path)

    app = QApplication(sys.argv)
    window = PetWindow(config)
    window.show()
    window.show_message("阶段 1 成功", 2500)
    logger.info("阶段 1 成功：透明宠物窗口已就绪。")
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_preview())
