from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


Coordinate = Tuple[float, float]  # (lat, lon)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ChargingServiceError(Exception):
    pass


@dataclass
class ChargingConnection:
    connection_type: Optional[str]
    power_kw: Optional[float]
    current_type: Optional[str]
    quantity: Optional[int]
    is_fast_charge_capable: Optional[bool]
    status: Optional[str]


@dataclass
class ChargingStation:
    ocm_id: int
    uuid: Optional[str]
    name: str
    operator: Optional[str]
    usage_type: Optional[str]
    usage_cost: Optional[str]
    address: str
    town: Optional[str]
    latitude: float
    longitude: float
    distance_km: Optional[float]
    number_of_points: Optional[int]
    status: Optional[str]
    is_operational: Optional[bool]
    connections: List[ChargingConnection]
    raw: Dict[str, Any]


class OpenChargeMapService:
    def __init__(
        self,
        base_url: str = "https://api.openchargemap.io/v3",
        api_key: Optional[str] = None,
        timeout: int = 20,
        user_agent: str = "ev-route-optimizer/0.1",
        fallback_file: str | Path | None = None,
        tr_cache_file: str | Path | None = None,
        debug: bool = True,
    ) -> None:
        raw_key = api_key or os.getenv("OCM_API_KEY")
        self.api_key = raw_key.strip() if raw_key else None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        self.debug = debug
        self.fallback_file = (
            Path(fallback_file)
            if fallback_file
            else Path("app/data/sample_stations.json")
        )
        # TR-wide önbellek: scripts/fetch_all_tr_stations.py'nin çıktısı.
        # Live API hata verdiğinde önce buradan filtreleyerek istasyon döndürürüz.
        self.tr_cache_file = (
            Path(tr_cache_file)
            if tr_cache_file
            else Path("app/data/all_tr_stations.json")
        )
        self._tr_cache_stations: Optional[List[ChargingStation]] = None

        # Circuit breaker:
        # İlk canlı API başarısız olursa aynı çalışmada tekrar zorlamayız.
        self.live_api_available = True

    @staticmethod
    def _validate_coordinate(coord: Coordinate) -> None:
        lat, lon = coord
        if not (-90 <= lat <= 90):
            raise ValueError(f"Geçersiz latitude: {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Geçersiz longitude: {lon}")

    @staticmethod
    def _build_address(address_info: Dict[str, Any]) -> str:
        parts = [
            address_info.get("Title"),
            address_info.get("AddressLine1"),
            address_info.get("AddressLine2"),
            address_info.get("Town"),
            address_info.get("StateOrProvince"),
            address_info.get("Postcode"),
        ]
        return ", ".join(str(p).strip() for p in parts if p)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _redact_params(params: Dict[str, Any]) -> Dict[str, Any]:
        safe = dict(params)
        if "key" in safe:
            safe["key"] = "***REDACTED***"
        return safe

    def _debug_print(self, message: str) -> None:
        if self.debug:
            print(message)

    @staticmethod
    def _normalize_connection(item: Dict[str, Any]) -> ChargingConnection:
        connection_type = None
        if item.get("ConnectionType"):
            connection_type = (
                item["ConnectionType"].get("Title")
                or item["ConnectionType"].get("FormalName")
                or item["ConnectionType"].get("Description")
            )

        current_type = None
        if item.get("CurrentType"):
            current_type = (
                item["CurrentType"].get("Title")
                or item["CurrentType"].get("Description")
            )

        status = None
        if item.get("StatusType"):
            status = (
                item["StatusType"].get("Title")
                or item["StatusType"].get("Description")
            )

        level = item.get("Level") or {}
        is_fast_charge_capable = None
        if isinstance(level, dict):
            is_fast_charge_capable = level.get("IsFastChargeCapable")

        return ChargingConnection(
            connection_type=connection_type,
            power_kw=OpenChargeMapService._safe_float(item.get("PowerKW")),
            current_type=current_type,
            quantity=OpenChargeMapService._safe_int(item.get("Quantity")),
            is_fast_charge_capable=is_fast_charge_capable,
            status=status,
        )

    def _normalize_station(self, item: Dict[str, Any]) -> ChargingStation:
        address_info = item.get("AddressInfo", {}) or {}
        operator_info = item.get("OperatorInfo", {}) or {}
        usage_type = item.get("UsageType", {}) or {}
        status_type = item.get("StatusType", {}) or {}

        connections_raw = item.get("Connections", []) or []
        connections = [self._normalize_connection(c) for c in connections_raw]

        name = (
            address_info.get("Title")
            or address_info.get("AddressLine1")
            or f"OCM-{item.get('ID')}"
        )

        return ChargingStation(
            ocm_id=int(item["ID"]),
            uuid=item.get("UUID"),
            name=name,
            operator=operator_info.get("Title") or operator_info.get("Description"),
            usage_type=usage_type.get("Title") or usage_type.get("Description"),
            usage_cost=item.get("UsageCost"),
            address=self._build_address(address_info),
            town=address_info.get("Town"),
            latitude=float(address_info["Latitude"]),
            longitude=float(address_info["Longitude"]),
            distance_km=self._safe_float(address_info.get("Distance")),
            number_of_points=self._safe_int(item.get("NumberOfPoints")),
            status=status_type.get("Title") or status_type.get("Description"),
            is_operational=status_type.get("IsOperational"),
            connections=connections,
            raw=item,
        )

    def _load_fallback_stations(self) -> List[ChargingStation]:
        if not self.fallback_file.exists():
            return []

        try:
            with self.fallback_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        stations: List[ChargingStation] = []
        for item in data:
            try:
                stations.append(self._normalize_station(item))
            except Exception:
                continue

        return stations

    def _load_tr_cache_stations(self) -> List[ChargingStation]:
        """app/data/all_tr_stations.json dosyasını yükler ve memoize eder."""
        if self._tr_cache_stations is not None:
            return self._tr_cache_stations

        if not self.tr_cache_file.exists():
            self._tr_cache_stations = []
            return self._tr_cache_stations

        try:
            with self.tr_cache_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self._tr_cache_stations = []
            return self._tr_cache_stations

        if not isinstance(data, list):
            self._tr_cache_stations = []
            return self._tr_cache_stations

        stations: List[ChargingStation] = []
        for item in data:
            try:
                stations.append(self._normalize_station(item))
            except Exception:
                continue

        self._debug_print(
            f"INFO: TR cache yüklendi → {len(stations)} istasyon "
            f"({self.tr_cache_file})"
        )
        self._tr_cache_stations = stations
        return stations

    def _filter_tr_cache_by_distance(
        self,
        coord: Coordinate,
        distance_km: float,
        max_results: int,
    ) -> List[ChargingStation]:
        """TR cache'i verilen noktaya göre haversine ile filtreler ve mesafe yazar."""
        cache = self._load_tr_cache_stations()
        if not cache:
            return []

        lat, lon = coord
        scored: List[Tuple[float, ChargingStation]] = []
        for station in cache:
            d = _haversine_km(lat, lon, station.latitude, station.longitude)
            if d <= distance_km:
                # distance_km alanını günceleyip yeni dataclass üret
                updated = ChargingStation(
                    ocm_id=station.ocm_id,
                    uuid=station.uuid,
                    name=station.name,
                    operator=station.operator,
                    usage_type=station.usage_type,
                    usage_cost=station.usage_cost,
                    address=station.address,
                    town=station.town,
                    latitude=station.latitude,
                    longitude=station.longitude,
                    distance_km=round(d, 3),
                    number_of_points=station.number_of_points,
                    status=station.status,
                    is_operational=station.is_operational,
                    connections=station.connections,
                    raw=station.raw,
                )
                scored.append((d, updated))

        scored.sort(key=lambda pair: pair[0])
        return [s for _, s in scored[:max_results]]

    def _resolve_fallback(
        self,
        coord: Coordinate,
        distance_km: float,
        max_results: int,
    ) -> List[ChargingStation]:
        """Önce TR-wide cache'i dene, yoksa sample_stations'a düş."""
        tr_results = self._filter_tr_cache_by_distance(
            coord=coord,
            distance_km=distance_km,
            max_results=max_results,
        )
        if tr_results:
            return tr_results
        return self._load_fallback_stations()

    def _request_with_retry(
        self,
        url: str,
        params: Dict[str, Any],
        headers: Dict[str, str],
        retries: int = 3,
        backoff_seconds: float = 1.0,
    ) -> requests.Response:
        last_status_code: Optional[int] = None
        last_error_kind: Optional[str] = None

        for attempt in range(1, retries + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )

                safe_params = self._redact_params(params)
                self._debug_print(f"DEBUG attempt={attempt} status={response.status_code}")
                self._debug_print(f"DEBUG params={safe_params}")

                last_status_code = response.status_code

                if 500 <= response.status_code <= 599:
                    last_error_kind = "server_error"
                    if attempt < retries:
                        time.sleep(backoff_seconds * attempt)
                        continue
                    raise ChargingServiceError(
                        f"Open Charge Map HTTP {response.status_code} (server error)."
                    )

                if 400 <= response.status_code <= 499:
                    last_error_kind = "client_error"
                    raise ChargingServiceError(
                        f"Open Charge Map HTTP {response.status_code} (client error)."
                    )

                return response

            except requests.Timeout:
                last_error_kind = "timeout"
                if attempt < retries:
                    time.sleep(backoff_seconds * attempt)
                    continue
                raise ChargingServiceError("Open Charge Map isteği timeout oldu.")

            except requests.ConnectionError:
                last_error_kind = "connection_error"
                if attempt < retries:
                    time.sleep(backoff_seconds * attempt)
                    continue
                raise ChargingServiceError("Open Charge Map bağlantı hatası oluştu.")

            except ChargingServiceError:
                raise

            except requests.RequestException:
                last_error_kind = "request_exception"
                if attempt < retries:
                    time.sleep(backoff_seconds * attempt)
                    continue
                raise ChargingServiceError("Open Charge Map isteği başarısız oldu.")

        raise ChargingServiceError(
            f"Open Charge Map isteği başarısız oldu. "
            f"last_status={last_status_code}, kind={last_error_kind}"
        )

    def get_nearby_stations(
        self,
        coord: Coordinate,
        distance_km: float = 10.0,
        max_results: int = 20,
        compact: bool = True,
        verbose: bool = False,
        opendata_only: bool = False,
        connection_type_ids: Optional[List[int]] = None,
        status_type_ids: Optional[List[int]] = None,
        allow_fallback: bool = True,
    ) -> List[ChargingStation]:
        self._validate_coordinate(coord)
        lat, lon = coord

        if not self.api_key:
            if allow_fallback:
                return self._resolve_fallback(
                    coord=coord,
                    distance_km=distance_km,
                    max_results=max_results,
                )
            raise ChargingServiceError(
                "OCM_API_KEY bulunamadi. Once terminalde export et."
            )

        if allow_fallback and not self.live_api_available:
            return self._resolve_fallback(
                coord=coord,
                distance_km=distance_km,
                max_results=max_results,
            )

        url = f"{self.base_url}/poi"
        params: Dict[str, Any] = {
            "output": "json",
            "latitude": lat,
            "longitude": lon,
            "distance": distance_km,
            "distanceunit": "km",
            "maxresults": max_results,
            "compact": str(compact).lower(),
            "verbose": str(verbose).lower(),
            "client": "ev-route-optimizer",
            # İsteyen API'ler header'ı görmeyebilir diye parametreyi bırakıyoruz,
            # ama tüm log ve hata yollarında redacted.
            "key": self.api_key,
        }

        if opendata_only:
            params["opendata"] = "true"

        if connection_type_ids:
            params["connectiontypeid"] = ",".join(str(x) for x in connection_type_ids)

        if status_type_ids:
            params["statustypeid"] = ",".join(str(x) for x in status_type_ids)

        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            "X-API-Key": self.api_key,
        }

        try:
            response = self._request_with_retry(
                url=url,
                params=params,
                headers=headers,
                retries=3,
                backoff_seconds=1.0,
            )
            data = response.json()

            if not isinstance(data, list):
                raise ChargingServiceError(
                    "Open Charge Map beklenen liste formatında yanıt döndürmedi."
                )

            return [self._normalize_station(item) for item in data]

        except Exception as exc:
            self.live_api_available = False

            if not allow_fallback:
                if isinstance(exc, ChargingServiceError):
                    raise
                raise ChargingServiceError("Charging service failed.") from exc

            self._debug_print(
                f"WARNING: Live OCM failed, using fallback. Reason: {type(exc).__name__}"
            )

            return self._resolve_fallback(
                coord=coord,
                distance_km=distance_km,
                max_results=max_results,
            )

    def get_nearby_stations_dict(
        self,
        coord: Coordinate,
        distance_km: float = 10.0,
        max_results: int = 20,
        allow_fallback: bool = True,
    ) -> List[Dict[str, Any]]:
        stations = self.get_nearby_stations(
            coord=coord,
            distance_km=distance_km,
            max_results=max_results,
            allow_fallback=allow_fallback,
        )
        return [self.station_to_dict(s) for s in stations]

    def find_stations_along_route(
        self,
        sampled_geometry: List[Coordinate],
        query_every_n_points: int = 4,
        distance_km: float = 5.0,
        max_results_per_query: int = 10,
        allow_fallback: bool = True,
    ) -> List[ChargingStation]:
        if not sampled_geometry:
            return []

        selected_points: List[Coordinate] = []
        for i, point in enumerate(sampled_geometry):
            if i == 0 or i == len(sampled_geometry) - 1 or i % query_every_n_points == 0:
                selected_points.append(point)

        all_stations: Dict[int, ChargingStation] = {}

        for point in selected_points:
            stations = self.get_nearby_stations(
                coord=point,
                distance_km=distance_km,
                max_results=max_results_per_query,
                allow_fallback=allow_fallback,
            )
            for station in stations:
                existing = all_stations.get(station.ocm_id)
                if existing is None:
                    all_stations[station.ocm_id] = station
                else:
                    old_d = (
                        existing.distance_km
                        if existing.distance_km is not None
                        else float("inf")
                    )
                    new_d = (
                        station.distance_km
                        if station.distance_km is not None
                        else float("inf")
                    )
                    if new_d < old_d:
                        all_stations[station.ocm_id] = station

        result = list(all_stations.values())
        result.sort(
            key=lambda s: (
                0 if s.is_operational else 1,
                s.distance_km if s.distance_km is not None else float("inf"),
            )
        )
        return result

    @staticmethod
    def station_to_dict(station: ChargingStation) -> Dict[str, Any]:
        return {
            "ocm_id": station.ocm_id,
            "uuid": station.uuid,
            "name": station.name,
            "operator": station.operator,
            "usage_type": station.usage_type,
            "usage_cost": station.usage_cost,
            "address": station.address,
            "town": station.town,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "distance_km": round(station.distance_km, 3)
            if station.distance_km is not None
            else None,
            "number_of_points": station.number_of_points,
            "status": station.status,
            "is_operational": station.is_operational,
            "connections": [
                {
                    "connection_type": c.connection_type,
                    "power_kw": c.power_kw,
                    "current_type": c.current_type,
                    "quantity": c.quantity,
                    "is_fast_charge_capable": c.is_fast_charge_capable,
                    "status": c.status,
                }
                for c in station.connections
            ],
        }


if __name__ == "__main__":
    service = OpenChargeMapService(debug=False)

    coord = (39.9208, 32.8541)  # Ankara Kızılay

    stations = service.get_nearby_stations_dict(
        coord=coord,
        distance_km=8,
        max_results=10,
        allow_fallback=True,
    )

    print(f"Bulunan istasyon sayısı: {len(stations)}")
    print("İlk 3 istasyon:")
    for station in stations[:3]:
        print(station)