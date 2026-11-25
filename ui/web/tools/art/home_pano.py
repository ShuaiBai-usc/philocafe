"""The full-screen home (assets/home_pano.png): the team's café, widened so nobody sits at the screen's edge.

sources/home_canvas.png puts the café (assets/home_bg.png) on a 9:16 canvas with magenta margins; an
ElevenLabs generation (Nano Banana 2, outpainting, sample 2 of 2) filled the margins as one flat room seen
straight from the front: the back wall, wainscot and floorboards run on to both edges, with no side walls
and no perspective, plus a few plants, a shelf and a picture (sources/home_pano_gen.jpg).

This script reads the generated margins back onto the café's own 12 px grid, snaps their colours to the
café's palette where they are close, and pastes the original café over the middle unchanged, so the
team's sprites keep their places (offset OX, OY; template.html CAFE_AT).

    python3 ui/web/tools/art/home_pano.py
"""
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
WEB = HERE.parents[1]
C = 12
GX, GY, SX, SY = 138, 181, 493 / 1179, 1069 / 2556   # where the original landed in the generation
OX, OY = 264, 432                                     # where it sits in the result (whole cells)
W, H = 1179 + 2 * OX, OY + 2556 + 288                 # 22 cells each side, 36 above, 24 below


def build():
    gen = np.asarray(Image.open(HERE / "sources/home_pano_gen.jpg").convert("RGB")).astype(float)
    orig = np.asarray(Image.open(WEB / "assets/home_bg.png").convert("RGB")).astype(int).copy()
    # the original's top rows are a darker band where its picture ended; on the taller wall it would read
    # as a stripe, so they take the plain wall from just below (stripes and the lamp cord line up)
    orig[0:144] = orig[144:288]
    nx, ny = -(-W // C), H // C
    cells = np.zeros((ny, nx, 3))
    for j in range(ny):
        for i in range(nx):
            x0, y0 = i * C, j * C
            gx0, gx1 = GX + (x0 + 3 - OX) * SX, GX + (x0 + 9 - OX) * SX
            gy0, gy1 = GY + (y0 + 3 - OY) * SY, GY + (y0 + 9 - OY) * SY
            xa = int(np.clip(np.floor(gx0), 0, gen.shape[1] - 1))
            xb = int(np.clip(max(np.ceil(gx1), xa + 1), 1, gen.shape[1]))
            ya = int(np.clip(np.floor(gy0), 0, gen.shape[0] - 1))
            yb = int(np.clip(max(np.ceil(gy1), ya + 1), 1, gen.shape[0]))
            cells[j, i] = np.median(gen[ya:yb, xa:xb].reshape(-1, 3), 0)
    # palette: a generated colour close to one of the café's snaps to it; the others are reduced by k-means
    pal = np.unique(orig.reshape(-1, 3), axis=0).astype(float)
    flat = cells.reshape(-1, 3)
    d = ((flat[:, None] - pal[None]) ** 2).sum(2)
    out = flat.copy()
    snap = np.sqrt(d.min(1)) < 22
    out[snap] = pal[d.argmin(1)[snap]]
    rest = flat[~snap]
    if len(rest):
        k = min(16, len(rest))
        rng = np.random.default_rng(0)
        cen = rest[rng.choice(len(rest), k, replace=False)]
        for _ in range(30):
            lab = ((rest[:, None] - cen[None]) ** 2).sum(2).argmin(1)
            for c in range(k):
                if (lab == c).any():
                    cen[c] = rest[lab == c].mean(0)
        out[~snap] = np.round(cen[lab])
    full = np.asarray(Image.fromarray(out.reshape(ny, nx, 3).astype(np.uint8)).resize((nx * C, ny * C), Image.NEAREST))
    full = full[:H, :W].copy()
    # the original café, exactly; its cut right-hand column carried across the rest of that cell
    full[OY:OY + 2556, OX:OX + 1179] = orig
    end = OX + 1179
    full[OY:OY + 2556, end:end + (C - end % C) % C] = orig[:, -1:]
    Image.fromarray(full).save(WEB / "assets/home_pano.png", optimize=True)
    print(full.shape[1], "x", full.shape[0], "snapped", round(float(snap.mean()), 3), "original at", (OX, OY))


if __name__ == "__main__":
    build()
