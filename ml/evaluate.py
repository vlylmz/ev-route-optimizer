from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
)
from sklearn.model_selection import train_test_split

from ml.train_model import (
    _heuristic_baseline_predict,
    _load_vehicle_lookup,
    prepare_training_frame,
)


def _calculate_metrics(
    y_true: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
) -> Dict[str, float]:
    mse = mean_squared_error(y_true, y_pred)
    rmse = math.sqrt(float(mse))

    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": rmse,
        "mape": float(mean_absolute_percentage_error(y_true, y_pred)),
    }


def _measure_latency_ms(model_pipeline: Any, X_sample: pd.DataFrame, repeats: int = 50) -> float:
    sample = X_sample.iloc[:1].copy()
    if sample.empty:
        return 0.0

    start = perf_counter()
    for _ in range(repeats):
        model_pipeline.predict(sample)
    end = perf_counter()

    return ((end - start) / repeats) * 1000.0


def _improvement_percentage(baseline_value: float, model_value: float) -> float:
    if baseline_value == 0:
        return 0.0
    return ((baseline_value - model_value) / baseline_value) * 100.0


def evaluate_model(
    *,
    data_path: str | Path = "app/data/synthetic_drive_data.csv",
    vehicles_path: str | Path = "app/data/vehicles.json",
    model_path: str | Path = "ml/models/lgbm_v1.joblib",
    test_size: float = 0.2,
    random_state: int = 42,
    save_report_path: str | Path | None = None,
) -> Dict[str, Any]:
    df = pd.read_csv(data_path)
    X, y, target_source = prepare_training_frame(df)
    vehicle_lookup = _load_vehicle_lookup(vehicles_path)

    _, X_test, _, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
    )

    artifact = joblib.load(model_path)
    model_pipeline = artifact["model_pipeline"]
    metadata = artifact.get("metadata", {})

    baseline_pred = _heuristic_baseline_predict(X_test, vehicle_lookup)
    model_pred = model_pipeline.predict(X_test)

    baseline_metrics = _calculate_metrics(y_test, baseline_pred)
    model_metrics = _calculate_metrics(y_test, model_pred)
    latency_ms = _measure_latency_ms(model_pipeline, X_test)

    improvements = {
        "mae_improvement_percent": round(
            _improvement_percentage(baseline_metrics["mae"], model_metrics["mae"]), 2
        ),
        "rmse_improvement_percent": round(
            _improvement_percentage(baseline_metrics["rmse"], model_metrics["rmse"]), 2
        ),
        "mape_improvement_percent": round(
            _improvement_percentage(baseline_metrics["mape"], model_metrics["mape"]), 2
        ),
    }

    report: Dict[str, Any] = {
        "evaluation_name": "lightgbm_segment_energy_evaluation",
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
        "data_path": str(data_path),
        "vehicles_path": str(vehicles_path),
        "model_path": str(model_path),
        "target_source_column": target_source,
        "row_count": int(len(X)),
        "test_rows": int(len(X_test)),
        "saved_model_metadata": metadata,
        "baseline_metrics": baseline_metrics,
        "model_metrics": model_metrics,
        "improvements": improvements,
        "latency_ms_per_request": round(latency_ms, 4),
        "model_better_than_baseline": {
            "mae": model_metrics["mae"] < baseline_metrics["mae"],
            "rmse": model_metrics["rmse"] < baseline_metrics["rmse"],
            "mape": model_metrics["mape"] < baseline_metrics["mape"],
        },
    }

    if save_report_path is not None:
        output_path = Path(save_report_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EV Route Optimizer - saved model evaluation"
    )
    parser.add_argument("--data", default="app/data/synthetic_drive_data.csv")
    parser.add_argument("--vehicles", default="app/data/vehicles.json")
    parser.add_argument("--model", default="ml/models/lgbm_v1.joblib")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    report = evaluate_model(
        data_path=args.data,
        vehicles_path=args.vehicles,
        model_path=args.model,
        save_report_path=args.out,
    )

    print("Model degerlendirmesi tamamlandi.")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()