"""Socrates' full-screen chat scene: a generated picture, put on the bust's pixel grid.

1. sources/socrates_seated_gen.jpg was generated (ElevenLabs, Nano Banana 2, 9:16) from the
   bust and the café scene as references. It is median-filtered (generated "pixel art" is
   noisy and not on a true grid), then each 5.9 px cell is read back as its most common
   colour onto a 130 x 232 grid: on a 390 x 844 phone a cell is 3.64 px, as on the bust.
2. The grid is reduced to 20 colours and lone cells (fewer than three matching neighbours)
   take their neighbours' colour, so areas read as flat, clean shapes.
3. The generated head is taken out (wall stripes run down the columns, the frame and the
   wainscot are continued) and the bust's head goes in, drawn at 40 x 46 cells instead of
   56 x 64 so it sits in proportion with the body. Its skin is mapped onto the arms' own
   tones (base, shadow, deep shadow), so face and hands are one skin.
4. Expressions are small patches over the face (eyes, brows, mouth, cheeks).

    .venv/bin/python ui/web/tools/art/socrates_scene.py

writes ui/web/assets/personas/socrates/full/: scene.png (130 x 232, the attentive face),
faces.png (one row per mood: open, half, closed, talk1, talk2), faces.json, and bust.png
(the bust's framing cut from the scene, for comparison with the Meet page portrait).
The table that will cover his lower half is a separate layer, added later.
"""
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "ui/web/assets/personas/socrates/full"
SOURCE = Path(__file__).resolve().parent / "sources/socrates_seated_gen.jpg"
PORTRAIT = ROOT / "ui/web/assets/portrait_socrates.png"
W, H = 130, 232
COLOURS = 20
HEAD_GRID = (40, 46)             # the bust's 56 x 64 grid at 5/7: the head in proportion with the body
DX, DY = 45, 39                  # where the small bust's grid sits on the scene's


def cells(src, gw, gh, inset=0, bucket=1):
    """Each cell's most common colour (colours bucketed to ignore compression noise)."""
    a = np.asarray(src.convert("RGB")).astype(np.int32)
    h0, w0, _ = a.shape
    out = np.zeros((gh, gw, 3), np.uint8)
    for gy in range(gh):
        y0, y1 = int(gy * h0 / gh), max(int(gy * h0 / gh) + 1, int((gy + 1) * h0 / gh))
        for gx in range(gw):
            x0, x1 = int(gx * w0 / gw), max(int(gx * w0 / gw) + 1, int((gx + 1) * w0 / gw))
            c = a[y0 + inset:max(y0 + inset + 1, y1 - inset), x0 + inset:max(x0 + inset + 1, x1 - inset)].reshape(-1, 3)
            q = c // bucket
            keys = q[:, 0] * 1_000_000 + q[:, 1] * 1000 + q[:, 2]
            vals, counts = np.unique(keys, return_counts=True)
            out[gy, gx] = c[keys == vals[counts.argmax()]].mean(0)
    return Image.fromarray(out)


def despeckle(img, passes=3, keep=3):
    """A cell that matches fewer than `keep` of its neighbours takes their most common colour."""
    a = np.asarray(img).copy()
    h, w, _ = a.shape
    for _ in range(passes):
        b = a.copy()
        for y in range(h):
            for x in range(w):
                c = tuple(a[y, x])
                nb = [tuple(a[y + dy, x + dx]) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                      if (dy or dx) and 0 <= y + dy < h and 0 <= x + dx < w]
                if sum(n == c for n in nb) < keep:
                    b[y, x] = Counter(nb).most_common(1)[0][0]
        a = b
    return Image.fromarray(a)


def remove_head(base, keep):
    """Take the generated head out; `keep` is the cells the new head will cover."""
    bp = base.load(); out = base.copy(); op = out.load()
    wall = {(231, 221, 187), (239, 219, 177)}
    fx0, fy0, fy1 = 63, 13, 42                 # the painting's frame: left edge, top, bottom
    frame = Counter(bp[x, y] for y in range(fy0, fy1 + 1) for x in range(78, 97))
    mask = set()
    for y in range(28, 58):
        for x in range(46, 84):
            if x >= fx0 and y <= fy1:
                if frame[bp[x, y]] < 6: mask.add((x, y))
            elif bp[x, y] not in wall:
                mask.add((x, y))
    around = Counter(bp[x, y] for y in range(56, 80) for x in [*range(38, 48), *range(84, 94)])
    headish = {c for c in Counter(bp[x, y] for y in range(56, 78) for x in range(52, 80)) if around[c] < 4}
    mask |= {(x, y) for y in range(56, 80) for x in range(48, 84) if bp[x, y] in headish}
    for (x, y) in sorted(mask - keep, key=lambda p: p[1]):
        if x >= fx0 and y <= fy1:
            if x <= fx0 + 1: op[x, y] = bp[x, 25]          # the frame's left edge
            elif y >= fy1 - 2: op[x, y] = bp[86, y]        # its bottom edge
            else: op[x, y] = bp[x + 12, y]                 # the painting, from further right
        elif y < 58:
            op[x, y] = bp[x, 10]                           # wall stripes run down the columns
        else:                                              # wainscot, chair, robe: nearest in the row
            for d in range(1, 40):
                if (x - d, y) not in mask: op[x, y] = bp[x - d, y]; break
                if (x + d, y) not in mask: op[x, y] = bp[x + d, y]; break
    return out


# ---------- the scene ----------
_raw = cells(Image.open(SOURCE).convert("RGB").filter(ImageFilter.MedianFilter(5)), W, H, inset=1, bucket=10)
_q = despeckle(_raw.quantize(colors=COLOURS, method=Image.Quantize.MEDIANCUT, kmeans=5,
                             dither=Image.Dither.NONE).convert("RGB"))
SKIN, SHADE, DEEP = (221, 175, 128), (201, 154, 109), (188, 141, 100)   # the arms' tones
LIGHT = (233, 193, 148)          # the one highlight, on the crown

# ---------- the head, smaller than the bust's, in the arms' skin ----------
DROP = {(171, 175, 136), (162, 168, 128), (153, 160, 120), (179, 182, 145), (144, 153, 111), (124, 122, 87),   # background
        (253, 250, 240), (242, 236, 218), (221, 209, 178), (187, 169, 138),                                    # robe
        (184, 112, 79), (148, 87, 61), (111, 63, 44), (211, 140, 104)}                                         # sash
_bust = cells(Image.open(PORTRAIT), *HEAD_GRID)
_bp = _bust.load()
HEAD = {}
for by in range(6, 36):          # top of the head to the bottom of the beard
    for bx in range(HEAD_GRID[0]):
        c = _bp[bx, by]
        if c in DROP:
            continue
        HEAD[(bx, by)] = {(242, 207, 168): LIGHT if by <= 11 else SKIN, (226, 180, 132): SKIN,
                          (201, 154, 108): SHADE, (168, 119, 79): DEEP}.get(c, c)
base = remove_head(_q, {(x + DX, y + DY) for (x, y) in HEAD})
_b = base.load()
for (x, y), c in HEAD.items():
    _b[x + DX, y + DY] = c
PALETTE = sorted(set(base.get_flattened_data()))


# ---------- expressions ----------
C = dict(x=(246,239,226), A=(63,45,28), B=(91,66,42), k=(156,148,128), t=(164,112,75), u=(164,112,75),
         z=(156,90,68), v=(111,63,44), y=(232,162,131), m=(112,104,90))
# Where the features are, on the small bust's grid.
EYE_ROW, EYES = 18, {'L': (16, 18), 'R': (23, 25)}
BROW_ROW, BROWS = 16, {'L': (15, 18), 'R': (23, 26)}
MOUTH_ROW, MOUTH = 26, (19, 21)
CHEEKS = [(15, 21), (16, 21), (17, 21), (24, 21), (25, 21), (26, 21)]
PATCH = (13, 14, 29, 29)         # box that holds every change (x0, y0, x1, y1)
BROW_SHAPES = {                  # rows relative to BROW_ROW, one per brow column (left, right)
    'neutral': ([0] * 4, [0] * 4), 'raised': ([-1] * 4, [-1] * 4),
    'one_up': ([0, 0, 1, 1], [-1] * 4), 'inner_up': ([0, 0, -1, -1], [-1, -1, 0, 0]),
    'relaxed': ([1, 0, 0, 0], [0, 0, 0, 1]),
}
MOODS = {
    'attentive': dict(brows='neutral', eyes='open', mouth='rest'),
    'curious':   dict(brows='raised', eyes='wide', mouth='o'),
    'amused':    dict(brows='raised', eyes='smile', mouth='grin', blush=True),
    'skeptical': dict(brows='one_up', eyes=('half', 'side'), mouth='side'),
    'pondering': dict(brows='inner_up', eyes='up', mouth='hmm'),
    'pleased':   dict(brows='relaxed', eyes='soft', mouth='smile', blush=True),
}


def face(mood='attentive', eyes=None, mouth=None):
    img = base.copy(); p = img.load()
    def s(x, y, c): p[x + DX, y + DY] = C[c] if isinstance(c, str) else c
    skin = lambda x, y: base.getpixel((x + DX, y + DY))
    spec = MOODS[mood]
    # brows
    bl, br = BROW_SHAPES[spec['brows']]
    for side, rows in (('L', bl), ('R', br)):
        x0, x1 = BROWS[side]
        for x in range(x0, x1 + 1): s(x, BROW_ROW, skin(x, BROW_ROW + 1))
        for x, r in zip(range(x0, x1 + 1), rows): s(x, BROW_ROW + r, 'k')
    # eyes
    def eye(side, state):
        x0, x1 = EYES[side]; dark = 't' if side == 'L' else 'u'
        for x in range(x0, x1 + 1): s(x, EYE_ROW, skin(x, EYE_ROW + 1))
        seq = {'open': 'xAx', 'half': dark + 'A' + dark, 'closed': dark * 3, 'soft': dark + 'A' + dark,
               'side': 'xxA', 'wide': 'xAx', 'up': 'xxx', 'smile': dark + '.' + dark}[state]
        if state == 'smile': s(x0 + 1, EYE_ROW - 1, dark)                       # happy closed eyes: a little arch
        if state == 'up': s(x0 + 1, EYE_ROW - 1, 'A')                           # iris above, white below
        if state == 'wide': s(x0 + 1, EYE_ROW - 1, 'x')
        for x, ch in zip(range(x0, x1 + 1), seq):
            if ch != '.': s(x, EYE_ROW, ch)
    base_eyes = spec['eyes'] if isinstance(spec['eyes'], tuple) else (spec['eyes'], spec['eyes'])
    if eyes in ('half', 'closed') and spec['eyes'] != 'smile':
        base_eyes = (eyes, eyes)       # a blink; smiling eyes are already closed
    eye('L', base_eyes[0]); eye('R', base_eyes[1])
    if spec.get('blush'):
        for (x, y) in CHEEKS: s(x, y, 'y')
    # mouth, under the moustache
    m0, m1 = MOUTH
    for x in range(m0 - 1, m1 + 2):
        s(x, MOUTH_ROW, 'm' if m0 <= x <= m1 else skin(x, MOUTH_ROW)); s(x, MOUTH_ROW + 1, skin(x, MOUTH_ROW + 1))
    mo = mouth or spec['mouth']
    row = lambda xs, cs, r=MOUTH_ROW: [s(x, r, c) for x, c in zip(xs, cs)]
    mid = range(m0, m1 + 1); wide = range(m0 - 1, m1 + 2)
    if mo == 'rest':    row(mid, 'zzz')
    elif mo == 'smile': row(mid, 'zzz'); s(m0 - 1, MOUTH_ROW - 1, 'z'); s(m1 + 1, MOUTH_ROW - 1, 'z')
    elif mo == 'grin':  row(wide, 'zvvvz'); row(mid, 'zzz', MOUTH_ROW + 1)
    elif mo == 'o':     row(mid, 'zvz'); s(m0 + 1, MOUTH_ROW + 1, 'z')
    elif mo == 'side':  row(range(m0 + 1, m1 + 2), 'zzz')
    elif mo == 'hmm':   row(range(m0 + 1, m1 + 1), 'zz')
    elif mo == 'talk1': row(mid, 'zvz'); s(m0 + 1, MOUTH_ROW + 1, 'z')
    elif mo == 'talk2': row(wide, 'zvvvz'); row(mid, 'zvz', MOUTH_ROW + 1)
    return img


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
    base.crop((DX, DY, DX + HEAD_GRID[0], DY + HEAD_GRID[1])).save(OUT / "bust.png")     # the bust's framing, cut from the scene
    sheet = Image.new("RGB", (pw * len(FRAMES), ph * len(MOODS)))
    for r, mood in enumerate(MOODS):
        for c, name in enumerate(FRAMES):
            sheet.paste(frame(mood, name).crop((px0, py0, px0 + pw, py0 + ph)), (c * pw, r * ph))
    sheet.save(OUT / "faces.png")
    meta = {
        "grid": [W, H], "patch": {"x": px0, "y": py0, "w": pw, "h": ph},
        "moods": list(MOODS), "frames": list(FRAMES),
        "anchor": {"face": [DX + 20, DY + 20], "head": [DX + 9, DY + 6, DX + 32, DY + 36]},
        "source": SOURCE.name, "palette": len(PALETTE),
        # A blink and a change of mood share one path, so expressions never jump:
        # open -> half -> closed (the new mood's brows and mouth arrive here) -> half -> open.
        "timing_ms": {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150]},
    }
    (OUT / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("wrote", OUT, "-", len(PALETTE), "colours")


if __name__ == "__main__":
    main()
