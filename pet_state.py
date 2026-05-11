from __future__ import annotations

from enum import Enum


class PetState(str, Enum):
    # 枚举值同时对应资源目录名，例如 assets/happy/frame_00.png。
    IDLE = "idle"
    GREETING = "greeting"
    LISTENING = "listening"
    REVIEWING = "reviewing"
    DRAGGING = "dragging"
    RESIZING = "resizing"
    THINKING = "thinking"
    ANGRY = "angry"
    HAPPY = "happy"
    CODING = "coding"
    SLEEPY = "sleepy"
    CONFUSED = "confused"
    SURPRISED = "surprised"
    PROUD = "proud"
    BORED = "bored"

    @property
    def asset_filename(self) -> str:
        # 单帧资源的默认文件名；如果存在同名目录，则 UI 会优先加载动画帧。
        return f"{self.value}.webp"

    @classmethod
    def from_emotion(cls, value: str | None) -> "PetState":
        # 模型输出不一定完全等于枚举名，所以这里集中维护一组同义词映射。
        token = (value or "").strip().upper()
        mapping = {
            "IDLE": cls.IDLE,
            "NEUTRAL": cls.IDLE,
            "CALM": cls.IDLE,
            "GREETING": cls.GREETING,
            "HELLO": cls.GREETING,
            "WELCOME": cls.GREETING,
            "LISTENING": cls.LISTENING,
            "HEARING": cls.LISTENING,
            "RECEPTIVE": cls.LISTENING,
            "REVIEWING": cls.REVIEWING,
            "REVIEW": cls.REVIEWING,
            "INSPECTING": cls.REVIEWING,
            "SCANNING": cls.REVIEWING,
            "DRAGGING": cls.DRAGGING,
            "RESIZING": cls.RESIZING,
            "THINKING": cls.THINKING,
            "FOCUSED": cls.THINKING,
            "ANALYTICAL": cls.THINKING,
            "CODING": cls.CODING,
            "WORKING": cls.CODING,
            "FOCUSED_CODING": cls.CODING,
            "ANGRY": cls.ANGRY,
            "ROAST": cls.ANGRY,
            "CRITICAL": cls.ANGRY,
            "HAPPY": cls.HAPPY,
            "PRAISE": cls.HAPPY,
            "POSITIVE": cls.HAPPY,
            "SLEEPY": cls.SLEEPY,
            "TIRED": cls.SLEEPY,
            "CONFUSED": cls.CONFUSED,
            "PUZZLED": cls.CONFUSED,
            "SURPRISED": cls.SURPRISED,
            "SHOCKED": cls.SURPRISED,
            "PROUD": cls.PROUD,
            "SMUG": cls.PROUD,
            "BORED": cls.BORED,
            "WAITING": cls.BORED,
        }
        return mapping.get(token, cls.IDLE)


# 随机心情只选适合自然轮播的状态，不包含拖拽、缩放这类交互态。
RANDOM_MOOD_STATES = (
    PetState.IDLE,
    PetState.THINKING,
    PetState.CODING,
    PetState.SLEEPY,
    PetState.CONFUSED,
    PetState.SURPRISED,
    PetState.PROUD,
    PetState.BORED,
    PetState.HAPPY,
)
