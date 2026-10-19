"""TROPICAL.MIF: a tile set for playing ordinary cities with the Waikiki look.

    python tools/play_tileset.py "C:/Users/webre/Documents/SC2K"   # build/TROPICAL.MIF and build/TROPSTK.MIF

Two versions of the same set:
  TROPICAL.MIF  drawn in the Perler bead palette; needs patch_game.py --play.
  TROPSTK.MIF   drawn in the game's own palette, so it works in an unpatched game (with
                sc2kfix). Colours are the nearest palette entries, not beads.

WAIKIKI.MIF borrows many sprite slots for the diorama (industry shows hotels, rubble shows
beach towels, radiation shows reef water), so it isn't fit for a game that grows. This
set keeps every slot meaning what the game means by it, and only changes the look:
  * terrain, water, trees and small parks: the diorama's tropical art (terrain_art.py),
    with tree slot 7 a tree again rather than hillside homes;
  * flat roads: lined with monkeypods, palms and flowering shrubs;
  * light residential (0x70-0x77): the Hawaiian homes from houses.py;
  * every other building is the stock picture, recoloured (recolour()):
      - "tropical" (homes, shops, offices, civic): green lots and trees in the diorama's
        greens, warm walls (brick, brown, tan) lifted toward pastel (bare ground is left:
        its palette slots are shared with brown walls);
      - "green" (industry, construction sites, abandoned buildings, the fire station):
        lots and trees only, so factories still look industrial, abandoned buildings still
        read as such and the fire station stays red;
      - water in pools, ponds and the marina basin: the sea's azure;
  * the ramps, tunnels and empty zoned land, whose bare ground is tan: grassed over;
  * the rest (rubble, radiation, power lines, rails, bridges, highways, vehicles,
    disasters, the underground) stays stock (in TROPICAL.MIF re-pointed to bead slots).
The coloured zone line round each lot is never touched. Neither version works in diorama
mode: its terrain table sends shallow water to slot 5, which is radiation here.
"""
import colorsys
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import houses
import make_mif
import perler as P
import terrain_art as TA

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
OFFSETS = (0, 500, 1000)
TILE_PX = {0: 8, 500: 16, 1000: 32}

HOMES = range(0x70, 0x78)
INDUSTRY = [*range(0x84, 0x88), *range(0x9E, 0xA6), *range(0xBC, 0xC2)]
BUILDING_SITES = [*range(0xA6, 0xAA), 0xC2, 0xC3]          # construction
ABANDONED = [*range(0xAA, 0xAE), 0xC4, 0xC5]
FIRE_STATION = [0xD3]                                       # stays fire-engine red
GREEN_ONLY = set(INDUSTRY + BUILDING_SITES + ABANDONED + FIRE_STATION)
TROPICAL = [i for i in range(0x78, 0x100) if i not in GREEN_ONLY and i not in (0xC6, 0xC7, 0xC8)]
GROUND_ONLY = [*range(0x3F, 0x43), *range(0x5D, 0x61), *range(0x123, 0x12C)]   # tunnels, ramps, zoned land
PASTEL = 0.35         # how far warm walls move toward white
GRASS_FAMILY = ["Kiwi Lime", "Bright Green", "Dark Green", "Shamrock", "Evergreen", "Forest", "Sour Apple"]


def ground_indices(stock):
    """Palette slots of the stock flat terrain (bare tan ground), at every zoom."""
    out = set()
    for off in OFFSETS:
        px = stock[off + 256]
        out |= set(np.unique(px[px >= 0]).tolist())
    return out


def zone_line(px, n):
    """Pixels on and next to the footprint diamond's outline (the coloured lot line)."""
    h, w = px.shape
    hw, hh = w / 2, w / 4
    ys, xs = np.mgrid[0:h, 0:w] + 0.5
    cy = h - hh                                   # diamond centre, bottom-aligned
    d = np.abs(xs - hw) / hw + np.abs(ys - cy) / hh
    return (np.abs(d - 1) * hh < 1.6) & (ys > h - 2 * hh - 1)


class Recolour:
    def __init__(self, orig, pal, usable, ground):
        self.orig, self.pal, self.usable, self.ground = orig, pal, usable, ground
        self.grass = P.slots_of(pal, GRASS_FAMILY, usable)
        self.lab = make_mif.to_lab(pal[usable])
        self.glab = make_mif.to_lab(pal[self.grass])
        self.ref = TA.lum(orig[TA.SAND_REF])
        self.cache = {}

    def nearest(self, rgb, cands, labs):
        d = P.ciede2000(make_mif.to_lab(np.asarray(rgb, dtype=np.float64))[None], labs)
        return int(cands[int(np.argmin(d))])

    def slot(self, idx, mode):
        """New palette slot for stock slot `idx` under `mode` (tropical / green / ground)."""
        key = (idx, mode)
        if key in self.cache:
            return self.cache[key]
        c = self.orig[idx]
        out = None
        if idx == 0 or idx >= 171:
            out = idx                               # outline black; animated slots keep cycling
        elif idx in TA.STOCK_WATER:                 # pools, ponds, marina basins: the sea's azure
            out = self.nearest(TA.AZURE, self.usable, self.lab)
        elif mode == "ground" and idx in self.ground:   # bare ground: lawn, shaded like the stock dirt
            k = min(TA.lum(c) / self.ref, 1.15)
            out = self.nearest(np.clip(TA.GRASS * k, 0, 255), self.grass, self.glab)
        elif mode != "ground":
            h, l, s = colorsys.rgb_to_hls(*(c / 255))
            if 0.20 <= h <= 0.45 and s > 0.25 and l > 0.12:          # lawn, hedges, trees
                out = self.nearest(c, self.grass, self.glab)
            elif mode == "tropical" and (h < 0.14 or h > 0.92) and s > 0.18 and 0.12 < l < 0.75:
                out = self.nearest(c + (255 - c) * PASTEL, self.usable, self.lab)     # warm walls
        if out is None:
            out = self.nearest(c, self.usable, self.lab)
        self.cache[key] = out
        return out

    def __call__(self, px, mode, n=1):
        out = np.full(px.shape, -1, dtype=int)
        keep = zone_line(px, n) if mode != "ground" else np.zeros(px.shape, bool)
        for idx in np.unique(px[px >= 0]):
            m = px == idx
            new = self.slot(int(idx), mode)
            plain = self.nearest(self.orig[idx], self.usable, self.lab) if 0 < idx < 171 else int(idx)
            out[m & ~keep] = new
            out[m & keep] = plain
        return out


def footprint(stock, obj):
    """1, 2 or 3 tiles, from the large sprite's width."""
    return max(1, stock[1000 + obj].shape[1] // 32)


def build(game_dir, stock_palette=False):
    """stock_palette=False: TROPICAL.MIF in the bead palette; True: TROPSTK.MIF in the game's own."""
    game = Path(game_dir)
    orig = P.original_palette(game)
    if stock_palette:
        out, pal, remap = BUILD / "TROPSTK.MIF", orig, np.arange(256)    # nothing to re-point
    else:
        out = BUILD / "TROPICAL.MIF"
        pal = make_mif.read_bmp_palette(game / "BITMAPS" / "PAL_MSTR.BMP")
        want, _, remap = P.game_palette(game)
        if not np.allclose(pal[16:246], want[16:246]):
            sys.exit("PAL_MSTR.BMP isn't the Perler palette yet: run tools/patch_game.py first")
    usable = make_mif.USABLE
    template = (game / "SCURKART" / "TILESET1.MIF").read_bytes()
    info, tmpl = make_mif.read_pieces(template)
    layout = [(sid, w) for tag, sid, w, _ in tmpl if tag == "SHAP"]
    stock = TA.stock_sprites(game)
    stock.update(TA.read_archive(game / "DATA" / "SPECIAL.DAT"))
    rc = Recolour(orig, pal, usable, ground_indices(stock))

    ours, kept = {}, set()
    # terrain, water, trees, lawns: the diorama's art, minus the slots it borrows
    art = TA.sprites(game, pal, usable, orig)
    for off in OFFSETS:
        for base in [*TA.TERRAIN, *TA.WATER, *TA.TREES, TA.LAWN_PALMS_ID]:
            if off + base in art:
                ours[off + base] = art[off + base]
        palms, broad = TA.TREE_MIX[TA.HILL_HOMES_ID]
        ours[off + TA.HILL_HOMES_ID] = TA.tree_pixels(TILE_PX[off], palms, broad, 7 * 31, pal, usable)
    # Hawaiian homes, rendered fresh from houses.py
    import json
    T = json.load(open(BUILD / "placements.json"))["T"]
    for obj in HOMES:
        for off, tp in TILE_PX.items():
            img = houses.house_scene(obj, T, tp).render()
            ours[off + obj] = make_mif.quantize_building(img, pal, usable)
    # every other building, recoloured
    for obj in range(0x78, 0x100):
        mode = "tropical" if obj in TROPICAL else "green" if obj in GREEN_ONLY else None
        if mode is None:
            continue
        n = footprint(stock, obj)
        for off in OFFSETS:
            if off + obj in stock:
                ours[off + obj] = rc(stock[off + obj], mode, n)
                kept.add(off + obj)
    for obj in GROUND_ONLY:
        for off in OFFSETS:
            if off + obj in stock:
                ours[off + obj] = rc(stock[off + obj], "ground")
                kept.add(off + obj)
    # everything else that touches a slot the Perler palette gave away: re-point it
    swapped = np.nonzero(remap != np.arange(256))[0]
    for sid, px in stock.items():
        if sid not in ours and np.isin(px, swapped).any():
            ours[sid] = np.where(px >= 0, remap[np.maximum(px, 0)], -1)
            kept.add(sid)
    # tree- and flower-lined streets
    for piece in TA.STREET_ARMS:
        for off, tp in TILE_PX.items():
            ours[off + piece] = TA.street_trees(ours.get(off + piece, stock[off + piece]), tp, piece, pal, usable)
            kept.add(off + piece)

    pieces = []
    for sid, width in layout:
        if sid in ours:
            pieces.append((b"SHAP", make_mif.shape_payload(sid, ours[sid])))
        else:
            pieces.append((b"SHAP", make_mif.struct.pack(">HHHI", sid, width, 1, len(make_mif.PLACEHOLDER))
                           + make_mif.PLACEHOLDER))
    slots = {sid for sid, _ in layout}
    for sid in sorted(set(ours) - slots):
        pieces.append((b"SHAP", make_mif.shape_payload(sid, ours[sid])))
    data = make_mif.to_bytes(info, pieces)
    make_mif.verify(data, layout, ours, kept)
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)} bytes, {len(ours)} sprites)")
    contact_sheets(stock, ours, orig, pal, BUILD / ("tropstk_review" if stock_palette else "tropical_review"))
    return ours


def contact_sheets(stock, ours, orig, pal, d, cols=8):
    """build/tropical_review/: each building, stock beside recoloured, large zoom."""
    from PIL import ImageDraw
    d.mkdir(exist_ok=True)

    def img(px, p):
        o = np.zeros(px.shape + (3,), np.uint8)
        o[:] = (200, 200, 210)
        m = px >= 0
        o[m] = p[px[m]].astype(np.uint8)
        return Image.fromarray(o)
    objs = [o for o in range(0x70, 0x100) if 1000 + o in ours]
    for start in range(0, len(objs), 24):
        cells = []
        for o in objs[start:start + 24]:
            a, b = img(stock[1000 + o], orig), img(ours[1000 + o], pal)
            c = Image.new("RGB", (a.width + b.width + 6, max(a.height, b.height) + 12), (200, 200, 210))
            c.paste(a, (0, c.height - 12 - a.height))
            c.paste(b, (a.width + 6, c.height - 12 - b.height))
            ImageDraw.Draw(c).text((1, c.height - 11), f"{o:#x}", fill=(0, 0, 0))
            cells.append(c)
        rows = [cells[k:k + cols] for k in range(0, len(cells), cols)]
        W = max(sum(c.width + 8 for c in r) for r in rows)
        H = sum(max(c.height for c in r) + 8 for r in rows)
        sheet = Image.new("RGB", (W, H), (200, 200, 210))
        y = 0
        for r in rows:
            x, rh = 0, max(c.height for c in r)
            for c in r:
                sheet.paste(c, (x, y + rh - c.height))
                x += c.width + 8
            y += rh + 8
        sheet.save(d / f"buildings_{objs[start]:02x}.png")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    build(sys.argv[1])
    build(sys.argv[1], stock_palette=True)
