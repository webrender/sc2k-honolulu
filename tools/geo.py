"""Project Waikiki's real-world geography onto SimCity 2000's 128x128 tile grid.

Grid orientation: Waikiki's street grid runs at bearings ~42 deg / ~132 deg, so the
map's axes follow it (roads stay straight instead of becoming staircases).
  +x  runs along the shore toward Diamond Head (bearing 132 deg, ESE)
  +y  runs makai, toward the ocean (bearing 222 deg, SW)
In SC2K's default view, +x points down-right and +y down-left on screen, so the
ocean sits at the bottom-left and Diamond Head at the bottom-right.

Run:  python tools/geo.py   ->  data/grid.npz, data/grid_preview.png
"""
import json
import math
import time
from pathlib import Path

import numpy as np
import requests
from shapely.geometry import LineString, Polygon, Point, box
from shapely.ops import linemerge, split, unary_union
from shapely.strtree import STRtree
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
N = 128

# Frame anchors: the map spans from the Ala Wai Harbor entrance to the far
# (Kahala) side of Diamond Head crater.
WEST_ANCHOR = (21.2860, -157.8445)   # lat, lon: Ala Wai Harbor entrance
EAST_ANCHOR = (21.2610, -157.7975)   # east rim of Diamond Head crater
COAST_ANCHOR = (21.2540, -157.8100)  # offshore of Diamond Head lighthouse
COAST_ANCHOR_Y = 102                 # leaves about a quarter of the map as ocean beyond it
BEARING = 132.0                      # grid +x direction, degrees from north
# the frame is slid this many tiles east of WEST_ANCHOR so the coast can be seen
# curving north past Diamond Head toward Kahala (the harbour falls off the west edge)
SHIFT_X = 14

LAT0, LON0 = 21.275, -157.825
KX = 111320 * math.cos(math.radians(LAT0))
KY = 110574


def to_m(lat, lon):
    return ((lon - LON0) * KX, (lat - LAT0) * KY)


def to_ll(e, n):
    return (LAT0 + n / KY, LON0 + e / KX)


class Frame:
    def __init__(self):
        b = math.radians(BEARING)
        self.ax = np.array([math.sin(b), math.cos(b)])              # +x
        self.ay = np.array([math.sin(b + math.pi / 2), math.cos(b + math.pi / 2)])  # +y (makai)
        w = np.array(to_m(*WEST_ANCHOR))
        e = np.array(to_m(*EAST_ANCHOR))
        span = (e - w) @ self.ax
        self.T = span / (N - 2)                                    # metres per tile
        self.x0 = w @ self.ax - self.T + SHIFT_X * self.T            # one tile margin, then the shift
        c = np.array(to_m(*COAST_ANCHOR))
        self.y0 = c @ self.ay - COAST_ANCHOR_Y * self.T

    def world_to_grid(self, e, n):
        p = np.array([e, n])
        return ((p @ self.ax - self.x0) / self.T, (p @ self.ay - self.y0) / self.T)

    def grid_to_world(self, gx, gy):
        p = self.ax * (gx * self.T + self.x0) + self.ay * (gy * self.T + self.y0)
        return float(p[0]), float(p[1])

    def tile_poly(self, x, y):
        return Polygon([self.grid_to_world(x + dx, y + dy) for dx, dy in ((0, 0), (1, 0), (1, 1), (0, 1))])

    def frame_poly(self, margin=0):
        return Polygon([self.grid_to_world(gx, gy) for gx, gy in
                        ((-margin, -margin), (N + margin, -margin), (N + margin, N + margin), (-margin, N + margin))])


def load_osm():
    return json.load(open(DATA / "osm_waikiki.json", encoding="utf-8"))["elements"]


def way_coords(el):
    return [to_m(p["lat"], p["lon"]) for p in el["geometry"]]


def polygons_of(el):
    """Polygons for a closed way or a multipolygon relation."""
    if el["type"] == "way":
        c = way_coords(el)
        if len(c) >= 4 and c[0] == c[-1]:
            p = Polygon(c)
            return [p if p.is_valid else p.buffer(0)]
        return []
    outers, inners = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or "geometry" not in m:
            continue
        line = [to_m(p["lat"], p["lon"]) for p in m["geometry"]]
        (inners if m.get("role") == "inner" else outers).append(LineString(line))
    polys = []
    for group, out in ((outers, True), (inners, False)):
        merged = linemerge(group) if group else None
        if merged is None:
            continue
        lines = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
        for ln in lines:
            if ln.is_ring:
                polys.append((Polygon(ln.coords).buffer(0), out))
    shell = unary_union([p for p, o in polys if o]) if polys else None
    if shell is None:
        return []
    holes = [p for p, o in polys if not o]
    if holes:
        shell = shell.difference(unary_union(holes))
    return list(shell.geoms) if shell.geom_type == "MultiPolygon" else [shell]


def land_polygon(elements, frame):
    """Land inside the map frame, from OSM coastline ways (land is on the left)."""
    fp = frame.frame_poly(margin=2)
    lines = [LineString(way_coords(e)) for e in elements
             if e["type"] == "way" and e.get("tags", {}).get("natural") == "coastline"]
    merged = linemerge(lines)
    merged_lines = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
    left = unary_union([ln.buffer(15, single_sided=True) for ln in merged_lines])
    right = unary_union([ln.buffer(-15, single_sided=True) for ln in merged_lines])
    pieces = split(fp, unary_union(merged_lines))
    land = []
    for piece in pieces.geoms:
        l, r = piece.intersection(left).area, piece.intersection(right).area
        if l > r:
            land.append(piece)
    return unary_union(land)


def coverage(frame, geoms):
    """Fraction of each tile covered by the union of geoms."""
    cov = np.zeros((N, N))
    if not geoms:
        return cov
    tree = STRtree(geoms)
    area = frame.T ** 2
    for x in range(N):
        for y in range(N):
            tp = frame.tile_poly(x, y)
            hits = tree.query(tp)
            if len(hits):
                cov[x, y] = min(1.0, sum(tp.intersection(geoms[i]).area for i in hits) / area)
    return cov


ROAD_CLASSES = {
    "motorway": 4, "trunk": 4, "primary": 4, "secondary": 3, "tertiary": 3,
    "unclassified": 2, "residential": 2, "living_street": 1,
}


MINOR_ROAD_MAX_SKEW = 14  # degrees


def rasterize_roads(elements, frame, min_class=2):
    """Road tiles, 4-connected so SimCity treats them as joined."""
    roads = np.zeros((N, N), dtype=np.int8)
    bridges = np.zeros((N, N), dtype=bool)
    names = {}
    for e in elements:
        t = e.get("tags", {})
        cls = ROAD_CLASSES.get(t.get("highway"))
        if e["type"] != "way" or cls is None or cls < min_class:
            continue
        if t.get("tunnel") == "yes" or t.get("access") == "private":
            continue
        pts = [frame.world_to_grid(*c) for c in way_coords(e)]
        prev = None
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if cls < 3:
                # minor streets only where they follow the grid; diagonal ones
                # would become jagged staircases of road tiles
                ang = math.degrees(math.atan2(by - ay, bx - ax)) % 90
                if MINOR_ROAD_MAX_SKEW < ang < 90 - MINOR_ROAD_MAX_SKEW:
                    prev = None
                    continue
            steps = max(1, int(math.hypot(bx - ax, by - ay) * 4))
            for s in range(steps + 1):
                gx, gy = ax + (bx - ax) * s / steps, ay + (by - ay) * s / steps
                cell = (int(math.floor(gx)), int(math.floor(gy)))
                if prev is not None and cell != prev and abs(cell[0] - prev[0]) + abs(cell[1] - prev[1]) == 2:
                    # diagonal step: add the corner tile nearer the line
                    c1, c2 = (cell[0], prev[1]), (prev[0], cell[1])
                    d1 = (c1[0] + .5 - gx) ** 2 + (c1[1] + .5 - gy) ** 2
                    d2 = (c2[0] + .5 - gx) ** 2 + (c2[1] + .5 - gy) ** 2
                    mid = c1 if d1 < d2 else c2
                    if 0 <= mid[0] < N and 0 <= mid[1] < N:
                        roads[mid] = max(roads[mid], cls)
                if 0 <= cell[0] < N and 0 <= cell[1] < N:
                    roads[cell] = max(roads[cell], cls)
                    if t.get("bridge") in ("yes", "viaduct", "culvert") or t.get("layer", "0") not in ("0", "-1"):
                        bridges[cell] = True
                    if t.get("name"):
                        names.setdefault(t["name"], set()).add(cell)
                prev = cell
    return roads, names, bridges


def building_height(t):
    for key in ("height", "building:height"):
        if key in t:
            try:
                return float(t[key].replace("m", "").split()[0])
            except ValueError:
                pass
    if "building:levels" in t:
        try:
            return float(t["building:levels"]) * 2.9 + 3
        except ValueError:
            pass
    return 7.0  # untagged: a typical 2-storey building


def buildings(elements):
    out = []
    for e in elements:
        t = e.get("tags", {})
        if "building" not in t or t.get("building") in ("roof", "construction", "no"):
            continue
        for p in polygons_of(e):
            if p.area > 15:
                out.append({"id": e["id"], "name": t.get("name", ""), "h": building_height(t),
                            "kind": t.get("building"), "tourism": t.get("tourism", ""), "poly": p})
    return out


def fetch_elevation(frame, land_cov):
    """Ground elevation (m) at tile centres, from USGS NED 10 m via OpenTopoData. Cached."""
    cache_path = DATA / "elevation_cache.json"
    cache = json.load(open(cache_path)) if cache_path.exists() else {}
    want = []
    for x in range(N):
        for y in range(N):
            if land_cov[x, y] > 0.05:
                lat, lon = to_ll(*frame.grid_to_world(x + .5, y + .5))
                key = f"{lat:.5f},{lon:.5f}"
                if key not in cache:
                    want.append(key)
    for i in range(0, len(want), 100):
        batch = want[i:i + 100]
        for attempt in range(5):
            r = requests.get("https://api.opentopodata.org/v1/ned10m",
                             params={"locations": "|".join(batch)}, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 + attempt * 2)
        r.raise_for_status()
        for key, res in zip(batch, r.json()["results"]):
            cache[key] = res["elevation"] if res["elevation"] is not None else 0.0
        json.dump(cache, open(cache_path, "w"))
        print(f"  elevation {min(i + 100, len(want))}/{len(want)}")
        time.sleep(1.1)
    elev = np.zeros((N, N))
    for x in range(N):
        for y in range(N):
            if land_cov[x, y] > 0.05:
                lat, lon = to_ll(*frame.grid_to_world(x + .5, y + .5))
                elev[x, y] = max(0.0, cache[f"{lat:.5f},{lon:.5f}"])
    return elev


def main():
    frame = Frame()
    print(f"tile size {frame.T:.1f} m, map {frame.T * N / 1000:.2f} km square")
    els = load_osm()

    land = land_polygon(els, frame)
    land_cov = coverage(frame, [land] if land.geom_type == "Polygon" else list(land.geoms))

    water_polys = []
    for e in els:
        t = e.get("tags", {})
        if t.get("natural") == "water" or t.get("waterway") in ("canal", "dock") or t.get("leisure") == "marina":
            if t.get("water") in ("pond", "reflecting_pool", "fountain") and t.get("name") is None:
                continue
            water_polys += polygons_of(e)
    water_cov = coverage(frame, water_polys)

    park_polys, golf_polys, beach_polys, resi_polys = [], [], [], []
    for e in els:
        t = e.get("tags", {})
        if t.get("leisure") in ("park", "pitch") or t.get("landuse") in ("grass", "recreation_ground", "cemetery") \
                or t.get("natural") in ("wood", "scrub", "grassland"):
            park_polys += polygons_of(e)
        elif t.get("leisure") == "golf_course":
            golf_polys += polygons_of(e)
        elif t.get("natural") == "beach":
            beach_polys += polygons_of(e)
        elif t.get("landuse") == "residential":
            resi_polys += polygons_of(e)
    park_cov = coverage(frame, park_polys)
    golf_cov = coverage(frame, golf_polys)
    beach_cov = coverage(frame, beach_polys)
    # residential land use: OSM's building footprints are missing across much of Kapahulu,
    # Kaimuki and St. Louis Heights, so placement.py also fills these areas with homes
    resi_cov = coverage(frame, resi_polys)

    roads, road_names, _ = rasterize_roads(els, frame)

    blds = buildings(els)
    bld_cov = coverage(frame, [b["poly"] for b in blds])
    # tallest building over each tile (by area overlap > 15% of tile or > 40% of building)
    tall = np.zeros((N, N))
    tree = STRtree([b["poly"] for b in blds])
    for x in range(N):
        for y in range(N):
            tp = frame.tile_poly(x, y)
            for i in tree.query(tp):
                b = blds[i]
                a = tp.intersection(b["poly"]).area
                if a > 0.15 * frame.T ** 2 or a > 0.4 * b["poly"].area:
                    tall[x, y] = max(tall[x, y], b["h"])

    print("fetching elevation ...")
    elev = fetch_elevation(frame, land_cov)

    np.savez_compressed(DATA / "grid.npz", land=land_cov, water=water_cov, park=park_cov, golf=golf_cov,
                        beach=beach_cov, resi=resi_cov, roads=roads, bld=bld_cov, tall=tall, elev=elev, T=frame.T)
    json.dump({k: sorted(v) for k, v in road_names.items()}, open(DATA / "road_names.json", "w", encoding="utf-8"),
              ensure_ascii=False)
    preview(land_cov, water_cov, park_cov, golf_cov, beach_cov, roads, tall, elev)
    print("wrote data/grid.npz and data/grid_preview.png")


def preview(land, water, park, golf, beach, roads, tall, elev, path=DATA / "grid_preview.png", scale=5):
    """Top-down debug image in grid space (x right, y down)."""
    from PIL import Image
    img = np.zeros((N, N, 3), dtype=np.uint8)
    for x in range(N):
        for y in range(N):
            if land[x, y] < 0.5 or water[x, y] > 0.5:
                c = (40, 90, 170)
            elif roads[x, y]:
                c = (60, 60, 60)
            elif tall[x, y] > 0:
                v = min(255, 120 + int(tall[x, y]))
                c = (v, v, int(v * 0.85))
            elif beach[x, y] > 0.4:
                c = (230, 210, 150)
            elif park[x, y] > 0.4 or golf[x, y] > 0.4:
                c = (60, 150, 60)
            else:
                g = min(200, 120 + int(elev[x, y]))
                c = (g, int(g * 0.8), int(g * 0.6))
            img[y, x] = c
    Image.fromarray(img).resize((N * scale, N * scale), Image.NEAREST).save(path)


if __name__ == "__main__":
    main()
