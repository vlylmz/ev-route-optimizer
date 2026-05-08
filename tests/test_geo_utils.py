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


def test_spatial_index_returns_correct_nearest():
    """RouteSpatialIndex en yakin noktayi dogru bulur."""
    from app.core.geo_utils import RoutePoint, RouteSpatialIndex

    points = [
        RoutePoint(lat=39.0, lon=32.0, cumulative_distance_km=0.0),
        RoutePoint(lat=40.0, lon=33.0, cumulative_distance_km=140.0),
        RoutePoint(lat=41.0, lon=34.0, cumulative_distance_km=280.0),
    ]
    index = RouteSpatialIndex(points)

    nearest, offset = index.nearest(40.05, 33.05)
    assert nearest.cumulative_distance_km == 140.0
    assert offset < 10  # ~7km civari


def test_spatial_index_smoke_200_stations_500_route_points_under_100ms():
    """200 istasyon x 500 route_point < 100ms (KDTree ile)."""
    import time

    from app.core.geo_utils import RoutePoint, RouteSpatialIndex

    points = [
        RoutePoint(lat=39.0 + i * 0.005, lon=32.0 + i * 0.005, cumulative_distance_km=i * 0.7)
        for i in range(500)
    ]
    index = RouteSpatialIndex(points)

    stations = [(39.0 + i * 0.012, 32.0 + i * 0.012) for i in range(200)]

    start = time.perf_counter()
    for lat, lon in stations:
        index.nearest(lat, lon)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"Spatial index 200x500 sorgu {elapsed*1000:.1f}ms (>100ms hedef)"
