"""Experimento A/B: dos sesiones con el mismo coche y circuito y distinto reglaje, ¿cuál va mejor y dónde?

Para no fiarse de una vuelta con suerte, se compara el ritmo (mediana de tus vueltas limpias) y, curva a
curva, la mediana del tiempo en cada frenada de todas las vueltas limpias de cada sesión, medidas contra la
misma referencia (la mejor vuelta de A).
"""
import statistics
from dataclasses import dataclass, field

import numpy as np

from . import analysis, lapstats

MAX_LAPS = 15


@dataclass
class Side:
    best: float | None
    pace: float | None           # mediana del 80 % más rápido de las vueltas válidas
    spread: float | None         # desviación típica de esas vueltas (consistencia)
    laps: int
    best_sectors: list = field(default_factory=list)


@dataclass
class CornerDiff:
    idx: int
    apex: float
    a: float          # s respecto a la referencia (mediana)
    b: float

    @property
    def diff(self) -> float:       # >0: B pierde frente a A
        return self.b - self.a


@dataclass
class ABResult:
    a: Side
    b: Side
    corners: list
    setup_diff: list               # [(categoría, nombre, valor A, valor B)]
    weather: tuple                 # (tiempo de A, tiempo de B)

    def verdict(self) -> str:
        if self.a.pace is None or self.b.pace is None:
            return "Hacen falta vueltas válidas en las dos sesiones para comparar."
        d = self.b.pace - self.a.pace
        if abs(d) < 0.08:
            head = "Mismo ritmo con los dos reglajes"
        else:
            head = f"{'B' if d < 0 else 'A'} va {abs(d):.3f} s por vuelta más rápido de ritmo"
        gains = [c for c in self.corners if c.diff < -0.04]
        losses = [c for c in self.corners if c.diff > 0.04]
        parts = [head + "."]
        if gains:
            parts.append("B gana en " + ", ".join(f"F{c.idx}" for c in sorted(gains, key=lambda c: c.diff)[:4]) + ".")
        if losses:
            parts.append("B pierde en " + ", ".join(f"F{c.idx}" for c in sorted(losses, key=lambda c: -c.diff)[:4]) + ".")
        if self.a.spread and self.b.spread and abs(self.a.spread - self.b.spread) > 0.15:
            parts.append(f"Con {'B' if self.b.spread < self.a.spread else 'A'} eres más regular.")
        if self.weather[0] != self.weather[1]:
            parts.append(f"Ojo: el tiempo era distinto ({self.weather[0]} / {self.weather[1]}).")
        return " ".join(parts)


def _clean(sd):
    laps = [l for l in sd.laps if l.valid]
    laps.sort(key=lambda l: l.time)
    return laps[:max(1, int(len(laps) * 0.8))] if laps else []


def _side(sd) -> Side:
    laps = [l for l in sd.laps if l.valid]
    clean = _clean(sd)
    times = [l.time for l in clean]
    sec = []
    for k in ("s1", "s2", "s3"):
        vals = [getattr(l, k) for l in laps if getattr(l, k) > 0]
        sec.append(min(vals) if vals else None)
    return Side(min((l.time for l in laps), default=None), statistics.median(times) if times else None,
                statistics.pstdev(times) if len(times) > 1 else None, len(laps), sec)


def _corner_medians(sd, ref, L, laps) -> dict:
    vals = {}
    for lap in laps[:MAX_LAPS]:
        data = analysis.by_distance(sd.lap_data(lap.num), L)
        dlt = analysis.delta(ref, data)
        for z in analysis.compare_zones(ref, data, dlt):
            vals.setdefault(z.zone.idx, (z.zone.apex, []))[1].append(z.time_diff)
    return {k: (apex, float(np.median(v))) for k, (apex, v) in vals.items() if v}


def compare(sd_a, sd_b) -> ABResult:
    a, b = _side(sd_a), _side(sd_b)
    corners = []
    clean_a, clean_b = _clean(sd_a), _clean(sd_b)
    if clean_a and clean_b:
        L = sd_a.track_len
        best_a = min(clean_a, key=lambda l: l.time)
        ref = analysis.by_distance(sd_a.lap_data(best_a.num), L)
        ma = _corner_medians(sd_a, ref, L, clean_a)
        mb = _corner_medians(sd_b, ref, L, clean_b)
        corners = [CornerDiff(k, ma[k][0], ma[k][1], mb[k][1]) for k in sorted(ma) if k in mb]
    diff = [(cat, name, va, vb) for cat, name, va, vb, changed in lapstats.setup_rows(sd_a.setup(), sd_b.setup())
            if changed]
    return ABResult(a, b, corners, diff, (sd_a.info.weather, sd_b.info.weather))
