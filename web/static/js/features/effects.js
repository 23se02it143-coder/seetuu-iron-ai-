// Interaction polish: scroll progress, cursor glow, spotlight and tilt cards, magnetic buttons,
// scroll reveals, count-up numbers, the hero text scramble and the floating "try the coach" button.
// Everything is skipped or simplified when the visitor prefers reduced motion.
import { $, $$, prefersReducedMotion } from "../lib/dom.js";

const fine = () => window.matchMedia("(hover: hover) and (pointer: fine)").matches;

function scrollProgress() {
  const bar = $("#scroll-progress");
  if (!bar) return;
  let ticking = false;
  const update = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.setProperty("--p", max > 0 ? Math.min(1, scrollY / max).toFixed(4) : "0");
    ticking = false;
  };
  addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  update();
}

function cursorGlow() {
  const glow = $("#cursor-glow");
  if (!glow || !fine()) return;
  let x = -600, y = -600, tx = x, ty = y, raf = 0;
  const loop = () => {
    x += (tx - x) * 0.14; y += (ty - y) * 0.14;
    glow.style.setProperty("--gx", `${x.toFixed(1)}px`);
    glow.style.setProperty("--gy", `${y.toFixed(1)}px`);
    raf = Math.abs(tx - x) + Math.abs(ty - y) > 0.5 ? requestAnimationFrame(loop) : 0;
  };
  addEventListener("pointermove", (e) => { tx = e.clientX; ty = e.clientY; if (!raf) raf = requestAnimationFrame(loop); }, { passive: true });
}

/** Cards get a spotlight that follows the pointer; a few also tilt in 3D. */
function pointerCards() {
  if (!fine()) return;
  const tilt = !prefersReducedMotion();
  document.addEventListener("pointermove", (e) => {
    const el = e.target.closest?.(".spot, .plan, .pcard, .step, .meal, .goal__box");
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty("--mx", `${e.clientX - r.left}px`);
    el.style.setProperty("--my", `${e.clientY - r.top}px`);
    if (tilt && el.matches(".plan, .pcard")) {
      const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
      el.style.transform = `perspective(900px) rotateX(${(-py * 5).toFixed(2)}deg) rotateY(${(px * 6).toFixed(2)}deg) translateZ(0)`;
    }
  }, { passive: true });
  document.addEventListener("pointerout", (e) => {
    const el = e.target.closest?.(".plan, .pcard");
    if (el && !el.contains(e.relatedTarget)) el.style.transform = "";
  });
}

/** Buttons lean toward the cursor a few pixels. */
function magnetic() {
  if (!fine() || prefersReducedMotion()) return;
  document.addEventListener("pointermove", (e) => {
    document.querySelectorAll(".btn--primary.is-mag").forEach((b) => { if (!b.matches(":hover")) b.style.transform = ""; });
    const b = e.target.closest?.(".btn--primary:not(.btn--block)");
    if (!b) return;
    b.classList.add("is-mag");
    const r = b.getBoundingClientRect();
    b.style.transform = `translate(${((e.clientX - r.left - r.width / 2) * 0.12).toFixed(1)}px, ${((e.clientY - r.top - r.height / 2) * 0.2).toFixed(1)}px)`;
  }, { passive: true });
  document.addEventListener("pointerout", (e) => { const b = e.target.closest?.(".btn--primary"); if (b) b.style.transform = ""; });
}

function reveal() {
  if (prefersReducedMotion() || !("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
  }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
  const add = (root = document) => {
    root.querySelectorAll(".section__head, .proof__grid > div, .step, .facts > *, .coach__layout > *, .diet__grid > *, .plan, .pcard, .faq, .lab__grid > *").forEach((el, i) => {
      if (el.classList.contains("reveal") || el.getBoundingClientRect().top < innerHeight * 0.9) return; // already on screen: leave alone
      el.classList.add("reveal");
      el.style.setProperty("--d", `${(i % 4) * 0.08}s`);
      io.observe(el);
    });
  };
  add();
  // cards that arrive later from the API
  const mo = new MutationObserver(() => add());
  ["#plans", "#programs-feature", "#programs-more"].forEach((s) => { const n = $(s); if (n) mo.observe(n, { childList: true }); });
}

function countUp() {
  const items = $$("[data-count]");
  if (!items.length) return;
  const run = (el) => {
    const end = Number(el.dataset.count), pre = el.dataset.prefix || "";
    if (prefersReducedMotion() || end === 0) { el.textContent = `${pre}${end}`; return; }
    const t0 = performance.now(), dur = 1300;
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / dur);
      el.textContent = `${pre}${Math.round(end * (1 - Math.pow(1 - p, 3)))}`;
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };
  const io = new IntersectionObserver((entries) => entries.forEach((en) => { if (en.isIntersecting) { run(en.target); io.unobserve(en.target); } }), { threshold: 0.6 });
  items.forEach((el) => io.observe(el));
}

/** Decodes the hero kicker one letter at a time. */
function scramble() {
  const el = $("[data-scramble]");
  if (!el || prefersReducedMotion()) return;
  const final = el.textContent, glyphs = "01/\\#=+*<>";
  let frame = 0;
  const total = 26;
  el.setAttribute("aria-label", final);
  const step = () => {
    const reveal = Math.floor((frame / total) * final.length);
    el.textContent = [...final].map((c, i) => (c === " " || i < reveal ? c : glyphs[Math.floor(Math.random() * glyphs.length)])).join("");
    if (frame++ < total) setTimeout(step, 38); else el.textContent = final;
  };
  setTimeout(step, 400);
}

/** After the hero, a pill follows you down the page until the camera coach is on screen. */
function fab() {
  const btn = $("#fab"), coach = $("#coach");
  if (!btn || !coach) return;
  let inCoach = false;
  new IntersectionObserver((e) => { inCoach = e[0].isIntersecting; update(); }, { threshold: 0.15 }).observe(coach);
  const update = () => { btn.hidden = !(scrollY > innerHeight * 0.9) || inCoach; };
  addEventListener("scroll", update, { passive: true });
  update();
}

export function initEffects() {
  scrollProgress();
  cursorGlow();
  pointerCards();
  magnetic();
  reveal();
  countUp();
  scramble();
  fab();
}
