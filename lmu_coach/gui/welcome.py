"""Asistente de bienvenida: la primera vez que se abre la app, deja LMU, la voz y la copia listos.

Se puede volver a pasar desde Ajustes › General.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWizard, QWizardPage,
)

from .. import archive, diagnostics
from .. import config as C
from ..paths import load_settings, save_settings
from ..speech import Speaker
from . import theme
from .diagnostics_dialog import ICON, pick_lmu_dir


def needs_welcome() -> bool:
    return not load_settings().get("welcome_done")


def mark_done():
    s = load_settings()
    s["welcome_done"] = True
    save_settings(s)


def _text(html):
    lb = QLabel(html)
    lb.setWordWrap(True)
    lb.setTextFormat(Qt.RichText)
    lb.setOpenExternalLinks(True)
    return lb


def _check_row(ok, title, detail):
    label, color = ICON[ok]
    box = QFrame()
    box.setStyleSheet(f"QFrame {{ background: {theme.PANEL}; border-radius: 6px; }}")
    h = QHBoxLayout(box)
    mark = QLabel(label)
    mark.setStyleSheet(f"color: #101114; background: {color}; border-radius: 4px; "
                       "font-weight: 700; font-size: 8pt; padding: 2px 0;")
    mark.setFixedWidth(34)
    mark.setAlignment(Qt.AlignCenter)
    h.addWidget(mark, 0, Qt.AlignTop)
    t = QLabel(f"<b>{title}</b><br>{detail}")
    t.setWordWrap(True)
    t.setStyleSheet("background: transparent;")
    h.addWidget(t, 1)
    return box


class _LmuPage(QWizardPage):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setTitle("Le Mans Ultimate")
        self.setSubTitle("Lo que la app necesita del juego")
        self.lay = QVBoxLayout(self)
        self.rows = QVBoxLayout()
        self.lay.addLayout(self.rows)
        row = QHBoxLayout()
        pick = QPushButton("📁  Elegir carpeta de LMU…")
        pick.clicked.connect(self._pick)
        again = QPushButton("⟳  Volver a comprobar")
        again.clicked.connect(self.refresh)
        row.addWidget(pick)
        row.addWidget(again)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.lay.addWidget(_text(
            "<b>En el juego</b>: activa <i>Automatically Record Telemetry</i> (para guardar las sesiones que "
            "analiza la app) y pon la pantalla en <i>Ventana sin bordes</i> (para ver el overlay del coach "
            "encima). Si cambias algo, pulsa «Volver a comprobar»."))
        self.lay.addStretch(1)

    def initializePage(self):
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.setParent(None)
        wanted = ("Carpeta de LMU", "Grabación automática de telemetría", "Sesiones grabadas por LMU")
        for c in diagnostics.run():
            if c.title in wanted:
                self.rows.addWidget(_check_row(c.ok, c.title, c.detail.replace("\n", "<br>")))

    def _pick(self):
        if pick_lmu_dir(self):
            self.changed.emit()
            self.refresh()


class _VoicePage(QWizardPage):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setTitle("Voz del coach")
        self.setSubTitle("El coach te habla mientras conduces: frenadas, tiempos, coches al lado y la carrera")
        v = QVBoxLayout(self)
        self.voice = QCheckBox("Avisos por voz")
        self.voice.setChecked(bool(cfg.get("voice", True)))
        v.addWidget(self.voice)
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.addItem("(buscando voces…)")
        self.combo.setEnabled(False)
        test = QPushButton("▶  Probar")
        test.clicked.connect(self._test)
        row.addWidget(QLabel("Voz:"))
        row.addWidget(self.combo, 1)
        row.addWidget(test)
        v.addLayout(row)
        self.spotter = QCheckBox("Spotter: avisar de los coches que van a mi lado")
        self.spotter.setChecked(bool(cfg.get("spotter", True)))
        self.engineer = QCheckBox("Ingeniero de carrera: posición, diferencias, banderas y estrategia")
        self.engineer.setChecked(bool(cfg.get("engineer", True)))
        v.addWidget(self.spotter)
        v.addWidget(self.engineer)
        v.addWidget(_text("Cada mensaje se puede activar o quitar uno a uno en <b>⚙ Ajustes</b>."))
        v.addStretch(1)
        self.speaker = None
        self.poll = QTimer(self, interval=300, timeout=self._fill)

    def initializePage(self):
        if self.speaker is None:
            self.speaker = Speaker(True, self.cfg.get("voice_name"), float(self.cfg.get("voice_rate", 1.2)))
            self.speaker.start()
            self.poll.start()

    def _fill(self):
        if not self.speaker.voices:
            return
        self.poll.stop()
        self.combo.clear()
        self.combo.addItems(self.speaker.voices)
        cur = self.cfg.get("voice_name") or self.speaker.current
        if cur in self.speaker.voices:
            self.combo.setCurrentText(cur)
        self.combo.setEnabled(True)
        self.combo.currentTextChanged.connect(lambda n: (self.speaker.set_voice(n), self._test()))

    def _test(self):
        if self.speaker:
            self.speaker.say("Frena. Coche a la izquierda. Subes a la posición tres")

    def apply(self):
        self.cfg["voice"] = self.voice.isChecked()
        self.cfg["spotter"] = self.spotter.isChecked()
        self.cfg["engineer"] = self.engineer.isChecked()
        if self.combo.isEnabled() and self.combo.currentText():
            self.cfg["voice_name"] = self.combo.currentText()

    def close_speaker(self):
        self.poll.stop()
        if self.speaker:
            self.speaker.close()


class _BackupPage(QWizardPage):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setTitle("Copia de tus sesiones")
        self.setSubTitle("Para no perder nada aunque LMU borre sus archivos")
        v = QVBoxLayout(self)
        v.addWidget(_text("Cada vez que la app busca sesiones nuevas, copia las que LMU ha terminado de grabar "
                          "a una carpeta tuya. La app lee de ahí; la carpeta del juego nunca se toca."))
        self.where = QLabel()
        self.where.setWordWrap(True)
        v.addWidget(self.where)
        row = QHBoxLayout()
        change = QPushButton("Cambiar carpeta…")
        change.clicked.connect(self._change)
        row.addWidget(change)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        self._show()

    def _show(self):
        self.where.setText(f"Carpeta: <b>{archive.archive_dir()}</b>")

    def _change(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Carpeta para la copia de tus sesiones",
                                             str(archive.archive_dir().parent))
        if d:
            from pathlib import Path
            archive.set_archive_dir(Path(d))
            self._show()
            self.changed.emit()


class WelcomeWizard(QWizard):
    lmu_dir_changed = Signal()
    archive_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bienvenido a LMU Coach")
        self.setWizardStyle(QWizard.ModernStyle)
        self.resize(760, 560)
        self.setButtonText(QWizard.NextButton, "Siguiente ›")
        self.setButtonText(QWizard.BackButton, "‹ Atrás")
        self.setButtonText(QWizard.FinishButton, "Empezar")
        self.setButtonText(QWizard.CancelButton, "Saltar")
        self.cfg = C.load_config()

        hello = QWizardPage()
        hello.setTitle("👋  Bienvenido a LMU Coach")
        hello.setSubTitle("Tu ingeniero para Le Mans Ultimate")
        hv = QVBoxLayout(hello)
        hv.addWidget(_text(
            "<p>Dos cosas en una:</p><ul>"
            "<li><b>Análisis</b>: abre cualquier sesión que hayas corrido y mira dónde pierdes tiempo, curva a "
            "curva, frente a tu mejor vuelta o la de otro piloto. Combustible, neumáticos, ritmo, reglaje y "
            "tu progreso.</li>"
            "<li><b>Modo coach</b>: un overlay encima del juego con el delta en directo, avisos de frenada, "
            "spotter e ingeniero de carrera por voz.</li></ul>"
            "<p>En tres pasos lo dejamos todo listo.</p>"))
        hv.addStretch(1)
        self.addPage(hello)
        self.lmu = _LmuPage()
        self.lmu.changed.connect(self.lmu_dir_changed.emit)
        self.addPage(self.lmu)
        self.voice = _VoicePage(self.cfg)
        self.addPage(self.voice)
        self.backup = _BackupPage()
        self.backup.changed.connect(self.archive_changed.emit)
        self.addPage(self.backup)

        done = QWizardPage()
        done.setTitle("Todo listo")
        dv = QVBoxLayout(done)
        dv.addWidget(_text(
            "<ul><li>Pulsa <b>▶ Iniciar modo coach</b> y sal a pista.</li>"
            "<li>Elige una sesión de la lista para analizarla.</li>"
            "<li>En <b>⚙ Ajustes</b> decides qué te dice el coach: cada mensaje del spotter, del ingeniero y "
            "del coach se puede activar o quitar.</li>"
            "<li>Si algo no carga, <b>🩺 Diagnóstico</b> te dice qué falta.</li></ul>"))
        dv.addStretch(1)
        self.addPage(done)

    def done(self, r):
        if r == QWizard.Accepted:
            self.voice.apply()
            cur = C.load_config()
            for k in ("voice", "spotter", "engineer", "voice_name"):
                cur[k] = self.cfg.get(k)
            C.save_config(cur)
        self.voice.close_speaker()
        mark_done()        # también si lo salta: no volver a molestar (se puede abrir desde Ajustes)
        super().done(r)
