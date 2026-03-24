from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("lightgbm")

from ml.model_service import ModelService
from ml.train_model import train_model
from tests.test_ml import build_synthetic_dataframe


def test_predict_segment_uses_ml_when_model_exists(tmp_path: Path):
    df = build_synthetic_dataframe()
    data_path = tmp_path / "synthetic_drive_data.csv"
    vehicles_path = tmp_path / "vehicles.json"
    model_path = tmp_path / "models" / "lgbm_v1.joblib"

    df.to_csv(data_path, index=False)
    vehicles_path.write_text(
        json.dumps(
            [
                {"id": "ev_a", "ideal_consumption_wh_km": 170, "temp_penalty_factor": 0.01},
                {"id": "ev_b", "ideal_consumption_wh_km": 190, "temp_penalty_factor": 0.012},
            ]
        ),
        encoding="utf-8",
    )

    train_model(
        data_path=data_path,
        vehicles_path=vehicles_path,
        model_output_path=model_path,
    )

    service = ModelService(model_path=model_path, enabled=True)

    result = service.predict_segment_energy(
        segment={
            "segment_length_km": 10.0,
            "avg_speed_kmh": 80.0,
            "elevation_gain_m": 50.0,
            "elevation_loss_m": 10.0,
            "soc_start_percent": 80.0,
            "soc_end_percent": 74.0,
            "temperature_c": 18.0,
        },
        vehicle={
            "id": "ev_a",
            "ideal_consumption_wh_km": 170,
            "temp_penalty_factor": 0.01,
        },
    )

    assert result["used_model"] is True
    assert result["source"] == "ml"
    assert result["predicted_energy_kwh"] > 0
    assert result["model_version"] == "lgbm_v1"


def test_predict_segment_falls_back_when_model_missing(tmp_path: Path):
    service = ModelService(
        model_path=tmp_path / "missing_model.joblib",
        enabled=True,
    )

    result = service.predict_segment_energy(
        segment={
            "segment_length_km": 8.0,
            "avg_speed_kmh": 70.0,
            "elevation_gain_m": 30.0,
            "elevation_loss_m": 5.0,
            "soc_start_percent": 65.0,
            "soc_end_percent": 60.0,
            "temperature_c": 12.0,
        },
        vehicle={
            "id": "ev_a",
            "ideal_consumption_wh_km": 175,
            "temp_penalty_factor": 0.01,
        },
    )

    assert result["used_model"] is False
    assert result["source"] == "heuristic_no_model"
    assert result["predicted_energy_kwh"] > 0
    assert result["predicted_energy_kwh"] == result["fallback_energy_kwh"]


def test_predict_segments_returns_total_energy(tmp_path: Path):
    service = ModelService(
        model_path=tmp_path / "missing_model.joblib",
        enabled=True,
    )

    result = service.predict_segments(
        segments=[
            {
                "segment_length_km": 6.0,
                "avg_speed_kmh": 60.0,
                "elevation_gain_m": 20.0,
                "elevation_loss_m": 5.0,
                "soc_start_percent": 80.0,
                "soc_end_percent": 76.0,
                "temperature_c": 20.0,
            },
            {
                "segment_length_km": 9.0,
                "avg_speed_kmh": 85.0,
                "elevation_gain_m": 40.0,
                "elevation_loss_m": 10.0,
                "soc_start_percent": 76.0,
                "soc_end_percent": 70.0,
                "temperature_c": 18.0,
            },
        ],
        vehicle={
            "id": "ev_test",
            "ideal_consumption_wh_km": 180,
            "temp_penalty_factor": 0.012,
        },
    )

    assert result["segment_count"] == 2
    assert result["heuristic_prediction_count"] == 2
    assert result["ml_prediction_count"] == 0
    assert result["total_energy_kwh"] > 0
    assert len(result["segments"]) == 2