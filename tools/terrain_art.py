"""Tropical replacements for the game's own terrain, water and tree sprites.

    python tools/terrain_art.py "C:/Users/webre/Documents/SC2K"   # writes build/terrain_art.png

sc2kfix lets a .MIF replace any sprite ID, not only buildings, so make_mif.py
packs these into WAIKIKI.MIF alongside the Waikiki towers:
  256-269  terrain                           flat -> lush grass, slopes -> drier olive grass,
                                             cliff faces -> brown volcanic rock
  270      open water (all flat water)       stock blue   -> deep azure
  5        shallow flat water                turquoise (patch_game.py points XTER 0x20/0x30 here;
                                             the slot normally holds radioactivity)
  271-290  shoreline and stream tiles        turquoise, foam at the waterline, sand beach edge
  6-12     trees (7 densities)               palms, then broadleaf canopy (monkeypod/banyan) as density rises
  13       small park                        park lawn with a palm and a shade tree
  219      statue                            striped golf fairway
  (1-4, the beach props from tileset.py, get a sand floor in make_mif.py via sand_floor())
Water keeps the stock shimmer pixels. They sit in colour-cycling palette entries,
and patch_game.py recolours those: 208-211 (a 4-step cycle) turquoise for
shallow water, 200-207 (an 8-step cycle) azure for deep water.
Terrain and water are recoloured from the stock sprites (read from DATA/LARGE.DAT
and DATA/SMALLMED.DAT), so every slope, cliff and shoreline keeps the game's
exact shape. Each sprite ID exists at three zooms: small = id, medium = 500 + id,
large = 1000 + id.
"""
import math
import random
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import perler as P

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"

TERRAIN = range(256, 270)
WATER = range(270, 291)
TREES = range(6, 13)
ZOOM_OFFSET = (0, 500, 1000)
ZOOM_TILE_PX = {0: 8, 500: 16, 1000: 32}

# every colour is a Perler bead (tools/perler.py); shading picks among each family's beads
SAND = P.rgb("Champagne")                              # lit flat sand
SAND_REF = 120                                         # stock index of lit flat ground
ROCK = np.array([1.0, 0.90, 0.74], dtype=np.float32)   # tint for the grey cliff stone
TURQUOISE = P.rgb("Lagoon")                            # shallow reef water
AZURE = P.rgb("Light Blue")                            # deep water
GRASS = P.rgb("Bright Green")                          # flat ground and park lawns
OLIVE = P.rgb("Fern")                                  # sloped ground: a yellower green than the flats
ROCK_BROWN = P.rgb("Gingerbread")
FAIRWAY = P.rgb("Kiwi Lime")
ROCK_REF = 163                                        # stock mid-grey cliff stone
SHALLOW_ID = 5
MARINA_ID = 0xF8
# With the harbour off the map, the marina's sprite slot is free; patch_game.py points
# surface water (the Ala Wai Canal, streams and ponds: XTER 0x30-0x45) at it, drawn as
# a full tile of dark teal water like the walled canal (no sandy banks).
CANAL_ID = MARINA_ID
# Mid-depth water: the seabed steps down a level per tile in a ring outside the reef
# (build_city.reef_depth), so those tiles are "deep water on a slope" (XTER 0x11-0x1D);
# patch_game.py points that type at this slot (the Forest Arcology's, never built here),
# drawn as teal-blue water between the turquoise reef and the deep azure
MID_ID = 0xFD
MID = P.rgb("Peacock")
BORROWED_WATER = (CANAL_ID, MID_ID)       # slots whose sprite isn't the size winSCURK expects
CANAL = P.rgb("Parrot Green")
LAWN_PALMS_ID = 13
HILL_HOMES_ID = 7          # placement.HILL_HOMES
LAWN_ID = 219
SHALLOW_GLINT = list(range(208, 212))   # sc2kfix "short blue shimmer" cycle
DEEP_GLINT = list(range(200, 208))      # sc2kfix "mid blue shimmer" cycle
# colours patch_game.py writes into PAL_MSTR.BMP for those cycles (one ripple each)
def _beads(*names):
    return [tuple(int(v) for v in P.rgb(n)) for n in names]


CYCLE_COLOURS = {
    **dict(zip(SHALLOW_GLINT, _beads("Lagoon", "Caribbean Sea", "Capri Blue", "Robin's Egg"))),
    **dict(zip(DEEP_GLINT, _beads("Light Blue", "Light Blue", "Pastel Blue", "Sky",
                                  "Pastel Blue", "Light Blue", "Turquoise", "Light Blue"))),
}
NAVY = P.rgb("Dark Blue")                              # water seen side-on at the map edge
WATER_COLUMN = 284                                     # waterfall / map-edge water column
FOAM = P.rgb("Robin's Egg")
# the beads each kind of ground or water may use
FAMILIES = {
    "grass": ["Kiwi Lime", "Bright Green", "Dark Green", "Shamrock", "Evergreen", "Forest", "Sour Apple"],
    # hillsides: green like the flats, but yellower in the sun and olive in shade, so ridges read
    "dry": ["Fern", "Sour Apple", "Kiwi Lime", "Olive", "Evergreen", "Dark Green", "Forest", "Bright Green"],
    "sand": ["Sand", "Wheat", "Champagne", "Fawn", "Tan", "Oyster", "Toasted Marshmallow", "Khaki", "Beige"],
    "rock": ["Gingerbread", "Brown", "Cocoa", "Beige", "Toffee", "Light Brown", "Iron", "Tan", "Stone"],
    "water": ["Lagoon", "Caribbean Sea", "Capri Blue", "Sky", "Teal", "Peacock", "Turquoise", "Light Blue",
              "Pastel Blue", "Cobalt", "Dark Blue", "Midnight", "Robin's Egg", "Parrot Green", "Clear Blue"],
}
STOCK_PAL = None     # the game's original palette, for reading stock sprites (set by sprites())
STOCK_WATER = {95}
STOCK_GLINT = set(range(200, 212))
STOCK_WATERLINE = {146}
TREE_MIX = {6: (1, 0), 7: (2, 0), 8: (2, 1), 9: (1, 2), 10: (2, 3), 11: (1, 5), 12: (0, 8)}  # (palms, broadleaf)


def read_archive(path):
    """DATA/*.DAT sprite archive -> {sprite id: pixel array}."""
    from make_mif import decode
    d = Path(path).read_bytes()
    cnt = struct.unpack(">H", d[:2])[0]
    ent = [struct.unpack(">HIHH", d[2 + 10 * i:12 + 10 * i]) for i in range(cnt)]
    out = {}
    for i, (sid, off, h, w) in enumerate(ent):
        end = ent[i + 1][1] if i + 1 < cnt else len(d)
        out[sid] = decode(d[off:end], w, h)
    return out


def stock_sprites(game_dir):
    data = Path(game_dir) / "DATA"
    out = read_archive(data / "SMALLMED.DAT")
    out.update(read_archive(data / "LARGE.DAT"))
    return out


def lum(rgb):
    return rgb @ np.array([0.30, 0.59, 0.11], dtype=np.float32)


def family(pal, usable, kind):
    """Palette slots holding the beads a recoloured sprite of this kind may use."""
    return P.slots_of(pal, FAMILIES[kind], usable)


def dither(target, mask, pal, cands, strength=0.6):
    """Floyd-Steinberg from target RGB to palette indices in `cands`; -1 outside mask.
    `strength` scales the diffused error: low values give near-solid fills."""
    h, w = mask.shape
    t = target.astype(np.float32).copy()
    out = np.full((h, w), -1, dtype=int)
    cpal = pal[cands]
    wts = np.array([0.30, 0.59, 0.11], dtype=np.float32) ** 0.5
    for y in range(h):
        for x in range(w):
            if not mask[y, x]:
                continue
            want = t[y, x]
            k = int(np.argmin((((cpal - want) * wts) ** 2).sum(1)))
            out[y, x] = cands[k]
            err = want - cpal[k]
            for dx, dy, f in ((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)):
                xx, yy = x + dx, y + dy
                if 0 <= xx < w and yy < h and mask[yy, xx]:
                    t[yy, xx] += err * (f / 16) * strength
    return out


def recolour(px, pal, usable, water=TURQUOISE, glint="shallow", surface=SAND, rock=None):
    """Stock terrain/water sprite -> `surface` ground and `water`, same shape and shading.
    With `rock`, the stock grey stone (and very dark mortar) of cliff faces becomes
    that colour instead of tinted surface. Shimmer pixels stay in a colour-cycling
    range: the stock short cycle for shallow water, the 8-step cycle for deep water."""
    spal = STOCK_PAL if STOCK_PAL is not None else pal      # stock pixels: original colours
    ref = lum(spal[SAND_REF])
    rock_ref = lum(spal[ROCK_REF])
    target = np.zeros(px.shape + (3,), dtype=np.float32)
    is_water = np.isin(px, list(STOCK_WATER))
    is_glint = np.isin(px, list(STOCK_GLINT))
    is_line = np.isin(px, list(STOCK_WATERLINE))
    land = (px >= 0) & ~is_water & ~is_glint & ~is_line
    is_rock = np.zeros(px.shape, dtype=bool)
    kmap = np.full(px.shape, np.nan, dtype=np.float32)
    for idx in np.unique(px[land]):
        c = spal[idx]
        k = min(lum(c) / ref, 1.0)          # sunlit slopes would otherwise dither to white
        grey = (c.max() - c.min()) < 8
        if rock is not None and (grey or k < 0.5):
            target[px == idx] = (rock * min(lum(c) / rock_ref, 1.3)).clip(0, 255)
            is_rock |= px == idx
        else:
            kmap[px == idx] = k
            target[px == idx] = (surface * k * (ROCK if grey else 1)).clip(0, 255)
    # grass and sand: a 3x3 median of the stock shading drops its speckle texture but keeps
    # each face's light, so the fill comes out near-solid
    grass = land & ~is_rock
    pad = np.pad(np.where(grass, kmap, np.nan), 1, constant_values=np.nan)
    h, w = px.shape
    stack = np.stack([pad[1 + dy:h + 1 + dy, 1 + dx:w + 1 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
    with np.errstate(all="ignore"):
        smooth = np.nanmedian(stack, axis=0)
    target[grass] = (surface * smooth[grass][:, None]).clip(0, 255)
    target[is_water] = water
    target[is_line] = FOAM
    out = np.full(px.shape, -1, dtype=int)
    # grass and rock dither separately, so neither picks the other's colours
    top = land & ~is_rock
    kind = "sand" if rock is None else "grass" if surface is GRASS else "dry"
    # ground is near-solid (the stock shading still shows); sand keeps a light grain
    out[top] = dither(target, top, pal, family(pal, usable, kind), 0.0)[top]     # solid beads
    if is_rock.any():
        out[is_rock] = dither(target, is_rock, pal, family(pal, usable, "rock"), 0.0)[is_rock]
    sea = dither(target, is_water | is_line, pal, family(pal, usable, "water"), 0.0)
    out[is_water | is_line] = sea[is_water | is_line]
    if glint == "deep":
        ys, xs = np.nonzero(is_glint)
        for y, x in zip(ys, xs):
            k = px[y, x] % 4 if px[y, x] >= 208 else (px[y, x] - 200) // 2
            out[y, x] = DEEP_GLINT[2 * k + ((x + y) & 1)]
    else:
        ys, xs = np.nonzero(is_glint)
        for y, x in zip(ys, xs):
            v = px[y, x]
            out[y, x] = v if v >= 208 else SHALLOW_GLINT[(v - 200) % 4]
    return out


# --- trees --------------------------------------------------------------------------
TRUNK = _beads("Light Brown")[0] + (255,)
TRUNK_DARK = _beads("Brown")[0] + (255,)
FRONDS = [c + (255,) for c in _beads("Dark Green", "Bright Green", "Kiwi Lime")]
CANOPY = [c + (255,) for c in _beads("Evergreen", "Dark Green", "Bright Green", "Kiwi Lime")]  # dark -> lit


def draw_palm(dr, bx, by, tile_px, ss, rng):
    th = tile_px * 0.30 * rng.uniform(0.75, 1.1)
    lean = rng.uniform(-0.25, 0.25) * th
    top = (bx + lean, by - th)
    steps = 6
    pts = [(bx + lean * (i / steps) ** 2, by - th * i / steps) for i in range(steps + 1)]
    lw = max(1, round(tile_px / 20 * ss))
    dr.line([(x * ss, y * ss) for x, y in pts], fill=TRUNK_DARK, width=lw + ss // 2)
    dr.line([(x * ss + ss * 0.3, y * ss) for x, y in pts], fill=TRUNK, width=lw)
    r = tile_px * rng.uniform(0.13, 0.16)
    for j in range(7):
        a = j * 2 * math.pi / 7 + rng.uniform(-0.3, 0.3)
        col = FRONDS[0] if math.sin(a) > 0.3 else FRONDS[1] if math.sin(a) > -0.3 else FRONDS[2]
        arc = []
        for i in range(6):
            f = i / 5
            arc.append(((top[0] + math.cos(a) * r * f) * ss,
                        (top[1] + 0.5 * math.sin(a) * r * f + r * 0.55 * f * f) * ss))
        dr.line(arc, fill=col, width=max(1, round(tile_px / 18 * ss)))


def draw_broadleaf(dr, bx, by, tile_px, ss, rng):
    """A spreading monkeypod/banyan-style shade tree: short trunk, wide domed canopy."""
    th = tile_px * rng.uniform(0.10, 0.14)
    w = tile_px * rng.uniform(0.15, 0.21)
    h = w * 0.62
    dr.line([(bx * ss, by * ss), (bx * ss, (by - th) * ss)], fill=TRUNK_DARK, width=max(1, round(tile_px / 14 * ss)))
    cx, cy = bx, by - th - h * 0.45
    for k, col in enumerate(CANOPY):
        f = 1 - 0.2 * k                      # each lighter layer smaller, nudged up-left toward the sun
        ox, oy = -w * 0.12 * k, -h * 0.16 * k
        for _ in range(3):
            jx, jy = rng.uniform(-0.18, 0.18) * w, rng.uniform(-0.15, 0.15) * h
            rx, ry = w * f * rng.uniform(0.55, 0.75), h * f * rng.uniform(0.55, 0.75)
            x0, y0 = cx + ox + jx, cy + oy + jy
            dr.ellipse([(x0 - rx) * ss, (y0 - ry) * ss, (x0 + rx) * ss, (y0 + ry) * ss], fill=col)


def tree_sprite(tile_px, palms, broad, seed):
    """Trees standing on one tile, bottom-aligned like a stock tree sprite (RGBA)."""
    rng = random.Random(seed)
    ss = 4
    hw, hh = tile_px / 2, tile_px / 4
    pad = int(math.ceil(tile_px * 0.44)) + 1
    W, H = int(tile_px), int(tile_px / 2) + pad
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    kinds = ["palm"] * palms + ["broad"] * broad
    rng.shuffle(kinds)
    spots = []
    for _ in range(len(kinds) * 40):
        if len(spots) == len(kinds):
            break
        gx, gy = rng.uniform(0.15, 0.85), rng.uniform(0.15, 0.85)
        if all(math.hypot(gx - a, gy - b) > 0.24 for a, b in spots) or len(kinds) > 6:
            spots.append((gx, gy))
    order = sorted(zip(spots, kinds), key=lambda p: p[0][0] + p[0][1])   # back to front
    for (gx, gy), kind in order:
        bx = (gx - gy) * hw + hw
        by = H - tile_px / 2 + (gx + gy) * hh
        (draw_palm if kind == "palm" else draw_broadleaf)(dr, bx, by, tile_px, ss, rng)
    return img.resize((W, H), Image.BOX)


# --- street trees ---------------------------------------------------------------------
# flat road pieces and the road arms each one has (T = x-1, B = x+1, R = y-1, L = y+1,
# as in highway.py); the sloped pieces 0x1F-0x22 stay bare
STREET_ARMS = {0x1D: "LR", 0x1E: "TB", 0x23: "BR", 0x24: "BL", 0x25: "TL", 0x26: "TR",
               0x27: "RTB", 0x28: "LBR", 0x29: "TLB", 0x2A: "LTR", 0x2B: "LTBR"}
EDGE_SPOTS = {"T": [(0.07, 0.3), (0.07, 0.72)], "B": [(0.93, 0.3), (0.93, 0.72)],
              "R": [(0.3, 0.07), (0.72, 0.07)], "L": [(0.3, 0.93), (0.72, 0.93)]}


# flowering shrubs between the street trees: the middle of each planted side
FLOWER_SPOTS = {"T": [(0.07, 0.51)], "B": [(0.93, 0.51)], "R": [(0.51, 0.07)], "L": [(0.51, 0.93)]}
# bougainvillea (Fuchsia, Magenta), hibiscus (Hot Coral), plumeria (White, Yellow), bird of paradise (Orange)
BLOOMS = [c + (255,) for c in _beads("Fuchsia", "Magenta", "Hot Coral", "White", "Yellow", "Orange")]
LEAVES = _beads("Dark Green")[0] + (255,)


def draw_flowers(dr, bx, by, tile_px, ss, rng):
    """A low flowering shrub: a dark leafy mound dotted with blossoms."""
    rx, ry = tile_px * 0.075, tile_px * 0.045
    dr.ellipse([(bx - rx) * ss, (by - 2 * ry) * ss, (bx + rx) * ss, by * ss], fill=LEAVES)
    col = rng.choice(BLOOMS)
    for _ in range(3):
        fx, fy = bx + rng.uniform(-0.6, 0.6) * rx, by - ry * rng.uniform(1.0, 1.7)
        r = max(0.5, tile_px / 40)
        dr.ellipse([(fx - r) * ss, (fy - r) * ss, (fx + r) * ss, (fy + r) * ss], fill=col)


def street_tree_sprite(tile_px, spots, seed, flowers=()):
    """Trees (and flowering shrubs at `flowers`) at given tile positions (gx, gy in 0..1),
    bottom-aligned like tree_sprite."""
    rng = random.Random(seed)
    ss = 4
    hw, hh = tile_px / 2, tile_px / 4
    pad = int(math.ceil(tile_px * 0.40)) + 1
    W, H = int(tile_px), int(tile_px / 2) + pad
    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    items = [(p, "tree") for p in spots] + [(p, "flowers") for p in flowers]
    k = 0
    for (gx, gy), kind in sorted(items, key=lambda it: it[0][0] + it[0][1]):     # back to front
        bx = (gx - gy) * hw + hw
        by = H - tile_px / 2 + (gx + gy) * hh
        if kind == "flowers":
            draw_flowers(dr, bx, by, tile_px * 0.8, ss, rng)
            continue
        (draw_palm if (k + seed) % 3 == 0 else draw_broadleaf)(dr, bx, by, tile_px * 0.8, ss, rng)
        k += 1
    return img.resize((W, H), Image.BOX)


def street_trees(road_px, tile_px, piece, pal, usable):
    """A road piece lined with monkeypods, palms and flowering shrubs along each side
    that has no road."""
    arms = STREET_ARMS[piece]
    if len(arms) == 4:                                  # crossroads: one tree in each corner
        spots, flowers = [(0.06, 0.06), (0.94, 0.06), (0.06, 0.94), (0.94, 0.94)], []
    else:
        spots = [p for side in "TBRL" if side not in arms for p in EDGE_SPOTS[side]]
        flowers = [p for side in "TBRL" if side not in arms for p in FLOWER_SPOTS[side]]
    trees = rgba_to_indices(street_tree_sprite(tile_px, spots, piece, flowers), pal, usable)
    return underlay(trees, road_px)


def rgba_to_indices(a, pal, usable):
    a = np.asarray(a, dtype=np.float32)
    mask = a[..., 3] > 90
    out = np.full(mask.shape, -1, dtype=int)
    rgb = a[..., :3] / np.maximum(a[..., 3:4] / 255, 1e-3)
    wts = np.array([0.30, 0.59, 0.11]) ** 0.5
    d = (((rgb[..., None, :] - pal[usable][None, None]) * wts) ** 2).sum(-1)
    out[mask] = usable[np.argmin(d, -1)][mask]
    return out


def tree_pixels(tile_px, palms, broad, seed, pal, usable):
    return rgba_to_indices(tree_sprite(tile_px, palms, broad, seed), pal, usable)


def underlay(px, floor):
    """Put `floor` (a flat tile sprite) under `px`, bottom-aligned; returns the taller of the two."""
    H = max(px.shape[0], floor.shape[0])
    out = np.full((H, px.shape[1]), -1, dtype=int)
    out[H - floor.shape[0]:] = floor
    top = out[H - px.shape[0]:]
    top[px >= 0] = px[px >= 0]
    return out


def lawn_pixels(tile_px, palms, broad, seed, ground_mask, pal, usable, colour=GRASS, stripes=False):
    """A grass-covered tile (exactly the flat terrain diamond), optionally with trees."""
    rng = np.random.default_rng(seed)
    gh, w = ground_mask.shape[0], int(tile_px)
    target = np.zeros((gh, w, 3), dtype=np.float32)
    shade = 1 + rng.normal(0, 0.015, size=(gh, w))
    target[:] = colour * shade[..., None]
    if stripes:                              # mowing stripes along one grid axis: two greens
        ys, xs = np.mgrid[0:gh, 0:w]
        band = ((xs / 2 + ys) // max(2, tile_px // 8)).astype(int) % 2
        target[band == 1] = GRASS
    out = dither(target.clip(0, 255), ground_mask, pal, family(pal, usable, "grass"), 0.0)
    if palms or broad:
        out = underlay(tree_pixels(tile_px, palms, broad, seed, pal, usable), out)
    return out


def water_floor(tile, n, tile_px):
    """n x n flat water tiles laid out as the game tiles them (for the marina's basin)."""
    hw, hh = tile_px // 2, tile_px // 4
    th = tile.shape[0]
    H = (n - 1) * 2 * hh + th
    out = np.full((H, n * tile_px), -1, dtype=int)
    for s in range(2 * n - 1):                 # back to front
        for i in range(n):
            j = s - i
            if 0 <= j < n:
                x, y = (i - j + n - 1) * hw, (i + j) * hh
                region = out[y:y + th, x:x + tile.shape[1]]
                region[tile >= 0] = tile[tile >= 0]
    return out


def water_column(px, top, pal, usable):
    """The water column drawn down the map edge (and under waterfalls): deep azure on
    top, dark navy down the sides, its stock streaks kept as slightly lighter blue."""
    h, w = px.shape
    ys, xs = np.mgrid[0:h, 0:w]
    side = ys > w / 4 + (w / 2 - np.abs(xs + 0.5 - w / 2)) / 2
    k = np.ones((h, w), dtype=np.float32)
    k[np.isin(px, list(STOCK_GLINT | STOCK_WATERLINE))] = 1.45
    k[xs >= w / 2] *= 0.8                           # right face in shade
    k *= 1.1 - 0.35 * ys / h                       # darker with depth
    target = NAVY * k[..., None]
    m = (px >= 0) & side
    out = np.full(px.shape, -1, dtype=int)
    out[m] = dither(target.clip(0, 255), m, pal, family(pal, usable, "water"), 0.0)[m]
    t = min(top.shape[0], h)                       # the surface: the deep-water tile
    lid = (px[:t] >= 0) & ~side[:t] & (top[:t] >= 0)
    out[:t][lid] = top[:t][lid]
    return out


def sand_floor(stock, off, pal, usable):
    """The flat sand tile used under the beach props (matches the shoreline sand)."""
    return recolour(stock[off + 256], pal, usable)


def sprites(game_dir, pal, usable, stock_pal=None):
    """{sprite id: pixel array} for every replaced terrain, water, tree and lawn sprite.
    `pal` is the palette the game will show (the Perler one); `stock_pal` the
    original, which the stock sprites' pixels refer to."""
    global STOCK_PAL
    STOCK_PAL = stock_pal
    stock = stock_sprites(game_dir)
    out = {}
    for off in ZOOM_OFFSET:
        for base in TERRAIN:
            surface = GRASS if base == 256 else OLIVE
            out[off + base] = recolour(stock[off + base], pal, usable, surface=surface, rock=ROCK_BROWN)
        for base in WATER:
            deep = base == 270
            out[off + base] = recolour(stock[off + base], pal, usable,
                                       water=AZURE if deep else TURQUOISE, glint="deep" if deep else "shallow")
        out[off + SHALLOW_ID] = recolour(stock[off + 270], pal, usable)
        out[off + CANAL_ID] = recolour(stock[off + 270], pal, usable, water=CANAL)
        out[off + MID_ID] = recolour(stock[off + 270], pal, usable, water=MID, glint="deep")
        out[off + WATER_COLUMN] = water_column(stock[off + WATER_COLUMN], out[off + 270], pal, usable)
        tp = ZOOM_TILE_PX[off]
        for base in TREES:
            if base == HILL_HOMES_ID:
                continue                       # drawn by houses.hillside_scene instead
            palms, broad = TREE_MIX[base]
            px = tree_pixels(tp, palms, broad, base * 31, pal, usable)
            assert px.shape[1] == stock[off + base].shape[1]
            out[off + base] = px
        ground = stock[off + 256] >= 0
        out[off + LAWN_PALMS_ID] = lawn_pixels(tp, 1, 1, 1313, ground, pal, usable)
        out[off + LAWN_ID] = lawn_pixels(tp, 0, 0, 2191, ground, pal, usable, colour=FAIRWAY, stripes=True)
    return out


def preview(spr, pal, out=BUILD / "terrain_art.png"):
    ids = [1000 + i for i in list(TREES) + [LAWN_PALMS_ID, LAWN_ID] + list(TERRAIN) + [SHALLOW_ID, MID_ID, CANAL_ID]
           + list(WATER) if 1000 + i in spr]
    cols, cw = 11, 36
    ch = max(spr[i].shape[0] for i in ids) + 4
    rows = (len(ids) + cols - 1) // cols
    sheet = np.full((rows * ch, cols * cw, 3), 255, dtype=np.uint8)
    for k, i in enumerate(ids):
        px = spr[i]
        y0 = (k // cols) * ch + ch - 2 - px.shape[0]
        x0 = (k % cols) * cw + (cw - px.shape[1]) // 2
        m = px >= 0
        cols_ = pal.copy()
        for i, c in CYCLE_COLOURS.items():
            cols_[i] = c                       # show the shimmer as the patched palette will
        sheet[y0:y0 + px.shape[0], x0:x0 + px.shape[1]][m] = cols_[px[m]].astype(np.uint8)
    Image.fromarray(sheet).resize((sheet.shape[1] * 3, sheet.shape[0] * 3), Image.NEAREST).save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    from make_mif import read_bmp_palette, USABLE
    game = Path(sys.argv[1])
    pal = read_bmp_palette(game / "BITMAPS" / "PAL_MSTR.BMP")
    preview(sprites(game, pal, USABLE, P.original_palette(game)), pal)
