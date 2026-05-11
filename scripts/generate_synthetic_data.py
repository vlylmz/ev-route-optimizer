from __future__ import annotations

import random
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.core.energy_model import load_vehicles, estimate_segment_energy


def weighted_choice(items: list[tuple[str, float]]) -> str:
    labels = [x[0] for x in items]
    weights = [x[1] for x in items]
    return random.choices(labels, weights=weights, k=1)[0]


def sample_speed_kmh(route_type: str) -> float:
    if route_type == "city":
        return round(random.uniform(25, 65), 1)
    if route_type == "mixed":
        return round(random.uniform(50, 100), 1)
    if route_type == "highway":
        return round(random.uniform(90, 140), 1)
    return round(random.uniform(40, 110), 1)


def sample_distance_km(route_type: str) -> float:
    if route_type == "city":
        return round(random.uniform(2, 20), 2)
    if route_type == "mixed":
        return round(random.uniform(10, 60), 2)
    if route_type == "highway":
        return round(random.uniform(30, 180), 2)
    return round(random.uniform(5, 80), 2)


def sample_grade_pct(terrain_type: str) -> float:
    if terrain_type == "flat":
        return round(random.uniform(-1.0, 1.0), 2)
    if terrain_type == "rolling":
        return round(random.uniform(-4.0, 4.0), 2)
    if terrain_type == "hilly_up":
        return round(random.uniform(1.5, 7.0), 2)
    if terrain_type == "hilly_down":
        return round(random.uniform(-7.0, -1.5), 2)
    return round(random.uniform(-5.0, 5.0), 2)


def sample_temp_c(climate_type: str) -> float:
    if climate_type == "cold":
        return round(random.uniform(-10, 8), 1)
    if climate_type == "mild":
        return round(random.uniform(10, 24), 1)
    if climate_type == "hot":
        return round(random.uniform(25, 40), 1)
    return round(random.uniform(0, 30), 1)


def sample_hvac_kw(default_hvac_load_kw: float, temp_c: float) -> float:
    """
    Override bazen default değer etrafında oynasın.
    Soğuk/sıcak havada biraz artsın.
    """
    extra = 0.0
    if temp_c < 5:
        extra = random.uniform(0.3, 1.5)
    elif temp_c > 28:
        extra = random.uniform(0.2, 1.0)
    else:
        extra = random.uniform(-0.2, 0.5)

    hvac_kw = max(0.2, default_hvac_load_kw + extra)
    return round(hvac_kw, 2)


def apply_measurement_noise(value: float, noise_ratio: float = 0.03) -> float:
    """
    Modelin birebir formülü ezberlememesi için küçük gürültü ekle.
    """
    noisy = value * (1 + random.uniform(-noise_ratio, noise_ratio))
    return noisy


def generate_dataset(
    vehicles_json_path: str | Path,
    n_samples: int = 5000,
    seed: int = 42,
) -> pd.DataFrame:
    random.seed(seed)

    vehicles = load_vehicles(vehicles_json_path)
    rows = []

    for _ in range(n_samples):
        vehicle = random.choice(vehicles)

        route_type = weighted_choice([
            ("city", 0.25),
            ("mixed", 0.35),
            ("highway", 0.40),
        ])

        terrain_type = weighted_choice([
            ("flat", 0.35),
            ("rolling", 0.35),
            ("hilly_up", 0.15),
            ("hilly_down", 0.15),
        ])

        climate_type = weighted_choice([
            ("cold", 0.20),
            ("mild", 0.55),
            ("hot", 0.25),
        ])

        distance_km = sample_distance_km(route_type)
        speed_kmh = sample_speed_kmh(route_type)
        grade_pct = sample_grade_pct(terrain_type)
        temp_c = sample_temp_c(climate_type)
        start_soc_pct = round(random.uniform(20, 100), 2)
        hvac_override_kw = sample_hvac_kw(vehicle.default_hvac_load_kw, temp_c)

        result = estimate_segment_energy(
            vehicle=vehicle,
            distance_km=distance_km,
            speed_kmh=speed_kmh,
            temp_c=temp_c,
            grade_pct=grade_pct,
            start_soc_pct=start_soc_pct,
            hvac_override_kw=hvac_override_kw,
        )

        noisy_wh_km = apply_measurement_noise(result.consumption_wh_km, noise_ratio=0.03)

        min_wh_km = vehicle.ideal_consumption_wh_km * 0.70
        noisy_wh_km = max(min_wh_km, noisy_wh_km)
        noisy_energy_kwh = (noisy_wh_km * distance_km) / 1000.0

        rows.append(
            {
                "vehicle_id": vehicle.id,
                "make": vehicle.make,
                "model": vehicle.model,
                "variant": vehicle.variant,
                "year": vehicle.year,
                "body_type": vehicle.body_type,
                "drivetrain": vehicle.drivetrain,
                "battery_chemistry": vehicle.battery_chemistry,
                "usable_battery_kwh": vehicle.usable_battery_kwh,
                "ideal_consumption_wh_km": vehicle.ideal_consumption_wh_km,
                "regen_efficiency": vehicle.regen_efficiency,
                "weight_kg": vehicle.weight_kg,
                "max_dc_charge_kw": vehicle.max_dc_charge_kw,
                "temp_penalty_factor": vehicle.temp_penalty_factor,
                "charge_curve_hint": vehicle.charge_curve_hint,
                "route_type": route_type,
                "terrain_type": terrain_type,
                "climate_type": climate_type,
                "distance_km": distance_km,
                "speed_kmh": speed_kmh,
                "grade_pct": grade_pct,
                "temp_c": temp_c,
                "start_soc_pct": start_soc_pct,
                "hvac_override_kw": hvac_override_kw,
                "base_consumption_kwh": result.breakdown.base_consumption_kwh,
                "speed_delta_kwh": result.breakdown.speed_delta_kwh,
                "slope_kwh": result.breakdown.slope_kwh,
                "regen_kwh": result.breakdown.regen_kwh,
                "hvac_kwh": result.breakdown.hvac_kwh,
                "temp_penalty_kwh": result.breakdown.temp_penalty_kwh,
                "gross_consumption_kwh": result.breakdown.gross_consumption_kwh,
                "net_consumption_kwh": result.breakdown.net_consumption_kwh,
                "estimated_wh_km": result.consumption_wh_km,
                "target_wh_km": round(noisy_wh_km, 3),
                "target_energy_kwh": round(noisy_energy_kwh, 4),
                "end_soc_pct": result.end_soc_pct,
                "below_reserve": int(result.below_reserve),
            }
        )

    return pd.DataFrame(rows)


def main() -> None:
    vehicles_json_path = ROOT_DIR / "app" / "data" / "vehicles.json"
    output_dir = ROOT_DIR / "app" / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_csv = output_dir / "synthetic_drive_data.csv"

    df = generate_dataset(
        vehicles_json_path=vehicles_json_path,
        n_samples=5000,
        seed=42,
    )

    df.to_csv(output_csv, index=False)

    # PowerShell cp1252 ile uyumsuzluk olmasin diye ASCII print.
    print(f"Dataset olusturuldu: {output_csv}")
    print(f"Satir sayisi: {len(df)}")
    print("\nIlk 5 satir:")
    print(df.head())
    print("\nHedef ortalama tuketim (Wh/km):", round(df["target_wh_km"].mean(), 2))
    print("Min/Max hedef tuketim:", round(df["target_wh_km"].min(), 2), "/", round(df["target_wh_km"].max(), 2))


if __name__ == "__main__":
    main()