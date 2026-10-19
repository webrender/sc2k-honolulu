# How it works

This project builds a SimCity 2000 diorama of Waikiki and Diamond Head for the Windows 95 Special Edition with
sc2kfix. The result is a city file (`WAIKIKI.SC2`), a custom tile set (`WAIKIKI.MIF`) and two small patches to
the installed game. Every colour on screen is a real Perler bead, because the city will be built as a Perler
bead piece.

Working conventions and the owner's preferences are in [CLAUDE.md](../CLAUDE.md). Read it first.

![Waikiki in the game](screenshot.webp)

## The map

- 128×128 tiles of **43.4 m**, on a grid aligned with Waikiki's streets (bearing 132°). +x runs toward
  Diamond Head and +y runs makai (toward the ocean). One altitude level is 26.6 m.
- **Framing** (`tools/geo.py`):
  - `COAST_ANCHOR_Y = 102` leaves about a quarter of the map as ocean along both bottom edges.
  - `SHIFT_X = 14` slides the frame east, so the ocean is seen curving around Diamond Head toward Kahala.
    Ala Wai Harbor, the Ala Moana Hotel and the west half of the Hilton fall off the west edge. That was
    accepted.
  - The whole Diamond Head crater must stay inside the map.
- **Hand-placed tile coordinates** must move with the frame if it ever changes: `placement.SPECIAL`,
  `placement.HARBOUR_*`, `placement.TIDY`, `build_city.DH_CENTRE` and `build_city.REEF_WIDTH`.

## Files

| Path | What it is |
|---|---|
| `data/osm_waikiki.json`, `data/osm_parts.json` | OpenStreetMap extract (Overpass queries in `data/*.txt`) |
| `data/elevation_cache.json` | USGS 10 m elevation per tile centre (OpenTopoData), cached |
| `data/grid.npz` | Rasterised geography written by `geo.py` |
| `data/perler_colors.json` | The 124 Perler beads (code, name, hex) from pixel-beads.com's 2026 chart |
| `data/stock_slot_usage.npy` | Pixel count per palette slot across all stock sprites (cache for `perler.py`) |
| `build/WAIKIKI.SC2` | The city |
| `build/WAIKIKI.MIF` | The tile set: custom buildings, terrain, water, trees and roads, plus re-pointed stock sprites |
| `build/sprites/` | Rendered building sprites (`<XBLD>_L/M/S.png`) and `names.json` |
| `build/preview_game.png`, `build/preview_game_waikiki.png` | The city drawn as the game draws it (the best check) |
| `build/preview_iso.png`, `build/preview_skyline.png`, `build/map_topdown.png` | Older previews and a debug map |
| `build/tileset_sheet.png`, `build/tileset_quantized.png`, `build/terrain_art.png`, `build/perler_palette.png` | Contact sheets |
| `templates/DEFAULT.SC2` | Blank city every build starts from |

## Pipeline

```bash
.venv/Scripts/python tools/geo.py                                      # only after changing the frame or OSM data
.venv/Scripts/python tools/patch_game.py "C:/Users/webre/Documents/SC2K"    # game closed; after palette/table changes
.venv/Scripts/python tools/make_all.py "C:/Users/webre/Documents/SC2K"      # city + sprites + checks + MIF
.venv/Scripts/python tools/preview_game.py "C:/Users/webre/Documents/SC2K"  # render it as the game would
```

Set `PYTHONIOENCODING=utf-8` when you redirect output, because place names contain ʻokina and macrons.
The project avoids SciPy; `tools/scipy_free.py` has the few grid helpers it needs.

1. **`geo.py`** projects OSM land, water, parks, golf, beach, residential land use, roads and buildings onto the
   grid. It fetches elevation only for points missing from the cache. The output is `data/grid.npz`.
2. **`build_city.py`** writes the `.sc2`:
   - **Terrain** follows the game's retiling rules (`terrain.py`, ported from OpenSC2K): one level per tile at
     most, with slope shapes from higher neighbours.
   - **Diamond Head** is exaggerated (`exaggerate_diamond_head`): the rim's relief is stretched, Leahi is
     raised to a sharp peak, and the outer flanks rise as steeply as the game allows.
   - **Water:** any water not joined to the ocean (the Ala Wai Canal, streams, ponds) is surface water.
   - **Reef depth:** `reef_depth` builds a smooth turquoise reef flat (`REEF_WIDTH` by shore x), then a
     three-tile slope ring, then flat deep water. See *Game patches* for why the ring shows as a third colour.
   - **Coast clean-up:** the beach is widened one tile, and stray islets in `TIDY` are drowned.
   - **Level ground:** special landmarks are flattened. The H-1 freeway (`highway.py`) runs at one level, on an
     embankment over low ground and in a cut through Kaimuki.
   - **Roads** are thinned to one tile and 4-connected, with slope pieces on hills.
3. **`placement.py`** decides what stands on every tile:
   - **Specials** (`SPECIAL`, hand-modelled, fixed spots):
     - St. Augustine by the Sea (0xF7);
     - Honolulu Zoo gate (0xC1) and savanna (0xC0);
     - Waikiki Shell (0xBF);
     - Waikiki Aquarium (0x9F, 2×2);
     - UH athletics (0xBE) and UH campus core (0xBD).
   - **UH Mānoa campus:** every tile within two tiles of a university building. Where 3×3 lots fit, it gets
     campus blocks (`CAMPUS_SLOTS` 0xB9–0xBC: lecture halls, labs, residence towers, Hawaiian studies, in a
     seeded weighted mix). The rest is lawn and monkeypods, with no houses.
   - **Landmarks:** the most prominent OSM buildings get unique 1×1, 2×2 or 3×3 sprites (`UNIQUE_SLOTS`).
     The Royal Hawaiian, the Moana and the Kaimana Beach Hotel are always included.
   - **Generic towers:** everything 13 m or taller uses one of 12 height classes (`GENERIC_SLOTS`).
   - **Homes (0x70–0x77):** placed on tiles with any OSM building (over 2% coverage). OSM footprints are missing
     across much of Kapahulu, Kaimuki and St. Louis Heights, so homes also go on residential land use and along
     residential streets. Parks, the zoo and the campus get no houses.
   - **Sloped residential tiles** get tree slot 0x07, redrawn as hillside homes, because the game can't put
     buildings on slopes.
   - **Vegetation:**
     - Kapiʻolani Park and other parks: open lawn with scattered shade trees.
     - The zoo grounds: dense planting.
     - Diamond Head: sparse scrub.
     - Ridges: forest.
     - Yards: palms and shade trees.
     - The beach: sand props in the rubble slots 1–4.
4. **`tileset.py`** renders every building sprite with the small 3D renderer in `render3d.py`. It also sends
   work to the modules below.
   - Landmarks are 3D models of their real OSM footprints and building parts. Famous ones get hand-set looks
     in `STYLES`.
   - The **Royal Hawaiian** is pink Spanish-Moorish, with a domed bell tower, slate-roofed corner towers and
     grey-blue flat roofs. The **Moana** is white, with a massive courtyard banyan.
   - **Tower walls** are bead pastels (`TOWER_COLOURS`), with coloured window tints (`GLASSES`).
   - `houses.py` draws the Hawaiian homes (white roofs, pastel walls), the church, the hillside homes and the
     old marina.
   - `parks.py` draws the zoo, the Shell, the aquarium, UH and the campus blocks.
   - `garden.py` adds hedges, flowering shrubs, palms and shade trees to every lot. Trees cast a Dark Green
     shadow. Tower lots get a paved drop-off with parked cars instead of a street hedge.
   - **SimCity 2000 line work** (`render3d.py`), copied from the stock art:
     - Pixels are hard. Supersampling only decides coverage, and colours are never blended.
     - At large and medium zoom, buildings get a dark outline wherever they stand in front of something
       farther away (`INK`). Roofs get a light rim along their near edges, and the near vertical corner
       gets a light line (`HIGHLIGHT`).
     - Shaded walls are at `SHADE` brightness. Plants (functions marked `@soft`) and props narrower than
       three pixels get no outline.
     - Towers of 20 m or more get a lift housing and air-conditioning boxes on the roof
       (`tileset.roof_kit`).
     - The look before this change is kept in `backup/pre_style/`.
5. **`make_mif.py`** quantises sprites to the Perler palette (in Lab colour, hue weighted above lightness).
   - It adds `terrain_art.py`'s ground, water, trees, lawns and tree-lined road pieces.
   - It re-points stock sprites that touch swapped palette slots.
   - It writes the MIF in winSCURK's layout. Extra sprites are appended; sc2kfix loads any sprite ID.
6. **`check_city.py`** runs automatically. It checks chunk sizes, the slope rule, shapes the game won't retile,
   buildings and highways only on flat dry land, footprints, and road slope pieces.

## Game patches (`tools/patch_game.py`)

Both edited files are backed up once to `<file>.orig`; `--restore` puts them back. `SIMCITY.EXE` can only be
patched while the game is closed.

- **`SIMCITY.EXE`:** the table that maps a tile's XTER terrain type to its sprite (`nXTERTileIDs`, VA
  0x4E7628). sc2kfix identifies the game by its PE timestamp, which the patch doesn't touch.
  - 0x20 (one level deep, flat) goes to sprite 5: the turquoise reef.
  - 0x11–0x1D (deeper water over a sloping seabed) go to sprite 0xFD: the mid-depth teal-blue ring.
  - 0x30–0x3D and 0x40–0x45 (surface water) go to sprite 0xF8: the dark-teal canal tile.
  - 0x10 (flat deep water) stays on sprite 270: deep azure.
- **`BITMAPS/PAL_MSTR.BMP`:** rebuilt from the original as the Perler palette (see below). The water-shimmer
  slots sc2kfix animates become a turquoise ripple (208–211) and an azure ripple (200–207).

## Borrowed sprite slots

The game's sprite table is full, so every new picture reuses an existing ID. Each ID has three zooms: small =
id, medium = 500 + id, large = 1000 + id.

| ID | Normally | Now |
|---|---|---|
| 1–4 | rubble | beach: sand, umbrellas, palms, surfboards |
| 5 | radioactivity | shallow reef water |
| 6, 8–12 | trees | palms and broadleaf canopy |
| 7 | trees | hillside homes |
| 13 | small park | lawn with a palm and a shade tree |
| 0x1D–0x2B | roads | roads lined with street trees (the sloped pieces 0x1F–0x22 are bare) |
| 0x70–0x77 | light residential | Hawaiian homes |
| 0xDB | statue | striped golf fairway |
| 0xF7 | church | St. Augustine by the Sea |
| 0xF8 | marina | Ala Wai Canal water (the marina art is unused while the harbour is off the map) |
| 0xFD | Forest Arcology | mid-depth water |
| 256–269 | terrain | green flats, yellow-green slopes, brown cliffs |
| 270–290 | water and shore | deep azure, turquoise shore with sand edge |
| 284 | water column | navy map-edge water |

## Perler bead palette (`tools/perler.py`)

- The goal is that the whole game, menus and interface art included, looks as close to the original as bead
  colours allow. Colour distance is CIEDE2000; plain Lab distance turns SimCity's saturated blues violet.
- Each slot becomes its nearest bead where it can. All 124 beads also need a fixed slot in 16–170. Which
  slots give up their colour for them is solved as a minimum-cost assignment (`scipy_free.assignment`). The
  cost is the extra colour change, weighted by how many pixels use each slot in the stock sprites
  (`data/stock_slot_usage.npy`) and in the interface art (`data/ui_slot_usage.npy`: `BITMAPS/*.BMP` and the
  EXE's bitmap resources).
- The 76 slots that give up their colour are listed in `remap`. The roughly 690 stock sprites that use them
  ship in the MIF, with their pixels moved to slots holding their nearest bead.
- `perler.py <game dir>` reports the average colour change per pixel: about 7 CIEDE2000 for both sprites and
  interface (it was 9 and 11 before the assignment was solved this way).
- Slots 1–15 and 246–255 belong to Windows. Slot 0 is Perler Black.
- The colour-cycling slots get their nearest beads, so the menus and toolbars show bead colours too.
- Terrain and water use named bead families (`terrain_art.FAMILIES`) with no dithering.
- `perler.py <game dir>` writes `build/perler_palette.png`, showing each slot's original colour next to its bead.

## Using it in the game

1. Copy `build/WAIKIKI.SC2` into `SC2K/CITIES` and `build/WAIKIKI.MIF` into `SC2K/SCURKART`. Run
   `patch_game.py` once, and again after palette or terrain-table changes.
2. Start `SC2K/SIMCITY.EXE` with the city path as its argument. Starting it from CD media skips sc2kfix and
   shows a "not properly registered" error.
3. Load `SCURKART/WAIKIKI.MIF` from the game's tile-set menu. A tile set isn't saved in the city, so reload it
   every session. After the MIF changes, reload it; after the SC2 changes, reopen the city.
4. Keep `weather_effects` false in `SC2K/settings.json`. sc2kfix rewrites that file on a clean exit, so edit it
   only while the game is closed.
5. Use the default rotation, with the ocean at the bottom. Building sprites don't rotate.
6. The city starts paused. It's a diorama: nothing is powered, and running the simulation will redevelop
   buildings. Marinas would spawn sailboats.

## Playing other cities: TROPICAL.MIF

`WAIKIKI.MIF` borrows sprite slots, so it isn't fit for a city that grows: industry would show hotels and
rubble would show beach towels. `tools/play_tileset.py <game dir>` builds `build/TROPICAL.MIF`, which keeps
every slot's meaning and only changes the look:

- **Terrain, water, trees and small parks:** the diorama's tropical art. Tree slot 7 is a tree again.
- **Flat roads:** lined with monkeypods, palms and flowering shrubs (as in the diorama).
- **Light residential (0x70–0x77):** the Hawaiian homes.
- **Other buildings:** the stock pictures, recoloured. Lots and trees take the diorama's greens. Pools and
  ponds take the sea's azure.
  - Homes, shops, offices and civic buildings also get warm walls (brick, brown, tan) lifted toward pastel
    (`PASTEL`).
  - Industry, construction sites, abandoned buildings and the fire station only get the greens.
  - The coloured zone line round each lot is never touched.
- **Ramps, tunnels and empty zoned land:** their tan bare ground becomes grass.
- **Everything else:** stock, including rubble, radiation, power lines, rails, bridges, highways, vehicles,
  disasters and the underground.
- **Review sheets:** `build/tropical_review/` shows every building, stock beside recoloured.

The two sets need different terrain tables in the EXE, so the game has two modes:

```bash
.venv/Scripts/python tools/patch_game.py "C:/Users/webre/Documents/SC2K" --play   # TROPICAL.MIF, any city
.venv/Scripts/python tools/patch_game.py "C:/Users/webre/Documents/SC2K"          # WAIKIKI.MIF, the diorama
```

- Both modes use the Perler palette, and both need the game closed. `patch_game.mode()` reports the current
  mode.
- In diorama mode, shallow sea in other cities draws as radiation with TROPICAL.MIF.
- In play mode, Waikiki loses its three-colour sea.
- `preview_game.py <game dir> --play CITIES/SIMCITY.SC2` draws any city with the play set
  (`build/preview_play.png`).

## Known limitations

- At 43 m per tile, every street takes a full tile, so minor off-grid streets are dropped.
- Buildings can't stand on slopes. Hilly neighbourhoods use the hillside-homes tree slot instead.
- The H-1 is a staircase of 2×2 blocks, since SimCity has no diagonal highway. Its in-game look (turns and
  crossings) is built from what the stock cities store, and was untested when this was written.
- Canal bridges are causeways rather than bridge pieces.
- Some OSM heights are estimated from floor counts, and a few look wrong (Holiday Inn Express at 44 floors).
- OSM building footprints are sparse in Kapahulu, Kaimuki and St. Louis Heights, so homes there are inferred.
- Overpass is often overloaded. Try `overpass.kumi.systems` and send a User-Agent header.

## Data and credits

- Map data © OpenStreetMap contributors, ODbL. Elevation: USGS NED 1/3″ via OpenTopoData.
- Perler colours from https://www.pixel-beads.com/perler-bead-color-chart.
- File formats: [dfloer/SC2k-docs](https://github.com/dfloer/SC2k-docs) and
  [OpenCity2k/SC2k-docs](https://github.com/OpenCity2k/SC2k-docs) (CC BY-SA 4.0), and the
  [OpenSC2K](https://github.com/OpenSC2K/OpenSC2K) source. Where they disagree (ALTM bit layout, XBIT flag
  order), the code follows OpenSC2K and the stock cities.
- Highway storage was read from the stock cities (e.g. `CITIES/TOKYO.SC2`). The XBLD direction letters map to
  the grid as T = x−1, B = x+1, R = y−1, L = y+1.
