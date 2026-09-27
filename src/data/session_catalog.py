"""Session Catalog and Track Map Coordinates Provider.

Dynamically discovers all 22 Formula 1 sessions, parses driver rosters and lap metadata,
and extracts normalized 2D track polylines for visualization (isolated from ML features).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def get_all_sessions() -> list[dict[str, Any]]:
    """Dynamically discover all session CSV files and return catalog."""
    sessions = []
    for path in sorted(ROOT.glob("SessionData_*.csv")):
        sid = path.stem.split("_", 1)[1]
        try:
            row = pd.read_csv(path).iloc[0].to_dict()
        except Exception:
            continue
        sessions.append({
            "session_id": str(sid),
            "circuit": str(row.get("trackId", "Unknown")),
            "track_length_m": float(row.get("trackLength", 5000.0)),
            "air_temp_c": float(row.get("airTemperature", 25.0)),
            "track_temp_c": float(row.get("trackTemperature", 30.0)),
        })
    return sessions


def get_session_drivers(session_id: str) -> list[dict[str, Any]]:
    """Return driver roster for a given session."""
    p_path = ROOT / f"ParticipantData_{session_id}.csv"
    if not p_path.exists():
        return []
    df = pd.read_csv(p_path)
    drivers = []
    for _, row in df.iterrows():
        drivers.append({
            "pilot_index": int(row["pilot_index"]),
            "driver_name": str(row.get("driverId", f"Driver {row['pilot_index']}")),
            "team": str(row.get("teamId", "Unknown Team")),
            "car_number": int(row.get("raceNumber", row["pilot_index"] + 1)),
        })
    return drivers


def get_session_laps(session_id: str, pilot_index: int | None = None) -> list[dict[str, Any]]:
    """Return available lap records for a session from RaceTimeData."""
    r_path = ROOT / f"RaceTimeData_{session_id}.csv"
    if not r_path.exists():
        return []
    df = pd.read_csv(r_path)
    if pilot_index is not None and "pilot_index" in df.columns:
        df = df[df["pilot_index"].eq(pilot_index)]

    laps = []
    for _, row in df.iterrows():
        laps.append({
            "pilot_index": int(row.get("pilot_index", 0)),
            "lap_number": int(row.get("currentLapNum", row.get("Lap", 1))),
            "lap_time": float(row.get("LapTime", 0.0)),
            "sector1_time": float(row.get("sector1TimeInMS", 0.0)) / 1000.0 if "sector1TimeInMS" in row else 0.0,
            "sector2_time": float(row.get("sector2TimeInMS", 0.0)) / 1000.0 if "sector2TimeInMS" in row else 0.0,
            "sector3_time": float(row.get("sector3TimeInMS", 0.0)) / 1000.0 if "sector3TimeInMS" in row else 0.0,
        })
    return laps


def get_track_polyline(session_id: str, sample_points: int = 600) -> dict[str, Any]:
    """Extract downsampled, normalized (X, Z) track coordinates for 2D canvas rendering.

    Note: World coordinates are strictly isolated for UI visualization and NEVER enter ML inference.
    """
    telemetry_path = ROOT / f"TelemetryData_{session_id}.csv"
    if not telemetry_path.exists():
        return {"points": [], "bounds": {}}

    # Read first 100,000 rows to extract one clean lap of positions
    usecols = ["pilot_index", "currentLapNum", "worldPositionX", "worldPositionZ", "speed"]
    chunks = []
    with pd.read_csv(telemetry_path, usecols=usecols, chunksize=100_000) as reader:
        for chunk in reader:
            chunks.append(chunk)
            if len(chunks) * 100_000 >= 200_000:
                break

    df = pd.concat(chunks, ignore_index=True)
    # Pick pilot with the most rows in this slice
    pilot = df["pilot_index"].value_counts().index[0]
    p_df = df[df["pilot_index"].eq(pilot)].dropna(subset=["worldPositionX", "worldPositionZ"])

    # Pick a lap that has a good number of points
    lap_counts = p_df["currentLapNum"].value_counts()
    valid_laps = lap_counts[lap_counts > 1000]
    if not valid_laps.empty:
        target_lap = valid_laps.index[0]
        lap_df = p_df[p_df["currentLapNum"].eq(target_lap)]
    else:
        lap_df = p_df.iloc[:2500]

    # Downsample
    step = max(1, len(lap_df) // sample_points)
    sampled = lap_df.iloc[::step].copy()

    xs = sampled["worldPositionX"].tolist()
    zs = sampled["worldPositionZ"].tolist()

    if not xs:
        return {"points": [], "bounds": {}}

    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    span_x = max(1.0, max_x - min_x)
    span_z = max(1.0, max_z - min_z)

    # Normalize to 0..1000 range preserving aspect ratio
    scale = 800.0 / max(span_x, span_z)
    points = []
    for x, z in zip(xs, zs):
        px = (x - min_x) * scale + 100.0
        pz = (z - min_z) * scale + 100.0
        points.append({"x": round(px, 1), "y": round(pz, 1), "raw_x": round(x, 2), "raw_z": round(z, 2)})

    return {
        "session_id": session_id,
        "point_count": len(points),
        "points": points,
        "bounds": {"min_x": min_x, "max_x": max_x, "min_z": min_z, "max_z": max_z},
    }
