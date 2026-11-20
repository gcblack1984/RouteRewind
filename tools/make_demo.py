"""
Crea i file dimostrativi in examples/: una gita fittizia in Puglia
(Bari, Polignano a Mare, Monopoli, Castellana Grotte, Alberobello, Locorotondo,
Cisternino, Ostuni) in PDF ed Excel. Servono per provare l'app e fare gli screenshot.
"""
import math
import os
import random
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "examples")

# (lat, lon, nome, sosta in minuti)
WAYPOINTS = [
    (41.1177, 16.8697, "Bari, partenza", 0),
    (41.1050, 16.9180, "", 0),
    (41.0790, 16.9890, "", 0),
    (41.0620, 17.0600, "", 0),
    (41.0585, 17.0905, "Mola di Bari", 0),
    (41.0290, 17.1450, "", 0),
    (40.9960, 17.2190, "Polignano a Mare", 45),
    (40.9720, 17.2640, "", 0),
    (40.9505, 17.2985, "Monopoli", 30),
    (40.9150, 17.2420, "", 0),
    (40.8870, 17.1680, "Castellana Grotte", 60),
    (40.8400, 17.2000, "", 0),
    (40.7835, 17.2365, "Alberobello", 90),
    (40.7700, 17.2850, "", 0),
    (40.7550, 17.3265, "Locorotondo", 30),
    (40.7430, 17.4250, "Cisternino", 30),
    (40.7380, 17.5000, "", 0),
    (40.7290, 17.5775, "Ostuni, arrivo", 0),
]
START = datetime(2026, 11, 14, 8, 30, 0)
SPEED_KMH = 48          # media su strade extraurbane con traffico
SAMPLE_S = 90           # un punto ogni 90 secondi in movimento
STOP_SAMPLE_MIN = 10    # un punto ogni 10 minuti durante le soste


def km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def build_points():
    random.seed(7)
    pts, t = [], START
    for i, (lat, lon, name, stop) in enumerate(WAYPOINTS):
        if i > 0:
            a, b = WAYPOINTS[i - 1], WAYPOINTS[i]
            seconds = km(a, b) / SPEED_KMH * 3600
            n = max(1, int(seconds // SAMPLE_S))
            for k in range(1, n):
                f = k / n
                jit = 0.0006
                pts.append((a[0] + (b[0] - a[0]) * f + random.uniform(-jit, jit),
                            a[1] + (b[1] - a[1]) * f + random.uniform(-jit, jit),
                            t + timedelta(seconds=seconds * f), "in movimento"))
            t += timedelta(seconds=seconds)
        pts.append((lat, lon, t, name or "in movimento"))
        if stop:
            for k in range(STOP_SAMPLE_MIN, stop + 1, STOP_SAMPLE_MIN):
                pts.append((lat + random.uniform(-0.0002, 0.0002), lon + random.uniform(-0.0002, 0.0002),
                            t + timedelta(minutes=k), f"sosta {name}"))
            t += timedelta(minutes=stop)
    return [(la, lo, (t + timedelta(microseconds=500000)).replace(microsecond=0), n) for la, lo, t, n in pts]


def it(v, d=6):
    return f"{v:.{d}f}".replace(".", ",")


def make_pdf(pts):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    doc = SimpleDocTemplate(os.path.join(OUT, "Esempio_gita_Puglia.pdf"), pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Esempio RouteRewind - gita in Puglia", author="RouteRewind")
    rows = [["N.", "Data", "Ora", "Latitudine", "Longitudine", "Note"]]
    for i, (la, lo, t, note) in enumerate(pts, 1):
        rows.append([str(i), t.strftime("%d/%m/%Y"), t.strftime("%H:%M:%S"), it(la), it(lo), note])
    tb = Table(rows, repeatRows=1, colWidths=[12 * mm, 24 * mm, 20 * mm, 28 * mm, 28 * mm, 66 * mm])
    tb.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f2040")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f7")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
    ]))
    doc.build([
        Paragraph("Registro posizioni – gita in Puglia (dati di esempio)", ss["Title"]),
        Paragraph("Percorso fittizio creato per provare RouteRewind: Bari → Polignano a Mare → Monopoli → "
                  "Castellana Grotte → Alberobello → Locorotondo → Cisternino → Ostuni. "
                  f"{len(pts)} posizioni del {START:%d/%m/%Y}.", ss["Normal"]),
        Spacer(1, 6 * mm), tb])


def make_xlsx(pts):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Posizioni"
    ws.append(["Data/Ora", "Latitudine", "Longitudine", "Note"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0F2040")
    for la, lo, t, note in pts:
        ws.append([t, round(la, 6), round(lo, 6), note])
    for col, w in zip("ABCD", (20, 13, 13, 32)):
        ws.column_dimensions[col].width = w
    for c in ws["A"][1:]:
        c.number_format = "dd/mm/yyyy hh:mm:ss"
    wb.save(os.path.join(OUT, "Esempio_gita_Puglia.xlsx"))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    p = build_points()
    make_pdf(p)
    make_xlsx(p)
    print(len(p), "punti, da", p[0][2], "a", p[-1][2])
