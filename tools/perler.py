"""The Perler bead palette, and the game palette built from it.

The art is meant to become a Perler bead piece, so every colour the game shows
should be a real bead colour. data/perler_colors.json holds the 124 colours of the
2026 Perler chart (https://www.pixel-beads.com/perler-bead-color-chart).

    python tools/perler.py "C:/Users/webre/Documents/SC2K"   # report + build/perler_palette.png

SimCity 2000 draws everything through the 256-entry palette in BITMAPS/PAL_MSTR.BMP.
Every sprite (stock or ours) and most of the interface (toolbars, advisers, title and
menu art) store slot numbers, not colours. build_palette() rewrites the slots so the
whole game looks as close to the original as bead colours allow:
  * each slot becomes, where it can, the bead nearest its original colour (CIEDE2000);
  * all 124 Perler colours must be present somewhere in the fixed slots 16-170, so our
    own art can use any bead. Which slots give up their colour to hold the beads that
    nearest-matching leaves out is solved as an assignment problem
    (scipy_free.assignment): the least total colour change, weighted by how many
    pixels of the stock sprites and of the interface art (ui_usage) use each slot;
  * the colour-cycling slots (171-245) also get their nearest bead, and the water
    shimmer cycles (200-211) are set from bead blues by terrain_art.CYCLE_COLOURS.
A slot given a left-out colour no longer shows its stock colour, so build_palette
also returns `remap` (old slot -> a slot holding that slot's nearest bead), and
make_mif.py re-points every stock sprite that touches a swapped slot and packs it
into the MIF. The stock art then shows exactly its nearest beads.
Slots 1-15 and 246-255 belong to Windows and are left alone; slot 0 (black, used
by the stock art for outlines) becomes Perler Black.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIXED = np.arange(16, 171)
CYCLING = np.arange(171, 246)


def load():
    """[(name, code, rgb float32[3])] in chart order."""
    d = json.load(open(DATA / "perler_colors.json", encoding="utf-8"))
    return [(c["name"], c["code"], np.array([int(c["hex"][i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32))
            for c in d["colors"]]


COLORS = load()
NAMES = {n: rgb for n, _, rgb in COLORS}
RGB = np.array([rgb for _, _, rgb in COLORS])


def rgb(name):
    return NAMES[name].copy()


def hexof(name):
    return "".join(f"{int(v):02x}" for v in NAMES[name])


def ciede2000(lab1, lab2):
    """CIEDE2000 colour difference between broadcastable Lab arrays (..., 3)."""
    L1, a1, b1 = np.moveaxis(np.asarray(lab1, float), -1, 0)
    L2, a2, b2 = np.moveaxis(np.asarray(lab2, float), -1, 0)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lpm, Cpm = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hpm = np.where(C1p * C2p == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2,
                   np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = (1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm))
         + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63)))
    dtheta = 30 * np.exp(-((hpm - 275) / 25) ** 2)
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cpm, 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def dist2(a, b):
    """Squared CIEDE2000 colour difference between sRGB colours. Plain Lab distance
    would send SimCity's saturated blues to violet beads; CIEDE2000 corrects blue hues."""
    from make_mif import to_lab
    return ciede2000(to_lab(np.asarray(a, dtype=np.float32)), to_lab(np.asarray(b, dtype=np.float32))) ** 2


def nearest(c):
    return int(np.argmin(dist2(RGB, c)))


def build_palette(orig, weight):
    """orig: 256x3 game palette, weight: pixels per slot (stock sprites + interface art)
    -> (new palette, {slot: bead name}, remap: int[256] for stock sprite pixels)."""
    from scipy_free import assignment
    pal = orig.copy()
    d2 = dist2(orig[:, None, :], RGB[None, :, :])              # slot x bead
    assign = {int(s): int(d2[s].argmin()) for s in list(FIXED) + list(CYCLING) + [0]}
    # every bead needs a fixed slot: each bead claims one, at the cost of the extra colour
    # change there (zero at a slot whose nearest bead it already is)
    w = np.asarray(weight, dtype=np.float64) + 1.0
    extra = w[FIXED][None, :] * (d2[FIXED].T - d2[FIXED].min(1)[None, :])    # bead x slot
    for k, col in enumerate(assignment(extra)):
        assign[int(FIXED[col])] = k
    for s, k in assign.items():
        pal[s] = RGB[k]
    remap = np.arange(256)
    for s in assign:
        want = int(d2[s].argmin())
        if assign[s] != want:
            remap[s] = next(int(t) for t in FIXED if assign[int(t)] == want)
    return pal, {s: COLORS[k][0] for s, k in assign.items()}, remap


def stock_usage(game_dir):
    """Pixel count per palette slot over every stock sprite (cached in data/)."""
    path = DATA / "stock_slot_usage.npy"
    if path.exists():
        return np.load(path)
    from terrain_art import stock_sprites
    cnt = np.zeros(256, dtype=np.int64)
    for px in stock_sprites(game_dir).values():
        cnt += np.bincount(px[px >= 0], minlength=256)
    np.save(path, cnt)
    return cnt


def ui_usage(game_dir):
    """Pixel count per palette slot over the interface art: BITMAPS/*.BMP and the
    8-bit bitmaps inside SIMCITY.EXE (cached in data/). A bitmap with its own colour
    table is shown through the master palette by colour, so each of its colours
    counts at the original slot nearest it."""
    path = DATA / "ui_slot_usage.npy"
    if path.exists():
        return np.load(path)
    game = Path(game_dir)
    master = original_palette(game)

    def count(raw, off):
        hs, w, h, _, bpp, comp = struct.unpack_from("<IiiHHI", raw, off)
        if bpp != 8 or comp != 0:
            return 0
        ncol = struct.unpack_from("<I", raw, off + 32)[0] or 256
        stride = (w + 3) & ~3
        start = off + hs + 4 * ncol
        px = np.frombuffer(raw[start:start + stride * abs(h)], np.uint8)
        if len(px) < stride * abs(h):
            return 0
        cnt = np.bincount(px.reshape(abs(h), stride)[:, :w].ravel(), minlength=256)
        tab = np.zeros((256, 3))
        tab[:ncol] = np.frombuffer(raw[off + hs:start], np.uint8).reshape(ncol, 4)[:, [2, 1, 0]]
        same = np.abs(tab - master).sum(1) < 7
        slot = np.where(same, np.arange(256), ((tab[:, None] - master[None]) ** 2).sum(-1).argmin(1))
        return np.bincount(slot, weights=cnt, minlength=256)

    total = np.zeros(256)
    for f in sorted((game / "BITMAPS").glob("*.BMP")):
        if not f.name.upper().startswith("PAL_"):
            total += count(f.read_bytes(), 14)
    exe = game / "SIMCITY.EXE.orig"
    for raw in exe_bitmaps(exe if exe.exists() else game / "SIMCITY.EXE"):
        total += count(raw, 0)
    np.save(path, total)
    return total


def exe_bitmaps(path):
    """The RT_BITMAP resources (DIBs without a file header) of a PE file."""
    exe = Path(path).read_bytes()
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    nsec, opt_size = struct.unpack_from("<H", exe, pe + 6)[0], struct.unpack_from("<H", exe, pe + 20)[0]
    opt = pe + 24
    rsrc = struct.unpack_from("<I", exe, opt + 96 + 2 * 8)[0]
    secs = [struct.unpack_from("<8sIIII", exe, opt + opt_size + 40 * i)[1:] for i in range(nsec)]

    def off(rva):
        return next(ra + rva - va for vs, va, rs, ra in secs if va <= rva < va + max(vs, rs))
    base = off(rsrc)

    def entries(d):
        n = sum(struct.unpack_from("<HH", exe, base + d + 12))
        return [struct.unpack_from("<II", exe, base + d + 16 + 8 * i) for i in range(n)]
    out = []
    for typ, o in entries(0):
        if typ == 2 and o & 0x80000000:                    # RT_BITMAP
            for _, o2 in entries(o & 0x7FFFFFFF):
                for _, o3 in entries(o2 & 0x7FFFFFFF):
                    rva, size = struct.unpack_from("<II", exe, base + o3)
                    out.append(exe[off(rva):off(rva) + size])
    return out


def slot_weight(game_dir):
    """How much each slot's colour shows: stock sprite pixels plus interface pixels."""
    return stock_usage(game_dir) + ui_usage(game_dir)


def original_palette(game_dir):
    from make_mif import read_bmp_palette
    bmp = Path(game_dir) / "BITMAPS" / "PAL_MSTR.BMP"
    orig = bmp.with_name(bmp.name + ".orig")
    return read_bmp_palette(orig if orig.exists() else bmp)


def game_palette(game_dir):
    """(Perler palette with the water cycles, {slot: bead}, stock remap), from the original."""
    from terrain_art import CYCLE_COLOURS
    pal, names, remap = build_palette(original_palette(game_dir), slot_weight(game_dir))
    for idx, c in CYCLE_COLOURS.items():
        pal[idx] = c
    return pal, names, remap


def slots_of(pal, names, usable=FIXED):
    """Fixed slots holding any of the named bead colours."""
    want = np.array([NAMES[n] for n in names])
    return np.array([s for s in usable if (np.abs(want - pal[s]).sum(1) < 1).any()])


def report(game_dir):
    from PIL import Image, ImageDraw
    game = Path(game_dir)
    orig = original_palette(game)
    usage = slot_weight(game)
    pal, names, remap = build_palette(orig, usage)
    print(f"{int((remap != np.arange(256)).sum())} slots swapped to fit all {len(COLORS)} beads; stock pixels re-pointed")
    de = np.sqrt([float(dist2(orig[s], pal[s])) for s in range(256)])
    for label, w in (("stock sprites", stock_usage(game)), ("interface art", ui_usage(game))):
        w = np.asarray(w, dtype=float)
        print(f"mean colour change (CIEDE2000) per pixel of {label}: {(de * w).sum() / w.sum():.1f}")
    moved = sorted(((de[s] * usage[s], s) for s in names), reverse=True)
    print("largest colour shifts (weighted by use in sprites and interface):")
    for _, s in moved[:15]:
        print(f"  slot {s:3d} used {int(usage[s]):7d}  {tuple(int(v) for v in orig[s])} -> {names[s]} (dE {de[s]:.0f})")
    sheet = Image.new("RGB", (16 * 40, 16 * 20), "white")
    d = ImageDraw.Draw(sheet)
    for s in range(256):
        x, y = (s % 16) * 40, (s // 16) * 20
        d.rectangle([x, y, x + 19, y + 18], fill=tuple(int(v) for v in orig[s]))
        d.rectangle([x + 20, y, x + 38, y + 18], fill=tuple(int(v) for v in pal[s]))
    sheet.save(ROOT / "build" / "perler_palette.png")
    print("wrote build/perler_palette.png (each slot: original | bead)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    report(sys.argv[1])
