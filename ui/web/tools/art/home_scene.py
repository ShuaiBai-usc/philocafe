"""The café for the full-screen home (assets/home/: cafe.png, people.png, ambient.png, home.json).

Two ElevenLabs edits (Nano Banana 2) of one flat, front-view Stardew-style café drawn in the chat scenes'
style: sources/home_people_gen.jpg has the five philosophers in their armchairs (square side tables drawn
straight from the front, so no surface shows a top in perspective), and sources/home_plate_gen.jpg is the
same picture with the armchairs empty. Both are read on the same 143 x 256 grid and palette; the cells
that differ around each face are that philosopher, and the empty chair is what is behind him (as in
face_sheet.py for the chat scenes). Ten rows of plain wall go into the top band so the wordmark has room.

Each philosopher gets four frames of his own rectangle (people.png, one row each): breathing in (head
and shoulders up a row, the chest row stretches), a nod (head and beard down a row), and a blink on each
of those two (the eye cells take the cheek's colour). The page draws the café, then each philosopher's
current frame, then the room's own motion (ambient.py: leaves leaning, the cat and the poodle breathing,
the poodle perking up and wagging now and then, two small flames) and loose pixels (dust under the
lamps, steam off Socrates' cup).

    python3 ui/web/tools/art/home_scene.py        (needs opencv-python)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pixelate import find_grid, quantize, sample  # noqa: E402
import ambient  # noqa: E402
import layers  # noqa: E402

ROOT = HERE.parents[3]
OUT = ROOT / "ui/web/assets/home"
GRID = (143, 256)
WALL = (20, 10, 20)            # insert rows 10..19 again at row 20: the logo's room on the striped wall

# seed (a face cell), box the philosopher stays inside, eyes (approximate cells; the darkest cell
# within one is used), chin (last row of head and beard: what nods), breath (the chest row that stretches)
PEOPLE = {
    "socrates":     {"seed": (39, 65), "box": (20, 56, 58, 110), "eyes": [(37, 65), (40, 65)], "chin": 71, "breath": 78},
    "montaigne":    {"seed": (107, 65), "box": (88, 55, 128, 108), "eyes": [(107, 64), (110, 64)], "chin": 68, "breath": 76},
    "seneca":       {"seed": (34, 131), "box": (14, 122, 57, 170), "eyes": [(32, 130), (35, 130)], "chin": 135, "breath": 142},
    "schopenhauer": {"seed": (110, 131), "box": (93, 122, 130, 170), "eyes": [(109, 130), (112, 130)], "chin": 133, "breath": 141},
    "epictetus":    {"seed": (72, 187), "box": (46, 178, 92, 232), "eyes": [(69, 188), (72, 188)], "chin": 193, "breath": 200},
}
AMBIENT = [
    ("sway", (55, 54, 71, 67)),                      # Socrates' plant
    ("sway", (80, 124, 99, 146)),                    # Schopenhauer's fern
    ("breathe", (86, 103, 108, 118)),                # Montaigne's cat
    ("breathe", (89, 151, 106, 175), [(89, 151, 106, 175)]),           # the poodle
    ("perk", (89, 151, 106, 175), (92, 151, 106, 161), [(89, 151, 106, 175)]),
    ("wag", (89, 151, 106, 175), (89, 163, 94, 173), [(89, 151, 106, 175)]),
    ("flame", (58, 141, 68, 151)),                   # Seneca's oil lamp
    ("flame", (89, 200, 100, 211)),                  # Epictetus' clay lamp
]
LAMPS = [(33, 52), (59, 52), (108, 52)]            # under each pendant lamp's shade: where the dust drifts
TIMING = {"breath": [1700, 2300], "blink_every": [2600, 6500], "blink": 140, "nod_every": [7000, 16000], "nod": 320,
          "pet_every": [9000, 18000]}


def lum(c):
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


def person(base, plate, d, f):
    import cv2
    x0, y0, x1, y1 = f["box"]
    box = np.zeros(d.shape, bool)
    box[y0:y1 + 1, x0:x1 + 1] = True
    m = layers.keep_component((d > 28) & box, f["seed"])
    grown = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    m |= grown & (d > 12) & box                     # his outline's softer cells, so no ring is left behind
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
    m = layers.fill_holes(m)
    back = base.copy()
    back[m] = plate[m]
    return m, back


def eyes(base, f):
    """the darkest cell near each estimate; returns [(x, y, cheek colour)]"""
    out = []
    for ex, ey in f["eyes"]:
        cand = [(lum(base[y, x]), x, y) for y in range(ey - 1, ey + 2) for x in range(ex - 1, ex + 2)]
        _, x, y = min(cand)
        out.append((x, y, base[y + 1, x].copy()))
    return out


def blink(img, ey, dy=0):
    out = img.copy()
    for x, y, cheek in ey:
        out[y + dy, x] = cheek
    return out


def insert_wall(a):
    at, a0, a1 = WALL
    return np.concatenate([a[:at], a[a0:a1], a[at:]])


def shift(y):
    return y + (WALL[2] - WALL[1]) if y >= WALL[0] else y


def build():
    src = np.asarray(Image.open(HERE / "sources/home_people_gen.jpg").convert("RGB")).astype(float)
    grid = find_grid(src, [GRID[0]], [GRID[1]])
    base = np.asarray(quantize(sample(src, *grid), 48)).copy()
    psrc = np.asarray(Image.open(HERE / "sources/home_plate_gen.jpg").convert("RGB")).astype(float)
    plate = layers.palette_snap(np.asarray(sample(psrc, *grid)).astype(np.uint8), base)
    d = np.abs(base.astype(int) - plate.astype(int)).sum(2)
    OUT.mkdir(parents=True, exist_ok=True)
    H, W = base.shape[:2]

    people, rows = {}, []
    masks = np.zeros(base.shape[:2], bool)
    for pid, f in PEOPLE.items():
        M, back = person(base, plate, d, f)
        masks |= M
        top = int(np.nonzero(M.any(1))[0].min())
        ys, xs = np.nonzero(M)
        rx0, ry0, rx1, ry1 = max(0, xs.min() - 1), max(0, top - 1), min(W - 1, xs.max() + 1), min(H - 1, ys.max() + 1)
        inn = layers.compose(base, back, M, ambient.rise(M, top, f["breath"]))
        head = layers.rows(M, top, f["chin"])
        sx = f["seed"][0]
        head[:, :sx - 9] = False
        head[:, sx + 10:] = False
        head = layers.keep_component(head, f["seed"])
        nod = layers.compose(base, back, M, [(head, 0, 1)])
        ey = eyes(base, f)
        frames = [inn, nod, blink(base, ey), blink(inn, ey, -1)]
        rows.append([fr[ry0:ry1 + 1, rx0:rx1 + 1] for fr in frames])
        people[pid] = {"x": int(rx0), "y": shift(int(ry0)), "w": int(rx1 - rx0 + 1), "h": int(ry1 - ry0 + 1),
                       "tap": [int(xs.min()), shift(int(ys.min())), int(xs.max()), shift(int(ys.max()))]}

    width = max(r[0].shape[1] for r in rows) * 4
    sheet = np.zeros((sum(r[0].shape[0] for r in rows), width, 3), np.uint8)
    sy = 0
    for (pid, p), r in zip(people.items(), rows):
        for k, fr in enumerate(r):
            sheet[sy:sy + p["h"], k * p["w"]:(k + 1) * p["w"]] = fr
        p["sy"] = sy
        sy += p["h"]
    Image.fromarray(sheet).save(OUT / "people.png", optimize=True)

    els = ambient.build(base, AMBIENT)
    amb, sy = [], 0
    width = max((r[2] - r[0] + 1) * len(fr) for r, fr, _ in els)
    sheet_a = np.zeros((sum(r[3] - r[1] + 1 for r, _, _ in els), width, 3), np.uint8)
    for (ax0, ay0, ax1, ay1), frames, info in els:
        aw, ah = ax1 - ax0 + 1, ay1 - ay0 + 1
        for k, fr in enumerate(frames):
            sheet_a[sy:sy + ah, k * aw:(k + 1) * aw] = fr[ay0:ay1 + 1, ax0:ax1 + 1]
        amb.append({"x": int(ax0), "y": shift(int(ay0)), "w": aw, "h": ah, "sy": sy, "frames": len(frames), **info})
        sy += ah
    Image.fromarray(sheet_a).save(OUT / "ambient.png", optimize=True)

    cafe = insert_wall(base)
    Image.fromarray(cafe).save(OUT / "cafe.png", optimize=True)
    meta = {"grid": [W, cafe.shape[0]], "people": people, "ambient": amb, "timing_ms": TIMING,
            "particles": {"dust": [{"x": x, "y": shift(y), "spread": 12, "depth": 16} for x, y in LAMPS],
                          "steam": [59, shift(79)]},
            "source": ["home_people_gen.jpg", "home_plate_gen.jpg"], "palette": 48}
    (OUT / "home.json").write_text(json.dumps(meta, indent=1) + "\n")
    print("cafe", cafe.shape[1], "x", cafe.shape[0], {k: (v["x"], v["y"], v["w"], v["h"]) for k, v in people.items()})


if __name__ == "__main__":
    build()
