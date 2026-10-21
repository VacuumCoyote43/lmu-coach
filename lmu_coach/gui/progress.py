"""«Mi progreso»: todos tus circuitos y coches, tu evolución, tu vuelta ideal y tus objetivos."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from . import car_pix, theme
from .common import car_label, item, make_table, short_track
from .. import goals, lapstats as ls
from ..laps import fmt_time

RIGHT = Qt.AlignRight | Qt.AlignVCenter


def track_name(c) -> str:
    """«Silverstone · WEC» si el circuito tiene varios trazados."""
    name = short_track(c.track)
    if c.layout and c.layout != c.track:
        name += " · " + c.layout.rsplit(" - ", 1)[-1]
    return name


def _note(text=""):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setObjectName("subtitle")
    return lb


class ProgressPanel(QWidget):
    """Gráfica por días (mejor y mediana), vuelta ideal y objetivo de un circuito y coche."""

    def __init__(self):
        super().__init__()
        self.combo = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel()
        self.title.setObjectName("title")
        lay.addWidget(self.title)
        self.sub = _note()
        lay.addWidget(self.sub)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setLabel("left", "Tiempo de vuelta (s)")
        lay.addWidget(self.plot, 1)
        lay.addWidget(_note("Morado: tu mejor vuelta del día · Gris: mediana de tus vueltas válidas · Puntos: cada "
                            "vuelta · Verde: tu objetivo · Discontinua: tu vuelta ideal"))

        self.ideal = QLabel()
        self.ideal.setWordWrap(True)
        box = QGroupBox("Vuelta ideal (tus mejores sectores de todas las sesiones)")
        QVBoxLayout(box).addWidget(self.ideal)
        lay.addWidget(box)

        gbox = QGroupBox("Objetivo")
        g = QVBoxLayout(gbox)
        self.goal_info = QLabel()
        self.goal_info.setWordWrap(True)
        g.addWidget(self.goal_info)
        row = QHBoxLayout()
        self.goal_edit = QLineEdit()
        self.goal_edit.setPlaceholderText("p. ej. 1:46.0")
        self.goal_edit.setFixedWidth(140)
        self.goal_edit.returnPressed.connect(self._set_goal)
        setb = QPushButton("🎯  Fijar objetivo")
        setb.clicked.connect(self._set_goal)
        self.ideal_btn = QPushButton("Usar mi vuelta ideal")
        self.ideal_btn.setToolTip("Tu vuelta ideal es un objetivo realista: ya has hecho cada sector así de rápido")
        self.ideal_btn.clicked.connect(self._goal_ideal)
        self.clear_btn = QPushButton("Quitar")
        self.clear_btn.clicked.connect(self._clear_goal)
        for w in (self.goal_edit, setb, self.ideal_btn, self.clear_btn):
            row.addWidget(w)
        row.addStretch(1)
        g.addLayout(row)
        g.addWidget(_note("Con el modo coach en este circuito y coche, al acabar cada vuelta te dice a cuánto estás "
                          "de tu objetivo (se puede quitar en ⚙ Ajustes › Coach)."))
        lay.addWidget(gbox)

    def set_combo(self, c: ls.ComboStats):
        self.combo = c
        self.title.setText(f"{track_name(c)}  ·  {c.car}")
        self.sub.setText(f"{c.sessions} sesiones · {c.laps} vueltas válidas · {c.days} días · desde {c.first_day} · "
                         f"has bajado {c.gained:.3f} s desde el primer día")
        self._plot()
        self._fill_ideal()
        self._fill_goal()

    def _plot(self):
        c, plot = self.combo, self.plot
        plot.clear()
        days = ls.progress(c.infos)
        if not days:
            return
        x = np.arange(len(days))
        rng = np.random.default_rng(0)
        for i, d in enumerate(days):
            ts = [lap[1] for s in c.infos if s.recorded[:10] == d["day"] for lap in s.lap_list if lap[2]]
            plot.addItem(pg.ScatterPlotItem(np.full(len(ts), i) + rng.uniform(-0.15, 0.15, len(ts)), ts,
                                            size=4, pen=None, brush=pg.mkBrush(150, 155, 165, 90)))
        plot.plot(x, [d["median"] for d in days], pen=pg.mkPen(theme.MUTED, width=2), symbol="o",
                  symbolSize=6, symbolBrush=theme.MUTED)
        plot.plot(x, [d["best"] for d in days], pen=pg.mkPen(theme.PURPLE, width=2.5), symbol="o",
                  symbolSize=8, symbolBrush=theme.PURPLE)
        if c.ideal:
            plot.addItem(pg.InfiniteLine(c.ideal, angle=0, pen=pg.mkPen(theme.PURPLE, width=1, style=Qt.DashLine)))
        goal = goals.get(c.track, c.car, c.layout)
        if goal:
            plot.addItem(pg.InfiniteLine(goal, angle=0, pen=pg.mkPen(theme.GREEN, width=2)))
        plot.getAxis("bottom").setTicks([[(i, d["day"][5:]) for i, d in enumerate(days)]])
        lo = min([d["best"] for d in days] + [v for v in (c.ideal, goal) if v]) - 1
        hi = np.percentile([d["median"] for d in days], 90) + 3
        plot.setYRange(lo, hi)
        plot.setXRange(-0.5, len(days) - 0.5)

    def _fill_ideal(self):
        c = self.combo
        sectors, real = ls.ideal_lap(c.infos)
        if not sectors:
            self.ideal.setText("Aún no hay sectores suficientes (hacen falta vueltas válidas con los tres sectores).")
            self.ideal_btn.setEnabled(False)
            return
        self.ideal_btn.setEnabled(True)
        ideal = sum(s.time for s in sectors)
        parts = " · ".join(f"S{i + 1} <b>{s.time:.3f}</b> ({s.session[:10]}, V{s.lap})" for i, s in enumerate(sectors))
        self.ideal.setText(
            f"<span style='font-size:16pt; font-weight:600; color:{theme.PURPLE}'>{fmt_time(ideal)}</span>"
            f"&nbsp;&nbsp; tu mejor vuelta real: <b>{fmt_time(real[0])}</b> ({real[1]}, V{real[2]})"
            f" · margen: <b>{real[0] - ideal:.3f} s</b><br>{parts}")

    def _fill_goal(self):
        c = self.combo
        goal = goals.get(c.track, c.car, c.layout)
        self.clear_btn.setEnabled(goal is not None)
        if goal is None:
            self.goal_info.setText("Sin objetivo. Fija un tiempo que quieras conseguir con este coche aquí.")
            self.goal_edit.clear()
            return
        self.goal_edit.setText(fmt_time(goal))
        gap = c.best - goal
        if gap <= 0:
            txt = f"<span style='color:{theme.GREEN}'><b>¡Conseguido!</b></span> Tu mejor vuelta ({fmt_time(c.best)}) " \
                  f"está {abs(gap):.3f} s por debajo de {fmt_time(goal)}. Toca poner otro."
        else:
            txt = f"Objetivo <b>{fmt_time(goal)}</b> · tu mejor vuelta {fmt_time(c.best)} · te faltan " \
                  f"<b style='color:{theme.AMBER}'>{gap:.3f} s</b>"
            if c.ideal and c.ideal <= goal:
                txt += " · tu vuelta ideal ya lo baja: está a tu alcance"
        self.goal_info.setText(txt)

    def _set_goal(self):
        t = goals.parse_time(self.goal_edit.text())
        if not t or not 20 < t < 1200 or self.combo is None:
            self.goal_info.setText(f"<span style='color:{theme.RED}'>Escribe el tiempo como 1:46.0</span>")
            return
        goals.set_goal(self.combo.track, self.combo.car, t, self.combo.layout)
        self.set_combo(self.combo)

    def _goal_ideal(self):
        c = self.combo
        if c and c.ideal:
            goals.set_goal(c.track, c.car, round(c.ideal, 1), c.layout)
            self.set_combo(c)

    def _clear_goal(self):
        if self.combo:
            goals.clear(self.combo.track, self.combo.car, self.combo.layout)
            self.set_combo(self.combo)


class MyProgressDialog(QDialog):
    def __init__(self, parent, sessions, select: tuple[str, str, str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Mi progreso")
        self.resize(1560, 860)
        self.combos = ls.overview(sessions)
        lay = QVBoxLayout(self)
        head = QLabel("📈  Mi progreso")
        head.setObjectName("title")
        lay.addWidget(head)
        lay.addWidget(_note("Cada circuito con cada coche que has corrido. Elige uno para ver tu evolución, tu vuelta "
                            "ideal y fijar un objetivo."))
        split = QSplitter(Qt.Horizontal)
        self.table = make_table(["Circuito", "Coche", "Días", "Vueltas", "Mejor", "Ideal", "Objetivo", "Mejora",
                                 "Última vez"], stretch_col=1)
        self.table.setSortingEnabled(False)
        self.table.setIconSize(QSize(48, 22))
        split.addWidget(self.table)
        self.panel = ProgressPanel()
        split.addWidget(self.panel)
        split.setSizes([860, 700])
        lay.addWidget(split, 1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)
        self._fill()
        self.table.itemSelectionChanged.connect(self._selected)
        self.panel.goal_edit.returnPressed.connect(self._refresh_goals)
        for b in self.panel.findChildren(QPushButton):
            b.clicked.connect(self._refresh_goals)
        row = 0
        if select:
            row = next((r for r, c in enumerate(self.combos) if (c.track, c.car, c.layout) == select), 0)
        if self.combos:
            self.table.selectRow(row)
        else:
            self.panel.title.setText("Aún no hay sesiones tuyas con vueltas válidas")

    def _fill(self):
        t = self.table
        all_goals = goals.all_goals()
        t.setRowCount(len(self.combos))
        for r, c in enumerate(self.combos):
            t.setItem(r, 0, item(track_name(c)))
            car = item(car_label(c.car))
            car.setToolTip(c.car)
            pix = car_pix.pixmap(c.car, "thumb", 22)
            if pix:
                car.setIcon(QIcon(pix))
            t.setItem(r, 1, car)
            t.setItem(r, 2, item(c.days, Qt.AlignCenter))
            t.setItem(r, 3, item(c.laps, Qt.AlignCenter))
            t.setItem(r, 4, item(fmt_time(c.best), RIGHT, theme.PURPLE, bold=True))
            t.setItem(r, 5, item(fmt_time(c.ideal) if c.ideal else "", RIGHT, theme.MUTED))
            self._goal_cell(r, c, all_goals.get((c.track, c.car, c.layout)))
            gained = f"−{c.gained:.3f}" if c.gained >= 0.0005 else ""
            t.setItem(r, 7, item(gained, RIGHT, theme.GREEN))
            t.setItem(r, 8, item(c.last_day, Qt.AlignCenter, theme.MUTED))

    def _goal_cell(self, r, c, goal):
        if goal is None:
            self.table.setItem(r, 6, item("", RIGHT))
            return
        done = c.best <= goal
        self.table.setItem(r, 6, item(("✓ " if done else "") + fmt_time(goal), RIGHT,
                                      theme.GREEN if done else theme.AMBER))

    def _refresh_goals(self):
        all_goals = goals.all_goals()
        for r, c in enumerate(self.combos):
            self._goal_cell(r, c, all_goals.get((c.track, c.car, c.layout)))

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.panel.set_combo(self.combos[rows[0].row()])

