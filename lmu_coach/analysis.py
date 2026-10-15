"""Comparación de dos vueltas por distancia: delta y análisis frenada a frenada."""
from dataclasses import dataclass

import numpy as np

from .coach import Feedback, advice
from .laps import BrakeZone, detect_brake_zones

STEP = 2.0  # metros


def by_distance(data: dict, length: float) -> dict:
    """Remuestrea una vuelta (arrays a 50 Hz) a una rejilla común de distancia."""
    d = data["d"]
    ok = np.concatenate([[True], np.diff(d) > 0])
    d = d[ok]
    grid = np.arange(0.0, length, STEP)
    out = {"d": grid}
    for key in ("t", "v", "thr", "brk", "steer", "gear", "rpm", "x", "y"):
        if key in data:
            out[key] = np.interp(grid, d, data[key][ok])
    return out


def delta(ref: dict, lap: dict) -> np.ndarray:
    """Tiempo perdido (+) o ganado (−) respecto a la referencia en cada punto (misma rejilla)."""
    return lap["t"] - ref["t"]


@dataclass
class ZoneResult:
    zone: BrakeZone
    time_diff: float
    brake_diff: float
    min_speed_diff: float
    throttle_diff: float
    my_min_speed: float
    messages: list


def compare_zones(ref: dict, lap: dict, dlt: np.ndarray) -> list[ZoneResult]:
    """Para cada frenada de la referencia, qué hiciste distinto y cuánto tiempo costó."""
    zones = detect_brake_zones({"d": ref["d"], "v": ref["v"], "thr": ref["thr"], "brk": ref["brk"]})
    d = lap["d"]
    results = []
    for i, z in enumerate(zones):
        # La zona va desde 150 m antes de frenar (sin invadir el vértice anterior)
        # hasta gas a fondo + 50 m (sin invadir la frenada siguiente)
        prev_apex = zones[i - 1].apex + 20 if i else 0.0
        z_from = max(0.0, z.start - 150, min(prev_apex, z.start - 10))
        nxt = zones[i + 1].start - 10 if i + 1 < len(zones) else d[-1]
        z_to = max(min(max(z.full_throttle + 50, z.apex + 80), nxt), z.apex + 10)
        win = (d >= z_from) & (d <= z.apex + 30)
        braking = np.where(win & (lap["brk"] > 0.12))[0]
        my_brake = d[braking[0]] if len(braking) else None
        seg = (d >= max(z.start - 50, z_from)) & (d <= z_to)
        my_min = float(lap["v"][seg].min()) if seg.any() else z.min_speed
        after = np.where((d >= z.apex) & (d <= z_to + 200) & (lap["thr"] >= 0.95))[0]
        my_full = d[after[0]] if len(after) else None
        i0, i1 = int(z_from / STEP), min(int(z_to / STEP), len(dlt) - 1)
        fb = Feedback(
            zone=z,
            time_diff=float(dlt[i1] - dlt[i0]),
            brake_diff=(my_brake - z.start) if my_brake is not None else 0.0,
            min_speed_diff=my_min - z.min_speed,
            throttle_diff=(my_full - z.full_throttle) if my_full is not None else 0.0,
            messages=[], created=0.0,
        )
        results.append(ZoneResult(z, fb.time_diff, fb.brake_diff, fb.min_speed_diff, fb.throttle_diff,
                                  my_min, advice(fb, my_brake is None)))
    return results
