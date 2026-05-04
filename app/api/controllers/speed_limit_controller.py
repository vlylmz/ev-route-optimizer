"""
Rota geometrisi için segment bazlı hız limiti endpoint'i.

POST /speed-limits  — { geometry: [[lat,lon], ...], sample_every_n_points }
Dönüş: segments[] (start_index, end_index, maxspeed_kmh, highway)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_speed_limit_service
from app.api.schemas import (
    SpeedLimitsRequest,
    SpeedLimitsResponse,
    SpeedLimitSegment as SpeedLimitSegmentSchema,
)
from app.services.speed_limit_service import (
    OverpassSpeedLimitService,
    SpeedLimitServiceError,
)

router = APIRouter(tags=["speed-limits"])


@router.post(
    "/speed-limits",
    response_model=SpeedLimitsResponse,
    summary="Rota üzerindeki hız limitlerini OSM (Overpass) ile tahmin eder",
    responses={502: {"description": "Overpass servisinde hata"}},
)
def get_speed_limits(
    req: SpeedLimitsRequest,
    service: OverpassSpeedLimitService = Depends(get_speed_limit_service),
) -> SpeedLimitsResponse:
    geometry = [(p[0], p[1]) for p in req.geometry if len(p) >= 2]
    if len(geometry) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="geometry en az 2 nokta içermeli.",
        )

    try:
        segments, source = service.get_segments(
            geometry=geometry,
            sample_every_n_points=req.sample_every_n_points,
        )
    except SpeedLimitServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Speed limit service error: {exc}",
        ) from exc

    sampled_count = len(
        {s.start_index for s in segments}
    )

    return SpeedLimitsResponse(
        segments=[
            SpeedLimitSegmentSchema(
                start_index=s.start_index,
                end_index=s.end_index,
                maxspeed_kmh=s.maxspeed_kmh,
                highway=s.highway,
            )
            for s in segments
        ],
        source=source,
        sampled_point_count=sampled_count,
    )
