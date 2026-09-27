from __future__ import annotations
import pandas as pd

def lap_analytics(telemetry: pd.DataFrame, events: pd.DataFrame | None = None) -> pd.DataFrame:
    data = telemetry.copy(); data["brake_active"] = data.brake.gt(.05); data["abs_steer"] = data.steer.abs()
    keys = ["session_id","circuit","pilot_index","currentLapNum"]
    result = data.groupby(keys, as_index=False).agg(telemetry_points=("frameIdentifier","size"), average_speed=("speed","mean"), maximum_speed=("speed","max"), mean_throttle=("throttle","mean"), mean_brake=("brake","mean"), brake_frame_fraction=("brake_active","mean"), mean_abs_steer=("abs_steer","mean"), telemetry_missing_values=("speed",lambda x:int(x.isna().sum())))
    if events is not None and not events.empty:
        counts = events.groupby(["session_id","circuit","pilot_index","lap"], as_index=False).size().rename(columns={"lap":"currentLapNum","size":"surface_departure_events"})
        result = result.merge(counts, on=keys, how="left")
    return result.fillna({"surface_departure_events":0})

def driver_analytics(laps: pd.DataFrame) -> pd.DataFrame:
    return laps.groupby(["session_id","circuit","pilot_index"], as_index=False).agg(laps=("currentLapNum","nunique"), average_speed=("average_speed","mean"), maximum_speed=("maximum_speed","max"), braking_fraction=("brake_frame_fraction","mean"), throttle=("mean_throttle","mean"), steering=("mean_abs_steer","mean"), surface_departure_events=("surface_departure_events","sum")).assign(surface_departure_event_rate=lambda x:x.surface_departure_events/x.laps.clip(lower=1))

def circuit_analytics(laps: pd.DataFrame) -> pd.DataFrame:
    return laps.groupby("circuit", as_index=False).agg(sessions=("session_id","nunique"), drivers=("pilot_index","nunique"), laps=("currentLapNum","nunique"), telemetry_points=("telemetry_points","sum"), average_speed=("average_speed","mean"), surface_departure_events=("surface_departure_events","sum")).assign(event_density_per_1000_points=lambda x:1000*x.surface_departure_events/x.telemetry_points.clip(lower=1))

def location_density(events: pd.DataFrame, grid_metres: float = 50.) -> pd.DataFrame:
    data = events.dropna(subset=["location_x","location_z"]).copy(); data["grid_x"]=(data.location_x/grid_metres).round().astype(int); data["grid_z"]=(data.location_z/grid_metres).round().astype(int)
    return data.groupby(["circuit","grid_x","grid_z"],as_index=False).agg(event_count=("start_frame","size"), mean_speed=("peak_speed","mean"), mean_confidence=("model_confidence","mean"))
