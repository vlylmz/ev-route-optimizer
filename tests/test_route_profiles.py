from app.core.route_profiles import RouteProfiles


class FakeSelector:
    def select_stop(
        self,
        *,
        vehicle,
        route_context,
        simulation_result,
        charge_need,
        strategy,
    ):
        station_names = {
            "fast": "Fast DC",
            "efficient": "Eco Station",
            "balanced": "Balanced Hub",
        }

        return {
            "needs_charging": True,
            "selected_station": {
                "name": station_names[strategy],
                "distance_along_route_km": 150,
                "remaining_distance_km": 150,
                "detour_distance_km": 2.0 if strategy == "fast" else 1.0,
                "detour_minutes": 3.0 if strategy == "fast" else 2.0,
                "soc_at_arrival_percent": 45.0,
                "target_soc_percent": 62.0,
                "charge_minutes": 10.0 if strategy == "fast" else 14.0,
                "power_kw": 120 if strategy == "fast" else 60,
            },
            "candidates": [],
            "message": "ok",
        }


class FakeChargingPlanner:
    def build_plan(
        self,
        *,
        vehicle,
        route_context,
        simulation_result,
        charge_need,
        selector_result,
        strategy,
    ):
        profiles = {
            "fast": {
                "status": "ok",
                "strategy": "fast",
                "needs_charging": True,
                "feasible": True,
                "recommended_stops": [{"name": "Fast DC"}],
                "summary": {
                    "stop_count": 1,
                    "charge_minutes": 10.0,
                    "detour_minutes": 3.0,
                    "total_trip_minutes": 275.0,
                    "total_energy_kwh": 57.0,
                    "projected_arrival_soc_percent": 14.0,
                },
            },
            "efficient": {
                "status": "ok",
                "strategy": "efficient",
                "needs_charging": True,
                "feasible": True,
                "recommended_stops": [{"name": "Eco Station"}],
                "summary": {
                    "stop_count": 1,
                    "charge_minutes": 14.0,
                    "detour_minutes": 2.0,
                    "total_trip_minutes": 282.0,
                    "total_energy_kwh": 55.0,
                    "projected_arrival_soc_percent": 16.0,
                },
            },
            "balanced": {
                "status": "ok",
                "strategy": "balanced",
                "needs_charging": True,
                "feasible": True,
                "recommended_stops": [{"name": "Balanced Hub"}],
                "summary": {
                    "stop_count": 1,
                    "charge_minutes": 12.0,
                    "detour_minutes": 2.5,
                    "total_trip_minutes": 278.0,
                    "total_energy_kwh": 56.0,
                    "projected_arrival_soc_percent": 15.0,
                },
            },
        }
        return profiles[strategy]


class FakeChargingPlannerBalancedRisky:
    def build_plan(
        self,
        *,
        vehicle,
        route_context,
        simulation_result,
        charge_need,
        selector_result,
        strategy,
    ):
        base = {
            "fast": {
                "status": "ok",
                "strategy": "fast",
                "needs_charging": True,
                "feasible": True,
                "recommended_stops": [{"name": "Fast DC"}],
                "summary": {
                    "stop_count": 1,
                    "charge_minutes": 10.0,
                    "detour_minutes": 3.0,
                    "total_trip_minutes": 275.0,
                    "total_energy_kwh": 57.0,
                    "projected_arrival_soc_percent": 14.0,
                },
            },
            "efficient": {
                "status": "ok",
                "strategy": "efficient",
                "needs_charging": True,
                "feasible": True,
                "recommended_stops": [{"name": "Eco Station"}],
                "summary": {
                    "stop_count": 1,
                    "charge_minutes": 14.0,
                    "detour_minutes": 2.0,
                    "total_trip_minutes": 282.0,
                    "total_energy_kwh": 55.0,
                    "projected_arrival_soc_percent": 16.0,
                },
            },
            "balanced": {
                "status": "risky_plan",
                "strategy": "balanced",
                "needs_charging": True,
                "feasible": False,
                "recommended_stops": [{"name": "Balanced Hub"}],
                "summary": {
                    "stop_count": 1,
                    "charge_minutes": 12.0,
                    "detour_minutes": 2.5,
                    "total_trip_minutes": 278.0,
                    "total_energy_kwh": 56.0,
                    "projected_arrival_soc_percent": 6.0,
                },
            },
        }
        return base[strategy]


def build_common_inputs():
    vehicle = {
        "name": "Test EV",
        "usable_battery_kwh": 60,
    }

    route_context = {
        "route": {
            "distance_km": 300,
            "duration_min": 260,
        },
        "stations": [],
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

    return vehicle, route_context, simulation_result, charge_need


def test_generates_three_profiles_and_cards():
    engine = RouteProfiles(
        charging_stop_selector=FakeSelector(),
        charging_planner=FakeChargingPlanner(),
    )

    vehicle, route_context, simulation_result, charge_need = build_common_inputs()

    result = engine.generate_profiles(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
    )

    assert result["status"] == "ok"
    assert set(result["profiles"].keys()) == {"fast", "efficient", "balanced"}
    assert len(result["profile_cards"]) == 3
    assert result["profiles"]["fast"]["label"] == "Hizli"
    assert result["profiles"]["efficient"]["label"] == "Verimli"
    assert result["profiles"]["balanced"]["label"] == "Dengeli"


def test_marks_best_by_time_and_energy_correctly():
    engine = RouteProfiles(
        charging_stop_selector=FakeSelector(),
        charging_planner=FakeChargingPlanner(),
    )

    vehicle, route_context, simulation_result, charge_need = build_common_inputs()

    result = engine.generate_profiles(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
    )

    assert result["best_by_time"] == "fast"
    assert result["best_by_energy"] == "efficient"
    assert result["recommended_profile"] == "balanced"


def test_falls_back_when_balanced_not_feasible():
    engine = RouteProfiles(
        charging_stop_selector=FakeSelector(),
        charging_planner=FakeChargingPlannerBalancedRisky(),
    )

    vehicle, route_context, simulation_result, charge_need = build_common_inputs()

    result = engine.generate_profiles(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
    )

    assert result["status"] == "ok"
    assert result["profiles"]["balanced"]["feasible"] is False
    assert result["recommended_profile"] == "fast"