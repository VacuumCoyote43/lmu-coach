"""Fase 2: alinear las posiciones del .Vcr con la telemetría .duckdb de la misma sesión.

    python tools/vcr/align.py "replay.Vcr" "telemetria.duckdb"

1. Saca los registros de posición float32 del .Vcr (registros 0x41, x/y/z en +45).
2. Convierte el «GPS» de la telemetría a metros probando signos/ejes y se queda con la
   transformación que mejor superpone ambas trayectorias.
3. Para cada registro, busca el instante de la telemetría más cercano en posición y
   estudia si algún campo del registro se comporta como un reloj.
"""
import math
import struct
import sys
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from by_vehicle import records  # noqa: E402

R = 111320.0  # metros por grado (aprox.)


def replay_points(path: Path, mb=200):
    with open(path, "rb") as f:
        data = f.read(int(mb * 1e6))
    out = []
    for off, key, flag, (x, y, z) in records(data):
        out.append((off, key, flag, x, y, z, data[off:off + 70]))
    return out


def telemetry(path: Path):
    c = duckdb.connect(str(path), read_only=True)
    q = lambda s: np.array([r[0] for r in c.execute(s).fetchall()], dtype=float)
    lat, lon = q('select value from "GPS Latitude"'), q('select value from "GPS Longitude"')
    t0 = c.execute('select min(value) from "GPS Time"').fetchone()[0]
    t = t0 + np.arange(len(lat)) / 10.0
    return t, lat, lon


def best_transform(K, lat, lon):
    """Prueba 8 combinaciones de ejes/signos; devuelve la que minimiza la distancia K→telemetría."""
    a = (lat - 60.0) * R
    b = lon * R * math.cos(math.radians(60))
    cands = {}
    for swap in (False, True):
        u, v = (b, a) if not swap else (a, b)
        for sx in (1, -1):
            for sz in (1, -1):
                T = np.stack([sx * u, sz * v], axis=1)
                # mejor traslación: alinear medianas
                shift = np.median(K, axis=0) - np.median(T, axis=0)
                T2 = T + shift
                d = nn_dist(K[:: max(1, len(K) // 3000)], T2)
                cands[(swap, sx, sz)] = (float(np.median(d)), shift, T2)
    key = min(cands, key=lambda k: cands[k][0])
    return key, cands[key], cands


def nn_dist(P, T):
    out = np.empty(len(P))
    for i in range(0, len(P), 500):
        d = np.linalg.norm(P[i:i + 500, None, :] - T[None, :, :], axis=2)
        out[i:i + 500] = d.min(axis=1)
    return out


def main():
    rp, tp = Path(sys.argv[1]), Path(sys.argv[2])
    recs = replay_points(rp)
    K = np.array([[r[3], r[5]] for r in recs])
    t, lat, lon = telemetry(tp)
    print(f"{len(recs)} registros del .Vcr · {len(t)} muestras de telemetría (t {t[0]:.1f}–{t[-1]:.1f} s)")
    key, (med, shift, T), cands = best_transform(K, lat, lon)
    for k, (m, s, _) in sorted(cands.items(), key=lambda kv: kv[1][0]):
        print(f"   ejes cambiados={k[0]!s:5} signos x{k[1]:+d} z{k[2]:+d}: distancia mediana {m:8.2f} m")
    print(f"Mejor: {key}, traslación {shift.round(2)}, distancia mediana {med:.2f} m")

    # Instante de telemetría más cercano para cada registro
    d_all = np.empty(len(K))
    idx = np.empty(len(K), dtype=int)
    for i in range(0, len(K), 500):
        d = np.linalg.norm(K[i:i + 500, None, :] - T[None, :, :], axis=2)
        idx[i:i + 500] = d.argmin(axis=1)
        d_all[i:i + 500] = d.min(axis=1)
    good = d_all < 3.0
    print(f"Registros a menos de 3 m de la trayectoria: {good.sum()} de {len(K)}")
    tt = t[idx]
    # ¿Algún campo del registro (u8/u16/u32/f32 en cada offset) crece como el tiempo?
    print("\nCampos del registro que más se correlacionan con el tiempo de la telemetría:")
    best = []
    sel = np.where(good)[0]
    for off in range(7, 66):
        for fmt, size in (("<f", 4), ("<I", 4), ("<H", 2), ("<B", 1)):
            if off + size > 70:
                continue
            vals = np.array([struct.unpack_from(fmt, recs[i][6], off)[0] for i in sel], dtype=float)
            if not np.all(np.isfinite(vals)) or np.std(vals) == 0:
                continue
            r = np.corrcoef(vals, tt[sel])[0, 1]
            best.append((abs(r), off, fmt, vals[:5]))
    for r, off, fmt, v in sorted(best, reverse=True)[:8]:
        print(f"   +{off:2d} {fmt}: |r|={r:.3f}  primeros {np.round(v, 3)}")
    # orden en el archivo frente a tiempo
    r_file = np.corrcoef(np.array([recs[i][0] for i in sel], float), tt[sel])[0, 1]
    print(f"\nCorrelación offset en el archivo ↔ tiempo: {r_file:.3f}")


if __name__ == "__main__":
    main()
