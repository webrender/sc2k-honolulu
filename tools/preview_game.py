"""Draw the city with the game's own sprites, roughly the way SimCity 2000 does.

    python tools/preview_game.py "C:/Users/webre/Documents/SC2K"
    python tools/preview_game.py "C:/Users/webre/Documents/SC2K" --play CITIES/SIMCITY.SC2
        (any city with build/TROPICAL.MIF and the stock terrain table; writes build/preview_play.png)

Reads build/WAIKIKI.SC2 and build/WAIKIKI.MIF, plus the game's DATA/*.DAT sprites,
BITMAPS/PAL_MSTR.BMP palette and SIMCITY.EXE terrain table (patched or not). Writes
build/preview_game.png (the whole map, large zoom) and build/preview_game_waikiki.png
(the skyline from the harbour to Diamond Head). Not pixel-exact: no animation, and
slope sprites are anchored approximately. It's for checking art without the game.
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import make_mif
import patch_game
import terrain_art
from sc2file import City

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
N = 128
HW, HH, STEP = 16, 8, 12
TOP = 32 * STEP + 120


def screen(x, y, z):
    return N * HW + (x - y) * HW, TOP + (x + y) * HH - z * STEP


def load_sprites(game, mif=BUILD / "WAIKIKI.MIF"):
    spr = {}
    for f in ("SMALLMED.DAT", "LARGE.DAT", "SPECIAL.DAT"):
        spr.update(terrain_art.read_archive(game / "DATA" / f))
    _, pieces = make_mif.read_pieces(Path(mif).read_bytes())
    for tag, sid, w, px in pieces:
        if tag == "SHAP" and px.shape[0] > 1:
            spr[sid] = px
    return spr


def xter_table(game):
    exe = (game / "SIMCITY.EXE").read_bytes()
    return struct.unpack_from("<80H", exe, patch_game.va_to_offset(exe, patch_game.XTER_TABLE_VA))


def to_rgba(px, pal):
    out = np.zeros(px.shape + (4,), dtype=np.uint8)
    m = px >= 0
    out[m, :3] = pal[px[m]].astype(np.uint8)
    out[m, 3] = 255
    return Image.fromarray(out, "RGBA")


def main(game_dir, play_city=None):
    game = Path(game_dir)
    pal = make_mif.read_bmp_palette(game / "BITMAPS" / "PAL_MSTR.BMP")
    spr = load_sprites(game, BUILD / ("TROPICAL.MIF" if play_city else "WAIKIKI.MIF"))
    table = list(xter_table(game))
    for t, sid in patch_game.PATCHES.items():      # show the mode's table, whichever is installed
        table[t] = patch_game.STOCK[t] if play_city else sid
    city = City.load(game / play_city if play_city else BUILD / "WAIKIKI.SC2")
    alt = np.array(struct.unpack(">16384H", city.chunks[b"ALTM"])).reshape(N, N)
    land, wl = alt & 31, (alt >> 5) & 31
    ter = np.frombuffer(city.chunks[b"XTER"], np.uint8).reshape(N, N)
    bld = np.frombuffer(city.chunks[b"XBLD"], np.uint8).reshape(N, N)
    zon = np.frombuffer(city.chunks[b"XZON"], np.uint8).reshape(N, N)
    cache = {}

    def sprite(sid):
        if sid not in cache:
            cache[sid] = to_rgba(spr[sid], pal) if sid in spr else None
        return cache[sid]

    W, H = N * HW * 2 + 64, TOP + N * HH * 2 + 64
    img = Image.new("RGBA", (W, H), (30, 34, 40, 255))

    def blit(sid, x, y, z, n=1):
        im = sprite(1000 + sid)
        if im is None:
            return
        bx, by = screen(x + 1, y + 1, z)
        img.alpha_composite(im, (int(bx - im.width / 2), int(by - im.height + 1 + (n - 1) * 0)))

    for s in range(2 * N - 1):
        for x in range(max(0, s - N + 1), min(N, s + 1)):
            y = s - x
            t = int(ter[x, y])
            water = t >= 0x10
            z = int(wl[x, y]) if water else int(land[x, y])
            blit(table[t] if t < len(table) else 256, x, y, z)
            b = int(bld[x, y])
            if not b:
                continue
            if b >= 0x70:
                corners = zon[x, y] & 0xF0
                if corners == 0xF0 or corners & 0x40:      # 1x1, or the bottom corner of a bigger building
                    blit(b, x, y, int(land[x, y]))
            else:
                blit(b, x, y, z)
    img = img.convert("RGB")
    if play_city:
        img.save(BUILD / "preview_play.png")
        print("wrote build/preview_play.png")
        return
    img.save(BUILD / "preview_game.png")
    lx, ly = screen(0, 80, 0)
    bx, by = screen(118, 128, 0)
    img.crop((int(lx) - 100, int(ly) - 600, int(bx) + 350, int(by) + 40)).save(BUILD / "preview_game_waikiki.png")
    print("wrote build/preview_game.png and build/preview_game_waikiki.png")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    play = sys.argv[sys.argv.index("--play") + 1] if "--play" in sys.argv else None
    main(sys.argv[1], play)
