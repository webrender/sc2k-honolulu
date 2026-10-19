"""DOS SimCity 2000 sprite files (LARGE/SMALL/OTHER .HED + .DAT).

HED: 1500 entries of 8 bytes, indexed by sprite id: u32 LE offset into the DAT,
u8 height, u8 width, 0xFFFF. Unused entries are all 0xFF.
Sprite ids: small = object id, medium = 500 + id, large = 1000 + id.
DAT rows: 0x10, L, then L-1 bytes of runs: [0x04, n] skips n transparent pixels,
[0x0C, n, n palette indices] draws pixels. A sprite ends with 0x00. A one-row empty
sprite (10 01 00) is a placeholder that keeps the game's own artwork.
"""
import struct

import numpy as np

PLACEHOLDER = bytes([0x10, 0x01, 0x00])


def read_hed(hed):
    out = {}
    for i in range(len(hed) // 8):
        off, h, w, _ = struct.unpack_from("<IBBH", hed, i * 8)
        if off != 0xFFFFFFFF:
            out[i] = (off, h, w)
    return out


def decode(dat, off, h, w):
    px = np.full((h, w), -1, dtype=int)
    i = off
    for y in range(h):
        if dat[i] != 0x10:
            raise ValueError(f"row {y}: expected 0x10 at {i}, got {dat[i]:#x}")
        n = dat[i + 1]
        end = i + 1 + n
        i += 2
        x = 0
        while i < end:
            op, cnt = dat[i], dat[i + 1]
            if op == 0x04:
                x += cnt
                i += 2
            elif op == 0x0C:
                px[y, x:x + cnt] = list(dat[i + 2:i + 2 + cnt])
                x += cnt
                i += 2 + cnt
            else:
                raise ValueError(f"row {y}: unknown run op {op:#x}")
        if i != end:
            raise ValueError(f"row {y}: overran row")
    if dat[i] != 0x00:
        raise ValueError(f"missing sprite end at {i}")
    return px, i + 1


def encode(px):
    h, w = px.shape
    out = bytearray()
    for y in range(h):
        line = px[y]
        row = bytearray()
        x = 0
        # trailing transparency is implicit
        last = w
        while last > 0 and line[last - 1] < 0:
            last -= 1
        while x < last:
            start = x
            transparent = line[x] < 0
            while x < last and (line[x] < 0) == transparent and x - start < 255:
                x += 1
            cnt = x - start
            if transparent:
                row += bytes([0x04, cnt])
            else:
                row += bytes([0x0C, cnt]) + bytes(int(v) for v in line[start:x])
        if len(row) + 1 > 255:
            raise ValueError("row too long for DOS sprite format")
        out += bytes([0x10, len(row) + 1]) + row
    out.append(0x00)
    return bytes(out)


def build(sprites, ids):
    """sprites: {sprite_id: px array or None (placeholder)}; ids: every id the HED lists.
    Returns (hed bytes, dat bytes)."""
    hed = bytearray(b"\xff" * 12000)
    dat = bytearray()
    for sid in sorted(ids):
        px = sprites.get(sid)
        if px is None:
            data, h, w = PLACEHOLDER, 1, ids[sid]
        else:
            data, h, w = encode(px), px.shape[0], px.shape[1]
        struct.pack_into("<IBBH", hed, sid * 8, len(dat), h, w, 0xFFFF)
        dat += data
    return bytes(hed), bytes(dat)
