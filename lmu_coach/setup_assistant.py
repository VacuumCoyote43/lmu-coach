"""Asistente de reglaje: diagnóstico a partir de la telemetría y sugerencias direccionales.

Las sugerencias son orientativas (no hay modelo físico del coche): dicen hacia dónde mover cada
ajuste y por qué, con el dato que lo justifica. Hay que probarlas en pista.
"""
import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from . import analysis, lapstats

WHEELBASE = 2.7          # m (aprox. GT3/LMDh; solo afecta a la escala, no a la comparación entre fases)
MIN_LAT_G = 0.5          # solo se mide el equilibrio en apoyo
THRESH = 0.45            # º de volante «de más» o «de menos» para considerar una fase desequilibrada


# --------------------------------------------------------------------------- medidas por vuelta

def _steer_lock_deg(setup: dict) -> float:
    """Giro máximo de la rueda delantera: 'VM_STEER_LOCK' = '476 (17.2) deg' → 17.2."""
    v = setup.get("VM_STEER_LOCK", ("", ""))[1]
    m = re.search(r"\(([\d.]+)\)", v)
    return float(m.group(1)) if m else 17.0


def _smooth(a, n):
    if n <= 1:
        return a
    k = np.ones(n) / n
    pad = np.concatenate([np.full(n, a[0]), a, np.full(n, a[-1])])
    return np.convolve(pad, k, mode="same")[n:-n]


@dataclass
class LapBalance:
    lat_g: np.ndarray        # aceleración lateral (g, con signo) calculada de la trayectoria
    us_deg: np.ndarray       # volante «de más» (º de rueda): >0 subviraje, <0 sobreviraje
    counter: np.ndarray      # contravolante (bool)
    d: np.ndarray
    kappa: np.ndarray        # curvatura (1/m)


def lap_balance(data: dict, lock_deg: float) -> LapBalance:
    """Equilibrio a lo largo de la vuelta. data: SessionData.lap_data (50 Hz).
    La aceleración lateral se calcula con la trayectoria (v²·curvatura): el canal «G Force Lat» de LMU
    no es fiable."""
    x, y = _smooth(data["x"], 15), _smooth(data["y"], 15)
    dx, dy = np.gradient(x), np.gradient(y)
    ddx, ddy = np.gradient(dx), np.gradient(dy)
    kappa = (dx * ddy - dy * ddx) / np.maximum((dx * dx + dy * dy) ** 1.5, 1e-6)
    kappa = _smooth(kappa, 15)
    v = data["v"] / 3.6
    lat = v * v * kappa / 9.81
    steer = _smooth(data["steer"], 5)
    sign = -1.0 if np.corrcoef(steer, kappa)[0, 1] < 0 else 1.0
    delta = sign * steer * math.radians(lock_deg)
    kin = WHEELBASE * kappa
    us = np.degrees(np.abs(delta) - np.abs(kin))
    counter = (np.sign(delta) != np.sign(kin)) & (np.abs(lat) > MIN_LAT_G) & (np.abs(np.degrees(delta)) > 0.8)
    return LapBalance(lat, us, counter, data["d"], kappa)


@dataclass
class Slip:
    front_lock: float = 0.0   # fracción de la frenada fuerte con una delantera bloqueando (coches sin ABS)
    rear_lock: float = 0.0
    rear_spin: float = 0.0    # fracción del tiempo acelerando con patinada trasera clara
    front_slip: float = 0.0   # deslizamiento típico en frenada fuerte (p5; negativo = la rueda frena más)
    rear_slip: float = 0.0
    abs_active: float | None = None   # fracción de la frenada fuerte con ABS actuando
    tc_active: float | None = None    # fracción del tiempo acelerando con TC actuando
    braking_samples: int = 0
    traction_samples: int = 0


def lap_slip(sd, lap, data) -> Slip:
    out = Slip()
    ws = sd.channel("Wheel Speed")             # m/s de cada rueda
    t = data["t"] + lap.start
    brake = (data["brk"] > 0.3) & (data["v"] > 60)
    trac = (data["thr"] > 0.7) & (data["v"] > 40) & (data["v"] < 220)
    out.braking_samples = int(brake.sum())
    out.traction_samples = int(trac.sum())
    if ws is not None:
        w = np.stack([np.interp(t, ws[0], np.abs(ws[1][:, k])) for k in range(4)], 1)
        v = np.maximum(data["v"] / 3.6, 1.0)
        slip = w / v[:, None] - 1.0
        if out.braking_samples:
            out.front_lock = float((slip[brake, :2].min(1) < -0.10).mean())
            out.rear_lock = float((slip[brake, 2:].min(1) < -0.10).mean())
            out.front_slip = float(np.percentile(slip[brake, :2].min(1), 5))
            out.rear_slip = float(np.percentile(slip[brake, 2:].min(1), 5))
        if out.traction_samples:
            out.rear_spin = float((slip[trac, 2:].max(1) > 0.08).mean())
    if out.braking_samples:
        abs_on = sd.event_state("ABS", t)
        if abs_on is not None:
            out.abs_active = float(abs_on[brake].mean())
    if out.traction_samples:
        tc = sd.channel("TC")
        if tc is not None:
            out.tc_active = float((np.interp(t, tc[0], tc[1][:, 0]) > 0.5)[trac].mean())
    return out


def _merge_slips(slips) -> Slip:
    s = Slip()
    bs = sum(x.braking_samples for x in slips)
    ts = sum(x.traction_samples for x in slips)
    wavg = lambda attr, items, weight: (sum(getattr(x, attr) * getattr(x, weight) for x in items) /
                                        max(sum(getattr(x, weight) for x in items), 1))
    if bs:
        for a in ("front_lock", "rear_lock", "front_slip", "rear_slip"):
            setattr(s, a, wavg(a, slips, "braking_samples"))
        ab = [x for x in slips if x.abs_active is not None and x.braking_samples]
        if ab:
            s.abs_active = wavg("abs_active", ab, "braking_samples")
    if ts:
        s.rear_spin = wavg("rear_spin", slips, "traction_samples")
        tcs = [x for x in slips if x.tc_active is not None and x.traction_samples]
        if tcs:
            s.tc_active = wavg("tc_active", tcs, "traction_samples")
    s.braking_samples, s.traction_samples = bs, ts
    return s


# --------------------------------------------------------------------------- análisis de sesión

@dataclass
class ZoneBalance:
    idx: int
    start: float
    entry: float | None      # volante de más (+) o de menos (−) respecto a la curva propia del coche
    mid: float | None
    exit: float | None
    counter: int             # nº de vueltas con contravolante en la zona
    laps: int
    apex: float = 0.0        # m


@dataclass
class Suggestion:
    priority: int            # 1 alta, 2 media, 3 baja
    area: str
    title: str
    evidence: str
    changes: list            # [(parámetro, ajuste)]


@dataclass
class Report:
    zones: list = field(default_factory=list)
    gradient: float | None = None     # º de volante extra por cada g lateral (subviraje «natural» del coche)
    slip: Slip | None = None
    suggestions: list = field(default_factory=list)
    laps_used: int = 0


def analyze(sd, own_infos=None) -> Report:
    rep = Report()
    laps = [l for l in sd.laps if l.valid]
    if len(laps) < 2:
        laps = [l for l in sd.laps if l.note not in ("incompleta", "boxes / vuelta de salida")]
    if not laps:
        return rep
    rep.laps_used = len(laps)
    setup = sd.setup()
    lock = _steer_lock_deg(setup)
    best = min(laps, key=lambda l: l.time if l.valid else l.duration)
    ref = analysis.by_distance(sd.lap_data(best.num), sd.track_len)
    zones = analysis.detect_brake_zones({"d": ref["d"], "v": ref["v"], "thr": ref["thr"], "brk": ref["brk"]})

    balances, slips = [], []
    for lap in laps:
        data = sd.lap_data(lap.num)
        balances.append(lap_balance(data, lock))
        slips.append(lap_slip(sd, lap, data))
    rep.slip = _merge_slips(slips)

    # Calibración propia del coche en esta sesión: volante «esperado» = a + b·|g| + c·|κ|.
    # Absorbe lo que no conocemos (batalla, desmultiplicación real de la dirección) y el subviraje
    # natural con la carga; lo que queda en cada fase es el desequilibrio real de esa fase.
    rows = [(np.abs(b.lat_g), np.abs(b.kappa), b.us_deg, np.abs(b.lat_g) > MIN_LAT_G) for b in balances]
    G = np.concatenate([g[m] for g, _, _, m in rows])
    K = np.concatenate([k[m] for _, k, _, m in rows])
    U = np.concatenate([u[m] for _, _, u, m in rows])
    if len(G) < 50:
        rep.suggestions = _suggest(rep, sd, laps, setup, own_infos or [])
        return rep
    A = np.stack([np.ones_like(G), G, K], 1)
    coef, *_ = np.linalg.lstsq(A, U, rcond=None)
    # una pasada robusta: quitar el 10 % de muestras más alejadas y reajustar
    res = U - A @ coef
    keep = np.abs(res) < np.percentile(np.abs(res), 90)
    coef, *_ = np.linalg.lstsq(A[keep], U[keep], rcond=None)
    rep.gradient = float(coef[1])
    expected = lambda b: coef[0] + coef[1] * np.abs(b.lat_g) + coef[2] * np.abs(b.kappa)

    phase_vals = defaultdict(list)
    counters = defaultdict(int)
    for b in balances:
        loaded = np.abs(b.lat_g) > MIN_LAT_G
        resid = b.us_deg - expected(b)
        for z in zones:
            ex = max(z.full_throttle, z.apex + 60)
            phases = {"entry": (b.d >= z.start) & (b.d < z.apex - 10),
                      "mid": (b.d >= z.apex - 10) & (b.d <= z.apex + 10),
                      "exit": (b.d > z.apex + 10) & (b.d <= ex)}
            for ph, m in phases.items():
                m = m & loaded
                if m.sum() >= 5:
                    phase_vals[(z.idx, ph)].append(float(np.median(resid[m])))
            if (b.counter & (b.d >= z.start) & (b.d <= ex)).sum() >= 5:
                counters[z.idx] += 1
    for z in zones:
        dev = lambda ph: statistics.median(phase_vals[(z.idx, ph)]) if phase_vals.get((z.idx, ph)) else None
        rep.zones.append(ZoneBalance(z.idx, z.start, dev("entry"), dev("mid"), dev("exit"), counters[z.idx], len(laps),
                                     apex=z.apex))

    rep.suggestions = _suggest(rep, sd, laps, setup, own_infos or [])
    rep.suggestions.sort(key=lambda x: x.priority)
    return rep


# --------------------------------------------------------------------------- reglas

def _fz(zs):
    return ", ".join(f"F{z.idx}" for z in zs)


BALANCE_RULES = [
    ("entry", +1, "Subviraje al entrar en las curvas",
     [("Reparto de frenada", "0,5–1 % más atrás"), ("Freno motor", "+1 (más retención)"),
      ("Diferencial en retención", "menos bloqueo"), ("Barra estabilizadora del.", "un punto más blanda")]),
    ("entry", -1, "Sobreviraje al entrar en las curvas (la trasera se va al frenar)",
     [("Reparto de frenada", "0,5–1 % más adelante"), ("Freno motor", "-1 (menos retención)"),
      ("Diferencial en retención", "más bloqueo")]),
    ("mid", +1, "Subviraje en el vértice",
     [("Barra estabilizadora del.", "un punto más blanda"), ("Barra estabilizadora tras.", "un punto más dura"),
      ("Alerón trasero", "un punto menos (o el delantero uno más)")]),
    ("mid", -1, "Sobreviraje en el vértice",
     [("Barra estabilizadora tras.", "un punto más blanda"), ("Alerón trasero", "un punto más")]),
    ("exit", +1, "Subviraje a la salida (al acelerar se abre)",
     [("Diferencial en tracción", "menos bloqueo"), ("Barra estabilizadora tras.", "un punto más dura")]),
    ("exit", -1, "Sobreviraje a la salida (la trasera se va al acelerar)",
     [("Control de tracción", "+1"), ("Barra estabilizadora tras.", "un punto más blanda"),
      ("Diferencial en tracción", "más bloqueo si se va de golpe")]),
]


def _suggest(rep: Report, sd, laps, setup, own_infos) -> list:
    sug = []
    measured = [z for z in rep.zones if any(v is not None for v in (z.entry, z.mid, z.exit))]
    n = len(measured)
    need = max(2, math.ceil(n / 3))
    for phase, sign, title, changes in BALANCE_RULES:
        zs = [z for z in measured if getattr(z, phase) is not None and sign * getattr(z, phase) > THRESH]
        if len(zs) >= need:
            prio = 1 if len(zs) >= max(3, n // 2) else 2
            how = "más volante del que pide la curva" if sign > 0 else "menos volante del que pide la curva"
            sug.append(Suggestion(prio, "Equilibrio", title,
                                  f"En {len(zs)} de {n} curvas ({_fz(zs)}) llevas {how}, comparado con lo que hace "
                                  "tu coche a la misma carga lateral en el resto de la vuelta.", changes))
    spins = [z for z in rep.zones if z.counter >= max(2, math.ceil(z.laps / 3))]
    if spins:
        sug.append(Suggestion(1, "Equilibrio", "Contravolantes repetidos",
                              f"Corriges con contravolante en {_fz(spins)} en al menos un tercio de las vueltas: "
                              "la trasera pierde agarre ahí.",
                              [("Control de tracción", "+1 si ocurre al acelerar"),
                               ("Reparto de frenada", "más adelante si ocurre al frenar")]))

    s = rep.slip
    if s and s.braking_samples > 200:
        diff = s.front_slip - s.rear_slip          # más negativo: las delanteras deslizan más
        axle, change = None, None
        if diff < -0.006:
            axle, change = "delantero", ("Reparto de frenada", "0,5 % más atrás")
        elif diff > 0.006:
            axle, change = "trasero", ("Reparto de frenada", "0,5 % más adelante")
        if s.abs_active is not None and s.abs_active > 0.45:
            txt = f"El ABS actúa el {s.abs_active * 100:.0f} % del tiempo que frenas fuerte" + \
                  (f"; desliza más el eje {axle}." if axle else "; los dos ejes deslizan parecido.")
            changes = ([change] if change else []) + \
                [("Tu técnica", "pisa algo menos a fondo al principio de la frenada: con tanto ABS la frenada se alarga")]
            sug.append(Suggestion(2, "Frenos", "El ABS trabaja mucho", txt, changes))
        elif axle:
            sug.append(Suggestion(2, "Frenos", f"En frenada desliza más el eje {axle}",
                                  f"Deslizamiento típico en frenada fuerte: delanteras {s.front_slip * 100:.1f} %, "
                                  f"traseras {s.rear_slip * 100:.1f} %.", [change]))
        if s.abs_active is None:   # coche sin ABS: bloqueos claros
            if s.front_lock > 0.08 and s.front_lock > 2 * s.rear_lock:
                sug.append(Suggestion(1, "Frenos", "Bloqueas las delanteras",
                                      f"Una delantera bloquea el {s.front_lock * 100:.0f} % de la frenada fuerte.",
                                      [("Reparto de frenada", "0,5–1 % más atrás")]))
            elif s.rear_lock > 0.06 and s.rear_lock > 1.5 * s.front_lock:
                sug.append(Suggestion(1, "Frenos", "Bloqueas las traseras",
                                      f"Una trasera bloquea el {s.rear_lock * 100:.0f} % de la frenada fuerte.",
                                      [("Reparto de frenada", "0,5–1 % más adelante"), ("Freno motor", "-1")]))
    if s and s.tc_active is not None and s.tc_active > 0.15:
        sug.append(Suggestion(2, "Tracción", "El TC actúa mucho",
                              f"El control de tracción corta el {s.tc_active * 100:.0f} % del tiempo que aceleras: "
                              "pierdes empuje a la salida.",
                              [("Diferencial en tracción", "más bloqueo"), ("Barra estabilizadora tras.", "un punto más blanda"),
                               ("Tu técnica", "abre gas más progresivo a la salida")]))
    elif s and s.traction_samples > 200 and s.rear_spin > 0.12:
        sug.append(Suggestion(2, "Tracción", "Patinas al acelerar",
                              f"Las traseras giran más rápido que el coche el {s.rear_spin * 100:.0f} % del tiempo "
                              "que aceleras a fondo.", [("Control de tracción", "+1")]))

    sug += _tyres_and_brakes(sd, laps)
    sug += _history(setup, own_infos)
    return sug


def _tyres_and_brakes(sd, laps) -> list:
    sug = []
    nums = {l.num for l in laps}
    stats = [st for st in lapstats.lap_stats(sd) if st.num in nums]
    if not stats or not stats[0].t_centre:
        return sug
    avg = lambda attr, k: statistics.mean(getattr(st, attr)[k] for st in stats if getattr(st, attr))
    press, camber_more, camber_less = [], [], []
    for k, w in enumerate(lapstats.WHEELS):
        i, c, o = avg("t_inner", k), avg("t_centre", k), avg("t_outer", k)
        edges = (i + o) / 2
        if abs(c - edges) > 4:
            press.append((w, c - edges))
        if i - o > 12:
            camber_less.append((w, i - o))
        elif o - i > 2:
            camber_more.append((w, o - i))
    for sign, word in ((1, "alta"), (-1, "baja")):
        ws = [(w, d) for w, d in press if sign * d > 0]
        if ws:
            sug.append(Suggestion(2, "Neumáticos", f"Presión {word} en {', '.join(w for w, _ in ws)}",
                                  "El centro de la banda va " + ", ".join(f"{w} {abs(d):.0f} °C" for w, d in ws) +
                                  f" {'más caliente' if sign > 0 else 'más frío'} que los bordes.",
                                  [(f"Presión en frío ({w})", f"{-round(d * 1.5):+d} kPa "
                                    f"({-round(d * 1.5) / lapstats.KPA_PER_PSI:+.1f} psi)") for w, d in ws]))
    if camber_less:
        sug.append(Suggestion(3, "Neumáticos", f"Sobra caída en {', '.join(w for w, _ in camber_less)}",
                              "El interior va " + ", ".join(f"{w} {d:.0f} °C" for w, d in camber_less) +
                              " más caliente que el exterior.",
                              [(f"Caída (camber) ({w})", "algo menos negativa") for w, _ in camber_less]))
    if camber_more:
        sug.append(Suggestion(3, "Neumáticos", f"Falta caída en {', '.join(w for w, _ in camber_more)}",
                              "El exterior va " + ", ".join(f"{w} {d:.0f} °C" for w, d in camber_more) +
                              " más caliente que el interior.",
                              [(f"Caída (camber) ({w})", "algo más negativa") for w, _ in camber_more]))
    if stats[0].brake_max:
        fmax = max(max(st.brake_max[:2]) for st in stats if st.brake_max)
        rmax = max(max(st.brake_max[2:]) for st in stats if st.brake_max)
        for axle, val, key in (("delanteros", fmax, "Tomas de freno delanteras"),
                               ("traseros", rmax, "Tomas de freno traseras")):
            if val > 850:
                sug.append(Suggestion(2, "Frenos", f"Frenos {axle} muy calientes", f"Llegan a {val:.0f} °C.",
                                      [(key, "más abiertas")]))
            elif val < 350:
                sug.append(Suggestion(3, "Frenos", f"Frenos {axle} fríos", f"No pasan de {val:.0f} °C.",
                                      [(key, "más cerradas")]))
    return sug


def _history(setup, own_infos) -> list:
    """Ajustes con los que, en tus sesiones con este coche y circuito, has ido más rápido."""
    if len(own_infos) < 4:
        return []
    by_param = defaultdict(lambda: defaultdict(list))
    for s in own_infos:
        if s.best <= 0:
            continue
        try:
            st = lapstats.read_setup_file(s.path)
        except Exception:
            continue
        for key, (_, val) in st.items():
            cat, _, _ = lapstats.setup_label(key)
            if cat in ("Electrónica", "Frenos", "Aerodinámica", "Diferencial") and val not in ("", "N/A"):
                by_param[key][val].append(s.best)
    out = []
    for key, vals in by_param.items():
        good = {v: statistics.median(t) for v, t in vals.items() if len(t) >= 2}
        if len(good) < 2:
            continue
        best_val = min(good, key=good.get)
        cur = setup.get(key, ("", ""))[1]
        if cur == best_val or cur not in good:
            continue
        gain = good[cur] - good[best_val]
        if gain < 0.25:
            continue
        _, name, _ = lapstats.setup_label(key)
        out.append(Suggestion(3, "Tu historial", f"{name}: te ha ido mejor con {best_val}",
                              f"Tu mejor vuelta por sesión (mediana): {good[best_val]:.3f} s con {best_val} "
                              f"({len(vals[best_val])} sesiones) frente a {good[cur]:.3f} s con {cur} "
                              f"({len(vals[cur])} sesiones). Ojo: la pista, el combustible o el día también influyen.",
                              [(name, f"{cur} → {best_val}")]))
    out.sort(key=lambda s: s.title)
    return out[:4]
