// Simulated athletes (side-on, facing right, 1280x720). They drive the coach's demo mode, so the feature can be seen
// without a camera, and they are the test fixtures in tests/js/formmath.test.mjs. Same kinematics as the Form Lab figure.
import { ik } from "./formmath.js";

export const DEMO_W = 1280;
export const DEMO_H = 720;
const K = 1.6;
const blank = () => Array.from({ length: 33 }, () => ({ x: 0, y: 0, visibility: 0.02 }));
const put = (lm, i, p) => { lm[i] = { x: p.x / DEMO_W, y: p.y / DEMO_H, visibility: 0.99 }; };

/** depth 0 (standing) .. 1 (bottom). lean = torso lean at the bottom (deg), heel = px of heel lift at the bottom. */
export function squatPose(depth, { lean = 40, heel = 0 } = {}) {
  const L1 = 88 * K, L2 = 92 * K, L3 = 118 * K, TOE = { x: 700, y: 660 };
  const lift = heel * K * Math.pow(depth, 1.1), phi = Math.asin(Math.min(1, lift / (72 * K)));
  const c = Math.cos(phi), s = Math.sin(phi), v = { x: -52 * K, y: -26 * K };
  const A = { x: TOE.x + v.x * c - v.y * s, y: TOE.y + v.x * s + v.y * c };
  const heelPt = { x: TOE.x - 72 * K * c, y: TOE.y - 72 * K * s };
  const Hp = { x: A.x - (8 + depth * 59) * K, y: A.y - (176 - depth * 96) * K };
  const l = ik({ x: 0, y: 0 }, { x: Hp.x - A.x, y: Hp.y - A.y }, L1, L2);
  const Kn = { x: A.x + l.x, y: A.y + l.y };
  const th = ((4 + (lean - 4) * Math.pow(depth, 1.15)) * Math.PI) / 180;
  const S = { x: Hp.x + L3 * Math.sin(th), y: Hp.y - L3 * Math.cos(th) };
  const lm = blank();
  put(lm, 27, A); put(lm, 25, Kn); put(lm, 23, Hp); put(lm, 11, S); put(lm, 29, heelPt); put(lm, 31, TOE);
  put(lm, 13, { x: S.x + 20, y: S.y + 80 }); put(lm, 15, { x: S.x + 10, y: S.y + 160 }); put(lm, 7, { x: S.x + 20, y: S.y - 60 });
  return lm;
}

/** t: 0 = lockout, 1 = bar on the floor. barOff = how far the bar drifts from mid-foot (shin lengths). */
export function deadliftPose(t, { barOff = 0.05, leanBottom = 50 } = {}) {
  const L1 = 88 * K, L2 = 92 * K, L3 = 118 * K, TOE = { x: 700, y: 660 };
  const A = { x: TOE.x - 52 * K, y: TOE.y - 26 * K };
  const heelPt = { x: TOE.x - 72 * K, y: TOE.y };
  const midLocal = (heelPt.x + TOE.x) / 2 - A.x;
  const th = ((4 + (leanBottom - 4) * Math.pow(t, 1.1)) * Math.PI) / 180;
  const S = { x: A.x + midLocal + 0.06 * L1, y: 0 };
  const Hp = { x: 0, y: A.y - 176 * K * (1 - 0.42 * t) };
  Hp.x = S.x - L3 * Math.sin(th);
  S.y = Hp.y - L3 * Math.cos(th);
  const l = ik({ x: 0, y: 0 }, { x: Hp.x - A.x, y: Hp.y - A.y }, L1, L2);
  const Kn = { x: A.x + l.x, y: A.y + l.y };
  const lm = blank();
  put(lm, 27, A); put(lm, 25, Kn); put(lm, 23, Hp); put(lm, 11, S); put(lm, 29, heelPt); put(lm, 31, TOE);
  put(lm, 15, { x: A.x + midLocal + barOff * L1, y: A.y - 30 * K }); put(lm, 13, { x: S.x, y: (S.y + A.y) / 2 });
  return lm;
}

/** e = elbow angle (165 top, 85 bottom). sag = hip drop in torso lengths (+ toward the floor). */
export function pushupPose(e, { sag = 0 } = {}) {
  const a = 140, floor = 620, Wx = 900;
  const chord = 2 * a * Math.sin((e * Math.PI) / 360);
  const S = { x: Wx, y: floor - chord };
  const A = { x: 200, y: floor + 10 };
  const wr = { x: Wx, y: floor };
  const el = { x: Wx - Math.sqrt(Math.max(0, a * a - (chord / 2) ** 2)), y: floor - chord / 2 };
  const t = 0.55;
  const torso = Math.hypot(S.x - (A.x + t * (S.x - A.x)), S.y - (A.y + t * (S.y - A.y)));
  const Hp = { x: A.x + t * (S.x - A.x), y: A.y + t * (S.y - A.y) + sag * torso };
  const lm = blank();
  put(lm, 27, A); put(lm, 23, Hp); put(lm, 11, S); put(lm, 13, el); put(lm, 15, wr);
  put(lm, 25, { x: (A.x + Hp.x) / 2, y: (A.y + Hp.y) / 2 }); put(lm, 29, { x: A.x + 10, y: A.y + 5 }); put(lm, 31, { x: A.x - 20, y: A.y + 12 });
  return lm;
}

/** d: 0 dead hang .. 1 chin over the bar. kip: fraction of total arm length the shoulder swings away from
 * directly under the wrist (matches what the analyzer measures, so a test can assert on the input value).
 * Wrist is the fixed pivot (the bar doesn't move) and the shoulder is driven explicitly, exactly mirroring
 * squatPose's ankle/hip roles; the elbow is IK-solved between them, same as the knee is for a squat. */
export function pullupPose(d, { kip = 0 } = {}) {
  const Lw = 60 * K, Lu = 66 * K; // forearm (wrist->elbow), upper arm (elbow->shoulder)
  const total = Lw + Lu;
  const wrist = { x: 700, y: 220 };
  const shoulder = { x: wrist.x + kip * total, y: wrist.y + total * (1 - d * 0.6) };
  const l = ik({ x: 0, y: 0 }, { x: shoulder.x - wrist.x, y: shoulder.y - wrist.y }, Lw, Lu);
  const elbow = { x: wrist.x + l.x, y: wrist.y + l.y };
  const lm = blank();
  put(lm, 15, wrist); put(lm, 13, elbow); put(lm, 11, shoulder);
  put(lm, 7, { x: shoulder.x, y: shoulder.y - 40 });
  // legs hang low in frame with poor visibility, same as a real hanging pull-up filmed from a normal distance
  const legY = shoulder.y + 300;
  put(lm, 23, { x: shoulder.x, y: legY }); put(lm, 25, { x: shoulder.x, y: legY + 90 }); put(lm, 27, { x: shoulder.x, y: legY + 180 });
  put(lm, 29, { x: shoulder.x - 10, y: legY + 185 }); put(lm, 31, { x: shoulder.x + 10, y: legY + 190 });
  for (const i of [23, 25, 27, 29, 31]) lm[i].visibility = 0.05;
  return lm;
}

// ---------------------------------------------------------------- demo timeline
const FPS = 30;
const CAL_FRAMES = 30; // standing still while the coach learns the body
const REP = 66; // frames per rep (2.2 s)
const REST = 14;
const ease = (u) => 0.5 - 0.5 * Math.cos(Math.PI * Math.min(1, Math.max(0, u)));

// each rep is [description, options]. The second rep has faults on purpose so you can see the corrections.
const REPS = {
  squat: [["clean", {}], ["faulty", { lean: 74, heel: 26 }], ["clean", {}]],
  deadlift: [["clean", {}], ["faulty", { barOff: 0.9, leanBottom: 84 }], ["clean", {}]],
  pushup: [["clean", {}], ["faulty", { sag: 0.22 }], ["clean", {}]],
  pullup: [["clean", {}], ["faulty", { kip: 0.32 }], ["clean", {}]],
};
const POSE = { squat: (d, o) => squatPose(d, o), deadlift: (d, o) => deadliftPose(d, o), pushup: (d, o) => pushupPose(165 - 80 * d, o), pullup: (d, o) => pullupPose(d, o) };

export const demoFps = FPS;

// shrink the athlete a little so the head and feet stay clear of the on-screen cue and stats
const FIT = 0.72;
const fit = (lm) => lm.map((p) => ({ x: (640 + (p.x * DEMO_W - 700) * FIT) / DEMO_W, y: (650 - (660 - p.y * DEMO_H) * FIT) / DEMO_H, visibility: p.visibility }));

/** Landmarks for demo frame i. Frames 0..CAL are the calibration stand; then reps loop forever. */
export function demoFrame(exercise, i) {
  const pose = POSE[exercise];
  if (i < CAL_FRAMES) return { lm: fit(pose(0, {})), label: "calibrating" };
  const cycle = REPS[exercise].length * (REP + REST);
  const j = (i - CAL_FRAMES) % cycle;
  const idx = Math.floor(j / (REP + REST));
  const k = j - idx * (REP + REST);
  const [label, opts] = REPS[exercise][idx];
  const d = k >= REP ? 0 : ease(k < REP / 2 ? k / (REP / 2) : 1 - (k - REP / 2) / (REP / 2));
  return { lm: fit(pose(d, opts)), label };
}
