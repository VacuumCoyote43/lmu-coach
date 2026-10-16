"""Aviso de actualización: novedades, descarga del instalador y reinicio."""
from PySide6.QtCore import QProcess, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from .. import updater
from ..paths import FROZEN, load_settings, save_settings
from ..version import __version__


class CheckWorker(QThread):
    """Consulta GitHub sin bloquear la ventana. Sin conexión, simplemente no avisa."""
    found = Signal(object)  # Release

    def run(self):
        try:
            rel = updater.check()
        except Exception:
            return
        if rel and load_settings().get("skip_version") != rel.version:
            self.found.emit(rel)


class _DownloadWorker(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, rel):
        super().__init__()
        self.rel = rel
        self.cancel = False

    def run(self):
        try:
            path = updater.download(self.rel, lambda d, t: self.progress.emit(d, t), lambda: self.cancel)
            self.done.emit(str(path))
        except Exception as e:
            self.failed.emit(str(e))


class UpdateDialog(QDialog):
    def __init__(self, parent, rel: updater.Release):
        super().__init__(parent)
        self.rel = rel
        self.worker = None
        self.setWindowTitle("Actualización disponible")
        self.resize(620, 480)
        lay = QVBoxLayout(self)
        title = QLabel(f"LMU Coach {rel.version} ya está disponible")
        title.setObjectName("title")
        lay.addWidget(title)
        sub = QLabel(f"Tienes la {__version__}.  ·  Instalador: {rel.asset_name} ({rel.asset_size / 1e6:.0f} MB)")
        sub.setObjectName("subtitle")
        lay.addWidget(sub)
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.notes or "_Sin notas de versión._")
        lay.addWidget(notes, 1)
        self.bar = QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setObjectName("subtitle")
        lay.addWidget(self.status)

        row = QHBoxLayout()
        self.skip_btn = QPushButton("Saltar esta versión")
        self.web_btn = QPushButton("Ver en GitHub")
        self.later_btn = QPushButton("Más tarde")
        self.install_btn = QPushButton("⬇  Descargar e instalar")
        self.install_btn.setObjectName("coach")
        if not FROZEN:  # en desarrollo no hay instalación que actualizar
            self.install_btn.setEnabled(False)
            self.install_btn.setToolTip("Solo en la app instalada. En desarrollo, actualiza con git pull.")
        row.addWidget(self.skip_btn)
        row.addWidget(self.web_btn)
        row.addStretch(1)
        row.addWidget(self.later_btn)
        row.addWidget(self.install_btn)
        lay.addLayout(row)

        self.skip_btn.clicked.connect(self._skip)
        self.web_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(rel.url)))
        self.later_btn.clicked.connect(self.reject)
        self.install_btn.clicked.connect(self._install)

    def _skip(self):
        s = load_settings()
        s["skip_version"] = self.rel.version
        save_settings(s)
        self.reject()

    def _install(self):
        self.install_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.bar.show()
        self.bar.setValue(0)
        self.status.setText("Descargando…")
        self.worker = _DownloadWorker(self.rel)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._run_installer)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, done, total):
        if total:
            self.bar.setMaximum(total)
            self.bar.setValue(done)
            self.status.setText(f"Descargando… {done / 1e6:.0f} / {total / 1e6:.0f} MB")

    def _failed(self, msg):
        self.bar.hide()
        self.install_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.status.setText("")
        if "cancelada" not in msg:
            QMessageBox.warning(self, "No se pudo descargar", f"{msg}\n\nPuedes descargarla desde «Ver en GitHub».")

    def _run_installer(self, path):
        self.status.setText("Abriendo el instalador… la app se cerrará y se volverá a abrir al terminar.")
        # /SILENT: instala con barra de progreso, sin preguntas; el instalador vuelve a abrir la app
        ok = QProcess.startDetached(path, ["/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS"])
        if not ok:
            QMessageBox.warning(self, "No se pudo abrir el instalador", f"Ábrelo a mano:\n{path}")
            return
        self.accept()
        if self.parent():
            self.parent().close()  # cierra también el overlay del coach si estaba abierto
        QApplication.instance().quit()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel = True
            self.worker.wait(3000)
        super().reject()
