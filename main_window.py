"""Finestra principale: mappa, animazione, cursore temporale, elenco punti, report."""
from __future__ import annotations

import json
import os
import tempfile
from bisect import bisect_right
from datetime import datetime, timedelta

from PySide6.QtCore import (QAbstractTableModel, QElapsedTimer, QEvent, QMarginsF, QModelIndex,
                            QObject, QSettings, Qt, QThread, QTimer, QUrl, Signal, Slot)
from PySide6.QtGui import (QAction, QDesktopServices, QIcon, QKeySequence, QPageLayout,
                           QPageSize)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog,
                               QFrame, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox,
                               QProgressDialog, QPushButton, QSizePolicy, QSlider, QStyle, QTableView,
                               QToolBar, QVBoxLayout, QWidget)

from app_info import (APP_NAME, APP_TAGLINE, APP_VERSION, AUTHOR, COPYRIGHT, WINDOW_TITLE,
                      resource_path)
from offline import OfflineLibrary, TileServer
from offline_ui import OfflineController
from parsers import SUPPORTED_EXTENSIONS, ParseError, load_track
from report import build_report_html, save_report
from track import compute_stats, fmt_dist, fmt_dt, fmt_duration

UNIFORM_SPEEDS = [0.25, 0.5, 1, 2, 3, 5, 8, 12, 20, 35, 60, 100, 200]          # punti al secondo
TIME_SPEEDS = [1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 21600, 86400]  # moltiplicatore
SLIDER_RES = 100   # passi del cursore tra due punti consecutivi


def time_speed_label(m: int) -> str:
    if m < 60:
        return f"×{m}  ({m} s al secondo)"
    if m < 3600:
        return f"×{m}  ({m // 60} min al secondo)"
    return f"×{m}  ({m / 3600:g} h al secondo)"


# --------------------------------------------------------------------------- #
class Bridge(QObject):
    """Ponte JavaScript → Python (clic su un punto della mappa)."""
    clicked = Signal(int)

    @Slot(int)
    def pointClicked(self, i):
        self.clicked.emit(int(i))


class LoaderThread(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        try:
            self.done.emit(load_track(self.path, progress=lambda c, t: self.progress.emit(c, t)))
        except ParseError as e:
            self.failed.emit(str(e))
        except Exception as e:  # imprevisti
            self.failed.emit(f"{type(e).__name__}: {e}")


class PointsModel(QAbstractTableModel):
    HEAD = ["#", "Data e ora", "Latitudine", "Longitudine", "km/h"]

    def __init__(self):
        super().__init__()
        self.pts, self.kmh = [], []

    def set_points(self, pts, kmh):
        self.beginResetModel()
        self.pts, self.kmh = pts, kmh
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.pts)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEAD)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return self.HEAD[s]
        return None

    def data(self, idx, role=Qt.DisplayRole):
        if role == Qt.TextAlignmentRole and idx.column() != 1:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            return self.pts[idx.row()].label or None
        if role != Qt.DisplayRole:
            return None
        p, c = self.pts[idx.row()], idx.column()
        if c == 0:
            return idx.row() + 1
        if c == 1:
            return fmt_dt(p.time)
        if c == 2:
            return f"{p.lat:.6f}"
        if c == 3:
            return f"{p.lon:.6f}"
        v = self.kmh[idx.row()]
        return f"{v:.1f}" if v is not None else "—"


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(QIcon(resource_path("assets", "icon.ico")))
        self.setAcceptDrops(True)
        self.settings = QSettings(AUTHOR, APP_NAME)

        self.result = None
        self.stats = None
        self.ts: list[float] = []          # timestamp (s) dei punti
        self.pos = 0.0                     # posizione corrente (indice frazionario)
        self.sim_t = 0.0                   # tempo simulato (modalità temporale)
        self.playing = False
        self.map_ready = False
        self._pending_js: list[str] = []
        self._loader = None
        self._last_row = -1

        self.offline_lib = OfflineLibrary()
        self.tile_server = TileServer(self.offline_lib.folder)
        self.offline = OfflineController(self, self.offline_lib, self.push_offline_maps)
        self._build_map()
        self._build_controls()
        self._build_table()
        self._build_actions()
        self.statusBar().showMessage("Pronto. Trascina un file sulla finestra o premi Ctrl+O.")

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()

        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1280, 800)
        self._set_enabled(False)

    # ------------------------------------------------------------------ UI
    def _build_map(self):
        # profilo con cache su disco: le mappe già viste restano disponibili anche senza rete
        prof = self.profile = QWebEngineProfile(APP_NAME, QApplication.instance())
        prof.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
        prof.setHttpCacheMaximumSize(512 * 1024 * 1024)
        prof.setHttpUserAgent(prof.httpUserAgent() + f" {APP_NAME}/{APP_VERSION}")
        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(prof, self.view))
        self.view.setAcceptDrops(False)
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.bridge = Bridge()
        self.bridge.clicked.connect(self._on_map_click)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.loadFinished.connect(self._on_map_loaded)
        self.view.load(QUrl.fromLocalFile(resource_path("web", "map.html")))
        self.view.installEventFilter(self)

    def _build_controls(self):
        st = self.style()
        self.btn_start = QPushButton(st.standardIcon(QStyle.SP_MediaSkipBackward), "")
        self.btn_start.setToolTip("Torna all'inizio (Home)")
        self.btn_play = QPushButton(st.standardIcon(QStyle.SP_MediaPlay), " Avvia")
        self.btn_play.setToolTip("Avvia / metti in pausa l'animazione (Spazio)")
        self.btn_play.setMinimumWidth(110)
        self.btn_stop = QPushButton(st.standardIcon(QStyle.SP_MediaStop), "")
        self.btn_stop.setToolTip("Ferma e torna all'inizio")
        self.btn_end = QPushButton(st.standardIcon(QStyle.SP_MediaSkipForward), "")
        self.btn_end.setToolTip("Vai alla fine (Fine)")
        self.btn_start.clicked.connect(lambda: self.seek(0))
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_end.clicked.connect(lambda: self.seek(len(self.result.points) - 1 if self.result else 0))

        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setToolTip("Trascina per scegliere il punto di partenza nella cronologia")
        self.timeline.valueChanged.connect(self._on_timeline)
        self.lbl_t0 = QLabel("—")
        self.lbl_t1 = QLabel("—")
        for l in (self.lbl_t0, self.lbl_t1):
            l.setStyleSheet("color:#64748b;")

        self.mode = QComboBox()
        self.mode.addItems(["Velocità uniforme (punti al secondo)", "Tempo reale accelerato"])
        self.mode.setToolTip("Uniforme: ogni punto dura lo stesso tempo.\n"
                             "Tempo reale: rispetta gli intervalli reali tra i punti, accelerati.")
        self.mode.currentIndexChanged.connect(self._on_mode)
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(0, len(UNIFORM_SPEEDS) - 1)
        self.speed.setValue(int(self.settings.value("speed", 4)))
        self.speed.setFixedWidth(200)
        self.speed.valueChanged.connect(self._update_speed_label)
        self.lbl_speed = QLabel()
        self.lbl_speed.setMinimumWidth(190)
        self.chk_follow = QCheckBox("Segui il segnaposto")
        self.chk_follow.setChecked(True)
        self.chk_follow.toggled.connect(lambda v: self.js(f"setFollow({str(v).lower()})"))
        self.btn_fit = QPushButton("Vedi tutto")
        self.btn_fit.clicked.connect(lambda: self.js("fitAll()"))
        self.lbl_info = QLabel("Nessun file caricato")
        self.lbl_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_info.setStyleSheet("font-weight:600;")

        row1 = QHBoxLayout()
        for w in (self.btn_start, self.btn_play, self.btn_stop, self.btn_end):
            row1.addWidget(w)
        row1.addSpacing(10)
        row1.addWidget(self.lbl_t0)
        row1.addWidget(self.timeline, 1)
        row1.addWidget(self.lbl_t1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Modalità:"))
        row2.addWidget(self.mode)
        row2.addSpacing(12)
        row2.addWidget(QLabel("Velocità:"))
        row2.addWidget(self.speed)
        row2.addWidget(self.lbl_speed)
        row2.addWidget(self.chk_follow)
        row2.addWidget(self.btn_fit)
        row2.addStretch(1)
        row3 = QHBoxLayout()
        row3.addWidget(self.lbl_info, 1)

        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addLayout(row3)

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self.view, 1)
        v.addWidget(panel)
        self.setCentralWidget(central)
        self._update_speed_label()

    def _build_table(self):
        self.model = PointsModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.clicked.connect(lambda idx: self.seek(idx.row()))
        dock = QDockWidget("Cronologia dei punti", self)
        dock.setObjectName("dock_points")
        dock.setWidget(self.table)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.dock = dock
        dock.resize(380, 600)

    def _build_actions(self):
        st = self.style()
        self.act_open = QAction(st.standardIcon(QStyle.SP_DialogOpenButton), "Apri…", self)
        self.act_open.setShortcut(QKeySequence.Open)
        self.act_open.triggered.connect(self.open_dialog)
        self.act_report = QAction(st.standardIcon(QStyle.SP_FileDialogDetailedView), "Report HTML…", self)
        self.act_report.setShortcut("Ctrl+R")
        self.act_report.triggered.connect(self.make_report)
        self.act_pdf = QAction(st.standardIcon(QStyle.SP_DialogSaveButton), "Report PDF…", self)
        self.act_pdf.setShortcut("Ctrl+P")
        self.act_pdf.triggered.connect(self.make_pdf)
        self.act_info = QAction(st.standardIcon(QStyle.SP_MessageBoxInformation), "Informazioni", self)
        self.act_info.setShortcut("F1")
        self.act_info.triggered.connect(self.show_info)
        self.act_off_save = QAction("Salva offline l'area del percorso…", self)
        self.act_off_save.triggered.connect(lambda: self.offline.download_route_area(self.result))
        self.act_off_import = QAction("Importa mappa offline (.pmtiles)…", self)
        self.act_off_import.triggered.connect(self.offline.import_file)
        self.act_off_manage = QAction("Gestisci mappe offline…", self)
        self.act_off_manage.triggered.connect(self.offline.manage)
        self.act_off_use = QAction("Passa alla mappa offline", self)
        self.act_off_use.triggered.connect(lambda: self.js("useOffline()"))
        act_quit = QAction("Esci", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)

        tb = QToolBar("Strumenti")
        tb.setObjectName("toolbar")
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setMovable(False)
        for a in (self.act_open, self.act_report, self.act_pdf):
            tb.addAction(a)
        tb.addSeparator()
        self.act_offline_menu = QAction(st.standardIcon(QStyle.SP_DriveHDIcon), "Mappe offline", self)
        self.act_offline_menu.triggered.connect(self.offline.manage)
        tb.addAction(self.act_offline_menu)
        tb.addAction(self.dock.toggleViewAction())
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.act_info)
        self.addToolBar(tb)

        m = self.menuBar().addMenu("&File")
        m.addAction(self.act_open)
        m.addSeparator()
        m.addAction(act_quit)
        m = self.menuBar().addMenu("&Report")
        m.addAction(self.act_report)
        m.addAction(self.act_pdf)
        m = self.menuBar().addMenu("&Mappe offline")
        for a in (self.act_off_save, self.act_off_import, self.act_off_manage):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_off_use)
        m = self.menuBar().addMenu("&Visualizza")
        m.addAction(self.dock.toggleViewAction())
        m = self.menuBar().addMenu("&?")
        m.addAction(self.act_info)

        for key, fn in ((Qt.Key_Space, self.toggle_play), (Qt.Key_Home, lambda: self.seek(0)),
                        (Qt.Key_Right, lambda: self.step(1)), (Qt.Key_Left, lambda: self.step(-1))):
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(fn)
            self.addAction(a)

    def _set_enabled(self, on: bool):
        for w in (self.btn_start, self.btn_play, self.btn_stop, self.btn_end, self.timeline,
                  self.act_report, self.act_pdf, self.btn_fit, self.act_off_save):
            w.setEnabled(on)
        self.mode.model().item(1).setEnabled(bool(on and self.result and self.result.has_times))

    # ------------------------------------------------------------------ JS
    def js(self, code: str, callback=None):
        if not self.map_ready:
            self._pending_js.append(code)
            return
        if callback:
            self.view.page().runJavaScript(code, 0, callback)
        else:
            self.view.page().runJavaScript(code)

    def _on_map_loaded(self, ok):
        self._wait_leaflet(0)
        for w in self.view.findChildren(QWidget):
            w.installEventFilter(self)

    def _wait_leaflet(self, tries):
        def cb(v):
            if v:
                self.map_ready = True
                pend, self._pending_js = self._pending_js, []
                for c in pend:
                    self.js(c)
                self.push_offline_maps()
            elif tries < 100:
                QTimer.singleShot(150, lambda: self._wait_leaflet(tries + 1))
        self.view.page().runJavaScript("window.isReady && window.isReady()", 0, cb)

    def push_offline_maps(self):
        maps = [{"name": mm["name"], "url": self.tile_server.url_for(mm["file"]), "bbox": mm["bbox"],
                 "maxzoom": mm["maxzoom"]} for mm in self.offline_lib.maps() if mm["vector"]]
        self.js(f"setOfflineMaps({json.dumps(maps)})")

    # ------------------------------------------------------------- caricamento
    def open_dialog(self):
        exts = " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Apri file con coordinate", self.settings.value("last_dir", ""),
            f"File supportati ({exts});;Tutti i file (*.*)")
        if path:
            self.load_file(path)

    def load_file(self, path: str):
        if self._loader and self._loader.isRunning():
            return
        self.pause()
        self.settings.setValue("last_dir", os.path.dirname(path))
        self.progress = QProgressDialog(f"Lettura di {os.path.basename(path)}…", "Annulla", 0, 0, self)
        self.progress.setCancelButton(None)
        self.progress.setWindowTitle(APP_NAME)
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setMinimumDuration(300)
        self._loader = LoaderThread(path, self)
        self._loader.progress.connect(self._on_load_progress)
        self._loader.done.connect(self._on_loaded)
        self._loader.failed.connect(self._on_load_failed)
        self._loader.start()

    def _on_load_progress(self, cur, tot):
        self.progress.setMaximum(tot)
        self.progress.setValue(cur)
        self.progress.setLabelText(f"Lettura pagina {cur} di {tot}…")

    def _on_load_failed(self, msg):
        self.progress.close()
        QMessageBox.warning(self, APP_NAME, f"Non è stato possibile caricare il file.\n\n{msg}")

    def _on_loaded(self, result):
        self.progress.close()
        self.result = result
        pts = result.points
        self.stats = compute_stats(pts)
        self.ts = [p.time.timestamp() for p in pts] if result.has_times else []
        self.model.set_points(pts, self.stats.seg_kmh)
        self.timeline.blockSignals(True)
        self.timeline.setRange(0, max(0, (len(pts) - 1) * SLIDER_RES))
        self.timeline.setValue(0)
        self.timeline.blockSignals(False)
        self.lbl_t0.setText(fmt_dt(pts[0].time) if pts[0].time else "1")
        self.lbl_t1.setText(fmt_dt(pts[-1].time) if pts[-1].time else str(len(pts)))
        if not result.has_times:
            self.mode.setCurrentIndex(0)
        self._set_enabled(True)
        data = [{"lat": p.lat, "lon": p.lon, "t": fmt_dt(p.time)} for p in pts]
        self.js(f"setTrack({json.dumps(data)})")
        self._last_row = -1
        self.seek(0)
        name = os.path.basename(result.source)
        self.setWindowTitle(f"{name} — {WINDOW_TITLE}")
        msg = (f"{name}: {len(pts)} punti · {fmt_dist(self.stats.distance_m)} · "
               f"durata {fmt_duration(self.stats.duration_s)} · lettura: {result.method}")
        self.statusBar().showMessage(msg)
        if result.warnings:
            QMessageBox.information(self, APP_NAME, "File caricato con alcune note:\n\n• " +
                                    "\n• ".join(result.warnings))

    # --------------------------------------------------------- drag & drop
    def _accept_drag(self, e) -> bool:
        md = e.mimeData()
        return md.hasUrls() and any(u.isLocalFile() for u in md.urls())

    def dragEnterEvent(self, e):
        if self._accept_drag(e):
            e.acceptProposedAction()
            self.js("showDrop(true)")

    def dragMoveEvent(self, e):
        if self._accept_drag(e):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.js("showDrop(false)")

    def dropEvent(self, e):
        self.js("showDrop(false)")
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            e.acceptProposedAction()
            self.load_file(files[0])

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.DragEnter:
            self.dragEnterEvent(ev)
            return True
        if t == QEvent.DragMove:
            self.dragMoveEvent(ev)
            return True
        if t == QEvent.DragLeave:
            self.dragLeaveEvent(ev)
            return True
        if t == QEvent.Drop:
            self.dropEvent(ev)
            return True
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------ animazione
    def _n(self):
        return len(self.result.points) if self.result else 0

    def _time_mode(self):
        return self.mode.currentIndex() == 1 and bool(self.ts)

    def _update_speed_label(self):
        i = self.speed.value()
        self.lbl_speed.setText(time_speed_label(TIME_SPEEDS[i]) if self.mode.currentIndex() == 1
                               else f"{UNIFORM_SPEEDS[i]:g} punti al secondo")
        self.settings.setValue("speed", i)

    def _on_mode(self, _):
        self._update_speed_label()
        self.sim_t = self._pos_to_time(self.pos)

    def _pos_to_time(self, f):
        if not self.ts:
            return 0.0
        i = int(f)
        if i >= len(self.ts) - 1:
            return self.ts[-1]
        return self.ts[i] + (f - i) * (self.ts[i + 1] - self.ts[i])

    def _time_to_pos(self, t):
        ts = self.ts
        if t <= ts[0]:
            return 0.0
        if t >= ts[-1]:
            return float(len(ts) - 1)
        i = bisect_right(ts, t) - 1
        span = ts[i + 1] - ts[i]
        return i + ((t - ts[i]) / span if span > 0 else 0.0)

    def toggle_play(self):
        if not self.result:
            return
        self.pause() if self.playing else self.play()

    def play(self):
        if self.pos >= self._n() - 1:
            self.seek(0)
        self.sim_t = self._pos_to_time(self.pos)
        self.playing = True
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.btn_play.setText(" Pausa")
        self.clock.start()
        self.timer.start()

    def pause(self):
        self.playing = False
        self.timer.stop()
        self.btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_play.setText(" Avvia")

    def stop(self):
        self.pause()
        self.seek(0)

    def step(self, d):
        if self.result:
            self.pause()
            self.seek(max(0, min(self._n() - 1, round(self.pos) + d)))

    def seek(self, f):
        if not self.result:
            return
        self.pos = float(max(0, min(self._n() - 1, f)))
        self.sim_t = self._pos_to_time(self.pos)
        self._apply()

    def _tick(self):
        dt = self.clock.restart() / 1000.0
        i = self.speed.value()
        if self._time_mode():
            self.sim_t += TIME_SPEEDS[i] * dt
            self.pos = self._time_to_pos(self.sim_t)
        else:
            self.pos += UNIFORM_SPEEDS[i] * dt
        if self.pos >= self._n() - 1:
            self.pos = float(self._n() - 1)
            self._apply()
            self.pause()
            return
        self._apply()

    def _on_timeline(self, v):
        self.pos = v / SLIDER_RES
        self.sim_t = self._pos_to_time(self.pos)
        self._apply(update_slider=False)

    def _on_map_click(self, i):
        self.seek(i)

    def _apply(self, update_slider=True):
        self.js(f"setPosition({self.pos:.4f})")
        if update_slider:
            self.timeline.blockSignals(True)
            self.timeline.setValue(int(round(self.pos * SLIDER_RES)))
            self.timeline.blockSignals(False)
        n = self._n()
        i = int(self.pos)
        k = self.pos - i
        pts = self.result.points
        a, b = pts[i], pts[min(i + 1, n - 1)]
        lat = a.lat + (b.lat - a.lat) * k
        lon = a.lon + (b.lon - a.lon) * k
        when = "—"
        if self.ts:
            when = fmt_dt(datetime.fromtimestamp(self._pos_to_time(self.pos)).replace(microsecond=0))
        elif a.time:
            when = fmt_dt(a.time)
        dist = self.stats.cum_dist[i] + (self.stats.cum_dist[min(i + 1, n - 1)] - self.stats.cum_dist[i]) * k
        self.lbl_info.setText(f"Punto {i + 1} di {n}   ·   {when}   ·   {lat:.6f}, {lon:.6f}   ·   "
                              f"percorsi {fmt_dist(dist)} di {fmt_dist(self.stats.distance_m)}")
        row = int(round(self.pos))
        if row != self._last_row:
            self._last_row = row
            idx = self.model.index(row, 0)
            self.table.selectRow(row)
            self.table.scrollTo(idx, QAbstractItemView.EnsureVisible)

    # --------------------------------------------------------------- report
    def _ask_range(self):
        cur = int(round(self.pos))
        if cur == 0:
            return 0
        box = QMessageBox(self)
        box.setWindowTitle("Report")
        box.setText("Quale parte del percorso vuoi nel report?")
        whole = box.addButton("Intero percorso", QMessageBox.AcceptRole)
        part = box.addButton(f"Dal punto attuale (n. {cur + 1}) alla fine", QMessageBox.AcceptRole)
        box.addButton("Annulla", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is whole:
            return 0
        if box.clickedButton() is part:
            return cur
        return None

    def _default_name(self, ext):
        stem = os.path.splitext(os.path.basename(self.result.source))[0]
        return os.path.join(self.settings.value("last_dir", ""),
                            f"Report_{stem}_{datetime.now():%Y%m%d_%H%M}.{ext}")

    def make_report(self):
        if not self.result:
            return
        start = self._ask_range()
        if start is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salva report HTML", self._default_name("html"),
                                              "Pagina web (*.html)")
        if not path:
            return
        save_report(self.result, path, start)
        if QMessageBox.question(self, APP_NAME, "Report salvato. Vuoi aprirlo nel browser?") == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def make_pdf(self):
        if not self.result:
            return
        start = self._ask_range()
        if start is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salva report PDF", self._default_name("pdf"),
                                              "Documento PDF (*.pdf)")
        if not path:
            return
        tmp = os.path.join(tempfile.gettempdir(), f"{APP_NAME}_report.html")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(build_report_html(self.result, start))
        # vista fuori schermo: serve a far disegnare la mappa prima della stampa
        self._pdf_view = QWebEngineView()
        self._pdf_view.setPage(QWebEnginePage(self.profile, self._pdf_view))
        self._pdf_view.setAttribute(Qt.WA_DontShowOnScreen, True)
        self._pdf_view.resize(1100, 1500)
        self._pdf_view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self._pdf_view.show()
        page = self._pdf_view.page()
        page.pdfPrintingFinished.connect(self._pdf_done)
        self._pdf_view.loadFinished.connect(lambda ok: self._pdf_wait(path, 0))
        self._pdf_progress = QProgressDialog("Creazione del PDF…", "Annulla", 0, 0, self)
        self._pdf_progress.setCancelButton(None)
        self._pdf_progress.setWindowModality(Qt.WindowModal)
        self._pdf_progress.show()
        self._pdf_view.load(QUrl.fromLocalFile(tmp))

    def _pdf_wait(self, path, tries):
        def cb(ready):
            if ready or tries > 40:
                layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(10, 10, 10, 10),
                                     QPageLayout.Millimeter)
                QTimer.singleShot(700, lambda: self._pdf_view.page().printToPdf(path, layout))
            else:
                QTimer.singleShot(250, lambda: self._pdf_wait(path, tries + 1))
        self._pdf_view.page().runJavaScript("window.reportReady === true", 0, cb)

    def _pdf_done(self, path, ok):
        self._pdf_progress.close()
        self._pdf_view.deleteLater()
        self._pdf_view = None
        if not ok:
            QMessageBox.warning(self, APP_NAME, "Creazione del PDF non riuscita.")
            return
        if QMessageBox.question(self, APP_NAME, "PDF salvato. Vuoi aprirlo?") == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ----------------------------------------------------------------- info
    def show_info(self):
        exts = ", ".join(e.lstrip(".").upper() for e in SUPPORTED_EXTENSIONS)
        QMessageBox.about(self, f"Informazioni su {APP_NAME}", f"""
            <h2 style="margin-bottom:0">{APP_NAME}</h2>
            <p style="margin-top:2px">{APP_TAGLINE}<br>Versione {APP_VERSION}</p>
            <p><b>Autore:</b> {AUTHOR}<br>{COPYRIGHT}</p>
            <p>Disegna su mappa il percorso di un segnaposto a partire da un file che contiene
            coordinate e data/ora, con animazione a velocità regolabile, cursore sulla cronologia
            e report del percorso.</p>
            <p><b>Formati supportati:</b> {exts}</p>
            <p style="color:#666;font-size:small">Realizzato con Qt for Python (PySide6) e Leaflet.
            Mappe © OpenStreetMap contributors, © CARTO, Esri;<br>mappe offline Protomaps (dati OpenStreetMap, licenza ODbL).</p>""")

    # ---------------------------------------------------------------- uscita
    def closeEvent(self, e):
        self.settings.setValue("geometry", self.saveGeometry())
        self.timer.stop()
        try:
            self.tile_server.stop()
        except Exception:
            pass
        super().closeEvent(e)
