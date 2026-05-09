from __future__ import annotations

import base64
import io
import logging
from typing import Sequence

from mss import mss
from PIL import Image
from PyQt6.QtCore import QThread, pyqtSignal

from config_loader import AppConfig
from conversation_history import ChatTurn
from llm_client import generate_chat_reply
from logging_utils import LOGGER_NAME


class ChatWorker(QThread):
    response_ready = pyqtSignal(str, str, str)
    request_failed = pyqtSignal(str)

    def __init__(
        self,
        config: AppConfig,
        user_text: str,
        history_turns: Sequence[ChatTurn] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._user_text = user_text
        self._history_turns = tuple(history_turns or ())

    def run(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        try:
            screenshot_base64 = None
            if self._config.observer.global_observation_enabled:
                screenshot_base64 = self._capture_screen()
            reply = generate_chat_reply(
                self._config,
                self._user_text,
                screenshot_base64,
                self._history_turns,
            )
        except Exception:
            logger.warning("主动聊天请求失败，已回退到 IDLE。", exc_info=True)
            self.request_failed.emit("这次信号有点乱，稍后再试吧。")
            return

        self.response_ready.emit(self._user_text, reply.message, reply.emotion.value)

    def _capture_screen(self) -> str | None:
        logger = logging.getLogger(LOGGER_NAME)
        try:
            with mss() as screen_capture:
                screenshot = screen_capture.grab(screen_capture.monitors[1])
        except Exception:
            logger.warning("主动聊天截图失败，已改为纯文本发送。", exc_info=True)
            return None

        image = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        image.thumbnail((1600, 900), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
