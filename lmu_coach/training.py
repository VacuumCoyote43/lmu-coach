"""Plan de entrenamiento: las curvas donde más tiempo se te escapa y qué cambiar en cada una.

Compara cada vuelta válida con tu mejor vuelta de la sesión: lo que pierdes de media en una curva es
tiempo que ya has demostrado que puedes ganar. El plan se puede activar en el coach, que te recuerda
el objetivo al llegar a esas curvas.
"""
import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from . import analysis, corners
from .paths import DATA_DIR

PLAN_PATH = DATA_DIR / "training_plans.json"
MIN_LOSS = 0.04       # s de media para que una curva entre en el plan


@dataclass
class Focus:
    idx: int
    apex: float
    name: str                 # «F3 · Ferradura»
    loss: float               # s perdidos de media por vuelta frente a tu mejor vuelta
    tips: list = field(default_factory=list)       # frases completas para la app
    short: str = ""           # versión corta para el coach y la voz
    laps: int = 0


def build(sd, top=3) -> tuple[list[Focus], dict]:
    """Plan para esta sesión: (curvas a trabajar, resumen)."""
    valid = [l for l in sd.laps if l.valid]
    info = sd.info
    if len(valid) < 3:
        return [], {"laps": len(valid)}
    best = min(valid, key=lambda l: l.time)
    L = sd.track_len
    ref = analysis.by_distance(sd.lap_data(best.num), L)
    per = defaultdict(list)
    zones = {}
    for lap in valid:
        if lap.num == best.num:
            continue
        cur = analysis.by_distance(sd.lap_data(lap.num), L)
        for z in analysis.compare_zones(ref, cur, analysis.delta(ref, cur)):
            per[z.zone.idx].append(z)
            zones[z.zone.idx] = z.zone
    out = []
    for idx, rs in per.items():
        if len(rs) < 2:
            continue
        loss = statistics.mean(r.time_diff for r in rs)
        if loss < MIN_LOSS:
            continue
        z = zones[idx]
        brake = statistics.median(r.brake_diff for r in rs)
        brake_sd = statistics.pstdev(r.brake_diff for r in rs)
        speed = statistics.median(r.min_speed_diff for r in rs)
        thr = statistics.median(r.throttle_diff for r in rs)
        tips, short = [], []
        steady = brake_sd < 25 and abs(brake) <= 50     # si no, la media del punto de frenada es ruido
        if steady and brake < -8:
            tips.append(f"frena unos {-brake:.0f} m más tarde (como en tu mejor vuelta)")
            short.append(f"frena {-brake:.0f} m más tarde")
        elif steady and brake > 8:
            tips.append(f"frena unos {brake:.0f} m antes: llegas pasado y lo pagas en el vértice")
            short.append(f"frena {brake:.0f} m antes")
        if brake_sd > 10:
            tips.append(f"frena siempre en el mismo punto: varías ±{brake_sd:.0f} m de una vuelta a otra")
            if not short:
                short.append("frena siempre en el mismo punto")
        if speed < -3:
            tips.append(f"lleva {-speed:.0f} km/h más al vértice (suelta el freno antes y deja correr el coche)")
            short.append(f"{-speed:.0f} km/h más al vértice")
        if thr > 10:
            tips.append(f"vuelve a gas a fondo {thr:.0f} m antes")
            short.append("acelera antes")
        if not tips:
            tips.append("repite la trazada de tu mejor vuelta: compárala en la repetición")
            short.append("trazada de tu mejor vuelta")
        out.append(Focus(idx, z.apex, corners.label(z, info.track, info.layout), loss, tips,
                         " · ".join(short[:2]), len(rs)))
    out.sort(key=lambda f: -f.loss)
    chosen = out[:top]
    total = sum(f.loss for f in out)
    return chosen, {"laps": len(valid), "best": best.time, "total_loss": total,
                    "focus_loss": sum(f.loss for f in chosen)}


# --- planes activos en el coach (por circuito y coche) ------------------------------------

def _load() -> dict:
    try:
        return json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _key(track: str, car: str) -> str:
    return f"{track}|{car}"


def save(track: str, car: str, focus: list[Focus]):
    plans = _load()
    plans[_key(track, car)] = [asdict(f) for f in focus]
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")


def clear(track: str, car: str):
    plans = _load()
    plans.pop(_key(track, car), None)
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")


def active(track: str, car: str) -> list[Focus]:
    return [Focus(**f) for f in _load().get(_key(track, car), [])]


def focus_for(plan: list[Focus], zone, tol=100) -> Focus | None:
    """Objetivo del plan para esta frenada (por cercanía del vértice)."""
    hits = [f for f in plan if abs(f.apex - zone.apex) <= tol]
    return min(hits, key=lambda f: abs(f.apex - zone.apex)) if hits else None
