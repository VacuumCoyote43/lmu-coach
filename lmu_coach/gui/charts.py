"""Gráficas de telemetría (pyqtgraph): canales por distancia y mapa del circuito."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from . import theme

pg.setConfigOptions(antialias=True, background=theme.PANEL, foreground=theme.MUTED)


def _pen(color, width=1.6, dash=False):
    p = pg.mkPen(color, width=width)
    if dash:
        p.setStyle(Qt.DashLine)
    return p


class TelemetryCharts(pg.GraphicsLayoutWidget):
    """Delta, velocidad, pedales, volante y marcha frente a la distancia, con cursor compartido."""

    cursor_moved = Signal(float)  # distancia en metros

    ROWS = [  # clave, título, altura relativa
        ("delta", "Delta (s)", 2),
        ("v", "Velocidad (km/h)", 3),
        ("pedals", "Gas / Freno", 2),
        ("steer", "Volante", 1.5),
        ("gear", "Marcha", 1.2),
    ]

    def __init__(self):
        super().__init__()
        self.ci.layout.setSpacing(2)
        self.plots = {}
        self.cursors = []
        first = None
        for row, (key, title, stretch) in enumerate(self.ROWS):
            p = self.addPlot(row=row, col=0)
            p.showGrid(x=True, y=True, alpha=0.12)
            p.setMenuEnabled(False)
            p.hideButtons()
            p.getAxis("left").setWidth(48)
            p.getAxis("left").enableAutoSIPrefix(False)
            p.setLabel("left", title, **{"font-size": "8pt"})
            if row < len(self.ROWS) - 1:
                p.getAxis("bottom").setStyle(showValues=False)
            else:
                p.setLabel("bottom", "Distancia (m)")
            p.setMouseEnabled(x=True, y=False)
            p.setAutoVisible(y=True)  # al hacer zoom, el eje Y se ajusta a lo visible
            if first is None:
                first = p
            else:
                p.setXLink(first)
            self.ci.layout.setRowStretchFactor(row, int(stretch * 10))
            line = pg.InfiniteLine(angle=90, pen=_pen("#ffffff55", 1))
            p.addItem(line, ignoreBounds=True)
            self.cursors.append(line)
            self.plots[key] = p
        self.readout = pg.TextItem(anchor=(0, 0), color=theme.FG)
        self.plots["v"].addItem(self.readout, ignoreBounds=True)
        self._data = None
        self._regions = []
        self.scene().sigMouseMoved.connect(self._on_mouse)

    def clear_all(self):
        for p in self.plots.values():
            for item in list(p.listDataItems()):
                p.removeItem(item)
        for r, p in self._regions:
            p.removeItem(r)
        self._regions = []
        self._data = None
        self.readout.setText("")

    def display(self, lap: dict, ref: dict | None, delta: np.ndarray | None, zones=()):
        """lap/ref: diccionarios por distancia (analysis.by_distance)."""
        self.clear_all()
        self._data = (lap, ref, delta)
        d = lap["d"]
        P = self.plots
        if delta is not None:
            P["delta"].addItem(pg.PlotDataItem(d, np.zeros_like(d), pen=_pen("#ffffff40", 1)))
            fill_pos = pg.PlotDataItem(d, np.maximum(delta, 0), pen=None, fillLevel=0, brush=QColor(255, 90, 90, 70))
            fill_neg = pg.PlotDataItem(d, np.minimum(delta, 0), pen=None, fillLevel=0, brush=QColor(46, 204, 113, 70))
            P["delta"].addItem(fill_pos)
            P["delta"].addItem(fill_neg)
            P["delta"].addItem(pg.PlotDataItem(d, delta, pen=_pen(theme.FG, 1.4)))
        if ref is not None:
            P["v"].plot(ref["d"], ref["v"], pen=_pen(theme.REF, 1.3, dash=True))
            P["pedals"].plot(ref["d"], ref["thr"] * 100, pen=_pen("#2ecc7188", 1.2, dash=True))
            P["pedals"].plot(ref["d"], ref["brk"] * 100, pen=_pen("#ff5a5a88", 1.2, dash=True))
            P["steer"].plot(ref["d"], ref["steer"] * 100, pen=_pen(theme.REF, 1.1, dash=True))
            P["gear"].plot(ref["d"], ref["gear"], pen=_pen(theme.REF, 1.1, dash=True))
        P["v"].plot(d, lap["v"], pen=_pen(theme.ACCENT, 1.8))
        P["pedals"].plot(d, lap["thr"] * 100, pen=_pen(theme.GREEN, 1.6))
        P["pedals"].plot(d, lap["brk"] * 100, pen=_pen(theme.RED, 1.6))
        P["steer"].plot(d, lap["steer"] * 100, pen=_pen(theme.ACCENT, 1.4))
        P["gear"].plot(d, lap["gear"], pen=_pen(theme.ACCENT, 1.6))
        P["pedals"].setYRange(-5, 105, padding=0)
        for z in zones:
            r = pg.LinearRegionItem((z.start, z.apex), movable=False, brush=QColor(255, 176, 32, 22),
                                    pen=pg.mkPen(None))
            P["v"].addItem(r)
            label = pg.TextItem(f"F{z.idx}", color=theme.AMBER, anchor=(0.5, 1))
            label.setPos((z.start + z.apex) / 2, float(lap["v"].max()) + 12)
            P["v"].addItem(label)
            self._regions += [(r, P["v"]), (label, P["v"])]
        P["v"].setXRange(0, float(d[-1]), padding=0.01)

    def zoom_to(self, start, end):
        self.plots["v"].setXRange(start, end, padding=0.05)

    def reset_zoom(self):
        if self._data:
            self.plots["v"].setXRange(0, float(self._data[0]["d"][-1]), padding=0.01)

    def set_cursor(self, dist):
        for c in self.cursors:
            c.setPos(dist)
        if not self._data:
            return
        lap, ref, delta = self._data
        i = int(np.clip(np.searchsorted(lap["d"], dist), 0, len(lap["d"]) - 1))
        txt = f"{dist:.0f} m   {lap['v'][i]:.0f} km/h"
        if ref is not None:
            j = int(np.clip(np.searchsorted(ref["d"], dist), 0, len(ref["d"]) - 1))
            txt += f"  (ref {ref['v'][j]:.0f})"
        if delta is not None:
            txt += f"   Δ {delta[i]:+.3f}"
        self.readout.setText(txt)
        vb = self.plots["v"].getViewBox()
        (x0, _), (_, y1) = vb.viewRange()
        self.readout.setPos(x0, y1)

    def _on_mouse(self, pos):
        for p in self.plots.values():
            if p.sceneBoundingRect().contains(pos):
                x = p.getViewBox().mapSceneToView(pos).x()
                self.set_cursor(x)
                self.cursor_moved.emit(x)
                return


class TrackMap(pg.PlotWidget):
    """Trazada de tu vuelta coloreada por ganancia (verde) o pérdida (rojo) frente a la referencia."""

    def __init__(self):
        super().__init__()
        self.setAspectLocked(True)
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.setMenuEnabled(False)
        self.hideButtons()
        self.dot = pg.ScatterPlotItem(size=11, brush=pg.mkBrush(theme.FG), pen=pg.mkPen(theme.BG, width=2))
        self._lap = None

    def display(self, lap: dict, ref: dict | None, delta: np.ndarray | None, zones=()):
        self.clear()
        self._lap = lap
        x, y = lap["x"], lap["y"]
        if ref is not None:
            self.plot(ref["x"], ref["y"], pen=_pen("#ffffff30", 6))
        if delta is None:
            self.plot(x, y, pen=_pen(theme.ACCENT, 2.5))
        else:
            # Pendiente del delta suavizada (~40 m): >0 pierdes, <0 ganas
            k = 20
            slope = np.convolve(np.gradient(delta), np.ones(k) / k, mode="same")
            sign = np.where(slope > 0.0004, 1, np.where(slope < -0.0004, -1, 0))
            start = 0
            for i in range(1, len(sign) + 1):
                if i == len(sign) or sign[i] != sign[start]:
                    color = {1: theme.RED, -1: theme.GREEN, 0: "#8b8f99"}[int(sign[start])]
                    self.plot(x[start:i + 1], y[start:i + 1], pen=_pen(color, 3))
                    start = i
        # frenadas: un punto en cada una y el nombre solo si no se pisa con otro (todos al pasar el ratón)
        span = max(float(np.ptp(x)), float(np.ptp(y)), 1.0)
        pts, shown = [], []
        for z in zones:
            i = int(np.clip(np.searchsorted(lap["d"], z.start), 0, len(x) - 1))
            px, py = float(x[i]), float(y[i])
            pts.append({"pos": (px, py), "data": f"F{z.idx}"})
            if all(np.hypot(px - qx, py - qy) > span * 0.18 for qx, qy in shown):
                shown.append((px, py))
                t = pg.TextItem(f"F{z.idx}", color=theme.AMBER, anchor=(-0.15, 1.1))
                t.setPos(px, py)
                self.addItem(t)
        if pts:
            self.addItem(pg.ScatterPlotItem(pts, size=6, brush=pg.mkBrush(theme.AMBER), pen=None, hoverable=True,
                                            hoverSize=10, tip=lambda x, y, data: data))
        self.addItem(self.dot)
        self.autoRange()

    def set_cursor(self, dist):
        if self._lap is None:
            return
        i = int(np.clip(np.searchsorted(self._lap["d"], dist), 0, len(self._lap["d"]) - 1))
        self.dot.setData([float(self._lap["x"][i])], [float(self._lap["y"][i])])
