"""
POST /charging-curve — vehicle + station_kw için zaman bazlı şarj seansı
simulasyonu döndürür (frontend grafik için).
"""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_vehicles_lookup
from app.api.schemas import (
    ChargingCurvePoint,
    ChargingCurveRequest,
    ChargingCurveResponse,
)
from app.core.energy_model import Vehicle
from app.services.charging_curve_service import ChargingCurveService

router = APIRouter(tags=["charging-curve"])

_service = ChargingCurveService()


@router.post(
    "/charging-curve",
    response_model=ChargingCurveResponse,
    summary="Vehicle + station gücü için SOC bazlı şarj eğrisi",
    responses={404: {"description": "Araç bulunamadı"}},
)
def compute_curve(
    req: ChargingCurveRequest,
    vehicles: Dict[str, Vehicle] = Depends(get_vehicles_lookup),
) -> ChargingCurveResponse:
    vehicle = vehicles.get(req.vehicle_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle '{req.vehicle_id}' not found",
        )

    points = _service.simulate_session(
        vehicle=vehicle,
        station_kw=req.station_kw,
        start_soc_pct=req.start_soc_pct,
        target_soc_pct=req.target_soc_pct,
        usable_battery_kwh=float(vehicle.usable_battery_kwh),
    )
    total_minutes = points[-1]["time_min"] if points else 0.0
    soc_delta = max(req.target_soc_pct - req.start_soc_pct, 0.0)
    energy_kwh = round(soc_delta / 100.0 * float(vehicle.usable_battery_kwh), 2)

    return ChargingCurveResponse(
        vehicle_id=vehicle.id,
        station_kw=req.station_kw,
        start_soc_pct=req.start_soc_pct,
        target_soc_pct=req.target_soc_pct,
        total_minutes=round(total_minutes, 1),
        energy_kwh=energy_kwh,
        points=[ChargingCurvePoint(**p) for p in points],
    )
