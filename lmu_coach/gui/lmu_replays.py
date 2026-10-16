"""Ventana «Repeticiones de LMU»: reproduce los .Vcr del juego con todos los coches sobre el mapa."""
import zlib
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QElapsedTimer, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import replay_import
from ..sessions import find_lmu_dir
from . import theme

SESSIONS = {"PRACTICE": "Libres", "QUALIFY": "Clasificación", "RACE": "Carrera", "WARMUP": "Warm-up"}
SPEEDS = [1, 2, 5, 10, 30, 60]
MAX_STEP = 60.0  # m entre muestras a 5 Hz (~1000 km/h): más es un salto a boxes, no cuenta como distancia


def hms(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def car_color(vehicle_file: str) -> QColor:
    """Color estable por modelo de coche (los compañeros de marca comparten color)."""
    model = vehicle_file.split("_")[-1] if vehicle_file else "?"
    h = (zlib.crc32(model.encode()) % 360) / 360.0
    return QColor.fromHsvF(h, 0.65, 1.0)


class _Loader(QThread):
    progress = Signal(float)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.cancel = False

    def run(self):
        try:
            data = replay_import.load(Path(self.path), self.progress.emit, lambda: self.cancel)
            self.done.emit(data)
        except InterruptedError:
            pass
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class ReplayViewer(QWidget):
    def __init__(self, player_name: str = ""):
        super().__init__()
        self.player = player_name.casefold()
        self.data = None
        self.t = 0.0
        self.follow = None
        self.playing = False
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)

        split = QSplitter(Qt.Horizontal)
        self.plot = pg.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        split.addWidget(self.plot)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Pos", "Piloto", "Equipo", "#", "km/h"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(22)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)  # el equipo se recorta; el piloto, nunca
        self.table.itemClicked.connect(self._row_clicked)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        hint = QLabel("Orden aproximado por distancia recorrida · clic en un piloto para seguirlo")
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        rl.addWidget(hint)
        rl.addWidget(self.table, 1)
        split.addWidget(right)
        split.setSizes([760, 470])
        lay.addWidget(split, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(46)
        self.play_btn.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.sliderMoved.connect(self._slider_moved)
        self.time_lbl = QLabel("0:00")
        self.time_lbl.setMinimumWidth(130)
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"×{s}", s)
        self.names = QCheckBox("Nombres")
        self.names.setChecked(True)
        self.names.toggled.connect(lambda _: self._render())
        self.all_btn = QPushButton("Ver todo el circuito")
        self.all_btn.clicked.connect(self._unfollow)
        for w in (self.play_btn,):
            controls.addWidget(w)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_lbl)
        controls.addWidget(self.speed)
        controls.addWidget(self.names)
        controls.addWidget(self.all_btn)
        lay.addLayout(controls)

        self.dots = pg.ScatterPlotItem(pxMode=True)
        self.labels = {}

    # --- datos -------------------------------------------------------------

    def load(self, data: replay_import.ReplayData):
        self.pause()
        self.data = data
        self.follow = None
        # tu coche: cualquier plaza en la que hayas conducido (en resistencia lo comparte tu equipo)
        self.mine = {p.vehicle for p in data.participants if self.player and p.driver.casefold() == self.player}
        s = data.session
        self.title.setText(f"{s.get('eventTitle') or s.get('sceneDesc', '')}  ·  {SESSIONS.get(s.get('session'), s.get('session', ''))}")
        self.subtitle.setText(f"{replay_import.display_name(Path(data.path).stem)}  ·  {len(data.cars)} coches  ·  duración {hms(data.t1 - data.t0)}"
                              f"  ·  circuito {data.track}")
        # distancia acumulada por coche (para el orden aproximado)
        self.cum = {}
        for vid, (t, x, z) in data.cars.items():
            step = np.hypot(np.diff(x), np.diff(z))
            step[step > MAX_STEP] = 0
            self.cum[vid] = np.concatenate([[0.0], np.cumsum(step)])
        self.plot.clear()
        # trazado del circuito: posiciones de todos los coches, muestreadas
        xs = np.concatenate([v[1][::10] for v in data.cars.values()])
        zs = np.concatenate([v[2][::10] for v in data.cars.values()])
        self.plot.addItem(pg.ScatterPlotItem(xs, zs, size=2, pen=None, brush=pg.mkBrush(70, 74, 84, 140), pxMode=True))
        self.plot.addItem(self.dots)
        self.labels = {}
        for vid in data.cars:
            lbl = pg.TextItem("", color=theme.FG, anchor=(0, 1.2))
            lbl.setZValue(10)
            self.plot.addItem(lbl)
            self.labels[vid] = lbl
        self.speed.setCurrentIndex(SPEEDS.index(10) if data.t1 - data.t0 > 1800 else 0)
        self.seek(data.t0)
        self.plot.autoRange()

    # --- reproducción --------------------------------------------------------

    def toggle(self):
        self.pause() if self.playing else self.play()

    def play(self):
        if not self.data:
            return
        self.playing = True
        self.play_btn.setText("⏸")
        self._clock.start()
        self._timer.start()

    def pause(self):
        self.playing = False
        self.play_btn.setText("▶")
        self._timer.stop()

    def seek(self, t):
        if not self.data:
            return
        self.t = min(max(t, self.data.t0), self.data.t1)
        self._clock.restart()
        self._render()

    def _slider_moved(self, v):
        d = self.data
        if d:
            self.seek(d.t0 + v / 10000 * (d.t1 - d.t0))

    def _tick(self):
        self.t += self._clock.restart() / 1000.0 * self.speed.currentData()
        if self.t >= self.data.t1:
            self.t = self.data.t1
            self.pause()
        self._render()

    def _state(self, vid, t):
        tt, x, z = self.data.cars[vid]
        if t < tt[0] or t > tt[-1] + 2:
            return None
        px, pz = float(np.interp(t, tt, x)), float(np.interp(t, tt, z))
        qx, qz = float(np.interp(t - 0.4, tt, x)), float(np.interp(t - 0.4, tt, z))
        v = np.hypot(px - qx, pz - qz) / 0.4 * 3.6
        dist = float(np.interp(t, tt, self.cum[vid]))
        return px, pz, (v if v < 450 else 0.0), dist

    def _render(self):
        d = self.data
        if not d:
            return
        t = self.t
        spots, rows = [], []
        for vid in d.cars:
            st = self._state(vid, t)
            lbl = self.labels[vid]
            if st is None:
                lbl.setText("")
                continue
            px, pz, v, dist = st
            e = d.entry(vid, t)
            name = e.driver if e else f"Coche {vid}"
            is_me = vid in self.mine
            focus = vid == self.follow
            color = QColor(theme.ACCENT) if is_me else car_color(e.vehicle_file if e else "")
            spots.append({"pos": (px, pz), "size": 15 if (is_me or focus) else 10,
                          "brush": pg.mkBrush(color),
                          "pen": pg.mkPen("#ffffff" if (is_me or focus) else "#101114", width=2 if focus else 1),
                          "data": vid})
            show = self.names.isChecked() and (is_me or focus or self.follow is None)
            lbl.setText(name.split(" ")[-1] if show else "")
            lbl.setColor(QColor(theme.ACCENT) if is_me else QColor(theme.FG))
            lbl.setPos(px, pz)
            rows.append((dist, vid, name, e, v, is_me))
        self.dots.setData(spots)
        rows.sort(key=lambda r: -r[0])
        self._fill_table(rows)
        self.time_lbl.setText(f"{hms(t - d.t0)} / {hms(d.t1 - d.t0)}")
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int((t - d.t0) / max(d.t1 - d.t0, 1e-6) * 10000))
            self.slider.blockSignals(False)
        if self.follow is not None:
            st = self._state(self.follow, t)
            if st:
                s = 300
                self.plot.setRange(xRange=(st[0] - s, st[0] + s), yRange=(st[1] - s, st[1] + s), padding=0)

    def _fill_table(self, rows):
        t = self.table
        t.setRowCount(len(rows))
        for i, (dist, vid, name, e, v, is_me) in enumerate(rows):
            vals = [str(i + 1), name, e.team if e else "", e.number if e else "", f"{v:.0f}"]
            for c, val in enumerate(vals):
                it = t.item(i, c)
                if it is None:
                    it = QTableWidgetItem()
                    t.setItem(i, c, it)
                it.setText(val)
                it.setData(Qt.UserRole, vid)
                it.setForeground(QColor(theme.ACCENT) if is_me else QColor(theme.FG if c != 2 else theme.MUTED))
                if c in (0, 3, 4):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def _row_clicked(self, item):
        self.follow = item.data(Qt.UserRole)
        self._render()

    def _unfollow(self):
        self.follow = None
        self.plot.autoRange()
        self._render()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space:
            self.toggle()
        elif e.key() == Qt.Key_Right:
            self.seek(self.t + 10 * self.speed.currentData())
        elif e.key() == Qt.Key_Left:
            self.seek(self.t - 10 * self.speed.currentData())
        else:
            super().keyPressEvent(e)


class LmuReplaysWindow(QMainWindow):
    """Lista de repeticiones de LMU + visor."""

    def __init__(self, parent=None, player_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Repeticiones de LMU · LMU Coach")
        self.resize(1500, 900)
        self.loader = None
        lmu = find_lmu_dir()
        self.folder = (lmu / "UserData" / "Replays") if lmu else None

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 6, 12)
        head = QLabel("REPETICIONES DE LMU")
        head.setObjectName("section")
        ll.addWidget(head)
        self.list = QTableWidget(0, 4)
        self.list.setHorizontalHeaderLabels(["Repetición", "Sesión", "Coches", "MB"])
        self.list.verticalHeader().setVisible(False)
        self.list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setShowGrid(False)
        self.list.setAlternatingRowColors(True)
        self.list.verticalHeader().setDefaultSectionSize(24)
        hh = self.list.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        self.list.itemDoubleClicked.connect(lambda *_: self._open_selected())
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        open_btn = QPushButton("▶  Abrir")
        open_btn.setObjectName("coach")
        open_btn.clicked.connect(self._open_selected)
        other = QPushButton("Otro archivo…")
        other.clicked.connect(self._open_other)
        row.addWidget(open_btn)
        row.addWidget(other)
        ll.addLayout(row)
        note = QLabel("Las repeticiones grandes (carreras) tardan unos segundos la primera vez; "
                      "después se abren al instante.")
        note.setObjectName("subtitle")
        note.setWordWrap(True)
        ll.addWidget(note)
        split.addWidget(left)

        self.stack = QStackedWidget()
        empty = QLabel("Elige una repetición de la lista")
        empty.setAlignment(Qt.AlignCenter)
        empty.setObjectName("subtitle")
        loading = QWidget()
        ld = QVBoxLayout(loading)
        ld.addStretch(1)
        self.loading_lbl = QLabel("Leyendo la repetición…")
        self.loading_lbl.setAlignment(Qt.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedWidth(400)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(lambda: (self._cancel(), self.stack.setCurrentIndex(0)))
        ld.addWidget(self.loading_lbl)
        ld.addWidget(self.bar, 0, Qt.AlignHCenter)
        ld.addWidget(cancel, 0, Qt.AlignHCenter)
        ld.addStretch(1)
        self.viewer = ReplayViewer(player_name)
        for w in (empty, loading, self.viewer):
            self.stack.addWidget(w)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(6, 12, 12, 12)
        wl.addWidget(self.stack)
        split.addWidget(wrap)
        split.setSizes([430, 1070])
        self.setCentralWidget(split)
        self._fill_list()

    def _fill_list(self):
        self.items = replay_import.list_replays(self.folder) if self.folder and self.folder.is_dir() else []
        t = self.list
        t.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            vals = [it["name"], SESSIONS.get(it["session"], it["session"]), str(it["cars"]), f"{it['size'] / 1e6:.0f}"]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                cell.setData(Qt.UserRole, it["path"])
                if c == 0:
                    cell.setToolTip(f"{it['event']}\n{it['path']}")
                if c in (2, 3):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, cell)

    def _open_selected(self):
        rows = self.list.selectionModel().selectedRows()
        if rows:
            self.open(self.list.item(rows[0].row(), 0).data(Qt.UserRole))

    def _open_other(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir repetición de LMU", str(self.folder or ""),
                                              "Repeticiones de LMU (*.Vcr *.vcr)")
        if path:
            self.open(path)

    def open(self, path):
        self._cancel()
        self.viewer.pause()
        self.stack.setCurrentIndex(1)
        self.bar.setValue(0)
        self.loading_lbl.setText(f"Leyendo {Path(path).name}…")
        self.loader = _Loader(path)
        self.loader.progress.connect(lambda f: self.bar.setValue(int(f * 1000)))
        self.loader.done.connect(self._loaded)
        self.loader.failed.connect(self._failed)
        self.loader.start()

    def _loaded(self, data):
        self.viewer.load(data)
        self.stack.setCurrentWidget(self.viewer)
        self.viewer.setFocus()
        self._fill_list()

    def _failed(self, msg):
        self.stack.setCurrentIndex(0)
        QMessageBox.warning(self, "No se pudo leer la repetición", msg)

    def _cancel(self):
        if self.loader and self.loader.isRunning():
            self.loader.cancel = True
            self.loader.wait(5000)

    def closeEvent(self, e):
        self._cancel()
        self.viewer.pause()
        super().closeEvent(e)
