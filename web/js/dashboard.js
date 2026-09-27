/**
 * Main Application Dashboard Coordinator
 * Manages WebSocket telemetry stream, cockpit gauges, circuit track map,
 * rolling probability chart, and Session Logging & Driver Analysis.
 */
class TelemetryDashboard {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.gauges = new CockpitGauges();
    this.trackmap = new TrackMapRenderer("trackmap-canvas");
    this.chart = new ProbabilityChart("prob-chart-canvas", 60);

    // Replay State
    this.isPlaying = false;
    this.currentFrame = 0;
    this.totalFrames = 0;
    this.currentSpeed = 1.0;
    this.selectedSessionId = "4048657932346004126"; // Spa default
    this.selectedPilot = 0;
    this.selectedLap = null;

    // Logging State
    this.isLogging = false;
    this.activeLogId = null;

    // UI Elements - Navigation & Replay
    this.connStatus = document.getElementById("connection-status");
    this.btnPlay = document.getElementById("btn-play");
    this.iconPlay = document.getElementById("icon-play");
    this.iconPause = document.getElementById("icon-pause");
    this.playText = document.getElementById("play-text");
    this.btnReset = document.getElementById("btn-reset");
    this.scrubber = document.getElementById("replay-scrubber");
    this.lblFrame = document.getElementById("lbl-frame");
    this.lblTotalFrames = document.getElementById("lbl-total-frames");
    this.lblTime = document.getElementById("lbl-time");
    this.sectorEl = document.getElementById("val-sector");
    this.lapEl = document.getElementById("val-lap");
    this.circuitTag = document.getElementById("circuit-name-tag");

    this.selectSession = document.getElementById("select-session");
    this.selectDriver = document.getElementById("select-driver");
    this.selectLap = document.getElementById("select-lap");

    // UI Elements - LOG Control
    this.btnLog = document.getElementById("btn-log");
    this.logText = document.getElementById("log-text");
    this.logLiveStats = document.getElementById("log-live-stats");
    this.logTimer = document.getElementById("log-timer");
    this.logFrameCount = document.getElementById("log-frame-count");

    // UI Elements - Modals
    this.modalBenchmarks = document.getElementById("modal-benchmarks");
    this.btnOpenBenchmarks = document.getElementById("btn-open-benchmarks");
    this.btnCloseBenchmarks = document.getElementById("btn-close-modal");
    this.featureTagsList = document.getElementById("feature-tags-list");

    this.modalLogs = document.getElementById("modal-logs");
    this.btnOpenLogs = document.getElementById("btn-open-logs");
    this.btnCloseLogs = document.getElementById("btn-close-logs");
    this.btnRefreshLogs = document.getElementById("btn-refresh-logs");
    this.savedLogsList = document.getElementById("saved-logs-list");
    this.logDetailContent = document.getElementById("log-detail-content");

    this.bindEvents();
    this.initApp();
  }

  async initApp() {
    await this.loadSessions();
    await this.loadTrackMap(this.selectedSessionId);
    await this.loadDrivers(this.selectedSessionId);
    await this.loadLaps(this.selectedSessionId, this.selectedPilot);
    this.initWebSocket();
  }

  bindEvents() {
    // Play / Pause
    this.btnPlay.addEventListener("click", () => this.togglePlay());

    // Reset
    this.btnReset.addEventListener("click", () => {
      this.sendWsCommand({ command: "seek", frame_index: 0 });
      this.chart.reset();
    });

    // Scrubber
    this.scrubber.addEventListener("input", (e) => {
      const targetFrame = parseInt(e.target.value, 10);
      this.sendWsCommand({ command: "seek", frame_index: targetFrame });
    });

    // Speed Controls
    document.querySelectorAll(".btn-speed").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        document.querySelectorAll(".btn-speed").forEach((b) => b.classList.remove("active"));
        e.target.classList.add("active");
        const speed = parseFloat(e.target.dataset.speed);
        this.currentSpeed = speed;
        this.sendWsCommand({ command: "set_speed", speed: speed });
      });
    });

    // LOG Button
    this.btnLog.addEventListener("click", () => this.toggleLogging());

    // Selectors
    this.selectSession.addEventListener("change", async (e) => {
      this.selectedSessionId = e.target.value;
      const circuitName = e.target.selectedOptions[0]?.dataset?.circuit || "F1 CIRCUIT";
      if (this.circuitTag) this.circuitTag.textContent = circuitName.toUpperCase();
      await this.loadTrackMap(this.selectedSessionId);
      await this.loadDrivers(this.selectedSessionId);
      await this.loadLaps(this.selectedSessionId, this.selectedPilot);
      this.applySessionConfig();
    });

    this.selectDriver.addEventListener("change", async (e) => {
      this.selectedPilot = parseInt(e.target.value, 10);
      await this.loadLaps(this.selectedSessionId, this.selectedPilot);
      this.applySessionConfig();
    });

    this.selectLap.addEventListener("change", (e) => {
      const val = e.target.value;
      this.selectedLap = val === "" ? null : parseInt(val, 10);
      this.applySessionConfig();
    });

    // Benchmark Modal
    this.btnOpenBenchmarks.addEventListener("click", () => this.openBenchmarksModal());
    this.btnCloseBenchmarks.addEventListener("click", () => this.closeBenchmarksModal());
    this.modalBenchmarks.querySelector(".modal-backdrop").addEventListener("click", () => this.closeBenchmarksModal());

    // Session Logs Modal
    this.btnOpenLogs.addEventListener("click", () => this.openLogsModal());
    this.btnCloseLogs.addEventListener("click", () => this.closeLogsModal());
    this.btnRefreshLogs.addEventListener("click", () => this.loadSavedLogs());
    this.modalLogs.querySelector(".modal-backdrop").addEventListener("click", () => this.closeLogsModal());
  }

  // --- Session & Track Discovery ---
  async loadSessions() {
    try {
      const res = await fetch("/api/sessions");
      const sessions = await res.json();
      this.selectSession.innerHTML = "";
      sessions.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = s.session_id;
        opt.dataset.circuit = s.circuit;
        opt.textContent = `${s.circuit} (${s.session_id.slice(0, 8)}...)`;
        if (s.session_id === this.selectedSessionId) {
          opt.selected = true;
          if (this.circuitTag) this.circuitTag.textContent = s.circuit.toUpperCase();
        }
        this.selectSession.appendChild(opt);
      });
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  }

  async loadDrivers(sessionId) {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/drivers`);
      const drivers = await res.json();
      this.selectDriver.innerHTML = "";
      drivers.forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d.pilot_index;
        opt.textContent = `#${d.car_number} ${d.driver_name} (${d.team})`;
        if (d.pilot_index === this.selectedPilot) opt.selected = true;
        this.selectDriver.appendChild(opt);
      });
    } catch (err) {
      console.error("Failed to load drivers:", err);
    }
  }

  async loadLaps(sessionId, pilotIndex) {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/laps?pilot_index=${pilotIndex}`);
      const laps = await res.json();
      this.selectLap.innerHTML = '<option value="">Full Session</option>';
      const uniqueLaps = [...new Set(laps.map((l) => l.lap_number))].sort((a, b) => a - b);
      uniqueLaps.forEach((lapNum) => {
        const opt = document.createElement("option");
        opt.value = lapNum;
        opt.textContent = `Lap ${lapNum}`;
        this.selectLap.appendChild(opt);
      });
    } catch (err) {
      console.error("Failed to load laps:", err);
    }
  }

  async loadTrackMap(sessionId) {
    try {
      const res = await fetch(`/api/sessions/${sessionId}/trackmap`);
      if (res.ok) {
        const trackData = await res.json();
        this.trackmap.setTrackData(trackData);
      }
    } catch (err) {
      console.error("Failed to load track map:", err);
    }
  }

  applySessionConfig() {
    this.sendWsCommand({
      command: "set_session",
      session_id: this.selectedSessionId,
      pilot_index: this.selectedPilot,
      lap_number: this.selectedLap,
    });
    this.chart.reset();
  }

  // --- WebSocket Communications ---
  initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.setConnected(true);
      if (this.reconnectTimer) {
        clearInterval(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleWsMessage(msg);
      } catch (e) {
        console.error("Malformed WebSocket message:", e);
      }
    };

    this.ws.onclose = () => {
      this.setConnected(false);
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.warn("WebSocket error:", err);
      this.setConnected(false);
    };
  }

  scheduleReconnect() {
    if (!this.reconnectTimer) {
      this.reconnectTimer = setInterval(() => {
        this.initWebSocket();
      }, 2000);
    }
  }

  setConnected(connected) {
    if (this.connStatus) {
      if (connected) {
        this.connStatus.className = "status-pill online";
        this.connStatus.querySelector(".status-text").textContent = "LIVE WS ONLINE";
      } else {
        this.connStatus.className = "status-pill offline";
        this.connStatus.querySelector(".status-text").textContent = "DISCONNECTED";
      }
    }
  }

  sendWsCommand(cmdObj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(cmdObj));
    }
  }

  togglePlay() {
    if (this.isPlaying) {
      this.sendWsCommand({ command: "pause" });
    } else {
      this.sendWsCommand({ command: "play" });
    }
  }

  toggleLogging() {
    if (this.isLogging) {
      this.sendWsCommand({ command: "stop_log" });
      fetch("/api/log/stop", { method: "POST" }).catch(() => {});
    } else {
      this.sendWsCommand({ command: "start_log" });
      fetch("/api/log/start", { method: "POST" }).catch(() => {});
    }
  }

  setPlayUiState(playing) {
    this.isPlaying = playing;
    if (playing) {
      this.iconPlay.classList.add("hidden");
      this.iconPause.classList.remove("hidden");
      this.playText.textContent = "PAUSE";
      this.btnPlay.className = "btn btn-secondary";
    } else {
      this.iconPlay.classList.remove("hidden");
      this.iconPause.classList.add("hidden");
      this.playText.textContent = "PLAY";
      this.btnPlay.className = "btn btn-primary";
    }
  }

  updateLoggingUi(isLogging, status) {
    this.isLogging = Boolean(isLogging);
    if (this.isLogging) {
      this.btnLog.classList.add("active");
      this.logText.textContent = "LOGGING";
      this.logLiveStats.classList.remove("hidden");

      if (status) {
        const sec = status.duration_seconds || 0;
        const mins = Math.floor(sec / 60);
        const remSec = (sec % 60).toFixed(1);
        const minStr = String(mins).padStart(2, "0");
        const secStr = String(remSec).padStart(4, "0");
        this.logTimer.textContent = `${minStr}:${secStr}`;
        this.logFrameCount.textContent = `${(status.frames_recorded || 0).toLocaleString()} frames`;
      }
    } else {
      this.btnLog.classList.remove("active");
      this.logText.textContent = "LOG";
      this.logLiveStats.classList.add("hidden");
    }
  }

  handleWsMessage(msg) {
    // 1. Check logging status
    if (msg.logging !== undefined) {
      this.updateLoggingUi(msg.logging, msg.log_status);
    }

    // 2. Process message types
    if (msg.type === "state") {
      const s = msg.data;
      this.setPlayUiState(s.is_playing);
      this.totalFrames = s.total_frames;
      this.currentFrame = s.current_frame;
      this.scrubber.max = Math.max(0, s.total_frames - 1);
      this.scrubber.value = s.current_frame;
      if (this.lblTotalFrames) this.lblTotalFrames.textContent = s.total_frames;
      if (this.lblFrame) this.lblFrame.textContent = s.current_frame;

      if (s.logging !== undefined) {
        this.updateLoggingUi(s.logging, s.log_status);
      }
    } else if (msg.type === "telemetry") {
      const f = msg.data;
      this.currentFrame = f.index;
      this.totalFrames = f.total_frames;

      // Update Scrubber & Timeline labels
      this.scrubber.value = f.index;
      this.scrubber.max = Math.max(0, f.total_frames - 1);
      if (this.lblFrame) this.lblFrame.textContent = f.index;
      if (this.lblTotalFrames) this.lblTotalFrames.textContent = f.total_frames;
      if (this.lblTime) this.lblTime.textContent = f.telemetry.sessionTime.toFixed(2);
      if (this.sectorEl) this.sectorEl.textContent = f.telemetry.sector;
      if (this.lapEl) this.lapEl.textContent = f.telemetry.currentLapNum;

      // Update Cockpit Gauges
      this.gauges.update(f.telemetry, f.prediction, f.evaluation);

      // Rolling Probability Chart
      if (f.prediction) {
        this.chart.pushSample(f.prediction.departure_probability);
      }

      // Track Map Car Position
      if (f.position) {
        this.trackmap.updateCarPosition(f.position, f.prediction?.warning_state);
      }
    } else if (msg.type === "end_of_session") {
      this.setPlayUiState(false);
      this.updateLoggingUi(false);
    }
  }

  // --- Benchmark Specs Modal ---
  async openBenchmarksModal() {
    this.modalBenchmarks.classList.remove("hidden");
    try {
      const res = await fetch("/api/status");
      const status = await res.json();
      if (this.featureTagsList && status.features) {
        this.featureTagsList.innerHTML = "";
        status.features.forEach((feat) => {
          const tag = document.createElement("span");
          tag.className = "tag";
          tag.textContent = feat;
          this.featureTagsList.appendChild(tag);
        });
      }
    } catch (e) {
      console.error("Failed to load model details:", e);
    }
  }

  closeBenchmarksModal() {
    this.modalBenchmarks.classList.add("hidden");
  }

  // --- Session Logs & Driver Analysis Modal ---
  async openLogsModal() {
    this.modalLogs.classList.remove("hidden");
    await this.loadSavedLogs();
  }

  closeLogsModal() {
    this.modalLogs.classList.add("hidden");
  }

  async loadSavedLogs() {
    try {
      this.savedLogsList.innerHTML = '<div style="color:var(--text-dim);font-size:0.75rem;padding:8px;">Loading saved sessions...</div>';
      const res = await fetch("/api/logs");
      const logs = await res.json();

      if (!logs || logs.length === 0) {
        this.savedLogsList.innerHTML = '<div style="color:var(--text-dim);font-size:0.75rem;padding:8px;">No recorded logs found. Press LOG during replay to record.</div>';
        return;
      }

      this.savedLogsList.innerHTML = "";
      logs.forEach((item) => {
        const card = document.createElement("div");
        card.className = "log-item-card";
        card.dataset.logId = item.log_id;

        card.innerHTML = `
          <div class="log-item-top">
            <span class="log-item-circuit">${item.circuit || "F1 Session"}</span>
            <span class="log-item-date">${item.created_at || ""}</span>
          </div>
          <div style="font-size:0.7rem;color:var(--text-muted);font-family:var(--font-mono);">
            Pilot ${item.pilot_index} ${item.lap_number ? `&bull; Lap ${item.lap_number}` : ""}
          </div>
          <div class="log-item-pills">
            <span class="pill-count pill-warning">${item.warning_events_count || 0} Warn</span>
            <span class="pill-count pill-caution">${item.caution_events_count || 0} Caut</span>
            <span class="pill-count pill-frames">${(item.total_frames || 0).toLocaleString()}f</span>
          </div>
        `;

        card.addEventListener("click", () => {
          document.querySelectorAll(".log-item-card").forEach((c) => c.classList.remove("active"));
          card.classList.add("active");
          this.loadLogDetail(item.log_id);
        });

        this.savedLogsList.appendChild(card);
      });

      // Auto select first log if none selected
      if (logs.length > 0) {
        const firstCard = this.savedLogsList.querySelector(".log-item-card");
        firstCard?.classList.add("active");
        this.loadLogDetail(logs[0].log_id);
      }
    } catch (e) {
      console.error("Failed to load logs:", e);
      this.savedLogsList.innerHTML = '<div style="color:var(--f1-red);font-size:0.75rem;padding:8px;">Error loading logs.</div>';
    }
  }

  async loadLogDetail(logId) {
    try {
      this.logDetailContent.innerHTML = '<div class="empty-selection-placeholder">Loading session review...</div>';
      const res = await fetch(`/api/logs/${logId}`);
      if (!res.ok) throw new Error("Log detail not found");
      const data = await res.json();
      const s = data.session;
      const events = data.events || [];
      const d = s.driver_analysis || {};

      let commonListHtml = "<li>Varied vehicle dynamics across logged events</li>";
      if (d.common_preceding_conditions && d.common_preceding_conditions.length > 0) {
        commonListHtml = d.common_preceding_conditions.map((c) => `<li>${c}</li>`).join("");
      }

      // Build events list HTML
      let eventsHtml = '<div style="color:var(--text-dim);font-size:0.78rem;font-style:italic;">No threshold-crossing events detected during this recording.</div>';
      if (events.length > 0) {
        eventsHtml = events
          .map((ev, idx) => {
            const isWarn = ev.event_type === "WARNING";
            const badgeClass = isWarn ? "event-warning" : "event-caution";
            const icon = isWarn ? "⚠" : "●";
            const p = ev.preceding_conditions || {};

            const fmtDelta = (val, suffix = "") => {
              if (val > 0) return `<span class="delta-pos">+${val}${suffix}</span>`;
              if (val < 0) return `<span class="delta-neg">${val}${suffix}</span>`;
              return `<span class="delta-neutral">0.0${suffix}</span>`;
            };

            return `
            <div class="event-card ${badgeClass}">
              <div class="event-card-top">
                <div class="event-badge-title">
                  <span>${icon} ${ev.event_type}</span>
                  <span style="font-size:0.75rem;font-weight:700;color:#fff;">(Peak: ${(ev.max_probability * 100).toFixed(1)}%)</span>
                </div>
                <div class="event-timestamp">
                  Time: ${ev.start_time.toFixed(2)}s &bull; Frame ${ev.frame_index} &bull; Lap ${ev.lap} (Sector ${ev.sector})
                </div>
              </div>

              <!-- Telemetry at Onset -->
              <div class="event-metrics-row">
                <div class="event-metric-item">
                  <span>SPEED</span>
                  <strong>${ev.telemetry_at_start.speed} km/h</strong>
                </div>
                <div class="event-metric-item">
                  <span>THROTTLE</span>
                  <strong>${Math.round(ev.telemetry_at_start.throttle * 100)}%</strong>
                </div>
                <div class="event-metric-item">
                  <span>BRAKE</span>
                  <strong>${Math.round(ev.telemetry_at_start.brake * 100)}%</strong>
                </div>
                <div class="event-metric-item">
                  <span>LATERAL G</span>
                  <strong>${ev.telemetry_at_start.gForceLateral}G</strong>
                </div>
              </div>

              <!-- Preceding Conditions (Causal Historical Context) -->
              <div class="preceding-conditions-box">
                <div class="preceding-title">CONDITIONS IN PRECEDING 0.5s (HISTORICAL FRAMES ONLY)</div>
                <table class="preceding-table">
                  <thead>
                    <tr>
                      <th>Signal</th>
                      <th>0.5s Before</th>
                      <th>At Onset</th>
                      <th>Change (&Delta;)</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Speed</td>
                      <td>${p.speed_0_5s_before ?? "-"} km/h</td>
                      <td>${ev.telemetry_at_start.speed} km/h</td>
                      <td>${fmtDelta(p.speed_change_0_5s, " km/h")}</td>
                    </tr>
                    <tr>
                      <td>Throttle</td>
                      <td>${Math.round((p.throttle_0_5s_before ?? 0) * 100)}%</td>
                      <td>${Math.round(ev.telemetry_at_start.throttle * 100)}%</td>
                      <td>${fmtDelta(Math.round((p.throttle_change_0_5s ?? 0) * 100), "%")}</td>
                    </tr>
                    <tr>
                      <td>Brake</td>
                      <td>${Math.round((p.brake_0_5s_before ?? 0) * 100)}%</td>
                      <td>${Math.round(ev.telemetry_at_start.brake * 100)}%</td>
                      <td>${fmtDelta(Math.round((p.brake_change_0_5s ?? 0) * 100), "%")}</td>
                    </tr>
                    <tr>
                      <td>Steering</td>
                      <td>${(p.steer_0_5s_before ?? 0).toFixed(3)}</td>
                      <td>${ev.telemetry_at_start.steer.toFixed(3)}</td>
                      <td>${fmtDelta((p.steer_change_0_5s ?? 0).toFixed(3))}</td>
                    </tr>
                  </tbody>
                </table>

                <div class="incident-narrative">
                  <strong>Telemetry Observation:</strong> ${ev.incident_analysis || "Standard dynamic profile leading into event."}
                </div>
              </div>

              <!-- Action Bar -->
              <div class="event-actions-bar">
                <button class="btn-jump-replay" data-frame="${ev.frame_index}">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                  Jump Replay to Event
                </button>
                <button class="btn-export btn-view-timeline" data-log-id="${logId}" data-event-idx="${idx}">
                  Show Timeline Window (-1.0s to +0.5s)
                </button>
              </div>
              <div class="event-timeline-chart-wrap hidden" id="timeline-wrap-${idx}">
                <canvas id="timeline-canvas-${idx}" width="650" height="90"></canvas>
              </div>
            </div>
            `;
          })
          .join("");
      }

      this.logDetailContent.innerHTML = `
        <div class="session-review-header">
          <div class="session-title-large">
            <h4>${s.circuit || "F1 Session"} &bull; Pilot ${s.pilot_index}</h4>
            <div class="session-meta-sub">
              Logged on ${s.created_at || "N/A"} &bull; ID: <code>${s.log_id}</code>
            </div>
          </div>
          <div class="export-btn-group">
            <a href="/api/logs/${logId}/export/csv" class="btn-export" download>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Telemetry CSV
            </a>
            <a href="/api/logs/${logId}/export/events_json" class="btn-export" download>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Events JSON
            </a>
            <a href="/api/logs/${logId}/export/session_json" class="btn-export" download>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              Session JSON
            </a>
          </div>
        </div>

        <!-- Session Stats Grid -->
        <div class="session-stats-bar">
          <div class="mini-stat">
            <span class="mini-stat-label">RECORDED DURATION</span>
            <span class="mini-stat-val">${s.duration_seconds || 0}s</span>
          </div>
          <div class="mini-stat">
            <span class="mini-stat-label">TOTAL FRAMES</span>
            <span class="mini-stat-val">${(s.total_frames || 0).toLocaleString()}</span>
          </div>
          <div class="mini-stat">
            <span class="mini-stat-label">TIME IN SAFE</span>
            <span class="mini-stat-val stat-safe">${s.time_in_safe_seconds || 0}s (${s.time_in_safe_pct || 0}%)</span>
          </div>
          <div class="mini-stat">
            <span class="mini-stat-label">TIME IN CAUTION</span>
            <span class="mini-stat-val stat-caution">${s.time_in_caution_seconds || 0}s (${s.time_in_caution_pct || 0}%)</span>
          </div>
          <div class="mini-stat">
            <span class="mini-stat-label">TIME IN WARNING</span>
            <span class="mini-stat-val stat-warning">${s.time_in_warning_seconds || 0}s (${s.time_in_warning_pct || 0}%)</span>
          </div>
        </div>

        <!-- Driver Telemetry Analysis Card -->
        <div class="driver-analysis-panel">
          <div class="driver-analysis-header">OBJECTIVE DRIVER TELEMETRY ANALYSIS (RECORDED EVENTS)</div>
          <div class="analysis-averages">
            <div>Avg Warning Speed: <span>${d.avg_warning_speed_kmh || 0} km/h</span></div>
            <div>Avg Warning Throttle: <span>${d.avg_warning_throttle_pct || 0}%</span></div>
            <div>Avg Warning Brake: <span>${d.avg_warning_brake_pct || 0}%</span></div>
          </div>
          <div style="font-size:0.72rem;font-weight:700;color:var(--text-muted);margin-bottom:4px;">COMMON PRECEDING BEHAVIORS:</div>
          <ul class="common-conditions-list">
            ${commonListHtml}
          </ul>
        </div>

        <!-- Events List -->
        <div class="events-section-title">DETECTED INCIDENTS (${events.length} TOTAL)</div>
        <div class="events-cards-container">
          ${eventsHtml}
        </div>
      `;

      // Bind Jump Replay buttons
      this.logDetailContent.querySelectorAll(".btn-jump-replay").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const frameIdx = parseInt(e.currentTarget.dataset.frame, 10);
          this.closeLogsModal();
          this.sendWsCommand({ command: "seek", frame_index: frameIdx });
        });
      });

      // Bind Show Timeline Window buttons
      this.logDetailContent.querySelectorAll(".btn-view-timeline").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          const lId = e.currentTarget.dataset.logId;
          const evIdx = parseInt(e.currentTarget.dataset.eventIdx, 10);
          const wrap = document.getElementById(`timeline-wrap-${evIdx}`);
          const canvas = document.getElementById(`timeline-canvas-${evIdx}`);

          if (!wrap.classList.contains("hidden")) {
            wrap.classList.add("hidden");
            e.currentTarget.textContent = "Show Timeline Window (-1.0s to +0.5s)";
            return;
          }

          wrap.classList.remove("hidden");
          e.currentTarget.textContent = "Hide Timeline Window";
          await this.renderEventTimelineChart(lId, evIdx, canvas);
        });
      });
    } catch (e) {
      console.error("Failed to load log detail:", e);
      this.logDetailContent.innerHTML = '<div class="empty-selection-placeholder" style="color:var(--f1-red);">Failed to load session details.</div>';
    }
  }

  async renderEventTimelineChart(logId, eventIndex, canvas) {
    if (!canvas) return;
    try {
      const res = await fetch(`/api/logs/${logId}/event_timeline/${eventIndex}`);
      if (!res.ok) return;
      const data = await res.json();
      const frames = data.timeline || [];
      if (frames.length < 2) return;

      const ctx = canvas.getContext("2d");
      const w = canvas.width;
      const h = canvas.height;

      ctx.clearRect(0, 0, w, h);

      const padL = 40;
      const padR = 20;
      const padT = 15;
      const padB = 20;
      const plotW = w - padL - padR;
      const plotH = h - padT - padB;

      // Draw grid
      ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#545b69";
      ctx.font = "9px JetBrains Mono, monospace";

      [0.0, 0.5, 1.0].forEach((lev) => {
        const y = padT + plotH * (1 - lev);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(padL + plotW, y);
        ctx.stroke();
        ctx.fillText(`${Math.round(lev * 100)}%`, 5, y + 3);
      });

      const stepX = plotW / (frames.length - 1);

      // 1. Throttle line (green)
      ctx.strokeStyle = "#00e676";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      frames.forEach((f, i) => {
        const x = padL + i * stepX;
        const y = padT + plotH * (1 - f.throttle);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // 2. Brake line (red)
      ctx.strokeStyle = "#ff1801";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      frames.forEach((f, i) => {
        const x = padL + i * stepX;
        const y = padT + plotH * (1 - f.brake);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // 3. Departure Probability line (cyan)
      ctx.strokeStyle = "#00d2ff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      frames.forEach((f, i) => {
        const x = padL + i * stepX;
        const y = padT + plotH * (1 - f.departure_probability);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // 4. Threshold line at 0.50
      ctx.strokeStyle = "rgba(255, 24, 1, 0.6)";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      const threshY = padT + plotH * 0.5;
      ctx.moveTo(padL, threshY);
      ctx.lineTo(padL + plotW, threshY);
      ctx.stroke();
      ctx.setLineDash([]);

      // Legend
      ctx.fillStyle = "#00e676";
      ctx.fillText("■ Throttle", padL + 10, padT - 4);
      ctx.fillStyle = "#ff1801";
      ctx.fillText("■ Brake", padL + 80, padT - 4);
      ctx.fillStyle = "#00d2ff";
      ctx.fillText("■ Warning Prob", padL + 140, padT - 4);
    } catch (e) {
      console.error("Failed to render timeline chart:", e);
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  window.dashboard = new TelemetryDashboard();
});
