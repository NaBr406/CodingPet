from __future__ import annotations

import base64
import io
import logging

import pygetwindow as gw
from mss import mss
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

from config_loader import AppConfig
from llm_client import analyze_screenshot
from logging_utils import LOGGER_NAME


class ObserverWorker(QThread):
    observation_started = pyqtSignal()
    observation_failed = pyqtSignal()
    observation_ready = pyqtSignal(str, str, str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._running = True
        self._interval_ms = config.observer.interval_seconds * 1000

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        logger.info("阶段 3 成功：观察线程已就绪。")

        while self._running:
            try:
                self._observe_once()
            except Exception:
                logger.warning("观察循环失败，已回退到 IDLE。", exc_info=True)
                self.observation_failed.emit()
            self._sleep_interruptibly(self._interval_ms)

    def _observe_once(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        active_window = gw.getActiveWindow()
        title = ""
        if active_window is not None:
            title = str(getattr(active_window, "title", "") or "")
        if not title:
            title = str(gw.getActiveWindowTitle() or "")

        if not title:
            title = "未识别前台窗口"

        self.observation_started.emit()
        logger.info("观察线程准备截图并请求视觉模型：%s", title)
        screenshot_base64 = self._capture_active_region(active_window)
        reply = analyze_screenshot(self._config, screenshot_base64, title)
        logger.info("观察线程已为窗口生成主动评论：%s", title)
        self.observation_ready.emit(title, reply.message, reply.emotion.value)

    def _capture_active_region(self, active_window: object | None) -> str:
        with mss() as screen_capture:
            region = self._resolve_region(screen_capture, active_window)
            screenshot = screen_capture.grab(region)

        image = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        image.thumbnail((1600, 900), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _resolve_region(self, screen_capture: mss, active_window: object | None) -> dict[str, int]:
        left = int(getattr(active_window, "left", 0) or 0)
        top = int(getattr(active_window, "top", 0) or 0)
        width = int(getattr(active_window, "width", 0) or 0)
        height = int(getattr(active_window, "height", 0) or 0)

        if width > 0 and height > 0:
            return {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }

        return dict(screen_capture.monitors[1])

    def _sleep_interruptibly(self, total_ms: int) -> None:
        remaining = total_ms
        while self._running and remaining > 0:
            chunk = min(500, remaining)
            self.msleep(chunk)
            remaining -= chunk
