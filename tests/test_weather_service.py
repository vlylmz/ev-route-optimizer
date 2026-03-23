import pytest

from app.services.weather_service import OpenMeteoWeatherService


def test_validate_coordinate_rejects_invalid_latitude():
    service = OpenMeteoWeatherService()

    with pytest.raises(ValueError):
        service._validate_coordinate((120.0, 32.0))


def test_validate_coordinate_rejects_invalid_longitude():
    service = OpenMeteoWeatherService()

    with pytest.raises(ValueError):
        service._validate_coordinate((39.0, 250.0))