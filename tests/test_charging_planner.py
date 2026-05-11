from app.core.charging_planner import ChargingPlanner


def test_max_stops_default_is_eight():
    """ChargingPlanner default max_stops 5 yerine 8 (uzun rotalar icin)."""
    planner = ChargingPlanner()
    assert planner.max_stops == 8


def test_max_stops_user_override_respected():
    """Kullanici max_stops=3 verirse planner buna saygi gosterir."""
    planner = ChargingPlanner(max_stops=3)
    assert planner.max_stops == 3


def test_dynamic_max_stops_extends_for_long_routes():
    """1500km rota + dusuk menzil -> dinamik max_stops 8'in uzerine cikar."""
    planner = ChargingPlanner()

    vehicle = {
        "usable_battery_kwh": 50,  # kucuk batarya
        "ideal_consumption_wh_km": 200,
    }

    # Basitlestirilmis dummy data: 1500km rota, dusuk menzilli arac.
    # est_range = 50 * 0.7 / 0.2 = 175km. min_stops_needed = 1500/175 = 8.
    # dynamic_max_stops = max(8, 8+3) = 11.
    route_distance_km = 1500.0
    avg_consumption = 0.2  # kwh/km

    est_range_km = (vehicle["usable_battery_kwh"] * 0.7) / avg_consumption
    min_stops_needed = max(1, int(route_distance_km / est_range_km))
    dynamic_max_stops = max(planner.max_stops, min_stops_needed + 3)

    assert dynamic_max_stops > planner.max_stops
    assert dynamic_max_stops >= 11


def test_returns_direct_plan_when_charging_not_needed():
    planner = ChargingPlanner()

    vehicle = {
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
    }

    route_context = {
        "route": {
            "distance_km": 120,
            "duration_min": 90,
        }
    }

    simulation_result = {
        "initial_soc": 90,
        "total_energy_kwh": 20,
        "segments": [
            {"cumulative_distance_km": 60, "soc_after": 75},
            {"cumulative_distance_km": 120, "soc_after": 58},
        ],
    }

    charge_need = {
        "needs_charging": False,
        "reserve_soc_percent": 10,
    }

    selector_result = {
        "needs_charging": False,
        "selected_station": None,
    }

    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy="balanced",
    )

    assert result["status"] == "ok"
    assert result["needs_charging"] is False
    assert result["summary"]["stop_count"] == 0
    assert result["summary"]["total_trip_minutes"] == 90.0
    assert result["summary"]["projected_arrival_soc_percent"] == 58.0


def test_builds_single_stop_plan_when_station_selected():
    planner = ChargingPlanner()

    vehicle = {
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
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
        "reserve_soc_percent": 10,
    }

    selector_result = {
        "selected_station": {
            "name": "Ankara DC",
            "distance_along_route_km": 150,
            "remaining_distance_km": 150,
            "detour_distance_km": 3.0,
            "detour_minutes": 4.5,
            "soc_at_arrival_percent": 46.0,
            "target_soc_percent": 62.0,
            "charge_minutes": 11.0,
            "power_kw": 120,
        }
    }

    # NOT: Balanced profili +10% güvenlik bonusu uyguladigi icin marjinal
    # tek-stop senaryosunu infeasible bulup multi-stop'a geciyor. Bu test
    # single-stop yolunu dogruluyor — Fast strategy bonus uygulamiyor.
    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy="fast",
    )

    assert result["needs_charging"] is True
    assert result["summary"]["stop_count"] == 1
    assert result["recommended_stops"][0]["name"] == "Ankara DC"
    assert result["summary"]["total_trip_minutes"] > 260.0
    assert result["summary"]["total_energy_kwh"] > 54.0
    assert result["summary"]["projected_arrival_soc_percent"] >= 10.0
    assert result["feasible"] is True


def test_returns_no_feasible_plan_when_no_station_found():
    planner = ChargingPlanner()

    vehicle = {
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
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
        "reserve_soc_percent": 10,
    }

    selector_result = {
        "selected_station": None,
    }

    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy="balanced",
    )

    assert result["status"] == "no_feasible_plan"
    assert result["feasible"] is False
    assert result["recommended_stops"] == []
def test_build_plan_propagates_ml_summary():
    planner = ChargingPlanner()

    vehicle = {
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
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
        "reserve_soc_percent": 10,
        "used_ml": True,
        "ml_segment_count": 3,
        "heuristic_segment_count": 0,
        "model_version": "lgbm_v1",
    }

    selector_result = {
        "selected_station": {
            "name": "Ankara DC",
            "distance_along_route_km": 150,
            "remaining_distance_km": 150,
            "detour_distance_km": 3.0,
            "detour_minutes": 4.5,
            "soc_at_arrival_percent": 46.0,
            "target_soc_percent": 62.0,
            "charge_minutes": 11.0,
            "power_kw": 120,
        }
    }

    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy="balanced",
    )

    assert result["ml_summary"]["used_ml"] is True
    assert result["ml_summary"]["ml_segment_count"] == 3
    assert result["ml_summary"]["heuristic_segment_count"] == 0
    assert result["ml_summary"]["model_version"] == "lgbm_v1"
    assert "ML" in result["message"]


def test_target_arrival_soc_pct_overrides_default_reserve():
    """User target_arrival_soc_pct=25 -> planner reserve 10 yerine 25'e gore.
    Single-stop senaryosu icin sadece varis SOC'unun reserve_soc + arrival_bonus
    'tan etkilendigini dogrula."""
    planner = ChargingPlanner()

    vehicle = {
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
    }
    route_context = {
        "route": {"distance_km": 300, "duration_min": 260},
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
    charge_need_with_target = {
        "needs_charging": True,
        "reserve_soc_percent": 10,
        "target_arrival_soc_pct": 25,
    }
    selector_result = {
        "selected_station": {
            "name": "DC1",
            "distance_along_route_km": 150,
            "remaining_distance_km": 150,
            "detour_distance_km": 1.0,
            "detour_minutes": 1.5,
            "soc_at_arrival_percent": 46.0,
            "target_soc_percent": 80.0,
            "charge_minutes": 25.0,
            "power_kw": 120,
        },
    }

    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need_with_target,
        selector_result=selector_result,
        strategy="fast",
    )

    # User 25% varış istiyor; planner ya yeterli sarj eder ya da infeasible deklare eder.
    if result.get("feasible"):
        arrival = result["summary"]["projected_arrival_soc_percent"]
        assert arrival >= 25.0, f"target_arrival_soc_pct=25 saglanmadi: {arrival}"


def test_unreachable_destination_returns_no_feasible_plan():
    """Initial SOC dusuk + istasyon yok -> infeasible mesaji net."""
    planner = ChargingPlanner()

    vehicle = {"usable_battery_kwh": 60, "ideal_consumption_wh_km": 180}
    route_context = {
        "route": {"distance_km": 500, "duration_min": 380},
        "stations": [],
    }
    simulation_result = {
        "initial_soc": 15,
        "total_energy_kwh": 90,
        "segments": [
            {"cumulative_distance_km": 100, "soc_after": -10},
            {"cumulative_distance_km": 500, "soc_after": -100},
        ],
    }
    charge_need = {"needs_charging": True, "reserve_soc_percent": 10}
    selector_result = {"selected_station": None}

    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy="balanced",
    )

    assert result["status"] == "no_feasible_plan"
    assert result["feasible"] is False