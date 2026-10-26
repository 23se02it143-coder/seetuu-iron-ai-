// Small DOM helpers shared by every page.
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

export const icon = (name, cls = "") =>
  `<svg class="icon ${cls}" aria-hidden="true" focusable="false"><use href="/static/img/icons.svg#i-${esc(name)}"></use></svg>`;

export function money(cents, currency = "INR") {
  const amount = cents / 100;
  const whole = Number.isInteger(amount);
  try {
    return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
      style: "currency", currency, minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(whole ? 0 : 2)}`;
  }
}

export function formatDate(iso, opts = { year: "numeric", month: "short", day: "numeric" }) {
  if (!iso) return "";
  return new Intl.DateTimeFormat("en-US", opts).format(new Date(iso));
}

export function toast(message, kind = "ok") {
  const host = $("#toasts");
  if (!host) return;
  const el = document.createElement("div");
  el.className = `toast${kind === "error" ? " toast--error" : ""}`;
  el.textContent = message;
  host.append(el);
  setTimeout(() => el.remove(), kind === "error" ? 7000 : 4500);
}

export function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.innerHTML;
    button.setAttribute("aria-busy", "true");
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${esc(label || "Working")}</span>`;
  } else {
    button.removeAttribute("aria-busy");
    if (button.dataset.label !== undefined) button.innerHTML = button.dataset.label;
  }
}

/** Show server-side field errors next to their inputs. Returns true when something was shown. */
export function showFieldErrors(form, fields = {}) {
  let shown = false;
  $$("[data-error-for]", form).forEach((el) => {
    const msg = fields[el.dataset.errorFor] || "";
    el.textContent = msg;
    el.closest(".field")?.classList.toggle("has-error", Boolean(msg));
    if (msg) shown = true;
  });
  const first = form.querySelector(".has-error input, .has-error textarea, .has-error select");
  first?.focus();
  return shown;
}

export function clearErrors(form) {
  showFieldErrors(form, {});
  const box = $("[data-form-error]", form);
  if (box) { box.hidden = true; box.textContent = ""; }
}

export function showFormError(form, message) {
  const box = $("[data-form-error]", form);
  if (!box) { toast(message, "error"); return; }
  box.textContent = message;
  box.hidden = false;
}

export const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function debounce(fn, wait = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
}
