"""Istasyon enrichment ortak adimlari.

Selector ve planner icinde duplike: operational filter, connector filter,
distance_along_route + offset, power_kw. Tek noktada toplandi.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.charging_stop_selector import (
    _extract_station_connectors,
)
from app.core.geo_utils import (
    RoutePoint,
    RouteSpatialIndex,
    haversine_km,
)
from app.core.utils import pick, safe_float


def resolve_station_route_metrics(
    *,
    station: Dict[str, Any],
    route_points: List[RoutePoint],
    spatial_index: Optional[RouteSpatialIndex] = None,
) -> tuple[Optional[float], float]:
    """Distance_along_route + offset_km dondur. Hesaplanmamis ise spatial
    index/lineer fallback ile en yakin route_point'i bul."""
    precomputed_along = pick(
        station,
        "distance_along_route_km",
        "distance_from_start_km",
        default=None,
    )
    precomputed_offset = pick(
        station,
        "distance_from_route_km",
        "offset_km",
        "detour_km",
        default=None,
    )
    if precomputed_along is not None:
        return safe_float(precomputed_along), safe_float(precomputed_offset, 0.0)

    if not route_points:
        return None, 0.0

    station_lat = safe_float(pick(station, "lat", "latitude"), 0.0)
    station_lon = safe_float(pick(station, "lon", "lng", "longitude"), 0.0)

    if spatial_index is not None:
        nearest, offset_km = spatial_index.nearest(station_lat, station_lon)
        return nearest.cumulative_distance_km, offset_km

    nearest = min(
        route_points,
        key=lambda p: haversine_km(station_lat, station_lon, p.lat, p.lon),
    )
    offset_km = haversine_km(station_lat, station_lon, nearest.lat, nearest.lon)
    return nearest.cumulative_distance_km, offset_km


def passes_hard_filters(
    *,
    station: Dict[str, Any],
    vehicle_connectors: Optional[set] = None,
    max_detour_km: float = 30.0,
) -> bool:
    """Operational + connector + detour HARD filter. False ise istasyon elenmeli.

    max_detour_km: rotadan >X km uzaktaki istasyon ekleme zahmetine girilmez.
    Default 30km (her yon = 60km extra surus). 200+ km uzaktaki istasyonlar
    spatial index'in 'en yakin nokta' sonucu olarak listeye sizabilir.
    """
    operational = bool(pick(station, "is_operational", "available", default=True))
    if not operational:
        return False

    if vehicle_connectors:
        station_connectors = _extract_station_connectors(station)
        # Station connector verisi yoksa filtreleme (eski cache'lenmis kayit).
        if station_connectors and not vehicle_connectors.intersection(station_connectors):
            return False

    # Detour HARD filter: rotadan absurt uzakta istasyon listeye giremez.
    offset_km = pick(station, "distance_from_route_km", "offset_km", default=None)
    if offset_km is not None:
        try:
            if float(offset_km) > max_detour_km:
                return False
        except (TypeError, ValueError):
            pass

    return True
