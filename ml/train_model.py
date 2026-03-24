from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

try:
    from lightgbm import LGBMRegressor
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "lightgbm paketi kurulu değil. Kurmak için: pip install lightgbm"
    ) from exc


FEATURE_COLUMNS = [
    "segment_length_km",
    "avg_speed_kmh",
    "elevation_gain_m",
    "elevation_loss_m",
    "soc_band",
    "temperature_c",
    "vehicle_id",
]

NUMERIC_FEATURES = [
    "segment_length_km",
    "avg_speed_kmh",
    "elevation_gain_m",
    "elevation_loss_m",
    "temperature_c",
]

CATEGORICAL_FEATURES = [
    "soc_band",
    "vehicle_id",
]

COLUMN_ALIASES: Dict[str, list[str]] = {
    "segment_length_km": [
        "segment_length_km",
        "segment_distance_km",
        "distance_km",
        "length_km",
        "route_segment_km",
    ],
    "avg_speed_kmh": [
        "avg_speed_kmh",
        "average_speed_kmh",
        "speed_kmh",
        "mean_speed_kmh",
    ],
    "elevation_gain_m": [
        "elevation_gain_m",
        "gain_m",
        "uphill_m",
        "climb_m",
        "slope_gain_m",
    ],
    "elevation_loss_m": [
        "elevation_loss_m",
        "loss_m",
        "downhill_m",
        "descent_m",
        "slope_loss_m",
    ],
    "temperature_c": [
        "temperature_c",
        "temp_c",
        "ambient_temp_c",
        "weather_temp_c",
    ],
    "vehicle_id": [
        "vehicle_id",
        "vehicle",
        "car_id",
        "model_id",
        "ev_id",
    ],
    "soc_start_percent": [
        "soc_start_percent",
        "start_soc",
        "initial_soc",
        "soc_start",
    ],
    "soc_end_percent": [
        "soc_end_percent",
        "end_soc",
        "final_soc",
        "soc_end",
    ],
    "target_energy_kwh": [
        "energy_consumed_kwh",
        "segment_energy_kwh",
        "energy_kwh",
        "consumed_energy_kwh",
        "target_energy_kwh",
    ],
    "target_wh_per_km": [
        "consumption_wh_km",
        "energy_wh_km",
        "target_wh_km",
        "wh_per_km",
    ],
}


@dataclass
class TrainingArtifacts:
    model_pipeline: Pipeline
    report: Dict[str, Any]
    X_test: pd.DataFrame
    y_test: pd.Series


def _normalize_column_name(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[%/()\\-]+", "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _normalize_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {col: _normalize_column_name(str(col)) for col in df.columns}
    return df.rename(columns=renamed)


def _first_existing_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_vehicle_lookup(vehicles_path: str | Path) -> Dict[str, Dict[str, Any]]:
    path = Path(vehicles_path)
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        if "vehicles" in raw and isinstance(raw["vehicles"], list):
            items = raw["vehicles"]
        else:
            items = (
                list(raw.values())
                if all(isinstance(v, dict) for v in raw.values())
                else []
            )
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    lookup: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue

        keys = {
            str(item.get("id", "")).strip(),
            str(item.get("vehicle_id", "")).strip(),
            str(item.get("model", "")).strip(),
            str(item.get("name", "")).strip(),
        }

        for key in keys:
            if key:
                lookup[key] = item

    return lookup


def _resolve_target_series(df: pd.DataFrame) -> tuple[pd.Series, str]:
    energy_col = _first_existing_column(df, COLUMN_ALIASES["target_energy_kwh"])
    if energy_col:
        return pd.to_numeric(df[energy_col], errors="coerce"), energy_col

    whkm_col = _first_existing_column(df, COLUMN_ALIASES["target_wh_per_km"])
    dist_col = _first_existing_column(df, COLUMN_ALIASES["segment_length_km"])
    if whkm_col and dist_col:
        whkm = pd.to_numeric(df[whkm_col], errors="coerce")
        dist = pd.to_numeric(df[dist_col], errors="coerce")
        return (whkm * dist) / 1000.0, whkm_col

    raise ValueError(
        "Hedef kolon bulunamadı. Beklenen kolonlardan biri yok: "
        f"{COLUMN_ALIASES['target_energy_kwh']} veya {COLUMN_ALIASES['target_wh_per_km']}"
    )


def _build_soc_band(start_soc: float, end_soc: float) -> str:
    avg_soc = (start_soc + end_soc) / 2.0
    if avg_soc < 25:
        return "low"
    if avg_soc < 70:
        return "mid"
    return "high"


def prepare_training_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, str]:
    df = _normalize_dataframe_columns(df.copy())

    resolved: Dict[str, str] = {}
    for key in [
        "segment_length_km",
        "avg_speed_kmh",
        "elevation_gain_m",
        "elevation_loss_m",
        "temperature_c",
        "vehicle_id",
        "soc_start_percent",
        "soc_end_percent",
    ]:
        col = _first_existing_column(df, COLUMN_ALIASES[key])
        if col:
            resolved[key] = col

    if "segment_length_km" not in resolved or "avg_speed_kmh" not in resolved:
        raise ValueError("En az segment_length_km ve avg_speed_kmh kolonları bulunmalı.")

    target, target_source = _resolve_target_series(df)

    work = pd.DataFrame()
    work["segment_length_km"] = pd.to_numeric(
        df[resolved["segment_length_km"]], errors="coerce"
    )
    work["avg_speed_kmh"] = pd.to_numeric(
        df[resolved["avg_speed_kmh"]], errors="coerce"
    )
    work["elevation_gain_m"] = (
        pd.to_numeric(df[resolved["elevation_gain_m"]], errors="coerce")
        if "elevation_gain_m" in resolved
        else 0.0
    )
    work["elevation_loss_m"] = (
        pd.to_numeric(df[resolved["elevation_loss_m"]], errors="coerce")
        if "elevation_loss_m" in resolved
        else 0.0
    )
    work["temperature_c"] = (
        pd.to_numeric(df[resolved["temperature_c"]], errors="coerce")
        if "temperature_c" in resolved
        else 20.0
    )
    work["vehicle_id"] = (
        df[resolved["vehicle_id"]].astype(str).fillna("unknown")
        if "vehicle_id" in resolved
        else "unknown"
    )

    soc_start = (
        pd.to_numeric(df[resolved["soc_start_percent"]], errors="coerce")
        if "soc_start_percent" in resolved
        else pd.Series(np.full(len(df), 80.0))
    )
    soc_end = (
        pd.to_numeric(df[resolved["soc_end_percent"]], errors="coerce")
        if "soc_end_percent" in resolved
        else (soc_start - 8.0)
    )

    work["soc_band"] = [
        _build_soc_band(_safe_float(s), _safe_float(e))
        for s, e in zip(soc_start, soc_end)
    ]
    work["target_energy_kwh"] = target

    work = work.dropna(
        subset=["segment_length_km", "avg_speed_kmh", "target_energy_kwh"]
    ).reset_index(drop=True)

    if work.empty:
        raise ValueError("Eğitim için kullanılabilir satır kalmadı.")

    X = work[FEATURE_COLUMNS].copy()
    y = work["target_energy_kwh"].copy()
    return X, y, target_source


def _heuristic_baseline_predict(
    X: pd.DataFrame,
    vehicle_lookup: Dict[str, Dict[str, Any]],
) -> np.ndarray:
    predictions: list[float] = []

    for _, row in X.iterrows():
        vehicle_id = str(row["vehicle_id"])
        meta = vehicle_lookup.get(vehicle_id, {})

        ideal_wh_km = _safe_float(meta.get("ideal_consumption_wh_km"), 180.0)
        temp_penalty_factor = _safe_float(meta.get("temp_penalty_factor"), 0.012)

        segment_length_km = _safe_float(row["segment_length_km"], 0.0)
        avg_speed_kmh = _safe_float(row["avg_speed_kmh"], 80.0)
        elevation_gain_m = _safe_float(row["elevation_gain_m"], 0.0)
        elevation_loss_m = _safe_float(row["elevation_loss_m"], 0.0)
        temperature_c = _safe_float(row["temperature_c"], 20.0)
        soc_band = str(row["soc_band"])

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

        segment_energy_kwh = (segment_length_km * wh_per_km) / 1000.0
        segment_energy_kwh += elevation_gain_m * 0.00011
        segment_energy_kwh -= elevation_loss_m * 0.00004
        segment_energy_kwh = max(segment_energy_kwh, 0.01)

        predictions.append(segment_energy_kwh)

    return np.array(predictions, dtype=float)


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


def _measure_latency_ms(
    model_pipeline: Pipeline,
    X_sample: pd.DataFrame,
    repeats: int = 50,
) -> float:
    sample = X_sample.iloc[:1].copy()
    if sample.empty:
        return 0.0

    start = perf_counter()
    for _ in range(repeats):
        model_pipeline.predict(sample)
    end = perf_counter()

    return ((end - start) / repeats) * 1000.0


def _build_one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def train_model(
    *,
    data_path: str | Path = "app/data/synthetic_drive_data.csv",
    vehicles_path: str | Path = "app/data/vehicles.json",
    model_output_path: str | Path = "ml/models/lgbm_v1.joblib",
    test_size: float = 0.2,
    random_state: int = 42,
) -> TrainingArtifacts:
    df = pd.read_csv(data_path)
    X, y, target_source = prepare_training_frame(df)
    vehicle_lookup = _load_vehicle_lookup(vehicles_path)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", NUMERIC_FEATURES),
            ("cat", _build_one_hot_encoder(), CATEGORICAL_FEATURES),
        ]
    ).set_output(transform="pandas")

    model = LGBMRegressor(
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=random_state,
        verbose=-1,
    )

    model_pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model),
        ]
    )

    model_pipeline.fit(X_train, y_train)

    baseline_pred = _heuristic_baseline_predict(X_test, vehicle_lookup)
    model_pred = model_pipeline.predict(X_test)

    baseline_metrics = _calculate_metrics(y_test, baseline_pred)
    model_metrics = _calculate_metrics(y_test, model_pred)
    latency_ms = _measure_latency_ms(model_pipeline, X_test)

    report: Dict[str, Any] = {
        "model_name": "lightgbm_segment_energy_predictor",
        "model_version": "lgbm_v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "data_path": str(data_path),
        "vehicles_path": str(vehicles_path),
        "target_source_column": target_source,
        "feature_columns": FEATURE_COLUMNS,
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "baseline_metrics": baseline_metrics,
        "model_metrics": model_metrics,
        "latency_ms_per_request": round(latency_ms, 4),
    }

    artifact = {
        "model_pipeline": model_pipeline,
        "metadata": report,
    }

    output_path = Path(model_output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_path)

    return TrainingArtifacts(
        model_pipeline=model_pipeline,
        report=report,
        X_test=X_test,
        y_test=y_test,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="EV Route Optimizer - LightGBM model training"
    )
    parser.add_argument("--data", default="app/data/synthetic_drive_data.csv")
    parser.add_argument("--vehicles", default="app/data/vehicles.json")
    parser.add_argument("--out", default="ml/models/lgbm_v1.joblib")
    args = parser.parse_args()

    artifacts = train_model(
        data_path=args.data,
        vehicles_path=args.vehicles,
        model_output_path=args.out,
    )

    print("Model egitimi tamamlandi.")
    print(json.dumps(artifacts.report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()