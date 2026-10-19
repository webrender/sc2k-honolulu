"""Build everything from your own copy of the game and install it, in one step.

    python tools/install.py "C:/Games/SC2K"              # the Waikiki diorama (default)
    python tools/install.py "C:/Games/SC2K" --play       # play any city with the tropical tile set
    python tools/install.py "C:/Games/SC2K" --restore    # put the game back as it was

The game must be closed. It needs SimCity 2000 Special Edition for Windows 95 with sc2kfix.
The first two forms:
  1. patch SIMCITY.EXE's terrain table for the chosen mode and BITMAPS/PAL_MSTR.BMP to the
     Perler palette (patch_game.py; both files are backed up to *.orig first);
  2. build the city and the tile sets from the game's own art (make_all.py, play_tileset.py);
  3. copy WAIKIKI.SC2 to CITIES/, and WAIKIKI.MIF, TROPICAL.MIF and TROPSTK.MIF to SCURKART/.
Switching mode later only needs patch_game.py (step 1). --restore undoes step 1 and
leaves the copied files, which do nothing until you load them. TROPSTK.MIF is the one set
meant for the restored (unpatched) game.
"""
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BUILD = TOOLS.parent / "build"


def run(script, *args):
    print(f"\n== {script} {' '.join(args)}")
    r = subprocess.run([sys.executable, str(TOOLS / script), *args], cwd=TOOLS)
    if r.returncode:
        sys.exit(f"{script} failed (exit {r.returncode})")


def main(argv):
    if not argv or argv[0].startswith("-"):
        sys.exit(__doc__)
    game = Path(argv[0])
    if not (game / "SIMCITY.EXE").exists() or not (game / "DATA" / "LARGE.DAT").exists():
        sys.exit(f"{game} doesn't look like the SimCity 2000 Special Edition folder")
    if "--restore" in argv:
        run("patch_game.py", str(game), "--restore")
        return
    play = "--play" in argv
    run("patch_game.py", str(game), *(["--play"] if play else []))
    run("make_all.py", str(game))
    run("play_tileset.py", str(game))
    for src, dst in ((BUILD / "WAIKIKI.SC2", game / "CITIES"), (BUILD / "WAIKIKI.MIF", game / "SCURKART"),
                     (BUILD / "TROPICAL.MIF", game / "SCURKART"), (BUILD / "TROPSTK.MIF", game / "SCURKART")):
        shutil.copy2(src, dst / src.name)
        print(f"copied {src.name} -> {dst}")
    if play:
        print("\nPlay mode. Start the game, open any city, and load SCURKART/TROPICAL.MIF from the tile-set menu.")
    else:
        print("\nDiorama mode. Start SIMCITY.EXE with CITIES/WAIKIKI.SC2 and load SCURKART/WAIKIKI.MIF from the "
              "tile-set menu. Keep the city paused.")


if __name__ == "__main__":
    main(sys.argv[1:])
