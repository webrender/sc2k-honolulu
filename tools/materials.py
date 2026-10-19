"""Procedural facade and roof materials for the sprite renderer.

A wall shader is called as fn(s, z, normal, edge_len, P) with arrays of along-edge
distance s (m) and height z (m); it returns an (N, 4) float array of RGBA 0..255.
A roof shader is fn(u, v, z, P).
"""
import numpy as np

from render3d import wall_light


def hexrgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


NAMED = {
    "white": "f2f0e8", "tan": "d2b48c", "beige": "e6dcc0", "gray": "a8a8a8", "grey": "a8a8a8",
    "brown": "8b6a4a", "pink": "f0a0b0", "green": "6a9a5a", "blue": "7090c0", "cream": "f4ecd0",
    "yellow": "e8d890", "red": "b04838", "black": "404040", "orange": "e09050",
}


def color(c, default="eeeae0"):
    if c is None:
        return hexrgb(default)
    c = c.strip().lower()
    if c in NAMED:
        return hexrgb(NAMED[c])
    try:
        return hexrgb(c)
    except ValueError:
        return hexrgb(default)


def _out(rgb, k):
    out = np.empty((rgb.shape[0], 4), dtype=np.float32)
    out[:, :3] = rgb * k
    out[:, 3] = 255
    return out


def solid(col):
    col = color(col) if isinstance(col, str) else col

    def fn(s, z, normal, edge_len, P):
        return _out(np.tile(col, (len(s), 1)), wall_light(normal))
    return fn


def tower(wall="eeeae0", glass="5a7088", floor_h=3.0, win=0.5, bay=4.0, pier=0.35,
          balcony=None, lobby_h=6.0, lobby="3c4650", base_z=0.0, top_band=0.0, band_col=None):
    """Concrete tower: horizontal window bands and piers. `balcony` adds a lighter
    slab line at each floor (the classic Waikiki look)."""
    wall, glass, lobby = color(wall), color(glass), color(lobby)
    bal = color(balcony) if balcony else None
    band = color(band_col) if band_col else wall

    def fn(s, z, normal, edge_len, P):
        k = wall_light(normal)
        zz = z - base_z
        f = (zz % floor_h) / floor_h
        is_glass = f >= (1 - win)
        if pier > 0:
            is_glass &= ((s % bay) / bay) > pier
        rgb = np.where(is_glass[:, None], glass, wall)
        if bal is not None:
            rgb = np.where((f < 0.18)[:, None], bal, rgb)
        if lobby_h > 0:
            rgb = np.where(((zz < lobby_h) & ((s % bay) / bay > 0.15))[:, None], lobby, rgb)
        if top_band > 0:
            ztop = P[:, 2].max() if len(P) else 0
            rgb = np.where((z > ztop - top_band)[:, None], band, rgb)
        # slight shading variation with the window glass picking up sky
        return _out(rgb, k)
    return fn


def curtain(glass="6a88a8", mullion="c8d0d8", floor_h=3.3, bay=3.0):
    glass, mullion = color(glass), color(mullion)

    def fn(s, z, normal, edge_len, P):
        k = wall_light(normal)
        f = (z % floor_h) / floor_h
        g = (s % bay) / bay
        rgb = np.where(((f < 0.12) | (g < 0.08))[:, None], mullion, glass)
        # vertical sky-gradient reflection
        t = np.clip(z / 120.0, 0, 1)[:, None]
        rgb = rgb * (0.85 + 0.25 * t)
        return _out(rgb, k)
    return fn


def mosaic_end(base, art):
    """Wall shader that paints `art(s_frac, z_frac) -> rgb or None` on short end walls
    (used for the Rainbow Tower)."""
    def fn(s, z, normal, edge_len, P):
        rgb = base(s, z, normal, edge_len, P)
        if edge_len < 25:
            zmax = max(1.0, P[:, 2].max())
            custom = art(s / max(edge_len, 1e-6), z / zmax)
            if custom is not None:
                sel, col = custom
                rgb[sel, :3] = col[sel] * wall_light(normal)
        return rgb
    return fn


def rainbow_art(sf, zf):
    """The Rainbow Tower's 26-storey mosaic: rainbow arc bands, top to bottom."""
    bands = [hexrgb(c) for c in ("d83a34", "ee7d30", "f2cf3a", "4fa64a", "3a72c4", "6a4aa8")]
    cx, cy = 0.5, 0.25
    r = np.hypot((sf - cx) * 1.6, zf - cy)
    col = np.zeros((len(sf), 3), dtype=np.float32) + hexrgb("f4f2ee")
    inside = (zf > 0.08) & (zf < 0.96)
    for i, bc in enumerate(bands):
        r0 = 0.62 - i * 0.07
        sel = inside & (r < r0) & (r >= r0 - 0.07) & (zf > cy)
        col[sel] = bc
    return inside, col


def roof(col="b8b4ac", edge="8a8680", pool=None):
    col, edge = color(col), color(edge)
    poolc = color("3aa8d8")

    def fn(u, v, z, P):
        rgb = np.tile(col, (len(u), 1))
        if pool is not None:
            (u0, v0, u1, v1) = pool
            sel = (u > u0) & (u < u1) & (v > v0) & (v < v1)
            rgb[sel] = poolc
        out = np.empty((len(u), 4), dtype=np.float32)
        out[:, :3] = rgb * 1.08
        out[:, 3] = 255
        return out
    return fn


def ground(kind="paving"):
    cols = {"paving": "a0a5a5", "grass": "4fad42", "sand": "e4b690", "pool": "54cde3", "lawn": "4fad42"}   # beads
    base = color(cols.get(kind, kind))

    def fn(u, v, z, P):
        # subtle speckle so the lot doesn't look like a flat fill
        noise = (np.sin(u * 1.7) * np.cos(v * 2.3)) * 6
        rgb = np.tile(base, (len(u), 1)) + noise[:, None]
        out = np.empty((len(u), 4), dtype=np.float32)
        out[:, :3] = rgb
        out[:, 3] = 255
        return out
    return fn


def patch(base_fn, rects, kind):
    """Ground shader with rectangular patches (pools, lawns) on top of base_fn."""
    pc = color({"pool": "3aa8d8", "grass": "5e9a48", "sand": "e2d4a0"}.get(kind, kind))

    def fn(u, v, z, P):
        out = base_fn(u, v, z, P)
        for (u0, v0, u1, v1) in rects:
            sel = (u > u0) & (u < u1) & (v > v0) & (v < v1)
            out[sel, :3] = pc
        return out
    return fn


def awning_wall(wall="f0a6b6", glass="6e4250", awning="3f8a6c", floor_h=3.8, bay=3.4, base_h=0.0):
    """Stucco wall with rows of windows, each under a little green canvas awning
    (the Royal Hawaiian). Per storey, bottom to top: wall, window, awning."""
    wall, glass, awning = color(wall), color(glass), color(awning)

    def fn(s, z, normal, edge_len, P):
        k = wall_light(normal)
        f = ((z - base_h) % floor_h) / floor_h
        g = (s % bay) / bay
        col = (g > 0.25) & (g < 0.75) & (z > base_h + floor_h * 0.3)
        rgb = np.tile(wall, (len(s), 1))
        rgb = np.where((col & (f >= 0.34) & (f < 0.67))[:, None], glass, rgb)
        rgb = np.where((col & (f >= 0.67))[:, None], awning, rgb)
        return _out(rgb, k)
    return fn
