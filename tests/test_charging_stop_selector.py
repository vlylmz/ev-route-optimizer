import json
from pathlib import Path

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


def test_zero_power_station_excluded_from_candidates():
    """power_kw=0 olan park yeri / bilinmeyen guc istasyonu aday olamaz."""
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = build_common_data()

    route_context["stations"] = [
        {
            "name": "Royal Park Yeri",
            "distance_along_route_km": 150,
            "distance_from_route_km": 0.5,
            "power_kw": 0,  # OCM'den gelen park yeri kayitlari
            "is_operational": True,
        },
    ]

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="fast",
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


def _three_candidate_route_context():
    """Skorlama testleri icin 3 farkli profile sahip aday istasyon kurar.
    distance_along_route_km hepsinde ayni; soc_margin esit, safety doleysiz."""
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
                {"lat": 39.6000, "lon": 32.6000},
            ],
        },
        "stations": [
            # A: kisa detour, dusuk guc -> uzun charge_minutes ama dusuk detour
            {
                "name": "A_Yavas_Yakinda",
                "distance_along_route_km": 150,
                "distance_from_route_km": 0.2,
                "power_kw": 50,
                "is_operational": True,
                "price_per_kwh_try": 7.0,
            },
            # B: uzun detour, yuksek guc -> kisa charge ama uzun detour
            {
                "name": "B_Hizli_Uzakta",
                "distance_along_route_km": 150,
                "distance_from_route_km": 5.0,
                "power_kw": 250,
                "is_operational": True,
                "price_per_kwh_try": 9.0,
            },
            # C: orta detour, orta guc, ucuz fiyat
            {
                "name": "C_Orta_Ucuz",
                "distance_along_route_km": 150,
                "distance_from_route_km": 1.5,
                "power_kw": 120,
                "is_operational": True,
                "price_per_kwh_try": 5.0,
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


def test_normalized_scoring_prefers_lower_time_in_fast_mode():
    """fast modu toplam sureyi minimize eder; en kisa stop_minutes secilmeli."""
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = _three_candidate_route_context()

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="fast",
    )

    selected = result["selected_station"]
    candidates = result["candidates"]

    # Adaylar arasi en kisa extra_time_min'e sahip olan secilmeli.
    min_time_candidate = min(candidates, key=lambda c: c["extra_time_min"])
    assert selected["name"] == min_time_candidate["name"]


def test_normalized_scoring_prefers_lower_energy_in_efficient_mode():
    """efficient modu sapma + sarj kaybi enerjisini minimize eder."""
    selector = ChargingStopSelector()
    vehicle, route_context, simulation_result, charge_need = _three_candidate_route_context()

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="efficient",
    )

    selected = result["selected_station"]
    candidates = result["candidates"]

    min_energy_candidate = min(candidates, key=lambda c: c["extra_energy_kwh"])
    assert selected["name"] == min_energy_candidate["name"]


def test_strategy_weights_loaded_from_config(tmp_path):
    """Custom config dosyasi gecirilirse skorlama davranisi degisir."""
    custom_config = {
        "weights": {
            # 'fast' modunda tum agirligi cost'a verirsek en ucuz aday secilmeli.
            "fast":      {"time": 0.0, "energy": 0.0, "cost": 1.0, "safety": 0.0},
            "efficient": {"time": 0.15, "energy": 0.50, "cost": 0.20, "safety": 0.15},
            "balanced":  {"time": 0.35, "energy": 0.30, "cost": 0.15, "safety": 0.20},
        },
        "default_price_per_kwh_try": 7.0,
        "min_safe_soc_margin_pct": 3.0,
    }
    config_path = tmp_path / "custom_weights.json"
    config_path.write_text(json.dumps(custom_config), encoding="utf-8")

    selector = ChargingStopSelector(strategy_config_path=config_path)
    vehicle, route_context, simulation_result, charge_need = _three_candidate_route_context()

    result = selector.select_stop(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        strategy="fast",
    )

    # Custom config: cost-only ile en ucuz aday C_Orta_Ucuz olmali.
    assert result["selected_station"]["name"] == "C_Orta_Ucuz"


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