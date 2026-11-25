"""The Philocafé wordmark (assets/logo_philocafe.png): Pixelify Sans (OFL) at 24 px, drawn one bit deep,
with a cream-to-toast fill, a highlight row, a brown outline and a drop shadow. Shown at the café
panorama's pixel size.

    .venv/bin/python ui/web/tools/art/logo.py
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
f = ImageFont.truetype(str(HERE / 'sources/PixelifySans.ttf'), 24)
im = Image.new('L', (220, 60), 0); d = ImageDraw.Draw(im); d.fontmode = '1'
x = 4; SP = 0
for ch in 'Philocafé':
    d.text((x, 6), ch, font=f, fill=255); x += d.textlength(ch, font=f) + SP
m = np.asarray(im) > 0
ys, xs = np.nonzero(m); m = m[ys.min():ys.max()+1, xs.min():xs.max()+1]
# bold: thicken every stroke by one pixel to the right
b = m.copy()
H, W = b.shape
P = 3  # padding for outline and shadow
canvas = np.zeros((H + 2*P + 2, W + 2*P + 2), int)   # 0 empty, 1 shadow, 2 outline, 3 fill
fill = np.zeros_like(canvas, bool); fill[P:P+H, P:P+W] = b
def dil(a):
    o = a.copy(); o[1:] |= a[:-1]; o[:-1] |= a[1:]; o[:, 1:] |= a[:, :-1]; o[:, :-1] |= a[:, 1:]
    o[1:, 1:] |= a[:-1, :-1]; o[1:, :-1] |= a[:-1, 1:]; o[:-1, 1:] |= a[1:, :-1]; o[:-1, :-1] |= a[1:, 1:]
    return o
outline = dil(fill)
shadow = np.zeros_like(outline); shadow[2:, 1:] = outline[:-2, :-1]   # one right, two down
canvas[shadow] = 1; canvas[outline] = 2; canvas[fill] = 3
ink = (74, 47, 26); outc = (107, 78, 46)
top, mid, bot = (255, 246, 214), (246, 222, 164), (222, 178, 112)   # cream to toasted
rgba = np.zeros(canvas.shape + (4,), np.uint8)
rgba[canvas == 1] = (*ink, 200)
rgba[canvas == 2] = (*outc, 255)
rows = np.nonzero(fill.any(1))[0]; r0, r1 = rows.min(), rows.max()
for y in range(canvas.shape[0]):
    t = (y - r0) / max(1, r1 - r0)
    c = top if t < .34 else mid if t < .7 else bot
    sel = (canvas[y] == 3)
    rgba[y, sel] = (*c, 255)
# a highlight dot row on the upper edge of each letter
hi = fill & ~np.roll(fill, 1, 0)
rgba[hi] = (255, 252, 238, 255)
out = Image.fromarray(rgba, 'RGBA')
out.save(HERE.parents[1] / 'assets/logo_philocafe.png'); print(out.size)
