"""
Overpass API üzerinden rota geometrisi için hız sınırı (maxspeed) çekme.

Tasarım:
- Rota geometrisini örnekler (her N noktada bir)
- Her örneklenen nokta etrafında küçük bir bbox kurar
- Overpass'a `way["highway"]["maxspeed"]` sorgusu gönderir
- En yakın yolu bulur, maxspeed değerini parser eder
- Limit alınamayan kesimler için highway tipine göre fallback değer döner

Hata politikası:
- Overpass'a ulaşılamazsa highway-tipi fallback'e döner
- Tek bir nokta bulunamazsa atlanır, kalanına devam edilir
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests


Coordinate = Tuple[float, float]  # (lat, lon)


# Overpass'tan veri yoksa veya parse edilemezse highway tipine göre tahmin
HIGHWAY_DEFAULT_KMH: Dict[str, float] = {
    "motorway": 120.0,
    "motorway_link": 80.0,
    "trunk": 90.0,
    "trunk_link": 60.0,
    "primary": 90.0,
    "primary_link": 60.0,
    "secondary": 70.0,
    "secondary_link": 50.0,
    "tertiary": 60.0,
    "tertiary_link": 40.0,
    "residential": 50.0,
    "unclassified": 50.0,
    "living_street": 30.0,
    "service": 30.0,
}


@dataclass
class SpeedLimitSegment:
    start_index: int
    end_index: int
    maxspeed_kmh: Optional[float]
    highway: Optional[str]


class SpeedLimitServiceError(Exception):
    pass


def _haversine_km(a: Coordinate, b: Coordinate) -> float:
    """Coordinate tuple (lat, lon) imzasiyla geo_utils.haversine_km wrapper'i."""
    from app.core.geo_utils import haversine_km

    return haversine_km(a[0], a[1], b[0], b[1])


def _parse_maxspeed(raw: Optional[str]) -> Optional[float]:
    """OSM'in maxspeed değerini km/h'a çevirir.

    Örnek değerler: "50", "30 mph", "RU:rural", "none", "signals"
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if s in {"none", "signals", "variable", "walk"}:
        return None

    m = re.match(r"^(\d+(?:\.\d+)?)\s*(mph|km/?h)?$", s)
    if not m:
        # Bölgesel kural ("RU:rural" vb.) → atla
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "mph":
        return round(value * 1.609344, 1)
    return value


class OverpassSpeedLimitService:
    """Overpass API üzerinden rota üzerindeki hız limitlerini çıkarır."""

    def __init__(
        self,
        base_url: str = "https://overpass-api.de/api/interpreter",
        timeout: int = 25,
        bbox_radius_m: float = 200.0,
        max_attempts: int = 2,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.bbox_radius_m = bbox_radius_m
        self.max_attempts = max_attempts

    def get_segments(
        self,
        geometry: List[Coordinate],
        *,
        sample_every_n_points: int = 20,
    ) -> Tuple[List[SpeedLimitSegment], str]:
        """
        geometry: [(lat, lon), ...]

        Dönüş:
            (segments, source)
            source ∈ {"overpass", "fallback"}
        """
        if len(geometry) < 2:
            return [], "fallback"

        sample_indices = self._build_sample_indices(
            len(geometry), sample_every_n_points
        )
        sample_points = [geometry[i] for i in sample_indices]

        # Tek Overpass sorgusu: tum bbox'lari union ile birlestir
        try:
            ways = self._query_bbox_union(sample_points)
            used_overpass = True
        except Exception:  # noqa: BLE001
            ways = []
            used_overpass = False

        results: Dict[int, Tuple[Optional[float], Optional[str]]] = {}
        for idx, (lat, lon) in zip(sample_indices, sample_points):
            results[idx] = self._pick_best_way_from_pool(lat, lon, ways)

        segments: List[SpeedLimitSegment] = []
        for i, idx in enumerate(sample_indices):
            start_idx = idx
            end_idx = (
                sample_indices[i + 1] - 1
                if i + 1 < len(sample_indices)
                else len(geometry) - 1
            )
            ms, hw = results.get(idx, (None, None))
            if ms is None and hw:
                ms = HIGHWAY_DEFAULT_KMH.get(hw)
            segments.append(
                SpeedLimitSegment(
                    start_index=start_idx,
                    end_index=end_idx,
                    maxspeed_kmh=ms,
                    highway=hw,
                )
            )

        any_real_match = any(
            s.maxspeed_kmh is not None or s.highway is not None for s in segments
        )
        source = "overpass" if used_overpass and any_real_match else "fallback"
        return segments, source

    def _query_bbox_union(
        self, sample_points: List[Coordinate]
    ) -> List[dict]:
        """Tum nokta bbox'larini tek sorguda birlestirip way listesi doner."""
        if not sample_points:
            return []

        bbox_clauses = []
        for lat, lon in sample_points:
            bbox = self._bbox_around(lat, lon, self.bbox_radius_m)
            bbox_clauses.append(
                f"way[\"highway\"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});"
            )

        ql = (
            f"[out:json][timeout:{self.timeout}];"
            f"({''.join(bbox_clauses)});"
            "out tags geom;"
        )

        headers = {
            "User-Agent": "ev-route-optimizer/0.6 (academic project)",
            "Accept": "application/json",
        }

        last_err: Optional[Exception] = None
        for _ in range(self.max_attempts):
            try:
                resp = requests.post(
                    self.base_url,
                    data={"data": ql},
                    headers=headers,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("elements", []) or []
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue

        if last_err:
            raise SpeedLimitServiceError(str(last_err))
        return []

    def _pick_best_way_from_pool(
        self, lat: float, lon: float, ways: List[dict]
    ) -> Tuple[Optional[float], Optional[str]]:
        """Onceden cekilmis way havuzundan bu noktaya en yakini secer."""
        best_way: Optional[dict] = None
        best_dist_km = math.inf

        for el in ways:
            if el.get("type") != "way":
                continue
            tags = el.get("tags") or {}
            hw = tags.get("highway")
            if hw not in self.DRIVABLE_HIGHWAYS:
                continue
            geom = el.get("geometry") or []
            if not geom:
                continue
            for node in geom:
                d = _haversine_km(
                    (lat, lon), (node.get("lat", 0.0), node.get("lon", 0.0))
                )
                if d < best_dist_km:
                    best_dist_km = d
                    best_way = el

        if best_way is None:
            return None, None
        tags = best_way.get("tags") or {}
        return _parse_maxspeed(tags.get("maxspeed")), tags.get("highway")

    def _build_sample_indices(self, total: int, step: int) -> List[int]:
        if total <= 0:
            return []
        if step <= 0:
            step = 1
        indices = list(range(0, total, step))
        if indices[-1] != total - 1:
            indices.append(total - 1)
        return indices

    def _query_point(
        self, lat: float, lon: float
    ) -> Tuple[Optional[float], Optional[str]]:
        bbox = self._bbox_around(lat, lon, self.bbox_radius_m)
        ql = (
            "[out:json][timeout:20];"
            f"way[\"highway\"]({bbox[0]:.6f},{bbox[1]:.6f},{bbox[2]:.6f},{bbox[3]:.6f});"
            "out tags geom;"
        )

        headers = {
            "User-Agent": "ev-route-optimizer/0.6 (academic project)",
            "Accept": "application/json",
        }

        last_err: Optional[Exception] = None
        for _ in range(self.max_attempts):
            try:
                resp = requests.post(
                    self.base_url,
                    data={"data": ql},
                    headers=headers,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return self._pick_best_way(lat, lon, data.get("elements", []))
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue

        # Tum denemeler basarisiz
        if last_err:
            raise SpeedLimitServiceError(str(last_err))
        return None, None

    @staticmethod
    def _bbox_around(
        lat: float, lon: float, radius_m: float
    ) -> Tuple[float, float, float, float]:
        # ~1 derece enlem ≈ 111 km
        d_lat = radius_m / 111_000.0
        d_lon = radius_m / (111_000.0 * max(math.cos(math.radians(lat)), 1e-6))
        return (lat - d_lat, lon - d_lon, lat + d_lat, lon + d_lon)

    # Sadece araçlarin kullandigi yollari secelim
    DRIVABLE_HIGHWAYS = frozenset(
        {
            "motorway",
            "motorway_link",
            "trunk",
            "trunk_link",
            "primary",
            "primary_link",
            "secondary",
            "secondary_link",
            "tertiary",
            "tertiary_link",
            "unclassified",
            "residential",
            "living_street",
            "service",
        }
    )

    @classmethod
    def _pick_best_way(
        cls, lat: float, lon: float, elements: List[dict]
    ) -> Tuple[Optional[float], Optional[str]]:
        best_way: Optional[dict] = None
        best_dist_km = math.inf

        for el in elements:
            if el.get("type") != "way":
                continue
            tags = el.get("tags") or {}
            hw = tags.get("highway")
            if hw not in cls.DRIVABLE_HIGHWAYS:
                continue
            geom = el.get("geometry") or []
            if not geom:
                continue
            for node in geom:
                d = _haversine_km(
                    (lat, lon), (node.get("lat", 0.0), node.get("lon", 0.0))
                )
                if d < best_dist_km:
                    best_dist_km = d
                    best_way = el

        if best_way is None:
            return None, None

        tags = best_way.get("tags") or {}
        ms = _parse_maxspeed(tags.get("maxspeed"))
        hw = tags.get("highway")
        return ms, hw
