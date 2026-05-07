from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from openai import BadRequestError, NotFoundError, OpenAI

from config_loader import AppConfig
from logging_utils import LOGGER_NAME
from pet_state import PetState


@dataclass(frozen=True)
class ModelReply:
    message: str
    emotion: PetState


STATE_NAMES = "|".join(state.name for state in PetState)
STATE_PREFIX_PATTERN = re.compile(r"^\s*\[([A-Z_]+)\]\s*(.*)$", flags=re.IGNORECASE | re.DOTALL)


def generate_chat_reply(
    config: AppConfig,
    user_text: str,
    screenshot_base64: str | None = None,
) -> ModelReply:
    client = _build_client(
        base_url=config.llm.base_url,
        api_key=config.llm.api_key,
        timeout_seconds=config.runtime.request_timeout_seconds,
    )
    messages = _build_chat_messages(config, user_text, screenshot_base64)
    try:
        response = client.chat.completions.create(
            model=_chat_model_for_request(config, screenshot_base64),
            temperature=0.8,
            messages=messages,
        )
    except (BadRequestError, NotFoundError) as exc:
        if not screenshot_base64 or not _is_unsupported_image_error(exc):
            raise

        logging.getLogger(LOGGER_NAME).warning(
            "当前配置的 LLM 端点不支持图像输入，主动聊天将降级为纯文本重试。"
        )
        response = client.chat.completions.create(
            model=config.llm.chat_model_name,
            temperature=0.8,
            messages=_build_chat_messages(config, user_text, None),
        )
    raw_text = _extract_chat_text(response)
    return parse_model_reply(raw_text, fallback_message="抱歉，我没读懂这次回复。")


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
                    "你是 CodingPet，一个安静观察代码的桌面编程伙伴。"
                    f"请始终保持人设：{config.pet_preset.personality_prompt}。"
                    "请分析截图，判断用户正在做什么，并主动给出简短评价。"
                    "请严格只输出一行，格式必须是：[STATE] 一句简短吐槽或建议。"
                    f"只允许使用这些状态：{STATE_NAMES}。"
                    "不要输出 JSON、Markdown 或额外说明。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "请分析这张截图里的代码或 IDE 状态。"
                            f"当前活动窗口标题：{window_title}。"
                            "请用人设说一句简短的主动评论。"
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
    return parse_model_reply(raw_text, fallback_message="抱歉，我没读懂这次回复。")


def _build_client(base_url: str, api_key: str, timeout_seconds: float) -> OpenAI:
    if not base_url.strip():
        raise ValueError("缺少 base_url")
    if not api_key.strip():
        raise ValueError("缺少 api_key")
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout_seconds,
        max_retries=0,
    )


def _chat_model_for_request(config: AppConfig, screenshot_base64: str | None) -> str:
    if screenshot_base64:
        return config.llm.vision_model_name
    return config.llm.chat_model_name


def _build_chat_messages(
    config: AppConfig,
    user_text: str,
    screenshot_base64: str | None,
) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "你是 CodingPet，一个悬浮在桌面上的编程伙伴。"
                f"请始终保持人设：{config.pet_preset.personality_prompt}。"
                "请严格只输出一行，格式必须是：[STATE] 消息内容。"
                f"只允许使用这些状态：{STATE_NAMES}。"
                "如果截图对回答有帮助，请结合截图内容。"
                "不要输出 JSON、Markdown 或额外说明。"
            ),
        },
        {"role": "user", "content": _build_user_content(user_text, screenshot_base64)},
    ]


def _build_user_content(user_text: str, screenshot_base64: str | None) -> str | list[dict[str, Any]]:
    text = user_text.strip()
    if not screenshot_base64:
        return text

    return [
        {
            "type": "text",
            "text": (
                "用户消息："
                f"{text}\n\n"
                "已附上当前屏幕截图，请结合可见代码、报错或 IDE 状态进行回答。"
            ),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{screenshot_base64}",
            },
        },
    ]


def _is_unsupported_image_error(exc: BadRequestError | NotFoundError) -> bool:
    text = str(exc).lower()
    return (
        "image input" in text
        or "image_url" in text
        or "vision" in text
        or "multimodal" in text
    )


def _extract_chat_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("聊天补全响应未包含 choices")
    message = getattr(choices[0], "message", None)
    if message is None:
        raise ValueError("聊天补全响应未包含 message")
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
    if not cleaned:
        return ModelReply(message=fallback_message, emotion=PetState.IDLE)

    match = STATE_PREFIX_PATTERN.match(cleaned)
    if match:
        state_token = match.group(1).strip().upper()
        emotion = PetState.__members__.get(state_token)
        message = match.group(2).strip() or cleaned
        if emotion is not None:
            return ModelReply(message=message, emotion=emotion)
        return ModelReply(message=message, emotion=PetState.IDLE)

    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(payload, dict):
                message = str(
                    payload.get("message")
                    or payload.get("reply")
                    or payload.get("text")
                    or cleaned
                ).strip()
                emotion = PetState.from_emotion(str(payload.get("emotion") or payload.get("sentiment")))
                return ModelReply(message=message or cleaned, emotion=emotion)

    return ModelReply(message=cleaned, emotion=PetState.IDLE)


def _strip_code_fences(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    return candidate.strip()
