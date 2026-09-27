import unittest
import pandas as pd
from src.data.events import segment_events
from src.data.features import add_features, departure_label, future_warning_target
from src.data.schema import MODEL_FEATURES

class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.data=pd.DataFrame({"pilot_index":[0]*5,"frameIdentifier":[1,2,3,4,5],"sessionTime":[0,.05,.10,.15,.20],"surfaceType":["0/0/0/0","0/0/0/0","7/0/0/0","7/0/0/0","0/0/0/0"],"speed":[1,2,3,4,5],"throttle":[0,.1,.2,.3,.4],"brake":[0]*5,"steer":[0]*5})
 def test_documented_target_only(self): self.assertEqual(departure_label(pd.Series(["0/0/0/0","2/2/2/2","0/7/0/0"])).tolist(),[0,0,1])
 def test_no_future_feature(self):
  frame,_=add_features(self.data); self.assertTrue(pd.isna(frame.acceleration_kmh_s.iloc[0])); self.assertEqual(frame.acceleration_kmh_s.iloc[1],20.)
 def test_target_looks_ahead(self): self.assertEqual(future_warning_target(self.data,horizon=2).tolist(),[1,1,1,0,0])
 def test_event_segmentation(self):
  d=self.data.assign(session_id="s",circuit="c",probability=[0,.9,.8,0,.9]); events=segment_events(d,.5); self.assertEqual(len(events),2); self.assertEqual(events.frame_count.tolist(),[2,1])
 def test_model_schema_has_no_target_or_surface(self): self.assertNotIn("surfaceType",MODEL_FEATURES); self.assertNotIn("target_departure_next_1s",MODEL_FEATURES)
 def test_missing_values_are_preserved_for_model_imputation(self):
  data=self.data.copy(); data.loc[2,"speed"]=float("nan"); frame,_=add_features(data); self.assertTrue(pd.isna(frame.speed.iloc[2]))
if __name__=="__main__": unittest.main()
