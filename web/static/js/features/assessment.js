// Six-question readiness assessment -> /api/assessments -> result with optional "save my plan".
import { api, ApiError, track } from "../lib/api.js";
import { $, $$, clearErrors, esc, icon, prefersReducedMotion, setBusy, showFieldErrors, showFormError } from "../lib/dom.js";
import { state, onUser } from "../shell.js";

const STEPS = [
  { key: "goal", title: "What are you training for?", hint: "Pick the closest match. You can change it later.", options: [
    ["strength", "Get stronger", "Lift heavier with good technique"],
    ["fitness", "General fitness", "Feel better, move better"],
    ["performance", "Sport performance", "Be sharper for your sport"],
    ["recovery", "Recover and rebuild", "Return after a layoff or setback"]] },
  { key: "experience", title: "How long have you trained consistently?", hint: "Be honest, it changes what we recommend.", options: [
    ["beginner", "Under a year", "Still learning the movements"],
    ["intermediate", "One to three years", "Comfortable with the main lifts"],
    ["advanced", "Over three years", "Structured, progressive training"]] },
  { key: "days_per_week", title: "How many days a week do you train?", hint: "Include every session, even short ones.", days: true },
  { key: "sleep", title: "How much do you usually sleep?", hint: "A typical night over the past month.", options: [
    ["under_5", "Under 5 hours", ""], ["5_6", "5 to 6 hours", ""], ["6_7", "6 to 7 hours", ""],
    ["7_8", "7 to 8 hours", ""], ["8_plus", "8 hours or more", ""]] },
  { key: "pain", title: "Anything sore or niggling right now?", hint: "Select every area that applies, or none.", pain: true },
  { key: "red_flags", title: "In the last two weeks, have you had chest pain, dizziness, numbness or sudden severe pain?", hint: "This is a safety check, not a diagnosis.", options: [
    ["no", "No", "None of these"], ["yes", "Yes", "At least one"]] },
];

const PAIN = [["lower_back", "Lower back"], ["knee", "Knee"], ["shoulder", "Shoulder"], ["hip", "Hip"], ["neck", "Neck"], ["ankle", "Ankle"], ["elbow_wrist", "Elbow or wrist"]];
const PLAN_NAMES = { starter: "Starter", pro: "Pro", elite: "Elite" };

export function initAssessment() {
  const root = $("#assessment-root");
  if (!root) return;

  let step = 0;
  let answers = {};
  let started = false;
  let lastPayload = null;

  const markStarted = () => { if (!started) { started = true; track("assessment_started"); } };
  root.addEventListener("change", markStarted, { once: true });

  function progress() {
    const pct = Math.round((step / STEPS.length) * 100);
    return `<div class="progress"><span>Question ${step + 1} of ${STEPS.length}</span><span class="progress__bar"><span class="progress__fill" data-pct="${pct}"></span></span></div>`;
  }

  function choice(name, type, value, title, desc, checked, cls = "") {
    return `<label class="choice ${cls}"><input type="${type}" name="${name}" value="${esc(value)}"${checked ? " checked" : ""}>
      <span class="choice__box"><strong>${esc(title)}</strong>${desc ? `<span>${esc(desc)}</span>` : ""}</span></label>`;
  }

  function renderStep(moved = true) {
    const s = STEPS[step];
    let body = "";
    if (s.days) {
      body = `<div class="choices choices--days">${[1, 2, 3, 4, 5, 6, 7].map((n) => choice("days", "radio", n, n, "", answers.days_per_week === n)).join("")}</div>`;
    } else if (s.pain) {
      const picked = answers.pain_areas || [];
      body = `<div class="pain-wrap">${PAIN.map(([v, t]) => choice("pain", "checkbox", v, t, "", picked.includes(v), "choice--pill")).join("")}
        ${choice("pain", "checkbox", "none", "None", "", answers.pain_areas && !picked.length, "choice--pill")}</div>
        <div class="q__sub"><span class="label" id="inj-label">Have you had an injury in the last three months?</span>
        <div class="choices choices--2" role="radiogroup" aria-labelledby="inj-label">
          ${choice("injury", "radio", "no", "No", "", !answers.recent_injury)}${choice("injury", "radio", "yes", "Yes", "", !!answers.recent_injury)}</div></div>`;
    } else {
      const current = s.key === "red_flags" ? (answers.red_flags == null ? null : answers.red_flags ? "yes" : "no") : answers[s.key];
      body = `<div class="choices choices--${s.options.length}">${s.options.map(([v, t, d]) => choice(s.key, "radio", v, t, d, current === v)).join("")}</div>`;
    }
    const last = step === STEPS.length - 1;
    root.innerHTML = `${progress()}
      <form novalidate><fieldset class="q"><legend tabindex="-1">${esc(s.title)}</legend><p class="q__hint">${esc(s.hint)}</p>${body}</fieldset>
        <p class="form-error assess__error" data-form-error hidden></p>
        <div class="assess__nav">${step > 0 ? `<button type="button" class="btn btn--ghost" data-back>Back</button>` : "<span></span>"}
        <button type="submit" class="btn btn--primary">${last ? "See my result" : "Continue"}</button></div></form>`;
    requestAnimationFrame(() => { const f = $(".progress__fill", root); if (f) f.style.width = `${f.dataset.pct}%`; });
    const form = $("form", root);
    $("[data-back]", root)?.addEventListener("click", () => { step -= 1; renderStep(); });

    if (s.pain) {
      form.addEventListener("change", (e) => {
        if (e.target.name !== "pain") return;
        const boxes = $$('input[name="pain"]', form);
        if (e.target.value === "none" && e.target.checked) boxes.forEach((b) => { if (b.value !== "none") b.checked = false; });
        else if (e.target.checked) $('input[value="none"]', form).checked = false;
      });
    }
    form.addEventListener("submit", (e) => { e.preventDefault(); if (collect(form, s)) next(); });
    if (moved) $("legend", root).focus({ preventScroll: true });
  }

  function collect(form, s) {
    const fail = (msg) => { const box = $("[data-form-error]", form); box.textContent = msg; box.hidden = false; return false; };
    const val = (name) => form.querySelector(`input[name="${name}"]:checked`)?.value;
    if (s.days) { const v = val("days"); if (!v) return fail("Choose how many days you train."); answers.days_per_week = Number(v); }
    else if (s.pain) {
      const chosen = $$('input[name="pain"]:checked', form).map((i) => i.value).filter((v) => v !== "none");
      answers.pain_areas = chosen;
      answers.recent_injury = val("injury") === "yes";
    } else {
      const v = val(s.key);
      if (!v) return fail("Choose an option to continue.");
      answers[s.key] = s.key === "red_flags" ? v === "yes" : v;
    }
    return true;
  }

  async function next() {
    if (step < STEPS.length - 1) { step += 1; renderStep(); return; }
    await submit();
  }

  function payload() {
    return { goal: answers.goal, experience: answers.experience, days_per_week: answers.days_per_week, pain_areas: answers.pain_areas || [],
      recent_injury: !!answers.recent_injury, sleep: answers.sleep, red_flags: !!answers.red_flags };
  }

  async function submit() {
    root.innerHTML = `<div class="progress"><span>Scoring your answers</span><span class="progress__bar"><span class="progress__fill" data-pct="100"></span></span></div><p class="muted">One moment...</p>`;
    requestAnimationFrame(() => { const f = $(".progress__fill", root); if (f) f.style.width = "100%"; });
    try {
      lastPayload = payload();
      const res = await api("/api/assessments", { method: "POST", body: lastPayload });
      track("assessment_completed");
      window.dispatchEvent(new Event("iron:strike"));
      renderResult(res.result);
    } catch (err) {
      step = STEPS.length - 1;
      renderStep();
      const box = $("[data-form-error]", root);
      box.textContent = err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
      box.hidden = false;
    }
  }

  function renderResult(r) {
    const medical = r.status === "medical_review";
    const program = r.program;
    const score = r.readiness?.score ?? 0;
    const insights = (r.insights || []).map((t) => `<li>${icon("check")}<span>${esc(t)}</span></li>`).join("");
    const focus = (r.focus || []).map((f) => `<div><b>${esc(f.label)}</b>${esc(f.tip)}</div>`).join("");
    const plan = r.plan_slug ? PLAN_NAMES[r.plan_slug] || r.plan_slug : "";

    root.innerHTML = `<div class="result ${medical ? "result--medical" : ""}">
      <div class="result__top">
        <div class="ring" role="img" aria-label="Readiness score ${score} out of 100">
          <svg viewBox="0 0 120 120"><circle class="ring__track" cx="60" cy="60" r="52"/><circle class="ring__value" cx="60" cy="60" r="52"/></svg>
          <div class="ring__label"><b data-score>0</b><span>${esc(r.readiness?.label || "")}</span></div>
        </div>
        <div>
          ${medical ? `<div class="notice">${icon("warning")}<div><b>${esc(r.headline)}</b><br>${esc(r.summary)}</div></div>` : `<h3 tabindex="-1">${esc(r.headline)}</h3><p class="muted">${esc(r.summary)}</p>`}
        </div>
      </div>
      <ul class="result__list">${insights}</ul>
      ${focus ? `<div class="result__focus">${focus}</div>` : ""}
      ${program ? `<div class="result__program"><div><h4>${esc(program.name)}</h4><p>${esc(program.tagline)}${plan ? ` Best fit: the ${esc(plan)} plan.` : ""}</p></div>
        <div class="row"><button type="button" class="btn btn--light btn--sm" data-program="${esc(program.slug)}">See the program</button>
        <a class="btn btn--ghost btn--sm" href="#pricing" data-plan="${esc(r.plan_slug || "")}">View plans</a></div></div>` : ""}
      ${medical ? "" : saveBlock()}
      <p class="result__disclaimer">${esc(r.disclaimer)}</p>
      <div class="row mt-l"><button type="button" class="btn btn--ghost btn--sm" data-retake>Retake the assessment</button></div>
    </div>`;

    if (!medical) animateScore(score);
    $("[data-retake]", root).addEventListener("click", () => { step = 0; answers = {}; renderStep(); });
    $("[data-program]", root)?.addEventListener("click", (e) => window.dispatchEvent(new CustomEvent("iron:program", { detail: { slug: e.currentTarget.dataset.program } })));
    $("[data-plan]", root)?.addEventListener("click", (e) => { track("plan_selected"); sessionStorage.setItem("suggested_plan", e.currentTarget.dataset.plan); window.dispatchEvent(new CustomEvent("iron:suggest-plan", { detail: { slug: e.currentTarget.dataset.plan } })); });
    const save = $("#save-form", root);
    if (save) bindSave(save);
    $(".result h3, .result .notice", root)?.focus?.({ preventScroll: true });
  }

  function saveBlock() {
    const user = state.user;
    return `<div class="save"><h4>Keep this plan</h4>
      <p class="muted">${user ? "Save this result to your account." : "We'll email you the plan and keep your answers so you can come back to them. Skip this and nothing is stored."}</p>
      <form id="save-form" novalidate>
        ${user ? "" : `<div class="save__row">
          <div class="field"><label for="s-name">First name</label><input class="input" id="s-name" name="name" autocomplete="given-name" maxlength="80"></div>
          <div class="field"><label for="s-email">Email</label><input class="input" id="s-email" name="email" type="email" autocomplete="email" required><span class="field-error" data-error-for="email"></span></div></div>
        <label class="check"><input type="checkbox" name="consent"><span>Store my answers so I can revisit my plan. I can delete them any time.</span></label>
        <span class="field-error" data-error-for="consent"></span>
        <label class="check"><input type="checkbox" name="join_waitlist"><span>Also add me to the launch waitlist.</span></label>`}
        <div class="form-error" data-form-error hidden></div>
        <div><button class="btn btn--primary" type="submit">${user ? "Save to my account" : "Email me my plan"}</button></div>
      </form></div>`;
  }

  function bindSave(form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      clearErrors(form);
      const btn = $('button[type="submit"]', form);
      const d = Object.fromEntries(new FormData(form));
      const body = { ...lastPayload, save: true, email: d.email || null, name: d.name || "", consent: !!d.consent || !!state.user, join_waitlist: !!d.join_waitlist };
      setBusy(btn, true, "Saving");
      try {
        const res = await api("/api/assessments", { method: "POST", body });
        const msg = state.user ? "Saved to your account." : "Plan on its way. Check your inbox.";
        const extra = res.waitlist?.position ? ` You're #${Number(res.waitlist.position).toLocaleString()} on the waitlist.` : "";
        form.innerHTML = `<div class="success">${icon("check-circle")}<div><b>${msg}</b>${esc(extra)}</div></div>`;
      } catch (err) {
        if (!(err instanceof ApiError)) throw err;
        if (!showFieldErrors(form, err.fields)) showFormError(form, err.message);
      } finally {
        setBusy(btn, false);
      }
    });
  }

  function animateScore(target) {
    const ring = $(".ring__value", root);
    const num = $("[data-score]", root);
    const circumference = 326.7;
    const apply = (v) => { num.textContent = String(Math.round(v)); };
    if (prefersReducedMotion()) { apply(target); ring.style.strokeDashoffset = String(circumference * (1 - target / 100)); return; }
    requestAnimationFrame(() => { ring.style.strokeDashoffset = String(circumference * (1 - target / 100)); });
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / 1300);
      apply(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  onUser(() => { /* result page re-renders on next retake; nothing to do mid-quiz */ });
  renderStep(false);
}
