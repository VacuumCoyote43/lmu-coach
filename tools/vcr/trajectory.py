"""Fase 1: extraer la trayectoria de los registros de 70 bytes y dibujarla.

    python tools/vcr/trajectory.py "archivo.Vcr" salida.png

Lee el archivo por bloques (sirve para los de 2,6 GB), localiza la marca 41 10 04 00 00 00 20,
toma la posición float32 del byte 45 y guarda un PNG con el recorrido. También vuelca los
bytes que rodean a algunos registros para buscar el tiempo y el identificador del coche.
"""
import math
import struct
import sys
from pathlib import Path

MARK = bytes.fromhex("41 10 04 00 00 00 20")
POS_OFF = 45
STRUCT = bytes.fromhex("00 00 02 02")  # bytes 7-10 de todo registro de posicion
REC = 70
BLOCK = 64 * 1024 * 1024


def iter_records(path: Path, limit_bytes=None):
    """(offset absoluto, bytes del registro) — lectura por bloques con solape."""
    with open(path, "rb") as f:
        base, carry = 0, b""
        while True:
            chunk = f.read(BLOCK)
            if not chunk:
                break
            data = carry + chunk
            start = base - len(carry)
            i = data.find(MARK)
            last_end = 0
            while i != -1 and i + REC <= len(data):
                yield start + i, data[max(0, i - 16):i + REC]
                last_end = i + REC
                i = data.find(MARK, i + 1)
            keep = max(last_end, len(data) - REC)
            carry = data[keep:]
            base += len(chunk)
            if limit_bytes and base >= limit_bytes:
                break


def main():
    path, out = Path(sys.argv[1]), Path(sys.argv[2])
    pts = []
    dumps = []
    for off, rec in iter_records(path):
        body = rec[16:] if len(rec) >= 16 + REC else rec[-REC:]
        if body[7:11] != STRUCT:  # estructura fija tras la marca: descarta coincidencias casuales
            continue
        x, y, z = struct.unpack_from("<fff", body, POS_OFF)
        if all(math.isfinite(v) for v in (x, y, z)) and abs(x) < 20000 and abs(z) < 20000:
            pts.append((off, x, y, z))
            if len(dumps) < 6 and len(pts) > 50 and len(pts) % 7 == 0:
                dumps.append((off, rec))
    print(f"{path.name}: {len(pts)} registros con posición")
    print("\nBytes alrededor de algunos registros (16 antes | registro):")
    for off, rec in dumps:
        print(f"  {off:010x}  {rec[:16].hex(' ')} | {rec[16:16 + 45].hex(' ')} | pos | {rec[16 + 57:].hex(' ')}")

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
    app = QGuiApplication.instance() or QGuiApplication([])
    xs = sorted(p[1] for p in pts)
    zs = sorted(p[3] for p in pts)
    q = lambda v, f: v[int(f * (len(v) - 1))]  # percentiles: que un valor raro no arruine la escala
    minx, maxx, minz, maxz = q(xs, 0.002), q(xs, 0.998), q(zs, 0.002), q(zs, 0.998)
    W = 900
    scale = (W - 40) / max(maxx - minx, maxz - minz, 1)
    img = QImage(W, W, QImage.Format_RGB32)
    img.fill(QColor("#121318"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    n = len(pts)
    for i, (_, x, _, z) in enumerate(pts):
        c = QColor.fromHsvF(0.6 * i / max(n - 1, 1), 0.8, 1.0)  # color = orden en el archivo
        p.setPen(QPen(c, 2))
        p.drawPoint(QPointF(20 + (x - minx) * scale, W - 20 - (z - minz) * scale))
    p.end()
    img.save(str(out))
    print(f"\nrango x {minx:.0f}..{maxx:.0f}  z {minz:.0f}..{maxz:.0f}  -> {out}")


if __name__ == "__main__":
    main()
