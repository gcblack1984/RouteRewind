"""Genera file di esempio in più formati con lo stesso percorso (Latiano -> Brindisi)."""
import json
import os
import sys
from datetime import datetime, timedelta

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
os.makedirs(OUT, exist_ok=True)

START = datetime(2026, 11, 18, 8, 0, 0)
A, B = (40.5545, 17.7187), (40.6327, 17.9418)
N = 25
PTS = [(A[0] + (B[0] - A[0]) * i / (N - 1) + (0.002 if i % 3 == 0 else 0),
        A[1] + (B[1] - A[1]) * i / (N - 1),
        START + timedelta(minutes=2 * i)) for i in range(N)]
SHUF = PTS[5:] + PTS[:5]   # disordinati: l'app deve riordinare per data


def dms(v, pos, neg):
    h = pos if v >= 0 else neg
    v = abs(v); d = int(v); m = int((v - d) * 60); s = (v - d - m / 60) * 3600
    return f"{d}°{m}'{s:.2f}\"{h}"


def make_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    rows = [["N.", "Data", "Ora", "Latitudine", "Longitudine", "Note"]]
    for i, (la, lo, t) in enumerate(SHUF):
        rows.append([str(i + 1), t.strftime("%d/%m/%Y"), t.strftime("%H:%M:%S"),
                     f"{la:.6f}".replace(".", ","), f"{lo:.6f}".replace(".", ","), "fix GPS"])
    doc = SimpleDocTemplate(os.path.join(OUT, "tabulato.pdf"), pagesize=A4)
    doc.build([Paragraph("Tabulato posizioni", getSampleStyleSheet()["Title"]), Table(rows)])


def make_pdf_text():
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(os.path.join(OUT, "testo_libero.pdf"))
    y = 800
    c.drawString(40, y, "Rapporto posizioni rilevate"); y -= 20
    for la, lo, t in SHUF:
        c.drawString(40, y, f"Il {t:%d/%m/%Y} alle ore {t:%H:%M} il dispositivo era in {dms(la,'N','S')} {dms(lo,'E','W')}")
        y -= 16
        if y < 40:
            c.showPage(); y = 800
    c.save()


def make_csv():
    with open(os.path.join(OUT, "posizioni_it.csv"), "w", encoding="cp1252") as f:
        f.write("Data;Ora;Latitudine;Longitudine;Velocità\n")
        for la, lo, t in SHUF:
            f.write(f"{t:%d/%m/%Y};{t:%H:%M:%S};{la:.6f};{lo:.6f};50\n".replace(".", ","))
    with open(os.path.join(OUT, "positions_en.csv"), "w") as f:
        f.write("timestamp,position\n")
        for la, lo, t in SHUF:
            f.write(f"{t.isoformat()}Z,\"{la:.5f}, {lo:.5f}\"\n")


def make_xlsx():
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Celle"
    ws.append(["Report celle telefoniche"]); ws.append([])
    ws.append(["Data/Ora inizio", "Lat", "Long", "Indirizzo"])
    for la, lo, t in SHUF:
        ws.append([t, la, lo, "Via Roma"])
    wb.save(os.path.join(OUT, "celle.xlsx"))


def make_docx():
    import docx
    d = docx.Document(); d.add_heading("Relazione", 1)
    tb = d.add_table(rows=1, cols=3)
    tb.rows[0].cells[0].text, tb.rows[0].cells[1].text, tb.rows[0].cells[2].text = "Data e ora", "Coordinate", "Fonte"
    for la, lo, t in SHUF:
        r = tb.add_row().cells
        r[0].text, r[1].text, r[2].text = f"{t:%d/%m/%Y %H:%M}", f"{la:.6f}, {lo:.6f}", "GPS"
    d.save(os.path.join(OUT, "relazione.docx"))


def make_gpx_kml_json_nmea():
    with open(os.path.join(OUT, "traccia.gpx"), "w") as f:
        f.write('<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>')
        for la, lo, t in PTS:
            f.write(f'<trkpt lat="{la}" lon="{lo}"><time>{t.isoformat()}Z</time></trkpt>')
        f.write("</trkseg></trk></gpx>")
    with open(os.path.join(OUT, "traccia.kml"), "w") as f:
        f.write('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><Placemark><gx:Track>')
        f.write("".join(f"<when>{t.isoformat()}Z</when>" for _, _, t in PTS))
        f.write("".join(f"<gx:coord>{lo} {la} 0</gx:coord>" for la, lo, _ in PTS))
        f.write("</gx:Track></Placemark></Document></kml>")
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lo, la]},
         "properties": {"time": t.isoformat()}} for la, lo, t in SHUF]}
    json.dump(fc, open(os.path.join(OUT, "punti.geojson"), "w"))
    json.dump({"locations": [{"latitudeE7": int(la * 1e7), "longitudeE7": int(lo * 1e7),
                              "timestamp": t.isoformat() + "Z"} for la, lo, t in SHUF]},
              open(os.path.join(OUT, "Records.json"), "w"))
    with open(os.path.join(OUT, "log.nmea"), "w") as f:
        for la, lo, t in PTS:
            dla = f"{int(la):02d}{(la - int(la)) * 60:07.4f}"; dlo = f"{int(lo):03d}{(lo - int(lo)) * 60:07.4f}"
            f.write(f"$GPRMC,{t:%H%M%S}.00,A,{dla},N,{dlo},E,0.0,0.0,{t:%d%m%y},,,A*00\n")


if __name__ == "__main__":
    make_pdf(); make_pdf_text(); make_csv(); make_xlsx(); make_docx(); make_gpx_kml_json_nmea()
    print("Campioni in", OUT)
