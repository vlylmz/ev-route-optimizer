from app.services.elevation_service import OpenElevationService, ElevationPoint


def test_sample_geometry_keeps_first_and_last():
    service = OpenElevationService()

    geometry = [
        (39.0000, 32.0000),
        (39.0005, 32.0005),
        (39.0050, 32.0050),
        (39.0100, 32.0100),
    ]

    sampled = service.sample_geometry(
        geometry=geometry,
        min_spacing_km=0.5,
        max_points=10,
    )

    assert sampled[0] == geometry[0]
    assert sampled[-1] == geometry[-1]
    assert len(sampled) >= 2


def test_build_slope_segments_returns_positive_and_negative_grades():
    service = OpenElevationService()

    profile = [
        ElevationPoint(lat=39.0, lon=32.0, elevation_m=900, cumulative_distance_km=0.0),
        ElevationPoint(lat=39.01, lon=32.01, elevation_m=950, cumulative_distance_km=1.5),
        ElevationPoint(lat=39.02, lon=32.02, elevation_m=920, cumulative_distance_km=3.0),
    ]

    slopes = service.build_slope_segments(profile)

    assert len(slopes) == 2
    assert slopes[0].grade_pct > 0
    assert slopes[1].grade_pct < 0