"""Stable production schema: do not expose raw CSV fields to future clients."""
RAW_FEATURES = ["speed", "throttle", "brake", "steer", "gear", "engineRPM", "drs", "gForceLateral", "gForceLongitudinal", "gForceVertical", "lapDistance", "sector"]
DERIVED_FEATURES = ["acceleration_kmh_s", "throttle_rate_s", "brake_rate_s", "steer_rate_s"]
MODEL_FEATURES = RAW_FEATURES + DERIVED_FEATURES
REQUIRED_COLUMNS = ["sessionTime", "frameIdentifier", "pilot_index", "currentLapNum", "surfaceType", "worldPositionX", "worldPositionY", "worldPositionZ"] + RAW_FEATURES
TARGET_HORIZON_FRAMES = 19
CHUNK_SIZE = 200_000

FEATURE_CATALOG = [
 {"name":"speed","source":"speed","calculation":"raw","units":"km/h","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"throttle","source":"throttle","calculation":"raw","units":"0-1","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"brake","source":"brake","calculation":"raw","units":"0-1","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"steer","source":"steer","calculation":"raw","units":"-1 to 1","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"gear","source":"gear","calculation":"raw","units":"gear","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"engineRPM","source":"engineRPM","calculation":"raw","units":"rpm","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"drs","source":"drs","calculation":"raw","units":"binary","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"gForceLateral","source":"gForceLateral","calculation":"raw","units":"g","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"gForceLongitudinal","source":"gForceLongitudinal","calculation":"raw","units":"g","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"gForceVertical","source":"gForceVertical","calculation":"raw","units":"g","available_at_prediction":True,"leakage_risk":"none"},
 {"name":"lapDistance","source":"lapDistance","calculation":"raw","units":"m","available_at_prediction":True,"leakage_risk":"track-location dependence; no coordinates used"},
 {"name":"sector","source":"sector","calculation":"raw","units":"category","available_at_prediction":True,"leakage_risk":"none"},
 *[{"name":n,"source":b+" and sessionTime","calculation":"difference from immediately previous same-driver frame / elapsed seconds","units":"per second","available_at_prediction":True,"leakage_risk":"none; no future rows"} for b,n in [("speed","acceleration_kmh_s"),("throttle","throttle_rate_s"),("brake","brake_rate_s"),("steer","steer_rate_s")]],
]
