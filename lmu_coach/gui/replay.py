"""Repetición animada de una vuelta sobre el mapa, con la referencia como coche fantasma."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from ..laps import fmt_time
from . import theme

RATE = 50.0   # muestras/s de SessionData.lap_data
FOLLOW_SPAN = 260.0  # metros visibles alrededor del coche con «Seguir coche»


def _at(data: dict, key: str, t: float):
    """Valor de un canal en el instante t (interpolado)."""
    return float(np.interp(t, data["t"], data[key]))


class PedalBars(QWidget):
    """Gas y freno: tuyos (barra) y de la referencia (marca blanca)."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(90, 120)
        self.vals = (0.0, 0.0, None, None)

    def set_values(self, thr, brk, ref_thr, ref_brk):
        self.vals = (thr, brk, ref_thr, ref_brk)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        thr, brk, rthr, rbrk = self.vals
        h = self.height() - 18
        w = 26
        for i, (val, ref, color, label) in enumerate(((thr, rthr, theme.GREEN, "GAS"), (brk, rbrk, theme.RED, "FRENO"))):
            x = 10 + i * (w + 18)
            p.fillRect(QRectF(x, 0, w, h), QColor(theme.PANEL_2))
            fill = max(0.0, min(1.0, val))
            p.fillRect(QRectF(x, h * (1 - fill), w, h * fill), QColor(color))
            if ref is not None:
                y = h * (1 - max(0.0, min(1.0, ref)))
                p.fillRect(QRectF(x - 4, y - 1.5, w + 8, 3), QColor(theme.FG))
            p.setPen(QColor(theme.MUTED))
            p.setFont(QFont("Segoe UI", 7))
            p.drawText(QRectF(x - 10, h + 2, w + 20, 14), Qt.AlignCenter, label)


class ReplayView(QWidget):
    """Reproduce la vuelta seleccionada; `position_changed(distancia)` sincroniza gráficas y mapa pequeño."""

    position_changed = Signal(float)

    SPEEDS = [0.25, 0.5, 1.0, 2.0, 4.0]

    def __init__(self):
        super().__init__()
        self.lap = None      # datos por tiempo de tu vuelta (SessionData.lap_data)
        self.ref = None      # ídem de la referencia (o None)
        self.ref_by_d = None  # referencia por distancia (para el delta)
        self.t = 0.0
        self.duration = 0.0
        self.playing = False
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        self.plot = pg.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        left.addWidget(self.plot, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(46)
        self.play_btn.setToolTip("Reproducir / pausa (espacio)")
        self.play_btn.clicked.connect(self.toggle)
        self.restart_btn = QPushButton("⏮")
        self.restart_btn.setFixedWidth(40)
        self.restart_btn.setToolTip("Volver al inicio")
        self.restart_btn.clicked.connect(lambda: self.seek(0.0))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(lambda v: self.seek(v / 1000 * self.duration))
        self.slider.sliderPressed.connect(lambda: self.seek(self.slider.value() / 1000 * self.duration))
        self.time_lbl = QLabel("0:00.000")
        self.time_lbl.setMinimumWidth(150)
        self.speed = QComboBox()
        for s in self.SPEEDS:
            self.speed.addItem(f"×{s:g}", s)
        self.speed.setCurrentIndex(self.SPEEDS.index(1.0))
        self.speed.setMinimumWidth(70)
        self.follow = QCheckBox("Seguir coche")
        self.follow.setChecked(True)
        self.follow.toggled.connect(lambda on: self._update_view() if on else self.plot.autoRange())
        for w in (self.restart_btn, self.play_btn):
            controls.addWidget(w)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_lbl)
        controls.addWidget(self.speed)
        controls.addWidget(self.follow)
        left.addLayout(controls)
        lay.addLayout(left, 1)

        # Panel de datos en directo
        hud = QWidget()
        hud.setFixedWidth(280)
        g = QGridLayout(hud)
        g.setContentsMargins(10, 0, 0, 0)
        self.delta_lbl = QLabel("—")
        self.delta_lbl.setStyleSheet("font-size: 26pt; font-weight: 600;")
        self.delta_lbl.setAlignment(Qt.AlignCenter)
        g.addWidget(self.delta_lbl, 0, 0, 1, 3)
        self.delta_sub = QLabel("delta contra la referencia")
        self.delta_sub.setObjectName("subtitle")
        self.delta_sub.setAlignment(Qt.AlignCenter)
        g.addWidget(self.delta_sub, 1, 0, 1, 3)
        head = [QLabel(""), QLabel("Tú"), QLabel("Ref")]
        head[1].setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        head[2].setStyleSheet(f"color: {theme.REF}; font-weight: 600;")
        for c, w in enumerate(head):
            g.addWidget(w, 2, c)
        self.rows = {}
        for r, (key, label) in enumerate((("v", "Velocidad"), ("gear", "Marcha"), ("d", "Distancia")), start=3):
            name = QLabel(label)
            name.setObjectName("subtitle")
            me, ref = QLabel("—"), QLabel("—")
            me.setStyleSheet("font-size: 12pt; font-weight: 600;")
            ref.setStyleSheet(f"font-size: 12pt; color: {theme.REF};")
            g.addWidget(name, r, 0)
            g.addWidget(me, r, 1)
            g.addWidget(ref, r, 2)
            self.rows[key] = (me, ref)
        self.gap_lbl = QLabel("")
        self.gap_lbl.setObjectName("subtitle")
        self.gap_lbl.setWordWrap(True)
        g.addWidget(self.gap_lbl, 6, 0, 1, 3)
        self.pedals = PedalBars()
        g.addWidget(self.pedals, 7, 0, 1, 3)
        legend = QLabel(f"<span style='color:{theme.ACCENT}'>●</span> tu vuelta &nbsp; "
                        f"<span style='color:{theme.REF}'>●</span> fantasma (referencia)<br>"
                        "Espacio: play/pausa · ←/→: ±2 s")
        legend.setObjectName("subtitle")
        g.addWidget(legend, 8, 0, 1, 3)
        g.setRowStretch(9, 1)
        lay.addWidget(hud)

        self.car = pg.ScatterPlotItem(size=16, brush=pg.mkBrush(theme.ACCENT), pen=pg.mkPen("#ffffff", width=2))
        self.ghost = pg.ScatterPlotItem(size=14, brush=pg.mkBrush(QColor(201, 204, 212, 170)),
                                        pen=pg.mkPen(theme.BG, width=1.5))
        self.setFocusPolicy(Qt.StrongFocus)

    # --- datos -------------------------------------------------------------

    def load(self, lap: dict, ref: dict | None, ref_by_d: dict | None, zones=()):
        """lap/ref: por tiempo (t, d, x, y, v, thr, brk, gear). ref_by_d: referencia por distancia."""
        self.pause()
        self.lap, self.ref, self.ref_by_d = lap, ref, ref_by_d
        self.duration = float(lap["t"][-1]) if len(lap["t"]) else 0.0
        self.plot.clear()
        base = ref if ref is not None else lap
        self.plot.plot(base["x"], base["y"], pen=pg.mkPen("#2e313a", width=14))   # asfalto
        self.plot.plot(lap["x"], lap["y"], pen=pg.mkPen(QColor(63, 182, 255, 90), width=2))
        for z in zones:
            i = int(np.clip(np.searchsorted(lap["d"], z.start), 0, len(lap["x"]) - 1))
            label = pg.TextItem(f"F{z.idx}", color=theme.AMBER, anchor=(0.5, 0.5))
            label.setPos(float(lap["x"][i]), float(lap["y"][i]))
            self.plot.addItem(label)
        if ref is not None:
            self.plot.addItem(self.ghost)
        self.plot.addItem(self.car)
        self.seek(0.0)

    # --- reproducción --------------------------------------------------------

    def toggle(self):
        self.pause() if self.playing else self.play()

    def play(self):
        if not self.lap:
            return
        if self.t >= self.duration:
            self.t = 0.0
        self.playing = True
        self.play_btn.setText("⏸")
        self._clock.start()
        self._timer.start()

    def pause(self):
        self.playing = False
        self.play_btn.setText("▶")
        self._timer.stop()

    def seek(self, t: float):
        if not self.lap:
            return
        self.t = max(0.0, min(self.duration, t))
        self._clock.restart()
        self._render()

    def _tick(self):
        dt = self._clock.restart() / 1000.0
        self.t += dt * self.speed.currentData()
        if self.t >= self.duration:
            self.t = self.duration
            self.pause()
        self._render()

    def _render(self):
        lap, ref, t = self.lap, self.ref, self.t
        x, y, d = _at(lap, "x", t), _at(lap, "y", t), _at(lap, "d", t)
        self.car.setData([x], [y])
        me_v, me_gear = _at(lap, "v", t), int(round(_at(lap, "gear", t)))
        self.rows["v"][0].setText(f"{me_v:.0f} km/h")
        self.rows["gear"][0].setText(f"{me_gear}")
        self.rows["d"][0].setText(f"{max(d, 0):.0f} m")
        ref_thr = ref_brk = None
        if ref is not None:
            # El fantasma va donde estaba la referencia en ese mismo instante
            t_ref = min(t, float(ref["t"][-1]))
            gx, gy, gd = _at(ref, "x", t_ref), _at(ref, "y", t_ref), _at(ref, "d", t_ref)
            self.ghost.setData([gx], [gy])
            self.rows["v"][1].setText(f"{_at(ref, 'v', t_ref):.0f} km/h")
            self.rows["gear"][1].setText(f"{int(round(_at(ref, 'gear', t_ref)))}")
            self.rows["d"][1].setText(f"{max(gd, 0):.0f} m")
            # Delta: tiempo que tardó la referencia en llegar a tu misma posición
            rb = self.ref_by_d
            ref_time_here = float(np.interp(d, rb["d"], rb["t"])) if d >= 0 else 0.0
            delta = t - ref_time_here if d >= 0 else 0.0
            col = theme.GREEN if delta < 0 else theme.RED
            self.delta_lbl.setText(f"{delta:+.3f}")
            self.delta_lbl.setStyleSheet(f"font-size: 26pt; font-weight: 600; color: {col};")
            gap_m = d - gd
            self.gap_lbl.setText(f"{'Vas por delante' if gap_m > 0 else 'Vas por detrás'} del fantasma "
                                 f"{abs(gap_m):.0f} m")
            # pedales de la referencia en tu misma posición (no en el mismo instante)
            ref_thr = float(np.interp(d, rb["d"], rb["thr"]))
            ref_brk = float(np.interp(d, rb["d"], rb["brk"]))
        else:
            self.delta_lbl.setText("—")
            self.gap_lbl.setText("Sin referencia: elige una en «Comparar con»")
            for key in self.rows:
                self.rows[key][1].setText("—")
        self.pedals.set_values(_at(lap, "thr", t), _at(lap, "brk", t), ref_thr, ref_brk)
        self.time_lbl.setText(f"{fmt_time(t) if t > 0 else '0:00.000'} / {fmt_time(self.duration)}")
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(t / self.duration * 1000) if self.duration else 0)
            self.slider.blockSignals(False)
        self._update_view(x, y)
        self.position_changed.emit(d)

    def _update_view(self, x=None, y=None):
        if not self.follow.isChecked() or not self.lap:
            return
        if x is None:
            x, y = _at(self.lap, "x", self.t), _at(self.lap, "y", self.t)
        s = FOLLOW_SPAN / 2
        self.plot.setRange(xRange=(x - s, x + s), yRange=(y - s, y + s), padding=0)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space:
            self.toggle()
        elif e.key() == Qt.Key_Left:
            self.seek(self.t - 2)
        elif e.key() == Qt.Key_Right:
            self.seek(self.t + 2)
        else:
            super().keyPressEvent(e)

    def hideEvent(self, e):
        self.pause()
        super().hideEvent(e)
