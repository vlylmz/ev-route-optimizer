"""
A/B araç karşılaştırma — aynı rotayı 2-4 araçla aynı strateji ile
planlar ve özet metrikleri döndürür.

POST /compare-vehicles
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_charge_need_analyzer,
    get_route_context_service,
    get_route_energy_simulator,
    get_route_profiles,
    get_tariff_service,
    get_vehicles_lookup,
)
from app.api.schemas import (
    CompareVehiclesRequest,
    CompareVehiclesResponse,
    VehicleComparisonRow,
)
from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.energy_model import Vehicle
from app.core.route_energy_simulator import RouteEnergySimulator
from app.core.route_profiles import RouteProfiles
from app.services.route_context_service import (
    RouteContextService,
    RouteContextServiceError,
)
from app.services.tariff_service import TariffService

router = APIRouter(tags=["compare"])


def _to_plain(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    return obj


def _vehicle_to_dict(v: Vehicle) -> Dict[str, Any]:
    return {
        "id": v.id,
        "vehicle_id": v.id,
        "name": v.full_name,
        "usable_battery_kwh": v.usable_battery_kwh,
        "ideal_consumption_wh_km": v.ideal_consumption_wh_km,
        "max_dc_charge_kw": v.max_dc_charge_kw,
        "max_dc_charge_power_kw": v.max_dc_charge_kw,
        "temp_penalty_factor": v.temp_penalty_factor,
    }


@router.post(
    "/compare-vehicles",
    response_model=CompareVehiclesResponse,
    summary="A/B araç karşılaştırma — aynı rota üzerinde 2-4 araç",
)
def compare_vehicles(
    req: CompareVehiclesRequest,
    vehicles: Dict[str, Vehicle] = Depends(get_vehicles_lookup),
    route_context_service: RouteContextService = Depends(get_route_context_service),
    simulator: RouteEnergySimulator = Depends(get_route_energy_simulator),
    analyzer: ChargeNeedAnalyzer = Depends(get_charge_need_analyzer),
    profiles_engine: RouteProfiles = Depends(get_route_profiles),
    tariff: TariffService = Depends(get_tariff_service),
) -> CompareVehiclesResponse:
    # Rota her araç için aynı; tek seferlik route context
    try:
        route_context = route_context_service.build_route_context(
            start=req.start.as_tuple(),
            end=req.end.as_tuple(),
        )
    except RouteContextServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Route build: {exc}") from exc

    rows: List[VehicleComparisonRow] = []

    for vid in req.vehicle_ids:
        vehicle = vehicles.get(vid)
        if vehicle is None:
            rows.append(
                VehicleComparisonRow(
                    vehicle_id=vid,
                    vehicle_name=vid,
                    feasible=False,
                    total_distance_km=0.0,
                    total_energy_kwh=0.0,
                    total_trip_minutes=0.0,
                    charging_minutes=0.0,
                    stop_count=0,
                    final_soc_pct=0.0,
                    total_cost_try=0.0,
                    error="Araç bulunamadı",
                )
            )
            continue

        try:
            simulation = simulator.simulate(
                vehicle=vehicle,
                route_context=route_context,
                start_soc_pct=req.initial_soc_pct,
                use_ml=req.use_ml,
            )
            charge_need = analyzer.analyze(
                simulation=simulation,
                usable_battery_kwh=vehicle.usable_battery_kwh,
                reserve_soc_pct=float(vehicle.soc_min_pct),
            )

            simulation_dict = _to_plain(simulation)
            charge_need_dict = _to_plain(charge_need)

            if req.target_arrival_soc_pct is not None:
                charge_need_dict["target_arrival_soc_pct"] = float(
                    req.target_arrival_soc_pct
                )

            profile_result = profiles_engine.generate_profiles(
                vehicle=_vehicle_to_dict(vehicle),
                route_context=route_context,
                simulation_result=simulation_dict,
                charge_need=charge_need_dict,
                strategies=[req.strategy],
            )

            profile = (profile_result.get("profiles") or {}).get(req.strategy, {})
            summary = profile.get("summary") or {}
            stops_raw = profile.get("recommended_stops") or []

            # Toplam maliyet
            total_cost_try = 0.0
            for s in stops_raw:
                try:
                    arrival = float(s.get("arrival_soc_percent", 0.0) or 0.0)
                    target = float(s.get("target_soc_percent", 0.0) or 0.0)
                    power_kw = float(s.get("power_kw", 0.0) or 0.0)
                    operator = s.get("operator")
                    is_dc = bool(s.get("is_dc", power_kw >= 50.0))
                    soc_delta = max(target - arrival, 0.0)
                    energy_kwh = (
                        soc_delta / 100.0 * vehicle.usable_battery_kwh / 0.85
                    )
                    total_cost_try += tariff.estimate_stop_cost(
                        operator=operator, kwh=energy_kwh, is_dc=is_dc
                    )
                except (TypeError, ValueError):
                    continue

            rows.append(
                VehicleComparisonRow(
                    vehicle_id=vehicle.id,
                    vehicle_name=vehicle.full_name,
                    feasible=bool(profile.get("feasible", False)),
                    total_distance_km=float(simulation.total_distance_km),
                    total_energy_kwh=float(
                        summary.get("total_energy_kwh", simulation.total_energy_kwh)
                        or 0.0
                    ),
                    total_trip_minutes=float(
                        summary.get("total_trip_minutes", 0.0) or 0.0
                    ),
                    charging_minutes=float(summary.get("charge_minutes", 0.0) or 0.0),
                    stop_count=int(summary.get("stop_count", 0) or 0),
                    final_soc_pct=float(
                        summary.get("projected_arrival_soc_percent", 0.0) or 0.0
                    ),
                    total_cost_try=round(total_cost_try, 2),
                )
            )

        except Exception as exc:  # noqa: BLE001
            rows.append(
                VehicleComparisonRow(
                    vehicle_id=vehicle.id,
                    vehicle_name=vehicle.full_name,
                    feasible=False,
                    total_distance_km=0.0,
                    total_energy_kwh=0.0,
                    total_trip_minutes=0.0,
                    charging_minutes=0.0,
                    stop_count=0,
                    final_soc_pct=0.0,
                    total_cost_try=0.0,
                    error=str(exc),
                )
            )

    feasible_rows = [r for r in rows if r.feasible]

    def _arg_min(rows_, key):
        if not rows_:
            return None
        return min(rows_, key=key).vehicle_id

    cheapest = _arg_min(feasible_rows, lambda r: r.total_cost_try)
    fastest = _arg_min(feasible_rows, lambda r: r.total_trip_minutes)
    efficient = _arg_min(feasible_rows, lambda r: r.total_energy_kwh)

    return CompareVehiclesResponse(
        rows=rows,
        cheapest_vehicle_id=cheapest,
        fastest_vehicle_id=fastest,
        most_efficient_vehicle_id=efficient,
    )
