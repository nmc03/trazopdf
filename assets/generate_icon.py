"""Generate TrazoPDF's original Windows icon with Python's standard library."""
from pathlib import Path
import struct
import zlib

SIZE = 256
pixels = bytearray(SIZE * SIZE * 4)


def polygon(points, color):
    for y in range(SIZE):
        intersections = []
        for i, (x1, y1) in enumerate(points):
            x2, y2 = points[(i + 1) % len(points)]
            if (y1 <= y < y2) or (y2 <= y < y1):
                intersections.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        intersections.sort()
        for left, right in zip(intersections[::2], intersections[1::2]):
            for x in range(max(0, int(left)), min(SIZE, int(right) + 1)):
                offset = (y * SIZE + x) * 4
                pixels[offset:offset + 4] = bytes(color)


for y in range(16, 240):
    for x in range(16, 240):
        dx = max(68 - x, 0, x - 187)
        dy = max(68 - y, 0, y - 187)
        if dx * dx + dy * dy <= 52 * 52:
            offset = (y * SIZE + x) * 4
            pixels[offset:offset + 4] = bytes((20, 40, 62, 255))

polygon([(70, 48), (149, 48), (188, 87), (188, 207), (70, 207)], (243, 247, 251, 255))
polygon([(149, 48), (149, 87), (188, 87)], (173, 200, 218, 255))
for y, right in ((108, 161), (128, 140), (148, 127)):
    polygon([(86, y), (right, y), (right, y + 9), (86, y + 9)], (73, 113, 138, 255))
polygon([(127, 180), (139, 147), (181, 105), (202, 126), (160, 168)], (56, 204, 178, 255))
polygon([(127, 180), (139, 147), (160, 168)], (29, 119, 106, 255))
polygon([(172, 114), (176, 110), (198, 132), (194, 136)], (20, 40, 62, 255))


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)


raw = b''.join(b'\x00' + pixels[y * SIZE * 4:(y + 1) * SIZE * 4] for y in range(SIZE))
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', SIZE, SIZE, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')
root = Path(__file__).resolve().parent
(root / 'pdf-editor.png').write_bytes(png)
(root / 'pdf-editor.ico').write_bytes(struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(png), 22) + png)
