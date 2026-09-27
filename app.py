"""FastAPI Backend for Formula 1 Surface Departure Warning Application.

Provides REST endpoints for session catalog, replay state, model status, research benchmark metrics,
and session logging & driver analysis, along with a high-throughput WebSocket stream (/ws/telemetry).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.data.causal_features import FEATURE_NAMES_EXP_C, verify_feature_integrity
from src.data.replay import TelemetryReplaySession
from src.data.session_catalog import (
    get_all_sessions,
    get_session_drivers,
    get_session_laps,
    get_track_polyline,
)
from src.data.session_logger import (
    LOGS_DIR,
    get_log_detail,
    get_log_event_timeline,
    list_saved_logs,
    session_logger,
)
from src.model.inference import DEFAULT_MODEL_DIR, SurfaceWarningPredictor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("f1_warning_app")

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"

app = FastAPI(
    title="F1 Surface-Departure Warning System",
    description="Real-time causal ML prediction, sequential telemetry replay, and session logging.",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize shared singleton predictor
predictor = SurfaceWarningPredictor(model_dir=DEFAULT_MODEL_DIR, threshold=0.50)


# Replay State Manager
class ReplayController:
    def __init__(self):
        self.session_id: str = "4048657932346004126"  # Default: Spa
        self.pilot_index: int = 0
        self.lap_number: Optional[int] = None
        self.speed: float = 1.0
        self.is_playing: bool = False
        self.replay_session: Optional[TelemetryReplaySession] = None
        self._lock = asyncio.Lock()
        self._init_session()

    def _init_session(self) -> None:
        try:
            self.replay_session = TelemetryReplaySession(
                session_id=self.session_id,
                pilot_index=self.pilot_index,
                lap_number=self.lap_number,
                predictor=predictor,
            )
            logger.info(
                f"Loaded replay session {self.session_id} (pilot {self.pilot_index}): {self.replay_session.total_frames} frames"
            )
        except Exception as e:
            logger.error(f"Failed to initialize replay session {self.session_id}: {e}")
            self.replay_session = None

    async def configure(
        self,
        session_id: str,
        pilot_index: int = 0,
        lap_number: Optional[int] = None,
        speed: float = 1.0,
    ) -> dict[str, Any]:
        async with self._lock:
            self.session_id = str(session_id)
            self.pilot_index = int(pilot_index)
            self.lap_number = int(lap_number) if lap_number is not None else None
            self.speed = max(0.5, min(float(speed), 5.0))
            self.is_playing = False
            self._init_session()
            return self.get_state()

    def get_state(self) -> dict[str, Any]:
        total = self.replay_session.total_frames if self.replay_session else 0
        current = self.replay_session.current_frame_index if self.replay_session else 0
        return {
            "session_id": self.session_id,
            "pilot_index": self.pilot_index,
            "lap_number": self.lap_number,
            "speed": self.speed,
            "is_playing": self.is_playing,
            "current_frame": current,
            "total_frames": total,
            "logging": session_logger.is_logging,
            "log_status": session_logger.get_status(),
        }

    async def set_playing(self, play: bool) -> None:
        async with self._lock:
            self.is_playing = play

    async def seek(self, frame_index: int) -> dict[str, Any]:
        async with self._lock:
            if self.replay_session:
                self.replay_session.seek(frame_index)
            return self.get_state()

    async def set_speed(self, speed: float) -> None:
        async with self._lock:
            self.speed = max(0.5, min(float(speed), 5.0))


replay_ctrl = ReplayController()


def _get_circuit_name(session_id: str) -> str:
    """Helper to lookup circuit name from session ID."""
    for s in get_all_sessions():
        if s["session_id"] == session_id:
            return s["circuit"]
    return "Unknown Circuit"


# --- Pydantic Request Models ---
class ReplayConfigRequest(BaseModel):
    session_id: str
    pilot_index: int = 0
    lap_number: Optional[int] = None
    speed: float = 1.0


class ReplayControlRequest(BaseModel):
    action: str  # "play", "pause", "reset", "seek", "speed"
    frame_index: Optional[int] = None
    speed: Optional[float] = None


# --- Core System REST Endpoints ---
@app.get("/api/status")
async def get_system_status() -> dict[str, Any]:
    """Return model runtime status, feature validation, and threshold configuration."""
    verify_feature_integrity(predictor.features)
    return {
        "status": "online",
        "model_type": predictor.metadata.get("model_type", "XGBClassifier"),
        "experiment": predictor.metadata.get("experiment", "Exp C (No LapDist)"),
        "feature_count": len(predictor.features),
        "threshold": predictor.threshold,
        "features": predictor.features,
        "packaged_at": predictor.metadata.get("packaged_at", "N/A"),
    }


@app.get("/api/research/benchmark")
async def get_research_benchmark() -> dict[str, Any]:
    """Return frozen research benchmark results on held-out Spa."""
    return {
        "benchmark_circuit": "Spa",
        "session_id": "4048657932346004126",
        "training_circuits": ["Mexico", "Monza", "Sakhir"],
        "frozen_metrics": {
            "roc_auc": 0.73095,
            "pr_auc": 0.24385,
            "precision": 0.42815,
            "recall": 0.14881,
            "f1": 0.22086,
            "event_recall": 0.3116,
            "events_detected": 86,
            "total_events": 276,
            "mean_lead_seconds": 0.729,
            "false_warning_rate": 0.0199,
        },
        "clarification_note": (
            "The mean lead time of ~0.729 s is an offline evaluation statistic on detected events "
            "in held-out Spa, NOT a guaranteed real-time advance-warning interval for every live frame. "
            "Warnings occur dynamically whenever the calibrated probability exceeds the 0.50 threshold."
        ),
    }


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    """Return all discovered F1 sessions."""
    return get_all_sessions()


@app.get("/api/sessions/{session_id}/drivers")
async def get_drivers(session_id: str) -> list[dict[str, Any]]:
    """Return driver roster for a given session."""
    drivers = get_session_drivers(session_id)
    if not drivers:
        raise HTTPException(status_code=404, detail="No driver data found for session.")
    return drivers


@app.get("/api/sessions/{session_id}/laps")
async def get_laps(session_id: str, pilot_index: Optional[int] = None) -> list[dict[str, Any]]:
    """Return lap timing records for a given session."""
    return get_session_laps(session_id, pilot_index)


@app.get("/api/sessions/{session_id}/trackmap")
async def get_trackmap(session_id: str) -> dict[str, Any]:
    """Return normalized 2D circuit coordinates strictly for map visualization."""
    data = get_track_polyline(session_id)
    if not data.get("points"):
        raise HTTPException(status_code=404, detail="Track geometry not available for session.")
    return data


@app.get("/api/replay/state")
async def get_replay_state() -> dict[str, Any]:
    """Return current replay playback state."""
    return replay_ctrl.get_state()


@app.post("/api/replay/config")
async def configure_replay(req: ReplayConfigRequest) -> dict[str, Any]:
    """Change active session, pilot, lap, and speed."""
    state = await replay_ctrl.configure(
        session_id=req.session_id,
        pilot_index=req.pilot_index,
        lap_number=req.lap_number,
        speed=req.speed,
    )
    return state


@app.post("/api/replay/control")
async def control_replay(req: ReplayControlRequest) -> dict[str, Any]:
    """Handle play, pause, reset, seek, and speed change."""
    action = req.action.lower()
    if action == "play":
        await replay_ctrl.set_playing(True)
    elif action == "pause":
        await replay_ctrl.set_playing(False)
    elif action == "reset":
        await replay_ctrl.set_playing(False)
        await replay_ctrl.seek(0)
    elif action == "seek":
        if req.frame_index is not None:
            await replay_ctrl.seek(req.frame_index)
    elif action == "speed":
        if req.speed is not None:
            await replay_ctrl.set_speed(req.speed)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

    return replay_ctrl.get_state()


# --- Session Logging & Driver Analysis REST Endpoints ---
@app.post("/api/log/start")
async def start_logging_endpoint() -> dict[str, Any]:
    """Start active telemetry and prediction logging for the current replay session."""
    circuit = _get_circuit_name(replay_ctrl.session_id)
    log_id = session_logger.start_logging(
        session_id=replay_ctrl.session_id,
        circuit=circuit,
        pilot_index=replay_ctrl.pilot_index,
        lap_number=replay_ctrl.lap_number,
    )
    return {
        "status": "started",
        "log_id": log_id,
        "state": session_logger.get_status(),
    }


@app.post("/api/log/stop")
async def stop_logging_endpoint() -> dict[str, Any]:
    """Stop active logging, finalize event analysis, and serialize files to logs/."""
    saved = session_logger.stop_logging()
    if not saved:
        return {"status": "not_logging", "saved": None}
    return {
        "status": "stopped",
        "saved": saved,
    }


@app.get("/api/log/status")
async def get_log_status_endpoint() -> dict[str, Any]:
    """Return active logging state, duration, and frame count."""
    return session_logger.get_status()


@app.get("/api/logs")
async def get_saved_logs_endpoint() -> list[dict[str, Any]]:
    """Return all saved session logs sorted newest first."""
    return list_saved_logs(LOGS_DIR)


@app.get("/api/logs/{log_id}")
async def get_log_detail_endpoint(log_id: str) -> dict[str, Any]:
    """Return full session metadata, driver analysis summary, and detected events."""
    detail = get_log_detail(log_id, LOGS_DIR)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Log '{log_id}' not found.")
    return detail


@app.get("/api/logs/{log_id}/events")
async def get_log_events_endpoint(log_id: str) -> list[dict[str, Any]]:
    """Return detected CAUTION and WARNING events with preceding condition reports."""
    detail = get_log_detail(log_id, LOGS_DIR)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Log '{log_id}' not found.")
    return detail.get("events", [])


@app.get("/api/logs/{log_id}/telemetry")
async def get_log_telemetry_endpoint(
    log_id: str, limit: int = 2000, offset: int = 0
) -> dict[str, Any]:
    """Return recorded frame-by-frame telemetry rows with pagination."""
    target_file = LOGS_DIR / log_id / "telemetry.csv"
    if not target_file.exists():
        raise HTTPException(status_code=404, detail="Telemetry CSV not found.")

    df = pd.read_csv(target_file)
    total_rows = len(df)
    slice_df = df.iloc[offset : offset + limit]

    return {
        "log_id": log_id,
        "total_rows": total_rows,
        "limit": limit,
        "offset": offset,
        "rows": slice_df.to_dict(orient="records"),
    }


@app.get("/api/logs/{log_id}/event_timeline/{event_index}")
async def get_event_timeline_endpoint(
    log_id: str,
    event_index: int,
    pre_sec: float = 1.0,
    post_sec: float = 0.5,
) -> dict[str, Any]:
    """Extract a window of frames (-pre_sec to +post_sec) around an event for visualization."""
    data = get_log_event_timeline(
        log_id=log_id,
        event_index=event_index,
        pre_sec=pre_sec,
        post_sec=post_sec,
        logs_dir=LOGS_DIR,
    )
    if not data:
        raise HTTPException(status_code=404, detail="Event timeline data not found.")
    return data


@app.get("/api/logs/{log_id}/export/{file_type}")
async def export_log_file_endpoint(log_id: str, file_type: str):
    """Download session.json, events.json, or telemetry.csv."""
    target_dir = LOGS_DIR / log_id
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="Log not found.")

    if file_type == "csv":
        p = target_dir / "telemetry.csv"
        media = "text/csv"
        fn = f"{log_id}_telemetry.csv"
    elif file_type == "events_json":
        p = target_dir / "events.json"
        media = "application/json"
        fn = f"{log_id}_events.json"
    elif file_type == "session_json":
        p = target_dir / "session.json"
        media = "application/json"
        fn = f"{log_id}_session.json"
    else:
        raise HTTPException(status_code=400, detail=f"Invalid export file_type '{file_type}'.")

    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Export file '{p.name}' missing.")
    return FileResponse(path=str(p), media_type=media, filename=fn)


# --- WebSocket Streaming Endpoint ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


ws_manager = ConnectionManager()


@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """Bi-directional WebSocket streaming live telemetry, predictions, and logging state."""
    await ws_manager.connect(websocket)
    # Send initial state
    await websocket.send_json({
        "type": "state",
        "data": replay_ctrl.get_state(),
        "logging": session_logger.is_logging,
        "log_id": session_logger.log_id,
        "log_status": session_logger.get_status(),
    })

    try:
        while True:
            # Check for incoming client commands (non-blocking with short timeout)
            try:
                msg_text = await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
                data = json.loads(msg_text)
                cmd = data.get("command")

                if cmd == "play":
                    await replay_ctrl.set_playing(True)
                elif cmd == "pause":
                    await replay_ctrl.set_playing(False)
                elif cmd == "seek":
                    idx = int(data.get("frame_index", 0))
                    await replay_ctrl.seek(idx)
                elif cmd == "set_speed":
                    spd = float(data.get("speed", 1.0))
                    await replay_ctrl.set_speed(spd)
                elif cmd == "set_session":
                    sid = str(data.get("session_id", replay_ctrl.session_id))
                    pid = int(data.get("pilot_index", 0))
                    lap = data.get("lap_number")
                    await replay_ctrl.configure(sid, pid, lap, replay_ctrl.speed)
                elif cmd == "start_log":
                    circuit = _get_circuit_name(replay_ctrl.session_id)
                    session_logger.start_logging(
                        session_id=replay_ctrl.session_id,
                        circuit=circuit,
                        pilot_index=replay_ctrl.pilot_index,
                        lap_number=replay_ctrl.lap_number,
                    )
                elif cmd == "stop_log":
                    session_logger.stop_logging()

                await websocket.send_json({
                    "type": "state",
                    "data": replay_ctrl.get_state(),
                    "logging": session_logger.is_logging,
                    "log_id": session_logger.log_id,
                    "log_status": session_logger.get_status(),
                })
            except asyncio.TimeoutError:
                pass

            # If playing, stream next frame
            if replay_ctrl.is_playing and replay_ctrl.replay_session:
                frame = replay_ctrl.replay_session.next_frame()
                if frame is not None:
                    # Feed sequential frame into SessionLogger if active
                    if session_logger.is_logging:
                        session_logger.log_frame(frame)

                    # Broadcast frame along with current logging metadata
                    await websocket.send_json({
                        "type": "telemetry",
                        "data": frame,
                        "logging": session_logger.is_logging,
                        "log_id": session_logger.log_id,
                        "log_status": session_logger.get_status(),
                    })
                else:
                    # End of session reached: auto-finalize log safely
                    if session_logger.is_logging:
                        session_logger.stop_logging()

                    await replay_ctrl.set_playing(False)
                    await websocket.send_json({
                        "type": "end_of_session",
                        "data": replay_ctrl.get_state(),
                        "logging": False,
                        "log_status": session_logger.get_status(),
                    })

            # Base tick rate is ~52ms (19.08 Hz telemetry stream) adjusted by speed
            base_delay = 0.0524 / max(0.5, replay_ctrl.speed)
            await asyncio.sleep(base_delay)

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        if len(ws_manager.active_connections) == 0:
            replay_ctrl.is_playing = False
    except Exception as e:
        logger.warning(f"WebSocket client error: {e}")
        ws_manager.disconnect(websocket)
        if len(ws_manager.active_connections) == 0:
            replay_ctrl.is_playing = False


# --- Serve Static Web Assets ---
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
