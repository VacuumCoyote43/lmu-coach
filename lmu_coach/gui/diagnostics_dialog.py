"""Ventana de diagnóstico: qué falla cuando la app no carga nada del simulador."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from .. import diagnostics
from ..paths import load_settings, save_settings
from ..sessions import is_lmu_dir
from . import theme

ICON = {True: ("OK", theme.GREEN), False: ("MAL", theme.RED), None: ("INFO", theme.AMBER)}


def pick_lmu_dir(parent) -> Path | None:
    """Pide la carpeta de LMU. Acepta también UserData o Telemetry (sube hasta encontrar el .exe)."""
    start = load_settings().get("lmu_dir") or r"C:\Program Files (x86)\Steam\steamapps\common"
    chosen = QFileDialog.getExistingDirectory(parent, "Carpeta de Le Mans Ultimate (donde está «Le Mans Ultimate.exe»)",
                                              start)
    if not chosen:
        return None
    p = Path(chosen)
    for cand in (p, *p.parents):
        if is_lmu_dir(cand):
            settings = load_settings()
            settings["lmu_dir"] = str(cand)
            save_settings(settings)
            return cand
    QMessageBox.warning(parent, "Carpeta no válida",
                        f"En «{p}» no está «Le Mans Ultimate.exe».\n\nSuele estar en "
                        r"...\steamapps\common\Le Mans Ultimate (en Steam: clic derecho en el juego → "
                        "Administrar → Ver archivos locales).")
    return None


class DiagnosticsDialog(QDialog):
    lmu_dir_changed = Signal()

    def __init__(self, parent=None, headline: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Diagnóstico · LMU Coach")
        self.resize(880, 560)
        lay = QVBoxLayout(self)
        title = QLabel(headline or "Comprobando la conexión con Le Mans Ultimate")
        title.setObjectName("title")
        title.setWordWrap(True)
        lay.addWidget(title)
        self.body = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)

        row = QHBoxLayout()
        pick = QPushButton("📁  Elegir carpeta de LMU…")
        pick.clicked.connect(self._pick)
        again = QPushButton("⟳  Volver a comprobar")
        again.clicked.connect(self.refresh)
        logs = QPushButton("📄  Abrir registro")
        logs.setToolTip("Abre la carpeta con los registros de errores de la app y del coach")
        logs.clicked.connect(self._open_logs)
        copy = QPushButton("📋  Copiar informe")
        copy.setToolTip("Copia el resultado para enviarlo por WhatsApp/Discord")
        copy.clicked.connect(self._copy)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        for b in (pick, again, logs, copy):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.checks = []
        self.refresh()

    def refresh(self):
        while self.body.count():
            w = self.body.takeAt(0).widget()
            if w:
                w.setParent(None)  # que desaparezca ya, no al procesar deleteLater
                w.deleteLater()
        self.checks = diagnostics.run()
        for c in self.checks:
            label, color = ICON[c.ok]
            box = QFrame()
            box.setStyleSheet(f"QFrame {{ background: {theme.PANEL}; border-radius: 6px; }}")
            h = QHBoxLayout(box)
            # Etiqueta de color en vez de emoji: Windows pinta ✔/✖ como emoji y no respeta el color
            mark = QLabel(label)
            mark.setStyleSheet(f"color: #101114; background: {color}; border-radius: 4px; "
                               "font-weight: 700; font-size: 8pt; padding: 2px 0;")
            mark.setFixedWidth(34)
            mark.setAlignment(Qt.AlignCenter)
            h.addWidget(mark, 0, Qt.AlignTop)
            text = QLabel(f"<b>{c.title}</b><br>{c.detail.replace(chr(10), '<br>')}")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            text.setStyleSheet("background: transparent;")
            h.addWidget(text, 1)
            self.body.addWidget(box)
        self.body.addStretch(1)

    def _pick(self):
        if pick_lmu_dir(self):
            self.lmu_dir_changed.emit()
            self.refresh()

    def _open_logs(self):
        import os
        from ..log import LOG_DIR
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOG_DIR))

    def _copy(self):
        QApplication.clipboard().setText(diagnostics.report(self.checks))
        QMessageBox.information(self, "Copiado", "Informe copiado. Pégalo donde quieras (WhatsApp, Discord…).")
