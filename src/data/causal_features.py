"""Shared Causal Feature Engineering Module for Surface-Departure Warning.

Single source of truth for both offline model packaging and live streaming inference.
Strictly excludes:
- lapDistance
- surfaceType
- worldPositionX, worldPositionY, worldPositionZ
- future telemetry / future controls
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd

# The exact 30 Exp C features in verified order
FEATURE_NAMES_EXP_C = [
    # Basic safe raw telemetry (11 features, lapDistance excluded)
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
    # Instantaneous 1-step rates (4 features)
    "acceleration_kmh_s",
    "throttle_rate_s",
    "brake_rate_s",
    "steer_rate_s",
    # Causal rolling metrics (15 features: 10 frames ~0.5s, 19 frames ~1.0s at ~19.08 Hz)
    "speed_roll_mean_0_5s",
    "speed_roll_mean_1s",
    "speed_roll_std_1s",
    "throttle_roll_mean_0_5s",
    "throttle_roll_mean_1s",
    "throttle_roll_std_1s",
    "brake_roll_mean_0_5s",
    "brake_roll_mean_1s",
    "steer_roll_mean_0_5s",
    "steer_roll_std_1s",
    "gforce_lat_max_1s",
    "brake_max_1s",
    "throttle_change_0_5s",
    "steer_change_0_5s",
    "accel_change_0_5s",
]

# Raw fields needed to calculate Exp C features
INPUT_TELEMETRY_FIELDS = [
    "sessionTime",
    "frameIdentifier",
    "pilot_index",
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
]


def verify_feature_integrity(features: list[str]) -> bool:
    """Explicitly verify that prohibited signals are absent."""
    prohibited = ["lapdistance", "surfacetype", "worldposition", "future", "lead"]
    for f in features:
        fl = f.lower()
        for p in prohibited:
            if p in fl:
                raise ValueError(f"Prohibited signal '{p}' found in feature '{f}'!")
    if len(features) != 30:
        raise ValueError(f"Expected 30 Exp C features, got {len(features)}: {features}")
    return True


# Run integrity check at module load time
verify_feature_integrity(FEATURE_NAMES_EXP_C)


def compute_causal_features_batch(df: pd.DataFrame) -> pd.DataFrame:
    """Compute causal features over a contiguous session dataframe sorted by (pilot_index, frameIdentifier).

    Matches the exact mathematics of ml_experiments/refined_surface_warning.py.
    """
    out = df.sort_values(["pilot_index", "frameIdentifier"]).copy()
    group = out.groupby("pilot_index", sort=False)

    dt = group["sessionTime"].diff().replace(0, np.nan)

    # 1-step instantaneous rates
    out["acceleration_kmh_s"] = (group["speed"].diff() / dt).fillna(0.0)
    out["throttle_rate_s"] = (group["throttle"].diff() / dt).fillna(0.0)
    out["brake_rate_s"] = (group["brake"].diff() / dt).fillna(0.0)
    out["steer_rate_s"] = (group["steer"].diff() / dt).fillna(0.0)

    # Causal rolling features (past and present samples only)
    out["speed_roll_mean_0_5s"] = group["speed"].transform(lambda x: x.rolling(10, min_periods=1).mean())
    out["speed_roll_mean_1s"] = group["speed"].transform(lambda x: x.rolling(19, min_periods=1).mean())
    out["speed_roll_std_1s"] = group["speed"].transform(lambda x: x.rolling(19, min_periods=1).std()).fillna(0.0)

    out["throttle_roll_mean_0_5s"] = group["throttle"].transform(lambda x: x.rolling(10, min_periods=1).mean())
    out["throttle_roll_mean_1s"] = group["throttle"].transform(lambda x: x.rolling(19, min_periods=1).mean())
    out["throttle_roll_std_1s"] = group["throttle"].transform(lambda x: x.rolling(19, min_periods=1).std()).fillna(0.0)

    out["brake_roll_mean_0_5s"] = group["brake"].transform(lambda x: x.rolling(10, min_periods=1).mean())
    out["brake_roll_mean_1s"] = group["brake"].transform(lambda x: x.rolling(19, min_periods=1).mean())

    out["steer_roll_mean_0_5s"] = group["steer"].transform(lambda x: x.rolling(10, min_periods=1).mean())
    out["steer_roll_std_1s"] = group["steer"].transform(lambda x: x.rolling(19, min_periods=1).std()).fillna(0.0)

    out["gforce_lat_max_1s"] = group["gForceLateral"].transform(lambda x: x.abs().rolling(19, min_periods=1).max())
    out["brake_max_1s"] = group["brake"].transform(lambda x: x.rolling(19, min_periods=1).max())

    out["throttle_change_0_5s"] = group["throttle"].transform(lambda x: x - x.shift(10).bfill()).fillna(0.0)
    out["steer_change_0_5s"] = group["steer"].transform(lambda x: x - x.shift(10).bfill()).fillna(0.0)
    out["accel_change_0_5s"] = group["acceleration_kmh_s"].transform(lambda x: x - x.shift(10).bfill()).fillna(0.0)

    return out


def compute_causal_features_single(history: list[dict[str, Any]]) -> dict[str, float]:
    """Compute the exact 30 Exp C features for the latest frame in a FIFO history buffer.

    Parameters:
        history: list of dicts with the latest sample at history[-1], and up to 24 preceding
                 samples for the same driver. Must contain INPUT_TELEMETRY_FIELDS.

    Returns:
        dict mapping feature_name -> float value for the 30 Exp C features.
    """
    if not history:
        raise ValueError("History buffer cannot be empty.")

    curr = history[-1]
    n = len(history)

    # 1-step instantaneous rates
    if n >= 2:
        prev = history[-2]
        dt = float(curr["sessionTime"]) - float(prev["sessionTime"])
        if dt <= 0:
            dt = 0.0524  # Fallback to ~19.08 Hz frame time
        accel = (float(curr["speed"]) - float(prev["speed"])) / dt
        throttle_rate = (float(curr["throttle"]) - float(prev["throttle"])) / dt
        brake_rate = (float(curr["brake"]) - float(prev["brake"])) / dt
        steer_rate = (float(curr["steer"]) - float(prev["steer"])) / dt
    else:
        accel = 0.0
        throttle_rate = 0.0
        brake_rate = 0.0
        steer_rate = 0.0

    # Extract sequences for rolling calculations
    speeds = [float(h["speed"]) for h in history]
    throttles = [float(h["throttle"]) for h in history]
    brakes = [float(h["brake"]) for h in history]
    steers = [float(h["steer"]) for h in history]
    lat_gs = [abs(float(h["gForceLateral"])) for h in history]

    # Windows: last 10 samples (~0.5s) and last 19 samples (~1.0s)
    w10_speeds = speeds[-10:]
    w19_speeds = speeds[-19:]
    w10_throttles = throttles[-10:]
    w19_throttles = throttles[-19:]
    w10_brakes = brakes[-10:]
    w19_brakes = brakes[-19:]
    w10_steers = steers[-10:]
    w19_steers = steers[-19:]
    w19_lat_gs = lat_gs[-19:]

    speed_roll_mean_0_5s = float(np.mean(w10_speeds))
    speed_roll_mean_1s = float(np.mean(w19_speeds))
    speed_roll_std_1s = float(np.std(w19_speeds, ddof=1)) if len(w19_speeds) > 1 else 0.0

    throttle_roll_mean_0_5s = float(np.mean(w10_throttles))
    throttle_roll_mean_1s = float(np.mean(w19_throttles))
    throttle_roll_std_1s = float(np.std(w19_throttles, ddof=1)) if len(w19_throttles) > 1 else 0.0

    brake_roll_mean_0_5s = float(np.mean(w10_brakes))
    brake_roll_mean_1s = float(np.mean(w19_brakes))

    steer_roll_mean_0_5s = float(np.mean(w10_steers))
    steer_roll_std_1s = float(np.std(w19_steers, ddof=1)) if len(w19_steers) > 1 else 0.0

    gforce_lat_max_1s = float(np.max(w19_lat_gs))
    brake_max_1s = float(np.max(w19_brakes))

    # 10-sample delta changes (val_t - val_{t-10})
    ref_idx = max(0, n - 11)  # 10 steps back
    ref_frame = history[ref_idx]
    throttle_change_0_5s = float(curr["throttle"]) - float(ref_frame["throttle"])
    steer_change_0_5s = float(curr["steer"]) - float(ref_frame["steer"])

    # Accel change requires ref accel
    if ref_idx >= 1:
        dt_ref = float(ref_frame["sessionTime"]) - float(history[ref_idx - 1]["sessionTime"])
        dt_ref = dt_ref if dt_ref > 0 else 0.0524
        ref_accel = (float(ref_frame["speed"]) - float(history[ref_idx - 1]["speed"])) / dt_ref
    else:
        ref_accel = accel
    accel_change_0_5s = accel - ref_accel

    # Return exactly the 30 features
    return {
        "speed": float(curr["speed"]),
        "throttle": float(curr["throttle"]),
        "brake": float(curr["brake"]),
        "steer": float(curr["steer"]),
        "gear": float(curr["gear"]),
        "engineRPM": float(curr["engineRPM"]),
        "drs": float(curr["drs"]),
        "gForceLateral": float(curr["gForceLateral"]),
        "gForceLongitudinal": float(curr["gForceLongitudinal"]),
        "gForceVertical": float(curr["gForceVertical"]),
        "sector": float(curr["sector"]),
        "acceleration_kmh_s": accel,
        "throttle_rate_s": throttle_rate,
        "brake_rate_s": brake_rate,
        "steer_rate_s": steer_rate,
        "speed_roll_mean_0_5s": speed_roll_mean_0_5s,
        "speed_roll_mean_1s": speed_roll_mean_1s,
        "speed_roll_std_1s": speed_roll_std_1s if not np.isnan(speed_roll_std_1s) else 0.0,
        "throttle_roll_mean_0_5s": throttle_roll_mean_0_5s,
        "throttle_roll_mean_1s": throttle_roll_mean_1s,
        "throttle_roll_std_1s": throttle_roll_std_1s if not np.isnan(throttle_roll_std_1s) else 0.0,
        "brake_roll_mean_0_5s": brake_roll_mean_0_5s,
        "brake_roll_mean_1s": brake_roll_mean_1s,
        "steer_roll_mean_0_5s": steer_roll_mean_0_5s,
        "steer_roll_std_1s": steer_roll_std_1s if not np.isnan(steer_roll_std_1s) else 0.0,
        "gforce_lat_max_1s": gforce_lat_max_1s,
        "brake_max_1s": brake_max_1s,
        "throttle_change_0_5s": throttle_change_0_5s,
        "steer_change_0_5s": steer_change_0_5s,
        "accel_change_0_5s": accel_change_0_5s,
    }
