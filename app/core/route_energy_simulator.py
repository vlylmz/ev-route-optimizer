from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.core.energy_model import Vehicle, estimate_segment_energy


@dataclass
class RouteEnergySegmentResult:
    segment_no: int
    distance_km: float
    speed_kmh: float
    grade_pct: float
    temp_c: float
    start_soc_pct: float
    end_soc_pct: float
    energy_used_kwh: float
    consumption_wh_km: float
    below_reserve: bool
    segment_start: tuple[float, float]
    segment_end: tuple[float, float]


@dataclass
class RouteEnergySimulationResult:
    vehicle_id: str
    vehicle_name: str
    total_distance_km: float
    total_energy_kwh: float
    average_consumption_wh_km: float
    start_soc_pct: float
    end_soc_pct: float
    below_reserve: bool
    segment_count: int
    segments: List[RouteEnergySegmentResult]


class RouteEnergySimulator:
    def simulate(
        self,
        vehicle: Vehicle,
        route_context: Dict[str, Any],
        start_soc_pct: float,
    ) -> RouteEnergySimulationResult:
        slope_segments = route_context["elevation"]["slope_segments"]
        weather = route_context["weather"]

        if not slope_segments:
            raise ValueError("Route context içinde slope_segments bulunamadı.")

        avg_temp_c = weather.get("avg_temp_c")
        if avg_temp_c is None:
            avg_temp_c = 20.0

        total_distance_km = 0.0
        total_energy_kwh = 0.0
        current_soc = float(start_soc_pct)

        duration_min = route_context["route"]["duration_min"]
        route_distance_km = route_context["route"]["distance_km"]

        if route_distance_km <= 0:
            raise ValueError("Route distance 0 veya negatif olamaz.")

        avg_speed_kmh = route_distance_km / (duration_min / 60.0) if duration_min > 0 else 50.0

        results: List[RouteEnergySegmentResult] = []

        for i, seg in enumerate(slope_segments, start=1):
            distance_km = float(seg["distance_km"])
            grade_pct = float(seg["grade_pct"])

            result = estimate_segment_energy(
                vehicle=vehicle,
                distance_km=distance_km,
                speed_kmh=avg_speed_kmh,
                temp_c=avg_temp_c,
                grade_pct=grade_pct,
                start_soc_pct=current_soc,
            )

            total_distance_km += result.distance_km
            total_energy_kwh += result.energy_used_kwh
            current_soc = result.end_soc_pct

            results.append(
                RouteEnergySegmentResult(
                    segment_no=i,
                    distance_km=result.distance_km,
                    speed_kmh=result.speed_kmh,
                    grade_pct=result.grade_pct,
                    temp_c=result.temp_c,
                    start_soc_pct=result.start_soc_pct,
                    end_soc_pct=result.end_soc_pct,
                    energy_used_kwh=result.energy_used_kwh,
                    consumption_wh_km=result.consumption_wh_km,
                    below_reserve=result.below_reserve,
                    segment_start=tuple(seg["start"]),
                    segment_end=tuple(seg["end"]),
                )
            )

        avg_consumption = 0.0
        if total_distance_km > 0:
            avg_consumption = (total_energy_kwh * 1000.0) / total_distance_km

        return RouteEnergySimulationResult(
            vehicle_id=vehicle.id,
            vehicle_name=vehicle.full_name,
            total_distance_km=round(total_distance_km, 3),
            total_energy_kwh=round(total_energy_kwh, 4),
            average_consumption_wh_km=round(avg_consumption, 2),
            start_soc_pct=round(start_soc_pct, 2),
            end_soc_pct=round(current_soc, 2),
            below_reserve=current_soc < vehicle.routing_reserve_soc_pct,
            segment_count=len(results),
            segments=results,
        )

    def to_dict(self, result: RouteEnergySimulationResult) -> Dict[str, Any]:
        return {
            "vehicle_id": result.vehicle_id,
            "vehicle_name": result.vehicle_name,
            "total_distance_km": result.total_distance_km,
            "total_energy_kwh": result.total_energy_kwh,
            "average_consumption_wh_km": result.average_consumption_wh_km,
            "start_soc_pct": result.start_soc_pct,
            "end_soc_pct": result.end_soc_pct,
            "below_reserve": result.below_reserve,
            "segment_count": result.segment_count,
            "segments": [
                {
                    "segment_no": s.segment_no,
                    "distance_km": s.distance_km,
                    "speed_kmh": s.speed_kmh,
                    "grade_pct": s.grade_pct,
                    "temp_c": s.temp_c,
                    "start_soc_pct": s.start_soc_pct,
                    "end_soc_pct": s.end_soc_pct,
                    "energy_used_kwh": s.energy_used_kwh,
                    "consumption_wh_km": s.consumption_wh_km,
                    "below_reserve": s.below_reserve,
                    "segment_start": s.segment_start,
                    "segment_end": s.segment_end,
                }
                for s in result.segments
            ],
        }


if __name__ == "__main__":
    from pathlib import Path

    from app.core.energy_model import get_vehicle_by_id
    from app.services.route_context_service import RouteContextService

    json_path_candidates = [
        Path("app/data/vehicles.json"),
        Path("vehicles.json"),
    ]

    json_path = None
    for p in json_path_candidates:
        if p.exists():
            json_path = p
            break

    if json_path is None:
        raise FileNotFoundError("vehicles.json bulunamadı.")

    vehicle = get_vehicle_by_id(json_path, "tesla_model_y_rwd")

    route_context_service = RouteContextService()
    route_context = route_context_service.build_route_context(
        start=(39.9208, 32.8541),   # Ankara
        end=(39.7767, 30.5206),     # Eskişehir
        allow_station_fallback=True,
    )

    simulator = RouteEnergySimulator()
    simulation = simulator.simulate(
        vehicle=vehicle,
        route_context=route_context,
        start_soc_pct=80.0,
    )

    print("=== ROUTE ENERGY SIMULATION ===")
    print("Vehicle:", simulation.vehicle_name)
    print("Total distance (km):", simulation.total_distance_km)
    print("Total energy (kWh):", simulation.total_energy_kwh)
    print("Average consumption (Wh/km):", simulation.average_consumption_wh_km)
    print("Start SOC (%):", simulation.start_soc_pct)
    print("End SOC (%):", simulation.end_soc_pct)
    print("Below reserve:", simulation.below_reserve)
    print("Segment count:", simulation.segment_count)