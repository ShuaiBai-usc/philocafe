"""The café panorama for the full-screen home (assets/home_pano.png).

sources/home_canvas.png puts the café (assets/home_bg.png) on a 9:16 canvas with magenta margins; an
ElevenLabs generation (Nano Banana 2, outpainting, sample 3 of 4) filled the margins: sources/home_pano_gen.jpg.
This script finds where the café landed in that picture (registration below), reads the generated margins
back onto the café's own 12 px grid, snaps their colours to the café's palette, and pastes the original
café over the middle unchanged, so the philosophers' sprites keep their places (offset 317, 432).

    .venv/bin/python ui/web/tools/art/home_pano.py
"""
from pathlib import Path

import numpy as np
from PIL import Image
HERE = Path(__file__).resolve().parent
WEB = HERE.parents[1]
gen = np.asarray(Image.open(HERE / 'sources/home_pano_gen.jpg').convert('RGB')).astype(float)
orig_im = Image.open(WEB / 'assets/home_bg.png').convert('RGB')
orig = np.asarray(orig_im).astype(int).copy()
# the original's top six rows are a darker band where its picture ended; on the taller wall it would read
# as a stripe, so they take the plain wall from just below (stripes and the lamp cord line up)
orig[0:144] = orig[144:288]
SX, SY, GX, GY = 0.42, 0.4175, 137, 182          # where the original sits in the generated picture
OX, OY = 336, 432                                 # where it sits on the canvas
X0, X1, Y0, Y1 = 19, 1831, 0, 3288                # final picture on the canvas (12 px cells, original grid)
C = 12
nx, ny = (X1 - X0) // C, (Y1 - Y0) // C
cells = np.zeros((ny, nx, 3))
for j in range(ny):
    for i in range(nx):
        cx0, cy0 = X0 + i * C, Y0 + j * C
        gx0 = GX + (cx0 + 3 - OX) * SX; gx1 = GX + (cx0 + 9 - OX) * SX
        gy0 = GY + (cy0 + 3 - OY) * SY; gy1 = GY + (cy0 + 9 - OY) * SY
        xa, xb = int(np.floor(gx0)), max(int(np.ceil(gx1)), int(np.floor(gx0)) + 1)
        ya, yb = int(np.floor(gy0)), max(int(np.ceil(gy1)), int(np.floor(gy0)) + 1)
        xa, xb = np.clip([xa, xb], 0, gen.shape[1]); ya, yb = np.clip([ya, yb], 0, gen.shape[0])
        if xb <= xa: xa = max(0, xb - 1)
        if yb <= ya: ya = max(0, yb - 1)
        cells[j, i] = np.median(gen[ya:yb, xa:xb].reshape(-1, 3), axis=0)
# palette: the original's colours; a generated colour close to one snaps to it, others are reduced by k-means
pal = np.unique(orig.reshape(-1, 3), axis=0).astype(float)
flat = cells.reshape(-1, 3)
d = ((flat[:, None, :] - pal[None]) ** 2).sum(2)
near = d.argmin(1); nd = np.sqrt(d.min(1))
out = flat.copy()
snap = nd < 22
out[snap] = pal[near[snap]]
rest = flat[~snap]
if len(rest):
    k = min(16, len(rest))
    rng = np.random.default_rng(0); cen = rest[rng.choice(len(rest), k, replace=False)]
    for _ in range(30):
        lab = ((rest[:, None] - cen[None]) ** 2).sum(2).argmin(1)
        for c in range(k):
            if (lab == c).any(): cen[c] = rest[lab == c].mean(0)
    out[~snap] = np.round(cen[lab])
print('snapped', snap.mean())
cells = out.reshape(ny, nx, 3).astype(np.uint8)
img = Image.fromarray(cells).resize((nx * C, ny * C), Image.NEAREST)
full = np.asarray(img).copy()
# the original café, exactly, with its two cut edge columns carried across their whole cells
ox, oy = OX - X0, OY - Y0
full[oy:oy + 2556, ox:ox + 1179] = orig
left_cell = ox - (ox % C) if (ox % C) else ox          # cell that starts before the original
for y in range(oy, oy + 2556):
    full[y, left_cell:ox] = orig[y - oy, 0]
right_end = ox + 1179; rc_end = right_end + (C - right_end % C) % C
for y in range(oy, oy + 2556):
    full[y, right_end:rc_end] = orig[y - oy, 1178]
Image.fromarray(full).save(WEB / 'assets/home_pano.png', optimize=True)
print(full.shape, 'offset of the original:', ox, oy)
