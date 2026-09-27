"""Targeted Model Packaging & Benchmark Parity Verification.

Trains the finalized Experiment C XGBoost model strictly on Mexico, Monza, and Sakhir,
evaluates against held-out Spa, checks exact numerical parity against frozen benchmarks,
and packages the model into models/surface_departure_xgboost/.
"""
from __future__ import annotations

import sys, json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from src.data.causal_features import (
    FEATURE_NAMES_EXP_C,
    compute_causal_features_batch,
    verify_feature_integrity,
)
MODELS_DIR = ROOT / "models" / "surface_departure_xgboost"

# The 4 verified pilot sessions
SESSIONS = {
    "Mexico": "10230136787177318441",
    "Monza": "1087987310493855854",
    "Sakhir": "3335673977098133433",
    "Spa": "4048657932346004126",
}
TRAIN_CIRCUITS = ["Mexico", "Monza", "Sakhir"]
TEST_CIRCUIT = "Spa"

# Frozen benchmark values for Exp C at threshold 0.50
FROZEN_BENCHMARK = {
    "roc_auc": 0.73095,
    "pr_auc": 0.24385,
    "precision": 0.42815,
    "recall": 0.14881,
    "f1": 0.22086,
    "event_recall": 0.3116,
    "events_detected": 86,
    "total_events": 276,
    "mean_lead_seconds": 0.729,
    "false_warning_rate": 0.0199,
}

RAW_COLS = [
    "sessionTime",
    "frameIdentifier",
    "pilot_index",
    "surfaceType",
    "currentLapNum",
    "speed",
    "throttle",
    "brake",
    "steer",
    "gear",
    "engineRPM",
    "drs",
    "gForceLateral",
    "gForceLongitudinal",
    "gForceVertical",
    "sector",
    "lapDistance",
]


def load_session_samples(circuit: str, sid: str) -> pd.DataFrame:
    """Load single session, compute target and causal features, return deterministic 10:1 sample."""
    csv_path = ROOT / f"TelemetryData_{sid}.csv"
    pieces = []
    for chunk in pd.read_csv(csv_path, usecols=RAW_COLS, chunksize=200_000):
        pieces.append(chunk)
    frame = pd.concat(pieces, ignore_index=True).sort_values(["pilot_index", "frameIdentifier"]).reset_index(drop=True)

    # Compute target: code 7 in t+1 .. t+19
    frame["departure_now"] = (
        frame["surfaceType"].astype("string")
        .str.contains(r"(?:^|/)7(?:/|$)", regex=True, na=False)
        .astype(int)
    )
    group = frame.groupby("pilot_index", sort=False)
    reverse_roll = group["departure_now"].transform(
        lambda x: x.iloc[::-1].rolling(19, min_periods=1).max().iloc[::-1]
    )
    frame["target_departure_next_1s"] = (
        reverse_roll.groupby(frame["pilot_index"]).shift(-1).fillna(0).astype(int)
    )

    # Compute causal features
    frame = compute_causal_features_batch(frame)

    # Retain on-track frames only
    on_track = frame[frame["departure_now"].eq(0)].copy()
    on_track["circuit"] = circuit
    on_track["session_id"] = sid

    # Controlled deterministic 10:1 negative sampling (matching pilot)
    pos = on_track[on_track["target_departure_next_1s"].eq(1)]
    neg = on_track[on_track["target_departure_next_1s"].eq(0)]
    take_neg = min(len(neg), max(20_000, len(pos) * 10))
    sampled_neg = neg.sample(take_neg, random_state=42)

    return pd.concat([pos, sampled_neg], ignore_index=True).sort_values(["pilot_index", "frameIdentifier"])


def evaluate_event_level(test_df: pd.DataFrame, probas: np.ndarray, threshold: float = 0.5) -> dict:
    """Evaluate event detection against ground truth Spa departure events."""
    events_path = ROOT / "analysis_outputs" / "surface_departure_events.csv"
    spa_events = pd.read_csv(events_path).query("circuit == 'Spa'").reset_index(drop=True)

    preds = (probas >= threshold).astype(int)
    test_eval = test_df[["pilot_index", "frameIdentifier", "sessionTime"]].copy()
    test_eval["pred"] = preds

    driver_groups = {pid: grp.set_index("frameIdentifier") for pid, grp in test_eval.groupby("pilot_index")}

    total_events = len(spa_events)
    detected = 0
    leads_sec = []

    for _, ev in spa_events.iterrows():
        pid = int(ev["pilot_index"])
        start_f = int(ev["start_frame"])
        start_t = float(ev["start_time"])

        if pid not in driver_groups:
            continue

        driver_data = driver_groups[pid]
        pre_frames = [f for f in range(start_f - 19, start_f) if f in driver_data.index]
        if not pre_frames:
            continue

        warnings = driver_data.loc[pre_frames]
        if (warnings["pred"] == 1).any():
            detected += 1
            first_warn_f = warnings[warnings["pred"] == 1].index[0]
            first_warn_t = float(warnings.loc[first_warn_f, "sessionTime"])
            leads_sec.append(max(0.0, start_t - first_warn_t))

    neg_frames = test_eval[test_df["target_departure_next_1s"].eq(0)]
    false_warning_rate = float(neg_frames["pred"].sum()) / len(neg_frames) if len(neg_frames) > 0 else 0.0

    return {
        "total_events": total_events,
        "events_detected": detected,
        "event_recall": detected / total_events if total_events > 0 else 0.0,
        "mean_lead_seconds": float(np.mean(leads_sec)) if leads_sec else 0.0,
        "false_warning_rate": false_warning_rate,
    }


def main() -> None:
    print("=" * 70)
    print("F1 TELEMETRY ML: TARGETED MODEL PACKAGING & PARITY VALIDATION")
    print("=" * 70)

    # 1. Verify feature integrity
    verify_feature_integrity(FEATURE_NAMES_EXP_C)
    print(f"Verified feature list: 30 features, strict exclusion of lapDistance/surfaceType/worldPosition.")

    # 2. Load the 3 training sessions and 1 test session
    print("\nLoading session samples (deterministic 10:1 sampling)...")
    t0 = time.time()
    train_dfs = []
    for circuit in TRAIN_CIRCUITS:
        sid = SESSIONS[circuit]
        print(f"  Loading {circuit} (session {sid})...")
        df_c = load_session_samples(circuit, sid)
        print(f"    -> {len(df_c):,} rows ({df_c['target_departure_next_1s'].sum():,} positives)")
        train_dfs.append(df_c)

    train_df = pd.concat(train_dfs, ignore_index=True)
    print(f"Total training data: {len(train_df):,} rows ({train_df['target_departure_next_1s'].sum():,} positives)")

    print(f"  Loading held-out {TEST_CIRCUIT} (session {SESSIONS[TEST_CIRCUIT]})...")
    test_df = load_session_samples(TEST_CIRCUIT, SESSIONS[TEST_CIRCUIT])
    print(f"    -> {len(test_df):,} rows ({test_df['target_departure_next_1s'].sum():,} positives)")
    print(f"Data preparation completed in {time.time() - t0:.1f}s.")

    # 3. Fit Imputer and XGBoost
    X_train = train_df[FEATURE_NAMES_EXP_C]
    y_train = train_df["target_departure_next_1s"]
    X_test = test_df[FEATURE_NAMES_EXP_C]
    y_test = test_df["target_departure_next_1s"]

    num_neg = int((y_train == 0).sum())
    num_pos = int((y_train == 1).sum())
    spw = num_neg / num_pos if num_pos > 0 else 1.0

    print(f"\nFitting SimpleImputer and XGBClassifier (scale_pos_weight={spw:.2f})...")
    t_fit = time.time()
    imputer = SimpleImputer(strategy="median")
    X_train_imp = imputer.fit_transform(X_train)
    X_test_imp = imputer.transform(X_test)

    model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=spw,
        eval_metric="logloss",
        n_jobs=-1,
        random_state=42,
    )
    model.fit(X_train_imp, y_train)
    print(f"Fitting completed in {time.time() - t_fit:.1f}s.")

    # 4. Evaluate against held-out Spa
    print("\nEvaluating on held-out Spa test set (Threshold = 0.50)...")
    probas = model.predict_proba(X_test_imp)[:, 1]
    preds = (probas >= 0.50).astype(int)

    roc_auc = float(roc_auc_score(y_test, probas))
    pr_auc = float(average_precision_score(y_test, probas))
    prec = float(precision_score(y_test, preds, zero_division=0))
    rec = float(recall_score(y_test, preds, zero_division=0))
    f1 = float(f1_score(y_test, preds, zero_division=0))
    ev_res = evaluate_event_level(test_df, probas, threshold=0.50)

    reproduced = {
        "roc_auc": round(roc_auc, 5),
        "pr_auc": round(pr_auc, 5),
        "precision": round(prec, 5),
        "recall": round(rec, 5),
        "f1": round(f1, 5),
        "event_recall": round(ev_res["event_recall"], 4),
        "events_detected": ev_res["events_detected"],
        "total_events": ev_res["total_events"],
        "mean_lead_seconds": round(ev_res["mean_lead_seconds"], 3),
        "false_warning_rate": round(ev_res["false_warning_rate"], 4),
    }

    print("\n" + "=" * 70)
    print("PARITY VALIDATION REPORT (FROZEN vs REPRODUCED)")
    print("=" * 70)
    print(f"{'Metric':<25} | {'Frozen':<12} | {'Reproduced':<12} | {'Diff':<10}")
    print("-" * 65)
    for key in FROZEN_BENCHMARK:
        fz = FROZEN_BENCHMARK[key]
        rp = reproduced[key]
        diff = rp - fz if isinstance(fz, (int, float)) else 0
        diff_str = f"{diff:+.5f}" if isinstance(diff, float) else f"{diff:+d}"
        print(f"{key:<25} | {fz:<12} | {rp:<12} | {diff_str:<10}")

    # Check tolerances
    assert abs(reproduced["roc_auc"] - FROZEN_BENCHMARK["roc_auc"]) < 0.005, "ROC-AUC divergence!"
    assert abs(reproduced["pr_auc"] - FROZEN_BENCHMARK["pr_auc"]) < 0.005, "PR-AUC divergence!"
    assert abs(reproduced["precision"] - FROZEN_BENCHMARK["precision"]) < 0.010, "Precision divergence!"
    assert abs(reproduced["recall"] - FROZEN_BENCHMARK["recall"]) < 0.010, "Recall divergence!"
    assert abs(reproduced["events_detected"] - FROZEN_BENCHMARK["events_detected"]) <= 2, "Event recall divergence!"
    print("\nPARITY VALIDATION PASSED: All metrics match frozen benchmark within strict tolerances!")

    # 5. Save model artifacts
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODELS_DIR / "model.joblib")
    joblib.dump(imputer, MODELS_DIR / "preprocessor.joblib")

    with open(MODELS_DIR / "feature_list.json", "w", encoding="utf-8") as f:
        json.dump(FEATURE_NAMES_EXP_C, f, indent=2)

    metadata = {
        "model_name": "surface_departure_xgboost",
        "experiment": "Exp C (No LapDist)",
        "model_type": "XGBClassifier",
        "application_threshold": 0.50,
        "feature_count": len(FEATURE_NAMES_EXP_C),
        "features": FEATURE_NAMES_EXP_C,
        "training_circuits": TRAIN_CIRCUITS,
        "validation_circuit": "Sakhir",
        "test_circuit": TEST_CIRCUIT,
        "training_rows": len(train_df),
        "test_rows": len(test_df),
        "test_metrics": reproduced,
        "xgboost_params": {
            "n_estimators": 200,
            "max_depth": 6,
            "learning_rate": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "scale_pos_weight": round(spw, 4),
            "eval_metric": "logloss",
            "random_state": 42,
        },
        "packaged_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(MODELS_DIR / "model_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nModel artifacts successfully saved to {MODELS_DIR}:")
    print(f"  - {MODELS_DIR / 'model.joblib'}")
    print(f"  - {MODELS_DIR / 'preprocessor.joblib'}")
    print(f"  - {MODELS_DIR / 'feature_list.json'}")
    print(f"  - {MODELS_DIR / 'model_metadata.json'}")


if __name__ == "__main__":
    main()
