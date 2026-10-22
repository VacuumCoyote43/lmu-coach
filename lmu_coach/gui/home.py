"""Pantalla de inicio (sin sesión abierta): empezar el coach, tu última sesión, tu objetivo más cercano y la
semana."""
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import car_pix, theme
from .common import SESSION_TYPES, short_track
from .. import goals, lapstats
from ..laps import fmt_time


def _card(title: str, body: str, hint: str = "") -> QPushButton:
    b = QPushButton()
    b.setObjectName("home_card")
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(120)
    lay = QVBoxLayout(b)
    t = QLabel(title)
    t.setObjectName("section")
    lay.addWidget(t)
    body_lb = QLabel(body)
    body_lb.setWordWrap(True)
    body_lb.setTextFormat(Qt.RichText)
    lay.addWidget(body_lb, 1)
    labels = [t, body_lb]
    if hint:
        h = QLabel(hint)
        h.setObjectName("subtitle")
        lay.addWidget(h)
        labels.append(h)
    for w in labels:
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        w.setStyleSheet("background: transparent;")
    b.body = body_lb
    return b


class HomePage(QWidget):
    open_session = Signal(object)
    start_coach = Signal()
    show_progress = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        title = QLabel("LMU Coach")
        title.setStyleSheet("font-size: 22pt; font-weight: 600;")
        outer.addWidget(title)
        self.sub = QLabel("Elige una sesión de la lista para analizarla, o sal a pista con el coach.")
        self.sub.setObjectName("subtitle")
        self.sub.setWordWrap(True)
        outer.addWidget(self.sub)
        outer.addSpacing(16)

        self.coach_btn = QPushButton("▶  Iniciar modo coach")
        self.coach_btn.setObjectName("coach")
        self.coach_btn.setMinimumHeight(48)
        self.coach_btn.setStyleSheet("font-size: 12pt;")
        self.coach_btn.clicked.connect(self.start_coach.emit)
        outer.addWidget(self.coach_btn)
        outer.addSpacing(12)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.last = _card("Tu última sesión", "—", "Clic para abrirla")
        self.goal = _card("Objetivo más cercano", "—", "Clic para ver Mi progreso")
        self.week = _card("Últimos 7 días", "—")
        self.week.setCursor(Qt.ArrowCursor)
        grid.addWidget(self.last, 0, 0, 1, 2)
        grid.addWidget(self.goal, 1, 0)
        grid.addWidget(self.week, 1, 1)
        outer.addLayout(grid)
        outer.addStretch(1)
        self._last_info = None
        self.last.clicked.connect(lambda: self._last_info and self.open_session.emit(self._last_info))
        self.goal.clicked.connect(self.show_progress.emit)

    def set_message(self, text: str):
        self.sub.setText(text)

    def set_coach_running(self, running: bool):
        self.coach_btn.setText("■  Detener modo coach" if running else "▶  Iniciar modo coach")
        self.coach_btn.setProperty("running", "true" if running else "false")
        self.coach_btn.style().unpolish(self.coach_btn)
        self.coach_btn.style().polish(self.coach_btn)

    def set_sessions(self, sessions):
        mine = [s for s in sessions if not s.imported and not s.error]
        mine.sort(key=lambda s: s.recorded, reverse=True)
        self._fill_last(mine)
        self._fill_goal(sessions)
        self._fill_week(mine)

    def _fill_last(self, mine):
        self._last_info = mine[0] if mine else None
        if not mine:
            self.last.body.setText("Aún no hay sesiones tuyas. Corre en LMU con la grabación de telemetría activada.")
            return
        s = mine[0]
        record = min((x.best for x in mine if x.track == s.track and x.car == s.car and x.best), default=0)
        is_record = s.best and abs(s.best - record) < 1e-6
        best = (f"<span style='color:{theme.PURPLE if is_record else theme.FG}'><b>{fmt_time(s.best)}</b></span>"
                + ("  · tu récord" if is_record else f"  · récord {fmt_time(record)}" if record else "")
                if s.best else "sin vueltas válidas")
        pix = car_pix.pixmap(s.car, "large", 60)
        img = ""
        if pix:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            pix.save(buf, "PNG")
            img = f"<img src='data:image/png;base64,{bytes(ba.toBase64()).decode()}' height='60'>&nbsp;&nbsp;"
        self.last.body.setText(
            f"<table><tr><td>{img}</td><td><span style='font-size:14pt; font-weight:600'>{short_track(s.track)}"
            f"</span> · {s.car.split(':')[0]}<br>{SESSION_TYPES.get(s.session_type, s.session_type)} · {s.recorded}"
            f" · {s.valid_laps} vueltas válidas · {best}</td></tr></table>")

    def _fill_goal(self, sessions):
        all_goals = goals.all_goals()
        if not all_goals:
            self.goal.body.setText("Sin objetivos. En <b>📈 Mi progreso</b> fija un tiempo que quieras conseguir "
                                   "en un circuito con un coche.")
            return
        best = None
        for c in lapstats.overview(sessions):
            g = all_goals.get((c.track, c.car, c.layout))
            if g is None or c.best <= g:
                continue
            gap = c.best - g
            if best is None or gap < best[0]:
                best = (gap, c, g)
        if best is None:
            self.goal.body.setText(f"<span style='color:{theme.GREEN}'><b>¡Todos conseguidos!</b></span> "
                                   "Pon uno nuevo en Mi progreso.")
            return
        gap, c, g = best
        self.goal.body.setText(
            f"<span style='font-size:13pt; font-weight:600'>{short_track(c.track)}</span> · {c.car.split(':')[0]}<br>"
            f"Objetivo <b>{fmt_time(g)}</b> · tu mejor {fmt_time(c.best)} · te faltan "
            f"<b style='color:{theme.AMBER}'>{gap:.3f} s</b>")

    def _fill_week(self, mine):
        since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        week = [s for s in mine if s.recorded[:10] >= since]
        if not week:
            self.week.body.setText("Sin sesiones esta semana.")
            return
        laps = sum(s.valid_laps for s in week)
        older = {}
        for s in mine:
            if s.recorded[:10] < since and s.best:
                k = (s.track, s.car)
                older[k] = min(older.get(k, 1e9), s.best)
        records = set()
        for s in week:
            k = (s.track, s.car)
            if s.best and s.best < older.get(k, 1e9):
                records.add(k)
        tracks = sorted({short_track(s.track) for s in week})
        self.week.body.setText(
            f"<span style='font-size:14pt; font-weight:600'>{len(week)}</span> sesiones · "
            f"<span style='font-size:14pt; font-weight:600'>{laps}</span> vueltas válidas<br>"
            f"{', '.join(tracks)}<br>"
            + (f"<span style='color:{theme.PURPLE}'><b>{len(records)} récord{'s' if len(records) != 1 else ''} "
               f"personal{'es' if len(records) != 1 else ''}</b></span>" if records else "Sin récords nuevos"))
