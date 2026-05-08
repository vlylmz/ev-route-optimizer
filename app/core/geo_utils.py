"""Cografi yardimcilar - haversine, bearing, route point cikartma.

Once 7+ dosyada duplike _haversine_km tanimi vardi; tek noktada toplandi.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin, sqrt
from typing import Any, Dict, Iterable, List, Tuple


EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Iki koordinat arasi great-circle mesafesi (km)."""
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)

    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(a), sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (compass derecesi: 0=kuzey, 90=dogu)."""
    lat1_r = radians(lat1)
    lat2_r = radians(lat2)
    d_lon = radians(lon2 - lon1)

    y = sin(d_lon) * cos(lat2_r)
    x = cos(lat1_r) * sin(lat2_r) - sin(lat1_r) * cos(lat2_r) * cos(d_lon)
    return (degrees(atan2(y, x)) + 360.0) % 360.0


@dataclass
class RoutePoint:
    lat: float
    lon: float
    cumulative_distance_km: float


def parse_geometry(raw_points: Iterable[Any]) -> List[Tuple[float, float]]:
    """Heterojen geometry input'unu (lat, lon) listesine cevir.

    Kabul edilen format:
    - {"lat": ..., "lon": ...} dict (lat/lng/longitude/latitude alias'lari)
    - [lat, lon] tuple/list
    """
    parsed: List[Tuple[float, float]] = []
    for item in raw_points:
        if isinstance(item, dict):
            lat = item.get("lat")
            if lat is None:
                lat = item.get("latitude")
            lon = item.get("lon")
            if lon is None:
                lon = item.get("lng")
            if lon is None:
                lon = item.get("longitude")
            try:
                parsed.append((float(lat), float(lon)))
            except (TypeError, ValueError):
                continue
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                parsed.append((float(item[0]), float(item[1])))
            except (TypeError, ValueError):
                continue
    return parsed


def build_route_points(raw_points: Iterable[Any]) -> List[RoutePoint]:
    """Geometry'den kumulatif mesafeli RoutePoint listesi olustur."""
    coords = parse_geometry(raw_points)
    points: List[RoutePoint] = []
    cumulative = 0.0
    prev: Tuple[float, float] | None = None

    for lat, lon in coords:
        if prev is not None:
            cumulative += haversine_km(prev[0], prev[1], lat, lon)
        points.append(RoutePoint(lat=lat, lon=lon, cumulative_distance_km=cumulative))
        prev = (lat, lon)

    return points
