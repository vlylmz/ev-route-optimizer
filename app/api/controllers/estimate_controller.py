"""
Segment bazlı enerji tüketim tahmini endpoint'i.

ModelService:
- Model yüklenmişse ML tahmini
- Değilse / hata verirse heuristic fallback
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_model_service, get_vehicles_lookup
from app.api.schemas import EstimateRequest, EstimateResponse
from app.core.energy_model import Vehicle
from ml.model_service import ModelService

router = APIRouter(tags=["estimate"])


def _vehicle_to_model_payload(vehicle: Vehicle) -> Dict[str, Any]:
    return {
        "id": vehicle.id,
        "vehicle_id": vehicle.id,
        "name": vehicle.full_name,
        "ideal_consumption_wh_km": vehicle.ideal_consumption_wh_km,
        "temp_penalty_factor": vehicle.temp_penalty_factor,
        "usable_battery_kwh": vehicle.usable_battery_kwh,
    }


@router.post(
    "/estimate-consumption",
    response_model=EstimateResponse,
    responses={404: {"description": "Araç bulunamadı"}},
    summary="Segment bazında enerji tüketimi tahmini (ML veya formül fallback)",
)
def estimate_consumption(
    req: EstimateRequest,
    vehicles: Dict[str, Vehicle] = Depends(get_vehicles_lookup),
    model_service: ModelService = Depends(get_model_service),
) -> EstimateResponse:
    vehicle = vehicles.get(req.vehicle_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle '{req.vehicle_id}' not found",
        )

    segment_payload = req.segment.model_dump(exclude_none=False)
    weather_payload = (
        req.weather.model_dump(exclude_none=False) if req.weather else None
    )

    result = model_service.predict_segment_energy(
        segment=segment_payload,
        vehicle=_vehicle_to_model_payload(vehicle),
        weather=weather_payload,
    )

    features = result.get("features") or {}
    if is_dataclass(features):
        features = asdict(features)

    return EstimateResponse(
        vehicle_id=vehicle.id,
        source=str(result.get("source", "unknown")),
        used_model=bool(result.get("used_model", False)),
        predicted_energy_kwh=float(result.get("predicted_energy_kwh", 0.0)),
        fallback_energy_kwh=float(result.get("fallback_energy_kwh", 0.0)),
        model_version=result.get("model_version"),
        features=features,
        error=result.get("error"),
    )
