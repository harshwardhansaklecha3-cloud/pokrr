"""Generate POKRR app icons (pastel gradient + a bold black 'P').
Pure Python (no image libraries). Run: .venv\\Scripts\\python.exe tools\\make_icons.py"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web"
A, B, C = (0xBC, 0xD7, 0xFF), (0xF6, 0xD5, 0xC4), (0xF4, 0xA5, 0x82)   # the POKRR gradient


def lerp(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def in_p(x, y):
    """A chunky letter P in a 1x1 box (coordinates 0..1)."""
    stem = 0.30 <= x <= 0.44 and 0.20 <= y <= 0.82
    bowl_outer = (x - 0.48) ** 2 / 0.23 ** 2 + (y - 0.39) ** 2 / 0.19 ** 2 <= 1 and x >= 0.36
    bowl_inner = (x - 0.48) ** 2 / 0.10 ** 2 + (y - 0.39) ** 2 / 0.07 ** 2 <= 1
    return stem or (bowl_outer and not bowl_inner)


def png(size: int) -> bytes:
    rows = []
    for j in range(size):
        row = bytearray([0])
        for i in range(size):
            x, y = i / size, j / size
            t = (x + y) / 2
            col = lerp(A, B, t / 0.55) if t < 0.55 else lerp(B, C, (t - 0.55) / 0.45)
            if in_p(x, y):
                col = (0, 0, 0)
            row += bytes(col)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


for s in (180, 192, 512):
    (OUT / f"icon-{s}.png").write_bytes(png(s))
print("icons written to", OUT)
