"""Hawaiian homes for the eight light-residential slots, and St. Augustine by the Sea.

The houses follow Honolulu's residential vernacular:
  * the "Hawaiian-style" bungalow (1920s-30s Kaimuki, Kapahulu): one storey on posts,
    a steep double-pitched hip roof (the Dickey roof), deep eaves and an entry lanai;
  * plantation cottages: small single-wall houses with a plain hip roof;
  * post-war ranch houses and newer two-storey homes, carports, ohana units and
    three-storey walk-up apartments.
Roofs are mostly white or light grey (corrugated metal and "cool roof" coatings,
which cut heat gain), with a few green or rust corrugated roofs and some solar
panels. Walls are white and pastels. Lots are green, with a shade tree or palms.

A SimCity 1x1 tile is 43 m here, so each tile is a small cluster of lots; houses are
drawn about 1.5x true size so they read at SimCity's zoom levels.
"""
import math
import random

import numpy as np

import garden
import materials as M
from render3d import LIGHT, Scene, soft

HOUSE_SLOTS = {
    0x70: "Kaimuki Bungalows",
    0x71: "Plantation Cottages",
    0x72: "Bungalows & Monkeypod",
    0x73: "Ranch Homes",
    0x74: "Two-Storey Homes",
    0x75: "House & Ohana",
    0x76: "Walk-up Apartments",
    0x77: "Kapahulu Homes",
}
CHURCH_NAME = "St. Augustine by the Sea"

# bright plantation pastels: sunny yellow, teal, coral, sky blue, lime, pink, lavender, mint
# Perler beads: Rich Butter, Toothpaste, Coral, Colonial Blue, Sour Apple, Light Pink,
# Lavender, Mint, Apricot, White
WALLS = ["f6c966", "93c8d4", "f98878", "86c3d6", "b0d169", "f6b3dd", "ad98d4", "b4debd", "ffa967",
         "f8f8f8"]
ROOF_WHITE = ["f8f8f8", "f8f8f8", "d7d7e3"]     # White, Violet Frost
ROOF_OTHER = ["b1b5b2", "1c753e", "8c372c"]     # Light Grey, Dark Green and Rust corrugated
TRIM = "f8f8f8"
SCALE = 1.5


def roof_colour(rng):
    return rng.choice(ROOF_WHITE)        # white roofs throughout (the colour is on the walls)


def lit(col, normal3):
    """Flat shader for a sloped roof face, lit by its 3D normal."""
    c = M.color(col)
    n = np.array(normal3, dtype=float)
    n /= np.linalg.norm(n)
    k = 0.80 + 0.30 * max(0.0, n[0] * LIGHT[0] + n[1] * LIGHT[1]) + 0.12 * n[2]

    def fn(u, v, z, P):
        out = np.empty((len(u), 4), dtype=np.float32)
        out[:, :3] = np.clip(c * k, 0, 255)
        out[:, 3] = 255
        return out
    return fn


def face(sc, pts, col, bias=0.0):
    p0, p1, p2 = (np.array(p, dtype=float) for p in pts[:3])
    n = np.cross(p1 - p0, p2 - p0)
    if n[2] < 0:
        n = -n
    sc.add_quad(pts, (lit(col, n), None, 0), "roof", bias)


def hip_roof(sc, u0, v0, u1, v1, z, rise, col, bias=0.0):
    """Plain hip roof over a rectangle: ridge along the long side."""
    du, dv = u1 - u0, v1 - v0
    h = min(du, dv) / 2
    zt = z + rise
    if du >= dv:
        a, b = (u0 + h, v0 + h, zt), (u1 - h, v0 + h, zt)
        face(sc, [(u0, v0, z), (u1, v0, z), b, a], col, bias)
        face(sc, [(u1, v1, z), (u0, v1, z), a, b], col, bias)
        face(sc, [(u1, v0, z), (u1, v1, z), b], col, bias)
        face(sc, [(u0, v1, z), (u0, v0, z), a], col, bias)
    else:
        a, b = (u0 + h, v0 + h, zt), (u0 + h, v1 - h, zt)
        face(sc, [(u0, v1, z), (u0, v0, z), a, b], col, bias)
        face(sc, [(u1, v0, z), (u1, v1, z), b, a], col, bias)
        face(sc, [(u0, v0, z), (u1, v0, z), a], col, bias)
        face(sc, [(u1, v1, z), (u0, v1, z), b], col, bias)


def dickey_roof(sc, u0, v0, u1, v1, z, col, bias=0.0):
    """Double-pitched Hawaiian hip roof: a gentle flared skirt, then a steep high hip."""
    w = min(u1 - u0, v1 - v0)
    i = w * 0.22
    z1 = z + w * 0.07
    for pts in ([(u0, v0, z), (u1, v0, z), (u1 - i, v0 + i, z1), (u0 + i, v0 + i, z1)],
                [(u1, v0, z), (u1, v1, z), (u1 - i, v1 - i, z1), (u1 - i, v0 + i, z1)],
                [(u1, v1, z), (u0, v1, z), (u0 + i, v1 - i, z1), (u1 - i, v1 - i, z1)],
                [(u0, v1, z), (u0, v0, z), (u0 + i, v0 + i, z1), (u0 + i, v1 - i, z1)]):
        face(sc, pts, col, bias)
    hip_roof(sc, u0 + i, v0 + i, u1 - i, v1 - i, z1, w * 0.26, col, bias)


def walls(sc, u0, v0, u1, v1, z0, z1, col, rng, glass="4a5a66"):
    sc.add_prism([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], z0, z1,
                 M.tower(wall=col, glass=glass, floor_h=max(2.8, (z1 - z0)), win=0.42, bay=3.2, pier=0.45,
                         lobby_h=0), None)


def solar(sc, u0, v0, u1, v1, z):
    """Dark solar panels on the lit (+v) side of a roof."""
    sc.add_quad([(u0, v0, z), (u1, v0, z), (u1, v1, z), (u0, v1, z)], (M.roof("26344a", "26344a"), None, 0), "roof", 0.4)


@soft
def tree(sc, u, v, rng, big=False):
    r = rng.uniform(3.2, 4.2) * (1.6 if big else 1.0) * SCALE
    h = rng.uniform(4, 5.5) * (1.3 if big else 1.0) * SCALE
    sc.add_prism([(u - .5, v - .5), (u + .5, v - .5), (u + .5, v + .5), (u - .5, v + .5)], 0, h, M.solid("7a5a3c"))
    crown = [(u + r * math.cos(a), v + r * math.sin(a)) for a in [k * math.pi / 5 for k in range(10)]]
    sc.add_prism(crown, h, h + r * 0.55, M.solid("3c6e30"), M.roof("4c8238", "3c6a2c"))


@soft
def palm(sc, u, v, rng):
    h = rng.uniform(8, 11) * SCALE
    sc.add_prism([(u - .35, v - .35), (u + .35, v - .35), (u + .35, v + .35), (u - .35, v + .35)], 0, h, M.solid("8a6a48"))
    r = rng.uniform(2.6, 3.2) * SCALE
    crown = [(u + r * math.cos(a), v + r * math.sin(a)) for a in [k * math.pi / 4 for k in range(8)]]
    sc.add_prism(crown, h - 1.0, h, M.solid("3f7a32"), M.roof("4c8a3a", "3a6a2c"))


def ground(sc, T):
    sc.add_quad([(0, 0, 0), (T, 0, 0), (T, T, 0), (0, T, 0)], (M.ground("lawn"), None, 0), "roof", -1e4)


def drive(sc, u0, v0, u1, v1):
    sc.add_quad([(u0, v0, .05), (u1, v0, .05), (u1, v1, .05), (u0, v1, .05)], (M.ground("b8b4aa"), None, 0), "roof", -10)


def bungalow(sc, u, v, rng, w=11, d=9, dickey=True, posts=0.8, solar_ok=True):
    w, d = w * SCALE, d * SCALE
    z0, z1 = posts, posts + 3.6 * SCALE
    col = rng.choice(WALLS)
    if posts:
        sc.add_prism([(u, v), (u + w, v), (u + w, v + d), (u, v + d)], 0, posts, M.solid("6a645c"))
    walls(sc, u, v, u + w, v + d, z0, z1, col, rng)
    # entry lanai on the street (+v) side
    lw = w * 0.4
    lu = u + rng.uniform(0.1, 0.5) * w
    sc.add_prism([(lu, v + d), (lu + lw, v + d), (lu + lw, v + d + 2.2 * SCALE), (lu, v + d + 2.2 * SCALE)],
                 0, z0 + 0.15, M.solid("c8c0b0"), M.roof("b4aa98"))
    e = 0.45 * SCALE                                  # eaves (kept short so the walls show)
    rc = roof_colour(rng)
    if dickey:
        dickey_roof(sc, u - e, v - e, u + w + e, v + d + 2.2 * SCALE + e * .3, z1, rc)
    else:
        hip_roof(sc, u - e, v - e, u + w + e, v + d + e, z1, min(w, d) * 0.22, rc)
    if solar_ok and rc in ROOF_WHITE and rng.random() < 0.3:
        solar(sc, u + w * .25, v + d * .55, u + w * .7, v + d * .85, z1 + min(w, d) * 0.2)


def two_storey(sc, u, v, rng, w=12, d=10):
    w, d = w * SCALE, d * SCALE
    col = rng.choice(WALLS)
    z1 = 6.4 * SCALE
    walls(sc, u, v, u + w, v + d, 0, z1, col, rng)
    sc.add_prism([(u + w * .1, v + d), (u + w * .6, v + d), (u + w * .6, v + d + 2 * SCALE), (u + w * .1, v + d + 2 * SCALE)],
                 2.8 * SCALE, 3.0 * SCALE, M.solid(TRIM), M.roof(TRIM))   # upper lanai slab
    e = 0.45 * SCALE
    rc = roof_colour(rng)
    hip_roof(sc, u - e, v - e, u + w + e, v + d + e, z1, min(w, d) * 0.22, rc)
    if rc in ROOF_WHITE and rng.random() < 0.45:
        solar(sc, u + w * .2, v + d * .55, u + w * .75, v + d * .9, z1 + min(w, d) * 0.18)


def carport(sc, u, v, rng, w=6, d=6):
    w, d = w * SCALE, d * SCALE
    h = 2.6 * SCALE
    for pu, pv in ((u, v), (u + w, v), (u, v + d), (u + w, v + d)):
        sc.add_prism([(pu - .2, pv - .2), (pu + .2, pv - .2), (pu + .2, pv + .2), (pu - .2, pv + .2)], 0, h, M.solid(TRIM))
    sc.add_prism([(u, v), (u + w, v), (u + w, v + d), (u, v + d)], h, h + 0.3, M.solid(TRIM), M.roof(rng.choice(ROOF_WHITE)))
    drive(sc, u, v + d, u + w, 43.4)


def walkup(sc, T, rng):
    """Three-storey walk-up: flat white roof, open walkway on the street side."""
    u0, v0, u1, v1 = T * .14, T * .18, T * .86, T * .62
    col = rng.choice(["f2c650", "6cc4b4", "ec8c74", "86b4e4"])
    sc.add_prism([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], 0, 9.6 * SCALE,
                 M.tower(wall=col, glass="44525c", floor_h=3.2 * SCALE, win=0.45, bay=3.6, pier=0.4,
                         balcony="ffffff", lobby_h=0), M.roof("f2f2ee", "d8d8d4"))
    sc.add_prism([(u0 + 2, v1), (u1 - 2, v1), (u1 - 2, v1 + 1.6 * SCALE), (u0 + 2, v1 + 1.6 * SCALE)],
                 0, 9.0 * SCALE, M.tower(wall="ffffff", glass="9aa4aa", floor_h=3.2 * SCALE, win=0.55, bay=2.0,
                                          pier=0.2, lobby_h=0), M.roof("f4f4f0"))
    drive(sc, u0, v1 + 2 * SCALE, u1, T)


def house_scene(slot, T, tile_px):
    rng = random.Random(slot * 101)
    sc = Scene(1, T, tile_px)
    ground(sc, T)
    q = T / 2
    v = slot - 0x70
    if v == 0:      # three Kaimuki bungalows and a palm
        for (u, vv) in ((2, 2), (q + 2, 3), (3, q + 3)):
            bungalow(sc, u, vv, rng, w=rng.uniform(9, 11), d=rng.uniform(8, 9))
        palm(sc, q + 14, q + 15, rng)
    elif v == 1:    # four small plantation cottages on posts, plain hip roofs
        for (u, vv) in ((2, 2), (q + 3, 2), (2, q + 3), (q + 3, q + 3)):
            bungalow(sc, u, vv, rng, w=rng.uniform(7, 8.5), d=rng.uniform(6, 7), dickey=False, posts=1.0, solar_ok=False)
    elif v == 2:    # two bungalows shaded by a big monkeypod
        bungalow(sc, 2, 3, rng, w=11, d=9)
        bungalow(sc, q + 4, q + 2, rng, w=10, d=8.5)
        tree(sc, q + 8, 9, rng, big=True)
    elif v == 3:    # two long, low ranch houses with carports
        for vv in (2, q + 2):
            bungalow(sc, 2, vv, rng, w=13, d=7.5, dickey=False, posts=0)
            carport(sc, 2 + 13 * SCALE + 1, vv + 1, rng, w=5, d=5)
    elif v == 4:    # two newer two-storey homes
        two_storey(sc, 2, 2, rng, w=11, d=9)
        two_storey(sc, q + 3, q + 3, rng, w=10, d=8.5)
        palm(sc, q + 12, 6, rng)
        tree(sc, 6, q + 12, rng)
    elif v == 5:    # main house with an ohana cottage behind
        bungalow(sc, 3, q + 2, rng, w=12, d=9)
        bungalow(sc, q + 6, 3, rng, w=7, d=6, dickey=False, posts=0.6, solar_ok=False)
        palm(sc, 6, 6, rng)
        palm(sc, q + 16, q + 14, rng)
    elif v == 6:    # walk-up apartments
        walkup(sc, T, rng)
        palm(sc, T * .08, T * .9, rng)
        palm(sc, T * .92, T * .9, rng)
    else:           # Kapahulu mix: a two-storey and two bungalows
        two_storey(sc, 2, 2, rng, w=10, d=9)
        bungalow(sc, q + 3, 3, rng, w=9, d=8)
        bungalow(sc, 4, q + 4, rng, w=10, d=8.5)
        tree(sc, q + 12, q + 12, rng)
    yard(sc, T, rng, drive=v == 3)
    return sc


def yard(sc, T, rng, drive=False):
    """Front-yard planting: a clipped hedge along the street (+v) with a gap for the
    gate, and flowering shrubs (hibiscus, bougainvillea, plumeria) along the front
    and the side facing the camera."""
    if not drive:
        g = rng.uniform(.35, .6) * T
        garden.hedge_line(sc, (1.5, T - 1), (g - 2.5, T - 1), h=1.4)
        garden.hedge_line(sc, (g + 2.5, T - 1), (T - 1.5, T - 1), h=1.4)
    for _ in range(4):
        garden.shrub(sc, rng.uniform(3, T - 4), T - rng.uniform(3.5, 5.5), rng, r=rng.uniform(1.5, 2.1))
    for _ in range(2):
        garden.shrub(sc, T - rng.uniform(2.5, 4), rng.uniform(4, T - 6), rng, r=rng.uniform(1.4, 2.0))


# --- St. Augustine by the Sea ----------------------------------------------------------
CHURCH_GREEN = "56ba9f"         # Light Green
CHURCH_GREEN_LIGHT = "76c882"   # Pastel Green
CHURCH_WHITE = "f8f8f8"


def church_scene(T, tile_px):
    """St. Augustine by the Sea (1962), Ohua Ave at Kalakaua: a steep green A-frame
    with stepped green tiers down each side, rows of white fins, and a tall glass
    gable facing makai (+v, toward Kalakaua and the camera). Drawn 2x2 and larger
    than life so it stands out among the towers."""
    rng = random.Random(247)
    sc = Scene(2, T, tile_px)
    L = 2 * T
    T = L                  # the code below lays out the church on the whole 2x2 lot
    sc.add_quad([(0, 0, 0), (T, 0, 0), (T, T, 0), (0, T, 0)], (M.ground("b0aca2"), None, 0), "roof", -1e4)
    uc = T * 0.50
    hw = 18.0              # half-width of the main A-frame at its base
    v0, v1 = T * 0.10, T * 0.80
    zb, zr = 6.0, 60.0     # eave and ridge heights (exaggerated)
    # low white side wings under the tiers
    for side in (-1, 1):
        a, b = sorted((uc + side * hw, uc + side * (hw + 5.4)))
        sc.add_prism([(a, v0 + 1), (b, v0 + 1), (b, v1 - 1), (a, v1 - 1)], 0, zb, M.solid(CHURCH_WHITE), M.roof("e8e8e2"))
    # stepped green tiers down each side of the main roof
    for side in (-1, 1):
        for k in range(3):
            z = zb + k * 3.4
            out = hw + 5.4 - k * 2.6
            inn = out - 3.0
            a, b = sorted((uc + side * out, uc + side * inn))
            face(sc, [(a, v0 + 1, z + (0 if side > 0 else 1.2)), (b, v0 + 1, z + (1.2 if side > 0 else 0)),
                      (b, v1 - 1, z + (1.2 if side > 0 else 0)), (a, v1 - 1, z + (0 if side > 0 else 1.2))],
                 CHURCH_GREEN_LIGHT if k % 2 else CHURCH_GREEN, 0.1)
    # the main A-frame roof
    for side in (-1, 1):
        face(sc, [(uc + side * hw, v0, zb), (uc + side * hw, v1, zb), (uc, v1, zr), (uc, v0, zr)], CHURCH_GREEN, 0.2)
    # white fins marching down both sides
    n_fins = 11
    for side in (-1, 1):
        for i in range(n_fins):
            v = v0 + 2 + i * (v1 - v0 - 4) / (n_fins - 1)
            ub = uc + side * (hw + 6.0)
            ut = uc + side * (hw - 2.5)
            zt = zb + 15
            sc.add_quad([(ub, v - .6, 0), (ub, v + .6, 0), (ut, v + .6, zt), (ut, v - .6, zt)],
                        (M.solid(CHURCH_WHITE), (side, 0.0), 1.2), "wall", 0.6)
            sc.add_quad([(ub, v + .6, 0), (ut, v + .6, zt), (ut - side * 1.0, v + .6, zt), (ub - side * 1.0, v + .6, 0)],
                        (M.solid(CHURCH_WHITE), (0.0, 1.0), 1.0), "wall", 0.6)
    # makai gable: white frame and the tall glass wall
    sc.add_quad([(uc - hw - .8, v1 + .4, 0), (uc + hw + .8, v1 + .4, 0), (uc, v1 + .4, zr + 2.0)],
                (M.solid(CHURCH_WHITE), (0.0, 1.0), 2 * hw), "wall", 0.8)
    sc.add_quad([(uc - hw + 2.6, v1 + .9, 0), (uc + hw - 2.6, v1 + .9, 0), (uc, v1 + .9, zr - 5.0)],
                (M.curtain(glass="3e5a74", mullion="dfe6ea", floor_h=3.4, bay=2.4), (0.0, 1.0), 2 * hw), "wall", 0.9)
    # small flat-roofed hall at the front corner, a shade tree and palms along Kalakaua
    sc.add_prism([(T * .04, T * .86), (T * .24, T * .86), (T * .24, T * .97), (T * .04, T * .97)], 0, 6.0,
                 M.tower(wall="e4e2da", glass="3e5258", floor_h=6.0, win=0.4, bay=2.4, lobby_h=0), M.roof("c8c6be"))
    tree(sc, T * .86, T * .88, rng, big=True)
    for u in (T * .32, T * .50, T * .68):
        palm(sc, u, T * .95, rng)
    for u in (T * .28, T * .40, T * .58, T * .72):
        garden.shrub(sc, u, T * .91, rng, r=2.0)
    return sc


# --- hillside homes -------------------------------------------------------------------
HILL_HOMES_NAME = "Hillside Homes"


def hillside_scene(T, tile_px):
    """Houses on a sloping lot (Kaimuki, St. Louis Heights, Wilhelmina Rise). SimCity
    can't put buildings on slopes, but trees can stand anywhere, so this is drawn in
    a tree slot: two bungalows on posts and a shade tree, with no ground of their own,
    so the green hillside shows around them."""
    rng = random.Random(707)
    sc = Scene(1, T, tile_px)
    q = T / 2
    bungalow(sc, 3, 4, rng, w=10, d=8.5, posts=1.6, solar_ok=False)
    bungalow(sc, q + 3, q + 2, rng, w=9.5, d=8, dickey=False, posts=1.6, solar_ok=False)
    two_storey(sc, 4, q + 5, rng, w=9, d=8)
    tree(sc, q + 12, 7, rng)
    palm(sc, T - 4, T - 5, rng)
    return sc


# --- Ala Wai Harbor ----------------------------------------------------------------
MARINA_NAME = "Ala Wai Harbor"
DOCK = "b0916a"
HULLS = ["fafaf8", "fafaf8", "f4f2ea", "e8f0f4", "1e3c6c", "fafaf8"]
COVERS = ["2a5aa0", "1e7a8c", "c8483a", "2a5aa0", "e0c050"]


def boat(sc, u, v, rng, length=None, kind=None):
    """A boat in a slip, bow toward -u: sailboat (mast and sail cover), motor yacht or catamaran."""
    kind = kind or rng.choice(["sail", "sail", "sail", "motor", "cat"])
    L = (length or rng.uniform(9, 13)) * 1.4
    W = (5.0 if kind == "cat" else 3.4) * 1.4
    hull = rng.choice(HULLS) if kind != "cat" else "fafaf8"
    v0, v1 = v - W / 2, v + W / 2
    if kind == "cat":
        for vv in (v0, v1 - 1.4):
            sc.add_prism([(u, vv + .7), (u + L * .2, vv), (u + L, vv), (u + L, vv + 1.4), (u + L * .2, vv + 1.4)],
                         0, 1.2, M.solid(hull), M.roof(hull))
        sc.add_prism([(u + L * .3, v0), (u + L * .95, v0), (u + L * .95, v1), (u + L * .3, v1)], 1.2, 1.8,
                     M.solid("f2f2ee"), M.roof("eeeeea"))
        sc.add_prism([(u + L * .6, v0 + 1), (u + L * .9, v0 + 1), (u + L * .9, v1 - 1), (u + L * .6, v1 - 1)], 1.8, 3.2,
                     M.solid("ffffff"), M.roof("e8e8e4"))
    else:
        sc.add_prism([(u, v), (u + L * .3, v0), (u + L, v0 + .3), (u + L, v1 - .3), (u + L * .3, v1)], 0, 1.4,
                     M.solid(hull), M.roof("e4d6b6" if kind == "sail" else "f4f4f0"))
        top = 3.4 if kind == "motor" else 2.4
        sc.add_prism([(u + L * .45, v0 + .7), (u + L * .85, v0 + .7), (u + L * .85, v1 - .7), (u + L * .45, v1 - .7)],
                     1.4, top, M.tower(wall="ffffff", glass="34485a", floor_h=top - 1.4, win=0.45, bay=1.6, pier=0.2,
                                       lobby_h=0), M.roof("f6f6f2"))
    if kind in ("sail", "cat"):
        mu = u + L * (.4 if kind == "sail" else .55)
        sc.add_prism([(mu - .45, v - .45), (mu + .45, v - .45), (mu + .45, v + .45), (mu - .45, v + .45)], 1.4, 15.0,
                     M.solid("f0f0ec"))
        if kind == "sail":                      # furled main under a coloured cover along the boom
            c = rng.choice(COVERS)
            sc.add_prism([(mu, v - .7), (mu + L * .45, v - .7), (mu + L * .45, v + .7), (mu, v + .7)], 2.6, 3.6,
                         M.solid(c), M.roof(c))


def marina_scene(T, tile_px):
    """Ala Wai Small Boat Harbor, 3x3: wooden docks with finger piers full of white
    sailboats, catamarans and motor yachts, and a plantation-style yacht club
    (white lanai, green double-pitched roof) among palms. No water: make_mif.py
    lays the game's own shimmering turquoise water underneath, so it matches the sea."""
    rng = random.Random(2481)
    sc = Scene(3, T, tile_px)
    L = 3 * T
    # yacht club on a grassy pad with a low stone seawall, at the back corner
    pu, pv = L * .36, L * .30
    sc.add_prism([(0, 0), (pu, 0), (pu, pv), (0, pv)], 0, 1.2, M.solid("8c8478"), M.ground("grass"))
    walls(sc, 6, 7, 30, 24, 1.2, 9.5, "f6f4ee", rng, glass="3c5868")
    sc.add_prism([(6, 24), (30, 24), (30, 28), (6, 28)], 1.2, 1.6, M.solid("c8c0b0"), M.roof("b4aa98"))
    hip_roof(sc, 5, 6, 31, 28.5, 9.5, 4.5, "4f8a5c")
    sc.add_prism([(36, 8), (36.8, 8), (36.8, 8.8), (36, 8.8)], 1.2, 22, M.solid("f4f4f0"))     # flagpole
    sc.add_quad([(36.4, 8.4, 22), (36.4, 13, 22), (36.4, 13, 19.5), (36.4, 8.4, 19.5)],
                (M.solid("d8392c"), (1.0, 0.0), 4.6), "wall", 0.5)
    for u, v in ((3, 34), (41, 5), (42, 34), (34, 35)):
        palm(sc, u, v, rng)
    for u, v in ((10, 33), (18, 34), (26, 33), (40, 14), (41, 24)):
        garden.shrub(sc, u, v, rng, r=2.0)
    # docks: a promenade along the pad, then two spines running makai with finger piers
    def deck(u0, v0, u1, v1):
        sc.add_prism([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], 0, 0.9, M.solid("7a6448"), M.roof(DOCK, "8a7050"))
    deck(pu, 2, pu + 3, L - 2)                    # spine 1 along the pad edge, running makai
    deck(L * .70, 2, L * .70 + 3, L - 2)          # spine 2
    deck(2, pv + 2, pu, pv + 4.5)                 # a pier off the pad
    for spine, sides in ((pu + 3, (1,)), (L * .70, (-1, 1))):
        for k in range(9):
            v = 6 + k * (L - 12) / 8
            for s in sides:
                u0 = spine + (3 if s > 0 and spine == L * .70 else 0)
                fu0, fu1 = (u0, u0 + 17) if s > 0 else (spine - 17, spine)
                deck(fu0, v - .8, fu1, v + .8)
                if rng.random() < 0.85 and v + 5.4 < L - 1:
                    boat(sc, fu0 + 1.5, v + 5.0, rng, length=rng.uniform(9, 11))
    # boats tied along the pad pier
    for u in (6, 22):
        boat(sc, u, pv + 9.5, rng, length=10, kind="sail")
    return sc
