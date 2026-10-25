"""Debrief de una sesión: las 3 cosas que más tiempo te darían, ordenadas por lo que ganarías por vuelta.

Junta lo que ya calcula la app en sitios distintos (curvas donde pierdes, degradación y errores de cada relevo,
regularidad, asistente de reglaje y vuelta ideal) y lo convierte en acciones concretas, cada una con lo que
la app puede hacer por ti: practicar esa curva con el coach, abrir el setup en el editor o fijar un objetivo.
"""
import statistics
from dataclasses import dataclass, field

from . import lapstats, training
from .log import log


@dataclass
class Action:
    gain: float              # s por vuelta que podrías ganar (estimado)
    kind: str                # corner · tyres · consistency · setup · goal
    title: str
    detail: str
    button: str = ""         # texto del botón
    data: dict = field(default_factory=dict)


@dataclass
class Debrief:
    laps: int
    best: float | None
    pace: float | None
    ideal: float | None
    spread: float | None
    goal: float | None
    actions: list
    headline: str = ""


def _clean_times(sd):
    laps = sorted(l.time for l in sd.laps if l.valid)
    return laps[:max(1, int(len(laps) * 0.8))] if laps else []


def build(sd, own_infos=None, goal=None) -> Debrief:
    info = sd.info
    valid = [l for l in sd.laps if l.valid]
    clean = _clean_times(sd)
    best = min((l.time for l in valid), default=None)
    pace = statistics.median(clean) if clean else None
    spread = statistics.pstdev(clean) if len(clean) > 2 else None
    secs = [min((getattr(l, k) for l in valid if getattr(l, k) > 0), default=0) for k in ("s1", "s2", "s3")]
    ideal = sum(secs) if all(secs) else None
    cands: list[Action] = []

    # 1) curvas donde más pierdes frente a tu mejor vuelta
    try:
        focus, _ = training.build(sd, top=4)
        for f in focus[:2]:
            cands.append(Action(f.loss, "corner", f"{f.name}: pierdes {f.loss:.2f} s por vuelta",
                                f"{f.tips[0][:1].upper() + f.tips[0][1:]}." + (f" También: {f.tips[1]}." if len(f.tips) > 1 else ""),
                                "🎯 Practicar esta curva en el coach",
                                {"apex": f.apex, "name": f.name.split("·")[-1].strip(), "focus": focus}))
    except Exception:
        log.warning("Debrief: no se pudieron analizar las curvas", exc_info=True)

    # 2) relevos: degradación de neumáticos y errores
    stats = []
    try:
        stats = lapstats.lap_stats(sd)
        for st in lapstats.stints(stats):
            n = len(st.clean)
            if st.slope_fuel is not None and st.slope_fuel > 0.06 and n >= 6:
                hot = [h for h in lapstats.tyre_hints(st.laps[-1]) if "más calientes" in h or "presión alta" in h]
                cands.append(Action(st.slope_fuel * n / 2, "tyres",
                                    f"Los neumáticos te cuestan {st.slope_fuel * n:.1f} s al final del relevo {st.idx}",
                                    f"Cada vuelta vas {st.slope_fuel:.2f} s más lento que la anterior, descontando el "
                                    "combustible: de media pierdes lo de la derecha en cada vuelta del relevo. " +
                                    (hot[0] + ". " if hot else "") +
                                    "Cuida las salidas (menos patinar) o prueba un reglaje que caliente menos el eje "
                                    "que sufre.", "🛠 Abrir el setup en el editor", {}))
            if st.mistakes and n >= 4:
                lost = sum(m[1] for m in st.mistakes)
                cands.append(Action(lost / max(len(st.laps), 1), "consistency",
                                    f"{len(st.mistakes)} errores te costaron {lost:.1f} s (relevo {st.idx})",
                                    "Vueltas " + ", ".join(str(m[0].num) for m in st.mistakes[:5]) + " salen muy "
                                    "por encima de tu ritmo. Mira en «Consistencia» qué frenada varía más.",
                                    "📈 Ver consistencia", {}))
    except Exception:
        log.warning("Debrief: no se pudieron analizar los relevos", exc_info=True)

    # 3) regularidad en general (si no hay errores claros)
    if spread and spread > 0.45 and not any(c.kind == "consistency" for c in cands):
        cands.append(Action(spread * 0.5, "consistency", f"Vas irregular: ±{spread:.2f} s entre vueltas",
                            "Tus vueltas limpias varían mucho. Antes de buscar el límite, repite la misma vuelta: "
                            "frena siempre en el mismo punto.", "📈 Ver consistencia", {}))

    # 4) reglaje: la sugerencia más importante del asistente que se puede aplicar
    try:
        from . import setup_assistant
        rep = setup_assistant.analyze(sd, own_infos or [])
        top = next((s for s in rep.suggestions if s.priority == 1 and s.raw_changes), None)
        if top:
            ch = "; ".join(f"{c[0]}: {c[1]}" for c in top.raw_changes[:2])
            cands.append(Action(0.15, "setup", f"Reglaje: {top.title.lower()}", f"{top.evidence} Prueba: {ch}.",
                                "🛠 Aplicarlo en el editor de setups", {"suggestions": rep.suggestions}))
    except Exception:
        log.warning("Debrief: no se pudo pasar el asistente de reglaje", exc_info=True)

    # 5) vuelta ideal como objetivo
    if best and ideal and best - ideal > 0.15 and not goal:
        cands.append(Action((best - ideal) * 0.3, "goal", f"Tu vuelta ideal es {_t(ideal)}",
                            f"Ya has hecho cada sector así de rápido, pero no en la misma vuelta: {best - ideal:.2f} s "
                            "que están a tu alcance. Fíjala como objetivo y el coach te dirá a cuánto estás.",
                            "🏁 Fijar como objetivo", {"ideal": ideal}))

    # las 3 que más dan, con un máximo de 2 curvas
    cands.sort(key=lambda a: -a.gain)
    actions, corners = [], 0
    for a in cands:
        if a.kind == "corner":
            if corners >= 2:
                continue
            corners += 1
        if a.kind in {x.kind for x in actions} and a.kind != "corner":
            continue
        actions.append(a)
        if len(actions) == 3:
            break
    d = Debrief(len(valid), best, pace, ideal, spread, goal, actions)
    d.headline = _headline(d, info)
    return d


def _t(t):
    from .laps import fmt_time
    return fmt_time(t)


def _headline(d: Debrief, info) -> str:
    if not d.laps:
        return "Sin vueltas válidas: no hay nada que analizar."
    parts = [f"{d.laps} vueltas válidas, mejor {_t(d.best)}"]
    if d.pace:
        parts.append(f"ritmo {_t(d.pace)}")
    if d.goal and d.best:
        gap = d.best - d.goal
        parts.append("objetivo conseguido" if gap <= 0 else f"a {gap:.2f} s de tu objetivo")
    total = sum(a.gain for a in d.actions)
    if total >= 0.1:
        parts.append(f"con estas 3 cosas podrías ganar hasta {total:.1f} s por vuelta")
    return ", ".join(parts) + "."
