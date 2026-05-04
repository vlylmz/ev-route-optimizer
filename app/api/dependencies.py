"""
FastAPI dependency'leri — lifespan'da oluşturulan servisleri
request başına enjekte eder.
"""

from __future__ import annotations

from typing import Dict

from fastapi import Request

from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.charging_planner import ChargingPlanner
from app.core.charging_stop_selector import ChargingStopSelector
from app.core.energy_model import Vehicle
from app.core.route_energy_simulator import RouteEnergySimulator
from app.core.route_profiles import RouteProfiles
from app.services.charging_service import OpenChargeMapService
from app.services.geocoding_service import NominatimGeocodingService
from app.services.route_context_service import RouteContextService
from app.services.speed_limit_service import OverpassSpeedLimitService
from ml.model_service import ModelService


def get_vehicles_lookup(request: Request) -> Dict[str, Vehicle]:
    return request.app.state.vehicles


def get_model_service(request: Request) -> ModelService:
    return request.app.state.model_service


def get_route_context_service(request: Request) -> RouteContextService:
    return request.app.state.route_context_service


def get_route_energy_simulator(request: Request) -> RouteEnergySimulator:
    return request.app.state.route_energy_simulator


def get_charge_need_analyzer(request: Request) -> ChargeNeedAnalyzer:
    return request.app.state.charge_need_analyzer


def get_charging_stop_selector(request: Request) -> ChargingStopSelector:
    return request.app.state.charging_stop_selector


def get_charging_planner(request: Request) -> ChargingPlanner:
    return request.app.state.charging_planner


def get_route_profiles(request: Request) -> RouteProfiles:
    return request.app.state.route_profiles


def get_charging_service(request: Request) -> OpenChargeMapService:
    return request.app.state.charging_service


def get_speed_limit_service(request: Request) -> OverpassSpeedLimitService:
    return request.app.state.speed_limit_service


def get_geocoding_service(request: Request) -> NominatimGeocodingService:
    return request.app.state.geocoding_service
