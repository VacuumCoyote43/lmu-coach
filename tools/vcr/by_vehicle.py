"""Fase 1: agrupar registros de posición por los bytes variables de la cabecera y dibujarlos.

    python tools/vcr/by_vehicle.py "archivo.Vcr" salida.png [MB]

Registro de posición (hipótesis): 0x41, b1, b2, b3, 00, 00, flags, 00 00 02 02 …, x y z float32 en +45.
Si cada grupo (b1, b2, b3) es una trayectoria continua, esos bytes identifican al coche.
"""
import collections
import math
import struct
import sys
from pathlib import Path

POS_OFF = 45
STRUCT = bytes.fromhex("00 00 02 02")
FLAGS = {0x20, 0x24, 0x30}


def records(data: bytes):
    i = data.find(b"\x41")
    mv = memoryview(data)
    while i != -1 and i + 60 <= len(data):
        # cabecera: 41, b1 par (0x10–0x1e), b2, b3, 00, 00, flags; byte 7 = 00 y byte 9 = 01/02
        if (data[i + 4] == 0 and data[i + 5] == 0 and data[i + 6] in FLAGS and 0x10 <= data[i + 1] <= 0x1e
                and data[i + 1] % 2 == 0 and data[i + 7] == 0 and data[i + 9] in (1, 2)):
            x, y, z = struct.unpack_from("<fff", mv, i + POS_OFF)
            if all(math.isfinite(v) for v in (x, y, z)) and abs(x) < 5000 and abs(z) < 5000:
                yield i, data[i + 1:i + 4], data[i + 6], (x, y, z)
        i = data.find(b"\x41", i + 1)


def main():
    path, out = Path(sys.argv[1]), Path(sys.argv[2])
    mb = float(sys.argv[3]) if len(sys.argv) > 3 else 60
    with open(path, "rb") as f:
        data = f.read(int(mb * 1e6))
    groups = collections.defaultdict(list)
    for off, key, flag, pos in records(data):
        groups[key].append((off, flag, pos))
    print(f"{path.name}: {sum(map(len, groups.values()))} registros en {len(groups)} grupos ({len(data) / 1e6:.0f} MB)")
    for key, recs in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:20]:
        steps = sorted(math.dist((a[2][0], a[2][2]), (b[2][0], b[2][2])) for a, b in zip(recs, recs[1:]))
        med = steps[len(steps) // 2] if steps else 0
        xs = [r[2][0] for r in recs]
        zs = [r[2][2] for r in recs]
        flags = collections.Counter(hex(r[1]) for r in recs)
        print(f"  {key.hex(' ')}: {len(recs):6d} reg · paso mediano {med:6.2f} m · "
              f"x {min(xs):7.0f}..{max(xs):6.0f} z {min(zs):7.0f}..{max(zs):6.0f} · flags {dict(flags)}")

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
    app = QGuiApplication.instance() or QGuiApplication([])
    allp = [r[2] for g in groups.values() for r in g]
    xs = sorted(p[0] for p in allp)
    zs = sorted(p[2] for p in allp)
    q = lambda v, f: v[int(f * (len(v) - 1))]
    minx, maxx, minz, maxz = q(xs, 0.001), q(xs, 0.999), q(zs, 0.001), q(zs, 0.999)
    W = 900
    scale = (W - 40) / max(maxx - minx, maxz - minz, 1)
    img = QImage(W, W, QImage.Format_RGB32)
    img.fill(QColor("#121318"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    keys = sorted(groups, key=lambda k: -len(groups[k]))
    for gi, key in enumerate(keys[:12]):
        color = QColor.fromHsvF((gi * 0.17) % 1.0, 0.75, 1.0)
        p.setPen(QPen(color, 1.6))
        for _, _, (x, _, z) in groups[key]:
            p.drawPoint(QPointF(20 + (x - minx) * scale, W - 20 - (z - minz) * scale))
        p.drawText(10, 20 + gi * 16, f"{key.hex(' ')}  ({len(groups[key])})")
    p.end()
    img.save(str(out))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
