"""Finestre per le mappe offline: scaricamento dell'area del percorso e gestione."""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QProgressDialog, QPushButton,
                               QVBoxLayout)

from app_info import APP_NAME
from offline import OfflineLibrary
from pmtiles_extract import Cancelled, Extractor, PMTilesError, find_latest_protomaps_build

DETAILS = [("Dettaglio massimo: vie e numeri civici (zoom 15)", 15),
           ("Strade (zoom 14)", 14),
           ("Strade principali e paesi (zoom 12)", 12)]


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def bbox_with_margin(points, km: float):
    lats = [p.lat for p in points]
    lons = [p.lon for p in points]
    mid = (min(lats) + max(lats)) / 2
    dlat = km / 111.0
    dlon = km / (111.0 * max(0.2, math.cos(math.radians(mid))))
    return (max(-180, min(lons) - dlon), max(-85, min(lats) - dlat),
            min(180, max(lons) + dlon), min(85, max(lats) + dlat))


class ExtractThread(QThread):
    planned = Signal(dict)
    finished_ok = Signal(str)
    failed = Signal(str)
    progress = Signal(str, int, int)

    def __init__(self, source: str, bbox, maxzoom: int, dest: str, parent=None):
        super().__init__(parent)
        self.source, self.bbox, self.maxzoom, self.dest = source, bbox, maxzoom, dest
        self.extractor = None
        self.stage = "plan"
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self.stage == "plan":
                url = self.source
                if not url or url == "auto":
                    self.progress.emit("resolve", 0, 0)
                    url = find_latest_protomaps_build()
                self.extractor = Extractor(url, self.bbox, maxzoom=self.maxzoom,
                                           progress=lambda s, a, b: self.progress.emit(s, a, b),
                                           cancelled=lambda: self._cancel)
                self.planned.emit(self.extractor.plan())
            else:
                self.extractor.run(self.dest)
                self.finished_ok.emit(self.dest)
        except Cancelled:
            self.failed.emit("")
        except PMTilesError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class DownloadDialog(QDialog):
    def __init__(self, parent, default_name: str, source: str):
        super().__init__(parent)
        self.setWindowTitle("Salva offline l'area del percorso")
        self.name = QLineEdit(default_name)
        self.detail = QComboBox()
        for label, _ in DETAILS:
            self.detail.addItem(label)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0.5, 100)
        self.margin.setValue(3)
        self.margin.setSuffix(" km")
        self.source = QLineEdit("" if source == "auto" else source)
        self.source.setPlaceholderText("automatico: OpenStreetMap da build.protomaps.com")
        form = QFormLayout()
        form.addRow("Nome della mappa:", self.name)
        form.addRow("Dettaglio:", self.detail)
        form.addRow("Margine attorno al percorso:", self.margin)
        form.addRow("Sorgente (facoltativa):", self.source)
        note = QLabel("Serve Internet solo ora, per lo scaricamento. Prima di scaricare viene mostrata "
                      "la dimensione stimata.\nLa vista satellite non è disponibile offline.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b;")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Calcola dimensione")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(bb)
        self.resize(560, 0)

    def values(self):
        return (self.name.text().strip() or "Area percorso", DETAILS[self.detail.currentIndex()][1],
                self.margin.value(), self.source.text().strip() or "auto")


class OfflineController:
    """Coordina scaricamento, importazione e gestione; avvisa la finestra quando cambia l'elenco."""

    def __init__(self, window, library: OfflineLibrary, on_change):
        self.w = window
        self.lib = library
        self.on_change = on_change
        self.thread = None

    # ---------------------------------------------------------------- scarica
    def download_route_area(self, result):
        if not result:
            return
        if self.thread and self.thread.isRunning():
            return
        stem = os.path.splitext(os.path.basename(result.source))[0]
        src = self.w.settings.value("offline_source", "auto")
        dlg = DownloadDialog(self.w, f"Area {stem}", src)
        if dlg.exec() != QDialog.Accepted:
            return
        name, zoom, km, source = dlg.values()
        self.w.settings.setValue("offline_source", source)
        bbox = bbox_with_margin(result.points, km)
        self._name, self._bbox = name, bbox
        dest = self.lib.new_path(name)
        self.thread = ExtractThread(source, bbox, zoom, dest, self.w)
        self.progress = QProgressDialog("Collegamento alla mappa di base…", "Annulla", 0, 0, self.w)
        self.progress.setWindowTitle(APP_NAME)
        self.progress.setMinimumDuration(0)
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.canceled.connect(self.thread.cancel)
        self.thread.progress.connect(self._on_progress)
        self.thread.planned.connect(self._on_planned)
        self.thread.finished_ok.connect(self._on_done)
        self.thread.failed.connect(self._on_failed)
        self.progress.show()
        self.thread.start()

    def _on_progress(self, stage, a, b):
        if stage == "resolve":
            self.progress.setLabelText("Ricerca della mappa di base più recente…")
            self.progress.setMaximum(0)
            return
        self.progress.setMaximum(max(1, b))
        self.progress.setValue(min(a, b))
        if stage == "plan":
            self.progress.setLabelText(f"Calcolo dell'area: {a} di {b} tessere…")
        else:
            self.progress.setLabelText(f"Scaricamento: {fmt_bytes(a)} di {fmt_bytes(b)}")

    def _on_planned(self, plan):
        self.progress.hide()
        size = plan["bytes"]
        msg = (f"L'area scelta contiene {plan['tiles']:,} tessere (zoom {plan['minzoom']}–{plan['maxzoom']}).\n"
               f"Dimensione stimata: {fmt_bytes(size)}.\n\nVuoi scaricarla?").replace(",", ".")
        if size > 1.5 * 1024 ** 3:
            msg += "\n\nAttenzione: è molto grande. Puoi ridurre il dettaglio o il margine."
        if QMessageBox.question(self.w, APP_NAME, msg) != QMessageBox.Yes:
            self.progress.close()
            return
        self.progress.setLabelText("Scaricamento…")
        self.progress.setValue(0)
        self.progress.show()
        self.thread.wait()
        self.thread.stage = "run"
        self.thread._cancel = False
        self.thread.start()

    def _on_done(self, path):
        self.progress.close()
        self.lib.write_meta(path, self._name, {"bbox": list(self._bbox)})
        self.on_change()
        QMessageBox.information(self.w, APP_NAME, f"Mappa offline «{self._name}» salvata.\n"
                                "Verrà usata in automatico quando manca la connessione; "
                                "puoi anche sceglierla dal selettore dei livelli sulla mappa.")

    def _on_failed(self, msg):
        self.progress.close()
        dest = self.thread.dest
        for p in (dest, dest + ".part"):
            if os.path.exists(p):
                os.remove(p)
        if msg:
            QMessageBox.warning(self.w, APP_NAME, f"Scaricamento non riuscito.\n\n{msg}")

    # --------------------------------------------------------------- importa
    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self.w, "Importa mappa offline", "",
                                              "Mappe PMTiles (*.pmtiles)")
        if not path:
            return
        try:
            self.lib.import_file(path)
        except Exception as e:
            QMessageBox.warning(self.w, APP_NAME, f"File non valido.\n\n{e}")
            return
        self.on_change()

    # ---------------------------------------------------------------- gestisci
    def manage(self):
        dlg = QDialog(self.w)
        dlg.setWindowTitle("Mappe offline")
        lst = QListWidget()

        def refresh():
            lst.clear()
            for m in self.lib.maps():
                it = QListWidgetItem(f"{m['name']}   ·   {fmt_bytes(m['size'])}   ·   fino a zoom {m['maxzoom']}"
                                     + (f"   ·   {m['created']}" if m['created'] else ""))
                it.setData(256, m["path"])
                if not m["vector"]:
                    it.setToolTip("Mappa raster: non supportata (servono mappe vettoriali OpenStreetMap)")
                lst.addItem(it)
            if not lst.count():
                lst.addItem("Nessuna mappa offline. Carica un percorso e usa «Salva offline l'area del percorso».")

        def delete():
            it = lst.currentItem()
            path = it.data(256) if it else None
            if not path:
                return
            if QMessageBox.question(dlg, APP_NAME, f"Eliminare «{it.text().split('   ·')[0]}»?") == QMessageBox.Yes:
                try:
                    self.lib.delete(path)
                except OSError as e:
                    QMessageBox.warning(dlg, APP_NAME, f"Impossibile eliminare: {e}")
                refresh()
                self.on_change()

        b_add = QPushButton("Salva l'area del percorso…")
        b_add.clicked.connect(lambda: (dlg.accept(), self.download_route_area(self.w.result)))
        b_add.setEnabled(self.w.result is not None)
        b_imp = QPushButton("Importa file…")
        b_imp.clicked.connect(lambda: (self.import_file(), refresh()))
        b_del = QPushButton("Elimina")
        b_del.clicked.connect(delete)
        b_dir = QPushButton("Apri cartella")
        b_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.lib.folder)))
        b_close = QPushButton("Chiudi")
        b_close.clicked.connect(dlg.accept)
        row = QHBoxLayout()
        for b in (b_add, b_imp, b_del, b_dir):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_close)
        lay = QVBoxLayout(dlg)
        lay.addWidget(lst)
        lay.addLayout(row)
        dlg.resize(720, 360)
        refresh()
        dlg.exec()
