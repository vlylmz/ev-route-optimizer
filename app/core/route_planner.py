from __future__ import annotations

from pprint import pprint
from typing import Any, Dict, Iterable, List, Optional

from app.core.charging_stop_selector import ChargingStopSelector


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


class RoutePlanner:
    """
    Mevcut zinciri tek noktada birleştiren orkestrasyon katmanı.

    Akış:
    start/end
      -> route_context_service
      -> route_energy_simulator
      -> charge_need_analyzer
      -> charging_stop_selector
      -> birleşik plan çıktısı
    """

    def __init__(
        self,
        *,
        route_context_service: Any,
        route_energy_simulator: Any,
        charge_need_analyzer: Any,
        charging_stop_selector: Optional[Any] = None,
    ) -> None:
        self.route_context_service = route_context_service
        self.route_energy_simulator = route_energy_simulator
        self.charge_need_analyzer = charge_need_analyzer
        self.charging_stop_selector = charging_stop_selector or ChargingStopSelector()

    def plan(
        self,
        *,
        start: Any,
        end: Any,
        vehicle: Dict[str, Any],
        initial_soc: float,
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        route_context = self._build_route_context(start=start, end=end)

        simulation_result = self._simulate_route(
            vehicle=vehicle,
            route_context=route_context,
            initial_soc=initial_soc,
        )

        charge_need = self._analyze_charge_need(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result=simulation_result,
        )

        charging_plan = self._select_charging_stop(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result=simulation_result,
            charge_need=charge_need,
            strategy=strategy,
        )

        return self._assemble_result(
            start=start,
            end=end,
            vehicle=vehicle,
            initial_soc=initial_soc,
            route_context=route_context,
            simulation_result=simulation_result,
            charge_need=charge_need,
            charging_plan=charging_plan,
            strategy=strategy,
        )

    def plan_from_context(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        initial_soc: float,
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        simulation_result = self._simulate_route(
            vehicle=vehicle,
            route_context=route_context,
            initial_soc=initial_soc,
        )

        charge_need = self._analyze_charge_need(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result=simulation_result,
        )

        charging_plan = self._select_charging_stop(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result=simulation_result,
            charge_need=charge_need,
            strategy=strategy,
        )

        return self._assemble_result(
            start=_pick(route_context, "start", "origin", default="unknown"),
            end=_pick(route_context, "end", "destination", default="unknown"),
            vehicle=vehicle,
            initial_soc=initial_soc,
            route_context=route_context,
            simulation_result=simulation_result,
            charge_need=charge_need,
            charging_plan=charging_plan,
            strategy=strategy,
        )

    def _build_route_context(self, *, start: Any, end: Any) -> Dict[str, Any]:
        return self._call_first_supported(
            service=self.route_context_service,
            method_names=[
                "build_route_context",
                "get_route_context",
                "create_route_context",
            ],
            kwargs_options=[
                {"start": start, "end": end},
                {"origin": start, "destination": end},
                {"start_point": start, "end_point": end},
            ],
            service_name="route_context_service",
        )

    def _simulate_route(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        initial_soc: float,
    ) -> Dict[str, Any]:
        return self._call_first_supported(
            service=self.route_energy_simulator,
            method_names=[
                "simulate",
                "simulate_route",
                "run",
            ],
            kwargs_options=[
                {
                    "vehicle": vehicle,
                    "route_context": route_context,
                    "initial_soc": initial_soc,
                },
                {
                    "vehicle": vehicle,
                    "route": route_context,
                    "initial_soc": initial_soc,
                },
                {
                    "vehicle": vehicle,
                    "context": route_context,
                    "initial_soc": initial_soc,
                },
            ],
            service_name="route_energy_simulator",
        )

    def _analyze_charge_need(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self._call_first_supported(
            service=self.charge_need_analyzer,
            method_names=[
                "analyze",
                "analyze_need",
                "evaluate",
            ],
            kwargs_options=[
                {
                    "vehicle": vehicle,
                    "route_context": route_context,
                    "simulation_result": simulation_result,
                },
                {
                    "vehicle": vehicle,
                    "route": route_context,
                    "simulation": simulation_result,
                },
                {
                    "vehicle": vehicle,
                    "context": route_context,
                    "result": simulation_result,
                },
            ],
            service_name="charge_need_analyzer",
        )

    def _select_charging_stop(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        strategy: str,
    ) -> Dict[str, Any]:
        needs_charging = bool(
            _pick(charge_need, "needs_charging", "requires_charging", default=False)
        )

        if not needs_charging:
            return {
                "needs_charging": False,
                "selected_station": None,
                "candidates": [],
                "message": "Şarj gerekmiyor.",
            }

        selector = self.charging_stop_selector

        if hasattr(selector, "select_stop") and callable(selector.select_stop):
            return selector.select_stop(
                vehicle=vehicle,
                route_context=route_context,
                simulation_result=simulation_result,
                charge_need=charge_need,
                strategy=strategy,
            )

        if callable(selector):
            return selector(
                vehicle=vehicle,
                route_context=route_context,
                simulation_result=simulation_result,
                charge_need=charge_need,
                strategy=strategy,
            )

        raise TypeError("charging_stop_selector kullanılabilir bir nesne değil.")

    def _assemble_result(
        self,
        *,
        start: Any,
        end: Any,
        vehicle: Dict[str, Any],
        initial_soc: float,
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        charging_plan: Dict[str, Any],
        strategy: str,
    ) -> Dict[str, Any]:
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

        final_soc = self._extract_final_soc(simulation_result)

        return {
            "status": "ok",
            "start": start,
            "end": end,
            "strategy": strategy,
            "vehicle": {
                "name": _pick(vehicle, "name", "model", default="unknown"),
                "usable_battery_kwh": _safe_float(
                    _pick(vehicle, "usable_battery_kwh", "battery_capacity_kwh"),
                    0.0,
                ),
            },
            "route_summary": {
                "distance_km": round(route_distance_km, 2),
                "duration_min": round(route_duration_min, 1),
            },
            "simulation_summary": {
                "initial_soc_percent": round(initial_soc, 2),
                "final_soc_percent": round(final_soc, 2),
                "total_energy_kwh": round(total_energy_kwh, 2),
            },
            "charge_need": charge_need,
            "charging_plan": charging_plan,
            "raw": {
                "route_context": route_context,
                "simulation_result": simulation_result,
            },
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

    def _call_first_supported(
        self,
        *,
        service: Any,
        method_names: Iterable[str],
        kwargs_options: List[Dict[str, Any]],
        service_name: str,
    ) -> Dict[str, Any]:
        for method_name in method_names:
            method = getattr(service, method_name, None)
            if not callable(method):
                continue

            for kwargs in kwargs_options:
                try:
                    result = method(**kwargs)
                    if result is None:
                        continue
                    return result
                except TypeError:
                    continue

        available = [
            name for name in dir(service)
            if not name.startswith("_") and callable(getattr(service, name))
        ]
        raise AttributeError(
            f"{service_name} için uygun method bulunamadı. "
            f"Denenen methodlar: {list(method_names)} | "
            f"Mevcut callables: {available}"
        )


# -------------------------------------------------------------------
# Aşağısı sadece python -m app.core.route_planner ile hızlı deneme için
# -------------------------------------------------------------------

class _DemoRouteContextService:
    def build_route_context(self, start: Any, end: Any) -> Dict[str, Any]:
        return {
            "start": start,
            "end": end,
            "route": {
                "distance_km": 300,
                "duration_min": 260,
                "geometry": [
                    {"lat": 39.0, "lon": 32.0},
                    {"lat": 39.2, "lon": 32.2},
                    {"lat": 39.4, "lon": 32.4},
                    {"lat": 39.6, "lon": 32.6},
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
            ],
        }


class _DemoRouteEnergySimulator:
    def simulate(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        initial_soc: float,
    ) -> Dict[str, Any]:
        return {
            "initial_soc": initial_soc,
            "total_energy_kwh": 54,
            "segments": [
                {"cumulative_distance_km": 100, "soc_after": 60},
                {"cumulative_distance_km": 200, "soc_after": 32},
                {"cumulative_distance_km": 300, "soc_after": 6},
            ],
        }


class _DemoChargeNeedAnalyzer:
    def analyze(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        final_soc = _safe_float(_pick(simulation_result, "final_soc"), -1.0)
        if final_soc < 0:
            segments = simulation_result.get("segments", [])
            if segments:
                final_soc = _safe_float(segments[-1].get("soc_after"), 0.0)
            else:
                final_soc = 0.0

        if final_soc > 10:
            return {
                "needs_charging": False,
                "critical_distance_km": None,
                "reserve_soc_percent": 10,
            }

        return {
            "needs_charging": True,
            "critical_distance_km": 210,
            "reserve_soc_percent": 10,
        }


if __name__ == "__main__":
    vehicle = {
        "name": "Demo EV",
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
        "max_dc_charge_power_kw": 120,
    }

    planner = RoutePlanner(
        route_context_service=_DemoRouteContextService(),
        route_energy_simulator=_DemoRouteEnergySimulator(),
        charge_need_analyzer=_DemoChargeNeedAnalyzer(),
        charging_stop_selector=ChargingStopSelector(),
    )

    result = planner.plan(
        start="Ankara",
        end="Eskisehir",
        vehicle=vehicle,
        initial_soc=80,
        strategy="balanced",
    )

    pprint(result)