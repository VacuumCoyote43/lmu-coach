"""Imágenes oficiales de los coches, sacadas de la interfaz de LMU (Bin/UI.zip).

LMU trae en su interfaz una imagen por decoración (vista frontal en dos tamaños y vista cenital),
con el nombre del archivo .VEH de esa decoración. Para pasar del nombre que guarda la telemetría
(«Manthey Ema 2024 #91:LM») al .VEH se combinan, por orden:
  1. la lista que LMU sirve en http://localhost:6397 mientras está abierto (se guarda en caché),
  2. la lista que viene dentro de UI.zip (puede no tener las decoraciones más nuevas),
  3. una aproximación por dorsal, año y equipo.
No se modifica ni se extrae nada del juego: se lee el zip en memoria.
"""
import json
import re
import threading
import urllib.request
import zipfile
from pathlib import Path

from .paths import DATA_DIR

CACHE_PATH = DATA_DIR / "car_map.json"
API = "http://localhost:6397/rest/sessions/getAllVehicles"
KINDS = {"thumb": "FrontThumbnail", "large": "FrontLarge", "top": "topDownRotated"}

_NAME_RE = re.compile(r"^(?P<team>.*?)\s*(?:(?P<year>20\d\d)\s*)?#(?P<num>\d+)(?::(?P<tag>\w+))?\s*$")
_VEH_RE = re.compile(rb'name:\s*"([^"]+)",\s*veh:\s*"([^"]+)\.VEH"', re.I)


def _stem(path: str) -> str:
    return re.split(r"[\\/]", path)[-1].rsplit(".", 1)[0]


class CarImages:
    def __init__(self, lmu_dir: Path | None):
        self.zip_path = Path(lmu_dir) / "Bin" / "UI.zip" if lmu_dir else None
        self._zip = None
        self._files: dict[tuple[str, str], str] = {}   # (tipo, stem) -> ruta en el zip
        self._stems: set[str] = set()
        self._map: dict[str, str] = {}                 # nombre de la telemetría -> stem
        self._lock = threading.Lock()
        self._loaded = False

    # --- carga -----------------------------------------------------------

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            self._zip = zipfile.ZipFile(self.zip_path) if self.zip_path and self.zip_path.is_file() else None
        except (OSError, zipfile.BadZipFile):
            self._zip = None
        if not self._zip:
            return
        rev = {v: k for k, v in KINDS.items()}
        for n in self._zip.namelist():
            m = re.match(r"start/images/cars/(FrontLarge|FrontThumbnail|topDownRotated)/(.+)_(?:frontAngle|topDown)\.webp$", n)
            if m:
                self._files[(rev[m.group(1)], m.group(2))] = n
                self._stems.add(m.group(2))
        # lista que trae la propia interfaz
        for n in self._zip.namelist():
            if n.startswith("start/assets/") and n.endswith(".js"):
                data = self._zip.read(n)
                if b"veh:" in data:
                    for a, b in _VEH_RE.findall(data):
                        self._map.setdefault(a.decode("utf-8", "replace"), b.decode("utf-8", "replace"))
        # lista completa guardada de una vez anterior con LMU abierto
        try:
            self._map.update(json.loads(CACHE_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    def refresh_from_game(self, timeout=2.0) -> bool:
        """Si LMU está abierto, guarda su lista completa de decoraciones. Devuelve si lo consiguió."""
        try:
            with urllib.request.urlopen(API, timeout=timeout) as r:
                cars = json.loads(r.read().decode("utf-8"))
            new = {c["desc"]: _stem(c["vehFile"]) for c in cars if c.get("desc") and c.get("vehFile")}
        except Exception:
            return False         # LMU cerrado: lo normal, no es un error
        if not new:
            return False
        with self._lock:
            self._load()
            self._map.update(new)
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                old = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
                old.update(new)
                CACHE_PATH.write_text(json.dumps(old, ensure_ascii=False, indent=0), encoding="utf-8")
            except (OSError, ValueError):
                pass
        return True

    # --- búsqueda --------------------------------------------------------

    def stem_for(self, car_name: str) -> str | None:
        with self._lock:
            self._load()
            if not self._stems or not car_name:
                return None
            s = self._map.get(car_name)
            if s in self._stems:
                return s
            return self._guess(car_name)

    def _guess(self, name: str) -> str | None:
        m = _NAME_RE.match(name.strip())
        if not m:
            return None
        team, year, num, tag = m.group("team"), m.group("year"), m.group("num"), m.group("tag") or ""
        yy = year[2:] if year else (re.search(r"(\d\d)$", tag).group(1) if re.search(r"\d\d$", tag) else None)
        if "Custom Team" in team:     # «296GT3 Custom Team 2026 #397», «911GT3R ELMS Custom Team 2025 #397»
            model = team.split("Custom Team")[0].split()
            if model and yy:
                series = "ELMS" if "ELMS" in model[1:] else ""
                s = f"397_{yy}{series}_{model[0].upper()}"
                return s if s in self._stems else None
            return None
        words = [re.sub(r"[^A-Z0-9]", "", w) for w in team.upper().split()]
        keys = ["".join(words[i:]) for i in range(len(words)) if words[i]]   # «Vista AF Corse» → AFCO…

        def score(rest):
            best = 0
            for key in keys:
                n = 0
                while n < min(len(rest), len(key)) and rest[n] == key[n]:
                    n += 1
                best = max(best, n)
            return best
        # primero con el año; si no hay ninguna decoración de ese año, las que no llevan año
        for prefix in ([f"{num}_{yy}_"] if yy else []) + [f"{num}_"]:
            scored = sorted(((score(s[len(prefix):]), s) for s in self._stems
                             if s.startswith(prefix) and (prefix != f"{num}_" or not re.match(r"\d\d_", s[len(prefix):]))),
                            reverse=True)
            # con varias del mismo equipo, dorsal y año (otra carrera) cualquiera se parece: vale la primera
            if scored and scored[0][0] >= 3:
                return scored[0][1]
        return None

    def image_bytes(self, car_name: str, kind: str = "thumb") -> bytes | None:
        """Imagen .webp de la decoración (kind: thumb 500×200, large 2000×800, top 400×1000)."""
        stem = self.stem_for(car_name)
        if not stem:
            return None
        with self._lock:
            path = self._files.get((kind, stem))
            try:
                return self._zip.read(path) if path else None
            except (OSError, KeyError, zipfile.BadZipFile):
                return None
