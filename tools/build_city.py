"""Assemble waikiki.sc2 from the rasterised geography and building placements.

Run after tools/geo.py:   python tools/build_city.py
Writes build/WAIKIKI.SC2, build/placements.json and build/map_topdown.png.
"""
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np
from shapely.strtree import STRtree

import geo
import highway
import osm_buildings
import placement
import terrain
from sc2file import City
from scipy_free import distance_to, four_connect, thin

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
TEMPLATE = ROOT / "templates" / "DEFAULT.SC2"     # the game's blank city; make_all.py copies it here
N = 128

# road pieces by neighbour mask (1: x-1, 2: x+1, 4: y-1, 8: y+1); from real saves
ROAD_BY_MASK = {0: 0x1D, 1: 0x1E, 2: 0x1E, 3: 0x1E, 4: 0x1D, 8: 0x1D, 12: 0x1D,
                6: 0x23, 10: 0x24, 9: 0x25, 5: 0x26, 7: 0x27, 14: 0x28, 11: 0x29, 13: 0x2A, 15: 0x2B}
# road on a simple slope: XTER 1..4 -> piece; 1 and 3 need the road along x, 2 and 4 along y
ROAD_SLOPE = {1: (0x1F, "x"), 2: (0x20, "y"), 3: (0x21, "x"), 4: (0x22, "y")}

MISC_TILE_COUNTS = 0x1F0
MISC_WATER_LEVEL = 0xE40
MISC_COAST = 0xE44
MISC_RIVER = 0xE48


def tallest_per_tile(entities):
    tall = np.zeros((N, N))
    tree = STRtree([e["poly"] for e in entities])
    from shapely.geometry import box
    for x in range(N):
        for y in range(N):
            tp = box(x, y, x + 1, y + 1)
            for i in tree.query(tp):
                e = entities[i]
                a = tp.intersection(e["poly"]).area
                if a > 0.15 or a > 0.4 * e["poly"].area:
                    tall[x, y] = max(tall[x, y], e["h"])
    return tall


# Diamond Head, exaggerated so the crater reads at SimCity's scale (grid tiles)
# reef-flat width (tiles from shore) by the grid x of the nearest shore
REEF_WIDTH = [(0, 3), (30, 3.5), (45, 5), (58, 8), (70, 10), (95, 10), (110, 12), (127, 12)]


def components(mask):
    """4-connected components of a boolean grid, as lists of (x, y)."""
    seen = np.zeros_like(mask)
    out = []
    for sx, sy in zip(*np.nonzero(mask)):
        if seen[sx, sy]:
            continue
        comp, stack = [], [(sx, sy)]
        seen[sx, sy] = True
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < N and 0 <= ny < N and mask[nx, ny] and not seen[nx, ny]:
                    seen[nx, ny] = True
                    stack.append((nx, ny))
        out.append(comp)
    return out


def reef_depth(sea, land):
    """Depth (levels below sea level) for each tile: 1 on the reef flat, 2-3 beyond.
    The reef edge is a smooth curve: true (Euclidean) distance from the shore against
    a width that varies gently along the coast, blurred, then cleared of stray
    islands of shallow water and stray holes of deep water."""
    near = np.zeros_like(land)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        near |= np.roll(np.roll(sea, dx, 0), dy, 1)
    shore = np.array(np.nonzero(land & near)).T.astype(float)            # land tiles on the sea
    cells = np.array(np.nonzero(sea)).T
    dist = np.zeros((N, N))
    width = np.zeros((N, N))
    for k in range(0, len(cells), 2048):
        c = cells[k:k + 2048].astype(float)
        d2 = ((c[:, None, :] - shore[None, :, :]) ** 2).sum(-1)
        nearest = d2.argmin(1)
        dist[c[:, 0].astype(int), c[:, 1].astype(int)] = np.sqrt(d2[np.arange(len(c)), nearest])
        width[c[:, 0].astype(int), c[:, 1].astype(int)] = np.interp(shore[nearest, 0], *zip(*REEF_WIDTH))
    shallow = (sea & (dist <= width)).astype(float)
    for _ in range(3):                                   # blur the edge into a curve
        pad = np.pad(shallow, 2, mode="edge")
        shallow = sum(pad[2 + dx:N + 2 + dx, 2 + dy:N + 2 + dy] for dx in range(-2, 3) for dy in range(-2, 3)) / 25
    shallow = sea & ((shallow >= 0.5) | (dist <= 1.5))
    # a shallow patch not touching the shore is a stray: deepen it; a small deep hole
    # inside the reef (not open to the map edge) is a stray too: make it shallow
    for comp in components(shallow):
        if not any(near[x, y] or land[max(x - 1, 0):x + 2, max(y - 1, 0):y + 2].any() for x, y in comp):
            for x, y in comp:
                shallow[x, y] = False
    for comp in components(sea & ~shallow):
        if len(comp) < 60 and not any(x in (0, N - 1) or y in (0, N - 1) for x, y in comp):
            for x, y in comp:
                shallow[x, y] = True
    # beyond the reef the seabed drops a level per tile for two tiles (rings by
    # Chebyshev distance, so each ring touches the one before): every tile in that
    # band, and the first ring of the deep floor, sits on a slope, which patch_game.py
    # draws as a third, mid-depth colour; the open floor further out is flat and deep
    ring = distance_to(shallow | land)
    depth = np.where(shallow, 1, 1 + np.minimum(ring, 3))
    return depth, dist
DH_CENTRE = (94.9, 77.7)      # middle of the crater floor
DH_FLOOR_M = 80.0              # crater floor height; relief above it is stretched
DH_STRETCH, DH_CAP_LEVELS = 3.0, 5
DH_LEAHI_LEVELS = 5            # extra height for the Leahi summit (a sharp peak at the SW corner)


def exaggerate_diamond_head(elev, land, level_m, keep=None):
    """Stretch the crater rim's relief (capped, so the inner wall leaves a wide floor),
    lift Leahi, and raise the outer flanks to the steepest slope the game allows, so
    the rim stands up as a ring. `keep` tiles (roads) are not raised, so the roads
    around the crater stay drivable. Returns (elevation, Diamond Head region mask)."""
    xs, ys = np.mgrid[0:N, 0:N]
    cx, cy = DH_CENTRE
    r = np.hypot(xs - cx, ys - cy)
    radius = 18 + 5 * np.clip((ys - cy) / np.maximum(r, 1e-6), 0, 1)   # wider toward the sea
    w = np.clip((radius - r) / 4, 0, 1)
    rel = elev - DH_FLOOR_M
    e = np.where(rel > 0, DH_FLOOR_M + np.minimum(rel * DH_STRETCH, DH_CAP_LEVELS * level_m) * w + rel * (1 - w), elev)
    ring = (r < radius) & land
    peak = np.unravel_index(np.argmax(np.where(ring, elev, 0)), elev.shape)
    d = np.hypot(xs - peak[0], ys - peak[1])
    e = e + np.clip(1 - d / 3.5, 0, 1) * DH_LEAHI_LEVELS * level_m
    for _ in range(40):                        # outer flanks: as steep as the slope rule allows
        p = np.pad(e, 1)
        hi = np.max([p[1 + dx:N + 1 + dx, 1 + dy:N + 1 + dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1)], axis=0)
        e = np.where(ring & ~keep if keep is not None else ring, np.maximum(e, hi - level_m * 0.98), e)
    return e, ring


def ocean_component(water):
    """The largest 4-connected body of water (the Pacific); everything else is inland."""
    seen = np.zeros_like(water)
    best = np.zeros_like(water)
    for sx, sy in zip(*np.nonzero(water)):
        if seen[sx, sy]:
            continue
        comp, stack = [], [(sx, sy)]
        seen[sx, sy] = True
        while stack:
            x, y = stack.pop()
            comp.append((x, y))
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < N and 0 <= ny < N and water[nx, ny] and not seen[nx, ny]:
                    seen[nx, ny] = True
                    stack.append((nx, ny))
        if len(comp) > best.sum():
            best[:] = False
            for x, y in comp:
                best[x, y] = True
    return best


def small_islands(land, box, max_tiles):
    """Land components (4-connected) of at most `max_tiles` tiles lying wholly in `box`."""
    x0, y0, x1, y1 = box
    seen = np.zeros_like(land)
    out = np.zeros_like(land)
    for sx in range(x0, x1):
        for sy in range(y0, y1):
            if not land[sx, sy] or seen[sx, sy]:
                continue
            comp, stack = [], [(sx, sy)]
            seen[sx, sy] = True
            while stack:
                x, y = stack.pop()
                comp.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < N and 0 <= ny < N and land[nx, ny] and not seen[nx, ny]:
                        seen[nx, ny] = True
                        stack.append((nx, ny))
            if len(comp) <= max_tiles and all(x0 <= x < x1 and y0 <= y < y1 for x, y in comp):
                for x, y in comp:
                    out[x, y] = True
    return out


def main():
    BUILD.mkdir(exist_ok=True)
    g = dict(np.load(geo.DATA / "grid.npz"))
    frame = geo.Frame()
    T = float(g["T"])
    print(f"tile {T:.1f} m")

    entities = osm_buildings.load(frame)
    g["tall"] = tallest_per_tile(entities)

    # --- terrain ---------------------------------------------------------------
    land = g["land"] >= 0.5
    water = ~land | (g["water"] >= 0.5)
    els = geo.load_osm()
    # the H-1 freeway is drawn as a SimCity highway (highway.py), not as streets
    road_cls, _, bridges = geo.rasterize_roads([e for e in els if e.get("tags", {}).get("highway") != "motorway"],
                                               frame)
    # divided avenues and closely parallel streets rasterise two tiles wide; thin
    # them to single-tile roads, then make every joint 4-connected
    roads = four_connect(thin(road_cls > 0))
    # water wins over roads, except at real bridges: those become causeway fill
    # (SC2K needs proper bridges for water; a short culvert keeps the grid intact)
    # surface water: lakes and streams inside the land, and the Ala Wai Canal, which OSM's
    # coastline treats as tidal sea; drawn at ground level as the dark canal tile
    inland_water = water & (land | (g["water"] >= 0.5) | ~ocean_component(water))
    near_bridge = bridges.copy()
    near_bridge[1:] |= bridges[:-1]; near_bridge[:-1] |= bridges[1:]
    near_bridge[:, 1:] |= bridges[:, :-1]; near_bridge[:, :-1] |= bridges[:, 1:]
    culvert = roads & inland_water & near_bridge
    water &= ~culvert
    roads &= ~water

    # Ala Wai Harbor, laid out by hand: the coastline data leaves scraps of land
    # all over the basin, so set its water and land outright, then drown islets
    for x0, y0, x1, y1 in placement.HARBOUR_WATER:
        water[x0:x1, y0:y1] = True
        inland_water[x0:x1, y0:y1] = False
        g["beach"][x0:x1, y0:y1] = 0
    for x0, y0, x1, y1 in placement.HARBOUR_LAND:
        water[x0:x1, y0:y1] = False
        inland_water[x0:x1, y0:y1] = False
        g["elev"][x0:x1, y0:y1] = 0.5
        g["beach"][x0:x1, y0:y1] = 0
        g["land"][x0:x1, y0:y1], g["water"][x0:x1, y0:y1] = 1.0, 0.0
    for x0, y0, x1, y1 in placement.HARBOUR_BEACH:
        water[x0:x1, y0:y1] = False
        inland_water[x0:x1, y0:y1] = False
        roads[x0:x1, y0:y1] = False
        g["elev"][x0:x1, y0:y1] = 0.5
        g["beach"][x0:x1, y0:y1] = 1.0
        g["land"][x0:x1, y0:y1], g["water"][x0:x1, y0:y1] = 1.0, 0.0
    islets = small_islands(~water, placement.TIDY, max_tiles=10)
    water |= islets
    g["land"] = np.where(islets, 0.0, g["land"])
    roads &= ~water

    # the marina sprites draw their own water, so their tiles are land
    harbour = np.zeros_like(water)
    for x, y in placement.MARINAS:
        harbour[x:x + 3, y:y + 3] = True
    water &= ~harbour
    inland_water &= ~harbour
    g["elev"] = np.where(harbour, 0.5, g["elev"])
    # Waikiki Beach one tile wider: ocean tiles touching a beach become sand
    sea = water & ~inland_water
    beach_land = ~water & (g["beach"] > 0.15)
    touch = np.zeros_like(beach_land)
    touch[1:] |= beach_land[:-1]; touch[:-1] |= beach_land[1:]
    touch[:, 1:] |= beach_land[:, :-1]; touch[:, :-1] |= beach_land[:, 1:]
    basin = np.zeros_like(water)
    for x0, y0, x1, y1 in placement.HARBOUR_WATER:
        basin[x0:x1, y0:y1] = True
    widen = sea & touch & ~harbour & ~basin
    water &= ~widen
    g["beach"] = np.where(widen, 1.0, g["beach"])
    g["elev"] = np.where(widen, 0.5, g["elev"])
    for k in ("land", "water"):
        g[k] = np.where(harbour | widen, 1.0 if k == "land" else 0.0, g[k])
    # the widened sand can leave specks offshore of the Hilton: drown them too
    specks = small_islands(~water, placement.TIDY, max_tiles=10)
    water |= specks
    g["land"] = np.where(specks, 0.0, g["land"])
    g["beach"] = np.where(specks, 0.0, g["beach"])
    print(f"beach widened by {int(widen.sum() - specks.sum())} tiles net; {int(islets.sum() + specks.sum())} islet tiles drowned")
    roads &= ~harbour
    print(f"beach widened by {int(widen.sum())} tiles; {len(placement.MARINAS)} marinas")

    # specials sit on dry land
    for _, (x0, y0), n, *_ in placement.SPECIAL:
        water[x0:x0 + n, y0:y0 + n] = False
        inland_water[x0:x0 + n, y0:y0 + n] = False
        g["land"][x0:x0 + n, y0:y0 + n] = 1.0
    # the UH Manoa campus: tiles within two of a university building
    uni = np.zeros((N, N), dtype=bool)
    for e in els:
        t = e.get("tags", {})
        if t.get("building") in ("university", "college") or t.get("amenity") in ("university", "college"):
            for poly in geo.polygons_of(e):
                cx, cy = frame.world_to_grid(poly.centroid.x, poly.centroid.y)
                if 0 <= cx < N and 0 <= cy < N:
                    uni[int(cx), int(cy)] = True
    campus = uni.copy()
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            campus |= np.roll(np.roll(uni, dx, 0), dy, 1)
    g["campus"] = campus
    # the Honolulu Zoo's grounds (for its planting)
    zoo = [p for e in els if e.get("tags", {}).get("name") == "Honolulu Zoo" for p in geo.polygons_of(e)]
    g["zoo"] = geo.coverage(frame, zoo)

    # H-1: a two-tile band of dry land with a one-tile margin, all levelled below
    hw_blocks = highway.plan(frame, els)
    hw_band = highway.band_mask(hw_blocks)
    hw_margin = np.zeros_like(hw_band)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            hw_margin |= np.roll(np.roll(hw_band, dx, 0), dy, 1)
    hw_margin &= ~hw_band
    for m in (hw_band, hw_margin):
        water &= ~m
        inland_water &= ~m
        g["land"] = np.where(m, 1.0, g["land"])
    hw_cross = highway.crossings(hw_blocks, roads)
    roads &= ~hw_band
    print(f"H-1: {len(hw_blocks)} blocks, {sum(b['kind'] == 'corner' for b in hw_blocks)} turns, "
          f"{len(hw_cross) // 2} road crossings")

    # sea depth: the turquoise reef flat, narrow off central Waikiki and wide past
    # Kaimana, Diamond Head and Kahala (from satellite imagery), with a smooth edge;
    # deeper water beyond
    depth, dist = reef_depth(water & ~inland_water, ~water)
    depth = np.where(inland_water, 1, depth)
    level_m = 12 / (0.866 * 32 / (math.sqrt(2) * T))    # metres per altitude level (true scale)
    print(f"altitude step {level_m:.1f} m")
    g["elev"], g["diamond_head"] = exaggerate_diamond_head(g["elev"], ~water, level_m, keep=roads)
    # hand-modelled landmarks stand on level ground: flatten each footprint (and pull
    # down any higher ground round it) to the footprint's median height
    for _, (x0, y0), n, *_ in placement.SPECIAL:
        med = float(np.median(g["elev"][x0:x0 + n, y0:y0 + n]))
        g["elev"][x0:x0 + n, y0:y0 + n] = med
        ring = g["elev"][max(0, x0 - 1):x0 + n + 1, max(0, y0 - 1):y0 + n + 1]
        ring[...] = np.minimum(ring, med)
        g["elev"][x0:x0 + n, y0:y0 + n] = med
    # the freeway runs level: an embankment over low ground, a cut (with its margin) through hills
    hw_elev = highway.LEVEL * level_m
    g["elev"] = np.where(hw_band, hw_elev, np.where(hw_margin, np.minimum(g["elev"], hw_elev), g["elev"]))
    altm, xter, xbit, level = terrain.build(g["elev"], water, level_m, sea_depth=depth, surface=inland_water)
    xter = bytearray(xter)
    xbit = bytearray(xbit)
    is_water = np.frombuffer(bytes(xbit), dtype=np.uint8).reshape(N, N) & terrain.XBIT_WATER > 0

    # --- buildings & vegetation -------------------------------------------------
    grid = dict(g)
    grid["roads"] = np.where(roads, np.maximum(road_cls, 1), 0).astype(np.int8)
    grid["land"] = (~is_water).astype(float)
    grid["water"] = is_water.astype(float)
    shape = np.frombuffer(bytes(xter), dtype=np.uint8).reshape(N, N)
    # buildings need flat ground; mark sloped tiles occupied for placement purposes
    sloped = (shape != 0) & ~is_water
    grid["land"][sloped] = 0.0
    bad = hw_band & ((shape != 0) | is_water)
    assert not bad.any(), f"H-1 on slope/water at {list(zip(*np.nonzero(bad)))[:5]}"
    grid["roads"] = np.where(hw_band, 4, grid["roads"]).astype(np.int8)   # nothing else goes on the freeway
    placements, landmarks, trees, claimed = placement.place(grid, entities)
    roads &= ~claimed

    xbld = bytearray(N * N)
    xzon = bytearray(N * N)
    for p in placements:
        x0, y0, n = p["x"], p["y"], p["n"]
        for x in range(x0, x0 + n):
            for y in range(y0, y0 + n):
                xbld[x * N + y] = p["xbld"]
                xzon[x * N + y] = p["zone"]
        if n == 1:
            xzon[x0 * N + y0] |= 0xF0
        else:
            far = (x0 + n - 1, y0 + n - 1)
            xzon[x0 * N + y0] |= 0x10
            xzon[far[0] * N + y0] |= 0x20
            xzon[far[0] * N + far[1]] |= 0x40
            xzon[x0 * N + far[1]] |= 0x80
    for x, y, t in trees:
        if t in placement.LAWNS and shape[x, y] != 0:
            if t == placement.LAWN:
                continue                                  # lawns only render on flat ground;
            t = 0x08                                      # the grass terrain shows instead
        xbld[x * N + y] = t
        if t >= 0x70:
            xzon[x * N + y] |= 0xF0   # 1x1 building: all four corner bits

    for x, y, pid, bits in highway.pieces(hw_blocks, hw_cross):
        xbld[x * N + y] = pid
        xzon[x * N + y] = bits

    # --- roads ------------------------------------------------------------------
    road_ok = roads & ~is_water
    under = np.zeros_like(road_ok)              # roads passing under the freeway still join up
    for x, y in hw_cross:
        under[x, y] = True
    for x in range(N):
        for y in range(N):
            if not road_ok[x, y]:
                continue
            s = shape[x, y]
            if s != 0 and s not in ROAD_SLOPE:
                road_ok[x, y] = False
    for x in range(N):
        for y in range(N):
            if not road_ok[x, y]:
                continue
            m = 0
            for bit, (dx, dy) in enumerate(((-1, 0), (1, 0), (0, -1), (0, 1))):
                X, Y = x + dx, y + dy
                if 0 <= X < N and 0 <= Y < N and (road_ok[X, Y] or under[X, Y]):
                    m |= 1 << bit
            s = shape[x, y]
            if s in ROAD_SLOPE:
                piece, axis = ROAD_SLOPE[s]
                if (axis == "x" and m & 12) or (axis == "y" and m & 3):
                    continue  # a junction can't sit on a slope; leave a gap
                xbld[x * N + y] = piece
            else:
                xbld[x * N + y] = ROAD_BY_MASK[m]
            xzon[x * N + y] = 0

    # --- city file -------------------------------------------------------------
    if not TEMPLATE.exists():
        sys.exit(f"{TEMPLATE} is missing: run make_all.py with the game folder, which copies the game's DEFAULT.SC2")
    city = City.load(TEMPLATE)
    city.set_name("Waikiki")
    city.chunks[b"ALTM"] = altm
    city.chunks[b"XTER"] = bytes(xter)
    city.chunks[b"XBLD"] = bytes(xbld)
    city.chunks[b"XZON"] = bytes(xzon)
    city.chunks[b"XUND"] = bytes(N * N)
    city.chunks[b"XTXT"] = bytes(N * N)
    city.chunks[b"XBIT"] = bytes(xbit)
    for cid in (b"XTRF", b"XPLT", b"XVAL", b"XCRM"):
        city.chunks[cid] = bytes(4096)
    for cid in (b"XPLC", b"XFIR", b"XPOP"):
        city.chunks[cid] = bytes(1024)
    city.chunks[b"XROG"] = bytes([0x7F]) * 1024
    city.chunks[b"XTHG"] = bytes(480)
    city.chunks[b"XMIC"] = bytes(1200)

    # landmark signs (max 50 user signs)
    xtxt = bytearray(N * N)
    xlab = bytearray(city.chunks[b"XLAB"])
    named = [p for p in landmarks if p["entity"]["name"]][:50]
    for i, p in enumerate(named, start=1):
        text = sign_text(p["entity"]["name"])
        rec = bytes([len(text)]) + text + bytes(24 - len(text))
        xlab[i * 25:(i + 1) * 25] = rec
        cx, cy = p["x"] + p["n"] // 2, p["y"] + p["n"] // 2
        xtxt[cx * N + cy] = i
    city.chunks[b"XTXT"] = bytes(xtxt)
    city.chunks[b"XLAB"] = bytes(xlab)

    misc = bytearray(city.chunks[b"MISC"])
    counts = np.bincount(np.frombuffer(bytes(xbld), dtype=np.uint8), minlength=256)
    for i in range(256):
        struct.pack_into(">i", misc, MISC_TILE_COUNTS + 4 * i, int(counts[i]))
    city.chunks[b"MISC"] = bytes(misc)
    city.misc_set(MISC_WATER_LEVEL, terrain.SEA_LEVEL)
    city.misc_set(MISC_COAST, 1)
    city.misc_set(MISC_RIVER, 0)
    city.misc_set(0x14, 1_000_000)        # funds
    city.misc_set(0x0C, 1996)             # year founded
    city.misc_set(0xFEC, 1)               # speed: paused
    city.misc_set(0x1018, 64)             # view centre x
    city.misc_set(0x101C, 80)             # view centre y
    out = BUILD / "WAIKIKI.SC2"
    city.save(out)
    print(f"wrote {out}  ({len(landmarks)} landmarks, {len(placements)} buildings)")

    # placements for the sprite generator / preview
    rec = []
    for p in placements:
        q = {k: v for k, v in p.items() if k != "entity"}
        if p["kind"] == "landmark":
            q["entity_id"] = p["entity"]["id"]
            q["h"] = p["entity"]["h"]
        rec.append(q)
    json.dump({"T": T, "placements": rec}, open(BUILD / "placements.json", "w"), indent=0)
    for p in landmarks:
        print(f"  {p['n']}x{p['n']} 0x{p['xbld']:02X} ({p['x']:3d},{p['y']:3d}) {p['entity']['h']:5.0f} m  {p['entity']['name']}")
    np.savez_compressed(BUILD / "city_layers.npz", level=level, shape=shape, xbld=np.frombuffer(bytes(xbld), dtype=np.uint8).reshape(N, N),
                        water=is_water)


def sign_text(name):
    name = (name.replace("ʻ", "'").replace("ī", "i").replace("ā", "a").replace("ū", "u")
            .replace("ō", "o").replace("ē", "e"))
    for cut in (" by Hilton Grand Vacations", ", LXR Hotels & Resorts", " Resort and Spa", " Resort & Spa",
                " Beach Resort", " Hotel", " Waikiki Beach"):
        if len(name) > 23:
            name = name.replace(cut, "")
    return name.encode("ascii", "replace")[:23]


if __name__ == "__main__":
    main()
