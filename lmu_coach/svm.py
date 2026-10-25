"""Reglajes de LMU en texto (.svm): leer, cambiar posiciones y guardar uno nuevo.

Cada línea es «Clave=posición//texto»: LMU usa la posición; el texto es solo un comentario con el valor
(«RearAntiSwaySetting=3//P3 18x2mm»). Al cambiar una posición no sabemos el texto nuevo, así que el
comentario se marca como cambiado y LMU lo vuelve a calcular al cargarlo.

Los límites de cada ajuste no vienen en el .svm: se sacan de tu última sesión con ese mismo coche (LMU
guarda en cada sesión la posición, el mínimo y el máximo de todo el reglaje). El coche se reconoce por su
archivo .VEH, que el .svm apunta en la cabecera.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

WHEEL_SECTIONS = {"FRONTLEFT": "FL", "FRONTRIGHT": "FR", "REARLEFT": "RL", "REARRIGHT": "RR"}
WHEEL_NAMES = {"FL": "DI", "FR": "DD", "RL": "TI", "RR": "TD"}
NOT_ADJUSTABLE = ("n/a", "non-adjustable", "fixed", "detached", "desacoplada", "n/d")

# clave del .svm (o sección:clave) → clave del reglaje en las sesiones
_VM = {
    "FuelSetting": "VM_FUEL_LEVEL", "VirtualEnergySetting": "VM_VIRTUAL_ENERGY", "NumPitstopsSetting": "VM_NUM_PITSTOPS",
    "FWSetting": "VM_FRONT_WING", "RWSetting": "VM_REAR_WING",
    "WaterRadiatorSetting": "VM_WATER_RADIATOR", "OilRadiatorSetting": "VM_OIL_RADIATOR",
    "BrakeDuctSetting": "VM_BRAKE_DUCTS", "BrakeDuctRearSetting": "VM_BRAKE_DUCTS_REAR",
    "FrontAntiSwaySetting": "VM_FRONT_ANTISWAY", "RearAntiSwaySetting": "VM_REAR_ANTISWAY",
    "FrontToeInSetting": "VM_FRONT_TOEIN", "RearToeInSetting": "VM_REAR_TOEIN",
    "FrontToeOffsetSetting": "VM_FRONT_TOEOFFSET", "RearToeOffsetSetting": "VM_REAR_TOEOFFSET",
    "SteerLockSetting": "VM_STEER_LOCK", "RearBrakeSetting": "VM_BRAKE_BALANCE",
    "BrakeMigrationSetting": "VM_BRAKE_MIGRATION", "BrakePressureSetting": "VM_BRAKE_PRESSURE",
    "TractionControlMapSetting": "VM_TRACTIONCONTROLMAP", "TCPowerCutMapSetting": "VM_TRACTIONCONTROLPOWERCUTMAP",
    "TCSlipAngleMapSetting": "VM_TRACTIONCONTROLSLIPANGLEMAP",
    "AntilockBrakeSystemMapSetting": "VM_ANTILOCKBRAKESYSTEMMAP",
    "RevLimitSetting": "VM_REV_LIMITER", "EngineBoostSetting": "VM_ENGINE_BOOST",
    "RegenerationMapSetting": "VM_REGEN_LEVEL", "ElectricMotorMapSetting": "VM_ELECTRIC_MOTOR_MAP",
    "EngineMixtureSetting": "VM_ENGINE_MIXTURE", "EngineBrakingMapSetting": "VM_ENGINE_BRAKEMAP",
    "DiffPumpSetting": "VM_DIFF_PUMP", "DiffPowerSetting": "VM_DIFF_POWER", "DiffCoastSetting": "VM_DIFF_COAST",
    "DiffPreloadSetting": "VM_DIFF_PRELOAD",
    "Front3rdPackerSetting": "VM_FRONT_3RD_PACKERS", "Front3rdSpringSetting": "VM_FRONT_3RD_SPRING",
    "Front3rdSlowBumpSetting": "VM_FRONT_3RD_SLOWBUMP", "Front3rdFastBumpSetting": "VM_FRONT_3RD_FASTBUMP",
    "Front3rdSlowReboundSetting": "VM_FRONT_3RD_SLOWREBOUND", "Front3rdFastReboundSetting": "VM_FRONT_3RD_FASTREBOUND",
    "Rear3rdPackerSetting": "VM_REAR_3RD_PACKERS", "Rear3rdSpringSetting": "VM_REAR_3RD_SPRING",
    "Rear3rdSlowBumpSetting": "VM_REAR_3RD_SLOWBUMP", "Rear3rdFastBumpSetting": "VM_REAR_3RD_FASTBUMP",
    "Rear3rdSlowReboundSetting": "VM_REAR_3RD_SLOWREBOUND", "Rear3rdFastReboundSetting": "VM_REAR_3RD_FASTREBOUND",
}
_WM = {
    "CamberSetting": "WM_CAMBER", "PressureSetting": "WM_PRESSURE", "PackerSetting": "WM_PACKERS",
    "SpringSetting": "WM_SPRING", "TenderSpringSetting": "WM_TENDERSPRING",
    "TenderTravelSetting": "WM_TENDERSPRINGTRAVEL", "SpringRubberSetting": "WM_SRUBBER",
    "RideHeightSetting": "WM_RIDEHEIGHT", "SlowBumpSetting": "WM_SLOWBUMP", "FastBumpSetting": "WM_FASTBUMP",
    "SlowReboundSetting": "WM_SLOWREBOUND", "FastReboundSetting": "WM_FASTREBOUND",
    "BrakeDiscSetting": "WM_BRAKEDISC", "BrakePadSetting": "WM_BRAKEPAD", "CompoundSetting": "WM_COMPOUND",
}

# qué hace subir o bajar cada ajuste (orientativo: en LMU, subir la posición sube el valor; el reparto va atrás)
EFFECTS = {
    "VM_REAR_WING": ("más agarre detrás en curva rápida y más estable; menos velocidad punta",
                     "más velocidad punta; la trasera más suelta en curva rápida"),
    "VM_FRONT_ANTISWAY": ("delante más reactivo, más subviraje en apoyo", "más agarre delante en apoyo, más balanceo"),
    "VM_REAR_ANTISWAY": ("gira mejor (menos subviraje), trasera más nerviosa", "trasera más estable y con más tracción"),
    "VM_BRAKE_BALANCE": ("freno más atrás: gira mejor al frenar, puede soltarse la trasera",
                         "freno más adelante: más estable, más subviraje al frenar"),
    "VM_TRACTIONCONTROLMAP": ("más control de tracción: más fácil, algo menos de empuje",
                              "menos control: más empuje si lo dosificas"),
    "VM_TRACTIONCONTROLPOWERCUTMAP": ("corta más potencia al patinar", "corta menos potencia"),
    "VM_TRACTIONCONTROLSLIPANGLEMAP": ("actúa antes con el coche cruzado", "deja cruzar más el coche"),
    "VM_ANTILOCKBRAKESYSTEMMAP": ("más ayuda del ABS", "menos ABS: frenada más corta si no bloqueas"),
    "VM_BRAKE_PRESSURE": ("más fuerza de freno con el mismo pedal", "menos fuerza: más fácil no bloquear"),
    "VM_BRAKE_DUCTS": ("frenos delanteros más calientes (tomas más cerradas)", "frenos delanteros más fríos"),
    "VM_BRAKE_DUCTS_REAR": ("frenos traseros más calientes (tomas más cerradas)", "frenos traseros más fríos"),
    "VM_DIFF_PRELOAD": ("más tracción y estabilidad, cuesta más girar", "gira mejor, menos tracción a la salida"),
    "VM_STEER_LOCK": ("más giro de rueda: dirección más rápida", "dirección más lenta y suave"),
    "VM_FUEL_LEVEL": ("más combustible: más peso", "menos combustible: menos peso"),
    "WM_PRESSURE": ("más presión: neumático más caliente y reactivo, menos huella", "menos presión: más huella"),
    "WM_CAMBER": ("caída menos negativa: mejor en frenada y tracción", "más negativa: más agarre en apoyo"),
    "WM_SPRING": ("muelle más duro: más reactivo, menos agarre en baches", "más blando: más agarre mecánico"),
    "WM_RIDEHEIGHT": ("más alto: menos carga aerodinámica, más margen en piques", "más bajo: más carga, toca antes"),
    "WM_SLOWBUMP": ("más compresión lenta: transferencias más rápidas", "menos: transferencias más suaves"),
    "WM_FASTBUMP": ("más compresión rápida: más duro en pianos", "menos: absorbe mejor pianos"),
    "WM_SLOWREBOUND": ("más extensión lenta: más control del balanceo", "menos: transferencias más suaves"),
    "WM_FASTREBOUND": ("más extensión rápida", "menos extensión rápida"),
}


@dataclass
class Entry:
    section: str
    key: str
    index: int
    text: str            # comentario (valor legible) tal como venía
    line: int            # nº de línea en el archivo
    new_index: int | None = None
    default: bool = False   # línea comentada: LMU usa el valor de serie (al cambiarla se descomenta)

    @property
    def session_key(self) -> str | None:
        if self.section in WHEEL_SECTIONS and self.key in _WM:
            return f"{_WM[self.key]}-W_{WHEEL_SECTIONS[self.section]}"
        return _VM.get(self.key)

    @property
    def effect_key(self) -> str | None:
        k = self.session_key
        return k.split("-W_")[0] if k else None

    @property
    def adjustable(self) -> bool:
        return self.text.strip().lower() not in NOT_ADJUSTABLE

    @property
    def changed(self) -> bool:
        return self.new_index is not None and self.new_index != self.index

    @property
    def value(self) -> int:
        return self.new_index if self.new_index is not None else self.index


@dataclass
class SvmFile:
    path: Path
    lines: list
    entries: list = field(default_factory=list)
    vehicle_class: str = ""
    veh_stem: str = ""

    def entry(self, session_key: str) -> Entry | None:
        return next((e for e in self.entries if e.session_key == session_key), None)

    def changes(self) -> list[Entry]:
        return [e for e in self.entries if e.changed]


_LINE = re.compile(r"^(//)?(\w+)=(-?\d+)(?://(.*))?$")


def parse(path: Path) -> SvmFile:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()
    svm = SvmFile(Path(path), lines)
    section = ""
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if line.startswith("VehicleClassSetting="):
            svm.vehicle_class = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("//VEH="):
            svm.veh_stem = Path(line[6:].strip().replace("\\", "/")).stem
        if section in ("", "BASIC"):
            continue
        m = _LINE.match(line)
        if m:
            svm.entries.append(Entry(section, m.group(2), int(m.group(3)), (m.group(4) or "").strip(), i,
                                     default=bool(m.group(1))))
    return svm


def render(svm: SvmFile, note: str = "") -> str:
    out = list(svm.lines)
    for e in svm.entries:
        if e.changed:
            out[e.line] = f"{e.key}={e.new_index}//(cambiado en LMU Coach; antes {e.index}: {e.text})"
    if note:
        for i, line in enumerate(out):
            if line.strip().startswith("Notes="):
                out[i] = f'Notes="{note.replace(chr(34), chr(39))}"'
                break
    return "\r\n".join(out) + "\r\n"


def save(svm: SvmFile, path: Path, note: str = "") -> Path:
    path = Path(path)
    if path.suffix.lower() != ".svm":
        path = path.with_suffix(".svm")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(svm, note), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- dónde están

def settings_dir() -> Path | None:
    from .sessions import find_lmu_dir
    lmu = find_lmu_dir()
    d = lmu / "UserData" / "player" / "Settings" if lmu else None
    return d if d and d.is_dir() else None


def find_setups() -> list[Path]:
    """El reglaje que tienes cargado ahora en LMU (TempModFile.svm) y los .svm guardados por circuito."""
    d = settings_dir()
    if d is None:
        return []
    out = []
    temp = d.parent / "TempModFile.svm"
    if temp.is_file():
        out.append(temp)
    out += sorted(d.glob("*/*.svm"), key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def track_folders() -> list[str]:
    d = settings_dir()
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d else []


def guess_track_folder(track: str, folders: list[str]) -> str | None:
    """«Algarve International Circuit» → «Portimao» (por el nombre corto que ya usa la app)."""
    import unicodedata
    from .gui.common import SHORT_TRACKS

    def norm(s):
        s = unicodedata.normalize("NFD", s.lower())
        return "".join(c for c in s if c.isalnum() and unicodedata.category(c) != "Mn")

    cands = [norm(track), norm(SHORT_TRACKS.get(track, ""))]
    for f in folders:
        nf = norm(f)
        if any(c and (c == nf or c.startswith(nf) or nf.startswith(c)) for c in cands):
            return f
    for f in folders:
        nf = norm(f)
        if any(c and (nf in c or c in nf) for c in cands if len(c) > 3):
            return f
    return None


def limits_from_sessions(svm: SvmFile, sessions, car_stem_for) -> tuple[dict, str | None]:
    """({clave de sesión: (posición, mín, máx)}, coche) de tu sesión más reciente con el coche del .svm."""
    if not svm.veh_stem:
        return {}, None
    from .sessions import SessionData
    mine = sorted((s for s in sessions if not s.error and not s.imported), key=lambda s: s.recorded, reverse=True)
    for s in mine:
        try:
            if car_stem_for(s.car) != svm.veh_stem:
                continue
            return SessionData(s).setup_steps(), s.car
        except Exception:
            continue
    return {}, None


def apply_suggestions(svm: SvmFile, suggestions, limits: dict) -> list[str]:
    """Aplica los cambios del asistente de reglaje que se pueden aplicar (un paso en su sentido)."""
    done = []
    for s in suggestions:
        for ch in getattr(s, "raw_changes", []):
            if len(ch) < 4 or not ch[2] or not ch[3]:
                continue
            e = svm.entry(ch[2])
            if e is None or not e.adjustable or e.changed:
                continue
            new = e.index + ch[3]
            lo, hi = (limits.get(ch[2]) or (None, 0, None))[1:]
            if new < (lo or 0) or (hi is not None and new > hi):
                continue
            e.new_index = new
            done.append(f"{ch[0]}: {ch[1]}")
    return done
