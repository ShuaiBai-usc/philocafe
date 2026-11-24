"""Full-screen chat scenes for Montaigne, Schopenhauer, Seneca and Epictetus (the Socrates scene has its
own hand-tuned script, socrates_scene.py; these four follow its layout and timing).

Each scene is an ElevenLabs generation (Nano Banana 2) made from the Socrates scene and the philosopher's
bust: sources/<id>_seated_gen.jpg. pixelate.py puts it on its own 143 x 256 grid with 48 colours. The
expressions are edits of the generated face, placed from a few anchors read off each face (eye row and
pupils, brow row and spans, mouth row and span):
    half / closed   lid over the eyes / one lash line
    talk1 / talk2   the mouth opens a little / more
    curious         brows up, pupils a row taller
    amused          squint, cheeks up, mouth corners up, a blush
    skeptical       one brow up, the other down over a half-lidded eye
    pondering       inner brow ends down, pupils to the side
    pleased         eyes closed in arcs, corners up, a blush

    .venv/bin/python ui/web/tools/art/seated_scene.py [id ...]

writes ui/web/assets/personas/<id>/full/: scene.png, faces.png, faces.json (same format as Socrates).
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
GRID = (143, 256)
MOODS = ("attentive", "curious", "amused", "skeptical", "pondering", "pleased")
FRAMES = ("open", "half", "closed", "talk1", "talk2")

# anchors on the 143 x 256 grid: eye row, pupils (x0, x1) left and right, eye whites around them,
# brow row and spans, mouth row and span (x0, x1); 'dark_beard' mouths are drawn in lip red to show
FACES = {
    "montaigne":    dict(ey=60, lp=(65, 66), rp=(75, 76), lw=(64, 67), rw=(74, 77), by=57, lb=(63, 67), rb=(73, 77), my=69, mx=(67, 72), dark_beard=True),
    "schopenhauer": dict(ey=59, lp=(66, 66), rp=(75, 75), lw=(65, 67), rw=(74, 76), by=56, lb=(63, 66), rb=(75, 78), my=67, mx=(67, 74), dark_beard=False),
    "seneca":       dict(ey=57, lp=(65, 66), rp=(75, 76), lw=(64, 67), rw=(74, 77), by=55, lb=(63, 67), rb=(73, 77), my=68, mx=(67, 72), dark_beard=True),
    "epictetus":    dict(ey=57, lp=(65, 66), rp=(74, 75), lw=(64, 67), rw=(73, 76), by=54, lb=(63, 66), rb=(73, 76), my=67, mx=(67, 73), dark_beard=False),
}
BLUSH = (214, 140, 112)
TIMING = {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150]}


def mix(a, b, t=.5):
    return tuple(int(round(x * (1 - t) + y * t)) for x, y in zip(a, b))


def colours(p, f):
    ey = f["ey"]
    around = [tuple(p[y, x]) for y in (ey - 1, ey + 1) for x in range(f["lw"][0], f["rw"][1] + 1)]
    skin = tuple(int(v) for v in np.median(np.array(around), 0))
    pupil = tuple(int(v) for v in np.asarray([p[ey, x] for x in range(f["lp"][0], f["lp"][1] + 1)]).mean(0))
    brow = tuple(int(v) for v in np.asarray([p[f["by"], x] for x in range(*f["lb"])]).mean(0))
    forehead = tuple(int(v) for v in np.median(np.array([p[f["by"] - 2, x] for x in range(f["lb"][0], f["rb"][1] + 1)]), 0))
    return dict(skin=skin, shade=mix(skin, (90, 55, 30), .22), deep=mix(skin, (60, 35, 20), .4), light=mix(skin, (255, 240, 220), .3),
                pupil=pupil, dark=mix(pupil, skin, .35), brow=brow, forehead=forehead,
                white=(242, 234, 216), lip=(150, 74, 54), inside=(86, 50, 34))


def put(p, x, y, c):
    p[y, x] = c


def brow_cells(f, mood):
    """(x, y) of each brow pixel for a mood; left brow is image-left, inner ends nearest the nose."""
    (l0, l1), (r0, r1), by = f["lb"], f["rb"], f["by"]
    L = [(x, by) for x in range(l0, l1 + 1)]
    R = [(x, by) for x in range(r0, r1 + 1)]
    up = lambda cells: [(x, y - 1) for x, y in cells]
    down = lambda cells: [(x, y + 1) for x, y in cells]
    if mood == "curious":
        return up(L), up(R)
    if mood == "skeptical":
        return up(L), [(x, by + 1) if x <= r0 + 1 else (x, by) for x in range(r0, r1 + 1)]
    if mood == "pondering":
        return [(x, by + 1) if x >= l1 - 1 else (x, by) for x in range(l0, l1 + 1)], [(x, by + 1) if x <= r0 + 1 else (x, by) for x in range(r0, r1 + 1)]
    if mood == "amused":
        return [(x, by - 1) if x <= l0 + 1 else (x, by) for x in range(l0, l1 + 1)], [(x, by - 1) if x >= r1 - 1 else (x, by) for x in range(r0, r1 + 1)]
    return L, R


def frame(base, f, C, mood, name):
    p = base.copy()
    by, ey = f["by"], f["ey"]
    # brows: lift the generated ones off, then draw the mood's
    for x0, x1 in (f["lb"], f["rb"]):
        for x in range(x0, x1 + 1):
            p[by, x] = C["forehead"] if mood != "attentive" else base[by, x]
    for side in brow_cells(f, mood):
        for x, y in side:
            p[y, x] = C["brow"]
    eyes = [(f["lw"], f["lp"]), (f["rw"], f["rp"])]
    state = name if name in ("half", "closed") else "open"
    for k, ((w0, w1), (p0, p1)) in enumerate(eyes):
        right = k == 1
        e_state = "half" if (mood == "skeptical" and right and state == "open") else state
        if mood == "pleased":                                   # closed, smiling arcs
            for x in range(w0, w1 + 1):
                p[ey, x] = C["skin"]
            p[ey, w0] = p[ey, w1] = C["dark"]
            for x in range(w0 + 1, w1):
                p[ey - 1, x] = C["dark"]
            continue
        if e_state == "closed":
            for x in range(w0, w1 + 1):
                p[ey, x] = C["dark"]
            continue
        if e_state == "half":
            for x in range(w0, w1 + 1):
                p[ey, x] = C["dark"] if p0 <= x <= p1 else C["shade"]
                p[ey - 1, x] = C["deep"]
            continue
        if mood == "curious":
            for x in range(p0, p1 + 1):
                p[ey - 1, x] = C["pupil"]
        elif mood == "amused":
            for x in (w0, w1):
                p[ey, x] = C["deep"]
            for x in range(w0, w1 + 1):
                p[ey + 1, x] = C["light"]
        elif mood == "pondering":                               # both look to the image-right
            for x in range(w0, w1 + 1):
                p[ey, x] = C["white"] if x < w1 - (p1 - p0) else C["pupil"]
    if mood in ("amused", "pleased"):
        for x in (f["lw"][0] - 1, f["lw"][0], f["rw"][1], f["rw"][1] + 1):
            p[ey + 2, x] = BLUSH
    # mouth
    my, (m0, m1) = f["my"], f["mx"]
    lipc = C["lip"] if f["dark_beard"] else C["dark"]
    mid0, mid1 = (m0 + m1) // 2 - 1, (m0 + m1) // 2 + 1
    if mood in ("amused", "pleased") and name not in TALKS:
        p[my - 1, m0] = p[my - 1, m1] = lipc
        for x in range(m0 + 1, m1):
            p[my, x] = lipc
        if mood == "amused":
            for x in range(mid0, mid1 + 1):
                p[my, x] = C["white"]
    elif mood == "skeptical" and name not in TALKS:
        for x in range(m0, m1 + 1):
            p[my - (1 if x > mid1 else 0), x] = lipc
    elif mood == "curious" and name not in TALKS:
        for x in range(mid0, mid1):
            p[my, x] = C["inside"]
    if name == "talk1":
        for x in range(mid0, mid1 + 1):
            p[my, x] = C["inside"]
        p[my + 1, mid0 + 1] = C["lip"]
    elif name == "talk2":
        for x in range(mid0 - 1, mid1 + 2):
            p[my, x] = C["inside"]
        for x in range(mid0, mid1 + 1):
            p[my + 1, x] = C["lip"] if mid0 < x < mid1 else C["inside"]
    return p


TALKS = ("talk1", "talk2")


def build(pid):
    f = FACES[pid]
    src = np.asarray(Image.open(HERE / f"sources/{pid}_seated_gen.jpg").convert("RGB")).astype(float)
    nw, nh, ox, oy = find_grid(src, [GRID[0]], [GRID[1]])
    base = np.asarray(quantize(sample(src, nw, nh, ox, oy), 48)).copy()
    C = colours(base, f)
    x0, x1 = min(f["lw"][0], f["lb"][0]) - 3, max(f["rw"][1], f["rb"][1]) + 3
    y0, y1 = f["by"] - 3, f["my"] + 3
    P = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    w, h = P[2], P[3]
    sheet = np.zeros((h * len(MOODS), w * len(FRAMES), 3), np.uint8)
    for i, mood in enumerate(MOODS):
        for j, name in enumerate(FRAMES):
            sheet[i * h:(i + 1) * h, j * w:(j + 1) * w] = frame(base, f, C, mood, name)[y0:y0 + h, x0:x0 + w]
    out = ROOT / f"ui/web/assets/personas/{pid}/full"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame(base, f, C, "attentive", "open")).save(out / "scene.png", optimize=True)
    Image.fromarray(sheet).save(out / "faces.png", optimize=True)
    face_x = (f["lp"][0] + f["rp"][1]) / 2
    meta = {"grid": list(GRID), "patch": {"x": x0, "y": y0, "w": w, "h": h}, "moods": list(MOODS), "frames": list(FRAMES),
            "anchor": {"face": [round(face_x), f["ey"] + 3], "head": [x0 - 4, f["by"] - 16, x1 + 4, f["my"] + 10]},
            "source": f"{pid}_seated_gen.jpg", "palette": 48, "timing_ms": TIMING}
    (out / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(pid, f"grid {nw}x{nh} offset ({ox}, {oy}) patch {P}")


if __name__ == "__main__":
    for pid in sys.argv[1:] or list(FACES):
        build(pid)
