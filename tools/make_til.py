"""Build the DOS SimCity 2000 graphics for the Waikiki buildings.

    python tools/make_til.py "C:/GOG Games/SimCity 2000 Special Edition"

Writes:
  build/WAIKIKI.TIL   a SCURK (DOS) graphics set; open it in SCURK's Pick & Copy
  build/SC2000.DAT    a copy of the game's data file with the Waikiki sprites
                      installed, which is what SCURK's Pick & Copy does when the
                      target is "Current SIM CITY 2000 Graphic Set"

The palette comes from the game (MINE.PAL inside SC2000.DAT). Indices the game
colour-cycles (water shimmer, lights) are never used.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import dosarchive
import dos_sprites as ds

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
SPRITES = BUILD / "sprites"
VIEW_OFFSET = {"L": 1000, "M": 500, "S": 0}
# DOS palette entries that map onto the Windows colour-cycling ranges (per the
# sc2kfix DOS->Windows table), plus entries with no Windows equivalent
ANIMATED = set(range(155, 204)) | set(range(210, 218)) | set(range(224, 232)) | set(range(233, 255))


def quantize(img, pal, allowed, boost=1.7, neutral_sat=0.10, grey_spread=8):
    """Hue-preserving match to the game's saturated palette: near-neutral pixels
    snap to true greys, tinted pixels get their saturation boosted first (the DOS
    palette has no muted blue-greys, so plain nearest-colour turns glass grey)."""
    a = np.asarray(img.convert("RGBA"), dtype=np.float32)
    rgb, alpha = a[..., :3], a[..., 3]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    grey = rgb.mean(-1, keepdims=True)
    boosted = np.clip(grey + (rgb - grey) * boost, 0, 255)
    target = np.where((sat < neutral_sat)[..., None], rgb, boosted)
    cand_all = allowed
    spread = pal[allowed].max(1) - pal[allowed].min(1)
    cand_grey = allowed[spread < grey_spread]
    w = np.array([0.30, 0.59, 0.11]) ** 0.5

    def nearest(cands, px):
        d = (((px[..., None, :] - pal[cands][None, None, :, :]) * w) ** 2).sum(-1)
        return cands[np.argmin(d, axis=-1)]

    idx = np.where(sat < neutral_sat, nearest(cand_grey, target), nearest(cand_all, target))
    return np.where(alpha > 127, idx, -1)


def load_game(game_dir):
    files, entries = dosarchive.read(Path(game_dir) / "SC2000.DAT")
    pal = np.frombuffer(files["MINE.PAL"], np.uint8).reshape(256, 3).astype(np.float32)
    template, tentries = dosarchive.read(Path(game_dir) / "TEMPLATE.URK")
    return files, entries, pal, template, tentries


def our_sprites(pal):
    allowed = np.array([i for i in range(256) if i not in ANIMATED])
    names = json.load(open(SPRITES / "names.json", encoding="utf-8"))
    out = {}
    for key in names:
        obj = int(key, 16)
        for view, off in VIEW_OFFSET.items():
            img = Image.open(SPRITES / f"{key}_{view}.png")
            out[off + obj] = quantize(img, pal, allowed)
    return out, names


def hed_ids(hed):
    return {sid: w for sid, (_, _, w) in ds.read_hed(hed).items()}


def decoded(files, name, sid):
    off, h, w = ds.read_hed(files[name + ".HED"])[sid]
    return ds.decode(files[name + ".DAT"], off, h, w)[0]


def build(game_dir):
    files, entries, pal, template, tentries = load_game(game_dir)
    sprites, names = our_sprites(pal)
    large = {s: p for s, p in sprites.items() if s >= 1000}
    small = {s: p for s, p in sprites.items() if s < 1000}

    # --- SCURK graphics set (.TIL): template ids, placeholders except ours ----
    til = dict(template)
    for part, mine in (("LARGE", large), ("SMALL", small)):
        til[part + ".HED"], til[part + ".DAT"] = ds.build(mine, hed_ids(template[part + ".HED"]))
    other_ids = hed_ids(template["OTHER.HED"])
    til["OTHER.HED"], til["OTHER.DAT"] = ds.build({s: p for s, p in small.items() if s in other_ids}, other_ids)
    til_bytes = dosarchive.write([(n, til[n]) for n, _ in tentries])
    (BUILD / "WAIKIKI.TIL").write_bytes(til_bytes)

    # --- the game's own data file with our sprites swapped in ---------------
    game = dict(files)
    for part, mine in (("LARGE", large), ("SMALL", small)):
        ids = hed_ids(files[part + ".HED"])
        keep = {}
        for sid in ids:
            keep[sid] = mine[sid] if sid in mine else decoded(files, part, sid)
        game[part + ".HED"], game[part + ".DAT"] = ds.build(keep, ids)
    dat_bytes = dosarchive.write([(n, game[n]) for n, _ in entries])
    (BUILD / "SC2000.DAT").write_bytes(dat_bytes)

    verify(til_bytes, dat_bytes, files, sprites)
    print(f"wrote build/WAIKIKI.TIL ({len(til_bytes)} bytes) and build/SC2000.DAT ({len(dat_bytes)} bytes); "
          f"{len(names)} objects, {len(sprites)} sprites")
    save_preview(sprites, pal)


def verify(til_bytes, dat_bytes, original, sprites):
    til, _ = dosarchive.read(til_bytes)
    game, _ = dosarchive.read(dat_bytes)
    for sid, px in sprites.items():
        part = "LARGE" if sid >= 1000 else "SMALL"
        for files in (til, game):
            got = decoded(files, part, sid)
            assert got.shape == px.shape and (got == px).all(), f"sprite {sid} did not round-trip"
            assert not np.isin(got[got >= 0], list(ANIMATED)).any()
    # every other game sprite and every other archive member is unchanged
    for part in ("LARGE", "SMALL"):
        for sid in ds.read_hed(original[part + ".HED"]):
            if sid not in sprites:
                assert (decoded(game, part, sid) == decoded(original, part, sid)).all(), f"{part} {sid} changed"
    for name in original:
        if name not in ("LARGE.HED", "LARGE.DAT", "SMALL.HED", "SMALL.DAT"):
            assert game[name] == original[name], f"{name} changed"


def save_preview(sprites, pal):
    items = sorted((s, p) for s, p in sprites.items() if s >= 1000)
    cw = max(p.shape[1] for _, p in items) + 8
    ch = max(p.shape[0] for _, p in items) + 8
    cols = 10
    rows = (len(items) + cols - 1) // cols
    sheet = np.full((rows * ch, cols * cw, 3), (190, 190, 190), dtype=np.uint8)
    for i, (_, px) in enumerate(items):
        y0 = (i // cols) * ch + ch - 4 - px.shape[0]
        x0 = (i % cols) * cw + (cw - px.shape[1]) // 2
        m = px >= 0
        sheet[y0:y0 + px.shape[0], x0:x0 + px.shape[1]][m] = pal[px[m]].astype(np.uint8)
    img = Image.fromarray(sheet)
    img.resize((img.width * 2, img.height * 2), Image.NEAREST).save(BUILD / "tileset_game_palette.png")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    build(sys.argv[1])
