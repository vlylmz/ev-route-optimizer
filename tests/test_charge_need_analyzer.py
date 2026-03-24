from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.route_energy_simulator import (
    RouteEnergySimulationResult,
    RouteEnergySegmentResult,
)


def build_simulation_ok() -> RouteEnergySimulationResult:
    return RouteEnergySimulationResult(
        vehicle_id="test_vehicle",
        vehicle_name="Test EV",
        total_distance_km=100.0,
        total_energy_kwh=16.5,
        average_consumption_wh_km=165.0,
        start_soc_pct=80.0,
        end_soc_pct=32.0,
        below_reserve=False,
        segment_count=3,
        segments=[
            RouteEnergySegmentResult(
                segment_no=1,
                distance_km=30.0,
                speed_kmh=80.0,
                grade_pct=1.0,
                temp_c=10.0,
                start_soc_pct=80.0,
                end_soc_pct=62.0,
                energy_used_kwh=5.2,
                consumption_wh_km=173.0,
                below_reserve=False,
                segment_start=(39.9, 32.8),
                segment_end=(39.8, 32.7),
            ),
            RouteEnergySegmentResult(
                segment_no=2,
                distance_km=40.0,
                speed_kmh=80.0,
                grade_pct=-0.5,
                temp_c=10.0,
                start_soc_pct=62.0,
                end_soc_pct=46.0,
                energy_used_kwh=5.5,
                consumption_wh_km=137.5,
                below_reserve=False,
                segment_start=(39.8, 32.7),
                segment_end=(39.7, 32.6),
            ),
            RouteEnergySegmentResult(
                segment_no=3,
                distance_km=30.0,
                speed_kmh=80.0,
                grade_pct=0.8,
                temp_c=10.0,
                start_soc_pct=46.0,
                end_soc_pct=32.0,
                energy_used_kwh=5.8,
                consumption_wh_km=193.3,
                below_reserve=False,
                segment_start=(39.7, 32.6),
                segment_end=(39.6, 32.5),
            ),
        ],
    )


def build_simulation_needs_charge() -> RouteEnergySimulationResult:
    return RouteEnergySimulationResult(
        vehicle_id="test_vehicle",
        vehicle_name="Test EV",
        total_distance_km=100.0,
        total_energy_kwh=22.0,
        average_consumption_wh_km=220.0,
        start_soc_pct=35.0,
        end_soc_pct=4.0,
        below_reserve=True,
        segment_count=3,
        segments=[
            RouteEnergySegmentResult(
                segment_no=1,
                distance_km=30.0,
                speed_kmh=90.0,
                grade_pct=1.5,
                temp_c=5.0,
                start_soc_pct=35.0,
                end_soc_pct=22.0,
                energy_used_kwh=6.0,
                consumption_wh_km=200.0,
                below_reserve=False,
                segment_start=(39.9, 32.8),
                segment_end=(39.8, 32.7),
            ),
            RouteEnergySegmentResult(
                segment_no=2,
                distance_km=40.0,
                speed_kmh=95.0,
                grade_pct=2.0,
                temp_c=4.0,
                start_soc_pct=22.0,
                end_soc_pct=9.0,
                energy_used_kwh=8.0,
                consumption_wh_km=200.0,
                below_reserve=True,
                segment_start=(39.8, 32.7),
                segment_end=(39.7, 32.6),
            ),
            RouteEnergySegmentResult(
                segment_no=3,
                distance_km=30.0,
                speed_kmh=95.0,
                grade_pct=0.5,
                temp_c=4.0,
                start_soc_pct=9.0,
                end_soc_pct=4.0,
                energy_used_kwh=8.0,
                consumption_wh_km=266.7,
                below_reserve=True,
                segment_start=(39.7, 32.6),
                segment_end=(39.6, 32.5),
            ),
        ],
    )


def test_charge_not_required_when_above_reserve():
    analyzer = ChargeNeedAnalyzer()
    result = analyzer.analyze(
        simulation=build_simulation_ok(),
        usable_battery_kwh=57.5,
        reserve_soc_pct=10.0,
    )

    assert result.charging_required is False
    assert result.critical_segment_no is None
    assert result.estimated_additional_soc_needed_pct == 0.0


def test_charge_required_when_below_reserve():
    analyzer = ChargeNeedAnalyzer()
    result = analyzer.analyze(
        simulation=build_simulation_needs_charge(),
        usable_battery_kwh=57.5,
        reserve_soc_pct=10.0,
    )

    assert result.charging_required is True
    assert result.critical_segment_no == 2
    assert result.minimum_soc_pct == 4.0
    assert result.estimated_additional_soc_needed_pct > 0
    assert result.estimated_additional_energy_needed_kwh > 0
def test_charge_need_analysis_propagates_ml_metadata():
    analyzer = ChargeNeedAnalyzer()

    simulation = build_simulation_ok()
    simulation.used_ml = True
    simulation.ml_segment_count = 3
    simulation.heuristic_segment_count = 0
    simulation.model_version = "lgbm_v1"

    result = analyzer.analyze(
        simulation=simulation,
        usable_battery_kwh=57.5,
        reserve_soc_pct=10.0,
    )

    assert result.used_ml is True
    assert result.ml_segment_count == 3
    assert result.heuristic_segment_count == 0
    assert result.model_version == "lgbm_v1"
    assert "ML" in result.recommendation