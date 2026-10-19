"""Top-down debug map of build/city_layers.npz (x right, y down)."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
UNIQUE = set(range(0xAE, 0xC2)) | set(range(0x8C, 0xA0)) | {0x7C, 0x7F, 0x82, 0x83, 0x84, 0x85}
GEN2 = set(range(0xA0, 0xA6))
GEN1 = {0x78, 0x79, 0x7A, 0x7B, 0x86, 0x87}


def main(crop=None):
    L = np.load(ROOT / "build/city_layers.npz")
    b, w, lv = L["xbld"], L["water"], L["level"]
    N = 128
    img = np.zeros((N, N, 3), np.uint8)
    for x in range(N):
        for y in range(N):
            v = b[x, y]
            if w[x, y]:
                c = (40, 90, 170)
            elif 0x1D <= v <= 0x2B:
                c = (50, 50, 50)
            elif v in UNIQUE:
                c = (230, 60, 60)
            elif v in GEN2:
                c = (240, 200, 80)
            elif v in GEN1:
                c = (240, 240, 180)
            elif 6 <= v <= 0x0D:
                c = (50, 140, 50)
            elif v:
                c = (170, 150, 130)
            else:
                g = min(250, 110 + int(lv[x, y]) * 8)
                c = (g, int(g * .85), int(g * .6))
            img[y, x] = c
    im = Image.fromarray(img)
    if crop:
        x0, y0, x1, y1 = crop
        im = im.crop((x0, y0, x1, y1)).resize(((x1 - x0) * 12, (y1 - y0) * 12), Image.NEAREST)
        im.save(ROOT / "build/map_zoom.png")
    else:
        im.resize((640, 640), Image.NEAREST).save(ROOT / "build/map_topdown.png")


if __name__ == "__main__":
    main(tuple(map(int, sys.argv[1:5])) if len(sys.argv) > 4 else None)
