"""Objetivos de tiempo por circuito y coche («bajar de 1:46,0 en Portimão con el 296»).

Se guardan en goals.json; el coach los lee para decirte en pista a cuánto estás.
"""
import json
import time

from .paths import DATA_DIR

GOALS_PATH = DATA_DIR / "goals.json"


def _key(track: str, car: str, layout: str | None = None) -> str:
    """Un circuito con varios trazados (Silverstone WEC / ELMS) tiene un objetivo por trazado."""
    return f"{track}|{car}" + (f"|{layout}" if layout and layout != track else "")


def _load() -> dict:
    try:
        data = json.loads(GOALS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict):
    GOALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOALS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get(track: str, car: str, layout: str | None = None) -> float | None:
    g = _load().get(_key(track, car, layout))
    return float(g["target"]) if g else None


def set_goal(track: str, car: str, target: float, layout: str | None = None):
    data = _load()
    data[_key(track, car, layout)] = {"target": round(float(target), 3), "since": time.strftime("%Y-%m-%d")}
    _save(data)


def clear(track: str, car: str, layout: str | None = None):
    data = _load()
    if data.pop(_key(track, car, layout), None) is not None:
        _save(data)


def all_goals() -> dict[tuple[str, str, str], float]:
    """{(circuito, coche, trazado): objetivo}; el trazado es el circuito si solo tiene uno."""
    out = {}
    for k, g in _load().items():
        parts = k.split("|")
        track, car = parts[0], parts[1] if len(parts) > 1 else ""
        layout = parts[2] if len(parts) > 2 else track
        out[(track, car, layout)] = float(g["target"])
    return out


def parse_time(text: str) -> float | None:
    """«1:46.5», «1:46,500» o «106.5» → segundos."""
    t = text.strip().replace(",", ".")
    if not t:
        return None
    try:
        if ":" in t:
            m, s = t.split(":", 1)
            return int(m) * 60 + float(s)
        return float(t)
    except ValueError:
        return None


def spoken_gap(gap: float) -> str:
    """Frase para la voz al acabar una vuelta válida, frente al objetivo."""
    from .speech import gap_es
    if gap <= 0:
        return "Objetivo conseguido"
    if gap < 0.05:
        return "A nada de tu objetivo"
    return f"Te faltan {gap_es(gap)} para tu objetivo"
