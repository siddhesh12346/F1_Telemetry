from __future__ import annotations
import numpy as np
import pandas as pd
from .schema import DERIVED_FEATURES, RAW_FEATURES, TARGET_HORIZON_FRAMES

def departure_label(surface: pd.Series) -> pd.Series:
    """Documented code 7 only; this is not an FIA track-limit label."""
    return surface.astype("string").str.contains(r"(?:^|/)7(?:/|$)", regex=True, na=False).astype("int8")

def add_features(frame: pd.DataFrame, previous: dict | None = None) -> tuple[pd.DataFrame, dict]:
    previous = {} if previous is None else previous.copy(); out = frame.sort_values(["pilot_index", "frameIdentifier"]).copy()
    for pilot, index in out.groupby("pilot_index", sort=False).groups.items():
        rows = out.loc[index]; prior = previous.get(int(pilot)); base = rows[["sessionTime", "speed", "throttle", "brake", "steer"]]
        if prior is not None: base = pd.concat([pd.DataFrame([prior]), base], ignore_index=True)
        dt = base.sessionTime.diff().replace(0, np.nan)
        for raw, derived in [("speed","acceleration_kmh_s"),("throttle","throttle_rate_s"),("brake","brake_rate_s"),("steer","steer_rate_s")]:
            values = (base[raw].diff() / dt).iloc[-len(rows):].to_numpy(); out.loc[index, derived] = values
        previous[int(pilot)] = rows[["sessionTime", "speed", "throttle", "brake", "steer"]].iloc[-1].to_dict()
    return out, previous

def future_warning_target(frame: pd.DataFrame, horizon: int = TARGET_HORIZON_FRAMES) -> pd.Series:
    """For offline training only: any documented departure in next 19 frames."""
    ordered = frame.sort_values(["pilot_index", "frameIdentifier"]).copy(); now = departure_label(ordered.surfaceType)
    future = now.groupby(ordered.pilot_index).transform(lambda x: x.iloc[::-1].rolling(horizon, min_periods=horizon).max().iloc[::-1]).groupby(ordered.pilot_index).shift(-1).fillna(0).astype("int8")
    return future.reindex(frame.index).fillna(0).astype("int8")
