# Phase 3 Report: Production Data and ML Pipeline

## 1. Objective and Architecture

Phase 3 turns the frozen Phase 2 research direction into a read-only production pipeline for **Off-Track / Surface Departure** intelligence. The architecture is documented in `ARCHITECTURE.md`; no frontend, authentication or deployment is included.

## 2. Data and Feature Pipeline

`src/pipeline.py` reads only required columns in 200,000-row chunks. It retains only per-driver previous state for rate calculations, uses the schema catalogue, and never edits source CSVs. Raw telemetry and derived rate features are formally separated in `src/data/schema.py`.

## 3. Model Integration and Explainability

The production baseline is Random Forest, chosen from frozen results because PR-AUC 0.171 was highest for the rare-event task; XGBoost's ROC-AUC 0.685 remains the highest ROC ranking result. The model saves as Joblib with model metadata, feature list, random seed, training sessions and sampling configuration. Random-Forest importances are available through the saved estimator; SHAP remains optional and was not fabricated.

## 4. Events and Analytics

Adjacent positive prediction frames are aggregated per session/driver. Events contain identifiers, lap, timing, duration, peak speed, mean throttle/brake, starting X/Y/Z location and confidence. Lap analytics exposes averages, maxima, brake/steer/throttle behaviour, event counts and telemetry missing values. Driver and circuit aggregations expose rates, totals and event density. Short laps are retained in telemetry analytics; timing-model filters are documented separately and never silently delete raw data.

## 5. Evaluation and Testing

`src/model/evaluate.py` distinguishes frame metrics (ROC-AUC, PR-AUC, precision, recall, F1 and matrix) from overlapping event metrics. `tests/test_pipeline.py` uses synthetic data for code-7 target construction, previous-frame features, look-ahead target construction, event segmentation and schema/leakage prevention.

## 6. Performance and Limitations

The production pipeline is chunked and selective. A Mexico validation run processed 1,180,640 telemetry rows in 19.20 s: feature extraction 2.37 s and model inference 2.66 s. Python `tracemalloc` peak was 1,301,490,782 bytes; this includes the session-level derived frame table used to generate the future visualization timeline, rather than the raw 11.47 GB corpus. The trained model took 5.70 s for 98,832 sampled training rows. Run metadata is written with each execution. Main limitations remain the frozen Phase 2 limitations: simulation telemetry, indirect label, imbalance, location dependence and no steward adjudication.

## 7. Future Web Application

The next phase can expose the derived CSV/API contract: session/driver/lap input, with telemetry summaries, prediction timelines, events, zones and analytics output. It should not access the raw files directly.
