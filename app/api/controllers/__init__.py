from app.api.controllers.estimate_controller import router as estimate_router
from app.api.controllers.optimize_controller import router as optimize_router
from app.api.controllers.route_controller import router as route_router
from app.api.controllers.speed_limit_controller import router as speed_limit_router
from app.api.controllers.station_controller import router as station_router
from app.api.controllers.vehicle_controller import router as vehicle_router

__all__ = [
    "estimate_router",
    "optimize_router",
    "route_router",
    "speed_limit_router",
    "station_router",
    "vehicle_router",
]
