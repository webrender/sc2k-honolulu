"""Decide which SC2K building goes on which tile.

Output: list of placements {x, y, n, xbld, zone, kind, sprite} where (x, y) is the
footprint's minimum corner and `sprite` describes how to draw custom slots.
"""
import math
import random

import numpy as np
from shapely.geometry import box

N = 128

# --- SCURK slot plan ------------------------------------------------------------
# Unique landmark sprites (replace these stock buildings' graphics):
UNIQUE_SLOTS = {
    3: [0xAE, 0xAF, 0xB0, 0xB1,                     # residential 3x3
        0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xBB,   # commercial 3x3
        0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xC1],        # industrial 3x3
    2: [0x8C, 0x8D, 0x8E, 0x8F, 0x90, 0x91, 0x92, 0x93,            # residential 2x2
        0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0x9B, 0x9C, 0x9D,  # commercial 2x2
        0x9E, 0x9F],                                # industrial 2x2
    1: [0x7C, 0x7F, 0x82, 0x83, 0x84, 0x85],        # commercial/industrial 1x1
}
# Generic Waikiki towers, by height (metres) they stand in for:
GENERIC_SLOTS = {
    2: [(0xA0, 30), (0xA1, 48), (0xA2, 66), (0xA3, 84), (0xA4, 104), (0xA5, 125)],
    1: [(0x78, 16), (0x79, 26), (0x7A, 38), (0x7B, 52), (0x86, 70), (0x87, 92)],
}
# Stock graphics kept as-is for low-rise neighbourhoods
# Rubble ground cover, redrawn as beach sand (plain, umbrellas, palms, surfboards)
BEACH_TILES = [0x01, 0x02, 0x02, 0x03, 0x04]
# green ground: tropical art (tools/terrain_art.py) redraws these two 1x1 objects as grass
LAWN_PALMS = 0x0D   # small park
LAWN = 0xDB         # statue
LAWNS = (LAWN_PALMS, LAWN)
# a tree slot redrawn as houses (houses.hillside_scene): homes on slopes, where
# SimCity allows trees but not buildings
HILL_HOMES = 0x07
# light residential: redrawn as Hawaiian homes by houses.py
STOCK_HOMES = [0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77]
# hand-modelled landmarks at fixed tiles: (slot, (x, y), n, name, OSM name to keep out of the
# automatic landmark pass)
# UH Manoa campus blocks (parks.campus_block_scene), tiled over the campus in place of houses
CAMPUS_SLOTS = [0xB9, 0xBA, 0xBB, 0xBC]
CAMPUS_NAMES = ["UH Lecture Halls", "UH Science Labs", "UH Residence Halls", "UH Hawaiian Studies"]
# (slot, (x, y), n, name, OSM name kept out of the landmark pass or None, scene: houses/parks.py)
SPECIAL = [
    (0xF7, (44, 85), 2, "St. Augustine by the Sea", "St. Augustine By the Sea Catholic Church", "church"),
    (0xC1, (56, 85), 3, "Honolulu Zoo", None, "zoo_gate"),             # entrance off Kapahulu Ave
    (0xC0, (60, 81), 3, "Honolulu Zoo Savanna", None, "zoo_savanna"),
    (0xBF, (62, 86), 3, "Waikiki Shell", "Waikiki Shell", "shell"),
    (0x9F, (62, 99), 2, "Waikiki Aquarium", None, "aquarium"),          # between Kalakaua and the reef
    (0xBE, (20, 36), 3, "UH Athletics", "Clarence T.C. Ching Athletics Complex", "uh_athletics"),
    (0xBD, (9, 28), 3, "UH Manoa", None, "uh_campus"),                  # Varney Circle, Campus Center
]
# Ala Wai Small Boat Harbor: SimCity marinas (3x3, redrawn by houses.marina_scene).
# build_city turns these harbour tiles into sea-level land, as the marina sprite
# draws its own water and docks. The basin is laid out by hand (HARBOUR_* below):
# two rows of marinas, an open entrance basin, the channel along Magic Island
# (x 0-1) and the harbour's east promenade (x 11) below the Prince Waikiki (9, 89).
MARINA = 0xF8
# (with geo.SHIFT_X = 14 the harbour itself is off the map; only the beach east of it remains)
MARINAS = []         # must stay empty while terrain_art.CANAL_ID borrows the marina slot
HARBOUR_WATER = [(0, 96, 8, 101)]    # (x0, y0, x1, y1), end-exclusive
HARBOUR_LAND = []
HARBOUR_BEACH = [(0, 95, 8, 96)]     # Kahanamoku Beach: one clean strip of sand
TIDY = (0, 84, 16, 104)        # stray islets in this box are drowned
STOCK_SHOPS = [0x7D, 0x7E, 0x80, 0x81]

ZONE_OF = {}
for _id in list(range(0x70, 0x7C)) + list(range(0x8C, 0x94)) + list(range(0xAE, 0xB2)):
    ZONE_OF[_id] = 2      # dense residential
for _id in list(range(0x7C, 0x84)) + list(range(0x94, 0x9E)) + list(range(0xB2, 0xBC)):
    ZONE_OF[_id] = 4      # dense commercial
for _id in list(range(0x84, 0x88)) + list(range(0x9E, 0xA6)) + list(range(0xBC, 0xC2)):
    ZONE_OF[_id] = 6      # dense industrial
for _id in STOCK_HOMES:
    ZONE_OF[_id] = 1
for _id in STOCK_SHOPS:
    ZONE_OF[_id] = 3

LANDMARK_MIN_H = 35.0
BIG_LANDMARK_H = 80.0
# famous low-rise landmarks that always get their own sprite
FORCE_NAMES = ["Royal Hawaiian Hotel", "Moana Hotel", "Kaimana Beach Hotel"]
GENERIC_MIN_H = 13.0


def entity_score(e):
    return e["h"] * math.sqrt(max(e["poly"].area, 0.05))


def window_score(e, x, y, n):
    w = box(x, y, x + n, y + n)
    pieces = e["parts"] or [{"poly": e["poly"], "h": e["h"]}]
    return sum(w.intersection(p["poly"]).area * (p["h"] or e["h"]) for p in pieces)


def place(grid, entities, seed=1):
    rng = random.Random(seed)
    land = (grid["land"] >= 0.5) & (grid["water"] < 0.5)
    roads = (grid["roads"] > 0) & land
    occupied = ~land | roads
    # big landmarks may absorb a few minor-street tiles (hotel driveways, lanes)
    claimable = roads & (grid["roads"] <= 2)
    claimed = np.zeros_like(roads)
    placements = []
    special_slots = {s[0] for s in SPECIAL} | set(CAMPUS_SLOTS)
    free_slots = {n: [s for s in v if s not in special_slots] for n, v in UNIQUE_SLOTS.items()}

    def free(x, y, n, may_claim=False):
        if not (0 <= x and 0 <= y and x + n <= N and y + n <= N):
            return False
        occ = occupied[x:x + n, y:y + n]
        if not may_claim:
            return not occ.any()
        soft = claimable[x:x + n, y:y + n] & ~claimed[x:x + n, y:y + n]
        return not (occ & ~soft).any() and (occ & soft).sum() <= n

    # 0) hand-modelled landmarks (drawn by houses.py); their roads become church grounds
    for slot, (x, y), n, name, _, scene in SPECIAL:
        claimed[x:x + n, y:y + n] |= roads[x:x + n, y:y + n]
        occupied[x:x + n, y:y + n] = True
        placements.append({"x": x, "y": y, "n": n, "xbld": slot, "zone": 0, "kind": "special", "name": name,
                           "scene": scene})
    for x, y in MARINAS:
        claimed[x:x + 3, y:y + 3] |= roads[x:x + 3, y:y + 3]
        occupied[x:x + 3, y:y + 3] = True
        placements.append({"x": x, "y": y, "n": 3, "xbld": MARINA, "zone": 0, "kind": "stock",
                           "name": "Ala Wai Harbor"})
    special_osm = {s[4] for s in SPECIAL if s[4]}
    entities = [e for e in entities if e["name"] not in special_osm]

    # 1) landmarks
    forced = [e for name in FORCE_NAMES for e in entities if e["name"] == name][:len(FORCE_NAMES)]
    forced_ids = {id(e) for e in forced}
    # famous low-rises rank as if they were 70 m tall, so the big towers next to
    # them still get first pick of space
    cands = sorted(forced + [e for e in entities if e["h"] >= LANDMARK_MIN_H and id(e) not in forced_ids],
                   key=lambda e: entity_score(e) * (max(1.0, 70 / e["h"]) if id(e) in forced_ids else 1.0),
                   reverse=True)
    landmarks = []
    for e in cands:
        if not any(free_slots.values()):
            break
        b = e["poly"].bounds
        ext = max(b[2] - b[0], b[3] - b[1])
        n_target = max(1, min(3, int(round(ext - 0.2))))
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        done = False
        big = e["h"] >= BIG_LANDMARK_H or id(e) in forced_ids
        for n in range(n_target, 0, -1):
            if not free_slots.get(n):
                continue
            best = None
            for x in range(int(math.floor(cx - n / 2)) - 1, int(math.floor(cx - n / 2)) + 2):
                for y in range(int(math.floor(cy - n / 2)) - 1, int(math.floor(cy - n / 2)) + 2):
                    if not free(x, y, n, may_claim=big and n > 1):
                        continue
                    s = window_score(e, x, y, n) - 0.05 * e["h"] * occupied[x:x + n, y:y + n].sum()
                    if best is None or s > best[0]:
                        best = (s, x, y)
            need = 0.25 * e["h"] * min(e["poly"].area, n * n)
            if best and (best[0] > need or (id(e) in forced_ids and best[0] > 0)):
                _, x, y = best
                slot = free_slots[n].pop(0)
                claimed[x:x + n, y:y + n] |= roads[x:x + n, y:y + n]
                occupied[x:x + n, y:y + n] = True
                p = {"x": x, "y": y, "n": n, "xbld": slot, "zone": ZONE_OF[slot], "kind": "landmark",
                     "name": e["name"] or "Waikiki Tower", "entity": e}
                placements.append(p)
                landmarks.append(p)
                done = True
                break
        if not done:
            continue

    # 1b) the UH Manoa campus: 3x3 campus blocks wherever they fit
    campus = grid.get("campus", np.zeros((N, N), dtype=bool)) > 0
    for x in range(N - 2):
        for y in range(N - 2):
            if campus[x:x + 3, y:y + 3].all() and free(x, y, 3):
                # a seeded mix, so the four kinds don't line up; residence towers are the rarest
                k = random.Random(x * 1009 + y).choices(range(len(CAMPUS_SLOTS)), weights=[35, 30, 13, 22])[0]
                occupied[x:x + 3, y:y + 3] = True
                placements.append({"x": x, "y": y, "n": 3, "xbld": CAMPUS_SLOTS[k], "zone": 0, "kind": "campus",
                                   "scene": f"campus_{k}", "name": CAMPUS_NAMES[k]})

    # 2) generic towers: 2x2 blocks of tall tiles, then single tiles
    tall = grid["tall"]
    # residential neighbourhoods where OSM lacks footprints: inside a residential land-use
    # area, or on a residential street, away from parks, golf, beach and Diamond Head
    street = (grid["roads"] > 0) & (grid["roads"] <= 2)
    on_street = np.zeros_like(street)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        on_street |= np.roll(np.roll(street, dx, 0), dy, 1)
    neighbourhood = ((grid.get("resi", np.zeros_like(tall)) > 0.3) | on_street)         & (grid["park"] < 0.2) & (grid["golf"] < 0.2) & (grid["beach"] < 0.05) & ~grid["diamond_head"] & ~campus
    for x in range(N - 1):
        for y in range(N - 1):
            if free(x, y, 2) and (tall[x:x + 2, y:y + 2] >= 28).all():
                h = float(np.percentile(tall[x:x + 2, y:y + 2], 75))
                slot = min(GENERIC_SLOTS[2], key=lambda s: abs(s[1] - h))[0]
                occupied[x:x + 2, y:y + 2] = True
                placements.append({"x": x, "y": y, "n": 2, "xbld": slot, "zone": ZONE_OF[slot], "kind": "generic"})
    for x in range(N):
        for y in range(N):
            if occupied[x, y]:
                continue
            h = tall[x, y]
            if h >= GENERIC_MIN_H:
                slot = min(GENERIC_SLOTS[1], key=lambda s: abs(s[1] - h))[0]
            elif (grid["park"][x, y] > 0.5 or campus[x, y]) and h < GENERIC_MIN_H:
                continue        # park pavilions, zoo sheds and campus odds and ends stay lawn
            elif grid["bld"][x, y] > 0.02 or h > 0:      # one house on a 43 m tile is ~8%
                slot = rng.choice(STOCK_HOMES) if h < 9 else rng.choice(STOCK_SHOPS)
            elif neighbourhood[x, y]:
                slot = rng.choice(STOCK_HOMES)            # homes OSM hasn't mapped yet
            else:
                continue
            occupied[x, y] = True
            placements.append({"x": x, "y": y, "n": 1, "xbld": slot, "zone": ZONE_OF[slot], "kind": "generic"})

    # 3) vegetation on remaining land
    trees = []
    wat = grid["water"] >= 0.5
    shore = np.zeros_like(wat)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            shore |= np.roll(np.roll(wat, dx, 0), dy, 1)
    # vegetation may also go on slopes (which `land` excludes, since buildings can't);
    # it only avoids water, roads and tiles a building already took
    veg_ok = ~wat & ~(grid["roads"] > 0) & ~(occupied & land)
    for x in range(N):
        for y in range(N):
            if not veg_ok[x, y]:
                continue
            bc = grid["beach"][x, y]
            if land[x, y] and (bc > 0.15 or (bc > 0.01 and shore[x, y])) and grid["elev"][x, y] < 8:
                # Waikiki sand, drawn with the repurposed rubble graphics
                trees.append((x, y, rng.choice(BEACH_TILES)))
                continue
            r = rng.random()
            if campus[x, y]:
                # campus lawns under monkeypods
                t = rng.choice([0x0A, 0x0B]) if r < 0.45 else LAWN_PALMS if r < 0.6 else None
                if t is not None:
                    trees.append((x, y, t))
                continue
            if not land[x, y] and (grid["bld"][x, y] > 0.02 or grid.get("resi", grid["bld"])[x, y] > 0.3)                     and grid["park"][x, y] < 0.4 and not grid["diamond_head"][x, y]:
                trees.append((x, y, HILL_HOMES))          # houses on a hillside lot
                continue
            if grid.get("zoo", grid["park"] * 0)[x, y] > 0.4:
                # the rest of the zoo: dense tropical planting round the exhibits
                t = rng.choice([0x0A, 0x0B, 0x0C]) if r < 0.75 else LAWN_PALMS
            elif grid["diamond_head"][x, y]:
                # Diamond Head: mostly open, so the rim and crater read; low kiawe and
                # haole koa scrub on the flanks, a few shade trees on the crater floor
                flat = land[x, y]
                t = rng.choice([0x08, 0x09, 0x0A]) if flat and r < 0.3 else                     rng.choice([0x08, 0x09]) if not flat and r < 0.2 else None
            elif grid["park"][x, y] > 0.4:
                # open park lawn (the bare grass terrain) with scattered shade trees and palms,
                # like Kapiolani Park; build_city swaps lawns out where the ground isn't flat
                t = rng.choice([0x09, 0x0A, 0x0B]) if r < 0.22 else LAWN_PALMS if r < 0.32 else None
            elif grid["golf"][x, y] > 0.4:
                t = LAWN if r < 0.75 else rng.choice([0x08, 0x09]) if r < 0.9 else LAWN_PALMS
            elif grid["elev"][x, y] > 25:
                # Diamond Head, the crater and the ridges: kiawe and haole koa scrub
                t = rng.choice([0x08, 0x09, 0x0A, 0x0B, 0x0C]) if r < 0.7 else None
            else:
                # yards, vacant lots and gulches: palms and shade trees
                t = rng.choice([0x06, 0x08, 0x09, 0x0A]) if r < 0.6 else None
            if t is not None:
                trees.append((x, y, t))
    return placements, landmarks, trees, claimed
