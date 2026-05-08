from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config_loader import AppConfig, CoreSettings, core_settings_from_config


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("CodingPet 设置")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMinimumHeight(430)

        settings = core_settings_from_config(config)
        self._base_url_edit = QLineEdit(settings.base_url)
        self._api_key_edit = QLineEdit(settings.api_key)
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._vision_model_edit = QLineEdit(settings.vision_model_name)
        self._chat_model_edit = QLineEdit(settings.chat_model_name)
        self._observation_enabled_check = QCheckBox("开启全局监听")
        self._observation_enabled_check.setChecked(settings.global_observation_enabled)
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(5, 86400)
        self._interval_spin.setSuffix(" 秒")
        self._interval_spin.setValue(settings.interval_seconds)

        self._build_layout()
        self._apply_style()

    def core_settings(self) -> CoreSettings:
        return CoreSettings(
            base_url=self._base_url_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            vision_model_name=self._vision_model_edit.text().strip(),
            chat_model_name=self._chat_model_edit.text().strip(),
            global_observation_enabled=self._observation_enabled_check.isChecked(),
            interval_seconds=self._interval_spin.value(),
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
        subtitle = QLabel("配置模型和全局监听，保存后会立即应用到新的聊天和观察任务。")
        subtitle.setObjectName("DialogSubtitle")
        subtitle.setWordWrap(True)

        model_group = QGroupBox("模型配置")
        model_form = QFormLayout(model_group)
        model_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        model_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        model_form.setHorizontalSpacing(14)
        model_form.setVerticalSpacing(12)
        model_form.addRow("接口地址", self._base_url_edit)
        model_form.addRow("API Key", self._build_api_key_row())
        model_form.addRow("", self._build_field_hint("留空可以保存，但模型请求仍需要有效 API Key。"))
        model_form.addRow("视觉模型", self._vision_model_edit)
        model_form.addRow("聊天模型", self._chat_model_edit)

        observer_group = QGroupBox("全局监听")
        observer_form = QFormLayout(observer_group)
        observer_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        observer_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        observer_form.setHorizontalSpacing(14)
        observer_form.setVerticalSpacing(12)
        observer_form.addRow("", self._observation_enabled_check)
        observer_form.addRow("监听间隔", self._interval_spin)
        observer_form.addRow("", self._build_field_hint("开启后会按间隔观察当前前台窗口，不再按窗口标题或 IDE 关键词过滤。"))

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
        layout.addWidget(observer_group)
        layout.addStretch(1)
        layout.addWidget(self._buttons)

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

    def _build_field_hint(self, text: str) -> QLabel:
        hint = QLabel(text)
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        return hint

    def _toggle_api_key_visibility(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._api_key_edit.setEchoMode(mode)

    def _validate_settings(self, settings: CoreSettings) -> None:
        if not settings.base_url:
            raise ValueError("接口地址不能为空。")
        if not settings.vision_model_name:
            raise ValueError("视觉模型不能为空。")
        if not settings.chat_model_name:
            raise ValueError("聊天模型不能为空。")
        if settings.interval_seconds < 5:
            raise ValueError("监听间隔不能小于 5 秒。")

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
            QSpinBox {
                background: #ffffff;
                border: 1px solid #b7d4ff;
                border-radius: 6px;
                color: #102033;
                selection-background-color: #3b82f6;
                padding: 7px 9px;
            }
            QLineEdit:focus,
            QSpinBox:focus {
                border: 1px solid #2563eb;
            }
            QCheckBox {
                color: #1e385f;
                spacing: 8px;
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
