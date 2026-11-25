"""The café for the full-screen home (assets/home/: cafe.png, <id>.png strips, ambient.png, home.json).

Background: sources/home_natural_gen.jpg, an ElevenLabs edit (Nano Banana 2) of the first café
(sources/home_cafe_gen.jpg: five empty armchairs set about unevenly, rugs off-centre or missing) with its
round side tables made square and drawn straight from the front, and its rugs made rectangles, so nothing
shows a top in perspective. It is read on the team sprites' grid (96 cells across, 8 source px a
cell), reduced to 44 colours, with ten rows of plain wall in the top band for the wordmark. Socrates'
generated cup and the walking stick by Epictetus' chair go: their sprites bring their own.

People: the team's home sprites (data.json home_*, 12 px cells) with their motions fitted to the room:
    seated     the thigh rows are taken out, so each sits in his armchair (hands on its arms, feet on the
               rug) instead of standing in front of it
    the cup    rests on that nook's own surface (Socrates' side table, Montaigne's desk, Seneca's table,
               Epictetus' stool); the reaching arm is redrawn from the shoulder to wherever the cup is
    Seneca     his frames had no resting cup (the old café drew one), so Socrates' cup is set on his table
    Schopenhauer  no surface beside his chair, so he keeps the cup in his hands: only his hold, raise
               and sip frames play
Each philosopher is one strip (assets/home/<id>.png, one cell = one pixel, alpha) and a timeline.

The room: ambient.py on the café (leaves leaning, the cat and the poodle breathing, the poodle perking up
and wagging now and then, the oil lamps' flames); the poodle is drawn in front of Schopenhauer.

    python3 ui/web/tools/art/home_scene.py        (needs opencv-python)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ambient  # noqa: E402

ROOT = HERE.parents[3]
WEB = ROOT / "ui/web"
OUT = WEB / "assets/home"
G, K = 96, 44                      # cells across, colours
WALL = (12, 8, 18)                 # rows 8..17 again at row 12: the wordmark's room on the striped wall

# x, y: the seated sprite's top-left cell; cut: thigh rows taken out (first row, how many);
# cup: (left column, bottom row) of the resting cup on the nook's surface, or None (kept in hand);
# stick: Epictetus' walking stick moved this many columns right, against the armchair
PEOPLE = {
    "socrates":     {"x": 18, "y": 51, "cut": (19, 5), "cup": (36, 65)},
    "montaigne":    {"x": 64, "y": 49, "cut": (19, 4), "cup": (89, 62)},
    "seneca":       {"x": 15, "y": 90, "cut": (20, 5), "cup": (34, 108)},
    "schopenhauer": {"x": 66, "y": 91, "cut": (19, 5), "cup": None},
    "epictetus":    {"x": 34, "y": 132, "cut": (19, 5), "cup": (64, 149), "stick": 2},
}
ERASE_CUP = (37, 41, 63, 65)       # Socrates' generated cup on his side table (cells x0..x1, rows y0..y1)
ERASE_STICK = (34, 38, 141, 160)   # the generated walking stick by Epictetus' chair: his sprite has its own
AMBIENT = [
    ("sway", (38, 47, 47, 58)),                      # the plant on Socrates' side table
    ("sway", (53, 94, 65, 108)),                     # Schopenhauer's fern
    ("breathe", (58, 79, 74, 90)),                   # Montaigne's cat
    ("breathe", (58, 111, 72, 128)),                 # the poodle
    ("perk", (58, 111, 72, 128), (60, 111, 72, 119)),
    ("wag", (58, 111, 72, 128), (58, 120, 62, 127)),
    ("flame", (37, 104, 45, 111)),                   # Seneca's oil lamp
    ("flame", (59, 143, 66, 150)),                   # Epictetus' clay lamp
]
FRONT = {3, 4, 5}                  # the poodle: drawn over Schopenhauer
LAMPS = [(22, 44), (40, 44), (73, 44)]


def pano():
    src = np.asarray(Image.open(HERE / "sources/home_natural_gen.jpg").convert("RGB")).astype(float)
    cell = src.shape[1] / G
    ny = int(round(src.shape[0] / cell))
    cells_ = np.zeros((ny, G, 3))
    for j in range(ny):
        for i in range(G):
            xa, xb = int(i * cell + cell * .25), int(i * cell + cell * .75) + 1
            ya, yb = int(j * cell + cell * .25), min(int(j * cell + cell * .75) + 1, src.shape[0])
            cells_[j, i] = np.median(src[ya:yb, xa:xb].reshape(-1, 3), 0)
    X = cells_.reshape(-1, 3)
    rng = np.random.default_rng(2)
    cent = [X[rng.integers(len(X))]]
    for _ in range(1, K):                                   # k-means++ seeding, then Lloyd
        d = np.min(((X[:, None] - np.array(cent)[None]) ** 2).sum(2), 1)
        cent.append(X[rng.choice(len(X), p=d / d.sum())])
    cent = np.array(cent)
    for _ in range(30):
        lab = ((X[:, None] - cent[None]) ** 2).sum(2).argmin(1)
        for t in range(K):
            if (lab == t).any():
                cent[t] = X[lab == t].mean(0)
    a = cent[lab].reshape(ny, G, 3).round().astype(np.uint8)
    at, a0, a1 = WALL
    return np.concatenate([a[:at], a[a0:a1], a[at:]])


def erase(a, box, dx):
    """cells x0..x1, rows y0..y1 take the cells dx columns over (the floor runs in horizontal bands)"""
    x0, x1, y0, y1 = box
    a[y0:y1 + 1, x0:x1 + 1] = a[y0:y1 + 1, x0 + dx:x1 + 1 + dx].copy()


def erase_cup(a):
    """the generated cup: its cells take the row just above it (what is behind the table top)"""
    x0, x1, y0, y1 = ERASE_CUP
    for y in range(y0, y1 + 1):
        a[y, x0:x1 + 1] = a[y0 - 1, x0:x1 + 1]


def cells(path):
    """a team sprite frame (12 px cells starting at x = 2) as one RGBA pixel per cell"""
    a = np.asarray(Image.open(path).convert("RGBA"))
    n = (a.shape[1] - 2) // 12
    return a[6::12, 8::12][:, :n].copy()


def kind(name):
    for k in ("reach", "carry", "hold", "raise", "sip"):
        if f"_{k}" in name:
            return k
    return "rest"


def seat(f, cut):
    r0, n = cut
    return np.concatenate([f[:r0], f[r0 + n:]])


def body_right(f):
    """last column of the body: the widest run of opaque columns (Epictetus' stick and the cup are apart)"""
    op = f[..., 3].any(0)
    best, x = (0, -1), 0
    while x < len(op):
        if op[x]:
            x1 = x
            while x1 + 1 < len(op) and op[x1 + 1]:
                x1 += 1
            best = max(best, (x1 - x, x1))
            x = x1 + 1
        else:
            x += 1
    return best[1]


def line(p, q):
    (x0, y0), (x1, y1) = p, q
    n = max(abs(x1 - x0), abs(y1 - y0), 1)
    return [(round(x0 + (x1 - x0) * t / n), round(y0 + (y1 - y0) * t / n)) for t in range(n + 1)]


def paste(dst, src, x, y):
    h, w = src.shape[:2]
    for j in range(h):
        for i in range(w):
            if src[j, i, 3] and 0 <= y + j < dst.shape[0] and 0 <= x + i < dst.shape[1]:
                dst[y + j, x + i] = src[j, i]


def move_cup(f, br, dx, dy):
    """rest frames: the cup (opaque cells right of the body, rows 6-16) moves by dx, dy"""
    out = f.copy()
    m = np.zeros(f.shape[:2], bool)
    m[6:17, br + 3:] = f[6:17, br + 3:, 3] > 0
    out[m] = 0
    for y, x in zip(*np.nonzero(m)):
        if 0 <= y + dy < f.shape[0] and 0 <= x + dx < f.shape[1]:
            out[y + dy, x + dx] = f[y, x]
    return out


def reach(f, br, dx, dy, cup=None):
    """reach frames: the hand (and the cup under it) moves by dx, dy and the arm is redrawn from the shoulder"""
    out = f.copy()
    side = np.zeros(f.shape[:2], bool)
    side[:, br + 1:] = f[:, br + 1:, 3] > 0
    ys, xs = np.nonzero(side)
    hx0 = xs.max() - 4 if cup is None else xs.max() - 1     # the hand (with the cup under it: its last cells)
    arm = [(y, x) for y, x in zip(ys, xs) if x < hx0]
    hand = [(y, x) for y, x in zip(ys, xs) if x >= hx0]
    mid = (br + 1 + hx0) // 2
    sec = [f[y, mid].copy() for y in range(f.shape[0]) if side[y, mid]]       # the arm's cross-section
    ay = min(y for y, _ in arm) if arm else min(y for y, _ in hand)
    hy = max(y for y, _ in hand)
    out[side] = 0
    H, W = f.shape[:2]
    if cup is not None:
        paste(out, cup, hx0 + dx - cup.shape[1] + 2, hy + dy - cup.shape[0] + 1)
    for x, y in line((br + 1, ay), (hx0 - 1 + dx, ay + dy)):
        for k, c in enumerate(sec):
            if 0 <= y + k < H and 0 <= x < W:
                out[y + k, x] = c
    for y, x in hand:
        if 0 <= y + dy < H and 0 <= x + dx < W:
            out[y + dy, x + dx] = f[y, x]
    return out


def sprite(pid, data):
    d = data[f"home_{pid}"]
    P = PEOPLE[pid]
    names = d["frames"]
    raw = [cells(WEB / "assets" / f) for f in names]
    br = body_right(raw[0])

    def cup_of(f, b):
        m = f[6:17, b + 3:]
        ys, xs = np.nonzero(m[..., 3])
        return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1], b + 3 + int(xs.min()), 6 + int(ys.max())

    rest0 = next(f for f, n in zip(raw, names) if kind(n) == "rest")
    add = None
    if rest0[6:17, br + 3:, 3].any():
        cup, cx, cy = cup_of(rest0, br)
    else:                                              # Seneca: no cup of his own on the table
        soc = cells(WEB / "assets" / data["home_socrates"]["frames"][0])
        add, _, _ = cup_of(soc, body_right(soc))
        r = next(f for f, n in zip(raw, names) if kind(n) == "reach")
        ys, xs = np.nonzero(r[:, br + 1:, 3])
        cx, cy = br + 1 + int(xs.max()) - add.shape[1] + 2, int(ys.max())
    frames = []
    for f, n in zip(raw, names):
        k = kind(n)
        if P["cup"] is not None:
            dx, dy = P["cup"][0] - (P["x"] + cx), P["cup"][1] - (P["y"] + cy)
            if k == "rest":
                if add is not None:
                    f = f.copy()
                    paste(f, add, cx + dx, cy + dy - add.shape[0] + 1)
                else:
                    f = move_cup(f, br, dx, dy)
            elif k == "reach":
                f = reach(f, br, dx, dy, add)
        if P.get("stick"):                               # the walking stick leans on the armchair's side
            f = f.copy()
            st = f[:, :3].copy()
            f[:, :3] = 0
            paste(f, st, P["stick"], 0)
        frames.append(seat(f, P["cut"]))
    seq = [list(s) for s in d["seq"]]
    if P["cup"] is None:                                 # nowhere to put it down: the cup stays in his hands
        keep = {i for i, n in enumerate(names) if kind(n) in ("hold", "raise", "sip")}
        merged = []
        for i, ms in seq:
            if i not in keep:
                continue
            if merged and merged[-1][0] == i:
                merged[-1][1] += ms
            else:
                merged.append([i, ms])
        used = sorted({i for i, _ in merged})
        remap = {i: j for j, i in enumerate(used)}
        frames = [frames[i] for i in used]
        seq = [[remap[i], ms] for i, ms in merged]
    return frames, seq


def build():
    data = json.loads((WEB / "data.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "people.png").unlink(missing_ok=True)
    base = pano()
    erase_cup(base)
    erase(base, ERASE_STICK, -3)
    H, W = base.shape[:2]
    people = {}
    for pid, P in PEOPLE.items():
        frames, seq = sprite(pid, data)
        h, w = frames[0].shape[:2]
        Image.fromarray(np.concatenate(frames, 1), "RGBA").save(OUT / f"{pid}.png", optimize=True)
        op = np.any([f[..., 3] > 0 for f in frames], 0)
        ys, xs = np.nonzero(op)
        people[pid] = {"x": P["x"], "y": P["y"], "w": int(w), "h": int(h), "frames": len(frames), "seq": seq,
                       "tap": [P["x"] + int(xs.min()), P["y"] + int(ys.min()), P["x"] + int(xs.max()), P["y"] + int(ys.max())]}
    els = ambient.build(base, AMBIENT)
    amb, sy = [], 0
    width = max((r[2] - r[0] + 1) * len(fr) for r, fr, _ in els)
    sheet = np.zeros((sum(r[3] - r[1] + 1 for r, _, _ in els), width, 4), np.uint8)
    for n, ((ax0, ay0, ax1, ay1), frames, info) in enumerate(els):
        aw, ah = ax1 - ax0 + 1, ay1 - ay0 + 1

        def rect(a):
            return a[ay0:ay1 + 1, ax0:ax1 + 1]
        changed = np.any([np.any(rect(fr) != rect(base), 2) for fr in frames], 0)
        if n in FRONT:                                    # the whole pet, so it stays in front of him
            changed |= rect(ambient.pet_mask(base, AMBIENT[n][1]))
        for k, fr in enumerate(frames):
            al = changed if n in FRONT else np.any(rect(fr) != rect(base), 2)
            sheet[sy:sy + ah, k * aw:(k + 1) * aw] = np.dstack([rect(fr), al.astype(np.uint8) * 255])
        amb.append({"x": int(ax0), "y": int(ay0), "w": aw, "h": ah, "sy": sy, "frames": len(frames),
                    "front": n in FRONT, **info})
        sy += ah
    Image.fromarray(sheet, "RGBA").save(OUT / "ambient.png", optimize=True)
    Image.fromarray(base).save(OUT / "cafe.png", optimize=True)
    meta = {"grid": [W, H], "people": people, "ambient": amb, "timing_ms": {"pet_every": [9000, 18000]},
            "particles": {"dust": [{"x": x, "y": y, "spread": 8, "depth": 12} for x, y in LAMPS]},
            "source": "home_natural_gen.jpg + data.json home_* sprites", "palette": K}
    (OUT / "home.json").write_text(json.dumps(meta, indent=1) + "\n")
    print("cafe", W, "x", H, {k: (v["x"], v["y"], v["w"], v["h"], v["frames"]) for k, v in people.items()})
    return base, people


if __name__ == "__main__":
    build()
