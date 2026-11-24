"""Turn a generated "pixel-art-looking" picture into true pixel art: one colour per cell on
the picture's own grid, and a small shared palette.

    .venv/bin/python ui/web/tools/art/pixelate.py SOURCE.png OUT.png [--colors 48]

Image models draw pixel art without a real grid: each "pixel" is a blurred block of about
5 x 5 screen pixels, and the colours drift. This finds the grid (the cell count and offset
that make each cell most uniform), takes the median of each cell's centre, and reduces the
colours with k-means in Lab space, so similar hues (the grey beard and the sage chair) stay
apart. Used for the full-screen chat scenes (design doc 7.5): the Socrates scene came from
an ElevenLabs (Nano Banana 2) generation, 768 x 1376, on a 143 x 256 grid.
"""

import argparse

import numpy as np
from PIL import Image, ImageCms


def find_grid(im, widths, heights, steps=np.arange(-2.5, 2.75, 0.25)):
    H, W, _ = im.shape
    flat = im.reshape(-1, 3)
    def cost(nw, nh, ox, oy):
        xs = np.clip(((np.arange(W) - ox) / (W / nw)).astype(int), 0, nw - 1)
        ys = np.clip(((np.arange(H) - oy) / (H / nh)).astype(int), 0, nh - 1)
        idx = (ys[:, None] * nw + xs[None, :]).reshape(-1)
        n = np.bincount(idx, minlength=nw * nh)
        s = np.stack([np.bincount(idx, weights=flat[:, c], minlength=nw * nh) for c in range(3)], 1)
        s2 = np.stack([np.bincount(idx, weights=flat[:, c] ** 2, minlength=nw * nh) for c in range(3)], 1)
        return (s2 - s ** 2 / np.maximum(n, 1)[:, None]).sum()
    return min((cost(nw, nh, ox, oy), nw, nh, ox, oy) for nw in widths for nh in heights for ox in steps for oy in steps)[1:]


def sample(im, nw, nh, ox, oy):
    H, W, _ = im.shape
    cw, ch = W / nw, H / nh
    out = np.zeros((nh, nw, 3))
    for j in range(nh):
        for i in range(nw):
            x0, y0 = ox + i * cw, oy + j * ch
            xa = int(np.clip(round(x0 + cw * .25), 0, W - 1)); xb = int(np.clip(round(x0 + cw * .75), xa + 1, W))
            ya = int(np.clip(round(y0 + ch * .25), 0, H - 1)); yb = int(np.clip(round(y0 + ch * .75), ya + 1, H))
            out[j, i] = np.median(im[ya:yb, xa:xb].reshape(-1, 3), axis=0)
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def quantize(img, k=48, seed=1, iters=40):
    to_lab = ImageCms.buildTransformFromOpenProfiles(ImageCms.createProfile("sRGB"), ImageCms.createProfile("LAB"), "RGB", "LAB")
    X = np.asarray(ImageCms.applyTransform(img, to_lab)).reshape(-1, 3).astype(float)
    X[:, 0] *= .8                                        # a little less weight on lightness than on hue
    rgb = np.asarray(img).reshape(-1, 3).astype(float)
    rng = np.random.default_rng(seed)
    c = [X[rng.integers(len(X))]]
    for _ in range(1, k):                                # k-means++ start
        d = np.min(((X[:, None, :] - np.array(c)[None]) ** 2).sum(2), 1)
        c.append(X[rng.choice(len(X), p=d / d.sum())])
    c = np.array(c)
    for _ in range(iters):
        lab = ((X[:, None, :] - c[None]) ** 2).sum(2).argmin(1)
        for i in range(k):
            if (lab == i).any(): c[i] = X[lab == i].mean(0)
    pal = np.array([np.median(rgb[lab == i], 0) if (lab == i).any() else (0, 0, 0) for i in range(k)]).round().astype(np.uint8)
    return Image.fromarray(pal[lab].reshape(img.height, img.width, 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source"); ap.add_argument("out")
    ap.add_argument("--colors", type=int, default=48)
    ap.add_argument("--width", type=int, nargs="+", default=list(range(140, 147)))
    ap.add_argument("--height", type=int, nargs="+", default=list(range(252, 260)))
    a = ap.parse_args()
    im = np.asarray(Image.open(a.source).convert("RGB")).astype(float)
    nw, nh, ox, oy = find_grid(im, a.width, a.height)
    print(f"grid {nw} x {nh}, offset ({ox}, {oy})")
    quantize(sample(im, nw, nh, ox, oy), a.colors).save(a.out)


if __name__ == "__main__":
    main()
