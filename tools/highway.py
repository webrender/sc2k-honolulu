"""H-1 (the Lunalilo Freeway) as a SimCity 2000 highway.

How the game stores highways (read from the stock cities, e.g. CITIES/TOKYO.SC2,
and the XBLD table in dfloer/SC2k-docs):
  * a highway is two tiles wide; straight runs are separate 1x1 tiles, every one
    with all four XZON corner bits: 0x4A ("TB") runs along grid x, 0x49 ("LR")
    along grid y;
  * where a road passes under, both highway tiles become crossover pieces:
    0x4C (highway along x over a road along y) or 0x4B (the other way round);
  * a turn is one 2x2 piece whose four tiles share the ID and carry the usual
    2x2 corner bits: 0x65 BR, 0x66 BL, 0x67 TL, 0x68 TR.
The direction letters match the road pieces we take from real saves:
T = x-1, B = x+1, R = y-1, L = y+1.

The route follows the OSM centreline of H-1 as a staircase of 2x2 blocks (SimCity
has no diagonal highway). It runs at one level (LEVEL above the sea): on a low
embankment over Moiliili and Kahala, in a cut through Kaimuki, as the real one
does, so every highway tile is flat without ramp pieces.
"""
import numpy as np

N = 128
ALONG_X, ALONG_Y = 0x4A, 0x49
OVER_ROAD = {"x": 0x4C, "y": 0x4B}
CORNERS = {frozenset("BR"): 0x65, frozenset("BL"): 0x66, frozenset("TL"): 0x67, frozenset("TR"): 0x68}
DIRS = {(-1, 0): "T", (1, 0): "B", (0, -1): "R", (0, 1): "L"}
OPPOSITE = {"T": "B", "B": "T", "L": "R", "R": "L"}
LEVEL = 1          # altitude levels above sea level
JOG = 3            # drift (tiles) from the real route before the staircase steps


def centreline(frame, elements):
    """Target y (grid) for each grid x, from the OSM H-1 carriageways; NaN off the route."""
    import geo
    pts = []
    for e in elements:
        t = e.get("tags", {})
        if e["type"] == "way" and t.get("highway") == "motorway" and "H1" in (t.get("ref") or "").replace("-", ""):
            for p in e["geometry"]:
                pts.append(frame.world_to_grid(*geo.to_m(p["lat"], p["lon"])))
    pts = np.array(pts)
    pts = pts[(pts[:, 0] > -20) & (pts[:, 0] < N + 20)]
    xs = np.arange(-20, N + 20)
    ys = np.full(len(xs), np.nan)
    for i, x in enumerate(xs):
        sel = pts[np.abs(pts[:, 0] - (x + 0.5)) < 2.0]
        if len(sel):
            ys[i] = sel[:, 1].mean()
    ok = ~np.isnan(ys)
    ys = np.interp(xs, xs[ok], ys[ok])
    return dict(zip(xs.tolist(), ys.tolist()))


def plan(frame, elements):
    """[{x, y, tiles: [(x, y)], dirs, kind: 'x' | 'y' | 'corner'}] from the west edge eastward."""
    yc = centreline(frame, elements)
    target = lambda x: yc.get(int(x) + 1, yc[max(yc)]) - 0.5     # band's first row for a block at x
    bx, by = 0, int(round(target(0)))
    blocks = [(bx, by)]
    while True:
        t = target(bx + 2)
        if t - by <= -JOG:
            if by - 2 < 0:
                break                          # the freeway leaves the map at the top edge
            by -= 2
        elif t - by >= JOG and by + 2 <= N - 2:
            by += 2
        elif bx + 2 <= N - 2:
            bx += 2
        else:
            break
        blocks.append((bx, by))
    out = []
    for i, (x, y) in enumerate(blocks):
        dirs = set()
        for j in (i - 1, i + 1):
            if 0 <= j < len(blocks):
                dx, dy = blocks[j][0] - x, blocks[j][1] - y
                dirs.add(DIRS[(dx // 2, dy // 2)])
        if len(dirs) == 1:                     # an end: carry on off the map
            dirs.add(OPPOSITE[next(iter(dirs))])
        kind = "x" if dirs == {"T", "B"} else "y" if dirs == {"L", "R"} else "corner"
        out.append({"x": x, "y": y, "dirs": dirs, "kind": kind,
                    "tiles": [(x + i, y + j) for i in (0, 1) for j in (0, 1)]})
    return out


def band_mask(blocks):
    m = np.zeros((N, N), dtype=bool)
    for b in blocks:
        for x, y in b["tiles"]:
            m[x, y] = True
    return m


def crossings(blocks, roads):
    """{(x, y): kind} for highway tiles a road passes under, at right angles."""
    out = {}
    for b in blocks:
        if b["kind"] == "x":                   # band rows y, y+1: a road along y crosses it
            for x in (b["x"], b["x"] + 1):
                y0 = b["y"]
                if y0 - 1 >= 0 and y0 + 2 < N and roads[x, y0 - 1] and roads[x, y0 + 2]:
                    out[(x, y0)] = out[(x, y0 + 1)] = "x"
        elif b["kind"] == "y":
            for y in (b["y"], b["y"] + 1):
                x0 = b["x"]
                if x0 - 1 >= 0 and x0 + 2 < N and roads[x0 - 1, y] and roads[x0 + 2, y]:
                    out[(x0, y)] = out[(x0 + 1, y)] = "y"
    return out


def pieces(blocks, cross):
    """[(x, y, xbld, xzon corner bits)] for every highway tile."""
    out = []
    for b in blocks:
        if b["kind"] == "corner":
            pid = CORNERS[frozenset(b["dirs"])]
            x0, y0 = b["x"], b["y"]
            bits = {(x0, y0): 0x10, (x0 + 1, y0): 0x20, (x0 + 1, y0 + 1): 0x40, (x0, y0 + 1): 0x80}
            out += [(x, y, pid, bits[(x, y)]) for x, y in b["tiles"]]
        else:
            for x, y in b["tiles"]:
                pid = OVER_ROAD[b["kind"]] if (x, y) in cross else (ALONG_X if b["kind"] == "x" else ALONG_Y)
                out.append((x, y, pid, 0xF0))
    return out
