from app.core.charging_stop_selector import ChargingStopSelector


def build_common_data():
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
                "name": "Yakın Hızlı İstasyon",
                "distance_along_route_km": 150,
                "distance_from_route_km": 1.5,
                "power_kw": 120,
                "is_operational": True,
            },
            {
                "name": "Çok Yakın Ama Yavaş",
                "distance_along_route_km": 145,
                "distance_from_route_km": 0.3,
                "power_kw": 50,
                "is_operational": True,
            },
            {
                "name": "Geç Kalan İstasyon",
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

    return vehicle, route_context, simulation_result, charge_need


def test_returns_none_when_no_charge_needed():
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()
    charge_need["needs_charging"] = False

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
    )

    assert result["needs_charging"] is False
    assert result["selected_station"] is None
    assert result["candidates"] == []


def test_selects_reachable_station_before_critical_point():
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="balanced",
    )

    assert result["selected_station"] is not None
    assert result["selected_station"]["distance_along_route_km"] <= 210
    assert result["selected_station"]["soc_at_arrival_percent"] > 10
    assert result["selected_station"]["name"] in {
        "Yakın Hızlı İstasyon",
        "Çok Yakın Ama Yavaş",
    }


def test_fast_strategy_prefers_higher_power_station():
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="fast",
    )

    assert result["selected_station"] is not None
    assert result["selected_station"]["name"] == "Yakın Hızlı İstasyon"


def test_operational_false_station_is_filtered_out():
    """Kapali istasyon ne kadar uygun gozukse de aday listede olmamali."""
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()

    # Diger butun istasyonlari kaldir; sadece operational=False kalsin.
    route_context["stations"] = [
        {
            "name": "Kapali Istasyon",
            "distance_along_route_km": 150,
            "distance_from_route_km": 0.5,
            "power_kw": 180,
            "is_operational": False,
        },
    ]

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="balanced",
    )

    assert result["selected_station"] is None
    assert result["candidates"] == []


def test_socket_type_mismatch_eliminates_candidate():
    """Vehicle CHAdeMO bekliyorsa CCS-only istasyon aday olamaz."""
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()
    vehicle["dc_connectors"] = ["CHAdeMO"]
    vehicle["ac_connectors"] = ["Type 2"]

    route_context["stations"] = [
        {
            "name": "CCS Only Hizli",
            "distance_along_route_km": 150,
            "distance_from_route_km": 0.5,
            "power_kw": 180,
            "is_operational": True,
            "connections": [
                {"connection_type": "CCS (Type 2)", "power_kw": 180},
            ],
        },
    ]

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="balanced",
    )

    assert result["selected_station"] is None
    assert result["candidates"] == []


def test_socket_type_match_passes_filter():
    """Vehicle CCS2 ve istasyonda CCS varsa aday gecmeli."""
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()
    vehicle["dc_connectors"] = ["CCS2"]
    vehicle["ac_connectors"] = ["Type 2"]

    route_context["stations"] = [
        {
            "name": "CCS Hizli",
            "distance_along_route_km": 150,
            "distance_from_route_km": 0.5,
            "power_kw": 180,
            "is_operational": True,
            "connections": [
                {"connection_type": "CCS (Type 2)", "power_kw": 180},
            ],
        },
    ]

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="balanced",
    )

    assert result["selected_station"] is not None
    assert result["selected_station"]["name"] == "CCS Hizli"


def test_operational_false_excluded_when_other_candidates_exist():
    """Birden fazla aday varsa operational=False olan candidates listesinde olmamali."""
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()

    route_context["stations"].append(
        {
            "name": "Kapali Hizli",
            "distance_along_route_km": 160,
            "distance_from_route_km": 0.2,
            "power_kw": 350,
            "is_operational": False,
        }
    )

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="balanced",
    )

    candidate_names = {c["name"] for c in result["candidates"]}
    assert "Kapali Hizli" not in candidate_names
    assert result["selected_station"] is not None
    assert result["selected_station"]["name"] != "Kapali Hizli"