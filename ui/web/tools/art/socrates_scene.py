"""Socrates' full-screen chat scene, drawn pixel by pixel in the bust's style.

The head and beard are the bust's own pixels (portrait_socrates.png read back onto its
56 x 64 grid), so the character stays the same; the body, armchair, café and table are
drawn here on the same grid. Expressions are small patches over the face (eyes, brows,
mouth, cheeks), so changing mood never moves the head.

    .venv/bin/python ui/web/tools/art/socrates_scene.py

writes ui/web/assets/personas/socrates/full/: scene.png (96 x 208, the attentive face),
faces.png (one row per mood: open, half, closed, talk1, talk2) and faces.json (where the
patch goes, the frame order and the timings the chat page uses).
"""
import json
import math
import random
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "ui/web/assets/personas/socrates/full"
W, H = 96, 208


def bust_grid(path=ROOT / "ui/web/assets/portrait_socrates.png", nw=56, nh=64):
    """The bust is drawn on a 56 x 64 grid scaled up about 7.2x; sample each cell's centre."""
    src = Image.open(path).convert("RGB")
    out = Image.new("RGB", (nw, nh))
    for y in range(nh):
        for x in range(nw):
            out.putpixel((x, y), src.getpixel((int((x + .5) * src.width / nw), int((y + .5) * src.height / nh))))
    return out


B = bust_grid(); bp = B.load()
BG = {(171,175,136),(162,168,128),(179,182,145),(153,160,120),(144,153,111)}   # bust background greens
P = dict(
  wall=(234,224,196), wall2=(226,214,184), wallhi=(240,232,208),
  panel=(170,128,90), panel2=(156,116,80), panelhi=(184,142,100), paneldk=(132,96,64),
  shelf=(122,88,58), shelfdk=(98,70,46), shelfhi=(146,108,72),
  bk1=(144,153,111), bk2=(184,112,79), bk3=(221,209,178), bk4=(156,148,128), bk5=(124,122,87), bk6=(201,154,108),
  frame=(150,108,70), framehi=(180,138,94), sky=(200,210,190), hill=(150,160,120), hill2=(124,134,98), town=(214,196,160),
  lamp=(196,128,84), lampdk=(156,94,60), lamphi=(232,170,120), cord=(110,84,60), glow=(250,236,200),
  leaf=(124,140,98), leaf2=(104,120,82), leafhi=(150,164,118), pot=(184,112,79), potdk=(148,87,61),
  chair=(150,168,124), chair2=(132,150,108), chairhi=(170,186,142), chairdk=(112,128,92),
  robe=(242,236,218), robehi=(253,250,240), robe2=(221,209,178), robe3=(187,169,138), robeedge=(124,122,87),
  sash=(184,112,79), sashhi=(211,140,104), sash2=(148,87,61), sashdk=(111,63,44),
  skin=(226,180,132), skinhi=(242,207,168), skin2=(201,154,108), skin3=(168,119,79),
  wood=(176,126,84), wood2=(164,116,76), woodhi=(192,142,96), wooddk=(140,98,62), woodedge=(116,80,50),
  cup=(246,239,226), cup2=(221,209,178), coffee=(111,63,44), saucer=(230,226,212),
)
im = Image.new('RGB', (W, H), P['wall']); px = im.load()
def put(x, y, c):
    if 0 <= x < W and 0 <= y < H: px[x, y] = P[c] if isinstance(c, str) else c
def rect(x0, y0, x1, y1, c):
    for y in range(y0, y1):
        for x in range(x0, x1): put(x, y, c)
def dith(x0, y0, x1, y1, c1, c2):
    for y in range(y0, y1):
        for x in range(x0, x1): put(x, y, c1 if (x + y) % 2 else c2)

# --- wall: cream stripes, softer and lower in contrast than Socrates
for x in range(W):
    for y in range(0, 92):
        put(x, y, 'wall2' if (x // 3) % 3 == 0 else 'wall')
dith(0, 0, W, 6, 'wall', 'wall2')
# wood panelling below the chair rail
rect(0, 92, W, 112, 'panel'); rect(0, 92, W, 94, 'panelhi'); rect(0, 94, W, 95, 'paneldk')
for x in range(4, W, 12):
    rect(x, 97, x + 9, 98, 'panelhi'); rect(x, 98, x + 1, 110, 'panelhi'); rect(x + 8, 98, x + 9, 110, 'panel2'); rect(x, 109, x + 9, 110, 'panel2')

# --- bookshelf, left
rect(0, 10, 17, 112, 'shelf'); rect(16, 10, 17, 112, 'shelfdk'); rect(0, 10, 17, 12, 'shelfhi')
random.seed(7)
for sy in (13, 33, 53, 73):
    rect(0, sy + 17, 17, sy + 19, 'shelfhi'); rect(0, sy + 19, 17, sy + 20, 'shelfdk')
    x = 0
    while x < 15:
        w = random.choice((2, 2, 3)); h = random.choice((13, 14, 15, 16)); c = random.choice(('bk1', 'bk2', 'bk3', 'bk4', 'bk5', 'bk6'))
        if random.random() < .12: x += 1; continue
        rect(x, sy + 17 - h, min(x + w, 16), sy + 17, c); rect(x, sy + 17 - h, min(x + w, 16), sy + 18 - h, 'shelfhi' if c != 'bk3' else 'bk4')
        x += w
# a trailing plant on top of the shelf
for (x, y) in [(3,9),(4,8),(5,8),(6,9),(7,8),(8,9),(2,10),(9,10),(10,9),(11,10),(12,11),(13,12),(13,14),(14,16)]:
    put(x, y, 'leaf'); put(x, y + 1, 'leaf2')
rect(5, 9, 9, 11, 'pot')

# --- framed landscape, right
rect(64, 16, 90, 36, 'frame'); rect(64, 16, 90, 17, 'framehi'); rect(64, 16, 65, 36, 'framehi')
rect(66, 18, 88, 34, 'sky')
for x in range(66, 88):
    h1 = 27 + int(2 * math.sin(x / 3)); rect(x, h1, x + 1, 34, 'hill')
    h2 = 30 + int(1.5 * math.cos(x / 2.2)); rect(x, h2, x + 1, 34, 'hill2')
rect(78, 24, 80, 29, 'town'); rect(81, 26, 83, 29, 'town'); put(79, 23, 'potdk')

# --- hanging lamp, centre-right (above his head, not over it)
rect(76, 0, 77, 8, 'cord')
for i, y in enumerate(range(8, 13)):
    rect(76 - 2 - i, y, 77 + 2 + i, y + 1, 'lamp')
rect(71, 12, 82, 13, 'lampdk'); rect(73, 8, 76, 10, 'lamphi')
dith(72, 13, 81, 15, 'glow', 'wall')

# --- plant, right of the chair
rect(84, 96, 95, 108, 'pot'); rect(84, 96, 95, 98, 'potdk'); rect(93, 98, 95, 108, 'potdk')
for (x0, y0, ln, dx) in [(89, 95, 18, -0.3), (90, 95, 22, 0.15), (88, 95, 14, -0.8), (91, 95, 16, 0.6)]:
    for t in range(ln):
        x = int(x0 + dx * t); y = y0 - t
        put(x, y, 'leaf2')
        if t % 3 == 0:
            for k in range(1, 4): put(x - k, y + k // 2, 'leaf'); put(x + k, y + k // 2, 'leafhi' if k == 1 else 'leaf')

# --- armchair behind him
def chair_back():
    for y in range(52, 112):
        half = 34 if y > 60 else int(34 - (60 - y) ** 1.6 / 4)
        for x in range(48 - half, 48 + half):
            c = 'chair'
            if x < 48 - half + 3: c = 'chairhi'
            elif x > 48 + half - 4: c = 'chair2'
            if y < 55: c = 'chairhi'
            put(x, y, c)
        put(48 - half - 1, y, 'chairdk'); put(48 + half, y, 'chairdk')
    for x in range(14, 82, 6): put(x, 58, 'chair2'); put(x + 1, 58, 'chair2')     # buttons / seams
chair_back()
# chair arms
rect(10, 88, 24, 112, 'chair'); rect(10, 86, 24, 89, 'chairhi'); rect(10, 88, 12, 112, 'chairhi'); rect(23, 88, 24, 112, 'chairdk')
rect(72, 88, 86, 112, 'chair2'); rect(72, 86, 86, 89, 'chair'); rect(85, 88, 86, 112, 'chairdk'); rect(72, 88, 73, 112, 'chairdk')

# --- Socrates: the bust's head and beard, pixel for pixel
DX, DY = 20, 31
for by in range(9, 48):
    for bx in range(56):
        c = bp[bx, by]
        if c not in BG: put(bx + DX, by + DY, c)

# torso: the bust's chest (rows 47-63, sash included) continued with the same shading
def outline_x(y):
    # silhouette from the bust's own shoulder line, carried on outward and down
    t = y - 78
    left = max(15, 33 - int(t * 1.05) if t < 14 else 19 - int((t - 14) * .45))
    right = min(81, 68 + int(t * .55) if t < 14 else 76 + int((t - 14) * .3))
    return left, right
for y in range(78, 113):
    l, r = outline_x(y)
    for x in range(l, r + 1):
        f = (x - l) / max(1, r - l)
        c = 'robehi' if f < .2 else 'robe' if f < .6 else 'robe2' if f < .86 else 'robe3'
        put(x, y, c)
    put(r + 1, y, 'robeedge')
for by in range(47, 64):                      # the bust's chest and sash on top
    for bx in range(56):
        c = bp[bx, by]
        if c not in BG and by + DY >= 78: put(bx + DX, by + DY, c)
# the sash slips under the drape on his left side, as in the bust, so it simply ends there
# soft folds in the robe below the chest
for (x, y0, ln, c) in [(52, 97, 12, 'robe2'), (60, 99, 10, 'robe2'), (44, 100, 8, 'robe2'), (68, 96, 14, 'robe3'), (36, 102, 7, 'robe2')]:
    for t in range(ln): put(x + t // 4, y0 + t, c)
# upper arms under the robe at both sides, a shade darker so the arms read
for y in range(88, 113):
    l, r = outline_x(y)
    for x in range(l, l + 5): put(x, y, 'robe' if x > l + 1 else 'robehi')
    put(l + 5, y, 'robe2')
    for x in range(r - 4, r + 1): put(x, y, 'robe3' if x > r - 2 else 'robe2')
    put(r - 5, y, 'robe3')

# hands resting on the table edge, fingers towards the middle
LEFT_HAND = [
    "..ssss....",
    ".sHHsss...",
    "sHHssssss.",
    "sHsssssss2",
    "sss2s2s2s2",
    ".2222222..",
]
def hand(x0, y0, rows, flip=False):
    for dy, row in enumerate(rows):
        row = row[::-1] if flip else row
        for dx, ch in enumerate(row):
            c = {'s': 'skin', 'H': 'skinhi', '2': 'skin2'}.get(ch)
            if c: put(x0 + dx, y0 + dy, c)
def sleeve(x0, x1, y0, y1):
    rect(x0, y0, x1, y1, 'robe2'); rect(x0, y1 - 1, x1, y1, 'robe3')

# --- table top (lower half): quiet planks seen from slightly above
rect(0, 112, W, H, 'wood')
rect(0, 112, W, 113, 'woodedge'); rect(0, 113, W, 114, 'wooddk')
for y in range(116, H, 13):
    rect(0, y, W, y + 1, 'wood2')
random.seed(3)
for y in range(118, H, 3):
    x = random.randrange(W); ln = random.randrange(6, 18)
    rect(x, y, min(W, x + ln), y + 1, 'woodhi' if random.random() < .5 else 'wood2')
# forearms come in from the sides; the hands rest clasped on the table edge
for y in range(98, 112):
    t = (y - 98) / 13
    xl = int(20 + t * 16); xr = int(76 - t * 16)
    for x in range(xl - 5, xl + 4): put(x, y, 'robe' if x < xl - 1 else 'robe2')
    put(xl + 4, y, 'robe3')
    for x in range(xr - 3, xr + 6): put(x, y, 'robe2' if x < xr + 2 else 'robe3')
    put(xr - 4, y, 'robe3')
HANDS = [
    "....ssssssssss....",
    "..sHHsssssssss22..",
    ".sHHssHssss2sss22.",
    "sHHsssHssss2ssss22",
    "sHssssHsss2sssss22",
    "s2s2s2s2ss2s2s2s22",
    ".222222222222222..",
]
for dy, row in enumerate(HANDS):
    for dx, ch in enumerate(row):
        c = {'s': 'skin', 'H': 'skinhi', '2': 'skin2'}.get(ch)
        if c: put(39 + dx, 108 + dy, c)
rect(39, 115, 57, 116, 'wooddk')
# cup of coffee near his right hand (the viewer's left)
rect(10, 120, 22, 123, 'saucer'); rect(11, 123, 21, 124, 'cup2')
rect(12, 114, 20, 121, 'cup'); rect(18, 114, 20, 121, 'cup2'); rect(12, 114, 20, 115, 'coffee')
rect(20, 116, 22, 117, 'cup'); rect(21, 116, 22, 119, 'cup'); rect(20, 118, 22, 119, 'cup2')



# ---------- expressions ----------
base = im.copy()
C = dict(x=(246,239,226), A=(63,45,28), B=(91,66,42), k=(156,148,128), f=(201,195,176), t=(168,119,79), u=(148,87,61),
         l=(201,154,108), h=(226,180,132), z=(156,90,68), v=(111,63,44), w=(211,140,104), y=(232,162,131), m=(112,104,90),
         i=(230,226,212), o=(242,207,168))
EYES = {'L': (22, 25), 'R': (32, 35)}        # columns of each eye, row 25
BROWS = {'L': (21, 25), 'R': (31, 35)}       # columns of each brow, row 22
PATCH = (17, 19, 39, 39)                     # bust-grid box that holds every change (x0, y0, x1, y1)

def face(mood='attentive', eyes=None, mouth=None):
    img = base.copy(); p = img.load()
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
    sheet = Image.new("RGB", (pw * len(FRAMES), ph * len(MOODS)))
    for r, mood in enumerate(MOODS):
        for c, name in enumerate(FRAMES):
            sheet.paste(frame(mood, name).crop((px0, py0, px0 + pw, py0 + ph)), (c * pw, r * ph))
    sheet.save(OUT / "faces.png")
    meta = {
        "grid": [W, H], "patch": {"x": px0, "y": py0, "w": pw, "h": ph},
        "moods": list(MOODS), "frames": list(FRAMES),
        "anchor": {"face": [DX + 28, DY + 27], "head": [DX + 12, DY + 9, DX + 45, DY + 48]},
        # A blink and a change of mood share one path, so expressions never jump:
        # open -> half -> closed (the new mood's brows and mouth arrive here) -> half -> open.
        "timing_ms": {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150]},
    }
    (OUT / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
