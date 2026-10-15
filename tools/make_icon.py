"""Genera assets/icon.ico y assets/icon.png: cronómetro con los tres sectores estilo F1."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen

OUT = Path(__file__).resolve().parent.parent / "assets"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#15161b"))
    p.drawRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    # Arcos de sector alrededor del cronómetro: morado, verde, amarillo
    rect = QRectF(52 * s, 44 * s, 152 * s, 152 * s)
    for i, color in enumerate(("#8e44ff", "#1fa85a", "#e0b000")):
        pen = QPen(QColor(color), 22 * s)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawArc(rect, int((90 - i * 120 - 4) * 16), int(-112 * 16))
    # Pulsador y aguja
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#e8e8ea"))
    p.drawRoundedRect(QRectF(114 * s, 14 * s, 28 * s, 20 * s), 5 * s, 5 * s)
    pen = QPen(QColor("#e8e8ea"), 14 * s)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(int(128 * s), int(120 * s), int(166 * s), int(86 * s))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(116 * s, 108 * s, 24 * s, 24 * s))
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    OUT.mkdir(exist_ok=True)
    draw(256).save(str(OUT / "icon.png"))
    draw(256).save(str(OUT / "icon.ico"))
    print("ok", OUT)
