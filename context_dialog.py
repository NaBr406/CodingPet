from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from conversation_history import MAX_USER_INPUT_CHARS, PASSIVE_CHAT_SOURCE, ChatTurn


class ContextDialog(QDialog):
    # 展示本次运行内的主动聊天和被动观察记录，并允许继续发送消息。
    submitted = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("本次对话记录")
        self.setModal(False)
        self.setMinimumSize(680, 640)

        title_label = QLabel("本次对话记录")
        title_label.setObjectName("ContextTitle")
        subtitle_label = QLabel("本次运行中，CodingPet 记住的聊天与观察会在这里汇总。")
        subtitle_label.setObjectName("ContextSubtitle")
        subtitle_label.setWordWrap(True)

        self._multi_turn_badge = self._build_badge()
        self._memory_badge = self._build_badge()
        self._count_badge = self._build_badge()

        badge_row = QWidget()
        badge_layout = QHBoxLayout(badge_row)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setSpacing(8)
        badge_layout.addWidget(self._multi_turn_badge)
        badge_layout.addWidget(self._memory_badge)
        badge_layout.addWidget(self._count_badge)
        badge_layout.addStretch(1)

        header = QFrame()
        header.setObjectName("HeaderPanel")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(4, 0, 4, 4)
        header_layout.setSpacing(7)
        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        header_layout.addWidget(badge_row)

        self._history_scroll = QScrollArea()
        self._history_scroll.setObjectName("HistoryScroll")
        self._history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._history_content = QWidget()
        self._history_content.setObjectName("HistoryContent")
        self._history_layout = QVBoxLayout(self._history_content)
        self._history_layout.setContentsMargins(0, 4, 0, 4)
        self._history_layout.setSpacing(14)
        self._history_scroll.setWidget(self._history_content)

        self._status_label = QLabel()
        self._status_label.setObjectName("ContextStatus")
        self._status_label.setWordWrap(True)

        self._input = QLineEdit()
        self._input.setObjectName("ContextInput")
        self._input.setMaxLength(MAX_USER_INPUT_CHARS)
        self._input.setPlaceholderText("继续说点什么...")
        self._input.returnPressed.connect(self._submit)

        self._send_button = QPushButton("发送")
        self._send_button.setObjectName("SendButton")
        self._send_button.clicked.connect(self._submit)

        input_row = QFrame()
        input_row.setObjectName("ComposerRow")
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)
        input_layout.addWidget(self._input, 1)
        input_layout.addWidget(self._send_button)

        composer = QFrame()
        composer.setObjectName("ComposerPanel")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(14, 10, 14, 14)
        composer_layout.setSpacing(8)
        composer_layout.addWidget(self._status_label)
        composer_layout.addWidget(input_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(16)
        layout.addWidget(header)
        layout.addWidget(self._history_scroll, 1)
        layout.addWidget(composer)

        self._apply_style()
        self.update_context((), multi_turn_enabled=False, memory_turns=5)
        self.set_sending(False)

    def update_context(
        self,
        history: Sequence[ChatTurn],
        multi_turn_enabled: bool,
        memory_turns: int,
    ) -> None:
        # 这里展示的是“本次运行中的对话记录”，不是永久历史。
        # 所以每次刷新都由当前内存中的 chat history 直接重建。
        self._set_badge_text(
            self._multi_turn_badge,
            "多轮已开启" if multi_turn_enabled else "多轮未开启",
            "enabled" if multi_turn_enabled else "muted",
        )
        self._set_badge_text(self._memory_badge, f"记忆 {memory_turns} 条", "normal")
        self._set_badge_text(self._count_badge, f"已记录 {len(history)} 条", "normal")
        self._rebuild_history_view(history)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def set_sending(self, sending: bool) -> None:
        # 发送态下禁用输入，避免用户连续发起多次请求把状态打乱。
        self._input.setEnabled(not sending)
        self._send_button.setEnabled(not sending)
        self._send_button.setText("发送中" if sending else "发送")
        self._status_label.setText("正在等 CodingPet 回复..." if sending else "")
        if not sending:
            self._input.setFocus()

    def set_status(self, message: str) -> None:
        self._status_label.setText(message)

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if len(text) > MAX_USER_INPUT_CHARS:
            self.set_status(f"输入太长了，最多 {MAX_USER_INPUT_CHARS} 个字。")
            return
        self._input.clear()
        self.set_sending(True)
        self.submitted.emit(text)

    def _rebuild_history_view(self, history: Sequence[ChatTurn]) -> None:
        # 采用整块重建而不是局部 diff，代码更直白，也足够应对当前记录量。
        self._clear_history_layout()
        if not history:
            self._history_layout.addStretch(1)
            self._history_layout.addWidget(
                self._build_empty_state(),
                0,
                Qt.AlignmentFlag.AlignCenter,
            )
            self._history_layout.addStretch(1)
            return

        for index, turn in enumerate(history, start=1):
            self._history_layout.addWidget(self._build_turn_card(index, turn))
        self._history_layout.addStretch(1)

    def _clear_history_layout(self) -> None:
        while self._history_layout.count():
            item = self._history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_turn_card(self, index: int, turn: ChatTurn) -> QWidget:
        # 主动聊天和被动观察虽然都进历史，但展示策略略有不同。
        passive = turn.source == PASSIVE_CHAT_SOURCE
        card = QFrame()
        card.setObjectName("TurnCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(12)

        source_badge = QLabel("自动记录" if passive else "主动对话")
        source_badge.setObjectName("PassiveSourceBadge" if passive else "ActiveSourceBadge")
        source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        index_label = QLabel(f"第 {index} 条")
        index_label.setObjectName("TurnIndex")

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(source_badge)
        header_layout.addWidget(index_label)
        header_layout.addStretch(1)
        card_layout.addWidget(header)

        if passive:
            # 被动观察会把“窗口标题”放进观察到的内容里，和普通用户输入区分开。
            card_layout.addWidget(
                self._build_message_row(
                    "观察到",
                    self._observation_text(turn.user),
                    "ObservationBubble",
                    align_right=False,
                    fill_width=True,
                )
            )
        else:
            card_layout.addWidget(
                self._build_message_row(
                    "你",
                    turn.user,
                    "UserBubble",
                    align_right=True,
                    fill_width=False,
                )
            )

        card_layout.addWidget(
            self._build_message_row(
                "CodingPet",
                turn.assistant,
                "AssistantBubble",
                align_right=False,
                fill_width=passive,
            )
        )
        return card

    def _build_message_row(
        self,
        speaker: str,
        message: str,
        bubble_name: str,
        *,
        align_right: bool,
        fill_width: bool,
    ) -> QWidget:
        row = QWidget()
        row.setObjectName("MessageRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        bubble = QFrame()
        bubble.setObjectName(bubble_name)
        if fill_width:
            bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        else:
            bubble.setMinimumWidth(260)
            bubble.setMaximumWidth(540)
            bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 12)
        bubble_layout.setSpacing(6)

        speaker_label = QLabel(speaker)
        speaker_label.setObjectName("BubbleSpeaker")

        body_label = QLabel(message or "（没有内容）")
        body_label.setObjectName("BubbleText")
        body_label.setWordWrap(True)
        body_label.setTextFormat(Qt.TextFormat.PlainText)
        body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        bubble_layout.addWidget(speaker_label)
        bubble_layout.addWidget(body_label)

        if fill_width:
            # 观察记录通常更长，直接让气泡铺满可读性会更好。
            row_layout.addWidget(bubble, 1)
        elif align_right:
            row_layout.addStretch(2)
            row_layout.addWidget(bubble, 5)
        else:
            row_layout.addWidget(bubble, 5)
            row_layout.addStretch(2)
        return row

    def _build_empty_state(self) -> QWidget:
        # 空状态不是为了装饰，而是说明这里会记录什么、下一步该怎么触发记录。
        empty = QFrame()
        empty.setObjectName("EmptyState")
        empty.setMaximumWidth(460)
        layout = QVBoxLayout(empty)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(12)

        mark = QLabel("CP")
        mark.setObjectName("EmptyMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("还没有对话记录")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QLabel("从下面继续说一句话，或等 CodingPet 自动观察到新的窗口内容后，这里会出现整理好的记录。")
        body.setObjectName("EmptyBody")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(body)
        return empty

    def _build_badge(self) -> QLabel:
        badge = QLabel()
        badge.setObjectName("ContextBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return badge

    def _set_badge_text(self, badge: QLabel, text: str, tone: str) -> None:
        badge.setText(text)
        badge.setProperty("tone", tone)
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    def _scroll_to_bottom(self) -> None:
        scroll_bar = self._history_scroll.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def _observation_text(self, text: str) -> str:
        # 被动观察的 user 字段里带了一个统一前缀，这里剥掉后更适合展示。
        prefix = "被动观察："
        if text.startswith(prefix):
            return text[len(prefix):].strip() or "当前窗口"
        return text.strip() or "当前窗口"

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #f5f8fc;
                color: #102033;
                font-size: 13px;
            }
            QFrame#HeaderPanel {
                background: transparent;
                border: none;
            }
            QFrame#ComposerPanel {
                background: #ffffff;
                border: 1px solid #dbe6f4;
                border-radius: 8px;
            }
            QLabel#ContextTitle {
                color: #102033;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#ContextSubtitle {
                color: #607086;
            }
            QLabel#ContextBadge {
                border: 1px solid #d5e3f4;
                border-radius: 10px;
                color: #31506f;
                font-size: 12px;
                padding: 4px 10px;
            }
            QLabel#ContextBadge[tone="enabled"] {
                background: #e6f0ff;
                border-color: #a9c7f5;
                color: #2454a6;
            }
            QLabel#ContextBadge[tone="muted"] {
                background: #f1f5f9;
                border-color: #d7e1eb;
                color: #64748b;
            }
            QLabel#ContextBadge[tone="normal"] {
                background: #eef6ff;
                border-color: #c9daf7;
                color: #31506f;
            }
            QLabel#ContextStatus {
                color: #64748b;
                min-height: 18px;
            }
            QScrollArea#HistoryScroll {
                background: transparent;
                border: none;
            }
            QWidget#HistoryContent {
                background: transparent;
            }
            QFrame#TurnCard {
                background: #ffffff;
                border: 1px solid #dbe6f4;
                border-radius: 8px;
            }
            QLabel#ActiveSourceBadge,
            QLabel#PassiveSourceBadge {
                border-radius: 9px;
                font-size: 12px;
                font-weight: 600;
                padding: 4px 9px;
            }
            QLabel#ActiveSourceBadge {
                background: #e7f1ff;
                color: #255ea8;
            }
            QLabel#PassiveSourceBadge {
                background: #eef3f8;
                color: #52677a;
            }
            QLabel#TurnIndex {
                color: #8da0b5;
                font-size: 12px;
            }
            QFrame#UserBubble,
            QFrame#AssistantBubble,
            QFrame#ObservationBubble {
                border-radius: 8px;
            }
            QFrame#UserBubble {
                background: #2563eb;
                border: 1px solid #2563eb;
            }
            QFrame#AssistantBubble {
                background: #f8fbff;
                border: 1px solid #d7e4f5;
            }
            QFrame#ObservationBubble {
                background: #f3f6fa;
                border: 1px solid #dce5ef;
            }
            QFrame#UserBubble QLabel#BubbleSpeaker,
            QFrame#UserBubble QLabel#BubbleText {
                color: #ffffff;
            }
            QLabel#BubbleSpeaker {
                color: #425d78;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#BubbleText {
                color: #102033;
                line-height: 145%;
                selection-background-color: #bfdbfe;
            }
            QFrame#EmptyState {
                background: #ffffff;
                border: 1px dashed #c7d8ee;
                border-radius: 8px;
            }
            QLabel#EmptyMark {
                background: #e7f1ff;
                border: 1px solid #b5cff4;
                border-radius: 22px;
                color: #2454a6;
                font-weight: 800;
                min-height: 44px;
                min-width: 44px;
                max-height: 44px;
                max-width: 44px;
            }
            QLabel#EmptyTitle {
                color: #102033;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#EmptyBody {
                color: #64748b;
            }
            QLineEdit#ContextInput {
                background: #f8fbff;
                border: 1px solid #c7d8ee;
                border-radius: 6px;
                color: #102033;
                padding: 9px 11px;
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
                padding: 9px 16px;
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
