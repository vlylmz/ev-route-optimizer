"""
GET /geocode?q=Ankara — yer adı → koordinat (Nominatim / OSM).
GET /reverse-geocode?lat=...&lon=... — koordinat → yer adı.

Frontend autocomplete + sim icin canli konum etiketi.
"""

from __future__ import annotations

from typing import Optional

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


@router.get(
    "/reverse-geocode",
    response_model=Optional[GeocodeResultItem],
    summary="Koordinat -> yer adi (Nominatim/OSM reverse)",
    responses={502: {"description": "Nominatim hatası"}},
)
def reverse_geocode(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
    service: NominatimGeocodingService = Depends(get_geocoding_service),
) -> Optional[GeocodeResultItem]:
    try:
        result = service.reverse(lat=lat, lon=lon)
    except GeocodingServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Reverse geocode error: {exc}",
        ) from exc

    if result is None:
        return None
    return GeocodeResultItem(
        display_name=result.display_name,
        name=result.name,
        lat=result.lat,
        lon=result.lon,
        type=result.type,
        importance=result.importance,
        country_code=result.country_code,
    )
