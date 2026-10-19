"""Tropical landscaping for the building sprites: hedges, flowering shrubs, palms
and shade trees.

Waikiki lots are planted: clipped hedges (mock orange, ixora, croton) along the
street and around building bases, bougainvillea, hibiscus, plumeria and bird of
paradise, coconut palms, and monkeypod or banyan shade trees. Everything is drawn
larger than life (shrubs a few metres across, flowers as bright tops), or it would
vanish at SimCity's 0.74 px per metre.
"""
import math

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

import materials as M
from render3d import soft

HEDGE, HEDGE_TOP = "1c753e", "007341"      # Dark Green, Shamrock
# bougainvillea (Fuchsia, Magenta), hibiscus (Hot Coral), plumeria (White, Yellow),
# bird of paradise (Orange), ixora (Bubblegum), and Plum
FLOWERS = ["dc44b7", "ff3851", "f8f8f8", "ecd800", "ed6120", "dd669b", "a24b9c", "f22a7b"]
LEAF = "1c753e"


@soft
def blob(sc, u, v, r, z0, z1, wall, top, rng, k=8):
    pts = [(u + r * math.cos(a) * rng.uniform(.82, 1.1), v + r * math.sin(a) * rng.uniform(.82, 1.1))
           for a in [i * 2 * math.pi / k for i in range(k)]]
    sc.add_prism(pts, z0, z1, M.solid(wall), M.roof(top, wall))


SHADOW = "1c753e"           # Dark Green: tree shadows on the lawn


def shadow(sc, u, v, r, z=0.0):
    """A tree's shadow: a dark disc on the ground, cast away from the light (toward -v, +u),
    so the canopy stands out from the grass the way stock trees do."""
    pts = [(u + r * .35 + r * math.cos(a), v - r * .45 + r * 0.8 * math.sin(a))
           for a in [i * math.pi / 6 for i in range(12)]]
    sc.add_quad([(a, b, z + .02) for a, b in pts], (M.roof(SHADOW, SHADOW), None, 0), "roof", -5e3 + z)


@soft
def palm(sc, u, v, rng, z=0.0, scale=1.0):
    h = rng.uniform(9, 14) * scale
    shadow(sc, u, v, 2.4 * scale, z)
    sc.add_prism([(u - .4, v - .4), (u + .4, v - .4), (u + .4, v + .4), (u - .4, v + .4)], z, z + h, M.solid("8a6a48"))
    blob(sc, u, v, rng.uniform(2.8, 3.6) * scale, z + h - 1.2, z + h, "3f7a32", "52943e", rng)


@soft
def shade_tree(sc, u, v, rng, z=0.0, r=None):
    """Monkeypod: short trunk, wide flat-topped umbrella canopy."""
    r = r or rng.uniform(4.5, 6.5)
    h = r * 0.9
    shadow(sc, u, v, r * 0.9, z)
    sc.add_prism([(u - .6, v - .6), (u + .6, v - .6), (u + .6, v + .6), (u - .6, v + .6)], z, z + h, M.solid("6e5a42"))
    blob(sc, u, v, r, z + h - .5, z + h + r * 0.35, "2f6a2c", "3f8034", rng, k=10)
    blob(sc, u - r * .15, v + r * .1, r * .6, z + h + r * .3, z + h + r * .55, "3f8034", "5a9c44", rng)


@soft
def shrub(sc, u, v, rng, z=0.0, r=None, flower=None):
    """A flowering shrub: dark leaves, the top a mass of colour."""
    r = r or rng.uniform(1.8, 2.8)
    col = flower or rng.choice(FLOWERS)
    blob(sc, u, v, r, z, z + r * 0.9, LEAF, col, rng, k=7)


@soft
def hedge_line(sc, a, b, z=0.0, w=1.4, h=1.8):
    (u0, v0), (u1, v1) = a, b
    du, dv = u1 - u0, v1 - v0
    ln = math.hypot(du, dv) or 1
    nu, nv = -dv / ln * w / 2, du / ln * w / 2
    sc.add_prism([(u0 + nu, v0 + nv), (u1 + nu, v1 + nv), (u1 - nu, v1 - nv), (u0 - nu, v0 - nv)], z, z + h,
                 M.solid(HEDGE), M.roof(HEDGE_TOP, HEDGE))


@soft
def landscape(sc, lot, buildings, rng, amount=1.0, extra_blocked=(), street_hedge=True, z=0.0):
    """Plant a lot of side `lot` metres around `buildings` (shapely polygons, scene metres)."""
    # a clipped hedge hugging each building's base
    for b in buildings:
        if b.area < 30:
            continue
        ring = b.buffer(1.6, join_style=2).simplify(0.3)
        for g in getattr(ring, "geoms", [ring]):
            if g.geom_type == "Polygon":
                sc.add_prism(list(g.exterior.coords), z, z + 1.6, M.solid(HEDGE), M.roof(HEDGE_TOP, HEDGE), bias=-0.2)
    taken = [b.buffer(2.0) for b in buildings] + list(extra_blocked)
    # hedges along the two street sides facing the camera, with a gap for the drive
    if street_hedge:
        gap = rng.uniform(0.3, 0.6) * lot
        for a, b in (((1, lot - 1), (gap - 4, lot - 1)), ((gap + 4, lot - 1), (lot - 1, lot - 1)),
                     ((lot - 1, 1), (lot - 1, lot * .45)), ((lot - 1, lot * .55), (lot - 1, lot - 1))):
            seg = box(min(a[0], b[0]) - 1, min(a[1], b[1]) - 1, max(a[0], b[0]) + 1, max(a[1], b[1]) + 1)
            if not any(t.intersects(seg) for t in taken) and math.dist(a, b) > 3:
                hedge_line(sc, a, b, z)
        taken.append(box(0, lot - 2.5, lot, lot))
        taken.append(box(lot - 2.5, 0, lot, lot))
    blocked = unary_union(taken) if taken else None

    def spot(r, margin=2.0):
        for _ in range(30):
            u, v = rng.uniform(margin + r, lot - margin - r), rng.uniform(margin + r, lot - margin - r)
            c = Point(u, v).buffer(r)
            if blocked is None or not blocked.intersects(c):
                return u, v, c
        return None

    area = lot * lot
    plan = [("tree", 5.5)] * max(0, round(area / 1400 * amount)) + \
           [("palm", 3.0)] * max(1, round(area / 450 * amount)) + \
           [("shrub", 2.4)] * max(2, round(area / 160 * amount))
    for kind, r in plan:
        s = spot(r)
        if s is None:
            continue
        u, v, c = s
        if kind == "tree":
            shade_tree(sc, u, v, rng, z)
        elif kind == "palm":
            palm(sc, u, v, rng, z)
            c = Point(u, v).buffer(1.0)          # shrubs may grow under palms
        else:
            shrub(sc, u, v, rng, z)
        blocked = c if blocked is None else blocked.union(c)


CAR_COLOURS = ["f8f8f8", "f8f8f8", "a0a5a5", "ff3851", "2b3f87", "ecd800", "323755"]   # beads


@soft
def forecourt(sc, lot, blocked, rng, z=0.0):
    """A paved drop-off by the street with a few parked cars, in place of a street hedge
    (the stock art's lots have paving and cars). Returns the paved polygon, or None."""
    taken = unary_union(blocked) if blocked else None
    for _ in range(12):
        w, d = rng.uniform(.35, .55) * lot, 7.0
        if rng.random() < .5:                                       # along the +v street
            u0 = rng.uniform(2, lot - w - 2)
            pave = box(u0, lot - d, u0 + w, lot - .5)
            along_u = True
        else:                                                       # along the +u street
            v0 = rng.uniform(2, lot - w - 2)
            pave = box(lot - d, v0, lot - .5, v0 + w)
            along_u = False
        if taken is None or not taken.intersects(pave.buffer(0.8)):
            break
    else:
        return None
    sc.add_quad([(a, b, z + .03) for a, b in pave.exterior.coords[:-1]], (M.ground("paving"), None, 0), "roof", -6e3)
    minx, miny, maxx, maxy = pave.bounds
    span = (maxx - minx) if along_u else (maxy - miny)
    for i in range(int(span // 6.0)):
        if rng.random() < .3:
            continue
        a = (minx if along_u else miny) + 1.5 + i * 6.0
        if along_u:
            q = [(a, miny + 1.6), (a + 4.4, miny + 1.6), (a + 4.4, miny + 3.6), (a, miny + 3.6)]
        else:
            q = [(minx + 1.6, a), (minx + 3.6, a), (minx + 3.6, a + 4.4), (minx + 1.6, a + 4.4)]
        col = rng.choice(CAR_COLOURS)
        sc.add_prism(q, z, z + 1.5, M.solid(col), M.roof(col))
    return pave


def lawn(sc, lot, z=0.0):
    sc.add_quad([(0, 0, z), (lot, 0, z), (lot, lot, z), (0, lot, z)], (M.ground("lawn"), None, 0), "roof", -1e4)


@soft
def roof_garden(sc, poly, z, rng):
    """Pool deck on a podium roof: a pool, palms in planters and flowering pots."""
    minx, miny, maxx, maxy = poly.bounds
    w, d = maxx - minx, maxy - miny
    pu, pv = minx + w * .55, miny + d * .55
    pool = [(pu, pv), (pu + w * .3, pv), (pu + w * .3, pv + d * .25), (pu, pv + d * .25)]
    sc.add_quad([(a, b, z + .05) for a, b in pool], (M.ground("pool"), None, 0), "roof", 0.1)
    for fu, fv in ((.12, .85), (.88, .12), (.9, .9), (.15, .2)):
        u, v = minx + w * fu, miny + d * fv
        if poly.contains(Point(u, v)):
            palm(sc, u, v, rng, z, scale=0.9)
            shrub(sc, u + 2, v - 1.5, rng, z, r=1.6)
