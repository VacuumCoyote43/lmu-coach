"""Spotter (coches a izquierda y derecha) y daños del coche, a partir de la telemetría de LMU.

Spotter: con la posición de todos los coches, mira cuáles están solapados contigo a un lado. Qué eje
es «derecha» en el mundo de LMU se aprende solo: al girar a la derecha, el morro se va hacia tu
derecha; hasta que no lo ha comprobado en unas curvas, no dice lados (mejor callar que equivocarse).
"""
import math
import time
from dataclasses import dataclass

CAR_LEN = 5.2          # m de solape longitudinal para considerar que va «al lado»
SIDE_MIN, SIDE_MAX = 1.2, 4.8   # m de separación lateral
CALIB_NEEDED = 4.0     # «votos» de giro para fiarse del sentido
MIN_GAP_S = 0.6        # entre mensajes del spotter


@dataclass
class SpotFrame:
    me: tuple              # (x, z)
    vel: tuple             # velocidad en el mundo (x, z) m/s
    steer: float           # -1 izquierda … 1 derecha
    others: list           # [(x, z, velocidad m/s)]


# texto de cada aviso (la clave es la del catálogo de mensajes de config.py)
TEXT = {"spot_left": "Izquierda", "spot_right": "Derecha", "spot_middle": "En medio", "spot_clear": "Libre",
        "spot_ready": "Spotter listo"}


class Spotter:
    """update() devuelve (clave, frase) o None; quién lo usa decide si se dice (mensajes activados)."""

    def __init__(self, car_len=CAR_LEN, side_max=SIDE_MAX, min_gap=MIN_GAP_S, still_s=4.0):
        self.car_len, self.side_max, self.min_gap, self.still_s = car_len, side_max, min_gap, still_s
        self._ready_said = False
        self._still_at = 0.0
        self.calib = 0.0          # >0: el eje candidato es la derecha; <0: es la izquierda
        self.prev_fwd = None
        self.left = self.right = False
        self._since = {"left": None, "right": None}   # desde cuándo hay (o no) coche a cada lado
        self._shown = (False, False)
        self.last_msg = 0.0
        self.state = None

    @property
    def calibrated(self) -> bool:
        return abs(self.calib) >= CALIB_NEEDED

    def configure(self, car_len=None, side_max=None, min_gap=None, still_s=None):
        if car_len:
            self.car_len = float(car_len)
        if side_max:
            self.side_max = max(SIDE_MIN + 0.5, float(side_max))
        if min_gap is not None:
            self.min_gap = float(min_gap)
        if still_s:
            self.still_s = float(still_s)

    def update(self, f: SpotFrame, now: float | None = None) -> tuple[str, str] | None:
        now = time.monotonic() if now is None else now
        vx, vz = f.vel
        speed = math.hypot(vx, vz)
        if speed < 8:              # parado o en boxes
            self.prev_fwd = None
            self.state = None
            return None
        fwd = (vx / speed, vz / speed)
        cand = (-fwd[1], fwd[0])   # perpendicular; la calibración dice si es derecha o izquierda
        # calibrar: al girar, el morro se mueve hacia el lado del volante
        if self.prev_fwd is not None and abs(f.steer) > 0.12 and speed > 15:
            d = (fwd[0] - self.prev_fwd[0], fwd[1] - self.prev_fwd[1])
            turn = d[0] * cand[0] + d[1] * cand[1]
            if abs(turn) > 1e-4:
                self.calib = max(-50.0, min(50.0, self.calib + math.copysign(1.0, turn * f.steer)))
        self.prev_fwd = fwd
        if not self.calibrated:
            self.state = None
            return None
        if not self._ready_said:
            self._ready_said = True
            self.last_msg = now
            return "spot_ready", TEXT["spot_ready"]
        right = cand if self.calib > 0 else (-cand[0], -cand[1])
        left_now = right_now = False
        for x, z, v in f.others:
            dx, dz = x - f.me[0], z - f.me[1]
            lon = dx * fwd[0] + dz * fwd[1]
            lat = dx * right[0] + dz * right[1]
            if abs(lon) < self.car_len and SIDE_MIN < abs(lat) < self.side_max and v > 5:
                if lat > 0:
                    right_now = True
                else:
                    left_now = True
        self.left, self.right = left_now, right_now
        self.state = {"left": left_now, "right": right_now}
        return self._message(now)

    def _message(self, now) -> tuple[str, str] | None:
        """Aviso al cambiar el estado (con un poco de margen para que no parpadee) y, mientras siga
        igual, el recordatorio «sigue ahí»."""
        cur = (self.left, self.right)
        if now - self.last_msg < self.min_gap:
            return None
        if cur == self._shown:
            if any(cur) and now - self._still_at >= self.still_s:
                self._still_at = now
                side = "en medio" if all(cur) else "a la izquierda" if cur[0] else "a la derecha"
                return "spot_still", ("Sigues " if all(cur) else "Sigue ") + side
            return None
        before = self._shown
        self._shown = cur
        self.last_msg = self._still_at = now
        if cur == (True, True):
            return "spot_middle", TEXT["spot_middle"]
        if cur == (True, False) and not before[0]:
            return "spot_left", TEXT["spot_left"]
        if cur == (False, True) and not before[1]:
            return "spot_right", TEXT["spot_right"]
        if cur == (False, False):
            return "spot_clear", TEXT["spot_clear"]
        if before == (True, True):    # de tres en paralelo a uno solo al lado
            return "spot_clear_side", "Libre a la izquierda" if cur[1] else "Libre a la derecha"
        return None


# --------------------------------------------------------------------------- daños

WHEEL_NAMES = ("delantera izquierda", "delantera derecha", "trasera izquierda", "trasera derecha")


class DamageWatch:
    """Avisa de los daños nuevos: golpes que abollan, piezas sueltas, pinchazos y motor."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.dents = None
        self.detached = False
        self.flat = [False] * 4
        self.wheel_off = [False] * 4
        self.overheat_said = 0.0
        self.state = None

    def update(self, d: dict, now: float | None = None) -> list[tuple[str, str]]:
        """[(clave, frase)] de los daños nuevos."""
        now = time.monotonic() if now is None else now
        out = []
        dents = list(d["dents"])
        if self.dents is None:
            self.dents = dents
        worse = sum(dents) > sum(self.dents)
        if worse:
            level = max(dents)
            out.append(("dmg_body", "Daños fuertes en la carrocería" if level >= 2 else "Daños en la carrocería"))
        self.dents = dents
        if d["detached"] and not self.detached:
            out.append(("dmg_part", "Has perdido alguna pieza"))
        self.detached = d["detached"]
        for i in range(4):
            if d["wheel_off"][i] and not self.wheel_off[i]:
                out.append(("dmg_tyre", f"Has perdido la rueda {WHEEL_NAMES[i]}"))
            elif d["flat"][i] and not self.flat[i]:
                out.append(("dmg_tyre", f"Pinchazo {WHEEL_NAMES[i]}"))
        self.flat, self.wheel_off = list(d["flat"]), list(d["wheel_off"])
        if d["overheating"] and now - self.overheat_said > 60:
            self.overheat_said = now
            out.append(("dmg_engine", "Motor sobrecalentado"))
        level = max(dents) if dents else 0
        self.state = {"level": level, "detached": self.detached, "flat": any(self.flat) or any(self.wheel_off),
                      "overheating": bool(d["overheating"])}
        return out
