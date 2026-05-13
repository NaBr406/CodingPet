from __future__ import annotations

import base64
import io
import logging
from threading import Event

import pygetwindow as gw
from mss import mss
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

from config_loader import AppConfig
from llm_client import analyze_screenshot
from logging_utils import LOGGER_NAME


class ObserverWorker(QThread):
    # 后台观察线程：定时截取前台窗口并请求视觉模型生成主动评论。
    observation_started = pyqtSignal(object)
    observation_failed = pyqtSignal(object)
    observation_ready = pyqtSignal(object, str, str, str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._stop_requested = Event()
        self._observation_allowed = Event()
        self._observation_allowed.set()
        self._interval_ms = config.observer.interval_seconds * 1000

    def stop(self) -> None:
        # 通过标志位协作退出，而不是强杀线程，避免截图请求卡在半路时留下脏状态。
        self._stop_requested.set()
        self._observation_allowed.clear()

    def set_observation_allowed(self, allowed: bool) -> None:
        # 这个开关由主线程维护，worker 只读它，避免忙碌时还去截图和调模型。
        if allowed and not self._stop_requested.is_set():
            self._observation_allowed.set()
        else:
            self._observation_allowed.clear()

    def is_stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def run(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        logger.info("阶段 3 成功：观察线程已就绪。")

        with mss() as screen_capture:
            while not self._stop_requested.is_set():
                if not self._observation_allowed.is_set():
                    logger.info("观察线程跳过本轮：当前用户交互或请求正忙。")
                    self._sleep_interruptibly(self._interval_ms)
                    continue

                try:
                    # 每轮先观测一次，再进入等待；这样启动后不会白白空转一个间隔。
                    self._observe_once(screen_capture)
                except Exception:
                    logger.warning("观察循环失败，已回退到 IDLE。", exc_info=True)
                    self.observation_failed.emit(self)
                self._sleep_interruptibly(self._interval_ms)

    def _observe_once(self, screen_capture: mss) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        active_window = gw.getActiveWindow()
        title = ""
        if active_window is not None:
            title = str(getattr(active_window, "title", "") or "")
        if not title:
            title = str(gw.getActiveWindowTitle() or "")

        if not title:
            title = "未识别前台窗口"

        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        # 先告诉主界面“现在要观察了”，这样 UI 可以切到 REVIEWING 态。
        self.observation_started.emit(self)
        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        logger.info("观察线程准备截图并请求视觉模型：%s", title)
        screenshot_base64 = self._capture_active_region(screen_capture, active_window)
        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        reply = analyze_screenshot(self._config, screenshot_base64, title)
        if self._stop_requested.is_set() or not self._observation_allowed.is_set():
            return

        logger.info("观察线程已为窗口生成主动评论：%s", title)
        self.observation_ready.emit(self, title, reply.message, reply.emotion.value)

    def _capture_active_region(self, screen_capture: mss, active_window: object | None) -> str:
        # 优先只截前台窗口区域；如果取不到窗口几何，再退回整屏。
        region = self._resolve_region(screen_capture, active_window)
        screenshot = screen_capture.grab(region)

        # 一样先压缩尺寸再编码，减少模型请求和本地内存压力。
        image = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        image.thumbnail((1600, 900), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _resolve_region(self, screen_capture: mss, active_window: object | None) -> dict[str, int]:
        # 某些窗口句柄拿不到坐标或大小时，直接回退为整屏，保证观察链路不断。
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
        # 分块睡眠，便于 stop() 尽快生效，而不是一口气睡满整个间隔。
        remaining = total_ms
        while not self._stop_requested.is_set() and remaining > 0:
            chunk = min(500, remaining)
            self.msleep(chunk)
            remaining -= chunk
