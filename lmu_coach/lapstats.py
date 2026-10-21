"""Análisis por vuelta y por sesión: combustible/energía, estrategia, neumáticos, frenos,
consistencia, progreso y vuelta ideal. Todo sale de la telemetría que graba LMU."""
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

import duckdb
import numpy as np

from . import analysis
from .log import log

WHEELS = ("DI", "DD", "TI", "TD")         # delantera izq./dcha., trasera izq./dcha. (orden de LMU)
KPA_PER_PSI = 6.894757


# --------------------------------------------------------------------------- por vuelta

@dataclass
class LapStats:
    num: int
    time: float            # oficial si es válida, si no la duración
    valid: bool
    note: str
    fuel_used: float | None = None     # L
    ve_used: float | None = None       # % de energía virtual
    refuel: bool = False               # repostó o recargó durante la vuelta
    pressure: list = field(default_factory=list)   # kPa medias por rueda
    t_inner: list = field(default_factory=list)    # °C medias por rueda
    t_centre: list = field(default_factory=list)
    t_outer: list = field(default_factory=list)
    t_carcass: list = field(default_factory=list)
    brake_max: list = field(default_factory=list)  # °C máximos por rueda
    wear: list = field(default_factory=list)       # % gastado en la vuelta por rueda
    wear_left: list = field(default_factory=list)  # % de goma que queda al acabar la vuelta


def _at(ch, t):
    if ch is None:
        return None
    ts, v = ch
    if t < ts[0] or t > ts[-1]:
        return None
    return np.array([np.interp(t, ts, v[:, k]) for k in range(v.shape[1])])


def _mean_in(ch, a, b, reducer=np.mean):
    if ch is None:
        return []
    ts, v = ch
    m = (ts >= a) & (ts <= b)
    if not m.any():
        return []
    return [float(reducer(v[m, k])) for k in range(v.shape[1])]


def lap_stats(sd) -> list[LapStats]:
    """Estadísticas de cada vuelta completa de una SessionData."""
    fuel = sd.channel("Fuel Level")
    ve = sd.channel("Virtual Energy")
    press = sd.channel("TyresPressure")
    tl, tc, tr = sd.channel("TyresTempLeft"), sd.channel("TyresTempCentre"), sd.channel("TyresTempRight")
    carc = sd.channel("TyresCarcassTemp")
    brakes = sd.channel("Brakes Temp")
    wear = sd.channel("Tyres Wear")
    out = []
    for lap in sd.laps:
        if lap.note == "incompleta":
            continue
        a, b = lap.start, lap.end
        st = LapStats(lap.num, lap.time if lap.valid else lap.duration, lap.valid, lap.note)
        for ch, attr in ((fuel, "fuel_used"), (ve, "ve_used")):
            v0, v1 = _at(ch, a + 0.2), _at(ch, b - 0.2)
            if v0 is not None and v1 is not None:
                used = float(v0[0] - v1[0])
                ts, vals = ch
                m = (ts >= a) & (ts <= b)
                if (m.sum() > 2 and np.diff(vals[m, 0]).max() > 0.5) or used < -0.5:   # subió: repostaje
                    st.refuel = True
                setattr(st, attr, used)
        st.pressure = _mean_in(press, a, b)
        L, C, R = _mean_in(tl, a, b), _mean_in(tc, a, b), _mean_in(tr, a, b)
        if L and C and R:
            # en las ruedas izquierdas el lado interior es el derecho de la banda, y al revés
            st.t_inner = [R[0], L[1], R[2], L[3]]
            st.t_outer = [L[0], R[1], L[2], R[3]]
            st.t_centre = C
        st.t_carcass = _mean_in(carc, a, b)
        st.brake_max = _mean_in(brakes, a, b, np.max)
        w0, w1 = _at(wear, a + 0.2), _at(wear, b - 0.2)
        if w0 is not None and w1 is not None:
            st.wear = [float(x) for x in (w0 - w1)]
            st.wear_left = [float(x) for x in w1]
        out.append(st)
    return out


def tyre_hints(st: LapStats) -> list[str]:
    """Pistas clásicas de lectura de temperaturas (orientativas)."""
    hints = []
    if not (st.t_inner and st.t_centre and st.t_outer):
        return hints
    for k, name in enumerate(WHEELS):
        i, c, o = st.t_inner[k], st.t_centre[k], st.t_outer[k]
        edges = (i + o) / 2
        if c > edges + 4:
            hints.append(f"{name}: centro {c - edges:.0f} °C más caliente que los bordes → presión alta")
        elif c < edges - 4:
            hints.append(f"{name}: centro {edges - c:.0f} °C más frío que los bordes → presión baja")
        if i - o > 12:
            hints.append(f"{name}: interior {i - o:.0f} °C más caliente que el exterior → mucha caída (camber)")
        elif o > i + 2:
            hints.append(f"{name}: exterior más caliente que el interior → poca caída (camber)")
    if st.t_centre:
        f = (st.t_centre[0] + st.t_centre[1]) / 2
        r = (st.t_centre[2] + st.t_centre[3]) / 2
        if abs(f - r) > 10:
            hints.append(f"{'Delanteras' if f > r else 'Traseras'} {abs(f - r):.0f} °C más calientes que el otro eje")
    return hints


# --------------------------------------------------------------------------- consumos históricos

def session_consumption(path: str) -> list[tuple[float, float | None, float | None]]:
    """(tiempo de vuelta, combustible, energía) de cada vuelta completa sin repostaje ni boxes. Lectura ligera."""
    from .sessions import read_laps
    con = duckdb.connect(path, read_only=True)
    try:
        laps = read_laps(con)
        freqs = dict((n, f) for n, f, _ in con.execute("select * from channelsList").fetchall())
        t0 = con.execute('select value from "GPS Time" limit 1').fetchone()[0]
        chans = {}
        for name in ("Fuel Level", "Virtual Energy"):
            if name in freqs:
                v = con.execute(f'select value from "{name}"').fetchnumpy()["value"].astype(float)
                chans[name] = (t0 + np.arange(len(v)) / float(freqs[name]), v[:, None])
    finally:
        con.close()
    out = []
    for lap in laps:
        if lap.note in ("incompleta", "boxes / vuelta de salida"):
            continue
        row = [lap.time if lap.valid else lap.duration]
        ok = True
        for name in ("Fuel Level", "Virtual Energy"):
            ch = chans.get(name)
            v0, v1 = _at(ch, lap.start + 0.2), _at(ch, lap.end - 0.2)
            if v0 is None or v1 is None:
                row.append(None)
                continue
            ts, vals = ch
            m = (ts >= lap.start) & (ts <= lap.end)
            if m.sum() > 2 and np.diff(vals[m, 0]).max() > 0.5:
                ok = False
            used = float(v0[0] - v1[0])
            row.append(used if used > 0.01 else None)
        if ok and (row[1] or row[2]):
            out.append(tuple(row))
    return out


@dataclass
class Consumption:
    fuel: float | None      # L por vuelta (mediana)
    ve: float | None        # % por vuelta (mediana)
    laps: int
    sessions: int
    lap_time: float | None  # mediana de tiempos de esas vueltas
    tank: float | None      # mayor nivel de combustible visto (≈ depósito)


def history_consumption(infos: list, max_sessions=12) -> Consumption:
    """Consumo típico de un coche+circuito a partir de tus sesiones más recientes."""
    rows, used, tank = [], 0, None
    for info in sorted(infos, key=lambda s: s.mtime, reverse=True)[:max_sessions]:
        try:
            r = session_consumption(info.path)
        except (duckdb.Error, OSError):
            continue
        if r:
            rows += r
            used += 1
        try:
            con = duckdb.connect(info.path, read_only=True)
            mx = con.execute('select max(value) from "Fuel Level"').fetchone()[0]
            con.close()
            tank = max(tank or 0, mx or 0) or None
        except duckdb.Error:
            pass
    med = lambda xs: statistics.median(xs) if xs else None
    fuel = [r[1] for r in rows if r[1]]
    ve = [r[2] for r in rows if r[2]]
    return Consumption(med(fuel), med(ve), len(rows), used, med([r[0] for r in rows]), tank)


# --------------------------------------------------------------------------- estrategia

@dataclass
class Stint:
    laps: int
    fuel_start: float | None
    ve_start: float | None


@dataclass
class Plan:
    total_laps: int
    laps_per_stint: int
    limiter: str             # "combustible" o "energía"
    stops: int
    stints: list
    notes: list


def strategy(race_minutes: float, lap_time: float, fuel_per_lap: float | None, ve_per_lap: float | None,
             tank: float | None, ve_max: float = 100.0, reserve_laps: float = 0.5) -> Plan:
    """Plan de paradas: cuántas vueltas por relevo y cuánto cargar en cada uno."""
    total = math.ceil(race_minutes * 60 / lap_time) + 1            # +1: la vuelta en la que cae la bandera
    limits = []
    if fuel_per_lap and tank:
        limits.append((math.floor(tank / fuel_per_lap - reserve_laps), "combustible"))
    if ve_per_lap:
        limits.append((math.floor(ve_max / ve_per_lap - reserve_laps), "energía"))
    if not limits:
        return Plan(total, total, "-", 0, [Stint(total, None, None)], ["Sin datos de consumo para este coche y circuito"])
    per, limiter = min(limits)
    per = max(per, 1)
    stints = []
    left = total
    while left > 0:
        n = min(per, left)
        fuel = min(tank, (n + reserve_laps) * fuel_per_lap) if (fuel_per_lap and tank) else None
        ve = min(ve_max, (n + reserve_laps) * ve_per_lap) if ve_per_lap else None
        stints.append(Stint(n, fuel, ve))
        left -= n
    notes = []
    if len(stints) > 1:
        # repartir las vueltas para que los relevos sean parejos (y cargar menos en el último)
        even = math.ceil(total / len(stints))
        notes.append(f"Con {len(stints) - 1} parada(s) puedes hacer relevos de ~{even} vueltas")
    return Plan(total, per, limiter, len(stints) - 1, stints, notes)


# --------------------------------------------------------------------------- consistencia

@dataclass
class ZoneConsistency:
    idx: int
    start: float
    brake_sd: float          # m
    min_speed_sd: float      # km/h
    time_sd: float           # s
    mean_loss: float         # s respecto a la mejor vuelta
    n: int
    apex: float = 0.0        # m


def consistency(sd) -> tuple[list[ZoneConsistency], float | None, int]:
    """Variación frenada a frenada entre las vueltas válidas de la sesión (referencia: la mejor)."""
    valid = [l for l in sd.laps if l.valid]
    if len(valid) < 3:
        return [], None, len(valid)
    best = min(valid, key=lambda l: l.time)
    L = sd.track_len
    ref = analysis.by_distance(sd.lap_data(best.num), L)
    per = defaultdict(list)
    zones = {}
    for lap in valid:
        if lap.num == best.num:
            continue
        cur = analysis.by_distance(sd.lap_data(lap.num), L)
        dlt = analysis.delta(ref, cur)
        for z in analysis.compare_zones(ref, cur, dlt):
            per[z.zone.idx].append(z)
            zones[z.zone.idx] = z.zone
    out = []
    for idx, rs in sorted(per.items()):
        if len(rs) < 2:
            continue
        out.append(ZoneConsistency(idx, zones[idx].start,
                                   statistics.pstdev([r.brake_diff for r in rs]),
                                   statistics.pstdev([r.min_speed_diff for r in rs]),
                                   statistics.pstdev([r.time_diff for r in rs]),
                                   statistics.mean([r.time_diff for r in rs]), len(rs), apex=zones[idx].apex))
    lap_sd = statistics.pstdev([l.time for l in valid])
    return out, lap_sd, len(valid)


def brake_baseline(infos, max_sessions=6):
    """Temperaturas de freno habituales con este coche: {'front': (p10, p99), 'rear': (p10, p99)} o None."""
    fr, rr = [], []
    for info in sorted(infos, key=lambda i: -i.mtime)[:max_sessions]:
        try:
            con = duckdb.connect(info.path, read_only=True)
            try:
                row = con.execute('select quantile_cont(greatest(value1, value2), [0.1, 0.99]), '
                                  'quantile_cont(greatest(value3, value4), [0.1, 0.99]) from "Brakes Temp"').fetchone()
            finally:
                con.close()
        except Exception:
            log.warning("Temperaturas de freno: no se pudo leer %s", info.path, exc_info=True)
            continue
        if row and row[0] and row[1]:
            fr.append(row[0])
            rr.append(row[1])
    if not fr:
        return None
    med = lambda xs, k: statistics.median(x[k] for x in xs)
    return {"front": (med(fr, 0), med(fr, 1)), "rear": (med(rr, 0), med(rr, 1))}


# --------------------------------------------------------------------------- ritmo y relevos

FUEL_S_PER_L = 0.025      # cada litro menos hace el coche ~0,025 s/vuelta más rápido (aprox. 0,035 s/kg)
MISTAKE_S = 1.2           # vuelta «con error»: más lenta que la tendencia de su relevo en al menos esto
MIN_TREND_LAPS = 8        # vueltas limpias mínimas para hablar de degradación


@dataclass
class RunStint:
    idx: int
    laps: list                 # LapStats del relevo (sin vueltas de boxes)
    clean: list                # las que cuentan para el ritmo
    mistakes: list             # [(LapStats, segundos perdidos frente a la tendencia)]
    avg: float | None
    best: float | None
    slope: float | None        # s/vuelta (positivo: cada vuelta más lento)
    slope_fuel: float | None   # descontando lo que ayuda quemar combustible: ≈ degradación de neumáticos
    first_last: float | None   # media de las 3 últimas − media de las 3 primeras (vueltas limpias)
    fuel_per_lap: float | None
    wear_per_lap: list         # %/vuelta por rueda
    wear_left: list            # % que queda al final del relevo
    trend: tuple | None        # (a, b) con tiempo ≈ a + b·nº de vuelta


def _is_pit(st: LapStats) -> bool:
    return ("boxes" in st.note or st.refuel or (st.fuel_used is not None and st.fuel_used < -0.5)
            or any(w < -0.5 for w in st.wear))


def _theil_sen(x, y):
    """Pendiente robusta (mediana de las pendientes entre pares) y ordenada."""
    sl = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(len(x)) for j in range(i + 1, len(x)) if x[j] != x[i]]
    if not sl:
        return None
    b = statistics.median(sl)
    a = statistics.median(yi - b * xi for xi, yi in zip(x, y))
    return a, b


def stints(stats: list[LapStats]) -> list[RunStint]:
    """Parte la sesión en relevos (entre paradas) y calcula ritmo, degradación, errores y desgaste."""
    groups, cur = [], []
    for st in stats:
        if _is_pit(st):
            if cur:
                groups.append(cur)
            cur = []
        elif st.time > 0:
            cur.append(st)
    if cur:
        groups.append(cur)
    out = []
    for gi, laps in enumerate(g for g in groups if len(g) >= 3):
        times = [l.time for l in laps]
        med = statistics.median(times)
        # fuera lo que no es ritmo (trompos, banderas, vueltas a medio gas): más de 5 s sobre la mediana
        pace = [l for l in laps if l.time < med + 5]
        trend = _theil_sen([l.num for l in pace], [l.time for l in pace]) if len(pace) >= 3 else None
        mistakes, clean = [], []
        for l in pace:
            exp = trend[0] + trend[1] * l.num if trend else med
            (mistakes.append((l, l.time - exp)) if l.time - exp > MISTAKE_S else clean.append(l))
        mistakes += [(l, l.time - med) for l in laps if l not in pace]
        mistakes.sort(key=lambda m: m[0].num)
        fuel = [l.fuel_used for l in laps if l.fuel_used and l.fuel_used > 0]
        fpl = statistics.median(fuel) if fuel else None
        slope = trend[1] if trend and len(clean) >= MIN_TREND_LAPS else None
        ct = [l.time for l in clean]
        wear = [l.wear for l in laps if l.wear and all(0 <= w < 5 for w in l.wear)]
        out.append(RunStint(
            idx=gi + 1, laps=laps, clean=clean, mistakes=mistakes,
            avg=statistics.mean(ct) if ct else None, best=min(ct) if ct else None,
            slope=slope, slope_fuel=(slope + fpl * FUEL_S_PER_L) if slope is not None and fpl else None,
            first_last=(statistics.mean(ct[-3:]) - statistics.mean(ct[:3])) if len(ct) >= 6 else None,
            fuel_per_lap=fpl,
            wear_per_lap=[statistics.median(w[k] for w in wear) for k in range(4)] if wear else [],
            wear_left=next((l.wear_left for l in reversed(laps) if l.wear_left), []),
            trend=trend))
    return out


def stint_summary(sts: list[RunStint]) -> list[str]:
    """Una frase por relevo para el resumen de la pestaña."""
    out = []
    for s in sts:
        parts = []
        if s.slope is not None and s.slope_fuel is not None:
            deg = s.slope_fuel
            if deg > 0.08:
                parts.append(f"pierdes ~{deg:.2f} s/vuelta por los neumáticos: cuídalos más "
                             "(menos deslizamiento a la salida de las curvas)")
            elif deg > 0.03:
                parts.append(f"degradación moderada (~{deg:.2f} s/vuelta descontando el combustible)")
            elif s.slope < -0.05:
                parts.append(f"vas cada vez más rápido ({s.slope:+.2f} s/vuelta): te cuestan las primeras vueltas")
            else:
                parts.append("los neumáticos aguantan bien")
        if s.mistakes:
            parts.append(f"{len(s.mistakes)} vuelta(s) con error ({sum(m[1] for m in s.mistakes):.1f} s perdidos)")
        if s.wear_per_lap:
            f = (s.wear_per_lap[0] + s.wear_per_lap[1]) / 2
            r = (s.wear_per_lap[2] + s.wear_per_lap[3]) / 2
            if max(f, r) > 0 and abs(f - r) / max(f, r) > 0.3:
                parts.append(f"gastas bastante más las {'delanteras' if f > r else 'traseras'} "
                             f"({max(f, r):.2f} frente a {min(f, r):.2f} %/vuelta)")
        if parts:
            out.append(f"Relevo {s.idx}: " + "; ".join(parts) + ".")
    return out


# --------------------------------------------------------------------------- progreso y vuelta ideal

def own_sessions(index_sessions, track, car):
    return [s for s in index_sessions if not s.imported and not s.error and s.track == track and s.car == car]


def progress(infos) -> list[dict]:
    """Por día: mejor vuelta, mediana de vueltas válidas y nº de vueltas."""
    days = defaultdict(list)
    for s in infos:
        day = s.recorded[:10]
        days[day] += [lap[1] for lap in s.lap_list if lap[2]]
    out = []
    for day in sorted(days):
        t = days[day]
        if t:
            out.append({"day": day, "best": min(t), "median": statistics.median(t), "laps": len(t)})
    return out


@dataclass
class IdealSector:
    time: float
    session: str     # fecha
    lap: int


def ideal_lap(infos):
    """Vuelta ideal con tus mejores sectores de todas las sesiones (y la mejor vuelta real)."""
    best = [None, None, None]
    best_real = None
    for s in infos:
        for num, t, ok, s1, s2, s3, _ in s.lap_list:
            if not ok:
                continue
            if best_real is None or t < best_real[0]:
                best_real = (t, s.recorded, num)
            for k, v in enumerate((s1, s2, s3)):
                if v > 0 and (best[k] is None or v < best[k].time):
                    best[k] = IdealSector(v, s.recorded, num)
    if any(b is None for b in best):
        return None, best_real
    return best, best_real


@dataclass
class ComboStats:
    """Tu historial con un coche en un circuito (para «Mi progreso»)."""
    track: str
    car: str
    car_class: str
    sessions: int
    laps: int              # vueltas válidas
    best: float
    best_day: str
    first_best: float      # mejor vuelta del primer día que corriste ahí
    ideal: float | None    # suma de tus mejores sectores
    first_day: str
    last_day: str
    days: int              # días distintos
    last_week_gain: float | None   # cuánto has bajado tu récord en los últimos 7 días de actividad
    infos: list = field(default_factory=list, repr=False)
    layout: str = ""       # trazado (Silverstone WEC / ELMS); igual que el circuito si solo hay uno

    @property
    def gained(self) -> float:
        return self.first_best - self.best


def overview(index_sessions) -> list[ComboStats]:
    """Un resumen por circuito y coche con tus sesiones (las importadas no cuentan). Lo último primero."""
    combos = defaultdict(list)
    for s in index_sessions:
        if not s.imported and not s.error and s.best:
            combos[(s.track, s.layout or s.track, s.car)].append(s)
    out = []
    for (track, layout, car), infos in combos.items():
        days = progress(infos)
        if not days:
            continue
        laps = sum(d["laps"] for d in days)
        best_d = min(days, key=lambda d: d["best"])
        sectors, _ = ideal_lap(infos)
        ideal = sum(x.time for x in sectors) if sectors else None
        # los últimos 7 días con actividad frente a todo lo anterior
        gain = None
        if len(days) > 1:
            n_recent = min(7, len(days) - 1)
            before, recent = days[:-n_recent], days[-n_recent:]
            gain = max(0.0, min(d["best"] for d in before) - min(d["best"] for d in recent))
        out.append(ComboStats(track, car, infos[0].car_class, len(infos), laps, best_d["best"], best_d["day"],
                              days[0]["best"], ideal, days[0]["day"], days[-1]["day"], len(days), gain, infos,
                              layout))
    out.sort(key=lambda c: c.last_day, reverse=True)
    return out


# --------------------------------------------------------------------------- ranking con otros pilotos

@dataclass
class RankRow:
    driver: str
    mine: bool
    best: float
    best_car: str
    best_date: str
    sectors: list            # mejores S1, S2, S3 (de cualquier vuelta válida)
    ideal: float | None
    laps: int                # vueltas válidas


def ranking(sessions, track: str, layout: str, car_class: str) -> list[RankRow]:
    """Tú y los pilotos de las sesiones importadas en ese circuito y clase, del más rápido al más lento."""
    per = {}
    for s in sessions:
        if s.error or s.track != track or s.layout != layout or s.car_class != car_class:
            continue
        who = (s.driver or "Importado") if s.imported else "__yo__"
        r = per.setdefault(who, RankRow(s.driver or "Tú" if not s.imported else (s.driver or "Importado"),
                                        not s.imported, 0.0, "", "", [0.0, 0.0, 0.0], None, 0))
        for num, t, ok, s1, s2, s3, _ in s.lap_list:
            if not ok or t <= 0:
                continue
            r.laps += 1
            if not r.best or t < r.best:
                r.best, r.best_car, r.best_date = t, s.car, s.recorded
            for k, v in enumerate((s1, s2, s3)):
                if v > 0 and (not r.sectors[k] or v < r.sectors[k]):
                    r.sectors[k] = v
    rows = [r for r in per.values() if r.best]
    for r in rows:
        r.ideal = sum(r.sectors) if all(r.sectors) else None
    return sorted(rows, key=lambda r: r.best)


def ranking_groups(sessions) -> list[tuple[str, str, str, int, bool]]:
    """(circuito, trazado, clase, nº de pilotos, hay importadas) con vueltas válidas, los compartidos primero."""
    groups = defaultdict(lambda: [set(), False])
    for s in sessions:
        if s.error or not s.best:
            continue
        g = groups[(s.track, s.layout, s.car_class)]
        g[0].add((s.driver or "Importado") if s.imported else "__yo__")
        g[1] |= s.imported
    out = [(t, l, c, len(d), imp) for (t, l, c), (d, imp) in groups.items()]
    return sorted(out, key=lambda g: (-g[3], g[0], g[2]))


# --------------------------------------------------------------------------- reglaje

_CAT = {
    "Electrónica": ["VM_TRACTION_CONTROL", "VM_TRACTIONCONTROLMAP", "VM_TRACTIONCONTROLPOWERCUTMAP",
                    "VM_TRACTIONCONTROLSLIPANGLEMAP", "VM_ANTILOCK_BRAKES", "VM_ANTILOCKBRAKESYSTEMMAP",
                    "VM_ENGINE_BRAKEMAP", "VM_ENGINE_MIXTURE", "VM_ENGINE_BOOST", "VM_ELECTRIC_MOTOR_MAP",
                    "VM_REGEN_LEVEL", "VM_REV_LIMITER"],
    "Frenos": ["VM_BRAKE_BALANCE", "VM_BRAKE_MIGRATION", "VM_BRAKE_PRESSURE", "VM_BRAKE_DUCTS",
               "VM_BRAKE_DUCTS_REAR", "WM_BRAKEDISC", "WM_BRAKEPAD"],
    "Aerodinámica": ["VM_FRONT_WING", "VM_REAR_WING", "VM_WATER_RADIATOR", "VM_OIL_RADIATOR",
                     "VM_LEFT_FENDER_FLARE", "VM_RIGHT_FENDER_FLARE"],
    "Neumáticos": ["WM_PRESSURE", "WM_COMPOUND", "VM_FRONT_TIRE_COMPOUND", "VM_REAR_TIRE_COMPOUND", "WM_CAMBER",
                   "VM_FRONT_TOEIN", "VM_REAR_TOEIN", "VM_LEFT_CASTER", "VM_RIGHT_CASTER"],
    "Suspensión": ["WM_RIDEHEIGHT", "WM_SPRING", "WM_PACKERS", "WM_SLOWBUMP", "WM_FASTBUMP", "WM_SLOWREBOUND",
                   "WM_FASTREBOUND", "VM_FRONT_ANTISWAY", "VM_REAR_ANTISWAY", "VM_FRONT_3RD_SPRING",
                   "VM_REAR_3RD_SPRING", "VM_FRONT_3RD_PACKERS", "VM_REAR_3RD_PACKERS"],
    "Diferencial": ["VM_DIFF_PRELOAD", "VM_DIFF_POWER", "VM_DIFF_COAST", "VM_DIFF_PUMP"],
    "Combustible y estrategia": ["VM_FUEL_LEVEL", "VM_VIRTUAL_ENERGY", "VM_FUEL_CAPACITY", "VM_NUM_PITSTOPS"],
    "Caja de cambios": ["VM_GEAR_FINAL", "VM_RATIO_SET", "VM_GEAR_1", "VM_GEAR_2", "VM_GEAR_3", "VM_GEAR_4",
                        "VM_GEAR_5", "VM_GEAR_6"],
    "Dirección": ["VM_STEER_LOCK"],
}
_NAMES = {
    "VM_TRACTION_CONTROL": "Control de tracción", "VM_TRACTIONCONTROLMAP": "TC (mapa)",
    "VM_TRACTIONCONTROLPOWERCUTMAP": "TC corte de potencia", "VM_TRACTIONCONTROLSLIPANGLEMAP": "TC deslizamiento",
    "VM_ANTILOCK_BRAKES": "ABS", "VM_ANTILOCKBRAKESYSTEMMAP": "ABS (mapa)", "VM_ENGINE_BRAKEMAP": "Freno motor",
    "VM_ENGINE_MIXTURE": "Mapa motor", "VM_ENGINE_BOOST": "Boost", "VM_ELECTRIC_MOTOR_MAP": "Mapa motor eléctrico",
    "VM_REGEN_LEVEL": "Regeneración", "VM_REV_LIMITER": "Limitador de vueltas",
    "VM_BRAKE_BALANCE": "Reparto de frenada (del:tras)", "VM_BRAKE_MIGRATION": "Migración de frenada",
    "VM_BRAKE_PRESSURE": "Presión máxima del pedal", "VM_BRAKE_DUCTS": "Tomas de freno delanteras",
    "VM_BRAKE_DUCTS_REAR": "Tomas de freno traseras", "WM_BRAKEDISC": "Disco de freno", "WM_BRAKEPAD": "Pastilla",
    "VM_FRONT_WING": "Alerón delantero", "VM_REAR_WING": "Alerón trasero", "VM_WATER_RADIATOR": "Radiador de agua",
    "VM_OIL_RADIATOR": "Radiador de aceite", "VM_LEFT_FENDER_FLARE": "Dive plane izq.",
    "VM_RIGHT_FENDER_FLARE": "Dive plane dcho.", "WM_PRESSURE": "Presión en frío", "WM_COMPOUND": "Compuesto",
    "VM_FRONT_TIRE_COMPOUND": "Compuesto delantero", "VM_REAR_TIRE_COMPOUND": "Compuesto trasero",
    "WM_CAMBER": "Caída (camber)", "VM_FRONT_TOEIN": "Convergencia delantera", "VM_REAR_TOEIN": "Convergencia trasera",
    "VM_LEFT_CASTER": "Avance izq.", "VM_RIGHT_CASTER": "Avance dcho.", "WM_RIDEHEIGHT": "Altura",
    "WM_SPRING": "Muelle", "WM_PACKERS": "Topes (packers)", "WM_SLOWBUMP": "Compresión lenta",
    "WM_FASTBUMP": "Compresión rápida", "WM_SLOWREBOUND": "Extensión lenta", "WM_FASTREBOUND": "Extensión rápida",
    "VM_FRONT_ANTISWAY": "Barra estabilizadora del.", "VM_REAR_ANTISWAY": "Barra estabilizadora tras.",
    "VM_FRONT_3RD_SPRING": "3er muelle del.", "VM_REAR_3RD_SPRING": "3er muelle tras.",
    "VM_FRONT_3RD_PACKERS": "3er elemento topes del.", "VM_REAR_3RD_PACKERS": "3er elemento topes tras.",
    "VM_DIFF_PRELOAD": "Precarga del diferencial", "VM_DIFF_POWER": "Diferencial en tracción",
    "VM_DIFF_COAST": "Diferencial en retención", "VM_DIFF_PUMP": "Diferencial (pump)",
    "VM_FUEL_LEVEL": "Combustible inicial", "VM_VIRTUAL_ENERGY": "Energía virtual inicial",
    "VM_FUEL_CAPACITY": "Capacidad del depósito", "VM_NUM_PITSTOPS": "Paradas previstas",
    "VM_GEAR_FINAL": "Grupo final", "VM_RATIO_SET": "Juego de relaciones", "VM_STEER_LOCK": "Giro del volante",
}
_WHEEL_SUFFIX = {"FL": "DI", "FR": "DD", "RL": "TI", "RR": "TD"}


def setup_label(key: str) -> tuple[str, str, int]:
    """(categoría, nombre en español, orden) de un parámetro del reglaje."""
    import re
    m = re.match(r"(.+?)[-_](?:W_)?(FL|FR|RL|RR)$", key)
    base, wheel = (m.group(1), m.group(2)) if m else (key, None)
    for order, (cat, keys) in enumerate(_CAT.items()):
        if base in keys:
            name = _NAMES.get(base, base)
            if base.startswith("VM_GEAR_") and base[-1].isdigit():
                name = f"Relación {base[-1]}ª"
            return cat, name + (f" ({_WHEEL_SUFFIX[wheel]})" if wheel else ""), order * 1000 + keys.index(base)
    pretty = base.replace("VM_", "").replace("WM_", "").replace("_", " ").capitalize()
    return "Otros", pretty + (f" ({_WHEEL_SUFFIX[wheel]})" if wheel else ""), 99000


def setup_rows(a: dict, b: dict | None):
    """Filas (categoría, nombre, valor A, valor B, distinto) ordenadas; sin parámetros N/A."""
    rows = []
    for key in set(a) | set(b or {}):
        if key == "gearGraph":
            continue
        va = a.get(key, ("", ""))[1]
        vb = (b or {}).get(key, ("", ""))[1] if b is not None else ""
        if va in ("N/A", "") and vb in ("N/A", ""):
            continue
        cat, name, order = setup_label(key)
        rows.append((order, cat, name, va, vb, b is not None and va != vb))
    rows.sort(key=lambda r: (r[0], r[2]))
    return [r[1:] for r in rows]


def read_setup_file(path: str) -> dict:
    """Reglaje de una sesión sin cargar su telemetría (solo metadatos)."""
    import json
    con = duckdb.connect(path, read_only=True)
    try:
        raw = dict(con.execute("select key, value from metadata").fetchall()).get("CarSetup", "")
    finally:
        con.close()
    out = {}
    try:
        for k, v in json.loads(raw).items():
            if isinstance(v, dict) and v.get("available", True):
                out[k] = (v.get("caption") or k, str(v.get("stringValue", v.get("value", ""))).strip())
    except (ValueError, TypeError):
        pass
    return out
