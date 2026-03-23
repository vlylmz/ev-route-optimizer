from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import requests


Coordinate = Tuple[float, float]  # (lat, lon)


class WeatherServiceError(Exception):
    pass


@dataclass
class CurrentWeather:
    lat: float
    lon: float
    temperature_c: float
    apparent_temperature_c: float | None
    wind_speed_kmh: float | None
    raw: Dict[str, Any]


class OpenMeteoWeatherService:
    def __init__(
        self,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        timeout: int = 15,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout

    @staticmethod
    def _validate_coordinate(coord: Coordinate) -> None:
        lat, lon = coord
        if not (-90 <= lat <= 90):
            raise ValueError(f"Geçersiz latitude: {lat}")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Geçersiz longitude: {lon}")

    def get_current_weather(self, coord: Coordinate) -> CurrentWeather:
        self._validate_coordinate(coord)
        lat, lon = coord

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,wind_speed_10m",
            "timezone": "auto",
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WeatherServiceError(f"Open-Meteo isteği başarısız: {exc}") from exc

        data = response.json()
        current = data.get("current")
        if not current:
            raise WeatherServiceError("Open-Meteo current verisi döndürmedi.")

        return CurrentWeather(
            lat=float(data["latitude"]),
            lon=float(data["longitude"]),
            temperature_c=float(current["temperature_2m"]),
            apparent_temperature_c=(
                float(current["apparent_temperature"])
                if current.get("apparent_temperature") is not None
                else None
            ),
            wind_speed_kmh=(
                float(current["wind_speed_10m"])
                if current.get("wind_speed_10m") is not None
                else None
            ),
            raw=data,
        )

    def get_current_weather_dict(self, coord: Coordinate) -> Dict[str, Any]:
        result = self.get_current_weather(coord)
        return {
            "lat": result.lat,
            "lon": result.lon,
            "temperature_c": result.temperature_c,
            "apparent_temperature_c": result.apparent_temperature_c,
            "wind_speed_kmh": result.wind_speed_kmh,
        }

    def get_weather_for_points(self, coords: List[Coordinate]) -> List[Dict[str, Any]]:
        """
        Basit ve güvenli sürüm: her örnek nokta için ayrı current weather çağrısı.
        İlk entegrasyon için yeterli.
        """
        if not coords:
            return []

        results: List[Dict[str, Any]] = []
        for coord in coords:
            w = self.get_current_weather_dict(coord)
            results.append(w)

        return results

    def summarize_route_temperature(
        self,
        coords: List[Coordinate],
    ) -> Dict[str, Any]:
        """
        Rota örnek noktaları için sıcaklık özeti:
        min / max / avg
        """
        weather_points = self.get_weather_for_points(coords)
        if not weather_points:
            return {
                "point_count": 0,
                "min_temp_c": None,
                "max_temp_c": None,
                "avg_temp_c": None,
                "points": [],
            }

        temps = [p["temperature_c"] for p in weather_points]

        return {
            "point_count": len(weather_points),
            "min_temp_c": round(min(temps), 2),
            "max_temp_c": round(max(temps), 2),
            "avg_temp_c": round(sum(temps) / len(temps), 2),
            "points": weather_points,
        }


if __name__ == "__main__":
    service = OpenMeteoWeatherService()

    # Ankara
    coord = (39.9208, 32.8541)
    current = service.get_current_weather_dict(coord)

    print("Current weather:", current)

    # Örnek rota noktaları
    sample_points = [
        (39.9208, 32.8541),
        (39.8500, 31.9000),
        (39.7767, 30.5206),
    ]
    summary = service.summarize_route_temperature(sample_points)
    print("Route temperature summary:", summary)