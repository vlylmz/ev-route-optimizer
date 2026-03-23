from dataclasses import dataclass


@dataclass
class SocSimulationResult:
    usable_battery_kwh: float
    start_soc_pct: float
    energy_used_kwh: float
    end_soc_pct: float
    below_reserve: bool


def simulate_soc_drop(
    usable_battery_kwh: float,
    start_soc_pct: float,
    energy_used_kwh: float,
    reserve_soc_pct: float = 10.0,
) -> SocSimulationResult:
    start_energy_kwh = usable_battery_kwh * (start_soc_pct / 100.0)
    end_energy_kwh = max(0.0, start_energy_kwh - energy_used_kwh)
    end_soc_pct = (end_energy_kwh / usable_battery_kwh) * 100.0

    return SocSimulationResult(
        usable_battery_kwh=round(usable_battery_kwh, 3),
        start_soc_pct=round(start_soc_pct, 2),
        energy_used_kwh=round(energy_used_kwh, 4),
        end_soc_pct=round(end_soc_pct, 2),
        below_reserve=end_soc_pct < reserve_soc_pct,
    )