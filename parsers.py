"""
Estrazione di coordinate geografiche e data/ora da file di formati diversi.

Formati: PDF, CSV/TSV/TXT, XLSX/XLSM (XLS se è installato xlrd), DOCX,
GPX, KML/KMZ, GeoJSON/JSON (anche Google Takeout), NMEA, HTML.

Strategia: per ogni file si producono uno o più "candidati" (lettura come
tabella con intestazioni riconosciute, lettura riga per riga del testo, ...)
e si tiene quello con più punti datati.
"""
from __future__ import annotations

import csv
import html as html_mod
import io
import json
import os
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone

SUPPORTED_EXTENSIONS = [
    ".pdf", ".csv", ".tsv", ".txt", ".log", ".xlsx", ".xlsm", ".xls", ".docx",
    ".gpx", ".kml", ".kmz", ".geojson", ".json", ".nmea", ".html", ".htm",
]


# --------------------------------------------------------------------------- #
# Modello dati
# --------------------------------------------------------------------------- #
@dataclass
class TrackPoint:
    lat: float
    lon: float
    time: datetime | None = None
    label: str = ""


@dataclass
class ParseResult:
    points: list
    source: str
    method: str = ""
    warnings: list = field(default_factory=list)

    @property
    def has_times(self) -> bool:
        return bool(self.points) and all(p.time is not None for p in self.points)


class ParseError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Utilità numeri e coordinate
# --------------------------------------------------------------------------- #
def _valid(lat, lon) -> bool:
    return (lat is not None and lon is not None and -90 <= lat <= 90
            and -180 <= lon <= 180 and not (abs(lat) < 1e-9 and abs(lon) < 1e-9))


_DMS_RE = re.compile(
    r"""(?P<deg>\d{1,3}(?:[.,]\d+)?)\s*[°º˚]\s*
        (?:(?P<min>\d{1,2}(?:[.,]\d+)?)\s*['′’`]\s*)?
        (?:(?P<sec>\d{1,2}(?:[.,]\d+)?)\s*(?:"|″|''|”|′′)\s*)?
        (?P<hem>[NSEWO])(?![A-Za-z])""",
    re.X | re.I,
)


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _dms_value(m) -> tuple[float, str]:
    v = _f(m.group("deg"))
    if m.group("min"):
        v += _f(m.group("min")) / 60
    if m.group("sec"):
        v += _f(m.group("sec")) / 3600
    hem = m.group("hem").upper()
    if hem in ("S", "W", "O"):
        v = -v
    return v, ("lat" if hem in ("N", "S") else "lon")


def to_float(v) -> float | None:
    """Converte un valore di cella in numero (accetta virgola decimale, °, N/S/E/W, DMS)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    m = _DMS_RE.fullmatch(s)
    if m and (m.group("min") or m.group("sec")):
        return _dms_value(m)[0]
    if s.count(",") == 1 and "." not in s:
        s = s.replace(",", ".")
    m = re.fullmatch(r"([NSEWO])?([-+]?\d+(?:\.\d+)?)[°º]?([NSEWO])?", s, re.I)
    if not m:
        return None
    val = float(m.group(2))
    hem = (m.group(1) or m.group(3) or "").upper()
    if hem in ("S", "W", "O"):
        val = -abs(val)
    return val


_LAT_LBL = re.compile(r"\blat(?:itude|itudine|itud)?\b\.?\s*[:=]?\s*([-+]?\d{1,2}(?:[.,]\d+)?)\s*°?\s*([NS])?", re.I)
_LON_LBL = re.compile(r"\b(?:lon|lng|long)(?:itude|itudine|gitude|gitudine|itud)?\b\.?\s*[:=]?\s*([-+]?\d{1,3}(?:[.,]\d+)?)\s*°?\s*([EWO])?", re.I)
_HEM_PAIR = re.compile(r"([-+]?\d{1,2}[.,]\d+)\s*°?\s*([NS])(?![A-Za-z])[\s,;/]*([-+]?\d{1,3}[.,]\d+)\s*°?\s*([EWO])(?![A-Za-z])", re.I)
_DOT_PAIR = re.compile(r"(?<![\w.])([-+]?\d{1,2}\.\d{3,})°?(?:\s*[,;/|]\s*|\s+)([-+]?\d{1,3}\.\d{3,})°?(?![\w.])")
_COMMA_PAIR = re.compile(r"(?<![\w,])([-+]?\d{1,2},\d{4,})°?(?:\s*[;/|]\s*|\s+)([-+]?\d{1,3},\d{4,})°?(?![\w,])")
_LOOSE_PAIR = re.compile(r"([-+]?\d{1,3}(?:\.\d+)?)\s*[,;/\s]\s*([-+]?\d{1,3}(?:\.\d+)?)")


def find_coords(text: str, loose: bool = False) -> tuple[float, float] | None:
    """Cerca una coppia latitudine/longitudine in un testo libero."""
    if not text:
        return None
    # 1) gradi, primi, secondi con emisfero
    lat = lon = None
    for m in _DMS_RE.finditer(text):
        v, kind = _dms_value(m)
        if kind == "lat" and lat is None:
            lat = v
        elif kind == "lon" and lon is None:
            lon = v
    if _valid(lat, lon):
        return lat, lon
    # 2) etichette "Lat: ... Lon: ..."
    ml, mn = _LAT_LBL.search(text), _LON_LBL.search(text)
    if ml and mn:
        lat, lon = _f(ml.group(1)), _f(mn.group(1))
        if (ml.group(2) or "").upper() == "S":
            lat = -abs(lat)
        if (mn.group(2) or "").upper() in ("W", "O"):
            lon = -abs(lon)
        if _valid(lat, lon):
            return lat, lon
    # 3) decimali con emisfero "40.5 N 17.2 E"
    m = _HEM_PAIR.search(text)
    if m:
        lat, lon = _f(m.group(1)), _f(m.group(3))
        if m.group(2).upper() == "S":
            lat = -abs(lat)
        if m.group(4).upper() in ("W", "O"):
            lon = -abs(lon)
        if _valid(lat, lon):
            return lat, lon
    # 4) coppie decimali
    for rx in (_DOT_PAIR, _COMMA_PAIR) + ((_LOOSE_PAIR,) if loose else ()):
        for m in rx.finditer(text):
            lat, lon = _f(m.group(1)), _f(m.group(2))
            if _valid(lat, lon):
                return lat, lon
    return None


# --------------------------------------------------------------------------- #
# Utilità data/ora
# --------------------------------------------------------------------------- #
_MONTHS = {
    "gen": 1, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "may": 5,
    "giu": 6, "jun": 6, "lug": 7, "jul": 7, "ago": 8, "aug": 8, "set": 9,
    "sep": 9, "ott": 10, "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}
_T = r"(?:[\sT,]+(?:ore\s+|h\s*)?(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,6}))?)?\s*(Z|UTC|[+-]\d{2}:?\d{2})?)?"
_ISO_RE = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)" + _T, re.I)
_EU_RE = re.compile(r"(?<![\d.])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d.])" + _T, re.I)
_TXT_RE = re.compile(r"(?<!\d)(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})" + _T, re.I)
_TIME_RE = re.compile(r"(?<![\d:.,])(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,]\d{1,6})?)?(?![\d:])")


def _to_local_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _tz(s: str | None):
    if not s:
        return None
    s = s.upper()
    if s in ("Z", "UTC"):
        return timezone.utc
    sign = 1 if s[0] == "+" else -1
    s = s[1:].replace(":", "")
    return timezone(sign * timedelta(hours=int(s[:2]), minutes=int(s[2:4] or 0)))


def _build(y, mo, d, hh, mm, ss, frac, tz):
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        dd = date(y, mo, d)
    except ValueError:
        return None, None
    if hh is None:
        return "date", dd
    try:
        us = int((frac or "0").ljust(6, "0")[:6])
        dt = datetime(y, mo, d, int(hh), int(mm), int(ss or 0), us, tzinfo=_tz(tz))
    except ValueError:
        return "date", dd
    return "datetime", _to_local_naive(dt)


def find_datetime(text: str):
    """Restituisce (tipo, valore, spans). tipo: 'datetime' | 'date' | 'time' | None."""
    if not text:
        return None, None, []
    for rx, order in ((_ISO_RE, "ymd"), (_EU_RE, "dmy"), (_TXT_RE, "dMy")):
        for m in rx.finditer(text):
            g = m.groups()
            if order == "ymd":
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            elif order == "dmy":
                d, mo, y = int(g[0]), int(g[1]), int(g[2])
                if mo > 12 and d <= 12:      # formato USA mm/dd/yyyy
                    d, mo = mo, d
            else:
                mo = _MONTHS.get(g[1][:3].lower())
                if not mo:
                    continue
                d, y = int(g[0]), int(g[2])
            kind, val = _build(y, mo, d, g[3], g[4], g[5], g[6], g[7])
            if kind is None:
                continue
            spans = [m.span()]
            if kind == "date":   # ora in un'altra colonna della stessa riga
                rest = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
                mt = _TIME_RE.search(rest)
                if mt:
                    try:
                        t = dtime(int(mt.group(1)), int(mt.group(2)), int(mt.group(3) or 0))
                        return "datetime", datetime.combine(val, t), spans + [mt.span()]
                    except ValueError:
                        pass
            return kind, val, spans
    mt = _TIME_RE.search(text)
    if mt:
        try:
            return "time", dtime(int(mt.group(1)), int(mt.group(2)), int(mt.group(3) or 0)), [mt.span()]
        except ValueError:
            pass
    return None, None, []


def parse_cell_datetime(v, allow_serial: bool = False):
    """Interpreta il contenuto di una cella come data/ora. Restituisce (tipo, valore)."""
    if v is None or v == "":
        return None, None
    if isinstance(v, datetime):
        return "datetime", _to_local_naive(v)
    if isinstance(v, date):
        return "date", v
    if isinstance(v, dtime):
        return "time", v
    num = None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        num = float(v)
    elif isinstance(v, str) and re.fullmatch(r"\d{9,13}(\.\d+)?", v.strip()):
        num = float(v.strip())
    if num is not None:
        if 1e12 <= num < 1e14:                       # epoch in millisecondi
            return "datetime", _to_local_naive(datetime.fromtimestamp(num / 1000, timezone.utc))
        if 3e8 <= num < 1e11:                        # epoch in secondi
            return "datetime", _to_local_naive(datetime.fromtimestamp(num, timezone.utc))
        if allow_serial and 20000 < num < 80000:      # numero seriale Excel
            return "datetime", datetime(1899, 12, 30) + timedelta(days=num)
        if allow_serial and 0 <= num < 1:            # ora come frazione di giorno
            return "time", (datetime(2000, 1, 1) + timedelta(days=num)).time()
        return None, None
    s = str(v).strip()
    kind, val, _ = find_datetime(s)
    if kind:
        return kind, val
    try:
        from dateutil import parser as dparser
        dt = dparser.parse(s, dayfirst=True, fuzzy=False)
        return "datetime", _to_local_naive(dt)
    except Exception:
        return None, None


# --------------------------------------------------------------------------- #
# Lettura riga per riga (testo libero)
# --------------------------------------------------------------------------- #
def _blank(text: str, spans) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


def points_from_lines(lines) -> list[TrackPoint]:
    pts: list[TrackPoint] = []
    cur_date: date | None = None
    pending: datetime | None = None
    for raw in lines:
        line = str(raw).strip()
        if not line:
            continue
        if line.startswith("$") and "RMC," in line[:8]:
            p = _nmea_rmc(line)
            if p:
                pts.append(p)
            continue
        kind, val, spans = find_datetime(line)
        coord = find_coords(_blank(line, spans))
        if kind == "date":
            cur_date = val
        if coord is None:
            if kind == "datetime":
                pending = val
            elif kind == "time" and cur_date:
                pending = datetime.combine(cur_date, val)
            continue
        t = None
        if kind == "datetime":
            t = val
        elif kind == "time":
            t = datetime.combine(cur_date, val) if cur_date else None
        elif kind == "date":
            t = datetime.combine(val, dtime())
        elif pending is not None:
            t = pending
        pending = None
        pts.append(TrackPoint(coord[0], coord[1], t, line[:240]))
    return pts


def _nmea_rmc(line: str) -> TrackPoint | None:
    f = line.split("*")[0].split(",")
    try:
        if len(f) < 10 or f[2] != "A":
            return None
        def conv(v, hemi, degw):
            deg = float(v[:degw]); mins = float(v[degw:])
            val = deg + mins / 60
            return -val if hemi in ("S", "W") else val
        lat = conv(f[3], f[4], 2)
        lon = conv(f[5], f[6], 3)
        t, d = f[1], f[9]
        dt = datetime(2000 + int(d[4:6]), int(d[2:4]), int(d[0:2]),
                      int(t[0:2]), int(t[2:4]), int(float(t[4:])), tzinfo=timezone.utc)
        return TrackPoint(lat, lon, _to_local_naive(dt), line[:240])
    except (ValueError, IndexError):
        return None


# --------------------------------------------------------------------------- #
# Lettura tabellare con riconoscimento intestazioni
# --------------------------------------------------------------------------- #
def _tokens(s) -> list[str]:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", s)


_LAT_W = {"lat", "latitude", "latitudine", "latitud"}
_LON_W = {"lon", "lng", "long", "longitude", "longitudine", "longitud"}
_COORD_W = {"coord", "coords", "coordinate", "coordinates", "coordinata", "posizione",
            "position", "location", "gps", "geo", "latlon", "latlng", "luogo", "point", "punto"}
_DT_W = {"timestamp", "datetime", "dataora", "datatime", "istante", "fix", "when", "datahora"}
_DATE_W = {"data", "date", "giorno", "day"}
_TIME_W = {"ora", "orario", "time", "hour", "ore", "hh", "utc"}


def classify_header(cell) -> str | None:
    t = set(_tokens(cell))
    if not t:
        return None
    has_lat = bool(t & _LAT_W) or any(x.startswith("latit") for x in t)
    has_lon = bool(t & _LON_W) or any(x.startswith("longit") for x in t)
    # "x"/"y" valgono solo se sono l'intera intestazione
    if t in ({"x"}, {"y"}):
        return "lon" if t == {"x"} else "lat"
    if has_lat and has_lon:
        return "coord"
    if has_lat:
        return "lat"
    if has_lon:
        return "lon"
    if t & _COORD_W or any(x.startswith("coord") for x in t):
        return "coord"
    if t & _DT_W or ((t & _DATE_W) and (t & _TIME_W)):
        return "datetime"
    if t & _DATE_W:
        return "date"
    if t & _TIME_W:
        return "time"
    return None


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, float):
        return repr(v)
    return str(v).replace("\n", " ")


def points_from_table(rows) -> list[TrackPoint] | None:
    """Righe di una tabella -> punti. None se non trova intestazioni utili."""
    rows = [r for r in rows if r and any(c not in (None, "") for c in r)]
    header_idx, cols = None, {}
    for i, row in enumerate(rows[:20]):
        roles = {}
        for j, c in enumerate(row):
            if c is None or isinstance(c, (int, float, datetime)):
                continue
            r = classify_header(c)
            if r and r not in roles:
                roles[r] = j
        if ("lat" in roles and "lon" in roles) or "coord" in roles:
            header_idx, cols = i, roles
            break
    if header_idx is None:
        return None

    pts = []
    for row in rows[header_idx + 1:]:
        def cell(role):
            j = cols.get(role)
            return row[j] if j is not None and j < len(row) else None

        coord = None
        if "lat" in cols and "lon" in cols:
            la, lo = to_float(cell("lat")), to_float(cell("lon"))
            if _valid(la, lo):
                coord = (la, lo)
        if coord is None and "coord" in cols and cell("coord") is not None:
            coord = find_coords(_cell_text(cell("coord")), loose=True)
        if coord is None:
            continue

        t = None
        if "datetime" in cols:
            k, v = parse_cell_datetime(cell("datetime"), allow_serial=True)
            if k == "datetime":
                t = v
            elif k == "date":
                t = datetime.combine(v, dtime())
        if t is None and "date" in cols:
            kd, vd = parse_cell_datetime(cell("date"), allow_serial=True)
            if kd == "datetime":
                t = vd
                vd = vd.date()
            if kd in ("date", "datetime"):
                tv = None
                if "time" in cols:
                    kt, vt = parse_cell_datetime(cell("time"), allow_serial=True)
                    if kt == "time":
                        tv = vt
                    elif kt == "datetime":
                        tv = vt.time()
                if tv is not None:
                    t = datetime.combine(vd, tv)
                elif t is None:
                    t = datetime.combine(vd, dtime())
        if t is None and "time" in cols:
            kt, vt = parse_cell_datetime(cell("time"), allow_serial=False)
            if kt == "datetime":
                t = vt
        line = " | ".join(_cell_text(c) for c in row)
        if t is None:
            k, v, _ = find_datetime(line)
            if k == "datetime":
                t = v
        pts.append(TrackPoint(coord[0], coord[1], t, line[:240]))
    return pts


def _table_candidates(rows, label):
    cands = []
    p = points_from_table(rows)
    if p:
        cands.append((f"{label} (colonne)", p))
    lines = [" | ".join(_cell_text(c) for c in r) for r in rows if r]
    p = points_from_lines(lines)
    if p:
        cands.append((f"{label} (righe)", p))
    return cands


# --------------------------------------------------------------------------- #
# Lettori per formato
# --------------------------------------------------------------------------- #
def _read_text_file(path) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            txt = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            return txt
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "ignore")


def _read_delimited(text, label):
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    cands = []
    p = points_from_table(rows)
    if p:
        cands.append((f"{label} (colonne)", p))
    p = points_from_lines(text.splitlines())
    if p:
        cands.append((f"{label} (righe)", p))
    return cands


def read_pdf(path, progress=None):
    import pdfplumber
    rows, lines, warnings = [], [], []
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            try:
                for tb in page.extract_tables() or []:
                    rows.extend(tb)
            except Exception:
                pass
            lines.extend((page.extract_text() or "").splitlines())
            if progress:
                progress(i + 1, n)
    if not lines and not rows:
        warnings.append("Il PDF non contiene testo selezionabile (probabile scansione): serve prima un OCR.")
    cands = []
    if rows:
        p = points_from_table(rows)
        if p:
            cands.append(("PDF, tabella (colonne)", p))
    p = points_from_lines(lines)
    if p:
        cands.append(("PDF, testo (righe)", p))
    return cands, warnings


def read_xlsx(path, progress=None):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    allpts, methods = [], []
    sheets = wb.worksheets
    for i, ws in enumerate(sheets):
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        best = _best(_table_candidates(rows, f"Excel, foglio «{ws.title}»"))
        if best:
            methods.append(best[0])
            allpts.extend(best[1])
        if progress:
            progress(i + 1, len(sheets))
    wb.close()
    return ([(" + ".join(methods), allpts)] if allpts else []), []


def read_xls(path, progress=None):
    try:
        import xlrd
    except ImportError:
        raise ParseError("Per i vecchi file .xls serve il modulo xlrd: salva il file come .xlsx e riprova.")
    book = xlrd.open_workbook(path)
    allpts = []
    for sh in book.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                else:
                    row.append(cell.value)
            rows.append(row)
        best = _best(_table_candidates(rows, "Excel"))
        if best:
            allpts.extend(best[1])
    return ([("Excel .xls", allpts)] if allpts else []), []


def read_docx(path, progress=None):
    import docx
    d = docx.Document(path)
    cands = []
    rows = []
    for tb in d.tables:
        for r in tb.rows:
            rows.append([c.text for c in r.cells])
    if rows:
        cands += _table_candidates(rows, "Word, tabella")
    lines = [p.text for p in d.paragraphs]
    p = points_from_lines(lines)
    if p:
        cands.append(("Word, testo (righe)", p))
    return cands, []


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_gpx(path, progress=None):
    root = ET.parse(path).getroot()
    pts = []
    for el in root.iter():
        if _local(el.tag) in ("trkpt", "rtept", "wpt"):
            try:
                lat, lon = float(el.get("lat")), float(el.get("lon"))
            except (TypeError, ValueError):
                continue
            t, name = None, ""
            for ch in el:
                ln = _local(ch.tag)
                if ln == "time" and ch.text:
                    t = parse_cell_datetime(ch.text.strip())[1]
                elif ln == "name" and ch.text:
                    name = ch.text.strip()
            if t is not None and not isinstance(t, datetime):
                t = None
            pts.append(TrackPoint(lat, lon, t, name))
    return [("GPX", pts)], []


def _kml_root(path):
    if path.lower().endswith(".kmz"):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
            if not name:
                raise ParseError("Il file KMZ non contiene un KML.")
            return ET.fromstring(z.read(name))
    return ET.parse(path).getroot()


def read_kml(path, progress=None):
    root = _kml_root(path)
    pts = []

    def dt_of(s):
        k, v = parse_cell_datetime((s or "").strip())
        return v if k == "datetime" else (datetime.combine(v, dtime()) if k == "date" else None)

    for pm in root.iter():
        ln = _local(pm.tag)
        if ln == "Track":   # gx:Track
            whens = [dt_of(e.text) for e in pm if _local(e.tag) == "when"]
            coords = [e.text.split() for e in pm if _local(e.tag) == "coord" and e.text]
            for i, c in enumerate(coords):
                try:
                    pts.append(TrackPoint(float(c[1]), float(c[0]), whens[i] if i < len(whens) else None))
                except (ValueError, IndexError):
                    pass
        elif ln == "Placemark":
            name, when, coords_txt, is_point = "", None, None, False
            for e in pm.iter():
                l2 = _local(e.tag)
                if l2 == "name" and e.text and not name:
                    name = e.text.strip()
                elif l2 in ("when", "begin") and e.text and when is None:
                    when = dt_of(e.text)
                elif l2 == "Track":
                    coords_txt = None
                    break
                elif l2 in ("Point", "LineString", "LinearRing") and coords_txt is None:
                    is_point = l2 == "Point"
                    c = next((x for x in e.iter() if _local(x.tag) == "coordinates"), None)
                    if c is not None and c.text:
                        coords_txt = c.text
            if coords_txt:
                if when is None:
                    k, v, _ = find_datetime(name)
                    when = v if k == "datetime" else None
                for tup in coords_txt.split():
                    p = tup.split(",")
                    try:
                        pts.append(TrackPoint(float(p[1]), float(p[0]), when if is_point else None, name))
                    except (ValueError, IndexError):
                        pass
    return [("KML", pts)], []


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _json_lists(obj, depth=0):
    """Trova tutte le liste di oggetti nel JSON."""
    if depth > 6:
        return
    if isinstance(obj, list):
        if obj and sum(isinstance(x, dict) for x in obj) >= max(1, len(obj) // 2):
            yield obj
        for x in obj[:50] if obj and not isinstance(obj[0], dict) else obj[:1]:
            yield from _json_lists(x, depth + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _json_lists(v, depth + 1)


def read_json(path, progress=None):
    data = json.loads(_read_text_file(path))
    cands = []
    # GeoJSON
    feats = None
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        feats = data.get("features", [])
    elif isinstance(data, dict) and data.get("type") == "Feature":
        feats = [data]
    if feats is not None:
        pts = []
        for f in feats:
            g = f.get("geometry") or {}
            props = f.get("properties") or {}
            t = None
            for k, v in props.items():
                if classify_header(k) in ("datetime", "date", "time"):
                    kk, vv = parse_cell_datetime(v)
                    if kk == "datetime":
                        t = vv
                        break
            gt, c = g.get("type"), g.get("coordinates")
            if gt == "Point" and c:
                pts.append(TrackPoint(float(c[1]), float(c[0]), t, str(props.get("name", ""))))
            elif gt in ("LineString", "MultiPoint") and c:
                times = props.get("coordTimes") or props.get("times") or []
                for i, cc in enumerate(c):
                    ti = parse_cell_datetime(times[i])[1] if i < len(times) else None
                    pts.append(TrackPoint(float(cc[1]), float(cc[0]), ti if isinstance(ti, datetime) else None))
        cands.append(("GeoJSON", pts))
    # Google Takeout (Records.json / Timeline)
    for lst in _json_lists(data):
        sample = lst[0] if lst else {}
        if "latitudeE7" in sample:
            pts = []
            for r in lst:
                try:
                    lat, lon = r["latitudeE7"] / 1e7, r["longitudeE7"] / 1e7
                except (KeyError, TypeError):
                    continue
                ts = r.get("timestamp") or r.get("timestampMs")
                pts.append(TrackPoint(lat, lon, parse_cell_datetime(ts)[1] if ts else None))
            cands.append(("Google Takeout", pts))
        else:
            flat = [_flatten(x) for x in lst if isinstance(x, dict)]
            keys = []
            for f in flat:
                for k in f:
                    if k not in keys:
                        keys.append(k)
            rows = [keys] + [[f.get(k) for k in keys] for f in flat]
            p = points_from_table(rows)
            if p:
                cands.append(("JSON (campi)", p))
    if not cands:
        text = json.dumps(data, ensure_ascii=False, indent=0, default=str)
        cands.append(("JSON (testo)", points_from_lines(text.splitlines())))
    return cands, []


def read_html(path, progress=None):
    txt = _read_text_file(path)
    txt = re.sub(r"(?is)<(script|style).*?</\1>", " ", txt)
    txt = re.sub(r"(?i)<\s*(br|/p|/tr|/div|/li|/h\d)[^>]*>", "\n", txt)
    txt = re.sub(r"(?i)<\s*/t[dh]\s*>", " | ", txt)
    txt = html_mod.unescape(re.sub(r"<[^>]+>", " ", txt))
    return [("HTML (righe)", points_from_lines(txt.splitlines()))], []


def read_text(path, progress=None):
    txt = _read_text_file(path)
    return _read_delimited(txt, "Testo/CSV"), []


_READERS = {
    ".pdf": read_pdf, ".xlsx": read_xlsx, ".xlsm": read_xlsx, ".xls": read_xls,
    ".docx": read_docx, ".gpx": read_gpx, ".kml": read_kml, ".kmz": read_kml,
    ".geojson": read_json, ".json": read_json, ".html": read_html, ".htm": read_html,
}


def _best(cands):
    cands = [c for c in cands if c and c[1]]
    if not cands:
        return None
    return max(cands, key=lambda c: (sum(1 for p in c[1] if p.time), len(c[1])))


# --------------------------------------------------------------------------- #
# Ingresso principale
# --------------------------------------------------------------------------- #
def load_track(path: str, progress=None) -> ParseResult:
    if not os.path.isfile(path):
        raise ParseError(f"File non trovato: {path}")
    ext = os.path.splitext(path)[1].lower()
    reader = _READERS.get(ext, read_text)
    try:
        cands, warnings = reader(path, progress)
    except ParseError:
        raise
    except Exception as e:  # file danneggiato o formato inatteso
        raise ParseError(f"Impossibile leggere il file ({type(e).__name__}): {e}") from e

    best = _best(cands)
    if not best:
        msg = "Nessuna coordinata trovata nel file."
        if warnings:
            msg += "\n" + "\n".join(warnings)
        raise ParseError(msg)
    method, pts = best
    return _finish(pts, warnings, path, method)


def _finish(pts, warnings, path, method) -> ParseResult:
    warnings = list(warnings)
    pts = [p for p in pts if _valid(p.lat, p.lon)]
    timed = [p for p in pts if p.time is not None]
    if timed and len(timed) >= len(pts) * 0.5:
        if len(timed) < len(pts):
            warnings.append(f"{len(pts) - len(timed)} punti senza data/ora sono stati scartati.")
        pts = sorted(timed, key=lambda p: p.time)
    elif timed:
        warnings.append("Solo alcuni punti hanno data/ora: mantenuto l'ordine del file.")
    else:
        warnings.append("Nessuna data/ora trovata: i punti seguono l'ordine del file.")
    seen, out = set(), []
    for p in pts:
        key = (round(p.lat, 7), round(p.lon, 7), p.time)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    if len(out) < len(pts):
        warnings.append(f"{len(pts) - len(out)} punti duplicati rimossi.")
    if not out:
        raise ParseError("Nessuna coordinata valida trovata nel file.")
    return ParseResult(out, path, method, warnings)
