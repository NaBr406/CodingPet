from __future__ import annotations

import logging
import sys
from pathlib import Path
from io import BytesIO

from PIL import Image
from rembg import remove

from config_loader import load_config
from llm_client import generate_character_image
from logging_utils import LOGGER_NAME, setup_logging
from pet_state import PetState


STATE_PROMPTS = {
    PetState.IDLE: "relaxed idle pose, neutral expression, full body, white background",
    PetState.THINKING: "focused thinking pose, analytical expression, full body, white background",
    PetState.ANGRY: "annoyed lecturing pose, critical expression, full body, white background",
    PetState.HAPPY: "cheerful celebratory pose, bright smile, full body, white background",
}

FRAME_DIRS = {
    PetState.IDLE: "idle",
    PetState.THINKING: "thinking",
    PetState.ANGRY: "angry",
    PetState.HAPPY: "happy",
}


def build_assets(config_path: str = "config.yaml") -> bool:
    logger = logging.getLogger(LOGGER_NAME)
    config = load_config(config_path)
    config.assets_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    for state, state_prompt in STATE_PROMPTS.items():
        prompt = f"{config.pet_preset.appearance_prompt}. {state_prompt}."
        try:
            raw_image = generate_character_image(config, prompt)
            transparent_bytes = remove(raw_image)
            image = Image.open(BytesIO(transparent_bytes)).convert("RGBA")

            output_path = config.assets_dir / state.asset_filename
            image.save(output_path, "WEBP", lossless=True, quality=100, method=6)
            logger.info("Saved transparent asset: %s", output_path)
            generated += 1
        except Exception:
            logger.exception("Failed to generate asset for state '%s'.", state.name)

    if generated == len(STATE_PROMPTS):
        logger.info("Phase 0 Success: generated %d transparent assets.", generated)
        return True

    logger.error("Phase 0 incomplete: generated %d/%d assets.", generated, len(STATE_PROMPTS))
    return False


def describe_frame_layout() -> str:
    return "Use assets/<state>/frame_001.png, frame_002.png, ... for animation; single assets/<state>.webp still works."


if __name__ == "__main__":
    setup_logging()
    sys.exit(0 if build_assets() else 1)
