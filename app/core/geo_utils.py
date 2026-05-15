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


class RouteSpatialIndex:
    """Rota route_points'i uzerinde O(log n) en yakin nokta sorgusu.

    Eskiden her istasyon icin tum route_points'i taraniyordu (O(n*m));
    KDTree (scipy) ile O(n*log m). Buyuk rotalar icin onemli kazanim.
    """

    def __init__(self, route_points: List[RoutePoint]) -> None:
        self.route_points = route_points
        self._tree = None
        if not route_points:
            return
        try:
            from scipy.spatial import cKDTree
            import numpy as np

            lats = np.radians([p.lat for p in route_points])
            lons = np.radians([p.lon for p in route_points])
            coords = np.column_stack([
                np.cos(lats) * np.cos(lons),
                np.cos(lats) * np.sin(lons),
                np.sin(lats),
            ])
            self._tree = cKDTree(coords)
        except ImportError:
            self._tree = None

    def nearest(self, lat: float, lon: float) -> Tuple[RoutePoint, float]:
        """En yakin route_point + (km cinsinden) gercek haversine mesafesi."""
        if not self.route_points:
            raise ValueError("Index bos.")

        if self._tree is not None:
            lat_r = radians(lat)
            lon_r = radians(lon)
            query = [
                cos(lat_r) * cos(lon_r),
                cos(lat_r) * sin(lon_r),
                sin(lat_r),
            ]
            _, idx = self._tree.query(query, k=1)
            nearest_point = self.route_points[int(idx)]
        else:
            nearest_point = min(
                self.route_points,
                key=lambda p: haversine_km(lat, lon, p.lat, p.lon),
            )

        offset_km = haversine_km(lat, lon, nearest_point.lat, nearest_point.lon)
        return nearest_point, offset_km
