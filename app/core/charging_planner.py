from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional


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


class ChargingPlanner:
    """
    charging_stop_selector sonucunu alir ve uygulanabilir
    tek durakli bir sarj plani uretir.

    Bu katman:
    - final trip metrics hesaplar
    - durak listesini normalize eder
    - toplam sure / toplam enerji / tahmini varis SOC dondurur
    - ML kullanim ozetini yukari tasir

    Not:
    Ilk surum MVP icin tek durakli plan uretiyor.
    Cok durakli plan daha sonra genisletilebilir.
    """

    def __init__(
        self,
        *,
        reserve_soc_default: float = 10.0,
        energy_buffer_factor: float = 1.05,
    ) -> None:
        self.reserve_soc_default = reserve_soc_default
        self.energy_buffer_factor = energy_buffer_factor

    def build_plan(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        selector_result: Dict[str, Any],
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        needs_charging = bool(
            _pick(
                charge_need,
                "needs_charging",
                "requires_charging",
                "charging_required",
                default=False,
            )
        )

        route = _pick(route_context, "route", default={}) or {}
        route_distance_km = _safe_float(
            _pick(route, "distance_km", "total_distance_km"),
            0.0,
        )
        route_duration_min = _safe_float(
            _pick(route, "duration_min", "duration_minutes", "estimated_duration_min"),
            0.0,
        )

        total_energy_kwh = _safe_float(
            _pick(simulation_result, "total_energy_kwh", "energy_used_kwh"),
            0.0,
        )
        final_soc_without_charge = self._extract_final_soc(simulation_result)

        usable_battery_kwh = _safe_float(
            _pick(vehicle, "usable_battery_kwh", "battery_capacity_kwh"),
            0.0,
        )

        avg_consumption_kwh_per_km = self._resolve_avg_consumption(
            route_distance_km=route_distance_km,
            total_energy_kwh=total_energy_kwh,
            vehicle=vehicle,
        )

        ml_summary = self._extract_ml_summary(
            simulation_result=simulation_result,
            charge_need=charge_need,
        )

        if not needs_charging:
            return {
                "status": "ok",
                "strategy": strategy,
                "needs_charging": False,
                "feasible": final_soc_without_charge >= 0,
                "recommended_stops": [],
                "summary": {
                    "stop_count": 0,
                    "charge_minutes": 0.0,
                    "detour_minutes": 0.0,
                    "total_trip_minutes": round(route_duration_min, 1),
                    "total_energy_kwh": round(total_energy_kwh, 2),
                    "projected_arrival_soc_percent": round(final_soc_without_charge, 2),
                },
                "ml_summary": ml_summary,
                "message": "Şarj gerekmiyor.",
            }

        selected_station = _pick(selector_result, "selected_station", default=None)

        if not selected_station:
            return {
                "status": "no_feasible_plan",
                "strategy": strategy,
                "needs_charging": True,
                "feasible": False,
                "recommended_stops": [],
                "summary": {
                    "stop_count": 0,
                    "charge_minutes": 0.0,
                    "detour_minutes": 0.0,
                    "total_trip_minutes": round(route_duration_min, 1),
                    "total_energy_kwh": round(total_energy_kwh, 2),
                    "projected_arrival_soc_percent": None,
                },
                "ml_summary": ml_summary,
                "message": "Uygun bir şarj planı oluşturulamadı.",
            }

        reserve_soc = _safe_float(
            _pick(
                charge_need,
                "reserve_soc_percent",
                "min_soc_percent",
                "reserve_soc_pct",
                default=self.reserve_soc_default,
            ),
            self.reserve_soc_default,
        )

        station_name = _pick(selected_station, "name", "title", default="İstasyon")
        distance_along_route_km = _safe_float(
            _pick(selected_station, "distance_along_route_km"),
            0.0,
        )
        remaining_distance_km = _safe_float(
            _pick(selected_station, "remaining_distance_km"),
            max(route_distance_km - distance_along_route_km, 0.0),
        )
        detour_distance_km = _safe_float(
            _pick(selected_station, "detour_distance_km"),
            0.0,
        )
        detour_minutes = _safe_float(
            _pick(selected_station, "detour_minutes"),
            0.0,
        )
        charge_minutes = _safe_float(
            _pick(selected_station, "charge_minutes"),
            0.0,
        )
        arrival_soc_at_station = _safe_float(
            _pick(selected_station, "soc_at_arrival_percent"),
            0.0,
        )
        target_soc_percent = _safe_float(
            _pick(selected_station, "target_soc_percent"),
            0.0,
        )
        station_power_kw = _safe_float(
            _pick(selected_station, "power_kw", "max_power_kw", "dc_power_kw"),
            0.0,
        )

        post_charge_remaining_distance_km = remaining_distance_km + detour_distance_km
        required_post_charge_energy_kwh = (
            post_charge_remaining_distance_km
            * avg_consumption_kwh_per_km
            * self.energy_buffer_factor
        )

        if usable_battery_kwh > 0:
            required_post_charge_soc_percent = (
                required_post_charge_energy_kwh / usable_battery_kwh
            ) * 100.0
        else:
            required_post_charge_soc_percent = 999.0

        projected_arrival_soc_percent = target_soc_percent - required_post_charge_soc_percent
        projected_arrival_soc_percent = max(projected_arrival_soc_percent, 0.0)

        feasible = projected_arrival_soc_percent >= reserve_soc

        extra_detour_energy_kwh = detour_distance_km * avg_consumption_kwh_per_km
        total_trip_energy_kwh = total_energy_kwh + extra_detour_energy_kwh
        total_trip_minutes = route_duration_min + detour_minutes + charge_minutes

        stop = {
            "name": station_name,
            "distance_along_route_km": round(distance_along_route_km, 2),
            "detour_distance_km": round(detour_distance_km, 2),
            "detour_minutes": round(detour_minutes, 1),
            "arrival_soc_percent": round(arrival_soc_at_station, 2),
            "target_soc_percent": round(target_soc_percent, 2),
            "charge_minutes": round(charge_minutes, 1),
            "power_kw": round(station_power_kw, 1),
        }

        single_stop_result: Dict[str, Any] = {
            "status": "ok" if feasible else "risky_plan",
            "strategy": strategy,
            "needs_charging": True,
            "feasible": feasible,
            "recommended_stops": [stop],
            "summary": {
                "stop_count": 1,
                "charge_minutes": round(charge_minutes, 1),
                "detour_minutes": round(detour_minutes, 1),
                "total_trip_minutes": round(total_trip_minutes, 1),
                "total_energy_kwh": round(total_trip_energy_kwh, 2),
                "projected_arrival_soc_percent": round(projected_arrival_soc_percent, 2),
            },
            "ml_summary": ml_summary,
            "message": self._build_message(
                station_name=station_name,
                feasible=feasible,
                projected_arrival_soc_percent=projected_arrival_soc_percent,
                total_trip_minutes=total_trip_minutes,
                used_ml=bool(_pick(ml_summary, "used_ml", default=False)),
                model_version=_pick(ml_summary, "model_version", default=None),
            ),
        }

        # Tek durak yeterliyse direkt dön; degilse cok durakli zinciri dene.
        if feasible:
            return single_stop_result

        multi_stop_result = self._try_multi_stop(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result=simulation_result,
            strategy=strategy,
            route_distance_km=route_distance_km,
            route_duration_min=route_duration_min,
            total_energy_kwh=total_energy_kwh,
            ml_summary=ml_summary,
            avg_consumption_kwh_per_km=avg_consumption_kwh_per_km,
            usable_battery_kwh=usable_battery_kwh,
            reserve_soc=reserve_soc,
        )

        if multi_stop_result is not None and multi_stop_result.get("feasible"):
            return multi_stop_result

        return single_stop_result

    def _try_multi_stop(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        strategy: str,
        route_distance_km: float,
        route_duration_min: float,
        total_energy_kwh: float,
        ml_summary: Dict[str, Any],
        avg_consumption_kwh_per_km: float,
        usable_battery_kwh: float,
        reserve_soc: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Tek durak yetmedigi durumlarda greedy bir cok durakli zincir kurar.

        Strateji: mevcut konumdan reserve+buffer ile ulasilabilen en uzak
        istasyonu sec, sonraki adimi ya bitise ya da bir sonraki istasyona
        yetecek SOC'ye kadar sarj et, tekrar dene.
        """
        if usable_battery_kwh <= 0 or avg_consumption_kwh_per_km <= 0:
            return None

        if route_distance_km <= 0:
            return None

        enriched = self._enrich_all_stations(route_context=route_context)
        if not enriched:
            return None

        initial_soc = _safe_float(
            _pick(
                simulation_result,
                "initial_soc",
                "start_soc",
                "start_soc_pct",
                default=100.0,
            ),
            100.0,
        )

        avg_speed_kmh = (
            (route_distance_km / route_duration_min) * 60.0
            if route_duration_min > 0
            else 80.0
        )

        # Sapasiteye gore ulasilabilir maksimum mesafe (reserve uzeri kullanilabilir SOC)
        soc_buffer = 2.0  # istasyona varisinda guvenli marj
        max_target_soc = 80.0
        max_stops = 5

        stops: List[Dict[str, Any]] = []
        current_distance = 0.0
        current_soc = initial_soc

        for _ in range(max_stops):
            remaining_km = max(route_distance_km - current_distance, 0.0)
            if remaining_km <= 0.001:
                break

            soc_to_finish_pct = (
                (remaining_km * avg_consumption_kwh_per_km * self.energy_buffer_factor)
                / usable_battery_kwh
            ) * 100.0

            if current_soc - soc_to_finish_pct >= reserve_soc:
                break  # bitise dogrudan ulasilabilir

            # Mevcut SOC ile reserve+buffer kalacak sekilde menzil
            usable_pct = max(current_soc - reserve_soc - soc_buffer, 0.0)
            max_reachable_km = (
                usable_pct
                * usable_battery_kwh
                / 100.0
                / avg_consumption_kwh_per_km
            )
            max_reach_distance = current_distance + max_reachable_km

            candidates = [
                s
                for s in enriched
                if current_distance + 1.0 < s["distance_along_route_km"]
                <= max_reach_distance + 0.1
            ]
            if not candidates:
                return None  # cok durakli plan da kuramiyoruz

            # En uzak ve en guclu istasyonu sec
            candidates.sort(
                key=lambda s: (-s["distance_along_route_km"], -s["power_kw"])
            )
            selected = candidates[0]

            leg_km = selected["distance_along_route_km"] - current_distance
            soc_drop_pct = (
                (leg_km * avg_consumption_kwh_per_km) / usable_battery_kwh
            ) * 100.0
            soc_at_arrival = current_soc - soc_drop_pct

            # Hedef SOC: kalan mesafeyi reserve marjla bitirmeye yetecek kadar (cap 80%)
            remaining_after_stop = max(
                route_distance_km - selected["distance_along_route_km"], 0.0
            )
            soc_to_finish_after_pct = (
                (
                    remaining_after_stop
                    * avg_consumption_kwh_per_km
                    * self.energy_buffer_factor
                )
                / usable_battery_kwh
            ) * 100.0
            target_soc = min(soc_to_finish_after_pct + reserve_soc, max_target_soc)
            target_soc = max(target_soc, soc_at_arrival)

            station_power_kw = max(_safe_float(selected.get("power_kw"), 50.0), 1.0)
            # 80% sonrasi taper
            charge_kwh = max((target_soc - soc_at_arrival), 0.0) * usable_battery_kwh / 100.0
            effective_power = (
                station_power_kw if target_soc <= 80.0 else station_power_kw * 0.55
            )
            charge_minutes = (charge_kwh / effective_power) * 60.0

            detour_km = _safe_float(selected.get("detour_distance_km"), 0.0)
            detour_minutes = (
                (detour_km / 40.0) * 60.0 if detour_km > 0 else 0.0
            )

            stops.append(
                {
                    "name": selected.get("name", "İstasyon"),
                    "distance_along_route_km": round(
                        selected["distance_along_route_km"], 2
                    ),
                    "detour_distance_km": round(detour_km, 2),
                    "detour_minutes": round(detour_minutes, 1),
                    "arrival_soc_percent": round(soc_at_arrival, 2),
                    "target_soc_percent": round(target_soc, 2),
                    "charge_minutes": round(charge_minutes, 1),
                    "power_kw": round(station_power_kw, 1),
                }
            )

            current_distance = selected["distance_along_route_km"]
            current_soc = target_soc
        else:
            # max_stops doldu ama hala bitemedik
            return None

        if not stops:
            return None

        # Son duraktan varisa kalan SOC
        remaining_after_last = max(route_distance_km - current_distance, 0.0)
        final_soc_drop_pct = (
            (remaining_after_last * avg_consumption_kwh_per_km)
            / usable_battery_kwh
        ) * 100.0
        projected_arrival_soc = current_soc - final_soc_drop_pct

        feasible = projected_arrival_soc >= reserve_soc

        total_charge_minutes = sum(s["charge_minutes"] for s in stops)
        total_detour_minutes = sum(s["detour_minutes"] for s in stops)
        total_detour_km = sum(s["detour_distance_km"] for s in stops)
        total_trip_minutes = (
            route_duration_min + total_detour_minutes + total_charge_minutes
        )
        total_trip_energy_kwh = (
            total_energy_kwh + total_detour_km * avg_consumption_kwh_per_km
        )

        # avg_speed kullanmasak da hesap dogru: route_duration_min zaten bitise
        # kadar olan tum suruyu kapsiyor.
        _ = avg_speed_kmh

        message = (
            f"{len(stops)} durakli plan olusturuldu. "
            f"Tahmini varis SOC: %{projected_arrival_soc:.1f}, "
            f"toplam sure: {total_trip_minutes:.1f} dk."
        )
        used_ml = bool(_pick(ml_summary, "used_ml", default=False))
        if used_ml:
            mv = _pick(ml_summary, "model_version", default=None)
            message += f" Tahmin kaynagi: ML ({mv})." if mv else " Tahmin kaynagi: ML."

        return {
            "status": "ok" if feasible else "risky_plan",
            "strategy": strategy,
            "needs_charging": True,
            "feasible": feasible,
            "recommended_stops": stops,
            "summary": {
                "stop_count": len(stops),
                "charge_minutes": round(total_charge_minutes, 1),
                "detour_minutes": round(total_detour_minutes, 1),
                "total_trip_minutes": round(total_trip_minutes, 1),
                "total_energy_kwh": round(total_trip_energy_kwh, 2),
                "projected_arrival_soc_percent": round(projected_arrival_soc, 2),
            },
            "ml_summary": ml_summary,
            "message": message,
        }

    def _enrich_all_stations(
        self,
        *,
        route_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Ham istasyonlara distance_along_route_km, power_kw vb. ekler."""
        raw_stations = (
            _pick(route_context, "stations", "charging_stations", default=[]) or []
        )
        if not raw_stations:
            return []

        route = _pick(route_context, "route", default={}) or {}
        route_points = self._build_route_points(route)

        enriched: List[Dict[str, Any]] = []
        for station in raw_stations:
            distance_along = _pick(
                station,
                "distance_along_route_km",
                "distance_from_start_km",
                default=None,
            )
            offset = _pick(
                station,
                "distance_from_route_km",
                "offset_km",
                "detour_km",
                default=None,
            )

            station_lat, station_lon = self._station_coords(station)

            if distance_along is None:
                if not route_points or station_lat is None or station_lon is None:
                    continue
                nearest = min(
                    route_points,
                    key=lambda p: _haversine_km(
                        station_lat, station_lon, p[0], p[1]
                    ),
                )
                distance_along = nearest[2]
                offset = _haversine_km(
                    station_lat, station_lon, nearest[0], nearest[1]
                )

            distance_along = _safe_float(distance_along, 0.0)
            offset = _safe_float(offset, 0.0)

            power_kw = self._station_power_kw(station)
            if power_kw <= 0:
                continue

            operational = bool(
                _pick(station, "is_operational", "available", default=True)
            )
            if not operational:
                continue

            name = _pick(station, "name", "title", default=None)
            if name is None:
                addr = _pick(station, "AddressInfo", default={}) or {}
                name = _pick(addr, "Title", default="İstasyon")

            enriched.append(
                {
                    **station,
                    "name": name,
                    "distance_along_route_km": distance_along,
                    "distance_from_route_km": offset,
                    "detour_distance_km": offset * 2.0,
                    "power_kw": power_kw,
                }
            )

        enriched.sort(key=lambda s: s["distance_along_route_km"])
        return enriched

    def _build_route_points(
        self,
        route: Dict[str, Any],
    ) -> List[tuple]:
        """Route geometry'den (lat, lon, cumulative_km) listesi cikarir."""
        raw_points = (
            _pick(route, "geometry", "points", "coordinates", default=[])
            or _pick(route, "polyline_points", default=[])
            or []
        )
        if not raw_points:
            return []

        parsed: List[tuple] = []
        for item in raw_points:
            if isinstance(item, dict):
                lat = _safe_float(_pick(item, "lat", "latitude"), 0.0)
                lon = _safe_float(_pick(item, "lon", "lng", "longitude"), 0.0)
                parsed.append((lat, lon))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                parsed.append((_safe_float(item[0]), _safe_float(item[1])))

        if not parsed:
            return []

        result: List[tuple] = []
        cumulative = 0.0
        prev: Optional[tuple] = None
        for lat, lon in parsed:
            if prev is not None:
                cumulative += _haversine_km(prev[0], prev[1], lat, lon)
            result.append((lat, lon, cumulative))
            prev = (lat, lon)
        return result

    def _station_coords(
        self,
        station: Dict[str, Any],
    ) -> tuple:
        """Hem flat hem AddressInfo iceren OCM formatlarindan koordinat cekme."""
        lat = _pick(station, "lat", "latitude", default=None)
        lon = _pick(station, "lon", "lng", "longitude", default=None)
        if lat is None or lon is None:
            addr = _pick(station, "AddressInfo", default={}) or {}
            lat = _pick(addr, "Latitude", default=lat)
            lon = _pick(addr, "Longitude", default=lon)
        if lat is None or lon is None:
            return None, None
        return _safe_float(lat, None), _safe_float(lon, None)

    def _station_power_kw(self, station: Dict[str, Any]) -> float:
        """Flat 'power_kw' yoksa Connections'dan en yukseki alir."""
        power = _safe_float(
            _pick(station, "power_kw", "max_power_kw", "dc_power_kw", default=None),
            0.0,
        )
        if power > 0:
            return power

        for collection_key in ("connections", "Connections"):
            conns = _pick(station, collection_key, default=None) or []
            for conn in conns:
                p = _safe_float(_pick(conn, "power_kw", "PowerKW", default=0.0), 0.0)
                if p > power:
                    power = p
        return power

    def _extract_ml_summary(
        self,
        *,
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
    ) -> Dict[str, Any]:
        used_ml = bool(
            _pick(
                charge_need,
                "used_ml",
                default=_pick(simulation_result, "used_ml", default=False),
            )
        )

        ml_segment_count = int(
            _safe_float(
                _pick(
                    charge_need,
                    "ml_segment_count",
                    default=_pick(simulation_result, "ml_segment_count", default=0),
                ),
                0,
            )
        )

        heuristic_segment_count = int(
            _safe_float(
                _pick(
                    charge_need,
                    "heuristic_segment_count",
                    default=_pick(
                        simulation_result,
                        "heuristic_segment_count",
                        default=0,
                    ),
                ),
                0,
            )
        )

        model_version = _pick(
            charge_need,
            "model_version",
            default=_pick(simulation_result, "model_version", default=None),
        )

        return {
            "used_ml": used_ml,
            "ml_segment_count": ml_segment_count,
            "heuristic_segment_count": heuristic_segment_count,
            "model_version": model_version,
        }

    def _extract_final_soc(self, simulation_result: Dict[str, Any]) -> float:
        direct_soc = _pick(
            simulation_result,
            "final_soc",
            "end_soc",
            "remaining_soc",
            default=None,
        )
        if direct_soc is not None:
            return _safe_float(direct_soc, 0.0)

        segments = _pick(simulation_result, "segments", "segment_results", default=[]) or []
        if segments:
            last_segment = segments[-1]
            return _safe_float(
                _pick(last_segment, "soc_after", "ending_soc", "end_soc", "remaining_soc"),
                0.0,
            )

        return 0.0

    def _resolve_avg_consumption(
        self,
        *,
        route_distance_km: float,
        total_energy_kwh: float,
        vehicle: Dict[str, Any],
    ) -> float:
        if route_distance_km > 0 and total_energy_kwh > 0:
            return total_energy_kwh / route_distance_km

        ideal_wh_km = _safe_float(_pick(vehicle, "ideal_consumption_wh_km"), 180.0)
        return ideal_wh_km / 1000.0

    def _build_message(
        self,
        *,
        station_name: str,
        feasible: bool,
        projected_arrival_soc_percent: float,
        total_trip_minutes: float,
        used_ml: bool = False,
        model_version: Optional[str] = None,
    ) -> str:
        prediction_note = ""
        if used_ml:
            if model_version:
                prediction_note = f" Tahmin kaynağı: ML ({model_version})."
            else:
                prediction_note = " Tahmin kaynağı: ML."

        if feasible:
            return (
                f"{station_name} ile tek duraklı plan oluşturuldu. "
                f"Tahmini varış SOC: %{projected_arrival_soc_percent:.1f}, "
                f"toplam süre: {total_trip_minutes:.1f} dk."
                f"{prediction_note}"
            )

        return (
            f"{station_name} seçilerek plan oluşturuldu ancak marj düşük görünüyor. "
            f"Tahmini varış SOC: %{projected_arrival_soc_percent:.1f}."
            f"{prediction_note}"
        )


def build_charging_plan(
    *,
    vehicle: Dict[str, Any],
    route_context: Dict[str, Any],
    simulation_result: Dict[str, Any],
    charge_need: Dict[str, Any],
    selector_result: Dict[str, Any],
    strategy: str = "balanced",
) -> Dict[str, Any]:
    planner = ChargingPlanner()
    return planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy=strategy,
    )


if __name__ == "__main__":
    vehicle = {
        "name": "Demo EV",
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
        "max_dc_charge_power_kw": 120,
    }

    route_context = {
        "route": {
            "distance_km": 300,
            "duration_min": 260,
        }
    }

    simulation_result = {
        "initial_soc": 80,
        "total_energy_kwh": 54,
        "used_ml": True,
        "ml_segment_count": 3,
        "heuristic_segment_count": 0,
        "model_version": "lgbm_v1",
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
        "used_ml": True,
        "ml_segment_count": 3,
        "heuristic_segment_count": 0,
        "model_version": "lgbm_v1",
    }

    selector_result = {
        "needs_charging": True,
        "selected_station": {
            "name": "Yakin Hizli Istasyon",
            "distance_along_route_km": 150,
            "remaining_distance_km": 150,
            "detour_distance_km": 3.0,
            "detour_minutes": 4.5,
            "soc_at_arrival_percent": 46.0,
            "target_soc_percent": 62.0,
            "charge_minutes": 11.0,
            "power_kw": 120,
        },
    }

    planner = ChargingPlanner()
    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy="balanced",
    )

    print(result)