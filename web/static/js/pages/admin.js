import { state, openAuth, refreshSession } from "../shell.js";
import { api, ApiError } from "../lib/api.js";
import { $, $$, debounce, esc, formatDate, icon, money, setBusy, toast } from "../lib/dom.js";

const root = $("#admin-root");
const tabsEl = $("#admin-tabs");
const TABS = [["overview", "Overview"], ["waitlist", "Waitlist"], ["contacts", "Messages"], ["subscriptions", "Subscriptions"], ["users", "Users"], ["emails", "Emails"], ["content", "Content"]];
let current = (location.hash || "#overview").slice(1);
if (!TABS.some(([k]) => k === current)) current = "overview";

const dt = (iso) => (iso ? formatDate(iso, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "");
const table = (heads, rows, empty = "Nothing here yet.") => rows.length
  ? `<div class="table-wrap"><table class="table"><thead><tr>${heads.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
  : `<div class="empty">${esc(empty)}</div>`;
const statusPill = (s) => `<span class="status ${{ confirmed: "", active: "", handled: "", new: "status--warn", pending: "status--warn", unsubscribed: "status--muted", canceled: "status--muted", past_due: "status--bad", failed: "status--bad", sent: "", logged: "status--muted" }[s] ?? "status--muted"}">${esc(s)}</span>`;

function pager(data, go) {
  const pages = Math.max(1, Math.ceil(data.total / data.per_page));
  return `<div class="pager"><span>${data.total.toLocaleString()} total</span><div class="row">
    <button class="btn btn--ghost btn--sm" data-page="${data.page - 1}" ${data.page <= 1 ? "disabled" : ""}>Previous</button>
    <span>Page ${data.page} of ${pages}</span>
    <button class="btn btn--ghost btn--sm" data-page="${data.page + 1}" ${data.page >= pages ? "disabled" : ""}>Next</button></div></div>`;
}

// ------------------------------------------------------------------ views
async function overview() {
  const d = await api("/api/admin/overview");
  const w = d.waitlist;
  const delta = w.prev_7d ? Math.round(((w.last_7d - w.prev_7d) / w.prev_7d) * 100) : null;
  const max = Math.max(1, ...d.signups_per_day.map((x) => x.count));
  const f = d.funnel_30d;
  const steps = [["Page views", f.page_views], ["Waitlist clicks", f.cta_clicks], ["Assessments started", f.assessments_started], ["Assessments completed", f.assessments_completed], ["Plans selected", f.plans_selected], ["Assistant chats", f.assistant_chats], ["Camera coach sessions", f.coach_sessions || 0], ["Diet plans built", f.diet_plans || 0]];
  const top = Math.max(1, ...steps.map(([, n]) => n));
  root.innerHTML = `
  <div class="tiles">
    <div class="tile"><b>${w.total.toLocaleString()}</b><span>On the waitlist</span><small class="${delta !== null && delta < 0 ? "down" : ""}">${w.last_7d} this week${delta === null ? "" : `, ${delta >= 0 ? "+" : ""}${delta}% vs last`}</small></div>
    <div class="tile"><b>${w.confirmed.toLocaleString()}</b><span>Confirmed</span><small>${w.pending} pending, ${w.referred} referred</small></div>
    <div class="tile"><b>${money(d.subscriptions.mrr_cents)}</b><span>Monthly recurring revenue</span><small>${d.subscriptions.active} active ${d.subscriptions.active === 1 ? "subscription" : "subscriptions"}</small></div>
    <div class="tile"><b>${d.users.toLocaleString()}</b><span>Accounts</span><small>${d.assessments_saved} saved ${d.assessments_saved === 1 ? "assessment" : "assessments"}</small></div>
    <div class="tile"><b>${d.contacts.new}</b><span>New messages</span><small>${d.contacts.total} total</small></div>
  </div>
  <div class="admin__cols">
    <section class="panel"><h2>Waitlist sign-ups, last 14 days</h2>
      <div class="bars" role="img" aria-label="Daily waitlist sign-ups">${d.signups_per_day.map((x) => `<div title="${x.date}: ${x.count}" data-h="${Math.round((x.count / max) * 100)}">${x.count ? `<span>${x.count}</span>` : ""}</div>`).join("")}</div>
      <div class="bars-x"><span>${formatDate(d.signups_per_day[0].date + "T00:00:00Z", { month: "short", day: "numeric" })}</span><span>Today</span></div></section>
    <section class="panel"><h2>Where sign-ups come from</h2>
      ${d.sources.length ? `<div class="funnel">${d.sources.map((s) => `<div><span>${esc(s.source)} <b>${s.count}</b></span></div>`).join("")}</div>` : `<p class="muted">No sign-ups yet.</p>`}
      <h2 class="mt-l">Plans</h2>${Object.keys(d.subscriptions.by_plan).length ? `<div class="pills mt-l">${Object.entries(d.subscriptions.by_plan).map(([k, v]) => `<span class="status status--muted">${esc(k)}: ${v}</span>`).join("")}</div>` : `<p class="muted">No paid subscribers yet.</p>`}</section>
  </div>
  <section class="panel mt-l"><h2>Funnel, last 30 days</h2><div class="funnel">${steps.map(([label, n]) => `<div><span>${label} <b>${n.toLocaleString()}</b></span><div class="bar"><i data-w="${Math.min(100, Math.round((n / top) * 100))}"></i></div></div>`).join("")}</div></section>`;
  $$(".bars div", root).forEach((el) => { el.style.height = `${el.dataset.h}%`; });
  $$(".funnel .bar i", root).forEach((el) => { el.style.width = `${el.dataset.w}%`; });
}

function pagedView({ path, heads, row, filters = "", extraQuery = () => "", empty }) {
  return async () => {
    const st = { page: 1, q: "", status: "" };
    root.innerHTML = `<div class="toolbar">${filters}</div><div id="list"></div>`;
    const load = async () => {
      const qs = new URLSearchParams({ page: st.page, per_page: 25 });
      if (st.q) qs.set("q", st.q);
      if (st.status) qs.set("status", st.status);
      const data = await api(`${path}?${qs}`);
      $("#list").innerHTML = table(heads, data.items.map(row), empty) + pager(data);
      $$("[data-page]", root).forEach((b) => b.addEventListener("click", () => { st.page = Number(b.dataset.page); load(); }));
      $$("[data-mark]", root).forEach((b) => b.addEventListener("click", async () => {
        await api(`/api/admin/contacts/${b.dataset.mark}`, { method: "PATCH", body: { status: b.dataset.to } });
        load();
      }));
    };
    $("#f-q", root)?.addEventListener("input", debounce((e) => { st.q = e.target.value.trim(); st.page = 1; load(); }));
    $("#f-status", root)?.addEventListener("change", (e) => { st.status = e.target.value; st.page = 1; load(); });
    await load();
  };
}

const waitlist = pagedView({
  path: "/api/admin/waitlist",
  heads: ["Email", "Name", "Interest", "Status", "Source", "Joined"],
  filters: `<input class="input" id="f-q" type="search" placeholder="Search email or name" aria-label="Search waitlist">
    <select class="select" id="f-status" aria-label="Filter by status"><option value="">All statuses</option><option value="confirmed">Confirmed</option><option value="pending">Pending</option><option value="unsubscribed">Unsubscribed</option></select>
    <a class="btn btn--ghost btn--sm" href="/api/admin/waitlist.csv" download>${icon("download-simple")}Export CSV</a>`,
  row: (w) => `<tr><td>${esc(w.email)}</td><td>${esc(w.name)}</td><td>${esc(w.interest)}</td><td>${statusPill(w.status)}</td><td>${esc(w.utm_source || w.source || "direct")}</td><td>${dt(w.created_at)}</td></tr>`,
  empty: "No sign-ups match.",
});
const contacts = pagedView({
  path: "/api/admin/contacts",
  heads: ["From", "Topic", "Message", "Status", "Received", ""],
  filters: `<select class="select" id="f-status" aria-label="Filter by status"><option value="">All messages</option><option value="new">New</option><option value="handled">Handled</option></select>`,
  row: (c) => `<tr><td><b>${esc(c.name)}</b><br><a class="link" href="mailto:${esc(c.email)}">${esc(c.email)}</a>${c.company ? `<br><span class="muted">${esc(c.company)}</span>` : ""}</td><td>${esc(c.topic)}</td><td class="cell-msg">${esc(c.message)}</td><td>${statusPill(c.status)}</td><td>${dt(c.created_at)}</td>
    <td><button class="btn btn--ghost btn--sm" data-mark="${c.id}" data-to="${c.status === "new" ? "handled" : "new"}">${c.status === "new" ? "Mark handled" : "Reopen"}</button></td></tr>`,
  empty: "No messages.",
});
const subscriptions = pagedView({
  path: "/api/admin/subscriptions",
  heads: ["Customer", "Plan", "Billing", "Status", "Renews", "Amount"],
  row: (s) => `<tr><td>${esc(s.email)}</td><td>${esc(s.plan)}</td><td>${esc(s.interval)}ly, ${esc(s.provider)}</td><td>${statusPill(s.cancel_at_period_end ? "canceled" : s.status)}</td><td>${formatDate(s.current_period_end)}</td><td class="num">${money(s.amount_cents, s.currency)}</td></tr>`,
  empty: "No subscriptions yet.",
});
const users = pagedView({
  path: "/api/admin/users",
  heads: ["Name", "Email", "Role", "Joined", "Last sign-in"],
  filters: `<input class="input" id="f-q" type="search" placeholder="Search name or email" aria-label="Search users">`,
  row: (u) => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc(u.role)}</td><td>${formatDate(u.created_at)}</td><td>${dt(u.last_login_at)}</td></tr>`,
});

async function emails() {
  const { items } = await api("/api/admin/emails?limit=40");
  root.innerHTML = `<p class="muted mb">Every email the app sends is recorded here. Without SMTP configured, emails are only logged, so you can read them in development.</p>` +
    (items.length ? items.map((m) => `<details class="panel mt-l"><summary><b>${esc(m.subject)}</b> <span class="muted">to ${esc(m.to)}, ${dt(m.created_at)}</span> ${statusPill(m.status)}</summary>
      ${m.error ? `<p class="form-error mt-l">${esc(m.error)}</p>` : ""}<pre class="cell-msg mt-l">${esc(m.body)}</pre></details>`).join("") : `<div class="empty">No emails yet.</div>`);
}

async function content() {
  const [t, f] = await Promise.all([api("/api/admin/testimonials"), api("/api/admin/faqs")]);
  const tCard = (x) => `<div class="editor" data-kind="testimonials" data-id="${x.id}">
      <div class="row"><input class="input" data-f="name" value="${esc(x.name)}" placeholder="Name" aria-label="Name"><input class="input" data-f="role" value="${esc(x.role)}" placeholder="Role" aria-label="Role">
      <select class="select" data-f="rating" aria-label="Rating">${[5, 4, 3, 2, 1].map((n) => `<option ${n === x.rating ? "selected" : ""}>${n}</option>`).join("")}</select></div>
      <textarea class="textarea" data-f="quote" aria-label="Quote">${esc(x.quote)}</textarea>
      <div class="row"><label class="check"><input type="checkbox" data-f="published" ${x.published ? "checked" : ""}><span>Published</span></label>${x.is_sample ? `<span class="status status--warn">Placeholder</span>` : ""}
      <button class="btn btn--primary btn--sm" data-save>Save</button><button class="btn btn--danger btn--sm" data-del>Delete</button></div></div>`;
  const fCard = (x) => `<div class="editor" data-kind="faqs" data-id="${x.id}">
      <input class="input" data-f="question" value="${esc(x.question)}" aria-label="Question"><textarea class="textarea" data-f="answer" aria-label="Answer">${esc(x.answer)}</textarea>
      <div class="row"><label class="check"><input type="checkbox" data-f="published" ${x.published ? "checked" : ""}><span>Published</span></label>
      <input class="input" data-f="sort_order" type="number" min="0" max="9999" value="${x.sort_order}" aria-label="Order"><button class="btn btn--primary btn--sm" data-save>Save</button><button class="btn btn--danger btn--sm" data-del>Delete</button></div></div>`;
  root.innerHTML = `<section class="panel"><div class="row row--between"><h2>Testimonials</h2><button class="btn btn--ghost btn--sm" data-add="testimonials">${icon("plus")}Add testimonial</button></div>
      <p class="sub">Placeholders are shown on the site with a note until you delete them.</p>${t.items.map(tCard).join("") || `<div class="empty">None yet.</div>`}</section>
    <section class="panel mt-l"><div class="row row--between"><h2>FAQ</h2><button class="btn btn--ghost btn--sm" data-add="faqs">${icon("plus")}Add question</button></div>
      <p class="sub">Changes appear on the home page after a refresh.</p>${f.items.map(fCard).join("") || `<div class="empty">None yet.</div>`}</section>`;

}

const readEditor = (box) => {
  const out = {};
  $$("[data-f]", box).forEach((el) => { out[el.dataset.f] = el.type === "checkbox" ? el.checked : el.type === "number" || el.dataset.f === "rating" ? Number(el.value) : el.value; });
  return out;
};

// One delegated listener for the Content tab (registered once, so re-rendering never stacks handlers).
root.addEventListener("click", async (e) => {
  if (current !== "content") return;
  const box = e.target.closest(".editor");
  const add = e.target.closest("[data-add]");
  try {
    if (add) {
      const body = add.dataset.add === "faqs"
        ? { question: "New question", answer: "Write the answer here.", published: false, sort_order: 99 }
        : { name: "Name", role: "", quote: "Write the quote here, at least ten characters.", rating: 5, published: false, sort_order: 99 };
      await api(`/api/admin/${add.dataset.add}`, { method: "POST", body });
      content();
    } else if (box && e.target.closest("[data-save]")) {
      setBusy(e.target.closest("button"), true, "Saving");
      await api(`/api/admin/${box.dataset.kind}/${box.dataset.id}`, { method: "PUT", body: readEditor(box) });
      toast("Saved.");
      content();
    } else if (box && e.target.closest("[data-del]")) {
      if (!confirm("Delete this item?")) return;
      await api(`/api/admin/${box.dataset.kind}/${box.dataset.id}`, { method: "DELETE" });
      content();
    }
  } catch (err) {
    toast(err instanceof ApiError ? Object.values(err.fields || {})[0] || err.message : "Something went wrong.", "error");
    $$("button[aria-busy]", root).forEach((b) => setBusy(b, false));
  }
});

const VIEWS = { overview, waitlist, contacts, subscriptions, users, emails, content };

async function show(key) {
  current = key;
  history.replaceState(null, "", `#${key}`);
  $$("button", tabsEl).forEach((b) => b.setAttribute("aria-selected", String(b.dataset.key === key)));
  root.innerHTML = `<div class="skeleton"></div>`;
  try {
    await VIEWS[key]();
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return denied(err.status);
    root.innerHTML = `<div class="load-error">${esc(err.message || "Couldn't load this section.")}</div>`;
  }
}

function denied(status) {
  root.innerHTML = `<section class="panel"><h2>${status === 401 ? "Sign in with an admin account" : "This account isn't an admin"}</h2>
    <p class="sub">${status === 401 ? "The admin area is only for administrators." : "Sign out and use the admin account instead."}</p>
    <button class="btn btn--primary" id="admin-signin">${status === 401 ? "Sign in" : "Switch account"}</button></section>`;
  $("#admin-signin").addEventListener("click", async () => {
    if (status === 403) { await api("/api/auth/logout", { method: "POST" }); await refreshSession(); }
    const user = await openAuth("login");
    if (user) show(current);
  });
}

tabsEl.innerHTML = TABS.map(([k, label]) => `<button type="button" role="tab" data-key="${k}" aria-selected="false">${label}</button>`).join("");
tabsEl.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) show(b.dataset.key); });
window.addEventListener("hashchange", () => { const k = location.hash.slice(1); if (VIEWS[k] && k !== current) show(k); });
(state.ready ? Promise.resolve() : refreshSession()).then(() => show(current));
