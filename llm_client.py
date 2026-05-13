from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from threading import Lock
from typing import Any, Sequence

from openai import BadRequestError, NotFoundError, OpenAI

from config_loader import AppConfig
from conversation_history import ChatTurn
from logging_utils import LOGGER_NAME
from pet_state import PetState


@dataclass(frozen=True)
class ModelReply:
    # 所有模型回复最终都会归一成“展示文本 + 宠物情绪状态”。
    message: str
    emotion: PetState


# 提示词要求模型输出 [STATE] 前缀，这里预先拼出合法状态集合并准备解析正则。
STATE_NAMES = "|".join(state.name for state in PetState)
STATE_PREFIX_PATTERN = re.compile(r"^\s*\[([A-Z_]+)\]\s*(.*)$", flags=re.IGNORECASE | re.DOTALL)
_CLIENT_CACHE_LOCK = Lock()
_CLIENT_CACHE: dict[tuple[str, str, float], OpenAI] = {}


def generate_chat_reply(
    config: AppConfig,
    user_text: str,
    screenshot_base64: str | None = None,
    history_turns: Sequence[ChatTurn] | None = None,
) -> ModelReply:
    # 主动聊天会根据是否有截图自动选择聊天模型或视觉模型。
    client = _build_client(
        base_url=config.llm.base_url,
        api_key=config.llm.api_key,
        timeout_seconds=config.runtime.request_timeout_seconds,
    )
    active_history = _active_chat_history(config, history_turns)
    messages = _build_chat_messages(config, user_text, screenshot_base64, active_history)
    try:
        response = client.chat.completions.create(
            model=_chat_model_for_request(config, screenshot_base64),
            temperature=0.8,
            messages=messages,
        )
    except (BadRequestError, NotFoundError) as exc:
        # 有些 OpenAI 兼容端点会把 image_url 当作不支持的能力直接拒绝。
        # 主动聊天允许降级成纯文本重试，避免用户因为截图失败完全收不到回复。
        if not screenshot_base64 or not _is_unsupported_image_error(exc):
            raise

        logging.getLogger(LOGGER_NAME).warning(
            "当前配置的 LLM 端点不支持图像输入，主动聊天将降级为纯文本重试。"
        )
        response = client.chat.completions.create(
            model=config.llm.chat_model_name,
            temperature=0.8,
            messages=_build_chat_messages(config, user_text, None, active_history),
        )
    raw_text = _extract_chat_text(response)
    return parse_model_reply(raw_text, fallback_message="抱歉，我没读懂这次回复。")


def analyze_screenshot(config: AppConfig, screenshot_base64: str, window_title: str) -> ModelReply:
    # 被动观察必须走视觉模型，因为它的输入就是当前窗口截图。
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
                    "你是 CodingPet，一个安静观察前台窗口的桌面编程伙伴。"
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
                            "请分析这张截图里的当前前台窗口内容。"
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
    # 这里显式禁止空 base_url / api_key，让错误尽早暴露在本地。
    normalized_base_url = base_url.strip()
    normalized_api_key = api_key.strip()
    normalized_timeout = float(timeout_seconds)
    if not normalized_base_url:
        raise ValueError("缺少 base_url")
    if not normalized_api_key:
        raise ValueError("缺少 api_key")
    cache_key = (normalized_base_url, normalized_api_key, normalized_timeout)
    with _CLIENT_CACHE_LOCK:
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            client = OpenAI(
                base_url=normalized_base_url,
                api_key=normalized_api_key,
                timeout=normalized_timeout,
                max_retries=0,
            )
            _CLIENT_CACHE[cache_key] = client
        return client


def close_cached_clients() -> None:
    # 退出应用时关闭底层 HTTP 连接池，避免 OpenAI SDK 的连接资源拖住进程。
    with _CLIENT_CACHE_LOCK:
        clients = list(_CLIENT_CACHE.values())
        _CLIENT_CACHE.clear()

    for client in clients:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _chat_model_for_request(config: AppConfig, screenshot_base64: str | None) -> str:
    # 只要有截图，就优先使用视觉模型；没有截图才用纯文本聊天模型。
    if screenshot_base64:
        return config.llm.vision_model_name
    return config.llm.chat_model_name


def _build_chat_messages(
    config: AppConfig,
    user_text: str,
    screenshot_base64: str | None,
    history_turns: Sequence[ChatTurn] | None = None,
) -> list[dict[str, Any]]:
    # messages 按 system -> 历史对话 -> 本轮用户输入的顺序构造。
    messages: list[dict[str, Any]] = [
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
        }
    ]
    for turn in history_turns or ():
        # 历史中可能包含被动观察记录，这里仍按用户/助手轮次灌给模型，
        # 让模型能理解此前发生过什么。
        user = turn.user.strip()
        assistant = turn.assistant.strip()
        if user:
            messages.append({"role": "user", "content": user})
        if assistant:
            messages.append({"role": "assistant", "content": assistant})

    messages.append({"role": "user", "content": _build_user_content(user_text, screenshot_base64)})
    return messages


def _active_chat_history(
    config: AppConfig,
    history_turns: Sequence[ChatTurn] | None,
) -> tuple[ChatTurn, ...]:
    # 多轮关闭时完全不传历史；开启时只截取最近 N 条，避免 prompt 过长。
    if not config.chat.multi_turn_enabled or not history_turns:
        return ()
    return tuple(history_turns)[-config.chat.memory_turns:]


def _build_user_content(user_text: str, screenshot_base64: str | None) -> str | list[dict[str, Any]]:
    text = user_text.strip()
    if not screenshot_base64:
        return text

    # OpenAI 兼容接口的多模态消息需要把文本和 image_url 放进同一个 content 数组。
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
    # 不同 provider 的错误文本不统一，只能用几个常见关键词做宽松判断。
    text = str(exc).lower()
    return (
        "image input" in text
        or "image_url" in text
        or "vision" in text
        or "multimodal" in text
    )


def _extract_chat_text(response: Any) -> str:
    # SDK 响应对象在不同兼容端点上可能略有差异，先按 choices/message/content 逐层取。
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("聊天补全响应未包含 choices")
    message = getattr(choices[0], "message", None)
    if message is None:
        raise ValueError("聊天补全响应未包含 message")
    return _coerce_message_content(getattr(message, "content", None))


def _coerce_message_content(content: Any) -> str:
    # 有些端点返回字符串，有些返回分段 content；统一压成普通文本。
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
    # 主格式是 [STATE] message；如果模型没守格式，再尽量兼容 JSON 或纯文本。
    cleaned = _strip_code_fences(raw_text)
    if not cleaned:
        return ModelReply(message=fallback_message, emotion=PetState.IDLE)

    match = STATE_PREFIX_PATTERN.match(cleaned)
    if match:
        # 严格匹配到合法状态时用对应情绪，否则只取消息并回退到 IDLE。
        state_token = match.group(1).strip().upper()
        emotion = PetState.__members__.get(state_token)
        message = match.group(2).strip() or cleaned
        if emotion is not None:
            return ModelReply(message=message, emotion=emotion)
        return ModelReply(message=message, emotion=PetState.IDLE)

    if cleaned.startswith("{") and cleaned.endswith("}"):
        # 兼容模型偶尔输出 JSON 的情况，减少一次格式漂移造成的坏体验。
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
    # 模型有时会自作主张包一层代码块，这里先剥掉外壳再解析。
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    return candidate.strip()
