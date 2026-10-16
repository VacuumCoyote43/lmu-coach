"""Lectura de las sesiones de telemetría que graba LMU (UserData/Telemetry/*.duckdb).

Formato (descubierto inspeccionando los archivos):
- Una tabla por canal. Los canales periódicos solo tienen `value` y se muestrean a la
  frecuencia de `channelsList`; la muestra i está en t0 + i/f, con t0 = primer "GPS Time".
- Los eventos tienen (ts, value) y solo se graban cuando cambia el valor.
- "Lap" marca el inicio de cada vuelta; "Lap Time" vale el tiempo oficial al acabar
  la vuelta, o 0 si el juego la invalidó.
"""
import bisect
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import numpy as np

from .laps import Lap

DEFAULT_LMU_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate")
RATE = 50.0  # Hz al que remuestreamos cada vuelta


def is_lmu_dir(path: Path) -> bool:
    return (Path(path) / "Le Mans Ultimate.exe").is_file()


def steam_lmu_candidates() -> list[Path]:
    """Carpetas donde podría estar LMU según las bibliotecas de Steam."""
    candidates = [DEFAULT_LMU_DIR]
    steam_dirs = [Path(r"C:\Program Files (x86)\Steam")]
    try:  # Steam puede estar instalado en otra ruta: la guarda en el registro
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam_dirs.insert(0, Path(winreg.QueryValueEx(k, "SteamPath")[0]))
    except OSError:
        pass
    for steam in steam_dirs:
        try:
            vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', vdf):
            lib = Path(m.group(1).replace("\\\\", "\\"))
            candidates.append(lib / "steamapps" / "common" / "Le Mans Ultimate")
    return list(dict.fromkeys(candidates))


def find_lmu_dir() -> Path | None:
    """Carpeta de instalación de LMU: la elegida a mano en la app o la encontrada en Steam."""
    from .paths import load_settings
    manual = load_settings().get("lmu_dir")
    if manual and is_lmu_dir(Path(manual)):
        return Path(manual)
    return next((c for c in steam_lmu_candidates() if is_lmu_dir(c)), None)


def find_telemetry_dir() -> Path:
    # Aunque aún no exista (LMU la crea al grabar la primera sesión) devolvemos dónde estará
    return (find_lmu_dir() or DEFAULT_LMU_DIR) / "UserData" / "Telemetry"


def auto_record_telemetry(lmu_dir: Path | None) -> bool | None:
    """Valor de "Automatically Record Telemetry" en los ajustes de LMU (None si no se puede leer)."""
    if not lmu_dir:
        return None
    try:
        text = (Path(lmu_dir) / "UserData" / "player" / "Settings.JSON").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'"Automatically Record Telemetry"\s*:\s*(true|false)', text, re.IGNORECASE)
    return (m.group(1).lower() == "true") if m else None


@dataclass
class LapInfo:
    num: int
    start: float
    end: float
    duration: float
    time: float        # tiempo oficial (0 si no válida)
    valid: bool
    note: str          # motivo si no es válida
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0


@dataclass
class SessionInfo:
    path: str
    mtime: float
    size: int
    track: str
    layout: str
    car: str
    car_class: str
    session_type: str
    recorded: str      # "2026-10-15 20:07"
    weather: str
    laps: int
    valid_laps: int
    best: float        # mejor vuelta válida (0 si ninguna)
    best_lap: int
    error: str = ""
    driver: str = ""
    imported: bool = False   # sesión importada de otro piloto (o de otro PC)


def _connect(path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=True)


def _events(con, table):
    try:
        return con.execute(f'select ts, value from "{table}" order by ts').fetchall()
    except duckdb.Error:
        return []


def _value_at(events, ts, tol=0.5):
    """Último valor de un evento registrado hasta ts (los eventos solo se graban al cambiar)."""
    times = [e[0] for e in events]
    i = bisect.bisect_right(times, ts + tol)
    return events[i - 1][1] if i else None


def read_laps(con) -> list[LapInfo]:
    lap_ev = _events(con, "Lap")
    if not lap_ev:
        return []
    lt_ev = _events(con, "Lap Time")
    s1_ev = _events(con, "Last Sector1")
    s2_ev = _events(con, "Last Sector2")
    pit_ev = _events(con, "In Pits")
    t_end = con.execute('select max(value) from "GPS Time"').fetchone()[0] or lap_ev[-1][0]

    laps = []
    for i, (start, num) in enumerate(lap_ev):
        finished = i + 1 < len(lap_ev)
        end = lap_ev[i + 1][0] if finished else t_end
        duration = end - start
        official = (_value_at(lt_ev, end) or 0.0) if finished else 0.0
        in_pits = any(start - 0.5 <= ts <= end and v for ts, v in pit_ev) or (_value_at(pit_ev, start) or 0)
        note = ""
        if not finished:
            note = "incompleta"
        elif i == 0 or in_pits:
            note = "boxes / vuelta de salida"
        elif official <= 0:
            note = "invalidada"
        elif abs(official - duration) > 0.5:
            note = "datos incoherentes"
        valid = note == ""
        info = LapInfo(int(num), start, end, duration, official if valid else 0.0, valid, note)
        if valid:
            s1 = _value_at(s1_ev, end) or 0.0
            s12 = _value_at(s2_ev, end) or 0.0
            if 0 < s1 < s12 < official:
                info.s1, info.s2, info.s3 = s1, s12 - s1, official - s12
        laps.append(info)
    return laps


def read_session_info(path: Path, imported: bool = False) -> SessionInfo:
    st = path.stat()
    base = dict(path=str(path), mtime=st.st_mtime, size=st.st_size, imported=imported)
    try:
        con = _connect(path)
        try:
            m = dict(con.execute("select key, value from metadata").fetchall())
            laps = read_laps(con)
        finally:
            con.close()
    except Exception as e:  # archivo en uso por el juego o corrupto
        return SessionInfo(**base, track="?", layout="", car="?", car_class="", session_type="",
                           recorded="", weather="", laps=0, valid_laps=0, best=0.0, best_lap=0,
                           error=f"{type(e).__name__}: {e}"[:200])
    valid = [l for l in laps if l.valid]
    best = min(valid, key=lambda l: l.time) if valid else None
    rec = m.get("RecordingTime", "")
    rec_fmt = re.sub(r"(\d{4}-\d{2}-\d{2})T(\d{2})_(\d{2}).*", r"\1 \2:\3", rec)
    return SessionInfo(
        **base,
        track=m.get("TrackName", "?"), layout=m.get("TrackLayout", ""),
        car=m.get("CarName", "?"), car_class=m.get("CarClass", ""),
        session_type=m.get("SessionType", ""), recorded=rec_fmt,
        weather=m.get("WeatherConditions", ""), driver=m.get("DriverName", ""),
        laps=len(laps), valid_laps=len(valid),
        best=best.time if best else 0.0, best_lap=best.num if best else 0,
    )


class SessionIndex:
    """Índice cacheado de las sesiones propias (telemetría de LMU) y las importadas."""

    CACHE_VERSION = 2

    def __init__(self, telemetry_dir: Path, cache_path: Path, imported_dir: Path | None = None):
        self.dir = Path(telemetry_dir)
        self.imported_dir = Path(imported_dir) if imported_dir else None
        self.cache_path = Path(cache_path)
        self.sessions: list[SessionInfo] = []
        self._load_cache()

    def _load_cache(self):
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if raw.get("version") != self.CACHE_VERSION:
                raise ValueError("caché antigua")
            self.sessions = [SessionInfo(**r) for r in raw["sessions"]]
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError, AttributeError, KeyError):
            self.sessions = []

    def _save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({"version": self.CACHE_VERSION,
                                               "sessions": [asdict(s) for s in self.sessions]}), encoding="utf-8")

    def refresh(self, progress=None) -> list[SessionInfo]:
        """Relee solo los archivos nuevos o modificados. progress(hechos, total)."""
        cached = {s.path: s for s in self.sessions}
        files = [(f, False) for f in self.dir.glob("*.duckdb")]
        if self.imported_dir and self.imported_dir.is_dir():
            files += [(f, True) for f in self.imported_dir.glob("*.duckdb")]
        files.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
        out = []
        for i, (f, imported) in enumerate(files):
            st = f.stat()
            c = cached.get(str(f))
            # Las sesiones con error (p. ej. en uso) se reintentan siempre
            if c and c.mtime == st.st_mtime and c.size == st.st_size and not c.error:
                out.append(c)
            else:
                out.append(read_session_info(f, imported))
            if progress:
                progress(i + 1, len(files))
        self.sessions = out
        self._save_cache()
        return out

    def best_for(self, track: str, car: str, include_imported=False) -> tuple[SessionInfo, float] | None:
        """Mejor vuelta válida para circuito+coche (por defecto solo tus sesiones, no las importadas)."""
        key = (track.strip().casefold(), car.strip().casefold())
        cands = [s for s in self.sessions if s.best > 0 and (include_imported or not s.imported) and
                 (s.track.strip().casefold(), s.car.strip().casefold()) == key]
        if not cands:
            return None
        s = min(cands, key=lambda s: s.best)
        return s, s.best


class SessionData:
    """Una sesión abierta: vueltas y acceso a la telemetría de cada una."""

    CHANNELS = {  # nombre interno: (tabla, escala)
        "v": ("Ground Speed", 1.0),
        "thr": ("Throttle Pos", 0.01),
        "brk": ("Brake Pos", 0.01),
        "steer": ("Steering Pos", 0.01),
        "rpm": ("Engine RPM", 1.0),
        "lapdist": ("Lap Dist", 1.0),
        "lat": ("GPS Latitude", 1.0),
        "lon": ("GPS Longitude", 1.0),
    }

    def __init__(self, info: SessionInfo):
        self.info = info
        con = _connect(info.path)
        try:
            self.laps = read_laps(con)
            freqs = dict((n, f) for n, f, _ in con.execute("select * from channelsList").fetchall())
            self.t0 = con.execute('select value from "GPS Time" limit 1').fetchone()[0]
            self._ch = {}
            for key, (table, scale) in self.CHANNELS.items():
                vals = con.execute(f'select value from "{table}"').fetchnumpy()["value"].astype(np.float64) * scale
                f = float(freqs.get(table, 10))
                self._ch[key] = (self.t0 + np.arange(len(vals)) / f, vals)
            self._gear = _events(con, "Gear")
            self._sector_ev = _events(con, "Current Sector")  # 1=S1, 2=S2, 0=S3
        finally:
            con.close()
        ld_t, ld = self._ch["lapdist"]
        self.track_len = float(np.percentile(ld, 99.9)) if len(ld) else 0.0
        # "Desenrolla" la distancia para que interpolar no mezcle el final y el inicio de vuelta:
        # en cada cruce de meta se suma lo recorrido en la vuelta anterior.
        jumps = np.where(np.diff(ld) < -self.track_len * 0.5)[0] if len(ld) else np.array([], int)
        offsets = np.zeros(len(ld))
        self._wrap_t = ld_t[jumps + 1] if len(jumps) else np.array([])
        self._wrap_c = np.cumsum(ld[jumps]) if len(jumps) else np.array([])
        for j, c in zip(jumps, self._wrap_c):
            offsets[j + 1:] = c
        self._ch["lapdist"] = (ld_t, ld + offsets)
        self._cache = {}

    def lap(self, num: int) -> LapInfo | None:
        return next((l for l in self.laps if l.num == num), None)

    def lap_data(self, num: int) -> dict:
        """Arrays numpy a 50 Hz: t, d, v (km/h), thr, brk (0..1), steer (-1..1), gear, rpm, x, y (m)."""
        if num in self._cache:
            return self._cache[num]
        lap = self.lap(num)
        tg = np.arange(lap.start, lap.end, 1.0 / RATE)
        out = {"t": tg - lap.start}
        for key, (ts, vals) in self._ch.items():
            out[key] = np.interp(tg, ts, vals) if len(vals) else np.zeros_like(tg)
        out["d"] = self._lap_dist(out.pop("lapdist"), lap)
        if self._gear:
            gts = np.array([g[0] for g in self._gear])
            gv = np.array([g[1] for g in self._gear])
            idx = np.clip(np.searchsorted(gts, tg, side="right") - 1, 0, len(gv) - 1)
            out["gear"] = gv[idx]
        else:
            out["gear"] = np.zeros_like(tg)
        lat0 = np.deg2rad(60.0)
        out["x"] = out.pop("lon") * 111320.0 * np.cos(lat0)
        out["y"] = out.pop("lat") * 110540.0
        self._cache[num] = out
        return out

    def _lap_dist(self, d_unwrapped, lap: LapInfo):
        """Distancia desde la línea de meta: resta lo acumulado hasta el cruce de esta vuelta.

        El cruce en Lap Dist puede ir ±0.1 s desfasado del evento "Lap", de ahí el margen de 1 s.
        Si cae justo después del inicio, las primeras muestras quedan ligeramente negativas.
        """
        k = int(np.searchsorted(self._wrap_t, lap.start + 1.0, side="right"))
        base = self._wrap_c[k - 1] if k > 0 else 0.0
        return np.maximum.accumulate(d_unwrapped - base)

    def to_coach_lap(self, num: int) -> Lap:
        """Convierte una vuelta al formato que usa el coach en directo."""
        data = self.lap_data(num)
        lap = self.lap(num)
        keep = (data["d"] >= 0) & (data["d"] <= self.track_len + 5)
        # el coach exige distancia estrictamente creciente
        d = data["d"][keep]
        mono = np.concatenate([[True], np.diff(d) > 0])
        cols = {}
        for key in ("d", "t", "v", "thr", "brk", "steer", "gear", "x", "y"):
            arr = data[key][keep][mono]
            cols["z" if key == "y" else key] = [round(float(v), 4) for v in arr]
        cols["gear"] = [int(g) for g in cols["gear"]]
        return Lap(self.info.track, self.info.car, round(lap.time or lap.duration, 3), self.track_len,
                   self.info.recorded.replace(" ", "T") + ":00", cols, self.sector_starts(num))

    def sector_starts(self, num: int) -> list:
        """Distancias donde empiezan S2 y S3 en esa vuelta (vacío si no se encuentran)."""
        lap = self.lap(num)
        data = self.lap_data(num)
        out = []
        for value in (2, 0):
            ts = next((t for t, v in self._sector_ev if v == value and lap.start + 1 < t < lap.end - 1), None)
            if ts is None:
                return []
            out.append(round(float(np.interp(ts - lap.start, data["t"], data["d"])), 1))
        return out if out[0] < out[1] else []
