"""Read-only pilot ML study on Mexico, Monza, Sakhir and Spa.

The primary classification task is a one-second-ahead warning, not a label
reconstruction task: surfaceType is never a model input.  Spa is wholly held
out, so neither adjacent frames nor any data from its session appear in train.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score,
                             mean_absolute_error, mean_squared_error, precision_score,
                             r2_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

try:
    from xgboost import XGBClassifier
except ImportError:
    XGBClassifier = None

from utils import OUTPUT, ROOT, session_catalog, telemetry_path

PILOT_CIRCUITS = ["Mexico", "Monza", "Sakhir", "Spa"]
TEST_CIRCUIT = "Spa"
RAW = ["speed", "throttle", "brake", "steer", "gear", "engineRPM", "drs", "gForceLateral", "gForceLongitudinal", "gForceVertical", "lapDistance", "sector"]
DERIVED = ["acceleration_kmh_s", "throttle_rate_s", "brake_rate_s", "steer_rate_s"]
USECOLS = ["sessionTime", "frameIdentifier", "pilot_index", "surfaceType", "currentLapNum"] + RAW
RNG = np.random.default_rng(42)


def binary_metrics(y, probability) -> dict:
    prediction = (probability >= .5).astype(int)
    return {"precision": float(precision_score(y, prediction, zero_division=0)), "recall": float(recall_score(y, prediction, zero_division=0)), "f1": float(f1_score(y, prediction, zero_division=0)), "roc_auc": float(roc_auc_score(y, probability)), "pr_auc": float(average_precision_score(y, probability)), "confusion_matrix": confusion_matrix(y, prediction).tolist()}


def telemetry_pilot(catalogue: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    samples, counts = [], {"rows": 0, "positive_warning_frames": 0, "laps": set(), "drivers": set()}
    for _, info in catalogue.iterrows():
        sid, circuit = str(info.session_id), str(info.trackId)
        participant = pd.read_csv(ROOT / f"ParticipantData_{sid}.csv", usecols=["pilot_index", "driverId"])
        pieces = []
        # Each session is loaded independently; it is the maximum in-memory unit.
        for chunk in pd.read_csv(telemetry_path(sid), usecols=USECOLS, chunksize=200_000): pieces.append(chunk)
        frame = pd.concat(pieces, ignore_index=True).sort_values(["pilot_index", "frameIdentifier"])
        frame["departure_now"] = frame.surfaceType.astype("string").str.contains(r"(?:^|/)7(?:/|$)", regex=True, na=False).astype(int)
        group = frame.groupby("pilot_index", sort=False)
        # Target = a departure in frames t+1 .. t+19 (approximately next second).
        reverse_roll = group["departure_now"].transform(lambda x: x.iloc[::-1].rolling(19, min_periods=19).max().iloc[::-1])
        frame["target_departure_next_1s"] = reverse_roll.groupby(frame.pilot_index).shift(-1).fillna(0).astype(int)
        dt = group.sessionTime.diff().replace(0, np.nan)
        for base, name in [("speed", "acceleration_kmh_s"), ("throttle", "throttle_rate_s"), ("brake", "brake_rate_s"), ("steer", "steer_rate_s")]: frame[name] = group[base].diff() / dt
        frame = frame[frame.departure_now.eq(0)].merge(participant, on="pilot_index", how="left")
        frame["circuit"], frame["session_id"] = circuit, sid
        counts["rows"] += len(frame); counts["positive_warning_frames"] += int(frame.target_departure_next_1s.sum())
        counts["laps"].update(zip(frame.session_id, frame.pilot_index, frame.currentLapNum)); counts["drivers"].update(frame.driverId.dropna())
        # Retain every rare positive and a deterministic 10:1 negative sample per session.
        positive = frame[frame.target_departure_next_1s.eq(1)]
        negative = frame[frame.target_departure_next_1s.eq(0)]
        take = min(len(negative), max(20_000, len(positive) * 10))
        samples.append(pd.concat([positive, negative.sample(take, random_state=42)], ignore_index=True))
    counts["laps"] = len(counts["laps"]); counts["drivers"] = len(counts["drivers"])
    return pd.concat(samples, ignore_index=True), counts


def classification(sample: pd.DataFrame) -> dict:
    features = RAW + DERIVED
    train, test = sample[sample.circuit.ne(TEST_CIRCUIT)], sample[sample.circuit.eq(TEST_CIRCUIT)]
    X_train, y_train, X_test, y_test = train[features], train.target_departure_next_1s, test[features], test.target_departure_next_1s
    pre = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    models = {"logistic_regression": Pipeline([("pre", pre), ("model", LogisticRegression(max_iter=500, class_weight="balanced", n_jobs=-1))]), "random_forest": Pipeline([("impute", SimpleImputer(strategy="median")), ("model", RandomForestClassifier(n_estimators=200, min_samples_leaf=5, class_weight="balanced_subsample", n_jobs=-1, random_state=42))])}
    if XGBClassifier:
        models["xgboost"] = Pipeline([("impute", SimpleImputer(strategy="median")), ("model", XGBClassifier(n_estimators=200, max_depth=6, learning_rate=.1, subsample=.8, colsample_bytree=.8, eval_metric="logloss", n_jobs=-1, random_state=42))])
    results, importance = {}, {}
    for name, model in models.items():
        model.fit(X_train, y_train); p = model.predict_proba(X_test)[:, 1]; results[name] = binary_metrics(y_test, p)
        if name == "random_forest": importance = dict(sorted(zip(features, model.named_steps["model"].feature_importances_), key=lambda x: -x[1]))
    return {"split": {"train_circuits": sorted(train.circuit.unique().tolist()), "test_circuit": TEST_CIRCUIT, "train_rows": len(train), "test_rows": len(test), "test_positive_frames": int(y_test.sum())}, "results": results, "random_forest_feature_importance": importance}


def lap_time(catalogue: pd.DataFrame) -> dict:
    rows = []
    for _, info in catalogue.iterrows():
        sid = str(info.session_id); data = pd.read_csv(ROOT / f"RaceTimeData_{sid}.csv")
        data = data[data.LapTime.between(45, 150)].copy()
        data["trackLength"], data["airTemperature"], data["trackTemperature"], data["circuit"] = info.trackLength, info.airTemperature, info.trackTemperature, info.trackId
        rows.append(data)
    data = pd.concat(rows, ignore_index=True); train, test = data[data.circuit.ne(TEST_CIRCUIT)], data[data.circuit.eq(TEST_CIRCUIT)]
    # Option B: Sector 1 is complete; sectors 2/3 are deliberately excluded.
    features = ["sector1TimeInMS", "currentLapNum", "trackLength", "airTemperature", "trackTemperature"]
    models = {"ridge": Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=1.0))]), "random_forest": RandomForestRegressor(n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=42)}
    scores = {}
    for name, model in models.items():
        model.fit(train[features], train.LapTime); p = model.predict(test[features]); scores[name] = {"mae_seconds": float(mean_absolute_error(test.LapTime, p)), "rmse_seconds": float(mean_squared_error(test.LapTime, p) ** .5), "r2": float(r2_score(test.LapTime, p))}
    return {"scenario": "predict final lap time after Sector 1", "clean_laps": len(data), "train_laps": len(train), "test_laps": len(test), "results": scores}


def anomalies(sample: pd.DataFrame) -> dict:
    features = RAW + DERIVED; train = sample[sample.circuit.ne(TEST_CIRCUIT)]; test = sample[sample.circuit.eq(TEST_CIRCUIT)]
    pipe = Pipeline([("impute", SimpleImputer(strategy="median")), ("model", IsolationForest(n_estimators=200, contamination=.01, n_jobs=-1, random_state=42))])
    pipe.fit(train[features]); score = -pipe.decision_function(test[features]); return binary_metrics(test.target_departure_next_1s.to_numpy(), (score - score.min()) / (score.max() - score.min()))


def main() -> None:
    OUTPUT.mkdir(exist_ok=True); catalogue = session_catalog(); pilot = catalogue[catalogue.trackId.isin(PILOT_CIRCUITS)].copy()
    sample, coverage = telemetry_pilot(pilot)
    result = {"pilot": {"circuits": pilot.trackId.tolist(), "sessions": len(pilot), **coverage, "model_sample_rows": len(sample)}, "surface_departure_classification": classification(sample), "lap_time_prediction": lap_time(pilot), "anomaly_detection_against_next_1s_surface_target": anomalies(sample)}
    with open(OUTPUT / "pilot_ml_results.json", "w", encoding="utf-8") as handle: json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
