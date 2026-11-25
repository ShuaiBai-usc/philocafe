"""Moving bits of the chat scenes, built by face_sheet.py from each persona's `ambient` list.

Each element is cut out on its own layer (layers.py): a mask, a plate with the element painted out, and
frames that draw the element back with some of its parts moved, so nothing behind it moves. The page draws
the current frame's rectangle over the scene (faces.json "ambient", frames in ambient.png, one row each):
    sway      leaves (green cells in the box): the upper half leans a column each way
    breathe   a pet: its upper half rises a row, the row below it stretches
    perk      a pet's head lifts a row; played when he starts a reply
    wag       a tail moves a column each way; played with perk
    flame     a small flame flickers (tip off, tip up, brighter); colour only
Modes: pingpong (frames back and forth, slow), flicker (random frame), once (on an event).
lamp_box finds the pendant lamp (it does not move; the page's dust drifts under it).
"""
import numpy as np

import layers


def lamp_box(base, xr):
    """the pendant lamp in columns xr, rows 0-33: cells unlike their column's wallpaper (rows 34-38)"""
    a = base.astype(int)
    m = np.zeros(base.shape[:2], bool)
    for x in range(xr[0], xr[1] + 1):
        col = [tuple(c) for c in base[34:39, x]]
        bg = np.array(max(set(col), key=col.count))
        for y in range(34):
            m[y, x] = np.abs(a[y, x] - bg).sum() > 30
    m = layers.keep_component(m)
    ys, xs = np.nonzero(m)
    return int(xs.min()), 0, int(xs.max()), int(ys.max())


def green_mask(base, rect):
    import cv2
    x0, y0, x1, y1 = rect
    hsv = cv2.cvtColor(base, cv2.COLOR_RGB2HSV).astype(int)
    g = (hsv[..., 0] > 28) & (hsv[..., 0] < 95) & (hsv[..., 1] > 45)
    m = np.zeros(base.shape[:2], bool)
    m[y0:y1 + 1, x0:x1 + 1] = g[y0:y1 + 1, x0:x1 + 1]
    return m


def pet_mask(base, rect, keep=None):
    """GrabCut inside rect: the rect's border and the sage rug are background, the middle is the pet;
    `keep` (boxes) trims it where the floor's edge would join it"""
    import cv2
    x0, y0, x1, y1 = rect
    S = 6
    big = cv2.resize(base, (base.shape[1] * S, base.shape[0] * S), interpolation=cv2.INTER_NEAREST)
    mk = np.full(big.shape[:2], cv2.GC_BGD, np.uint8)
    mk[(y0 + 1) * S:y1 * S, (x0 + 1) * S:x1 * S] = cv2.GC_PR_FGD
    hsv = cv2.cvtColor(base, cv2.COLOR_RGB2HSV).astype(int)
    green = (hsv[..., 0] > 30) & (hsv[..., 0] < 75) & (hsv[..., 1] > 30)
    mk[cv2.resize(green.astype(np.uint8), big.shape[1::-1], interpolation=cv2.INTER_NEAREST).astype(bool)] = cv2.GC_BGD
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    mk[(cy - 3) * S:(cy + 3) * S, (cx - 4) * S:(cx + 4) * S] = cv2.GC_FGD
    cv2.grabCut(cv2.cvtColor(big, cv2.COLOR_RGB2BGR), mk, None, np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_MASK)
    fg = ((mk == cv2.GC_FGD) | (mk == cv2.GC_PR_FGD)).astype(np.uint8)
    m = cv2.resize(fg, base.shape[1::-1], interpolation=cv2.INTER_AREA) > 0
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)).astype(bool)   # no rug edges
    if keep:
        k = np.zeros_like(m)
        for kx0, ky0, kx1, ky1 in keep:
            k[ky0:ky1 + 1, kx0:kx1 + 1] = True
        m &= k
    return layers.fill_holes(layers.keep_component(m, (cx, cy)))


def rise(m, top, cut):
    """moves for a part rising a row: rows top..cut go up, row cut is also kept in place (it stretches)"""
    return [(layers.rows(m, cut, cut), 0, 0), (layers.rows(m, top, cut), 0, -1)]


def sway(base, rect):
    x0, y0, x1, y1 = rect
    m = green_mask(base, rect)
    back = layers.plate(base, m)
    top = (y0 + y1) // 2
    lean = lambda dx: layers.compose(base, back, m, [(layers.rows(m, y0, top), dx, 0)])
    return (x0 - 1, y0, x1 + 1, y1), [base, lean(1), lean(-1)], {"mode": "pingpong", "seq": [0, 1, 0, 2], "ms": [1100, 1700]}


def breathe(base, rect, keep=None):
    m = pet_mask(base, rect, keep)
    back = layers.plate(base, m)
    ys = np.nonzero(m.any(1))[0]
    top, mid = ys.min(), (ys.min() + ys.max()) // 2
    x0, y0, x1, y1 = rect
    return (x0, y0 - 1, x1, y1), [base, layers.compose(base, back, m, rise(m, top, mid))], \
        {"mode": "pingpong", "seq": [0, 1], "ms": [1300, 1600]}


def perk(base, rect, head, keep=None):
    m = pet_mask(base, rect, keep)
    back = layers.plate(base, m)
    hx0, hy0, hx1, hy1 = head
    hm = np.zeros_like(m)
    hm[hy0:hy1 + 1, hx0:hx1 + 1] = m[hy0:hy1 + 1, hx0:hx1 + 1]
    top = np.nonzero(hm.any(1))[0].min()
    x0, y0, x1, y1 = rect
    up = layers.compose(base, back, m, [(layers.rows(hm, hy1, hy1), 0, 0), (layers.rows(hm, top, hy1), 0, -1)])
    return (x0, y0 - 1, x1, y1), [base, up], {"mode": "once", "on": ["reply"], "seq": [1, 0], "ms": [900, 0]}


def wag(base, rect, tail, keep=None):
    m = pet_mask(base, rect, keep)
    back = layers.plate(base, m)
    tx0, ty0, tx1, ty1 = tail
    tm = np.zeros_like(m)
    tm[ty0:ty1 + 1, tx0:tx1 + 1] = m[ty0:ty1 + 1, tx0:tx1 + 1]
    go = lambda dx: layers.compose(base, back, m, [(tm, dx, 0)])
    return (tx0 - 2, ty0, tx1 + 2, ty1), [base, go(1), go(-1)], \
        {"mode": "once", "on": ["reply"], "seq": [1, 2, 1, 2, 1, 2, 0], "ms": [130, 0]}


def flame(base, rect):
    x0, y0, x1, y1 = rect
    a = base.astype(int)
    m = np.zeros(base.shape[:2], bool)
    m[y0:y1 + 1, x0:x1 + 1] = (a[y0:y1 + 1, x0:x1 + 1, 0] > 190) & (a[y0:y1 + 1, x0:x1 + 1, 1] > 120)
    ys, xs = np.nonzero(m)
    top = ys.min()
    tips = [x for y, x in zip(ys, xs) if y == top]
    low, high, bright = base.copy(), base.copy(), base.copy()
    for x in tips:
        low[top, x] = base[top, x + 1] if not m[top, x + 1] else base[top - 1, x]
        high[top - 1, x] = base[top, x]
    for y, x in zip(ys, xs):
        bright[y, x] = np.clip(base[y, x].astype(int) * 1.12 + 10, 0, 255)
    return (x0, y0 - 1, x1, y1), [base, low, high, bright], {"mode": "flicker", "ms": [110, 260]}


KINDS = {"sway": sway, "breathe": breathe, "perk": perk, "wag": wag, "flame": flame}


def build(base, items):
    """[(rect, frames, info)] for a persona's ambient list (each item: kind plus its arguments)"""
    out = []
    H, W = base.shape[:2]
    for it in items:
        (x0, y0, x1, y1), frames, info = KINDS[it[0]](base, *it[1:])
        rect = (max(0, int(x0)), max(0, int(y0)), min(W - 1, int(x1)), min(H - 1, int(y1)))
        out.append((rect, frames, {"kind": it[0], **info}))
    return out
