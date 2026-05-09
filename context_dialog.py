from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from conversation_history import PASSIVE_CHAT_SOURCE, ChatTurn


class ContextDialog(QDialog):
    submitted = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("本次对话")
        self.setModal(False)
        self.setMinimumSize(560, 620)

        self._summary_label = QLabel()
        self._summary_label.setObjectName("ContextSummary")
        self._summary_label.setWordWrap(True)

        self._history_view = QPlainTextEdit()
        self._history_view.setObjectName("HistoryView")
        self._history_view.setReadOnly(True)
        self._history_view.setPlaceholderText("本次运行还没有记录聊天上下文。")

        self._status_label = QLabel()
        self._status_label.setObjectName("ContextStatus")
        self._status_label.setWordWrap(True)

        self._input = QLineEdit()
        self._input.setObjectName("ContextInput")
        self._input.setPlaceholderText("继续说点什么...")
        self._input.returnPressed.connect(self._submit)

        self._send_button = QPushButton("发送")
        self._send_button.setObjectName("SendButton")
        self._send_button.clicked.connect(self._submit)

        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)
        input_layout.addWidget(self._input, 1)
        input_layout.addWidget(self._send_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._summary_label)
        layout.addWidget(self._history_view, 1)
        layout.addWidget(self._status_label)
        layout.addWidget(input_row)

        self._apply_style()
        self.update_context((), multi_turn_enabled=False, memory_turns=5)
        self.set_sending(False)

    def update_context(
        self,
        history: Sequence[ChatTurn],
        multi_turn_enabled: bool,
        memory_turns: int,
    ) -> None:
        status = "开启" if multi_turn_enabled else "关闭"
        self._summary_label.setText(
            f"多轮发送：{status}    保留记录：{memory_turns} 条    本次已记录：{len(history)} 条"
        )
        self._history_view.setPlainText(self._format_history(history))
        self._history_view.moveCursor(QTextCursor.MoveOperation.End)

    def set_sending(self, sending: bool) -> None:
        self._input.setEnabled(not sending)
        self._send_button.setEnabled(not sending)
        self._status_label.setText("发送中..." if sending else "")
        if not sending:
            self._input.setFocus()

    def set_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.set_sending(True)
        self.submitted.emit(text)

    def _format_history(self, history: Sequence[ChatTurn]) -> str:
        if not history:
            return ""

        blocks: list[str] = []
        for index, turn in enumerate(history, start=1):
            source_label = "被动观察" if turn.source == PASSIVE_CHAT_SOURCE else "主动聊天"
            speaker_label = "观察对象" if turn.source == PASSIVE_CHAT_SOURCE else "用户"
            blocks.append(f"第 {index} 条 · {source_label}")
            blocks.append(f"{speaker_label}：{turn.user}")
            blocks.append(f"CodingPet：{turn.assistant}")
            blocks.append("")
        return "\n".join(blocks).strip()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #f8fbff;
                color: #102033;
                font-size: 13px;
            }
            QLabel#ContextSummary {
                color: #0f3f8c;
                font-weight: 700;
            }
            QLabel#ContextStatus {
                color: #64748b;
                min-height: 18px;
            }
            QPlainTextEdit#HistoryView {
                background: #ffffff;
                border: 1px solid #bfd7ff;
                border-radius: 8px;
                color: #102033;
                padding: 10px;
                selection-background-color: #3b82f6;
            }
            QLineEdit#ContextInput {
                background: #ffffff;
                border: 1px solid #b7d4ff;
                border-radius: 6px;
                color: #102033;
                padding: 8px 10px;
            }
            QLineEdit#ContextInput:focus {
                border: 1px solid #2563eb;
            }
            QPushButton#SendButton {
                background: #2563eb;
                border: 1px solid #2563eb;
                border-radius: 6px;
                color: #ffffff;
                font-weight: 600;
                min-width: 82px;
                padding: 8px 14px;
            }
            QPushButton#SendButton:hover {
                background: #1d4ed8;
            }
            QPushButton#SendButton:disabled {
                background: #93c5fd;
                border-color: #93c5fd;
            }
            """
        )
