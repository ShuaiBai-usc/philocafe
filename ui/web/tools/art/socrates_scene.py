"""Socrates' full-screen chat scene: a generated picture, put on the bust's pixel grid.

1. sources/socrates_seated_gen.jpg was generated (ElevenLabs, Nano Banana 2, 9:16) from the
   bust and the café scene as references. Generated "pixel art" is not on a true grid, so
   each 5.9 px cell is read back as its most common colour onto a 130 x 232 grid: on a
   390 x 844 phone a cell is then 3.64 px, the same as the bust on the Meet page.
2. The colours are reduced to 40, with no dithering added.
3. The head and beard are replaced by the bust's own pixels (portrait_socrates.png on its
   56 x 64 grid), which fit the generated head 1:1, so he is the same man as on the Meet
   page and the face patches below line up.
4. Expressions are small patches over the face (eyes, brows, mouth, cheeks).

    .venv/bin/python ui/web/tools/art/socrates_scene.py

writes ui/web/assets/personas/socrates/full/: scene.png (130 x 232, the attentive face),
faces.png (one row per mood: open, half, closed, talk1, talk2), faces.json, and bust.png
(the bust's framing re-cut from the scene, for comparison with the Meet page portrait).
The table that will cover his lower half is a separate layer, added later.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "ui/web/assets/personas/socrates/full"
SOURCE = Path(__file__).resolve().parent / "sources/socrates_seated_gen.jpg"
W, H = 130, 232
DX, DY = 37, 28                  # where the bust's grid sits on the scene's (its head fits here 1:1)
BG = {(171, 175, 136), (162, 168, 128), (179, 182, 145), (153, 160, 120), (144, 153, 111)}   # bust background


def bust_grid(path=ROOT / "ui/web/assets/portrait_socrates.png", nw=56, nh=64):
    """The bust is drawn on a 56 x 64 grid scaled up about 7.2x; sample each cell's centre."""
    src = Image.open(path).convert("RGB")
    out = Image.new("RGB", (nw, nh))
    for y in range(nh):
        for x in range(nw):
            out.putpixel((x, y), src.getpixel((int((x + .5) * src.width / nw), int((y + .5) * src.height / nh))))
    return out


def on_grid(path, gw, gh):
    """Each cell's most common colour (colours bucketed by 12 to ignore compression noise)."""
    src = np.asarray(Image.open(path).convert("RGB")).astype(np.int32)
    h0, w0, _ = src.shape
    out = np.zeros((gh, gw, 3), np.uint8)
    for gy in range(gh):
        y0, y1 = int(gy * h0 / gh), int((gy + 1) * h0 / gh)
        for gx in range(gw):
            x0, x1 = int(gx * w0 / gw), int((gx + 1) * w0 / gw)
            cell = src[y0 + 1:y1 - 1, x0 + 1:x1 - 1].reshape(-1, 3)
            q = cell // 12
            keys = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
            vals, counts = np.unique(keys, return_counts=True)
            out[gy, gx] = cell[keys == vals[counts.argmax()]].mean(0)
    img = Image.fromarray(out)
    return img.quantize(colors=40, method=Image.Quantize.MAXCOVERAGE, dither=Image.Dither.NONE).convert("RGB")


base = on_grid(SOURCE, W, H)
bp = bust_grid().load()
_p = base.load()
for by in range(9, 47):                       # head and beard: the bust's pixels
    for bx in range(56):
        c = bp[bx, by]
        if c not in BG:
            _p[bx + DX, by + DY] = c

# ---------- expressions ----------
C = dict(x=(246,239,226), A=(63,45,28), B=(91,66,42), k=(156,148,128), f=(201,195,176), t=(168,119,79), u=(148,87,61),
         l=(201,154,108), h=(226,180,132), z=(156,90,68), v=(111,63,44), w=(211,140,104), y=(232,162,131), m=(112,104,90),
         i=(230,226,212), o=(242,207,168))
EYES = {'L': (22, 25), 'R': (32, 35)}        # columns of each eye, row 25
BROWS = {'L': (21, 25), 'R': (31, 35)}       # columns of each brow, row 22
PATCH = (17, 19, 39, 39)                     # bust-grid box that holds every change (x0, y0, x1, y1)

def face(mood='attentive', eyes=None, mouth=None):
    img = base.copy(); p = img.load()  # base: the aligned scene with the bust's head
    g = lambda x, y: p[x + DX, y + DY]
    def s(x, y, c): p[x + DX, y + DY] = C[c] if isinstance(c, str) else c
    skin = lambda x, y: base.getpixel((x + DX, y + DY))
    below = lambda x: skin(x, 26)            # skin under the eyes, to paint over an eye
    spec = MOODS[mood]
    # brows
    def brow(side, rows):                     # rows: one row number per brow column
        x0, x1 = BROWS[side]
        for x in range(x0, x1 + 1): s(x, 22, skin(x, 24) if side == 'L' else skin(x, 24))
        for x, r in zip(range(x0, x1 + 1), rows): s(x, r, 'k')
    b = spec['brows']
    shapes = {'neutral': ([22] * 5, [22] * 5), 'raised': ([21] * 5, [21] * 5),
              'one_up': ([22, 22, 23, 23, 23], [21] * 5), 'inner_up': ([22, 22, 22, 21, 21], [21, 21, 22, 22, 22]),
              'relaxed': ([23, 22, 22, 22, 22], [22, 22, 22, 22, 23]), 'knit': ([22, 22, 22, 23, 23], [23, 23, 22, 22, 22])}
    bl, br = shapes[b]; brow('L', bl); brow('R', br)
    # eyes
    def eye(side, state):
        x0, x1 = EYES[side]; dark = 't' if side == 'L' else 'u'
        for x in range(x0, x1 + 1): s(x, 25, below(x))
        if state == 'open':   seq = 'xABx'
        elif state == 'half': seq = dark + 'AB' + dark
        elif state == 'closed': seq = dark * 4
        elif state == 'smile':                 # happy closed eyes: a little arch
            seq = dark + '..' + dark; s(x0 + 1, 24, dark); s(x0 + 2, 24, dark)
        elif state == 'up':                    # looking up: iris above, white below
            seq = 'xxxx'; s(x0 + 1, 24, 'A'); s(x0 + 2, 24, 'B')
        elif state == 'side':  seq = 'xxAB'
        elif state == 'wide':  seq = 'xABx'; s(x0 + 1, 24, 'x'); s(x0 + 2, 24, 'x')
        elif state == 'soft':  seq = dark + 'AB' + dark   # relaxed, a little lowered lid
        for x, ch in zip(range(x0, x1 + 1), seq):
            if ch != '.': s(x, 25, ch)
    e = eyes or spec['eyes']
    if e == 'half':   el = er = 'half'
    elif e == 'closed': el = er = 'closed'
    else: el, er = spec['eyes'] if isinstance(spec['eyes'], tuple) else (spec['eyes'], spec['eyes'])
    if spec['eyes'] in ('smile',) and e in ('half', 'closed'): el = er = 'smile'      # already closed: a blink changes nothing
    eye('L', el); eye('R', er)
    # cheeks
    if spec.get('blush'):
        for x, yy in ((20, 29), (21, 29), (22, 29), (21, 30), (34, 29), (35, 29), (33, 29), (35, 30)): s(x, yy, 'y')
    # mouth (row 36 under the moustache)
    mo = mouth or spec['mouth']
    for x in range(26, 31): s(x, 36, skin(x, 36) if x not in (27, 28, 29) else 'm'); s(x, 37, skin(x, 37))
    if mo == 'rest':    [s(x, 36, 'z') for x in (27, 28, 29)]
    elif mo == 'smile': [s(x, 36, 'z') for x in (27, 28, 29)]; s(26, 35, 'z'); s(30, 35, 'z')
    elif mo == 'grin':  [s(x, 36, c) for x, c in zip(range(26, 31), 'zvvvz')]; [s(x, 37, 'z') for x in (27, 28, 29)]
    elif mo == 'o':     s(27, 36, 'z'); s(28, 36, 'v'); s(29, 36, 'z'); s(28, 37, 'z')
    elif mo == 'side':  [s(x, 36, 'z') for x in (28, 29, 30)]; s(27, 36, 'm')
    elif mo == 'hmm':   s(28, 36, 'z'); s(29, 36, 'z')
    elif mo == 'talk1': [s(x, 36, c) for x, c in zip((27, 28, 29), 'zvz')]; s(28, 37, 'z')
    elif mo == 'talk2': [s(x, 36, c) for x, c in zip(range(26, 31), 'zvvvz')]; [s(x, 37, c) for x, c in zip((27, 28, 29), 'zvz')]
    return img

MOODS = {
    'attentive': dict(brows='neutral', eyes='open', mouth='rest'),
    'curious':   dict(brows='raised', eyes='wide', mouth='o'),
    'amused':    dict(brows='relaxed', eyes='smile', mouth='grin', blush=True),
    'skeptical': dict(brows='one_up', eyes=('half', 'side'), mouth='side'),
    'pondering': dict(brows='inner_up', eyes='up', mouth='hmm'),
    'pleased':   dict(brows='relaxed', eyes='soft', mouth='smile', blush=True),
}


FRAMES = ("open", "half", "closed", "talk1", "talk2")


def frame(mood, name):
    if name in ("half", "closed"):
        return face(mood, eyes=name)
    if name.startswith("talk"):
        return face(mood, mouth=name)
    return face(mood)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = PATCH
    px0, py0, pw, ph = x0 + DX, y0 + DY, x1 - x0, y1 - y0
    face("attentive").save(OUT / "scene.png")
    base.crop((DX, DY, DX + 56, DY + 64)).save(OUT / "bust.png")        # the bust, re-cut from the scene
    sheet = Image.new("RGB", (pw * len(FRAMES), ph * len(MOODS)))
    for r, mood in enumerate(MOODS):
        for c, name in enumerate(FRAMES):
            sheet.paste(frame(mood, name).crop((px0, py0, px0 + pw, py0 + ph)), (c * pw, r * ph))
    sheet.save(OUT / "faces.png")
    meta = {
        "grid": [W, H], "patch": {"x": px0, "y": py0, "w": pw, "h": ph},
        "moods": list(MOODS), "frames": list(FRAMES),
        "anchor": {"face": [DX + 28, DY + 27], "head": [DX + 12, DY + 9, DX + 45, DY + 48]},
        "source": SOURCE.name,
        # A blink and a change of mood share one path, so expressions never jump:
        # open -> half -> closed (the new mood's brows and mouth arrive here) -> half -> open.
        "timing_ms": {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150]},
    }
    (OUT / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
