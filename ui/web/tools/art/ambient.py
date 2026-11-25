"""Moving bits of the chat scenes, built by face_sheet.py from each persona's `ambient` list.

Every element is a small rectangle of the scene with a few frames; the page draws the current frame over
the scene (faces.json "ambient", frames in ambient.png, one row per element):
    lamp      the pendant lamp's shade swings a column left and right (cord kinked above the shade)
    sway      leaves (green cells in the box): the upper half leans a column each way
    breathe   a pet: its upper half rises a row (GrabCut finds it on the rug)
    perk      a pet's head lifts a row; played when the user sends or he starts a reply
    wag       a tail moves a column each way; played with perk
    flame     a small flame flickers (warm bright cells: tip off, tip up, brighter)
Mode per element: pingpong (frames back and forth, slow), flicker (random frame), or once (on an event).
"""
import numpy as np


def keep_component(m, seed=None):
    """the 8-connected part of m holding `seed` (default: the largest part)"""
    import cv2
    n, lab = cv2.connectedComponents(m.astype(np.uint8), connectivity=8)
    if n <= 1:
        return m
    if seed is not None and lab[seed[1], seed[0]]:
        k = lab[seed[1], seed[0]]
    else:
        k = 1 + int(np.argmax([(lab == i).sum() for i in range(1, n)]))
    return lab == k


def col_bg(base, xs, rows):
    """each column's wallpaper colour: its commonest colour over `rows` (the stripes are vertical)"""
    out = {}
    for x in xs:
        col = [tuple(c) for c in base[rows[0]:rows[1] + 1, x]]
        out[x] = max(set(col), key=col.count)
    return out


def nearest_out(base, m, x, y, side):
    """the closest cell in row y, on `side` (-1 left, +1 right) first, that is not in the mask"""
    for d in range(1, 12):
        for s in (side, -side):
            xx = x + s * d
            if 0 <= xx < base.shape[1] and not m[y, xx]:
                return tuple(base[y, xx])
    return tuple(base[y, x])


def shift(base, m, dx, dy, rows=None, fill=None):
    """the masked cells (optionally only `rows`) moved by dx, dy; a vacated cell takes `fill(x, y)` or the
    unmasked cell next to it on the far side (the background that the move uncovers)"""
    out = base.copy()
    sel = m.copy()
    if rows is not None:
        keep = np.zeros_like(sel)
        keep[rows[0]:rows[1] + 1] = True
        sel &= keep
    ys, xs = np.nonzero(sel)
    for y, x in zip(ys, xs):
        tx, ty = x - dx, y - dy                      # the cell that would have moved here
        inside = 0 <= tx < base.shape[1] and 0 <= ty < base.shape[0]
        if not (inside and m[ty, tx]):               # what was behind: the background cell it came from
            out[y, x] = fill(x, y) if fill else base[ty, tx] if inside else nearest_out(base, m, x, y, 1)
    for y, x in zip(ys, xs):
        if 0 <= y + dy < base.shape[0] and 0 <= x + dx < base.shape[1]:
            out[y + dy, x + dx] = base[y, x]
    return out


def lamp(base, xr):
    """the pendant lamp in columns xr, rows 0-33: unlike its column's wallpaper (rows 34-38)"""
    xs = range(xr[0], xr[1] + 1)
    bg = col_bg(base, xs, (34, 38))
    m = np.zeros(base.shape[:2], bool)
    for x in xs:
        for y in range(34):
            m[y, x] = np.abs(base[y, x].astype(int) - bg[x]).sum() > 30
    m = keep_component(m)
    rows = [y for y in range(34) if m[y].sum() >= 4]
    pivot = rows[0] - 3
    ys, xs_ = np.nonzero(m)
    rect = (xs_.min() - 2, 0, xs_.max() + 2, ys.max() + 1)
    fill = lambda x, y: bg.get(x, tuple(base[y, x]))
    frames = [base, shift(base, m, 1, 0, (pivot, 33), fill), shift(base, m, -1, 0, (pivot, 33), fill)]
    return rect, frames, {"mode": "pingpong", "seq": [0, 1, 0, 2], "ms": [900, 1300]}


def green_mask(base, rect):
    import cv2
    x0, y0, x1, y1 = rect
    hsv = cv2.cvtColor(base, cv2.COLOR_RGB2HSV).astype(int)
    g = (hsv[..., 0] > 28) & (hsv[..., 0] < 95) & (hsv[..., 1] > 45)
    m = np.zeros(base.shape[:2], bool)
    m[y0:y1 + 1, x0:x1 + 1] = g[y0:y1 + 1, x0:x1 + 1]
    return m


def sway(base, rect):
    x0, y0, x1, y1 = rect
    m = green_mask(base, rect)
    top = (y0 + y1) // 2                              # the upper half leans, the stems stay
    frames = [base, shift(base, m, 1, 0, (y0, top)), shift(base, m, -1, 0, (y0, top))]
    return (x0 - 1, y0, x1 + 1, y1), frames, {"mode": "pingpong", "seq": [0, 1, 0, 2], "ms": [1100, 1700]}


def pet_mask(base, rect):
    import cv2
    x0, y0, x1, y1 = rect
    S = 6
    big = cv2.resize(base, (base.shape[1] * S, base.shape[0] * S), interpolation=cv2.INTER_NEAREST)
    mk = np.full(big.shape[:2], cv2.GC_BGD, np.uint8)
    mk[y0 * S:(y1 + 1) * S, x0 * S:(x1 + 1) * S] = cv2.GC_PR_FGD
    hsv = cv2.cvtColor(base, cv2.COLOR_RGB2HSV).astype(int)
    green = (hsv[..., 0] > 30) & (hsv[..., 0] < 75) & (hsv[..., 1] > 30)
    mk[cv2.resize(green.astype(np.uint8), big.shape[1::-1], interpolation=cv2.INTER_NEAREST).astype(bool)] = cv2.GC_BGD
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    mk[(cy - 2) * S:(cy + 2) * S, (cx - 3) * S:(cx + 3) * S] = cv2.GC_FGD
    cv2.grabCut(cv2.cvtColor(big, cv2.COLOR_RGB2BGR), mk, None, np.zeros((1, 65)), np.zeros((1, 65)), 5, cv2.GC_INIT_WITH_MASK)
    fg = ((mk == cv2.GC_FGD) | (mk == cv2.GC_PR_FGD)).astype(np.uint8)
    return keep_component(cv2.resize(fg, base.shape[1::-1], interpolation=cv2.INTER_AREA) > 0, (cx, cy))


def breathe(base, rect):
    m = pet_mask(base, rect)
    ys = np.nonzero(m.any(1))[0]
    top, mid = ys.min(), (ys.min() + ys.max()) // 2
    up = shift(base, m, 0, -1, (top, mid))            # rising: the row under the upper half stays
    x0, y0, x1, y1 = rect
    return (x0, y0 - 1, x1, y1), [base, up], {"mode": "pingpong", "seq": [0, 1], "ms": [1300, 1600]}


def perk(base, rect, head):
    """head = (x0, y0, x1, y1) inside rect: those pet cells lift a row"""
    m = pet_mask(base, rect)
    hm = np.zeros_like(m)
    hx0, hy0, hx1, hy1 = head
    hm[hy0:hy1 + 1, hx0:hx1 + 1] = m[hy0:hy1 + 1, hx0:hx1 + 1]
    x0, y0, x1, y1 = rect
    return (x0, y0 - 1, x1, y1), [base, shift(base, hm, 0, -1)], {"mode": "once", "on": ["send", "reply"],
                                                                     "seq": [1, 0], "ms": [900, 0]}


def wag(base, rect, tail):
    m = pet_mask(base, rect)
    tm = np.zeros_like(m)
    tx0, ty0, tx1, ty1 = tail
    tm[ty0:ty1 + 1, tx0:tx1 + 1] = m[ty0:ty1 + 1, tx0:tx1 + 1]
    return (tx0 - 2, ty0, tx1 + 2, ty1), [base, shift(base, tm, 1, 0), shift(base, tm, -1, 0)], \
        {"mode": "once", "on": ["send", "reply"], "seq": [1, 2, 1, 2, 1, 2, 0], "ms": [130, 0]}


def flame(base, rect):
    x0, y0, x1, y1 = rect
    a = base.astype(int)
    m = np.zeros(base.shape[:2], bool)
    m[y0:y1 + 1, x0:x1 + 1] = (a[y0:y1 + 1, x0:x1 + 1, 0] > 190) & (a[y0:y1 + 1, x0:x1 + 1, 1] > 120)
    ys, xs = np.nonzero(m)
    top = ys.min()
    tips = [x for y, x in zip(ys, xs) if y == top]
    low = base.copy()
    for x in tips:
        low[top, x] = nearest_out(base, m, x, top, 1)
    high = base.copy()
    for x in tips:
        if top - 1 >= 0:
            high[top - 1, x] = base[top, x]
    bright = base.copy()
    for y, x in zip(ys, xs):
        bright[y, x] = np.clip(base[y, x].astype(int) * 1.12 + 10, 0, 255)
    return (x0, y0 - 1, x1, y1), [base, low, high, bright], {"mode": "flicker", "ms": [110, 260]}


KINDS = {"lamp": lamp, "sway": sway, "breathe": breathe, "perk": perk, "wag": wag, "flame": flame}


def build(base, items):
    """[(rect, frames, meta)] for a persona's ambient list (each item: kind plus its arguments)"""
    out = []
    for it in items:
        kind, args = it[0], it[1:]
        (x0, y0, x1, y1), frames, info = KINDS[kind](base, *args)
        H, W = base.shape[:2]
        rect = (max(0, int(x0)), max(0, int(y0)), min(W - 1, int(x1)), min(H - 1, int(y1)))
        out.append((rect, frames, {"kind": kind, **info}))
    return out
