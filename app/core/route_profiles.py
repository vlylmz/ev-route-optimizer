from __future__ import annotations

from pprint import pprint
from typing import Any, Dict, Iterable, List, Optional

from concurrent.futures import ThreadPoolExecutor

from app.core.charging_planner import ChargingPlanner
from app.core.charging_stop_selector import ChargingStopSelector
from app.core.utils import pick as _pick, safe_float as _safe_float


class RouteProfiles:
    """
    Faz 3/4 için çoklu rota profili üretir.

    Aynı route_context + simulation_result + charge_need
    üstünden 3 farklı strateji çıkarır:
    - fast      -> en kısa toplam süre odaklı
    - efficient -> en düşük enerji / düşük sapma odaklı
    - balanced  -> orta yol

    Ek olarak:
    - profile bazında ml_summary taşır
    - kart yapısına ML kullanım bilgisini ekler
    """

    STRATEGY_LABELS = {
        "fast": "Hizli",
        "efficient": "Verimli",
        "balanced": "Dengeli",
    }

    def __init__(
        self,
        *,
        charging_stop_selector: Optional[Any] = None,
        charging_planner: Optional[Any] = None,
    ) -> None:
        self.charging_stop_selector = charging_stop_selector or ChargingStopSelector()
        self.charging_planner = charging_planner or ChargingPlanner()

    def generate_profiles(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        strategies: Optional[Iterable[str]] = None,
        simulator: Optional[Any] = None,
        analyzer: Optional[Any] = None,
        vehicle_obj: Any = None,
        initial_soc: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        simulator + vehicle_obj + initial_soc verildiyse her strateji icin
        ayri simulate cagirir; bu yontemle hiz profili (fast/efficient/balanced)
        enerji tuketim farkina yansir. Aksi halde tek simulation_result tum
        modlar icin kullanilir (geri uyumluluk).
        """
        strategy_list = list(strategies or ["fast", "efficient", "balanced"])

        # Stratejileri paralel olarak isle. Selector + planner + curve_service
        # state'siz hesap; ML predict singleton ise thread-safe (joblib model
        # read-only). max_workers strateji sayisina baglandi.
        def _process(strategy: str) -> tuple:
            sim_for_strategy = simulation_result
            charge_need_for_strategy = charge_need

            if simulator is not None and vehicle_obj is not None and initial_soc is not None:
                strategy_sim_dict, strategy_charge_need = self._simulate_for_strategy(
                    simulator=simulator,
                    analyzer=analyzer,
                    vehicle_obj=vehicle_obj,
                    route_context=route_context,
                    initial_soc=initial_soc,
                    strategy=strategy,
                    fallback_charge_need=charge_need,
                )
                if strategy_sim_dict is not None:
                    sim_for_strategy = strategy_sim_dict
                if strategy_charge_need is not None:
                    charge_need_for_strategy = strategy_charge_need

            selector_result = self._run_selector(
                vehicle=vehicle,
                route_context=route_context,
                simulation_result=sim_for_strategy,
                charge_need=charge_need_for_strategy,
                strategy=strategy,
            )

            plan_result = self._run_planner(
                vehicle=vehicle,
                route_context=route_context,
                simulation_result=sim_for_strategy,
                charge_need=charge_need_for_strategy,
                selector_result=selector_result,
                strategy=strategy,
            )

            profile_ml_summary = self._extract_ml_summary(
                plan_result=plan_result,
                simulation_result=sim_for_strategy,
                charge_need=charge_need_for_strategy,
            )

            return strategy, {
                "key": strategy,
                "label": self.STRATEGY_LABELS.get(strategy, strategy.title()),
                **plan_result,
                "ml_summary": profile_ml_summary,
            }

        profiles: Dict[str, Dict[str, Any]] = {}
        if len(strategy_list) <= 1:
            for strategy in strategy_list:
                key, profile = _process(strategy)
                profiles[key] = profile
        else:
            with ThreadPoolExecutor(max_workers=len(strategy_list)) as pool:
                results = list(pool.map(_process, strategy_list))
            for key, profile in results:
                profiles[key] = profile

        profile_cards = self._build_profile_cards(profiles)
        feasible_profiles = self._feasible_profiles(profiles)

        best_by_time = self._best_profile_key(
            feasible_profiles or profiles,
            metric_path=("summary", "total_trip_minutes"),
        )
        best_by_energy = self._best_profile_key(
            feasible_profiles or profiles,
            metric_path=("summary", "total_energy_kwh"),
        )
        recommended_profile = self._choose_recommended_profile(profiles)

        status = "ok" if feasible_profiles else "no_feasible_profiles"

        profiles_using_ml = [
            key for key, profile in profiles.items()
            if bool(_pick(profile.get("ml_summary", {}), "used_ml", default=False))
        ]

        return {
            "status": status,
            "profiles": profiles,
            "profile_cards": profile_cards,
            "best_by_time": best_by_time,
            "best_by_energy": best_by_energy,
            "recommended_profile": recommended_profile,
            "profiles_using_ml": profiles_using_ml,
            "any_profile_used_ml": len(profiles_using_ml) > 0,
            "message": self._build_message(
                status=status,
                recommended_profile=recommended_profile,
                best_by_time=best_by_time,
                best_by_energy=best_by_energy,
            ),
        }

    def _simulate_for_strategy(
        self,
        *,
        simulator: Any,
        analyzer: Any,
        vehicle_obj: Any,
        route_context: Dict[str, Any],
        initial_soc: float,
        strategy: str,
        fallback_charge_need: Dict[str, Any],
    ) -> tuple:
        """Strateji bazli yeniden simulate + analyze. Hata olursa fallback.

        Eger fast modunda yuksek hiz nedeniyle istasyon gap'leri atlanmaz hale
        gelir ve plan kurulamazsa, simulator'a 'balanced' strategy ile cagri
        gonderilir (downgrade); bu sayede en azindan bir plan uretilir.
        """
        try:
            sim_obj = simulator.simulate(
                vehicle=vehicle_obj,
                route_context=route_context,
                start_soc_pct=initial_soc,
                strategy=strategy,
            )
        except Exception:
            return None, None

        sim_dict = self._dataclass_to_dict(sim_obj)

        charge_need_dict: Optional[Dict[str, Any]] = None
        if analyzer is not None:
            try:
                usable_battery_kwh = float(getattr(vehicle_obj, "usable_battery_kwh", 0.0))
                reserve_soc_pct = float(getattr(vehicle_obj, "soc_min_pct", 10.0))
                charge_need_obj = analyzer.analyze(
                    simulation=sim_obj,
                    usable_battery_kwh=usable_battery_kwh,
                    reserve_soc_pct=reserve_soc_pct,
                )
                charge_need_dict = self._dataclass_to_dict(charge_need_obj)
                # Kullanici override'i (ornegin target_arrival_soc_pct) korunsun.
                for key in ("target_arrival_soc_pct",):
                    if key in fallback_charge_need:
                        charge_need_dict[key] = fallback_charge_need[key]
            except Exception:
                charge_need_dict = None

        return sim_dict, charge_need_dict

    @staticmethod
    def _dataclass_to_dict(obj: Any) -> Dict[str, Any]:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)
        return {}

    def _run_selector(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        strategy: str,
    ) -> Dict[str, Any]:
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

        raise TypeError("charging_stop_selector kullanilabilir degil.")

    def _run_planner(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        selector_result: Dict[str, Any],
        strategy: str,
    ) -> Dict[str, Any]:
        planner = self.charging_planner

        if hasattr(planner, "build_plan") and callable(planner.build_plan):
            return planner.build_plan(
                vehicle=vehicle,
                route_context=route_context,
                simulation_result=simulation_result,
                charge_need=charge_need,
                selector_result=selector_result,
                strategy=strategy,
            )

        if callable(planner):
            return planner(
                vehicle=vehicle,
                route_context=route_context,
                simulation_result=simulation_result,
                charge_need=charge_need,
                selector_result=selector_result,
                strategy=strategy,
            )

        raise TypeError("charging_planner kullanilabilir degil.")

    def _extract_ml_summary(
        self,
        *,
        plan_result: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan_ml = _pick(plan_result, "ml_summary", default={}) or {}

        used_ml = bool(
            _pick(
                plan_ml,
                "used_ml",
                default=_pick(
                    charge_need,
                    "used_ml",
                    default=_pick(simulation_result, "used_ml", default=False),
                ),
            )
        )

        ml_segment_count = int(
            _safe_float(
                _pick(
                    plan_ml,
                    "ml_segment_count",
                    default=_pick(
                        charge_need,
                        "ml_segment_count",
                        default=_pick(simulation_result, "ml_segment_count", default=0),
                    ),
                ),
                0,
            )
        )

        heuristic_segment_count = int(
            _safe_float(
                _pick(
                    plan_ml,
                    "heuristic_segment_count",
                    default=_pick(
                        charge_need,
                        "heuristic_segment_count",
                        default=_pick(
                            simulation_result,
                            "heuristic_segment_count",
                            default=0,
                        ),
                    ),
                ),
                0,
            )
        )

        model_version = _pick(
            plan_ml,
            "model_version",
            default=_pick(
                charge_need,
                "model_version",
                default=_pick(simulation_result, "model_version", default=None),
            ),
        )

        return {
            "used_ml": used_ml,
            "ml_segment_count": ml_segment_count,
            "heuristic_segment_count": heuristic_segment_count,
            "model_version": model_version,
        }

    def _build_profile_cards(
        self,
        profiles: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []

        order = ["fast", "efficient", "balanced"]
        for key in order:
            if key not in profiles:
                continue

            profile = profiles[key]
            summary = _pick(profile, "summary", default={}) or {}
            ml_summary = _pick(profile, "ml_summary", default={}) or {}

            cards.append(
                {
                    "key": key,
                    "label": _pick(profile, "label", default=key.title()),
                    "status": _pick(profile, "status", default="unknown"),
                    "feasible": bool(_pick(profile, "feasible", default=False)),
                    "arrival_soc_percent": round(
                        _safe_float(
                            _pick(summary, "projected_arrival_soc_percent"),
                            0.0,
                        ),
                        2,
                    ),
                    "total_trip_minutes": round(
                        _safe_float(_pick(summary, "total_trip_minutes"), 0.0),
                        1,
                    ),
                    "charge_minutes": round(
                        _safe_float(_pick(summary, "charge_minutes"), 0.0),
                        1,
                    ),
                    "total_energy_kwh": round(
                        _safe_float(_pick(summary, "total_energy_kwh"), 0.0),
                        2,
                    ),
                    "stop_count": int(_safe_float(_pick(summary, "stop_count"), 0)),
                    "used_ml": bool(_pick(ml_summary, "used_ml", default=False)),
                    "ml_segment_count": int(
                        _safe_float(_pick(ml_summary, "ml_segment_count"), 0)
                    ),
                    "heuristic_segment_count": int(
                        _safe_float(_pick(ml_summary, "heuristic_segment_count"), 0)
                    ),
                    "model_version": _pick(ml_summary, "model_version", default=None),
                }
            )

        return cards

    def _feasible_profiles(
        self,
        profiles: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        return {
            key: profile
            for key, profile in profiles.items()
            if bool(_pick(profile, "feasible", default=False))
        }

    def _best_profile_key(
        self,
        profiles: Dict[str, Dict[str, Any]],
        *,
        metric_path: tuple[str, ...],
    ) -> Optional[str]:
        if not profiles:
            return None

        def read_metric(profile: Dict[str, Any]) -> float:
            value: Any = profile
            for part in metric_path:
                if not isinstance(value, dict):
                    return float("inf")
                value = value.get(part)
            return _safe_float(value, float("inf"))

        return min(profiles.keys(), key=lambda key: read_metric(profiles[key]))

    def _choose_recommended_profile(
        self,
        profiles: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        feasible = self._feasible_profiles(profiles)

        for preferred in ["balanced", "fast", "efficient"]:
            if preferred in feasible:
                return preferred

        if "balanced" in profiles:
            return "balanced"
        if "fast" in profiles:
            return "fast"
        if "efficient" in profiles:
            return "efficient"
        return None

    def _build_message(
        self,
        *,
        status: str,
        recommended_profile: Optional[str],
        best_by_time: Optional[str],
        best_by_energy: Optional[str],
    ) -> str:
        if status != "ok":
            return "Uygulanabilir profil bulunamadi."

        label = self.STRATEGY_LABELS.get(recommended_profile or "", recommended_profile)
        time_label = self.STRATEGY_LABELS.get(best_by_time or "", best_by_time)
        energy_label = self.STRATEGY_LABELS.get(best_by_energy or "", best_by_energy)

        return (
            f"Onerilen profil: {label}. "
            f"En hizli: {time_label}. "
            f"En verimli: {energy_label}."
        )


def build_route_profiles(
    *,
    vehicle: Dict[str, Any],
    route_context: Dict[str, Any],
    simulation_result: Dict[str, Any],
    charge_need: Dict[str, Any],
) -> Dict[str, Any]:
    engine = RouteProfiles()
    return engine.generate_profiles(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
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
        ],
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

    engine = RouteProfiles()
    result = engine.generate_profiles(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
    )

    pprint(result)