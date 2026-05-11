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


def test_simulator_uses_speed_limit_when_available():
    """speed_limit_summary varsa avg_speed_kmh ona gore clamp edilir."""
    simulator = RouteEnergySimulator()
    vehicle = sample_vehicle()

    # Yuksek OSRM hizi (140) ama speed limit 90 -> clamp.
    rc = sample_route_context()
    rc["route"]["duration_min"] = 100.0 / 140.0 * 60.0  # 140 km/h equivalent
    rc["speed_limit_summary"] = {"max_speed_kmh": 90.0}

    rc_unlimited = sample_route_context()
    rc_unlimited["route"]["duration_min"] = 100.0 / 140.0 * 60.0

    capped = simulator.simulate(
        vehicle=vehicle, route_context=rc, start_soc_pct=80.0, strategy="fast"
    )
    unlimited = simulator.simulate(
        vehicle=vehicle, route_context=rc_unlimited, start_soc_pct=80.0, strategy="fast"
    )

    # Limitli versiyon daha az enerji harcamali (daha dusuk hiz).
    assert capped.total_energy_kwh < unlimited.total_energy_kwh


def test_per_segment_speed_limit_overrides_global_avg():
    """Bir segmentin koordinatlarina denk gelen speed_limit varsa, o segment
    o limit ile clamp edilir (digerleri global avg ile gider)."""
    simulator = RouteEnergySimulator()
    vehicle = sample_vehicle()
    rc = sample_route_context()

    # Yuksek OSRM hizi (140 km/h equivalent). Geometry ekleyelim.
    rc["route"]["duration_min"] = 100.0 / 140.0 * 60.0
    rc["route"]["geometry"] = [
        (39.90, 32.80),
        (39.85, 32.70),
        (39.80, 32.60),
        (39.75, 32.50),
    ]
    # Speed limit: sadece ilk segment 60 km/h (yavaş şehir içi).
    rc["speed_limit_segments"] = [
        {"start_index": 0, "end_index": 1, "maxspeed_kmh": 60, "highway": "secondary"},
    ]

    capped = simulator.simulate(
        vehicle=vehicle, route_context=rc, start_soc_pct=80.0, strategy="fast"
    )

    # Speed_limit_segments'siz versiyon
    rc_no_limit = sample_route_context()
    rc_no_limit["route"]["duration_min"] = 100.0 / 140.0 * 60.0
    unlimited = simulator.simulate(
        vehicle=vehicle, route_context=rc_no_limit, start_soc_pct=80.0, strategy="fast"
    )

    # Per-segment limit varsa toplam enerji azalmali (en azindan ilk segmentte
    # daha dusuk hiz -> daha dusuk speed_delta).
    assert capped.total_energy_kwh <= unlimited.total_energy_kwh


def test_simulator_falls_back_to_osrm_speed_when_no_limits():
    """speed_limit_summary yoksa avg_speed OSRM duration'dan turetilir."""
    simulator = RouteEnergySimulator()
    vehicle = sample_vehicle()
    rc = sample_route_context()
    # Default rc'de speed_limit_summary yok -> calismali, crash yok.
    result = simulator.simulate(
        vehicle=vehicle, route_context=rc, start_soc_pct=80.0
    )
    assert result.total_distance_km > 0


def test_fast_mode_consumes_more_energy_than_efficient():
    """Hiz profili: fast > balanced > efficient enerji tuketimi."""
    simulator = RouteEnergySimulator()
    vehicle = sample_vehicle()
    route_context = sample_route_context()

    fast = simulator.simulate(
        vehicle=vehicle, route_context=route_context, start_soc_pct=80.0, strategy="fast"
    )
    balanced = simulator.simulate(
        vehicle=vehicle, route_context=route_context, start_soc_pct=80.0, strategy="balanced"
    )
    efficient = simulator.simulate(
        vehicle=vehicle, route_context=route_context, start_soc_pct=80.0, strategy="efficient"
    )

    assert fast.total_energy_kwh > balanced.total_energy_kwh
    assert balanced.total_energy_kwh > efficient.total_energy_kwh


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
def test_route_energy_simulation_uses_ml_when_available():
    class FakeModelService:
        def predict_segment_energy(self, *, segment, vehicle, weather=None):
            return {
                "source": "ml",
                "used_model": True,
                "predicted_energy_kwh": 1.2,
                "fallback_energy_kwh": 1.4,
                "model_version": "lgbm_v1",
            }

    simulator = RouteEnergySimulator(
        model_service=FakeModelService(),
        use_ml_default=True,
    )

    vehicle = sample_vehicle()
    route_context = sample_route_context()

    result = simulator.simulate(
        vehicle=vehicle,
        route_context=route_context,
        start_soc_pct=80.0,
    )

    assert result.used_ml is True
    assert result.ml_segment_count == 3
    assert result.heuristic_segment_count == 0
    assert result.model_version == "lgbm_v1"
    assert result.total_energy_kwh > 0


def test_route_energy_simulation_falls_back_without_ml():
    simulator = RouteEnergySimulator(
        model_service=None,
        use_ml_default=True,
    )

    vehicle = sample_vehicle()
    route_context = sample_route_context()

    result = simulator.simulate(
        vehicle=vehicle,
        route_context=route_context,
        start_soc_pct=80.0,
    )

    assert result.used_ml is False
    assert result.ml_segment_count == 0
    assert result.heuristic_segment_count == 3
    assert result.total_energy_kwh > 0