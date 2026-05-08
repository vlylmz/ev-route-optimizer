from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Optional

from app.core.charging_stop_selector import ChargingStopSelector
from app.core.protocols import (
    IChargeNeedAnalyzer,
    IRouteContextService,
    IRouteEnergySimulator,
)


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


def _to_plain(obj: Any) -> Any:
    if is_dataclass(obj):
        return _to_plain(asdict(obj))
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_plain(v) for v in obj]
    return obj


class RoutePlanner:
    """
    Mevcut zinciri tek noktada birleştiren orkestrasyon katmanı.

    Desteklediği akışlar:
    - Eski dict tabanlı servisler
    - Yeni dataclass tabanlı simulator / analyzer
    """

    def __init__(
        self,
        *,
        route_context_service: IRouteContextService,
        route_energy_simulator: IRouteEnergySimulator,
        charge_need_analyzer: IChargeNeedAnalyzer,
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
        vehicle: Any,
        initial_soc: float,
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        route_context = self._build_route_context(start=start, end=end)

        simulation_result_raw = self._simulate_route(
            vehicle=vehicle,
            route_context=route_context,
            initial_soc=initial_soc,
            strategy=strategy,
        )
        simulation_result = self._normalize_simulation_result(simulation_result_raw)

        charge_need_raw = self._analyze_charge_need(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result_raw=simulation_result_raw,
            simulation_result=simulation_result,
        )
        charge_need = self._normalize_charge_need(
            charge_need_raw=charge_need_raw,
            simulation_result=simulation_result,
            vehicle=vehicle,
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
        vehicle: Any,
        route_context: Dict[str, Any],
        initial_soc: float,
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        simulation_result_raw = self._simulate_route(
            vehicle=vehicle,
            route_context=route_context,
            initial_soc=initial_soc,
            strategy=strategy,
        )
        simulation_result = self._normalize_simulation_result(simulation_result_raw)

        charge_need_raw = self._analyze_charge_need(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result_raw=simulation_result_raw,
            simulation_result=simulation_result,
        )
        charge_need = self._normalize_charge_need(
            charge_need_raw=charge_need_raw,
            simulation_result=simulation_result,
            vehicle=vehicle,
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
        return self.route_context_service.build_route_context(start=start, end=end)

    def _simulate_route(
        self,
        *,
        vehicle: Any,
        route_context: Dict[str, Any],
        initial_soc: float,
        strategy: str = "balanced",
    ) -> Any:
        return self.route_energy_simulator.simulate(
            vehicle=vehicle,
            route_context=route_context,
            start_soc_pct=initial_soc,
            strategy=strategy,
        )

    def _analyze_charge_need(
        self,
        *,
        vehicle: Any,
        route_context: Dict[str, Any],
        simulation_result_raw: Any,
        simulation_result: Dict[str, Any],
    ) -> Any:
        # route_context kanonik analyze imzasinda kullanilmiyor; signature
        # uyumu icin imzada tutuluyor.
        del route_context
        del simulation_result

        usable_battery_kwh = self._vehicle_usable_battery_kwh(vehicle)
        reserve_soc_pct = self._vehicle_reserve_soc_pct(vehicle)

        return self.charge_need_analyzer.analyze(
            simulation=simulation_result_raw,
            usable_battery_kwh=usable_battery_kwh,
            reserve_soc_pct=reserve_soc_pct,
        )

    def _select_charging_stop(
        self,
        *,
        vehicle: Any,
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        strategy: str,
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
                vehicle=self._vehicle_to_selector_payload(vehicle),
                route_context=route_context,
                simulation_result=simulation_result,
                charge_need=charge_need,
                strategy=strategy,
            )

        if callable(selector):
            return selector(
                vehicle=self._vehicle_to_selector_payload(vehicle),
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
        vehicle: Any,
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
                "name": self._vehicle_name(vehicle),
                "usable_battery_kwh": round(self._vehicle_usable_battery_kwh(vehicle), 2),
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
            "ml_summary": {
                "used_ml": bool(_pick(simulation_result, "used_ml", default=False)),
                "ml_segment_count": int(_safe_float(_pick(simulation_result, "ml_segment_count"), 0)),
                "heuristic_segment_count": int(_safe_float(_pick(simulation_result, "heuristic_segment_count"), 0)),
                "model_version": _pick(simulation_result, "model_version", default=None),
            },
            "charge_need": charge_need,
            "charging_plan": charging_plan,
            "raw": {
                "route_context": route_context,
                "simulation_result": simulation_result,
            },
        }

    def _normalize_simulation_result(self, simulation_result: Any) -> Dict[str, Any]:
        raw = _to_plain(simulation_result)

        if not isinstance(raw, dict):
            return {}

        segments = raw.get("segments") or raw.get("segment_results") or []
        normalized_segments: List[Dict[str, Any]] = []

        prev_cumulative = 0.0
        cumulative = 0.0

        for index, seg in enumerate(segments, start=1):
            if not isinstance(seg, dict):
                continue

            seg_distance = _safe_float(
                _pick(seg, "distance_km", "segment_length_km", "length_km"),
                0.0,
            )

            cumulative_distance = _pick(seg, "cumulative_distance_km", default=None)
            if cumulative_distance is not None:
                cumulative = _safe_float(cumulative_distance, prev_cumulative)
                if seg_distance <= 0:
                    seg_distance = max(cumulative - prev_cumulative, 0.0)
            else:
                cumulative = prev_cumulative + seg_distance

            normalized_segments.append(
                {
                    **seg,
                    "segment_no": int(_safe_float(_pick(seg, "segment_no"), index)),
                    "distance_km": seg_distance,
                    "cumulative_distance_km": cumulative,
                    "soc_after": _safe_float(
                        _pick(seg, "soc_after", "end_soc_pct", "end_soc", "remaining_soc"),
                        0.0,
                    ),
                    "soc_before": _safe_float(
                        _pick(seg, "soc_before", "start_soc_pct", "start_soc"),
                        0.0,
                    ),
                }
            )
            prev_cumulative = cumulative

        initial_soc = _safe_float(
            _pick(raw, "initial_soc", "start_soc_pct"),
            0.0,
        )

        final_soc = _pick(raw, "final_soc", "end_soc_pct", "remaining_soc", default=None)
        if final_soc is None and normalized_segments:
            final_soc = normalized_segments[-1]["soc_after"]

        return {
            **raw,
            "initial_soc": initial_soc,
            "final_soc": _safe_float(final_soc, 0.0),
            "total_energy_kwh": _safe_float(
                _pick(raw, "total_energy_kwh", "energy_used_kwh"),
                0.0,
            ),
            "used_ml": bool(_pick(raw, "used_ml", default=False)),
            "ml_segment_count": int(_safe_float(_pick(raw, "ml_segment_count"), 0)),
            "heuristic_segment_count": int(_safe_float(_pick(raw, "heuristic_segment_count"), 0)),
            "model_version": _pick(raw, "model_version", default=None),
            "segments": normalized_segments,
        }

    def _normalize_charge_need(
        self,
        *,
        charge_need_raw: Any,
        simulation_result: Dict[str, Any],
        vehicle: Any,
    ) -> Dict[str, Any]:
        raw = _to_plain(charge_need_raw)
        if not isinstance(raw, dict):
            raw = {}

        if "needs_charging" in raw or "requires_charging" in raw:
            normalized = dict(raw)
        else:
            normalized = {
                **raw,
                "needs_charging": bool(_pick(raw, "charging_required", default=False)),
                "reserve_soc_percent": _safe_float(
                    _pick(raw, "reserve_soc_pct"),
                    self._vehicle_reserve_soc_pct(vehicle),
                ),
                "min_soc_percent": _safe_float(
                    _pick(raw, "minimum_soc_pct", "end_soc_pct"),
                    _safe_float(_pick(simulation_result, "final_soc"), 0.0),
                ),
                "critical_segment_no": _pick(raw, "critical_segment_no", default=None),
                "estimated_additional_soc_needed_pct": _safe_float(
                    _pick(raw, "estimated_additional_soc_needed_pct"),
                    0.0,
                ),
                "estimated_additional_energy_needed_kwh": _safe_float(
                    _pick(raw, "estimated_additional_energy_needed_kwh"),
                    0.0,
                ),
                "recommendation": _pick(raw, "recommendation", default=""),
                "used_ml": bool(_pick(raw, "used_ml", default=_pick(simulation_result, "used_ml", default=False))),
                "ml_segment_count": int(_safe_float(_pick(raw, "ml_segment_count", default=_pick(simulation_result, "ml_segment_count", default=0)), 0)),
                "heuristic_segment_count": int(_safe_float(_pick(raw, "heuristic_segment_count", default=_pick(simulation_result, "heuristic_segment_count", default=0)), 0)),
                "model_version": _pick(raw, "model_version", default=_pick(simulation_result, "model_version", default=None)),
            }

        if "critical_distance_km" not in normalized or normalized["critical_distance_km"] is None:
            critical_segment_no = _pick(normalized, "critical_segment_no", default=None)
            normalized["critical_distance_km"] = self._critical_distance_from_segment_no(
                simulation_result=simulation_result,
                critical_segment_no=critical_segment_no,
            )

        if "reserve_soc_percent" not in normalized or normalized["reserve_soc_percent"] is None:
            normalized["reserve_soc_percent"] = self._vehicle_reserve_soc_pct(vehicle)

        if "min_soc_percent" not in normalized or normalized["min_soc_percent"] is None:
            normalized["min_soc_percent"] = _safe_float(
                _pick(normalized, "minimum_soc_pct"),
                _safe_float(_pick(simulation_result, "final_soc"), 0.0),
            )

        return normalized

    def _critical_distance_from_segment_no(
        self,
        *,
        simulation_result: Dict[str, Any],
        critical_segment_no: Any,
    ) -> Optional[float]:
        if critical_segment_no is None:
            return None

        try:
            critical_segment_no = int(critical_segment_no)
        except (TypeError, ValueError):
            return None

        segments = _pick(simulation_result, "segments", default=[]) or []
        for seg in segments:
            if int(_safe_float(_pick(seg, "segment_no"), 0)) == critical_segment_no:
                return _safe_float(_pick(seg, "cumulative_distance_km"), None)

        return None

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

    def _vehicle_name(self, vehicle: Any) -> str:
        if isinstance(vehicle, dict):
            return str(_pick(vehicle, "name", "model", default="unknown"))
        if hasattr(vehicle, "full_name"):
            return str(vehicle.full_name)
        if hasattr(vehicle, "model"):
            return str(getattr(vehicle, "model"))
        return "unknown"

    def _vehicle_usable_battery_kwh(self, vehicle: Any) -> float:
        if isinstance(vehicle, dict):
            return _safe_float(_pick(vehicle, "usable_battery_kwh", "battery_capacity_kwh"), 0.0)
        if hasattr(vehicle, "usable_battery_kwh"):
            return _safe_float(getattr(vehicle, "usable_battery_kwh"), 0.0)
        if hasattr(vehicle, "battery_capacity_kwh"):
            return _safe_float(getattr(vehicle, "battery_capacity_kwh"), 0.0)
        return 0.0

    def _vehicle_reserve_soc_pct(self, vehicle: Any) -> float:
        if isinstance(vehicle, dict):
            return _safe_float(
                _pick(vehicle, "routing_reserve_soc_pct", "soc_min_pct"),
                10.0,
            )
        if hasattr(vehicle, "routing_reserve_soc_pct"):
            return _safe_float(getattr(vehicle, "routing_reserve_soc_pct"), 10.0)
        if hasattr(vehicle, "soc_min_pct"):
            return _safe_float(getattr(vehicle, "soc_min_pct"), 10.0)
        return 10.0

    def _vehicle_to_selector_payload(self, vehicle: Any) -> Dict[str, Any]:
        if isinstance(vehicle, dict):
            return dict(vehicle)

        payload = {
            "name": self._vehicle_name(vehicle),
            "usable_battery_kwh": self._vehicle_usable_battery_kwh(vehicle),
            "ideal_consumption_wh_km": _safe_float(
                getattr(vehicle, "ideal_consumption_wh_km", 180.0),
                180.0,
            ),
            "max_dc_charge_power_kw": _safe_float(
                getattr(vehicle, "max_dc_charge_kw", getattr(vehicle, "max_dc_charge_power_kw", 50.0)),
                50.0,
            ),
        }

        if hasattr(vehicle, "id"):
            payload["id"] = getattr(vehicle, "id")
            payload["vehicle_id"] = getattr(vehicle, "id")

        if hasattr(vehicle, "temp_penalty_factor"):
            payload["temp_penalty_factor"] = getattr(vehicle, "temp_penalty_factor")

        return payload

