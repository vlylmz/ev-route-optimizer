from __future__ import annotations

import json
from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pick(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)

    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


# Kabaca match: OCM "CCS (Type 2)" gibi degerleri "CCS2" anahtarina yansitir.
_CONNECTOR_PATTERNS = {
    "CCS2": ("CCS",),
    "CCS1": ("CCS Type 1",),
    "CHAdeMO": ("CHADEMO",),
    "Type 2": ("TYPE 2", "MENNEKES"),
    "Type 1": ("TYPE 1", "J1772"),
    "Tesla": ("TESLA",),
}


def _normalize_connector_label(raw: str) -> Optional[str]:
    if not raw:
        return None
    upper = raw.upper()
    for canonical, patterns in _CONNECTOR_PATTERNS.items():
        for pattern in patterns:
            if pattern in upper:
                return canonical
    return None


def _extract_station_connectors(station: Dict[str, Any]) -> set:
    """Station dict'inden normalize edilmis connector setini cikarir."""
    connections = _pick(station, "connections", "Connections", default=[]) or []
    result: set = set()
    for conn in connections:
        if not isinstance(conn, dict):
            continue
        raw = _pick(conn, "connection_type", "ConnectionType", default=None)
        if isinstance(raw, dict):
            raw = raw.get("Title") or raw.get("FormalName")
        canonical = _normalize_connector_label(raw or "")
        if canonical:
            result.add(canonical)
    # Bazi cache'lenmis station'larda connections olmayabilir; en azindan
    # legacy alan varsa onu da kullan.
    legacy = _pick(station, "connector", "connector_type", default=None)
    if legacy:
        canonical = _normalize_connector_label(str(legacy))
        if canonical:
            result.add(canonical)
    return result


def _vehicle_connector_set(vehicle: Dict[str, Any]) -> set:
    """Vehicle dict'inden DC + AC connector setini birlestirir."""
    dc = vehicle.get("dc_connectors") or ["CCS2"]
    ac = vehicle.get("ac_connectors") or ["Type 2"]
    return {_normalize_connector_label(c) or c for c in list(dc) + list(ac)}


@dataclass
class RoutePoint:
    lat: float
    lon: float
    cumulative_distance_km: float


class ChargingStopSelector:
    """
    charge_need_analyzer sonrası ilk uygun şarj durağını seçer.

    Tasarım amacı:
    - mevcut projedeki dict tabanlı veri akışına uyum
    - istasyonları kritik SOC noktasından önce filtreleme
    - sapma + şarj süresi + risk puanı ile sıralama
    - tek sonraki durak seçimi (çok duraklı zinciri route_planner kuracak)
    """

    def __init__(
        self,
        *,
        reserve_soc_buffer: float = 10.0,
        station_arrival_buffer_soc: float = 2.0,
        default_station_power_kw: float = 50.0,
        default_detour_speed_kmh: float = 40.0,
        max_target_soc_percent: float = 85.0,
        post_80_taper_factor: float = 0.55,
        curve_service: Any = None,
        strategy_config_path: Optional[Path] = None,
    ) -> None:
        from app.services.charging_curve_service import ChargingCurveService

        self.reserve_soc_buffer = reserve_soc_buffer
        self.station_arrival_buffer_soc = station_arrival_buffer_soc
        self.default_station_power_kw = default_station_power_kw
        self.default_detour_speed_kmh = default_detour_speed_kmh
        self.max_target_soc_percent = max_target_soc_percent
        self.post_80_taper_factor = post_80_taper_factor
        self.curve_service = curve_service or ChargingCurveService()
        self.strategy_config_path = strategy_config_path
        self._strategy_config_cache: Optional[Dict[str, Any]] = None

    def select_stop(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        """
        Beklenen ana inputlar:

        vehicle:
            usable_battery_kwh
            ideal_consumption_wh_km
            max_dc_charge_power_kw

        route_context:
            {
                "route": {
                    "distance_km": ...,
                    "geometry": [{"lat": ..., "lon": ...}, ...]  # opsiyonel
                },
                "stations": [...]
            }

        simulation_result:
            {
                "initial_soc": ...,
                "total_energy_kwh": ...,
                "segments": [
                    {"cumulative_distance_km": 50, "soc_after": 70},
                    ...
                ]
            }

        charge_need:
            {
                "needs_charging": True/False,
                "critical_distance_km": ...,
                "reserve_soc_percent": ...
            }
        """
        needs_charging = bool(
            _pick(charge_need, "needs_charging", "requires_charging", "charging_needed", "charging_required", default=False)
        )

        if not needs_charging:
            return {
                "needs_charging": False,
                "selected_station": None,
                "candidates": [],
                "message": "Şarj ihtiyacı yok.",
            }

        route = _pick(route_context, "route", default={}) or {}
        stations = _pick(route_context, "stations", "charging_stations", default=[]) or []

        route_distance_km = _safe_float(
            _pick(route, "distance_km", "total_distance_km"), 0.0
        )

        critical_distance_km = _safe_float(
            _pick(
                charge_need,
                "critical_distance_km",
                "charge_by_distance_km",
                "last_safe_distance_km",
                default=route_distance_km,
            ),
            route_distance_km,
        )

        reserve_soc = _safe_float(
            _pick(
                charge_need,
                "reserve_soc_percent",
                "min_soc_percent",
                default=self.reserve_soc_buffer,
            ),
            self.reserve_soc_buffer,
        )

        route_points = self._build_route_points(route)
        usable_battery_kwh = _safe_float(
            _pick(vehicle, "usable_battery_kwh", "battery_capacity_kwh"),
            0.0,
        )

        avg_consumption_kwh_per_km = self._resolve_avg_consumption(
            route_distance_km=route_distance_km,
            simulation_result=simulation_result,
            vehicle=vehicle,
        )

        vehicle_connectors = _vehicle_connector_set(vehicle)

        enriched_candidates: List[Dict[str, Any]] = []
        for station in stations:
            candidate = self._enrich_station(
                station=station,
                route_points=route_points,
                simulation_result=simulation_result,
                route_distance_km=route_distance_km,
                critical_distance_km=critical_distance_km,
                reserve_soc=reserve_soc,
                usable_battery_kwh=usable_battery_kwh,
                avg_consumption_kwh_per_km=avg_consumption_kwh_per_km,
                vehicle=vehicle,
                strategy=strategy,
                vehicle_connectors=vehicle_connectors,
            )
            if candidate is not None:
                enriched_candidates.append(candidate)

        if not enriched_candidates:
            return {
                "needs_charging": True,
                "selected_station": None,
                "candidates": [],
                "message": "Uygun ve erişilebilir şarj istasyonu bulunamadı.",
            }

        # Normalize edilmis multi-objective skor; dusuk = iyi.
        self._normalize_and_score(candidates=enriched_candidates, strategy=strategy)
        ranked = sorted(enriched_candidates, key=lambda x: x["score"])
        selected = ranked[0]

        return {
            "needs_charging": True,
            "selected_station": selected,
            "candidates": ranked,
            "message": self._build_reason(selected, strategy),
        }

    def _build_route_points(self, route: Dict[str, Any]) -> List[RoutePoint]:
        raw_points = (
            _pick(route, "geometry", "points", "coordinates", default=[])
            or _pick(route, "polyline_points", default=[])
            or []
        )

        if not raw_points:
            return []

        parsed_points: List[Tuple[float, float]] = []
        for item in raw_points:
            if isinstance(item, dict):
                lat = _safe_float(_pick(item, "lat", "latitude"), 0.0)
                lon = _safe_float(_pick(item, "lon", "lng", "longitude"), 0.0)
                parsed_points.append((lat, lon))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                parsed_points.append((_safe_float(item[0]), _safe_float(item[1])))

        route_points: List[RoutePoint] = []
        cumulative = 0.0
        prev = None

        for lat, lon in parsed_points:
            if prev is not None:
                cumulative += _haversine_km(prev[0], prev[1], lat, lon)
            route_points.append(RoutePoint(lat=lat, lon=lon, cumulative_distance_km=cumulative))
            prev = (lat, lon)

        return route_points

    def _resolve_avg_consumption(
        self,
        *,
        route_distance_km: float,
        simulation_result: Dict[str, Any],
        vehicle: Dict[str, Any],
    ) -> float:
        total_energy_kwh = _safe_float(
            _pick(simulation_result, "total_energy_kwh", "energy_used_kwh", default=None),
            default=-1.0,
        )

        if route_distance_km > 0 and total_energy_kwh > 0:
            return total_energy_kwh / route_distance_km

        ideal_wh_km = _safe_float(_pick(vehicle, "ideal_consumption_wh_km"), 180.0)
        return ideal_wh_km / 1000.0

    def _enrich_station(
        self,
        *,
        station: Dict[str, Any],
        route_points: List[RoutePoint],
        simulation_result: Dict[str, Any],
        route_distance_km: float,
        critical_distance_km: float,
        reserve_soc: float,
        usable_battery_kwh: float,
        avg_consumption_kwh_per_km: float,
        vehicle: Dict[str, Any],
        strategy: str,
        vehicle_connectors: Optional[set] = None,
    ) -> Optional[Dict[str, Any]]:
        # HARD filter: arac soket tipi istasyondaki en az bir bagliyla esleshmeli.
        # Bos vehicle_connectors -> kontrol atlanir (geri uyumluluk).
        if vehicle_connectors:
            station_connectors = _extract_station_connectors(station)
            # Station connector verisi yoksa filtreleme (eski cache'lenmis kayit).
            if station_connectors and not vehicle_connectors.intersection(station_connectors):
                return None

        distance_along_route_km, distance_from_route_km = self._resolve_station_route_metrics(
            station=station,
            route_points=route_points,
        )

        if distance_along_route_km is None:
            return None

        # Kritik noktadan sonraki istasyonları ilk selector aşamasında eliyoruz.
        if distance_along_route_km > critical_distance_km:
            return None

        soc_at_station = self._interpolate_soc_at_distance(
            simulation_result=simulation_result,
            distance_km=distance_along_route_km,
        )

        # İstasyona minimum tamponla ulaşabilmeli.
        if soc_at_station < reserve_soc + self.station_arrival_buffer_soc:
            return None

        remaining_distance_km = max(route_distance_km - distance_along_route_km, 0.0)

        target_soc = self._estimate_target_soc(
            remaining_distance_km=remaining_distance_km,
            reserve_soc=reserve_soc,
            usable_battery_kwh=usable_battery_kwh,
            avg_consumption_kwh_per_km=avg_consumption_kwh_per_km,
        )

        station_power_kw = _safe_float(
            _pick(
                station,
                "power_kw",
                "max_power_kw",
                "dc_power_kw",
                default=self.default_station_power_kw,
            ),
            self.default_station_power_kw,
        )

        charge_minutes = self._estimate_charge_minutes(
            start_soc=soc_at_station,
            target_soc=target_soc,
            usable_battery_kwh=usable_battery_kwh,
            station_power_kw=station_power_kw,
            vehicle=vehicle,
        )

        detour_distance_km = max(distance_from_route_km * 2.0, 0.0)
        detour_minutes = 0.0
        if self.default_detour_speed_kmh > 0:
            detour_minutes = (detour_distance_km / self.default_detour_speed_kmh) * 60.0

        # HARD filter: kapali istasyonu hicbir kosulda secme.
        if not bool(_pick(station, "is_operational", "available", default=True)):
            return None

        margin_soc = soc_at_station - reserve_soc

        risk_score = self._risk_score(
            margin_soc=margin_soc,
            station_power_kw=station_power_kw,
        )

        total_stop_minutes = charge_minutes + detour_minutes

        # HARD filter: rezerv ustunde anlamli marj birakmayan istasyon adayligi
        # alamaz. Min marj strategy_weights.json'dan; default 3.0 puan.
        config = self._load_strategy_config()
        min_margin = float(config.get("min_safe_soc_margin_pct", self._DEFAULT_MIN_SAFE_SOC_MARGIN))
        if margin_soc < min_margin:
            return None

        # Raw metrics: normalize asamasinda min-max'e tabi tutulur.
        charge_kwh = max(0.0, target_soc - soc_at_station) * usable_battery_kwh / 100.0
        # Detour enerjisi + sarj kaybi (~%5 charging loss).
        extra_energy_kwh = detour_distance_km * avg_consumption_kwh_per_km + charge_kwh * 0.05
        price_per_kwh = _safe_float(
            _pick(station, "price_per_kwh_try", "price_per_kwh"),
            float(config.get("default_price_per_kwh_try", self._DEFAULT_PRICE_PER_KWH_TRY)),
        )
        extra_cost_try = price_per_kwh * charge_kwh

        max_reachable_without_extra_stop_kwh = (
            usable_battery_kwh * max(self.max_target_soc_percent - reserve_soc, 0.0) / 100.0
        )
        required_remaining_energy_kwh = remaining_distance_km * avg_consumption_kwh_per_km

        return {
            **station,
            "distance_along_route_km": round(distance_along_route_km, 2),
            "distance_from_route_km": round(distance_from_route_km, 2),
            "detour_distance_km": round(detour_distance_km, 2),
            "soc_at_arrival_percent": round(soc_at_station, 2),
            "target_soc_percent": round(target_soc, 2),
            "charge_minutes": round(charge_minutes, 1),
            "detour_minutes": round(detour_minutes, 1),
            "total_stop_minutes": round(total_stop_minutes, 1),
            "risk_score": round(risk_score, 2),
            "remaining_distance_km": round(remaining_distance_km, 2),
            "requires_additional_stop": required_remaining_energy_kwh > max_reachable_without_extra_stop_kwh,
            # Normalize asamasinda kullanilacak raw metrics:
            "extra_time_min": round(total_stop_minutes, 2),
            "extra_energy_kwh": round(extra_energy_kwh, 3),
            "extra_cost_try": round(extra_cost_try, 2),
            "soc_margin_at_station": round(margin_soc, 2),
            "charge_kwh": round(charge_kwh, 2),
            "price_per_kwh_try": round(price_per_kwh, 2),
        }

    def _resolve_station_route_metrics(
        self,
        *,
        station: Dict[str, Any],
        route_points: List[RoutePoint],
    ) -> Tuple[Optional[float], float]:
        # Eğer charging_service zaten hesapladıysa direkt onu kullan.
        precomputed_along = _pick(
            station,
            "distance_along_route_km",
            "distance_from_start_km",
            default=None,
        )
        precomputed_offset = _pick(
            station,
            "distance_from_route_km",
            "offset_km",
            "detour_km",
            default=None,
        )

        if precomputed_along is not None:
            return _safe_float(precomputed_along), _safe_float(precomputed_offset, 0.0)

        if not route_points:
            return None, 0.0

        station_lat = _safe_float(_pick(station, "lat", "latitude"), 0.0)
        station_lon = _safe_float(_pick(station, "lon", "lng", "longitude"), 0.0)

        nearest_point = min(
            route_points,
            key=lambda p: _haversine_km(station_lat, station_lon, p.lat, p.lon),
        )

        offset_km = _haversine_km(station_lat, station_lon, nearest_point.lat, nearest_point.lon)
        return nearest_point.cumulative_distance_km, offset_km

    def _interpolate_soc_at_distance(
        self,
        *,
        simulation_result: Dict[str, Any],
        distance_km: float,
    ) -> float:
        initial_soc = _safe_float(
            _pick(simulation_result, "initial_soc", "start_soc", "start_soc_pct", default=100.0),
            100.0,
        )

        segments = _pick(simulation_result, "segments", "segment_results", default=[]) or []
        if not segments:
            return initial_soc

        normalized: List[Tuple[float, float]] = []
        cumulative = 0.0
        for index, segment in enumerate(segments):
            # Try precomputed cumulative first; fall back to summing per-segment distance_km
            seg_distance = _pick(segment, "cumulative_distance_km", "end_distance_km", default=None)
            if seg_distance is None:
                per_seg = _safe_float(_pick(segment, "distance_km", default=None), 0.0)
                cumulative += per_seg
                seg_distance = cumulative if cumulative > 0 else float(index + 1)

            soc_after = _safe_float(
                _pick(segment, "soc_after", "ending_soc", "end_soc", "end_soc_pct", "remaining_soc"),
                initial_soc,
            )
            normalized.append((_safe_float(seg_distance), soc_after))

        normalized.sort(key=lambda x: x[0])

        if distance_km <= normalized[0][0]:
            first_distance, first_soc = normalized[0]
            if first_distance <= 0:
                return first_soc
            ratio = max(min(distance_km / first_distance, 1.0), 0.0)
            return initial_soc + (first_soc - initial_soc) * ratio

        for i in range(1, len(normalized)):
            prev_distance, prev_soc = normalized[i - 1]
            curr_distance, curr_soc = normalized[i]

            if distance_km <= curr_distance:
                span = curr_distance - prev_distance
                if span <= 0:
                    return curr_soc
                ratio = (distance_km - prev_distance) / span
                return prev_soc + (curr_soc - prev_soc) * ratio

        return normalized[-1][1]

    def _estimate_target_soc(
        self,
        *,
        remaining_distance_km: float,
        reserve_soc: float,
        usable_battery_kwh: float,
        avg_consumption_kwh_per_km: float,
    ) -> float:
        if usable_battery_kwh <= 0:
            return self.max_target_soc_percent

        # Biraz güvenlik payı ekliyoruz.
        required_energy_kwh = remaining_distance_km * avg_consumption_kwh_per_km * 1.08
        required_soc_percent = (required_energy_kwh / usable_battery_kwh) * 100.0

        target_soc = reserve_soc + required_soc_percent
        target_soc = max(target_soc, reserve_soc + 15.0)

        return min(target_soc, self.max_target_soc_percent)

    def _estimate_charge_minutes(
        self,
        *,
        start_soc: float,
        target_soc: float,
        usable_battery_kwh: float,
        station_power_kw: float,
        vehicle: Dict[str, Any],
    ) -> float:
        # Vehicle'ın charge_curve_hint + max_dc_charge_kw + station gücü ile
        # SOC bazlı entegrasyon. Eski 80% sabit taper'ından çok daha doğru.
        # Vehicle dict'inde max_dc_charge_power_kw varsa onu max_dc_charge_kw'a haritala.
        vehicle_for_curve = dict(vehicle) if isinstance(vehicle, dict) else vehicle
        if isinstance(vehicle_for_curve, dict):
            if "max_dc_charge_kw" not in vehicle_for_curve:
                v = _pick(
                    vehicle_for_curve,
                    "max_dc_charge_power_kw",
                    "max_charge_power_kw",
                    default=None,
                )
                if v is not None:
                    vehicle_for_curve["max_dc_charge_kw"] = v

        return self.curve_service.compute_charge_minutes(
            vehicle=vehicle_for_curve,
            station_kw=station_power_kw,
            start_soc_pct=start_soc,
            target_soc_pct=target_soc,
            usable_battery_kwh=usable_battery_kwh,
        )

    def _risk_score(
        self,
        *,
        margin_soc: float,
        station_power_kw: float,
    ) -> float:
        score = 0.0

        # Rezerv SOC'a çok yakın varmak riskli.
        if margin_soc < 6.0:
            score += (6.0 - margin_soc) * 4.0

        # Güç düşükse risk/ceza biraz artsın.
        if station_power_kw < 50.0:
            score += (50.0 - station_power_kw) * 0.15

        return score

    _DEFAULT_STRATEGY_WEIGHTS = {
        "fast":      {"time": 0.65, "energy": 0.10, "cost": 0.10, "safety": 0.15},
        "efficient": {"time": 0.15, "energy": 0.50, "cost": 0.20, "safety": 0.15},
        "balanced":  {"time": 0.35, "energy": 0.30, "cost": 0.15, "safety": 0.20},
    }
    _DEFAULT_PRICE_PER_KWH_TRY = 7.0
    _DEFAULT_MIN_SAFE_SOC_MARGIN = 3.0

    def _load_strategy_config(self) -> Dict[str, Any]:
        """JSON config'i bir kez yukle, runtime cache'le. Hata olursa default."""
        if self._strategy_config_cache is not None:
            return self._strategy_config_cache

        path = self.strategy_config_path
        if path is None:
            path = Path(__file__).resolve().parent.parent / "data" / "strategy_weights.json"

        config = {
            "weights": dict(self._DEFAULT_STRATEGY_WEIGHTS),
            "default_price_per_kwh_try": self._DEFAULT_PRICE_PER_KWH_TRY,
            "min_safe_soc_margin_pct": self._DEFAULT_MIN_SAFE_SOC_MARGIN,
        }

        try:
            with Path(path).open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("weights"), dict):
                config["weights"] = data["weights"]
            if "default_price_per_kwh_try" in data:
                config["default_price_per_kwh_try"] = float(data["default_price_per_kwh_try"])
            if "min_safe_soc_margin_pct" in data:
                config["min_safe_soc_margin_pct"] = float(data["min_safe_soc_margin_pct"])
        except (OSError, json.JSONDecodeError, ValueError):
            pass

        self._strategy_config_cache = config
        return config

    def _normalize_and_score(
        self,
        *,
        candidates: List[Dict[str, Any]],
        strategy: str,
    ) -> None:
        """Aday listesindeki raw metrics'i min-max normalize eder ve score ekler."""
        if not candidates:
            return

        config = self._load_strategy_config()
        weights = config["weights"].get(strategy.lower()) or self._DEFAULT_STRATEGY_WEIGHTS["balanced"]

        def col(name: str) -> List[float]:
            return [float(c.get(name, 0.0)) for c in candidates]

        def normalize(values: List[float], invert: bool = False) -> List[float]:
            lo, hi = min(values), max(values)
            if hi - lo < 1e-9:
                return [0.0] * len(values)
            normalized = [(v - lo) / (hi - lo) for v in values]
            return [1.0 - x for x in normalized] if invert else normalized

        time_norm = normalize(col("extra_time_min"))
        energy_norm = normalize(col("extra_energy_kwh"))
        cost_norm = normalize(col("extra_cost_try"))
        # SOC margin: yuksek margin iyi -> dusuk safety penalty.
        safety_norm = normalize(col("soc_margin_at_station"), invert=True)

        for i, cand in enumerate(candidates):
            score = (
                weights.get("time", 0.0) * time_norm[i]
                + weights.get("energy", 0.0) * energy_norm[i]
                + weights.get("cost", 0.0) * cost_norm[i]
                + weights.get("safety", 0.0) * safety_norm[i]
            )
            cand["score"] = round(score, 4)
            cand["score_breakdown"] = {
                "time": round(weights.get("time", 0.0) * time_norm[i], 4),
                "energy": round(weights.get("energy", 0.0) * energy_norm[i], 4),
                "cost": round(weights.get("cost", 0.0) * cost_norm[i], 4),
                "safety": round(weights.get("safety", 0.0) * safety_norm[i], 4),
            }

    def _build_reason(self, station: Dict[str, Any], strategy: str) -> str:
        name = _pick(station, "name", "title", default="İstasyon")
        return (
            f"{name} seçildi. "
            f"Varış SOC: %{station['soc_at_arrival_percent']}, "
            f"hedef SOC: %{station['target_soc_percent']}, "
            f"tahmini şarj süresi: {station['charge_minutes']} dk, "
            f"sapma: {station['detour_distance_km']} km, "
            f"strateji: {strategy}."
        )


def select_charging_stop(
    *,
    vehicle: Dict[str, Any],
    route_context: Dict[str, Any],
    simulation_result: Dict[str, Any],
    charge_need: Dict[str, Any],
    strategy: str = "balanced",
) -> Dict[str, Any]:
    selector = ChargingStopSelector()
    return selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy=strategy,
    )
if __name__ == "__main__":
    vehicle = {
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
        "max_dc_charge_power_kw": 120,
    }

    route_context = {
        "route": {
            "distance_km": 300,
            "geometry": [
                {"lat": 39.0000, "lon": 32.0000},
                {"lat": 39.2000, "lon": 32.2000},
                {"lat": 39.4000, "lon": 32.4000},
                {"lat": 39.6000, "lon": 32.6000},
            ],
        },
        "stations": [
            {
                "name": "Yakin Hizli Istasyon",
                "distance_along_route_km": 150,
                "distance_from_route_km": 1.5,
                "power_kw": 120,
                "is_operational": True,
            },
            {
                "name": "Cok Yakin Ama Yavas",
                "distance_along_route_km": 145,
                "distance_from_route_km": 0.3,
                "power_kw": 50,
                "is_operational": True,
            },
            {
                "name": "Gec Kalan Istasyon",
                "distance_along_route_km": 240,
                "distance_from_route_km": 0.2,
                "power_kw": 180,
                "is_operational": True,
            },
        ],
    }

    simulation_result = {
        "initial_soc": 80,
        "total_energy_kwh": 54,
        "segments": [
            {"cumulative_distance_km": 100, "soc_after": 60},
            {"cumulative_distance_km": 200, "soc_after": 32},
            {"cumulative_distance_km": 300, "soc_after": 6},
        ],
    }

    charge_need = {
        "needs_charging": True,
        "critical_distance_km": 210,
        "reserve_soc_percent": 10,
    }

    selector = ChargingStopSelector()
    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="balanced",
    )

    from pprint import pprint
    pprint(result)