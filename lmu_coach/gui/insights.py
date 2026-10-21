"""Pestañas de análisis de la vista de sesión: combustible y estrategia, reglaje, consistencia,
neumáticos y frenos, ritmo, asistente de reglaje, plan y ranking."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import corners
from .. import lapstats as ls
from ..laps import fmt_time
from . import theme
from ..log import log

RIGHT = Qt.AlignRight | Qt.AlignVCenter


def _table(headers, stretch=None, row_h=26):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(row_h)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch is not None:
        h.setSectionResizeMode(stretch, QHeaderView.Stretch)
    return t


def _it(text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None, bold=False, tip=None):
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(align)
    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    if color:
        it.setForeground(QBrush(QColor(color)))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    if tip:
        it.setToolTip(tip)
    return it


def _note(text=""):
    lab = QLabel(text)
    lab.setObjectName("subtitle")
    lab.setWordWrap(True)
    return lab


def _fmt(v, nd=2, unit=""):
    return "—" if v is None else f"{v:.{nd}f}{unit}"


# --------------------------------------------------------------------------- combustible y estrategia

class _HistoryWorker(QThread):
    done = Signal(object)

    def __init__(self, infos):
        super().__init__()
        self.infos = infos

    def run(self):
        try:
            self.done.emit(ls.history_consumption(self.infos))
        except Exception:
            log.warning("No se pudo calcular el consumo histórico", exc_info=True)
            self.done.emit(None)


class FuelTab(QWidget):
    def __init__(self):
        super().__init__()
        self.history = None
        self.worker = None
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        left.addWidget(self.summary)
        self.table = _table(["Vuelta", "Tiempo", "Combustible", "Energía", "Nota"], stretch=4)
        left.addWidget(self.table, 1)
        lay.addLayout(left, 3)

        box = QGroupBox("Calculadora de estrategia")
        form = QFormLayout(box)
        self.minutes = self._spin(5, 1440, 60, 0, " min")
        self.lap_time = self._spin(30, 600, 107, 1, " s")
        self.fuel = self._spin(0, 30, 3, 2, " L/vuelta")
        self.ve = self._spin(0, 30, 3.5, 2, " %/vuelta")
        self.tank = self._spin(0, 200, 90, 0, " L")
        self.reserve = self._spin(0, 3, 0.5, 1, " vueltas")
        form.addRow("Duración de la carrera", self.minutes)
        form.addRow("Ritmo", self.lap_time)
        form.addRow("Consumo de combustible", self.fuel)
        form.addRow("Consumo de energía", self.ve)
        form.addRow("Depósito", self.tank)
        form.addRow("Margen de seguridad", self.reserve)
        self.plan_lbl = QLabel()
        self.plan_lbl.setWordWrap(True)
        form.addRow(self.plan_lbl)
        self.stints = _table(["Relevo", "Vueltas", "Combustible", "Energía"], stretch=0, row_h=22)
        self.stints.setMinimumHeight(150)
        form.addRow(self.stints)
        form.addRow(_note("Pon «Energía» a 0 si el coche no usa energía virtual. Valores por defecto: "
                          "la mediana de tus vueltas con este coche en este circuito."))
        for w in (self.minutes, self.lap_time, self.fuel, self.ve, self.tank, self.reserve):
            w.valueChanged.connect(self._plan)
        lay.addWidget(box, 2)

    @staticmethod
    def _spin(lo, hi, val, dec, suffix):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setValue(val)
        s.setSuffix(suffix)
        s.setSingleStep(10 ** -dec if dec else 1)
        return s

    def set_data(self, stats, own_infos):
        t = self.table
        t.setRowCount(len(stats))
        clean = [s for s in stats if s.fuel_used and not s.refuel and s.note != "boxes / vuelta de salida"]
        for r, s in enumerate(stats):
            muted = None if s.valid else theme.MUTED
            t.setItem(r, 0, _it(s.num, Qt.AlignCenter, muted))
            t.setItem(r, 1, _it(fmt_time(s.time), RIGHT, muted))
            # en la vuelta del repostaje el nivel sube: se muestra lo cargado («+60.0 L»), no un consumo negativo
            fmt_use = lambda v, unit: (f"+{-v:.1f}{unit}" if v is not None and v < 0 else _fmt(v, 2, unit))
            t.setItem(r, 2, _it(fmt_use(s.fuel_used, " L"), RIGHT, theme.AMBER if (s.fuel_used or 0) < 0 else muted))
            t.setItem(r, 3, _it(fmt_use(s.ve_used, " %"), RIGHT, theme.AMBER if (s.ve_used or 0) < 0 else muted))
            note = "repostaje" if s.refuel else ("boxes" if "boxes" in s.note else ("" if s.valid else s.note))
            t.setItem(r, 4, _it(note, color=theme.AMBER if s.refuel else theme.MUTED))
        med = lambda xs: float(np.median(xs)) if xs else None
        self.sess_fuel = med([s.fuel_used for s in clean])
        self.sess_ve = med([s.ve_used for s in clean if s.ve_used])
        self._summary()
        # histórico en segundo plano
        if self.worker and self.worker.isRunning():
            self.worker.wait()
        self.history = None
        self.worker = _HistoryWorker(own_infos)
        self.worker.done.connect(self._history)
        self.worker.start()

    def _history(self, h):
        self.history = h
        self._summary()
        if h:
            for spin, val in ((self.fuel, h.fuel), (self.ve, h.ve), (self.lap_time, h.lap_time), (self.tank, h.tank)):
                if val:
                    spin.blockSignals(True)
                    spin.setValue(val)
                    spin.blockSignals(False)
        elif self.sess_fuel:
            self.fuel.setValue(self.sess_fuel)
        self._plan()

    def _summary(self):
        h = self.history
        txt = (f"<b>Esta sesión</b> (vueltas sin repostaje ni boxes): combustible {_fmt(self.sess_fuel, 2, ' L')}"
               f" · energía {_fmt(self.sess_ve, 2, ' %')} por vuelta")
        if h is None:
            txt += "<br><span style='color:#8b8f99'>Calculando la media de tus sesiones con este coche…</span>"
        elif h.laps:
            txt += (f"<br><b>Histórico</b> ({h.laps} vueltas de {h.sessions} sesiones): combustible "
                    f"{_fmt(h.fuel, 2, ' L')} · energía {_fmt(h.ve, 2, ' %')} por vuelta · ritmo {fmt_time(h.lap_time)}"
                    f" · depósito ≈ {_fmt(h.tank, 0, ' L')}")
        self.summary.setText(txt)

    def _plan(self):
        p = ls.strategy(self.minutes.value(), self.lap_time.value(), self.fuel.value() or None,
                        self.ve.value() or None, self.tank.value() or None, 100.0, self.reserve.value())
        if p.limiter == "-":
            self.plan_lbl.setText(p.notes[0])
            self.stints.setRowCount(0)
            return
        self.plan_lbl.setText(
            f"<b>{p.total_laps} vueltas</b> · hasta <b>{p.laps_per_stint}</b> por relevo (limita {p.limiter}) · "
            f"<b>{p.stops} parada{'s' if p.stops != 1 else ''}</b>" + (f"<br>{p.notes[0]}" if p.notes else ""))
        t = self.stints
        t.setRowCount(len(p.stints))
        for r, s in enumerate(p.stints):
            t.setItem(r, 0, _it(f"{r + 1}{' (salida)' if r == 0 else ''}"))
            t.setItem(r, 1, _it(s.laps, RIGHT))
            t.setItem(r, 2, _it(_fmt(s.fuel_start, 1, " L"), RIGHT))
            t.setItem(r, 3, _it(_fmt(s.ve_start, 0, " %"), RIGHT))


# --------------------------------------------------------------------------- reglaje

class SetupTab(QWidget):
    def __init__(self):
        super().__init__()
        self.mine = {}
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Comparar con:"))
        self.other = QComboBox()
        self.other.setMinimumWidth(320)
        bar.addWidget(self.other)
        self.only_diff = QCheckBox("Solo diferencias")
        self.only_diff.setChecked(True)
        bar.addWidget(self.only_diff)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.info = _note()
        lay.addWidget(self.info)
        self.table = _table(["Categoría", "Parámetro", "Esta sesión", "Comparada"], stretch=1)
        lay.addWidget(self.table, 1)
        self.other.currentIndexChanged.connect(self._fill)
        self.only_diff.toggled.connect(self._fill)

    def set_data(self, sd, own_infos):
        self.mine = sd.setup()
        cur = sd.info.path
        others = sorted((s for s in own_infos if s.path != cur), key=lambda s: (s.best <= 0, s.best or 1e9))
        self.other.blockSignals(True)
        self.other.clear()
        for s in others:
            best = fmt_time(s.best) if s.best > 0 else "sin vuelta válida"
            self.other.addItem(f"{s.recorded} · {best}", s.path)
        self.other.addItem("Nada (ver el reglaje completo)", None)
        self.other.setCurrentIndex(0)
        self.other.blockSignals(False)
        self._fill()

    def _fill(self):
        path = self.other.currentData()
        theirs = ls.read_setup_file(path) if path else None
        rows = ls.setup_rows(self.mine, theirs)
        n_diff = sum(1 for r in rows if r[4])
        if theirs is not None:
            self.info.setText(f"{n_diff} parámetro(s) distintos. La primera opción de la lista es tu sesión más rápida "
                              "con este coche y circuito.")
        else:
            self.info.setText(f"{len(rows)} parámetros")
        if self.only_diff.isChecked() and theirs is not None:
            rows = [r for r in rows if r[4]]
        t = self.table
        t.setRowCount(len(rows))
        for i, (cat, name, va, vb, diff) in enumerate(rows):
            t.setItem(i, 0, _it(cat, color=theme.MUTED))
            t.setItem(i, 1, _it(name))
            t.setItem(i, 2, _it(va, color=theme.AMBER if diff else None, bold=diff))
            t.setItem(i, 3, _it(vb, color=theme.MUTED if not diff else None))


# --------------------------------------------------------------------------- consistencia

class ConsistencyTab(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.table = _table(["Frenada", "Punto de frenada", "V. mínima", "Tiempo en la zona", "Pérdida media",
                             "Valoración"], stretch=5)
        lay.addWidget(self.table, 1)
        lay.addWidget(_note("Variación (desviación típica) entre tus vueltas válidas de esta sesión, comparando cada "
                            "una con tu mejor vuelta. Cuanto más baja, más constante."))

    def set_data(self, sd):
        self.track = (sd.info.track, sd.info.layout)
        zones, lap_sd, n = ls.consistency(sd)
        t = self.table
        if not zones:
            self.summary.setText(f"Hacen falta al menos 3 vueltas válidas en la sesión (hay {n}).")
            t.setRowCount(0)
            return
        worst = max(zones, key=lambda z: z.time_sd)
        self.summary.setText(f"<b>{n} vueltas válidas</b> · variación del tiempo de vuelta ±{lap_sd:.3f} s · "
                             f"zona más irregular: <b>F{worst.idx}</b> (±{worst.time_sd:.3f} s)")
        t.setRowCount(len(zones))
        for r, z in enumerate(zones):
            if z.time_sd < 0.06:
                verdict, col = "estable", theme.GREEN
            elif z.time_sd < 0.15:
                verdict, col = "algo irregular", theme.AMBER
            else:
                verdict, col = "irregular", theme.RED
            tips = []
            if z.brake_sd > 8:
                tips.append(f"frenas en un punto distinto cada vuelta (±{z.brake_sd:.0f} m)")
            if z.min_speed_sd > 4:
                tips.append(f"velocidad de paso variable (±{z.min_speed_sd:.0f} km/h)")
            t.setItem(r, 0, _it(corners.label(z, *self.track), color=theme.AMBER, tip=f"Frena a {z.start:.0f} m"))
            t.setItem(r, 1, _it(f"±{z.brake_sd:.1f} m", RIGHT, theme.AMBER if z.brake_sd > 8 else None))
            t.setItem(r, 2, _it(f"±{z.min_speed_sd:.1f} km/h", RIGHT, theme.AMBER if z.min_speed_sd > 4 else None))
            t.setItem(r, 3, _it(f"±{z.time_sd:.3f} s", RIGHT, col, bold=True))
            t.setItem(r, 4, _it(f"{z.mean_loss:+.3f} s", RIGHT, theme.RED if z.mean_loss > 0.05 else None))
            t.setItem(r, 5, _it(verdict + (": " + ", ".join(tips) if tips else ""), color=col))


# --------------------------------------------------------------------------- neumáticos y frenos

class TyresTab(QWidget):
    def __init__(self):
        super().__init__()
        self.stats = []
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Horizontal)
        self.table = _table(["Vuelta", "Tiempo"] + [f"{w}" for w in ls.WHEELS], row_h=74)
        for c in range(2, 6):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        split.addWidget(self.table)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        title = QLabel("Lectura de la vuelta seleccionada")
        title.setObjectName("section")
        rl.addWidget(title)
        self.hints = QLabel()
        self.hints.setWordWrap(True)
        self.hints.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        rl.addWidget(self.hints, 1)
        rl.addWidget(_note("Cada rueda: presión media (psi) · temperatura interior / centro / exterior · "
                           "temperatura máxima del freno · desgaste en la vuelta. Las pistas son orientativas: "
                           "compara siempre con tu sensación al volante."))
        split.addWidget(right)
        split.setSizes([800, 340])
        lay.addWidget(split)

    def set_data(self, stats):
        self.stats = stats
        t = self.table
        t.setRowCount(len(stats))
        for r, s in enumerate(stats):
            muted = None if s.valid else theme.MUTED
            num = _it(s.num, Qt.AlignCenter, muted)
            num.setData(Qt.UserRole, r)
            t.setItem(r, 0, num)
            t.setItem(r, 1, _it(fmt_time(s.time), RIGHT, muted))
            for k in range(4):
                lines = []
                if s.pressure:
                    lines.append(f"{s.pressure[k] / ls.KPA_PER_PSI:.1f} psi")
                if s.t_inner:
                    lines.append(f"{s.t_inner[k]:.0f} · {s.t_centre[k]:.0f} · {s.t_outer[k]:.0f} °C")
                if s.brake_max:
                    lines.append(f"freno {s.brake_max[k]:.0f} °C")
                if s.wear:
                    lines.append(f"desgaste {s.wear[k]:.2f} %")
                cell = _it("\n".join(lines) or "—", Qt.AlignCenter, muted)
                if s.pressure:
                    cell.setToolTip(f"{s.pressure[k]:.1f} kPa")
                t.setItem(r, 2 + k, cell)
        best = [i for i, s in enumerate(stats) if s.valid]
        if best:
            t.selectRow(min(best, key=lambda i: stats[i].time))

    def set_lap(self, num):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() == str(num):
                self.table.selectRow(r)
                return

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        s = self.stats[self.table.item(rows[0].row(), 0).data(Qt.UserRole)]
        hints = ls.tyre_hints(s)
        if s.brake_max:
            hot = [f"{w} {v:.0f} °C" for w, v in zip(ls.WHEELS, s.brake_max)]
            hints.append("Frenos (máx.): " + ", ".join(hot))
        if s.wear:
            hints.append("Desgaste en la vuelta: " + ", ".join(f"{w} {v:.2f} %" for w, v in zip(ls.WHEELS, s.wear)))
        self.hints.setText("<br>".join(f"• {h}" for h in hints) if hints else
                           "Temperaturas equilibradas: nada destacable en esta vuelta.")


# --------------------------------------------------------------------------- progreso y vuelta ideal

# --------------------------------------------------------------------------- asistente de reglaje

FIXED_OK = ("Reparto de frenada", "Control de tracción", "Mapa de TC", "ABS", "Freno motor", "Tu técnica")


class AssistantTab(QWidget):
    PRIO = {1: ("ALTA", theme.RED), 2: ("MEDIA", theme.AMBER), 3: ("BAJA", theme.MUTED)}

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        title = QLabel("Sugerencias")
        title.setObjectName("section")
        ll.addWidget(title)
        self.list = QTableWidget(0, 1)
        self.list.horizontalHeader().setVisible(False)
        self.list.verticalHeader().setVisible(False)
        self.list.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setShowGrid(False)
        self.list.setWordWrap(True)
        ll.addWidget(self.list, 1)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        t2 = QLabel("Equilibrio por curva")
        t2.setObjectName("section")
        rl.addWidget(t2)
        self.balance = _table(["Curva", "Entrada", "Vértice", "Salida", "Contrav."], stretch=None, row_h=24)
        for c in (1, 2, 3):
            self.balance.horizontalHeader().setSectionResizeMode(c, QHeaderView.Stretch)
        rl.addWidget(self.balance, 1)
        self.aids = _note()
        rl.addWidget(self.aids)
        rl.addWidget(_note("Ámbar (+) = subviraje: necesitas más volante del normal para tu coche a esa carga lateral. "
                           "Azul (−) = sobreviraje: menos (la trasera ayuda a girar o se escapa)."))
        split.addWidget(right)
        split.setSizes([640, 420])
        lay.addWidget(split, 1)
        lay.addWidget(_note("Sugerencias orientativas, calculadas con tu telemetría: cambia una cosa cada vez y "
                            "compruébala en pista. ✓ = se puede cambiar también en series de reglaje fijo."))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        width = max(self.list.viewport().width(), 420)
        for r in range(self.list.rowCount()):
            w = self.list.cellWidget(r, 0)
            if w is not None:
                self.list.setRowHeight(r, w.heightForWidth(width - 8) + 14)

    @staticmethod
    def _phase(v):
        """(texto corto, color, explicación) de una fase."""
        if v is None:
            return "—", theme.MUTED, "sin datos suficientes"
        if v > 0.45:
            return f"{v:+.1f}°", theme.AMBER, f"subviraje: {v:.1f}° de volante de más"
        if v < -0.45:
            return f"{v:+.1f}°", theme.ACCENT, f"sobreviraje: {abs(v):.1f}° de volante de menos"
        return f"{v:+.1f}°", theme.MUTED, "neutro"

    def set_data(self, sd, own_infos):
        self.track = (sd.info.track, sd.info.layout)
        from .. import setup_assistant as sa
        rep = sa.analyze(sd, own_infos)
        if not rep.laps_used:
            self.summary.setText("Hacen falta vueltas completas para analizar el coche.")
            self.list.setRowCount(0)
            self.balance.setRowCount(0)
            return
        n_hi = sum(1 for s in rep.suggestions if s.priority == 1)
        self.summary.setText(f"<b>{len(rep.suggestions)} sugerencias</b> ({n_hi} de prioridad alta) a partir de "
                             f"<b>{rep.laps_used} vueltas</b> de esta sesión"
                             + (" y de tus otras sesiones con este coche y circuito." if own_infos else "."))
        t = self.list
        t.setRowCount(len(rep.suggestions))
        for r, s in enumerate(rep.suggestions):
            tag, col = self.PRIO[s.priority]
            changes = "".join(
                f"<br>&nbsp;&nbsp;→ <b>{p}</b>: {a}{' <span style=\"color:#2ecc71\">✓</span>' if p.startswith(FIXED_OK) else ''}"
                for p, a in s.changes)
            html = (f"<span style='color:{col}; font-weight:700'>{tag}</span> · <span style='color:{theme.MUTED}'>"
                    f"{s.area}</span><br><b style='font-size:11pt'>{s.title}</b><br>"
                    f"<span style='color:{theme.MUTED}'>{s.evidence}</span>{changes}")
            lbl = QLabel(html)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet("background: transparent; padding: 8px;")
            t.setCellWidget(r, 0, lbl)
            width = max(t.viewport().width(), 420)
            t.setRowHeight(r, lbl.heightForWidth(width - 8) + 14)
        if not rep.suggestions:
            t.setRowCount(1)
            lbl = QLabel("Nada destacable: el coche está equilibrado y los neumáticos y frenos en su ventana.")
            lbl.setStyleSheet("padding: 8px;")
            t.setCellWidget(0, 0, lbl)
        b = self.balance
        b.setRowCount(len(rep.zones))
        for r, z in enumerate(rep.zones):
            b.setItem(r, 0, _it(corners.label(z, *self.track), color=theme.AMBER, tip=f"Frena a {z.start:.0f} m"))
            for c, v in enumerate((z.entry, z.mid, z.exit), start=1):
                txt, col, tip = self._phase(v)
                b.setItem(r, c, _it(txt, Qt.AlignCenter, col, tip=tip))
            b.setItem(r, 4, _it(f"{z.counter}/{z.laps}" if z.counter else "—", Qt.AlignCenter,
                                theme.RED if z.counter else theme.MUTED))
        s = rep.slip
        parts = []
        if s and s.abs_active is not None:
            parts.append(f"ABS activo el {s.abs_active * 100:.0f} % de la frenada fuerte")
        if s and s.tc_active is not None:
            parts.append(f"TC activo el {s.tc_active * 100:.0f} % del tiempo acelerando")
        if s and s.braking_samples:
            parts.append(f"deslizamiento en frenada: del. {s.front_slip * 100:.1f} % · tras. {s.rear_slip * 100:.1f} %")
        self.aids.setText(" · ".join(parts))


# --------------------------------------------------------------------------- ritmo y relevos

STINT_COLORS = (theme.ACCENT, theme.GREEN, theme.AMBER, theme.PURPLE)


class PaceTab(QWidget):
    """Ritmo vuelta a vuelta por relevo: tendencia, degradación, errores y desgaste de neumáticos."""

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        left.addWidget(self.summary)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("left", "Tiempo (s)")
        self.plot.setMouseEnabled(x=True, y=False)
        self.tyres = pg.PlotWidget()
        self.tyres.showGrid(x=True, y=True, alpha=0.15)
        self.tyres.setLabel("left", "Goma (%)")
        self.tyres.setLabel("bottom", "Vuelta")
        self.tyres.setXLink(self.plot)
        self.tyres.setMouseEnabled(x=True, y=False)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.plot)
        split.addWidget(self.tyres)
        split.setSizes([300, 150])
        left.addWidget(split, 1)
        left.addWidget(_note("Puntos: vueltas (huecos = boxes) · línea: tendencia del relevo · "
                             "rojo: vuelta con error (≥ 1,2 s más lenta que la tendencia). "
                             "Abajo, goma que queda: delanteras (línea) y traseras (discontinua)."))
        lay.addLayout(left, 3)

        right = QVBoxLayout()
        right.addWidget(_note("D = delanteras · T = traseras (la peor de cada eje en «Queda»)"))
        self.table = _table(["", "Vueltas", "Media", "Tend.", "Gomas", "Errores"], stretch=None, row_h=24)
        self.table.horizontalHeaderItem(3).setToolTip("Tendencia: segundos que pierdes (+) o ganas (−) cada vuelta")
        self.table.horizontalHeaderItem(4).setToolTip(
            "Tendencia descontando lo que ayuda ir quemando combustible: aproxima la degradación de las gomas")
        right.addWidget(self.table)
        self.wear = _table(["", "Desgaste/vuelta", "Queda al final", "Comb./v"], stretch=None, row_h=24)
        right.addWidget(self.wear)
        self.errors = _table(["Vuelta", "Relevo", "Pierdes"], stretch=None, row_h=22)
        right.addWidget(self.errors, 1)
        lay.addLayout(right, 2)

    def set_data(self, stats):
        sts = ls.stints(stats)
        self.plot.clear()
        self.tyres.clear()
        for t in (self.table, self.wear, self.errors):
            t.setRowCount(0)
        if not sts:
            self.summary.setText("Hace falta al menos un relevo de 3 vueltas seguidas sin pasar por boxes.")
            return
        lines = ls.stint_summary(sts)
        allc = [l.time for s in sts for l in s.clean]
        head = (f"<b>{len(sts)} relevo(s)</b> · ritmo medio <b>{fmt_time(sum(allc) / len(allc))}</b>"
                if allc else f"<b>{len(sts)} relevo(s)</b>")
        self.summary.setText(head + ("<br>" + "<br>".join(f"• {x}" for x in lines) if lines else ""))

        for s in sts:
            col = STINT_COLORS[(s.idx - 1) % len(STINT_COLORS)]
            xs = [l.num for l in s.laps]
            ys = [l.time for l in s.laps]
            self.plot.plot(xs, ys, pen=pg.mkPen(col, width=1, style=Qt.DotLine), symbol="o", symbolSize=6,
                           symbolBrush=col, symbolPen=None)
            if s.trend:
                a, b = s.trend
                self.plot.plot([xs[0], xs[-1]], [a + b * xs[0], a + b * xs[-1]], pen=pg.mkPen(col, width=2.5))
            if s.mistakes:
                self.plot.addItem(pg.ScatterPlotItem([m[0].num for m in s.mistakes], [m[0].time for m in s.mistakes],
                                                     size=12, brush=None, pen=pg.mkPen(theme.RED, width=2)))
            left = [(l.num, l.wear_left) for l in s.laps if len(l.wear_left) == 4]
            if left:
                self.tyres.plot([n for n, _ in left], [(w[0] + w[1]) / 2 for _, w in left], pen=pg.mkPen(col, width=2))
                self.tyres.plot([n for n, _ in left], [(w[2] + w[3]) / 2 for _, w in left],
                                pen=pg.mkPen(col, width=2, style=Qt.DashLine))
        if allc:
            self.plot.setYRange(min(allc) - 0.8, float(np.percentile([l.time for s in sts for l in s.laps], 98)) + 1.0)

        t = self.table
        t.setRowCount(len(sts))
        for r, s in enumerate(sts):
            col = STINT_COLORS[(s.idx - 1) % len(STINT_COLORS)]
            t.setItem(r, 0, _it(f"● {s.idx}", Qt.AlignCenter, col, bold=True))
            t.setItem(r, 1, _it(f"{len(s.laps)}", Qt.AlignCenter))
            t.setItem(r, 2, _it(fmt_time(s.avg) if s.avg else "—", RIGHT,
                                tip=f"Media de las vueltas limpias · mejor {fmt_time(s.best)}" if s.best else None))
            t.setItem(r, 3, _it(_fmt(s.slope, 2, " s/v") if s.slope is None else f"{s.slope:+.2f} s/v", RIGHT,
                                tip=None if s.slope is not None else "Pocas vueltas limpias para calcularla"))
            deg = s.slope_fuel
            dcol = None if deg is None else (theme.RED if deg > 0.08 else theme.AMBER if deg > 0.03 else theme.GREEN)
            t.setItem(r, 4, _it("—" if deg is None else f"{deg:+.2f} s/v", RIGHT, dcol))
            lost = sum(m[1] for m in s.mistakes)
            t.setItem(r, 5, _it(f"{len(s.mistakes)} · {lost:.1f} s" if s.mistakes else "0", RIGHT,
                                theme.RED if s.mistakes else theme.MUTED))

        w = self.wear
        w.setRowCount(len(sts))
        for r, s in enumerate(sts):
            col = STINT_COLORS[(s.idx - 1) % len(STINT_COLORS)]
            w.setItem(r, 0, _it(f"● {s.idx}", Qt.AlignCenter, col, bold=True))
            wl = s.wear_per_lap
            w.setItem(r, 1, _it(f"D {(wl[0] + wl[1]) / 2:.2f} · T {(wl[2] + wl[3]) / 2:.2f} %" if wl else "—",
                                tip="  ".join(f"{n} {v:.2f} %" for n, v in zip(ls.WHEELS, wl)) if wl else None))
            le = s.wear_left
            w.setItem(r, 2, _it(f"D {min(le[:2]):.0f} · T {min(le[2:]):.0f} %" if le else "—",
                                tip="  ".join(f"{n} {v:.0f} %" for n, v in zip(ls.WHEELS, le)) if le else None))
            w.setItem(r, 3, _it(_fmt(s.fuel_per_lap, 2, " L"), RIGHT))

        errs = [(m, s.idx) for s in sts for m in s.mistakes]
        e = self.errors
        e.setRowCount(len(errs))
        for r, ((lap, lost), idx) in enumerate(errs):
            e.setItem(r, 0, _it(f"V{lap.num}", Qt.AlignCenter))
            e.setItem(r, 1, _it(idx, Qt.AlignCenter, STINT_COLORS[(idx - 1) % len(STINT_COLORS)]))
            e.setItem(r, 2, _it(f"+{lost:.1f} s", RIGHT, theme.RED))


# --------------------------------------------------------------------------- plan de entrenamiento

class TrainingDialog(QDialog):
    """Las 3 curvas donde más pierdes frente a tu mejor vuelta y qué cambiar; se puede activar en el coach."""

    def __init__(self, parent, sd):
        from .. import training
        super().__init__(parent)
        self.training = training
        info = sd.info
        self.key = (info.track, info.car)
        self.setWindowTitle("Plan de entrenamiento")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        head = QLabel("🎯  Plan de entrenamiento")
        head.setObjectName("title")
        lay.addWidget(head)
        self.focus, summ = training.build(sd)
        if not self.focus:
            msg = ("Hacen falta al menos 3 vueltas válidas." if summ.get("laps", 0) < 3 else
                   "No hay ninguna curva donde pierdas tiempo de forma repetida frente a tu mejor vuelta. ¡Bien!")
            lay.addWidget(_note(msg))
        else:
            lay.addWidget(QLabel(
                f"Frente a tu mejor vuelta de esta sesión ({fmt_time(summ['best'])}), en una vuelta normal pierdes "
                f"<b>{summ['total_loss']:.2f} s</b> en las frenadas. Estas {len(self.focus)} curvas son "
                f"<b>{summ['focus_loss']:.2f} s</b> de eso: céntrate en ellas en tu próxima sesión."))
            for n, f in enumerate(self.focus, 1):
                tips = "".join(f"<br>→ {t[0].upper() + t[1:]}" for t in f.tips)
                card = QLabel(f"<span style='color:{theme.AMBER}; font-weight:600'>{n}. {f.name}</span>"
                              f"<span style='color:{theme.MUTED}'>  ·  pierdes {f.loss:.2f} s por vuelta de media"
                              f" ({f.laps} vueltas)</span>{tips}")
                card.setWordWrap(True)
                card.setStyleSheet(f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                                   "border-radius: 6px; padding: 10px;")
                lay.addWidget(card)
            if info.session_type == "Race":
                lay.addWidget(_note("Es una carrera: el tráfico hace variar las frenadas. Para un plan más fino, "
                                    "genéralo desde una sesión de libres o clasificación."))
        lay.addStretch(1)
        self.status = _note()
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.on_btn = QPushButton("▶  Activar en el coach")
        self.on_btn.setObjectName("coach")
        self.on_btn.setToolTip("Al llegar a estas curvas, el coach te recordará el objetivo (en pantalla y por voz)")
        self.on_btn.clicked.connect(self._activate)
        self.on_btn.setEnabled(bool(self.focus))
        self.off_btn = QPushButton("Quitar plan del coach")
        self.off_btn.clicked.connect(self._clear)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        row.addWidget(self.on_btn)
        row.addWidget(self.off_btn)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._refresh()

    def _refresh(self):
        cur = self.training.active(*self.key)
        self.off_btn.setEnabled(bool(cur))
        self.status.setText(("Plan activo en el coach: " + ", ".join(f.name for f in cur)) if cur
                            else "Ningún plan activo en el coach para este coche y circuito.")

    def _activate(self):
        self.training.save(*self.key, self.focus)
        self._refresh()

    def _clear(self):
        self.training.clear(*self.key)
        self._refresh()


# --------------------------------------------------------------------------- ranking

class RankingDialog(QDialog):
    """Tus tiempos frente a los de las sesiones importadas (mismo circuito y clase)."""

    def __init__(self, parent, sessions, short_track):
        super().__init__(parent)
        self.sessions = sessions
        self.setWindowTitle("Ranking")
        self.resize(980, 520)
        lay = QVBoxLayout(self)
        head = QLabel("🏆  Ranking")
        head.setObjectName("title")
        lay.addWidget(head)
        self.combo = QComboBox()
        self.groups = ls.ranking_groups(sessions)
        for t, l, c, n, imp in self.groups:
            extra = f"  ·  {n} pilotos" if n > 1 else "  ·  solo tú"
            name = short_track(t) + ("" if l == t else f" ({l.split(' - ')[-1]})")
            self.combo.addItem(f"{name}  ·  {c}{extra}")
        self.combo.currentIndexChanged.connect(self._fill)
        lay.addWidget(self.combo)
        self.table = _table(["#", "Piloto", "Mejor vuelta", "Dif.", "S1", "S2", "S3", "Ideal", "Coche", "Fecha"],
                            stretch=8, row_h=28)
        lay.addWidget(self.table, 1)
        self.note = _note()
        lay.addWidget(self.note)
        if not any(g[3] > 1 for g in self.groups):
            lay.addWidget(_note("Todavía no hay sesiones importadas de otros pilotos: cuando tu amigo te pase un "
                                ".lmusession (⬇ Importar sesión), sus tiempos aparecen aquí junto a los tuyos."))
        self._fill()

    def _fill(self):
        t = self.table
        if not self.groups:
            t.setRowCount(0)
            return
        track, layout, cls, _, _ = self.groups[self.combo.currentIndex()]
        rows = ls.ranking(self.sessions, track, layout, cls)
        t.setRowCount(len(rows))
        best_sec = [min((r.sectors[k] for r in rows if r.sectors[k]), default=0) for k in range(3)]
        lead = rows[0].best if rows else 0
        for i, r in enumerate(rows):
            me = theme.ACCENT if r.mine else None
            t.setItem(i, 0, _it(i + 1, Qt.AlignCenter, theme.PURPLE if i == 0 else None, bold=i == 0))
            t.setItem(i, 1, _it(("🙋 " if r.mine else "📥 ") + r.driver, color=me, bold=r.mine))
            t.setItem(i, 2, _it(fmt_time(r.best), RIGHT, theme.PURPLE if i == 0 else None, bold=True))
            t.setItem(i, 3, _it("—" if i == 0 else f"+{r.best - lead:.3f}", RIGHT, theme.MUTED if i == 0 else theme.RED))
            for k in range(3):
                v = r.sectors[k]
                t.setItem(i, 4 + k, _it(f"{v:.3f}" if v else "—", RIGHT,
                                        theme.PURPLE if v and v == best_sec[k] and len(rows) > 1 else None))
            t.setItem(i, 7, _it(fmt_time(r.ideal) if r.ideal else "—", RIGHT, theme.MUTED))
            t.setItem(i, 8, _it(r.best_car, color=theme.MUTED))
            t.setItem(i, 9, _it(r.best_date, color=theme.MUTED))
        mine = next((r for r in rows if r.mine), None)
        others = [r for r in rows if not r.mine]
        if mine and others:
            rival = min(others, key=lambda r: r.best)
            parts = []
            for k in range(3):
                if mine.sectors[k] and rival.sectors[k]:
                    d = mine.sectors[k] - rival.sectors[k]
                    parts.append(f"S{k + 1} {'+' if d > 0 else ''}{d:.3f}")
            verb = "Le sacas" if mine.best < rival.best else "Te saca"
            self.note.setText(f"{verb} {abs(mine.best - rival.best):.3f} s a {rival.driver}. Por sectores (tú − él): "
                              + " · ".join(parts) + ". Morado: mejor sector de todos.")
        else:
            self.note.setText("Morado: el mejor tiempo y los mejores sectores.")
