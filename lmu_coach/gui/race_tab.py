"""Pestaña «Resumen de carrera»: lo que apuntó el coach en directo (posición por vuelta, diferencias,
ritmo frente a tu clase y paradas). La telemetría de LMU solo trae tu coche, así que sin el coach abierto
durante la carrera no hay resumen."""
import pyqtgraph as pg
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .. import racelog
from ..laps import fmt_time


def _stat(title, value, color=None, sub=""):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(10, 6, 10, 6)
    t = QLabel(title)
    t.setObjectName("section")
    val = QLabel(value)
    val.setStyleSheet(f"font-size: 17pt; font-weight: 600; color: {color or theme.FG};")
    v.addWidget(t)
    v.addWidget(val)
    if sub:
        s = QLabel(sub)
        s.setObjectName("subtitle")
        v.addWidget(s)
    w.setStyleSheet(f"QWidget {{ background: {theme.PANEL_2}; border-radius: 6px; }}")
    return w


class RaceSummaryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.stats = QGridLayout()
        self.lay.addLayout(self.stats)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        self.msg.setObjectName("subtitle")
        self.lay.addWidget(self.msg)
        plots = QHBoxLayout()
        self.pos_plot = pg.PlotWidget()
        self.pos_plot.showGrid(x=True, y=True, alpha=0.15)
        self.pos_plot.setLabel("left", "Posición en tu clase")
        self.pos_plot.setLabel("bottom", "Vuelta")
        self.pos_plot.invertY(True)
        self.gap_plot = pg.PlotWidget()
        self.gap_plot.showGrid(x=True, y=True, alpha=0.15)
        self.gap_plot.setLabel("left", "Diferencia (s)")
        self.gap_plot.setLabel("bottom", "Vuelta")
        self.gap_plot.addLegend(offset=(10, 10))
        plots.addWidget(self.pos_plot)
        plots.addWidget(self.gap_plot)
        self.lay.addLayout(plots, 1)

    def _clear_stats(self):
        while self.stats.count():
            w = self.stats.takeAt(0).widget()
            if w:
                w.setParent(None)

    def set_session(self, info):
        self._clear_stats()
        self.pos_plot.clear()
        self.gap_plot.clear()
        if info.session_type != "Race":
            self._empty("El resumen de carrera solo existe para las carreras.")
            return
        d = racelog.find(info.track, info.car, info.recorded)
        if d is None:
            self._empty("No hay resumen de esta carrera. Lo apunta el modo coach en directo (la telemetría de LMU "
                        "solo trae tu coche): abre el modo coach antes de la próxima carrera y al acabar aparecerá "
                        "aquí la posición vuelta a vuelta, las diferencias y tu ritmo frente a tu clase.")
            return
        self.pos_plot.show()
        self.gap_plot.show()
        gained = d["start"] - d["finish"]
        gcol = theme.GREEN if gained > 0 else theme.RED if gained < 0 else theme.MUTED
        gtxt = f"+{gained}" if gained > 0 else str(gained)
        self.stats.addWidget(_stat("Final", f"P{d['finish']} / {d['of']}", theme.ACCENT, d.get("cls", "")), 0, 0)
        self.stats.addWidget(_stat("Salida", f"P{d['start']}", None, "en tu clase"), 0, 1)
        self.stats.addWidget(_stat("Posiciones", gtxt, gcol), 0, 2)
        self.stats.addWidget(_stat("Tu mejor vuelta", fmt_time(d["best"]) if d.get("best") else "—", theme.PURPLE,
                                   (f"mejor de tu clase {fmt_time(d['class_best'])}" if d.get("class_best") else "")),
                             0, 3)
        pace, med = d.get("pace"), d.get("class_median_best")
        sub = f"mediana de los mejores de tu clase {fmt_time(med)}" if med else ""
        self.stats.addWidget(_stat("Tu ritmo", fmt_time(pace) if pace else "—", None, sub), 0, 4)
        self.stats.addWidget(_stat("Paradas", str(d.get("stops", 0)), None, f"{d.get('laps', 0)} vueltas"), 0, 5)
        self.msg.setText(self._verdict(d))

        log = d.get("log") or []
        if log:
            laps = [r[0] for r in log]
            self.pos_plot.plot(laps, [r[1] for r in log], pen=pg.mkPen(theme.ACCENT, width=2.5), symbol="o",
                               symbolSize=6, symbolBrush=theme.ACCENT, stepMode=None)
            pits = [r for r in log if r[4]]
            if pits:
                self.pos_plot.addItem(pg.ScatterPlotItem([r[0] for r in pits], [r[1] for r in pits], size=13,
                                                         brush=None, pen=pg.mkPen(theme.AMBER, width=2)))
            self.pos_plot.setYRange(0.5, max(r[1] for r in log) + 0.5)
            ahead = [(r[0], r[2]) for r in log if r[2] is not None]
            behind = [(r[0], -r[3]) for r in log if r[3] is not None]
            if ahead:
                self.gap_plot.plot([a for a, _ in ahead], [b for _, b in ahead], pen=pg.mkPen(theme.RED, width=2),
                                   name="al de delante")
            if behind:
                self.gap_plot.plot([a for a, _ in behind], [b for _, b in behind],
                                   pen=pg.mkPen(theme.GREEN, width=2), name="al de detrás (abajo)")
            self.gap_plot.addItem(pg.InfiniteLine(0, angle=0, pen=pg.mkPen(theme.MUTED, width=1)))

    def _verdict(self, d) -> str:
        parts = []
        pace, med, best = d.get("pace"), d.get("class_median_best"), d.get("best")
        if best and d.get("class_best"):
            diff = best - d["class_best"]
            parts.append("Hiciste la vuelta rápida de tu clase." if diff <= 0 else
                         f"Tu mejor vuelta, a {diff:.3f} s de la mejor de tu clase.")
        if pace and med:
            parts.append(f"Ritmo de carrera {pace - med:+.3f} s frente a la mediana de los mejores de tu clase.")
        parts.append("Círculos naranjas: vueltas en las que entraste en boxes.")
        return "  ".join(parts)

    def _empty(self, text):
        self.msg.setText(text)
        self.pos_plot.hide()
        self.gap_plot.hide()
