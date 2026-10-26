// Form Lab: a simulated side-view squat with joint angles and coaching cues.
// Two-link inverse kinematics places the knee from the hip and ankle, so angles are real geometry, not canned frames.
import { $, $$, prefersReducedMotion } from "../lib/dom.js";

const L1 = 88;   // shin
const L2 = 92;   // thigh
const L3 = 118;  // torso
const FOOT = 72;
const TOE = { x: 255, y: 350 };
const ANKLE_FROM_TOE = { x: -52, y: -26 };
const MIDFOOT_X = TOE.x - 36;
const FAULTS = { clean: { lean: 40, heel: 0 }, lean: { lean: 68, heel: 0 }, heels: { lean: 45, heel: 20 } };

const sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y });
const len = (v) => Math.hypot(v.x, v.y);
const angleBetween = (u, v) => (Math.acos(Math.max(-1, Math.min(1, (u.x * v.x + u.y * v.y) / (len(u) * len(v))))) * 180) / Math.PI;

function ik(A, H) {
  const dx = H.x - A.x, dy = H.y - A.y;
  const d = Math.min(Math.max(Math.hypot(dx, dy), Math.abs(L1 - L2) + 0.01), L1 + L2 - 0.01);
  const a = (L1 * L1 - L2 * L2 + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, L1 * L1 - a * a));
  const mx = A.x + (a * dx) / d, my = A.y + (a * dy) / d;
  const k1 = { x: mx + (h * dy) / d, y: my - (h * dx) / d };
  const k2 = { x: mx - (h * dy) / d, y: my + (h * dx) / d };
  return k1.x > k2.x ? k1 : k2; // knee always bends forward
}

function pose(depth, fault) {
  const f = FAULTS[fault];
  const heel = f.heel * Math.pow(depth, 1.1);
  const phi = Math.asin(Math.min(1, heel / FOOT));
  const c = Math.cos(phi), s = Math.sin(phi);
  const A = { x: TOE.x + ANKLE_FROM_TOE.x * c - ANKLE_FROM_TOE.y * s, y: TOE.y + ANKLE_FROM_TOE.x * s + ANKLE_FROM_TOE.y * c };
  const heelPt = { x: TOE.x - FOOT * c, y: TOE.y - FOOT * s };
  const H = { x: A.x - (8 + depth * 59), y: A.y - (176 - depth * 96) };
  const K = ik(A, H);
  const lean = 3 + (f.lean - 3) * Math.pow(depth, 1.15);
  const th = (lean * Math.PI) / 180;
  const S = { x: H.x + L3 * Math.sin(th), y: H.y - L3 * Math.cos(th) };
  const head = { x: S.x + 46 * Math.sin(th * 0.7), y: S.y - 46 * Math.cos(th * 0.7) };
  return { A, K, H, S, head, heelPt, heel, lean };
}

export function initFormLab() {
  const svg = $("#lab-svg");
  if (!svg) return;
  const slider = $("#lab-depth");
  const stage = $("#lab-stage");
  const set = (id, attrs) => { const el = $(id, svg); Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, typeof v === "number" ? v.toFixed(1) : v)); return el; };
  let depth = 0;
  let fault = "clean";
  let anim = 0;

  function render() {
    const p = pose(depth, fault);
    const { A, K, H, S, head } = p;
    set("#lab-foot", { points: `${p.heelPt.x.toFixed(1)},${p.heelPt.y.toFixed(1)} ${TOE.x},${TOE.y}` });
    set("#lab-shin", { x1: A.x, y1: A.y, x2: K.x, y2: K.y });
    set("#lab-thigh", { x1: K.x, y1: K.y, x2: H.x, y2: H.y });
    set("#lab-torso", { x1: H.x, y1: H.y, x2: S.x, y2: S.y });
    set("#lab-neck", { x1: S.x, y1: S.y, x2: head.x, y2: head.y });
    set("#lab-head", { cx: head.x, cy: head.y });
    set("#lab-plate", { cx: S.x, cy: S.y });
    set("#lab-bar", { cx: S.x, cy: S.y });
    set("#lab-j-ankle", { cx: A.x, cy: A.y });
    set("#lab-j-knee", { cx: K.x, cy: K.y });
    set("#lab-j-hip", { cx: H.x, cy: H.y });
    set("#lab-plumb", { x1: S.x, y1: S.y + 22, x2: S.x, y2: 350 });
    set("#lab-mid", { d: `M${MIDFOOT_X - 7} 350 L${MIDFOOT_X + 7} 350 L${MIDFOOT_X} 340 Z` });

    // angles
    const u1 = sub(A, K), u2 = sub(H, K);
    const knee = angleBetween(u1, u2);
    const hip = angleBetween(sub(K, H), sub(S, H));
    const n1 = { x: u1.x / len(u1), y: u1.y / len(u1) }, n2 = { x: u2.x / len(u2), y: u2.y / len(u2) };
    const r = 26;
    const cross = n1.x * n2.y - n1.y * n2.x;
    set("#lab-arc", { d: `M${(K.x + r * n1.x).toFixed(1)} ${(K.y + r * n1.y).toFixed(1)} A ${r} ${r} 0 0 ${cross > 0 ? 1 : 0} ${(K.x + r * n2.x).toFixed(1)} ${(K.y + r * n2.y).toFixed(1)}` });
    const label = set("#lab-arc-label", { x: K.x + 36, y: K.y + 22 });
    label.textContent = `${Math.round(knee)}\u00b0`;

    // judgement
    const depthOK = H.y >= K.y - 3;
    const barOff = S.x - MIDFOOT_X;
    let score = 100 - Math.max(0, p.lean - 52) * 1.6 - p.heel * 1.8 - Math.max(0, Math.abs(barOff) - 25) * 0.5 - (depth > 0.55 && !depthOK ? 6 : 0);
    score = Math.round(Math.max(40, Math.min(100, score)));
    let state = "ok";
    let cue;
    let torsoWarn = false, footWarn = false;
    if (depth < 0.08) cue = "Standing tall. Brace, take a breath and start the descent.";
    else if (p.heel > 7) { state = "warn"; footWarn = true; cue = "Heels are lifting. Keep your whole foot on the floor; work on ankle mobility or use a small wedge."; }
    else if (p.lean > 52 && depth > 0.3) { state = "warn"; torsoWarn = true; cue = "Chest is folding forward and the bar has drifted ahead of mid-foot. Brace harder and keep your chest up."; }
    else if (depth > 0.55 && !depthOK) cue = "Nearly there. A little deeper takes the hip crease to knee height.";
    else if (depthOK) cue = Math.abs(barOff) <= 25 ? "Depth reached with the bar over mid-foot. Drive up through the whole foot." : "Depth reached. Drive up through the whole foot.";
    else cue = Math.abs(barOff) <= 25 ? "Good position. Knees track over the toes and the bar stays over mid-foot." : "Keep your chest tall and the bar over mid-foot.";

    stage.dataset.state = state;
    $("#lab-torso", svg).classList.toggle("is-warn", torsoWarn);
    $("#lab-foot", svg).classList.toggle("is-warn", footWarn);
    $("#lab-score").textContent = String(score);
    $("#lab-cue-text").textContent = cue;
    $("#lab-knee").textContent = `${Math.round(knee)}\u00b0`;
    $("#lab-hip").textContent = `${Math.round(hip)}\u00b0`;
    $("#lab-lean").textContent = `${Math.round(p.lean)}\u00b0`;
    $("#lab-depth-state").textContent = depth < 0.08 ? "Standing" : depthOK ? "At depth" : "Above parallel";
    return cue;
  }

  const announce = () => { $("#lab-sr").textContent = `${$("#lab-cue-text").textContent} Knee angle ${$("#lab-knee").textContent}.`; };

  function setDepth(d) { depth = Math.max(0, Math.min(1, d)); slider.value = String(Math.round(depth * 100)); render(); }

  function play() {
    cancelAnimationFrame(anim);
    if (prefersReducedMotion()) { setDepth(1); announce(); return; }
    const start = performance.now();
    const from = depth;
    const down = (1 - from) * 1400 + 200;
    const total = down + 1400 * (1) * 0.9 + 350;
    const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
    const tick = (now) => {
      const t = now - start;
      if (t < down) setDepth(from + (1 - from) * ease(t / down));
      else if (t < down + 350) setDepth(1);
      else if (t < total) setDepth(1 - ease((t - down - 350) / (total - down - 350)));
      else { setDepth(0); announce(); return; }
      anim = requestAnimationFrame(tick);
    };
    anim = requestAnimationFrame(tick);
  }

  slider.addEventListener("input", () => { cancelAnimationFrame(anim); setDepth(slider.value / 100); });
  slider.addEventListener("change", announce);
  $$('input[name="fault"]').forEach((r) => r.addEventListener("change", () => {
    fault = r.value;
    if (depth < 0.4) { setDepth(0.85); } else render();
    announce();
  }));
  $("#lab-play").addEventListener("click", play);

  render();
  // one demonstration rep the first time the lab scrolls into view
  new IntersectionObserver((entries, io) => {
    if (entries[0].isIntersecting) { io.disconnect(); if (depth === 0) play(); }
  }, { threshold: 0.55 }).observe(stage);
}
