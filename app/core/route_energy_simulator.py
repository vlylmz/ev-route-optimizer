from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    prediction_source: str = "formula"
    used_ml: bool = False
    model_version: Optional[str] = None


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
    # Strateji bazli surus suresi (segment hizlarindan turetilen toplam dakika).
    # OSRM duration ile karistirmamak icin ayri tutuyoruz.
    total_drive_minutes: float = 0.0
    used_ml: bool = False
    ml_segment_count: int = 0
    heuristic_segment_count: int = 0
    model_version: Optional[str] = None


class RouteEnergySimulator:
    def __init__(
        self,
        *,
        model_service: Optional[Any] = None,
        use_ml_default: bool = False,
    ) -> None:
        self.model_service = model_service
        self.use_ml_default = use_ml_default

    # Strateji bazli surus profili: fast = agresif, efficient = ekonomik.
    # Hizla speed_delta etkisi (kabaca kupik) nedeniyle %10 hiz +%14 enerji
    # demek; bu istasyon gap'lerini atlayamamaya yol acabiliyor. Bu yuzden
    # fast=1.05 olarak sinirli (+%7 enerji), yine fast modunda gozle gorulur
    # avantaj saglar.
    _STRATEGY_SPEED_FACTOR = {
        "fast": 1.05,
        "balanced": 1.00,
        "efficient": 0.94,
    }

    def simulate(
        self,
        vehicle: Vehicle,
        route_context: Dict[str, Any],
        start_soc_pct: float,
        use_ml: Optional[bool] = None,
        strategy: str = "balanced",
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
        total_drive_minutes = 0.0
        current_soc = float(start_soc_pct)

        duration_min = route_context["route"]["duration_min"]
        route_distance_km = route_context["route"]["distance_km"]

        if route_distance_km <= 0:
            raise ValueError("Route distance 0 veya negatif olamaz.")

        base_avg_speed_kmh = (
            route_distance_km / (duration_min / 60.0)
            if duration_min > 0
            else 50.0
        )
        speed_factor = self._STRATEGY_SPEED_FACTOR.get(strategy, 1.00)
        # ENERGY speed (segment enerji hesabi icin): %50'lik partial factor.
        # %100 factor istasyon gap'lerini atlayamamaya yol acabiliyor;
        # %50 factor enerji farkini koruyup pratik plan'a olanak verir.
        energy_speed_factor = 1.0 + (speed_factor - 1.0) * 0.5
        # DRIVE speed (toplam surus suresi icin): tam factor uygulanir.
        drive_speed_factor = speed_factor

        # Otoyolda 130km/h legal limit; nadir gerekli ise 140'a izin ver.
        avg_speed_kmh = max(20.0, min(140.0, base_avg_speed_kmh * energy_speed_factor))
        drive_speed_kmh = max(20.0, min(140.0, base_avg_speed_kmh * drive_speed_factor))

        traffic_factor = {"fast": 1.00, "balanced": 0.95, "efficient": 0.85}.get(strategy, 0.95)

        # Speed limit summary varsa global avg_speed_kmh cap (fallback).
        speed_summary = route_context.get("speed_limit_summary") or {}
        max_observed_limit = speed_summary.get("max_speed_kmh")
        if max_observed_limit:
            speed_cap = float(max_observed_limit) * traffic_factor
            avg_speed_kmh = min(avg_speed_kmh, speed_cap)
            drive_speed_kmh = min(drive_speed_kmh, speed_cap)

        # Per-segment speed limit lookup hazirligi.
        speed_limit_segments = route_context.get("speed_limit_segments") or []
        geometry = route_context.get("route", {}).get("geometry", []) or []
        seg_spatial_index = None
        if speed_limit_segments and geometry:
            from app.core.geo_utils import RoutePoint, RouteSpatialIndex
            # Geometry coordinatlarini RoutePoint'lerle sar; spatial index ile
            # her slope_segment koordinatina en yakin geometry index'i hizli bul.
            seg_points = [
                RoutePoint(lat=float(g[0]), lon=float(g[1]), cumulative_distance_km=float(i))
                for i, g in enumerate(geometry)
            ]
            seg_spatial_index = (seg_points, RouteSpatialIndex(seg_points))

        use_ml = self.use_ml_default if use_ml is None else use_ml

        results: List[RouteEnergySegmentResult] = []
        ml_segment_count = 0
        heuristic_segment_count = 0
        model_versions: set[str] = set()

        for i, seg in enumerate(slope_segments, start=1):
            distance_km = float(seg["distance_km"])
            grade_pct = float(seg["grade_pct"])

            # Per-segment speed limit lookup (varsa). Yoksa global avg_speed_kmh.
            segment_speed_kmh = avg_speed_kmh
            if seg_spatial_index is not None:
                seg_speed_limit = self._find_segment_speed_limit(
                    seg_start=tuple(seg["start"]),
                    seg_end=tuple(seg["end"]),
                    seg_points=seg_spatial_index[0],
                    spatial_index=seg_spatial_index[1],
                    speed_limit_segments=speed_limit_segments,
                )
                if seg_speed_limit is not None:
                    # Per-segment limit: traffic factor uygula, mevcut avg ile min al.
                    segment_speed_kmh = min(
                        avg_speed_kmh,
                        seg_speed_limit * traffic_factor,
                    )

            segment_result = self._simulate_segment(
                vehicle=vehicle,
                distance_km=distance_km,
                speed_kmh=segment_speed_kmh,
                temp_c=avg_temp_c,
                grade_pct=grade_pct,
                start_soc_pct=current_soc,
                segment_no=i,
                segment_start=tuple(seg["start"]),
                segment_end=tuple(seg["end"]),
                use_ml=use_ml,
            )

            total_distance_km += segment_result.distance_km
            total_energy_kwh += segment_result.energy_used_kwh
            # Segment suresi = mesafe / drive_speed (tam strategy factor yansir;
            # enerji ise partial factor ile hesaplandi).
            if drive_speed_kmh > 0:
                total_drive_minutes += (segment_result.distance_km / drive_speed_kmh) * 60.0
            current_soc = segment_result.end_soc_pct

            if segment_result.used_ml:
                ml_segment_count += 1
                if segment_result.model_version:
                    model_versions.add(segment_result.model_version)
            else:
                heuristic_segment_count += 1

            results.append(segment_result)

        avg_consumption = 0.0
        if total_distance_km > 0:
            avg_consumption = (total_energy_kwh * 1000.0) / total_distance_km

        reserve_soc_pct = self._reserve_soc_pct(vehicle)

        return RouteEnergySimulationResult(
            vehicle_id=vehicle.id,
            vehicle_name=vehicle.full_name,
            total_distance_km=round(total_distance_km, 3),
            total_energy_kwh=round(total_energy_kwh, 4),
            average_consumption_wh_km=round(avg_consumption, 2),
            start_soc_pct=round(start_soc_pct, 2),
            end_soc_pct=round(current_soc, 2),
            below_reserve=current_soc < reserve_soc_pct,
            segment_count=len(results),
            segments=results,
            total_drive_minutes=round(total_drive_minutes, 1),
            used_ml=ml_segment_count > 0,
            ml_segment_count=ml_segment_count,
            heuristic_segment_count=heuristic_segment_count,
            model_version=sorted(model_versions)[0] if model_versions else None,
        )

    @staticmethod
    def _find_segment_speed_limit(
        *,
        seg_start: tuple,
        seg_end: tuple,
        seg_points: list,
        spatial_index: Any,
        speed_limit_segments: list,
    ) -> Optional[float]:
        """Slope segment'in baslangic ve bitis koordinatlarina denk gelen
        geometry index'lerini bul; bu araliktaki speed_limit segmentlerinden
        en yaygın (max) maxspeed_kmh'i dondur. Yoksa None."""
        if not speed_limit_segments or not seg_points:
            return None

        # En yakin geometry index'leri bul.
        # spatial_index.nearest cumulative_distance_km field'inde index degeri tutuluyor.
        try:
            start_point, _ = spatial_index.nearest(seg_start[0], seg_start[1])
            end_point, _ = spatial_index.nearest(seg_end[0], seg_end[1])
            start_idx = int(start_point.cumulative_distance_km)
            end_idx = int(end_point.cumulative_distance_km)
        except (ValueError, AttributeError):
            return None

        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx

        # Bu araligi orten speed_limit segmentlerini topla.
        overlapping_limits = []
        for sl_seg in speed_limit_segments:
            sl_start = int(sl_seg.get("start_index", 0))
            sl_end = int(sl_seg.get("end_index", 0))
            maxspeed = sl_seg.get("maxspeed_kmh")
            if maxspeed is None:
                continue
            # Kesisim var mi?
            if sl_end < start_idx or sl_start > end_idx:
                continue
            overlapping_limits.append(float(maxspeed))

        if not overlapping_limits:
            return None
        # Birden fazla cakisma varsa muhafazakar yaklasim: en dusuk limit
        # (her zaman saygi gosterilmeli).
        return min(overlapping_limits)

    def _simulate_segment(
        self,
        *,
        vehicle: Vehicle,
        distance_km: float,
        speed_kmh: float,
        temp_c: float,
        grade_pct: float,
        start_soc_pct: float,
        segment_no: int,
        segment_start: tuple[float, float],
        segment_end: tuple[float, float],
        use_ml: bool,
    ) -> RouteEnergySegmentResult:
        reserve_soc_pct = self._reserve_soc_pct(vehicle)

        if use_ml and self.model_service is not None:
            ml_prediction = self._predict_with_ml(
                vehicle=vehicle,
                distance_km=distance_km,
                speed_kmh=speed_kmh,
                temp_c=temp_c,
                grade_pct=grade_pct,
                start_soc_pct=start_soc_pct,
            )

            if ml_prediction is not None:
                energy_used_kwh = ml_prediction["predicted_energy_kwh"]
                end_soc_pct = self._calc_end_soc(
                    start_soc_pct=start_soc_pct,
                    energy_used_kwh=energy_used_kwh,
                    usable_battery_kwh=vehicle.usable_battery_kwh,
                )
                consumption_wh_km = (
                    (energy_used_kwh * 1000.0) / distance_km
                    if distance_km > 0
                    else 0.0
                )

                return RouteEnergySegmentResult(
                    segment_no=segment_no,
                    distance_km=round(distance_km, 3),
                    speed_kmh=round(speed_kmh, 2),
                    grade_pct=round(grade_pct, 3),
                    temp_c=round(temp_c, 2),
                    start_soc_pct=round(start_soc_pct, 2),
                    end_soc_pct=round(end_soc_pct, 2),
                    energy_used_kwh=round(energy_used_kwh, 4),
                    consumption_wh_km=round(consumption_wh_km, 2),
                    below_reserve=end_soc_pct < reserve_soc_pct,
                    segment_start=segment_start,
                    segment_end=segment_end,
                    prediction_source=ml_prediction["source"],
                    used_ml=True,
                    model_version=ml_prediction.get("model_version"),
                )

        result = estimate_segment_energy(
            vehicle=vehicle,
            distance_km=distance_km,
            speed_kmh=speed_kmh,
            temp_c=temp_c,
            grade_pct=grade_pct,
            start_soc_pct=start_soc_pct,
        )

        return RouteEnergySegmentResult(
            segment_no=segment_no,
            distance_km=result.distance_km,
            speed_kmh=result.speed_kmh,
            grade_pct=result.grade_pct,
            temp_c=result.temp_c,
            start_soc_pct=result.start_soc_pct,
            end_soc_pct=result.end_soc_pct,
            energy_used_kwh=result.energy_used_kwh,
            consumption_wh_km=result.consumption_wh_km,
            below_reserve=result.below_reserve,
            segment_start=segment_start,
            segment_end=segment_end,
            prediction_source="formula",
            used_ml=False,
            model_version=None,
        )

    def _predict_with_ml(
        self,
        *,
        vehicle: Vehicle,
        distance_km: float,
        speed_kmh: float,
        temp_c: float,
        grade_pct: float,
        start_soc_pct: float,
    ) -> Optional[Dict[str, Any]]:
        try:
            elevation_gain_m, elevation_loss_m = self._grade_to_elevation(
                distance_km=distance_km,
                grade_pct=grade_pct,
            )

            segment_payload = {
                "segment_length_km": distance_km,
                "avg_speed_kmh": speed_kmh,
                "elevation_gain_m": elevation_gain_m,
                "elevation_loss_m": elevation_loss_m,
                "temperature_c": temp_c,
                "soc_start_percent": start_soc_pct,
                "soc_end_percent": max(start_soc_pct - 5.0, 0.0),
            }

            prediction = self.model_service.predict_segment_energy(
                segment=segment_payload,
                vehicle={
                    "id": vehicle.id,
                    "vehicle_id": vehicle.id,
                    "name": vehicle.full_name,
                    "model": vehicle.model,
                    "usable_battery_kwh": vehicle.usable_battery_kwh,
                    "ideal_consumption_wh_km": vehicle.ideal_consumption_wh_km,
                    "temp_penalty_factor": getattr(vehicle, "temp_penalty_factor", 0.012),
                },
                weather={"temperature_c": temp_c},
            )

            if not prediction:
                return None

            predicted_energy_kwh = float(prediction.get("predicted_energy_kwh", 0.0))
            if predicted_energy_kwh <= 0:
                return None

            return {
                "source": str(prediction.get("source", "ml")),
                "predicted_energy_kwh": predicted_energy_kwh,
                "model_version": prediction.get("model_version"),
            }
        except Exception:
            return None

    def _grade_to_elevation(
        self,
        *,
        distance_km: float,
        grade_pct: float,
    ) -> tuple[float, float]:
        horizontal_distance_m = distance_km * 1000.0
        elevation_delta_m = horizontal_distance_m * (grade_pct / 100.0)

        if elevation_delta_m >= 0:
            return elevation_delta_m, 0.0
        return 0.0, abs(elevation_delta_m)

    def _calc_end_soc(
        self,
        *,
        start_soc_pct: float,
        energy_used_kwh: float,
        usable_battery_kwh: float,
    ) -> float:
        if usable_battery_kwh <= 0:
            return start_soc_pct

        soc_drop_pct = (energy_used_kwh / usable_battery_kwh) * 100.0
        return max(start_soc_pct - soc_drop_pct, 0.0)

    def _reserve_soc_pct(self, vehicle: Vehicle) -> float:
        if hasattr(vehicle, "routing_reserve_soc_pct"):
            return float(vehicle.routing_reserve_soc_pct)
        if hasattr(vehicle, "soc_min_pct"):
            return float(vehicle.soc_min_pct)
        return 10.0

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
            "used_ml": result.used_ml,
            "ml_segment_count": result.ml_segment_count,
            "heuristic_segment_count": result.heuristic_segment_count,
            "model_version": result.model_version,
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
                    "prediction_source": s.prediction_source,
                    "used_ml": s.used_ml,
                    "model_version": s.model_version,
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
        start=(39.9208, 32.8541),
        end=(39.7767, 30.5206),
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
    print("Used ML:", simulation.used_ml)
    print("ML segment count:", simulation.ml_segment_count)