from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.route_energy_simulator import (
    RouteEnergySimulationResult,
    RouteEnergySegmentResult,
)


@dataclass
class ChargeNeedAnalysis:
    route_completed: bool
    charging_required: bool
    reserve_soc_pct: float
    start_soc_pct: float
    end_soc_pct: float
    minimum_soc_pct: float
    critical_segment_no: Optional[int]
    critical_segment_start_soc_pct: Optional[float]
    critical_segment_end_soc_pct: Optional[float]
    estimated_additional_soc_needed_pct: float
    estimated_additional_energy_needed_kwh: float
    recommendation: str

    # ML / fallback izleme alanları
    used_ml: bool = False
    ml_segment_count: int = 0
    heuristic_segment_count: int = 0
    model_version: Optional[str] = None


class ChargeNeedAnalyzer:
    def analyze(
        self,
        simulation: RouteEnergySimulationResult,
        usable_battery_kwh: float,
        reserve_soc_pct: float,
    ) -> ChargeNeedAnalysis:
        if usable_battery_kwh <= 0:
            raise ValueError("usable_battery_kwh 0'dan büyük olmalı.")

        minimum_soc_pct = (
            min(seg.end_soc_pct for seg in simulation.segments)
            if simulation.segments
            else simulation.end_soc_pct
        )

        critical_segment = self._find_critical_segment(
            simulation.segments,
            reserve_soc_pct=reserve_soc_pct,
        )

        charging_required = minimum_soc_pct < reserve_soc_pct
        route_completed = simulation.end_soc_pct >= 0.0

        additional_soc_needed_pct = 0.0
        additional_energy_needed_kwh = 0.0

        if charging_required:
            deficit_pct = reserve_soc_pct - minimum_soc_pct
            additional_soc_needed_pct = max(0.0, deficit_pct)
            additional_energy_needed_kwh = usable_battery_kwh * (
                additional_soc_needed_pct / 100.0
            )

        recommendation = self._build_recommendation(
            charging_required=charging_required,
            end_soc_pct=simulation.end_soc_pct,
            reserve_soc_pct=reserve_soc_pct,
            critical_segment=critical_segment,
            additional_soc_needed_pct=additional_soc_needed_pct,
            used_ml=getattr(simulation, "used_ml", False),
            model_version=getattr(simulation, "model_version", None),
        )

        return ChargeNeedAnalysis(
            route_completed=route_completed,
            charging_required=charging_required,
            reserve_soc_pct=round(reserve_soc_pct, 2),
            start_soc_pct=round(simulation.start_soc_pct, 2),
            end_soc_pct=round(simulation.end_soc_pct, 2),
            minimum_soc_pct=round(minimum_soc_pct, 2),
            critical_segment_no=critical_segment.segment_no if critical_segment else None,
            critical_segment_start_soc_pct=round(critical_segment.start_soc_pct, 2)
            if critical_segment
            else None,
            critical_segment_end_soc_pct=round(critical_segment.end_soc_pct, 2)
            if critical_segment
            else None,
            estimated_additional_soc_needed_pct=round(additional_soc_needed_pct, 2),
            estimated_additional_energy_needed_kwh=round(
                additional_energy_needed_kwh, 3
            ),
            recommendation=recommendation,
            used_ml=getattr(simulation, "used_ml", False),
            ml_segment_count=getattr(simulation, "ml_segment_count", 0),
            heuristic_segment_count=getattr(simulation, "heuristic_segment_count", 0),
            model_version=getattr(simulation, "model_version", None),
        )

    @staticmethod
    def _find_critical_segment(
        segments: list[RouteEnergySegmentResult],
        reserve_soc_pct: float,
    ) -> Optional[RouteEnergySegmentResult]:
        for seg in segments:
            if seg.end_soc_pct < reserve_soc_pct:
                return seg
        return None

    @staticmethod
    def _build_recommendation(
        charging_required: bool,
        end_soc_pct: float,
        reserve_soc_pct: float,
        critical_segment: Optional[RouteEnergySegmentResult],
        additional_soc_needed_pct: float,
        used_ml: bool = False,
        model_version: Optional[str] = None,
    ) -> str:
        prediction_note = ""
        if used_ml:
            if model_version:
                prediction_note = f" Tahmin kaynağı: ML ({model_version})."
            else:
                prediction_note = " Tahmin kaynağı: ML."

        if not charging_required:
            return (
                f"Rota mevcut batarya ile tamamlanabilir. "
                f"Tahmini varış SOC: %{end_soc_pct:.1f}, rezerv eşik: %{reserve_soc_pct:.1f}."
                f"{prediction_note}"
            )

        if critical_segment is None:
            return (
                f"Rota rezerv eşik altında kalıyor. "
                f"Yaklaşık %{additional_soc_needed_pct:.1f} ek SOC gerekli."
                f"{prediction_note}"
            )

        return (
            f"Şarj gerekli. Kritik düşüş {critical_segment.segment_no}. segmentte başlıyor. "
            f"Tahmini ek ihtiyaç: %{additional_soc_needed_pct:.1f} SOC."
            f"{prediction_note}"
        )

    @staticmethod
    def to_dict(result: ChargeNeedAnalysis) -> Dict[str, Any]:
        return {
            "route_completed": result.route_completed,
            "charging_required": result.charging_required,
            "reserve_soc_pct": result.reserve_soc_pct,
            "start_soc_pct": result.start_soc_pct,
            "end_soc_pct": result.end_soc_pct,
            "minimum_soc_pct": result.minimum_soc_pct,
            "critical_segment_no": result.critical_segment_no,
            "critical_segment_start_soc_pct": result.critical_segment_start_soc_pct,
            "critical_segment_end_soc_pct": result.critical_segment_end_soc_pct,
            "estimated_additional_soc_needed_pct": result.estimated_additional_soc_needed_pct,
            "estimated_additional_energy_needed_kwh": result.estimated_additional_energy_needed_kwh,
            "recommendation": result.recommendation,
            "used_ml": result.used_ml,
            "ml_segment_count": result.ml_segment_count,
            "heuristic_segment_count": result.heuristic_segment_count,
            "model_version": result.model_version,
        }


if __name__ == "__main__":
    from pathlib import Path

    from app.core.energy_model import get_vehicle_by_id
    from app.core.route_energy_simulator import RouteEnergySimulator
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
        start_soc_pct=40.0,
    )

    analyzer = ChargeNeedAnalyzer()
    analysis = analyzer.analyze(
        simulation=simulation,
        usable_battery_kwh=vehicle.usable_battery_kwh,
        reserve_soc_pct=vehicle.routing_reserve_soc_pct,
    )

    print("=== CHARGE NEED ANALYSIS ===")
    print("Charging required:", analysis.charging_required)
    print("Start SOC (%):", analysis.start_soc_pct)
    print("End SOC (%):", analysis.end_soc_pct)
    print("Minimum SOC (%):", analysis.minimum_soc_pct)
    print("Critical segment:", analysis.critical_segment_no)
    print("Extra SOC needed (%):", analysis.estimated_additional_soc_needed_pct)
    print("Extra energy needed (kWh):", analysis.estimated_additional_energy_needed_kwh)
    print("Used ML:", analysis.used_ml)
    print("ML segment count:", analysis.ml_segment_count)
    print("Heuristic segment count:", analysis.heuristic_segment_count)
    print("Model version:", analysis.model_version)
    print("Recommendation:", analysis.recommendation)