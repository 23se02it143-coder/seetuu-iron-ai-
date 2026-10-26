// Diet planner: form -> /api/diet/plan -> targets, macro bars, meal cards with swaps, email and print.
import { api, ApiError, track } from "../lib/api.js";
import { $, $$, esc, icon, setBusy, showFieldErrors, clearErrors, showFormError, toast } from "../lib/dom.js";

const GOALS = { bulk: "Bulking", cut: "Cutting", recomp: "Recomposition", maintain: "Maintenance" };
const KEY = "iron-diet-v1";

export function initDiet() {
  const form = $("#diet-form");
  const result = $("#diet-result");
  if (!form) return;
  let variants = {};
  let last = null;
  let busy = false;

  // remember the last inputs on this device (a convenience; never sent anywhere until you press the button)
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (saved) for (const [k, v] of Object.entries(saved)) setField(k, v);
  } catch { /* storage unavailable */ }

  function setField(name, value) {
    const els = form.elements[name];
    if (!els) return;
    if (els instanceof RadioNodeList) els.value = String(value);
    else els.value = String(value);
  }

  function values() {
    const f = new FormData(form);
    return {
      sex: f.get("sex"), age: Number(f.get("age")), height_cm: Number(f.get("height_cm")), weight_kg: Number(f.get("weight_kg")),
      activity: f.get("activity"), goal: f.get("goal"), pace: f.get("pace") || "standard", preference: f.get("preference"), meals: Number(f.get("meals")),
    };
  }

  const paceField = $("#d-pace-field");
  const syncPace = () => { paceField.hidden = !["bulk", "cut"].includes(form.elements.goal.value); };
  syncPace();

  form.addEventListener("change", () => {
    variants = {};
    syncPace();
    try { localStorage.setItem(KEY, JSON.stringify(values())); } catch { /* ignore */ }
  });

  async function build({ scroll = true, source = "form" } = {}) {
    if (busy) return;
    clearErrors(form);
    const body = { ...values(), variants };
    busy = true;
    const btn = $("button[type=submit]", form);
    setBusy(btn, true, "Building");
    try {
      const plan = await api("/api/diet/plan", { method: "POST", body });
      last = { plan, body };
      render(plan);
      if (source === "form") track("diet_plan");
      if (scroll && window.matchMedia("(max-width: 999px)").matches) result.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.fields && Object.keys(err.fields).length) showFieldErrors(form, err.fields);
        showFormError(form, err.message);
      } else showFormError(form, "Something went wrong. Please try again.");
    } finally {
      busy = false;
      setBusy(btn, false);
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); variants = {}; build(); });

  // the chat can prefill the form
  window.addEventListener("iron:diet", (e) => {
    const { goal, weight } = e.detail || {};
    if (goal) form.elements.goal.value = goal;
    if (weight) form.elements.weight_kg.value = weight;
    syncPace();
    $("#diet")?.scrollIntoView({ behavior: "smooth" });
    setTimeout(() => build({ scroll: false, source: "chat" }), 500);
  });

  function render(plan) {
    const t = plan.targets;
    const b = last.body;
    const kcalP = t.protein_g * 4, kcalC = t.carbs_g * 4, kcalF = t.fat_g * 9;
    const sum = kcalP + kcalC + kcalF || 1;
    const change = t.weekly_change_kg;
    const changeText = b.goal === "maintain" ? "Weight steady" : `${change > 0 ? "+" : ""}${change.toFixed(2)} kg / week`;
    result.innerHTML = `<div class="dplan">
      <div class="dplan__head">
        <p class="label">${esc(GOALS[b.goal])} plan</p>
        <div class="dplan__kcal"><b>${t.calories.toLocaleString("en-IN")}</b><span>kcal a day</span></div>
        <div class="macrobar" role="img" aria-label="Macro split"><i class="p"></i><i class="c"></i><i class="f"></i></div>
        <div class="macrolegend"><div class="p"><b>${t.protein_g} g</b><span>Protein</span></div><div class="c"><b>${t.carbs_g} g</b><span>Carbs</span></div><div class="f"><b>${t.fat_g} g</b><span>Fats</span></div></div>
        <div class="dplan__facts"><span>Maintenance ~${t.tdee.toLocaleString("en-IN")} kcal</span><span>${changeText}</span><span>Water ~${t.water_l} L</span></div>
      </div>
      ${t.notes.map((n) => `<p class="dnote">${esc(n)}</p>`).join("")}
      <div class="meals">${plan.meals.map(mealCard).join("")}</div>
      <p class="muted dplan__total">Day total: ${plan.totals.kcal.toLocaleString("en-IN")} kcal, ${plan.totals.p} g protein, ${plan.totals.c} g carbs, ${plan.totals.f} g fats</p>
      <div><h3 class="h3">How to make it work</h3><ul class="dtips mt-l">${plan.tips.map((x) => `<li>${icon("check")}<span>${esc(x)}</span></li>`).join("")}</ul></div>
      <details class="faq"><summary>Supplements (optional)</summary><div class="faq__a">${plan.supplements.map((x) => `<p>${esc(x)}</p>`).join("")}</div></details>
      <div class="dactions no-print"><button type="button" class="btn btn--ghost btn--sm" data-shuffle>${icon("sparkle")}Shuffle all meals</button><button type="button" class="btn btn--ghost btn--sm" data-print>${icon("download-simple")}Print or save as PDF</button></div>
      <form class="demail no-print" id="diet-email" novalidate>
        <b>Email me this plan</b>
        <div class="row"><input class="input" name="name" placeholder="Your name (optional)" maxlength="80" autocomplete="given-name"><input class="input" name="email" type="email" placeholder="you@example.com" required autocomplete="email"></div>
        <label class="check"><input type="checkbox" name="join"><span>Also add me to the IRON-AI waitlist</span></label>
        <div class="form-error" data-form-error hidden></div>
        <button class="btn btn--primary btn--sm" type="submit">Send my plan</button>
      </form>
      <p class="form-note">${esc(plan.disclaimer)}</p>
    </div>`;
    // widths are set through the CSSOM: the site's CSP blocks inline style attributes
    [["p", kcalP], ["c", kcalC], ["f", kcalF]].forEach(([k, v]) => { result.querySelector(`.macrobar .${k}`).style.width = `${(v / sum) * 100}%`; });
    result.querySelector("[data-print]").addEventListener("click", () => window.print());
    result.querySelector("[data-shuffle]").addEventListener("click", () => {
      variants = {};
      plan.meals.forEach((m) => { variants[m.slot] = (m.variant + 1) % m.variants_count; });
      build({ scroll: false, source: "shuffle" });
    });
    result.querySelectorAll("[data-swap]").forEach((btn) => btn.addEventListener("click", () => {
      variants[btn.dataset.swap] = (Number(btn.dataset.variant) + 1) % Number(btn.dataset.count);
      build({ scroll: false, source: "swap" });
    }));
    result.querySelector("#diet-email").addEventListener("submit", emailPlan);
  }

  function mealCard(m) {
    return `<article class="meal">
      <div class="meal__head"><div class="meal__title"><b>${esc(m.label)}</b><span>${esc(m.time)}</span></div>
        <button type="button" class="chip no-print" data-swap="${m.slot}" data-variant="${m.variant}" data-count="${m.variants_count}" aria-label="Swap ${esc(m.label)} for another option">Swap meal</button></div>
      <ul class="meal__items">${m.items.map((i) => `<li><span>${esc(i.name)} <small class="meal__serving">${esc(i.serving)}</small></span><span>${i.kcal} kcal</span></li>`).join("")}</ul>
      <p class="meal__total">${m.kcal} kcal &middot; ${Math.round(m.p)} g protein &middot; ${Math.round(m.c)} g carbs &middot; ${Math.round(m.f)} g fats</p>
    </article>`;
  }

  async function emailPlan(e) {
    e.preventDefault();
    const f = e.currentTarget;
    clearErrors(f);
    const fd = new FormData(f);
    const btn = $("button[type=submit]", f);
    setBusy(btn, true, "Sending");
    try {
      await api("/api/diet/email", { method: "POST", body: { ...last.body, email: fd.get("email"), name: fd.get("name") || "", join_waitlist: fd.get("join") === "on" } });
      f.innerHTML = `<p class="status">${icon("check-circle")} Sent. Check your inbox in a minute.</p>`;
    } catch (err) {
      if (err instanceof ApiError && err.fields) showFieldErrors(f, err.fields);
      showFormError(f, err instanceof ApiError ? err.message : "Couldn't send. Please try again.");
      setBusy(btn, false);
    }
  }
}
