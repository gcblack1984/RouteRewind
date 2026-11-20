"""Splash screen disegnata a mano, centrata sullo schermo, con barra di caricamento."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from app_info import APP_NAME, APP_TAGLINE, APP_VERSION, AUTHOR, COPYRIGHT, resource_path


class SplashScreen(QWidget):
    W, H = 600, 360

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)
        self._progress = 0.0
        self._message = "Avvio…"
        self._icon = QPixmap(resource_path("assets", "icon.png"))
        self.center_on_screen()

    def center_on_screen(self):
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.center().x() - self.W // 2, scr.center().y() - self.H // 2)

    def set_progress(self, value: float, message: str | None = None):
        self._progress = max(0.0, min(100.0, value))
        if message is not None:
            self._message = message
        self.repaint()

    # ------------------------------------------------------------------ #
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.W, self.H).adjusted(1, 1, -1, -1)

        bg = QLinearGradient(0, 0, self.W, self.H)
        bg.setColorAt(0, QColor("#0b1220"))
        bg.setColorAt(1, QColor("#13284a"))
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(path)

        # percorso stilizzato
        p.setClipPath(path)
        pts = [QPointF(330, 300), QPointF(380, 250), QPointF(360, 200), QPointF(430, 170),
               QPointF(470, 110), QPointF(540, 95)]
        route = QPainterPath(pts[0])
        for a, b in zip(pts[1::2], pts[2::2]):
            route.quadTo(a, b)
        p.setPen(QPen(QColor(96, 165, 250, 120), 5, Qt.DashLine, Qt.RoundCap))
        p.drawPath(route)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#22c55e"))
        p.drawEllipse(pts[0], 7, 7)
        self._draw_pin(p, QPointF(540, 95))
        p.setClipping(False)

        # testi
        x = 40
        if not self._icon.isNull():
            p.drawPixmap(x, 42, 56, 56, self._icon)
            tx = x + 70
        else:
            tx = x
        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Segoe UI", 28, QFont.DemiBold))
        p.drawText(QPointF(tx, 82), APP_NAME)
        p.setPen(QColor("#93c5fd"))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(QPointF(x, 130), APP_TAGLINE)
        p.setPen(QColor("#e2e8f0"))
        p.setFont(QFont("Segoe UI", 12, QFont.DemiBold))
        p.drawText(QPointF(x, 170), f"di {AUTHOR}")
        p.setPen(QColor("#94a3b8"))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QPointF(x, 192), f"Versione {APP_VERSION}")

        # barra di caricamento
        bar = QRectF(x, self.H - 74, self.W - 2 * x, 8)
        p.setBrush(QColor(255, 255, 255, 35))
        p.drawRoundedRect(bar, 4, 4)
        fill = QRectF(bar.x(), bar.y(), bar.width() * self._progress / 100, bar.height())
        g = QLinearGradient(bar.topLeft(), bar.topRight())
        g.setColorAt(0, QColor("#3b82f6"))
        g.setColorAt(1, QColor("#22d3ee"))
        p.setBrush(g)
        if fill.width() > 0:
            p.drawRoundedRect(fill, 4, 4)
        p.setPen(QColor("#cbd5e1"))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRectF(x, self.H - 58, self.W - 2 * x, 20), Qt.AlignLeft | Qt.AlignVCenter, self._message)
        p.drawText(QRectF(x, self.H - 58, self.W - 2 * x, 20), Qt.AlignRight | Qt.AlignVCenter,
                   f"{int(self._progress)}%")
        p.setPen(QColor("#64748b"))
        p.drawText(QRectF(x, self.H - 34, self.W - 2 * x, 20), Qt.AlignLeft | Qt.AlignVCenter, COPYRIGHT)
        p.end()

    @staticmethod
    def _draw_pin(p: QPainter, tip: QPointF):
        pin = QPainterPath()
        pin.moveTo(tip)
        pin.cubicTo(tip + QPointF(-18, -22), tip + QPointF(-14, -44), tip + QPointF(0, -44))
        pin.cubicTo(tip + QPointF(14, -44), tip + QPointF(18, -22), tip)
        p.setBrush(QColor("#ef4444"))
        p.drawPath(pin)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(tip + QPointF(0, -30), 6, 6)
