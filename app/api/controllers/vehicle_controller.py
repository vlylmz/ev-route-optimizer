"""
Araç veritabanı endpoint'leri — liste ve tekil okuma.
"""

from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_vehicles_lookup
from app.api.schemas import VehicleDetail, VehicleSummary
from app.core.energy_model import Vehicle

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def _to_summary(v: Vehicle) -> VehicleSummary:
    return VehicleSummary(
        id=v.id,
        name=v.full_name,
        make=v.make,
        model=v.model,
        variant=v.variant,
        year=v.year,
        body_type=v.body_type,
        usable_battery_kwh=v.usable_battery_kwh,
        ideal_consumption_wh_km=v.ideal_consumption_wh_km,
        wltp_range_km=v.wltp_range_km,
        max_dc_charge_kw=v.max_dc_charge_kw,
    )


def _to_detail(v: Vehicle) -> VehicleDetail:
    return VehicleDetail(
        id=v.id,
        name=v.full_name,
        make=v.make,
        model=v.model,
        variant=v.variant,
        year=v.year,
        body_type=v.body_type,
        usable_battery_kwh=v.usable_battery_kwh,
        ideal_consumption_wh_km=v.ideal_consumption_wh_km,
        wltp_range_km=v.wltp_range_km,
        max_dc_charge_kw=v.max_dc_charge_kw,
        drivetrain=v.drivetrain,
        battery_chemistry=v.battery_chemistry,
        gross_battery_kwh=v.gross_battery_kwh,
        soc_min_pct=v.soc_min_pct,
        soc_max_pct=v.soc_max_pct,
        regen_efficiency=v.regen_efficiency,
        weight_kg=v.weight_kg,
        max_ac_charge_kw=v.max_ac_charge_kw,
        temp_penalty_factor=v.temp_penalty_factor,
        charge_curve_hint=v.charge_curve_hint,
        default_hvac_load_kw=v.default_hvac_load_kw,
    )


@router.get(
    "",
    response_model=List[VehicleSummary],
    summary="Tüm araç özetlerini listele",
)
def list_vehicles(
    vehicles: Dict[str, Vehicle] = Depends(get_vehicles_lookup),
) -> List[VehicleSummary]:
    return [_to_summary(v) for v in vehicles.values()]


@router.get(
    "/{vehicle_id}",
    response_model=VehicleDetail,
    responses={404: {"description": "Araç bulunamadı"}},
    summary="Tek bir aracın tüm teknik detaylarını döner",
)
def get_vehicle(
    vehicle_id: str,
    vehicles: Dict[str, Vehicle] = Depends(get_vehicles_lookup),
) -> VehicleDetail:
    vehicle = vehicles.get(vehicle_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle '{vehicle_id}' not found",
        )
    return _to_detail(vehicle)
