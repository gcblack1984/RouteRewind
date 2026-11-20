"""
Mappe offline: archivio dei file .pmtiles e piccolo server HTTP locale
(serve le mappe alla pagina della mappa con richieste parziali Range).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

from pmtiles_extract import PMTilesError, archive_info

DEFAULT_SOURCE = "auto"   # = build giornaliera più recente di Protomaps


def default_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "RouteRewind", "offline")
    os.makedirs(d, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    name = re.sub(r"[^\w\- ]+", "_", name, flags=re.UNICODE).strip() or "mappa"
    return name[:60]


class OfflineLibrary:
    """Elenco delle mappe offline salvate nella cartella dell'app."""

    def __init__(self, folder: str | None = None):
        self.folder = folder or default_dir()
        os.makedirs(self.folder, exist_ok=True)

    def maps(self) -> list[dict]:
        out = []
        for fn in sorted(os.listdir(self.folder)):
            if not fn.lower().endswith(".pmtiles"):
                continue
            path = os.path.join(self.folder, fn)
            try:
                info = archive_info(path)
            except (PMTilesError, OSError, Exception):
                continue
            meta = {}
            side = path + ".json"
            if os.path.exists(side):
                try:
                    meta = json.load(open(side, encoding="utf-8"))
                except Exception:
                    meta = {}
            info.update({"file": fn, "path": path,
                         "name": meta.get("name") or os.path.splitext(fn)[0],
                         "created": meta.get("created", ""),
                         "vector": info["tile_type"] == 1})
            out.append(info)
        return out

    def new_path(self, name: str) -> str:
        base = safe_name(name)
        path = os.path.join(self.folder, base + ".pmtiles")
        i = 2
        while os.path.exists(path):
            path = os.path.join(self.folder, f"{base}_{i}.pmtiles")
            i += 1
        return path

    def write_meta(self, path: str, name: str, extra: dict | None = None):
        meta = {"name": name, "created": datetime.now().strftime("%d/%m/%Y %H:%M")}
        meta.update(extra or {})
        with open(path + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)

    def import_file(self, src: str) -> str:
        archive_info(src)               # verifica che sia un PMTiles valido
        name = os.path.splitext(os.path.basename(src))[0]
        dst = self.new_path(name)
        shutil.copyfile(src, dst)
        self.write_meta(dst, name, {"imported_from": src})
        return dst

    def delete(self, path: str):
        for p in (path, path + ".json"):
            if os.path.exists(p):
                os.remove(p)


# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    folder = ""

    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Range, If-Match")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, ETag")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_HEAD(self):
        self._serve(head=True)

    def do_GET(self):
        self._serve(head=False)

    def _serve(self, head):
        name = os.path.basename(unquote(self.path.split("?", 1)[0]))
        path = os.path.join(self.folder, name)
        if not name.lower().endswith(".pmtiles") or not os.path.isfile(path):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        size = os.path.getsize(path)
        etag = f'"{int(os.path.getmtime(path))}-{size}"'
        start, end = 0, size - 1
        partial = False
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m:
            partial = True
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self._cors()
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self._cors()
        self.end_headers()
        if head:
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass


class TileServer:
    """Server HTTP su 127.0.0.1 con porta libera scelta dal sistema."""

    def __init__(self, folder: str):
        handler = type("Handler", (_Handler,), {"folder": folder})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url_for(self, filename: str) -> str:
        return f"http://127.0.0.1:{self.port}/{quote(filename)}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
