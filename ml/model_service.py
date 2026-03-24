from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import joblib
import numpy as np
import pandas as pd


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value = float(value)
        if math.isnan(value):
            return default
        return value
    except (TypeError, ValueError):
        return default


def _pick(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _build_soc_band(start_soc: float, end_soc: float) -> str:
    avg_soc = (start_soc + end_soc) / 2.0
    if avg_soc < 25:
        return "low"
    if avg_soc < 70:
        return "mid"
    return "high"


class ModelService:
    """
    Eğitilmiş ML modelini güvenli şekilde kullanır.

    Tasarım hedefi:
    - model varsa ML tahmini yap
    - model yoksa / kapalıysa / hata verirse heuristic fallback kullan
    - çekirdek sistem asla ML yüzünden kırılmasın
    """

    def __init__(
        self,
        *,
        model_path: str | Path = "ml/models/lgbm_v1.joblib",
        enabled: bool = True,
        default_temperature_c: float = 20.0,
    ) -> None:
        self.model_path = Path(model_path)
        self.enabled = enabled
        self.default_temperature_c = default_temperature_c
        self._artifact: Optional[Dict[str, Any]] = None

    def is_available(self) -> bool:
        return self.enabled and self.model_path.exists()

    def get_metadata(self) -> Dict[str, Any]:
        artifact = self._load_artifact(silent=True)
        if artifact is None:
            return {}
        return artifact.get("metadata", {}) or {}

    def predict_segment_energy(
        self,
        *,
        segment: Dict[str, Any],
        vehicle: Dict[str, Any],
        weather: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        features = self._build_feature_row(
            segment=segment,
            vehicle=vehicle,
            weather=weather,
        )

        fallback_energy_kwh = self._heuristic_predict_energy_kwh(
            features=features.iloc[0].to_dict(),
            vehicle=vehicle,
        )

        if not self.enabled:
            return {
                "source": "heuristic_disabled",
                "used_model": False,
                "predicted_energy_kwh": round(fallback_energy_kwh, 6),
                "fallback_energy_kwh": round(fallback_energy_kwh, 6),
                "model_version": None,
                "features": features.iloc[0].to_dict(),
            }

        artifact = self._load_artifact(silent=True)
        if artifact is None:
            return {
                "source": "heuristic_no_model",
                "used_model": False,
                "predicted_energy_kwh": round(fallback_energy_kwh, 6),
                "fallback_energy_kwh": round(fallback_energy_kwh, 6),
                "model_version": None,
                "features": features.iloc[0].to_dict(),
            }

        try:
            pipeline = artifact["model_pipeline"]
            raw_pred = pipeline.predict(features)
            predicted = float(raw_pred[0])

            if math.isnan(predicted) or predicted <= 0:
                raise ValueError("Model tahmini gecersiz.")

            metadata = artifact.get("metadata", {}) or {}

            return {
                "source": "ml",
                "used_model": True,
                "predicted_energy_kwh": round(predicted, 6),
                "fallback_energy_kwh": round(fallback_energy_kwh, 6),
                "model_version": metadata.get("model_version"),
                "features": features.iloc[0].to_dict(),
            }

        except Exception as exc:
            return {
                "source": "heuristic_error",
                "used_model": False,
                "predicted_energy_kwh": round(fallback_energy_kwh, 6),
                "fallback_energy_kwh": round(fallback_energy_kwh, 6),
                "model_version": None,
                "error": str(exc),
                "features": features.iloc[0].to_dict(),
            }

    def predict_segments(
        self,
        *,
        segments: Iterable[Dict[str, Any]],
        vehicle: Dict[str, Any],
        weather: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []

        for index, segment in enumerate(segments):
            result = self.predict_segment_energy(
                segment=segment,
                vehicle=vehicle,
                weather=weather,
            )
            result["segment_index"] = index
            results.append(result)

        total_energy_kwh = sum(_safe_float(item["predicted_energy_kwh"]) for item in results)
        ml_count = sum(1 for item in results if item["used_model"])
        heuristic_count = len(results) - ml_count

        return {
            "segments": results,
            "segment_count": len(results),
            "total_energy_kwh": round(total_energy_kwh, 6),
            "ml_prediction_count": ml_count,
            "heuristic_prediction_count": heuristic_count,
        }

    def _load_artifact(self, *, silent: bool = False) -> Optional[Dict[str, Any]]:
        if self._artifact is not None:
            return self._artifact

        if not self.model_path.exists():
            return None

        try:
            self._artifact = joblib.load(self.model_path)
            return self._artifact
        except Exception:
            if silent:
                return None
            raise

    def _build_feature_row(
        self,
        *,
        segment: Dict[str, Any],
        vehicle: Dict[str, Any],
        weather: Optional[Dict[str, Any]] = None,
    ) -> pd.DataFrame:
        segment_length_km = _safe_float(
            _pick(segment, "segment_length_km", "distance_km", "length_km"),
            0.0,
        )

        avg_speed_kmh = _safe_float(
            _pick(segment, "avg_speed_kmh", "average_speed_kmh", "speed_kmh"),
            0.0,
        )

        if avg_speed_kmh <= 0:
            duration_min = _safe_float(
                _pick(segment, "duration_min", "duration_minutes"),
                0.0,
            )
            if duration_min > 0 and segment_length_km > 0:
                avg_speed_kmh = segment_length_km / (duration_min / 60.0)

        elevation_gain_m = _safe_float(
            _pick(segment, "elevation_gain_m", "gain_m", "uphill_m"),
            0.0,
        )
        elevation_loss_m = _safe_float(
            _pick(segment, "elevation_loss_m", "loss_m", "downhill_m"),
            0.0,
        )

        temperature_c = self._resolve_temperature(
            segment=segment,
            weather=weather,
        )

        vehicle_id = str(
            _pick(vehicle, "id", "vehicle_id", "name", "model", default="unknown")
        )

        soc_start_percent = _safe_float(
            _pick(segment, "soc_start_percent", "start_soc", "initial_soc"),
            80.0,
        )
        soc_end_percent = _safe_float(
            _pick(segment, "soc_end_percent", "end_soc", "final_soc"),
            max(soc_start_percent - 5.0, 0.0),
        )

        soc_band = _build_soc_band(soc_start_percent, soc_end_percent)

        row = {
            "segment_length_km": segment_length_km,
            "avg_speed_kmh": avg_speed_kmh,
            "elevation_gain_m": elevation_gain_m,
            "elevation_loss_m": elevation_loss_m,
            "soc_band": soc_band,
            "temperature_c": temperature_c,
            "vehicle_id": vehicle_id,
        }

        return pd.DataFrame([row])

    def _resolve_temperature(
        self,
        *,
        segment: Dict[str, Any],
        weather: Optional[Dict[str, Any]],
    ) -> float:
        if weather:
            value = _pick(
                weather,
                "temperature_c",
                "temp_c",
                "current_temp_c",
                "ambient_temp_c",
                default=None,
            )
            if value is not None:
                return _safe_float(value, self.default_temperature_c)

        seg_temp = _pick(segment, "temperature_c", "temp_c", default=None)
        if seg_temp is not None:
            return _safe_float(seg_temp, self.default_temperature_c)

        return self.default_temperature_c

    def _heuristic_predict_energy_kwh(
        self,
        *,
        features: Dict[str, Any],
        vehicle: Dict[str, Any],
    ) -> float:
        ideal_wh_km = _safe_float(
            _pick(vehicle, "ideal_consumption_wh_km"),
            180.0,
        )
        temp_penalty_factor = _safe_float(
            _pick(vehicle, "temp_penalty_factor"),
            0.012,
        )

        segment_length_km = _safe_float(features.get("segment_length_km"), 0.0)
        avg_speed_kmh = _safe_float(features.get("avg_speed_kmh"), 80.0)
        elevation_gain_m = _safe_float(features.get("elevation_gain_m"), 0.0)
        elevation_loss_m = _safe_float(features.get("elevation_loss_m"), 0.0)
        temperature_c = _safe_float(features.get("temperature_c"), self.default_temperature_c)
        soc_band = str(features.get("soc_band", "mid"))

        wh_per_km = ideal_wh_km

        if temperature_c < 20:
            wh_per_km *= 1 + ((20 - temperature_c) * temp_penalty_factor)
        elif temperature_c > 28:
            wh_per_km *= 1 + ((temperature_c - 28) * 0.006)

        if avg_speed_kmh > 90:
            wh_per_km *= 1 + ((avg_speed_kmh - 90) * 0.004)
        elif avg_speed_kmh < 55:
            wh_per_km *= 1 + ((55 - avg_speed_kmh) * 0.0015)

        if soc_band == "low":
            wh_per_km *= 1.02
        elif soc_band == "high":
            wh_per_km *= 1.01

        energy_kwh = (segment_length_km * wh_per_km) / 1000.0
        energy_kwh += elevation_gain_m * 0.00011
        energy_kwh -= elevation_loss_m * 0.00004

        return max(energy_kwh, 0.01)


if __name__ == "__main__":
    vehicle = {
        "id": "demo_ev",
        "ideal_consumption_wh_km": 180,
        "temp_penalty_factor": 0.012,
    }

    segment = {
        "segment_length_km": 12.0,
        "avg_speed_kmh": 88.0,
        "elevation_gain_m": 70.0,
        "elevation_loss_m": 20.0,
        "soc_start_percent": 78.0,
        "soc_end_percent": 72.0,
    }

    service = ModelService()
    result = service.predict_segment_energy(segment=segment, vehicle=vehicle)
    print(result)