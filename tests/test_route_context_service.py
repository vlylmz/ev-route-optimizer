from app.services.route_context_service import RouteContextService


def test_build_route_context_with_mocked_services():
    class DummyRoutingService:
        def get_route_dict(self, start, end):
            return {
                "distance_m": 100000.0,
                "distance_km": 100.0,
                "duration_s": 5400.0,
                "duration_min": 90.0,
                "geometry": [
                    (39.9208, 32.8541),
                    (39.8500, 31.9000),
                    (39.7767, 30.5206),
                ],
                "geometry_point_count": 3,
                "waypoints": [
                    {"name": "start", "location": (39.9208, 32.8541), "snapped_distance_m": 5.0},
                    {"name": "end", "location": (39.7767, 30.5206), "snapped_distance_m": 5.0},
                ],
            }

    class DummyElevationService:
        def get_elevation_and_slope(self, geometry, min_spacing_km=5.0, max_points=60):
            return {
                "sampled_point_count": 3,
                "sampled_geometry": geometry,
                "elevation_profile": [
                    {"lat": 39.9208, "lon": 32.8541, "elevation_m": 900, "cumulative_distance_km": 0.0},
                    {"lat": 39.8500, "lon": 31.9000, "elevation_m": 950, "cumulative_distance_km": 50.0},
                    {"lat": 39.7767, "lon": 30.5206, "elevation_m": 870, "cumulative_distance_km": 100.0},
                ],
                "slope_segments": [
                    {
                        "start": (39.9208, 32.8541),
                        "end": (39.8500, 31.9000),
                        "distance_km": 50.0,
                        "elevation_start_m": 900,
                        "elevation_end_m": 950,
                        "elevation_delta_m": 50,
                        "grade_pct": 0.1,
                    },
                    {
                        "start": (39.8500, 31.9000),
                        "end": (39.7767, 30.5206),
                        "distance_km": 50.0,
                        "elevation_start_m": 950,
                        "elevation_end_m": 870,
                        "elevation_delta_m": -80,
                        "grade_pct": -0.16,
                    },
                ],
            }

    class DummyWeatherService:
        def summarize_route_temperature(self, coords):
            return {
                "point_count": len(coords),
                "min_temp_c": 7.0,
                "max_temp_c": 10.0,
                "avg_temp_c": 8.5,
                "points": [{"temperature_c": 8.5}],
            }

    class DummyChargingService:
        def find_stations_along_route(
            self,
            sampled_geometry,
            query_every_n_points=4,
            distance_km=5.0,
            max_results_per_query=10,
            allow_fallback=True,
        ):
            class DummyStation:
                def __init__(self, ocm_id, name):
                    self.ocm_id = ocm_id
                    self.uuid = None
                    self.name = name
                    self.operator = "Test Operator"
                    self.usage_type = "Public"
                    self.usage_cost = None
                    self.address = "Test Address"
                    self.town = "Test Town"
                    self.latitude = 39.90
                    self.longitude = 32.80
                    self.distance_km = 1.2
                    self.number_of_points = 2
                    self.status = "Operational"
                    self.is_operational = True
                    self.connections = []

            return [
                DummyStation(1001, "Station A"),
                DummyStation(1002, "Station B"),
            ]

        def station_to_dict(self, station):
            return {
                "ocm_id": station.ocm_id,
                "name": station.name,
                "operator": station.operator,
                "distance_km": station.distance_km,
                "is_operational": station.is_operational,
                "connections": [],
            }

    service = RouteContextService(
        routing_service=DummyRoutingService(),
        elevation_service=DummyElevationService(),
        weather_service=DummyWeatherService(),
        charging_service=DummyChargingService(),
    )

    context = service.build_route_context(
        start=(39.9208, 32.8541),
        end=(39.7767, 30.5206),
    )

    assert context["summary"]["distance_km"] == 100.0
    assert context["summary"]["duration_min"] == 90.0
    assert context["summary"]["station_count"] == 2
    assert context["summary"]["avg_temp_c"] == 8.5
    assert context["summary"]["max_uphill_grade_pct"] == 0.1
    assert context["summary"]["max_downhill_grade_pct"] == -0.16
    assert len(context["stations"]) == 2


def test_route_context_cache_hit_skips_ocm_call():
    """Ayni rota icin ikinci build_route_context: rota cagrilir, OCM atlanir."""

    class DummyRoutingService:
        def __init__(self):
            self.call_count = 0

        def get_route_dict(self, start, end):
            self.call_count += 1
            return {
                "distance_km": 100.0,
                "duration_min": 90.0,
                "geometry": [(39.92, 32.85), (39.78, 30.52)],
                "geometry_point_count": 2,
                "waypoints": [],
            }

    class DummyElevationService:
        def get_elevation_and_slope(self, geometry, min_spacing_km=5.0, max_points=60):
            return {
                "sampled_point_count": 2,
                "sampled_geometry": geometry,
                "elevation_profile": [],
                "slope_segments": [
                    {"start": geometry[0], "end": geometry[1], "distance_km": 100.0,
                     "elevation_start_m": 0, "elevation_end_m": 0, "elevation_delta_m": 0,
                     "grade_pct": 0},
                ],
            }

    class DummyWeatherService:
        def summarize_route_temperature(self, coords):
            return {"point_count": len(coords), "min_temp_c": 10, "max_temp_c": 15,
                    "avg_temp_c": 12.5, "points": []}

    class CountingChargingService:
        def __init__(self):
            self.call_count = 0

        def find_stations_along_route(self, **kwargs):
            self.call_count += 1
            return []

        def station_to_dict(self, station):
            return {}

    routing = DummyRoutingService()
    charging = CountingChargingService()
    service = RouteContextService(
        routing_service=routing,
        elevation_service=DummyElevationService(),
        weather_service=DummyWeatherService(),
        charging_service=charging,
    )

    coords = ((39.9208, 32.8541), (39.7767, 30.5206))

    service.build_route_context(start=coords[0], end=coords[1])
    service.build_route_context(start=coords[0], end=coords[1])

    # Rota her seferinde cagrilir; OCM ikinci sefer cache'den okunur.
    assert routing.call_count == 2
    assert charging.call_count == 1