from __future__ import annotations
import json, time
from pathlib import Path
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from src.data.schema import MODEL_FEATURES

def train_random_forest(data: pd.DataFrame, artifact_dir: Path, metadata: dict) -> Path:
    """Production choice: best Phase-2 PR-AUC, portable and interpretable."""
    artifact_dir.mkdir(parents=True, exist_ok=True); started=time.perf_counter()
    model=Pipeline([("imputer",SimpleImputer(strategy="median")),("model",RandomForestClassifier(n_estimators=200,min_samples_leaf=5,class_weight="balanced_subsample",n_jobs=-1,random_state=42))])
    model.fit(data[MODEL_FEATURES],data.target_departure_next_1s)
    path=artifact_dir/"surface_departure_random_forest.joblib"; joblib.dump(model,path)
    (artifact_dir/"feature_list.json").write_text(json.dumps(MODEL_FEATURES,indent=2),encoding="utf-8")
    metadata.update({"model":"RandomForestClassifier","selection":"Phase 2 best PR-AUC (0.171); XGBoost retained highest ROC-AUC (0.685)","features":MODEL_FEATURES,"training_rows":len(data),"seconds":time.perf_counter()-started,"random_state":42})
    (artifact_dir/"model_metadata.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    return path
