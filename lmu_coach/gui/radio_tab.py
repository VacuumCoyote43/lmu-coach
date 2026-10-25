"""Pestaña «Radio» de Ajustes: botón para hablar, frases que entiende el ingeniero y qué responde a cada una."""
import copy

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import radio as R


def _note(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setObjectName("subtitle")
    return lb


class AssignDialog(QDialog):
    """Espera a que pulses un botón del volante o una tecla."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Asignar botón")
        self.resize(420, 140)
        self.result_button = None
        v = QVBoxLayout(self)
        self.msg = QLabel("Pulsa el botón del volante (o la tecla) que quieras usar para hablar con el ingeniero…")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        v.addWidget(cancel, 0, Qt.AlignRight)
        self._armed = False          # primero hay que soltar lo que estuviera pulsado (el clic del ratón no cuenta)
        self._left = 100             # 10 s
        self.timer = QTimer(self, interval=100, timeout=self._poll)
        self.timer.start()

    def _poll(self):
        self._left -= 1
        if self._left <= 0:
            self.reject()
            return
        b = R.pressed_now()
        if not self._armed:
            self._armed = b is None
            return
        if b is not None:
            self.result_button = b
            self.timer.stop()
            self.accept()


class RadioTab(QWidget):
    changed = Signal(dict)       # la configuración de la radio entera, para guardarla

    def __init__(self, cfg: dict, play):
        super().__init__()
        self.play = play
        self.r = copy.deepcopy(cfg.get("radio") or {})
        if not self.r.get("commands"):
            self.r["commands"] = copy.deepcopy(R.DEFAULT_COMMANDS)
        self.listener = None
        lay = QVBoxLayout(self)

        top = QGroupBox("Radio con el ingeniero")
        f = QFormLayout(top)
        f.addRow(_note("Mantén pulsado el botón, di una de tus frases y suéltalo: el ingeniero te contesta con los "
                       "datos que elijas. Todo funciona sin internet (Whisper, una vez descargado el modelo, o el reconocimiento "
                       "de Windows). "
                       "En LMU, ese botón no debe tener otra función asignada."))
        self.on = QCheckBox("Radio activada")
        self.on.setChecked(bool(self.r.get("on")))
        self.on.toggled.connect(lambda v: self._set("on", v))
        f.addRow(self.on)
        brow = QHBoxLayout()
        self.btn_label = QLabel()
        brow.addWidget(self.btn_label, 1)
        assign = QPushButton("Asignar botón…")
        assign.clicked.connect(self._assign)
        clear = QPushButton("Quitar")
        clear.clicked.connect(lambda: (self._set("button", None), self._show_button()))
        brow.addWidget(assign)
        brow.addWidget(clear)
        f.addRow("Botón para hablar:", brow)
        self.beep = QCheckBox("Pitido al empezar a escuchar")
        self.beep.setChecked(bool(self.r.get("beep", True)))
        self.beep.toggled.connect(lambda v: self._set("beep", v))
        f.addRow(self.beep)
        from .. import whisper_asr as W
        self.engine = QComboBox()
        modern = R.ModernListener.available()
        self.engine.addItem("Whisper (recomendado: el que mejor entiende)" if W.available() else
                            "Whisper (no disponible)", "whisper")
        self.engine.addItem("Moderno de Windows" if modern else "Moderno de Windows (no disponible en este PC)",
                            "moderno")
        self.engine.addItem("Clásico de Windows", "clasico")
        self.engine.model().item(0).setEnabled(W.available())
        self.engine.model().item(1).setEnabled(modern)
        cur = self.r.get("engine", "auto")
        if cur == "auto":
            cur = "whisper" if W.available() else "moderno" if modern else "clasico"
        self.engine.setCurrentIndex(max(0, self.engine.findData(cur)))
        self.engine.currentIndexChanged.connect(self._engine_changed)
        f.addRow("Reconocimiento:", self.engine)
        wrow = QHBoxLayout()
        self.wmodel = QComboBox()
        for size, desc in W.SIZES.items():
            self.wmodel.addItem(f"{size} · {desc}", size)
        self.wmodel.setCurrentIndex(max(0, self.wmodel.findData(self.r.get("whisper_model", "base"))))
        self.wmodel.currentIndexChanged.connect(self._wmodel_changed)
        self.wdl = QPushButton("⬇  Descargar modelo")
        self.wdl.clicked.connect(self._download_model)
        self.wstatus = QLabel()
        wrow.addWidget(self.wmodel, 1)
        wrow.addWidget(self.wdl)
        self.wrow_label = QLabel("Modelo de Whisper:")
        f.addRow(self.wrow_label, wrow)
        f.addRow("", self.wstatus)
        self._show_whisper()
        conf = QDoubleSpinBox()
        conf.setRange(0.2, 0.9)
        conf.setSingleStep(0.05)
        conf.setDecimals(2)
        conf.setValue(float(self.r.get("min_conf", 0.45)))
        conf.setFixedWidth(90)
        conf.valueChanged.connect(lambda v: self._set("min_conf", v))
        f.addRow("Seguridad mínima:", conf)
        f.addRow(_note("Más alta: solo responde si está muy seguro de lo que has dicho. Más baja: responde más "
                       "aunque a veces se confunda de frase."))
        mrow = QHBoxLayout()
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(12)
        self.meter.setStyleSheet("QProgressBar { max-height: 12px; } QProgressBar::chunk { background: #2ecc71; }")
        self.meter_label = QLabel("—")
        self.meter_label.setFixedWidth(230)
        mrow.addWidget(self.meter, 1)
        mrow.addWidget(self.meter_label)
        f.addRow("Micrófono:", mrow)
        from .. import micmeter
        mics = micmeter.devices()
        mic_note = _note("Habla y mira la barra: si no se mueve, no te oye. Usa el micrófono predeterminado de Windows "
                         "(Sonido › Entrada).")
        mic_note.setToolTip("Micrófonos que ve Windows:\n" + "\n".join(m.strip() for m in mics) if mics else "")
        f.addRow(mic_note)
        self.mic = None
        self.mic_timer = QTimer(self, interval=80, timeout=self._mic_poll)
        trow = QHBoxLayout()
        self.test_btn = QPushButton("🎙  Probar micrófono (5 s)")
        self.test_btn.clicked.connect(self._test)
        self.test_out = QLabel()
        self.test_out.setWordWrap(True)
        trow.addWidget(self.test_btn)
        trow.addWidget(self.test_out, 1)
        f.addRow(trow)
        lay.addWidget(top)

        box = QGroupBox("Frases y respuestas")
        v = QVBoxLayout(box)
        v.addWidget(_note("Frases: lo que dices, separadas por «/» si quieres varias formas de pedir lo mismo. "
                          "Respuesta: lo que te dice, con los datos entre llaves (elige uno en «Insertar dato» y se "
                          "añade a la respuesta de la fila seleccionada). Si un dato no está disponible en ese "
                          "momento, se salta ese trozo de la frase. «{repetir}» repite la última respuesta."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Frases", "Respuesta", ""])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(2, 40)
        self.table.verticalHeader().hide()
        self.table.setMinimumHeight(260)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.insert = QComboBox()
        self.insert.addItem("Insertar dato…")
        for grp in dict.fromkeys(f.group for f in R.FIELDS):
            self.insert.addItem(f"— {grp} —")
            self.insert.model().item(self.insert.count() - 1).setEnabled(False)
            for fl in R.FIELDS:
                if fl.group == grp:
                    self.insert.addItem(f"{fl.label}  ({{{fl.key}}})", fl.key)
        self.insert.activated.connect(self._insert_field)
        add = QPushButton("➕  Añadir")
        add.clicked.connect(self._add_row)
        rem = QPushButton("Quitar fila")
        rem.clicked.connect(self._remove_row)
        reset = QPushButton("Frases de serie")
        reset.clicked.connect(self.reset)
        row.addWidget(self.insert, 1)
        row.addWidget(add)
        row.addWidget(rem)
        row.addWidget(reset)
        v.addLayout(row)
        lay.addWidget(box, 1)
        self._fill()
        self._show_button()
        self.table.itemChanged.connect(self._table_changed)

    # --- datos -------------------------------------------------------------------

    def _set(self, key, value):
        self.r[key] = value
        self.changed.emit(copy.deepcopy(self.r))

    def _fill(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for c in self.r["commands"]:
            self._append(" / ".join(c.get("phrases", [])), c.get("say", ""))
        self.table.blockSignals(False)

    def _append(self, phrases, say):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(phrases))
        self.table.setItem(r, 1, QTableWidgetItem(say))
        play = QPushButton("▶")
        play.setStyleSheet("padding: 0; min-width: 0;")
        play.setFixedSize(30, 24)
        play.setToolTip("Oír la respuesta con datos de ejemplo")
        play.clicked.connect(lambda _=False, b=play: self._preview(b))
        self.table.setCellWidget(r, 2, play)

    def _row_of(self, button):
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is button:
                return r
        return -1

    def _preview(self, button):
        r = self._row_of(button)
        if r >= 0:
            say = (self.table.item(r, 1).text() if self.table.item(r, 1) else "")
            self.play(R.render(say, {}, examples=True) if say != R.REPEAT else "Repito la última respuesta")

    def _collect(self):
        cmds = []
        for r in range(self.table.rowCount()):
            ph = self.table.item(r, 0).text() if self.table.item(r, 0) else ""
            say = self.table.item(r, 1).text() if self.table.item(r, 1) else ""
            phrases = [p.strip() for p in ph.split("/") if p.strip()]
            if phrases or say.strip():
                cmds.append({"phrases": phrases, "say": say.strip()})
        return cmds

    def _table_changed(self, _item=None):
        self._set("commands", self._collect())

    def _add_row(self):
        self._append("nueva frase", "{posicion}")
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 0))
        self._table_changed()

    def _remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._table_changed()

    def reset(self):
        self.r["commands"] = copy.deepcopy(R.DEFAULT_COMMANDS)
        self._fill()
        self._table_changed()

    def _insert_field(self, i):
        key = self.insert.itemData(i)
        self.insert.setCurrentIndex(0)
        r = self.table.currentRow()
        if not key or r < 0:
            return
        it = self.table.item(r, 1)
        txt = (it.text() if it else "").rstrip()
        it.setText((txt + " " if txt else "") + "{" + key + "}")

    # --- botón y prueba --------------------------------------------------------------

    def _show_button(self):
        b = self.r.get("button")
        self.btn_label.setText(R.button_label(b) if b else "<span style='color:#ffb020'>sin asignar</span>")

    def _assign(self):
        dlg = AssignDialog(self)
        if dlg.exec() and dlg.result_button:
            self._set("button", dlg.result_button)
            self._show_button()

    def _show_whisper(self):
        from .. import whisper_asr as W
        on = self.engine.currentData() == "whisper"
        for w in (self.wmodel, self.wdl, self.wstatus, self.wrow_label):
            w.setVisible(on)
        size = self.wmodel.currentData()
        if W.is_downloaded(size):
            self.wstatus.setText(f"<span style='color:#2ecc71'>Modelo «{size}» descargado.</span> Funciona sin internet.")
            self.wdl.setEnabled(False)
        else:
            self.wstatus.setText(f"<span style='color:#ffb020'>Falta descargar el modelo «{size}»</span> (una sola vez; "
                                 "mientras tanto se usa el reconocimiento de Windows).")
            self.wdl.setEnabled(True)

    def _wmodel_changed(self, _i):
        self._set("whisper_model", self.wmodel.currentData())
        self._reset_listener()
        self._show_whisper()

    def _download_model(self):
        import threading
        from .. import whisper_asr as W
        size = self.wmodel.currentData()
        self.wdl.setEnabled(False)
        self.wstatus.setText(f"Descargando «{size}»… (puede tardar un poco)")
        self._dl_result = None

        def work():
            self._dl_result = W.download(size) or "ok"
        threading.Thread(target=work, daemon=True).start()
        self._dl_timer = QTimer(self, interval=300, timeout=self._download_poll)
        self._dl_timer.start()

    def _download_poll(self):
        if self._dl_result is None:
            return
        self._dl_timer.stop()
        if self._dl_result != "ok":
            self.wstatus.setText(f"<span style='color:#ff5a5a'>{self._dl_result}</span>")
            self.wdl.setEnabled(True)
        else:
            self._reset_listener()
            self._show_whisper()

    def _reset_listener(self):
        if self.listener is not None:
            self.listener.close()
            self.listener = None

    def _engine_changed(self, _i):
        self._set("engine", self.engine.currentData())
        self._show_whisper()
        if self.listener is not None:
            self.listener.close()
            self.listener = None

    def _test(self):
        if self.listener is None:
            self.listener = R.make_listener(self.engine.currentData(), self.wmodel.currentData())
        phrases = R.all_phrases(self._collect())
        self.listener.start(phrases)
        while not self.listener.results.empty():
            self.listener.results.get_nowait()
        self.test_btn.setEnabled(False)
        self.test_out.setText("Escuchando… di una de tus frases")
        self._test_left = 110 if self.engine.currentData() == "whisper" else 50
        QTimer.singleShot(1200, lambda: self.listener.listen(True))     # el proceso tarda en arrancar
        if self.engine.currentData() == "whisper":
            self.test_out.setText("Grabando 4 s… di una de tus frases")
            QTimer.singleShot(5200, lambda: (self.listener.listen(False),
                                             self.test_out.setText("Transcribiendo…")))
        self._test_timer = QTimer(self, interval=100, timeout=self._test_poll)
        self._test_timer.start()

    def _test_poll(self):
        self._test_left -= 1
        res = None
        if not self.listener.results.empty():
            res = self.listener.results.get_nowait()
        if self.listener.error:
            self._test_done(f"<span style='color:#ff5a5a'>{self.listener.error}</span>")
        elif res and res[0]:
            text, conf = res
            cmd = R.find_command(text, self._collect())
            ans = R.render(cmd["say"], {}, examples=True) if cmd else ""
            low = conf < float(self.r.get("min_conf", 0.45))
            self._test_done(f"Oído: <b>{text}</b> (seguridad {conf:.2f}"
                            + (", <span style='color:#ffb020'>por debajo de tu mínimo: en pista diría «no te he "
                               "entendido»</span>" if low else "") + ")" + (f" → «{ans}»" if ans and not low else ""))
        elif res:
            self.test_out.setText("Te he oído, pero no se parece a ninguna de tus frases. Prueba otra vez…")
        elif self._test_left <= 0:
            self._test_done("No he oído ninguna de tus frases. Comprueba el micrófono de Windows.")

    def _test_done(self, html):
        self._test_timer.stop()
        self.listener.listen(False)
        self.test_btn.setEnabled(True)
        self.test_out.setText(html)

    # --- nivel del micrófono (solo mientras se ve esta pestaña) -----------------------

    def showEvent(self, e):
        super().showEvent(e)
        from .. import micmeter
        if self.mic is None:
            self.mic = micmeter.MicMeter()
            if not self.mic.open():
                self.meter_label.setText(f"<span style='color:#ff5a5a'>{self.mic.error}</span>")
                self.meter_label.setWordWrap(True)
                self.mic = None
                return
        self.mic_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._mic_stop()

    def _mic_poll(self):
        if self.mic is None:
            return
        lvl = self.mic.level()
        if lvl is None:
            return
        peak = self.mic.peak
        self.meter.setValue(int(peak * 100))
        color = "#ff5a5a" if peak > 0.92 else "#2ecc71" if peak > 0.25 else "#ffb020"
        self.meter.setStyleSheet("QProgressBar { max-height: 12px; } "
                                 f"QProgressBar::chunk {{ background: {color}; }}")
        self.meter_label.setText("muy alto (satura)" if peak > 0.92 else "te oigo bien" if peak > 0.35 else
                                 "bajo: habla o sube el micro" if peak > 0.12 else "silencio")

    def _mic_stop(self):
        self.mic_timer.stop()
        if self.mic:
            self.mic.close()
            self.mic = None

    def close_listener(self):
        self._mic_stop()
        if self.listener:
            self.listener.close()
