from app.core.energy_model import Vehicle
from app.core.route_energy_simulator import RouteEnergySimulator


def sample_vehicle() -> Vehicle:
    return Vehicle(
        id="test_vehicle",
        make="Tesla",
        model="Model Y",
        variant="RWD",
        year=2024,
        body_type="SUV",
        drivetrain="RWD",
        battery_chemistry="LFP",
        gross_battery_kwh=60.0,
        usable_battery_kwh=57.5,
        soc_min_pct=10.0,
        soc_max_pct=100.0,
        ideal_consumption_wh_km=150.0,
        regen_efficiency=0.7,
        weight_kg=1900.0,
        max_dc_charge_kw=170.0,
        max_ac_charge_kw=11.0,
        wltp_range_km=455.0,
        temp_penalty_factor=0.004,
        charge_curve_hint="flat_lfp",
        default_hvac_load_kw=1.2,
    )


def sample_route_context():
    return {
        "route": {
            "distance_km": 100.0,
            "duration_min": 75.0,
        },
        "weather": {
            "avg_temp_c": 10.0,
        },
        "elevation": {
            "slope_segments": [
                {
                    "start": (39.90, 32.80),
                    "end": (39.85, 32.70),
                    "distance_km": 30.0,
                    "grade_pct": 1.5,
                },
                {
                    "start": (39.85, 32.70),
                    "end": (39.80, 32.60),
                    "distance_km": 40.0,
                    "grade_pct": -1.0,
                },
                {
                    "start": (39.80, 32.60),
                    "end": (39.75, 32.50),
                    "distance_km": 30.0,
                    "grade_pct": 0.5,
                },
            ]
        },
    }


def test_route_energy_simulation_returns_valid_output():
    simulator = RouteEnergySimulator()
    vehicle = sample_vehicle()
    route_context = sample_route_context()

    result = simulator.simulate(
        vehicle=vehicle,
        route_context=route_context,
        start_soc_pct=80.0,
    )

    assert result.total_distance_km == 100.0
    assert result.total_energy_kwh > 0
    assert result.average_consumption_wh_km > 0
    assert result.end_soc_pct < result.start_soc_pct
    assert result.segment_count == 3
    assert len(result.segments) == 3


def test_route_energy_simulation_flags_low_soc():
    simulator = RouteEnergySimulator()
    vehicle = sample_vehicle()
    route_context = sample_route_context()

    result = simulator.simulate(
        vehicle=vehicle,
        route_context=route_context,
        start_soc_pct=20.0,
    )

    assert result.end_soc_pct < 20.0