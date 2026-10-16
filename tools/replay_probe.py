"""Fase 0 del plan de repeticiones: ¿publica LMU todos los coches en la memoria compartida
mientras se reproduce una repetición?

Uso (con LMU abierto y una repetición reproduciéndose):
    python tools/replay_probe.py [segundos]   (por defecto 30)

Solo lee la memoria compartida; no toca el juego. Al final imprime un resumen y guarda
las muestras en data/replay_probe.csv para analizarlas.
"""
import csv
import ctypes as C
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lmu_coach.paths import DATA_DIR  # noqa: E402
from lmu_coach.reader import LMUReader  # noqa: E402
from lmu_coach.shm_structs import (  # noqa: E402
    MAX_VEHICLES, ScoringInfoV01, SharedMemoryGeneric, SharedMemoryObjectOut, TelemInfoV01,
    VehicleScoringInfoV01, offset_of,
)

CONTROL = {-1: "nadie", 0: "jugador", 1: "IA", 2: "remoto", 3: "repetición"}


def s(b: bytes) -> str:
    return b.split(b"\0", 1)[0].decode("utf-8", "replace")


def main(seconds: float):
    r = LMUReader()
    if not r.connect():
        print("LMU no está abierto (no existe LMU_Data). Abre el juego y una repetición.")
        return 1
    view = r._view
    off_si = offset_of(SharedMemoryObjectOut, "scoring", "scoringInfo")
    off_vsc = offset_of(SharedMemoryObjectOut, "scoring", "vehScoringInfo")
    off_tel = offset_of(SharedMemoryObjectOut, "telemetry")
    off_ti = offset_of(SharedMemoryObjectOut, "telemetry", "telemInfo")
    rows = []
    t0 = time.perf_counter()
    print(f"Grabando {seconds:.0f} s… (reproduce la repetición en LMU)")
    while time.perf_counter() - t0 < seconds:
        now = time.perf_counter() - t0
        gen = SharedMemoryGeneric.from_buffer_copy(C.string_at(view, C.sizeof(SharedMemoryGeneric)))
        si = ScoringInfoV01.from_buffer_copy(C.string_at(view + off_si, C.sizeof(ScoringInfoV01)))
        hdr = C.string_at(view + off_tel, 3)
        n_sc = max(0, min(si.mNumVehicles, MAX_VEHICLES))
        for i in range(n_sc):
            v = VehicleScoringInfoV01.from_buffer_copy(
                C.string_at(view + off_vsc + i * C.sizeof(VehicleScoringInfoV01), C.sizeof(VehicleScoringInfoV01)))
            rows.append(dict(t=round(now, 3), src="scoring", idx=i, id=v.mID, driver=s(v.mDriverName),
                             car=s(v.mVehicleName), control=v.mControl, is_player=int(v.mIsPlayer),
                             lap=v.mTotalLaps, lapdist=round(v.mLapDist, 2), et=round(si.mCurrentET, 3),
                             x=round(v.mPos.x, 2), y=round(v.mPos.y, 2), z=round(v.mPos.z, 2),
                             speed=round(math.hypot(v.mLocalVel.x, v.mLocalVel.z) * 3.6, 1),
                             phase=si.mGamePhase, realtime=int(si.mInRealtime), app_loc=gen.appInfo.mOptionsLocation,
                             page=s(gen.appInfo.mOptionsPage)))
        for i in range(min(hdr[0], MAX_VEHICLES)):
            te = TelemInfoV01.from_buffer_copy(
                C.string_at(view + off_ti + i * C.sizeof(TelemInfoV01), C.sizeof(TelemInfoV01)))
            rows.append(dict(t=round(now, 3), src="telemetry", idx=i, id=te.mID, driver="", car=s(te.mVehicleName),
                             control="", is_player=int(i == hdr[1]), lap=te.mLapNumber, lapdist="",
                             et=round(te.mElapsedTime, 3), x=round(te.mPos.x, 2), y=round(te.mPos.y, 2),
                             z=round(te.mPos.z, 2),
                             speed=round(math.sqrt(te.mLocalVel.x ** 2 + te.mLocalVel.y ** 2 + te.mLocalVel.z ** 2) * 3.6, 1),
                             phase=si.mGamePhase, realtime=int(si.mInRealtime), app_loc=gen.appInfo.mOptionsLocation,
                             page=s(gen.appInfo.mOptionsPage)))
        time.sleep(0.05)
    r.close()

    out = DATA_DIR / "replay_probe.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["t"])
        w.writeheader()
        w.writerows(rows)
    summarize(rows, seconds)
    print(f"\nMuestras guardadas en {out}")
    return 0


def summarize(rows, seconds):
    print("\n================ RESULTADO FASE 0 ================")
    if not rows:
        print("No llegó ningún dato (¿en el menú principal?).")
        return
    last = rows[-1]
    print(f"Estado: fase de juego {last['phase']} · en pista (realtime) {last['realtime']} · "
          f"pantalla '{last['page']}' (loc {last['app_loc']})")
    for src in ("scoring", "telemetry"):
        rs = [r for r in rows if r["src"] == src]
        cars = defaultdict(list)
        for r in rs:
            cars[(r["id"], r["car"])].append(r)
        ets = sorted({r["et"] for r in rs})
        rate = len(ets) / seconds if seconds else 0
        print(f"\n[{src}] coches distintos: {len(cars)} · actualizaciones/s ≈ {rate:.1f} · "
              f"tiempo de sesión {ets[0] if ets else '-'} → {ets[-1] if ets else '-'}")
        moving = 0
        for (cid, car), samples in sorted(cars.items(), key=lambda kv: kv[0][0]):
            dist = sum(math.dist((a["x"], a["z"]), (b["x"], b["z"])) for a, b in zip(samples, samples[1:]))
            ctl = {CONTROL.get(r["control"], r["control"]) for r in samples} if src == "scoring" else {""}
            moving += dist > 5
            print(f"   id {cid:3d} {car[:32]:32s} {samples[-1]['driver'][:18]:18s} "
                  f"recorrido {dist:7.0f} m  vel {samples[-1]['speed']:5.0f} km/h  control {','.join(map(str, ctl))}")
        print(f"   → se mueven {moving} de {len(cars)}")
    sc = [r for r in rows if r["src"] == "scoring"]
    te = [r for r in rows if r["src"] == "telemetry"]
    n_sc = len({r["id"] for r in sc})
    n_te_moving = len({r["id"] for r in te})
    print("\nVEREDICTO:")
    if n_sc > 1 and any(r["control"] == 3 for r in sc):
        print(" ✔ El scoring publica todos los coches en modo repetición (control=3).")
    elif n_sc > 1:
        print(" • El scoring publica varios coches, pero no aparecen marcados como repetición.")
    else:
        print(" ✖ El scoring solo publica 1 coche o ninguno.")
    print(f" • La telemetría (datos a ~50 Hz) incluye {n_te_moving} coche(s).")


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 30))
