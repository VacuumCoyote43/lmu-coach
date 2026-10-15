"""Rutas de datos y cómo lanzar el coach, tanto en desarrollo como en la app instalada (.exe)."""
import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)  # True dentro del .exe de PyInstaller
PROJECT_ROOT = Path(__file__).resolve().parent.parent

if FROZEN:
    # La carpeta de instalación puede no ser escribible: los datos van al perfil del usuario
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LMU Coach"
    CONFIG_PATH = DATA_DIR / "config.json"
else:
    DATA_DIR = PROJECT_ROOT / "data"
    CONFIG_PATH = PROJECT_ROOT / "config.json"

ASSETS_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)) / "assets"
LAPS_DIR = DATA_DIR / "laps"
DEMO_LAPS_DIR = DATA_DIR / "demo_laps"
INDEX_PATH = DATA_DIR / "sessions_index.json"
IMPORTED_DIR = DATA_DIR / "imported_sessions"


def coach_command(demo: bool = False) -> tuple[str, list[str]]:
    """Programa y argumentos para abrir el overlay del coach en un proceso aparte."""
    extra = ["--demo"] if demo else []
    if FROZEN:
        return sys.executable, ["--coach", *extra]
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else exe), ["-m", "lmu_coach", *extra]
