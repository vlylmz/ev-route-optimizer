"""
FastAPI katmanı için uçtan uca testler.

Dış servisler (OSRM, OpenElevation, OpenMeteo, OCM) doğrudan çağrılmaz:
lifespan'da kurulu servisler dependency_overrides ile sahtelenir.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient

from app.api import dependencies as deps
from app.api.main import create_app
from app.core.charge_need_analyzer import ChargeNeedAnalysis
from app.core.route_energy_simulator import (
    RouteEnergySegmentResult,
    RouteEnergySimulationResult,
)


# ---------------------------------------------------------
# Fake servisler
# ---------------------------------------------------------


class FakeRouteContextService:
    def build_route_context(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return {
            "route": {
                "distance_km": 120.0,
                "duration_min": 100.0,
                "geometry": [
                    [start[0], start[1]],
                    [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2],
                    [end[0], end[1]],
                ],
            },
            "elevation": {
                "elevation_profile": [
                    {"lat": start[0], "lon": start[1], "elevation_m": 100.0,
                     "cumulative_distance_km": 0.0},
                    {"lat": end[0], "lon": end[1], "elevation_m": 110.0,
                     "cumulative_distance_km": 120.0},
                ],
                "slope_segments": [
                    {
                        "segment_no": 1,
                        "distance_km": 60.0,
                        "avg_speed_kmh": 90.0,
                        "grade_pct": 1.0,
                        "start": [start[0], start[1]],
                        "end": [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2],
                    },
                    {
                        "segment_no": 2,
                        "distance_km": 60.0,
                        "avg_speed_kmh": 90.0,
                        "grade_pct": -0.5,
                        "start": [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2],
                        "end": [end[0], end[1]],
                    },
                ],
            },
            "weather": {
                "avg_temp_c": 20.0,
                "min_temp_c": 18.0,
                "max_temp_c": 22.0,
                "samples": [],
            },
            "stations": [
                {
                    "ocm_id": 1,
                    "name": "Test Istasyon 1",
                    "address": "Test Adres",
                    "latitude": (start[0] + end[0]) / 2,
                    "longitude": (start[1] + end[1]) / 2,
                    "distance_along_route_km": 60.0,
                    "distance_from_route_km": 0.5,
                    "power_kw": 150,
                    "is_operational": True,
                    "connections": [],
                }
            ],
            "summary": {
                "distance_km": 120.0,
                "duration_min": 100.0,
                "geometry_point_count": 3,
                "sampled_point_count": 2,
                "weather_point_count": 2,
                "station_count": 1,
                "avg_temp_c": 20.0,
                "min_temp_c": 18.0,
                "max_temp_c": 22.0,
                "avg_grade_pct": 0.25,
                "max_uphill_grade_pct": 1.0,
                "max_downhill_grade_pct": -0.5,
            },
        }


class FakeChargingService:
    def get_nearby_stations_dict(
        self,
        coord: Tuple[float, float],
        distance_km: float = 10.0,
        max_results: int = 20,
        allow_fallback: bool = True,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "ocm_id": 42,
                "name": "Fake DC Istasyonu",
                "operator": "Test Operator",
                "address": "Fake Cad. No:1",
                "town": "TestCity",
                "latitude": coord[0] + 0.01,
                "longitude": coord[1] + 0.01,
                "distance_km": 0.7,
                "number_of_points": 4,
                "is_operational": True,
                "connections": [
                    {
                        "connection_type": "CCS",
                        "power_kw": 150.0,
                        "current_type": "DC",
                        "quantity": 2,
                        "is_fast_charge_capable": True,
                        "status": "Operational",
                    }
                ],
            }
        ]


class FakeSimulator:
    """Deterministic simulator that always yields feasible trip."""

    def simulate(self, vehicle, route_context, start_soc_pct, use_ml=None, strategy="balanced"):
        seg1 = RouteEnergySegmentResult(
            segment_no=1,
            distance_km=60.0,
            speed_kmh=90.0,
            grade_pct=1.0,
            temp_c=20.0,
            start_soc_pct=start_soc_pct,
            end_soc_pct=max(0.0, start_soc_pct - 15.0),
            energy_used_kwh=9.0,
            consumption_wh_km=150.0,
            below_reserve=False,
            segment_start=(40.0, 30.0),
            segment_end=(40.5, 30.5),
            prediction_source="formula",
            used_ml=False,
            model_version=None,
        )
        seg2 = RouteEnergySegmentResult(
            segment_no=2,
            distance_km=60.0,
            speed_kmh=90.0,
            grade_pct=-0.5,
            temp_c=20.0,
            start_soc_pct=seg1.end_soc_pct,
            end_soc_pct=max(0.0, seg1.end_soc_pct - 12.0),
            energy_used_kwh=7.0,
            consumption_wh_km=116.0,
            below_reserve=False,
            segment_start=(40.5, 30.5),
            segment_end=(41.0, 31.0),
            prediction_source="formula",
            used_ml=False,
            model_version=None,
        )
        return RouteEnergySimulationResult(
            vehicle_id=vehicle.id,
            vehicle_name=vehicle.full_name,
            total_distance_km=120.0,
            total_energy_kwh=16.0,
            average_consumption_wh_km=133.0,
            start_soc_pct=start_soc_pct,
            end_soc_pct=seg2.end_soc_pct,
            below_reserve=False,
            segment_count=2,
            segments=[seg1, seg2],
            used_ml=False,
            ml_segment_count=0,
            heuristic_segment_count=2,
            model_version=None,
        )


class FakeAnalyzer:
    def analyze(self, simulation, usable_battery_kwh, reserve_soc_pct):
        return ChargeNeedAnalysis(
            route_completed=True,
            charging_required=False,
            reserve_soc_pct=reserve_soc_pct,
            start_soc_pct=simulation.start_soc_pct,
            end_soc_pct=simulation.end_soc_pct,
            minimum_soc_pct=min(seg.end_soc_pct for seg in simulation.segments),
            critical_segment_no=None,
            critical_segment_start_soc_pct=None,
            critical_segment_end_soc_pct=None,
            estimated_additional_soc_needed_pct=0.0,
            estimated_additional_energy_needed_kwh=0.0,
            recommendation="Şarj gerekmiyor.",
            used_ml=False,
            ml_segment_count=0,
            heuristic_segment_count=2,
            model_version=None,
        )


class FakeProfiles:
    def generate_profiles(
        self,
        *,
        vehicle,
        route_context,
        simulation_result,
        charge_need,
        strategies=None,
        simulator=None,
        analyzer=None,
        vehicle_obj=None,
        initial_soc=None,
    ):
        strategy_list = list(strategies or ["fast", "efficient", "balanced"])
        profiles = {}
        cards = []
        for key in strategy_list:
            summary = {
                "total_trip_minutes": 100.0,
                "charge_minutes": 0.0,
                "total_energy_kwh": 16.0,
                "stop_count": 0,
                "projected_arrival_soc_percent": simulation_result.get("end_soc_pct", 50.0),
            }
            ml_summary = {
                "used_ml": False,
                "ml_segment_count": 0,
                "heuristic_segment_count": 2,
                "model_version": None,
            }
            profiles[key] = {
                "key": key,
                "label": key.title(),
                "status": "ok",
                "feasible": True,
                "summary": summary,
                "ml_summary": ml_summary,
            }
            cards.append(
                {
                    "key": key,
                    "label": key.title(),
                    "status": "ok",
                    "feasible": True,
                    "arrival_soc_percent": summary["projected_arrival_soc_percent"],
                    "total_trip_minutes": summary["total_trip_minutes"],
                    "charge_minutes": summary["charge_minutes"],
                    "total_energy_kwh": summary["total_energy_kwh"],
                    "stop_count": summary["stop_count"],
                    "used_ml": False,
                    "ml_segment_count": 0,
                    "heuristic_segment_count": 2,
                    "model_version": None,
                }
            )
        return {
            "status": "ok",
            "profiles": profiles,
            "profile_cards": cards,
            "best_by_time": strategy_list[0] if strategy_list else None,
            "best_by_energy": strategy_list[0] if strategy_list else None,
            "recommended_profile": "balanced" if "balanced" in strategy_list else strategy_list[0],
            "profiles_using_ml": [],
            "any_profile_used_ml": False,
            "message": "Test profilleri üretildi.",
        }


# ---------------------------------------------------------
# Fixtures
# ---------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()

    fake_ctx = FakeRouteContextService()
    fake_charging = FakeChargingService()
    fake_sim = FakeSimulator()
    fake_analyzer = FakeAnalyzer()
    fake_profiles = FakeProfiles()

    app.dependency_overrides[deps.get_route_context_service] = lambda: fake_ctx
    app.dependency_overrides[deps.get_charging_service] = lambda: fake_charging
    app.dependency_overrides[deps.get_route_energy_simulator] = lambda: fake_sim
    app.dependency_overrides[deps.get_charge_need_analyzer] = lambda: fake_analyzer
    app.dependency_overrides[deps.get_route_profiles] = lambda: fake_profiles

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------
# Testler
# ---------------------------------------------------------


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "ev-route-optimizer"
    assert body["vehicle_count"] > 0
    assert "model_available" in body


def test_list_vehicles(client: TestClient) -> None:
    r = client.get("/vehicles")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) > 0
    v0 = data[0]
    for required in ("id", "name", "make", "model", "usable_battery_kwh"):
        assert required in v0


def test_get_vehicle_detail(client: TestClient) -> None:
    r_all = client.get("/vehicles")
    vid = r_all.json()[0]["id"]

    r = client.get(f"/vehicles/{vid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == vid
    assert "drivetrain" in body
    assert "battery_chemistry" in body


def test_get_vehicle_not_found(client: TestClient) -> None:
    r = client.get("/vehicles/this_vehicle_does_not_exist")
    assert r.status_code == 404


def test_stations_endpoint(client: TestClient) -> None:
    r = client.get(
        "/stations",
        params={"lat": 40.0, "lon": 30.0, "distance_km": 5.0, "max_results": 10},
    )
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["ocm_id"] == 42
    assert data[0]["connections"][0]["power_kw"] == 150.0


def test_route_endpoint(client: TestClient) -> None:
    payload = {
        "start": {"lat": 39.92, "lon": 32.85},
        "end": {"lat": 41.01, "lon": 28.97},
    }
    r = client.post("/route", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["distance_km"] == 120.0
    assert body["summary"]["station_count"] == 1
    assert len(body["geometry"]) >= 2


def test_estimate_consumption_fallback(client: TestClient) -> None:
    r_all = client.get("/vehicles")
    vid = r_all.json()[0]["id"]

    payload = {
        "vehicle_id": vid,
        "segment": {
            "segment_length_km": 80.0,
            "avg_speed_kmh": 95.0,
            "elevation_gain_m": 50.0,
            "elevation_loss_m": 40.0,
            "temperature_c": 18.0,
            "soc_start_percent": 80.0,
        },
        "weather": {"temperature_c": 18.0},
    }
    r = client.post("/estimate-consumption", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["vehicle_id"] == vid
    assert body["fallback_energy_kwh"] > 0
    assert body["source"].startswith("heuristic") or body["source"] == "ml"


def test_estimate_consumption_vehicle_not_found(client: TestClient) -> None:
    payload = {
        "vehicle_id": "no_such_vehicle",
        "segment": {
            "segment_length_km": 10.0,
            "avg_speed_kmh": 50.0,
        },
    }
    r = client.post("/estimate-consumption", json=payload)
    assert r.status_code == 404


def test_optimize_endpoint(client: TestClient) -> None:
    r_all = client.get("/vehicles")
    vid = r_all.json()[0]["id"]

    payload = {
        "vehicle_id": vid,
        "start": {"lat": 39.92, "lon": 32.85},
        "end": {"lat": 41.01, "lon": 28.97},
        "initial_soc_pct": 80.0,
        "strategies": ["fast", "efficient", "balanced"],
        "use_ml": False,
    }
    r = client.post("/optimize", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["vehicle_id"] == vid
    assert body["total_distance_km"] == 120.0
    assert body["recommended_profile"] == "balanced"
    assert len(body["profiles"]) == 3
    for card in body["profiles"]:
        assert card["key"] in ("fast", "efficient", "balanced")
        assert card["feasible"] is True


def test_optimize_rejects_empty_strategies(client: TestClient) -> None:
    payload = {
        "vehicle_id": "tesla_model_y_rwd",
        "start": {"lat": 39.92, "lon": 32.85},
        "end": {"lat": 41.01, "lon": 28.97},
        "initial_soc_pct": 80.0,
        "strategies": [],
    }
    r = client.post("/optimize", json=payload)
    assert r.status_code == 422


def test_openapi_docs(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    paths = spec.get("paths", {})
    for p in ("/health", "/vehicles", "/route", "/stations", "/optimize", "/estimate-consumption"):
        assert p in paths, f"Missing path in OpenAPI: {p}"
