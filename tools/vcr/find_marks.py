"""Fase 1: descubrir las marcas de registro de posición en cualquier .Vcr.

    python tools/vcr/find_marks.py "archivo.Vcr" [MB]

Busca ternas float32 con pinta de posición en pista y cuenta qué 7 bytes hay 45 bytes antes
(donde empezaba el registro en las repeticiones de libres). Si se repiten, son las marcas.
"""
import collections
import math
import struct
import sys
from pathlib import Path


def main():
    path = Path(sys.argv[1])
    mb = float(sys.argv[2]) if len(sys.argv) > 2 else 20
    with open(path, "rb") as f:
        data = f.read(int(mb * 1e6))
    heads = collections.Counter()
    tails = collections.Counter()
    n = 0
    mv = memoryview(data)
    for off in range(45, len(data) - 25):
        x, y, z = struct.unpack_from("<fff", mv, off)
        if not (20 < abs(x) < 3000 and abs(y) < 200 and 20 < abs(z) < 3000):
            continue
        if not all(math.isfinite(v) for v in (x, y, z)) or abs(y) < 0.01:
            continue
        n += 1
        heads[bytes(mv[off - 45:off - 38])] += 1
        tails[bytes(mv[off - 38:off - 34])] += 1
    print(f"{path.name}: {n} ternas candidatas en {len(data) / 1e6:.0f} MB")
    print("7 bytes a -45 (posible marca) más comunes:")
    for k, v in heads.most_common(15):
        print(f"   {k.hex(' ')}  ×{v}")
    print("bytes -38..-35 más comunes:", [(k.hex(' '), v) for k, v in tails.most_common(6)])


if __name__ == "__main__":
    main()
