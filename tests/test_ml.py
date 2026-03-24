from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
import pytest

pytest.importorskip("lightgbm")

from ml.train_model import train_model


def build_synthetic_dataframe(rows: int = 80) -> pd.DataFrame:
    data = []
    for i in range(rows):
        vehicle_id = "ev_a" if i % 2 == 0 else "ev_b"
        segment_length_km = 5 + (i % 12)
        avg_speed_kmh = 55 + (i % 45)
        elevation_gain_m = (i % 8) * 10
        elevation_loss_m = (i % 6) * 6
        temperature_c = 8 + (i % 20)
        soc_start_percent = 90 - (i % 50)
        soc_end_percent = soc_start_percent - 5

        ideal_wh_km = 170 if vehicle_id == "ev_a" else 190
        temp_factor = 1 + max(20 - temperature_c, 0) * 0.01
        speed_factor = 1 + max(avg_speed_kmh - 90, 0) * 0.003
        elevation_kwh = elevation_gain_m * 0.00011 - elevation_loss_m * 0.00004

        energy_kwh = ((segment_length_km * ideal_wh_km) / 1000.0) * temp_factor * speed_factor
        energy_kwh += elevation_kwh
        energy_kwh = max(energy_kwh, 0.02)

        data.append(
            {
                "segment_length_km": segment_length_km,
                "avg_speed_kmh": avg_speed_kmh,
                "elevation_gain_m": elevation_gain_m,
                "elevation_loss_m": elevation_loss_m,
                "temperature_c": temperature_c,
                "vehicle_id": vehicle_id,
                "soc_start_percent": soc_start_percent,
                "soc_end_percent": soc_end_percent,
                "energy_consumed_kwh": energy_kwh,
            }
        )

    return pd.DataFrame(data)


def test_train_model_creates_joblib_and_metrics(tmp_path: Path):
    df = build_synthetic_dataframe()
    data_path = tmp_path / "synthetic_drive_data.csv"
    vehicles_path = tmp_path / "vehicles.json"
    model_path = tmp_path / "models" / "lgbm_v1.joblib"

    df.to_csv(data_path, index=False)

    vehicles = [
        {
            "id": "ev_a",
            "name": "EV A",
            "ideal_consumption_wh_km": 170,
            "temp_penalty_factor": 0.01,
        },
        {
            "id": "ev_b",
            "name": "EV B",
            "ideal_consumption_wh_km": 190,
            "temp_penalty_factor": 0.012,
        },
    ]
    vehicles_path.write_text(json.dumps(vehicles), encoding="utf-8")

    result = train_model(
        data_path=data_path,
        vehicles_path=vehicles_path,
        model_output_path=model_path,
    )

    assert model_path.exists()
    assert "baseline_metrics" in result.report
    assert "model_metrics" in result.report
    assert "mae" in result.report["baseline_metrics"]
    assert "mae" in result.report["model_metrics"]
    assert result.report["train_rows"] > 0
    assert result.report["test_rows"] > 0
    assert result.report["latency_ms_per_request"] >= 0.0


def test_saved_artifact_contains_pipeline_and_metadata(tmp_path: Path):
    df = build_synthetic_dataframe()
    data_path = tmp_path / "synthetic_drive_data.csv"
    vehicles_path = tmp_path / "vehicles.json"
    model_path = tmp_path / "models" / "lgbm_v1.joblib"

    df.to_csv(data_path, index=False)
    vehicles_path.write_text(
        json.dumps(
            [{"id": "ev_a", "ideal_consumption_wh_km": 170},
             {"id": "ev_b", "ideal_consumption_wh_km": 190}]
        ),
        encoding="utf-8",
    )

    train_model(
        data_path=data_path,
        vehicles_path=vehicles_path,
        model_output_path=model_path,
    )

    artifact = joblib.load(model_path)

    assert "model_pipeline" in artifact
    assert "metadata" in artifact
    assert artifact["metadata"]["model_version"] == "lgbm_v1"