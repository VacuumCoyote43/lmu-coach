"""Grabación de vueltas, almacenamiento y vuelta de referencia."""
import bisect
import gzip
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .reader import Sample

CHANNELS = ("d", "t", "v", "thr", "brk", "steer", "gear", "x", "z")


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "desconocido"


def fmt_time(seconds: float) -> str:
    if seconds is None or seconds <= 0:
        return "--:--.---"
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"


@dataclass
class Lap:
    track: str
    car: str
    lap_time: float
    track_len: float
    recorded_at: str
    data: dict = field(default_factory=lambda: {c: [] for c in CHANNELS})
    sectors: list = field(default_factory=list)  # distancias (m) donde empiezan S2 y S3

    def to_json(self) -> dict:
        return {"track": self.track, "car": self.car, "lap_time": self.lap_time,
                "track_len": self.track_len, "recorded_at": self.recorded_at, "data": self.data,
                "sectors": self.sectors}

    @classmethod
    def from_json(cls, obj: dict) -> "Lap":
        return cls(obj["track"], obj["car"], obj["lap_time"], obj["track_len"], obj["recorded_at"], obj["data"],
                   obj.get("sectors", []))


class LapStore:
    """Vueltas en data/laps/<circuito>/<coche>/<tiempo>_<fecha>.json.gz"""

    def __init__(self, root: Path):
        self.root = Path(root)

    def folder(self, track: str, car: str) -> Path:
        return self.root / slug(track) / slug(car)

    def save(self, lap: Lap) -> Path:
        folder = self.folder(lap.track, lap.car)
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{lap.lap_time:08.3f}_{lap.recorded_at.replace(':', '-')}.json.gz"
        path = folder / name
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(lap.to_json(), f, separators=(",", ":"))
        return path

    def load(self, path: Path) -> Lap:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return Lap.from_json(json.load(f))

    def best(self, track: str, car: str) -> Lap | None:
        # El nombre empieza por el tiempo con ceros a la izquierda: el orden alfabético es el de tiempos
        files = sorted(p for p in self.folder(track, car).glob("*.json.gz") if p.name != self.PINNED)
        return self.load(files[0]) if files else None

    # Referencia fijada a mano desde la app: tiene prioridad sobre la mejor vuelta
    PINNED = "fijada.json.gz"

    def pin(self, lap: Lap) -> Path:
        folder = self.folder(lap.track, lap.car)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / self.PINNED
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(lap.to_json(), f, separators=(",", ":"))
        return path

    def unpin(self, track: str, car: str):
        (self.folder(track, car) / self.PINNED).unlink(missing_ok=True)

    def pinned(self, track: str, car: str) -> Lap | None:
        path = self.folder(track, car) / self.PINNED
        return self.load(path) if path.exists() else None


class LapRecorder:
    """Acumula muestras de la vuelta en curso y entrega vueltas válidas completas."""

    MIN_LAP_TIME = 20.0

    def __init__(self, on_lap_complete):
        self.on_lap_complete = on_lap_complete  # callback(lap: Lap | None, lap_time, valid, reason)
        self._reset(None)

    def _reset(self, s: Sample | None):
        self.lap_no = s.lap if s else None
        self.lap_start_et = s.lap_start_et if s else None
        self.data = {c: [] for c in CHANNELS}
        # Solo vale si hemos visto empezar la vuelta en la línea de meta
        self.started_clean = bool(s) and s.lap_dist < 200 or (bool(s) and s.lap_dist > s.track_len - 200)
        self.invalid_reason = None if s and not s.in_pits else "salida de boxes"
        self._last_et = None
        self._pre_line = True   # aún con la distancia de la vuelta anterior (scoring retrasado)
        self.cur_dist = -1.0
        self.sectors = []       # distancias donde el juego cambió a S2 y a S3
        self._sector = s.sector if s else None

    def feed(self, s: Sample):
        if self.lap_no is None:
            self._reset(s)
            self.started_clean = False  # nos hemos enganchado a mitad de vuelta
            self.invalid_reason = "vuelta incompleta"
            self._pre_line = False
        if s.lap != self.lap_no:
            self._finish(s)
            self._reset(s)
        if s.et == self._last_et:
            return  # el juego no ha actualizado (pausa o sondeo más rápido que la física)
        self._last_et = s.et
        if s.in_pits and not self.invalid_reason:
            self.invalid_reason = "boxes"
        if s.lap_invalid and not self.invalid_reason:
            self.invalid_reason = "límites de pista / vuelta invalidada"

        t = s.et - self.lap_start_et
        d = self.cur_dist = self._corrected_dist(s)
        if d < 0:
            return
        if s.sector != self._sector:
            if s.sector in (1, 2) and len(self.sectors) == s.sector - 1:
                self.sectors.append(round(d, 1))
            self._sector = s.sector
        dd = self.data
        if dd["d"] and d <= dd["d"][-1]:
            return
        for key, val in (("d", d), ("t", t), ("v", s.speed), ("thr", s.throttle), ("brk", s.brake),
                         ("steer", s.steer), ("gear", s.gear), ("x", s.x), ("z", s.z)):
            dd[key].append(round(val, 4) if isinstance(val, float) else val)

    def _corrected_dist(self, s: Sample) -> float:
        """La distancia del scoring va desfasada con el contador de vueltas: corrige el cruce de meta.

        Justo tras cambiar de vuelta puede llegar aún la distancia de la anterior (≈L) → negativa.
        Justo antes, puede llegar ya reiniciada (≈0) → se le suma L.
        """
        d, L = s.lap_dist, s.track_len
        if L <= 0:
            return d
        if self._pre_line:
            if d > L * 0.5:
                return d - L
            self._pre_line = False
        last = self.data["d"][-1] if self.data["d"] else 0.0
        if last > L * 0.7 and d < L * 0.3:
            return d + L
        return d

    def _finish(self, nxt: Sample):
        if self.lap_start_et is None:
            return
        lap_time = nxt.lap_start_et - self.lap_start_et
        reason = self.invalid_reason
        if not reason and not self.started_clean:
            reason = "vuelta incompleta"
        dd = self.data
        if not reason and (not dd["d"] or dd["d"][-1] < nxt.track_len * 0.95):
            reason = "faltan datos"
        if not reason and lap_time < self.MIN_LAP_TIME:
            reason = "demasiado corta"
        valid = reason is None
        lap = None
        if dd["d"]:
            lap = Lap(nxt.track, nxt.car, round(lap_time, 3), nxt.track_len,
                      time.strftime("%Y-%m-%dT%H:%M:%S"), dd,
                      self.sectors if len(self.sectors) == 2 else [])
        self.on_lap_complete(lap, lap_time, valid, reason)


@dataclass
class BrakeZone:
    idx: int            # número de curva (1..n)
    start: float        # distancia donde empieza a frenar (m)
    end: float          # distancia donde suelta el freno (m)
    apex: float         # distancia de la velocidad mínima (m)
    entry_speed: float  # km/h al empezar a frenar
    min_speed: float    # km/h mínima
    full_throttle: float  # distancia donde vuelve a gas a fondo (m)
    peak_brake: float

    @property
    def name(self) -> str:
        return f"Frenada {self.idx}"


class Reference:
    """Vuelta de referencia con consultas por distancia."""

    def __init__(self, lap: Lap):
        self.lap = lap
        self.d = lap.data["d"]
        self.t = lap.data["t"]
        self.v = lap.data["v"]
        self.thr = lap.data["thr"]
        self.brk = lap.data["brk"]
        self.zones = detect_brake_zones(lap.data)

    def _interp(self, arr, d):
        xs = self.d
        if not xs:
            return 0.0
        if d <= xs[0]:
            return arr[0]
        if d >= xs[-1]:
            return arr[-1]
        i = bisect.bisect_right(xs, d)
        x0, x1 = xs[i - 1], xs[i]
        f = (d - x0) / (x1 - x0) if x1 > x0 else 0.0
        return arr[i - 1] + (arr[i] - arr[i - 1]) * f

    def time_at(self, d):
        return self._interp(self.t, d)

    def speed_at(self, d):
        return self._interp(self.v, d)

    def throttle_at(self, d):
        return self._interp(self.thr, d)

    def brake_at(self, d):
        return self._interp(self.brk, d)


def detect_brake_zones(data: dict, on=0.12, off=0.05, merge_gap=40.0, min_drop=12.0) -> list[BrakeZone]:
    d, v, thr, brk = data["d"], data["v"], data["thr"], data["brk"]
    n = len(d)
    zones = []
    i = 0
    while i < n:
        if brk[i] >= on:
            start = i
            j = i
            last_on = i
            # Avanza mientras el freno siga pisado (permitiendo huecos cortos de trail braking)
            while j < n and (brk[j] >= off or d[j] - d[last_on] < merge_gap):
                if brk[j] >= off:
                    last_on = j
                j += 1
            end = last_on
            # Ápice: velocidad mínima desde la frenada hasta 300 m después de soltar o hasta gas a fondo
            k = end
            limit = d[end] + 300
            while k < n - 1 and d[k] < limit and thr[k] < 0.95:
                k += 1
            seg = range(start, max(k, end) + 1)
            apex_i = min(seg, key=lambda x: v[x])
            full_i = k
            peak = max(brk[x] for x in range(start, end + 1))
            if v[start] - v[apex_i] >= min_drop and peak >= 0.2:
                zones.append(BrakeZone(len(zones) + 1, d[start], d[end], d[apex_i], v[start],
                                       v[apex_i], d[full_i], peak))
            i = max(j, k)
        else:
            i += 1
    return zones


def save_async(store: LapStore, lap: Lap, done=None):
    def work():
        path = store.save(lap)
        if done:
            done(path)
    threading.Thread(target=work, daemon=True).start()
