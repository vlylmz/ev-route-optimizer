"""Planner._try_dijkstra_solver gercek istasyon datasiyla calistir."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from dataclasses import asdict

from app.core.charging_planner import ChargingPlanner
from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.charging_stop_selector import ChargingStopSelector
from app.core.energy_model import get_vehicle_by_id
from app.core.route_energy_simulator import RouteEnergySimulator

vehicle = get_vehicle_by_id("app/data/vehicles.json", "tesla_model_y_rwd")

# /route uzerinden gercek context cek
resp = requests.post(
    "http://localhost:8000/route",
    json={"start": {"lat": 40.6499, "lon": 35.8353}, "end": {"lat": 38.4192, "lon": 27.1287}},
    timeout=180,
)
route_data = resp.json()
print(f"Distance: {route_data['summary']['distance_km']} km, Duration: {route_data['summary']['duration_min']} dk")
print(f"Stations: {len(route_data['stations'])}")

# /route response'undan context kur
route_context = {
    "route": {
        "distance_km": route_data["summary"]["distance_km"],
        "duration_min": route_data["summary"]["duration_min"],
        "geometry": route_data["geometry"],
    },
    "weather": route_data["weather"],
    "elevation": {"slope_segments": route_data["slope_segments"]},
    "stations": route_data["stations"],
}

# Simulate balanced
simulator = RouteEnergySimulator()
sim = simulator.simulate(vehicle=vehicle, route_context=route_context, start_soc_pct=80.0, strategy="balanced")
print(f"\nSimulation: total_energy={sim.total_energy_kwh}kWh, end_soc={sim.end_soc_pct}%")

# Analyze
analyzer = ChargeNeedAnalyzer()
charge_need = analyzer.analyze(
    simulation=sim, usable_battery_kwh=vehicle.usable_battery_kwh, reserve_soc_pct=vehicle.soc_min_pct
)
print(f"Charge need: required={charge_need.charging_required}, critical_segment={charge_need.critical_segment_no}")

# Planner'in _enrich_all_stations'ina bakalim
planner = ChargingPlanner(min_stop_minutes=10.0)
vehicle_dict = {
    "id": vehicle.id,
    "usable_battery_kwh": vehicle.usable_battery_kwh,
    "ideal_consumption_wh_km": vehicle.ideal_consumption_wh_km,
    "max_dc_charge_kw": vehicle.max_dc_charge_kw,
    "soc_min_pct": vehicle.soc_min_pct,
    "soc_max_pct": vehicle.soc_max_pct,
    "charge_curve_hint": vehicle.charge_curve_hint,
    "battery_chemistry": vehicle.battery_chemistry,
    "dc_connectors": list(vehicle.dc_connectors),
    "ac_connectors": list(vehicle.ac_connectors),
}
enriched = planner._enrich_all_stations(route_context=route_context, vehicle=vehicle_dict)
print(f"\nEnriched stations: {len(enriched)}")
for e in enriched[:15]:
    nm = (e['name'] or '').encode('ascii', 'replace').decode()[:50]
    print(f"  {nm:<55s}  along={e['distance_along_route_km']:>6.1f}km  power={e['power_kw']}kW  detour={e['detour_distance_km']:.1f}km")

# Simdi multi-stop solver'i dene
print("\n=== Multi-stop solver test ===")
from app.core.multi_stop_solver import MultiStopDijkstraSolver

avg_speed_kmh = (route_context["route"]["distance_km"] / route_context["route"]["duration_min"]) * 60
avg_cons = sim.total_energy_kwh / route_context["route"]["distance_km"]

def charge_min_fn(p, s, t):
    from app.services.charging_curve_service import ChargingCurveService
    return ChargingCurveService().compute_charge_minutes(
        vehicle=vehicle, station_kw=p, start_soc_pct=s, target_soc_pct=t, usable_battery_kwh=vehicle.usable_battery_kwh
    )

solver = MultiStopDijkstraSolver(max_target_soc_pct=100.0, avg_speed_kmh=avg_speed_kmh)
solution = solver.solve(
    stations=enriched,
    route_distance_km=route_context["route"]["distance_km"],
    usable_battery_kwh=vehicle.usable_battery_kwh,
    avg_consumption_kwh_per_km=avg_cons,
    initial_soc_pct=80.0,
    reserve_soc_pct=vehicle.soc_min_pct,
    arrival_soc_floor_pct=30.0,  # balanced target_arrival=20 + bonus=10
    charge_minutes_fn=charge_min_fn,
)
if solution is None:
    print("Solution: NONE (solver kuramadi)")
else:
    print(f"Solution: {len(solution.chain)} durak, drive={solution.total_drive_minutes}dk, charge={solution.total_charge_minutes}dk")
    for s in solution.chain:
        nm = (s['name'] or '').encode('ascii', 'replace').decode()[:50]
        print(f"  -> {nm:<55s}  along={s['distance_along_route_km']:>6.1f}km  power={s['power_kw']}kW  target={s.get('target_soc_percent')}%")

# Daha rahat goruvler ile dene
print("\n=== Daha gevsek (arrival=0, en gevsek) ===")
solution2 = solver.solve(
    stations=enriched,
    route_distance_km=route_context["route"]["distance_km"],
    usable_battery_kwh=vehicle.usable_battery_kwh,
    avg_consumption_kwh_per_km=avg_cons,
    initial_soc_pct=80.0,
    reserve_soc_pct=vehicle.soc_min_pct,
    arrival_soc_floor_pct=0.0,
    charge_minutes_fn=charge_min_fn,
)
if solution2 is None:
    print("Solution: NONE")
else:
    print(f"Solution: {len(solution2.chain)} durak")
    for s in solution2.chain:
        nm = (s['name'] or '').encode('ascii', 'replace').decode()[:50]
        print(f"  -> {nm:<55s}  along={s['distance_along_route_km']:>6.1f}km")

# Reach hesabini yazalim
# Controller'la ayni akisi calistir
print("\n=== Controller'la ayni akis (planner.build_plan) ===")
selector = ChargingStopSelector()
selector_result = selector.select_stop(
    vehicle=vehicle_dict,
    route_context=route_context,
    simulation_result=asdict(sim),
    charge_need=asdict(charge_need),
    strategy="fast",
)
sel_name = (selector_result.get('selected_station', {}).get('name', 'none') if selector_result.get('selected_station') else 'none').encode('ascii', 'replace').decode()
print(f"Selector picked: {sel_name}")

planner.energy_buffer_factor = 1.05
plan_result = planner.build_plan(
    vehicle=vehicle_dict,
    route_context=route_context,
    simulation_result=asdict(sim),
    charge_need={**asdict(charge_need), "target_arrival_soc_pct": 10},
    selector_result=selector_result,
    strategy="fast",
)
print(f"Plan status: {plan_result['status']}")
print(f"Plan stops: {plan_result['summary'].get('stop_count')}")
print(f"Plan feasible: {plan_result['feasible']}")
print(f"Plan solver: {plan_result.get('solver', 'single-or-greedy')}")
for s in plan_result.get('recommended_stops', [])[:10]:
    nm = (s.get('name') or '').encode('ascii', 'replace').decode()[:45]
    print(f"  -> {nm:<48s}: along={s.get('distance_along_route_km')}km, {s.get('power_kw')}kW, target={s.get('target_soc_percent')}%")

print(f"\navg_cons={avg_cons}, usable_battery_kwh={vehicle.usable_battery_kwh}")
print(f"reach @ 80% (reserve=10): {(80-10)/100 * vehicle.usable_battery_kwh / avg_cons:.1f} km")
print(f"reach @ 95% (reserve=10): {(95-10)/100 * vehicle.usable_battery_kwh / avg_cons:.1f} km")
print(f"reach @ 100% (reserve=10): {(100-10)/100 * vehicle.usable_battery_kwh / avg_cons:.1f} km")
print(f"Toplam mesafe: {route_context['route']['distance_km']} km")
print(f"En uzun gap: 1.4km -> 275.2km = 273.8 km")
