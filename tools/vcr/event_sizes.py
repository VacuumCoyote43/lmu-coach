"""Fase 2: deducir el tamaño de cada tipo de evento a partir de fotogramas de límites conocidos.

    python tools/vcr/event_sizes.py "archivo.Vcr" [MB]

Fotograma = [f32 tiempo][u16 n] + n eventos; evento = [u8 id][u8 tipo][datos].
Partimos de que el tipo 0x41 mide 70 bytes. En cada fotograma recorremos los eventos de
tamaño conocido; si el único desconocido es el último, su tamaño es lo que queda hasta el
siguiente fotograma. Se repite hasta que no se aprende nada nuevo.
"""
import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frames import candidates, longest_increasing_chain  # noqa: E402


def learn(data, chain, sizes):
    seen = collections.defaultdict(collections.Counter)
    unresolved = collections.Counter()
    for (a, t, n), (b, _, _) in zip(chain, chain[1:]):
        pos = a + 6
        for k in range(n):
            if pos + 2 > b:
                break
            typ = data[pos + 1]
            if typ in sizes and isinstance(sizes[typ], int):
                pos += sizes[typ]
                continue
            if k == n - 1:
                seen[typ][b - pos] += 1
            else:
                unresolved[typ] += 1
            break
    return seen, unresolved


def main():
    path = Path(sys.argv[1])
    mb = float(sys.argv[2]) if len(sys.argv) > 2 else 60
    data = open(path, "rb").read(int(mb * 1e6))
    chain = longest_increasing_chain(candidates(data))
    sizes = {0x41: 70}
    variable = {}
    for it in range(12):
        seen, unresolved = learn(data, chain, sizes)
        new = 0
        for typ, cnt in seen.items():
            if typ in sizes:
                continue
            (sz, k), = cnt.most_common(1)
            if k >= 3 and k / sum(cnt.values()) > 0.9:
                sizes[typ] = sz
                new += 1
            elif sum(cnt.values()) >= 3:
                variable[typ] = cnt
        if not new:
            break
    print(f"{path.name}: {len(chain)} fotogramas")
    print("Tamaños fijos deducidos:", {hex(k): v for k, v in sorted(sizes.items())})
    print("Tipos de tamaño variable:")
    for typ, cnt in variable.items():
        if typ not in sizes:
            print(f"   {hex(typ)}: {cnt.most_common(6)}")
    # cobertura: ¿cuántos fotogramas se recorren completos?
    ok = 0
    for (a, t, n), (b, _, _) in zip(chain, chain[1:]):
        pos = a + 6
        for _ in range(n):
            typ = data[pos + 1] if pos + 1 < b else None
            if typ not in sizes:
                break
            pos += sizes[typ]
        else:
            ok += pos == b
    print(f"Fotogramas recorridos exactamente de principio a fin: {ok} de {len(chain) - 1}")
    print("Tipos sin resolver (en medio de un fotograma):", {hex(k): v for k, v in unresolved.most_common(10)})


if __name__ == "__main__":
    main()
