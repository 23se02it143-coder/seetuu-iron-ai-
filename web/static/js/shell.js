// Loaded on every page: header behaviour, session state, the sign-in dialog and one-off banners.
import { api, ApiError } from "./lib/api.js";
import { $, $$, clearErrors, esc, icon, setBusy, showFieldErrors, showFormError, toast } from "./lib/dom.js";

export const state = { user: null, ready: false };
const listeners = new Set();
export const onUser = (fn) => { listeners.add(fn); if (state.ready) fn(state.user); };

// ---------------------------------------------------------------- header
const header = $("#header");
if (header && !header.classList.contains("header--solid")) {
  const toggle = () => header.classList.toggle("is-scrolled", window.scrollY > 40);
  toggle();
  window.addEventListener("scroll", toggle, { passive: true });
}

const menuBtn = $("#menu-btn");
const mobileNav = $("#mobile-nav");
function setMenu(open) {
  if (!menuBtn || !mobileNav) return;
  mobileNav.hidden = !open;
  menuBtn.setAttribute("aria-expanded", String(open));
  menuBtn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  menuBtn.innerHTML = icon(open ? "x" : "list");
  document.body.style.overflow = open ? "hidden" : "";
}
menuBtn?.addEventListener("click", () => setMenu(mobileNav.hidden));
mobileNav?.addEventListener("click", (e) => { if (e.target.closest("a")) setMenu(false); });
window.addEventListener("keydown", (e) => { if (e.key === "Escape" && mobileNav && !mobileNav.hidden) { setMenu(false); menuBtn.focus(); } });
window.matchMedia("(min-width: 900px)").addEventListener("change", (e) => { if (e.matches) setMenu(false); });

// Highlight the nav link of the section in view (home page only).
if (document.body.dataset.page === "home" && "IntersectionObserver" in window) {
  const links = new Map($$(".nav a").map((a) => [a.getAttribute("href").replace(/^\//, ""), a]));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      links.forEach((a) => a.removeAttribute("aria-current"));
      links.get(`#${entry.target.id}`)?.setAttribute("aria-current", "true");
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  ["mission", "safety", "assessment", "programs", "pricing", "faq"].forEach((id) => { const el = document.getElementById(id); if (el) io.observe(el); });
}

// --------------------------------------------------------------- session
function renderSession() {
  const box = $("[data-session]");
  const user = state.user;
  const signIn = $('[data-open-auth="login"]', box || document);
  $$("[data-account-link]").forEach((n) => n.remove());
  if (signIn) {
    if (user) {
      signIn.hidden = true;
      const account = document.createElement("a");
      account.className = "btn btn--ghost btn--sm";
      account.href = "/account";
      account.dataset.accountLink = "";
      account.textContent = "Account";
      signIn.after(account);
      if (user.role === "admin") {
        const admin = document.createElement("a");
        admin.className = "btn btn--ghost btn--sm";
        admin.href = "/admin";
        admin.dataset.accountLink = "";
        admin.textContent = "Admin";
        account.after(admin);
      }
    } else {
      signIn.hidden = false;
    }
  }
  const mobile = $("[data-mobile-account]");
  if (mobile) mobile.textContent = user ? "Your account" : "Sign in";
  if (mobile && !user) mobile.setAttribute("href", "#auth");
}

export function setUser(user) {
  state.user = user;
  state.ready = true;
  renderSession();
  listeners.forEach((fn) => fn(user));
}

export async function refreshSession() {
  try {
    const data = await api("/api/auth/session");
    setUser(data.user);
  } catch {
    setUser(null);
  }
  return state.user;
}

// ----------------------------------------------------------- auth dialog
const dialog = $("#auth-dialog");
let pendingAuth = null;

const TABS = {
  login: ["Sign in", "Access your plan, invoices and saved assessments."],
  register: ["Create your account", "Free to start. Save assessments and manage your plan."],
  forgot: ["Reset your password", "We'll email you a link to choose a new one."],
};

function setTab(tab) {
  if (!dialog || !TABS[tab]) return;
  $$("[data-auth-form]", dialog).forEach((f) => { f.hidden = f.dataset.authForm !== tab; clearErrors(f); });
  $$("#auth-tabs [data-tab]", dialog).forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  $("#auth-tabs", dialog).hidden = tab === "forgot";
  $("#auth-title").textContent = TABS[tab][0];
  $("#auth-sub").textContent = TABS[tab][1];
}

export function openAuth(tab = "login") {
  if (!dialog) return Promise.resolve(null);
  setTab(tab);
  if (!dialog.open) dialog.showModal();
  setTimeout(() => dialog.querySelector("form:not([hidden]) input")?.focus(), 30);
  return new Promise((resolve) => { pendingAuth = resolve; });
}

/** Resolve with the signed-in user, prompting for sign-in or sign-up when needed. */
export async function ensureUser(tab = "register") {
  if (!state.ready) await refreshSession();
  return state.user || openAuth(tab);
}

dialog?.addEventListener("close", () => {
  if (pendingAuth) { pendingAuth(state.user); pendingAuth = null; }
});
dialog?.addEventListener("click", (e) => {
  if (e.target === dialog || e.target.closest("[data-close]")) dialog.close();
  const tab = e.target.closest("[data-tab]");
  if (tab) setTab(tab.dataset.tab);
  const eye = e.target.closest("[data-toggle-pw]");
  if (eye) {
    const input = eye.parentElement.querySelector("input");
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    eye.innerHTML = icon(show ? "eye-slash" : "eye");
    eye.setAttribute("aria-label", show ? "Hide password" : "Show password");
  }
});
document.addEventListener("click", (e) => {
  const opener = e.target.closest("[data-open-auth]");
  if (opener) { e.preventDefault(); openAuth(opener.dataset.openAuth); }
  if (e.target.closest('[data-mobile-account][href="#auth"]')) { e.preventDefault(); openAuth("login"); }
});

function passwordLevel(pw) {
  if (!pw) return 0;
  let score = 0;
  if (pw.length >= 10) score++;
  if (pw.length >= 14) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
  return Math.max(1, Math.min(4, score));
}
$("#reg-password")?.addEventListener("input", (e) => {
  $(".pwmeter", dialog).dataset.level = String(passwordLevel(e.target.value));
});

dialog?.addEventListener("submit", async (e) => {
  const form = e.target.closest("[data-auth-form]");
  if (!form) return;
  e.preventDefault();
  clearErrors(form);
  const kind = form.dataset.authForm;
  const data = Object.fromEntries(new FormData(form));
  const button = form.querySelector('button[type="submit"]');

  if (kind === "register" && !form.elements.terms.checked) {
    showFieldErrors(form, { terms: "Please accept the terms to continue" });
    return;
  }
  const payloads = {
    login: ["/api/auth/login", { email: data.email, password: data.password }],
    register: ["/api/auth/register", { name: data.name, email: data.email, password: data.password }],
    forgot: ["/api/auth/forgot", { email: data.email }],
  };
  const [url, body] = payloads[kind];
  setBusy(button, true, kind === "forgot" ? "Sending" : "Please wait");
  try {
    const res = await api(url, { method: "POST", body });
    if (kind === "forgot") {
      form.innerHTML = `<div class="success">${icon("check-circle")}<div><b>Check your inbox</b>${esc(res.message)}</div></div>`;
      return;
    }
    setUser(res.user);
    form.reset();
    toast(kind === "register" ? `Welcome, ${res.user.name.split(" ")[0]}.` : "Signed in.");
    dialog.close();
  } catch (err) {
    if (!(err instanceof ApiError)) throw err;
    if (!showFieldErrors(form, err.fields)) showFormError(form, err.message);
    else if (err.fields._) showFormError(form, err.message);
  } finally {
    setBusy(button, false);
  }
});

// -------------------------------------------------- one-off URL messages
function banner(message) {
  const el = document.createElement("div");
  el.className = "banner";
  el.setAttribute("role", "status");
  el.innerHTML = `<span>${esc(message)}</span><button type="button" aria-label="Dismiss">${icon("x")}</button>`;
  el.querySelector("button").addEventListener("click", () => el.remove());
  document.body.append(el);
  setTimeout(() => el.remove(), 9000);
}

(function readUrl() {
  const params = new URLSearchParams(location.search);
  const ref = params.get("ref");
  if (ref && /^[A-Za-z0-9]{4,16}$/.test(ref)) sessionStorage.setItem("ref", ref.toUpperCase());
  for (const key of ["utm_source", "utm_medium", "utm_campaign"]) {
    const v = params.get(key);
    if (v) sessionStorage.setItem(key, v.slice(0, 64));
  }
  const messages = {
    "waitlist=confirmed": "You're confirmed. Thanks for joining the waitlist.",
    "waitlist=unsubscribed": "You've been removed from the waitlist. No more emails from us.",
    "waitlist=invalid": "That link has expired or was already used.",
    "checkout=cancelled": "Checkout cancelled. Nothing was charged.",
  };
  for (const [k, v] of Object.entries(messages)) {
    const [name, value] = k.split("=");
    if (params.get(name) === value) {
      banner(v);
      params.delete(name);
      const q = params.toString();
      history.replaceState(null, "", location.pathname + (q ? `?${q}` : "") + location.hash);
      break;
    }
  }
})();

refreshSession();
