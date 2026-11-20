"""Generazione del report HTML del percorso, con mappa interattiva."""
from __future__ import annotations

import html
import json
import os
from datetime import datetime

from app_info import APP_NAME, APP_VERSION, AUTHOR
from track import compute_stats, fmt_dist, fmt_dt, fmt_duration

LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"


def build_report_html(result, start: int = 0, end: int | None = None, title: str | None = None,
                      carto_key: str = "") -> str:
    pts = result.points[start:(end + 1) if end is not None else None]
    st = compute_stats(pts)
    src = os.path.basename(result.source)
    title = title or f"Report percorso — {src}"
    data = [{"lat": p.lat, "lon": p.lon, "t": fmt_dt(p.time), "n": start + i + 1}
            for i, p in enumerate(pts)]

    rows = []
    for i, p in enumerate(pts):
        v = st.seg_kmh[i]
        rows.append(
            "<tr>"
            f"<td>{start + i + 1}</td><td>{fmt_dt(p.time)}</td>"
            f"<td>{p.lat:.6f}</td><td>{p.lon:.6f}</td>"
            f"<td>{fmt_dist(st.seg_dist[i]) if i else '—'}</td>"
            f"<td>{fmt_dist(st.cum_dist[i])}</td>"
            f"<td>{f'{v:.1f}' if v is not None else '—'}</td>"
            f"<td><a href='https://www.google.com/maps?q={p.lat:.6f},{p.lon:.6f}' target='_blank'>apri</a></td>"
            "</tr>"
        )

    cards = [
        ("Punti", str(st.count)),
        ("Inizio", fmt_dt(st.start)),
        ("Fine", fmt_dt(st.end)),
        ("Durata", fmt_duration(st.duration_s)),
        ("Distanza", fmt_dist(st.distance_m)),
        ("Velocità media", f"{st.avg_kmh:.1f} km/h" if st.avg_kmh else "—"),
        ("Velocità max tra punti", f"{st.max_kmh:.1f} km/h" if st.max_kmh else "—"),
    ]
    cards_html = "".join(f"<div class='card'><span>{k}</span><b>{html.escape(v)}</b></div>" for k, v in cards)
    warn_html = "".join(f"<li>{html.escape(w)}</li>" for w in result.warnings)
    range_note = ""
    if start > 0 or (end is not None and end < len(result.points) - 1):
        range_note = f"<p class='note'>Intervallo: punti {start + 1}–{start + len(pts)} di {len(result.points)}.</p>"

    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="{APP_NAME} {APP_VERSION} — {AUTHOR}">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{LEAFLET_CSS}">
<style>
 :root {{ --ink:#0f172a; --mut:#64748b; --line:#e2e8f0; --acc:#2563eb; }}
 * {{ box-sizing:border-box; }}
 body {{ font-family:"Segoe UI",system-ui,sans-serif; color:var(--ink); margin:0; background:#f8fafc; }}
 header {{ background:#0f172a; color:#fff; padding:18px 28px; }}
 header h1 {{ margin:0; font-size:22px; font-weight:600; }}
 header p {{ margin:4px 0 0; color:#cbd5e1; font-size:13px; }}
 main {{ padding:20px 28px 40px; max-width:1200px; margin:auto; }}
 .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; margin-bottom:16px; }}
 .card {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:10px 12px; }}
 .card span {{ display:block; font-size:12px; color:var(--mut); }}
 .card b {{ font-size:15px; font-weight:600; }}
 #map {{ height:520px; border-radius:8px; border:1px solid var(--line); }}
 h2 {{ font-size:16px; margin:24px 0 8px; }}
 table {{ width:100%; border-collapse:collapse; background:#fff; font-size:12.5px; }}
 th, td {{ border-bottom:1px solid var(--line); padding:5px 8px; text-align:left; white-space:nowrap; }}
 th {{ background:#f1f5f9; position:sticky; top:0; }}
 tr:hover td {{ background:#eff6ff; }}
 .note, .warn {{ font-size:13px; color:var(--mut); }}
 footer {{ text-align:center; font-size:12px; color:var(--mut); padding:16px; }}
 @media print {{
   body {{ background:#fff; }} header {{ background:#fff; color:#000; border-bottom:2px solid #000; }}
   header p {{ color:#333; }} #map {{ height:12cm; page-break-inside:avoid; }}
   a {{ color:inherit; text-decoration:none; }} th {{ position:static; }}
 }}
</style></head>
<body>
<header>
 <h1>{html.escape(title)}</h1>
 <p>File: {html.escape(src)} · Metodo di lettura: {html.escape(result.method)} ·
 Generato il {datetime.now().strftime('%d/%m/%Y alle %H:%M')} con {APP_NAME} {APP_VERSION} di {AUTHOR}</p>
</header>
<main>
 {range_note}
 <div class="cards">{cards_html}</div>
 <div id="map"></div>
 {f"<h2>Avvisi</h2><ul class='warn'>{warn_html}</ul>" if warn_html else ""}
 <h2>Cronologia dei punti</h2>
 <table><thead><tr><th>#</th><th>Data e ora</th><th>Latitudine</th><th>Longitudine</th>
 <th>Dal precedente</th><th>Progressiva</th><th>km/h</th><th>Mappa</th></tr></thead>
 <tbody>{''.join(rows)}</tbody></table>
</main>
<footer>{APP_NAME} {APP_VERSION} — {AUTHOR} · Mappe © OpenStreetMap contributors, © CARTO, Esri</footer>
<script src="{LEAFLET_JS}"></script>
<script>
window.reportReady = false;
const P = {json.dumps(data)};
(function () {{
  if (typeof L === 'undefined') {{
    document.getElementById('map').innerHTML = '<p style="padding:20px">Mappa non disponibile: serve una connessione a Internet.</p>';
    window.reportReady = true; return;
  }}
  const map = L.map('map', {{ preferCanvas: true }});
  const KEY = {json.dumps(carto_key or "")};
  const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
    {{ maxZoom: 19, attribution: 'Tiles © Esri' }});
  let base = sat;
  if (KEY) {{
    base = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png?key=' + encodeURIComponent(KEY),
      {{ maxZoom: 20, attribution: '© OpenStreetMap contributors © CARTO' }});
    L.control.layers({{ 'Mappa': base, 'Satellite': sat }}).addTo(map);
  }}
  base.addTo(map);
  base.on('load', () => window.reportReady = true);
  setTimeout(() => window.reportReady = true, 8000);
  if (!P.length) return;
  const ll = P.map(p => [p.lat, p.lon]);
  const n = ll.length;
  function col(i) {{ const h = 220 - 220 * (n > 1 ? i / (n - 1) : 0); return `hsl(${{h}},80%,45%)`; }}
  for (let i = 1; i < n; i++) L.polyline([ll[i - 1], ll[i]], {{ color: col(i), weight: 4, opacity: .9 }}).addTo(map);
  P.forEach((p, i) => L.circleMarker(ll[i], {{ radius: 4, color: '#fff', weight: 1, fillColor: col(i), fillOpacity: 1 }})
    .bindPopup(`<b>#${{p.n}}</b><br>${{p.t}}<br>${{p.lat.toFixed(6)}}, ${{p.lon.toFixed(6)}}`).addTo(map));
  const pin = c => L.divIcon({{ className: '', iconSize: [26, 26], iconAnchor: [13, 13],
    html: `<div style="width:22px;height:22px;border-radius:50%;background:${{c}};border:3px solid #fff;box-shadow:0 1px 4px #0008"></div>` }});
  L.marker(ll[0], {{ icon: pin('#16a34a') }}).bindTooltip('Partenza: ' + P[0].t).addTo(map);
  L.marker(ll[n - 1], {{ icon: pin('#dc2626') }}).bindTooltip('Arrivo: ' + P[n - 1].t).addTo(map);
  map.fitBounds(L.latLngBounds(ll).pad(0.1));
}})();
</script>
</body></html>"""


def save_report(result, path: str, start: int = 0, end: int | None = None, carto_key: str = "") -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_report_html(result, start, end, carto_key=carto_key))
    return path
