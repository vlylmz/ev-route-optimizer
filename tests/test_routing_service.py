from app.services.routing_service import OSRMRoutingService


def test_route_service_returns_basic_route():
    service = OSRMRoutingService()

    start = (39.9208, 32.8541)   # Ankara
    end = (39.7767, 30.5206)     # Eskişehir

    route = service.get_route_dict(start, end)

    assert route["distance_km"] > 0
    assert route["duration_min"] > 0
    assert route["geometry_point_count"] > 0
    assert len(route["waypoints"]) == 2