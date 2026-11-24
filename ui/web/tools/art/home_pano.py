"""The café for the full-screen home (assets/home_pano.png, 1152 x 2184).

An ElevenLabs generation (Nano Banana 2, sample 4 of 4; references: the old café and the strip of the five
chat scenes, sources/nooks_strip.png) drew an empty café, flat front view in the old café's style, with one
nook per philosopher furnished like his chat scene: sources/home_cafe_gen.jpg. This script reads it onto a
96-cell grid (8 source px per cell), reduces it to 44 colours, and draws each cell 12 px wide, the grid of
the team's sprites, so a sprite fits an armchair.

Then a few edits so the sprites' props land on something (a sprite's resting cup is at box x 314-373,
y 120-167, so a surface belongs on row y0/12 + 14):
    Socrates       the generated side table and cup go; a taller table stands under his cup
    Schopenhauer   a side table at his left (his sprite is flipped), in front of the fern
    Epictetus      his sprite brings its own walking stick, so the generated one goes; his stool is taller,
                   with the clay lamp beside his cup
and ten rows of plain wall go into the top band, so the wordmark has room under the status bar.

    python3 ui/web/tools/art/home_pano.py

Sprite boxes (template.html HOME_SEATS) are on this picture; x0 = 10 mod 12 (11 when flipped) and
y0 = 0 mod 12 keep the sprites on the same grid.
"""
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
WEB = HERE.parents[1]
G, C, K = 96, 12, 44

src = np.asarray(Image.open(HERE / "sources/home_cafe_gen.jpg").convert("RGB")).astype(float)
cell = src.shape[1] / G
NY = int(round(src.shape[0] / cell))
cells = np.zeros((NY, G, 3))
for j in range(NY):
    for i in range(G):
        xa, xb = int(i * cell + cell * .25), int(i * cell + cell * .75) + 1
        ya, yb = int(j * cell + cell * .25), min(int(j * cell + cell * .75) + 1, src.shape[0])
        cells[j, i] = np.median(src[ya:yb, xa:xb].reshape(-1, 3), 0)

X = cells.reshape(-1, 3)
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
a = cent[lab].reshape(NY, G, 3).round().astype(np.uint8)
pal = np.unique(a.reshape(-1, 3), axis=0)


def snap(c):
    return tuple(pal[((pal.astype(int) - np.array(c)) ** 2).sum(1).argmin()])


TOP, TOP2, EDGE, LEG, LEGL, DEEP = map(snap, [(150, 112, 76), (128, 96, 64), (100, 72, 46), (92, 67, 43), (112, 82, 54), (70, 50, 32)])
CLAY, CLAY2, FLAME, GLOW = map(snap, [(176, 112, 70), (140, 86, 52), (246, 214, 120), (255, 240, 190)])


def erase(x0, x1, y0, y1, dx):
    """cells x0..x1, y0..y1 take the cells dx columns over (floor and wall run in horizontal bands)"""
    a[y0:y1 + 1, x0:x1 + 1] = a[y0:y1 + 1, x0 + dx:x1 + 1 + dx].copy()


def shadow(x0, x1, y):
    for x in range(x0, x1 + 1):
        a[y, x] = snap(tuple(int(v * .82) for v in a[y, x]))


def table(cx, top, floor):
    """round pedestal side table: surface on row `top` (cells cx-4..cx+4), feet on row `floor`"""
    for x in range(cx - 4, cx + 5): a[top, x] = TOP
    for x in range(cx - 5, cx + 6): a[top + 1, x] = TOP2
    for x in range(cx - 4, cx + 5): a[top + 2, x] = EDGE
    for y in range(top + 3, floor - 1):
        a[y, cx] = LEGL; a[y, cx + 1] = LEG
    for x in range(cx - 1, cx + 3): a[floor - 2, x] = LEG
    for x in (cx - 2, cx - 1, cx + 2, cx + 3): a[floor - 1, x] = LEG
    for x in (cx - 3, cx - 2, cx + 3, cx + 4): a[floor, x] = DEEP
    shadow(cx - 3, cx + 4, floor + 1)


def stool(x0, x1, top, floor):
    for x in range(x0, x1 + 1): a[top, x] = TOP
    for x in range(x0, x1 + 1): a[top + 1, x] = EDGE
    for y in range(top + 2, floor + 1):
        a[y, x0 + 1] = LEGL; a[y, x1 - 1] = LEG
    for x in range(x0 + 1, x1): a[(top + floor) // 2 + 2, x] = LEG
    for y in range(top + 2, floor - 1): a[y, (x0 + x1) // 2] = DEEP if y > top + 3 else EDGE
    shadow(x0, x1, floor + 1)


# Socrates (box y0 = row 38 before the wall rows go in): cup on cells 44-48, rows 48-51
erase(35, 48, 54, 70, 13)
erase(37, 41, 51, 53, 13)
table(46, 52, 68)
# Schopenhauer (row 79): cup on cells 52-56, rows 89-92
table(54, 93, 109)
# Epictetus (row 121): cup on cells 67-71, rows 131-134
erase(32, 37, 129, 153, -6)
erase(61, 70, 134, 153, 9)
stool(61, 72, 135, 151)
for x in range(62, 66): a[134, x] = CLAY2
for x in range(62, 65): a[133, x] = CLAY
a[133, 65] = CLAY2; a[132, 63] = CLAY2
a[132, 62] = FLAME; a[131, 62] = GLOW
# ten rows of plain wall in the top band
a = np.concatenate([a[:12], a[8:18], a[12:]])

out = Image.fromarray(a).resize((a.shape[1] * C, a.shape[0] * C), Image.NEAREST)
out.save(WEB / "assets/home_pano.png", optimize=True)
print("home_pano.png", out.size, len(np.unique(a.reshape(-1, 3), axis=0)), "colours")
