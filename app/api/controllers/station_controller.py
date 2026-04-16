"""
Şarj istasyonu listeleme — belirli bir koordinat etrafında
Open Charge Map verisini döner (fallback ile).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_charging_service
from app.api.schemas import StationConnection, StationSummary
from app.services.charging_service import (
    ChargingServiceError,
    OpenChargeMapService,
)

router = APIRouter(tags=["stations"])


def _to_station_summary(station_dict: dict) -> StationSummary:
    connections_raw = station_dict.get("connections") or []
    return StationSummary(
        ocm_id=int(station_dict.get("ocm_id", 0)),
        name=str(station_dict.get("name", "")),
        operator=station_dict.get("operator"),
        address=str(station_dict.get("address", "")),
        town=station_dict.get("town"),
        latitude=float(station_dict.get("latitude", 0.0)),
        longitude=float(station_dict.get("longitude", 0.0)),
        distance_km=station_dict.get("distance_km"),
        number_of_points=station_dict.get("number_of_points"),
        is_operational=station_dict.get("is_operational"),
        connections=[StationConnection(**c) for c in connections_raw],
    )


@router.get(
    "/stations",
    response_model=List[StationSummary],
    summary="Belirli bir koordinat etrafındaki şarj istasyonlarını döner",
)
def list_stations(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    distance_km: float = Query(10.0, gt=0.0, le=100.0),
    max_results: int = Query(20, gt=0, le=200),
    allow_fallback: bool = Query(True),
    service: OpenChargeMapService = Depends(get_charging_service),
) -> List[StationSummary]:
    try:
        station_dicts = service.get_nearby_stations_dict(
            coord=(lat, lon),
            distance_km=distance_km,
            max_results=max_results,
            allow_fallback=allow_fallback,
        )
    except ChargingServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Station lookup failed: {exc}",
        ) from exc

    return [_to_station_summary(s) for s in station_dicts]
