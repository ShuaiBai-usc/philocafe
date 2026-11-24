"""Socrates' full-screen chat scene: a generated picture turned into true pixel art.

1. sources/socrates_seated_gen.webp was generated (ElevenLabs, Nano Banana 2, 9:16, 768 x 1376;
   the bust and the café scene as references) and picked by Christopher (sample #4). It is
   stored losslessly.
2. pixelate.py finds the picture's own pixel grid (143 x 256 cells of about 5.4 px), takes the
   median of each cell's centre and reduces the colours to 48 with k-means in Lab space.
   The scene no longer depends on the bust; it keeps its own head and proportions.
3. Expressions are small patches over the face (brows, eyes, mouth, cheeks), drawn here
   by hand on the scene's own palette: one row per mood, columns open, half, closed, talk1,
   talk2. A mood change goes through a blink (open, half, closed, then the new mood's half
   and open), so the switch is hidden behind closed eyes.

    .venv/bin/python ui/web/tools/art/socrates_scene.py

writes ui/web/assets/personas/socrates/full/: scene.png (143 x 256, the attentive face),
faces.png and faces.json. The table that will cover his lower half is a separate layer,
added later.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pixelate import find_grid, quantize, sample  # noqa: E402

ROOT = HERE.parents[3]
OUT = ROOT / "ui/web/assets/personas/socrates/full"
SOURCE = HERE / "sources/socrates_seated_gen.webp"
GRID = (143, 256)
COLOURS = 48

MOODS = ("attentive", "curious", "amused", "skeptical", "pondering", "pleased")
FRAMES = ("open", "half", "closed", "talk1", "talk2")
PATCH = (61, 52, 18, 19)          # x, y, w, h on the scene: brows, eyes, cheeks, mouth

# the scene's own colours around the face (all from the 48-colour palette, plus a blush)
C = {
    "skin": (223, 176, 128), "skin2": (201, 152, 106), "shade": (196, 141, 101), "deep": (165, 116, 76),
    "light": (241, 204, 165), "brow": (153, 144, 123), "pupil": (62, 44, 27), "dark": (124, 94, 62),
    "white": (243, 236, 218), "white2": (230, 220, 188), "mouth": (136, 102, 66), "lip": (147, 73, 51), "inside": (102, 76, 49), "blush": (214, 140, 112),
}

# brows: (x, row) per pixel; left brow is image-left (his right), inner end at x 67 / 73
BROWS = {
    "attentive": ([(63, 54), (64, 54), (65, 54), (66, 54), (67, 54)], [(73, 54), (74, 54), (75, 54), (76, 54)]),
    "curious":   ([(63, 54), (64, 53), (65, 53), (66, 53), (67, 53)], [(73, 53), (74, 53), (75, 53), (76, 54)]),
    "amused":    ([(63, 54), (64, 53), (65, 53), (66, 54), (67, 54)], [(73, 54), (74, 54), (75, 53), (76, 53)]),
    "skeptical": ([(63, 54), (64, 53), (65, 52), (66, 52), (67, 53)], [(73, 55), (74, 55), (75, 54), (76, 54)]),
    "pondering": ([(63, 54), (64, 54), (65, 54), (66, 55), (67, 55)], [(73, 55), (74, 55), (75, 54), (76, 54)]),
    "pleased":   ([(63, 55), (64, 54), (65, 54), (66, 54), (67, 54)], [(73, 54), (74, 54), (75, 54), (76, 55)]),
}

# eyes when open: per side, a list of (x, row, colour); row 57 is the eye line
EYES = {
    "attentive": ([(64, 57, "white"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "white2")],
                  [(74, 57, "dark"), (75, 57, "pupil"), (76, 57, "white2")]),
    "curious":   ([(64, 57, "white"), (65, 56, "pupil"), (66, 56, "pupil"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "white2")],
                  [(74, 56, "pupil"), (75, 56, "pupil"), (74, 57, "pupil"), (75, 57, "pupil"), (76, 57, "white2")]),
    "amused":    ([(64, 57, "deep"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "deep"), (64, 58, "light"), (65, 58, "light"), (66, 58, "light"), (67, 58, "light")],
                  [(74, 57, "pupil"), (75, 57, "pupil"), (76, 57, "deep"), (74, 58, "light"), (75, 58, "light")]),
    "skeptical": ([(64, 57, "white"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "white2")],
                  [(74, 56, "deep"), (75, 56, "deep"), (76, 56, "deep"), (74, 57, "dark"), (75, 57, "pupil"), (76, 57, "shade")]),
    "pondering": ([(64, 57, "white"), (65, 57, "white"), (66, 57, "pupil"), (67, 57, "pupil")],
                  [(74, 57, "white"), (75, 57, "pupil"), (76, 57, "pupil")]),
    "pleased":   ([(64, 57, "dark"), (65, 56, "dark"), (66, 56, "dark"), (67, 57, "dark")],
                  [(73, 57, "dark"), (74, 56, "dark"), (75, 56, "dark"), (76, 57, "dark")]),
}

# mouth when closed; talk frames open it in the same place
MOUTHS = {
    "attentive": [(68, 67, "dark"), (69, 67, "lip"), (70, 67, "mouth"), (71, 67, "dark"), (72, 67, "dark"), (73, 67, "dark"), (74, 67, "dark")],
    "curious":   [(69, 67, "dark"), (70, 67, "pupil"), (71, 67, "pupil"), (72, 67, "dark"), (70, 68, "inside"), (71, 68, "inside")],
    "amused":    [(67, 66, "dark"), (68, 67, "dark"), (69, 67, "white"), (70, 67, "white"), (71, 67, "white"), (72, 67, "white"), (73, 67, "white"), (74, 67, "dark"), (75, 66, "dark"),
                  (69, 68, "dark"), (70, 68, "lip"), (71, 68, "lip"), (72, 68, "lip"), (73, 68, "dark")],
    "skeptical": [(68, 67, "dark"), (69, 67, "dark"), (70, 67, "dark"), (71, 67, "dark"), (72, 66, "dark"), (73, 66, "dark"), (74, 65, "dark")],
    "pondering": [(69, 67, "dark"), (70, 67, "dark"), (71, 67, "dark"), (72, 67, "dark")],
    "pleased":   [(67, 66, "dark"), (68, 67, "dark"), (69, 67, "lip"), (70, 67, "dark"), (71, 67, "dark"), (72, 67, "dark"), (73, 67, "dark"), (74, 66, "dark")],
}
TALK = {
    "talk1": [(69, 67, "pupil"), (70, 67, "pupil"), (71, 67, "pupil"), (72, 67, "pupil"), (70, 68, "lip"), (71, 68, "lip")],
    "talk2": [(69, 67, "pupil"), (70, 67, "pupil"), (71, 67, "pupil"), (72, 67, "pupil"), (73, 67, "pupil"),
              (69, 68, "pupil"), (70, 68, "lip"), (71, 68, "lip"), (72, 68, "lip"), (73, 68, "pupil"), (70, 69, "inside"), (71, 69, "inside"), (72, 69, "inside")],
}
BLUSH = {"amused": [(63, 59), (64, 59), (76, 59), (77, 59)], "pleased": [(63, 59), (64, 59), (65, 59), (75, 59), (76, 59), (77, 59)]}


def clean(base):
    """The face without its features: each brow, eye and mouth pixel painted with what is next to it."""
    p = base.copy()
    for x in list(range(63, 68)) + list(range(73, 77)):
        p[54, x] = base[53, x]                    # brows: forehead skin from the row above
    for x in list(range(64, 68)) + list(range(74, 77)):
        p[57, x] = C["skin2"]                     # eyes: cheek skin
    for x in range(68, 75):
        p[67, x] = base[68, x]                    # mouth line: the beard just below it
    return p


def eyes_for(mood, state):
    out = []
    for side in EYES[mood]:
        if state == "open" or mood == "pleased":
            out += side
            continue
        xs = sorted({x for x, _, _ in side})
        if state == "half":                       # upper lid down: lid line above, pupils dimmed, whites covered
            for x, r, c in side:
                if r == 57:
                    out.append((x, r, "dark" if c == "pupil" else "skin2"))
            out += [(x, 56, "deep") for x in xs]
        else:                                     # closed: one lash line
            out += [(x, 57, "dark") for x in xs]
    return out


def frame(base, cleaned, mood, name):
    p = cleaned.copy()
    for side in BROWS[mood]:
        for x, r in side:
            p[r, x] = C["brow"]
    state = name if name in ("half", "closed") else "open"
    for x, r, c in eyes_for(mood, state):
        p[r, x] = C[c]
    for x, r in BLUSH.get(mood, []):
        p[r, x] = C["blush"]
    for x, r, c in MOUTHS[mood]:
        p[r, x] = C[c]
    if name in TALK:
        for x, r, c in TALK[name]:
            p[r, x] = C[c]
    return p


def main():
    src = np.asarray(Image.open(SOURCE).convert("RGB")).astype(float)
    nw, nh, ox, oy = find_grid(src, [GRID[0]], [GRID[1]])
    scene = quantize(sample(src, nw, nh, ox, oy), COLOURS)
    base = np.asarray(scene).copy()
    cleaned = clean(base)
    x0, y0, w, h = PATCH
    sheet = np.zeros((h * len(MOODS), w * len(FRAMES), 3), np.uint8)
    for i, mood in enumerate(MOODS):
        for j, name in enumerate(FRAMES):
            sheet[i * h:(i + 1) * h, j * w:(j + 1) * w] = frame(base, cleaned, mood, name)[y0:y0 + h, x0:x0 + w]
    attentive = frame(base, cleaned, "attentive", "open")
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(attentive).save(OUT / "scene.png", optimize=True)
    Image.fromarray(sheet).save(OUT / "faces.png", optimize=True)
    meta = {
        "grid": list(GRID),
        "patch": {"x": x0, "y": y0, "w": w, "h": h},
        "moods": list(MOODS),
        "frames": list(FRAMES),
        "anchor": {"face": [70, 60], "head": [54, 38, 88, 82]},
        "source": SOURCE.name,
        "palette": COLOURS,
        "timing_ms": {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150]},
    }
    (OUT / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"grid {nw} x {nh}, offset ({ox}, {oy}); wrote {OUT}")


if __name__ == "__main__":
    main()
