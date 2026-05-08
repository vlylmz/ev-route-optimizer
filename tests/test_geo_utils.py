from app.core.geo_utils import (
    bearing_deg,
    build_route_points,
    haversine_km,
    parse_geometry,
)


def test_haversine_km_known_distance_ankara_istanbul():
    """Ankara (39.92, 32.85) -> Istanbul (41.01, 28.97) ~351 km."""
    distance = haversine_km(39.9208, 32.8541, 41.0082, 28.9784)
    assert 345 < distance < 360


def test_haversine_km_zero_for_same_point():
    assert haversine_km(40.0, 30.0, 40.0, 30.0) == 0.0


def test_bearing_deg_north_returns_zero():
    """Tam kuzeye gidis -> bearing 0."""
    assert abs(bearing_deg(40.0, 30.0, 41.0, 30.0)) < 0.5


def test_bearing_deg_east_returns_about_90():
    assert 89 < bearing_deg(40.0, 30.0, 40.0, 31.0) < 91


def test_parse_geometry_handles_dict_and_tuple():
    raw = [
        {"lat": 39.0, "lon": 32.0},
        {"latitude": 40.0, "longitude": 33.0},
        [41.0, 34.0],
    ]
    parsed = parse_geometry(raw)
    assert parsed == [(39.0, 32.0), (40.0, 33.0), (41.0, 34.0)]


def test_build_route_points_cumulative_distance_increases():
    raw = [
        {"lat": 39.0, "lon": 32.0},
        {"lat": 39.5, "lon": 32.5},
        {"lat": 40.0, "lon": 33.0},
    ]
    points = build_route_points(raw)
    assert len(points) == 3
    assert points[0].cumulative_distance_km == 0.0
    assert points[1].cumulative_distance_km > 0
    assert points[2].cumulative_distance_km > points[1].cumulative_distance_km
