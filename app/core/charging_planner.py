from __future__ import annotations

from pprint import pprint
from typing import Any, Dict, Optional


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


class ChargingPlanner:
    """
    charging_stop_selector sonucunu alir ve uygulanabilir
    tek durakli bir sarj plani uretir.

    Bu katman:
    - final trip metrics hesaplar
    - durak listesini normalize eder
    - toplam sure / toplam enerji / tahmini varis SOC dondurur

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
            _pick(charge_need, "needs_charging", "requires_charging", default=False)
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
                "message": "Uygun bir şarj planı oluşturulamadı.",
            }

        reserve_soc = _safe_float(
            _pick(
                charge_need,
                "reserve_soc_percent",
                "min_soc_percent",
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

        return {
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
            "message": self._build_message(
                station_name=station_name,
                feasible=feasible,
                projected_arrival_soc_percent=projected_arrival_soc_percent,
                total_trip_minutes=total_trip_minutes,
            ),
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
    ) -> str:
        if feasible:
            return (
                f"{station_name} ile tek duraklı plan oluşturuldu. "
                f"Tahmini varış SOC: %{projected_arrival_soc_percent:.1f}, "
                f"toplam süre: {total_trip_minutes:.1f} dk."
            )

        return (
            f"{station_name} seçilerek plan oluşturuldu ancak marj düşük görünüyor. "
            f"Tahmini varış SOC: %{projected_arrival_soc_percent:.1f}."
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