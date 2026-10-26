// Hero status row: real API latency, local clock, public waitlist counter, and the scroll-scrubbed ticker.
import { api } from "../lib/api.js";
import { $, prefersReducedMotion } from "../lib/dom.js";

export async function initStatus() {
  const clock = $("#current-time");
  const tick = () => { if (clock) clock.textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); };
  tick();
  setInterval(tick, 15000);

  const label = $("#status-api");
  try {
    const t0 = performance.now();
    const res = await fetch("/api/health", { cache: "no-store" });
    const ms = Math.max(1, Math.round(performance.now() - t0));
    if (!res.ok) throw new Error("degraded");
    label.textContent = "All systems operational";
    $("#status-latency").textContent = `${ms} ms`;
    $("#status-latency-wrap").hidden = false;
  } catch {
    label.textContent = "Service degraded";
    $("#status-dot").classList.add("dot--off");
  }

  try {
    const { waitlist_count: n } = await api("/api/stats");
    if (n) {
      $("#status-count").textContent = n.toLocaleString();
      $("#status-count-wrap").hidden = false;
      const c = $("#cta-counter");
      c.textContent = `${n.toLocaleString()} people are already on the list.`;
      c.hidden = false;
    }
  } catch { /* the counter is optional */ }
}

export function initTicker() {
  const section = $("[data-ticker]");
  const track = $("[data-ticker-track]", section || document);
  if (!section || !track || prefersReducedMotion()) return;
  let raf = 0;
  const update = () => {
    raf = 0;
    const r = section.getBoundingClientRect();
    const vh = window.innerHeight;
    if (r.bottom < 0 || r.top > vh) return;
    const p = Math.min(1, Math.max(0, (vh - r.top) / (vh + r.height)));
    track.style.transform = `translate3d(${(-p * track.scrollWidth) / 2}px, 0, 0)`;
  };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(update); };
  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  update();
}
