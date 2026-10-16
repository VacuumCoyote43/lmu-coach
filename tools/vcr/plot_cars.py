"""Dibuja la trayectoria de cada coche de una repetición con el lector lmu_coach.vcr.

    python tools/vcr/plot_cars.py "archivo.Vcr" salida.png [tipos_hex separados por comas]
"""
import collections
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lmu_coach import vcr  # noqa: E402

STATE_KINDS = {0x10, 0x12, 0x14, 0x16, 0x18, 0x1a, 0x1c}


def main():
    path, out = Path(sys.argv[1]), Path(sys.argv[2])
    kinds = {int(k, 16) for k in sys.argv[3].split(",")} if len(sys.argv) > 3 else STATE_KINDS
    cars = collections.defaultdict(list)
    per_kind = collections.Counter()
    for fr in vcr.frames(path):
        for ev in fr.events:
            if ev.kind in kinds and len(ev.data) == 70:
                x, y, z = struct.unpack_from("<fff", ev.data, vcr.POS_OFFSET)
                if all(math.isfinite(v) for v in (x, y, z)) and abs(x) < 20000 and abs(z) < 20000:
                    cars[ev.vehicle].append((fr.time, x, y, z, ev.kind))
                    per_kind[ev.kind] += 1
    print(f"{path.name}: {len(cars)} vehículos · posiciones por tipo {dict(per_kind)}")
    for vid, pts in sorted(cars.items(), key=lambda kv: -len(kv[1]))[:12]:
        pts.sort()
        steps = sorted(math.dist((a[1], a[3]), (b[1], b[3])) / max(b[0] - a[0], 1e-3)
                       for a, b in zip(pts, pts[1:]) if b[0] > a[0])
        v_med = steps[len(steps) // 2] * 3.6 if steps else 0
        dt = sorted(b[0] - a[0] for a, b in zip(pts, pts[1:]))
        print(f"   coche {vid:3d}: {len(pts):6d} pos · t {pts[0][0]:.1f}–{pts[-1][0]:.1f} · "
              f"Δt mediano {dt[len(dt) // 2] if dt else 0:.2f} s · vel. mediana {v_med:.0f} km/h")

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
    app = QGuiApplication.instance() or QGuiApplication([])
    allp = [(p[1], p[3]) for v in cars.values() for p in v]
    xs, zs = sorted(p[0] for p in allp), sorted(p[1] for p in allp)
    q = lambda v, f: v[int(f * (len(v) - 1))]
    minx, maxx, minz, maxz = q(xs, 0.001), q(xs, 0.999), q(zs, 0.001), q(zs, 0.999)
    W = 1000
    scale = (W - 40) / max(maxx - minx, maxz - minz, 1)
    img = QImage(W, W, QImage.Format_RGB32)
    img.fill(QColor("#121318"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    order = sorted(cars, key=lambda k: -len(cars[k]))
    for gi, vid in enumerate(order):
        color = QColor.fromHsvF((gi * 0.137) % 1.0, 0.7, 1.0)
        p.setPen(QPen(color, 1.4))
        pts = cars[vid]
        for a, b in zip(pts, pts[1:]):
            if b[0] - a[0] < 1.0 and math.dist((a[1], a[3]), (b[1], b[3])) < 120:
                p.drawLine(QPointF(20 + (a[1] - minx) * scale, W - 20 - (a[3] - minz) * scale),
                           QPointF(20 + (b[1] - minx) * scale, W - 20 - (b[3] - minz) * scale))
    p.end()
    img.save(str(out))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
