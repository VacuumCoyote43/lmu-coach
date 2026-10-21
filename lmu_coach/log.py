"""Registro de errores en archivo: %LOCALAPPDATA%\\LMU Coach\\logs\\app.log (la app) y coach.log (el overlay).

- Recoge los errores no controlados de la app, del coach y de sus hilos (antes se perdían en silencio).
- warn_once(): para fallos que se pueden repetir muchas veces por segundo (lectura en directo del juego):
  se escribe el primero con todo el detalle y luego solo cuántas veces se ha repetido al cerrar.
- Archivos rotativos (1 MB × 3), así nunca crecen sin límite.
"""
import logging
import logging.handlers
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from .paths import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
log = logging.getLogger("lmu_coach")
_repeats = Counter()
_name = None


def log_path(name: str | None = None) -> Path:
    return LOG_DIR / f"{name or _name or 'app'}.log"


def setup(name: str):
    """Activa el registro en LOG_DIR/<name>.log y captura los errores no controlados. Se llama una vez al arrancar."""
    global _name
    if _name:
        return log
    _name = name
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(log_path(name), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())      # sin permiso de escritura: la app sigue igual
    log.setLevel(logging.INFO)
    from .version import __version__
    log.info("---- LMU Coach %s (%s) · Python %s", __version__, name, sys.version.split()[0])

    previous = sys.excepthook

    def hook(t, v, tb):
        log.error("Error no controlado", exc_info=(t, v, tb))
        previous(t, v, tb)

    sys.excepthook = hook
    threading.excepthook = lambda a: log.error("Error no controlado en el hilo %s", a.thread.name if a.thread else "?",
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    import atexit
    atexit.register(_summary)
    return log


def warn_once(key: str, msg: str, *args):
    """Aviso con el detalle del error en curso, solo la primera vez para esa clave."""
    _repeats[key] += 1
    if _repeats[key] == 1:
        log.warning(msg, *args, exc_info=sys.exc_info()[0] is not None)


def _summary():
    many = {k: n for k, n in _repeats.items() if n > 1}
    if many:
        log.info("Avisos repetidos en esta sesión: %s", ", ".join(f"{k} ×{n}" for k, n in sorted(many.items())))


def recent_problems(hours: float = 24) -> int:
    """Errores y avisos de las últimas horas en todos los registros (para el diagnóstico)."""
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - hours * 3600))
    n = 0
    for f in LOG_DIR.glob("*.log*") if LOG_DIR.is_dir() else []:
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if line[:19] >= since and (" ERROR " in line or " WARNING " in line):
                    n += 1
        except OSError:
            continue
    return n
