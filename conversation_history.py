from __future__ import annotations

from dataclasses import dataclass


# source 用来区分“用户主动聊天”和“系统被动观察”，上下文窗口会按它改变展示。
ACTIVE_CHAT_SOURCE = "active"
PASSIVE_CHAT_SOURCE = "passive"


@dataclass(frozen=True)
class ChatTurn:
    # 这里保存的是本次运行内存中的一轮记录，不会自动持久化到磁盘。
    user: str
    assistant: str
    source: str = ACTIVE_CHAT_SOURCE
