from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image


PROJECT_DIR = Path(__file__).resolve().parents[1]
BUILD_DIR = PROJECT_DIR / "build"
DIST_DIR = PROJECT_DIR / "dist"
RUNTIME_ASSETS_DIR = BUILD_DIR / "runtime-assets" / "assets"
ICON_PNG = PROJECT_DIR / "assets" / "bored.png"
ICON_ICO = PROJECT_DIR / "assets" / "codingpet.ico"
APP_NAME = "CodingPet"
PET_STATES = (
    "idle",
    "greeting",
    "listening",
    "reviewing",
    "dragging",
    "resizing",
    "thinking",
    "angry",
    "happy",
    "coding",
    "sleepy",
    "confused",
    "surprised",
    "proud",
    "bored",
)


def main() -> int:
    _ensure_icon()
    _stage_runtime_assets()
    _build_exe()

    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    print(f"打包完成: {exe_path}")
    return 0


def _ensure_icon() -> None:
    if not ICON_PNG.exists():
        raise FileNotFoundError(f"Icon source not found: {ICON_PNG}")

    image = Image.open(ICON_PNG).convert("RGBA")
    image.save(
        ICON_ICO,
        sizes=[
            (16, 16),
            (24, 24),
            (32, 32),
            (48, 48),
            (64, 64),
            (128, 128),
            (256, 256),
        ],
    )


def _build_exe() -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON_ICO),
        "--add-data",
        f"{RUNTIME_ASSETS_DIR};assets",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "torch",
        "--exclude-module",
        "torchvision",
        "--exclude-module",
        "rembg",
        "--exclude-module",
        "onnxruntime",
        "--add-data",
        f"{PROJECT_DIR / 'config.example.yaml'};.",
        str(PROJECT_DIR / "main.py"),
    ]
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


def _stage_runtime_assets() -> None:
    if RUNTIME_ASSETS_DIR.exists():
        shutil.rmtree(RUNTIME_ASSETS_DIR)
    RUNTIME_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ICON_ICO, RUNTIME_ASSETS_DIR / ICON_ICO.name)
    for state in PET_STATES:
        _copy_if_exists(PROJECT_DIR / "assets" / f"{state}.png", RUNTIME_ASSETS_DIR / f"{state}.png")
        state_source_dir = PROJECT_DIR / "assets" / state
        state_target_dir = RUNTIME_ASSETS_DIR / state
        state_target_dir.mkdir(parents=True, exist_ok=True)
        for frame_path in sorted(state_source_dir.glob("frame_*.png")):
            shutil.copy2(frame_path, state_target_dir / frame_path.name)


def _copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        shutil.copy2(source, target)


if __name__ == "__main__":
    raise SystemExit(main())
