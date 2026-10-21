"""Ingeniero de carrera: posición, diferencias con los de delante y detrás y avisos de lo que pasa.

Trabaja con la clasificación de la memoria compartida de LMU (todos los coches). Las diferencias se
calculan por el avance en pista (vueltas + fracción) y el ritmo estimado, dentro de tu clase.
Devuelve frases cortas para la voz y un resumen para el overlay; no habla más de lo necesario.
"""
import time
from dataclasses import dataclass, field

CLOSE_S = 1.0          # coche detrás «encima»
POSITION_SETTLE_S = 3.0   # el cambio de posición se anuncia cuando lleva este tiempo sin cambiar
CLOSE_RESET_S = 1.6    # vuelve a avisar solo si se aleja más que esto
FAST_CLASS_S = 2.5     # coche de otra clase más rápida que te va a alcanzar


@dataclass
class RaceCar:
    place: int
    cls: str
    driver: str
    laps: int              # vueltas completadas
    lap_dist: float        # m en la vuelta actual
    in_pits: bool
    pitstops: int
    is_player: bool
    best: float
    last: float
    est: float             # tiempo de vuelta estimado por el juego
    finished: bool = False
    behind_leader: float = 0.0      # s detrás del líder (según el juego)
    laps_behind_leader: int = 0


def _pace(c: RaceCar) -> float:
    """Ritmo real del coche: última vuelta, si no la mejor, si no la estimación del juego."""
    for t in (c.last, c.best, c.est):
        if t and t > 0:
            return t
    return 0.0


@dataclass
class RaceInfo:
    is_race: bool
    track_len: float
    time_left: float | None      # s (None si es a vueltas)
    laps_left: int | None
    cars: list = field(default_factory=list)


def _progress(c: RaceCar, L: float) -> float:
    return c.laps + (max(0.0, c.lap_dist) / L if L else 0.0)


def _n(i: int) -> str:
    from .speech import number_es
    return number_es(i) if 0 <= i < 100 else str(i)


def _num(x: float) -> str:
    """1.23 → «uno coma dos» (para la voz)."""
    from .speech import number_es
    x = abs(x)
    if x >= 10:
        return f"{number_es(int(round(x)))}"
    e, d = int(x), int(round((x - int(x)) * 10))
    if d == 10:
        e, d = e + 1, 0
    return f"{number_es(e)} coma {number_es(d)}"


class Engineer:
    def __init__(self, close_s=CLOSE_S, fast_s=FAST_CLASS_S, summary_every=1):
        self.configure(close_s, fast_s, summary_every)
        self.reset()

    def configure(self, close_s=None, fast_s=None, summary_every=None):
        if close_s:
            self.close_s = float(close_s)
            self.close_reset_s = self.close_s + (CLOSE_RESET_S - CLOSE_S)
        if fast_s:
            self.fast_s = float(fast_s)
        if summary_every:
            self.summary_every = max(1, int(summary_every))

    def reset(self):
        self.place = None
        self.last_lap = None
        self.gap_hist = {}                 # driver -> [(vuelta, diferencia)]
        self.alerted_close = set()
        self.alerted_pit = set()
        self.alerted_fast = {}
        self.said_5min = self.said_last = False
        self.state = None
        self.pending_summary = None        # resumen de la vuelta (se dice unos segundos después de cruzar meta)
        self._pos_seen, self._pos_since = None, 0.0

    def update(self, info: RaceInfo, now: float | None = None) -> list[tuple[str, str]]:
        """Procesa una lectura (unas 4 por segundo) y devuelve [(frase, tipo)] para decir ahora."""
        now = time.monotonic() if now is None else now
        if not info.is_race or not info.cars:
            self.state = None
            return []
        me = next((c for c in info.cars if c.is_player), None)
        if me is None:
            return []
        L = info.track_len or 1.0
        lap_t = _pace(me) or 100.0
        mine = sorted([c for c in info.cars if c.cls == me.cls], key=lambda c: c.place)
        pos = mine.index(me) + 1
        ahead = mine[pos - 2] if pos > 1 else None
        behind = mine[pos] if pos < len(mine) else None
        def gap(a, b):
            """s que «a» va por delante de «b»: el cálculo del juego si van en la misma vuelta del líder,
            si no por el avance en pista."""
            if a.laps_behind_leader == b.laps_behind_leader and (a.behind_leader or b.behind_leader):
                return b.behind_leader - a.behind_leader
            return (_progress(a, L) - _progress(b, L)) * lap_t
        g_ahead = gap(ahead, me) if ahead else None
        g_behind = gap(me, behind) if behind else None
        out = []

        # cambios de posición: se anuncian juntos cuando la posición lleva unos segundos estable
        # (en una curva con varios adelantamientos, un solo mensaje con el resultado)
        if self.place is None:
            self.place = pos
        if pos != self._pos_seen:
            self._pos_seen, self._pos_since = pos, now
        elif pos != self.place and now - self._pos_since >= POSITION_SETTLE_S and not me.in_pits:
            n = abs(self.place - pos)
            if n == 1:
                txt = f"Subes a la posición {_n(pos)}" if pos < self.place else f"Bajas a la posición {_n(pos)}"
            else:
                txt = f"{'Ganas' if pos < self.place else 'Pierdes'} {_n(n)} posiciones. Posición {_n(pos)}"
            out.append((txt, "position"))
            self.place = pos

        # coche de tu clase encima
        if behind and g_behind is not None and not behind.in_pits:
            if g_behind < self.close_s and behind.driver not in self.alerted_close and not me.in_pits and me.laps >= 1:
                self.alerted_close.add(behind.driver)
                out.append((f"Coche detrás a {_num(g_behind)}", "close"))
            elif g_behind > self.close_reset_s:
                self.alerted_close.discard(behind.driver)

        # paradas de los rivales directos
        for who, label in ((ahead, "El de delante"), (behind, "El de detrás")):
            if who is None:
                continue
            key = (who.driver, who.pitstops)
            if who.in_pits and key not in self.alerted_pit:
                self.alerted_pit.add(key)
                out.append((f"{label} entra en boxes", "pit"))

        # clase más rápida que te va a alcanzar (multiclase)
        for c in info.cars:
            if c.cls == me.cls or c.in_pits or not _pace(c) or _pace(c) > lap_t * 0.97:
                continue
            g = ((_progress(me, L) - _progress(c, L)) * lap_t) % lap_t   # cuánto le falta para alcanzarte
            if 0 < g < self.fast_s and now - self.alerted_fast.get(c.driver, 0) > 60:
                self.alerted_fast[c.driver] = now
                out.append((f"{c.cls} detrás, déjale sitio", "fastclass"))
                break

        # resumen al empezar cada vuelta
        if me.laps != self.last_lap:
            if self.last_lap is not None and not me.in_pits and me.laps % self.summary_every == 0:
                self.pending_summary = self._lap_summary(pos, len(mine), ahead, behind, g_ahead, g_behind, me.laps)
            self.last_lap = me.laps
            for c, g in ((ahead, g_ahead), (behind, g_behind)):
                if c is not None and g is not None:
                    self.gap_hist.setdefault(c.driver, []).append((me.laps, g))

        # final de carrera
        if info.time_left is not None:
            if 0 < info.time_left <= 300 and not self.said_5min:
                self.said_5min = True
                out.append(("Quedan cinco minutos", "end5"))
        if info.laps_left == 1 and not self.said_last:
            self.said_last = True
            out.append(("Última vuelta", "lastlap"))

        self.state = {"pos": pos, "of": len(mine), "cls": me.cls, "ahead": g_ahead, "behind": g_behind,
                      "trend_ahead": self._trend(ahead.driver) if ahead else None,
                      "trend_behind": self._trend(behind.driver) if behind else None}
        return [x for x in out if x and x[0]]

    def _trend(self, driver) -> float | None:
        """Cuánto cambia la diferencia con ese coche por vuelta (media de las 3 últimas vueltas)."""
        h = self.gap_hist.get(driver, [])[-4:]
        if len(h) < 2:
            return None
        return (h[-1][1] - h[0][1]) / max(1, h[-1][0] - h[0][0])

    def _lap_summary(self, pos, n, ahead, behind, g_ahead, g_behind, lap) -> str:
        parts = [f"Posición {_n(pos)} de {_n(n)}"]
        if ahead is not None and g_ahead is not None and g_ahead < 30:
            parts.append(f"Delante a {_num(g_ahead)}")
            t = self._trend(ahead.driver)
            if t is not None and abs(t) >= 0.15:
                parts.append(f"{'Recortas' if t < 0 else 'Pierdes'} {_num(abs(t))} por vuelta")
        if behind is not None and g_behind is not None and g_behind < 30:
            parts.append(f"Detrás a {_num(g_behind)}")
        return ". ".join(parts)
