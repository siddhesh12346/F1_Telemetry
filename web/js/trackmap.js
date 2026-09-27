/**
 * Circuit Track Map and Probability Rolling Chart Renderers
 */
class TrackMapRenderer {
  constructor(canvasId = "trackmap-canvas") {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas ? this.canvas.getContext("2d") : null;
    this.points = [];
    this.bounds = null;
    this.carPos = null;
    this.carState = "SAFE";

    // Handle high DPI
    if (this.canvas) {
      this.resize();
      window.addEventListener("resize", () => this.resize());
    }
  }

  resize() {
    if (!this.canvas) return;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    if (this.ctx) {
      this.ctx.scale(dpr, dpr);
    }
    this.draw();
  }

  setTrackData(trackData) {
    if (!trackData || !trackData.points) return;
    this.points = trackData.points;
    this.bounds = trackData.bounds;
    this.draw();
  }

  updateCarPosition(pos, warningState) {
    this.carPos = pos;
    this.carState = warningState || "SAFE";
    this.draw();
  }

  draw() {
    if (!this.ctx || !this.canvas) return;
    const ctx = this.ctx;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    if (!this.points || this.points.length === 0) {
      ctx.fillStyle = "#545b69";
      ctx.font = "12px JetBrains Mono, monospace";
      ctx.textAlign = "center";
      ctx.fillText("LOADING CIRCUIT GEOMETRY...", w / 2, h / 2);
      return;
    }

    // Determine scale to fit canvas with padding
    const padding = 30;
    const minX = Math.min(...this.points.map((p) => p.x));
    const maxX = Math.max(...this.points.map((p) => p.x));
    const minY = Math.min(...this.points.map((p) => p.y));
    const maxY = Math.max(...this.points.map((p) => p.y));

    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);

    const scale = Math.min((w - padding * 2) / spanX, (h - padding * 2) / spanY);
    const offsetX = (w - spanX * scale) / 2 - minX * scale;
    const offsetY = (h - spanY * scale) / 2 - minY * scale;

    const toScreen = (pt) => ({
      x: pt.x * scale + offsetX,
      y: pt.y * scale + offsetY,
    });

    // 1. Draw track asphalt outline
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    // Track outer border
    ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
    ctx.lineWidth = 10;
    ctx.beginPath();
    this.points.forEach((pt, i) => {
      const s = toScreen(pt);
      if (i === 0) ctx.moveTo(s.x, s.y);
      else ctx.lineTo(s.x, s.y);
    });
    ctx.closePath();
    ctx.stroke();

    // Track centerline / racing groove
    ctx.strokeStyle = "rgba(0, 210, 255, 0.6)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    this.points.forEach((pt, i) => {
      const s = toScreen(pt);
      if (i === 0) ctx.moveTo(s.x, s.y);
      else ctx.lineTo(s.x, s.y);
    });
    ctx.closePath();
    ctx.stroke();

    // Start / Finish Line
    if (this.points.length > 0) {
      const sf = toScreen(this.points[0]);
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(sf.x, sf.y, 4, 0, Math.PI * 2);
      ctx.fill();
    }

    // 2. Draw Car Position Marker
    if (this.carPos && this.bounds) {
      // Convert raw x, z to normalized track coordinate system
      const bx = this.bounds;
      const spanRawX = Math.max(1.0, bx.max_x - bx.min_x);
      const spanRawZ = Math.max(1.0, bx.max_z - bx.min_z);
      const normScale = 800.0 / Math.max(spanRawX, spanRawZ);

      const normX = (this.carPos.x - bx.min_x) * normScale + 100.0;
      const normY = (this.carPos.z - bx.min_z) * normScale + 100.0;
      const carScreen = toScreen({ x: normX, y: normY });

      // Color by warning status
      let color = "#00e676";
      let glow = "rgba(0, 230, 118, 0.6)";
      if (this.carState === "CAUTION") {
        color = "#ffb800";
        glow = "rgba(255, 184, 0, 0.7)";
      } else if (this.carState === "WARNING") {
        color = "#ff1801";
        glow = "rgba(255, 24, 1, 0.9)";
      }

      // Outer glow circle
      ctx.shadowColor = glow;
      ctx.shadowBlur = 12;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(carScreen.x, carScreen.y, 6, 0, Math.PI * 2);
      ctx.fill();

      // Inner white pin
      ctx.shadowBlur = 0;
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(carScreen.x, carScreen.y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

class ProbabilityChart {
  constructor(canvasId = "prob-chart-canvas", maxSamples = 60) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas ? this.canvas.getContext("2d") : null;
    this.maxSamples = maxSamples;
    this.history = [];

    if (this.canvas) {
      this.resize();
      window.addEventListener("resize", () => this.resize());
    }
  }

  resize() {
    if (!this.canvas) return;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    if (this.ctx) {
      this.ctx.scale(dpr, dpr);
    }
    this.draw();
  }

  pushSample(prob) {
    this.history.push(Math.max(0, Math.min(1, prob)));
    if (this.history.length > this.maxSamples) {
      this.history.shift();
    }
    this.draw();
  }

  reset() {
    this.history = [];
    this.draw();
  }

  draw() {
    if (!this.ctx || !this.canvas) return;
    const ctx = this.ctx;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    // Padding
    const padL = 35;
    const padR = 15;
    const padT = 15;
    const padB = 25;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;

    // Grid lines & labels (0.0, 0.5, 1.0)
    ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#545b69";
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.textAlign = "right";

    [0.0, 0.5, 1.0].forEach((level) => {
      const y = padT + plotH * (1 - level);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();
      ctx.fillText(level.toFixed(1), padL - 8, y + 3);
    });

    // Threshold Line at 0.50 (Dashed Red)
    const threshY = padT + plotH * 0.5;
    ctx.save();
    ctx.strokeStyle = "rgba(255, 24, 1, 0.85)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padL, threshY);
    ctx.lineTo(padL + plotW, threshY);
    ctx.stroke();
    ctx.restore();

    if (this.history.length < 2) return;

    // Plot probability line & gradient fill
    const stepX = plotW / (this.maxSamples - 1);
    const startIdx = this.maxSamples - this.history.length;

    const points = this.history.map((val, i) => {
      const x = padL + (startIdx + i) * stepX;
      const y = padT + plotH * (1 - val);
      return { x, y, val };
    });

    // Area Fill with Gradient
    const gradient = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    gradient.addColorStop(0, "rgba(255, 24, 1, 0.35)");
    gradient.addColorStop(0.5, "rgba(255, 184, 0, 0.2)");
    gradient.addColorStop(1, "rgba(0, 230, 118, 0.05)");

    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(points[0].x, padT + plotH);
    points.forEach((p) => ctx.lineTo(p.x, p.y));
    ctx.lineTo(points[points.length - 1].x, padT + plotH);
    ctx.closePath();
    ctx.fill();

    // Curve Line
    ctx.strokeStyle = "#00d2ff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((p, i) => {
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    ctx.stroke();

    // Latest Point Dot
    const latest = points[points.length - 1];
    let dotColor = "#00e676";
    if (latest.val >= 0.5) dotColor = "#ff1801";
    else if (latest.val >= 0.3) dotColor = "#ffb800";

    ctx.fillStyle = dotColor;
    ctx.shadowColor = dotColor;
    ctx.shadowBlur = 6;
    ctx.beginPath();
    ctx.arc(latest.x, latest.y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }
}

window.TrackMapRenderer = TrackMapRenderer;
window.ProbabilityChart = ProbabilityChart;
