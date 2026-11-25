"""Layers for the moving parts of a chat scene.

A moving thing (the philosopher, a pet, a plant) is cut out of the scene with a mask; the hole is filled
with OpenCV inpainting and snapped to the scene's palette, which gives the plate behind it. A pose or a
frame is the plate with the thing drawn back on top, some parts of it moved. Nothing behind the thing
moves with it, and where a moved part uncovers something, the plate shows.

    plate(base, mask)                          the scene with the masked cells painted out
    compose(base, back, mask, moves)           back + the masked cells of base, each move = (part, dx, dy);
                                               cells of mask in no moving part stay where they are
"""
import numpy as np


def palette_snap(img, base):
    pal = np.unique(base.reshape(-1, 3), axis=0).astype(int)
    flat = img.reshape(-1, 3).astype(int)
    idx = ((flat[:, None, :] - pal[None]) ** 2).sum(2).argmin(1)
    return pal[idx].reshape(img.shape).astype(np.uint8)


def plate(base, mask, grow=1):
    import cv2
    m = mask.astype(np.uint8)
    if grow:
        m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=grow)
    painted = cv2.inpaint(cv2.cvtColor(base, cv2.COLOR_RGB2BGR), m * 255, 4, cv2.INPAINT_TELEA)
    painted = cv2.cvtColor(painted, cv2.COLOR_BGR2RGB)
    out = base.copy()                              # inpainted with a margin, written back only under the mask
    out[mask] = palette_snap(painted[mask][None], base)[0]
    return out


def compose(base, back, mask, moves=()):
    out = back.copy()
    moving = np.zeros_like(mask)
    for part, _, _ in moves:
        moving |= part
    still = mask & ~moving
    out[still] = base[still]
    H, W = mask.shape
    for part, dx, dy in moves:
        ys, xs = np.nonzero(part)
        ty, tx = ys + dy, xs + dx
        ok = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
        out[ty[ok], tx[ok]] = base[ys[ok], xs[ok]]
    return out


def rows(mask, top, bottom):
    """the part of mask in rows top..bottom"""
    keep = np.zeros_like(mask)
    keep[max(0, top):bottom + 1] = True
    return mask & keep


def fill_holes(mask):
    import cv2
    m = mask.astype(np.uint8)
    h, w = m.shape
    flood = np.pad(m, 1).copy()
    cv2.floodFill(flood, None, (0, 0), 1)
    holes = flood[1:-1, 1:-1] == 0
    return mask | holes


def keep_component(mask, seed=None):
    import cv2
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    if seed is not None and lab[seed[1], seed[0]]:
        k = lab[seed[1], seed[0]]
    else:
        k = 1 + int(np.argmax([(lab == i).sum() for i in range(1, n)]))
    return lab == k
