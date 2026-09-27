"""Supporting driver-signature study using lap-level control summaries.

It deliberately avoids world position and circuit identity as classifier inputs;
those variables would allow track/session memorisation rather than a driving
signature.  The held-out circuit is Spa.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from utils import OUTPUT, ROOT, session_catalog, telemetry_path

PILOT = ["Mexico", "Monza", "Sakhir", "Spa"]
FEATURES = ["mean_speed", "max_speed", "mean_throttle", "mean_brake", "brake_frame_fraction", "mean_abs_steer", "mean_rpm", "mean_lateral_g", "mean_longitudinal_g"]


def aggregate() -> pd.DataFrame:
    output = []
    for _, info in session_catalog().query("trackId in @PILOT").iterrows():
        sid = str(info.session_id)
        telemetry = []
        cols = ["pilot_index", "currentLapNum", "speed", "throttle", "brake", "steer", "engineRPM", "gForceLateral", "gForceLongitudinal"]
        for chunk in pd.read_csv(telemetry_path(sid), usecols=cols, chunksize=200_000): telemetry.append(chunk)
        data = pd.concat(telemetry, ignore_index=True)
        data["brake_frame"] = data.brake.gt(0.05).astype(int); data["abs_steer"] = data.steer.abs()
        metrics = data.groupby(["pilot_index", "currentLapNum"], as_index=False).agg(mean_speed=("speed", "mean"), max_speed=("speed", "max"), mean_throttle=("throttle", "mean"), mean_brake=("brake", "mean"), brake_frame_fraction=("brake_frame", "mean"), mean_abs_steer=("abs_steer", "mean"), mean_rpm=("engineRPM", "mean"), mean_lateral_g=("gForceLateral", "mean"), mean_longitudinal_g=("gForceLongitudinal", "mean"))
        roster = pd.read_csv(ROOT / f"ParticipantData_{sid}.csv", usecols=["pilot_index", "driverId"])
        metrics = metrics.merge(roster, on="pilot_index"); metrics["circuit"] = info.trackId; output.append(metrics)
    return pd.concat(output, ignore_index=True)


def main() -> None:
    OUTPUT.mkdir(exist_ok=True); data = aggregate(); train, test = data[data.circuit.ne("Spa")], data[data.circuit.eq("Spa")]
    model = Pipeline([("impute", SimpleImputer(strategy="median")), ("rf", RandomForestClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced", n_jobs=-1, random_state=42))])
    model.fit(train[FEATURES], train.driverId); pred = model.predict(test[FEATURES])
    importance = dict(sorted(zip(FEATURES, model.named_steps["rf"].feature_importances_), key=lambda x: -x[1]))
    driver_metrics = data.groupby("driverId")[FEATURES].mean().round(3).to_dict(orient="index")
    result = {"split": {"train_circuits": sorted(train.circuit.unique().tolist()), "test_circuit": "Spa", "train_laps": len(train), "test_laps": len(test), "classes": int(data.driverId.nunique())}, "metrics": {"accuracy": float(accuracy_score(test.driverId, pred)), "balanced_accuracy": float(balanced_accuracy_score(test.driverId, pred)), "macro_f1": float(f1_score(test.driverId, pred, average="macro", zero_division=0))}, "feature_importance": importance, "driver_mean_metrics": driver_metrics}
    with open(OUTPUT / "driver_classification_results.json", "w", encoding="utf-8") as handle: json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
