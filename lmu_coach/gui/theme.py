"""Tema oscuro de la app."""
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#121318"
PANEL = "#1a1c22"
PANEL_2 = "#22252d"
BORDER = "#2e313a"
FG = "#e6e7ea"
MUTED = "#8b8f99"
ACCENT = "#3fb6ff"      # tu vuelta
REF = "#c9ccd4"         # referencia
GREEN = "#2ecc71"
RED = "#ff5a5a"
AMBER = "#ffb020"
PURPLE = "#b07cff"      # mejor vuelta / mejor sector

STYLESHEET = f"""
QWidget {{ background: {BG}; color: {FG}; font-family: 'Segoe UI'; font-size: 10pt; }}
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; spacing: 8px; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QLabel#title {{ font-size: 15pt; font-weight: 600; }}
QLabel#subtitle, QLabel.muted {{ color: {MUTED}; }}
QLabel#section {{ color: {MUTED}; font-size: 9pt; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
QTableWidget {{ background: {PANEL}; alternate-background-color: {PANEL_2}; gridline-color: transparent;
               border: 1px solid {BORDER}; border-radius: 6px; selection-background-color: #2b4a66; selection-color: {FG}; }}
QTableWidget::item {{ padding: 3px 6px; border: none; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 6px; font-weight: 600; font-size: 9pt; }}
QTableCornerButton::section {{ background: {PANEL}; border: none; }}
QComboBox {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 5px; padding: 4px 8px; min-width: 120px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: #2b4a66; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#coach {{ background: #1f7a45; border: none; font-weight: 600; padding: 7px 16px; }}
QPushButton#coach:hover {{ background: #25904f; }}
QPushButton#coach[running="true"] {{ background: #8a2a2a; }}
QPushButton#coach[running="true"]:hover {{ background: #a33232; }}
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {MUTED}; border-radius: 3px; background: {PANEL_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: none; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; background: {PANEL}; }}
QTabBar::tab {{ background: {BG}; color: {MUTED}; padding: 6px 16px; border: 1px solid {BORDER};
               border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {PANEL}; color: {FG}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {FG}; }}
QSlider::groove:horizontal {{ height: 6px; background: {PANEL_2}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {FG}; width: 14px; margin: -5px 0; border-radius: 7px; }}
QLineEdit {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 5px; padding: 5px 8px; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QScrollBar:vertical {{ background: {PANEL}; width: 12px; }}
QScrollBar:horizontal {{ background: {PANEL}; height: 12px; }}
QScrollBar::handle:vertical {{ background: #5a5e69; border-radius: 5px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #5a5e69; border-radius: 5px; min-width: 30px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""


def apply(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [
        (QPalette.Window, BG), (QPalette.WindowText, FG), (QPalette.Base, PANEL),
        (QPalette.AlternateBase, PANEL_2), (QPalette.Text, FG), (QPalette.Button, PANEL_2),
        (QPalette.ButtonText, FG), (QPalette.Highlight, "#2b4a66"), (QPalette.HighlightedText, FG),
        (QPalette.ToolTipBase, PANEL_2), (QPalette.ToolTipText, FG), (QPalette.PlaceholderText, MUTED),
    ]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLESHEET)
