"""Fase 2: localizar fotogramas por su cabecera [float32 tiempo][u16 n][0x68] y comprobar el orden.

    python tools/vcr/frames.py "archivo.Vcr" [MB]

Busca todas las cabeceras candidatas, se queda con la cadena de tiempos creciente más larga
y muestra el ritmo (Δt), los huecos y cuántos registros 0x41 de 70 bytes hay en cada fotograma.
"""
import collections
import math
import struct
import sys
from pathlib import Path

import numpy as np


def candidates(data: bytes):
    """(offset de la cabecera, tiempo, n) para cada '?? ?? ?? ?? nn nn 68' con tiempo plausible."""
    out = []
    i = data.find(b"\x68", 6)
    mv = memoryview(data)
    while i != -1:
        t, n = struct.unpack_from("<fH", mv, i - 6)
        if math.isfinite(t) and 0 <= t < 200000 and (t == 0 or t > 1e-3) and 0 < n < 2000:
            # tiempos de fotograma redondos a 1/50 s (con margen de float32)
            if abs(t * 50 - round(t * 50)) < 0.02:
                out.append((i - 6, t, n))
        i = data.find(b"\x68", i + 1)
    return out


def longest_increasing_chain(cands):
    """Cadena de cabeceras con tiempo no decreciente y saltos razonables (greedy hacia delante)."""
    chain = []
    for off, t, n in cands:
        if not chain:
            chain.append((off, t, n))
            continue
        lt = chain[-1][1]
        if lt <= t <= lt + 30:  # el tiempo no retrocede y no salta más de 30 s
            chain.append((off, t, n))
    return chain


def main():
    path = Path(sys.argv[1])
    mb = float(sys.argv[2]) if len(sys.argv) > 2 else 60
    with open(path, "rb") as f:
        data = f.read(int(mb * 1e6))
    cands = candidates(data)
    chain = longest_increasing_chain(cands)
    print(f"{path.name}: {len(cands)} cabeceras candidatas, cadena creciente de {len(chain)} fotogramas")
    if len(chain) < 3:
        return
    ts = np.array([c[1] for c in chain])
    dt = np.diff(ts)
    print(f"tiempo {ts[0]:.2f} → {ts[-1]:.2f} s  ({(ts[-1] - ts[0]) / 60:.1f} min)")
    print("Δt más comunes:", collections.Counter(np.round(dt, 3)).most_common(8))
    gaps = [(chain[i][1], chain[i + 1][1]) for i in range(len(dt)) if dt[i] > 1.0]
    print(f"huecos > 1 s: {len(gaps)}", gaps[:8])
    sizes = np.diff([c[0] for c in chain])
    print("bytes por fotograma: mediana", int(np.median(sizes)), "p90", int(np.percentile(sizes, 90)))
    # registros 0x41 dentro de cada fotograma
    per = []
    for (a, t, n), (b, _, _) in zip(chain, chain[1:]):
        seg = data[a + 7:b]
        k, j = 0, seg.find(b"\x41")
        while j != -1:
            if j + 11 <= len(seg) and seg[j + 4] == 0 and seg[j + 5] == 0 and seg[j + 7] == 0:
                k += 1
            j = seg.find(b"\x41", j + 1)
        per.append((n, k))
    print("(n de cabecera, registros 0x41) más comunes:", collections.Counter(per).most_common(8))
    print("primeros fotogramas:", [(hex(o), round(t, 2), n) for o, t, n in chain[:8]])


if __name__ == "__main__":
    main()
