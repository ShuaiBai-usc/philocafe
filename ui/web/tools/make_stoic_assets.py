"""Draw the conversation frames, scene, portrait and avatar for Seneca and Epictetus, and add
both philosophers to data.json.

The prototype only shipped their café-home frames (home_seneca_*, home_epictetus_*). The other
philosophers' conversation frames share the home frames' 31-cell pixel grid, so a conversation
frame here is the home frame's pixels with the cup on the café table removed (that table is not
in the conversation scene; a cup in the hand stays).

- Epictetus sits in the left armchair of the conversation scene, like the others, staff at his side.
- Seneca's home frames face a table on his left, so he takes the right armchair.
- The conversation scenes are the same room for everyone, so each new scene is a copy of Socrates'.
- Portrait and avatar are the rest frame drawn large on the portraits' olive background. They are
  placeholders until the UI/UX team draws detailed ones; replace the PNGs and nothing else changes.

    .venv/bin/python ui/web/tools/make_stoic_assets.py
    .venv/bin/python ui/web/tools/build_index.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

WEB = Path(__file__).resolve().parent.parent
ASSETS = WEB / "assets"
DATA = WEB / "data.json"

HOME_CELL, HOME_X0 = 12, 2          # home frames: 12 px per pixel, starting 2 px in
CHAT_CELL = 7.04                    # conversation scene units per pixel (as in Socrates' frames)
OUT_CELL = 7                        # conversation frame PNGs: 7 px per pixel
CLEAR = (0, 0, 0, 0)
BG = [(171, 175, 136), (179, 182, 145), (162, 168, 128), (153, 160, 120), (144, 153, 111)]

# Home seats: the prototype's box for each figure, moved from its original chair to a free one.
# Chair backs in home_bg.png (left, top): Seneca from (908, 2184) to (920, 1176), Epictetus from
# (620, 1680) to (116, 1932). Original boxes: Seneca [750, 2124, 1125, 2508], Epictetus [534, 1632, 969, 2004].
HOME_BOX = {"seneca": [762, 1116, 1137, 1500], "epictetus": [30, 1884, 465, 2256]}
# Prototype timelines for the home frames.
HOME_SEQ = {
    "seneca": [[14, 400], [0, 600], [4, 200], [5, 200], [6, 400], [7, 200], [8, 1400], [7, 200], [15, 800],
               [12, 200], [13, 200], [16, 800], [2, 100], [0, 6900], [1, 600], [2, 100], [3, 600], [4, 200],
               [5, 200], [6, 300], [7, 200], [8, 800], [9, 400], [10, 400], [11, 800], [12, 200], [13, 200],
               [14, 400]],
    "epictetus": [[13, 500], [14, 200], [15, 200], [16, 800], [0, 5900], [1, 800], [2, 400], [3, 200], [4, 200],
                  [5, 600], [6, 200], [7, 1600], [8, 200], [9, 1000], [4, 200], [3, 200], [2, 600], [0, 100],
                  [10, 1000], [2, 400], [11, 200], [4, 200], [12, 400], [6, 200], [7, 1200], [6, 200], [13, 300]],
}
# Conversation scene placement (scene is 1242 x 662). Socrates' body (cells 0-16) starts at x 377 in the
# left armchair, feet ending at y 531. Epictetus' body starts at cell 5; Seneca's body (cells 14-30)
# is centred on the right armchair, mirrored from Socrates' place in the left one.
FEET_Y = 313 + 31 * CHAT_CELL
CHAT_X0 = {"epictetus": 377 - 5 * CHAT_CELL, "seneca": 803 - 22.5 * CHAT_CELL}
# Rest frame used for the portrait, and the cells it shows (left column, top row).
PORTRAIT = {"seneca": ("home_seneca_17_rest_smile.png", 13.5, -1.5),
            "epictetus": ("home_epictetus_03_rest.png", 4.5, -2.0)}
PORTRAIT_SIZE, PORTRAIT_CELL = (408, 460), 20


def cells(path: Path) -> list[list[tuple]]:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    return [[px[HOME_X0 + HOME_CELL * i + 6, HOME_CELL * j + 6] for i in range((w - HOME_X0) // HOME_CELL)]
            for j in range(h // HOME_CELL)]


def drop_table_cup(grid: list[list[tuple]]) -> list[list[tuple]]:
    """Clear small detached pieces (the cup and saucer on the café table); keep the figure and the staff."""
    rows, cols = len(grid), len(grid[0])
    seen, out = set(), [row[:] for row in grid]
    for j in range(rows):
        for i in range(cols):
            if grid[j][i][3] == 0 or (j, i) in seen:
                continue
            part, todo = [], [(j, i)]
            seen.add((j, i))
            while todo:
                y, x = todo.pop()
                part.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        n = (y + dy, x + dx)
                        if 0 <= n[0] < rows and 0 <= n[1] < cols and n not in seen and grid[n[0]][n[1]][3]:
                            seen.add(n)
                            todo.append(n)
            height = max(y for y, _ in part) - min(y for y, _ in part) + 1
            if len(part) <= 16 and height <= 5:
                for y, x in part:
                    out[y][x] = CLEAR
    return out


def render(grid: list[list[tuple]], cell: int) -> Image.Image:
    im = Image.new("RGBA", (len(grid[0]) * cell, len(grid) * cell), CLEAR)
    for j, row in enumerate(grid):
        for i, colour in enumerate(row):
            if colour[3]:
                im.paste(colour, (i * cell, j * cell, (i + 1) * cell, (j + 1) * cell))
    return im


def portrait_background() -> Image.Image:
    """The olive backdrop shared by the existing portraits, taken wherever one of them shows it."""
    sources = [Image.open(ASSETS / f"portrait_{n}.png").convert("RGB")
               for n in ("socrates", "montaigne", "schopenhauer")]
    w, h = PORTRAIT_SIZE
    out = Image.new("RGB", (w, h))
    src = [s.load() for s in sources]
    px = out.load()
    for y in range(h):
        last = BG[0]
        for x in range(w):
            for s in src:
                if s[x, y] in BG:
                    last = s[x, y]
                    break
            px[x, y] = last
    return out


def portrait(who: str) -> Image.Image:
    frame, left, top = PORTRAIT[who]
    figure = render(drop_table_cup(cells(ASSETS / frame)), PORTRAIT_CELL)
    bg = portrait_background().convert("RGBA")
    bg.alpha_composite(figure, (round(-left * PORTRAIT_CELL), round(-top * PORTRAIT_CELL)))
    return bg.convert("RGB")


def build(who: str, data: dict) -> None:
    home = data.get("home_" + who) or {}
    home_frames = home.get("frames") or sorted(p.name for p in ASSETS.glob(f"home_{who}_*.png"))
    frames = []
    for name in home_frames:
        grid = drop_table_cup(cells(ASSETS / name))
        out = name.removeprefix("home_")
        render(grid, OUT_CELL).save(ASSETS / out)
        frames.append(out)
    rows, cols = len(grid), len(grid[0])
    x0, y0 = CHAT_X0[who], FEET_Y - rows * CHAT_CELL
    shutil.copyfile(ASSETS / "scene_socrates.png", ASSETS / f"scene_{who}.png")
    data[who] = {"scene": f"scene_{who}.png",
                 "box": [round(x0, 1), round(y0, 1), round(x0 + cols * CHAT_CELL, 1), round(FEET_Y, 1)],
                 "size": [1242, 662], "frames": frames, "seq": HOME_SEQ[who]}
    data["home_" + who] = {"box": HOME_BOX[who], "frames": home_frames, "seq": HOME_SEQ[who]}
    p = portrait(who)
    p.save(ASSETS / f"portrait_{who}.png")
    p.crop((0, 30, 408, 438)).resize((64, 64), Image.NEAREST).save(ASSETS / f"mono_{who}.png")
    print(f"{who}: {len(frames)} conversation frames, scene, portrait, avatar")


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    for who in ("seneca", "epictetus"):
        build(who, data)
    DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"updated {DATA.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
