"""Chunked full-dataset audit of the wheel-level surface telemetry."""
from __future__ import annotations

import argparse
import json
from collections import Counter

import pandas as pd

from utils import DOCUMENTED_SURFACE_CODES, OUTPUT, parse_surface, session_catalog, telemetry_path


def audit_surface(chunk_size: int = 200_000) -> dict:
    raw_counts, wheel_counts = Counter(), [Counter() for _ in range(4)]
    total_rows = valid_rows = positives = malformed = 0
    events, active, session_rows = [], {}, []
    for _, session in session_catalog().iterrows():
        sid, circuit = str(session.session_id), str(session.trackId)
        session_total = session_positive = 0
        for chunk in pd.read_csv(telemetry_path(sid), usecols=["pilot_index", "frameIdentifier", "sessionTime", "surfaceType"], chunksize=chunk_size):
            total_rows += len(chunk); session_total += len(chunk)
            surface = chunk["surfaceType"].astype("string")
            parts = surface.str.split("/", expand=True)
            valid = surface.notna() & (parts.shape[1] == 4) & parts.notna().all(axis=1)
            valid_rows += int(valid.sum()); malformed += int((~valid).sum())
            raw_counts.update(surface[valid].value_counts(dropna=True).to_dict())
            for index in range(4): wheel_counts[index].update(parts.loc[valid, index].value_counts(dropna=True).to_dict())
            departure = surface.str.contains(r"(?:^|/)7(?:/|$)", regex=True, na=False)
            positive = chunk.loc[departure, ["pilot_index", "frameIdentifier", "sessionTime"]]
            positives += len(positive); session_positive += len(positive)
            # Only positive rows are iterated; at this class prevalence that is far
            # smaller than the dataset, while the raw scan remains fully chunked.
            for row in positive.itertuples(index=False):
                pilot, frame, stamp = int(row.pilot_index), int(row.frameIdentifier), float(row.sessionTime)
                key, previous = (sid, pilot), active.get((sid, pilot))
                # Frame identifiers are consecutive in this capture.  A normal
                # frame must end an event, so only exactly adjacent positives join.
                if previous and frame <= previous["end_frame"] + 1:
                    previous.update(end_frame=frame, end_time=stamp, frames=previous["frames"] + 1)
                else:
                    if previous: events.append(previous)
                    active[key] = {"session_id": sid, "circuit": circuit, "pilot_index": pilot, "start_frame": frame, "end_frame": frame, "start_time": stamp, "end_time": stamp, "frames": 1}
        session_rows.append({"session_id": sid, "circuit": circuit, "rows": session_total, "positive_frames": session_positive})
    events.extend(active.values())
    event_df = pd.DataFrame(events)
    if not event_df.empty: event_df["duration_seconds"] = (event_df.end_time - event_df.start_time).clip(lower=0)
    unknown = sorted({code for x in wheel_counts for code in x if code not in DOCUMENTED_SURFACE_CODES}, key=int)
    return {"total_rows": total_rows, "valid_surface_rows": valid_rows, "malformed_or_null_rows": malformed, "positive_frames": positives, "negative_frames": valid_rows - positives, "raw_counts": dict(raw_counts), "wheel_counts": [dict(x) for x in wheel_counts], "unknown_codes": unknown, "sessions": session_rows, "events": event_df}


def write_outputs(result: dict) -> None:
    OUTPUT.mkdir(exist_ok=True)
    denominator = result["valid_surface_rows"]
    patterns = []
    for pattern, count in sorted(result["raw_counts"].items(), key=lambda x: (-x[1], x[0])):
        meaning = "contains documented off-track code 7" if "7" in parse_surface(pattern) else "no documented off-track code 7"
        patterns.append({"value_pattern_rl_rr_fl_fr": pattern, "count": count, "percentage": count / denominator * 100, "meaning": meaning})
    pd.DataFrame(patterns).to_csv(OUTPUT / "surface_type_patterns.csv", index=False)
    result["events"].to_csv(OUTPUT / "surface_departure_events.csv", index=False)
    with open(OUTPUT / "surface_analysis_summary.json", "w", encoding="utf-8") as handle:
        json.dump({k: v for k, v in result.items() if k != "events"}, handle, indent=2)
    print("Surface Type\n" + "-" * 72 + "\nValue/Pattern | Count | Meaning")
    for row in patterns[:20]: print(f"{row['value_pattern_rl_rr_fl_fr']} | {row['count']:,} | {row['meaning']}")
    events = result["events"]
    print(f"\nValid frames: {denominator:,}; positive frames: {result['positive_frames']:,}; events: {len(events):,}")
    if len(events): print("Duration seconds (min/median/p95/max): " + ", ".join(f"{x:.3f}" for x in events.duration_seconds.quantile([0, .5, .95, 1]).tolist()))
    print("Undocumented observed codes (not labels): " + ", ".join(result["unknown_codes"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--chunk-size", type=int, default=200_000)
    write_outputs(audit_surface(parser.parse_args().chunk_size))
