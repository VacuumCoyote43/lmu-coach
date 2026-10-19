"""Ventana «Copia de seguridad»: la copia propia de las sesiones."""
import os
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from .. import archive
from . import theme


def _gb(b: int) -> str:
    return f"{b / 2**30:.1f} GB" if b >= 2**30 else f"{b / 2**20:.0f} MB"


class BackupDialog(QDialog):
    archive_changed = Signal()      # la carpeta de la copia ha cambiado: hay que releer las sesiones

    def __init__(self, parent, last_sync=None):
        super().__init__(parent)
        self.setWindowTitle("Copia de seguridad")
        self.resize(720, 280)
        lay = QVBoxLayout(self)
        head = QLabel("💾  Copia de seguridad")
        head.setObjectName("title")
        lay.addWidget(head)

        box = QGroupBox("Copia propia de tus sesiones")
        bl = QVBoxLayout(box)
        bl.addWidget(self._note(
            "Cada vez que la app busca sesiones nuevas, copia aquí las que LMU ha terminado de grabar. "
            "La app lee de esta copia: aunque LMU borre sus archivos, reinstales el juego o cambies de PC "
            "(copiando esta carpeta), no pierdes nada. La carpeta de LMU nunca se modifica."))
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self.info)
        row = QHBoxLayout()
        open_btn = QPushButton("📂  Abrir carpeta")
        open_btn.clicked.connect(lambda: os.startfile(str(archive.archive_dir())) if archive.archive_dir().is_dir() else None)
        change = QPushButton("Cambiar carpeta…")
        change.clicked.connect(self._change)
        row.addWidget(open_btn)
        row.addWidget(change)
        row.addStretch(1)
        bl.addLayout(row)
        lay.addWidget(box)

        lay.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        self.last_sync = last_sync
        self._refresh()

    @staticmethod
    def _note(text):
        lab = QLabel(text)
        lab.setObjectName("subtitle")
        lab.setWordWrap(True)
        return lab

    def _refresh(self):
        d = archive.archive_dir()
        n, size = archive.stats(d)
        free = shutil.disk_usage(d if d.exists() else d.anchor).free
        txt = (f"<b>{d}</b><br>{n} sesiones · {_gb(size)} · quedan {_gb(free)} libres en el disco")
        ls = self.last_sync
        if ls:
            if ls.get("error"):
                txt += f"<br><span style='color:{theme.RED}'>Última copia con problemas: {ls['error']}</span>"
            elif ls.get("copied"):
                txt += f"<br><span style='color:{theme.GREEN}'>Última búsqueda: {ls['copied']} sesiones nuevas copiadas</span>"
            else:
                txt += "<br>Última búsqueda: nada nuevo que copiar"
        self.info.setText(txt)

    def _change(self):
        old = archive.archive_dir()
        chosen = QFileDialog.getExistingDirectory(self, "Carpeta para la copia de tus sesiones", str(old.parent))
        if not chosen:
            return
        new = Path(chosen)
        if new.resolve() == old.resolve():
            return
        files = [f for f in old.glob("*.duckdb*")] if old.is_dir() else []
        if files and QMessageBox.question(
                self, "Mover la copia",
                f"¿Muevo las {sum(1 for f in files if f.suffix == '.duckdb')} sesiones ya copiadas a «{new}»?\n\n"
                "Si dices que no, se quedan donde están y la nueva carpeta se rellena de nuevo desde LMU "
                "(solo con lo que LMU todavía conserve).") == QMessageBox.Yes:
            new.mkdir(parents=True, exist_ok=True)
            for f in files:
                try:
                    shutil.move(str(f), str(new / f.name))
                except OSError as e:
                    QMessageBox.warning(self, "No se pudo mover", f"{f.name}: {e}")
                    break
        archive.set_archive_dir(new)
        self.last_sync = None
        self._refresh()
        self.archive_changed.emit()
