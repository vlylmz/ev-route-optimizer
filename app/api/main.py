"""
FastAPI uygulaması — Faz 5 MVC katmanı.

Tüm ağır servis örnekleri lifespan içinde bir kere kurulur ve
`request.app.state` üzerinden controller'lara enjekte edilir.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.controllers import (
    estimate_router,
    optimize_router,
    route_router,
    speed_limit_router,
    station_router,
    vehicle_router,
)
from app.api.schemas import HealthResponse
from app.core.charge_need_analyzer import ChargeNeedAnalyzer
from app.core.charging_planner import ChargingPlanner
from app.core.charging_stop_selector import ChargingStopSelector
from app.core.energy_model import Vehicle, load_vehicles
from app.core.route_energy_simulator import RouteEnergySimulator
from app.core.route_profiles import RouteProfiles
from app.services.charging_service import OpenChargeMapService
from app.services.route_context_service import RouteContextService
from app.services.speed_limit_service import OverpassSpeedLimitService
from ml.model_service import ModelService


APP_VERSION = "0.5.0"

DEFAULT_VEHICLES_PATH = Path("app/data/vehicles.json")
DEFAULT_MODEL_PATH = Path("ml/models/lgbm_v1.joblib")


def _resolve_path(env_key: str, default: Path) -> Path:
    raw = os.getenv(env_key)
    return Path(raw) if raw else default


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    vehicles_path = _resolve_path("EV_VEHICLES_PATH", DEFAULT_VEHICLES_PATH)
    model_path = _resolve_path("EV_MODEL_PATH", DEFAULT_MODEL_PATH)
    ocm_api_key = os.getenv("OCM_API_KEY", "")

    # Araç veritabanı
    vehicles_list = load_vehicles(vehicles_path)
    vehicles: Dict[str, Vehicle] = {v.id: v for v in vehicles_list}

    # ML servisi — model yoksa heuristic fallback (lazy load)
    model_service = ModelService(model_path=model_path, enabled=True)

    # Dış servisler
    charging_service = OpenChargeMapService(api_key=ocm_api_key) if ocm_api_key else OpenChargeMapService()
    route_context_service = RouteContextService(charging_service=charging_service)
    speed_limit_service = OverpassSpeedLimitService()

    # Core planlama bileşenleri
    route_energy_simulator = RouteEnergySimulator(model_service=model_service)
    charge_need_analyzer = ChargeNeedAnalyzer()
    charging_stop_selector = ChargingStopSelector()
    charging_planner = ChargingPlanner()
    route_profiles = RouteProfiles(
        charging_stop_selector=charging_stop_selector,
        charging_planner=charging_planner,
    )

    # app.state'e yerleştir
    app.state.vehicles = vehicles
    app.state.model_service = model_service
    app.state.charging_service = charging_service
    app.state.route_context_service = route_context_service
    app.state.route_energy_simulator = route_energy_simulator
    app.state.charge_need_analyzer = charge_need_analyzer
    app.state.charging_stop_selector = charging_stop_selector
    app.state.charging_planner = charging_planner
    app.state.route_profiles = route_profiles
    app.state.speed_limit_service = speed_limit_service

    try:
        yield
    finally:
        # Gerekirse dış bağlantıları burada kapatırız.
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="EV Route Optimizer",
        version=APP_VERSION,
        description=(
            "EV için enerji tüketimi, şarj ihtiyacı ve çok profilli "
            "rota planlaması — FastAPI MVC."
        ),
        lifespan=lifespan,
    )

    # CORS — frontend dev sunucusu için (Vite: 5173, CRA: 3000)
    cors_origins_env = os.getenv("EV_CORS_ORIGINS", "")
    default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()] or default_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        model_service: ModelService = app.state.model_service
        model_available = bool(model_service.is_available())
        model_version = None
        try:
            metadata = model_service.get_metadata()
            model_version = metadata.get("model_version") if isinstance(metadata, dict) else None
        except Exception:  # noqa: BLE001
            model_version = None

        return HealthResponse(
            service="ev-route-optimizer",
            version=APP_VERSION,
            model_available=model_available,
            model_version=model_version,
            vehicle_count=len(app.state.vehicles),
        )

    app.include_router(vehicle_router)
    app.include_router(route_router)
    app.include_router(station_router)
    app.include_router(estimate_router)
    app.include_router(optimize_router)
    app.include_router(speed_limit_router)

    return app


app = create_app()
