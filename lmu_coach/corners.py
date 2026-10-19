"""Nombres de las curvas: los conocidos de cada circuito y los que pongas tú.

Cada nombre va anclado a la distancia del vértice en la vuelta de LMU (m). Una frenada toma el
nombre del ancla más cercana a su vértice (hasta MATCH_M), así sirve para cualquier coche aunque
frene antes o después. Si no hay nombre, se queda como «F3».
"""
import json

from .paths import DATA_DIR

USER_PATH = DATA_DIR / "corner_names.json"
MATCH_M = 100

# (circuito, trazado) -> [(vértice en m, nombre)]. Solo las curvas reconocibles con seguridad;
# el resto se puede nombrar desde la app.
DEFAULTS = {
    ("Autodromo Nazionale Monza", "Autodromo Nazionale Monza"): [
        (964, "Rettifilo"), (2154, "Roggia"), (2584, "Lesmo 1"), (2866, "Lesmo 2"),
        (3953, "Ascari"), (5225, "Parabolica"),
    ],
    ("Silverstone Circuit", "Silverstone Grand Prix Circuit - WEC"): [
        (244, "Abbey"), (773, "Village"), (903, "The Loop"), (1875, "Brooklands"), (2041, "Luffield"),
        (2992, "Copse"), (3636, "Maggotts"), (3758, "Becketts"), (3889, "Chapel"), (4893, "Stowe"),
        (5393, "Vale"),
    ],
    ("Silverstone Circuit", "Silverstone Grand Prix Circuit - ELMS"): [
        (431, "Copse"), (1040, "Maggotts"), (1200, "Becketts"), (1313, "Chapel"), (2345, "Stowe"),
        (2809, "Vale"), (3552, "Abbey"), (4052, "Village"), (4191, "The Loop"), (5177, "Brooklands"),
        (5352, "Luffield"),
    ],
    ("Autódromo José Carlos Pace", "Autódromo José Carlos Pace"): [
        (391, "S do Senna"), (1436, "Descida do Lago"), (2168, "Ferradura"), (2340, "Pinheirinho"),
        (2759, "Bico de Pato"), (3259, "Junção"),
    ],
    ("Fuji Speedway", "Fuji Speedway"): [
        (763, "Curva 1"), (1343, "Coca-Cola"), (1749, "100R"), (2012, "Horquilla"), (2837, "Dunlop"),
        (3668, "Panasonic"),
    ],
    ("Circuit of the Americas", "Circuit of the Americas"): [
        (668, "Curva 1"), (2597, "Curva 11"), (3783, "Curva 12"), (5319, "Curva 20"),
    ],
    ("Sebring International Raceway", "Sebring International Raceway"): [
        (516, "Curva 1"), (2014, "Horquilla"), (5423, "Sunset Bend"),
    ],
    ("Michelin Raceway Road Atlanta", "Michelin Raceway Road Atlanta"): [
        (476, "Curva 1"), (2153, "Curva 7"), (3520, "Curva 10"), (3906, "Curva 12"),
    ],
    ("Grand Prix of Long Beach", "Grand Prix of Long Beach"): [
        (723, "Curva 1"), (2818, "Horquilla"),
    ],
    ("Algarve International Circuit", "Algarve International Circuit"): [
        (419, "Curva 1"),
    ],
}

_user: dict | None = None


def _load_user() -> dict:
    global _user
    if _user is None:
        try:
            _user = json.loads(USER_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _user = {}
    return _user


def _key(track: str, layout: str | None) -> str:
    return f"{track}|{layout or ''}"


def _anchors(track: str, layout: str | None) -> list[tuple[float, str]]:
    """Anclas del circuito: las tuyas (mandan) y las de serie. Acepta el nombre del circuito o del trazado
    (el coach en directo solo conoce uno de los dos)."""
    out = []
    user = _load_user()
    for k, names in user.items():
        t, l = k.split("|", 1)
        if (t == track and (l == (layout or "") or not layout)) or (not layout and l == track):
            out += [(float(a), n) for a, n in names.items()]
    for (t, l), names in DEFAULTS.items():
        if (t == track and (layout is None or l == layout)) or (layout is None and l == track):
            out += [(a, n) for a, n in names if all(abs(a - u) > MATCH_M for u, _ in out)]
    return out


def name_for(track: str, layout: str | None, apex: float) -> str | None:
    best = None
    for a, n in _anchors(track, layout):
        d = abs(a - apex)
        if d <= MATCH_M and (best is None or d < best[0]):
            best = (d, n)
    return best[1] if best and best[1] else None


def label(zone, track: str, layout: str | None = None, with_num=True) -> str:
    """«F3 · Ferradura» (o solo «Ferradura» con with_num=False); «F3» si no tiene nombre."""
    n = name_for(track, layout, zone.apex)
    if not n:
        return f"F{zone.idx}"
    return f"F{zone.idx} · {n}" if with_num else n


def spoken(zone, track: str, layout: str | None = None) -> str:
    """Para la voz: «en Ferradura» / «en la 3»."""
    n = name_for(track, layout, zone.apex)
    return f"en {n}" if n else f"en la {zone.idx}"


def resolve_layout(track: str, apexes: list[float]) -> str | None:
    """Trazado de ese circuito cuyas curvas encajan mejor con estas frenadas (el coach no lo sabe)."""
    best = None
    for (t, l), names in DEFAULTS.items():
        if t != track and l != track:
            continue
        hits = sum(any(abs(a - x) <= MATCH_M for x in apexes) for a, _ in names)
        if best is None or hits > best[0]:
            best = (hits, l, t)
    return best[1] if best and best[0] else None


def default_name(track: str, layout: str | None, apex: float) -> str | None:
    for (t, l), names in DEFAULTS.items():
        if t == track and (layout is None or l == layout):
            for a, n in names:
                if abs(a - apex) <= MATCH_M:
                    return n
    return None


def reset_name(track: str, layout: str | None, apex: float):
    """Quita tu nombre y vuelve al de serie (si lo hay)."""
    user = _load_user()
    names = user.get(_key(track, layout), {})
    for a in [a for a in names if abs(float(a) - apex) <= MATCH_M]:
        del names[a]
    USER_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_PATH.write_text(json.dumps(user, ensure_ascii=False, indent=1), encoding="utf-8")


def set_name(track: str, layout: str | None, apex: float, name: str):
    """Guarda (o borra, con nombre vacío) el nombre de la curva con ese vértice."""
    user = _load_user()
    names = user.setdefault(_key(track, layout), {})
    for a in [a for a in names if abs(float(a) - apex) <= MATCH_M]:
        del names[a]
    # un nombre vacío tapa también el de serie (vuelve a «F3»)
    names[str(round(apex))] = name.strip()
    USER_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_PATH.write_text(json.dumps(user, ensure_ascii=False, indent=1), encoding="utf-8")
