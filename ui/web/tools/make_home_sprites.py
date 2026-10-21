"""Draw the café-home sprites for Montaigne and Schopenhauer from their conversation frames.

The prototype seated Seneca and Epictetus (home_seneca_*, home_epictetus_*) where Montaigne
and Schopenhauer should be. A home frame is the conversation frame's native pixel art drawn
at 12 px per pixel, plus the coffee cup where the home table needs it; Socrates, who has
both sets, is the reference. This script rebuilds the Socrates home frames from his
conversation frames to check the transform, then draws the other two.

    .venv/bin/python ui/web/tools/make_home_sprites.py          # check, write frames, update data.json
    .venv/bin/python ui/web/tools/make_home_sprites.py --check  # check only
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image

WEB = Path(__file__).resolve().parent.parent
ASSETS = WEB / "assets"
DATA = WEB / "data.json"

CELLS = 31            # conversation and home frames share a 31 x 31 pixel grid
CHAT_CELL = 7.04      # conversation frames: about 7.04 px per pixel (non-integer export)
HOME_CELL = 12        # home frames: exactly 12 px per pixel, starting 2 px in
HOME_X0 = 2
HOME_SIZE = (375, 372)
# Socrates frame (index in data.json) whose cup placement each pose uses.
POSE_REF = {"rest": 0, "ponder": 2, "reach": 4, "carry": 5, "hold": 6, "raise": 7, "sip": 8}
# Seats: the prototype's boxes for these two chairs, resized to the home frame and kept on the floor.
SEATS = {"montaigne": (750, 2508), "schopenhauer": (564, 2004)}     # (left, bottom) in home_bg pixels
CLEAR = (0, 0, 0, 0)


def chat_cells(path: Path) -> list[list[tuple]]:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    return [[px[min(w - 1, int((i + .5) * CHAT_CELL)), min(h - 1, int((j + .5) * CHAT_CELL))]
             for i in range(CELLS)] for j in range(CELLS)]


def home_cells(path: Path) -> list[list[tuple]]:
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    return [[px[HOME_X0 + HOME_CELL * i + 6, HOME_CELL * j + 6] if HOME_X0 + HOME_CELL * i + 6 < w and
             HOME_CELL * j + 6 < h else CLEAR for i in range(CELLS)] for j in range(CELLS)]


def render(cells: list[list[tuple]]) -> Image.Image:
    im = Image.new("RGBA", HOME_SIZE, CLEAR)
    px = im.load()
    for j, row in enumerate(cells):
        for i, colour in enumerate(row):
            if colour[3] == 0:
                continue
            for y in range(HOME_CELL * j, min(HOME_SIZE[1], HOME_CELL * (j + 1))):
                for x in range(HOME_X0 + HOME_CELL * i, min(HOME_SIZE[0], HOME_X0 + HOME_CELL * (i + 1))):
                    px[x, y] = colour
    return im


class Props:
    """Per pose, the cup cells that the conversation frame has but the home frame drops, and the
    ones the home frame adds, taken from Socrates."""

    def __init__(self, data: dict):
        self.chat = [chat_cells(ASSETS / f) for f in data["socrates"]["frames"]]
        self.home = [home_cells(ASSETS / f) for f in data["home_socrates"]["frames"]]

    def apply(self, cells: list[list[tuple]], ref: int) -> list[list[tuple]]:
        chat, home = self.chat[ref], self.home[ref]
        out = [row[:] for row in cells]
        for j in range(CELLS):
            for i in range(CELLS):
                if chat[j][i][3] and not home[j][i][3]:
                    out[j][i] = CLEAR                       # the conversation table's cup
                elif home[j][i][3] and not chat[j][i][3]:
                    out[j][i] = home[j][i]                  # the home table's cup
        return out


def pose_of(frame: str) -> str:
    return re.match(r"[a-z]+_\d+_([a-z]+)", frame).group(1)


def check(data: dict, props: Props) -> float:
    """Rebuild every Socrates home frame and return the worst share of matching cells."""
    worst = 1.0
    for k, (chat, home) in enumerate(zip(data["socrates"]["frames"], data["home_socrates"]["frames"])):
        built = props.apply(chat_cells(ASSETS / chat), POSE_REF[pose_of(chat)])
        real = home_cells(ASSETS / home)
        cells = [(built[j][i], real[j][i]) for j in range(CELLS) for i in range(CELLS)
                 if built[j][i][3] or real[j][i][3]]
        same = sum(1 for a, b in cells if a[3] and b[3] and max(abs(a[c] - b[c]) for c in range(3)) < 24)
        worst = min(worst, same / len(cells))
        print(f"  {home:44} {same}/{len(cells)} cells match")
    return worst


def build(data: dict, props: Props, who: str) -> dict:
    frames = []
    for chat in data[who]["frames"]:
        cells = props.apply(chat_cells(ASSETS / chat), POSE_REF[pose_of(chat)])
        name = "home_" + chat
        render(cells).save(ASSETS / name)
        frames.append(name)
    left, bottom = SEATS[who]
    seq = data[who]["seq"] + [[0, 6200 if who == "montaigne" else 5400]]   # a long rest, like the other seats
    start = len(seq) // 3                                                     # out of step with the others
    return {"box": [left, bottom - HOME_SIZE[1], left + HOME_SIZE[0], bottom], "frames": frames,
            "seq": seq[start:] + seq[:start]}


def main(argv: list[str]) -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    props = Props(data)
    print("Rebuilding Socrates' home frames from his conversation frames:")
    worst = check(data, props)
    print(f"worst frame: {worst:.1%} of cells match")
    if worst < 0.95:
        print("transform does not reproduce the reference; not writing frames")
        return 1
    if "--check" in argv:
        return 0
    for who in ("montaigne", "schopenhauer"):
        data["home_" + who] = build(data, props, who)
        print(f"wrote {len(data['home_' + who]['frames'])} frames for home_{who}")
    for unused in ("home_seneca", "home_epictetus"):
        data.pop(unused, None)
    DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"updated {DATA.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
