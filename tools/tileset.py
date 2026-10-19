"""Render the custom building sprites for every SCURK slot used by the map.

Landmark sprites are literal 3D renders of the OSM footprints (and building:part
pieces) that fall inside the building's tiles. Generic slots get synthetic
Waikiki-style towers of a given height.

Run after build_city.py:  python tools/tileset.py
Writes build/sprites/<ID>_{L,M,S}.png, build/sprites/names.json and
build/tileset_sheet.png.
"""
import json
import math
import random
from pathlib import Path

from PIL import Image
from shapely.affinity import translate
from shapely.geometry import box, Polygon
from shapely.ops import unary_union

import garden
import geo
import houses
import materials as M
import osm_buildings
import parks
import placement
from render3d import Scene, soft

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
OUT = BUILD / "sprites"
ZOOMS = {"L": 32, "M": 16, "S": 8}

# Tower walls, all Perler beads: a few whites and creams, then a sunny resort mix of
# pastels (more colourful than the real skyline, on purpose)
TOWER_COLOURS = ["f8f8f8",   # White
                 "ebe1cd",   # Toasted Marshmallow
                 "e0dea9",   # Creme
                 "f6c966",   # Rich Butter
                 "edc591",   # Wheat
                 "eebab2",   # Peach
                 "f0aa93",   # Orange Cream
                 "ffb9b9",   # Flamingo
                 "f6b3dd",   # Light Pink
                 "e8c9d1",   # Frosted Lilac
                 "ad98d4",   # Lavender
                 "afe1e6",   # Robin's Egg
                 "93c8d4",   # Toothpaste
                 "86c3d6",   # Colonial Blue
                 "b4debd",   # Mint
                 "b5dca4",   # Glow in the Dark Green
                 "e1ee7d",   # Sherbet
                 "c3dad8"]   # Seafoam
WHITES = TOWER_COLOURS
GLASS = "323755"             # Midnight
# window tints, so towers differ in their glass as well as their walls
GLASSES = ["323755", "43658b", "067c81", "484780", "2b3f87", "5a7180"]   # Midnight, Denim, Parrot Green,
                                                                          # Iris, Dark Blue, Slate Blue

# Hand-tuned looks for famous buildings (matched by substring of the OSM name).
STYLES = {
    "Rainbow Tower": dict(wall="f4f2ee", balcony="ffffff", glass="607080", mosaic=True),
    "Royal Hawaiian Hotel": dict(wall="f0a6b6", glass="9a4e60", roof="e48c98", floor_h=3.8, win=0.45,
                                 bay=3.0, pier=0.4, balcony=None, lobby_h=0),
    "Royal Tower": dict(wall="ffb9b9", balcony="f8f8f8", glass="43658b"),
    "Moana Hotel": dict(wall="f8f8f8", glass="5a7180", roof="ccccc8", floor_h=3.8, win=0.45, bay=3.0,
                  balcony="ffffff", lobby_h=4),
    "Hyatt Regency": dict(wall="cbb497", glass="4a4038", balcony="e2d6be", roof="b0a08a"),
    "Sheraton Waikiki": dict(wall="ebe3cf", glass="566676", balcony="ffffff"),
    "Ka Laʻi": dict(curtain="6a86a4"),
    "Ritz-Carlton": dict(curtain="7d94aa"),
    "Grand Islander": dict(curtain="5f84a6"),
    "Ilikai": dict(wall="f2f2ee", balcony="ffffff", glass="405060"),
    "Hale Koa": dict(wall="f0eee6", balcony="ffffff", glass="4c5c6c"),
    "Halekulani": dict(wall="f4f2ea", glass="5a6a70", roof="606060", balcony="ffffff"),
    "Halepuna": dict(wall="f4f2ea", glass="5a6a70", balcony="ffffff"),
    "Alohilani": dict(wall="f2f2f0", glass="5a7a9a", balcony="ffffff"),
    "Hawaii Convention Center": dict(wall="ebe7dc", glass="4a8a90", roof="d8d8cc", floor_h=6.0, win=0.6),
    "Modern Honolulu": dict(wall="f4f4f0", glass="6684a2", win=0.62),
    "Waikiki Shell": dict(wall="f6f6f2", roof="f6f6f2", floor_h=20, win=0.0),
    "Kaimana Beach": dict(wall="f2f0e6", glass="6a7a8a", balcony="ffffff"),
}


def style_for(entity, rng):
    name = entity.get("name") or ""
    for key, st in STYLES.items():
        if key in name and not (key.startswith("Moana") and "Ala Moana" in name):
            return dict(st)
    t = entity["tags"]
    st = {"wall": t.get("building:colour") or rng.choice(TOWER_COLOURS), "glass": rng.choice(GLASSES)}
    if t.get("roof:colour"):
        st["roof"] = t["roof:colour"]
    if entity["h"] > 25 and t.get("building") in ("apartments", "hotel", "residential", "yes", None):
        st["balcony"] = "ffffff"
    return st


def wall_shader(st, h, vpx=None):
    """`vpx` (sprite px per metre, from the Scene) stretches the floor pattern so each
    window band is at least 2 px tall; at true scale a storey is ~1.3 px and the
    windows blur into grey."""
    floor_h = st.get("floor_h", 3.0)
    bay = st.get("bay", 4.0)
    win, pier, balcony = st.get("win", 0.5), st.get("pier", 0.35), st.get("balcony")
    if vpx and floor_h * vpx < 3.0:
        # too fine to draw true to scale: a SimCity-style grid instead, each storey
        # 1 px of dark window over 2 px of solid wall, windows split by 1 px piers
        floor_h, win = 3.0 / vpx, 0.34
        bay, pier = 3.0 / (vpx * 1.15), 0.34
        balcony = None                    # a white line would just wash the wall out
    if "curtain" in st:
        return M.curtain(st["curtain"], floor_h=max(3.3, floor_h), bay=max(3.0, bay))
    base = M.tower(wall=st.get("wall", "eeeae0"), glass=st.get("glass", GLASS),
                   floor_h=floor_h, win=win, bay=bay, pier=pier, balcony=balcony,
                   lobby_h=st.get("lobby_h", 6.0 if h > 20 else 0))
    if st.get("mosaic"):
        return M.mosaic_end(base, M.rainbow_art)
    return base


def roof_kit(sc, poly, z, wall, rng):
    """Rooftop clutter in the stock art's manner: a lift and stair housing in the wall
    colour, and a few grey air-conditioning boxes, all inside the roof outline."""
    from shapely.ops import polylabel
    if poly.area < 120:
        return
    minx, miny, maxx, maxy = poly.bounds
    span = min(maxx - minx, maxy - miny)
    c = polylabel(poly, tolerance=0.5)
    boxes = [(c.x, c.y, span * 0.22, 4.0, wall, "a0a5a5")]                   # lift housing
    for _ in range(rng.randint(2, 3)):
        boxes.append((c.x + rng.uniform(-.3, .3) * span, c.y + rng.uniform(-.3, .3) * span,
                      rng.uniform(1.3, 2.0), 1.6, "d7d7e3", "b1b5b2"))           # AC units
    for u, v, r, h, side, top in boxes:
        sq = Polygon([(u - r, v - r), (u + r, v - r), (u + r, v + r), (u - r, v + r)])
        if poly.buffer(-1.0).contains(sq):
            sc.add_prism(list(sq.exterior.coords), z, z + h, M.solid(side), M.roof(top))


@soft
def add_palms(scene, lot, blocked, rng, count):
    """Coconut palms on open ground of the lot (trunk + crown prisms)."""
    T = scene.T
    for _ in range(count * 4):
        if count <= 0:
            break
        u, v = rng.uniform(0.08, 0.92) * lot, rng.uniform(0.08, 0.92) * lot
        if any(p.buffer(1.5).contains(Polygon([(u, v), (u + .1, v), (u, v + .1)])) for p in blocked):
            continue
        h = rng.uniform(9, 14)
        trunk = [(u - .35, v - .35), (u + .35, v - .35), (u + .35, v + .35), (u - .35, v + .35)]
        scene.add_prism(trunk, 0, h, M.solid("8a6a48"), None)
        r = rng.uniform(2.6, 3.4)
        crown = [(u + r * math.cos(a), v + r * math.sin(a)) for a in [i * math.pi / 4 for i in range(8)]]
        scene.add_prism(crown, h - 1.2, h, M.solid("3f7a32"), M.roof("4c8a3a", "3a6a2c"))
        count -= 1


def landmark_scene(p, entities_by_id, all_entities, T, tile_px, rng_seed):
    rng = random.Random(rng_seed)
    n, x0, y0 = p["n"], p["x"], p["y"]
    win = box(x0, y0, x0 + n, y0 + n)
    lot = n * T
    sc = Scene(n, T, tile_px)
    main = entities_by_id[p["entity_id"]]

    # everything whose centre lies in the window is drawn (neighbours included)
    drawn = [main] + [e for e in all_entities
                      if e is not main and win.contains(e["poly"].representative_point())]
    blocked, heights, royal_parts = [], [0.0], []
    for e in drawn:
        st = style_for(e, random.Random(e["id"]))
        pieces = e["parts"] or [{"poly": e["poly"], "h": e["h"], "min_h": 0.0, "tags": e["tags"]}]
        for part in pieces:
            g = part["poly"].intersection(win)
            if g.is_empty:
                continue
            polys = [g] if g.geom_type == "Polygon" else [q for q in getattr(g, "geoms", []) if q.geom_type == "Polygon"]
            h = part.get("h") or e["h"]
            z0 = part.get("min_h", 0.0) or 0.0
            if h <= z0:
                continue
            pst = dict(st)
            if part.get("tags", {}).get("building:colour") and e["name"] not in STYLES:
                pst["wall"] = part["tags"]["building:colour"]
            for q in polys:
                q = q.simplify(0.02)
                local = translate(q, -x0, -y0)
                pts = [(u * T, v * T) for u, v in local.exterior.coords]
                if len(pts) < 4:
                    continue
                if e is main and (e.get("name") or "").startswith("Royal Hawaiian Hotel"):
                    royal_parts.append(Polygon(pts))
                    blocked.append(Polygon(pts))
                    continue
                roof_col = pst.get("roof", "b8b4ac")
                sc.add_prism(pts, z0, h, wall_shader(pst, h, sc.vpx), M.roof(roof_col))
                if h >= 20 and "curtain" not in pst and e["name"] not in ("Waikiki Shell",):
                    roof_kit(sc, Polygon(pts), h, pst.get("wall", "eeeae0"), rng)
                blocked.append(Polygon(pts))
                heights.append(h)
    garden.lawn(sc, lot)
    extra = []
    if royal_parts:
        royal_hawaiian(sc, royal_parts, sc.vpx, rng)
    if (main.get("name") or "").startswith("Moana") and blocked:   # not "Ala Moana"
        # the Banyan Courtyard: a huge banyan fills the open court of the U-shaped hotel
        built = unary_union(blocked)
        court = built.convex_hull.difference(built.buffer(0.5))
        if not court.is_empty:
            big = max(getattr(court, "geoms", [court]), key=lambda g: g.area)
            c = big.centroid if big.contains(big.centroid) else big.representative_point()
            r = max(30.0, math.sqrt(big.area / math.pi) * 1.8)
            add_banyan(sc, c.x, c.y, rng, r, top=30.0)    # over the historic wings (the tower is taller)
            extra.append(c.buffer(r))
    pave = garden.forecourt(sc, lot, blocked + extra, rng)
    garden.landscape(sc, lot, blocked, rng, amount=1.0, extra_blocked=extra + ([pave] if pave else []),
                     street_hedge=False)
    return sc


RH_PINK, RH_PINK_LIGHT, RH_TILE, RH_TILE_SIDE = "ffb9b9", "eebab2", "5a7180", "3c4949"   # Flamingo, Peach,
                                                                                         # Slate Blue, Charcoal
RH_DECK = "9cb9c7"          # the wings' flat roofs: pale blue-grey (Mist)


def stepped_roof(sc, poly, z, top, side, step=1.6, rise=0.8, steps=9):
    """A hip roof over any footprint, built as shrinking terraces (insets of the
    plan): at sprite scale the steps read as a pitched tile roof."""
    for k in range(steps):
        g = poly.buffer(-k * step, join_style=2) if k else poly
        for q in getattr(g, "geoms", [g]):
            if q.geom_type == "Polygon" and q.area > 2:
                sc.add_prism(list(q.simplify(0.2).exterior.coords), z + k * rise, z + (k + 1) * rise,
                             M.solid(side), M.roof(top, side))


def domed_tower(sc, u, v, w, z0, z1, rng, dome=True):
    """Square pink tower with an arcaded belfry, an octagonal drum and a dome."""
    sq = lambda r, cu=u, cv=v: [(cu - r, cv - r), (cu + r, cv - r), (cu + r, cv + r), (cu - r, cv + r)]
    sc.add_prism(sq(w / 2), z0, z1 - 4, M.awning_wall(RH_PINK, floor_h=4.2, bay=w / 2), M.roof(RH_PINK_LIGHT))
    sc.add_prism(sq(w / 2 + .4), z1 - 4, z1, M.awning_wall(RH_PINK, glass="4a2a34", awning=RH_PINK, floor_h=4.0,
                                                            bay=w / 3), M.roof(RH_PINK_LIGHT))
    if not dome:
        stepped_roof(sc, Polygon(sq(w / 2 + .6)), z1, RH_TILE, RH_TILE_SIDE, step=0.9, rise=0.9, steps=5)
        return
    oct_ = lambda r, zz0, zz1, col, top: sc.add_prism(
        [(u + r * math.cos(a), v + r * math.sin(a)) for a in [(i + .5) * math.pi / 4 for i in range(8)]],
        zz0, zz1, M.solid(col), M.roof(top, col))
    r = w * 0.46
    oct_(r, z1, z1 + 3, RH_PINK, RH_PINK_LIGHT)                    # drum
    zz = z1 + 3
    for f in (1.0, 0.97, 0.9, 0.78, 0.6, 0.36):                    # the dome, in rings
        oct_(r * f, zz, zz + r * 0.24, RH_PINK_LIGHT, "f8c8d0")
        zz += r * 0.24
    oct_(r * 0.16, zz, zz + 2.5, RH_PINK_LIGHT, "f8c8d0")           # lantern


def royal_hawaiian(sc, parts, vpx, rng):
    """The Royal Hawaiian (1927), "the Pink Palace of the Pacific": Spanish-Moorish
    pink stucco wings with green-awninged windows under teal tile hip roofs, a domed
    bell tower over the entrance and cupolas at the wing ends. Drawn ~1.6x tall so
    the storeys and awnings read."""
    h = 28.0
    floor_h = max(3.8, 3.0 / vpx)
    for poly in parts:
        sc.add_prism(list(poly.exterior.coords), 0, h, M.awning_wall(RH_PINK, floor_h=floor_h, bay=4.2),
                     M.roof(RH_DECK, "8c989e"))
        # low pink parapet around each flat roof
        ring = list(poly.simplify(0.3).exterior.coords)
        for (u0, v0), (u1, v1) in zip(ring, ring[1:]):
            d = math.hypot(u1 - u0, v1 - v0)
            if d < 0.5:
                continue
            nu, nv = -(v1 - v0) / d * .5, (u1 - u0) / d * .5
            sc.add_prism([(u0 + nu, v0 + nv), (u1 + nu, v1 + nv), (u1 - nu, v1 - nv), (u0 - nu, v0 - nv)],
                         h, h + 1.4, M.solid(RH_PINK), M.roof(RH_PINK_LIGHT))
    from shapely.ops import polylabel
    big = max(parts, key=lambda q: q.area)
    c = polylabel(big, tolerance=0.5)
    domed_tower(sc, c.x, c.y, 14.0, 0, h + 26, rng)
    # cupola towers at the wing ends toward the camera, left and right
    pts = [p for q in parts for p in q.exterior.coords]
    for key in (lambda p: p[0] - p[1], lambda p: p[1] - p[0]):
        u, v = max(pts, key=key)
        inward = big.centroid
        du, dv = inward.x - u, inward.y - v
        d = math.hypot(du, dv) or 1
        domed_tower(sc, u + du / d * 5, v + dv / d * 5, 8.0, 0, h + 6, rng, dome=False)   # slate hip roofs


@soft
def add_banyan(sc, u, v, rng, r=20.0, top=26.0):
    """The Moana's great banyan: a grove of aerial-root trunks under a vast, lumpy,
    domed canopy that fills the courtyard and spills over the wings around it."""
    for _ in range(14):
        a, d = rng.uniform(0, 2 * math.pi), rng.uniform(0, r * 0.55)
        tu, tv = u + d * math.cos(a), v + d * math.sin(a)
        w = rng.uniform(.6, 1.3)
        sc.add_prism([(tu - w, tv - w), (tu + w, tv - w), (tu + w, tv + w), (tu - w, tv + w)], 0, top * .5,
                     M.solid(rng.choice(["6e5a42", "7c664c", "5e4c38"])))
    z0 = top * 0.45
    garden.blob(sc, u, v, r, z0, z0 + 2.5, "2a5e28", "347030", rng, k=20)
    # a dome of overlapping foliage clumps: higher toward the middle, lit on top
    clumps = []
    for _ in range(46):
        a, d = rng.uniform(0, 2 * math.pi), r * math.sqrt(rng.uniform(0, 1)) * 0.92
        zt = top - (d / r) ** 2 * (top - z0 - 3) + rng.uniform(-1.5, 1.0)
        clumps.append((zt, u + d * math.cos(a), v + d * math.sin(a), rng.uniform(r * .16, r * .26)))
    for zt, cu, cv, lr in sorted(clumps):
        garden.blob(sc, cu, cv, lr, zt - 2.2, zt, "336c2e", rng.choice(["3e7c34", "468838", "52943e", "3a7630"]),
                    rng, k=9)


def generic_scene(n, h, T, tile_px, seed):
    rng = random.Random(seed)
    lot = n * T
    sc = Scene(n, T, tile_px)
    wall = TOWER_COLOURS[seed * 7 % len(TOWER_COLOURS)]
    st = {"wall": wall, "glass": GLASSES[seed % len(GLASSES)], "balcony": "ffffff" if rng.random() < 0.8 else None}
    garden.lawn(sc, lot)
    # slab tower, long axis alternating by slot
    if seed % 2:
        tw = [(lot * .22, lot * .30), (lot * .78, lot * .30), (lot * .78, lot * .62), (lot * .22, lot * .62)]
    else:
        tw = [(lot * .32, lot * .2), (lot * .64, lot * .2), (lot * .64, lot * .78), (lot * .32, lot * .78)]
    blocked = [Polygon(tw)]
    if h > 30:
        # podium with a planted pool deck; a garden strip around it at street level
        pod = [(lot * .16, lot * .14), (lot * .86, lot * .14), (lot * .86, lot * .84), (lot * .16, lot * .84)]
        sc.add_prism(pod, 0, 9, M.tower(wall="d8d2c4", glass="3c4650", floor_h=4.5, win=0.4), M.roof("a8a49c"))
        garden.roof_garden(sc, Polygon(pod).difference(Polygon(tw).buffer(1.5)), 9, rng)
        blocked = [Polygon(pod)]
    sc.add_prism(tw, 0, h, wall_shader(st, h, sc.vpx), M.roof("bcb8b0"))
    roof_kit(sc, Polygon(tw), h, wall, rng)
    pave = garden.forecourt(sc, lot, blocked, rng)
    garden.landscape(sc, lot, blocked, rng, amount=1.0, extra_blocked=[pave] if pave else [], street_hedge=False)
    return sc


BEACH_NAMES = {0x01: "Waikiki Beach", 0x02: "Beach Umbrellas", 0x03: "Beach Palms", 0x04: "Surfboard Rack"}


def beach_scene(variant, T, tile_px):
    """Beach props (repurposed rubble slot): towels, umbrellas, palms or surfboards.
    No ground of their own: they stand on the game's terrain, which terrain_art.py
    redraws as sand, so beach tiles match the land around them (slopes included)."""
    rng = random.Random(variant * 17)
    sc = Scene(1, T, tile_px)
    sc.soft_on = True             # props too small for outlines
    sc.min_cover = 0.2            # and too thin to survive the usual coverage test
    if variant == 0x01:
        for _ in range(4):
            u, v = rng.uniform(6, T - 8), rng.uniform(6, T - 8)
            col = rng.choice(["e04a3a", "f0c030", "3a7ad0", "f4f4f4", "f08a30"])
            sc.add_quad([(u, v, .05), (u + 1.8, v, .05), (u + 1.8, v + .9, .05), (u, v + .9, .05)],
                        (M.roof(col), None, 0), "roof")
    elif variant == 0x02:
        for _ in range(6):
            u, v = rng.uniform(5, T - 5), rng.uniform(5, T - 5)
            sc.add_prism([(u - .2, v - .2), (u + .2, v - .2), (u + .2, v + .2), (u - .2, v + .2)], 0, 2.6, M.solid("f0f0f0"))
            r = 1.8
            col = rng.choice(["e04a3a", "f0c030", "3a7ad0", "f4f4f4", "2aa070"])
            sc.add_prism([(u + r * math.cos(a), v + r * math.sin(a)) for a in [i * math.pi / 3 for i in range(6)]],
                         2.4, 2.9, M.solid(col), M.roof(col))
    elif variant == 0x03:
        add_palms(sc, T, [], rng, count=3)
    elif variant == 0x04:
        for i in range(5):
            u, v = 10 + i * 4.5, T * .45
            col = rng.choice(["e04a3a", "f0c030", "3a7ad0", "f4f4f4", "2aa070", "f08a30"])
            sc.add_prism([(u, v), (u + .9, v), (u + .9, v + .5), (u, v + .5)], 0, 3.2, M.solid(col), M.roof(col))
    return sc


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.load(open(BUILD / "placements.json"))
    T = data["T"]
    frame = geo.Frame()
    entities = osm_buildings.load(frame)
    by_id = {}
    for e in entities:
        by_id.setdefault(e["id"], e)

    jobs = {}  # xbld -> (kind, args, name)
    for p in data["placements"]:
        if p["kind"] == "landmark" and p["xbld"] not in jobs:
            jobs[p["xbld"]] = ("landmark", p, p.get("name", "Waikiki Tower"))
    for n, slots in placement.GENERIC_SLOTS.items():
        for xbld, h in slots:
            jobs.setdefault(xbld, ("generic", (n, h), f"Waikiki Tower {h}m"))

    for xbld in BEACH_NAMES:
        jobs[xbld] = ("beach", xbld, BEACH_NAMES[xbld])
    for xbld, name in houses.HOUSE_SLOTS.items():
        jobs[xbld] = ("house", xbld, name)
    jobs[placement.HILL_HOMES] = ("hillside", None, houses.HILL_HOMES_NAME)
    for p in data["placements"]:
        if p["kind"] in ("special", "campus"):   # hand-modelled: church, zoo, Shell, aquarium, UH
            jobs[p["xbld"]] = ("special", p["scene"], p["name"])
        elif p["xbld"] == placement.MARINA:
            jobs[p["xbld"]] = ("marina", None, houses.MARINA_NAME)

    names = {}
    sheet = []
    for xbld, (kind, args, name) in sorted(jobs.items()):
        for zk, px in ZOOMS.items():
            if kind == "landmark":
                sc = landmark_scene(args, by_id, entities, T, px, xbld)
            elif kind == "beach":
                sc = beach_scene(args, T, px)
            elif kind == "house":
                sc = houses.house_scene(args, T, px)
            elif kind == "special":
                sc = houses.church_scene(T, px) if args == "church" else parks.SCENES[args](T, px)
            elif kind == "hillside":
                sc = houses.hillside_scene(T, px)
            elif kind == "marina":
                sc = houses.marina_scene(T, px)
            else:
                sc = generic_scene(args[0], args[1], T, px, xbld)
            im = sc.render()
            im.save(OUT / f"{xbld:02X}_{zk}.png")
            if zk == "L":
                sheet.append((xbld, name, im))
        names[f"{xbld:02X}"] = name
        print(f"0x{xbld:02X} {kind:8s} {name}")
    json.dump(names, open(OUT / "names.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    contact_sheet(sheet)


def contact_sheet(items, cols=10):
    from PIL import ImageDraw
    cw = max(im.width for _, _, im in items) + 12
    ch = max(im.height for _, _, im in items) + 22
    rows = math.ceil(len(items) / cols)
    sheet = Image.new("RGBA", (cw * cols, ch * rows), (200, 214, 226, 255))
    d = ImageDraw.Draw(sheet)
    for i, (xbld, name, im) in enumerate(items):
        cx, cy = (i % cols) * cw, (i // cols) * ch
        sheet.alpha_composite(im, (cx + (cw - im.width) // 2, cy + ch - 20 - im.height))
        d.text((cx + 3, cy + ch - 18), f"{xbld:02X} {name[:16]}", fill=(20, 20, 20, 255))
    sheet.save(BUILD / "tileset_sheet.png")


if __name__ == "__main__":
    main()
