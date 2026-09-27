# Phase 2 Frozen Baseline

This document freezes, rather than replaces, the measured research result in `ML_FEASIBILITY_REPORT.md` and `analysis_outputs/pilot_ml_results.json`.

- Dataset: 88 CSV files; 22 sessions; 20 drivers; 23,642,660 telemetry rows; 12,852 laps; approximately 11.47 GB; about 19.08 Hz.
- Target: **Off-Track / Surface Departure**. A positive is any four-wheel `surfaceType` value containing the documented code `7`; it is not an FIA/steward track-limit violation.
- Counts: 42,424 positive frames and 11,159 adjacent-frame events; 0.179% positive frame rate.
- Features: speed, throttle, brake, steer, gear, RPM, DRS, G-force, lap distance, sector and one-step rates. Surface type was target-only; coordinates were excluded from the primary classifier.
- Split: train Mexico/Monza/Sakhir, test Spa. No random adjacent-frame split.
- Leakage controls: no future telemetry, no target sensor input, no post-event features. The warning target was departure during next 1--19 frames.
- Results: Logistic Regression ROC/PR-AUC 0.658/0.148; Random Forest 0.678/0.171; XGBoost 0.685/0.163. Lap-time and driver classification did not generalise well.
- Limitations: simulation source, code 7 is not adjudication, four-circuit pilot, severe imbalance, and frame-based event segmentation.

The selected direction is **F1 Off-Track / Surface-Departure Detection and Telemetry Intelligence System** because it has the direct, explainable label and the strongest measured supervised result. Phase 3 does not overwrite these artifacts.
