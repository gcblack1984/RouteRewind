"""Punto di avvio: mostra subito lo splash, carica i moduli e apre la finestra principale."""
import os
import sys

from PySide6.QtCore import QCoreApplication, QElapsedTimer, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app_info import APP_ID, APP_NAME, APP_VERSION, AUTHOR, resource_path

SPLASH_MIN_MS = 3000


def _windows_taskbar_id():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


class Startup:
    """Caricamento a tappe: lo splash resta reattivo e la barra avanza davvero."""

    def __init__(self, app, splash, file_arg):
        self.app, self.splash, self.file_arg = app, splash, file_arg
        self.clock = QElapsedTimer()
        self.clock.start()
        self.window = None
        self.steps = [
            (8, "Avvio del motore grafico…", lambda: None),
            (30, "Caricamento del motore della mappa…", self._load_web),
            (50, "Caricamento dei lettori di file (PDF, Excel, Word)…", self._load_parsers),
            (65, "Preparazione dei report…", lambda: __import__("report")),
            (90, "Creazione della finestra…", self._make_window),
        ]
        self.shown = 0.0

    def start(self):
        QTimer.singleShot(50, self._next)

    def _load_web(self):
        import PySide6.QtWebEngineWidgets  # noqa: F401  (il modulo più pesante)
        import PySide6.QtWebChannel  # noqa: F401

    def _load_parsers(self):
        import parsers  # noqa: F401
        for mod in ("pdfplumber", "openpyxl", "docx"):
            try:
                __import__(mod)
            except ImportError:
                pass

    def _make_window(self):
        from main_window import MainWindow
        self.window = MainWindow()

    def _next(self):
        if self.steps:
            target, msg, fn = self.steps.pop(0)
            self.splash.set_progress(self.shown, msg)
            self.app.processEvents()
            fn()
            self.shown = target
            self.splash.set_progress(self.shown)
            QTimer.singleShot(10, self._next)
        else:
            self._finish()

    def _finish(self):
        # completa la barra in modo fluido fino a raggiungere almeno 3 secondi
        remaining = SPLASH_MIN_MS - self.clock.elapsed()
        if self.shown < 100:
            step = max(1.0, (100 - self.shown) / max(1, remaining / 30))
            self.shown = min(100.0, self.shown + step)
            self.splash.set_progress(self.shown, "Pronto" if self.shown >= 100 else "Quasi pronto…")
            QTimer.singleShot(30, self._finish)
            return
        if remaining > 0:
            QTimer.singleShot(int(remaining), self._finish)
            return
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.splash.close()
        if self.file_arg:
            self.window.load_file(self.file_arg)


def main():
    _windows_taskbar_id()
    # necessario per caricare QtWebEngine dopo la creazione dell'applicazione
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(AUTHOR)
    app.setWindowIcon(QIcon(resource_path("assets", "icon.ico")))
    app.setStyle("Fusion")

    from splash import SplashScreen
    splash = SplashScreen()
    splash.show()
    splash.raise_()
    app.processEvents()

    file_arg = next((a for a in sys.argv[1:] if os.path.isfile(a)), None)
    startup = Startup(app, splash, file_arg)
    startup.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
