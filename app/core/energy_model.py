from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# =========================================================
# Sabitler
# =========================================================

GRAVITY = 9.81
IDEAL_SPEED_KMH = 90.0
TEMP_REFERENCE_C = 20.0
MIN_SEGMENT_KM = 0.01


# =========================================================
# Data Models
# =========================================================

@dataclass
class Vehicle:
    id: str
    make: str
    model: str
    variant: str
    year: int
    body_type: str
    drivetrain: str
    battery_chemistry: str
    gross_battery_kwh: float
    usable_battery_kwh: float
    soc_min_pct: float
    soc_max_pct: float
    ideal_consumption_wh_km: float
    regen_efficiency: float
    weight_kg: float
    max_dc_charge_kw: float
    max_ac_charge_kw: float
    wltp_range_km: float
    temp_penalty_factor: float
    charge_curve_hint: str
    default_hvac_load_kw: float

    @property
    def full_name(self) -> str:
        return f"{self.make} {self.model} {self.variant}".strip()

    @property
    def routing_reserve_soc_pct(self) -> float:
        return self.soc_min_pct

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Vehicle":
        return cls(
            id=data["id"],
            make=data["make"],
            model=data["model"],
            variant=data["variant"],
            year=int(data["year"]),
            body_type=data["body_type"],
            drivetrain=data["drivetrain"],
            battery_chemistry=data["battery_chemistry"],
            gross_battery_kwh=float(data["gross_battery_kwh"]),
            usable_battery_kwh=float(data["usable_battery_kwh"]),
            soc_min_pct=float(data["soc_min_pct"]),
            soc_max_pct=float(data["soc_max_pct"]),
            ideal_consumption_wh_km=float(data["ideal_consumption_wh_km"]),
            regen_efficiency=float(data["regen_efficiency"]),
            weight_kg=float(data["weight_kg"]),
            max_dc_charge_kw=float(data["max_dc_charge_kw"]),
            max_ac_charge_kw=float(data["max_ac_charge_kw"]),
            wltp_range_km=float(data["wltp_range_km"]),
            temp_penalty_factor=float(data["temp_penalty_factor"]),
            charge_curve_hint=data["charge_curve_hint"],
            default_hvac_load_kw=float(data["default_hvac_load_kw"]),
        )


@dataclass
class ConsumptionBreakdown:
    base_consumption_kwh: float
    speed_delta_kwh: float
    slope_kwh: float
    regen_kwh: float
    hvac_kwh: float
    temp_penalty_kwh: float
    drivetrain_factor: float
    gross_consumption_kwh: float
    net_consumption_kwh: float
    wh_per_km_raw: float


@dataclass
class SegmentEnergyResult:
    distance_km: float
    speed_kmh: float
    grade_pct: float
    temp_c: float
    start_soc_pct: float
    end_soc_pct: float
    below_reserve: bool
    energy_used_kwh: float
    consumption_wh_km: float
    breakdown: ConsumptionBreakdown


# =========================================================
# JSON Loader
# =========================================================

def load_vehicle_database(json_path: str | Path) -> Dict[str, Any]:
    path = Path(json_path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if "vehicles" not in data or not isinstance(data["vehicles"], list):
        raise ValueError("JSON içinde 'vehicles' listesi bulunamadı.")

    return data


def load_vehicles(json_path: str | Path) -> List[Vehicle]:
    data = load_vehicle_database(json_path)
    return [Vehicle.from_dict(item) for item in data["vehicles"]]


def get_vehicle_by_id(json_path: str | Path, vehicle_id: str) -> Vehicle:
    vehicles = load_vehicles(json_path)
    for vehicle in vehicles:
        if vehicle.id == vehicle_id:
            return vehicle
    raise ValueError(f"Vehicle id bulunamadı: {vehicle_id}")


# =========================================================
# Helpers
# =========================================================

def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def estimate_hvac_load_kw(
    vehicle: Vehicle,
    temp_c: float,
    hvac_override_kw: Optional[float] = None,
) -> float:
    if hvac_override_kw is not None:
        return max(0.0, hvac_override_kw)

    base = vehicle.default_hvac_load_kw
    delta = abs(temp_c - TEMP_REFERENCE_C)

    if temp_c < 10:
        extra = delta * 0.05
    else:
        extra = delta * 0.03

    return round(base + extra, 3)


def get_speed_delta_kwh(base_consumption_kwh: float, speed_kmh: float) -> float:
    speed_kmh = max(5.0, speed_kmh)
    speed_ratio = speed_kmh / IDEAL_SPEED_KMH
    speed_factor = (speed_ratio ** 1.7) - 1.0
    return base_consumption_kwh * speed_factor


def get_slope_and_regen_kwh(
    vehicle: Vehicle,
    segment_km: float,
    grade_pct: float,
) -> tuple[float, float]:
    """
    DÜZELTME:
    - Çıkışta slope_kwh > 0 ve tüketime eklenir.
    - İnişte slope_kwh gross içine negatif girmez.
    - İnişten gelen fayda sadece regen_kwh üzerinden net tüketime yansır.
    """
    grade_fraction = grade_pct / 100.0
    delta_h_meters = segment_km * 1000.0 * grade_fraction
    slope_joules = vehicle.weight_kg * GRAVITY * delta_h_meters
    slope_kwh_raw = slope_joules / 3_600_000.0

    if slope_kwh_raw >= 0:
        slope_kwh = slope_kwh_raw
        regen_kwh = 0.0
    else:
        slope_kwh = 0.0
        regen_kwh = abs(slope_kwh_raw) * vehicle.regen_efficiency

    return slope_kwh, regen_kwh


def get_hvac_kwh(
    hvac_load_kw: float,
    segment_km: float,
    speed_kmh: float,
) -> float:
    speed_kmh = max(5.0, speed_kmh)
    segment_hours = segment_km / speed_kmh
    return hvac_load_kw * segment_hours


def get_temp_penalty_kwh(
    vehicle: Vehicle,
    base_consumption_kwh: float,
    temp_c: float,
) -> float:
    """
    20C altı için ceza uygula.
    20C üstü klima etkisinin HVAC tarafında temsil edildiğini varsay.
    """
    temp_diff = max(0.0, TEMP_REFERENCE_C - temp_c)
    return base_consumption_kwh * vehicle.temp_penalty_factor * temp_diff


def get_drivetrain_factor(vehicle: Vehicle) -> float:
    mapping = {
        "FWD": 1.00,
        "RWD": 1.00,
        "AWD": 1.03,
    }
    return mapping.get(vehicle.drivetrain.upper(), 1.00)


# =========================================================
# Core Energy Model
# =========================================================

def estimate_segment_energy(
    vehicle: Vehicle,
    distance_km: float,
    speed_kmh: float,
    temp_c: float,
    grade_pct: float,
    start_soc_pct: float,
    hvac_override_kw: Optional[float] = None,
) -> SegmentEnergyResult:
    if distance_km < MIN_SEGMENT_KM:
        distance_km = MIN_SEGMENT_KM

    speed_kmh = max(5.0, speed_kmh)
    start_soc_pct = clamp(start_soc_pct, 0.0, 100.0)

    base_consumption_kwh = (vehicle.ideal_consumption_wh_km * distance_km) / 1000.0
    speed_delta_kwh = get_speed_delta_kwh(base_consumption_kwh, speed_kmh)
    slope_kwh, regen_kwh = get_slope_and_regen_kwh(vehicle, distance_km, grade_pct)

    hvac_load_kw = estimate_hvac_load_kw(vehicle, temp_c, hvac_override_kw)
    hvac_kwh = get_hvac_kwh(hvac_load_kw, distance_km, speed_kmh)

    temp_penalty_kwh = get_temp_penalty_kwh(vehicle, base_consumption_kwh, temp_c)
    drivetrain_factor = get_drivetrain_factor(vehicle)

    gross_consumption_kwh = (
        base_consumption_kwh
        + speed_delta_kwh
        + slope_kwh
        + hvac_kwh
        + temp_penalty_kwh
    )

    gross_consumption_kwh = max(0.0, gross_consumption_kwh)
    gross_consumption_kwh *= drivetrain_factor

    net_consumption_kwh = gross_consumption_kwh - regen_kwh
    net_consumption_kwh = max(0.0, net_consumption_kwh)

    wh_per_km_raw = (net_consumption_kwh * 1000.0) / distance_km

    # Aşırı iyimser sonuçlara taban koy
    min_wh_km = vehicle.ideal_consumption_wh_km * 0.70
    if wh_per_km_raw < min_wh_km:
        wh_per_km_raw = min_wh_km
        net_consumption_kwh = (wh_per_km_raw * distance_km) / 1000.0

    start_energy_kwh = vehicle.usable_battery_kwh * (start_soc_pct / 100.0)
    end_energy_kwh = max(0.0, start_energy_kwh - net_consumption_kwh)
    end_soc_pct = (end_energy_kwh / vehicle.usable_battery_kwh) * 100.0

    below_reserve = end_soc_pct < vehicle.routing_reserve_soc_pct

    breakdown = ConsumptionBreakdown(
        base_consumption_kwh=round(base_consumption_kwh, 4),
        speed_delta_kwh=round(speed_delta_kwh, 4),
        slope_kwh=round(slope_kwh, 4),
        regen_kwh=round(regen_kwh, 4),
        hvac_kwh=round(hvac_kwh, 4),
        temp_penalty_kwh=round(temp_penalty_kwh, 4),
        drivetrain_factor=round(drivetrain_factor, 4),
        gross_consumption_kwh=round(gross_consumption_kwh, 4),
        net_consumption_kwh=round(net_consumption_kwh, 4),
        wh_per_km_raw=round(wh_per_km_raw, 4),
    )

    return SegmentEnergyResult(
        distance_km=round(distance_km, 3),
        speed_kmh=round(speed_kmh, 2),
        grade_pct=round(grade_pct, 3),
        temp_c=round(temp_c, 2),
        start_soc_pct=round(start_soc_pct, 2),
        end_soc_pct=round(end_soc_pct, 2),
        below_reserve=below_reserve,
        energy_used_kwh=round(net_consumption_kwh, 4),
        consumption_wh_km=round(wh_per_km_raw, 2),
        breakdown=breakdown,
    )


def estimate_route_energy(
    vehicle: Vehicle,
    segments: List[Dict[str, float]],
    start_soc_pct: float,
    default_temp_c: Optional[float] = None,
) -> Dict[str, Any]:
    current_soc = clamp(start_soc_pct, 0.0, 100.0)
    total_energy_kwh = 0.0
    total_distance_km = 0.0
    segment_results: List[Dict[str, Any]] = []

    for i, seg in enumerate(segments, start=1):
        temp_c = float(seg.get("temp_c", default_temp_c if default_temp_c is not None else 20.0))

        result = estimate_segment_energy(
            vehicle=vehicle,
            distance_km=float(seg["distance_km"]),
            speed_kmh=float(seg["speed_kmh"]),
            temp_c=temp_c,
            grade_pct=float(seg.get("grade_pct", 0.0)),
            start_soc_pct=current_soc,
            hvac_override_kw=seg.get("hvac_override_kw"),
        )

        total_energy_kwh += result.energy_used_kwh
        total_distance_km += result.distance_km
        current_soc = result.end_soc_pct

        segment_results.append(
            {
                "segment_no": i,
                "distance_km": result.distance_km,
                "speed_kmh": result.speed_kmh,
                "grade_pct": result.grade_pct,
                "temp_c": result.temp_c,
                "energy_used_kwh": result.energy_used_kwh,
                "consumption_wh_km": result.consumption_wh_km,
                "start_soc_pct": result.start_soc_pct,
                "end_soc_pct": result.end_soc_pct,
                "below_reserve": result.below_reserve,
                "breakdown": result.breakdown.__dict__,
            }
        )

    avg_consumption = 0.0
    if total_distance_km > 0:
        avg_consumption = (total_energy_kwh * 1000.0) / total_distance_km

    return {
        "vehicle_id": vehicle.id,
        "vehicle_name": vehicle.full_name,
        "total_distance_km": round(total_distance_km, 3),
        "total_energy_kwh": round(total_energy_kwh, 4),
        "average_consumption_wh_km": round(avg_consumption, 2),
        "start_soc_pct": round(start_soc_pct, 2),
        "end_soc_pct": round(current_soc, 2),
        "below_reserve": current_soc < vehicle.routing_reserve_soc_pct,
        "segments": segment_results,
    }


def estimate_max_range_km(
    vehicle: Vehicle,
    speed_kmh: float,
    temp_c: float,
    grade_pct: float = 0.0,
    start_soc_pct: float = 100.0,
    hvac_override_kw: Optional[float] = None,
    respect_reserve: bool = True,
) -> float:
    """
    Tek koşul altında yaklaşık erişilebilir menzil.
    Burada yuvarlanmış gösterim değeri yerine breakdown.wh_per_km_raw kullanılıyor.
    """
    preview = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=10.0,
        speed_kmh=speed_kmh,
        temp_c=temp_c,
        grade_pct=grade_pct,
        start_soc_pct=start_soc_pct,
        hvac_override_kw=hvac_override_kw,
    )

    wh_per_km = preview.breakdown.wh_per_km_raw
    if wh_per_km <= 0:
        return 0.0

    start_soc_pct = clamp(start_soc_pct, 0.0, 100.0)
    usable_energy_kwh = vehicle.usable_battery_kwh * (start_soc_pct / 100.0)

    if respect_reserve:
        reserve_energy_kwh = vehicle.usable_battery_kwh * (vehicle.routing_reserve_soc_pct / 100.0)
        usable_energy_kwh = max(0.0, usable_energy_kwh - reserve_energy_kwh)

    range_km = usable_energy_kwh / (wh_per_km / 1000.0)
    return round(range_km, 2)


# =========================================================
# Example Usage
# =========================================================

if __name__ == "__main__":
    candidate_paths = [
        Path("app/data/vehicles.json"),
        Path("vehicles.json"),
    ]

    json_path = None
    for path in candidate_paths:
        if path.exists():
            json_path = path
            break

    if json_path is None:
        raise FileNotFoundError("vehicles.json bulunamadı.")

    vehicle = get_vehicle_by_id(json_path, "tesla_model_y_rwd")

    result = estimate_segment_energy(
        vehicle=vehicle,
        distance_km=120.0,
        speed_kmh=110.0,
        temp_c=8.0,
        grade_pct=1.5,
        start_soc_pct=85.0,
    )

    print("Vehicle:", vehicle.full_name)
    print("Consumption (Wh/km):", result.consumption_wh_km)
    print("Energy used (kWh):", result.energy_used_kwh)
    print("End SOC (%):", result.end_soc_pct)
    print("Below reserve:", result.below_reserve)
    print("Breakdown:", result.breakdown)

    route = estimate_route_energy(
        vehicle=vehicle,
        start_soc_pct=85.0,
        segments=[
            {"distance_km": 60, "speed_kmh": 110, "grade_pct": 1.5, "temp_c": 10},
            {"distance_km": 80, "speed_kmh": 95, "grade_pct": 2.0, "temp_c": 8},
            {"distance_km": 40, "speed_kmh": 75, "grade_pct": -1.5, "temp_c": 7},
        ],
    )

    print("\nRoute summary:")
    print(route)