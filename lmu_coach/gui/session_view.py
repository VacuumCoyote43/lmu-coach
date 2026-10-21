"""Vista de una sesión: vueltas, comparación, gráficas, trazada y pestañas de análisis."""
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

from . import car_pix, theme
from .charts import TelemetryCharts, TrackMap
from .common import SESSION_TYPES, fmt_sec, item, make_table, section, short_track
from .insights import (
    AssistantTab, ConsistencyTab, FuelTab, PaceTab, SetupTab, TrainingDialog, TyresTab,
)
from .lap_picker import LapPicker
from .race_tab import RaceSummaryTab
from .replay import ReplayView
from .. import analysis, corners, lapstats, share
from ..laps import LapStore, fmt_time
from ..log import log
from ..paths import LAPS_DIR
from ..sessions import SessionData, SessionInfo


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
        self.image_btn = QPushButton("📷  Imagen")
        self.image_btn.setToolTip("Guarda una imagen de lo que ves (y la copia al portapapeles) para compartirla")
        self.image_btn.clicked.connect(self._save_image)
        head.addWidget(self.image_btn, 0, Qt.AlignTop)
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
        self.fuel_tab = FuelTab()
        self.setup_tab = SetupTab()
        self.cons_tab = ConsistencyTab()
        self.tyres_tab = TyresTab()
        self.pace_tab = PaceTab()
        self.assistant_tab = AssistantTab()
        self.race_tab = RaceSummaryTab()
        # tres grupos (la vuelta, la carrera y el coche), cada uno con sus pestañas
        self.tabs = QTabWidget()
        self.groups = []
        for title, pages in (
                ("🏁  Vuelta", [(self.charts, "📈  Gráficas"), (self.replay, "▶  Repetición"),
                               (self.cons_tab, "🎯  Consistencia")]),
                ("📊  Carrera", [(self.race_tab, "🏁  Resumen de carrera"), (self.pace_tab, "📉  Ritmo y relevos"),
                                (self.fuel_tab, "⛽  Combustible y estrategia")]),
                ("🔧  Coche", [(self.tyres_tab, "🛞  Neumáticos y frenos"), (self.setup_tab, "🔧  Reglaje"),
                              (self.assistant_tab, "🧠  Asistente de reglaje")])):
            inner = QTabWidget()
            inner.setDocumentMode(True)
            for w, label in pages:
                inner.addTab(w, label)
            inner.currentChanged.connect(lambda _i: self._page_changed())
            self.tabs.addTab(inner, title)
            self.groups.append(inner)
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
        self.zones.setContextMenuPolicy(Qt.CustomContextMenu)
        self.zones.customContextMenuRequested.connect(self._zones_menu)
        self.charts.cursor_moved.connect(self.map.set_cursor)
        self.replay.position_changed.connect(self._replay_moved)
        self.tabs.currentChanged.connect(lambda _i: self._page_changed())
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
            log.error("No se pudo abrir la sesión %s", info.path, exc_info=True)
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
        self._page_changed()  # si hay abierta una pestaña de análisis, recalcularla

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

    def _zones_menu(self, pos):
        """Clic derecho en una frenada: practicarla en el coach (solo se habla de esa curva)."""
        it = self.zones.itemAt(pos)
        if it is None or not self.sd:
            return
        from .. import config as C
        r = self.zones.item(it.row(), 0).data(Qt.UserRole)
        z = self.zone_results[r].zone
        i = self.sd.info
        cfg = C.load_config()
        cur = cfg.get("practice_corner")
        m = QMenu(self)
        practice = m.addAction(f"🎯  Practicar {corners.label(z, i.track, i.layout, with_num=False)} en el coach")
        practice.setToolTip("En pista, el coach solo te habla de esta curva: cada pasada, lo que ganas o pierdes y por qué")
        stop = m.addAction("Quitar el modo práctica") if cur else None
        rename = m.addAction("✏  Ponerle nombre…")
        chosen = m.exec(self.zones.viewport().mapToGlobal(pos))
        if chosen is practice:
            cfg["practice_corner"] = {"track": i.track, "car": i.car, "apex": round(z.apex, 1),
                                      "name": corners.label(z, i.track, i.layout, with_num=False)}
            C.save_config(cfg)
            self.status.emit(f"Modo práctica: {cfg['practice_corner']['name']}. El coach solo hablará de esa curva "
                             "(quítalo con clic derecho o en ⚙ Ajustes › Coach)")
        elif stop is not None and chosen is stop:
            cfg["practice_corner"] = None
            C.save_config(cfg)
            self.status.emit("Modo práctica quitado")
        elif chosen is rename:
            self._rename_zone(it.row(), 0)

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

    def _save_image(self):
        """Imagen de la vista tal como está (vuelta, comparación y pestaña abiertas); también al portapapeles."""
        if not self.sd:
            return
        i = self.sd.info
        pix = self.grab()
        QApplication.clipboard().setPixmap(pix)
        pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
        name = f"{short_track(i.track)} {i.recorded[:16].replace(':', '.')} {i.car.split(':')[0]}.png"
        name = "".join(c for c in name if c not in r'\/*?"<>|')
        path, _ = QFileDialog.getSaveFileName(self, "Guardar imagen", str(Path(pics) / name), "Imagen PNG (*.png)")
        if path:
            pix.save(path, "PNG")
            self.status.emit(f"Imagen guardada en {path} (también está en el portapapeles)")
        else:
            self.status.emit("Imagen copiada al portapapeles: pégala en Discord o WhatsApp")

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

    def all_pages(self):
        """[(grupo, pestaña)] de todas las pestañas de análisis (para recorrerlas)."""
        return [(g, i) for g in range(self.tabs.count()) for i in range(self.groups[g].count())]

    def show_page(self, group: int, index: int):
        self.tabs.setCurrentIndex(group)
        self.groups[group].setCurrentIndex(index)

    def _page_changed(self):
        g = self.tabs.currentIndex()
        if not 0 <= g < len(self.groups):      # aún montando las pestañas
            return
        w = self.groups[g].currentWidget()
        if w is self.replay:
            self.replay.setFocus()
        if not self.sd or w in self._loaded_tabs:
            return
        if w in (self.fuel_tab, self.setup_tab, self.cons_tab, self.tyres_tab, self.assistant_tab, self.pace_tab,
                 self.race_tab):
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
                elif w is self.race_tab:
                    self.race_tab.set_session(self.sd.info)
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
        from .progress import MyProgressDialog
        i = self.sd.info
        MyProgressDialog(self, self.index_getter().sessions, (i.track, i.car, i.layout or i.track)).exec()
