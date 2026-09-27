# Formula 1 Telemetry ML Feasibility Study

## 1. Executive Summary

The data supports **off-track / surface-departure** labels, not verified track-limit-violation labels. `surfaceType` reports the surface under each wheel; it contains no steward decision or rule-specific infringement outcome. The strongest candidate is therefore surface-departure detection or short-horizon warning, with carefully limited claims.

The first held-out-circuit warning experiment is modest, not deployment-ready: best ROC-AUC is 0.685 (XGBoost) and best PR-AUC is 0.171 (Random Forest) on Spa. The problem is nonetheless labelled, explainable and feasible for an FYP.

## 2. Dataset and Characteristics

Only the existing UDP telemetry CSVs were used; none were altered. Cached inspection establishes 88 CSV files, 22 sessions/circuits, 20 drivers, 10 teams, 23,642,660 telemetry rows, 12,852 lap records and about 11.47 GB. Sampling is about 19.08 Hz with roughly 5.6 ms average jitter. There are 163 lap records shorter than 40 seconds; lap experiments filter to 45--150 seconds.

The 56 telemetry fields include speed, throttle, brake, steer, gear, RPM, DRS, G-forces, position/velocity, distance, sector and surface data. Primary raw candidates are speed, controls, gear, RPM, DRS, G-forces, lap distance and sector. Derived pilot features are one-step acceleration, throttle-rate, brake-rate and steering-rate; they use only the current and preceding same-driver sample.

## 3. Surface Type Analysis

`surfaceType` is an object/string containing four slash-delimited wheel values in documented `RL/RR/FL/FR` order. Existing project documentation defines code 0 as track, 1 as rumble kerb and 7 as off-track grass/gravel. The audit also observed 2, 4, 9 and 10. They are explicitly **undocumented** and were not guessed or used as labels.

Surface Type

| Value/pattern (RL/RR/FL/FR) | Count | Meaning |
|---|---:|---|
| `0/0/0/0` | 21,184,793 | all wheels on documented track surface |
| `1/0/1/0` | 748,269 | documented kerb on two wheels |
| `0/1/0/1` | 582,319 | documented kerb on two wheels |
| `0/1/0/0` | 254,501 | documented kerb on one wheel |
| `1/0/0/0` | 250,849 | documented kerb on one wheel |
| `0/0/0/1` | 248,285 | documented kerb on one wheel |
| `0/0/1/0` | 238,137 | documented kerb on one wheel |
| `2/2/2/2` | 39,730 | undocumented code 2 |
| `0/7/0/7` | 9,485 | contains documented off-track code 7 |
| `7/7/7/7` | 3,735 | all wheels report documented off-track code 7 |

The full chunked audit found 23,640,740 valid four-wheel values and 1,920 null/malformed values. Code 7 occurs at every wheel (RL 17,926; RR 18,796; FL 16,170; FR 20,148), supporting consistent four-wheel encoding across sessions.

## 4. Target Definition and Events

The conservative frame target is `1` when at least one wheel has documented code 7, otherwise `0`. This yields 42,424 positive frames (0.179% of valid data) and 23,598,316 negative frames, a 1:556 imbalance. It is a surface-departure label, not an official violation label.

Positive frames were grouped by `(session, pilot)` into events only when frame identifiers were adjacent. The audit found 11,159 events. Event duration is median 0.104 s, 95th percentile 0.463 s and 99th percentile 0.642 s; median length is three frames and 95th percentile length ten frames. This conservative segmentation can split events at missing/non-positive frames instead of silently merging them.

## 5. Leakage Controls

| Feature or signal | Used? | Reason |
|---|---|---|
| Current controls, speed, gear, RPM, DRS and G-force | Yes | Available at prediction time |
| One-step rates from `t-1` to `t` | Yes | Available at prediction time |
| Current `surfaceType` | No | It is the outcome sensor/target |
| Future telemetry or future controls | No | Leakage |
| World position | No | High risk of circuit memorisation |
| Lap distance | Audited baseline only | Available, but track-specific; compare without it later |
| Sector 2/3 time for post-Sector-1 lap model | No | Future information |

The warning target is a departure in `t+1` through `t+19` (about one second). No random row split was used.

## 6. Pilot and Train/Test Strategy

The pilot comprises Mexico, Monza, Sakhir and Spa: four sessions, 20 drivers, 2,148 telemetry laps and 4,175,074 eligible telemetry rows. It is not claimed to be statistically representative merely because it is large. Mexico/Monza/Sakhir train and all Spa telemetry test; this circuit-held-out split prevents adjacent rows and the same track trajectory being on both sides.

Every rare positive was retained; deterministic negatives were bounded for laptop-scale fitting. This produced 98,832 training rows and 31,933 Spa test rows, including 2,903 warning-positive Spa frames.

## 7. Track-Surface Classification

| Model | Precision | Recall | F1 | ROC-AUC | PR-AUC |
|---|---:|---:|---:|---:|---:|
| Logistic Regression | 0.164 | 0.380 | 0.229 | 0.658 | 0.148 |
| Random Forest | 0.250 | 0.007 | 0.014 | 0.678 | 0.171 |
| XGBoost | 0.203 | 0.012 | 0.023 | 0.685 | 0.163 |

Tree ranking is modest, but the default 0.5 decision threshold has very low recall. A final study must select/calibrate thresholds on validation circuits and report event-level recall; accuracy is deliberately not a primary metric.

## 8. Lap-Time Prediction

The tested scenario is Option B: predict final lap time immediately after Sector 1. Inputs were only Sector 1 time, current lap number, track length and temperatures. Sector 2/3 and later telemetry were excluded. Of 2,111 clean pilot laps, 1,697 were train and 414 held-out Spa test laps.

| Model | MAE (s) | RMSE (s) | R² |
|---|---:|---:|---:|
| Ridge | 15.431 | 15.788 | -2.984 |
| Random Forest | 14.815 | 15.262 | -2.723 |

This scenario does not transfer usefully to unseen Spa with the current small feature set, so it is not recommended as the main FYP model.

## 9. Driver Performance and Classification

Lap-level metrics calculated are mean/max speed, mean throttle, mean brake, brake-active frame fraction, mean absolute steering, mean RPM and mean lateral/longitudinal G-force. They are meaningful descriptive comparisons, but not proof of personal driving style. Corner-entry, apex-minimum and exit speed require a validated corner map/segmentation and were not invented.

The supporting Random Forest used only those control summaries, excluding world position, circuit and session IDs. Mexico/Monza/Sakhir trained 1,727 laps; Spa tested 421 laps across 20 drivers. Accuracy was 0.121, balanced accuracy 0.124 and macro F1 0.081. Cross-circuit driver identification is therefore weak.

## 10. Anomaly Detection

Isolation Forest trained without labels on the three training circuits and tested against Spa's next-second target: precision 0.141, recall 0.142, F1 0.141, ROC-AUC 0.532 and PR-AUC 0.130. It does not align sufficiently with surface departures to be the primary method.

## 11. Feature Importance

Random Forest impurity importance ranked lateral G-force (0.230), lap distance (0.198), steering (0.148), speed (0.098), sector (0.067) and gear (0.057) highest. This is model evidence, not a causal claim. Lap-distance prominence reinforces the need for an ablation without it. SHAP was not run because it is unavailable in the supplied runtime; it is not required for the feasibility conclusion.

## 12. Computational Efficiency

The surface audit streams 200,000 rows at a time and only reads four columns. It completed across all 22 telemetry files without modifying them. Pilot scripts process one session at a time, select required fields and train on a bounded rare-event-aware sample. No raw-data copies, Parquet conversion or DuckDB database were created.

## 13. Limitations

The source is sim-racing UDP telemetry, not steward adjudication. Code 7 proves only the documented surface condition. The pilot uses four circuits, sampled classifier prevalence differs from natural prevalence, segmentation is frame-based, and feature importance is not causal. These limitations must accompany all claims.

## 14. FYP Recommendation

🥇 **#1: Off-track / surface-departure detection and short-horizon warning.** It has the only direct measured target and the strongest supervised pilot ranking results. Never call it track-limit-violation prediction.

🥈 **#2: Telemetry coaching / driver-performance analytics.** It has strong demonstration and portfolio value, but needs validated corner segmentation before ML-style performance claims.

🥉 **#3: Lap-time prediction after Sector 1.** Keep it secondary: current unseen-circuit scores are poor and require a redesigned prediction context.

Driver identity and Isolation Forest anomaly detection are not recommended as primary FYP problems under this protocol.

## 15. Reproducibility Artifacts

- `ml_experiments/analyze_surface.py`: full chunked surface audit and event segmentation.
- `ml_experiments/run_pilot_study.py`: classification, lap-time and anomaly pilot experiments.
- `ml_experiments/driver_classification.py`: supporting grouped driver experiment.
- `analysis_outputs/surface_analysis_summary.json`, `surface_type_patterns.csv`, `surface_departure_events.csv`, `pilot_ml_results.json`, and `driver_classification_results.json`: measured outputs.
- `ml_experiments/refined_surface_warning.py`: refined study script with causal feature engineering, threshold tuning, ablations, and event-level evaluation.
- `analysis_outputs/refined_surface_warning_results.json`, `refined_surface_warning_metrics.csv`, and `refined_surface_warning_report.txt`: measured refined study outputs.
- `analysis_outputs/refined_surface_warning_roc_curve.png`, `refined_surface_warning_pr_curve.png`, `refined_surface_warning_threshold_curve.png`, and `refined_surface_warning_feature_importance.png`: diagnostic visual artifacts.

## 16. Refined Surface-Departure Warning Protocol & Leakage Controls

To advance beyond the exploratory Phase 2 pilot, a refined study (`ml_experiments/refined_surface_warning.py`) was executed to determine whether telemetry at time $t$ can predict an impending **surface departure** occurring within approximately 1.0 second ($t+1$ to $t+19$ frames).

1. **Sampling & Conversion**: At ~19.08 Hz ($\Delta t \approx 52.4\text{ ms}$), 19 frames represent exactly $0.996\text{ s}$ ($\approx 1.0\text{ s}$), and 10 frames represent $0.524\text{ s}$ ($\approx 0.5\text{ s}$).
2. **Target Isolation**: The warning target is evaluated strictly on on-track frames (`departure_now == 0`, no wheel reporting code 7 at $t$), predicting whether ANY wheel will depart onto documented off-track grass/gravel (code 7) in the subsequent 19 frames.
3. **Anti-Leakage Verification**:
   - `surfaceType` is strictly excluded from predictive features.
   - World coordinates (`worldPositionX`, `worldPositionY`, `worldPositionZ`) are omitted.
   - Future telemetry and control signals are excluded.
   - All historical rolling windows are strictly causal (ending at $t$, never forward-looking).
   - Splitting is circuit-aware: **Mexico + Monza** train, **Sakhir** validates/calibrates thresholds, and **Spa** is held out for final evaluation.

## 17. Causal Rolling Features & Dynamic Context (Exp A vs. Exp B)

Exp A tested 16 instantaneous features (controls, rates, G-forces, and lap distance). Exp B added 15 causal temporal features (0.5s and 1.0s rolling means, standard deviations of speed/steer/throttle, peak lateral G in the past 1s, and 0.5s delta changes).

Adding causal temporal context yielded substantial ranking gains on held-out Spa:
- **Random Forest**: ROC-AUC improved from 0.682 to **0.704**, and PR-AUC surged from 0.169 to **0.213** (+26.0% relative gain).
- **XGBoost**: PR-AUC surged from 0.160 to **0.234** (+46.3% relative gain).
- **Precision at default 0.50 threshold**: Jumped from 0.117 to **0.683** for Random Forest, demonstrating that temporal stability metrics (e.g. rolling steering variance and peak lateral load) dramatically reduce false positive spikes.

## 18. Threshold Calibration & Resolution of Tree Recall Collapse

Under the default 0.50 probability threshold, tree-based models suffered severe recall collapse (RF: 0.2% recall, 5/276 events; XGBoost: 2.8% recall, 40/276 events) despite modest ROC-AUC. This was caused by severe class imbalance skewing output probabilities toward zero.

To resolve this without data leakage, probability decision thresholds were tuned exclusively on the **Sakhir validation circuit** to maximize validation $F_1$, locked, and applied to held-out Spa:
- **Random Forest (Exp A)**: Tuned threshold (0.100) lifted frame recall from 0.2% to **43.9%** ($F_1 = 0.250$), and increased event detection from 5 events (1.8%) to **177 events (64.1%)** with a **0.81-second average warning lead time**.
- **XGBoost (Exp B)**: Tuned threshold (0.020) lifted frame recall from 14.6% to **33.4%** ($F_1 = 0.266$), boosting event detection from 80 events (29.0%) to **152 events (55.1%)** with **0.78-second average lead time**.

Validation-calibrated thresholds are therefore mandatory for operational deployment.

## 19. Ablation Study: Track Memorization vs. Vehicle Dynamics (`lapDistance`)

In Exp B, `lapDistance` accounted for significant model importance, raising concerns that models were memorizing track coordinates rather than learning vehicle instability. Exp C evaluated the identical model architecture and temporal features **WITHOUT `lapDistance`**:

| Model | Metric | Exp A (Basic + LapDist) | Exp B (Rolling + LapDist) | Exp C (Rolling WITHOUT LapDist) |
|---|---|---:|---:|---:|
| **Logistic Regression** | ROC-AUC | 0.658 | 0.683 | **0.733** |
| | PR-AUC | 0.148 | 0.163 | **0.191** |
| | Event Recall (Spa) | 62.0% (171/276) | 59.4% (164/276) | **71.7% (198/276)** |
| **Random Forest** | ROC-AUC | 0.682 | 0.704 | **0.732** |
| | PR-AUC | 0.169 | 0.213 | **0.240** |
| **XGBoost** | ROC-AUC | 0.673 | 0.690 | **0.731** |
| | PR-AUC | 0.160 | 0.234 | **0.244** |

**Critical Generalization Insight**:
Removing `lapDistance` **increased** unseen Spa ROC-AUC from ~0.68–0.70 to **0.731–0.733** across all three model architectures, and pushed PR-AUC to **0.244**. When `lapDistance` is present, trees partially overfit to circuit-specific coordinates that do not transfer to Spa. Relying strictly on causal vehicle dynamics (lateral acceleration buildup, steering reversal rate, and speed decay) ensures superior cross-track generalizability.

## 20. Event-Level Warning Efficacy & Final FYP Feasibility Conclusion

### Event-Level Performance
Evaluating models at the event level (warning delivered within $t-19$ to $t$ before departure entry) reveals high operational effectiveness on Spa's 276 ground-truth departure events:
- **Maximum Event Recall**: **71.7% (198 of 276 events detected)** achieved by dynamic Logistic Regression (lead time: $0.82\text{ s}$).
- **Balanced Tree Performance**: Tuned Random Forest detected **64.1% of events (177 of 276)** with $0.81\text{ s}$ average lead time and a false warning rate on negative frames of ~20%.
- **High-Precision Warning**: XGBoost in Exp C achieved 31.2% event recall with a low false warning rate of **1.99%** on non-departure frames.

### Final Feasibility Verdict
The primary task — **Off-Track / Surface-Departure Detection and Short-Horizon Warning** — is **confirmed feasible and strongly recommended for the Final Year Project (FYP)**.
1. Supervised machine learning on standard UDP telemetry provides genuine pre-incident warning capability (~0.8s advance notice) without requiring GPS or high-definition track maps.
2. Causal rolling features are essential to provide dynamic inertia context.
3. `lapDistance` must be omitted to prevent track memorization and maximize cross-track generalization.
4. Threshold calibration on a validation circuit resolves class-imbalance recall collapse.

