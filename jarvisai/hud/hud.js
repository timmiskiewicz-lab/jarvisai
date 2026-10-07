const canvas = document.getElementById("rings");
const ctx = canvas.getContext("2d");
const orb = document.getElementById("orb");
const statusEl = document.getElementById("status");
const captionEl = document.getElementById("caption");
const voiceEl = document.getElementById("voice");
const settingsEl = document.getElementById("settings");

const state = {
  mode: "idle",
  amplitude: 0,
  caption: "",
  status: "Starting systems",
  voice: "Voice",
};

let smooth = 0;
let demo = null;

function resize() {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = 640 * ratio;
  canvas.height = 640 * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
}

function draw(time) {
  const mode = state.mode;
  const speaking = mode === "speaking";
  const listening = mode === "listening";
  if (state.voice === "Preview" && speaking) {
    state.amplitude = 0.3 + Math.abs(Math.sin(time / 140)) * 0.7;
  }
  smooth += (state.amplitude - smooth) * (speaking ? 0.45 : 0.18);
  const amp = Math.max(0, Math.min(1, smooth));
  const breathe = speaking ? 0 : Math.sin(time / 900) * 0.018;
  const scale = 1 + breathe + amp * (speaking ? 0.34 : listening ? 0.16 : 0.08);
  orb.style.transform = `scale(${scale.toFixed(4)})`;

  const w = 640;
  const h = 640;
  const cx = w / 2;
  const cy = h / 2;
  const base = 250;
  const speed = speaking ? 1.7 : listening ? 1.15 : 0.5;
  const spin = time / 1000;
  ctx.clearRect(0, 0, w, h);

  ring(cx, cy, base * 1.08, "rgba(110, 210, 240, 0.28)", 1.5, 0);
  ticks(cx, cy, base, spin * 0.12 * speed, amp);
  segments(cx, cy, base * 0.9, spin * 0.32 * speed, amp);
  goldMarks(cx, cy, base);
  dashed(cx, cy, base * 0.74, -spin * 0.46 * speed);
  glow(cx, cy, base * 0.6, amp);
  mesh(cx, cy, base, spin, amp, listening || speaking);
  core(cx, cy, base, amp);

  requestAnimationFrame(draw);
}

function ring(cx, cy, radius, color, width, rotation) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(rotation);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.arc(0, 0, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function ticks(cx, cy, base, rotation) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(rotation);
  ctx.strokeStyle = "rgba(140, 230, 255, 0.7)";
  ctx.lineWidth = 2;
  for (let i = 0; i < 120; i += 1) {
    const angle = (i / 120) * Math.PI * 2;
    const inner = base * (i % 10 === 0 ? 0.98 : 1.01);
    const outer = base * (i % 10 === 0 ? 1.08 : 1.045);
    ctx.beginPath();
    ctx.moveTo(Math.cos(angle) * inner, Math.sin(angle) * inner);
    ctx.lineTo(Math.cos(angle) * outer, Math.sin(angle) * outer);
    ctx.stroke();
  }
  ctx.restore();
}

function segments(cx, cy, radius, rotation, amp) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(rotation);
  ctx.strokeStyle = "#8af4ff";
  ctx.lineWidth = 9;
  ctx.lineCap = "round";
  ctx.shadowColor = "#39dfff";
  ctx.shadowBlur = 18 + amp * 28;
  const count = 8;
  for (let i = 0; i < count; i += 1) {
    const gap = 0.34;
    const start = (i / count) * Math.PI * 2 + gap / 2;
    const end = ((i + 1) / count) * Math.PI * 2 - gap / 2;
    ctx.beginPath();
    ctx.arc(0, 0, radius, start, end);
    ctx.stroke();
  }
  ctx.restore();
}

function goldMarks(cx, cy, base) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.strokeStyle = "#e2b15a";
  ctx.lineWidth = 3;
  ctx.shadowColor = "#e2b15a";
  ctx.shadowBlur = 8;
  for (let i = 0; i < 8; i += 1) {
    const angle = Math.PI * 0.78 + i * 0.085;
    ctx.beginPath();
    ctx.moveTo(Math.cos(angle) * base * 0.8, Math.sin(angle) * base * 0.8);
    ctx.lineTo(Math.cos(angle) * base * 0.86, Math.sin(angle) * base * 0.86);
    ctx.stroke();
  }
  ctx.restore();
}

function dashed(cx, cy, radius, rotation) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(rotation);
  ctx.strokeStyle = "rgba(120, 220, 255, 0.75)";
  ctx.lineWidth = 2;
  ctx.setLineDash([8, 12]);
  ctx.beginPath();
  ctx.arc(0, 0, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function glow(cx, cy, radius, amp) {
  ctx.save();
  ctx.translate(cx, cy);
  ctx.strokeStyle = "rgba(190, 248, 255, 0.95)";
  ctx.lineWidth = 3;
  ctx.shadowColor = "#7aefff";
  ctx.shadowBlur = 22 + amp * 36;
  ctx.beginPath();
  ctx.arc(0, 0, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function mesh(cx, cy, base, spin, amp, active) {
  const rings = 4;
  const points = 14;
  const coords = [];
  for (let ringIndex = 1; ringIndex <= rings; ringIndex += 1) {
    const row = [];
    const radius = base * 0.12 + ringIndex * base * 0.075 + amp * (8 + ringIndex * 4);
    for (let point = 0; point < points; point += 1) {
      const angle = (point / points) * Math.PI * 2 + spin * (active ? 0.35 : 0.12);
      row.push([Math.cos(angle) * radius, Math.sin(angle) * radius]);
    }
    coords.push(row);
  }
  ctx.save();
  ctx.translate(cx, cy);
  ctx.strokeStyle = `rgba(150, 235, 255, ${0.22 + amp * 0.6})`;
  ctx.lineWidth = 1.15;
  coords.forEach((row, ringIndex) => {
    row.forEach(([x, y], point) => {
      const next = row[(point + 1) % row.length];
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(next[0], next[1]);
      ctx.stroke();
      if (coords[ringIndex + 1]) {
        const down = coords[ringIndex + 1][point];
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(down[0], down[1]);
        ctx.stroke();
      }
    });
  });
  ctx.restore();
}

function core(cx, cy, base, amp) {
  const gradient = ctx.createRadialGradient(cx, cy, 8, cx, cy, base * 0.32);
  gradient.addColorStop(0, `rgba(110, 230, 255, ${0.28 + amp * 0.5})`);
  gradient.addColorStop(1, "rgba(6, 16, 24, 0)");
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(cx, cy, base * 0.34, 0, Math.PI * 2);
  ctx.fill();
}

function applyState(next) {
  state.mode = next.mode || "idle";
  state.amplitude = Number(next.amplitude || 0);
  state.caption = next.caption || "";
  state.status = next.status || "Standing by";
  state.voice = next.voice || state.voice;
  statusEl.textContent = state.status;
  captionEl.textContent = state.caption;
  voiceEl.textContent = state.voice;
}

async function poll() {
  try {
    if (window.pywebview) {
      applyState(await window.pywebview.api.get_state());
    }
  } catch (error) {
    statusEl.textContent = "Link lost";
  }
  setTimeout(poll, 40);
}

function startDemo() {
  if (demo || window.pywebview) {
    return;
  }
  let phase = 0;
  demo = setInterval(() => {
    phase = (phase + 1) % 3;
    const mode = ["idle", "listening", "speaking"][phase];
    applyState({
      mode,
      amplitude: mode === "speaking" ? 0.85 : mode === "listening" ? 0.35 : 0.04,
      status: mode,
      caption: mode === "speaking" ? "What's up, sir?" : "",
      voice: "Preview",
    });
  }, 1600);
  applyState({ mode: "idle", amplitude: 0.05, status: "Standing by", caption: "", voice: "Preview" });
}

document.getElementById("hide").addEventListener("click", () => {
  if (window.pywebview) {
    window.pywebview.api.hide_window();
  }
});

document.getElementById("settings-open").addEventListener("click", async () => {
  settingsEl.classList.remove("hidden");
  if (!window.pywebview) {
    return;
  }
  const settings = await window.pywebview.api.get_settings();
  document.getElementById("api-key").value = settings.api_key || "";
});

document.getElementById("settings-close").addEventListener("click", () => {
  settingsEl.classList.add("hidden");
});

document.getElementById("save").addEventListener("click", async () => {
  const note = document.getElementById("settings-note");
  if (!window.pywebview) {
    note.textContent = "Save is available in the desktop app.";
    return;
  }
  const result = await window.pywebview.api.save_settings(document.getElementById("api-key").value);
  note.textContent = result.elevenlabs
    ? "Daniel is ready."
    : "Built-in Jarvis voice stays on.";
});

document.getElementById("test-voice").addEventListener("click", async () => {
  if (window.pywebview) {
    await window.pywebview.api.test_voice();
    settingsEl.classList.add("hidden");
  }
});

document.getElementById("listen-now").addEventListener("click", async () => {
  if (window.pywebview) {
    await window.pywebview.api.listen_now();
    settingsEl.classList.add("hidden");
  }
});

resize();
requestAnimationFrame(draw);
window.addEventListener("pywebviewready", () => {
  if (demo) {
    clearInterval(demo);
    demo = null;
  }
  poll();
});
setTimeout(startDemo, 700);
