"""Shared, read-only utilities for the ML feasibility study."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "analysis_outputs"

# The codebook is exactly what DATASET_ANALYSIS.md documents.  Other observed
# codes are reported as undocumented, never guessed or used as labels.
DOCUMENTED_SURFACE_CODES = {
    "0": "track surface",
    "1": "rumble kerb",
    "7": "off-track surface (grass/gravel in dataset documentation)",
}


def session_catalog(root: Path = ROOT) -> pd.DataFrame:
    rows = []
    for path in sorted(root.glob("SessionData_*.csv")):
        row = pd.read_csv(path).iloc[0].to_dict()
        row.update(session_id=path.stem.split("_", 1)[1], session_file=path.name)
        rows.append(row)
    return pd.DataFrame(rows)


def telemetry_path(session_id: str, root: Path = ROOT) -> Path:
    return root / f"TelemetryData_{session_id}.csv"


def parse_surface(value: object) -> tuple[str, str, str, str] | None:
    if pd.isna(value):
        return None
    parts = tuple(str(value).split("/"))
    return parts if len(parts) == 4 else None


def is_departure(value: object) -> bool:
    parts = parse_surface(value)
    return parts is not None and "7" in parts


def load_metadata(root: Path = ROOT) -> dict:
    with open(root / "metadata_cache.json", encoding="utf-8") as handle:
        return json.load(handle)
