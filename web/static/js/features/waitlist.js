// Waitlist forms (hero + footer): join, show queue position, share referral link.
import { api, ApiError, track } from "../lib/api.js";
import { $, $$, esc, icon, setBusy, toast } from "../lib/dom.js";

async function copy(text, input) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    input?.select();
    document.execCommand?.("copy");
  }
  toast("Link copied.");
}

function renderResult(host, res, compact) {
  if (res.status === "exists") {
    host.innerHTML = `<div class="success">${icon("check-circle")}<div><b>You're already on the list.</b>${
      res.confirmation_required ? "Check your inbox for the confirmation link we just re-sent." : "We've re-sent your referral link. Check your inbox."
    }</div></div>`;
    return;
  }
  const confirm = res.confirmation_required
    ? `<p><b>One more step:</b> confirm your email using the link we just sent. Your spot is held until you do.</p>` : "";
  const share = `<div class="share">
      <label class="sr-only" for="ref-link-${compact ? "a" : "b"}">Your referral link</label>
      <input class="input" id="ref-link-${compact ? "a" : "b"}" readonly value="${esc(res.referral_url)}">
      <button type="button" class="btn btn--light btn--sm" data-copy>${icon("copy")}Copy</button>
    </div>`;
  host.innerHTML = `<div class="joined" tabindex="-1">
      <div class="joined__pos">#${Number(res.position).toLocaleString()}<small>of ${Number(res.total).toLocaleString()} on the list</small></div>
      <p>Each friend who joins with your link moves you up ten places.</p>${confirm}${share}</div>`;
  const input = $("input", host);
  $("[data-copy]", host).addEventListener("click", () => copy(res.referral_url, input));
  host.querySelector(".joined").focus({ preventScroll: true });
}

function bind(form) {
  const scope = form.closest(".hero__cta, .container--narrow") || form.parentElement;
  const errorBox = $("[data-waitlist-error]", scope);
  const resultBox = $("[data-waitlist-result]", scope);
  const button = $('button[type="submit"]', form);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorBox.textContent = "";
    const data = Object.fromEntries(new FormData(form));
    const email = String(data.email || "").trim();
    if (!email) { errorBox.textContent = "Enter your email address."; form.elements.email.focus(); return; }
    setBusy(button, true, "Joining");
    try {
      const res = await api("/api/waitlist", {
        method: "POST",
        body: {
          email,
          name: data.name || "",
          interest: data.interest || "athlete",
          goal: data.goal || "",
          website: data.website || "",
          ref: sessionStorage.getItem("ref") || "",
          source: form.dataset.source || "",
          utm_source: sessionStorage.getItem("utm_source") || "",
          utm_medium: sessionStorage.getItem("utm_medium") || "",
          utm_campaign: sessionStorage.getItem("utm_campaign") || "",
        },
      });
      if (res.position == null && res.status === "joined") {
        resultBox.innerHTML = `<div class="success">${icon("check-circle")}<div><b>You're on the list.</b>Watch your inbox.</div></div>`;
      } else {
        renderResult(resultBox, res, form.dataset.source === "hero");
      }
      window.dispatchEvent(new Event("iron:strike"));
      form.hidden = true;
      $$(".inline-form", scope).forEach((n) => { n.hidden = true; });
      $(".cta__extra", scope)?.setAttribute("hidden", "");
      track("cta_click");
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      errorBox.textContent = err.fields?.email || err.message;
    } finally {
      setBusy(button, false);
    }
  });
}

export function initWaitlist() {
  $$("form[data-waitlist]").forEach(bind);
}
