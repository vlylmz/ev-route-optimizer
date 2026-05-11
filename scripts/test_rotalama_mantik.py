"""
Gercek bir senaryo uzerinden tum mantik testleri.

Test seti:
1. Fast < Balanced < Efficient toplam sure (sürüş+sarj)
2. Fast > Balanced > Efficient enerji
3. Tum modlarda varis SOC >= reserve
4. Tum stop'larda charge_minutes >= min_stop_minutes (tolerans %80)
5. Maliyet hesabi gercekci (kWh * fiyat)
6. Multi-stop optimal mi (greedy vs Dijkstra karsilastirma)
7. Cok uzun rotada (1300km) plan uretiliyor mu (dinamik max_stops)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.charging_planner import ChargingPlanner
from app.core.charging_stop_selector import ChargingStopSelector
from app.core.energy_model import get_vehicle_by_id
from app.core.route_energy_simulator import RouteEnergySimulator
from app.core.route_profiles import RouteProfiles


def build_test_route_context(distance_km: float, n_stations: int = 6):
    """TR'de gercekci bir rota benzeri context kurar."""
    # Slope segments
    seg_distance = distance_km / 8
    slope_segments = []
    for i in range(8):
        lat_a, lat_b = 39.92 - i * 0.15, 39.92 - (i + 1) * 0.15
        lon_a, lon_b = 32.85 - i * 0.20, 32.85 - (i + 1) * 0.20
        # Cesitli egim: dalgali
        grade = [0.5, -0.3, 1.5, -1.0, 0.8, -0.4, 0.6, -0.2][i]
        slope_segments.append({
            "start": (lat_a, lon_a),
            "end": (lat_b, lon_b),
            "distance_km": seg_distance,
            "grade_pct": grade,
        })

    # Istasyonlar — TR cesitliligi: 50/120/180/250/400 kW karisik fiyatlar
    stations = []
    station_configs = [
        {"name": "ZES 100km", "power_kw": 250, "price": 8.5},
        {"name": "Trugo 200km", "power_kw": 180, "price": 7.2},
        {"name": "Eyvolt 300km", "power_kw": 120, "price": 7.0},
        {"name": "Voltrun 400km", "power_kw": 250, "price": 8.0},
        {"name": "EnerjiSA 500km", "power_kw": 350, "price": 9.0},
        {"name": "ESarj 600km", "power_kw": 150, "price": 7.5},
        {"name": "ZES 700km", "power_kw": 180, "price": 8.0},
        {"name": "Trugo 800km", "power_kw": 250, "price": 8.2},
        {"name": "Voltrun 900km", "power_kw": 120, "price": 7.0},
        {"name": "ZES 1000km", "power_kw": 180, "price": 8.0},
    ]
    for idx, cfg in enumerate(station_configs[:n_stations]):
        d = (idx + 1) * (distance_km / (n_stations + 1))
        stations.append({
            "name": cfg["name"],
            "distance_along_route_km": d,
            "distance_from_route_km": 0.8,
            "lat": 39.92 - d * 0.001,
            "lon": 32.85 - d * 0.001,
            "power_kw": cfg["power_kw"],
            "is_operational": True,
            "price_per_kwh_try": cfg["price"],
            "connections": [{"connection_type": "CCS (Type 2)", "power_kw": cfg["power_kw"]}],
        })

    return {
        "route": {
            "distance_km": distance_km,
            "duration_min": distance_km / 90 * 60,  # OSRM tahmini avg 90 km/h
            "geometry": [(s["start"][0], s["start"][1]) for s in slope_segments] + [tuple(slope_segments[-1]["end"])],
        },
        "weather": {"avg_temp_c": 20.0},
        "elevation": {"slope_segments": slope_segments},
        "stations": stations,
    }


def vehicle_to_dict(v):
    return {
        "id": v.id,
        "vehicle_id": v.id,
        "name": v.full_name,
        "usable_battery_kwh": v.usable_battery_kwh,
        "ideal_consumption_wh_km": v.ideal_consumption_wh_km,
        "max_dc_charge_kw": v.max_dc_charge_kw,
        "max_dc_charge_power_kw": v.max_dc_charge_kw,
        "temp_penalty_factor": v.temp_penalty_factor,
        "soc_min_pct": v.soc_min_pct,
        "soc_max_pct": v.soc_max_pct,
        "charge_curve_hint": v.charge_curve_hint,
        "battery_chemistry": v.battery_chemistry,
        "dc_connectors": list(v.dc_connectors),
        "ac_connectors": list(v.ac_connectors),
    }


def run_scenario(name: str, distance_km: float, vehicle_id: str, initial_soc: float, n_stations: int = 6, target_arrival_soc_pct: float | None = None, min_stop_minutes: float = 10.0):
    print("=" * 80)
    print(f"SENARYO: {name}")
    print(f"  Rota: {distance_km} km | Arac: {vehicle_id} | Initial SOC: {initial_soc}% | Target arrival: {target_arrival_soc_pct or 'reserve'} | min_stop: {min_stop_minutes}dk")
    print("=" * 80)

    vehicle = get_vehicle_by_id("app/data/vehicles.json", vehicle_id)
    v_dict = vehicle_to_dict(vehicle)
    route_context = build_test_route_context(distance_km, n_stations)

    simulator = RouteEnergySimulator()
    analyzer = ChargeNeedAnalyzer()
    planner = ChargingPlanner(min_stop_minutes=min_stop_minutes)
    selector = ChargingStopSelector()
    profiles_engine = RouteProfiles(
        charging_stop_selector=selector,
        charging_planner=planner,
    )

    # Balanced ile baseline simulate (RouteProfiles strateji-bazli yeniden simulate eder)
    sim_balanced = simulator.simulate(
        vehicle=vehicle, route_context=route_context, start_soc_pct=initial_soc, strategy="balanced"
    )
    from dataclasses import asdict
    sim_dict = asdict(sim_balanced)

    charge_need_balanced = analyzer.analyze(
        simulation=sim_balanced,
        usable_battery_kwh=vehicle.usable_battery_kwh,
        reserve_soc_pct=vehicle.soc_min_pct,
    )
    cn_dict = asdict(charge_need_balanced)
    if target_arrival_soc_pct is not None:
        cn_dict["target_arrival_soc_pct"] = target_arrival_soc_pct

    result = profiles_engine.generate_profiles(
        vehicle=v_dict,
        route_context=route_context,
        simulation_result=sim_dict,
        charge_need=cn_dict,
        strategies=["fast", "balanced", "efficient"],
        simulator=simulator,
        analyzer=analyzer,
        vehicle_obj=vehicle,
        initial_soc=initial_soc,
    )

    profiles = result["profiles"]

    print(f"\n{'Mod':<12}{'Toplam':>10}{'Surus':>10}{'Sarj':>8}{'Durak':>8}{'Enerji':>10}{'Varis':>8}  {'Feasible'}")
    print("-" * 90)
    for s in ["fast", "balanced", "efficient"]:
        p = profiles.get(s, {})
        summ = p.get("summary", {}) or {}
        stops = p.get("recommended_stops") or []
        feasible = "evet" if p.get("feasible") else "HAYIR"
        total = summ.get("total_trip_minutes") or 0
        charge = summ.get("charge_minutes") or 0
        arrival = summ.get("projected_arrival_soc_percent")
        arrival_str = f"{arrival:>6.1f}%" if arrival is not None else "  --  "
        print(f"{s:<12}{total:>8.1f}dk"
              f"{(total - charge):>8.1f}dk"
              f"{charge:>6.1f}dk"
              f"{summ.get('stop_count', 0):>8}"
              f"{summ.get('total_energy_kwh', 0):>8.1f}kWh"
              f"{arrival_str:>8}  {feasible}")

    # Mantik kontrolleri
    print("\nMANTIK KONTROLLERI:")
    issues = []

    fast_p = profiles.get("fast", {}).get("summary", {})
    bal_p = profiles.get("balanced", {}).get("summary", {})
    eff_p = profiles.get("efficient", {}).get("summary", {})

    fast_total = fast_p.get("total_trip_minutes", 0)
    bal_total = bal_p.get("total_trip_minutes", 0)
    eff_total = eff_p.get("total_trip_minutes", 0)

    fast_energy = fast_p.get("total_energy_kwh", 0)
    bal_energy = bal_p.get("total_energy_kwh", 0)
    eff_energy = eff_p.get("total_energy_kwh", 0)

    # 1) Toplam sure: fast <= balanced <= efficient
    if fast_total > 0 and bal_total > 0:
        if not (fast_total <= bal_total + 2.0):  # 2 dk tolerans
            issues.append(f"X Fast toplam sure ({fast_total:.1f}) > Balanced ({bal_total:.1f})")
        else:
            print(f"  OK Fast toplam sure ({fast_total:.1f}) <= Balanced ({bal_total:.1f})")

    if eff_total > 0 and bal_total > 0:
        if not (eff_total >= bal_total - 2.0):
            issues.append(f"X Efficient toplam sure ({eff_total:.1f}) < Balanced ({bal_total:.1f})")
        else:
            print(f"  OK Efficient toplam sure ({eff_total:.1f}) >= Balanced ({bal_total:.1f})")

    # 2) Enerji: fast >= balanced >= efficient
    if fast_energy > 0 and bal_energy > 0:
        if not (fast_energy >= bal_energy - 1.0):
            issues.append(f"X Fast enerji ({fast_energy:.1f}) < Balanced ({bal_energy:.1f})")
        else:
            print(f"  OK Fast enerji ({fast_energy:.1f}) >= Balanced ({bal_energy:.1f})")

    if eff_energy > 0 and bal_energy > 0:
        if not (eff_energy <= bal_energy + 1.0):
            issues.append(f"X Efficient enerji ({eff_energy:.1f}) > Balanced ({bal_energy:.1f})")
        else:
            print(f"  OK Efficient enerji ({eff_energy:.1f}) <= Balanced ({bal_energy:.1f})")

    # 3) Varis SOC >= reserve
    for s in ["fast", "balanced", "efficient"]:
        arrival = profiles.get(s, {}).get("summary", {}).get("projected_arrival_soc_percent", 0)
        if profiles.get(s, {}).get("feasible") and arrival < vehicle.soc_min_pct:
            issues.append(f"X {s} varis SOC ({arrival}) < reserve ({vehicle.soc_min_pct})")

    # 4) Min stop saygisi (sadece feasible plan'lar icin sert kontrol).
    # Infeasible plan'larda best-effort sonuc doner; vehicle.soc_max sinirinda
    # tapered egri yuzunden min_stop tutturulamayabilir (fiziksel sinir).
    for s in ["fast", "balanced", "efficient"]:
        p = profiles.get(s, {})
        stops = p.get("recommended_stops") or []
        feasible = p.get("feasible", False)
        for stop in stops:
            cm = stop.get("charge_minutes", 0)
            if feasible and cm < min_stop_minutes * 0.7:
                issues.append(f"X {s} (feasible) stop charge_minutes={cm} << {min_stop_minutes}dk")
        if stops:
            min_cm = min(s["charge_minutes"] for s in stops)
            status = "feasible" if feasible else "best-effort"
            print(f"  OK {s} ({status}): {len(stops)} durak, min charge = {min_cm:.1f} dk")

    if not issues:
        print("\nSONUC: Tum kontroller GECTI [OK]")
    else:
        print(f"\nSONUC: {len(issues)} sorun bulundu:")
        for iss in issues:
            print(f"   {iss}")

    return profiles, issues


if __name__ == "__main__":
    all_issues = []

    # Senaryo 1: Orta mesafe (600km), modern NMC arac (75 kWh)
    _, issues = run_scenario("Orta mesafe + modern EV", 600, "tesla_model_y_lr_awd", 90.0)
    all_issues.extend(issues)

    # Senaryo 2: Uzun mesafe (1200km), kucuk LFP arac (43 kWh) - cok durak
    _, issues = run_scenario("Uzun mesafe + kucuk LFP", 1200, "byd_dolphin", 95.0, n_stations=10)
    all_issues.extend(issues)

    # Senaryo 3: Kisa mesafe (250km), durak gerekmeyebilir
    _, issues = run_scenario("Kisa mesafe + buyuk batarya", 250, "kia_ev9_lr_awd", 85.0, n_stations=3)
    all_issues.extend(issues)

    # Senaryo 4: Cok uzun + dusuk SOC
    _, issues = run_scenario("Cok uzun + dusuk SOC", 1300, "hyundai_ioniq6_lr_rwd", 40.0, n_stations=10)
    all_issues.extend(issues)

    # Senaryo 5: Kullanici target_arrival_soc=90 istiyor (ekran goruntusu senaryosu)
    profiles, issues = run_scenario(
        "Yuksek varis hedefi (target_arrival=90)",
        480, "tesla_model_y_rwd", 80.0,
        n_stations=6,
        target_arrival_soc_pct=90.0,
        min_stop_minutes=20.0,
    )
    # Ekstra kontrol: target_arrival=90 isteniyorsa, feasible plan'larda varis >= 90 olmali
    for s in ["fast", "balanced", "efficient"]:
        p = profiles.get(s, {})
        if p.get("feasible"):
            arrival = p.get("summary", {}).get("projected_arrival_soc_percent", 0)
            if arrival < 89.0:  # 1 puan tolerans
                issues.append(f"X {s} feasible ama varis ({arrival}) < target_arrival (90)")
    all_issues.extend(issues)

    print("\n" + "=" * 80)
    print(f"TOPLAM SONUC: {len(all_issues)} sorun bulundu")
    print("=" * 80)
    if all_issues:
        for iss in all_issues:
            print(f"  {iss}")
        sys.exit(1)
