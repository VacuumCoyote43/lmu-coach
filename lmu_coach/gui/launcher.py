"""Arranque de la app con pantalla de carga.

La pantalla aparece nada más crear la QApplication; lo pesado (numpy, duckdb, pyqtgraph y la ventana)
se importa en un hilo aparte para que la animación no se congele, y la pantalla se cierra cuando
la lista de sesiones está lista.
"""
import importlib
import sys
import threading

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ..paths import ASSETS_DIR
from ..version import __version__
from . import theme
from .splash import Splash

MAX_SPLASH_S = 12      # si leer las sesiones tarda más, se abre la ventana igualmente (sigue en la barra de estado)


def _import_in_background(app, name):
    """Importa un módulo en otro hilo mientras el bucle de eventos sigue animando la pantalla."""
    result = {}

    def work():
        try:
            result["mod"] = importlib.import_module(name)
        except BaseException as e:      # se relanza en el hilo principal
            result["err"] = e

    th = threading.Thread(target=work, daemon=True)
    th.start()
    loop = QEventLoop()
    timer = QTimer(interval=15, timeout=lambda: th.is_alive() or loop.quit())
    timer.start()
    loop.exec()
    timer.stop()
    if "err" in result:
        raise result["err"]
    return result["mod"]


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LMU Coach")
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "icon.png")))
    theme.apply(app)

    splash = Splash(__version__)
    splash.set_icon(ASSETS_DIR / "icon.png")
    splash.show()
    app.processEvents()

    splash.set_status("Cargando módulos de análisis…")
    gui = _import_in_background(app, "lmu_coach.gui.main")

    splash.set_status("Preparando la ventana…")
    app.processEvents()
    w = gui.MainWindow()

    shown = False

    def show_window(*_):
        nonlocal shown
        if shown:
            return
        shown = True
        w.show()
        w.raise_()
        w.activateWindow()
        splash.finish()

    worker = w.worker
    if worker is None:
        show_window()
    else:
        splash.set_status("Buscando sesiones de LMU…")
        what = {"text": "Leyendo sesiones"}
        worker.stage.connect(lambda s: what.update(text=s))
        worker.progress.connect(lambda i, n: splash.set_status(f"{what['text']}… {i}/{n}", i / n if n else None))
        # Se comprueba el hilo en vez de esperar a su señal: puede haber terminado ya
        poll = QTimer(splash, interval=100, timeout=lambda: worker.isFinished() and show_window())
        poll.start()
        QTimer.singleShot(MAX_SPLASH_S * 1000, show_window)
    sys.exit(app.exec())
