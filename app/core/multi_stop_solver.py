"""Multi-stop sarj plani icin Dijkstra labeled-graph solver.

Greedy yaklasim lokal optimuma takiliyordu: mevcut konumdan ulasilabilir en uzak
istasyonu sec -> ileride guclu sarj olmamasi durumu yakalanmiyor.

State = (station_index, soc_bucket_pct). Edge: i'den j'ye (varisi en az reserve+min
buffer ile mumkunse). Edge cost: stratejiye gore (drive_time + charge_time) ya da
weighted (time/energy/cost/safety).

Literatur referansi: Sweda & Klabjan 2012; Storandt 2012.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class _Node:
    """Graf node: -1 = start, len(stations) = end, aksi halde istasyon indeksi."""
    station_idx: int  # -1 start, N end
    soc_bucket: int  # 0..10 (her bucket %10)


@dataclass
class MultiStopSolution:
    chain: List[Dict[str, Any]]  # secilen istasyonlar (enriched)
    total_drive_minutes: float
    total_charge_minutes: float
    total_trip_minutes: float
    feasible: bool


class MultiStopDijkstraSolver:
    """Multi-stop sarj plani solver. State = (station, SOC bucket %10)."""

    def __init__(
        self,
        *,
        soc_bucket_pct: int = 10,
        max_target_soc_pct: float = 85.0,
        detour_speed_kmh: float = 40.0,
        avg_speed_kmh: float = 90.0,
    ) -> None:
        self.soc_bucket_pct = soc_bucket_pct
        self.max_target_soc_pct = max_target_soc_pct
        self.detour_speed_kmh = detour_speed_kmh
        self.avg_speed_kmh = avg_speed_kmh

    def solve(
        self,
        *,
        stations: List[Dict[str, Any]],
        route_distance_km: float,
        usable_battery_kwh: float,
        avg_consumption_kwh_per_km: float,
        initial_soc_pct: float,
        reserve_soc_pct: float,
        arrival_soc_floor_pct: float,
        charge_minutes_fn: Callable[[float, float, float], float],
        edge_cost_fn: Optional[Callable[[Dict[str, Any]], float]] = None,
    ) -> Optional[MultiStopSolution]:
        """
        charge_minutes_fn(station_power_kw, start_soc, target_soc) -> dakika
        edge_cost_fn(edge_metrics_dict) -> skor (varsayilan: drive+charge dakikalari)
        """
        if not stations or usable_battery_kwh <= 0 or avg_consumption_kwh_per_km <= 0:
            return None
        if route_distance_km <= 0:
            return None

        # Istasyonlari rota mesafesine gore sirala.
        ordered = sorted(stations, key=lambda s: float(s.get("distance_along_route_km", 0)))
        end_distance = route_distance_km
        end_idx = len(ordered)

        # Reachable mesafe: belirli SOC ile ne kadar km gidilebilir (reserve uzerinde).
        def reachable_km(from_soc_pct: float) -> float:
            usable_pct = max(0.0, from_soc_pct - reserve_soc_pct)
            energy_kwh = usable_pct / 100.0 * usable_battery_kwh
            return energy_kwh / avg_consumption_kwh_per_km

        # SOC bucket -> percent (orta nokta tercih ediliyor: 10 -> 5% yerine
        # bucket=k 'nin temsil ettigi soc = k*10).
        def bucket_to_pct(bucket: int) -> float:
            return min(100.0, max(0.0, bucket * self.soc_bucket_pct))

        def pct_to_bucket(pct: float) -> int:
            return max(0, min(10, int(round(pct / self.soc_bucket_pct))))

        def default_edge_cost(edge_metrics: Dict[str, Any]) -> float:
            return float(edge_metrics["drive_minutes"]) + float(edge_metrics["charge_minutes"])

        cost_fn = edge_cost_fn or default_edge_cost

        # Start node: SOC bucket = initial_soc'nin bucket'i.
        start_bucket = pct_to_bucket(initial_soc_pct)
        start_node = _Node(station_idx=-1, soc_bucket=start_bucket)

        # Dijkstra: priority queue (cost, node, path).
        # Path = liste of (station_idx, target_soc_pct, charge_minutes, drive_minutes_from_prev).
        initial_path: List[Tuple[int, float, float, float]] = []
        heap: List[Tuple[float, int, _Node, List]] = [
            (0.0, 0, start_node, initial_path)
        ]
        # Visited best cost per (station_idx, soc_bucket).
        best: Dict[Tuple[int, int], float] = {}

        counter = 1
        max_iters = 50000  # guvenlik tavani

        while heap and max_iters > 0:
            max_iters -= 1
            cost, _, node, path = heapq.heappop(heap)
            key = (node.station_idx, node.soc_bucket)
            if key in best and best[key] <= cost:
                continue
            best[key] = cost

            # End'e ulastik mi?
            current_distance_km = (
                end_distance if node.station_idx == end_idx
                else (0.0 if node.station_idx == -1
                      else float(ordered[node.station_idx].get("distance_along_route_km", 0)))
            )

            if node.station_idx == end_idx:
                # Arrival SOC floor saglandi mi? bucket arrival_floor'dan dusukse atla.
                arrival_pct = bucket_to_pct(node.soc_bucket)
                if arrival_pct < arrival_soc_floor_pct:
                    continue
                # En kucuk cost ile uca ulastik.
                return self._build_solution(path, ordered, cost_fn)

            current_soc_pct = bucket_to_pct(node.soc_bucket)
            reach = reachable_km(current_soc_pct)

            # Komsu adaylar: ileri konumdaki istasyonlar veya end.
            candidates: List[Tuple[int, float]] = []
            for j in range(max(0, node.station_idx + 1), len(ordered)):
                j_distance = float(ordered[j].get("distance_along_route_km", 0))
                if j_distance <= current_distance_km:
                    continue
                leg_km = j_distance - current_distance_km
                if leg_km > reach:
                    break  # ileri istasyonlar daha uzak; ulasilamaz
                candidates.append((j, leg_km))

            # End'e direk gitme adayi:
            end_leg_km = end_distance - current_distance_km
            if end_leg_km <= reach:
                candidates.append((end_idx, end_leg_km))

            for j, leg_km in candidates:
                # j'ye varisindaki SOC:
                consumed_pct = (leg_km * avg_consumption_kwh_per_km / usable_battery_kwh) * 100.0
                soc_at_j_pct = current_soc_pct - consumed_pct

                if j == end_idx:
                    # End: charge yok. Drive only.
                    drive_min = (leg_km / self.avg_speed_kmh) * 60.0
                    arrival_bucket = pct_to_bucket(soc_at_j_pct)
                    end_node = _Node(station_idx=end_idx, soc_bucket=arrival_bucket)
                    edge_cost = cost_fn({
                        "drive_minutes": drive_min,
                        "charge_minutes": 0.0,
                        "leg_km": leg_km,
                    })
                    new_cost = cost_fn_total = cost + edge_cost
                    new_path = path + [(end_idx, bucket_to_pct(arrival_bucket), 0.0, drive_min)]
                    heapq.heappush(heap, (new_cost, counter, end_node, new_path))
                    counter += 1
                    continue

                # Istasyona vardik; rezerv + 3pp buffer.
                if soc_at_j_pct < reserve_soc_pct + 3.0:
                    continue

                station = ordered[j]
                station_power_kw = float(station.get("power_kw", 50.0))
                detour_km = float(station.get("detour_distance_km", 0.0))
                detour_min = (detour_km / self.detour_speed_kmh) * 60.0 if self.detour_speed_kmh > 0 else 0.0
                drive_min = (leg_km / self.avg_speed_kmh) * 60.0

                # Hedef SOC bucket: min ulasilabilir + buffer'dan max_target'a.
                # Dijkstra her bucket'i ayri state olarak isler; 1 charge bucket
                # secimi yerine birden cok target'i deneyelim.
                soc_at_j_bucket = pct_to_bucket(soc_at_j_pct)
                max_target_bucket = pct_to_bucket(self.max_target_soc_pct)
                for target_bucket in range(max(soc_at_j_bucket, 4), max_target_bucket + 1):
                    target_pct = bucket_to_pct(target_bucket)
                    if target_pct <= soc_at_j_pct:
                        # En azindan mevcut SOC seviyesi (hic sarj yapmadan gec)
                        if target_bucket == soc_at_j_bucket:
                            charge_min = 0.0
                        else:
                            continue
                    else:
                        charge_min = charge_minutes_fn(station_power_kw, soc_at_j_pct, target_pct)

                    new_node = _Node(station_idx=j, soc_bucket=target_bucket)
                    key2 = (j, target_bucket)
                    edge_cost = cost_fn({
                        "drive_minutes": drive_min + detour_min,
                        "charge_minutes": charge_min,
                        "leg_km": leg_km,
                        "detour_km": detour_km,
                        "station_power_kw": station_power_kw,
                    })
                    new_cost = cost + edge_cost
                    if key2 in best and best[key2] <= new_cost:
                        continue
                    new_path = path + [(j, target_pct, charge_min, drive_min + detour_min)]
                    heapq.heappush(heap, (new_cost, counter, new_node, new_path))
                    counter += 1

        return None

    def _build_solution(
        self,
        path: List[Tuple[int, float, float, float]],
        ordered_stations: List[Dict[str, Any]],
        cost_fn: Callable[[Dict[str, Any]], float],
    ) -> MultiStopSolution:
        chain: List[Dict[str, Any]] = []
        total_drive = 0.0
        total_charge = 0.0
        for idx, target_pct, charge_min, drive_min in path:
            total_drive += drive_min
            total_charge += charge_min
            if idx >= 0 and idx < len(ordered_stations):
                station_copy = dict(ordered_stations[idx])
                station_copy["target_soc_percent"] = round(target_pct, 1)
                station_copy["charge_minutes"] = round(charge_min, 1)
                station_copy["drive_minutes_to_here"] = round(drive_min, 1)
                chain.append(station_copy)
        return MultiStopSolution(
            chain=chain,
            total_drive_minutes=round(total_drive, 1),
            total_charge_minutes=round(total_charge, 1),
            total_trip_minutes=round(total_drive + total_charge, 1),
            feasible=True,
        )
