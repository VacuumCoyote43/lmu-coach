"""Resúmenes de carrera que guarda el coach al acabar (posición por vuelta, ritmo, paradas…).

La telemetría de LMU solo tiene tu coche; la clasificación de los demás solo se ve en directo, así que el
coach la apunta y la app la enseña luego en la sesión de esa carrera.
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from .paths import DATA_DIR

RACES_DIR = DATA_DIR / "race_summaries"


def save(summary: dict, track: str, car: str) -> Path:
    RACES_DIR.mkdir(parents=True, exist_ok=True)
    data = dict(summary, track=track, car=car, saved=time.strftime("%Y-%m-%d %H:%M"))
    data.pop("spoken", None)
    name = time.strftime("%Y-%m-%d_%H%M%S") + ".json"
    p = RACES_DIR / name
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def find(track: str, car: str, recorded: str, max_hours: float = 6.0) -> dict | None:
    """El resumen de la carrera que empezó a la hora «recorded» («2026-10-19 20:01»): mismo circuito y coche,
    guardado después de empezar y no mucho más tarde."""
    try:
        start = datetime.strptime(recorded[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    best = None
    for p in sorted(RACES_DIR.glob("*.json")) if RACES_DIR.is_dir() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            saved = datetime.strptime(d.get("saved", ""), "%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            continue
        if d.get("track") != track or d.get("car") != car:
            continue
        if start - timedelta(minutes=5) <= saved <= start + timedelta(hours=max_hours):
            if best is None or saved < best[0]:
                best = (saved, d)
    return best[1] if best else None
