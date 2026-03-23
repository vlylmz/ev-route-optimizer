from pathlib import Path

import pytest

from app.core.energy_model import (
    get_vehicle_by_id,
    load_vehicles,
    estimate_segment_energy,
    estimate_route_energy,
)


def resolve_vehicle_json_path() -> Path:
    candidates = [
        Path("app/data/vehicles.json"),
        Path("vehicles.json"),
    ]

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError("vehicles.json bulunamadı.")


@pytest.fixture
def vehicle():
    json_path = resolve_vehicle_json_path()
    return get_vehicle_by_id(json_path, "tesla_model_y_rwd")


def test_load_vehicles_success():
    json_path = resolve_vehicle_json_path()
    vehicles = load_vehicles(json_path)

    assert len(vehicles) > 0
    assert any(v.id == "tesla_model_y_rwd" for v in vehicles)


def test_consumption_increases_with_speed(vehicle):
    low_speed = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=50,
        speed_kmh=80,
        temp_c=20,
        grade_pct=0,
        start_soc_pct=80,
    )

    high_speed = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=50,
        speed_kmh=130,
        temp_c=20,
        grade_pct=0,
        start_soc_pct=80,
    )

    assert high_speed.energy_used_kwh > low_speed.energy_used_kwh
    assert high_speed.consumption_wh_km > low_speed.consumption_wh_km


def test_consumption_increases_in_cold_weather(vehicle):
    mild = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=40,
        speed_kmh=100,
        temp_c=20,
        grade_pct=0,
        start_soc_pct=80,
    )

    cold = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=40,
        speed_kmh=100,
        temp_c=-5,
        grade_pct=0,
        start_soc_pct=80,
    )

    assert cold.energy_used_kwh > mild.energy_used_kwh
    assert cold.consumption_wh_km > mild.consumption_wh_km


def test_uphill_costs_more_than_flat(vehicle):
    flat = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=20,
        speed_kmh=90,
        temp_c=15,
        grade_pct=0,
        start_soc_pct=80,
    )

    uphill = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=20,
        speed_kmh=90,
        temp_c=15,
        grade_pct=5,
        start_soc_pct=80,
    )

    assert uphill.energy_used_kwh > flat.energy_used_kwh
    assert uphill.breakdown.slope_kwh > 0
    assert uphill.breakdown.regen_kwh == 0


def test_downhill_uses_less_energy_but_not_negative(vehicle):
    flat = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=20,
        speed_kmh=80,
        temp_c=15,
        grade_pct=0,
        start_soc_pct=80,
    )

    downhill = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=20,
        speed_kmh=80,
        temp_c=15,
        grade_pct=-5,
        start_soc_pct=80,
    )

    min_allowed_wh_km = vehicle.ideal_consumption_wh_km * 0.70

    assert downhill.energy_used_kwh < flat.energy_used_kwh
    assert downhill.breakdown.slope_kwh == 0
    assert downhill.breakdown.regen_kwh > 0
    assert downhill.energy_used_kwh >= 0
    assert downhill.consumption_wh_km >= min_allowed_wh_km


def test_soc_drops_after_segment(vehicle):
    result = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=100,
        speed_kmh=110,
        temp_c=10,
        grade_pct=1.5,
        start_soc_pct=85,
    )

    assert result.end_soc_pct < result.start_soc_pct
    assert result.energy_used_kwh > 0


def test_below_reserve_flag_works(vehicle):
    result = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=300,
        speed_kmh=120,
        temp_c=0,
        grade_pct=2.0,
        start_soc_pct=35,
    )

    assert result.below_reserve is True


def test_route_energy_returns_consistent_summary(vehicle):
    route = estimate_route_energy(
        vehicle=vehicle,
        start_soc_pct=85,
        segments=[
            {"distance_km": 40, "speed_kmh": 100, "grade_pct": 1.0, "temp_c": 12},
            {"distance_km": 60, "speed_kmh": 110, "grade_pct": 2.0, "temp_c": 10},
            {"distance_km": 30, "speed_kmh": 80, "grade_pct": -1.5, "temp_c": 8},
        ],
    )

    assert route["total_distance_km"] == 130
    assert route["total_energy_kwh"] > 0
    assert route["average_consumption_wh_km"] > 0
    assert route["end_soc_pct"] < route["start_soc_pct"]
    assert len(route["segments"]) == 3