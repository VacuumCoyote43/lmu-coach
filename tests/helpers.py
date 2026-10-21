"""Utilidades comunes de las pruebas: carpetas temporales y aislamiento de los datos de la app."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TempDirTest(unittest.TestCase):
    """Cada prueba tiene su carpeta temporal en self.tmp (se borra al acabar)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lmu_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def real_sessions(limit=None):
    """Sesiones reales de LMU de este PC (las de la copia propia y las de LMU), o [] si no hay."""
    try:
        from lmu_coach.paths import IMPORTED_DIR, INDEX_PATH
        from lmu_coach.sessions import SessionIndex, find_telemetry_dir
        idx = SessionIndex(find_telemetry_dir(), INDEX_PATH, IMPORTED_DIR)
        if not idx.sessions:
            idx.refresh(sync=False)
    except Exception:
        return []
    good = [s for s in idx.sessions if not s.error and s.valid_laps >= 3 and Path(s.path).exists()]
    good.sort(key=lambda s: (-s.valid_laps, s.path))
    return good[:limit] if limit else good


def offscreen():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if os.name == "nt":
        os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
