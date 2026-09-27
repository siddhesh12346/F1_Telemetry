from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd
from src.data.features import add_features, departure_label, future_warning_target
from src.data.schema import REQUIRED_COLUMNS
from src.model.train import train_random_forest

ROOT=Path(__file__).resolve().parents[2]
def build(circuits=("Mexico","Monza","Sakhir"), negative_ratio=10):
    sessions=[]; manifest=[]
    for path in sorted(ROOT.glob("SessionData_*.csv")):
        meta=pd.read_csv(path).iloc[0]; sid=path.stem.split("_",1)[1]
        if meta.trackId not in circuits: continue
        # Training is session-bounded (not whole-dataset), selectively loaded in
        # chunks.  A single session is retained only because the future label needs
        # a 19-frame look-ahead; the 11.47 GB corpus is never resident at once.
        chunks=pd.read_csv(ROOT/f"TelemetryData_{sid}.csv",usecols=REQUIRED_COLUMNS,chunksize=200_000)
        data=pd.concat(chunks,ignore_index=True).sort_values(["pilot_index","frameIdentifier"])
        data,_=add_features(data); data["target_departure_next_1s"]=future_warning_target(data); data=data[departure_label(data.surfaceType).eq(0)]
        positive=data[data.target_departure_next_1s.eq(1)]; negative=data[data.target_departure_next_1s.eq(0)]
        take=min(len(negative),max(20_000,len(positive)*negative_ratio)); sessions.append(pd.concat([positive,negative.sample(take,random_state=42)])); manifest.append({"session_id":sid,"circuit":meta.trackId,"eligible_rows":len(data),"positive_rows":len(positive),"sampled_negative_rows":take})
    return pd.concat(sessions,ignore_index=True),manifest
if __name__=="__main__":
 p=argparse.ArgumentParser(); p.add_argument("--artifacts",default="artifacts"); a=p.parse_args(); data,manifest=build(); path=train_random_forest(data,ROOT/a.artifacts,{"train_circuits":["Mexico","Monza","Sakhir"],"target":"documented code 7 in next 1..19 frames","horizon_frames":19,"negative_sampling_ratio":10,"sessions":manifest}); print(path)
