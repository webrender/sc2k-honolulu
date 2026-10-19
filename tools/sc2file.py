"""Read and write SimCity 2000 (Win95 Special Edition) .sc2 city files.

Format reference: https://github.com/dfloer/SC2k-docs ("sc2 file spec.md").
A file is an IFF container: b"FORM" + u32 length + b"SCDH", followed by chunks of
4-byte id + u32 big-endian length + data. Most chunks are RLE-compressed.
"""
import struct

UNCOMPRESSED = {b"CNAM", b"ALTM", b"TEXT", b"SCEN", b"PICT", b"TMPL"}
CHUNK_ORDER = [b"CNAM", b"MISC", b"ALTM", b"XTER", b"XBLD", b"XZON", b"XUND", b"XTXT",
               b"XLAB", b"XMIC", b"XTHG", b"XBIT", b"XTRF", b"XPLT", b"XVAL", b"XCRM",
               b"XPLC", b"XFIR", b"XPOP", b"XROG", b"XGRP"]
SIZE = 128


def decompress(data):
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b < 128:
            out += data[i + 1:i + 1 + b]
            i += 1 + b
        else:
            out += bytes([data[i + 1]]) * (b - 127)
            i += 2
    return bytes(out)


def compress(data):
    """RLE in the game's style: runs of 3+ become repeat records, the rest literal records."""
    out = bytearray()
    lit = bytearray()

    def flush():
        while lit:
            part = lit[:127]
            out.append(len(part))
            out.extend(part)
            del lit[:127]

    i, n = 0, len(data)
    while i < n:
        j = i
        while j < n and data[j] == data[i] and j - i < 128:
            j += 1
        run = j - i
        if run >= 3:
            flush()
            out += bytes([127 + run, data[i]])
            i = j
        else:
            lit += data[i:j]
            i = j
    flush()
    return bytes(out)


class City:
    def __init__(self, chunks):
        self.chunks = chunks  # dict id -> uncompressed bytes, insertion-ordered

    @classmethod
    def load(cls, path):
        raw = open(path, "rb").read()
        assert raw[:4] == b"FORM" and raw[8:12] == b"SCDH", "not a .sc2 file"
        chunks = {}
        i = 12
        while i + 8 <= len(raw):
            cid = raw[i:i + 4]
            ln = struct.unpack(">I", raw[i + 4:i + 8])[0]
            data = raw[i + 8:i + 8 + ln]
            chunks[cid] = data if cid in UNCOMPRESSED else decompress(data)
            i += 8 + ln
        return cls(chunks)

    def save(self, path):
        body = bytearray(b"SCDH")
        for cid, data in self.chunks.items():
            enc = data if cid in UNCOMPRESSED else compress(data)
            body += cid + struct.pack(">I", len(enc)) + enc
        open(path, "wb").write(b"FORM" + struct.pack(">I", len(body)) + body)

    # --- MISC helpers (big-endian signed 32-bit values) ---
    def misc_get(self, offset):
        return struct.unpack(">i", self.chunks[b"MISC"][offset:offset + 4])[0]

    def misc_set(self, offset, value):
        m = bytearray(self.chunks[b"MISC"])
        m[offset:offset + 4] = struct.pack(">i", value)
        self.chunks[b"MISC"] = bytes(m)

    def name(self):
        c = self.chunks.get(b"CNAM", b"")
        return c[1:1 + c[0]].decode("latin-1") if c else ""

    def set_name(self, name):
        n = name.encode("latin-1")[:31]
        self.chunks[b"CNAM"] = bytes([len(n)]) + n + bytes(31 - len(n))
