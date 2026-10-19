"""DOS SimCity 2000 archive files (SC2000.DAT, .TIL, .URK): a table of 16-byte
entries (12-byte NUL-padded 8.3 name + little-endian u32 offset), then the files."""
import struct


def read(path_or_bytes):
    raw = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, "rb").read()
    entries = []
    i = 0
    first = len(raw)
    while i + 16 <= first:
        name = raw[i:i + 12].split(b"\0")[0].decode("ascii", "replace")
        off = struct.unpack_from("<I", raw, i + 12)[0]
        if not name:
            break
        entries.append((name, off))
        first = min(first, off)
        i += 16
    files = {}
    offs = sorted(set(o for _, o in entries)) + [len(raw)]
    for name, off in entries:
        end = offs[offs.index(off) + 1]
        files[name] = raw[off:end]
    return files, entries


def write(files):
    """files: list of (name, bytes) in the order to store them."""
    header_len = 16 * len(files)
    out = bytearray()
    body = bytearray()
    for name, data in files:
        nb = name.encode("ascii")
        assert len(nb) <= 12
        out += nb + bytes(12 - len(nb)) + struct.pack("<I", header_len + len(body))
        body += data
    return bytes(out + body)
