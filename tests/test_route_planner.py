from app.core.route_planner import RoutePlanner


class FakeRouteContextService:
    def build_route_context(self, *, start, end, **opts):
        return {
            "start": start,
            "end": end,
            "route": {
                "distance_km": 300,
                "duration_min": 260,
            },
            "stations": [
                {
                    "name": "Ankara DC",
                    "distance_along_route_km": 150,
                    "distance_from_route_km": 1.0,
                    "power_kw": 120,
                    "is_operational": True,
                }
            ],
        }


class FakeRouteEnergySimulator:
    def simulate(self, *, vehicle, route_context, start_soc_pct, use_ml=None):
        return {
            "initial_soc": start_soc_pct,
            "total_energy_kwh": 52,
            "segments": [
                {"cumulative_distance_km": 100, "soc_after": 58},
                {"cumulative_distance_km": 200, "soc_after": 30},
                {"cumulative_distance_km": 300, "soc_after": 8},
            ],
        }


class FakeChargeNeedAnalyzerNeedCharge:
    def analyze(self, *, simulation, usable_battery_kwh, reserve_soc_pct):
        return {
            "needs_charging": True,
            "critical_distance_km": 220,
            "reserve_soc_percent": reserve_soc_pct,
        }


class FakeChargeNeedAnalyzerNoCharge:
    def analyze(self, *, simulation, usable_battery_kwh, reserve_soc_pct):
        return {
            "needs_charging": False,
            "critical_distance_km": None,
            "reserve_soc_percent": reserve_soc_pct,
        }


class FakeSelector:
    def __init__(self):
        self.called = False

    def select_stop(self, *, vehicle, route_context, simulation_result, charge_need, strategy):
        self.called = True
        return {
            "needs_charging": True,
            "selected_station": {
                "name": "Ankara DC",
                "score": 12.4,
            },
            "candidates": [
                {
                    "name": "Ankara DC",
                    "score": 12.4,
                }
            ],
            "message": "Ankara DC seçildi.",
        }


def test_route_planner_returns_station_when_charge_is_needed():
    selector = FakeSelector()

    planner = RoutePlanner(
        route_context_service=FakeRouteContextService(),
        route_energy_simulator=FakeRouteEnergySimulator(),
        charge_need_analyzer=FakeChargeNeedAnalyzerNeedCharge(),
        charging_stop_selector=selector,
    )

    vehicle = {
        "name": "Test EV",
        "usable_battery_kwh": 60,
    }

    result = planner.plan(
        start="Ankara",
        end="Eskisehir",
        vehicle=vehicle,
        initial_soc=80,
        strategy="balanced",
    )

    assert result["status"] == "ok"
    assert result["charging_plan"]["needs_charging"] is True
    assert result["charging_plan"]["selected_station"]["name"] == "Ankara DC"
    assert selector.called is True


def test_route_planner_skips_selector_when_charge_not_needed():
    selector = FakeSelector()

    planner = RoutePlanner(
        route_context_service=FakeRouteContextService(),
        route_energy_simulator=FakeRouteEnergySimulator(),
        charge_need_analyzer=FakeChargeNeedAnalyzerNoCharge(),
        charging_stop_selector=selector,
    )

    vehicle = {
        "name": "Test EV",
        "usable_battery_kwh": 60,
    }

    result = planner.plan(
        start="Ankara",
        end="Eskisehir",
        vehicle=vehicle,
        initial_soc=95,
        strategy="balanced",
    )

    assert result["status"] == "ok"
    assert result["charging_plan"]["needs_charging"] is False
    assert result["charging_plan"]["selected_station"] is None
    assert selector.called is False
def test_route_planner_propagates_ml_summary():
    class FakeRouteEnergySimulatorWithML:
        def simulate(self, *, vehicle, route_context, start_soc_pct, use_ml=None):
            return {
                "initial_soc": start_soc_pct,
                "final_soc": 18,
                "total_energy_kwh": 48,
                "used_ml": True,
                "ml_segment_count": 3,
                "heuristic_segment_count": 0,
                "model_version": "lgbm_v1",
                "segments": [
                    {"cumulative_distance_km": 100, "soc_after": 58},
                    {"cumulative_distance_km": 200, "soc_after": 36},
                    {"cumulative_distance_km": 300, "soc_after": 18},
                ],
            }

    class FakeChargeNeedAnalyzerNoCharge:
        def analyze(self, *, simulation, usable_battery_kwh, reserve_soc_pct):
            return {
                "needs_charging": False,
                "critical_distance_km": None,
                "reserve_soc_percent": reserve_soc_pct,
            }

    planner = RoutePlanner(
        route_context_service=FakeRouteContextService(),
        route_energy_simulator=FakeRouteEnergySimulatorWithML(),
        charge_need_analyzer=FakeChargeNeedAnalyzerNoCharge(),
        charging_stop_selector=FakeSelector(),
    )

    vehicle = {
        "name": "Test EV",
        "usable_battery_kwh": 60,
    }

    result = planner.plan(
        start="Ankara",
        end="Eskisehir",
        vehicle=vehicle,
        initial_soc=80,
        strategy="balanced",
    )

    assert result["ml_summary"]["used_ml"] is True
    assert result["ml_summary"]["ml_segment_count"] == 3
    assert result["ml_summary"]["heuristic_segment_count"] == 0
    assert result["ml_summary"]["model_version"] == "lgbm_v1"


def test_route_planner_raises_clearly_when_simulator_misimplements_interface():
    """Imzasi uymayan fake simulator -> TypeError (sessizce yutulmuyor)."""
    import pytest

    class BrokenSimulator:
        # Eksik kw 'route_context' ve 'start_soc_pct' yerine farkli isim.
        def simulate(self, *, vehicle, ctx, soc):
            return {}

    planner = RoutePlanner(
        route_context_service=FakeRouteContextService(),
        route_energy_simulator=BrokenSimulator(),
        charge_need_analyzer=FakeChargeNeedAnalyzerNoCharge(),
        charging_stop_selector=FakeSelector(),
    )

    with pytest.raises(TypeError):
        planner.plan(
            start="Ankara",
            end="Eskisehir",
            vehicle={"name": "Test EV", "usable_battery_kwh": 60},
            initial_soc=80,
            strategy="balanced",
        )