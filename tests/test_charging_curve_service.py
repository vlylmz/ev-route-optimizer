from app.services.charging_curve_service import ChargingCurveService


def _vehicle_nmc():
    class V:
        max_dc_charge_kw = 200.0
        charge_curve_hint = "tapered_nmc"
        battery_chemistry = "NMC"

    return V()


def _vehicle_lfp():
    class V:
        max_dc_charge_kw = 150.0
        charge_curve_hint = "flat_lfp"
        battery_chemistry = "LFP"

    return V()


def test_compute_charge_minutes_step_2_within_1pct_of_step_05():
    """step_pct=2.0 ile step_pct=0.5 arasi fark < %1."""
    service = ChargingCurveService()
    vehicle = _vehicle_nmc()

    fine = service.compute_charge_minutes(
        vehicle=vehicle,
        station_kw=150.0,
        start_soc_pct=20.0,
        target_soc_pct=80.0,
        usable_battery_kwh=75.0,
        step_pct=0.5,
    )
    coarse = service.compute_charge_minutes(
        vehicle=vehicle,
        station_kw=150.0,
        start_soc_pct=20.0,
        target_soc_pct=80.0,
        usable_battery_kwh=75.0,
        step_pct=2.0,
    )

    diff_ratio = abs(fine - coarse) / fine
    assert diff_ratio < 0.01, f"fine={fine:.2f} coarse={coarse:.2f} diff={diff_ratio*100:.2f}%"


def test_lfp_curve_flatter_than_nmc_above_50pct():
    """50%-90% araligi: LFP toplam dakika < NMC (LFP daha duz egri)."""
    service = ChargingCurveService()

    nmc_minutes = service.compute_charge_minutes(
        vehicle=_vehicle_nmc(),
        station_kw=200.0,
        start_soc_pct=50.0,
        target_soc_pct=90.0,
        usable_battery_kwh=80.0,
    )
    lfp_minutes = service.compute_charge_minutes(
        vehicle=_vehicle_lfp(),
        station_kw=200.0,
        start_soc_pct=50.0,
        target_soc_pct=90.0,
        usable_battery_kwh=80.0,
    )

    assert lfp_minutes < nmc_minutes
