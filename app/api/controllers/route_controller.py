"""
Rota bağlamı endpoint'i — OSRM + elevation + hava + istasyon
tek bir route context içinde döner.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_route_context_service
from app.api.schemas import RouteRequest, RouteResponse, RouteSummary
from app.core.geo_utils import build_route_points
from app.services.route_context_service import (
    RouteContextService,
    RouteContextServiceError,
)

router = APIRouter(tags=["route"])


@router.post(
    "/route",
    response_model=RouteResponse,
    responses={502: {"description": "Dış servis hatası"}},
    summary="İki nokta arasında rota + eğim + hava + istasyon verisini hesapla",
)
def build_route(
    req: RouteRequest,
    service: RouteContextService = Depends(get_route_context_service),
) -> RouteResponse:
    try:
        context = service.build_route_context(
            start=req.start.as_tuple(),
            end=req.end.as_tuple(),
            elevation_min_spacing_km=req.elevation_min_spacing_km,
            elevation_max_points=req.elevation_max_points,
            weather_sample_limit=req.weather_sample_limit,
            station_query_every_n_points=req.station_query_every_n_points,
            station_distance_km=req.station_distance_km,
            station_max_results_per_query=req.station_max_results_per_query,
            allow_station_fallback=req.allow_station_fallback,
        )
    except RouteContextServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Route context build failed: {exc}",
        ) from exc

    summary = RouteSummary(**context["summary"])
    geometry = context["route"].get("geometry", [])

    # Frontend tekrar haversine sum yapmamali: kumulatif mesafeyi tek noktada hesapla.
    route_points = build_route_points(geometry)
    cumulative_distances = [p.cumulative_distance_km for p in route_points]

    return RouteResponse(
        summary=summary,
        geometry=geometry,
        cumulative_distances=cumulative_distances,
        elevation_profile=context["elevation"].get("elevation_profile", []),
        slope_segments=context["elevation"].get("slope_segments", []),
        weather=context.get("weather", {}),
        stations=context.get("stations", []),
    )
