"""Trial scenes with no expressions yet: sources/<id>_restyled_gen.jpg (the persona's chat scene with the
face redrawn in the style of the first Schopenhauer scene, ElevenLabs) on the usual 143 x 256 grid.

faces.png repeats the scene's own face in every mood and frame, so the page shows a still face (no
blinks, no talking) until a face sheet is made for the new art.

    .venv/bin/python ui/web/tools/art/static_scene.py socrates montaigne seneca epictetus
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pixelate import find_grid, quantize, sample  # noqa: E402

ROOT = HERE.parents[3]
GRID = (143, 256)


def build(pid):
    out = ROOT / f"ui/web/assets/personas/{pid}/full"
    meta = json.loads((out / "faces.json").read_text())
    src = np.asarray(Image.open(HERE / f"sources/{pid}_restyled_gen.jpg").convert("RGB")).astype(float)
    nw, nh, ox, oy = find_grid(src, [GRID[0]], [GRID[1]])
    base = np.asarray(quantize(sample(src, nw, nh, ox, oy), 48))
    P = meta["patch"]
    face = base[P["y"]:P["y"] + P["h"], P["x"]:P["x"] + P["w"]]
    sheet = np.tile(face, (len(meta["moods"]), len(meta["frames"]), 1))
    Image.fromarray(base).save(out / "scene.png", optimize=True)
    Image.fromarray(sheet).save(out / "faces.png", optimize=True)
    meta.update(source=f"{pid}_restyled_gen.jpg", static=True)
    (out / "faces.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(pid, f"grid {nw}x{nh} offset ({ox}, {oy})")


if __name__ == "__main__":
    for pid in sys.argv[1:]:
        build(pid)
