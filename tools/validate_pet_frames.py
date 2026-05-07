from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageChops


PROJECT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_DIR / "assets"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pet_state import PetState

MIN_FRAME_COUNT = 24
MIN_CHANGED_FRAMES = 8
MIN_VISIBLE_PIXELS = 2000
MAX_CENTER_DRIFT = 24
MAX_FRAME_CENTER_STEP = 9
CORNER_SIZE = 8


def main() -> int:
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
            if first_frame is None:
                first_frame = rgba
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
            avg_x = sum(x for x, _ in centers) / len(centers)
            avg_y = sum(y for _, y in centers) / len(centers)
            max_drift = max(abs(x - avg_x) + abs(y - avg_y) for x, y in centers)
            if max_drift > MAX_CENTER_DRIFT:
                failures.append(f"{state.value}: frame center drift too high ({max_drift:.1f})")

            max_step = max(
                abs(x - last_x) + abs(y - last_y)
                for (last_x, last_y), (x, y) in zip(centers, centers[1:])
            )
            if max_step > MAX_FRAME_CENTER_STEP:
                failures.append(f"{state.value}: frame-to-frame center jump too high ({max_step:.1f})")

            if changed_frames < MIN_CHANGED_FRAMES:
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
    width, height = alpha.size
    corners = (
        (0, 0, CORNER_SIZE, CORNER_SIZE),
        (width - CORNER_SIZE, 0, width, CORNER_SIZE),
        (0, height - CORNER_SIZE, CORNER_SIZE, height),
        (width - CORNER_SIZE, height - CORNER_SIZE, width, height),
    )
    for box in corners:
        if count_alpha_values(alpha.crop(box), threshold=0) > 0:
            return False
    return True


def count_alpha_values(alpha: Image.Image, threshold: int) -> int:
    histogram = alpha.histogram()
    return sum(histogram[threshold + 1 :])


if __name__ == "__main__":
    raise SystemExit(main())
