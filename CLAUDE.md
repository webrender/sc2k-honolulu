# Working on the Waikiki SimCity 2000 diorama

[docs/TECHNICAL.md](docs/TECHNICAL.md) describes how the project works; [README.md](README.md) is the public overview. This file holds what isn't in the code: the owner's
preferences, the decisions already made, and how to build, check, install and launch.

## The setup

- **Game:** SimCity 2000 Special Edition for Windows 95, with sc2kfix Release 11b, at
  `C:\Users\webre\Documents\SC2K`. The GOG copy is DOS-only and no longer used.
- **Python:** `.venv/Scripts/python`. Set `PYTHONIOENCODING=utf-8` when redirecting output.
- **Not a git repository.** Back up game files before overwriting them; `patch_game.py` keeps `.orig` copies.

## The loop the owner uses

The owner reviews in the game itself. "Open the game" or "start the game" means launch it:

```powershell
Start-Process -FilePath "C:\Users\webre\Documents\SC2K\SIMCITY.EXE" -ArgumentList '"C:\Users\webre\Documents\SC2K\CITIES\WAIKIKI.SC2"' -WorkingDirectory "C:\Users\webre\Documents\SC2K"
```

Check `Get-Process SIMCITY` first; it may already be running. After launching, remind the owner to load
`SCURKART\WAIKIKI.MIF` from the tile-set menu. It isn't saved with the city.

After every change:

1. Rebuild with `tools/make_all.py "C:/Users/webre/Documents/SC2K"`. Run `tools/geo.py` first only if the frame
   or OSM data changed.
2. If the palette, the water-shimmer colours or the XTER table changed, run `tools/patch_game.py`. The EXE part
   needs the game **closed**. The palette alone can be written while it runs (`patch_game.patch_palette`), but
   it only takes effect on restart.
3. Render with `tools/preview_game.py "C:/Users/webre/Documents/SC2K"` and look at the relevant crop of
   `build/preview_game.png`. Screen position of tile (x, y) at level z:
   `(2048 + (x - y) * 16, 504 + (x + y) * 8 - z * 12)`.
4. Run `tools/check_beads.py`. Every pixel must be a Perler bead.
5. Copy `build/WAIKIKI.SC2` to `SC2K\CITIES\` and `build/WAIKIKI.MIF` to `SC2K\SCURKART\`, and compare hashes.
   If the game is open, tell the owner to reopen the city or reload the tile set.

**Two modes.** The diorama (WAIKIKI.MIF) needs the patched terrain table. Playing any other city with
`TROPICAL.MIF` needs play mode: `tools/patch_game.py <game> --play`. Check `patch_game.mode()` before
launching, and switch only with the game closed. After changing shared art (terrain, trees, roads, homes,
palette), rebuild both sets: `make_all.py` and `play_tileset.py`. Install both MIFs, and copy them to
`dist/` (the prebuilt sets in the repository).

Only edit `SC2K\settings.json` while the game is closed. sc2kfix rewrites it on exit. `weather_effects` stays
false.

## The owner's preferences and decisions

**Colour**
- **Every colour must be a Perler bead** from `data/perler_colors.json`. The owner is making a Perler bead piece.
  The source chart is https://www.pixel-beads.com/perler-bead-color-chart, which supersedes their spreadsheet.
  - Pick new art colours as bead hexes, and keep the palette build and stock re-pointing in the pipeline.
  - The palette keeps every slot as close to its original colour as beads allow, menus included
    (`perler.build_palette`: CIEDE2000, a minimum-cost assignment weighted by sprite and interface use).
- **Solid colour fills, no dithering.** Speckled ground was rejected.
- The skyline should be **more colourful than real life**: pastel bead towers and tinted glass. Creative licence
  is given, but loud accents that "stick out like a sore thumb" aren't wanted. The rust-red UH roofs were
  softened to Stone.

**Look**
- **Tropical and green:** lush grass, many palms and shade trees, and hedges and flowering shrubs on every lot.
  Roads are tree-lined.
- **Houses:** white roofs, with colourful pastel walls.
- **Readability over scale:** exaggerating is fine where it helps. Diamond Head's rim and Leahi, the 2×2 church,
  the massive Moana banyan and the tall Waikiki Shell are all larger than life.
- **Sea:** three colours, with smooth curves and no jagged bits or stray squares. Turquoise reef, then a
  teal-blue ring, then deep azure. Map-edge water is navy.

**Framing**
- About a quarter ocean along both bottom edges, with the ocean visibly curving around Diamond Head.
- Diamond Head must stay fully on the map. Losing Ala Wai Harbor and the Ala Moana area off the west edge was
  accepted.

**Landmarks the owner asked for**
- **Moana Surfrider:** white, with a massive banyan filling its courtyard.
- **Royal Hawaiian:** pink, with grey-blue (not teal) flat roofs and a domed bell tower.
- **St. Augustine by the Sea:** 2×2.
- **Kapiʻolani Park:** the Honolulu Zoo, the Waikiki Shell, and the Waikiki Aquarium down the road.
- **UH Mānoa:** campus buildings in place of houses, and the stadium.
- **H-1:** as a real highway.

**Reference images.** The owner often shares photos and satellite views. Compare against them and propose
concrete changes.

## Gotchas

- **The sprite table is full.** New pictures must borrow an existing ID at all three zooms; see the table in
  docs/TECHNICAL.md. 0xF8 is the canal tile only while `placement.MARINAS` is empty.
- **Only 3×3 landmark slots are free.** The 1×1 and 2×2 unique slots are all used. A new 2×2 special takes a slot
  from the least prominent landmark.
- **Buildings and highways need flat, dry land.** `check_city.py` enforces this. Specials are flattened in
  `build_city.py`.
- **Moving the frame** (`geo.SHIFT_X`, `geo.COAST_ANCHOR_Y`) means moving every hand-placed tile coordinate;
  docs/TECHNICAL.md lists them.
- **Sprite depth sorting** is approximate. A tall object inside or behind another can show through, as trees
  once did inside the Shell. Check close-ups.
- **Overpass:** the main server is often at capacity. `overpass.kumi.systems` works; send a User-Agent header.
- **Unverified in the game:** the H-1 highway pieces (turns and crossings) and the mid-depth water band were
  built from file analysis and the preview. Ask the owner how they look.
