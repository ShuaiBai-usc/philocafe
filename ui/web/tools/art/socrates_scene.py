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

# The generated face is turned a little: its right eye sat 3 cells further out than the left
# one mirrored. Features are drawn symmetric about the face's centre line (between x 69 and
# 70, where the nose and the hair tufts put it): the left side is listed, the right side is
# its mirror, except where a mood is one-sided on purpose.
AXIS = 139                        # x -> AXIS - x mirrors a cell across the centre line


def mirror(cells):
    return [(AXIS - c[0],) + tuple(c[1:]) for c in cells]


def both(left, right=None):
    return (left, mirror(left) if right is None else right)


# brows: (x, row) per pixel, image-left brow (his right); inner ends at x 67 and 72
BROWS = {
    "attentive": both([(63, 54), (64, 54), (65, 54), (66, 54), (67, 54)]),
    "curious":   both([(63, 54), (64, 53), (65, 53), (66, 53), (67, 53)]),
    "amused":    both([(63, 53), (64, 53), (65, 54), (66, 54), (67, 54)]),
    "skeptical": both([(63, 54), (64, 53), (65, 52), (66, 52), (67, 53)], [(72, 55), (73, 55), (74, 54), (75, 54), (76, 54)]),
    "pondering": both([(63, 54), (64, 54), (65, 54), (66, 55), (67, 55)]),
    "pleased":   both([(63, 55), (64, 54), (65, 54), (66, 54), (67, 54)]),
}

# eyes when open: (x, row, colour); row 57 is the eye line, the eyes are x 64-67 and 73-76
EYES = {
    "attentive": both([(64, 57, "white"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "white2")]),
    "curious":   both([(64, 57, "white"), (65, 56, "pupil"), (66, 56, "pupil"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "white2")]),
    "amused":    both([(64, 57, "deep"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "deep"), (64, 58, "light"), (65, 58, "light"), (66, 58, "light"), (67, 58, "light")]),
    "skeptical": both([(64, 57, "white"), (65, 57, "pupil"), (66, 57, "pupil"), (67, 57, "white2")],
                      [(72, 56, "deep"), (73, 56, "deep"), (74, 56, "deep"), (75, 56, "deep"), (72, 57, "shade"), (73, 57, "dark"), (74, 57, "pupil"), (75, 57, "shade")]),
    "pondering": both([(64, 57, "white"), (65, 57, "white2"), (66, 57, "pupil"), (67, 57, "pupil")],          # both look to the side
                      [(72, 57, "white"), (73, 57, "white2"), (74, 57, "pupil"), (75, 57, "pupil")]),
    "pleased":   both([(64, 57, "dark"), (65, 56, "dark"), (66, 56, "dark"), (67, 57, "dark")]),
}

# the right eye sits on the shaded half of the face, where white2 reads as skin: its inner corner is plain white
# and the whole right eye sits one cell further out (Christopher's call: it reads as centred there)
for _m, (_l, _r) in EYES.items():
    EYES[_m] = (_l, [(x + 1, y, "white" if (x, y, c) == (72, 57, "white2") else c) for x, y, c in _r])

# mouth when closed, centred on the same line; talk frames open it in the same place
MOUTHS = {
    "attentive": [(67, 67, "dark"), (68, 67, "dark"), (69, 67, "lip"), (70, 67, "lip"), (71, 67, "dark"), (72, 67, "dark")],
    "curious":   [(68, 67, "dark"), (69, 67, "pupil"), (70, 67, "pupil"), (71, 67, "dark"), (69, 68, "inside"), (70, 68, "inside")],
    "amused":    [(66, 66, "dark"), (67, 67, "dark"), (68, 67, "white"), (69, 67, "white"), (70, 67, "white"), (71, 67, "white"), (72, 67, "dark"), (73, 66, "dark"),
                  (68, 68, "dark"), (69, 68, "lip"), (70, 68, "lip"), (71, 68, "dark")],
    "skeptical": [(66, 67, "dark"), (67, 67, "dark"), (68, 67, "dark"), (69, 67, "dark"), (70, 66, "dark"), (71, 66, "dark"), (72, 65, "dark")],
    "pondering": [(68, 67, "dark"), (69, 67, "dark"), (70, 67, "dark"), (71, 67, "dark")],
    "pleased":   [(66, 66, "dark"), (67, 67, "dark"), (68, 67, "dark"), (69, 67, "lip"), (70, 67, "lip"), (71, 67, "dark"), (72, 67, "dark"), (73, 66, "dark")],
}
TALK = {
    "talk1": [(68, 67, "pupil"), (69, 67, "pupil"), (70, 67, "pupil"), (71, 67, "pupil"), (69, 68, "lip"), (70, 68, "lip")],
    "talk2": [(67, 67, "pupil"), (68, 67, "pupil"), (69, 67, "pupil"), (70, 67, "pupil"), (71, 67, "pupil"), (72, 67, "pupil"),
              (68, 68, "pupil"), (69, 68, "lip"), (70, 68, "lip"), (71, 68, "pupil"), (69, 69, "inside"), (70, 69, "inside")],
}
# the mouth sits one cell right of the centre line (Christopher's call), like the right eye
MOUTHS = {m: [(x + 1, y, c) for x, y, c in cells] for m, cells in MOUTHS.items()}
TALK = {t: [(x + 1, y, c) for x, y, c in cells] for t, cells in TALK.items()}
BLUSH = {"amused": [(c, 59) for c in (63, 64, 75, 76)], "pleased": [(c, 59) for c in (62, 63, 64, 75, 76, 77)]}


def clean(base):
    """The face without the generated features: brows, eyes and mouth painted with the skin and beard around them."""
    p = base.copy()
    for x in range(62, 78):
        for y in (53, 54):                        # brows (and stray brow hairs) back to forehead skin
            if x not in (68, 69, 70, 71):
                p[y, x] = C["skin"] if x < 70 else C["skin2"]
    p[55, 62] = C["skin2"]                        # a stray brow hair at the left temple
    for x in range(63, 77):
        if x not in (68, 69, 70, 71):
            p[57, x] = base[58, x]                # eyes: the cheek just below
    for x in range(66, 76):
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


# The generated face is darker than his arms and feet: half of it sits in a mid shade the
# body never uses. Face skin goes onto the body's two tones (base, shade), keeping the
# forehead highlight, so face and hands are one skin.
FACE_SKIN = {
    (201, 152, 106): (223, 176, 128),   # mid shade -> body base
    (179, 140, 98): (196, 141, 101),    # deep mid shade -> body shade
    (165, 116, 76): (196, 141, 101),    # deep shade -> body shade
}
# the head's rows and right edge: above row 49 the picture frame's wood (same browns) starts
# at x 79, and the wall stripe above the crown ends at row 41
FACE_ROWS = [(y, 55, 78 if y < 49 else 80) for y in range(42, 63)]


def body_skin(img):
    p = img.copy()
    for y, x0, x1 in FACE_ROWS:
        row = p[y, x0:x1 + 1]
        for src, dst in FACE_SKIN.items():
            row[(row == src).all(1)] = dst
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
            sheet[i * h:(i + 1) * h, j * w:(j + 1) * w] = body_skin(frame(base, cleaned, mood, name))[y0:y0 + h, x0:x0 + w]
    attentive = body_skin(frame(base, cleaned, "attentive", "open"))
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
