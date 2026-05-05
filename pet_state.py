from __future__ import annotations

from enum import Enum


class PetState(str, Enum):
    IDLE = "idle"
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
        return f"{self.value}.webp"

    @classmethod
    def from_emotion(cls, value: str | None) -> "PetState":
        token = (value or "").strip().upper()
        mapping = {
            "IDLE": cls.IDLE,
            "NEUTRAL": cls.IDLE,
            "CALM": cls.IDLE,
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
