"""Scenes and face sheets for the five full-screen chats (current art: the first Schopenhauer scene and the
other four restyled after it, see CLAUDE.md).

Each scene is an ElevenLabs generation put on the 143 x 256 grid with 48 colours (pixelate.py). The face
sheet (rows = moods, columns = frames, same layout as before) is made by editing that face, from a few
anchors per persona read off the grid:
    eyes    a box per eye: top row = the upper lid, bottom row = the eye itself; the pupil's columns
    brows   a box around each brow; the brow is whatever in the box is not skin, so it can be lifted or tilted
    mouth   the row of the mouth line and its columns
Frames: open, half (lid down to the pupil), closed (one lash line), talk1 / talk2 (the mouth opens).
Moods: attentive (the face as drawn), curious (brows up, eyes a row taller when 5+ cells wide), amused (squint, cheeks up,
corners up, blush), skeptical (one brow up, the other's inner end down, that eye half shut), pondering
(inner brow ends down, eyes to the side), pleased (closed smiling eyes, corners up, blush).

Before the face: the pendant lamp moves off the middle where `lamp` names a new centre column (it is the
cells in the top 34 rows that differ from their column's wallpaper; the stripes are vertical, so each
column's own colour fills the hole).

After the face, two poses for the body (design: still art that breathes and nods):
    scene_in.png    breathing in: the person's head and shoulders, down to `breath` row, one row up
    scene_nod.png   a nod: the head, down to `chin` row, one row down (the wallpaper above fills the gap)
The person is found with GrabCut (OpenCV) seeded with the face and chest as person and the sage armchair
and rug as not, plus any black clothes joined to the chest. faces.json gives each pose's row shift so the
page moves the face patch with it.

    python3 ui/web/tools/art/face_sheet.py [id ...]       # needs opencv-python (cv2), numpy, Pillow
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
TIMING = {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150],
          "breath": [1500, 1700], "nod_every": [1800, 4200], "nod": 260}

# eyes: (x0, x1, lid row, eye row) and pupil (p0, p1), image-left eye first; brows: (x0, x1, y0, y1);
# mouth: (row, x0, x1), the line between the lips just under the moustache, not the beard below it; lips=True draws the open mouth's lip in red (for mouths inside a dark beard)
FACES = {
    "socrates": dict(src="socrates_restyled_gen.jpg",
                     eyes=[((64, 66, 57, 58), (65, 65)), ((74, 76, 57, 58), (75, 75))],
                     brows=[(62, 67, 54, 56), (73, 78, 54, 56)], mouth=(67, 67, 73), lips=False, breath=100, chin=84),
    "montaigne": dict(src="montaigne_restyled_gen.jpg",
                      eyes=[((63, 68, 60, 61), (66, 67)), ((73, 79, 60, 61), (76, 77))],
                      brows=[(63, 69, 57, 58), (73, 79, 57, 58)], mouth=(68, 69, 74), lips=True, breath=98, chin=76, lamp=100),
    "seneca": dict(src="seneca_restyled_gen.jpg",
                   eyes=[((64, 67, 57, 58), (65, 66)), ((74, 77, 57, 58), (75, 76))],
                   brows=[(62, 69, 54, 56), (72, 79, 54, 56)], mouth=(67, 68, 74), lips=True, breath=100, chin=82, lamp=101),
    "epictetus": dict(src="epictetus_restyled_gen.jpg",
                      eyes=[((64, 67, 57, 58), (66, 66)), ((73, 76, 57, 58), (75, 75))],
                      brows=[(63, 68, 54, 56), (72, 78, 54, 56)], mouth=(67, 67, 74), lips=False, breath=100, chin=86),
    "schopenhauer": dict(src="schopenhauer_seated_gen.jpg",
                         eyes=[((64, 67, 58, 59), (66, 66)), ((74, 77, 58, 59), (75, 75))],
                         brows=[(62, 69, 55, 57), (72, 79, 55, 57)], mouth=(67, 68, 73), lips=False, breath=98, chin=76, lamp=38),
}
BLUSH = (214, 140, 112)
INSIDE = (92, 46, 38)
LIP = (168, 86, 70)


def mix(a, b, t):
    return tuple(int(round(x * (1 - t) + y * t)) for x, y in zip(a, b))


def lum(c):
    return sum(int(v) for v in c) / 3


class Face:
    def __init__(self, base, f):
        self.base, self.f = base, f
        (e0, p0), (e1, _) = f["eyes"]
        y = e0[3] + 2
        cheek = [tuple(base[y, x]) for x in range(e0[0], e1[1] + 1)]
        self.skin = tuple(int(v) for v in np.median(np.array(cheek), 0))
        lids = [tuple(base[e[2], x]) for e, _ in f["eyes"] for x in range(e[0], e[1] + 1)]
        self.lash = min(lids, key=lum)
        if lum(self.lash) < 60:                 # a black lid line reads too heavy as a closed eye
            self.lash = mix(self.lash, self.skin, .3)
        self.pupil = min((tuple(base[e[3], x]) for e, (a, b) in f["eyes"] for x in range(a, b + 1)), key=lum)
        self.white = (240, 232, 214)
        self.shade = mix(self.skin, (80, 45, 25), .25)
        self.light = mix(self.skin, (255, 240, 220), .3)

    def skinlike(self, c):
        return np.abs(np.asarray(c, float) - np.asarray(self.skin, float)).sum() < 75

    def skin_at(self, p, x, y):
        """the skin just below (x, y), for painting over an eye"""
        for yy in (y + 1, y + 2):
            if self.skinlike(p[yy, x]):
                return tuple(p[yy, x])
        return self.skin

    # --- brows -------------------------------------------------------------------------------------
    def brow(self, p, k, how):
        x0, x1, y0, y1 = self.f["brows"][k]
        src = self.base
        cells = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if not self.skinlike(src[y, x])]
        cols = {xy: tuple(src[xy[1], xy[0]]) for xy in cells}
        centre = (self.f["eyes"][0][0][1] + self.f["eyes"][1][0][0]) / 2
        mid = (x0 + x1) / 2
        inner = (lambda x: x >= mid) if k == 0 else (lambda x: x <= mid)
        if how == "up":
            dy = lambda x: -1
        elif how == "inner_down":
            dy = lambda x: 1 if inner(x) else 0
        elif how == "outer_up":
            dy = lambda x: -1 if not inner(x) else 0
        else:
            return
        for x, y in cells:
            p[y, x] = self.skin_at(src, x, y1) if y == y1 else tuple(src[y0 - 1, x]) if self.skinlike(src[y0 - 1, x]) else self.skin
        for (x, y), c in cols.items():
            p[y + dy(x), x] = c

    # --- eyes --------------------------------------------------------------------------------------
    def eye(self, p, k, how):
        (x0, x1, t, b), (p0, p1) = self.f["eyes"][k]
        if how == "open":
            return
        if how in ("closed", "pleased"):
            for x in range(x0, x1 + 1):
                s = self.skin_at(p, x, b)
                p[t, x] = s; p[b, x] = s
            if how == "closed":
                for x in range(x0, x1 + 1): p[b, x] = self.lash
            else:
                p[b, x0] = p[b, x1] = self.lash
                for x in range(x0 + 1, x1): p[t, x] = self.lash
        elif how == "half":
            for x in range(x0, x1 + 1):
                p[t, x] = self.shade
                p[b, x] = self.pupil if p0 <= x <= p1 else self.lash
        elif how == "wide":                     # a row taller; an eye under 5 cells wide stays as drawn
            if x1 - x0 + 1 >= 5:
                for x in range(x0 + 1, x1): p[t - 1, x] = self.lash
                for x in range(x0 + 1, x1): p[t, x] = self.pupil if p0 <= x <= p1 else self.white
        elif how == "squint":                   # the whites go to lid shade, the cheek rises under the eye
            for x in range(x0, x1 + 1):
                if not (p0 <= x <= p1) and lum(p[b, x]) > lum(self.skin) + 15:
                    p[b, x] = self.shade
                p[b + 1, x] = self.light
        elif how == "side":                     # both pupils one column to the image-right
            for y in (t, b):
                row = [tuple(p[y, x]) for x in range(x0, x1 + 1)]
                if y == b or any(lum(c) < lum(self.pupil) + 8 for c in row[p0 - x0:p1 - x0 + 1]):
                    if p1 + 1 <= x1 and y == b:
                        fill = tuple(p[b, p1 + 1])
                        p[b, p1 + 1] = self.pupil
                        p[b, p0] = fill if lum(fill) > 150 else self.white

    def blush(self, p):
        for (x0, x1, t, b), _ in self.f["eyes"]:
            for x in (x0 - 1, x1 + 1):
                p[b + 2, x] = BLUSH

    # --- mouth -------------------------------------------------------------------------------------
    def mouth(self, p, how):
        y, x0, x1 = self.f["mouth"]
        line = min((tuple(self.base[y, x]) for x in range(x0, x1 + 1)), key=lum)
        cx = (x0 + x1) / 2
        m0, m1 = int(np.floor(cx)) - 1, int(np.ceil(cx)) + 1
        lip = LIP if self.f["lips"] else mix(self.skin, (150, 70, 55), .45)
        if how == "smile":
            p[y - 1, x0] = p[y - 1, x1] = line
            for x in range(x0 + 1, x1): p[y, x] = line
        elif how == "talk1":
            for x in range(m0, m1 + 1): p[y, x] = INSIDE
            for x in range(m0 + 1, m1): p[y + 1, x] = lip
        elif how == "talk2":
            for x in range(m0 - 1, m1 + 2): p[y, x] = INSIDE
            for x in range(m0, m1 + 1): p[y + 1, x] = INSIDE
            for x in range(m0 + 1, m1): p[y + 2, x] = lip
        elif how == "smirk":
            for x in range(int(cx), x1 + 1): p[y - 1, x] = line
            p[y, x1] = tuple(self.base[y + 1, x1])

    # --- one cell of the sheet ---------------------------------------------------------------------
    def frame(self, mood, name):
        p = self.base.copy()
        brows = {"curious": ("up", "up"), "skeptical": ("up", "inner_down"), "pondering": ("inner_down", "inner_down"),
                 "amused": ("outer_up", "outer_up")}.get(mood, (None, None))
        for k in (0, 1):
            self.brow(p, k, brows[k])
        blink = name if name in ("half", "closed") else None
        for k in (0, 1):
            if mood == "pleased":
                how = "pleased"
            elif blink:
                how = blink
            elif mood == "curious":
                how = "wide"
            elif mood == "amused":
                how = "squint"
            elif mood == "skeptical" and k == 1:
                how = "half"
            else:
                how = "open"
            self.eye(p, k, how)
        if mood == "pondering" and not blink:
            for k in (0, 1):
                self.eye(p, k, "side")
        if mood in ("amused", "pleased"):
            self.blush(p)
        if name in ("talk1", "talk2"):
            self.mouth(p, name)
        elif mood in ("amused", "pleased"):
            self.mouth(p, "smile")
        elif mood == "skeptical":
            self.mouth(p, "smirk")
        return p


def move_lamp(base, to):
    """the lamp: cells in rows 0-33, columns 52-91, unlike their column's wallpaper (rows 34-38)"""
    a = base.astype(int)
    out = base.copy()
    cells = []
    for x in range(52, 92):
        col = [tuple(c) for c in base[34:39, x]]
        bg = max(set(col), key=col.count)
        for y in range(0, 34):
            if np.abs(a[y, x] - bg).sum() > 30:
                cells.append((x, y, tuple(base[y, x])))
            out[y, x] = bg
    xs = [x for x, _, _ in cells]
    dx = to - round((min(xs) + max(xs)) / 2)
    for x, y, c in cells:
        out[y, x + dx] = c
    return out


def person_mask(base, P):
    import cv2
    S = 6
    big = cv2.resize(base, (base.shape[1] * S, base.shape[0] * S), interpolation=cv2.INTER_NEAREST)
    mask = np.full(big.shape[:2], cv2.GC_BGD, np.uint8)
    mask[36 * S:200 * S, 18 * S:125 * S] = cv2.GC_PR_FGD
    hsv = cv2.cvtColor(base, cv2.COLOR_RGB2HSV).astype(int)
    green = (hsv[..., 0] > 30) & (hsv[..., 0] < 75) & (hsv[..., 1] > 35)
    mask[cv2.resize(green.astype(np.uint8), big.shape[1::-1], interpolation=cv2.INTER_NEAREST).astype(bool)] = cv2.GC_BGD
    hx0, hx1, sh = P["x"] - 5, P["x"] + P["w"] + 5, P["y"] + P["h"] + 5
    mask[:sh * S, :hx0 * S] = cv2.GC_BGD
    mask[:sh * S, hx1 * S:] = cv2.GC_BGD
    mask[P["y"] * S:(P["y"] + P["h"]) * S, (P["x"] + 2) * S:(P["x"] + P["w"] - 2) * S] = cv2.GC_FGD
    cx, yb = P["x"] + P["w"] // 2, P["y"] + P["h"]
    mask[(yb + 4) * S:(yb + 34) * S, (cx - 8) * S:(cx + 8) * S] = cv2.GC_FGD
    cv2.grabCut(cv2.cvtColor(big, cv2.COLOR_RGB2BGR), mask, None, np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_MASK)
    fg = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
    m = cv2.resize(fg, base.shape[1::-1], interpolation=cv2.INTER_AREA) > 0
    _, lab = cv2.connectedComponents(m.astype(np.uint8), connectivity=4)
    k = lab[P["y"] + P["h"] // 2, cx]
    if k:
        m = lab == k
    dark = base.astype(int).sum(2) / 3 < 55
    dark[:yb - 2] = False
    _, ld = cv2.connectedComponents(dark.astype(np.uint8), connectivity=4)
    for kd in set(np.unique(ld[yb + 4:yb + 34, cx - 20:cx + 20])) - {0}:
        if (ld == kd).sum() > 20:
            m |= ld == kd
    return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)


def pose(base, m, top, bottom, dy):
    """the masked cells of rows top..bottom moved dy rows (dy = -1 up, +1 down)"""
    out = base.copy()
    rows = range(top, bottom + 1) if dy < 0 else range(bottom, top - 1, -1)
    for y in rows:
        for x in np.nonzero(m[y])[0]:
            out[y + dy, x] = base[y, x]
            if dy > 0 and not m[y - 1, x]:          # the head's old top edge: the wallpaper above
                out[y, x] = base[y - 1, x]
    return out


def build(pid):
    f = FACES[pid]
    src = np.asarray(Image.open(HERE / "sources" / f["src"]).convert("RGB")).astype(float)
    nw, nh, ox, oy = find_grid(src, [GRID[0]], [GRID[1]])
    base = np.asarray(quantize(sample(src, nw, nh, ox, oy), 48)).copy()
    if f.get("lamp"):
        base = move_lamp(base, f["lamp"])
    face = Face(base, f)
    xs = [e[0] for e, _ in f["eyes"]] + [e[1] for e, _ in f["eyes"]] + [b[0] for b in f["brows"]] + [b[1] for b in f["brows"]]
    x0, x1 = min(xs) - 2, max(xs) + 2
    y0, y1 = min(b[2] for b in f["brows"]) - 2, f["mouth"][0] + 3
    w, h = x1 - x0 + 1, y1 - y0 + 1
    sheet = np.zeros((h * len(MOODS), w * len(FRAMES), 3), np.uint8)
    for i, mood in enumerate(MOODS):
        for j, name in enumerate(FRAMES):
            sheet[i * h:(i + 1) * h, j * w:(j + 1) * w] = face.frame(mood, name)[y0:y0 + h, x0:x0 + w]
    out = ROOT / f"ui/web/assets/personas/{pid}/full"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(base).save(out / "scene.png", optimize=True)
    m = person_mask(base, {"x": x0, "y": y0, "w": w, "h": h})
    top = min(y for y in range(base.shape[0]) if m[y].any())
    Image.fromarray(pose(base, m, top, f["breath"], -1)).save(out / "scene_in.png", optimize=True)
    Image.fromarray(pose(base, m, top, f["chin"], 1)).save(out / "scene_nod.png", optimize=True)
    Image.fromarray(sheet).save(out / "faces.png", optimize=True)
    (e0, _), (e1, _) = f["eyes"]
    meta = {"grid": list(GRID), "patch": {"x": x0, "y": y0, "w": w, "h": h}, "moods": list(MOODS), "frames": list(FRAMES),
            "anchor": {"face": [round((e0[0] + e1[1]) / 2), e0[3] + 2], "head": [x0 - 4, y0 - 14, x1 + 4, y1 + 8]},
            "source": f["src"], "palette": 48, "timing_ms": TIMING,
            "poses": {"in": {"src": "scene_in.png", "dy": -1}, "nod": {"src": "scene_nod.png", "dy": 1}}}
    (out / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(pid, f"grid {nw}x{nh} offset ({ox}, {oy}) patch {(x0, y0, w, h)}")


if __name__ == "__main__":
    for pid in sys.argv[1:] or list(FACES):
        build(pid)
