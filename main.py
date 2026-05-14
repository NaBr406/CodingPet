from __future__ import annotations

import logging
import random
import sys

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from chat_thread import ChatWorker
from config_loader import ConfigError, AppConfig, load_config, save_core_settings, user_config_dir
from context_dialog import ContextDialog
from conversation_history import ACTIVE_CHAT_SOURCE, MAX_USER_INPUT_CHARS, PASSIVE_CHAT_SOURCE, ChatTurn
from llm_client import close_cached_clients
from logging_utils import LOGGER_NAME, setup_logging
from observer_thread import ObserverWorker
from pet_state import RANDOM_MOOD_STATES, PetState
from settings_dialog import SettingsDialog
from ui_core import PetWindow


class CodingPetController(QObject):
    # 应用控制器：连接 UI、聊天线程、观察线程、配置和上下文历史。
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._logger = logging.getLogger(LOGGER_NAME)
        self._chat_worker: ChatWorker | None = None
        self._observer_worker: ObserverWorker | None = None
        self._context_dialog: ContextDialog | None = None
        self._chat_history: list[ChatTurn] = []
        self._interaction_busy = False
        self._manual_override_active = False
        self._random_mood_active = False
        self._observer_restart_after_stop = False
        self._observer_stopping = False

        self.window = PetWindow(config)
        self.window.chat_submitted.connect(self._start_chat)
        self.window.chat_opened.connect(self._handle_chat_opened)
        self.window.chat_cancelled.connect(self._handle_chat_cancelled)
        self.window.drag_started.connect(self._handle_drag_started)
        self.window.drag_finished.connect(self._handle_drag_finished)
        self.window.resize_started.connect(self._handle_resize_started)
        self.window.resize_finished.connect(self._handle_resize_finished)
        self.window.settings_requested.connect(self._open_settings)
        self.window.context_requested.connect(self._open_context_dialog)

        self._state_reset_timer = QTimer(self)
        self._state_reset_timer.setSingleShot(True)
        self._state_reset_timer.timeout.connect(self._finish_interaction_state)

        self._random_mood_timer = QTimer(self)
        self._random_mood_timer.setSingleShot(True)
        self._random_mood_timer.timeout.connect(self._switch_random_mood)

        self._initial_observer_timer = QTimer(self)
        self._initial_observer_timer.setSingleShot(True)
        self._initial_observer_timer.timeout.connect(self._sync_observer_worker)

    def start(self) -> None:
        # 启动时先把窗口和基础状态亮出来，再接入观察线程。
        self.window.show()
        self.window.set_state(PetState.GREETING)
        self.window.show_message("双击我对话", 2800)

        self._logger.info("阶段 1 成功：透明宠物窗口已就绪。")
        self._logger.info("阶段 2 成功：交互聊天链路已接好。")

        self._schedule_initial_observer_start()

        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()
            self._logger.info("随机心情切换已启用。")

    def shutdown(self) -> None:
        # 退出时按顺序停掉后台线程和悬浮窗口，避免进程结束前还在请求模型。
        self._stop_observer_worker(
            wait_ms=self._observer_shutdown_wait_ms(),
            force_terminate=True,
        )

        if self._chat_worker is not None and self._chat_worker.isRunning():
            self._chat_worker.wait(1500)

        if self._context_dialog is not None:
            self._context_dialog.close()

        self._random_mood_timer.stop()
        self._state_reset_timer.stop()
        self._initial_observer_timer.stop()
        close_cached_clients()

    def _start_chat(self, text: str) -> bool:
        # 同一时间只允许一条主动请求，避免聊天结果和界面状态交叉覆盖。
        user_text = text.strip()
        if not user_text:
            return False
        if len(user_text) > MAX_USER_INPUT_CHARS:
            self.window.show_message(f"一次最多输入 {MAX_USER_INPUT_CHARS} 个字。")
            if self._context_dialog is not None:
                self._context_dialog.set_sending(False)
                self._context_dialog.set_status(f"输入太长了，最多 {MAX_USER_INPUT_CHARS} 个字。")
            return False

        if self._chat_worker is not None and self._chat_worker.isRunning():
            self.window.show_message("一次只处理一个请求，别把我当竞态条件。")
            if self._context_dialog is not None:
                self._context_dialog.set_sending(False)
                self._context_dialog.set_status("当前已有请求处理中。")
            return False

        self.window.set_state(PetState.THINKING)
        self.window.show_message("我想一下...", 1600)
        self._interaction_busy = True
        self._manual_override_active = False
        self._random_mood_active = False
        self._random_mood_timer.stop()
        self._refresh_observer_observation_gate()

        if self._context_dialog is not None:
            self._context_dialog.set_sending(True)

        worker = ChatWorker(self._config, user_text, self._chat_history_snapshot())
        worker.response_ready.connect(self._handle_chat_reply)
        worker.request_failed.connect(self._handle_interaction_failed)
        worker.finished.connect(self._clear_chat_worker)
        self._chat_worker = worker
        worker.start()
        return True

    def _clear_chat_worker(self) -> None:
        if self._chat_worker is not None:
            self._chat_worker.deleteLater()
            self._chat_worker = None
        self._refresh_observer_observation_gate()

    def _open_settings(self) -> None:
        # 设置保存后立刻重载，让新请求走新的配置。
        dialog = SettingsDialog(self._config, self.window)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            save_core_settings(self._config.config_path, dialog.core_settings())
            config = load_config(self._config.config_path)
        except (ConfigError, OSError, ValueError) as exc:
            self._logger.exception("保存设置失败。")
            QMessageBox.warning(self.window, "设置保存失败", str(exc))
            return

        self._apply_config(config)
        self.window.show_message("设置已保存，新的请求会使用这套配置。", 2600)

    def _apply_config(self, config: AppConfig) -> None:
        # 重新注入配置后，要同步刷新窗口、历史记录和观察线程。
        self._config = config
        self.window.update_config(config)
        self._trim_chat_history()
        self._refresh_context_dialog()
        self._initial_observer_timer.stop()
        self._sync_observer_worker(force_restart=True)

    def _schedule_initial_observer_start(self) -> None:
        if not self._config.observer.global_observation_enabled:
            self._sync_observer_worker()
            return

        self._initial_observer_timer.start(self._initial_observer_start_delay_ms())

    def _initial_observer_start_delay_ms(self) -> int:
        return max(
            self._config.runtime.message_duration_ms,
            min(
                self._config.observer.interval_seconds * 1000,
                self._config.runtime.random_mood_min_seconds * 1000,
            ),
        )

    def _sync_observer_worker(self, force_restart: bool = False) -> None:
        # 观察线程是否启用完全由配置控制。
        if force_restart and self._observer_worker is not None:
            self._stop_observer_worker(restart_after_stop=True)
            return

        if self._config.observer.global_observation_enabled:
            self._start_observer_worker()
        else:
            self._stop_observer_worker()
            self._logger.info("阶段 3 已关闭：配置里禁用了全局观测。")

    def _start_observer_worker(self) -> None:
        # 观察线程负责后台“看屏幕 + 生成主动评论”，只在配置允许时启动。
        if self._observer_worker is not None:
            return

        worker = ObserverWorker(self._config)
        self._connect_observer_worker_signals(worker)
        self._observer_worker = worker
        self._observer_stopping = False
        self._observer_restart_after_stop = False
        self._refresh_observer_observation_gate()
        worker.start()
        self._logger.info("阶段 3 成功：全局观测线程已启动。")

    def _stop_observer_worker(
        self,
        restart_after_stop: bool = False,
        wait_ms: int = 1500,
        force_terminate: bool = False,
    ) -> bool:
        # 优雅停线程：先请求 stop，再等一小会儿。
        if self._observer_worker is None:
            self._observer_restart_after_stop = False
            return True

        worker = self._observer_worker
        self._observer_restart_after_stop = restart_after_stop
        self._observer_stopping = True
        self._disconnect_observer_observation_signals(worker)
        worker.set_observation_allowed(False)
        worker.stop()
        if worker.wait(max(0, wait_ms)):
            self._finalize_observer_worker(worker)
            return True

        if force_terminate:
            self._logger.warning("观察线程退出超时，将在应用退出路径强制结束。")
            worker.terminate()
            if worker.wait(1000):
                self._finalize_observer_worker(worker)
                return True
            self._logger.critical("观察线程强制结束后仍未退出，进程可能需要由系统回收。")
            return False

        self._logger.warning("观察线程仍在收尾，等待当前请求结束后再释放。")
        return False

    def _handle_observer_worker_finished(self, worker: ObserverWorker) -> None:
        if worker is not self._observer_worker:
            self._disconnect_all_observer_signals(worker)
            worker.deleteLater()
            return

        self._finalize_observer_worker(worker)

    def _finalize_observer_worker(self, worker: ObserverWorker) -> None:
        restart_after_stop = self._observer_restart_after_stop
        if worker is self._observer_worker:
            self._observer_worker = None
            self._observer_restart_after_stop = False
            self._observer_stopping = False
        self._disconnect_all_observer_signals(worker)
        worker.deleteLater()
        if restart_after_stop and self._config.observer.global_observation_enabled:
            self._start_observer_worker()

    def _connect_observer_worker_signals(self, worker: ObserverWorker) -> None:
        worker.observation_started.connect(self._handle_observation_started)
        worker.observation_failed.connect(self._handle_observation_finished_without_reply)
        worker.observation_ready.connect(self._handle_observation_reply)
        worker.finished.connect(lambda: self._handle_observer_worker_finished(worker))

    def _disconnect_observer_observation_signals(self, worker: ObserverWorker) -> None:
        for signal in (
            worker.observation_started,
            worker.observation_failed,
            worker.observation_ready,
        ):
            try:
                signal.disconnect()
            except TypeError:
                pass

    def _disconnect_all_observer_signals(self, worker: ObserverWorker) -> None:
        self._disconnect_observer_observation_signals(worker)
        try:
            worker.finished.disconnect()
        except TypeError:
            pass

    def _observer_shutdown_wait_ms(self) -> int:
        return int((self._config.runtime.request_timeout_seconds + 2.0) * 1000)

    def _is_active_observer_worker(self, worker: ObserverWorker) -> bool:
        return (
            worker is self._observer_worker
            and not self._observer_stopping
            and not worker.is_stop_requested()
        )

    def _observer_can_run_cycle(self) -> bool:
        if self._observer_worker is None or self._observer_stopping:
            return False
        if not self._config.observer.global_observation_enabled:
            return False
        if self._interaction_busy or self._manual_override_active:
            return False
        return not (self._chat_worker is not None and self._chat_worker.isRunning())

    def _refresh_observer_observation_gate(self) -> None:
        if self._observer_worker is not None:
            self._observer_worker.set_observation_allowed(self._observer_can_run_cycle())

    def _handle_chat_reply(self, user_text: str, message: str, emotion: str) -> None:
        # 主动聊天完成后，把记录写进历史，再驱动宠物状态和上下文面板。
        self._record_chat_turn(user_text, message, ACTIVE_CHAT_SOURCE)
        if self._context_dialog is not None:
            self._context_dialog.set_sending(False)
        self._handle_model_reply(message, emotion)
        self._refresh_context_dialog()

    def _handle_observation_reply(
        self,
        worker: ObserverWorker,
        window_title: str,
        message: str,
        emotion: str,
    ) -> None:
        # 被动观察会把窗口标题一起记进历史，方便上下文面板区分来源。
        if not self._is_active_observer_worker(worker):
            return
        if not self._observer_can_run_cycle():
            self._logger.info("观察回复到达时当前正忙，已忽略本轮结果。")
            self._refresh_observer_observation_gate()
            return
        self._record_chat_turn(f"被动观察：{window_title}", message, PASSIVE_CHAT_SOURCE)
        self._handle_model_reply(message, emotion, clear_manual_override=False)
        self._refresh_context_dialog()

    def _handle_model_reply(
        self,
        message: str,
        emotion: str,
        clear_manual_override: bool = True,
    ) -> None:
        # 模型输出里带的情绪值会映射到宠物状态图。
        if self._manual_override_active and not clear_manual_override:
            return
        state = PetState.from_emotion(emotion)
        self._interaction_busy = True
        if clear_manual_override:
            self._manual_override_active = False
        self._random_mood_active = False
        self._random_mood_timer.stop()
        self._refresh_observer_observation_gate()
        self.window.set_state(state)
        display_ms = self._config.runtime.message_duration_ms
        self.window.show_message(message, display_ms)
        self._state_reset_timer.start(max(self._config.runtime.state_reset_ms, display_ms))

    def _handle_observation_started(self, worker: ObserverWorker) -> None:
        # 只有在当前不忙、也没有手动拖拽/缩放时，才切到观察态。
        if not self._is_active_observer_worker(worker) or not self._observer_can_run_cycle():
            self._refresh_observer_observation_gate()
            return
        self._random_mood_active = False
        self._random_mood_timer.stop()
        self.window.set_state(PetState.REVIEWING)

    def _handle_observation_finished_without_reply(self, worker: ObserverWorker) -> None:
        # 本轮观察没生成有效回复时，回到空闲态并重新安排随机心情。
        if not self._is_active_observer_worker(worker):
            return
        if self._interaction_busy or self._manual_override_active:
            self._refresh_observer_observation_gate()
            return
        self._random_mood_active = False
        self.window.set_state(PetState.IDLE)
        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()

    def _handle_interaction_failed(self, message: str) -> None:
        # 出错时要把上下文面板和窗口状态都拉回可继续交互的状态。
        if self._context_dialog is not None:
            self._context_dialog.set_sending(False)
            self._context_dialog.set_status("发送失败，稍后再试吧。")
        self._random_mood_active = False
        self.window.set_state(PetState.IDLE)
        self.window.show_message(message)
        self._finish_interaction_state()

    def _finish_interaction_state(self) -> None:
        # 一次回复展示完以后，交互态不应该一直占着。
        self._interaction_busy = False
        self._manual_override_active = False
        self._random_mood_active = False
        self._refresh_observer_observation_gate()
        self.window.set_state(PetState.IDLE)
        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()

    def _switch_random_mood(self) -> None:
        # 随机心情只在没有人工操作和请求占用时切换。
        if (
            self._interaction_busy
            or self._manual_override_active
            or (self._chat_worker is not None and self._chat_worker.isRunning())
        ):
            self._random_mood_active = False
            self._schedule_random_mood()
            return

        if self._random_mood_active:
            self._random_mood_active = False
            self.window.set_state(PetState.IDLE)
            self._schedule_random_mood()
            return

        mood_choices = [
            state
            for state in RANDOM_MOOD_STATES
            if state is not PetState.IDLE and state != self.window.current_state
        ]
        if not mood_choices:
            self._schedule_random_mood()
            return

        self._random_mood_active = True
        self.window.set_state(random.choice(mood_choices))
        self._random_mood_timer.start(self._random_mood_hold_ms())

    def _random_mood_hold_ms(self) -> int:
        return max(3000, min(5500, self._config.runtime.message_duration_ms - 1500))

    def _schedule_random_mood(self) -> None:
        self._random_mood_active = False
        # 随机时间间隔由配置决定，避免心情切换过于机械。
        min_ms = self._config.runtime.random_mood_min_seconds * 1000
        max_ms = self._config.runtime.random_mood_max_seconds * 1000
        self._random_mood_timer.start(random.randint(min_ms, max_ms))

    def _handle_chat_opened(self) -> None:
        # 打开输入框时进入“听你说”的状态，但如果当前已有请求则不抢状态。
        if self._interaction_busy:
            return
        self._manual_override_active = True
        self._random_mood_active = False
        self._random_mood_timer.stop()
        self._refresh_observer_observation_gate()
        self.window.set_state(PetState.LISTENING)

    def _handle_chat_cancelled(self) -> None:
        self._clear_manual_override()

    def _open_context_dialog(self) -> None:
        # 上下文窗口只创建一次，后续重复打开时直接刷新内容。
        if self._context_dialog is None:
            dialog = ContextDialog(self.window)
            dialog.submitted.connect(self._handle_context_submitted)
            self._context_dialog = dialog
        self._refresh_context_dialog()
        self._context_dialog.show()
        self._context_dialog.raise_()
        self._context_dialog.activateWindow()

    def _handle_context_submitted(self, text: str) -> None:
        if not self._start_chat(text) and self._context_dialog is not None:
            self._context_dialog.set_sending(False)

    def _record_chat_turn(self, user_text: str, assistant_text: str, source: str) -> None:
        # 本次运行的对话记录只保留内存中的有限轮数。
        self._chat_history.append(ChatTurn(user=user_text, assistant=assistant_text, source=source))
        self._trim_chat_history()

    def _chat_history_snapshot(self) -> tuple[ChatTurn, ...]:
        if not self._config.chat.multi_turn_enabled:
            return ()
        return tuple(self._chat_history[-self._config.chat.memory_turns:])

    def _trim_chat_history(self) -> None:
        # 按设置里的 memory_turns 截断，避免历史无限增长。
        limit = self._config.chat.memory_turns
        if len(self._chat_history) > limit:
            del self._chat_history[:-limit]

    def _refresh_context_dialog(self) -> None:
        # 上下文面板显示的始终是当前内存里的那份历史快照。
        if self._context_dialog is None:
            return
        self._context_dialog.update_context(
            self._chat_history,
            self._config.chat.multi_turn_enabled,
            self._config.chat.memory_turns,
        )

    def _handle_drag_started(self) -> None:
        # 用户手动拖动宠物时，随机心情暂时停掉，状态切成拖拽态。
        if self._interaction_busy:
            return
        self._manual_override_active = True
        self._random_mood_active = False
        self._random_mood_timer.stop()
        self._refresh_observer_observation_gate()
        self.window.set_state(PetState.DRAGGING)

    def _handle_drag_finished(self) -> None:
        self._clear_manual_override()

    def _handle_resize_started(self) -> None:
        # 缩放与拖动一样，属于人工接管状态。
        if self._interaction_busy:
            return
        self._manual_override_active = True
        self._random_mood_active = False
        self._random_mood_timer.stop()
        self._refresh_observer_observation_gate()
        self.window.set_state(PetState.RESIZING)

    def _handle_resize_finished(self) -> None:
        self._clear_manual_override()

    def _clear_manual_override(self) -> None:
        # 人工操作结束后，重新回到自动状态，并恢复随机心情调度。
        if self._interaction_busy:
            return
        self._manual_override_active = False
        self._random_mood_active = False
        self._refresh_observer_observation_gate()
        self.window.set_state(PetState.IDLE)
        if self._config.runtime.random_mood_enabled:
            self._schedule_random_mood()


def main() -> int:
    # 入口函数只做三件事：初始化日志、加载配置、启动 Qt 应用。
    log_path = user_config_dir() / "codingpet.log" if getattr(sys, "frozen", False) else "codingpet.log"
    setup_logging(log_path)
    logger = logging.getLogger(LOGGER_NAME)

    try:
        config = load_config()
    except ConfigError:
        logger.exception("加载 config.yaml 失败。")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("CodingPet")
    icon_path = config.assets_dir / "codingpet.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    controller = CodingPetController(config)
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
