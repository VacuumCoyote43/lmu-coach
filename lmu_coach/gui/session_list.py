"""Lista de sesiones con filtros (circuito, coche, tipo, importadas)."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from . import car_pix, theme
from .common import SESSION_TYPES, car_label, item, make_table, section, short_track, sitem
from ..laps import fmt_time
from ..sessions import SessionInfo


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
