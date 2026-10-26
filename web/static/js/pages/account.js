import { state, openAuth, refreshSession, setUser } from "../shell.js";
import { api, ApiError } from "../lib/api.js";
import { $, $$, clearErrors, esc, formatDate, icon, money, setBusy, showFieldErrors, showFormError, toast } from "../lib/dom.js";

const root = $("#account-root");
const params = new URLSearchParams(location.search);
const resetToken = params.get("reset");

function pwField(id, name, label, autocomplete) {
  return `<div class="field"><label for="${id}">${label}</label>
    <div class="pw"><input class="input" id="${id}" name="${name}" type="password" autocomplete="${autocomplete}" required>
    <button type="button" data-toggle-pw aria-label="Show password">${icon("eye")}</button></div>
    <span class="field-error" data-error-for="${name}"></span></div>`;
}

function pwToggles(scope) {
  $$("[data-toggle-pw]", scope).forEach((btn) => btn.addEventListener("click", () => {
    const input = btn.parentElement.querySelector("input");
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.innerHTML = icon(show ? "eye-slash" : "eye");
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  }));
}

async function submitForm(form, work, okMessage) {
  clearErrors(form);
  const btn = $('button[type="submit"]', form);
  setBusy(btn, true, "Saving");
  try {
    const res = await work(Object.fromEntries(new FormData(form)));
    if (okMessage) toast(okMessage);
    return res;
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (!showFieldErrors(form, err.fields)) showFormError(form, err.message);
    return null;
  } finally {
    setBusy(btn, false);
  }
}

function resetView() {
  root.innerHTML = `<section class="panel"><h2>Choose a new password</h2><p class="sub">Use at least 10 characters. Avoid common passwords.</p>
    <form id="reset-form" novalidate>${pwField("rp", "password", "New password", "new-password")}<div class="form-error" data-form-error hidden></div>
    <div><button class="btn btn--primary" type="submit">Set new password</button></div></form></section>`;
  pwToggles(root);
  $("#reset-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const res = await submitForm(e.target, (d) => api("/api/auth/reset", { method: "POST", body: { token: resetToken, password: d.password } }), "Password updated. You're signed in.");
    if (res) { setUser(res.user); history.replaceState(null, "", "/account"); render(); }
  });
}

function signedOutView() {
  root.innerHTML = `<section class="panel"><h2>Sign in to see your account</h2><p class="sub">Your plan, invoices and data controls live here.</p>
    <div class="row"><button class="btn btn--primary" id="go-login">Sign in</button><button class="btn btn--ghost" id="go-register">Create an account</button></div></section>`;
  const go = async (tab) => { const u = await openAuth(tab); if (u) render(); };
  $("#go-login").addEventListener("click", () => go("login"));
  $("#go-register").addEventListener("click", () => go("register"));
}

function planLine(sub) {
  if (!sub.is_paid) return "Free plan. Upgrade any time for adaptive programming and unlimited assistant access.";
  const price = `${money(sub.amount_cents, sub.currency || "INR")} per ${sub.interval}`;
  if (sub.status === "past_due") return `${price}. Your last payment failed; update your payment method to keep access.`;
  return sub.cancel_at_period_end
    ? `${price}. Ends on ${formatDate(sub.current_period_end)}, then you move to Starter.`
    : `${price}. Renews on ${formatDate(sub.current_period_end)}.`;
}

async function render() {
  const user = state.ready ? state.user : await refreshSession();
  if (resetToken) return resetView();
  if (!user) return signedOutView();

  let billing;
  try { billing = await api("/api/billing/subscription"); } catch { billing = null; }
  const sub = billing?.subscription;
  const invoices = billing?.invoices || [];
  let sessions = null;
  try { sessions = await api("/api/sessions"); } catch { sessions = null; }

  root.innerHTML = `
  <section class="panel"><div class="row row--between"><div><h2>Profile</h2><p class="sub">${esc(user.email)}</p></div><button class="btn btn--ghost btn--sm" id="logout">${icon("sign-out")}Sign out</button></div>
    <form id="profile-form" novalidate><div class="field"><label for="pn">Name</label><input class="input" id="pn" name="name" value="${esc(user.name)}" autocomplete="name" maxlength="80" required><span class="field-error" data-error-for="name"></span></div>
    <div class="form-error" data-form-error hidden></div><div><button class="btn btn--primary btn--sm" type="submit">Save name</button></div></form></section>

  <section class="panel"><h2>Plan and billing</h2>
    ${sub ? `<div class="plan-card"><div><div class="plan-card__name">${esc(sub.plan.name)} ${sub.cancel_at_period_end ? `<span class="status status--warn">Ending</span>` : sub.status === "past_due" ? `<span class="status status--bad">Payment failed</span>` : `<span class="status">Active</span>`}</div>
      <div class="plan-card__meta">${esc(planLine(sub))}</div></div>
      <div class="row"><a class="btn btn--ghost btn--sm" href="/#pricing">${sub.is_paid ? "Change plan" : "See plans"}</a>
      ${sub.is_paid ? (sub.cancel_at_period_end ? `<button class="btn btn--primary btn--sm" id="resume">Keep my plan</button>` : `<button class="btn btn--danger btn--sm" id="cancel">Cancel plan</button>`) : ""}</div></div>`
      : `<p class="sub">We couldn't load your billing details. Refresh to try again.</p>`}
    <h3 class="h3">Invoices</h3>
    ${invoices.length ? `<div class="table-wrap mt-l"><table class="table"><thead><tr><th>Date</th><th>Description</th><th>Status</th><th class="num">Amount</th></tr></thead><tbody>
      ${invoices.map((i) => `<tr><td>${formatDate(i.created_at)}</td><td>${esc(i.description)}</td><td>${esc(i.status)}</td><td class="num">${money(i.amount_cents, i.currency)}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="muted mt-l">No invoices yet.</p>`}</section>

  <section class="panel"><h2>Form coach history</h2>
    ${sessions && sessions.sessions.length ? `<div class="sess-sum"><div><b>${sessions.summary.sessions}</b><span>Sessions</span></div><div><b>${sessions.summary.reps}</b><span>Total reps</span></div><div><b>${sessions.summary.avg_score}</b><span>Average form</span></div></div>
      <div class="table-wrap"><table class="table"><thead><tr><th>Date</th><th>Lift</th><th class="num">Reps</th><th class="num">Form</th><th>Fix next</th></tr></thead><tbody>
      ${sessions.sessions.slice(0, 10).map((x) => `<tr><td>${formatDate(x.created_at)}</td><td>${esc(({ squat: "Squat", deadlift: "Deadlift", pushup: "Push-up" })[x.exercise] || x.exercise)}</td><td class="num">${x.reps}</td><td class="num">${x.avg_score}</td><td>${esc(Object.entries(x.faults || {}).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k]) => k).join(", ") || "Clean")}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="sub">No sessions yet. Finish a camera coach session while signed in and it appears here. Only rep counts and scores are saved, never video.</p><a class="btn btn--ghost btn--sm" href="/#coach">Open the form coach</a>`}</section>

  <section class="panel"><h2>Password</h2><p class="sub">Changing it signs you out on your other devices.</p>
    <form id="password-form" novalidate>${pwField("cp", "current_password", "Current password", "current-password")}${pwField("np", "new_password", "New password", "new-password")}
    <div class="form-error" data-form-error hidden></div><div><button class="btn btn--primary btn--sm" type="submit">Update password</button></div></form></section>

  <section class="panel"><h2>Your data</h2><p class="sub">Download everything we hold about you, or delete your account.</p>
    <div class="row"><a class="btn btn--ghost btn--sm" href="/api/auth/export" download>${icon("download-simple")}Download my data</a>
    <button class="btn btn--danger btn--sm" id="delete-open">${icon("trash")}Delete my account</button></div></section>`;

  pwToggles(root);
  $("#logout").addEventListener("click", async () => { await api("/api/auth/logout", { method: "POST" }); setUser(null); location.href = "/"; });
  $("#profile-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const res = await submitForm(e.target, (d) => api("/api/auth/me", { method: "PATCH", body: { name: d.name } }), "Name saved.");
    if (res) setUser(res.user);
  });
  $("#password-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const res = await submitForm(form, (d) => api("/api/auth/password", { method: "POST", body: { current_password: d.current_password, new_password: d.new_password } }), "Password updated.");
    if (res) form.reset();
  });
  const act = (id, path, msg) => $(id)?.addEventListener("click", async (e) => {
    setBusy(e.currentTarget, true, "Working");
    try { await api(path, { method: "POST" }); toast(msg); render(); }
    catch (err) { toast(err.message, "error"); setBusy(e.currentTarget, false); }
  });
  act("#cancel", "/api/billing/cancel", "Cancelled. You keep access until the period ends.");
  act("#resume", "/api/billing/resume", "Your plan will renew as normal.");
  $("#delete-open").addEventListener("click", () => $("#delete-dialog").showModal());
}

const del = $("#delete-dialog");
del?.addEventListener("click", (e) => { if (e.target === del || e.target.closest("[data-close]")) del.close(); });
$("#delete-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await submitForm(e.target, (d) => api("/api/auth/me", { method: "DELETE", body: { password: d.password } }));
  if (res) { setUser(null); location.href = "/"; }
});

if (params.get("checkout") === "success") {
  toast("Payment received. Your plan is active.");
  history.replaceState(null, "", "/account");
}
render();
