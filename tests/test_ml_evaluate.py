from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("lightgbm")

from ml.evaluate import evaluate_model
from ml.train_model import train_model
from tests.test_ml import build_synthetic_dataframe


def test_evaluate_model_returns_comparison_report(tmp_path: Path):
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

    train_model(
        data_path=data_path,
        vehicles_path=vehicles_path,
        model_output_path=model_path,
    )

    report = evaluate_model(
        data_path=data_path,
        vehicles_path=vehicles_path,
        model_path=model_path,
    )

    assert "baseline_metrics" in report
    assert "model_metrics" in report
    assert "improvements" in report
    assert "model_better_than_baseline" in report
    assert report["test_rows"] > 0
    assert report["latency_ms_per_request"] >= 0.0


def test_evaluate_model_can_save_json_report(tmp_path: Path):
    df = build_synthetic_dataframe()
    data_path = tmp_path / "synthetic_drive_data.csv"
    vehicles_path = tmp_path / "vehicles.json"
    model_path = tmp_path / "models" / "lgbm_v1.joblib"
    report_path = tmp_path / "reports" / "evaluation_report.json"

    df.to_csv(data_path, index=False)
    vehicles_path.write_text(
        json.dumps(
            [
                {"id": "ev_a", "ideal_consumption_wh_km": 170},
                {"id": "ev_b", "ideal_consumption_wh_km": 190},
            ]
        ),
        encoding="utf-8",
    )

    train_model(
        data_path=data_path,
        vehicles_path=vehicles_path,
        model_output_path=model_path,
    )

    report = evaluate_model(
        data_path=data_path,
        vehicles_path=vehicles_path,
        model_path=model_path,
        save_report_path=report_path,
    )

    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["evaluation_name"] == "lightgbm_segment_energy_evaluation"
    assert "baseline_metrics" in saved
    assert "model_metrics" in saved