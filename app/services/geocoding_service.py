"""
OSM Nominatim ile ücretsiz, anahtarsız geocoding (yer adı → koordinat).

Kullanım kuralları:
- User-Agent zorunlu
- Saniyede 1'den fazla istek atma (Nominatim rate limit)
- Production'da kendi Nominatim sunucusu önerilir, akademik proje için ücretsiz halka açık iyidir.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional

import requests


@dataclass
class GeocodeResult:
    display_name: str
    name: str
    lat: float
    lon: float
    type: Optional[str]
    importance: float
    country_code: Optional[str]


class GeocodingServiceError(Exception):
    pass


class NominatimGeocodingService:
    """OSM Nominatim ile yer adı sorgular."""

    def __init__(
        self,
        base_url: str = "https://nominatim.openstreetmap.org",
        timeout: int = 15,
        user_agent: str = "ev-route-optimizer/0.7 (academic project)",
        country_codes: str = "tr",  # sadece Türkiye sonuçları
        min_request_interval: float = 1.05,  # Nominatim 1/saniye limiti
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        self.country_codes = country_codes
        self.min_request_interval = min_request_interval
        self._last_call = 0.0
        self._lock = Lock()

    def _throttle(self) -> None:
        """Nominatim rate-limit için minimum bekleme uygula."""
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
            self._last_call = time.time()

    def search(
        self,
        query: str,
        limit: int = 5,
    ) -> List[GeocodeResult]:
        """Yer adı sorgular, en alakalı `limit` adet sonucu döndürür."""
        if not query or not query.strip():
            return []

        self._throttle()

        params: Dict[str, Any] = {
            "q": query.strip(),
            "format": "json",
            "addressdetails": 1,
            "limit": limit,
            "accept-language": "tr",
        }
        if self.country_codes:
            params["countrycodes"] = self.country_codes

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        try:
            resp = requests.get(
                f"{self.base_url}/search",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise GeocodingServiceError(f"Nominatim isteği başarısız: {exc}") from exc

        if not isinstance(data, list):
            return []

        results: List[GeocodeResult] = []
        for item in data:
            try:
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
            except (TypeError, ValueError):
                continue

            address = item.get("address") or {}
            country_code = address.get("country_code")

            # Kısa ad: city/town/village/suburb varsa onu kullan
            name = (
                address.get("city")
                or address.get("town")
                or address.get("village")
                or address.get("suburb")
                or address.get("road")
                or item.get("display_name", "").split(",")[0]
            )

            results.append(
                GeocodeResult(
                    display_name=item.get("display_name", ""),
                    name=name,
                    lat=lat,
                    lon=lon,
                    type=item.get("type"),
                    importance=float(item.get("importance", 0.0)),
                    country_code=country_code,
                )
            )

        return results

    def reverse(self, lat: float, lon: float) -> Optional[GeocodeResult]:
        """Koordinat → adres."""
        self._throttle()

        params: Dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "addressdetails": 1,
            "accept-language": "tr",
        }
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        try:
            resp = requests.get(
                f"{self.base_url}/reverse",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise GeocodingServiceError(f"Nominatim reverse hatası: {exc}") from exc

        if not isinstance(data, dict) or "lat" not in data:
            return None

        address = data.get("address") or {}
        name = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("suburb")
            or data.get("display_name", "").split(",")[0]
        )
        try:
            return GeocodeResult(
                display_name=data.get("display_name", ""),
                name=name,
                lat=float(data["lat"]),
                lon=float(data["lon"]),
                type=data.get("type"),
                importance=float(data.get("importance", 0.0)),
                country_code=address.get("country_code"),
            )
        except (TypeError, ValueError):
            return None
