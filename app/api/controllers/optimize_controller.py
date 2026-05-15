"""
Uçtan uca rota planlama endpoint'i:

route_context -> simulate -> charge_need -> route_profiles

Tek istekte "fast", "efficient", "balanced" profillerini dönmek
için core servisleri orkestre eder.
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
from app.services.tariff_service import TariffService
from app.api.schemas import (
    OptimizeRequest,
    OptimizeResponse,
    ProfileCard,
    RecommendedStop,
)
from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.energy_model import Vehicle
from app.core.route_energy_simulator import RouteEnergySimulator
from app.core.route_profiles import RouteProfiles
from app.services.route_context_service import (
    RouteContextService,
    RouteContextServiceError,
)

router = APIRouter(tags=["optimize"])


def _dataclass_to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


def _vehicle_to_dict(vehicle: Vehicle) -> Dict[str, Any]:
    return {
        "id": vehicle.id,
        "vehicle_id": vehicle.id,
        "name": vehicle.full_name,
        "usable_battery_kwh": vehicle.usable_battery_kwh,
        "ideal_consumption_wh_km": vehicle.ideal_consumption_wh_km,
        "max_dc_charge_kw": vehicle.max_dc_charge_kw,
        "max_dc_charge_power_kw": vehicle.max_dc_charge_kw,
        "temp_penalty_factor": vehicle.temp_penalty_factor,
        "soc_min_pct": vehicle.soc_min_pct,
        "soc_max_pct": vehicle.soc_max_pct,
        "charge_curve_hint": vehicle.charge_curve_hint,
        "battery_chemistry": vehicle.battery_chemistry,
        "dc_connectors": list(vehicle.dc_connectors),
        "ac_connectors": list(vehicle.ac_connectors),
    }


def _build_profile_cards(
    profile_result: Dict[str, Any],
    *,
    usable_battery_kwh: float,
    tariff: TariffService,
) -> List[ProfileCard]:
    cards: List[ProfileCard] = []
    raw_cards = profile_result.get("profile_cards") or []
    profiles = profile_result.get("profiles") or {}

    for card in raw_cards:
        key = card.get("key")
        profile = profiles.get(key, {})
        summary = profile.get("summary") or {}
        ml_summary = profile.get("ml_summary") or {}
        stops_raw = profile.get("recommended_stops") or []

        recommended_stops: List[RecommendedStop] = []
        total_cost_try = 0.0
        for s in stops_raw:
            try:
                arrival = float(s.get("arrival_soc_percent", 0.0) or 0.0)
                target = float(s.get("target_soc_percent", 0.0) or 0.0)
                power_kw = float(s.get("power_kw", 0.0) or 0.0)
                operator = s.get("operator")
                is_dc = bool(s.get("is_dc", power_kw >= 50.0))

                # Tahmini eklenen enerji (durakta + transfer kayıpları için ~85% verim)
                soc_delta = max(target - arrival, 0.0)
                energy_kwh = round(
                    soc_delta / 100.0 * usable_battery_kwh / 0.85, 2
                )
                cost_try = tariff.estimate_stop_cost(
                    operator=operator, kwh=energy_kwh, is_dc=is_dc
                )
                total_cost_try += cost_try

                recommended_stops.append(
                    RecommendedStop(
                        name=str(s.get("name", "İstasyon")),
                        operator=operator,
                        distance_along_route_km=float(
                            s.get("distance_along_route_km", 0.0) or 0.0
                        ),
                        detour_distance_km=float(
                            s.get("detour_distance_km", 0.0) or 0.0
                        ),
                        detour_minutes=float(s.get("detour_minutes", 0.0) or 0.0),
                        arrival_soc_percent=arrival,
                        target_soc_percent=target,
                        charge_minutes=float(s.get("charge_minutes", 0.0) or 0.0),
                        power_kw=power_kw,
                        is_dc=is_dc,
                        energy_kwh=energy_kwh,
                        cost_try=cost_try,
                    )
                )
            except (TypeError, ValueError):
                continue

        cards.append(
            ProfileCard(
                key=key,
                label=card.get("label") or key,
                feasible=bool(card.get("feasible", False)),
                total_energy_kwh=card.get("total_energy_kwh"),
                total_trip_minutes=card.get("total_trip_minutes"),
                charging_minutes=card.get("charge_minutes"),
                stop_count=card.get("stop_count"),
                final_soc_pct=card.get("arrival_soc_percent"),
                used_ml=bool(ml_summary.get("used_ml", card.get("used_ml", False))),
                model_version=ml_summary.get("model_version"),
                recommended_stops=recommended_stops,
                total_cost_try=round(total_cost_try, 2),
                raw={
                    "summary": summary,
                    "ml_summary": ml_summary,
                    "status": profile.get("status"),
                },
            )
        )
    return cards


@router.post(
    "/optimize",
    response_model=OptimizeResponse,
    responses={
        404: {"description": "Araç bulunamadı"},
        502: {"description": "Dış servis hatası"},
    },
    summary="Uçtan uca rota planı: 3 profil (fast/efficient/balanced)",
)
def optimize_route(
    req: OptimizeRequest,
    vehicles: Dict[str, Vehicle] = Depends(get_vehicles_lookup),
    route_context_service: RouteContextService = Depends(get_route_context_service),
    simulator: RouteEnergySimulator = Depends(get_route_energy_simulator),
    analyzer: ChargeNeedAnalyzer = Depends(get_charge_need_analyzer),
    profiles_engine: RouteProfiles = Depends(get_route_profiles),
    tariff: TariffService = Depends(get_tariff_service),
) -> OptimizeResponse:
    vehicle = vehicles.get(req.vehicle_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle '{req.vehicle_id}' not found",
        )

    # 1) Rota bağlamı
    try:
        route_context = route_context_service.build_route_context(
            start=req.start.as_tuple(),
            end=req.end.as_tuple(),
            elevation_min_spacing_km=req.elevation_min_spacing_km,
            elevation_max_points=req.elevation_max_points,
            station_distance_km=req.station_distance_km,
        )
    except RouteContextServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Route context build failed: {exc}",
        ) from exc

    # 2) Enerji simülasyonu
    try:
        simulation = simulator.simulate(
            vehicle=vehicle,
            route_context=route_context,
            start_soc_pct=req.initial_soc_pct,
            use_ml=req.use_ml,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {exc}",
        ) from exc

    reserve_soc_pct = max(float(vehicle.soc_min_pct), float(req.min_soc_floor_pct))

    # 3) Şarj ihtiyacı analizi
    try:
        charge_need = analyzer.analyze(
            simulation=simulation,
            usable_battery_kwh=vehicle.usable_battery_kwh,
            reserve_soc_pct=reserve_soc_pct,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Charge need analysis failed: {exc}",
        ) from exc

    simulation_dict = _dataclass_to_dict(simulation)
    charge_need_dict = _dataclass_to_dict(charge_need)
    vehicle_dict = _vehicle_to_dict(vehicle)

    # Kullanıcının varış SOC tercihi: planlamada ayrı bir alan olarak iletilir.
    # Planner reserve_soc'u in-trip floor olarak kullanır,
    # target_arrival_soc_pct'i ise varışta ayrı kontrol eder.
    if req.target_arrival_soc_pct is not None:
        charge_need_dict["target_arrival_soc_pct"] = float(req.target_arrival_soc_pct)

    # Min duraklama süresi (kullanıcı 1-2 dk için durmaz). Planner attribute'una uygula.
    _planner = getattr(profiles_engine, "charging_planner", None)
    if _planner is not None:
        try:
            _planner.min_stop_minutes = float(req.min_stop_minutes)
        except AttributeError:
            pass  # Test fixture'larda planner yok / değiştirilemez olabilir
        try:
            _planner.min_soc_floor_pct = float(req.min_soc_floor_pct)
        except AttributeError:
            pass
        if req.max_stops is not None:
            try:
                _planner.max_stops = int(req.max_stops)
            except AttributeError:
                pass
        if req.energy_buffer_factor is not None:
            try:
                _planner.energy_buffer_factor = float(req.energy_buffer_factor)
            except AttributeError:
                pass

    # 4) Profiller (her strateji icin yeniden simulate -> hiz profili enerjiye yansir)
    try:
        profile_result = profiles_engine.generate_profiles(
            vehicle=vehicle_dict,
            route_context=route_context,
            simulation_result=simulation_dict,
            charge_need=charge_need_dict,
            strategies=req.strategies,
            simulator=simulator,
            analyzer=analyzer,
            vehicle_obj=vehicle,
            initial_soc=req.initial_soc_pct,
            use_ml=req.use_ml,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile generation failed: {exc}",
        ) from exc

    cards = _build_profile_cards(
        profile_result,
        usable_battery_kwh=float(vehicle.usable_battery_kwh),
        tariff=tariff,
    )

    return OptimizeResponse(
        status=str(profile_result.get("status", "unknown")),
        vehicle_id=vehicle.id,
        vehicle_name=vehicle.full_name,
        initial_soc_pct=float(simulation.start_soc_pct),
        final_soc_pct=float(simulation.end_soc_pct),
        total_distance_km=float(simulation.total_distance_km),
        total_energy_kwh=float(simulation.total_energy_kwh),
        used_ml=bool(simulation.used_ml),
        ml_segment_count=int(simulation.ml_segment_count),
        heuristic_segment_count=int(simulation.heuristic_segment_count),
        model_version=simulation.model_version,
        recommended_profile=profile_result.get("recommended_profile"),
        profiles=cards,
        raw_optimization={
            "best_by_time": profile_result.get("best_by_time"),
            "best_by_energy": profile_result.get("best_by_energy"),
            "any_profile_used_ml": profile_result.get("any_profile_used_ml", False),
            "message": profile_result.get("message"),
        },
    )
