"""Fase 1: localizar registros por su marca y estudiar su tamaño y contenido.

    python tools/vcr/records.py "archivo.Vcr" [MB_a_leer] [marca_hex]

Por defecto busca la marca 41 10 04 00 00 00 20 (la secuencia más repetida en P1 1) y
muestra: cuántas hay, distancias entre marcas, y las posiciones float32 que contiene
cada registro, para ver si describen un coche moviéndose.
"""
import collections
import math
import struct
import sys
from pathlib import Path

DEFAULT_MARK = bytes.fromhex("41 10 04 00 00 00 20")


def find_all(data: bytes, mark: bytes):
    out, i = [], data.find(mark)
    while i != -1:
        out.append(i)
        i = data.find(mark, i + 1)
    return out


def pos_triplets(chunk: bytes, base: int):
    res = []
    for off in range(0, len(chunk) - 12):
        a, b, c = struct.unpack_from("<fff", chunk, off)
        if all(math.isfinite(v) for v in (a, b, c)) and 5 < abs(a) < 5000 and abs(b) < 300 and 5 < abs(c) < 5000:
            res.append((base + off, a, b, c))
    return res


def main():
    path = Path(sys.argv[1])
    mb = float(sys.argv[2]) if len(sys.argv) > 2 else 4
    mark = bytes.fromhex(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_MARK
    with open(path, "rb") as f:
        data = f.read(int(mb * 1e6))
    offs = find_all(data, mark)
    print(f"{path.name}: marca {mark.hex(' ')} ×{len(offs)} en {len(data) / 1e6:.1f} MB")
    gaps = collections.Counter(b - a for a, b in zip(offs, offs[1:]))
    print("distancias entre marcas más comunes:", gaps.most_common(12))
    # Contexto: los 12 bytes antes de la marca (¿tipo/longitud/tiempo?)
    pre = collections.Counter(data[o - 4:o] for o in offs[1:2000])
    print("4 bytes previos más comunes:", [(p.hex(' '), n) for p, n in pre.most_common(6)])
    print("\nPrimeros registros (offset, bytes tras la marca, ternas de posición):")
    for a, b in list(zip(offs, offs[1:]))[:12]:
        rec = data[a:b]
        trip = pos_triplets(rec, a)
        tail = rec[len(mark):len(mark) + 24].hex(" ")
        print(f"  {a:08x} len {b - a:4d} | {tail}")
        for off, x, y, z in trip[:3]:
            print(f"        pos @+{off - a:3d}: ({x:9.2f}, {y:7.2f}, {z:9.2f})")
    # Trayectoria: primera terna de cada registro con posición, ¿se mueve de forma continua?
    seq = []
    for a, b in zip(offs, offs[1:]):
        t = pos_triplets(data[a:b], a)
        if t:
            seq.append(t[0][1:])
    if len(seq) > 2:
        steps = [math.dist((p[0], p[2]), (q[0], q[2])) for p, q in zip(seq, seq[1:])]
        steps.sort()
        print(f"\n{len(seq)} registros con posición; paso entre registros consecutivos: "
              f"mediana {steps[len(steps) // 2]:.2f} m, p90 {steps[int(len(steps) * 0.9)]:.2f} m, máx {steps[-1]:.1f} m")
        xs = [p[0] for p in seq]
        zs = [p[2] for p in seq]
        print(f"rango x {min(xs):.0f}…{max(xs):.0f}, z {min(zs):.0f}…{max(zs):.0f}")


if __name__ == "__main__":
    main()
