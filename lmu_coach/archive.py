"""Copia propia de las sesiones de LMU.

Al buscar sesiones nuevas, cada archivo de telemetría terminado (.duckdb) se copia a una carpeta de
la app. Así no se pierde nada aunque LMU borre o rote sus archivos, se reinstale el juego o se cambie
de PC: la app lee primero de su copia. Nunca se modifica ni se borra nada de la carpeta de LMU.
"""
import ctypes
import shutil
import time
from pathlib import Path

from .paths import load_settings, save_settings

STABLE_S = 30          # un archivo que ha cambiado hace menos de esto puede estar grabándose todavía
MARGIN_BYTES = 1 << 30 # deja al menos 1 GB libre en el disco


def documents_dir() -> Path:
    """Carpeta «Documentos» real del usuario (aunque esté movida o en OneDrive)."""
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:   # CSIDL_PERSONAL
            return Path(buf.value)
    except (AttributeError, OSError):
        pass
    return Path.home() / "Documents"


def default_dir() -> Path:
    return documents_dir() / "LMU Coach" / "Sesiones"


def archive_dir() -> Path:
    custom = load_settings().get("archive_dir")
    return Path(custom) if custom else default_dir()


def set_archive_dir(path: Path | None):
    s = load_settings()
    if path is None:
        s.pop("archive_dir", None)
    else:
        s["archive_dir"] = str(path)
    save_settings(s)


def _wal(f: Path) -> Path:
    """DuckDB guarda en «archivo.duckdb.wal» lo que aún no ha pasado al archivo principal."""
    return f.with_name(f.name + ".wal")


def _size(f: Path) -> int | None:
    try:
        return f.stat().st_size
    except OSError:
        return None


def pending(lmu_dir: Path, dest: Path) -> list[Path]:
    """Sesiones de LMU terminadas que aún no están (completas e iguales) en la copia."""
    if not lmu_dir or not Path(lmu_dir).is_dir():
        return []
    now = time.time()
    out = []
    for f in Path(lmu_dir).glob("*.duckdb"):
        try:
            mtime = max(f.stat().st_mtime, _wal(f).stat().st_mtime if _wal(f).exists() else 0)
        except OSError:
            continue
        if now - mtime < STABLE_S:
            continue
        copy = dest / f.name
        same_db = _size(copy) == _size(f)
        same_wal = _size(_wal(copy)) == _size(_wal(f))      # None == None si ninguno tiene .wal
        if not (same_db and same_wal):
            out.append(f)
    return sorted(out, key=lambda f: f.stat().st_mtime)


def sync(lmu_dir: Path, dest: Path | None = None, progress=None) -> dict:
    """Copia lo nuevo. Devuelve {'copied': n, 'bytes': b, 'error': texto o None}."""
    dest = Path(dest) if dest else archive_dir()
    todo = pending(lmu_dir, dest)
    result = {"copied": 0, "bytes": 0, "error": None, "dir": str(dest)}
    if not todo:
        return result
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        result["error"] = f"No puedo crear {dest}: {e}"
        return result
    for i, f in enumerate(todo):
        size = (_size(f) or 0) + (_size(_wal(f)) or 0)
        try:
            if shutil.disk_usage(dest).free < size + MARGIN_BYTES:
                result["error"] = "No queda espacio en el disco de la copia de sesiones"
                break
            # el .duckdb y su .wal (si lo hay) van juntos; primero a temporales: nunca queda una copia a medias
            pairs = [(f, dest / f.name)]
            if _wal(f).exists():
                pairs.append((_wal(f), _wal(dest / f.name)))
            for src, dst in pairs:
                tmp = dst.with_name(dst.name + ".copiando")
                shutil.copy2(src, tmp)
                tmp.replace(dst)
            if not _wal(f).exists() and _wal(dest / f.name).exists():
                _wal(dest / f.name).unlink()     # LMU ya lo pasó al archivo principal
            result["copied"] += 1
            result["bytes"] += size
        except OSError as e:
            result["error"] = f"{f.name}: {e}"
        if progress:
            progress(i + 1, len(todo))
    return result


def stats(dest: Path | None = None) -> tuple[int, int]:
    """(nº de sesiones, bytes) en la copia."""
    dest = Path(dest) if dest else archive_dir()
    files = list(dest.glob("*.duckdb")) if dest.is_dir() else []
    return len(files), sum(f.stat().st_size for f in files)
