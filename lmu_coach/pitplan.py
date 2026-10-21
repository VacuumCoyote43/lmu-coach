"""Estrategia en directo: con tu consumo real y lo que queda de carrera, cuándo parar y cuánto repostar.

Cuenta en vueltas desde la próxima vez que cruces meta: «para en 0» = entra en boxes al acabar esta vuelta.
"""
import math
from dataclasses import dataclass

MARGIN_LAPS = 0.35      # reserva para no quedarse seco (vuelta de entrada más lenta, consumo que sube…)


@dataclass
class LivePlan:
    laps_needed: float           # vueltas que te quedan por correr (desde ahora)
    range_laps: float            # vueltas que te dan el combustible / la energía que llevas
    limit: str                   # "fuel" o "ve": qué se acaba antes
    stop_in: int | None          # paradas: vueltas completas que puedes dar antes de entrar (None: llegas)
    add_fuel: float | None = None    # litros a repostar en esa parada
    ve_target: float | None = None   # % de energía con el que salir

    @property
    def makes_it(self) -> bool:
        return self.stop_in is None


def remaining_laps(time_left: float | None, laps_left: int | None, lap_t: float, lap_frac: float) -> float | None:
    """Vueltas que te quedan (con decimales, desde donde estás). En carreras por tiempo, la vuelta en la que
    se acaba el tiempo se termina entera."""
    if laps_left is not None:
        return max(0.0, laps_left - lap_frac)
    if time_left is not None and lap_t > 0:
        to_line = 1 - lap_frac
        after = max(0.0, time_left - to_line * lap_t)
        return to_line + math.ceil(after / lap_t)
    return None


def plan(laps_needed: float, lap_frac: float, fuel: float | None, fuel_pl: float | None, ve: float | None,
         ve_pl: float | None, capacity: float | None = None) -> LivePlan | None:
    ranges = {}
    if fuel is not None and fuel_pl and fuel_pl > 0:
        ranges["fuel"] = fuel / fuel_pl
    if ve is not None and ve_pl and ve_pl > 0:
        ranges["ve"] = ve / ve_pl
    if not ranges or laps_needed is None:
        return None
    limit = min(ranges, key=ranges.get)
    rng = ranges[limit]
    if rng >= laps_needed + MARGIN_LAPS:
        return LivePlan(laps_needed, rng, limit, None)
    # vueltas completas que aún puedes dar después de cruzar meta (con la reserva)
    after_line = rng - (1 - lap_frac)
    stop_in = max(0, math.floor(after_line - MARGIN_LAPS))
    left_after_stop = laps_needed - (1 - lap_frac) - stop_in      # vueltas que faltan al salir de boxes
    add_fuel = ve_target = None
    if fuel is not None and fuel_pl:
        in_tank = max(0.0, fuel - ((1 - lap_frac) + stop_in) * fuel_pl)
        add_fuel = max(0.0, (left_after_stop + MARGIN_LAPS) * fuel_pl - in_tank)
        if capacity:
            add_fuel = min(add_fuel, max(0.0, capacity - in_tank))
    if ve is not None and ve_pl:
        ve_target = min(100.0, (left_after_stop + MARGIN_LAPS) * ve_pl)
    return LivePlan(laps_needed, rng, limit, stop_in, add_fuel, ve_target)


def spoken(p: LivePlan, rejoin: int | None = None) -> str:
    from .speech import number_es
    if p.makes_it:
        return "Con este consumo llegas al final"
    when = ("Entra en boxes al acabar esta vuelta" if p.stop_in == 0 else
            "Para en la próxima vuelta" if p.stop_in == 1 else f"Para en {number_es(p.stop_in)} vueltas")
    parts = [when]
    if p.add_fuel:
        parts.append(f"reposta {number_es(int(math.ceil(p.add_fuel)))} litros")
    if p.ve_target is not None:
        parts.append(f"energía al {number_es(int(math.ceil(p.ve_target)))} por ciento")
    txt = ", ".join(parts)
    if rejoin:
        txt += f". Volverías {_ordinal(rejoin)}"
    return txt


_ORD = ["", "primero", "segundo", "tercero", "cuarto", "quinto", "sexto", "séptimo", "octavo", "noveno",
        "décimo"]


def _ordinal(n: int) -> str:
    from .speech import number_es
    return _ORD[n] if 0 < n < len(_ORD) else f"en la posición {number_es(n)}"
