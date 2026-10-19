"""Patch the Windows 95 SimCity 2000 SE install for the tropical water.

    python tools/patch_game.py "C:/Users/webre/Documents/SC2K"            # diorama mode (WAIKIKI.MIF)
    python tools/patch_game.py "C:/Users/webre/Documents/SC2K" --play     # play mode (TROPICAL.MIF)
    python tools/patch_game.py "C:/Users/webre/Documents/SC2K" --restore  # undo everything

The game must be closed. Both modes use the Perler palette; they differ only in the
terrain table. Diorama mode borrows sprite slots 5, 0xF8 and 0xFD for its three water
colours, which the play tile set leaves as radiation, the marina and the Forest
Arcology, so a city grown with TROPICAL.MIF needs play mode (the stock table).

Two changes, each backed up once to <file>.orig before the first write:
  SIMCITY.EXE   The table that maps a tile's XTER terrain type to its sprite
                (nXTERTileIDs, 0x4E7628, per sc2kfix's sc2k_1996.h) draws every
                flat water tile with sprite 270. Types 0x20 (one level deep) and
                0x30-0x45 (surface water) are repointed: one-level-deep sea at
                sprite 5 (shallow turquoise in WAIKIKI.MIF), so 270 can be deep
                azure, and every surface-water shape at the canal tile (0xF8). sc2kfix identifies the game by the PE timestamp, which
                this doesn't touch.
  PAL_MSTR.BMP  Rebuilt from the original as the Perler bead palette (perler.py):
                every slot the game draws with becomes a bead colour, all 124
                beads are present, and the water-shimmer slots sc2kfix animates
                become a turquoise ripple (208-211) and an azure one (200-207).
"""
import shutil
import struct
import sys
from pathlib import Path

import perler
from terrain_art import CANAL_ID, MID_ID, SHALLOW_ID

XTER_TABLE_VA = 0x4E7628
# XTER type -> sprite: shallow sea to the turquoise slot, every surface-water shape
# (canal, streams, ponds) to the full dark-teal canal tile
PATCHES = {0x20: SHALLOW_ID, **{t: MID_ID for t in range(0x11, 0x1E)},
           **{t: CANAL_ID for t in list(range(0x30, 0x3E)) + list(range(0x40, 0x46))}}
STOCK = {0x20: 270, 0x30: 270, **{t: 270 for t in range(0x11, 0x1E)}, **{t: 271 + t - 0x31 for t in range(0x31, 0x3E)},
         **{t: 285 + t - 0x40 for t in range(0x40, 0x46)}}


def va_to_offset(exe, va):
    pe = struct.unpack_from("<I", exe, 0x3C)[0]
    nsec = struct.unpack_from("<H", exe, pe + 6)[0]
    opt = struct.unpack_from("<H", exe, pe + 20)[0]
    rva = va - struct.unpack_from("<I", exe, pe + 24 + 28)[0]
    for i in range(nsec):
        s = pe + 24 + opt + 40 * i
        vsz, vaddr, rsz, raddr = struct.unpack_from("<IIII", exe, s + 8)
        if vaddr <= rva < vaddr + rsz:
            return raddr + rva - vaddr
    raise ValueError(f"0x{va:X} is not in the file")


def backup(path):
    orig = path.with_name(path.name + ".orig")
    if not orig.exists():
        shutil.copy2(path, orig)
        print(f"backed up {path.name} -> {orig.name}")
    return orig


def patch_exe(path, play=False):
    """Diorama mode: the water types go to the borrowed slots. Play mode: the stock table."""
    exe = bytearray(path.read_bytes())
    base = va_to_offset(exe, XTER_TABLE_VA)
    table = struct.unpack_from("<80H", exe, base)
    assert table[0x00:0x04] == (256, 257, 258, 259) and table[0x21] == 271, "not the SC2K 1996 XTER table"
    for t, sid in PATCHES.items():
        assert table[t] in (STOCK[t], SHALLOW_ID, sid), f"XTER 0x{t:02X} maps to {table[t]}, expected {STOCK[t]}"
    backup(path)
    for t, sid in PATCHES.items():
        struct.pack_into("<H", exe, base + 2 * t, STOCK[t] if play else sid)
    path.write_bytes(exe)
    if play:
        print(f"{path.name}: play mode, stock terrain table (water drawn with sprites 270-290)")
        return
    print(f"{path.name}: diorama mode, XTER 0x20 -> sprite {SHALLOW_ID}; deep water on a slope 0x11-0x1D -> sprite {MID_ID}; "
          f"surface water 0x30-0x45 -> sprite {CANAL_ID}")


def patch_palette(path, game):
    orig = backup(path)
    bmp = bytearray(orig.read_bytes())                 # always start from the stock palette
    assert bmp[:2] == b"BM" and struct.unpack_from("<H", bmp, 28)[0] == 8
    table = 14 + struct.unpack_from("<I", bmp, 14)[0]
    pal, names, remap = perler.game_palette(game)
    slots = [0] + list(range(16, 246))                 # 1-15 and 246-255 are Windows' own
    for idx in slots:
        r, g, b = (int(v) for v in pal[idx])
        bmp[table + 4 * idx:table + 4 * idx + 3] = bytes((b, g, r))
    path.write_bytes(bmp)
    print(f"{path.name}: {len(slots)} entries set to Perler beads "
          f"({len(set(names.values()))} distinct; {int((remap != range(256)).sum())} swapped slots re-pointed in the MIF)")


def restore(path):
    orig = path.with_name(path.name + ".orig")
    if orig.exists():
        shutil.copy2(orig, path)
        print(f"restored {path.name}")


def mode(game_dir):
    """'diorama', 'play' or 'stock', read from the EXE's terrain table."""
    exe = (Path(game_dir) / "SIMCITY.EXE").read_bytes()
    table = struct.unpack_from("<80H", exe, va_to_offset(exe, XTER_TABLE_VA))
    if table[0x20] == PATCHES[0x20]:
        return "diorama"
    pal = (Path(game_dir) / "BITMAPS" / "PAL_MSTR.BMP").read_bytes()
    orig = Path(game_dir) / "BITMAPS" / "PAL_MSTR.BMP.orig"
    return "play" if orig.exists() and orig.read_bytes() != pal else "stock"


def main(game_dir, undo=False, play=False):
    game = Path(game_dir)
    files = [game / "SIMCITY.EXE", game / "BITMAPS" / "PAL_MSTR.BMP"]
    if undo:
        for f in files:
            restore(f)
        return
    try:
        patch_exe(files[0], play)
    except PermissionError:
        sys.exit("SIMCITY.EXE is in use: close the game first")
    patch_palette(files[1], game)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], "--restore" in sys.argv[2:], "--play" in sys.argv[2:])
