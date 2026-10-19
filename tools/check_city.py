"""Sanity checks for build/WAIKIKI.SC2 against the rules the game relies on."""
import struct
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from sc2file import City  # noqa: E402
import terrain as TR  # noqa: E402

N = 128
EXPECTED = {b"CNAM": 32, b"MISC": 4800, b"ALTM": 32768, b"XTER": 16384, b"XBLD": 16384, b"XZON": 16384,
            b"XUND": 16384, b"XTXT": 16384, b"XLAB": 6400, b"XMIC": 1200, b"XTHG": 480, b"XBIT": 16384,
            b"XTRF": 4096, b"XPLT": 4096, b"XVAL": 4096, b"XCRM": 4096, b"XPLC": 1024, b"XFIR": 1024,
            b"XPOP": 1024, b"XROG": 1024, b"XGRP": 3328}
FOOTPRINT = {}
for r, n in ((range(0x70, 0x8C), 1), (range(0x8C, 0xAE), 2), (range(0xAE, 0xC6), 3)):
    for i in r:
        FOOTPRINT[i] = n
FOOTPRINT[0xF7] = 2   # church (St. Augustine by the Sea)
FOOTPRINT[0xF8] = 3   # marina (Ala Wai Harbor)
for _hw in (0x65, 0x66, 0x67, 0x68):
    FOOTPRINT[_hw] = 2    # highway turns
HIGHWAY = set(range(0x49, 0x51)) | set(range(0x65, 0x6A))


def main(path):
    c = City.load(path)
    errors = []
    for cid, ln in EXPECTED.items():
        if len(c.chunks.get(cid, b"")) != ln:
            errors.append(f"chunk {cid} has {len(c.chunks.get(cid, b''))} bytes, expected {ln}")
    alt = np.array(struct.unpack(">16384H", c.chunks[b"ALTM"])).reshape(N, N)
    land = alt & 31
    wl = (alt >> 5) & 31
    ter = np.frombuffer(c.chunks[b"XTER"], np.uint8).reshape(N, N)
    bld = np.frombuffer(c.chunks[b"XBLD"], np.uint8).reshape(N, N)
    zon = np.frombuffer(c.chunks[b"XZON"], np.uint8).reshape(N, N)
    bit = np.frombuffer(c.chunks[b"XBIT"], np.uint8).reshape(N, N)
    water = bit & TR.XBIT_WATER > 0

    # slope rule
    for dx, dy in TR.NEIGHBORS:
        a = land[max(0, dx):N + min(0, dx), max(0, dy):N + min(0, dy)]
        b = land[max(0, -dx):N + min(0, -dx), max(0, -dy):N + min(0, -dy)]
        if (abs(a - b) > 1).any():
            errors.append(f"slope rule broken for neighbour {dx, dy}: {(abs(a - b) > 1).sum()} pairs")
    # terrain shape consistency (recompute like the game)
    _, shape = TR.shapes(land.copy())
    dry = ~water
    if (shape[dry] != ter[dry]).any():
        errors.append(f"{(shape[dry] != ter[dry]).sum()} dry tiles have a slope shape the game would retile")
    if (water & (wl != TR.SEA_LEVEL)).any():
        errors.append("water tiles with wrong water level")
    # buildings on flat dry land, consistent footprints
    for x in range(N):
        for y in range(N):
            b = bld[x, y]
            if (b >= 0x70 or b in HIGHWAY) and (ter[x, y] != 0 or water[x, y]):
                errors.append(f"{'highway' if b in HIGHWAY else 'building'} 0x{b:02X} on slope/water at {x, y}")
                break
    corners = Counter()
    for x in range(N):
        for y in range(N):
            if zon[x, y] & 0xF0 == 0xF0:
                corners["1x1"] += 1
            elif zon[x, y] & 0x10:
                n = FOOTPRINT.get(bld[x, y], 1)
                blk = bld[x:x + n, y:y + n]
                if blk.shape != (n, n) or (blk != bld[x, y]).any():
                    errors.append(f"footprint of 0x{bld[x, y]:02X} at {x, y} is inconsistent")
                corners[f"{n}x{n}"] += 1
    # roads on slopes must match their slope piece
    for x in range(N):
        for y in range(N):
            b = bld[x, y]
            if 0x1D <= b <= 0x2B and not (ter[x, y] == 0 or b == 0x1E + ter[x, y]):
                errors.append(f"road 0x{b:02X} on terrain 0x{ter[x, y]:02X} at {x, y}")
    print("buildings by footprint:", dict(corners))
    print("water tiles:", int(water.sum()), " road tiles:", int(((bld >= 0x1D) & (bld <= 0x2B)).sum()))
    print("altitude range:", int(land.min()), "-", int(land.max()))
    print("\n".join(errors[:30]) if errors else "all checks passed")
    return not errors


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else "build/WAIKIKI.SC2") else 1)
