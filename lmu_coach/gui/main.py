"""Ventana principal: sesiones de LMU, análisis de vueltas y lanzador del modo coach."""
import sys
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import analysis, corners, lapstats, share
from ..laps import LapStore, fmt_time
from ..paths import ASSETS_DIR, IMPORTED_DIR, INDEX_PATH, LAPS_DIR, PROJECT_ROOT, coach_command
from ..sessions import SessionData, SessionIndex, SessionInfo, find_telemetry_dir
from . import car_pix, theme
from .charts import TelemetryCharts, TrackMap
from .diagnostics_dialog import DiagnosticsDialog
from .insights import (AssistantTab, ConsistencyTab, FuelTab, PaceTab, ProgressDialog, SetupTab, TrainingDialog,
                       TyresTab, RankingDialog)
from .lap_picker import LapPicker
from .replay import ReplayView
from .update_dialog import CheckWorker, UpdateDialog

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


def car_label(car: str, car_class: str | None = None) -> str:
    """'Vista AF Corse 2026 #21:WEC' + GT3 -> 'Vista AF Corse 2026 #21 (WEC) · GT3'"""
    name, _, series = car.partition(":")
    label = f"{name} ({series})" if series else name
    return f"{label}  ·  {car_class}" if car_class else label


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
    stage = Signal(str)
    done = Signal(list)

    def __init__(self, index: SessionIndex):
        super().__init__()
        self.index = index

    def run(self):
        self.done.emit(self.index.refresh(lambda i, n: self.progress.emit(i, n), lambda s: self.stage.emit(s)))


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
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Buscar circuito, coche o piloto…")
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        self.track = QComboBox()
        self.car = QComboBox()
        self.kind = QComboBox()
        self.source = QComboBox()
        self.source.addItem("Todas", None)
        self.source.addItem("Mis sesiones", "mine")
        self.source.addItem("Importadas", "imported")
        self.only_valid = QCheckBox("Solo con vueltas válidas")
        self.only_valid.setChecked(True)
        for w in (self.track, self.car, self.kind, self.source):
            w.setMaxVisibleItems(30)  # que se vean todos sin tener que descubrir el scroll
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
        self.table.setIconSize(QSize(72, 26))
        self.table.verticalHeader().setDefaultSectionSize(30)
        lay.addWidget(self.table, 1)
        self.count = QLabel()
        self.count.setObjectName("subtitle")
        lay.addWidget(self.count)
        for combo in (self.track, self.car, self.kind, self.source):
            combo.currentIndexChanged.connect(self._fill)
        self.only_valid.toggled.connect(self._fill)
        self.search.textChanged.connect(self._fill)
        self.table.itemSelectionChanged.connect(self._on_select)

    def set_sessions(self, sessions):
        self.sessions = [s for s in sessions if not s.error]
        classes = {}
        for s in self.sessions:
            classes.setdefault(s.car, s.car_class)
        # Los desplegables muestran SIEMPRE todos los circuitos y coches; los filtros solo cambian los contadores
        self._reset_combo(self.track, "Todos los circuitos",
                          [(short_track(t), t) for t in sorted({s.track for s in self.sessions}, key=short_track)])
        self._reset_combo(self.car, "Todos los coches",
                          [(car_label(c, classes.get(c)), c)
                           for c in sorted({s.car for s in self.sessions}, key=lambda c: (classes.get(c) or "", c))])
        self._reset_combo(self.kind, "Todos los tipos",
                          [(SESSION_TYPES.get(k, k), k) for k in sorted({s.session_type for s in self.sessions})])
        self._fill()

    @staticmethod
    def _reset_combo(combo, all_label, entries):
        cur = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_label, None)
        for label, value in entries:
            combo.addItem(label, value)
            combo.setItemData(combo.count() - 1, label, Qt.UserRole + 1)  # etiqueta sin contador
        i = combo.findData(cur)
        combo.setCurrentIndex(max(i, 0))
        combo.blockSignals(False)

    def _matches(self, s, skip=None):
        """¿Pasa la sesión los filtros? `skip` ignora uno (para los contadores de ese desplegable)."""
        track, car = self.track.currentData(), self.car.currentData()
        kind, source = self.kind.currentData(), self.source.currentData()
        text = self.search.text().strip().casefold()
        if skip != "track" and track is not None and s.track != track:
            return False
        if skip != "car" and car is not None and s.car != car:
            return False
        if kind is not None and s.session_type != kind:
            return False
        if source is not None and (source == "imported") != s.imported:
            return False
        if self.only_valid.isChecked() and not s.valid_laps:
            return False
        if text:
            hay = " ".join((s.track, short_track(s.track), s.car, s.car_class, s.driver,
                            SESSION_TYPES.get(s.session_type, s.session_type))).casefold()
            if not all(word in hay for word in text.split()):
                return False
        return True

    def _update_counts(self):
        for combo, dim, attr in ((self.track, "track", "track"), (self.car, "car", "car")):
            counts = {}
            for s in self.sessions:
                if self._matches(s, skip=dim):
                    counts[getattr(s, attr)] = counts.get(getattr(s, attr), 0) + 1
            for i in range(1, combo.count()):
                n = counts.get(combo.itemData(i), 0)
                combo.setItemText(i, f"{combo.itemData(i, Qt.UserRole + 1)}   ({n})")

    def _fill(self):
        self._update_counts()
        rows = [s for s in self.sessions if self._matches(s)]
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
            pix = car_pix.pixmap(s.car, "thumb", 26)
            # con imagen no cabe también el nombre: va en el aviso al pasar el ratón y en la cabecera de la sesión
            car = sitem("" if pix else s.car, s.car.casefold())
            car.setData(Qt.UserRole, s.car)
            car.setToolTip(f"{s.car} · {s.car_class}")
            if pix:
                car.setIcon(QIcon(pix))
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
        hidden = len(self.sessions) - len(rows)
        extra = f"  ·  {hidden} ocultas por los filtros" if hidden else ""
        self.count.setText(f"{len(rows)} sesiones{extra}  ·  morado: tu récord  ·  📥 naranja: importadas")

    def select_path(self, path: str):
        """Selecciona una sesión concreta (p. ej. recién importada), quitando filtros si hace falta."""
        for attempt in range(2):
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).data(Qt.UserRole) == path:
                    self.table.selectRow(r)
                    self.table.scrollToItem(self.table.item(r, 0))
                    return
            for w in (self.track, self.car, self.kind, self.source, self.search, self.only_valid):
                w.blockSignals(True)
            for combo in (self.track, self.car, self.kind, self.source):
                combo.setCurrentIndex(0)
            self.search.clear()
            self.only_valid.setChecked(False)
            for w in (self.track, self.car, self.kind, self.source, self.search, self.only_valid):
                w.blockSignals(False)
            self._fill()

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
        self.custom_lap = None      # (ruta, nº) elegida con «Elegir cualquier vuelta…»
        self._compare_prev = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 12, 12, 12)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        head = QHBoxLayout()
        self.car_img = QLabel()
        self.car_img.setFixedHeight(84)
        self.car_img.hide()
        head.addWidget(self.car_img, 0, Qt.AlignVCenter)
        titles = QVBoxLayout()
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.export_btn = QPushButton("⬆  Exportar sesión")
        self.export_btn.setToolTip("Guarda esta sesión en un archivo .lmusession para pasársela a otro piloto")
        self.remove_btn = QPushButton("🗑  Quitar importada")
        self.remove_btn.setToolTip("Borra la copia importada de la app (no toca nada de LMU)")
        self.progress_btn = QPushButton("📈  Progreso")
        self.progress_btn.setToolTip("Tu evolución con este coche y circuito, y tu vuelta ideal")
        self.progress_btn.clicked.connect(self._show_progress)
        self.plan_btn = QPushButton("🎯  Plan")
        self.plan_btn.setToolTip("Las curvas donde más pierdes frente a tu mejor vuelta y qué cambiar")
        self.plan_btn.clicked.connect(self._show_plan)
        head.addWidget(self.plan_btn, 0, Qt.AlignTop)
        head.addWidget(self.progress_btn, 0, Qt.AlignTop)
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
        self.replay = ReplayView()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.charts, "📈  Gráficas")
        self.tabs.addTab(self.replay, "▶  Repetición")
        self.fuel_tab = FuelTab()
        self.setup_tab = SetupTab()
        self.cons_tab = ConsistencyTab()
        self.tyres_tab = TyresTab()
        self.tabs.addTab(self.fuel_tab, "⛽  Combustible y estrategia")
        self.tabs.addTab(self.setup_tab, "🔧  Reglaje")
        self.tabs.addTab(self.cons_tab, "🎯  Consistencia")
        self.tabs.addTab(self.tyres_tab, "🛞  Neumáticos y frenos")
        self.pace_tab = PaceTab()
        self.tabs.addTab(self.pace_tab, "📉  Ritmo y relevos")
        self.assistant_tab = AssistantTab()
        self.tabs.addTab(self.assistant_tab, "🧠  Asistente de reglaje")
        self._loaded_tabs = set()
        self._stats_cache = {}
        split.addWidget(self.tabs)

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
        self.compare.currentIndexChanged.connect(self._compare_changed)
        self.laps.setContextMenuPolicy(Qt.CustomContextMenu)
        self.laps.customContextMenuRequested.connect(self._laps_menu)
        self.zones.itemSelectionChanged.connect(self._zone_selected)
        self.zones.cellDoubleClicked.connect(self._rename_zone)
        self.charts.cursor_moved.connect(self.map.set_cursor)
        self.replay.position_changed.connect(self._replay_moved)
        self.tabs.currentChanged.connect(self._tab_changed)
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
        pix = car_pix.pixmap(i.car, "large", 84)
        self.car_img.setVisible(pix is not None)
        if pix:
            self.car_img.setPixmap(pix)
        best = f"Mejor {fmt_time(i.best)} (V{i.best_lap})" if i.best else "Sin vueltas válidas"
        who = f"📥 Importada · piloto: {i.driver or 'desconocido'}  ·  " if i.imported else ""
        self.subtitle.setText(f"{who}{SESSION_TYPES.get(i.session_type, i.session_type)}  ·  {i.recorded}  ·  "
                              f"{i.weather}  ·  {i.car_class}  ·  {best}")
        self.remove_btn.setVisible(i.imported)
        self._loaded_tabs = set()
        self._fill_compare()
        self._fill_laps()
        self._update_coach_ref()
        self._tab_changed(self.tabs.currentIndex())  # si hay abierta una pestaña de análisis, recalcularla

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
        if self.tyres_tab in self._loaded_tabs:
            self.tyres_tab.set_lap(self.lap_num)
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
            self.compare.addItem(f"📥 {s.driver or 'importada'}  ·  {fmt_time(s.best)}{car}", f"imported::{s.path}")
        custom = self._custom_label()
        if custom:
            self.compare.insertItem(0, custom, self._lap_key(*self.custom_lap))
        self.compare.addItem("🔎  Elegir cualquier vuelta…", "pick")
        self.compare.addItem("Nada", "none")
        idx = self.compare.findData(prev)
        self.compare.setCurrentIndex(idx if idx >= 0 else 0)
        self._compare_prev = self.compare.currentIndex()
        self.compare.blockSignals(False)

    @staticmethod
    def _lap_key(path, num) -> str:
        # Qt convierte las tuplas en listas al guardarlas en el combo: usamos texto para poder buscarlas
        return f"lap::{num}::{path}"

    def _custom_label(self) -> str | None:
        """Texto para la vuelta elegida a mano (si es del mismo circuito que la sesión abierta)."""
        if not self.custom_lap:
            return None
        path, num = self.custom_lap
        info = next((s for s in self.index_getter().sessions if s.path == path), None)
        if not info or info.track != self.sd.info.track:
            self.custom_lap = None
            return None
        lap = next((l for l in info.lap_list if l[0] == num), None)
        t = fmt_time(lap[1]) if lap else "?"
        who = f"📥 {info.driver}" if info.imported else info.recorded
        same = "esta sesión" if path == self.sd.info.path else who
        return f"V{num}  ·  {t}  ·  {same}"

    def _compare_changed(self, index):
        if self.compare.itemData(index) == "pick":
            self._pick_lap()
            return
        self._compare_prev = index
        self._refresh_analysis()

    def _pick_lap(self):
        i = self.sd.info
        dlg = LapPicker(self, self.index_getter().sessions, i.track, i.car,
                        exclude=(i.path, self.lap_num), short_track=short_track)
        if dlg.exec() and dlg.choice:
            self.set_custom_lap(*dlg.choice)
        else:  # cancelado: volver a la opción anterior
            self.compare.blockSignals(True)
            self.compare.setCurrentIndex(self._compare_prev)
            self.compare.blockSignals(False)

    def set_custom_lap(self, path, num):
        self.custom_lap = (path, num)
        self._fill_compare()
        self.compare.blockSignals(True)
        self.compare.setCurrentIndex(self.compare.findData(self._lap_key(path, num)))
        self._compare_prev = self.compare.currentIndex()
        self.compare.blockSignals(False)
        self._refresh_analysis()

    def _laps_menu(self, pos):
        row = self.laps.rowAt(pos.y())
        if row < 0 or not self.sd:
            return
        num = self.laps.item(row, 0).data(Qt.UserRole)
        menu = QMenu(self)
        if num != self.lap_num:
            menu.addAction(f"Comparar la vuelta seleccionada con la V{num}",
                           lambda: self.set_custom_lap(self.sd.info.path, num))
        menu.addAction("Comparar con cualquier vuelta del circuito…", self._pick_lap)
        menu.exec(self.laps.viewport().mapToGlobal(pos))

    def _reference(self):
        """Devuelve (SessionData, nº de vuelta, descripción) de la vuelta con la que comparar."""
        mode = self.compare.currentData()
        if mode == "none":
            return None
        if isinstance(mode, str) and mode.startswith("lap::"):
            _, num, path = mode.split("::", 2)
            num = int(num)
            info = next((s for s in self.index_getter().sessions if s.path == path), None)
            if info:
                sd = self._load(path)
                lap = sd.lap(num)
                who = f"{info.driver} " if info.imported else ""
                t = lap.time if lap and lap.valid else (lap.duration if lap else 0)
                return sd, num, f"{who}V{num} {fmt_time(t)} ({info.recorded})"
        if isinstance(mode, str) and mode.startswith("imported::"):
            path = mode.split("::", 1)[1]
            info = next((s for s in self.index_getter().sessions if s.path == path), None)
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
        lap_raw = self.sd.lap_data(self.lap_num)
        lap = analysis.by_distance(lap_raw, L)
        ref_info = self._reference()
        ref = dlt = ref_raw = None
        zones = []
        self.zone_results = []
        if ref_info:
            ref_sd, ref_num, desc = ref_info
            same = ref_sd is self.sd and ref_num == self.lap_num
            ref_raw = ref_sd.lap_data(ref_num)
            ref = analysis.by_distance(ref_raw, L)
            dlt = analysis.delta(ref, lap)
            self.zone_results = analysis.compare_zones(ref, lap, dlt)
            zones = [z.zone for z in self.zone_results]
            lap_t = self.sd.lap(self.lap_num)
            shown = lap_t.time if lap_t.valid else lap_t.duration
            ref_lap = ref_sd.lap(ref_num)
            ref_t = ref_lap.time if ref_lap.valid else ref_lap.duration
            self.status.emit(f"Vuelta {self.lap_num} ({fmt_time(shown)}) contra {desc}"
                             + ("  ·  es la misma vuelta" if same else f"  ·  {shown - ref_t:+.3f} s"))
        else:
            self.status.emit(f"Vuelta {self.lap_num} sin comparación")
        self.charts.display(lap, ref, dlt, zones)
        self.map.display(lap, ref, dlt, zones)
        self.replay.load(lap_raw, ref_raw, ref, zones)
        self._fill_zones()

    def _replay_moved(self, d):
        """La repetición mueve el cursor de las gráficas y el punto del mapa pequeño."""
        self.charts.set_cursor(d)
        self.map.set_cursor(d)

    def _rename_zone(self, row, col):
        if col != 0 or not self.sd:
            return
        from PySide6.QtWidgets import QInputDialog
        z = self.zone_results[self.zones.item(row, 0).data(Qt.UserRole)].zone
        i = self.sd.info
        cur = corners.name_for(i.track, i.layout, z.apex) or ""
        default = corners.default_name(i.track, i.layout, z.apex)
        hint = f" (de serie: {default})" if default else ""
        text, ok = QInputDialog.getText(self, "Nombre de la curva",
                                        f"F{z.idx}, vértice a {z.apex:.0f} m{hint}.\n"
                                        "Déjalo vacío para volver al nombre de serie.", text=cur)
        if not ok:
            return
        if text.strip():
            corners.set_name(i.track, i.layout, z.apex, text)
        else:
            corners.reset_name(i.track, i.layout, z.apex)
        self._fill_zones()

    def _fill_zones(self):
        t = self.zones
        res = self.zone_results
        t.blockSignals(True)
        t.setRowCount(len(res))
        for r, z in enumerate(res):
            col = theme.RED if z.time_diff > 0.02 else theme.GREEN if z.time_diff < -0.02 else theme.MUTED
            i = self.sd.info
            name = item(corners.label(z.zone, i.track, i.layout), color=theme.AMBER)
            name.setToolTip(f"Frena a {z.zone.start:.0f} m · doble clic para ponerle nombre")
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


    # --- pestañas de análisis (se calculan al abrirlas) --------------------

    def _own_infos(self):
        i = self.sd.info
        return lapstats.own_sessions(self.index_getter().sessions, i.track, i.car)

    def _lap_stats(self):
        key = self.sd.info.path
        if key not in self._stats_cache:
            self._stats_cache[key] = lapstats.lap_stats(self.sd)
        return self._stats_cache[key]

    def _tab_changed(self, i):
        w = self.tabs.widget(i)
        if w is self.replay:
            self.replay.setFocus()
        if not self.sd or w in self._loaded_tabs:
            return
        if w in (self.fuel_tab, self.setup_tab, self.cons_tab, self.tyres_tab, self.assistant_tab, self.pace_tab):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                if w is self.fuel_tab:
                    self.fuel_tab.set_data(self._lap_stats(), self._own_infos())
                elif w is self.setup_tab:
                    self.setup_tab.set_data(self.sd, self._own_infos())
                elif w is self.cons_tab:
                    self.cons_tab.set_data(self.sd)
                elif w is self.assistant_tab:
                    self.assistant_tab.set_data(self.sd, self._own_infos())
                elif w is self.pace_tab:
                    self.pace_tab.set_data(self._lap_stats())
                elif w is self.tyres_tab:
                    self.tyres_tab.set_data(self._lap_stats())
                    if self.lap_num is not None:
                        self.tyres_tab.set_lap(self.lap_num)
                self._loaded_tabs.add(w)
            finally:
                QApplication.restoreOverrideCursor()

    def _show_plan(self):
        if not self.sd:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            dlg = TrainingDialog(self, self.sd)
        finally:
            QApplication.restoreOverrideCursor()
        dlg.exec()

    def _show_progress(self):
        if not self.sd:
            return
        i = self.sd.info
        ProgressDialog(self, f"{short_track(i.track)} · {i.car}", self._own_infos()).exec()


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
        self.rank_btn = QPushButton("🏆  Ranking")
        self.rank_btn.setToolTip("Tus tiempos frente a los de las sesiones importadas de otros pilotos")
        self.rank_btn.clicked.connect(lambda: RankingDialog(self, self.index.sessions, short_track).exec())
        tb.addWidget(self.rank_btn)
        self.import_btn = QPushButton("⬇  Importar sesión")
        self.import_btn.setToolTip("Abre un .lmusession que te haya pasado otro piloto (también puedes arrastrarlo aquí)")
        self.import_btn.clicked.connect(self._choose_import)
        tb.addWidget(self.import_btn)
        self.backup_btn = QPushButton("💾  Copia")
        self.backup_btn.setToolTip("Copia propia de tus sesiones (no se pierden aunque LMU las borre)")
        self.backup_btn.clicked.connect(self._show_backup)
        tb.addWidget(self.backup_btn)
        self.diag_btn = QPushButton("🩺  Diagnóstico")
        self.diag_btn.setToolTip("Comprueba por qué no se cargan datos de LMU y permite elegir la carpeta del juego")
        self.diag_btn.clicked.connect(lambda: self.show_diagnostics())
        tb.addWidget(self.diag_btn)
        self.update_btn = QPushButton()
        self.update_btn.setObjectName("coach")
        self.update_btn.clicked.connect(self._show_update)
        self.update_action = tb.addWidget(self.update_btn)
        self.update_action.setVisible(False)  # solo aparece si hay versión nueva
        self._release = None
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
        # Buscar actualizaciones en segundo plano, cuando la ventana ya está a la vista
        self.update_worker = CheckWorker()
        self.update_worker.found.connect(self._update_found)
        QTimer.singleShot(3000, self.update_worker.start)

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
        self.worker.stage.connect(lambda s: self.statusBar().showMessage(f"{s}…"))
        self.worker.done.connect(self._indexed)
        self.worker.start()
        # con LMU abierto, aprender su lista completa de decoraciones para poner la imagen de cada coche
        if not (getattr(self, "car_worker", None) and self.car_worker.isRunning()):
            self.car_worker = car_pix.GameListWorker()
            self.car_worker.learned.connect(self._cars_learned)
            self.car_worker.start()

    def _cars_learned(self):
        """Poner las imágenes que faltaban sin rehacer la lista (se conserva la selección)."""
        car_pix.forget_missing()
        t = self.list.table
        for r in range(t.rowCount()):
            it = t.item(r, 2)
            if it is not None and it.icon().isNull():
                pix = car_pix.pixmap(it.data(Qt.UserRole), "thumb", 26)
                if pix:
                    it.setIcon(QIcon(pix))
                    it.setText("")
        info = getattr(self.view, "sd", None)
        if info is not None and self.view.car_img.isHidden():
            pix = car_pix.pixmap(info.info.car, "large", 84)
            if pix:
                self.view.car_img.setPixmap(pix)
                self.view.car_img.show()

    def _indexed(self, sessions):
        self.progress.hide()
        self.refresh_btn.setEnabled(True)
        self.list.set_sessions(sessions)
        errors = sum(1 for s in sessions if s.error)
        msg = f"{len(sessions)} sesiones"
        ls = self.index.last_sync
        if ls and ls.get("copied"):
            msg += f"  ·  {ls['copied']} copiadas a tu carpeta"
        if ls and ls.get("error"):
            msg += f"  ·  ⚠ copia: {ls['error']}"

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

    # --- actualizaciones -------------------------------------------------

    def _update_found(self, rel):
        self._release = rel
        self.update_btn.setText(f"⬆  Actualizar a {rel.version}")
        self.update_action.setVisible(True)
        self.statusBar().showMessage(f"Hay una versión nueva de LMU Coach: {rel.version}", 15000)

    def _show_update(self):
        if self._release:
            UpdateDialog(self, self._release).exec()

    # --- diagnóstico ------------------------------------------------------

    def _show_backup(self):
        from .backup_dialog import BackupDialog
        dlg = BackupDialog(self, self.index.last_sync)
        dlg.archive_changed.connect(self._archive_changed)
        dlg.exec()

    def _archive_changed(self):
        from .. import archive
        self.index.archive_dir = archive.archive_dir()
        self.refresh()

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
