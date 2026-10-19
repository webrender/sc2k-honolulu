"""Pack the rendered sprites into a SCURK tile set (.MIF) for SimCity 2000 SE (Windows 95).

    python tools/make_mif.py "C:/Users/webre/Documents/SC2K"

Writes build/WAIKIKI.MIF. It reads from the game folder:
  BITMAPS/PAL_MSTR.BMP   the palette (a MIF stores palette indices, not colours)
  SCURKART/TILESET1.MIF  a winSCURK-saved set, for the INFO block and sprite order

Format (checked against every .MIF in the game's SCURKART folder):
  "MIFF" u32 len "SC2K"
  "INFO" u32 0x72 <0x72 bytes from winSCURK, starting "NIW_"; copied verbatim>
  "TILE" u32 len u16 piece_count, then pieces:
     "SHAP" u32 len  u16 sprite_id  u16 width  u16 height  u32 data_len  <data>
     "NAME" u32 len  u16 object_id  u16 text_len  <text, NUL-padded to even length>
  winSCURK always writes all 184 objects (552 sprites) in a fixed order: large
  (1000 + id), medium (500 + id), small (id), then that object's NAME if it has
  one. Objects the set doesn't replace get a 1-pixel-high empty placeholder.
  Sprites with no winSCURK slot (terrain, water) follow the 552; sc2kfix's loader
  accepts any sprite ID taller than 1 px, so they replace the game's own art.
  Sprite data is a stream of [count, mode] chunks: 1 = start a row (count = its
  byte length), 3 = skip count pixels, 4 = count palette indices padded to even,
  2 = end of sprite. All integers big-endian.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import perler
import terrain_art
from make_til import quantize

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
SPRITES = BUILD / "sprites"
VIEW_OFFSET = {"L": 1000, "M": 500, "S": 0}
# 0-15 and 246-255 are Windows system colours; 171-239 are the colour-cycling
# slots (water, lights). Stock SCURK art only uses 16-170.
USABLE = np.arange(16, 171)
PLACEHOLDER = bytes([0, 1, 2, 1, 2, 2])


def read_bmp_palette(path):
    raw = Path(path).read_bytes()
    assert raw[:2] == b"BM", "not a BMP"
    header_size = struct.unpack_from("<I", raw, 14)[0]
    bpp = struct.unpack_from("<H", raw, 28)[0]
    assert bpp == 8, f"expected an 8-bit BMP, got {bpp}-bit"
    colors_used = struct.unpack_from("<I", raw, 46)[0] or 256
    off = 14 + header_size
    pal = np.zeros((256, 3), dtype=np.float32)
    for i in range(min(colors_used, 256)):
        b, g, r = raw[off + 4 * i:off + 4 * i + 3]
        pal[i] = (r, g, b)
    return pal


def to_lab(rgb):
    """sRGB 0-255 (..., 3) -> CIE Lab (D65)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.2126, 0.0193], [0.3576, 0.7152, 0.1192], [0.1805, 0.0722, 0.9505]])
    xyz /= np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def quantize_building(img, pal, allowed, light_weight=0.55):
    """Building sprite -> the nearest Perler bead, matched in Lab with lightness
    counting for less than hue and chroma: a shaded pastel wall becomes a deeper
    bead of the same colour rather than a grey one. Truly neutral pixels (white
    walls, grey roofs) only match the neutral beads."""
    a = np.asarray(img.convert("RGBA"), dtype=np.float32)
    rgb, alpha = a[..., :3], a[..., 3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    spread = pal[allowed].max(1) - pal[allowed].min(1)
    greys, colours = allowed[spread < 10], allowed

    def nearest(cands, lab):
        d = lab[..., None, :] - to_lab(pal[cands])[None, None]
        d[..., 0] *= light_weight
        return cands[np.argmin((d ** 2).sum(-1), axis=-1)]

    lab = to_lab(rgb)
    idx = np.where(sat < 0.06, nearest(greys, lab), nearest(colours, lab))
    return np.where(alpha > 127, idx, -1)


def encode_pixels(px):
    h, w = px.shape
    out = bytearray()
    for y in range(h):
        line = px[y]
        row = bytearray()
        x = 0
        while x < w:
            transparent = line[x] < 0
            start = x
            while x < w and (line[x] < 0) == transparent and x - start < 255:
                x += 1
            count = x - start
            if transparent:
                if x < w:  # trailing transparency needs no chunk
                    row += bytes([count, 3])
            else:
                row += bytes([count, 4]) + bytes(int(v) for v in line[start:x])
                if count % 2:
                    row.append(0)
        if len(row) > 255:
            raise ValueError("sprite row needs more than 255 bytes")
        out += bytes([len(row), 1]) + row
    out += bytes([2, 1, 2, 2])
    return bytes(out)


def shape_payload(sprite_id, px):
    h, w = px.shape
    data = encode_pixels(px)
    return struct.pack(">HHHI", sprite_id, w, h, len(data)) + data


def name_payload(object_id, text):
    b = text.encode("ascii", "replace")[:23]
    if len(b) % 2:
        b += b"\0"
    return struct.pack(">HH", object_id, len(b)) + b


def to_bytes(info, pieces):
    tile = struct.pack(">H", len(pieces))
    for tag, payload in pieces:
        tile += tag + struct.pack(">I", len(payload)) + payload
    body = b"SC2K" + b"INFO" + struct.pack(">I", len(info)) + info + b"TILE" + struct.pack(">I", len(tile)) + tile
    return b"MIFF" + struct.pack(">I", len(body)) + body


def build(game_dir, out=BUILD / "WAIKIKI.MIF"):
    game = Path(game_dir)
    pal = read_bmp_palette(game / "BITMAPS" / "PAL_MSTR.BMP")
    want, _, remap = perler.game_palette(game)
    if not np.allclose(pal[16:246], want[16:246]):
        sys.exit("PAL_MSTR.BMP isn't the Perler palette yet: run tools/patch_game.py first")
    stock_pal = perler.original_palette(game)
    terrain_art.STOCK_PAL = stock_pal
    template = (game / "SCURKART" / "TILESET1.MIF").read_bytes()
    info, stock = read_pieces(template)
    layout = [(sid, w) for tag, sid, w, _ in stock if tag == "SHAP"]
    assert len(layout) == 552

    names = json.load(open(SPRITES / "names.json", encoding="utf-8"))
    ours = {}
    for key in names:
        obj = int(key, 16)
        for view, offset in VIEW_OFFSET.items():
            ours[offset + obj] = quantize_building(Image.open(SPRITES / f"{key}_{view}.png"), pal, USABLE)
    # beach props (the repurposed rubble slots) stand on sand; the land around them is grass
    stock = terrain_art.stock_sprites(game)
    for obj in (0x01, 0x02, 0x03, 0x04):
        for offset in VIEW_OFFSET.values():
            if offset + obj in ours:
                ours[offset + obj] = terrain_art.underlay(ours[offset + obj],
                                                          terrain_art.sand_floor(stock, offset, pal, USABLE))
    # tropical terrain, water, trees and lawns in place of the stock ones (needs sc2kfix)
    ours.update(terrain_art.sprites(game, pal, USABLE, stock_pal))
    # the harbour sprite has no water of its own: lay shimmering shallow water under it
    for off, tp in terrain_art.ZOOM_TILE_PX.items():
        if "F8" in names:                 # a marina placement (its slot is the canal otherwise)
            floor = terrain_art.water_floor(ours[off + terrain_art.SHALLOW_ID], 3, tp)
            ours[off + terrain_art.MARINA_ID] = terrain_art.underlay(ours[off + terrain_art.MARINA_ID], floor)

    # stock sprites that touch a slot the Perler palette gave another bead: re-point
    # their pixels to slots holding their nearest bead, and ship them in the MIF
    swapped = np.nonzero(remap != np.arange(256))[0]
    repointed = set()
    for sid, px in stock.items():
        if sid in ours or not np.isin(px, swapped).any():
            continue
        ours[sid] = np.where(px >= 0, remap[np.maximum(px, 0)], -1)
        repointed.add(sid)
    print(f"{len(repointed)} stock sprites re-pointed to Perler slots")
    # tree-lined streets: the flat road pieces get monkeypods and palms along their sides
    for piece in terrain_art.STREET_ARMS:
        for off, tp in terrain_art.ZOOM_TILE_PX.items():
            sid = off + piece
            base = ours.get(sid, stock[sid])
            ours[sid] = terrain_art.street_trees(base, tp, piece, pal, USABLE)
            repointed.add(sid)           # stock-derived: keeps its own outline pixels

    pieces = []
    for sid, width in layout:
        if sid in ours:
            px = ours[sid]
            # (a re-pointed stock sprite keeps its own size; sc2kfix reads it from the header)
            assert (px.shape[1] == width or sid in repointed or sid % 500 in terrain_art.BORROWED_WATER
                    or sid - 1000 in terrain_art.BORROWED_WATER), f"sprite {sid} is {px.shape[1]} px wide, slot is {width}"
            pieces.append((b"SHAP", shape_payload(sid, px)))
        else:
            pieces.append((b"SHAP", struct.pack(">HHHI", sid, width, 1, len(PLACEHOLDER)) + PLACEHOLDER))
        if sid < 500 and f"{sid:02X}" in names:
            pieces.append((b"NAME", name_payload(sid, ascii_name(names[f"{sid:02X}"]))))
    # terrain and water have no winSCURK slot; sc2kfix loads any sprite ID, so append them
    slots = {sid for sid, _ in layout}
    for sid in sorted(set(ours) - slots):
        pieces.append((b"SHAP", shape_payload(sid, ours[sid])))
    data = to_bytes(info, pieces)
    verify(data, layout, ours, repointed)
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)} bytes, {len(names)} objects)")
    save_quantized_preview({s: p for s, p in ours.items() if s - 1000 in {int(k, 16) for k in names}}, pal)
    return data


def ascii_name(name):
    for a, b in (("ʻ", "'"), ("ī", "i"), ("ā", "a"), ("ū", "u"), ("ō", "o"), ("ē", "e")):
        name = name.replace(a, b)
    for cut in (" by Hilton Grand Vacations", ", LXR Hotels & Resorts", " Resort and Spa", " Resort & Spa",
                " Waikiki Beach", " Beach Resort", " Hotel"):
        if len(name) > 23:
            name = name.replace(cut, "")
    return name[:23]


def verify(data, layout, ours, stock_ids=()):
    _, pieces = read_pieces(data)
    shaps = [p for p in pieces if p[0] == "SHAP"]
    assert [sid for _, sid, _, _ in shaps[:len(layout)]] == [sid for sid, _ in layout], "sprite order differs from winSCURK's"
    assert {sid for _, sid, _, _ in shaps} >= set(ours), "a sprite is missing"
    for _, sid, _, px in shaps:
        if sid in ours:
            assert px.shape == ours[sid].shape and (px == ours[sid]).all(), f"sprite {sid} did not round-trip"
            # 16-170, plus the water shimmer cycles 200-211 that terrain_art.py uses on purpose
            if sid in stock_ids:
                continue              # stock art keeps its outline black and animated slots
            ok = (px < 0) | ((px >= 16) & (px <= 170)) | ((px >= 200) & (px <= 211))
            assert ok.all(), f"sprite {sid} uses a reserved palette entry"


def save_quantized_preview(preview, pal):
    """Contact sheet of the sprites as the game will colour them."""
    items = sorted(preview.items())
    cw = max(p.shape[1] for _, p in items) + 8
    ch = max(p.shape[0] for _, p in items) + 8
    cols = 10
    rows = (len(items) + cols - 1) // cols
    sheet = np.full((rows * ch, cols * cw, 3), (200, 214, 226), dtype=np.uint8)
    for i, (_, px) in enumerate(items):
        y0 = (i // cols) * ch + ch - 4 - px.shape[0]
        x0 = (i % cols) * cw + (cw - px.shape[1]) // 2
        mask = px >= 0
        region = sheet[y0:y0 + px.shape[0], x0:x0 + px.shape[1]]
        region[mask] = pal[px[mask]].astype(np.uint8)
    img = Image.fromarray(sheet)
    img.resize((img.width * 2, img.height * 2), Image.NEAREST).save(BUILD / "tileset_quantized.png")


# --- reader -----------------------------------------------------------------------
def read_pieces(data):
    """-> (info bytes, [(tag, id, width, pixels or name)])."""
    assert data[:4] == b"MIFF" and data[8:12] == b"SC2K"
    assert struct.unpack(">I", data[4:8])[0] == len(data) - 8
    assert data[12:16] == b"INFO"
    info_len = struct.unpack(">I", data[16:20])[0]
    info = data[20:20 + info_len]
    pos = 20 + info_len
    assert data[pos:pos + 4] == b"TILE"
    tile_len = struct.unpack(">I", data[pos + 4:pos + 8])[0]
    assert pos + 8 + tile_len == len(data)
    count = struct.unpack(">H", data[pos + 8:pos + 10])[0]
    pos += 10
    pieces = []
    for _ in range(count):
        tag, ln = data[pos:pos + 4], struct.unpack(">I", data[pos + 4:pos + 8])[0]
        payload = data[pos + 8:pos + 8 + ln]
        pos += 8 + ln
        if tag == b"SHAP":
            sid, w, h, dl = struct.unpack(">HHHI", payload[:10])
            assert 10 + dl == len(payload)
            pieces.append(("SHAP", sid, w, decode(payload[10:], w, h)))
        else:
            assert tag == b"NAME", tag
            oid, tl = struct.unpack(">HH", payload[:4])
            assert 4 + tl == len(payload)
            pieces.append(("NAME", oid, None, payload[4:].split(b"\0")[0].decode("latin-1")))
    assert pos == len(data)
    return info, pieces


def decode(data, w, h):
    px = np.full((h, w), -1, dtype=int)
    y, x, i = -1, 0, 0
    while i < len(data):
        cnt, mode = data[i], data[i + 1]
        i += 2
        if mode == 0:  # no-op; only in Maxis-made sets
            continue
        elif mode == 1:
            y, x = y + 1, 0
        elif mode == 2:
            return px
        elif mode == 3:
            x += cnt
        elif mode == 4:
            if 0 <= y < h:
                px[y, x:x + cnt] = list(data[i:i + cnt])[:max(0, w - x)]
            x += cnt
            i += cnt + (cnt & 1)
        else:
            raise AssertionError(f"bad chunk mode {mode}")
    raise AssertionError("missing sprite end")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    build(sys.argv[1])
