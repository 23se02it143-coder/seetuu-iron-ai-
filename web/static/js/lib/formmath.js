// Pure pose maths for the camera form coach. No DOM, no camera: it takes MediaPipe landmarks in and gives cues out,
// so it can be unit-tested in Node (tests/js/formmath.test.mjs).
//
// Geometry works in a "local" frame: origin at the ankle, +x pointing the way the athlete faces, y pointing down.
// The ghost coach is built from the athlete's OWN limb lengths, so the ideal skeleton always fits their body.

export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
export const rad = (deg) => (deg * Math.PI) / 180;
export const deg = (r) => (r * 180) / Math.PI;

/** Interior angle at b (degrees) between segments b->a and b->c. */
export function angleAt(a, b, c) {
  const ux = a.x - b.x, uy = a.y - b.y, vx = c.x - b.x, vy = c.y - b.y;
  const m = Math.hypot(ux, uy) * Math.hypot(vx, vy);
  if (!m) return 180;
  return deg(Math.acos(clamp((ux * vx + uy * vy) / m, -1, 1)));
}

/** Degrees the shoulder is ahead of (+) or behind (-) the hip, measured from vertical, in the facing direction. */
export function leanFromVertical(hip, shoulder, dir) {
  return deg(Math.atan2((shoulder.x - hip.x) * dir, hip.y - shoulder.y));
}

/** Two-link inverse kinematics in local coordinates: where is the knee, given ankle A and hip H? Knee bends forward (+x). */
export function ik(A, H, l1, l2) {
  const dx = H.x - A.x, dy = H.y - A.y;
  const d = clamp(Math.hypot(dx, dy), Math.abs(l1 - l2) + 0.01, l1 + l2 - 0.01);
  const a = (l1 * l1 - l2 * l2 + d * d) / (2 * d);
  const h = Math.sqrt(Math.max(0, l1 * l1 - a * a));
  const ux = dx / Math.hypot(dx, dy || 1e-9), uy = dy / Math.hypot(dx, dy || 1e-9);
  const mx = A.x + a * ux, my = A.y + a * uy;
  const k1 = { x: mx - h * uy, y: my + h * ux };
  const k2 = { x: mx + h * uy, y: my - h * ux };
  return k1.x > k2.x ? k1 : k2;
}

// -------------------------------------------------------------- smoothing
/** One Euro filter: smooth when still, responsive when moving. Removes the "shaky skeleton" look. */
export class OneEuro {
  constructor(minCutoff = 1.4, beta = 0.03, dCutoff = 1) {
    this.minCutoff = minCutoff; this.beta = beta; this.dCutoff = dCutoff;
    this.x = null; this.dx = 0; this.t = null;
  }
  static alpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  filter(value, t) {
    if (this.x === null) { this.x = value; this.t = t; return value; }
    const dt = Math.max(1e-3, t - this.t);
    const dxRaw = (value - this.x) / dt;
    this.dx += OneEuro.alpha(this.dCutoff, dt) * (dxRaw - this.dx);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.dx);
    this.x += OneEuro.alpha(cutoff, dt) * (value - this.x);
    this.t = t;
    return this.x;
  }
}

export class PoseSmoother {
  constructor() { this.f = Array.from({ length: 33 }, () => ({ x: new OneEuro(), y: new OneEuro(), v: 0.5 })); }
  smooth(landmarks, tSec) {
    return landmarks.map((p, i) => {
      const f = this.f[i];
      f.v += 0.4 * ((p.visibility ?? 1) - f.v);
      return { x: f.x.filter(p.x, tSec), y: f.y.filter(p.y, tSec), visibility: f.v };
    });
  }
}

// ---------------------------------------------------------------- framing
const SIDE = {
  L: { sh: 11, el: 13, wr: 15, hip: 23, kn: 25, an: 27, heel: 29, toe: 31, ear: 7 },
  R: { sh: 12, el: 14, wr: 16, hip: 24, kn: 26, an: 28, heel: 30, toe: 32, ear: 8 },
};

/** Pick the side of the body the camera sees best and convert normalised landmarks to pixel coordinates. */
export function prepare(lm, w, h, exercise) {
  const vis = (ids) => ids.reduce((s, i) => s + (lm[i]?.visibility ?? 0), 0) / ids.length;
  const left = vis([11, 23, 25, 27, 31]);
  const right = vis([12, 24, 26, 28, 32]);
  const side = left >= right ? "L" : "R";
  const idx = SIDE[side];
  const P = {};
  for (const [k, i] of Object.entries(idx)) P[k] = { x: lm[i].x * w, y: lm[i].y * h, v: lm[i].visibility ?? 0 };
  const dir = exercise === "pushup" ? (P.sh.x >= P.an.x ? 1 : -1) : exercise === "pullup" ? 1 : P.toe.x >= P.heel.x ? 1 : -1;
  // a pull-up hangs the legs out of frame or crossed behind, so judge quality from the arm only, not the leg
  const quality = exercise === "pullup" ? Math.min(1, vis([idx.sh, idx.el, idx.wr])) : Math.min(1, vis([idx.sh, idx.hip, idx.kn, idx.an]));
  return { P, dir, side, quality };
}

export const toLocal = (p, origin, dir) => ({ x: (p.x - origin.x) * dir, y: p.y - origin.y });
export const toWorld = (q, origin, dir) => ({ x: origin.x + q.x * dir, y: origin.y + q.y });

// ------------------------------------------------------------ calibration
export function newCal() {
  return {
    n: 0, ready: false, progress: 0, L1: 0, L2: 0, L3: 0, standH: 0, footLen: 0, footFlat: 0, midX: 0, torso: 0, arm: 0,
    armUpper: 0, armLower: 0, kipBase: 0,
  };
}
const ema = (old, v, n) => (n === 0 ? v : old + 0.15 * (v - old));

/** Learn the athlete's proportions while they stand (or hang, or hold a plank). Returns true once enough clean frames were seen. */
export function updateCal(cal, ex, F) {
  const { P, dir, quality } = F;
  if (cal.ready || quality < 0.55) return cal.ready;
  const knee = angleAt(P.an, P.kn, P.hip);
  const lean = leanFromVertical(P.hip, P.sh, dir);
  let ok;
  if (ex === "pullup") {
    // dead hang: arms straight, hands clearly above the shoulder (gripping something overhead)
    ok = angleAt(P.sh, P.el, P.wr) > 155 && P.wr.y < P.sh.y - 0.3 * dist(P.sh, P.el);
  } else if (ex === "pushup") {
    const line = angleAt(P.an, P.hip, P.sh);
    ok = line > 160 && angleAt(P.sh, P.el, P.wr) > 150;
  } else {
    const reach = dist(P.an, P.kn) + dist(P.kn, P.hip);
    ok = knee > 150 && Math.abs(lean) < 25 && P.sh.y < P.hip.y && P.an.y - P.hip.y > 0.9 * reach; // standing, not part-way down
  }
  if (!ok) { cal.progress = Math.max(0, cal.progress - 0.02); return false; }
  cal.L1 = ema(cal.L1, dist(P.an, P.kn), cal.n);
  cal.L2 = ema(cal.L2, dist(P.kn, P.hip), cal.n);
  cal.L3 = ema(cal.L3, dist(P.hip, P.sh), cal.n);
  const armUpper = dist(P.sh, P.el), armLower = dist(P.el, P.wr);
  cal.armUpper = ema(cal.armUpper, armUpper, cal.n);
  cal.armLower = ema(cal.armLower, armLower, cal.n);
  cal.arm = ema(cal.arm, armUpper + armLower, cal.n);
  cal.kipBase = ema(cal.kipBase, (P.sh.x - P.wr.x) / Math.max(1, armUpper + armLower), cal.n);
  cal.standH = ema(cal.standH, P.an.y - P.hip.y, cal.n);
  const footLen = Math.max(1, dist(P.heel, P.toe));
  cal.footLen = ema(cal.footLen, footLen, cal.n);
  cal.footFlat = ema(cal.footFlat, (P.heel.y - P.toe.y) / footLen, cal.n);
  cal.midX = ema(cal.midX, (toLocal(P.heel, P.an, dir).x + toLocal(P.toe, P.an, dir).x) / 2, cal.n);
  cal.n += 1;
  cal.progress = Math.min(1, cal.n / 22);
  if (cal.n >= 22) cal.ready = true;
  return cal.ready;
}

// ------------------------------------------------------------ ideal pose
const CFG = {
  squat: { leanTop: 4, leanBottom: 40, shoulderBias: 0, hipRange: 0.52, downAt: 0.45, upAt: 0.18, depthGoal: 0.8 },
  deadlift: { leanTop: 4, leanBottom: 50, shoulderBias: 0.06, hipRange: 0.42, downAt: 0.5, upAt: 0.16, depthGoal: 0 },
  pushup: { downAt: 0.5, upAt: 0.2, depthGoal: 0.75 },
  pullup: { downAt: 0.35, upAt: 0.15, depthGoal: 0.75 },
};
export const config = (ex) => CFG[ex];

/** The ideal skeleton for this athlete at this depth, in world pixels. Hip height is taken from the athlete so it lines up. */
export function idealSagittal(ex, cal, d, F) {
  const c = CFG[ex];
  const { P, dir } = F;
  const th = rad(c.leanTop + (c.leanBottom - c.leanTop) * Math.pow(d, 1.1));
  const hipLocalY = P.hip.y - P.an.y;
  const S = { x: cal.midX + c.shoulderBias * cal.L1, y: 0 };
  const H = { x: S.x - cal.L3 * Math.sin(th), y: hipLocalY };
  S.y = H.y - cal.L3 * Math.cos(th);
  const K = ik({ x: 0, y: 0 }, H, cal.L1, cal.L2);
  const head = { x: S.x + 0.4 * cal.L3 * Math.sin(th * 0.7), y: S.y - 0.4 * cal.L3 * Math.cos(th * 0.7) };
  const w = (q) => toWorld(q, P.an, dir);
  return { leanDeg: deg(th), points: { ankle: w({ x: 0, y: 0 }), knee: w(K), hip: w(H), shoulder: w(S), head: w(head) } };
}

// ----------------------------------------------------------- exercise logic
const cue = (id, severity, text, speak) => ({ id, severity, text, speak: speak || text });
const OK = (text) => cue("good", "ok", text);

/** Squat, side view. */
function analyzeSquat(F, cal, state) {
  const { P, dir } = F;
  const c = CFG.squat;
  const hipH = P.an.y - P.hip.y;
  const d = clamp((1 - hipH / cal.standH) / c.hipRange, 0, 1);
  const knee = angleAt(P.an, P.kn, P.hip);
  const hip = angleAt(P.kn, P.hip, P.sh);
  const lean = leanFromVertical(P.hip, P.sh, dir);
  const ideal = idealSagittal("squat", cal, d, F);
  const heelRise = cal.footFlat - (P.heel.y - P.toe.y) / cal.footLen;
  const mid = toLocal(P.heel, P.an, dir).x / 2 + toLocal(P.toe, P.an, dir).x / 2;
  const bar = (toLocal(P.sh, P.an, dir).x - mid) / cal.L1;
  const depthOK = P.hip.y >= P.kn.y - 0.04 * cal.L2;
  const leanExcess = lean - ideal.leanDeg;

  const faults = [];
  if (d > 0.3 && leanExcess > 15) faults.push(cue("lean", "warn", "Chest up. You're folding forward.", "Chest up"));
  if (d > 0.25 && heelRise > 0.12) faults.push(cue("heels", "warn", "Heels are lifting. Press through mid-foot.", "Heels down"));
  if (d > 0.3 && bar > 0.4) faults.push(cue("bar", "warn", "Weight is drifting onto your toes. Sit back.", "Sit back"));
  if (d > 0.3 && bar < -0.4) faults.push(cue("bar", "warn", "You're sitting too far back. Bring your chest over mid-foot.", "Chest over your feet"));
  if (state.shallow) faults.push(cue("depth", "warn", "Go a little deeper: hips to knee height.", "Deeper"));

  let score = 100
    - clamp((leanExcess - 8) * 1.5, 0, 30)
    - clamp((heelRise - 0.06) * 250, 0, 30)
    - clamp((Math.abs(bar) - 0.25) * 60, 0, 25);
  score = Math.round(clamp(score, 35, 100));
  const primary = faults[0]
    || (d < 0.1 ? OK("Standing tall. Brace, breathe in, then sit back and down.")
      : depthOK ? OK("Good depth. Drive up through your whole foot.")
      : OK("Nice position. Keep your chest up and knees out."));
  return { d, score, cue: primary, faults, ideal, metrics: { knee, hip, lean, heelRise, bar, depthOK }, depthOK };
}

/** Conventional deadlift, side view. */
function analyzeDeadlift(F, cal) {
  const { P, dir } = F;
  const c = CFG.deadlift;
  const hipH = P.an.y - P.hip.y;
  const d = clamp((1 - hipH / cal.standH) / c.hipRange, 0, 1);
  const knee = angleAt(P.an, P.kn, P.hip);
  const hip = angleAt(P.kn, P.hip, P.sh);
  const lean = leanFromVertical(P.hip, P.sh, dir);
  const ideal = idealSagittal("deadlift", cal, d, F);
  const mid = toLocal(P.heel, P.an, dir).x / 2 + toLocal(P.toe, P.an, dir).x / 2;
  const bar = (toLocal(P.wr, P.an, dir).x - mid) / cal.L1; // hands hold the bar
  const leanDelta = lean - ideal.leanDeg;

  const faults = [];
  if (d > 0.3 && Math.abs(bar) > 0.4) faults.push(cue("bar", "warn", "Keep the bar over mid-foot, close to your legs.", "Bar close"));
  if (d > 0.3 && leanDelta > 16) faults.push(cue("hips", "warn", "Hips are shooting up. Chest up and push the floor away.", "Chest up"));
  if (d > 0.6 && leanDelta < -18) faults.push(cue("low", "warn", "Hips too low. Hinge back more, this isn't a squat.", "Hips back"));
  if (d < 0.12 && hip < 165) faults.push(cue("lockout", "warn", "Finish tall. Squeeze your glutes at the top.", "Stand tall"));
  if (d < 0.12 && lean < -8) faults.push(cue("lean_back", "warn", "Don't lean back at the top. Stand tall.", "Don't lean back"));

  let score = 100
    - clamp((Math.abs(bar) - 0.3) * 60, 0, 25)
    - clamp((leanDelta - 10) * 1.4, 0, 30)
    - clamp((-leanDelta - 12) * 1.2, 0, 20)
    - (d < 0.12 && hip < 165 ? 10 : 0);
  score = Math.round(clamp(score, 35, 100));
  const primary = faults[0] || (d < 0.1 ? OK("Set your lats, brace hard, then push the floor away.") : OK("Strong pull. Bar close, back flat."));
  return { d, score, cue: primary, faults, ideal, metrics: { knee, hip, lean, bar }, depthOK: true };
}

/** Push-up, side view. */
function analyzePushup(F, cal) {
  const { P, dir } = F;
  const elbow = angleAt(P.sh, P.el, P.wr);
  const d = clamp((165 - elbow) / (165 - 85), 0, 1);
  const torso = Math.max(1, dist(P.hip, P.sh));
  // signed distance of the hip from the ankle-shoulder line (+ = sagging toward the floor)
  const ax = P.an.x, ay = P.an.y, bx = P.sh.x, by = P.sh.y;
  const lineY = ay + ((P.hip.x - ax) / (bx - ax || 1e-6)) * (by - ay);
  const sag = (P.hip.y - lineY) / torso;
  const line = angleAt(P.an, P.hip, P.sh);
  const t = clamp((P.hip.x - ax) / (bx - ax || 1e-6), 0, 1);
  const idealHip = { x: P.hip.x, y: ay + t * (by - ay) };

  const faults = [];
  if (sag > 0.11) faults.push(cue("sag", "warn", "Hips are sagging. Squeeze glutes and brace your abs.", "Hips up"));
  if (sag < -0.11) faults.push(cue("pike", "warn", "Hips too high. Make one straight line.", "Hips down"));
  let score = 100 - clamp((Math.abs(sag) - 0.05) * 220, 0, 45);
  score = Math.round(clamp(score, 35, 100));
  const primary = faults[0] || (d < 0.1 ? OK("Strong plank. Lower with control.") : d > 0.75 ? OK("Good depth. Press the floor away.") : OK("Straight body line. Keep going."));
  return {
    d, score, cue: primary, faults,
    ideal: { leanDeg: 0, points: { ankle: P.an, hip: idealHip, shoulder: P.sh, knee: null, head: null } },
    metrics: { elbow, line, sag }, depthOK: true,
  };
}

/** The ghost for a pull-up: rooted at the wrist (the bar doesn't move; the body does), arms bent to
 * the athlete's own current depth but with zero horizontal swing, since swing (kipping) - not depth -
 * is the thing being coached here. Reuses the same wrist->elbow->shoulder IK as the leg chain. */
function idealPullup(cal, d, F) {
  const { P, dir } = F;
  const total = cal.armUpper + cal.armLower;
  const H = { x: 0, y: -total * (1 - d * 0.3) };
  const E = ik({ x: 0, y: 0 }, H, cal.armLower, cal.armUpper);
  const w = (q) => toWorld(q, P.wr, dir);
  return { points: { wrist: w({ x: 0, y: 0 }), elbow: w(E), shoulder: w(H), head: w({ x: H.x, y: H.y - 0.5 * cal.armUpper }) } };
}

/** Pull-up, side view, hands fixed on a bar above the camera's view of the shoulder. */
function analyzePullup(F, cal, state) {
  const { P } = F;
  const elbow = angleAt(P.sh, P.el, P.wr);
  const d = clamp((165 - elbow) / (165 - 35), 0, 1);
  const armTotal = Math.max(1, cal.armUpper + cal.armLower);
  const kip = Math.abs((P.sh.x - P.wr.x) / armTotal - cal.kipBase); // swing away from the athlete's own still baseline
  const ideal = idealPullup(cal, d, F);

  const faults = [];
  if (d > 0.35 && kip > 0.22) faults.push(cue("kip", "warn", "You're swinging. Keep your body still and pull straight up.", "Stay still"));
  if (state.shallow) faults.push(cue("depth", "warn", "Pull until your chin clears the bar.", "Chin over the bar"));

  let score = 100 - clamp((kip - 0.12) * 140, 0, 35);
  score = Math.round(clamp(score, 35, 100));
  const primary = faults[0]
    || (d < 0.1 ? OK("Dead hang. Set your shoulder blades, then pull.")
      : d > 0.85 ? OK("Chin over the bar. Lower with control.")
      : OK("Good pull. Elbows driving down and back."));
  return { d, score, cue: primary, faults, ideal, metrics: { elbow, kip }, depthOK: true };
}

export function analyze(ex, F, cal, state = {}) {
  if (ex === "squat") return analyzeSquat(F, cal, state);
  if (ex === "deadlift") return analyzeDeadlift(F, cal);
  if (ex === "pullup") return analyzePullup(F, cal, state);
  return analyzePushup(F, cal);
}

// ----------------------------------------------------------- rep counting
export class RepTracker {
  constructor(ex) {
    this.ex = ex; this.c = CFG[ex];
    this.phase = "up"; this.maxD = 0; this.frames = []; this.faults = new Set();
    this.reps = 0; this.repScores = []; this.faultCounts = {}; this.shallow = false;
  }
  /** Feed one analysed frame. Returns a finished-rep summary or null. */
  update(res) {
    const { d, score, faults } = res;
    if (this.phase === "up") {
      if (d > this.c.downAt) { this.phase = "down"; this.maxD = d; this.frames = []; this.faults = new Set(); this.shallow = false; }
      return null;
    }
    this.maxD = Math.max(this.maxD, d);
    this.frames.push(score);
    faults.forEach((f) => { if (f.id !== "depth") this.faults.add(f.id); });
    const rising = d < this.maxD - 0.07;
    if (this.c.depthGoal && rising && this.maxD < this.c.depthGoal) this.shallow = true;
    if (d < this.c.upAt) {
      this.phase = "up";
      const shallow = this.c.depthGoal > 0 && this.maxD < this.c.depthGoal;
      if (shallow) this.faults.add("depth");
      // judge the rep by its worst moments (bottom 40% of frames), so a fault can't be averaged away
      const sorted = [...this.frames].sort((a, b) => a - b).slice(0, Math.max(1, Math.ceil(this.frames.length * 0.4)));
      const avg = sorted.reduce((a, b) => a + b, 0) / sorted.length;
      const score = Math.round(clamp(avg - (shallow ? 12 : 0), 30, 100));
      this.reps += 1;
      this.repScores.push(score);
      this.faults.forEach((f) => { this.faultCounts[f] = (this.faultCounts[f] || 0) + 1; });
      const summary = { rep: this.reps, score, shallow, faults: [...this.faults] };
      this.frames = []; this.shallow = false;
      return summary;
    }
    return null;
  }
  summary() {
    const n = this.repScores.length;
    return {
      reps: n,
      avg: n ? Math.round(this.repScores.reduce((a, b) => a + b, 0) / n) : 0,
      best: n ? Math.max(...this.repScores) : 0,
      faults: { ...this.faultCounts },
    };
  }
}

/** A cue must persist for a few frames before it replaces the current one, so text never flickers. */
export class CueStabilizer {
  constructor(hold = 5) { this.hold = hold; this.current = null; this.cand = null; this.count = 0; }
  push(cue) {
    if (!this.current) { this.current = cue; return cue; }
    if (cue.id === this.current.id) { this.current = cue; this.cand = null; this.count = 0; return cue; }
    if (this.cand && this.cand.id === cue.id) this.count += 1; else { this.cand = cue; this.count = 1; }
    if (this.count >= this.hold || (cue.severity === "warn" && this.count >= 3)) { this.current = cue; this.cand = null; this.count = 0; }
    return this.current;
  }
}
