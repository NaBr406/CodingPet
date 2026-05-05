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

        self.window = PetWindow(config)
        self.window.chat_submitted.connect(self._start_chat)

        self._state_reset_timer = QTimer(self)
        self._state_reset_timer.setSingleShot(True)
        self._state_reset_timer.timeout.connect(self._finish_interaction_state)

        self._random_mood_timer = QTimer(self)
        self._random_mood_timer.setSingleShot(True)
        self._random_mood_timer.timeout.connect(self._switch_random_mood)

    def start(self) -> None:
        self.window.show()
        self.window.show_message("Double-click me when your code starts drifting.", 2800)

        self._logger.info("Phase 1 Success: transparent pet window ready.")
        self._logger.info("Phase 2 Success: interactive chat flow wired.")

        if self._config.observer.enabled:
            self._observer_worker = ObserverWorker(self._config)
            self._observer_worker.observation_ready.connect(self._handle_model_reply)
            self._observer_worker.start()
            self._logger.info("Phase 3 Success: observer monitoring started.")
        else:
            self._logger.info("Phase 3 Success: observer monitoring disabled by config.")

        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()
            self._logger.info("Random mood switching enabled.")

    def shutdown(self) -> None:
        if self._observer_worker is not None:
            self._observer_worker.stop()
            self._observer_worker.wait(1500)

        if self._chat_worker is not None and self._chat_worker.isRunning():
            self._chat_worker.wait(1500)

        self._random_mood_timer.stop()

    def _start_chat(self, text: str) -> None:
        if self._chat_worker is not None and self._chat_worker.isRunning():
            self.window.show_message("One thread at a time. I am not your race condition.")
            return

        self.window.set_state(PetState.THINKING)
        self.window.show_message("Thinking...", 1600)
        self._interaction_busy = True
        self._random_mood_timer.stop()

        worker = ChatWorker(self._config, text)
        worker.response_ready.connect(self._handle_model_reply)
        worker.transient_message.connect(self._handle_transient_message)
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
        self._random_mood_timer.stop()
        self.window.set_state(state)
        self.window.show_message(message)
        self._state_reset_timer.start(self._config.runtime.state_reset_ms)

    def _handle_transient_message(self, message: str) -> None:
        self.window.set_state(PetState.IDLE)
        self.window.show_message(message)
        self._finish_interaction_state()

    def _finish_interaction_state(self) -> None:
        self._interaction_busy = False
        self.window.set_state(PetState.IDLE)
        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()

    def _switch_random_mood(self) -> None:
        if self._interaction_busy or (self._chat_worker is not None and self._chat_worker.isRunning()):
            self._schedule_random_mood()
            return

        self.window.set_state(random.choice(RANDOM_MOOD_STATES))
        self._schedule_random_mood()

    def _schedule_random_mood(self) -> None:
        min_ms = self._config.runtime.random_mood_min_seconds * 1000
        max_ms = self._config.runtime.random_mood_max_seconds * 1000
        self._random_mood_timer.start(random.randint(min_ms, max_ms))


def main() -> int:
    setup_logging()
    logger = logging.getLogger(LOGGER_NAME)

    try:
        config = load_config()
    except ConfigError:
        logger.exception("Failed to load config.yaml.")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("CodingPet")

    controller = CodingPetController(config)
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
