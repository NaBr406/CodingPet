from __future__ import annotations

import base64
import ast
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
STATE_WRAPPED_PREFIX_PATTERN = re.compile(
    r"^\s*[\[【(（]\s*([A-Z0-9_\-\s\u4e00-\u9fff]+)\s*[\]】)）]\s*[:：\-–—]?\s*(.*)$",
    flags=re.IGNORECASE | re.DOTALL,
)
STATE_LABEL_PREFIX_PATTERN = re.compile(
    r"^\s*(?:state|emotion|mood|status|pet_state|状态|情绪|心情)\s*[:：=]\s*([^\n\r,，。;；]+)\s*(.*)$",
    flags=re.IGNORECASE | re.DOTALL,
)
STATE_INLINE_PREFIX_PATTERN = re.compile(
    r"^\s*([A-Z][A-Z0-9_\-\s]{1,32}|[\u4e00-\u9fff]{1,8})\s*[:：\-–—]\s*(.+)$",
    flags=re.IGNORECASE | re.DOTALL,
)
FIELD_LINE_PATTERN = re.compile(
    r"^\s*([A-Z_][A-Z0-9_\-\s]*|[\u4e00-\u9fff]{1,8})\s*[:：=]\s*(.*)$",
    flags=re.IGNORECASE,
)
STATE_FIELD_KEYS = {
    "state",
    "emotion",
    "mood",
    "status",
    "sentiment",
    "pet_state",
    "expression",
    "状态",
    "情绪",
    "心情",
    "表情",
}
MESSAGE_FIELD_KEYS = {
    "message",
    "reply",
    "text",
    "content",
    "response",
    "comment",
    "answer",
    "output",
    "say",
    "消息",
    "回复",
    "内容",
    "文本",
    "评论",
    "建议",
}
JSONISH_START_CHARS = ("{", "[")
PARSE_LOG_TEXT_LIMIT = 500
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
    # 普通被动观察走视觉模型；隐私进程会在 observer_thread 中改走纯文本脱敏路径。
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


def analyze_redacted_observation(config: AppConfig, process_name: str) -> ModelReply:
    # 隐私进程只走文本模型，输入里不包含截图、窗口标题、联系人名或聊天内容。
    safe_process_name = process_name.strip() or "受保护进程"
    client = _build_client(
        base_url=config.llm.base_url,
        api_key=config.llm.api_key,
        timeout_seconds=config.runtime.request_timeout_seconds,
    )
    response = client.chat.completions.create(
        model=config.llm.chat_model_name,
        temperature=0.6,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是 CodingPet，一个安静观察前台窗口的桌面编程伙伴。"
                    f"请始终保持人设：{config.pet_preset.personality_prompt}。"
                    "当前窗口命中隐私保护名单，本轮没有截图、窗口标题、联系人名或聊天内容。"
                    "只能根据进程名做一句很轻的主动评论，不要猜测用户正在和谁聊天或聊天内容。"
                    "请严格只输出一行，格式必须是：[STATE] 一句简短吐槽或建议。"
                    f"只允许使用这些状态：{STATE_NAMES}。"
                    "不要输出 JSON、Markdown 或额外说明。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "隐私脱敏后的当前前台窗口信息只有这一项："
                    f"进程名：{safe_process_name}。"
                    "请基于这个进程名说一句简短主动评论。"
                ),
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
    # 主格式是 [STATE] message；如果模型没守格式，再尽量兼容 JSON、键值行或纯文本。
    cleaned = _strip_code_fences(raw_text)
    if not cleaned:
        return ModelReply(message=fallback_message, emotion=PetState.IDLE)

    for parser in (
        _parse_state_prefixed_reply,
        _parse_json_reply,
        _parse_field_lines_reply,
        _parse_inline_state_reply,
    ):
        parsed = parser(cleaned)
        if parsed is not None:
            return parsed

    _log_unparsed_model_reply(cleaned)
    return ModelReply(message=cleaned, emotion=PetState.IDLE)


def _parse_state_prefixed_reply(text: str) -> ModelReply | None:
    parsed = _parse_state_prefix_candidate(text)
    if parsed is not None:
        return parsed

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        parsed = _parse_state_prefix_candidate(line)
        if parsed is None:
            continue
        if parsed.message == line and index + 1 < len(lines):
            return ModelReply(
                message="\n".join(lines[index + 1:]).strip(),
                emotion=parsed.emotion,
            )
        return parsed
    return None


def _parse_state_prefix_candidate(candidate: str) -> ModelReply | None:
    for pattern in (STATE_PREFIX_PATTERN, STATE_WRAPPED_PREFIX_PATTERN):
        match = pattern.match(candidate)
        if not match:
            continue

        state_token = _normalize_state_token(match.group(1))
        emotion = PetState.resolve_emotion(state_token)

        message = _clean_message_text(match.group(2)) or candidate.strip()
        if emotion is None and state_token != "STATE":
            _log_unknown_state_token(state_token, message)
        return ModelReply(message=message, emotion=emotion or PetState.IDLE)
    return None


def _parse_json_reply(text: str) -> ModelReply | None:
    for candidate in _json_candidates(text):
        payload = _loads_jsonish(candidate)
        parsed = _reply_from_payload(payload)
        if parsed is not None:
            return parsed
    return None


def _json_candidates(text: str) -> list[str]:
    stripped = text.strip()
    candidates: list[str] = []
    if stripped.startswith(JSONISH_START_CHARS):
        candidates.append(stripped)

    # 模型常见漂移是“说明文字 + JSON”，这里只抽第一个平衡的对象或数组。
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        quote = ""
        for index, char in enumerate(stripped[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    in_string = False
                continue
            if char in {"'", '"'}:
                in_string = True
                quote = char
                continue
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : index + 1]
                    if candidate not in candidates:
                        candidates.append(candidate)
                    break
    return candidates


def _loads_jsonish(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    try:
        return ast.literal_eval(candidate)
    except (SyntaxError, ValueError):
        return None


def _reply_from_payload(payload: Any) -> ModelReply | None:
    if isinstance(payload, list):
        for item in payload:
            parsed = _reply_from_payload(item)
            if parsed is not None:
                return parsed
        return None

    if isinstance(payload, str):
        return _parse_state_prefixed_reply(payload) or _parse_inline_state_reply(payload)

    if not isinstance(payload, dict):
        return None

    state_value, message_value = _extract_payload_fields(payload)
    if message_value is not None:
        message_text = _clean_message_value(message_value)
        parsed_message = _parse_state_prefixed_reply(message_text) or _parse_inline_state_reply(message_text)
        if state_value is None and parsed_message is not None:
            return parsed_message
    else:
        message_text = ""

    emotion = PetState.resolve_emotion(_normalize_state_token(state_value))
    if emotion is None and state_value is None:
        for value in payload.values():
            parsed = _reply_from_payload(value)
            if parsed is not None:
                return parsed
        return None

    message = message_text or _compact_json(payload)
    return ModelReply(message=message, emotion=emotion or PetState.IDLE)


def _extract_payload_fields(payload: dict[Any, Any]) -> tuple[Any | None, Any | None]:
    state_value: Any | None = None
    message_value: Any | None = None
    nested_candidates: list[Any] = []

    for key, value in payload.items():
        normalized_key = _normalize_field_key(key)
        if normalized_key in STATE_FIELD_KEYS and state_value is None:
            state_value = value
            continue
        if normalized_key in MESSAGE_FIELD_KEYS and message_value is None:
            message_value = value
            continue
        if isinstance(value, (dict, list, str)):
            nested_candidates.append(value)

    if state_value is None or message_value is None:
        for candidate in nested_candidates:
            nested = _reply_from_payload(candidate)
            if nested is None:
                continue
            if state_value is None:
                state_value = nested.emotion.name
            if message_value is None:
                message_value = nested.message
            break

    return state_value, message_value


def _parse_field_lines_reply(text: str) -> ModelReply | None:
    state_value: str | None = None
    message_parts: list[str] = []
    collecting_message = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        match = FIELD_LINE_PATTERN.match(stripped)
        if match:
            key = _normalize_field_key(match.group(1))
            value = match.group(2).strip()
            if key in STATE_FIELD_KEYS:
                state_value = value
                collecting_message = False
                continue
            if key in MESSAGE_FIELD_KEYS:
                if value:
                    message_parts.append(value)
                collecting_message = True
                continue

            emotion = PetState.resolve_emotion(_normalize_state_token(match.group(1)))
            if emotion is not None and value:
                return ModelReply(message=_clean_message_text(value), emotion=emotion)

        if collecting_message:
            message_parts.append(stripped)

    if state_value is None and not message_parts:
        return None

    emotion = PetState.resolve_emotion(_normalize_state_token(state_value))
    if emotion is None and state_value is not None:
        return None
    message = _clean_message_text("\n".join(message_parts)) or text.strip()
    return ModelReply(message=message, emotion=emotion or PetState.IDLE)


def _parse_inline_state_reply(text: str) -> ModelReply | None:
    for pattern in (STATE_LABEL_PREFIX_PATTERN, STATE_INLINE_PREFIX_PATTERN):
        match = pattern.match(text)
        if not match:
            continue

        state_token = _normalize_state_token(match.group(1))
        emotion = PetState.resolve_emotion(state_token)
        if emotion is None:
            continue

        message = _clean_message_text(match.group(2)) or text.strip()
        message = _strip_leading_message_label(message)
        return ModelReply(message=message or text.strip(), emotion=emotion)
    return None


def _normalize_state_token(value: Any) -> str:
    token = str(value or "").strip()
    token = token.removeprefix("PetState.").strip()
    token = token.strip("[]【】()（）{}\"'` \t\r\n:：,，.。;；")
    token = re.sub(r"[\s\-–—]+", "_", token)
    return token.upper() if token.isascii() else token.replace("_", "")


def _normalize_field_key(value: Any) -> str:
    key = str(value or "").strip().strip("\"'`[]【】()（）")
    key = re.sub(r"[\s\-]+", "_", key)
    return key.lower()


def _clean_message_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_message_text(value)
    if isinstance(value, list):
        parts = [_clean_message_value(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        nested = _reply_from_payload(value)
        if nested is not None:
            return nested.message
        return _compact_json(value)
    return _clean_message_text(str(value))


def _clean_message_text(text: str) -> str:
    cleaned = _strip_code_fences(str(text))
    cleaned = _strip_leading_message_label(cleaned)
    return cleaned.strip().strip("\"'`")


def _strip_leading_message_label(text: str) -> str:
    return re.sub(
        r"^\s*(?:message|reply|text|content|response|comment|answer|消息|回复|内容|文本|评论|建议)\s*[:：=]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _compact_json(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        return str(payload)


def _log_unparsed_model_reply(text: str) -> None:
    preview = re.sub(r"\s+", " ", text).strip()
    if len(preview) > PARSE_LOG_TEXT_LIMIT:
        preview = f"{preview[:PARSE_LOG_TEXT_LIMIT]}..."
    logging.getLogger(LOGGER_NAME).warning(
        "LLM 回复未匹配状态协议，已按纯文本和 IDLE 处理。原始回复片段：%s",
        preview,
    )


def _log_unknown_state_token(state_token: str, message: str) -> None:
    preview = re.sub(r"\s+", " ", message).strip()
    if len(preview) > PARSE_LOG_TEXT_LIMIT:
        preview = f"{preview[:PARSE_LOG_TEXT_LIMIT]}..."
    logging.getLogger(LOGGER_NAME).warning(
        "LLM 回复状态无法识别，已保留正文并回退到 IDLE。状态=%s，正文片段：%s",
        state_token,
        preview,
    )


def _strip_code_fences(text: str) -> str:
    # 模型有时会自作主张包一层代码块，这里先剥掉外壳再解析。
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    return candidate.strip()
