// Live camera form coach. Runs entirely in the browser: the video never leaves the device.
// Pipeline: getUserMedia -> MediaPipe Pose (self-hosted WASM) -> One Euro smoothing -> formmath analysis -> canvas + cues.
import { api, ApiError, track } from "../lib/api.js";
import { $, $$, esc, icon, prefersReducedMotion, toast } from "../lib/dom.js";
import {
  CueStabilizer, PoseSmoother, RepTracker, analyze, config, newCal, prepare, updateCal, toWorld,
} from "../lib/formmath.js";
import { DEMO_H, DEMO_W, demoFps, demoFrame } from "../lib/demo.js";
import { ensureUser, onUser, state } from "../shell.js";

const FREE_EXERCISES = ["squat"];
const FREE_SECONDS = 180;
const LIB = "/static/vendor/mediapipe/pose/";
const NAMES = { squat: "Squat", deadlift: "Deadlift", pushup: "Push-up", pullup: "Pull-up" };
const FAULT_TEXT = {
  lean: "Chest folding forward", heels: "Heels lifting", bar: "Weight off mid-foot", depth: "Not deep enough",
  hips: "Hips shooting up", low: "Hips too low", lockout: "Incomplete lockout", lean_back: "Leaning back at the top",
  sag: "Hips sagging", pike: "Hips too high", kip: "Swinging (kipping)",
};
const INTRO = {
  squat: "Stand side-on to the camera with your whole body in frame, feet shoulder-width apart.",
  deadlift: "Stand side-on with the bar (or your hands) in view and your whole body in frame.",
  pushup: "Set up side-on in a plank so the camera sees your head, hips and heels.",
  pullup: "Set the camera side-on, far enough back to see your shoulder, elbow and hand on the bar. Legs can be out of frame.",
};

let posePromise = null;
function loadPose() {
  if (posePromise) return posePromise;
  posePromise = new Promise((resolve, reject) => {
    if (window.Pose) return resolve(window.Pose);
    const s = document.createElement("script");
    s.src = `${LIB}pose.js`;
    s.onload = () => (window.Pose ? resolve(window.Pose) : reject(new Error("pose library missing")));
    s.onerror = () => reject(new Error("could not load the pose library"));
    document.head.append(s);
  });
  posePromise.catch(() => { posePromise = null; });
  return posePromise;
}

export function initFormCoach() {
  const stage = $("#coach-stage");
  if (!stage) return;
  const canvas = $("#coach-canvas");
  const ctx = canvas.getContext("2d");
  const video = $("#coach-video");
  const overlay = $("#coach-overlay");
  const debug = new URLSearchParams(location.search).has("debug");

  const ui = {
    cue: $("#coach-cue"), score: $("#coach-score"), reps: $("#coach-reps"), fps: $("#coach-fps"),
    calBar: $("#coach-cal"), gauge: $("#coach-gauge-fill"), goal: $("#coach-gauge-goal"),
    ghost: $("#coach-ghost"), voice: $("#coach-voice"), summary: $("#coach-summary"), timer: $("#coach-timer"),
    demo: $$("[data-coach-demo]"), start: $("#coach-start"), stop: $("#coach-stop"), flip: $("#coach-flip"), gate: $("#coach-gate"), hud: $("#coach-hud"),
  };

  const S = {
    ex: "squat", running: false, stream: null, pose: null, facing: "user", pro: false,
    smoother: null, cal: null, tracker: null, stab: null,
    disp: {}, target: null, ghost: null, res: null, faultIds: new Set(), open: false, demo: false, demoIdx: -1,
    lastDetect: 0, fpsEma: 0, slowSince: 0, complexity: 1, startedAt: 0, lastSpoken: 0, lastCueId: "", lostFrames: 0,
    detectLoop: 0, renderLoop: 0, w: 1280, h: 720, debugFrame: false,
  };

  // ------------------------------------------------------------- plan gating
  const isPro = () => S.pro || S.open;
  const GATE_HTML = ui.gate.innerHTML;
  api("/api/config").then((cfg) => { S.open = Boolean(cfg.coach_open_access); syncTabs(); }).catch(() => {});
  onUser(async (user) => {
    S.pro = false;
    if (user) {
      try { S.pro = Boolean((await api("/api/billing/subscription")).subscription?.is_paid); } catch { /* stay on the free tier */ }
    }
    syncTabs();
  });

  function syncTabs() {
    $$("#coach-tabs [data-ex]").forEach((b) => {
      const locked = !isPro() && !FREE_EXERCISES.includes(b.dataset.ex);
      b.classList.toggle("is-locked", locked);
      b.setAttribute("aria-selected", String(b.dataset.ex === S.ex));
      const lock = $(".coach__lock", b);
      if (lock) lock.hidden = !locked;
    });
    ui.voice.disabled = !isPro();
    ui.voice.closest(".check").classList.toggle("is-disabled", !isPro());
    $("#coach-voice-note").hidden = isPro();
    ui.gate.hidden = S.pro;
    ui.gate.innerHTML = S.open && !S.pro ? "<b>Preview mode:</b> every lift, unlimited time and voice cues are unlocked on this local install. The Free and Pro limits apply on the live site." : GATE_HTML;
    setIntro();
  }

  function setIntro() {
    const locked = !isPro() && !FREE_EXERCISES.includes(S.ex);
    $("#coach-intro-text").textContent = INTRO[S.ex] + (locked ? " Live camera sessions for this lift are part of Pro. You can still watch the demo." : "");
  }

  function setExercise(ex) {
    if (S.running) return toast("Stop the session before switching exercise.");
    S.ex = ex;
    syncTabs();
    const goal = config(ex).depthGoal;
    ui.goal.hidden = !goal;
    if (goal) ui.goal.style.bottom = `${goal * 100}%`;
    resetOverlay("intro");
  }

  $("#coach-tabs")?.addEventListener("click", (e) => { const b = e.target.closest("[data-ex]"); if (b) setExercise(b.dataset.ex); });
  window.addEventListener("iron:coach", (e) => { if (e.detail?.exercise) setExercise(e.detail.exercise); $("#coach")?.scrollIntoView({ behavior: "smooth" }); });

  // ---------------------------------------------------------------- overlay
  function resetOverlay(kind, message = "") {
    overlay.hidden = false;
    overlay.dataset.kind = kind;
    $$("[data-panel]", overlay).forEach((p) => { p.hidden = p.dataset.panel !== kind; });
    if (kind === "error") $("#coach-error-text").textContent = message;
    if (kind === "loading") $("#coach-load-text").textContent = message || "Loading the pose model (about 9 MB, once)";
  }

  // ----------------------------------------------------------------- camera
  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error("Camera access needs a secure page (https or localhost)."), { name: "Insecure" });
    S.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: S.facing, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false,
    });
    video.srcObject = S.stream;
    await video.play();
    S.w = video.videoWidth || 1280;
    S.h = video.videoHeight || 720;
    canvas.width = S.w;
    canvas.height = S.h;
    stage.style.setProperty("--ar", `${S.w} / ${S.h}`);
  }

  function friendly(err) {
    const n = err?.name;
    if (n === "NotAllowedError" || n === "SecurityError") return "Camera permission is blocked. Click the camera icon in your browser's address bar, allow it, then try again.";
    if (n === "NotFoundError" || n === "OverconstrainedError") return "No camera was found on this device.";
    if (n === "NotReadableError") return "Your camera is being used by another app. Close it and try again.";
    if (n === "Insecure") return err.message;
    return err?.message || "Something went wrong starting the camera.";
  }

  // ---------------------------------------------------------------- session
  async function start() {
    if (S.running) return;
    if (!isPro() && !FREE_EXERCISES.includes(S.ex)) {
      track("plan_selected");
      toast(`${NAMES[S.ex]} coaching is part of Pro.`);
      $("#pricing")?.scrollIntoView({ behavior: "smooth" });
      return;
    }
    ui.summary.hidden = true;
    ui.stop.textContent = "Stop";
    try {
      resetOverlay("loading", "Starting your camera");
      await startCamera();
      resetOverlay("loading", "Loading the pose model (about 9 MB, once)");
      const Pose = await loadPose();
      if (!S.pose) {
        S.pose = new Pose({ locateFile: (f) => `${LIB}${f}` });
        S.pose.setOptions({ modelComplexity: S.complexity, smoothLandmarks: true, enableSegmentation: false, minDetectionConfidence: 0.5, minTrackingConfidence: 0.5 });
        S.pose.onResults(onResults);
        await S.pose.initialize();
      }
    } catch (err) {
      stopStream();
      resetOverlay("error", friendly(err));
      return;
    }
    S.smoother = new PoseSmoother();
    S.cal = newCal();
    S.tracker = new RepTracker(S.ex);
    S.stab = new CueStabilizer(5);
    S.disp = {}; S.target = null; S.ghost = null; S.res = null; S.lostFrames = 0; S.fpsEma = 0; S.slowSince = 0; S.crawlSince = 0;
    S.running = true;
    S.startedAt = performance.now();
    overlay.hidden = true;
    ui.hud.hidden = false;
    ui.start.hidden = true; ui.stop.hidden = false; ui.flip.hidden = false;
    ui.reps.textContent = "0";
    ui.score.textContent = "--";
    showCue({ id: "cal", severity: "ok", text: "Stand tall and still for two seconds so I can learn your body." });
    track("coach_started");
    S.detectLoop = 1;
    detectLoop();
    S.renderLoop = requestAnimationFrame(render);
    tickTimer();
  }

  function stopStream() {
    S.stream?.getTracks().forEach((t) => t.stop());
    S.stream = null;
    video.srcObject = null;
  }

  async function stop(reason = "") {
    if (!S.running && !reason) return;
    if (S.demo) {
      S.demo = false; S.running = false; S.debugFrame = false;
      cancelAnimationFrame(S.renderLoop);
      ui.hud.hidden = true; ui.start.hidden = false; ui.stop.hidden = true; ui.stop.textContent = "Stop";
      delete stage.dataset.flash; stage.dataset.state = "ok";
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      resetOverlay("intro");
      return;
    }
    S.running = false;
    cancelAnimationFrame(S.renderLoop);
    stopStream();
    window.speechSynthesis?.cancel();
    ui.hud.hidden = true;
    ui.start.hidden = false; ui.stop.hidden = true; ui.flip.hidden = true;
    const sum = S.tracker?.summary() || { reps: 0, avg: 0, best: 0, faults: {} };
    const seconds = Math.max(1, Math.round((performance.now() - S.startedAt) / 1000));
    renderSummary(sum, seconds, reason);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    resetOverlay("intro");
    if (sum.reps > 0) track("coach_finished");
  }

  function renderSummary(sum, seconds, reason) {
    const faults = Object.entries(sum.faults).sort((a, b) => b[1] - a[1]);
    const mins = Math.floor(seconds / 60), secs = String(seconds % 60).padStart(2, "0");
    ui.summary.hidden = false;
    ui.summary.innerHTML = `
      <h3 class="h3">${reason === "limit" ? "Free session complete" : "Session summary"}</h3>
      <dl class="coach__sum">
        <div><dt>Reps</dt><dd>${sum.reps}</dd></div><div><dt>Average form</dt><dd>${sum.reps ? sum.avg : "--"}</dd></div>
        <div><dt>Best rep</dt><dd>${sum.reps ? sum.best : "--"}</dd></div><div><dt>Time</dt><dd>${mins}:${secs}</dd></div>
      </dl>
      ${faults.length ? `<p class="label">Fix next time</p><ul class="coach__faults">${faults.map(([k, n]) => `<li>${icon("warning")}<span>${esc(FAULT_TEXT[k] || k)} <b>x${n}</b></span></li>`).join("")}</ul>` : sum.reps ? `<p class="muted">Clean session. No repeated faults.</p>` : `<p class="muted">No full reps were counted. Make sure your whole body is in frame and go through the full range.</p>`}
      ${reason === "limit" ? `<p class="muted">Free sessions run for 3 minutes. Pro removes the limit and adds deadlift, push-up, pull-up and voice coaching.</p><a class="btn btn--primary btn--sm" href="#pricing">See Pro plans</a>` : ""}
      <div class="row mt-l" id="coach-save-row"></div>`;
    if (sum.reps > 0) saveSession(sum, seconds);
  }

  async function saveSession(sum, seconds) {
    const row = $("#coach-save-row");
    const payload = { exercise: S.ex, reps: sum.reps, avg_score: sum.avg, best_score: sum.best, duration_s: seconds, faults: sum.faults };
    const post = async () => {
      try {
        await api("/api/sessions", { method: "POST", body: payload });
        row.innerHTML = `<span class="status">Saved to your account</span> <a class="link" href="/account">View history</a>`;
      } catch (err) {
        row.innerHTML = `<span class="muted">${esc(err instanceof ApiError ? err.message : "Couldn't save this session.")}</span>`;
      }
    };
    if (state.user) return post();
    row.innerHTML = `<button class="btn btn--ghost btn--sm" type="button" id="coach-signin-save">Sign in to save this session</button>`;
    $("#coach-signin-save").addEventListener("click", async () => { if (await ensureUser("register")) post(); });
  }

  function tickTimer() {
    if (!S.running) return;
    const s = Math.floor((performance.now() - S.startedAt) / 1000);
    const cap = isPro() ? null : FREE_SECONDS;
    ui.timer.textContent = cap ? `${Math.floor((cap - s) / 60)}:${String(Math.max(0, (cap - s) % 60)).padStart(2, "0")} left` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    if (cap && s >= cap) return void stop("limit");
    setTimeout(tickTimer, 500);
  }

  // -------------------------------------------------------------- detection
  async function detectLoop() {
    let lastTime = -1;
    while (S.running) {
      if (video.readyState >= 2 && video.currentTime !== lastTime) {
        lastTime = video.currentTime;
        const t0 = performance.now();
        try { await S.pose.send({ image: video }); } catch (err) { console.warn("pose error", err); await new Promise((r) => setTimeout(r, 200)); }
        const dt = performance.now() - t0;
        S.fpsEma = S.fpsEma ? S.fpsEma * 0.9 + (1000 / Math.max(1, dt)) * 0.1 : 1000 / Math.max(1, dt);
        adaptQuality();
        tooSlowGuard();
      } else {
        await new Promise((r) => requestAnimationFrame(r));
      }
    }
  }

  /** Keep it smooth: if the device can't hold ~15 fps on the full model, drop to the lite model. */
  function adaptQuality() {
    ui.fps.textContent = `${Math.round(S.fpsEma)} fps`;
    if (debug) console.info("coach-fps", Math.round(S.fpsEma), "complexity", S.complexity);
    if (S.complexity === 0) return;
    if (S.fpsEma && S.fpsEma < 15) {
      S.slowSince ||= performance.now();
      if (performance.now() - S.slowSince > 3000) {
        S.complexity = 0;
        S.pose.setOptions({ modelComplexity: 0 });
        ui.fps.dataset.lite = "true";
        toast("Performance mode on: using the lighter model.");
      }
    } else S.slowSince = 0;
  }

  /** Software rendering (no GPU) can't run live pose. Say so instead of leaving a frozen page. */
  function tooSlowGuard() {
    if (S.complexity !== 0 || !S.fpsEma || S.fpsEma >= 5) { S.crawlSince = 0; return; }
    S.crawlSince ||= performance.now();
    if (performance.now() - S.crawlSince > 8000) {
      stop("slow").then(() => resetOverlay("error", "This browser is running without hardware graphics, so live pose tracking is too slow here. Turn on hardware acceleration in your browser settings, or try Chrome on a recent phone or laptop."));
    }
  }

  function onResults(results) {
    if (!S.running) return;
    const lm = results.poseLandmarks;
    if (!lm) {
      S.lostFrames += 1;
      if (S.lostFrames > 8) showCue({ id: "lost", severity: "warn", text: "I can't see you. Step back until your whole body is in frame." });
      return;
    }
    S.lostFrames = 0;
    process(S.smoother.smooth(lm, performance.now() / 1000));
  }

  function process(lm) {
    const F = prepare(lm, S.w, S.h, S.ex);
    S.target = F;
    if (F.quality < 0.5) return showCue({ id: "frame", severity: "warn", text: "Turn side-on and step back so I can see your whole body." });
    if (!S.cal.ready) {
      updateCal(S.cal, S.ex, F);
      ui.calBar.style.width = `${Math.round(S.cal.progress * 100)}%`;
      ui.calBar.parentElement.hidden = false;
      if (S.cal.ready) { ui.calBar.parentElement.hidden = true; showCue({ id: "go", severity: "ok", text: "Locked in. Start your first rep." }); }
      return;
    }
    const res = analyze(S.ex, F, S.cal, { shallow: S.tracker.shallow });
    S.res = res;
    S.ghost = res.ideal;
    S.faultIds = new Set(res.faults.map((f) => f.id));
    const ev = S.tracker.update(res);
    showCue(res.cue);
    ui.score.textContent = String(res.score);
    ui.score.dataset.level = res.score >= 85 ? "good" : res.score >= 65 ? "mid" : "low";
    ui.gauge.style.height = `${Math.round(res.d * 100)}%`;
    if (ev) onRep(ev);
  }

  function showCue(c) {
    const shown = S.stab ? S.stab.push(c) : c;
    if (ui.cue.dataset.id !== shown.id) {
      ui.cue.dataset.id = shown.id;
      ui.cue.dataset.severity = shown.severity;
      ui.cue.textContent = shown.text;
      stage.dataset.state = shown.severity;
      if (shown.severity === "warn") speak(shown.speak || shown.text);
    }
  }

  function onRep(ev) {
    ui.reps.textContent = String(ev.rep);
    ui.reps.classList.remove("pulse");
    void ui.reps.offsetWidth;
    ui.reps.classList.add("pulse");
    const tone = ev.score >= 85 ? "Great rep" : ev.score >= 65 ? "Decent rep" : "Rep needs work";
    stage.dataset.flash = ev.score >= 85 ? "good" : "warn";
    setTimeout(() => { delete stage.dataset.flash; }, 500);
    speak(`Rep ${ev.rep}. ${tone}, ${ev.score}.`, true);
    window.dispatchEvent(new Event("iron:strike"));
  }

  function speak(text, force = false) {
    if (!isPro() || !ui.voice.checked || !window.speechSynthesis) return;
    const now = performance.now();
    if (!force && now - S.lastSpoken < 3500) return;
    S.lastSpoken = now;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.08;
    window.speechSynthesis.speak(u);
  }

  // ---------------------------------------------------------------- render
  const lerp = (a, b, t) => a + (b - a) * t;
  let lastFrameT = performance.now();

  function smoothPoint(key, p, k) {
    const cur = S.disp[key];
    if (!cur) { S.disp[key] = { x: p.x, y: p.y }; return S.disp[key]; }
    cur.x = lerp(cur.x, p.x, k); cur.y = lerp(cur.y, p.y, k);
    return cur;
  }

  function render(now) {
    if (!S.running) return;
    S.renderLoop = requestAnimationFrame(render);
    const dt = Math.min(0.1, (now - lastFrameT) / 1000);
    lastFrameT = now;
    if (S.demo) {
      const idx = Math.floor(((now - S.startedAt) / 1000) * demoFps);
      if (idx - S.demoIdx > 10) S.demoIdx = idx - 10; // tab was throttled: skip ahead instead of replaying
      while (S.demoIdx < idx) { S.demoIdx += 1; process(demoFrame(S.ex, S.demoIdx).lm); }
    }
    drawFrame(1 - Math.exp(-dt * 16));
  }

  function drawFrame(k) {
    const w = canvas.width, h = canvas.height;
    const mirror = S.facing === "user" && !S.debugFrame;
    const X = (x) => (mirror ? w - x : x);
    if (S.debugFrame) {
      const bg = ctx.createRadialGradient(w * 0.5, h * 0.45, 40, w * 0.5, h * 0.5, w * 0.7);
      bg.addColorStop(0, "#2a0d17"); bg.addColorStop(1, "#0f0f10");
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = "rgba(255,255,255,0.045)";
      for (let x = 0; x < w; x += 80) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
      for (let y = 0; y < h; y += 80) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
      if (S.demo) {
        ctx.fillStyle = "rgba(240,116,138,0.9)"; ctx.font = "600 22px Inter, sans-serif"; ctx.textAlign = "right";
        ctx.fillText("DEMO  \u00b7  SIMULATED ATHLETE", w - 24, h - 26); ctx.textAlign = "left";
      }
    } else {
      ctx.save();
      if (mirror) { ctx.translate(w, 0); ctx.scale(-1, 1); }
      ctx.drawImage(video, 0, 0, w, h);
      ctx.restore();
      ctx.fillStyle = "rgba(20,12,16,0.28)"; // slight scrim so the overlay reads on any background
      ctx.fillRect(0, 0, w, h);
    }
    const F = S.target;
    if (!F) return;
    const u = w / 1280; // scale strokes with resolution
    const P = {};
    for (const key of ["sh", "el", "wr", "hip", "kn", "an", "heel", "toe"]) P[key] = smoothPoint(key, F.P[key], k);
    const pt = (p) => ({ x: X(p.x), y: p.y });

    // ghost coach: the ideal skeleton fitted to this body
    if (S.cal?.ready && ui.ghost.checked && S.ghost) {
      const g = {};
      for (const [name, p] of Object.entries(S.ghost.points)) if (p) g[name] = pt(smoothPoint(`g_${name}`, p, k));
      ctx.save();
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      ctx.setLineDash([16 * u, 12 * u]);
      ctx.strokeStyle = "rgba(240,116,138,0.95)"; ctx.lineWidth = 7 * u;
      ctx.shadowColor = "rgba(240,116,138,0.6)"; ctx.shadowBlur = 14 * u;
      const chain = S.ex === "pushup" ? ["ankle", "hip", "shoulder"] : S.ex === "pullup" ? ["wrist", "elbow", "shoulder"] : ["ankle", "knee", "hip", "shoulder"];
      ctx.beginPath();
      chain.forEach((name, i) => { const p = g[name]; if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y); });
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.shadowBlur = 0;
      if (g.head) { ctx.beginPath(); ctx.arc(g.head.x, g.head.y, 24 * u, 0, Math.PI * 2); ctx.lineWidth = 4 * u; ctx.stroke(); }
      ctx.fillStyle = "rgba(240,116,138,0.95)";
      for (const name of chain) { ctx.beginPath(); ctx.arc(g[name].x, g[name].y, 9 * u, 0, Math.PI * 2); ctx.fill(); }
      // how far off you are from where you should be: the hip for a leg exercise, the shoulder for a pull-up
      const devKey = S.ex === "pullup" ? "shoulder" : "hip";
      const devPoint = S.ex === "pullup" ? P.sh : P.hip;
      const devScale = S.ex === "pullup" ? (S.cal.armUpper + S.cal.armLower) : S.cal.L3;
      const devUser = pt(devPoint), devIdeal = g[devKey];
      if (devIdeal && Math.hypot(devUser.x - devIdeal.x, devUser.y - devIdeal.y) > 0.06 * devScale) {
        ctx.strokeStyle = "rgba(242,193,78,0.9)"; ctx.lineWidth = 3 * u; ctx.setLineDash([4 * u, 6 * u]);
        ctx.beginPath(); ctx.moveTo(devUser.x, devUser.y); ctx.lineTo(devIdeal.x, devIdeal.y); ctx.stroke();
      }
      ctx.restore();
    }

    // mid-foot plumb line (legs on the ground only - meaningless for a hanging pull-up)
    if (S.cal?.ready && S.ex !== "pushup" && S.ex !== "pullup") {
      const base = toWorld({ x: S.cal.midX, y: 0 }, F.P.an, F.dir);
      const bx = X(base.x);
      ctx.save();
      ctx.strokeStyle = "rgba(255,255,255,0.25)"; ctx.lineWidth = 2 * u; ctx.setLineDash([3 * u, 9 * u]);
      ctx.beginPath(); ctx.moveTo(bx, 0); ctx.lineTo(bx, F.P.toe.y); ctx.stroke();
      ctx.restore();
    }

    // your skeleton
    const warn = "rgba(242,193,78,1)", bone = "rgba(241,236,230,0.96)";
    const torsoWarn = S.faultIds.has("lean") || S.faultIds.has("hips") || S.faultIds.has("low") || S.faultIds.has("lean_back");
    const footWarn = S.faultIds.has("heels");
    const bodyWarn = S.faultIds.has("sag") || S.faultIds.has("pike");
    const armWarn = S.faultIds.has("kip");
    const seg = (a, b, color, width = 9) => {
      ctx.strokeStyle = color; ctx.lineWidth = width * u; ctx.lineCap = "round";
      const pa = pt(P[a]), pb = pt(P[b]);
      ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
    };
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.5)"; ctx.shadowBlur = 8 * u;
    if (S.ex === "pullup") {
      // legs are usually out of frame or irrelevant while hanging: draw the arm only
      seg("wr", "el", armWarn ? warn : bone, 7); seg("el", "sh", armWarn ? warn : bone, 7);
    } else {
      seg("an", "kn", bone); seg("kn", "hip", bone);
      seg("hip", "sh", torsoWarn || bodyWarn ? warn : bone);
      seg("sh", "el", bone, 7); seg("el", "wr", bone, 7);
      seg("heel", "toe", footWarn ? warn : bone, 7);
      seg("an", "heel", footWarn ? warn : bone, 5);
    }
    ctx.restore();
    ctx.fillStyle = "#f0748a";
    const dots = S.ex === "pullup" ? ["sh", "el", "wr"] : ["sh", "el", "wr", "hip", "kn", "an", "toe"];
    for (const key of dots) {
      const p = pt(P[key]);
      ctx.beginPath(); ctx.arc(p.x, p.y, (key === "kn" || key === "hip" ? 11 : 8) * u, 0, Math.PI * 2); ctx.fill();
    }
  }

  // ------------------------------------------------------------------- demo
  /** A simulated athlete runs through the real analysis, ghost and cue code. No camera needed. */
  function startDemo() {
    if (S.running) return;
    ui.summary.hidden = true;
    S.smoother = null; S.cal = newCal(); S.tracker = new RepTracker(S.ex); S.stab = new CueStabilizer(4);
    S.disp = {}; S.target = null; S.ghost = null; S.res = null; S.faultIds = new Set();
    S.w = DEMO_W; S.h = DEMO_H; canvas.width = DEMO_W; canvas.height = DEMO_H;
    stage.style.setProperty("--ar", `${DEMO_W} / ${DEMO_H}`);
    S.running = true; S.demo = true; S.debugFrame = true; S.startedAt = performance.now(); S.demoIdx = -1;
    overlay.hidden = true; ui.hud.hidden = false;
    ui.start.hidden = true; ui.stop.hidden = false; ui.stop.textContent = "Stop demo"; ui.flip.hidden = true;
    ui.reps.textContent = "0"; ui.score.textContent = "--"; ui.timer.textContent = "Demo"; ui.fps.textContent = "demo";
    showCue({ id: "cal", severity: "ok", text: "Demo with a simulated athlete. Watch the dotted ghost and the corrections." });
    S.renderLoop = requestAnimationFrame(render);
  }

  // --------------------------------------------------------------- controls
  $$("[data-coach-start]").forEach((b) => b.addEventListener("click", start));
  ui.stop.addEventListener("click", () => stop());
  $("#coach-retry")?.addEventListener("click", start);
  ui.demo.forEach((b) => b.addEventListener("click", startDemo));
  ui.flip.addEventListener("click", async () => {
    S.facing = S.facing === "user" ? "environment" : "user";
    stopStream();
    try { await startCamera(); } catch (err) { S.facing = S.facing === "user" ? "environment" : "user"; toast(friendly(err), "error"); await startCamera().catch(() => {}); }
  });
  ui.ghost.addEventListener("change", () => { if (!ui.ghost.checked) S.disp = {}; });
  document.addEventListener("visibilitychange", () => { if (document.hidden && S.running) stop(); });

  setExercise("squat");
  syncTabs();

  if (debug) {
    // Test hook (only with ?debug=1): feed landmarks without a camera to exercise the analysis and drawing.
    window.__coach = {
      begin(ex = "squat") {
        S.pro = true; setExercise(ex); syncTabs();
        S.smoother = new PoseSmoother(); S.cal = newCal(); S.tracker = new RepTracker(S.ex); S.stab = new CueStabilizer(3);
        S.running = true; S.debugFrame = true; S.startedAt = performance.now(); overlay.hidden = true; ui.hud.hidden = false;
        canvas.width = S.w = 1280; canvas.height = S.h = 720;
      },
      feed(lm) { process(lm); drawFrame(1); },
      stopDebug() { S.running = false; S.debugFrame = false; },
      get state() { return { cal: S.cal, res: S.res, reps: S.tracker?.summary() }; },
    };
  }
}
