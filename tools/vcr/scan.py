"""Fase 1: primer reconocimiento de un .Vcr (solo lectura).

    python tools/vcr/scan.py "ruta\\archivo.Vcr" [bytes_a_analizar]

Muestra la cabecera, los n-gramas más repetidos (posibles marcas de registro) y dónde
aparecen ternas de float32 con pinta de posición (x, y, z en metros), con la distancia
entre ellas (si se repite, es el tamaño de un registro o de un fotograma).
"""
import collections
import struct
import sys
from pathlib import Path


def header(data: bytes):
    end = data.find(b"\n")
    print("Cabecera de texto:", data[:end].decode("latin-1"))
    print("Siguientes 96 bytes:")
    rest = data[end + 1:end + 1 + 96]
    for i in range(0, len(rest), 16):
        chunk = rest[i:i + 16]
        print(f"  {end + 1 + i:06x}  {chunk.hex(' ')}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)}")
    return end + 1


def ngrams(data: bytes, n=6, top=15):
    c = collections.Counter(data[i:i + n] for i in range(0, len(data) - n))
    print(f"\n{n}-gramas más repetidos:")
    for g, k in c.most_common(top):
        if g.count(0) == n:
            continue
        print(f"  {g.hex(' ')}  ×{k}")


def position_like(a, b, c):
    return all(0.5 < abs(v) < 5000 for v in (a, c)) and abs(b) < 400


def float_positions(data: bytes, limit=200000):
    """Busca ternas consecutivas de float32 (en cualquier alineación) con pinta de x, y, z."""
    hits = []
    for off in range(0, min(len(data), limit) - 12):
        a, b, c = struct.unpack_from("<fff", data, off)
        if position_like(a, b, c):
            hits.append((off, a, b, c))
    # quedarnos con ternas aisladas (no solapadas)
    clean, last = [], -12
    for h in hits:
        if h[0] >= last + 12:
            clean.append(h)
            last = h[0]
    print(f"\nTernas float32 con pinta de posición en los primeros {limit} bytes: {len(clean)}")
    for off, a, b, c in clean[:20]:
        print(f"  {off:06x}: ({a:9.2f}, {b:8.2f}, {c:9.2f})")
    gaps = collections.Counter(b[0] - a[0] for a, b in zip(clean, clean[1:]))
    print("Distancias más comunes entre ternas:", gaps.most_common(10))
    return clean


def main():
    path = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4_000_000
    with open(path, "rb") as f:
        data = f.read(n)
    print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB (analizando {len(data) / 1e6:.1f} MB)")
    header(data)
    ngrams(data, 4)
    ngrams(data, 8)
    float_positions(data)


if __name__ == "__main__":
    main()
