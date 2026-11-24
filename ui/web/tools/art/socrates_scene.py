"""Socrates' full-screen chat scene: a generated picture, put on the bust's pixel grid.

1. sources/socrates_seated_gen.jpg was generated (ElevenLabs, Nano Banana 2, 9:16) from the
   bust and the café scene as references. Generated "pixel art" is not on a true grid, so
   each 5.9 px cell is read back as its most common colour onto a 130 x 232 grid: on a
   390 x 844 phone a cell is 3.64 px, the same as the bust on the Meet page.
2. Every cell takes the nearest colour of one palette: the bust's 28 colours plus the few
   the room needs that the bust lacks. So skin, robe, sash and greens are the bust's own
   tones everywhere, and the face matches the arms and hands.
3. Lone cells that match fewer than two neighbours take their neighbours' colour (less noise).
4. The generated head is taken out and the bust's head goes in, drawn again a little smaller
   (the bust read onto a 48 x 55 grid instead of 56 x 64, eyes repainted), so the head sits
   in proportion with the generated body.
5. Expressions are small patches over the face (eyes, brows, mouth, cheeks).

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
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "ui/web/assets/personas/socrates/full"
SOURCE = Path(__file__).resolve().parent / "sources/socrates_seated_gen.jpg"
PORTRAIT = ROOT / "ui/web/assets/portrait_socrates.png"
W, H = 130, 232
HEAD_GRID = (48, 55)             # the bust's 56 x 64 grid, about 86%: the head in proportion
DX, DY = 41, 34                  # where the small bust's grid sits on the scene's
BG = {(171, 175, 136), (162, 168, 128), (179, 182, 145), (153, 160, 120), (144, 153, 111)}   # bust background
WEIGHT = np.array([.30, .59, .11])


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


def palette_for(img, bust):
    """The bust's colours, plus the room's own where none of the bust's is close."""
    pal = sorted(set(bust.get_flattened_data()))
    room = img.quantize(colors=20, method=Image.Quantize.MEDIANCUT, kmeans=3, dither=Image.Dither.NONE).convert("RGB")
    for c in sorted(set(room.get_flattened_data())):
        if min((((np.array(c) - np.array(p)) * WEIGHT) ** 2).sum() for p in pal) > 60:
            pal.append(c)
    return pal


def to_palette(img, pal):
    p = np.array(pal, float)
    a = np.asarray(img).reshape(-1, 3).astype(float)
    idx = ((((a[:, None, :] - p[None]) * WEIGHT) ** 2).sum(-1)).argmin(1)
    return Image.fromarray(p[idx].reshape(img.height, img.width, 3).astype(np.uint8))


def despeckle(img, passes=2, keep=2):
    """A cell that matches fewer than `keep` of its 8 neighbours takes their most common colour."""
    a = np.asarray(img).copy()
    h, w, _ = a.shape
    for _ in range(passes):
        b = a.copy()
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                c = tuple(a[y, x])
                nb = [tuple(a[y + dy, x + dx]) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
                if sum(n == c for n in nb) < keep:
                    b[y, x] = Counter(nb).most_common(1)[0][0]
        a = b
    return Image.fromarray(a)


# ---------- the head, a little smaller than the bust's ----------
SMALL = cells(Image.open(PORTRAIT), *HEAD_GRID)
_s = SMALL.load()
for x0 in (18, 27):              # the downscale loses the eyes: white, dark, brown, white as in the bust
    for k, c in enumerate([(246, 239, 226), (63, 45, 28), (91, 66, 42), (246, 239, 226)]):
        _s[x0 + k, 21] = c
HEAD_ROWS = range(6, 41)         # top of the head to the bottom of the beard

# ---------- the scene ----------
_raw = cells(Image.open(SOURCE), W, H, inset=1, bucket=12)
PALETTE = palette_for(_raw, SMALL)
base = despeckle(to_palette(_raw, PALETTE))
_b = base.load()
# take the generated head out: its colours inside its box, filled from what is around it
_box = (49, 34, 82, 76)
_around = Counter(_b[x, y] for y in range(28, 76) for x in [*range(40, 49), *range(82, 92)])
_around.update(_b[x, y] for y in range(20, 34) for x in range(49, 82))
_headish = {c for c, n in Counter(_b[x, y] for y in range(37, 74) for x in range(53, 77)).items() if _around[c] < 3}
_mask = {(x, y) for y in range(_box[1], _box[3]) for x in range(_box[0], _box[2]) if _b[x, y] in _headish}
_new = {(bx + DX, by + DY) for by in HEAD_ROWS for bx in range(HEAD_GRID[0]) if _s[bx, by] not in BG}
_orig = base.copy().load()
for (x, y) in sorted((p for p in _mask if p not in _new), key=lambda p: p[1]):
    if y < DY + 8:               # above the new head: copy down the column, so the frame keeps its edges
        yy = y
        while (x, yy) in _mask and yy > 0:
            yy -= 1
        _b[x, y] = _b[x, yy]
    else:                        # beside it: the nearest cell in the row that is not head
        for d in range(1, 30):
            if (x - d, y) not in _mask and x - d >= 0:
                _b[x, y] = _orig[x - d, y]; break
            if (x + d, y) not in _mask and x + d < W:
                _b[x, y] = _orig[x + d, y]; break
for (x, y) in _new:
    _b[x, y] = _s[x - DX, y - DY]


# ---------- expressions ----------
C = dict(x=(246,239,226), A=(63,45,28), B=(91,66,42), k=(156,148,128), t=(168,119,79), u=(148,87,61),
         z=(156,90,68), v=(111,63,44), y=(232,162,131), m=(112,104,90))
# Where the features are, on the small bust's grid.
EYE_ROW, EYES = 21, {'L': (18, 21), 'R': (27, 30)}
BROW_ROW, BROWS = 19, {'L': (18, 21), 'R': (27, 30)}
MOUTH_ROW, MOUTH = 31, (23, 25)
CHEEKS = [(17, 25), (18, 25), (19, 25), (18, 26), (28, 25), (29, 25), (30, 25), (29, 26)]
PATCH = (14, 16, 35, 35)         # box that holds every change (x0, y0, x1, y1)
BROW_SHAPES = {                  # rows relative to BROW_ROW, one per brow column (left, right)
    'neutral': ([0] * 4, [0] * 4), 'raised': ([-1] * 4, [-1] * 4),
    'one_up': ([0, 0, 1, 1], [-1] * 4), 'inner_up': ([0, 0, -1, -1], [-1, -1, 0, 0]),
    'relaxed': ([1, 0, 0, 0], [0, 0, 0, 1]),
}
MOODS = {
    'attentive': dict(brows='neutral', eyes='open', mouth='rest'),
    'curious':   dict(brows='raised', eyes='wide', mouth='o'),
    'amused':    dict(brows='relaxed', eyes='smile', mouth='grin', blush=True),
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
        seq = {'open': 'xABx', 'half': dark + 'AB' + dark, 'closed': dark * 4, 'soft': dark + 'AB' + dark,
               'side': 'xxAB', 'wide': 'xABx', 'up': 'xxxx', 'smile': dark + '..' + dark}[state]
        if state == 'smile': s(x0 + 1, EYE_ROW - 1, dark); s(x0 + 2, EYE_ROW - 1, dark)       # happy closed eyes
        if state == 'up': s(x0 + 1, EYE_ROW - 1, 'A'); s(x0 + 2, EYE_ROW - 1, 'B')            # iris above, white below
        if state == 'wide': s(x0 + 1, EYE_ROW - 1, 'x'); s(x0 + 2, EYE_ROW - 1, 'x')
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
    base.crop((DX - 4, DY - 2, DX + 52, DY + 62)).save(OUT / "bust.png")     # the bust's framing, cut from the scene
    sheet = Image.new("RGB", (pw * len(FRAMES), ph * len(MOODS)))
    for r, mood in enumerate(MOODS):
        for c, name in enumerate(FRAMES):
            sheet.paste(frame(mood, name).crop((px0, py0, px0 + pw, py0 + ph)), (c * pw, r * ph))
    sheet.save(OUT / "faces.png")
    meta = {
        "grid": [W, H], "patch": {"x": px0, "y": py0, "w": pw, "h": ph},
        "moods": list(MOODS), "frames": list(FRAMES),
        "anchor": {"face": [DX + 24, DY + 23], "head": [DX + 10, DY + 6, DX + 38, DY + 41]},
        "source": SOURCE.name, "palette": len(PALETTE),
        # A blink and a change of mood share one path, so expressions never jump:
        # open -> half -> closed (the new mood's brows and mouth arrive here) -> half -> open.
        "timing_ms": {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150]},
    }
    (OUT / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("wrote", OUT, "-", len(PALETTE), "colours")


if __name__ == "__main__":
    main()
