from __future__ import annotations
import numpy as np
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from src.data.events import segment_events

def frame_metrics(y, p, threshold=.5):
    pred=(np.asarray(p)>=threshold).astype(int)
    return {"roc_auc":float(roc_auc_score(y,p)),"pr_auc":float(average_precision_score(y,p)),"precision":float(precision_score(y,p,zero_division=0)),"recall":float(recall_score(y,p,zero_division=0)),"f1":float(f1_score(y,p,zero_division=0)),"confusion_matrix":confusion_matrix(y,pred).tolist(),"threshold":threshold}

def event_metrics(predictions, truth_events, threshold=.5):
    predicted=segment_events(predictions,threshold); matched=set()
    for p in predicted.itertuples(index=False):
        candidates=truth_events[(truth_events.session_id==p.session_id)&(truth_events.pilot_index==p.pilot_index)&(truth_events.start_frame<=p.end_frame)&(truth_events.end_frame>=p.start_frame)]
        matched.update(candidates.index.tolist())
    precision=len(matched)/len(predicted) if len(predicted) else 0.; recall=len(matched)/len(truth_events) if len(truth_events) else 0.
    return {"predicted_events":len(predicted),"true_events":len(truth_events),"matched_true_events":len(matched),"event_precision":precision,"event_recall":recall}
