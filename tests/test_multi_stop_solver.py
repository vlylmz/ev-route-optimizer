import time

from app.core.multi_stop_solver import MultiStopDijkstraSolver


def _dummy_charge_minutes(station_kw: float, start_soc: float, target_soc: float) -> float:
    """Lineer yaklasim - test icin basit."""
    if target_soc <= start_soc or station_kw <= 0:
        return 0.0
    # Sabit 60 kWh batarya ve %100 verim varsayalim
    delta_pct = target_soc - start_soc
    energy_kwh = delta_pct / 100.0 * 60.0
    return (energy_kwh / station_kw) * 60.0


def test_dijkstra_solver_basic_2_stop_feasible():
    """Basit 2-istasyon rota: hem A hem B'den gecip varisa ulasmali."""
    solver = MultiStopDijkstraSolver(
        soc_bucket_pct=10,
        max_target_soc_pct=80.0,
        avg_speed_kmh=90.0,
    )

    stations = [
        {"name": "A", "distance_along_route_km": 100, "power_kw": 100,
         "detour_distance_km": 1.0},
        {"name": "B", "distance_along_route_km": 300, "power_kw": 100,
         "detour_distance_km": 1.0},
    ]

    solution = solver.solve(
        stations=stations,
        route_distance_km=500,
        usable_battery_kwh=60.0,
        avg_consumption_kwh_per_km=0.18,
        initial_soc_pct=90.0,
        reserve_soc_pct=10.0,
        arrival_soc_floor_pct=10.0,
        charge_minutes_fn=_dummy_charge_minutes,
    )

    assert solution is not None
    assert solution.feasible
    assert len(solution.chain) >= 1
    assert solution.total_trip_minutes > 0


def test_dijkstra_solver_unreachable_returns_none():
    """Initial SOC dusuk + tek uzak istasyon -> infeasible (None)."""
    solver = MultiStopDijkstraSolver(avg_speed_kmh=90.0)

    stations = [
        {"name": "Uzak", "distance_along_route_km": 800, "power_kw": 100,
         "detour_distance_km": 0.5},
    ]

    solution = solver.solve(
        stations=stations,
        route_distance_km=1000,
        usable_battery_kwh=40.0,
        avg_consumption_kwh_per_km=0.20,
        initial_soc_pct=20.0,  # cok dusuk
        reserve_soc_pct=10.0,
        arrival_soc_floor_pct=10.0,
        charge_minutes_fn=_dummy_charge_minutes,
    )

    assert solution is None


def test_dijkstra_finds_better_chain_than_naive_greedy():
    """Bilinen karsi ornek: greedy 'mevcut konumdan en uzak ulasilabilir' kuralinin
    bozuldugu senaryo.

    A=200km dusuk guc, B=350km dusuk guc, C=450km YUKSEK guc, D=700km dusuk guc.
    Naive greedy A'ya gider, sonra B veya direkt C'ye. Dijkstra C'yi tercih edebilir."""
    solver = MultiStopDijkstraSolver(avg_speed_kmh=90.0)

    stations = [
        {"name": "A", "distance_along_route_km": 100, "power_kw": 50,
         "detour_distance_km": 0.5},
        {"name": "B", "distance_along_route_km": 200, "power_kw": 50,
         "detour_distance_km": 0.5},
        {"name": "C", "distance_along_route_km": 300, "power_kw": 250,
         "detour_distance_km": 0.5},
        {"name": "D", "distance_along_route_km": 500, "power_kw": 50,
         "detour_distance_km": 0.5},
    ]

    solution = solver.solve(
        stations=stations,
        route_distance_km=600,
        usable_battery_kwh=60.0,
        avg_consumption_kwh_per_km=0.18,
        initial_soc_pct=90.0,
        reserve_soc_pct=10.0,
        arrival_soc_floor_pct=10.0,
        charge_minutes_fn=_dummy_charge_minutes,
    )

    assert solution is not None
    chain_names = [s["name"] for s in solution.chain]
    # Yuksek guclu C kullanilmali (sarj minimize).
    assert "C" in chain_names


def test_long_route_with_50_stations_completes_under_2s():
    """Performance smoke: 50 istasyon < 2 saniye."""
    solver = MultiStopDijkstraSolver(avg_speed_kmh=90.0)

    stations = [
        {
            "name": f"S{i}",
            "distance_along_route_km": 50 + i * 25,
            "power_kw": 100 + (i % 5) * 30,
            "detour_distance_km": 0.5,
        }
        for i in range(50)
    ]

    start = time.perf_counter()
    solution = solver.solve(
        stations=stations,
        route_distance_km=1500,
        usable_battery_kwh=60.0,
        avg_consumption_kwh_per_km=0.18,
        initial_soc_pct=90.0,
        reserve_soc_pct=10.0,
        arrival_soc_floor_pct=10.0,
        charge_minutes_fn=_dummy_charge_minutes,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"Dijkstra 50 istasyon {elapsed:.2f}s (>2s)"
    assert solution is not None
