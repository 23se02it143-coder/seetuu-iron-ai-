// Contact form -> /api/contact
import { api, ApiError } from "../lib/api.js";
import { $, clearErrors, esc, icon, setBusy, showFieldErrors, showFormError } from "../lib/dom.js";

export function initContact() {
  const form = $("#contact-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearErrors(form);
    const btn = $('button[type="submit"]', form);
    const d = Object.fromEntries(new FormData(form));
    setBusy(btn, true, "Sending");
    try {
      await api("/api/contact", { method: "POST", body: {
        name: d.name || "", email: d.email || "", company: d.company || "", topic: d.topic || "other", message: d.message || "", website: d.website || "",
      } });
      form.innerHTML = `<div class="success">${icon("check-circle")}<div><b>Message sent.</b>Thanks, ${esc((d.name || "").split(" ")[0])}. We've emailed you a receipt and will reply within two working days.</div></div>`;
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      if (!showFieldErrors(form, err.fields)) showFormError(form, err.message);
    } finally {
      setBusy(btn, false);
    }
  });
}
