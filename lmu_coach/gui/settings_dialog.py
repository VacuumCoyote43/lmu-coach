"""Ventana de Ajustes: voz, overlay y qué dice el coach (spotter, ingeniero, coach y coche).

Los cambios se guardan al momento en config.json; si el modo coach está abierto, los aplica en un
segundo sin reiniciarlo.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import config as C
from ..speech import RATES, Speaker


def _note(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setObjectName("subtitle")
    return lb


class SettingsDialog(QDialog):
    archive_requested = Signal()     # abrir la ventana de la copia de seguridad
    wizard_requested = Signal()      # volver a pasar el asistente de bienvenida

    def __init__(self, parent=None, tab: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes")
        self.resize(880, 840)
        self.cfg = C.load_config()
        self.msg_boxes: dict[str, QCheckBox] = {}
        self._dirty, self._dirty_msgs = {}, {}
        self.speaker = Speaker(True, self.cfg.get("voice_name"), float(self.cfg.get("voice_rate", 1.2)))
        self.speaker.start()
        self._save_timer = QTimer(self, singleShot=True, interval=300, timeout=self._save)

        lay = QVBoxLayout(self)
        head = QLabel("⚙  Ajustes")
        head.setObjectName("title")
        lay.addWidget(head)
        lay.addWidget(_note("Se guardan al momento. Si el modo coach está abierto, los cambios se aplican en un "
                            "segundo, sin reiniciarlo."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._spotter_tab(), "Spotter")
        self.tabs.addTab(self._engineer_tab(), "Ingeniero")
        self.tabs.addTab(self._coach_tab(), "Coach")
        self.tabs.addTab(self._car_tab(), "Coche")
        from .radio_tab import RadioTab
        self.radio_tab = RadioTab(self.cfg, self._play)
        self.radio_tab.changed.connect(lambda r: self._set("radio", r))
        self.tabs.addTab(self.radio_tab, "📻 Radio")
        lay.addWidget(self.tabs, 1)
        names = {"general": 0, "spotter": 1, "engineer": 2, "coach": 3, "car": 4, "radio": 5}
        if tab in names:
            self.tabs.setCurrentIndex(names[tab])

        row = QHBoxLayout()
        reset = QPushButton("Restablecer esta pestaña")
        reset.setToolTip("Vuelve a los valores de fábrica de la pestaña que estás viendo")
        reset.clicked.connect(self._reset_tab)
        row.addWidget(reset)
        row.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

        self._voice_poll = QTimer(self, interval=300, timeout=self._fill_voices)
        self._voice_poll.start()

    # --- guardar ------------------------------------------------------------

    def _set(self, key, value):
        self.cfg[key] = value
        self._dirty[key] = value
        self._save_timer.start()

    def _set_msg(self, key, on):
        self.cfg.setdefault("msgs", {})[key] = bool(on)
        self._dirty_msgs[key] = bool(on)
        self._save_timer.start()

    def _save(self):
        """Guarda solo lo que se ha cambiado aquí, sobre lo último del archivo (el coach también lo escribe)."""
        if not self._dirty and not self._dirty_msgs:
            return
        cur = C.load_config()
        cur.update(self._dirty)
        cur.setdefault("msgs", {}).update(self._dirty_msgs)
        C.save_config(cur)
        self._dirty, self._dirty_msgs = {}, {}

    def done(self, r):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()
        self._voice_poll.stop()
        self.speaker.close()
        self.radio_tab.close_listener()
        super().done(r)

    # --- piezas ---------------------------------------------------------------

    def _check(self, text, key, tip=""):
        cb = QCheckBox(text)
        cb.setChecked(bool(self.cfg.get(key, C.DEFAULT_CONFIG.get(key))))
        cb.toggled.connect(lambda on: self._set(key, on))
        if tip:
            cb.setToolTip(tip)
        self._widgets[key] = cb
        return cb

    def _spin(self, key, lo, hi, step, decimals=1, suffix=""):
        sb = QDoubleSpinBox() if decimals else QSpinBox()
        if decimals:
            sb.setDecimals(decimals)
        sb.setRange(lo, hi)
        sb.setSingleStep(step)
        sb.setSuffix(suffix)
        val = self.cfg.get(key, C.DEFAULT_CONFIG[key])
        sb.setValue(float(val) if decimals else int(val))
        sb.valueChanged.connect(lambda v: self._set(key, v))
        sb.setFixedWidth(110)
        self._widgets[key] = sb
        return sb

    def _messages(self, group):
        """Una fila por mensaje: activado, qué es, ejemplo y botón para oírlo."""
        box = QGroupBox("Qué puede decir")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        all_on = QPushButton("Todos")
        none_on = QPushButton("Ninguno")
        for b in (all_on, none_on):
            b.setFixedWidth(90)
        msgs = [m for m in C.MESSAGES if m.group == group]
        all_on.clicked.connect(lambda: [self.msg_boxes[m.key].setChecked(True) for m in msgs])
        none_on.clicked.connect(lambda: [self.msg_boxes[m.key].setChecked(False) for m in msgs])
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(all_on)
        top.addWidget(none_on)
        grid.addLayout(top, 0, 0, 1, 4)
        for r, m in enumerate(msgs, start=1):
            cb = QCheckBox(m.label)
            cb.setChecked(C.msg_on(self.cfg, m.key))
            cb.toggled.connect(lambda on, k=m.key: self._set_msg(k, on))
            if m.help:
                cb.setToolTip(m.help)
            self.msg_boxes[m.key] = cb
            ex = QLabel(f"«{m.example}»")
            ex.setObjectName("subtitle")
            if m.help:
                ex.setToolTip(m.help)
            play = QToolButton()
            play.setText("▶")
            play.setToolTip("Oír cómo suena")
            play.clicked.connect(lambda _=False, t=m.example: self._play(t))
            grid.addWidget(cb, r, 0)
            grid.addWidget(ex, r, 1)
            grid.addWidget(play, r, 2)
        return box

    def _page(self, *widgets):
        inner = QWidget()
        v = QVBoxLayout(inner)
        for w in widgets:
            v.addWidget(w)
        v.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setWidget(inner)
        return sc

    @property
    def _widgets(self):
        if not hasattr(self, "_w"):
            self._w = {}
        return self._w

    def _play(self, text):
        self.speaker.say(text)

    # --- pestañas ---------------------------------------------------------------

    def _general_tab(self):
        voice = QGroupBox("Voz")
        f = QFormLayout(voice)
        f.addRow(self._check("Avisos por voz", "voice", "Si lo quitas, el coach no dice nada (el overlay sigue)"))
        self.voice_combo = QComboBox()
        self.voice_combo.addItem("(buscando voces…)")
        self.voice_combo.setEnabled(False)
        self.voice_combo.currentTextChanged.connect(self._voice_chosen)
        test = QPushButton("▶  Probar")
        test.clicked.connect(lambda: self._play("Frena. Uno cuarenta y seis seis. Coche a la izquierda"))
        vrow = QHBoxLayout()
        vrow.addWidget(self.voice_combo, 1)
        vrow.addWidget(test)
        f.addRow("Voz:", vrow)
        self.rate_combo = QComboBox()
        for label, r in RATES:
            self.rate_combo.addItem(label, r)
        cur = float(self.cfg.get("voice_rate", 1.2))
        self.rate_combo.setCurrentIndex(min(range(len(RATES)), key=lambda i: abs(RATES[i][1] - cur)))
        self.rate_combo.currentIndexChanged.connect(self._rate_chosen)
        f.addRow("Velocidad:", self.rate_combo)
        f.addRow(_note("Más voces: Configuración de Windows › Hora e idioma › Voz › Agregar voces."))

        ov = QGroupBox("Overlay del coach")
        g = QFormLayout(ov)
        op = QSlider(Qt.Horizontal)
        op.setRange(40, 100)
        op.setValue(int(round(float(self.cfg.get("opacity", 0.93)) * 100)))
        op_label = QLabel(f"{op.value()} %")
        op.valueChanged.connect(lambda v: (op_label.setText(f"{v} %"), self._set("opacity", v / 100)))
        orow = QHBoxLayout()
        orow.addWidget(op, 1)
        orow.addWidget(op_label)
        self._widgets["opacity"] = op
        g.addRow("Opacidad:", orow)
        g.addRow(self._check("Temperaturas de gomas y frenos", "temps"))
        g.addRow(self._check("Pitido en el punto de frenada", "beep_on_brake",
                             "Además (o en lugar) de la voz, un pitido corto al llegar al punto de frenada"))
        g.addRow(_note("Para verlo encima del juego, LMU debe estar en «Ventana sin bordes». Clic derecho en el "
                       "overlay para el menú rápido; arrástralo para moverlo."))

        other = QGroupBox("Otros")
        h = QHBoxLayout(other)
        backup = QPushButton("💾  Copia de seguridad…")
        backup.clicked.connect(self.archive_requested.emit)
        wiz = QPushButton("👋  Asistente de bienvenida…")
        wiz.clicked.connect(self.wizard_requested.emit)
        h.addWidget(backup)
        h.addWidget(wiz)
        h.addStretch(1)
        return self._page(voice, ov, other)

    def _spotter_tab(self):
        on = QGroupBox("Spotter")
        v = QVBoxLayout(on)
        v.addWidget(_note("Avisa de los coches que van a tu lado, como el spotter de una carrera real. Al salir a "
                          "pista aprende qué lado es cuál con tus primeras curvas; hasta entonces no dice nada."))
        v.addWidget(self._check("Spotter activado", "spotter"))
        v.addWidget(self._check("Barras rojas a los lados del overlay", "spot_overlay",
                                "Además de la voz, el overlay marca el lado donde hay un coche"))
        params = QGroupBox("Cuándo cuenta un coche como «al lado»")
        f = QFormLayout(params)
        f.addRow("Distancia lateral máxima:", self._spin("spot_side", 2.5, 8.0, 0.1, 1, " m"))
        f.addRow(_note("Más alta: avisa también de coches algo más separados (más avisos). Más baja: solo de los "
                       "que van rueda con rueda."))
        f.addRow("Solape longitudinal:", self._spin("spot_len", 3.0, 8.0, 0.1, 1, " m"))
        f.addRow(_note("Cuánto se tienen que solapar los coches. 5,2 m ≈ un coche de largo."))
        f.addRow("Pausa mínima entre avisos:", self._spin("spot_gap", 0.2, 3.0, 0.1, 1, " s"))
        f.addRow("Recordar «sigue ahí» cada:", self._spin("spot_still_s", 2.0, 15.0, 0.5, 1, " s"))
        return self._page(on, self._messages("spotter"), params)

    def _engineer_tab(self):
        on = QGroupBox("Ingeniero de carrera")
        v = QVBoxLayout(on)
        v.addWidget(_note("Solo en carreras: posición, diferencias con los de delante y detrás de tu clase, "
                          "paradas de tus rivales, banderas y estrategia."))
        v.addWidget(self._check("Ingeniero activado", "engineer"))
        params = QGroupBox("Ajustes")
        f = QFormLayout(params)
        f.addRow("«Coche detrás» por debajo de:", self._spin("eng_close_s", 0.3, 3.0, 0.1, 1, " s"))
        f.addRow("Aviso de clase más rápida con:", self._spin("eng_fast_s", 1.0, 6.0, 0.5, 1, " s de antelación"))
        f.addRow("Resumen cada:", self._spin("eng_summary_every", 1, 10, 1, 0, " vueltas"))
        f.addRow("Tiempo perdido en una parada:", self._spin("eng_pit_loss", 10, 120, 1, 0, " s"))
        f.addRow(_note("Entrar en boxes, repostar y salir frente a seguir en pista. Sirve para decirte en qué "
                       "posición volverías. Míralo en la pestaña «Ritmo y relevos» de una carrera con parada."))
        return self._page(on, self._messages("engineer"), params)

    def _coach_tab(self):
        params = QGroupBox("Ajustes")
        f = QFormLayout(params)
        f.addRow("Decir el delta cada:", self._spin("delta_every", 0, 3, 1, 0, " sectores"))
        f.addRow(_note("0 = nunca. Con 1 lo dice al pasar por cada sector («más tres décimas»). Activa también "
                       "«Delta con tu referencia» arriba."))
        practice = self.cfg.get("practice_corner")
        pr = QHBoxLayout()
        if isinstance(practice, dict):
            from .common import short_track
            txt = f"Modo práctica: {practice.get('name')} · {short_track(practice.get('track', ''))}"
        else:
            txt = "Modo práctica: desactivado"
        lab = QLabel(txt)
        pr.addWidget(lab, 1)
        off = QPushButton("Quitar")
        off.setEnabled(bool(practice))
        off.clicked.connect(lambda: (self._set("practice_corner", None), lab.setText("Modo práctica: desactivado"),
                                     off.setEnabled(False)))
        pr.addWidget(off)
        f.addRow(pr)
        f.addRow(_note("El modo práctica se activa desde una sesión: en «Dónde pierdes tiempo», clic derecho en una "
                       "frenada › «Practicar esta curva»."))
        return self._page(self._messages("coach"), params)

    def _car_tab(self):
        return self._page(self._messages("car"))

    # --- voz --------------------------------------------------------------------

    def _fill_voices(self):
        if not self.speaker.voices:
            return
        self._voice_poll.stop()
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        self.voice_combo.addItems(self.speaker.voices)
        cur = self.cfg.get("voice_name") or self.speaker.current
        if cur in self.speaker.voices:
            self.voice_combo.setCurrentText(cur)
        self.voice_combo.setEnabled(True)
        self.voice_combo.blockSignals(False)

    def _voice_chosen(self, name):
        if not name or not self.voice_combo.isEnabled():
            return
        self._set("voice_name", name)
        self.speaker.set_voice(name)
        self._play("Frena. Coche a la izquierda")

    def _rate_chosen(self, i):
        r = self.rate_combo.itemData(i)
        self._set("voice_rate", r)
        self.speaker.set_rate(r)
        self._play("Frena. Coche a la izquierda")

    # --- restablecer ------------------------------------------------------------------

    TAB_KEYS = {
        0: ["voice", "opacity", "temps", "beep_on_brake"],
        1: ["spotter", "spot_overlay", "spot_side", "spot_len", "spot_gap", "spot_still_s"],
        2: ["engineer", "eng_close_s", "eng_fast_s", "eng_summary_every", "eng_pit_loss"],
        3: ["delta_every"],
        4: [],
    }
    TAB_GROUP = {1: "spotter", 2: "engineer", 3: "coach", 4: "car"}

    def _reset_tab(self):
        i = self.tabs.currentIndex()
        if self.tabs.widget(i) is self.radio_tab:
            self.radio_tab.reset()
            return
        for k in self.TAB_KEYS[i]:
            w = self._widgets.get(k)
            d = C.DEFAULT_CONFIG[k]
            if isinstance(w, QCheckBox):
                w.setChecked(bool(d))
            elif isinstance(w, QSlider):
                w.setValue(int(round(d * 100)))
            elif w is not None:
                w.setValue(d)
        g = self.TAB_GROUP.get(i)
        if g:
            for m in C.MESSAGES:
                if m.group == g:
                    self.msg_boxes[m.key].setChecked(m.default)
