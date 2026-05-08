from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

import requests


Coordinate = Tuple[float, float]  # (lat, lon)


class ElevationServiceError(Exception):
    pass


@dataclass
class ElevationPoint:
    lat: float
    lon: float
    elevation_m: float
    cumulative_distance_km: float


@dataclass
class SlopeSegment:
    start: Coordinate
    end: Coordinate
    distance_km: float
    elevation_start_m: float
    elevation_end_m: float
    elevation_delta_m: float
    grade_pct: float


class OpenElevationService:
    def __init__(
        self,
        base_url: str = "https://api.open-elevation.com",
        timeout: int = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def _validate_coordinate(coord: Coordinate) -> None:
        lat, lon = coord
        if not (-90 <= lat <= 90):
            raise ValueError(f"Geçersiz latitude: {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Geçersiz longitude: {lon}")

    @staticmethod
    def haversine_km(a: Coordinate, b: Coordinate) -> float:
        """Coordinate tuple imzasiyla geo_utils.haversine_km wrapper'i."""
        from app.core.geo_utils import haversine_km

        return haversine_km(a[0], a[1], b[0], b[1])

    def sample_geometry(
        self,
        geometry: List[Coordinate],
        min_spacing_km: float = 3.0,
        max_points: int = 80,
    ) -> List[Coordinate]:
        """
        OSRM geometry çok yoğunsa seyrekleştir.
        - İlk ve son nokta korunur
        - Aradaki noktalar min_spacing_km'e göre seçilir
        - Gerekirse max_points'e göre ikinci kez inceltilir
        """
        if not geometry:
            raise ValueError("Boş geometry verildi.")

        for coord in geometry:
            self._validate_coordinate(coord)

        if len(geometry) <= 2:
            return geometry[:]

        sampled = [geometry[0]]
        last_kept = geometry[0]

        for point in geometry[1:-1]:
            if self.haversine_km(last_kept, point) >= min_spacing_km:
                sampled.append(point)
                last_kept = point

        if sampled[-1] != geometry[-1]:
            sampled.append(geometry[-1])

        # Hâlâ çok fazlaysa eşit aralıklı incelt
        if len(sampled) > max_points:
            step = (len(sampled) - 1) / (max_points - 1)
            reduced = []
            for i in range(max_points):
                idx = round(i * step)
                reduced.append(sampled[idx])

            # olası duplicate temizliği
            deduped = []
            for p in reduced:
                if not deduped or deduped[-1] != p:
                    deduped.append(p)

            if deduped[0] != sampled[0]:
                deduped.insert(0, sampled[0])
            if deduped[-1] != sampled[-1]:
                deduped.append(sampled[-1])

            sampled = deduped

        return sampled

    def lookup_elevations(
        self,
        coordinates: List[Coordinate],
    ) -> List[Dict[str, float]]:
        """
        Open-Elevation POST /api/v1/lookup
        Gönderim sırası korunur, yanıt da aynı sırada gelir.
        """
        if not coordinates:
            raise ValueError("Elevation lookup için koordinat listesi boş olamaz.")

        for coord in coordinates:
            self._validate_coordinate(coord)

        url = f"{self.base_url}/api/v1/lookup"
        payload = {
            "locations": [
                {"latitude": lat, "longitude": lon}
                for lat, lon in coordinates
            ]
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ElevationServiceError(f"Open-Elevation isteği başarısız: {exc}") from exc

        data = response.json()
        results = data.get("results", [])

        if len(results) != len(coordinates):
            raise ElevationServiceError(
                f"Beklenen {len(coordinates)} sonuç yerine {len(results)} sonuç döndü."
            )

        normalized = []
        for item in results:
            normalized.append(
                {
                    "latitude": float(item["latitude"]),
                    "longitude": float(item["longitude"]),
                    "elevation": float(item["elevation"]),
                }
            )

        return normalized

    def build_elevation_profile(
        self,
        coordinates: List[Coordinate],
    ) -> List[ElevationPoint]:
        if not coordinates:
            raise ValueError("Koordinat listesi boş olamaz.")

        elevations = self.lookup_elevations(coordinates)

        profile: List[ElevationPoint] = []
        cumulative_distance_km = 0.0
        prev_coord: Optional[Coordinate] = None

        for item in elevations:
            coord = (item["latitude"], item["longitude"])

            if prev_coord is not None:
                cumulative_distance_km += self.haversine_km(prev_coord, coord)

            profile.append(
                ElevationPoint(
                    lat=item["latitude"],
                    lon=item["longitude"],
                    elevation_m=item["elevation"],
                    cumulative_distance_km=round(cumulative_distance_km, 4),
                )
            )
            prev_coord = coord

        return profile

    def build_slope_segments(
        self,
        profile: List[ElevationPoint],
        grade_cap_pct: float = 12.0,
    ) -> List[SlopeSegment]:
        """
        İki elevation noktası arasındaki yaklaşık eğim yüzdesini hesaplar.
        Aşırı gürültüyü azaltmak için eğim üst sınırı koyulur.
        """
        if len(profile) < 2:
            return []

        segments: List[SlopeSegment] = []

        for i in range(len(profile) - 1):
            a = profile[i]
            b = profile[i + 1]

            start = (a.lat, a.lon)
            end = (b.lat, b.lon)

            distance_km = max(
                0.001,
                self.haversine_km(start, end),
            )
            elevation_delta_m = b.elevation_m - a.elevation_m
            grade_pct = (elevation_delta_m / (distance_km * 1000.0)) * 100.0
            grade_pct = max(-grade_cap_pct, min(grade_cap_pct, grade_pct))

            segments.append(
                SlopeSegment(
                    start=start,
                    end=end,
                    distance_km=round(distance_km, 4),
                    elevation_start_m=round(a.elevation_m, 2),
                    elevation_end_m=round(b.elevation_m, 2),
                    elevation_delta_m=round(elevation_delta_m, 2),
                    grade_pct=round(grade_pct, 3),
                )
            )

        return segments

    def get_elevation_and_slope(
        self,
        geometry: List[Coordinate],
        min_spacing_km: float = 3.0,
        max_points: int = 80,
    ) -> Dict[str, Any]:
        sampled_geometry = self.sample_geometry(
            geometry=geometry,
            min_spacing_km=min_spacing_km,
            max_points=max_points,
        )

        profile = self.build_elevation_profile(sampled_geometry)
        slope_segments = self.build_slope_segments(profile)

        return {
            "sampled_point_count": len(sampled_geometry),
            "sampled_geometry": sampled_geometry,
            "elevation_profile": [
                {
                    "lat": p.lat,
                    "lon": p.lon,
                    "elevation_m": p.elevation_m,
                    "cumulative_distance_km": p.cumulative_distance_km,
                }
                for p in profile
            ],
            "slope_segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "distance_km": s.distance_km,
                    "elevation_start_m": s.elevation_start_m,
                    "elevation_end_m": s.elevation_end_m,
                    "elevation_delta_m": s.elevation_delta_m,
                    "grade_pct": s.grade_pct,
                }
                for s in slope_segments
            ],
        }


if __name__ == "__main__":
    from app.services.routing_service import OSRMRoutingService

    routing = OSRMRoutingService()
    elevation = OpenElevationService()

    start = (39.9208, 32.8541)   # Ankara
    end = (39.7767, 30.5206)     # Eskişehir

    route = routing.get_route_dict(start, end)
    geometry = route["geometry"]

    result = elevation.get_elevation_and_slope(
        geometry=geometry,
        min_spacing_km=5.0,
        max_points=60,
    )

    print("Orijinal geometri nokta sayısı:", len(geometry))
    print("Örneklenmiş nokta sayısı:", result["sampled_point_count"])
    print("İlk 3 elevation point:", result["elevation_profile"][:3])
    print("İlk 3 slope segment:", result["slope_segments"][:3])