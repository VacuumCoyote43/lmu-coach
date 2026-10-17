"""Pantalla de carga animada: un coche da vueltas a un circuito mientras la app arranca.

Solo depende de PySide6 para poder mostrarse antes de importar lo pesado (numpy, duckdb, pyqtgraph).
"""
import math
import time

from PySide6.QtCore import QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import theme

W, H = 460, 300
LAP_S = 2.6          # segundos por vuelta del coche
TRAIL = 0.16         # longitud de la estela (fracción de vuelta)


def _circuit(rect: QRectF) -> QPainterPath:
    """Trazado estilizado: recta principal, horquilla, chicane y curva rápida."""
    x0, y0, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    p = lambda fx, fy: QPointF(x0 + fx * w, y0 + fy * h)
    path = QPainterPath(p(0.18, 0.92))
    path.lineTo(p(0.78, 0.92))                                     # recta de meta
    path.cubicTo(p(0.98, 0.92), p(1.0, 0.62), p(0.86, 0.55))      # curva 1
    path.cubicTo(p(0.74, 0.50), p(0.70, 0.38), p(0.80, 0.28))      # chicane
    path.cubicTo(p(0.92, 0.16), p(0.84, 0.0), p(0.66, 0.04))       # horquilla
    path.lineTo(p(0.32, 0.10))                                     # recta de atrás
    path.cubicTo(p(0.08, 0.14), p(0.0, 0.34), p(0.12, 0.48))       # curva rápida
    path.cubicTo(p(0.22, 0.60), p(0.10, 0.70), p(0.06, 0.80))      # ese
    path.cubicTo(p(0.03, 0.90), p(0.08, 0.92), p(0.18, 0.92))
    return path


class Splash(QWidget):
    def __init__(self, version: str = ""):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.version = version
        self.status = "Arrancando…"
        self.fraction = None            # progreso 0..1 cuando se conoce
        self._t0 = time.perf_counter()
        self._icon = QPixmap()
        self._track = _circuit(QRectF(150, 70, 280, 150))
        screen = QApplication.primaryScreen()
        if screen:
            self.move(screen.availableGeometry().center() - self.rect().center())
        self._timer = QTimer(self, interval=16, timeout=self.update)
        self._timer.start()
        self._fade = None

    def set_icon(self, path):
        self._icon = QPixmap(str(path))

    def set_status(self, text: str, fraction: float | None = None):
        self.status = text
        self.fraction = fraction
        self.update()

    def show(self):
        self.setWindowOpacity(0.0)
        super().show()
        self._animate_opacity(1.0, 180)

    def finish(self):
        """Desvanece y cierra la pantalla de carga."""
        self._animate_opacity(0.0, 220, self.close)

    def _animate_opacity(self, end, ms, then=None):
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(ms)
        self._fade.setEndValue(end)
        if then:
            self._fade.finished.connect(then)
        self._fade.start()

    def closeEvent(self, e):
        self._timer.stop()
        super().closeEvent(e)

    # --- dibujo -----------------------------------------------------------

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        # panel
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(r, 14, 14)

        # icono, nombre y versión
        if not self._icon.isNull():
            p.drawPixmap(QRectF(30, 34, 56, 56).toRect(), self._icon)
        p.setPen(QColor(theme.FG))
        p.setFont(QFont("Segoe UI", 17, QFont.DemiBold))
        p.drawText(QRectF(28, 98, 130, 32), Qt.AlignLeft | Qt.AlignVCenter, "LMU Coach")
        p.setPen(QColor(theme.MUTED))
        p.setFont(QFont("Segoe UI", 9))
        if self.version:
            p.drawText(QRectF(30, 128, 120, 20), Qt.AlignLeft | Qt.AlignVCenter, f"versión {self.version}")
        p.drawText(QRectF(30, 148, 120, 40), Qt.AlignLeft | Qt.TextWordWrap, "Telemetría y coach\npara Le Mans Ultimate")

        self._paint_track(p)

        # estado y barra
        p.setPen(QColor(theme.MUTED))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(30, 238, W - 60, 20), Qt.AlignLeft | Qt.AlignVCenter, self.status)
        bar = QRectF(30, 264, W - 60, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.PANEL_2))
        p.drawRoundedRect(bar, 2, 2)
        p.setBrush(QColor(theme.ACCENT))
        if self.fraction is not None:
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * max(0.02, min(1.0, self.fraction)), 4), 2, 2)
        else:   # indeterminada: un tramo que va y viene
            t = (time.perf_counter() - self._t0) / 1.4
            x = (0.5 - 0.5 * math.cos(t * math.pi)) * (bar.width() * 0.7)
            p.drawRoundedRect(QRectF(bar.x() + x, bar.y(), bar.width() * 0.3, 4), 2, 2)
        p.end()

    def _paint_track(self, p: QPainter):
        # asfalto
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.PANEL_2), 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(self._track)
        p.setPen(QPen(QColor(theme.BORDER), 1.2, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(self._track)

        # línea de meta
        start = self._track.pointAtPercent(0.04)
        p.setPen(QPen(QColor(theme.FG), 2))
        p.drawLine(QPointF(start.x(), start.y() - 6), QPointF(start.x(), start.y() + 6))

        # estela del coche: segmentos cada vez más opacos hasta el coche
        pos = ((time.perf_counter() - self._t0) / LAP_S) % 1.0
        steps = 28
        accent = QColor(theme.ACCENT)
        for i in range(steps):
            a = (pos - TRAIL * (1 - i / steps)) % 1.0
            b = (pos - TRAIL * (1 - (i + 1) / steps)) % 1.0
            c = QColor(accent)
            c.setAlphaF(((i + 1) / steps) ** 1.6 * 0.9)
            p.setPen(QPen(c, 1.5 + 3.5 * (i + 1) / steps, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(self._track.pointAtPercent(a), self._track.pointAtPercent(b))

        # coche con halo
        car = self._track.pointAtPercent(pos)
        glow = QColor(accent)
        glow.setAlphaF(0.25)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(car, 9, 9)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(car, 4, 4)
