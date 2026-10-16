"""Carga una repetición .Vcr para la app: posiciones de todos los coches remuestreadas y en caché."""
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import vcr
from .paths import DATA_DIR

RATE = 5.0           # Hz con que se guardan las posiciones (la vista interpola entre medias)
CACHE_DIR = DATA_DIR / "replay_cache"
CACHE_VERSION = 1


@dataclass
class ReplayData:
    path: str
    session: dict
    track: str
    participants: list           # list[vcr.Participant]
    t0: float
    t1: float
    cars: dict                   # id -> (t, x, z) np.float32, a RATE Hz

    def driver(self, vehicle: int, t: float) -> str:
        p = vcr.driver_at(self.participants, vehicle, t)
        return p.driver if p else f"Coche {vehicle}"

    def entry(self, vehicle: int, t: float):
        return vcr.driver_at(self.participants, vehicle, t)


def display_name(stem: str) -> str:
    """LMU codifica los bytes UTF-8 no ASCII de los nombres de archivo como '+~XX'.
    'Aut+~c3+~b3dromo' -> 'Autódromo'."""
    import re
    if "+~" not in stem:
        return stem
    raw = re.sub(r"\+~([0-9a-fA-F]{2})", lambda m: "%" + m.group(1), stem)
    from urllib.parse import unquote
    return unquote(raw, encoding="utf-8", errors="replace")


def _cache_file(path: Path) -> Path:
    st = path.stat()
    safe = "".join(c if c.isalnum() else "_" for c in path.stem)
    return CACHE_DIR / f"{safe}_{st.st_size}_{int(st.st_mtime)}.npz"


def list_replays(folder: Path) -> list[dict]:
    """Repeticiones de la carpeta con su información básica (lee solo el bloque final, rápido)."""
    out = []
    for p in sorted(folder.glob("*.Vcr"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            inf = vcr.info(p)
        except (OSError, ValueError, struct.error):
            continue
        sess = inf["session"]
        out.append({
            "path": str(p), "name": display_name(p.stem), "size": p.stat().st_size, "mtime": p.stat().st_mtime,
            "session": sess.get("session", ""), "event": sess.get("eventTitle") or sess.get("sceneDesc", ""),
            "cars": len({x.vehicle for x in inf["participants"]}),
            "cached": _cache_file(p).exists(),
        })
    return out


def load(path: Path, progress=None, cancelled=lambda: False) -> ReplayData:
    """Lee la repetición (o su caché). progress(fracción 0..1)."""
    path = Path(path)
    inf = vcr.info(path)
    cache = _cache_file(path)
    if cache.exists():
        try:
            z = np.load(cache, allow_pickle=False)
            if int(z["version"]) == CACHE_VERSION:
                meta = json.loads(str(z["meta"]))
                cars = {int(k[1:]): (z[f"{k}_t"], z[f"{k}_x"], z[f"{k}_z"]) for k in meta["keys"]}
                return ReplayData(str(path), inf["session"], inf["track"], inf["participants"],
                                  meta["t0"], meta["t1"], cars)
        except (OSError, ValueError, KeyError):
            pass

    size = path.stat().st_size
    step = 1.0 / RATE
    raw = {}            # id -> listas t, x, z
    next_t = {}         # id -> siguiente instante a guardar
    t0 = t1 = None
    for k, fr in enumerate(vcr.frames(path)):
        if t0 is None:
            t0 = fr.time
        t1 = fr.time
        for ev in fr.events:
            if ev.kind in vcr.STATE_KINDS and len(ev.data) == vcr.STATE_SIZE:
                vid = ev.vehicle
                if fr.time < next_t.get(vid, -1e9):
                    continue
                x, _, zz = struct.unpack_from("<fff", ev.data, vcr.POS_OFFSET)
                if not (abs(x) < 20000 and abs(zz) < 20000):
                    continue
                lst = raw.setdefault(vid, ([], [], []))
                lst[0].append(fr.time)
                lst[1].append(x)
                lst[2].append(zz)
                next_t[vid] = fr.time + step * 0.999
        if k % 2000 == 0:
            if progress:
                progress(min(fr.offset / size, 1.0))
            if cancelled():
                raise InterruptedError
    cars = {vid: tuple(np.asarray(a, dtype=np.float32) for a in lists) for vid, lists in raw.items()}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for vid, (t, x, z) in cars.items():
        arrays[f"c{vid}_t"], arrays[f"c{vid}_x"], arrays[f"c{vid}_z"] = t, x, z
    meta = {"keys": [f"c{v}" for v in cars], "t0": t0 or 0.0, "t1": t1 or 0.0}
    try:
        np.savez_compressed(cache, version=CACHE_VERSION, meta=json.dumps(meta), **arrays)
    except OSError:
        pass
    if progress:
        progress(1.0)
    return ReplayData(str(path), inf["session"], inf["track"], inf["participants"], meta["t0"], meta["t1"], cars)
