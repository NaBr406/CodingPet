from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.request import urlopen

from openai import OpenAI

from config_loader import AppConfig
from pet_state import PetState


@dataclass(frozen=True)
class ModelReply:
    message: str
    emotion: PetState


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
                    "Reply with compact JSON only: "
                    '{"message":"short reply","emotion":"IDLE|GREETING|LISTENING|REVIEWING|THINKING|ANGRY|HAPPY|CODING|SLEEPY|CONFUSED|SURPRISED|PROUD|BORED"}'
                ),
            },
            {"role": "user", "content": user_text},
        ],
    )
    raw_text = _extract_chat_text(response)
    return _parse_model_reply(raw_text, fallback_message="Still thinking about that.")


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
                    "Reply with compact JSON only: "
                    '{"message":"one short roast or tip","emotion":"IDLE|LISTENING|REVIEWING|THINKING|ANGRY|HAPPY|CODING|CONFUSED|SURPRISED|PROUD|BORED"}'
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
    return _parse_model_reply(raw_text, fallback_message="That code smells unstable.")


def generate_character_image(config: AppConfig, prompt: str) -> bytes:
    client = _build_client(
        base_url=config.image_gen.base_url,
        api_key=config.image_gen.api_key,
        timeout_seconds=config.runtime.request_timeout_seconds,
    )
    response = client.images.generate(
        model=config.image_gen.model_name,
        prompt=prompt,
    )
    if not getattr(response, "data", None):
        raise ValueError("Image generation response did not include data")

    first_item = response.data[0]
    b64_data = _get_field(first_item, "b64_json")
    if isinstance(b64_data, str) and b64_data.strip():
        return base64.b64decode(b64_data)

    url = _get_field(first_item, "url")
    if isinstance(url, str) and url.strip():
        with urlopen(url, timeout=config.runtime.request_timeout_seconds) as remote_image:
            return remote_image.read()

    raise ValueError("Image generation response did not include b64_json or url")


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


def _parse_model_reply(raw_text: str, fallback_message: str) -> ModelReply:
    cleaned = _strip_code_fences(raw_text)
    if cleaned:
        try:
            payload = json.loads(cleaned)
            if isinstance(payload, dict):
                message = str(
                    payload.get("message")
                    or payload.get("reply")
                    or payload.get("text")
                    or fallback_message
                ).strip()
                emotion = PetState.from_emotion(str(payload.get("emotion") or payload.get("sentiment")))
                return ModelReply(message=message or fallback_message, emotion=emotion)
        except json.JSONDecodeError:
            pass

    emotion_match = re.search(
        r"\b(IDLE|GREETING|LISTENING|REVIEWING|THINKING|ANGRY|HAPPY|CODING|SLEEPY|CONFUSED|SURPRISED|PROUD|BORED)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    emotion = PetState.from_emotion(emotion_match.group(1) if emotion_match else None)
    message = cleaned.strip() or fallback_message
    return ModelReply(message=message, emotion=emotion)


def _strip_code_fences(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    return candidate.strip()


def _get_field(item: Any, field_name: str) -> Any:
    if isinstance(item, dict):
        return item.get(field_name)
    return getattr(item, field_name, None)
