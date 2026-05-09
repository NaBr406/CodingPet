from __future__ import annotations

from dataclasses import dataclass


ACTIVE_CHAT_SOURCE = "active"
PASSIVE_CHAT_SOURCE = "passive"


@dataclass(frozen=True)
class ChatTurn:
    user: str
    assistant: str
    source: str = ACTIVE_CHAT_SOURCE
