"""Amasya-Izmir multi-stop neden infeasible kontrol."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
import json

# /optimize sonucu raw alaninda multi-stop debug bilgisi alalim
resp = requests.post(
    "http://localhost:8000/optimize",
    json={
        "vehicle_id": "tesla_model_y_rwd",
        "start": {"lat": 40.6499, "lon": 35.8353},
        "end": {"lat": 38.4192, "lon": 27.1287},
        "initial_soc_pct": 80,
        "target_arrival_soc_pct": 20,
        "min_stop_minutes": 10,
    },
    timeout=180,
)
data = resp.json()
print("Distance:", data["total_distance_km"], "km")
print("Energy:", data["total_energy_kwh"], "kWh")
print()
for p in data["profiles"]:
    print(f"=== {p['label']} (feasible={p['feasible']}) ===")
    raw = p.get("raw", {})
    summary = raw.get("summary", {})
    print(f"  Status: {raw.get('status')}")
    print(f"  Stop count: {summary.get('stop_count')}")
    print(f"  Total trip: {summary.get('total_trip_minutes')} dk")
    print(f"  Projected arrival SOC: {summary.get('projected_arrival_soc_percent')}")
    print()

# Simdi /route ile istasyon dagilimina bakalim
print("=== Istasyon dagilimi ===")
resp2 = requests.post(
    "http://localhost:8000/route",
    json={"start": {"lat": 40.6499, "lon": 35.8353}, "end": {"lat": 38.4192, "lon": 27.1287}},
    timeout=180,
)
data2 = resp2.json()
print(f"Toplam {len(data2['stations'])} istasyon")

# Distance_along var mi?
stations_with_dist = [s for s in data2["stations"] if s.get("distance_km") is not None]
print(f"  distance_km olan: {len(stations_with_dist)}")

# Power dagilimi
power_buckets = {"50+": 0, "100+": 0, "150+": 0, "250+": 0, "350+": 0, "0kW": 0}
for s in data2["stations"]:
    conns = s.get("connections", [])
    max_p = max((c.get("power_kw") or 0) for c in conns) if conns else 0
    if max_p >= 350:
        power_buckets["350+"] += 1
    elif max_p >= 250:
        power_buckets["250+"] += 1
    elif max_p >= 150:
        power_buckets["150+"] += 1
    elif max_p >= 100:
        power_buckets["100+"] += 1
    elif max_p >= 50:
        power_buckets["50+"] += 1
    else:
        power_buckets["0kW"] += 1
print("  Power buckets:", power_buckets)
