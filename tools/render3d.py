"""Tiny isometric renderer that draws SimCity 2000-style building sprites.

Scene units are metres in the building's local frame:
  u  along grid +x (toward Diamond Head), v along grid +y (toward the ocean), z up.
The footprint is n x n tiles of `tile_m` metres. A sprite is 32*n px wide at large
zoom (16*n medium, 8*n small); the footprint diamond sits at the bottom of the image.

Projection (SC2K's 2:1 dimetric view, camera above the +x/+y corner):
  sx = (gx - gy) * half_w          gx, gy in tiles
  sy = (gx + gy) * half_h - z * vpx
"""
import math

import numpy as np
from PIL import Image, ImageDraw

SS = 3  # supersampling factor (coverage only: colours are never blended)
OUTLINES = True
INK = 0.42        # an outline pixel is its surface colour darkened to this fraction
HIGHLIGHT = 0.55  # roof rims and near corners move this far toward white
SHADE = 0.66      # brightness of a wall facing away from the light


class Scene:
    def __init__(self, n, tile_m, tile_px=32, vexag=1.0):
        self.n, self.T, self.tile_px = n, tile_m, tile_px
        self.hw, self.hh = tile_px / 2, tile_px / 4
        # px per metre vertically, matching the true scale of the ground plane
        self.vpx = 0.866 * tile_px / (math.sqrt(2) * tile_m) * vexag
        self.faces = []  # (points, shader, kind, bias, soft)
        self.soft_on = False
        self.min_cover = 0.45  # share of a pixel a surface must cover to be drawn

    # -- projection -----------------------------------------------------
    def project(self, u, v, z):
        gx, gy = u / self.T, v / self.T
        return ((gx - gy) * self.hw, (gx + gy) * self.hh - z * self.vpx)

    @staticmethod
    def depth(u, v, z):
        # distance toward the camera (bigger = nearer)
        return (u + v) * 0.6124 + z * 0.5

    # -- geometry ---------------------------------------------------------
    def add_quad(self, pts3, shader, kind="wall", bias=0.0):
        """Planar quad/polygon given by 3D points; shader(a, b) gets plane coords."""
        self.faces.append((pts3, shader, kind, bias, self.soft_on))

    def add_prism(self, footprint, z0, z1, wall, roof=None, bias=0.0):
        """Extrude a polygon footprint [(u, v), ...] (any winding) from z0 to z1."""
        pts = list(footprint)
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        # make counter-clockwise in (u, v) so outward normals are to the right of each edge
        area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))
        if area < 0:
            pts = pts[::-1]
        for i in range(len(pts)):
            (u1, v1), (u2, v2) = pts[i], pts[(i + 1) % len(pts)]
            nu, nv = (v2 - v1), -(u2 - u1)  # outward normal for CCW polygon
            if nu + nv <= 1e-9:
                continue  # faces away from the camera
            ln = math.hypot(nu, nv)
            self.add_quad([(u1, v1, z0), (u2, v2, z0), (u2, v2, z1), (u1, v1, z1)],
                          (wall, (nu / ln, nv / ln), math.hypot(u2 - u1, v2 - v1)), "wall", bias)
        if roof is not None:
            self.add_quad([(u, v, z1) for u, v in pts], (roof, None, 0), "roof", bias)

    # -- rasterisation --------------------------------------------------------
    def render(self, height_px=None):
        n, ss = self.n, SS
        W = int(self.tile_px * n)
        # find the top of the drawing
        top = 0.0
        for pts3, *_ in self.faces:
            for u, v, z in pts3:
                top = min(top, self.project(u, v, z)[1])
        ground_h = n * self.hh * 2
        H = height_px or int(math.ceil(ground_h - top)) + 2
        Wss, Hss = W * ss, H * ss
        # screen offset: footprint top corner (0,0,0) maps to (W/2, H - ground_h - 1)
        ox, oy = W / 2, H - ground_h - 1
        img = np.zeros((Hss, Wss, 4), dtype=np.float32)
        zbuf = np.full((Hss, Wss), -1e9, dtype=np.float32)
        fbuf = np.full((Hss, Wss), -1, dtype=np.int32)
        ys, xs = np.mgrid[0:Hss, 0:Wss]
        px = (xs + 0.5) / ss - ox
        py = (ys + 0.5) / ss - oy
        # per face: 0 = building surface, 1 = plant (soft), 2 = flat on the ground; and wall or not
        ftype, fwall = [], []

        for fi, (pts3, shader, kind, bias, soft) in enumerate(self.faces):
            flat = kind != "wall" and max(p[2] for p in pts3) < 0.3
            ftype.append(2 if (flat or bias <= -1000) else 1 if soft else 0)
            fwall.append(kind == "wall")
            scr = [self.project(*p) for p in pts3]
            mask_img = Image.new("L", (Wss, Hss), 0)
            ImageDraw.Draw(mask_img).polygon([((x + ox) * ss, (y + oy) * ss) for x, y in scr], fill=255)
            m = np.asarray(mask_img) > 0
            if not m.any():
                continue
            # affine inverse: screen -> plane coords (a, b) via the first three points
            p0, p1, p3 = np.array(pts3[0]), np.array(pts3[1]), np.array(pts3[-1])
            e1, e2 = p1 - p0, p3 - p0
            s0, s1, s3 = np.array(scr[0]), np.array(scr[1]), np.array(scr[-1])
            M = np.column_stack([s1 - s0, s3 - s0])
            if abs(np.linalg.det(M)) < 1e-9:
                continue
            Minv = np.linalg.inv(M)
            qx, qy = px[m] - s0[0], py[m] - s0[1]
            a = Minv[0, 0] * qx + Minv[0, 1] * qy
            b = Minv[1, 0] * qx + Minv[1, 1] * qy
            P = p0[None, :] + a[:, None] * e1[None, :] + b[:, None] * e2[None, :]
            d = self.depth(P[:, 0], P[:, 1], P[:, 2]) + bias
            fn, normal, edge_len = shader
            if kind == "wall":
                # along-edge distance (m) and height (m)
                s = a * np.linalg.norm(e1[:2])
                rgba = fn(s, P[:, 2], normal, edge_len, P)
            else:
                rgba = fn(P[:, 0], P[:, 1], P[:, 2], P)
            idx_y, idx_x = np.nonzero(m)
            closer = d > zbuf[idx_y, idx_x]
            opaque = rgba[:, 3] > 0.5
            sel = closer & opaque
            zbuf[idx_y[sel], idx_x[sel]] = d[sel]
            img[idx_y[sel], idx_x[sel]] = rgba[sel]
            fbuf[idx_y[sel], idx_x[sel]] = fi

        # Hard pixels, no blending (SimCity 2000 sprites have no soft edges): a covered
        # pixel takes its centre sample, or its most common sample if the centre missed;
        # the sub-samples only decide coverage.
        k = ss * ss

        def sub(a):
            return a.reshape(H, ss, W, ss, *a.shape[2:]).swapaxes(1, 2).reshape(H, W, k, *a.shape[2:])
        img_s, z_s, f_s = sub(img), sub(zbuf), sub(fbuf)
        cover = f_s >= 0
        alpha = cover.mean(axis=2)
        c8 = np.clip(img_s[..., :3], 0, 255).astype(np.int64)
        key = np.where(cover, (c8[..., 0] << 16) | (c8[..., 1] << 8) | c8[..., 2], -1)
        score = (key[..., :, None] == key[..., None, :]).sum(axis=3) * cover
        centre = k // 2
        score[..., centre] = np.where(cover[..., centre], 100, 0)
        pick = score.argmax(axis=2)[..., None]
        rgb = np.take_along_axis(img_s[..., :3], pick[..., None], axis=2)[:, :, 0]
        dep = np.take_along_axis(z_s, pick, axis=2)[..., 0]
        fid = np.take_along_axis(f_s, pick, axis=2)[..., 0]
        on = alpha >= self.min_cover
        fid[~on] = -1
        dep[~on] = -1e9
        if self.tile_px >= 16 and OUTLINES:
            rgb = self._ink(rgb, dep, fid, np.array(ftype + [2]), np.array(fwall + [False]))
        out = np.zeros((H, W, 4), dtype=np.uint8)
        out[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        out[..., 3] = np.where(on, 255, 0)
        return Image.fromarray(out, "RGBA")

    def _ink(self, rgb, dep, fid, ftype, fwall):
        """SimCity 2000's line work: a dark outline wherever a building's edge stands in
        front of something farther away (or nothing), a light rim along the near edges
        of its roofs, and a light line down its near vertical corner."""
        H, W = fid.shape
        thr = 4.0 * 32 / self.tile_px          # depth jump (m) that counts as an edge
        t = ftype[fid]                         # fid -1 picks the trailing "ground" entry
        wall = fwall[fid]
        solid = (fid >= 0) & (t == 0)

        def pad(a, v):
            return np.pad(a, 1, constant_values=v)
        D, F, Tt, Wl = pad(dep, -1e9), pad(fid, -1), pad(t, 2), pad(wall, False)
        shifts = {"up": (0, 1), "down": (2, 1), "left": (1, 0), "right": (1, 2)}
        nb = {name: (D[r:r + H, c:c + W], F[r:r + H, c:c + W], Tt[r:r + H, c:c + W], Wl[r:r + H, c:c + W])
              for name, (r, c) in shifts.items()}
        # an outline needs at least three pixels of continuous surface behind it, so
        # slivers and tiny props (umbrellas, AC units) keep their colour
        cont = lambda a, b: (a > -1e8) & (b > -1e8) & (np.abs(a - b) < thr)
        D2 = np.pad(dep, 2, constant_values=-1e9)
        opposite = {"up": (1, 0), "down": (-1, 0), "left": (0, 1), "right": (0, -1)}
        edge = np.zeros_like(solid)
        for name, (d, f, _, _) in nb.items():
            dy, dx = opposite[name]
            in1 = D2[2 + dy:2 + dy + H, 2 + dx:2 + dx + W]
            in2 = D2[2 + 2 * dy:2 + 2 * dy + H, 2 + 2 * dx:2 + 2 * dx + W]
            edge |= (f != fid) & (d < dep - thr) & cont(dep, in1) & cont(in1, in2)
        edge &= solid
        # roof rim: a roof pixel sitting directly on top of a wall of a building
        _, fd, td, wd = nb["down"]
        rim = solid & ~wall & (fd != fid) & wd & (td == 0) & ~edge
        # near corner: a wall pixel on the lit face whose right neighbour is another face, joined to it
        dr, fr, tr, wr = nb["right"]
        corner = solid & wall & wr & (tr == 0) & (fr != fid) & (np.abs(dr - dep) < thr) & ~edge
        lum = rgb @ np.array([0.30, 0.59, 0.11], dtype=np.float32)
        lr = np.pad(lum, 1)[1:H + 1, 2:W + 2]
        corner &= lum > lr
        out = rgb.copy()
        hi = rim | corner
        out[hi] = out[hi] * (1 - HIGHLIGHT) + 255 * HIGHLIGHT
        out[edge] = out[edge] * INK
        return out


# -- lighting -------------------------------------------------------------------
LIGHT = np.array([-0.35, 0.75, 0.0])  # light from screen-left (+v side), slightly from -u
LIGHT /= np.linalg.norm(LIGHT)


def wall_light(normal):
    nu, nv = normal
    # shaded faces sit at half brightness, as in the stock art, so pastel walls keep their depth
    return SHADE + (1.0 - SHADE) * max(0.0, nu * LIGHT[0] + nv * LIGHT[1])


def soft(fn):
    """Decorator for plant helpers fn(scene, ...): their faces get no outline."""
    import functools

    @functools.wraps(fn)
    def wrapped(sc, *a, **k):
        prev, sc.soft_on = sc.soft_on, True
        try:
            return fn(sc, *a, **k)
        finally:
            sc.soft_on = prev
    return wrapped


def rgba(col, k=1.0):
    return np.array([col[0] * k, col[1] * k, col[2] * k, 255.0], dtype=np.float32)
