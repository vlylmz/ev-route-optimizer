"""
GET /geocode?q=Ankara — yer adı → koordinat (Nominatim / OSM).

Frontend autocomplete için.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_geocoding_service
from app.api.schemas import GeocodeResponse, GeocodeResultItem
from app.services.geocoding_service import (
    GeocodingServiceError,
    NominatimGeocodingService,
)

router = APIRouter(tags=["geocode"])


@router.get(
    "/geocode",
    response_model=GeocodeResponse,
    summary="Yer adı arama (Nominatim/OSM, varsayılan TR)",
    responses={502: {"description": "Nominatim hatası"}},
)
def geocode_search(
    q: str = Query(..., min_length=2, description="Aranacak yer adı"),
    limit: int = Query(5, ge=1, le=15),
    service: NominatimGeocodingService = Depends(get_geocoding_service),
) -> GeocodeResponse:
    try:
        results = service.search(query=q, limit=limit)
    except GeocodingServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Geocode error: {exc}",
        ) from exc

    return GeocodeResponse(
        query=q,
        results=[
            GeocodeResultItem(
                display_name=r.display_name,
                name=r.name,
                lat=r.lat,
                lon=r.lon,
                type=r.type,
                importance=r.importance,
                country_code=r.country_code,
            )
            for r in results
        ],
    )
