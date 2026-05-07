from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


PROJECT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_DIR / "assets"
REFERENCE_DIR = ASSETS_DIR / "reference"
FRAME_COUNT = 32
CANVAS_SIZE = 512
SOURCE_SIZE = 1024


@dataclass(frozen=True)
class RasterPose:
    x_offset: float = 0.0
    y_offset: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    lean_px: float = 0.0


STATE_ORDER = (
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

SHEET_CELLS = {
    "idle": (0, 0),
    "thinking": (1, 0),
    "angry": (2, 0),
    "happy": (3, 0),
    "coding": (4, 0),
    "sleepy": (0, 1),
    "confused": (1, 1),
    "surprised": (2, 1),
    "proud": (3, 1),
    "bored": (4, 1),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild CodingPet action sources and same-layer animation frames."
    )
    parser.add_argument(
        "sheet",
        type=Path,
        nargs="?",
        help="Optional path to the generated 5x2 action contact sheet.",
    )
    parser.add_argument(
        "--reference-name",
        default="codingpet-action-sheet-v2.png",
        help="Filename to keep under assets/reference/.",
    )
    parser.add_argument(
        "--with-webp-frames",
        action="store_true",
        help="Also encode frame_*.webp files. PNG frames are the runtime default.",
    )
    args = parser.parse_args()

    sources = load_state_sources(args.sheet, args.reference_name)

    for state in STATE_ORDER:
        source = sources[state]
        write_state_source(state, source)
        write_state_frames(state, source, write_webp=args.with_webp_frames)

    if args.sheet is not None:
        reference_path = (REFERENCE_DIR / args.reference_name).resolve()
        print(f"Copied reference sheet: {reference_path}")
    print(f"Rebuilt {len(STATE_ORDER)} states x {FRAME_COUNT} frames under {ASSETS_DIR}")
    return 0


def load_state_sources(sheet_path_arg: Path | None, reference_name: str) -> dict[str, Image.Image]:
    if sheet_path_arg is not None:
        sheet_path = sheet_path_arg.expanduser().resolve()
        if not sheet_path.exists():
            raise SystemExit(f"Sheet not found: {sheet_path}")

        REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        reference_path = REFERENCE_DIR / reference_name
        if sheet_path != reference_path.resolve():
            shutil.copy2(sheet_path, reference_path)

        sheet = Image.open(reference_path).convert("RGBA")
        sheet_sources = extract_state_sources(sheet)
    else:
        sheet_sources = {}

    source_dir = ASSETS_DIR / "source"
    sources: dict[str, Image.Image] = {}
    missing_states: list[str] = []
    for state in STATE_ORDER:
        explicit_source = source_dir / f"{state}_source.png"
        if explicit_source.exists():
            sources[state] = Image.open(explicit_source).convert("RGBA")
            continue
        if state in sheet_sources:
            sources[state] = sheet_sources[state]
            continue
        missing_states.append(state)

    if missing_states:
        available = ", ".join(sorted(path.name for path in source_dir.glob("*_source.png")))
        raise SystemExit(
            "Missing source images for states: "
            + ", ".join(missing_states)
            + (f". Available in assets/source: {available}" if available else ".")
        )
    return sources


def extract_state_sources(sheet: Image.Image) -> dict[str, Image.Image]:
    cell_width = sheet.width / 5
    cell_height = sheet.height / 2
    sources: dict[str, Image.Image] = {}
    for state, (col, row) in SHEET_CELLS.items():
        crop_box = (
            round(col * cell_width),
            round(row * cell_height),
            round((col + 1) * cell_width),
            round((row + 1) * cell_height),
        )
        crop = sheet.crop(crop_box)
        cutout = remove_green_key(crop)
        cutout = keep_primary_subject(cutout)
        source = fit_subject_to_canvas(cutout, SOURCE_SIZE, padding=72)
        sources[state] = keep_primary_subject(source)
    return sources


def remove_green_key(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = []
    for red, green, blue, alpha in rgba.getdata():
        is_key = green > 135 and green - red > 38 and green - blue > 28
        near_key = green > 102 and green - red > 22 and green - blue > 18
        if is_key:
            pixels.append((red, green, blue, 0))
        elif near_key:
            softened_alpha = max(0, min(alpha, int(alpha * 0.18)))
            pixels.append((red, green, blue, softened_alpha))
        else:
            pixels.append((red, green, blue, alpha))

    keyed = Image.new("RGBA", rgba.size)
    keyed.putdata(pixels)
    alpha = keyed.getchannel("A")
    alpha = ImageChops.subtract(alpha, Image.new("L", alpha.size, 8))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.25))
    keyed.putalpha(alpha)
    return despill_green(keyed)


def despill_green(image: Image.Image) -> Image.Image:
    pixels = []
    for red, green, blue, alpha in image.getdata():
        if alpha == 0:
            pixels.append((red, green, blue, alpha))
            continue
        spill_limit = max(red, blue) + 12
        if green > spill_limit:
            green = int(spill_limit)
        pixels.append((red, green, blue, alpha))
    image = Image.new("RGBA", image.size)
    image.putdata(pixels)
    return image


def write_state_source(state: str, source: Image.Image) -> None:
    source_dir = ASSETS_DIR / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source.save(source_dir / f"{state}_source.png")

    display = source_to_canvas(source)
    display.save(ASSETS_DIR / f"{state}.png")
    display.save(ASSETS_DIR / f"{state}.webp", "WEBP", lossless=True, quality=100, method=6)


def write_state_frames(state: str, source: Image.Image, *, write_webp: bool = False) -> None:
    state_dir = ASSETS_DIR / state
    state_dir.mkdir(parents=True, exist_ok=True)
    base = source_to_canvas(source)

    for index in range(FRAME_COUNT):
        frame = build_motion_frame(state, base, index)
        png_path = state_dir / f"frame_{index:02d}.png"
        frame.save(png_path)
        if write_webp:
            webp_path = state_dir / f"frame_{index:02d}.webp"
            frame.save(webp_path, "WEBP", lossless=False, quality=92, method=0)


def source_to_canvas(source: Image.Image) -> Image.Image:
    source = source.convert("RGBA")
    if source.size == (CANVAS_SIZE, CANVAS_SIZE):
        return source
    return source.resize((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)


def build_motion_frame(state: str, base: Image.Image, index: int) -> Image.Image:
    timeline = index / FRAME_COUNT
    pose = choreograph_pose(state, timeline)
    posed = apply_anchored_scale(base, pose)
    if abs(pose.lean_px) >= 0.05:
        posed = apply_same_layer_lean(posed, pose.lean_px)
    return clear_corner_alpha(posed)


def choreograph_pose(state: str, timeline: float) -> RasterPose:
    p = timeline % 1.0
    match state:
        case "idle":
            return pose_from_keyframes(
                p,
                scale_x=[(0.0, 1.0), (0.5, 0.994), (1.0, 1.0)],
                scale_y=[(0.0, 1.0), (0.5, 1.010), (1.0, 1.0)],
                y=[(0.0, 0.0), (0.5, -2.5), (1.0, 0.0)],
            )
        case "greeting":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.2, -3.0), (0.48, -1.0), (0.74, -2.0), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.22, 4.5), (0.48, -2.0), (0.74, 3.5), (1.0, 0.0)],
                scale_y=[(0.0, 1.0), (0.22, 1.006), (0.56, 0.998), (1.0, 1.0)],
            )
        case "listening":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.35, -2.0), (0.62, -3.5), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.28, -4.0), (0.56, -2.0), (0.82, 2.0), (1.0, 0.0)],
                scale_y=[(0.0, 1.0), (0.58, 1.008), (1.0, 1.0)],
            )
        case "reviewing":
            return pose_from_keyframes(
                p,
                x=[(0.0, 0.0), (0.25, -2.0), (0.58, 2.0), (1.0, 0.0)],
                y=[(0.0, 0.0), (0.5, -2.0), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.25, -3.2), (0.58, 3.0), (1.0, 0.0)],
            )
        case "dragging":
            return pose_from_keyframes(
                p,
                x=[(0.0, 0.0), (0.18, -4.0), (0.46, 4.5), (0.72, 2.0), (1.0, 0.0)],
                y=[(0.0, 0.0), (0.18, 1.5), (0.46, -3.0), (0.72, -1.0), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.18, -7.0), (0.46, 5.5), (0.72, 2.0), (1.0, 0.0)],
                scale_x=[(0.0, 1.0), (0.2, 1.010), (0.48, 0.995), (1.0, 1.0)],
            )
        case "resizing":
            return pose_from_keyframes(
                p,
                scale_x=[(0.0, 1.0), (0.18, 1.018), (0.44, 0.992), (0.66, 1.012), (1.0, 1.0)],
                scale_y=[(0.0, 1.0), (0.18, 0.994), (0.44, 1.010), (0.66, 0.997), (1.0, 1.0)],
                y=[(0.0, 0.0), (0.44, -2.0), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.24, -2.5), (0.58, 2.5), (1.0, 0.0)],
            )
        case "thinking":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.46, -2.0), (0.76, -1.0), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.32, -3.8), (0.66, 2.2), (1.0, 0.0)],
                scale_y=[(0.0, 1.0), (0.48, 1.007), (1.0, 1.0)],
            )
        case "angry":
            return pose_from_keyframes(
                p,
                x=[(0.0, 0.0), (0.22, -1.5), (0.45, 1.5), (0.72, -0.8), (1.0, 0.0)],
                y=[(0.0, 0.0), (0.26, 1.5), (0.52, -1.0), (0.78, 1.0), (1.0, 0.0)],
                scale_x=[(0.0, 1.0), (0.26, 1.014), (0.52, 0.996), (0.78, 1.010), (1.0, 1.0)],
                scale_y=[(0.0, 1.0), (0.26, 0.992), (0.52, 1.006), (0.78, 0.996), (1.0, 1.0)],
                lean=[(0.0, 0.0), (0.26, -2.2), (0.52, 2.0), (0.78, -1.0), (1.0, 0.0)],
            )
        case "happy":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.22, -8.5), (0.42, -10.0), (0.66, -2.0), (1.0, 0.0)],
                scale_x=[(0.0, 1.0), (0.22, 0.996), (0.42, 0.992), (0.66, 1.012), (1.0, 1.0)],
                scale_y=[(0.0, 1.0), (0.22, 1.010), (0.42, 1.014), (0.66, 0.986), (1.0, 1.0)],
                lean=[(0.0, 0.0), (0.25, 2.5), (0.58, -2.0), (1.0, 0.0)],
            )
        case "coding":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.32, -1.5), (0.62, -2.0), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.28, -2.0), (0.5, 1.5), (0.72, -1.5), (1.0, 0.0)],
                scale_y=[(0.0, 1.0), (0.42, 1.006), (1.0, 1.0)],
            )
        case "sleepy":
            return pose_from_keyframes(
                p,
                x=[(0.0, 0.0), (0.35, -2.0), (0.7, 2.0), (1.0, 0.0)],
                y=[(0.0, 0.0), (0.48, 3.5), (0.76, 2.5), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.35, -4.2), (0.7, 3.2), (1.0, 0.0)],
                scale_y=[(0.0, 1.0), (0.5, 0.990), (1.0, 1.0)],
            )
        case "confused":
            return pose_from_keyframes(
                p,
                x=[(0.0, 0.0), (0.22, -3.0), (0.52, 2.5), (0.78, -1.5), (1.0, 0.0)],
                y=[(0.0, 0.0), (0.5, -2.0), (1.0, 0.0)],
                lean=[(0.0, 0.0), (0.22, -5.2), (0.52, 5.0), (0.78, -2.0), (1.0, 0.0)],
            )
        case "surprised":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.18, -6.0), (0.36, -4.0), (0.58, 1.5), (1.0, 0.0)],
                scale_x=[(0.0, 1.0), (0.18, 0.988), (0.36, 1.018), (0.58, 1.006), (1.0, 1.0)],
                scale_y=[(0.0, 1.0), (0.18, 1.024), (0.36, 0.992), (0.58, 0.998), (1.0, 1.0)],
                lean=[(0.0, 0.0), (0.2, 1.8), (0.48, -1.6), (1.0, 0.0)],
            )
        case "proud":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.36, -3.5), (0.7, -2.0), (1.0, 0.0)],
                scale_x=[(0.0, 1.0), (0.36, 1.006), (0.7, 1.002), (1.0, 1.0)],
                scale_y=[(0.0, 1.0), (0.36, 1.008), (0.7, 1.004), (1.0, 1.0)],
                lean=[(0.0, 0.0), (0.36, 2.2), (0.7, 1.2), (1.0, 0.0)],
            )
        case "bored":
            return pose_from_keyframes(
                p,
                y=[(0.0, 0.0), (0.34, 4.5), (0.7, 5.5), (1.0, 0.0)],
                scale_x=[(0.0, 1.0), (0.5, 1.006), (1.0, 1.0)],
                scale_y=[(0.0, 1.0), (0.5, 0.988), (1.0, 1.0)],
                lean=[(0.0, 0.0), (0.34, -4.5), (0.7, -2.0), (1.0, 0.0)],
            )
    return RasterPose()


def pose_from_keyframes(
    timeline: float,
    *,
    x: list[tuple[float, float]] | None = None,
    y: list[tuple[float, float]] | None = None,
    scale_x: list[tuple[float, float]] | None = None,
    scale_y: list[tuple[float, float]] | None = None,
    lean: list[tuple[float, float]] | None = None,
) -> RasterPose:
    return RasterPose(
        x_offset=interpolate_keyframes(timeline, x or [(0.0, 0.0), (1.0, 0.0)]),
        y_offset=interpolate_keyframes(timeline, y or [(0.0, 0.0), (1.0, 0.0)]),
        scale_x=interpolate_keyframes(timeline, scale_x or [(0.0, 1.0), (1.0, 1.0)]),
        scale_y=interpolate_keyframes(timeline, scale_y or [(0.0, 1.0), (1.0, 1.0)]),
        lean_px=interpolate_keyframes(timeline, lean or [(0.0, 0.0), (1.0, 0.0)]),
    )


def interpolate_keyframes(timeline: float, points: list[tuple[float, float]]) -> float:
    p = max(0.0, min(1.0, timeline))
    ordered = sorted(points, key=lambda item: item[0])
    if p <= ordered[0][0]:
        return ordered[0][1]
    for (start_t, start_value), (end_t, end_value) in zip(ordered, ordered[1:]):
        if p <= end_t:
            span = max(0.0001, end_t - start_t)
            local = smoothstep((p - start_t) / span)
            return start_value + (end_value - start_value) * local
    return ordered[-1][1]


def smoothstep(value: float) -> float:
    clamped = max(0.0, min(1.0, value))
    return clamped * clamped * (3.0 - 2.0 * clamped)


def apply_anchored_scale(image: Image.Image, pose: RasterPose) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return Image.new("RGBA", image.size, (0, 0, 0, 0))

    subject_box = expand_box(bbox, image.size, 4)
    subject = image.crop(subject_box)
    target_size = (
        max(1, round(subject.width * pose.scale_x)),
        max(1, round(subject.height * pose.scale_y)),
    )
    if target_size != subject.size:
        subject = subject.resize(target_size, Image.Resampling.BICUBIC)

    left, _top, right, bottom = subject_box
    anchor_x = (left + right) / 2 + pose.x_offset
    anchor_bottom = bottom + pose.y_offset
    x = round(anchor_x - subject.width / 2)
    y = round(anchor_bottom - subject.height)

    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    canvas.alpha_composite(subject, (x, y))
    return canvas


def apply_same_layer_lean(image: Image.Image, lean_px: float) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return image

    left, top, right, bottom = expand_box(bbox, image.size, round(abs(lean_px)) + 6)
    subject = image.crop((left, top, right, bottom))
    height = max(1, subject.height)
    # Affine shear keeps the face and body in one raster layer while the feet stay anchored.
    coefficients = (1.0, lean_px / height, -lean_px, 0.0, 1.0, 0.0)
    leaned = subject.transform(subject.size, Image.Transform.AFFINE, coefficients, Image.Resampling.BICUBIC)

    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    canvas.alpha_composite(leaned, (left, top))
    return clear_corner_alpha(canvas)


def clear_corner_alpha(image: Image.Image) -> Image.Image:
    rgba = image.copy()
    alpha = rgba.getchannel("A")
    width, height = alpha.size
    empty_corner = Image.new("L", (8, 8), 0)
    for box in (
        (0, 0, 8, 8),
        (width - 8, 0, width, 8),
        (0, height - 8, 8, height),
        (width - 8, height - 8, width, height),
    ):
        alpha.paste(empty_corner, box)
    rgba.putalpha(alpha)
    return rgba


def keep_primary_subject(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > 34 else 0)
    components = find_alpha_components(mask)
    if not components:
        return image

    main = max(components, key=lambda item: item["area"])
    keep = Image.new("L", image.size, 0)
    main_box = main["box"]
    cropped = alpha.crop(main_box)
    keep.paste(cropped, main_box)

    filtered = image.copy()
    filtered.putalpha(keep)
    return filtered


def remove_lower_detached_artifacts(frame: Image.Image) -> Image.Image:
    alpha = frame.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > 34 else 0)
    components = find_alpha_components(mask)
    if not components:
        return frame

    main = max(components, key=lambda item: item["area"])
    keep_alpha = Image.new("L", frame.size, 0)
    main_box = main["box"]
    keep_alpha.paste(alpha.crop(main_box), main_box)

    for component in components:
        if component is main:
            continue
        area = int(component["area"])
        left, top, right, bottom = component["box"]
        keep_existing_upper_detail = area >= 60 and bottom < 360
        keep_attached_detail = area >= 12 and boxes_touch_or_overlap(main_box, component["box"], margin=2)
        if keep_existing_upper_detail or keep_attached_detail:
            keep_alpha.paste(alpha.crop(component["box"]), component["box"])

    cleaned = frame.copy()
    cleaned.putalpha(keep_alpha)
    return cleaned


def find_alpha_components(mask: Image.Image) -> list[dict[str, object]]:
    width, height = mask.size
    data = mask.load()
    visited = bytearray(width * height)
    components: list[dict[str, object]] = []

    for start_y in range(height):
        row_offset = start_y * width
        for start_x in range(width):
            start_index = row_offset + start_x
            if visited[start_index] or data[start_x, start_y] == 0:
                continue

            stack = [(start_x, start_y)]
            visited[start_index] = 1
            area = 0
            left = right = start_x
            top = bottom = start_y

            while stack:
                x, y = stack.pop()
                area += 1
                left = min(left, x)
                right = max(right, x)
                top = min(top, y)
                bottom = max(bottom, y)

                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    index = ny * width + nx
                    if visited[index] or data[nx, ny] == 0:
                        continue
                    visited[index] = 1
                    stack.append((nx, ny))

            components.append({"area": area, "box": (left, top, right + 1, bottom + 1)})

    return components


def boxes_touch_or_overlap(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
    margin: int,
) -> bool:
    first_left, first_top, first_right, first_bottom = first
    second_left, second_top, second_right, second_bottom = second
    return not (
        second_right < first_left - margin
        or second_left > first_right + margin
        or second_bottom < first_top - margin
        or second_top > first_bottom + margin
    )


def fit_subject_to_canvas(image: Image.Image, size: int, padding: int) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))

    subject = image.crop(expand_box(bbox, image.size, 8))
    max_subject_width = size - (padding * 2)
    max_subject_height = size - (padding * 2)
    scale = min(max_subject_width / subject.width, max_subject_height / subject.height)
    target_size = (
        max(1, round(subject.width * scale)),
        max(1, round(subject.height * scale)),
    )
    subject = subject.resize(target_size, Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - subject.width) // 2
    y = size - subject.height - padding // 2
    canvas.alpha_composite(subject, (x, y))
    return canvas


def expand_box(box: tuple[int, int, int, int], size: tuple[int, int], margin: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    width, height = size
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(width, right + margin),
        min(height, bottom + margin),
    )


if __name__ == "__main__":
    raise SystemExit(main())
