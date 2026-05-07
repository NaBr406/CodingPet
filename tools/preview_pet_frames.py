from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


PROJECT_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_DIR / "assets"
REFERENCE_DIR = ASSETS_DIR / "reference"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from pet_state import PetState


SAMPLE_INDICES = (0, 4, 8, 12, 16, 20, 24, 28)
CELL_SIZE = 128
LABEL_HEIGHT = 24
ROW_GAP = 10
COL_GAP = 8
LEFT_LABEL_WIDTH = 104
BACKGROUND_A = (238, 242, 246, 255)
BACKGROUND_B = (218, 225, 233, 255)


def main() -> int:
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REFERENCE_DIR / "animation-preview-sheet.png"

    font = ImageFont.load_default()
    sheet_width = LEFT_LABEL_WIDTH + len(SAMPLE_INDICES) * (CELL_SIZE + COL_GAP) - COL_GAP
    sheet_height = LABEL_HEIGHT + len(tuple(PetState)) * (CELL_SIZE + ROW_GAP) - ROW_GAP
    sheet = Image.new("RGBA", (sheet_width, sheet_height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sheet)

    for column, frame_index in enumerate(SAMPLE_INDICES):
        x = LEFT_LABEL_WIDTH + column * (CELL_SIZE + COL_GAP)
        draw.text((x + 6, 6), f"f{frame_index:02d}", fill=(65, 74, 86, 255), font=font)

    for row, state in enumerate(PetState):
        y = LABEL_HEIGHT + row * (CELL_SIZE + ROW_GAP)
        draw.text((8, y + 54), state.value, fill=(28, 35, 45, 255), font=font)
        for column, frame_index in enumerate(SAMPLE_INDICES):
            frame_path = ASSETS_DIR / state.value / f"frame_{frame_index:02d}.png"
            x = LEFT_LABEL_WIDTH + column * (CELL_SIZE + COL_GAP)
            cell = checkerboard(CELL_SIZE, CELL_SIZE)
            if frame_path.exists():
                with Image.open(frame_path) as image:
                    frame = image.convert("RGBA")
                frame.thumbnail((CELL_SIZE - 12, CELL_SIZE - 12), Image.Resampling.LANCZOS)
                cell.alpha_composite(frame, ((CELL_SIZE - frame.width) // 2, (CELL_SIZE - frame.height) // 2))
            else:
                draw_missing_cell(cell)
            sheet.alpha_composite(cell, (x, y))
            draw.rectangle((x, y, x + CELL_SIZE - 1, y + CELL_SIZE - 1), outline=(198, 207, 218, 255), width=1)

    sheet.convert("RGB").save(output_path)
    print(f"Wrote preview sheet: {output_path}")
    return 0


def checkerboard(width: int, height: int) -> Image.Image:
    image = Image.new("RGBA", (width, height), BACKGROUND_A)
    draw = ImageDraw.Draw(image)
    block = 16
    for top in range(0, height, block):
        for left in range(0, width, block):
            if ((left // block) + (top // block)) % 2:
                draw.rectangle((left, top, left + block - 1, top + block - 1), fill=BACKGROUND_B)
    return image


def draw_missing_cell(cell: Image.Image) -> None:
    draw = ImageDraw.Draw(cell)
    draw.line((18, 18, CELL_SIZE - 18, CELL_SIZE - 18), fill=(210, 90, 90, 255), width=3)
    draw.line((CELL_SIZE - 18, 18, 18, CELL_SIZE - 18), fill=(210, 90, 90, 255), width=3)


if __name__ == "__main__":
    raise SystemExit(main())
