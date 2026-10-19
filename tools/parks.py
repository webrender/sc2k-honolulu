"""Hand-modelled civic landmarks: Kapiolani Park's Honolulu Zoo and Waikiki Shell,
the Waikiki Aquarium, and the University of Hawaii at Manoa.

Each is a placement.SPECIAL entry: a fixed footprint at its real spot, drawn here
in the same 3D sprite style as tileset.py. Colours are Perler beads (perler.py).
Animals, trees and people-scale things are drawn larger than life (about 2x), so
they read at SimCity's 0.45-0.74 px per metre.
"""
import math
import random

import numpy as np

import garden
import materials as M
from houses import face, hip_roof, walls
from render3d import Scene, soft

# beads
LAWN, SAVANNA, PATH, SAND = "4fad42", "b0d169", "ebe1cd", "e4b690"
WATER, WATER_LIGHT = "2b89c6", "54cde3"
WHITE, LIGHT_GREY, PEWTER, GREY = "f8f8f8", "b1b5b2", "a0a5a5", "8a8d91"
UH_GREEN, WOOD = "1c753e", "815d34"
ROOF_SOFT = "9c8d8e"     # Stone: a warm grey for the campus hip roofs (rust red stood out too much)


def ground(sc, L, col=LAWN):
    sc.add_quad([(0, 0, 0), (L, 0, 0), (L, L, 0), (0, L, 0)], (M.ground(col), None, 0), "roof", -1e4)


def patch(sc, pts, col, bias=-9e3, z=0.03):
    """A flat area painted on the ground (paths, ponds, sand)."""
    sc.add_quad([(u, v, z) for u, v in pts], (M.ground(col), None, 0), "roof", bias)


def disc(u, v, r, k=16, squash=1.0, rng=None):
    j = (lambda: rng.uniform(0.85, 1.1)) if rng else (lambda: 1.0)
    return [(u + r * math.cos(a) * j(), v + r * squash * math.sin(a) * j()) for a in [i * 2 * math.pi / k for i in range(k)]]


def box(sc, u0, v0, u1, v1, z0, z1, col, top=None):
    sc.add_prism([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], z0, z1, M.solid(col), M.roof(top or col))


def fence(sc, a, b, h=1.6):
    (u0, v0), (u1, v1) = a, b
    d = math.hypot(u1 - u0, v1 - v0) or 1
    nu, nv = -(v1 - v0) / d * .25, (u1 - u0) / d * .25
    sc.add_prism([(u0 + nu, v0 + nv), (u1 + nu, v1 + nv), (u1 - nu, v1 - nv), (u0 - nu, v0 - nv)], 0, h,
                 M.solid(WOOD), M.roof(WOOD))


# --- animals (about 2x life size) -----------------------------------------------------------
def giraffe(sc, u, v, s=1.9):
    for du, dv in ((-1, -.35), (-1, .35), (1, -.35), (1, .35)):
        box(sc, u + du * s - .25, v + dv * s - .25, u + du * s + .25, v + dv * s + .25, 0, 2.2 * s, "bc9371")
    box(sc, u - 1.3 * s, v - .5 * s, u + 1.3 * s, v + .5 * s, 2.2 * s, 3.2 * s, "f6c966")
    box(sc, u + .8 * s, v - .25 * s, u + 1.3 * s, v + .25 * s, 3.2 * s, 5.6 * s, "f6c966")      # neck
    box(sc, u + .8 * s, v - .3 * s, u + 1.9 * s, v + .3 * s, 5.4 * s, 6.0 * s, "d48437")        # head


def zebra(sc, u, v, s=1.8):
    for du, dv in ((-1, -.3), (-1, .3), (1, -.3), (1, .3)):
        box(sc, u + du * s - .2, v + dv * s - .2, u + du * s + .2, v + dv * s + .2, 0, 1.1 * s, "2e2f32")
    box(sc, u - 1.2 * s, v - .45 * s, u + 1.2 * s, v + .45 * s, 1.1 * s, 2.0 * s, WHITE)
    box(sc, u + 1.0 * s, v - .3 * s, u + 1.7 * s, v + .3 * s, 1.6 * s, 2.3 * s, "2e2f32")


def elephant(sc, u, v, s=2.0):
    for du, dv in ((-1, -.6), (-1, .6), (1, -.6), (1, .6)):
        box(sc, u + du * s - .5, v + dv * s - .5, u + du * s + .5, v + dv * s + .5, 0, 1.4 * s, GREY)
    box(sc, u - 1.6 * s, v - .95 * s, u + 1.6 * s, v + .95 * s, 1.4 * s, 3.2 * s, GREY)
    box(sc, u + 1.6 * s, v - .7 * s, u + 2.4 * s, v + .7 * s, 1.8 * s, 3.0 * s, GREY)          # head
    box(sc, u + 2.4 * s, v - .2 * s, u + 2.8 * s, v + .2 * s, 0.4 * s, 2.2 * s, GREY)          # trunk


def flamingo(sc, u, v):
    box(sc, u - .15, v - .15, u + .15, v + .15, 0, 1.6, "f08bb3")
    garden.blob(sc, u, v, 0.9, 1.6, 2.6, "f08bb3", "ffb9b9", random.Random(int(u * 7 + v)), k=6)


@soft
def acacia(sc, u, v, rng):
    """Flat-topped savanna tree."""
    h = rng.uniform(6, 8)
    box(sc, u - .5, v - .5, u + .5, v + .5, 0, h, WOOD)
    garden.blob(sc, u, v, rng.uniform(5, 7), h, h + 1.6, "355343", "7b9730", rng, k=12)


# --- Honolulu Zoo -------------------------------------------------------------------------
def zoo_savanna_scene(T, tile_px):
    """The African Savanna: dry grass, a waterhole, flat-topped trees, giraffes and
    zebras, and the elephant yard behind a fence, all ringed by lush zoo planting."""
    rng = random.Random(1001)
    sc = Scene(3, T, tile_px)
    L = 3 * T
    ground(sc, L, SAVANNA)
    patch(sc, disc(L * .52, L * .55, 13, rng=rng, squash=.7), "e4b690", -9.2e3)                 # mud shore
    patch(sc, disc(L * .52, L * .55, 10, rng=rng, squash=.7), WATER, -9e3)                      # waterhole
    patch(sc, [(4, L * .30), (L - 4, L * .30), (L - 4, L * .33), (4, L * .33)], PATH)          # visitor path
    for x in range(6, int(L) - 6, 10):
        fence(sc, (x, L * .335), (x + 8, L * .335))
    # elephant yard (behind the path)
    patch(sc, [(L * .08, L * .05), (L * .6, L * .05), (L * .6, L * .27), (L * .08, L * .27)], "bc9371", -9.1e3)
    patch(sc, disc(L * .45, L * .14, 6, squash=.6), WATER, -9e3)
    elephant(sc, L * .22, L * .15)
    elephant(sc, L * .34, L * .2, s=1.6)
    for a, b in (((L * .08, L * .27), (L * .6, L * .27)), ((L * .6, L * .05), (L * .6, L * .27))):
        fence(sc, a, b, h=2.0)
    # the savanna
    for u, v in ((L * .25, L * .5), (L * .78, L * .45), (L * .35, L * .8), (L * .8, L * .78)):
        acacia(sc, u, v, rng)
    for u, v in ((L * .42, L * .66), (L * .6, L * .72), (L * .3, L * .62)):
        giraffe(sc, u, v)
    for u, v in ((L * .66, L * .5), (L * .7, L * .6), (L * .2, L * .72), (L * .48, L * .86)):
        zebra(sc, u, v)
    for u, v in ((L * .62, L * .36), (L * .14, L * .4)):
        garden.blob(sc, u, v, 3.5, 0, 2.5, PEWTER, LIGHT_GREY, rng, k=7)                       # rocks
    # lush planting round the back and sides
    for i in range(7):
        garden.shade_tree(sc, L * .7 + i % 2 * 8, 6 + i * 5, rng)
    for i in range(6):
        garden.palm(sc, 4, L * .38 + i * 13, rng)
    return sc


def zoo_gate_scene(T, tile_px):
    """The zoo entrance off Kapahulu Avenue: a gate with a green roof, the plaza,
    the flamingo pond, an aviary and dense tropical planting."""
    rng = random.Random(1002)
    sc = Scene(3, T, tile_px)
    L = 3 * T
    ground(sc, L)
    patch(sc, [(L * .55, L * .62), (L, L * .62), (L, L), (L * .55, L)], PATH)                   # entry plaza
    patch(sc, [(L * .1, L * .45), (L * .6, L * .45), (L * .6, L * .5), (L * .1, L * .5)], PATH)
    patch(sc, [(L * .45, L * .1), (L * .5, L * .1), (L * .5, L * .62), (L * .45, L * .62)], PATH)
    # gate: two pillars and a roofed lintel over the walk, ticket booths either side
    gu, gv = L * .8, L * .8
    for dv in (-9, 9):
        box(sc, gu - 2.5, gv + dv - 2.5, gu + 2.5, gv + dv + 2.5, 0, 13, "e0dea9")
    box(sc, gu - 3, gv - 12, gu + 3, gv + 12, 13, 16, "f6c966")                                  # sign board
    hip_roof(sc, gu - 4.5, gv - 13.5, gu + 4.5, gv + 13.5, 16, 4.5, UH_GREEN)
    for dv in (-20, 20):
        walls(sc, gu - 4, gv + dv - 4, gu + 4, gv + dv + 4, 0, 6, WHITE, rng)
        hip_roof(sc, gu - 5, gv + dv - 5, gu + 5, gv + dv + 5, 6, 3.0, UH_GREEN)
    # flamingo pond
    patch(sc, disc(L * .3, L * .7, 12, squash=.75, rng=rng), WATER_LIGHT, -9e3)
    for i in range(9):
        a = i * 2.3
        flamingo(sc, L * .3 + 7 * math.cos(a) * rng.uniform(.4, 1), L * .7 + 5 * math.sin(a) * rng.uniform(.4, 1))
    # aviary: a mesh dome
    for r, z0, z1 in ((10, 0, 4), (9, 4, 8), (7, 8, 11), (4, 11, 13)):
        garden.blob(sc, L * .25, L * .22, r, z0, z1, LIGHT_GREY, "c3dad8", rng, k=14)
    # a giraffe and an elephant visible over the trees
    giraffe(sc, L * .7, L * .3)
    elephant(sc, L * .82, L * .15, s=1.7)
    placed = 0
    for _ in range(200):
        if placed >= 16:
            break
        u, v = rng.uniform(5, L - 5), rng.uniform(5, L - 5)
        on_path = (L * .43 < u < L * .55) or (L * .43 < v < L * .52) or (u > L * .53 and v > L * .6)
        in_feature = (abs(u - L * .25) < 13 and abs(v - L * .22) < 13) or math.hypot(u - L * .3, v - L * .7) < 14             or math.hypot(u - L * .7, v - L * .3) < 6 or math.hypot(u - L * .82, v - L * .15) < 7
        if not (on_path or in_feature):
            (garden.shade_tree if rng.random() < .6 else garden.palm)(sc, u, v, rng)
            placed += 1
    for i in range(5):
        garden.shrub(sc, L * .56 + i * 9, L * .6, rng, r=2.2)
    return sc


# --- Waikiki Shell -------------------------------------------------------------------------
def shell_scene(T, tile_px):
    """The Waikiki Shell (1956): a white concert band shell opening onto lawn seating,
    with rows of seats in a fan in front of the stage."""
    rng = random.Random(1003)
    sc = Scene(3, T, tile_px)
    L = 3 * T
    ground(sc, L)
    fwd = np.array([1, 1]) / math.sqrt(2)                   # the shell faces the camera
    side = np.array([1, -1]) / math.sqrt(2)
    C = np.array([L * .3, L * .3])
    R, H = 24.0, 42.0                       # far taller than life, or the camera sees only its top
    # seating fan: concentric rows on paving, lawn behind them
    for k, r in enumerate(np.arange(R * 1.0, R * 2.6, 3.2)):
        ring = []
        for a in np.linspace(-1.05, 1.05, 18):
            d = math.cos(a) * fwd + math.sin(a) * side
            ring.append(tuple(C + d * r))
        inner = []
        for a in np.linspace(1.05, -1.05, 18):
            d = math.cos(a) * fwd + math.sin(a) * side
            inner.append(tuple(C + d * (r + 1.6)))
        patch(sc, ring + inner, PEWTER if k % 2 == 0 else LIGHT_GREY, -8.9e3)
    # stage
    # stage: fills the floor under the shell and runs out as an apron toward the seats
    back = [tuple(C + (math.cos(t) * side - math.sin(t) * fwd) * R * .98) for t in np.linspace(0, math.pi, 13)]
    apron = [tuple(C - side * R * .98 + fwd * R * .45), tuple(C + side * R * .98 + fwd * R * .45)]
    sc.add_prism(back + apron, 0, 1.4, M.solid("ccccc8"), M.roof("e0dea9"))
    # the shell: a quarter-sphere of arched bands, open toward the seats
    n_t, n_p = 14, 7
    for i in range(n_t):
        for j in range(n_p):
            pts = []
            for (ti, pj) in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                th = math.pi * ti / n_t
                ph = (math.pi / 2) * pj / n_p
                d = math.cos(th) * side - math.sin(th) * fwd
                xy = C + d * R * math.cos(ph)
                pts.append((float(xy[0]), float(xy[1]), H * math.sin(ph)))
            face(sc, pts, WHITE if j % 2 == 0 else "d7d7e3", 0.3)
    for i in range(6):
        garden.palm(sc, L * .05 + i * 4, L * .9 - i * 3, rng)
        garden.palm(sc, L * .9 - i * 3, L * .05 + i * 4, rng)
    for u, v in ((6, 6), (L * .04, L * .6), (L * .6, L * .04)):          # outside the shell
        garden.shade_tree(sc, u, v, rng, r=7)
    return sc


# --- Waikiki Aquarium -----------------------------------------------------------------------
def mural(base="f8f8f8"):
    """Sea-life mural: blue waves with orange and yellow fish (on the street front)."""
    sea, wave, fish1, fish2 = (M.color(c) for c in ("54cde3", "2b89c6", "ed6120", "ecd800"))
    wall = M.color(base)

    def fn(s, z, normal, edge_len, P):
        from render3d import wall_light
        k = wall_light(normal)
        rgb = np.tile(wall, (len(s), 1))
        band = (z > 1.0) & (z < 7.5)
        rgb[band] = sea
        crest = band & (np.abs(z - (4.2 + 1.1 * np.sin(s / 3.0))) < 0.6)
        rgb[crest] = wave
        f = band & ((s % 7.0) < 1.6) & (np.abs(z - (2.4 + (s // 7 % 3))) < 0.5)
        rgb[f] = np.where(((s // 7) % 2 == 0)[f][:, None], fish1, fish2)
        out = np.empty((len(s), 4), dtype=np.float32)
        out[:, :3] = rgb * k
        out[:, 3] = 255
        return out
    return fn


def aquarium_scene(T, tile_px):
    """The Waikiki Aquarium (1904, on the reef at Kapiolani Park): a low white
    building with a sea-life mural, outdoor seal and reef pools, and palms."""
    rng = random.Random(1004)
    sc = Scene(2, T, tile_px)
    L = 2 * T
    ground(sc, L)
    patch(sc, [(L * .55, L * .55), (L, L * .55), (L, L), (L * .55, L)], PATH)
    sc.add_prism([(10, 10), (L * .62, 10), (L * .62, L * .45), (10, L * .45)], 0, 9.5,
                 M.tower(wall=WHITE, glass="2b89c6", floor_h=4.6, win=0.45, bay=3.4, pier=0.35, lobby_h=0),
                 M.roof(LIGHT_GREY, PEWTER))
    box(sc, 9.5, 9.5, L * .62 + .5, L * .45 + .5, 9.5, 10.3, "02caad")                          # teal fascia
    sc.add_prism([(10, L * .45), (L * .4, L * .45), (L * .4, L * .78), (10, L * .78)], 0, 7.5,
                 mural(), M.roof(LIGHT_GREY, PEWTER))
    # monk seal pool and reef tank outside
    patch(sc, disc(L * .72, L * .25, 9, squash=.7, rng=rng), WATER_LIGHT, -9e3)
    garden.blob(sc, L * .76, L * .26, 2.5, 0, 1.4, PEWTER, LIGHT_GREY, rng, k=6)
    sc.add_prism(disc(L * .78, L * .72, 6, k=12), 0, 1.0, M.solid("ccccc8"), M.roof(WATER, "2b89c6"))
    for u, v in ((L * .5, L * .92), (L * .66, L * .9), (L * .92, L * .48), (L * .92, L * .62), (L * .1, L * .9)):
        garden.palm(sc, u, v, rng)
    for i in range(4):
        garden.shrub(sc, L * .45 + i * 8, L * .52, rng, r=1.8)
    return sc


# --- University of Hawaii at Manoa ------------------------------------------------------------
def field_shader(u0, u1, v0, v1):
    grass, dark, line = (M.color(c) for c in ("4fad42", "1c753e", WHITE))

    def fn(u, v, z, P):
        rgb = np.tile(grass, (len(u), 1))
        f = (u - u0) / (u1 - u0)
        rgb[(f < 0.09) | (f > 0.91)] = dark                                   # end zones
        rgb[((u - u0) % 9.0 < 0.9) & (f >= 0.09) & (f <= 0.91)] = line         # yard lines
        out = np.empty((len(u), 4), dtype=np.float32)
        out[:, :3] = rgb
        out[:, 3] = 255
        return out
    return fn


def uh_athletics_scene(T, tile_px):
    """UH Manoa's lower campus: the Clarence T.C. Ching Athletics Complex (football
    field inside a running track, green grandstand with a press box) and the
    white dome of the Stan Sheriff Center."""
    rng = random.Random(1005)
    sc = Scene(3, T, tile_px)
    L = 3 * T
    ground(sc, L)
    patch(sc, disc(L * .5, L * .58, 52, k=28, squash=.52), "f9916c", -9.1e3)                    # track
    u0, u1, v0, v1 = L * .5 - 44, L * .5 + 44, L * .58 - 20, L * .58 + 20
    sc.add_quad([(u0, v0, .06), (u1, v0, .06), (u1, v1, .06), (u0, v1, .06)], (field_shader(u0, u1, v0, v1), None, 0),
                "roof", -9e3)
    # grandstand along the back of the field, stepping up away from it
    for k in range(6):
        vb = L * .58 - 30 - k * 3.2
        box(sc, L * .5 - 40, vb - 3.2, L * .5 + 40, vb, 0, 1.6 + k * 1.6, UH_GREEN if k % 2 == 0 else "ccccc8")
    box(sc, L * .5 - 20, L * .58 - 52, L * .5 + 20, L * .58 - 46, 10, 15, WHITE)               # press box
    sc.add_prism([(L * .5 - 20, L * .58 - 46.2), (L * .5 + 20, L * .58 - 46.2), (L * .5 + 20, L * .58 - 46),
                  (L * .5 - 20, L * .58 - 46)], 11, 14, M.solid("323755"))
    # low bleachers on the near side
    for k in range(2):
        vb = L * .58 + 30 + k * 3
        box(sc, L * .5 - 30, vb, L * .5 + 30, vb + 3, 0, 1.2 + k * 1.2, LIGHT_GREY)
    # light towers
    for u, v in ((L * .5 - 50, L * .58 - 32), (L * .5 + 50, L * .58 - 32), (L * .5 - 50, L * .58 + 32),
                 (L * .5 + 50, L * .58 + 32)):
        box(sc, u - .6, v - .6, u + .6, v + .6, 0, 26, GREY)
        box(sc, u - 2.5, v - 1, u + 2.5, v + 1, 26, 28.5, LIGHT_GREY)
    # Stan Sheriff Center, the arena, at the near corner
    cu, cv = L * .86, L * .14
    sc.add_prism(disc(cu, cv, 15, k=20), 0, 7, M.tower(wall="ccccc8", glass="43658b", floor_h=7, win=0.3, bay=3.0,
                                                      lobby_h=0), M.roof(WHITE))
    for r, z0, z1 in ((14, 7, 9.5), (11, 9.5, 11.5), (7, 11.5, 13)):
        sc.add_prism(disc(cu, cv, r, k=20), z0, z1, M.solid(WHITE), M.roof(WHITE, "d7d7e3"))
    for i in range(8):
        garden.shade_tree(sc, 6 + i * 15, L - 6, rng, r=5)
    return sc


def fins(wall="ccccc8", glass="323755"):
    """Hamilton Library: tall concrete fins with deep dark slots between them."""
    return M.tower(wall=wall, glass=glass, floor_h=40, win=0.9, bay=2.6, pier=0.45, lobby_h=0)


def uh_campus_scene(T, tile_px):
    """UH Manoa's core campus: Hamilton Library's finned concrete block, the Campus
    Center, a red-tiled Bachman Hall, and the monkeypod-shaded quad round the
    Varney Circle fountain."""
    rng = random.Random(1006)
    sc = Scene(3, T, tile_px)
    L = 3 * T
    ground(sc, L)
    patch(sc, [(L * .45, 0), (L * .53, 0), (L * .53, L), (L * .45, L)], PATH)                   # malls
    patch(sc, [(0, L * .45), (L, L * .45), (L, L * .53), (0, L * .53)], PATH)
    patch(sc, disc(L * .49, L * .49, 10, k=20), PATH, -8.95e3)
    sc.add_prism(disc(L * .49, L * .49, 6, k=20), 0, .8, M.solid(WHITE), M.roof(WATER_LIGHT, WHITE))   # Varney fountain
    box(sc, L * .49 - .5, L * .49 - .5, L * .49 + .5, L * .49 + .5, .8, 3.5, WHITE)
    # Hamilton Library (back left)
    sc.add_prism([(8, 8), (L * .4, 8), (L * .4, L * .38), (8, L * .38)], 0, 24, fins(), M.roof(LIGHT_GREY, PEWTER))
    # Bachman Hall (back right): white with a hip roof in soft warm grey (Stone), so it sits in
    walls(sc, L * .6, 10, L - 8, L * .3, 0, 9, WHITE, rng)
    hip_roof(sc, L * .6 - 1.2, 8.8, L - 6.8, L * .3 + 1.2, 9, 4.5, ROOF_SOFT)
    # Campus Center (front right)
    sc.add_prism([(L * .6, L * .62), (L - 8, L * .62), (L - 8, L - 10), (L * .6, L - 10)], 0, 12,
                 M.tower(wall="e0dea9", glass="43658b", floor_h=4.0, win=0.5, bay=3.2, lobby_h=0),
                 M.roof(LIGHT_GREY, PEWTER))
    # a lecture building (front left)
    sc.add_prism([(10, L * .62), (L * .38, L * .62), (L * .38, L - 12), (10, L - 12)], 0, 14,
                 M.tower(wall=WHITE, glass="5a7180", floor_h=4.0, win=0.45, bay=3.6, lobby_h=0),
                 M.roof(LIGHT_GREY, PEWTER))
    for u, v in ((L * .3, L * .48), (L * .68, L * .48), (L * .48, L * .3), (L * .48, L * .7), (L * .15, L * .5),
                 (L * .85, L * .5)):
        garden.shade_tree(sc, u, v, rng, r=6.5)
    return sc


SCENES = {"zoo_savanna": zoo_savanna_scene, "zoo_gate": zoo_gate_scene, "shell": shell_scene,
          "aquarium": aquarium_scene, "uh_athletics": uh_athletics_scene, "uh_campus": uh_campus_scene}


# --- UH Manoa campus blocks (3x3, tiled across the rest of the campus) ----------------------
CAMPUS_NAMES = ["UH Lecture Halls", "UH Science Labs", "UH Residence Halls", "UH Hawaiian Studies"]


def campus_block_scene(variant, T, tile_px):
    """Four kinds of UH Manoa block, so a campus of them doesn't repeat: concrete
    lecture halls round a courtyard, science labs with a mid-rise and rooftop plant,
    the Hale Aloha-style residence towers, and low Hawaiian-style buildings with
    hip roofs and a garden. Monkeypods and lawn in between."""
    rng = random.Random(1100 + variant)
    sc = Scene(3, T, tile_px)
    L = 3 * T
    ground(sc, L)
    patch(sc, [(L * .46, 0), (L * .54, 0), (L * .54, L), (L * .46, L)], PATH)
    concrete = M.tower(wall="ccccc8", glass="43658b", floor_h=4.0, win=0.45, bay=3.2, pier=0.4, lobby_h=0)
    white = M.tower(wall=WHITE, glass="5a7180", floor_h=3.6, win=0.45, bay=3.4, lobby_h=0)
    trees = []
    if variant == 0:                 # lecture halls round a courtyard
        sc.add_prism([(8, 8), (L * .42, 8), (L * .42, L * .4), (8, L * .4)], 0, 16, concrete, M.roof(LIGHT_GREY, PEWTER))
        sc.add_prism([(L * .58, 10), (L - 8, 10), (L - 8, L * .36), (L * .58, L * .36)], 0, 12, white, M.roof(LIGHT_GREY))
        sc.add_prism([(10, L * .6), (L * .4, L * .6), (L * .4, L - 10), (10, L - 10)], 0, 12, white, M.roof(LIGHT_GREY))
        trees = [(L * .7, L * .62), (L * .8, L * .8), (L * .62, L * .85), (L * .3, L * .48)]
    elif variant == 1:               # science labs: a long lab and a mid-rise with rooftop plant
        sc.add_prism([(8, 10), (L - 8, 10), (L - 8, L * .3), (8, L * .3)], 0, 10, concrete, M.roof(LIGHT_GREY, PEWTER))
        for i in range(5):
            box(sc, 14 + i * 22, 14, 20 + i * 22, 22, 10, 12.5, PEWTER)                               # plant
        sc.add_prism([(L * .58, L * .5), (L - 10, L * .5), (L - 10, L - 12), (L * .58, L - 12)], 0, 30,
                     M.tower(wall="e0dea9", glass="323755", floor_h=3.8, win=0.5, bay=3.0, lobby_h=0),
                     M.roof(LIGHT_GREY, PEWTER))
        box(sc, L * .64, L * .56, L * .74, L * .66, 30, 33, PEWTER)
        trees = [(L * .2, L * .55), (L * .3, L * .75), (L * .15, L * .85), (L * .4, L * .62)]
    elif variant == 2:               # residence towers on a lawn
        for u, v in ((L * .22, L * .25), (L * .72, L * .3), (L * .25, L * .72), (L * .72, L * .74)):
            sc.add_prism([(u - 8, v - 8), (u + 8, v - 8), (u + 8, v + 8), (u - 8, v + 8)], 0, 40,
                         M.tower(wall=WHITE, glass="43658b", floor_h=3.0, win=0.45, bay=2.8, balcony="f8f8f8",
                                 lobby_h=4), M.roof(LIGHT_GREY, PEWTER))
        trees = [(L * .5, L * .14), (L * .5, L * .88), (L * .1, L * .5), (L * .9, L * .52)]
    else:                            # low Hawaiian-style buildings with hip roofs and a garden
        for u0, v0, u1, v1 in ((8, 8, L * .4, L * .3), (L * .6, 12, L - 8, L * .34), (10, L * .62, L * .38, L - 10)):
            walls(sc, u0, v0, u1, v1, 0, 7, "e9c79b", rng)
            hip_roof(sc, u0 - 2, v0 - 2, u1 + 2, v1 + 2, 7, 6, ROOF_SOFT)
        patch(sc, disc(L * .72, L * .72, 12, rng=rng), WATER_LIGHT, -9e3)                         # garden pond
        trees = [(L * .6, L * .55), (L * .88, L * .6), (L * .6, L * .9), (L * .3, L * .48)]
    for u, v in trees:
        garden.shade_tree(sc, u, v, rng, r=6)
    for i in range(3):
        garden.shrub(sc, L * .44 - 4, L * .2 + i * 30, rng, r=2)
    return sc


for _i in range(4):
    SCENES[f"campus_{_i}"] = (lambda i: (lambda T, px: campus_block_scene(i, T, px)))(_i)
