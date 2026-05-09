from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIntValidator, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from config_loader import AppConfig, CoreSettings, DEFAULT_PERSONALITY_PROMPT, core_settings_from_config


INTERVAL_MIN_SECONDS = 5
INTERVAL_MAX_SECONDS = 86400


class IntervalStepButton(QAbstractButton):
    def __init__(self, direction: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._direction = 1 if direction > 0 else -1
        self.setFixedSize(34, 23)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("增加 1 秒" if self._direction > 0 else "减少 1 秒")

    def paintEvent(self, event: object) -> None:
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.isDown():
            fill = QColor("#d9ebff")
            border = QColor("#60a5fa")
            chevron = QColor("#0f3f8c")
        elif self.underMouse():
            fill = QColor("#eef6ff")
            border = QColor("#93c5fd")
            chevron = QColor("#1d4ed8")
        else:
            fill = QColor("#f7fbff")
            border = QColor("#bfdbfe")
            chevron = QColor("#2563eb")

        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)

        pen = QPen(chevron, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        center_x = self.width() / 2
        center_y = self.height() / 2
        span = 5.0
        rise = 3.8
        if self._direction > 0:
            points = (
                (center_x - span, center_y + 2),
                (center_x, center_y - rise),
                (center_x + span, center_y + 2),
            )
        else:
            points = (
                (center_x - span, center_y - 2),
                (center_x, center_y + rise),
                (center_x + span, center_y - 2),
            )

        painter.drawLine(int(points[0][0]), int(points[0][1]), int(points[1][0]), int(points[1][1]))
        painter.drawLine(int(points[1][0]), int(points[1][1]), int(points[2][0]), int(points[2][1]))


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("CodingPet 设置")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(740)

        settings = core_settings_from_config(config)
        self._base_url_edit = QLineEdit(settings.base_url)
        self._base_url_edit.setPlaceholderText("https://your-endpoint.example/v1")
        self._api_key_edit = QLineEdit(settings.api_key)
        self._api_key_edit.setPlaceholderText("sk-...")
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._vision_model_edit = QLineEdit(settings.vision_model_name)
        self._vision_model_edit.setPlaceholderText("支持 image_url 的视觉模型")
        self._chat_model_edit = QLineEdit(settings.chat_model_name)
        self._chat_model_edit.setPlaceholderText("纯文本聊天模型")
        self._personality_edit = QPlainTextEdit(settings.personality_prompt)
        self._personality_edit.setObjectName("PersonalityInput")
        self._personality_edit.setPlaceholderText(DEFAULT_PERSONALITY_PROMPT)
        self._personality_edit.setFixedHeight(86)
        self._observation_enabled_check = QCheckBox("开启全局监听")
        self._observation_enabled_check.setChecked(settings.global_observation_enabled)
        self._interval_edit = QLineEdit(str(settings.interval_seconds))
        self._interval_edit.setObjectName("IntervalInput")
        self._interval_edit.setPlaceholderText("300")
        self._interval_edit.setValidator(
            QIntValidator(INTERVAL_MIN_SECONDS, INTERVAL_MAX_SECONDS, self)
        )

        self._build_layout()
        self._apply_style()

    def core_settings(self) -> CoreSettings:
        return CoreSettings(
            base_url=self._base_url_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            vision_model_name=self._vision_model_edit.text().strip(),
            chat_model_name=self._chat_model_edit.text().strip(),
            personality_prompt=self._personality_edit.toPlainText().strip() or DEFAULT_PERSONALITY_PROMPT,
            global_observation_enabled=self._observation_enabled_check.isChecked(),
            interval_seconds=self._interval_seconds(),
        )

    def accept(self) -> None:
        try:
            settings = self.core_settings()
            self._validate_settings(settings)
        except ValueError as exc:
            QMessageBox.warning(self, "设置有误", str(exc))
            return
        super().accept()

    def _build_layout(self) -> None:
        title = QLabel("设置")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("配置模型、人设和全局监听，保存后会立即应用到新的聊天和观察任务。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        model_group = self._build_model_group()
        preset_group = self._build_preset_group()
        observer_group = self._build_observer_group()

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        save_button.setText("保存")
        cancel_button.setText("取消")
        save_button.setObjectName("SaveButton")
        cancel_button.setObjectName("CancelButton")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(model_group)
        layout.addWidget(preset_group)
        layout.addWidget(observer_group)
        layout.addStretch(1)
        layout.addWidget(self._buttons)

    def _build_model_group(self) -> QGroupBox:
        group = QGroupBox("模型配置")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_field(
            "接口地址",
            self._base_url_edit,
            "OpenAI 兼容接口地址，通常以 /v1 结尾。",
        ))
        layout.addWidget(self._build_field(
            "API Key",
            self._build_api_key_row(),
            "留空可以保存，但模型请求仍需要有效 API Key。",
        ))
        layout.addWidget(self._build_field(
            "视觉模型",
            self._vision_model_edit,
            "用于截图聊天和全局观测，需要支持图片输入。",
        ))
        layout.addWidget(self._build_field(
            "聊天模型",
            self._chat_model_edit,
            "用于纯文本聊天，也会作为视觉请求降级后的重试模型。",
        ))
        return group

    def _build_preset_group(self) -> QGroupBox:
        group = QGroupBox("人设设置")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(self._build_field(
            "人设提示词",
            self._personality_edit,
            "留空保存会使用默认人设。",
        ))
        return group

    def _build_observer_group(self) -> QGroupBox:
        group = QGroupBox("全局监听")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(self._observation_enabled_check)
        layout.addWidget(self._build_field(
            "监听间隔",
            self._build_interval_row(),
            "开启后会按间隔观察当前前台窗口，不再按窗口标题或 IDE 关键词过滤。",
        ))
        return group

    def _build_field(self, title: str, editor: QWidget, hint: str = "") -> QWidget:
        title_label = QLabel(title)
        title_label.setObjectName("FieldLabel")

        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(title_label)
        layout.addWidget(editor)
        if hint:
            layout.addWidget(self._build_field_hint(hint))
        return block

    def _build_api_key_row(self) -> QWidget:
        show_key_check = QCheckBox("显示")
        show_key_check.toggled.connect(self._toggle_api_key_visibility)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._api_key_edit, 1)
        layout.addWidget(show_key_check)
        return row

    def _build_interval_row(self) -> QWidget:
        seconds_label = QLabel("秒")
        seconds_label.setObjectName("IntervalUnit")

        increase_button = IntervalStepButton(1)
        decrease_button = IntervalStepButton(-1)
        for button, position, delta in (
            (increase_button, "up", 1),
            (decrease_button, "down", -1),
        ):
            button.setObjectName("StepButton")
            button.setProperty("stepPosition", position)
            button.clicked.connect(lambda _checked=False, step=delta: self._step_interval(step))

        step_layout = QVBoxLayout()
        step_layout.setContentsMargins(0, 0, 0, 0)
        step_layout.setSpacing(4)
        step_layout.addWidget(increase_button)
        step_layout.addWidget(decrease_button)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._interval_edit, 1)
        layout.addWidget(seconds_label)
        layout.addLayout(step_layout)
        return row

    def _build_field_hint(self, text: str) -> QLabel:
        hint = QLabel(text)
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        return hint

    def _toggle_api_key_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._api_key_edit.setEchoMode(mode)

    def _interval_seconds(self) -> int:
        raw_value = self._interval_edit.text().strip()
        if not raw_value:
            raise ValueError("监听间隔不能为空。")
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError("监听间隔必须是数字。") from exc

    def _set_interval_seconds(self, value: int) -> None:
        clamped = max(INTERVAL_MIN_SECONDS, min(INTERVAL_MAX_SECONDS, value))
        self._interval_edit.setText(str(clamped))

    def _step_interval(self, delta: int) -> None:
        try:
            value = self._interval_seconds()
        except ValueError:
            value = INTERVAL_MIN_SECONDS
        self._set_interval_seconds(value + delta)

    def _validate_settings(self, settings: CoreSettings) -> None:
        if not settings.base_url:
            raise ValueError("接口地址不能为空。")
        if not settings.vision_model_name:
            raise ValueError("视觉模型不能为空。")
        if not settings.chat_model_name:
            raise ValueError("聊天模型不能为空。")
        if settings.interval_seconds < INTERVAL_MIN_SECONDS:
            raise ValueError("监听间隔不能小于 5 秒。")
        if settings.interval_seconds > INTERVAL_MAX_SECONDS:
            raise ValueError("监听间隔不能大于 86400 秒。")

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog {
                background: #f8fbff;
                color: #102033;
                font-size: 13px;
            }
            QLabel#DialogTitle {
                color: #0f3f8c;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#DialogSubtitle {
                color: #4b6382;
                font-size: 12px;
            }
            QLabel#FieldLabel {
                color: #1d4ed8;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#FieldHint {
                color: #64748b;
                font-size: 11px;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #bfd7ff;
                border-radius: 8px;
                margin-top: 14px;
                padding: 14px 12px 12px 12px;
                font-weight: 600;
                color: #1d4ed8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                background: #f8fbff;
            }
            QLineEdit,
            QLineEdit#IntervalInput,
            QPlainTextEdit#PersonalityInput {
                background: #ffffff;
                border: 1px solid #b7d4ff;
                border-radius: 6px;
                color: #102033;
                selection-background-color: #3b82f6;
                padding: 7px 9px;
            }
            QLineEdit:focus,
            QLineEdit#IntervalInput:focus,
            QPlainTextEdit#PersonalityInput:focus {
                border: 1px solid #2563eb;
            }
            QLabel#IntervalUnit {
                color: #1e385f;
                padding: 0 2px;
            }
            QCheckBox {
                color: #1e385f;
                spacing: 8px;
                font-weight: 600;
            }
            QDialogButtonBox {
                button-layout: 0;
            }
            QPushButton {
                border-radius: 6px;
                padding: 8px 18px;
                min-width: 78px;
                font-weight: 600;
            }
            QPushButton#SaveButton {
                background: #2563eb;
                border: 1px solid #2563eb;
                color: #ffffff;
            }
            QPushButton#SaveButton:hover {
                background: #1d4ed8;
            }
            QPushButton#CancelButton {
                background: #ffffff;
                border: 1px solid #b7d4ff;
                color: #1d4ed8;
            }
            QPushButton#CancelButton:hover {
                background: #eaf2ff;
            }
            """
        )
