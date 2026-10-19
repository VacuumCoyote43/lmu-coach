"""Imágenes de los coches para la interfaz (con caché de pixmaps ya escalados)."""
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap

from ..car_images import CarImages
from ..sessions import find_lmu_dir

_images: CarImages | None = None
_cache: dict[tuple, QPixmap | None] = {}


def images() -> CarImages:
    global _images
    if _images is None:
        _images = CarImages(find_lmu_dir())
    return _images


def pixmap(car_name: str, kind: str = "thumb", height: int = 24) -> QPixmap | None:
    """Imagen del coche escalada a esa altura, o None si no hay."""
    key = (car_name, kind, height)
    if key not in _cache:
        data = images().image_bytes(car_name, kind)
        pix = None
        if data:
            img = QImage.fromData(data, "WEBP")
            if not img.isNull():
                # recortar el margen transparente para que el coche llene el hueco
                rect = _content_rect(img)
                img = img.copy(rect) if rect else img
                pix = QPixmap.fromImage(img.scaledToHeight(height, Qt.SmoothTransformation))
        _cache[key] = pix
    return _cache[key]


def forget_missing():
    """Tras aprender nombres nuevos, volver a intentar los coches que no tenían imagen."""
    for k in [k for k, v in _cache.items() if v is None]:
        del _cache[k]


def _content_rect(img: QImage):
    """Rectángulo con contenido (alfa > 8)."""
    import numpy as np
    from PySide6.QtCore import QRect
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8, count=img.sizeInBytes()).reshape(h, img.bytesPerLine())
    alpha = a[:, 3:w * 4:4] > 8          # ARGB32 en little-endian: B, G, R, A
    rows, cols = np.flatnonzero(alpha.any(1)), np.flatnonzero(alpha.any(0))
    if not len(rows):
        return None
    return QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))


class GameListWorker(QThread):
    """Si LMU está abierto, aprende su lista completa de decoraciones (para las más nuevas)."""
    learned = Signal()

    def run(self):
        if images().refresh_from_game():
            self.learned.emit()
