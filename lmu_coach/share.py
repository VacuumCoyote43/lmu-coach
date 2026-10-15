"""Exportar e importar sesiones (.lmusession) para compartirlas con otros pilotos.

Un .lmusession es un zip con:
  session.duckdb  – el archivo de telemetría de LMU, tal cual
  info.json       – resumen (piloto, circuito, coche, mejor vuelta...) para mostrarlo sin abrir la sesión
También se aceptan al importar un .duckdb suelto o un .zip con un .duckdb dentro.
"""
import json
import re
import shutil
import time
import zipfile
from dataclasses import asdict
from pathlib import Path

from .sessions import SessionInfo, read_session_info

EXTENSION = ".lmusession"
FORMAT_VERSION = 1


class ShareError(Exception):
    pass


class AlreadyImported(ShareError):
    def __init__(self, path: Path):
        super().__init__("Esta sesión ya está importada.")
        self.path = path


def suggested_name(info: SessionInfo) -> str:
    """Nombre de archivo legible: Piloto_Circuito_Coche_2026-10-15_2007.lmusession"""
    parts = [info.driver, info.track, info.car, info.recorded.replace(":", "").replace(" ", "_")]
    name = "_".join(re.sub(r"[^\w-]+", "-", p).strip("-") for p in parts if p)
    return (name or "sesion") + EXTENSION


def export_session(info: SessionInfo, dest: Path) -> Path:
    src = Path(info.path)
    if Path(str(src) + ".wal").exists():
        raise ShareError("LMU todavía está grabando esta sesión. Sal de la sesión en el juego y vuelve a intentarlo.")
    dest = Path(dest)
    if dest.suffix.lower() != EXTENSION:
        dest = dest.with_suffix(EXTENSION)
    meta = {k: v for k, v in asdict(info).items() if k not in ("path", "mtime", "size", "error", "imported")}
    meta.update(format=FORMAT_VERSION, app="LMU Coach", original_name=src.name,
                exported_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("info.json", json.dumps(meta, ensure_ascii=False, indent=2))
        z.write(src, "session.duckdb")
    tmp.replace(dest)
    return dest


def import_session(src: Path, imported_dir: Path) -> SessionInfo:
    """Copia la sesión a la carpeta de importadas y devuelve su resumen. Lanza ShareError si no es válida."""
    src = Path(src)
    imported_dir = Path(imported_dir)
    imported_dir.mkdir(parents=True, exist_ok=True)
    tmp = imported_dir / f".importando_{int(time.time() * 1000)}.duckdb"
    try:
        name = _extract(src, tmp)
        target = imported_dir / name
        if target.exists():
            if target.stat().st_size == tmp.stat().st_size:
                raise AlreadyImported(target)
            target = imported_dir / f"{Path(name).stem}_{int(time.time())}.duckdb"
        info = read_session_info(tmp, imported=True)
        if info.error:
            raise ShareError(f"El archivo no es una sesión de LMU válida.\n\n{info.error}")
        tmp.replace(target)
        return read_session_info(target, imported=True)
    finally:
        tmp.unlink(missing_ok=True)


def _extract(src: Path, out: Path) -> str:
    """Escribe el .duckdb de src en out y devuelve el nombre con el que guardarlo."""
    if src.suffix.lower() == ".duckdb":
        shutil.copyfile(src, out)
        return src.name
    if not zipfile.is_zipfile(src):
        raise ShareError("Formato no reconocido. Elige un archivo .lmusession, .zip o .duckdb.")
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        member = "session.duckdb" if "session.duckdb" in names else next(
            (n for n in names if n.lower().endswith(".duckdb")), None)
        if member is None:
            raise ShareError("El archivo no contiene ninguna sesión (.duckdb).")
        original = Path(member).name
        if "info.json" in names:
            try:
                original = json.loads(z.read("info.json")).get("original_name") or original
            except (ValueError, KeyError):
                pass
        with z.open(member) as fsrc, open(out, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, 1024 * 1024)
    return re.sub(r'[\\/:*?"<>|]+', "_", Path(original).name)


def remove_imported(info: SessionInfo):
    if not info.imported:
        raise ShareError("Solo se pueden quitar sesiones importadas.")
    Path(info.path).unlink(missing_ok=True)
