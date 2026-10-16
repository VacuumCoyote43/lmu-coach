"""Fase 2: validar el lector con la telemetría de la misma sesión.

    python tools/vcr/validate.py "replay.Vcr" "telemetria.duckdb"

Para cada coche calcula la velocidad a partir de sus posiciones en el .Vcr y la compara con la
velocidad registrada por LMU (Ground Speed) en el mismo tiempo de sesión. El coche del jugador
debe dar una correlación casi perfecta.
"""
import collections
import struct
import sys
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lmu_coach import vcr  # noqa: E402

STATE_KINDS = {int(k, 16) for k in (sys.argv[3].split(",") if len(sys.argv) > 3 else ["10", "12", "14", "16", "18", "1a", "1c"])}


def main():
    rp, tp = Path(sys.argv[1]), Path(sys.argv[2])
    cars = collections.defaultdict(list)
    for fr in vcr.frames(rp):
        for ev in fr.events:
            if ev.kind in STATE_KINDS and len(ev.data) == 70:
                cars[ev.vehicle].append((fr.time, *struct.unpack_from("<fff", ev.data, vcr.POS_OFFSET)))
    c = duckdb.connect(str(tp), read_only=True)
    gt = np.array([r[0] for r in c.execute('select value from "GPS Time"').fetchall()])
    gs = np.array([r[0] for r in c.execute('select value from "Ground Speed"').fetchall()])  # km/h, 100 Hz
    print(f"telemetría: t {gt[0]:.2f}–{gt[-1]:.2f} s · velocidad máx {gs.max():.0f} km/h")
    results = []
    for vid, pts in cars.items():
        a = np.array(sorted(pts))
        t, x, z = a[:, 0], a[:, 1], a[:, 3]
        keep = np.concatenate([[True], np.diff(t) > 0])
        t, x, z = t[keep], x[keep], z[keep]
        if len(t) < 100:
            continue
        lo, hi = max(t[0], gt[0]), min(t[-1], gt[-1])
        if hi - lo < 30:
            continue
        # Remuestrear la posición a una rejilla uniforme de 0,1 s: algunos fotogramas tienen
        # tiempos fuera de la rejilla de 1/50 s y derivar con Δt diminutos dispara la velocidad
        tt = np.arange(lo, hi, 0.1)
        xi, zi = np.interp(tt, t, x), np.interp(tt, t, z)
        vr = np.hypot(np.gradient(xi, 0.1), np.gradient(zi, 0.1)) * 3.6
        vt = np.interp(tt, gt, gs)
        if vt.std() < 1 or vr.std() < 1:
            continue
        r = np.corrcoef(vr, vt)[0, 1]
        err = np.median(np.abs(vr - vt))
        results.append((r, vid, err, vr.max(), len(t)))
    results.sort(reverse=True)
    print("Coches cuya velocidad más se parece a la tuya:")
    for r, vid, err, vmax, n in results[:5]:
        print(f"   coche {vid:3d}: correlación {r:.4f} · error mediano {err:.2f} km/h · v. máx {vmax:.0f} km/h · {n} pos")


if __name__ == "__main__":
    main()
