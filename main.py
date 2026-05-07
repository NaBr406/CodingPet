from __future__ import annotations

import logging
import random
import sys

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication

from chat_thread import ChatWorker
from config_loader import ConfigError, AppConfig, load_config
from logging_utils import LOGGER_NAME, setup_logging
from observer_thread import ObserverWorker
from pet_state import RANDOM_MOOD_STATES, PetState
from ui_core import PetWindow


class CodingPetController(QObject):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._logger = logging.getLogger(LOGGER_NAME)
        self._chat_worker: ChatWorker | None = None
        self._observer_worker: ObserverWorker | None = None
        self._interaction_busy = False
        self._manual_override_active = False

        self.window = PetWindow(config)
        self.window.chat_submitted.connect(self._start_chat)
        self.window.chat_opened.connect(self._handle_chat_opened)
        self.window.chat_cancelled.connect(self._handle_chat_cancelled)
        self.window.drag_started.connect(self._handle_drag_started)
        self.window.drag_finished.connect(self._handle_drag_finished)
        self.window.resize_started.connect(self._handle_resize_started)
        self.window.resize_finished.connect(self._handle_resize_finished)

        self._state_reset_timer = QTimer(self)
        self._state_reset_timer.setSingleShot(True)
        self._state_reset_timer.timeout.connect(self._finish_interaction_state)

        self._random_mood_timer = QTimer(self)
        self._random_mood_timer.setSingleShot(True)
        self._random_mood_timer.timeout.connect(self._switch_random_mood)

    def start(self) -> None:
        self.window.show()
        self.window.set_state(PetState.GREETING)
        self.window.show_message("双击我对话", 2800)

        self._logger.info("阶段 1 成功：透明宠物窗口已就绪。")
        self._logger.info("阶段 2 成功：交互聊天链路已接好。")

        if self._config.observer.enabled:
            self._observer_worker = ObserverWorker(self._config)
            self._observer_worker.observation_started.connect(self._handle_observation_started)
            self._observer_worker.observation_failed.connect(self._handle_observation_finished_without_reply)
            self._observer_worker.observation_ready.connect(self._handle_model_reply)
            self._observer_worker.start()
            self._logger.info("阶段 3 成功：观察线程已启动。")
        else:
            self._logger.info("阶段 3 已关闭：配置里禁用了观察线程。")

        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()
            self._logger.info("随机心情切换已启用。")

    def shutdown(self) -> None:
        if self._observer_worker is not None:
            self._observer_worker.stop()
            self._observer_worker.wait(1500)

        if self._chat_worker is not None and self._chat_worker.isRunning():
            self._chat_worker.wait(1500)

        self._random_mood_timer.stop()

    def _start_chat(self, text: str) -> None:
        if self._chat_worker is not None and self._chat_worker.isRunning():
            self.window.show_message("一次只处理一个请求，别把我当竞态条件。")
            return

        self.window.set_state(PetState.THINKING)
        self.window.show_message("我想一下...", 1600)
        self._interaction_busy = True
        self._manual_override_active = False
        self._random_mood_timer.stop()

        worker = ChatWorker(self._config, text)
        worker.response_ready.connect(self._handle_model_reply)
        worker.request_failed.connect(self._handle_interaction_failed)
        worker.finished.connect(self._clear_chat_worker)
        self._chat_worker = worker
        worker.start()

    def _clear_chat_worker(self) -> None:
        if self._chat_worker is not None:
            self._chat_worker.deleteLater()
            self._chat_worker = None

    def _handle_model_reply(self, message: str, emotion: str) -> None:
        state = PetState.from_emotion(emotion)
        self._interaction_busy = True
        self._manual_override_active = False
        self._random_mood_timer.stop()
        self.window.set_state(state)
        self.window.show_message(message)
        self._state_reset_timer.start(self._config.runtime.state_reset_ms)

    def _handle_observation_started(self) -> None:
        if self._interaction_busy or self._manual_override_active:
            return
        self._random_mood_timer.stop()
        self.window.set_state(PetState.REVIEWING)

    def _handle_observation_finished_without_reply(self) -> None:
        if self._interaction_busy or self._manual_override_active:
            return
        self.window.set_state(PetState.IDLE)
        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()

    def _handle_interaction_failed(self, message: str) -> None:
        self.window.set_state(PetState.IDLE)
        self.window.show_message(message)
        self._finish_interaction_state()

    def _finish_interaction_state(self) -> None:
        self._interaction_busy = False
        self._manual_override_active = False
        self.window.set_state(PetState.IDLE)
        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()

    def _switch_random_mood(self) -> None:
        if (
            self._interaction_busy
            or self._manual_override_active
            or (self._chat_worker is not None and self._chat_worker.isRunning())
        ):
            self._schedule_random_mood()
            return

        self.window.set_state(random.choice(RANDOM_MOOD_STATES))
        self._schedule_random_mood()

    def _schedule_random_mood(self) -> None:
        min_ms = self._config.runtime.random_mood_min_seconds * 1000
        max_ms = self._config.runtime.random_mood_max_seconds * 1000
        self._random_mood_timer.start(random.randint(min_ms, max_ms))

    def _handle_chat_opened(self) -> None:
        if self._interaction_busy:
            return
        self._manual_override_active = True
        self._random_mood_timer.stop()
        self.window.set_state(PetState.LISTENING)

    def _handle_chat_cancelled(self) -> None:
        self._clear_manual_override()

    def _handle_drag_started(self) -> None:
        if self._interaction_busy:
            return
        self._manual_override_active = True
        self._random_mood_timer.stop()
        self.window.set_state(PetState.DRAGGING)

    def _handle_drag_finished(self) -> None:
        self._clear_manual_override()

    def _handle_resize_started(self) -> None:
        if self._interaction_busy:
            return
        self._manual_override_active = True
        self._random_mood_timer.stop()
        self.window.set_state(PetState.RESIZING)

    def _handle_resize_finished(self) -> None:
        self._clear_manual_override()

    def _clear_manual_override(self) -> None:
        if self._interaction_busy:
            return
        self._manual_override_active = False
        self.window.set_state(PetState.IDLE)
        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()


def main() -> int:
    setup_logging()
    logger = logging.getLogger(LOGGER_NAME)

    try:
        config = load_config()
    except ConfigError:
        logger.exception("加载 config.yaml 失败。")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("CodingPet")

    controller = CodingPetController(config)
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
