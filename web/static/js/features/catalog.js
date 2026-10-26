// Content that comes from the database: programs, plans (with checkout) and testimonials.
import { api, ApiError, track } from "../lib/api.js";
import { $, $$, esc, icon, money, setBusy, toast } from "../lib/dom.js";
import { ensureUser } from "../shell.js";

const loadError = (msg) => `<div class="load-error">${esc(msg)}</div>`;

// -------------------------------------------------------------- programs
function programDialog(programs) {
  const dialog = $("#program-dialog");
  const body = $("#program-dialog-body");
  if (!dialog) return;

  function open(slug) {
    const p = programs.find((x) => x.slug === slug);
    if (!p) return;
    body.innerHTML = `<button type="button" class="dialog__close" data-close aria-label="Close">${icon("x")}</button>
      <h2 id="pdlg-title">${esc(p.name)}</h2>
      <p class="muted">${esc(p.tagline)}</p>
      <div class="pdlg__meta"><span>${esc(p.level)}</span><span>${p.weeks} weeks</span><span>${esc(p.sessions_per_week)} sessions a week</span></div>
      <p>${esc(p.description)}</p>
      <h3 class="h3 mt-l">What's inside</h3>
      <ul class="pdlg__list mt-l">${p.highlights.map((h) => `<li>${icon("check")}<span>${esc(h)}</span></li>`).join("")}</ul>
      <section class="sched" id="pdlg-sched"><h3 class="h3">Your week</h3><div class="skeleton sched__skeleton"></div></section>
      <div class="pdlg__actions"><a class="btn btn--primary" href="#assessment" data-close-link>Check if it fits me</a>
      <a class="btn btn--ghost" href="#waitlist" data-close-link>Join the waitlist</a></div>`;
    dialog.showModal();
    loadSchedule(slug);
  }

  async function loadSchedule(slug) {
    const box = $("#pdlg-sched", body);
    try {
      const data = await api(`/api/programs/${encodeURIComponent(slug)}/schedule`);
      const dayHtml = (d) => `<div class="sched__day"><h4>${esc(d.title)}</h4><p class="sched__focus">${esc(d.focus)}</p>
        <ul class="sched__list">${d.exercises.map((x) => `<li><b>${esc(x.name)}</b><span class="sched__sets">${esc(x.sets)}</span>
          <div class="sched__cue"><span>${esc(x.cue)}</span>${x.coach ? `<button type="button" class="chip chip--action" data-coach="${esc(x.coach)}">${icon("camera")}Coach this lift</button>` : ""}</div></li>`).join("")}</ul></div>`;
      box.innerHTML = `<h3 class="h3">Your week</h3><p class="muted">${esc(data.summary)}</p>
        <div class="sched__tabs" role="tablist">${data.days.map((d, i) => `<button type="button" role="tab" aria-selected="${i === 0}" data-day="${i}">${esc(d.day)}</button>`).join("")}</div>
        <div id="sched-body">${dayHtml(data.days[0])}</div>`;
      box.addEventListener("click", (e) => {
        const tab = e.target.closest("[data-day]");
        if (tab) {
          $$("[data-day]", box).forEach((b) => b.setAttribute("aria-selected", String(b === tab)));
          $("#sched-body", box).innerHTML = dayHtml(data.days[Number(tab.dataset.day)]);
        }
        const coach = e.target.closest("[data-coach]");
        if (coach) { dialog.close(); window.dispatchEvent(new CustomEvent("iron:coach", { detail: { exercise: coach.dataset.coach } })); }
      });
    } catch {
      box?.remove();
    }
  }
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog || e.target.closest("[data-close]") || e.target.closest("[data-close-link]")) dialog.close();
  });
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-program]");
    if (trigger && !trigger.closest("#assessment-root")) open(trigger.dataset.program);
  });
  window.addEventListener("iron:program", (e) => open(e.detail.slug));
}

export async function initPrograms() {
  const feature = $("#programs-feature");
  const more = $("#programs-more");
  if (!feature) return;
  try {
    const { programs } = await api("/api/programs");
    const big = programs.filter((p) => p.featured).slice(0, 2);
    const rest = programs.filter((p) => !big.includes(p));
    feature.innerHTML = big.map((p, i) => `<article class="pcard ${i % 2 === 0 ? "pcard--fill" : ""}">
        <div class="pcard__top"><div class="pcard__icon">${icon(p.icon)}</div><span class="pcard__code">${esc(p.code)}</span></div>
        <div><h3>${esc(p.name)}</h3><p>${esc(p.tagline)}</p>
          <div class="pcard__meta"><span>${esc(p.level)}</span><span>${p.weeks} weeks</span><span>${esc(p.sessions_per_week)} sessions a week</span></div></div>
        <button type="button" class="pcard__more" data-program="${esc(p.slug)}">See what's inside ${icon("arrow-right")}</button></article>`).join("");
    more.innerHTML = rest.map((p) => `<button type="button" class="prow" data-program="${esc(p.slug)}">
        ${icon(p.icon)}<span><span class="prow__name">${esc(p.name)}</span><span class="prow__tag">${esc(p.tagline)}</span></span>
        <span class="prow__meta">${esc(p.level)}, ${p.weeks} weeks</span></button>`).join("");
    programDialog(programs);
  } catch (err) {
    feature.innerHTML = loadError("Programs are unavailable right now. Please refresh in a moment.");
  }
}

// --------------------------------------------------------------- pricing
export async function initPricing() {
  const host = $("#plans");
  if (!host) return;
  let interval = "month";
  let data;
  let cfg = { payments_mode: "test" };
  try {
    [data, cfg] = await Promise.all([api("/api/plans"), api("/api/config")]);
  } catch {
    host.innerHTML = loadError("Pricing is unavailable right now. Please refresh in a moment.");
    return;
  }
  const { plans, currency } = data;

  const monthsFree = (p) => {
    if (!p.price_monthly_cents) return 0;
    return Math.round(((p.price_monthly_cents * 12 - p.price_annual_cents) / p.price_monthly_cents) * 10) / 10;
  };
  const best = Math.max(0, ...plans.map(monthsFree));
  $("#save-badge").textContent = best > 0 ? ` ${Number.isInteger(best) ? best : best.toFixed(1)} months free` : "";

  function render() {
    host.innerHTML = plans.map((p) => {
      const free = p.price_monthly_cents === 0;
      const cents = interval === "year" ? p.price_annual_cents : p.price_monthly_cents;
      const note = free ? "No card needed" : interval === "year" ? `${money(Math.round(p.price_annual_cents / 12), currency)} a month, billed yearly` : "Billed monthly";
      return `<article class="plan ${p.highlight ? "plan--hi" : ""}" data-slug="${esc(p.slug)}">
        <div class="plan__head"><h3 class="plan__name">${esc(p.name)}</h3>${p.badge ? `<span class="plan__badge">${esc(p.badge)}</span>` : ""}</div>
        <p class="plan__tag">${esc(p.tagline)}</p>
        <div class="plan__price"><b>${free ? "Free" : money(cents, currency)}</b>${free ? "" : `<span>/ ${interval === "year" ? "year" : "month"}</span>`}</div>
        <p class="plan__note">${esc(note)}</p>
        <ul class="plan__features">${p.features.map((f) => `<li>${icon("check")}<span>${esc(f)}</span></li>`).join("")}</ul>
        <button type="button" class="btn ${p.highlight ? "btn--primary" : "btn--ghost"} btn--block" data-plan="${esc(p.slug)}">${esc(p.cta_label)}</button>
      </article>`;
    }).join("");
  }
  render();

  $$("[data-interval]").forEach((btn) => btn.addEventListener("click", () => {
    interval = btn.dataset.interval;
    $$("[data-interval]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    render();
  }));

  host.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-plan]");
    if (!btn) return;
    const plan = plans.find((p) => p.slug === btn.dataset.plan);
    track("plan_selected");
    const user = await ensureUser("register");
    if (!user) return;
    if (plan.price_monthly_cents === 0) { location.href = "/account"; return; }
    setBusy(btn, true, "Opening checkout");
    try {
      const res = await api("/api/billing/checkout", { method: "POST", body: { plan_slug: plan.slug, interval } });
      location.href = res.url;
    } catch (err) {
      setBusy(btn, false);
      toast(err instanceof ApiError ? err.message : "Couldn't start checkout. Please try again.", "error");
    }
  });

  window.addEventListener("iron:suggest-plan", (e) => {
    $$(".plan", host).forEach((el) => el.classList.toggle("is-suggested", el.dataset.slug === e.detail.slug));
  });

  $("#pricing-foot").textContent = (cfg.payments_mode === "test"
    ? "Checkout is in test mode: no card is charged. "
    : `Prices in ${currency}. Taxes may apply. `) + "Change or cancel any time from your account.";
}

// --------------------------------------------------------------- stories
export async function initStories() {
  const track_ = $("#marquee-track");
  const section = $("#stories");
  if (!track_) return;
  try {
    const { testimonials } = await api("/api/testimonials");
    if (!testimonials.length) { section.hidden = true; return; }
    $("#sample-note").hidden = !testimonials.some((t) => t.is_sample);
    let set = testimonials;
    while (set.length < 6) set = set.concat(testimonials);
    const card = (t, hidden) => `<figure class="quote"${hidden ? ' aria-hidden="true"' : ""}>
      <div class="quote__who"><div class="quote__avatar" aria-hidden="true">${esc(t.name.trim()[0] || "?")}</div>
        <div><div class="quote__name">${esc(t.name)}</div>${t.role ? `<div class="quote__role">${esc(t.role)}</div>` : ""}
          <div class="stars" role="img" aria-label="${t.rating} out of 5 stars">${Array.from({ length: t.rating }, () => icon("star-fill")).join("")}</div></div></div>
      <blockquote><p>&ldquo;${esc(t.quote)}&rdquo;</p></blockquote></figure>`;
    track_.innerHTML = set.map((t) => card(t, false)).join("") + set.map((t) => card(t, true)).join("");
  } catch {
    section.hidden = true;
  }
  const toggle = $("#marquee-toggle");
  toggle?.addEventListener("click", () => {
    const paused = $("#marquee").classList.toggle("is-paused");
    toggle.setAttribute("aria-pressed", String(paused));
    toggle.innerHTML = `${icon(paused ? "play" : "pause")}<span>${paused ? "Resume scrolling" : "Pause scrolling"}</span>`;
  });
}
