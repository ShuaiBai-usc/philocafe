"""App icons for the PWA (Add to Home Screen): the prototype's coffee cup, scaled by whole
numbers onto the page colour so the pixels stay crisp.

    .venv/bin/python ui/web/tools/make_icons.py
"""

from pathlib import Path

from PIL import Image

WEB = Path(__file__).resolve().parent.parent
PAPER = (255, 250, 224, 255)     # --paper
SIZES = (180, 192, 512)
ART_SHARE = 0.72                 # the cup's width as a share of the icon


def native(im: Image.Image, cell: int = 12) -> Image.Image:
    w, h = im.size
    return im.resize((round(w / cell), round(h / cell)), Image.NEAREST)


def main() -> None:
    art = native(Image.open(WEB / "assets" / "icon_coffee_big.png").convert("RGBA"))
    out = WEB / "icons"
    out.mkdir(exist_ok=True)
    for size in SIZES:
        scale = max(1, int(size * ART_SHARE // art.width))
        cup = art.resize((art.width * scale, art.height * scale), Image.NEAREST)
        icon = Image.new("RGBA", (size, size), PAPER)
        icon.alpha_composite(cup, ((size - cup.width) // 2, (size - cup.height) // 2))
        icon.convert("RGB").save(out / f"icon-{size}.png")
        print(f"icon-{size}.png (cup x{scale})")


if __name__ == "__main__":
    main()
