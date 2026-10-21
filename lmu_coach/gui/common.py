"""Utilidades comunes de la interfaz: tablas, nombres cortos de circuitos y formatos."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem

from .. import share


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
