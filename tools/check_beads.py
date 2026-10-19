"""Check that a rendered preview uses only Perler bead colours.

    python tools/check_beads.py [build/preview_game.png]

Prints the beads used and any off-palette colours. The preview's dark background,
(30, 34, 40), is the one expected exception.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import perler

BACKGROUND = (30, 34, 40)


def main(path):
    px = np.asarray(Image.open(path).convert("RGB")).reshape(-1, 3)
    cols, counts = np.unique(px, axis=0, return_counts=True)
    names = {tuple(int(v) for v in rgb): n for n, _, rgb in perler.COLORS}
    used = [(int(c), names[tuple(int(v) for v in col)]) for col, c in zip(cols, counts)
            if tuple(int(v) for v in col) in names]
    bad = [(tuple(int(v) for v in col), int(c)) for col, c in zip(cols, counts)
           if tuple(int(v) for v in col) not in names and tuple(int(v) for v in col) != BACKGROUND]
    print(f"{len(used)} beads used; most common: {[n for _, n in sorted(used, reverse=True)[:12]]}")
    if bad:
        print(f"OFF-PALETTE colours ({len(bad)}): {sorted(bad, key=lambda t: -t[1])[:20]}")
        return False
    print("every pixel is a Perler bead")
    return True


if __name__ == "__main__":
    ok = main(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "build" / "preview_game.png")
    sys.exit(0 if ok else 1)
