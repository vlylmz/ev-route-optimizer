from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

from app.services.routing_service import OSRMRoutingService
from app.services.elevation_service import OpenElevationService
from app.services.weather_service import OpenMeteoWeatherService
from app.services.charging_service import OpenChargeMapService


Coordinate = Tuple[float, float]  # (lat, lon)


class RouteContextServiceError(Exception):
    pass


class RouteContextService:
    def __init__(
        self,
        routing_service: Optional[OSRMRoutingService] = None,
        elevation_service: Optional[OpenElevationService] = None,
        weather_service: Optional[OpenMeteoWeatherService] = None,
        charging_service: Optional[OpenChargeMapService] = None,
    ) -> None:
        self.routing_service = routing_service or OSRMRoutingService()
        self.elevation_service = elevation_service or OpenElevationService()
        self.weather_service = weather_service or OpenMeteoWeatherService()
        self.charging_service = charging_service or OpenChargeMapService()

    def build_route_context(
        self,
        start: Coordinate,
        end: Coordinate,
        elevation_min_spacing_km: float = 5.0,
        elevation_max_points: int = 60,
        weather_sample_limit: int = 5,
        station_query_every_n_points: int = 4,
        station_distance_km: float = 5.0,
        station_max_results_per_query: int = 10,
        allow_station_fallback: bool = True,
    ) -> Dict[str, Any]:
        """
        Tüm dış servisleri birleştirip tek bir route context üretir.
        """

        # 1) Rota
        route = self.routing_service.get_route_dict(start, end)
        geometry: List[Coordinate] = route["geometry"]

        if not geometry:
            raise RouteContextServiceError("Rota geometry verisi boş döndü.")

        # 2) Elevation + slope
        elevation = self.elevation_service.get_elevation_and_slope(
            geometry=geometry,
            min_spacing_km=elevation_min_spacing_km,
            max_points=elevation_max_points,
        )

        sampled_geometry: List[Coordinate] = elevation["sampled_geometry"]

        # 3) Hava özeti
        weather_points = self._select_weather_points(
            sampled_geometry,
            limit=weather_sample_limit,
        )
        weather = self.weather_service.summarize_route_temperature(weather_points)

        # 4) Şarj istasyonları
        stations_raw = self.charging_service.find_stations_along_route(
            sampled_geometry=sampled_geometry,
            query_every_n_points=station_query_every_n_points,
            distance_km=station_distance_km,
            max_results_per_query=station_max_results_per_query,
            allow_fallback=allow_station_fallback,
        )
        stations = [self.charging_service.station_to_dict(s) for s in stations_raw]

        # 5) Özet metrikler
        slope_summary = self._build_slope_summary(elevation["slope_segments"])

        return {
            "input": {
                "start": start,
                "end": end,
            },
            "route": route,
            "elevation": {
                "sampled_point_count": elevation["sampled_point_count"],
                "elevation_profile": elevation["elevation_profile"],
                "slope_segments": elevation["slope_segments"],
                "slope_summary": slope_summary,
            },
            "weather": weather,
            "stations": stations,
            "summary": {
                "distance_km": route["distance_km"],
                "duration_min": route["duration_min"],
                "geometry_point_count": route["geometry_point_count"],
                "sampled_point_count": elevation["sampled_point_count"],
                "weather_point_count": weather["point_count"],
                "station_count": len(stations),
                "avg_temp_c": weather["avg_temp_c"],
                "min_temp_c": weather["min_temp_c"],
                "max_temp_c": weather["max_temp_c"],
                "avg_grade_pct": slope_summary["avg_grade_pct"],
                "max_uphill_grade_pct": slope_summary["max_uphill_grade_pct"],
                "max_downhill_grade_pct": slope_summary["max_downhill_grade_pct"],
            },
        }

    @staticmethod
    def _select_weather_points(
        sampled_geometry: List[Coordinate],
        limit: int = 5,
    ) -> List[Coordinate]:
        """
        Tüm örnek noktaları hava için sorgulamak yerine birkaç temsilci nokta seç.
        İlk, son ve aradaki eşit aralıklı noktaları korur.
        """
        if not sampled_geometry:
            return []

        if len(sampled_geometry) <= limit:
            return sampled_geometry

        selected: List[Coordinate] = []
        step = (len(sampled_geometry) - 1) / (limit - 1)

        for i in range(limit):
            idx = round(i * step)
            selected.append(sampled_geometry[idx])

        deduped: List[Coordinate] = []
        for point in selected:
            if not deduped or deduped[-1] != point:
                deduped.append(point)

        return deduped

    @staticmethod
    def _build_slope_summary(slope_segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not slope_segments:
            return {
                "segment_count": 0,
                "avg_grade_pct": None,
                "max_uphill_grade_pct": None,
                "max_downhill_grade_pct": None,
            }

        grades = [float(seg["grade_pct"]) for seg in slope_segments]
        uphill = [g for g in grades if g > 0]
        downhill = [g for g in grades if g < 0]

        return {
            "segment_count": len(slope_segments),
            "avg_grade_pct": round(sum(grades) / len(grades), 3),
            "max_uphill_grade_pct": round(max(uphill), 3) if uphill else 0.0,
            "max_downhill_grade_pct": round(min(downhill), 3) if downhill else 0.0,
        }


if __name__ == "__main__":
    service = RouteContextService()

    start = (39.9208, 32.8541)   # Ankara
    end = (39.7767, 30.5206)     # Eskişehir

    context = service.build_route_context(
        start=start,
        end=end,
        elevation_min_spacing_km=5.0,
        elevation_max_points=60,
        weather_sample_limit=5,
        station_query_every_n_points=4,
        station_distance_km=5.0,
        station_max_results_per_query=10,
        allow_station_fallback=True,
    )

    print("=== ROUTE CONTEXT SUMMARY ===")
    print("Distance (km):", context["summary"]["distance_km"])
    print("Duration (min):", context["summary"]["duration_min"])
    print("Geometry points:", context["summary"]["geometry_point_count"])
    print("Sampled points:", context["summary"]["sampled_point_count"])
    print("Weather avg temp (C):", context["summary"]["avg_temp_c"])
    print("Station count:", context["summary"]["station_count"])
    print("Avg grade (%):", context["summary"]["avg_grade_pct"])
    print("Max uphill (%):", context["summary"]["max_uphill_grade_pct"])
    print("Max downhill (%):", context["summary"]["max_downhill_grade_pct"])