"""Génère deux icônes PNG (192 & 512) pour la PWA, sans dépendance externe.
Un carré vert avec un disque clair au centre — suffisant pour le MVP."""
import struct, zlib, os

GREEN = (13, 110, 92)
LIGHT = (235, 243, 241)

def png(size, path):
    cx = cy = size / 2
    r = size * 0.30
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filtre 0 par ligne
        for x in range(size):
            dx, dy = x - cx, y - cy
            inside = dx * dx + dy * dy <= r * r
            raw += bytes(LIGHT if inside else GREEN)
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # RGB
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    print("écrit", path)

here = os.path.join(os.path.dirname(__file__), "static")
png(192, os.path.join(here, "icon-192.png"))
png(512, os.path.join(here, "icon-512.png"))
