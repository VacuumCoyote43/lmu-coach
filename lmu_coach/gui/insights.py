"""Pestañas de análisis de la vista de sesión: combustible y estrategia, reglaje, consistencia,
neumáticos y frenos; y la ventana de progreso con la vuelta ideal."""
import datetime as dt

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import lapstats as ls
from ..laps import fmt_time
from . import theme

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
            t.setItem(r, 2, _it(_fmt(s.fuel_used, 2, " L"), RIGHT, muted))
            t.setItem(r, 3, _it(_fmt(s.ve_used, 2, " %"), RIGHT, muted))
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
            t.setItem(r, 0, _it(f"F{z.idx} · {z.start:.0f} m", color=theme.AMBER))
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

class ProgressDialog(QDialog):
    def __init__(self, parent, title: str, infos):
        super().__init__(parent)
        self.setWindowTitle(f"Progreso · {title}")
        self.resize(1000, 680)
        lay = QVBoxLayout(self)
        head = QLabel(title)
        head.setObjectName("title")
        lay.addWidget(head)

        days = ls.progress(infos)
        plot = pg.PlotWidget()
        plot.showGrid(x=True, y=True, alpha=0.15)
        plot.setLabel("left", "Tiempo de vuelta (s)")
        if days:
            x = np.arange(len(days))
            # todas las vueltas válidas (puntos), mejor del día y mediana
            for i, d in enumerate(days):
                ts = [lap[1] for s in infos if s.recorded[:10] == d["day"] for lap in s.lap_list if lap[2]]
                plot.addItem(pg.ScatterPlotItem(np.full(len(ts), i) + np.random.uniform(-0.15, 0.15, len(ts)), ts,
                                                size=4, pen=None, brush=pg.mkBrush(150, 155, 165, 90)))
            plot.plot(x, [d["median"] for d in days], pen=pg.mkPen(theme.MUTED, width=2), symbol="o",
                      symbolSize=6, symbolBrush=theme.MUTED, name="mediana")
            plot.plot(x, [d["best"] for d in days], pen=pg.mkPen(theme.PURPLE, width=2.5), symbol="o",
                      symbolSize=8, symbolBrush=theme.PURPLE, name="mejor")
            ax = plot.getAxis("bottom")
            ax.setTicks([[(i, d["day"][5:]) for i, d in enumerate(days)]])
            best_all = min(d["best"] for d in days)
            lo = best_all - 1
            hi = np.percentile([d["median"] for d in days], 90) + 3
            plot.setYRange(lo, hi)
        lay.addWidget(plot, 1)
        legend = _note("Morado: tu mejor vuelta del día · Gris: mediana de tus vueltas válidas · Puntos: cada vuelta")
        lay.addWidget(legend)

        sectors, real = ls.ideal_lap(infos)
        box = QGroupBox("Vuelta ideal (tus mejores sectores de todas las sesiones)")
        bl = QVBoxLayout(box)
        if sectors:
            ideal = sum(s.time for s in sectors)
            gain = (real[0] - ideal) if real else 0
            lbl = QLabel(f"<span style='font-size:18pt; font-weight:600; color:{theme.PURPLE}'>{fmt_time(ideal)}</span>"
                         f"&nbsp;&nbsp; tu mejor vuelta real: <b>{fmt_time(real[0])}</b> ({real[1]}, V{real[2]})"
                         f" · margen de mejora: <b>{gain:.3f} s</b>")
            bl.addWidget(lbl)
            t = _table(["Sector", "Mejor tiempo", "Sesión", "Vuelta"], stretch=2)
            t.setRowCount(3)
            for r, s in enumerate(sectors):
                t.setItem(r, 0, _it(f"S{r + 1}"))
                t.setItem(r, 1, _it(f"{s.time:.3f}", RIGHT, theme.PURPLE, bold=True))
                t.setItem(r, 2, _it(s.session))
                t.setItem(r, 3, _it(f"V{s.lap}", Qt.AlignCenter))
            t.setFixedHeight(4 * 27 + 8)
            bl.addWidget(t)
        else:
            bl.addWidget(_note("Aún no hay sectores suficientes (hacen falta vueltas válidas con los tres sectores)."))
        lay.addWidget(box)


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
            b.setItem(r, 0, _it(f"F{z.idx} · {z.start:.0f} m", color=theme.AMBER))
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
