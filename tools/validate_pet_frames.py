from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageChops


PROJECT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_DIR / "assets"
if str(PROJECT_DIR) not in sys.path:
    # 从 tools 目录执行时，把项目根目录加入导入路径，方便复用 PetState。
    sys.path.insert(0, str(PROJECT_DIR))

from pet_state import PetState

MIN_FRAME_COUNT = 24
MIN_CHANGED_FRAMES = 8
MIN_VISIBLE_PIXELS = 2000
BASE_CANVAS_SIZE = 512
MAX_CENTER_DRIFT = 24
MAX_FRAME_CENTER_STEP = 9
CORNER_SIZE = 8


def main() -> int:
    # 逐状态检查动画资源：数量、尺寸、透明度、主体稳定性和动作变化量。
    failures: list[str] = []
    for state in PetState:
        frame_dir = ASSETS_DIR / state.value
        frames = sorted(frame_dir.glob("frame_*.png"))
        if len(frames) < MIN_FRAME_COUNT:
            failures.append(f"{state.value}: expected at least {MIN_FRAME_COUNT} frames, found {len(frames)}")
            continue

        centers: list[tuple[float, float]] = []
        first_frame: Image.Image | None = None
        changed_frames = 0
        for frame_path in frames:
            with Image.open(frame_path) as image:
                rgba = image.convert("RGBA")
            width, height = rgba.size
            # 运行时按正方形画布缩放，非正方形帧会导致定位和缩放不稳定。
            if width != height:
                failures.append(f"{state.value}/{frame_path.name}: expected square frame, found {width}x{height}")
            if first_frame is None:
                first_frame = rgba
                expected_size = rgba.size
            elif rgba.size != expected_size:
                failures.append(
                    f"{state.value}/{frame_path.name}: size {rgba.size} differs from first frame {expected_size}"
                )
            elif ImageChops.difference(first_frame, rgba).getbbox() is not None:
                changed_frames += 1

            alpha = rgba.getchannel("A")
            bbox = alpha.getbbox()
            if bbox is None:
                failures.append(f"{state.value}/{frame_path.name}: empty alpha")
                continue

            visible_pixels = count_alpha_values(alpha, threshold=24)
            if visible_pixels < MIN_VISIBLE_PIXELS:
                failures.append(f"{state.value}/{frame_path.name}: too few visible pixels ({visible_pixels})")

            if not corners_are_transparent(alpha):
                failures.append(f"{state.value}/{frame_path.name}: non-transparent corner pixels")

            left, top, right, bottom = bbox
            centers.append(((left + right) / 2, (top + bottom) / 2))

        if centers:
            # 主体中心如果跳得太厉害，桌宠播放时会看起来像在抖。
            frame_scale = first_frame.width / BASE_CANVAS_SIZE if first_frame is not None else 1.0
            avg_x = sum(x for x, _ in centers) / len(centers)
            avg_y = sum(y for _, y in centers) / len(centers)
            max_drift = max(abs(x - avg_x) + abs(y - avg_y) for x, y in centers)
            if max_drift > MAX_CENTER_DRIFT * frame_scale:
                failures.append(f"{state.value}: frame center drift too high ({max_drift:.1f})")

            max_step = max(
                abs(x - last_x) + abs(y - last_y)
                for (last_x, last_y), (x, y) in zip(centers, centers[1:])
            )
            if max_step > MAX_FRAME_CENTER_STEP * frame_scale:
                failures.append(f"{state.value}: frame-to-frame center jump too high ({max_step:.1f})")

            if changed_frames < MIN_CHANGED_FRAMES:
                # 至少要有一定数量的帧真正变化，避免“动画目录里全是同一张图”。
                failures.append(
                    f"{state.value}: animation is too static ({changed_frames} changed frames)"
                )

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print(f"Validated {len(tuple(PetState))} pet states under {ASSETS_DIR}")
    return 0


def corners_are_transparent(alpha: Image.Image) -> bool:
    # 透明窗口最怕角落残留脏像素，这里专门检查四角。
    width, height = alpha.size
    corner_size = max(CORNER_SIZE, round(CORNER_SIZE * width / BASE_CANVAS_SIZE))
    corners = (
        (0, 0, corner_size, corner_size),
        (width - corner_size, 0, width, corner_size),
        (0, height - corner_size, corner_size, height),
        (width - corner_size, height - corner_size, width, height),
    )
    for box in corners:
        if count_alpha_values(alpha.crop(box), threshold=0) > 0:
            return False
    return True


def count_alpha_values(alpha: Image.Image, threshold: int) -> int:
    # 用 alpha 直方图统计可见像素，比逐像素循环更快。
    histogram = alpha.histogram()
    return sum(histogram[threshold + 1 :])


if __name__ == "__main__":
    raise SystemExit(main())
