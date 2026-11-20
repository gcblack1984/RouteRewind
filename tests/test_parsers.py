import os
import sys
from datetime import datetime

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import make_samples  # noqa: E402
from parsers import find_coords, find_datetime, load_track  # noqa: E402
from report import build_report_html  # noqa: E402

S = make_samples.OUT


@pytest.fixture(scope="session", autouse=True)
def samples():
    make_samples.make_pdf(); make_samples.make_pdf_text(); make_samples.make_csv()
    make_samples.make_xlsx(); make_samples.make_docx(); make_samples.make_gpx_kml_json_nmea()


# GPX/KML/GeoJSON/Takeout/NMEA hanno orari in UTC: convertiti in ora locale
UTC_FILES = {"traccia.gpx", "traccia.kml", "Records.json", "log.nmea", "positions_en.csv"}


@pytest.mark.parametrize("name", ["tabulato.pdf", "testo_libero.pdf", "posizioni_it.csv", "positions_en.csv",
                                  "celle.xlsx", "relazione.docx", "traccia.gpx", "traccia.kml",
                                  "punti.geojson", "Records.json", "log.nmea"])
def test_formats(name):
    r = load_track(os.path.join(S, name))
    assert len(r.points) == make_samples.N, (r.method, r.warnings)
    times = [p.time for p in r.points]
    assert all(times) and times == sorted(times)
    first = r.points[0]
    assert abs(first.lat - make_samples.PTS[0][0]) < 1e-3
    assert abs(first.lon - make_samples.PTS[0][1]) < 1e-3
    if name not in UTC_FILES and name != "punti.geojson":
        assert first.time.replace(second=0) == make_samples.START


def test_coord_variants():
    assert find_coords("Lat: 40,5545 Lon: 17,7187") == (40.5545, 17.7187)
    assert find_coords("pos 40.5545 N, 17.7187 E") == (40.5545, 17.7187)
    assert find_coords("https://maps.google.com/?q=40.554512,17.718734") == (40.554512, 17.718734)
    la, lo = find_coords("40°33'16.2\"N 17°43'7.3\"W")
    assert abs(la - 40.5545) < 1e-3 and lo < 0
    assert find_coords("Tel 0831 123456") is None


def test_datetime_variants():
    assert find_datetime("2026-11-18T08:04:00")[1] == datetime(2026, 11, 18, 8, 4)
    assert find_datetime("18/11/2026 ore 08:04")[1] == datetime(2026, 11, 18, 8, 4)
    assert find_datetime("18 nov 2026 08:04:30")[1] == datetime(2026, 11, 18, 8, 4, 30)


def test_report():
    r = load_track(os.path.join(S, "celle.xlsx"))
    h = build_report_html(r, 3)
    assert "Giovanni Ciccarese" in h and "Intervallo" in h and "leaflet" in h
