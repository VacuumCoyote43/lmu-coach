"""Elegir cualquier vuelta de cualquier sesión del mismo circuito para comparar."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..laps import fmt_time
from ..sessions import SessionInfo
from . import theme

SESSION_TYPES = {"Practice": "Libres", "Qualify": "Clasificación", "Race": "Carrera", "Warmup": "Warm-up"}


class _SortItem(QTableWidgetItem):
    def __lt__(self, other):
        a, b = self.data(Qt.UserRole + 1), other.data(Qt.UserRole + 1)
        if a is not None and b is not None:
            return a < b
        return super().__lt__(other)


def _item(text, key=None, color=None, align=Qt.AlignLeft | Qt.AlignVCenter, bold=False):
    it = _SortItem(str(text))
    it.setTextAlignment(align)
    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    if key is not None:
        it.setData(Qt.UserRole + 1, key)
    if color:
        it.setForeground(QColor(color))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    return it


class LapPicker(QDialog):
    """Devuelve (ruta de la sesión, nº de vuelta) en self.choice al aceptar."""

    COLS = ["Tiempo", "S1", "S2", "S3", "Coche", "Piloto", "Fecha", "Sesión", "Vuelta"]

    def __init__(self, parent, sessions: list[SessionInfo], track: str, car: str, exclude=None, short_track=str):
        super().__init__(parent)
        self.setWindowTitle(f"Elegir vuelta para comparar · {short_track(track)}")
        self.resize(1050, 640)
        self.choice = None
        self.car = car
        self.exclude = exclude  # (ruta, nº) de la vuelta que estás analizando
        self.sessions = [s for s in sessions if s.track == track and not s.error]

        lay = QVBoxLayout(self)
        title = QLabel(f"Todas las vueltas en {short_track(track)}")
        title.setObjectName("title")
        lay.addWidget(title)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Buscar coche, piloto o fecha…")
        self.search.setClearButtonEnabled(True)
        self.same_car = QCheckBox("Solo mi coche")
        self.same_car.setChecked(False)
        self.same_car.setToolTip(car)
        self.include_invalid = QCheckBox("Incluir vueltas no válidas")
        self.source = QComboBox()
        self.source.addItem("Mías e importadas", None)
        self.source.addItem("Solo mías", "mine")
        self.source.addItem("Solo importadas", "imported")
        filters.addWidget(self.search, 1)
        filters.addWidget(self.source)
        filters.addWidget(self.same_car)
        filters.addWidget(self.include_invalid)
        lay.addLayout(filters)

        t = self.table = QTableWidget(0, len(self.COLS))
        t.setHorizontalHeaderLabels(self.COLS)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        t.verticalHeader().setDefaultSectionSize(26)
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        t.setSortingEnabled(True)
        lay.addWidget(t, 1)

        bottom = QHBoxLayout()
        self.info = QLabel()
        self.info.setObjectName("subtitle")
        bottom.addWidget(self.info, 1)
        cancel = QPushButton("Cancelar")
        self.ok = QPushButton("Comparar con esta vuelta")
        self.ok.setObjectName("coach")
        self.ok.setEnabled(False)
        bottom.addWidget(cancel)
        bottom.addWidget(self.ok)
        lay.addLayout(bottom)

        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self._accept)
        t.itemDoubleClicked.connect(lambda *_: self._accept())
        t.itemSelectionChanged.connect(lambda: self.ok.setEnabled(bool(t.selectionModel().selectedRows())))
        for w in (self.same_car, self.include_invalid):
            w.toggled.connect(self._fill)
        self.source.currentIndexChanged.connect(self._fill)
        self.search.textChanged.connect(self._fill)
        self._fill()
        t.sortItems(0, Qt.AscendingOrder)

    def _rows(self):
        text = self.search.text().strip().casefold()
        src = self.source.currentData()
        for s in self.sessions:
            if self.same_car.isChecked() and s.car != self.car:
                continue
            if src is not None and (src == "imported") != s.imported:
                continue
            hay = f"{s.car} {s.car_class} {s.driver} {s.recorded} {SESSION_TYPES.get(s.session_type, s.session_type)}".casefold()
            if text and not all(w in hay for w in text.split()):
                continue
            for num, t, valid, s1, s2, s3, note in s.lap_list:
                if not valid and not self.include_invalid.isChecked():
                    continue
                if self.exclude == (s.path, num):
                    continue
                yield s, num, t, valid, s1, s2, s3, note

    def _fill(self):
        rows = list(self._rows())
        valid = [r for r in rows if r[3]]
        best = min((r[2] for r in valid), default=0)
        best_s = [min((r[i] for r in valid if r[i] > 0), default=0) for i in (4, 5, 6)]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (s, num, lt, ok, s1, s2, s3, note) in enumerate(rows):
            muted = None if ok else theme.MUTED
            tm = _item(fmt_time(lt), lt if ok else lt + 10000, theme.PURPLE if ok and lt == best else muted,
                       Qt.AlignRight | Qt.AlignVCenter, bold=ok and lt == best)
            tm.setData(Qt.UserRole, (s.path, num))
            if not ok:
                tm.setToolTip(note)
            t.setItem(i, 0, tm)
            for c, (v, b) in enumerate(zip((s1, s2, s3), best_s)):
                t.setItem(i, 1 + c, _item(f"{v:.3f}" if v > 0 else "—", v or 1e9,
                                          theme.PURPLE if ok and v > 0 and v == b else muted,
                                          Qt.AlignRight | Qt.AlignVCenter))
            car = _item(s.car, s.car, muted)
            car.setToolTip(f"{s.car} · {s.car_class}")
            t.setItem(i, 4, car)
            who = f"📥 {s.driver}" if s.imported else (s.driver or "tú")
            t.setItem(i, 5, _item(who, who, theme.AMBER if s.imported else muted))
            t.setItem(i, 6, _item(s.recorded, s.recorded, muted))
            t.setItem(i, 7, _item(SESSION_TYPES.get(s.session_type, s.session_type), s.session_type, theme.MUTED))
            t.setItem(i, 8, _item(f"V{num}", num, muted, Qt.AlignCenter))
        t.setSortingEnabled(True)
        n_sessions = len({r[0].path for r in rows})
        self.info.setText(f"{len(rows)} vueltas de {n_sessions} sesiones  ·  doble clic para comparar  ·  "
                          "morado: mejor vuelta / mejores sectores de la lista")

    def _accept(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        self.choice = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        self.accept()
