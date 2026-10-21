"""Lógica del coach en directo: delta, aviso de frenada y feedback por curva."""
import time
from collections import deque
from dataclasses import dataclass

from .laps import BrakeZone, Reference
from .reader import Sample


@dataclass
class BrakeCue:
    zone: BrakeZone
    dist_to: float        # metros hasta el punto de frenada de la referencia (<0: ya pasado)
    speed_diff: float     # km/h tuyos - referencia en este punto
    braking: bool         # ¿ya estás frenando?


@dataclass
class Feedback:
    zone: BrakeZone
    time_diff: float      # s ganados (<0) o perdidos (>0) en la zona
    brake_diff: float     # m: >0 frenaste más tarde que la referencia
    min_speed_diff: float  # km/h: >0 pasaste más rápido por el vértice
    throttle_diff: float  # m: >0 aceleraste a fondo más tarde
    messages: list
    created: float


@dataclass
class _ZoneTrack:
    zone: BrakeZone
    entry_delta: float
    my_brake_start: float | None = None
    my_min_speed: float = 1e9
    my_full_throttle: float | None = None
    passed_apex: bool = False


PURPLE, GREEN, YELLOW, GREY = "purple", "green", "yellow", "grey"


@dataclass
class SectorResult:
    time: float
    diff: float | None   # contra el mismo sector de la referencia
    color: str           # PURPLE: mejor que la referencia · GREEN: mejor de la sesión · YELLOW: más lento · GREY: vuelta no válida


class SectorTracker:
    """Tiempos por sector al estilo F1, medidos en los mismos puntos que la referencia."""

    def __init__(self):
        self.bounds: list[float] = []         # distancias donde empiezan S2 y S3
        self.ref_split: list[float] | None = None
        self.session_best: list[float | None] = [None] * 3
        self.cur: list[SectorResult | None] = [None] * 3
        self.prev: list[SectorResult | None] = [None] * 3
        self.idx = 0
        self.live_delta = None
        self._start_t = 0.0
        self._start_delta = 0.0
        self._started = False

    def set_reference(self, ref):
        self.ref_split = None
        if ref and len(ref.lap.sectors) == 2:
            self.bounds = list(ref.lap.sectors)
            t1, t2 = ref.time_at(self.bounds[0]), ref.time_at(self.bounds[1])
            self.ref_split = [t1, t2 - t1, ref.lap.lap_time - t2]

    def learn_bounds(self, sectors: list):
        """Sin referencia con sectores, usa los que marca el juego en la primera vuelta grabada."""
        if not self.bounds and len(sectors) == 2:
            self.bounds = list(sectors)

    def new_lap(self):
        if any(self.cur):
            self.prev = self.cur
        self.cur = [None] * 3
        self.idx = 0
        self._start_t = self._start_delta = 0.0
        self._started = False
        self.live_delta = None

    def update(self, d: float, t_lap: float, delta: float | None, invalid: bool):
        if len(self.bounds) != 2 or d < 0:
            return
        target = 0 if d < self.bounds[0] else 1 if d < self.bounds[1] else 2
        if not self._started:
            # solo medimos si hemos visto empezar el sector 1 (no al engancharnos a mitad de vuelta)
            self._started = target == 0
            self.idx = target
            return
        while self.idx < target:
            self._close(self.idx, t_lap - self._start_t, invalid)
            self.idx += 1
            self._start_t = t_lap
            self._start_delta = delta or 0.0
        self.live_delta = (delta - self._start_delta) if delta is not None else None

    def finish_lap(self, lap_time: float, valid: bool):
        if self._started and self.idx == 2 and self.cur[2] is None:
            self._close(2, lap_time - self._start_t, not valid)

    def _close(self, i, t, invalid):
        ref = self.ref_split[i] if self.ref_split else None
        diff = t - ref if ref is not None else None
        if invalid:
            color = GREY
        else:
            best = self.session_best[i]
            if ref is not None and t < ref:
                color = PURPLE
            elif best is None or t < best:
                color = GREEN
            else:
                color = YELLOW
            if best is None or t < best:
                self.session_best[i] = t
        self.cur[i] = SectorResult(t, diff, color)

    def ideal(self) -> float | None:
        """Vuelta ideal: suma de tus mejores sectores de la sesión."""
        if all(b is not None for b in self.session_best):
            return sum(self.session_best)
        return None


class LiveCoach:
    WARN_SECONDS = 3.0      # avisa de la frenada con este margen
    WARN_MIN_DIST = 120.0
    ZONE_LOOKBACK = 200.0   # empieza a vigilar la zona antes del punto de frenada

    def __init__(self):
        self.ref: Reference | None = None
        self.sectors = SectorTracker()
        self.reset_lap()
        self.last_feedback: Feedback | None = None
        self.lap_feedback: list[Feedback] = []

    def set_reference(self, ref: Reference | None):
        self.ref = ref
        self.sectors.set_reference(ref)
        self.reset_lap()

    def reset_lap(self):
        self.sectors.new_lap()
        self.delta = None
        self._delta_hist = deque(maxlen=120)  # (d, delta)
        self._active: _ZoneTrack | None = None
        self._done_zones = set()
        self.lap_feedback = []

    # --- por muestra -----------------------------------------------------

    def update(self, s: Sample, d: float, t_into_lap: float, invalid: bool = False):
        """d: distancia corregida en la vuelta; t_into_lap: tiempo de vuelta actual."""
        if not self.ref or d < 0:
            self.delta = None
            self.sectors.update(d, t_into_lap, None, invalid)
            return
        self.delta = t_into_lap - self.ref.time_at(d)
        self.sectors.update(d, t_into_lap, self.delta, invalid)
        self._delta_hist.append((d, self.delta))
        self._track_zone(s, d)

    def delta_trend(self, window=60.0):
        """Variación del delta en los últimos `window` metros (negativo = ganando)."""
        if len(self._delta_hist) < 2:
            return 0.0
        d_now, delta_now = self._delta_hist[-1]
        for d, delta in reversed(self._delta_hist):
            if d_now - d >= window:
                return delta_now - delta
        return delta_now - self._delta_hist[0][1]

    def brake_cue(self, s: Sample, d: float) -> BrakeCue | None:
        if not self.ref:
            return None
        warn = max(self.WARN_MIN_DIST, s.speed / 3.6 * self.WARN_SECONDS)
        for z in self.ref.zones:
            if z.idx in self._done_zones:
                continue
            dist_to = z.start - d
            if dist_to <= warn and d <= z.apex:
                return BrakeCue(z, dist_to, s.speed - self.ref.speed_at(d), s.brake > 0.1)
            if dist_to > warn:
                break
        return None

    # --- evaluación de zonas ---------------------------------------------

    def _track_zone(self, s: Sample, d: float):
        a = self._active
        if a is None:
            prev_apex = 0.0
            for z in self.ref.zones:
                # en frenadas encadenadas, la vigilancia empieza pasado el vértice anterior
                lookback = max(10.0, min(self.ZONE_LOOKBACK, z.start - prev_apex - 20))
                if z.idx not in self._done_zones and z.start - lookback <= d <= z.apex:
                    self._active = a = _ZoneTrack(z, self.delta)
                    break
                prev_apex = z.apex
            if a is None:
                return
        z = a.zone
        if a.my_brake_start is None and s.brake > 0.12 and d <= z.apex + 30:
            a.my_brake_start = d
        if d <= z.full_throttle + 50:
            a.my_min_speed = min(a.my_min_speed, s.speed)
        if d >= z.apex:
            a.passed_apex = True
        if a.passed_apex and a.my_full_throttle is None and s.throttle >= 0.95:
            a.my_full_throttle = d
        exit_d = max(z.full_throttle, z.apex + 80) + 30
        nxt = next((n for n in self.ref.zones if n.idx == z.idx + 1), None)
        if nxt:  # no invadir la frenada siguiente
            exit_d = max(min(exit_d, nxt.start - 10), z.apex + 10)
        if d >= exit_d:
            self._finish_zone(a, d)

    def _finish_zone(self, a: _ZoneTrack, d: float):
        z = a.zone
        self._done_zones.add(z.idx)
        self._active = None
        fb = Feedback(
            zone=z,
            time_diff=self.delta - a.entry_delta,
            brake_diff=(a.my_brake_start - z.start) if a.my_brake_start is not None else 0.0,
            min_speed_diff=a.my_min_speed - z.min_speed if a.my_min_speed < 1e9 else 0.0,
            throttle_diff=(a.my_full_throttle - z.full_throttle) if a.my_full_throttle is not None else 0.0,
            messages=[],
            created=time.monotonic(),
        )
        fb.messages = advice(fb, a.my_brake_start is None)
        self.last_feedback = fb
        self.lap_feedback.append(fb)


def advice(fb: Feedback, no_brake: bool) -> list[str]:
    """Consejos cortos y legibles en carrera, los más importantes primero."""
    msgs = []
    if no_brake:
        msgs.append("sin frenar (la referencia frena aquí)")
    elif fb.brake_diff < -12:
        msgs.append(f"frenaste {abs(fb.brake_diff):.0f} m antes")
    elif fb.brake_diff > 12:
        msgs.append(f"frenaste {fb.brake_diff:.0f} m más tarde")
    if fb.min_speed_diff < -3:
        msgs.append(f"vértice {abs(fb.min_speed_diff):.0f} km/h más lento")
    elif fb.min_speed_diff > 3:
        msgs.append(f"vértice +{fb.min_speed_diff:.0f} km/h")
    if fb.throttle_diff > 15:
        msgs.append(f"gas a fondo {fb.throttle_diff:.0f} m tarde")
    elif fb.throttle_diff < -15:
        msgs.append(f"gas a fondo {abs(fb.throttle_diff):.0f} m antes")
    if not msgs:
        msgs.append("como la referencia")
    return msgs


def spoken_tip(fb: Feedback, no_brake: bool = False) -> str | None:
    """La causa principal de lo que has perdido en una frenada, dicha en una frase corta («frenas quince metros
    antes»). None si no has perdido nada apreciable o no hay una causa clara."""
    from .speech import number_es

    def n(x):
        """Número delante de «metros» o «kilómetros»: «veintiún», «cuarenta y un»."""
        x = int(round(abs(x)))
        w = number_es(x) if x < 100 else str(x)
        return "veintiún" if w == "veintiuno" else w[:-1] if w.endswith(" uno") or w == "uno" else w

    if fb.time_diff < 0.1:
        return None
    if no_brake:
        return "no frenas donde frena tu referencia"
    causes = []      # (peso, frase): la que más explica la pérdida
    if fb.brake_diff < -12:
        causes.append((abs(fb.brake_diff) / 12, f"frenas {n(fb.brake_diff)} metros antes"))
    if fb.min_speed_diff < -3:
        causes.append((abs(fb.min_speed_diff) / 3, f"{n(fb.min_speed_diff)} kilómetros por hora menos en el vértice"))
    if fb.throttle_diff > 15:
        causes.append((fb.throttle_diff / 15, f"aceleras {n(fb.throttle_diff)} metros tarde"))
    if fb.brake_diff > 12 and fb.min_speed_diff < -3:
        causes.append((99, "frenas tarde y te pasas en el vértice"))
    if not causes:
        return None
    return max(causes)[1]
