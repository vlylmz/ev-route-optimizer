"""
Pydantic v2 request/response şemaları.

Tek dosyada tüm API modelleri; endpoint'ler arası paylaşımı kolaylaştırır.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =========================================================
# Ortak
# =========================================================


class Coordinate(BaseModel):
    """Enlem/boylam çifti."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90.0, le=90.0, description="Enlem (-90, 90)")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Boylam (-180, 180)")

    def as_tuple(self) -> tuple[float, float]:
        return (self.lat, self.lon)


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "ev-route-optimizer"
    version: str
    model_available: bool
    model_version: Optional[str] = None
    vehicle_count: int


# =========================================================
# Araçlar
# =========================================================


class VehicleSummary(BaseModel):
    id: str
    name: str
    make: str
    model: str
    variant: str
    year: int
    body_type: str
    usable_battery_kwh: float
    ideal_consumption_wh_km: float
    wltp_range_km: float
    max_dc_charge_kw: float


class VehicleDetail(VehicleSummary):
    drivetrain: str
    battery_chemistry: str
    gross_battery_kwh: float
    soc_min_pct: float
    soc_max_pct: float
    regen_efficiency: float
    weight_kg: float
    max_ac_charge_kw: float
    temp_penalty_factor: float
    charge_curve_hint: str
    default_hvac_load_kw: float


# =========================================================
# /route
# =========================================================


class RouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: Coordinate
    end: Coordinate
    elevation_min_spacing_km: float = Field(5.0, gt=0)
    elevation_max_points: int = Field(60, gt=0, le=500)
    weather_sample_limit: int = Field(5, gt=0, le=50)
    station_query_every_n_points: int = Field(4, gt=0)
    station_distance_km: float = Field(5.0, gt=0)
    station_max_results_per_query: int = Field(10, gt=0, le=100)
    allow_station_fallback: bool = True


class RouteSummary(BaseModel):
    distance_km: float
    duration_min: float
    geometry_point_count: int
    sampled_point_count: int
    weather_point_count: int
    station_count: int
    avg_temp_c: Optional[float] = None
    min_temp_c: Optional[float] = None
    max_temp_c: Optional[float] = None
    avg_grade_pct: Optional[float] = None
    max_uphill_grade_pct: Optional[float] = None
    max_downhill_grade_pct: Optional[float] = None


class RouteResponse(BaseModel):
    summary: RouteSummary
    geometry: List[List[float]] = Field(
        default_factory=list,
        description="Rota koordinatları [[lat,lon], ...]",
    )
    elevation_profile: List[Dict[str, Any]] = Field(default_factory=list)
    slope_segments: List[Dict[str, Any]] = Field(default_factory=list)
    weather: Dict[str, Any] = Field(default_factory=dict)
    stations: List[Dict[str, Any]] = Field(default_factory=list)


# =========================================================
# /stations
# =========================================================


class StationConnection(BaseModel):
    connection_type: Optional[str] = None
    power_kw: Optional[float] = None
    current_type: Optional[str] = None
    quantity: Optional[int] = None
    is_fast_charge_capable: Optional[bool] = None
    status: Optional[str] = None


class StationSummary(BaseModel):
    ocm_id: int
    name: str
    operator: Optional[str] = None
    address: str
    town: Optional[str] = None
    latitude: float
    longitude: float
    distance_km: Optional[float] = None
    number_of_points: Optional[int] = None
    is_operational: Optional[bool] = None
    connections: List[StationConnection] = Field(default_factory=list)


# =========================================================
# /estimate-consumption
# =========================================================


class SegmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_length_km: float = Field(..., gt=0)
    avg_speed_kmh: float = Field(..., gt=0, le=300)
    elevation_gain_m: float = Field(0.0, ge=0)
    elevation_loss_m: float = Field(0.0, ge=0)
    temperature_c: Optional[float] = Field(None, ge=-50, le=60)
    soc_start_percent: float = Field(80.0, ge=0, le=100)
    soc_end_percent: Optional[float] = Field(None, ge=0, le=100)


class WeatherInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature_c: Optional[float] = None


class EstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    segment: SegmentInput
    weather: Optional[WeatherInput] = None


class EstimateResponse(BaseModel):
    vehicle_id: str
    source: str = Field(..., description="ml | heuristic_* | fallback")
    used_model: bool
    predicted_energy_kwh: float
    fallback_energy_kwh: float
    model_version: Optional[str] = None
    features: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


# =========================================================
# /optimize
# =========================================================


StrategyName = Literal["fast", "efficient", "balanced"]


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    start: Coordinate
    end: Coordinate
    initial_soc_pct: float = Field(..., ge=0.0, le=100.0)
    strategies: List[StrategyName] = Field(
        default_factory=lambda: ["fast", "efficient", "balanced"]
    )
    use_ml: bool = False

    # /route parametreleri — opsiyonel override
    elevation_min_spacing_km: float = Field(5.0, gt=0)
    elevation_max_points: int = Field(60, gt=0, le=500)
    station_distance_km: float = Field(5.0, gt=0)

    @field_validator("strategies")
    @classmethod
    def _strategies_non_empty_unique(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("En az 1 strateji seçilmeli.")
        deduped: List[str] = []
        for strat in v:
            if strat not in deduped:
                deduped.append(strat)
        return deduped


class ProfileCard(BaseModel):
    key: StrategyName
    label: str
    feasible: bool
    total_energy_kwh: Optional[float] = None
    total_trip_minutes: Optional[float] = None
    charging_minutes: Optional[float] = None
    stop_count: Optional[int] = None
    final_soc_pct: Optional[float] = None
    used_ml: bool = False
    model_version: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class OptimizeResponse(BaseModel):
    status: str
    vehicle_id: str
    vehicle_name: str
    initial_soc_pct: float
    final_soc_pct: float
    total_distance_km: float
    total_energy_kwh: float
    used_ml: bool
    ml_segment_count: int = 0
    heuristic_segment_count: int = 0
    model_version: Optional[str] = None
    recommended_profile: Optional[StrategyName] = None
    profiles: List[ProfileCard] = Field(default_factory=list)
    raw_optimization: Dict[str, Any] = Field(default_factory=dict)


# =========================================================
# /speed-limits
# =========================================================


class SpeedLimitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry: List[List[float]] = Field(
        ...,
        description="Rota koordinat listesi [[lat, lon], ...]",
        min_length=2,
    )
    sample_every_n_points: int = Field(
        20,
        gt=0,
        le=200,
        description="Hız sınırı sorgusu için her N noktada bir örnekle.",
    )


class SpeedLimitSegment(BaseModel):
    start_index: int
    end_index: int
    maxspeed_kmh: Optional[float] = None
    highway: Optional[str] = None


class SpeedLimitsResponse(BaseModel):
    segments: List[SpeedLimitSegment] = Field(default_factory=list)
    source: str = Field(default="overpass", description="overpass | fallback")
    sampled_point_count: int = 0
