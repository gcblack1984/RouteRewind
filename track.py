"""Calcoli sul percorso: distanze, velocità, statistiche."""
from __future__ import annotations

import math
from dataclasses import dataclass


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class TrackStats:
    count: int
    start: object
    end: object
    duration_s: float | None
    distance_m: float
    avg_kmh: float | None
    max_kmh: float | None
    seg_dist: list        # distanza dal punto precedente (m)
    seg_kmh: list         # velocità dal punto precedente (km/h) o None
    cum_dist: list        # distanza progressiva (m)


def compute_stats(points) -> TrackStats:
    seg_d, seg_v, cum = [0.0], [None], [0.0]
    for a, b in zip(points, points[1:]):
        d = haversine_m(a.lat, a.lon, b.lat, b.lon)
        v = None
        if a.time and b.time:
            dt = (b.time - a.time).total_seconds()
            if dt > 0:
                v = d / dt * 3.6
        seg_d.append(d)
        seg_v.append(v)
        cum.append(cum[-1] + d)
    start = points[0].time if points else None
    end = points[-1].time if points else None
    dur = (end - start).total_seconds() if start and end else None
    dist = cum[-1] if cum else 0.0
    avg = dist / dur * 3.6 if dur else None
    speeds = [v for v in seg_v if v is not None]
    return TrackStats(len(points), start, end, dur, dist, avg,
                      max(speeds) if speeds else None, seg_d, seg_v, cum)


def fmt_duration(sec) -> str:
    if sec is None:
        return "—"
    sec = int(round(sec))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    out = f"{h:02d}:{m:02d}:{s:02d}"
    return f"{d} g {out}" if d else out


def fmt_dist(m) -> str:
    return f"{m / 1000:.2f} km" if m >= 1000 else f"{m:.0f} m"


def fmt_dt(dt) -> str:
    return dt.strftime("%d/%m/%Y %H:%M:%S") if dt else "—"
