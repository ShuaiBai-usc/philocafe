"""Socrates' full-screen chat scene, drawn pixel by pixel in the bust's style.

The head and beard are the bust's own pixels (portrait_socrates.png read back onto its
56 x 64 grid), so the character stays the same; the rest of him (seated in the armchair,
hands on his knees, sandalled feet on the rug) and the café are drawn here on the same
grid. The table that will cover his lower half is a separate layer, added later. Expressions are small patches over the face (eyes, brows,
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

# ---------- room ----------
P.update(floor=(150,108,72), floor2=(138,98,64), floorhi=(164,120,80), floordk=(118,82,52),
         rug=(178,186,150), rug2=(160,170,132), rugedge=(132,142,104), rughi=(196,202,170),
         shadow=(120,86,58), sandal=(122,84,52), sandal2=(98,66,40), strap=(148,87,61))
FLOOR = 140
for x in range(W):
    for y in range(0, 100):
        put(x, y, 'wall2' if (x // 3) % 3 == 0 else 'wall')
dith(0, 0, W, 6, 'wall', 'wall2')
rect(0, 100, W, FLOOR, 'panel'); rect(0, 100, W, 102, 'panelhi'); rect(0, 102, W, 103, 'paneldk')
for x in range(4, W, 12):
    rect(x, 106, x + 9, 107, 'panelhi'); rect(x, 107, x + 1, 141, 'panelhi'); rect(x + 8, 107, x + 9, 141, 'panel2'); rect(x, 140, x + 9, 141, 'panel2')
rect(0, FLOOR - 2, W, FLOOR, 'paneldk')                       # skirting
rect(0, FLOOR, W, H, 'floor')
for y in range(FLOOR + 6, H, 8): rect(0, y, W, y + 1, 'floor2')
random.seed(5)
for y in range(FLOOR + 2, H, 8):
    for x in range((y * 7) % 23, W, 23): rect(x, y, x + 1, y + 6, 'floordk')
# rug under the chair, seen from slightly above
for y in range(152, H):
    inset = max(0, 8 - (y - 152) // 3)
    rect(4 + inset, y, W - 4 - inset, y + 1, 'rug')
    put(4 + inset, y, 'rugedge'); put(W - 5 - inset, y, 'rugedge')
rect(8, 152, W - 8, 153, 'rugedge')
for y in range(158, H, 10):
    for x in range(14, W - 14, 8): put(x, y, 'rug2'); put(x + 1, y, 'rug2'); put(x, y + 1, 'rug2')
# bookshelf on the left, standing on the floor
rect(0, 10, 17, FLOOR, 'shelf'); rect(16, 10, 17, FLOOR, 'shelfdk'); rect(0, 10, 17, 12, 'shelfhi')
random.seed(7)
for sy in (13, 34, 55, 76, 97):
    rect(0, sy + 18, 17, sy + 20, 'shelfhi'); rect(0, sy + 20, 17, sy + 21, 'shelfdk')
    x = 0
    while x < 15:
        w = random.choice((2, 2, 3)); h = random.choice((13, 14, 15, 16)); c = random.choice(('bk1', 'bk2', 'bk3', 'bk4', 'bk5', 'bk6'))
        if random.random() < .12: x += 1; continue
        rect(x, sy + 18 - h, min(x + w, 16), sy + 18, c); rect(x, sy + 18 - h, min(x + w, 16), sy + 19 - h, 'shelfhi' if c != 'bk3' else 'bk4')
        x += w
for (x, y) in [(3,9),(4,8),(5,8),(6,9),(7,8),(8,9),(2,10),(9,10),(10,9),(11,10),(12,11),(13,12),(13,14),(14,16)]:
    put(x, y, 'leaf'); put(x, y + 1, 'leaf2')
rect(5, 9, 9, 11, 'pot')
# framed landscape and lamp
rect(64, 16, 90, 36, 'frame'); rect(64, 16, 90, 17, 'framehi'); rect(64, 16, 65, 36, 'framehi')
rect(66, 18, 88, 34, 'sky')
for x in range(66, 88):
    rect(x, 27 + int(2 * math.sin(x / 3)), x + 1, 34, 'hill'); rect(x, 30 + int(1.5 * math.cos(x / 2.2)), x + 1, 34, 'hill2')
rect(78, 24, 80, 29, 'town'); rect(81, 26, 83, 29, 'town'); put(79, 23, 'potdk')
rect(76, 0, 77, 8, 'cord')
for i, y in enumerate(range(8, 13)): rect(76 - 2 - i, y, 77 + 2 + i, y + 1, 'lamp')
rect(71, 12, 82, 13, 'lampdk'); rect(73, 8, 76, 10, 'lamphi'); dith(72, 13, 81, 15, 'glow', 'wall')
# plant in a pot on the floor, right
rect(85, 122, 95, FLOOR + 2, 'pot'); rect(85, 122, 95, 124, 'potdk'); rect(93, 124, 95, FLOOR + 2, 'potdk')
for (x0, y0, ln, dx) in [(90, 121, 24, -0.25), (91, 121, 30, 0.12), (89, 121, 18, -0.7), (92, 121, 20, 0.5)]:
    for t in range(ln):
        x = int(x0 + dx * t); y = y0 - t; put(x, y, 'leaf2')
        if t % 3 == 0:
            for k in range(1, 4): put(x - k, y + k // 2, 'leaf'); put(x + k, y + k // 2, 'leafhi' if k == 1 else 'leaf')

# ---------- armchair: back, then the rolled arms ----------
CX = 48
for y in range(50, 128):                                   # back, with rounded wings
    half = 35 if y > 60 else int(35 - (60 - y) ** 1.55 / 4)
    for x in range(CX - half, CX + half):
        c = 'chairhi' if x < CX - half + 3 or y < 53 else 'chair2' if x > CX + half - 4 else 'chair'
        put(x, y, c)
    put(CX - half - 1, y, 'chairdk'); put(CX + half, y, 'chairdk')
for x in range(16, 82, 6): put(x, 58, 'chair2'); put(x + 1, 58, 'chair2')
def arm_rest(x0, x1, light):
    # a rolled arm: the round top, then the flat front down to the floor
    for y in range(96, FLOOR - 3):
        for x in range(x0, x1):
            f = (x - x0) / (x1 - x0)
            if y < 103:
                c = 'chairhi' if y < 99 else 'chair'
            else:
                c = ('chairhi' if f < .25 else 'chair' if f < .8 else 'chair2') if light else ('chair' if f < .2 else 'chair2' if f < .85 else 'chairdk')
            put(x, y, c)
        put(x0 - 1, y, 'chairdk'); put(x1, y, 'chairdk')
    rect(x0, 103, x1, 104, 'chairdk')
    for x in range(x0 - 1, x1 + 1): put(x, 95, 'chairdk')
# seat cushion, seen beside his hips, and the front of the seat below it
rect(14, 104, 82, 122, 'chair'); rect(14, 104, 82, 106, 'chairhi'); rect(14, 121, 82, 122, 'chairdk')
rect(14, 122, 82, FLOOR - 3, 'chair2'); rect(14, FLOOR - 4, 82, FLOOR - 3, 'chairdk')
arm_rest(3, 15, True); arm_rest(81, 93, False)
for x0 in (4, 16, 77, 89):
    rect(x0, FLOOR - 3, x0 + 3, FLOOR + 3, 'shelf'); rect(x0 + 2, FLOOR - 3, x0 + 3, FLOOR + 3, 'shelfdk')
rect(4, FLOOR + 3, 92, FLOOR + 5, 'shadow')

# ---------- Socrates ----------
DX, DY = 20, 31
for by in range(9, 48):                                     # head and beard: the bust's pixels
    for bx in range(56):
        c = bp[bx, by]
        if c not in BG: put(bx + DX, by + DY, c)

def shade(f):            # light from the left
    return 'robehi' if f < .16 else 'robe' if f < .58 else 'robe2' if f < .86 else 'robe3'

LEFT = {78: 33, 79: 31, 80: 29, 81: 27, 82: 26, 83: 25, 84: 24, 85: 23, 86: 23, 87: 22, 88: 22}
RIGHT = {78: 67, 79: 68, 80: 69, 81: 70, 82: 71, 83: 72, 84: 72, 85: 73, 86: 73, 87: 74, 88: 74}
WAIST = 106                      # where the body meets the lap
def body_lr(y):
    if y <= 88: return LEFT[y], RIGHT[y]
    return 22 - (y - 88) // 9, 74 + (y - 88) // 9       # upper arms, a touch outward
# torso and upper arms
for y in range(78, WAIST + 2):
    l, r = body_lr(y)
    for x in range(l, r + 1): put(x, y, shade((x - l) / (r - l)))
    put(r + 1, y, 'robeedge')
for by in range(47, 64):                                     # the bust's own chest and sash
    for bx in range(56):
        c = bp[bx, by]
        if c not in BG and by + DY >= 78: put(bx + DX, by + DY, c)
# the sash carries on from the bust down to his left hip, where it tucks under the drape
SASH = ('sashhi', 'sash', 'sash', 'sash', 'sash2', 'sash2', 'sashdk')
for y in range(92, 104):
    x0 = 34 - int((y - 92) * 1.1)
    for k, c in enumerate(SASH):
        if x0 + k < 44 - (y - 92): put(x0 + k, y, c)
# creases between the upper arms and the body
for y in range(86, WAIST):
    l, r = body_lr(y)
    put(l + 7, y, 'robe2'); put(r - 7, y, 'robe3')
    if y > 90: put(l + 8, y, 'robe'); put(r - 8, y, 'robe2')
# the lap: thighs towards us, knees catching the light, a dip between the legs
KNEES = (35, 61)
for y in range(WAIST, 124):
    t = (y - WAIST) / 18
    l = int(22 - 2 * t); r = int(74 + 2 * t)
    for x in range(l, r + 1):
        f = (x - l) / (r - l)
        c = 'robehi' if f < .3 else 'robe' if f < .78 else 'robe2'     # the top of the thighs faces the light
        for kx in KNEES:
            d = ((x - kx) / 9) ** 2 + ((y - 119) / 5) ** 2
            if d < 1: c = 'robehi' if (x < kx and kx < 48) else 'robe' if kx < 48 else 'robe2' if x > kx + 3 else 'robe'
        put(x, y, c)
    put(r + 1, y, 'robeedge')
rect(23, WAIST, 74, WAIST + 1, 'robe2')
for y in range(WAIST + 3, 124): put(48, y, 'robe3'); put(49, y, 'robe2')
for (x, y0) in ((30, 110), (40, 112), (56, 112), (66, 110)):      # folds over the thighs, towards the knees
    for t in range(6): put(x + (t if x < 48 else -t) // 2, y0 + t, 'robe2' if x < 60 else 'robe3')
# forearms: from the elbows forward onto the thighs, hands resting on the knees
def forearm(xe, xh, light):
    for i, y in enumerate(range(WAIST - 4, 118)):
        xc = round(xe + (xh - xe) * i / 15)
        for x in range(xc - 4, xc + 4):
            put(x, y, ('robehi' if x < xc - 2 else 'robe') if light else ('robe' if x < xc - 1 else 'robe2'))
        put(xc - 5 if not light else xc + 4, y, 'robe3')
forearm(24, 33, True); forearm(72, 63, False)
HAND = ["..sssss..", ".sHsssss.", "sHssssss2", "sHssssss2", "s2s2s2s22", ".2.2.2.2."]
def hand(x0, y0, flip=False):
    for dy, row in enumerate(HAND):
        row = row[::-1] if flip else row
        for dx, ch in enumerate(row):
            if ch != '.': put(x0 + dx, y0 + dy, {'s': 'skin', 'H': 'skinhi', '2': 'skin2'}[ch])
hand(29, 116); hand(59, 116, flip=True)
# the edge of the knees, then the robe falls from them to mid-shin, in shade
for x in range(22, 77):                      # the knee edge: rounded under each knee
    dy = 1 if min(abs(x - KNEES[0]), abs(x - KNEES[1])) < 6 else 0
    put(x, 123 + dy, 'robe3')
    if dy: put(x, 123, 'robehi' if x < 48 else 'robe')
HEM = 148
for y in range(124, HEM):
    l = 25 + (y - 124) // 6; r = 71 - (y - 124) // 6
    for x in range(l, r + 1):
        f = (x - l) / (r - l)
        put(x, y, 'robe' if f < .22 else 'robe2' if f < .72 else 'robe3')
    put(r + 1, y, 'robeedge')
    for xf, d in ((33, 1), (41, 0), (55, 0), (63, -1)): put(xf + d * (y - 124) // 8, y, 'robe2' if xf < 60 else 'robe3')
rect(29, HEM - 2, 68, HEM - 1, 'robe3'); rect(29, HEM - 1, 68, HEM, 'robeedge')
for y in range(125, HEM - 2): put(48, y, 'robe3')                  # the hollow between the legs
# shins and sandalled feet on the rug
for (x0, light) in ((33, True), (57, False)):
    for y in range(HEM, HEM + 11):
        for x in range(x0, x0 + 7): put(x, y, ('skinhi' if x < x0 + 2 else 'skin') if light else ('skin' if x < x0 + 4 else 'skin2'))
    fy = HEM + 11
    rect(x0 - 2, fy, x0 + 9, fy + 4, 'skin'); rect(x0 - 2, fy + 3, x0 + 9, fy + 4, 'skin2')
    rect(x0 - 3, fy + 4, x0 + 10, fy + 6, 'sandal'); rect(x0 - 3, fy + 5, x0 + 10, fy + 6, 'sandal2')
    rect(x0 - 1, fy, x0 + 8, fy + 1, 'strap'); rect(x0 + 2, fy - 4, x0 + 5, fy - 3, 'strap')
    for k in range(0, 11, 2): put(x0 - 2 + k, fy + 2, 'skin2')
rect(28, HEM + 17, 70, HEM + 18, 'rugedge')


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
        "anchor": {"face": [DX + 28, DY + 27], "head": [DX + 12, DY + 9, DX + 45, DY + 48], "lap": 106, "feet": 165},
        # A blink and a change of mood share one path, so expressions never jump:
        # open -> half -> closed (the new mood's brows and mouth arrive here) -> half -> open.
        "timing_ms": {"half": 55, "closed": 85, "blink_every": [2800, 6500], "talk": [90, 150]},
    }
    (OUT / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
