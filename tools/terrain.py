"""Turn an elevation grid into SC2K ALTM / XTER / XBIT terrain.

Rules follow the game's TerrainRetile logic (as reimplemented in OpenSC2K,
native/core/sim/src/sim/tools/terrain.rs):
  * ALTM word: bits 0-4 land level, bits 5-9 water level, 10-15 tunnel.
  * Neighbouring tiles may differ by at most one level.
  * A tile's slope shape comes from which of its 8 neighbours are higher.
  * Water tiles have land below the sea level; XTER gets +0x20 (shore, one
    level deep) or +0x10 (deeper).
Grid index is x * 128 + y.
"""
import numpy as np

N = 128
SEA_LEVEL = 4

# XBIT flags (from the game, not the community spec, which lists them reversed)
XBIT_SALT = 0x01
XBIT_WATER = 0x04
XBIT_POWERABLE = 0x80

NEIGHBORS = [(0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1)]
NEIGHBOR_MASKS = [3, 2, 6, 4, 12, 8, 9, 1]
RAISE_BASIN = 50
# surface water (rivers, canals): XTER 0x30 + shape, chosen from water neighbours
CARDINAL_WATER_SHAPES = [13, 21, 18, 8, 19, 16, 5, 1, 20, 7, 17, 4, 6, 3, 2]
DIAGONAL_WATER_SHAPES = [0, 9, 10, 0, 11, 0, 0, 0, 12, 0, 0, 0, 0, 0, 0, 0]
SURFACE_WATER_FIRST = 0x30
WATERFALL = 0x3E
TERRAIN_SHAPES = [0x00, 0x09, 0x0A, 0x02, 0x0B, 0x0D, 0x03, 0x06,
                  0x0C, 0x01, 0x0D, 0x05, 0x04, 0x08, 0x07, RAISE_BASIN]


def limit_slopes(level, fixed):
    """Lower tiles until no neighbour pair differs by more than one level.
    `fixed` tiles (water) keep their level."""
    level = level.copy()
    changed = True
    while changed:
        changed = False
        padded = np.pad(level, 1, constant_values=99)
        lowest = np.full_like(level, 99)
        for dx, dy in NEIGHBORS:
            lowest = np.minimum(lowest, padded[1 + dx:N + 1 + dx, 1 + dy:N + 1 + dy])
        too_high = (level > lowest + 1) & ~fixed
        if too_high.any():
            level[too_high] = lowest[too_high] + 1
            changed = True
    return level


def shapes(level):
    """XTER slope shape per tile; raises enclosed one-tile basins like the game does."""
    level = level.copy()
    while True:
        padded = np.pad(level, 1, constant_values=-1)
        mask = np.zeros_like(level)
        for (dx, dy), m in zip(NEIGHBORS, NEIGHBOR_MASKS):
            higher = padded[1 + dx:N + 1 + dx, 1 + dy:N + 1 + dy] > level
            mask |= np.where(higher, m, 0)
        shape = np.array(TERRAIN_SHAPES)[mask]
        basin = shape == RAISE_BASIN
        if not basin.any():
            return level, shape
        level[basin] += 1


def water_shape(water, x, y):
    """LandscapeCommand._water_shape: 1 = y-1, 2 = x+1, 4 = y+1, 8 = x-1 are water."""
    def w(X, Y):
        return 0 <= X < N and 0 <= Y < N and water[X, Y]
    card = (1 if w(x, y - 1) else 0) | (2 if w(x + 1, y) else 0) | (4 if w(x, y + 1) else 0) | (8 if w(x - 1, y) else 0)
    if card < 15:
        return CARDINAL_WATER_SHAPES[card]
    miss = 0
    if x > 0 and y > 0 and not w(x - 1, y - 1):
        miss |= 1
    if x < N - 1 and y > 0 and not w(x + 1, y - 1):
        miss |= 2
    if x < N - 1 and y < N - 1 and not w(x + 1, y + 1):
        miss |= 4
    if x > 0 and y < N - 1 and not w(x - 1, y + 1):
        miss |= 8
    return DIAGONAL_WATER_SHAPES[miss]


def build(elev_m, is_water, level_m, sea_depth=None, salt=None, surface=None):
    """elev_m: ground elevation in metres (land tiles); is_water: bool grid.
    sea_depth: optional levels below sea level for water tiles (default 1).
    Returns (altm bytes, xter bytes, xbit bytes, land level grid)."""
    surface = np.zeros((N, N), dtype=bool) if surface is None else (surface & is_water)
    is_water = is_water & ~surface            # sea/sunken water; surface water sits on land
    land_lvl = SEA_LEVEL + np.round(np.maximum(elev_m, 0) / level_m).astype(int)
    land_lvl[surface] = SEA_LEVEL
    depth = np.ones((N, N), dtype=int) if sea_depth is None else sea_depth
    level = np.where(is_water, SEA_LEVEL - depth, land_lvl)
    level = np.clip(level, 0, 31)
    level = limit_slopes(level, is_water)
    # water tiles beside steep land must also respect the slope rule: raise them
    # (they stay below sea level, so they remain water)
    for _ in range(4):
        padded = np.pad(level, 1, constant_values=-99)
        highest = np.full_like(level, -99)
        for dx, dy in NEIGHBORS:
            highest = np.maximum(highest, padded[1 + dx:N + 1 + dx, 1 + dy:N + 1 + dy])
        low = is_water & (level < highest - 1)
        level[low] = np.minimum(highest[low] - 1, SEA_LEVEL - 1)
    level = limit_slopes(level, is_water)
    level, shape = shapes(level)

    water = level < SEA_LEVEL
    xter = shape.copy()
    xter[water] = shape[water] + np.where(SEA_LEVEL - level[water] == 1, 0x20, 0x10)

    all_water = water | surface
    for x, y in zip(*np.nonzero(surface)):
        xter[x, y] = WATERFALL if shape[x, y] != 0 else SURFACE_WATER_FIRST + water_shape(all_water, x, y)
    altm = np.where(all_water, level | (np.maximum(level, SEA_LEVEL) << 5), level).astype(">u2")
    water = all_water
    xbit = np.zeros((N, N), dtype=np.uint8)
    xbit[water] |= XBIT_WATER
    salt = water if salt is None else (salt & water)
    xbit[salt] |= XBIT_SALT
    return altm.reshape(-1).tobytes(), xter.astype(np.uint8).reshape(-1).tobytes(), \
        xbit.reshape(-1).tobytes(), level
