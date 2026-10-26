// Test-mode checkout page (used when PAYMENTS_PROVIDER=mock). No card data is collected and no money moves.
import { state, openAuth, refreshSession } from "../shell.js";
import { api, ApiError } from "../lib/api.js";
import { $, esc, icon, money, setBusy, toast } from "../lib/dom.js";

const root = $("#checkout-root");
const id = location.pathname.split("/").filter(Boolean).pop();

async function load() {
  const user = state.ready ? state.user : await refreshSession();
  if (!user) {
    root.innerHTML = `<section class="panel"><h2>Sign in to continue</h2><p class="sub">Checkout is tied to your account.</p><button class="btn btn--primary" id="signin">Sign in</button></section>`;
    $("#signin").addEventListener("click", async () => { if (await openAuth("login")) load(); });
    return;
  }
  let c;
  try {
    const u = await api(`/api/billing/upi/${encodeURIComponent(id)}`);
    return renderUpi(u);
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 404) {
      root.innerHTML = `<section class="panel"><h2>We couldn't load that checkout</h2><p class="sub">${esc(err.message)}</p><a class="btn btn--ghost" href="/#pricing">Back to plans</a></section>`;
      return;
    }
  }
  try {
    c = await api(`/api/billing/mock/${encodeURIComponent(id)}`);
  } catch (err) {
    root.innerHTML = `<section class="panel"><h2>We couldn't find that checkout</h2><p class="sub">${esc(err.message)}</p><a class="btn btn--ghost" href="/#pricing">Back to plans</a></section>`;
    return;
  }
  if (c.status !== "open") {
    const msg = { complete: "This checkout is already complete.", canceled: "This checkout was cancelled.", expired: "This checkout expired. Start again from the pricing section." }[c.status] || "This checkout is no longer available.";
    root.innerHTML = `<section class="panel"><h2>${esc(msg)}</h2><div class="row mt-l"><a class="btn btn--primary" href="${c.status === "complete" ? "/account" : "/#pricing"}">${c.status === "complete" ? "Go to your account" : "Back to plans"}</a></div></section>`;
    return;
  }
  const per = c.interval === "year" ? "year" : "month";
  root.innerHTML = `
    <section class="summary"><h2>${esc(c.plan.name)} plan</h2>
      <dl><div><dt>Billing</dt><dd>${c.interval === "year" ? "Yearly" : "Monthly"}</dd></div><div><dt>Renews</dt><dd>Every ${per} until cancelled</dd></div>
      <div><dt>Total today</dt><dd class="tnum">${money(c.amount_cents, c.currency)}</dd></div></dl></section>
    <section class="panel"><h2>Confirm</h2>
      <div class="testmode">${icon("info")}<span><b>Test mode.</b> No card is collected and nothing is charged. Confirming activates the plan on your account so you can try the full flow.</span></div>
      <div class="stack mt-l"><button class="btn btn--primary btn--block" id="pay">Confirm ${esc(c.plan.name)} for ${money(c.amount_cents, c.currency)}</button>
      <button class="btn btn--ghost btn--block" id="cancel">Cancel and go back</button></div>
      <p class="form-note mt-l">You can cancel any time from your account. By confirming you agree to the <a class="link" href="/terms" target="_blank">Terms</a>.</p></section>`;
  const finish = async (outcome, btn) => {
    setBusy(btn, true, outcome === "success" ? "Activating" : "Cancelling");
    try {
      await api(`/api/billing/mock/${encodeURIComponent(id)}/complete`, { method: "POST", body: { outcome } });
      location.href = outcome === "success" ? "/account?checkout=success" : "/?checkout=cancelled#pricing";
    } catch (err) {
      setBusy(btn, false);
      toast(err instanceof ApiError ? err.message : "Something went wrong.", "error");
    }
  };
  $("#pay").addEventListener("click", (e) => finish("success", e.currentTarget));
  $("#cancel").addEventListener("click", (e) => finish("cancel", e.currentTarget));
}
// ---- UPI QR checkout (PAYMENTS_PROVIDER=upi): scan / pay, submit the reference, owner approves ----
function renderUpi(c) {
  const per = c.interval === "year" ? "year" : "month";
  const total = money(c.amount_cents, c.currency);
  const summary = `
    <section class="summary"><h2>${esc(c.plan.name)} plan</h2>
      <dl><div><dt>Billing</dt><dd>${c.interval === "year" ? "Yearly" : "Monthly"}</dd></div><div><dt>Period</dt><dd>1 ${per}</dd></div>
      <div><dt>Total today</dt><dd class="tnum">${total}</dd></div></dl></section>`;
  if (c.status === "pending") {
    root.innerHTML = `${summary}<section class="panel"><h2>Payment received - verifying</h2>
      <p class="sub">We have your UPI reference <b>${esc(c.reference || "")}</b>. We are checking it now and will email you as soon as your plan is active (usually within a few hours).</p>
      <div class="row mt-l"><a class="btn btn--primary" href="/account">Go to your account</a></div></section>`;
    return;
  }
  if (c.status !== "open") {
    const msg = { complete: "This checkout is already complete.", canceled: "This checkout was cancelled.", expired: "This checkout expired. Start again from the pricing section." }[c.status] || "This checkout is no longer available.";
    root.innerHTML = `<section class="panel"><h2>${esc(msg)}</h2><div class="row mt-l"><a class="btn btn--primary" href="${c.status === "complete" ? "/account" : "/#pricing"}">${c.status === "complete" ? "Go to your account" : "Back to plans"}</a></div></section>`;
    return;
  }
  root.innerHTML = `${summary}
    <section class="panel upi"><h2>Pay ${total}</h2>
      <div class="upi__qr"><img src="/api/billing/upi/${encodeURIComponent(c.id)}/qr.svg" alt="UPI QR code for ${esc(total)}" width="220" height="220"></div>
      <p class="sub upi__hint">Scan with any UPI app (GPay, PhonePe, Paytm, BHIM). The amount is filled in for you.</p>
      <a class="btn btn--primary btn--block upi__app" href="${esc(c.upi_uri)}">Open my UPI app</a>
      <div class="upi__id"><span>Pay to <b>${esc(c.upi_name)}</b></span><button type="button" class="btn btn--ghost" id="copy-upi">${esc(c.upi_id)} - copy</button></div>
      <form id="upi-form" class="stack mt-l" novalidate>
        <div class="field"><label for="upi-ref">After paying, enter the UPI transaction ID (UTR)</label>
          <input class="input" id="upi-ref" name="reference" type="text" autocomplete="off" maxlength="40" placeholder="e.g. 412345678901" required></div>
        <p class="form-error" id="upi-error" role="alert" hidden></p>
        <button class="btn btn--primary btn--block" id="upi-submit" type="submit">I have paid - verify my payment</button>
      </form>
      ${c.cards_available
        ? `<div class="upi__or"><span>or</span></div><button class="btn btn--ghost btn--block" id="pay-card" type="button">Pay by card / netbanking / wallet</button>`
        : `<p class="form-note mt-l">Card and netbanking payments are coming soon. UPI works with every bank.</p>`}
      <p class="form-note mt-l">Your plan is activated after we confirm the payment. By paying you agree to the <a class="link" href="/terms" target="_blank">Terms</a>.</p>
    </section>`;
  $("#copy-upi").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(c.upi_id); toast("UPI ID copied"); } catch { toast(c.upi_id); }
  });
  $("#upi-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("#upi-submit");
    const err = $("#upi-error");
    err.hidden = true;
    const reference = new FormData(e.currentTarget).get("reference").toString().trim();
    setBusy(btn, true, "Sending");
    try {
      await api(`/api/billing/upi/${encodeURIComponent(c.id)}/submit`, { method: "POST", body: { reference } });
      await load();
    } catch (ex) {
      setBusy(btn, false);
      err.textContent = ex instanceof ApiError ? ex.message : "Something went wrong.";
      err.hidden = false;
    }
  });
  const card = $("#pay-card");
  if (card) card.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    setBusy(btn, true, "Opening");
    try {
      const r = await api(`/api/billing/upi/${encodeURIComponent(c.id)}/card`, { method: "POST" });
      location.href = r.url;
    } catch (ex) {
      setBusy(btn, false);
      toast(ex instanceof ApiError ? ex.message : "Something went wrong.", "error");
    }
  });
}

load();
