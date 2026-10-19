"""Rebuild everything after geo.py has produced data/grid.npz.

    python tools/make_all.py                       # city + sprites + previews + checks
    python tools/make_all.py path/to/SC2K          # ...and the SCURK tile set (needs the game folder)
"""
import shutil
import sys
from pathlib import Path

import build_city
import check_city
import preview_iso
import preview_topdown
import tileset

if not build_city.TEMPLATE.exists():
    if len(sys.argv) < 2:
        sys.exit("pass the game folder: the build starts from the game's own DEFAULT.SC2")
    build_city.TEMPLATE.parent.mkdir(exist_ok=True)
    shutil.copy2(Path(sys.argv[1]) / "DEFAULT.SC2", build_city.TEMPLATE)
build_city.main()
tileset.main()
preview_topdown.main()
preview_iso.main()
ok = check_city.main(str(build_city.BUILD / "WAIKIKI.SC2"))
if len(sys.argv) > 1:
    import make_mif
    make_mif.build(sys.argv[1])
sys.exit(0 if ok else 1)
