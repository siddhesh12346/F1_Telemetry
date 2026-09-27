from __future__ import annotations
import pandas as pd

def segment_events(predictions: pd.DataFrame, threshold: float = .5) -> pd.DataFrame:
    """Adjacent positive frames per session/pilot become one event."""
    required = {"session_id","circuit","pilot_index","frameIdentifier","sessionTime","probability"}
    missing = required - set(predictions); assert not missing, f"missing event fields: {missing}"
    data = predictions[predictions.probability.ge(threshold)].sort_values(["session_id","pilot_index","frameIdentifier"])
    events = []
    for (session, pilot), part in data.groupby(["session_id","pilot_index"], sort=False):
        run = []
        for row in part.itertuples(index=False):
            if run and row.frameIdentifier != run[-1].frameIdentifier + 1:
                events.append(_summarise(run)) ; run = []
            run.append(row)
        if run: events.append(_summarise(run))
    return pd.DataFrame(events)

def _summarise(run):
    first, last = run[0], run[-1]
    return {"session_id":first.session_id,"circuit":first.circuit,"pilot_index":first.pilot_index,"driver":getattr(first,"driver",None),"lap":getattr(first,"currentLapNum",None),"start_frame":first.frameIdentifier,"end_frame":last.frameIdentifier,"start_timestamp":first.sessionTime,"end_timestamp":last.sessionTime,"duration_seconds":max(0,last.sessionTime-first.sessionTime),"frame_count":len(run),"peak_speed":max(getattr(x,"speed",float("nan")) for x in run),"mean_throttle":sum(getattr(x,"throttle",0) for x in run)/len(run),"mean_brake":sum(getattr(x,"brake",0) for x in run)/len(run),"location_x":getattr(first,"worldPositionX",None),"location_y":getattr(first,"worldPositionY",None),"location_z":getattr(first,"worldPositionZ",None),"model_confidence":max(x.probability for x in run)}
