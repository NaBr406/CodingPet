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
    def resolve_emotion(cls, value: str | None) -> "PetState | None":
        # 模型输出不一定完全等于枚举名，所以这里集中维护一组同义词映射。
        token = (value or "").strip().upper()
        mapping = {
            "IDLE": cls.IDLE,
            "DEFAULT": cls.IDLE,
            "NEUTRAL": cls.IDLE,
            "CALM": cls.IDLE,
            "空闲": cls.IDLE,
            "默认": cls.IDLE,
            "中立": cls.IDLE,
            "GREETING": cls.GREETING,
            "HELLO": cls.GREETING,
            "WELCOME": cls.GREETING,
            "问候": cls.GREETING,
            "打招呼": cls.GREETING,
            "LISTENING": cls.LISTENING,
            "HEARING": cls.LISTENING,
            "RECEPTIVE": cls.LISTENING,
            "倾听": cls.LISTENING,
            "聆听": cls.LISTENING,
            "REVIEWING": cls.REVIEWING,
            "REVIEW": cls.REVIEWING,
            "INSPECTING": cls.REVIEWING,
            "SCANNING": cls.REVIEWING,
            "审查": cls.REVIEWING,
            "检查": cls.REVIEWING,
            "复查": cls.REVIEWING,
            "DRAGGING": cls.DRAGGING,
            "拖拽": cls.DRAGGING,
            "RESIZING": cls.RESIZING,
            "缩放": cls.RESIZING,
            "THINKING": cls.THINKING,
            "FOCUSED": cls.THINKING,
            "ANALYTICAL": cls.THINKING,
            "思考": cls.THINKING,
            "分析": cls.THINKING,
            "CODING": cls.CODING,
            "WORKING": cls.CODING,
            "FOCUSED_CODING": cls.CODING,
            "编程": cls.CODING,
            "写代码": cls.CODING,
            "工作": cls.CODING,
            "ANGRY": cls.ANGRY,
            "ROAST": cls.ANGRY,
            "CRITICAL": cls.ANGRY,
            "生气": cls.ANGRY,
            "吐槽": cls.ANGRY,
            "批评": cls.ANGRY,
            "HAPPY": cls.HAPPY,
            "PRAISE": cls.HAPPY,
            "POSITIVE": cls.HAPPY,
            "开心": cls.HAPPY,
            "高兴": cls.HAPPY,
            "愉快": cls.HAPPY,
            "SLEEPY": cls.SLEEPY,
            "TIRED": cls.SLEEPY,
            "困": cls.SLEEPY,
            "疲惫": cls.SLEEPY,
            "困倦": cls.SLEEPY,
            "CONFUSED": cls.CONFUSED,
            "PUZZLED": cls.CONFUSED,
            "困惑": cls.CONFUSED,
            "疑惑": cls.CONFUSED,
            "SURPRISED": cls.SURPRISED,
            "SHOCKED": cls.SURPRISED,
            "惊讶": cls.SURPRISED,
            "震惊": cls.SURPRISED,
            "PROUD": cls.PROUD,
            "SMUG": cls.PROUD,
            "骄傲": cls.PROUD,
            "得意": cls.PROUD,
            "BORED": cls.BORED,
            "WAITING": cls.BORED,
            "无聊": cls.BORED,
            "等待": cls.BORED,
        }
        return mapping.get(token)

    @classmethod
    def from_emotion(cls, value: str | None) -> "PetState":
        return cls.resolve_emotion(value) or cls.IDLE


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
