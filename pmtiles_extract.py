"""
Lettura ed estrazione di archivi PMTiles v3 (mappe in un unico file).

Serve a creare una mappa offline ritagliando, da un archivio remoto molto grande
(es. la build giornaliera di OpenStreetMap di Protomaps), solo l'area del percorso.
Usa solo la libreria standard: richieste HTTP con intestazione Range.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import os
import struct
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

HEADER_LEN = 127
ROOT_MAX = 16384 - HEADER_LEN
C_NONE, C_GZIP = 1, 2
USER_AGENT = "RouteRewind/1.0 (offline map extract)"


class PMTilesError(Exception):
    pass


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- #
# Tile ID (curva di Hilbert)
# --------------------------------------------------------------------------- #
def zxy_to_tileid(z: int, x: int, y: int) -> int:
    acc = ((1 << (2 * z)) - 1) // 3
    n = 1 << z
    d = 0
    s = n >> 1
    while s > 0:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x = n - 1 - x
                y = n - 1 - y
            x, y = y, x
        s >>= 1
    return acc + d


def tileid_to_zxy(tid: int):
    acc, z = 0, 0
    while True:
        num = 1 << (2 * z)
        if acc + num > tid:
            break
        acc += num
        z += 1
    d = tid - acc
    n = 1 << z
    x = y = 0
    s = 1
    t = d
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s *= 2
    return z, x, y


def lonlat_to_tile(lon, lat, z):
    lat = max(-85.05112878, min(85.05112878, lat))
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    r = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n)
    return min(n - 1, max(0, x)), min(n - 1, max(0, y))


def tiles_in_bbox(bbox, minzoom, maxzoom):
    """bbox = (min_lon, min_lat, max_lon, max_lat). Restituisce gli ID ordinati."""
    ids = []
    for z in range(minzoom, maxzoom + 1):
        x0, y1 = lonlat_to_tile(bbox[0], bbox[1], z)
        x1, y0 = lonlat_to_tile(bbox[2], bbox[3], z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                ids.append(zxy_to_tileid(z, x, y))
    ids.sort()
    return ids


# --------------------------------------------------------------------------- #
# Formato binario
# --------------------------------------------------------------------------- #
_HDR = struct.Struct("<7sB QQ QQ QQ QQ QQQ BBBB BB iiii B ii")
assert _HDR.size == HEADER_LEN


@dataclass
class Header:
    root_offset: int
    root_length: int
    metadata_offset: int
    metadata_length: int
    leaf_offset: int
    leaf_length: int
    data_offset: int
    data_length: int
    addressed_tiles: int
    tile_entries: int
    tile_contents: int
    clustered: int
    internal_compression: int
    tile_compression: int
    tile_type: int
    min_zoom: int
    max_zoom: int
    min_lon_e7: int
    min_lat_e7: int
    max_lon_e7: int
    max_lat_e7: int
    center_zoom: int
    center_lon_e7: int
    center_lat_e7: int

    @classmethod
    def parse(cls, buf: bytes) -> "Header":
        v = _HDR.unpack(buf[:HEADER_LEN])
        if v[0] != b"PMTiles":
            raise PMTilesError("Il file non è un archivio PMTiles.")
        if v[1] != 3:
            raise PMTilesError(f"Versione PMTiles {v[1]} non supportata (serve la 3).")
        return cls(*v[2:])

    def pack(self) -> bytes:
        return _HDR.pack(b"PMTiles", 3, *self.__dict__.values())


def _read_varint(b, pos):
    shift = result = 0
    while True:
        byte = b[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7


def _write_varint(out: bytearray, v: int):
    while v >= 0x80:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)


def _decompress(data: bytes, comp: int) -> bytes:
    if comp in (0, C_NONE):
        return data
    if comp == C_GZIP:
        return gzip.decompress(data)
    raise PMTilesError("Compressione interna non supportata (serve gzip).")


def _compress(data: bytes, comp: int) -> bytes:
    if comp == C_GZIP:
        return gzip.compress(data, compresslevel=9, mtime=0)
    return data


@dataclass
class Entry:
    tile_id: int
    offset: int
    length: int
    run_length: int


def deserialize_directory(raw: bytes) -> list[Entry]:
    n, pos = _read_varint(raw, 0)
    entries = []
    last = 0
    for _ in range(n):
        v, pos = _read_varint(raw, pos)
        last += v
        entries.append(Entry(last, 0, 0, 0))
    for e in entries:
        e.run_length, pos = _read_varint(raw, pos)
    for e in entries:
        e.length, pos = _read_varint(raw, pos)
    for i, e in enumerate(entries):
        v, pos = _read_varint(raw, pos)
        if v == 0 and i > 0:
            e.offset = entries[i - 1].offset + entries[i - 1].length
        else:
            e.offset = v - 1
    return entries


def serialize_directory(entries: list[Entry]) -> bytes:
    out = bytearray()
    _write_varint(out, len(entries))
    last = 0
    for e in entries:
        _write_varint(out, e.tile_id - last)
        last = e.tile_id
    for e in entries:
        _write_varint(out, e.run_length)
    for e in entries:
        _write_varint(out, e.length)
    for i, e in enumerate(entries):
        if i > 0 and e.offset == entries[i - 1].offset + entries[i - 1].length:
            _write_varint(out, 0)
        else:
            _write_varint(out, e.offset + 1)
    return bytes(out)


def find_entry(entries: list[Entry], tid: int) -> Entry | None:
    i = _bisect(entries, tid)
    if i < 0:
        return None
    e = entries[i]
    if e.run_length == 0:          # puntatore a una directory foglia
        return e
    if tid - e.tile_id < e.run_length:
        return e
    return None


def _bisect(entries, tid):
    lo, hi = 0, len(entries)
    while lo < hi:
        mid = (lo + hi) // 2
        if entries[mid].tile_id <= tid:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


# --------------------------------------------------------------------------- #
# Sorgenti (URL o file locale)
# --------------------------------------------------------------------------- #
class Source:
    def __init__(self, location: str, timeout: float = 60):
        self.location = location
        self.timeout = timeout
        self.is_url = location.lower().startswith(("http://", "https://"))
        self.bytes_read = 0

    def read(self, offset: int, length: int) -> bytes:
        if length <= 0:
            return b""
        self.bytes_read += length
        if not self.is_url:
            with open(self.location, "rb") as f:
                f.seek(offset)
                return f.read(length)
        req = urllib.request.Request(self.location, headers={
            "Range": f"bytes={offset}-{offset + length - 1}", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            if r.status != 206 and offset != 0:
                raise PMTilesError("Il server non supporta le richieste parziali (Range).")
            data = r.read()
        return data[:length]


def find_latest_protomaps_build(days: int = 14, base: str = "https://build.protomaps.com/") -> str:
    """Cerca la build giornaliera più recente disponibile."""
    today = date.today()
    for i in range(days):
        url = f"{base}{(today - timedelta(days=i)):%Y%m%d}.pmtiles"
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status in (200, 206):
                    return url
        except Exception:
            continue
    raise PMTilesError("Nessuna mappa di base raggiungibile su build.protomaps.com: "
                       "controlla la connessione o indica un altro indirizzo.")


# --------------------------------------------------------------------------- #
# Estrazione
# --------------------------------------------------------------------------- #
class Extractor:
    """Due fasi: plan() calcola tessere e dimensione, run() scarica e scrive."""

    def __init__(self, location: str, bbox, maxzoom: int = 15, minzoom: int = 0,
                 progress=None, cancelled=lambda: False):
        self.src = Source(location)
        self.bbox = bbox
        self.minzoom, self.maxzoom = minzoom, maxzoom
        self.progress = progress or (lambda *_: None)
        self.cancelled = cancelled
        self.header: Header | None = None
        self._leaf_cache: dict[int, list[Entry]] = {}
        self.plan_result = None

    def _check(self):
        if self.cancelled():
            raise Cancelled()

    def _dir(self, offset, length) -> list[Entry]:
        return deserialize_directory(_decompress(self.src.read(offset, length), self.header.internal_compression))

    def plan(self):
        first = self.src.read(0, 16384)
        h = self.header = Header.parse(first)
        self.maxzoom = min(self.maxzoom, h.max_zoom)
        self.minzoom = max(self.minzoom, h.min_zoom)
        root_raw = first[h.root_offset:h.root_offset + h.root_length]
        if len(root_raw) < h.root_length:
            root_raw = self.src.read(h.root_offset, h.root_length)
        root = deserialize_directory(_decompress(root_raw, h.internal_compression))
        wanted = tiles_in_bbox(self.bbox, self.minzoom, self.maxzoom)
        found: list[tuple[int, int, int]] = []      # (tile_id, offset, length)
        total = len(wanted)
        for k, tid in enumerate(wanted):
            if k % 500 == 0:
                self._check()
                self.progress("plan", k, total)
            entries, depth = root, 0
            while depth < 4:
                e = find_entry(entries, tid)
                if e is None:
                    break
                if e.run_length > 0:
                    found.append((tid, e.offset, e.length))
                    break
                key = h.leaf_offset + e.offset
                if key not in self._leaf_cache:
                    self._leaf_cache[key] = self._dir(key, e.length)
                entries = self._leaf_cache[key]
                depth += 1
        contents = {}
        for _, off, ln in found:
            contents[off] = ln
        self.plan_result = found, contents
        self.progress("plan", total, total)
        return {"tiles": len(found), "contents": len(contents), "bytes": sum(contents.values()),
                "minzoom": self.minzoom, "maxzoom": self.maxzoom}

    def _fetch_contents(self, contents: dict[int, int], gap=32768, chunk=4 << 20, workers=4) -> dict[int, bytes]:
        h = self.header
        offs = sorted(contents)
        groups, cur = [], []
        for o in offs:
            if cur:
                start = cur[0]
                end = cur[-1] + contents[cur[-1]]
                if o - end <= gap and (o + contents[o] - start) <= chunk:
                    cur.append(o)
                    continue
                groups.append(cur)
            cur = [o]
        if cur:
            groups.append(cur)
        result: dict[int, bytes] = {}
        total = sum(contents.values())
        done = [0]

        def job(g):
            self._check()
            start = g[0]
            end = g[-1] + contents[g[-1]]
            blob = self.src.read(h.data_offset + start, end - start)
            part = {o: blob[o - start:o - start + contents[o]] for o in g}
            return part, sum(contents[o] for o in g)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for part, size in ex.map(job, groups):
                result.update(part)
                done[0] += size
                self.progress("download", done[0], total)
        return result

    def run(self, dest: str):
        if self.plan_result is None:
            self.plan()
        found, contents = self.plan_result
        if not found:
            raise PMTilesError("Nessuna tessera disponibile per quest'area.")
        h = self.header
        data = self._fetch_contents(contents)
        self._check()
        meta_raw = b""
        if h.metadata_length:
            meta = _decompress(self.src.read(h.metadata_offset, h.metadata_length), h.internal_compression)
            try:
                md = json.loads(meta)
                md["routerewind_extract"] = {"bbox": list(self.bbox), "maxzoom": self.maxzoom}
                meta = json.dumps(md).encode()
            except Exception:
                pass
            meta_raw = meta
        write_archive(dest, [(tid, data[off]) for tid, off, _ in found], h, self.bbox,
                      self.minzoom, self.maxzoom, meta_raw, content_keys=[off for _, off, _ in found])
        return dest


def _build_entries(tiles, content_keys=None):
    """tiles: lista ordinata (tile_id, bytes). Deduplica e applica il run-length."""
    entries: list[Entry] = []
    blobs = []
    seen: dict = {}
    offset = 0
    for i, (tid, blob) in enumerate(tiles):
        key = content_keys[i] if content_keys else blob
        if key in seen:
            off, ln = seen[key]
        else:
            off, ln = offset, len(blob)
            seen[key] = (off, ln)
            blobs.append(blob)
            offset += ln
        last = entries[-1] if entries else None
        if last and last.offset == off and last.tile_id + last.run_length == tid:
            last.run_length += 1
        else:
            entries.append(Entry(tid, off, ln, 1))
    return entries, b"".join(blobs), len(seen)


def _optimize_directories(entries, comp):
    root = _compress(serialize_directory(entries), comp)
    if len(root) <= ROOT_MAX:
        return root, b""
    leaf_size = 4096
    while True:
        leaves = bytearray()
        root_entries = []
        for i in range(0, len(entries), leaf_size):
            chunk = entries[i:i + leaf_size]
            ser = _compress(serialize_directory(chunk), comp)
            root_entries.append(Entry(chunk[0].tile_id, len(leaves), len(ser), 0))
            leaves += ser
        root = _compress(serialize_directory(root_entries), comp)
        if len(root) <= ROOT_MAX:
            return root, bytes(leaves)
        leaf_size *= 2


def write_archive(dest, tiles, src_header: Header, bbox, minzoom, maxzoom, metadata: bytes,
                  content_keys=None, internal_compression=C_GZIP):
    entries, blob, n_contents = _build_entries(tiles, content_keys)
    root, leaves = _optimize_directories(entries, internal_compression)
    meta = _compress(metadata or b"{}", internal_compression)
    root_off = HEADER_LEN
    meta_off = root_off + len(root)
    leaf_off = meta_off + len(meta)
    data_off = leaf_off + len(leaves)
    cz = max(minzoom, min(maxzoom, 10))
    h = Header(
        root_off, len(root), meta_off, len(meta), leaf_off, len(leaves), data_off, len(blob),
        sum(e.run_length for e in entries), len(entries), n_contents,
        1, internal_compression, src_header.tile_compression, src_header.tile_type,
        minzoom, maxzoom,
        int(bbox[0] * 1e7), int(bbox[1] * 1e7), int(bbox[2] * 1e7), int(bbox[3] * 1e7),
        cz, int((bbox[0] + bbox[2]) / 2 * 1e7), int((bbox[1] + bbox[3]) / 2 * 1e7),
    )
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(h.pack())
        f.write(root)
        f.write(meta)
        f.write(leaves)
        f.write(blob)
    os.replace(tmp, dest)


def read_tile(location: str, z: int, x: int, y: int) -> bytes | None:
    """Legge una singola tessera (usato nei test e per verificare un archivio)."""
    src = Source(location)
    h = Header.parse(src.read(0, HEADER_LEN))
    tid = zxy_to_tileid(z, x, y)
    entries = deserialize_directory(_decompress(src.read(h.root_offset, h.root_length), h.internal_compression))
    for _ in range(4):
        e = find_entry(entries, tid)
        if e is None:
            return None
        if e.run_length > 0:
            return src.read(h.data_offset + e.offset, e.length)
        entries = deserialize_directory(_decompress(src.read(h.leaf_offset + e.offset, e.length),
                                                    h.internal_compression))
    return None


def archive_info(path: str) -> dict:
    h = Header.parse(Source(path).read(0, HEADER_LEN))
    return {"bbox": [h.min_lon_e7 / 1e7, h.min_lat_e7 / 1e7, h.max_lon_e7 / 1e7, h.max_lat_e7 / 1e7],
            "minzoom": h.min_zoom, "maxzoom": h.max_zoom, "tile_type": h.tile_type,
            "size": os.path.getsize(path)}
