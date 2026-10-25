"""Editor de reglajes (.svm de LMU) y experimentos A/B entre dos sesiones."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from . import theme
from .common import item, make_table, short_track
from .. import abtest, lapstats, svm
from ..laps import fmt_time
from ..log import log

RIGHT = Qt.AlignRight | Qt.AlignVCenter


def _note(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setObjectName("subtitle")
    return lb


# --------------------------------------------------------------------------- editor de reglajes

class SetupEditorDialog(QDialog):
    def __init__(self, parent, sessions, session_data=None, suggestions=None):
        super().__init__(parent)
        self.setWindowTitle("Editor de setups")
        self.resize(1180, 820)
        self.sessions = sessions
        self.sd = session_data
        self.suggestions = suggestions
        self.svm = None
        self.limits = {}
        lay = QVBoxLayout(self)
        head = QLabel("🛠  Editor de setups")
        head.setObjectName("title")
        lay.addWidget(head)
        lay.addWidget(_note(
            "Parte del reglaje que tienes cargado en LMU (o de otro .svm), cambia lo que quieras y guárdalo con otro "
            "nombre en la carpeta del circuito. En el garaje de LMU, cárgalo y pruébalo; luego compara las dos "
            "sesiones con «🧪 Comparar setups (A/B)». No se puede simular el tiempo por vuelta sin el modelo del "
            "coche: la columna «Qué hace» es orientativa."))

        src = QHBoxLayout()
        src.addWidget(QLabel("Partir de:"))
        self.source = QComboBox()
        for p in svm.find_setups():
            label = "Lo que tienes cargado ahora en LMU" if p.name == "TempModFile.svm" else f"{p.parent.name} / {p.stem}"
            self.source.addItem(label, str(p))
        self.source.currentIndexChanged.connect(lambda _i: self._load(self.source.currentData()))
        src.addWidget(self.source, 1)
        other = QPushButton("Abrir otro .svm…")
        other.clicked.connect(self._open_other)
        src.addWidget(other)
        lay.addLayout(src)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        tools = QHBoxLayout()
        self.show_all = QCheckBox("Mostrar también lo que no se puede ajustar")
        self.show_all.toggled.connect(lambda _v: self._fill())
        tools.addWidget(self.show_all)
        tools.addStretch(1)
        self.apply_btn = QPushButton("🧠  Aplicar sugerencias del asistente")
        self.apply_btn.setToolTip("Un paso en el sentido que propone el asistente de reglaje para la sesión abierta")
        self.apply_btn.clicked.connect(self._apply_suggestions)
        self.apply_btn.setEnabled(self.sd is not None)
        undo = QPushButton("Deshacer cambios")
        undo.clicked.connect(self._undo)
        tools.addWidget(self.apply_btn)
        tools.addWidget(undo)
        lay.addLayout(tools)

        self.table = make_table(["Ajuste", "Ahora", "Nueva posición", "Cambio", "Qué hace"], stretch_col=4)
        self.table.setSortingEnabled(False)
        lay.addWidget(self.table, 1)

        save = QGroupBox("Guardar")
        g = QGridLayout(save)
        g.addWidget(QLabel("Nombre:"), 0, 0)
        self.name = QLineEdit()
        self.name.setPlaceholderText("p. ej. Portimao menos ala")
        g.addWidget(self.name, 0, 1)
        g.addWidget(QLabel("Circuito:"), 0, 2)
        self.track = QComboBox()
        self.track.addItems(svm.track_folders())
        if self.sd is not None:
            guess = svm.guess_track_folder(self.sd.info.track, svm.track_folders())
            if guess:
                self.track.setCurrentText(guess)
        g.addWidget(self.track, 0, 3)
        g.addWidget(QLabel("Notas:"), 1, 0)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Qué has cambiado y por qué (se guarda dentro del setup)")
        g.addWidget(self.notes, 1, 1, 1, 3)
        self.save_btn = QPushButton("💾  Guardar en LMU")
        self.save_btn.setObjectName("coach")
        self.save_btn.clicked.connect(self._save)
        g.addWidget(self.save_btn, 0, 4, 2, 1)
        lay.addWidget(save)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)

        if self.source.count():
            self._load(self.source.currentData())
        else:
            self.info.setText("<span style='color:#ffb020'>No encuentro reglajes de LMU (.svm). Abre el juego, entra "
                              "en el garaje con el coche y vuelve aquí, o usa «Abrir otro .svm…».</span>")

    # --- cargar ----------------------------------------------------------------------

    def _open_other(self):
        start = str(svm.settings_dir() or Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Abrir setup", start, "Setups de LMU (*.svm)")
        if path:
            self.source.addItem(Path(path).stem, path)
            self.source.setCurrentIndex(self.source.count() - 1)

    def _load(self, path):
        if not path:
            return
        try:
            self.svm = svm.parse(Path(path))
        except OSError as e:
            QMessageBox.warning(self, "No se pudo abrir", str(e))
            return
        from . import car_pix
        stem_for = car_pix.images().stem_for
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.limits, car = svm.limits_from_sessions(self.svm, self.sessions, stem_for)
        finally:
            QApplication.restoreOverrideCursor()
        lim = (f"Límites de cada ajuste sacados de tu última sesión con <b>{car}</b>." if self.limits else
               "<span style='color:#ffb020'>No tienes sesiones con este coche: no sé el máximo de cada ajuste "
               "(si te pasas, LMU lo deja en el máximo).</span>")
        self.info.setText(f"Coche del setup: <b>{self.svm.vehicle_class or '?'}</b>. {lim}")
        if self.sd is not None and self.svm.veh_stem and stem_for(self.sd.info.car) not in (None, self.svm.veh_stem):
            self.info.setText(self.info.text() + "<br><span style='color:#ffb020'>Ojo: no es el coche de la sesión "
                                                 "abierta; las sugerencias del asistente no se aplican.</span>")
            self.apply_btn.setEnabled(False)
        elif self.sd is not None:
            self.apply_btn.setEnabled(True)
        self._fill()

    # --- tabla -------------------------------------------------------------------------

    def _rows(self):
        rows = []
        for e in self.svm.entries:
            lim = self.limits.get(e.session_key) if e.session_key else None
            fixed = not e.adjustable or (lim is not None and lim[2] <= lim[1])     # una sola posición
            if e.session_key is None or (fixed and not self.show_all.isChecked()):
                continue
            cat, name, order = lapstats.setup_label(e.session_key)
            rows.append((order, cat, name, e))
        rows.sort(key=lambda r: r[0])
        return rows

    def _fill(self):
        if self.svm is None:
            return
        t = self.table
        rows = self._rows()
        t.setRowCount(0)
        t.setRowCount(len(rows) + len({r[1] for r in rows}))
        r, last_cat = 0, None
        for _, cat, name, e in rows:
            if cat != last_cat:
                t.setItem(r, 0, item(cat.upper(), color=theme.MUTED, bold=True))
                t.setSpan(r, 0, 1, 5)
                r, last_cat = r + 1, cat
            t.setItem(r, 0, item(name))
            t.setItem(r, 1, item(e.text or str(e.index), color=theme.MUTED))
            spin = QSpinBox()
            lim = self.limits.get(e.session_key)
            spin.setRange(lim[1] if lim else 0, lim[2] if lim else 999)
            spin.setValue(e.value)
            spin.setEnabled(e.adjustable and not (lim and lim[2] <= lim[1]))
            spin.setFixedWidth(110)
            spin.setSuffix(f" / {lim[2]}" if lim else "")
            spin.valueChanged.connect(lambda v, e=e, row=r: self._changed(e, v, row))
            t.setCellWidget(r, 2, spin)
            self._show_change(e, r)
            r += 1
        t.setRowCount(r)
        t.resizeColumnToContents(0)

    def _changed(self, e, v, row):
        e.new_index = v
        self._show_change(e, row)

    def _show_change(self, e, row):
        t = self.table
        if not e.changed:
            t.setItem(row, 3, item(""))
            t.setItem(row, 4, item(""))
            return
        d = e.new_index - e.index
        t.setItem(row, 3, item(f"{'+' if d > 0 else ''}{d} posición{'es' if abs(d) != 1 else ''}", RIGHT,
                               theme.AMBER, bold=True))
        eff = svm.EFFECTS.get(e.effect_key or "")
        t.setItem(row, 4, item(eff[0 if d > 0 else 1] if eff else "", color=theme.FG))

    def _apply_suggestions(self):
        if self.svm is None or self.sd is None:
            return
        sugs = self.suggestions
        if sugs is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                from .. import setup_assistant
                sugs = setup_assistant.analyze(self.sd).suggestions
                self.suggestions = sugs
            except Exception:
                log.warning("Editor de setups: no se pudo analizar la sesión", exc_info=True)
                sugs = []
            finally:
                QApplication.restoreOverrideCursor()
        done = svm.apply_suggestions(self.svm, sugs, self.limits)
        self._fill()
        QMessageBox.information(self, "Sugerencias del asistente",
                                ("Aplicado (un paso cada uno):\n\n• " + "\n• ".join(done)) if done else
                                "No hay sugerencias del asistente que se puedan aplicar a este setup.")
        if done and not self.notes.text():
            self.notes.setText("Asistente: " + "; ".join(done))

    def _undo(self):
        if self.svm:
            for e in self.svm.entries:
                e.new_index = None
            self._fill()

    # --- guardar ---------------------------------------------------------------------------

    def _save(self):
        if self.svm is None:
            return
        if not self.svm.changes():
            QMessageBox.information(self, "Guardar", "No has cambiado nada.")
            return
        name = "".join(c for c in self.name.text().strip() if c not in '\\/:*?"<>|') or "LMU Coach"
        base = svm.settings_dir()
        if base is None or not self.track.currentText():
            QMessageBox.warning(self, "Guardar", "No encuentro la carpeta de reglajes de LMU.")
            return
        path = base / self.track.currentText() / f"{name}.svm"
        if path.exists() and QMessageBox.question(self, "Guardar", f"Ya existe «{path.name}». ¿Lo reemplazo?") \
                != QMessageBox.Yes:
            return
        try:
            out = svm.save(self.svm, path, self.notes.text())
        except OSError as e:
            QMessageBox.warning(self, "No se pudo guardar", str(e))
            return
        changes = "\n".join(f"• {lapstats.setup_label(e.session_key)[1] if e.session_key else e.key}: "
                            f"{e.index} → {e.new_index}" for e in self.svm.changes())
        QMessageBox.information(self, "Setup guardado",
                                f"Guardado en:\n{out}\n\n{changes}\n\nEn LMU: garaje › Cargar setup › «{name}». "
                                "Después de correr con él, compara las dos sesiones con «🧪 Comparar setups (A/B)».")


# --------------------------------------------------------------------------- experimentos A/B

class ABDialog(QDialog):
    def __init__(self, parent, sessions, sd_a, load):
        super().__init__(parent)
        self.setWindowTitle("Comparar setups (A/B)")
        self.resize(1200, 820)
        self.load = load              # ruta -> SessionData (con la caché de la vista)
        self.sd_a = sd_a
        i = sd_a.info
        lay = QVBoxLayout(self)
        head = QLabel(f"🧪  Comparar setups · {short_track(i.track)} · {i.car}")
        head.setObjectName("title")
        lay.addWidget(head)
        lay.addWidget(_note("A es la sesión abierta. Elige la sesión B con el mismo coche y circuito: se compara tu "
                            "ritmo (mediana de tus vueltas limpias, no la vuelta con suerte) y cada curva, y qué "
                            "cambiaba del reglaje entre una y otra."))
        row = QHBoxLayout()
        row.addWidget(QLabel(f"A: <b>{i.recorded}</b> · {fmt_time(i.best) if i.best else '—'}   ·   B:"))
        self.other = QComboBox()
        same = [s for s in sessions if s.track == i.track and s.layout == i.layout and s.car == i.car
                and s.path != i.path and not s.error and s.valid_laps >= 2]
        same.sort(key=lambda s: s.recorded, reverse=True)
        for s in same:
            who = f" · {s.driver}" if s.imported else ""
            self.other.addItem(f"{s.recorded} · {s.session_type} · {s.valid_laps} vueltas · mejor "
                               f"{fmt_time(s.best)}{who}", s.path)
        row.addWidget(self.other, 1)
        lay.addLayout(row)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setStyleSheet("font-size: 12pt; font-weight: 600;")
        lay.addWidget(self.verdict)
        self.cards = QGridLayout()
        lay.addLayout(self.cards)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Qué cambiaba del reglaje</b>"))
        self.diff = make_table(["Ajuste", "A", "B"], stretch_col=0)
        lv.addWidget(self.diff)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("<b>Curva a curva</b> (mediana de tus vueltas limpias; verde: B gana)"))
        self.corners = make_table(["Frenada", "A", "B", "B − A"], stretch_col=0)
        rv.addWidget(self.corners)
        split.addWidget(left)
        split.addWidget(right)
        lay.addWidget(split, 1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        self.other.currentIndexChanged.connect(lambda _i: self._run())
        if same:
            self._run()
        else:
            self.verdict.setText("No hay otra sesión tuya con este coche en este circuito para comparar.")

    def _run(self):
        path = self.other.currentData()
        if not path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            sd_b = self.load(path)
            r = abtest.compare(self.sd_a, sd_b)
        except Exception as e:
            log.warning("A/B: no se pudo comparar", exc_info=True)
            self.verdict.setText(f"No se pudo comparar: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.verdict.setText(r.verdict())
        while self.cards.count():
            w = self.cards.takeAt(0).widget()
            if w:
                w.setParent(None)
        stats = [("Mejor vuelta", r.a.best, r.b.best, fmt_time), ("Ritmo", r.a.pace, r.b.pace, fmt_time),
                 ("Regularidad (±)", r.a.spread, r.b.spread, lambda v: f"{v:.3f} s"),
                 ("Vueltas válidas", r.a.laps, r.b.laps, str)]
        for col, (title, va, vb, fmt) in enumerate(stats):
            box = QGroupBox(title)
            v = QVBoxLayout(box)
            better_b = va is not None and vb is not None and title != "Vueltas válidas" and vb < va
            v.addWidget(QLabel(f"A: <b>{fmt(va) if va is not None else '—'}</b>"))
            v.addWidget(QLabel(f"B: <b style='color:{theme.GREEN if better_b else theme.FG}'>"
                               f"{fmt(vb) if vb is not None else '—'}</b>"))
            self.cards.addWidget(box, 0, col)
        t = self.diff
        t.setRowCount(len(r.setup_diff))
        for k, (cat, name, va, vb) in enumerate(r.setup_diff):
            t.setItem(k, 0, item(name))
            t.setItem(k, 1, item(va))
            t.setItem(k, 2, item(vb, color=theme.AMBER))
        if not r.setup_diff:
            t.setRowCount(1)
            t.setItem(0, 0, item("Mismo reglaje en las dos sesiones", color=theme.MUTED))
        c = self.corners
        c.setRowCount(len(r.corners))
        from .. import corners as cn
        i = self.sd_a.info
        for k, cd in enumerate(r.corners):
            z = type("Z", (), {"idx": cd.idx, "apex": cd.apex})()
            c.setItem(k, 0, item(cn.label(z, i.track, i.layout), color=theme.AMBER))
            c.setItem(k, 1, item(f"{cd.a:+.3f}", RIGHT, theme.MUTED))
            c.setItem(k, 2, item(f"{cd.b:+.3f}", RIGHT, theme.MUTED))
            col = theme.GREEN if cd.diff < -0.04 else theme.RED if cd.diff > 0.04 else theme.MUTED
            c.setItem(k, 3, item(f"{cd.diff:+.3f} s", RIGHT, col, bold=True))

