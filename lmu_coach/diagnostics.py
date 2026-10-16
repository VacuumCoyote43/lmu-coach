"""Diagnóstico: comprueba qué necesita la app de LMU y lo explica (para cuando "no carga nada")."""
import ctypes as C
import platform
from dataclasses import dataclass
from pathlib import Path

from .paths import DATA_DIR, FROZEN, load_settings
from .sessions import auto_record_telemetry, find_lmu_dir, steam_lmu_candidates

APP_VERSION = "1.4.0"


@dataclass
class Check:
    ok: bool | None   # True bien, False problema, None aviso / no se puede saber
    title: str
    detail: str


def _shared_memory():
    """(¿existe LMU_Data?, versión del juego, ¿hay coche del jugador?, texto)"""
    from .reader import LMUReader
    from .shm_structs import SharedMemoryGeneric
    r = LMUReader()
    try:
        if not r.connect():
            return False, None, False, ""
        gen = SharedMemoryGeneric.from_buffer_copy(C.string_at(r._view, C.sizeof(SharedMemoryGeneric)))
        s = r.read()
        where = f"{s.track} · {s.car}" if s else ""
        return True, gen.gameVersion, s is not None, where
    finally:
        r.close()


def run() -> list[Check]:
    checks = []
    manual = load_settings().get("lmu_dir")
    lmu = find_lmu_dir()
    if lmu:
        how = "elegida a mano" if manual and Path(manual) == lmu else "encontrada en Steam"
        checks.append(Check(True, "Carpeta de LMU", f"{lmu}  ({how})"))
    else:
        tried = "\n".join(f"  · {c}" for c in steam_lmu_candidates())
        checks.append(Check(False, "Carpeta de LMU",
                            "No encuentro Le Mans Ultimate. Pulsa «Elegir carpeta de LMU» y selecciona la carpeta "
                            "donde está «Le Mans Ultimate.exe».\nBuscado en:\n" + tried))

    tdir = (lmu / "UserData" / "Telemetry") if lmu else None
    n = len(list(tdir.glob("*.duckdb"))) if tdir and tdir.is_dir() else 0
    rec = auto_record_telemetry(lmu)
    if tdir and n:
        checks.append(Check(True, "Sesiones grabadas por LMU", f"{n} sesiones en {tdir}"))
    elif lmu:
        checks.append(Check(False, "Sesiones grabadas por LMU",
                            "No hay ninguna sesión en la carpeta UserData\\Telemetry de LMU. Solo se guardan "
                            "si la grabación de telemetría está activada (ver abajo) y después de conducir en pista."))
    if rec is True:
        checks.append(Check(True, "Grabación automática de telemetría", "Activada en LMU"))
    elif rec is False:
        checks.append(Check(False, "Grabación automática de telemetría",
                            "DESACTIVADA. En LMU activa la opción «Automatically Record Telemetry» "
                            "(Ajustes del juego) o usa el atajo de teclado «Telemetry Recording». "
                            "Sin ella no se guardan sesiones para analizar (el modo coach sí funciona)."))
    elif lmu:
        checks.append(Check(None, "Grabación automática de telemetría",
                            "No he podido leer el ajuste. Comprueba en LMU que «Automatically Record Telemetry» "
                            "esté activada."))

    try:
        mapped, version, has_car, where = _shared_memory()
    except Exception as e:  # nunca debe romper el diagnóstico
        mapped, version, has_car, where = False, None, False, f"error: {e}"
    if not mapped:
        checks.append(Check(None, "Datos en directo (modo coach)",
                            "LMU no está abierto ahora mismo (o es una versión antigua sin «LMU_Data»). "
                            "Abre el juego y vuelve a ejecutar el diagnóstico."))
    elif has_car:
        checks.append(Check(True, "Datos en directo (modo coach)", f"Recibiendo datos: {where}  (versión del juego {version})"))
    else:
        checks.append(Check(None, "Datos en directo (modo coach)",
                            f"LMU está abierto (versión {version}) pero no estás en pista. Sal a pista y el coach "
                            "empezará a mostrar datos."))
    checks.append(Check(None, "Overlay del coach",
                        "Para verlo encima del juego, LMU debe estar en «Ventana sin bordes» (Borderless), "
                        "no en pantalla completa."))
    checks.append(Check(None, "App", f"LMU Coach {APP_VERSION} · {'instalada' if FROZEN else 'desarrollo'} · "
                                     f"datos en {DATA_DIR} · Windows {platform.version()}"))
    return checks


def report(checks: list[Check]) -> str:
    mark = {True: "OK ", False: "MAL", None: " ? "}
    return "\n".join(f"[{mark[c.ok]}] {c.title}: {c.detail}" for c in checks)
