from __future__ import annotations

import argparse
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


PROJECT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_DIR / "assets"
REFERENCE_DIR = ASSETS_DIR / "reference"
FRAME_COUNT = 24
CANVAS_SIZE = 512
SOURCE_SIZE = 1024


@dataclass(frozen=True)
class MotionProfile:
    y_amplitude: float
    x_amplitude: float = 0.0
    scale_amplitude: float = 0.0
    rotation_amplitude: float = 0.0
    phase: float = 0.0
    squash_amplitude: float = 0.0
    blink_frames: tuple[int, ...] = ()
    reaction_burst: bool = False
    sweat_drop: bool = False
    idea_pop: bool = False
    sleep_bubble: bool = False
    anger_marks: bool = False
    proud_sparkles: bool = False
    typing_ticks: bool = False
    bored_puff: bool = False


STATE_ORDER = (
    "idle",
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

MOTION_PROFILES = {
    "idle": MotionProfile(y_amplitude=5, scale_amplitude=0.012, blink_frames=(10, 11)),
    "thinking": MotionProfile(
        y_amplitude=3,
        x_amplitude=2,
        rotation_amplitude=1.2,
        phase=0.2,
        idea_pop=True,
        blink_frames=(14,),
    ),
    "angry": MotionProfile(
        y_amplitude=6,
        x_amplitude=2,
        scale_amplitude=0.01,
        rotation_amplitude=2.4,
        phase=0.5,
        anger_marks=True,
    ),
    "happy": MotionProfile(
        y_amplitude=10,
        scale_amplitude=0.035,
        rotation_amplitude=3.0,
        phase=0.1,
        reaction_burst=True,
        proud_sparkles=True,
        blink_frames=(3, 4),
    ),
    "coding": MotionProfile(
        y_amplitude=3,
        x_amplitude=1,
        scale_amplitude=0.006,
        phase=0.35,
        typing_ticks=True,
        blink_frames=(16,),
    ),
    "sleepy": MotionProfile(
        y_amplitude=4,
        x_amplitude=1,
        scale_amplitude=0.015,
        phase=0.75,
        sleep_bubble=True,
        blink_frames=(0, 1, 2, 3, 4, 5, 6, 7),
    ),
    "confused": MotionProfile(
        y_amplitude=5,
        x_amplitude=3,
        rotation_amplitude=3.4,
        phase=0.15,
        idea_pop=True,
        sweat_drop=True,
    ),
    "surprised": MotionProfile(
        y_amplitude=8,
        scale_amplitude=0.04,
        rotation_amplitude=1.8,
        phase=0.42,
        reaction_burst=True,
    ),
    "proud": MotionProfile(
        y_amplitude=4,
        scale_amplitude=0.014,
        rotation_amplitude=1.2,
        phase=0.1,
        proud_sparkles=True,
        blink_frames=(8, 9, 10),
    ),
    "bored": MotionProfile(
        y_amplitude=3,
        x_amplitude=2,
        rotation_amplitude=1.6,
        phase=0.6,
        bored_puff=True,
        blink_frames=(0, 1, 2, 3, 4, 5),
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild CodingPet action sources and animation frames from an AI-generated contact sheet."
    )
    parser.add_argument(
        "sheet",
        type=Path,
        help="Path to the generated 5x2 action contact sheet.",
    )
    parser.add_argument(
        "--reference-name",
        default="codingpet-action-sheet-v2.png",
        help="Filename to keep under assets/reference/.",
    )
    args = parser.parse_args()

    sheet_path = args.sheet.expanduser().resolve()
    if not sheet_path.exists():
        raise SystemExit(f"Sheet not found: {sheet_path}")

    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    reference_path = REFERENCE_DIR / args.reference_name
    if sheet_path != reference_path.resolve():
        shutil.copy2(sheet_path, reference_path)

    sheet = Image.open(reference_path).convert("RGBA")
    sources = extract_state_sources(sheet)

    for state in STATE_ORDER:
        source = sources[state]
        write_state_source(state, source)
        write_state_frames(state, source)

    print(f"Copied reference sheet: {reference_path}")
    print(f"Rebuilt {len(STATE_ORDER)} states x {FRAME_COUNT} frames under {ASSETS_DIR}")
    return 0


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


def write_state_source(state: str, source: Image.Image) -> None:
    source_dir = ASSETS_DIR / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source.save(source_dir / f"{state}_source.png")
    source.save(ASSETS_DIR / f"{state}.png")
    source.save(ASSETS_DIR / f"{state}.webp", "WEBP", lossless=True, quality=100, method=6)


def write_state_frames(state: str, source: Image.Image) -> None:
    state_dir = ASSETS_DIR / state
    state_dir.mkdir(parents=True, exist_ok=True)
    profile = MOTION_PROFILES[state]

    for index in range(FRAME_COUNT):
        frame = build_motion_frame(source, profile, index)
        png_path = state_dir / f"frame_{index:02d}.png"
        webp_path = state_dir / f"frame_{index:02d}.webp"
        frame.save(png_path)
        frame.save(webp_path, "WEBP", lossless=False, quality=96, method=4)


def build_motion_frame(source: Image.Image, profile: MotionProfile, index: int) -> Image.Image:
    t = (index / FRAME_COUNT + profile.phase) % 1.0
    wave = math.sin(t * math.tau)
    bounce = math.sin(t * math.tau * 2)
    y_offset = round(profile.y_amplitude * wave)
    x_offset = round(profile.x_amplitude * math.sin(t * math.tau + math.pi / 2))
    scale = 1.0 + profile.scale_amplitude * max(0.0, bounce)
    rotation = profile.rotation_amplitude * math.sin(t * math.tau)

    animated = source
    if index in profile.blink_frames:
        animated = add_blink(animated)

    if profile.squash_amplitude:
        animated = squash_image(animated, 1.0 + profile.squash_amplitude * wave)

    target_size = max(1, round(CANVAS_SIZE * scale))
    animated = animated.resize((target_size, target_size), Image.Resampling.LANCZOS)
    if abs(rotation) >= 0.1:
        animated = animated.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True)

    frame = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    x = (CANVAS_SIZE - animated.width) // 2 + x_offset
    y = (CANVAS_SIZE - animated.height) // 2 + y_offset
    frame.alpha_composite(animated, (x, y))

    if profile.typing_ticks:
        draw_typing_ticks(frame, index)
    if profile.idea_pop:
        draw_idea_pop(frame, t)
    if profile.reaction_burst:
        draw_reaction_burst(frame, t)
    if profile.sleep_bubble:
        draw_sleep_bubble(frame, t)
    if profile.anger_marks:
        draw_anger_marks(frame, t)
    if profile.proud_sparkles:
        draw_sparkles(frame, t)
    if profile.sweat_drop:
        draw_sweat_drop(frame, t)
    if profile.bored_puff:
        draw_bored_puff(frame, t)

    frame = remove_lower_detached_artifacts(frame)
    return frame


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
        keep_upper_effect = area >= 60 and bottom < 360
        keep_close_detail = area >= 12 and boxes_touch_or_overlap(main_box, component["box"], margin=2)
        if keep_upper_effect or keep_close_detail:
            keep_alpha.paste(alpha.crop(component["box"]), component["box"])

    cleaned = frame.copy()
    cleaned.putalpha(keep_alpha)
    return cleaned


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


def add_blink(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    mark = Image.new("RGBA", (110, 16), (0, 0, 0, 0))
    from PIL import ImageDraw

    draw = ImageDraw.Draw(mark)
    draw.rounded_rectangle((8, 5, 102, 11), radius=4, fill=(31, 45, 65, 210))
    overlay.alpha_composite(mark, (image.width // 2 - 55, 188))
    return Image.alpha_composite(image, overlay)


def squash_image(image: Image.Image, factor: float) -> Image.Image:
    width, height = image.size
    squashed = image.resize((width, max(1, round(height * factor))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    canvas.alpha_composite(squashed, ((width - squashed.width) // 2, height - squashed.height))
    return canvas


def draw_typing_ticks(frame: Image.Image, index: int) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    active = index % 6
    for i in range(3):
        alpha = 210 if i == active // 2 else 80
        x = 186 + i * 18
        draw.rounded_rectangle((x, 297, x + 10, 303), radius=3, fill=(88, 199, 231, alpha))


def draw_idea_pop(frame: Image.Image, t: float) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    lift = round(8 * math.sin(t * math.tau))
    alpha = int(150 + 80 * max(0, math.sin(t * math.tau)))
    draw.arc((352, 92 + lift, 400, 140 + lift), 200, 520, fill=(87, 190, 232, alpha), width=6)
    draw.ellipse((371, 151 + lift, 382, 162 + lift), fill=(87, 190, 232, alpha))


def draw_reaction_burst(frame: Image.Image, t: float) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    pulse = int(190 + 55 * max(0, math.sin(t * math.tau)))
    for x, y, size in ((118, 118, 18), (392, 132, 14), (362, 86, 10)):
        draw.line((x, y - size, x, y + size), fill=(252, 222, 84, pulse), width=4)
        draw.line((x - size, y, x + size, y), fill=(252, 222, 84, pulse), width=4)


def draw_sleep_bubble(frame: Image.Image, t: float) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    grow = 1.0 + 0.22 * max(0, math.sin(t * math.tau))
    radius = round(13 * grow)
    x = 339 + round(12 * math.sin(t * math.tau))
    y = 124 - round(10 * math.sin(t * math.tau))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(215, 244, 255, 145), outline=(98, 192, 231, 170), width=3)


def draw_anger_marks(frame: Image.Image, t: float) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    alpha = int(180 + 60 * max(0, math.sin(t * math.tau * 2)))
    for x, y in ((143, 113), (371, 118)):
        draw.line((x - 10, y, x + 10, y), fill=(244, 91, 65, alpha), width=5)
        draw.line((x, y - 10, x, y + 10), fill=(244, 91, 65, alpha), width=5)


def draw_sparkles(frame: Image.Image, t: float) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    alpha = int(150 + 90 * max(0, math.sin(t * math.tau)))
    for x, y, size in ((132, 158, 10), (382, 172, 12)):
        draw.polygon(
            ((x, y - size), (x + 4, y - 4), (x + size, y), (x + 4, y + 4), (x, y + size), (x - 4, y + 4), (x - size, y), (x - 4, y - 4)),
            fill=(255, 226, 78, alpha),
        )


def draw_sweat_drop(frame: Image.Image, t: float) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    y = 154 + round(8 * math.sin(t * math.tau))
    draw.ellipse((360, y, 377, y + 23), fill=(106, 202, 236, 185), outline=(255, 255, 255, 180), width=2)


def draw_bored_puff(frame: Image.Image, t: float) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    alpha = int(90 + 70 * max(0, math.sin(t * math.tau)))
    x = 143 - round(12 * t)
    y = 377 + round(3 * math.sin(t * math.tau))
    draw.ellipse((x, y, x + 24, y + 16), fill=(245, 245, 245, alpha))
    draw.ellipse((x + 18, y - 5, x + 32, y + 7), fill=(245, 245, 245, max(0, alpha - 35)))


if __name__ == "__main__":
    raise SystemExit(main())
