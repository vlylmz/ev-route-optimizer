"""Optimize endpoint'in tamamini Python'da direk cagir, hangi adimda fail var bul."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.controllers.optimize_controller import _vehicle_to_dict, _dataclass_to_dict
from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.charging_planner import ChargingPlanner
from app.core.charging_stop_selector import ChargingStopSelector
from app.core.energy_model import get_vehicle_by_id
from app.core.route_energy_simulator import RouteEnergySimulator
from app.core.route_profiles import RouteProfiles
import requests

vehicle = get_vehicle_by_id("app/data/vehicles.json", "tesla_model_y_rwd")
v_dict = _vehicle_to_dict(vehicle)
print("vehicle_dict keys:", sorted(v_dict.keys()))
print(f"  soc_max_pct: {v_dict.get('soc_max_pct')}")
print(f"  charge_curve_hint: {v_dict.get('charge_curve_hint')}")

# Route context backend'den cek
resp = requests.post(
    "http://localhost:8000/route",
    json={"start": {"lat": 40.6499, "lon": 35.8353}, "end": {"lat": 38.4192, "lon": 27.1287}},
    timeout=180,
)
route_data = resp.json()
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

simulator = RouteEnergySimulator()
sim = simulator.simulate(vehicle=vehicle, route_context=route_context, start_soc_pct=80.0, strategy="balanced")

analyzer = ChargeNeedAnalyzer()
cn = analyzer.analyze(simulation=sim, usable_battery_kwh=vehicle.usable_battery_kwh, reserve_soc_pct=vehicle.soc_min_pct)
sim_dict = _dataclass_to_dict(sim)
cn_dict = _dataclass_to_dict(cn)
cn_dict["target_arrival_soc_pct"] = 10.0

planner = ChargingPlanner(min_stop_minutes=10.0)
selector = ChargingStopSelector()
profiles_engine = RouteProfiles(charging_stop_selector=selector, charging_planner=planner)

# Controller'la AYNI cagri (strateji-bazli yeniden simulate ile):
result = profiles_engine.generate_profiles(
    vehicle=v_dict,
    route_context=route_context,
    simulation_result=sim_dict,
    charge_need=cn_dict,
    strategies=["fast", "balanced", "efficient"],
    simulator=simulator,
    analyzer=analyzer,
    vehicle_obj=vehicle,
    initial_soc=80.0,
)
print("\n>>> Strateji bazli yeniden simulate kullanildi <<<")

# Strategy=fast yeniden simulate'in ciktisini cek ve build_plan'a tek basina ver
print("\n=== Strategy=fast yeniden simulate sim_dict ===")
sim_fast = simulator.simulate(vehicle=vehicle, route_context=route_context, start_soc_pct=80.0, strategy="fast")
sim_fast_dict = _dataclass_to_dict(sim_fast)
print(f"  total_drive_minutes: {sim_fast_dict.get('total_drive_minutes')}")
print(f"  total_energy_kwh: {sim_fast_dict.get('total_energy_kwh')}")
print(f"  start_soc_pct: {sim_fast_dict.get('start_soc_pct')}")
print(f"  end_soc_pct: {sim_fast_dict.get('end_soc_pct')}")
print(f"  segment_count: {sim_fast_dict.get('segment_count')}")

cn_fast = analyzer.analyze(simulation=sim_fast, usable_battery_kwh=vehicle.usable_battery_kwh, reserve_soc_pct=vehicle.soc_min_pct)
cn_fast_dict = _dataclass_to_dict(cn_fast)
cn_fast_dict["target_arrival_soc_pct"] = 10.0
print(f"  cn.charging_required: {cn_fast_dict.get('charging_required')}")
print(f"  cn.critical_segment_no: {cn_fast_dict.get('critical_segment_no')}")
print(f"  cn.needs_charging: {cn_fast_dict.get('needs_charging')}")

selector2 = ChargingStopSelector()
sel_fast = selector2.select_stop(
    vehicle=v_dict, route_context=route_context, simulation_result=sim_fast_dict,
    charge_need=cn_fast_dict, strategy="fast",
)
print(f"  Selector picked: {sel_fast.get('selected_station', {}).get('name', '-') if sel_fast.get('selected_station') else None}")
print(f"  Candidate count: {len(sel_fast.get('candidates', []))}")

plan_fast = planner.build_plan(
    vehicle=v_dict, route_context=route_context, simulation_result=sim_fast_dict,
    charge_need=cn_fast_dict, selector_result=sel_fast, strategy="fast",
)
print(f"  build_plan stops: {plan_fast['summary'].get('stop_count')}, status: {plan_fast['status']}, solver: {plan_fast.get('solver', 'n/a')}")

# Simdi simulator gecirmeden:
result2 = profiles_engine.generate_profiles(
    vehicle=v_dict,
    route_context=route_context,
    simulation_result=sim_dict,
    charge_need=cn_dict,
    strategies=["fast", "balanced", "efficient"],
)
print("\n=== simulator GECIRILMEDEN sonuc ===")
for s in ["fast", "balanced", "efficient"]:
    p = result2["profiles"].get(s, {})
    summ = p.get("summary", {})
    stops = p.get("recommended_stops") or []
    print(f"  {s}: feasible={p.get('feasible')}, stops={len(stops)}, total={summ.get('total_trip_minutes')}dk")

for s in ["fast", "balanced", "efficient"]:
    p = result["profiles"].get(s, {})
    summ = p.get("summary", {})
    stops = p.get("recommended_stops") or []
    print(f"\n== {s} (feasible={p.get('feasible')}) ==")
    print(f"  Stops: {len(stops)}, Total: {summ.get('total_trip_minutes')} dk")
    print(f"  Status: {p.get('status')} | solver: {p.get('solver', 'n/a')}")
    for st in stops[:8]:
        nm = (st.get('name') or '').encode('ascii', 'replace').decode()[:40]
        print(f"    -> {nm:<43s}: along={st.get('distance_along_route_km')}km")
