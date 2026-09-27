/**
 * Gauges and Cockpit Dynamics Controller
 */
class CockpitGauges {
  constructor() {
    this.speedEl = document.getElementById("val-speed");
    this.speedBar = document.getElementById("speed-bar");
    this.gearEl = document.getElementById("val-gear");
    this.rpmNum = document.getElementById("val-rpm");
    this.rpmContainer = document.getElementById("rpm-leds");
    this.drsEl = document.getElementById("val-drs");
    this.throttleFill = document.getElementById("pedal-throttle");
    this.throttlePct = document.getElementById("val-throttle");
    this.brakeFill = document.getElementById("pedal-brake");
    this.brakePct = document.getElementById("val-brake");
    this.steeringWheel = document.getElementById("steering-wheel");
    this.steerVal = document.getElementById("val-steer");
    this.glatVal = document.getElementById("val-glat");
    this.glongVal = document.getElementById("val-glong");
    this.gvertVal = document.getElementById("val-gvert");
    this.gCanvas = document.getElementById("gforce-canvas");
    this.gCtx = this.gCanvas ? this.gCanvas.getContext("2d") : null;

    // Warning banner elements
    this.warningBanner = document.getElementById("warning-banner");
    this.warningStateText = document.getElementById("warning-state-text");
    this.probPercentage = document.getElementById("prob-percentage");
    this.probBarFill = document.getElementById("prob-bar-fill");
    this.evalGroundTruth = document.getElementById("eval-ground-truth");

    this.initRpmLeds();
    this.drawGForceCrosshair(0, 0);
  }

  initRpmLeds() {
    if (!this.rpmContainer) return;
    this.rpmContainer.innerHTML = "";
    this.leds = [];
    const totalLeds = 15;
    for (let i = 0; i < totalLeds; i++) {
      const led = document.createElement("div");
      led.className = "rpm-led";
      let colorClass = "green";
      if (i >= 5 && i < 10) colorClass = "red";
      if (i >= 10) colorClass = "blue";
      led.dataset.color = colorClass;
      this.rpmContainer.appendChild(led);
      this.leds.push(led);
    }
  }

  update(telemetry, prediction, evaluation) {
    if (!telemetry) return;

    // 1. Speed (km/h)
    const speed = Math.round(telemetry.speed || 0);
    if (this.speedEl) this.speedEl.textContent = speed;
    if (this.speedBar) {
      const pct = Math.min(100, Math.max(0, (speed / 350) * 100));
      this.speedBar.style.width = `${pct}%`;
    }

    // 2. Gear
    if (this.gearEl) {
      const g = telemetry.gear;
      let gearStr = g === 0 ? "N" : g < 0 ? "R" : String(g);
      this.gearEl.textContent = gearStr;
    }

    // 3. Engine RPM & LEDs
    const rpm = telemetry.engineRPM || 0;
    if (this.rpmNum) this.rpmNum.textContent = `${rpm.toLocaleString()} RPM`;
    if (this.leds) {
      // 8,000 to 13,500 RPM mapping
      const minRpm = 7500;
      const maxRpm = 13500;
      const fraction = Math.min(1, Math.max(0, (rpm - minRpm) / (maxRpm - minRpm)));
      const activeCount = Math.floor(fraction * this.leds.length);
      this.leds.forEach((led, idx) => {
        if (idx < activeCount) {
          led.className = `rpm-led active ${led.dataset.color}`;
        } else {
          led.className = "rpm-led";
        }
      });
    }

    // 4. DRS
    if (this.drsEl) {
      const drs = telemetry.drs === 1;
      if (drs) {
        this.drsEl.className = "drs-badge active";
        this.drsEl.textContent = "DRS OPEN";
      } else {
        this.drsEl.className = "drs-badge";
        this.drsEl.textContent = "DRS OFF";
      }
    }

    // 5. Pedals (Throttle 0..1, Brake 0..1)
    const throttle = Math.min(1, Math.max(0, telemetry.throttle || 0));
    const brake = Math.min(1, Math.max(0, telemetry.brake || 0));
    if (this.throttleFill) this.throttleFill.style.height = `${throttle * 100}%`;
    if (this.throttlePct) this.throttlePct.textContent = `${Math.round(throttle * 100)}%`;
    if (this.brakeFill) this.brakeFill.style.height = `${brake * 100}%`;
    if (this.brakePct) this.brakePct.textContent = `${Math.round(brake * 100)}%`;

    // 6. Steering (-1.0 to 1.0)
    const steer = telemetry.steer || 0;
    if (this.steerVal) this.steerVal.textContent = steer.toFixed(3);
    if (this.steeringWheel) {
      const deg = steer * 90; // Rotate up to 90 deg each side
      this.steeringWheel.style.transform = `rotate(${deg}deg)`;
    }

    // 7. G-Forces
    const glat = telemetry.gForceLateral || 0;
    const glong = telemetry.gForceLongitudinal || 0;
    const gvert = telemetry.gForceVertical || 0;
    if (this.glatVal) this.glatVal.textContent = glat.toFixed(2);
    if (this.glongVal) this.glongVal.textContent = glong.toFixed(2);
    if (this.gvertVal) this.gvertVal.textContent = gvert.toFixed(2);
    this.drawGForceCrosshair(glat, glong);

    // 8. Warning State & Departure Probability
    if (prediction) {
      const prob = prediction.departure_probability || 0;
      const state = prediction.warning_state || "SAFE";
      const pct = (prob * 100).toFixed(1);

      if (this.probPercentage) this.probPercentage.textContent = `${pct}%`;
      if (this.probBarFill) this.probBarFill.style.width = `${Math.min(100, prob * 100)}%`;
      if (this.warningStateText) this.warningStateText.textContent = state;

      if (this.warningBanner) {
        this.warningBanner.className = `warning-banner state-${state.toLowerCase()}`;
      }
    }

    // 9. Ground Truth Evaluation Display (isolated from ML)
    if (evaluation && this.evalGroundTruth) {
      if (evaluation.is_off_track) {
        this.evalGroundTruth.className = "eval-value off-track";
        this.evalGroundTruth.textContent = `OFF-TRACK (${evaluation.surfaceType})`;
      } else {
        this.evalGroundTruth.className = "eval-value on-track";
        this.evalGroundTruth.textContent = "ON-TRACK (NOMINAL)";
      }
    }
  }

  drawGForceCrosshair(lat, lon) {
    if (!this.gCtx || !this.gCanvas) return;
    const ctx = this.gCtx;
    const w = this.gCanvas.width;
    const h = this.gCanvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const maxG = 5.0; // +/- 5G full scale

    ctx.clearRect(0, 0, w, h);

    // Rings
    ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
    ctx.lineWidth = 1;
    [0.33, 0.66, 1.0].forEach((ratio) => {
      ctx.beginPath();
      ctx.arc(cx, cy, (w / 2 - 10) * ratio, 0, Math.PI * 2);
      ctx.stroke();
    });

    // Crosshairs
    ctx.beginPath();
    ctx.moveTo(10, cy);
    ctx.lineTo(w - 10, cy);
    ctx.moveTo(cx, 10);
    ctx.lineTo(cx, h - 10);
    ctx.stroke();

    // Point
    const px = cx + (lat / maxG) * (w / 2 - 10);
    const py = cy - (lon / maxG) * (h / 2 - 10);

    ctx.fillStyle = "#ff1801";
    ctx.shadowColor = "#ff1801";
    ctx.shadowBlur = 8;
    ctx.beginPath();
    ctx.arc(
      Math.max(10, Math.min(w - 10, px)),
      Math.max(10, Math.min(h - 10, py)),
      5,
      0,
      Math.PI * 2
    );
    ctx.fill();
    ctx.shadowBlur = 0;
  }
}

window.CockpitGauges = CockpitGauges;
