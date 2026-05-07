from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from config_loader import AppConfig
from llm_client import generate_chat_reply
from logging_utils import LOGGER_NAME


class ChatWorker(QThread):
    response_ready = pyqtSignal(str, str)
    request_failed = pyqtSignal(str)

    def __init__(self, config: AppConfig, user_text: str) -> None:
        super().__init__()
        self._config = config
        self._user_text = user_text

    def run(self) -> None:
        logger = logging.getLogger(LOGGER_NAME)
        try:
            reply = generate_chat_reply(self._config, self._user_text)
        except Exception:
            logger.warning("Chat request failed; falling back to IDLE.", exc_info=True)
            self.request_failed.emit("The uplink is noisy. Try again in a moment.")
            return

        self.response_ready.emit(reply.message, reply.emotion.value)
