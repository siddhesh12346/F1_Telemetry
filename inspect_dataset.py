import os
import glob
import json
import time
import numpy as np
import pandas as pd

def make_json_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [make_json_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return make_json_serializable(obj.tolist())
    elif pd.isna(obj):
        return None
    else:
        return obj

def inspect_files(directory="."):
    csv_files = glob.glob(os.path.join(directory, "*.csv"))
    print(f"Found {len(csv_files)} CSV files in {directory}")
    
    metadata = {}
    
    # Global tracking sets
    all_drivers = set()
    all_constructors = set()
    all_tracks = set()
    all_weather = set()
    
    # Lap-time tracking lists
    all_laps = []
    
    # Telemetry tracking lists
    total_telemetry_rows = 0
    all_frequencies = []
    frequency_stds = []
    
    start_time = time.time()
    
    for idx, filepath in enumerate(sorted(csv_files), 1):
        filename = os.path.basename(filepath)
        size_bytes = os.path.getsize(filepath)
        
        # Determine category and session ID
        if "_" in filename:
            category, session_ext = filename.split("_", 1)
            session_id = session_ext.replace(".csv", "")
        else:
            category = "Other"
            session_id = "Unknown"
            
        print(f"[{idx}/{len(csv_files)}] Processing {filename} ({size_bytes / (1024*1024):.2f} MB)...")
        file_start = time.time()
        
        try:
            if category == "TelemetryData":
                # Chunked reading to avoid memory issues (TelemetryData is large)
                chunk_size = 200000
                rows = 0
                cols = 0
                column_names = []
                dtypes = {}
                null_counts = {}
                
                # We read the first chunk to get metadata
                first_chunk = True
                for chunk in pd.read_csv(filepath, chunksize=chunk_size):
                    rows += chunk.shape[0]
                    if first_chunk:
                        cols = chunk.shape[1]
                        column_names = list(chunk.columns)
                        dtypes = {col: str(dtype) for col, dtype in zip(chunk.columns, chunk.dtypes)}
                        null_counts = {col: 0 for col in chunk.columns}
                        first_chunk = False
                    
                    for col in chunk.columns:
                        null_counts[col] += int(chunk[col].isnull().sum())
                
                # Check duplicates and calculate frequency on ID columns only (highly efficient)
                df_ids = pd.read_csv(filepath, usecols=["pilot_index", "frameIdentifier", "sessionTime"])
                
                # Duplicates check on identifiers: (pilot_index, frameIdentifier)
                duplicate_count = int(df_ids.duplicated(subset=["pilot_index", "frameIdentifier"]).sum())
                
                # Frequency analysis: calculate sampling rate using pilot_index = 0 (or first available)
                freq_info = {}
                if len(df_ids) > 0:
                    pilots = df_ids["pilot_index"].unique()
                    if len(pilots) > 0:
                        sample_pilot = pilots[0]
                        pilot_df = df_ids[df_ids["pilot_index"] == sample_pilot].sort_values("sessionTime")
                        
                        if len(pilot_df) > 1:
                            time_diffs = pilot_df["sessionTime"].diff().dropna()
                            # Filter out negative differences or zero differences if they are anomalies
                            time_diffs = time_diffs[time_diffs > 0]
                            
                            if len(time_diffs) > 0:
                                mean_diff = float(time_diffs.mean())
                                std_diff = float(time_diffs.std())
                                min_diff = float(time_diffs.min())
                                max_diff = float(time_diffs.max())
                                sampling_hz = 1.0 / mean_diff if mean_diff > 0 else 0
                                
                                freq_info = {
                                    "mean_diff_seconds": mean_diff,
                                    "std_diff_seconds": std_diff,
                                    "min_diff_seconds": min_diff,
                                    "max_diff_seconds": max_diff,
                                    "sampling_hz": sampling_hz,
                                    "constant_sampling": std_diff < 0.005 # very low variance indicates constant rate
                                }
                                all_frequencies.append(sampling_hz)
                                frequency_stds.append(std_diff)
                
                total_telemetry_rows += rows
                
                metadata[filename] = {
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "category": category,
                    "session_id": session_id,
                    "rows": rows,
                    "columns": cols,
                    "column_names": column_names,
                    "dtypes": dtypes,
                    "null_counts": null_counts,
                    "duplicate_count": duplicate_count,
                    "telemetry_frequency": freq_info,
                    "sheets": 1,
                    "sheet_names": ["Sheet1"]
                }
                
            else:
                # Small files can be read fully
                df = pd.read_csv(filepath)
                rows, cols = df.shape
                column_names = list(df.columns)
                dtypes = {col: str(dtype) for col, dtype in zip(df.columns, df.dtypes)}
                null_counts = {col: int(val) for col, val in zip(df.columns, df.isnull().sum())}
                duplicate_count = int(df.duplicated().sum())
                
                # Category-specific processing
                if category == "ParticipantData":
                    if "driverId" in df.columns:
                        all_drivers.update(df["driverId"].dropna().unique())
                    if "teamId" in df.columns:
                        all_constructors.update(df["teamId"].dropna().unique())
                        
                elif category == "SessionData":
                    if "trackId" in df.columns:
                        all_tracks.update(df["trackId"].dropna().unique())
                    if "weather" in df.columns:
                        all_weather.update(df["weather"].dropna().unique())
                        
                elif category == "RaceTimeData":
                    # Collect valid lap times
                    if "LapTime" in df.columns:
                        # filter out zero lap times as they represent incomplete/invalid laps
                        valid_laps = df[df["LapTime"] > 10.0]["LapTime"].tolist()
                        all_laps.extend(valid_laps)
                
                sample_data = df.head(3).to_dict(orient="records")
                
                metadata[filename] = {
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "category": category,
                    "session_id": session_id,
                    "rows": rows,
                    "columns": cols,
                    "column_names": column_names,
                    "dtypes": dtypes,
                    "null_counts": null_counts,
                    "duplicate_count": duplicate_count,
                    "sample_data": sample_data,
                    "sheets": 1,
                    "sheet_names": ["Sheet1"]
                }
                
            file_time = time.time() - file_start
            print(f"    Done: {rows} rows, {cols} cols, duplicates={duplicate_count} in {file_time:.2f}s")
            
        except Exception as e:
            print(f"    Error processing {filename}: {str(e)}")
            metadata[filename] = {
                "filename": filename,
                "size_bytes": size_bytes,
                "category": category,
                "session_id": session_id,
                "error": str(e)
            }
            
    total_time = time.time() - start_time
    print(f"Processed all files in {total_time:.2f} seconds.")
    
    # Calculate lap statistics
    lap_stats = {}
    if len(all_laps) > 0:
        lap_stats = {
            "total_laps_recorded": len(all_laps),
            "fastest_lap_seconds": float(np.min(all_laps)),
            "average_lap_seconds": float(np.mean(all_laps)),
            "slowest_lap_seconds": float(np.max(all_laps)),
            "lap_time_std_seconds": float(np.std(all_laps)),
            "lap_time_iqr_seconds": float(np.percentile(all_laps, 75) - np.percentile(all_laps, 25))
        }
    
    # Calculate global frequency statistics
    avg_hz = float(np.mean(all_frequencies)) if len(all_frequencies) > 0 else 0.0
    avg_std = float(np.mean(frequency_stds)) if len(frequency_stds) > 0 else 0.0
    
    # Construct global stats summary
    global_stats = {
        "total_files": len(csv_files),
        "total_size_bytes": sum(os.path.getsize(f) for f in csv_files),
        "session_ids": list(set(m["session_id"] for m in metadata.values() if "session_id" in m)),
        "unique_drivers": sorted(list(all_drivers)),
        "unique_constructors": sorted(list(all_constructors)),
        "unique_tracks": sorted(list(all_tracks)),
        "unique_weather": sorted(list(all_weather)),
        "total_laps_completed_records": len(all_laps),
        "total_telemetry_rows": total_telemetry_rows,
        "average_telemetry_hz": avg_hz,
        "average_telemetry_jitter_seconds": avg_std,
        "lap_stats": lap_stats,
        "process_time_seconds": total_time
    }
    
    output = {
        "global_stats": global_stats,
        "files": metadata
    }
    
    # Ensure standard Python types for JSON
    serializable_output = make_json_serializable(output)
    
    with open("metadata_cache.json", "w") as f:
        json.dump(serializable_output, f, indent=2)
    print("Saved metadata to metadata_cache.json")

if __name__ == "__main__":
    inspect_files(".")
