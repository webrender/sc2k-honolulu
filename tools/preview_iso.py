"""Isometric preview of the generated city, approximating SimCity 2000's view.

Uses the custom sprites from build/sprites and simple stand-ins for stock
buildings, terrain, roads and trees. Not pixel-exact to the game (no game art),
but shows the skyline layout. Run after tileset.py:
    python tools/preview_iso.py            -> build/preview_iso.png, build/preview_skyline.png
"""
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import materials as M
import terrain as TR
from render3d import Scene

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
N = 128
HW, HH, STEP = 16, 8, 12
TOP = 40 * STEP + 40

# corner raise mask (1 top, 2 right, 4 bottom, 8 left) for each XTER slope shape
SHAPE_MASK = {}
for mask, shp in enumerate(TR.TERRAIN_SHAPES):
    if shp != TR.RAISE_BASIN:
        SHAPE_MASK.setdefault(shp, mask)
SHAPE_MASK[0x0D] = 15


def screen(x, y, z):
    return (N * HW + (x - y) * HW, TOP + (x + y) * HH - z * STEP)


def shade(col, k):
    return tuple(int(max(0, min(255, c * k))) for c in col)


def stock_sprites(T):
    """Simple stand-ins for stock SC2K buildings."""
    out = {}
    rng = random.Random(3)
    for xbld in range(0x70, 0x78):
        sc = Scene(1, T, 32)
        sc.add_quad([(0, 0, 0), (T, 0, 0), (T, T, 0), (0, T, 0)], (M.ground("5e9a48"), None, 0), "roof", -1e4)
        for (u, v) in ((.15, .15), (.55, .55)):
            w = T * .32
            sc.add_prism([(u * T, v * T), (u * T + w, v * T), (u * T + w, v * T + w), (u * T, v * T + w)], 0,
                         rng.uniform(4, 7), M.solid(rng.choice(["e8e0d0", "d8ccb0", "f0ece0"])), M.roof(rng.choice(["8a4a3a", "6a6a70", "5a6a5a"])))
        out[xbld] = sc.render()
    for xbld in (0x7D, 0x7E, 0x80, 0x81):
        sc = Scene(1, T, 32)
        sc.add_quad([(0, 0, 0), (T, 0, 0), (T, T, 0), (0, T, 0)], (M.ground("paving"), None, 0), "roof", -1e4)
        sc.add_prism([(T * .15, T * .15), (T * .85, T * .15), (T * .85, T * .85), (T * .15, T * .85)], 0,
                     rng.uniform(8, 14), M.tower(wall=rng.choice(["e4dccc", "d0c8b8"]), floor_h=4, win=.4, lobby_h=0), M.roof())
        out[xbld] = sc.render()
    return out


def main(crop=None):
    L = np.load(BUILD / "city_layers.npz")
    level, shape, xbld, water = L["level"], L["shape"], L["xbld"], L["water"]
    data = json.load(open(BUILD / "placements.json"))
    T = data["T"]
    sprites = {}
    for f in (BUILD / "sprites").glob("*_L.png"):
        sprites[int(f.name[:2], 16)] = Image.open(f).convert("RGBA")
    sprites.update({k: v for k, v in stock_sprites(T).items() if k not in sprites})

    # building anchors: draw each building once, at its bottom (max x+y) tile
    anchor = {}
    for p in data["placements"]:
        n = p["n"]
        anchor[(p["x"] + n - 1, p["y"] + n - 1)] = p
    covered = np.zeros((N, N), dtype=bool)
    for p in data["placements"]:
        covered[p["x"]:p["x"] + p["n"], p["y"]:p["y"] + p["n"]] = True

    W, H = N * HW * 2 + 40, TOP + N * HH * 2 + 40
    img = Image.new("RGBA", (W, H), (150, 190, 225, 255))
    draw = ImageDraw.Draw(img)
    # sky gradient
    for yy in range(H):
        t = yy / H
        draw.line([(0, yy), (W, yy)], fill=(int(120 + 80 * t), int(170 + 60 * t), int(230 + 15 * t), 255))
    rng = random.Random(7)

    for s in range(2 * N - 1):
        for x in range(max(0, s - N + 1), min(N, s + 1)):
            y = s - x
            lv = int(level[x, y])
            if water[x, y]:
                z = TR.SEA_LEVEL
                pts = [screen(x, y, z), screen(x + 1, y, z), screen(x + 1, y + 1, z), screen(x, y + 1, z)]
                deep = lv < TR.SEA_LEVEL - 1
                draw.polygon(pts, fill=(38, 92, 168) if deep else (52, 132, 190))
                continue
            m = SHAPE_MASK.get(int(shape[x, y]), 0)
            zc = [lv + (1 if m & 1 else 0), lv + (1 if m & 2 else 0), lv + (1 if m & 4 else 0), lv + (1 if m & 8 else 0)]
            pts = [screen(x, y, zc[0]), screen(x + 1, y, zc[1]), screen(x + 1, y + 1, zc[2]), screen(x, y + 1, zc[3])]
            b = int(xbld[x, y])
            # slope shading: light from the left (+y side)
            k = 1.0 + 0.18 * ((zc[0] + zc[1]) - (zc[2] + zc[3])) * 0.5 - 0.14 * ((zc[3] + zc[0]) - (zc[1] + zc[2])) * 0.5
            base = (128, 160, 80) if lv <= TR.SEA_LEVEL + 1 else (150, 150, 92)
            if 0x1D <= b <= 0x2B:
                base = (96, 96, 100)
            draw.polygon(pts, fill=shade(base, k))
            if 0x1D <= b <= 0x2B:
                cx, cy = (pts[0][0] + pts[2][0]) / 2, (pts[0][1] + pts[2][1]) / 2
                draw.point((cx, cy), fill=(230, 220, 120))
            if 1 <= b <= 4 and b in sprites:
                spr = sprites[b]
                bx, by = screen(x + 1, y + 1, lv)
                img.alpha_composite(spr, (int(bx - spr.width / 2), int(by - spr.height + 1)))
            if 6 <= b <= 0x0C:
                ntrees = {6: 1, 7: 2, 8: 3, 9: 3, 10: 4, 11: 5, 12: 6}[b]
                for _ in range(ntrees):
                    cx = (pts[0][0] + pts[2][0]) / 2 + rng.uniform(-8, 8)
                    cy = (pts[0][1] + pts[2][1]) / 2 + rng.uniform(-3, 4)
                    r = rng.uniform(2.5, 4)
                    draw.line([(cx, cy), (cx, cy - 4)], fill=(90, 70, 50))
                    draw.ellipse([cx - r, cy - 4 - r * 1.3, cx + r, cy - 4 + r * .7], fill=(52, 112, 48), outline=(32, 80, 30))
            if (x, y) in anchor:
                p = anchor[(x, y)]
                spr = sprites.get(p["xbld"])
                if spr is not None:
                    n = p["n"]
                    bx, by = screen(p["x"] + n, p["y"] + n, lv)  # bottom corner of footprint
                    img.alpha_composite(spr, (int(bx - spr.width / 2), int(by - spr.height + 1)))
    img = img.convert("RGB")
    img.save(BUILD / "preview_iso.png")
    # skyline crop: Waikiki (left corner) through Diamond Head (bottom corner)
    lx, ly = screen(0, 80, 0)
    bx, by = screen(118, 128, 0)
    sky = img.crop((int(lx) - 100, int(ly) - 700, int(bx) + 350, int(by) + 40))
    sky.save(BUILD / "preview_skyline.png")
    print("wrote build/preview_iso.png", img.size, "and build/preview_skyline.png", sky.size)


if __name__ == "__main__":
    main()
