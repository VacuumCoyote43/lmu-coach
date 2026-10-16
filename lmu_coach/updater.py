"""Comprobar si hay una versión nueva en GitHub Releases y descargar su instalador."""
import json
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .version import GITHUB_REPO, __version__

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
# Solo se descargan instaladores servidos por GitHub
ALLOWED_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}


@dataclass
class Release:
    version: str
    url: str           # página de la release
    notes: str
    asset_name: str
    asset_url: str
    asset_size: int


def parse_version(text: str) -> tuple:
    """'v1.10.2' -> (1, 10, 2). Lo que no sea número se ignora."""
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3]) or (0,)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"LMU-Coach/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def latest_release(timeout: float = 6.0) -> Release | None:
    """La última release publicada con un instalador .exe, o None si no hay. Lanza OSError sin conexión."""
    with _get(API_URL, timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    asset = next((a for a in data.get("assets", [])
                  if a.get("name", "").lower().endswith(".exe") and "setup" in a.get("name", "").lower()), None)
    if not asset:
        return None
    return Release(
        version=data.get("tag_name", "").lstrip("v"),
        url=data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"),
        notes=data.get("body") or "",
        asset_name=asset["name"],
        asset_url=asset["browser_download_url"],
        asset_size=int(asset.get("size", 0)),
    )


def check() -> Release | None:
    """La release si es más nueva que la versión instalada; si no, None."""
    rel = latest_release()
    return rel if rel and is_newer(rel.version) else None


def download(rel: Release, progress=None, cancelled=lambda: False) -> Path:
    """Descarga el instalador a una carpeta temporal. progress(bytes, total). Devuelve la ruta."""
    if urlparse(rel.asset_url).hostname not in ALLOWED_HOSTS:
        raise OSError(f"Descarga rechazada: {rel.asset_url} no es de GitHub")
    folder = Path(tempfile.mkdtemp(prefix="lmucoach_update_"))
    dest = folder / Path(rel.asset_name).name
    with _get(rel.asset_url, 30) as r:
        if urlparse(r.geturl()).hostname not in ALLOWED_HOSTS:  # tras las redirecciones
            raise OSError(f"Descarga rechazada: redirigida a {r.geturl()}")
        total = int(r.headers.get("Content-Length") or rel.asset_size or 0)
        done = 0
        with open(dest, "wb") as f:
            while chunk := r.read(256 * 1024):
                if cancelled():
                    raise OSError("Descarga cancelada")
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if rel.asset_size and dest.stat().st_size != rel.asset_size:
        raise OSError("La descarga está incompleta. Inténtalo de nuevo.")
    return dest
