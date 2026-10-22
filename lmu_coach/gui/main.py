"""Ventana principal: barra de herramientas, lista de sesiones, vista de sesión y lanzador del modo coach."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter,
    QStackedWidget, QToolBar, QWidget,
)

from . import car_pix, theme
from .common import IMPORTABLE, short_track
from .diagnostics_dialog import DiagnosticsDialog
from .session_list import SessionList
from .session_view import SessionView
from .update_dialog import CheckWorker, UpdateDialog
from .. import share
from ..laps import fmt_time
from ..paths import ASSETS_DIR, IMPORTED_DIR, INDEX_PATH, PROJECT_ROOT, coach_command
from ..sessions import SessionIndex, find_telemetry_dir

# Compatibilidad: antes todo esto vivía en gui.main y otros módulos/pruebas lo importan de aquí
from .common import (  # noqa: F401
    SESSION_TYPES, SHORT_TRACKS, SortItem, car_label, fmt_sec, item, make_table, section, sitem,
)


class IndexWorker(QThread):
    progress = Signal(int, int)
    stage = Signal(str)
    done = Signal(list)

    def __init__(self, index: SessionIndex):
        super().__init__()
        self.index = index

    def run(self):
        self.done.emit(self.index.refresh(lambda i, n: self.progress.emit(i, n), lambda s: self.stage.emit(s)))


# --------------------------------------------------------------------------- ventana

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Coach")
        self.resize(1500, 920)
        self.index = SessionIndex(find_telemetry_dir(), INDEX_PATH, IMPORTED_DIR)
        self.coach = None
        self.worker = None
        # Archivos pasados al abrir (doble clic en un .lmusession) o soltados mientras se indexa
        self._pending_imports = [a for a in sys.argv[1:] if Path(a).suffix.lower() in IMPORTABLE and Path(a).is_file()]
        self._select_after = None
        self._diag_auto_shown = False
        self.setAcceptDrops(True)

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        self.coach_btn = QPushButton("▶  Iniciar modo coach")
        self.coach_btn.setObjectName("coach")
        self.coach_btn.clicked.connect(self._toggle_coach)
        tb.addWidget(self.coach_btn)
        self.coach_state = QLabel("LMU en «ventana sin bordes»")
        self.coach_state.setObjectName("subtitle")
        self.coach_state.setToolTip("El overlay se muestra encima de LMU si el juego está en modo ventana sin bordes")
        tb.addWidget(self.coach_state)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")
        tb.addWidget(spacer)
        self.update_btn = QPushButton()
        self.update_btn.setObjectName("coach")
        self.update_btn.clicked.connect(self._show_update)
        self.update_action = tb.addWidget(self.update_btn)
        self.update_action.setVisible(False)  # solo aparece si hay versión nueva
        self._release = None
        self.home_btn = QPushButton("🏠")
        self.home_btn.setObjectName("icon")
        self.home_btn.setToolTip("Inicio: tu última sesión, tu objetivo más cercano y la semana")
        self.home_btn.clicked.connect(self.show_home)
        tb.addWidget(self.home_btn)
        self.progress_btn = QPushButton("📈  Mi progreso")
        self.progress_btn.setToolTip("Tu evolución en cada circuito y coche, tu vuelta ideal y tus objetivos")
        self.progress_btn.clicked.connect(self._show_progress)
        tb.addWidget(self.progress_btn)
        self.settings_btn = QPushButton("⚙  Ajustes")
        self.settings_btn.setToolTip("Voz, overlay y qué dice el coach: spotter, ingeniero, coach y coche")
        self.settings_btn.clicked.connect(lambda: self.show_settings())
        tb.addWidget(self.settings_btn)
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setObjectName("icon")
        self.refresh_btn.setToolTip("Buscar sesiones nuevas (y copiarlas a tu carpeta)")
        self.refresh_btn.clicked.connect(self.refresh)
        tb.addWidget(self.refresh_btn)
        # lo que se usa de vez en cuando, en un menú
        more = QMenu(self)
        more.addAction("⬇  Importar sesión…", self._choose_import).setToolTip(
            "Abre un .lmusession que te haya pasado otro piloto (también puedes arrastrarlo aquí)")
        more.addAction("💾  Copia de seguridad…", self._show_backup)
        more.addAction("🩺  Diagnóstico…", lambda: self.show_diagnostics())
        more.addSeparator()
        more.addAction("👋  Asistente de bienvenida…", self.show_welcome)
        more.setToolTipsVisible(True)
        self.more_btn = QPushButton("⋯")
        self.more_btn.setObjectName("icon")
        self.more_btn.setToolTip("Importar sesión, copia de seguridad, diagnóstico…")
        self.more_btn.setMenu(more)
        tb.addWidget(self.more_btn)

        self.list = SessionList()
        self.view = SessionView(lambda: self.index)
        self.stack = QStackedWidget()
        from .home import HomePage
        self.home = HomePage()
        self.home.open_session.connect(self._open_from_home)
        self.home.start_coach.connect(self._toggle_coach)
        self.home.show_progress.connect(self._show_progress)
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.view)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.list)
        split.addWidget(self.stack)
        split.setSizes([600, 900])
        self.setCentralWidget(split)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.list.selected.connect(self._open)
        self.view.status.connect(lambda s: self.statusBar().showMessage(s))
        self.view.removed.connect(self._imported_removed)

        if self.index.sessions:
            self.list.set_sessions(self.index.sessions)
            self.home.set_sessions(self.index.sessions)
        self.refresh()
        # Buscar actualizaciones en segundo plano, cuando la ventana ya está a la vista
        self.update_worker = CheckWorker()
        self.update_worker.found.connect(self._update_found)
        QTimer.singleShot(3000, self.update_worker.start)

    def _open(self, info):
        self.stack.setCurrentWidget(self.view)
        self.view.open_session(info)

    def refresh(self):
        if self.worker and self.worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage(f"Leyendo sesiones de {self.index.dir}…")
        self.worker = IndexWorker(self.index)
        self.worker.progress.connect(lambda i, n: (self.progress.setMaximum(n), self.progress.setValue(i)))
        self.worker.stage.connect(lambda s: self.statusBar().showMessage(f"{s}…"))
        self.worker.done.connect(self._indexed)
        self.worker.start()
        # con LMU abierto, aprender su lista completa de decoraciones para poner la imagen de cada coche
        if not (getattr(self, "car_worker", None) and self.car_worker.isRunning()):
            self.car_worker = car_pix.GameListWorker()
            self.car_worker.learned.connect(self._cars_learned)
            self.car_worker.start()

    def _cars_learned(self):
        """Poner las imágenes que faltaban sin rehacer la lista (se conserva la selección)."""
        car_pix.forget_missing()
        t = self.list.table
        for r in range(t.rowCount()):
            it = t.item(r, 2)
            if it is not None and it.icon().isNull():
                pix = car_pix.pixmap(it.data(Qt.UserRole), "thumb", 26)
                if pix:
                    it.setIcon(QIcon(pix))
                    it.setText("")
        info = getattr(self.view, "sd", None)
        if info is not None and self.view.car_img.isHidden():
            pix = car_pix.pixmap(info.info.car, "large", 84)
            if pix:
                self.view.car_img.setPixmap(pix)
                self.view.car_img.show()

    def _indexed(self, sessions):
        self.progress.hide()
        self.refresh_btn.setEnabled(True)
        self.list.set_sessions(sessions)
        self.home.set_sessions(sessions)
        errors = sum(1 for s in sessions if s.error)
        msg = f"{len(sessions)} sesiones"
        ls = self.index.last_sync
        if ls and ls.get("copied"):
            msg += f"  ·  {ls['copied']} copiadas a tu carpeta"
        if ls and ls.get("error"):
            msg += f"  ·  ⚠ copia: {ls['error']}"

        if errors:
            msg += f"  ·  {errors} no se pudieron leer (¿LMU las está grabando ahora?)"
        self.statusBar().showMessage(msg, 8000)
        if self._select_after:
            path, self._select_after = self._select_after, None
            self.list.select_path(path)
        if self._pending_imports:
            files, self._pending_imports = self._pending_imports, []
            QTimer.singleShot(0, lambda: self.import_files(files))
        elif self._welcome_pending():
            QTimer.singleShot(300, self.show_welcome)
        elif not any(not s.imported and not s.error for s in sessions) and not self._diag_auto_shown:
            # Sin ninguna sesión propia: casi siempre es la carpeta o la grabación de telemetría de LMU
            self._diag_auto_shown = True
            self.home.set_message("No hay sesiones de LMU todavía. Pulsa ⋯ › 🩺 Diagnóstico para ver qué falta.")
            QTimer.singleShot(0, lambda: self.show_diagnostics("No encuentro sesiones de Le Mans Ultimate"))
        else:
            QTimer.singleShot(300, self._show_whats_new)

    # --- actualizaciones -------------------------------------------------

    def _update_found(self, rel):
        self._release = rel
        self.update_btn.setText(f"⬆  Actualizar a {rel.version}")
        self.update_action.setVisible(True)
        self.statusBar().showMessage(f"Hay una versión nueva de LMU Coach: {rel.version}", 15000)

    def _show_update(self):
        if self._release:
            UpdateDialog(self, self._release).exec()

    def _show_progress(self):
        from .progress import MyProgressDialog
        MyProgressDialog(self, self.index.sessions).exec()

    # --- ajustes y bienvenida -------------------------------------------------

    def show_settings(self, tab: str | None = None):
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, tab)
        dlg.archive_requested.connect(self._show_backup)
        dlg.wizard_requested.connect(lambda: (dlg.accept(), QTimer.singleShot(0, self.show_welcome)))
        dlg.exec()

    def _welcome_pending(self):
        from .welcome import needs_welcome
        if os.environ.get("LMU_COACH_NO_WELCOME") or getattr(self, "_welcome_shown", False):
            return False
        return needs_welcome()

    def _show_whats_new(self):
        """Después de actualizar, una vez: qué hay de nuevo."""
        from .. import changelog
        from ..paths import load_settings, save_settings
        from ..version import __version__
        if os.environ.get("LMU_COACH_NO_WELCOME") or getattr(self, "_news_shown", False):
            return
        self._news_shown = True
        st = load_settings()
        seen = st.get("seen_version")
        if seen == __version__:
            return
        st["seen_version"] = __version__
        save_settings(st)
        news = changelog.since(seen, __version__)
        if not seen or not news:        # instalación nueva: el asistente ya lo cuenta
            return
        html = "".join(f"<h3>{v}</h3><ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>" for v, items in news)
        box = QMessageBox(self)
        box.setWindowTitle("Novedades de LMU Coach")
        box.setTextFormat(Qt.RichText)
        box.setText(f"<h2>Novedades de la versión {__version__}</h2>{html}")
        box.exec()

    def show_welcome(self):
        from .welcome import WelcomeWizard
        self._welcome_shown = True
        wiz = WelcomeWizard(self)
        wiz.lmu_dir_changed.connect(self._lmu_dir_changed)
        wiz.archive_changed.connect(self._archive_changed)
        wiz.exec()

    # --- diagnóstico ------------------------------------------------------

    def _show_backup(self):
        from .backup_dialog import BackupDialog
        dlg = BackupDialog(self, self.index.last_sync)
        dlg.archive_changed.connect(self._archive_changed)
        dlg.exec()

    def _archive_changed(self):
        from .. import archive
        self.index.archive_dir = archive.archive_dir()
        self.refresh()

    def show_diagnostics(self, headline: str = ""):
        dlg = DiagnosticsDialog(self, headline)
        dlg.lmu_dir_changed.connect(self._lmu_dir_changed)
        dlg.exec()

    def _lmu_dir_changed(self):
        self.index.dir = find_telemetry_dir()
        self.view.cache.clear()
        self.refresh()

    # --- importar ---------------------------------------------------------

    def _choose_import(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Importar sesión", QStandardPaths.writableLocation(QStandardPaths.DownloadLocation),
            f"Sesiones (*{share.EXTENSION} *.zip *.duckdb)")
        if files:
            self.import_files(files)

    def import_files(self, files):
        if self.worker and self.worker.isRunning():
            self._pending_imports += list(files)  # se importan al terminar de indexar
            return
        ok, msgs, last = [], [], None
        for f in files:
            try:
                info = share.import_session(Path(f), IMPORTED_DIR)
                ok.append(info)
                last = info.path
            except share.AlreadyImported as e:
                msgs.append(f"{Path(f).name}: ya estaba importada.")
                last = str(e.path)
            except (share.ShareError, OSError) as e:
                msgs.append(f"{Path(f).name}: {e}")
        if ok:
            names = ", ".join(f"{i.driver or 'piloto'} en {short_track(i.track)} ({fmt_time(i.best)})" for i in ok)
            self.statusBar().showMessage(f"Importada: {names}", 10000)
        if msgs:
            QMessageBox.warning(self, "Importar sesión", "\n\n".join(msgs))
        if last:
            self._select_after = last
            self.refresh()

    def _imported_removed(self, path):
        self.stack.setCurrentIndex(0)
        self.statusBar().showMessage("Sesión importada quitada", 6000)
        self.refresh()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in IMPORTABLE
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if Path(u.toLocalFile()).suffix.lower() in IMPORTABLE]
        if files:
            self.import_files(files)

    # --- modo coach ------------------------------------------------------

    def _toggle_coach(self):
        if self.coach and self.coach.state() != QProcess.NotRunning:
            self.coach.terminate()
            if not self.coach.waitForFinished(1500):
                self.coach.kill()
            return
        program, args = coach_command()
        self.coach = QProcess(self)
        self.coach.setWorkingDirectory(str(PROJECT_ROOT))
        self.coach.finished.connect(self._coach_stopped)
        self.coach.errorOccurred.connect(lambda e: self._coach_stopped())
        self.coach.start(program, args)
        if self.coach.waitForStarted(3000):
            self._set_coach_ui(True)

    def _coach_stopped(self, *args):
        self._set_coach_ui(False)

    def show_home(self):
        self.list.table.clearSelection()
        self.home.set_sessions(self.index.sessions)     # p. ej. un objetivo nuevo
        self.stack.setCurrentWidget(self.home)

    def _open_from_home(self, info):
        self.list.select_path(info.path)
        if self.stack.currentWidget() is not self.view:
            self._open(info)

    def _set_coach_ui(self, running):
        self.home.set_coach_running(running)
        self.coach_btn.setText("■  Detener modo coach" if running else "▶  Iniciar modo coach")
        self.coach_btn.setProperty("running", "true" if running else "false")
        self.coach_btn.style().unpolish(self.coach_btn)
        self.coach_btn.style().polish(self.coach_btn)
        self.coach_state.setText("Coach activo: sal a pista" if running else "LMU en «ventana sin bordes»")

    def closeEvent(self, e):
        if self.coach and self.coach.state() != QProcess.NotRunning:
            self.coach.kill()
            self.coach.waitForFinished(1000)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LMU Coach")
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "icon.png")))
    theme.apply(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
