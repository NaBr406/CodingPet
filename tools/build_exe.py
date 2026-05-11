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
    # 打包流程分三步：准备图标、整理运行时资源、调用 PyInstaller。
    _ensure_icon()
    _stage_runtime_assets()
    _build_exe()

    exe_path = DIST_DIR / f"{APP_NAME}.exe"
    print(f"打包完成: {exe_path}")
    return 0


def _ensure_icon() -> None:
    # Windows 可执行文件需要 .ico，这里从现有宠物图生成多尺寸图标。
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
    # 使用当前 Python 环境里的 PyInstaller，确保依赖和解释器与项目环境一致。
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
        # 这些大体积模块不是运行桌宠所需，排除后能显著减小 exe 体积。
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
    # 只把运行时需要的资源拷到临时目录，再交给 PyInstaller 打包。
    if RUNTIME_ASSETS_DIR.exists():
        shutil.rmtree(RUNTIME_ASSETS_DIR)
    RUNTIME_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ICON_ICO, RUNTIME_ASSETS_DIR / ICON_ICO.name)
    for state in PET_STATES:
        # 兼容单帧资源和动画帧目录两种形态。
        _copy_if_exists(PROJECT_DIR / "assets" / f"{state}.png", RUNTIME_ASSETS_DIR / f"{state}.png")
        state_source_dir = PROJECT_DIR / "assets" / state
        state_target_dir = RUNTIME_ASSETS_DIR / state
        state_target_dir.mkdir(parents=True, exist_ok=True)
        for frame_path in sorted(state_source_dir.glob("frame_*.png")):
            shutil.copy2(frame_path, state_target_dir / frame_path.name)


def _copy_if_exists(source: Path, target: Path) -> None:
    # 某些状态可能只有动画目录，没有单帧图；不存在就安静跳过。
    if source.exists():
        shutil.copy2(source, target)


if __name__ == "__main__":
    raise SystemExit(main())
