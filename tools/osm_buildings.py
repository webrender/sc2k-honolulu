"""OSM buildings for the map, in grid coordinates, grouped into renderable entities.

An entity is one OSM building outline plus any building:part pieces inside it
(OSM's 3D convention: when parts exist, they replace the outline).
"""
import json

from shapely.affinity import affine_transform
from shapely.strtree import STRtree

import geo


def to_grid_poly(poly, frame):
    # world (e, n) -> grid (gx, gy): gx = (P.ax - x0)/T, gy = (P.ay - y0)/T
    ax, ay, T = frame.ax, frame.ay, frame.T
    return affine_transform(poly, [ax[0] / T, ax[1] / T, ay[0] / T, ay[1] / T, -frame.x0 / T, -frame.y0 / T])


def num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace("m", "").replace(",", ".").split()[0].split(";")[0])
    except ValueError:
        return None


def height_of(t, default=7.0):
    h = num(t.get("height")) or num(t.get("building:height"))
    if h:
        return h
    lv = num(t.get("building:levels"))
    if lv:
        return lv * 2.9 + 3
    return default


def min_height_of(t):
    h = num(t.get("min_height"))
    if h is not None:
        return h
    lv = num(t.get("building:min_level"))
    return lv * 3.1 if lv else 0.0


def load(frame):
    main = json.load(open(geo.DATA / "osm_waikiki.json", encoding="utf-8"))["elements"]
    parts_raw = json.load(open(geo.DATA / "osm_parts.json", encoding="utf-8"))["elements"]
    hotels = [e for e in parts_raw if e.get("tags", {}).get("tourism") == "hotel"]
    frame_poly = to_grid_poly(frame.frame_poly(), frame)

    entities = []
    for e in main:
        t = e.get("tags", {})
        if "building" not in t or t.get("building") in ("roof", "no", "construction", "ruins"):
            continue
        for p in geo.polygons_of(e):
            g = to_grid_poly(p, frame)
            if g.area < 0.01 or not g.intersects(frame_poly):
                continue
            entities.append({
                "id": e["id"], "name": t.get("name", ""), "tags": t, "poly": g,
                "h": height_of(t), "parts": [],
            })

    parts = []
    for e in parts_raw:
        t = e.get("tags", {})
        if "building:part" not in t:
            continue
        for p in geo.polygons_of(e):
            g = to_grid_poly(p, frame)
            if g.area > 0.002:
                parts.append({"id": e["id"], "tags": t, "poly": g, "h": height_of(t, 0), "min_h": min_height_of(t)})

    tree = STRtree([en["poly"] for en in entities])
    for part in parts:
        c = part["poly"].representative_point()
        for i in tree.query(c):
            if entities[i]["poly"].buffer(0.02).contains(c):
                entities[i]["parts"].append(part)
                break

    for en in entities:
        if en["parts"]:
            hs = [p["h"] for p in en["parts"] if p["h"]]
            if hs:
                en["h"] = max(en["h"], max(hs))
        en["tourism"] = en["tags"].get("tourism", "")

    # attach hotel names from separate hotel features
    for h in hotels:
        t = h["tags"]
        if h["type"] == "node":
            pt = to_grid_poly(__import__("shapely.geometry", fromlist=["Point"]).Point(*geo.to_m(h["lat"], h["lon"])), frame)
            for i in tree.query(pt):
                if entities[i]["poly"].contains(pt) and not entities[i]["name"]:
                    entities[i]["name"] = t.get("name", "")
                    entities[i]["tourism"] = "hotel"
    return entities
