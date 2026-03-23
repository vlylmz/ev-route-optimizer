from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

import requests


Coordinate = Tuple[float, float]  # (lat, lon)


class RoutingServiceError(Exception):
    pass


@dataclass
class RouteWaypoint:
    name: str
    location: Coordinate   # (lat, lon)
    snapped_distance_m: float


@dataclass
class RouteSummary:
    distance_m: float
    duration_s: float
    geometry: List[Coordinate]  # [(lat, lon), ...]
    waypoints: List[RouteWaypoint]
    raw: Dict[str, Any]


class OSRMRoutingService:
    def __init__(
        self,
        base_url: str = "https://router.project-osrm.org",
        profile: str = "driving",
        timeout: int = 15,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.timeout = timeout

    @staticmethod
    def _validate_coordinate(coord: Coordinate) -> None:
        lat, lon = coord
        if not (-90 <= lat <= 90):
            raise ValueError(f"Geçersiz latitude: {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Geçersiz longitude: {lon}")

    @staticmethod
    def _to_osrm_coord(coord: Coordinate) -> str:
        """
        OSRM koordinatları lon,lat formatında bekler.
        Biz içeride (lat, lon) kullanıyoruz.
        """
        lat, lon = coord
        return f"{lon},{lat}"

    @staticmethod
    def _from_osrm_coord(coord: List[float]) -> Coordinate:
        """
        OSRM geometry/waypoint location çıktısı [lon, lat] verir.
        İçeride (lat, lon) standardına çeviriyoruz.
        """
        lon, lat = coord
        return (lat, lon)

    def get_route(
        self,
        start: Coordinate,
        end: Coordinate,
        alternatives: bool = False,
        steps: bool = True,
        annotations: bool = True,
    ) -> RouteSummary:
        self._validate_coordinate(start)
        self._validate_coordinate(end)

        coordinates = f"{self._to_osrm_coord(start)};{self._to_osrm_coord(end)}"
        url = f"{self.base_url}/route/v1/{self.profile}/{coordinates}"

        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": str(steps).lower(),
            "annotations": str(annotations).lower(),
            "alternatives": str(alternatives).lower(),
        }

        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RoutingServiceError(f"OSRM isteği başarısız: {exc}") from exc

        data = response.json()

        if data.get("code") != "Ok":
            raise RoutingServiceError(
                f"OSRM hata döndü: code={data.get('code')} message={data.get('message')}"
            )

        routes = data.get("routes", [])
        if not routes:
            raise RoutingServiceError("OSRM rota döndürmedi.")

        best_route = routes[0]

        distance_m = float(best_route.get("distance", 0.0))
        duration_s = float(best_route.get("duration", 0.0))

        geometry_coords = (
            best_route.get("geometry", {}).get("coordinates", [])
            if isinstance(best_route.get("geometry"), dict)
            else []
        )
        geometry: List[Coordinate] = [
            self._from_osrm_coord(coord)
            for coord in geometry_coords
        ]

        waypoints_raw = data.get("waypoints", [])
        waypoints: List[RouteWaypoint] = []
        for wp in waypoints_raw:
            location = wp.get("location", [0.0, 0.0])
            waypoints.append(
                RouteWaypoint(
                    name=wp.get("name", ""),
                    location=self._from_osrm_coord(location),
                    snapped_distance_m=float(wp.get("distance", 0.0)),
                )
            )

        return RouteSummary(
            distance_m=distance_m,
            duration_s=duration_s,
            geometry=geometry,
            waypoints=waypoints,
            raw=data,
        )

    def get_route_dict(
        self,
        start: Coordinate,
        end: Coordinate,
        alternatives: bool = False,
        steps: bool = True,
        annotations: bool = True,
    ) -> Dict[str, Any]:
        result = self.get_route(
            start=start,
            end=end,
            alternatives=alternatives,
            steps=steps,
            annotations=annotations,
        )

        return {
            "distance_m": round(result.distance_m, 2),
            "distance_km": round(result.distance_m / 1000.0, 3),
            "duration_s": round(result.duration_s, 2),
            "duration_min": round(result.duration_s / 60.0, 2),
            "geometry": result.geometry,
            "geometry_point_count": len(result.geometry),
            "waypoints": [
                {
                    "name": wp.name,
                    "location": wp.location,
                    "snapped_distance_m": round(wp.snapped_distance_m, 2),
                }
                for wp in result.waypoints
            ],
        }


if __name__ == "__main__":
    service = OSRMRoutingService()

    # Ankara -> Eskişehir örneği
    start = (39.9208, 32.8541)
    end = (39.7767, 30.5206)

    route = service.get_route_dict(start, end)

    print("Mesafe (km):", route["distance_km"])
    print("Süre (dk):", route["duration_min"])
    print("Geometri nokta sayısı:", route["geometry_point_count"])
    print("Waypoints:", route["waypoints"])