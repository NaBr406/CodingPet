from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any

import yaml


APP_NAME = "CodingPet"
DEFAULT_CONFIG_FILENAME = "config.yaml"
DEFAULT_PERSONALITY_PROMPT = "一个嘴毒但靠谱的资深工程师，能快速指出坏代码的问题，并给出有用建议"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    vision_model_name: str
    chat_model_name: str


@dataclass(frozen=True)
class PetPresetConfig:
    personality_prompt: str


@dataclass(frozen=True)
class ChatConfig:
    multi_turn_enabled: bool
    memory_turns: int


@dataclass(frozen=True)
class ObserverConfig:
    global_observation_enabled: bool
    interval_seconds: int
    ide_keywords: tuple[str, ...]


@dataclass(frozen=True)
class CoreSettings:
    base_url: str
    api_key: str
    vision_model_name: str
    chat_model_name: str
    personality_prompt: str
    multi_turn_enabled: bool
    memory_turns: int
    global_observation_enabled: bool
    interval_seconds: int


@dataclass(frozen=True)
class RuntimeConfig:
    request_timeout_seconds: float
    message_duration_ms: int
    state_reset_ms: int
    random_mood_enabled: bool
    random_mood_min_seconds: int
    random_mood_max_seconds: int
    sprite_size: int
    sprite_min_size: int
    sprite_max_size: int


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    project_dir: Path
    llm: LLMConfig
    pet_preset: PetPresetConfig
    chat: ChatConfig
    observer: ObserverConfig
    runtime: RuntimeConfig

    @property
    def assets_dir(self) -> Path:
        bundled_assets_dir = resource_path("assets")
        if bundled_assets_dir.exists():
            return bundled_assets_dir
        return self.project_dir / "assets"


def load_config(path: str | Path = DEFAULT_CONFIG_FILENAME) -> AppConfig:
    config_path = _resolve_app_path(path)
    if not config_path.exists():
        _write_default_config(config_path, path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    raw = _load_yaml_mapping(config_path)

    llm_raw = _read_section(raw, "llm")
    preset_raw = _optional_section(raw, "pet_preset")
    chat_raw = _optional_section(raw, "chat")
    observer_raw = raw.get("observer") or {}
    runtime_raw = raw.get("runtime") or {}

    llm = LLMConfig(
        base_url=_require_str(llm_raw, "llm.base_url"),
        api_key=_require_str(llm_raw, "llm.api_key", allow_empty=True),
        vision_model_name=_require_str(llm_raw, "llm.vision_model_name"),
        chat_model_name=_require_str(llm_raw, "llm.chat_model_name"),
    )
    preset = PetPresetConfig(
        personality_prompt=_optional_str(
            preset_raw,
            "personality_prompt",
            DEFAULT_PERSONALITY_PROMPT,
        ),
    )
    chat = ChatConfig(
        multi_turn_enabled=_bool_value(
            chat_raw.get("multi_turn_enabled", False),
            "chat.multi_turn_enabled",
        ),
        memory_turns=max(1, min(20, int(chat_raw.get("memory_turns", 5)))),
    )
    observer = ObserverConfig(
        global_observation_enabled=_observer_enabled(observer_raw),
        interval_seconds=max(5, int(observer_raw.get("interval_seconds", 300))),
        ide_keywords=tuple(_string_list(observer_raw.get("ide_keywords"), default=[
            "Code",
            "Cursor",
            "IDEA",
            "PyCharm",
            "Visual Studio",
        ])),
    )
    runtime = RuntimeConfig(
        request_timeout_seconds=max(5.0, float(runtime_raw.get("request_timeout_seconds", 20.0))),
        message_duration_ms=max(1000, int(runtime_raw.get("message_duration_ms", 7000))),
        state_reset_ms=max(1000, int(runtime_raw.get("state_reset_ms", 6000))),
        random_mood_enabled=bool(runtime_raw.get("random_mood_enabled", True)),
        random_mood_min_seconds=max(3, int(runtime_raw.get("random_mood_min_seconds", 8))),
        random_mood_max_seconds=max(
            max(3, int(runtime_raw.get("random_mood_min_seconds", 8))),
            int(runtime_raw.get("random_mood_max_seconds", 20)),
        ),
        sprite_size=max(120, int(runtime_raw.get("sprite_size", 300))),
        sprite_min_size=max(80, int(runtime_raw.get("sprite_min_size", 160))),
        sprite_max_size=max(240, int(runtime_raw.get("sprite_max_size", 560))),
    )

    return AppConfig(
        config_path=config_path,
        project_dir=config_path.parent,
        llm=llm,
        pet_preset=preset,
        chat=chat,
        observer=observer,
        runtime=runtime,
    )


def core_settings_from_config(config: AppConfig) -> CoreSettings:
    return CoreSettings(
        base_url=config.llm.base_url,
        api_key=config.llm.api_key,
        vision_model_name=config.llm.vision_model_name,
        chat_model_name=config.llm.chat_model_name,
        personality_prompt=config.pet_preset.personality_prompt,
        multi_turn_enabled=config.chat.multi_turn_enabled,
        memory_turns=config.chat.memory_turns,
        global_observation_enabled=config.observer.global_observation_enabled,
        interval_seconds=config.observer.interval_seconds,
    )


def save_core_settings(path: str | Path, settings: CoreSettings) -> None:
    config_path = _resolve_app_path(path)
    if config_path.exists():
        raw = _load_yaml_mapping(config_path)
    else:
        default_config_path = resource_path("config.example.yaml")
        raw = _load_yaml_mapping(default_config_path) if default_config_path.exists() else {}

    llm_raw = _ensure_section(raw, "llm")
    preset_raw = _ensure_section(raw, "pet_preset")
    chat_raw = _ensure_section(raw, "chat")
    observer_raw = _ensure_section(raw, "observer")

    base_url = _clean_required_text(settings.base_url, "llm.base_url")
    vision_model_name = _clean_required_text(settings.vision_model_name, "llm.vision_model_name")
    chat_model_name = _clean_required_text(settings.chat_model_name, "llm.chat_model_name")
    personality_prompt = settings.personality_prompt.strip() or DEFAULT_PERSONALITY_PROMPT
    api_key = settings.api_key.strip()
    memory_turns = max(1, min(20, int(settings.memory_turns)))
    interval_seconds = max(5, int(settings.interval_seconds))

    llm_raw["base_url"] = base_url
    llm_raw["api_key"] = api_key
    llm_raw["vision_model_name"] = vision_model_name
    llm_raw["chat_model_name"] = chat_model_name
    preset_raw["personality_prompt"] = personality_prompt
    chat_raw["multi_turn_enabled"] = bool(settings.multi_turn_enabled)
    chat_raw["memory_turns"] = memory_turns
    observer_raw["global_observation_enabled"] = bool(settings.global_observation_enabled)
    observer_raw["interval_seconds"] = interval_seconds

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(raw, handle, allow_unicode=True, sort_keys=False)


def _read_section(raw: dict[str, Any], section_name: str) -> dict[str, Any]:
    section = raw.get(section_name)
    if not isinstance(section, dict):
        raise ConfigError(f"Missing config section: {section_name}")
    return section


def _ensure_section(raw: dict[str, Any], section_name: str) -> dict[str, Any]:
    section = raw.get(section_name)
    if section is None:
        section = {}
        raw[section_name] = section
    if not isinstance(section, dict):
        raise ConfigError(f"Invalid config section: {section_name}")
    return section


def _optional_section(raw: dict[str, Any], section_name: str) -> dict[str, Any]:
    section = raw.get(section_name)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigError(f"Invalid config section: {section_name}")
    return section


def _require_str(section: dict[str, Any], field_name: str, allow_empty: bool = False) -> str:
    key = field_name.split(".")[-1]
    value = section.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"Invalid or missing config value: {field_name}")
    if not allow_empty and not value.strip():
        raise ConfigError(f"Empty config value: {field_name}")
    return value.strip()


def _optional_str(section: dict[str, Any], key: str, default: str) -> str:
    value = section.get(key)
    if not isinstance(value, str):
        return default
    normalized = value.strip()
    return normalized or default


def _clean_required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ConfigError(f"Empty config value: {field_name}")
    return normalized


def _string_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return default
    if not isinstance(value, list):
        raise ConfigError("observer.ide_keywords must be a list of strings")
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return normalized or default


def _observer_enabled(observer_raw: dict[str, Any]) -> bool:
    if "global_observation_enabled" in observer_raw:
        return _bool_value(observer_raw["global_observation_enabled"], "observer.global_observation_enabled")
    return _bool_value(observer_raw.get("enabled", True), "observer.enabled")


def _bool_value(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "1"}:
            return True
        if lowered in {"false", "no", "off", "0"}:
            return False
    raise ConfigError(f"Invalid boolean config value: {field_name}")


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ConfigError("Config file root must be a mapping")
    return raw


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_NAME
    return Path.home() / "AppData" / "Roaming" / APP_NAME


def user_config_path() -> Path:
    return user_config_dir() / DEFAULT_CONFIG_FILENAME


def resource_path(relative_path: str | Path) -> Path:
    base_dir = Path(getattr(sys, "_MEIPASS", application_dir()))
    return base_dir / relative_path


def _resolve_app_path(path: str | Path) -> Path:
    config_path = Path(path).expanduser()
    if not config_path.is_absolute():
        if _is_default_config_request(config_path) and getattr(sys, "frozen", False):
            config_path = user_config_path()
        else:
            config_path = application_dir() / config_path
    return config_path.resolve()


def _bundled_default_config_path(requested_path: str | Path) -> Path | None:
    requested = Path(requested_path)
    if not _is_default_config_request(requested):
        return None

    candidate = resource_path("config.example.yaml")
    if candidate.exists():
        return candidate
    return None


def _write_default_config(config_path: Path, requested_path: str | Path) -> None:
    default_config_path = _bundled_default_config_path(requested_path)
    if default_config_path is None:
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(default_config_path.read_text(encoding="utf-8"), encoding="utf-8")


def _is_default_config_request(path: Path) -> bool:
    return path.name == DEFAULT_CONFIG_FILENAME and str(path.parent) in {"", "."}
