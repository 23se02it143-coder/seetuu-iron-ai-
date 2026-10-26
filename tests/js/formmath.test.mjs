// Run with: node --test tests/js
import test from "node:test";
import assert from "node:assert/strict";
import { prepare, newCal, updateCal, analyze, RepTracker, CueStabilizer, ik, OneEuro, angleAt } from "../../web/static/js/lib/formmath.js";
import { squatPose, deadliftPose, pushupPose, pullupPose, demoFrame } from "../../web/static/js/lib/demo.js";

const W = 1280, H = 720;
const squat = squatPose, deadlift = deadliftPose, pushup = pushupPose, pullup = pullupPose;

function run(ex, make, steps, opts = {}) {
  const cal = newCal(), tracker = new RepTracker(ex), out = { events: [], frames: [] };
  for (let i = 0; i < 40; i++) { const F = prepare(make(ex === "pushup" ? 165 : 0, opts.calOpts || {}), W, H, ex); updateCal(cal, ex, F); }
  assert.equal(cal.ready, true, "calibration should complete on a still, correct starting pose");
  for (const x of steps) {
    const F = prepare(make(x, opts.rep || {}), W, H, ex);
    const res = analyze(ex, F, cal, { shallow: tracker.shallow });
    const ev = tracker.update(res);
    out.frames.push(res);
    if (ev) out.events.push(ev);
  }
  out.tracker = tracker; out.cal = cal;
  return out;
}
const up = (n, top) => Array.from({ length: n }, (_, i) => (top * i) / (n - 1));
const cycle = (top, n = 24) => [...up(n, top), ...up(n, top).reverse(), 0, 0, 0];

// ---- tests ---------------------------------------------------------------
test("one euro filter smooths jitter but follows real movement", () => {
  const f = new OneEuro();
  let last = 0, still = [];
  for (let i = 0; i < 60; i++) { last = f.filter(100 + (i % 2 ? 1.5 : -1.5), i / 30); if (i > 20) still.push(last); }
  assert.ok(Math.max(...still) - Math.min(...still) < 2, "jitter around a still point should be damped");
  for (let i = 60; i < 75; i++) last = f.filter(300, i / 30);
  assert.ok(last > 250, "a real jump must be followed quickly");
});

test("ik places the knee forward and keeps limb lengths", () => {
  const k = ik({ x: 0, y: 0 }, { x: -60, y: -120 }, 90, 95);
  assert.ok(k.x > -30);
  assert.ok(Math.abs(Math.hypot(k.x, k.y) - 90) < 0.5);
  assert.ok(Math.abs(Math.hypot(k.x + 60, k.y + 120) - 95) < 0.5);
});

test("squat: a clean rep is counted and scores well", () => {
  const r = run("squat", (d, o) => squat(d, o), cycle(1));
  assert.equal(r.events.length, 1);
  assert.ok(r.events[0].score >= 88, `score ${r.events[0].score}`);
  assert.deepEqual(r.events[0].faults, []);
  assert.equal(r.frames.find((f) => f.d > 0.95).cue.id, "good");
});

test("squat: folding forward is flagged", () => {
  const r = run("squat", (d, o) => squat(d, o), cycle(1), { rep: { lean: 70 } });
  assert.ok(r.frames.some((f) => f.faults.some((x) => x.id === "lean")));
  assert.ok(r.events[0].faults.includes("lean") && r.events[0].score < 85);
});

test("squat: rising heels are flagged", () => {
  const r = run("squat", (d, o) => squat(d, o), cycle(1), { rep: { heel: 22 } });
  assert.ok(r.frames.some((f) => f.faults.some((x) => x.id === "heels")));
  assert.ok(r.events[0].faults.includes("heels"));
});

test("squat: a half rep is counted but marked shallow", () => {
  const r = run("squat", (d, o) => squat(d, o), cycle(0.55));
  assert.equal(r.events.length, 1);
  assert.equal(r.events[0].shallow, true);
  assert.ok(r.events[0].faults.includes("depth"));
});

test("squat: the ghost coach keeps the athlete's own ankle and hip height", () => {
  const r = run("squat", (d, o) => squat(d, o), cycle(1));
  const F = prepare(squat(1), W, H, "squat");
  const g = analyze("squat", F, r.cal).ideal.points;
  assert.ok(Math.abs(g.ankle.y - F.P.an.y) < 1 && Math.abs(g.hip.y - F.P.hip.y) < 1);
  assert.ok(Math.abs(Math.hypot(g.knee.x - g.ankle.x, g.knee.y - g.ankle.y) - r.cal.L1) < 2, "ideal shin length matches the athlete");
});

test("deadlift: clean pull vs bar drifting away", () => {
  const good = run("deadlift", (t, o) => deadlift(t, o), cycle(1));
  assert.equal(good.events.length, 1);
  assert.ok(good.events[0].score >= 85, `score ${good.events[0].score}`);
  const bad = run("deadlift", (t, o) => deadlift(t, o), cycle(1), { rep: { barOff: 0.9 } });
  assert.ok(bad.frames.some((f) => f.faults.some((x) => x.id === "bar")));
});

test("deadlift: rounding forward too far (hips shooting up) is flagged", () => {
  const r = run("deadlift", (t, o) => deadlift(t, o), cycle(1), { rep: { leanBottom: 82 } });
  assert.ok(r.frames.some((f) => f.faults.some((x) => x.id === "hips")));
});

test("push-up: straight body counts, sagging hips are flagged", () => {
  const good = run("pushup", (e, o) => pushup(e, o), [...up(20, 1).map((t) => 165 - 80 * t), ...up(20, 1).reverse().map((t) => 165 - 80 * t), 165, 165]);
  assert.equal(good.events.length, 1);
  assert.ok(good.events[0].score >= 90, `score ${good.events[0].score}`);
  const sag = run("pushup", (e, o) => pushup(e, o), [...up(20, 1).map((t) => 165 - 80 * t), ...up(20, 1).reverse().map((t) => 165 - 80 * t), 165, 165], { rep: { sag: 0.22 } });
  assert.ok(sag.frames.some((f) => f.faults.some((x) => x.id === "sag")));
});

test("pull-up: a clean rep is counted and scores well", () => {
  const r = run("pullup", pullup, cycle(1));
  assert.equal(r.events.length, 1);
  assert.ok(r.events[0].score >= 88, `score ${r.events[0].score}`);
  assert.deepEqual(r.events[0].faults, []);
});

test("pull-up: swinging (kipping) is flagged", () => {
  const r = run("pullup", pullup, cycle(1), { rep: { kip: 0.32 } });
  assert.ok(r.frames.some((f) => f.faults.some((x) => x.id === "kip")));
  assert.ok(r.events[0].faults.includes("kip") && r.events[0].score < 85);
});

test("pull-up: a half rep is counted but marked shallow", () => {
  const r = run("pullup", pullup, cycle(0.5));
  assert.equal(r.events.length, 1);
  assert.equal(r.events[0].shallow, true);
  assert.ok(r.events[0].faults.includes("depth"));
});

test("pull-up: the ghost coach stays anchored to the athlete's own wrist and arm length", () => {
  const r = run("pullup", pullup, cycle(1));
  const F = prepare(pullup(1), W, H, "pullup");
  const g = analyze("pullup", F, r.cal).ideal.points;
  assert.ok(Math.hypot(g.wrist.x - F.P.wr.x, g.wrist.y - F.P.wr.y) < 1, "the ghost's wrist is the athlete's own wrist");
  assert.ok(Math.abs(Math.hypot(g.elbow.x - g.wrist.x, g.elbow.y - g.wrist.y) - r.cal.armLower) < 2, "ghost forearm length matches the athlete's own");
});

test("cue stabilizer does not flicker", () => {
  const s = new CueStabilizer(5);
  const a = { id: "a", severity: "ok", text: "a" }, b = { id: "b", severity: "ok", text: "b" };
  s.push(a);
  assert.equal(s.push(b).id, "a");
  assert.equal(s.push(a).id, "a");
  for (let i = 0; i < 5; i++) s.push(b);
  assert.equal(s.current.id, "b");
});

test("angleAt is a proper interior angle", () => {
  assert.ok(Math.abs(angleAt({ x: 1, y: 0 }, { x: 0, y: 0 }, { x: 0, y: 1 }) - 90) < 1e-9);
});

test("demo mode: the scripted athlete produces counted reps with the faults on the second rep", () => {
  for (const ex of ["squat", "deadlift", "pushup", "pullup"]) {
    const cal = newCal(), tracker = new RepTracker(ex), events = [];
    for (let i = 0; i < 30 + 3 * 80 + 5; i++) {
      const { lm } = demoFrame(ex, i);
      const F = prepare(lm, 1280, 720, ex);
      if (!cal.ready) { updateCal(cal, ex, F); continue; }
      const ev = tracker.update(analyze(ex, F, cal, { shallow: tracker.shallow }));
      if (ev) events.push(ev);
    }
    assert.equal(events.length, 3, `${ex}: three reps`);
    assert.ok(events[0].score >= 85 && events[2].score >= 85, `${ex}: clean reps score well (${events.map((e) => e.score)})`);
    assert.ok(events[1].faults.length > 0 && events[1].score < events[0].score, `${ex}: the faulty rep is caught (${JSON.stringify(events[1])})`);
  }
});
