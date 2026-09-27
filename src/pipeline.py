"""CLI production pipeline; default runs only the named session, never raw-data writes."""
from __future__ import annotations
import argparse, json, time, tracemalloc
from pathlib import Path
import pandas as pd
from src.data.analytics import circuit_analytics, driver_analytics, lap_analytics, location_density
from src.data.events import segment_events
from src.data.features import add_features
from src.data.schema import CHUNK_SIZE, MODEL_FEATURES, REQUIRED_COLUMNS

ROOT=Path(__file__).resolve().parents[1]
def run_session(session_id: str, model_path: Path, output: Path, threshold=.5):
    import joblib
    started=time.perf_counter(); tracemalloc.start(); feature_seconds=inference_seconds=0.; output.mkdir(parents=True,exist_ok=True); model=joblib.load(model_path)
    session=pd.read_csv(ROOT/f"SessionData_{session_id}.csv").iloc[0]; roster=pd.read_csv(ROOT/f"ParticipantData_{session_id}.csv",usecols=["pilot_index","driverId"]).rename(columns={"driverId":"driver"}); state={}; parts=[]
    for chunk in pd.read_csv(ROOT/f"TelemetryData_{session_id}.csv",usecols=REQUIRED_COLUMNS,chunksize=CHUNK_SIZE):
        tick=time.perf_counter(); frame,state=add_features(chunk,state); feature_seconds+=time.perf_counter()-tick; frame[MODEL_FEATURES]=frame[MODEL_FEATURES].replace([float("inf"),float("-inf")],float("nan")); tick=time.perf_counter(); frame["probability"]=model.predict_proba(frame[MODEL_FEATURES])[:,1]; inference_seconds+=time.perf_counter()-tick; parts.append(frame)
    data=pd.concat(parts,ignore_index=True).merge(roster,on="pilot_index",how="left"); data["session_id"],data["circuit"]=session_id,session.trackId
    events=segment_events(data,threshold); laps=lap_analytics(data,events); drivers=driver_analytics(laps); circuits=circuit_analytics(laps); zones=location_density(events)
    for name,item in [("events",events),("laps",laps),("drivers",drivers),("circuits",circuits),("event_zones",zones)]: item.to_csv(output/f"{name}.csv",index=False)
    # Stable future-UI contract: selected derived fields, never raw wheel surface labels.
    data[["session_id","circuit","pilot_index","driver","currentLapNum","frameIdentifier","sessionTime","probability","speed","throttle","brake","worldPositionX","worldPositionY","worldPositionZ"]].to_csv(output/"prediction_timeline.csv",index=False)
    _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
    (output/"run_metadata.json").write_text(json.dumps({"session_id":session_id,"circuit":session.trackId,"telemetry_rows":len(data),"total_seconds":time.perf_counter()-started,"feature_seconds":feature_seconds,"inference_seconds":inference_seconds,"python_tracemalloc_peak_bytes":peak,"threshold":threshold},indent=2),encoding="utf-8")
if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("session_id"); p.add_argument("--model",default="artifacts/surface_departure_random_forest.joblib"); p.add_argument("--output",default="production_outputs"); p.add_argument("--threshold",type=float,default=.5); a=p.parse_args(); run_session(a.session_id,Path(a.model),Path(a.output)/a.session_id,a.threshold)
