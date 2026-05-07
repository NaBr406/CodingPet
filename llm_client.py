from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from config_loader import AppConfig
from pet_state import PetState


@dataclass(frozen=True)
class ModelReply:
    message: str
    emotion: PetState


STATE_NAMES = "|".join(state.name for state in PetState)
STATE_PREFIX_PATTERN = re.compile(r"^\s*\[([A-Z_]+)\]\s*(.*)$", flags=re.IGNORECASE | re.DOTALL)


def generate_chat_reply(config: AppConfig, user_text: str) -> ModelReply:
    client = _build_client(
        base_url=config.llm.base_url,
        api_key=config.llm.api_key,
        timeout_seconds=config.runtime.request_timeout_seconds,
    )
    response = client.chat.completions.create(
        model=config.llm.chat_model_name,
        temperature=0.8,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are CodingPet, a floating desktop coding companion. "
                    f"Stay in character: {config.pet_preset.personality_prompt} "
                    "Reply with exactly one line in this format: [STATE] message. "
                    f"Use only these states: {STATE_NAMES}. "
                    "Do not use JSON, markdown, or extra commentary."
                ),
            },
            {"role": "user", "content": user_text},
        ],
    )
    raw_text = _extract_chat_text(response)
    return parse_model_reply(raw_text, fallback_message="Still thinking about that.")


def analyze_screenshot(config: AppConfig, screenshot_base64: str, window_title: str) -> ModelReply:
    client = _build_client(
        base_url=config.llm.base_url,
        api_key=config.llm.api_key,
        timeout_seconds=config.runtime.request_timeout_seconds,
    )
    response = client.chat.completions.create(
        model=config.llm.vision_model_name,
        temperature=0.6,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are CodingPet, a desktop coding companion that watches code quietly. "
                    f"Stay in character: {config.pet_preset.personality_prompt} "
                    "Analyze the screenshot, infer what the user is coding, and proactively comment. "
                    "Reply with exactly one line in this format: [STATE] one short roast or tip. "
                    f"Use only these states: {STATE_NAMES}. "
                    "Do not use JSON, markdown, or extra commentary."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Analyze the code or IDE state in this screenshot. "
                            f"Active window title: {window_title}. "
                            "Give one short proactive message in character."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_base64}",
                        },
                    },
                ],
            },
        ],
    )
    raw_text = _extract_chat_text(response)
    return parse_model_reply(raw_text, fallback_message="That code smells unstable.")


def _build_client(base_url: str, api_key: str, timeout_seconds: float) -> OpenAI:
    if not base_url.strip():
        raise ValueError("Missing base_url")
    if not api_key.strip():
        raise ValueError("Missing api_key")
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=0,
    )


def _extract_chat_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("Chat completion response did not include choices")
    message = getattr(choices[0], "message", None)
    if message is None:
        raise ValueError("Chat completion response did not include a message")
    return _coerce_message_content(getattr(message, "content", None))


def _coerce_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


def parse_model_reply(raw_text: str, fallback_message: str) -> ModelReply:
    cleaned = _strip_code_fences(raw_text)
    match = STATE_PREFIX_PATTERN.match(cleaned)
    if not match:
        return ModelReply(message=fallback_message, emotion=PetState.IDLE)

    state_token = match.group(1).strip().upper()
    emotion = PetState.__members__.get(state_token)
    if emotion is None:
        return ModelReply(message=fallback_message, emotion=PetState.IDLE)

    message = match.group(2).strip() or fallback_message
    return ModelReply(message=message, emotion=emotion)


def _strip_code_fences(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    return candidate.strip()
