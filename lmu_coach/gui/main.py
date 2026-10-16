"""Ventana principal: sesiones de LMU, análisis de vueltas y lanzador del modo coach."""
import sys
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QProcess, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from .. import analysis, share
from ..laps import LapStore, fmt_time
from ..paths import ASSETS_DIR, IMPORTED_DIR, INDEX_PATH, LAPS_DIR, PROJECT_ROOT, coach_command
from ..sessions import SessionData, SessionIndex, SessionInfo, find_telemetry_dir
from . import theme
from .charts import TelemetryCharts, TrackMap
from .diagnostics_dialog import DiagnosticsDialog

IMPORTABLE = (share.EXTENSION, ".zip", ".duckdb")
SESSION_TYPES = {"Practice": "Libres", "Qualify": "Clasificación", "Race": "Carrera", "Warmup": "Warm-up"}
SHORT_TRACKS = {
    "Algarve International Circuit": "Portimão",
    "Autódromo José Carlos Pace": "Interlagos",
    "Autodromo Nazionale Monza": "Monza",
    "Circuit of the Americas": "COTA",
    "Circuit de la Sarthe": "Le Mans",
    "Circuit de Spa-Francorchamps": "Spa",
    "Bahrain International Circuit": "Bahrain",
    "Lusail International Circuit": "Qatar",
    "Michelin Raceway Road Atlanta": "Road Atlanta",
    "Sebring International Raceway": "Sebring",
    "Grand Prix of Long Beach": "Long Beach",
    "Silverstone Circuit": "Silverstone",
    "Fuji Speedway": "Fuji",
    "Autodromo Enzo e Dino Ferrari": "Imola",
}


def short_track(name: str) -> str:
    return SHORT_TRACKS.get(name, name)


def fmt_sec(s: float) -> str:
    return f"{s:.3f}" if s > 0 else "—"


def item(text, align=Qt.AlignLeft | Qt.AlignVCenter, color=None, sort_key=None, bold=False, cls=QTableWidgetItem):
    it = cls(str(text))
    it.setTextAlignment(align)
    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    if color:
        it.setForeground(QBrush(QColor(color)))
    if sort_key is not None:
        it.setData(Qt.UserRole + 1, sort_key)
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    return it


class SortItem(QTableWidgetItem):
    """Ordena por la clave numérica guardada (tiempos, fechas) en vez de por el texto."""

    def __lt__(self, other):
        a, b = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


def sitem(text, sort_key, **kw):
    return item(text, sort_key=sort_key, cls=SortItem, **kw)


def make_table(headers, stretch_col=None):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.verticalHeader().setDefaultSectionSize(26)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    h.setHighlightSections(False)
    if stretch_col is not None:
        h.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
    return t


def section(text):
    lab = QLabel(text)
    lab.setObjectName("section")
    return lab


# --------------------------------------------------------------------------- indexado


class IndexWorker(QThread):
    progress = Signal(int, int)
    done = Signal(list)

    def __init__(self, index: SessionIndex):
        super().__init__()
        self.index = index

    def run(self):
        self.done.emit(self.index.refresh(lambda i, n: self.progress.emit(i, n)))


# --------------------------------------------------------------------------- lista de sesiones


class SessionList(QWidget):
    selected = Signal(object)  # SessionInfo

    def __init__(self):
        super().__init__()
        self.sessions: list[SessionInfo] = []
        self._sorted_once = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 6, 12)
        lay.addWidget(section("Sesiones"))
        self.track = QComboBox()
        self.car = QComboBox()
        self.kind = QComboBox()
        self.source = QComboBox()
        self.source.addItem("Todas", None)
        self.source.addItem("Mis sesiones", "mine")
        self.source.addItem("Importadas", "imported")
        self.only_valid = QCheckBox("Solo con vueltas válidas")
        self.only_valid.setChecked(True)
        for w in (self.track, self.car):
            w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(18)
        row = QHBoxLayout()
        row.addWidget(self.kind)
        row.addWidget(self.source)
        row.addWidget(self.only_valid)
        lay.addWidget(self.track)
        lay.addWidget(self.car)
        lay.addLayout(row)
        self.table = make_table(["Fecha", "Circuito", "Coche", "Tipo", "Válidas", "Mejor"], stretch_col=2)
        self.table.setSortingEnabled(True)
        lay.addWidget(self.table, 1)
        self.count = QLabel()
        self.count.setObjectName("subtitle")
        lay.addWidget(self.count)
        self.track.currentIndexChanged.connect(self._track_changed)
        self.car.currentIndexChanged.connect(self._fill)
        self.kind.currentIndexChanged.connect(self._fill)
        self.source.currentIndexChanged.connect(self._fill)
        self.only_valid.toggled.connect(self._fill)
        self.table.itemSelectionChanged.connect(self._on_select)

    def set_sessions(self, sessions):
        self.sessions = [s for s in sessions if not s.error]
        cur_track = self.track.currentData()
        self.track.blockSignals(True)
        self.track.clear()
        self.track.addItem("Todos los circuitos", None)
        for t in sorted({s.track for s in self.sessions}, key=short_track):
            self.track.addItem(short_track(t), t)
        i = self.track.findData(cur_track)
        self.track.setCurrentIndex(max(i, 0))
        self.track.blockSignals(False)
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItem("Todos los tipos", None)
        for k in sorted({s.session_type for s in self.sessions}):
            self.kind.addItem(SESSION_TYPES.get(k, k), k)
        self.kind.blockSignals(False)
        self._track_changed()

    def _track_changed(self):
        track = self.track.currentData()
        cur = self.car.currentData()
        self.car.blockSignals(True)
        self.car.clear()
        self.car.addItem("Todos los coches", None)
        for c in sorted({s.car for s in self.sessions if track is None or s.track == track}):
            self.car.addItem(c, c)
        i = self.car.findData(cur)
        self.car.setCurrentIndex(max(i, 0))
        self.car.blockSignals(False)
        self._fill()

    def _fill(self):
        track, car, kind = self.track.currentData(), self.car.currentData(), self.kind.currentData()
        source = self.source.currentData()
        rows = [s for s in self.sessions
                if (track is None or s.track == track) and (car is None or s.car == car)
                and (kind is None or s.session_type == kind) and (not self.only_valid.isChecked() or s.valid_laps)
                and (source is None or (source == "imported") == s.imported)]
        # tu mejor tiempo por circuito+coche (sin contar importadas), para marcar en morado la sesión récord
        records = {}
        for s in self.sessions:
            if not s.imported and s.best > 0 and s.best < records.get((s.track, s.car), 1e9):
                records[(s.track, s.car)] = s.best
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, s in enumerate(rows):
            is_record = not s.imported and s.best > 0 and records.get((s.track, s.car)) == s.best
            date = sitem(s.recorded, s.mtime, color=theme.AMBER if s.imported else None)
            date.setData(Qt.UserRole, s.path)
            t.setItem(r, 0, date)
            t.setItem(r, 1, item(short_track(s.track)))
            car = item(s.car)
            car.setToolTip(s.car)
            t.setItem(r, 2, car)
            kind_txt = SESSION_TYPES.get(s.session_type, s.session_type)
            if s.imported:
                kind_it = item(f"📥 {s.driver or 'importada'}", color=theme.AMBER)
                kind_it.setToolTip(f"Sesión importada · {kind_txt} · piloto: {s.driver or 'desconocido'}")
            else:
                kind_it = item(kind_txt, color=theme.MUTED)
            t.setItem(r, 3, kind_it)
            t.setItem(r, 4, sitem(f"{s.valid_laps}/{s.laps}", s.valid_laps, align=Qt.AlignCenter))
            t.setItem(r, 5, sitem(fmt_time(s.best), s.best or 1e9, align=Qt.AlignRight | Qt.AlignVCenter,
                                  color=theme.PURPLE if is_record else None, bold=is_record))
        t.setSortingEnabled(True)
        if not self._sorted_once:  # al principio, lo más reciente arriba; luego respeta lo que elija el usuario
            t.sortItems(0, Qt.DescendingOrder)
            self._sorted_once = True
        self.count.setText(f"{len(rows)} sesiones  ·  morado: tu récord  ·  📥 naranja: importadas")

    def select_path(self, path: str):
        """Selecciona una sesión concreta (p. ej. recién importada), quitando filtros si hace falta."""
        for attempt in range(2):
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).data(Qt.UserRole) == path:
                    self.table.selectRow(r)
                    self.table.scrollToItem(self.table.item(r, 0))
                    return
            for combo in (self.track, self.car, self.kind, self.source):
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
            self.only_valid.setChecked(False)
            self._track_changed()

    def _on_select(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        path = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        info = next((s for s in self.sessions if s.path == path), None)
        if info:
            self.selected.emit(info)


# --------------------------------------------------------------------------- vista de sesión


class SessionView(QWidget):
    status = Signal(str)
    removed = Signal(str)  # ruta de una sesión importada que se ha quitado

    def __init__(self, index_getter):
        super().__init__()
        self.index_getter = index_getter
        self.store = LapStore(LAPS_DIR)
        self.cache: OrderedDict[str, SessionData] = OrderedDict()
        self.sd: SessionData | None = None
        self.lap_num = None
        self.zone_results = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 12, 12, 12)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.export_btn = QPushButton("⬆  Exportar sesión")
        self.export_btn.setToolTip("Guarda esta sesión en un archivo .lmusession para pasársela a otro piloto")
        self.remove_btn = QPushButton("🗑  Quitar importada")
        self.remove_btn.setToolTip("Borra la copia importada de la app (no toca nada de LMU)")
        head.addWidget(self.export_btn, 0, Qt.AlignTop)
        head.addWidget(self.remove_btn, 0, Qt.AlignTop)
        lay.addLayout(head)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Comparar con:"))
        self.compare = QComboBox()
        self.compare.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        bar.addWidget(self.compare)
        bar.addStretch(1)
        self.coach_ref = QLabel()
        self.coach_ref.setObjectName("subtitle")
        bar.addWidget(self.coach_ref)
        self.pin_btn = QPushButton("📌 Usar como referencia del coach")
        self.unpin_btn = QPushButton("Quitar")
        self.unpin_btn.setToolTip("Quitar la referencia fijada (el coach volverá a usar tu mejor vuelta)")
        bar.addWidget(self.pin_btn)
        bar.addWidget(self.unpin_btn)
        lay.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        top = QSplitter(Qt.Horizontal)
        laps_box = QWidget()
        lb = QVBoxLayout(laps_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.addWidget(section("Vueltas"))
        self.laps = make_table(["Vuelta", "Tiempo", "S1", "S2", "S3", "Δ mejor", "Estado"], stretch_col=6)
        lb.addWidget(self.laps)
        top.addWidget(laps_box)
        map_box = QWidget()
        mb = QVBoxLayout(map_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.addWidget(section("Trazada  ·  verde ganas / rojo pierdes"))
        self.map = TrackMap()
        mb.addWidget(self.map)
        top.addWidget(map_box)
        top.setSizes([520, 380])
        split.addWidget(top)

        self.charts = TelemetryCharts()
        split.addWidget(self.charts)

        zones_box = QWidget()
        zb = QVBoxLayout(zones_box)
        zb.setContentsMargins(0, 0, 0, 0)
        zrow = QHBoxLayout()
        zrow.addWidget(section("Dónde pierdes tiempo  ·  frenada a frenada"))
        zrow.addStretch(1)
        self.zone_summary = QLabel()
        zrow.addWidget(self.zone_summary)
        reset = QPushButton("Ver vuelta entera")
        reset.clicked.connect(self.charts.reset_zoom)
        zrow.addWidget(reset)
        zb.addLayout(zrow)
        self.zones = make_table(["Frenada", "Tiempo", "Punto de frenada", "V. mínima (tú / ref)",
                                 "Gas a fondo", "Qué cambiar"], stretch_col=5)
        zb.addWidget(self.zones)
        split.addWidget(zones_box)
        split.setSizes([230, 470, 220])
        lay.addWidget(split, 1)

        self.laps.itemSelectionChanged.connect(self._lap_selected)
        self.compare.currentIndexChanged.connect(self._refresh_analysis)
        self.zones.itemSelectionChanged.connect(self._zone_selected)
        self.charts.cursor_moved.connect(self.map.set_cursor)
        self.pin_btn.clicked.connect(self._pin)
        self.unpin_btn.clicked.connect(self._unpin)
        self.export_btn.clicked.connect(self._export)
        self.remove_btn.clicked.connect(self._remove_imported)

    # --- carga -----------------------------------------------------------

    def _load(self, path) -> SessionData:
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        info = next((s for s in self.index_getter().sessions if s.path == path), None)
        sd = SessionData(info)
        self.cache[path] = sd
        while len(self.cache) > 6:
            self.cache.popitem(last=False)
        return sd

    def open_session(self, info: SessionInfo):
        try:
            self.sd = self._load(info.path)
        except Exception as e:
            QMessageBox.warning(self, "No se pudo abrir", f"{Path(info.path).name}\n\n{e}")
            return
        i = self.sd.info
        self.title.setText(f"{short_track(i.track)}  ·  {i.car}")
        best = f"Mejor {fmt_time(i.best)} (V{i.best_lap})" if i.best else "Sin vueltas válidas"
        who = f"📥 Importada · piloto: {i.driver or 'desconocido'}  ·  " if i.imported else ""
        self.subtitle.setText(f"{who}{SESSION_TYPES.get(i.session_type, i.session_type)}  ·  {i.recorded}  ·  "
                              f"{i.weather}  ·  {i.car_class}  ·  {best}")
        self.remove_btn.setVisible(i.imported)
        self._fill_compare()
        self._fill_laps()
        self._update_coach_ref()

    def _fill_laps(self):
        laps = self.sd.laps
        valid = [l for l in laps if l.valid]
        best = min((l.time for l in valid), default=0)
        best_s = [min((getattr(l, k) for l in valid if getattr(l, k) > 0), default=0) for k in ("s1", "s2", "s3")]
        t = self.laps
        t.blockSignals(True)
        t.setRowCount(len(laps))
        select_row = None
        for r, l in enumerate(laps):
            muted = None if l.valid else theme.MUTED
            is_best = l.valid and l.time == best
            num = item(l.num, align=Qt.AlignCenter, color=muted)
            num.setData(Qt.UserRole, l.num)
            t.setItem(r, 0, num)
            shown = l.time if l.valid else l.duration
            t.setItem(r, 1, item(fmt_time(shown), Qt.AlignRight | Qt.AlignVCenter,
                                 theme.PURPLE if is_best else muted, bold=is_best))
            for c, (k, bs) in enumerate(zip(("s1", "s2", "s3"), best_s)):
                v = getattr(l, k)
                t.setItem(r, 2 + c, item(fmt_sec(v), Qt.AlignRight | Qt.AlignVCenter,
                                         theme.PURPLE if v > 0 and v == bs else muted))
            dl = f"{l.time - best:+.3f}" if l.valid and best and not is_best else ""
            t.setItem(r, 5, item(dl, Qt.AlignRight | Qt.AlignVCenter, theme.MUTED))
            t.setItem(r, 6, item("✓ válida" if l.valid else l.note, color=theme.GREEN if l.valid else muted))
            if is_best:
                select_row = r
        t.blockSignals(False)
        if select_row is None and laps:
            # sin válidas: la vuelta completa más larga en datos
            select_row = max(range(len(laps)), key=lambda r: laps[r].duration if laps[r].note != "incompleta" else 0)
        if select_row is not None:
            t.selectRow(select_row)
        else:
            self.charts.clear_all()

    # --- análisis --------------------------------------------------------

    def _lap_selected(self):
        rows = self.laps.selectionModel().selectedRows()
        if not rows or not self.sd:
            return
        self.lap_num = self.laps.item(rows[0].row(), 0).data(Qt.UserRole)
        self._refresh_analysis()

    def _fill_compare(self):
        """Opciones de comparación: sesión, tu histórico y las mejores vueltas importadas de ese circuito."""
        i = self.sd.info
        prev = self.compare.currentData()
        self.compare.blockSignals(True)
        self.compare.clear()
        self.compare.addItem("Mejor vuelta de la sesión", "session")
        self.compare.addItem("Tu mejor vuelta histórica", "history")
        others = sorted((s for s in self.index_getter().sessions
                         if s.imported and s.best > 0 and s.track == i.track and s.path != i.path),
                        key=lambda s: (s.car != i.car, s.best))
        for s in others[:15]:
            car = "" if s.car == i.car else f"  ·  {s.car}"
            self.compare.addItem(f"📥 {s.driver or 'importada'}  ·  {fmt_time(s.best)}{car}", ("imported", s.path))
        self.compare.addItem("Nada", "none")
        idx = self.compare.findData(prev)
        self.compare.setCurrentIndex(idx if idx >= 0 else 0)
        self.compare.blockSignals(False)

    def _reference(self):
        """Devuelve (SessionData, nº de vuelta, descripción) de la vuelta con la que comparar."""
        mode = self.compare.currentData()
        if mode == "none":
            return None
        if isinstance(mode, tuple) and mode[0] == "imported":
            info = next((s for s in self.index_getter().sessions if s.path == mode[1]), None)
            if info:
                sd = self._load(info.path)
                return sd, info.best_lap, f"{info.driver or 'importada'} {fmt_time(info.best)}"
        if mode == "history":
            hit = self.index_getter().best_for(self.sd.info.track, self.sd.info.car)
            if hit:
                info, _ = hit
                sd = self._load(info.path)
                return sd, info.best_lap, f"histórica {fmt_time(info.best)} ({info.recorded})"
        i = self.sd.info
        if i.best_lap:
            return self.sd, i.best_lap, f"mejor de la sesión {fmt_time(i.best)}"
        return None

    def _refresh_analysis(self):
        if not self.sd or self.lap_num is None:
            return
        L = self.sd.track_len
        lap = analysis.by_distance(self.sd.lap_data(self.lap_num), L)
        ref_info = self._reference()
        ref = dlt = None
        zones = []
        self.zone_results = []
        if ref_info:
            ref_sd, ref_num, desc = ref_info
            same = ref_sd is self.sd and ref_num == self.lap_num
            ref = analysis.by_distance(ref_sd.lap_data(ref_num), L)
            dlt = analysis.delta(ref, lap)
            self.zone_results = analysis.compare_zones(ref, lap, dlt)
            zones = [z.zone for z in self.zone_results]
            lap_t = self.sd.lap(self.lap_num)
            shown = lap_t.time if lap_t.valid else lap_t.duration
            ref_t = ref_sd.lap(ref_num).time
            self.status.emit(f"Vuelta {self.lap_num} ({fmt_time(shown)}) contra {desc}"
                             + ("  ·  es la misma vuelta" if same else f"  ·  {shown - ref_t:+.3f} s"))
        else:
            self.status.emit(f"Vuelta {self.lap_num} sin comparación")
        self.charts.display(lap, ref, dlt, zones)
        self.map.display(lap, ref, dlt, zones)
        self._fill_zones()

    def _fill_zones(self):
        t = self.zones
        res = self.zone_results
        t.blockSignals(True)
        t.setRowCount(len(res))
        for r, z in enumerate(res):
            col = theme.RED if z.time_diff > 0.02 else theme.GREEN if z.time_diff < -0.02 else theme.MUTED
            name = item(f"F{z.zone.idx}  ·  {z.zone.start:.0f} m", color=theme.AMBER)
            name.setData(Qt.UserRole, r)
            t.setItem(r, 0, name)
            t.setItem(r, 1, item(f"{z.time_diff:+.3f} s", Qt.AlignRight | Qt.AlignVCenter, col, bold=True))
            bd = z.brake_diff
            btxt = "igual" if abs(bd) < 5 else (f"{abs(bd):.0f} m antes" if bd < 0 else f"{bd:.0f} m después")
            t.setItem(r, 2, item(btxt, color=theme.AMBER if abs(bd) > 12 else None))
            t.setItem(r, 3, item(f"{z.my_min_speed:.0f} / {z.zone.min_speed:.0f} km/h  ({z.min_speed_diff:+.0f})",
                                 color=theme.RED if z.min_speed_diff < -3 else theme.GREEN if z.min_speed_diff > 3 else None))
            td = z.throttle_diff
            ttxt = "igual" if abs(td) < 8 else (f"{abs(td):.0f} m antes" if td < 0 else f"{td:.0f} m después")
            t.setItem(r, 4, item(ttxt, color=theme.AMBER if td > 15 else None))
            t.setItem(r, 5, item(" · ".join(z.messages)))
        t.blockSignals(False)
        if res:
            worst = max(res, key=lambda z: z.time_diff)
            lost = sum(z.time_diff for z in res if z.time_diff > 0)
            self.zone_summary.setText(
                f"Peor: F{worst.zone.idx} ({worst.time_diff:+.3f} s)   ·   perdido en frenadas: {lost:.3f} s"
                if worst.time_diff > 0.02 else "Sin pérdidas apreciables en frenadas")
        else:
            self.zone_summary.setText("")

    def _zone_selected(self):
        rows = self.zones.selectionModel().selectedRows()
        if not rows:
            return
        z = self.zone_results[self.zones.item(rows[0].row(), 0).data(Qt.UserRole)].zone
        self.charts.zoom_to(z.start - 200, max(z.full_throttle, z.apex + 100) + 100)

    # --- referencia del coach -------------------------------------------

    def _update_coach_ref(self):
        i = self.sd.info
        pinned = self.store.pinned(i.track, i.car)
        if pinned:
            self.coach_ref.setText(f"Coach: referencia fijada {fmt_time(pinned.lap_time)}")
        else:
            hit = self.index_getter().best_for(i.track, i.car)
            own = self.store.best(i.track, i.car)
            cands = [t for t in ((hit[1] if hit else 0), (own.lap_time if own else 0)) if t > 0]
            self.coach_ref.setText(f"Coach: usará tu mejor vuelta {fmt_time(min(cands))}" if cands
                                   else "Coach: sin referencia todavía")
        self.unpin_btn.setEnabled(pinned is not None)

    def _pin(self):
        if not self.sd or self.lap_num is None:
            return
        lap = self.sd.lap(self.lap_num)
        if not lap.valid:
            QMessageBox.information(self, "Vuelta no válida",
                                    "Elige una vuelta válida para usarla como referencia del coach.")
            return
        self.store.pin(self.sd.to_coach_lap(self.lap_num))
        self._update_coach_ref()
        self.status.emit(f"Vuelta {lap.num} ({fmt_time(lap.time)}) fijada como referencia del coach "
                         "(se aplica al iniciar el coach)")

    def _unpin(self):
        if self.sd:
            self.store.unpin(self.sd.info.track, self.sd.info.car)
            self._update_coach_ref()

    # --- exportar / quitar importada ------------------------------------

    def _export(self):
        if not self.sd:
            return
        info = self.sd.info
        desktop = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation) or str(Path.home())
        start = str(Path(desktop) / share.suggested_name(info))
        path, _ = QFileDialog.getSaveFileName(self, "Exportar sesión", start,
                                              f"Sesión LMU Coach (*{share.EXTENSION})")
        if not path:
            return
        try:
            out = share.export_session(info, Path(path))
        except (share.ShareError, OSError) as e:
            QMessageBox.warning(self, "No se pudo exportar", str(e))
            return
        mb = out.stat().st_size / 1e6
        self.status.emit(f"Sesión exportada en {out} ({mb:.1f} MB)")
        QMessageBox.information(self, "Sesión exportada",
                                f"Guardada en:\n{out}\n\n({mb:.1f} MB) Pásale este archivo a otro piloto: "
                                "lo abre con «Importar sesión» en LMU Coach.")

    def _remove_imported(self):
        if not self.sd or not self.sd.info.imported:
            return
        info = self.sd.info
        if QMessageBox.question(self, "Quitar sesión importada",
                                f"¿Quitar la sesión de {info.driver or 'este piloto'} en {short_track(info.track)} "
                                f"({info.recorded}) de la app?") != QMessageBox.Yes:
            return
        self.cache.pop(info.path, None)
        self.sd = None
        try:
            share.remove_imported(info)
        except (share.ShareError, OSError) as e:
            QMessageBox.warning(self, "No se pudo quitar", str(e))
            return
        self.removed.emit(info.path)


# --------------------------------------------------------------------------- ventana


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LMU Coach")
        self.resize(1500, 920)
        self.index = SessionIndex(find_telemetry_dir(), INDEX_PATH, IMPORTED_DIR)
        self.coach = None
        self.worker = None
        # Archivos pasados al abrir (doble clic en un .lmusession) o soltados mientras se indexa
        self._pending_imports = [a for a in sys.argv[1:] if Path(a).suffix.lower() in IMPORTABLE and Path(a).is_file()]
        self._select_after = None
        self._diag_auto_shown = False
        self.setAcceptDrops(True)

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        self.coach_btn = QPushButton("▶  Iniciar modo coach")
        self.coach_btn.setObjectName("coach")
        self.coach_btn.clicked.connect(self._toggle_coach)
        tb.addWidget(self.coach_btn)
        self.coach_state = QLabel("El overlay se muestra encima de LMU (modo ventana sin bordes)")
        self.coach_state.setObjectName("subtitle")
        tb.addWidget(self.coach_state)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.import_btn = QPushButton("⬇  Importar sesión")
        self.import_btn.setToolTip("Abre un .lmusession que te haya pasado otro piloto (también puedes arrastrarlo aquí)")
        self.import_btn.clicked.connect(self._choose_import)
        tb.addWidget(self.import_btn)
        self.diag_btn = QPushButton("🩺  Diagnóstico")
        self.diag_btn.setToolTip("Comprueba por qué no se cargan datos de LMU y permite elegir la carpeta del juego")
        self.diag_btn.clicked.connect(lambda: self.show_diagnostics())
        tb.addWidget(self.diag_btn)
        self.refresh_btn = QPushButton("⟳  Buscar sesiones nuevas")
        self.refresh_btn.clicked.connect(self.refresh)
        tb.addWidget(self.refresh_btn)

        self.list = SessionList()
        self.view = SessionView(lambda: self.index)
        self.stack = QStackedWidget()
        self.empty = empty = QLabel("Elige una sesión de la lista")
        empty.setAlignment(Qt.AlignCenter)
        empty.setObjectName("subtitle")
        self.stack.addWidget(empty)
        self.stack.addWidget(self.view)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.list)
        split.addWidget(self.stack)
        split.setSizes([600, 900])
        self.setCentralWidget(split)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.list.selected.connect(self._open)
        self.view.status.connect(lambda s: self.statusBar().showMessage(s))
        self.view.removed.connect(self._imported_removed)

        if self.index.sessions:
            self.list.set_sessions(self.index.sessions)
        self.refresh()

    def _open(self, info):
        self.stack.setCurrentWidget(self.view)
        self.view.open_session(info)

    def refresh(self):
        if self.worker and self.worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage(f"Leyendo sesiones de {self.index.dir}…")
        self.worker = IndexWorker(self.index)
        self.worker.progress.connect(lambda i, n: (self.progress.setMaximum(n), self.progress.setValue(i)))
        self.worker.done.connect(self._indexed)
        self.worker.start()

    def _indexed(self, sessions):
        self.progress.hide()
        self.refresh_btn.setEnabled(True)
        self.list.set_sessions(sessions)
        errors = sum(1 for s in sessions if s.error)
        msg = f"{len(sessions)} sesiones"
        if errors:
            msg += f"  ·  {errors} no se pudieron leer (¿LMU las está grabando ahora?)"
        self.statusBar().showMessage(msg, 8000)
        if self._select_after:
            path, self._select_after = self._select_after, None
            self.list.select_path(path)
        if self._pending_imports:
            files, self._pending_imports = self._pending_imports, []
            QTimer.singleShot(0, lambda: self.import_files(files))
        elif not any(not s.imported and not s.error for s in sessions) and not self._diag_auto_shown:
            # Sin ninguna sesión propia: casi siempre es la carpeta o la grabación de telemetría de LMU
            self._diag_auto_shown = True
            self.empty.setText("No hay sesiones de LMU todavía.\nPulsa «🩺 Diagnóstico» para ver qué falta.")
            QTimer.singleShot(0, lambda: self.show_diagnostics("No encuentro sesiones de Le Mans Ultimate"))

    # --- diagnóstico ------------------------------------------------------

    def show_diagnostics(self, headline: str = ""):
        dlg = DiagnosticsDialog(self, headline)
        dlg.lmu_dir_changed.connect(self._lmu_dir_changed)
        dlg.exec()

    def _lmu_dir_changed(self):
        self.index.dir = find_telemetry_dir()
        self.view.cache.clear()
        self.refresh()

    # --- importar ---------------------------------------------------------

    def _choose_import(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Importar sesión", QStandardPaths.writableLocation(QStandardPaths.DownloadLocation),
            f"Sesiones (*{share.EXTENSION} *.zip *.duckdb)")
        if files:
            self.import_files(files)

    def import_files(self, files):
        if self.worker and self.worker.isRunning():
            self._pending_imports += list(files)  # se importan al terminar de indexar
            return
        ok, msgs, last = [], [], None
        for f in files:
            try:
                info = share.import_session(Path(f), IMPORTED_DIR)
                ok.append(info)
                last = info.path
            except share.AlreadyImported as e:
                msgs.append(f"{Path(f).name}: ya estaba importada.")
                last = str(e.path)
            except (share.ShareError, OSError) as e:
                msgs.append(f"{Path(f).name}: {e}")
        if ok:
            names = ", ".join(f"{i.driver or 'piloto'} en {short_track(i.track)} ({fmt_time(i.best)})" for i in ok)
            self.statusBar().showMessage(f"Importada: {names}", 10000)
        if msgs:
            QMessageBox.warning(self, "Importar sesión", "\n\n".join(msgs))
        if last:
            self._select_after = last
            self.refresh()

    def _imported_removed(self, path):
        self.stack.setCurrentIndex(0)
        self.statusBar().showMessage("Sesión importada quitada", 6000)
        self.refresh()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in IMPORTABLE
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if Path(u.toLocalFile()).suffix.lower() in IMPORTABLE]
        if files:
            self.import_files(files)

    # --- modo coach ------------------------------------------------------

    def _toggle_coach(self):
        if self.coach and self.coach.state() != QProcess.NotRunning:
            self.coach.terminate()
            if not self.coach.waitForFinished(1500):
                self.coach.kill()
            return
        program, args = coach_command()
        self.coach = QProcess(self)
        self.coach.setWorkingDirectory(str(PROJECT_ROOT))
        self.coach.finished.connect(self._coach_stopped)
        self.coach.errorOccurred.connect(lambda e: self._coach_stopped())
        self.coach.start(program, args)
        if self.coach.waitForStarted(3000):
            self._set_coach_ui(True)

    def _coach_stopped(self, *args):
        self._set_coach_ui(False)

    def _set_coach_ui(self, running):
        self.coach_btn.setText("■  Detener modo coach" if running else "▶  Iniciar modo coach")
        self.coach_btn.setProperty("running", "true" if running else "false")
        self.coach_btn.style().unpolish(self.coach_btn)
        self.coach_btn.style().polish(self.coach_btn)
        self.coach_state.setText("Coach activo: entra en pista y tendrás delta y avisos de frenada" if running
                                 else "El overlay se muestra encima de LMU (modo ventana sin bordes)")

    def closeEvent(self, e):
        if self.coach and self.coach.state() != QProcess.NotRunning:
            self.coach.kill()
            self.coach.waitForFinished(1000)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LMU Coach")
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "icon.png")))
    theme.apply(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
