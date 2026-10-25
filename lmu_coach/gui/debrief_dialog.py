"""Ventana de debrief: el resumen de la sesión y las 3 acciones que más tiempo te darían, cada una con su botón."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import theme
from .common import SESSION_TYPES, short_track
from .. import config as C, debrief, goals
from ..laps import fmt_time

KIND_ICON = {"corner": "🎯", "tyres": "🛞", "consistency": "📈", "setup": "🛠", "goal": "🏁"}


class DebriefDialog(QDialog):
    open_page = Signal(int, int)       # grupo y pestaña de la vista de sesión
    open_setup = Signal(object)        # sugerencias del asistente (o None)

    def __init__(self, parent, sd, own_infos):
        super().__init__(parent)
        self.sd = sd
        i = sd.info
        self.setWindowTitle("Debrief")
        self.resize(860, 640)
        lay = QVBoxLayout(self)
        head = QLabel(f"🧾  Debrief · {short_track(i.track)} · {SESSION_TYPES.get(i.session_type, i.session_type)}")
        head.setObjectName("title")
        lay.addWidget(head)
        sub = QLabel(f"{i.car} · {i.recorded}")
        sub.setObjectName("subtitle")
        lay.addWidget(sub)
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            goal = goals.get(i.track, i.car, i.layout or i.track)
            self.d = debrief.build(sd, own_infos, goal)
        finally:
            QApplication.restoreOverrideCursor()
        hl = QLabel(self.d.headline)
        hl.setWordWrap(True)
        hl.setStyleSheet("font-size: 12pt; margin: 6px 0;")
        lay.addWidget(hl)
        stats = QHBoxLayout()
        for title, val in (("Mejor vuelta", self.d.best), ("Ritmo", self.d.pace), ("Vuelta ideal", self.d.ideal),
                           ("Objetivo", self.d.goal)):
            if val:
                box = QLabel(f"<span style='color:{theme.MUTED}; font-size:8pt'>{title.upper()}</span><br>"
                             f"<span style='font-size:15pt; font-weight:600'>{fmt_time(val)}</span>")
                box.setStyleSheet(f"background: {theme.PANEL_2}; border-radius: 6px; padding: 8px 14px;")
                stats.addWidget(box)
        stats.addStretch(1)
        lay.addLayout(stats)

        if not self.d.actions:
            msg = QLabel("No encuentro nada claro que mejorar en esta sesión (o hay pocas vueltas válidas). "
                         "¡Buena sesión!")
            msg.setWordWrap(True)
            lay.addWidget(msg)
        for n, a in enumerate(self.d.actions, 1):
            lay.addWidget(self._card(n, a))
        lay.addStretch(1)
        self.status = QLabel()
        self.status.setStyleSheet(f"color: {theme.GREEN};")
        lay.addWidget(self.status)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)

    def _card(self, n, a):
        f = QFrame()
        f.setStyleSheet(f"QFrame {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
                        "QLabel { border: none; background: transparent; }")
        v = QVBoxLayout(f)
        top = QHBoxLayout()
        t = QLabel(f"<span style='color:{theme.ACCENT}; font-size:14pt; font-weight:700'>{n}</span>&nbsp;&nbsp;"
                   f"{KIND_ICON.get(a.kind, '')} <b style='font-size:11pt'>{a.title}</b>")
        top.addWidget(t, 1)
        gain = QLabel(f"<span style='color:{theme.GREEN}'>≈ {a.gain:.2f} s/vuelta</span>")
        gain.setToolTip("Lo que podrías ganar por vuelta, estimado")
        top.addWidget(gain)
        v.addLayout(top)
        d = QLabel(a.detail)
        d.setWordWrap(True)
        d.setObjectName("subtitle")
        v.addWidget(d)
        if a.button:
            b = QPushButton(a.button)
            b.clicked.connect(lambda _=False, a=a, b=b: self._do(a, b))
            v.addWidget(b, 0, Qt.AlignLeft)
        return f

    def _do(self, a, button):
        i = self.sd.info
        if a.kind == "corner":
            cfg = C.load_config()
            cfg["practice_corner"] = {"track": i.track, "car": i.car, "apex": round(a.data["apex"], 1),
                                      "name": a.data["name"]}
            C.save_config(cfg)
            self.status.setText(f"Modo práctica activado: {a.data['name']}. En pista, el coach solo te hablará de esa "
                                "curva (quítalo en ⚙ Ajustes › Coach).")
            button.setEnabled(False)
        elif a.kind == "goal":
            goals.set_goal(i.track, i.car, round(a.data["ideal"], 1), i.layout or i.track)
            self.status.setText(f"Objetivo fijado: {fmt_time(round(a.data['ideal'], 1))}. El coach te dirá a cuánto "
                                "estás al acabar cada vuelta.")
            button.setEnabled(False)
        elif a.kind == "consistency":
            self.accept()
            self.open_page.emit(0, 2)
        elif a.kind in ("tyres", "setup"):
            self.accept()
            self.open_setup.emit(a.data.get("suggestions"))
