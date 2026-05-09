from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config_loader import AppConfig, CoreSettings, DEFAULT_PERSONALITY_PROMPT, core_settings_from_config


INTERVAL_MIN_SECONDS = 5
INTERVAL_MAX_SECONDS = 86400
MEMORY_TURNS_MIN = 1
MEMORY_TURNS_MAX = 20
MENU_WIDTH = 148
MENU_ANIMATION_MS = 180


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("CodingPet 设置")
        self.setModal(True)
        self.setMinimumSize(680, 520)

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
        self._multi_turn_enabled_check = QCheckBox("开启多轮对话")
        self._multi_turn_enabled_check.setChecked(settings.multi_turn_enabled)
        self._memory_turns_edit = QLineEdit(str(settings.memory_turns))
        self._memory_turns_edit.setObjectName("MemoryTurnsInput")
        self._memory_turns_edit.setPlaceholderText("5")
        self._memory_turns_edit.setValidator(
            QIntValidator(MEMORY_TURNS_MIN, MEMORY_TURNS_MAX, self)
        )
        self._observation_enabled_check = QCheckBox("开启全局监听")
        self._observation_enabled_check.setChecked(settings.global_observation_enabled)
        self._interval_edit = QLineEdit(str(settings.interval_seconds))
        self._interval_edit.setObjectName("IntervalInput")
        self._interval_edit.setPlaceholderText("300")
        self._interval_edit.setValidator(
            QIntValidator(INTERVAL_MIN_SECONDS, INTERVAL_MAX_SECONDS, self)
        )
        self._menu_panel: QWidget | None = None
        self._section_stack: QStackedWidget | None = None
        self._section_buttons: list[QPushButton] = []
        self._menu_effect: QGraphicsOpacityEffect | None = None
        self._menu_animation: QParallelAnimationGroup | None = None
        self._menu_visible = True

        self._build_layout()
        self._apply_style()

    def core_settings(self) -> CoreSettings:
        return CoreSettings(
            base_url=self._base_url_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            vision_model_name=self._vision_model_edit.text().strip(),
            chat_model_name=self._chat_model_edit.text().strip(),
            personality_prompt=self._personality_edit.toPlainText().strip() or DEFAULT_PERSONALITY_PROMPT,
            multi_turn_enabled=self._multi_turn_enabled_check.isChecked(),
            memory_turns=self._memory_turns(),
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

        menu_button = QPushButton("☰")
        menu_button.setObjectName("MenuToggleButton")
        menu_button.setFixedSize(38, 34)
        menu_button.setToolTip("展开或收起设置分类")
        menu_button.clicked.connect(self._toggle_menu)

        title_row = QWidget()
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(10)
        title_layout.addWidget(menu_button)
        title_layout.addWidget(title, 1)

        self._section_stack = QStackedWidget()
        self._section_stack.setObjectName("SectionStack")
        sections = (
            ("模型配置", self._build_model_group()),
            ("人设设置", self._build_preset_group()),
            ("多轮对话", self._build_chat_group()),
            ("全局监听", self._build_observer_group()),
        )
        for _label, page in sections:
            self._section_stack.addWidget(page)

        self._menu_panel = QWidget()
        self._menu_panel.setObjectName("MenuPanel")
        self._menu_panel.setMinimumWidth(MENU_WIDTH)
        self._menu_panel.setMaximumWidth(MENU_WIDTH)
        self._menu_effect = QGraphicsOpacityEffect(self._menu_panel)
        self._menu_effect.setOpacity(1.0)
        self._menu_panel.setGraphicsEffect(self._menu_effect)
        menu_layout = QVBoxLayout(self._menu_panel)
        menu_layout.setContentsMargins(8, 8, 8, 8)
        menu_layout.setSpacing(8)

        self._section_button_group = QButtonGroup(self)
        self._section_button_group.setExclusive(True)
        self._section_buttons = []
        for index, (label, _page) in enumerate(sections):
            button = QPushButton(label)
            button.setObjectName("SectionButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, page_index=index: self._select_section(page_index))
            self._section_button_group.addButton(button)
            self._section_buttons.append(button)
            menu_layout.addWidget(button)
        menu_layout.addStretch(1)
        self._section_buttons[0].setChecked(True)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(self._menu_panel)
        content_layout.addWidget(self._section_stack, 1)

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
        layout.setSpacing(12)
        layout.addWidget(title_row)
        layout.addWidget(subtitle)
        layout.addWidget(content, 1)
        layout.addWidget(self._buttons)

    def _toggle_menu(self) -> None:
        if self._menu_panel is None or self._menu_effect is None:
            return

        showing = not self._menu_visible
        self._menu_visible = showing
        self._menu_panel.show()

        if self._menu_animation is not None:
            self._menu_animation.stop()

        start_width = self._menu_panel.maximumWidth()
        end_width = MENU_WIDTH if showing else 0
        start_opacity = self._menu_effect.opacity()
        end_opacity = 1.0 if showing else 0.0

        min_width_animation = QPropertyAnimation(self._menu_panel, b"minimumWidth", self)
        min_width_animation.setStartValue(start_width)
        min_width_animation.setEndValue(end_width)
        min_width_animation.setDuration(MENU_ANIMATION_MS)
        min_width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        max_width_animation = QPropertyAnimation(self._menu_panel, b"maximumWidth", self)
        max_width_animation.setStartValue(start_width)
        max_width_animation.setEndValue(end_width)
        max_width_animation.setDuration(MENU_ANIMATION_MS)
        max_width_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        opacity_animation = QPropertyAnimation(self._menu_effect, b"opacity", self)
        opacity_animation.setStartValue(start_opacity)
        opacity_animation.setEndValue(end_opacity)
        opacity_animation.setDuration(MENU_ANIMATION_MS)
        opacity_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        animation = QParallelAnimationGroup(self)
        animation.addAnimation(min_width_animation)
        animation.addAnimation(max_width_animation)
        animation.addAnimation(opacity_animation)
        animation.finished.connect(lambda: self._finish_menu_animation(showing))
        self._menu_animation = animation
        animation.start()

    def _finish_menu_animation(self, showing: bool) -> None:
        if self._menu_panel is None:
            return
        if showing:
            self._menu_panel.setMinimumWidth(MENU_WIDTH)
            self._menu_panel.setMaximumWidth(MENU_WIDTH)
            self._menu_panel.show()
        else:
            self._menu_panel.hide()
            self._menu_panel.setMinimumWidth(0)
            self._menu_panel.setMaximumWidth(0)

    def _select_section(self, index: int) -> None:
        if self._section_stack is not None:
            self._section_stack.setCurrentIndex(index)

    def _build_section_page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("SectionPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)
        return page, layout

    def _build_model_group(self) -> QWidget:
        group, layout = self._build_section_page("模型配置")
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
        layout.addStretch(1)
        return group

    def _build_preset_group(self) -> QWidget:
        group, layout = self._build_section_page("人设设置")
        layout.addWidget(self._build_field(
            "人设提示词",
            self._personality_edit,
            "留空保存会使用默认人设。",
        ))
        layout.addStretch(1)
        return group

    def _build_chat_group(self) -> QWidget:
        group, layout = self._build_section_page("多轮对话")
        layout.addWidget(self._multi_turn_enabled_check)
        layout.addWidget(self._build_field(
            "记忆轮数",
            self._build_memory_turns_row(),
            "保留本次运行期间最近的主动聊天和被动观察；关闭应用后会清空。",
        ))
        layout.addStretch(1)
        return group

    def _build_observer_group(self) -> QWidget:
        group, layout = self._build_section_page("全局监听")
        layout.addWidget(self._observation_enabled_check)
        layout.addWidget(self._build_field(
            "监听间隔",
            self._build_interval_row(),
            "开启后会按间隔观察当前前台窗口，不再按窗口标题或 IDE 关键词过滤。",
        ))
        layout.addStretch(1)
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

        decrease_button = QPushButton("-")
        increase_button = QPushButton("+")
        for button, delta in (
            (decrease_button, -1),
            (increase_button, 1),
        ):
            button.setObjectName("StepButton")
            button.setFixedSize(34, 34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip("增加 1 秒" if delta > 0 else "减少 1 秒")
            button.clicked.connect(lambda _checked=False, step=delta: self._step_interval(step))

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(self._interval_edit, 1)
        layout.addWidget(seconds_label)
        layout.addWidget(decrease_button)
        layout.addWidget(increase_button)
        return row

    def _build_memory_turns_row(self) -> QWidget:
        unit_label = QLabel("轮")
        unit_label.setObjectName("MemoryTurnsUnit")

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._memory_turns_edit, 1)
        layout.addWidget(unit_label)
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

    def _memory_turns(self) -> int:
        raw_value = self._memory_turns_edit.text().strip()
        if not raw_value:
            raise ValueError("记忆轮数不能为空。")
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ValueError("记忆轮数必须是数字。") from exc

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
        if settings.memory_turns < MEMORY_TURNS_MIN:
            raise ValueError("记忆轮数不能小于 1 轮。")
        if settings.memory_turns > MEMORY_TURNS_MAX:
            raise ValueError("记忆轮数不能大于 20 轮。")
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
            QWidget#SectionPage {
                background: #ffffff;
                border: 1px solid #bfd7ff;
                border-radius: 8px;
            }
            QLabel#SectionTitle {
                color: #1d4ed8;
                font-size: 15px;
                font-weight: 700;
                padding-bottom: 2px;
            }
            QWidget#MenuPanel {
                background: #ffffff;
                border: 1px solid #bfd7ff;
                border-radius: 8px;
            }
            QStackedWidget#SectionStack {
                background: transparent;
            }
            QLineEdit,
            QLineEdit#IntervalInput,
            QLineEdit#MemoryTurnsInput,
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
            QLineEdit#MemoryTurnsInput:focus,
            QPlainTextEdit#PersonalityInput:focus {
                border: 1px solid #2563eb;
            }
            QLabel#IntervalUnit {
                color: #1e385f;
                padding: 0 2px;
            }
            QLabel#MemoryTurnsUnit {
                color: #1e385f;
                padding: 0 2px;
            }
            QCheckBox {
                color: #1e385f;
                spacing: 8px;
                font-weight: 600;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #7aa7e8;
                background: #f7fbff;
            }
            QCheckBox::indicator:hover {
                border: 1px solid #2563eb;
                background: #eaf2ff;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #2563eb;
                background: #2563eb;
                image: none;
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
            QPushButton#MenuToggleButton {
                background: #ffffff;
                border: 1px solid #b7d4ff;
                color: #1d4ed8;
                font-size: 18px;
                padding: 0;
                min-width: 38px;
            }
            QPushButton#MenuToggleButton:hover {
                background: #eaf2ff;
            }
            QPushButton#SectionButton {
                background: transparent;
                border: none;
                color: #1e385f;
                padding: 9px 10px;
                text-align: left;
                min-width: 0;
            }
            QPushButton#SectionButton:hover {
                background: #eef6ff;
                color: #1d4ed8;
            }
            QPushButton#SectionButton:checked {
                background: #dbeafe;
                color: #0f3f8c;
            }
            QPushButton#StepButton {
                background: #ffffff;
                border: 1px solid #b7d4ff;
                border-radius: 6px;
                color: #1d4ed8;
                font-size: 16px;
                font-weight: 700;
                padding: 0;
                min-width: 34px;
            }
            QPushButton#StepButton:hover {
                background: #eaf2ff;
                border-color: #60a5fa;
            }
            QPushButton#StepButton:pressed {
                background: #dbeafe;
                border-color: #2563eb;
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
