from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.charging_stop_selector import (
    _extract_station_connectors,
    _vehicle_connector_set,
)
from app.core.geo_utils import RouteSpatialIndex, haversine_km as _haversine_km
from app.core.station_enricher import (
    passes_hard_filters,
    resolve_station_route_metrics,
)
from app.core.utils import pick as _pick, safe_float as _safe_float


class ChargingPlanner:
    """
    charging_stop_selector sonucunu alir ve uygulanabilir
    tek durakli bir sarj plani uretir.

    Bu katman:
    - final trip metrics hesaplar
    - durak listesini normalize eder
    - toplam sure / toplam enerji / tahmini varis SOC dondurur
    - ML kullanim ozetini yukari tasir

    Not:
    Ilk surum MVP icin tek durakli plan uretiyor.
    Cok durakli plan daha sonra genisletilebilir.
    """

    def __init__(
        self,
        *,
        reserve_soc_default: float = 10.0,
        energy_buffer_factor: float = 1.05,
        min_stop_minutes: float = 10.0,
        max_stops: int = 8,
        curve_service: Any = None,
        use_dijkstra: bool = True,
        dijkstra_station_limit: int = 100,
    ) -> None:
        from app.services.charging_curve_service import ChargingCurveService

        self.reserve_soc_default = reserve_soc_default
        self.energy_buffer_factor = energy_buffer_factor
        self.min_stop_minutes = min_stop_minutes
        self.max_stops = max_stops
        self.curve_service = curve_service or ChargingCurveService()
        self.use_dijkstra = use_dijkstra
        self.dijkstra_station_limit = dijkstra_station_limit

    def build_plan(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
        selector_result: Dict[str, Any],
        strategy: str = "balanced",
    ) -> Dict[str, Any]:
        needs_charging = bool(
            _pick(
                charge_need,
                "needs_charging",
                "requires_charging",
                "charging_required",
                default=False,
            )
        )

        metrics = self._compute_trip_metrics(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result=simulation_result,
            charge_need=charge_need,
        )
        route_distance_km = metrics["route_distance_km"]
        route_duration_min = metrics["route_duration_min"]
        total_energy_kwh = metrics["total_energy_kwh"]
        final_soc_without_charge = metrics["final_soc_without_charge"]
        usable_battery_kwh = metrics["usable_battery_kwh"]
        avg_consumption_kwh_per_km = metrics["avg_consumption_kwh_per_km"]
        ml_summary = metrics["ml_summary"]

        if not needs_charging:
            return {
                "status": "ok",
                "strategy": strategy,
                "needs_charging": False,
                "feasible": final_soc_without_charge >= 0,
                "recommended_stops": [],
                "summary": {
                    "stop_count": 0,
                    "charge_minutes": 0.0,
                    "detour_minutes": 0.0,
                    "total_trip_minutes": round(route_duration_min, 1),
                    "total_energy_kwh": round(total_energy_kwh, 2),
                    "projected_arrival_soc_percent": round(final_soc_without_charge, 2),
                },
                "ml_summary": ml_summary,
                "message": "Şarj gerekmiyor.",
            }

        selected_station = _pick(selector_result, "selected_station", default=None)

        if not selected_station:
            return {
                "status": "no_feasible_plan",
                "strategy": strategy,
                "needs_charging": True,
                "feasible": False,
                "recommended_stops": [],
                "summary": {
                    "stop_count": 0,
                    "charge_minutes": 0.0,
                    "detour_minutes": 0.0,
                    "total_trip_minutes": round(route_duration_min, 1),
                    "total_energy_kwh": round(total_energy_kwh, 2),
                    "projected_arrival_soc_percent": None,
                },
                "ml_summary": ml_summary,
                "message": "Uygun bir şarj planı oluşturulamadı.",
            }

        reserve_soc, target_arrival_soc, effective_arrival_floor = self._resolve_arrival_floor(
            charge_need=charge_need,
            strategy=strategy,
        )

        station_name = _pick(selected_station, "name", "title", default="İstasyon")
        distance_along_route_km = _safe_float(
            _pick(selected_station, "distance_along_route_km"),
            0.0,
        )
        remaining_distance_km = _safe_float(
            _pick(selected_station, "remaining_distance_km"),
            max(route_distance_km - distance_along_route_km, 0.0),
        )
        detour_distance_km = _safe_float(
            _pick(selected_station, "detour_distance_km"),
            0.0,
        )
        detour_minutes = _safe_float(
            _pick(selected_station, "detour_minutes"),
            0.0,
        )
        charge_minutes = _safe_float(
            _pick(selected_station, "charge_minutes"),
            0.0,
        )
        arrival_soc_at_station = _safe_float(
            _pick(selected_station, "soc_at_arrival_percent"),
            0.0,
        )
        target_soc_percent = _safe_float(
            _pick(selected_station, "target_soc_percent"),
            0.0,
        )
        station_power_kw = _safe_float(
            _pick(selected_station, "power_kw", "max_power_kw", "dc_power_kw"),
            0.0,
        )

        target_soc_percent, charge_minutes = self._apply_min_stop_extension(
            vehicle=vehicle,
            station_power_kw=station_power_kw,
            arrival_soc_at_station=arrival_soc_at_station,
            target_soc_percent=target_soc_percent,
            charge_minutes=charge_minutes,
            usable_battery_kwh=usable_battery_kwh,
        )

        post_charge_remaining_distance_km = remaining_distance_km + detour_distance_km
        required_post_charge_energy_kwh = (
            post_charge_remaining_distance_km
            * avg_consumption_kwh_per_km
            * self.energy_buffer_factor
        )

        if usable_battery_kwh > 0:
            required_post_charge_soc_percent = (
                required_post_charge_energy_kwh / usable_battery_kwh
            ) * 100.0
        else:
            required_post_charge_soc_percent = 999.0

        projected_arrival_soc_percent = target_soc_percent - required_post_charge_soc_percent
        projected_arrival_soc_percent = max(projected_arrival_soc_percent, 0.0)

        feasible = projected_arrival_soc_percent >= effective_arrival_floor

        extra_detour_energy_kwh = detour_distance_km * avg_consumption_kwh_per_km
        total_trip_energy_kwh = total_energy_kwh + extra_detour_energy_kwh
        total_trip_minutes = route_duration_min + detour_minutes + charge_minutes

        stop = {
            "name": station_name,
            "operator": _pick(selected_station, "operator"),
            "distance_along_route_km": round(distance_along_route_km, 2),
            "detour_distance_km": round(detour_distance_km, 2),
            "detour_minutes": round(detour_minutes, 1),
            "arrival_soc_percent": round(arrival_soc_at_station, 2),
            "target_soc_percent": round(target_soc_percent, 2),
            "charge_minutes": round(charge_minutes, 1),
            "power_kw": round(station_power_kw, 1),
            "is_dc": station_power_kw >= 50.0,
        }

        single_stop_result: Dict[str, Any] = {
            "status": "ok" if feasible else "risky_plan",
            "strategy": strategy,
            "needs_charging": True,
            "feasible": feasible,
            "recommended_stops": [stop],
            "summary": {
                "stop_count": 1,
                "charge_minutes": round(charge_minutes, 1),
                "detour_minutes": round(detour_minutes, 1),
                "total_trip_minutes": round(total_trip_minutes, 1),
                "total_energy_kwh": round(total_trip_energy_kwh, 2),
                "projected_arrival_soc_percent": round(projected_arrival_soc_percent, 2),
            },
            "ml_summary": ml_summary,
            "message": self._build_message(
                station_name=station_name,
                feasible=feasible,
                projected_arrival_soc_percent=projected_arrival_soc_percent,
                total_trip_minutes=total_trip_minutes,
                used_ml=bool(_pick(ml_summary, "used_ml", default=False)),
                model_version=_pick(ml_summary, "model_version", default=None),
            ),
        }

        # Tek durak yeterliyse direkt dön; degilse cok durakli zinciri dene.
        if feasible:
            return single_stop_result

        multi_stop_result = self._try_multi_stop(
            vehicle=vehicle,
            route_context=route_context,
            simulation_result=simulation_result,
            strategy=strategy,
            route_distance_km=route_distance_km,
            route_duration_min=route_duration_min,
            total_energy_kwh=total_energy_kwh,
            ml_summary=ml_summary,
            avg_consumption_kwh_per_km=avg_consumption_kwh_per_km,
            usable_battery_kwh=usable_battery_kwh,
            reserve_soc=reserve_soc,
            target_arrival_soc=target_arrival_soc,
        )

        if multi_stop_result is not None and multi_stop_result.get("feasible"):
            return multi_stop_result

        # Hem single hem multi infeasible: daha bilgili olani sec.
        return self._select_better_plan(single_stop_result, multi_stop_result)

    # =====================================================================
    # build_plan helper'lari
    # =====================================================================

    def _compute_trip_metrics(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
    ) -> Dict[str, Any]:
        """build_plan'in temel metric setup'i: distance/duration/energy/consumption."""
        route = _pick(route_context, "route", default={}) or {}
        route_distance_km = _safe_float(
            _pick(route, "distance_km", "total_distance_km"), 0.0
        )
        route_duration_min = _safe_float(
            _pick(route, "duration_min", "duration_minutes", "estimated_duration_min"),
            0.0,
        )
        total_energy_kwh = _safe_float(
            _pick(simulation_result, "total_energy_kwh", "energy_used_kwh"), 0.0
        )
        final_soc_without_charge = self._extract_final_soc(simulation_result)
        usable_battery_kwh = _safe_float(
            _pick(vehicle, "usable_battery_kwh", "battery_capacity_kwh"), 0.0
        )
        avg_consumption_kwh_per_km = self._resolve_avg_consumption(
            route_distance_km=route_distance_km,
            total_energy_kwh=total_energy_kwh,
            vehicle=vehicle,
        )
        ml_summary = self._extract_ml_summary(
            simulation_result=simulation_result, charge_need=charge_need,
        )
        return {
            "route_distance_km": route_distance_km,
            "route_duration_min": route_duration_min,
            "total_energy_kwh": total_energy_kwh,
            "final_soc_without_charge": final_soc_without_charge,
            "usable_battery_kwh": usable_battery_kwh,
            "avg_consumption_kwh_per_km": avg_consumption_kwh_per_km,
            "ml_summary": ml_summary,
        }

    def _resolve_arrival_floor(
        self,
        *,
        charge_need: Dict[str, Any],
        strategy: str,
    ) -> tuple[float, float, float]:
        """Reserve SOC + user target -> effective_arrival_floor.
        Donus: (reserve_soc, target_arrival_soc, effective_arrival_floor)."""
        reserve_soc = _safe_float(
            _pick(
                charge_need,
                "reserve_soc_percent",
                "min_soc_percent",
                "reserve_soc_pct",
                default=self.reserve_soc_default,
            ),
            self.reserve_soc_default,
        )
        target_arrival_soc = _safe_float(
            _pick(charge_need, "target_arrival_soc_pct", default=None),
            reserve_soc,
        )
        # Dengeli profil multi-stop'a egilim icin ek %10 marj.
        strategy_arrival_bonus = 10.0 if strategy == "balanced" else 0.0
        effective_arrival_floor = (
            max(reserve_soc, target_arrival_soc) + strategy_arrival_bonus
        )
        return reserve_soc, target_arrival_soc, effective_arrival_floor

    def _apply_min_stop_extension(
        self,
        *,
        vehicle: Dict[str, Any],
        station_power_kw: float,
        arrival_soc_at_station: float,
        target_soc_percent: float,
        charge_minutes: float,
        usable_battery_kwh: float,
    ) -> tuple[float, float]:
        """Kullanici 1-2 dk icin durmaz. Charge<min_stop ise target SOC'u yukselt."""
        if (
            self.min_stop_minutes <= 0
            or charge_minutes >= self.min_stop_minutes
            or station_power_kw <= 0
        ):
            return target_soc_percent, charge_minutes

        extended_target = self.curve_service.find_target_soc_for_minutes(
            vehicle=vehicle,
            station_kw=station_power_kw,
            start_soc_pct=arrival_soc_at_station,
            target_minutes=self.min_stop_minutes,
            usable_battery_kwh=usable_battery_kwh,
            max_target=90.0,
        )
        if extended_target > target_soc_percent:
            new_target = extended_target
            new_minutes = self.curve_service.compute_charge_minutes(
                vehicle=vehicle,
                station_kw=station_power_kw,
                start_soc_pct=arrival_soc_at_station,
                target_soc_pct=new_target,
                usable_battery_kwh=usable_battery_kwh,
            )
            return new_target, new_minutes
        return target_soc_percent, charge_minutes

    @staticmethod
    def _select_better_plan(
        single_result: Dict[str, Any],
        multi_result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Hem single hem multi infeasible ise daha bilgili olani (yuksek varis
        SOC) dondur. Multi yoksa single dondur."""
        if multi_result is None or not multi_result.get("recommended_stops"):
            return single_result

        single_arrival = _safe_float(
            _pick(single_result.get("summary", {}), "projected_arrival_soc_percent", default=0.0),
            0.0,
        )
        multi_arrival = _safe_float(
            _pick(multi_result.get("summary", {}), "projected_arrival_soc_percent", default=0.0),
            0.0,
        )
        return multi_result if multi_arrival > single_arrival else single_result

    def _try_multi_stop(
        self,
        *,
        vehicle: Dict[str, Any],
        route_context: Dict[str, Any],
        simulation_result: Dict[str, Any],
        strategy: str,
        route_distance_km: float,
        route_duration_min: float,
        total_energy_kwh: float,
        ml_summary: Dict[str, Any],
        avg_consumption_kwh_per_km: float,
        usable_battery_kwh: float,
        reserve_soc: float,
        target_arrival_soc: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Tek durak yetmedigi durumlarda greedy bir cok durakli zincir kurar.

        Strateji: mevcut konumdan reserve+buffer ile ulasilabilen en uzak
        istasyonu sec, sonraki adimi ya bitise ya da bir sonraki istasyona
        yetecek SOC'ye kadar sarj et, tekrar dene.
        """
        if usable_battery_kwh <= 0 or avg_consumption_kwh_per_km <= 0:
            return None

        if route_distance_km <= 0:
            return None

        enriched = self._enrich_all_stations(
            route_context=route_context, vehicle=vehicle
        )
        if not enriched:
            return None

        initial_soc = _safe_float(
            _pick(
                simulation_result,
                "initial_soc",
                "start_soc",
                "start_soc_pct",
                default=100.0,
            ),
            100.0,
        )

        # Dijkstra solver: makul istasyon sayisinda once optimal zinciri dene.
        # Basarisiz olursa greedy'e dus.
        if self.use_dijkstra and 0 < len(enriched) <= self.dijkstra_station_limit:
            dijkstra_plan = self._try_dijkstra_solver(
                enriched=enriched,
                vehicle=vehicle,
                strategy=strategy,
                route_distance_km=route_distance_km,
                route_duration_min=route_duration_min,
                total_energy_kwh=total_energy_kwh,
                ml_summary=ml_summary,
                initial_soc=initial_soc,
                avg_consumption_kwh_per_km=avg_consumption_kwh_per_km,
                usable_battery_kwh=usable_battery_kwh,
                reserve_soc=reserve_soc,
                target_arrival_soc=target_arrival_soc,
            )
            if dijkstra_plan is not None:
                return dijkstra_plan

        avg_speed_kmh = (
            (route_distance_km / route_duration_min) * 60.0
            if route_duration_min > 0
            else 80.0
        )

        # Strateji bazli ayarlar — fast/efficient/balanced farkli sonuclar uretsin diye
        if strategy == "fast":
            # En kisa toplam sure: yuksek guc istasyonlari, kucuk marj
            soc_buffer = 1.5
            max_target_soc = 75.0
            arrival_bonus = 0.0
        elif strategy == "efficient":
            # En dusuk enerji/sapma: dusuk sapmali istasyonlar, daha tutucu marj
            soc_buffer = 3.0
            max_target_soc = 70.0
            arrival_bonus = 0.0
        else:  # balanced
            soc_buffer = 2.0
            max_target_soc = 80.0
            arrival_bonus = 10.0  # ekstra guvenlik marji — varisi %10 yukari ittir

        # Dinamik max_stops: rota mesafesi / kullanilabilir menzil + safety marji.
        # Uzun rotada (orn. 1500km, 50kWh batarya) 5 durak yetmiyordu.
        if usable_battery_kwh > 0 and avg_consumption_kwh_per_km > 0:
            est_range_km = (usable_battery_kwh * 0.7) / avg_consumption_kwh_per_km
            min_stops_needed = max(1, int(route_distance_km / est_range_km))
            max_stops = max(self.max_stops, min_stops_needed + 3)
        else:
            max_stops = self.max_stops

        # Varişta tutulacak minimum SOC: reserve ile target'in büyüğü
        # + dengeli icin ek guvenlik bonusu (boylece duraklar arasi marjin yukari cikar)
        effective_arrival_floor = max(
            reserve_soc,
            float(target_arrival_soc) if target_arrival_soc is not None else 0.0,
        ) + arrival_bonus

        stops: List[Dict[str, Any]] = []
        current_distance = 0.0
        current_soc = initial_soc

        for _ in range(max_stops):
            remaining_km = max(route_distance_km - current_distance, 0.0)
            if remaining_km <= 0.001:
                break

            soc_to_finish_pct = (
                (remaining_km * avg_consumption_kwh_per_km * self.energy_buffer_factor)
                / usable_battery_kwh
            ) * 100.0

            if current_soc - soc_to_finish_pct >= effective_arrival_floor:
                break  # bitise istenen marjla ulasilabilir

            # Mevcut SOC ile reserve+buffer kalacak sekilde menzil
            usable_pct = max(current_soc - reserve_soc - soc_buffer, 0.0)
            max_reachable_km = (
                usable_pct
                * usable_battery_kwh
                / 100.0
                / avg_consumption_kwh_per_km
            )
            max_reach_distance = current_distance + max_reachable_km

            candidates = [
                s
                for s in enriched
                if current_distance + 1.0 < s["distance_along_route_km"]
                <= max_reach_distance + 0.1
            ]
            if not candidates:
                return None  # cok durakli plan da kuramiyoruz

            # Faydasiz erken duraklari ele: ulasilabilir mesafenin son %40'inda
            # olmayan stoplari at. Battery'yi yeterince kullanmadan duraklarsak
            # 0-1 dk sarjli bos stoplar olusuyor; bu filtre onu engeller.
            useful_threshold_km = current_distance + max_reachable_km * 0.6
            useful = [
                s
                for s in candidates
                if s["distance_along_route_km"] >= useful_threshold_km
            ]
            if not useful:
                useful = candidates  # esige hicbiri ulasamiyorsa fallback

            # Strateji bazli secim
            # "Fast" icin yuksek-guc istasyonlar oncelik (≥100kW). Boylece
            # "fast" ve "efficient" ayni 22kW yavas istasyonu secip benzemiyor.
            if strategy == "fast":
                high_power = [
                    s
                    for s in useful
                    if _safe_float(s.get("power_kw"), 0.0) >= 100.0
                ]
                if high_power:
                    useful = high_power

            if strategy == "fast":
                # Toplam ek sure (detour + efektif sarj suresi) minimize et —
                # sadece guc bakmak yetmez, sapma 350 kW istasyona gitmek de pahali.
                # Sarj suresi min_stop_minutes esigine clamp edilir (gerc-life: 10dk
                # altindaysa zaten min stop kuralina takilip uzayacak).
                min_stop = self.min_stop_minutes

                def fast_total_time_score(s: Dict[str, Any]) -> float:
                    detour_min = (
                        _safe_float(s.get("detour_distance_km"), 0.0) / 40.0
                    ) * 60.0
                    leg_km = max(
                        s["distance_along_route_km"] - current_distance, 0.0
                    )
                    soc_drop = (
                        (leg_km * avg_consumption_kwh_per_km) / usable_battery_kwh
                    ) * 100.0
                    arrival = max(current_soc - soc_drop, 0.0)
                    remaining_after = max(
                        route_distance_km - s["distance_along_route_km"], 0.0
                    )
                    soc_need_after = (
                        (
                            remaining_after
                            * avg_consumption_kwh_per_km
                            * self.energy_buffer_factor
                        )
                        / usable_battery_kwh
                    ) * 100.0
                    target = min(
                        soc_need_after + effective_arrival_floor, max_target_soc
                    )
                    target = max(target, arrival)
                    delta_kwh = (
                        max(target - arrival, 0.0) / 100.0 * usable_battery_kwh
                    )
                    power = max(_safe_float(s.get("power_kw"), 50.0), 1.0)
                    # 1.4 = ortalama taper faktoru (egri %50+ icin yavaslar)
                    charge_min = (delta_kwh / power) * 60.0 * 1.4
                    # Min stop kurali: 10dk altinda olamaz, gercek planda uzayacak
                    if min_stop > 0:
                        charge_min = max(charge_min, min_stop)
                    return detour_min + charge_min

                useful.sort(key=fast_total_time_score)
            elif strategy == "efficient":
                # En dusuk sapma → ek enerji minimum; esitlikte en uzak
                useful.sort(
                    key=lambda s: (
                        _safe_float(s.get("detour_distance_km"), 0.0),
                        -s["distance_along_route_km"],
                    )
                )
            else:  # balanced
                # En uzaktan basla, esitlikte en gucluyu sec
                useful.sort(
                    key=lambda s: (-s["distance_along_route_km"], -s["power_kw"])
                )
            selected = useful[0]

            leg_km = selected["distance_along_route_km"] - current_distance
            soc_drop_pct = (
                (leg_km * avg_consumption_kwh_per_km) / usable_battery_kwh
            ) * 100.0
            soc_at_arrival = current_soc - soc_drop_pct

            # Hedef SOC: kalan mesafeyi varış marjıyla bitirmeye yetecek kadar
            remaining_after_stop = max(
                route_distance_km - selected["distance_along_route_km"], 0.0
            )
            soc_to_finish_after_pct = (
                (
                    remaining_after_stop
                    * avg_consumption_kwh_per_km
                    * self.energy_buffer_factor
                )
                / usable_battery_kwh
            ) * 100.0
            # Hedef SOC: kalan mesafeyi tamamlayacak + arrival floor (target_arrival)
            # Strateji limiti (max_target_soc) ihtiyactan az kalirsa %90'a kadar
            # gevseklet — yoksa ihtiyac karsilanmaz, gereksiz ek durak eklenir.
            needed_target = soc_to_finish_after_pct + effective_arrival_floor
            if needed_target <= max_target_soc:
                target_soc = needed_target  # ihtiyac kadar (overcharge etme)
            else:
                target_soc = min(needed_target, 90.0)  # ihtiyac fazla → gevsek
            target_soc = max(target_soc, soc_at_arrival)

            station_power_kw = max(_safe_float(selected.get("power_kw"), 50.0), 1.0)
            # Sofistike şarj eğrisi (vehicle.charge_curve_hint × station_kw)
            charge_minutes = self.curve_service.compute_charge_minutes(
                vehicle=vehicle,
                station_kw=station_power_kw,
                start_soc_pct=soc_at_arrival,
                target_soc_pct=target_soc,
                usable_battery_kwh=usable_battery_kwh,
            )
            # Min duraklama süresi: kullanıcı 1-2 dk için durmaz.
            # Süre çok kısaysa, target SOC'yi yükselt — gerekirse %90'a kadar
            # cik (max_target_soc'yi gevsetiyoruz, yoksa zaten max'taysak min
            # stop garantisi tutmuyor ve 0-1 dk durak cikiyor).
            if self.min_stop_minutes > 0 and charge_minutes < self.min_stop_minutes:
                extended_target = self.curve_service.find_target_soc_for_minutes(
                    vehicle=vehicle,
                    station_kw=station_power_kw,
                    start_soc_pct=soc_at_arrival,
                    target_minutes=self.min_stop_minutes,
                    usable_battery_kwh=usable_battery_kwh,
                    max_target=90.0,
                )
                if extended_target > target_soc:
                    target_soc = extended_target
                    charge_minutes = self.curve_service.compute_charge_minutes(
                        vehicle=vehicle,
                        station_kw=station_power_kw,
                        start_soc_pct=soc_at_arrival,
                        target_soc_pct=target_soc,
                        usable_battery_kwh=usable_battery_kwh,
                    )

            detour_km = _safe_float(selected.get("detour_distance_km"), 0.0)
            detour_minutes = (
                (detour_km / 40.0) * 60.0 if detour_km > 0 else 0.0
            )

            stops.append(
                {
                    "name": selected.get("name", "İstasyon"),
                    "operator": selected.get("operator"),
                    "distance_along_route_km": round(
                        selected["distance_along_route_km"], 2
                    ),
                    "detour_distance_km": round(detour_km, 2),
                    "detour_minutes": round(detour_minutes, 1),
                    "arrival_soc_percent": round(soc_at_arrival, 2),
                    "target_soc_percent": round(target_soc, 2),
                    "charge_minutes": round(charge_minutes, 1),
                    "power_kw": round(station_power_kw, 1),
                    "is_dc": station_power_kw >= 50.0,
                }
            )

            current_distance = selected["distance_along_route_km"]
            current_soc = target_soc
        # else: max_stops doldu ama hala bitemedik — yine de elimizdeki kismi
        # zinciri risky_plan olarak don. Tek-stop fallback'inin %0 varisindan
        # daha bilgili (birkac durak + projected arrival) sonuc cikar.

        if not stops:
            return None

        # Son duraktan varisa kalan SOC
        remaining_after_last = max(route_distance_km - current_distance, 0.0)
        final_soc_drop_pct = (
            (remaining_after_last * avg_consumption_kwh_per_km)
            / usable_battery_kwh
        ) * 100.0
        projected_arrival_soc = current_soc - final_soc_drop_pct

        feasible = projected_arrival_soc >= effective_arrival_floor

        total_charge_minutes = sum(s["charge_minutes"] for s in stops)
        total_detour_minutes = sum(s["detour_minutes"] for s in stops)
        total_detour_km = sum(s["detour_distance_km"] for s in stops)
        total_trip_minutes = (
            route_duration_min + total_detour_minutes + total_charge_minutes
        )
        total_trip_energy_kwh = (
            total_energy_kwh + total_detour_km * avg_consumption_kwh_per_km
        )

        # avg_speed kullanmasak da hesap dogru: route_duration_min zaten bitise
        # kadar olan tum suruyu kapsiyor.
        _ = avg_speed_kmh

        message = (
            f"{len(stops)} durakli plan olusturuldu. "
            f"Tahmini varis SOC: %{projected_arrival_soc:.1f}, "
            f"toplam sure: {total_trip_minutes:.1f} dk."
        )
        used_ml = bool(_pick(ml_summary, "used_ml", default=False))
        if used_ml:
            mv = _pick(ml_summary, "model_version", default=None)
            message += f" Tahmin kaynagi: ML ({mv})." if mv else " Tahmin kaynagi: ML."

        return {
            "status": "ok" if feasible else "risky_plan",
            "strategy": strategy,
            "needs_charging": True,
            "feasible": feasible,
            "recommended_stops": stops,
            "summary": {
                "stop_count": len(stops),
                "charge_minutes": round(total_charge_minutes, 1),
                "detour_minutes": round(total_detour_minutes, 1),
                "total_trip_minutes": round(total_trip_minutes, 1),
                "total_energy_kwh": round(total_trip_energy_kwh, 2),
                "projected_arrival_soc_percent": round(projected_arrival_soc, 2),
            },
            "ml_summary": ml_summary,
            "message": message,
        }

    def _try_dijkstra_solver(
        self,
        *,
        enriched: List[Dict[str, Any]],
        vehicle: Dict[str, Any],
        strategy: str,
        route_distance_km: float,
        route_duration_min: float,
        total_energy_kwh: float,
        ml_summary: Dict[str, Any],
        initial_soc: float,
        avg_consumption_kwh_per_km: float,
        usable_battery_kwh: float,
        reserve_soc: float,
        target_arrival_soc: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Dijkstra solver ile multi-stop zincir kurmayi dener.
        Basarili olursa build_plan output formatinda dict dondurur; aksi None.
        """
        from app.core.multi_stop_solver import MultiStopDijkstraSolver

        # strateji bazli max_target_soc + arrival_floor secimleri planner'in
        # mevcut mantigini takip eder.
        if strategy == "fast":
            max_target_soc = 85.0
            arrival_bonus = 0.0
        elif strategy == "efficient":
            max_target_soc = 75.0
            arrival_bonus = 0.0
        else:
            max_target_soc = 80.0
            arrival_bonus = 10.0

        effective_arrival_floor = max(
            reserve_soc,
            float(target_arrival_soc) if target_arrival_soc is not None else 0.0,
        ) + arrival_bonus

        avg_speed_kmh = (
            (route_distance_km / route_duration_min) * 60.0
            if route_duration_min > 0
            else 80.0
        )

        def charge_minutes_fn(station_kw: float, start_soc: float, target_soc: float) -> float:
            return self.curve_service.compute_charge_minutes(
                vehicle=vehicle,
                station_kw=station_kw,
                start_soc_pct=start_soc,
                target_soc_pct=target_soc,
                usable_battery_kwh=usable_battery_kwh,
            )

        solver = MultiStopDijkstraSolver(
            soc_bucket_pct=10,
            max_target_soc_pct=max_target_soc,
            avg_speed_kmh=avg_speed_kmh,
        )

        solution = solver.solve(
            stations=enriched,
            route_distance_km=route_distance_km,
            usable_battery_kwh=usable_battery_kwh,
            avg_consumption_kwh_per_km=avg_consumption_kwh_per_km,
            initial_soc_pct=initial_soc,
            reserve_soc_pct=reserve_soc,
            arrival_soc_floor_pct=effective_arrival_floor,
            charge_minutes_fn=charge_minutes_fn,
        )
        if solution is None or not solution.chain:
            return None

        # Solver chain'ini planner output formatina dönüştür.
        stops_payload: List[Dict[str, Any]] = []
        current_soc = initial_soc
        current_distance = 0.0
        for stop in solution.chain:
            # Solver target_soc_percent ve charge_minutes ekledi.
            target_soc = float(stop.get("target_soc_percent", current_soc))
            charge_min = float(stop.get("charge_minutes", 0.0))
            distance_along = float(stop.get("distance_along_route_km", 0.0))
            leg_km = max(0.0, distance_along - current_distance)
            soc_at_arrival = current_soc - (leg_km * avg_consumption_kwh_per_km / usable_battery_kwh) * 100.0

            detour_km = float(stop.get("detour_distance_km", 0.0))
            detour_min = (detour_km / 40.0) * 60.0 if detour_km > 0 else 0.0

            stops_payload.append({
                **stop,
                "soc_at_arrival_percent": round(soc_at_arrival, 2),
                "target_soc_percent": round(target_soc, 1),
                "charge_minutes": round(charge_min, 1),
                "detour_distance_km": round(detour_km, 2),
                "detour_minutes": round(detour_min, 1),
                "total_stop_minutes": round(charge_min + detour_min, 1),
            })
            current_soc = target_soc
            current_distance = distance_along

        remaining_after_last = max(route_distance_km - current_distance, 0.0)
        final_soc_drop_pct = (
            (remaining_after_last * avg_consumption_kwh_per_km) / usable_battery_kwh
        ) * 100.0
        projected_arrival_soc = current_soc - final_soc_drop_pct
        feasible = projected_arrival_soc >= effective_arrival_floor

        total_charge_minutes = sum(s["charge_minutes"] for s in stops_payload)
        total_detour_minutes = sum(s["detour_minutes"] for s in stops_payload)
        total_detour_km = sum(s["detour_distance_km"] for s in stops_payload)
        total_trip_minutes = route_duration_min + total_detour_minutes + total_charge_minutes
        total_trip_energy_kwh = total_energy_kwh + total_detour_km * avg_consumption_kwh_per_km

        message = (
            f"{len(stops_payload)} durakli plan olusturuldu (Dijkstra). "
            f"Tahmini varis SOC: %{projected_arrival_soc:.1f}, "
            f"toplam sure: {total_trip_minutes:.1f} dk."
        )

        return {
            "status": "ok" if feasible else "risky_plan",
            "strategy": strategy,
            "needs_charging": True,
            "feasible": feasible,
            "recommended_stops": stops_payload,
            "summary": {
                "stop_count": len(stops_payload),
                "charge_minutes": round(total_charge_minutes, 1),
                "detour_minutes": round(total_detour_minutes, 1),
                "total_trip_minutes": round(total_trip_minutes, 1),
                "total_energy_kwh": round(total_trip_energy_kwh, 2),
                "projected_arrival_soc_percent": round(projected_arrival_soc, 2),
            },
            "ml_summary": ml_summary,
            "message": message,
            "solver": "dijkstra",
        }

    def _enrich_all_stations(
        self,
        *,
        route_context: Dict[str, Any],
        vehicle: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Ham istasyonlara distance_along_route_km, power_kw vb. ekler."""
        raw_stations = (
            _pick(route_context, "stations", "charging_stations", default=[]) or []
        )
        if not raw_stations:
            return []

        route = _pick(route_context, "route", default={}) or {}
        route_points = self._build_route_points(route)

        vehicle_connectors = (
            _vehicle_connector_set(vehicle) if vehicle is not None else set()
        )

        spatial_index = RouteSpatialIndex(route_points) if route_points else None

        enriched: List[Dict[str, Any]] = []
        for station in raw_stations:
            # HARD filter: operational + connector match (station_enricher).
            if not passes_hard_filters(
                station=station,
                vehicle_connectors=vehicle_connectors,
            ):
                continue

            distance_along, offset = resolve_station_route_metrics(
                station=station,
                route_points=route_points,
                spatial_index=spatial_index,
            )
            if distance_along is None:
                continue

            distance_along = _safe_float(distance_along, 0.0)
            offset = _safe_float(offset, 0.0)

            power_kw = self._station_power_kw(station)
            if power_kw <= 0:
                continue

            name = _pick(station, "name", "title", default=None)
            if name is None:
                addr = _pick(station, "AddressInfo", default={}) or {}
                name = _pick(addr, "Title", default="İstasyon")

            enriched.append(
                {
                    **station,
                    "name": name,
                    "distance_along_route_km": distance_along,
                    "distance_from_route_km": offset,
                    "detour_distance_km": offset * 2.0,
                    "power_kw": power_kw,
                }
            )

        enriched.sort(key=lambda s: s["distance_along_route_km"])
        return enriched

    def _build_route_points(self, route: Dict[str, Any]):
        """Route geometry'den RoutePoint listesi cikarir (geo_utils helper)."""
        from app.core.geo_utils import build_route_points

        raw_points = (
            _pick(route, "geometry", "points", "coordinates", default=[])
            or _pick(route, "polyline_points", default=[])
            or []
        )
        return build_route_points(raw_points)

    def _station_coords(
        self,
        station: Dict[str, Any],
    ) -> tuple:
        """Hem flat hem AddressInfo iceren OCM formatlarindan koordinat cekme."""
        lat = _pick(station, "lat", "latitude", default=None)
        lon = _pick(station, "lon", "lng", "longitude", default=None)
        if lat is None or lon is None:
            addr = _pick(station, "AddressInfo", default={}) or {}
            lat = _pick(addr, "Latitude", default=lat)
            lon = _pick(addr, "Longitude", default=lon)
        if lat is None or lon is None:
            return None, None
        return _safe_float(lat, None), _safe_float(lon, None)

    def _station_power_kw(self, station: Dict[str, Any]) -> float:
        """Flat 'power_kw' yoksa Connections'dan en yukseki alir."""
        power = _safe_float(
            _pick(station, "power_kw", "max_power_kw", "dc_power_kw", default=None),
            0.0,
        )
        if power > 0:
            return power

        for collection_key in ("connections", "Connections"):
            conns = _pick(station, collection_key, default=None) or []
            for conn in conns:
                p = _safe_float(_pick(conn, "power_kw", "PowerKW", default=0.0), 0.0)
                if p > power:
                    power = p
        return power

    def _extract_ml_summary(
        self,
        *,
        simulation_result: Dict[str, Any],
        charge_need: Dict[str, Any],
    ) -> Dict[str, Any]:
        used_ml = bool(
            _pick(
                charge_need,
                "used_ml",
                default=_pick(simulation_result, "used_ml", default=False),
            )
        )

        ml_segment_count = int(
            _safe_float(
                _pick(
                    charge_need,
                    "ml_segment_count",
                    default=_pick(simulation_result, "ml_segment_count", default=0),
                ),
                0,
            )
        )

        heuristic_segment_count = int(
            _safe_float(
                _pick(
                    charge_need,
                    "heuristic_segment_count",
                    default=_pick(
                        simulation_result,
                        "heuristic_segment_count",
                        default=0,
                    ),
                ),
                0,
            )
        )

        model_version = _pick(
            charge_need,
            "model_version",
            default=_pick(simulation_result, "model_version", default=None),
        )

        return {
            "used_ml": used_ml,
            "ml_segment_count": ml_segment_count,
            "heuristic_segment_count": heuristic_segment_count,
            "model_version": model_version,
        }

    def _extract_final_soc(self, simulation_result: Dict[str, Any]) -> float:
        direct_soc = _pick(
            simulation_result,
            "final_soc",
            "end_soc",
            "remaining_soc",
            default=None,
        )
        if direct_soc is not None:
            return _safe_float(direct_soc, 0.0)

        segments = _pick(simulation_result, "segments", "segment_results", default=[]) or []
        if segments:
            last_segment = segments[-1]
            return _safe_float(
                _pick(last_segment, "soc_after", "ending_soc", "end_soc", "remaining_soc"),
                0.0,
            )

        return 0.0

    def _resolve_avg_consumption(
        self,
        *,
        route_distance_km: float,
        total_energy_kwh: float,
        vehicle: Dict[str, Any],
    ) -> float:
        if route_distance_km > 0 and total_energy_kwh > 0:
            return total_energy_kwh / route_distance_km

        ideal_wh_km = _safe_float(_pick(vehicle, "ideal_consumption_wh_km"), 180.0)
        return ideal_wh_km / 1000.0

    def _build_message(
        self,
        *,
        station_name: str,
        feasible: bool,
        projected_arrival_soc_percent: float,
        total_trip_minutes: float,
        used_ml: bool = False,
        model_version: Optional[str] = None,
    ) -> str:
        prediction_note = ""
        if used_ml:
            if model_version:
                prediction_note = f" Tahmin kaynağı: ML ({model_version})."
            else:
                prediction_note = " Tahmin kaynağı: ML."

        if feasible:
            return (
                f"{station_name} ile tek duraklı plan oluşturuldu. "
                f"Tahmini varış SOC: %{projected_arrival_soc_percent:.1f}, "
                f"toplam süre: {total_trip_minutes:.1f} dk."
                f"{prediction_note}"
            )

        return (
            f"{station_name} seçilerek plan oluşturuldu ancak marj düşük görünüyor. "
            f"Tahmini varış SOC: %{projected_arrival_soc_percent:.1f}."
            f"{prediction_note}"
        )


def build_charging_plan(
    *,
    vehicle: Dict[str, Any],
    route_context: Dict[str, Any],
    simulation_result: Dict[str, Any],
    charge_need: Dict[str, Any],
    selector_result: Dict[str, Any],
    strategy: str = "balanced",
) -> Dict[str, Any]:
    planner = ChargingPlanner()
    return planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy=strategy,
    )


if __name__ == "__main__":
    vehicle = {
        "name": "Demo EV",
        "usable_battery_kwh": 60,
        "ideal_consumption_wh_km": 180,
        "max_dc_charge_power_kw": 120,
    }

    route_context = {
        "route": {
            "distance_km": 300,
            "duration_min": 260,
        }
    }

    simulation_result = {
        "initial_soc": 80,
        "total_energy_kwh": 54,
        "used_ml": True,
        "ml_segment_count": 3,
        "heuristic_segment_count": 0,
        "model_version": "lgbm_v1",
        "segments": [
            {"cumulative_distance_km": 100, "soc_after": 60},
            {"cumulative_distance_km": 200, "soc_after": 32},
            {"cumulative_distance_km": 300, "soc_after": 6},
        ],
    }

    charge_need = {
        "needs_charging": True,
        "critical_distance_km": 210,
        "reserve_soc_percent": 10,
        "used_ml": True,
        "ml_segment_count": 3,
        "heuristic_segment_count": 0,
        "model_version": "lgbm_v1",
    }

    selector_result = {
        "needs_charging": True,
        "selected_station": {
            "name": "Yakin Hizli Istasyon",
            "distance_along_route_km": 150,
            "remaining_distance_km": 150,
            "detour_distance_km": 3.0,
            "detour_minutes": 4.5,
            "soc_at_arrival_percent": 46.0,
            "target_soc_percent": 62.0,
            "charge_minutes": 11.0,
            "power_kw": 120,
        },
    }

    planner = ChargingPlanner()
    result = planner.build_plan(
        vehicle=vehicle,
        route_context=route_context,
        simulation_result=simulation_result,
        charge_need=charge_need,
        selector_result=selector_result,
        strategy="balanced",
    )

    print(result)