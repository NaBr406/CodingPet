from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    vision_model_name: str
    chat_model_name: str


@dataclass(frozen=True)
class ImageGenConfig:
    base_url: str
    api_key: str
    model_name: str


@dataclass(frozen=True)
class PetPresetConfig:
    appearance_prompt: str
    personality_prompt: str


@dataclass(frozen=True)
class ObserverConfig:
    enabled: bool
    interval_seconds: int
    ide_keywords: tuple[str, ...]


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
    image_gen: ImageGenConfig
    pet_preset: PetPresetConfig
    observer: ObserverConfig
    runtime: RuntimeConfig

    @property
    def assets_dir(self) -> Path:
        return self.project_dir / "assets"


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    llm_raw = _read_section(raw, "llm")
    image_gen_raw = _read_section(raw, "image_gen")
    preset_raw = _read_section(raw, "pet_preset")
    observer_raw = raw.get("observer") or {}
    runtime_raw = raw.get("runtime") or {}

    llm = LLMConfig(
        base_url=_require_str(llm_raw, "llm.base_url"),
        api_key=_require_str(llm_raw, "llm.api_key", allow_empty=True),
        vision_model_name=_require_str(llm_raw, "llm.vision_model_name"),
        chat_model_name=_require_str(llm_raw, "llm.chat_model_name"),
    )
    image_gen = ImageGenConfig(
        base_url=_require_str(image_gen_raw, "image_gen.base_url"),
        api_key=_require_str(image_gen_raw, "image_gen.api_key", allow_empty=True),
        model_name=_require_str(image_gen_raw, "image_gen.model_name"),
    )
    preset = PetPresetConfig(
        appearance_prompt=_require_str(preset_raw, "pet_preset.appearance_prompt"),
        personality_prompt=_require_str(preset_raw, "pet_preset.personality_prompt"),
    )
    observer = ObserverConfig(
        enabled=bool(observer_raw.get("enabled", True)),
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
        image_gen=image_gen,
        pet_preset=preset,
        observer=observer,
        runtime=runtime,
    )


def _read_section(raw: dict[str, Any], section_name: str) -> dict[str, Any]:
    section = raw.get(section_name)
    if not isinstance(section, dict):
        raise ConfigError(f"Missing config section: {section_name}")
    return section


def _require_str(section: dict[str, Any], field_name: str, allow_empty: bool = False) -> str:
    key = field_name.split(".")[-1]
    value = section.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"Invalid or missing config value: {field_name}")
    if not allow_empty and not value.strip():
        raise ConfigError(f"Empty config value: {field_name}")
    return value.strip()


def _string_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return default
    if not isinstance(value, list):
        raise ConfigError("observer.ide_keywords must be a list of strings")
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return normalized or default
