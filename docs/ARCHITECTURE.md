# Production Architecture

```text
Raw CSV (read-only)
        ↓
Selective chunk reader
        ↓
Feature engineering (current and prior frame only)
        ↓
Random Forest production model
        ↓
Frame probabilities
        ↓
Adjacent-frame event detection
        ↓
Lap, driver, circuit and location-zone analytics
        ↓
Future visualization/API layer
```

`src/data/schema.py` is the single feature and input contract. `features.py` builds prediction-safe fields; `events.py` turns positive frame probabilities into events; `analytics.py` provides stable aggregate tables. `src/model/build_training_data.py` and `train.py` create versioned model artifacts. `src/pipeline.py` is the CLI boundary and writes only derived outputs.

## Future application contract

The future API/UI supplies `session_id`, optionally `driver` and `lap`; it receives telemetry summary, probability timeline, surface-departure events, event locations/zones, driver metrics and lap metrics. It must consume the CSV outputs produced by `src.pipeline`, never raw telemetry CSV columns.

## Feature contract

The full feature catalogue (source, calculation, units, availability and leakage risk) is in `src/data/schema.py` as `FEATURE_CATALOG`. No feature depends on a future row. `surfaceType` is excluded from model features and only constructs offline training labels.
